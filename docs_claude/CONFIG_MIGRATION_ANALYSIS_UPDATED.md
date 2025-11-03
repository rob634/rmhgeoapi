# Configuration Migration Analysis - UPDATED AFTER REVIEW

**Date**: 02 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Updated analysis after reviewing current codebase state

## Executive Summary - Revised

**IMPORTANT FINDINGS**:
1. ✅ **H3 handlers ARE actively used** - Registered in `jobs/__init__.py` and `services/__init__.py`
2. ⚠️ **Gold tier IS actively used** by H3 workflows (lines 77, 102 in handlers)
3. ⚠️ **All raster workflows still use deprecated container patterns**
4. 📊 **Total deprecated references**: 15 files, 23+ usages

---

## Active Job Registrations (jobs/__init__.py)

### **Registered Jobs Using Deprecated Patterns**:

1. ✅ **`create_h3_base`** - CreateH3BaseJob (line 94)
   - **Handler**: `h3_base_generate` (line 114 in services/__init__.py)
   - **Uses**: `config.gold_container_name` (services/handler_h3_base.py:77)
   - **Status**: ACTIVE, needs migration

2. ✅ **`generate_h3_level4`** - GenerateH3Level4Job (line 93)
   - **Handler**: `h3_level4_generate` (line 113 in services/__init__.py)
   - **Uses**: `config.gold_container_name` (services/handler_h3_level4.py:102)
   - **Status**: ACTIVE, needs migration

3. ✅ **`validate_raster_job`** - ValidateRasterJob (line 89)
   - **Handler**: `validate_raster` (line 111 in services/__init__.py)
   - **Uses**: `config.bronze_container_name` (3 references)
   - **Status**: ACTIVE, needs migration

4. ✅ **`process_raster`** - ProcessRasterWorkflow (line 90)
   - **Handler**: `create_cog` (line 112 in services/__init__.py)
   - **Uses**: `config.bronze_container_name`, `config.silver_container_name` (4 references)
   - **Last Updated**: 01 NOV 2025 (line 6 header)
   - **Status**: ACTIVE, recently updated, needs migration

5. ✅ **`process_large_raster`** - ProcessLargeRasterWorkflow (line 92)
   - **Handlers**: `generate_tiling_scheme` (line 123), `extract_tiles` (line 124)
   - **Uses**: `config.bronze_container_name`, `config.silver_container_name` (6 references)
   - **Last Updated**: 02 NOV 2025 (recent changes noted)
   - **Status**: ACTIVE, recently updated, needs migration

6. ✅ **`process_raster_collection`** - ProcessRasterCollectionWorkflow (line 91)
   - **Handler**: `create_mosaicjson`, `create_stac_collection`
   - **Uses**: `config.bronze_container_name` (2 references)
   - **Status**: ACTIVE, needs migration

---

## Critical Issue: Gold Tier in Active Use ⚠️

### **Problem Statement**
The gold tier is **NOT deprecated in practice** - it's actively used by:
- `create_h3_base` job (generates H3 base grids at resolutions 0-4)
- `generate_h3_level4` job (generates H3 level 4 grids)

### **Current Gold Tier Usage**
```python
# services/handler_h3_base.py:77
h3_service = H3GridService(
    duckdb_repo=duckdb_repo,
    blob_repo=blob_repo,
    gold_container=config.gold_container_name  # ACTIVE USE!
)
```

### **What H3 Handlers Output**
- **Data Type**: GeoParquet files (not GeoJSON!)
- **File Size**: 288,122 cells at resolution 4
- **Purpose**: Analytical grid system for hexagonal binning
- **Storage Pattern**: `gold_container/h3_grids/h3_res{X}_{config}.parquet`
- **Use Case**: Data aggregation, spatial indexing, analytics

### **Why Gold Makes Sense for H3**
1. ✅ **Analytics-ready format** (GeoParquet)
2. ✅ **Not raw data** (Bronze) or processed imagery (Silver)
3. ✅ **Reference grids** used by other analytics workflows
4. ✅ **DuckDB/analytical query optimization**

