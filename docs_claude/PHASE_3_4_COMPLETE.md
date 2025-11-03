# Phase 3-4 Migration Complete

**Date**: 02 NOV 2025
**Status**: ✅ COMPLETE - All raster workflow default values migrated
**Time**: ~10 minutes

---

## Summary

Successfully migrated all raster workflow files from deprecated container name pattern to new multi-account storage pattern.

**Total Changes**: 11 references across 5 files
- **Code changes**: 6 (actual default values)
- **Comment/Docstring changes**: 5 (documentation)

---

## Files Modified

### Phase 3: validate_raster_job.py ✅
**Changes**: 3 (1 code + 2 comments)

| Line | Type | Change |
|------|------|--------|
| 72 | Comment | Schema description updated |
| 93 | Docstring | Parameter documentation updated |
| 183 | **Code** | Default container value updated |

**Pattern**:
```python
# OLD
config.bronze_container_name

# NEW
config.storage.bronze.get_container('rasters')
```

---

### Phase 4: Raster Processing Files ✅

#### 1. process_raster.py
**Changes**: 4 (2 code + 2 comments)

| Line | Type | Stage | Change |
|------|------|-------|--------|
| 86 | Comment | N/A | Schema description updated |
| 130 | Docstring | N/A | Parameter documentation updated |
| 395 | **Code** | Stage 1 | Validation default container |
| 442 | **Code** | Stage 2 | COG creation default container |

**Pattern** (same as Phase 3):
```python
# OLD
config.bronze_container_name

# NEW
config.storage.bronze.get_container('rasters')
```

---

#### 2. process_raster_collection.py
**Changes**: 2 (1 code + 1 comment)

| Line | Type | Change |
|------|------|--------|
| 134 | Comment | Schema description updated |
| 230 | **Code** | Default container assignment |

**Pattern** (same as Phase 3):
```python
# OLD
config.bronze_container_name

# NEW
config.storage.bronze.get_container('rasters')
```

---

#### 3. raster_cog.py
**Changes**: 1 (code only)

| Line | Type | Change |
|------|------|--------|
| 261 | **Code** | Silver output container |

**Pattern** (silver tier - NEW):
```python
# OLD
config.silver_container_name

# NEW
config.storage.silver.get_container('cogs')
```

**Note**: This is the **output** container where processed COGs are uploaded (silver tier, not bronze).

---

#### 4. health.py
**Changes**: 1 (code only)

| Line | Type | Change |
|------|------|--------|
| 1071 | **Code** | GDAL test container |

**Pattern** (same as Phase 3):
```python
# OLD
config.bronze_container_name

# NEW
config.storage.bronze.get_container('rasters')
```

**Note**: This is for the GDAL health check test using dctest3_R1C2.tif.

---

## Container Mapping Applied

### Bronze Tier (Input - Raw Rasters)
```python
config.storage.bronze.get_container('rasters')
# Returns: "bronze-rasters"
```

**Used in**:
- `validate_raster_job.py` - Read raw rasters for validation
- `process_raster.py` - Read raw rasters for processing (both stages)
- `process_raster_collection.py` - Read raw rasters from collection
- `health.py` - GDAL test raster

### Silver Tier (Output - Processed COGs)
```python
config.storage.silver.get_container('cogs')
# Returns: "silver-cogs"
```

**Used in**:
- `raster_cog.py` - Write processed COG outputs

---

## Verification

### Syntax Check ✅
```bash
python3 -m py_compile jobs/validate_raster_job.py
python3 -m py_compile jobs/process_raster.py
python3 -m py_compile jobs/process_raster_collection.py
python3 -m py_compile services/raster_cog.py
python3 -m py_compile triggers/health.py
```

**Result**: ✅ All files compile successfully

---

## Testing Commands

### Test validate_raster_job
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "dctest3_R1C2.tif"}'

# Expected: Job reads from bronze-rasters container
```

### Test Health Check (GDAL)
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Expected: GDAL test passes using bronze-rasters container
```

### Test process_raster
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest3_R1C2.tif",
    "output_tier": "analysis"
  }'

# Expected:
# - Stage 1: Reads from bronze-rasters
# - Stage 2: Writes COG to silver-cogs
```

### Test process_raster_collection
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection \
  -H "Content-Type: application/json" \
  -d '{
    "blob_prefix": "test/",
    "output_tier": "analysis"
  }'

# Expected: Reads collection from bronze-rasters
```

---

## Backward Compatibility

✅ **Maintained**: Deprecated fields still present in config.py:
- `config.bronze_container_name`
- `config.silver_container_name`
- `config.gold_container_name`

These will be removed in **Phase 6** after all code is migrated.

---

## Migration Status

### Completed ✅
- ✅ Phase 0: Gold tier support added
- ✅ Phase 1: Documentation comments updated
- ✅ Phase 2: H3 handlers migrated
- ✅ **Phase 3: Raster validation migrated**
- ✅ **Phase 4: Raster processing migrated**

### Remaining
- ⏸️ Phase 5: Large raster pipeline (process_large_raster.py - 6 references)
- ⏸️ Phase 6: Remove deprecated fields (after Phase 5 complete)

---

## Remaining Deprecated References

After Phase 3-4, only **Phase 5** remains:

**File**: `jobs/process_large_raster.py`
**References**: 6 total

| Line | Type | Usage |
|------|------|-------|
| 135 | Comment | Schema description |
| 472 | Code | Stage 1 input container |
| 482 | Code | Stage 1 output container |
| 499 | Code | Stage 2 input container |
| 508 | Code | Stage 2 tiling scheme container |
| 634 | Code | Stage 3 COG output container |

**Complexity**: High - Multi-stage job, recently updated (02 NOV 2025)

**Recommended**: Coordinate with author before Phase 5 migration due to recent changes.

---

## Success Criteria Met

✅ All Phase 3-4 references migrated
✅ All files compile without errors
✅ Backward compatibility maintained
✅ New pattern consistently applied:
   - Bronze inputs: `config.storage.bronze.get_container('rasters')`
   - Silver outputs: `config.storage.silver.get_container('cogs')`

---

## Next Steps

### Option 1: Deploy and Test Now
```bash
# Deploy Phase 0-4 changes
func azure functionapp publish rmhgeoapibeta --python --build remote

# Test health check
curl .../api/health

# Test raster workflows
curl -X POST .../api/jobs/submit/validate_raster_job -d '{"blob_name": "test.tif"}'
curl -X POST .../api/jobs/submit/process_raster -d '{"blob_name": "test.tif", "output_tier": "analysis"}'
```

### Option 2: Continue to Phase 5
- Migrate `process_large_raster.py` (6 references)
- Test large raster tiling workflow
- Complete full migration (Phase 0-5)
- Then deploy all at once

### Option 3: Pause and Review
- Review Phase 0-4 changes
- Test in staging environment first
- Proceed to Phase 5 after validation

---

**Status**: ✅ Phase 3-4 COMPLETE - Ready for deployment or Phase 5

