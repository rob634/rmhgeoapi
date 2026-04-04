# SAFe Documentation Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create 7 new SAFe documentation files in `docs/product/` that accurately represent the Geospatial Backend Solution platform as of v0.10.9.

**Architecture:** One Epic (Geospatial Backend Solution), 5 Features organized by audience persona (data scientists, data owners, platform operators), plus Enablers. Master registry (`EPICS.md`) stays stable; volatile story detail lives in separate docs per feature. A `PRODUCT_OVERVIEW.md` narrative ties it together.

**Tech Stack:** Markdown, SAFe Agile Framework, Mermaid diagrams

**Spec:** `docs/superpowers/specs/2026-04-03-safe-documentation-redesign.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `docs/product/PRODUCT_OVERVIEW.md` | Narrative overview — "read this first" |
| Create | `docs/product/EPICS.md` | Master SAFe registry — 1 Epic, 5 Features, Enablers, story index |
| Create | `docs/product/STORIES_F1_VECTOR.md` | Vector Data & Serving story detail |
| Create | `docs/product/STORIES_F2_RASTER.md` | Raster Data & Serving story detail |
| Create | `docs/product/STORIES_F3_MULTIDIM.md` | Multidimensional Data & Serving story detail |
| Create | `docs/product/STORIES_F4_LIFECYCLE.md` | Asset Lifecycle Management story detail |
| Create | `docs/product/STORIES_F5_PLATFORM.md` | Platform & Operations story detail |

---

## Task 1: Create directory and EPICS.md (master registry)

EPICS.md defines the canonical IDs that all other docs reference. Write this first.

**Files:**
- Create: `docs/product/EPICS.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p docs/product
```

- [ ] **Step 2: Write EPICS.md**

Create `docs/product/EPICS.md` with the following content. This is the master registry — Epic-to-Feature level only. No story detail. Must survive 3 months without update.

Research sources: All 6 subagent reports from this conversation (handler catalog, workflow inventory, API surface, history timeline, architecture summary, old EPICS gap analysis).

```markdown
# SAFe Epic & Feature Registry

**Last Updated**: 03 APR 2026

---

## Epic: Geospatial Backend Solution

**Epic ID**: [TBD]
**Version**: v0.10.9
**Status**: Operational — Epoch 5 DAG migration ~95% complete

### Description

A cloud-native geospatial ETL platform on Azure that processes raster, vector, and multidimensional data into standards-compliant APIs. Raw data flows through a Bronze-Silver-Gold storage tier model, orchestrated by a YAML-defined DAG workflow engine backed by PostgreSQL. The platform serves processed data through OGC API - Features (via TiPG), STAC API (via pgSTAC), and dynamic tile rendering (via TiTiler).

The system runs as four Azure apps sharing one PostgreSQL database as the single source of truth. Workers poll for tasks using SKIP LOCKED — no message queues in the target architecture. A strangler fig migration from the legacy Service Bus + Function App architecture (Epoch 4) to the DAG Brain + Docker Worker architecture (Epoch 5) is ~95% complete, with full removal targeted at v0.11.0.

---

## Feature Summary

| # | Feature | Status | Stories | Persona |
|---|---------|--------|:-------:|---------|
| F1 | Vector Data & Serving | Operational | 12 | Data Scientists |
| F2 | Raster Data & Serving | Operational | 14 | Data Scientists |
| F3 | Multidimensional Data & Serving | Partial | 10 | Data Scientists |
| F4 | Asset Lifecycle Management | Operational | 8 | Data Owners |
| F5 | Platform & Operations | Operational | 11 | Platform Operators |

**Total**: 55 stories across 5 features. 8 enablers.

---

## F1: Vector Data & Serving

**Status**: Operational
**Persona**: Data scientists with vector geospatial data (shapefiles, GeoJSON, GeoPackage, CSV, KML)

End-to-end pipeline that ingests vector files into PostGIS and exposes them as OGC API - Features collections via TiPG. Supports single-file, multi-file, multi-layer GeoPackage, and categorical split views. Includes a scheduled ACLED conflict data sync as a reference implementation for API-driven recurring workflows. All vector workflows run on the Epoch 5 DAG engine with atomic handlers.

**Key capabilities**: 6 input formats, split views (1 file to N OGC collections), multi-source (N files to N tables), two-phase TiPG discovery (browsable pre-approval, searchable post-approval), symmetric unpublish, scheduled API sync.

**Stories**: [STORIES_F1_VECTOR.md](STORIES_F1_VECTOR.md)

---

## F2: Raster Data & Serving

**Status**: Operational
**Persona**: Data scientists with raster geospatial data (GeoTIFF, elevation models, satellite imagery)

End-to-end pipeline that converts GeoTIFF files into Cloud-Optimized GeoTIFFs (COGs) with STAC metadata, served through TiTiler for dynamic tile rendering. Handles single files, large rasters (>2GB with automatic tiling via fan-out/fan-in), and multi-file collections (5 fan-out/fan-in phases). The raster DAG workflow is the most complex in the system at 12 nodes with conditional size-based routing.

**Key capabilities**: Single and tiled COG creation, 3 compression tiers (analysis/visualization/archive), collection pipeline with homogeneity checking, STAC + pgSTAC search registration, point/clip/preview extraction API, FATHOM flood data ETL.

**Stories**: [STORIES_F2_RASTER.md](STORIES_F2_RASTER.md)

---

## F3: Multidimensional Data & Serving

**Status**: Partial — core pipelines operational, CMIP6 hosting and unified TiTiler planned
**Persona**: Data scientists with climate/weather NetCDF or Zarr data

