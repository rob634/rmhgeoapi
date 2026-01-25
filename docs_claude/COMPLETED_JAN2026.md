# Completed Features - January 2026

**Last Updated**: 25 JAN 2026
**Purpose**: Detailed completion summaries for features finished in January 2026
**Reference**: These are indexed in [TODO.md](./TODO.md)

---

## Explicit Approval Record Creation (F7.Approval)

**Completed**: 22 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Goal**: Every dataset MUST have an approval record - no implicit unapproved state

### Problem Statement

The approval workflow service existed but **no job handlers created approval records**:

| Handler | Creates STAC Item | Creates Approval Record |
|---------|------------------|------------------------|
| `handler_process_raster_complete.py` | Yes | No |
| `handler_process_large_raster_complete.py` | Yes | No |
| Vector handlers | Yes | No |

**Current behavior**: STAC items were published immediately with no QA gate.
**Required behavior**: Every STAC item starts unpublished, requires explicit approval.

### Design Decision: Centralized Hook

Created approval records in **CoreMachine job finalization** via the existing `on_job_complete` callback.

**Why this approach**:
- Single integration point - can't be forgotten
- Already has job context (`job_id`, `job_type`, `result`)
- `result` dict contains STAC info (`stac_item_id`, `stac_collection_id`)
- Non-fatal pattern already established (callback failures don't fail job)

### Implementation Summary

**Files Modified**:

| File | Change |
|------|--------|
| `services/stac_metadata_helper.py` | Added `app:published=False` to `AppMetadata.to_stac_properties()` |
| `function_app.py` | Implemented `_global_platform_callback()` with approval creation |

**Key Implementation Details**:

1. **STAC Items Default to Unpublished**
   - `AppMetadata.to_stac_properties()` now includes `'app:published': False`
   - All STAC items created via `STACMetadataHelper` automatically get this property

2. **Automatic Approval Record Creation**
   - `_global_platform_callback()` in `function_app.py` creates approval records
   - Triggered by CoreMachine's `on_job_complete` callback
   - Extracts STAC item/collection IDs from job result
   - Creates `PENDING` approval record via `ApprovalService`
   - Non-fatal: failures logged but don't affect job completion

3. **Classification Support**
   - `_extract_classification()` helper extracts classification from job result
   - Checks: `result.classification`, `result.parameters.classification`, `result.access_level`
   - Default: `ouo` (Official Use Only)
   - `public` triggers ADF pipeline on approval

**Workflow**:
```
Job Completes → STAC item created (app:published=false)
             → _global_platform_callback() called
             → Approval record created (PENDING)
             → Human approves via /api/platform/approve
             → STAC updated (app:published=true)
```

**Helper Functions Added to function_app.py**:
- `_extract_stac_item_id(result)` - Finds STAC item ID in various result structures
- `_extract_stac_collection_id(result)` - Finds STAC collection ID
- `_extract_classification(result)` - Gets classification (default: ouo)

---

## Consolidate Status Endpoints

**Completed**: 21 JAN 2026

### Implementation Summary

`GET /api/platform/status/{id}` now accepts EITHER:
- A `request_id` (Platform request identifier)
- A `job_id` (CoreMachine job identifier)

The endpoint auto-detects which type of ID was provided:
1. First tries lookup by `request_id`
2. If not found, tries reverse lookup by `job_id` via `PlatformRepository.get_request_by_job()`

**Deprecated endpoint**: `/api/platform/jobs/{job_id}/status`
- Still works but logs deprecation warning
- Response includes `Deprecation: true` header and `_deprecated` field

**Files modified**:
- `triggers/trigger_platform_status.py` - Added auto-detect logic
- `function_app.py` - Updated docstrings

---

## Force Reprocess via processing_options.overwrite

**Completed**: 21 JAN 2026

### Implementation Summary

Implemented via `processing_options.overwrite` (not separate `force_reprocess` parameter).

When `processing_options.overwrite: true` and request already exists:
1. Submits unpublish job for existing outputs (dry_run=False, force_approved=True)
2. Deletes existing platform request record
3. Creates new job with fresh processing

### Request Body

```json
{
    "dataset_id": "...",
    "resource_id": "...",
    "version_id": "...",
    "container_name": "...",
    "file_name": "...",
    "processing_options": {
        "overwrite": true
    }
}
```

### Response Variants

**When overwrite bypasses idempotency**: Normal 202 response with new job_id. The unpublish job runs in background.

**When request exists but overwrite=false**:
```json
{
    "success": true,
    "message": "Request already submitted (idempotent)",
    "hint": "Use processing_options.overwrite=true to force reprocessing"
}
```

**Files Modified**:
- `triggers/trigger_platform.py`:
  - Added `_handle_overwrite_unpublish()` helper
  - Added `_delete_platform_request()` helper
  - Added `_generate_table_name()` and `_generate_stac_item_id()` helpers
  - Modified `platform_request_submit()` idempotency check

---

## Consolidate Unpublish Endpoints

**Completed**: 21 JAN 2026

### Implementation Summary

`POST /api/platform/unpublish` now auto-detects data type:

**Input options** (in resolution order):
1. `request_id` → Lookup platform request, get data_type
2. `job_id` → Lookup platform request by job, get data_type
3. DDH identifiers (`dataset_id`, `resource_id`, `version_id`) → Lookup platform request
4. Explicit `data_type` with direct identifiers (cleanup mode)
5. Fallback: Infer from `table_name` (vector) or `stac_item_id`/`collection_id` (raster)

**Deprecated endpoints**:
- `/api/platform/unpublish/vector` - Still works but logs deprecation warning
- `/api/platform/unpublish/raster` - Still works but logs deprecation warning

**Files modified**:
- `triggers/trigger_platform.py` - Added `platform_unpublish()` and helper functions
- `function_app.py` - Registered new route, marked old routes as deprecated

**Also added `request_id` support to**:
- `/api/platform/approve`
- `/api/platform/revoke`

---

## Infrastructure as Code DRY Cleanup (F7.IaC)

**Completed**: 22 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Goal**: Consolidate DDL and schema definitions into single source of truth

### Background

Architecture review identified multiple DRY violations in database schema definitions.
Same tables defined in multiple places with **conflicting schemas**.

**Critical Issues Found**:
1. `geo.table_metadata` defined in 3+ places with different column sets
2. `ExpectedSchemaRegistry` manually duplicates Pydantic models
3. H3 schema defined in both `h3_schema.py` and `schema_analyzer.py`

### Architecture Goal

```
┌──────────────────────────────────────────────────────────────┐
│              SINGLE SOURCE OF TRUTH (Pydantic)               │
│  core/models/job.py, task.py, geo.py (NEW), h3.py (NEW)     │
└──────────────────────────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    DDL GENERATION                            │
│  core/schema/sql_generator.py (PydanticToSQL - EXTENDED)    │
└──────────────────────────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION                             │
│  infrastructure/database_initializer.py (CONSOLIDATED)       │
└──────────────────────────────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    DRIFT DETECTION                           │
│  infrastructure/schema_analyzer.py (reads from Pydantic)     │
└──────────────────────────────────────────────────────────────┘
```

### Architecture Decision: Separation of Concerns

**Problem**: `geo.table_metadata` mixed ETL traceability with service layer concerns.

**Solution**: Split into two tables:

```
┌─────────────────────────────────────────────────────────────────┐
│                    INTERNAL DATABASE                            │
├─────────────────────────────────────────────────────────────────┤
│  app schema (NEVER replicated)     geo schema (replicated via ADF)
│  ├── jobs                          ├── table_catalog ← Service Layer
│  ├── tasks                         │   • title, description, bbox
│  ├── vector_etl_tracking ──FK────────  • geometry_type, srid
│  │   • etl_job_id                  │   • providers, keywords
│  │   • source_file, source_crs     │   • stac_collection_id
│  │   • processing_timestamp        │   (NO ETL internals)
│  └── (internal only)               └── (replicable to external)
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Phases

#### Phase 1: Pydantic Models - COMPLETE

- Created `core/models/geo.py` with `GeoTableCatalog` Pydantic model
- Created `core/models/etl_tracking.py` with `VectorEtlTracking` model
- Exported from `core/models/__init__.py`
- Added `from_service_catalog()`, `from_internal_db()`, `split_to_catalog_and_tracking()` to VectorMetadata

#### Phase 2: DDL Generation - COMPLETE

New Methods Added to `PydanticToSQL`:
- `get_model_sql_metadata()` - Extract `__sql_*` ClassVar attributes from models
- `generate_table_from_model()` - Model-driven CREATE TABLE DDL
- `generate_indexes_from_model()` - Model-driven CREATE INDEX DDL
- `generate_enum_from_model()` - Schema-aware ENUM generation
- `generate_geo_schema_ddl()` - Complete geo schema DDL
- `generate_etl_tracking_ddl()` - ETL tracking tables DDL
- `generate_all_schemas_ddl()` - Master method for all schemas

#### Phase 3: Schema Migration - COMPLETE

- `_initialize_geo_schema()` now calls `PydanticToSQL.generate_geo_schema_ddl()`
- `_initialize_app_schema()` now calls both core DDL and `generate_etl_tracking_ddl()`
- FK dependency verified: checks `geo.table_catalog` exists before creating `app.vector_etl_tracking`
- Old hardcoded `geo.table_metadata` DDL removed

#### Phase 4: Code Updates - COMPLETE

**Files Updated**:
- `ogc_features/repository.py` - `get_table_metadata()`, `get_vector_metadata()` now query `geo.table_catalog`
- `services/vector/postgis_handler.py` - `register_table_metadata()` writes to BOTH tables
- `services/unpublish_handlers.py` - Queries/deletes from both tables
- `services/service_stac_vector.py` - `_get_vector_metadata()` uses `geo.table_catalog`
- `services/metadata_consistency.py` - All vector checks use `geo.table_catalog`
- `triggers/admin/db_maintenance.py` - Removed 100+ lines of hardcoded DDL, uses `PydanticToSQL`
- `triggers/admin/geo_table_operations.py` - All operations use `geo.table_catalog`
- `triggers/trigger_approvals.py` - STAC lookup uses `geo.table_catalog`
- `services/janitor_service.py` - Orphan detection uses `geo.table_catalog`

### Database Tables

| Old Table | New Table(s) | Schema | Pydantic Model |
|-----------|--------------|--------|----------------|
| `geo.table_metadata` | `geo.table_catalog` | geo | `GeoTableCatalog` |
| (new) | `app.vector_etl_tracking` | app | `VectorEtlTracking` |
| `app.jobs` | `app.jobs` | app | `JobRecord` |
| `app.tasks` | `app.tasks` | app | `TaskRecord` |

### Key Files Created

| File | Purpose |
|------|---------|
| `infrastructure/database_initializer.py` | Consolidated database initialization orchestrator |
| `infrastructure/schema_analyzer.py` | Drift detection and schema introspection |
| `core/models/geo.py` | GeoTableCatalog Pydantic model |
| `core/models/etl_tracking.py` | VectorEtlTracking Pydantic model |

---

## External Database Initialization (F4.3.8)

**Completed**: 21 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Feature**: F4.3 External Delivery Infrastructure
**Goal**: Initialize target databases with pgstac and geo schemas using temporary admin UMI

### Background

When replicating data to external databases for partners/public access,
the target database needs pgstac and geo schemas. This is a SETUP operation run by
DevOps with temporary admin credentials - the production app won't have write access.

### Architecture

```
POST /api/admin/external/initialize
{
  "target_host": "external-db.postgres.database.azure.com",
  "target_database": "geodb",
  "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "dry_run": false
}
```

### Implementation

| Story | Description | Status |
|-------|-------------|--------|
| S4.3.8a | Create `ExternalDatabaseInitializer` service class | Done |
| S4.3.8b | Reuse `PydanticToSQL.generate_geo_schema_ddl()` for geo schema | Done |
| S4.3.8c | Run pypgstac migrate via subprocess with target DB env vars | Done |
| S4.3.8d | Create HTTP endpoints `/api/admin/external/initialize` and `/prereqs` | Done |
| S4.3.8e | Add dry-run mode for validation | Done |

### Key Files

- `services/external_db_initializer.py` - `ExternalDatabaseInitializer` class
- `triggers/admin/admin_external_db.py` - Blueprint with HTTP endpoints

### DBA Prerequisites

Must be done before running:
1. External PostgreSQL server exists
2. Admin UMI user created in target database
3. Admin UMI has CREATE privilege on database
4. PostGIS extension enabled (service request required)
5. pgstac_admin, pgstac_ingest, pgstac_read roles created
6. Admin UMI granted pgstac_* roles WITH ADMIN OPTION

### API Endpoints

- `GET /api/admin/external/prereqs` - Check DBA prerequisites
- `POST /api/admin/external/initialize` - Initialize target database

---

## V0.8 MosaicJSON Removal (F7.18.MJ)

**Completed**: 25 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Goal**: Remove deprecated MosaicJSON from Docker raster workflow

### Background

MosaicJSON was documented as "NOT viable" (12 NOV 2025) due to two-tier authentication issues:
- MosaicJSON requires HTTPS for JSON file + OAuth for COG access
- Violates Managed Identity-only architecture requirements
- pgSTAC searches provide OAuth-only mosaic access

Despite being deprecated, MosaicJSON code remained in the Docker worker handler and was causing warnings in job results.

### Changes Made

#### Phase Reduction (5 → 4 phases)

| Before | After |
|--------|-------|
| 1. Tiling Scheme | 1. Tiling Scheme |
| 2. Extract Tiles | 2. Extract Tiles |
| 3. Create COGs | 3. Create COGs |
| 4. MosaicJSON | ~~Removed~~ |
| 5. STAC Collection | 4. STAC Collection |

#### Files Modified

| File | Changes |
|------|---------|
| `services/handler_process_raster_complete.py` | Removed Phase 4 (MosaicJSON) ~50 lines, renumbered phases |
| `jobs/process_raster_docker.py` | Removed mosaicjson from result dict, updated comments |
| `services/stac_collection.py` | Added V0.8 direct call mode, made mosaicjson_blob optional |

#### STAC Collection Service Updates

Added **two call modes** to `create_stac_collection()`:

1. **Direct Call Mode (V0.8)**: Handler passes `cog_blobs`/`cog_container` directly
   - No MosaicJSON dependency
   - Used by Docker handler

2. **Fan-in Mode (Legacy)**: Receives `previous_results` from MosaicJSON stage
   - Backward compatible for any remaining callers
   - MosaicJSON asset only added if `mosaicjson_blob` provided

#### Key Code Changes

```python
# _create_stac_collection_impl signature change
def _create_stac_collection_impl(
    collection_id: str,
    mosaicjson_blob: Optional[str],  # Was: str (required)
    ...
)

# MosaicJSON asset now conditional
if mosaicjson_blob:
    collection.add_asset("mosaicjson", Asset(...))
else:
    logger.info("No MosaicJSON asset (V0.8: use pgSTAC search)")
```

### Result

- Docker raster jobs no longer produce MosaicJSON warnings
- Tiled outputs use pgSTAC collection for mosaic access
- TiTiler URLs generated via pgSTAC search (collection-level) not MosaicJSON
- Code simplified: ~100 lines removed across 3 files
