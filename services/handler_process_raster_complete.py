# ============================================================================
# PROCESS RASTER COMPLETE HANDLER (Docker)
# ============================================================================
# STATUS: Services - Consolidated raster handler for Docker worker
# PURPOSE: Single handler that does validate → COG → STAC in one execution
# LAST_REVIEWED: 27 JAN 2026
# F7.18: Integrated with Docker Orchestration Framework (graceful shutdown)
# F7.19: Real-time progress reporting for Workflow Monitor (19 JAN 2026)
# F7.20: Resource metrics tracking (peak memory, CPU) for capacity planning
# V0.8: Internal tiling decision based on file size (24 JAN 2026)
# V0.8.2: Row/column tile naming + metadata.json for disaster recovery (27 JAN 2026)
# ============================================================================
"""
Process Raster Complete - Consolidated Docker Handler.

V0.8 Architecture (24 JAN 2026):
    This handler now handles BOTH single COG and tiled output internally:
    - Files <= raster_tiling_threshold_mb → Single COG (3 phases)
    - Files > raster_tiling_threshold_mb → Tiled output (5 phases)

    The tiling decision is made internally based on the file size passed
    via '_file_size_mb' parameter. This consolidates process_raster_docker
    and process_large_raster_docker into a single workflow.

Single COG Mode (files <= threshold):
    1. Validation (CRS, type detection)
    2. COG creation (reproject + compress)
    3. STAC metadata (catalog registration)

Tiled Mode (files > threshold):
    1. Generate tiling scheme
    2. Extract tiles (tile_r{row}_c{col}.tif naming)
    3. Create COGs for each tile
    4. Create STAC collection (pgSTAC-based, no MosaicJSON)
    5. Write metadata.json for disaster recovery

V0.8.2 Tile Naming (27 JAN 2026):
    Tiles use row/column naming: tile_r0_c0.tif, tile_r0_c1.tif, etc.
    Output folder: silver-cogs/{job_id[:8]}/
    Metadata file: silver-cogs/{job_id[:8]}/metadata.json

Why Consolidated:
    - Docker has no timeout (unlike 10-min Function App limit)
    - Eliminates stage progression overhead
    - Single atomic operation with rollback on failure
    - One job type for all raster sizes

Docker Orchestration Framework (F7.18 - 16 JAN 2026):
    When running in Docker mode, receives DockerTaskContext via _docker_context:
    - Pre-configured CheckpointManager with shutdown awareness
    - Graceful shutdown support (saves checkpoint on SIGTERM)
    - Progress reporting for visibility

Checkpoint/Resume Support:
    - Phase tracking (skip completed phases on resume)
    - Artifact validation (ensure outputs exist before saving checkpoint)
    - Data persistence (pass results between phases on resume)

Exports:
    process_raster_complete: Consolidated handler function
"""

import logging
import re
import time
from typing import Dict, Any, Optional, Callable, List

from util_logger import (
    get_memory_stats,
    get_peak_memory_mb,
    track_peak_memory_to_task,
)

