# ============================================================================
# RASTER COLLECTION COMPLETE HANDLER (Docker)
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Services - Consolidated raster collection handler for Docker worker
# PURPOSE: Process raster collection to COGs with checkpoint-based resume
# CREATED: 30 JAN 2026
# EXPORTS: raster_collection_complete
# DEPENDENCIES: CheckpointManager, JobEvent, create_stac_collection
# ============================================================================
"""
Raster Collection Complete - Sequential Checkpoint-Based Docker Handler.

Processes a collection of raster files into COGs with STAC registration.
Downloads all source files to temp storage first to avoid OOM issues.

Phases:
    1. DOWNLOAD: Copy all blobs from bronze → temp mount storage
    2. COG CREATION: Sequential processing with per-file checkpoints
    3. STAC: Create collection and register items (direct call mode)
    4. CLEANUP: Remove temp files (optional)

Resume Support:
    - CheckpointManager tracks phase completion
    - COG phase saves checkpoint after each file
    - Can resume mid-collection on Docker restart

JobEvents:
    - Emits CHECKPOINT events for execution timeline visibility
    - Enables "last successful step" debugging in UI

Input/Output:
    - N GeoTIFFs in → N COGs out (one-to-one mapping)
    - All COGs registered in single STAC collection

Exports:
    raster_collection_complete: Main handler function
"""

import logging
import os
import time
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List

from util_logger import LoggerFactory, ComponentType, get_peak_memory_mb

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "raster_collection_complete")


# =============================================================================
# JOBEVENT HELPER
# =============================================================================

def _emit_job_event(
    job_id: str,
    task_id: str,
    stage: int,
    checkpoint_name: str,
    event_data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None
) -> None:
    """
    Emit a JobEvent for checkpoint visibility.

    Args:
        job_id: Parent job ID
        task_id: Task ID
        stage: Stage number
        checkpoint_name: Checkpoint identifier (e.g., 'download_started')
        event_data: Additional event data
        error_message: Error message if failure
        duration_ms: Duration of operation
    """
    try:
        from core.models.job_event import JobEvent, JobEventType, JobEventStatus
        from infrastructure.job_event_repository import JobEventRepository

        event = JobEvent.create_task_event(
            job_id=job_id,
            task_id=task_id,
            stage=stage,
            event_type=JobEventType.CHECKPOINT,
            event_status=JobEventStatus.SUCCESS if not error_message else JobEventStatus.FAILURE,
            checkpoint_name=checkpoint_name,
            event_data=event_data or {},
            error_message=error_message,
            duration_ms=duration_ms
        )

        repo = JobEventRepository()
        repo.create_event(event)
        logger.debug(f"📌 JobEvent: {checkpoint_name}")

    except Exception as e:
        # JobEvents are non-critical - log and continue
        logger.warning(f"Failed to emit JobEvent '{checkpoint_name}': {e}")


# =============================================================================
# PROGRESS REPORTING
# =============================================================================

def _report_progress(
    docker_context,
    percent: float,
    phase: int,
    total_phases: int,
    phase_name: str,
    message: str
) -> None:
    """Report progress to task metadata for Workflow Monitor visibility."""
    if not docker_context:
        return

    try:
        docker_context.report_progress(
            percent=percent,
            message=f"Phase {phase}/{total_phases}: {phase_name} - {message}"
        )
    except Exception as e:
        logger.debug(f"Progress report failed (non-critical): {e}")


# =============================================================================
# MOUNT PATH HELPERS
# =============================================================================

def _get_mount_paths(job_id: str, config) -> Dict[str, Path]:
    """
    Get mount paths for temp storage.

    Uses config.raster.etl_mount_path for Azure Files mount in Docker.
    Falls back to /tmp for local development.

    Args:
        job_id: Job ID for unique folder naming
        config: AppConfig instance

    Returns:
        Dict with 'base', 'source', 'cogs' paths
    """
    # Use configured mount path (default: /mounts/etl-temp)
    mount_path = config.raster.etl_mount_path

    # Check for mounted storage
    if os.path.exists(mount_path) and os.access(mount_path, os.W_OK):
        base = Path(mount_path) / f"collection_{job_id[:8]}"
    else:
        # Fallback for local dev
        logger.warning(f"Mount path {mount_path} not available, using /tmp")
        base = Path('/tmp') / f"collection_{job_id[:8]}"

    return {
        'base': base,
        'source': base / 'source',
        'cogs': base / 'cogs',
    }


