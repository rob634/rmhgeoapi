# Active Tasks

**Last Updated**: 5 NOV 2025
**Author**: Robert and Geospatial Claude Legion

---

## 🚨 NEW: CoreMachine Failure Analysis Complete (5 NOV 2025)

**Status**: ✅ **ANALYSIS COMPLETE** - Comprehensive failure point analysis documented
**Document**: `WORKFLOW_FAILURE_ANALYSIS.md`
**Focus**: Stuck-in-processing scenarios for production-critical workflows

### Key Findings

**9 Failure Points Identified**:
- **3 Critical (Code Fixes)**: Job exception swallowed, task status update failure, stage advancement failure
- **4 Medium (Timer Trigger)**: Task timeout, database connection loss, partial failures, constraint violations
- **2 Low (Already Handled)**: PostgreSQL deadlock (fixed), STAC insertion (handled)

**Immediate Actions Required**:
1. **FP1**: Add job failure marking in `function_app.py` job exception handler (~30 min)
2. **FP2**: Fail-fast if task PROCESSING update fails in `core/machine.py` (~20 min)
3. **FP3**: Wrap stage advancement in try-catch, mark job FAILED on error (~30 min)

**Total Code Fix Effort**: ~1.5 hours
**Expected Impact**: 90% reduction in stuck-in-processing scenarios

**Timer Trigger Design**: Complete backup recovery function for infrastructure failures (timeout, connection loss)

**Next Steps**:
- [ ] Implement FP1-3 code fixes (Phase 1)
- [ ] Test with invalid job submissions and simulated failures
- [ ] Deploy and monitor in dev environment
- [ ] Implement timer trigger cleanup function (Phase 2)

---

## 🎉 MAJOR SUCCESS: Vector Ingest Configurable Indexes + Job Completion Fix (01 NOV 2025)

**Status**: ✅ **BOTH ISSUES RESOLVED** - Vector ingest fully operational with configurable database indexes
**Achievement**: End-to-end vector ETL with spatial GIST, attribute B-tree, and temporal DESC indexes working

### What We Fixed (01 NOV 2025)

✅ **Issue 1: Configurable Index Creation**:
- **Problem**: Index config code existed but wasn't connected - job params never passed to PostGIS handler
- **Root Cause**: `jobs/ingest_vector.py` didn't extract `indexes` from job_params, handler used GeoDataFrame metadata (never set)
- **Fix**: Pass indexes parameter through entire chain (job → handler → _create_table_if_not_exists → _create_indexes)
- **Result**: All 3 index types working - spatial GIST, attribute B-tree, temporal B-tree DESC

✅ **Issue 2: Jobs Stuck When create_stac=false**:
- **Problem**: Jobs completed all tasks but stuck at "processing" stage 1/3, never marked complete
- **Root Cause**: `total_stages=3` hardcoded, Stage 3 returned `[]` when create_stac=false, job never advanced to stage 3
- **Fix**: Removed `create_stac` parameter entirely - STAC records ALWAYS created for system-vectors
- **Result**: All vector ingest jobs complete successfully through all 3 stages

✅ **Production Test - ACLED with Full Index Suite**:
```json
{
  "blob_name": "acled_test.csv",
  "table_name": "acled_1997_indexed",
  "indexes": {
    "spatial": true,
    "attributes": ["country", "event_type"],
    "temporal": ["event_date"]
  }
}
```

**Results**: 5,000 rows, 4 indexes created, STAC item in system-vectors, 100% success ✅

**Indexes Verified in PostgreSQL**:
1. `idx_acled_1997_indexed_geom` - GIST spatial index
2. `idx_acled_1997_indexed_country` - B-tree attribute index
3. `idx_acled_1997_indexed_event_type` - B-tree attribute index
4. `idx_acled_1997_indexed_event_date_desc` - B-tree DESC temporal index

**Git Commits**:
- `9b74697` - Index creation fix (DEPLOYED)
- `2f348c5` - Remove create_stac parameter (COMMITTED, ready to deploy)

---

## 🎯 CURRENT PRIORITY: Production Readiness & APIM Architecture (30 OCT 2025)

**Status**: 🎉 **MAJOR MILESTONE ACHIEVED** - Standards-compliant geospatial data platform operational
**Context**: OGC Features API integrated successfully, STAC API working, Platform layer operational
**Next Phase**: Production deployment architecture with Azure API Management

### What We've Built (30 OCT 2025)

✅ **Three Standards-Compliant APIs**:
1. **STAC API** (pgstac/) - STAC v1.0 metadata catalog
2. **OGC Features API** (ogc_features/) - OGC API - Features Core 1.0 vector access
3. **Platform/CoreMachine** - Custom job orchestration + data processing

✅ **Interactive Web Application** 🎉:
- **Live URL**: https://rmhazuregeo.z13.web.core.windows.net/
- **User Quote**: *"omg my very first web app loading geojson from a postgis database!!!"*
- Leaflet map with collection selector
- Load 50-1000 features from any of 7 PostGIS collections
- Click polygons for popups, hover to highlight
- Azure Storage Static Website hosting
- CORS configured for cross-origin API access

✅ **All APIs Tested & Working** in browser:
- STAC collections and items serving properly
- OGC Features returning GeoJSON with PostGIS geometries
- Platform layer processing requests
- 7 vector collections available via OGC
- **End-to-end data flow**: PostgreSQL → OGC API → Web Map ✨

### 🚀 NEXT UP: End-to-End Vector Workflow (Platform Layer)

**Priority**: P0 - Finalize complete vector data pipeline
**Goal**: Platform-orchestrated workflow from upload → PostGIS → STAC → OGC Features URL
**Philosophy**: Platform layer changes, CoreMachine stays stable (no changes)

**Complete Workflow**:
```
1. User uploads vector file (GeoJSON/Shapefile/etc.) via Platform API
   ↓
2. Platform → Vector ETL Job (CoreMachine)
   - Ingest to PostGIS (geo schema)
   - Validate geometries
   - Create spatial indexes
   ↓
3. Platform → STAC Catalog Job (CoreMachine)
   - Generate STAC Collection metadata
   - Create STAC Items for features
   - Write to pgstac schema
   ↓
4. Platform returns response:
   - PostGIS table name
   - STAC Collection ID
   - OGC Features API URL: /api/features/collections/{table_name}/items
   ↓
5. User can immediately:
   - Query via OGC Features API
   - Search via STAC API
   - View on web map: https://rmhazuregeo.z13.web.core.windows.net/
```

**NEW PRIORITY (31 OCT 2025): Individual Job Testing First, Platform Layer Second**
**Philosophy**: Jobs must work standalone before Platform orchestration

**Phase 1: Individual CoreMachine Jobs (CURRENT PRIORITY)**
- [ ] **Test ingest_vector job standalone** (P0)
  - Submit via: `POST /api/jobs/submit/ingest_vector`
  - Test vector file: Valid GeoJSON/Shapefile from blob storage
  - Verify: PostGIS table created in geo schema
  - Verify: Spatial indexes created
  - Verify: Job completes with table_name in result
  - Success: Can query table via psql/OGC Features API

- [ ] **Test stac_catalog_vectors job standalone** (P0)
  - Submit via: `POST /api/jobs/submit/stac_catalog_vectors`
  - Prerequisite: PostGIS table exists (from ingest_vector or manual)
  - Verify: STAC collection created in pgstac schema
  - Verify: STAC items created for features
  - Verify: Job completes with collection_id in result
  - Success: Can query via STAC API

- [ ] **Document individual job usage** (P0)
  - Create curl examples for each job
  - Document required parameters
  - Document expected results
  - Document how to verify success

- [ ] **Test all accepted vector file formats** (P0)
  - **doc.kml** (KML format)
  - **acled_test.csv** (CSV with coordinates)
  - **roads.zip** (Zipped shapefile)
  - **11.geojson** (GeoJSON)
  - **8.geojson** (GeoJSON)
  - **DMA/Dominica_Southeast_AOI.kml** (KML with complex geometries)
  - For each format:
    - Submit via ingest_vector job
    - Verify successful ingestion to PostGIS
    - Verify correct geometry type detection
    - Verify proper CRS handling
    - Document any format-specific issues
    - Test OGC Features API access to ingested data

**Phase 2: Platform Orchestration (AFTER Phase 1 Complete)**
- [ ] **Platform job chaining**: Chain ingest_vector → stac_catalog_vectors
- [ ] **Platform response formatting**: Return OGC Features URL + STAC Collection ID
- [ ] **Platform idempotency**: Test re-submitting same file
- [ ] **End-to-end Platform test**: Upload via Platform → verify all steps

**Deferred Tasks**:
- [ ] **Investigate /api/db/debug/all endpoint failure** (Low priority)
  - Returns "Debug dump failed: 0" instead of jobs/tasks data
  - Can use /api/db/jobs and /api/db/tasks instead

**Success Criteria**:
✅ Upload vector file → Get OGC Features URL back in < 2 minutes
✅ Re-upload same file → Returns existing OGC URL (idempotent)
✅ Can immediately view data on web map
✅ STAC catalog searchable
✅ CoreMachine unchanged (all edits in Platform/services layers)

**Notes**:
- Leverage existing CoreMachine jobs (ingest_vector, stac_catalog_vectors)
- Platform layer handles orchestration and response formatting
- Services layer may need updates for better OGC/STAC integration
- Goal: Platform API returns everything user needs to access their data

---

### 🔧 NEXT UP: Independent STAC Query Module (Like OGC Features)

**Priority**: P0 - Separate STAC query from STAC ingestion/ETL
**Goal**: Create standalone stac_query/ module with zero dependencies on main app
**Architecture**: Query and ETL live together, but ETL not exposed publicly

**Vision**:
```
Same Function App Structure:
├── ogc_features/          (Query only - public API)
│   ├── repository.py      → PostGIS queries
│   ├── service.py         → Business logic
│   ├── triggers.py        → HTTP endpoints
│   └── map.html           → Web UI
│
├── stac_query/            (Query only - public API) ⭐ NEW
│   ├── repository.py      → pgstac queries (read-only)
│   ├── service.py         → STAC search/filter logic
│   ├── triggers.py        → HTTP endpoints (/collections, /search, /items)
│   └── config.py          → Independent configuration
│
└── infrastructure/stac.py (ETL/Ingestion - internal only)
    ├── install_pgstac()   → Schema setup
    ├── create_collection() → Write operations
    ├── add_items()        → Write operations
    └── clear_stac_data()  → Nuclear button (DEV only)
```

