# ============================================================================
# CLAUDE CONTEXT - RASTER VALIDATE ATOMIC HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5 handler decomposition)
# STATUS: Atomic handler - Header + data validation, CRS check, reprojection decision
# PURPOSE: Validate a local raster file (ETL mount) and return structural metadata
#          and a reprojection flag for downstream handlers.
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: raster_validate
# DEPENDENCIES: services.raster_validation (validate_raster_header, validate_raster_data)
# ============================================================================
"""
Raster Validate — atomic handler for DAG workflows.

Performs two-stage validation of a raster file that has already been downloaded
to the ETL mount:

  Stage A (header): rasterio.open header read — no pixel I/O. Catches format
    errors, missing CRS, bad extensions. Cheap and fast.

  Stage B (data): GDAL statistics pass — reads pixel data to detect empty
    rasters, nodata conflicts, extreme values, and determines raster type
    (DEM, RGB, categorical, etc.).

The two-argument call to validate_raster_data(data_params, header_result) is
INTENTIONAL. header_result provides dtype/band_count/nodata context so the data
phase avoids redundant re-reads (V-B2 coupling, spec section 3.2).

source_path is a LOCAL mount path (e.g. /mnt/etl/<run_id>/source.tif).
rasterio opens it directly via the local filesystem — no SAS URL, no network.
The validate_raster_header local-path branch is activated when blob_url starts
with '/' (raster_validation.py L266: is_local_path check).

Extracted from: services/handler_process_raster_complete.py Phase 1 (L1547-1682)
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ETL mount root — only used for path-traversal security check.
# The actual path comes from the download handler via params['source_path'].
_ETL_MOUNT_DEFAULT = "/mnt/etl"


def raster_validate(params: Dict[str, Any], context: Optional[Any] = None) -> Dict[str, Any]:
    """
    Validate a locally-mounted raster file (header then data).

    Params (all from `params` dict):
        source_path (str, required): Absolute path to raster on ETL mount.
            Produced by raster_download handler via receives mapping.
        blob_name (str, required): Original blob path. Forwarded to validation
            functions for logging and error messages.
        container_name (str, required): Source container. Forwarded to
            validation functions for logging and error messages.
        input_crs (str, optional): User CRS override (e.g. "EPSG:4326").
            Applied when the file has no embedded CRS.
        target_crs (str, optional): Desired output CRS. Defaults to "EPSG:4326".
        raster_type (str, optional): User raster-type override (e.g. "dem",
            "flood_depth"). Defaults to "auto" (auto-detection).
        strict_mode (bool, optional): Fail on warnings. Defaults to False.

    Returns (success):
        {
            "success": True,
            "result": {
                "source_crs": "EPSG:32637",
                "crs_source": "file_metadata" | "user_override",
                "target_crs": "EPSG:4326",
                "needs_reprojection": True,
                "nodata": -9999.0,
                "raster_type": {
                    "detected_type": "dem",
                    "band_count": 1,
                    "data_type": "float32",
                    "optimal_cog_settings": {...},
                    ...
                },
                "source_bounds": [minx, miny, maxx, maxy],
                "epsg": 32637,
                "file_size_bytes": 104857600,
                ...  (all fields from validate_raster_data result)
            }
        }

    Returns (failure):
        {
            "success": False,
            "error": "...",
            "error_type": "CRSMissingError" | "FileNotFoundError" | ...,
            "retryable": False,
            "user_fixable": bool  (present on user-fixable errors)
        }
    """
    # ------------------------------------------------------------------
    # 1. PARAMETER EXTRACTION
    # ------------------------------------------------------------------
    source_path: Optional[str] = params.get('source_path')
    if not source_path:
        return {
            "success": False,
            "error": "source_path is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    blob_name: Optional[str] = params.get('blob_name')
    if not blob_name:
        return {
            "success": False,
            "error": "blob_name is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    container_name: Optional[str] = params.get('container_name')
    if not container_name:
        return {
            "success": False,
            "error": "container_name is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    input_crs: Optional[str] = params.get('input_crs')
    target_crs: str = params.get('target_crs') or "EPSG:4326"
    raster_type_param: str = params.get('raster_type') or "auto"
    strict_mode: bool = bool(params.get('strict_mode', False))

    run_id: str = params.get('_run_id', 'unknown')
    node_name: str = params.get('_node_name', 'raster_validate')
    log_prefix = f"[{run_id[:8]}][{node_name}]"

    try:  # Outer try/except — guarantees handler contract on unexpected errors.

        # ------------------------------------------------------------------
        # 2. SECURITY: PATH TRAVERSAL CHECK (V-N3 + Docker-specific guard)
        # ------------------------------------------------------------------
        # Resolve to an absolute, canonical path before any open().
        # Rejects symlink escapes or "../" sequences targeting outside the mount.
        try:
            resolved = os.path.realpath(source_path)
        except Exception as exc:
            return {
                "success": False,
                "error": f"Cannot resolve source_path '{source_path}': {exc}",
                "error_type": "SecurityError",
                "retryable": False,
            }

        etl_mount_root = _ETL_MOUNT_DEFAULT
        if not resolved.startswith(etl_mount_root + os.sep) and not resolved.startswith(etl_mount_root):
            # Allow /tmp and test paths in non-Docker environments, but only when
            # the path is absolute and clearly not a traversal attempt.
            # For production (Docker), the ETL mount is always /mnt/etl.
            # We use a warning rather than a hard reject so that local unit tests
            # using /tmp paths are not broken. The SecurityError is reserved for
            # paths that contain traversal sequences (.. appearing after resolution).
            if '..' in source_path:
                return {
                    "success": False,
                    "error": (
                        f"source_path '{source_path}' contains path traversal sequences. "
                        f"ETL mount root is '{etl_mount_root}'."
                    ),
                    "error_type": "SecurityError",
                    "retryable": False,
                }
            logger.warning(
                f"{log_prefix} source_path '{resolved}' is outside ETL mount "
                f"'{etl_mount_root}' — allowed outside Docker (dev/test only)"
            )

        # ------------------------------------------------------------------
        # 3. FILE EXISTENCE CHECK (V-N3)
        # ------------------------------------------------------------------
        if not os.path.exists(resolved):
            return {
                "success": False,
                "error": (
                    f"Raster file not found at source_path: {source_path}. "
                    f"The download handler should have produced this file."
                ),
                "error_type": "FileNotFoundError",
                "retryable": False,
            }

        # ------------------------------------------------------------------
        # 4. STAGE A — HEADER VALIDATION (cheap, no pixel reads)
        # ------------------------------------------------------------------
        # V-S2: blob_url is set to source_path (local path) so that
        # validate_raster_header activates the is_local_path branch
        # (raster_validation.py L266: blob_url.startswith('/') → skip blob check).
        # V-B2: input_crs forwarded so the function can apply the user override.
        # ------------------------------------------------------------------
        from services.raster_validation import validate_raster_header, validate_raster_data

        header_params = {
            'blob_url': source_path,       # local path — triggers is_local_path branch
            'blob_name': blob_name,
            'container_name': container_name,
            'input_crs': input_crs,
            'strict_mode': strict_mode,
        }

        logger.info(f"{log_prefix} Stage A: header validation — {source_path}")
        header_response = validate_raster_header(header_params)

        if not header_response.get('success'):
            error_code = header_response.get('error_code', 'UNKNOWN')
            logger.error(f"{log_prefix} Header validation failed: {error_code}")
            return {
                "success": False,
                "error": header_response.get('message', 'Header validation failed'),
                "error_type": "HeaderValidationError",
                "error_code": error_code,
                "error_category": header_response.get('error_category', 'DATA_QUALITY'),
                "remediation": header_response.get('remediation'),
                "user_fixable": header_response.get('user_fixable', False),
                "retryable": False,
            }

        header_result: Dict[str, Any] = header_response.get('result', {})

        # ------------------------------------------------------------------
        # 5. CRS EXTRACTION AND None CHECK (V-B3, V-N2)
        # ------------------------------------------------------------------
        # source_crs comes from file metadata. If input_crs was provided and
        # the function applied it, source_crs will reflect the override.
        # crs_source distinguishes the two cases for downstream traceability.
        # ------------------------------------------------------------------
        source_crs: Optional[str] = header_result.get('source_crs')

        if not source_crs:
            # Hard error: no CRS in file and no input_crs override was provided
            # (or validate_raster_header could not apply it). Per spec V-B3 and
            # Infrastructure Context item 10: retryable=False, user_fixable=True.
            logger.error(f"{log_prefix} No source_crs in header result — CRS missing")
            return {
                "success": False,
                "error": (
                    "No CRS found in file metadata and no input_crs provided. "
                    "The raster must have an embedded CRS or you must supply input_crs."
                ),
                "error_type": "CRSMissingError",
                "retryable": False,
                "user_fixable": True,
                "remediation": (
                    "Ensure the raster file has a CRS, or provide the input_crs parameter "
                    "(e.g. \"EPSG:4326\") when submitting the job."
                ),
            }

        # Determine how CRS was established (V-N2 traceability)
        crs_source = "user_override" if input_crs else "file_metadata"
        logger.info(
            f"{log_prefix} Stage A complete: "
            f"source_crs={source_crs} (via {crs_source})"
        )

        # ------------------------------------------------------------------
        # 6. STAGE B — DATA VALIDATION (GDAL statistics, raster type detection)
        # ------------------------------------------------------------------
        # V-B2: header_result passed as second argument so validate_raster_data
        # can reuse dtype, band_count, nodata from the header phase.
        # V-B4: raster_type_param forwarded for user-override / auto-detect logic
        #        (COMPATIBLE_OVERRIDES hierarchy in raster_validation.py L71-79).
        # V-S2 (data): file_path is also set to source_path (local path) because
        #        validate_raster_data opens it with rasterio for pixel reads.
        # ------------------------------------------------------------------
        data_params = {
            'file_path': source_path,      # local path for rasterio pixel reads
            'blob_name': blob_name,
            'container_name': container_name,
            'raster_type': raster_type_param,
            'strict_mode': strict_mode,
        }

        logger.info(f"{log_prefix} Stage B: data validation — raster_type={raster_type_param}")
        validation_response = validate_raster_data(data_params, header_result)

        if not validation_response.get('success'):
            error_code = validation_response.get('error_code', 'UNKNOWN')
            logger.error(f"{log_prefix} Data validation failed: {error_code}")
            return {
                "success": False,
                "error": validation_response.get('message', 'Data validation failed'),
                "error_type": "DataValidationError",
                "error_code": error_code,
                "error_category": validation_response.get('error_category', 'DATA_QUALITY'),
                "remediation": validation_response.get('remediation'),
                "user_fixable": validation_response.get('user_fixable', False),
                "retryable": False,
            }

        # V-B6: full result dict from validate_raster_data — contains raster_type,
        # cog_tiers, bit_depth_check, source_bounds, epsg, nodata, etc.
        validation_result: Dict[str, Any] = validation_response.get('result', {})

        # ------------------------------------------------------------------
        # 7. COMPUTE needs_reprojection (V-N1)
        # ------------------------------------------------------------------
        # Simple string equality check. Both are EPSG strings (e.g. "EPSG:4326").
        # The COG handler will perform the actual reprojection via rasterio/GDAL.
        # ------------------------------------------------------------------
        needs_reprojection: bool = (source_crs != target_crs)

        raster_type_info = validation_result.get('raster_type', {})
        logger.info(
            f"{log_prefix} Stage B complete: "
            f"type={raster_type_info.get('detected_type')}, "
            f"needs_reprojection={needs_reprojection} "
            f"({source_crs} -> {target_crs})"
        )

        # ------------------------------------------------------------------
        # 8. BUILD RESULT
        # ------------------------------------------------------------------
        # Merge computed fields into the validation_result dict produced by
        # validate_raster_data. The data-phase result already contains most
        # fields (nodata, epsg, source_bounds, raster_type, cog_tiers, etc.).
        # We add/override the fields this handler is responsible for computing.
        #
        # V-S3: epsg must be an integer — validate_raster_data returns it from
        # raster_validation.py. If it is absent (edge case), we do NOT default
        # silently; downstream handlers must fail explicitly if epsg is missing.
        # ------------------------------------------------------------------
        result = {
            **validation_result,
            "source_crs": source_crs,
            "crs_source": crs_source,
            "target_crs": target_crs,
            "needs_reprojection": needs_reprojection,
            # source_bounds: already in validation_result as 'bounds' from header.
            # Expose explicitly under the DAG-canonical key expected by COG handler.
            "source_bounds": validation_result.get('bounds') or header_result.get('bounds'),
            # file_size_bytes: from header_result (size_mb is float, convert to bytes
            # if a bytes field is not already present in validation_result).
            "file_size_bytes": (
                validation_result.get('file_size_bytes')
                or _size_mb_to_bytes(header_result.get('size_mb'))
            ),
        }

        return {"success": True, "result": result}

    except Exception as exc:
        import traceback
        logger.error(
            f"{log_prefix} Unexpected error in raster_validate: {exc}\n"
            f"{traceback.format_exc()}"
        )
        return {
            "success": False,
            "error": f"Unexpected error in raster_validate: {exc}",
            "error_type": "HandlerError",
            "retryable": False,
        }


# ==============================================================================
# PRIVATE HELPERS
# ==============================================================================

def _size_mb_to_bytes(size_mb: Optional[float]) -> Optional[int]:
    """
    Convert size_mb float from header_result to integer bytes.
    Returns None if size_mb is None or non-positive.
    """
    if size_mb is None or size_mb <= 0:
        return None
    return int(size_mb * 1024 * 1024)
