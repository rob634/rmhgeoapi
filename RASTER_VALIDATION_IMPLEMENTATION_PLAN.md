# Raster Workflow Validation - Implementation Plan

**Author**: Robert and Geospatial Claude Legion
**Date**: 11 NOV 2025
**Status**: Ready for Implementation
**Azure Exception**: `azure.core.exceptions.ResourceNotFoundError`

## Overview

Implement immediate fail-fast validation for raster workflows using **Azure-native exceptions** with explicit error messages.

---

## 1. Implementation Strategy - Two-Tier Validation

### Tier 1: Job Submission Validation ⚡ IMMEDIATE FAIL-FAST

**When**: Before job record creation
**Where**: `jobs/process_raster.py` → `validate_job_parameters()`
**Cost**: ~100ms per job (2 Azure API calls)
**Exception**: `azure.core.exceptions.ResourceNotFoundError`

#### Code Implementation

```python
@staticmethod
def validate_job_parameters(params: dict) -> dict:
    """
    Enhanced validation with blob existence checks using Azure exceptions.

    Raises:
        ResourceNotFoundError: If container or blob doesn't exist
    """
    from azure.core.exceptions import ResourceNotFoundError
    from infrastructure.blob import BlobRepository

    validated = {}

    # ... existing validation (blob_name format, raster_type, etc.) ...

    # Get blob repository instance
    blob_repo = BlobRepository.instance()
    container_name = validated.get("container_name")
    blob_name = validated["blob_name"]

    # ================================================================
    # NEW: Validate container exists (Azure ResourceNotFoundError)
    # ================================================================
    if not blob_repo.container_exists(container_name):
        raise ResourceNotFoundError(
            f"Container '{container_name}' does not exist in storage account "
            f"'{blob_repo.account_name}'. Verify container name spelling or create "
            f"container before submitting job."
        )

    # ================================================================
    # NEW: Validate blob exists (Azure ResourceNotFoundError)
    # ================================================================
    if not blob_repo.blob_exists(container_name, blob_name):
        raise ResourceNotFoundError(
            f"File '{blob_name}' not found in existing container '{container_name}' "
            f"(storage account: '{blob_repo.account_name}'). Verify blob path spelling. "
            f"Available blobs can be listed via /api/containers/{container_name}/blobs endpoint."
        )

    return validated
```

#### Error Message Examples

**Container doesn't exist**:
```
ResourceNotFoundError: Container 'rmhazuregeobronze' does not exist in storage account 'rmhazuregeo'. Verify container name spelling or create container before submitting job.
```

**File doesn't exist**:
```
ResourceNotFoundError: File 'wrong_path.tif' not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'). Verify blob path spelling. Available blobs can be listed via /api/containers/rmhazuregeobronze/blobs endpoint.
```

---

### Tier 2: Stage 1 Validation Enhancement (Better Error Detection)

**When**: Stage 1 task execution
**Where**: `services/raster_validation.py` → `validate_raster()`
**Cost**: ~50ms before GDAL operation
**Exception**: `azure.core.exceptions.ResourceNotFoundError`

#### Code Implementation