def _ensure_mount_paths(paths: Dict[str, Path]) -> None:
    """Create mount directories if they don't exist."""
    for key, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"📁 Ensured path: {path}")


def _cleanup_mount_paths(paths: Dict[str, Path]) -> Dict[str, Any]:
    """
    Remove temp directories after processing.

    Returns:
        Cleanup result with files/bytes deleted
    """
    result = {'files_deleted': 0, 'bytes_deleted': 0}

    try:
        base = paths['base']
        if base.exists():
            # Count files first
            for f in base.rglob('*'):
                if f.is_file():
                    result['files_deleted'] += 1
                    result['bytes_deleted'] += f.stat().st_size

            shutil.rmtree(base)
            logger.info(f"🗑️ Cleaned up temp: {base} ({result['files_deleted']} files)")
    except Exception as e:
        logger.warning(f"Cleanup failed (non-fatal): {e}")

    return result


# =============================================================================
# PHASE 1: DOWNLOAD
# =============================================================================

def _download_blobs_to_mount(
    blob_list: List[str],
    container_name: str,
    dest_path: Path,
    docker_context,
    job_id: str,
    task_id: str
) -> Dict[str, Any]:
    """
    Download all source blobs to mount storage.

    Args:
        blob_list: List of blob paths to download
        container_name: Source container
        dest_path: Local destination directory
        docker_context: For progress reporting
        job_id: Job ID for events
        task_id: Task ID for events

    Returns:
        Result dict with downloaded files and sizes
    """
    from infrastructure.blob import BlobRepository

    blob_repo = BlobRepository.for_zone('bronze')
    downloaded_files = []
    total_bytes = 0
    start_time = time.time()

    _emit_job_event(job_id, task_id, 1, "download_started", {
        'blob_count': len(blob_list),
        'container': container_name,
    })

    for idx, blob_name in enumerate(blob_list):
        # Progress: 0-25% for download phase
        progress = int((idx / len(blob_list)) * 25)
        _report_progress(docker_context, progress, 1, 4, "Download", f"{idx+1}/{len(blob_list)}")

        # Generate local filename
        filename = Path(blob_name).name
        local_path = dest_path / filename

        logger.info(f"📥 Downloading {idx+1}/{len(blob_list)}: {blob_name}")

        try:
            # Download blob to local file
            blob_data = blob_repo.read_blob(container_name, blob_name)
            local_path.write_bytes(blob_data)

            file_size = len(blob_data)
            total_bytes += file_size

            downloaded_files.append({
                'blob_name': blob_name,
                'local_path': str(local_path),
                'size_bytes': file_size,
            })

            logger.debug(f"   ✓ {filename} ({file_size / 1024 / 1024:.1f} MB)")

        except Exception as e:
            logger.error(f"❌ Failed to download {blob_name}: {e}")
            raise

    duration_ms = int((time.time() - start_time) * 1000)

    _emit_job_event(job_id, task_id, 1, "download_complete", {
        'files_downloaded': len(downloaded_files),
        'total_mb': round(total_bytes / 1024 / 1024, 1),
    }, duration_ms=duration_ms)

    return {
        'files': downloaded_files,
        'total_bytes': total_bytes,
        'total_mb': round(total_bytes / 1024 / 1024, 1),
        'duration_seconds': round(duration_ms / 1000, 1),
    }


# =============================================================================
# PHASE 2: COG CREATION
# =============================================================================

