# SAFe Epic & Feature Registry

**Last Updated**: 19 DEC 2025
**Framework**: SAFe (Scaled Agile Framework)
**Purpose**: Master reference for Azure DevOps Boards import
**Source of Truth**: This file defines Epic/Feature numbers; TODO.md should align

---

## Quick Reference

**FY26 Target (ends 30 JUN 2026)**: E1 ✅, E2, E9, E7, E6

| Priority | Epic | Name | Status | Features | WSJF |
|:--------:|------|------|--------|:--------:|:----:|
| — | E1 | Vector Data as API | ✅ Complete | 4 | — |
| 1 | E2 | Raster Data as API | 🚧 Partial | 7 | TBD |
| 2 | E9 | DDH Platform Integration | 📋 Planned | 4 | TBD |
| 3 | E7 | Data Externalization | 📋 Planned | 3 | TBD |
| 4 | E6 | Platform Observability | 🚧 Mostly Complete | 3 | TBD |
| 5 | E3 | Zarr/Climate Data as API | 🚧 Partial | 3 | TBD |
| 6 | E4 | Managed Datasets | 🚧 Partial | 2 | TBD |
| 7 | E5 | Vector Styling | 🚧 Partial | 2 | TBD |
| 8 | E8 | H3 Analytics Pipeline | 🚧 Partial | 6 | TBD |

**Priority Notes**:
- **E9 + E6 tightly coupled**: Observability enables Integration monitoring
- **E9 requires elaboration**: ITSDA team (ITS Platform / DDH owner) has original requirements but no geospatial knowledge
- **E3, E4, E5, E8**: Nice-to-have for FY26 — E3 (Zarr/Climate) is top priority among these

| Enabler | Name | Status | Enables |
|---------|------|--------|---------|
| EN1 | Job Orchestration Engine | ✅ Complete | E1, E2, E3 |
| EN2 | Database Architecture | ✅ Complete | All |
| EN3 | Azure Platform Integration | ✅ Complete | All |
| EN4 | Configuration System | ✅ Complete | All |
| EN5 | Pre-flight Validation | ✅ Complete | E1, E2 |
| EN6 | Long-Running Task Infrastructure | 📋 Planned | E2, E3 |

---

# COMPLETED EPICS

## Epic E1: Vector Data as API ✅

**Business Requirement**: "Make vector data available as API"
**Status**: ✅ COMPLETE
**Completed**: NOV 2025

### Feature F1.1: Vector ETL Pipeline ✅

**Deliverable**: `process_vector` job with idempotent DELETE+INSERT pattern

| Story | Description |
|-------|-------------|
| S1.1.1 | Design etl_batch_id idempotency pattern |
| S1.1.2 | Create PostGIS handler with DELETE+INSERT |
| S1.1.3 | Implement chunked upload (500-row chunks) |
| S1.1.4 | Add spatial + batch index creation |
| S1.1.5 | Create process_vector job with JobBaseMixin |

**Key Files**: `jobs/process_vector.py`, `services/vector/process_vector_tasks.py`, `services/vector/postgis_handler.py`

---

### Feature F1.2: OGC Features API ✅

**Deliverable**: `/api/features/collections/{id}/items` with bbox queries

| Story | Description |
|-------|-------------|
| S1.2.1 | Create /api/features landing page |
| S1.2.2 | Implement /api/features/collections list |
| S1.2.3 | Add bbox query support |
| S1.2.4 | Create interactive map web interface |

**Key Files**: `web_interfaces/features/`, `triggers/ogc_features.py`

---

### Feature F1.3: Vector STAC Integration ✅

**Deliverable**: Items registered in pgSTAC `system-vectors` collection

| Story | Description |
|-------|-------------|
| S1.3.1 | Create system-vectors collection |
| S1.3.2 | Generate STAC items for vector datasets |
| S1.3.3 | Add vector-specific STAC properties |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `services/stac_metadata.py`

---

### Feature F1.4: Vector Unpublish ✅

