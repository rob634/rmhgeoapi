# Phase 5 Analysis - process_large_raster.py

**Date**: 02 NOV 2025
**File**: `jobs/process_large_raster.py`
**References**: 6 total
**Complexity**: HIGH - Multi-stage job with 4 different container usage patterns

---

## Summary

Phase 5 is **NOT just simple defaults** - it's more complex because `process_large_raster.py` uses containers in **4 different ways** across its 4-stage workflow:

1. **Input rasters** (Bronze - source data)
2. **Tiling schemes** (Silver - metadata)
3. **Intermediate tiles** (Bronze/Silver - temporary files)
4. **Output COGs** (Silver - final processed data)

---

## The 6 References Explained

### Reference 1: Line 135 (COMMENT - Simple)
```python
"description": "Source container name (uses config.bronze_container_name if None)"
```

**Type**: Comment/documentation
**Change**: Update to reference new pattern
**Risk**: None (documentation only)

---

### Reference 2: Line 472 (CODE - Default for INPUT)
```python
# Stage 1: Generate Tiling Scheme
container_name = job_params["container_name"] or config.bronze_container_name
```

**Type**: Code - default container for input raster
**Purpose**: Where to read the original large raster from
**Change**:
```python
# NEW
container_name = job_params["container_name"] or config.storage.bronze.get_container('rasters')
```
**Risk**: Low (same pattern as Phase 3-4)
**Result**: Reads large raster from `bronze-rasters`

---

### Reference 3: Line 482 (CODE - TILING SCHEME OUTPUT)
```python
# Stage 1: Generate Tiling Scheme
return [{
    "task_type": "generate_tiling_scheme",
    "parameters": {
        # ...
        "output_container": config.silver_container_name,  # <-- Where to save tiling scheme GeoJSON
    }
}]
```

**Type**: Code - where to save tiling scheme metadata
**Purpose**: Tiling scheme is a GeoJSON file defining the tile grid
**Change**:
```python
# NEW
"output_container": config.storage.silver.get_container('tiles')  # or 'mosaicjson'?
```
**Risk**: Medium - Need to decide which silver container
**Options**:
  - `config.storage.silver.get_container('tiles')` - Seems most appropriate
  - `config.storage.silver.get_container('mosaicjson')` - Alternative
  - `config.storage.silver.get_container('misc')` - Generic

**Question**: Where should tiling scheme GeoJSON files go?

---

### Reference 4: Line 499 (CODE - Default for INPUT - Stage 2)
```python
# Stage 2: Extract Tiles
container_name = job_params["container_name"] or config.bronze_container_name
```

**Type**: Code - default container for input raster (again, in Stage 2)
**Purpose**: Where to read the original large raster from (for tile extraction)
**Change**: Same as Reference 2
```python
# NEW
container_name = job_params["container_name"] or config.storage.bronze.get_container('rasters')
```
**Risk**: Low (same pattern)

---

### Reference 5: Line 508 (CODE - TILING SCHEME INPUT)
```python
# Stage 2: Extract Tiles
return [{
    "task_type": "extract_tiles",
    "parameters": {
        "tiling_scheme_blob": tiling_scheme_blob,
        "tiling_scheme_container": config.silver_container_name,  # <-- Where to READ tiling scheme FROM
        "output_container": config.resolved_intermediate_tiles_container,
    }
}]
```

**Type**: Code - where to read tiling scheme from
**Purpose**: Read the GeoJSON tiling scheme created in Stage 1
**Change**: Must match Reference 3's output!
```python
# NEW
"tiling_scheme_container": config.storage.silver.get_container('tiles')  # Must match Stage 1 output
```
**Risk**: Medium - Must be consistent with Reference 3

---

### Reference 6: Line 634 (CODE - MOSAICJSON OUTPUT)
```python
# Stage 4: Create MosaicJSON + STAC
return [{
    "task_type": "create_mosaicjson",
    "parameters": {
        "cog_blobs": successful_cogs,
        "container_name": config.silver_container_name,  # <-- Where to save MosaicJSON
    }
}]
```

