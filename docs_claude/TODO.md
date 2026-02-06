# Working Backlog
**This file contains high level items only**
This file references other documents containing implementation details. This is to avoid a 50,000 line TODO.md. This file should not exceed 500 lines.

**Last Updated**: 06 FEB 2026
**Source of Truth**: [ado_wiki/V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md) - Epic/Feature/Story definitions
**Purpose**: Sprint-level task tracking and delegation (INDEX format)

---

## Quick Navigation

| Document | Purpose |
|----------|---------|
| [ENVIRONMENT_VARIABLES.md](./ENVIRONMENT_VARIABLES.md) | **All env vars reference (42 validated)** |
| [RASTER_RESULT_MODELS.md](./RASTER_RESULT_MODELS.md) | F7.21 Raster result type safety |
| [DOCKER_UI_GAPS.md](./DOCKER_UI_GAPS.md) | Docker UI gap tracking (V0.8 testing) |
| [V0.8_TESTING_PLAN.md](./V0.8_TESTING_PLAN.md) | V0.8 comprehensive testing (68 tests) |
| [COMPLETED_JAN2026.md](./COMPLETED_JAN2026.md) | Completed features (Jan 2026) |
| [COREMACHINE_GAPS.md](./COREMACHINE_GAPS.md) | CoreMachine gap analysis & job_events |
| [APPROVAL_WORKFLOW.md](./APPROVAL_WORKFLOW.md) | F4.AP approval system details |
| [RASTER_METADATA.md](./RASTER_METADATA.md) | F7.9 RasterMetadata architecture |
| [CLASSIFICATION_ENFORCEMENT.md](./CLASSIFICATION_ENFORCEMENT.md) | E4 access_level enforcement |
| [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md) | F7.18 framework, F7.15 HTTP-trigger |
| [/UI_MIGRATION.md](/UI_MIGRATION.md) | UI migration to Jinja2/Docker |
| [HISTORY.md](./HISTORY.md) | Completed work log |
| [REFACTOR_TRIGGER_PLATFORM.md](./REFACTOR_TRIGGER_PLATFORM.md) | trigger_platform.py split plan |
| [/V0.8_COPY.md](/V0.8_COPY.md) | AzCopy integration for 5-10x faster blob transfers |
| [/V0.8_DAG_READINESS.md](/V0.8_DAG_READINESS.md) | DAG orchestration readiness assessment (Epoch 5 prep) |
| [/V0.8_DDH_MIGRATION.md](/V0.8_DDH_MIGRATION.md) | **DDH column removal - platform_refs migration** |
| [DRY_RUN_IMPLEMENTATION.md](./DRY_RUN_IMPLEMENTATION.md) | **Platform Submit dry_run + previous_version_id (V0.8.4)** |
| [SERVICE_LAYER_CLIENT.md](./SERVICE_LAYER_CLIENT.md) | **TiPG refresh webhook integration (F1.6)** |
| [APP_MODE_ENDPOINT_REFACTOR.md](./APP_MODE_ENDPOINT_REFACTOR.md) | **APP_MODE endpoint restrictions (F12.11)** |
| [B2B_REQUEST_CONTEXT.md](./B2B_REQUEST_CONTEXT.md) | **B2B request context tracking (F12.12)** |

---

## Active Work

### APP_MODE Endpoint Refactor (F12.11)
**Status**: IN PROGRESS
**Priority**: HIGH - Security/Architecture
**Details**: [APP_MODE_ENDPOINT_REFACTOR.md](./APP_MODE_ENDPOINT_REFACTOR.md)

**Goal**: Restrict endpoints per APP_MODE so each deployment only exposes intended endpoints.

**APP_MODE=platform (Gateway) should only expose:**
- `/api/livez`, `/api/readyz`, `/api/health` - Health probes
- `/api/platform/*` - Platform API (B2B)
- `/api/interface/*` - Web UI (calls platform API)

**Current Progress:**
- [x] Gateway deployed and healthy (rmhgeogateway)
- [x] Implementation plan documented
- [x] Phase 1: Add `has_*_endpoints` properties to app_mode_config.py (05 FEB 2026)
- [x] Phase 2: Three-tier health endpoints (05 FEB 2026)
  - `/api/health` - Instance health (triggers/probes.py, all modes)
  - `/api/platform/health` - B2B system health (existing, unchanged)
  - `/api/system-health` - Infrastructure admin (triggers/system_health.py, orchestrator only)
