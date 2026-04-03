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
