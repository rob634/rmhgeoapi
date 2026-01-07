# Working Backlog

**Last Updated**: 06 JAN 2026
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) — Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| **1** | E9 | **FATHOM Rwanda Pipeline** | 🚧 | F9.1: Rwanda inventory + processing |
| **2** | E8 | **H3 Analytics (Rwanda)** | 📋 | F8.13: Rwanda H3 aggregation |
| **3** | E8 | **Open Buildings Access** | 📋 | F8.7: Building Exposure Pipeline |
| 4 | E9 | Pre-prepared Raster Ingest | 📋 | F9.8: COG copy + STAC |
| 5 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 6 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| 7 | E1 | Vector Data as API | 🚧 | F1.8: ETL Style Integration |
| — | E7 | Pipeline Builder | 📋 | F7.5: Future (after concrete implementations) |

**Focus**: Rwanda as test region for all analytics pipelines before scaling.

---

## Current Sprint Focus

### 🔴 Priority 1: FATHOM Rwanda Pipeline

**Epic**: E9 Large Data Hosting
**Goal**: End-to-end FATHOM processing on Rwanda data (1,872 TIF files, 1.85 GB)
**Test Region**: Rwanda (6 tiles: s01e030, s02e029, s02e030, s03e028, s03e029, s03e030)

#### Rwanda Data Dimensions

| Dimension | Values |
|-----------|--------|
| Flood Types | FLUVIAL_DEFENDED, FLUVIAL_UNDEFENDED, PLUVIAL_DEFENDED |
| Years | 2020, 2030, 2050, 2080 |
| SSP Scenarios | SSP1_2.6, SSP2_4.5, SSP3_7.0, SSP5_8.5 (future only) |
| Return Periods | 1in5, 1in10, 1in20, 1in50, 1in100, 1in200, 1in500, 1in1000 |
| Tiles | 6 tiles covering Rwanda |

#### F9.1: FATHOM Rwanda Processing

| Story | Description | Status |
|-------|-------------|--------|
| S9.1.R1 | Add `base_prefix` parameter to `inventory_fathom_container` job | 📋 |
| S9.1.R2 | Deploy and run inventory for Rwanda (`base_prefix: "rwa"`) | 📋 |
| S9.1.R3 | Run Phase 1 band stacking (8 return periods → 1 COG per scenario) | 📋 |
| S9.1.R4 | Run Phase 2 spatial merge (6 tiles → merged COGs) | 📋 |
| S9.1.R5 | Verify outputs in silver-fathom storage | 📋 |
| S9.1.R6 | Register merged COGs in STAC catalog | 📋 |
| S9.1.R7 | Change FATHOM grid from 5×5 to 4×4 degrees | ✅ Done (06 JAN) |

**NEXT SESSION (07 JAN 2026)**: Deploy with 4×4 grid and rerun full RWA pipeline from inventory.

**Expected Outputs**:
- Phase 1: ~1,924 stacked COGs (44 tiles × ~44 scenarios)
- Phase 2: ~312 merged COGs (with 4×4 grid: max 16 tiles per merge, ~3-4 GB peak memory)

**Key Files**:
- `jobs/inventory_fathom_container.py` - Needs `base_prefix` parameter
- `services/fathom_container_inventory.py` - Handler already supports `base_prefix`
- `jobs/process_fathom_stack.py` - Phase 1 job
- `jobs/process_fathom_merge.py` - Phase 2 job

---

### 🟡 Priority 2: H3 Analytics on Rwanda

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: H3 aggregation of FATHOM flood data for Rwanda
**Dependency**: F9.1 (FATHOM merged COGs must exist in STAC)

#### F8.13: Rwanda H3 Aggregation (NEW)

| Story | Description | Status |
|-------|-------------|--------|
| S8.13.1 | Seed Rwanda H3 cells (res 4-7, country-filtered) | 📋 |
| S8.13.2 | Add FATHOM merged COGs to source_catalog | 📋 |
| S8.13.3 | Run H3 raster aggregation on Rwanda FATHOM | 📋 |
| S8.13.4 | Verify zonal_stats populated for flood themes | 📋 |
| S8.13.5 | Test H3 export endpoint with Rwanda data | 📋 |

**H3 Theme Structure** (flood data):
```
themes:
  flood_risk:
    - fathom_fluvial_defended_2020_1in100
    - fathom_fluvial_defended_2050_ssp245_1in100
    - fathom_pluvial_defended_2020_1in100
    ...
```