- [x] Phase 2b: Docker worker always checked in system-health (06 FEB 2026)
- [ ] Phase 3: Wrap endpoint registration with mode checks
- [ ] Phase 4: Deploy and test on rmhgeogateway
- [ ] Phase 5: Apply to other APP_MODEs

---

### B2B Request Context Tracking (F12.12)
**Status**: PLANNED
**Priority**: MEDIUM - B2B attribution and audit
**Details**: [B2B_REQUEST_CONTEXT.md](./B2B_REQUEST_CONTEXT.md)
**Created**: 06 FEB 2026

**Problem**: Cannot identify which B2B client submitted platform/submit requests. Need to distinguish DDH from internal UIs (Orchestrator vs Gateway) for audit trail.

**Design Decisions:**
- No API keys/tokens - identity-based auth only
- Primary: Azure AD token `appid` claim (zero effort from DDH)
- Fallback: `User-Agent` header pattern matching
- Storage: Explicit columns on `api_requests` + JSONB overflow

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Extend `ApiRequest` model with new fields | Pending |
| Phase 2 | Create `services/request_context.py` extractor | Pending |
| Phase 3 | Wire to platform/submit endpoint | Pending |
| Phase 4 | Wire to platform/validate endpoint | Pending |
| Phase 5 | Update internal UI User-Agents | Pending |
| Phase 6 | Database migration (action=ensure) | Pending |
| Phase 7 | Documentation updates | Pending |

**Internal Clients to Register:**
| Client ID | Display Name | User-Agent Pattern |
|-----------|--------------|-------------------|
| `rmh_orchestrator_ui` | Orchestrator Admin UI | `RMH-Orchestrator-UI/*` |
| `rmh_gateway_ui` | Gateway Platform UI | `RMH-Gateway-UI/*` |
| `ddh` | Data Distribution Hub | DDH's agent or Azure AD appid |

**Files to create:**
- `services/request_context.py` - Context extraction helper

**Files to modify:**
- `core/models/platform.py` - Add fields to ApiRequest
- `triggers/platform/submit.py` - Call extractor
- `triggers/trigger_platform_status.py` - Wire to validate
- `static/js/*.js` or base template - Set User-Agent headers

---

## Code Legibility / Technical Debt

### Refactor trigger_platform.py (F12.10)
**Status**: PLANNED
**Priority**: MEDIUM - Code maintainability
**Details**: [REFACTOR_TRIGGER_PLATFORM.md](./REFACTOR_TRIGGER_PLATFORM.md)

**Problem**: `triggers/trigger_platform.py` has grown to 2,414 lines with mixed responsibilities (HTTP handlers, translation logic, job submission, deprecated code).

| Phase | Description | Effort |
|-------|-------------|--------|
| Phase 0 | Decision: Delete deprecated endpoints | 5 min |
| Phase 1 | Extract translation/submission to `services/` | 2-3 hrs |
| Phase 2 | Split HTTP handlers into `triggers/platform/` | 2-3 hrs |
| Phase 3 | Delete deprecated unpublish endpoints | 30 min |
| Phase 4 | Response builder pattern (optional) | 1 hr |

**Benefits**:
- Reduce main file from 2,414 → ~50 lines (re-exports only)
- Unit testable translation logic in `services/`
- Remove 375 lines of deprecated code
- Single-responsibility modules

---

## Testing Needed

- [ ] **Test Approval Workflow** - Submit job, verify approval record created, approve via API
- [ ] **Test Artifact/Revision Workflow** - Submit with same DDH identifiers, verify revision increments
- [ ] **Test External Service Registry** - `/api/jobs/services/register`, list, health check

### Geo Schema Emergency Management (MEDIUM PRIORITY)
**Status**: ✅ DONE (30 JAN 2026)
**Priority**: MEDIUM - Testing/DEV enhancement for V0.8 validation
**Pattern**: NOT for production - emergency override for dev/QA only

