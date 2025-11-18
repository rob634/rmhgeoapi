# TiTiler COG Validation - Stage 4 Implementation Task

**Date**: November 10, 2025
**Status**: 🔧 Ready for Implementation
**Priority**: High - Prevents unreadable COGs from being cataloged

---

## Problem Statement

COGs created by the pipeline may not be readable by TiTiler (GDAL /vsiaz/), causing tile generation failures. Current validation only checks CRS, bit-depth, and raster type - not TiTiler-specific requirements.

**Example Issue**: `dctest3_R1C2_cog_cog_analysis.tif`
- ✅ Successfully processed through COG pipeline
- ✅ Cataloged to STAC with correct `/vsiaz/` path
- ✅ Opens in QGIS locally
- ❌ Cannot be read by TiTiler: `not recognized as being in a supported file format`

---

## Solution: Add Optional Stage 4 - TiTiler Validation

### High-Level Design

Add a new **optional** Stage 4 to the `ProcessRasterWorkflow` that validates TiTiler compatibility after COG creation.

**Current Pipeline** (3 stages):
1. Validate Raster → CRS, bit-depth, type detection
2. Create COG → rio-cogeo conversion
3. Extract STAC → Catalog to PgSTAC

**New Pipeline** (4 stages):
1. Validate Raster → CRS, bit-depth, type detection
2. Create COG → rio-cogeo conversion
3. Extract STAC → Catalog to PgSTAC
4. **Validate TiTiler (Optional)** → Test COG via /vsiaz/ with OAuth

---

## Implementation Requirements

### 1. Configuration (config.py)

Add new configuration settings:

```python
class Config(BaseSettings):
    # ... existing config ...

    # TiTiler validation settings
    titiler_validation_mode: Literal["skip", "warn", "fail"] = Field(
        default="fail",
        description="TiTiler validation mode: skip=no validation, warn=validate but don't fail job, fail=fail job if validation fails"
    )

    titiler_base_url: str = Field(
        default="https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net",
        description="Base URL for TiTiler-pgSTAC tile server (MUST be set as environment variable)"
    )
```

**Environment Variable**: `TITILER_BASE_URL` (required)

**Validation Modes**:
- `skip`: Stage 4 is completely skipped (no validation)
- `warn`: Validation runs but job succeeds even if validation fails (warnings logged)
- `fail`: Validation runs and job fails if validation fails (default)

### 2. Create Validation Handler

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_titiler_validation.py` (NEW)

```python
def validate_titiler_cog(params: dict) -> dict:
    """
    Validate COG is TiTiler-compatible by attempting to read it via /vsiaz/.

    Params:
        container: str - Azure container name
        blob_name: str - COG blob path
        validation_mode: str - "skip", "warn", or "fail" (optional, defaults to config)

    Returns:
        {
            "success": bool,
            "titiler_compatible": bool,
            "validation_mode": str,
            "skipped": bool,
            "validation_results": {
                "can_open_vsiaz": bool,
                "has_overviews": bool,
                "tile_size_ok": bool,
                "interleave_ok": bool,
                "can_read_metadata": bool,
                "sample_tile_read_ok": bool
            },
            "warnings": [...],
            "errors": [...],
            "test_urls": {
                "info": "https://titiler.../cog/info?url=/vsiaz/...",
                "preview": "https://titiler.../cog/preview.png?url=/vsiaz/...",
                "viewer": "https://titiler.../cog/WebMercatorQuad/map.html?url=/vsiaz/..."
            }
        }
    """
```

**Validation Steps**:
1. Check `validation_mode` - if "skip", return immediately with `skipped=True`
2. Get `titiler_base_url` from config (ensure it's set via environment variable)
3. Construct `/vsiaz/` path: `/vsiaz/{container}/{blob_name}`
4. Set OAuth token via `AZURE_STORAGE_ACCESS_TOKEN` environment variable
5. Open COG with rasterio using /vsiaz/ path
6. Check COG profile:
   - Has internal overviews
   - Tile size is 512x512
   - BAND interleave
   - Internal tiling present
7. Attempt to read sample metadata (bands, bounds, etc.)
8. **Optional**: Test TiTiler /cog/info endpoint via HTTP
9. **Generate correct TiTiler URLs** (see URL format section below)
10. Return detailed validation report

**CRITICAL: Correct TiTiler URL Format**

TiTiler is a **Direct COG Access** tile server, NOT a STAC API server. URLs must use the `/cog/` endpoint with the `/vsiaz/` path as a query parameter.

**✅ CORRECT Format** (Direct COG Access):
```
Base: https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/

