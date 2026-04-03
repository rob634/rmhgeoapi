# Geospatial Backend Solution — Product Overview

**Version**: v0.10.9 | **Last Updated**: 03 APR 2026

---

## What This Is

The Geospatial Backend Solution is a cloud-native ETL platform on Azure that turns raw geospatial data into standards-compliant APIs. Upload a GeoTIFF, Shapefile, GeoPackage, NetCDF, or Zarr store — the platform validates it, transforms it into an analysis-ready format, and serves it through industry-standard APIs that any GIS client can consume.

Data flows through a **Bronze-Silver-Gold** storage tier model:
- **Bronze**: Raw uploaded files (Azure Blob Storage)
- **Silver**: Processed data — Cloud-Optimized GeoTIFFs in blob storage, vector tables in PostGIS, rechunked Zarr v3 stores in blob storage
- **Gold**: Published exports and aggregations (future)

The platform exposes processed data through three API surfaces:
- **OGC API - Features** (via TiPG) — vector data queries with spatial filtering
- **STAC API** (via pgSTAC) — spatiotemporal metadata search and discovery for raster and Zarr
- **TiTiler** — dynamic map tile rendering for raster COGs and Zarr stores

---

## Architecture

The system runs as four Azure apps sharing one PostgreSQL database:

```
                    +-----------------------+
                    |   Function App        |
                    |   (rmhazuregeoapi)    |
                    |   Gateway + REST API  |
                    +-----------+-----------+
                                |
                    +-----------+-----------+
                    |    PostgreSQL          |
                    |    (geopgflex)         |
                    |    Single source of    |
                    |    truth for all state |
                    +-----------+-----------+
                       /                  \
          +-----------+------+    +-------+----------+
          |   DAG Brain      |    |   Docker Worker   |
          |   (rmhdagmaster) |    |   (rmhheavyapi)   |
          |   Orchestrates   |    |   Heavy compute   |
          |   workflows      |    |   (GDAL, xarray)  |
          +------------------+    +-------------------+
                                          |
                              +-----------+-----------+
                              |   TiTiler             |
                              |   (rmhtitiler)        |
                              |   Dynamic tiles from  |
                              |   COGs + Zarr stores  |
                              +-----------------------+
```

**DAG Brain** and **Docker Worker** share the same Docker image (`geospatial-worker`). The `APP_MODE` environment variable selects behavior. Workers poll PostgreSQL for tasks using `SELECT ... FOR UPDATE SKIP LOCKED` — no message queues in the target architecture.

**Architecture migration (Strangler Fig)**: The platform is migrating from Epoch 4 (Service Bus + Function App orchestration) to Epoch 5 (DAG Brain + PostgreSQL polling). Epoch 5 is ~95% complete with 10 YAML workflows and 58 handlers proven end-to-end on Azure. Legacy removal is targeted at v0.11.0.

---

## What It Processes

| Data Type | Input Formats | Output Format | Storage | API Surface |
|-----------|--------------|---------------|---------|-------------|
| **Vector** | Shapefile, GeoJSON, GeoPackage, CSV, KML | PostGIS tables | PostgreSQL (geo schema) | OGC API - Features (TiPG) |
| **Raster** | GeoTIFF | Cloud-Optimized GeoTIFF (COG) | Azure Blob (silver) | STAC + TiTiler tiles |
| **Multidimensional** | NetCDF, Zarr | Flat Zarr v3 (256x256 spatial, time=1) | Azure Blob (silver-zarr) | STAC + TiTiler xarray |

---

## Feature Map

