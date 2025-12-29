# Working Backlog

**Last Updated**: 28 DEC 2025
**Source of Truth**: [EPICS.md](/EPICS.md) — Epic/Feature/Story definitions live there
**Purpose**: Sprint-level task tracking and delegation

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| 1 | E10 | FATHOM Flood Data Pipeline | 🚧 | Phase 2 retry, scale testing |
| 2 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 3 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| 4 | E4 | Data Externalization | 📋 | F4.1: Publishing Workflow |
| 5 | E9 | Zarr/Climate Data as API | 🚧 | F9.2: Virtual Zarr Pipeline |
| **NEW** | **E12** | **Interface Modernization** | ✅ | **Phase 1 Complete** |
| **NEW** | **E13** | **Pipeline Observability** | ✅ | **Complete (9/10 stories)** |

---

## Current Sprint Focus

### E10: FATHOM Flood Data Pipeline

**Docs**: [FATHOM_ETL.md](./FATHOM_ETL.md)

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F10.1: Phase 1 | Band stacking (8 return periods → 1 COG) | Claude | ✅ CI Complete |
| F10.2: Phase 2 | Spatial merge (N×N tiles → 1 COG) | Claude | ⚠️ 46/47 tasks |
| F10.3: STAC | Register merged COGs to catalog | Claude | 📋 Blocked |
| F10.4: Scale | West Africa / Africa processing | Claude | 📋 |

**Current Issue**: Phase 2 task `n10-n15_w005-w010` failed. Need retry with `force_reprocess=true`.

### E2: Raster Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F2.7 | Raster Collection Processing (pgstac searches) | Claude | 📋 |
| S2.2.5 | Dynamic TiTiler preview URLs based on band count | Claude | 📋 |

**S2.2.5 Details**: TiTiler fails for >4 band imagery (e.g., WorldView-3 8-band) when default URLs don't specify `bidx` parameters. Need to:
- Detect band count in STAC metadata extraction
- Generate band-appropriate preview URLs (e.g., `&bidx=5&bidx=3&bidx=2` for WV RGB)
- Add WorldView-3 profile to `models/band_mapping.py` ✅ Done 21 DEC 2025

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S2.2.6 | Auto-rescale DEM TiTiler URLs using p2/p98 statistics | Claude | 📋 |

**S2.2.6 Details**: DEMs render grey without proper stretch. Need to:
- Query TiTiler `/cog/statistics` for p2/p98 percentiles during STAC extraction
- Add `&rescale={p2},{p98}&colormap_name=terrain` to DEM preview/viewer URLs
- Store rescale values in STAC item properties for client use

### E3: DDH Platform Integration

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F3.1: API Docs | OpenAPI 3.0 spec + Swagger UI | Claude | ✅ Deployed |
| **F3.1: Validate** | Review Swagger UI, test endpoints | User | 🔍 **Review** |
| F3.2: Identity | DDH service principal setup | DevOps | 📋 |
| F3.3: Envs | QA → UAT → Prod provisioning | DevOps | 📋 |

### E9: Zarr/Climate Data as API

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| F9.3: Reader Migration | Copy raster_api/xarray_api to rmhogcstac | Claude | ⬜ Ready |

### E12: Interface Modernization 🚧 ACTIVE

**Docs**: [NICEGUI.md](./NICEGUI.md)
**Goal**: Clean up interfaces, add HTMX, build Submit Vector UI

**Audit Findings (23 DEC 2025)**:
- 15 interfaces with ~3,500 LOC duplicated code
- Dashboard headers copied 9x identically
- 4 different status badge implementations
- 5 different filter/search patterns

#### Phase 1: Cleanup + HTMX (8-10 days total)