**Endpoint**: `POST /api/dbadmin/maintenance?action=nuke_geo&confirm=yes`

Cascade deletes ALL user tables in geo schema:
1. Deletes STAC items from pgstac.items
2. Truncates geo.table_catalog
3. Truncates app.vector_etl_tracking
4. Drops all user tables (preserves system tables)

**Preserved system tables**: `table_catalog`, `table_metadata`, `feature_collection_styles`

**Reference**: Single-table endpoint also available: `POST /api/dbadmin/geo?action=unpublish&table_name={name}&confirm=yes`

---

## Active Work

### Geo Schema Table Name Validation (F1.7) - CRITICAL
**Status**: ✅ COMPLETE (04 FEB 2026)
**Priority**: CRITICAL - PostgreSQL identifier requirement
**Created**: 04 FEB 2026

**Problem**: PostgreSQL identifiers (table names) must begin with a letter or underscore. If a vector ETL job receives parameters that produce a table name starting with a number (e.g., `2024_flood_data`), the table creation will fail or require quoting, which breaks TiPG/OGC Features discovery.

**Solution**: Added numeric prefix check to `_slugify_for_postgres()` in `config/platform_config.py`.

| Rule | Example Input | Output |
|------|---------------|--------|
| Starts with letter | `flood_data` | `flood_data` (unchanged) |
| Starts with number | `2024_flood_data` | `t_2024_flood_data` |
| Starts with number | `123abc` | `t_123abc` |

**Fix applied**: `config/platform_config.py:469` - `_slugify_for_postgres()`
```python
# PostgreSQL identifiers must begin with a letter or underscore (04 FEB 2026)
if slug and slug[0].isdigit():
    slug = f"t_{slug}"
```

**Why this location**: This function is the single sanitization point for ALL table names generated from platform/submit. No need for separate validation - it's already in the critical path.

---

### Raster Result Type Safety (F7.21) - CRITICAL
**Status**: ✅ PHASE 1-2 COMPLETE - Core models + service wiring done
**Details**: [RASTER_RESULT_MODELS.md](./RASTER_RESULT_MODELS.md)
**Priority**: CRITICAL - Blocks reliable checkpoint/resume, prevents silent failures

**Problem**: Docker raster workflow passes complex dicts between database, Python, and Service Bus with NO Pydantic models. Vector workflow has `ProcessVectorStage1Data` - raster has nothing.

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Core result models (Validation, COG, STAC) | ✅ DONE |
| Phase 2 | Wiring to services (validate, cog, stac) | ✅ DONE |
| Phase 3 | Tiling result models | Future |
| Phase 4 | Checkpoint data model | Future |

**Deliverables**:
- [x] Create `core/models/raster_results.py` with 12 Pydantic models (25 JAN)
- [x] Update `validate_raster()` to return typed result (25 JAN)
- [x] Update `create_cog()` to return typed result (25 JAN)
- [x] Update `extract_stac_metadata()` to return typed result (25 JAN)
- [x] Update handler imports for typed results (25 JAN)
- [ ] Update checkpoint save/load for type safety (Future)
- [ ] Update `finalize_job()` to validate input (Future)

---

### Platform Submit dry_run Implementation (V0.8.4)
**Status**: IN PROGRESS
**Priority**: CRITICAL - Blocks V0.8 Release Control validation
**Details**: [DRY_RUN_IMPLEMENTATION.md](./DRY_RUN_IMPLEMENTATION.md)
**Created**: 31 JAN 2026

**Problem**: No pre-flight validation for platform/submit. Also need `previous_version_id` validation to prevent version race conditions.

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Add `previous_version_id` to PlatformRequest model | Pending |
| Phase 2 | Create `validate_version_lineage()` helper | Pending |
| Phase 3 | Add `?dry_run=true` to submit endpoint | Pending |
| Phase 4 | Update/consolidate validate endpoint | Pending |
| Phase 5 | Add dry_run tests to V0.8_TESTING.md | Pending |

**Files to modify**:
- `core/models/platform.py` - Add `previous_version_id` field
- `services/platform_validation.py` - NEW validation helper
- `triggers/platform/submit.py` - Add dry_run logic

