# Phase 3-4 Migration Guide - Detailed Change List

**Date**: 02 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Estimated Time**: Phase 3 (15 min) + Phase 4 (30 min) = 45 minutes total

---

## Phase 3: Raster Validation Job (15 minutes)

**File**: `jobs/validate_raster_job.py`
**References**: 3 (2 comments + 1 code)
**Risk**: Low (validation only, no data modification)

### Change 1: Line 72 (Comment in Schema)
```python
# BEFORE
"container_name": {"type": "str", "required": True, "default": None},  # Uses config.bronze_container_name if None

# AFTER
"container_name": {"type": "str", "required": True, "default": None},  # Uses config.storage.bronze.get_container('rasters') if None
```

### Change 2: Line 93 (Docstring)
```python
# BEFORE
        Optional:
            container_name: str - Container name (default: config.bronze_container_name)

# AFTER
        Optional:
            container_name: str - Container name (default: config.storage.bronze.get_container('rasters'))
```

### Change 3: Line 183 (Actual Code)
```python
# BEFORE
        # Use config default if container_name not specified
        container_name = job_params.get('container_name') or config.bronze_container_name

# AFTER
        # Use config default if container_name not specified
        container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')
```

**Context**: Lines 180-184
```python
        config = get_config()

        # Use config default if container_name not specified
        container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')

        # Create Stage 1 task (validation only)
```

**Testing**:
```bash
# Without container_name (should use default)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif"}'

# With explicit container_name (should use provided value)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif", "container_name": "bronze-rasters"}'

# Check job completed successfully
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## Phase 4: Simple Raster Processing (30 minutes)

### File 1: `jobs/process_raster.py` (4 references)

**Change 1: Line 86 (Comment in Schema)**
```python
# BEFORE
"container_name": {"type": "str", "required": True, "default": None},  # Uses config.bronze_container_name if None

# AFTER
"container_name": {"type": "str", "required": True, "default": None},  # Uses config.storage.bronze.get_container('rasters') if None
```

**Change 2: Line 130 (Docstring)**
```python
# BEFORE
        Optional:
            container_name: str - Container name (default: config.bronze_container_name)

# AFTER
        Optional:
            container_name: str - Container name (default: config.storage.bronze.get_container('rasters'))
```

**Change 3: Line 395 (Stage 1 Code)**
```python
# BEFORE
            container_name = job_params.get('container_name') or config.bronze_container_name

# AFTER
            container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')
```

**Context**: Lines 393-397 (Stage 1: Validate Raster)
```python
            config = get_config()

            container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')

            # Stage 1: Validate raster
```

**Change 4: Line 442 (Stage 2 Code)**
```python
# BEFORE
            container_name = job_params.get('container_name') or config.bronze_container_name

# AFTER
            container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')
```

**Context**: Lines 440-444 (Stage 2: Create COG)
```python
            config = get_config()

            container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')

            # Stage 2: Create COG from validated raster
```

---

### File 2: `jobs/process_raster_collection.py` (2 references)

**Change 1: Line 134 (Comment in Schema)**
```python
# BEFORE
            "description": "Source container name (uses config.bronze_container_name if None)"

# AFTER
            "description": "Source container name (uses config.storage.bronze.get_container('rasters') if None)"
```

**Change 2: Line 230 (Code)**
```python
# BEFORE
            validated["container_name"] = config.bronze_container_name

# AFTER
            validated["container_name"] = config.storage.bronze.get_container('rasters')
```

**Context**: Lines 226-234
```python
        if container_name is None:
            # Use config default
            from config import get_config
            config = get_config()
            validated["container_name"] = config.storage.bronze.get_container('rasters')
        else:
            if not isinstance(container_name, str):
                raise ValueError("container_name must be a string")
            validated["container_name"] = container_name
```

---

### File 3: `services/raster_cog.py` (1 reference)

**Change 1: Line 261 (Code)**
```python
# BEFORE
        silver_container = config_obj.silver_container_name

# AFTER
        silver_container = config_obj.storage.silver.get_container('cogs')
```

**Context**: Lines 258-262
```python
        # Get silver container from config
        from config import get_config
        config_obj = get_config()
        silver_container = config_obj.storage.silver.get_container('cogs')

        # Download input tile bytes to memory
```

**Note**: This is the COG output container (where processed COGs are uploaded)

---

### File 4: `triggers/health.py` (1 reference)

**Change 1: Line 1071 (Code)**
```python
# BEFORE
                test_container = config.bronze_container_name

# AFTER
                test_container = config.storage.bronze.get_container('rasters')