| Story | Description | Effort | Owner | Status |
|-------|-------------|--------|-------|--------|
| **F12.1: Cleanup** | | | | ✅ COMPLETE |
| S12.1.1 | CSS Consolidation → `COMMON_CSS` | 1 day | Claude | ✅ 23 DEC |
| S12.1.2 | JS Utilities → `COMMON_JS` | 0.5 day | Claude | ✅ 23 DEC |
| S12.1.3 | Python Component Helpers in `BaseInterface` | 1 day | Claude | ✅ 23 DEC |
| **F12.2: HTMX** | | | | ✅ COMPLETE |
| S12.2.1 | Add HTMX to BaseInterface | 0.5 day | Claude | ✅ 23 DEC |
| S12.2.2 | Refactor Storage Interface (HTMX) | 1 day | Claude | ✅ 23 DEC |
| S12.2.3 | Create Submit Vector Interface | 2 days | Claude | ✅ 23 DEC |
| **F12.3: Migration** | | | | ✅ COMPLETE |
| S12.3.1 | Migrate Jobs Interface (HTMX + component helpers) | 0.5 day | Claude | ✅ 24 DEC |
| S12.3.2 | Migrate Tasks Interface (HTMX) | 0.5 day | Claude | ✅ 24 DEC |
| S12.3.3 | Migrate P1 interfaces (STAC, Vector) | 1 day | Claude | ✅ 24 DEC |
| S12.3.4 | Migrate P2 interfaces (H3, Health, Pipeline) | 1 day | Claude | ✅ 24 DEC |
| S12.3.5 | Migrate P3 interfaces (platform, docs, queues, gallery, home) | 1 day | Claude | ✅ 24 DEC |

**Progress**: 14/18 interfaces HTMX-enabled (4 specialized full-page interfaces use custom HTML: map, zarr, swagger, stac-map)

#### Phase 2: NiceGUI Evaluation (Future)

| Story | Description | Owner | Status |
|-------|-------------|-------|--------|
| S12.4.1-5 | NiceGUI PoC on Docker Web App | Claude | 📋 After Phase 1 |

### E13: Pipeline Observability ✅ COMPLETE

**Goal**: Real-time metrics for long-running jobs with massive task counts (H3 aggregation, FATHOM ETL, raster collections)

**Problem Statement**: Jobs with 100s-1000s of tasks lack visibility into:
- Progress (which stage, how many tasks done)
- Throughput (tasks/minute, cells/second)
- ETA (when will it finish)
- Health (error rates, stalled detection)

**Architecture**:
```
┌─────────────────────────────────────────────────────────────────────┐
│  UNIVERSAL METRICS (all long-running jobs)                          │
│  • stage progress, task counts, rates, ETA, error tracking         │
└─────────────────────────────────────────────────────────────────────┘
                              │ extends
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CONTEXT-SPECIFIC METRICS (domain knowledge)                        │
│  • H3: cells processed, stats computed, current tile               │
│  • FATHOM: tiles merged, bytes processed, current region           │
│  • Raster: files processed, COGs created, output size              │
└─────────────────────────────────────────────────────────────────────┘
```

#### Phase 1: Core Infrastructure ✅ COMPLETE (28 DEC 2025)

| Story | Description | Effort | Owner | Status |
|-------|-------------|--------|-------|--------|
| **F13.1: Config** | | | | ✅ |
| S13.1.1 | Create `config/metrics_config.py` with env vars | 0.5 day | Claude | ✅ 28 DEC |
| **F13.2: Storage** | | | | ✅ |
| S13.2.1 | Create `app.job_metrics` table (self-bootstrapping) | 0.5 day | Claude | ✅ 28 DEC |
| S13.2.2 | Create `infrastructure/metrics_repository.py` | 0.5 day | Claude | ✅ 28 DEC |
| **F13.3: Tracker** | | | | ✅ |
| S13.3.1 | Create `infrastructure/job_progress.py` - base tracker | 1 day | Claude | ✅ 28 DEC |
| S13.3.2 | Create `infrastructure/job_progress_contexts.py` - mixins | 0.5 day | Claude | ✅ 28 DEC |

**Files Created**:
- `config/metrics_config.py` - MetricsConfig with env vars
- `infrastructure/metrics_repository.py` - PostgreSQL storage
- `infrastructure/job_progress.py` - JobProgressTracker base
- `infrastructure/job_progress_contexts.py` - H3/FATHOM/Raster mixins

