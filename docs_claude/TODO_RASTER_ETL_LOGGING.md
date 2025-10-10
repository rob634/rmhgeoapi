# TODO: Raster ETL Granular Logging Implementation

**Date**: 10 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Priority**: HIGH (blocking COG creation debugging)

---

## Executive Summary

The `create_cog` handler is failing silently with `COG_CREATION_FAILED` but provides no diagnostic information. It lacks the granular STEP-by-STEP logging pattern that `validate_raster` uses successfully.

**Current State:**
- ❌ `create_cog`: Only has `print()` statements, no structured logger, minimal error context
- ✅ `validate_raster`: Has 9-step granular logging with LoggerFactory, detailed error tracking

**Goal:** Bring `create_cog` up to same logging standard as `validate_raster`.

---

## Pattern to Follow: validate_raster (Reference Implementation)

### Key Features of Good Logging (from raster_validation.py):

1. **Logger Initialization (STEP 0)**
```python
# STEP 0: Initialize logger
logger = None
try:
    from util_logger import LoggerFactory, ComponentType
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "validate_raster")
    logger.info("✅ STEP 0: Logger initialized successfully")
except Exception as e:
    return {
        "success": False,
        "error": "LOGGER_INIT_FAILED",
        "message": f"Failed to initialize logger: {e}"
    }
```

2. **Granular Step Wrapping**
```python
# STEP 3: Open raster file
try:
    logger.info(f"🔄 STEP 3: Opening raster file via SAS URL...")
    src = rasterio.open(blob_url)
    logger.info(f"✅ STEP 3: File opened successfully - {src.count} bands, {src.shape}")
except Exception as e:
    logger.error(f"❌ STEP 3 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "FILE_OPEN_FAILED",
        "message": f"Failed to open raster: {e}",
        "traceback": traceback.format_exc()
    }
```

3. **Error Codes Per Step**
- `LOGGER_INIT_FAILED`
- `PARAMETER_ERROR`
- `DEPENDENCY_LOAD_FAILED`
- `FILE_OPEN_FAILED`
- `CRS_DETECTION_FAILED`
- etc.

4. **Traceback Inclusion**
```python
"traceback": traceback.format_exc()
```

5. **Progress Logging**
```python
logger.info(f"🔄 STEP X: Starting operation...")
# ... operation ...
logger.info(f"✅ STEP X: Operation completed successfully")
```

---

## Current Issues in create_cog (services/raster_cog.py)

### ❌ **Issue 1: No LoggerFactory**
```python
# Current (BAD):
print(f"🏗️ COG CREATION: Starting COG creation", file=sys.stderr, flush=True)

# Should be (GOOD):
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_cog")
logger.info("✅ STEP 0: Logger initialized successfully")
```

### ❌ **Issue 2: Generic Exception Handling**
```python
# Current (BAD) - Line 286:
except Exception as e:
    import traceback
    print(f"❌ COG CREATION: Failed - {e}", file=sys.stderr, flush=True)
    print(traceback.format_exc(), file=sys.stderr, flush=True)
    return {
        "success": False,
        "error": "COG_CREATION_FAILED",  # Too generic!
        "message": str(e)
    }
```

**Problems:**
- Single catch-all exception at end
- No indication of WHERE in the process it failed
- Error code `COG_CREATION_FAILED` doesn't tell us if it was:
  - Download failed?
  - Import failed?
  - Reprojection failed?
  - Upload failed?
  - Temporary file I/O failed?

### ❌ **Issue 3: No Step Numbers**

Current flow has ~7 major operations but no STEP markers:
1. Parameter extraction
2. Lazy imports
3. Download raster from blob
4. Determine reprojection needs
5. Create COG (cog_translate)
6. Upload to silver container
7. Cleanup temp files

**Should have:** `STEP 0` through `STEP 7` with individual try-except blocks

### ❌ **Issue 4: No Intermediate Success Logging**

