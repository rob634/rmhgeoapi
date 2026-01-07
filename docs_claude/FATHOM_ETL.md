# FATHOM Flood Data ETL Pipeline

**Last Updated**: 07 JAN 2026
**Status**: Phase 1 & 2 Complete (RWA), Region Filtering Fixed
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
| `services/fathom_container_inventory.py` | Bronze container scanner, populates etl_source_files table |
| `core/models/etl.py` | EtlSourceFile Pydantic model (defines table schema via IaC) |
| `config/defaults.py` | FathomDefaults class (containers, prefixes, collection IDs) |

### Database Table: `app.etl_source_files` (Generalized ETL Tracking)

**Updated 21 DEC 2025**: FATHOM uses the generalized `app.etl_source_files` table with `etl_type='fathom'`.
This table supports ANY ETL pipeline type via namespace (`etl_type`) and flexible JSONB metadata.

```sql
CREATE TABLE app.etl_source_files (
    id SERIAL PRIMARY KEY,

    -- ETL Type Namespace (fathom, raster_v2, vector, etc.)
    etl_type VARCHAR(64) NOT NULL,

    -- Source file identification
    source_blob_path VARCHAR(512) NOT NULL,
    source_container VARCHAR(100) NOT NULL,
    file_size_bytes BIGINT,

    -- Domain-specific metadata as JSONB (flexible for each ETL type)
    source_metadata JSONB DEFAULT '{}',

    -- Phase 1 tracking (generic)
    phase1_group_key VARCHAR(150),
    phase1_output_blob VARCHAR(512),
    phase1_job_id VARCHAR(64),
    phase1_completed_at TIMESTAMP,

    -- Phase 2 tracking (generic)
    phase2_group_key VARCHAR(150),
    phase2_output_blob VARCHAR(512),
    phase2_job_id VARCHAR(64),
    phase2_completed_at TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    -- Unique per ETL type + source path
    UNIQUE (etl_type, source_blob_path)
);

-- FATHOM source_metadata example:
-- {
--   "flood_type": "fluvial",
--   "defense": "defended",
--   "year": 2020,
--   "ssp": null,
--   "return_period": "1in100",
--   "tile": "n04w006",
--   "grid_cell": "n00-n05_w005-w010"
-- }
```

**Key Design Principles**:
- Single table for ALL ETL types, namespaced by `etl_type`
- JSONB `source_metadata` stores domain-specific parsed fields
- Generic phase1/phase2 columns support most multi-phase pipelines
- Defined via Pydantic model (`core/models/etl.py`) → SQL generation (IaC)

---

## Handlers

### Phase 1 Handlers

| Handler | Purpose |
|---------|---------|
| `fathom_tile_inventory` | Query etl_source_files for Phase 1 pending, group by tile+scenario |
| `fathom_band_stack` | Download 8 TIFFs, stack bands, write COG, update phase1_completed_at |

### Phase 2 Handlers

| Handler | Purpose |
|---------|---------|
| `fathom_grid_inventory` | Query etl_source_files for Phase 1 complete, group by grid_cell+scenario |
| `fathom_spatial_merge` | Download N² COGs, merge spatially, write COG, update phase2_completed_at |
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

### Phase 2 Output (Flat Structure)
```
silver-fathom/fathom/{region}/{flood_type}-{defense}-{year}[-{ssp}]-{grid_cell}.tif

Example:
silver-fathom/fathom/ci/fluvial-defended-2020-n00-n05_w005-w010.tif
silver-fathom/fathom/ci/coastal-undefended-2030-ssp245-n00-n05_w005-w010.tif
```

**Note**: Phase 2 uses flat output (no grid_cell subfolder) with naming that matches
the original FATHOM file order: `{flood_type}-{defense}-{year}-{ssp}-{grid_cell}`

### Grid Cell Format
```
{lat_dir}{lat_start}-{lat_dir}{lat_end}_{lon_dir}{lon_start}-{lon_dir}{lon_end}

Example: n00-n05_w005-w010
         Latitude N0° to N5°, Longitude W5° to W10°
```

---

## Performance Metrics

**Last Updated**: 07 JAN 2026

### Infrastructure
- Azure Functions B3 (PremiumV3)
- 2 vCPUs, 7.7 GB RAM per worker
- 4 instances × 2 workers = **8 concurrent workers**

