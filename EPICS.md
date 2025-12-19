# SAFe Epic & Feature Registry

**Last Updated**: 19 DEC 2025
**Framework**: SAFe (Scaled Agile Framework)
**Purpose**: Master reference for Azure DevOps Boards import

---

## Quick Reference

| Epic | Name | Status | Features |
|------|------|--------|----------|
| E1 | Vector Data as API | ✅ Complete | 4 |
| E2 | Raster Data as API | ✅ Complete | 6 |
| E3 | Zarr/Climate Data as API | 🟢 Partial | 3 |
| E4 | Managed Datasets | 🟢 Partial | 2 |
| E5 | Vector Styling | 🟢 Partial | 2 |
| E6 | Platform Observability | 🟢 Mostly Complete | 3 |
| E7 | Data Externalization | 📋 Planned | 3 |

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

## Epic E2: Raster Data as API ✅

**Business Requirement**: "Make GeoTIFF available as API"
**Status**: ✅ COMPLETE (with active enhancements)
**Completed**: NOV 2025

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

### Feature F2.5: Service Layer API ✅

**Deliverable**: Simplified raster query endpoints

| Story | Description |
|-------|-------------|
| S2.5.1 | Create TiTiler client service |
| S2.5.2 | Create STAC client service with TTL cache |
| S2.5.3 | Implement /api/raster/extract endpoint |
| S2.5.4 | Implement /api/raster/point endpoint |
| S2.5.5 | Implement /api/raster/clip endpoint |
| S2.5.6 | Implement /api/raster/preview endpoint |
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

---

# ACTIVE EPICS

## Epic E3: Zarr/Climate Data as API 🟢

**Business Requirement**: "Now do Zarr" + time-series access
**Status**: 🟢 PARTIAL

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

## Epic E4: Managed Datasets 🟢

**Business Requirement**: Auto-updating external data sources
**Status**: 🟢 PARTIAL

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

## Epic E5: Vector Styling 🟢

**Business Requirement**: Server-side map rendering styles
**Status**: 🟢 PARTIAL

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

## Epic E6: Platform Observability 🟢

**Business Requirement**: Remote diagnostics without DB access
**Status**: 🟢 MOSTLY COMPLETE

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

## Enabler: PgSTAC Repository Consolidation 🔵

**Purpose**: Fix "Collection not found after insertion" - two classes manage pgSTAC data

| Task | Status |
|------|--------|
| Rename PgStacInfrastructure → PgStacBootstrap | ⬜ |
| Move data operations to PgStacRepository | ⬜ |
| Remove duplicate methods | ⬜ |
| Update StacMetadataService | ⬜ |

---

## Enabler: Repository Pattern Enforcement 🔵

**Purpose**: Eliminate direct database connections

| Task | Status |
|------|--------|
| Fix triggers/schema_pydantic_deploy.py | ⬜ |
| Fix triggers/db_query.py | ⬜ |
| Fix core/schema/deployer.py | ⬜ |
| Create PgSTACRepository | ⬜ |
| Update vector handlers | ⬜ |

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

# SUMMARY

## Counts

| Category | Count |
|----------|-------|
| Completed Epics | 2 |
| Active Epics | 4 |
| Planned Epics | 1 |
| **Total Epics** | **7** |
| Completed Features | 15 |
| Active Features | 4 |
| Planned Features | 4 |
| **Total Features** | **23** |
| Completed Enablers | 5 |
| Backlog Enablers | 3 |

## For Azure DevOps Import

| ADO Work Item Type | Maps To |
|-------------------|---------|
| Epic | Epic (E1-E7) |
| Feature | Feature (F1.1, F2.1, etc.) |
| User Story | Story (S1.1.1, S2.1.1, etc.) |
| Task | Enabler tasks |

---

**Last Updated**: 19 DEC 2025
