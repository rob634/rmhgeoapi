# ============================================================================
# CLAUDE CONTEXT - SERVICE - RASTER VALIDATION
# ============================================================================
# PURPOSE: Validate raster files for COG pipeline processing
# EXPORTS: validate_raster() handler function
# INTERFACES: Handler pattern for task execution
# PYDANTIC_MODELS: None (returns dict)
# DEPENDENCIES: rasterio, numpy, config, core.models.enums
# SOURCE: Bronze container raster files via Azure Blob Storage
# SCOPE: Stage 1 of raster processing pipeline
# VALIDATION: CRS, bit-depth, bounds, raster type detection
# PATTERNS: Handler pattern, validation chain
# ENTRY_POINTS: Called by task processor with parameters dict
# ============================================================================

"""
Raster Validation Service - Stage 1 of Raster Pipeline

Validates raster files before expensive COG processing:
- CRS validation (file metadata, user override, sanity checks)
- Bit-depth efficiency analysis (flag 64-bit data as CRITICAL)
- Raster type detection (RGB, RGBA, DEM, categorical, multispectral)
- Type mismatch validation (user-specified vs detected)
- Bounds sanity checks (catch obviously wrong coordinates)

Validation Philosophy: Garbage In = Error Out
- Data owners are responsible for clean data
- 64-bit data types flagged as organizational policy violation
- Detailed error messages force data owners to fix problems
- _skip_validation override for controlled testing only
"""

