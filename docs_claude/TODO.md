# Product Backlog - Geospatial ETL Platform

**Last Updated**: 19 DEC 2025
**Framework**: SAFe (Scaled Agile Framework)

---

## 📋 BACKLOG MANAGEMENT RULES

> **All future updates to this file MUST follow SAFe structure:**
> - Organize work under **Epics** (strategic initiatives)
> - Break Epics into **Features** (deliverable capabilities)
> - Break Features into **Stories** (1-3 day atomic tasks)
> - Use **Enablers** for technical debt/infrastructure
> - Use **Spikes** for research/investigation

**Status Icons:**
- ✅ Complete
- 🟢 In Progress
- ⬜ Ready (refined, can start)
- 📋 Planned (needs refinement)
- 🔵 Backlog (future)

---

## 🎯 CURRENT PROGRAM INCREMENT (PI 2025.4)

**PI Objectives:**
1. Complete Data Access Simplification (E1) - Reader App Migration
2. Begin Data Externalization (E6) - Publishing workflow + ADF
3. Climate Data Virtualization OR Vector Styling (client priority)

---

# EPICS

## Epic E1: Data Access Simplification

**Business Outcome**: Reduce client complexity for raster/xarray queries
**Status**: 🟢 Near Complete

### Feature F1.1: Service Layer API ✅ COMPLETE

**Delivered**: `/api/raster/` and `/api/xarray/` endpoints in rmhazuregeoapi

| Story | Status | Notes |
|-------|--------|-------|
| S1.1.1: TiTiler client service | ✅ | `services/titiler_client.py` |
| S1.1.2: STAC client service | ✅ | `services/stac_client.py` |
| S1.1.3: xarray reader service | ✅ | `services/xarray_reader.py` |
| S1.1.4: Raster extract endpoint | ✅ | `/api/raster/extract/{collection}/{item}` |
| S1.1.5: Raster point endpoint | ✅ | `/api/raster/point/{collection}/{item}` |
| S1.1.6: Raster clip endpoint | ✅ | `/api/raster/clip/{collection}/{item}` |
| S1.1.7: Raster preview endpoint | ✅ | `/api/raster/preview/{collection}/{item}` |
| S1.1.8: xarray point time-series | ✅ | `/api/xarray/point/{collection}/{item}` |
| S1.1.9: xarray statistics | ✅ | `/api/xarray/statistics/{collection}/{item}` |
| S1.1.10: xarray aggregate | ✅ | `/api/xarray/aggregate/{collection}/{item}` |
| S1.1.11: Error handling + validation | ✅ | bbox, date range, STAC lookup errors |
| S1.1.12: STAC caching | ✅ | TTL cache (5min items, 1hr collections) |

**API Reference**: See `/SERVICE-LAYER-API-DESIGN.md`

---

### Feature F1.2: Reader App Migration ⬜ READY

**Goal**: Migrate raster_api/xarray_api to rmhogcstac for clean separation
**Depends On**: F1.1 ✅

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S1.2.1: Copy raster_api module | ⬜ | Module exists in rmhogcstac |
| S1.2.2: Copy xarray_api module | ⬜ | Module exists in rmhogcstac |
| S1.2.3: Copy service clients | ⬜ | titiler_client, stac_client, xarray_reader |
| S1.2.4: Update requirements.txt | ⬜ | xarray, zarr, httpx added |
| S1.2.5: Register routes | ⬜ | Routes in rmhogcstac function_app.py |
| S1.2.6: Deploy and validate | ⬜ | All endpoints return correct responses |

**Deliverable**: Read-only queries in rmhogcstac, ETL in rmhazuregeoapi

---

## Epic E2: Managed Datasets

**Business Outcome**: System-maintained datasets from external sources with auto-updates
**Status**: 🟢 Partially Complete

### Feature F2.1: Managed Datasets Infrastructure ✅ COMPLETE

**Delivered**: System-maintained datasets from external sources (WDPA, FATHOM, ACLED)

| Story | Status | Location |
|-------|--------|----------|
| S2.1.1: Data models | ✅ | `core/models/curated.py` |
| S2.1.2: Database schema | ✅ | `app.curated_datasets`, `app.curated_update_log` |
| S2.1.3: Repository layer | ✅ | `infrastructure/curated_repository.py` |
| S2.1.4: Registry service | ✅ | `services/curated/registry_service.py` |
| S2.1.5: HTTP CRUD endpoints | ✅ | `/api/curated/datasets` |
| S2.1.6: Timer scheduler | ✅ | 2 AM UTC daily check |
| S2.1.7: 4-stage update job | ✅ | `jobs/curated_update.py` |
| S2.1.8: WDPA handler | ✅ | `services/curated/wdpa_handler.py` |

---

### Feature F2.2: Managed Dataset Handlers ⬜ READY

| Story | Status | Description |
|-------|--------|-------------|
| S2.2.1: Manual update trigger | ⬜ | Connect `/api/curated/datasets/{id}/update` to job |
| S2.2.2: FATHOM handler | ⬜ | Flood data integration |
| S2.2.3: Admin0 handler | 📋 | Natural Earth boundaries |
| S2.2.4: Style integration | 📋 | Auto-create OGC styles (depends on E4) |

