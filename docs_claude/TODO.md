# Active Tasks - Geospatial ETL Pipelines

**Last Updated**: 11 DEC 2025 (Service Bus Queue Standardization Complete)

**Note**: Completed tasks have been moved to `HISTORY2.md` (05 DEC 2025 cleanup)

---

## ✅ RECENTLY COMPLETED (11 DEC 2025)

### Service Bus Queue Standardization - No Legacy Fallbacks

**Status**: ✅ **COMPLETE**
**Philosophy**: First Principles - explicit errors over fallback patterns

**What Changed**:
- Removed `geospatial-tasks` legacy queue - now only 3 queues:
  - `geospatial-jobs` - Job orchestration + stage_complete signals
  - `raster-tasks` - Memory-intensive GDAL operations (low concurrency)
  - `vector-tasks` - DB-bound and lightweight operations (high concurrency)
- All task types MUST be explicitly mapped in `TaskRoutingDefaults`
- Unmapped task types raise `ContractViolationError` (no silent fallback)
- Retry logic now routes back to original queue (was routing to legacy queue)
- Health endpoint includes `task_routing` check for configuration validation

**Files Modified**:
- `config/defaults.py` - Removed `TASKS_QUEUE`, expanded `TaskRoutingDefaults`
- `config/queue_config.py` - Removed `tasks_queue` field
- `config/app_mode_config.py` - Removed `listens_to_legacy_tasks` property
- `function_app.py` - Removed legacy tasks trigger
- `core/machine.py` - Explicit routing with `ContractViolationError`
- `triggers/health.py` - Added `_check_task_routing_coverage()`
- `triggers/admin/servicebus.py` - Updated known queues
- `infrastructure/service_bus.py` - Updated `ensure_all_queues_exist()`

---

## 🚨 IMMEDIATE - NEXT WORK ITEM

### Database Diagnostics & Remote Administration Enhancement (07 DEC 2025)

**Status**: 🔴 **IMMEDIATE PRIORITY** - Ready for Implementation
**Priority**: HIGH - QA environment has no direct database access
**Purpose**: HTTP-based database inspection, verbose pre-flight validation, DDH visibility
**Full Plan**: `~/.claude/plans/vast-leaping-candle.md`

**Problem**: QA database requires PRIVX → Windows Server → DBeaver workflow. Need comprehensive remote diagnostics.

**Phase 1: Enhanced Health Endpoint** (START HERE):
- Add `schema_summary` component (all schemas, tables, row counts, STAC stats)
- Add `config_sources` when `DEBUG_MODE=true` (show env var vs default origins)
- File: `triggers/health.py`

**Phase 2: Verbose Pre-Flight Validation**:
- Add `job_context` to `run_validators()` (job_type, submission endpoint)
- Enhanced messages: `"Blob 'x' not found (param: blob_name, job: process_raster_v2)"`
- Files: `infrastructure/validators.py`, `jobs/mixins.py`

