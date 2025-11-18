# Raster Workflow Validation Analysis

**Author**: Robert and Geospatial Claude Legion
**Date**: 11 NOV 2025
**Status**: Analysis Complete - Validation Gap Identified

## Executive Summary

**Current State**: Raster workflows (`process_raster`, `process_raster_collection`) fail downstream when container/blob doesn't exist, resulting in cryptic `FILE_UNREADABLE` errors deep in GDAL operations.

**Gap Identified**: No immediate fail-fast validation at job submission or Stage 1 task creation.

**Solution Proposed**: Two-tier validation strategy using existing decorator infrastructure.

---

## 1. Current Validation - What Exists Today

### ✅ Existing Validation Infrastructure (28 OCT 2025)

**Location**: `infrastructure/decorators_blob.py`

Three decorator validators already exist and are production-ready:

```python
@validate_container              # Validates container exists
@validate_blob                   # Validates blob exists
@validate_container_and_blob     # Combined validation (most efficient)
```

**Current Usage**: Applied to `BlobRepository` methods (read_blob, write_blob, delete_blob, etc.)

**Validation Methods Available**:
- `blob_repo.container_exists(container_name) -> bool`
- `blob_repo.blob_exists(container_name, blob_name) -> bool`
- `blob_repo.validate_container_and_blob(container, blob) -> dict`

### ✅ Stage 1 Validation (Comprehensive)

**Location**: `services/raster_validation.py`
**Handler**: `validate_raster()`

**9-Step Validation Process**:
1. ✅ Logger initialization
2. ✅ Parameter extraction and validation
3. ✅ Lazy import rasterio/numpy dependencies
4. ✅ **Open raster file via GDAL** (blob_url with SAS token)
5. ✅ Extract basic file information (bands, dtype, shape, bounds)
6. ✅ CRS validation (file metadata vs user override)
7. ✅ Bit-depth efficiency check (flags 64-bit data as CRITICAL)
8. ✅ Raster type detection (RGB, RGBA, DEM, categorical, multispectral)
9. ✅ Optimal COG settings recommendation

**Current Error Handling**:
```python
# STEP 3: Open raster file
try:
    src = rasterio.open(blob_url)  # ← GDAL opens /vsiaz/ path
except Exception as e:
    return {
        "success": False,
        "error": "FILE_UNREADABLE",  # ← Generic error
        "message": f"Cannot open raster file: {e}"
    }
```

**Problem**: If container/blob doesn't exist, GDAL fails with cryptic error like:
- "No such file or directory"
- "HTTP error 404"
- "Access denied"

User sees `FILE_UNREADABLE` without clear indication that blob simply doesn't exist.

---

## 2. Validation Gaps - Where We Fail

### ❌ Gap 1: Job Submission Time (Immediate Failure Missing)

**Location**: `jobs/process_raster.py`, `jobs/process_raster_collection.py`

**Current Behavior**:
```python
@staticmethod
def validate_job_parameters(params: dict) -> dict:
    """
    Validates:
    - blob_name is non-empty string ✅
    - container_name format ✅
    - raster_type in allowed values ✅
    """
    # ❌ MISSING: Check if container exists
    # ❌ MISSING: Check if blob exists
```

**What Happens**:
1. User submits job with typo in blob path
2. Job validation passes (string format valid)
3. Job queued successfully
4. Stage 1 task created with SAS URL
5. **Task fails 10+ seconds later** when GDAL tries to open blob
6. Task retries 3 times (30+ seconds wasted)
7. Job marked FAILED with cryptic error

**User Experience**: 😢
```json
{
  "error": "FILE_UNREADABLE",
  "message": "Cannot open raster file: /vsiaz/rmhazuregeobronze/wrong_path.tif: No such file or directory"
}
```

User has to parse GDAL error to realize blob path is wrong.

### ❌ Gap 2: Stage 1 Task Creation (No Pre-Flight Check)

**Location**: `jobs/process_raster.py` lines 434-463
**Method**: `create_tasks_for_stage(stage=1, ...)`

**Current Behavior**:
```python
if stage == 1:
    # Use config default if container_name not specified
    container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')

    # ❌ MISSING: Validate container exists before generating SAS URL
    # ❌ MISSING: Validate blob exists before generating SAS URL

    # Build blob URL with SAS token
    blob_repo = BlobRepository.instance()
    blob_url = blob_repo.get_blob_url_with_sas(
        container_name=container_name,
        blob_name=job_params['blob_name'],
        hours=1
    )
    # SAS token generation SUCCEEDS even if blob doesn't exist!
```

