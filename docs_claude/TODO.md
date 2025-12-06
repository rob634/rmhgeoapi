# Active Tasks - Geospatial ETL Pipelines

**Last Updated**: 05 DEC 2025 (Janitor blob cleanup update)
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

### 2. Janitor Blob Cleanup (05 DEC 2025)

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

**Status**: 📋 **PLANNING COMPLETE** - Ready for Implementation
**Priority**: 🟡 MEDIUM - Future Enhancement
**Purpose**: Reverse raster/vector processing - remove STAC items and referenced data surgically
**Designed By**: Robert and Geospatial Claude Legion

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