```python
def validate_raster(params: dict) -> dict:
    """
    Validate raster file with pre-flight blob existence checks.

    Returns dict with explicit error codes:
    - CONTAINER_NOT_FOUND: Container doesn't exist
    - FILE_NOT_FOUND: Blob doesn't exist in existing container
    - FILE_UNREADABLE: Blob exists but GDAL can't open it
    """
    from azure.core.exceptions import ResourceNotFoundError

    # ... existing steps 0-2 (logger init, params, lazy imports) ...

    # ================================================================
    # NEW STEP 3a: Pre-flight blob validation (before GDAL)
    # ================================================================
    try:
        logger.info("🔄 STEP 3a: Pre-flight blob validation...")

        from infrastructure.blob import BlobRepository
        blob_repo = BlobRepository.instance()

        container_name = params.get('container_name')
        blob_name = params.get('blob_name')

        # Check container exists first
        if not blob_repo.container_exists(container_name):
            error_msg = (
                f"Container '{container_name}' does not exist in storage account "
                f"'{blob_repo.account_name}'"
            )
            logger.error(f"❌ STEP 3a FAILED: {error_msg}")
            return {
                "success": False,
                "error": "CONTAINER_NOT_FOUND",
                "error_type": "ResourceNotFoundError",
                "message": error_msg,
                "container_name": container_name,
                "storage_account": blob_repo.account_name,
                "blob_name": blob_name
            }

        # Check blob exists in container
        if not blob_repo.blob_exists(container_name, blob_name):
            error_msg = (
                f"File '{blob_name}' not found in existing container '{container_name}' "
                f"(storage account: '{blob_repo.account_name}')"
            )
            logger.error(f"❌ STEP 3a FAILED: {error_msg}")
            return {
                "success": False,
                "error": "FILE_NOT_FOUND",
                "error_type": "ResourceNotFoundError",
                "message": error_msg,
                "blob_name": blob_name,
                "container_name": container_name,
                "storage_account": blob_repo.account_name,
                "suggestion": f"Verify blob path spelling. Use /api/containers/{container_name}/blobs to list available files."
            }

        logger.info("✅ STEP 3a: Blob exists validation passed")

    except ResourceNotFoundError as e:
        # Catch Azure ResourceNotFoundError from blob_repo methods
        logger.error(f"❌ STEP 3a FAILED: Azure resource not found: {e}")
        return {
            "success": False,
            "error": "RESOURCE_NOT_FOUND",
            "error_type": "ResourceNotFoundError",
            "message": str(e),
            "blob_name": blob_name,
            "container_name": container_name
        }
    except Exception as e:
        logger.error(f"❌ STEP 3a FAILED: Validation error: {e}")
        return {
            "success": False,
            "error": "VALIDATION_ERROR",
            "message": f"Failed to validate blob existence: {e}"
        }

    # ================================================================
    # EXISTING STEP 3: Open raster file (GDAL operation)
    # ================================================================
    try:
        logger.info(f"🔄 STEP 3: Opening raster file via SAS URL...")
        src = rasterio.open(blob_url)
        logger.info(f"✅ STEP 3: File opened successfully")
        # ... rest of existing validation logic ...
```

#### Error Response Examples

**Container doesn't exist**:
```json
{
  "success": false,
  "error": "CONTAINER_NOT_FOUND",
  "error_type": "ResourceNotFoundError",
  "message": "Container 'rmhazuregeobronze' does not exist in storage account 'rmhazuregeo'",
  "container_name": "rmhazuregeobronze",
  "storage_account": "rmhazuregeo",
  "blob_name": "test.tif"
}
```

**File doesn't exist**:
```json
{
  "success": false,
  "error": "FILE_NOT_FOUND",
  "error_type": "ResourceNotFoundError",
  "message": "File 'wrong_path.tif' not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo')",
  "blob_name": "wrong_path.tif",
  "container_name": "rmhazuregeobronze",
  "storage_account": "rmhazuregeo",
  "suggestion": "Verify blob path spelling. Use /api/containers/rmhazuregeobronze/blobs to list available files."
}
```

---

## 2. Collection Workflow Validation

**Where**: `jobs/process_raster_collection.py` → `validate_job_parameters()`

#### Code Implementation

```python
@staticmethod
def validate_job_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate collection parameters with blob_list existence checks.

    Raises:
        ResourceNotFoundError: If container or any blob doesn't exist
    """
    from azure.core.exceptions import ResourceNotFoundError
    from infrastructure.blob import BlobRepository

    validated = {}

    # ... existing validation (blob_list format, collection_id, etc.) ...

    blob_repo = BlobRepository.instance()
    container_name = validated["container_name"]
    blob_list = validated["blob_list"]

    # ================================================================
    # NEW: Validate container exists
    # ================================================================
    if not blob_repo.container_exists(container_name):
        raise ResourceNotFoundError(
            f"Container '{container_name}' does not exist in storage account "
            f"'{blob_repo.account_name}'. Verify container name spelling."
        )

    # ================================================================
    # NEW: Validate ALL blobs in collection exist (fail immediately on first missing)
    # ================================================================
    missing_blobs = []
    for blob_name in blob_list:
        if not blob_repo.blob_exists(container_name, blob_name):
            missing_blobs.append(blob_name)

    if missing_blobs:
        # Report ALL missing blobs in error message
        missing_list = "\n  - ".join(missing_blobs)
        raise ResourceNotFoundError(
            f"Collection validation failed: {len(missing_blobs)} file(s) not found in "
            f"existing container '{container_name}' (storage account: '{blob_repo.account_name}'):\n"
            f"  - {missing_list}\n\n"
            f"Verify blob paths or use /api/containers/{container_name}/blobs to list available files."
        )

    return validated
```