**Key Files**:
- `services/h3_aggregation/` - Aggregation handlers
- `jobs/h3_raster_aggregation.py` - Main job
- `core/models/h3_sources.py` - source_catalog entries

---

### 🟢 Priority 3: Open Buildings Access

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: Access building footprints for Rwanda to enable exposure analysis
**Dependency**: F8.13 (H3 aggregation working)

#### F8.7: Building Exposure Pipeline

| Story | Description | Status |
|-------|-------------|--------|
| S8.7.1 | Verify Planetary Computer MS Buildings access | 📋 |
| S8.7.2 | Alternative: Verify Google Open Buildings GCS access | 📋 |
| S8.7.3 | Download/filter Rwanda building footprints | 📋 |
| S8.7.4 | Ingest buildings to PostGIS (geo schema) | 📋 |
| S8.7.5 | Vector→H3 aggregation (building count per cell) | 📋 |
| S8.7.6 | Join buildings + flood depth for exposure analysis | 📋 |
| S8.7.7 | Export building exposure by H3 cell | 📋 |

**Data Sources**:
- Microsoft Building Footprints: `https://planetarycomputer.microsoft.com/dataset/ms-buildings`
- Google Open Buildings: `gs://open-buildings-data/v3/`

**Output**: Buildings at flood risk by return period, H3 resolution, and climate scenario.

---

### ⚪ Future: Pipeline Builder (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Generalize FATHOM pipeline to configuration-driven raster processing
**Timeline**: After FATHOM + H3 + Open Buildings working on Rwanda

#### F7.5: Pipeline Builder

| Story | Description | Status |
|-------|-------------|--------|
| S7.5.1 | Abstract FATHOM dimension parser to configuration | 📋 |
| S7.5.2 | Create `ComplexRasterPipeline` base class | 📋 |
| S7.5.3 | YAML/JSON pipeline definition schema | 📋 |
| S7.5.4 | Pipeline Builder UI (visual orchestration) | 📋 |

**Design Principle**: Build concrete implementations first (FATHOM, H3, Buildings), then extract patterns.

---

## Other Active Work

### E9: Large Data Hosting

| Feature | Description | Status |
|---------|-------------|--------|
| F9.1: FATHOM ETL | Band stacking + spatial merge | 🚧 Rwanda focus |
| F9.5: xarray Service | Time-series endpoints | ✅ Complete |
| F9.6: TiTiler Services | COG + Zarr tile serving | 🚧 TiTiler-xarray deployed 04 JAN |
| F9.8: Pre-prepared Ingest | COG copy + STAC from params | 📋 After Rwanda |

### E8: GeoAnalytics Pipeline

| Feature | Description | Status |
|---------|-------------|--------|
| F8.1-F8.3 | Grid infrastructure, bootstrap, raster aggregation | ✅ Complete |
| F8.8 | Source Catalog | ✅ Complete |
| F8.9 | H3 Export Pipeline | ✅ Complete |
| F8.13 | **Rwanda H3 Aggregation** | 📋 Priority 2 |
| F8.7 | **Building Exposure Pipeline** | 📋 Priority 3 |
| F8.4 | Vector→H3 Aggregation | 📋 After buildings |
| F8.5-F8.6 | GeoParquet, Analytics API | 📋 After Rwanda |

### E2: Raster Data as API

| Story | Description | Status |
|-------|-------------|--------|
| S2.2.5 | Fix TiTiler URLs for >3 band rasters | ✅ Complete (stac_metadata_helper.py bidx handling) |
| S2.2.6 | Auto-rescale DEM TiTiler URLs | ✅ Complete (04 JAN 2026, smart dtype defaults) |
| F2.9 | STAC-Integrated Raster Viewer | 📋 |

### E3: DDH Platform Integration

| Feature | Description | Status |
|---------|-------------|--------|
| F3.1 | API Docs (Swagger UI) | ✅ Deployed |
| F3.2 | Identity (DDH service principal) | 📋 |
| F3.3 | Environments (QA/UAT/Prod) | 📋 |

### E12: Interface Modernization

| Feature | Description | Status |
|---------|-------------|--------|
| F12.1-F12.3 | Cleanup, HTMX, Migration | ✅ Complete |
| F12.4 | NiceGUI Evaluation | 📋 Future |

---

## System Diagnostics & Configuration Drift Detection

**Added**: 04 JAN 2026
**Purpose**: Capture Azure platform configuration snapshots to detect changes in corporate environments

### Background

