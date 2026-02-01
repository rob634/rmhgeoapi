# FATHOM Flood Data ETL Pipeline

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 07 JAN 2026
**Status**: Production (Phase 1 & 2 Complete)

> **Source of Truth**: This wiki file is the canonical user-facing documentation.
> See also: [docs_claude/FATHOM_ETL.md](../../docs_claude/FATHOM_ETL.md) (AI context version with additional implementation details)

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
| **Total Size** | ~8 TB (global dataset) |

---

## Quick Start

### 1. Inventory (Scan Bronze Container)

```bash
curl -X POST \
  https://<platform-api-url>/api/jobs/submit/inventory_fathom_container \
  -H 'Content-Type: application/json' \
  -d '{"base_prefix": "rwa"}'
```

### 2. Phase 1 - Band Stacking

```bash
curl -X POST \
  https://<platform-api-url>/api/jobs/submit/process_fathom_stack \
  -H 'Content-Type: application/json' \
  -d '{"region_code": "rwa"}'
```

### 3. Phase 2 - Spatial Merge

```bash
curl -X POST \
  https://<platform-api-url>/api/jobs/submit/process_fathom_merge \
  -H 'Content-Type: application/json' \
  -d '{"region_code": "rwa", "grid_size": 4}'
```

---

## Two-Phase Architecture

```
PHASE 1: Band Stacking (per tile)
┌─────────────────────────────────────────────────────────────┐
│ Input: 8 single-band TIFFs (one per return period)          │
│ bronze-fathom/FATHOM-3-0-3/GLOBAL-1ARCSEC/...              │
│                                                             │
│ Output: 1 multi-band COG (8 bands stacked)                  │
│ silver-fathom/fathom-stacked/{region}/{tile}/...           │
│                                                             │
│ Reduction: 8:1 file count                                   │
│ Memory: ~2-3 GB peak per task                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
PHASE 2: Spatial Merge (grid cells)
┌─────────────────────────────────────────────────────────────┐
│ Input: N×N stacked COGs from Phase 1 (e.g., 4×4 = 16 tiles) │
│ silver-fathom/fathom-stacked/{region}/{tile}/...           │
│                                                             │
│ Output: 1 merged COG (larger spatial extent)                │
│ silver-fathom/fathom/{region}/{scenario}-{grid_cell}.tif   │
│                                                             │
│ Reduction: N²:1 file count                                  │
│ Memory: ~4-5 GB peak per task (grid_size=4)                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Parameters

### Inventory Job: `inventory_fathom_container`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `base_prefix` | string | No | "" | Region prefix (e.g., "rwa", "civ") |
| `source_container` | string | No | "bronze-fathom" | Container to scan |
| `flood_types` | list | No | all | Filter by flood types |
| `years` | list | No | all | Filter by years (2020, 2030, 2050, 2080) |
| `ssp_scenarios` | list | No | all | Filter by SSP scenarios |
| `batch_size` | int | No | 1000 | Database insert batch size |
| `grid_size` | int | No | 5 | Grid cell size in degrees |
| `dry_run` | bool | No | false | Count files only, no database insert |

### Phase 1 Job: `process_fathom_stack`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `region_code` | string | **Yes** | - | Region code (e.g., "rwa", "civ") |
| `source_container` | string | No | "bronze-fathom" | Source container |
| `output_container` | string | No | "silver-fathom" | Output container |
| `dry_run` | bool | No | false | Inventory only, no processing |
| `force_reprocess` | bool | No | false | Ignore previous state |
| `bbox` | list | No | null | Spatial filter [minx, miny, maxx, maxy] |

### Phase 2 Job: `process_fathom_merge`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `region_code` | string | **Yes** | - | Region code (e.g., "rwa", "civ") |
| `grid_size` | int | No | 4 | N×N merge factor (2-10) |
| `source_container` | string | No | "silver-fathom" | Source container |
| `output_container` | string | No | "silver-fathom" | Output container |
| `dry_run` | bool | No | false | Inventory only, no processing |
| `force_reprocess` | bool | No | false | Ignore previous state |
| `bbox` | list | No | null | Spatial filter [minx, miny, maxx, maxy] |

---

## Performance Metrics

### Infrastructure

| Resource | Value |
|----------|-------|
| **Function App SKU** | B3 (PremiumV3) |
| **vCPUs per worker** | 2 |
| **RAM per worker** | 7.7 GB |
| **Instances** | 4 |
| **Workers per instance** | 2 |
| **Total concurrent workers** | **8** |

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

| Grid Size | Tiles Merged | Status |
|-----------|--------------|--------|
| **grid_size=3** | 9 tiles | Works (~5 GB peak) |
| **grid_size=4** | 16 tiles | Works (near memory limit) |
| **grid_size=5+** | 25+ tiles | Likely OOM |

**Effective memory budget**: ~4 GB (3.5 GB consumed by OS/runtime overhead)

### Scaling Projections

Based on RWA baseline throughput with 8 workers:

| Region | Tiles | Phase 1 Tasks | Phase 2 Tasks | Estimated Time |
|--------|-------|---------------|---------------|----------------|
| Rwanda (RWA) | 6 | 234 | 39 | ~17 min |
| Côte d'Ivoire (CIV) | 50 | 1,924 | ~312 | ~2 hours |
| West Africa | ~500 | ~20,000 | ~3,000 | ~15-20 hours |
| **Global (8TB)** | ~100,000 | ~4M+ | ~600K+ | **Several days** |

**Scaling formulas** (approximate):
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

```kusto
// Query: How many instances processed tasks?
traces
| where timestamp >= ago(2h)
| where message contains 'task_id' and message contains 'Result'
| summarize task_count=count() by cloud_RoleInstance
| order by task_count desc
```

### Count Workers Per Instance

```kusto
// Query: How many workers per instance? (should be 2)
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
cbefa55aa015...                | <uuid>   | 237
cbefa55aa015...                | <uuid>   | 112
6f2767c2e010...                | <uuid>   | 203
6f2767c2e010...                | <uuid>   | 79
64fcec8b11e2...                | <uuid>   | 237
64fcec8b11e2...                | <uuid>   | 99
50bd00d9b926...                | <uuid>   | 216
50bd00d9b926...                | <uuid>   | 116
-------------------------------|----------------------------------------|------
4 instances                    | 8 workers total                        | 1,299
```

### Calculate Actual Processing Rate

```kusto
// Query: Task duration distribution
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

