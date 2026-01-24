# ============================================================================
# PROCESS RASTER COMPLETE HANDLER (Docker)
# ============================================================================
# STATUS: Services - Consolidated raster handler for Docker worker
# PURPOSE: Single handler that does validate → COG → STAC in one execution
# LAST_REVIEWED: 24 JAN 2026
# F7.18: Integrated with Docker Orchestration Framework (graceful shutdown)
# F7.19: Real-time progress reporting for Workflow Monitor (19 JAN 2026)
# F7.20: Resource metrics tracking (peak memory, CPU) for capacity planning
# V0.8: Internal tiling decision based on file size (24 JAN 2026)
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
    2. Extract tiles
    3. Create COGs for each tile
    4. Create MosaicJSON
    5. Create STAC collection

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
import time
from typing import Dict, Any, Optional, Callable

from util_logger import (
    get_memory_stats,
    get_peak_memory_mb,
    track_peak_memory_to_task,
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
# V0.8: TILED WORKFLOW (24 JAN 2026)
# =============================================================================

def _process_raster_tiled(
    params: Dict[str, Any],
    context: Optional[Dict],
    start_time: float
) -> Dict[str, Any]:
    """
    Process large raster with tiled output.

    V0.8 Architecture (24 JAN 2026):
        This is the internal tiled workflow, called when file size exceeds
        raster_tiling_threshold_mb. It produces multiple COG tiles and a MosaicJSON.

    Phases:
        1. Generate tiling scheme
        2. Extract tiles
        3. Create COGs for each tile
        4. Create MosaicJSON
        5. Create STAC collection

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

    logger.info("=" * 70)
    logger.info("PROCESS RASTER - TILED MODE (V0.8)")
    logger.info(f"Source: {container_name}/{blob_name}")
    logger.info(f"File size: {file_size_mb:.1f} MB" if file_size_mb else "File size: unknown")
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
    mosaicjson_result = {}
    stac_result = {}

    try:
        # =====================================================================
        # PHASE 1: GENERATE TILING SCHEME
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping tiling scheme (checkpoint)")
            tiling_result = checkpoint.get_data('tiling_result', {})
        else:
            logger.info("🔄 PHASE 1: Generating tiling scheme...")
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

            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.2f}s")
            logger.info(f"   Tile count: {tiling_result.get('tile_count')}")
            logger.info(f"   Grid: {tiling_result.get('grid_dimensions')}")

            if checkpoint:
                checkpoint.save(phase=1, data={'tiling_result': tiling_result})

        # =====================================================================
        # PHASE 2: EXTRACT TILES
        # =====================================================================
        if checkpoint and checkpoint.should_skip(2):
            logger.info("⏭️ PHASE 2: Skipping tile extraction (checkpoint)")
            extraction_result = checkpoint.get_data('extraction_result', {})
        else:
            tile_count = tiling_result.get('tile_count', 0)
            logger.info(f"🔄 PHASE 2: Extracting {tile_count} tiles...")
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

            logger.info(f"✅ PHASE 2 complete: {phase2_duration:.2f}s")
            logger.info(f"   Tiles extracted: {extraction_result.get('tile_count')}")

            if checkpoint:
                checkpoint.save(phase=2, data={'extraction_result': extraction_result})

        # =====================================================================
        # PHASE 3: CREATE COGS
        # =====================================================================
        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping COG creation (checkpoint)")
            cog_results = checkpoint.get_data('cog_results', [])
        else:
            tile_blobs = extraction_result.get('tile_blobs', [])
            tile_count = len(tile_blobs)
            source_crs = extraction_result.get('source_crs')
            raster_metadata = extraction_result.get('raster_metadata', {})

            logger.info(f"🔄 PHASE 3: Creating {tile_count} COGs...")
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

            logger.info(f"✅ PHASE 3 complete: {phase3_duration:.2f}s")
            logger.info(f"   COGs created: {len(cog_blobs)}")

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
        # PHASE 4: CREATE MOSAICJSON
        # =====================================================================
        if checkpoint and checkpoint.should_skip(4):
            logger.info("⏭️ PHASE 4: Skipping MosaicJSON (checkpoint)")
            mosaicjson_result = checkpoint.get_data('mosaicjson_result', {})
        else:
            logger.info(f"🔄 PHASE 4: Creating MosaicJSON from {len(cog_blobs)} COGs...")
            phase4_start = time.time()

            from .raster_mosaicjson import create_mosaicjson

            # Generate MosaicJSON output path
            blob_stem = Path(blob_name).stem
            mosaicjson_blob = f"{blob_stem}_mosaic.json"
            if params.get('output_folder'):
                mosaicjson_blob = f"{params['output_folder']}/{mosaicjson_blob}"

            mosaicjson_params = {
                'cog_blobs': cog_blobs,
                'cog_container': config.storage.silver.cogs,
                'output_blob': mosaicjson_blob,
                'output_container': config.storage.silver.cogs,
                'name': blob_stem,
                'description': f"MosaicJSON for {blob_name}",
            }

            mosaicjson_response = create_mosaicjson(mosaicjson_params)

            if not mosaicjson_response.get('success'):
                logger.warning(f"⚠️ MosaicJSON creation failed (non-fatal): {mosaicjson_response.get('error')}")
                mosaicjson_result = {
                    "degraded": True,
                    "error": mosaicjson_response.get('error'),
                }
            else:
                mosaicjson_result = mosaicjson_response.get('result', {})

            phase4_duration = time.time() - phase4_start

            logger.info(f"✅ PHASE 4 complete: {phase4_duration:.2f}s")
            if mosaicjson_result.get('mosaicjson_blob'):
                logger.info(f"   MosaicJSON: {mosaicjson_result.get('mosaicjson_blob')}")

            if checkpoint:
                checkpoint.save(phase=4, data={'mosaicjson_result': mosaicjson_result})

        # =====================================================================
        # PHASE 5: CREATE STAC COLLECTION
        # =====================================================================
        if checkpoint and checkpoint.should_skip(5):
            logger.info("⏭️ PHASE 5: Skipping STAC (checkpoint)")
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            logger.info("🔄 PHASE 5: Creating STAC collection...")
            phase5_start = time.time()

            from .raster_stac_collection import create_stac_collection

            collection_id = params.get('collection_id')
            blob_stem = Path(blob_name).stem

            stac_params = {
                'collection_id': collection_id,
                'item_id': params.get('item_id') or blob_stem,
                'cog_blobs': cog_blobs,
                'cog_container': config.storage.silver.cogs,
                'mosaicjson_blob': mosaicjson_result.get('mosaicjson_blob'),
                'mosaicjson_container': config.storage.silver.cogs,
                'title': f"Large Raster: {blob_stem}",
                'description': f"Tiled COG mosaic from {blob_name}",
                # Platform passthrough
                'dataset_id': params.get('dataset_id'),
                'resource_id': params.get('resource_id'),
                'version_id': params.get('version_id'),
                'access_level': params.get('access_level'),
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

            phase5_duration = time.time() - phase5_start

            logger.info(f"✅ PHASE 5 complete: {phase5_duration:.2f}s")
            if stac_result.get('collection_id'):
                logger.info(f"   Collection: {stac_result.get('collection_id')}")

            if checkpoint:
                checkpoint.save(phase=5, data={'stac_result': stac_result})

        # =====================================================================
        # SUCCESS - TILED OUTPUT
        # =====================================================================
        total_duration = time.time() - start_time

        logger.info("=" * 70)
        logger.info("✅ PROCESS RASTER COMPLETE (TILED) - SUCCESS")
        logger.info(f"   Total duration: {total_duration:.2f}s ({total_duration/60:.1f} min)")
        logger.info(f"   Tiles: {tiling_result.get('tile_count', 0)}")
        logger.info(f"   COGs: {len(cog_blobs)}")
        if mosaicjson_result.get('mosaicjson_blob'):
            logger.info(f"   MosaicJSON: {mosaicjson_result.get('mosaicjson_blob')}")
        if stac_result.get('collection_id'):
            logger.info(f"   STAC: {stac_result.get('collection_id')}")
        logger.info("=" * 70)

        # =====================================================================
        # ARTIFACT REGISTRY (21 JAN 2026)
        # =====================================================================
        artifact_id = None
        try:
            from services.artifact_service import ArtifactService

            # Build client_refs from platform parameters
            client_refs = {}
            if params.get('dataset_id'):
                client_refs['dataset_id'] = params['dataset_id']
            if params.get('resource_id'):
                client_refs['resource_id'] = params['resource_id']
            if params.get('version_id'):
                client_refs['version_id'] = params['version_id']

            # Only create artifact if we have client refs (platform job) and MosaicJSON
            if client_refs and mosaicjson_result.get('mosaicjson_blob'):
                artifact_service = ArtifactService()
                artifact = artifact_service.create_artifact(
                    storage_account=config.storage.silver.account_name,
                    container=mosaicjson_result.get('mosaicjson_container'),
                    blob_path=mosaicjson_result.get('mosaicjson_blob'),
                    client_type='ddh',
                    client_refs=client_refs,
                    stac_collection_id=stac_result.get('collection_id'),
                    stac_item_id=stac_result.get('item_id'),
                    source_job_id=params.get('_job_id'),
                    source_task_id=params.get('_task_id'),
                    content_hash=None,  # MosaicJSON doesn't have checksum yet
                    size_bytes=None,
                    content_type='application/json',
                    blob_version_id=mosaicjson_result.get('blob_version_id'),
                    metadata={
                        'tile_count': tiling_result.get('tile_count'),
                        'cog_count': len(cog_blobs),
                        'raster_type': 'large_tiled',
                    },
                    overwrite=True
                )
                artifact_id = str(artifact.artifact_id)
                logger.info(f"📦 Artifact created: {artifact_id} (revision {artifact.revision})")
            else:
                logger.debug("Skipping artifact creation - no client_refs or MosaicJSON")
        except Exception as e:
            logger.warning(f"⚠️ Artifact creation failed (non-fatal): {e}")

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
                "mosaicjson": mosaicjson_result,
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
            Tiled output (5 phases: tiling → extract → COGs → MosaicJSON → STAC)
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

    logger.info("=" * 60)
    logger.info("PROCESS RASTER COMPLETE - Docker Handler (V0.8)")
    logger.info(f"Source: {container_name}/{blob_name}")
    if file_size_mb:
        logger.info(f"File size: {file_size_mb:.1f} MB (threshold: {tiling_threshold_mb} MB)")
    logger.info(f"Output mode: {'TILED' if use_tiling else 'SINGLE_COG'}")
    if task_id:
        logger.info(f"Task ID: {task_id[:8]}... (checkpoint enabled)")
    logger.info("=" * 60)

    # V0.8: Route to tiled workflow if file exceeds threshold
    if use_tiling:
        logger.info("📦 Routing to TILED workflow...")
        return _process_raster_tiled(params, context, start_time)

    # Initialize checkpoint manager
    # F7.18: Use DockerTaskContext if available (Docker mode)
    # Otherwise fall back to manual creation (Function App mode)
    docker_context = params.get('_docker_context')
    checkpoint = None

    if docker_context:
        # Docker mode: use pre-configured checkpoint from context
        checkpoint = docker_context.checkpoint
        if checkpoint.current_phase > 0:
            logger.info(f"🔄 Resuming from phase {checkpoint.current_phase} (Docker context)")
    elif task_id:
        # Function App mode: create checkpoint manually
        try:
            from infrastructure import CheckpointManager
            from infrastructure.factory import RepositoryFactory
            task_repo = RepositoryFactory.create_task_repository()
            checkpoint = CheckpointManager(task_id, task_repo)
            if checkpoint.current_phase > 0:
                logger.info(f"🔄 Resuming from phase {checkpoint.current_phase}")
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
                logger.error("Resume error: No source_crs in checkpoint data")
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
                logger.error(f"Validation failed: {validation_response.get('error')}")
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
                logger.error("No source_crs in validation results")
                return {
                    "success": False,
                    "error": "NO_SOURCE_CRS",
                    "message": "Validation did not return source CRS",
                    "phase": "validation",
                    "validation": validation_result,
                }

            phase1_duration = time.time() - phase1_start
            logger.info(f"✅ PHASE 1 complete: {phase1_duration:.2f}s")
            logger.info(f"  Source CRS: {source_crs}")
            logger.info(f"  Raster type: {validation_result.get('raster_type', {}).get('detected_type')}")
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
            logger.warning("=" * 50)
            logger.warning("🛑 GRACEFUL SHUTDOWN - Handler Interrupted")
            logger.warning(f"  Task ID: {task_id[:16] if task_id else 'unknown'}...")
            logger.warning(f"  Phase completed: 1 (validation)")
            logger.warning(f"  Phase skipped: 2 (COG creation), 3 (STAC)")
            logger.warning(f"  Source CRS saved: {source_crs}")
            logger.warning("  Returning interrupted=True for message abandonment")
            logger.warning("=" * 50)
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
                logger.error("Resume error: No cog_blob in checkpoint data")
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
                logger.error(f"COG creation failed: {cog_response.get('error')}")
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
                logger.error("COG creation did not return output blob path")
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
            logger.info(f"  COG blob: {cog_blob}")
            logger.info(f"  Size: {cog_size_mb} MB")
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
            logger.warning("=" * 50)
            logger.warning("🛑 GRACEFUL SHUTDOWN - Handler Interrupted")
            logger.warning(f"  Task ID: {task_id[:16] if task_id else 'unknown'}...")
            logger.warning(f"  Phase completed: 2 (COG creation)")
            logger.warning(f"  Phase skipped: 3 (STAC metadata)")
            logger.warning(f"  COG blob saved: {cog_blob}")
            logger.warning(f"  COG container: {cog_container}")
            logger.warning("  Returning interrupted=True for message abandonment")
            logger.warning("=" * 50)
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
                'item_id': params.get('item_id'),
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
                logger.warning(f"STAC creation failed (non-fatal): {stac_response.get('error')}")
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
                logger.info(f"  STAC item: {stac_result.get('item_id')}")
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

        logger.info("=" * 60)
        logger.info("PROCESS RASTER COMPLETE - SUCCESS")
        if resumed_from_phase:
            logger.info(f"🔄 Resumed from phase {resumed_from_phase} (skipped: {', '.join(phases_skipped)})")
        logger.info(f"Total duration: {total_duration:.2f}s")
        if phase1_duration > 0:
            logger.info(f"  Validation: {phase1_duration:.2f}s")
        if phase2_duration > 0:
            logger.info(f"  COG creation: {phase2_duration:.2f}s")
        if phase3_duration > 0:
            logger.info(f"  STAC metadata: {phase3_duration:.2f}s")
        # Log resource summary
        if resource_stats.get("peak_memory_mb"):
            logger.info(f"📊 Peak memory (COG): {resource_stats['peak_memory_mb']} MB")
        if resource_stats.get("peak_memory_overall_mb"):
            logger.info(f"📊 Peak memory (overall): {resource_stats['peak_memory_overall_mb']} MB")
        logger.info("=" * 60)

        # =====================================================================
        # ARTIFACT REGISTRY (21 JAN 2026)
        # =====================================================================
        # Create artifact record for lineage tracking with checksum
        artifact_id = None
        logger.info(f"📦 ARTIFACT DEBUG: Starting artifact creation, params keys: {list(params.keys())}")
        logger.info(f"📦 ARTIFACT DEBUG: dataset_id={params.get('dataset_id')}, resource_id={params.get('resource_id')}, version_id={params.get('version_id')}")
        try:
            from services.artifact_service import ArtifactService
            logger.info("📦 ARTIFACT DEBUG: ArtifactService imported successfully")

            # Build client_refs from platform parameters
            client_refs = {}
            if params.get('dataset_id'):
                client_refs['dataset_id'] = params['dataset_id']
            if params.get('resource_id'):
                client_refs['resource_id'] = params['resource_id']
            if params.get('version_id'):
                client_refs['version_id'] = params['version_id']

            logger.info(f"📦 ARTIFACT DEBUG: client_refs={client_refs}")

            # Only create artifact if we have client refs (platform job)
            if client_refs:
                logger.info(f"📦 ARTIFACT DEBUG: Creating ArtifactService...")
                artifact_service = ArtifactService()
                logger.info(f"📦 ARTIFACT DEBUG: Calling create_artifact with cog_blob={cog_blob}, cog_container={cog_container}")
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
                    metadata={
                        'cog_tier': cog_result.get('cog_tier'),
                        'compression': cog_result.get('compression'),
                        'raster_type': cog_result.get('raster_type', {}).get('detected_type') if isinstance(cog_result.get('raster_type'), dict) else cog_result.get('raster_type'),
                    },
                    overwrite=True  # Platform jobs always overwrite
                )
                artifact_id = str(artifact.artifact_id)
                logger.info(f"📦 Artifact created: {artifact_id} (revision {artifact.revision})")
            else:
                logger.info("📦 ARTIFACT DEBUG: Skipping artifact creation - no client_refs (non-platform job)")
        except Exception as e:
            # Artifact creation is non-fatal - log warning but continue
            import traceback
            logger.warning(f"⚠️ Artifact creation failed (non-fatal): {e}")
            logger.warning(f"⚠️ Artifact error traceback: {traceback.format_exc()}")

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

        logger.error("=" * 60)
        logger.error("PROCESS RASTER COMPLETE - FAILED")
        logger.error(f"Error: {e}")
        logger.error(f"Duration before failure: {total_duration:.2f}s")
        if checkpoint_state:
            logger.error(f"Checkpoint state: phase={checkpoint_state['current_phase']}, keys={checkpoint_state['data_keys']}")
        # Log resource state at failure
        if resource_stats.get("peak_memory_mb"):
            logger.error(f"📊 Peak memory (COG): {resource_stats['peak_memory_mb']} MB")
        if resource_stats.get("peak_memory_overall_mb"):
            logger.error(f"📊 Peak memory (overall): {resource_stats['peak_memory_overall_mb']} MB")
        logger.error("=" * 60)
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