Corporate Azure environments (ASE, VNet) have configurations that can change without warning.
The enhanced health endpoint now captures 90+ environment variables. System snapshots will
persist this data for drift detection and audit trails.

### Completed (04 JAN 2026)

| Task | Description | Status |
|------|-------------|--------|
| Database schema | `app.system_snapshots` table with Pydantic model | ✅ |
| SQL generator | Enum, table, indexes added to `sql_generator.py` | ✅ |
| Health: network_environment | Captures all WEBSITE_*/AZURE_* vars | ✅ Deployed |
| Health: instance_info | Instance ID, worker config, cold start detection | ✅ Committed |
| Scale controller logging | `SCALE_CONTROLLER_LOGGING_ENABLED=AppInsights:Verbose` | ✅ Enabled |
| Blueprint pattern investigation | Reviewed probes.py; snapshot follows same Blueprint pattern | ✅ |
| Snapshot capture service | `services/snapshot_service.py` - capture + drift detection | ✅ |
| Config hash computation | SHA256 of stable config fields for drift detection | ✅ |
| Drift diff computation | Compare current vs previous snapshot, identify changes | ✅ |
| Startup trigger | Capture snapshot in `function_app.py` after Phase 2 validation | ✅ |
| Scheduled trigger | Timer trigger (hourly) in `function_app.py` | ✅ |
| Manual trigger | `POST /api/system/snapshot` + `GET /api/system/snapshot/drift` | ✅ |
| Version bump | 0.7.2.1 → 0.7.3 | ✅ |

### Pending Deployment

| Task | Description | Priority |
|------|-------------|----------|
| Deploy changes | Deploy v0.7.3 to Azure | 🔴 High |
| Deploy schema | Run full-rebuild to create `system_snapshots` table | 🔴 High |
| Verify endpoints | Test `/api/admin/snapshot` endpoints | 🟡 Medium |

### Snapshot Trigger Types

| Trigger | When | Purpose |
|---------|------|---------|
| `startup` | App cold start | Baseline for each instance |
| `scheduled` | Timer (hourly) | Detect drift over time |
| `manual` | Admin endpoint | On-demand debugging |
| `drift_detected` | Hash changed | Record moment of change |

### Key Files

| File | Purpose |
|------|---------|
| `core/models/system_snapshot.py` | Pydantic model + SnapshotTriggerType enum |
| `core/schema/sql_generator.py` | DDL generation for system_snapshots table |
| `services/snapshot_service.py` | SnapshotService + SnapshotRepository |
| `triggers/admin/snapshot.py` | Blueprint with HTTP endpoints |
| `function_app.py` | Timer trigger + startup capture (lines 2484-2504, 3352-3395) |

### Application Insights Queries

```kusto
-- Scale controller decisions
traces
| where customDimensions.Category == "ScaleControllerLogs"
| where message == "Instance count changed"
| project timestamp,
    PreviousCount = customDimensions.PreviousInstanceCount,
    NewCount = customDimensions.CurrentInstanceCount,
    Reason = customDimensions.Reason

-- Active instances in last 30 min
performanceCounters
| where timestamp > ago(30m)
| summarize LastSeen=max(timestamp) by cloud_RoleInstance
| order by LastSeen desc
```

---

## Thread Safety Investigation

**Added**: 05 JAN 2026
**Trigger**: KeyError race condition in BlobRepository when scaled to 8 instances
**Status**: Initial fix applied, broader investigation needed

### Background

With `maxConcurrentCalls: 4` and 8 instances = 32 parallel task executions, we hit race conditions in BlobRepository's container client caching. Root cause: **check-then-act pattern without locking**.

### Key Concepts (05 JAN 2026 Discussion)

| Coordination Type | Scope | Lock Mechanism | Example |
|-------------------|-------|----------------|---------|
| **Distributed** | Across instances/processes | PostgreSQL `pg_advisory_xact_lock` | "Last task turns out lights" |
| **Local** | Within single process | Python `threading.Lock` | Dict caching in singletons |

**Why PostgreSQL can't help with local coordination**: The `_container_clients` dict exists only in Python process memory. PostgreSQL can only lock things it knows about (database rows/tables).

**The race condition pattern**:
```python
# UNSAFE: Three separate bytecode ops, GIL releases between them
if key not in dict:      # ① CHECK
    dict[key] = value    # ② STORE (may trigger dict resize!)
return dict[key]         # ③ RETURN (KeyError during resize!)
```