### Rwanda Baseline (07 JAN 2026)

RWA is a small test region with 6 tiles. This provides a clean baseline for throughput calculations.

| Phase | Tasks | Duration | Throughput | Avg Task Time |
|-------|-------|----------|------------|---------------|
| Inventory | 68 | 51 sec | ~80/min | <1s |
| **Phase 1** (band stack) | 234 | 7m 10s | **33/min** | **17.3s** |
| **Phase 2** (spatial merge) | 39 | 7m 48s | **5/min** | **100s** |
| **Total Pipeline** | 341 | **~17 min** | - | - |

### Per-Task Duration Analysis
| Phase | Metric | Value |
|-------|--------|-------|
| Phase 1 | Peak memory | ~2-3 GB RSS |
| Phase 1 | Avg task duration | 17.3 seconds |
| Phase 2 | Peak memory | ~4-5 GB RSS (90%+ system usage) |
| Phase 2 | Avg task duration | 100 seconds |
| Phase 2 | Min task duration | 4.4 seconds (sparse data) |
| Phase 2 | Max task duration | 277.6 seconds |

### Memory Limits
- **grid_size=3**: Works (9 tiles → ~5 GB peak)
- **grid_size=4**: Works with current config (16 tiles → near memory limit)
- **grid_size=5+**: Likely OOM (would exceed memory)
- **Effective memory budget**: ~4 GB (3.5 GB consumed by OS/runtime overhead)

### Scaling Projections

Based on RWA baseline throughput with 8 workers:

| Region | Tiles | Phase 1 Tasks | Phase 2 Tasks | Estimated Time |
|--------|-------|---------------|---------------|----------------|
| Rwanda (RWA) | 6 | 234 | 39 | ~17 min |
| Côte d'Ivoire (CIV) | 50 | 1,924 | ~312 | ~2 hours |
| West Africa | ~500 | ~20,000 | ~3,000 | ~15-20 hours |
| Global (8TB) | ~100,000 | ~4M+ | ~600K+ | **Several days** |

**Scaling formula** (approximate):
- Phase 1: `tasks ÷ 33/min`
- Phase 2: `tasks × 100s ÷ 8 workers`

---

## Instance & Worker Monitoring

Application Insights logs include instance and worker identifiers for calculating actual concurrency.

### Key Fields
| Field | Source | Description |
|-------|--------|-------------|
| `cloud_RoleInstance` | App Insights | Function App instance hash (unique per VM) |
| `HostInstanceId` | customDimensions | Worker GUID within an instance |
| `ProcessId` | customDimensions | Process ID within worker |

### Count Active Instances
```bash
# Query: How many instances processed tasks?
traces
| where timestamp >= ago(2h)
| where message contains 'task_id' and message contains 'Result'
| summarize task_count=count() by cloud_RoleInstance
| order by task_count desc
```

### Count Workers Per Instance
```bash
# Query: How many workers per instance? (should be 2)
traces
| where timestamp >= ago(2h)
| where message contains 'task_id' and message contains 'Result'
| extend hostId = tostring(parse_json(customDimensions).HostInstanceId)
| summarize task_count=count() by cloud_RoleInstance, hostId
| order by cloud_RoleInstance, task_count desc
```

### Example Output (RWA Pipeline, 07 JAN 2026)
```
Instance (cloud_RoleInstance)  | Worker (HostInstanceId)                | Tasks
-------------------------------|----------------------------------------|------
cbefa55aa015...                | cb58e3e4-5780-4cae-adab-2c100d9012a7   | 237
cbefa55aa015...                | 6ad84b40-431d-4cf1-bbf1-b016cfbb1b29   | 112
6f2767c2e010...                | 45639263-e784-4724-b03b-754fc50ca824   | 203
6f2767c2e010...                | ae1020a5-0287-42a6-aa9a-eadd1be1bd49   | 79
64fcec8b11e2...                | 0a176ad9-64fd-4616-ac3c-aad3c7296c91   | 237
64fcec8b11e2...                | 35e46522-dfc8-49f6-82cf-aab2f67a3e85   | 99
50bd00d9b926...                | 76acb5c2-f7f0-4059-a68d-3907ede8600a   | 216
50bd00d9b926...                | 6d2b3b9b-f9e9-4e84-b722-8e5afb27ac86   | 116
-------------------------------|----------------------------------------|------
4 instances                    | 8 workers total                        | 1,299
```