# F7.21: Type-safe result models (25 JAN 2026)
# These are used by validate_raster, create_cog, and extract_stac_metadata
# Services return model_dump() for backward compatibility
from core.models.raster_results import (
    RasterValidationResult,
    COGCreationResult,
    STACCreationResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# PROGRESS REPORTING HELPER (F7.19 - 19 JAN 2026)
# =============================================================================

def _report_progress(
    docker_context,
    percent: float,
    phase: int,
    total_phases: int,
    phase_name: str,
    message: str
) -> None:
    """
    Report progress to task metadata for Workflow Monitor visibility.

    Only reports if docker_context is available (Docker mode).
    Progress data is stored in task.metadata.progress and displayed
    in the Workflow Monitor UI.

    Args:
        docker_context: DockerTaskContext or None
        percent: Progress percentage (0-100)
        phase: Current phase number
        total_phases: Total number of phases in this workflow
        phase_name: Human-readable phase name
        message: Status message to display
    """
    if not docker_context:
        return

    try:
        docker_context.report_progress(
            percent=percent,
            message=f"Phase {phase}/{total_phases}: {phase_name} - {message}"
        )
    except Exception as e:
        # Progress reporting is non-critical - log and continue
        logger.debug(f"Progress report failed (non-critical): {e}")


# =============================================================================
# OVERWRITE LOGIC (28 JAN 2026)
# =============================================================================
# Race-condition-free overwrite using source checksum comparison.
# Replaces async unpublish jobs which caused timing issues.
# =============================================================================

def _compute_source_checksum(container_name: str, blob_name: str) -> str:
    """
    Compute SHA-256 checksum of source blob (Multihash format).

    Args:
        container_name: Source container
        blob_name: Source blob path

    Returns:
        Multihash hex string (e.g., "1220abcd...")
    """
    from infrastructure.blob import BlobRepository
    from utils.checksum import compute_multihash

    blob_repo = BlobRepository.for_zone('bronze')
    source_bytes = blob_repo.read_blob(container_name, blob_name)
    return compute_multihash(source_bytes, log_performance=True)


def _check_overwrite_mode(params: Dict[str, Any], source_checksum: str) -> Dict[str, Any]:
    """
    Determine overwrite action based on source checksum comparison.

    Args:
        params: Task parameters including overwrite flag and client refs
        source_checksum: SHA-256 checksum of source blob

    Returns:
        Dict with:
        - action: 'full_reprocess' | 'metadata_only' | 'no_change'
        - existing_artifact: Artifact or None
        - old_cog_path: str or None (for cleanup if reprocessing)
        - old_cog_container: str or None
        - metadata_changes: dict or None (for metadata-only update)
    """
    from services.artifact_service import ArtifactService

    overwrite = params.get('overwrite', False)
    if not overwrite:
        return {'action': 'full_reprocess', 'existing_artifact': None}

    # Build client_refs for lookup
    client_refs = {
        'dataset_id': params.get('dataset_id'),
        'resource_id': params.get('resource_id'),
        'version_id': params.get('version_id'),
    }

    # Skip if no client refs (non-platform job)
    if not all(client_refs.values()):
        logger.info("Overwrite requested but no client_refs - proceeding with full processing")
        return {'action': 'full_reprocess', 'existing_artifact': None}

    artifact_service = ArtifactService()
    existing = artifact_service.get_by_client_refs('ddh', client_refs)

    if not existing:
        # No existing artifact - normal first-time processing
        logger.info("Overwrite requested but no existing artifact found - full processing")
        return {'action': 'full_reprocess', 'existing_artifact': None}

    # Compare source checksums
    existing_source_checksum = existing.metadata.get('source_checksum')

    if not existing_source_checksum:
        # Old artifact without source_checksum - can't compare, full reprocess
        logger.info(f"Existing artifact {existing.artifact_id} missing source_checksum - full reprocess")
        return {
            'action': 'full_reprocess',
            'existing_artifact': existing,
            'old_cog_path': existing.blob_path,
            'old_cog_container': existing.container,
        }

    if existing_source_checksum == source_checksum:
        # Same source data - check if metadata changed
        metadata_changes = _detect_metadata_changes(params, existing)

        if metadata_changes:
            logger.info(f"Source unchanged, metadata changes detected: {list(metadata_changes.keys())}")
            return {
                'action': 'metadata_only',
                'existing_artifact': existing,
                'metadata_changes': metadata_changes,
            }
        else:
            logger.info("Source and metadata unchanged - no-op")
            return {
                'action': 'no_change',
                'existing_artifact': existing,
            }
    else:
        # Different source data - full reprocess, delete old COG
        logger.info(f"Source checksum changed - full reprocess (old COG will be deleted)")
        return {
            'action': 'full_reprocess',
            'existing_artifact': existing,
            'old_cog_path': existing.blob_path,
            'old_cog_container': existing.container,
        }


def _detect_metadata_changes(params: Dict[str, Any], existing) -> Optional[Dict[str, Any]]:
    """
    Detect which metadata fields changed (title, tags only for now).

    Args:
        params: Task parameters with potential new values
        existing: Existing artifact

    Returns:
        Dict of changes or None if no changes
    """
    changes = {}

    # Title change
    new_title = params.get('title')
    existing_title = existing.metadata.get('title')
    if new_title and new_title != existing_title:
        changes['title'] = new_title

    # Tags change
    new_tags = params.get('tags')
    existing_tags = existing.metadata.get('tags')
    if new_tags and new_tags != existing_tags:
        changes['tags'] = new_tags

    return changes if changes else None


def _handle_metadata_only_update(
    existing_artifact,
    metadata_changes: Dict[str, Any],
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Update only STAC metadata without reprocessing.

    Args:
        existing_artifact: Existing artifact to update
        metadata_changes: Dict of changed metadata fields
        params: Original task parameters

    Returns:
        Result dict compatible with handler return format
    """
    from infrastructure.pgstac_repository import PgStacRepository
    from services.artifact_service import ArtifactService

    logger.info(f"Performing metadata-only update for artifact {existing_artifact.artifact_id}")

    pgstac = PgStacRepository()
    artifact_service = ArtifactService()

    # Update STAC item properties
    stac_updates = {}
    if 'title' in metadata_changes:
        stac_updates['title'] = metadata_changes['title']
    if 'tags' in metadata_changes:
        # STAC uses 'app:tags' for custom properties
        stac_updates['app:tags'] = metadata_changes['tags']

    if stac_updates and existing_artifact.stac_item_id:
        try:
            pgstac.update_item_properties(
                item_id=existing_artifact.stac_item_id,
                collection_id=existing_artifact.stac_collection_id,
                properties_update=stac_updates
            )
            logger.info(f"Updated STAC item {existing_artifact.stac_item_id} properties: {list(stac_updates.keys())}")
        except Exception as e:
            logger.warning(f"STAC update failed (non-fatal): {e}")

    # Update artifact metadata
    artifact_service.update_metadata(existing_artifact.artifact_id, metadata_changes)

    return {
        'success': True,
        'result': {
            'output_mode': 'metadata_only_update',
            'action': 'metadata_only',
            'changes': metadata_changes,
            'artifact_id': str(existing_artifact.artifact_id),
            'cog': {
                'cog_blob': existing_artifact.blob_path,
                'cog_container': existing_artifact.container,
                'note': 'Existing COG unchanged',
            },
            # V0.8 FIX (30 JAN 2026): STAC info in 'stac' dict for catalog lookup
            'stac': {
                'item_id': existing_artifact.stac_item_id,
                'collection_id': existing_artifact.stac_collection_id,
            },
            'note': 'Source data unchanged, metadata updated',
        }
    }


def _handle_no_change(existing_artifact) -> Dict[str, Any]:
    """
    Return result when source and metadata are unchanged.

    Args:
        existing_artifact: Existing artifact

    Returns:
        Result dict compatible with handler return format
    """
    logger.info(f"No changes detected - returning existing artifact {existing_artifact.artifact_id}")

    return {
        'success': True,
        'result': {
            'output_mode': 'no_change',
            'action': 'no_change',
            'artifact_id': str(existing_artifact.artifact_id),
            'cog': {
                'cog_blob': existing_artifact.blob_path,
                'cog_container': existing_artifact.container,
                'note': 'Existing COG unchanged',
            },
            # V0.8 FIX (30 JAN 2026): STAC info in 'stac' dict for catalog lookup
            'stac': {
                'item_id': existing_artifact.stac_item_id,
                'collection_id': existing_artifact.stac_collection_id,
            },
            'note': 'Source data and metadata unchanged - no processing needed',
        }
    }


def _delete_old_cog(container: str, blob_path: str) -> bool:
    """
    Delete old COG blob after successful reprocessing.

    Args:
        container: COG container name
        blob_path: COG blob path

    Returns:
        True if deleted, False if not found or error
    """
    from infrastructure.blob import BlobRepository

    try:
        blob_repo = BlobRepository.for_zone('silver')
        if blob_repo.blob_exists(container, blob_path):
            blob_repo.delete_blob(container, blob_path)
            logger.info(f"🗑️ Deleted old COG: {container}/{blob_path}")
            return True
        else:
            logger.debug(f"Old COG not found (already deleted?): {container}/{blob_path}")
            return False
    except Exception as e:
        logger.warning(f"Failed to delete old COG {container}/{blob_path}: {e}")
        return False


# =============================================================================
# V0.8: TILED WORKFLOW (24 JAN 2026)
# =============================================================================

def _process_raster_tiled(
    params: Dict[str, Any],
    context: Optional[Dict],
    start_time: float
) -> Dict[str, Any]:
    """
    Process large raster with tiled output.

    V0.8 Architecture (25 JAN 2026):
        This is the internal tiled workflow, called when file size exceeds
        raster_tiling_threshold_mb. It produces multiple COG tiles registered in pgSTAC.

        NOTE: MosaicJSON was removed in V0.8 cleanup (25 JAN 2026).
        pgSTAC searches provide OAuth-only mosaic access (see HISTORY 12 NOV 2025).

    Phases:
        1. Generate tiling scheme
        2. Extract tiles
        3. Create COGs for each tile
        4. Create STAC collection (pgSTAC-based)

    This logic is adapted from handler_process_large_raster_complete.py,
    now unified into the single process_raster_docker workflow.
    """
    from datetime import datetime, timezone
    from pathlib import Path

    from config import get_config

    config = get_config()

    blob_name = params.get('blob_name', 'unknown')
    container_name = params.get('container_name', 'unknown')
    task_id = params.get('_task_id')
    job_id = params.get('_job_id', 'unknown')
    file_size_mb = params.get('_file_size_mb')

    # Extract docker_context for progress reporting
    docker_context = params.get('_docker_context')

    logger.info("=" * 70)
    logger.info("PROCESS RASTER COMPLETE - TILED MODE (V0.8)")
    logger.info(f"   Source: {container_name}/{blob_name}")
    if file_size_mb:
        logger.info(f"   File size: {file_size_mb:.1f} MB")
    if task_id:
        logger.info(f"   Task ID: {task_id[:8]}... (checkpoint enabled)")
    logger.info("=" * 70)

    # Initialize checkpoint manager
    checkpoint = None
    task_repo = None
    if task_id:
        try:
            from infrastructure import CheckpointManager
            from infrastructure.factory import RepositoryFactory
            task_repo = RepositoryFactory.create_task_repository()
            checkpoint = CheckpointManager(task_id, task_repo)
            if checkpoint.current_phase > 0:
                logger.info(f"🔄 RESUMING from phase {checkpoint.current_phase}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize CheckpointManager: {e}")

    # Track results from each phase
    tiling_result = {}
    extraction_result = {}
    cog_results = []
    stac_result = {}

    try:
        # =====================================================================
        # PHASE 1: GENERATE TILING SCHEME (0-10%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping tiling scheme (checkpoint)")
            _report_progress(docker_context, 10, 1, 4, "Tiling Scheme", "Skipped (resumed)")
            tiling_result = checkpoint.get_data('tiling_result', {})
        else:
            logger.info("🔄 PHASE 1: Generating tiling scheme...")
            _report_progress(docker_context, 2, 1, 4, "Tiling Scheme", "Calculating tile grid")
            phase1_start = time.time()

            from .tiling_scheme import generate_tiling_scheme

            tiling_params = {
                'container_name': container_name,
                'blob_name': blob_name,
                'tile_size': params.get('tile_size'),
                'overlap': params.get('overlap', 512),
                'output_container': config.storage.silver.cogs,
                'band_names': params.get('band_names'),
                'target_crs': params.get('target_crs') or config.raster.target_crs,
            }

            tiling_response = generate_tiling_scheme(tiling_params)

            if not tiling_response.get('success'):
                logger.error(f"❌ Tiling scheme generation failed: {tiling_response.get('error')}")
                return {
                    "success": False,
                    "error": "TILING_SCHEME_FAILED",
                    "message": tiling_response.get('message', 'Tiling scheme generation failed'),
                    "phase": 1,
                    "phase_name": "tiling_scheme",
                    "output_mode": "tiled",
                }

            tiling_result = tiling_response.get('result', {})
            phase1_duration = time.time() - phase1_start
            tile_count = tiling_result.get('tile_count', 0)

            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.2f}s")
            logger.info(f"   Tile count: {tile_count}")
            logger.info(f"   Grid: {tiling_result.get('grid_dimensions')}")
            _report_progress(docker_context, 10, 1, 4, "Tiling Scheme", f"Complete ({tile_count} tiles)")

            if checkpoint:
                checkpoint.save(phase=1, data={'tiling_result': tiling_result})

        # =====================================================================
        # PHASE 2: EXTRACT TILES (10-20%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(2):
            logger.info("⏭️ PHASE 2: Skipping tile extraction (checkpoint)")
            _report_progress(docker_context, 20, 2, 4, "Extract Tiles", "Skipped (resumed)")
            extraction_result = checkpoint.get_data('extraction_result', {})
        else:
            tile_count = tiling_result.get('tile_count', 0)
            logger.info(f"🔄 PHASE 2: Extracting {tile_count} tiles...")
            _report_progress(docker_context, 12, 2, 4, "Extract Tiles", f"Extracting {tile_count} tiles")
            phase2_start = time.time()

            from .tiling_extraction import extract_tiles

            extraction_params = {
                'container_name': container_name,
                'blob_name': blob_name,
                'tiling_scheme_blob': tiling_result.get('tiling_scheme_blob'),
                'tiling_scheme_container': config.storage.silver.cogs,
                'output_container': config.resolved_intermediate_tiles_container,
                'job_id': job_id,
                'band_names': params.get('band_names') or tiling_result.get('raster_metadata', {}).get('used_band_names'),
            }

            extraction_response = extract_tiles(extraction_params)

            if not extraction_response.get('success'):
                logger.error(f"❌ Tile extraction failed: {extraction_response.get('error')}")
                return {
                    "success": False,
                    "error": "TILE_EXTRACTION_FAILED",
                    "message": extraction_response.get('message', 'Tile extraction failed'),
                    "phase": 2,
                    "phase_name": "extract_tiles",
                    "tiling": tiling_result,
                    "output_mode": "tiled",
                }

            extraction_result = extraction_response.get('result', {})
            phase2_duration = time.time() - phase2_start
            extracted_count = extraction_result.get('tile_count', 0)

            logger.info(f"✅ PHASE 2 complete: {phase2_duration:.2f}s")
            logger.info(f"   Tiles extracted: {extracted_count}")
            _report_progress(docker_context, 20, 2, 4, "Extract Tiles", f"Complete ({extracted_count} tiles)")

            if checkpoint:
                checkpoint.save(phase=2, data={'extraction_result': extraction_result})

        # =====================================================================
        # PHASE 3: CREATE COGS (20-90%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping COG creation (checkpoint)")
            _report_progress(docker_context, 90, 3, 4, "Create COGs", "Skipped (resumed)")
            cog_results = checkpoint.get_data('cog_results', [])
        else:
            tile_blobs = extraction_result.get('tile_blobs', [])
            tile_count = len(tile_blobs)
            source_crs = extraction_result.get('source_crs')
            raster_metadata = extraction_result.get('raster_metadata', {})

            logger.info(f"🔄 PHASE 3: Creating {tile_count} COGs...")
            _report_progress(docker_context, 22, 3, 4, "Create COGs", f"Processing {tile_count} tiles")
            phase3_start = time.time()

            from .raster_cog import create_cog

            # Build raster_type dict from metadata
            raster_type = {
                "detected_type": raster_metadata.get("detected_type", "unknown"),
                "band_count": raster_metadata.get("band_count", 3),
                "data_type": raster_metadata.get("data_type", "uint8"),
                "optimal_cog_settings": {}
            }

            blob_stem = Path(blob_name).stem
            output_folder = params.get('output_folder')
            target_crs = params.get('target_crs') or config.raster.target_crs
            jpeg_quality = params.get('jpeg_quality') or config.raster.cog_jpeg_quality

            cog_results = []
            cog_blobs = []

            for idx, tile_blob in enumerate(tile_blobs):
                # Calculate progress: 22% to 88% over all tiles (Phase 3 ends at 90%)
                tile_progress = 22 + int((idx / tile_count) * 66)
                _report_progress(docker_context, tile_progress, 3, 4, "Create COGs", f"Tile {idx+1}/{tile_count}")
                logger.info(f"   📦 COG {idx+1}/{tile_count}: {tile_blob.split('/')[-1]}")

                # Generate output filename
                tile_filename = tile_blob.split('/')[-1]
                output_filename = tile_filename.replace('.tif', '_cog.tif')
                if output_folder:
                    output_blob_name = f"{output_folder}/{output_filename}"
                else:
                    output_blob_name = output_filename

                cog_params = {
                    'container_name': config.resolved_intermediate_tiles_container,
                    'blob_name': tile_blob,
                    'source_crs': source_crs,
                    'target_crs': target_crs,
                    'raster_type': raster_type,
                    'output_tier': params.get('output_tier', 'analysis'),
                    'output_blob_name': output_blob_name,
                    'output_container': config.storage.silver.cogs,
                    'jpeg_quality': jpeg_quality,
                    'overview_resampling': config.raster.overview_resampling,
                    'reproject_resampling': config.raster.reproject_resampling,
                    'in_memory': False,  # Docker uses disk for large files
                    '_task_id': task_id,  # Pass task_id for disk-based temp file naming
                }

                cog_response = create_cog(cog_params)

                if not cog_response.get('success'):
                    logger.error(f"❌ COG creation failed for tile {idx+1}: {cog_response.get('error')}")
                    return {
                        "success": False,
                        "error": "COG_CREATION_FAILED",
                        "message": f"COG creation failed for tile {idx+1}: {cog_response.get('error')}",
                        "phase": 3,
                        "phase_name": "create_cogs",
                        "tile_index": idx,
                        "tiling": tiling_result,
                        "extraction": extraction_result,
                        "output_mode": "tiled",
                    }

                cog_result = cog_response.get('result', {})
                cog_results.append(cog_result)
                cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
                if cog_blob:
                    cog_blobs.append(cog_blob)

            phase3_duration = time.time() - phase3_start
            cog_count = len(cog_blobs)

            logger.info(f"✅ PHASE 3 complete: {phase3_duration:.2f}s")
            logger.info(f"   COGs created: {cog_count}")
            _report_progress(docker_context, 90, 3, 4, "Create COGs", f"Complete ({cog_count} COGs)")

            if checkpoint:
                checkpoint.save(phase=3, data={
                    'cog_results': cog_results,
                    'cog_blobs': cog_blobs,
                })

        # Get cog_blobs from results if resuming
        if not cog_results:
            cog_blobs = checkpoint.get_data('cog_blobs', []) if checkpoint else []
        else:
            cog_blobs = [r.get('output_blob') or r.get('cog_blob') for r in cog_results if r]

        # =====================================================================
        # PHASE 4: CREATE STAC COLLECTION (90-100%)
        # NOTE: MosaicJSON removed in V0.8 (25 JAN 2026) - pgSTAC searches provide
        # OAuth-only mosaic access without the two-tier auth problem of MosaicJSON.
        # =====================================================================
        if checkpoint and checkpoint.should_skip(4):
            logger.info("⏭️ PHASE 4: Skipping STAC (checkpoint)")
            _report_progress(docker_context, 100, 4, 4, "STAC Registration", "Skipped (resumed)")
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            logger.info("🔄 PHASE 4: Creating STAC collection...")
            _report_progress(docker_context, 92, 4, 4, "STAC Registration", "Registering with catalog")
            phase4_start = time.time()

            from .stac_collection import create_stac_collection

            collection_id = params.get('collection_id')
            blob_stem = Path(blob_name).stem

            stac_params = {
                'collection_id': collection_id,
                'item_id': params.get('item_id') or blob_stem,
                'cog_blobs': cog_blobs,
                'cog_container': config.storage.silver.cogs,
                'title': f"Tiled Raster: {blob_stem}",
                'description': f"Tiled COG collection from {blob_name}",
                # Platform passthrough
                'dataset_id': params.get('dataset_id'),
                'resource_id': params.get('resource_id'),
                'version_id': params.get('version_id'),
                'access_level': params.get('access_level'),
                # BUG-006 FIX (27 JAN 2026): Pass raster_type for TiTiler bidx params
                # Without this, multi-band tiles get 500 errors from TiTiler
                'raster_type': raster_type,
                # Job traceability (02 FEB 2026): Pass job_id for STAC item metadata
                '_job_id': params.get('_job_id'),
                '_job_type': 'process_raster_docker',
            }

            stac_response = create_stac_collection(stac_params)

            if not stac_response.get('success'):
                logger.warning(f"⚠️ STAC creation failed (non-fatal): {stac_response.get('error')}")
                stac_result = {
                    "degraded": True,
                    "error": stac_response.get('error'),
                }
            else:
                stac_result = stac_response.get('result', {})

            phase4_duration = time.time() - phase4_start

            logger.info(f"✅ PHASE 4 complete: {phase4_duration:.2f}s")
            if stac_result.get('collection_id'):
                logger.info(f"   Collection: {stac_result.get('collection_id')}")
            _report_progress(docker_context, 100, 4, 4, "STAC Registration", f"Complete ({phase4_duration:.1f}s)")

            if checkpoint:
                checkpoint.save(phase=4, data={'stac_result': stac_result})

        # =====================================================================
        # SUCCESS - TILED OUTPUT
        # =====================================================================
        total_duration = time.time() - start_time

        logger.info("=" * 70)
        logger.info("✅ PROCESS RASTER COMPLETE (TILED) - SUCCESS")
        logger.info(f"   Total duration: {total_duration:.2f}s ({total_duration/60:.1f} min)")
        logger.info(f"   Tiles: {tiling_result.get('tile_count', 0)}")
        logger.info(f"   COGs: {len(cog_blobs)}")
        if stac_result.get('collection_id'):
            logger.info(f"   STAC: {stac_result.get('collection_id')}")
        logger.info("=" * 70)

        # =====================================================================
        # ARTIFACT REGISTRY (25 JAN 2026 - Updated for pgSTAC-only)
        # =====================================================================
        # NOTE: For tiled jobs, artifacts are not created since there's no single
        # primary output blob. The STAC collection/items provide the discovery
        # mechanism. Artifact registry is used for single-COG outputs only.
        artifact_id = None
        logger.debug("Skipping artifact creation for tiled job (use STAC collection for discovery)")

        # V0.8.16.7: Reset approval state after successful overwrite (10 FEB 2026)
        if params.get('reset_approval') and params.get('asset_id'):
            try:
                from services.asset_service import AssetService
                asset_service = AssetService()
                reset_done = asset_service.reset_approval_for_overwrite(params['asset_id'])
                if reset_done:
                    logger.info(f"Reset approval state to PENDING_REVIEW after successful overwrite")
            except Exception as reset_err:
                logger.warning(f"Failed to reset approval state: {reset_err}")

        return {
            "success": True,
            "result": {
                "output_mode": "tiled",
                "tiling": tiling_result,
                "extraction": extraction_result,
                "cogs": {
                    "count": len(cog_blobs),
                    "blobs": cog_blobs,
                },
                "stac": stac_result,
                "timing": {
                    "total_seconds": round(total_duration, 1),
                    "total_minutes": round(total_duration / 60, 2),
                },
                "artifact_id": artifact_id,
            }
        }

    except Exception as e:
        logger.exception(f"❌ PROCESS RASTER (TILED) FAILED: {e}")
        return {
            "success": False,
            "error": "PROCESSING_FAILED",
            "error_type": type(e).__name__,
            "message": str(e),
            "phase": "unknown",
            "output_mode": "tiled",
            "tiling": tiling_result,
            "extraction": extraction_result,
        }


# =============================================================================
# V0.8.1: MOUNT-BASED TILED WORKFLOW (27 JAN 2026)
# =============================================================================

def _generate_instance_prefix() -> str:
    """
    Generate unique file prefix from Docker instance ID + timestamp.

    This ensures that if multiple Docker instances accidentally pick up the same
    task (e.g., due to Service Bus lock expiry), they write to different paths
    on the mounted storage, preventing file conflicts.

    Returns:
        12-character hex string unique to this processing attempt
    """
    import hashlib
    import os
    from datetime import datetime, timezone

    # Get instance ID (Docker container ID or hostname)
    instance_id = os.environ.get('WEBSITE_INSTANCE_ID', '')
    if not instance_id:
        instance_id = os.environ.get('HOSTNAME', 'unknown')

    # Combine with high-precision timestamp
    timestamp = datetime.now(timezone.utc).isoformat()
    combined = f"{instance_id}_{timestamp}"

    # Hash and truncate for compact unique prefix
    return hashlib.sha256(combined.encode()).hexdigest()[:12]


def _get_mount_paths(job_id: str, config, instance_prefix: Optional[str] = None) -> Dict[str, 'Path']:
    """
    Generate standard mount paths for a job.

    Args:
        job_id: Job identifier (uses first 8 chars for uniqueness)
        config: AppConfig instance
        instance_prefix: Optional unique prefix for this processing instance.
                        If provided, creates isolated directory to prevent conflicts
                        when multiple instances process same job.

    Returns:
        Dict with Path objects for base, source, tiles, cogs directories
    """
    from pathlib import Path

    # Use job_id[:8] + instance_prefix for complete isolation
    if instance_prefix:
        dir_name = f"{job_id[:8]}_{instance_prefix}"
    else:
        dir_name = job_id[:8]

    base = Path(config.raster.etl_mount_path) / dir_name
    return {
        'base': base,
        'source': base / 'source',
        'tiles': base / 'tiles',
        'cogs': base / 'cogs',
        'instance_prefix': instance_prefix,  # Store for reference
    }


def _check_source_on_mount(mount_paths: Dict, expected_size: int) -> Optional['Path']:
    """
    Check if source file exists on mount with correct size (for resume).

    Args:
        mount_paths: Dict from _get_mount_paths()
        expected_size: Expected file size in bytes

    Returns:
        Path to source file if exists and matches size, else None
    """
    from pathlib import Path

    source_dir = mount_paths['source']
    if not source_dir.exists():
        return None

    files = list(source_dir.glob('*'))
    if files and files[0].stat().st_size == expected_size:
        return files[0]
    return None


def _get_completed_cog_indices(job_id: str, blob_repo, container: str) -> set:
    """
    Get set of tile indices that have already been uploaded as COGs.

    Used for resume detection in Phase 4.

    Args:
        job_id: Job identifier
        blob_repo: BlobRepository instance
        container: Silver COGs container name

    Returns:
        Set of tile indices (int) that are already uploaded
    """
    import re

    prefix = f"{job_id[:8]}/"
    try:
        blobs = blob_repo.list_blobs(container, prefix=prefix)
        completed = set()
        for blob in blobs:
            # Parse tile_r{row}_c{col}.tif → (row, col) tuple
            name = blob.get('name', '').split('/')[-1]
            match = re.match(r'tile_r(\d+)_c(\d+)\.tif$', name)
            if match:
                completed.add((int(match.group(1)), int(match.group(2))))
        return completed
    except Exception as e:
        logger.warning(f"⚠️ Failed to list existing COGs: {e}")
        return set()


def _cleanup_mount_for_job(mount_paths: Dict[str, 'Path']) -> None:
    """
    Clean up mount directory for a completed job.

    Args:
        mount_paths: Dict from _get_mount_paths() containing 'base' path
    """
    import shutil

    job_dir = mount_paths.get('base')
    if job_dir and job_dir.exists():
        try:
            shutil.rmtree(job_dir)
            logger.info(f"🧹 Cleaned up mount directory: {job_dir}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cleanup mount: {e}")


def _write_tiled_metadata_json(
    job_id: str,
    params: Dict[str, Any],
    tiling_result: Dict[str, Any],
    cog_blobs: List[str],
    stac_result: Dict[str, Any],
    cogs_container: str,
    blob_repo,
    config,
) -> None:
    """
    Write metadata JSON to blob storage alongside tiled COGs (27 JAN 2026).

    This provides disaster recovery capability - if STAC database is lost,
    the metadata.json contains everything needed to understand and rebuild:
    - Original job parameters (source blob, CRS, etc.)
    - Tiling scheme (grid dimensions, tile specs)
    - List of all COG blobs produced
    - STAC result (collection_id, item_ids, etc.)

    The JSON is written to: {cogs_container}/{job_id[:8]}/metadata.json

    Args:
        job_id: Job identifier
        params: Original job parameters
        tiling_result: Tiling scheme details
        cog_blobs: List of COG blob names
        stac_result: STAC creation result
        cogs_container: Container where COGs are stored
        blob_repo: Blob repository for upload
        config: Application configuration
    """
    import json
    from datetime import datetime, timezone

    try:
        # Build comprehensive metadata
        metadata = {
            "_metadata_version": "1.0",
            "_created_at": datetime.now(timezone.utc).isoformat(),
            "_purpose": "Disaster recovery - rebuild STAC from this if database is lost",

            # Job identification
            "job_id": job_id,
            "job_id_prefix": job_id[:8],

            # Original parameters (sanitized - remove internal fields)
            "parameters": {
                k: v for k, v in params.items()
                if not k.startswith('_') and k not in ['context']
            },

            # Tiling information
            "tiling": {
                "tile_count": tiling_result.get('tile_count'),
                "tile_size_px": tiling_result.get('tile_size'),
                "grid_dimensions": tiling_result.get('grid_dimensions'),
                "cols": tiling_result.get('cols'),
                "rows": tiling_result.get('rows'),
                "raster_metadata": tiling_result.get('raster_metadata', {}),
            },

            # Output COGs
            "cogs": {
                "container": cogs_container,
                "count": len(cog_blobs),
                "blobs": cog_blobs,
            },

            # STAC result (the key recovery data)
            "stac": stac_result,

            # Storage location
            "storage": {
                "account": config.storage.silver.account_name,
                "container": cogs_container,
                "prefix": f"{job_id[:8]}/",
            },
        }

        # Serialize to JSON
        json_content = json.dumps(metadata, indent=2, default=str)

        # Upload to blob storage
        metadata_blob_name = f"{job_id[:8]}/metadata.json"

        blob_repo.upload_blob(
            container_name=cogs_container,
            blob_name=metadata_blob_name,
            data=json_content.encode('utf-8'),
            content_type='application/json',
            overwrite=True,
        )

        logger.info(f"📋 Metadata JSON written: {cogs_container}/{metadata_blob_name}")

    except Exception as e:
        # Non-fatal - log warning but don't fail the job
        logger.warning(f"⚠️ Failed to write metadata JSON (non-fatal): {e}")


def _process_raster_tiled_mount(
    params: Dict[str, Any],
    context: Optional[Dict],
    start_time: float
) -> Dict[str, Any]:
    """
    Process large raster with tiled output using mount-based I/O.

    V0.8.1 Mount Architecture (27 JAN 2026):
        Replaces VSI streaming with simpler mount-based approach:
        1. Download source blob to mount ONCE (survives restart)
        2. Generate tiling scheme from local file (fast)
        3. Extract tiles to mount (sequential disk I/O)
        4. Create COGs and upload with per-tile resumability
        5. Register STAC collection and cleanup

    Resumability:
        - Resubmitting failed job resumes from last incomplete tile
        - Uses blob existence as completion checkpoint
        - Deterministic output paths: silver-cogs/{job_id[:8]}/tile_{N:04d}.tif

    Phases:
        1. Download source to mount (0-10%)
        2. Generate tiling scheme (10-15%)
        3. Extract tiles to mount (15-25%)
        4. Create COGs and upload (25-95%) - RESUMABLE PER-TILE
        5. Register STAC and cleanup (95-100%)

    Args:
        params: Task parameters with blob_name, container_name, _job_id, etc.
        context: Optional context (unused)
        start_time: Start timestamp for timing

    Returns:
        Dict with success status and results
    """
    import os
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path

    import rasterio
    from rasterio.windows import Window

    from config import get_config
    from infrastructure.blob import BlobRepository
    from infrastructure.factory import RepositoryFactory

    config = get_config()

    # Extract parameters
    blob_name = params.get('blob_name', 'unknown')
    container_name = params.get('container_name', 'unknown')
    task_id = params.get('_task_id')
    job_id = params.get('_job_id', 'unknown')
    file_size_mb = params.get('_file_size_mb')
    file_size_bytes = int(file_size_mb * 1024 * 1024) if file_size_mb else 0
    docker_context = params.get('_docker_context')

    # Generate unique instance prefix for mount isolation (V0.8.1 idempotency)
    instance_prefix = _generate_instance_prefix()

    logger.info("=" * 70)
    logger.info("PROCESS RASTER - MOUNT-BASED TILED MODE (V0.8.1)")
    logger.info(f"   Source: {container_name}/{blob_name}")
    if file_size_mb:
        logger.info(f"   File size: {file_size_mb:.1f} MB")
    logger.info(f"   Job ID: {job_id[:16]}...")
    logger.info(f"   Instance prefix: {instance_prefix}")
    logger.info(f"   Mount path: {config.raster.etl_mount_path}")
    logger.info("=" * 70)

    # Initialize repositories
    blob_repo = BlobRepository.for_zone("silver")
    bronze_repo = BlobRepository.for_zone("bronze")

    # Get mount paths with instance isolation
    mount_paths = _get_mount_paths(job_id, config, instance_prefix=instance_prefix)

    # Track results
    tiling_result = {}
    extraction_result = {}
    cog_results = []
    stac_result = {}

    try:
        # =====================================================================
        # PHASE 1: DOWNLOAD SOURCE TO MOUNT (0-10%)
        # =====================================================================
        source_mount_path = None

        # Resume check: source already on mount?
        existing_source = _check_source_on_mount(mount_paths, file_size_bytes)
        if existing_source:
            logger.info("⏭️ PHASE 1: Source already on mount, skipping download")
            _report_progress(docker_context, 10, 1, 5, "Download", "Skipped (resume)")
            source_mount_path = existing_source
        else:
            logger.info("🔄 PHASE 1: Downloading source to mount...")
            _report_progress(docker_context, 2, 1, 5, "Download", f"Streaming {file_size_mb:.0f} MB to mount")
            phase1_start = time.time()

            # Create mount directories
            mount_paths['source'].mkdir(parents=True, exist_ok=True)
            mount_paths['tiles'].mkdir(parents=True, exist_ok=True)
            mount_paths['cogs'].mkdir(parents=True, exist_ok=True)

            # Determine source filename
            source_filename = Path(blob_name).name
            source_mount_path = mount_paths['source'] / source_filename

            # Stream blob to mount
            download_result = bronze_repo.stream_blob_to_mount(
                container=container_name,
                blob_path=blob_name,
                mount_path=str(source_mount_path),
                chunk_size_mb=32,
            )

            if not download_result.get('success'):
                logger.error(f"❌ Failed to download source: {download_result.get('error')}")
                return {
                    "success": False,
                    "error": "DOWNLOAD_FAILED",
                    "message": download_result.get('error', 'Failed to download source to mount'),
                    "phase": 1,
                    "output_mode": "tiled_mount",
                }

            phase1_duration = time.time() - phase1_start
            throughput = download_result.get('throughput_mbps', 0)
            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.1f}s ({throughput:.1f} MB/s)")
            _report_progress(docker_context, 10, 1, 5, "Download", f"Complete ({throughput:.1f} MB/s)")

        # =====================================================================
        # PHASE 2: GENERATE TILING SCHEME (10-15%)
        # =====================================================================
        logger.info("🔄 PHASE 2: Generating tiling scheme from local file...")
        _report_progress(docker_context, 12, 2, 5, "Tiling Scheme", "Analyzing raster")
        phase2_start = time.time()

        # Read raster metadata from local file
        with rasterio.open(str(source_mount_path)) as src:
            source_crs = str(src.crs)
            raster_width = src.width
            raster_height = src.height
            raster_bounds = src.bounds
            raster_transform = src.transform
            band_count = src.count
            dtype = str(src.dtypes[0])
            block_size = src.block_shapes[0] if src.block_shapes else (256, 256)

        # Calculate tile grid
        target_tile_mb = config.raster.raster_tile_target_mb
        # Estimate bytes per pixel (rough: band_count * dtype_bytes)
        dtype_bytes = 4 if 'float' in dtype or '32' in dtype else 1
        bytes_per_pixel = band_count * dtype_bytes
        target_tile_pixels = (target_tile_mb * 1024 * 1024) / bytes_per_pixel
        tile_size = int(target_tile_pixels ** 0.5)  # Square tiles
        tile_size = max(tile_size, 1024)  # Minimum 1024 pixels

        # Calculate grid
        cols = (raster_width + tile_size - 1) // tile_size
        rows = (raster_height + tile_size - 1) // tile_size
        tile_count = cols * rows

        # Build tile specs
        tile_specs = []
        for row in range(rows):
            for col in range(cols):
                tile_index = row * cols + col
                x_off = col * tile_size
                y_off = row * tile_size
                width = min(tile_size, raster_width - x_off)
                height = min(tile_size, raster_height - y_off)

                tile_specs.append({
                    'index': tile_index,
                    'row': row,
                    'col': col,
                    'x_off': x_off,
                    'y_off': y_off,
                    'width': width,
                    'height': height,
                })

        tiling_result = {
            'tile_count': tile_count,
            'tile_size': tile_size,
            'grid_dimensions': f"{cols}x{rows}",
            'cols': cols,
            'rows': rows,
            'tile_specs': tile_specs,
            'raster_metadata': {
                'crs': source_crs,
                'width': raster_width,
                'height': raster_height,
                'bounds': list(raster_bounds),
                'band_count': band_count,
                'dtype': dtype,
            }
        }

        phase2_duration = time.time() - phase2_start
        logger.info(f"✅ PHASE 2 complete: {phase2_duration:.1f}s")
        logger.info(f"   Grid: {cols}x{rows} = {tile_count} tiles")
        logger.info(f"   Tile size: {tile_size}px (~{target_tile_mb}MB target)")
        _report_progress(docker_context, 15, 2, 5, "Tiling Scheme", f"Complete ({tile_count} tiles)")

        # =====================================================================
        # PHASE 3: EXTRACT TILES TO MOUNT (15-25%)
        # =====================================================================
        logger.info(f"🔄 PHASE 3: Extracting {tile_count} tiles to mount...")
        _report_progress(docker_context, 17, 3, 5, "Extract Tiles", f"Processing {tile_count} tiles")
        phase3_start = time.time()

        tile_mount_paths = []

        with rasterio.open(str(source_mount_path)) as src:
            for idx, tile_spec in enumerate(tile_specs):
                # V0.8.2: Row/column naming for clarity (27 JAN 2026)
                tile_path = mount_paths['tiles'] / f"tile_r{tile_spec['row']}_c{tile_spec['col']}.tif"

                # Skip if tile already exists on mount
                if tile_path.exists():
                    tile_mount_paths.append(str(tile_path))
                    continue

                # Extract window
                window = Window(
                    tile_spec['x_off'],
                    tile_spec['y_off'],
                    tile_spec['width'],
                    tile_spec['height']
                )

                # Read data
                data = src.read(window=window)

                # Calculate tile transform
                tile_transform = rasterio.windows.transform(window, src.transform)

                # Write tile
                profile = src.profile.copy()
                profile.update(
                    width=tile_spec['width'],
                    height=tile_spec['height'],
                    transform=tile_transform,
                    driver='GTiff',
                    compress='LZW',  # Light compression for intermediate tiles
                )

                with rasterio.open(str(tile_path), 'w', **profile) as dst:
                    dst.write(data)

                tile_mount_paths.append(str(tile_path))

                # Progress every 10 tiles
                if (idx + 1) % 10 == 0 or idx == tile_count - 1:
                    progress = 15 + int((idx / tile_count) * 10)
                    _report_progress(docker_context, progress, 3, 5, "Extract Tiles", f"Tile {idx+1}/{tile_count}")

        extraction_result = {
            'tile_count': len(tile_mount_paths),
            'tile_mount_paths': tile_mount_paths,
            'source_crs': source_crs,
        }

        phase3_duration = time.time() - phase3_start
        logger.info(f"✅ PHASE 3 complete: {phase3_duration:.1f}s")
        logger.info(f"   Tiles extracted: {len(tile_mount_paths)}")
        _report_progress(docker_context, 25, 3, 5, "Extract Tiles", f"Complete ({len(tile_mount_paths)} tiles)")

        # =====================================================================
        # PHASE 4: CREATE COGS AND UPLOAD - RESUMABLE PER-TILE (25-95%)
        # =====================================================================
        logger.info(f"🔄 PHASE 4: Creating COGs and uploading...")
        _report_progress(docker_context, 27, 4, 5, "Create COGs", "Starting")
        phase4_start = time.time()

        from .raster_cog import create_cog

        # Get already completed COGs for resume
        cogs_container = config.storage.silver.cogs
        completed_indices = _get_completed_cog_indices(job_id, blob_repo, cogs_container)

        if completed_indices:
            logger.info(f"🔄 RESUMING: {len(completed_indices)} COGs already uploaded, skipping...")

        target_crs = params.get('target_crs') or config.raster.target_crs
        cog_blobs = []
        skipped_count = 0

        for idx, tile_path in enumerate(tile_mount_paths):
            # V0.8.2: Parse row/col from filename (27 JAN 2026)
            # Format: tile_r{row}_c{col}.tif
            tile_filename = Path(tile_path).name
            match = re.match(r'tile_r(\d+)_c(\d+)\.tif$', tile_filename)
            if match:
                tile_row = int(match.group(1))
                tile_col = int(match.group(2))
            else:
                # Fallback for old format (shouldn't happen with new tiles)
                logger.warning(f"⚠️ Unexpected tile filename format: {tile_filename}")
                tile_row = idx // 10  # Approximate
                tile_col = idx % 10

            # V0.8.2: Row/column based blob name for clarity
            cog_blob_name = f"{job_id[:8]}/tile_r{tile_row}_c{tile_col}.tif"

            # Resume check: skip if COG already uploaded
            tile_key = (tile_row, tile_col)
            if tile_key in completed_indices:
                cog_blobs.append(cog_blob_name)
                skipped_count += 1
                continue

            # Progress
            progress = 25 + int((idx / tile_count) * 70)
            _report_progress(docker_context, progress, 4, 5, "Create COGs", f"Tile {idx+1}/{tile_count}")
            logger.info(f"   📦 COG {idx+1}/{tile_count}: tile_r{tile_row}_c{tile_col}")

            # Create COG params - use mount path as source
            cog_params = {
                'container_name': None,  # Not from blob
                'blob_name': None,
                '_local_source_path': tile_path,  # Direct local file
                'source_crs': source_crs,
                'target_crs': target_crs,
                'raster_type': {
                    'detected_type': 'raster',
                    'band_count': band_count,
                    'data_type': dtype,
                    'optimal_cog_settings': {},
                },
                'output_tier': params.get('output_tier', 'analysis'),
                'output_blob_name': cog_blob_name,
                'output_container': cogs_container,
                'jpeg_quality': params.get('jpeg_quality') or config.raster.cog_jpeg_quality,
                'overview_resampling': config.raster.overview_resampling,
                'reproject_resampling': config.raster.reproject_resampling,
                'in_memory': False,
                '_task_id': task_id,
            }

            cog_response = create_cog(cog_params)

            if not cog_response.get('success'):
                tile_id = f"r{tile_row}_c{tile_col}"
                logger.error(f"❌ COG creation failed for tile {tile_id}: {cog_response.get('error')}")
                return {
                    "success": False,
                    "error": "COG_CREATION_FAILED",
                    "message": f"COG creation failed for tile {tile_id}: {cog_response.get('error')}",
                    "phase": 4,
                    "tile_row": tile_row,
                    "tile_col": tile_col,
                    "tiles_completed": len(cog_blobs),
                    "tiles_total": tile_count,
                    "resumable": True,
                    "output_mode": "tiled_mount",
                }

            cog_result = cog_response.get('result', {})
            cog_results.append(cog_result)
            # Use actual blob name from COG result (may include tier suffix)
            # V0.8.2: Now uses row/col naming (e.g., tile_r0_c1.tif)
            actual_cog_blob = cog_result.get('cog_blob') or cog_blob_name
            cog_blobs.append(actual_cog_blob)

            # Delete tile from mount after successful COG upload (cleanup as we go)
            try:
                Path(tile_path).unlink()
            except Exception as e:
                logger.warning(f"⚠️ Failed to delete tile {tile_path}: {e}")

            # Graceful shutdown check
            if docker_context and docker_context.should_stop():
                logger.warning(f"🛑 Shutdown requested at tile {idx+1}/{tile_count}")
                return {
                    "success": True,
                    "interrupted": True,
                    "resumable": True,
                    "tiles_completed": len(cog_blobs),
                    "tiles_total": tile_count,
                    "output_mode": "tiled_mount",
                }

        phase4_duration = time.time() - phase4_start
        logger.info(f"✅ PHASE 4 complete: {phase4_duration:.1f}s")
        logger.info(f"   COGs created: {len(cog_blobs)} (skipped {skipped_count} on resume)")
        _report_progress(docker_context, 95, 4, 5, "Create COGs", f"Complete ({len(cog_blobs)} COGs)")

        # =====================================================================
        # PHASE 5: REGISTER STAC AND CLEANUP (95-100%)
        # =====================================================================
        logger.info("🔄 PHASE 5: Registering STAC collection...")
        _report_progress(docker_context, 97, 5, 5, "STAC + Cleanup", "Registering")
        phase5_start = time.time()

        from .stac_collection import create_stac_collection

        collection_id = params.get('collection_id')
        blob_stem = Path(blob_name).stem

        # Build raster_type from tiling metadata for TiTiler bidx params (02 FEB 2026)
        raster_metadata = tiling_result.get('raster_metadata', {})
        raster_type = {
            'detected_type': 'raster',
            'band_count': raster_metadata.get('band_count', 3),
            'data_type': raster_metadata.get('dtype', 'uint8'),
        }

        stac_params = {
            'collection_id': collection_id,
            'item_id': params.get('item_id') or blob_stem,
            'cog_blobs': cog_blobs,
            'cog_container': cogs_container,
            'title': f"Tiled Raster: {blob_stem}",
            'description': f"Tiled COG collection from {blob_name} (mount-based workflow)",
            'dataset_id': params.get('dataset_id'),
            'resource_id': params.get('resource_id'),
            'version_id': params.get('version_id'),
            'access_level': params.get('access_level'),
            # BUG-006 FIX (02 FEB 2026): Pass raster_type for TiTiler bidx params
            'raster_type': raster_type,
            # Job traceability (02 FEB 2026): Pass job_id for STAC item metadata
            '_job_id': params.get('_job_id'),
            '_job_type': 'process_raster_docker',
        }

        stac_response = create_stac_collection(stac_params)

        if not stac_response.get('success'):
            logger.warning(f"⚠️ STAC creation failed (non-fatal): {stac_response.get('error')}")
            stac_result = {"degraded": True, "error": stac_response.get('error')}
        else:
            stac_result = stac_response.get('result', {})

        # V0.8.2: Write metadata JSON to blob storage (27 JAN 2026)
        # This provides disaster recovery if STAC is lost - we can rebuild from this
        _write_tiled_metadata_json(
            job_id=job_id,
            params=params,
            tiling_result=tiling_result,
            cog_blobs=cog_blobs,
            stac_result=stac_result,
            cogs_container=cogs_container,
            blob_repo=blob_repo,
            config=config,
        )

        # Cleanup mount directory (uses instance-specific path)
        logger.info("🧹 Cleaning up mount...")
        _cleanup_mount_for_job(mount_paths)

        phase5_duration = time.time() - phase5_start
        logger.info(f"✅ PHASE 5 complete: {phase5_duration:.1f}s")
        _report_progress(docker_context, 100, 5, 5, "STAC + Cleanup", "Complete")

        # =====================================================================
        # SUCCESS
        # =====================================================================
        total_duration = time.time() - start_time

        logger.info("=" * 70)
        logger.info("✅ PROCESS RASTER (MOUNT-BASED TILED) - SUCCESS")
        logger.info(f"   Total duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")
        logger.info(f"   Tiles: {tile_count}")
        logger.info(f"   COGs: {len(cog_blobs)}")
        if stac_result.get('collection_id'):
            logger.info(f"   STAC: {stac_result.get('collection_id')}")
        logger.info("=" * 70)

        # V0.8.16.7: Reset approval state after successful overwrite (10 FEB 2026)
        if params.get('reset_approval') and params.get('asset_id'):
            try:
                from services.asset_service import AssetService
                asset_service = AssetService()
                reset_done = asset_service.reset_approval_for_overwrite(params['asset_id'])
                if reset_done:
                    logger.info(f"Reset approval state to PENDING_REVIEW after successful overwrite")
            except Exception as reset_err:
                logger.warning(f"Failed to reset approval state: {reset_err}")

        return {
            "success": True,
            "result": {
                "output_mode": "tiled_mount",
                "tiling": tiling_result,
                "extraction": extraction_result,
                "cogs": {
                    "count": len(cog_blobs),
                    "blobs": cog_blobs,
                },
                "stac": stac_result,
                "timing": {
                    "total_seconds": round(total_duration, 1),
                    "total_minutes": round(total_duration / 60, 2),
                },
            }
        }

    except Exception as e:
        logger.exception(f"❌ PROCESS RASTER (MOUNT-BASED TILED) FAILED: {e}")
        return {
            "success": False,
            "error": "PROCESSING_FAILED",
            "error_type": type(e).__name__,
            "message": str(e),
            "phase": "unknown",
            "output_mode": "tiled_mount",
            "tiling": tiling_result,
            "extraction": extraction_result,
            "resumable": True,
        }


def process_raster_complete(params: Dict[str, Any], context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Complete raster processing in single execution.

    V0.8 Architecture (24 JAN 2026):
        This handler decides internally whether to produce single COG or tiled output
        based on file size vs raster_tiling_threshold_mb config.

    Args:
        params: Task parameters with:
            - _task_id: Task ID for checkpoint tracking (optional but recommended)
            - _file_size_mb: File size in MB (from pre-flight validation)
            - blob_url: Azure blob URL with SAS token
            - blob_name: Source blob path
            - container_name: Source container
            - input_crs: Optional source CRS override
            - target_crs: Target CRS for reprojection
            - raster_type: 'auto', 'rgb', 'rgba', 'dem', etc.
            - output_blob_name: COG output path
            - output_tier: 'visualization', 'analysis', 'archive'
            - collection_id: STAC collection
            - item_id: Optional STAC item ID
            - use_windowed_read: Enable chunked processing for large files
            - chunk_size_mb: Window size for chunked processing
            - tile_size: (tiled mode) Tile size in pixels
            - overlap: (tiled mode) Tile overlap in pixels
            - band_names: (tiled mode) Band mapping for extraction
        context: Optional context (not used in Docker mode)

    Returns:
        dict: Combined result with validation, cog, and stac sections

    Output Mode:
        If _file_size_mb <= raster_tiling_threshold_mb (or not provided):
            Single COG output (3 phases: validate → COG → STAC)
        If _file_size_mb > raster_tiling_threshold_mb:
            Tiled output (4 phases: tiling → extract → COGs → STAC)
    """
    start_time = time.time()

    blob_name = params.get('blob_name', 'unknown')
    container_name = params.get('container_name', 'unknown')
    task_id = params.get('_task_id')
    job_id = params.get('_job_id', 'unknown')
    file_size_mb = params.get('_file_size_mb')

    # V0.8: Determine output mode based on file size (24 JAN 2026)
    from config import get_config
    config = get_config()
    tiling_threshold_mb = config.raster.raster_tiling_threshold_mb

    use_tiling = False
    if file_size_mb is not None and file_size_mb > tiling_threshold_mb:
        use_tiling = True

    logger.info("=" * 70)
    logger.info("PROCESS RASTER COMPLETE - Docker Handler (V0.8)")
    logger.info(f"   Source: {container_name}/{blob_name}")
    if file_size_mb:
        logger.info(f"   File size: {file_size_mb:.1f} MB (threshold: {tiling_threshold_mb} MB)")
    logger.info(f"   Output mode: {'TILED' if use_tiling else 'SINGLE_COG'}")
    if task_id:
        logger.info(f"   Task ID: {task_id[:8]}... (checkpoint enabled)")
    logger.info("=" * 70)

    # V0.8: Route to tiled workflow if file exceeds threshold
    # V0.8.1: Use mount-based workflow when ETL mount available (27 JAN 2026)
    if use_tiling:
        if config.raster.use_etl_mount:
            logger.info("📦 Routing to MOUNT-BASED tiled workflow (V0.8.1)...")
            return _process_raster_tiled_mount(params, context, start_time)
        else:
            logger.info("📦 Routing to VSI-based tiled workflow (fallback)...")
            return _process_raster_tiled(params, context, start_time)

    # =========================================================================
    # SOURCE CHECKSUM & OVERWRITE CHECK (28 JAN 2026)
    # =========================================================================
    # Compute source checksum for platform jobs (needed for overwrite comparison)
    # If overwrite=true, compare with existing artifact to determine action
    overwrite_result = None
    source_checksum = None

    # Determine if this is a platform job (has client_refs)
    is_platform_job = all([
        params.get('dataset_id'),
        params.get('resource_id'),
        params.get('version_id'),
    ])

    # Compute source checksum for platform jobs (enables future overwrite comparison)
    if is_platform_job:
        try:
            logger.info("📦 Computing source checksum (for artifact tracking)...")
            source_checksum = _compute_source_checksum(container_name, blob_name)
            logger.info(f"   Source checksum: {source_checksum[:24]}...")

            # =====================================================================
            # V0.8.16: Asset linking moved to CoreMachine factory (09 FEB 2026)
            # =====================================================================
            # Asset linking (current_job_id, content_hash) is now handled by the
            # CoreMachine factory on job completion using job.asset_id.
            # Tasks don't need asset awareness - they just execute work.
            # See: core/machine_factory.py lines 221-264
            # =====================================================================

        except Exception as e:
            logger.warning(f"Source checksum computation failed (non-fatal): {e}")
            source_checksum = None

    # If overwrite=true, check if we can skip processing
    if params.get('overwrite', False) and source_checksum:
        logger.info("🔄 OVERWRITE MODE: Checking for changes...")
        try:
            overwrite_result = _check_overwrite_mode(params, source_checksum)
            logger.info(f"   Overwrite action: {overwrite_result['action']}")

            # Handle no_change case - return immediately
            if overwrite_result['action'] == 'no_change':
                return _handle_no_change(overwrite_result['existing_artifact'])

            # Handle metadata_only case - update and return
            if overwrite_result['action'] == 'metadata_only':
                return _handle_metadata_only_update(
                    overwrite_result['existing_artifact'],
                    overwrite_result['metadata_changes'],
                    params
                )

            # full_reprocess continues with normal processing below

        except Exception as e:
            logger.warning(f"Overwrite check failed (proceeding with full processing): {e}")
            overwrite_result = {'action': 'full_reprocess', 'existing_artifact': None}

    # Initialize checkpoint manager
    # F7.18: Use DockerTaskContext if available (Docker mode)
    # Otherwise fall back to manual creation (Function App mode)
    docker_context = params.get('_docker_context')
    checkpoint = None

    if docker_context:
        # Docker mode: use pre-configured checkpoint from context
        checkpoint = docker_context.checkpoint
        if checkpoint.current_phase > 0:
            logger.info(f"🔄 RESUMING from phase {checkpoint.current_phase}")
    elif task_id:
        # Function App mode: create checkpoint manually
        try:
            from infrastructure import CheckpointManager
            from infrastructure.factory import RepositoryFactory
            task_repo = RepositoryFactory.create_task_repository()
            checkpoint = CheckpointManager(task_id, task_repo)
            if checkpoint.current_phase > 0:
                logger.info(f"🔄 RESUMING from phase {checkpoint.current_phase}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize CheckpointManager: {e}")
            checkpoint = None

    # Track results from each phase
    validation_result = {}
    cog_result = {}
    stac_result = {}

    # Track timing (may be partial on resume)
    phase1_duration = 0.0
    phase2_duration = 0.0
    phase3_duration = 0.0

    # F7.20: Resource tracking for Docker jobs (19 JAN 2026)
    # Captures initial/peak/final memory + CPU for capacity planning
    resource_stats = {
        "initial": get_memory_stats() or {},
        "peak_memory_mb": None,
        "peak_memory_phase": None,
        "final": None,
    }
    task_repo = docker_context.task_repo if docker_context else None

    try:
        # =====================================================================
        # PHASE 1: VALIDATION (0-20%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping validation (already completed)")
            _report_progress(docker_context, 20, 1, 3, "Validation", "Skipped (resumed)")
            # Restore validation result from checkpoint
            validation_result = checkpoint.get_data('validation_result', {})
            source_crs = checkpoint.get_data('source_crs')
            if not source_crs:
                logger.error("❌ Resume error: No source_crs in checkpoint data")
                return {
                    "success": False,
                    "error": "CHECKPOINT_MISSING_DATA",
                    "message": "Checkpoint missing source_crs from phase 1",
                    "phase": "resume_validation",
                }
        else:
            logger.info("🔄 PHASE 1: Validating raster...")
            _report_progress(docker_context, 5, 1, 3, "Validation", "Starting validation")
            phase1_start = time.time()

            from .raster_validation import validate_raster

            validation_params = {
                'blob_url': params.get('blob_url'),
                'blob_name': blob_name,
                'container_name': container_name,
                'input_crs': params.get('input_crs'),
                'raster_type': params.get('raster_type', 'auto'),
                'strict_mode': params.get('strict_mode', False),
            }

            validation_response = validate_raster(validation_params)

            if not validation_response.get('success'):
                logger.error(f"❌ Validation failed: {validation_response.get('error')}")
                return {
                    "success": False,
                    "error": "VALIDATION_FAILED",
                    "message": validation_response.get('message', 'Validation failed'),
                    "phase": "validation",
                    "validation": validation_response,
                }

            validation_result = validation_response.get('result', {})
            source_crs = validation_result.get('source_crs')

            if not source_crs:
                logger.error("❌ No source_crs in validation results")
                return {
                    "success": False,
                    "error": "NO_SOURCE_CRS",
                    "message": "Validation did not return source CRS",
                    "phase": "validation",
                    "validation": validation_result,
                }

            phase1_duration = time.time() - phase1_start
            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.2f}s")
            logger.info(f"   Source CRS: {source_crs}")
            logger.info(f"   Raster type: {validation_result.get('raster_type', {}).get('detected_type')}")
            _report_progress(docker_context, 20, 1, 3, "Validation", f"Complete ({phase1_duration:.1f}s)")

            # Save checkpoint after phase 1
            if checkpoint:
                checkpoint.save(
                    phase=1,
                    data={
                        'source_crs': source_crs,
                        'validation_result': validation_result,
                    }
                )

        # F7.18: Check for graceful shutdown before Phase 2
        if docker_context and docker_context.should_stop():
            logger.warning("=" * 70)
            logger.warning("🛑 GRACEFUL SHUTDOWN - Handler Interrupted")
            logger.warning(f"   Task ID: {task_id[:16] if task_id else 'unknown'}...")
            logger.warning(f"   Phase completed: 1 (validation)")
            logger.warning(f"   Phase skipped: 2 (COG creation), 3 (STAC)")
            logger.warning(f"   Source CRS saved: {source_crs}")
            logger.warning("   Returning interrupted=True for message abandonment")
            logger.warning("=" * 70)
            return {
                "success": True,
                "interrupted": True,
                "resumable": True,
                "phase_completed": 1,
                "message": "Graceful shutdown after validation phase",
            }

        # =====================================================================
        # PHASE 2: COG CREATION (20-80%)
        # =====================================================================
        from config import get_config
        config = get_config()

        if checkpoint and checkpoint.should_skip(2):
            logger.info("⏭️ PHASE 2: Skipping COG creation (already completed)")
            _report_progress(docker_context, 80, 2, 3, "COG Creation", "Skipped (resumed)")
            # Restore COG result from checkpoint
            cog_result = checkpoint.get_data('cog_result', {})
            cog_blob = checkpoint.get_data('cog_blob')
            cog_container = checkpoint.get_data('cog_container') or config.storage.silver.cogs
            if not cog_blob:
                logger.error("❌ Resume error: No cog_blob in checkpoint data")
                return {
                    "success": False,
                    "error": "CHECKPOINT_MISSING_DATA",
                    "message": "Checkpoint missing cog_blob from phase 2",
                    "phase": "resume_cog",
                }
        else:
            logger.info("🔄 PHASE 2: Creating COG...")
            _report_progress(docker_context, 25, 2, 3, "COG Creation", "Starting COG conversion")
            phase2_start = time.time()

            from .raster_cog import create_cog

            cog_params = {
                'blob_name': blob_name,
                'container_name': container_name,
                'source_crs': source_crs,
                'target_crs': params.get('target_crs') or config.raster.target_crs,
                'raster_type': validation_result.get('raster_type', {}),
                'output_blob_name': params.get('output_blob_name'),
                'output_tier': params.get('output_tier', 'analysis'),
                'jpeg_quality': params.get('jpeg_quality') or config.raster.cog_jpeg_quality,
                'overview_resampling': params.get('overview_resampling') or config.raster.overview_resampling,
                'reproject_resampling': params.get('reproject_resampling') or config.raster.reproject_resampling,
                'in_memory': False,  # Docker uses disk for large files
                '_task_id': task_id,  # Pass task_id for disk-based temp file naming
            }

            # F7.20: Track peak memory during COG creation (memory-intensive phase)
            if task_id and task_repo:
                with track_peak_memory_to_task(
                    task_id=task_id,
                    task_repo=task_repo,
                    logger=logger,
                    poll_interval=10.0,  # Poll every 10 seconds
                    operation_name="cog_creation"
                ) as mem_stats:
                    cog_response = create_cog(cog_params)
                # Capture peak memory from this phase
                resource_stats["peak_memory_mb"] = mem_stats.get("peak_memory_mb")
                resource_stats["peak_memory_phase"] = "cog_creation"
                resource_stats["cog_polls"] = mem_stats.get("poll_count", 0)
            else:
                cog_response = create_cog(cog_params)

            if not cog_response.get('success'):
                logger.error(f"❌ COG creation failed: {cog_response.get('error')}")
                return {
                    "success": False,
                    "error": "COG_CREATION_FAILED",
                    "message": cog_response.get('message', 'COG creation failed'),
                    "phase": "cog_creation",
                    "validation": validation_result,
                    "cog": cog_response,
                }

            cog_result = cog_response.get('result', {})
            cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
            cog_container = cog_result.get('cog_container') or config.storage.silver.cogs

            if not cog_blob:
                logger.error("❌ COG creation did not return output blob path")
                return {
                    "success": False,
                    "error": "NO_COG_OUTPUT",
                    "message": "COG creation did not return output blob path",
                    "phase": "cog_creation",
                    "validation": validation_result,
                    "cog": cog_result,
                }

            phase2_duration = time.time() - phase2_start
            cog_size_mb = cog_result.get('size_mb', 0)
            logger.info(f"✅ PHASE 2 complete: {phase2_duration:.2f}s")
            logger.info(f"   COG blob: {cog_blob}")
            logger.info(f"   Size: {cog_size_mb:.1f} MB")
            _report_progress(
                docker_context, 80, 2, 3, "COG Creation",
                f"Complete ({phase2_duration:.1f}s, {cog_size_mb:.1f} MB)"
            )

            # Save checkpoint after phase 2 with artifact validation
            if checkpoint:
                from infrastructure.blob import BlobRepository

                def validate_cog_exists():
                    """Validate COG blob exists before saving checkpoint."""
                    try:
                        blob_repo = BlobRepository.for_zone('silver')
                        return blob_repo.blob_exists(cog_container, cog_blob)
                    except Exception as e:
                        logger.warning(f"COG validation failed: {e}")
                        return False

                checkpoint.save(
                    phase=2,
                    data={
                        'cog_blob': cog_blob,
                        'cog_container': cog_container,
                        'cog_result': cog_result,
                    },
                    validate_artifact=validate_cog_exists
                )

        # F7.18: Check for graceful shutdown before Phase 3
        if docker_context and docker_context.should_stop():
            logger.warning("=" * 70)
            logger.warning("🛑 GRACEFUL SHUTDOWN - Handler Interrupted")
            logger.warning(f"   Task ID: {task_id[:16] if task_id else 'unknown'}...")
            logger.warning(f"   Phase completed: 2 (COG creation)")
            logger.warning(f"   Phase skipped: 3 (STAC metadata)")
            logger.warning(f"   COG blob saved: {cog_blob}")
            logger.warning(f"   COG container: {cog_container}")
            logger.warning("   Returning interrupted=True for message abandonment")
            logger.warning("=" * 70)
            return {
                "success": True,
                "interrupted": True,
                "resumable": True,
                "phase_completed": 2,
                "message": "Graceful shutdown after COG creation phase",
                "cog_blob": cog_blob,
                "cog_container": cog_container,
            }

        # =====================================================================
        # PHASE 3: STAC METADATA (80-100%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping STAC metadata (already completed)")
            _report_progress(docker_context, 100, 3, 3, "STAC Registration", "Skipped (resumed)")
            # Restore STAC result from checkpoint
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            logger.info("🔄 PHASE 3: Creating STAC metadata...")
            _report_progress(docker_context, 85, 3, 3, "STAC Registration", "Registering with catalog")
            phase3_start = time.time()

            from .stac_catalog import extract_stac_metadata

            stac_params = {
                'container_name': cog_container,
                'blob_name': cog_blob,
                'collection_id': params.get('collection_id') or config.raster.stac_default_collection,
                # 30 JAN 2026: Use stac_item_id from Platform (DDH format) if available
                'item_id': params.get('stac_item_id') or params.get('item_id'),
                # Platform passthrough
                'dataset_id': params.get('dataset_id'),
                'resource_id': params.get('resource_id'),
                'version_id': params.get('version_id'),
                'access_level': params.get('access_level'),
                # Raster type for visualization
                'raster_type': cog_result.get('raster_type'),
                # STAC file extension: checksum and size (21 JAN 2026)
                'file_checksum': cog_result.get('file_checksum'),
                'file_size': cog_result.get('file_size'),
            }

            stac_response = extract_stac_metadata(stac_params)

            if not stac_response.get('success'):
                # STAC failure is non-fatal - COG was created successfully
                logger.warning(f"⚠️ STAC creation failed (non-fatal): {stac_response.get('error')}")
                stac_result = {
                    "degraded": True,
                    "error": stac_response.get('error'),
                    "message": stac_response.get('message', 'STAC creation failed'),
                }
            else:
                stac_result = stac_response.get('result', {})

            phase3_duration = time.time() - phase3_start
            logger.info(f"✅ PHASE 3 complete: {phase3_duration:.2f}s")
            if stac_result.get('item_id'):
                logger.info(f"   STAC item: {stac_result.get('item_id')}")
            _report_progress(docker_context, 100, 3, 3, "STAC Registration", f"Complete ({phase3_duration:.1f}s)")

            # Save checkpoint after phase 3 (all phases complete)
            if checkpoint:
                checkpoint.save(
                    phase=3,
                    data={
                        'stac_result': stac_result,
                    }
                )

        # =====================================================================
        # SUCCESS
        # =====================================================================
        total_duration = time.time() - start_time

        # Determine if this was a resumed execution
        resumed_from_phase = checkpoint.current_phase if checkpoint and checkpoint.current_phase > 0 else None
        phases_skipped = []
        if resumed_from_phase:
            if resumed_from_phase >= 1:
                phases_skipped.append("validation")
            if resumed_from_phase >= 2:
                phases_skipped.append("cog_creation")
            if resumed_from_phase >= 3:
                phases_skipped.append("stac_metadata")

        # F7.20: Capture final resource stats
        resource_stats["final"] = get_memory_stats() or {}
        resource_stats["peak_memory_overall_mb"] = get_peak_memory_mb()

        logger.info("=" * 70)
        logger.info("✅ PROCESS RASTER COMPLETE (SINGLE COG) - SUCCESS")
        if resumed_from_phase:
            logger.info(f"   🔄 Resumed from phase {resumed_from_phase} (skipped: {', '.join(phases_skipped)})")
        logger.info(f"   Total duration: {total_duration:.2f}s")
        if phase1_duration > 0:
            logger.info(f"   Validation: {phase1_duration:.2f}s")
        if phase2_duration > 0:
            logger.info(f"   COG creation: {phase2_duration:.2f}s")
        if phase3_duration > 0:
            logger.info(f"   STAC metadata: {phase3_duration:.2f}s")
        # Log resource summary
        if resource_stats.get("peak_memory_mb"):
            logger.info(f"   📊 Peak memory (COG): {resource_stats['peak_memory_mb']} MB")
        if resource_stats.get("peak_memory_overall_mb"):
            logger.info(f"   📊 Peak memory (overall): {resource_stats['peak_memory_overall_mb']} MB")
        logger.info("=" * 70)

        # =====================================================================
        # ARTIFACT REGISTRY (21 JAN 2026)
        # =====================================================================
        # Create artifact record for lineage tracking with checksum
        artifact_id = None
        logger.debug(f"📦 ARTIFACT DEBUG: Starting artifact creation, params keys: {list(params.keys())}")
        logger.debug(f"📦 ARTIFACT DEBUG: dataset_id={params.get('dataset_id')}, resource_id={params.get('resource_id')}, version_id={params.get('version_id')}")
        try:
            from services.artifact_service import ArtifactService
            logger.debug("📦 ARTIFACT DEBUG: ArtifactService imported successfully")

            # Build client_refs from platform parameters
            client_refs = {}
            if params.get('dataset_id'):
                client_refs['dataset_id'] = params['dataset_id']
            if params.get('resource_id'):
                client_refs['resource_id'] = params['resource_id']
            if params.get('version_id'):
                client_refs['version_id'] = params['version_id']

            logger.debug(f"📦 ARTIFACT DEBUG: client_refs={client_refs}")

            # Only create artifact if we have client refs (platform job)
            if client_refs:
                logger.debug(f"📦 ARTIFACT DEBUG: Creating ArtifactService...")
                artifact_service = ArtifactService()
                logger.debug(f"📦 ARTIFACT DEBUG: Calling create_artifact with cog_blob={cog_blob}, cog_container={cog_container}")
                # Build artifact metadata (28 JAN 2026: include source_checksum for overwrite detection)
                artifact_metadata = {
                    'cog_tier': cog_result.get('cog_tier'),
                    'compression': cog_result.get('compression'),
                    'raster_type': cog_result.get('raster_type', {}).get('detected_type') if isinstance(cog_result.get('raster_type'), dict) else cog_result.get('raster_type'),
                    # Source tracking for overwrite comparison (28 JAN 2026)
                    'source_checksum': source_checksum,
                    'source_container': container_name,
                    'source_blob': blob_name,
                }
                # Include title/tags if provided (for overwrite metadata comparison)
                if params.get('title'):
                    artifact_metadata['title'] = params['title']
                if params.get('tags'):
                    artifact_metadata['tags'] = params['tags']

                artifact = artifact_service.create_artifact(
                    storage_account=config.storage.silver.account_name,
                    container=cog_container,
                    blob_path=cog_blob,
                    client_type='ddh',  # Platform client type
                    client_refs=client_refs,
                    stac_collection_id=stac_result.get('collection_id'),
                    stac_item_id=stac_result.get('item_id'),
                    source_job_id=params.get('_job_id'),
                    source_task_id=params.get('_task_id'),
                    content_hash=cog_result.get('file_checksum'),
                    size_bytes=cog_result.get('file_size'),
                    content_type='image/tiff; application=geotiff; profile=cloud-optimized',
                    blob_version_id=cog_result.get('blob_version_id'),  # Azure version (21 JAN 2026)
                    metadata=artifact_metadata,
                    overwrite=True  # Platform jobs always overwrite
                )
                artifact_id = str(artifact.artifact_id)
                logger.info(f"📦 Artifact created: {artifact_id} (revision {artifact.revision})")

                # Delete old COG if this was an overwrite with different source data (28 JAN 2026)
                if overwrite_result and overwrite_result.get('old_cog_path'):
                    old_path = overwrite_result['old_cog_path']
                    old_container = overwrite_result.get('old_cog_container', cog_container)
                    # Only delete if path is different (avoid deleting the new COG)
                    if old_path != cog_blob:
                        _delete_old_cog(old_container, old_path)
            else:
                logger.debug("📦 ARTIFACT DEBUG: Skipping artifact creation - no client_refs (non-platform job)")
        except Exception as e:
            # Artifact creation is non-fatal - log warning but continue
            import traceback
            logger.warning(f"⚠️ Artifact creation failed (non-fatal): {e}")
            logger.warning(f"⚠️ Artifact error traceback: {traceback.format_exc()}")

        # V0.8.16.7: Reset approval state after successful overwrite (10 FEB 2026)
        if params.get('reset_approval') and params.get('asset_id'):
            try:
                from services.asset_service import AssetService
                asset_service = AssetService()
                reset_done = asset_service.reset_approval_for_overwrite(params['asset_id'])
                if reset_done:
                    logger.info(f"Reset approval state to PENDING_REVIEW after successful overwrite")
            except Exception as reset_err:
                logger.warning(f"Failed to reset approval state: {reset_err}")

        return {
            "success": True,
            "result": {
                # V0.8: Output mode indicator (24 JAN 2026)
                "output_mode": "single_cog",
                "validation": {
                    "source_crs": source_crs,
                    "raster_type": validation_result.get('raster_type', {}).get('detected_type'),
                    "confidence": validation_result.get('raster_type', {}).get('confidence'),
                    "warnings": validation_result.get('warnings', []),
                },
                "cog": {
                    "cog_blob": cog_blob,
                    "cog_container": cog_container,
                    "size_mb": cog_result.get('size_mb'),
                    "compression": cog_result.get('compression'),
                    "processing_time_seconds": phase2_duration,
                    "raster_type": cog_result.get('raster_type'),
                    # STAC file extension compliant (21 JAN 2026)
                    "file_checksum": cog_result.get('file_checksum'),
                    "file_size": cog_result.get('file_size'),
                },
                "stac": stac_result,
                "processing": {
                    "total_seconds": total_duration,
                    "validation_seconds": phase1_duration,
                    "cog_seconds": phase2_duration,
                    "stac_seconds": phase3_duration,
                    "mode": "docker_single_stage",
                    "resumed": resumed_from_phase is not None,
                    "resumed_from_phase": resumed_from_phase,
                    "phases_skipped": phases_skipped,
                },
                # F7.20: Resource metrics for capacity planning (19 JAN 2026)
                "resources": {
                    "initial_rss_mb": resource_stats["initial"].get("process_rss_mb"),
                    "final_rss_mb": resource_stats["final"].get("process_rss_mb"),
                    "peak_memory_cog_mb": resource_stats.get("peak_memory_mb"),
                    "peak_memory_overall_mb": resource_stats.get("peak_memory_overall_mb"),
                    "cog_memory_polls": resource_stats.get("cog_polls", 0),
                    "system_available_mb": resource_stats["final"].get("system_available_mb"),
                    "system_percent": resource_stats["final"].get("system_percent"),
                },
                # Artifact registry (21 JAN 2026)
                "artifact_id": artifact_id,
            },
        }

    except Exception as e:
        import traceback
        total_duration = time.time() - start_time

        # Get checkpoint state for debugging
        checkpoint_state = None
        if checkpoint:
            checkpoint_state = {
                "current_phase": checkpoint.current_phase,
                "data_keys": list(checkpoint.data.keys()),
            }

        # F7.20: Capture final resource state on failure (useful for OOM debugging)
        resource_stats["final"] = get_memory_stats() or {}
        resource_stats["peak_memory_overall_mb"] = get_peak_memory_mb()

        logger.error("=" * 70)
        logger.error("❌ PROCESS RASTER COMPLETE (SINGLE COG) - FAILED")
        logger.error(f"   Error: {e}")
        logger.error(f"   Duration before failure: {total_duration:.2f}s")
        if checkpoint_state:
            logger.error(f"   Checkpoint state: phase={checkpoint_state['current_phase']}, keys={checkpoint_state['data_keys']}")
        # Log resource state at failure
        if resource_stats.get("peak_memory_mb"):
            logger.error(f"   📊 Peak memory (COG): {resource_stats['peak_memory_mb']} MB")
        if resource_stats.get("peak_memory_overall_mb"):
            logger.error(f"   📊 Peak memory (overall): {resource_stats['peak_memory_overall_mb']} MB")
        logger.error("=" * 70)
        logger.error(traceback.format_exc())

        return {
            "success": False,
            "error": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
            "validation": validation_result,
            "cog": cog_result,
            "stac": stac_result,
            "duration_seconds": total_duration,
            "checkpoint_state": checkpoint_state,
            # F7.20: Resource metrics at failure (for OOM debugging)
            "resources": {
                "initial_rss_mb": resource_stats["initial"].get("process_rss_mb"),
                "final_rss_mb": resource_stats["final"].get("process_rss_mb"),
                "peak_memory_cog_mb": resource_stats.get("peak_memory_mb"),
                "peak_memory_overall_mb": resource_stats.get("peak_memory_overall_mb"),
                "system_available_mb": resource_stats["final"].get("system_available_mb"),
            },
        }