### **Resolution: Keep Gold Tier** ✅

**Recommendation**: Do NOT deprecate gold tier - it serves a legitimate purpose!

**Updated Trust Zone Pattern**:
```
Bronze: Untrusted raw uploads (vectors, rasters)
Silver: Trusted processed geospatial data (COGs, vectors in PostGIS)
Gold: Analytics-ready exports (GeoParquet, optimized for querying)
```

**Action Required**: Add gold tier to new multi-account storage pattern

---

## Updated Container Mapping

### **Bronze Tier (Untrusted Raw Data)**
```python
# OLD
config.bronze_container_name  # "rmhazuregeobronze"

# NEW
config.storage.bronze.get_container('rasters')  # "bronze-rasters"
config.storage.bronze.get_container('vectors')  # "bronze-vectors"
```

### **Silver Tier (Trusted Processed Data)**
```python
# OLD
config.silver_container_name  # "rmhazuregeosilver"

# NEW
config.storage.silver.get_container('cogs')       # "silver-cogs"
config.storage.silver.get_container('vectors')    # "silver-vectors"
config.storage.silver.get_container('tiles')      # "silver-tiles"
config.storage.silver.get_container('mosaicjson') # "silver-mosaicjson"
```

### **Gold Tier (Analytics-Ready Exports)** ✅ KEEP!
```python
# OLD
config.gold_container_name  # "rmhazuregeogold"

# NEW (ADD TO CONFIG!)
config.storage.gold.get_container('geoparquet')  # "gold-geoparquet"
config.storage.gold.get_container('h3_grids')    # "gold-h3-grids"
config.storage.gold.get_container('analytics')   # "gold-analytics"
```

---

## Required Changes to config.py

### **Add Gold Account to MultiAccountStorageConfig**

```python
class MultiAccountStorageConfig(BaseModel):
    """Multi-account storage configuration for trust zones."""

    bronze: StorageAccountConfig = Field(...)  # Existing
    silver: StorageAccountConfig = Field(...)  # Existing
    silverext: StorageAccountConfig = Field(...)  # Existing

    # ADD THIS:
    gold: StorageAccountConfig = Field(
        default_factory=lambda: StorageAccountConfig(
            account_name=os.getenv("STORAGE_ACCOUNT_NAME", "rmhazuregeo"),
            container_prefix="gold",
            # Analytics containers
            vectors="gold-notused",     # Not used for vectors (use silver)
            rasters="gold-notused",     # Not used for rasters (use silver COGs)
            cogs="gold-notused",        # Not used for COGs (use silver)
            tiles="gold-notused",       # Not used for tiles (use silver)
            mosaicjson="gold-notused",  # Not used for MosaicJSON (use silver)
            stac_assets="gold-notused", # Not used for STAC (use silver)
            misc="gold-misc",           # Misc analytics files
            temp="gold-temp",           # Temp analytics processing
        )
    )

    def get_account(self, zone: str) -> StorageAccountConfig:
        if zone == "bronze":
            return self.bronze
        elif zone == "silver":
            return self.silver
        elif zone == "silverext":
            return self.silverext
        elif zone == "gold":  # ADD THIS
            return self.gold
        else:
            raise ValueError(f"Unknown storage zone: {zone}")
```

### **Add Gold-Specific Container Purposes**

Add new fields to `StorageAccountConfig` (optional, for gold tier only):

```python
class StorageAccountConfig(BaseModel):
    """Configuration for a single storage account."""

    # ... existing fields ...

    # Gold tier specific (optional - override for gold account)
    geoparquet: Optional[str] = Field(
        default=None,
        description="GeoParquet exports for analytics"
    )
    h3_grids: Optional[str] = Field(
        default=None,
        description="H3 hexagonal grids (GeoParquet)"
    )
    analytics: Optional[str] = Field(
        default=None,
        description="General analytics outputs"
    )
```

---

## Revised Migration Plan