**Quick Start**:
```bash
# Test current health endpoint
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

---

## 🚨 HIGH PRIORITY

### 1. Service Layer API - Raster & xarray Endpoints (18 DEC 2025)

**Status**: 📋 **PLANNING COMPLETE** - Ready for Implementation
**Priority**: 🚨 HIGH - Convenience wrappers for TiTiler + direct Zarr access
**Full Plan**: `/SERVICE-LAYER-API-DESIGN.md`

**Problem**: TiTiler requires full blob URLs, complex parameters (`bidx`, `decode_times`, `variable`). Time-series queries require N HTTP requests (slow).

**Solution**: Two new API layers:
- `/api/raster/` - TiTiler proxy with STAC item lookup (single time-slice operations)
- `/api/xarray/` - Direct Zarr access for time-series and temporal aggregation

**Strategy**: Build in `rmhazuregeoapi` first, validate, then migrate to `rmhogcstac`.

---

#### Phase 1: Foundation (Clients + Infrastructure)

| Step | Task | Files |
|------|------|-------|
| 1.1 | Add xarray dependencies to requirements.txt | `requirements.txt` |
| 1.2 | Create TiTiler HTTP client service | `services/titiler_client.py` |
| 1.3 | Create internal STAC client | `services/stac_client.py` |
| 1.4 | Create xarray/Zarr reader service | `services/xarray_reader.py` |
| 1.5 | Add TITILER_BASE_URL to config if not present | `config/settings.py` |

**Dependencies to Add**:
```
xarray
zarr
fsspec
adlfs
aiohttp
httpx[http2]
```

---

#### Phase 2: Raster API (`/api/raster/...`)

| Step | Task | Endpoint |
|------|------|----------|
| 2.1 | Create raster router module | `raster_api/__init__.py` |
| 2.2 | Implement extract endpoint | `GET /api/raster/extract/{collection}/{item}` |
| 2.3 | Implement point endpoint | `GET /api/raster/point/{collection}/{item}` |
| 2.4 | Implement clip endpoint | `GET /api/raster/clip/{collection}/{item}` |
| 2.5 | Implement preview endpoint | `GET /api/raster/preview/{collection}/{item}` |
| 2.6 | Register routes in function_app.py | `function_app.py` |
| 2.7 | Test locally with existing STAC items | Manual testing |

**Deliverable**: Four `/api/raster/` endpoints proxying TiTiler.

---

#### Phase 3: xarray API (`/api/xarray/...`)

| Step | Task | Endpoint |
|------|------|----------|
| 3.1 | Create xarray router module | `xarray_api/__init__.py` |
| 3.2 | Implement point time-series | `GET /api/xarray/point/{collection}/{item}` |
| 3.3 | Implement statistics | `GET /api/xarray/statistics/{collection}/{item}` |
| 3.4 | Implement aggregate | `GET /api/xarray/aggregate/{collection}/{item}` |
| 3.5 | Add GeoTIFF/PNG output helpers | `xarray_api/output.py` |
| 3.6 | Register routes in function_app.py | `function_app.py` |
| 3.7 | Test locally with Zarr files | Manual testing |

**Deliverable**: Three `/api/xarray/` endpoints with direct Zarr access.

---

#### Phase 4: Polish + Deploy

| Step | Task |
|------|------|
| 4.1 | Add error handling (missing items, invalid params) |
| 4.2 | Add request validation (bbox format, date ranges) |
| 4.3 | Add caching for STAC lookups |
| 4.4 | Deploy to rmhazuregeoapi and test |
| 4.5 | Document API |

---

#### Phase 5: Migration to rmhogcstac

| Step | Task |
|------|------|
| 5.1 | Copy `raster_api/` and `xarray_api/` modules |
| 5.2 | Copy service clients |
| 5.3 | Update requirements.txt in rmhogcstac |
| 5.4 | Register routes in rmhogcstac function_app.py |
| 5.5 | Remove from rmhazuregeoapi (optional) |
| 5.6 | Deploy rmhogcstac and validate |

**Deliverable**: Clean separation - read-only queries in rmhogcstac, ETL in rmhazuregeoapi.

---

#### File Structure (New)

```
rmhazuregeoapi/
├── services/
│   ├── titiler_client.py      # Phase 1.2
│   ├── stac_client.py         # Phase 1.3
│   └── xarray_reader.py       # Phase 1.4
├── raster_api/                 # Phase 2
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   └── triggers.py
├── xarray_api/                 # Phase 3
│   ├── __init__.py
│   ├── config.py
│   ├── service.py
│   ├── output.py
│   └── triggers.py
└── function_app.py            # Register new routes
```

---

### 2. OGC API Styles (17 DEC 2025)

**Status**: 📋 **PLANNING COMPLETE** - Ready for Implementation
**Priority**: HIGH - Required for Curated Datasets styling
**Full Plan**: `/STYLE_IMPLEMENTATION.md`

**Problem**: OGC Features serves vector data but no styling - clients must hardcode styles. Need server-side style management with multi-format output.

**Solution**: OGC API - Styles extension with CartoSym-JSON canonical storage:
```
CartoSym-JSON (stored) → StyleTranslator → Leaflet / Mapbox GL / OpenLayers
```

**Architecture**:
```
GET /features/collections/{id}/styles         → list styles
GET /features/collections/{id}/styles/{sid}   → style document
      ?f=cartosym  → CartoSym-JSON (canonical)
      ?f=leaflet   → Leaflet style object/function
      ?f=mapbox    → Mapbox GL style layers
```

**Files to Create/Modify**:
| File | Action | Purpose |
|------|--------|---------|
| `ogc_features/style_translator.py` | CREATE | CartoSym → Leaflet/Mapbox |
| `ogc_features/triggers.py` | MODIFY | Add 2 trigger classes |
| `ogc_features/repository.py` | MODIFY | Add style query methods |
| `ogc_features/service.py` | MODIFY | Add style orchestration |
| `ogc_features/models.py` | MODIFY | Add Pydantic models |
| `core/schema/sql_generator.py` | MODIFY | Add `geo.feature_collection_styles` |
| `function_app.py` | MODIFY | Register style routes |

**Key Features**:
- CartoSym-JSON storage in PostgreSQL JSONB
- Data-driven styling with CQL2-JSON selectors
- Auto-generated Leaflet style functions
- Mapbox GL layer definitions
- ETL integration for default style creation

**Implementation Order**:
1. [ ] Add Pydantic models to `models.py`
2. [ ] Create `style_translator.py`
3. [ ] Add repository methods
4. [ ] Add service methods
5. [ ] Add trigger classes
6. [ ] Add schema for `geo.feature_collection_styles`
7. [ ] Register routes in `function_app.py`
8. [ ] Deploy and full-rebuild
9. [ ] Test endpoints
10. [ ] (Optional) ETL integration for auto-generated styles

---

### 3. Virtual Zarr / CMIP6 NetCDF Support (17 DEC 2025)

**Status**: 📋 **PLANNING COMPLETE** - Ready for Implementation
**Priority**: 🚨 HIGH - Client has 20-100GB CMIP6 NetCDF, exploring unnecessary Zarr conversion
**Full Plan**: `/VIRTUAL_ZARR_IMPLEMENTATION.md`

**Problem**: Client is about to spend weeks converting NetCDF to Zarr (2x storage, massive compute). Unnecessary - we can virtualize instead.

**Solution**: Kerchunk reference files that make NetCDF accessible as virtual Zarr:
```
Client's Plan:   NetCDF → Physical Zarr (weeks, 2x storage)
Our Solution:    NetCDF → Reference JSON (hours, trivial storage)
```

**Architecture**:
```
CMIP6 NetCDF (Bronze) → inventory_netcdf job → generate_virtual_zarr job → Kerchunk Refs (Silver)
                                                                                    ↓