import sys
from typing import Any, Dict, Optional

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

    print(f"🔍 VALIDATION: Starting raster validation", file=sys.stderr, flush=True)

    # Extract parameters
    blob_url = params.get('blob_url')
    # Support both input_crs and source_crs parameter names
    input_crs = params.get('input_crs') or params.get('source_crs')
    raster_type_param = params.get('raster_type', 'auto')
    strict_mode = params.get('strict_mode', False)
    skip_validation = params.get('_skip_validation', False)

    if not blob_url:
        return {
            "success": False,
            "error": "MISSING_PARAMETER",
            "message": "blob_url parameter is required"
        }

    # TESTING ONLY: Skip validation if requested
    if skip_validation:
        print(f"⚠️ VALIDATION: Skipping validation (_skip_validation=True)", file=sys.stderr, flush=True)
        return {
            "success": True,
            "result": {
                "valid": True,
                "validation_skipped": True,
                "message": "Validation skipped for testing purposes"
            }
        }

    # Lazy import rasterio and numpy
    try:
        np, rasterio, ColorInterp, Window = _lazy_imports()
    except ImportError as e:
        return {
            "success": False,
            "error": "IMPORT_ERROR",
            "message": f"Failed to import dependencies: {e}"
        }

    # Open raster file
    try:
        print(f"📂 VALIDATION: Opening raster: {blob_url[:100]}...", file=sys.stderr, flush=True)
        src = rasterio.open(blob_url)
    except Exception as e:
        return {
            "success": False,
            "error": "FILE_UNREADABLE",
            "message": f"Cannot open raster file: {e}"
        }

    with src:
        # Basic file info
        band_count = src.count
        dtype = src.dtypes[0]
        shape = src.shape
        bounds = src.bounds
        nodata = src.nodata

        print(f"📊 VALIDATION: File info - {band_count} bands, {dtype}, shape {shape}", file=sys.stderr, flush=True)

        # Warnings list
        warnings = []

        # ================================================================
        # 1. CRS VALIDATION
        # ================================================================
        crs_result = _validate_crs(src, input_crs, bounds, skip_validation)
        if not crs_result["success"]:
            return crs_result

        source_crs = crs_result["source_crs"]
        crs_source = crs_result["crs_source"]

        # Add CRS warnings if any
        if "warning" in crs_result:
            warnings.append(crs_result["warning"])

        # ================================================================
        # 2. BIT-DEPTH EFFICIENCY CHECK
        # ================================================================
        bit_depth_result = _check_bit_depth_efficiency(src, dtype, strict_mode)

        # Add bit-depth warnings
        if "warning" in bit_depth_result:
            warnings.append(bit_depth_result["warning"])

            # CRITICAL warnings in strict mode = FAIL
            if strict_mode and bit_depth_result["warning"].get("severity") == "CRITICAL":
                return {
                    "success": False,
                    "error": "BIT_DEPTH_POLICY_VIOLATION",
                    "message": bit_depth_result["warning"]["message"],
                    "bit_depth_check": bit_depth_result
                }

        # ================================================================
        # 3. RASTER TYPE DETECTION
        # ================================================================
        type_result = _detect_raster_type(src, raster_type_param)
        if not type_result["success"]:
            return type_result

        detected_type = type_result["detected_type"]

        # ================================================================
        # 4. GET OPTIMAL COG SETTINGS
        # ================================================================
        optimal_settings = _get_optimal_cog_settings(detected_type)

        # Success result
        result = {
            "success": True,
            "result": {
                "valid": True,
                "source_blob": params.get('blob_name', 'unknown'),
                "source_crs": str(source_crs),
                "crs_source": crs_source,
                "bounds": list(bounds),
                "shape": list(shape),
                "band_count": band_count,
                "dtype": str(dtype),
                "size_mb": params.get('size_mb', 0),  # Passed from job
                "nodata": nodata,

                # Raster type detection
                "raster_type": {
                    "detected_type": detected_type,
                    "confidence": type_result.get("confidence", "UNKNOWN"),
                    "evidence": type_result.get("evidence", []),
                    "type_source": type_result.get("type_source", "auto_detected"),
                    "optimal_cog_settings": optimal_settings
                },

                # Bit-depth analysis
                "bit_depth_check": {
                    "efficient": bit_depth_result.get("efficient", True),
                    "current_dtype": str(dtype),
                    "reason": bit_depth_result.get("reason", "Unknown")
                },

                # Warnings
                "warnings": warnings
            }
        }

        print(f"✅ VALIDATION: Complete - Type: {detected_type}, CRS: {source_crs}", file=sys.stderr, flush=True)
        return result


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
                    print(f"⚠️ VALIDATION CRS: TESTING MODE - Override file CRS {file_crs_str} with user CRS {input_crs}", file=sys.stderr, flush=True)
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
                    print(f"❌ VALIDATION CRS: MISMATCH - File: {file_crs_str}, User: {input_crs}", file=sys.stderr, flush=True)
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
                print(f"✅ VALIDATION CRS: User CRS matches file CRS - {file_crs_str}", file=sys.stderr, flush=True)

        # Use file CRS (either user didn't specify, or user matched file)
        print(f"📍 VALIDATION CRS: From file metadata - {file_crs_str}", file=sys.stderr, flush=True)

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
        if input_crs:
            # User provides CRS for file with no metadata (necessary override)
            print(f"🔧 VALIDATION CRS: File has no CRS, using user override - {input_crs}", file=sys.stderr, flush=True)
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
            print(f"❌ VALIDATION CRS: Missing CRS, no user override", file=sys.stderr, flush=True)
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
        print(f"🚨 VALIDATION BIT-DEPTH: CRITICAL - 64-bit data type {dtype}", file=sys.stderr, flush=True)
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
        print(f"⚠️ VALIDATION BIT-DEPTH: Could not sample data: {e}", file=sys.stderr, flush=True)
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

        print(f"⚠️ VALIDATION BIT-DEPTH: HIGH - Categorical {len(unique_values)} values in {dtype}", file=sys.stderr, flush=True)
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

            print(f"⚠️ VALIDATION BIT-DEPTH: MEDIUM - Integer data in {dtype}", file=sys.stderr, flush=True)
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
        print(f"⚠️ VALIDATION TYPE: Could not sample data: {e}", file=sys.stderr, flush=True)
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
        except:
            pass

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
        except:
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
            except:
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
        except:
            pass

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

    print(f"🔍 VALIDATION TYPE: Detected {detected_type} ({confidence})", file=sys.stderr, flush=True)

    # User type validation (STRICT)
    if user_type and user_type != "auto":
        if user_type != detected_type:
            print(f"❌ VALIDATION TYPE: MISMATCH - User: {user_type}, Detected: {detected_type}", file=sys.stderr, flush=True)
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