def _process_files_to_cogs(
    downloaded_files: List[Dict],
    cog_dest_path: Path,
    params: Dict[str, Any],
    checkpoint,
    docker_context,
    job_id: str,
    task_id: str
) -> Dict[str, Any]:
    """
    Process downloaded files to COGs sequentially.

    Saves checkpoint after each file for resume capability.

    Args:
        downloaded_files: List of downloaded file info dicts
        cog_dest_path: Local destination for COGs
        params: Processing parameters
        checkpoint: CheckpointManager for resume
        docker_context: For progress/shutdown
        job_id: Job ID for events
        task_id: Task ID for events

    Returns:
        Result dict with COG info
    """
    from services.raster_validation import validate_raster
    from services.raster_cog import create_cog
    from config import get_config

    config = get_config()

    cog_results = []
    cog_blobs = []
    start_time = time.time()

    # Get resume index from checkpoint
    start_index = checkpoint.get_data('cog_last_index', -1) + 1 if checkpoint else 0
    if start_index > 0:
        # Restore previous results
        cog_results = checkpoint.get_data('cog_results', [])
        cog_blobs = checkpoint.get_data('cog_blobs', [])
        logger.info(f"🔄 Resuming COG creation from index {start_index}")

    _emit_job_event(job_id, task_id, 1, "cog_started", {
        'file_count': len(downloaded_files),
        'start_index': start_index,
    })

    total_files = len(downloaded_files)

    for idx in range(start_index, total_files):
        file_info = downloaded_files[idx]
        local_path = file_info['local_path']
        original_blob = file_info['blob_name']

        # Progress: 25-85% for COG phase
        progress = 25 + int(((idx - start_index) / (total_files - start_index)) * 60) if total_files > start_index else 25
        _report_progress(docker_context, progress, 2, 4, "Create COGs", f"{idx+1}/{total_files}")

        logger.info(f"📦 COG {idx+1}/{total_files}: {Path(local_path).name}")

        # Check for shutdown
        if checkpoint and checkpoint.should_stop():
            logger.warning("🛑 Shutdown requested, saving checkpoint...")
            checkpoint.save(phase=2, data={
                'cog_results': cog_results,
                'cog_blobs': cog_blobs,
                'cog_last_index': idx - 1,
            })
            return {
                'interrupted': True,
                'last_index': idx - 1,
                'cog_count': len(cog_blobs),
            }

        try:
            # Step 1: Validate raster
            # Note: validate_raster expects blob_url but rasterio can open local paths
            validation_params = {
                'blob_url': local_path,  # Local path works with rasterio.open()
                'blob_name': original_blob,  # From file_info['blob_name']
                'container_name': params.get('container_name', 'local'),
                'input_crs': params.get('input_crs'),
                'raster_type': params.get('raster_type', 'auto'),
                'strict_mode': params.get('strict_mode', False),
            }
            validation_result = validate_raster(validation_params)

            if not validation_result.get('success'):
                raise ValueError(f"Validation failed: {validation_result.get('error')}")

            validated = validation_result.get('result', {})

            # Step 2: Create COG
            # Generate output filename
            stem = Path(local_path).stem
            output_filename = f"{stem}_cog.tif"
            output_folder = params.get('output_folder', job_id[:8])
            output_blob_name = f"{output_folder}/{output_filename}"
            local_cog_path = cog_dest_path / output_filename

            cog_params = {
                '_local_source_path': local_path,  # V0.8.1: Local source mode (skips blob download)
                'source_crs': validated.get('source_crs'),  # From validation result
                'target_crs': params.get('target_crs') or config.raster.target_crs,
                'raster_type': validated.get('raster_type', {}),
                'output_tier': params.get('output_tier', 'analysis'),
                'output_local_path': str(local_cog_path),
                'output_blob_name': output_blob_name,
                'output_container': config.storage.silver.cogs,
                'jpeg_quality': params.get('jpeg_quality') or config.raster.cog_jpeg_quality,
                'overview_resampling': params.get('overview_resampling', config.raster.overview_resampling),
                'reproject_resampling': params.get('reproject_resampling', config.raster.reproject_resampling),
                'in_memory': False,  # Docker uses disk
                '_task_id': task_id,
            }

            cog_response = create_cog(cog_params)

            if not cog_response.get('success'):
                raise ValueError(f"COG creation failed: {cog_response.get('error')}")

            cog_result = cog_response.get('result', {})
            cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob') or output_blob_name

            cog_results.append({
                'source_blob': original_blob,
                'cog_blob': cog_blob,
                'size_mb': cog_result.get('size_mb'),
                'validation': validated,
            })
            cog_blobs.append(cog_blob)

            logger.info(f"   ✓ Created: {cog_blob}")

            # Save checkpoint after each file
            if checkpoint:
                checkpoint.save(phase=2, data={
                    'cog_results': cog_results,
                    'cog_blobs': cog_blobs,
                    'cog_last_index': idx,
                })

        except Exception as e:
            logger.error(f"❌ Failed to process {local_path}: {e}")
            _emit_job_event(job_id, task_id, 1, "cog_failed", {
                'file_index': idx,
                'file': Path(local_path).name,
            }, error_message=str(e))
            raise

    duration_ms = int((time.time() - start_time) * 1000)

    _emit_job_event(job_id, task_id, 1, "cog_complete", {
        'cog_count': len(cog_blobs),
    }, duration_ms=duration_ms)

    # Infer raster_type from first result for STAC
    raster_type_info = None
    if cog_results and cog_results[0].get('validation'):
        v = cog_results[0]['validation']
        raster_type_info = {
            'detected_type': v.get('detected_type', 'unknown'),
            'band_count': v.get('band_count', 3),
            'data_type': v.get('data_type', 'uint8'),
        }

    return {
        'cog_blobs': cog_blobs,
        'cog_results': cog_results,
        'cog_count': len(cog_blobs),
        'raster_type': raster_type_info,
        'duration_seconds': round(duration_ms / 1000, 1),
    }