**Problem**: Azure generates valid SAS URLs for non-existent blobs. URL generation != blob validation.

---

## 3. Proposed Solution - Two-Tier Validation

### Tier 1: Job Submission Validation (Immediate Fail-Fast)

**When**: Before job record creation
**Where**: `jobs/process_raster.py` → `validate_job_parameters()`
**Cost**: ~100ms per job (acceptable)

```python
@staticmethod
def validate_job_parameters(params: dict) -> dict:
    """Enhanced validation with blob existence checks"""
    validated = {}

    # ... existing validation ...

    # NEW: Validate container and blob exist (fail-fast)
    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.instance()

    container_name = validated.get("container_name")
    blob_name = validated["blob_name"]

    # Check container exists
    if not blob_repo.container_exists(container_name):
        raise ValueError(
            f"Container '{container_name}' does not exist in storage account. "
            f"Check container name spelling or create container first."
        )

    # Check blob exists
    if not blob_repo.blob_exists(container_name, blob_name):
        raise ValueError(
            f"Blob '{blob_name}' does not exist in container '{container_name}'. "
            f"Check blob path spelling. Available blobs can be listed via "
            f"/api/containers/{container_name}/blobs endpoint."
        )

    return validated
```

**Benefits**:
- ✅ Fail in **<1 second** (not 30+ seconds after retries)
- ✅ Clear error message with actionable guidance
- ✅ No wasted task retries
- ✅ No poison queue messages
- ✅ Better user experience

**Trade-off**: Extra 100ms validation time (negligible for ETL workflows)

### Tier 2: Stage 1 Validation Enhancement (Better Errors)

**When**: Stage 1 task execution
**Where**: `services/raster_validation.py` → `validate_raster()`
**Cost**: ~50ms before GDAL operation

**Option A: Pre-Flight Check Before GDAL Open**

```python
def validate_raster(params: dict) -> dict:
    # ... existing steps 0-2 ...

    # NEW STEP 3a: Validate blob exists before GDAL operation
    try:
        logger.info("🔄 STEP 3a: Pre-flight blob validation...")

        # Extract container and blob from blob_url
        # blob_url format: https://<account>.blob.core.windows.net/<container>/<blob>?<sas>
        from infrastructure.blob import BlobRepository
        blob_repo = BlobRepository.instance()

        container_name = params.get('container_name')
        blob_name = params.get('blob_name')

        # Validate container and blob exist
        validation = blob_repo.validate_container_and_blob(container_name, blob_name)

        if not validation['valid']:
            logger.error(f"❌ STEP 3a FAILED: {validation['message']}")
            return {
                "success": False,
                "error": "FILE_NOT_FOUND",  # NEW: Specific error code
                "message": validation['message'],
                "blob_name": blob_name,
                "container_name": container_name,
                "suggestion": "Verify blob path spelling and container name"
            }

        logger.info("✅ STEP 3a: Blob exists validation passed")

    except Exception as e:
        logger.error(f"❌ STEP 3a FAILED: Validation error: {e}")
        return {
            "success": False,
            "error": "VALIDATION_ERROR",
            "message": f"Failed to validate blob existence: {e}"
        }

    # EXISTING STEP 3: Open raster file
    try:
        logger.info(f"🔄 STEP 3: Opening raster file via SAS URL...")
        src = rasterio.open(blob_url)
        # ... rest of existing logic ...
```

**Option B: Enhanced Error Detection (Simpler)**

```python
# STEP 3: Open raster file
try:
    logger.info(f"🔄 STEP 3: Opening raster file via SAS URL...")
    src = rasterio.open(blob_url)
except Exception as e:
    error_str = str(e).lower()

    # NEW: Detect blob not found errors
    if any(phrase in error_str for phrase in ['no such file', '404', 'not found', 'does not exist']):
        logger.error(f"❌ STEP 3 FAILED: Blob not found - {e}")
        return {
            "success": False,
            "error": "FILE_NOT_FOUND",  # NEW: Specific error code
            "message": f"Blob '{blob_name}' does not exist in container '{container_name}'",
            "blob_name": blob_name,
            "container_name": container_name,
            "gdal_error": str(e),
            "suggestion": "Verify blob path spelling and container name"
        }

    # Generic file unreadable (different error)
    logger.error(f"❌ STEP 3 FAILED: Cannot open raster file: {e}")
    return {
        "success": False,
        "error": "FILE_UNREADABLE",
        "message": f"Cannot open raster file: {e}",
        # ... existing error details ...
    }
```