### **Phase 0: Add Gold Tier Support** ⭐ NEW
- [ ] Add `gold` to `MultiAccountStorageConfig` (see code above)
- [ ] Add gold-specific container purposes (`geoparquet`, `h3_grids`, `analytics`)
- [ ] Update `get_account()` to handle "gold" zone
- [ ] Test gold tier access pattern

**Risk**: None (additive only)
**Effort**: 20 minutes
**Testing**: Verify `config.storage.gold.get_container('h3_grids')` works

---

### **Phase 1: Low-Risk Changes (Comments/Docstrings)**
- [ ] Update `infrastructure/stac.py` docstring (line 536)
- [ ] Update `triggers/stac_collections.py` comment (line 75)
- [ ] Update `triggers/stac_extract.py` comment (line 52)

**Risk**: None (documentation only)
**Effort**: 5 minutes

---

### **Phase 2: H3 Handlers Migration** ⭐ HIGH PRIORITY
- [ ] `services/handler_h3_base.py` (line 77)
  ```python
  # OLD
  gold_container=config.gold_container_name

  # NEW
  gold_container=config.storage.gold.get_container('h3_grids')
  ```

- [ ] `services/handler_h3_level4.py` (line 102)
  ```python
  # OLD
  gold_container=config.gold_container_name

  # NEW
  gold_container=config.storage.gold.get_container('h3_grids')
  ```

**Risk**: Medium (active jobs use these)
**Effort**: 10 minutes
**Testing**: Submit `create_h3_base` and `generate_h3_level4` jobs

---

### **Phase 3: Raster Validation Job**
- [ ] `jobs/validate_raster_job.py` (3 references)
  ```python
  # OLD
  container_name = job_params.get('container_name') or config.bronze_container_name

  # NEW
  container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')
  ```

**Risk**: Low (validation only, no data modification)
**Effort**: 15 minutes
**Testing**: Submit `validate_raster_job` with and without container param

---

### **Phase 4: Simple Raster Processing**
- [ ] `jobs/process_raster.py` (4 references)
- [ ] `jobs/process_raster_collection.py` (2 references)
- [ ] `services/raster_cog.py` (1 reference at line 261)
- [ ] `triggers/health.py` (1 reference at line 1071)

**Risk**: Medium (active raster workflows)
**Effort**: 30 minutes
**Testing**: Full raster processing workflow (validate → process → COG)

---

### **Phase 5: Complex Large Raster Pipeline** ⚠️
- [ ] `jobs/process_large_raster.py` (6 references at lines 135, 472, 482, 499, 508, 634)
  - Input containers: `bronze.get_container('rasters')`
  - Intermediate tiles: `silver.get_container('tiles')`
  - Output COGs: `silver.get_container('cogs')`
  - Tiling schemes: `silver.get_container('tiles')` or `silver.get_container('mosaicjson')`

**Risk**: HIGH (complex multi-stage, recently updated 02 NOV 2025)
**Effort**: 1 hour
**Testing**: Full large raster workflow (11GB test file with 204 tiles)

---

### **Phase 6: Remove Deprecated Fields**
After ALL phases complete and tested:

```python
# Remove from AppConfig (config.py lines ~498-514)
bronze_container_name: str = Field(...)  # DELETE
silver_container_name: str = Field(...)  # DELETE
gold_container_name: str = Field(...)    # DELETE

# Remove from from_environment() (config.py lines ~1070-1072)
bronze_container_name=os.environ['BRONZE_CONTAINER_NAME'],  # DELETE
silver_container_name=os.environ['SILVER_CONTAINER_NAME'],  # DELETE
gold_container_name=os.environ['GOLD_CONTAINER_NAME'],      # DELETE
```

**Risk**: CRITICAL (breaking change if any references missed)
**Effort**: 5 minutes
**Testing**: Full regression test suite

---

## Estimated Timeline (Revised)

