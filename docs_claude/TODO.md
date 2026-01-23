# Working Backlog

**Last Updated**: 23 JAN 2026
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) — Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation

> **✅ HIGH PRIORITY items completed (22 JAN 2026)**: ~~Force Reprocess~~ ✅, ~~Consolidate Unpublish~~ ✅, ~~Consolidate Status~~ ✅, ~~Explicit Approval Records~~ ✅

---

## 📋 TESTING NEEDED

- [ ] **Test Approval Workflow** - Submit job, verify approval record created (PENDING), approve via API, verify `app:published=true`
- [ ] **Test Artifact/Revision Workflow** - Submit job with same dataset_id/resource_id/version_id, verify artifact revision increments
- [ ] **Test External Service Registry (22 JAN 2026)** - Deploy, run `action=ensure`, then:
  ```bash
  # Register a test service
  curl -X POST "https://rmhazuregeoapi-.../api/jobs/services/register" \
    -H "Content-Type: application/json" \
    -d '{"url": "https://services.nationalmap.gov/arcgis/rest/services/wbd/MapServer", "name": "USGS WBD"}'

  # List services
  curl "https://rmhazuregeoapi-.../api/jobs/services"

  # Force health check
  curl -X POST "https://rmhazuregeoapi-.../api/jobs/services/{service_id}/check"

  # Get stats
  curl "https://rmhazuregeoapi-.../api/jobs/services/stats"
  ```

---

## 🔥 ACTIVE: CoreMachine Gap Analysis & Execution Timeline

**Added**: 23 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Status**: GAPS FIXED - Ready for events table implementation
**Goal**: Add checkpoints/handling for silent failure points, then create job_events table for execution timeline UI

### Background

CoreMachine workflow has several potential "silent failure" points where errors could occur but not be properly logged or tracked. Need to:
1. Fix identified gaps in error handling
2. Create `app.job_events` table to track each execution step
3. Build UI to visualize execution timeline and identify "last successful step"

### CoreMachine Execution Flow

```
POST /api/platform/submit
  ↓
1. Job Creation (platform_service.submit_job)
   - Creates job record (QUEUED)
   - Creates stage records
   - Sends job message to Service Bus
   ↓
2. Job Message Processing (CoreMachine.handle_job_message)
   - Validates job exists
   - Creates tasks for stage 1
   - Sends task messages to Service Bus
   - Updates job status → PROCESSING
   ↓
3. Task Processing (CoreMachine.handle_task_message)
   - Executes task handler
   - Updates task status → COMPLETED/FAILED
   - Checks for stage completion ("last task turns out lights")
   ↓
4. Stage Advancement (CoreMachine._advance_to_next_stage)
   - Called when all tasks in stage complete
   - Creates tasks for next stage OR finalizes job
   ↓
5. Job Completion (CoreMachine._finalize_job)
   - Updates job status → COMPLETED
   - Calls on_job_complete callback (approval records, etc.)
```

### Gap Analysis

| Gap | Location | Issue | Severity | Fix |
|-----|----------|-------|----------|-----|
| GAP-1 | Task status update | Task execution succeeds but DB update fails | Already handled | ✅ Existing checkpoint logs |
| GAP-2 | Stage advancement | Stage advance fails after tasks complete | MEDIUM | Add checkpoint before/after |
| GAP-3 | mark_job_failed() | Return value not checked | HIGH | Check return + add checkpoint |
| GAP-4 | Retry logic | task_record None causes silent fall-through | HIGH | Add explicit None handling |
| GAP-5 | Task result conversion | Result parsing fails | Already handled | ✅ try/except with logging |
| GAP-6 | Job finalization | Finalization errors | Design decision | Keep non-fatal (job already COMPLETED) |
| GAP-7 | Completion callback | Callback failure not tracked | MEDIUM | Add checkpoint for callback status |

### Implementation Stories

#### Story 1: Fix GAP-3 - Check mark_job_failed Return Value ✅
**File**: `core/machine.py` ~line 1245
**Change**: Check return value and add checkpoint

#### Story 2: Fix GAP-4 - Handle task_record None in Retry Logic ✅
**File**: `core/machine.py` ~line 1350
**Change**: Add explicit early return with error checkpoint

#### Story 3: Fix GAP-7 - Add Checkpoint for Callback Failure ✅
**File**: `core/machine.py` ~line 2095
**Change**: Add checkpoint logging for callback success/failure

#### Story 4: Add GAP-2 Checkpoint for Stage Advancement ✅
**File**: `core/machine.py` ~line 1100
**Change**: Add checkpoint before and after stage advancement

#### Story 5: Create app.job_events Table (PENDING)
**Status**: Waiting - complete gap fixes first

**Table Design**:
```sql
CREATE TABLE app.job_events (
    event_id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64),
    event_type VARCHAR(50) NOT NULL,  -- job_created, task_started, task_completed, etc.
    event_status VARCHAR(20),         -- success, failure, warning
    event_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_job FOREIGN KEY (job_id) REFERENCES app.jobs(job_id)
);
CREATE INDEX idx_job_events_job ON app.job_events(job_id);
CREATE INDEX idx_job_events_time ON app.job_events(created_at);
```

#### Story 6: Create Execution Timeline UI (PENDING)
**Status**: Waiting - complete events table first

---

## 🔥 ACTIVE: UI Migration - Function App to Docker/Jinja2

**Added**: 23 JAN 2026
**Epic**: New - UI Infrastructure
**Status**: Phase 1 COMPLETE, Phase 2 PENDING
**Plan Document**: [UI_MIGRATION.md](/UI_MIGRATION.md)

### Goal

Migrate 36 web interface modules (~44,000 lines) from inline Python f-strings in Function App to proper Jinja2 templates in Docker app. Benefits:
- 60% code reduction through component reuse
- Static CSS/JS caching (currently regenerated every request)
- IDE support for HTML/CSS/JS
- Reusable macros instead of copy/paste duplication

### Phase 1: Foundation Setup ✅ COMPLETE (23 JAN 2026)

| Deliverable | Status | Notes |
|-------------|--------|-------|
| `templates/` directory structure | ✅ Done | base.html, components/, pages/ |
| `static/css/styles.css` | ✅ Done | 26KB extracted from base.py |
| `static/js/common.js` | ✅ Done | 22KB extracted from base.py |
| `templates_utils.py` | ✅ Done | Jinja2 config, render_template() |
| `templates/base.html` | ✅ Done | Layout with navbar, footer, HTMX |
| `templates/components/macros.html` | ✅ Done | 11 reusable macros |
| `templates/components/navbar.html` | ✅ Done | Navigation component |
| `templates/components/footer.html` | ✅ Done | Footer component |
| Static files mount in docker_service.py | ✅ Done | `/static/` endpoint |
| `/interface/home` route | ✅ Done | Landing page |
| Root `/` redirect | ✅ Done | Redirects to `/interface/home` |

**Available Macros**: `status_badge`, `card`, `stat_item`, `spinner`, `empty_state`, `error_state`, `modal`, `confirm_dialog`, `data_table`, `collection_card`, `service_status_card`

### Phase 2: System Health Dashboard (TOP PRIORITY) ⬜ PENDING

**Goal**: Migrate health interface as first real page

| Task | Status |
|------|--------|
| Review current `health/interface.py` (2,910 lines) | ⬜ Pending |
| Create `pages/admin/health.html` template | ⬜ Pending |
| Create `_health_status.html` HTMX partial | ⬜ Pending |
| Add `/interface/health` route | ⬜ Pending |
| Test auto-refresh via HTMX | ⬜ Pending |

### Phase 3: Unified Collection Browser (NEW) ⬜ PENDING

**Goal**: NEW interface combining STAC + OGC Feature Collections

| Task | Status |
|------|--------|
| Design unified collection data model | ⬜ Pending |
| Create API endpoint for unified list | ⬜ Pending |
| Create `pages/browse/collections.html` | ⬜ Pending |
| Create search/filter UI | ⬜ Pending |
| Create collection detail views | ⬜ Pending |

### Remaining Phases (REVIEW BEFORE MIGRATION)

All remaining interfaces require design review before migration:

| Phase | Interfaces | Total Lines |
|-------|------------|-------------|
| Phase 4 | jobs, tasks, pipeline, queues, execution | 8,207 |
| Phase 5 | submit_vector, submit_raster, submit_raster_collection, upload | 5,722 |
| Phase 6 | map, stac_map, h3_map, raster_viewer, fathom_viewer, vector_tiles, service_preview | 6,278 |
| Phase 7 | database, metrics, platform, external_services, integration, storage, promote_vector, gallery, promoted_viewer | 9,573 |
| Phase 8 | home, docs, swagger, redoc, h3, h3_sources, zarr, stac_collection | 4,609 |

---

## ✅ COMPLETE: Explicit Approval Record Creation (F7.Approval)

**Added**: 22 JAN 2026
**Completed**: 22 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Status**: ✅ DONE
**Goal**: Every dataset MUST have an approval record - no implicit unapproved state

### Problem Statement

The approval workflow service exists but **no job handlers create approval records**:

| Handler | Creates STAC Item | Creates Approval Record |
|---------|------------------|------------------------|
| `handler_process_raster_complete.py` | ✅ Yes | ❌ No |
| `handler_process_large_raster_complete.py` | ✅ Yes | ❌ No |
| Vector handlers | ✅ Yes | ❌ No |

**Current behavior**: STAC items are published immediately with no QA gate.
**Required behavior**: Every STAC item starts unpublished, requires explicit approval.

### Design Decision: Option B - Centralized Hook

Create approval records in **CoreMachine job finalization** via the existing `on_job_complete` callback.