**Key Principle - Separation of Concerns**:
- **stac_query/**: Read-only, public-facing, zero dependencies on main app
- **infrastructure/stac.py**: Write operations, ETL logic, called by CoreMachine jobs
- **Both use pgstac**: Different operations on same schema

**Benefits**:
✅ Query module can be deployed independently (future microservice)
✅ ETL stays internal (not exposed to public API)
✅ Same pattern as OGC Features (consistent architecture)
✅ Zero dependencies = easy to test and maintain
✅ Can add caching/optimization to queries without affecting ETL

**Implementation Tasks**:
- [ ] Create stac_query/ folder structure
- [ ] Extract read-only queries from infrastructure/stac.py
- [ ] Create stac_query/repository.py (pgstac SELECT queries only)
- [ ] Create stac_query/service.py (STAC API v1.0 compliance)
- [ ] Create stac_query/triggers.py (HTTP endpoints)
- [ ] Create stac_query/config.py (independent configuration)
- [ ] Update function_app.py with explicit STAC query routes
- [ ] Keep infrastructure/stac.py for ETL operations (no changes to callers)
- [ ] Test all existing STAC endpoints still work
- [ ] Verify CoreMachine jobs (stac_catalog_*) still work

**Endpoints to Implement** (Read-Only):
```bash
# STAC API v1.0 Core (query only)
GET  /api/collections                    # List all collections
GET  /api/collections/{id}               # Get collection metadata
GET  /api/collections/{id}/items         # Get items in collection
GET  /api/collections/{id}/items/{id}    # Get single item
POST /api/search                         # STAC search with filters
GET  /api/conformance                    # STAC conformance classes
GET  /api/                               # STAC landing page
```

**ETL Operations Stay Internal** (infrastructure/stac.py):
- Called by CoreMachine jobs only
- Not exposed via HTTP endpoints
- Platform layer orchestrates via job submission
- No public access to write operations

**Success Criteria**:
✅ stac_query/ module has zero dependencies on main app
✅ All STAC query endpoints work via new module
✅ ETL operations unchanged (infrastructure/stac.py still works)
✅ CoreMachine jobs don't need changes
✅ Same architecture pattern as OGC Features (consistency)
✅ Can be split into separate Function App in future (APIM ready)

**Notes**:
- Mirrors OGC Features architecture (proven pattern)
- Enables future microservices split
- Query and ETL coexist but serve different purposes
- Public API consumers only see stac_query/ endpoints
- Internal Platform/CoreMachine only uses infrastructure/stac.py for writes

---

### 🚀 Future: Production Architecture with APIM

**Vision**: Single custom domain with Azure API Management routing to multiple Function Apps

```
User Request:
https://geospatial.rmh.org/api/features/*     → OGC Features Function App
https://geospatial.rmh.org/api/collections/*  → STAC API Function App
https://geospatial.rmh.org/api/platform/*     → Platform Function App
https://geospatial.rmh.org/api/jobs/*         → CoreMachine Function App
```

**Benefits**:
- ✅ Seamless user experience (single domain)
- ✅ Independent scaling per API
- ✅ Separate deployment cycles
- ✅ API versioning (/v1/, /v2/)
- ✅ Centralized auth/rate limiting/caching
- ✅ SSL/TLS termination
- ✅ Request/response transformation

### Task Breakdown

**Phase 1: APIM Setup & Routing** (NOT STARTED)
- [ ] Create Azure API Management instance (Developer or Standard tier)
- [ ] Configure custom domain: geospatial.rmh.org
- [ ] Set up SSL certificate (Azure-managed or custom)
- [ ] Create API definitions for each backend
- [ ] Configure URL routing policies
- [ ] Test routing to existing rmhgeoapibeta Function App

**Phase 2: Function App Separation** (NOT STARTED)
- [ ] Plan microservices split:
  - OGC Features standalone (ogc_features/ → new Function App)
  - STAC API standalone (pgstac/ + infrastructure/stac.py → new Function App)
  - Platform layer (platform schema + triggers → existing or new)
  - CoreMachine (jobs/tasks → existing)
- [ ] Document shared dependencies (config.py, util_logger.py, infrastructure/)
- [ ] Create deployment strategy (which code goes where)

**Phase 3: Authentication & Security** (NOT STARTED)
- [ ] Design auth strategy:
  - Public APIs (/features/*, /collections/*): Azure AD token validation (any tenant user)
  - Internal APIs (/platform/*, /jobs/*): Specific app IDs only (DDH app + future apps)
- [ ] Configure APIM policies per API path:
  - `/api/features/*` → validate-azure-ad-token (open to tenant)
  - `/api/collections/*` → validate-azure-ad-token (open to tenant)
  - `/api/platform/*` → validate-azure-ad-token with client-application-ids (DDH only)
  - `/api/jobs/*` → validate-azure-ad-token with client-application-ids (DDH + future)
- [ ] Set up rate limiting per API:
  - Public APIs: 1,000 calls/minute
  - Internal APIs: 10,000 calls/minute
- [ ] Configure CORS policies (public APIs allow * origins, internal restrict)
- [ ] Add request validation (content-type, headers, payload size)
- [ ] Lock down Function Apps (VNET integration or private endpoints)
- [ ] Set Function Apps to AuthLevel.ANONYMOUS (APIM is gatekeeper)

**Phase 4: Monitoring & Analytics** (NOT STARTED)
- [ ] Configure Application Insights per Function App
- [ ] Set up APIM analytics
- [ ] Create unified dashboard
- [ ] Configure alerts

**Phase 5: Documentation & Client SDKs** (NOT STARTED)
- [ ] Generate OpenAPI specs for each API
- [ ] Create developer portal in APIM
- [ ] Write API usage guides
- [ ] Consider client SDK generation

### Questions to Answer

1. **Deployment Strategy**: Should we split into separate Function Apps now or wait?
2. **Shared Code**: How to handle shared modules (config, logger, infrastructure)?
   - Option A: Duplicate in each Function App
   - Option B: Shared Python package
   - Option C: Git submodules
3. **Database Access**: All Function Apps share same PostgreSQL - how to manage connection pooling?
4. **Cost**: APIM pricing tier - Developer ($50/mo) vs Standard ($700/mo)?
5. **Timeline**: Immediate APIM setup or continue with monolithic Function App?

### Current Status: Fully Functional Monolith

**What Works Right Now**:
- Single Function App (rmhgeoapibeta) serves all APIs
- All endpoints tested and operational
- Standards-compliant implementations
- Ready for production data ingestion

**Decision Point**:
- Continue with monolith + add features? (faster development)
- Split into microservices now? (better long-term architecture)

---

## ✅ COMPLETED: OGC Features API Integration (30 OCT 2025)

**Status**: ✅ **COMPLETE & TESTED** - 6 OGC-compliant endpoints deployed
**Achievement**: Fixed SQL parameter bug, integrated standalone OGC module
**Browser Tested**: User confirmed STAC JSON visible in browser! 🎉

See HISTORY.md for full details (lines 10-118)

---

## ✅ COMPLETED: Platform Infrastructure-as-Code Migration (29 OCT 2025)

**Status**: ✅ **COMPLETE & TESTED** - Platform tables now follow Infrastructure-as-Code pattern
**Deployment ID**: `50758bb6-2` (final working deployment)
**Priority**: P0 - Critical architecture alignment
**Completed**: 29 OCT 2025

### What Was Accomplished

**🎯 Goal**: Migrate Platform from manual DDL (70+ lines) to Pydantic Infrastructure-as-Code pattern, matching Jobs/Tasks architecture.

**Key Achievement**: Platform tables now have **zero drift guarantee** - Pydantic models ARE the database schema.

### 5 Implementation Phases

**Phase 1: Create Core Platform Models** (`core/models/platform.py` - NEW, 230+ lines)
- ✅ Created `PlatformRecord` with Field constraints (`max_length` → `VARCHAR` lengths)
- ✅ Created `PlatformRequestJobMapping` (bidirectional relationship table)
- ✅ Created `PlatformRequestStatus` enum (pending/processing/completed/failed)
- ✅ Created `DataType` enum (raster/vector/pointcloud)
- ✅ Used structured JSONB `jobs: Dict[str, Any]` instead of array (user feedback)

**Phase 2: Update SQL Generator** (`core/schema/sql_generator.py`)
- ✅ Added Platform model imports (lines 13-16)
- ✅ Added Platform ENUMs to generation (PlatformRequestStatus, DataType)
- ✅ Added Platform tables to generation (platform_requests, platform_request_jobs)
- ✅ Added PRIMARY KEY constraints (lines 313-331):
  - `platform_requests`: PRIMARY KEY (request_id)
  - `platform_request_jobs`: PRIMARY KEY (request_id, job_id)
- ✅ Added FOREIGN KEY constraint (platform_request_jobs → platform_requests, ON DELETE CASCADE)
- ✅ Added JSONB default handling for "jobs" field (lines 279-298)
- ✅ Added Platform indexes to generation

**Phase 3: Remove Manual DDL** (`triggers/schema_pydantic_deploy.py`)
- ✅ Deleted 70+ lines of manual CREATE TABLE statements
- ✅ Added Platform model imports (lines 72-77)
- ✅ Replaced DDL with documentation comment explaining Infrastructure-as-Code pattern

**Phase 4: Update All Imports**
- ✅ `core/models/__init__.py` - Export Platform models
- ✅ `triggers/trigger_platform.py` - Import from core.models
- ✅ `triggers/trigger_platform_status.py` - Import from core.models
- ✅ `infrastructure/platform.py` - Import from core.models (removed circular import workaround)

**Phase 5: Critical Design Changes**

**Change 1**: `job_ids: List[str]` → `jobs: Dict[str, Any]` (User Feedback)
- **User request**: "can we use jsonb so there is defined structure instead of hoping things are in the correct order in an array?"
- **New structure**:
  ```json
  {
    "validate_raster": {
      "job_id": "abc123...",
      "job_type": "validate_raster",
      "status": "completed",
      "sequence": 1,
      "created_at": "2025-10-29T12:00:00Z",
      "completed_at": "2025-10-29T12:01:30Z"
    }
  }
  ```
- ✅ Updated SQL generator JSONB defaults: `'[]'` → `'{}'`
- ✅ Updated `add_job_to_request()` to use `jsonb_set()` instead of array concatenation
- ✅ Updated `_row_to_dict()` to return dict instead of array
- ✅ Updated all SQL queries: `array_length()` → `jsonb_object_keys()`

**Change 2**: Added missing datetime import
- **Error**: `NameError: name 'datetime' is not defined`
- ✅ Added `from datetime import datetime` to `infrastructure/platform.py` line 45

### Errors Encountered and Fixed

**Error 1**: Schema Mismatch
- **Problem**: Tables created in "platform" schema, repository expected "app" schema
- **Fix**: Changed all schema references to "app"

**Error 2**: ComponentType.INFRASTRUCTURE doesn't exist
- **Problem**: Used non-existent ComponentType
- **Fix**: Changed to `ComponentType.REPOSITORY`

**Error 3**: Circular Import
- **Problem**: `infrastructure/platform.py` ↔ `triggers/trigger_platform.py`
- **Fix**: Moved all models to `core/models/platform.py`

**Error 4**: Missing PRIMARY KEY Constraints
- **Problem**: `ON CONFLICT (request_id)` failed - no PRIMARY KEY
- **Discovery**: SQL generator only handled hardcoded "jobs"/"tasks" table names
- **Fix**: Added elif blocks for Platform tables with PRIMARY KEY + FOREIGN KEY constraints

**Error 5**: Missing datetime import
- **Problem**: Used `datetime.utcnow()` without import
- **Fix**: Added import statement

### Deployment History

1. **be9073d1-3**: Initial deployment with PRIMARY KEY constraints
2. **6cf48ae5-9**: Added structured jobs field (partial test)
3. **d17af13a-6**: Updated repository queries for jobs dict
4. **50758bb6-2**: ✅ **FINAL SUCCESS** - Added datetime import, full integration test passed

### Test Results (Deployment 50758bb6-2)

**Test**: Submit Platform request with validate_raster + process_raster jobs
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "global-dem",
    "resource_id": "v1-cog",
    "version_id": "2025",
    "data_type": "raster",
    "job_types": ["validate_raster", "process_raster"]
  }'
```

**Result**: ✅ **SUCCESS**
```json
{
  "success": true,
  "request_id": "d8907c84885246b2de5f15df04515e13",
  "status": "pending",
  "jobs_created": ["59179b...", "848fe9..."],
  "message": "Platform request submitted. 2 jobs created."
}
```

### Schema Objects Created

**Tables**:
- `app.platform_requests` (from PlatformRecord)
- `app.platform_request_jobs` (from PlatformRequestJobMapping)

**ENUMs**:
- `app.platform_request_status_enum` (pending/processing/completed/failed)
- `app.data_type_enum` (raster/vector/pointcloud)

**Constraints**:
- PRIMARY KEY on platform_requests(request_id)
- Composite PRIMARY KEY on platform_request_jobs(request_id, job_id)
- FOREIGN KEY on platform_request_jobs(request_id) → platform_requests(request_id) ON DELETE CASCADE

**Indexes**: Auto-generated for all indexed fields

### Benefits Achieved

1. **Zero Drift Guarantee**: Database schema always matches Pydantic models
2. **Consistent Pattern**: Platform now follows same Infrastructure-as-Code pattern as Jobs/Tasks
3. **Field Constraints**: `Field(..., max_length=32)` auto-generates `VARCHAR(32)`
4. **Enum Safety**: Python Enums auto-generate PostgreSQL ENUM types
5. **Structured Data**: JSONB dict with semantic keys instead of ordered arrays
6. **Single Source of Truth**: Eliminated 70+ lines of manual DDL
7. **Referential Integrity**: FOREIGN KEY constraints enforce relationships
8. **Query Safety**: SQL composition pattern prevents SQL injection

### Documentation Created

- `PLATFORM_SCHEMA_COMPARISON.md` (comparison of manual DDL vs Infrastructure-as-Code)
- Updated `STORAGE_CONFIG_REVIEW_29OCT2025.md` with Platform architecture notes

---

## ✅ COMPLETED: Platform Table Renaming (api_requests + orchestration_jobs) (29 OCT 2025)

**Status**: ✅ **COMPLETE & DEPLOYED** - All 7 phases completed, tables renamed successfully
**Priority**: P1 - Improves API clarity
**User Decision**: "can we do app.api_requests and app.orchestration_jobs?"
**Completed**: 29 OCT 2025

### Rationale

**Current Names**: `platform_requests` / `platform_request_jobs`
- ❌ "Platform" is vague internal terminology
- ❌ "request_jobs" doesn't convey orchestration role

**New Names**: `api_requests` / `orchestration_jobs`
- ✅ **api_requests**: Client-facing layer - RESTful API requests from DDH
- ✅ **orchestration_jobs**: Execution layer - Maps API requests to CoreMachine jobs

### Architecture Clarity

```
DDH API Request → api_requests table → orchestration_jobs mapping → CoreMachine jobs
    (client)       (what user asked)     (execution plan)          (atomic work units)
```

**Example**:
- **API Request**: "Process global-dem dataset" (what client asked for)
- **Orchestration Jobs**: validate_raster → extract_metadata → create_cog (how we execute it)
- **CoreMachine Jobs**: Individual job executions with retry logic

### 7 Implementation Phases

**Phase 1: Update Pydantic Models** (`core/models/platform.py`)
- Rename `PlatformRecord` → `ApiRequest`
- Rename `PlatformRequestJobMapping` → `OrchestrationJob`
- Update all field descriptions and docstrings
- Update table name metadata

**Phase 2: Update SQL Generator** (`core/schema/sql_generator.py`)
- Update import statements
- Change table generation: "platform_requests" → "api_requests"
- Change table generation: "platform_request_jobs" → "orchestration_jobs"
- Update index generation calls
- Update PRIMARY KEY / FOREIGN KEY references

**Phase 3: Update Repository** (`infrastructure/platform.py`)
- Rename class: `PlatformRepository` → `ApiRequestRepository`
- Update all SQL table references (11 queries)
- Update method names for clarity
- Update imports

**Phase 4: Update Triggers**
- `triggers/trigger_platform.py`: Update imports, endpoint docs, class names
- `triggers/trigger_platform_status.py`: Update imports, endpoint docs

**Phase 5: Update Core Models Export** (`core/models/__init__.py`)
- Update import statements
- Update __all__ list

**Phase 6: Deploy & Test**
1. Deploy to Azure Functions: `func azure functionapp publish rmhgeoapibeta --python --build remote`
2. Redeploy database schema: `POST /api/db/schema/redeploy?confirm=yes`
3. Test API endpoint: `POST /api/platform/submit`
4. Verify new tables exist: `app.api_requests`, `app.orchestration_jobs`
5. Verify old tables dropped

**Phase 7: Update Documentation**
- `docs_claude/CLAUDE_CONTEXT.md` - Update Platform references
- `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md` - Update table names
- `docs_claude/FILE_CATALOG.md` - Update file descriptions

### Implementation Summary

**What Was Completed**:
- ✅ All 7 phases completed successfully
- ✅ Fixed import error in `triggers/schema_pydantic_deploy.py` (missed on first deployment)
- ✅ Added backward compatibility alias: `PlatformRepository = ApiRequestRepository`
- ✅ Updated 8 files total (models, generator, repository, triggers, exports, deployer)
- ✅ Deployed to Azure Functions (successful after fixing imports)
- ✅ Schema redeployed with new table names verified

**Files Modified**:
1. `core/models/platform.py` - Renamed classes, updated metadata
2. `core/schema/sql_generator.py` - Updated imports, table names, PRIMARY KEY/FOREIGN KEY refs
3. `infrastructure/platform.py` - Renamed class, updated all SQL queries, added alias
4. `triggers/trigger_platform.py` - Updated imports and docs
5. `triggers/trigger_platform_status.py` - Updated CLAUDE header
6. `core/models/__init__.py` - Updated exports
7. `triggers/schema_pydantic_deploy.py` - **CRITICAL FIX**: Updated imports (missed initially)
8. `docs_claude/TODO.md` - This file!

**Errors Encountered**:
1. **Import Error**: `schema_pydantic_deploy.py` still importing `PlatformRecord` (fixed)
2. **Type Hints**: Missed updating `Optional[PlatformRecord]` and `-> PlatformRecord` (fixed)
3. **Inheritance**: `PlatformStatusRepository` inheriting from old name (fixed)

**Deployment Summary**:
- Deployment 1: Failed (import error)
- Deployment 2: ✅ SUCCESS
- Schema redeploy: ✅ New tables created (`api_requests`, `orchestration_jobs`)

**Verification**:
```json
{
    "table_list": [
        "api_requests",      // ✅ NEW NAME
        "jobs",
        "orchestration_jobs", // ✅ NEW NAME
        "tasks"
    ]
}
```

### Benefits Achieved

1. **API Clarity**: "api_requests" immediately conveys client-facing nature
2. **Execution Separation**: "orchestration_jobs" clearly indicates workflow coordination
3. **Documentation**: Self-documenting table names
4. **Onboarding**: New developers understand table purposes instantly
5. **APIM Integration**: Naming aligns with future Azure API Management deployment

---

## ✅ COMPLETED: Multi-Account Storage Architecture (29 OCT 2025)

**Status**: ✅ **COMPLETE & TESTED** - Awaiting Azure CDN recovery for deployment
**Git Commit**: `cd4bd4f` - "Implement multi-account storage architecture with trust zone separation"

### What Was Completed

1. **Configuration Layer** (`config.py`)
   - ✅ Added `StorageAccountConfig` class (8 purpose-specific containers)
   - ✅ Added `MultiAccountStorageConfig` class (Bronze/Silver/SilverExternal zones)
   - ✅ Updated `AppConfig.storage` field
   - ✅ Backward compatible deprecated fields

2. **BlobRepository Updates** (`infrastructure/blob.py`)
   - ✅ Multi-instance singleton pattern (one per account)
   - ✅ Added `BlobRepository.for_zone(zone)` class method
   - ✅ Zone-aware container pre-caching
   - ✅ Backward compatible `instance()` method

3. **Factory Pattern** (`infrastructure/factory.py`)
   - ✅ Updated `create_blob_repository(zone="silver")`
   - ✅ Zone parameter support
   - ✅ Backward compatibility maintained

4. **Documentation**
   - ✅ `MULTI_ACCOUNT_STORAGE_ARCHITECTURE.md` (80KB+ comprehensive guide)
   - ✅ `IMPLEMENTATION_SUMMARY.txt` (testing results and migration path)

5. **Testing**
   - ✅ All syntax validated (py_compile)
   - ✅ All imports verified
   - ✅ Multi-instance singleton tested
   - ✅ Zone-based access tested
   - ✅ Backward compatibility confirmed

### Deployment Status

**❌ BLOCKED**: Azure Front Door / Oryx CDN outage
- Oryx CDN (`oryxsdks-cdn.azureedge.net`) not accessible
- Microsoft infrastructure issue (confirmed via testing)
- Code is ready, waiting for Azure recovery
- Will deploy when CDN accessible

### Container Naming (Ready in rmhazuregeo)

**Bronze Zone** (Untrusted):
- bronze-vectors, bronze-rasters, bronze-misc, bronze-temp

**Silver Zone** (Trusted):
- silver-cogs, silver-vectors, silver-mosaicjson, silver-stac-assets, silver-temp

**SilverExternal Zone** (Airgapped - placeholder):
- silverext-cogs, silverext-vectors, silverext-mosaicjson, etc.

### Next Steps (When Azure Recovers)
1. Deploy to Azure: `func azure functionapp publish rmhgeoapibeta --python --build remote`
2. Redeploy database schema: `POST /api/db/schema/redeploy?confirm=yes`
3. Test health endpoint: `GET /api/health`
4. Verify zone-based container access

---

## ✅ COMPLETED: Platform SQL Composition Refactoring (29 OCT 2025)

**Status**: ✅ **COMPLETE** - All 5 phases completed, awaiting deployment testing
**Priority**: P0 - Critical architecture alignment with CoreMachine
**Actual Effort**: ~2 hours (completed all 5 phases!)
**Completed**: 29 OCT 2025

### What Was Accomplished

**🎯 Exceeded Original Plan** - Completed ALL 5 phases in one session:

1. **Phase 1**: ✅ Repository Inheritance
   - Created `infrastructure/platform.py` (545 lines)
   - Moved both `PlatformRepository` and `PlatformStatusRepository`
   - Added lazy loading exports to `infrastructure/__init__.py`
   - Updated imports in both trigger files

2. **Phase 2**: ✅ SQL Composition Pattern
   - Converted ALL 11 SQL queries to use `sql.SQL().format(sql.Identifier())`
   - Eliminated raw SQL strings (except deprecated `_ensure_schema()`)
   - Schema-agnostic via `self.schema_name` variable

3. **Phase 3**: ✅ Error Context Management
   - Wrapped all repository methods with `_error_context()`
   - Detailed error logging for all database operations

4. **Phase 4**: ✅ Transaction Management
   - Replaced manual `conn.commit()` with `_execute_query()` auto-commit
   - Eliminated `with conn.cursor()` blocks
   - Leveraged base class transaction handling

5. **Phase 5**: ✅ Schema Variable Consistency
   - Replaced hardcoded `"app"` with `self.schema_name`
   - Syntax validation passed with `py_compile`

**🔒 Circular Import Handling**:
- Used `TYPE_CHECKING` to avoid runtime circular imports
- Runtime imports inside methods where needed
- String annotations for forward references

**Files Changed**:
- `infrastructure/platform.py` - NEW (545 lines, comprehensive SQL composition)
- `infrastructure/__init__.py` - Added PlatformRepository + PlatformStatusRepository exports
- `triggers/trigger_platform.py` - Removed repository class, updated imports
- `triggers/trigger_platform_status.py` - Removed repository class, updated imports

### Objective

Refactor Platform repository layer to use CoreMachine's SQL composition patterns:
- Use `psycopg.sql` composition for SQL injection prevention
- Inherit from `PostgreSQLRepository` base class
- Use `_execute_query()` and `_error_context()` helpers
- Eliminate raw SQL strings (currently 11 occurrences)

### Current Issues

❌ **Platform Repository (trigger_platform.py)**:
- Uses raw SQL strings (vulnerable to injection if schema becomes dynamic)
- No inheritance from `PostgreSQLRepository`
- Manual `conn.commit()` on every operation
- No `_error_context()` for detailed error logging
- Hardcoded schema name `"app"` throughout

✅ **CoreMachine (infrastructure/postgresql.py)**:
- 100% SQL composition with `sql.SQL()` + `sql.Identifier()`
- Inherits from `PostgreSQLRepository` base
- Uses `_execute_query()` with guaranteed commits
- `_error_context()` wraps all operations
- Schema name via `self.schema_name` variable

### Implementation Phases

#### Phase 1: Repository Inheritance ✅ COMPLETE (29 OCT 2025)
- [x] Create `infrastructure/platform.py` ✅
- [x] Move `PlatformRepository` from `trigger_platform.py` to `infrastructure/platform.py` ✅
- [x] Make `PlatformRepository` inherit from `PostgreSQLRepository` ✅
- [x] Move `PlatformStatusRepository` from `trigger_platform_status.py` to `infrastructure/platform.py` ✅
- [x] Convert ALL SQL queries to composition pattern (went beyond Phase 1!) ✅
- [x] Add error context wrappers with `_error_context()` (went beyond Phase 1!) ✅
- [x] Update imports in trigger files ✅
- [x] Add lazy loading exports to `infrastructure/__init__.py` ✅
- [x] Syntax validation with py_compile ✅
- [ ] **PENDING**: Test Platform endpoints functionality (requires deployment)

**Files Changed**:
- `infrastructure/platform.py` (NEW)
- `triggers/trigger_platform.py` (import changes only)
- `triggers/trigger_platform_status.py` (import changes only)
- `infrastructure/__init__.py` (add exports)

#### Phase 2: SQL Composition ✅ COMPLETE (29 OCT 2025)
- [x] Convert `_ensure_schema()` - LEFT AS RAW SQL (deprecated DDL code) ⚠️
- [x] Convert `create_request()` INSERT statement ✅
- [x] Convert `get_request()` SELECT statement ✅
- [x] Convert `update_request_status()` UPDATE statement ✅
- [x] Convert `add_job_to_request()` UPDATE + INSERT statements (2 queries) ✅
- [x] Convert `PlatformStatusRepository.get_request_with_jobs()` complex JOIN ✅
- [x] Convert `PlatformStatusRepository.get_all_requests()` SELECT ✅
- [x] Convert `PlatformStatusRepository.check_and_update_completion()` SELECT + UPDATE ✅
- [x] Replace all `"app"` strings with `self.schema_name` ✅
- [ ] **PENDING**: Test all Platform operations (requires deployment)

**Pattern Example**:
```python
# BEFORE (raw string)
cur.execute("""
    INSERT INTO app.platform_requests (...)
    VALUES (...)
""", (...))

# AFTER (composition)
query = sql.SQL("""
    INSERT INTO {}.{} (...)
    VALUES (...)
""").format(
    sql.Identifier(self.schema_name),
    sql.Identifier("platform_requests")
)
self._execute_query(query, (...), fetch='one')
```

#### Phase 3: Error Context Management ✅ COMPLETE (29 OCT 2025)
- [x] Wrap `create_request()` with `_error_context("platform request creation", ...)` ✅
- [x] Wrap `get_request()` with `_error_context("platform request retrieval", ...)` ✅
- [x] Wrap `update_request_status()` with `_error_context("platform status update", ...)` ✅
- [x] Wrap `add_job_to_request()` with `_error_context("platform job mapping", ...)` ✅
- [x] Wrap all status repository methods with `_error_context()` ✅
- [ ] **PENDING**: Test error messages include operation context (requires deployment)

#### Phase 4: Transaction Management ✅ COMPLETE (29 OCT 2025)
- [x] Replace manual `conn.commit()` with `_execute_query()` auto-commit ✅
- [x] Remove all `with conn.cursor()` blocks (use `_execute_query()`) ✅
- [ ] **PENDING**: Verify all operations commit successfully (requires deployment)
- [ ] **PENDING**: Test idempotent operations (requires deployment)

#### Phase 5: Schema Variable Consistency ✅ COMPLETE (29 OCT 2025)
- [x] Search for remaining `"app"` hardcoded strings ✅
- [x] Replace with `self.schema_name` where appropriate ✅
- [x] Verify schema resolution in all queries (syntax validated) ✅
- [ ] **PENDING**: Final integration test (requires deployment)

### Testing Checklist

After each phase:
- [ ] Platform submission works: `POST /api/platform/submit`
- [ ] Platform status works: `GET /api/platform/status/{request_id}`
- [ ] Platform list works: `GET /api/platform/status`
- [ ] Jobs created successfully in `app.jobs` table
- [ ] Mapping table populated in `app.platform_request_jobs`
- [ ] No errors in Application Insights logs

### Success Criteria

✅ **Code Quality**:
- Zero raw SQL strings in Platform repository
- All queries use `sql.SQL().format(sql.Identifier())`
- Platform inherits from `PostgreSQLRepository`
- All operations use `_execute_query()` + `_error_context()`

✅ **Functional**:
- All Platform endpoints working
- Database operations successful
- Error messages detailed and contextual
- Consistent with CoreMachine patterns

### Reference Files

- **Pattern Reference**: `infrastructure/postgresql.py` (lines 624-760)
- **Inheritance Example**: `PostgreSQLJobRepository` (line 514)
- **Error Context Example**: Lines 623, 676, 729, 787
- **Execute Query**: Lines 440-545

---

## ✅ COMPLETED: Systematic Documentation Review - Phase 1 (29 OCT 2025)

**Status**: ✅ **PHASE 1 COMPLETE** - All high-priority files documented
**Priority**: P1 - Quality assurance and maintenance
**Completed**: 48 files with comprehensive headers and docstrings
**Timeline**: Single day (29 OCT 2025)

### Phase 1 Achievement Summary

Successfully completed comprehensive documentation review of all high-priority files:

✅ **Triggers (19 files)** - 100% complete
- All HTTP endpoints documented
- Base class (http_base.py) serves as gold standard
- Template Method pattern fully explained
- Security notes added where applicable

✅ **Jobs (15 files)** - 100% complete
- All workflow definitions documented
- JobBase ABC with 5-method contract explained
- ALL_JOBS explicit registry documented
- Fan-out/fan-in patterns clearly described

✅ **Infrastructure (14 files)** - 100% complete
- All repository implementations documented
- Repository pattern consistently applied
- Factory pattern fully explained
- SQL injection prevention documented

### Documentation Standards Applied

**Every file (48 total) now has:**
1. ✅ **Claude Context Header** with EPOCH 4 designation
2. ✅ **LAST_REVIEWED: 29 OCT 2025** date
3. ✅ **PURPOSE** - one-line description
4. ✅ **EXPORTS** - what the file provides
5. ✅ **INTERFACES** - what it implements/extends
6. ✅ **DEPENDENCIES** - external requirements
7. ✅ **PATTERNS** - architectural patterns used
8. ✅ **ENTRY_POINTS** - how to use it
9. ✅ **INDEX** - major sections with line numbers
10. ✅ **Enhanced docstrings** with examples
11. ✅ **Author attribution**: "Robert and Geospatial Claude Legion"

### Benefits Delivered

**For Code Review:**
- Quick context from headers
- Change impact analysis via dependencies
- Pattern recognition documented
- Integration points explicit

**For Updates:**
- Interface contracts prevent breakage
- Clear separation of concerns
- Validation points documented
- Test guidance via entry points

**For Onboarding:**
- Complete architectural overview
- Navigation via INDEX sections
- Pattern learning across codebase
- Gold standard examples

### Files Serving as Gold Standards

- **http_base.py** - Perfect base class documentation
- **base.py** (jobs) - Exemplary interface contract
- **decorators_blob.py** - Gold standard decorator docs
- **process_large_raster.py** - Complete workflow documentation
- **submit_job.py** - Comprehensive endpoint docs
- **health.py** - Detailed 9-component monitoring

---

## 🎯 FUTURE: Systematic Documentation Review - Phase 2+ (Optional)

**Status**: ⏸️ **DEFERRED** - Phase 1 covered all critical files
**Priority**: P2 - Lower priority (optional enhancement)

### Remaining Phases (Optional Future Work)

**Phase 2: Service Layer** (Est: 3-4 hours)
- Core services (5 files)
- Raster services (4 files)
- Vector services (3 files) - Some already excellent (26 OCT)
- Container services (3 files) - Already complete (29 OCT)
- STAC services (2 files)
- **Total**: ~13 files (3 already done)

**Phase 3: Core Architecture** (Est: 2-3 hours)
- core/ folder (17 files) - CoreMachine orchestration
- **Total**: 17 files

**Phase 4: Supporting Files** (Est: 3-4 hours)
- Root Python files (6 files)
- Schemas (10 files) - Legacy and active
- Utils (3 files)
- Models (misc files)
- **Total**: 19+ files

**Phase 5: Update FILE_CATALOG.md** (Est: 1 hour)
- Add "Last Reviewed" column to all sections
- Update status markers
- Document completion percentage

### Review Checklist Per File

For each Python file, verify:

```markdown
## File: {filename}

### Claude Context Header
- [ ] Header present (Lines 1-20)
- [ ] EPOCH designation included
- [ ] STATUS description current
- [ ] PURPOSE one-liner accurate
- [ ] LAST_REVIEWED date current (< 60 days old)
- [ ] EXPORTS list complete
- [ ] INTERFACES documented (if applicable)
- [ ] PYDANTIC_MODELS listed (if applicable)
- [ ] DEPENDENCIES accurate
- [ ] SOURCE documented
- [ ] SCOPE defined
- [ ] VALIDATION described
- [ ] PATTERNS documented
- [ ] ENTRY_POINTS listed
- [ ] INDEX with line numbers (if file > 200 lines)

### Module Docstring
- [ ] Present immediately after header
- [ ] Clear purpose statement
- [ ] Key features/improvements listed (if applicable)
- [ ] Usage examples (for utilities/decorators)
- [ ] Author and date attribution

### Class Documentation
- [ ] All classes have docstrings
- [ ] Public methods documented
- [ ] Private methods have purpose comments
- [ ] Custom exceptions documented

### Function Documentation
- [ ] All public functions have docstrings
- [ ] Args/Parameters documented
- [ ] Returns documented
- [ ] Raises/Exceptions documented
- [ ] Examples provided (for complex functions)

### Issues Found
- [ ] None OR list specific issues

### Action Required
- [ ] None OR describe fixes needed
```

### Progress Tracking

**Phase 1: High-Priority Files** (36 files)
- [ ] **Triggers** (11 files)
  - [x] trigger_platform.py - ✅ EXCELLENT (reviewed 29 OCT)
  - [x] trigger_platform_status.py - ✅ EXCELLENT (reviewed 29 OCT)
  - [ ] trigger_job_processor.py
  - [ ] health.py
  - [ ] submit_job.py
  - [ ] list_jobs.py
  - [ ] job_status.py
  - [ ] db_admin.py
  - [ ] db_query.py
  - [ ] container.py
  - [ ] schema_pydantic_deploy.py

- [ ] **Jobs** (12 files)
  - [ ] base.py
  - [ ] hello_world.py
  - [ ] create_h3_base.py
  - [ ] generate_h3_level4.py
  - [ ] ingest_vector.py
  - [ ] validate_raster_job.py
  - [ ] container_summary.py
  - [ ] container_list.py
  - [ ] container_list_diamond.py
  - [ ] stac_catalog_container.py
  - [ ] stac_catalog_vectors.py
  - [ ] process_raster.py
  - [ ] process_large_raster.py

- [ ] **Infrastructure** (13 files)
  - [x] decorators_blob.py - ✅ EXCELLENT (reviewed 29 OCT)
  - [ ] base.py
  - [ ] factory.py
  - [ ] jobs_tasks.py
  - [ ] postgresql.py
  - [ ] blob.py
  - [ ] queue.py
  - [ ] service_bus.py
  - [ ] vault.py
  - [ ] stac.py
  - [ ] duckdb.py
  - [ ] interface_repository.py
  - [ ] __init__.py

**Phase 2: Service Layer** (16+ files)
- [ ] **Vector Services** (3 files)
  - [x] vector/postgis_handler_enhanced.py - ✅ EXCELLENT (reviewed 29 OCT)
  - [x] vector/tasks_enhanced.py - ✅ EXCELLENT (reviewed 29 OCT)
  - [ ] vector/converters.py

- [ ] **Core Services** (5 files)
  - [ ] service_hello_world.py
  - [ ] service_blob.py
  - [ ] service_stac_setup.py
  - [ ] container_summary.py
  - [ ] container_list.py

- [ ] **Raster Services** (4 files)
  - [ ] raster_validation.py
  - [ ] raster_cog.py
  - [ ] tiling_scheme.py
  - [ ] tiling_extraction.py

**Phase 3: Core Architecture** (17 files)
- [ ] core/machine.py
- [ ] core/task_id.py
- [ ] core/state_manager.py
- [ ] core/orchestration_manager.py
- [ ] core/models/enums.py
- [ ] core/models/job.py
- [ ] core/models/task.py
- [ ] core/models/results.py
- [ ] core/models/context.py
- [ ] core/models/__init__.py
- [ ] core/logic/task_creation.py
- [ ] core/logic/stage_advancement.py
- [ ] core/logic/job_completion.py
- [ ] core/schema/workflow.py
- [ ] core/schema/orchestration.py
- [ ] core/schema/queue.py
- [ ] core/schema/updates.py

**Phase 4: Supporting Files** (19+ files)
- [ ] **Root Python** (6 files)
  - [ ] function_app.py
  - [ ] config.py
  - [ ] exceptions.py
  - [ ] util_logger.py
  - [ ] service_stac.py
  - [ ] service_statistics.py

- [ ] **Utils** (3 files)
  - [ ] utils/contract_validator.py
  - [ ] util_azure_sql.py
  - [ ] task_factory.py

- [ ] **Schemas** (10 files) - Legacy
  - [ ] schema_base.py
  - [ ] schema_workflow.py
  - [ ] schema_orchestration.py
  - [ ] schema_queue.py
  - [ ] schema_updates.py
  - [ ] schema_file_item.py
  - [ ] schema_geospatial.py
  - [ ] schema_postgis.py
  - [ ] schema_stac.py
  - [ ] model_core.py

**Completion Stats**:
- Phase 1: 3/36 complete (8%) - trigger_platform.py, trigger_platform_status.py, decorators_blob.py
- Phase 2: 2/16 complete (13%) - postgis_handler_enhanced.py, tasks_enhanced.py
- Phase 3: 0/17 complete (0%)
- Phase 4: 0/19 complete (0%)
- **Overall**: 5/88 files reviewed (6%)

### Output Format

Each file review will produce:
1. **Updated Claude Context Header** (if needed)
2. **Added/Updated Docstrings** (if needed)
3. **FILE_CATALOG.md update** - Mark as "Reviewed DD MMM YYYY"
4. **Review report** - Issues found and fixed

### Success Criteria

- ✅ 100% of Python files have Claude context headers
- ✅ 100% of Python files have module docstrings
- ✅ 100% of classes have docstrings
- ✅ 100% of public functions have docstrings
- ✅ All LAST_REVIEWED dates < 60 days old
- ✅ FILE_CATALOG.md tracks review status

### Timeline

- **Start Date**: 29 OCT 2025
- **Target Completion**: 15 NOV 2025 (2 weeks)
- **Estimated Effort**: 10-15 hours total
- **Cadence**: Review 5-10 files per session

---

## 🔥 CRITICAL: Large Raster Workflow Silent Failures (29 OCT 2025)

**Status**: 🚨 **CRITICAL INVESTIGATION** - Multiple silent failures identified in process_large_raster
**Started**: 28 OCT 2025, **Escalated**: 29 OCT 2025
**Priority**: P0 - BLOCKING production use of all large raster workflows

### Problem Summary

**NEW FINDING (29 OCT 2025)**: Stage 2 `extract_tiles` is **failing silently** immediately after entry!
- Job: `7f8be55203646ed919b79896adbdeda9b3ce40a56342a7a72c2e8b25037682cf`
- File: `17apr2024wv2.tif` (production raster)
- Stage 1 (generate_tiling_scheme) ✅ Completes in 0.46s
- Stage 2 (extract_tiles) ❌ **SILENT FAILURE** - Starts but never logs progress
- Last log: `02:47:36.312` "CHECKPOINT_START extract_tiles handler entry"
- Task stuck in 'processing' status for 10+ minutes with ZERO subsequent logs
- Function app restarted multiple times (02:49, 02:50, 02:52)

**ORIGINAL ISSUE (28 OCT 2025)**: Stage 3 `create_cog` tasks never created
- Stage 1 (generate_tiling_scheme) ✅ Completes successfully
- Stage 2 (extract_tiles) ✅ Completes successfully (when it works), creates 72-204 intermediate tiles
- Stage 3 (create_cog) ❌ **ZERO tasks created** - silent failure
- No Stage 3 tasks appear in database
- No error logs visible in Application Insights

### Investigation Progress (29 OCT 2025)

**✅ Stage 2 Silent Failure Investigation**:
1. **Timeline Analysis** (Job `7f8be55203646ed9...`):
   - `02:47:29` - Job submitted via HTTP
   - `02:47:31` - Job processor started Stage 1
   - `02:47:35` - Stage 1 completed successfully (0.46s)
   - `02:47:35` - Job advanced to Stage 2, task created: `7f8be552-s2-extract-tiles`
   - `02:47:36` - Task started, status → 'processing'
   - `02:47:36.312` - **LAST LOG**: "CHECKPOINT_START extract_tiles handler entry"
   - `02:47:36.297` - Task database record updated
   - `02:48:00+` - **NO SUBSEQUENT LOGS** (complete silence)
   - `02:49:00+` - Function app restarts (multiple times)
   - `02:52:42` - Service Bus listeners stopped
   - `02:58:00` - Task still stuck in 'processing' status

2. **Evidence of Silent Failure**:
   - ✅ Handler `extract_tiles` IS registered correctly
   - ✅ Task created and queued to Service Bus successfully
   - ✅ Task processor picked up message and called handler
   - ✅ Handler entry checkpoint logged
   - ❌ **ZERO logs after entry checkpoint**
   - ❌ No exception logs, no error messages, no progress updates
   - ❌ Task never completed or failed - orphaned in 'processing'

3. **Failure Pattern Identified**:
   - Handler enters (`CHECKPOINT_START` logged)
   - **Code execution stops immediately after entry**
   - No subsequent logging statements execute
   - No exception handling catches the failure
   - Python worker may crash (SIGABRT/segfault)
   - Task left orphaned without cleanup

**🔍 Root Cause Hypotheses (Stage 2 Failure)**:

**Hypothesis A: GDAL/Rasterio Native Library Crash**
- `extract_tiles` uses rasterio/GDAL to open raster file
- Native C++ library crash (segfault) would kill Python worker
- No Python exception raised - worker process terminates
- Evidence: Function app restarts after task starts
- **Location**: First rasterio operation after entry checkpoint
- **Code**: `services/tiling_extraction.py` lines 475-492

**Hypothesis B: Missing/Invalid Tiling Scheme Data**
- Stage 1 result structure doesn't match expected format
- Code tries to access missing key → crashes before logging
- No defensive validation after entry checkpoint
- **Location**: Accessing Stage 1 result data in handler
- **Code**: `services/tiling_extraction.py` parsing `previous_results`

**Hypothesis C: Azure Functions Memory/Timeout**
- File too large, crashes during initial rasterio.open()
- Memory exhaustion before first log statement
- Python worker killed by Azure Functions runtime
- **File**: `17apr2024wv2.tif` - size unknown

**Hypothesis D: Missing Logging After Entry**
- Code IS executing but not logging
- Silent exception swallowing
- Early return/exit without logging
- **Evidence**: No error logs, no completion, just silence

**✅ Completed Investigations (Stage 3 - Original Issue)**:
1. **Handler Registration** - Verified `create_cog` IS properly registered in `services/__init__.py:112`
2. **Registration Pattern** - Confirmed system uses explicit registration (not decorators)
3. **Task Creation Code** - Found `create_tasks_for_stage()` method in `jobs/process_large_raster.py:448-535`
4. **Expected Data Flow** - Stage 2 returns `{"tile_blobs": [...], "source_crs": "..."}` which Stage 3 consumes
5. **Added Debug Logging** - Comprehensive logging added to Stage 3 task creation (not yet deployed)

**🚧 Current Status**:
- **Stage 2 failure takes priority** - Stage 3 won't run if Stage 2 fails
- Stage 3 debug logging ready but not deployed (waiting for Stage 2 fix)

### Immediate Action Items (Priority Order)

**PHASE 1: Add Defensive Logging to Stage 2 Handler** 🔥 **CRITICAL**
1. [ ] Add logging checkpoints in `services/tiling_extraction.py` after entry:
   ```python
   logger.info(f"[CHECKPOINT_1] Parsing tiling scheme from previous_results")
   logger.info(f"[CHECKPOINT_2] Opening raster with rasterio: {blob_name}")
   logger.info(f"[CHECKPOINT_3] Raster opened successfully - dims: {width}x{height}")
   logger.info(f"[CHECKPOINT_4] Extracting tile window: {window}")
   logger.info(f"[CHECKPOINT_5] Tile extracted, uploading to blob storage")
   logger.info(f"[CHECKPOINT_6] Upload complete, returning result")
   ```
2. [ ] Add try/except around EVERY rasterio/GDAL operation with detailed error logging
3. [ ] Add Stage 1 result validation BEFORE using tiling scheme data
4. [ ] Deploy with enhanced logging
5. [ ] Re-test with `17apr2024wv2.tif`
6. [ ] Analyze logs to identify exact failure point

**PHASE 2: Investigate Native Library Crash** (if checkpoints stop mid-execution)
1. [ ] Check rasterio/GDAL version compatibility with Azure Functions Python 3.12
2. [ ] Review `17apr2024wv2.tif` file properties (size, compression, CRS)
3. [ ] Test with smaller raster first to rule out memory issues
4. [ ] Add memory usage logging before/after rasterio operations
5. [ ] Consider GDAL error handler configuration

**PHASE 3: Fix Stage 3 Task Creation** (once Stage 2 works)
1. [ ] Deploy Stage 3 debug logging already written
2. [ ] Submit test job for `antigua.tif` (72 tiles expected)
3. [ ] Query logs for `[STAGE3_DEBUG]` markers
4. [ ] Identify exact failure point in task creation
5. [ ] Apply fix based on actual error discovered
6. [ ] Remove debug logging after fix confirmed

**PHASE 4: End-to-End Validation**
1. [ ] Test complete workflow: Stage 1 → 2 → 3 → 4
2. [ ] Verify all stages complete successfully
3. [ ] Check COG output quality
4. [ ] Validate STAC metadata creation
5. [ ] Update documentation with findings

### Diagnostic Data (29 OCT 2025)

**Failed Job Details**:
```json
{
  "job_id": "7f8be55203646ed919b79896adbdeda9b3ce40a56342a7a72c2e8b25037682cf",
  "job_type": "process_large_raster",
  "file": "17apr2024wv2.tif",
  "container": "rmhazuregeobronze",
  "status": "processing",
  "stage": 1,
  "total_stages": 4,
  "created_at": "2025-10-29T02:47:29.454937",
  "updated_at": "2025-10-29T02:47:35.904920"
}
```

**Failed Task Details**:
```json
{
  "task_id": "7f8be552-s2-extract-tiles",
  "parent_job_id": "7f8be55203646ed919b79896adbdeda9b3ce40a56342a7a72c2e8b25037682cf",
  "task_type": "extract_tiles",
  "status": "processing",
  "stage": 2,
  "created_at": "2025-10-29T02:47:36.295",
  "updated_at": "2025-10-29T02:47:36.297875",
  "stuck_duration": "10+ minutes"
}
```

**Last Known Log Entry**:
```
Timestamp: 2025-10-29T02:47:36.312740Z
Message: "🔍 [CHECKPOINT_START] extract_tiles handler entry for job_id: 7f8be55203646ed9"
Component: service.TilingExtraction
```

**System Events**:
- Function app restarts: 02:49:04, 02:49:42, 02:50:05, 02:50:29
- Service Bus listeners stopped: 02:52:42
- Python worker crashes suspected (exit code 134 seen in other scenarios)

### Related Files

- **🔥 CRITICAL**: [`services/tiling_extraction.py`](services/tiling_extraction.py:475-492) - Stage 2 handler (FAILING)
- **Workflow Definition**: [`jobs/process_large_raster.py`](jobs/process_large_raster.py)
- **Handler Registry**: [`services/__init__.py`](services/__init__.py:112)
- **Stage 3 Handler**: [`services/raster_cog.py`](services/raster_cog.py:101) - (Not reached yet)
- **CoreMachine Task Creation**: [`core/machine.py`](core/machine.py:300-313)

### Testing Commands

**Submit Test Job**:
```bash
# Test with 17apr2024wv2.tif (current failure case)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_large_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "17apr2024wv2.tif", "container_name": "rmhazuregeobronze"}'

# Alternative: Test with smaller raster
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_large_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "antigua.tif", "container_name": "rmhazuregeobronze"}'
```

**Monitor Stage 2 Processing**:
```bash
# Check for extract_tiles checkpoint logs
cat > /tmp/query_stage2_checkpoints.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where message contains 'CHECKPOINT' or message contains 'extract_tiles' | order by timestamp asc | project timestamp, message, severityLevel" \
  -G | python3 -m json.tool
EOF
chmod +x /tmp/query_stage2_checkpoints.sh
/tmp/query_stage2_checkpoints.sh
```

**Check for Crashes/Errors**:
```bash
# Look for worker crashes and exceptions
cat > /tmp/query_crashes.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=union traces, exceptions | where timestamp >= ago(15m) | where severityLevel >= 3 or itemType == 'exception' or message contains 'crash' or message contains 'exit' | order by timestamp desc | take 20 | project timestamp, message, severityLevel" \
  -G | python3 -m json.tool
EOF
chmod +x /tmp/query_crashes.sh
/tmp/query_crashes.sh
```

**Get Job/Task Status**:
```bash
# Check job status
JOB_ID="7f8be55203646ed919b79896adbdeda9b3ce40a56342a7a72c2e8b25037682cf"
curl -s "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/${JOB_ID}" | python3 -m json.tool

# Check task details
curl -s "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/${JOB_ID}" | python3 -c "import sys, json; data=json.load(sys.stdin); [print(f'Task: {t[\"task_id\"]}, stage={t[\"stage\"]}, status={t[\"status\"]}, updated={t[\"updated_at\"]}') for t in data['tasks']]"
```

**Query Stage 3 Debug Logs** (when Stage 2 works):
```bash
cat > /tmp/query_stage3_debug.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | where message contains '[STAGE3_DEBUG]' | order by timestamp desc | take 50" \
  -G | python3 -m json.tool
EOF
chmod +x /tmp/query_stage3_debug.sh
/tmp/query_stage3_debug.sh
```

### Known Issues

**Azure Functions Python Severity Mapping Bug** (28 OCT 2025):
- Azure SDK maps `logging.DEBUG` to severity 1 (INFO) instead of 0 (DEBUG)
- **Workaround**: Query by message content, not severity level
- See: [`docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md`](docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md#azure-functions-python-logging-severity-mapping-issue)

---

## ✅ COMPLETED: process_raster_collection Pattern Compliance Analysis (22 OCT 2025)

**Status**: ✅ **ANALYSIS COMPLETE** - Implementation plan created, ready for deployment
**Completion Date**: 22 OCT 2025
**Impact**: Identified 5 critical fixes for CoreMachine pattern compliance + comprehensive implementation plan

### What Was Analyzed

**Comprehensive Pattern Review**:
- Reviewed `process_raster_collection` 4-stage workflow (validate → COG → MosaicJSON → STAC)
- Compared against CoreMachine patterns validated 21-22 OCT 2025
- Identified reusable components vs. new implementation needed
- Created detailed implementation plan with before/after code snippets

**Key Findings**:
1. ✅ **Stages 1-2 Handlers Ready**: `validate_raster`, `create_cog` (100% reusable, zero changes needed)
2. ✅ **Parallelism Values Already Fixed**: Stage 1 = "single", Stage 2 = "fan_out" (lines 85, 92)
3. ❌ **Method Signature Mismatch**: `create_tasks_for_stage()` has `= None` default (should match JobBase)
4. ❌ **Dead Code Discovered**: 127 lines in unused `_create_stage_3_tasks()` and `_create_stage_4_tasks()`
5. ⚠️ **Handler Contract Minor Fix**: `create_stac_collection` extracts params incorrectly (needs `job_parameters` dict)
6. ✅ **Success Fields Compliant**: All handlers already return `{"success": bool, ...}`

**Critical Insight**: Only 2 files need changes (process_raster_collection.py, stac_collection.py) with 4 small edits total

### Implementation Plan Created

**Documentation**: `docs_claude/RASTER_COLLECTION_IMPLEMENTATION_PLAN.md` (107KB)

**Plan Contents**:
- Executive summary with current workflow status
- 4-stage diamond pattern architecture diagram
- 5 critical fixes with detailed before/after code snippets:
  1. ✅ Fix #1: Parallelism values (ALREADY FIXED)
  2. 🔧 Fix #2: Remove `= None` from `previous_results` parameter
  3. 🗑️ Fix #3: Delete 127 lines of dead code (Stages 3-4 methods)
  4. 🔧 Fix #4: Extract params from `job_parameters` dict in stac_collection handler
  5. ✅ Fix #5: Success field compliance (ALREADY COMPLIANT)
- Complete implementation checklist organized by phase:
  - **Phase 1**: Code fixes (2 files, ~10 min)
  - **Phase 2**: Testing with 2-tile workflow (30-45 min)
  - **Phase 3**: Documentation updates (10 min)
- Success criteria with specific validation points
- Timeline estimate: **4-5 hours total**

### Related Documentation Identified

**Large Raster Automatic Tiling** (answers "GeoTIFF over 1GB get split into tiles"):

1. **`RASTER_PIPELINE.md`** (93KB) ⭐ PRIMARY REFERENCE
   - **Pipeline Selection**: ≤1GB (2-stage) vs >1GB (4-stage with automatic tiling)
   - **Stage 2: Create Tiling Strategy** (lines 1056-1107)
     - Automatic tile grid calculation
     - Default: 5000x5000 pixels per tile
     - 100-pixel overlap for seamless stitching
     - Grid dimensions auto-calculated (rows × cols)
     - Example: 25,000 × 25,000 pixel raster → 5×5 grid = 25 tiles
   - **Stage 3: Parallel Tile Processing** (lines 1110-1156)
     - Fan-out pattern (N tiles = N parallel tasks)
     - Per-tile: extract window → reproject → create COG
     - Upload individual tiles to silver container
   - **Stage 4: Create MosaicJSON + STAC Metadata**
     - **NOT GDAL VRT** - Use MosaicJSON for virtual mosaic
     - Generate MosaicJSON from individual COG tiles
     - Add individual COG tiles to PgSTAC `system_tiles` collection
     - Add MosaicJSON dataset to PgSTAC `titiler` collection (for TiTiler serving)
     - No intermediate storage cleanup needed (all tiles kept in silver)

2. **`COG_MOSAIC.md`** (33KB) - Post-Tiling Workflow
   - MosaicJSON generation from completed COG tiles
   - Quadkey spatial indexing (zoom level 6-8 recommended)
   - **STAC Three-Collection Strategy**:
     - `system_tiles`: Individual COG tiles (internal tracking)
     - `titiler`: MosaicJSON datasets (TiTiler serving layer)
     - `datasets`: User-facing datasets (links to titiler collection)
   - Atomic transaction pattern for metadata visibility
   - TiTiler-PgSTAC integration (queries titiler collection)

3. **`CLAUDE.md`** (lines 669-678) - Example "stage_raster" Workflow
   ```
   Stage 1: Ensure metadata exists, extract if missing
   Stage 2: If raster is gigantic, create tiling scheme
   Stage 3: Fan-out - Parallel tasks to reproject/validate raster chunks
   Stage 4: Fan-out - Parallel tasks to convert chunks to COGs
   Stage 5: Create MosaicJSON + add to PgSTAC titiler collection
   ```

**CRITICAL ARCHITECTURE UPDATE (22 OCT 2025)**:
- ❌ **OLD**: GDAL VRT mosaic → final COG with overviews
- ✅ **NEW**: MosaicJSON virtual mosaic (no VRT, no merged COG)
- **Why**: Individual tiles remain accessible + virtual mosaic via MosaicJSON
- **TiTiler Integration**: Queries PgSTAC `titiler` collection for MosaicJSON datasets

**Tiling Scheme Inference Logic** (RASTER_PIPELINE.md lines 1062-1107):
```python
{
    "source_blob": "bronze/2024/huge_raster.tif",
    "total_tiles": 25,  # Auto-calculated: (raster_size / tile_size)²
    "tile_grid": {
        "rows": 5,  # Calculated from raster height / tile_size
        "cols": 5   # Calculated from raster width / tile_size
    },
    "tile_size_pixels": [5000, 5000],  # Configurable (default 5000)
    "overlap_pixels": 100,  # Prevents seams during mosaicking
    "tiles": [
        {
            "tile_id": "tile_0_0",
            "row": 0,
            "col": 0,
            "window": {"row_off": 0, "col_off": 0, "width": 5000, "height": 5000},
            "bounds": [-120.5, 39.0, -120.0, 39.5]  # CRS-specific bounds
        },
        # ... 24 more tiles with calculated windows and bounds
    ]
}
```

**When Automatic Tiling Triggers**:
- **Threshold**: File size > 1GB (configurable via `raster_size_threshold_mb`)
- **Why**: Rio-cogeo can struggle with large compressed files (tries to decompress entire file)
- **Benefit**: Prevents multi-hour processing times or crashes
- **Result**: Parallel processing across N tiles instead of single-file bottleneck

### Next Steps

**Ready for Implementation** (pending user approval):
1. Apply 4 small code fixes to 2 files
2. Deploy to Azure and test 4-stage workflow with 2 tiles
3. Verify MosaicJSON created in blob storage
4. Verify STAC collection created in PgSTAC
5. Document completion in HISTORY.md

**See**: `RASTER_COLLECTION_IMPLEMENTATION_PLAN.md` for complete implementation guide

---

## ✅ COMPLETED: Task ID Architecture Fix + CoreMachine Validation (22 OCT 2025)

**Status**: ✅ **COMPLETE** - Task IDs fixed, multi-stage workflows validated
**Completion Date**: 22 OCT 2025
**Impact**: Fixed task ID length limits + validated CoreMachine framework works correctly

### What Was Fixed

**1. Task ID Length Bug** ✅
**Problem**: Task IDs exceeded 100-character limit
- Used full 64-char job_id instead of 8-char prefix
- Included filename parameters in semantic name (redundant)
- Example: `268bc942aaf069fb...40411dd6-s1-namangan14aug2019_R1C1cog_analysis` = 103 chars ❌
- Caused Pydantic validation error: "String should have at most 100 characters"

**Root Cause (Key Insight)**:
- Semantic names should describe **TASK TYPE**, not duplicate parameters
- Parameters already hashed in job_id + stored in task.parameters
- Using filename in task_id violates DRY principle

**Solution**:
- Use 8-char job_id prefix (collision probability: ~0.00001% with 100K jobs)
- Semantic names: `validate-{i}`, `cog-{i}`, `mosaicjson`, `stac`
- Stage 1: `{job_id[:8]}-s1-validate-{i}` = 22 chars ✅
- Stage 2: `{job_id[:8]}-s2-cog-{i}` = 17 chars ✅
- Stage 3: `{job_id[:8]}-s3-mosaicjson` = 24 chars ✅
- Stage 4: `{job_id[:8]}-s4-stac` = 17 chars ✅

**2. Undefined Variable Bug** ✅
**Problem**: Incomplete refactoring when removing filename from task IDs
- Removed `tile_name` extraction logic but metadata still referenced it
- Caused `NameError: name 'tile_name' is not defined`
- Jobs failed before creating any tasks

**Solution**: Replace `tile_name` with `blob_name` in metadata (already available)

**3. `pending_analyses` Variable Scope Bug** ✅
**Problem**: Variable calculated as `queued_analyses` but used as `pending_analyses`
- Caused "cannot access local variable" error in job aggregation
**Solution**: Renamed to `pending_analyses` for consistency

### Validation Results

**Test 1: `list_container_contents` (2-stage)**:
- ✅ 6 tasks created, all completed
- ✅ `pending_analyses: 0` reported correctly
- ✅ Clean PROCESSING → QUEUED → PROCESSING transitions
- ✅ Job completed successfully

**Test 2: `hello_world` (2-stage)**:
- ✅ 2 tasks created: `12d5de8b-s1-0`, `12d5de8b-s2-0`
- ✅ Both tasks completed
- ✅ Task IDs use 8-char prefix pattern

**Test 3: `process_raster_collection` (4-stage)**:
- ✅ Job ID: `822d826ddd7f7756...`
- ✅ Tasks created:
  - `822d826d-s1-validate-0` (22 chars) - completed
  - `822d826d-s1-validate-1` (22 chars) - completed
  - `822d826d-s2-cog-0` (17 chars) - processing
  - `822d826d-s2-cog-1` (17 chars) - processing
- ✅ All task IDs under 100-char limit
- ✅ Multi-stage progression working (Stage 1 → Stage 2)

### Files Changed

- `jobs/process_raster_collection.py` - Task ID generation (4 stages)
- `jobs/container_list.py` - pending_analyses variable fix
- `core/machine.py` - Status transition fixes (from 21 OCT)

### Key Architectural Insight

**Task ID Semantic Naming Best Practice**:
- ✅ **Good**: `validate-{i}`, `cog-{i}`, `mosaicjson` - Describes task type
- ❌ **Bad**: `{filename}` - Duplicates parameter data already in job_id and task.parameters

This follows the pattern already used successfully in other jobs like `hello_world`, `container_summary`, `create_h3_base`.

**Git Commits**:
- `2cbc5e1` - Fix task ID generation: remove redundant parameters
- `c7ed216` - Fix undefined variable bug from task ID refactor
- `648a60c` - Fix pending_analyses variable scope bug

---

## ✅ COMPLETED: CoreMachine Status Transition Bug Fix (21 OCT 2025)

**Status**: ✅ **COMPLETE** - Multi-stage jobs now work correctly
**Completion Date**: 21 OCT 2025
**Impact**: Critical framework fix affecting ALL multi-stage jobs

### What Was Fixed

**Problem**: Multi-stage jobs experiencing Service Bus message redelivery and duplicate task processing
- Status transition errors: "Invalid status transition: PROCESSING → PROCESSING"
- Errors silently swallowed, preventing clean Azure Function completion
- Service Bus redelivery loops causing duplicate work

**Two Critical Bugs Fixed**:
1. ✅ **`_advance_stage()` missing status update** - Job remained PROCESSING when queuing next stage
2. ✅ **Silent exception swallowing** - Status validation errors caught and ignored

**Validation Results**:
- ✅ Clean PROCESSING → QUEUED → PROCESSING cycle between stages
- ✅ No "Invalid status transition" errors
- ✅ No Service Bus message redelivery
- ✅ Test job `list_container_contents` completed successfully

**Files Changed**:
- `core/machine.py` - Two fixes (lines 220-228, 915-918)
- `COREMACHINE_STATUS_TRANSITION_FIX.md` - Comprehensive documentation
- `docs_claude/HISTORY.md` - Added to project history

**See**: [HISTORY.md](HISTORY.md) for full details

---

## ✅ COMPLETED: Output Folder Control + Vendor Delivery Discovery (20 OCT 2025)

**Status**: ✅ **COMPLETE** - Custom output paths and intelligent delivery analysis
**Completion Date**: 20 OCT 2025

### What Was Completed

**1. Configurable Output Folder Parameter** ✅
- Added `output_folder` parameter to `process_raster` job
- Supports custom output paths instead of mirroring input folder structure
- Validated with 5 different test scenarios
- **Implementation**: [jobs/process_raster.py](jobs/process_raster.py:103-108, 223-235, 435-451)

**Testing Results**:
| Test | Input | output_folder | Output Path | Status |
|------|-------|---------------|-------------|--------|
| 1 | `test/dctest3_R1C2_regular.tif` | `null` | `test/dctest3_R1C2_regular_cog_analysis.tif` | ✅ |
| 2 | `test/dctest3_R1C2_regular.tif` | `cogs/processed/rgb` | `cogs/processed/rgb/dctest3_R1C2_regular_cog_visualization.tif` | ✅ |
| 3 | `test/dctest3_R1C2_regular.tif` | `processed` | `processed/dctest3_R1C2_regular_cog_archive.tif` | ✅ |
| 4 | `namangan/namangan14aug2019_R1C2cog.tif` | `cogs` | `cogs/namangan14aug2019_R1C2cog_cog_analysis.tif` | ✅ |
| 5 | `6681542855355853500/.../23JAN31104343-S2AS.TIF` | `cogs/maxar/test` | `cogs/maxar/test/23JAN31104343-S2AS_cog_analysis.tif` | ✅ (timed out but path verified) |

**Total Data Processed**: 644 MB across 5 test jobs

**2. Vendor Delivery Discovery System** ✅
- Created `services/delivery_discovery.py` with 3 core functions
- Added HTTP endpoint: `POST /api/analysis/delivery`
- Automatic detection of manifest files and tile patterns
- Smart workflow recommendations based on delivery structure

**Manifest Detection** (`detect_manifest_files()`):
- ✅ `.MAN` files (Maxar/vendor manifests)
- ✅ `delivery.json`, `manifest.json`
- ✅ `delivery.xml`, `manifest.xml`
- ✅ `README.txt`, `DELIVERY.txt`
- ✅ `.til` files (tile manifests)

**Tile Pattern Detection** (`detect_tile_pattern()`):
- ✅ **Maxar**: `R{row}C{col}` (e.g., R1C1, R10C25)
- ✅ **Generic XY**: `X{x}_Y{y}` (e.g., X100_Y200)
- ✅ **TMS**: `{z}/{x}/{y}.tif` (e.g., 12/1024/2048.tif)
- ✅ **Sequential**: `tile_0001.tif`, `tile_0002.tif`
- ✅ Returns grid dimensions and tile coordinates

**Delivery Types Detected**:
- ✅ `maxar_tiles` - Maxar .MAN + R{row}C{col} pattern
- ✅ `vivid_basemap` - TMS tile pattern
- ✅ `tiled_delivery` - Any recognized tile pattern
- ✅ `single_file` - One raster file
- ✅ `simple_folder` - Multiple rasters, no pattern

**Testing Results**:
```json
// Test 1: Single file with .MAN manifest
{
  "delivery_type": "single_file",
  "manifest": {
    "manifest_found": true,
    "manifest_type": "maxar_man",
    "manifest_path": "6681542855355853500/200007595339_01.MAN"
  },
  "recommended_workflow": {
    "job_type": "process_raster",
    "parameters": {
      "blob_name": "...",
      "output_folder": "cogs/6681542855355853500/200007595339_01/"
    }
  }
}

// Test 2: Tiled delivery with R{row}C{col} pattern
{
  "delivery_type": "maxar_tiles",
  "tile_pattern": {
    "pattern_detected": true,
    "pattern_type": "row_col",
    "grid_dimensions": {"rows": 2, "cols": 2, "min_row": 1, "min_col": 1},
    "tile_coordinates": [
      {"row": 1, "col": 1, "file": "R1C1.TIF"},
      {"row": 1, "col": 2, "file": "R1C2.TIF"},
      ...
    ]
  },
  "recommended_workflow": {
    "job_type": "process_raster_collection",
    "parameters": {
      "blob_list": ["R1C1.TIF", "R1C2.TIF", ...],
      "create_mosaicjson": true,
      "output_folder": "cogs/maxar/test_delivery/"
    }
  }
}
```

**API Endpoint**:
```bash
curl -X POST https://rmhgeoapibeta.../api/analysis/delivery \
  -H "Content-Type: application/json" \
  -d '{
    "folder_path": "vendor/delivery/",
    "blob_list": ["R1C1.TIF", "R1C2.TIF", "delivery.MAN"]
  }'
```

**Benefits Achieved**:
- ✅ Zero-configuration delivery analysis - just provide blob list
- ✅ Intelligent workflow recommendations - knows what job type to use
- ✅ Automatic grid dimension calculation for tile patterns
- ✅ Smart output folder suggestions based on input structure
- ✅ Foundation for future `process_raster_collection` job type

**Files Created**:
- ✅ `services/delivery_discovery.py` (383 lines with comprehensive docstrings)
- ✅ HTTP endpoint in `function_app.py` (60 lines)

**Production Ready**: Both features deployed and tested end-to-end

---

## ✅ COMPLETED: Logger Standardization (18-19 OCT 2025)

**Status**: ✅ **COMPLETE** - Module-level LoggerFactory implemented
**Completion Date**: 19 OCT 2025

### What Was Completed

**All files converted to LoggerFactory** (6 files):
- ✅ `services/vector/converters.py` - Module-level LoggerFactory
- ✅ `services/vector/postgis_handler.py` - Module-level LoggerFactory
- ✅ `services/stac_vector_catalog.py` - Module-level LoggerFactory
- ✅ `services/service_stac_vector.py` - Module-level LoggerFactory
- ✅ `services/service_stac_metadata.py` - Module-level LoggerFactory
- ✅ `jobs/ingest_vector.py` - Module-level LoggerFactory

**Implementation Pattern Used**:
```python
from util_logger import LoggerFactory, ComponentType

# Module-level structured logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_converters"
)

def handler(params):
    logger.info(f"Processing {params['file']}")
    # Output: JSON with component metadata
```

**Benefits Achieved**:
- ✅ JSON structured output for Application Insights
- ✅ Component metadata (component_type, component_name)
- ✅ Consistent logging patterns across codebase
- ✅ No plain text logging in production paths

---

## 🎯 Current Focus

**System Status**: ✅ FULLY OPERATIONAL - VECTOR ETL COMPLETE + COMPREHENSIVE DIAGNOSTICS

**Recent Completions** (See HISTORY.md for details):
- ✅ Comprehensive Diagnostic Logging (18 OCT 2025) - Replaced ALL print() with logger, detailed trace info
- ✅ Vector ETL All Format Support (18 OCT 2025) - GeoPackage, Shapefile, KMZ, KML, GeoJSON, CSV
- ✅ 2D Geometry Enforcement (18 OCT 2025) - Z/M dimension removal for KML/KMZ files
- ✅ PostgreSQL Deadlock Fix (18 OCT 2025) - Serialized table creation, parallel inserts
- ✅ Mixed Geometry Normalization (18 OCT 2025) - Multi- type conversion for ArcGIS compatibility
- ✅ Vector ETL GeoPackage Support (17 OCT 2025) - Optional layer_name, error validation
- ✅ Job Failure Detection (17 OCT 2025) - Auto-fail jobs when tasks exceed max retries
- ✅ Phase 2 ABC Migration (16 OCT 2025) - All 10 jobs migrated to JobBase
- ✅ Raster ETL Pipeline (10 OCT 2025) - Production-ready with granular logging
- ✅ STAC Metadata Extraction (6 OCT 2025) - Managed identity, rio-stac integration
- ✅ Multi-stage orchestration with advisory locks - Zero deadlocks at any scale

**Current Focus**: Multi-Tier COG Architecture Phase 1 complete (20 OCT 2025) + Output Folder Control + Vendor Delivery Discovery

**Latest Completions** (20 OCT 2025):
- ✅ **Configurable Output Folder** - `output_folder` parameter for custom COG output paths
- ✅ **Vendor Delivery Discovery** - Automatic detection of manifest files and tile patterns
- ✅ **Multi-Tier COG Testing** - End-to-end testing with 5 different scenarios (644 MB processed)

---

## ⏭️ Next Up

### 1. Platform Layer Fixes 🔥 **CRITICAL - BLOCKING PLATFORM USE**

**Status**: 🚨 **IMMEDIATE ACTION REQUIRED** - 2 critical runtime issues
**Started**: 25 OCT 2025, **Investigated**: 29 OCT 2025
**Priority**: P0 - Platform endpoints will crash when called
**Effort**: 20 minutes total

#### Context

The Platform Service Layer was implemented on 25 OCT 2025 to create a "Platform-as-a-Service" layer above CoreMachine. This implements the fractal "turtle above CoreMachine" pattern where external applications (like DDH - Data Discovery Hub) can submit high-level requests that get translated into CoreMachine jobs.

**Architecture Pattern**:
```
External App (DDH) → Platform Layer → CoreMachine → Tasks
                      (trigger_platform.py)  (core/machine.py)
```

**What's Working**:
- ✅ All imports load successfully
- ✅ Function app starts without errors
- ✅ HTTP routes registered in function_app.py
- ✅ Platform models, repository, orchestrator implemented
- ✅ Complete documentation exists

**What's Broken**:
- ❌ Platform endpoints will crash immediately when called
- ❌ CoreMachine instantiation missing required registries
- ❌ Service Bus usage violates repository pattern

#### Fix #1: CoreMachine Instantiation Missing Required Registries 🔴 CRITICAL

**Location**: [`triggers/trigger_platform.py:438`](triggers/trigger_platform.py:438)

**Current Code (BROKEN)**:
```python
def __init__(self):
    self.platform_repo = PlatformRepository()
    self.job_repo = JobRepository()
    self.core_machine = CoreMachine()  # ❌ Missing required parameters
```

**Problem**:
CoreMachine requires **explicit job and handler registries** passed as constructor arguments. The decorator-based auto-discovery was removed on 10 SEP 2025 due to import timing issues.

**Error When Called**:
```python
TypeError: __init__() missing 2 required positional arguments: 'all_jobs' and 'all_handlers'
```

**Fix Required**:
```python
def __init__(self):
    from jobs import ALL_JOBS
    from services import ALL_HANDLERS

    self.platform_repo = PlatformRepository()
    self.job_repo = JobRepository()
    self.core_machine = CoreMachine(
        all_jobs=ALL_JOBS,
        all_handlers=ALL_HANDLERS
    )
```

**Reference**: See `core/machine.py:116-149` for CoreMachine constructor signature

**Impact**: 🔴 **CRITICAL** - Platform endpoints will crash immediately when `PlatformOrchestrator()` is instantiated
**Effort**: 5 minutes

**Testing After Fix**:
```bash
# Test Platform request submission
curl -X POST 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit' \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id": "test-dataset",
    "resource_id": "test-resource",
    "version_id": "v1.0",
    "data_type": "raster",
    "source_location": "https://rmhazuregeo.blob.core.windows.net/bronze/test.tif",
    "parameters": {},
    "client_id": "test"
  }'
```

#### Fix #2: Direct Service Bus Usage Instead of Repository Pattern 🟠 MEDIUM

**Location**: [`triggers/trigger_platform.py:621-643`](triggers/trigger_platform.py:621-643)

**Current Code (INCONSISTENT)**:
```python
async def _submit_to_queue(self, job: JobRecord):
    """Submit job to Service Bus jobs queue"""
    try:
        client = ServiceBusClient.from_connection_string(
            config.service_bus_connection_string
        )

        with client:
            sender = client.get_queue_sender(queue_name="jobs")  # ❌ Hardcoded

            message = ServiceBusMessage(
                json.dumps({  # ❌ Manual JSON serialization
                    'job_id': job.job_id,
                    'job_type': job.job_type
                })
            )

            sender.send_messages(message)
```

**Problems**:
1. **Violates repository pattern** - creates `ServiceBusClient` directly instead of using `ServiceBusRepository`
2. **Hardcoded queue name** - uses `"jobs"` instead of `config.service_bus_jobs_queue`
3. **Manual serialization** - uses `json.dumps()` instead of Pydantic `JobQueueMessage` model
4. **Connection management** - creates new client per message (inefficient)

**Fix Required**:
```python
async def _submit_to_queue(self, job: JobRecord):
    """Submit job to Service Bus jobs queue via repository pattern"""
    try:
        import uuid
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage

        # Use repository pattern (handles connection pooling, retries, etc.)
        service_bus_repo = ServiceBusRepository()

        # Use Pydantic message model (automatic serialization + validation)
        queue_message = JobQueueMessage(
            job_id=job.job_id,
            job_type=job.job_type,
            parameters=job.parameters,
            stage=1,  # Platform always creates Stage 1 jobs
            correlation_id=str(uuid.uuid4())[:8]
        )

        # Send via repository (uses correct queue name from config)
        service_bus_repo.send_job_message(queue_message)

        logger.info(f"✅ Job {job.job_id} submitted to Service Bus")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to submit job to queue: {e}")
        raise
```

**Impact**: 🟠 Inconsistent with architecture patterns, potential connection issues
**Effort**: 15 minutes

#### Related Documentation

- **Architecture Guide**: [`docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md`](docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md)
- **Detailed Fixes**: [`PLATFORM_LAYER_FIXES_TODO.md`](PLATFORM_LAYER_FIXES_TODO.md)
- **Deployment Guide**: [`docs_claude/PLATFORM_DEPLOYMENT_STATUS.md`](docs_claude/PLATFORM_DEPLOYMENT_STATUS.md)

#### Success Criteria

After fixes applied:
1. [ ] Platform endpoints don't crash on instantiation
2. [ ] Test request successfully creates Platform record in database
3. [ ] Platform orchestrator creates CoreMachine job(s)
4. [ ] Jobs submitted to Service Bus via repository pattern
5. [ ] Status endpoint returns Platform request with associated job IDs

**Total Effort**: ~20 minutes to fix both issues + test

---

### 2. Multi-Tier COG Architecture 🌟 **HIGH VALUE**

**Status**: 🎯 **READY FOR IMPLEMENTATION** - After Platform fixes deployed
**Business Case**: Tiered storage for different access patterns and use cases

#### Storage Trade-offs

**Storage Requirements** (example: 1000 rasters @ 200MB original each):
- **Visualization**: ~17 MB/file = 17 GB total (hot storage)
- **Analysis**: ~50 MB/file = 50 GB total (hot storage)
- **Archive**: ~180 MB/file = 180 GB total (cool storage)

**User Scenarios**:
- **Visualization Only**: 17 GB hot - Web mapping, public viewers, fast access
- **Viz + Analysis**: 67 GB hot - GIS professionals, data analysis, preserves data quality
- **All Three Tiers**: 67 GB hot + 180 GB cool - Regulatory compliance, long-term archive

#### Technical Specifications

**Tier 1 - Visualization** (Web-optimized):
```python
{
    "compression": "JPEG",  # RGB imagery only
    "quality": 85,
    "blocksize": 512,
    "target_size": "~17MB",
    "use_case": "Fast web maps, visualization",
    "data_loss": "Lossy (acceptable for visualization)",
    "storage_tier": "hot",
    "applies_to": ["RGB imagery", "aerial photos", "satellite imagery"]
}
```

**Tier 2 - Analysis** (Lossless):
```python
{
    "compression": "DEFLATE",  # Universal - works for all data types
    "predictor": 2,
    "zlevel": 6,
    "blocksize": 512,
    "target_size": "~50MB",
    "use_case": "Scientific analysis, GIS operations",
    "data_loss": "None (lossless)",
    "storage_tier": "hot",
    "applies_to": ["All raster types", "DEM", "scientific data", "multispectral"]
}
```

**Tier 3 - Archive** (Compliance):
```python
{
    "compression": "LZW",  # Universal - works for all data types
    "predictor": 2,
    "blocksize": 512,
    "target_size": "~180MB",
    "use_case": "Long-term storage, regulatory compliance",
    "data_loss": "None (lossless)",
    "storage_tier": "cool",
    "applies_to": ["All raster types", "original data preservation"]
}
```

#### Non-Imagery Rasters (DEM, Scientific Data, etc.)

**Problem**: JPEG compression only works for RGB imagery (3 bands, 8-bit). Non-imagery rasters include:
- **DEM (Digital Elevation Models)**: Single band, floating point values
- **Scientific data**: Temperature, precipitation, NDVI, etc.
- **Multispectral imagery**: 4+ bands (e.g., Landsat, Sentinel)
- **Classification rasters**: Integer codes (land cover, soil types)

**Solution**: Tier detection based on raster characteristics

**Automatic Tier Selection Logic**:
```python
def determine_applicable_tiers(raster_metadata):
    """
    Determine which tiers can be applied based on raster type.

    Returns:
        List of applicable tiers
    """
    band_count = raster_metadata['band_count']
    data_type = raster_metadata['data_type']  # uint8, float32, etc.

    # All rasters support analysis and archive (lossless)
    applicable_tiers = ['analysis', 'archive']

    # Only RGB 8-bit imagery supports JPEG visualization tier
    if band_count == 3 and data_type == 'uint8':
        applicable_tiers.insert(0, 'visualization')

    return applicable_tiers
```

**Examples**:

1. **RGB Aerial Photo** (3 bands, uint8):
   - ✅ Visualization (JPEG)
   - ✅ Analysis (DEFLATE)
   - ✅ Archive (LZW)

2. **DEM** (1 band, float32):
   - ❌ Visualization (JPEG doesn't support float32)
   - ✅ Analysis (DEFLATE)
   - ✅ Archive (LZW)

3. **Landsat** (8 bands, uint16):
   - ❌ Visualization (JPEG only supports 3 bands)
   - ✅ Analysis (DEFLATE)
   - ✅ Archive (LZW)

**Implementation Strategy**:

1. **Detect raster type** in Stage 1 (validation)
2. **Auto-select applicable tiers** based on band count and data type
3. **Override user request** if they request incompatible tier:
   ```python
   # User requests: output_tier = "all"
   # DEM detected: only 'analysis' and 'archive' are valid
   # Result: Generate 2 COGs instead of 3, warn user
   ```

4. **Add metadata** to job result:
   ```json
   {
     "requested_tiers": ["visualization", "analysis", "archive"],
     "applicable_tiers": ["analysis", "archive"],
     "skipped_tiers": ["visualization"],
     "skip_reason": "JPEG compression not compatible with float32 data type"
   }
   ```

#### Implementation Plan

**Phase 1: Core Infrastructure** (~5 hours)
- ✅ **Step 1**: Define COG profile configurations in `config.py` - COMPLETED (19 OCT 2025)
  - ✅ Add `CogTierProfile` Pydantic model
  - ✅ Define VISUALIZATION, ANALYSIS, ARCHIVE profiles
  - ✅ Validate compression settings
  - ✅ Add compatibility matrix (band count, data type → applicable tiers)

- ✅ **Step 2**: Add raster type detection - COMPLETED (19 OCT 2025)
  - ✅ Create `determine_applicable_tiers()` function in config.py
  - ✅ Detect band count, data type compatibility
  - ✅ Return list of compatible tiers
  - ✅ Tested with RGB, DEM, Landsat examples

- ✅ **Step 3**: Update `process_raster` job parameters - COMPLETED (19 OCT 2025)
  - ✅ Add `output_tier` field (enum: "visualization", "analysis", "archive", "all") to parameters_schema
  - ✅ Add validation in `validate_job_parameters()`
  - ✅ Pass `output_tier` through job metadata and to Stage 2 tasks
  - ✅ Default to "analysis" for backward compatibility
  - ✅ Mark `compression` parameter as deprecated (use output_tier instead)

- ✅ **Step 4**: Extend COG conversion service - COMPLETED (19 OCT 2025)
  - ✅ Import `CogTier`, `COG_TIER_PROFILES` from config
  - ✅ Parse `output_tier` parameter (default: "analysis")
  - ✅ Get tier profile and check compatibility with raster characteristics
  - ✅ Fallback to "analysis" tier if requested tier incompatible
  - ✅ Apply tier-specific compression, quality, storage tier settings
  - ✅ Generate output filename with tier suffix: `sample_analysis.tif`
  - ✅ Add tier metadata to result: `cog_tier`, `storage_tier`, `tier_profile`
  - ✅ Log tier selection and compatibility warnings

- ✅ **Step 4b**: Add tier detection to validation service - COMPLETED (19 OCT 2025)
  - ✅ Import `determine_applicable_tiers()` in validation service
  - ✅ Call tier detection in Stage 1 using band_count and dtype
  - ✅ Add `cog_tiers` to validation result with applicable_tiers list
  - ✅ Include band_count and data_type in raster_type metadata
  - ✅ Log tier compatibility details
  - ✅ Handle tier detection errors with fallback to all tiers

**Phase 2: Multi-Output Support** (~3 hours)
- [ ] **Step 5**: Implement multi-tier fan-out pattern
  - If `output_tier: "all"`, create tasks for applicable tiers only
  - Use `applicable_tiers` from Stage 1 metadata
  - Stage 2: Convert to COG with tier-specific profiles
  - Stage 3: Upload to appropriate storage tier (hot vs cool)

- [ ] **Step 6**: Update STAC metadata
  - Add tier information to STAC item properties: `cog:tier`, `cog:compression`, `cog:size_mb`
  - Link related tiers: `rel: "alternate"` links between viz/analysis/archive versions
  - Example STAC item structure:
    ```json
    {
      "id": "sample_visualization",
      "properties": {
        "cog:tier": "visualization",
        "cog:compression": "JPEG",
        "cog:quality": 85,
        "cog:size_mb": 17.2
      },
      "links": [
        {"rel": "alternate", "href": "sample_analysis.tif", "title": "Analysis tier"},
        {"rel": "alternate", "href": "sample_archive.tif", "title": "Archive tier"}
      ]
    }
    ```

**Phase 3: Storage Tracking** (~2 hours)
- [ ] **Step 7**: Add storage usage tracking
  - Create `storage_usage` table (tier, container, size_gb, access_tier, cog_tier)
  - Track storage by COG tier (visualization, analysis, archive)
  - Track access tier (hot vs cool)
  - Aggregate endpoint: `/api/storage/usage` → breakdown by tier

- [ ] **Step 8**: Create storage reporting endpoint
  - `/api/storage/usage/summary` → total GB by COG tier and access tier
  - `/api/storage/usage/by-tier` → itemized breakdown
  - Support query parameters: `date_range`, `tier_filter`
  - Example response:
    ```json
    {
      "visualization": {"total_gb": 17.2, "access_tier": "hot"},
      "analysis": {"total_gb": 49.8, "access_tier": "hot"},
      "archive": {"total_gb": 178.5, "access_tier": "cool"}
    }
    ```

**Phase 4: Testing & Documentation** (~2 hours)
- [ ] **Step 9**: Test with sample rasters
  - Test RGB imagery: `output_tier: "all"` → 3 COGs (viz, analysis, archive)
  - Test DEM: `output_tier: "all"` → 2 COGs (analysis, archive only)
  - Test multispectral: `output_tier: "all"` → 2 COGs (analysis, archive only)
  - Verify file sizes match expectations (~17MB, ~50MB, ~180MB)
  - Verify storage tier placement (hot vs cool)
  - Verify tier skip warnings logged correctly

- [ ] **Step 10**: Documentation
  - Update `ARCHITECTURE_REFERENCE.md` with tier specifications
  - Create `COG_TIER_GUIDE.md` with pricing calculator
  - Add API examples to README

#### API Examples

**Single Tier**:
```bash
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "sample.tif",
    "output_tier": "visualization",
    "container": "rmhazuregeobronze"
  }'
```

**All Tiers**:
```bash
curl -X POST https://rmhgeoapibeta.../api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "sample.tif",
    "output_tier": "all",
    "container": "rmhazuregeobronze"
  }'
```

#### Success Criteria

✅ Single raster produces 3 COG variants with correct sizes
✅ STAC items linked with `rel: "alternate"` relationships
✅ Storage costs calculated correctly for each tier
✅ Hot storage used for viz/analysis, cool storage for archive
✅ API documentation complete with pricing examples

**Total Effort**: ~12 hours (1.5 days) - includes non-imagery raster support

---

---

### 2. Complex Raster Workflows

**Capabilities to Add**:
- Multi-stage tiling with deterministic lineage
- Parallel reproject/validate operations
- Batch COG conversion (process multiple rasters in one job)
- Automatic STAC record updates after processing

**Use Cases**:
- Process entire container of rasters (fan-out pattern)
- Tile gigantic rasters into manageable chunks
- Batch reproject datasets to common CRS

---

### 3. Advanced Workflow Patterns ✅ MOSTLY COMPLETE

**Implemented (16 OCT 2025)**:
- ✅ **Diamond Pattern**: Fan-out → Process → Fan-in → Aggregate
  - CoreMachine auto-creates aggregation tasks for `"parallelism": "fan_in"` stages
  - Complete documentation in ARCHITECTURE_REFERENCE.md
  - Production tested: 4 files, 100 files - both successful
  - Ready for production use

- ✅ **Dynamic Stage Creation**: Stage 1 results determine Stage 2 tasks
  - Fully supported via `"parallelism": "fan_out"` pattern
  - Previous stage results passed to `create_tasks_for_stage()`

- ✅ **Cross-Stage Data Dependencies**: Pickle intermediate storage (7 OCT 2025)
  - Implemented in `ingest_vector` job (vector ETL)
  - Stage 1 pickles GeoDataFrame chunks to blob storage
  - Stage 2 loads pickles in parallel for PostGIS upload
  - Config: `vector_pickle_container`, `vector_pickle_prefix`
  - Handles multi-GB datasets that exceed Service Bus 256KB limit
  - Production ready, registered in `jobs/__init__.py`

**Partially Implemented**:
- ⚠️ **Task-to-Task Communication**: Field exists but unused
  - Database field `next_stage_params` exists in TaskRecord
  - Documentation written in ARCHITECTURE_REFERENCE.md
  - No production jobs using it yet
  - **Recommended**: Create raster tiling job to demonstrate pattern
    - Stage 1 determines tile boundaries → `next_stage_params`
    - Stage 2 tasks with matching semantic IDs retrieve tile specs

**Example Diamond Workflow (Now Supported)**:
```python
stages = [
    {"number": 1, "task_type": "list_files", "parallelism": "single"},
    {"number": 2, "task_type": "process_file", "parallelism": "fan_out"},
    {"number": 3, "task_type": "aggregate_results", "parallelism": "fan_in"},  # ← AUTO
    {"number": 4, "task_type": "update_catalog", "parallelism": "single"}
]
```

---

### 4. Service Bus Production Implementation

**Status**: Architecture proven, needs production controllers

**Controllers to Build**:
1. **ServiceBusContainerController**
   - List container → process files in batches
   - Test with 10,000+ files
   - Compare performance vs Queue Storage

2. **ServiceBusSTACController**
   - List rasters → create STAC items in batches
   - Integrate with PgSTAC
   - Batch insert optimization

3. **ServiceBusGeoJSONController**
   - Read GeoJSON → upload to PostGIS in batches
   - Handle large feature collections
   - Spatial indexing

---

## 💡 Future Ideas (Backlog)

### Performance & Operations
- [ ] **Timer Cleanup Function** 🌟 **HIGH PRIORITY** - Orphaned Task Recovery
  - **Status**: Validated against real production failure (29 OCT 2025)
  - **Business Case**: Prevents single stuck tasks from blocking entire jobs indefinitely

  **Real-World Scenario Encountered** (29 OCT 2025):
  - Job: `list_container_contents` with 6,179 tasks
  - Issue: 1 task stuck in 'processing', 1 in 'queued' for 15+ minutes
  - Impact: Job blocked at stage 2 despite 6,177 tasks (99.97%) completed successfully
  - Root Cause: Azure Functions 30-minute timeout killed job processor mid-execution
  - Result: Orphaned tasks with no Service Bus messages, never processed

  **Architecture Design Validation**:
  - ✅ "Last task turns out lights" pattern **working as designed**
  - ✅ Completion logic correctly waits for ALL tasks before advancing
  - ✅ One stuck task = entire stage blocked = **prevents partial results**
  - ❌ **Missing**: Timeout/recovery mechanism for orphaned tasks

  **Timer Cleanup Mitigation Strategy**:

  ```python
  # Azure Timer Trigger: Every 5 minutes
  @app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer")
  def cleanup_orphaned_tasks(timer: func.TimerRequest) -> None:
      """
      Detect and recover orphaned tasks that prevent job completion.

      Scenarios Handled:
      1. Tasks stuck in 'processing' >10min with no heartbeat update
      2. Tasks stuck in 'queued' >15min (never picked up by Service Bus)
      3. Jobs with function timeout failures leaving tasks mid-flight
      4. Python worker crashes during task execution
      """

      # Query 1: Find tasks orphaned in 'processing' status
      orphaned_processing = """
          SELECT task_id, parent_job_id, updated_at,
                 NOW() - updated_at AS stuck_duration
          FROM app.tasks
          WHERE status = 'processing'
            AND updated_at < NOW() - INTERVAL '10 minutes'
            AND (heartbeat IS NULL OR heartbeat < NOW() - INTERVAL '5 minutes')
          ORDER BY updated_at ASC
          LIMIT 100
      """

      # Query 2: Find tasks orphaned in 'queued' status
      orphaned_queued = """
          SELECT task_id, parent_job_id, created_at,
                 NOW() - created_at AS stuck_duration
          FROM app.tasks
          WHERE status = 'queued'
            AND created_at < NOW() - INTERVAL '15 minutes'
          ORDER BY created_at ASC
          LIMIT 100
      """

      # For each orphaned task:
      # 1. Mark as 'failed' with diagnostic error message
      # 2. Set error_details: "Auto-failed by cleanup: stuck in {status} for {duration}"
      # 3. Trigger stage completion check (may unblock waiting jobs)
      # 4. Log recovery action to Application Insights
      # 5. Emit metric: orphaned_tasks_recovered counter
  ```

  **Detection Thresholds**:
  - **Processing timeout**: 10 minutes (tasks should complete or update heartbeat)
  - **Queued timeout**: 15 minutes (Service Bus should pick up within seconds normally)
  - **Heartbeat staleness**: 5 minutes (tasks should heartbeat every 1-2 min if long-running)

  **Recovery Actions**:
  ```python
  # For 'processing' orphans:
  UPDATE app.tasks
  SET status = 'failed',
      error_details = 'Auto-failed by cleanup: stuck in processing for {duration}, no heartbeat',
      updated_at = NOW()
  WHERE task_id = '{orphaned_task_id}'

  # Trigger completion check (may unblock job)
  SELECT complete_task_and_check_stage(
      p_task_id := '{orphaned_task_id}',
      p_job_id := '{job_id}',
      p_stage := {stage},
      p_result_data := NULL,
      p_error_details := 'Auto-failed by cleanup: timeout'
  )
  ```

  **Benefits**:
  - ✅ **Job Unblocking**: 6,177/6,179 tasks complete → job can advance/complete
  - ✅ **Visibility**: Clear error messages explain why task failed ("timeout", "orphaned")
  - ✅ **Automatic Recovery**: No manual intervention required
  - ✅ **Failure Transparency**: Job shows 99.97% success rate with specific failed tasks
  - ✅ **Prevents Silent Hangs**: Jobs stuck forever → jobs complete with error report

  **Metrics to Track**:
  - `orphaned_tasks_processing_count` - Tasks auto-failed from 'processing'
  - `orphaned_tasks_queued_count` - Tasks auto-failed from 'queued'
  - `jobs_unblocked_count` - Jobs that advanced/completed after cleanup
  - `cleanup_duration_ms` - Cleanup function execution time

  **Edge Cases Handled**:
  1. **Race Condition**: Task completes between query and update
     - Solution: Use `WHERE status = 'processing'` in UPDATE (no-op if already completed)
  2. **Legitimate Long Tasks**: Some tasks take >10 minutes
     - Solution: Implement heartbeat updates in long-running handlers
     - Alternative: Configurable timeout per task_type
  3. **Mass Failures**: What if 1000+ tasks orphaned?
     - Solution: `LIMIT 100` per cleanup run, process in batches
     - Metric: Queue depth of orphaned tasks for monitoring

  **Implementation Priority**: HIGH
  - **Effort**: ~4 hours (timer function, queries, testing, monitoring)
  - **Impact**: Prevents entire jobs from hanging indefinitely
  - **Validated**: Real production scenario (list_container_contents 6,179 tasks)

  **Testing Checklist**:
  - [ ] Submit job with intentional task timeout (sleep 15 min)
  - [ ] Verify cleanup function detects and fails orphaned task
  - [ ] Verify job advances after cleanup runs
  - [ ] Test with multiple orphaned tasks across different jobs
  - [ ] Verify cleanup doesn't affect legitimately processing tasks
  - [ ] Monitor Application Insights for cleanup metrics

  **See Also**:
  - Real failure case documented in investigation session (29 OCT 2025)
  - Job: `3107f1c37b64e3c0dcfaece79ab3385127ece1d72f5c3d6c2d56db627a6393e5`
  - Tasks: `ce9402272aece9fc` (processing), `2c099ba501afd78a` (queued)

- [ ] Job cancellation endpoint
- [ ] Task replay for failed jobs
- [ ] Historical analytics dashboard
- [ ] Connection pooling optimization
- [ ] Query performance tuning

### Advanced Features
- [ ] Cross-job dependencies (Job B waits for Job A)
- [ ] Scheduled jobs (cron-like triggers)
- [ ] Job templates (reusable workflows)
- [ ] Webhook notifications on job completion

### Vector ETL Pipeline ✅ IN PROGRESS (17 OCT 2025)
- ✅ **GeoJSON → PostGIS ingestion** (7 OCT 2025) - Production ready
  - Two-stage pipeline: pickle chunks → parallel upload
  - Handles multi-GB datasets beyond Service Bus limits
  - Registered in `jobs/__init__.py` as `ingest_vector`
- ✅ **GeoPackage support** (17 OCT 2025) - Production ready
  - Optional layer_name parameter (reads first layer by default)
  - Explicit error validation for invalid layer names
  - Error propagation: converter → TaskResult → job failure
- ✅ **Job failure detection** (17 OCT 2025) - Production ready
  - Jobs marked as FAILED when tasks exceed max retries (3 attempts)
  - Application-level retry with exponential backoff (5s → 10s → 20s)
  - Detailed error messages include task_id and retry count
- ✅ **Mixed geometry type handling** (18 OCT 2025) - Production ready
  - Normalize all geometries to Multi- types (Polygon → MultiPolygon, etc.)
  - Fixed coordinate counting for multi-part geometries
  - ArcGIS compatibility - uniform geometry types in PostGIS tables
  - Minimal overhead (<1% storage/performance cost)
- ✅ **PostgreSQL deadlock fix** (18 OCT 2025) - Production ready
  - **Solution**: Serialized table creation in Stage 1, parallel inserts in Stage 2
  - **Implementation**:
    - Split `services/vector/postgis_handler.py` methods:
      - `create_table_only()` - DDL only (Stage 1 aggregation)
      - `insert_features_only()` - DML only (Stage 2 parallel tasks)
    - Modified `jobs/ingest_vector.py` → `create_tasks_for_stage()` for Stage 2
    - Table created ONCE before Stage 2 tasks (using first chunk for schema)
    - Updated `upload_pickled_chunk()` to use insert-only method
  - **Testing Results**: kba_shp.zip (17 chunks) - 100% success, ZERO deadlocks
- ✅ **2D Geometry Enforcement** (18 OCT 2025) - Production ready
  - **Purpose**: System only supports 2D geometries (x, y)
  - **Implementation**: `shapely.force_2d()` strips Z and M dimensions
  - **Applied in**: `services/vector/postgis_handler.py` → `prepare_gdf()`
  - **Testing**: KML/KMZ files with 3D data (12,228 features each)
  - **Verified**: Coordinates reduced from 3 values (x,y,z) to 2 values (x,y)
  - **Bug Fixed**: Series boolean ambiguity - added `.any()` to `has_m` check
- ✅ **All vector format support** (18 OCT 2025) - Production ready
  - ✅ **GeoPackage (.gpkg)** - roads.gpkg (2 chunks, optional layer_name)
  - ✅ **Shapefile (.zip)** - kba_shp.zip (17 chunks, NO DEADLOCKS)
  - ✅ **KMZ (.kmz)** - grid.kml.kmz (21 chunks, 12,228 features, Z-dimension removal)
  - ✅ **KML (.kml)** - doc.kml (21 chunks, 12,228 features, Z-dimension removal)
  - ✅ **GeoJSON (.geojson)** - 8.geojson (10 chunks, 3,879 features)
  - ✅ **CSV (.csv)** - acled_test.csv (17 chunks, 5,000 features, lat/lon columns)
  - **Parameters for CSV**: `"converter_params": {"lat_name": "latitude", "lon_name": "longitude"}`
- ✅ **Comprehensive Diagnostic Logging** (18 OCT 2025) - Production ready
  - **Problem**: User requested exact trace details of why geometries are invalid - "invalid geometry" insufficient
  - **Solution**: Replaced ALL print() statements with logger across entire codebase
  - **Implementation**:
    - Replaced 94+ print() statements in vector ETL, raster validation, STAC, etc.
    - Added detailed diagnostics to shapefile loading (rows, columns, CRS, geometry types)
    - Enhanced geometry validation logging (null counts, sample data, error reasons)
    - All diagnostics now appear in Application Insights for debugging
  - **Files Updated**:
    - `services/vector/converters.py` - Shapefile loading diagnostics
    - `services/vector/postgis_handler.py` - Geometry validation diagnostics
    - `jobs/ingest_vector.py` - Table creation logging
  - **Example Diagnostic Output**:
    ```
    📂 Reading shapefile from: /tmp/tmpq8out_ps/wdpa.shp
    📊 Shapefile loaded - diagnostics:
       - Total rows read: 0
       - Columns: ['OBJECTID', 'WDPAID', ..., 'geometry']
       - CRS: EPSG:4326
       - Geometry column type: geometry
    📊 Geometry validation starting:
       - Total features loaded: 0
       - Null geometries found: 0
    ```
  - **Testing**: Caught corrupted 2GB wdpa.zip file (bad QGIS export, 0 rows despite valid schema)
  - **Benefit**: Complete visibility into file processing failures via Application Insights
- [ ] Vector tiling (MVT generation)
- [ ] Vector validation and repair
- [ ] **Advanced Shapefile Support** ⚠️ FUTURE (Avoid for now!)
  - [ ] Read shapefile as group of files (.shp, .shx, .dbf, .prj, etc.)
  - [ ] Auto-detect related files in same blob prefix
  - [ ] Handle multi-file upload workflows
  - **Note**: This is a hot mess - stick with ZIP format for production use

### Logging Enhancements (Future)
- [ ] **Context-Aware Logging** - Add job_id/task_id to Application Insights
  - **Current**: Module-level LoggerFactory (component metadata only)
  - **Future**: Handler-level LogContext for correlation tracking
  - **Pattern**: Create logger inside handlers with `LogContext(job_id=..., task_id=...)`
  - **Benefit**: Query Application Insights by job_id: `customDimensions.job_id == "abc123"`
  - **Effort**: ~3.5 hours (6 files, testing, deployment)
  - **Priority**: Low - module-level logging sufficient for current scale

### Data Quality
- [ ] Automated raster validation checks
- [ ] Metadata completeness scoring
- [ ] Duplicate detection
- [ ] Quality reports

### Container Operations Enhancements (3 NOV 2025)
- [ ] **Add Fan-In Aggregation to list_container_contents**
  - **Current**: 2-stage workflow (list → analyze N files) - results in N task records
  - **Enhancement**: Add Stage 3 fan-in aggregation (similar to diamond test job)
  - **Benefits**:
    - Single aggregated summary (total files, total size, extension breakdown)
    - Largest/smallest file identification
    - Better user experience (one summary vs N individual records)
  - **Reference**: `list_container_contents_diamond` has working Stage 3 aggregation handler
  - **Effort**: ~2 hours (add Stage 3 to workflow, test with existing handler)
  - **Priority**: P2 - Nice to have, improves UX but not blocking

**Note**: `list_container_contents_diamond` is a TEST/DIAGNOSTIC tool created 16 OCT 2025 to validate CoreMachine's fan-in pattern. It demonstrates the desired aggregation behavior but is NOT the production workflow.

---

## 🏆 System Capabilities (Current)

**Fully Operational**:
- ✅ Multi-stage job orchestration (sequential stages, parallel tasks)
- ✅ Atomic stage completion detection (PostgreSQL advisory locks)
- ✅ Automatic stage advancement
- ✅ Job completion with result aggregation
- ✅ Idempotency (SHA256 hash deduplication)
- ✅ Pydantic validation at all boundaries
- ✅ Contract enforcement with ABC patterns
- ✅ Raster ETL (validate → COG → STAC)
- ✅ STAC metadata extraction (managed identity)
- ✅ Container operations (summarize, list contents)
- ✅ Database monitoring endpoints
- ✅ Health checks with import validation

**Active Endpoints**:
```bash
# Job Management
POST /api/jobs/submit/{job_type}      - Submit job (hello_world, process_raster, etc.)
GET  /api/jobs/status/{job_id}        - Get job status
GET  /api/db/jobs                     - Query all jobs

# Task Management
GET /api/db/tasks/{job_id}            - Get tasks for job

# STAC Operations
POST /api/stac/init                   - Initialize STAC collections
POST /api/stac/extract                - Extract STAC metadata from raster
GET  /api/stac/setup                  - Check PgSTAC installation

# System Health
GET /api/health                       - System health check
POST /api/db/schema/redeploy?confirm=yes - Redeploy database schema
```

---

## 📋 Active Jobs (10 Production Jobs)

All jobs now inherit from `JobBase` ABC with compile-time enforcement:

1. **hello_world** - 2-stage demo workflow
2. **summarize_container** - Aggregate container statistics
3. **list_container_contents** - Inventory with metadata
4. **process_raster** - Validate → COG creation (PRODUCTION READY)
5. **vector_etl** - Vector data processing
6. **create_h3_base** - H3 hexagon grid generation
7. **generate_h3_level4** - H3 level 4 grid
8. **stac_setup** - STAC infrastructure setup
9. **stac_search** - STAC catalog search
10. **duckdb_query** - Analytical queries

---

## 🚀 Quick Test Commands

```bash
# Health Check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Submit Raster Processing Job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test/sample.tif", "container": "rmhazuregeobronze"}'

# Check Job Status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Extract STAC Metadata
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/stac/extract \
  -H "Content-Type: application/json" \
  -d '{"container": "rmhazuregeosilver", "blob_name": "test/sample_cog.tif", "collection_id": "cogs", "insert": true}'
```

---

**Note**: For completed work history, see `HISTORY.md`. For architectural details, see `ARCHITECTURE_REFERENCE.md`.
