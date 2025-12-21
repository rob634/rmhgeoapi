# FATHOM Flood Data ETL Pipeline

**Last Updated**: 21 DEC 2025
**Status**: Phase 1 Complete, Phase 2 In Testing
**Author**: Robert and Claude

---

## Overview

FATHOM is a global flood hazard dataset providing flood depth rasters at 3-arcsecond (~90m) resolution. The ETL pipeline transforms raw FATHOM tiles into optimized, multi-band Cloud-Optimized GeoTIFFs (COGs) with STAC metadata.

### Data Characteristics

| Attribute | Value |
|-----------|-------|
| **Resolution** | 3 arcseconds (~90m) |
| **Tile Size** | 1° × 1° (3600 × 3600 pixels) |
| **Bands per Tile** | 8 return periods (5, 10, 20, 50, 75, 100, 200, 500 year) |
| **Flood Types** | Fluvial (river), Pluvial (surface), Coastal |
| **Defense Scenarios** | Defended, Undefended |
| **Climate Scenarios** | 2020 (baseline), 2030/2050/2080 (SSP126/245/370/585) |
| **Coverage** | Global (land areas) |

---

## Two-Phase Architecture

```
PHASE 1: Band Stacking (per tile)
┌─────────────────────────────────────────────────────────────┐
│ Input: 8 single-band TIFFs (one per return period)          │
│ bronze-fathom/FATHOM-3-0-3/GLOBAL-1ARCSEC/...              │
│                                                             │
│ Output: 1 multi-band COG (8 bands stacked)                  │
│ silver-fathom/fathom-stacked/{region}/{tile}/{tile}_{scenario}.tif │
│                                                             │
│ Reduction: 8:1 file count                                   │
│ Memory: ~2-3 GB peak per task                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
PHASE 2: Spatial Merge (grid cells)
┌─────────────────────────────────────────────────────────────┐
│ Input: N×N stacked COGs from Phase 1 (e.g., 3×3 = 9 tiles)  │
│ silver-fathom/fathom-stacked/{region}/{tile}/...           │
│                                                             │
│ Output: 1 merged COG (larger spatial extent)                │
│ silver-fathom/fathom/{region}/{grid_cell}/{scenario}.tif   │
│                                                             │
│ Reduction: N²:1 file count                                  │
│ Memory: ~4-5 GB peak per task (grid_size=3)                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Files

| File | Purpose |
|------|---------|
| `jobs/process_fathom_stack.py` | Phase 1 job definition |
| `jobs/process_fathom_merge.py` | Phase 2 job definition |
| `services/fathom_etl.py` | Core handlers (tile_inventory, band_stack, grid_inventory, spatial_merge, stac_register) |
| `services/fathom_container_inventory.py` | Bronze container scanner, etl_fathom table management |
| `config/defaults.py` | FathomDefaults class (containers, prefixes, collection IDs) |

### Database Table: `app.etl_fathom`

Tracks processing state for each source file:

```sql
CREATE TABLE app.etl_fathom (
    id SERIAL PRIMARY KEY,
    source_container VARCHAR(100),
    source_blob VARCHAR(512),
    tile VARCHAR(20),                    -- e.g., "n04w006"
    flood_type VARCHAR(20),              -- fluvial/pluvial/coastal
    defense VARCHAR(20),                 -- defended/undefended
    return_period INTEGER,               -- 5, 10, 20, 50, 75, 100, 200, 500
    year INTEGER,                        -- 2020, 2030, 2050, 2080
    ssp VARCHAR(10),                     -- NULL for 2020, else ssp126/245/370/585

    -- Phase 1 tracking
    phase1_group_key VARCHAR(100),       -- tile + scenario (grouping key)
    phase1_output_blob VARCHAR(512),
    phase1_processed_at TIMESTAMP,
    phase1_job_id VARCHAR(64),

    -- Phase 2 tracking
    grid_cell VARCHAR(30),               -- e.g., "n00-n05_w005-w010"
    phase2_group_key VARCHAR(100),       -- grid_cell + scenario
    phase2_output_blob VARCHAR(512),
    phase2_processed_at TIMESTAMP,
    phase2_job_id VARCHAR(64)
);
```

---

## Handlers

### Phase 1 Handlers

| Handler | Purpose |
|---------|---------|
| `fathom_tile_inventory` | Query etl_fathom for Phase 1 pending, group by tile+scenario |
| `fathom_band_stack` | Download 8 TIFFs, stack bands, write COG, update etl_fathom |

### Phase 2 Handlers

| Handler | Purpose |
|---------|---------|
| `fathom_grid_inventory` | Query etl_fathom for Phase 1 complete, group by grid_cell+scenario |
| `fathom_spatial_merge` | Download N² COGs, merge spatially, write COG, update etl_fathom |
| `fathom_stac_register` | Create STAC items for merged COGs |

---

## Naming Conventions

### Phase 1 Output
```
silver-fathom/fathom-stacked/{region}/{tile}/{tile}_{flood_type}-{defense}_{year}[_{ssp}].tif

Example:
silver-fathom/fathom-stacked/ci/n04w006/n04w006_fluvial-defended_2020.tif
silver-fathom/fathom-stacked/ci/n04w006/n04w006_coastal-undefended_2030_ssp245.tif
```

### Phase 2 Output
```
silver-fathom/fathom/{region}/{grid_cell}/{grid_cell}_{flood_type}-{defense}_{year}[_{ssp}].tif