Info:    {base}/cog/info?url=/vsiaz/{container}/{blob_path}
Preview: {base}/cog/preview.png?url=/vsiaz/{container}/{blob_path}&max_size=512
Viewer:  {base}/cog/WebMercatorQuad/map.html?url=/vsiaz/{container}/{blob_path}
Tiles:   {base}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=/vsiaz/{container}/{blob_path}
```

**❌ WRONG Format** (STAC API - does not exist):
```
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections/system-rasters/items/{item_id}/WebMercatorQuad/map.html
```

**Why the wrong format doesn't work**:
- TiTiler-pgSTAC does NOT expose STAC item endpoints (`/collections/.../items/...`)
- Item-based URLs require a separate STAC API server (deployed at `rmhgeoapi`)
- TiTiler only serves tiles via `/cog/` (direct) or `/searches/` (pgSTAC mosaic)

**Example - Correct URL Construction**:
```python
# Given:
container = "silver-cogs"
blob_name = "nam_r2c2/namangan14aug2019_R2C2cog_cog_analysis.tif"
titiler_base_url = "https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net"

# Construct /vsiaz/ path
vsiaz_path = f"/vsiaz/{container}/{blob_name}"
# Result: /vsiaz/silver-cogs/nam_r2c2/namangan14aug2019_R2C2cog_cog_analysis.tif

# URL-encode the path for query parameter
import urllib.parse
encoded_path = urllib.parse.quote(vsiaz_path, safe='')
# Result: %2Fvsiaz%2Fsilver-cogs%2Fnam_r2c2%2Fnamangan14aug2019_R2C2cog_cog_analysis.tif

# Generate URLs
info_url = f"{titiler_base_url}/cog/info?url={encoded_path}"
viewer_url = f"{titiler_base_url}/cog/WebMercatorQuad/map.html?url={encoded_path}"
preview_url = f"{titiler_base_url}/cog/preview.png?url={encoded_path}&max_size=512"
```

**Result URLs**:
- Info: `https://rmhtitiler-.../cog/info?url=%2Fvsiaz%2Fsilver-cogs%2Fnam_r2c2%2Fnamangan14aug2019_R2C2cog_cog_analysis.tif`
- Viewer: `https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=%2Fvsiaz%2Fsilver-cogs%2Fnam_r2c2%2Fnamangan14aug2019_R2C2cog_cog_analysis.tif`
- Preview: `https://rmhtitiler-.../cog/preview.png?url=%2Fvsiaz%2Fsilver-cogs%2Fnam_r2c2%2Fnamangan14aug2019_R2C2cog_cog_analysis.tif&max_size=512`

**Error Handling**:
- If `validation_mode == "warn"`: Log errors but return `success=True`
- If `validation_mode == "fail"`: Return `success=False` on validation failure
- If `validation_mode == "skip"`: Return `success=True, skipped=True` immediately

### 3. Modify Process Raster Job

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/jobs/process_raster.py`

**Add Stage 4 definition**:
```python
stages: List[Dict[str, Any]] = [
    # ... existing stages 1-3 ...
    {
        "number": 4,
        "name": "validate_titiler",
        "task_type": "validate_titiler_cog",
        "description": "Validate COG is readable by TiTiler via /vsiaz/ (optional)",
        "parallelism": "single"
    }
]
```

**Update `create_tasks_for_stage()`**:
```python
elif stage == 4:
    # Stage 4: TiTiler validation (optional)
    from config import get_config
    config = get_config()

    # Check if validation should be skipped
    validation_mode = job_params.get("titiler_validation_mode", config.titiler_validation_mode)

    if validation_mode == "skip":
        # Return empty task list - skip stage entirely
        return []

    # Get COG info from Stage 2 results
    stage_2_result = previous_results[0]  # Assuming single task in Stage 2
    if not stage_2_result.get('success'):
        raise ValueError(f"Stage 2 failed: {stage_2_result.get('error')}")

    cog_container = stage_2_result['result']['cog_container']
    cog_blob = stage_2_result['result']['cog_blob']

    task_id = generate_deterministic_task_id(job_id, 4, f"{cog_container}/{cog_blob}")
    return [
        {
            "task_id": task_id,
            "task_type": "validate_titiler_cog",
            "parameters": {
                "container": cog_container,
                "blob_name": cog_blob,
                "validation_mode": validation_mode
            }
        }
    ]
