# ============================================================================
# RASTER VALIDATION SERVICE
# ============================================================================
# STATUS: Service layer - Raster file validation and analysis
# PURPOSE: Validate raster files before COG processing, determine output tiers
# LAST_REVIEWED: 26 FEB 2026
# REVIEW_STATUS: Split into header/data phases for accurate GDAL statistics
# EXPORTS: validate_raster, validate_raster_header, validate_raster_data
# ============================================================================
"""
Raster Validation Service - Stage 1 of Raster Pipeline.

Validates raster files before COG processing and determines applicable output tiers.

Validation Steps:
    1. File readability check
    2. CRS validation (file metadata, user override, sanity checks)
    3. Bit-depth efficiency analysis (flag 64-bit data as CRITICAL)
    4. Data quality checks (Phase 4 BUG_REFORM - 06 FEB 2026):
       - Mostly-empty detection (RASTER_EMPTY: 99%+ nodata)
       - Nodata conflict detection (RASTER_NODATA_CONFLICT)
       - Extreme value detection (RASTER_EXTREME_VALUES: 1e38 in DEMs)
    5. Raster type detection (RGB, RGBA, DEM, categorical, multispectral,
       continuous, vegetation_index — 12 FEB 2026 expanded)
    6. Type compatibility validation (hierarchical — 12 FEB 2026, replaces strict mismatch)
    7. Bounds sanity checks
    8. Optimal COG settings recommendation
    9. COG tier compatibility detection

COG Tier Detection:
    VISUALIZATION (JPEG): RGB only (3 bands, uint8)
    ANALYSIS (DEFLATE): Universal (all raster types)
    ARCHIVE (LZW): Universal (all raster types)

Error Codes (BUG_REFORM):
    RASTER_EMPTY: File is 99%+ nodata - waste of resources
    RASTER_NODATA_CONFLICT: Nodata value found in real data range
    RASTER_EXTREME_VALUES: DEM with 1e38 values (unset nodata)
    RASTER_64BIT_REJECTED: Policy violation (64-bit data types)
    RASTER_TYPE_MISMATCH: User type incompatible with detected type

Exports:
    validate_raster: Validation handler function
    COMPATIBLE_OVERRIDES: Hierarchical type compatibility map
"""

import sys
import logging
from typing import Any, Dict, Optional

# F7.21: Type-safe result models (25 JAN 2026)
from core.models.raster_results import (
    RasterTypeInfo,
    COGTierInfo,
    BitDepthCheck,
    MemoryEstimation,
    RasterValidationData,
    RasterValidationResult,
)

logger = logging.getLogger(__name__)


# ============================================================================
# HIERARCHICAL TYPE COMPATIBILITY (12 FEB 2026)
# ============================================================================
# Domain types that refine physical detections. When a user specifies a domain
# type (e.g. flood_depth) and the auto-detector sees a compatible physical type
# (e.g. dem or continuous), the user's type is accepted and used going forward.
# Key = user-specified type, Value = set of acceptable physical detections.
COMPATIBLE_OVERRIDES = {
    'flood_depth': {'dem', 'continuous', 'unknown'},
    'flood_probability': {'dem', 'continuous', 'unknown'},
    'hydrology': {'dem', 'continuous', 'unknown'},
    'temporal': {'dem', 'continuous', 'categorical', 'unknown'},
    'population': {'dem', 'continuous', 'unknown'},
    'vegetation_index': {'dem', 'continuous', 'unknown'},
    'continuous': {'dem', 'continuous', 'unknown'},
}

# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import numpy as np
    import rasterio
    from rasterio.enums import ColorInterp
    from rasterio.windows import Window
    return np, rasterio, ColorInterp, Window


