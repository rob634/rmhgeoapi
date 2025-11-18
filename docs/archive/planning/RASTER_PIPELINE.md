# Raster Processing Pipeline Design

**Author**: Robert and Geospatial Claude Legion
**Date**: 8 OCT 2025
**Status**: Design Phase - Implementation Pending

## Overview

Two-tiered raster processing pipeline for converting geospatial rasters to Cloud Optimized GeoTIFFs (COGs) with EPSG:4326 projection. Pipeline branches based on file size to handle both small files efficiently and large files with parallelization.

**Key Innovation**: Uses `rio-cogeo.cog_translate()` to combine reprojection + COG creation in a single operation, eliminating intermediate storage and reducing pipeline stages from 3 to 2 for small files.

## Design Principles

- **DRY (Don't Repeat Yourself)**: Services are reusable across both pipelines
- **Phased Implementation**: Small file pipeline (<1GB) first, then large file pipeline
- **ID-Based Lineage Tracking**: Task parameters track input/output files for complete provenance
- **Single-Pass Processing**: rio-cogeo reprojects + creates COG in one operation (no intermediate files)
- **Fail Fast**: Validation happens first to reject invalid inputs before expensive processing
- **Intelligent Validation**: Detect and reject garbage data from careless data owners
- **Data Owner Accountability**: System doesn't accommodate bad data - fixes are the data owner's responsibility

## Validation Philosophy: Garbage In = Error Out

**Critical Stance**: This is an expensive system. Data owners must deposit properly formatted data. We don't accommodate garbage.

**What We Catch**:
1. ✅ **Missing CRS** - Reject with clear message to provide `input_crs`
2. ✅ **64-bit data types** - Flag as CRITICAL policy violation (no legitimate use case)
3. ✅ **Inefficient bit-depth** - Warn about float64 for 5-class categorical data (87.5% waste)
4. ✅ **Raster type mismatches** - FAIL if user says "RGB" but file has 12 bands
5. ✅ **Suspicious bounds** - Warn if bounds obviously wrong for CRS (e.g., lat > 90°)
6. ✅ **Auto-detect raster types** - Optimize COG settings for RGB, RGBA (drone), DEM, categorical
7. ⚠️ **Cannot detect mislabeled CRS** - User responsibility to know their data

**Default Behavior**: Log warnings, continue processing (data owner gets notified about waste)
**Strict Mode**: Reject files with warnings (force data owner to fix garbage before wasting compute)

**Result**: Clean, efficient data in silver tier. Garbage gets rejected with detailed error messages.

## Pipeline Architecture

### Pipeline Selection Criteria

```
IF raster_size <= 1GB:
    → Small File Pipeline (2 stages, sequential)
ELSE:
    → Large File Pipeline (3 stages, stage 3 fan-out parallelization)
```

---

## Pipeline 1: Small Files (<= 1GB)

**Target Use Case**: Single rasters, quick turnaround, no parallelization needed

### Stage 1: Validate Raster

**Task Type**: `validate_raster`
**Input**: Bronze container raster file
**Output**: Validation results + warnings (file remains in bronze)

**Validation Checks**:
1. ✅ File is readable by GDAL/rasterio
2. ✅ Has valid CRS (from file metadata OR user-provided `input_crs` parameter)
3. ✅ Has valid bounds and dimensions
4. ✅ Band count > 0
5. ✅ No corruption in raster headers
6. ⚠️ **Bit-depth efficiency check** (warn if inefficient, CRITICAL for 64-bit)
7. ⚠️ **Nodata handling** (detect and validate)
8. 🔍 **Raster type detection** (auto-detect or user-specified)
9. ❌ **Raster type mismatch detection** (fail if user type doesn't match file)

**Parameters**:
- `container`: Bronze container name
- `blob_name`: Source raster path
- `input_crs`: (Optional) Override CRS if file metadata missing/incorrect (e.g., "EPSG:32611")
- `raster_type`: (Optional) Explicit raster type - if provided, file MUST match or fail
  - Allowed values: `"rgb"`, `"rgba"`, `"dem"`, `"categorical"`, `"multispectral"`, `"nir"`, `"auto"`
  - Default: `"auto"` (detect automatically)
- `strict_mode`: (Optional, default=False) Fail on warnings vs. log warnings and proceed
- `_skip_validation`: (Optional, default=False) **TESTING ONLY** - Skip all validation checks
  - **HIDDEN PARAMETER** - Not documented in API, used only for testing
  - Bypasses: CRS checks, bit-depth checks, raster type validation, bounds checks
  - **WARNING**: Use only for controlled testing with known garbage data

---

### Validation Strategy: CRS Issues

**Problem**: Rasters may have:
- No CRS in metadata
- Wrong CRS in metadata (but we can't detect this - see below)
- Unparseable CRS strings

**Brutal Honesty**: We **cannot** detect mislabeled CRS. If a file says "EPSG:32611" but is actually "EPSG:32610", it looks valid to us. We trust file metadata by default. **Data owners are responsible for correct CRS metadata.**

**Solution - Two-Tier Approach**:

#### Tier 1: File Metadata CRS (Trust by Default)
```python
with rasterio.open(blob_url) as src:
    if src.crs is not None:
        source_crs = src.crs
        crs_source = "file_metadata"

        # Log prominently for user review
        logger.info(f"Using CRS from file metadata: {src.crs}")
        logger.info(f"Bounds: {src.bounds}")

        # Sanity check: Bounds obviously wrong for CRS?
        if not validate_bounds_for_crs(src.crs, src.bounds):
            logger.warning(
                f"Bounds {src.bounds} suspicious for CRS {src.crs}. "
                f"CRS may be mislabeled. Review metadata or use input_crs parameter."
            )
```

**Sanity Checks** (catches obviously wrong bounds):
```python
def validate_bounds_for_crs(crs, bounds):
    """Basic sanity checks for obviously wrong bounds."""

    # EPSG:4326 (WGS84) - must be -180 to 180, -90 to 90
    if crs == "EPSG:4326":
        if not (-180 <= bounds[0] <= 180 and -180 <= bounds[2] <= 180):
            return False  # Longitude out of range
        if not (-90 <= bounds[1] <= 90 and -90 <= bounds[3] <= 90):
            return False  # Latitude out of range

    # UTM zones (EPSG:326xx, EPSG:327xx) - easting should be 0-1000000m
    if str(crs).startswith("EPSG:326") or str(crs).startswith("EPSG:327"):
        if bounds[0] < -1000000 or bounds[0] > 2000000:
            return False  # Easting way outside valid range

    return True  # Looks plausible
```

#### Tier 2: User-Provided `input_crs` Parameter (Override)
```python
if input_crs parameter provided:
    # User KNOWS file metadata is wrong or missing
    source_crs = input_crs
    crs_source = "user_provided"

    if src.crs and src.crs != input_crs:
        logger.warning(
            f"CRS OVERRIDE: File has {src.crs}, user specified {input_crs}. "
            f"Using user-provided CRS."
        )
    else:
        logger.info(f"Using user-provided CRS: {input_crs}")
```

#### Tier 3: Failure (No CRS Available)
```python
if src.crs is None and input_crs is None:
    # Cannot proceed without CRS
    return {
        "success": False,
        "error": "CRS_MISSING",
        "message": "Raster has no CRS in metadata and no input_crs parameter provided. "
                   "Provide input_crs parameter to proceed.",
        "suggestion": "Resubmit job with 'input_crs' parameter (e.g., 'EPSG:32611')",
        "file_info": {
            "blob_name": blob_name,
            "bounds": src.bounds,
            "shape": src.shape
        }
    }
```

**Key Design Decisions**:
- **Trust but verify**: Use file metadata by default, add sanity checks for obviously wrong bounds
- **User override available**: If user KNOWS metadata is wrong, `input_crs` parameter overrides
- **Cannot detect subtle errors**: Mislabeled CRS (e.g., Zone 11 vs Zone 10) looks valid to us
- **Data owner responsibility**: Correct CRS metadata is the data owner's job, not ours

---

### Validation Strategy: Bit-Depth Efficiency

**Problem**: Data owners deposit inefficient rasters:
- 64-bit float for categorical data with 5 classes
- 64-bit integers (no legitimate use case for this organization)
- 32-bit float for 8-bit elevation data
- Unnecessary precision wastes storage, bandwidth, and money

**Organizational Policy**: **All 64-bit data types are flagged**. There is no legitimate use case for 64-bit data in this system.

**Solution - Detect and Flag**:

```python
def check_bit_depth_efficiency(src: rasterio.DatasetReader) -> dict:
    """
    Analyze if raster uses inefficient bit-depth.

    ORGANIZATIONAL POLICY: All 64-bit data types are flagged as CRITICAL.

    Returns:
        {
            "efficient": True/False,
            "current_dtype": "float64",
            "recommended_dtype": "uint8",
            "reason": "Categorical data with 5 unique values",
            "potential_savings_percent": 87.5,
            "warning_level": "CRITICAL"  # For 64-bit data
        }
    """
    dtype = src.dtypes[0]

    # ORGANIZATIONAL POLICY: Flag ALL 64-bit data types immediately
    if dtype in ['float64', 'int64', 'uint64', 'complex64', 'complex128']:
        return {
            "efficient": False,
            "current_dtype": str(dtype),
            "recommended_dtype": "ANALYZE_DATA",  # Depends on actual data
            "reason": f"64-bit data type ({dtype}) has no legitimate use case for this organization",
            "potential_savings_percent": 50.0,  # Minimum (64-bit to 32-bit)
            "warning_level": "CRITICAL",
            "policy_violation": True,
            "message": "POLICY VIOLATION: 64-bit data types are not acceptable. "
                       "Contact data owner to provide properly formatted raster."
        }

    # Sample data to analyze (for 32-bit and smaller types)
    sample = src.read(1, window=Window(0, 0, min(1000, src.width), min(1000, src.height)))
    unique_values = np.unique(sample[~np.isnan(sample)])
    value_range = (sample.min(), sample.max())

    # Check for categorical data in float types
    if dtype in ['float32', 'float16'] and len(unique_values) < 256:
        if len(unique_values) <= 255:
            recommended = "uint8"
            savings = ((np.dtype(dtype).itemsize - 1) / np.dtype(dtype).itemsize) * 100
        else:
            recommended = "uint16"
            savings = ((np.dtype(dtype).itemsize - 2) / np.dtype(dtype).itemsize) * 100

        return {
            "efficient": False,
            "current_dtype": str(dtype),
            "recommended_dtype": recommended,
            "reason": f"Categorical/discrete data with {len(unique_values)} unique values stored as {dtype}",
            "unique_value_count": len(unique_values),
            "potential_savings_percent": round(savings, 1),
            "warning_level": "HIGH"
        }

    # Check for integer data in float types
    if dtype in ['float32', 'float16']:
        # Check if all values are integers
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

            return {
                "efficient": False,
                "current_dtype": str(dtype),
                "recommended_dtype": recommended,
                "reason": f"Integer data (range: {min_val} to {max_val}) stored as {dtype}",
                "value_range": value_range,
                "potential_savings_percent": round(savings, 1),
                "warning_level": "MEDIUM"
            }

    # Check for unnecessarily large int types (32-bit that could be smaller)
    if dtype in ['uint32', 'int32']:
        min_val, max_val = value_range

        if dtype == 'uint32' and max_val <= 65535:
            return {
                "efficient": False,
                "current_dtype": "uint32",
                "recommended_dtype": "uint16" if max_val <= 65535 else "uint8",
                "reason": f"Data range (0 to {max_val}) fits in smaller type",
                "potential_savings_percent": 50.0,
                "warning_level": "MEDIUM"
            }

    # Bit-depth is appropriate
    return {
        "efficient": True,
        "current_dtype": str(dtype),
        "reason": "Bit-depth appropriate for data type and range"
    }
```

**Behavior by Warning Level**:
- **CRITICAL (64-bit types)**:
  - `strict_mode=False`: Log CRITICAL warning, continue processing (but data owner gets notified)
  - `strict_mode=True`: **FAIL validation**, reject raster, require data owner to fix source
- **HIGH (categorical in float32)**:
  - `strict_mode=False`: Log warning, continue processing
  - `strict_mode=True`: Fail validation
- **MEDIUM (inefficient int types)**:
  - Log warning, continue processing (regardless of strict_mode)

**Example CRITICAL Warning (64-bit data)**:
```python
{
    "validation_warnings": [
        {
            "type": "INEFFICIENT_BIT_DEPTH",
            "severity": "CRITICAL",
            "current_dtype": "float64",
            "recommended_dtype": "ANALYZE_DATA",
            "reason": "64-bit data type (float64) has no legitimate use case for this organization",
            "potential_savings_percent": 50.0,
            "policy_violation": True,
            "message": "POLICY VIOLATION: 64-bit data types are not acceptable. "
                       "Contact data owner to provide properly formatted raster. "
                       "This raster wastes storage and bandwidth."
        }
    ]
}
```

**Example HIGH Warning (categorical in float)**:
```python
{
    "validation_warnings": [
        {
            "type": "INEFFICIENT_BIT_DEPTH",
            "severity": "HIGH",
            "current_dtype": "float64",
            "recommended_dtype": "uint8",
            "reason": "Categorical data with 5 unique values stored as float64",
            "potential_savings_percent": 87.5,
            "message": "Consider converting source raster to uint8 for 87.5% size reduction"
        }
    ]
}
```

**Future Enhancement**: Add `auto_optimize_dtype=True` parameter to automatically convert dtype during COG creation (for Phase 2).

---

### Validation Strategy: Raster Type Detection

**Purpose**: Automatically detect raster type to optimize COG settings (compression, resampling). Critical for drone imagery (RGBA) and scientific data (DEM).

**Design Philosophy**:
- **Auto-detection by default**: Analyze file characteristics to infer type
- **User override available**: `raster_type` parameter explicitly specifies type
- **Strict validation**: If user specifies type, file MUST match or FAIL with detailed error
- **Optimized processing**: Use type-specific COG settings

**Raster Type Enum**:
```python
class RasterType(str, Enum):
    RGB = "rgb"              # 3-band uint8/uint16 imagery (drone, aerial)
    RGBA = "rgba"            # 4-band uint8/uint16 with alpha (drone, ortho)
    DEM = "dem"              # Single-band elevation (float32, int16)
    CATEGORICAL = "categorical"  # Single-band discrete classes (land cover)
    MULTISPECTRAL = "multispectral"  # 5+ bands (Landsat, Sentinel, Planet)
    NIR = "nir"              # 4-band with NIR (RGB + Near-Infrared)
    UNKNOWN = "unknown"      # Cannot determine type
```

**Detection Logic**:
```python
def detect_raster_type(src: rasterio.DatasetReader, user_type: str = "auto") -> dict:
    """
    Detect raster type from file characteristics.

    If user_type specified, validate file matches - FAIL if mismatch.
    """

    band_count = src.count
    dtype = src.dtypes[0]

    # Sample data for analysis
    sample = src.read(1, window=Window(0, 0, min(1000, src.width), min(1000, src.height)))

    # Detect type from file characteristics
    detected_type = "unknown"
    confidence = "LOW"
    evidence = []

    # RGB Detection (HIGH confidence)
    if band_count == 3 and dtype in ['uint8', 'uint16']:
        detected_type = "rgb"
        confidence = "HIGH"
        evidence.append(f"3 bands, {dtype} (standard RGB)")

        # Check color interpretation
        if src.colorinterp[0] == ColorInterp.red:
            evidence.append("Color interpretation: Red/Green/Blue")
            confidence = "VERY_HIGH"

    # RGBA Detection (HIGH confidence) - CRITICAL FOR DRONE IMAGERY
    elif band_count == 4 and dtype in ['uint8', 'uint16']:
        # Check if 4th band is alpha (low unique values, often 0 or 255)
        alpha_band = src.read(4, window=Window(0, 0, min(1000, src.width), min(1000, src.height)))
        unique_alpha = np.unique(alpha_band)

        if len(unique_alpha) <= 10:  # Alpha typically has few values
            detected_type = "rgba"
            confidence = "HIGH"
            evidence.append(f"4 bands, {dtype}, alpha band detected ({len(unique_alpha)} unique values)")
        else:
            # Could be NIR or multispectral
            detected_type = "nir"
            confidence = "MEDIUM"
            evidence.append(f"4 bands, {dtype} (likely RGB + NIR)")

    # DEM Detection (HIGH confidence)
    elif band_count == 1 and dtype in ['float32', 'float64', 'int16', 'int32']:
        # Check for smooth gradients (spatial autocorrelation)
        # DEMs have neighboring pixels with similar values
        if sample.size >= 100:
            # Simple autocorrelation check
            horizontal_diff = np.abs(np.diff(sample, axis=1)).mean()
            vertical_diff = np.abs(np.diff(sample, axis=0)).mean()
            value_range = sample.max() - sample.min()

            smoothness = (horizontal_diff + vertical_diff) / (2 * value_range) if value_range > 0 else 0

            if smoothness < 0.1:  # Very smooth = likely DEM
                detected_type = "dem"
                confidence = "HIGH"
                evidence.append(f"Single-band {dtype}, smooth gradients (smoothness: {smoothness:.3f})")
            else:
                detected_type = "dem"
                confidence = "MEDIUM"
                evidence.append(f"Single-band {dtype} (likely elevation, but not smooth)")

    # Categorical Detection (HIGH confidence)
    elif band_count == 1:
        unique_values = np.unique(sample[~np.isnan(sample)])

        if len(unique_values) < 256:
            # Check if values are integers
            if np.allclose(sample, np.round(sample), equal_nan=True):
                detected_type = "categorical"
                confidence = "HIGH"
                evidence.append(f"Single-band, {len(unique_values)} discrete integer values")

    # Multispectral Detection (MEDIUM confidence)
    elif band_count >= 5:
        detected_type = "multispectral"
        confidence = "MEDIUM"
        evidence.append(f"{band_count} bands (likely multispectral satellite)")

        # Landsat specific
        if band_count in [7, 8, 9, 10, 11]:
            evidence.append("Band count matches Landsat")

        # Sentinel-2 specific
        elif band_count in [12, 13]:
            evidence.append("Band count matches Sentinel-2")

    # User type validation (STRICT)
    if user_type and user_type != "auto":
        if user_type != detected_type:
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
```

**Type-Specific COG Settings**:
```python
def get_optimal_cog_settings(raster_type: str) -> dict:
    """Get optimal COG settings based on raster type."""

    settings = {
        "rgb": {
            "compression": "jpeg",  # Lossy OK for visual
            "jpeg_quality": 85,
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        },
        "rgba": {
            "compression": "webp",  # Supports alpha, better than JPEG
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        },
        "dem": {
            "compression": "lerc_deflate",  # Lossless for scientific
            "overview_resampling": "average",  # Preserve statistics
            "reproject_resampling": "bilinear"
        },
        "categorical": {
            "compression": "deflate",  # Lossless
            "overview_resampling": "mode",  # Preserve classes
            "reproject_resampling": "nearest"  # No interpolation!
        },
        "multispectral": {
            "compression": "deflate",  # Lossless for scientific
            "overview_resampling": "average",
            "reproject_resampling": "bilinear"
        },
        "nir": {
            "compression": "deflate",  # Lossless
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        },
        "unknown": {
            "compression": "deflate",  # Safe default
            "overview_resampling": "cubic",
            "reproject_resampling": "cubic"
        }
    }

    return settings.get(raster_type, settings["unknown"])
```

---

### Validation Success Result

```python
{
    "success": True,
    "result": {
        "valid": True,
        "source_blob": "bronze/2024/raster.tif",
        "source_crs": "EPSG:32611",
        "crs_source": "user_provided",
        "bounds": [-120.5, 38.5, -119.5, 39.5],
        "shape": [10000, 10000],
        "band_count": 3,
        "dtype": "uint8",
        "size_mb": 285.4,
        "nodata": 0,

        # Raster type detection
        "raster_type": {
            "detected_type": "rgb",
            "confidence": "VERY_HIGH",
            "evidence": [
                "3 bands, uint8 (standard RGB)",
                "Color interpretation: Red/Green/Blue"
            ],
            "type_source": "auto_detected",
            "optimal_cog_settings": {
                "compression": "jpeg",
                "jpeg_quality": 85,
                "overview_resampling": "cubic",
                "reproject_resampling": "cubic"
            }
        },

        # Bit-depth analysis
        "bit_depth_check": {
            "efficient": True,
            "current_dtype": "uint8",
            "reason": "Bit-depth appropriate for data type and range"
        },

        # Warnings (if any)
        "warnings": []
    }
}
```

---

### Validation Failure: Raster Type Mismatch

**Scenario**: User specifies `raster_type="rgb"` but file has 12 bands (multispectral satellite data)

```python
{
    "success": False,
    "error": "RASTER_TYPE_MISMATCH",
    "message": "User specified raster_type='rgb' but file characteristics indicate 'multispectral'. "
               "File has 12 bands, dtype uint16. "
               "Evidence: 12 bands (likely multispectral satellite); Band count matches Sentinel-2. "
               "Either fix the source file or use correct raster_type parameter.",
    "user_specified_type": "rgb",
    "detected_type": "multispectral",
    "confidence": "MEDIUM",
    "file_characteristics": {
        "band_count": 12,
        "dtype": "uint16",
        "shape": [10980, 10980],
        "evidence": [
            "12 bands (likely multispectral satellite)",
            "Band count matches Sentinel-2"
        ]
    },
    "suggestion": "This appears to be Sentinel-2 multispectral data, not RGB. "
                  "Either use raster_type='multispectral' or provide correct RGB file."
}
```

**Job Status**: `FAILED` (data owner deposited wrong file or used wrong parameter)

**Why This Matters**: Prevents processing 12-band satellite data with RGB JPEG compression (would fail spectacularly). Forces data owner to fix their mistake.

---

### Validation Failure: CRS Missing

```python
{
    "success": False,
    "error": "CRS_MISSING",
    "message": "Raster has no CRS in metadata and no input_crs parameter provided. "
               "Provide input_crs parameter (e.g., 'EPSG:32611') to proceed.",
    "suggestion": "Resubmit job with 'input_crs' parameter",
    "example": {
        "blob_name": "2024/raster.tif",
        "container": "rmhazuregeobronze",
        "input_crs": "EPSG:32611"  # User must provide this
    }
}
```

**Job Status**: `FAILED` (not retryable - user must provide CRS)

---

### Validation Warning: Inefficient Bit-Depth

```python
{
    "success": True,  # Continues processing
    "result": {
        "valid": True,
        "source_blob": "bronze/2024/landcover.tif",
        "source_crs": "EPSG:32611",
        "dtype": "float64",
        "size_mb": 1842.5,

        "bit_depth_check": {
            "efficient": False,
            "current_dtype": "float64",
            "recommended_dtype": "uint8",
            "reason": "Categorical data with 5 unique values stored as float64",
            "unique_value_count": 5,
            "potential_savings_percent": 87.5,
            "warning_level": "HIGH"
        },

        "warnings": [
            {
                "type": "INEFFICIENT_BIT_DEPTH",
                "severity": "HIGH",
                "message": "Raster uses float64 for categorical data with 5 classes. "
                           "Converting to uint8 would reduce size by 87.5% (1842.5 MB → 230.3 MB). "
                           "Consider optimizing source data before reprocessing.",
                "action": "CONTINUE_WITH_WARNING"
            }
        ]
    }
}
```

**Job Status**: `PROCESSING` (continues to Stage 2 with warning)

---

### Stage 2: Reproject + Create COG (Combined Operation)

**Task Type**: `create_cog`
**Input**: Bronze container raster (from Stage 1 validation)
**Output**: COG in silver container

**Key Innovation**: Single `rio-cogeo.cog_translate()` call does **both** reprojection and COG creation in one pass!

**Processing Logic**:
```python
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from rasterio.enums import Resampling

# Check if reprojection needed
if stage_1_result["source_crs"] == "EPSG:4326":
    # Skip reprojection, just create COG
    config = {}
else:
    # Reproject + create COG
    config = {
        "dst_crs": "EPSG:4326",
        "resampling": Resampling.cubic,  # Reprojection quality
    }

# Single operation: reproject (if needed) + create COG
cog_translate(
    src_path=blob_url,  # Bronze container
    dst_path=local_output_path,  # Temp local file
    cog_profile=cog_profiles.get(compression),
    config=config,
    overview_resampling=Resampling.cubic,
    in_memory=False,  # Use disk for stability
    quiet=False,
)

# Upload to silver container
upload_to_blob(local_output_path, silver_blob_path)
```

**Parameters**:
- `source_blob`: Bronze container path (from Stage 1)
- `source_crs`: Source CRS (from Stage 1)
- `target_crs`: "EPSG:4326" (hardcoded)
- `compression`: "deflate" (default), "zstd", "lzw", "jpeg", "webp"
- `jpeg_quality`: 85 (only for jpeg compression)
- `overview_resampling`: "cubic" (default), "bilinear", "average", "mode"
- `reproject_resampling`: "cubic" (default), "bilinear", "lanczos"

**Success Result**:
```python
{
    "success": True,
    "result": {
        "cog_blob": "silver/2024/raster_cog.tif",
        "cog_container": "rmhazuregeosilver",
        "source_blob": "bronze/2024/raster.tif",
        "reprojection_performed": True,  # or False if already EPSG:4326
        "source_crs": "EPSG:32611",
        "target_crs": "EPSG:4326",
        "bounds_4326": [-120.5, 38.5, -119.5, 39.5],
        "size_mb": 195.3,
        "compression": "deflate",
        "tile_size": [512, 512],
        "overview_levels": [2, 4, 8, 16],
        "processing_time_seconds": 12.4
    }
}
```

**No intermediate storage needed** - Bronze → Silver directly! ✨

---

## Rio-cogeo: Complete Parameter Reference

### Why rio-cogeo?

**Research-Backed Decision** (based on web search 8 OCT 2025):
1. ✅ **Proven in Azure Functions**: Already successfully used in your environment
2. ✅ **Single-Pass Processing**: Reproject + COG in one operation
3. ✅ **Smart Defaults**: 512x512 tiles, auto-calculated overviews, DEFLATE compression
4. ✅ **Built-in Validation**: Can validate COGs after creation
5. ✅ **Modern**: Uses GDAL 3.1+ COG driver when available

**Alternative Considered**: Native GDAL COG driver
- **Performance**: Faster for huge files (300k x 150k pixels)
- **Issue**: rio-cogeo can get stuck on massive compressed files (tries to decompress all)
- **Decision**: Use rio-cogeo for <1GB files, consider tiling strategy for >1GB

---

### Compression Profiles (Complete List)

| Profile | Compression | Lossless | Use Case | Benchmark Results |
|---------|-------------|----------|----------|-------------------|
| `deflate` | DEFLATE | ✅ Yes | **Default - Universal** | 167MB → 58MB (65% reduction) |
| `lzw` | LZW | ✅ Yes | Alternative lossless | Similar to DEFLATE |
| `zstd` | ZSTD | ✅ Yes | Modern lossless (GDAL 3.1+) | Better than DEFLATE |
| `jpeg` | JPEG | ❌ No | RGB imagery (visual) | 167MB → 4.8MB (97% reduction!) |
| `webp` | WebP | ❌ No | RGB/RGBA imagery | Better than JPEG, supports alpha |
| `lerc` | LERC | ✅ Yes | Elevation/scientific | Lossless for floating point |
| `lerc_deflate` | LERC+DEFLATE | ✅ Yes | DEMs + extra compression | Best for elevation data |
| `lerc_zstd` | LERC+ZSTD | ✅ Yes | DEMs (GDAL 3.1+) | Better than lerc_deflate |
| `packbits` | PackBits | ✅ Yes | Simple RLE compression | Legacy, poor compression |
| `lzma` | LZMA | ✅ Yes | High compression, slow | Not recommended |
| `raw` | None | ✅ Yes | No compression | Largest files, fastest access |

**Recommendations by Data Type**:
- **General Purpose**: `deflate` (default) - 65% reduction, lossless, universal
- **Modern Systems**: `zstd` - Better compression than DEFLATE (requires GDAL 3.1+)
- **RGB Imagery (Visual)**: `jpeg` quality 85 - 97% reduction (lossy but acceptable for visual)
- **RGB with Transparency**: `webp` - Better than JPEG, supports alpha
- **Elevation/DEMs**: `lerc_deflate` - Lossless for floating point, excellent compression
- **Categorical/Land Cover**: `deflate` or `lzw` - Lossless, good for discrete values

**Warning**: Do NOT use lossy compression (JPEG/WebP) with internal nodata values or for scientific data requiring exact values.

---

### Tile Size / Blocksize

**Default**: 512x512 pixels

**Rationale**:
- Matches web tile standards (256x256 or 512x512)
- Good balance between HTTP request count and transfer size
- Optimal for cloud-native access patterns

**Custom Tile Sizes**:
```python
config = {
    "BLOCKXSIZE": 256,   # Smaller tiles, more HTTP requests
    "BLOCKYSIZE": 256,
}

config = {
    "BLOCKXSIZE": 1024,  # Larger tiles, fewer HTTP requests
    "BLOCKYSIZE": 1024,
}
```

**Guidelines**:
- **256x256**: Better for web mercator alignment, more granular access
- **512x512**: Default, best general-purpose (RECOMMENDED)
- **1024x1024**: Better for large files, but larger GET requests

**Recommendation**: Keep default **512x512** for web-optimized access.

---

### Overview Levels (Pyramids)

**Default**: Auto-calculated based on dataset size

**How it works**:
```python
overview_level=None  # Auto-calculates (RECOMMENDED)
overview_level=3     # Creates overviews at [2, 4, 8]
overview_level=5     # Creates overviews at [2, 4, 8, 16, 32]
overview_level=0     # No overviews (not recommended for COGs)
```

**Auto-Calculation Logic**:
- Creates overviews until smallest dimension <= tile size (512px)
- Power-of-2 decimation: 1/2, 1/4, 1/8, 1/16, etc.
- Ensures efficient zooming at all scales

**Example**:
- Dataset: 10,000 x 10,000 pixels
- Auto-generated levels: [2, 4, 8, 16] (5000, 2500, 1250, 625 pixels)
- Stops at 625 pixels (just above 512px tile size)

**Recommendation**: Use **auto (None)** - rio-cogeo calculates optimal levels.

---

### Overview Resampling Methods

**Purpose**: How to downsample data when creating pyramid overviews

| Method | Use Case | Quality | Speed |
|--------|----------|---------|-------|
| `nearest` | Categorical data (land cover) | Preserves values | Fast |
| `mode` | Categorical data (preferred) | Most common value | Medium |
| `bilinear` | Continuous data (elevation, imagery) | Good | Fast |
| `cubic` | High-quality imagery | Best | Medium |
| `average` | Downsampling, DEMs | Good for means | Fast |
| `lanczos` | Highest quality imagery | Excellent | Slow |

**Recommendations**:
- **RGB Imagery**: `cubic` (best quality) or `bilinear` (faster)
- **Elevation/DEMs**: `average` (preserves statistics) or `bilinear`
- **Land Cover/Categorical**: `mode` (preserves classes) or `nearest`

---

### Reprojection Resampling Methods

**Purpose**: How to interpolate pixel values when reprojecting to new CRS

| Method | Use Case | Quality | Speed |
|--------|----------|---------|-------|
| `nearest` | Categorical data (land cover) | Preserves exact values | Fast |
| `bilinear` | Continuous data | Good | Fast |
| `cubic` | High-quality imagery | Best | Medium |
| `lanczos` | Highest quality imagery | Excellent | Slow |
| `average` | Downsampling | Good for aggregation | Fast |

**Recommendations**:
- **RGB Imagery**: `cubic` (best quality, RECOMMENDED)
- **Elevation/DEMs**: `bilinear` or `cubic`
- **Land Cover/Categorical**: `nearest` (preserves class values)

**Warning**: Never use averaging/interpolation methods for categorical data!

---

### Nodata Handling

```python
# Auto-detect from source (default)
nodata=None

# Set custom nodata value
nodata=0
nodata=-9999

# Add internal bit mask (for byte/uint16 data)
add_mask=True
```

**Recommendations**:
- **Default**: Let rio-cogeo auto-detect and forward nodata from source
- **Custom**: Only override if source nodata is incorrect
- **Internal Mask**: Use for byte/uint16 data instead of nodata values

**Warning**: Do NOT use lossy compression (JPEG/WebP) with nodata values - causes artifacts at boundaries.

---

### Web-Optimized COGs

**Purpose**: Align COG to web mercator grid for tiling services

```python
cog_translate(
    src_path,
    dst_path,
    web_optimized=True,  # Aligns to web mercator grid
    cog_profile=cog_profiles.get("deflate"),
)
```

**Requirements**:
- Must have nodata value, alpha band, or internal mask
- Prevents black padding at tile edges

**Use Case**: Serving COGs via dynamic XYZ tiling services

**Recommendation**: Only use for web tile serving, not for general COG creation.

---

### Complete Code Example

```python
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from rasterio.enums import Resampling

def create_cog_from_bronze(
    source_blob_url: str,
    output_local_path: str,
    source_crs: str,
    target_crs: str = "EPSG:4326",
    compression: str = "deflate",
    jpeg_quality: int = 85,
    overview_resampling: str = "cubic",
    reproject_resampling: str = "cubic",
) -> dict:
    """
    Create COG with optional reprojection using rio-cogeo.

    Single operation combines reprojection + COG creation.

    Args:
        source_blob_url: Azure blob URL with SAS token
        output_local_path: Local temp path for output
        source_crs: Source CRS from validation
        target_crs: Target CRS (default: EPSG:4326)
        compression: deflate, lzw, zstd, jpeg, webp, lerc_deflate
        jpeg_quality: JPEG quality 1-100 (only for jpeg)
        overview_resampling: Resampling for overviews (cubic, bilinear, mode)
        reproject_resampling: Resampling for reprojection (cubic, bilinear, nearest)

    Returns:
        dict with success status, output path, and metadata
    """

    # Get COG profile
    cog_profile = cog_profiles.get(compression)

    # Add JPEG quality if using JPEG compression
    if compression == "jpeg":
        cog_profile["QUALITY"] = jpeg_quality

    # Determine if reprojection needed
    needs_reprojection = (source_crs != target_crs)

    # Configure reprojection if needed
    if needs_reprojection:
        config = {
            "dst_crs": target_crs,
            "resampling": getattr(Resampling, reproject_resampling),
        }
    else:
        config = {}

    # Create COG (with optional reprojection)
    cog_translate(
        source_blob_url,
        output_local_path,
        cog_profile,
        config=config,
        overview_level=None,  # Auto-calculate optimal levels
        overview_resampling=getattr(Resampling, overview_resampling),
        in_memory=False,  # Use disk for large files (more stable)
        quiet=False,  # Show progress
    )

    return {
        "success": True,
        "output_path": output_local_path,
        "reprojection_performed": needs_reprojection,
        "source_crs": source_crs,
        "target_crs": target_crs,
        "compression": compression,
    }
```

---

## Pipeline 2: Large Files (> 1GB)

**Target Use Case**: Massive rasters (2-10+ GB), requires parallelization to avoid timeouts

**Research Finding**: Rio-cogeo can struggle with large compressed files (tries to decompress entire file), causing multi-hour processing times or crashes.

**Solution**: Tile-based parallelization (same services, different orchestration)

### Stage 1: Validate Raster

**Identical to Small File Pipeline Stage 1**

Same validation logic, same CRS handling, same bit-depth checks. No changes needed.

---

### Stage 2: Create Tiling Strategy

**Task Type**: `create_tiling_strategy`
**Input**: Bronze container raster (from Stage 1 validation)
**Output**: Tiling scheme for parallel processing

**Tiling Strategy**:
1. Read raster dimensions and bounds (header only, fast)
2. Calculate optimal tile size (e.g., 5000x5000 pixels per tile)
3. Generate tile grid with overlap for seamless merging
4. Create tile manifest with windows and bounds

**Parameters**:
- `source_blob`: Bronze container path (from Stage 1)
- `source_crs`: Source CRS (from Stage 1)
- `target_tile_size`: 5000 (pixels, configurable)
- `tile_overlap`: 100 (pixels, for seamless stitching)

**Success Result**:
```python
{
    "success": True,
    "result": {
        "source_blob": "bronze/2024/huge_raster.tif",
        "total_tiles": 25,  # 5x5 grid
        "tile_grid": {
            "rows": 5,
            "cols": 5
        },
        "tile_size_pixels": [5000, 5000],
        "overlap_pixels": 100,
        "tiles": [
            {
                "tile_id": "tile_0_0",
                "row": 0,
                "col": 0,
                "window": {"row_off": 0, "col_off": 0, "width": 5000, "height": 5000},
                "bounds": [-120.5, 39.0, -120.0, 39.5]
            },
            {
                "tile_id": "tile_0_1",
                "row": 0,
                "col": 1,
                "window": {"row_off": 0, "col_off": 4900, "width": 5000, "height": 5000},
                "bounds": [-120.0, 39.0, -119.5, 39.5]
            },
            # ... 23 more tiles
        ]
    }
}
```

---

### Stage 3: Parallel Tile Processing (Fan-Out)

**Task Type**: `process_raster_tile` (one task per tile)
**Input**: One tile from tiling strategy
**Output**: Reprojected + COG-optimized tile in intermediate storage

**Fan-Out Pattern**:
```python
# Stage 2 creates 25 tiles → Stage 3 creates 25 parallel tasks
for tile in stage_2_result["tiles"]:
    create_task(
        task_type="process_raster_tile",
        parameters={
            "source_blob": stage_2_result["source_blob"],
            "tile_id": tile["tile_id"],
            "window": tile["window"],
            "bounds": tile["bounds"],
            "target_crs": "EPSG:4326",
            "compression": "deflate",
            "job_id": job_id
        }
    )
```

**Per-Tile Processing** (using rio-cogeo):
1. **Extract Tile**: Read tile window from bronze raster
2. **Reproject + Create COG**: Single `cog_translate()` call
3. **Write to Intermediate Storage**: `temp/raster_etl/{job_id}/tiles/{tile_id}_cog.tif`

**Note**: No overviews per tile (creates in mosaic stage for efficiency)

**Success Result** (per tile):
```python
{
    "success": True,
    "result": {
        "tile_id": "tile_0_0",
        "source_blob": "bronze/2024/huge_raster.tif",
        "tile_cog_blob": "temp/raster_etl/abc123/tiles/tile_0_0_cog.tif",
        "tile_container": "rmhazuregeotemp",
        "bounds_4326": [-120.5, 39.0, -120.0, 39.5],
        "size_mb": 48.2,
        "processing_time_seconds": 3.2
    }
}
```

---

### Stage 4: Mosaic Tiles (Future Implementation)

**Task Type**: `mosaic_tiles`
**Input**: All tile COGs from Stage 3
**Output**: Single mosaicked COG in silver container

**Mosaicking**:
1. Collect all tile COG paths from Stage 3 results
2. Use GDAL VRT to create virtual mosaic
3. Convert VRT to final COG with overviews (rio-cogeo)
4. Write to silver container
5. Cleanup intermediate tiles

**Parameters**:
- `tile_cog_blobs`: List of all tile COG paths (from Stage 3)
- `output_blob`: `silver/{year}/{original_name}_cog.tif`
- `compression`: "deflate" (final COG compression)

**Success Result**:
```python
{
    "success": True,
    "result": {
        "cog_blob": "silver/2024/huge_raster_cog.tif",
        "cog_container": "rmhazuregeosilver",
        "tiles_processed": 25,
        "source_crs": "EPSG:32611",
        "target_crs": "EPSG:4326",
        "bounds_4326": [-120.5, 38.5, -119.5, 39.5],
        "size_mb": 1205.3,
        "compression": "deflate",
        "tile_size": [512, 512],
        "overview_levels": [2, 4, 8, 16],
        "total_processing_time_seconds": 45.7
    }
}
```

---

## Configuration Requirements

### Existing Config (from config.py)

```python
# Bronze Container (input)
config.bronze_container_name = "rmhazuregeobronze"

# Silver Container (output COGs)
config.silver_container_name = "rmhazuregeosilver"

# Intermediate Storage (reuses vector pipeline setting)
config.vector_pickle_container = "rmhazuregeotemp"
```

### New Config (to be added to config.py)

```python
# ========================================================================
# Raster Pipeline Configuration
# ========================================================================

raster_intermediate_prefix: str = Field(
    default="temp/raster_etl",
    description="Blob path prefix for raster ETL intermediate files (large file tiles)",
    examples=["temp/raster_etl", "intermediate/raster"]
)

raster_size_threshold_mb: int = Field(
    default=1000,  # 1 GB
    description="File size threshold (MB) for pipeline selection (small vs large file)",
)

raster_tile_size_pixels: int = Field(
    default=5000,
    description="Tile size in pixels for large file processing",
)

raster_tile_overlap_pixels: int = Field(
    default=100,
    description="Tile overlap in pixels for seamless mosaicking",
)

raster_cog_compression: str = Field(
    default="deflate",
    description="Default compression algorithm for COG creation",
    examples=["deflate", "lzw", "zstd", "jpeg", "webp", "lerc_deflate"]
)

raster_cog_jpeg_quality: int = Field(
    default=85,
    description="JPEG quality for lossy compression (1-100, only applies to jpeg/webp)",
)

raster_cog_tile_size: int = Field(
    default=512,
    description="Internal tile size for COG (pixels)",
)

raster_overview_resampling: str = Field(
    default="cubic",
    description="Resampling method for COG overview generation",
    examples=["cubic", "bilinear", "average", "mode", "nearest"]
)

raster_reproject_resampling: str = Field(
    default="cubic",
    description="Resampling method for reprojection",
    examples=["cubic", "bilinear", "lanczos", "nearest"]
)

raster_strict_validation: bool = Field(
    default=False,
    description="Fail on validation warnings (inefficient bit-depth, etc)",
)
```

---

## Job Workflows

### Small File Workflow

**Job Type**: `process_raster`
**File**: `jobs/process_raster.py`

```python
class ProcessRasterWorkflow:
    job_type: str = "process_raster"
    description: str = "Process raster to COG (files <= 1GB)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "description": "Validate raster, check CRS, analyze bit-depth efficiency",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "create_cog",
            "task_type": "create_cog",
            "description": "Reproject to EPSG:4326 and create COG (single operation)",
            "parallelism": "single"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "container": {"type": "str", "required": True, "default": "rmhazuregeobronze"},
        "input_crs": {"type": "str", "required": False, "default": None},
        "raster_type": {"type": "str", "required": False, "default": "auto",
                        "allowed": ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]},
        "compression": {"type": "str", "required": False, "default": None},  # Auto-selected from raster type if None
        "jpeg_quality": {"type": "int", "required": False, "default": 85},
        "overview_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected from raster type
        "reproject_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected from raster type
        "strict_mode": {"type": "bool", "required": False, "default": False},
    }
```

---

### Large File Workflow

**Job Type**: `process_raster_large`
**File**: `jobs/process_raster_large.py`

```python
class ProcessRasterLargeWorkflow:
    job_type: str = "process_raster_large"
    description: str = "Process large raster to COG (files > 1GB)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "description": "Validate raster, check CRS, analyze bit-depth efficiency",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "tiling_strategy",
            "task_type": "create_tiling_strategy",
            "description": "Create tiling strategy for parallel processing",
            "parallelism": "single"
        },
        {
            "number": 3,
            "name": "process_tiles",
            "task_type": "process_raster_tile",
            "description": "Reproject and create COG for each tile (parallel)",
            "parallelism": "fan_out"  # Creates N tasks from Stage 2 tile list
        },
        {
            "number": 4,
            "name": "mosaic",
            "task_type": "mosaic_tiles",
            "description": "Mosaic tiles into final COG with overviews",
            "parallelism": "single"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "container": {"type": "str", "required": True, "default": "rmhazuregeobronze"},
        "input_crs": {"type": "str", "required": False, "default": None},
        "compression": {"type": "str", "required": False, "default": "deflate"},
        "tile_size": {"type": "int", "required": False, "default": 5000},
        "tile_overlap": {"type": "int", "required": False, "default": 100},
        "overview_resampling": {"type": "str", "required": False, "default": "average"},
        "reproject_resampling": {"type": "str", "required": False, "default": "bilinear"},
        "strict_mode": {"type": "bool", "required": False, "default": False},
    }
```

---

## Service Layer (DRY - Reusable Across Both Pipelines)

### RasterValidationService

**File**: `services/raster_validation.py`

**Methods**:
- `validate_raster(blob_url, input_crs=None, strict_mode=False) -> dict`
  - Validates raster (CRS, integrity, bit-depth)
  - Handles missing CRS with three-tier approach
  - Analyzes bit-depth efficiency
  - Used by BOTH small and large file pipelines (Stage 1)

**Key Features**:
- Three-tier CRS handling (file metadata → user override → failure)
- Bit-depth efficiency analysis with savings calculations
- Strict mode for failing on warnings
- Comprehensive validation results with actionable warnings

---

### RasterCOGService

**File**: `services/raster_cog.py`

**Methods**:
- `create_cog(blob_url, output_path, source_crs, target_crs="EPSG:4326", compression="deflate", ...) -> dict`
  - Single operation: reproject + create COG
  - Uses `rio-cogeo.cog_translate()`
  - Handles all compression types and resampling methods
  - Used by small file pipeline (Stage 2) and large file pipeline tile processing (Stage 3)

**Key Features**:
- Single-pass processing (reproject + COG)
- Automatic overview generation
- Configurable compression and resampling
- Skips reprojection if already in target CRS

---

### RasterTilingService

**File**: `services/raster_tiling.py`

**Methods**:
- `create_tiling_strategy(blob_url, tile_size=5000, overlap=100) -> dict`
  - Generates tile grid for large files
  - Calculates optimal tile count
  - Creates tile manifest with windows and bounds
  - Used ONLY by large file pipeline (Stage 2)

- `mosaic_tiles(tile_cog_blobs, output_blob, compression="deflate") -> dict`
  - Mosaics tiles into final COG
  - Creates VRT, then converts to COG with overviews
  - Cleanup intermediate tiles
  - Used ONLY by large file pipeline (Stage 4)

---

## Storage Layout

```
rmhazuregeobronze/                    # Bronze: Raw input rasters
  └── 2024/
      ├── raster.tif                  # Small file (285 MB)
      └── huge_raster.tif             # Large file (10.8 GB)

rmhazuregeotemp/                      # Intermediate storage (large files only)
  └── temp/raster_etl/
      └── abc123/                     # Large file job
          └── tiles/
              ├── tile_0_0_cog.tif   # Tile COGs
              ├── tile_0_1_cog.tif
              └── ...

rmhazuregeosilver/                    # Silver: Final COG outputs
  └── 2024/
      ├── raster_cog.tif             # Small file output
      └── huge_raster_cog.tif        # Large file output
```

**Key Points**:
- **Small files**: Bronze → Silver directly (no intermediate storage)
- **Large files**: Bronze → Intermediate tiles → Silver mosaic
- **Cleanup**: Intermediate tiles deleted after successful mosaic

---

## Implementation Phases

### Phase 1: Small File Pipeline (Current Focus)

**Priority**: Implement first, test thoroughly

**Tasks**:
1. ✅ Design document (this file)
2. ✅ Research rio-cogeo parameters and best practices
3. ⏳ Add raster config to `config.py`
4. ⏳ Create `services/raster_validation.py` (with CRS and bit-depth validation)
5. ⏳ Create `services/raster_cog.py` (rio-cogeo wrapper)
6. ⏳ Create `jobs/process_raster.py` (2-stage workflow)
7. ⏳ Register handlers in `services/__init__.py`
8. ⏳ Register workflow in `jobs/__init__.py`
9. ⏳ Test with small test rasters (various CRS, bit-depths)
10. ⏳ Deploy and validate in Azure

**Test Cases**:
- ✅ Valid raster with CRS in metadata (EPSG:32611)
- ✅ Valid raster with missing CRS + `input_crs` parameter
- ✅ Valid raster already in EPSG:4326 (skip reprojection)
- ✅ Invalid raster (corrupted file)
- ✅ Valid raster with missing CRS + no `input_crs` parameter (expect failure)
- ✅ Float64 land cover raster (inefficient bit-depth warning)

---

### Phase 2: Large File Pipeline (Future)

**Priority**: After Phase 1 is stable and tested

**Tasks**:
1. ⏳ Create `services/raster_tiling.py`
2. ⏳ Add tile processing handler (reuses validation/COG services)
3. ⏳ Add mosaic handler
4. ⏳ Create `jobs/process_raster_large.py` (4-stage workflow)
5. ⏳ Register handlers in `services/__init__.py`
6. ⏳ Register workflow in `jobs/__init__.py`
7. ⏳ Test with large test rasters (2-10 GB)
8. ⏳ Deploy and validate in Azure

**Test Cases**:
- ⏳ Large raster (2 GB) → tiling → parallel processing → mosaic
- ⏳ Large raster (10 GB) → tiling → parallel processing → mosaic
- ⏳ Large raster with odd dimensions (not evenly divisible by tile size)

---

## Error Handling

### CRS Missing Error

**Scenario**: Raster has no CRS in metadata, no `input_crs` parameter provided

**Response**:
```python
{
    "success": False,
    "error": "CRS_MISSING",
    "message": "Raster has no CRS in metadata and no input_crs parameter provided. "
               "Provide input_crs parameter (e.g., 'EPSG:32611') to proceed.",
    "suggestion": "Resubmit job with 'input_crs' parameter",
    "example": {
        "blob_name": "2024/raster.tif",
        "container": "rmhazuregeobronze",
        "input_crs": "EPSG:32611"
    }
}
```

**Job Status**: `FAILED` (not retryable - user must provide CRS)

---

### Reprojection + COG Creation Failure

**Scenario**: rio-cogeo fails during processing

**Response**:
```python
{
    "success": False,
    "error": "COG_CREATION_FAILED",
    "message": "Failed to create COG: Tolerance condition error",
    "exception": "rasterio.errors.CRSError: Tolerance condition error",
    "source_crs": "EPSG:32611",
    "target_crs": "EPSG:4326",
    "stack_trace": "..."
}
```

**Job Status**: `FAILED` (potentially retryable if transient)

---

### Inefficient Bit-Depth (Warning Only)

**Scenario**: Float64 raster with 5 categorical values

**Response**:
```python
{
    "success": True,  # Continues processing
    "result": {
        "valid": True,
        "warnings": [
            {
                "type": "INEFFICIENT_BIT_DEPTH",
                "severity": "HIGH",
                "current_dtype": "float64",
                "recommended_dtype": "uint8",
                "potential_savings_percent": 87.5,
                "message": "Raster uses float64 for categorical data with 5 classes. "
                           "Converting to uint8 would reduce size by 87.5%. "
                           "Consider optimizing source data before reprocessing."
            }
        ]
    }
}
```

**Job Status**: `PROCESSING` (continues with warning logged)

---

## Testing Strategy

### Phase 1 Testing (Small Files)

**Test Files**:
- `test_valid_utm11n.tif` (50 MB, EPSG:32611, uint8)
- `test_valid_4326.tif` (50 MB, EPSG:4326, uint8)
- `test_no_crs.tif` (50 MB, no CRS metadata, uint8)
- `test_corrupted.tif` (corrupted file)
- `test_landcover_float64.tif` (100 MB, 5 classes, float64 - inefficient)
- `test_dem_float32.tif` (80 MB, elevation, float32 - efficient)

**Test Scenarios**:
1. ✅ Valid raster with CRS → Should create COG with reprojection
2. ✅ Valid raster already in 4326 → Should create COG without reprojection
3. ✅ Valid raster no CRS + `input_crs` param → Should create COG with reprojection
4. ✅ Valid raster no CRS, no param → Should fail with CRS_MISSING
5. ✅ Corrupted raster → Should fail validation
6. ✅ Float64 categorical → Should warn but proceed
7. ✅ Test all compression types (deflate, zstd, lzw, jpeg)
8. ✅ Test all resampling methods (cubic, bilinear, nearest, mode)

---

### Phase 2 Testing (Large Files)

**Test Files**:
- `test_large_2gb.tif` (2 GB, EPSG:32611)
- `test_large_10gb.tif` (10 GB, EPSG:32611)

**Test Scenarios**:
1. ⏳ Large raster (2 GB) → Should create 4 tiles, process in parallel, mosaic
2. ⏳ Large raster (10 GB) → Should create 25 tiles, process in parallel, mosaic
3. ⏳ Verify tile overlap prevents seams
4. ⏳ Verify final mosaic has correct overviews
5. ⏳ Verify intermediate tiles are cleaned up

---

## Questions Resolved

### Q: Should Validate be its own task?
**A**: ✅ YES - Fail fast before expensive processing

### Q: Can reprojection and COG creation happen in one step?
**A**: ✅ YES - rio-cogeo's `cog_translate()` does both! (3 stages → 2 stages)

### Q: Should intermediate storage use the same container as vector pipeline?
**A**: ✅ YES - Reuses `config.vector_pickle_container` (large files only)

### Q: Should services be reusable across both pipelines?
**A**: ✅ YES - DRY principle, validation/COG services used by both

### Q: Should we implement small file pipeline first?
**A**: ✅ YES - Phased approach, large file pipeline after small is stable

### Q: How to handle missing CRS?
**A**: ✅ Three-tier approach: file metadata → user override → fail with clear message

### Q: How to handle inefficient bit-depth (float64 with 5 classes)?
**A**: ✅ Detect, warn, continue processing (default) OR fail in strict mode

### Q: What's the best compression?
**A**: ✅ DEFLATE (universal, lossless, 65% reduction) or ZSTD (better, requires GDAL 3.1+)

### Q: What about JPEG for imagery?
**A**: ✅ Use for visual RGB imagery only (97% reduction!), quality 85, never for scientific data

---

## Implementation TODO - Phase 1 (Small Files ≤ 1GB)

**Status**: Design Complete - Ready for Implementation
**Target**: 2-stage pipeline (Validate → Reproject+COG)
**Priority**: HIGH - Foundation for all raster processing

### Task Breakdown

#### 1. Configuration (config.py)
- [ ] Add `raster_intermediate_prefix` field (default: "temp/raster_etl")
- [ ] Add `raster_size_threshold_mb` field (default: 1000)
- [ ] Add `raster_cog_compression` field (default: "deflate")
- [ ] Add `raster_cog_jpeg_quality` field (default: 85)
- [ ] Add `raster_cog_tile_size` field (default: 512)
- [ ] Add `raster_overview_resampling` field (default: "cubic")
- [ ] Add `raster_reproject_resampling` field (default: "cubic")
- [ ] Add `raster_strict_validation` field (default: False)

#### 2. Raster Type Enum (new file: `core/enums.py` or add to existing)
- [ ] Create `RasterType` enum with values: rgb, rgba, dem, categorical, multispectral, nir, unknown
- [ ] Add docstrings for each type with band count and dtype expectations

#### 3. Validation Service (`services/raster_validation.py`)
- [ ] Create `validate_raster()` handler function
- [ ] Implement CRS validation (three-tier: file metadata → user override → fail)
- [ ] Implement bounds sanity checks (EPSG:4326 range, UTM range)
- [ ] Implement bit-depth efficiency check
  - [ ] Flag ALL 64-bit types as CRITICAL
  - [ ] Detect categorical data in float types (HIGH warning)
  - [ ] Detect integer data in float types (MEDIUM warning)
- [ ] Implement raster type detection
  - [ ] RGB detection (3-band uint8/uint16)
  - [ ] RGBA detection (4-band uint8/uint16, check alpha)
  - [ ] DEM detection (single-band float/int, smooth gradients)
  - [ ] Categorical detection (single-band, <256 discrete values)
  - [ ] Multispectral detection (5+ bands)
- [ ] Implement raster type mismatch validation (user_type vs detected_type)
- [ ] Implement `_skip_validation` override for testing
- [ ] Add comprehensive logging (CRS, bounds, dtype, raster type)
- [ ] Return validation result dict with all metadata

**Dependencies**: rasterio, numpy, config

#### 4. COG Creation Service (`services/raster_cog.py`)
- [ ] Create `create_cog()` handler function
- [ ] Integrate rio-cogeo `cog_translate()`
- [ ] Implement single-pass reproject + COG creation
- [ ] Auto-select COG settings based on raster type
  - [ ] RGB: JPEG compression, cubic resampling
  - [ ] RGBA: WebP compression, cubic resampling
  - [ ] DEM: LERC+DEFLATE, average overviews, bilinear reproject
  - [ ] Categorical: DEFLATE, mode overviews, nearest reproject
  - [ ] Multispectral: DEFLATE, average overviews, bilinear reproject
- [ ] Allow user override of compression/resampling settings
- [ ] Handle reprojection skip if already in target CRS
- [ ] Download from bronze blob to local temp
- [ ] Create COG with rio-cogeo
- [ ] Upload to silver blob
- [ ] Cleanup local temp files
- [ ] Return result dict with metadata (size, compression, overviews, etc.)

**Dependencies**: rio-cogeo, rasterio, azure blob storage, config

#### 5. Job Workflow (`jobs/process_raster.py`)
- [ ] Create `ProcessRasterWorkflow` class
- [ ] Define 2 stages:
  - [ ] Stage 1: validate_raster (single task)
  - [ ] Stage 2: create_cog (single task)
- [ ] Define parameters schema with all validation options
- [ ] Implement stage result passing (Stage 1 metadata → Stage 2)
- [ ] Implement `aggregate_job_results()` method

#### 6. Handler Registration
- [ ] Register `validate_raster` in `services/__init__.py` ALL_HANDLERS
- [ ] Register `create_cog` in `services/__init__.py` ALL_HANDLERS
- [ ] Register `process_raster` workflow in `jobs/__init__.py` ALL_JOBS

#### 7. Testing (Local)
- [ ] Create test raster files:
  - [ ] `test_rgb_utm.tif` (50 MB, 3-band uint8, EPSG:32611)
  - [ ] `test_rgb_4326.tif` (50 MB, 3-band uint8, EPSG:4326)
  - [ ] `test_rgba_drone.tif` (80 MB, 4-band uint8, EPSG:32611)
  - [ ] `test_dem_float32.tif` (60 MB, 1-band float32, EPSG:32611)
  - [ ] `test_landcover_float64.tif` (100 MB, 1-band float64, 5 classes - BAD)
  - [ ] `test_no_crs.tif` (50 MB, no CRS metadata)
  - [ ] `test_sentinel2.tif` (200 MB, 12-band uint16 - multispectral)
- [ ] Test validation stage:
  - [ ] Valid RGB with CRS → Should pass
  - [ ] Valid RGB already 4326 → Should pass, note skip reprojection
  - [ ] Valid RGBA (drone) → Should pass, detect RGBA type
  - [ ] Valid DEM → Should pass, detect DEM type
  - [ ] Float64 categorical → Should pass with CRITICAL warning
  - [ ] No CRS, no input_crs → Should FAIL with CRS_MISSING
  - [ ] No CRS, with input_crs → Should pass
  - [ ] User raster_type="rgb" but file is 12-band → Should FAIL with RASTER_TYPE_MISMATCH
- [ ] Test COG creation stage:
  - [ ] RGB with reprojection → JPEG COG in silver
  - [ ] RGB already 4326 → JPEG COG in silver (no reproject)
  - [ ] RGBA (drone) → WebP COG in silver
  - [ ] DEM → LERC+DEFLATE COG in silver
  - [ ] Categorical → DEFLATE COG with mode overviews
- [ ] Test end-to-end job:
  - [ ] Submit job → Should create job record
  - [ ] Stage 1 completes → Should have validation metadata
  - [ ] Stage 2 completes → Should have COG in silver
  - [ ] Job completes → Should have aggregated results

#### 8. Deployment to Azure
- [ ] Update `requirements.txt` with rio-cogeo dependency
- [ ] Deploy to `rmhgeoapibeta`
- [ ] Test health endpoint
- [ ] Redeploy database schema (if needed)
- [ ] Upload test rasters to bronze container
- [ ] Run end-to-end tests in Azure:
  - [ ] Submit RGB test job
  - [ ] Submit RGBA test job (drone)
  - [ ] Submit DEM test job
  - [ ] Submit float64 categorical (expect CRITICAL warning)
  - [ ] Submit job with wrong raster_type (expect FAIL)
- [ ] Verify COGs in silver container
- [ ] Check Application Insights logs
- [ ] Monitor queue processing

#### 9. Documentation
- [ ] Update `docs_claude/CLAUDE_CONTEXT.md` with raster pipeline overview
- [ ] Update `docs_claude/FILE_CATALOG.md` with new service files
- [ ] Update `docs_claude/TODO_ACTIVE.md` with Phase 2 tasks (large files)
- [ ] Update `docs_claude/HISTORY.md` with Phase 1 completion

### Estimated Effort
- **Configuration**: 30 minutes
- **Validation Service**: 4-6 hours (complex logic)
- **COG Service**: 3-4 hours (rio-cogeo integration)
- **Job Workflow**: 1 hour
- **Testing**: 3-4 hours
- **Deployment & Validation**: 2 hours
- **Total**: ~15-20 hours

### Dependencies
- `rio-cogeo` - COG creation library
- `rasterio` - Raster I/O (already installed)
- `numpy` - Array operations (already installed)
- Azure blob storage (already configured)

### Success Criteria
- [ ] All validation checks working (CRS, bit-depth, raster type)
- [ ] Type mismatch errors fail with detailed messages
- [ ] Auto-detection of RGB, RGBA, DEM, categorical types
- [ ] Optimal COG settings selected per type
- [ ] Single-pass reproject + COG creation
- [ ] COGs in silver container with correct compression
- [ ] 64-bit data flagged as CRITICAL
- [ ] End-to-end job processing (<5 minutes for small files)
- [ ] Clean error messages for garbage data
- [ ] `_skip_validation` works for testing

---

## Next Steps

1. ✅ Complete design document with rio-cogeo research
2. ✅ Add raster type detection and validation strategy
3. ✅ Add `_skip_validation` override for testing
4. ⏳ **BEGIN IMPLEMENTATION** - Start with configuration and validation service
5. ⏳ Test locally with sample rasters
6. ⏳ Deploy to Azure and validate
7. ⏳ Begin Phase 2 implementation (large files, 4-stage pipeline) after Phase 1 is stable