```python
# Current (BAD):
rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()
# No log that this succeeded!

# Should be (GOOD):
try:
    logger.info("🔄 STEP 2: Lazy loading rio-cogeo dependencies...")
    rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()
    logger.info("✅ STEP 2: Dependencies loaded successfully")
except ImportError as e:
    logger.error(f"❌ STEP 2 FAILED: {e}\n{traceback.format_exc()}")
    return {"success": False, "error": "DEPENDENCY_LOAD_FAILED", "traceback": traceback.format_exc()}
```

---

## Implementation Plan

### Phase 1: Add Logger Initialization (STEP 0)

**Location**: Line 85 (before parameter extraction)

**Code to Add**:
```python
# STEP 0: Initialize logger
logger = None
try:
    print(f"📦 STEP 0: Importing logger...", file=sys.stderr, flush=True)
    from util_logger import LoggerFactory, ComponentType
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "create_cog")
    logger.info("✅ STEP 0: Logger initialized successfully")
    print(f"✅ STEP 0: Logger initialized", file=sys.stderr, flush=True)
except Exception as e:
    print(f"❌ STEP 0 FAILED: Cannot initialize logger: {e}", file=sys.stderr, flush=True)
    return {
        "success": False,
        "error": "LOGGER_INIT_FAILED",
        "message": f"Failed to initialize logger: {e}"
    }
```

### Phase 2: Wrap Parameter Extraction (STEP 1)

**Location**: Lines 87-100

**Code to Add**:
```python
# STEP 1: Extract and validate parameters
try:
    logger.info("🔄 STEP 1: Extracting parameters...")

    blob_url = params.get('blob_url')
    if not blob_url:
        raise ValueError("blob_url is required")

    source_crs = params.get('source_crs')
    if not source_crs:
        raise ValueError("source_crs is required (from Stage 1 validation)")

    target_crs = params.get('target_crs', 'EPSG:4326')
    raster_type = params.get('raster_type', {}).get('detected_type', 'unknown')
    optimal_settings = params.get('raster_type', {}).get('optimal_cog_settings', {})

    compression = params.get('compression') or optimal_settings.get('compression', 'deflate')
    jpeg_quality = params.get('jpeg_quality', 85)
    overview_resampling = params.get('overview_resampling') or optimal_settings.get('overview_resampling', 'cubic')
    reproject_resampling = params.get('reproject_resampling') or optimal_settings.get('reproject_resampling', 'cubic')
    output_blob_name = params.get('output_blob_name')

    logger.info(f"✅ STEP 1: Parameters extracted - raster_type={raster_type}, compression={compression}")

except Exception as e:
    logger.error(f"❌ STEP 1 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "PARAMETER_ERROR",
        "message": f"Invalid parameters: {e}",
        "traceback": traceback.format_exc()
    }
```

### Phase 3: Wrap Lazy Imports (STEP 2)

**Location**: After parameter extraction

**Code to Add**:
```python
# STEP 2: Lazy import dependencies
try:
    logger.info("🔄 STEP 2: Lazy loading rio-cogeo dependencies...")
    rasterio, Resampling, cog_translate, cog_profiles = _lazy_imports()
    logger.info("✅ STEP 2: Dependencies loaded successfully")
except ImportError as e:
    logger.error(f"❌ STEP 2 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "DEPENDENCY_LOAD_FAILED",
        "message": f"Failed to load rasterio/rio-cogeo: {e}",
        "traceback": traceback.format_exc()
    }
```

### Phase 4: Wrap Download (STEP 3)

**Location**: Around blob download logic (line ~113)