```

**Update `finalize_job()`**:
```python
# Stage 4: TiTiler validation (if ran)
stage_4_tasks = [t for t in task_results if t.task_type == "validate_titiler_cog"]

titiler_validation = None
if stage_4_tasks:
    validation_task = stage_4_tasks[0]
    if validation_task.result_data:
        result = validation_task.result_data.get("result", {})
        titiler_validation = {
            "skipped": result.get("skipped", False),
            "compatible": result.get("titiler_compatible", False),
            "validation_mode": result.get("validation_mode", "unknown"),
            "warnings": result.get("warnings", []),
            "errors": result.get("errors", []),
            "test_urls": result.get("test_urls", {})
        }

return {
    # ... existing fields ...
    "titiler_validation": titiler_validation
}
```

### 4. Register Handler

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/__init__.py`

Add to `ALL_HANDLERS` registry:
```python
ALL_HANDLERS = {
    # ... existing handlers ...
    "validate_titiler_cog": validate_titiler_cog,
}
```

Import statement:
```python
from services.raster_titiler_validation import validate_titiler_cog
```

---

## Configuration Requirements

### Environment Variables (Azure Function App)

**Required**:
```bash
TITILER_BASE_URL=https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
```

**Optional**:
```bash
TITILER_VALIDATION_MODE=fail  # Options: skip, warn, fail (default: fail)
```

### Job Submission Parameters

Users can override validation mode per-job:

```json
{
  "job_type": "process_raster",
  "parameters": {
    "source_container": "bronze-rasters",
    "source_blob": "input.tif",
    "target_container": "silver-cogs",
    "titiler_validation_mode": "warn"  // Optional override
  }
}
```

---

## Job Response Format

### With Validation Enabled (mode: "fail" or "warn")

```json
{
  "job_id": "abc123...",
  "job_type": "process_raster",
  "status": "completed",
  "summary": {
    "validation": { "passed": true },
    "cog": { "created": true, "blob": "silver-cogs/output.tif" },
    "stac": { "inserted": true, "item_id": "..." },
    "titiler_validation": {
      "skipped": false,
      "compatible": true,
      "validation_mode": "fail",
      "warnings": [],
      "errors": [],
      "test_urls": {
        "info": "https://rmhtitiler-.../cog/info?url=/vsiaz/silver-cogs/output.tif",
        "preview": "https://rmhtitiler-.../cog/preview.png?url=/vsiaz/...",
        "viewer": "https://rmhtitiler-.../cog/WebMercatorQuad/map.html?url=/vsiaz/..."
      }
    }
  }
}
```

### With Validation Skipped (mode: "skip")

```json
{
  "job_id": "abc123...",
  "job_type": "process_raster",
  "status": "completed",
  "summary": {
    "validation": { "passed": true },
    "cog": { "created": true },
    "stac": { "inserted": true },
    "titiler_validation": {
      "skipped": true,
      "validation_mode": "skip"
    }
  }
}
```

### With Validation Failed (mode: "fail")

```json
{
  "job_id": "abc123...",
  "job_type": "process_raster",
  "status": "failed",
  "summary": {
    "validation": { "passed": true },
    "cog": { "created": true },
    "stac": { "inserted": true },
    "titiler_validation": {
      "skipped": false,
      "compatible": false,
      "validation_mode": "fail",
      "warnings": [],
      "errors": [
        "Failed to open COG via /vsiaz/: not recognized as being in a supported file format",
        "TiTiler /cog/info endpoint returned 500 error"
      ],
      "test_urls": {
        "info": "https://rmhtitiler-.../cog/info?url=/vsiaz/silver-cogs/output.tif"
      }
    }
  }
}
```

---

## Implementation Checklist

### Phase 1: Core Implementation
- [ ] Add `titiler_validation_mode` and `titiler_base_url` to `config.py`
- [ ] Set `TITILER_BASE_URL` environment variable in Azure Function App
- [ ] Create `services/raster_titiler_validation.py` with `validate_titiler_cog()` function
- [ ] Register handler in `services/__init__.py`
- [ ] Add Stage 4 definition to `jobs/process_raster.py`
- [ ] Implement Stage 4 task creation logic (handle "skip" mode)
- [ ] Update `finalize_job()` to include TiTiler validation results