**Related**: V0.8_RELEASE_CONTROL.md, V0.8_TESTING.md (Part 4)

---

### TiPG Collection Refresh Integration (F1.6)
**Status**: PLANNED
**Priority**: MEDIUM - Enables immediate TiPG visibility after vector ETL
**Details**: [SERVICE_LAYER_CLIENT.md](./SERVICE_LAYER_CLIENT.md)
**Created**: 04 FEB 2026
**Prerequisite**: ✅ F1.7 (Geo Schema Table Name Validation) - DONE

**Problem**: After vector ETL creates a PostGIS table, TiPG doesn't immediately see the new collection (cached). The Service Layer has a webhook (`POST /admin/refresh-collections`) but the ETL app doesn't call it.

**Solution**: Create `ServiceLayerClient` repository to call the webhook after vector table creation.

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Create `core/models/service_layer.py` models | Pending |
| Phase 2 | Create `infrastructure/service_layer_client.py` | Pending |
| Phase 3 | Add `SERVICE_LAYER_TOKEN_SCOPE` to config | Pending |
| Phase 4 | Wire to `handler_vector_docker_complete.py` | Pending |
| Phase 5 | Documentation updates | Pending |

**Files to create**:
- `core/models/service_layer.py` - Pydantic models (CollectionRefreshResponse)
- `infrastructure/service_layer_client.py` - HTTP client with Azure AD auth

**Files to modify**:
- `config/app_config.py` - Add `service_layer_token_scope`
- `services/handler_vector_docker_complete.py` - Call refresh after table creation

**Testing**: Manual webhook test first, then integration test with full ETL job.

**Effort**: ~1.5 hours implementation + Azure AD config (if needed)

---

### Vector Revision Tracking (F7.23)
**Status**: PLANNED
**Priority**: MEDIUM - Enables audit trail for vector overwrites
**Created**: 29 JAN 2026

**Problem**: Vector ETL overwrites work (table drop + recreate) but there's no revision tracking. The existing `app.artifacts` table is blob-centric (storage_account, container, blob_path) and doesn't fit PostGIS tables.

**Solution**: Create separate `app.vector_revisions` table with vector-specific fields.

| Field | Purpose |
|-------|---------|
| `schema_name`, `table_name` | PostGIS location (vs blob path) |
| `row_count` | Size metric (vs size_bytes) |
| `geometry_type`, `srid` | Vector-specific metadata |
| `columns` | Column names + types (JSONB) |
| `revision` | Monotonic revision number |
| `supersedes`, `superseded_by` | Revision chain |
| `client_type`, `client_refs` | DDH passthrough |
| `source_job_id` | Job linkage |

**Implementation**:

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Create `app.vector_revisions` table + enum | Pending |
| Phase 2 | Create `VectorRevisionRepository` | Pending |
| Phase 3 | Create `VectorRevisionService` | Pending |
| Phase 4 | Wire to `handler_vector_docker_complete.py` | Pending |
| Phase 5 | Add revision info to job result | Pending |

**Files to create**:
- `core/models/vector_revision.py` - Pydantic model
- `infrastructure/vector_revision_repository.py` - Repository
- `services/vector_revision_service.py` - Service with supersession logic

**Files to modify**:
- `infrastructure/iac/ddl_*.py` - Add table DDL
- `services/handler_vector_docker_complete.py` - Call service on completion

---

### Vector STAC ID Mismatch Bug (V0.8 CRITICAL)
**Status**: ✅ FIXED (31 JAN 2026) - Version 0.8.3.4 (previous fix was incomplete)
**Priority**: CRITICAL - Breaks GeospatialAsset ↔ STAC linkage
**Discovered**: 30 JAN 2026

**Problem**: Vector ETL creates STAC items with one ID format but GeospatialAsset stores a different ID format, breaking the link between them.

| Location | STAC Item ID Format | Example |
|----------|---------------------|---------|
| `pgstac.items` (actual) | `postgis-{schema}-{table}` | `postgis-geo-blessed_hexagons_v8_testing_v10` |
| `app.geospatial_assets` (expected) | `{dataset_id}-{resource_id}-{version_id}` | `blessed-hexagons-v8-testing-v10` |