---

## Epic E3: Climate Data Virtualization

**Business Outcome**: Eliminate unnecessary NetCDF→Zarr conversion (save weeks + 2x storage)
**Status**: 📋 Planned

### Feature F3.1: Virtual Zarr Pipeline 📋 PLANNED

**Problem**: Client converting 20-100GB CMIP6 NetCDF to physical Zarr unnecessarily.
**Solution**: Kerchunk reference files that make NetCDF accessible as virtual Zarr.

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S3.1.1: CMIP6 filename parser | ⬜ | Parse variable, model, scenario from filename |
| S3.1.2: Chunking validator | ⬜ | Pre-flight NetCDF compatibility check |
| S3.1.3: Reference generator | ⬜ | Single file → Kerchunk JSON |
| S3.1.4: Virtual combiner | ⬜ | Combine time series references |
| S3.1.5: STAC datacube registration | ⬜ | xarray-compatible STAC items |
| S3.1.6: Inventory job | ⬜ | Scan and group CMIP6 files |
| S3.1.7: Generate job | ⬜ | Full pipeline orchestration |
| S3.1.8: TiTiler-xarray config | ⬜ | Serve virtual Zarr as tiles |

**Dependencies**: `virtualizarr`, `kerchunk`, `h5netcdf`, `h5py`

---

## Epic E4: Vector Styling System

**Business Outcome**: Server-side OGC styles for map rendering
**Status**: 🟢 Partially Complete

### Feature F4.1: OGC API Styles ✅ COMPLETE

**Solution**: CartoSym-JSON canonical storage with multi-format output
**Module**: `ogc_styles/` (standalone module)

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S4.1.1: Pydantic models | ✅ | `ogc_styles/models.py` - CartoSym-JSON schemas |
| S4.1.2: Style translator service | ✅ | `ogc_styles/translator.py` - CartoSym → Leaflet/Mapbox GL |
| S4.1.3: Repository methods | ✅ | `ogc_styles/repository.py` - CRUD for `geo.feature_collection_styles` |
| S4.1.4: Service orchestration | ✅ | `ogc_styles/service.py` - Style lookup and format conversion |
| S4.1.5: List styles endpoint | ✅ | `GET /features/collections/{id}/styles` |
| S4.1.6: Get style endpoint | ✅ | `GET /features/collections/{id}/styles/{sid}?f=leaflet\|mapbox\|cartosym` |
| S4.1.7: Schema migration | ✅ | `geo.feature_collection_styles` table in db_maintenance.py |
| S4.1.8: ETL style integration | 📋 | Auto-create default styles on ingest |

**Tested 18 DEC 2025**: All three output formats verified working (Leaflet, Mapbox GL, CartoSym-JSON)

---

## Epic E5: Platform Observability

**Business Outcome**: Remote diagnostics without direct DB access
**Status**: 🟢 Partially Complete

### Feature F5.1: Health & Diagnostics ✅ MOSTLY COMPLETE

| Story | Status | Notes |
|-------|--------|-------|
| S5.1.1: Enhanced health endpoint | ✅ | `schema_summary`, `database_config` |
| S5.1.2: Platform status for DDH | ✅ | `/api/platform/health`, `/stats`, `/failures` |
| S5.1.3: 29 dbadmin endpoints | ✅ | Comprehensive inspection |
| S5.1.4: Verbose pre-flight validation | 🔵 | Job context in error messages |
| S5.1.5: Unified DEBUG_MODE | 🔵 | Consistent verbose behavior |

---

## Epic E6: Data Externalization

**Business Outcome**: Controlled, audited data movement from internal to external access zones
**Status**: 📋 Planned

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

### Feature F6.1: Publishing Workflow 📋 PLANNED

**Goal**: Human-approved data promotion with audit trail
**Owner**: Claude (code)

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S6.1.1: Design publish schema | ⬜ | `app.publish_queue`, `app.publish_audit_log` |
| S6.1.2: Create publishing repository | ⬜ | CRUD for publish queue |
| S6.1.3: Submit for review endpoint | ⬜ | `POST /api/publish/submit/{dataset_id}` |
| S6.1.4: Approve/Reject endpoints | ⬜ | `POST /api/publish/approve`, `/reject` |
| S6.1.5: Status check endpoint | ⬜ | `GET /api/publish/status/{dataset_id}` |
| S6.1.6: Audit log queries | ⬜ | `GET /api/publish/audit` |

---

### Feature F6.2: ADF Data Movement 📋 PLANNED

**Goal**: Automated blob copying between access zones
**Owner**: Claude (code) + Robert (Azure config)

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S6.2.1: Create ADF instance | ⬜ | `az datafactory create` in rmhazure_rg |
| S6.2.2: Design internal→external pipeline | ⬜ | Pipeline definition documented |
| S6.2.3: Create blob-to-blob copy activity | ⬜ | Copy from rmhazuregeo* to external storage |
| S6.2.4: Integrate approve trigger | ⬜ | Approval endpoint triggers ADF pipeline |
| S6.2.5: Add copy status to audit log | ⬜ | Pipeline completion updates audit record |
| S6.2.6: Add env variables | ⬜ | ADF config in Function App settings |