Planetary Computer Zarr ──────────────────────────────────────────────────► TiTiler-xarray → Tiles
```

**New Components**:
| Component | File | Purpose |
|-----------|------|---------|
| CMIP6 Parser | `services/netcdf_handlers/cmip6_parser.py` | Parse CMIP6 filenames |
| Chunking Validator | `services/netcdf_handlers/handler_validate_netcdf.py` | Pre-flight check |
| Reference Generator | `services/netcdf_handlers/handler_generate_kerchunk.py` | Single file → JSON ref |
| Virtual Combiner | `services/netcdf_handlers/handler_combine_virtual.py` | Combine time series |
| STAC Registration | `services/netcdf_handlers/handler_register_xarray_stac.py` | datacube extension |
| Inventory Job | `jobs/inventory_netcdf.py` | Scan, parse, group CMIP6 files |
| Generate Job | `jobs/generate_virtual_zarr.py` | Full pipeline orchestration |

**Dependencies to Add**:
```
virtualizarr>=1.0.0
kerchunk>=0.2.0
h5netcdf>=1.3.0
h5py>=3.10.0
```

**Implementation Order**:
1. [ ] CMIP6 parser utility
2. [ ] Chunking validator handler
3. [ ] Reference generator handler
4. [ ] Virtual combiner handler
5. [ ] STAC registration handler (datacube extension)
6. [ ] Inventory job
7. [ ] Generate job
8. [ ] Handler/job registration
9. [ ] TiTiler-xarray configuration

---

### 4. Database Diagnostics & Remote Administration Enhancement (07 DEC 2025)

**Status**: 🟡 **READY FOR IMPLEMENTATION**
**Priority**: 🚨 HIGH - QA environment has no direct database access
**Purpose**: HTTP-based database inspection, verbose pre-flight validation, DDH visibility

**Problem**: QA database requires PRIVX → Windows Server → DBeaver workflow. Need comprehensive remote diagnostics.

**Existing Infrastructure** (29 dbadmin endpoints already work):
- ✅ `/dbadmin/schemas`, `/tables/{schema}.{table}/sample` - Schema inspection
- ✅ `/dbadmin/jobs`, `/tasks/{job_id}` - Job/task queries
- ✅ `/dbadmin/health`, `/diagnostics/all` - Health monitoring
- ✅ `DEBUG_MODE=true` / `DEBUG_LOGGING=true` - Verbose logging flags

**Implementation Phases**:

| Phase | Description | Priority | Files |
|-------|-------------|----------|-------|
| 1 | Enhanced Health Endpoint - schema summary, config sources | HIGH | `triggers/health.py` |
| 2 | Verbose Pre-Flight Validation - job context, param origins/destinations | HIGH | `infrastructure/validators.py`, `jobs/mixins.py` |
| 3 | New Diagnostic Endpoints - config audit, ETL lineage, error aggregation | MEDIUM | `triggers/admin/db_diagnostics.py` |
| 4 | Debug Mode Integration - unified verbose flag behavior | LOW | `config/app_config.py` |
| 5 | Platform Status for DDH - `/platform/health`, `/stats`, `/failures` | MEDIUM | `triggers/trigger_platform_status.py` |

**Phase 1: Enhanced Health Endpoint**
- Add `schema_summary` component (all schemas, tables, row counts, STAC stats)
- Add `config_sources` when `DEBUG_MODE=true` (show env var vs default origins)

**Phase 2: Verbose Pre-Flight Validation**
- Add `job_context` to `run_validators()` (job_type, submission endpoint)
- Enhanced messages: `"Blob 'x' not found (param: blob_name, job: process_raster_v2)"`
- Validation summary report on success (source → destination, validators run, timing)

**Phase 3: New Diagnostic Endpoints**
- `GET /api/dbadmin/diagnostics/config` - All config with sources (masked secrets)
- `GET /api/dbadmin/diagnostics/lineage/{job_id}` - Full data lineage (source → STAC → table)
- `GET /api/dbadmin/diagnostics/errors?hours=24` - Error aggregation by job type

**Phase 4: Debug Mode Integration**
- Ensure `DEBUG_MODE=true` enables all verbose features
- Add debug banner to dbadmin responses

**Phase 5: Platform Status for DDH**
- `GET /api/platform/health` - Simplified health (no internal details)
- `GET /api/platform/stats?hours=24` - Aggregated job statistics
- `GET /api/platform/failures?hours=24` - Sanitized recent failures
- `GET /api/platform/status/{request_id}?verbose=true` - Enhanced detail

**Security Notes (Phase 5)**:
- READ-ONLY endpoints only
- Sanitized errors (no stack traces, internal paths)
- Request scoping (DDH sees only their requests)

**Full Plan**: `~/.claude/plans/vast-leaping-candle.md`

---

### 5. Azure Data Factory Integration (29 NOV 2025)

**Status**: 📋 **READY FOR IMPLEMENTATION** - Phase 1 Code Complete
**Purpose**: Enterprise ETL orchestration and audit logging
**Depends On**: Dual Database Architecture (COMPLETE)

**What's Done**:
- ✅ Repository layer implemented (`infrastructure/data_factory.py`)
- ✅ Interface defined (`IDataFactoryRepository`)
- ✅ Configuration added to `config/app_config.py`
- ✅ `azure-mgmt-datafactory` added to requirements.txt

**What's Needed**:
- [ ] Create ADF instance in Azure (`az datafactory create`)
- [ ] Create `copy_staging_to_production` pipeline
- [ ] Add ADF environment variables to Function App
- [ ] Test: `RepositoryFactory.create_data_factory_repository()`
- [ ] Create `promote_data` job that triggers ADF pipeline

**Use Cases**:
- Database-to-database copy (staging → production)
- Audit logging with full lineage
- Large data volumes (>1M rows)
- Scheduled/recurring ETL

---

### 6. Janitor Blob Cleanup (05 DEC 2025)

**Status**: 🟡 **PARTIALLY COMPLETE**
**Priority**: HIGH - Prevents orphaned intermediate files

**What's Done** (DELETE+INSERT Idempotency):
- ✅ `ingest_vector` replaced by `process_vector` (27 NOV 2025)
- ✅ DELETE+INSERT pattern in `process_vector` Stage 2 via `insert_chunk_idempotent()`
- ✅ Janitor database cleanup (3 timer triggers, comprehensive)

**What's Missing** (Blob Cleanup):
The Janitor marks jobs as FAILED but doesn't clean up intermediate blob storage:

| Workflow | Container | Prefix Pattern |
|----------|-----------|----------------|
| Vector ETL | `rmhazuregeotemp` | `temp/vector_etl/{job_id}/chunk_*.pkl` |
| Large Raster V2 | `silver-mosaicjson` | `{job_id[:8]}/tiles/*.tif` |

**Tasks**:
- [ ] Add `delete_blobs_by_prefix(container, prefix)` to `BlobRepository`
- [ ] Integrate blob cleanup into `JanitorService.mark_job_as_failed()`
- [ ] Add job_type detection to determine cleanup pattern

**Deprioritized** (resubmit pattern works for retry):
- ~~`/api/jobs/{job_id}/retry` endpoint~~ → Lowest priority
- ~~`/api/jobs/{job_id}/cleanup` endpoint~~ → Consolidated into Janitor

---

## 🟡 MEDIUM PRIORITY

### 3. Heartbeat Mechanism for Long-Running Operations (30 NOV 2025)

**Status**: 🟡 **PARTIALLY COMPLETE**
**Purpose**: Detect stuck tasks, prevent zombie jobs

**What's Done**:
- ✅ Janitor Task Watchdog (5 min timer) - marks stale PROCESSING tasks as FAILED
- ✅ Janitor Job Health Monitor (10 min timer) - propagates task failures to jobs
- ✅ Janitor Orphan Detector (15 min timer) - catches zombie jobs, stuck queued jobs
- ✅ `/api/cleanup/status` endpoint - shows janitor configuration
- ✅ `/api/cleanup/history` endpoint - shows recent janitor runs

**What's Missing**:
- [ ] Active heartbeat updates from tasks (currently uses timestamp-based detection)
- [ ] `/api/dbadmin/zombie-tasks` diagnostic endpoint (nice-to-have)

---

### 4. Sensor Metadata Extraction & Provenance System (02 DEC 2025)

**Status**: 📋 **PLANNING COMPLETE**
**Purpose**: Extract sensor metadata from rasters, track data lineage

**Features**:
- Extract EXIF/TIFF tags (sensor, acquisition date, etc.)
- Store in STAC item properties
- Track processing provenance (source → COG → STAC)

**Tasks**:
- [ ] Create `services/sensor_metadata.py` extractor
- [ ] Add `stac:processing_history` extension
- [ ] Update `process_raster_v2` to extract metadata

---

### 5. Dead Code Audit (28 NOV 2025)

**Status**: 🟡 **IN PROGRESS**
**Purpose**: Remove orphaned code, reduce maintenance burden

**Found So Far**:
- `core/state_manager.py`: Two `create_job_record` methods - BOTH unused
- Various deprecated helper functions

**Tasks**:
- [ ] Audit `core/` folder for unused methods
- [ ] Audit `infrastructure/` for unused methods
- [ ] Remove commented-out code blocks
- [ ] Update FILE_CATALOG.md after cleanup

---

## 🎯 ARCHITECTURAL WORK

### 6. PgSTAC Repository Consolidation

**Status**: Ready to implement
**Purpose**: Fix "Collection not found after insertion" error

**Problem**: Two classes manage pgSTAC data:
- `PgStacRepository` (390 lines) - newer, cleaner
- `PgStacInfrastructure` (2,060 lines) - older, bloated

**Plan**:
1. Rename `PgStacInfrastructure` → `PgStacBootstrap` (setup only)
2. Move all data operations to `PgStacRepository`
3. Remove duplicate methods (collection_exists has 3 copies!)
4. Update `StacMetadataService` to use single repository

**Tasks**:
- [ ] Implement quick fix in `stac_collection.py` (single repo instance)
- [ ] Rename `infrastructure/stac.py` → `infrastructure/pgstac_bootstrap.py`
- [ ] Remove duplicate methods from PgStacBootstrap
- [ ] Update all imports

---

### 7. Repository Pattern Enforcement (16 NOV 2025)

**Status**: 🟡 **IN PROGRESS**
**Purpose**: Eliminate direct database connections

**Problem**: 5+ service files bypass `PostgreSQLRepository`:
- `triggers/schema_pydantic_deploy.py`
- `triggers/db_query.py`
- `core/schema/deployer.py`
- `infrastructure/postgis.py`
- `infrastructure/stac.py` (10+ direct connections)
- `services/vector/postgis_handler.py`

**Correct Pattern**:
```python
# ✅ ALLOWED
repo = PostgreSQLRepository()
with repo._get_connection() as conn:
    cur.execute("SELECT ...")

# ❌ NOT ALLOWED
conn_str = get_postgres_connection_string()
with psycopg.connect(conn_str) as conn:
    ...
```

**Tasks**:
- [ ] Fix `triggers/schema_pydantic_deploy.py`
- [ ] Fix `triggers/db_query.py`
- [ ] Fix `core/schema/deployer.py`
- [ ] Create `PgSTACRepository` for STAC operations
- [ ] Update vector handlers to use repository

---

## 📋 BACKLOG

### 8. Unpublish Workflows - Surgical Data Removal (05 DEC 2025)

**Status**: ✅ **IMPLEMENTED** (12 DEC 2025) - See Recently Completed
**Priority**: 🟡 MEDIUM - Future Enhancement
**Purpose**: Reverse raster/vector processing - remove STAC items and referenced data surgically

> **Implementation Complete**: All code written and registered. Deploy and test with `dry_run=true`.
> Files: `jobs/unpublish_raster.py`, `jobs/unpublish_vector.py`, `services/unpublish_handlers.py`, `core/models/unpublish.py`, `infrastructure/validators.py` (stac_item_exists, stac_collection_exists)

#### Overview

Create `unpublish_raster` and `unpublish_vector` jobs that:
- Remove STAC items from pgstac catalog
- Delete associated blobs (COGs, MosaicJSON, tiles) from Silver storage
- Optionally drop PostGIS tables (vectors)
- Track deletions in audit table for idempotency management
- **Never** delete Bronze source files (separate archive process)
- Protect system collections (`system-rasters`, `system-vectors`, `system-h3-grids`)

#### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Pattern | JobBaseMixin | 77% less boilerplate, declarative validation |
| Default behavior | `dry_run: True` | Safety-first for destructive operations |
| Collection cleanup | Delete empty (except system-*) | `STACDefaults.SYSTEM_COLLECTIONS` protected |
| Bronze files | Never delete | Separate archive process handles these |
| Batch unpublish | Future enhancement | Design handlers to accept lists now |
| Audit table | `app.unpublished_jobs` | Track deletions + fix job idempotency |

#### Data Artifacts by Workflow

| Workflow | Storage Artifacts | Database Artifacts |
|----------|-------------------|-------------------|
| `process_raster_v2` | `silver-cogs/{name}_cog.tif` | STAC item in `pgstac.items` |
| `process_large_raster_v2` | `silver-cogs/tile_*.tif` + `silver-mosaicjson/{id}_mosaic.json` | STAC item |
| `process_raster_collection_v2` | `silver-cogs/tile_*.tif` + `silver-mosaicjson/{id}_mosaic.json` | STAC item |
| `stac_catalog_container` | (none - just catalogs existing COGs) | STAC items |
| `process_vector` | (none - data in PostGIS) | PostGIS table `geo.{table}` + STAC item |

#### Files to Create

**1. `infrastructure/validators.py` - Add new validators:**
```python
@register_validator("stac_item_exists")
def validate_stac_item_exists(params, config) -> ValidatorResult:
    """Validates STAC item exists before unpublish."""
    # Query pgstac.items WHERE id = item_id AND collection = collection_id
    # Store item metadata in params['_stac_item'] for downstream use

@register_validator("stac_collection_exists")
def validate_stac_collection_exists(params, config) -> ValidatorResult:
    """Validates collection exists."""
    # Query pgstac.collections WHERE id = collection_id
```

**2. `core/models/unpublished.py` (~50 lines):**
```python
class UnpublishedJob(BaseModel):
    """Audit record for unpublished jobs."""
    id: str                          # UUID
    original_job_id: str             # Job that created the deleted item
    original_job_type: str           # e.g., "process_raster_v2"
    original_parameters: Dict        # Preserved for audit
    unpublish_job_id: str            # The unpublish job that deleted it
    stac_item_id: str                # Deleted STAC item
    collection_id: str               # Collection item was in
    artifacts_deleted: Dict          # {"blobs": [...], "table": "...", "stac_item": "..."}
    collection_deleted: bool         # Whether empty collection was removed
    unpublished_at: datetime
```

**3. `jobs/unpublish_raster.py` (~120 lines):**
```python
class UnpublishRasterJob(JobBaseMixin, JobBase):
    job_type = "unpublish_raster"
    description = "Remove raster STAC item and associated COG/MosaicJSON blobs"

    stages = [
        {"number": 1, "name": "inventory", "task_type": "inventory_raster_item", "parallelism": "single"},
        {"number": 2, "name": "delete_blobs", "task_type": "delete_blob", "parallelism": "fan_out"},
        {"number": 3, "name": "cleanup", "task_type": "delete_stac_and_audit", "parallelism": "single"}
    ]

    parameters_schema = {
        'stac_item_id': {'type': 'str', 'required': True},
        'collection_id': {'type': 'str', 'required': True},
        'dry_run': {'type': 'bool', 'default': True},  # Safety default!
    }

    resource_validators = [
        {'type': 'stac_item_exists', 'item_param': 'stac_item_id', 'collection_param': 'collection_id',
         'error': 'STAC item not found in collection'}
    ]
```

**4. `jobs/unpublish_vector.py` (~100 lines):**
```python
class UnpublishVectorJob(JobBaseMixin, JobBase):
    job_type = "unpublish_vector"
    description = "Remove vector STAC item and optionally drop PostGIS table"

    stages = [
        {"number": 1, "name": "inventory", "task_type": "inventory_vector_item", "parallelism": "single"},
        {"number": 2, "name": "drop_table", "task_type": "drop_postgis_table", "parallelism": "single"},
        {"number": 3, "name": "cleanup", "task_type": "delete_stac_and_audit", "parallelism": "single"}
    ]

    parameters_schema = {
        'stac_item_id': {'type': 'str', 'required': True},
        'collection_id': {'type': 'str', 'required': True},
        'drop_table': {'type': 'bool', 'default': True},
        'dry_run': {'type': 'bool', 'default': True},  # Safety default!
    }

    resource_validators = [
        {'type': 'stac_item_exists', 'item_param': 'stac_item_id', 'collection_param': 'collection_id',
         'error': 'STAC item not found in collection'}
    ]
```

**5. `services/unpublish_handlers.py` (~300 lines):**
```python
def inventory_raster_item(params: dict) -> dict:
    """Query STAC item, extract asset hrefs, find original job.

    Uses get_item_by_id() from infrastructure/pgstac_bootstrap.py (lines 1867-1939)
    Extracts: COG blobs, MosaicJSON, tile COGs from item['assets']
    Finds original job via item['properties']['app:job_id']
    """

def inventory_vector_item(params: dict) -> dict:
    """Query STAC item, extract PostGIS table reference.

    Parses asset href like "postgis://geo.table_name"
    """

def delete_blob(params: dict) -> dict:
    """Delete single blob from Azure Storage (idempotent).

    Uses BlobRepository.delete_blob()
    Returns success even if blob already deleted
    """

def drop_postgis_table(params: dict) -> dict:
    """Drop PostGIS table (idempotent).

    DROP TABLE IF EXISTS geo.{table_name} CASCADE
    Respects dry_run parameter
    """

def delete_stac_and_audit(params: dict) -> dict:
    """Delete STAC item, cleanup empty collection, record audit.

    1. DELETE FROM pgstac.items WHERE id = ? AND collection = ?
    2. Check if collection empty: COUNT(*) FROM pgstac.items WHERE collection = ?
    3. If empty AND NOT IN STACDefaults.SYSTEM_COLLECTIONS: DELETE FROM pgstac.collections
    4. Record to app.unpublished_jobs audit table
    5. Mark original job as unpublished (for idempotency fix)
    """
```

#### Files to Modify

1. **`infrastructure/validators.py`** - Add `stac_item_exists` and `stac_collection_exists` validators
2. **`core/models/__init__.py`** - Export `UnpublishedJob`
3. **`core/schema/sql_generator.py`** - Import `UnpublishedJob`, add to schema generation
4. **`jobs/__init__.py`** - Register `UnpublishRasterJob`, `UnpublishVectorJob` in `ALL_JOBS`
5. **`services/__init__.py`** - Register handlers in `ALL_HANDLERS`

#### Workflow Diagrams

**Unpublish Raster Flow:**
```
Stage 1: Inventory (single task)
├── Query STAC item by ID (get_item_by_id from pgstac_bootstrap.py:1867)
├── Extract asset hrefs (COGs, MosaicJSON, tiles)
├── Find original job via item['properties']['app:job_id']
└── Return blob list for Stage 2 fan-out

Stage 2: Delete Blobs (fan-out, one task per blob)
├── Task per blob: delete from silver-cogs/
├── Delete MosaicJSON from silver-mosaicjson/
└── Delete tile COGs if present (large raster/collection workflows)

Stage 3: Cleanup (single task)
├── DELETE FROM pgstac.items WHERE id = ? AND collection = ?
├── Check if collection empty
├── Delete collection if empty AND NOT in SYSTEM_COLLECTIONS
└── Record to app.unpublished_jobs audit table
```

**Unpublish Vector Flow:**
```
Stage 1: Inventory (single task)
├── Query STAC item by ID
├── Parse "postgis://geo.table_name" from asset href
└── Find original job via item['properties']['app:job_id']

Stage 2: Drop Table (single task, if drop_table=True)
└── DROP TABLE IF EXISTS geo.{table_name} CASCADE

Stage 3: Cleanup (single task)
├── DELETE FROM pgstac.items WHERE id = ? AND collection = ?
├── Check if collection empty
├── Delete collection if empty AND NOT in SYSTEM_COLLECTIONS
└── Record to app.unpublished_jobs audit table
```

#### Protected Collections (config/defaults.py line 365)

```python
STACDefaults.SYSTEM_COLLECTIONS = ["system-vectors", "system-rasters", "system-h3-grids"]
```
These collections are NEVER deleted even when empty.

#### Critical File References

| File | Purpose | Key Lines |
|------|---------|-----------|
| `jobs/mixins.py` | JobBaseMixin pattern | 1-670 |
| `infrastructure/validators.py` | Resource validators registry | All |
| `infrastructure/pgstac_bootstrap.py` | STAC query/delete functions | 1485-1600, 1867-1939 |
| `config/defaults.py` | STACDefaults.SYSTEM_COLLECTIONS | 365 |
| `core/schema/sql_generator.py` | Database schema generation | All |
| `services/stac_metadata_helper.py` | AppMetadata with job_id linkage | 163-197 |

#### Job-to-STAC Item Linkage

STAC items track which job created them via `app:` prefixed properties:
```python
item['properties']['app:job_id']   # Original job ID that created item
item['properties']['app:job_type'] # e.g., "process_raster_v2"
```
This allows unpublish to find and mark the original job as unpublished.

#### Implementation Order

1. Add validators to `infrastructure/validators.py`
2. Create `core/models/unpublished.py` audit model
3. Update `core/schema/sql_generator.py` for `app.unpublished_jobs` table
4. Create `services/unpublish_handlers.py` with 5 handlers
5. Create `jobs/unpublish_raster.py`
6. Create `jobs/unpublish_vector.py`
7. Register in `jobs/__init__.py` and `services/__init__.py`
8. Deploy and rebuild schema (`/api/dbadmin/maintenance/full-rebuild?confirm=yes`)
9. Test with `dry_run=true` first

#### Testing Commands

```bash
# 1. Dry-run unpublish raster (preview only - SAFE)
curl -X POST .../api/jobs/submit/unpublish_raster \
  -H "Content-Type: application/json" \
  -d '{"stac_item_id": "my-cog-item", "collection_id": "cogs", "dry_run": true}'

# 2. Actually unpublish raster (dry_run=false)
curl -X POST .../api/jobs/submit/unpublish_raster \
  -H "Content-Type: application/json" \
  -d '{"stac_item_id": "my-cog-item", "collection_id": "cogs", "dry_run": false}'

# 3. Unpublish vector but keep PostGIS table
curl -X POST .../api/jobs/submit/unpublish_vector \
  -H "Content-Type: application/json" \
  -d '{"stac_item_id": "countries", "collection_id": "vectors", "drop_table": false, "dry_run": false}'

# 4. Unpublish vector AND drop table
curl -X POST .../api/jobs/submit/unpublish_vector \
  -H "Content-Type: application/json" \
  -d '{"stac_item_id": "countries", "collection_id": "vectors", "drop_table": true, "dry_run": false}'
```

#### Future Enhancement: Batch Unpublish

Design already supports future batch operations:
```python
# Future parameters_schema addition:
'item_ids': {'type': 'list', 'required': False},  # Alternative to single stac_item_id

# Handlers designed to work with lists
def inventory_raster_item(params):
    item_id = params.get('stac_item_id')
    # OR batch mode:
    item_ids = params.get('item_ids', [item_id] if item_id else [])
```

---

### Dynamic OpenAPI Documentation Generation (13 DEC 2025)

**Status**: 🎨 **LOW PRIORITY** - Future Enhancement
**Purpose**: Generate interactive API documentation from OpenAPI specification

**Current State**: Static HTML rendering in `web_interfaces/docs/interface.py`
- Hardcoded endpoint documentation for `process_vector` and `process_raster`
- Works well, matches existing interface pattern
- Changes require editing Python file

**Future Enhancement**: Dynamic OpenAPI parsing
- Maintain `openapi.yaml` specification file with all endpoints
- Use JavaScript library (Swagger UI or Redoc) to parse and render at runtime
- Benefits:
  - Single source of truth for API documentation
  - Interactive "Try it out" functionality
  - Auto-generated client SDKs
  - Industry-standard format for API consumers

**Why Deferred**:
- Current static approach works and matches existing patterns
- OpenAPI spec would require converting WIKI markdown to structured format
- No immediate consumer requesting OpenAPI format
- Many higher priority items in backlog

**Implementation Notes** (when ready):
1. Create `static/openapi.yaml` with endpoint definitions
2. Serve Swagger UI or Redoc from CDN in docs interface
3. Point to `/api/openapi.yaml` endpoint for spec
4. Consider generating spec from Pydantic models (FastAPI pattern)

---

### Multispectral Band Combination URLs in STAC

**Status**: 🎨 **LOW PRIORITY**
**Purpose**: Add TiTiler URLs for common band combinations (NDVI, false color)

### Function App Separation: Vector Worker Extraction

**Status**: 📋 **FUTURE ENHANCEMENT**
**Priority**: 🟡 MEDIUM
**Reference**: `/PRODUCTION_ARCHITECTURE.md`

**Problem**: Single `host.json` cannot optimize for both raster (GDAL, 2-8GB RAM, low concurrency) and vector (geopandas, 20-200MB, high parallelism) workloads simultaneously.

**Selected Architecture**: Option A - Main ETL as Entry Point + Vector Worker
- Main app: HTTP triggers, orchestration, raster processing (`maxConcurrentCalls: 2`)
- Vector app: Service Bus trigger only, vector tasks (`maxConcurrentCalls: 32`)

**Implementation Phases**:
1. Queue separation: Create `raster-tasks` + `vector-tasks` queues, add routing to CoreMachine
2. Vector worker extraction: Deploy dedicated Function App for vector processing
3. Host.json optimization: Tune main app for raster after vector extraction
4. Container app for 50GB+ files (DEFERRED - wait for TiTiler Docker stability)

**Benefits**: 10-30x vector throughput, workload isolation, no OOM during mixed loads

---

### Docker Worker for Long-Running GDAL Operations (12 DEC 2025)

**Status**: 📋 **PLANNING COMPLETE** - Ready for Implementation
**Priority**: 🟡 MEDIUM - Future Enhancement
**Reference**: `/GDAL_WORKER.md` (comprehensive implementation guide)

**Problem**: Azure Functions has a 30-minute timeout. Large raster operations (tile extraction, COG creation for >1GB files) can exceed this limit.

**Solution**: Separate Docker-based worker on Azure Web App with dedicated App Service Plan.

**Key Architecture Decisions**:
| Decision | Choice | Rationale |
|----------|--------|-----------|
| Platform | Azure Web App (Docker) | Dedicated App Service Plan, no EA approval needed |
| Codebase | **Separate Git repo** | Clean separation, copy only needed components |
| Queue | NEW `docker-tasks` queue | Explicit routing, no race conditions |
| Timeout | 1 hour default (env configurable) | Covers largest raster operations |
| Priority | Raster operations only | Vector timeout issues are rare |

**Critical Finding**: Architecture already supports multi-queue jobs! Stage completion is queue-agnostic - counts tasks in database regardless of which queue processed them.

**Phase 1: rmhgeoapi Modifications** (this repo):
- [ ] Add `DOCKER_TASKS_QUEUE = "docker-tasks"` to `config/defaults.py`
- [ ] Add `DockerRoutingDefaults` class with `DOCKER_TASK_TYPES` list
- [ ] Add `docker_tasks_queue` field to `config/queues_config.py`
- [ ] Add `_should_route_to_docker()` method to `core/machine.py`
- [ ] Update `_get_queue_for_task()` to check Docker routing first
- [ ] Create `docker-tasks` queue in Azure Service Bus

**Phase 2+: New Repository** (`rmh-gdal-worker`):
- Create Docker image with GDAL dependencies
- Service Bus listener for `docker-tasks` queue
- Copy CoreMachine task processing logic
- Send `stage_complete` signals to `geospatial-jobs` queue

**Full Implementation Details**: See `/GDAL_WORKER.md`

---

### Azure API Management (APIM)

**Status**: 📋 **FUTURE**
**Purpose**: Route single domain to specialized Function Apps
**When**: After Function App separation complete

---

### Service Bus Sessions for Jobs Queue (09 DEC 2025)

**Status**: 📋 **FUTURE ENHANCEMENT** (Low Priority)
**Purpose**: Enable high-throughput job orchestration without message timeout risk
**When**: When job submission volume causes stage_complete signals to timeout

**Problem (Future Scale)**:
The `geospatial-jobs` queue combines:
- New job submissions (from HTTP)
- Stage advancement messages (internal)
- Stage complete signals (from workers)

At high volume, stage_complete signals could timeout waiting behind unrelated job submissions (current lock duration: PT5M).

**Solution**: Service Bus Sessions
- Enable sessions on `geospatial-jobs` queue
- Use `job_id` as `SessionId` for all messages
- Messages with same `job_id` processed in order (FIFO)
- Different jobs processed in parallel
- `maxConcurrentSessions: 32+` for high parallelism

**How It Works**:
```
Without Sessions:
  Queue: [job1] [job2] [stage_complete_job1] [job3]...
                              ↑ Could timeout behind unrelated jobs

With Sessions:
  Session job1: [job1] → [stage_complete_job1]  ← Processed together
  Session job2: [job2]                          ← Independent, parallel
  Session job3: [job3]                          ← Independent, parallel
```

**Implementation Requirements**:
1. Create new queue with sessions enabled (can't modify existing)
2. Update senders to set `session_id=job_id` on all messages
3. Update `function_app.py` trigger: `is_sessions_enabled=True`
4. Update `host.json`: `sessionHandlerOptions.maxConcurrentSessions: 32`

**Code Changes**:
- `jobs/mixins.py` - Add `session_id` to `send_message()` calls
- `core/machine.py` - Add `session_id` to stage_complete and advance messages
- `function_app.py` - Enable session mode on jobs queue trigger
- `host.json` - Add `sessionHandlerOptions` configuration

**Trade-offs**:
| Aspect | Current | With Sessions |
|--------|---------|---------------|
| Ordering | No guarantee | Per-job FIFO |
| Parallelism | `maxConcurrentCalls` | `maxConcurrentSessions` (higher) |
| Migration | N/A | Requires new queue |

**Trigger**: Implement when observing stage_complete timeouts in Application Insights or dead-letter queue growth.

---

## ✅ Recently Completed

See `HISTORY2.md` for items completed and moved from TODO.md:
- UNPUBLISH Workflows (12 DEC 2025) - `unpublish_raster` and `unpublish_vector` jobs with surgical data removal (COGs, MosaicJSON, PostGIS tables), audit trail in `app.unpublish_jobs`, validators (`stac_item_exists`, `stac_collection_exists`), all 5 handlers registered. Next: deploy and test with `dry_run=true`
- Container Inventory Consolidation (07 DEC) - Consolidated container listing into `inventory_container_contents` job with basic/geospatial modes, sync endpoint with zone/suffix/metadata params, archived 3 legacy jobs
- JPEG COG Compression Fix (05 DEC) - INTERLEAVE=PIXEL for YCbCr encoding
- JSON Deserialization Error Handling (28 NOV)
- Pre-Flight Resource Validation (27 NOV)
- Platform Schema Consolidation (26 NOV)
- SQL Generator Invalid Index Bug (24 NOV)
- config.py Refactor (25 NOV)
- STAC Metadata Encapsulation (25 NOV)
- Managed Identity Pattern (22 NOV)
- STAC API Fixed (19 NOV)

---

**Last Updated**: 18 DEC 2025 (Service Layer API - Raster & xarray added as HIGH priority #1)