#### Error Message Example

**Collection with missing blobs**:
```
ResourceNotFoundError: Collection validation failed: 3 file(s) not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'):
  - namangan/tile_001.tif
  - namangan/tile_042.tif
  - namangan/tile_103.tif

Verify blob paths or use /api/containers/rmhazuregeobronze/blobs to list available files.
```

---

## 3. Error Code Reference

### Error Code Hierarchy

| Error Code | Exception Type | When | HTTP Status | Retry? |
|------------|----------------|------|-------------|--------|
| `CONTAINER_NOT_FOUND` | `ResourceNotFoundError` | Container doesn't exist | 404 | ❌ No |
| `FILE_NOT_FOUND` | `ResourceNotFoundError` | Blob doesn't exist in existing container | 404 | ❌ No |
| `FILE_UNREADABLE` | N/A | Blob exists but GDAL can't open (corrupt, wrong format) | 400 | ⚠️ Maybe |
| `RESOURCE_NOT_FOUND` | `ResourceNotFoundError` | Generic Azure resource not found (catch-all) | 404 | ❌ No |
| `VALIDATION_ERROR` | `Exception` | Validation logic failed unexpectedly | 500 | ⚠️ Maybe |

### Azure Exception Hierarchy

```python
azure.core.exceptions.ResourceNotFoundError
    ↓ (inherits from)
azure.core.exceptions.HttpResponseError
    ↓ (inherits from)
azure.core.exceptions.AzureError
```

### Message Format Convention

**Format**: `"<What> '<specific_value>' <issue> in <where> '<location>' (storage account: '<account>'). <Actionable_guidance>."`

**Examples**:
- Container: `"Container 'X' does not exist in storage account 'Y'. Verify spelling."`
- File: `"File 'X' not found in existing container 'Y' (storage account: 'Z'). Verify path."`
- Collection: `"Collection validation failed: N file(s) not found in existing container 'X'..."`

---

## 4. Implementation Checklist

### Phase 1: Job Submission Validation (Priority: HIGH)

**Files to Update**:
- [ ] `jobs/process_raster.py` → `validate_job_parameters()`
- [ ] `jobs/process_raster_collection.py` → `validate_job_parameters()`

**Changes**:
- [ ] Import `ResourceNotFoundError` from `azure.core.exceptions`
- [ ] Import `BlobRepository` from `infrastructure.blob`
- [ ] Add `container_exists()` check with explicit error message
- [ ] Add `blob_exists()` check with explicit error message (includes storage account name)
- [ ] For collections: validate ALL blobs, report missing ones
- [ ] Update docstrings with `Raises: ResourceNotFoundError` documentation

**Expected Behavior**:
- [ ] Job submission with missing container → Fail in <1s with "Container 'X' does not exist" message
- [ ] Job submission with missing blob → Fail in <1s with "File 'X' not found in existing container 'Y'" message
- [ ] Collection with missing blobs → Fail in <1s with list of all missing files

### Phase 2: Stage 1 Validation Enhancement (Priority: MEDIUM)

**Files to Update**:
- [ ] `services/raster_validation.py` → `validate_raster()` handler

**Changes**:
- [ ] Add STEP 3a: Pre-flight blob validation before GDAL open
- [ ] Check `container_exists()` → return `CONTAINER_NOT_FOUND` error
- [ ] Check `blob_exists()` → return `FILE_NOT_FOUND` error
- [ ] Add `error_type: "ResourceNotFoundError"` field to error responses
- [ ] Add `storage_account` field to error responses
- [ ] Add `suggestion` field with actionable guidance
- [ ] Catch `ResourceNotFoundError` from blob_repo methods

**Expected Behavior**:
- [ ] Validation task with missing container → Return `CONTAINER_NOT_FOUND` error before GDAL attempt
- [ ] Validation task with missing blob → Return `FILE_NOT_FOUND` error before GDAL attempt
- [ ] GDAL errors for corrupt/wrong format files → Still return `FILE_UNREADABLE` (unchanged)