**Deliverable**: `unpublish_vector` job for data removal

| Story | Description |
|-------|-------------|
| S1.4.1 | Create unpublish data models |
| S1.4.2 | Implement unpublish handlers |
| S1.4.3 | Add STAC item/collection validators |
| S1.4.4 | Create unpublish_vector job |

**Key Files**: `jobs/unpublish_vector.py`, `services/unpublish_handlers.py`, `core/models/unpublish.py`

**Note**: Code complete, needs deploy + test with `dry_run=true`

---

## Epic E2: Raster Data as API 🚧

**Business Requirement**: "Make GeoTIFF available as API"
**Status**: 🚧 PARTIAL (collection/mosaic workflow pending)
**Core Complete**: NOV 2025

### Feature F2.1: Raster ETL Pipeline ✅

**Deliverable**: `process_raster_v2` with 3-tier compression

| Story | Description |
|-------|-------------|
| S2.1.1 | Create COG conversion service |
| S2.1.2 | Implement 3-tier compression (analysis/visualization/archive) |
| S2.1.3 | Fix JPEG INTERLEAVE for YCbCr encoding |
| S2.1.4 | Add DEM auto-detection with colormap URLs |
| S2.1.5 | Implement blob size pre-flight validation |
| S2.1.6 | Create process_raster_v2 with JobBaseMixin (73% code reduction) |

**Key Files**: `jobs/process_raster_v2.py`, `services/raster_cog.py`

---

### Feature F2.2: TiTiler Integration ✅

**Deliverable**: Tile serving, previews, viewer URLs via rmhtitiler

| Story | Description |
|-------|-------------|
| S2.2.1 | Configure TiTiler for COG access |
| S2.2.2 | Generate viewer URLs in job results |
| S2.2.3 | Add preview image endpoints |
| S2.2.4 | Implement tile URL generation |

**Key Files**: `services/titiler_client.py`

---

### Feature F2.3: Raster STAC Integration ✅

**Deliverable**: Items registered in pgSTAC with COG assets

| Story | Description |
|-------|-------------|
| S2.3.1 | Create system-rasters collection |
| S2.3.2 | Generate STAC items with COG assets |
| S2.3.3 | Add raster-specific STAC properties |
| S2.3.4 | Integrate DDH metadata passthrough |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `services/stac_metadata.py`

---

### Feature F2.4: Raster Unpublish ✅

**Deliverable**: `unpublish_raster` job for data removal

| Story | Description |
|-------|-------------|
| S2.4.1 | Implement raster unpublish handlers |
| S2.4.2 | Create unpublish_raster job |

**Key Files**: `jobs/unpublish_raster.py`, `services/unpublish_handlers.py`

**Note**: Code complete, needs deploy + test with `dry_run=true`

---

### Feature F2.5: Raster Data Extract API ✅

**Deliverable**: Pixel-level data access endpoints (distinct from tile service)

**Access Pattern Distinction**:
| F2.2: Tile Service | F2.5: Data Extract API |
|--------------------|------------------------|
| XYZ tiles for map rendering | Pixel values for analysis |
| `/tiles/{z}/{x}/{y}` | `/api/raster/point`, `/extract`, `/clip` |
| Visual consumption | Data consumption |
| Pre-rendered, cached | On-demand, precise |

| Story | Description |
|-------|-------------|
| S2.5.1 | Create TiTiler client service |
| S2.5.2 | Create STAC client service with TTL cache |
| S2.5.3 | Implement /api/raster/extract endpoint (bbox → image) |
| S2.5.4 | Implement /api/raster/point endpoint (lon/lat → value) |
| S2.5.5 | Implement /api/raster/clip endpoint (geometry → masked image) |
| S2.5.6 | Implement /api/raster/preview endpoint (quick thumbnail) |
| S2.5.7 | Add error handling + validation |

**Key Files**: `raster_api/`, `services/titiler_client.py`, `services/stac_client.py`

---