```

**Context**: Lines 1068-1075
```python

                # Test with dctest3_R1C2.tif from bronze container
                test_blob = "dctest3_R1C2.tif"
                test_container = config.storage.bronze.get_container('rasters')

                # Generate SAS URL (4 hour expiry for health check stability)
                test_url = blob_repo.get_blob_url_with_sas(
                    container_name=test_container,
```

**Note**: This is for the GDAL health check test - uses a test raster from bronze

---

## Summary of Changes

### Phase 3 (validate_raster_job.py)
- **Line 72**: Update comment (schema)
- **Line 93**: Update docstring
- **Line 183**: Update code (default container)

### Phase 4
**process_raster.py**:
- **Line 86**: Update comment (schema)
- **Line 130**: Update docstring
- **Line 395**: Update code (Stage 1 default)
- **Line 442**: Update code (Stage 2 default)

**process_raster_collection.py**:
- **Line 134**: Update comment (schema)
- **Line 230**: Update code (default container)

**raster_cog.py**:
- **Line 261**: Update code (silver output container)

**health.py**:
- **Line 1071**: Update code (GDAL test container)

---

## Container Mapping Reference

### Input Containers (Bronze - Raw Data)
```python
# OLD
config.bronze_container_name

# NEW
config.storage.bronze.get_container('rasters')
```

**Returns**: `"bronze-rasters"` (currently simulated, same account)

### Output Containers (Silver - Processed Data)
```python
# OLD
config.silver_container_name

# NEW - For COGs
config.storage.silver.get_container('cogs')

# NEW - For Tiles (if needed later)
config.storage.silver.get_container('tiles')

# NEW - For MosaicJSON (if needed later)
config.storage.silver.get_container('mosaicjson')
```

**Returns**: `"silver-cogs"`, `"silver-tiles"`, `"silver-mosaicjson"`

---

## Testing Strategy

### Phase 3 Testing (validate_raster_job)
```bash
# 1. Test with default container (bronze-rasters)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "dctest3_R1C2.tif"}'

# 2. Get job ID from response, check status
JOB_ID="<from_response>"
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/$JOB_ID

# 3. Check tasks completed
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/$JOB_ID

# Expected: Job completes successfully, validation task succeeds
```

### Phase 4 Testing (process_raster, raster_cog, health)

**Test 1: Health Check (GDAL)**
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Expected: All checks pass including GDAL test
# Look for: "gdal_test": {"status": "healthy", ...}
```

**Test 2: Process Small Raster**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest3_R1C2.tif",
    "output_tier": "analysis"
  }'

# Get job ID, check status
JOB_ID="<from_response>"
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/$JOB_ID

# Expected:
# - Stage 1 validates raster from bronze-rasters
# - Stage 2 creates COG in silver-cogs
# - Job completes successfully
```

**Test 3: Process Raster Collection**
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "bronze-rasters",
    "blob_prefix": "test/",
    "output_tier": "analysis"
  }'

# Expected: Collection processed from bronze-rasters
```

---

## Verification Checklist

### Phase 3
- [ ] Line 72 comment updated
- [ ] Line 93 docstring updated
- [ ] Line 183 code updated
- [ ] File compiles (`python3 -m py_compile jobs/validate_raster_job.py`)
- [ ] validate_raster_job submission succeeds
- [ ] Job completes successfully
- [ ] Task reads from bronze-rasters container

### Phase 4
- [ ] process_raster.py: 4 changes applied
- [ ] process_raster_collection.py: 2 changes applied
- [ ] raster_cog.py: 1 change applied
- [ ] health.py: 1 change applied
- [ ] All files compile
- [ ] Health check passes (GDAL test)
- [ ] process_raster job completes successfully
- [ ] COG output appears in silver-cogs container
- [ ] process_raster_collection job works

---

## Rollback Plan

If issues arise during Phase 3-4:

```bash
# Revert changes
git diff HEAD jobs/validate_raster_job.py > phase3.patch
git diff HEAD jobs/process_raster.py jobs/process_raster_collection.py services/raster_cog.py triggers/health.py > phase4.patch

# If needed to rollback
git checkout HEAD jobs/validate_raster_job.py  # Rollback Phase 3
git checkout HEAD jobs/process_raster.py jobs/process_raster_collection.py services/raster_cog.py triggers/health.py  # Rollback Phase 4

# Redeploy
func azure functionapp publish rmhgeoapibeta --python --build remote
```

---

## Risk Assessment

### Phase 3 (Low Risk)
- ✅ Single file (validate_raster_job.py)
- ✅ Validation only (no data modification)
- ✅ 2 of 3 changes are comments/docstrings
- ✅ Easy to test (quick job execution)

### Phase 4 (Medium Risk)
- ⚠️ 4 files modified
- ⚠️ Affects actual data processing (COG creation)
- ⚠️ Health check modification (but low impact)
- ✅ Well-tested pattern (same as Phase 3)
- ✅ Each file independently testable

---

## Estimated Timeline

| Task | Time | Cumulative |
|------|------|------------|
| **Phase 3** | | |
| Update validate_raster_job.py | 5 min | 5 min |
| Test validate job | 5 min | 10 min |
| Verify results | 5 min | 15 min |
| **Phase 4** | | |
| Update process_raster.py | 5 min | 20 min |
| Update process_raster_collection.py | 3 min | 23 min |
| Update raster_cog.py | 2 min | 25 min |
| Update health.py | 2 min | 27 min |
| Deploy to Azure | 5 min | 32 min |
| Test health check | 2 min | 34 min |
| Test process_raster job | 5 min | 39 min |
| Test raster_collection job | 5 min | 44 min |
| Verify COG outputs | 1 min | 45 min |
| **Total** | **45 min** | |

---

## Success Criteria

### Phase 3 Complete When:
- ✅ All 3 references updated in validate_raster_job.py
- ✅ File compiles without errors
- ✅ validate_raster_job submission succeeds
- ✅ Job completes with status="completed"
- ✅ Validation task succeeds

### Phase 4 Complete When:
- ✅ All 8 references updated across 4 files
- ✅ All files compile without errors
- ✅ Health check passes (including GDAL test)
- ✅ process_raster job completes successfully
- ✅ COG appears in silver-cogs container
- ✅ process_raster_collection job works

---

**Ready to Execute**: All changes documented, testing plan ready, rollback plan in place

**Next**: Execute Phase 3, test, then proceed to Phase 4