**Recommendation**: Use **Option A (Pre-Flight Check)** because:
1. Validates blob before expensive GDAL operation
2. Consistent with existing decorator validation pattern
3. Clearer error messages (no GDAL error parsing)
4. 50ms overhead is negligible for raster validation (already 5-10 seconds)

---

## 4. Implementation Checklist

### Phase 1: Job Submission Validation (High Priority)

- [ ] **Update `jobs/process_raster.py`**:
  - [ ] Add container existence check to `validate_job_parameters()`
  - [ ] Add blob existence check to `validate_job_parameters()`
  - [ ] Update error messages with actionable guidance

- [ ] **Update `jobs/process_raster_collection.py`**:
  - [ ] Add container existence check to `validate_job_parameters()`
  - [ ] Add blob_list validation (check all blobs exist)
  - [ ] Fail immediately if any blob missing
  - [ ] Report which blobs are missing in error message

- [ ] **Test Cases**:
  - [ ] Submit job with non-existent container → Immediate failure with clear error
  - [ ] Submit job with non-existent blob → Immediate failure with clear error
  - [ ] Submit job with typo in blob path → Immediate failure with suggestion
  - [ ] Submit collection with 1 missing blob out of 10 → Report which blob missing

### Phase 2: Stage 1 Validation Enhancement (Medium Priority)

- [ ] **Update `services/raster_validation.py`**:
  - [ ] Add STEP 3a: Pre-flight blob validation (Option A)
  - [ ] Return `FILE_NOT_FOUND` error code for missing blobs
  - [ ] Add `blob_name` and `container_name` to error result
  - [ ] Add "suggestion" field to error result