# =============================================================================
# PHASE 3: STAC COLLECTION
# =============================================================================

def _create_stac_collection_from_cogs(
    cog_blobs: List[str],
    params: Dict[str, Any],
    raster_type: Optional[Dict],
    docker_context,
    job_id: str,
    task_id: str
) -> Dict[str, Any]:
    """
    Create STAC collection from COG blobs.

    Uses create_stac_collection in direct call mode (same as tiled end).

    Args:
        cog_blobs: List of COG blob paths
        params: Collection parameters
        raster_type: Raster type info for TiTiler
        docker_context: For progress
        job_id: Job ID for events
        task_id: Task ID for events

    Returns:
        STAC result dict
    """
    from services.stac_collection import create_stac_collection
    from config import get_config

    config = get_config()
    start_time = time.time()

    _emit_job_event(job_id, task_id, 1, "stac_started", {
        'cog_count': len(cog_blobs),
        'collection_id': params.get('collection_id'),
    })

    _report_progress(docker_context, 88, 3, 4, "STAC", "Creating collection")

    collection_id = params.get('collection_id')

    stac_params = {
        'cog_blobs': cog_blobs,
        'cog_container': config.storage.silver.cogs,
        'collection_id': collection_id,
        'title': params.get('collection_title') or f"Collection: {collection_id}",
        'description': params.get('collection_description') or f"Raster collection: {collection_id}",
        'license': params.get('license', 'proprietary'),
        # Platform passthrough
        'dataset_id': params.get('dataset_id'),
        'resource_id': params.get('resource_id'),
        'version_id': params.get('version_id'),
        'access_level': params.get('access_level'),
        # BUG-006: Pass raster_type for TiTiler bidx params
        'raster_type': raster_type,
    }

    stac_response = create_stac_collection(stac_params)

    duration_ms = int((time.time() - start_time) * 1000)

    if not stac_response.get('success'):
        error_msg = stac_response.get('error', 'Unknown STAC error')
        _emit_job_event(job_id, task_id, 1, "stac_failed", {
            'collection_id': collection_id,
        }, error_message=error_msg, duration_ms=duration_ms)

        # STAC is non-fatal - return degraded result
        logger.warning(f"⚠️ STAC creation failed (non-fatal): {error_msg}")
        return {
            'degraded': True,
            'error': error_msg,
            'collection_id': collection_id,
        }

    stac_result = stac_response.get('result', {})

    _emit_job_event(job_id, task_id, 1, "stac_complete", {
        'collection_id': stac_result.get('collection_id'),
        'item_count': stac_result.get('items_created', len(cog_blobs)),
    }, duration_ms=duration_ms)

    _report_progress(docker_context, 95, 3, 4, "STAC", "Complete")

    return stac_result


# =============================================================================
# MAIN HANDLER
# =============================================================================