| Phase | Effort | Risk | Dependencies |
|-------|--------|------|--------------|
| Phase 0 | 20 min | None | None |
| Phase 1 | 5 min | None | Phase 0 |
| Phase 2 | 10 min | Medium | Phase 0 (gold tier) |
| Phase 3 | 15 min | Low | Phase 0 |
| Phase 4 | 30 min | Medium | Phase 3 |
| Phase 5 | 1 hour | **HIGH** | Phase 4, recent changes |
| Phase 6 | 5 min | **CRITICAL** | ALL phases tested |
| **TOTAL** | **2.5 hours** | Mixed | Sequential |

**Reduced from 4 hours** - Gold tier resolution eliminated major uncertainty

---

## Testing Strategy (By Phase)

### **Phase 0: Gold Tier Testing**
```bash
# Python REPL test
python3
>>> from config import get_config
>>> config = get_config()
>>> config.storage.gold.get_container('h3_grids')
'gold-h3-grids'
```

### **Phase 2: H3 Handler Testing**
```bash
# Create H3 base grid (resolution 0 - fast test)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/create_h3_base \
  -H "Content-Type: application/json" \
  -d '{"resolution": 0, "exclude_antimeridian": true}'

# Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Verify output in gold-h3-grids container
```

### **Phase 3-5: Raster Pipeline Testing**
```bash
# Phase 3: Validate raster
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/validate_raster_job \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif"}'

# Phase 4: Process small raster
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.tif", "output_tier": "analysis"}'

# Phase 5: Process large raster (use 11GB test file)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_large_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "large_11gb.tif"}'
```

---

## Key Findings Summary

### **What Changed Since Initial Analysis**
1. ✅ **H3 jobs ARE active** (not deprecated)
2. ✅ **Gold tier IS needed** (analytics-ready GeoParquet exports)
3. ⚠️ **Raster workflows recently updated** (01-02 NOV 2025)
4. ✅ **All jobs properly registered** in explicit registries

### **Scope Reduction**
- **NO LONGER NEEDED**: Business decision on H3 usage (ACTIVE!)
- **NO LONGER NEEDED**: Investigation of gold tier purpose (ANALYTICS!)
- **SIMPLIFIED**: Gold tier mapping is clear (H3 grids, GeoParquet exports)

### **Risk Reduction**
- Phase 2 (H3) is now well-defined (20 min instead of 2 hours investigation)
- Phase 5 still high risk due to recent updates (need careful testing)
- Total timeline reduced 40% (2.5 hours vs 4 hours)

---

## Updated Recommendations

### **Before Production Handoff** ✅
1. ✅ Execute Phase 0 (add gold tier support) - **MUST DO FIRST**
2. ✅ Execute Phases 1-2 (30 min) - Documentation + H3 handlers
3. ✅ Execute Phases 3-4 (45 min) - Raster validation and simple processing
4. ⚠️ Execute Phase 5 (1 hour) - **COORDINATE WITH AUTHOR** (recent updates)
5. ✅ Execute Phase 6 (remove deprecated fields) - After full testing

### **Configuration Patterns for New Code** ✅
```python
# CORRECT - New pattern
config.storage.bronze.get_container('rasters')   # Raw rasters
config.storage.silver.get_container('cogs')      # Processed COGs
config.storage.gold.get_container('h3_grids')    # Analytics grids

# WRONG - Deprecated pattern
config.bronze_container_name  # Will be removed!
config.silver_container_name  # Will be removed!
config.gold_container_name    # Will be removed!
```

---

## Questions RESOLVED ✅

1. ~~**H3 Handlers**: Are they actively used?~~ → **YES**, registered and functional
2. ~~**Gold Tier Deprecation**: Should we remove it?~~ → **NO**, needed for analytics
3. ~~**Migration Timeline**: When to execute?~~ → **2.5 hours, before production**
4. ~~**Breaking Changes**: Remove deprecated fields?~~ → **YES**, after Phase 6 complete

---

**Status**: Analysis updated, ready for migration execution

**Next Step**: Execute Phase 0 (add gold tier to config.storage.*)