| # | Feature | Status | What It Does |
|---|---------|--------|-------------|
| F1 | [Vector Data & Serving](EPICS.md#f1-vector-data--serving) | Operational | Ingest vector files into PostGIS, serve via OGC Features |
| F2 | [Raster Data & Serving](EPICS.md#f2-raster-data--serving) | Operational | Convert GeoTIFFs to COGs, serve via STAC + TiTiler |
| F3 | [Multidimensional Data & Serving](EPICS.md#f3-multidimensional-data--serving) | Partial | Ingest NetCDF/Zarr, rechunk, serve via TiTiler xarray |
| F4 | [Asset Lifecycle Management](EPICS.md#f4-asset-lifecycle-management) | Operational | Approval workflow, versioning, unpublish, audit trail |
| F5 | [Platform & Operations](EPICS.md#f5-platform--operations) | Operational | DAG engine, admin UI, observability, deployment |

Full SAFe registry: [EPICS.md](EPICS.md)

---

## Architecture Migration

### Where We Came From (Epoch 4)
- Azure Function App orchestration with `CoreMachine` state machine
- Azure Service Bus for job/task messaging (3 queues)
- Monolithic Python handler classes (one handler per data type)
- Stage-based sequential pipeline with parallel tasks within stages

### Where We Are (Epoch 5 — v0.10.9)
- DAG Brain orchestrates YAML-defined workflows via PostgreSQL advisory locks
- Docker Workers poll for tasks using SKIP LOCKED (no message queues)
- 58 atomic handlers composed into 10 workflows
- Conditional routing, fan-out/fan-in parallelization, approval gates, best-effort tasks
- Legacy CoreMachine + Service Bus still present but in maintenance mode

### Where We're Going (v0.11.0)
- Complete strangler fig: delete CoreMachine, Service Bus triggers, Epoch 4 job classes
- DAG Brain is sole orchestrator
- Function App becomes gateway only — all orchestration in Docker apps

---

## Quality Assurance

The platform has been validated through a multi-agent adversarial review pipeline:

| Pipeline | Purpose | Runs | Methodology |
|----------|---------|:----:|-------------|
| **COMPETE** | Adversarial code review | 70 | Two agents debate findings; third judges |
| **SIEGE** | Live integration testing | 5 | End-to-end sequences against Azure deployment |
| **REFLEXION** | Targeted deep analysis | 17 | Reverse engineer, fault inject, patch, judge |
| **TOURNAMENT** | Full-spectrum adversarial | 1 | 87.2% score across all dimensions |
| **ADVOCATE** | B2B developer experience | 1 | 25 friction points identified and triaged |

**Results**: 83 total fixes applied (74 COMPETE + 9 SIEGE integration fixes). SIEGE-DAG Run 5 achieved 84% pass rate with 2 bugs found and fixed. All critical and high-severity findings resolved.

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Gateway** | Azure Functions (Python 3.12) | HTTP API, Service Bus triggers |
| **Orchestration** | Custom DAG engine (Python) | YAML workflow execution |
| **Compute** | Docker on Azure App Service | GDAL, geopandas, xarray, rasterio |
| **Database** | PostgreSQL 17 + PostGIS | Vector storage, job state, STAC catalog |
| **STAC Catalog** | pgSTAC | Spatiotemporal metadata search |
| **Tile Serving** | TiTiler (titiler-pgstac 2.1.0) | Dynamic COG + Zarr tile rendering |
| **Vector API** | TiPG | OGC API - Features from PostGIS |
| **Blob Storage** | Azure Blob Storage | Bronze (raw), Silver (processed) tiers |
| **Container Registry** | Azure Container Registry | geospatial-worker Docker image |
| **Observability** | Azure Application Insights | Structured logging, KQL queries |
| **Admin UI** | Jinja2 + HTMX | DAG Brain dashboard (no JavaScript frameworks) |

---

## Deployment Model

Four Azure apps deployed via `deploy.sh`:

| App | Name | APP_MODE | Deploy Command |
|-----|------|----------|---------------|
| Function App | rmhazuregeoapi | standalone | `./deploy.sh orchestrator` |
| DAG Brain | rmhdagmaster | orchestrator | `./deploy.sh dagbrain` |
| Docker Worker | rmhheavyapi | worker_docker | `./deploy.sh docker` |
| TiTiler | rmhtitiler | — | External (titiler-pgstac) |

DAG Brain and Docker Worker share the same ACR image — deploy both together when updating.

Full deployment guide: [docs_claude/DEPLOYMENT_GUIDE.md](../docs_claude/DEPLOYMENT_GUIDE.md)

---

## Key Documentation

| Document | Purpose |
|----------|---------|
| [EPICS.md](EPICS.md) | SAFe Feature & Story registry |
| [CLAUDE_CONTEXT.md](../docs_claude/CLAUDE_CONTEXT.md) | Technical context for development |
| [ARCHITECTURE_REFERENCE.md](../docs_claude/ARCHITECTURE_REFERENCE.md) | Deep technical architecture |
| [WORKFLOW_YAML_REFERENCE.md](../docs_claude/WORKFLOW_YAML_REFERENCE.md) | DAG workflow YAML specification |
| [DEPLOYMENT_GUIDE.md](../docs_claude/DEPLOYMENT_GUIDE.md) | Deployment procedures |
| [ERRORS_AND_FIXES.md](../docs_claude/ERRORS_AND_FIXES.md) | Error catalog and resolutions |