---

### Feature F6.3: External Delivery Infrastructure 📋 PLANNED

**Goal**: Secure public access via CDN and WAF
**Owner**: Robert (infrastructure)

| Story | Status | Acceptance Criteria |
|-------|--------|---------------------|
| S6.3.1: Create external storage account | ⬜ | New storage account for public data |
| S6.3.2: Configure Cloudflare WAF rules | ⬜ | Rate limiting, geo-blocking, bot protection |
| S6.3.3: Set up CDN for static assets | ⬜ | Cloudflare caching configured |
| S6.3.4: Configure custom domain | ⬜ | DNS pointing to Cloudflare |
| S6.3.5: Validate end-to-end external access | ⬜ | Public URL serves data through WAF/CDN |

---

# ENABLERS (Technical Debt)

## Enabler: PgSTAC Repository Consolidation

**Purpose**: Fix "Collection not found after insertion" - two classes manage pgSTAC data
**Status**: 🔵 Backlog

| Task | Status |
|------|--------|
| Rename PgStacInfrastructure → PgStacBootstrap | ⬜ |
| Move data operations to PgStacRepository | ⬜ |
| Remove duplicate methods | ⬜ |
| Update StacMetadataService | ⬜ |

---

## Enabler: Repository Pattern Enforcement

**Purpose**: Eliminate direct database connections
**Status**: 🔵 Backlog

**Problem**: 5+ files bypass `PostgreSQLRepository`

| Task | Status |
|------|--------|
| Fix `triggers/schema_pydantic_deploy.py` | ⬜ |
| Fix `triggers/db_query.py` | ⬜ |
| Fix `core/schema/deployer.py` | ⬜ |
| Create PgSTACRepository | ⬜ |
| Update vector handlers | ⬜ |

---

## Enabler: Dead Code Audit

**Purpose**: Remove orphaned code, reduce maintenance burden
**Status**: 🔵 Backlog

| Task | Status |
|------|--------|
| Audit `core/` folder | ⬜ |
| Audit `infrastructure/` folder | ⬜ |
| Remove commented-out code | ⬜ |
| Update FILE_CATALOG.md | ⬜ |

---

# FUTURE BACKLOG

## Feature: Docker Worker for Long-Running GDAL

**Problem**: Azure Functions 30-minute timeout
**Solution**: Separate Docker worker on Azure Web App
**Status**: 🔵 Backlog
**Reference**: `/GDAL_WORKER.md`

---

## Feature: Function App Separation

**Problem**: Single host.json can't optimize for both raster (2-8GB, low concurrency) and vector (200MB, high concurrency)
**Status**: 🔵 Backlog
**Reference**: `/PRODUCTION_ARCHITECTURE.md`

---

## Feature: Service Bus Sessions

**Purpose**: Per-job FIFO ordering at high volume
**Status**: 🔵 Backlog
**Trigger**: When stage_complete timeouts observed

---

## Feature: Azure API Management

**Purpose**: Route single domain to specialized Function Apps
**Status**: 🔵 Backlog
**Depends On**: Function App Separation

---

## Feature: Unpublish Workflows ✅ IMPLEMENTED

**Status**: ✅ Code complete, needs deploy + test with `dry_run=true`

Files:
- `jobs/unpublish_raster.py`
- `jobs/unpublish_vector.py`
- `services/unpublish_handlers.py`
- `core/models/unpublish.py`
- `infrastructure/validators.py` (stac_item_exists, stac_collection_exists)

---

## Feature: Janitor Blob Cleanup 🔵 BACKLOG

**Status**: Database cleanup done, blob cleanup deferred

| Task | Status |
|------|--------|
| Add `delete_blobs_by_prefix()` | 🔵 |
| Integrate into JanitorService | 🔵 |

---

## Feature: Sensor Metadata Extraction 🔵 BACKLOG

**Purpose**: Extract EXIF/TIFF tags, track provenance

| Task | Status |
|------|--------|
| Create `services/sensor_metadata.py` | 🔵 |
| Add `stac:processing_history` extension | 🔵 |
| Update `process_raster_v2` | 🔵 |

---

## Feature: Dynamic OpenAPI Documentation 🔵 BACKLOG

**Purpose**: Generate interactive API docs from OpenAPI spec
**Current**: Static HTML in `web_interfaces/docs/interface.py`

---

# ✅ RECENTLY COMPLETED

See `HISTORY.md` for full details:

| Date | Item |
|------|------|
| 18 DEC 2025 | OGC API Styles module complete (E4.F4.1) |
| 18 DEC 2025 | Service Layer API Phase 4 complete |
| 12 DEC 2025 | Unpublish workflows implemented |
| 11 DEC 2025 | Service Bus queue standardization |
| 07 DEC 2025 | Container inventory consolidation |
| 05 DEC 2025 | JPEG COG compression fix |

---

**Last Updated**: 19 DEC 2025 (Added E6: Data Externalization)