**Root Cause**: Two different ID generation strategies:
1. `create_vector_stac()` in `services/vector_stac.py` uses `postgis-{schema}-{table}` format
2. `handler_vector_docker_complete.py` passes `stac_item_id` from job params which uses DDH format

**Also Missing**: STAC item properties don't include `platform:dataset_id`, `platform:resource_id`, `platform:version_id` - these should be added for B2B discoverability.

**Fix Options**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A | Change `create_vector_stac()` to use DDH format | Aligns with GeospatialAsset | Breaking change for existing items |
| B | Change GeospatialAsset to use postgis format | No STAC changes | Loses DDH semantic meaning |
| **C (Recommended)** | Pass explicit `item_id` to `create_vector_stac()` | Handler controls ID, backward compatible | Minor code change |

**Recommended Fix (Option C)**:
1. Modify `create_vector_stac()` to accept optional `item_id` parameter
2. If provided, use it; if not, fall back to `postgis-{schema}-{table}` format
3. Add `platform:*` properties to STAC item from job params
4. Handler passes DDH-format `stac_item_id` from job params

**Files to modify**:
- `services/vector_stac.py` - Accept `item_id` param, add platform properties
- `services/handler_vector_docker_complete.py` - Pass `stac_item_id` to create_vector_stac

**Verification**:
```sql
-- After fix, these should match:
SELECT stac_item_id FROM app.geospatial_assets WHERE table_name = 'X';
SELECT id FROM pgstac.items WHERE content->'properties'->>'postgis:table' = 'X';
```

---

### CoreMachine Gap Analysis (E7)
**Status**: ✅ COMPLETE - All gaps fixed, events table + UI done
**Details**: [COREMACHINE_GAPS.md](./COREMACHINE_GAPS.md)

| Story | Status |
|-------|--------|
| GAP-3: Check mark_job_failed return | Done |
| GAP-4: Handle task_record None | Done |
| GAP-7: Checkpoint for callback failure | Done |
| GAP-2: Stage advancement checkpoint | Done |
| Story 5: Create app.job_events table | Done |
| Story 6: Execution Timeline UI | Done |

---

### UI Migration to Docker/Jinja2
**Status**: Phase 3 V0.8 Testing Gaps COMPLETE
**Details**: [/UI_MIGRATION.md](/UI_MIGRATION.md)

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Foundation (base.html, static files) | Done |
| Phase 2 | Core Routes (home, health, jobs, tasks, collections, submit) | Done |
| Phase 3 | V0.8 Testing Gaps (Raster/Vector Viewers, Logs, Queue Status) | Done (25 JAN) |
| Phases 4+ | Advanced interfaces (submit workflows, etc.) | Future |

---

### Docker UI V0.8 Testing Gaps (E12)
**Status**: ✅ HIGH-PRIORITY GAPS COMPLETE
**Details**: [DOCKER_UI_GAPS.md](./DOCKER_UI_GAPS.md)
**Priority**: HIGH - Enables V0.8 UI-based testing

| Gap | Description | Status |
|-----|-------------|--------|
| GAP-01 | Cross-System Health (FA + Docker) | ✅ DONE |
| GAP-02 | Queue Infrastructure Visibility | ✅ DONE |
| GAP-03 | Log Viewing | ✅ DONE |
| GAP-04 | Raster Curator Interface | ✅ DONE |
| GAP-04b | Vector Curator Interface | ✅ DONE |
| **GAP-05** | Standalone Storage Browser | **Future** |
| GAP-06 | API Response Verification | Future |

**Current Focus**: All high-priority gaps complete (GAP-01 through GAP-04b). Remaining gaps are low priority.

---

### Dataset Approval System (F4.AP)
**Status**: ✅ Phase 2 COMPLETE - UI integration done
**Details**: [APPROVAL_WORKFLOW.md](./APPROVAL_WORKFLOW.md)

| Story | Status |
|-------|--------|
| Core infrastructure (models, repo, service) | Done |
| HTTP endpoints (`/api/approvals/*`) | Done |
| Job completion hook | Done (22 JAN) |
| Viewer UI buttons (Raster + Vector Curator) | Done (25 JAN) |
| ADF integration for public data | Pending |

