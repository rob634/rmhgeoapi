# Configuration Migration Analysis - Deprecated Container Names

**Date**: 01 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive analysis of deprecated container name usage for production readiness

## Executive Summary

**Current State**: Codebase uses **two parallel configuration patterns** for container names:
- **OLD (Deprecated)**: `config.bronze_container_name`, `config.silver_container_name`, `config.gold_container_name`
- **NEW (Production)**: `config.storage.bronze.get_container('rasters')`, `config.storage.silver.get_container('cogs')`

**Impact**:
- **12 files** still use deprecated pattern (58 total references)
- **1 file** (`infrastructure/blob.py`) successfully migrated to new pattern
- **Migration required** before production handoff to ensure consistency

---

## Deprecated Pattern Usage by File

### **1. jobs/process_large_raster.py** - 7 references ⚠️
**Lines**: 135, 415, 425, 441, 450, 569, 574

**Usage Pattern**:
```python
container_name = job_params["container_name"] or config.bronze_container_name
"output_container": config.silver_container_name
"tiling_scheme_container": config.silver_container_name
"container_name": config.silver_container_name
```

**Migration Strategy**:
- Input containers (raw rasters): `config.storage.bronze.get_container('rasters')`
- Output containers (COGs): `config.storage.silver.get_container('cogs')`
- Tiling schemes: `config.storage.silver.get_container('tiles')`

---

### **2. jobs/process_raster.py** - 4 references ⚠️
**Lines**: 86, 124, 383, 430

**Usage Pattern**:
```python
"container_name": {"type": "str", "required": True, "default": None}  # Uses config.bronze_container_name if None
container_name = job_params.get('container_name') or config.bronze_container_name
```

**Migration Strategy**:
- Replace default: `config.storage.bronze.get_container('rasters')`
- Update docstrings to reference new pattern

---

### **3. jobs/validate_raster_job.py** - 3 references ⚠️
**Lines**: 72, 93, 183

**Usage Pattern**:
```python
"container_name": {"type": "str", "required": True, "default": None}  # Uses config.bronze_container_name if None
container_name = job_params.get('container_name') or config.bronze_container_name
```

**Migration Strategy**:
- Same as process_raster.py
- Bronze tier for raw validation inputs

---

### **4. jobs/process_raster_collection.py** - 2 references ⚠️
**Lines**: 134, 230

**Usage Pattern**:
```python
validated["container_name"] = config.bronze_container_name
```

**Migration Strategy**:
- Replace with: `config.storage.bronze.get_container('rasters')`

---

### **5. services/raster_cog.py** - 1 reference ⚠️
**Line**: 308

**Usage Pattern**:
```python
silver_container = config_obj.silver_container_name
```

**Migration Strategy**:
- Replace with: `config.storage.silver.get_container('cogs')`

---

### **6. services/handler_h3_base.py** - 1 reference ⚠️
**Line**: 77

**Usage Pattern**:
```python
gold_container=config.gold_container_name
```

**Migration Strategy**:
- **PROBLEM**: Gold tier deprecated in trust zone pattern!
- **Options**:
  1. Use `config.storage.silver.get_container('vectors')` (if H3 cells are vector data)
  2. Create new container purpose in silver tier: `h3_cells`
  3. Clarify if H3 handler is still used

---

### **7. services/handler_h3_level4.py** - 1 reference ⚠️
**Line**: 102

**Usage Pattern**:
```python
gold_container=config.gold_container_name
```

**Migration Strategy**:
- Same as handler_h3_base.py
- **Question**: Are H3 handlers actively used?

---

### **8. triggers/health.py** - 1 reference ⚠️
**Line**: 1071

**Usage Pattern**:
```python
test_container = config.bronze_container_name
```

**Migration Strategy**:
- Replace with: `config.storage.bronze.get_container('rasters')`
- Health check should test actual production containers

---

### **9. triggers/stac_collections.py** - 1 reference (comment) ⚠️
**Line**: 75

**Usage Pattern**:
```python
"container": "rmhazuregeobronze",  # Required (use config.bronze/silver/gold_container_name)
```

**Migration Strategy**:
- Update comment to reference new pattern
- Consider replacing hardcoded string with config reference

---

### **10. triggers/stac_extract.py** - 1 reference (comment) ⚠️
**Line**: 52

**Usage Pattern**:
```python
"container": "rmhazuregeobronze",      // Required (use config.bronze_container_name)
```

**Migration Strategy**:
- Update comment to reference new pattern
- Consider replacing hardcoded string with config reference

---

### **11. infrastructure/stac.py** - 1 reference (comment) ⚠️
**Line**: 536

**Usage Pattern**:
```python
container: Azure Storage container name (from config.bronze/silver/gold_container_name)
```

**Migration Strategy**:
- Update docstring comment only
- Reference new pattern in documentation