```kusto
traces
| where timestamp >= ago(1h)
| where message contains 'Starting task'
| summarize count() by bin(timestamp, 1s)
| order by timestamp desc
| take 30
```

If you see 8+ tasks starting in the same second, full concurrency is being utilized.

### Running Queries via CLI

```bash
# Create query script
cat > /tmp/query_instances.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/<uuid>/query" \
  --data-urlencode "query=traces | where timestamp >= ago(2h) | where message contains 'task_id' and message contains 'Result' | summarize task_count=count() by cloud_RoleInstance | order by task_count desc" \
  -G
EOF
chmod +x /tmp/query_instances.sh && /tmp/query_instances.sh | python3 -m json.tool
```

---

## Files

| File | Purpose |
|------|---------|
| `jobs/inventory_fathom_container.py` | Inventory job definition |
| `jobs/process_fathom_stack.py` | Phase 1 job definition |
| `jobs/process_fathom_merge.py` | Phase 2 job definition |
| `services/fathom_container_inventory.py` | Bronze container scanner |
| `services/fathom_etl.py` | Core handlers (tile_inventory, band_stack, grid_inventory, spatial_merge, stac_register) |
| `core/models/etl.py` | EtlSourceFile Pydantic model |
| `config/defaults.py` | FathomDefaults class |

### Database Table: `app.etl_source_files`

FATHOM uses the generalized `app.etl_source_files` table with `etl_type='fathom'`.

```sql
-- Key columns for FATHOM tracking
etl_type = 'fathom'
source_blob_path = 'FATHOM-3-0-3/GLOBAL-1ARCSEC/...'
source_container = 'bronze-fathom'

-- JSONB metadata (parsed from blob path)
source_metadata = {
    "flood_type": "fluvial",
    "defense": "defended",
    "year": 2020,
    "ssp": null,
    "return_period": "1in100",
    "tile": "n04w006",
    "grid_cell": "n00-n04_w004-w008",
    "region": "civ"  -- Region prefix for filtering
}

-- Phase tracking
phase1_group_key = 's01e030/fluvial-defended-2020'
phase1_completed_at = timestamp
phase2_group_key = 'n00-n04_e028-e032/fluvial-defended-2020'
phase2_completed_at = timestamp
```

---

## Output Naming Conventions

### Phase 1 Output (Stacked COGs)

```
silver-fathom/fathom-stacked/{region}/{tile}/{tile}_{flood_type}-{defense}_{year}[_{ssp}].tif

Examples:
silver-fathom/fathom-stacked/rwa/s01e030/s01e030_fluvial-defended_2020.tif
silver-fathom/fathom-stacked/rwa/s01e030/s01e030_coastal-undefended_2030_ssp245.tif
```

### Phase 2 Output (Merged COGs)

```
silver-fathom/fathom/{region}/{flood_type}-{defense}-{year}[-{ssp}]-{grid_cell}.tif

Examples:
silver-fathom/fathom/rwa/fluvial-defended-2020-s00-s04_e028-e032.tif
silver-fathom/fathom/rwa/coastal-undefended-2030-ssp245-s00-s04_e028-e032.tif
```

---

## Processing Status

### Rwanda (RWA) - Test Region

| Phase | Status | Details |
|-------|--------|---------|
| Bronze inventory | Complete | 6 tiles, 234 Phase 1 groups, 39 Phase 2 groups |
| Phase 1 (stack) | Complete | 234/234 tasks, 0 failures |
| Phase 2 (merge) | Complete | 39/39 tasks, 0 failures |
| STAC registration | Pending | Not yet run |

### Côte d'Ivoire (CIV) - Previous Test Region

| Phase | Status | Details |
|-------|--------|---------|
| Bronze inventory | Pending | 50 tiles expected |
| Phase 1 (stack) | Files exist | 1,924 COGs in silver-fathom/fathom-stacked/civ/ |
| Phase 2 (merge) | Files exist | 87 merged COGs in silver-fathom/fathom/civ/ |
| Database tracking | Needs sync | Blobs exist but etl_source_files was reset |

---

## Troubleshooting

### Region Filtering Bug (Fixed 07 JAN 2026)

**Symptom**: Inventory reports wrong tile count (e.g., 50 tiles for RWA when only 6 exist)

**Root cause**: Queries returned ALL fathom records regardless of region

**Fix**: Added `source_metadata->>'region'` filtering to all query handlers:
- `services/fathom_container_inventory.py`
- `services/fathom_etl.py`
- `jobs/inventory_fathom_container.py`

### Memory Errors (OOM)

**Symptom**: Tasks fail with memory errors during Phase 2

**Solution**: Reduce `grid_size` parameter (default 4, try 3)

### No Tasks Generated

**Symptom**: Phase 1 or Phase 2 job completes with 0 tasks

**Possible causes**:
1. Inventory not run for this region
2. Region code mismatch (case-sensitive)
3. All tiles already processed (check `force_reprocess: true`)

---

**Last Updated**: 07 JAN 2026