**Type**: Code - where to save MosaicJSON output
**Purpose**: Final MosaicJSON aggregating all COG tiles
**Change**:
```python
# NEW
"container_name": config.storage.silver.get_container('mosaicjson')
```
**Risk**: Low (clear purpose - MosaicJSON goes in mosaicjson container)

---

## Special Case: Line 509 - Intermediate Tiles

**Current Code**:
```python
"output_container": config.resolved_intermediate_tiles_container
```

**What is `resolved_intermediate_tiles_container`?**

From `config.py` line 882-894:
```python
@property
def resolved_intermediate_tiles_container(self) -> str:
    """
    Get intermediate tiles container, defaulting to bronze if not specified.

    Returns container name for intermediate raster tiles (Stage 2 output).
    If intermediate_tiles_container is None, falls back to bronze_container_name.
    """
    return self.intermediate_tiles_container or self.bronze_container_name
```

**This uses the OLD deprecated pattern internally!**

**Change Needed**:
```python
@property
def resolved_intermediate_tiles_container(self) -> str:
    """Get intermediate tiles container, defaulting to bronze if not specified."""
    return self.intermediate_tiles_container or self.storage.bronze.get_container('rasters')
```

**OR** - Better approach, change the job to use explicit container:
```python
# In process_large_raster.py line 509
"output_container": config.storage.bronze.get_container('rasters')  # Job-scoped folders: {job_id[:8]}/tiles/
```

---

## Container Flow - 4-Stage Pipeline

```
Stage 1: Generate Tiling Scheme
  INPUT:  config.storage.bronze.get_container('rasters')           [Line 472]
          └─ Source large raster (e.g., 11GB file)
  OUTPUT: config.storage.silver.get_container('tiles')             [Line 482]
          └─ Tiling scheme GeoJSON (grid definition)

Stage 2: Extract Tiles (Sequential)
  INPUT:  config.storage.bronze.get_container('rasters')           [Line 499]
          └─ Source large raster (read again for extraction)
  INPUT:  config.storage.silver.get_container('tiles')             [Line 508]
          └─ Tiling scheme GeoJSON (from Stage 1)
  OUTPUT: config.storage.bronze.get_container('rasters')           [Line 509 via resolved_intermediate_tiles_container]
          └─ Raw tiles: {job_id[:8]}/tiles/blob_stem_tile_0_0.tif

Stage 3: Convert Tiles to COGs (Parallel)
  INPUT:  config.storage.bronze.get_container('rasters')
          └─ Raw tiles from Stage 2
  OUTPUT: config.storage.silver.get_container('cogs')
          └─ COG tiles: cogs/blob_stem/blob_stem_tile_0_0_cog.tif

Stage 4: Create MosaicJSON + STAC
  INPUT:  config.storage.silver.get_container('cogs')
          └─ All COG tiles from Stage 3
  OUTPUT: config.storage.silver.get_container('mosaicjson')        [Line 634]
          └─ MosaicJSON file + STAC metadata
```

---

## Proposed Changes - Complete List

### 1. Line 135 (Comment)
```python
# OLD
"description": "Source container name (uses config.bronze_container_name if None)"

# NEW
"description": "Source container name (uses config.storage.bronze.get_container('rasters') if None)"
```

### 2. Line 472 (Stage 1 - Input Default)
```python
# OLD
container_name = job_params["container_name"] or config.bronze_container_name

# NEW
container_name = job_params["container_name"] or config.storage.bronze.get_container('rasters')
```

### 3. Line 482 (Stage 1 - Tiling Scheme Output)
```python
# OLD
"output_container": config.silver_container_name,

# NEW
"output_container": config.storage.silver.get_container('tiles'),  # Tiling scheme GeoJSON
```