def validate_raster_header(params: dict) -> dict:
    """
    Header-only validation of a raster file (no pixel data reads).

    Performs cheap checks that catch garbage files before download:
    - File extension validation
    - Blob existence verification
    - TIFF header readability (rasterio.open — header only)
    - GDAL driver check (must be GTiff)
    - Metadata extraction (band_count, dtype, shape, bounds, nodata)
    - Memory footprint estimation
    - CRS validation

    Does NOT read pixel data. For data quality checks (nodata percentage,
    extreme values, raster type detection), use validate_raster_data().

    Args:
        params: Task parameters dict with:
            - blob_url: Azure blob URL with SAS token (or local file path)
            - blob_name: Blob path (for logging)
            - container_name: Container name (for logging)
            - input_crs: (Optional) User-provided CRS override
            - strict_mode: (Optional) Fail on warnings
            - _skip_validation: (Optional) TESTING ONLY - skip all validation

    Returns:
        dict: {
            "success": True/False,
            "result": {
                "valid": True,
                "source_blob": str,
                "container_name": str,
                "source_crs": str,
                "crs_source": str,
                "bounds": [minx, miny, maxx, maxy],
                "shape": [height, width],
                "band_count": int,
                "dtype": str,
                "data_type": str,
                "nodata": value,
                "size_mb": float,
                "memory_estimation": {...},
                "warnings": [...]
            },
            "error": "ERROR_CODE" (if failed),
            "message": "Error description" (if failed)
        }
    """
    import traceback

    # STEP 0: Initialize logger
    logger = None
    task_id = params.get('_task_id')
    try:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_header")
        logger.info("🚀 [HEADER] Handler entry - validate_raster_header called")
        logger.debug(f"   Params keys: {list(params.keys())}")
        logger.debug(f"   blob_name: {params.get('blob_name', 'MISSING')}")
    except Exception as e:
        print(f"❌ STEP 0 FAILED: Logger initialization error: {e}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": "LOGGER_INIT_FAILED",
            "message": f"Failed to initialize logger: {e}",
            "blob_name": params.get("blob_name")
        }

    # STEP 1: Extract and validate parameters
    try:
        blob_url = params.get('blob_url')
        blob_name = params.get('blob_name', 'unknown')
        container_name = params.get('container_name', params.get('container', 'unknown'))
        input_crs = params.get('input_crs') or params.get('source_crs')
        strict_mode = params.get('strict_mode', False)
        skip_validation = params.get('_skip_validation', False)

        logger.info(f"✅ [HEADER] STEP 1: Parameters extracted - blob={blob_name}, container={container_name}")

        if not blob_url:
            logger.error("❌ [HEADER] STEP 1 FAILED: blob_url parameter is required")
            return {
                "success": False,
                "error": "MISSING_PARAMETER",
                "message": "blob_url parameter is required",
                "blob_name": blob_name,
                "container_name": container_name
            }
    except Exception as e:
        logger.error(f"❌ [HEADER] STEP 1 FAILED: Parameter extraction error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "PARAMETER_ERROR",
            "message": f"Failed to extract parameters: {e}",
            "traceback": traceback.format_exc()
        }

    # TESTING ONLY: Skip validation if requested
    if skip_validation:
        logger.warning(f"⏭️  VALIDATION SKIPPED: _skip_validation=True")
        return {
            "success": True,
            "result": {
                "valid": True,
                "validation_skipped": True,
                "message": "Validation skipped for testing purposes"
            }
        }

    # STEP 2: Lazy import rasterio and numpy
    try:
        logger.info("🔄 [HEADER] STEP 2: Lazy loading rasterio dependencies...")
        np, rasterio, ColorInterp, Window = _lazy_imports()
        logger.info("✅ [HEADER] STEP 2: Dependencies loaded successfully")
    except ImportError as e:
        logger.error(f"❌ [HEADER] STEP 2 FAILED: Import error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "message": f"Failed to import dependencies: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }
    except Exception as e:
        logger.error(f"❌ [HEADER] STEP 2 FAILED: Unexpected error during import: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "error_type": type(e).__name__,
            "message": f"Unexpected error loading dependencies: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }

    # STEP 2b: File extension validation
    logger.info("🔄 [HEADER] STEP 2b: Validating file extension...")
    ext = blob_name.rsplit('.', 1)[-1].lower() if '.' in blob_name else ''
    if ext not in {'tif', 'tiff', 'geotiff'}:
        from core.errors import ErrorCode, create_error_response
        if ext == 'nc':
            msg = (
                f"NetCDF (.nc) support is under development. "
                f"Currently only GeoTIFF (.tif, .tiff, .geotiff) files are accepted."
            )
        else:
            msg = (
                f"Unsupported file format '.{ext}' for file '{blob_name}'. "
                f"Only GeoTIFF (.tif, .tiff, .geotiff) files are accepted."
            )
        logger.error(f"❌ [HEADER] STEP 2b FAILED: {msg}")
        return create_error_response(
            ErrorCode.INVALID_FORMAT,
            msg,
            details={"blob_name": blob_name, "extension": ext,
                     "accepted_extensions": [".tif", ".tiff", ".geotiff"]}
        )
    logger.info(f"✅ [HEADER] STEP 2b: File extension '.{ext}' is valid")

    # STEP 3a: Pre-flight blob existence check
    # Skip for local file paths (used in data phase and tiled mount)
    is_local_path = blob_url.startswith('/') or blob_url.startswith('.')
    if not is_local_path:
        try:
            logger.info("🔄 [HEADER] STEP 3a: Pre-flight blob validation...")

            from infrastructure.blob import BlobRepository
            from core.errors import ErrorCode, create_error_response
            blob_repo = BlobRepository.for_zone("bronze")

            if not blob_repo.container_exists(container_name):
                error_msg = (
                    f"Container '{container_name}' does not exist in storage account "
                    f"'{blob_repo.account_name}'"
                )
                logger.error(f"❌ [HEADER] STEP 3a FAILED: {error_msg}")
                return create_error_response(
                    ErrorCode.CONTAINER_NOT_FOUND,
                    error_msg,
                    details={
                        "container_name": container_name,
                        "storage_account": blob_repo.account_name,
                        "blob_name": blob_name,
                    }
                )

            if not blob_repo.blob_exists(container_name, blob_name):
                error_msg = (
                    f"File '{blob_name}' not found in existing container '{container_name}' "
                    f"(storage account: '{blob_repo.account_name}')"
                )
                logger.error(f"❌ [HEADER] STEP 3a FAILED: {error_msg}")
                return create_error_response(
                    ErrorCode.FILE_NOT_FOUND,
                    error_msg,
                    remediation=f"Verify blob path spelling. Use /api/containers/{container_name}/blobs to list available files.",
                    details={
                        "blob_name": blob_name,
                        "container_name": container_name,
                        "storage_account": blob_repo.account_name,
                    }
                )

            logger.info("✅ [HEADER] STEP 3a: Blob exists validation passed")

        except Exception as e:
            from core.errors import ErrorCode, create_error_response
            logger.error(f"❌ [HEADER] STEP 3a FAILED: Validation error: {e}\n{traceback.format_exc()}")
            return create_error_response(
                ErrorCode.VALIDATION_ERROR,
                f"Failed to validate blob existence: {e}",
                details={
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc(),
                }
            )

    # STEP 3: Open raster file (header read only)
    try:
        logger.info(f"🔄 [HEADER] STEP 3: Opening raster file...")
        logger.debug(f"   URL/Path: {blob_url[:100]}...")
        src = rasterio.open(blob_url)
        logger.info(f"✅ [HEADER] STEP 3: File opened successfully - {src.count} bands, {src.shape}")

        from util_logger import log_memory_checkpoint
        log_memory_checkpoint(logger, "After GDAL open (header)", context_id=task_id)

        # STEP 3b: GDAL driver check
        if src.driver != 'GTiff':
            logger.error(f"❌ [HEADER] STEP 3b FAILED: File is {src.driver}, not GTiff")
            return {
                "success": False,
                "error": "INVALID_FORMAT",
                "message": (
                    f"File '{blob_name}' has a .tif extension but is actually "
                    f"a {src.driver} format (detected by GDAL). "
                    f"This is not a GeoTIFF. "
                    f"Convert: gdal_translate -of GTiff '{blob_name}' output.tif"
                ),
                "blob_name": blob_name,
                "container_name": container_name,
                "detected_driver": src.driver
            }
    except Exception as e:
        logger.error(f"❌ [HEADER] STEP 3 FAILED: Cannot open raster file: {e}\n{traceback.format_exc()}")

        error_str = str(e).lower()
        if 'not recognized as a supported file format' in error_str:
            user_message = (
                f"File '{blob_name}' is not a valid raster image. "
                f"It may be corrupted, a text file, PDF, ZIP archive, or other non-raster format. "
                f"Verify the file opens in QGIS or with 'gdalinfo {blob_name}' before uploading."
            )
        elif 'http' in error_str or 'curl' in error_str:
            user_message = (
                f"Could not download file '{blob_name}' from storage. "
                f"This is likely a transient network issue. "
                f"Re-upload the file or resubmit the job."
            )
        elif 'ireadblock' in error_str or 'tiffread' in error_str:
            user_message = (
                f"File '{blob_name}' has a valid TIFF header but the pixel data is corrupted. "
                f"The upload may have been interrupted or the source file is damaged. "
                f"Re-upload the file or re-export from the source application."
            )
        elif 'no such file' in error_str or 'does not exist' in error_str:
            user_message = (
                f"File '{blob_name}' was not found at the expected storage path. "
                f"Check the container name and file path are correct."
            )
        else:
            user_message = (
                f"Cannot open raster file '{blob_name}'. "
                f"The file may be corrupted or in an unsupported format. "
                f"Verify the file locally with 'gdalinfo {blob_name}' before re-uploading."
            )

        return {
            "success": False,
            "error": "FILE_UNREADABLE",
            "message": user_message,
            "gdal_error": str(e),
            "blob_name": blob_name,
            "container_name": container_name,
            "blob_url_prefix": blob_url[:100] if blob_url else None,
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }

    # STEP 4: Extract basic file information (header metadata only)
    try:
        with src:
            band_count = src.count
            dtype = src.dtypes[0]
            shape = src.shape
            bounds = src.bounds
            nodata = src.nodata
            logger.info(f"✅ [HEADER] STEP 4: File info - {band_count} bands, {dtype}, shape {shape}")
            logger.debug(f"   Bounds: {bounds}, nodata: {nodata}")

            from util_logger import log_memory_checkpoint
            log_memory_checkpoint(logger, "After metadata extraction (header)",
                                  context_id=task_id,
                                  band_count=band_count,
                                  shape_height=shape[0],
                                  shape_width=shape[1])

            warnings = []

            # STEP 4b: Memory footprint estimation
            try:
                logger.info("🔄 [HEADER] STEP 4b: Estimating memory footprint...")
                memory_estimation = _estimate_memory_footprint(
                    width=shape[1],
                    height=shape[0],
                    band_count=band_count,
                    dtype=dtype
                )
                logger.info(
                    f"✅ [HEADER] STEP 4b: Memory estimation - "
                    f"uncompressed: {memory_estimation['uncompressed_gb']:.2f}GB, "
                    f"strategy: {memory_estimation['processing_strategy']}"
                )
                for mem_warning in memory_estimation.get("warnings", []):
                    warnings.append(mem_warning)
            except Exception as e:
                logger.warning(f"⚠️  [HEADER] STEP 4b: Memory estimation failed (non-fatal): {e}")
                memory_estimation = {
                    "error": str(e),
                    "uncompressed_gb": None,
                    "processing_strategy": "unknown"
                }

            # STEP 5: CRS validation
            try:
                logger.info("🔄 [HEADER] STEP 5: Validating CRS...")
                crs_result = _validate_crs(src, input_crs, bounds, skip_validation)
                if not crs_result["success"]:
                    logger.error(f"❌ [HEADER] STEP 5 FAILED: CRS validation failed - {crs_result.get('message', 'unknown')}")
                    return crs_result

                source_crs = crs_result["source_crs"]
                crs_source = crs_result["crs_source"]
                logger.info(f"✅ [HEADER] STEP 5: CRS validated - {source_crs} (source: {crs_source})")

                if "warning" in crs_result:
                    warnings.append(crs_result["warning"])
            except Exception as e:
                logger.error(f"❌ [HEADER] STEP 5 FAILED: CRS validation error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "CRS_VALIDATION_ERROR",
                    "message": f"CRS validation failed: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

            # Build header-only result (no raster_type, cog_tiers, bit_depth_check)
            try:
                memory_estimation_model = None
                if memory_estimation and not memory_estimation.get("error"):
                    memory_estimation_model = MemoryEstimation(
                        uncompressed_gb=memory_estimation.get("uncompressed_gb"),
                        estimated_peak_gb=memory_estimation.get("estimated_peak_gb"),
                        system_ram_gb=memory_estimation.get("system_ram_gb"),
                        cpu_count=memory_estimation.get("cpu_count"),
                        safe_threshold_gb=memory_estimation.get("safe_threshold_gb"),
                        processing_strategy=memory_estimation.get("processing_strategy"),
                        gdal_config=memory_estimation.get("gdal_config"),
                        warnings=memory_estimation.get("warnings", [])
                    )

                validation_data = RasterValidationData(
                    valid=True,
                    source_blob=blob_name,
                    container_name=container_name,
                    source_crs=str(source_crs),
                    crs_source=crs_source,
                    bounds=list(bounds),
                    shape=list(shape),
                    band_count=band_count,
                    dtype=str(dtype),
                    data_type=str(dtype),
                    size_mb=params.get('size_mb', 0),
                    nodata=nodata,
                    memory_estimation=memory_estimation_model,
                    warnings=warnings
                )

                result = RasterValidationResult(
                    success=True,
                    result=validation_data
                )

                logger.info(f"✅ [HEADER] COMPLETE: CRS={source_crs}, bands={band_count}, dtype={dtype}")
                return result.model_dump()

            except Exception as e:
                logger.error(f"❌ [HEADER] Result build error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "RESULT_BUILD_ERROR",
                    "message": f"Failed to build header validation result: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

    except Exception as e:
        logger.error(f"❌ [HEADER] Unexpected error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "VALIDATION_ERROR",
            "error_type": type(e).__name__,
            "message": f"Unexpected header validation error: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }


def validate_raster_data(data_params: dict, header_result: dict) -> dict:
    """
    Data-phase validation using GDAL statistics on a file (local or remote).

    Runs pixel-level quality checks that require reading data:
    - GDAL band statistics (streaming, O(1) memory)
    - Block-by-block nodata percentage (accurate across ALL pixels)
    - Bit-depth efficiency analysis
    - Data quality checks (empty, nodata conflict, extreme values)
    - Raster type detection (DEM, RGB, categorical, etc.)
    - COG tier compatibility

    Merges data-phase results into header_result to produce a complete
    RasterValidationResult-compatible dict.

    Args:
        data_params: Dict with:
            - file_path: Local file path or SAS URL to read data from
            - blob_name: Blob path (for logging/error messages)
            - container_name: Container name (for logging/error messages)
            - raster_type: Expected raster type ('auto', 'rgb', 'dem', etc.)
            - strict_mode: If True, fail on warnings
        header_result: The 'result' dict from validate_raster_header()

    Returns:
        dict: Complete validation result compatible with RasterValidationResult:
            {
                "success": True/False,
                "result": {
                    ...header fields...,
                    "raster_type": RasterTypeInfo,
                    "cog_tiers": COGTierInfo,
                    "bit_depth_check": BitDepthCheck,
                },
                "error": "ERROR_CODE" (if failed),
                "message": "Error description" (if failed)
            }
    """
    import traceback

    # Initialize logger
    try:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_data")
        logger.info("🚀 [DATA] Handler entry - validate_raster_data called")
    except Exception as e:
        print(f"❌ [DATA] Logger init failed: {e}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": "LOGGER_INIT_FAILED",
            "message": f"Failed to initialize logger: {e}",
        }

    # Extract parameters
    file_path = data_params.get('file_path')
    blob_name = data_params.get('blob_name', 'unknown')
    container_name = data_params.get('container_name', 'unknown')
    raster_type_param = data_params.get('raster_type', 'auto')
    strict_mode = data_params.get('strict_mode', False)

    # Extract header metadata
    dtype = header_result.get('dtype', 'unknown')
    band_count = header_result.get('band_count', 1)
    nodata = header_result.get('nodata')

    if not file_path:
        logger.error("❌ [DATA] file_path parameter is required")
        return {
            "success": False,
            "error": "MISSING_PARAMETER",
            "message": "file_path parameter is required for data validation",
        }

    try:
        np, rasterio, ColorInterp, Window = _lazy_imports()
    except Exception as e:
        logger.error(f"❌ [DATA] Import error: {e}")
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "message": f"Failed to import dependencies: {e}",
            "traceback": traceback.format_exc()
        }

    try:
        # Open file for data reads
        logger.info(f"🔄 [DATA] Opening file for data validation...")
        with rasterio.open(file_path) as src:

            # ============================================================
            # STEP D1: Compute GDAL band statistics
            # ============================================================
            logger.info("🔄 [DATA] STEP D1: Computing GDAL band statistics...")
            try:
                band_stats = _compute_band_statistics(src)
                stats_band1 = band_stats.get(1)
                if stats_band1:
                    logger.info(f"✅ [DATA] STEP D1: Band stats computed - "
                                f"min={stats_band1['min']:.4f}, max={stats_band1['max']:.4f}")
                else:
                    logger.warning("⚠️ [DATA] STEP D1: Band 1 statistics unavailable")
            except Exception as e:
                logger.warning(f"⚠️ [DATA] STEP D1: Band statistics failed (non-fatal): {e}")
                band_stats = {}

            # ============================================================
            # STEP D2: Compute accurate nodata percentage
            # ============================================================
            logger.info("🔄 [DATA] STEP D2: Computing nodata percentage (full scan)...")
            try:
                nodata_percent = _compute_nodata_percentage(src, nodata)
                logger.info(f"✅ [DATA] STEP D2: Nodata percentage: {nodata_percent:.1f}%")
            except Exception as e:
                logger.warning(f"⚠️ [DATA] STEP D2: Nodata scan failed (non-fatal): {e}")
                nodata_percent = 0.0

            # Collect warnings from data phase
            warnings = list(header_result.get('warnings', []))

            # ============================================================
            # STEP D3: Bit-depth efficiency check
            # ============================================================
            try:
                logger.info("🔄 [DATA] STEP D3: Checking bit-depth efficiency...")
                bit_depth_result = _check_bit_depth_efficiency(band_stats, dtype, strict_mode)

                if "warning" in bit_depth_result:
                    warnings.append(bit_depth_result["warning"])
                    if strict_mode and bit_depth_result["warning"].get("severity") == "CRITICAL":
                        logger.error("❌ [DATA] STEP D3: CRITICAL bit-depth policy violation")
                        return {
                            "success": False,
                            "error": "BIT_DEPTH_POLICY_VIOLATION",
                            "message": bit_depth_result["warning"]["message"],
                            "bit_depth_check": bit_depth_result,
                            "blob_name": blob_name,
                            "container_name": container_name
                        }

                logger.info(f"✅ [DATA] STEP D3: Bit-depth check - efficient: {bit_depth_result.get('efficient', True)}")
            except Exception as e:
                logger.error(f"❌ [DATA] STEP D3: Bit-depth check error: {e}\n{traceback.format_exc()}")
                bit_depth_result = {"efficient": True, "current_dtype": str(dtype), "reason": f"Check failed: {e}"}

            # ============================================================
            # STEP D4: Data quality checks
            # ============================================================
            try:
                logger.info("🔄 [DATA] STEP D4: Performing data quality checks...")
                data_quality_result = _check_data_quality(
                    band_stats, nodata_percent, nodata, dtype,
                    blob_name, container_name, strict_mode
                )

                if not data_quality_result["success"]:
                    logger.error(f"❌ [DATA] STEP D4: {data_quality_result.get('error_code') or data_quality_result.get('error', 'DATA_QUALITY_ERROR')}")
                    return data_quality_result

                for dq_warning in data_quality_result.get("warnings", []):
                    warnings.append(dq_warning)

                logger.info(f"✅ [DATA] STEP D4: Data quality checks passed "
                            f"(nodata: {nodata_percent:.1f}%)")
            except Exception as e:
                logger.error(f"❌ [DATA] STEP D4: Data quality check error: {e}\n{traceback.format_exc()}")
                warnings.append({
                    "type": "DATA_QUALITY_CHECK_FAILED",
                    "severity": "LOW",
                    "message": f"Could not complete data quality checks: {e}"
                })

            # ============================================================
            # STEP D5: Raster type detection
            # ============================================================
            try:
                logger.info("🔄 [DATA] STEP D5: Detecting raster type...")
                type_result = _detect_raster_type(src, band_stats, raster_type_param)
                if not type_result["success"]:
                    logger.error(f"❌ [DATA] STEP D5: Type detection failed")
                    return type_result

                detected_type = type_result["detected_type"]
                logger.info(f"✅ [DATA] STEP D5: Raster type: {detected_type} "
                            f"(confidence: {type_result.get('confidence', 'UNKNOWN')})")
            except Exception as e:
                logger.error(f"❌ [DATA] STEP D5: Type detection error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "TYPE_DETECTION_ERROR",
                    "message": f"Type detection failed: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

            # ============================================================
            # STEP D6: Optimal COG settings
            # ============================================================
            try:
                optimal_settings = _get_optimal_cog_settings(detected_type)
            except Exception as e:
                logger.warning(f"⚠️ [DATA] STEP D6: COG settings error (using defaults): {e}")
                optimal_settings = {"compression": "deflate", "overview_resampling": "cubic", "reproject_resampling": "cubic"}

            # ============================================================
            # STEP D7: Determine applicable COG tiers
            # ============================================================
            try:
                from config import determine_applicable_tiers
                applicable_tiers = determine_applicable_tiers(band_count, str(dtype))
                logger.info(f"✅ [DATA] STEP D7: {len(applicable_tiers)} tiers: {applicable_tiers}")
            except Exception as e:
                logger.warning(f"⚠️ [DATA] STEP D7: Tier detection error: {e}")
                applicable_tiers = ['visualization', 'analysis', 'archive']

            # ============================================================
            # STEP D8: Build merged result
            # ============================================================
            try:
                raster_type_info = RasterTypeInfo(
                    detected_type=detected_type,
                    confidence=type_result.get("confidence", "UNKNOWN"),
                    evidence=type_result.get("evidence", []),
                    type_source=type_result.get("type_source", "auto_detected"),
                    optimal_cog_settings=optimal_settings,
                    band_count=band_count,
                    data_type=str(dtype)
                )

                cog_tier_info = COGTierInfo(
                    applicable_tiers=applicable_tiers,
                    total_compatible=len(applicable_tiers),
                    incompatible_reason="JPEG requires RGB (3 bands, uint8)" if 'visualization' not in applicable_tiers else None
                )

                bit_depth_info = BitDepthCheck(
                    efficient=bit_depth_result.get("efficient", True),
                    current_dtype=str(dtype),
                    reason=bit_depth_result.get("reason", "Unknown"),
                    recommended_dtype=bit_depth_result.get("recommended_dtype"),
                    potential_savings_percent=bit_depth_result.get("potential_savings_percent")
                )

                # Build memory estimation from header_result if available
                memory_estimation_model = None
                mem_est = header_result.get('memory_estimation')
                if mem_est and not isinstance(mem_est, type(None)):
                    memory_estimation_model = MemoryEstimation(
                        uncompressed_gb=mem_est.get("uncompressed_gb") if isinstance(mem_est, dict) else getattr(mem_est, 'uncompressed_gb', None),
                        estimated_peak_gb=mem_est.get("estimated_peak_gb") if isinstance(mem_est, dict) else getattr(mem_est, 'estimated_peak_gb', None),
                        system_ram_gb=mem_est.get("system_ram_gb") if isinstance(mem_est, dict) else getattr(mem_est, 'system_ram_gb', None),
                        cpu_count=mem_est.get("cpu_count") if isinstance(mem_est, dict) else getattr(mem_est, 'cpu_count', None),
                        safe_threshold_gb=mem_est.get("safe_threshold_gb") if isinstance(mem_est, dict) else getattr(mem_est, 'safe_threshold_gb', None),
                        processing_strategy=mem_est.get("processing_strategy") if isinstance(mem_est, dict) else getattr(mem_est, 'processing_strategy', None),
                        gdal_config=mem_est.get("gdal_config") if isinstance(mem_est, dict) else getattr(mem_est, 'gdal_config', None),
                        warnings=mem_est.get("warnings", []) if isinstance(mem_est, dict) else getattr(mem_est, 'warnings', []),
                    )

                # Merge header fields with data fields
                validation_data = RasterValidationData(
                    valid=True,
                    source_blob=header_result.get('source_blob', blob_name),
                    container_name=header_result.get('container_name', container_name),
                    source_crs=header_result.get('source_crs', 'UNKNOWN'),
                    crs_source=header_result.get('crs_source', 'file_metadata'),
                    bounds=header_result.get('bounds', [0, 0, 0, 0]),
                    shape=header_result.get('shape', [0, 0]),
                    band_count=band_count,
                    dtype=str(dtype),
                    data_type=str(dtype),
                    size_mb=header_result.get('size_mb', 0),
                    nodata=nodata,
                    raster_type=raster_type_info,
                    cog_tiers=cog_tier_info,
                    bit_depth_check=bit_depth_info,
                    memory_estimation=memory_estimation_model,
                    warnings=warnings
                )

                result = RasterValidationResult(
                    success=True,
                    result=validation_data
                )

                logger.info(f"✅ [DATA] COMPLETE: Type={detected_type}, "
                            f"Nodata={nodata_percent:.1f}%, Tiers={len(applicable_tiers)}")

                return result.model_dump()

            except Exception as e:
                logger.error(f"❌ [DATA] Result build error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "RESULT_BUILD_ERROR",
                    "message": f"Failed to build data validation result: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

    except Exception as e:
        logger.error(f"❌ [DATA] Unexpected error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "VALIDATION_ERROR",
            "error_type": type(e).__name__,
            "message": f"Unexpected data validation error: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }


def validate_raster(params: dict) -> dict:
    """
    Validate raster file for COG pipeline processing (backward-compatible wrapper).

    Calls validate_raster_header() then validate_raster_data() in sequence.
    Preserves the existing interface for handler registry and direct callers.

    Args:
        params: Task parameters dict with:
            - blob_url: Azure blob URL with SAS token
            - blob_name: Blob path (for logging)
            - container_name: Container name (for logging)
            - input_crs: (Optional) User-provided CRS override
            - raster_type: (Optional) Expected raster type (auto, rgb, rgba, dem, etc.)
            - strict_mode: (Optional) Fail on warnings
            - _skip_validation: (Optional) TESTING ONLY - skip all validation

    Returns:
        dict: {
            "success": True/False,
            "result": {...validation metadata...},
            "error": "ERROR_CODE" (if failed),
            "message": "Error description" (if failed)
        }
    """
    # Phase 1: Header validation (cheap, no pixel reads)
    header_response = validate_raster_header(params)
    if not header_response.get('success'):
        return header_response

    # Phase 2: Data validation (GDAL statistics, pixel analysis)
    data_params = {
        'file_path': params.get('blob_url'),
        'blob_name': params.get('blob_name', 'unknown'),
        'container_name': params.get('container_name', params.get('container', 'unknown')),
        'raster_type': params.get('raster_type', 'auto'),
        'strict_mode': params.get('strict_mode', False),
    }
    return validate_raster_data(data_params, header_response.get('result', {}))


def _validate_crs(src, input_crs: Optional[str], bounds, skip_validation: bool = False) -> dict:
    """
    Validate CRS with strict validation approach:
    1. If file has CRS and user provides CRS:
       - FAIL if they don't match (unless skip_validation=True for testing)
    2. If file has CRS and user provides nothing:
       - Use file CRS (normal case)
    3. If file has no CRS and user provides CRS:
       - Use user CRS as override (necessary for broken files)
    4. If file has no CRS and user provides nothing:
       - FAIL (cannot proceed without CRS)

    Also performs bounds sanity checks.
    """

    # Check file CRS
    file_crs = src.crs

    # Case 1: File has CRS
    if file_crs:
        file_crs_str = str(file_crs)

        # User specified CRS - check for mismatch
        if input_crs:
            if file_crs_str != input_crs:
                # MISMATCH: User says one thing, file says another
                if skip_validation:
                    # Testing mode: allow override with warning
                    from util_logger import LoggerFactory, ComponentType
                    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
                    logger.warning(f"⚠️ VALIDATION CRS: TESTING MODE - Override file CRS {file_crs_str} with user CRS {input_crs}")
                    return {
                        "success": True,
                        "source_crs": input_crs,
                        "crs_source": "user_override_testing",
                        "warning": {
                            "type": "CRS_OVERRIDE_TESTING",
                            "severity": "HIGH",
                            "message": f"TESTING MODE: Overriding file CRS {file_crs_str} with user CRS {input_crs}"
                        }
                    }
                else:
                    # Production mode: FAIL on mismatch
                    from util_logger import LoggerFactory, ComponentType
                    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
                    logger.error(f"❌ VALIDATION CRS: MISMATCH - File: {file_crs_str}, User: {input_crs}")
                    return {
                        "success": False,
                        "error": "CRS_MISMATCH",
                        "file_crs": file_crs_str,
                        "user_crs": input_crs,
                        "message": f"CRS mismatch: File metadata indicates {file_crs_str} but user specified {input_crs}. "
                                   f"Either the file is mislabeled or the user parameter is wrong. "
                                   f"Fix the source file metadata or remove the source_crs parameter to use file CRS.",
                        "file_info": {
                            "bounds": list(bounds),
                            "shape": src.shape
                        }
                    }
            else:
                # Match: User CRS matches file CRS (redundant but OK)
                from util_logger import LoggerFactory, ComponentType
                logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
                logger.info(f"✅ VALIDATION CRS: User CRS matches file CRS - {file_crs_str}")

        # Use file CRS (either user didn't specify, or user matched file)
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.info(f"📍 VALIDATION CRS: From file metadata - {file_crs_str}")

        # Sanity check bounds
        bounds_warning = _check_bounds_sanity(file_crs, bounds)

        result = {
            "success": True,
            "source_crs": file_crs_str,
            "crs_source": "file_metadata" if not input_crs else "user_confirmed"
        }

        if bounds_warning:
            result["warning"] = bounds_warning

        return result

    # Case 2: File has NO CRS
    else:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")

        if input_crs:
            # User provides CRS for file with no metadata (necessary override)
            logger.info(f"🔧 VALIDATION CRS: File has no CRS, using user override - {input_crs}")
            return {
                "success": True,
                "source_crs": input_crs,
                "crs_source": "user_override_required",
                "warning": {
                    "type": "CRS_OVERRIDE_NO_FILE_CRS",
                    "severity": "MEDIUM",
                    "message": f"File has no CRS metadata, using user-provided {input_crs}. "
                               f"Verify this is correct - cannot detect mislabeled CRS."
                }
            }
        else:
            # No CRS available anywhere - FAIL
            logger.error(f"❌ VALIDATION CRS: Missing CRS, rejecting file")
            return {
                "success": False,
                "error": "CRS_MISSING",
                "message": (
                    "Raster file has no coordinate reference system (CRS) in its metadata. "
                    "This file cannot be processed. Re-export from the source application "
                    "with the correct CRS embedded, or assign one with: "
                    "gdal_edit.py -a_srs EPSG:XXXX your_file.tif"
                ),
                "remediation": (
                    "Fix the source file to include CRS metadata. Common CRS codes: "
                    "EPSG:4326 (WGS84 lat/lon), EPSG:3857 (Web Mercator), "
                    "EPSG:326xx (UTM North), EPSG:327xx (UTM South)."
                ),
                "user_fixable": True,
                "retryable": False,
                "file_info": {
                    "bounds": list(bounds),
                    "shape": src.shape
                }
            }


def _check_bounds_sanity(crs, bounds) -> Optional[dict]:
    """
    Basic sanity checks for obviously wrong bounds.

    Returns warning dict if bounds look suspicious, None otherwise.
    """

    crs_str = str(crs)

    # EPSG:4326 (WGS84) - must be -180 to 180, -90 to 90
    if crs_str == "EPSG:4326":
        if not (-180 <= bounds[0] <= 180 and -180 <= bounds[2] <= 180):
            return {
                "type": "SUSPICIOUS_BOUNDS",
                "severity": "MEDIUM",
                "message": f"Bounds longitude {bounds[0]}, {bounds[2]} outside valid range for EPSG:4326 (-180 to 180). "
                           f"CRS may be mislabeled. Review metadata or use input_crs parameter."
            }
        if not (-90 <= bounds[1] <= 90 and -90 <= bounds[3] <= 90):
            return {
                "type": "SUSPICIOUS_BOUNDS",
                "severity": "MEDIUM",
                "message": f"Bounds latitude {bounds[1]}, {bounds[3]} outside valid range for EPSG:4326 (-90 to 90). "
                           f"CRS may be mislabeled. Review metadata or use input_crs parameter."
            }

    # UTM zones (EPSG:326xx, EPSG:327xx) - easting should be 0-1000000m
    if crs_str.startswith("EPSG:326") or crs_str.startswith("EPSG:327"):
        if bounds[0] < -1000000 or bounds[0] > 2000000:
            return {
                "type": "SUSPICIOUS_BOUNDS",
                "severity": "MEDIUM",
                "message": f"Bounds easting {bounds[0]} way outside typical UTM range (0-1000000m). "
                           f"CRS may be mislabeled. Review metadata or use input_crs parameter."
            }

    return None


def _check_bit_depth_efficiency(band_stats: dict, dtype: str, strict_mode: bool) -> dict:
    """
    Check if raster uses inefficient bit-depth.

    Refactored 26 FEB 2026: Uses pre-computed GDAL band statistics instead
    of reading a pixel window from the top-left corner.

    Args:
        band_stats: Pre-computed stats from _compute_band_statistics().
                    {bidx: {"min", "max", "mean", "std"}} or {bidx: None}
        dtype: Data type string (e.g., 'uint8', 'float32')
        strict_mode: If True, CRITICAL warnings cause failure

    ORGANIZATIONAL POLICY: All 64-bit data types are flagged as CRITICAL.
    """
    import numpy as np

    # ORGANIZATIONAL POLICY: Flag ALL 64-bit data types immediately
    if dtype in ['float64', 'int64', 'uint64', 'complex64', 'complex128']:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.error(f"🚨 VALIDATION BIT-DEPTH: CRITICAL - 64-bit data type {dtype}")
        return {
            "efficient": False,
            "current_dtype": str(dtype),
            "recommended_dtype": "ANALYZE_DATA",
            "reason": f"64-bit data type ({dtype}) has no legitimate use case for this organization",
            "potential_savings_percent": 50.0,
            "warning": {
                "type": "INEFFICIENT_BIT_DEPTH",
                "severity": "CRITICAL",
                "current_dtype": str(dtype),
                "recommended_dtype": "ANALYZE_DATA",
                "potential_savings_percent": 50.0,
                "policy_violation": True,
                "message": "POLICY VIOLATION: 64-bit data types are not acceptable. "
                           "Contact data owner to provide properly formatted raster. "
                           "This raster wastes storage and bandwidth."
            }
        }

    # Use GDAL stats for value range analysis (replaces corner sample)
    stats_band1 = band_stats.get(1)
    if not stats_band1:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.warning(f"⚠️ VALIDATION BIT-DEPTH: No band statistics available")
        return {
            "efficient": True,
            "current_dtype": str(dtype),
            "reason": "Could not compute statistics for analysis"
        }

    min_val = stats_band1["min"]
    max_val = stats_band1["max"]
    std_val = stats_band1["std"]
    value_range_span = max_val - min_val

    # Check for categorical data in float types
    # Heuristic: small value range + low std/range ratio suggests discrete values
    if dtype in ['float32', 'float16'] and value_range_span > 0:
        # If std is very small relative to range, data is likely categorical
        # (clustered around a few discrete values)
        std_ratio = std_val / value_range_span if value_range_span > 0 else 0

        if std_ratio < 0.05 and value_range_span < 256:
            # Likely categorical with few discrete values
            estimated_categories = max(2, int(value_range_span) + 1)
            if estimated_categories <= 255:
                recommended = "uint8"
                savings = ((np.dtype(dtype).itemsize - 1) / np.dtype(dtype).itemsize) * 100
            else:
                recommended = "uint16"
                savings = ((np.dtype(dtype).itemsize - 2) / np.dtype(dtype).itemsize) * 100

            from util_logger import LoggerFactory, ComponentType
            logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
            logger.warning(f"⚠️ VALIDATION BIT-DEPTH: HIGH - Likely categorical data in {dtype}")
            return {
                "efficient": False,
                "current_dtype": str(dtype),
                "recommended_dtype": recommended,
                "reason": f"Likely categorical data (range: {value_range_span:.0f}, std/range: {std_ratio:.3f}) stored as {dtype}",
                "potential_savings_percent": round(savings, 1),
                "warning": {
                    "type": "INEFFICIENT_BIT_DEPTH",
                    "severity": "HIGH",
                    "current_dtype": str(dtype),
                    "recommended_dtype": recommended,
                    "potential_savings_percent": round(savings, 1),
                    "message": f"Raster uses {dtype} for likely categorical data (range: {value_range_span:.0f}). "
                               f"Converting to {recommended} would reduce size by {savings:.1f}%. "
                               f"Consider optimizing source data before reprocessing."
                }
            }

    # Check for integer data in float types (all values are whole numbers)
    if dtype in ['float32', 'float16']:
        # If min and max are both integers, likely integer data in float container
        if min_val == int(min_val) and max_val == int(max_val):
            # Determine smallest int type that fits
            if min_val >= 0:
                if max_val <= 255:
                    recommended = "uint8"
                elif max_val <= 65535:
                    recommended = "uint16"
                else:
                    recommended = "uint32"
            else:
                if min_val >= -128 and max_val <= 127:
                    recommended = "int8"
                elif min_val >= -32768 and max_val <= 32767:
                    recommended = "int16"
                else:
                    recommended = "int32"

            savings = ((np.dtype(dtype).itemsize - np.dtype(recommended).itemsize) / np.dtype(dtype).itemsize) * 100

            from util_logger import LoggerFactory, ComponentType
            logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
            logger.warning(f"⚠️ VALIDATION BIT-DEPTH: MEDIUM - Integer data in {dtype}")
            return {
                "efficient": False,
                "current_dtype": str(dtype),
                "recommended_dtype": recommended,
                "reason": f"Integer data (range: {min_val} to {max_val}) stored as {dtype}",
                "value_range": (min_val, max_val),
                "potential_savings_percent": round(savings, 1),
                "warning": {
                    "type": "INEFFICIENT_BIT_DEPTH",
                    "severity": "MEDIUM",
                    "current_dtype": str(dtype),
                    "recommended_dtype": recommended,
                    "potential_savings_percent": round(savings, 1),
                    "message": f"Integer data stored as {dtype}. "
                               f"Converting to {recommended} would reduce size by {savings:.1f}%."
                }
            }

    # Bit-depth is appropriate
    return {
        "efficient": True,
        "current_dtype": str(dtype),
        "reason": "Bit-depth appropriate for data type and range"
    }


def _detect_raster_type(src, band_stats: dict, user_type: str) -> dict:
    """
    Detect raster type from file characteristics and GDAL statistics.

    Refactored 26 FEB 2026: Uses pre-computed band statistics instead of
    reading pixel windows from the top-left corner. Still accesses src for
    color_interp and band 4 alpha detection.

    Args:
        src: Open rasterio dataset (for color_interp, alpha band check)
        band_stats: Pre-computed stats from _compute_band_statistics().
                    {bidx: {"min", "max", "mean", "std"}} or {bidx: None}
        user_type: User-specified raster type or 'auto'

    If user_type specified, validate file matches - FAIL if mismatch.
    """
    from core.models.enums import RasterType

    np, rasterio, ColorInterp, Window = _lazy_imports()

    band_count = src.count
    dtype = src.dtypes[0]
    stats_band1 = band_stats.get(1)

    # Detect type from file characteristics
    detected_type = RasterType.UNKNOWN.value
    confidence = "LOW"
    evidence = []

    from util_logger import LoggerFactory, ComponentType
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_data")

    # RGB Detection (HIGH confidence)
    if band_count == 3 and dtype in ['uint8', 'uint16']:
        detected_type = RasterType.RGB.value
        confidence = "HIGH"
        evidence.append(f"3 bands, {dtype} (standard RGB)")

        # Check color interpretation (header only, no pixel read)
        try:
            if src.colorinterp[0] == ColorInterp.red:
                evidence.append("Color interpretation: Red/Green/Blue")
                confidence = "VERY_HIGH"
        except (IndexError, AttributeError) as e:
            logger.debug(f"Could not check color interpretation: {e}")

    # RGBA Detection (HIGH confidence) - CRITICAL FOR DRONE IMAGERY
    elif band_count == 4 and dtype in ['uint8', 'uint16']:
        # Use band 4 stats to detect alpha (low std = few values = likely alpha)
        stats_band4 = band_stats.get(4)
        if stats_band4:
            # Alpha band typically has very low std (mostly 0 or 255)
            alpha_range = stats_band4["max"] - stats_band4["min"]
            if alpha_range <= 255 and stats_band4["std"] < 50:
                detected_type = RasterType.RGBA.value
                confidence = "HIGH"
                evidence.append(f"4 bands, {dtype}, alpha band detected (std: {stats_band4['std']:.1f})")
            else:
                detected_type = RasterType.NIR.value
                confidence = "MEDIUM"
                evidence.append(f"4 bands, {dtype} (likely RGB + NIR)")
        else:
            detected_type = RasterType.NIR.value
            confidence = "LOW"
            evidence.append(f"4 bands, {dtype} (could be RGBA or NIR)")

    # Single-band continuous detection using GDAL stats
    # Order: vegetation_index → DEM (smooth) → continuous (catch-all)
    elif band_count == 1 and dtype in ['float32', 'float64', 'int16', 'int32'] and stats_band1:
        data_min = stats_band1["min"]
        data_max = stats_band1["max"]
        data_std = stats_band1["std"]
        value_range = data_max - data_min

        # Vegetation index: float values bounded in [-1, 1]
        if dtype in ['float32', 'float64'] and -1.0 <= data_min and data_max <= 1.0 and value_range > 0.1:
            detected_type = RasterType.VEGETATION_INDEX.value
            confidence = "HIGH"
            evidence.append(f"Single-band {dtype}, range [{data_min:.2f}, {data_max:.2f}] (vegetation index)")

        # DEM vs continuous: use std/range ratio as smoothness proxy
        # Low std/range ratio = smooth gradients (DEM-like)
        elif value_range > 0:
            smoothness_proxy = data_std / value_range
            if smoothness_proxy < 0.3:
                detected_type = RasterType.DEM.value
                confidence = "HIGH"
                evidence.append(f"Single-band {dtype}, smooth data (std/range: {smoothness_proxy:.3f})")
            else:
                detected_type = RasterType.CONTINUOUS.value
                confidence = "MEDIUM"
                evidence.append(f"Single-band {dtype}, non-smooth (std/range: {smoothness_proxy:.3f})")
        else:
            detected_type = RasterType.CONTINUOUS.value
            confidence = "LOW"
            evidence.append(f"Single-band {dtype}, zero range")

    # Categorical Detection using GDAL stats
    elif band_count == 1 and stats_band1:
        data_min = stats_band1["min"]
        data_max = stats_band1["max"]
        data_std = stats_band1["std"]
        value_range = data_max - data_min

        # Small integer range + low relative std suggests categorical
        if value_range < 256 and data_min == int(data_min) and data_max == int(data_max):
            detected_type = RasterType.CATEGORICAL.value
            confidence = "HIGH"
            evidence.append(f"Single-band, integer range [{int(data_min)}, {int(data_max)}] (categorical)")

    # Multispectral Detection (MEDIUM confidence)
    elif band_count >= 5:
        detected_type = RasterType.MULTISPECTRAL.value
        confidence = "MEDIUM"
        evidence.append(f"{band_count} bands (likely multispectral satellite)")

        if band_count in [7, 8, 9, 10, 11]:
            evidence.append("Band count matches Landsat")
        elif band_count in [12, 13]:
            evidence.append("Band count matches Sentinel-2")

    logger.info(f"🔍 VALIDATION TYPE: Detected {detected_type} ({confidence})")

    # User type validation (HIERARCHICAL — 12 FEB 2026)
    if user_type and user_type != "auto":
        compatible = COMPATIBLE_OVERRIDES.get(user_type, set())
        if user_type == detected_type:
            pass
        elif detected_type in compatible:
            logger.info(f"✅ VALIDATION TYPE: User override '{user_type}' accepted "
                        f"(compatible with detected '{detected_type}')")
            detected_type = user_type
        else:
            logger.error(f"❌ VALIDATION TYPE: MISMATCH - User: {user_type}, Detected: {detected_type}")
            return {
                "success": False,
                "error": "RASTER_TYPE_MISMATCH",
                "user_specified_type": user_type,
                "detected_type": detected_type,
                "confidence": confidence,
                "file_characteristics": {
                    "band_count": band_count,
                    "dtype": str(dtype),
                    "shape": src.shape,
                    "evidence": evidence
                },
                "message": f"User specified raster_type='{user_type}' but file characteristics indicate '{detected_type}'. "
                           f"File has {band_count} bands, dtype {dtype}. "
                           f"Evidence: {'; '.join(evidence)}. "
                           f"Either fix the source file or use correct raster_type parameter."
            }

    return {
        "success": True,
        "detected_type": detected_type,
        "confidence": confidence,
        "evidence": evidence,
        "type_source": "user_specified" if (user_type and user_type != "auto") else "auto_detected"
    }


def _get_optimal_cog_settings(raster_type: str) -> dict:
    """Get optimal COG settings based on raster type."""

    from core.models.enums import RasterType

    settings = {
        RasterType.RGB.value: {
            "compression": "jpeg",
            "jpeg_quality": 85,
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        },
        RasterType.RGBA.value: {
            "compression": "webp",
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        },
        RasterType.DEM.value: {
            "compression": "lerc_deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.CATEGORICAL.value: {
            "compression": "deflate",
            "overview_resampling": "mode",
            "reproject_resampling": "nearest"
        },
        RasterType.MULTISPECTRAL.value: {
            "compression": "deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.NIR.value: {
            "compression": "deflate",
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        },
        # 12 FEB 2026: New types
        RasterType.CONTINUOUS.value: {
            "compression": "deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.VEGETATION_INDEX.value: {
            "compression": "deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.FLOOD_DEPTH.value: {
            "compression": "lerc_deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.FLOOD_PROBABILITY.value: {
            "compression": "deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.HYDROLOGY.value: {
            "compression": "lerc_deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.TEMPORAL.value: {
            "compression": "deflate",
            "overview_resampling": "nearest",
            "reproject_resampling": "nearest"
        },
        RasterType.POPULATION.value: {
            "compression": "deflate",
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        RasterType.UNKNOWN.value: {
            "compression": "deflate",
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        }
    }

    return settings.get(raster_type, settings[RasterType.UNKNOWN.value])


# ============================================================================
# MEMORY FOOTPRINT ESTIMATION (30 NOV 2025)
# ============================================================================

def _get_memory_multiplier(dtype: str) -> float:
    """
    Get dtype-aware memory multiplier for peak RAM estimation.

    Different data types require different amounts of working memory
    during COG creation due to intermediate arrays, float math, and
    type upcasting during processing.

    Args:
        dtype: Data type string (e.g., 'uint8', 'float32')

    Returns:
        float: Multiplier to apply to uncompressed size for peak estimate

    Empirical Observations (23 DEC 2025):
        - uint8/int8:   2.5x - Simple byte operations
        - uint16/int16: 3.0x - Upcast to int32 during processing
        - uint32/int32: 3.5x - Larger intermediate buffers
        - float32:      4.0x - Float math creates many intermediate arrays
        - float64:      5.0x - Double precision overhead compounds
    """
    from config.defaults import RasterDefaults

    dtype_lower = str(dtype).lower()

    if 'float64' in dtype_lower or 'complex' in dtype_lower:
        return RasterDefaults.MEMORY_MULTIPLIER_FLOAT64
    elif 'float32' in dtype_lower or 'float16' in dtype_lower:
        return RasterDefaults.MEMORY_MULTIPLIER_FLOAT32
    elif 'int32' in dtype_lower or 'uint32' in dtype_lower:
        return RasterDefaults.MEMORY_MULTIPLIER_INT32
    elif 'int16' in dtype_lower or 'uint16' in dtype_lower:
        return RasterDefaults.MEMORY_MULTIPLIER_INT16
    else:
        # uint8, int8, or unknown - use conservative base multiplier
        return RasterDefaults.MEMORY_MULTIPLIER_UINT8


def _estimate_memory_footprint(width: int, height: int, band_count: int, dtype: str) -> dict:
    """
    Estimate memory footprint for raster processing operations.

    Calculates uncompressed size and estimates peak memory usage during
    COG creation (which includes warp buffers, overview generation, etc.).

    Uses dtype-aware multipliers (23 DEC 2025) to account for different
    working memory requirements of different data types:
        - float32 requires ~4x uncompressed size (vs 2.5x for uint8)
        - This explains OOM on float32 files that seemed "safe"

    Args:
        width: Raster width in pixels
        height: Raster height in pixels
        band_count: Number of bands
        dtype: Data type string (e.g., 'uint8', 'float32')

    Returns:
        dict: Memory estimation with processing strategy recommendation
        {
            "uncompressed_gb": float,
            "estimated_peak_gb": float,
            "system_ram_gb": float,
            "cpu_count": int,
            "safe_threshold_gb": float,
            "processing_strategy": "single_pass" | "chunked" | "reject",
            "gdal_config": {...},
            "warnings": []
        }
    """
    import numpy as np

    # Get bytes per pixel from dtype
    try:
        bytes_per_pixel = np.dtype(dtype).itemsize
    except TypeError:
        # Unknown dtype - assume float32 (4 bytes)
        bytes_per_pixel = 4

    # Calculate uncompressed size
    total_pixels = width * height * band_count
    uncompressed_bytes = total_pixels * bytes_per_pixel
    uncompressed_gb = uncompressed_bytes / (1024 ** 3)

    # Estimate peak memory during processing using dtype-aware multiplier
    # COG creation involves: source + dest + warp buffers + overview pyramid
    # Multiplier varies by dtype due to intermediate array allocations
    peak_multiplier = _get_memory_multiplier(dtype)
    estimated_peak_gb = uncompressed_gb * peak_multiplier

    # Detect system resources
    system_ram_gb = 16.0  # Default fallback
    cpu_count = 4  # Default fallback
    warnings = []

    try:
        import psutil
        system_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
        cpu_count = psutil.cpu_count(logical=True) or 4
    except ImportError:
        warnings.append({
            "type": "PSUTIL_UNAVAILABLE",
            "message": "psutil not available, using default system specs (16GB RAM, 4 CPUs)"
        })
    except Exception as e:
        warnings.append({
            "type": "SYSTEM_DETECTION_ERROR",
            "message": f"Could not detect system resources: {e}"
        })

    # Calculate safe threshold (60% of RAM to leave room for OS, other processes)
    # Also account for concurrent processing (maxConcurrentCalls=2)
    concurrent_jobs = 2  # From host.json
    safe_threshold_gb = (system_ram_gb * 0.6) / concurrent_jobs

    # Determine processing strategy
    if estimated_peak_gb <= safe_threshold_gb:
        processing_strategy = "single_pass"
        gdal_cachemax = 1024  # 1GB cache
        gdal_num_threads = min(2, cpu_count)
        gdal_swath_size = 134217728  # 128MB
    elif estimated_peak_gb <= system_ram_gb * 0.8:
        processing_strategy = "single_pass_conservative"
        gdal_cachemax = 512  # 512MB cache
        gdal_num_threads = 1  # Single thread for predictable memory
        gdal_swath_size = 67108864  # 64MB
        warnings.append({
            "type": "MEMORY_WARNING",
            "severity": "MEDIUM",
            "message": f"Raster may use up to {estimated_peak_gb:.1f}GB during processing. "
                       f"Using conservative GDAL settings."
        })
    else:
        processing_strategy = "chunked"
        gdal_cachemax = 256  # 256MB cache
        gdal_num_threads = 1
        gdal_swath_size = 33554432  # 32MB
        warnings.append({
            "type": "MEMORY_WARNING",
            "severity": "HIGH",
            "message": f"Raster estimated peak memory ({estimated_peak_gb:.1f}GB) exceeds safe "
                       f"threshold ({safe_threshold_gb:.1f}GB). Consider chunked processing."
        })

    # Build GDAL config recommendation
    gdal_config = {
        "GDAL_CACHEMAX": gdal_cachemax,
        "GDAL_NUM_THREADS": gdal_num_threads,
        "GDAL_SWATH_SIZE": gdal_swath_size,
        "GDAL_TIFF_INTERNAL_MASK": True,
        "GDAL_TIFF_OVR_BLOCKSIZE": 512,
        "BIGTIFF": "IF_SAFER",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"
    }

    return {
        "uncompressed_gb": round(uncompressed_gb, 2),
        "estimated_peak_gb": round(estimated_peak_gb, 2),
        "system_ram_gb": round(system_ram_gb, 1),
        "cpu_count": cpu_count,
        "safe_threshold_gb": round(safe_threshold_gb, 2),
        "concurrent_jobs": concurrent_jobs,
        "processing_strategy": processing_strategy,
        "gdal_config": gdal_config,
        "calculation_details": {
            "width": width,
            "height": height,
            "band_count": band_count,
            "dtype": dtype,
            "bytes_per_pixel": bytes_per_pixel,
            "peak_multiplier": peak_multiplier
        },
        "warnings": warnings
    }


# ============================================================================
# GDAL STATISTICS HELPERS (26 FEB 2026 - Split validation)
# ============================================================================
# These use GDAL's built-in statistics computation (streaming, O(1) memory)
# and block-by-block scanning for accurate nodata percentage across ALL pixels.
# Replaces corner-sampling approach that caused false RASTER_EMPTY on
# irregularly shaped rasters (e.g., Luang Prabang DTM).
# ============================================================================

def _compute_band_statistics(src) -> dict:
    """
    Compute per-band statistics using GDAL's streaming computation.

    Uses src.statistics(bidx) which calls GDALComputeRasterStatistics
    internally — reads all pixels in a streaming fashion with O(1) memory.

    Args:
        src: Open rasterio dataset

    Returns:
        dict: {band_index: {"min": float, "max": float, "mean": float, "std": float}}
              Band indices are 1-based (matching rasterio convention).
    """
    from util_logger import LoggerFactory, ComponentType
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_data")

    band_stats = {}
    for bidx in range(1, src.count + 1):
        try:
            stats = src.statistics(bidx)
            band_stats[bidx] = {
                "min": stats.min,
                "max": stats.max,
                "mean": stats.mean,
                "std": stats.std,
            }
            logger.debug(f"   Band {bidx}: min={stats.min:.4f}, max={stats.max:.4f}, "
                         f"mean={stats.mean:.4f}, std={stats.std:.4f}")
        except Exception as e:
            logger.warning(f"   Band {bidx}: statistics failed: {e}")
            band_stats[bidx] = None

    return band_stats


def _compute_nodata_percentage(src, nodata) -> float:
    """
    Compute accurate nodata percentage by scanning ALL pixels block-by-block.

    Uses src.block_windows(1) to iterate over internal TIFF tiles, reading
    one block at a time (O(block_size) memory). This replaces the old approach
    of sampling a 2000x2000 window from the top-left corner, which gave
    inaccurate results for irregularly shaped rasters.

    Args:
        src: Open rasterio dataset
        nodata: Nodata value from file metadata (can be None or NaN)

    Returns:
        float: Percentage of nodata pixels (0.0 - 100.0)
    """
    import numpy as np

    if nodata is None and not any(
        np.issubdtype(np.dtype(dt), np.floating) for dt in src.dtypes
    ):
        # No nodata defined and not float (no NaN possible) — assume 0% nodata
        return 0.0

    total_pixels = 0
    nodata_pixels = 0
    use_nan = nodata is not None and np.isnan(nodata)

    for _, window in src.block_windows(1):
        block = src.read(1, window=window)
        total_pixels += block.size

        if use_nan:
            nodata_pixels += int(np.isnan(block).sum())
        elif nodata is not None:
            nodata_pixels += int((block == nodata).sum())
        else:
            # No nodata defined — check for NaN in float data
            if np.issubdtype(block.dtype, np.floating):
                nodata_pixels += int(np.isnan(block).sum())

    if total_pixels == 0:
        return 0.0

    return (nodata_pixels / total_pixels) * 100.0


# ============================================================================
# DATA QUALITY CHECKS (Phase 4 - 06 FEB 2026 - BUG_REFORM)
# Refactored 26 FEB 2026: Accept pre-computed stats instead of corner sampling
# ============================================================================

def _check_data_quality(
    band_stats: dict,
    nodata_percent: float,
    nodata,
    dtype: str,
    blob_name: str,
    container_name: str,
    strict_mode: bool = False
) -> dict:
    """
    Enhanced data quality checks for raster files (BUG_REFORM Phase 4).

    Refactored 26 FEB 2026: Accepts pre-computed GDAL band statistics and
    accurate nodata percentage (computed block-by-block across ALL pixels)
    instead of sampling a 2000x2000 window from the top-left corner.

    Performs three critical quality checks:
    1. Mostly-empty detection: Files that are 99%+ nodata waste resources
    2. Nodata conflict detection: Nodata value appearing in real data causes holes
    3. Extreme value detection: DEMs with 1e38 values indicate unset nodata

    Args:
        band_stats: Pre-computed stats from _compute_band_statistics().
                    {bidx: {"min", "max", "mean", "std"}} or {bidx: None}
        nodata_percent: Accurate nodata percentage from _compute_nodata_percentage()
        nodata: Nodata value from file metadata
        dtype: Data type string
        blob_name: Blob path for error messages
        container_name: Container name for error messages
        strict_mode: If True, fail on warnings; if False, return warnings

    Returns:
        dict: {
            "success": True/False,
            "nodata_percent": float,
            "value_range": (min, max),
            "warnings": [...],
            "error": ErrorCode (if failed),
            "message": str (if failed)
        }

    Error Codes Used:
        RASTER_EMPTY: 99%+ nodata pixels
        RASTER_NODATA_CONFLICT: Nodata value found in real data
        RASTER_EXTREME_VALUES: DEM with 1e38 values
    """
    from core.errors import ErrorCode, create_error_response
    import numpy as np

    warnings = []

    # Extract value range from GDAL stats (band 1)
    stats_band1 = band_stats.get(1)
    if stats_band1:
        value_range = (stats_band1["min"], stats_band1["max"])
    else:
        value_range = (None, None)

    # ========================================================================
    # CHECK 1: MOSTLY-EMPTY DETECTION (RASTER_EMPTY)
    # ========================================================================
    # Now uses accurate block-by-block nodata percentage (not corner sample)
    EMPTY_THRESHOLD_PERCENT = 99.0

    if nodata_percent >= EMPTY_THRESHOLD_PERCENT:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_data")
        logger.error(f"🚨 DATA_QUALITY: File is {nodata_percent:.1f}% nodata (threshold: {EMPTY_THRESHOLD_PERCENT}%)")

        error_response = create_error_response(
            ErrorCode.RASTER_EMPTY,
            f"File '{blob_name}' is {nodata_percent:.1f}% nodata - effectively empty",
            remediation=(
                f"Provide a file with actual data pixels. This file contains almost no usable data "
                f"({nodata_percent:.1f}% is nodata or empty). If this is expected, check that your "
                f"source file was exported correctly and contains valid data."
            ),
            details={
                "nodata_percent": round(nodata_percent, 1),
                "threshold_percent": EMPTY_THRESHOLD_PERCENT,
                "scan_method": "full_block_scan",
            }
        )
        return error_response.model_dump()

    # Warn if file is mostly empty but not over threshold
    if nodata_percent >= 90.0:
        warnings.append({
            "type": "HIGH_NODATA_PERCENTAGE",
            "severity": "MEDIUM",
            "nodata_percent": round(nodata_percent, 1),
            "message": f"File is {nodata_percent:.1f}% nodata. Consider checking source data quality."
        })

    # ========================================================================
    # CHECK 2: NODATA CONFLICT DETECTION (RASTER_NODATA_CONFLICT)
    # ========================================================================
    if nodata is not None and not np.isnan(nodata) and value_range[0] is not None and value_range[1] is not None:
        data_range = value_range[1] - value_range[0]
        if data_range > 0:
            nodata_in_range = value_range[0] <= nodata <= value_range[1]

            if nodata_in_range:
                from util_logger import LoggerFactory, ComponentType
                logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_data")

                if strict_mode:
                    logger.error(f"🚨 DATA_QUALITY: Nodata value {nodata} is within valid data range [{value_range[0]}, {value_range[1]}]")
                    error_response = create_error_response(
                        ErrorCode.RASTER_NODATA_CONFLICT,
                        f"Nodata value ({nodata}) falls within the valid data range of this file",
                        remediation=(
                            f"Your file's nodata value ({nodata}) is within the actual data range "
                            f"[{value_range[0]:.4f} to {value_range[1]:.4f}]. This may cause data loss "
                            f"as real values matching {nodata} will be treated as empty. "
                            f"Change the nodata value in your source file to a value outside the data range, "
                            f"or set nodata to None if your file has no actual nodata pixels."
                        ),
                        details={
                            "nodata_value": nodata,
                            "value_range_min": value_range[0],
                            "value_range_max": value_range[1],
                            "blob_name": blob_name
                        }
                    )
                    return error_response.model_dump()
                else:
                    warnings.append({
                        "type": "NODATA_IN_DATA_RANGE",
                        "severity": "HIGH",
                        "nodata_value": nodata,
                        "value_range": value_range,
                        "message": (
                            f"Nodata value ({nodata}) is within valid data range "
                            f"[{value_range[0]:.4f}, {value_range[1]:.4f}]. "
                            f"This may cause real data to be treated as nodata."
                        )
                    })

    # ========================================================================
    # CHECK 3: EXTREME VALUE DETECTION (RASTER_EXTREME_VALUES)
    # ========================================================================
    EXTREME_THRESHOLD = 1e30

    if value_range[1] is not None and abs(value_range[1]) >= EXTREME_THRESHOLD:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster_data")

        is_float_max = abs(value_range[1]) >= 3.4e38
        dtype_lower = str(dtype).lower()
        is_likely_dem = dtype_lower in ['float32', 'float64', 'int16', 'int32']

        if is_likely_dem:
            logger.error(f"🚨 DATA_QUALITY: Extreme value detected - max: {value_range[1]:.2e}")
            error_response = create_error_response(
                ErrorCode.RASTER_EXTREME_VALUES,
                f"File contains extreme values (max: {value_range[1]:.2e}) suggesting corrupt or unset nodata",
                remediation=(
                    f"Your file contains extreme values (maximum: {value_range[1]:.2e}) that are likely "
                    f"uninitialized pixels without a proper nodata value. "
                    f"{'This appears to be the float32 maximum (3.4e38), a common placeholder for missing data. ' if is_float_max else ''}"
                    f"Set a proper nodata value in your source file, or re-export with nodata correctly defined. "
                    f"Values like 3.4e38 or 1e38 should not appear in valid elevation data."
                ),
                details={
                    "max_value": value_range[1],
                    "min_value": value_range[0],
                    "dtype": dtype,
                    "extreme_threshold": EXTREME_THRESHOLD,
                    "is_float_max": is_float_max,
                    "likely_raster_type": "DEM/elevation",
                    "blob_name": blob_name
                }
            )
            return error_response.model_dump()

    # Also check for extremely negative values
    if value_range[0] is not None and value_range[0] <= -EXTREME_THRESHOLD:
        warnings.append({
            "type": "EXTREME_NEGATIVE_VALUE",
            "severity": "MEDIUM",
            "min_value": value_range[0],
            "message": (
                f"File contains extremely negative value ({value_range[0]:.2e}). "
                f"This may indicate unset nodata or data corruption."
            )
        })

    # Success - all checks passed
    return {
        "success": True,
        "nodata_percent": round(nodata_percent, 1),
        "value_range": value_range,
        "scan_method": "full_block_scan",
        "warnings": warnings
    }