---

### **12. infrastructure/blob.py** - ✅ ALREADY MIGRATED
**Status**: Successfully using new pattern

**Example**:
```python
self.account_name = account_name or config.storage.silver.account_name
if self.account_name == config.storage.bronze.account_name:
    zone_config = config.storage.bronze
elif self.account_name == config.storage.silver.account_name:
    zone_config = config.storage.silver
```

**Lesson**: This is the reference implementation for migration pattern

---

## Migration Scope Summary

| Category | Count | Complexity |
|----------|-------|------------|
| **Jobs (process_large_raster)** | 7 refs | High - multiple container types |
| **Jobs (process_raster)** | 4 refs | Medium - defaults and docstrings |
| **Jobs (validate_raster)** | 3 refs | Medium - similar to process_raster |
| **Jobs (process_raster_collection)** | 2 refs | Low - simple replacement |
| **Services (raster_cog)** | 1 ref | Low - single assignment |
| **Services (H3 handlers)** | 2 refs | **High - uses deprecated gold tier!** |
| **Triggers (health)** | 1 ref | Low - test container |
| **Triggers (STAC)** | 2 refs | Very Low - comments only |
| **Infrastructure (stac)** | 1 ref | Very Low - docstring only |
| **TOTAL** | **23 files/refs** | Mixed complexity |

---

## Container Mapping Guide

### **Bronze Tier (Untrusted Raw Data)**
```python
# OLD
config.bronze_container_name  # Returns: "rmhazuregeobronze"

# NEW
config.storage.bronze.get_container('rasters')  # Returns: "bronze-rasters"
config.storage.bronze.get_container('vectors')  # Returns: "bronze-vectors"
config.storage.bronze.get_container('misc')     # Returns: "bronze-misc"
```

### **Silver Tier (Trusted Processed Data)**
```python
# OLD
config.silver_container_name  # Returns: "rmhazuregeosilver"

# NEW
config.storage.silver.get_container('cogs')       # Returns: "silver-cogs"
config.storage.silver.get_container('vectors')    # Returns: "silver-vectors"
config.storage.silver.get_container('tiles')      # Returns: "silver-tiles"
config.storage.silver.get_container('mosaicjson') # Returns: "silver-mosaicjson"
```

### **Gold Tier (DEPRECATED in Trust Zone Pattern)**
```python
# OLD
config.gold_container_name  # Returns: "rmhazuregeogold"

# NEW - No direct equivalent!
# Options:
# 1. Use silver tier for processed outputs
# 2. Create new purpose-specific containers in silver
# 3. Re-evaluate if "gold" tier concept is needed
```

---

## Critical Issue: Gold Tier Usage ⚠️

**Problem**: 2 files still reference `config.gold_container_name`:
- `services/handler_h3_base.py` (line 77)
- `services/handler_h3_level4.py` (line 102)

**Impact**:
- Gold tier is **DEPRECATED** in new trust zone pattern
- No equivalent in `config.storage.*` structure
- **H3 handlers will break** if gold tier removed

**Questions for Resolution**:
1. Are H3 handlers actively used in production?
2. What data type do H3 handlers output? (vectors, analytics, etc.)
3. Should H3 output go to silver tier with new purpose?

**Recommended Actions**:
1. **Audit H3 usage**: Check if these handlers are in active use
2. **If active**: Migrate to `config.storage.silver.get_container('h3_cells')` (add new container purpose)
3. **If inactive**: Mark handlers as deprecated and document for future removal

---

## Migration Plan

### **Phase 1: Low-Risk Changes (Comments/Docstrings)**
- [ ] Update `infrastructure/stac.py` docstring (line 536)
- [ ] Update `triggers/stac_collections.py` comment (line 75)
- [ ] Update `triggers/stac_extract.py` comment (line 52)

**Risk**: None (documentation only)
**Effort**: 5 minutes

---

### **Phase 2: Simple Replacements**
- [ ] `triggers/health.py` (line 1071) - test container
- [ ] `jobs/process_raster_collection.py` (lines 134, 230) - defaults
- [ ] `services/raster_cog.py` (line 308) - single assignment

**Risk**: Low (straightforward replacements)
**Effort**: 15 minutes
**Testing**: Run health check, validate_raster, process_raster_collection jobs

---

### **Phase 3: Job Parameter Defaults**
- [ ] `jobs/validate_raster_job.py` (3 references)
- [ ] `jobs/process_raster.py` (4 references)

**Risk**: Medium (affects default behavior)
**Effort**: 30 minutes
**Testing**: Submit jobs with and without explicit container params

---

### **Phase 4: Complex Job (process_large_raster)**
- [ ] `jobs/process_large_raster.py` (7 references)
  - Input container defaults
  - Output container assignments
  - Tiling scheme container
  - Multi-stage container handling