### 4. Line 499 (Stage 2 - Input Default)
```python
# OLD
container_name = job_params["container_name"] or config.bronze_container_name

# NEW
container_name = job_params["container_name"] or config.storage.bronze.get_container('rasters')
```

### 5. Line 508 (Stage 2 - Tiling Scheme Input)
```python
# OLD
"tiling_scheme_container": config.silver_container_name,

# NEW
"tiling_scheme_container": config.storage.silver.get_container('tiles'),  # Must match Stage 1 output
```

### 6. Line 634 (Stage 4 - MosaicJSON Output)
```python
# OLD
"container_name": config.silver_container_name,

# NEW
"container_name": config.storage.silver.get_container('mosaicjson'),  # MosaicJSON output
```

### BONUS: Fix config.py Property (Line 894)
```python
# OLD
return self.intermediate_tiles_container or self.bronze_container_name

# NEW
return self.intermediate_tiles_container or self.storage.bronze.get_container('rasters')
```

---

## Complexity Factors

### Why Phase 5 is Different

1. **Multiple Container Roles**: Not just input/output - has metadata, intermediate, and final output containers
2. **Cross-Stage Dependencies**: Stage 2 must read from same container Stage 1 wrote to
3. **Recently Updated**: File modified 02 NOV 2025 - need to coordinate with recent changes
4. **Job-Scoped Storage**: Uses job ID in folder paths (`{job_id[:8]}/tiles/`)
5. **Property Dependency**: Uses `resolved_intermediate_tiles_container` property which also needs updating

### Risk Assessment

| Change | Risk | Reason |
|--------|------|--------|
| Line 135 | None | Comment only |
| Line 472 | Low | Same pattern as Phase 3-4 |
| Line 482 | **Medium** | New decision - which silver container for tiling schemes? |
| Line 499 | Low | Same pattern as Phase 3-4 |
| Line 508 | **Medium** | Must match Line 482 |
| Line 634 | Low | Clear purpose (mosaicjson) |
| Config property | Low | Simple change |

---

## Questions to Answer Before Migration

### 1. Tiling Scheme Container Location (Lines 482, 508)

**Question**: Where should tiling scheme GeoJSON files go?

**Options**:
- `config.storage.silver.get_container('tiles')` ✅ **Recommended** - Logical grouping with tile data
- `config.storage.silver.get_container('mosaicjson')` - Also metadata, could work
- `config.storage.silver.get_container('misc')` - Too generic

**Recommendation**: Use `tiles` container since tiling schemes define the tile grid.

### 2. Intermediate Tiles Container (Line 509)

**Current**: Uses `config.resolved_intermediate_tiles_container` (falls back to bronze)

**Question**: Should intermediate tiles stay in bronze or move to silver?

**Recommendation**: Keep in bronze (`bronze-rasters`) with job-scoped folders since they're temporary:
- Path: `bronze-rasters/{job_id[:8]}/tiles/blob_stem_tile_0_0.tif`
- Cleanup: Handled separately (not part of ETL workflow per docs)

---

## Summary

**Is this just defaults?** → **NO, it's more complex!**

- ✅ 2 changes are simple defaults (lines 472, 499)
- ✅ 1 change is a comment (line 135)
- ⚠️ 3 changes require container purpose decisions (lines 482, 508, 634)
- ⚠️ 1 bonus change in config.py property (line 894)

**Total Impact**: 7 changes (6 in job file + 1 in config.py)

**Key Difference from Phase 3-4**: Multiple containers with different purposes in a single workflow

---

## Recommendation

**Before executing Phase 5**:
1. Confirm tiling scheme should go in `silver-tiles` container
2. Confirm intermediate tiles stay in `bronze-rasters` (with job-scoped folders)
3. Confirm MosaicJSON goes in `silver-mosaicjson` container
4. Review recent changes in process_large_raster.py (02 NOV 2025)

**After confirmation**, Phase 5 is straightforward to execute (~15 minutes).

---

**Status**: Ready for your decision on container mappings