### Phase 3: Error Handling Updates (Priority: MEDIUM)

**Files to Update**:
- [ ] Task retry logic (if centralized)
- [ ] API error response handlers
- [ ] CoreMachine task failure handling

**Changes**:
- [ ] Add `CONTAINER_NOT_FOUND` to non-retryable errors list
- [ ] Add `FILE_NOT_FOUND` to non-retryable errors list
- [ ] Update API responses to handle `ResourceNotFoundError` exceptions
- [ ] Update HTTP status codes: `CONTAINER_NOT_FOUND` → 404, `FILE_NOT_FOUND` → 404

### Phase 4: Testing (Priority: HIGH)

**Unit Tests**:
```python
from azure.core.exceptions import ResourceNotFoundError
import pytest

def test_validate_missing_container():
    """Job submission should raise Azure ResourceNotFoundError for missing container"""
    params = {"blob_name": "test.tif", "container_name": "nonexistent"}

    with pytest.raises(ResourceNotFoundError) as exc_info:
        ProcessRasterWorkflow.validate_job_parameters(params)

    assert "Container 'nonexistent' does not exist" in str(exc_info.value)
    assert "storage account" in str(exc_info.value)

def test_validate_missing_blob():
    """Job submission should raise Azure ResourceNotFoundError for missing blob"""
    params = {"blob_name": "missing.tif", "container_name": "rmhazuregeobronze"}

    with pytest.raises(ResourceNotFoundError) as exc_info:
        ProcessRasterWorkflow.validate_job_parameters(params)

    assert "File 'missing.tif' not found in existing container" in str(exc_info.value)

def test_validate_collection_partial_missing():
    """Collection validation should report ALL missing blobs"""
    params = {
        "blob_list": ["exists1.tif", "missing1.tif", "exists2.tif", "missing2.tif"],
        "container_name": "rmhazuregeobronze",
        "collection_id": "test-collection"
    }

    with pytest.raises(ResourceNotFoundError) as exc_info:
        ProcessRasterCollectionWorkflow.validate_job_parameters(params)

    assert "2 file(s) not found" in str(exc_info.value)
    assert "missing1.tif" in str(exc_info.value)
    assert "missing2.tif" in str(exc_info.value)
```

**Integration Tests**:
```bash
# Test 1: Container doesn't exist
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif", "container_name": "nonexistent"}'

# Expected: HTTP 404
{
  "error": "ResourceNotFoundError",
  "message": "Container 'nonexistent' does not exist in storage account 'rmhazuregeo'. Verify container name spelling or create container before submitting job."
}

# Test 2: File doesn't exist
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "missing.tif", "container_name": "rmhazuregeobronze"}'

# Expected: HTTP 404
{
  "error": "ResourceNotFoundError",
  "message": "File 'missing.tif' not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'). Verify blob path spelling. Available blobs can be listed via /api/containers/rmhazuregeobronze/blobs endpoint."
}

# Test 3: Correct submission (should succeed)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "sample_drone.tif", "container_name": "rmhazuregeobronze"}'

# Expected: HTTP 200
{
  "job_id": "abc123...",
  "status": "QUEUED",
  "message": "Job submitted successfully"
}
```

### Phase 5: Documentation (Priority: LOW)

- [ ] Update API documentation with new error codes
- [ ] Add error code reference to developer docs
- [ ] Document blob validation flow in architecture docs
- [ ] Update user-facing error message guide

---

## 5. Performance Impact

### Job Submission Overhead

| Operation | API Calls | Latency | When |
|-----------|-----------|---------|------|
| `container_exists()` | 1 Azure API call | ~50ms | Every job submission |
| `blob_exists()` | 1 Azure API call | ~50ms | Every job submission |
| **Total** | **2 Azure API calls** | **~100ms** | **Every job submission** |

**Trade-off Analysis**:
- ✅ **Successful jobs**: +100ms overhead (negligible for multi-minute workflows)
- ✅ **Failed jobs**: Save 30+ seconds (no task retries, no queue processing)
- ✅ **Net benefit**: 30,000% improvement for failed jobs

### Stage 1 Task Overhead

