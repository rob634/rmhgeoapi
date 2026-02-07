# ============================================================================
# RASTER COLLECTION COMPLETE HANDLER (Docker)
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Services - Consolidated raster collection handler for Docker worker
# PURPOSE: Process raster collection to COGs with checkpoint-based resume
# CREATED: 30 JAN 2026
# UPDATED: 06 FEB 2026 - Added homogeneity validation (BUG_REFORM Phase 3)
# EXPORTS: raster_collection_complete
# DEPENDENCIES: CheckpointManager, JobEvent, create_stac_collection
# ============================================================================
"""
Raster Collection Complete - Sequential Checkpoint-Based Docker Handler.

Processes a collection of raster files into COGs with STAC registration.
Downloads all source files to temp storage first to avoid OOM issues.

Phases:
    1. DOWNLOAD: Copy all blobs from bronze → temp mount storage
    2. VALIDATE: Homogeneity check - all files must have compatible properties
    3. COG CREATION: Sequential processing with per-file checkpoints
    4. STAC: Create collection and register items (direct call mode)
    5. CLEANUP: Remove temp files (optional)

Resume Support:
    - CheckpointManager tracks phase completion
    - COG phase saves checkpoint after each file
    - Can resume mid-collection on Docker restart

JobEvents:
    - Emits CHECKPOINT events for execution timeline visibility
    - Enables "last successful step" debugging in UI

Homogeneity Validation (06 FEB 2026 - BUG_REFORM):
    - All files must have same band count
    - All files must have same data type
    - All files must have same or compatible CRS
    - Resolution must be within tolerance (±20%)
    - Raster type must match (no mixing RGB with DEM)

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
# PHASE 2: HOMOGENEITY VALIDATION (06 FEB 2026 - BUG_REFORM Phase 3)
# =============================================================================

def _validate_collection_homogeneity(
    downloaded_files: List[Dict],
    job_id: str,
    task_id: str,
    tolerance_percent: float = 20.0
) -> Dict[str, Any]:
    """
    Validate all files in collection have compatible properties.

    Checks:
        - Band count: Must match exactly
        - Data type: Must match exactly
        - CRS: Must match (same EPSG code)
        - Resolution: Must be within tolerance (default ±20%)
        - Raster type: Must be same category (no RGB + DEM mixing)

    Args:
        downloaded_files: List of downloaded file info dicts with 'local_path'
        job_id: Job ID for events
        task_id: Task ID for events
        tolerance_percent: Max resolution difference allowed (default 20%)

    Returns:
        {
            "valid": True/False,
            "reference_file": "first file name",
            "properties": {...},  # Reference properties
            "mismatches": [...],  # List of incompatibilities
            "error_code": "COLLECTION_*" if invalid
        }
    """
    import rasterio
    from core.errors import ErrorCode
    from services.raster_validation import _detect_raster_type

    start_time = time.time()

    _emit_job_event(job_id, task_id, 1, "homogeneity_started", {
        'file_count': len(downloaded_files),
    })

    if len(downloaded_files) < 2:
        logger.info("   Single file collection, skipping homogeneity check")
        return {
            "valid": True,
            "message": "Single file, no homogeneity check needed",
            "file_count": len(downloaded_files)
        }

    mismatches = []
    reference = None
    file_properties = []

    for idx, file_info in enumerate(downloaded_files):
        local_path = file_info['local_path']
        blob_name = file_info.get('blob_name', Path(local_path).name)

        try:
            with rasterio.open(local_path) as src:
                # Extract properties
                props = {
                    "file": blob_name,
                    "local_path": local_path,
                    "band_count": src.count,
                    "dtype": str(src.dtypes[0]),
                    "crs": str(src.crs) if src.crs else None,
                    "crs_epsg": src.crs.to_epsg() if src.crs else None,
                    "resolution": src.res,
                    "bounds": src.bounds,
                    "width": src.width,
                    "height": src.height,
                }

                # Detect raster type (RGB, DEM, etc.)
                try:
                    raster_type = _detect_raster_type(src, props["dtype"])
                    props["raster_type"] = raster_type.get("detected_type", "unknown")
                except Exception:
                    props["raster_type"] = "unknown"

                file_properties.append(props)

                if idx == 0:
                    reference = props
                    logger.info(f"   Reference: {blob_name} ({props['band_count']} bands, {props['dtype']}, {props['crs']})")
                    continue

                # Check band count
                if props["band_count"] != reference["band_count"]:
                    mismatches.append({
                        "type": "BAND_COUNT",
                        "error_code": ErrorCode.COLLECTION_BAND_MISMATCH.value,
                        "file": blob_name,
                        "file_index": idx,
                        "expected": reference["band_count"],
                        "found": props["band_count"],
                        "reference_file": reference["file"],
                        "message": f"Expected {reference['band_count']} bands, found {props['band_count']}"
                    })

                # Check dtype
                if props["dtype"] != reference["dtype"]:
                    mismatches.append({
                        "type": "DTYPE",
                        "error_code": ErrorCode.COLLECTION_DTYPE_MISMATCH.value,
                        "file": blob_name,
                        "file_index": idx,
                        "expected": reference["dtype"],
                        "found": props["dtype"],
                        "reference_file": reference["file"],
                        "message": f"Expected {reference['dtype']}, found {props['dtype']}"
                    })

                # Check CRS
                if props["crs"] != reference["crs"]:
                    mismatches.append({
                        "type": "CRS",
                        "error_code": ErrorCode.COLLECTION_CRS_MISMATCH.value,
                        "file": blob_name,
                        "file_index": idx,
                        "expected": reference["crs"],
                        "found": props["crs"],
                        "reference_file": reference["file"],
                        "message": f"Expected CRS {reference['crs']}, found {props['crs']}"
                    })

                # Check resolution (within tolerance)
                if reference["resolution"] and props["resolution"]:
                    ref_res = reference["resolution"][0]
                    file_res = props["resolution"][0]
                    if ref_res > 0:
                        diff_pct = abs(file_res - ref_res) / ref_res * 100
                        if diff_pct > tolerance_percent:
                            mismatches.append({
                                "type": "RESOLUTION",
                                "error_code": ErrorCode.COLLECTION_RESOLUTION_MISMATCH.value,
                                "file": blob_name,
                                "file_index": idx,
                                "expected": f"{ref_res:.4f}",
                                "found": f"{file_res:.4f}",
                                "difference_percent": round(diff_pct, 1),
                                "tolerance_percent": tolerance_percent,
                                "reference_file": reference["file"],
                                "message": f"Resolution differs by {diff_pct:.1f}% (max {tolerance_percent}%)"
                            })

                # Check raster type (no RGB + DEM mixing)
                if props["raster_type"] != reference["raster_type"]:
                    # Allow unknown types to pass
                    if props["raster_type"] != "unknown" and reference["raster_type"] != "unknown":
                        mismatches.append({
                            "type": "RASTER_TYPE",
                            "error_code": ErrorCode.COLLECTION_TYPE_MISMATCH.value,
                            "file": blob_name,
                            "file_index": idx,
                            "expected": reference["raster_type"],
                            "found": props["raster_type"],
                            "reference_file": reference["file"],
                            "message": f"Expected {reference['raster_type']}, found {props['raster_type']}"
                        })

        except Exception as e:
            logger.error(f"❌ Failed to read {blob_name} for homogeneity check: {e}")
            # File read errors are NODE errors, not WORKFLOW errors
            # Re-raise to be handled by the caller
            raise

    duration_ms = int((time.time() - start_time) * 1000)

    if mismatches:
        # Group mismatches by type for summary
        mismatch_types = list(set(m["type"] for m in mismatches))
        incompatible_files = list(set(m["file"] for m in mismatches))

        # Use the first mismatch type for the primary error code
        primary_error_code = mismatches[0]["error_code"]

        _emit_job_event(job_id, task_id, 1, "homogeneity_failed", {
            'mismatch_count': len(mismatches),
            'mismatch_types': mismatch_types,
            'incompatible_files': incompatible_files,
        }, error_message=f"{len(mismatches)} incompatibilities found", duration_ms=duration_ms)

        logger.warning(f"⚠️ Homogeneity check failed: {len(mismatches)} mismatches in {len(incompatible_files)} files")
        for m in mismatches[:5]:  # Log first 5
            logger.warning(f"   • {m['file']}: {m['message']}")
        if len(mismatches) > 5:
            logger.warning(f"   ... and {len(mismatches) - 5} more")

        return {
            "valid": False,
            "reference_file": reference["file"],
            "reference_properties": {
                "band_count": reference["band_count"],
                "dtype": reference["dtype"],
                "crs": reference["crs"],
                "resolution": reference["resolution"][0] if reference["resolution"] else None,
                "raster_type": reference["raster_type"],
            },
            "mismatches": mismatches,
            "mismatch_summary": {
                "total_mismatches": len(mismatches),
                "mismatch_types": mismatch_types,
                "incompatible_files": incompatible_files,
                "compatible_files": len(downloaded_files) - len(incompatible_files),
            },
            "error_code": primary_error_code,
            "duration_ms": duration_ms,
        }

    _emit_job_event(job_id, task_id, 1, "homogeneity_passed", {
        'file_count': len(downloaded_files),
        'band_count': reference["band_count"],
        'dtype': reference["dtype"],
        'crs': reference["crs"],
        'raster_type': reference["raster_type"],
    }, duration_ms=duration_ms)

    logger.info(f"✅ Homogeneity check passed: {len(downloaded_files)} files compatible")
    logger.info(f"   Properties: {reference['band_count']} bands, {reference['dtype']}, {reference['crs']}, type={reference['raster_type']}")

    return {
        "valid": True,
        "reference_file": reference["file"],
        "reference_properties": {
            "band_count": reference["band_count"],
            "dtype": reference["dtype"],
            "crs": reference["crs"],
            "resolution": reference["resolution"][0] if reference["resolution"] else None,
            "raster_type": reference["raster_type"],
        },
        "file_count": len(downloaded_files),
        "message": f"All {len(downloaded_files)} files are compatible",
        "duration_ms": duration_ms,
    }


def _create_homogeneity_error_response(
    validation_result: Dict[str, Any],
    job_id: str,
    task_id: str
) -> Dict[str, Any]:
    """
    Create user-friendly error response for homogeneity failure.

    Uses the new ErrorResponse Pydantic model from core/errors.py.

    Args:
        validation_result: Result from _validate_collection_homogeneity
        job_id: Job ID
        task_id: Task ID

    Returns:
        Error response dict for return to caller
    """
    from core.errors import (
        ErrorCode, ErrorResponse, ErrorDebug,
        create_error_response_v2
    )

    mismatches = validation_result.get("mismatches", [])
    summary = validation_result.get("mismatch_summary", {})
    reference = validation_result.get("reference_properties", {})

    # Determine primary error code from first mismatch
    error_code_str = validation_result.get("error_code", "COLLECTION_BAND_MISMATCH")
    error_code = ErrorCode(error_code_str)

    # Build user-friendly message
    mismatch_types = summary.get("mismatch_types", [])
    incompatible_files = summary.get("incompatible_files", [])

    if "BAND_COUNT" in mismatch_types:
        message = f"Collection contains rasters with different band counts. Reference file '{validation_result.get('reference_file')}' has {reference.get('band_count')} bands."
    elif "DTYPE" in mismatch_types:
        message = f"Collection contains rasters with different data types. Reference file uses {reference.get('dtype')}."
    elif "CRS" in mismatch_types:
        message = f"Collection contains rasters with different coordinate systems. Reference file uses {reference.get('crs')}."
    elif "RESOLUTION" in mismatch_types:
        message = f"Collection contains rasters with incompatible resolutions (>{validation_result.get('tolerance_percent', 20)}% difference)."
    elif "RASTER_TYPE" in mismatch_types:
        message = f"Collection mixes incompatible raster types. Reference file is {reference.get('raster_type')}."
    else:
        message = "Collection contains incompatible rasters."

    # Build remediation guidance
    if len(incompatible_files) == 1:
        remediation = f"Remove '{incompatible_files[0]}' from the collection or submit it as a separate job."
    elif len(incompatible_files) <= 3:
        files_str = "', '".join(incompatible_files)
        remediation = f"Remove incompatible files ('{files_str}') from the collection or ensure all files have matching properties."
    else:
        remediation = f"{len(incompatible_files)} files are incompatible with the collection. Ensure all files have the same band count, data type, CRS, and resolution before resubmitting."

    # Create structured details
    details = {
        "reference_file": validation_result.get("reference_file"),
        "reference_properties": reference,
        "total_files": validation_result.get("file_count", len(mismatches) + summary.get("compatible_files", 0)),
        "compatible_files": summary.get("compatible_files", 0),
        "incompatible_files": len(incompatible_files),
        "mismatches": mismatches[:10],  # Limit to first 10 for response size
    }

    if len(mismatches) > 10:
        details["additional_mismatches"] = len(mismatches) - 10

    # Create ErrorResponse using v2 factory
    response, debug = create_error_response_v2(
        error_code=error_code,
        message=message,
        remediation=remediation,
        details=details,
        job_id=job_id,
        task_id=task_id,
        handler="raster_collection_complete",
        stage=2,  # Validation is phase 2
    )

    # Return as dict for handler return format
    return {
        "success": False,
        "error": response.error_code,
        "error_code": response.error_code,
        "error_category": response.error_category,
        "error_scope": response.error_scope,
        "message": response.message,
        "remediation": response.remediation,
        "user_fixable": response.user_fixable,
        "retryable": response.retryable,
        "http_status": response.http_status,
        "error_id": response.error_id,
        "details": details,
        # Store full debug in result for job record
        "_debug": debug.model_dump(),
    }


# =============================================================================
# PHASE 3: COG CREATION
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

        # Progress: 25-80% for COG phase (phase 3 of 5)
        progress = 25 + int(((idx - start_index) / (total_files - start_index)) * 55) if total_files > start_index else 25
        _report_progress(docker_context, progress, 3, 5, "Create COGs", f"{idx+1}/{total_files}")

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
    # BUG-012 FIX (01 FEB 2026): detected_type is nested inside raster_type, not at top level
    raster_type_info = None
    if cog_results and cog_results[0].get('validation'):
        v = cog_results[0]['validation']
        # raster_type is a nested dict containing detected_type, confidence, etc.
        rt = v.get('raster_type', {})
        raster_type_info = {
            'detected_type': rt.get('detected_type', 'unknown'),  # BUG-012: Was incorrectly v.get()
            'band_count': v.get('band_count', 3),  # band_count IS at top level
            'data_type': v.get('data_type', 'uint8'),  # data_type IS at top level
        }
        logger.info(f"   Raster type info: {raster_type_info['detected_type']}, {raster_type_info['band_count']} bands")

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

    _report_progress(docker_context, 85, 4, 5, "STAC", "Creating collection")

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
        # Job traceability (02 FEB 2026): Pass job_id for STAC item metadata
        '_job_id': job_id,
        '_job_type': 'process_raster_collection_docker',
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

    _report_progress(docker_context, 90, 4, 5, "STAC", "Complete")

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
    validation_result = {}
    cog_result = {}
    stac_result = {}
    cleanup_result = {}

    try:
        # Setup mount paths (uses config.raster.etl_mount_path)
        mount_paths = _get_mount_paths(job_id, config)
        _ensure_mount_paths(mount_paths)
        logger.info(f"   Mount base: {mount_paths['base']}")

        # =====================================================================
        # PHASE 1: DOWNLOAD (0-20%)
        # =====================================================================
        if checkpoint and checkpoint.should_skip(1):
            logger.info("⏭️ PHASE 1: Skipping download (checkpoint)")
            _report_progress(docker_context, 20, 1, 5, "Download", "Skipped (resumed)")
            download_result = checkpoint.get_data('download_result', {})
        else:
            logger.info("🔄 PHASE 1: Downloading source files...")
            _report_progress(docker_context, 2, 1, 5, "Download", f"Starting ({len(blob_list)} files)")

            download_result = _download_blobs_to_mount(
                blob_list=blob_list,
                container_name=container_name,
                dest_path=mount_paths['source'],
                docker_context=docker_context,
                job_id=job_id,
                task_id=task_id
            )

            logger.info(f"✅ PHASE 1 complete: {download_result.get('total_mb', 0):.1f} MB downloaded")
            _report_progress(docker_context, 20, 1, 5, "Download", "Complete")

            if checkpoint:
                checkpoint.save(phase=1, data={'download_result': download_result})

        # =====================================================================
        # PHASE 2: HOMOGENEITY VALIDATION (20-25%) - BUG_REFORM Phase 3
        # =====================================================================
        downloaded_files = download_result.get('files', [])

        if checkpoint and checkpoint.should_skip(2) and checkpoint.get_data('validation_passed'):
            logger.info("⏭️ PHASE 2: Skipping validation (checkpoint)")
            _report_progress(docker_context, 25, 2, 5, "Validate", "Skipped (resumed)")
            validation_result = checkpoint.get_data('validation_result', {"valid": True})
        else:
            logger.info("🔄 PHASE 2: Validating collection homogeneity...")
            _report_progress(docker_context, 22, 2, 5, "Validate", f"Checking {len(downloaded_files)} files")

            validation_result = _validate_collection_homogeneity(
                downloaded_files=downloaded_files,
                job_id=job_id,
                task_id=task_id,
                tolerance_percent=parameters.get('resolution_tolerance_percent', 20.0)
            )

            if not validation_result.get("valid"):
                # Collection is incompatible - return structured error
                logger.error("❌ PHASE 2 failed: Collection homogeneity check failed")
                _report_progress(docker_context, 25, 2, 5, "Validate", "FAILED - incompatible files")

                error_response = _create_homogeneity_error_response(
                    validation_result=validation_result,
                    job_id=job_id,
                    task_id=task_id
                )

                # Cleanup temp files before returning error
                if parameters.get('cleanup_temp', True):
                    _cleanup_mount_paths(mount_paths)

                return error_response

            logger.info(f"✅ PHASE 2 complete: All {len(downloaded_files)} files compatible")
            _report_progress(docker_context, 25, 2, 5, "Validate", "Complete")

            if checkpoint:
                checkpoint.save(phase=2, data={
                    'validation_result': validation_result,
                    'validation_passed': True,
                })

        # =====================================================================
        # PHASE 3: COG CREATION (25-80%)
        # =====================================================================

        if checkpoint and checkpoint.should_skip(3) and checkpoint.get_data('cog_last_index', -1) >= len(downloaded_files) - 1:
            logger.info("⏭️ PHASE 3: Skipping COG creation (checkpoint)")
            _report_progress(docker_context, 80, 3, 5, "Create COGs", "Skipped (resumed)")

            # BUG-012 FIX (01 FEB 2026): Re-derive raster_type if missing from older checkpoint
            cog_results_checkpoint = checkpoint.get_data('cog_results', [])
            raster_type_checkpoint = checkpoint.get_data('raster_type')

            if not raster_type_checkpoint and cog_results_checkpoint:
                # Re-derive from first result's validation
                v = cog_results_checkpoint[0].get('validation', {})
                rt = v.get('raster_type', {})
                if v.get('band_count'):
                    raster_type_checkpoint = {
                        'detected_type': rt.get('detected_type', 'unknown'),
                        'band_count': v.get('band_count', 3),
                        'data_type': v.get('data_type', 'uint8'),
                    }
                    logger.info(f"   Re-derived raster_type from checkpoint validation: {raster_type_checkpoint}")

            cog_result = {
                'cog_blobs': checkpoint.get_data('cog_blobs', []),
                'cog_results': cog_results_checkpoint,
                'cog_count': len(checkpoint.get_data('cog_blobs', [])),
                'raster_type': raster_type_checkpoint,
            }
        else:
            logger.info(f"🔄 PHASE 3: Creating COGs for {len(downloaded_files)} files...")
            _report_progress(docker_context, 27, 3, 5, "Create COGs", "Starting")

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

            logger.info(f"✅ PHASE 3 complete: {cog_result.get('cog_count', 0)} COGs created")
            _report_progress(docker_context, 80, 3, 5, "Create COGs", "Complete")

            if checkpoint:
                checkpoint.save(phase=3, data={
                    'cog_blobs': cog_result.get('cog_blobs', []),
                    'cog_results': cog_result.get('cog_results', []),
                    'cog_last_index': len(downloaded_files) - 1,
                    'raster_type': cog_result.get('raster_type'),
                })

        # =====================================================================
        # PHASE 4: STAC COLLECTION (80-92%)
        # =====================================================================
        cog_blobs = cog_result.get('cog_blobs', [])

        if checkpoint and checkpoint.should_skip(4):
            logger.info("⏭️ PHASE 4: Skipping STAC (checkpoint)")
            _report_progress(docker_context, 92, 4, 5, "STAC", "Skipped (resumed)")
            stac_result = checkpoint.get_data('stac_result', {})
        else:
            logger.info(f"🔄 PHASE 4: Creating STAC collection...")
            _report_progress(docker_context, 82, 4, 5, "STAC", "Starting")

            stac_result = _create_stac_collection_from_cogs(
                cog_blobs=cog_blobs,
                params=parameters,
                raster_type=cog_result.get('raster_type'),
                docker_context=docker_context,
                job_id=job_id,
                task_id=task_id
            )

            logger.info(f"✅ PHASE 4 complete: Collection {stac_result.get('collection_id')}")
            _report_progress(docker_context, 92, 4, 5, "STAC", "Complete")

            if checkpoint:
                checkpoint.save(phase=4, data={'stac_result': stac_result})

        # =====================================================================
        # PHASE 5: CLEANUP (92-100%)
        # =====================================================================
        if parameters.get('cleanup_temp', True):
            logger.info("🔄 PHASE 5: Cleaning up temp files...")
            _report_progress(docker_context, 95, 5, 5, "Cleanup", "Removing temp files")

            cleanup_result = _cleanup_mount_paths(mount_paths)

            _emit_job_event(job_id, task_id, 1, "cleanup_complete", cleanup_result)

            logger.info(f"✅ PHASE 5 complete: {cleanup_result.get('files_deleted', 0)} files cleaned")
            _report_progress(docker_context, 100, 5, 5, "Cleanup", "Complete")
        else:
            logger.info("⏭️ PHASE 5: Skipping cleanup (disabled)")
            _report_progress(docker_context, 100, 5, 5, "Cleanup", "Skipped")

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
                "validation": {
                    "passed": True,
                    "file_count": validation_result.get('file_count', len(downloaded_files)),
                    "reference_properties": validation_result.get('reference_properties', {}),
                    "duration_ms": validation_result.get('duration_ms', 0),
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