**The fix (double-checked locking)**:
```python
# SAFE: Lock protects entire sequence
if key in dict:                    # Fast path (no lock)
    return dict[key]
with lock:                         # Slow path (locked)
    if key not in dict:            # Double-check
        dict[key] = create_value()
    return dict[key]
```

### Completed (05 JAN 2026)

| Task | Description | Status |
|------|-------------|--------|
| BlobRepository fix | Added `_instances_lock` and `_container_clients_lock` | ✅ |
| Double-checked locking | `_get_container_client()` uses fast path + locked slow path | ✅ |
| Documentation | Explained pattern in docstrings | ✅ |

### Future Investigation

| Area | Concern | Priority |
|------|---------|----------|
| Other singletons | PostgreSQLRepository, other repos - same pattern? | 🟡 Medium |
| GDAL/rasterio threading | GDAL releases GIL - potential issues with concurrent raster ops | 🟡 Medium |
| Connection pools | psycopg3 pool thread safety under high concurrency | 🟡 Medium |
| Azure SDK clients | BlobServiceClient thread safety documentation | 🟢 Low |

### Key Files

| File | What Was Fixed |
|------|----------------|
| `infrastructure/blob.py` | `_instances_lock`, `_container_clients_lock`, double-checked locking |

### Related Context

- **CoreMachine uses PostgreSQL advisory locks** for distributed coordination (see `core/state_manager.py`, `core/schema/sql_generator.py`)
- **OOM concerns** have historically limited multi-threading exploration
- **GDAL threading issues** are separate from Python GIL (GDAL has own thread pool)

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| S9.2.2 | E9 | Create DDH service principal | Azure AD, IAM |
| S9.2.3 | E9 | Grant blob read access | Azure RBAC |
| EN6.1 | EN6 | Docker image with GDAL/rasterio | Docker, Python |
| EN6.2 | EN6 | Container deployment | Azure, DevOps |
| F7.2.1 | E7 | Create ADF instance | Azure Data Factory |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 05 JAN 2026 | **Docstring Review COMPLETE** (236/236 stable files, archived to docs_claude/) | — |
| 05 JAN 2026 | Thread-safety fixes for BlobRepository (concurrent pipeline support) | — |
| 05 JAN 2026 | FATHOM tile deduplication bug fix (8x duplicates) | E9 |
| 05 JAN 2026 | Database admin interface added to web_interfaces | E12 |
| 04 JAN 2026 | S2.2.5: Multi-band TiTiler URLs with bidx params | E2 |
| 04 JAN 2026 | S2.2.6: Auto-rescale for DEMs and non-uint8 rasters | E2 |
| 04 JAN 2026 | TiTiler-xarray deployed to DEV (Zarr tile serving) | E9 |
| 04 JAN 2026 | System snapshots schema (Pydantic model + DDL) | — |
| 04 JAN 2026 | Health: network_environment (90+ Azure vars) | — |
| 04 JAN 2026 | Health: instance_info (cold start detection) | — |
| 04 JAN 2026 | Scale controller logging enabled | — |
| 04 JAN 2026 | SERVICE_BUS_NAMESPACE explicit env var | — |
| 04 JAN 2026 | Version bump to 0.7.1 | — |
| 03 JAN 2026 | STARTUP_REFORM.md Phases 1-4 (livez/readyz probes) | — |
| 03 JAN 2026 | Blueprint refactor for probes.py | — |
| 30 DEC 2025 | Platform API Submit UI COMPLETE | E3 |
| 29 DEC 2025 | Epic Consolidation (E10,E11,E13,E14,E15 absorbed) | — |
| 29 DEC 2025 | F7.5 Collection Ingestion COMPLETE | E7 |
| 28 DEC 2025 | F8.12 H3 Export Pipeline COMPLETE | E8 |
| 28 DEC 2025 | F7.6 Pipeline Observability COMPLETE | E7 |
| 28 DEC 2025 | F8.8 Source Catalog COMPLETE | E8 |
| 24 DEC 2025 | F12.3 Migration COMPLETE (14 interfaces HTMX) | E12 |
| 21 DEC 2025 | FATHOM Phase 1 complete (CI), Phase 2 46/47 | E7 |

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |
| [H3_REVIEW.md](./H3_REVIEW.md) | H3 aggregation implementation |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |

---

**Workflow**:
1. Complete Rwanda FATHOM pipeline (Priority 1)
2. Run H3 aggregation on FATHOM outputs (Priority 2)
3. Access Open Buildings, join with flood data (Priority 3)
4. Generalize to Pipeline Builder (Future)