#### Phase 2: HTTP API + Dashboard ✅ COMPLETE (28 DEC 2025)

| Story | Description | Effort | Owner | Status |
|-------|-------------|--------|-------|--------|
| **F13.4: HTTP API** | | | | ✅ |
| S13.4.1 | Create `web_interfaces/metrics/interface.py` | 1 day | Claude | ✅ 28 DEC |
| **F13.5: Dashboard** | | | | ✅ |
| S13.5.1 | Create pipeline monitor at `/api/interface/metrics` | 1 day | Claude | ✅ 28 DEC |

**Dashboard Features**:
- HTMX live updates (auto-refresh 5s)
- Job cards with progress bars
- Rate display (tasks/min, cells/sec)
- ETA calculation
- Context-specific metrics (H3, FATHOM, Raster)
- Job details panel with event log

#### Phase 3: Handler Integration ✅ COMPLETE (28 DEC 2025)

| Story | Description | Effort | Owner | Status |
|-------|-------------|--------|-------|--------|
| **F13.6: H3 Integration** | | | | ✅ |
| S13.6.1 | Integrate `H3AggregationTracker` into `handler_raster_zonal.py` | 0.5 day | Claude | ✅ 28 DEC |
| S13.6.2 | Integrate into `handler_inventory_cells.py` | 0.5 day | Claude | 📋 Deferred |
| **F13.7: FATHOM Integration** | | | | ✅ |
| S13.7.1 | Integrate `FathomETLTracker` into FATHOM handlers | 0.5 day | Claude | ✅ 28 DEC |

**Handler Integration**:
- `handler_raster_zonal.py`: H3AggregationTracker tracks cells, stats, tiles
- `fathom_etl.py`: FathomETLTracker tracks tiles merged, bytes processed, regions

**Debug Mode Output** (when `METRICS_DEBUG_MODE=true`):
```
[METRICS] Job abc123 started: h3_raster_aggregation
[METRICS] Stage 2/3: compute_stats (5 tasks)
[METRICS]   Task batch-0 started
[METRICS]   Processing tile: Copernicus_DSM_COG_10_S02_00_E029_00
[METRICS]     Batch 0: 1000 cells
[METRICS]     ✓ 4000 stats @ 842 cells/sec
[METRICS]   Task batch-0 completed (2.3s, 2000 cells, 8000 stats)
[METRICS]   Progress: 2000/68597 cells (2.9%), ETA: 74s
```

**API Response Schema** (`GET /api/metrics/jobs/{job_id}`):
```json
{
  "job_id": "abc123...",
  "job_type": "h3_raster_aggregation",
  "status": "processing",
  "progress": {
    "stage": 2, "total_stages": 3, "stage_name": "compute_stats",
    "tasks_total": 5, "tasks_completed": 2, "tasks_failed": 0
  },
  "rates": {
    "tasks_per_minute": 1.5,
    "elapsed_seconds": 120,
    "eta_seconds": 180
  },
  "context": {
    "type": "h3_aggregation",
    "cells_total": 68597,
    "cells_processed": 25000,
    "cells_rate_per_sec": 850,
    "stats_computed": 100000,
    "current_tile": "Copernicus_DSM_COG_10_S02_00_E029_00"
  },
  "recent_events": [
    {"timestamp": "...", "type": "batch_done", "message": "Batch 2: 1000 cells, 4000 stats"}
  ]
}
```