Pipelines for ingesting NetCDF and Zarr stores into rechunked flat Zarr v3 format optimized for cloud-native tile serving via TiTiler xarray. Supports two ingest paths: native Zarr (cloud-native passthrough for abfs:// URLs) and NetCDF-to-Zarr conversion with spatial 256x256, time=1 chunking. Includes VirtualiZarr for lazy Kerchunk-style reference stores. Zarr v3 metadata consolidation fix ensures xarray compatibility.

**Key capabilities**: Native Zarr ingest (cloud passthrough), NetCDF conversion with rechunking, VirtualiZarr references, TiTiler xarray tile serving, xarray service layer (point queries, statistics, aggregation), Zarr-specific observability checkpoints.

**Stories**: [STORIES_F3_MULTIDIM.md](STORIES_F3_MULTIDIM.md)

---

## F4: Asset Lifecycle Management

**Status**: Operational
**Persona**: Data owners who submit, approve, version, and unpublish datasets

The governance layer that tracks every dataset from submission through approval to potential revocation. Built on an Asset/Release entity model where Assets are stable identity containers and Releases are versioned submissions with an approval state machine (draft to approved to revoked). STAC metadata is cached at ETL time but only published to pgSTAC at approval — deferred materialization keeps the catalog clean. Symmetric unpublish pipelines exist for all three data types.

**Key capabilities**: Asset/Release entity split, 3-state approval workflow, deferred STAC materialization, append-only release audit trail, version ordinal management, services block gating (services=null until approval), symmetric unpublish for raster/vector/zarr.

**Stories**: [STORIES_F4_LIFECYCLE.md](STORIES_F4_LIFECYCLE.md)

---

## F5: Platform & Operations

**Status**: Operational
**Persona**: Platform operators who deploy, monitor, and administer the system

The orchestration engine and operational tooling that powers all data pipelines. A YAML-defined DAG workflow engine with conditional routing, fan-out/fan-in parallelization, approval gates, and parameter resolution drives all Epoch 5 workflows. The DAG Brain admin UI provides dashboard, job submission, approval management, and handler inspection. 115+ API endpoints serve platform, STAC, DAG, admin, and OGC Features functions. A 3-tier observability system (inline logging, structured checkpoints, status integration) feeds Azure Application Insights.

**Key capabilities**: DAG orchestration engine (10 workflows, 58 handlers), admin UI (HTMX/Jinja2), scheduled workflows (cron), health/preflight system (20 checks), 3-tier observability, schema management (ensure/rebuild), COMPETE/SIEGE adversarial quality pipeline (70+ reviews, 83 fixes).

**Stories**: [STORIES_F5_PLATFORM.md](STORIES_F5_PLATFORM.md)

---

## Enablers

| ID | Name | Status | Enables | Key Components |
|----|------|--------|---------|---------------|
| EN1 | Database Architecture | Done | All | 5-schema PostgreSQL (app, platform, pgstac, geo, h3), Pydantic-to-SQL DDL generation |
| EN2 | Connection Pool & Auth | Done | All | ManagedIdentityAuth, ConnectionManager, circuit breaker, transient retry |
| EN3 | Docker Worker Infrastructure | Done | F1-F3, F5 | ACR image (geospatial-worker), APP_MODE routing, SKIP LOCKED polling |
| EN4 | Configuration System | Done | All | Modular Pydantic config (storage, database, queue, raster, vector, platform, metrics) |
| EN5 | Deployment Tooling | Done | All | deploy.sh (orchestrator/dagbrain/docker/all), health checks, version verification |
| EN6 | Azure Blob Storage | Done | F1-F3 | BlobRepository, zone-based auth (bronze/silver), SAS URL generation |
| EN7 | Service Bus | Deprecated | Legacy | 3 queues (geospatial-jobs, functionapp-tasks, container-tasks) — removal in v0.11.0 |
| EN8 | Pre-flight Validation | Done | F1-F3 | blob_exists, blob_exists_with_size, collection_exists, YAML validators |

---

## Story Index

All stories at a glance. Detail in each feature's STORIES doc.

| ID | Story | Feature | Status |
|----|-------|---------|--------|
| S1.1 | Vector ETL pipeline | F1 | Done |
| S1.2 | OGC Features API | F1 | Done |
| S1.3 | Multi-format support | F1 | Done |
| S1.4 | Split views | F1 | Done |
| S1.5 | Multi-source vector | F1 | Done |
| S1.6 | TiPG two-phase discovery | F1 | Done |
| S1.7 | Vector unpublish pipeline | F1 | Done |
| S1.8 | ACLED scheduled sync | F1 | Done |
| S1.9 | Catalog registration | F1 | Done |
| S1.10 | Vector DAG workflow | F1 | Done |
| S1.11 | Vector map viewer | F1 | Done |
| S1.12 | Enhanced data validation | F1 | Partial |
| S2.1 | Single raster pipeline | F2 | Done |
| S2.2 | Large raster tiling | F2 | Done |
| S2.3 | Raster collection pipeline | F2 | Partial |
| S2.4 | TiTiler integration | F2 | Done |
| S2.5 | STAC integration | F2 | Done |
| S2.6 | COG compression tiers | F2 | Done |
| S2.7 | Raster unpublish pipeline | F2 | Done |
| S2.8 | Raster DAG workflow | F2 | Done |
| S2.9 | pgSTAC search registration | F2 | Done |
| S2.10 | Raster map viewer | F2 | Done |
| S2.11 | Raster data extract API | F2 | Done |
| S2.12 | Raster classification | F2 | Planned |
| S2.13 | FATHOM ETL Phase 1 | F2 | Done |
| S2.14 | FATHOM ETL Phase 2 | F2 | Partial |
| S3.1 | Native Zarr ingest | F3 | Done |
| S3.2 | NetCDF to Zarr conversion | F3 | Done |
| S3.3 | Zarr v3 consolidation fix | F3 | Done |
| S3.4 | TiTiler xarray integration | F3 | Done |
| S3.5 | VirtualiZarr pipeline | F3 | Done |
| S3.6 | Zarr unpublish pipeline | F3 | Done |
| S3.7 | Zarr observability | F3 | Done |
| S3.8 | xarray service layer | F3 | Done |
| S3.9 | CMIP6 data hosting | F3 | Planned |
| S3.10 | TiTiler unified services | F3 | Planned |
| S4.1 | Asset/Release entity model | F4 | Done |
| S4.2 | Approval workflow | F4 | Done |
| S4.3 | STAC materialization at approval | F4 | Done |
| S4.4 | Release audit trail | F4 | Done |
| S4.5 | Unpublish orchestration | F4 | Done |
| S4.6 | Version ordinal management | F4 | Done |
| S4.7 | Services block gating | F4 | Done |
| S4.8 | Approval guard | F4 | Done |
| S5.1 | DAG orchestration engine | F5 | Done |
| S5.2 | DAG Brain admin UI | F5 | Done |
| S5.3 | Scheduled workflows | F5 | Done |
| S5.4 | Health and preflight system | F5 | Done |
| S5.5 | 3-tier observability | F5 | Done |
| S5.6 | API surface | F5 | Done |
| S5.7 | Schema management | F5 | Done |
| S5.8 | Worker dual-poll | F5 | Done |
| S5.9 | Janitor | F5 | Done |
| S5.10 | COMPETE/SIEGE quality pipeline | F5 | Done |
| S5.11 | Deployment tooling | F5 | Done |

---

## Roadmap

| Version | Milestone | Key Deliverables |
|---------|-----------|-----------------|
| v0.10.10 | F5d: Platform-to-DAG switchover | SIEGE-DAG rerun, flip DAG as default submission path |
| v0.11.0 | F6: Strangler fig complete | Remove CoreMachine, Service Bus, Epoch 4 jobs |
| Future | F3 completion | CMIP6 hosting (S3.9), unified TiTiler (S3.10) |
| Future | F2 completion | Raster classification (S2.12), FATHOM Phase 2 (S2.14) |
```

- [ ] **Step 3: Verify structure**

Confirm the file has these sections: Epic header, Feature Summary table, 5 Feature descriptions with links, Enablers table, Story Index table, Roadmap.

- [ ] **Step 4: Commit**

```bash
git add docs/product/EPICS.md
git commit -m "docs: create SAFe master registry (EPICS.md) with 1 Epic, 5 Features, 55 stories"
```

---

## Task 2: Write PRODUCT_OVERVIEW.md

The "read this first" narrative. References EPICS.md. A senior engineer should understand the system in 10 minutes.

**Files:**
- Create: `docs/product/PRODUCT_OVERVIEW.md`

- [ ] **Step 1: Write PRODUCT_OVERVIEW.md**

Create `docs/product/PRODUCT_OVERVIEW.md` with the following content.

Key data sources for writing this:
- Architecture: `docs_claude/CLAUDE_CONTEXT.md` (4-app architecture, deployment model)
- Current state: `config/__init__.py` for version, `services/__init__.py` for handler count
- Workflows: `workflows/*.yaml` (11 YAML files)
- Quality: `docs/agent_review/` for COMPETE/SIEGE run counts

```markdown
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
```

- [ ] **Step 2: Verify structure**

Confirm the file has: What This Is, Architecture (with diagram), What It Processes table, Feature Map linking to EPICS.md, Architecture Migration (3 phases), Quality Assurance, Technology Stack, Deployment Model, Key Documentation links.

- [ ] **Step 3: Commit**

```bash
git add docs/product/PRODUCT_OVERVIEW.md
git commit -m "docs: create product overview narrative for Geospatial Backend Solution"
```

---

## Task 3: Write STORIES_F1_VECTOR.md

**Files:**
- Create: `docs/product/STORIES_F1_VECTOR.md`

- [ ] **Step 1: Write STORIES_F1_VECTOR.md**

Create `docs/product/STORIES_F1_VECTOR.md` with the following content.

Key data sources:
- Handler catalog: `services/vector/` (8 atomic handlers), `services/handler_vector_docker_complete.py`, `services/handler_vector_multi_source.py`
- Workflow: `workflows/vector_docker_etl.yaml` (9 nodes), `workflows/unpublish_vector.yaml` (3 nodes), `workflows/acled_sync.yaml` (3 nodes)
- OGC Features: `ogc_features/` module
- History: Vector ETL complete NOV 2025, split views v0.10.0.2, multi-source v0.10.0.1, DAG workflow v0.10.7

```markdown
# Feature F1: Vector Data & Serving — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Vector Data & Serving is the end-to-end pipeline for ingesting vector geospatial data into PostGIS and exposing it as OGC API - Features collections. It accepts six input formats (Shapefile, GeoJSON, GeoPackage, CSV with coordinates, KML) and produces PostGIS tables with spatial indexes, standardized metadata columns, and automatic TiPG collection registration.

The pipeline supports three ingestion patterns: single-file (one file to one table), multi-source (N files or GPKG layers to N tables), and split views (one file to N OGC collections based on a categorical column). A two-phase TiPG discovery model makes tables browsable immediately for approval review, then adds rich metadata (title, description, keywords) after approval.

All vector workflows run on the Epoch 5 DAG engine. The `vector_docker_etl.yaml` workflow (9 nodes) handles the full pipeline including conditional split-column branching. The `acled_sync.yaml` workflow demonstrates API-driven scheduled ingestion as a reference implementation.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S1.1 | Vector ETL pipeline | Done | v0.10.5 | 7 atomic handlers: load, validate, create tables, split views, catalog, TiPG, finalize |
| S1.2 | OGC Features API | Done | v0.8.x | TiPG integration, bbox queries, spatial filtering |
| S1.3 | Multi-format support | Done | v0.10.5 | SHP, GeoJSON, GPKG, CSV (with coords), KML |
| S1.4 | Split views | Done | v0.10.0.2 | Single file to N OGC collections by categorical column (max 20 distinct values) |
| S1.5 | Multi-source vector | Done | v0.10.0.1 | N files to N tables; GPKG multi-layer to N tables |
| S1.6 | TiPG two-phase discovery | Done | v0.10.8 | Browsable pre-approval (bare table), searchable post-approval (rich metadata) |
| S1.7 | Vector unpublish pipeline | Done | v0.10.9 | `unpublish_vector.yaml`: inventory, drop table, STAC cleanup |
| S1.8 | ACLED scheduled sync | Done | v0.10.7 | `acled_sync.yaml`: fetch API, diff, append to PostGIS (cron-scheduled) |
| S1.9 | Catalog registration | Done | v0.10.5 | geo.table_catalog with title, bbox, feature count, CRS |
| S1.10 | Vector DAG workflow | Done | v0.10.7 | `vector_docker_etl.yaml`: 9 nodes, conditional split_column branching |
| S1.11 | Vector map viewer | Done | v0.8.x | Interactive Leaflet viewer at `/api/vector/viewer` |
| S1.12 | Enhanced data validation | Partial | — | Datetime range validation done; pandera evaluation pending |

---

## Story Detail

### S1.1: Vector ETL Pipeline
**Status**: Done (v0.10.5, 19 MAR 2026)

Seven atomic handlers compose the core vector pipeline:

| Handler | Task Type | Purpose |
|---------|-----------|---------|
| `vector_load_source` | `vector_load_source` | Stream blob from bronze to mount, detect format, convert to GeoParquet |
| `vector_validate_and_clean` | `vector_validate_and_clean` | Clean GeoDataFrame, split by geometry type, write GeoParquet |
| `vector_create_and_load_tables` | `vector_create_and_load_tables` | Create PostGIS tables, batch load with etl_batch_id tracking |
| `vector_create_split_views` | `vector_create_split_views` | Create PostgreSQL VIEWs on categorical column |
| `vector_register_catalog` | `vector_register_catalog` | Register in geo.table_catalog and app tracking tables |
| `vector_refresh_tipg` | `vector_refresh_tipg` | Refresh TiPG collection cache (best_effort) |
| `vector_finalize` | `vector_finalize` | Clean up ETL mount directory |

**Key files**: `services/vector/handler_*.py` (7 files), `workflows/vector_docker_etl.yaml`

### S1.2: OGC Features API
**Status**: Done (v0.8.x, NOV 2025)

OGC API - Features implementation via TiPG auto-discovery of PostGIS tables in the `geo` schema. Supports bbox spatial filtering, property filtering, pagination, and GeoJSON/JSON-FG output.

**Key files**: `ogc_features/` module
**Endpoints**: `/api/features/collections`, `/api/features/collections/{id}/items`

### S1.3: Multi-Format Support
**Status**: Done (v0.10.5)

The `vector_load_source` handler detects input format and converts to GeoParquet as a normalized intermediate. Supported formats: Shapefile (.shp + sidecars), GeoJSON (.geojson/.json), GeoPackage (.gpkg), CSV with coordinate columns, KML (.kml). macOS `__MACOSX` resource forks are filtered from ZIP archives.

**Key files**: `services/vector/handler_load_source.py`

### S1.4: Split Views
**Status**: Done (v0.10.0.2, 10 MAR 2026)

When `split_column` is provided, the pipeline creates one base table and N PostgreSQL VIEWs (one per distinct value). Each view is registered in geo.table_catalog and discovered by TiPG as a separate OGC Features collection. Constraints: max 20 distinct values, text/integer/boolean columns only, 63-character PostgreSQL identifier limit.

**Key files**: `services/vector/handler_create_split_views.py`

### S1.5: Multi-Source Vector
**Status**: Done (v0.10.0.1, 10 MAR 2026)

Two patterns: (1) N separate files uploaded together produce N PostGIS tables; (2) a multi-layer GeoPackage produces N tables (one per layer). Both patterns register each table independently in the catalog.

**Key files**: `services/handler_vector_multi_source.py`

### S1.6: TiPG Two-Phase Discovery
**Status**: Done (v0.10.8, 28 MAR 2026)

Phase 1 (pre-approval): `refresh_tipg_preview` runs after table creation. TiPG discovers bare PostGIS table — tiles render, features queryable, but no rich metadata. Approvers can preview data.

Phase 2 (post-approval): `register_catalog` writes title, description, keywords to geo.table_catalog. `refresh_tipg` re-reads metadata. Collection now searchable with full OGC metadata.

**Key files**: `services/vector/handler_refresh_tipg.py`, `workflows/vector_docker_etl.yaml` (nodes: refresh_tipg_preview, register_catalog, refresh_tipg)

### S1.7: Vector Unpublish Pipeline
**Status**: Done (v0.10.9)

`unpublish_vector.yaml` (3 nodes): inventory lookup, PostGIS table drop with metadata cleanup, STAC item deletion with audit. The inventory handler looks up the release_id and revokes atomically in the same transaction as the table drop.

**Key files**: `workflows/unpublish_vector.yaml`, `services/unpublish_handlers.py`

### S1.8: ACLED Scheduled Sync
**Status**: Done (v0.10.7, 20 MAR 2026)

Reference implementation for API-driven scheduled workflows. `acled_sync.yaml` (3 nodes): fetch new ACLED conflict events via API and diff against existing Silver table, save raw responses to Bronze for audit, bulk-INSERT new events into PostGIS via COPY. Runs on a cron schedule via DAGScheduler.

**Key files**: `workflows/acled_sync.yaml`, `services/handler_acled_*.py` (3 files)

### S1.9: Catalog Registration
**Status**: Done (v0.10.5)

The `vector_register_catalog` handler writes table metadata to `geo.table_catalog` including title, bounding box, feature count, CRS, and column schema. Also updates `app.vector_metadata` for ETL tracking. Used by TiPG for rich collection metadata.

**Key files**: `services/vector/handler_register_catalog.py`

### S1.10: Vector DAG Workflow
**Status**: Done (v0.10.7, 20 MAR 2026)

`vector_docker_etl.yaml` v3: 9 nodes with conditional branching on `split_column`. When split_column is provided, the `create_split_views` node activates; otherwise it is skipped via `when` clause. TiPG refresh nodes are marked `best_effort: true` so failures do not block the pipeline. Includes an approval gate between data loading and catalog registration.

**Key files**: `workflows/vector_docker_etl.yaml`

### S1.11: Vector Map Viewer
**Status**: Done (v0.8.x, DEC 2025)

Interactive Leaflet-based map viewer for browsing vector collections. Accessible at `/api/vector/viewer?collection={id}`.

**Key files**: `vector_viewer/service.py`

### S1.12: Enhanced Data Validation
**Status**: Partial

Datetime range validation implemented (catches garbage dates like year 48113 in KML imports — NULL substitution applied). Systematic validation via pandera library pending a 4-hour evaluation spike.

**Key files**: `services/vector/handler_validate_and_clean.py`
```

- [ ] **Step 2: Commit**

```bash
git add docs/product/STORIES_F1_VECTOR.md
git commit -m "docs: add F1 Vector Data & Serving story detail"
```

---

## Task 4: Write STORIES_F2_RASTER.md

**Files:**
- Create: `docs/product/STORIES_F2_RASTER.md`

- [ ] **Step 1: Write STORIES_F2_RASTER.md**

Create `docs/product/STORIES_F2_RASTER.md` with the following content.

Key data sources:
- Handler catalog: `services/raster/` (12 atomic handlers), `services/handler_process_raster_complete.py`, `services/handler_raster_collection_complete.py`
- Workflows: `workflows/process_raster.yaml` (10 nodes), `workflows/process_raster_collection.yaml` (9 phases), `workflows/unpublish_raster.yaml` (3 nodes)
- STAC: `services/stac/handler_materialize_item.py`, `services/stac/handler_materialize_collection.py`
- History: Raster DAG v0.10.8, FATHOM Phase 1 complete, Phase 2 46/47 tasks

```markdown
# Feature F2: Raster Data & Serving — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Raster Data & Serving converts GeoTIFF files into Cloud-Optimized GeoTIFFs (COGs) with STAC metadata, served through TiTiler for dynamic tile rendering and map visualization. The pipeline handles single files, large rasters exceeding 2GB (automatically tiled via fan-out/fan-in parallelization), and multi-file collections with homogeneity checking.

The raster DAG workflow (`process_raster.yaml`) is the most complex in the system at 10 nodes with conditional size-based routing between single-COG and tiled processing paths. The collection workflow (`process_raster_collection.yaml`) orchestrates 5 fan-out/fan-in cycles processing N files in parallel. Both workflows include approval gates and composable STAC materialization handlers shared with the Zarr pipeline.

The platform also hosts FATHOM global flood risk data through a specialized ETL pipeline with band stacking and spatial merge capabilities.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S2.1 | Single raster pipeline | Done | v0.10.5 | GeoTIFF to COG with validation, reprojection, compression |
| S2.2 | Large raster tiling | Done | v0.10.8 | >2GB conditional fan-out: tiling scheme, parallel tile processing, fan-in |
| S2.3 | Raster collection pipeline | Partial | v0.10.9 | `process_raster_collection.yaml` designed (5 fan-out/fan-in phases), not E2E tested |
| S2.4 | TiTiler integration | Done | v0.8.x | Dynamic tile rendering from COGs via pgSTAC |
| S2.5 | STAC integration | Done | v0.10.5 | Composable handlers: stac_materialize_item + stac_materialize_collection |
| S2.6 | COG compression tiers | Done | v0.8.x | Analysis (LZW), visualization (DEFLATE+overviews), archive (ZSTD) |
| S2.7 | Raster unpublish pipeline | Done | v0.10.9 | `unpublish_raster.yaml`: inventory, fan-out blob deletion, STAC cleanup |
| S2.8 | Raster DAG workflow | Done | v0.10.8 | `process_raster.yaml`: 10 nodes, conditional routing, approval gate |
| S2.9 | pgSTAC search registration | Done | v0.10.8 | Mosaic endpoints for tiled collections |
| S2.10 | Raster map viewer | Done | v0.8.x | Collection-aware Leaflet viewer |
| S2.11 | Raster data extract API | Done | v0.8.x | Point query, clip, preview endpoints |
| S2.12 | Raster classification | Planned | — | Automated classification: band count + dtype + value range decision tree |
| S2.13 | FATHOM ETL Phase 1 | Done | v0.9.x | Band stacking for flood return period data |
| S2.14 | FATHOM ETL Phase 2 | Partial | v0.9.x | Spatial merge: 46/47 tiles complete, 1 failed task pending retry |

---

## Story Detail

### S2.1: Single Raster Pipeline
**Status**: Done (v0.10.5, 19 MAR 2026)

Twelve atomic handlers compose the raster processing capabilities:

| Handler | Task Type | Purpose |
|---------|-----------|---------|
| `raster_download_source` | `raster_download_source` | Stream blob from bronze to ETL mount with namespace isolation |
| `raster_validate_atomic` | `raster_validate_atomic` | Header + data validation, CRS check, reprojection decision |
| `raster_create_cog_atomic` | `raster_create_cog_atomic` | Transform raster to COG, extract STAC metadata |
| `raster_upload_cog` | `raster_upload_cog` | Upload COG to silver, verify blob, return coordinates |
| `raster_persist_app_tables` | `raster_persist_app_tables` | Upsert cog_metadata + render_config, cache stac_item_json |
| `raster_finalize` | `raster_finalize` | Clean up ETL mount directory |

**Key files**: `services/raster/handler_*.py` (12 files), `workflows/process_raster.yaml`

### S2.2: Large Raster Tiling
**Status**: Done (v0.10.8, 22 MAR 2026)

Rasters exceeding 2GB are automatically routed through a tiled processing path. The conditional node in `process_raster.yaml` evaluates `file_size_bytes > 2000000000` and routes to: (1) `generate_tiling_scheme` which computes a tile grid, (2) fan-out of `process_single_tile` handlers (tested with 24 parallel tiles on 8.8GB data), (3) fan-in aggregation of tile results, (4) `persist_tiled` writes N cog_metadata rows.

**Key files**: `services/raster/handler_generate_tiling_scheme.py`, `services/raster/handler_process_single_tile.py`, `services/raster/handler_persist_tiled.py`

### S2.3: Raster Collection Pipeline
**Status**: Partial (v0.10.9 — workflow designed, not E2E tested)

`process_raster_collection.yaml` orchestrates 5 fan-out/fan-in cycles: (1) download N files, (2) validate N files, (3) check homogeneity across all validations, (4) create N COGs, (5) upload N COGs. Post-upload: persist collection metadata, approval gate, materialize N STAC items, materialize collection. Three new handlers: `raster_collection_entrypoint`, `raster_check_homogeneity`, `raster_persist_collection`.

**Key files**: `workflows/process_raster_collection.yaml`, `services/raster/handler_check_homogeneity.py`, `services/raster/handler_persist_collection.py`, `services/raster/handler_collection_entrypoint.py`

### S2.4: TiTiler Integration
**Status**: Done (v0.8.x)

Dynamic tile serving via TiTiler (titiler-pgstac 2.1.0). COGs registered in pgSTAC are automatically discoverable. TiTiler renders tiles on-the-fly with rescale, colormap, and band math parameters.

**Key files**: `services/stac_metadata_helper.py` (visualization metadata), TiTiler is an external service at `rmhtitiler`

### S2.5: STAC Integration
**Status**: Done (v0.10.5)

Two composable STAC handlers shared across raster and Zarr pipelines:

| Handler | Purpose |
|---------|---------|
| `stac_materialize_item` | Read stac_item_json from cog_metadata, sanitize properties, inject TiTiler URLs, upsert to pgSTAC |
| `stac_materialize_collection` | Recalculate collection spatial/temporal extent from pgSTAC items |

These handlers are generic — they operate on cached `stac_item_json` regardless of data type.

**Key files**: `services/stac/handler_materialize_item.py`, `services/stac/handler_materialize_collection.py`

### S2.6: COG Compression Tiers
**Status**: Done (v0.8.x)

Three compression profiles optimized for different access patterns:
- **Analysis**: LZW compression, no overviews (smallest decode overhead)
- **Visualization**: DEFLATE compression, internal overviews (fast tile serving)
- **Archive**: ZSTD compression (maximum compression ratio)

**Key files**: `services/raster/handler_create_cog.py`

### S2.7: Raster Unpublish Pipeline
**Status**: Done (v0.10.9)

`unpublish_raster.yaml` (3 nodes): inventory STAC item to extract asset blob paths, fan-out deletion of blobs from silver storage, STAC item deletion with audit trail. Idempotent — re-running on already-deleted assets is a no-op.

**Key files**: `workflows/unpublish_raster.yaml`, `services/unpublish_handlers.py`

### S2.8: Raster DAG Workflow
**Status**: Done (v0.10.8, 22 MAR 2026)

`process_raster.yaml`: 10 nodes with conditional size-based routing. PATH A (standard): download, validate, create COG, upload, persist, approval gate, materialize item, materialize collection. PATH B (large): same but with tiling scheme generation, fan-out tile processing, fan-in aggregation before persist. 16 DAG engine bugs fixed during E2E validation.

**Key files**: `workflows/process_raster.yaml`

### S2.9: pgSTAC Search Registration
**Status**: Done (v0.10.8)

Tiled raster collections register a pgSTAC search hash enabling mosaic tile endpoints. TiTiler uses the search hash to serve composite tiles across all items in a collection.

**Key files**: `services/pgstac_search_registration.py`

### S2.10: Raster Map Viewer
**Status**: Done (v0.8.x, 30 DEC 2025)

Collection-aware Leaflet viewer at `/api/raster/viewer?collection={id}`.

**Key files**: `raster_collection_viewer/service.py`

### S2.11: Raster Data Extract API
**Status**: Done (v0.8.x)

Endpoints for extracting raster data without visualization:
- `/api/raster/point` — value at coordinates
- `/api/raster/clip` — extract by bounding box
- `/api/raster/preview` — low-resolution preview image
- `/api/raster/extract` — general extraction

**Key files**: `raster_api/`

### S2.12: Raster Classification
**Status**: Planned

Automated raster classification using band count + dtype + value range to determine: DEM, RGB, Grayscale, Multispectral, Hyperspectral. Classification drives tier selection and default visualization parameters. Decision tree designed, not implemented.

### S2.13: FATHOM ETL Phase 1
**Status**: Done (v0.9.x)

Band stacking for FATHOM global flood return period data. Multiple GeoTIFFs (one per return period) stacked into a single multi-band COG for efficient storage and tile serving.

**Key files**: `services/fathom/fathom_etl.py`, `jobs/fathom_*.py`

### S2.14: FATHOM ETL Phase 2
**Status**: Partial (v0.9.x — 46/47 tiles complete)

Spatial merge of FATHOM tiles into contiguous coverage. 46 of 47 spatial merge tasks completed. One task (`n10-n15_w005-w010`) failed and requires retry with `force_reprocess=true`.

**Key files**: `services/fathom/fathom_etl.py`
```

- [ ] **Step 2: Commit**

```bash
git add docs/product/STORIES_F2_RASTER.md
git commit -m "docs: add F2 Raster Data & Serving story detail"
```

---

## Task 5: Write STORIES_F3_MULTIDIM.md

**Files:**
- Create: `docs/product/STORIES_F3_MULTIDIM.md`

- [ ] **Step 1: Write STORIES_F3_MULTIDIM.md**

Create `docs/product/STORIES_F3_MULTIDIM.md` with the following content.

Key data sources:
- Handlers: `services/zarr/` (4 atomic handlers), `services/handler_ingest_zarr.py` (4 handlers), `services/handler_netcdf_to_zarr.py` (6 handlers)
- Workflows: `workflows/ingest_zarr.yaml` (6 nodes), `workflows/unpublish_zarr.yaml` (3 nodes)
- xarray: `xarray_api/` module
- History: Native Zarr v0.9.11.8, VirtualiZarr v0.9.9.0, Zarr v3 fix v0.9.16.1, flat Zarr for tile serving v0.10.9

```markdown
# Feature F3: Multidimensional Data & Serving — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Partial — core pipelines operational, CMIP6 hosting and unified TiTiler planned

---

## Feature Description

Multidimensional Data & Serving handles NetCDF and Zarr stores — the primary formats for climate, weather, and Earth observation time-series data. The platform supports two ingest paths: native Zarr (cloud-native passthrough using abfs:// URLs that read directly from Azure Blob Storage) and NetCDF-to-Zarr conversion with spatial 256x256, time=1 rechunking optimized for TiTiler xarray tile serving.

All Zarr outputs use flat Zarr v3 format with Blosc+LZ4 compression. Pyramid generation was evaluated and removed — TiTiler xarray cannot read multiscale DataTree stores, so flat stores with optimized chunking are the correct approach. A VirtualiZarr pipeline creates lightweight Kerchunk-style reference stores that enable cloud-native access to NetCDF files without copying the full dataset.

The xarray service layer provides point queries, time-series statistics, and spatial aggregation endpoints for direct analytical access to Zarr stores.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S3.1 | Native Zarr ingest | Done | v0.9.11.8 | Cloud-native passthrough for abfs:// URLs, no copy needed |
| S3.2 | NetCDF to Zarr conversion | Done | v0.9.13.4 | Rechunked flat v3: spatial 256x256, time=1, Blosc+LZ4 |
| S3.3 | Zarr v3 consolidation fix | Done | v0.9.16.1 | Explicit zarr.consolidate_metadata() after every to_zarr() |
| S3.4 | TiTiler xarray integration | Done | v0.9.16.1 | Tile serving verified with ERA5 + CMIP6 data |
| S3.5 | VirtualiZarr pipeline | Done | v0.9.9.0 | Lazy Kerchunk-style reference stores (5-stage pipeline) |
| S3.6 | Zarr unpublish pipeline | Done | v0.10.9 | `unpublish_zarr.yaml`: inventory, fan-out blob deletion, cleanup |
| S3.7 | Zarr observability | Done | v0.9.16.0 | Tier 1 + Tier 2 checkpoint events at operation boundaries |
| S3.8 | xarray service layer | Done | v0.9.x | Point, statistics, aggregate endpoints |
| S3.9 | CMIP6 data hosting | Planned | — | Curated East Africa climate projections (SSP2-4.5, SSP5-8.5) |
| S3.10 | TiTiler unified services | Planned | — | Unified tile serving for COG + Zarr via single TiTiler instance |

---

## Story Detail

### S3.1: Native Zarr Ingest
**Status**: Done (v0.9.11.8, 2 MAR 2026)

Native Zarr stores already in Azure Blob Storage are ingested via cloud-native passthrough — the `zarr_download_to_mount` handler detects abfs:// URLs and skips the download step entirely. The Zarr store is read directly from blob storage, validated, and registered. Optional rechunking creates a new store with optimal chunk alignment (256x256 spatial, time=1). .zarr suffix auto-detection on file type.

**Key files**: `services/zarr/handler_download_to_mount.py`, `services/zarr/handler_validate_source.py`, `workflows/ingest_zarr.yaml`

### S3.2: NetCDF to Zarr Conversion
**Status**: Done (v0.9.13.4, 5 MAR 2026)

NetCDF files are converted to flat Zarr v3 stores with optimized chunking: spatial 256x256 pixels, time=1 slice, Blosc+LZ4 compression. This chunking pattern aligns with TiTiler xarray's access pattern for fast tile rendering. Pyramid generation (ndpyramid + pyresample) was evaluated and removed — TiTiler xarray cannot read multiscale DataTree stores.

**Key files**: `services/handler_netcdf_to_zarr.py`, `services/zarr/handler_download_to_mount.py`

### S3.3: Zarr v3 Consolidation Fix
**Status**: Done (v0.9.16.1, 9 MAR 2026)

Critical fix: xarray trusts consolidated metadata — if the consolidated metadata file is empty or stale, xarray reports zero variables. Solution: explicit `zarr.consolidate_metadata()` call after every `to_zarr()` write for zarr_format==3. Verified with ERA5 and CMIP6 data rendering on TiTiler.

**Key files**: `services/handler_netcdf_to_zarr.py`, `services/handler_ingest_zarr.py`

### S3.4: TiTiler xarray Integration
**Status**: Done (v0.9.16.1, 9 MAR 2026)

TiTiler xarray (titiler-xarray) serves dynamic tiles from Zarr stores. The platform injects `xarray:open_kwargs` with `account_name` and storage URL into STAC items so TiTiler can locate the Zarr store. Tile serving verified with rescale and colormap parameters on ERA5 temperature and CMIP6 precipitation data.

**Key files**: `services/zarr/handler_register.py` (xarray URL injection)
**Known issue**: `account_name` leaks to B2C consumers via STAC item properties (tracked as DF-STAC-5, deferred to v0.10.10)

### S3.5: VirtualiZarr Pipeline
**Status**: Done (v0.9.9.0, 28 FEB 2026)

Five-stage pipeline creating lightweight Kerchunk-style reference stores: (1) scan_netcdf_variables, (2) copy_netcdf_to_silver, (3) validate_netcdf, (4) combine_virtual_zarr, (5) register_zarr_catalog. The reference store is ~KB in size while the source NetCDF files remain unchanged in Bronze storage. Enables cloud-native access without THREDDS or full data copy.

**Key files**: `services/handler_netcdf_to_zarr.py`

### S3.6: Zarr Unpublish Pipeline
**Status**: Done (v0.10.9)

`unpublish_zarr.yaml` (3 nodes): inventory Zarr metadata to identify blob paths, fan-out deletion of Zarr chunks from silver-zarr storage, STAC item deletion with audit trail.

**Key files**: `workflows/unpublish_zarr.yaml`, `services/unpublish_handlers.py`

### S3.7: Zarr Observability
**Status**: Done (v0.9.16.0, 8 MAR 2026)

Tier 1 (inline logging): progress percentage and elapsed time at operation boundaries. Tier 2 (structured checkpoints): JobEventType.CHECKPOINT events with checkpoint_type (validate_start, copy_progress, rechunk_complete, etc.) for fine-grained progress tracking during long-running Zarr operations.

**Key files**: `services/zarr/handler_*.py`, `core/models/events.py`

### S3.8: xarray Service Layer
**Status**: Done (v0.9.x)

Direct analytical access to Zarr stores via REST API:
- `/api/xarray/point` — time-series value at coordinates
- `/api/xarray/statistics` — zonal statistics over bounding box
- `/api/xarray/aggregate` — temporal aggregation

**Key files**: `xarray_api/`, `services/xarray_reader.py`

### S3.9: CMIP6 Data Hosting
**Status**: Planned

Curated East Africa climate projections from CMIP6 models. Variables: tas, pr, tasmax, tasmin. Scenarios: SSP2-4.5, SSP5-8.5. Will use the native Zarr ingest pipeline (S3.1) with rechunking optimized for the target spatial domain.

### S3.10: TiTiler Unified Services
**Status**: Planned

Consolidate COG tile serving (titiler-pgstac) and Zarr tile serving (titiler-xarray) into a single TiTiler deployment or a unified routing layer. Currently separate services.
```

- [ ] **Step 2: Commit**

```bash
git add docs/product/STORIES_F3_MULTIDIM.md
git commit -m "docs: add F3 Multidimensional Data & Serving story detail"
```

---

## Task 6: Write STORIES_F4_LIFECYCLE.md

**Files:**
- Create: `docs/product/STORIES_F4_LIFECYCLE.md`

- [ ] **Step 1: Write STORIES_F4_LIFECYCLE.md**

Create `docs/product/STORIES_F4_LIFECYCLE.md` with the following content.

Key data sources:
- Entity model: `core/models/` (GeospatialAsset, AssetRelease)
- Approval: `services/asset_approval_service.py`
- STAC materialization: `services/stac_materialization.py`
- Audit: `core/models/events.py` (ReleaseAuditEvent)
- Unpublish: `workflows/unpublish_*.yaml` (3 workflows)
- History: Asset/Release split v0.9.0.0 (23 FEB), audit trail v0.9.12.1 (4 MAR), services block v0.10.9.14

```markdown
# Feature F4: Asset Lifecycle Management — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Asset Lifecycle Management is the governance layer that tracks every dataset from submission through approval to potential revocation. It answers the data owner's questions: "What happened to my data after I submitted it?", "Who approved it and when?", "Can I unpublish it?", and "What version is live?"

The system is built on an Asset/Release entity model inspired by software release management. An **Asset** is a stable identity container (SHA256 of platform_id, dataset_id, resource_id) that never changes. A **Release** is a versioned submission attached to an Asset, carrying its own approval state machine, version ordinal, and cached STAC metadata. Multiple releases can coexist under one Asset — `is_latest` is always computed dynamically, never stored.

STAC metadata is built during ETL processing but only published to pgSTAC at approval time. This deferred materialization pattern keeps the STAC catalog clean — only approved data is discoverable by consumers. Symmetric unpublish pipelines exist for all three data types (raster, vector, Zarr), each performing inventory, data deletion, and audit trail recording.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S4.1 | Asset/Release entity model | Done | v0.9.0.0 | Stable identity + versioned releases with ordinals |
| S4.2 | Approval workflow | Done | v0.9.0.0 | draft to approved to revoked state machine |
| S4.3 | STAC materialization at approval | Done | v0.9.0.0 | Cached dict on Release, written to pgSTAC when approved |
| S4.4 | Release audit trail | Done | v0.9.12.1 | Append-only lifecycle logging (APPROVED, REVOKED, OVERWRITTEN) |
| S4.5 | Unpublish orchestration | Done | v0.10.9 | Symmetric teardown for raster, vector, Zarr |
| S4.6 | Version ordinal management | Done | v0.9.0.0 | Reserved at submit, version_id assigned at approval |
| S4.7 | Services block gating | Done | v0.10.9.14 | services=null until release is approved |
| S4.8 | Approval guard | Done | v0.10.9 | DAG-aware: accepts processing status for DAG runs at gate |

---

## Story Detail

### S4.1: Asset/Release Entity Model
**Status**: Done (v0.9.0.0, 23 FEB 2026)

The monolithic GeospatialAsset entity was split into two entities:

**Asset** (stable identity container):
- `asset_id` = SHA256(platform_id | dataset_id | resource_id) — never changes
- `data_type` (raster, vector, zarr)
- `created_at`

**AssetRelease** (versioned submission):
- `release_id` = SHA256(asset_id | submission_key)
- `version_ordinal` (1, 2, 3... reserved at creation)
- `version_id` (assigned at approval, not submission)
- `approval_state` (draft, approved, revoked)
- `processing_status` (pending, processing, completed, failed)
- `stac_item_json` (cached STAC dict)
- `result_data` (ETL handler outputs)

**Key design decisions**:
- `is_latest` is computed, never stored: `ORDER BY version_ordinal DESC LIMIT 1`
- Multiple drafts can coexist under one Asset
- Ordinal naming: tables use `ord1`, `ord2` (not "draft")
- Vector data excluded from STAC — vector discovery via PostGIS/OGC Features only

**Key files**: `core/models/entities.py`, `infrastructure/postgresql.py`

### S4.2: Approval Workflow
**Status**: Done (v0.9.0.0, 23 FEB 2026)

Three-state approval lifecycle:

```
DRAFT ──> APPROVED ──> REVOKED
  │                       
  └──> REJECTED (terminal, no state change on Release)
```

- **Draft**: Created at job submission. ETL processing runs. Multiple drafts coexist.
- **Approved**: Approver assigns version_id. STAC item published to pgSTAC. Data discoverable.
- **Revoked**: Approver-triggered. STAC item deleted. Data hidden but not destroyed.

**Endpoints**: `POST /api/platform/approve`, `POST /api/platform/reject`, `POST /api/platform/revoke`
**Admin UI**: Approve/Reject/Revoke modals in DAG Brain Assets page

**Key files**: `services/asset_approval_service.py`, `triggers/platform/platform_bp.py`

### S4.3: STAC Materialization at Approval
**Status**: Done (v0.9.0.0)

Deferred materialization pattern:
1. ETL handler builds STAC item dict during processing
2. Dict cached on `release.stac_item_json` — NOT published
3. On approval: cached dict sanitized (remove `geoetl:*` and `processing:*` prefixes), TiTiler URLs injected, upserted to pgSTAC
4. On revocation: STAC item deleted from pgSTAC

**Why defer?** ETL may be re-run (overwrite). Approval may change version_id. Separation of concerns: ETL builds data, approval publishes metadata.

**Key files**: `services/stac_materialization.py`, `services/stac/handler_materialize_item.py`

### S4.4: Release Audit Trail
**Status**: Done (v0.9.12.1, 4 MAR 2026)

Append-only lifecycle logging capturing every approval state transition. Events: APPROVED, REVOKED, OVERWRITTEN. Each event records: actor, timestamp, previous state, new state, and full context (release_id, asset_id, version_ordinal). Inline single-transaction audit — no phantom events possible.

**Key files**: `core/models/events.py` (ReleaseAuditEvent), `infrastructure/audit_repository.py`

### S4.5: Unpublish Orchestration
**Status**: Done (v0.10.9)

Three symmetric unpublish workflows, one per data type:

| Workflow | Nodes | What It Deletes |
|----------|:-----:|----------------|
| `unpublish_raster.yaml` | 3 | COG blobs from silver, STAC item, audit record |
| `unpublish_vector.yaml` | 3 | PostGIS table, geo.table_catalog entry, release revocation |
| `unpublish_zarr.yaml` | 3 | Zarr chunks from silver-zarr, STAC item, audit record |

All unpublish handlers are idempotent — re-running on already-deleted data is a no-op.

**Key files**: `workflows/unpublish_*.yaml`, `services/unpublish_handlers.py`

### S4.6: Version Ordinal Management
**Status**: Done (v0.9.0.0)

Version ordinals are reserved at submission time (monotonically increasing integer per Asset). The human-readable `version_id` is assigned by the approver at approval time — not at submission. This ensures the version_id reflects the approval decision, not just the order of submission.

Table naming convention: `geo.{dataset}_{resource}_ord{N}` (e.g., `geo.acled_events_ord1`).

**Key files**: `services/asset_approval_service.py`, `core/models/entities.py`

### S4.7: Services Block Gating
**Status**: Done (v0.10.9.14, 2 APR 2026)

Service URLs (TiTiler visualization, OGC Features links) are only populated on a Release after approval. Before approval, `services = null`. This prevents consumers from accessing pre-approval data through service URLs — they can only browse raw tables via TiPG's two-phase discovery (which is intentional for approver preview).

**Key files**: `triggers/platform/trigger_platform_status.py`

### S4.8: Approval Guard
**Status**: Done (v0.10.9, 29 MAR 2026)

The approval endpoint validates that a release is ready for approval. Epoch 4 releases require `processing_status == 'completed'` (all tasks finished). DAG releases reach the approval gate mid-workflow (`processing_status == 'processing'`) — the guard accepts `processing` when the release has a `workflow_id` (DAG runs set `workflow_id = run_id`). The approval gate task must be in `waiting` status for STAC materialization to proceed.

**Key files**: `services/asset_approval_service.py:154-164`
```

- [ ] **Step 2: Commit**

```bash
git add docs/product/STORIES_F4_LIFECYCLE.md
git commit -m "docs: add F4 Asset Lifecycle Management story detail"
```

---

## Task 7: Write STORIES_F5_PLATFORM.md

**Files:**
- Create: `docs/product/STORIES_F5_PLATFORM.md`

- [ ] **Step 1: Write STORIES_F5_PLATFORM.md**

Create `docs/product/STORIES_F5_PLATFORM.md` with the following content.

Key data sources:
- DAG engine: `core/dag_orchestrator.py`, `core/dag_initializer.py`, `core/dag_transition_engine.py`, `core/dag_fan_engine.py`, `core/param_resolver.py`, `core/workflow_loader.py`
- Admin UI: `ui/`, `templates/`, `static/`
- Scheduler: `core/dag_scheduler.py`
- Health: `triggers/probes.py`, `triggers/admin/admin_preflight.py`
- API surface: `function_app.py`, `triggers/` (all blueprints)
- Quality: `docs/agent_review/` (COMPETE/SIEGE run reports)

```markdown
# Feature F5: Platform & Operations — Stories

**Parent Epic**: Geospatial Backend Solution [TBD]
**Last Updated**: 03 APR 2026
**Status**: Operational

---

## Feature Description

Platform & Operations encompasses the orchestration engine, admin tooling, and operational infrastructure that powers all data pipelines. The centerpiece is a custom DAG workflow engine that executes YAML-defined workflows with conditional routing, fan-out/fan-in parallelization, approval gates, and dotted-path parameter resolution. The DAG Brain admin UI provides a complete operational dashboard for job submission, approval management, and system monitoring.

The platform serves 115+ HTTP endpoints across five functional domains (platform, STAC, DAG, admin, OGC Features). A 3-tier observability system feeds Azure Application Insights with inline logging, structured checkpoint events, and status integration. Schema management supports safe additive changes (`ensure`) and destructive rebuilds (`rebuild`) for the 5-schema PostgreSQL architecture.

A rigorous quality assurance pipeline (COMPETE, SIEGE, REFLEXION, TOURNAMENT, ADVOCATE) has executed 70+ adversarial review cycles, discovering and fixing 83 defects across the codebase.

---

## Stories

| ID | Story | Status | Version | Notes |
|----|-------|--------|---------|-------|
| S5.1 | DAG orchestration engine | Done | v0.10.4 | YAML workflows, conditionals, fan-out/fan-in, gates, parameter resolution |
| S5.2 | DAG Brain admin UI | Done | v0.10.5.6 | Dashboard, submit (file browser), approve/reject/revoke, handlers grid, health |
| S5.3 | Scheduled workflows | Done | v0.10.7 | Cron-based DAGScheduler, app.schedules table |
| S5.4 | Health and preflight system | Done | v0.10.x | 20 plugin checks, mode-aware, /livez /readyz /health /preflight |
| S5.5 | 3-tier observability | Done | v0.9.16.0 | Inline logging, structured checkpoints, status integration |
| S5.6 | API surface | Done | v0.10.x | 115+ endpoints: platform, STAC, DAG, admin, OGC Features |
| S5.7 | Schema management | Done | v0.10.x | ensure (safe additive) / rebuild (destructive), Pydantic-to-SQL DDL |
| S5.8 | Worker dual-poll | Done | v0.10.4 | Legacy app.tasks + DAG workflow_tasks, SKIP LOCKED |
| S5.9 | Janitor | Done | v0.10.4 | Stale task recovery (30min TTL, STUCK detection) |
| S5.10 | COMPETE/SIEGE quality pipeline | Done | v0.10.9 | 70+ adversarial reviews, 83 fixes, 7 agent pipelines |
| S5.11 | Deployment tooling | Done | v0.10.x | deploy.sh, health checks, version verification |

---

## Story Detail

### S5.1: DAG Orchestration Engine
**Status**: Done (v0.10.4, 17 MAR 2026)

Custom YAML-defined workflow engine with four core modules:

| Module | Purpose |
|--------|---------|
| **DAGInitializer** | Converts workflow YAML into live database records (3-pass: validate, build tasks, build deps) |
| **DAGOrchestrator** | Main poll loop: load snapshot, evaluate transitions, check terminal state (max 1000 cycles) |
| **Transition Engine** | Promotes PENDING tasks to READY via 8-step gate (predecessor check, when-clause, parameter resolution) |
| **Fan Engine** | Evaluates conditionals (14 operators), expands fan-outs (Jinja2 parameterization), aggregates fan-ins (5 modes) |

**Key capabilities**:
- Conditional routing (14 operators: eq, gt, lt, truthy, in, contains, etc.)
- Fan-out/fan-in (up to 10,000 children per template, Jinja2 context with item/index/inputs/nodes)
- Approval gates (workflow suspension, external signal reconciliation)
- best_effort tasks (failure does not block downstream)
- Optional dependencies (`depends_on: ["task?"]` tolerates skipped upstream)
- Deterministic run_id (SHA256 of workflow + params, prevents duplicates)
- CAS guards on all state transitions

**Workflows**: 10 YAML definitions, 58 registered handlers

**Key files**: `core/dag_orchestrator.py`, `core/dag_initializer.py`, `core/dag_transition_engine.py`, `core/dag_fan_engine.py`, `core/param_resolver.py`, `core/workflow_loader.py`, `workflows/*.yaml`

### S5.2: DAG Brain Admin UI
**Status**: Done (v0.10.5.6, 23 MAR 2026)

Jinja2 + HTMX admin UI served by the DAG Brain app (APP_MODE=orchestrator). No JavaScript frameworks.

**Pages**:
- **Dashboard**: Active workflow runs, system status
- **Jobs**: List/detail with status filtering, task breakdown
- **Submit**: File browser (container selection, blob browsing, validate before submit)
- **Assets**: Approve/reject/revoke modals with release detail
- **Handlers**: Grid of all 58 registered handlers with task types
- **Health**: System health checks

All API calls proxied to Function App via httpx (ORCHESTRATOR_URL). Health checks skip irrelevant ETL mount, GDAL, and task polling checks in orchestrator mode.

**Key files**: `ui/`, `templates/`, `static/`, `docker_service.py`

### S5.3: Scheduled Workflows
**Status**: Done (v0.10.7, 20 MAR 2026)

DAGScheduler thread polls `app.schedules` table and submits workflows on cron schedules. CRUD endpoints for schedule management. Manual trigger endpoint for immediate execution. Reference implementation: ACLED sync (S1.8) runs on cron schedule.

**Endpoints**: `POST/GET/PUT/DELETE /api/dag/schedules`, `POST /api/dag/schedules/{id}/trigger`
**Key files**: `core/dag_scheduler.py`, `triggers/dag/dag_bp.py`

### S5.4: Health and Preflight System
**Status**: Done (v0.10.x)

Four probe endpoints with different purposes:
- `/livez` — process alive (always 200)
- `/readyz` — startup complete
- `/health` — comprehensive (20 plugin checks: database, blob, STAC, TiPG, etc.)
- `/preflight` — mode-aware capability validation with remediation guidance (13 checks)

Health checks are APP_MODE-aware — Docker workers skip irrelevant ETL mount checks, orchestrators skip task polling checks.

**Key files**: `triggers/probes.py`, `triggers/admin/admin_preflight.py`

### S5.5: 3-Tier Observability
**Status**: Done (v0.9.16.0, 8 MAR 2026)

| Tier | Method | Purpose |
|------|--------|---------|
| Tier 1 | `logger.info()` | Operation boundaries, 10% progress in long loops |
| Tier 2 | `JobEvent.CHECKPOINT` | Structured, non-fatal progress events with checkpoint_type |
| Tier 3 | Platform status endpoint | Recent checkpoint displayed in PROCESSING status response |

All 3 apps log to a single Application Insights instance. KQL query templates available at `/api/appinsights/templates`.

**Key files**: `core/models/events.py`, `docs_claude/APPLICATION_INSIGHTS.md`

### S5.6: API Surface
**Status**: Done (v0.10.x)

115+ HTTP endpoints across functional domains:

| Domain | Endpoints | Purpose |
|--------|:---------:|---------|
| Platform | 25 | B2B ETL submission, status, approvals, catalog |
| STAC | 19 | OGC STAC API v1.0.0 (collections, items, admin) |
| DAG | 13 | Workflow runs, tasks, schedules, test endpoints |
| Database Admin | 20 | Schema operations, diagnostics, maintenance |
| Admin/Maintenance | 35+ | System stats, cleanup, artifacts, services |
| Health Probes | 4 | Liveness, readiness, health, preflight |

Endpoints are conditionally registered based on APP_MODE (platform, orchestrator, worker, standalone).

**Key files**: `function_app.py`, `triggers/` (all blueprints)

### S5.7: Schema Management
**Status**: Done (v0.10.x)

Two schema operations via `/api/dbadmin/maintenance`:
- **ensure** (safe): Creates missing tables, indexes, enum types. Preserves existing data. Idempotent.
- **rebuild** (destructive): Drops and recreates app + pgstac schemas. Dev/test only.

DDL generated from Pydantic models via `generate_table_from_model()` (newer path with ClassVar PKs) and `generate_table_composed()` (older path with hardcoded PKs). Both coexist.

**Key files**: `core/schema/sql_generator.py`, `triggers/admin/db_maintenance.py`

### S5.8: Worker Dual-Poll
**Status**: Done (v0.10.4, 17 MAR 2026)

Docker workers poll both legacy `app.tasks` (Epoch 4) and DAG `app.workflow_tasks` (Epoch 5) using SKIP LOCKED. Each poll cycle checks both tables. A task claimed from either table is executed through the same handler registry (ALL_HANDLERS).

**Key files**: `docker_service.py`

### S5.9: Janitor
**Status**: Done (v0.10.4)

Background process that detects stale tasks (RUNNING for >30 minutes without heartbeat update). Stale tasks are marked STUCK and can be reclaimed. Prevents workflows from hanging indefinitely when a worker crashes mid-task.

**Known issue**: `validate` handler reclaimed by janitor on large files (60s+ execution exceeds heartbeat interval).

**Key files**: `core/dag_orchestrator.py`

### S5.10: COMPETE/SIEGE Quality Pipeline
**Status**: Done (v0.10.9)

Seven agent pipelines for adversarial quality assurance:

| Pipeline | Runs | Method |
|----------|:----:|--------|
| COMPETE | 70 | Two agents debate; third judges |
| SIEGE | 5 | Live E2E on Azure |
| REFLEXION | 17 | Reverse engineer, fault inject, patch, judge |
| TOURNAMENT | 1 | Full-spectrum (87.2% score) |
| ADVOCATE | 1 | B2B DX audit |
| GREENFIELD | 3 | Architecture from scratch comparison |
| OBSERVATORY | 2 | Observability audit |

**Results**: 83 total fixes. All critical/high findings resolved. SIEGE-DAG Run 5: 84% pass rate (16/19 sequences).

**Key files**: `docs/agent_review/`, `docs_claude/AGENT_PLAYBOOKS.md`

### S5.11: Deployment Tooling
**Status**: Done (v0.10.x)

`deploy.sh` handles all deployments:
- Reads version from `config/__init__.py`
- Deploys to target app (orchestrator, dagbrain, docker, all)
- Waits for restart (45s Function Apps, 60s Docker)
- Runs health check
- Verifies deployed version matches expected

DAG Brain and Docker Worker share the same ACR image — deploy both together.

**Key files**: `deploy.sh`, `config/__init__.py`
```

- [ ] **Step 2: Commit**

```bash
git add docs/product/STORIES_F5_PLATFORM.md
git commit -m "docs: add F5 Platform & Operations story detail"
```

---

## Task 8: Final verification and summary commit

- [ ] **Step 1: Verify all 7 files exist**

```bash
ls -la docs/product/
```

Expected output: 7 files (PRODUCT_OVERVIEW.md, EPICS.md, STORIES_F1_VECTOR.md, STORIES_F2_RASTER.md, STORIES_F3_MULTIDIM.md, STORIES_F4_LIFECYCLE.md, STORIES_F5_PLATFORM.md)

- [ ] **Step 2: Verify cross-references**

Check that:
- PRODUCT_OVERVIEW.md links to EPICS.md (Feature Map section)
- EPICS.md links to all 5 STORIES files
- STORIES files reference parent Epic
- STORIES files link to `docs_claude/` technical references where relevant
- No broken relative links

- [ ] **Step 3: Verify story ID consistency**

Confirm that every story ID in EPICS.md Story Index (S1.1 through S5.11) appears in the corresponding STORIES file, and vice versa. No orphaned or missing IDs.

- [ ] **Step 4: Verify status consistency**

Confirm that story status in EPICS.md Story Index matches the status in each STORIES file's table. No contradictions.

- [ ] **Step 5: Word count check**

```bash
wc -w docs/product/*.md
```

Targets: PRODUCT_OVERVIEW.md ~1000-1500 words, EPICS.md ~1500-2000 words, each STORIES file ~1500-2500 words. Total ~12,000-16,000 words across all 7 files.