### Phase 2: Testing
- [ ] Test with validation_mode="skip" (should skip Stage 4 entirely)
- [ ] Test with validation_mode="warn" + failing COG (should succeed with warnings)
- [ ] Test with validation_mode="fail" + failing COG (should fail job)
- [ ] Test with validation_mode="fail" + passing COG (should succeed)
- [ ] Test with dctest3 file (known to fail validation)
- [ ] Test with various raster types (RGB, DEM, multispectral)

### Phase 3: Documentation
- [ ] Update API documentation with new validation_mode parameter
- [ ] Document environment variable requirements
- [ ] Add troubleshooting guide for common validation failures
- [ ] Update job response schema documentation

---

## Key Design Decisions

### 1. Stage 4 is Optional and Configurable
- **Default**: `validation_mode="fail"` (strict validation)
- **Override**: Per-job parameter allows flexibility
- **Skip Mode**: Returns empty task list - stage never executes

### 2. TiTiler URL from Config + Environment Variable
- **Config Default**: Provides fallback URL
- **Environment Variable**: `TITILER_BASE_URL` must be set in production
- **Validation**: Handler should verify URL is set and valid

### 3. Three Validation Modes
- **skip**: No validation (backward compatible, fast)
- **warn**: Best for gradual rollout (identify issues without blocking)
- **fail**: Production mode (strict quality control)

### 4. Stage 4 Runs After STAC Cataloging
- COG already created and cataloged before validation
- If validation fails in "fail" mode:
  - Job marked as failed
  - STAC item remains in database (can be cleaned up later)
  - COG remains in storage (can be reprocessed)

---

## Testing Strategy

### 1. Unit Tests (services/raster_titiler_validation.py)
- Test "skip" mode returns immediately
- Test "warn" mode with failing COG returns success
- Test "fail" mode with failing COG returns failure
- Test OAuth token is set correctly
- Test /vsiaz/ path construction

### 2. Integration Tests (jobs/process_raster.py)
- Test Stage 4 is skipped when validation_mode="skip"
- Test Stage 4 receives correct parameters from Stage 2
- Test job fails when validation fails in "fail" mode
- Test job succeeds when validation fails in "warn" mode

### 3. End-to-End Tests
- Submit job with known-good COG (should pass)
- Submit job with dctest3 COG (should fail or warn)
- Submit job with validation_mode="skip" (should complete without Stage 4)

---

## Rollout Plan

### Phase 1: Soft Launch (validation_mode="warn")
1. Deploy with `TITILER_VALIDATION_MODE=warn`
2. Monitor validation results for 1-2 weeks
3. Identify common failure patterns
4. Fix any bugs in validation logic

### Phase 2: Strict Mode (validation_mode="fail")
1. Update to `TITILER_VALIDATION_MODE=fail`
2. All new COGs must pass TiTiler validation
3. Reprocess any existing COGs that fail validation

### Phase 3: Backfill (Optional)
1. Create "validate STAC collection" job to batch-validate existing items
2. Generate report of items that fail validation
3. Reprocess failed items through COG pipeline

---

## Related Files

### Files to Create
- `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_titiler_validation.py`

### Files to Modify
- `/Users/robertharrison/python_builds/rmhgeoapi/config.py` (add settings)
- `/Users/robertharrison/python_builds/rmhgeoapi/jobs/process_raster.py` (add Stage 4)
- `/Users/robertharrison/python_builds/rmhgeoapi/services/__init__.py` (register handler)

### Reference Files (No Changes Needed)
- `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_validation.py` (Stage 1 example)
- `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_cog.py` (Stage 2 example)
- `/Users/robertharrison/python_builds/rmhgeoapi/services/stac_catalog.py` (Stage 3 example)

---

## Success Criteria

After implementation:

✅ **Configuration**
- TiTiler URL configurable via environment variable
- Validation mode configurable (skip/warn/fail)
- Default mode is "fail" (strict)

✅ **Validation Logic**
- Opens COG via /vsiaz/ with OAuth
- Checks COG profile (overviews, tile size, interleave)
- Attempts sample metadata reads
- Returns detailed validation report

✅ **Job Execution**
- Stage 4 skipped entirely when validation_mode="skip"
- Stage 4 runs after STAC cataloging
- Job succeeds with warnings when validation_mode="warn"
- Job fails when validation_mode="fail" and COG fails validation

✅ **Testing**
- Known-good COGs pass validation
- Known-bad COGs fail validation
- All three modes (skip/warn/fail) work correctly
- Per-job override parameter works

---

**Status**: 📝 Ready for Implementation
**Estimated Effort**: 4-6 hours (implementation + testing)
**Priority**: High - Prevents catalog pollution with unreadable COGs