| Operation | API Calls | Latency | When |
|-----------|-----------|---------|------|
| STEP 3a validation | 2 Azure API calls | ~100ms | Before GDAL open |
| **Total** | **2 Azure API calls** | **~100ms** | **Every validation task** |

**Trade-off Analysis**:
- ✅ **Stage 1 already takes 5-10 seconds** (GDAL + metadata extraction)
- ✅ **100ms = 1-2% overhead** (negligible)
- ✅ **Clear error messages** vs cryptic GDAL errors (high value)

---

## 6. Backward Compatibility

### Breaking Changes: NONE ✅

**Reason**: Validation adds **earlier failure detection**. Jobs that would succeed still succeed, jobs that would fail just fail faster with better errors.

### API Contract: UNCHANGED ✅

**Job Submission Response**:
- Same JSON structure
- Same HTTP status codes (200 success, 400/404 error)
- More specific error messages (improvement, not breaking change)

**Task Result Response**:
- Same `{"success": bool, "error": str, "message": str}` structure
- New fields (`error_type`, `storage_account`, `suggestion`) are additive

### Deployment Risk: LOW ✅

- No database schema changes
- No queue message format changes
- Uses existing `BlobRepository` methods (production-tested since 28 OCT 2025)
- Existing decorators already in production use

---

## 7. Success Metrics

### Before Implementation

- **Time to failure (missing blob)**: 30+ seconds (3 retries × 10s each)
- **Error message**: `"FILE_UNREADABLE: Cannot open raster file: /vsiaz/container/blob: No such file or directory"`
- **User knows**: File failed to open
- **User doesn't know**: Whether file exists, exact path, how to fix

### After Implementation

- **Time to failure (missing blob)**: <1 second (immediate validation)
- **Error message**: `"File 'wrong_path.tif' not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'). Verify blob path spelling. Available blobs can be listed via /api/containers/rmhazuregeobronze/blobs endpoint."`
- **User knows**: Exact file path, exact container, storage account, how to fix

### KPIs

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Time to failure | 30s | <1s | **30x faster** |
| Error specificity | Generic | Explicit | **Clear file/container names** |
| Actionable guidance | None | Yes | **List blobs endpoint suggested** |
| Task retry waste | 3 retries | 0 retries | **100% elimination** |
| User confusion | High | Low | **Self-service debugging** |

---

## 8. Rollout Plan

### Week 1: Phase 1 Implementation
- Implement job submission validation (process_raster + process_raster_collection)
- Unit tests for validation logic
- Deploy to dev environment
- Test with known missing blobs/containers
- Monitor for false positives

### Week 2: Phase 2 Implementation
- Implement Stage 1 validation enhancement (raster_validation.py)
- Update error codes and retry logic
- Integration tests
- Deploy to dev environment
- Monitor task failure rates (should decrease)

### Week 3: Production Deployment
- Deploy to production
- Monitor job submission errors (should increase for invalid inputs - good!)
- Monitor task failures (should decrease overall)
- Collect user feedback on error message clarity
- Document lessons learned

---

## 9. Implementation Code Templates

### Template 1: Single File Validation (process_raster.py)

```python
# Add to top of validate_job_parameters()
from azure.core.exceptions import ResourceNotFoundError
from infrastructure.blob import BlobRepository

# After existing validation...
blob_repo = BlobRepository.instance()
container_name = validated.get("container_name")
blob_name = validated["blob_name"]

# Validate container
if not blob_repo.container_exists(container_name):
    raise ResourceNotFoundError(
        f"Container '{container_name}' does not exist in storage account "
        f"'{blob_repo.account_name}'. Verify container name spelling or create "
        f"container before submitting job."
    )

# Validate blob
if not blob_repo.blob_exists(container_name, blob_name):
    raise ResourceNotFoundError(
        f"File '{blob_name}' not found in existing container '{container_name}' "
        f"(storage account: '{blob_repo.account_name}'). Verify blob path spelling. "
        f"Available blobs can be listed via /api/containers/{container_name}/blobs endpoint."
    )
```

### Template 2: Collection Validation (process_raster_collection.py)