**Why this approach**:
- Single integration point - can't be forgotten
- Already has job context (`job_id`, `job_type`, `result`)
- `result` dict contains STAC info (`stac_item_id`, `stac_collection_id`)
- Non-fatal pattern already established (callback failures don't fail job)

### Integration Point

`core/machine.py:2092-2105` - The `on_job_complete` callback:

```python
if self.on_job_complete:
    self.on_job_complete(
        job_id=job_id,
        job_type=job_type,
        status='completed',
        result=final_result  # Contains stac_item_id, stac_collection_id
    )
```

### Implementation Stories

#### Story 1: STAC Items Default to Unpublished

**File**: `services/stac_catalog.py` (and similar STAC creation points)

**Change**: When creating STAC items, set `app:published=false` by default:

```python
properties = {
    ...
    'app:published': False,  # Requires approval to publish
}
```

**Acceptance Criteria**:
- All new STAC items have `app:published=false`
- Existing `app:published=true` logic only runs on approval

#### Story 2: Create Approval Record in Job Completion Callback

**File**: `triggers/trigger_platform.py` (where `on_job_complete` is registered)

**Current callback location**: Search for where CoreMachine is instantiated with `on_job_complete`

**New logic** (add to existing callback or create wrapper):

```python
def on_job_complete_with_approval(job_id: str, job_type: str, status: str, result: dict):
    # Existing platform callback logic...

    # NEW: Create approval record if job produced STAC item
    if status == 'completed':
        stac_item_id = _extract_stac_item_id(result)
        stac_collection_id = _extract_stac_collection_id(result)

        if stac_item_id:
            try:
                from services.approval_service import ApprovalService
                from core.models.promoted import Classification

                approval_service = ApprovalService()
                approval_service.create_approval_for_job(
                    job_id=job_id,
                    job_type=job_type,
                    classification=Classification.OUO,  # Default, can be overridden
                    stac_item_id=stac_item_id,
                    stac_collection_id=stac_collection_id
                )
                logger.info(f"📋 Approval record created for job {job_id[:8]}")
            except Exception as e:
                # Non-fatal - log warning
                logger.warning(f"⚠️ Approval creation failed (non-fatal): {e}")


def _extract_stac_item_id(result: dict) -> Optional[str]:
    """Extract STAC item ID from various result structures."""
    # Direct path
    if result.get('stac', {}).get('item_id'):
        return result['stac']['item_id']
    # Nested in result
    if result.get('result', {}).get('stac', {}).get('item_id'):
        return result['result']['stac']['item_id']
    # item_id at top level
    if result.get('item_id'):
        return result['item_id']
    return None
```

**Acceptance Criteria**:
- Every completed job that produces a STAC item gets an approval record
- Approval records start in `PENDING` status
- Callback failures don't fail the job (non-fatal)

#### Story 3: Classification from Job Parameters

**Enhancement**: Allow jobs to specify classification in parameters.

```python
# In job parameters:
{
    "classification": "public"  # or "ouo" (default)
}

# In callback:
classification_str = result.get('classification') or params.get('classification') or 'ouo'
classification = Classification.PUBLIC if classification_str == 'public' else Classification.OUO
```

**Acceptance Criteria**:
- Jobs can specify `classification` parameter
- Defaults to OUO if not specified
- PUBLIC triggers ADF on approval (existing logic)

#### Story 4: Query Filter for Published Items

**File**: `infrastructure/pgstac_repository.py` or STAC query endpoints

**Change**: Add ability to filter STAC queries by `app:published=true`.

This enables:
- Public-facing APIs show only approved items
- Admin APIs can see all items (with approval status)

**Acceptance Criteria**:
- STAC search can filter by `app:published`
- Default behavior TBD (show all vs show published only)

### Implementation Summary (22 JAN 2026)

**Files Modified**:

| File | Change |
|------|--------|
| `services/stac_metadata_helper.py` | Added `app:published=False` to `AppMetadata.to_stac_properties()` |
| `function_app.py` | Implemented `_global_platform_callback()` with approval creation |

**Key Implementation Details**:

1. **STAC Items Default to Unpublished**
   - `AppMetadata.to_stac_properties()` now includes `'app:published': False`
   - All STAC items created via `STACMetadataHelper` automatically get this property
   - Applies to raster, vector, and collection items

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

## ✅ COMPLETE: Consolidate Status Endpoints

**Added**: 21 JAN 2026
**Completed**: 21 JAN 2026
**Status**: ✅ DONE

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

## ✅ COMPLETE: Force Reprocess via processing_options.overwrite

**Added**: 21 JAN 2026
**Completed**: 21 JAN 2026
**Status**: ✅ DONE

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

### Response (when overwrite bypasses idempotency)

Normal 202 response with new job_id. The unpublish job runs in background.

### Response (when request exists but overwrite=false)

```json
{
    "success": true,
    "message": "Request already submitted (idempotent)",
    "hint": "Use processing_options.overwrite=true to force reprocessing"
}
```

### Files Modified

- `triggers/trigger_platform.py`:
  - Added `_handle_overwrite_unpublish()` helper
  - Added `_delete_platform_request()` helper
  - Added `_generate_table_name()` and `_generate_stac_item_id()` helpers
  - Modified `platform_request_submit()` idempotency check

---

## ✅ COMPLETE: Consolidate Unpublish Endpoints

**Added**: 21 JAN 2026
**Completed**: 21 JAN 2026
**Status**: ✅ DONE

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

## ✅ COMPLETE: Infrastructure as Code DRY Cleanup (F7.IaC)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Consolidate DDL and schema definitions into single source of truth
**Added**: 21 JAN 2026
**Completed**: 22 JAN 2026
**Status**: ✅ DONE (Phases 1-5 complete, H3 schema deferred)

### Background

Architecture review identified multiple DRY violations in database schema definitions.
Same tables defined in multiple places with **conflicting schemas**.

**Critical Issues Found**:
1. `geo.table_metadata` defined in 3+ places with different column sets
2. `ExpectedSchemaRegistry` manually duplicates Pydantic models
3. H3 schema defined in both `h3_schema.py` and `schema_analyzer.py`

### New Files Created (21 JAN 2026)

| File | Purpose |
|------|---------|
| `infrastructure/database_initializer.py` | Consolidated database initialization orchestrator |
| `infrastructure/schema_analyzer.py` | Drift detection and schema introspection |

### Architecture Goal

```
┌──────────────────────────────────────────────────────────────┐
│              SINGLE SOURCE OF TRUTH (Pydantic)               │
│  core/models/job.py, task.py, geo.py (NEW), h3.py (NEW)     │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    DDL GENERATION                            │
│  core/schema/sql_generator.py (PydanticToSQL - EXTENDED)    │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION                             │
│  infrastructure/database_initializer.py (CONSOLIDATED)       │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    DRIFT DETECTION                           │
│  infrastructure/schema_analyzer.py (reads from Pydantic)     │
└──────────────────────────────────────────────────────────────┘
```

### Architecture Decision: Separation of Concerns (21 JAN 2026)

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

**Key Classes Created**:
- `GeoTableCatalog` (core/models/geo.py) → `geo.table_catalog`
- `VectorEtlTracking` (core/models/etl_tracking.py) → `app.vector_etl_tracking`
- `VectorMetadata.from_service_catalog()` - External DB factory
- `VectorMetadata.from_internal_db()` - Internal DB factory (joins both tables)
- `VectorMetadata.split_to_catalog_and_tracking()` - Migration helper

### Implementation Stories

#### Phase 1: Pydantic Models ✅ COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.IaC.1 | Create `core/models/geo.py` with `GeoTableCatalog` Pydantic model | ✅ 21 JAN |
| S7.IaC.1b | Create `core/models/etl_tracking.py` with `VectorEtlTracking` model | ✅ 21 JAN |
| S7.IaC.3 | Export new models from `core/models/__init__.py` | ✅ 21 JAN |
| S7.IaC.3b | Add `from_service_catalog()`, `from_internal_db()`, `split_to_catalog_and_tracking()` to VectorMetadata | ✅ 21 JAN |

#### Phase 2: DDL Generation ✅ COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.IaC.5a | Extend `PydanticToSQL` to generate DDL for `GeoTableCatalog` → `geo.table_catalog` | ✅ 21 JAN |
| S7.IaC.5b | Extend `PydanticToSQL` to generate DDL for `VectorEtlTracking` → `app.vector_etl_tracking` | ✅ 21 JAN |
| S7.IaC.5c | Add FK constraint: `app.vector_etl_tracking.table_name` → `geo.table_catalog.table_name` | ✅ 21 JAN |
| S7.IaC.4 | Update `ExpectedSchemaRegistry` to read from Pydantic models dynamically | 📋 Deferred |

**New Methods Added to `PydanticToSQL`** (21 JAN 2026):
- `get_model_sql_metadata()` - Extract `__sql_*` ClassVar attributes from models
- `generate_table_from_model()` - Model-driven CREATE TABLE DDL
- `generate_indexes_from_model()` - Model-driven CREATE INDEX DDL
- `generate_enum_from_model()` - Schema-aware ENUM generation
- `generate_geo_schema_ddl()` - Complete geo schema DDL
- `generate_etl_tracking_ddl()` - ETL tracking tables DDL
- `generate_all_schemas_ddl()` - Master method for all schemas

#### Phase 3: Schema Migration ✅ COMPLETE

**Note**: User confirmed nuke-and-rebuild approach - no migration scripts needed.

| Story | Description | Status |
|-------|-------------|--------|
| S7.IaC.13 | Drop `geo.table_metadata`, create `geo.table_catalog` via PydanticToSQL | ✅ 21 JAN |
| S7.IaC.14 | Create `app.vector_etl_tracking` via PydanticToSQL | ✅ 21 JAN |
| S7.IaC.7 | Refactor `DatabaseInitializer._initialize_geo_schema()` to use `generate_geo_schema_ddl()` | ✅ 21 JAN |
| S7.IaC.7b | Refactor `DatabaseInitializer._initialize_app_schema()` to use `generate_etl_tracking_ddl()` | ✅ 21 JAN |

**Changes Made** (21 JAN 2026):
- `_initialize_geo_schema()` now calls `PydanticToSQL.generate_geo_schema_ddl()`
- `_initialize_app_schema()` now calls both core DDL and `generate_etl_tracking_ddl()`
- FK dependency verified: checks `geo.table_catalog` exists before creating `app.vector_etl_tracking`
- Old hardcoded `geo.table_metadata` DDL removed

#### Phase 4: Code Updates ✅ COMPLETE

| Story | Description | Status |
|-------|-------------|--------|
| S7.IaC.15 | Update `OgcRepository` to query `geo.table_catalog` instead of `geo.table_metadata` | ✅ 21 JAN |
| S7.IaC.16 | Update vector ETL pipeline to INSERT into both `geo.table_catalog` AND `app.vector_etl_tracking` | ✅ 21 JAN |
| S7.IaC.9 | Remove duplicate geo schema creation from `db_maintenance.py` | ✅ 21 JAN |
| S7.IaC.12 | Add `geo.feature_collection_styles` to Pydantic models | 📋 Deferred |

**Files Updated** (21 JAN 2026):
- `ogc_features/repository.py` - `get_table_metadata()`, `get_vector_metadata()` now query `geo.table_catalog`
- `services/vector/postgis_handler.py` - `register_table_metadata()` writes to BOTH tables
- `services/unpublish_handlers.py` - Queries/deletes from both tables
- `services/service_stac_vector.py` - `_get_vector_metadata()` uses `geo.table_catalog`
- `services/metadata_consistency.py` - All vector checks use `geo.table_catalog`
- `triggers/admin/db_maintenance.py` - Removed 100+ lines of hardcoded DDL, uses `PydanticToSQL`
- `triggers/admin/geo_table_operations.py` - All operations use `geo.table_catalog`
- `triggers/trigger_approvals.py` - STAC lookup uses `geo.table_catalog`
- `services/janitor_service.py` - Orphan detection uses `geo.table_catalog`

#### Phase 5: Cleanup (Priority 3) ✅ COMPLETE (22 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.IaC.10 | Deprecate `core/schema/deployer.py` (SchemaManager) | 📋 Low priority |
| S7.IaC.11 | Update wiki/documentation to reference new table names | ✅ 22 JAN |
| S7.IaC.12 | Add `geo.feature_collection_styles` to Pydantic models | ✅ 22 JAN |
| S7.IaC.17 | Deploy and test schema rebuild with new tables | ✅ 22 JAN |

#### Future: H3 Schema (Deferred)

| Story | Description | Status |
|-------|-------------|--------|
| S7.IaC.2 | Create `core/models/h3.py` with H3 table Pydantic models | 🔮 Deferred |
| S7.IaC.6 | Extend `PydanticToSQL` to support h3 schema DDL generation | 🔮 Deferred |
| S7.IaC.8 | Refactor `H3SchemaDeployer` to use Pydantic models | 🔮 Deferred |

### Key Files

| File | Current State | Target State |
|------|---------------|--------------|
| `core/models/geo.py` | ✅ `GeoTableCatalog` model | Source of truth for `geo.table_catalog` |
| `core/models/etl_tracking.py` | ✅ `VectorEtlTracking` model | Source of truth for `app.vector_etl_tracking` |
| `core/schema/sql_generator.py` | App DDL only | Extended for geo + app ETL tables |
| `infrastructure/database_initializer.py` | Uses raw SQL | Uses PydanticToSQL |
| `infrastructure/schema_analyzer.py` | Hardcoded expectations | Reads from Pydantic models |
| `triggers/admin/db_maintenance.py` | Has duplicate DDL | Remove DDL, call DatabaseInitializer |
| `core/schema/deployer.py` | App schema validation | **DEPRECATED** |

### Database Tables

| Old Table | New Table(s) | Schema | Pydantic Model |
|-----------|--------------|--------|----------------|
| `geo.table_metadata` | `geo.table_catalog` | geo | `GeoTableCatalog` |
| (new) | `app.vector_etl_tracking` | app | `VectorEtlTracking` |
| `app.jobs` | `app.jobs` | app | `JobRecord` |
| `app.tasks` | `app.tasks` | app | `TaskRecord` |

### Verification

```bash
# After consolidation - analyze for drift
python -c "
from infrastructure import SchemaAnalyzer
analyzer = SchemaAnalyzer()
report = analyzer.generate_migration_report()
print(report)
"

# Should show zero drift after proper consolidation
```

---

## 🔥 ACTIVE: Dataset Approval System (F4.AP)

**Epic**: E4 Security Zones / Externalization
**Goal**: QA workflow for reviewing datasets before STAC publication
**Added**: 16 JAN 2026
**Status**: 🚧 IN PROGRESS

### Background

When ETL jobs complete, datasets need human review before being marked "published" in STAC.
Classification determines post-approval action:
- **OUO** (Official Use Only): Just update STAC `app:published=true`
- **PUBLIC**: Trigger ADF pipeline for external distribution + update STAC

### Database Changes

**New Table**: `app.dataset_approvals`

| Column | Type | Description |
|--------|------|-------------|
| `approval_id` | VARCHAR(64) PK | Unique approval ID |
| `job_id` | VARCHAR(64) | Reference to completed job |
| `job_type` | VARCHAR(100) | Type of job (process_vector, etc.) |
| `classification` | ENUM | `public` or `ouo` |
| `status` | ENUM | `pending`, `approved`, `rejected` |
| `stac_item_id` | VARCHAR(100) | The STAC item to publish |
| `stac_collection_id` | VARCHAR(100) | The STAC collection |
| `reviewer` | VARCHAR(200) | Who approved/rejected |
| `notes` | TEXT | Review notes |
| `rejection_reason` | TEXT | Rejection reason (if rejected) |
| `adf_run_id` | VARCHAR(100) | ADF pipeline run ID (if public) |
| `created_at` | TIMESTAMP | When approval was created |
| `reviewed_at` | TIMESTAMP | When reviewed |
| `updated_at` | TIMESTAMP | Last update |

**New Enum**: `ApprovalStatus` (pending, approved, rejected)

**STAC Item Updates** (on approval):
- `app:published` = true
- `app:published_at` = timestamp
- `app:approved_by` = reviewer

### Implementation Stories

#### Phase 1: Core Infrastructure (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S4.AP.1 | Create `core/models/approval.py` with `DatasetApproval` model + `ApprovalStatus` enum | ✅ 16 JAN 2026 |
| S4.AP.2 | Export from `core/models/__init__.py` | ✅ 16 JAN 2026 |
| S4.AP.3 | Add table/indexes to `core/schema/sql_generator.py` | ✅ 16 JAN 2026 |
| S4.AP.4 | Create `infrastructure/approval_repository.py` with CRUD | ✅ 16 JAN 2026 |
| S4.AP.5 | Create `services/approval_service.py` with business logic | ✅ 16 JAN 2026 |
| S4.AP.6 | Create `triggers/admin/admin_approvals.py` HTTP endpoints | ✅ 16 JAN 2026 |
| S4.AP.7 | Register blueprint in `function_app.py` | ✅ 16 JAN 2026 |
| S4.AP.8 | Deploy + rebuild schema | 📋 |

#### Phase 2: Integration (Future)

| Story | Description | Status |
|-------|-------------|--------|
| S4.AP.9 | Hook job completion to create approval records | 📋 |
| S4.AP.10 | Wire viewer UI approve/reject buttons | 📋 |
| S4.AP.11 | ADF integration for public data | 📋 |

### API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/approvals` | List approvals (query: ?status=pending&limit=50) |
| GET | `/api/approvals/{id}` | Get specific approval with full details |
| POST | `/api/approvals/{id}/approve` | Approve (body: {reviewer, notes}) |
| POST | `/api/approvals/{id}/reject` | Reject (body: {reviewer, reason} - reason required) |
| POST | `/api/approvals/{id}/resubmit` | Resubmit rejected item back to pending |
| POST | `/api/approvals/test` | Create test approval (dev only) |

### Key Files

- `core/models/approval.py` - DatasetApproval model + ApprovalStatus enum
- `infrastructure/approval_repository.py` - Database CRUD
- `services/approval_service.py` - Business logic (approve/reject/STAC update)
- `triggers/admin/admin_approvals.py` - HTTP endpoints
- `core/schema/sql_generator.py` - DDL generation

### Verification Commands

```bash
# After deploy - use ensure (SAFE - additive, creates missing tables without dropping data)
curl -X POST ".../api/dbadmin/maintenance?action=ensure&confirm=yes"

# Or full rebuild (DESTRUCTIVE - drops ALL data, use only for fresh start)
# curl -X POST ".../api/dbadmin/maintenance?action=rebuild&confirm=yes"

# Create test approval
curl -X POST .../api/approvals/test \
  -H "Content-Type: application/json" \
  -d '{"job_id": "test-job-123", "classification": "ouo"}'

# List pending
curl ".../api/approvals?status=pending"

# Approve
curl -X POST .../api/approvals/{id}/approve \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "test@example.com", "notes": "Looks good"}'
```

---

## 🔥 ACTIVE: API Documentation Architecture (F12.8 + F12.9)

**Epic**: E12 Integration Onboarding
**Goal**: OpenAPI/Swagger for Function App ETL + Consumer docs for TiTiler
**Added**: 16 JAN 2026
**Status**: 🚧 IN PROGRESS (Structure first, content later)
**Reference**: `documentation_plan.md`

### Background

Two separate documentation deployments for different audiences:

| App | Audience | Docs Strategy |
|-----|----------|---------------|
| **Function App (ETL)** | B2B partners, internal systems | OpenAPI generation + Swagger/ReDoc |
| **TiTiler (Consumer)** | Web devs, data scientists | MkDocs narrative guides |

### F12.8: Function App API Documentation

**Phase 1: OpenAPI Infrastructure** ✅ COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S12.8.1-2 | Extend OpenAPI spec with Jobs/Platform/Approvals endpoints | ✅ 16 JAN |
| S12.8.3 | `/api/openapi.json` endpoint - serve static spec | ✅ (existed) |
| S12.8.4 | `/api/interface/swagger` - Swagger UI (inlined assets) | ✅ (existed) |
| S12.8.5 | `/api/interface/redoc` - ReDoc (CDN-loaded) | ✅ 16 JAN |
| S12.8.6 | Refactor to web_interfaces pattern (no inline code in function_app.py) | ✅ 16 JAN |

**Deliverables:**
- `/api/interface/swagger` - Interactive Swagger UI (inlined assets, self-contained)
- `/api/interface/redoc` - Clean ReDoc documentation (CDN-loaded)
- `/api/openapi.json` - OpenAPI 3.0 spec (now includes Jobs, Platform, Approvals)

**Key Files:**
- `web_interfaces/swagger/interface.py` - SwaggerInterface (pre-existing)
- `web_interfaces/redoc/interface.py` - ReDocInterface (created 16 JAN 2026)
- `openapi/platform-api-v1.json` - Extended spec

**Phase 2-3**: Documentation Hub UI + Content Refinement (see E12_interfaces.md)

### F12.9: TiTiler Consumer Documentation

**Phase 1: Documentation Structure (This App → TiTiler Claude)** ✅ COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S12.9.1 | Create `docs_titiler/IMPLEMENTATION_PLAN.md` - plan for TiTiler Claude | ✅ 16 JAN |
| S12.9.2 | Define documentation site structure (MkDocs Material recommended) | ✅ 16 JAN |
| S12.9.3 | Create content outline: Web Developer Guide | ✅ 16 JAN |
| S12.9.4 | Create content outline: Data Scientist Guide | ✅ 16 JAN |
| S12.9.5 | Create content outline: Auth Flow Guide | ✅ 16 JAN |

**Deliverable:** `docs_titiler/IMPLEMENTATION_PLAN.md` - Handoff document for TiTiler Claude with:
- MkDocs Material site structure
- Content outlines for all audience tracks
- Code examples for common use cases
- FATHOM flood data case study

**Phase 2**: Implementation by TiTiler Claude (see E12_interfaces.md for stories S12.9.6-12)

### Key Deliverables

1. **Function App**: `/api/interface/swagger`, `/api/interface/redoc`, `/api/openapi.json` ✅
2. **TiTiler**: `docs_titiler/IMPLEMENTATION_PLAN.md` (handoff document) ✅
3. **Shared**: FATHOM case study content (in TiTiler handoff)

### Key Files

- `docs/epics/E12_interfaces.md` - Full story definitions
- `documentation_plan.md` - Original strategy document
- `web_interfaces/swagger/interface.py` - SwaggerInterface
- `web_interfaces/redoc/interface.py` - ReDocInterface (created 16 JAN 2026)
- `openapi/platform-api-v1.json` - Extended OpenAPI spec
- `docs_titiler/IMPLEMENTATION_PLAN.md` - TiTiler handoff ✅

---

## 🔥 ACTIVE: Docker Orchestration Framework (F7.18)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Reusable infrastructure for Docker-based long-running jobs with connection pooling, checkpointing, and graceful shutdown
**Added**: 16 JAN 2026
**Updated**: 16 JAN 2026 (revised after reviewing `process_raster_docker`)
**Status**: 🚧 IN PROGRESS
**Priority**: HIGH - Foundation for ALL Docker jobs
**Reference**: `docs/epics/E7_pipeline_infra.md` → F7.18

### Existing Infrastructure (Already Implemented!)

**IMPORTANT**: Review of `process_raster_docker` revealed substantial existing infrastructure:

| Component | Status | Location |
|-----------|--------|----------|
| **CheckpointManager** | ✅ EXISTS | `infrastructure/checkpoint_manager.py` |
| **Task checkpoint fields** | ✅ EXISTS | `checkpoint_phase`, `checkpoint_data`, `checkpoint_updated_at` |
| **Handler pattern** | ✅ EXISTS | `services/handler_process_raster_complete.py` |
| **Connection pooling** | ❌ MISSING | Need to create |
| **DockerTaskContext** | ❌ MISSING | Need to create |
| **Graceful shutdown** | ❌ MISSING | Need to integrate |

**Existing CheckpointManager API**:
```python
# infrastructure/checkpoint_manager.py - ALREADY EXISTS!
checkpoint = CheckpointManager(task_id, task_repo)
checkpoint.should_skip(phase)      # Check if phase completed
checkpoint.save(phase, data, validate_artifact)  # Save with artifact validation
checkpoint.get_data(key, default)  # Retrieve checkpoint data
```

### Implementation Phases

#### Phase 1: Connection Pool Manager (S7.18.1-4) ✅ COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.1 | Create `ConnectionPoolManager` class | ✅ |
| S7.18.2 | Integrate with `PostgreSQLRepository._get_connection()` | ✅ |
| S7.18.3 | Wire token refresh to call `recreate_pool()` | ✅ |
| S7.18.4 | Add pool config env vars | ✅ |

**Key Files**: `infrastructure/connection_pool.py`, `infrastructure/postgresql.py`, `infrastructure/auth/__init__.py`

**Environment Variables** (Docker mode only):
- `DOCKER_DB_POOL_MIN` - Minimum pool connections (default: 2)
- `DOCKER_DB_POOL_MAX` - Maximum pool connections (default: 10)

#### Phase 2: Checkpoint Integration (S7.18.5-7) ✅ COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.5 | Task checkpoint schema | ✅ |
| S7.18.6 | CheckpointManager class | ✅ |
| S7.18.7 | Add `is_shutdown_requested()` method | ✅ |

**Key Files**: `infrastructure/checkpoint_manager.py`

**New Methods Added** (S7.18.7):
- `set_shutdown_event(event)` - Register shutdown event post-init
- `is_shutdown_requested()` - Check if shutdown signal received
- `should_stop()` - Alias for is_shutdown_requested()
- `save_and_stop_if_requested(phase, data)` - Convenience: save + check in one call

#### Phase 3: Docker Task Context (S7.18.8-11) ✅ COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.8 | Create `DockerTaskContext` dataclass | ✅ |
| S7.18.9 | Modify `BackgroundQueueWorker` to create context | ✅ |
| S7.18.10 | Pass context to handlers via CoreMachine | ✅ |
| S7.18.11 | Add progress reporting to task metadata | ✅ |

**Key Files**: `core/docker_context.py`, `docker_service.py`, `core/machine.py`

**How Handlers Access Context**:
```python
def my_handler(params: Dict) -> Dict:
    context = params.get('_docker_context')  # DockerTaskContext or None
    if context:
        # Docker mode: use provided context
        if context.should_stop():
            context.checkpoint.save(phase, data)
            return {'success': True, 'interrupted': True}
        context.report_progress(50, "Halfway done")
```

#### Phase 4: Graceful Shutdown (S7.18.12-15) ✅ COMPLETE (16 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.12 | Create `DockerWorkerLifecycle` class | ✅ |
| S7.18.13 | Integrate shutdown event with `BackgroundQueueWorker` | ✅ |
| S7.18.14 | Add shutdown status to `/health` endpoint | ✅ |
| S7.18.15 | Test graceful shutdown (SIGTERM → checkpoint saved) | ✅ |

**Key Files**: `docker_service.py`

**Graceful Shutdown Flow**:
1. SIGTERM received → `worker_lifecycle.initiate_shutdown()` called
2. Shutdown event set → all workers see `should_stop() = True`
3. In-flight tasks save checkpoint via `DockerTaskContext`
4. BackgroundQueueWorker abandons queued messages (retry later)
5. ConnectionPoolManager drains and closes
6. `/health` returns 503 with `status: "shutting_down"`

#### Phase 5: H3 Bootstrap Docker - First Consumer (S7.18.16-20) 📋

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.16 | Create `bootstrap_h3_docker` job definition | 📋 |
| S7.18.17 | Create `h3_bootstrap_complete` handler | 📋 |
| S7.18.18 | Register job and handler in `__init__.py` | 📋 |
| S7.18.19 | Test: Rwanda bootstrap with checkpoint/resume | 📋 |
| S7.18.20 | Test: Graceful shutdown mid-cascade | 📋 |

**Key Files**: `jobs/bootstrap_h3_docker.py`, `services/handler_h3_bootstrap_complete.py`

#### Phase 6: Migrate process_raster_docker (S7.18.21-23) ✅ COMPLETE (17 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.21 | Update handler to receive `DockerTaskContext` | ✅ |
| S7.18.22 | Use `context.checkpoint` with fallback for Function App | ✅ |
| S7.18.23 | Add `context.should_stop()` checks between phases | ✅ |

**Key Files**: `services/handler_process_raster_complete.py`

**Implementation Notes**:
- Handler now accepts `_docker_context` from params (Docker mode)
- Falls back to manual CheckpointManager creation (Function App mode)
- Shutdown checks added after Phase 1 and Phase 2
- Returns `{success: True, interrupted: True, resumable: True}` on graceful shutdown

#### Phase 7: Documentation (S7.18.24-26) 📋

| Story | Description | Status |
|-------|-------------|--------|
| S7.18.24 | Create `docs_claude/DOCKER_FRAMEWORK.md` | 📋 |
| S7.18.25 | Add handler template to `JOB_CREATION_QUICKSTART.md` | 📋 |
| S7.18.26 | Update `ARCHITECTURE_DIAGRAMS.md` | 📋 |

### Handler Pattern Evolution

```python
# OLD PATTERN (handler creates checkpoint)
def process_raster_complete(params: Dict, context: Optional[Dict] = None):
    task_id = params.get('_task_id')
    if task_id:
        checkpoint = CheckpointManager(task_id, task_repo)  # Handler creates

# NEW PATTERN (context provides checkpoint + shutdown awareness)
def process_raster_complete(params: Dict, context: DockerTaskContext):
    if context.should_stop():  # Shutdown awareness!
        return {'interrupted': True, 'resumable': True}
    if not context.checkpoint.should_skip(1):  # Checkpoint provided
        result = do_work()
        context.checkpoint.save(1, data={'result': result})
```

### Implementation Order

1. **Phase 1** (Connection Pool) - Independent, can ship first
2. **Phase 2** (Checkpoint Integration) - Mostly done, add shutdown awareness
3. **Phase 3** (Context) - Depends on Phase 2
4. **Phase 4** (Shutdown) - Depends on Phase 3
5. **Phase 5** (H3 Job) - First consumer, proves framework
6. **Phase 6** (Raster Migration) - Second consumer
7. **Phase 7** (Docs) - After framework proven

---

## 🔥 NEXT UP: RasterMetadata + STAC Self-Healing (F7.9 + F7.11)

**Epic**: E7 Pipeline Infrastructure → E2 Raster Data as API
**Goal**: Complete unified metadata architecture for rasters and wire up STAC self-healing
**Priority**: CRITICAL - Raster is primary STAC use case, self-healing depends on metadata
**Updated**: 12 JAN 2026

### Why Combined Priority

F7.9 (RasterMetadata) and F7.11 (STAC Self-Healing) are tightly coupled:
- F7.11 raster support **depends on** F7.9 being complete
- Both share the same service layer (`service_stac_metadata.py`, `stac_catalog.py`)
- Completing together ensures consistent metadata → STAC pipeline

### F7.9: RasterMetadata Implementation

**Status**: Phase 1 ✅ COMPLETE, Phase 2 📋 IN PROGRESS
**Dependency**: F7.8 ✅ (BaseMetadata, VectorMetadata pattern established)

#### Phase 1 (COMPLETE - 09 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.1 | Create `RasterMetadata` class in `core/models/unified_metadata.py` | ✅ |
| S7.9.2 | Create `app.cog_metadata` table DDL with typed columns | ✅ |
| S7.9.3 | Create `RasterMetadataRepository` with CRUD operations | ✅ |
| S7.9.4 | Implement `RasterMetadata.from_db_row()` factory method | ✅ |
| S7.9.5 | Implement `RasterMetadata.to_stac_item()` conversion | ✅ |
| S7.9.6 | Implement `RasterMetadata.to_stac_collection()` conversion | ✅ |

#### Phase 2 (IN PROGRESS - 12 JAN 2026)

**Key Discovery**: Both `process_raster_v2` and `process_raster_docker` use the SAME handler for STAC creation: `services/stac_catalog.py:extract_stac_metadata()`. This is the single wiring point.

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.8 | Wire `extract_stac_metadata` to populate `app.cog_metadata` | ✅ 12 JAN 2026 |
| S7.9.8a | Extract raster properties from STAC item for cog_metadata | ✅ |
| S7.9.8b | Call `RasterMetadataRepository.upsert()` after pgSTAC insert | ✅ |
| S7.9.8c | Handle graceful degradation if cog_metadata insert fails | ✅ |
| S7.11.5 | Enable raster rebuild in `rebuild_stac_handlers.py` | ✅ 12 JAN 2026 |
| S7.11.5a | Query `app.cog_metadata` for raster validation | ✅ |
| S7.11.5b | Use `RasterMetadata.to_stac_item()` for rebuild | ✅ |
| S7.9.TEST | Test: `process_raster_v2` populates cog_metadata + STAC | 📋 NEXT |

**Raster Job Architecture** (discovered 12 JAN 2026):
```
process_raster_v2 (Function App, <1GB)     process_raster_docker (Docker, large files)
        │                                           │
        │ Stage 3                                   │ Phase 3
        ▼                                           ▼
    ┌─────────────────────────────────────────────────┐
    │  services/stac_catalog.py:extract_stac_metadata │  ← SINGLE WIRING POINT
    │      Step 5: Insert STAC item to pgSTAC         │
    │      Step 5.5: Populate app.cog_metadata (NEW)  │
    └─────────────────────────────────────────────────┘
```

**Key Files**:
- `core/models/unified_metadata.py` - RasterMetadata domain model
- `core/models/raster_metadata.py` - CogMetadataRecord for DDL
- `core/schema/sql_generator.py` - Table/index generation
- `infrastructure/raster_metadata_repository.py` - CRUD operations

### F7.11: STAC Catalog Self-Healing

**Status**: 🚧 IN PROGRESS (vectors working, raster pending)
**Implemented**: 10 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| S7.11.1 | ✅ | Create `jobs/rebuild_stac.py` - 2-stage job definition |
| S7.11.2 | ✅ | Create `services/rebuild_stac_handlers.py` - validate + rebuild handlers |
| S7.11.3 | ✅ | Register job and handlers in `__init__.py` files |
| S7.11.4 | ✅ | Add `force_recreate` mode (delete existing STAC before rebuild) |
| S7.11.5 | 📋 | **Add raster support** (rebuild from app.cog_metadata) ← Depends on F7.9 |
| S7.11.6 | 📋 | Timer auto-submit (F7.10 detects → auto-submit rebuild job) |

**Key Files**:
- `jobs/rebuild_stac.py` - RebuildStacJob class
- `services/rebuild_stac_handlers.py` - stac_rebuild_validate, stac_rebuild_item

---

## 🟡 MEDIUM: Add Rasters to Existing Collections (F2.10)

**Added**: 12 JAN 2026
**Epic**: E2 Raster Data as API
**Goal**: Support adding rasters to existing STAC collections (vs always creating new)
**Status**: Core implementation ✅, Platform wiring 📋

### Completed (12 JAN 2026)

| Story | Description | Status |
|-------|-------------|--------|
| S2.10.1 | Add `collection_must_exist` param to `extract_stac_metadata` handler | ✅ |
| S2.10.2 | Add `collection_must_exist` to `process_raster_v2` parameters_schema | ✅ |
| S2.10.3 | Add `collection_must_exist` to `process_raster_docker` parameters_schema | ✅ |

### Remaining Work

| Story | Description | Status | Priority |
|-------|-------------|--------|----------|
| S2.10.4 | Create Platform endpoint `POST /api/platform/raster/add-to-collection` | 📋 | Medium |
| S2.10.5 | Endpoint wrapper enforces `collection_must_exist=true` | 📋 | Medium |
| S2.10.6 | Update `process_raster_collection_v2` to support adding tiles to existing collection | 📋 | Low |
| S2.10.7 | Test: `collection_must_exist=true` + existing collection → success | 📋 | Medium |
| S2.10.8 | Test: `collection_must_exist=true` + missing collection → clear error | 📋 | Medium |
| S2.10.9 | Document new parameter in API reference | 📋 | Low |

### Usage Examples

```bash
# Add raster to existing collection (fails if collection doesn't exist)
curl -X POST .../api/jobs/submit/process_raster_v2 \
  -d '{"container_name": "uploads", "blob_name": "new_tile.tif",
       "collection_id": "existing-collection", "collection_must_exist": true}'

# Default behavior unchanged (auto-creates collection if missing)
curl -X POST .../api/jobs/submit/process_raster_v2 \
  -d '{"container_name": "uploads", "blob_name": "my_raster.tif"}'
```

### Implementation Notes

**Platform endpoint design** (S2.8.4-5):
```python
# triggers/trigger_platform.py - New endpoint
@app.route(route="platform/raster/add-to-collection", methods=["POST"])
async def platform_add_raster_to_collection(req: func.HttpRequest) -> func.HttpResponse:
    """Add raster to EXISTING collection (fails if collection doesn't exist)."""
    # Enforce collection_must_exist=true, require collection_id
    request = PlatformAddToCollectionRequest.model_validate_json(req.get_body())
    # ... translate to process_raster_v2 with collection_must_exist=True
```

**Key Files**:
- `services/stac_catalog.py:224,357-362` - collection_must_exist check
- `jobs/process_raster_v2.py:87` - parameter schema
- `jobs/process_raster_docker.py:90` - parameter schema

---

## Docker Worker Remaining Backlog (Low Priority)

| Story | Description | Status |
|-------|-------------|--------|
| S7.13.13 | Test checkpoint/resume: Docker crash → resume from checkpoint | 📋 |
| S7.13.14 | Add `process_vector_docker` job (same pattern) | 📋 |

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Name | Status | Next Action |
|:--------:|------|------|--------|-------------|
| **1** | E7→E2 | **RasterMetadata + STAC Self-Healing** | 🔴 | F7.9 + F7.11: CRITICAL |
| **2** | E8 | **H3 Analytics (Rwanda)** | 🚧 | H3 bootstrap running (res 3-7) |
| 3 | E8 | Building Flood Exposure | 📋 | F8.7: MS Buildings → FATHOM → H3 |
| 4 | E9 | Pre-prepared Raster Ingest | 📋 | F9.8: COG copy + STAC |
| 5 | E2 | Raster Data as API | 🚧 | F2.7: Collection Processing |
| 6 | E3 | DDH Platform Integration | 🚧 | F3.1: Validate Swagger UI |
| — | E7 | Pipeline Builder | 📋 | F7.5: Future (after concrete implementations) |

**Focus**: Rwanda as test region for all analytics pipelines before scaling.

**Completed**:
- E9 FATHOM Rwanda Pipeline ✅
- E7 Unified Metadata Architecture ✅ (F7.8 VectorMetadata)
- E7 Docker Worker Infrastructure ✅ (F7.12-13)

---

## Current Sprint Focus

### 🟡 H3 Analytics on Rwanda

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: H3 aggregation of FATHOM flood data for Rwanda
**Dependency**: F9.1 ✅ (FATHOM merged COGs exist in silver-fathom)
**Status**: H3 bootstrap running (08 JAN 2026)

#### F8.13: Rwanda H3 Aggregation

| Story | Description | Status |
|-------|-------------|--------|
| S8.13.1 | Seed Rwanda H3 cells (res 2-7, country-filtered) | 🔴 Stage 3 timeout |
| S8.13.1a | **Fix H3 finalize timeout** - pg_cron + autovacuum | ✅ Done (08 JAN) |
| S8.13.1b | Enable pg_cron extension in Azure Portal | 📋 |
| S8.13.1c | Run pg_cron_setup.sql on database | 📋 |
| S8.13.1d | Re-run H3 bootstrap (run_vacuum=False) | 📋 |
| S8.13.2 | Add FATHOM merged COGs to source_catalog | 📋 |
| S8.13.3 | Run H3 raster aggregation on Rwanda FATHOM | 📋 |
| S8.13.4 | Verify zonal_stats populated for flood themes | 📋 |
| S8.13.5 | Test H3 export endpoint with Rwanda data | 📋 |

See [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) for pg_cron setup steps.

---

### 🟢 Building Flood Exposure Pipeline

**Epic**: E8 GeoAnalytics Pipeline
**Goal**: Calculate % of buildings in flood risk areas, aggregated to H3 level 7
**Dependency**: F8.13 (H3 cells for Rwanda), F9.1 ✅ (FATHOM COGs)
**Data Source**: Microsoft Building Footprints (direct download)
**Initial Scenario**: `fluvial-defended-2020` (baseline)

#### F8.7: Building Flood Exposure Job

| Story | Description | Status |
|-------|-------------|--------|
| S8.7.1 | Download MS Building Footprints for Rwanda | 📋 |
| S8.7.2 | Create `buildings` schema (footprints, flood_exposure tables) | 📋 |
| S8.7.3 | Create `BuildingFloodExposureJob` definition (4-stage) | 📋 |
| S8.7.4 | Stage 1 handler: `building_load_footprints` (GeoJSON → PostGIS) | 📋 |
| S8.7.5 | Stage 2 handler: `building_assign_h3` (centroid → H3 index) | 📋 |
| S8.7.6 | Stage 3 handler: `building_sample_fathom` (point → raster value) | 📋 |
| S8.7.7 | Stage 4 handler: `building_aggregate_h3` (SQL aggregation) | 📋 |
| S8.7.8 | End-to-end test: Rwanda + fluvial-defended-2020 | 📋 |
| S8.7.9 | Expand to all FATHOM scenarios (39 for Rwanda) | 📋 |

---

## Other Active Work

### ⚪ Future: Pipeline Builder (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Generalize FATHOM pipeline to configuration-driven raster processing
**Timeline**: After FATHOM + H3 + Open Buildings working on Rwanda

#### F7.5: Pipeline Builder

| Story | Description | Status |
|-------|-------------|--------|
| S7.5.1 | Abstract FATHOM dimension parser to configuration | 📋 |
| S7.5.2 | Create `ComplexRasterPipeline` base class | 📋 |
| S7.5.3 | YAML/JSON pipeline definition schema | 📋 |
| S7.5.4 | Pipeline Builder UI (visual orchestration) | 📋 |

**Design Principle**: Build concrete implementations first (FATHOM, H3, Buildings), then extract patterns.

---

## E4: Classification Enforcement & ADF Integration

**Added**: 07 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Make `access_level` (OUO/Public/Restricted) mandatory and prepare for ADF integration
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters

### Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

Currently `access_level` is inconsistently enforced across the codebase. This work makes it:
1. **Mandatory** at Platform API entry point
2. **Type-safe** using `AccessLevel` enum throughout
3. **Fail-fast** in pipeline tasks if somehow missing

### Current State Analysis (07 JAN 2026)

| Location | Type | Default | Required | Issue |
|----------|------|---------|----------|-------|
| `PlatformRequest` | `str` | `"OUO"` | ✅ | Not using enum |
| `AccessLevel` enum | `Enum` | N/A | N/A | Exists but unused |
| Job parameter schemas | `str` | `None` | ❌ | Loses value |
| `PlatformMetadata` dataclass | `Optional[str]` | `None` | ❌ | Loses value |
| `PlatformProperties` model | `Optional[AccessLevel]` | `None` | ❌ | Uses enum but optional |

**Key Files**:
- `core/models/stac.py:57-62` - `AccessLevel` enum definition
- `core/models/platform.py:147-151` - `PlatformRequest.access_level` field
- `triggers/trigger_platform.py` - Translation functions
- `jobs/process_raster_v2.py:92` - Job parameter schema
- `jobs/raster_mixin.py:93-98` - `PLATFORM_PASSTHROUGH_SCHEMA`
- `services/stac_metadata_helper.py:69` - `PlatformMetadata` dataclass
- `infrastructure/data_factory.py` - ADF repository (ready for testing)

### Phase 1: Enforce at Platform Level

**Goal**: Reject requests with invalid/missing classification at API entry point

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.1 | Update `PlatformRequest.access_level` to use `AccessLevel` enum | 📋 | `core/models/platform.py` |
| S4.CL.2 | Add Pydantic validator to normalize case (accept "OUO" → store as "ouo") | 📋 | `core/models/platform.py` |
| S4.CL.3 | Make `access_level` required (remove default) OR keep secure default "ouo" | 📋 | `core/models/platform.py` |
| S4.CL.4 | Update `_translate_to_coremachine()` to pass enum value (lowercase string) | 📋 | `triggers/trigger_platform.py` |
| S4.CL.5 | Add validation tests for Platform API rejection of invalid values | 📋 | `tests/` |

**Implementation Notes for S4.CL.1-3**:
```python
# core/models/platform.py - Change from:
access_level: str = Field(default="OUO", max_length=50, ...)

# To:
from core.models.stac import AccessLevel

access_level: AccessLevel = Field(
    default=AccessLevel.OUO,
    description="Data classification: public, ouo, restricted"
)

@field_validator('access_level', mode='before')
@classmethod
def normalize_access_level(cls, v):
    """Accept case-insensitive input, normalize to enum."""
    if isinstance(v, str):
        try:
            return AccessLevel(v.lower())
        except ValueError:
            raise ValueError(f"Invalid access_level '{v}'. Must be: public, ouo, restricted")
    return v
```

**Decision Point**: Keep `default=AccessLevel.OUO` (secure by default) or make truly required (no default). Recommend keeping default since OUO is the safe choice.

### Phase 2: Fail-Fast in Pipeline Tasks

**Goal**: Defense-in-depth - tasks fail immediately if access_level missing (shouldn't happen if Phase 1 works)

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.6 | Add `access_level` to job schemas with `required: True` | 📋 | `jobs/raster_mixin.py`, `jobs/process_raster_v2.py`, `jobs/process_vector.py` |
| S4.CL.7 | Add validation in STAC metadata creation (fail if missing) | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.8 | Add validation in promote handlers (data export tasks) | 📋 | `services/promote_service.py` |
| S4.CL.9 | Update `PlatformMetadata` dataclass to require access_level | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.10 | Add checkpoints logging for access_level at key stages | 📋 | Various handlers |

**Implementation Notes for S4.CL.6**:
```python
# jobs/raster_mixin.py - Update PLATFORM_PASSTHROUGH_SCHEMA:
PLATFORM_PASSTHROUGH_SCHEMA = {
    'dataset_id': {'type': 'str', 'default': None},
    'resource_id': {'type': 'str', 'default': None},
    'version_id': {'type': 'str', 'default': None},
    'access_level': {
        'type': 'str',
        'required': True,  # Now required!
        'allowed': ['public', 'ouo', 'restricted']
    },
}
```

**Implementation Notes for S4.CL.7**:
```python
# In job submission endpoint:
if file_size_mb > config.raster.raster_route_docker_mb:
    job_type = "process_raster_docker"  # Auto-route to Docker
else:
    job_type = "process_raster_v2"      # Standard Function App
```

**Alternative - TaskRoutingConfig**:
```bash
ROUTE_TO_DOCKER=create_cog,process_fathom_stack
```

**Current Decision**: Separate job definitions is simpler and sufficient for MVP.
Automatic routing can be added when:
1. Docker worker is proven stable
2. Real metrics show where the size threshold should be
3. Client convenience outweighs explicit job selection

---

### F4.3.8: External Database Initialization ✅ COMPLETE (21 JAN 2026)

**Epic**: E4 Security Zones / Externalization
**Feature**: F4.3 External Delivery Infrastructure
**Goal**: Initialize target databases with pgstac and geo schemas using temporary admin UMI

**Background**: When replicating data to external databases for partners/public access,
the target database needs pgstac and geo schemas. This is a SETUP operation run by
DevOps with temporary admin credentials - the production app won't have write access.

**Architecture**:
```
POST /api/admin/external/initialize
{
  "target_host": "external-db.postgres.database.azure.com",
  "target_database": "geodb",
  "admin_umi_client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "dry_run": false
}
```

**Implementation** (21 JAN 2026):

| Story | Description | Status |
|-------|-------------|--------|
| S4.3.8a | Create `ExternalDatabaseInitializer` service class | ✅ |
| S4.3.8b | Reuse `PydanticToSQL.generate_geo_schema_ddl()` for geo schema | ✅ |
| S4.3.8c | Run pypgstac migrate via subprocess with target DB env vars | ✅ |
| S4.3.8d | Create HTTP endpoints `/api/admin/external/initialize` and `/prereqs` | ✅ |
| S4.3.8e | Add dry-run mode for validation | ✅ |

**Key Files**:
- `services/external_db_initializer.py` - `ExternalDatabaseInitializer` class
- `triggers/admin/admin_external_db.py` - Blueprint with HTTP endpoints

**DBA Prerequisites** (must be done before running):
1. External PostgreSQL server exists
2. Admin UMI user created in target database
3. Admin UMI has CREATE privilege on database
4. PostGIS extension enabled (service request required)
5. pgstac_admin, pgstac_ingest, pgstac_read roles created
6. Admin UMI granted pgstac_* roles WITH ADMIN OPTION

**API Endpoints**:
- `GET /api/admin/external/prereqs` - Check DBA prerequisites
- `POST /api/admin/external/initialize` - Initialize target database

---

### F7.15: HTTP-Triggered Docker Worker (Alternative Architecture)

**Status**: 📋 PLANNED - Alternative to Service Bus polling
**Added**: 11 JAN 2026
**Prerequisite**: Complete F7.13 Option A first, then implement as configuration option

**Concept**: Eliminate Docker→Service Bus connection entirely.
Function App task worker HTTP-triggers Docker, then exits. Docker tracks its own state.

```
┌─────────────────┐    ┌──────────────────────┐
│  Function App   │───▶│  Service Bus Queue   │
│  (SB Trigger)   │◀───│  long-running-tasks  │
└────────┬────────┘    └──────────────────────┘
         │
         │ 1. HTTP POST /task/start
         │    {task_id, params, callback_url}
         │
         │ 2. Docker returns 202 Accepted immediately
         ▼
┌─────────────────┐
│  Docker Worker  │──── 3. Process task in background
│  (HTTP only)    │     4. Update task status in PostgreSQL
└────────┬────────┘     5. Optionally call callback_url when done
         │
         │ (Function App is already gone - no timeout issues)
         ▼
   Task completion detected by:
   - Polling task status table
   - Or callback to Function App HTTP endpoint
```

**Why This Might Be Better**:
1. **Simpler Docker auth** - Only needs HTTP endpoint, no Service Bus SDK
2. **No queue credentials in Docker** - Function App owns all queue logic
3. **Function App exits immediately** - No timeout concerns
4. **State in PostgreSQL** - Already have task status table

**Key Insight**: Docker uses THE SAME CoreMachine as Function App.
It's Python + SQL - the only difference is the trigger mechanism.

**Implementation Stories**:

| Story | Description | Status |
|-------|-------------|--------|
| S7.15.1 | Create 2-stage job: `process_raster_docker_http` | 📋 |
| S7.15.2 | Stage 1 handler: `validate_and_trigger_docker` | 📋 |
| S7.15.3 | Docker endpoint: `POST /task/start` | 📋 |
| S7.15.4 | Docker background processing with CoreMachine | 📋 |
| S7.15.5 | Configuration switch: `DOCKER_ORCHESTRATION_MODE` | 📋 |
| S7.15.6 | Test both modes work | 📋 |

**Detailed Flow**:
```
STAGE 1 (Function App - raster-tasks queue):
┌─────────────────────────────────────────────────────────┐
│ handler_validate_and_trigger_docker(params):            │
│   1. validation = validate_raster(params)               │
│   2. response = http_post(docker_url + "/task/start",   │
│        {job_id, stage: 2, params: validated_params})    │
│   3. if response.status == 202:                         │
│        return {success: True}  # Stage 1 done           │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼ HTTP POST
STAGE 2 (Docker - CoreMachine):
┌─────────────────────────────────────────────────────────┐
│ POST /task/start:                                       │
│   1. Create Stage 2 task record in DB                   │
│   2. Build TaskQueueMessage from HTTP payload           │
│   3. Spawn: CoreMachine.process_task_message(msg)       │
│   4. Return 202 Accepted immediately                    │
│                                                         │
│ Background thread:                                      │
│   - CoreMachine handles EVERYTHING:                     │
│     - Execute handler                                   │
│     - Update task status                                │
│     - Check stage completion (fan-in)                   │
│     - Advance job / complete job                        │
│   - Same code path as Service Bus trigger               │
└─────────────────────────────────────────────────────────┘
```

**Configuration**:
```bash
# Option A: Docker polls Service Bus (default)
DOCKER_ORCHESTRATION_MODE=service_bus

# Option B: Function App HTTP-triggers Docker
DOCKER_ORCHESTRATION_MODE=http_trigger
DOCKER_WORKER_URL=https://rmhheavyapi-xxx.azurewebsites.net
```

**Failure Handling**: Same as Function App - retries exhausted = job failed.
No special watchdog needed beyond existing job timeout logic.

**When to Implement**:
- After F7.13 Option A is working
- If Service Bus auth in Docker proves problematic
- As configuration option, not replacement

### Docker Execution Model Terminology (12 JAN 2026)

**Two Models - Clear Naming**:

| Model | Name | Trigger | Job Suffix | Use Case |
|-------|------|---------|------------|----------|
| **A** | **Queue-Polled** | Docker polls Service Bus | `*_docker` | Heavy ETL, hours-long |
| **B** | **Function-Triggered** | FA HTTP → Docker | `*_triggered` | FA as gatekeeper |

**Job Type Naming Convention**:
```
# QUEUE-POLLED (Docker polls queue, single stage)
process_raster_docker      # F7.13 - current implementation
process_vector_docker      # Future

# FUNCTION-TRIGGERED (FA triggers Docker, two stages)
process_raster_triggered   # F7.15 - FA validates → Docker ETL
process_vector_triggered   # F7.15 - FA validates → Docker ETL
```

**Common Abstraction for Function-Triggered Jobs**:
- `DockerTriggeredJobMixin` - standard 2-stage structure
- Stage 1 handler: `trigger_docker_task` (FA validates + POSTs to Docker)
- Stage 2: Docker creates task, runs CoreMachine in background
- Docker endpoint: `POST /task/start` returns 202 Accepted

**When to Use Which**:
| Scenario | Model |
|----------|-------|
| Tasks running hours (large rasters) | Queue-Polled |
| FA validation before Docker starts | Function-Triggered |
| Simpler Docker (no Service Bus) | Function-Triggered |
| High-volume parallel tasks | Queue-Polled |

---

### 🟡 RasterMetadata Architecture (F7.9)

**Epic**: E7 Pipeline Infrastructure → E2 Raster Data as API
**Goal**: RasterMetadata model providing single source of truth for STAC-based raster catalogs
**Dependency**: F7.8 ✅ (BaseMetadata, VectorMetadata pattern established)
**Status**: Phase 1 Complete (09 JAN 2026) - Models, DDL, Repository
**Priority**: CRITICAL - Raster is primary STAC use case

#### F7.9: RasterMetadata Implementation

| Story | Description | Status |
|-------|-------------|--------|
| S7.9.1 | Create `RasterMetadata` class in `core/models/unified_metadata.py` | ✅ Done (09 JAN) |
| S7.9.2 | Create `app.cog_metadata` table DDL with typed columns | ✅ Done (09 JAN) |
| S7.9.3 | Create `RasterMetadataRepository` with CRUD operations | ✅ Done (09 JAN) |
| S7.9.4 | Implement `RasterMetadata.from_db_row()` factory method | ✅ Done (09 JAN) |
| S7.9.5 | Implement `RasterMetadata.to_stac_item()` conversion | ✅ Done (09 JAN) |
| S7.9.6 | Implement `RasterMetadata.to_stac_collection()` conversion | ✅ Done (09 JAN) |
| S7.9.7 | Refactor `service_stac_metadata.py` to use RasterMetadata | 📋 |
| S7.9.8 | Refactor `stac_catalog.py` to use RasterMetadata | 📋 |
| S7.9.9 | Wire raster ingest to populate app.cog_metadata | 📋 |
| S7.9.10 | Wire raster STAC handlers to upsert app.dataset_refs | 📋 |
| S7.9.11 | Update `fathom_stac_register` to use RasterMetadata | 📋 |
| S7.9.12 | Update `fathom_stac_rebuild` to use RasterMetadata | 📋 |

**Phase 1 Complete (09 JAN 2026)**:
- `RasterMetadata` class added to `core/models/unified_metadata.py`
- `CogMetadataRecord` model in `core/models/raster_metadata.py` for DDL
- DDL added to `sql_generator.py` (table + 5 indexes)
- `RasterMetadataRepository` in `infrastructure/raster_metadata_repository.py`
- Implements: from_db_row, to_stac_item, to_stac_collection

**Key Files**:
- `core/models/unified_metadata.py` - RasterMetadata domain model
- `core/models/raster_metadata.py` - CogMetadataRecord for DDL
- `core/schema/sql_generator.py` - Table/index generation
- `infrastructure/raster_metadata_repository.py` - CRUD operations

**RasterMetadata Fields** (beyond BaseMetadata):
```python
class RasterMetadata(BaseMetadata):
    # COG-specific fields
    cog_url: str                    # /vsiaz/ path or HTTPS URL
    container: str                  # Azure container name
    blob_path: str                  # Path within container

    # Raster properties
    width: int                      # Pixel width
    height: int                     # Pixel height
    band_count: int                 # Number of bands
    dtype: str                      # numpy dtype (uint8, int16, float32, etc.)
    nodata: Optional[float]         # NoData value
    crs: str                        # CRS as EPSG code or WKT
    transform: List[float]          # Affine transform (6 values)
    resolution: Tuple[float, float] # (x_res, y_res) in CRS units

    # Band metadata
    band_names: List[str]           # Band descriptions
    band_units: Optional[List[str]] # Units per band

    # Processing metadata
    is_cog: bool                    # Cloud-optimized GeoTIFF?
    overview_levels: List[int]      # COG overview levels
    compression: Optional[str]      # DEFLATE, LZW, etc.
    blocksize: Tuple[int, int]      # Internal tile size

    # Visualization defaults
    colormap: Optional[str]         # Default colormap name
    rescale_range: Optional[Tuple[float, float]]  # Default min/max

    # STAC extensions
    eo_bands: Optional[List[dict]]  # EO extension band metadata
    raster_bands: Optional[List[dict]]  # Raster extension metadata
```

**app.cog_metadata Table** (in existing app schema):
```sql
CREATE TABLE app.cog_metadata (
    -- Identity
    cog_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id TEXT NOT NULL,
    item_id TEXT NOT NULL UNIQUE,

    -- Location
    container TEXT NOT NULL,
    blob_path TEXT NOT NULL,
    cog_url TEXT NOT NULL,

    -- Spatial
    bbox DOUBLE PRECISION[4],
    geometry GEOMETRY(Polygon, 4326),
    crs TEXT NOT NULL DEFAULT 'EPSG:4326',

    -- Raster properties
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    band_count INTEGER NOT NULL,
    dtype TEXT NOT NULL,
    nodata DOUBLE PRECISION,
    resolution DOUBLE PRECISION[2],

    -- COG properties
    is_cog BOOLEAN DEFAULT true,
    compression TEXT,
    blocksize INTEGER[2],
    overview_levels INTEGER[],

    -- Metadata
    title TEXT,
    description TEXT,
    datetime TIMESTAMPTZ,
    start_datetime TIMESTAMPTZ,
    end_datetime TIMESTAMPTZ,

    -- Band metadata (JSONB for flexibility)
    band_names TEXT[],
    eo_bands JSONB,
    raster_bands JSONB,

    -- Visualization
    colormap TEXT,
    rescale_min DOUBLE PRECISION,
    rescale_max DOUBLE PRECISION,

    -- Extensibility
    providers JSONB,
    custom_properties JSONB,

    -- STAC linkage
    stac_item_id TEXT,
    stac_collection_id TEXT,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(container, blob_path)
);

-- Indexes
CREATE INDEX idx_cog_metadata_collection ON app.cog_metadata(collection_id);
CREATE INDEX idx_cog_metadata_bbox ON app.cog_metadata USING GIST(geometry);
CREATE INDEX idx_cog_metadata_datetime ON app.cog_metadata(datetime);
```

**Why Critical**:
1. STAC is primarily a raster catalog standard
2. Current raster STAC items built ad-hoc without metadata registry
3. FATHOM, DEM, satellite imagery all need consistent metadata
4. TiTiler integration requires predictable metadata structure
5. DDH linkage for rasters depends on this

**Current Gap**:
- VectorMetadata has `geo.table_metadata` as source of truth
- Raster has NO equivalent — STAC items built directly from COG headers
- No way to query "all rasters for DDH dataset X"
- No consistent visualization defaults stored

---

### 🚧 F7.11: STAC Catalog Self-Healing

**Epic**: E7 Pipeline Infrastructure
**Goal**: Job-based remediation for metadata consistency issues detected by F7.10
**Status**: 🚧 IN PROGRESS (vectors working, raster pending)
**Implemented**: 10 JAN 2026

#### Background

F7.10 Metadata Consistency timer runs every 6 hours and detects:
- Broken backlinks (table_metadata.stac_item_id → non-existent STAC item)
- Orphaned STAC items (no corresponding metadata record)
- Missing blob references

The timer *detects* issues but cannot *fix* them (would timeout on large repairs).
F7.11 provides a dedicated `rebuild_stac` job to remediate these issues.

#### Stories

| Story | Status | Description |
|-------|--------|-------------|
| S7.11.1 | ✅ Done | Create `jobs/rebuild_stac.py` - 2-stage job definition |
| S7.11.2 | ✅ Done | Create `services/rebuild_stac_handlers.py` - validate + rebuild handlers |
| S7.11.3 | ✅ Done | Register job and handlers in `__init__.py` files |
| S7.11.4 | ✅ Done | Add `force_recreate` mode (delete existing STAC before rebuild) |
| S7.11.5 | 📋 | Add raster support (rebuild from app.cog_metadata) |
| S7.11.6 | 📋 | Timer auto-submit (F7.10 detects → auto-submit rebuild job) |

#### Usage

```bash
# Rebuild STAC for specific vector tables
POST /api/jobs/submit/rebuild_stac
{
    "data_type": "vector",
    "items": ["curated_admin0", "system_ibat_kba"],
    "schema": "geo",
    "dry_run": false
}

# With force_recreate (deletes existing STAC item first)
POST /api/jobs/submit/rebuild_stac
{
    "data_type": "vector",
    "items": ["curated_admin0"],
    "schema": "geo",
    "dry_run": false,
    "force_recreate": true
}
```

#### Key Files

- `jobs/rebuild_stac.py` - RebuildStacJob class (227 lines)
- `services/rebuild_stac_handlers.py` - stac_rebuild_validate, stac_rebuild_item (367 lines)

#### Remaining Work

**S7.11.5 - Raster Support**:
- Currently returns "Raster rebuild not yet implemented"
- Needs to query `app.cog_metadata` for COG info
- Call existing `extract_stac_metadata` handler
- Depends on F7.9 (RasterMetadata) being complete

**S7.11.6 - Timer Auto-Submit**:
- Modify F7.10 timer to submit rebuild_stac job when issues detected
- Add threshold (only submit if >0 issues found)
- Add cooldown (don't re-submit if job already running)

---

## Other Active Work

### F7.16: Code Maintenance - db_maintenance.py Split

**Added**: 12 JAN 2026
**Completed**: 12 JAN 2026
**Status**: ✅ PHASE 1 COMPLETE
**Goal**: Split 2,673-line monolithic file into focused modules

| Story | Description | Status |
|-------|-------------|--------|
| S7.16.1 | Create `schema_operations.py` (~1,400 lines) | ⏳ Future |
| S7.16.2 | Create `data_cleanup.py` (~195 lines) | ✅ |
| S7.16.3 | Create `geo_table_operations.py` (~578 lines) | ✅ |
| S7.16.4 | Refactor `db_maintenance.py` to use delegates | ✅ |
| S7.16.5 | Update imports and verify no regressions | ✅ |

**Results**:
- `db_maintenance.py`: 2,673 → 1,922 lines (28% reduction)
- Extracted `data_cleanup.py`: 195 lines (cleanup + prerequisites)
- Extracted `geo_table_operations.py`: 578 lines (geo table management)
- Schema operations remain in db_maintenance.py (future extraction)

**Current Structure**:
```
triggers/admin/
├── db_maintenance.py          # Router + schema ops (1,922 lines)
├── data_cleanup.py            # Record cleanup (195 lines) NEW
└── geo_table_operations.py    # Geo table mgmt (578 lines) NEW
```

---

### F7.17: Additional Features (12 JAN 2026)

**Status**: ✅ COMPLETE
**Version**: 0.7.7.11

| Feature | Description | Status |
|---------|-------------|--------|
| Job Resubmit Endpoint | `POST /api/jobs/{job_id}/resubmit` - nuclear reset + resubmit | ✅ |
| Platform processing_mode | Route Platform raster to Docker via `processing_mode=docker` | ✅ |
| Platform Default to Docker | Auto-route to Docker when `docker_worker_enabled=true` (21 JAN) | ✅ |
| Endpoint Consolidation | Removed `/platform/raster`, `/platform/raster-collection` - use `/platform/submit` (21 JAN) | ✅ |
| Env Validation Warnings | Separate errors from warnings (don't block Service Bus) | ✅ |
| PgStacRepository.delete_item | Delete STAC items for job resubmit cleanup | ✅ |
| JobRepository.delete_job | Delete job records for resubmit | ✅ |

**Job Resubmit Details** (`triggers/jobs/resubmit.py`):
- Dry run mode: preview cleanup without executing
- Cleanup: tasks, job record, PostGIS tables, STAC items
- Optionally delete blob artifacts (COGs)
- Force mode: resubmit even if job is processing

---

### E9: Large Data Hosting

| Feature | Description | Status |
|---------|-------------|--------|
| F9.1: FATHOM ETL | Band stacking + spatial merge | 🚧 Rwanda focus |
| F9.5: xarray Service | Time-series endpoints | ✅ Complete |
| F9.6: TiTiler Services | COG + Zarr tile serving | 🚧 TiTiler-xarray deployed 04 JAN |
| F9.8: Pre-prepared Ingest | COG copy + STAC from params | 📋 After Rwanda |

### E8: GeoAnalytics Pipeline

| Feature | Description | Status |
|---------|-------------|--------|
| F8.1-F8.3 | Grid infrastructure, bootstrap, raster aggregation | ✅ Complete |
| F8.8 | Source Catalog | ✅ Complete |
| F8.9 | H3 Export Pipeline | ✅ Complete |
| F8.13 | **Rwanda H3 Aggregation** | 📋 Priority 2 |
| F8.7 | **Building Exposure Pipeline** | 📋 Priority 3 |
| F8.4 | Vector→H3 Aggregation | 📋 After buildings |
| F8.5-F8.6 | GeoParquet, Analytics API | 📋 After Rwanda |

### E2: Raster Data as API

| Story | Description | Status |
|-------|-------------|--------|
| S2.2.5 | Fix TiTiler URLs for >3 band rasters | ✅ Complete (stac_metadata_helper.py bidx handling) |
| S2.2.6 | Auto-rescale DEM TiTiler URLs | ✅ Complete (04 JAN 2026, smart dtype defaults) |
| F2.9 | STAC-Integrated Raster Viewer | ✅ Complete (30 DEC 2025) |

### E3: DDH Platform Integration

| Feature | Description | Status |
|---------|-------------|--------|
| F3.1 | API Docs (Swagger UI) | ✅ Deployed |
| F3.2 | Identity (DDH service principal) | 📋 |
| F3.3 | Environments (QA/UAT/Prod) | 📋 |

### E12: Interface Modernization

| Feature | Description | Status |
|---------|-------------|--------|
| F12.1-F12.3 | Cleanup, HTMX, Migration | ✅ Complete |
| F12.3.1 | DRY Consolidation (CSS/JS dedup) | ✅ Complete (09 JAN 2026) |
| SP12.9 | NiceGUI Evaluation Spike | ✅ Complete - **Not Pursuing** |
| F12.EN1 | Helper Enhancements | 📋 Planned |
| F12.4 | System Dashboard | 📋 Planned |
| F12.5 | Pipeline Workflow Hub | 📋 Planned |
| F12.6 | STAC & Raster Browser | 📋 Planned |
| F12.7 | OGC Features Browser | 📋 Planned |
| F12.8 | API Documentation Hub | 📋 Planned |

**SP12.9 Decision (09 JAN 2026)**: Evaluated NiceGUI and decided to stay with current HTMX + hardcoded JS/HTML/CSS approach. Rationale:
- NiceGUI requires persistent WebSocket connections → incompatible with Azure Functions
- Would require separate Docker deployment (Container Apps)
- Current approach is working well, simpler architecture, no additional infrastructure needed

---

## E4: Classification Enforcement & ADF Integration

**Added**: 07 JAN 2026
**Epic**: E4 Security Zones / Externalization
**Goal**: Make `access_level` (OUO/Public/Restricted) mandatory and prepare for ADF integration
**Context**: Colleague configuring ADF; we need Python side ready with correct parameters

### Background

Data classification (`access_level`) controls where data can be exported:
- **PUBLIC**: Can be copied to external-facing storage (ADF will handle this)
- **OUO** (Official Use Only): Internal only, ADF should reject export requests
- **RESTRICTED**: Highest restriction, no external access

Currently `access_level` is inconsistently enforced across the codebase. This work makes it:
1. **Mandatory** at Platform API entry point
2. **Type-safe** using `AccessLevel` enum throughout
3. **Fail-fast** in pipeline tasks if somehow missing

### Current State Analysis (07 JAN 2026)

| Location | Type | Default | Required | Issue |
|----------|------|---------|----------|-------|
| `PlatformRequest` | `str` | `"OUO"` | ✅ | Not using enum |
| `AccessLevel` enum | `Enum` | N/A | N/A | Exists but unused |
| Job parameter schemas | `str` | `None` | ❌ | Loses value |
| `PlatformMetadata` dataclass | `Optional[str]` | `None` | ❌ | Loses value |
| `PlatformProperties` model | `Optional[AccessLevel]` | `None` | ❌ | Uses enum but optional |

**Key Files**:
- `core/models/stac.py:57-62` - `AccessLevel` enum definition
- `core/models/platform.py:147-151` - `PlatformRequest.access_level` field
- `triggers/trigger_platform.py` - Translation functions
- `jobs/process_raster_v2.py:92` - Job parameter schema
- `jobs/raster_mixin.py:93-98` - `PLATFORM_PASSTHROUGH_SCHEMA`
- `services/stac_metadata_helper.py:69` - `PlatformMetadata` dataclass
- `infrastructure/data_factory.py` - ADF repository (ready for testing)

### Phase 1: Enforce at Platform Level

**Goal**: Reject requests with invalid/missing classification at API entry point

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.1 | Update `PlatformRequest.access_level` to use `AccessLevel` enum | 📋 | `core/models/platform.py` |
| S4.CL.2 | Add Pydantic validator to normalize case (accept "OUO" → store as "ouo") | 📋 | `core/models/platform.py` |
| S4.CL.3 | Make `access_level` required (remove default) OR keep secure default "ouo" | 📋 | `core/models/platform.py` |
| S4.CL.4 | Update `_translate_to_coremachine()` to pass enum value (lowercase string) | 📋 | `triggers/trigger_platform.py` |
| S4.CL.5 | Add validation tests for Platform API rejection of invalid values | 📋 | `tests/` |

**Implementation Notes for S4.CL.1-3**:
```python
# core/models/platform.py - Change from:
access_level: str = Field(default="OUO", max_length=50, ...)

# To:
from core.models.stac import AccessLevel

access_level: AccessLevel = Field(
    default=AccessLevel.OUO,
    description="Data classification: public, ouo, restricted"
)

@field_validator('access_level', mode='before')
@classmethod
def normalize_access_level(cls, v):
    """Accept case-insensitive input, normalize to enum."""
    if isinstance(v, str):
        try:
            return AccessLevel(v.lower())
        except ValueError:
            raise ValueError(f"Invalid access_level '{v}'. Must be: public, ouo, restricted")
    return v
```

**Decision Point**: Keep `default=AccessLevel.OUO` (secure by default) or make truly required (no default). Recommend keeping default since OUO is the safe choice.

### Phase 2: Fail-Fast in Pipeline Tasks

**Goal**: Defense-in-depth - tasks fail immediately if access_level missing (shouldn't happen if Phase 1 works)

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.CL.6 | Add `access_level` to job schemas with `required: True` | 📋 | `jobs/raster_mixin.py`, `jobs/process_raster_v2.py`, `jobs/process_vector.py` |
| S4.CL.7 | Add validation in STAC metadata creation (fail if missing) | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.8 | Add validation in promote handlers (data export tasks) | 📋 | `services/promote_service.py` |
| S4.CL.9 | Update `PlatformMetadata` dataclass to require access_level | 📋 | `services/stac_metadata_helper.py` |
| S4.CL.10 | Add checkpoints logging for access_level at key stages | 📋 | Various handlers |

**Implementation Notes for S4.CL.6**:
```python
# jobs/raster_mixin.py - Update PLATFORM_PASSTHROUGH_SCHEMA:
PLATFORM_PASSTHROUGH_SCHEMA = {
    'dataset_id': {'type': 'str', 'default': None},
    'resource_id': {'type': 'str', 'default': None},
    'version_id': {'type': 'str', 'default': None},
    'access_level': {
        'type': 'str',
        'required': True,  # Now required!
        'allowed': ['public', 'ouo', 'restricted']
    },
}
```

**Implementation Notes for S4.CL.7**:
```python
# services/stac_metadata_helper.py - Add validation in augment_item():
def augment_item(self, item_dict, ..., platform: Optional[PlatformMetadata] = None, ...):
    # Fail fast if platform metadata provided but access_level missing
    if platform and not platform.access_level:
        raise ValueError(
            "access_level is required for STAC item creation. "
            "This is a pipeline bug - access_level should be set at Platform API."
        )
```

### Phase 3: ADF Integration Testing

**Goal**: Verify Python can call ADF and pass classification parameter

| Story | Description | Status | Files |
|-------|-------------|--------|-------|
| S4.ADF.1 | Create `/api/admin/adf/health` endpoint exposing health_check() | 📋 | `triggers/admin/` |
| S4.ADF.2 | Create `/api/admin/adf/pipelines` endpoint listing available pipelines | 📋 | `triggers/admin/` |
| S4.ADF.3 | Verify ADF env vars are set (`ADF_SUBSCRIPTION_ID`, `ADF_FACTORY_NAME`) | 📋 | Azure portal |
| S4.ADF.4 | Test trigger_pipeline() with simple test pipeline (colleague creates) | 📋 | Manual test |
| S4.ADF.5 | Add access_level to ADF pipeline parameters when triggering | 📋 | Future promote job |

**ADF Test Endpoint Implementation (S4.ADF.1-2)**:
```python
# triggers/admin/adf.py (new file)
from infrastructure.data_factory import get_data_factory_repository

def adf_health(req: func.HttpRequest) -> func.HttpResponse:
    """GET /api/admin/adf/health - Test ADF connectivity."""
    try:
        adf_repo = get_data_factory_repository()
        result = adf_repo.health_check()
        return func.HttpResponse(json.dumps(result), status_code=200, ...)
    except Exception as e:
        return func.HttpResponse(json.dumps({
            "status": "error",
            "error": str(e),
            "hint": "Check ADF_SUBSCRIPTION_ID, ADF_RESOURCE_GROUP, ADF_FACTORY_NAME env vars"
        }), status_code=500, ...)
```

### Testing Checklist

After implementation, verify:

- [ ] `POST /api/platform/submit` with `access_level: "INVALID"` returns 400
- [ ] `POST /api/platform/submit` with `access_level: "OUO"` (uppercase) succeeds
- [ ] `POST /api/platform/submit` with `access_level: "ouo"` (lowercase) succeeds
- [ ] `POST /api/platform/submit` without `access_level` uses default "ouo"
- [ ] STAC items have `platform:access_level` property populated
- [ ] Job parameters include `access_level` in task parameters
- [ ] `GET /api/admin/adf/health` returns ADF status (Phase 3)

### Acceptance Criteria

**Phase 1 Complete When**:
- Platform API validates and normalizes access_level on entry
- Invalid values rejected with clear error message
- Existing Platform API tests pass

**Phase 2 Complete When**:
- Pipeline tasks fail fast if access_level missing
- All STAC items have access_level in metadata
- Checkpoints logged at key stages

**Phase 3 Complete When**:
- ADF health endpoint working
- Can list pipelines from Python
- Ready to trigger actual export pipeline (pending ADF build)

---

## Reference Data Pipelines (Low Priority)

**Epic**: E7 Pipeline Infrastructure
**Goal**: Automated updates of reference datasets for spatial analysis
**Infrastructure**: Curated Datasets System (F7.1 ✅) - timer scheduler, 4-stage job, registry

### F7.2: IBAT Reference Data (Quarterly)

**Documentation**: [IBAT.md](/IBAT.md)
**Data Source**: IBAT Alliance API
**Auth**: `IBAT_AUTH_KEY` + `IBAT_AUTH_TOKEN`

| Story | Description | Status |
|-------|-------------|--------|
| S7.2.1 | IBAT base handler (shared auth) | ✅ Done |
| S7.2.2 | WDPA handler (protected areas, ~250K polygons) | ✅ Done |
| S7.2.3 | KBAs handler (Key Biodiversity Areas, ~16K polygons) | 📋 |
| S7.2.4 | Style integration (IUCN categories) | 📋 |
| S7.2.5 | Manual trigger endpoint | 📋 |

**Target Tables**: `geo.curated_wdpa_protected_areas`, `geo.curated_kbas`

### F7.6: ACLED Conflict Data (Twice Weekly)

**Documentation**: [ACLED.md](/ACLED.md)
**Data Source**: ACLED API
**Auth**: `ACLED_API_KEY` + `ACLED_EMAIL`
**Update Strategy**: `upsert` (incremental by event_id)

| Story | Description | Status |
|-------|-------------|--------|
| S7.6.1 | ACLED handler (API auth, pagination) | 📋 |
| S7.6.2 | Event data ETL (point geometry, conflict categories) | 📋 |
| S7.6.3 | Incremental updates (upsert vs full replace) | 📋 |
| S7.6.4 | Schedule config (Monday/Thursday timer) | 📋 |
| S7.6.5 | Style integration (conflict type symbology) | 📋 |

**Target Table**: `geo.curated_acled_events`

### F7.7: Static Reference Data (Manual)

| Story | Description | Status |
|-------|-------------|--------|
| S7.7.1 | Admin0 handler (Natural Earth countries) | 📋 |
| S7.7.2 | Admin1 handler (states/provinces) | 📋 |

**Target Tables**: `geo.curated_admin0`, `geo.curated_admin1`

---

## DevOps / Non-Geospatial Tasks

Tasks suitable for a colleague with Azure/Python/pipeline expertise but without geospatial domain knowledge.

### Ready Now (No Geospatial Knowledge Required)

| Task | Epic | Description | Skills Needed |
|------|------|-------------|---------------|
| S9.2.2 | E9 | Create DDH service principal | Azure AD, IAM |
| S9.2.3 | E9 | Grant blob read access | Azure RBAC |
| EN6.1 | EN6 | Docker image with GDAL/rasterio | Docker, Python |
| EN6.2 | EN6 | Container deployment | Azure, DevOps |
| F7.2.1 | E7 | Create ADF instance | Azure Data Factory |

---

## Recently Completed

| Date | Item | Epic |
|------|------|------|
| 21 JAN 2026 | **F7.12.F Docker AAD Auth Fix** - Docker worker App Insights AAD auth + RBAC role assignment | E7 |
| 21 JAN 2026 | **Docker Logging Health Check** - `/test/logging` and `/test/logging/verify` endpoints | E7 |
| 21 JAN 2026 | **Platform Routing Default** - Platform raster jobs now default to Docker when enabled | E7 |
| 21 JAN 2026 | **Endpoint Consolidation** - Removed redundant `/platform/raster`, `/platform/raster-collection` | E7 |
| 12 JAN 2026 | **F7.17 Job Resubmit + Features** - `/api/jobs/{job_id}/resubmit` endpoint, env validation fix | E7 |
| 12 JAN 2026 | **F7.16 db_maintenance.py Split** - Phase 1 complete (28% reduction, 2 modules extracted) | E7 |
| 11 JAN 2026 | **F7.12 Docker OpenTelemetry** - Docker worker logs to App Insights (v0.7.8-otel) | E7 |
| 11 JAN 2026 | **F7.12 Docker Worker Infrastructure** - Deployed to rmhheavyapi | E7 |
| 10 JAN 2026 | **F7.12 Logging Architecture** - Flag consolidation, global log context | E7 |
| 09 JAN 2026 | **F7.8 Unified Metadata Architecture** - VectorMetadata pattern (→ HISTORY.md) | E7 |
| 09 JAN 2026 | **F12.5 DRY Consolidation** - CSS/JS deduplication (→ HISTORY.md) | E12 |
| 08 JAN 2026 | pg_cron + autovacuum for H3 VACUUM | E8 |
| 07 JAN 2026 | **F9.1 FATHOM Rwanda Pipeline COMPLETE** (→ HISTORY.md) | E9 |
| 06 JAN 2026 | **System Diagnostics & Drift Detection** (→ HISTORY.md) | — |
| 05 JAN 2026 | **Thread-safety fix for BlobRepository** (→ HISTORY.md) | — |

*For full details on items marked (→ HISTORY.md), see [HISTORY.md](./HISTORY.md)*

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |
| [H3_REVIEW.md](./H3_REVIEW.md) | H3 aggregation implementation |
| [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) | pg_cron + autovacuum setup |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |

---

**Workflow**:
1. ~~Complete Rwanda FATHOM pipeline (Priority 1)~~ ✅ DONE
2. Run H3 aggregation on FATHOM outputs (Priority 2) - 🚧 H3 bootstrap running
3. Building flood exposure pipeline: MS Buildings → FATHOM sample → H3 aggregation (Priority 3)
4. Generalize to Pipeline Builder (Future)
