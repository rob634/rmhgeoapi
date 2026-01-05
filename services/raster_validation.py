# ============================================================================
# RASTER VALIDATION SERVICE
# ============================================================================
# STATUS: Service layer - Raster file validation and analysis
# PURPOSE: Validate raster files before COG processing, determine output tiers
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: validate_raster
# ============================================================================
"""
Raster Validation Service - Stage 1 of Raster Pipeline.

Validates raster files before COG processing and determines applicable output tiers.

Validation Steps:
    1. File readability check
    2. CRS validation (file metadata, user override, sanity checks)
    3. Bit-depth efficiency analysis (flag 64-bit data as CRITICAL)
    4. Raster type detection (RGB, RGBA, DEM, categorical, multispectral)
    5. Type mismatch validation (user-specified vs detected)
    6. Bounds sanity checks
    7. Optimal COG settings recommendation
    8. COG tier compatibility detection

COG Tier Detection:
    VISUALIZATION (JPEG): RGB only (3 bands, uint8)
    ANALYSIS (DEFLATE): Universal (all raster types)
    ARCHIVE (LZW): Universal (all raster types)

Exports:
    validate_raster: Validation handler function
"""

import sys
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lazy imports for Azure environment compatibility
def _lazy_imports():
    """Lazy import to avoid module-level import failures."""
    import numpy as np
    import rasterio
    from rasterio.enums import ColorInterp
    from rasterio.windows import Window
    return np, rasterio, ColorInterp, Window