```python
# Add to validate_job_parameters()
from azure.core.exceptions import ResourceNotFoundError
from infrastructure.blob import BlobRepository

# After existing validation...
blob_repo = BlobRepository.instance()
container_name = validated["container_name"]
blob_list = validated["blob_list"]

# Validate container
if not blob_repo.container_exists(container_name):
    raise ResourceNotFoundError(
        f"Container '{container_name}' does not exist in storage account "
        f"'{blob_repo.account_name}'. Verify container name spelling."
    )

# Validate ALL blobs (accumulate missing ones)
missing_blobs = []
for blob_name in blob_list:
    if not blob_repo.blob_exists(container_name, blob_name):
        missing_blobs.append(blob_name)

if missing_blobs:
    missing_list = "\n  - ".join(missing_blobs)
    raise ResourceNotFoundError(
        f"Collection validation failed: {len(missing_blobs)} file(s) not found in "
        f"existing container '{container_name}' (storage account: '{blob_repo.account_name}'):\n"
        f"  - {missing_list}\n\n"
        f"Verify blob paths or use /api/containers/{container_name}/blobs to list available files."
    )
```

### Template 3: Stage 1 Pre-Flight Check (raster_validation.py)

```python
# Add after STEP 2 (lazy imports), before STEP 3 (GDAL open)

# STEP 3a: Pre-flight blob validation
try:
    logger.info("🔄 STEP 3a: Pre-flight blob validation...")

    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.instance()

    container_name = params.get('container_name')
    blob_name = params.get('blob_name')

    # Check container
    if not blob_repo.container_exists(container_name):
        error_msg = (
            f"Container '{container_name}' does not exist in storage account "
            f"'{blob_repo.account_name}'"
        )
        logger.error(f"❌ STEP 3a FAILED: {error_msg}")
        return {
            "success": False,
            "error": "CONTAINER_NOT_FOUND",
            "error_type": "ResourceNotFoundError",
            "message": error_msg,
            "container_name": container_name,
            "storage_account": blob_repo.account_name,
            "blob_name": blob_name
        }

    # Check blob
    if not blob_repo.blob_exists(container_name, blob_name):
        error_msg = (
            f"File '{blob_name}' not found in existing container '{container_name}' "
            f"(storage account: '{blob_repo.account_name}')"
        )
        logger.error(f"❌ STEP 3a FAILED: {error_msg}")
        return {
            "success": False,
            "error": "FILE_NOT_FOUND",
            "error_type": "ResourceNotFoundError",
            "message": error_msg,
            "blob_name": blob_name,
            "container_name": container_name,
            "storage_account": blob_repo.account_name,
            "suggestion": f"Verify blob path spelling. Use /api/containers/{container_name}/blobs to list available files."
        }

    logger.info("✅ STEP 3a: Blob exists validation passed")

except Exception as e:
    logger.error(f"❌ STEP 3a FAILED: Validation error: {e}")
    return {
        "success": False,
        "error": "VALIDATION_ERROR",
        "message": f"Failed to validate blob existence: {e}"
    }
```

---

## 10. Open Questions & Decisions

### Q1: Should we validate SAS token permissions in addition to existence?

**Decision**: ❌ **Out of scope**
**Reason**: Different error type (permission vs existence). SAS token errors are caught by GDAL with clear "Access Denied" messages.

### Q2: Should we batch validate all blobs in collections (parallel validation)?

**Decision**: ⚠️ **Future optimization**
**Reason**: Current sequential validation is fine for <100 tiles. If collections grow to 1000+ tiles, implement parallel validation with `concurrent.futures`.

### Q3: What if blob is deleted between validation and task execution?

**Decision**: ✅ **Acceptable race condition**
**Reason**: Stage 1 will catch it with `FILE_NOT_FOUND` error. Job fails cleanly with clear message. No retry waste (non-retryable error).

### Q4: Should we add container/blob existence to health endpoint?

**Decision**: ❌ **No**
**Reason**: Health endpoint checks system status (database, Azure connection), not user data integrity.

---

## Summary

**Implementation Effort**: 2-3 days (all phases)
**Risk Level**: Low (uses existing production-tested infrastructure)
**Impact**: High (30x faster failure detection, crystal-clear error messages)
**Breaking Changes**: None (backward compatible)
**Recommendation**: ✅ **Proceed with implementation immediately**

**Next Action**: Implement Phase 1 (Job Submission Validation) first - highest impact, lowest risk.