### Calculate Actual Processing Rate
```bash
# Query: Task duration distribution
traces
| where timestamp >= ago(2h)
| where message contains 'Result' and message contains 'task_id'
| extend task_type = extract(@"task_type.*?'([^']+)'", 1, message)
| summarize
    count=count(),
    avg_duration_s=avg(duration) / 1000,
    min_duration_s=min(duration) / 1000,
    max_duration_s=max(duration) / 1000
  by task_type
```

### Verify Concurrency
To confirm all workers are active, check task start times overlap:
```bash
traces
| where timestamp >= ago(1h)
| where message contains 'Starting task'
| summarize count() by bin(timestamp, 1s)
| order by timestamp desc
| take 30
```

If you see 8+ tasks starting in the same second, full concurrency is being utilized.

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
**Problem**: grid_inventory filtered by `source_container = 'silver-fathom'` but table stores original source `bronze-fathom`.

```python
# BEFORE (buggy):
WHERE phase1_completed_at IS NOT NULL
  AND source_container = %(source_container)s  -- Always returns 0 rows!

# AFTER (fixed):
WHERE phase1_completed_at IS NOT NULL
  -- Removed source_container filter; phase1_completed_at IS NOT NULL is sufficient
```

**File**: `services/fathom_etl.py`

---

## Processing Status

**Last Updated**: 07 JAN 2026

### Region Filtering Fix (07 JAN 2026)

Fixed critical bug where inventory/Phase 1/Phase 2 queries returned ALL fathom records regardless of region.

**Root cause**: `source_metadata` JSONB wasn't being filtered by `region` field.

**Files modified**:
- `services/fathom_container_inventory.py` - Added region extraction and filtering
- `services/fathom_etl.py` - Added `source_metadata->>'region'` WHERE clauses
- `jobs/inventory_fathom_container.py` - Pass `base_prefix` to summary task

### Rwanda (RWA) - Current Test Region ✅

| Phase | Status | Details |
|-------|--------|---------|
| Bronze inventory | ✅ Complete | 6 tiles, 234 Phase 1 groups, 39 Phase 2 groups |
| Phase 1 (stack) | ✅ Complete | 234/234 tasks, 0 failures |
| Phase 2 (merge) | ✅ Complete | 39/39 tasks, 0 failures |
| STAC registration | ⏳ Pending | Not yet run |

### Côte d'Ivoire (CIV) - Previous Test Region

| Phase | Status | Details |
|-------|--------|---------|
| Bronze inventory | ⏳ Pending | 50 tiles expected |
| Phase 1 (stack) | ✅ Files exist | 1,924 COGs in silver-fathom/fathom-stacked/civ/ |
| Phase 2 (merge) | ✅ Files exist | 87 merged COGs in silver-fathom/fathom/civ/ |
| Database tracking | ⏳ Needs sync | Blobs exist but etl_source_files table was reset |

**Note**: CIV was processed with grid_size=3 before region filtering fix. Output files preserved.
To sync database with existing outputs, run inventory with `base_prefix: "civ"`.

### Running a New Region

```bash
# 1. Inventory (scan bronze-fathom for region)
curl -X POST "https://rmhazuregeoapi.../api/jobs/submit/inventory_fathom_container" \
  -H "Content-Type: application/json" \
  -d '{"base_prefix": "rwa"}'

# 2. Phase 1 (band stacking)
curl -X POST "https://rmhazuregeoapi.../api/jobs/submit/process_fathom_stack" \
  -H "Content-Type: application/json" \
  -d '{"region_code": "rwa"}'

# 3. Phase 2 (spatial merge)
curl -X POST "https://rmhazuregeoapi.../api/jobs/submit/process_fathom_merge" \
  -H "Content-Type: application/json" \
  -d '{"region_code": "rwa", "grid_size": 4}'
```

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

# Phase 1 completion
traces | where message contains 'Updated' and message contains 'phase1_completed_at'

# Phase 2 completion
traces | where message contains 'Updated' and message contains 'phase2_completed_at'

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
6. ~~**Generalized ETL Tracking**~~: ✅ Done (21 DEC 2025) - Migrated to `app.etl_source_files`
7. **Additional ETL Types**: Use `etl_source_files` for raster_v2, vector, and other pipelines