---

### RasterMetadata + STAC Self-Healing (F7.9 + F7.11)
**Status**: ✅ COMPLETE (31 JAN 2026)
**Details**: [RASTER_METADATA.md](./RASTER_METADATA.md)
**Priority**: CRITICAL - Raster is primary STAC use case

| Story | Status |
|-------|--------|
| RasterMetadata class + DDL | Done |
| RasterMetadataRepository | Done |
| Wire to extract_stac_metadata | Done |
| Enable raster rebuild | Done |
| Test: process_raster_docker populates cog_metadata | Done |

**Verified**: Job `eb8bb38b...` confirmed `app.cog_metadata` populated with correct STAC IDs.
**Minor gap**: `etl_job_id` column not populated (non-blocking).

---

### Job Version Tracking (F7.22)
**Status**: PLANNED
**Details**: [V0.8_PLAN.md Section 19](/V0.8_PLAN.md#19-job-version-tracking-f722)
**Priority**: MEDIUM - Enables audit trail for job processing versions

**Problem**: App version (`__version__`) is not captured in job execution metadata. When debugging or auditing historical jobs, there's no way to know which app version processed the job.

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Capture version at job creation | Pending |
| Phase 2 | Preserve version history on resubmit | Pending |
| Phase 3 | Expose metadata in job status API | Pending |

**Files to modify**:
- `jobs/mixins.py` - Add `app_version` to metadata
- `triggers/jobs/resubmit.py` - Preserve original version, build history
- `triggers/get_job_status.py` - Expose metadata in response

---

### Docker Orchestration Framework (F7.18)
**Status**: Phases 1-4 COMPLETE
**Details**: [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md)

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Connection Pool Manager | Done |
| Phase 2 | Checkpoint Integration | Done |
| Phase 3 | Docker Task Context | Done |
| Phase 4 | Graceful Shutdown | Done |
| Phase 5 | H3 Bootstrap Docker | Pending |
| Phase 6 | Migrate process_raster_docker | Done |
| Phase 7 | Documentation | Pending |

---

### Classification Enforcement (E4)
**Status**: Phase 0 + Phase 1 COMPLETE
**Details**: [CLASSIFICATION_ENFORCEMENT.md](./CLASSIFICATION_ENFORCEMENT.md)
**Priority**: HIGH - Blocks type-safe approval workflow

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Data Model Unification (unified to AccessLevel enum) | ✅ Done (25 JAN) |
| Phase 1 | Enforce at Platform Level | ✅ Done (26 JAN) |
| **Phase 2** | **Fail-Fast in Pipeline Tasks** | **NEXT** |
| Phase 3 | ADF Integration Testing | Pending |

**Completed (26 JAN)**: Platform API now enforces `access_level` via Pydantic validator. Accepts: "public" (any case), "OUO" or "Official Use Only" (any case). Rejects: "restricted" (future), invalid values. NOTE: RESTRICTED is defined but NOT YET SUPPORTED.

---

### API Documentation (F12.8 + F12.9)
**Status**: OpenAPI infrastructure COMPLETE

| Deliverable | Status |
|-------------|--------|
| `/api/interface/swagger` | Done |
| `/api/interface/redoc` | Done |
| `/api/openapi.json` | Done |
| TiTiler consumer docs handoff | Done |

---

## FY26 Priorities (ends 30 JUN 2026)

| Priority | Epic | Feature | Status |
|:--------:|------|---------|--------|
| ~~1~~ | E7 | F7.21 Raster Result Models | ✅ Core complete |
| ~~1~~ | E4 | Classification Enforcement | ✅ Phase 1 complete |
| **1** | E4 | **Classification Enforcement Phase 2** | **NEXT** |
| 2 | E7→E2 | RasterMetadata + STAC Self-Healing | In Progress |
| 3 | E3 | DDH Platform Integration | In Progress |
| 4 | E9 | Pre-prepared Raster Ingest | Pending |
| -- | E8 | H3 Analytics / Building Exposure | Backlog |

**Focus**: Phase 2 (fail-fast in pipeline tasks) is optional for V0.8 - Phase 1 enforcement at API layer is the critical gate.

---

## Current Sprint Focus

### 1. Classification Enforcement (E4) - ✅ Phase 1 COMPLETE
See [Active Work](#classification-enforcement-e4) section above.

**Completed (26 JAN)**:
1. ✅ Enforce `access_level` at Platform API layer (Pydantic validator)
2. ✅ Reject submissions with invalid classification
3. ✅ Pass validated enum value to CoreMachine jobs

**Phase 2 (Optional for V0.8)**:
- Fail-fast in pipeline tasks if access_level missing (defense-in-depth)

---

### 2. RasterMetadata + STAC Self-Healing
Continue testing and validation.

**Next Actions**:
1. Test raster STAC rebuild job
2. Validate cog_metadata population

---

### Backlog: H3 Analytics on Rwanda (E8)
**Status**: DEFERRED - Infrastructure ready, not current priority
**Dependency**: F9.1 FATHOM merged COGs exist in silver-fathom

| Story | Status |
|-------|--------|
| S8.13.1a | Fix H3 finalize timeout (pg_cron) | Done |
| S8.13.1b-d | Enable pg_cron, run setup, re-run bootstrap | Pending |
| S8.13.2-5 | Add FATHOM to source_catalog, run aggregation | Pending |

---

### Backlog: Building Flood Exposure Pipeline (E8)
**Status**: DEFERRED - Depends on H3 completion
**Data Source**: Microsoft Building Footprints

---

### Add Rasters to Existing Collections (F2.10)
**Status**: Core implementation COMPLETE, Platform wiring pending

| Story | Status |
|-------|--------|
| Add `collection_must_exist` to handlers | Done |
| Add to job parameters_schema | Done |
| Create Platform endpoint | Pending |
| Tests | Pending |

---

## Epic Status Summary

### E2: Raster Data as API

| Feature | Status |
|---------|--------|
| F2.7: Collection Processing | In Progress |
| F2.9: STAC-Integrated Viewer | Done |
| F2.10: Add to Existing Collections | Core done |

### E7: Pipeline Infrastructure

| Feature | Status |
|---------|--------|
| F7.8: VectorMetadata | Done |
| F7.9: RasterMetadata | In Progress |
| F7.10: Metadata Consistency Timer | Done |
| F7.11: STAC Self-Healing | In Progress |
| F7.13: Docker Worker | Done |
| F7.16: db_maintenance.py Split | Done |
| F7.17: Job Resubmit + Features | Done |
| F7.18: Docker Framework | Done (Phases 1-4) |

### E8: GeoAnalytics Pipeline

| Feature | Status |
|---------|--------|
| F8.1-F8.3: Grid infrastructure | Done |
| F8.8: Source Catalog | Done |
| F8.9: H3 Export Pipeline | Done |
| F8.13: Rwanda H3 Aggregation | In Progress |
| F8.7: Building Exposure | Pending |

### E9: Large Data Hosting

| Feature | Status |
|---------|--------|
| F9.1: FATHOM ETL | Done (Rwanda) |
| F9.5: xarray Service | Done |
| F9.6: TiTiler Services | In Progress |
| F9.8: Pre-prepared Ingest | Pending |

### E12: Interface Modernization

| Feature | Status |
|---------|--------|
| F12.1-F12.3: Cleanup, HTMX, Migration | Done |
| F12.3.1: DRY Consolidation | Done |
| SP12.9: NiceGUI Evaluation | Done - Not Pursuing |
| F12.4-F12.8: Remaining interfaces | Pending |

---

## Reference Data Pipelines (Low Priority)

| Feature | Data Source | Status |
|---------|-------------|--------|
| F7.2: IBAT (WDPA, KBAs) | IBAT API | Partial |
| F7.6: ACLED Conflict Data | ACLED API | Pending |
| F7.7: Static Reference (Admin0/1) | Natural Earth | Pending |

---

## DevOps Tasks (No Geospatial Knowledge Required)

| Task | Description | Skills |
|------|-------------|--------|
| S9.2.2 | Create DDH service principal | Azure AD |
| S9.2.3 | Grant blob read access | Azure RBAC |
| EN6.1 | Docker image with GDAL | Docker |
| EN6.2 | Container deployment | Azure DevOps |
| F7.2.1 | Create ADF instance | Azure Data Factory |

---

## Docker Worker Remaining Backlog

| Story | Status |
|-------|--------|
| S7.13.13: Test checkpoint/resume after crash | Pending |
| S7.13.14: Add `process_vector_docker` job | Pending |

---

### AzCopy Integration for Docker Worker (F7.24)
**Status**: PLANNED
**Priority**: MEDIUM - Performance optimization (5-10x speedup)
**Details**: [/V0.8_COPY.md](/V0.8_COPY.md)
**Created**: 29 JAN 2026

**Problem**: Current `stream_blob_to_mount()` and `stream_mount_to_blob()` use Python Azure SDK with 32MB chunked transfers, limited by Python's GIL.

**Solution**: Integrate AzCopy (Go-based CLI) for 5-10x faster blob ↔ Azure Files transfers.

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Add AzCopy to Dockerfile | Pending |
| Phase 2 | Submit eService for RBAC role | Pending |
| Phase 3 | Create `infrastructure/azcopy.py` wrapper | Pending |
| Phase 4 | Add `_fast` methods to BlobRepository | Pending |
| Phase 5 | Wire to `raster_cog.py` | Pending |

**Effort**: ~1 hour implementation + eService lead time for RBAC

**Prerequisite**: eService request for "Storage File Data Privileged Contributor" role on Docker worker managed identity (template in V0.8_COPY.md)

---

## Recently Completed

| Date | Item |
|------|------|
| 26 JAN 2026 | E4 Phase 1: Classification Enforcement at Platform API (Pydantic validator) |
| 25 JAN 2026 | F7.21 Phase 2: Service wiring (validate, cog, stac return typed results) |
| 25 JAN 2026 | F7.21 Phase 1: Raster Result Models (12 Pydantic models) |
| 25 JAN 2026 | GAP-04b Vector Curator Interface (MapLibre + TiPG) |
| 25 JAN 2026 | CoreMachine job_events table + Execution Timeline UI |
| 25 JAN 2026 | Docker UI Phase 2 Core Routes (tasks interface added) |
| 25 JAN 2026 | Docker UI Gap Analysis for V0.8 Testing |
| 25 JAN 2026 | V0.8 MosaicJSON Removal from Docker Workflow |
| 25 JAN 2026 | F7.21 Raster Result Models Implementation Plan |
| 23 JAN 2026 | UI Migration Phases 1-3 |
| 22 JAN 2026 | Explicit Approval Record Creation |
| 22 JAN 2026 | Infrastructure as Code DRY Cleanup |
| 21 JAN 2026 | Consolidate Status/Unpublish Endpoints |
| 21 JAN 2026 | Force Reprocess via overwrite |
| 21 JAN 2026 | Docker AAD Auth Fix |
| 21 JAN 2026 | Platform Default to Docker |
| 12 JAN 2026 | Job Resubmit Endpoint |
| 12 JAN 2026 | db_maintenance.py Split |

*For full details, see [COMPLETED_JAN2026.md](./COMPLETED_JAN2026.md) and [HISTORY.md](./HISTORY.md)*

---

## Quick Links

| Document | Purpose |
|----------|---------|
| [FATHOM_ETL.md](./FATHOM_ETL.md) | FATHOM flood data pipeline |
| [H3_REVIEW.md](./H3_REVIEW.md) | H3 aggregation implementation |
| [TABLE_MAINTENANCE.md](./TABLE_MAINTENANCE.md) | pg_cron + autovacuum setup |
| [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) | Technical patterns |
| [ado_wiki/V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md) | **Epic/Feature/Story definitions (single source of truth)** |

---

## Workflow

1. ~~Complete Rwanda FATHOM pipeline~~ DONE
2. ~~F7.21 Raster Result Models~~ Type safety for Docker workflow - DONE
3. ~~E4 Classification Enforcement Phase 1~~ Platform API enforcement - DONE
4. **V0.8 Finalization** - Docker UI + testing (CURRENT)
5. RasterMetadata + STAC Self-Healing testing (NEXT)
6. H3 aggregation / Building exposure (BACKLOG)