Example:
silver-fathom/fathom/ci/n00-n05_w005-w010/n00-n05_w005-w010_fluvial-defended_2020.tif
```

### Grid Cell Format
```
{lat_dir}{lat_start}-{lat_dir}{lat_end}_{lon_dir}{lon_start}-{lon_dir}{lon_end}

Example: n00-n05_w005-w010
         Latitude N0° to N5°, Longitude W5° to W10°
```

---

## Performance Metrics (21 DEC 2025)

### Infrastructure
- Azure Functions B3 (PremiumV3)
- 2 vCPUs, 7.7 GB RAM per worker
- 2 minimum instances configured

### Phase 1 (Band Stack)
| Metric | Value |
|--------|-------|
| Peak memory | ~2-3 GB RSS |
| Task duration | ~30-60 seconds |
| Côte d'Ivoire | 32 tiles processed |

### Phase 2 (Spatial Merge, grid_size=3)
| Metric | Value |
|--------|-------|
| Peak memory | ~4-5 GB RSS (90%+ system usage) |
| System available | ~750 MB at peak |
| Avg task duration | 96.8 seconds |
| Min task duration | 4.4 seconds (sparse data) |
| Max task duration | 277.6 seconds |

### Memory Limits
- **grid_size=3**: Works (9 tiles → ~5 GB peak)
- **grid_size=4**: Likely OOM (16 tiles → would exceed memory)
- **Effective memory budget**: ~4 GB (3.5 GB consumed by OS/runtime overhead)

---

## Bugs Fixed (20-21 DEC 2025)

### 1. dict_row Access Pattern (Phase 1 & 2)
**Problem**: psycopg3 with `row_factory=dict_row` returns dicts, but code used tuple unpacking.

```python
# BEFORE (buggy):
rows = cur.fetchall()
columns = [desc[0] for desc in cur.description]
for row in rows:
    row_dict = dict(zip(columns, row))  # iterates dict keys, not values!

# AFTER (fixed):
rows = cur.fetchall()  # Already list of dicts
for row in rows:
    row_dict = row  # Use directly
```

**Files**: `services/fathom_etl.py` (tile_inventory, grid_inventory handlers)

### 2. Phase 2 source_container Filter
**Problem**: grid_inventory filtered by `source_container = 'silver-fathom'` but etl_fathom stores original source `bronze-fathom`.

```python
# BEFORE (buggy):
WHERE phase1_processed_at IS NOT NULL
  AND source_container = %(source_container)s  -- Always returns 0 rows!

# AFTER (fixed):
WHERE phase1_processed_at IS NOT NULL
  -- Removed source_container filter; phase1_processed_at IS NOT NULL is sufficient
```

**File**: `services/fathom_etl.py:651`

---

## Processing Status

### Côte d'Ivoire (CI) - Test Region

| Phase | Status | Details |
|-------|--------|---------|
| Bronze inventory | ✅ Complete | ~256 source files scanned |
| Phase 1 (stack) | ✅ Complete | 32 stacked COGs created |
| Phase 2 (merge) | ⚠️ Partial | 46/47 tasks complete, 1 failed |
| STAC registration | ❌ Blocked | Waiting for Phase 2 retry |

**Phase 2 Failure**: Task `n10-n15_w005-w010_*` failed (likely OOM or timeout on larger grid).

### Next Steps
1. Retry failed Phase 2 task with `force_reprocess=true`
2. Investigate if that grid cell has more tiles (edge case)
3. Consider grid_size=2 for memory-constrained areas

---

## API Endpoints

### Submit Phase 1 Job
```bash
curl -X POST "https://rmhazuregeoapi.../api/jobs/submit/process_fathom_stack" \
  -H "Content-Type: application/json" \
  -d '{
    "region_code": "CI",
    "source_container": "bronze-fathom",
    "output_container": "silver-fathom",
    "dry_run": false
  }'
```

### Submit Phase 2 Job
```bash
curl -X POST "https://rmhazuregeoapi.../api/jobs/submit/process_fathom_merge" \
  -H "Content-Type: application/json" \
  -d '{
    "region_code": "CI",
    "grid_size": 3,
    "source_container": "silver-fathom",
    "output_container": "silver-fathom",
    "dry_run": false
  }'
```

### Key Parameters
| Parameter | Phase 1 | Phase 2 | Description |
|-----------|---------|---------|-------------|
| `region_code` | ✓ | ✓ | ISO 2-letter country code |
| `grid_size` | - | ✓ | N×N merge factor (2-10, default 5) |
| `dry_run` | ✓ | ✓ | Inventory only, no processing |
| `force_reprocess` | ✓ | ✓ | Ignore previous processing state |
| `bbox` | ✓ | ✓ | Spatial filter [minx, miny, maxx, maxy] |

---

## STAC Collections

| Collection ID | Description |
|---------------|-------------|
| `fathom-flood-stacked-ci` | Phase 1 output (per-tile stacked COGs) |
| `fathom-flood` | Phase 2 output (merged COGs) |

---

## Quick Reference: Application Insights Queries

```bash
# Memory checkpoints
traces | where message contains 'MEMORY CHECKPOINT' and message contains 'spatial_merge'

# Phase 2 completion
traces | where message contains 'Updated' and message contains 'phase2_processed_at'

# Failures
traces | where message contains 'Failed' or message contains 'Error'
```

---

## Future Work

1. **Scale Testing**: Process larger regions (West Africa, Africa)
2. **Memory Optimization**: Streaming/chunked processing for larger grids
3. **Retry Logic**: Auto-retry failed tasks with smaller grid_size
4. **Monitoring Dashboard**: Real-time processing metrics
5. **Global Processing**: Full FATHOM dataset (~100K tiles)