- [ ] **Update Error Handling**:
  - [ ] Add `FILE_NOT_FOUND` to error code documentation
  - [ ] Update API responses to handle new error code
  - [ ] Add error code to retry logic (don't retry FILE_NOT_FOUND)

- [ ] **Test Cases**:
  - [ ] Validation task with non-existent blob → FILE_NOT_FOUND error
  - [ ] Validation task with read-protected blob → FILE_UNREADABLE error
  - [ ] Validation task with corrupted blob → FILE_UNREADABLE error

### Phase 3: Documentation (Low Priority)

- [ ] Update `docs_claude/RASTER_WORKFLOW_VALIDATION.md` with new validation flow
- [ ] Add blob validation to API documentation
- [ ] Update error code reference guide

---

## 5. Error Code Matrix (Before/After)

| Scenario | Current Error | Proposed Error | User Experience Improvement |
|----------|---------------|----------------|----------------------------|
| Container doesn't exist | `FILE_UNREADABLE` (after 30s) | `ValueError` at submission | ✅ Fail in <1s with clear message |
| Blob doesn't exist | `FILE_UNREADABLE` (after 30s) | `ValueError` at submission | ✅ Fail in <1s with suggestion |
| Blob path typo | `FILE_UNREADABLE` (after 30s) | `ValueError` at submission | ✅ Clear error with path shown |
| Blob unreadable (corrupt) | `FILE_UNREADABLE` (correct) | `FILE_UNREADABLE` (unchanged) | ✅ No change (already correct) |
| Missing SAS permissions | `FILE_UNREADABLE` (after 10s) | `FILE_UNREADABLE` (unchanged) | ⚠️ No change (different issue) |

---

## 6. Performance Impact Analysis

### Job Submission Validation

**Added Operations**:
1. `container_exists()` → 1 Azure API call (~50ms)
2. `blob_exists()` → 1 Azure API call (~50ms)

**Total Overhead**: ~100ms per job submission

**Benefit**: Save 30+ seconds if blob doesn't exist (3 retries × 10s each)

**Net Impact**: ✅ **Massive improvement** for failed jobs, negligible for successful jobs

### Stage 1 Task Validation

**Added Operations**:
1. `validate_container_and_blob()` → 2 Azure API calls (~100ms)

**Total Overhead**: ~100ms before GDAL operation

**Benefit**: Clear error message instead of cryptic GDAL error

**Net Impact**: ✅ **Negligible overhead** (Stage 1 validation already takes 5-10 seconds)

---

## 7. Backward Compatibility

### Breaking Changes: NONE ✅

**Reason**: Validation only adds **earlier failure detection**. Jobs that would succeed still succeed, jobs that would fail just fail faster with better errors.

### API Contract Changes: NONE ✅

**Reason**:
- Job submission returns same success/error response structure
- New error messages are more specific but same format
- Task results use existing error code structure

### Deployment Risk: LOW ✅

**Reason**:
- No database schema changes
- No queue message format changes
- Uses existing `BlobRepository` methods (already production-tested)
- Decorators already in production use

---

## 8. Alternative Approaches Considered

### ❌ Option 1: Validate Only at Stage 1 Task Execution

**Rejected Reason**: Wastes queue resources, delayed feedback to user

### ❌ Option 2: Add Retry Logic with Better Errors

**Rejected Reason**: Doesn't solve root cause (missing blob), just makes retries prettier

### ❌ Option 3: Create Decorator for Job Parameter Validation

**Rejected Reason**: Over-engineering. Simple existence check doesn't need decorator pattern.

### ✅ Option 4: Two-Tier Validation (SELECTED)

**Why**: Best trade-off between early detection and implementation simplicity

---

## 9. Testing Strategy

### Unit Tests

```python
def test_validate_job_parameters_missing_container():
    """Job submission should fail immediately if container doesn't exist"""
    params = {
        "blob_name": "test.tif",
        "container_name": "nonexistent-container"
    }

    with pytest.raises(ValueError, match="Container.*does not exist"):
        ProcessRasterWorkflow.validate_job_parameters(params)

def test_validate_job_parameters_missing_blob():
    """Job submission should fail immediately if blob doesn't exist"""
    params = {
        "blob_name": "nonexistent.tif",
        "container_name": "bronze-rasters"  # exists
    }

    with pytest.raises(ValueError, match="Blob.*does not exist"):
        ProcessRasterWorkflow.validate_job_parameters(params)
```

### Integration Tests

```bash
# Test 1: Submit job with wrong container
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test.tif",
    "container_name": "wrong-container"
  }'

# Expected: HTTP 400, error message "Container 'wrong-container' does not exist"

# Test 2: Submit job with wrong blob path
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "wrong_path.tif",
    "container_name": "bronze-rasters"
  }'

# Expected: HTTP 400, error message "Blob 'wrong_path.tif' does not exist in container 'bronze-rasters'"
```

---

## 10. Rollout Plan

### Step 1: Implement Job Submission Validation (Week 1)

1. Update `process_raster.py` validation
2. Update `process_raster_collection.py` validation
3. Deploy to dev environment
4. Test with known missing blobs
5. Monitor for false positives

### Step 2: Implement Stage 1 Validation Enhancement (Week 2)

1. Add STEP 3a to `raster_validation.py`
2. Update error codes and messages
3. Deploy to dev environment
4. Test with various error scenarios
5. Monitor task retry rates (should decrease)

### Step 3: Production Deployment (Week 3)

1. Deploy to production
2. Monitor job submission errors (should increase for bad inputs)
3. Monitor task failures (should decrease overall)
4. Collect user feedback on error message clarity

---

## 11. Success Metrics

**Before Implementation**:
- Job submission with missing blob: Fails after 30+ seconds
- Error message: "FILE_UNREADABLE: Cannot open raster file: ..."
- User knows: File failed, but not why

**After Implementation**:
- Job submission with missing blob: Fails in <1 second
- Error message: "Blob 'x.tif' does not exist in container 'y'. Check blob path spelling."
- User knows: Exactly what to fix

**KPIs**:
- ✅ Time to failure: 30s → <1s (30x improvement)
- ✅ Error message clarity: Generic → Specific
- ✅ Task retry waste: 3 retries → 0 retries
- ✅ User confusion: High → Low

---

## 12. Open Questions

1. **Q**: Should we validate SAS token permissions in addition to blob existence?
   **A**: Out of scope for now. Different error type (permission vs existence).

2. **Q**: Should we add batch validation for collections (validate all blobs at once)?
   **A**: Yes, in Phase 1. Use `blob_repo.blob_exists()` in loop with early exit.

3. **Q**: What if validation passes but blob gets deleted before task execution?
   **A**: Acceptable race condition. Stage 1 will catch it with FILE_NOT_FOUND error.

4. **Q**: Should we add container/blob existence to health endpoint?
   **A**: No. Health endpoint checks system status, not user data.

---

## Conclusion

**Current State**: ❌ Poor user experience with delayed, cryptic errors

**Proposed State**: ✅ Immediate validation with clear, actionable error messages

**Implementation Effort**: Low (2-3 days)

**Risk**: Minimal (uses existing production-tested infrastructure)

**Impact**: High (30x faster failure detection, clear error messages)

**Recommendation**: ✅ **Proceed with implementation** using existing decorator infrastructure

---

**Next Steps**: Review this analysis, get approval, implement Phase 1 job submission validation.