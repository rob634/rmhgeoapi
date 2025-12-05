# Active Tasks - Geospatial ETL Pipelines

**Last Updated**: 05 DEC 2025
**Author**: Robert and Geospatial Claude Legion

**Note**: Completed tasks have been moved to `HISTORY2.md` (05 DEC 2025 cleanup)

---

## 🚨 HIGH PRIORITY

### 1. Azure Data Factory Integration (29 NOV 2025)

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

### 2. Idempotency Fixes for ETL Workflows (25 NOV 2025)

**Status**: 🔴 **READY FOR IMPLEMENTATION**
**Priority**: HIGH - Prevents duplicate data on retry

**Issue**: Some ETL handlers don't handle retries gracefully:
- `ingest_vector` Stage 2: Appends rows on retry (should DELETE+INSERT)
- Job cleanup/retry endpoints not implemented

**Tasks**:
- [ ] Implement DELETE+INSERT pattern in `ingest_vector` Stage 2
- [ ] Create `/api/jobs/{job_id}/retry` endpoint
- [ ] Create `/api/jobs/{job_id}/cleanup` endpoint
- [ ] Add `delete_blobs_by_prefix()` to blob repository

---

## 🟡 MEDIUM PRIORITY

### 3. Heartbeat Mechanism for Long-Running Operations (30 NOV 2025)

**Status**: 📋 **READY FOR IMPLEMENTATION**
**Purpose**: Detect stuck tasks, prevent zombie jobs

**Design**:
- Tasks update `heartbeat` column every 30 seconds
- Janitor process marks tasks as FAILED if heartbeat > 5 minutes old
- Uses existing `heartbeat` column in tasks table

**Tasks**:
- [ ] Add heartbeat update to task processor loop
- [ ] Create janitor function (timer trigger, every 5 minutes)
- [ ] Add `/api/dbadmin/zombie-tasks` diagnostic endpoint

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

### Multispectral Band Combination URLs in STAC

**Status**: 🎨 **LOW PRIORITY**
**Purpose**: Add TiTiler URLs for common band combinations (NDVI, false color)

### Azure API Management (APIM)

**Status**: 📋 **FUTURE**
**Purpose**: Route single domain to specialized Function Apps
**When**: After microservices split

---

## ✅ Recently Completed

See `HISTORY2.md` for items completed and moved from TODO.md:
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

**Last Updated**: 05 DEC 2025