**Total Effort**: ~7-9 days

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| **S9.2.2**: Create DDH service principal | E9 | Azure AD service principal for QA | Azure AD, IAM |
| **S9.2.3**: Grant blob read access | E9 | Assign Storage Blob Data Reader | Azure RBAC |
| **S9.2.4**: Grant blob write access | E9 | Assign Storage Blob Data Contributor | Azure RBAC |
| **S9.3.2**: Document QA config | E9 | Export current config for replication | Documentation |
| **EN6.1**: Docker image | EN6 | Create image with GDAL/rasterio/xarray | Docker, Python |
| **EN6.2**: Container deployment | EN6 | Azure Container App or Web App | Azure, DevOps |
| **EN6.3**: Service Bus queue | EN6 | Create `long-running-raster-tasks` queue | Azure Service Bus |
| **EN6.4**: Queue listener | EN6 | Implement in Docker worker | Python, Service Bus SDK |
| **F7.2.1**: Create ADF instance | E7 | `az datafactory create` in rmhazure_rg | Azure Data Factory |
| **F7.3.1**: External storage account | E7 | New storage for public data | Azure Storage |
| **F7.3.2**: Cloudflare WAF rules | E7 | Rate limiting, geo-blocking | Cloudflare |

### Ready After Dependencies

| Task | Epic | Depends On | Description |
|------|------|------------|-------------|
| S9.3.3-6: UAT provisioning | E9 | S9.3.2 | Replicate QA setup to UAT |
| EN6.5: Routing logic | EN6 | EN6.1-4 | Dispatch oversized jobs to Docker worker |
| F7.2.3: Blob-to-blob copy | E7 | F7.2.1 | ADF copy activity |
| F7.2.4: Approve trigger | E7 | F7.1 | Trigger ADF from approval endpoint |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 28 DEC 2025 | **E13 Pipeline Observability DESIGNED** - Universal metrics + H3/FATHOM contexts | E13 |
| 28 DEC 2025 | **H3 Phase 1 COMPLETE** - source_catalog, repository, API, dynamic tile discovery | E8 |
| 27 DEC 2025 | **Vector Workflow UI COMPLETE** - Submit Vector + Promote interfaces polished | E12 |
| 27 DEC 2025 | Timestamps standardized to Eastern Time across all interfaces | E12 |
| 27 DEC 2025 | Architecture diagram v2 created (grid layout, component mapping) | — |
| 24 DEC 2025 | **F12.3 Migration COMPLETE** - All 14 standard interfaces HTMX-enabled | E12 |
| 24 DEC 2025 | S12.3.3-5: STAC, Vector, H3, Health, Pipeline, Platform, Docs, Queues, Gallery, Home | E12 |
| 24 DEC 2025 | Jobs/Tasks interfaces migrated to HTMX (S12.3.1-2) | E12 |
| 23 DEC 2025 | F12.1 Cleanup complete (COMMON_CSS, COMMON_JS, component helpers) | E12 |
| 23 DEC 2025 | F12.2 HTMX complete (Storage + Submit Vector interfaces) | E12 |
| 23 DEC 2025 | Interface audit, E12 epic created, NICEGUI.md documentation | E12 |
| 21 DEC 2025 | FATHOM Phase 1 complete (CI), Phase 2 46/47 tasks | E10.F10.1-2 |
| 21 DEC 2025 | Fixed dict_row + source_container bugs in fathom_etl.py | E10 |
| 20 DEC 2025 | Swagger UI + OpenAPI spec (19 endpoints, 20 schemas) | E3.F3.1 |
| 18 DEC 2025 | OGC API Styles module | E5.F5.1 |
| 18 DEC 2025 | Service Layer API Phase 4 | E2.F2.5 |
| 12 DEC 2025 | Unpublish workflows | E1.F1.4, E2.F2.4 |
| 11 DEC 2025 | Service Bus queue standardization | EN3 |
| 07 DEC 2025 | Container inventory consolidation | E6 |
| DEC 2025 | PgSTAC Repository Consolidation | EN (completed) |

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [EPICS.md](/EPICS.md) | Master Epic/Feature/Story definitions |
| [HISTORY.md](./HISTORY.md) | Full completion log |
| [READER_MIGRATION_PLAN.md](/READER_MIGRATION_PLAN.md) | F3.3 implementation guide |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [NICEGUI.md](./NICEGUI.md) | E12 Interface Modernization (HTMX + NiceGUI) |

---

**Workflow**:
1. Pick task from "Current Sprint Focus" or "DevOps Tasks"
2. Update status here as work progresses
3. Reference EPICS.md for acceptance criteria
4. Log completion in HISTORY.md