**Code to Add**:
```python
# STEP 3: Download raster from bronze container
try:
    logger.info(f"🔄 STEP 3: Downloading raster from bronze via SAS URL...")
    logger.info(f"  URL: {blob_url[:100]}...")

    import requests
    response = requests.get(blob_url, stream=True)
    response.raise_for_status()

    with open(local_input, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    file_size_mb = os.path.getsize(local_input) / (1024 * 1024)
    logger.info(f"✅ STEP 3: Downloaded {file_size_mb:.2f} MB successfully")

except Exception as e:
    logger.error(f"❌ STEP 3 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "DOWNLOAD_FAILED",
        "message": f"Failed to download raster from blob: {e}",
        "traceback": traceback.format_exc()
    }
```

### Phase 5: Wrap Reprojection Check (STEP 4)

**Location**: Around CRS comparison logic

**Code to Add**:
```python
# STEP 4: Determine if reprojection is needed
try:
    logger.info("🔄 STEP 4: Checking if reprojection is needed...")

    with rasterio.open(local_input) as src:
        source_crs_obj = src.crs or source_crs
        target_crs_obj = rasterio.crs.CRS.from_string(target_crs)
        needs_reprojection = source_crs_obj != target_crs_obj

    logger.info(f"✅ STEP 4: Reprojection needed: {needs_reprojection}")
    logger.info(f"  Source CRS: {source_crs_obj}")
    logger.info(f"  Target CRS: {target_crs_obj}")

except Exception as e:
    logger.error(f"❌ STEP 4 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "CRS_CHECK_FAILED",
        "message": f"Failed to check CRS: {e}",
        "traceback": traceback.format_exc()
    }
```

### Phase 6: Wrap COG Creation (STEP 5) - MOST CRITICAL

**Location**: Around cog_translate call (line ~165)

**Code to Add**:
```python
# STEP 5: Create COG with optional reprojection
try:
    logger.info("🔄 STEP 5: Creating Cloud Optimized GeoTIFF...")
    logger.info(f"  Compression: {compression}")
    logger.info(f"  Overview resampling: {overview_resampling}")
    logger.info(f"  Reproject resampling: {reproject_resampling}")

    start_time = datetime.now(timezone.utc)

    # ... cog_translate call ...

    elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
    output_size_mb = os.path.getsize(local_output) / (1024 * 1024)

    logger.info(f"✅ STEP 5: COG created successfully in {elapsed_time:.2f}s")
    logger.info(f"  Output size: {output_size_mb:.2f} MB")
    logger.info(f"  Overview levels: {len(overviews)}")

except Exception as e:
    logger.error(f"❌ STEP 5 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "COG_TRANSLATE_FAILED",  # More specific!
        "message": f"Failed to create COG: {e}",
        "traceback": traceback.format_exc(),
        "params": {
            "compression": compression,
            "source_crs": str(source_crs),
            "target_crs": str(target_crs)
        }
    }
```

### Phase 7: Wrap Upload (STEP 6)

**Location**: Around blob upload (line ~220)

**Code to Add**:
```python
# STEP 6: Upload COG to silver container
try:
    logger.info(f"🔄 STEP 6: Uploading COG to silver container...")
    logger.info(f"  Destination: {output_blob_name}")

    from infrastructure import BlobRepository
    blob_infra = BlobRepository()

    from config import get_config
    config_obj = get_config()
    silver_container = config_obj.silver_container_name

    logger.info(f"  Silver container: {silver_container}")

    with open(local_output, 'rb') as f:
        blob_data = f.read()
        blob_infra.upload_blob(
            container_name=silver_container,
            blob_name=output_blob_name,
            data=blob_data
        )

    logger.info(f"✅ STEP 6: Uploaded {len(blob_data)/(1024*1024):.2f} MB to silver")

except Exception as e:
    logger.error(f"❌ STEP 6 FAILED: {e}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": "UPLOAD_FAILED",
        "message": f"Failed to upload COG to silver container: {e}",
        "traceback": traceback.format_exc()
    }
```

### Phase 8: Wrap Cleanup (STEP 7)

**Location**: Temp file cleanup (line ~286)