def validate_raster(params: dict) -> dict:
    """
    Validate raster file for COG pipeline processing.

    Stage 1 of raster processing pipeline. Checks:
    - File readability
    - CRS presence and validity
    - Bit-depth efficiency (flags 64-bit data as CRITICAL)
    - Raster type detection and validation
    - Bounds sanity checks

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
    import traceback

    # STEP 0: Initialize logger BEFORE any other operations
    logger = None
    task_id = params.get('_task_id')  # For checkpoint context tracking (20 DEC 2025)
    try:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.info("🚀 [CHECKPOINT_ENTRY] Handler entry - validate_raster called")
        logger.debug(f"   Params keys: {list(params.keys())}")
        logger.debug(f"   blob_name: {params.get('blob_name', 'MISSING')}")
        logger.info("✅ STEP 0: Logger initialized successfully")
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
        logger.info("🔄 STEP 1: Extracting parameters...")
        blob_url = params.get('blob_url')
        blob_name = params.get('blob_name', 'unknown')
        container_name = params.get('container_name', params.get('container', 'unknown'))
        input_crs = params.get('input_crs') or params.get('source_crs')
        raster_type_param = params.get('raster_type', 'auto')
        strict_mode = params.get('strict_mode', False)
        skip_validation = params.get('_skip_validation', False)

        logger.info(f"✅ STEP 1: Parameters extracted - blob={blob_name}, container={container_name}")

        if not blob_url:
            logger.error("❌ STEP 1 FAILED: blob_url parameter is required")
            return {
                "success": False,
                "error": "MISSING_PARAMETER",
                "message": "blob_url parameter is required",
                "blob_name": blob_name,
                "container_name": container_name
            }
    except Exception as e:
        logger.error(f"❌ STEP 1 FAILED: Parameter extraction error: {e}\n{traceback.format_exc()}")
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
        logger.info("🔄 STEP 2: Lazy loading rasterio dependencies...")
        np, rasterio, ColorInterp, Window = _lazy_imports()
        logger.info("✅ STEP 2: Dependencies loaded successfully")
    except ImportError as e:
        logger.error(f"❌ STEP 2 FAILED: Import error: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "message": f"Failed to import dependencies: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }
    except Exception as e:
        logger.error(f"❌ STEP 2 FAILED: Unexpected error during import: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "error_type": type(e).__name__,
            "message": f"Unexpected error loading dependencies: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }

    # ================================================================
    # NEW STEP 3a (Phase 2-3 - 11 NOV 2025): Pre-flight blob validation
    # Validate container and blob exist before GDAL operation
    # Uses Phase 3 error classification for retry logic
    # ================================================================
    try:
        logger.info("🔄 STEP 3a: Pre-flight blob validation...")

        from infrastructure.blob import BlobRepository
        from core.errors import ErrorCode, create_error_response
        # Use Bronze zone for input rasters (08 DEC 2025)
        blob_repo = BlobRepository.for_zone("bronze")

        # Check container exists first
        if not blob_repo.container_exists(container_name):
            error_msg = (
                f"Container '{container_name}' does not exist in storage account "
                f"'{blob_repo.account_name}'"
            )
            logger.error(f"❌ STEP 3a FAILED: {error_msg}")
            return create_error_response(
                ErrorCode.CONTAINER_NOT_FOUND,
                error_msg,
                error_type="ResourceNotFoundError",
                container_name=container_name,
                storage_account=blob_repo.account_name,
                blob_name=blob_name
            )

        # Check blob exists in container
        if not blob_repo.blob_exists(container_name, blob_name):
            error_msg = (
                f"File '{blob_name}' not found in existing container '{container_name}' "
                f"(storage account: '{blob_repo.account_name}')"
            )
            logger.error(f"❌ STEP 3a FAILED: {error_msg}")
            return create_error_response(
                ErrorCode.FILE_NOT_FOUND,
                error_msg,
                error_type="ResourceNotFoundError",
                blob_name=blob_name,
                container_name=container_name,
                storage_account=blob_repo.account_name,
                suggestion=f"Verify blob path spelling. Use /api/containers/{container_name}/blobs to list available files."
            )

        logger.info("✅ STEP 3a: Blob exists validation passed")

    except Exception as e:
        from core.errors import ErrorCode, create_error_response
        logger.error(f"❌ STEP 3a FAILED: Validation error: {e}\n{traceback.format_exc()}")
        return create_error_response(
            ErrorCode.VALIDATION_ERROR,
            f"Failed to validate blob existence: {e}",
            blob_name=blob_name,
            container_name=container_name,
            traceback=traceback.format_exc()
        )

    # STEP 3: Open raster file
    try:
        logger.info(f"🔄 STEP 3: Opening raster file via SAS URL...")
        logger.debug(f"   Blob URL: {blob_url[:100]}...")
        src = rasterio.open(blob_url)
        logger.info(f"✅ STEP 3: File opened successfully - {src.count} bands, {src.shape}")

        # Memory checkpoint 1 (DEBUG_MODE only)
        from util_logger import log_memory_checkpoint
        log_memory_checkpoint(logger, "After GDAL open", context_id=task_id)
    except Exception as e:
        logger.error(f"❌ STEP 3 FAILED: Cannot open raster file: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "FILE_UNREADABLE",
            "message": f"Cannot open raster file: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "blob_url_prefix": blob_url[:100] if blob_url else None,
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }

    # STEP 4: Extract basic file information
    try:
        logger.info("🔄 STEP 4: Extracting basic file information...")
        with src:
            band_count = src.count
            dtype = src.dtypes[0]
            shape = src.shape
            bounds = src.bounds
            nodata = src.nodata
            logger.info(f"✅ STEP 4: File info extracted - {band_count} bands, {dtype}, shape {shape}")
            logger.debug(f"   Bounds: {bounds}, nodata: {nodata}")

            # Memory checkpoint 2 (DEBUG_MODE only)
            from util_logger import log_memory_checkpoint
            log_memory_checkpoint(logger, "After metadata extraction",
                                  context_id=task_id,
                                  band_count=band_count,
                                  shape_height=shape[0],
                                  shape_width=shape[1])

            # Warnings list
            warnings = []

            # ================================================================
            # STEP 4b: MEMORY FOOTPRINT ESTIMATION (30 NOV 2025)
            # ================================================================
            # Estimate uncompressed size and peak memory to determine
            # processing strategy and GDAL configuration
            try:
                logger.info("🔄 STEP 4b: Estimating memory footprint...")
                memory_estimation = _estimate_memory_footprint(
                    width=shape[1],
                    height=shape[0],
                    band_count=band_count,
                    dtype=dtype
                )
                logger.info(
                    f"✅ STEP 4b: Memory estimation complete - "
                    f"uncompressed: {memory_estimation['uncompressed_gb']:.2f}GB, "
                    f"peak: {memory_estimation['estimated_peak_gb']:.2f}GB, "
                    f"strategy: {memory_estimation['processing_strategy']}"
                )
                logger.info(
                    f"   System: {memory_estimation['system_ram_gb']:.1f}GB RAM, "
                    f"{memory_estimation['cpu_count']} CPUs, "
                    f"safe threshold: {memory_estimation['safe_threshold_gb']:.2f}GB"
                )

                # Add any memory warnings to the main warnings list
                for mem_warning in memory_estimation.get("warnings", []):
                    warnings.append(mem_warning)
                    severity = mem_warning.get("severity", "INFO")
                    logger.warning(f"   ⚠️  Memory warning ({severity}): {mem_warning.get('message', 'unknown')}")

            except Exception as e:
                logger.warning(f"⚠️  STEP 4b: Memory estimation failed (non-fatal): {e}")
                memory_estimation = {
                    "error": str(e),
                    "uncompressed_gb": None,
                    "processing_strategy": "unknown"
                }

            # ================================================================
            # STEP 5: CRS VALIDATION
            # ================================================================
            try:
                logger.info("🔄 STEP 5: Validating CRS...")
                crs_result = _validate_crs(src, input_crs, bounds, skip_validation)
                if not crs_result["success"]:
                    logger.error(f"❌ STEP 5 FAILED: CRS validation failed - {crs_result.get('message', 'unknown error')}")
                    return crs_result

                source_crs = crs_result["source_crs"]
                crs_source = crs_result["crs_source"]
                logger.info(f"✅ STEP 5: CRS validated - {source_crs} (source: {crs_source})")

                # Add CRS warnings if any
                if "warning" in crs_result:
                    warnings.append(crs_result["warning"])
                    logger.warning(f"   ⚠️  CRS warning: {crs_result['warning'].get('message', 'unknown')}")
            except Exception as e:
                logger.error(f"❌ STEP 5 FAILED: CRS validation error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "CRS_VALIDATION_ERROR",
                    "message": f"CRS validation failed: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

            # ================================================================
            # STEP 6: BIT-DEPTH EFFICIENCY CHECK
            # ================================================================
            try:
                logger.info("🔄 STEP 6: Checking bit-depth efficiency...")
                bit_depth_result = _check_bit_depth_efficiency(src, dtype, strict_mode)

                # Add bit-depth warnings
                if "warning" in bit_depth_result:
                    warnings.append(bit_depth_result["warning"])
                    logger.warning(f"   ⚠️  Bit-depth warning: {bit_depth_result['warning'].get('message', 'unknown')}")

                    # CRITICAL warnings in strict mode = FAIL
                    if strict_mode and bit_depth_result["warning"].get("severity") == "CRITICAL":
                        logger.error("❌ STEP 6 FAILED: CRITICAL bit-depth policy violation in strict mode")
                        return {
                            "success": False,
                            "error": "BIT_DEPTH_POLICY_VIOLATION",
                            "message": bit_depth_result["warning"]["message"],
                            "bit_depth_check": bit_depth_result,
                            "blob_name": blob_name,
                            "container_name": container_name
                        }

                logger.info(f"✅ STEP 6: Bit-depth check complete - efficient: {bit_depth_result.get('efficient', True)}")
            except Exception as e:
                logger.error(f"❌ STEP 6 FAILED: Bit-depth check error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "BIT_DEPTH_CHECK_ERROR",
                    "message": f"Bit-depth check failed: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

            # ================================================================
            # STEP 7: RASTER TYPE DETECTION
            # ================================================================
            try:
                logger.info("🔄 STEP 7: Detecting raster type...")
                type_result = _detect_raster_type(src, raster_type_param)
                if not type_result["success"]:
                    logger.error(f"❌ STEP 7 FAILED: Type detection failed - {type_result.get('message', 'unknown error')}")
                    return type_result

                detected_type = type_result["detected_type"]
                logger.info(f"✅ STEP 7: Raster type detected - {detected_type} (confidence: {type_result.get('confidence', 'UNKNOWN')})")
            except Exception as e:
                logger.error(f"❌ STEP 7 FAILED: Type detection error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "TYPE_DETECTION_ERROR",
                    "message": f"Type detection failed: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

            # ================================================================
            # STEP 8: GET OPTIMAL COG SETTINGS
            # ================================================================
            try:
                logger.info("🔄 STEP 8: Determining optimal COG settings...")
                optimal_settings = _get_optimal_cog_settings(detected_type)
                logger.info(f"✅ STEP 8: Optimal settings determined - compression: {optimal_settings.get('compression', 'unknown')}")
            except Exception as e:
                logger.error(f"❌ STEP 8 FAILED: COG settings error: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "COG_SETTINGS_ERROR",
                    "message": f"Failed to determine COG settings: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

            # ================================================================
            # STEP 8b: DETERMINE APPLICABLE COG TIERS
            # ================================================================
            # Automatically detect which COG output tiers (VISUALIZATION, ANALYSIS,
            # ARCHIVE) are compatible with this raster based on band count and data type.
            #
            # Why This Matters:
            #   - JPEG (visualization tier) only works with RGB (3 bands, uint8)
            #   - DEM, Landsat, RGBA rasters are incompatible with JPEG
            #   - DEFLATE/LZW (analysis/archive) are universally compatible
            #
            # This metadata is used in Stage 2 COG creation to:
            #   1. Validate user-requested tier is compatible
            #   2. Auto-fallback to "analysis" if incompatible tier requested
            #   3. Future: Multi-tier fan-out (create all compatible tiers)
            #
            # Examples:
            #   RGB aerial photo (3 bands, uint8) → all 3 tiers available
            #   DEM elevation (1 band, float32) → 2 tiers only (JPEG incompatible)
            #   Landsat (8 bands, uint16) → 2 tiers only (JPEG incompatible)
            #
            # See: config.py → determine_applicable_tiers() for detection logic
            # See: docs_claude/TIER_DETECTION_GUIDE.md for complete guide
            # ================================================================
            try:
                logger.info("🔄 STEP 8b: Determining applicable COG tiers...")
                from config import determine_applicable_tiers

                # Determine which tiers are compatible with this raster
                # Returns list of CogTier enums (e.g., [ANALYSIS, ARCHIVE] for DEM)
                applicable_tiers = determine_applicable_tiers(band_count, str(dtype))

                logger.info(f"✅ STEP 8b: Applicable tiers determined - {len(applicable_tiers)} tiers: {applicable_tiers}")

                # Log tier compatibility details if not all 3 tiers available
                if len(applicable_tiers) < 3:
                    logger.info(f"   ℹ️  Tier compatibility: {band_count} bands, {dtype} → {', '.join(applicable_tiers)}")
                    if 'visualization' not in applicable_tiers:
                        logger.info(f"   ℹ️  JPEG visualization tier not compatible (requires RGB: 3 bands, uint8)")

            except Exception as e:
                logger.error(f"❌ STEP 8b FAILED: Tier detection error: {e}\n{traceback.format_exc()}")
                # Non-critical failure - default to all tiers if detection fails
                # User may get error in Stage 2 if they request incompatible tier
                applicable_tiers = ['visualization', 'analysis', 'archive']
                logger.warning(f"   ⚠️  Using default tiers (detection failed): {applicable_tiers}")

            # STEP 9: Build success result
            try:
                logger.info("🔄 STEP 9: Building validation result...")
                result = {
                    "success": True,
                    "result": {
                        "valid": True,
                        "source_blob": blob_name,
                        "container_name": container_name,
                        "source_crs": str(source_crs),
                        "crs_source": crs_source,
                        "bounds": list(bounds),
                        "shape": list(shape),
                        "band_count": band_count,
                        "dtype": str(dtype),
                        "data_type": str(dtype),  # Alias for tier compatibility
                        "size_mb": params.get('size_mb', 0),
                        "nodata": nodata,

                        # Raster type detection
                        "raster_type": {
                            "detected_type": detected_type,
                            "confidence": type_result.get("confidence", "UNKNOWN"),
                            "evidence": type_result.get("evidence", []),
                            "type_source": type_result.get("type_source", "auto_detected"),
                            "optimal_cog_settings": optimal_settings,
                            "band_count": band_count,  # For tier detection
                            "data_type": str(dtype)     # For tier detection
                        },

                        # COG tier compatibility
                        "cog_tiers": {
                            "applicable_tiers": applicable_tiers,
                            "total_compatible": len(applicable_tiers),
                            "incompatible_reason": "JPEG requires RGB (3 bands, uint8)" if 'visualization' not in applicable_tiers else None
                        },

                        # Bit-depth analysis
                        "bit_depth_check": {
                            "efficient": bit_depth_result.get("efficient", True),
                            "current_dtype": str(dtype),
                            "reason": bit_depth_result.get("reason", "Unknown")
                        },

                        # Memory footprint estimation (30 NOV 2025)
                        "memory_estimation": memory_estimation,

                        # Warnings
                        "warnings": warnings
                    }
                }

                logger.info(f"✅ STEP 9: Result built successfully")
                logger.info(f"✅ VALIDATION COMPLETE: Type={detected_type}, CRS={source_crs}, Tiers={len(applicable_tiers)}, Warnings={len(warnings)}")

                # Memory checkpoint 3 (DEBUG_MODE only)
                from util_logger import log_memory_checkpoint
                log_memory_checkpoint(logger, "Validation complete",
                                      context_id=task_id,
                                      detected_type=detected_type,
                                      warnings_count=len(warnings))

                return result

            except Exception as e:
                logger.error(f"❌ STEP 9 FAILED: Error building result: {e}\n{traceback.format_exc()}")
                return {
                    "success": False,
                    "error": "RESULT_BUILD_ERROR",
                    "message": f"Failed to build validation result: {e}",
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "traceback": traceback.format_exc()
                }

    except Exception as e:
        logger.error(f"❌ STEP 4+ FAILED: Unexpected error during validation: {e}\n{traceback.format_exc()}")
        return {
            "success": False,
            "error": "VALIDATION_ERROR",
            "error_type": type(e).__name__,
            "message": f"Unexpected validation error: {e}",
            "blob_name": blob_name,
            "container_name": container_name,
            "traceback": traceback.format_exc()
        }


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
            logger.error(f"❌ VALIDATION CRS: Missing CRS, no user override")
            return {
                "success": False,
                "error": "CRS_MISSING",
                "message": "Raster has no CRS in metadata and no source_crs parameter provided. "
                           "Provide source_crs parameter (e.g., 'EPSG:32611') to proceed.",
                "suggestion": "Resubmit job with 'source_crs' parameter",
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


def _check_bit_depth_efficiency(src, dtype, strict_mode: bool) -> dict:
    """
    Check if raster uses inefficient bit-depth.

    ORGANIZATIONAL POLICY: All 64-bit data types are flagged as CRITICAL.
    """

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

    # Sample data to analyze (for 32-bit and smaller types)
    try:
        np, rasterio, ColorInterp, Window = _lazy_imports()
        sample_size = min(1000, src.width), min(1000, src.height)
        sample = src.read(1, window=Window(0, 0, sample_size[0], sample_size[1]))
        unique_values = np.unique(sample[~np.isnan(sample)])
        value_range = (float(sample.min()), float(sample.max()))
    except Exception as e:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.warning(f"⚠️ VALIDATION BIT-DEPTH: Could not sample data: {e}")
        return {
            "efficient": True,
            "current_dtype": str(dtype),
            "reason": "Could not sample data for analysis"
        }

    # Check for categorical data in float types
    if dtype in ['float32', 'float16'] and len(unique_values) < 256:
        if len(unique_values) <= 255:
            recommended = "uint8"
            savings = ((np.dtype(dtype).itemsize - 1) / np.dtype(dtype).itemsize) * 100
        else:
            recommended = "uint16"
            savings = ((np.dtype(dtype).itemsize - 2) / np.dtype(dtype).itemsize) * 100

        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.warning(f"⚠️ VALIDATION BIT-DEPTH: HIGH - Categorical {len(unique_values)} values in {dtype}")
        return {
            "efficient": False,
            "current_dtype": str(dtype),
            "recommended_dtype": recommended,
            "reason": f"Categorical/discrete data with {len(unique_values)} unique values stored as {dtype}",
            "unique_value_count": len(unique_values),
            "potential_savings_percent": round(savings, 1),
            "warning": {
                "type": "INEFFICIENT_BIT_DEPTH",
                "severity": "HIGH",
                "current_dtype": str(dtype),
                "recommended_dtype": recommended,
                "potential_savings_percent": round(savings, 1),
                "message": f"Raster uses {dtype} for categorical data with {len(unique_values)} classes. "
                           f"Converting to {recommended} would reduce size by {savings:.1f}%. "
                           f"Consider optimizing source data before reprocessing."
            }
        }

    # Check for integer data in float types
    if dtype in ['float32', 'float16']:
        if np.allclose(sample, np.round(sample), equal_nan=True):
            min_val, max_val = value_range

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
                "value_range": value_range,
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


def _detect_raster_type(src, user_type: str) -> dict:
    """
    Detect raster type from file characteristics.

    If user_type specified, validate file matches - FAIL if mismatch.
    """
    from core.models.enums import RasterType

    np, rasterio, ColorInterp, Window = _lazy_imports()

    band_count = src.count
    dtype = src.dtypes[0]

    # Sample data for analysis
    try:
        sample_size = min(1000, src.width), min(1000, src.height)
        sample = src.read(1, window=Window(0, 0, sample_size[0], sample_size[1]))
    except Exception as e:
        from util_logger import LoggerFactory, ComponentType
        logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
        logger.warning(f"⚠️ VALIDATION TYPE: Could not sample data: {e}")
        sample = None

    # Detect type from file characteristics
    detected_type = RasterType.UNKNOWN.value
    confidence = "LOW"
    evidence = []

    # RGB Detection (HIGH confidence)
    if band_count == 3 and dtype in ['uint8', 'uint16']:
        detected_type = RasterType.RGB.value
        confidence = "HIGH"
        evidence.append(f"3 bands, {dtype} (standard RGB)")

        # Check color interpretation
        try:
            if src.colorinterp[0] == ColorInterp.red:
                evidence.append("Color interpretation: Red/Green/Blue")
                confidence = "VERY_HIGH"
        except (IndexError, AttributeError) as e:
            logger.debug(f"Could not check color interpretation: {e}")

    # RGBA Detection (HIGH confidence) - CRITICAL FOR DRONE IMAGERY
    elif band_count == 4 and dtype in ['uint8', 'uint16']:
        # Check if 4th band is alpha (low unique values)
        try:
            alpha_band = src.read(4, window=Window(0, 0, sample_size[0], sample_size[1]))
            unique_alpha = np.unique(alpha_band)

            if len(unique_alpha) <= 10:  # Alpha typically has few values
                detected_type = RasterType.RGBA.value
                confidence = "HIGH"
                evidence.append(f"4 bands, {dtype}, alpha band detected ({len(unique_alpha)} unique values)")
            else:
                # Could be NIR or multispectral
                detected_type = RasterType.NIR.value
                confidence = "MEDIUM"
                evidence.append(f"4 bands, {dtype} (likely RGB + NIR)")
        except Exception as e:
            logger.debug(f"Could not analyze 4th band for alpha detection: {e}")
            detected_type = RasterType.NIR.value
            confidence = "LOW"
            evidence.append(f"4 bands, {dtype} (could be RGBA or NIR)")

    # DEM Detection (HIGH confidence)
    elif band_count == 1 and dtype in ['float32', 'float64', 'int16', 'int32'] and sample is not None:
        # Check for smooth gradients (spatial autocorrelation)
        if sample.size >= 100:
            try:
                horizontal_diff = np.abs(np.diff(sample, axis=1)).mean()
                vertical_diff = np.abs(np.diff(sample, axis=0)).mean()
                value_range = sample.max() - sample.min()

                smoothness = (horizontal_diff + vertical_diff) / (2 * value_range) if value_range > 0 else 0

                if smoothness < 0.1:  # Very smooth = likely DEM
                    detected_type = RasterType.DEM.value
                    confidence = "HIGH"
                    evidence.append(f"Single-band {dtype}, smooth gradients (smoothness: {smoothness:.3f})")
                else:
                    detected_type = RasterType.DEM.value
                    confidence = "MEDIUM"
                    evidence.append(f"Single-band {dtype} (likely elevation, smoothness: {smoothness:.3f})")
            except Exception as e:
                logger.debug(f"Could not compute smoothness for DEM detection: {e}")
                detected_type = RasterType.DEM.value
                confidence = "LOW"
                evidence.append(f"Single-band {dtype} (likely elevation)")

    # Categorical Detection (HIGH confidence)
    elif band_count == 1 and sample is not None:
        try:
            unique_values = np.unique(sample[~np.isnan(sample)])

            if len(unique_values) < 256:
                # Check if values are integers
                if np.allclose(sample, np.round(sample), equal_nan=True):
                    detected_type = RasterType.CATEGORICAL.value
                    confidence = "HIGH"
                    evidence.append(f"Single-band, {len(unique_values)} discrete integer values")
        except Exception as e:
            logger.debug(f"Could not analyze unique values for categorical detection: {e}")

    # Multispectral Detection (MEDIUM confidence)
    elif band_count >= 5:
        detected_type = RasterType.MULTISPECTRAL.value
        confidence = "MEDIUM"
        evidence.append(f"{band_count} bands (likely multispectral satellite)")

        # Landsat specific
        if band_count in [7, 8, 9, 10, 11]:
            evidence.append("Band count matches Landsat")

        # Sentinel-2 specific
        elif band_count in [12, 13]:
            evidence.append("Band count matches Sentinel-2")

    from util_logger import LoggerFactory, ComponentType
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
    logger.info(f"🔍 VALIDATION TYPE: Detected {detected_type} ({confidence})")

    # User type validation (STRICT)
    if user_type and user_type != "auto":
        if user_type != detected_type:
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