### Feature F2.6: Large Raster Support ✅

**Deliverable**: `process_large_raster_v2` for oversized files

| Story | Description |
|-------|-------------|
| S2.6.1 | Create large raster processing job |
| S2.6.2 | Implement chunked processing strategy |

**Key Files**: `jobs/process_large_raster_v2.py`

**Note**: For files exceeding chunked processing limits, requires EN6 (Long-Running Task Infrastructure)

---

### Feature F2.7: Raster Collection Processing 📋 PLANNED

**Deliverable**: `process_raster_collection` job creating pgstac searches (unchanging mosaic URLs)

**Distinction from F2.1**:
| Aspect | F2.1: Individual TIF | F2.7: TIF Collection |
|--------|---------------------|----------------------|
| Input | Single blob | Manifest or folder |
| ETL output | Single COG + STAC item | Multiple COGs + pgstac search |
| API artifact | Item URL | **Search URL** (unchanging mosaic) |
| Use case | One-off analysis layer | Basemap/tile service |

| Story | Status | Description |
|-------|--------|-------------|
| S2.7.1 | 📋 | Design collection manifest schema |
| S2.7.2 | 📋 | Create multi-file orchestration job |
| S2.7.3 | 📋 | Implement pgstac search registration |
| S2.7.4 | 📋 | Generate stable mosaic URL in job results |
| S2.7.5 | 📋 | Add collection-level STAC metadata |

**Key Files**: `jobs/process_raster_collection.py` (planned)

---

# ACTIVE EPICS

## Epic E3: Zarr/Climate Data as API 🚧

**Business Requirement**: "Now do Zarr" + time-series access
**Status**: 🚧 PARTIAL

### Feature F3.1: xarray Service Layer ✅

**Deliverable**: Time-series and statistics endpoints

| Story | Description |
|-------|-------------|
| S3.1.1 | Create xarray reader service |
| S3.1.2 | Implement /api/xarray/point time-series |
| S3.1.3 | Implement /api/xarray/statistics |
| S3.1.4 | Implement /api/xarray/aggregate |

**Key Files**: `xarray_api/`, `services/xarray_reader.py`

---

### Feature F3.2: Virtual Zarr Pipeline 📋 PLANNED

**Deliverable**: Kerchunk references for NetCDF (eliminate physical conversion)

| Story | Status | Description |
|-------|--------|-------------|
| S3.2.1 | ⬜ | CMIP6 filename parser |
| S3.2.2 | ⬜ | Chunking validator (pre-flight) |
| S3.2.3 | ⬜ | Reference generator (single file → Kerchunk JSON) |
| S3.2.4 | ⬜ | Virtual combiner (time series references) |
| S3.2.5 | ⬜ | STAC datacube registration |
| S3.2.6 | ⬜ | Inventory job |
| S3.2.7 | ⬜ | Generate job (full pipeline) |
| S3.2.8 | ⬜ | TiTiler-xarray config |

**Dependencies**: `virtualizarr`, `kerchunk`, `h5netcdf`, `h5py`

---

### Feature F3.3: Reader App Migration ⬜ READY

**Deliverable**: Move read APIs to rmhogcstac (clean separation)

| Story | Status | Description |
|-------|--------|-------------|
| S3.3.1 | ⬜ | Copy raster_api module |
| S3.3.2 | ⬜ | Copy xarray_api module |
| S3.3.3 | ⬜ | Copy service clients |
| S3.3.4 | ⬜ | Update requirements.txt |
| S3.3.5 | ⬜ | Register routes |
| S3.3.6 | ⬜ | Deploy and validate |

---

## Epic E4: Managed Datasets 🚧

**Business Requirement**: Auto-updating external data sources
**Status**: 🚧 PARTIAL

### Feature F4.1: Managed Infrastructure ✅

**Deliverable**: Registry, scheduler, update job framework