**Code to Add**:
```python
# STEP 7: Cleanup temporary files
try:
    logger.info("🔄 STEP 7: Cleaning up temporary files...")

    if os.path.exists(local_input):
        os.remove(local_input)
        logger.info(f"  Removed temp input: {local_input}")

    if os.path.exists(local_output):
        os.remove(local_output)
        logger.info(f"  Removed temp output: {local_output}")

    logger.info("✅ STEP 7: Cleanup completed successfully")

except Exception as e:
    # Don't fail the whole operation for cleanup issues
    logger.warning(f"⚠️ STEP 7: Failed to cleanup temp files: {e}")
    # Continue to success return
```

---

## Error Code Taxonomy

Replace generic `COG_CREATION_FAILED` with specific codes:

| Step | Error Code | Meaning |
|------|-----------|---------|
| 0 | `LOGGER_INIT_FAILED` | LoggerFactory import/init failed |
| 1 | `PARAMETER_ERROR` | Missing or invalid parameters |
| 2 | `DEPENDENCY_LOAD_FAILED` | rasterio/rio-cogeo import failed |
| 3 | `DOWNLOAD_FAILED` | Failed to download from bronze blob |
| 4 | `CRS_CHECK_FAILED` | Failed to read/compare CRS |
| 5 | `COG_TRANSLATE_FAILED` | cog_translate() operation failed |
| 6 | `UPLOAD_FAILED` | Failed to upload to silver blob |
| 7 | `CLEANUP_WARNING` | Temp file cleanup failed (non-critical) |

---

## Success Criteria

After implementation, when COG creation fails, logs should show:

```
✅ STEP 0: Logger initialized successfully
✅ STEP 1: Parameters extracted - raster_type=rgb, compression=jpeg
✅ STEP 2: Dependencies loaded successfully
✅ STEP 3: Downloaded 65.32 MB successfully
✅ STEP 4: Reprojection needed: True
  Source CRS: EPSG:3857
  Target CRS: EPSG:4326
❌ STEP 5 FAILED: rasterio.errors.CRSError: Invalid CRS: EPSG:3857
[Full traceback...]

Error returned:
{
  "success": false,
  "error": "COG_TRANSLATE_FAILED",
  "message": "Failed to create COG: Invalid CRS: EPSG:3857",
  "traceback": "...",
  "params": {
    "compression": "jpeg",
    "source_crs": "EPSG:3857",
    "target_crs": "EPSG:4326"
  }
}
```

**This tells us EXACTLY where and why it failed!**

---

## Benefits

1. **Debugging**: Know exactly which step failed
2. **Performance**: See timing for each step
3. **Monitoring**: Application Insights gets structured logs
4. **User Feedback**: Can provide specific error messages
5. **Maintenance**: Future developers understand flow

---

## Files to Modify

1. **services/raster_cog.py** (293 lines)
   - Add STEP 0-7 logging
   - Add LoggerFactory initialization
   - Add traceback to all error returns
   - Add step-specific error codes

2. **Test After Changes**:
```bash
# Submit process_raster job
curl -X POST .../api/jobs/submit/process_raster \
  -d '{"blob_name": "test/dctest3_R1C2_regular.tif", "container_name": "rmhazuregeobronze"}'

# Check Application Insights for STEP logs
# Should see exactly which STEP failed
```

---

## Estimated Effort

- **Time**: 2-3 hours
- **Complexity**: Medium (copy pattern from validate_raster)
- **Risk**: Low (only adding logging, not changing logic)
- **Testing**: High priority (will immediately reveal COG failure cause)

---

## Priority Justification

**CRITICAL** because:
1. COG creation is completely broken (100% failure rate)
2. No diagnostic information available
3. Blocks end-to-end raster ETL pipeline
4. Pattern already proven successful in validate_raster
5. Will take <3 hours to implement
6. Will immediately reveal root cause of failures

**Recommendation**: Implement this before ANY other raster ETL work.