**Risk**: High (complex multi-stage job)
**Effort**: 1 hour
**Testing**: Full end-to-end test with large raster

---

### **Phase 5: H3 Handler Resolution** ⚠️
- [ ] Audit H3 handler usage in production
- [ ] Determine correct container mapping for H3 output
- [ ] Update `services/handler_h3_base.py` (line 77)
- [ ] Update `services/handler_h3_level4.py` (line 102)

**Risk**: **CRITICAL** - gold tier deprecated
**Effort**: 2 hours (includes investigation)
**Blocker**: Need business decision on H3 output storage tier

---

## Testing Strategy

### **Unit Tests** (Per Phase)
```bash
# Phase 2 - Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Phase 2 - Validate raster job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif"}'

# Phase 3 - Process raster job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif"}'

# Phase 4 - Process large raster
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_large_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "large.tif"}'
```

### **Integration Tests**
- Test with explicit container parameter (should override defaults)
- Test without container parameter (should use new defaults)
- Verify blob storage operations succeed with new container names
- Check STAC metadata references correct containers

### **Regression Tests**
- Run full test suite after each phase
- Verify no existing functionality broken
- Check Application Insights for errors

---

## Rollback Plan

### **If Migration Fails**
1. **Git revert** to previous commit (all changes in one branch)
2. **Keep deprecated fields** in config.py temporarily
3. **Add runtime warnings** instead of removing
4. **Document issues** for next migration attempt

### **Compatibility Shim (Emergency)**
```python
# Add to config.py if rollback needed
@property
def bronze_container_name(self) -> str:
    """DEPRECATED: Use storage.bronze.get_container('rasters')"""
    import warnings
    warnings.warn("bronze_container_name deprecated, use storage.bronze", DeprecationWarning)
    return self.storage.bronze.rasters
```

---

## Estimated Timeline

| Phase | Effort | Risk | Dependencies |
|-------|--------|------|--------------|
| Phase 1 | 5 min | None | None |
| Phase 2 | 15 min | Low | None |
| Phase 3 | 30 min | Medium | Phase 2 complete |
| Phase 4 | 1 hour | High | Phase 3 complete |
| Phase 5 | 2 hours | **CRITICAL** | Business decision on H3 |
| **TOTAL** | **4 hours** | Mixed | Sequential |

**Recommended**: Execute Phases 1-4 in one session, defer Phase 5 pending investigation

---

## Success Criteria

✅ All deprecated container name references removed
✅ All jobs use `config.storage.*` pattern consistently
✅ Health checks pass with new container references
✅ End-to-end job workflows succeed
✅ No hardcoded container names in codebase
✅ Documentation updated with new pattern
✅ H3 handler gold tier issue resolved or documented

---

## Post-Migration: Remove Deprecated Fields

**After ALL phases complete**:

```python
# Remove from AppConfig in config.py
# Lines 498-514
bronze_container_name: str = Field(...)  # DELETE
silver_container_name: str = Field(...)  # DELETE
gold_container_name: str = Field(...)    # DELETE
```

**Update `from_environment()` method**:
```python
# Remove these lines from from_environment() (lines 1070-1072)
bronze_container_name=os.environ['BRONZE_CONTAINER_NAME'],  # DELETE
silver_container_name=os.environ['SILVER_CONTAINER_NAME'],  # DELETE
gold_container_name=os.environ['GOLD_CONTAINER_NAME'],      # DELETE
```

**Update environment variables**:
- Can REMOVE from Azure Function App settings (after migration)
- Can REMOVE from `local.settings.json` (after migration)

---

## Recommendations

### **Immediate Actions**
1. ✅ **Execute Phase 1** (5 min) - Update documentation/comments
2. ✅ **Execute Phase 2** (15 min) - Simple replacements
3. ⏸️ **Investigate H3 handlers** - Are they used? What's the output type?

### **Before Production Handoff**
1. ✅ Complete Phases 1-4 (all non-H3 migrations)
2. ⚠️ **Document H3 gold tier issue** if unresolved
3. ✅ Update architecture documentation with new container pattern
4. ✅ Add migration guide for future container additions

### **Configuration Consistency Best Practices**
1. **Never hardcode container names** - always use config
2. **Use `config.storage.*` pattern** for all new code
3. **Add container purposes** to `StorageAccountConfig` when needed
4. **Document container usage** in job parameter schemas

---

## Questions for Discussion

1. **H3 Handlers**: Are `handler_h3_base.py` and `handler_h3_level4.py` actively used?
2. **Gold Tier Deprecation**: Should we completely remove gold tier concept or repurpose?
3. **Migration Timeline**: When should this migration happen? (Before production handoff?)
4. **Breaking Changes**: Are we OK with removing deprecated fields after migration?

---

**Status**: Analysis complete, awaiting decision on migration execution timeline