| Story | Description |
|-------|-------------|
| S4.1.1 | Create data models |
| S4.1.2 | Design database schema |
| S4.1.3 | Create repository layer |
| S4.1.4 | Create registry service |
| S4.1.5 | Implement HTTP CRUD endpoints |
| S4.1.6 | Create timer scheduler (2 AM UTC) |
| S4.1.7 | Create 4-stage update job |
| S4.1.8 | Implement WDPA handler |

**Key Files**: `core/models/curated.py`, `infrastructure/curated_repository.py`, `services/curated/`, `jobs/curated_update.py`

---

### Feature F4.2: Dataset Handlers ⬜ READY

**Deliverable**: Additional external source handlers

| Story | Status | Description |
|-------|--------|-------------|
| S4.2.1 | ⬜ | Manual update trigger endpoint |
| S4.2.2 | ⬜ | FATHOM handler (flood data) |
| S4.2.3 | 📋 | Admin0 handler (Natural Earth) |
| S4.2.4 | 📋 | Style integration (depends on E5) |

---

## Epic E5: Vector Styling 🚧

**Business Requirement**: Server-side map rendering styles
**Status**: 🚧 PARTIAL

### Feature F5.1: OGC API Styles ✅

**Deliverable**: CartoSym-JSON storage with multi-format output

| Story | Description |
|-------|-------------|
| S5.1.1 | Create Pydantic models |
| S5.1.2 | Build style translator (CartoSym → Leaflet/Mapbox) |
| S5.1.3 | Create repository layer |
| S5.1.4 | Implement service orchestration |
| S5.1.5 | Create GET /features/collections/{id}/styles |
| S5.1.6 | Create GET /features/collections/{id}/styles/{sid} |
| S5.1.7 | Add geo.feature_collection_styles table |

**Key Files**: `ogc_styles/`

**Tested**: 18 DEC 2025 - All three output formats verified (Leaflet, Mapbox GL, CartoSym-JSON)

---

### Feature F5.2: ETL Style Integration 📋 PLANNED

**Deliverable**: Auto-create default styles on vector ingest

| Story | Status | Description |
|-------|--------|-------------|
| S5.2.1 | 📋 | Design default style templates |
| S5.2.2 | 📋 | Integrate into process_vector job |

---

## Epic E6: Platform Observability 🚧

**Business Requirement**: Remote diagnostics without DB access
**Status**: 🚧 MOSTLY COMPLETE

### Feature F6.1: Health & Diagnostics ✅

**Deliverable**: Comprehensive health and status APIs

