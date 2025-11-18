# Raster Validation - Quick Reference Card

**Author**: Robert and Geospatial Claude Legion
**Date**: 11 NOV 2025

---

## ⚡ What We're Implementing

**Problem**: Jobs fail 30+ seconds later with cryptic GDAL errors when container/blob doesn't exist

**Solution**: Immediate fail-fast validation with explicit Azure exceptions

---

## 🎯 Key Changes

### 1. Job Submission (Process Raster)

**File**: `jobs/process_raster.py` → `validate_job_parameters()`

**Add**:
```python
from azure.core.exceptions import ResourceNotFoundError
from infrastructure.blob import BlobRepository

blob_repo = BlobRepository.instance()

# Validate container
if not blob_repo.container_exists(container_name):
    raise ResourceNotFoundError(
        f"Container '{container_name}' does not exist in storage account "
        f"'{blob_repo.account_name}'. Verify container name spelling."
    )

# Validate blob
if not blob_repo.blob_exists(container_name, blob_name):
    raise ResourceNotFoundError(
        f"File '{blob_name}' not found in existing container '{container_name}' "
        f"(storage account: '{blob_repo.account_name}'). Verify blob path spelling."
    )
```

### 2. Job Submission (Process Raster Collection)

**File**: `jobs/process_raster_collection.py` → `validate_job_parameters()`

**Add**:
```python
# Validate ALL blobs in collection
missing_blobs = []
for blob_name in blob_list:
    if not blob_repo.blob_exists(container_name, blob_name):
        missing_blobs.append(blob_name)

if missing_blobs:
    missing_list = "\n  - ".join(missing_blobs)
    raise ResourceNotFoundError(
        f"Collection validation failed: {len(missing_blobs)} file(s) not found:\n  - {missing_list}"
    )
```

### 3. Stage 1 Validation Enhancement

**File**: `services/raster_validation.py` → `validate_raster()` (after STEP 2, before STEP 3)

**Add STEP 3a**:
```python
# Check container
if not blob_repo.container_exists(container_name):
    return {
        "success": False,
        "error": "CONTAINER_NOT_FOUND",
        "message": f"Container '{container_name}' does not exist..."
    }

# Check blob
if not blob_repo.blob_exists(container_name, blob_name):
    return {
        "success": False,
        "error": "FILE_NOT_FOUND",
        "message": f"File '{blob_name}' not found in existing container '{container_name}'..."
    }
```

---

## 📋 Error Messages

### Container Missing
```
ResourceNotFoundError: Container 'rmhazuregeobronze' does not exist in storage account 'rmhazuregeo'. Verify container name spelling or create container before submitting job.
```

### File Missing
```
ResourceNotFoundError: File 'wrong_path.tif' not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'). Verify blob path spelling. Available blobs can be listed via /api/containers/rmhazuregeobronze/blobs endpoint.
```

### Collection Missing Blobs
```
ResourceNotFoundError: Collection validation failed: 3 file(s) not found in existing container 'rmhazuregeobronze' (storage account: 'rmhazuregeo'):
  - tile_001.tif
  - tile_042.tif
  - tile_103.tif

Verify blob paths or use /api/containers/rmhazuregeobronze/blobs to list available files.
```

---

## 🔢 Error Codes

| Code | Meaning | When | Retry? |
|------|---------|------|--------|
| `CONTAINER_NOT_FOUND` | Container doesn't exist | Container name wrong | ❌ No |
| `FILE_NOT_FOUND` | Blob doesn't exist | Blob path wrong | ❌ No |
| `FILE_UNREADABLE` | GDAL can't open | File corrupt/wrong format | ⚠️ Maybe |

---

## ✅ Testing Commands

```bash
# Test 1: Missing container
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif", "container_name": "nonexistent"}'

# Expected: HTTP 404, "Container 'nonexistent' does not exist"

# Test 2: Missing file
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "missing.tif", "container_name": "rmhazuregeobronze"}'

# Expected: HTTP 404, "File 'missing.tif' not found in existing container"

# Test 3: Success case
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "sample_drone.tif", "container_name": "rmhazuregeobronze"}'

# Expected: HTTP 200, job queued successfully
```

---

## 📊 Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Time to failure** | 30s | <1s | **30x faster** |
| **Error clarity** | Generic GDAL | Explicit Azure | **Clear file/container** |
| **Retries wasted** | 3 | 0 | **100% eliminated** |
| **User knows how to fix** | No | Yes | **Actionable guidance** |

---

## 🚀 Implementation Priority

1. ✅ **Phase 1**: Job submission validation (process_raster + process_raster_collection)
2. ✅ **Phase 2**: Stage 1 validation enhancement (raster_validation.py)
3. ⏳ **Phase 3**: Error handling updates (retry logic, API responses)
4. ⏳ **Phase 4**: Testing (unit + integration)
5. ⏳ **Phase 5**: Documentation

**Start here**: Phase 1 - Highest impact, lowest risk

---

## 💡 Key Decisions

- ✅ Use `azure.core.exceptions.ResourceNotFoundError` (Azure-native)
- ✅ Include storage account name in all error messages
- ✅ Validate ALL blobs in collections (report all missing, not just first)
- ✅ Add explicit suggestion text (`"Use /api/containers/X/blobs to list files"`)
- ✅ No backward compatibility issues (jobs that succeed still succeed)
- ✅ 100ms overhead acceptable (saves 30+ seconds on failures)

---

**Full Implementation Guide**: See `RASTER_VALIDATION_IMPLEMENTATION_PLAN.md`