def raster_collection_complete(
    parameters: Dict[str, Any],
    context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Process raster collection to COGs with STAC registration.

    Sequential checkpoint-based workflow:
        1. Download all source blobs to temp mount storage
        2. Process each file to COG (with per-file checkpoints)
        3. Create STAC collection from all COGs
        4. Cleanup temp files

    Args:
        parameters: Task parameters including:
            - blob_list: List of source blob paths
            - container_name: Source container
            - collection_id: STAC collection ID
            - target_crs: Output CRS
            - output_tier: COG compression tier
            - ...see job definition for full schema

        context: Optional task context

    Returns:
        {
            "success": bool,
            "result": {
                "download": {...},
                "cogs": {...},
                "stac": {...},
                "timing": {...}
            }
        }
    """
    from config import get_config

    config = get_config()
    start_time = time.time()

    # Extract key parameters
    blob_list = parameters.get('blob_list', [])
    container_name = parameters.get('container_name')
    collection_id = parameters.get('collection_id')
    task_id = parameters.get('_task_id')
    job_id = parameters.get('_job_id', 'unknown')

    # Docker context for progress/shutdown
    docker_context = parameters.get('_docker_context')

    logger.info("=" * 70)
    logger.info("RASTER COLLECTION COMPLETE - DOCKER")
    logger.info(f"   Collection: {collection_id}")
    logger.info(f"   Source: {container_name}")
    logger.info(f"   Files: {len(blob_list)}")
    if task_id:
        logger.info(f"   Task ID: {task_id[:8]}... (checkpoint enabled)")
    logger.info("=" * 70)

    # Initialize checkpoint manager
    checkpoint = None
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
    download_result = {}
    cog_result = {}
    stac_result = {}
    cleanup_result = {}

    try:
        # Setup mount paths (uses config.raster.etl_mount_path)
        mount_paths = _get_mount_paths(job_id, config)
        _ensure_mount_paths(mount_paths)
        logger.info(f"   Mount base: {mount_paths['base']}")

        # =====================================================================
        # PHASE 1: DOWNLOAD (0-25%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping download (checkpoint)")
            _report_progress(docker_context, 25, 1, 4, "Download", "Skipped (resumed)")
            download_result = checkpoint.get_data('download_result', {})
        else:
            logger.info("🔄 PHASE 1: Downloading source files...")
            _report_progress(docker_context, 2, 1, 4, "Download", f"Starting ({len(blob_list)} files)")

            download_result = _download_blobs_to_mount(
                blob_list=blob_list,
                container_name=container_name,
                dest_path=mount_paths['source'],
                docker_context=docker_context,
                job_id=job_id,
                task_id=task_id
            )

            logger.info(f"✅ PHASE 1 complete: {download_result.get('total_mb', 0):.1f} MB downloaded")
            _report_progress(docker_context, 25, 1, 4, "Download", "Complete")

            if checkpoint:
                checkpoint.save(phase=1, data={'download_result': download_result})

        # =====================================================================
        # PHASE 2: COG CREATION (25-85%)
        # =====================================================================
        downloaded_files = download_result.get('files', [])

        if checkpoint and checkpoint.should_skip(2) and checkpoint.get_data('cog_last_index', -1) >= len(downloaded_files) - 1:
            logger.info("⏭️ PHASE 2: Skipping COG creation (checkpoint)")
            _report_progress(docker_context, 85, 2, 4, "Create COGs", "Skipped (resumed)")
            cog_result = {
                'cog_blobs': checkpoint.get_data('cog_blobs', []),
                'cog_results': checkpoint.get_data('cog_results', []),
                'cog_count': len(checkpoint.get_data('cog_blobs', [])),
                'raster_type': checkpoint.get_data('raster_type'),
            }
        else:
            logger.info(f"🔄 PHASE 2: Creating COGs for {len(downloaded_files)} files...")
            _report_progress(docker_context, 27, 2, 4, "Create COGs", "Starting")

            cog_result = _process_files_to_cogs(
                downloaded_files=downloaded_files,
                cog_dest_path=mount_paths['cogs'],
                params=parameters,
                checkpoint=checkpoint,
                docker_context=docker_context,
                job_id=job_id,
                task_id=task_id
            )

            # Check for interruption
            if cog_result.get('interrupted'):
                logger.warning("🛑 Processing interrupted, returning partial result")
                return {
                    "success": True,
                    "interrupted": True,
                    "result": {
                        "download": download_result,
                        "cogs": cog_result,
                        "message": "Processing interrupted, checkpoint saved"
                    }
                }

            logger.info(f"✅ PHASE 2 complete: {cog_result.get('cog_count', 0)} COGs created")
            _report_progress(docker_context, 85, 2, 4, "Create COGs", "Complete")

            if checkpoint:
                checkpoint.save(phase=2, data={
                    'cog_blobs': cog_result.get('cog_blobs', []),
                    'cog_results': cog_result.get('cog_results', []),
                    'cog_last_index': len(downloaded_files) - 1,
                    'raster_type': cog_result.get('raster_type'),
                })

        # =====================================================================
        # PHASE 3: STAC COLLECTION (85-95%)
        # =====================================================================
        cog_blobs = cog_result.get('cog_blobs', [])

        if checkpoint and checkpoint.should_skip(3):
            logger.info("⏭️ PHASE 3: Skipping STAC (checkpoint)")
            _report_progress(docker_context, 95, 3, 4, "STAC", "Skipped (resumed)")
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            logger.info(f"🔄 PHASE 3: Creating STAC collection...")
            _report_progress(docker_context, 87, 3, 4, "STAC", "Starting")

            stac_result = _create_stac_collection_from_cogs(
                cog_blobs=cog_blobs,
                params=parameters,
                raster_type=cog_result.get('raster_type'),
                docker_context=docker_context,
                job_id=job_id,
                task_id=task_id
            )

            logger.info(f"✅ PHASE 3 complete: Collection {stac_result.get('collection_id')}")
            _report_progress(docker_context, 95, 3, 4, "STAC", "Complete")

            if checkpoint:
                checkpoint.save(phase=3, data={'stac_result': stac_result})

        # =====================================================================
        # PHASE 4: CLEANUP (95-100%)
        # =====================================================================
        if parameters.get('cleanup_temp', True):
            logger.info("🔄 PHASE 4: Cleaning up temp files...")
            _report_progress(docker_context, 97, 4, 4, "Cleanup", "Removing temp files")

            cleanup_result = _cleanup_mount_paths(mount_paths)

            _emit_job_event(job_id, task_id, 1, "cleanup_complete", cleanup_result)

            logger.info(f"✅ PHASE 4 complete: {cleanup_result.get('files_deleted', 0)} files cleaned")
            _report_progress(docker_context, 100, 4, 4, "Cleanup", "Complete")
        else:
            logger.info("⏭️ PHASE 4: Skipping cleanup (disabled)")
            _report_progress(docker_context, 100, 4, 4, "Cleanup", "Skipped")

        # =====================================================================
        # SUCCESS
        # =====================================================================
        total_duration = time.time() - start_time

        logger.info("=" * 70)
        logger.info("✅ RASTER COLLECTION COMPLETE - SUCCESS")
        logger.info(f"   Duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")
        logger.info(f"   Files: {len(blob_list)} → {len(cog_blobs)} COGs")
        if stac_result.get('collection_id'):
            logger.info(f"   STAC: {stac_result.get('collection_id')}")
        logger.info(f"   Peak memory: {get_peak_memory_mb():.1f} MB")
        logger.info("=" * 70)

        return {
            "success": True,
            "result": {
                "download": {
                    "files_downloaded": len(download_result.get('files', [])),
                    "total_mb": download_result.get('total_mb', 0),
                    "duration_seconds": download_result.get('duration_seconds', 0),
                },
                "cogs": {
                    "cog_count": cog_result.get('cog_count', 0),
                    "cog_blobs": cog_blobs,
                    "duration_seconds": cog_result.get('duration_seconds', 0),
                },
                "stac": stac_result,
                "cleanup": cleanup_result,
                "timing": {
                    "total_seconds": round(total_duration, 1),
                    "total_minutes": round(total_duration / 60, 2),
                },
                "peak_memory_mb": round(get_peak_memory_mb(), 1),
            }
        }

    except Exception as e:
        logger.exception(f"❌ RASTER COLLECTION FAILED: {e}")

        _emit_job_event(job_id, task_id, 1, "handler_failed", {
            'error_type': type(e).__name__,
        }, error_message=str(e))

        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "result": {
                "download": download_result,
                "cogs": cog_result,
                "stac": stac_result,
            }
        }


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['raster_collection_complete']