| Story | Description |
|-------|-------------|
| S6.1.1 | Enhanced /api/health endpoint |
| S6.1.2 | Platform status for DDH (/api/platform/*) |
| S6.1.3 | 29 dbadmin endpoints |

**Key Files**: `web_interfaces/health/`, `triggers/admin/db_*.py`

---

### Feature F6.2: Error Telemetry ✅

**Deliverable**: Structured logging and retry tracking

| Story | Description |
|-------|-------------|
| S6.2.1 | Add error_source field to logs |
| S6.2.2 | Create 6 retry telemetry checkpoints |
| S6.2.3 | Implement log_nested_error() helper |
| S6.2.4 | Add JSON deserialization error handling |

**Key Files**: `core/error_handler.py`, `core/machine.py`

---

### Feature F6.3: Verbose Validation 🔵 BACKLOG

**Deliverable**: Enhanced error context

| Story | Status | Description |
|-------|--------|-------------|
| S6.3.1 | 🔵 | Verbose pre-flight validation |
| S6.3.2 | 🔵 | Unified DEBUG_MODE |

---

# PLANNED EPICS

## Epic E7: Data Externalization 📋

**Business Requirement**: Controlled data movement to external access zones
**Status**: 📋 PLANNED

```
INTERNAL ZONE              EXTERNAL ZONE
(rmhazuregeo*)      →      (client-accessible)
        ↓
  Approval + ADF Copy
        ↓
  Cloudflare WAF/CDN
        ↓
   Public Access
```

### Feature F7.1: Publishing Workflow 📋 PLANNED

**Owner**: Claude (code)
**Deliverable**: Approval queue, audit log, status APIs

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S7.1.1 | ⬜ | Design publish schema (`app.publish_queue`, `app.publish_audit_log`) |
| S7.1.2 | ⬜ | Create publishing repository |
| S7.1.3 | ⬜ | Submit for review endpoint |
| S7.1.4 | ⬜ | Approve/Reject endpoints |
| S7.1.5 | ⬜ | Status check endpoint |
| S7.1.6 | ⬜ | Audit log queries |

---

### Feature F7.2: ADF Data Movement 📋 PLANNED

**Owner**: Claude (code) + Robert (Azure config)
**Deliverable**: Blob copy pipelines with approval triggers

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S7.2.1 | ⬜ | Create ADF instance |
| S7.2.2 | ⬜ | Design internal→external pipeline |
| S7.2.3 | ⬜ | Create blob-to-blob copy activity |
| S7.2.4 | ⬜ | Integrate approve trigger |
| S7.2.5 | ⬜ | Add copy status to audit log |
| S7.2.6 | ⬜ | Add env variables |

---

### Feature F7.3: External Delivery Infrastructure 📋 PLANNED

**Owner**: Robert (infrastructure)
**Deliverable**: Cloudflare WAF/CDN, external storage

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S7.3.1 | ⬜ | Create external storage account |
| S7.3.2 | ⬜ | Configure Cloudflare WAF rules |
| S7.3.3 | ⬜ | Set up CDN for static assets |
| S7.3.4 | ⬜ | Configure custom domain |
| S7.3.5 | ⬜ | Validate end-to-end external access |

---

## Epic E8: H3 Analytics Pipeline 🚧

**Business Requirement**: Columnar aggregations of raster/vector data to H3 hexagonal grid
**Status**: 🚧 PARTIAL (Infrastructure complete, aggregation handlers in progress)

**Architecture**:
```
Source Data           H3 Aggregation          Output
┌─────────────┐       ┌───────────────┐       ┌─────────────────┐
│ Rasters     │──────▶│ Zonal Stats   │──────▶│ PostgreSQL OLTP │
│ (COGs)      │       │ (mean,sum,etc)│       │ (h3.zonal_stats)│
├─────────────┤       ├───────────────┤       ├─────────────────┤
│ Vectors     │──────▶│ Point Counts  │──────▶│ GeoParquet OLAP │
│ (PostGIS)   │       │ (category agg)│       │ (DuckDB export) │
└─────────────┘       └───────────────┘       └─────────────────┘
```

### Feature F8.1: H3 Grid Infrastructure ✅

**Deliverable**: Normalized H3 schema with cell-country mappings

| Story | Status | Description |
|-------|--------|-------------|
| S8.1.1 | ✅ | Design normalized schema (cells, cell_admin0, cell_admin1) |
| S8.1.2 | ✅ | Create stat_registry metadata catalog |
| S8.1.3 | ✅ | Create zonal_stats table for raster aggregations |
| S8.1.4 | ✅ | Create point_stats table for vector aggregations |
| S8.1.5 | ✅ | Create batch_progress table for idempotency |
| S8.1.6 | ✅ | Implement H3Repository with COPY-based bulk inserts |

**Key Files**: `infrastructure/h3_schema.py`, `infrastructure/h3_repository.py`, `infrastructure/h3_batch_tracking.py`

---

### Feature F8.2: Grid Bootstrap System ✅

**Deliverable**: 3-stage cascade job generating res 2-7 pyramid

| Story | Status | Description |
|-------|--------|-------------|
| S8.2.1 | ✅ | Create generate_h3_grid handler (base + cascade modes) |
| S8.2.2 | ✅ | Create cascade_h3_descendants handler (multi-level) |
| S8.2.3 | ✅ | Create finalize_h3_pyramid handler |
| S8.2.4 | ✅ | Create bootstrap_h3_land_grid_pyramid job |
| S8.2.5 | ✅ | Implement batch-level idempotency (resumable jobs) |
| S8.2.6 | ✅ | Add country/bbox filtering for testing |

**Key Files**: `jobs/bootstrap_h3_land_grid_pyramid.py`, `services/handler_generate_h3_grid.py`, `services/handler_cascade_h3_descendants.py`, `services/handler_finalize_h3_pyramid.py`

**Expected Cell Counts** (land-filtered):
- Res 2: ~2,000 | Res 3: ~14,000 | Res 4: ~98,000
- Res 5: ~686,000 | Res 6: ~4.8M | Res 7: ~33.6M

---

### Feature F8.3: Raster→H3 Aggregation 🚧 IN PROGRESS

**Deliverable**: Zonal statistics from COGs to H3 cells

| Story | Status | Description |
|-------|--------|-------------|
| S8.3.1 | ✅ | Create h3_raster_aggregation job definition |
| S8.3.2 | ✅ | Design 3-stage workflow (inventory → compute → finalize) |
| S8.3.3 | ⬜ | Implement h3_inventory_cells handler |
| S8.3.4 | ⬜ | Implement h3_raster_zonal_stats handler |
| S8.3.5 | ⬜ | Implement h3_aggregation_finalize handler |
| S8.3.6 | ✅ | Create insert_zonal_stats_batch() repository method |

**Key Files**: `jobs/h3_raster_aggregation.py`

**Stats Supported**: mean, sum, min, max, count, std, median

---

### Feature F8.4: Vector→H3 Aggregation ⬜ READY

**Deliverable**: Point/polygon counts aggregated to H3 cells

| Story | Status | Description |
|-------|--------|-------------|
| S8.4.1 | ⬜ | Create h3_vector_aggregation job |
| S8.4.2 | ⬜ | Implement point-in-polygon handler |
| S8.4.3 | ⬜ | Implement category grouping |
| S8.4.4 | ✅ | Create insert_point_stats_batch() repository method |

**Schema Ready**: `h3.point_stats` table exists

---

### Feature F8.5: GeoParquet Export 📋 PLANNED

**Deliverable**: Columnar export for OLAP analytics

| Story | Status | Description |
|-------|--------|-------------|
| S8.5.1 | 📋 | Design export job parameters |
| S8.5.2 | 📋 | Implement PostgreSQL → GeoParquet writer |
| S8.5.3 | 📋 | Add DuckDB/Databricks compatibility |
| S8.5.4 | 📋 | Create export_h3_stats job |

---

### Feature F8.6: Analytics API 📋 PLANNED

**Deliverable**: Query endpoints for H3 statistics

| Story | Status | Description |
|-------|--------|-------------|
| S8.6.1 | 📋 | GET /api/h3/stats/{dataset_id} |
| S8.6.2 | 📋 | GET /api/h3/stats/{dataset_id}/cells?iso3=&bbox= |
| S8.6.3 | 📋 | GET /api/h3/registry (list all datasets) |
| S8.6.4 | 📋 | Interactive H3 map interface |

---

## Epic E9: DDH Platform Integration 📋

**Business Requirement**: Enable DDH application to consume geospatial platform services
**Status**: 📋 PLANNED
**Owner**: DDH Team (with Robert coordination)

**Integration Points**:
```
DDH Application                    Geospatial Platform
┌─────────────────┐               ┌─────────────────────┐
│                 │──── Submit ──▶│ /api/jobs/submit/*  │
│  Data Hub       │               │ (vector, raster)    │
│  Dashboard      │◀── Status ────│ /api/jobs/status/*  │
│                 │               │ /api/platform/*     │
│                 │──── Query ───▶│ /api/features/*     │
│                 │               │ /api/raster/*       │
│                 │               │ /api/h3/*           │
└─────────────────┘               └─────────────────────┘
```

### Feature F9.1: API Contract & Documentation 📋 PLANNED

**Owner**: DDH Team + Robert
**Deliverable**: Formal API specification for cross-team development

| Story | Status | Description |
|-------|--------|-------------|
| S9.1.1 | 📋 | Generate OpenAPI 3.0 spec from existing endpoints |
| S9.1.2 | 📋 | Document job submission request/response formats |
| S9.1.3 | 📋 | Document STAC item structure for vectors/rasters |
| S9.1.4 | 📋 | Document error response contract |
| S9.1.5 | 📋 | Publish API docs (Swagger UI or static) |

---

### Feature F9.2: Job Lifecycle Callbacks 📋 PLANNED

**Owner**: DDH Team (consumer) + Claude (implementation)
**Deliverable**: Webhook notifications for job state changes

| Story | Status | Description |
|-------|--------|-------------|
| S9.2.1 | 📋 | Design callback payload schema |
| S9.2.2 | 📋 | Add callback_url parameter to job submission |
| S9.2.3 | 📋 | Implement webhook POST on job completion |
| S9.2.4 | 📋 | Implement webhook POST on job failure |
| S9.2.5 | 📋 | Add retry logic for failed callbacks |

---

### Feature F9.3: Authentication & Authorization 📋 PLANNED

**Owner**: DDH Team + Robert
**Deliverable**: Secure API access between systems

| Story | Status | Description |
|-------|--------|-------------|
| S9.3.1 | 📋 | Define auth strategy (API key, OAuth, managed identity) |
| S9.3.2 | 📋 | Implement auth middleware |
| S9.3.3 | 📋 | Create DDH service account/identity |
| S9.3.4 | 📋 | Document auth setup for DDH team |

---

### Feature F9.4: Integration Testing 📋 PLANNED

**Owner**: DDH Team + Robert
**Deliverable**: End-to-end test suite validating integration

| Story | Status | Description |
|-------|--------|-------------|
| S9.4.1 | 📋 | Create integration test environment |
| S9.4.2 | 📋 | Write vector ETL round-trip test |
| S9.4.3 | 📋 | Write raster ETL round-trip test |
| S9.4.4 | 📋 | Write OGC Features query test |
| S9.4.5 | 📋 | Set up CI pipeline for integration tests |

---

# COMPLETED ENABLERS

Technical foundation that enables all Epics above.

## Enabler EN1: Job Orchestration Engine ✅

**What It Enables**: All ETL jobs (E1, E2, E3)

| Component | Description |
|-----------|-------------|
| CoreMachine | Job→Stage→Task state machine |
| JobBaseMixin | 70%+ code reduction for new jobs |
| Retry Logic | Exponential backoff with telemetry |
| Stage Completion | "Last task turns out the lights" pattern |

**Key Files**: `core/machine.py`, `core/state_manager.py`, `jobs/base.py`, `jobs/mixins.py`

---

## Enabler EN2: Database Architecture ✅

**What It Enables**: Data separation, safe schema management

| Component | Description |
|-----------|-------------|
| Dual Database | App DB (nukeable) vs Business DB (protected) |
| Schema Management | full-rebuild, redeploy, nuke endpoints |
| Managed Identity | Same identity, different permission grants |

**Key Files**: `config/database_config.py`, `triggers/admin/db_maintenance.py`

---

## Enabler EN3: Azure Platform Integration ✅

**What It Enables**: Secure, scalable Azure deployment

| Component | Description |
|-----------|-------------|
| Managed Identity | User-assigned identity for all services |
| Service Bus | Queue-based job orchestration |
| Blob Storage | Bronze/Silver tier with SAS URLs |

**Key Files**: `infrastructure/service_bus.py`, `infrastructure/storage.py`

---

## Enabler EN4: Configuration System ✅

**What It Enables**: Environment-based configuration

| Component | Description |
|-----------|-------------|
| Modular Config | Split from 1200-line monolith |
| Type Safety | Pydantic-based config classes |

**Key Files**: `config/__init__.py`, `config/database_config.py`, `config/storage_config.py`, `config/queue_config.py`, `config/raster_config.py`

---

## Enabler EN5: Pre-flight Validation ✅

**What It Enables**: Early failure before queue submission

| Validator | Description |
|-----------|-------------|
| blob_exists | Validate blob container + name |
| blob_exists_with_size | Combined existence + size check |
| collection_exists | Validate STAC collection |
| stac_item_exists | Validate STAC item |

**Key Files**: `infrastructure/validators.py`

---

# BACKLOG ENABLERS

## Enabler EN6: Long-Running Task Infrastructure 📋 PLANNED

**Purpose**: Docker-based worker for tasks exceeding Azure Functions 30-min timeout
**What It Enables**: E2 (oversized rasters), E3 (large climate datasets)
**Reference**: See architecture diagram at `/api/interface/health`

| Task | Status | Description |
|------|--------|-------------|
| EN6.1 | 📋 | Create Docker image with GDAL/rasterio/xarray |
| EN6.2 | 📋 | Deploy Azure Container App or Web App for Containers |
| EN6.3 | 📋 | Create `long-running-raster-tasks` Service Bus queue |
| EN6.4 | 📋 | Implement queue listener in Docker worker |
| EN6.5 | 📋 | Add routing logic to dispatch oversized jobs |
| EN6.6 | 📋 | Health check and monitoring integration |

**Enables**:
- F2.6 (Large Raster Support) - files exceeding chunked processing limits
- F3.2 (Virtual Zarr Pipeline) - large NetCDF reference generation

---

## Enabler: Repository Pattern Enforcement 🔵

**Purpose**: Eliminate remaining direct database connections

| Task | Status | Notes |
|------|--------|-------|
| Fix triggers/schema_pydantic_deploy.py | ⬜ | Has psycopg.connect |
| Fix triggers/health.py | ⬜ | Has psycopg.connect |
| Fix core/schema/sql_generator.py | ⬜ | Has psycopg.connect |
| Fix core/schema/deployer.py | ⬜ | Review for direct connections |

---

## Enabler: Dead Code Audit 🔵

**Purpose**: Remove orphaned code, reduce maintenance burden

| Task | Status |
|------|--------|
| Audit core/ folder | ⬜ |
| Audit infrastructure/ folder | ⬜ |
| Remove commented-out code | ⬜ |
| Update FILE_CATALOG.md | ⬜ |

---

# COMPLETED ENABLERS (ADDITIONAL)

## Enabler: PgSTAC Repository Consolidation ✅

**Purpose**: Fix "Collection not found after insertion" - two classes manage pgSTAC data
**Completed**: DEC 2025

| Task | Status |
|------|--------|
| Rename PgStacInfrastructure → PgStacBootstrap | ✅ |
| Create PgStacRepository | ✅ |
| Move data operations to PgStacRepository | ✅ |
| Remove duplicate methods | ✅ |

**Key Files**: `infrastructure/pgstac_bootstrap.py`, `infrastructure/pgstac_repository.py`

---

# SUMMARY

## Counts

| Category | Count |
|----------|-------|
| Completed Epics | 1 |
| Active Epics | 6 |
| Planned Epics | 2 |
| **Total Epics** | **9** |
| Completed Features | 17 |
| Active Features | 6 |
| Planned Features | 11 |
| **Total Features** | **34** |
| Completed Enablers | 6 |
| Backlog Enablers | 3 |

## For Azure DevOps Import

| ADO Work Item Type | Maps To |
|-------------------|---------|
| Epic | Epic (E1-E9) |
| Feature | Feature (F1.1, F2.1, etc.) |
| User Story | Story (S1.1.1, S2.1.1, etc.) |
| Task | Enabler tasks |

**Cross-Team Assignment**:
- E9 (DDH Platform Integration) → Assign to DDH Team in ADO
- All other Epics → Assign to Geospatial Team

---

**Last Updated**: 19 DEC 2025 (Added F2.7: Raster Collection Processing)
