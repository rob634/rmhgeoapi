# Working Backlog
**This file contains high level items only**
This file references other documents containing implementation details. This is to avoid a 50,000 line TODO.md. This file should not exceed 500 lines.

**Last Updated**: 25 JAN 2026
**Source of Truth**: [docs/epics/README.md](/docs/epics/README.md) - Epic/Feature/Story definitions
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

---

## Testing Needed

- [ ] **Test Approval Workflow** - Submit job, verify approval record created, approve via API
- [ ] **Test Artifact/Revision Workflow** - Submit with same DDH identifiers, verify revision increments
- [ ] **Test External Service Registry** - `/api/jobs/services/register`, list, health check

---

## Active Work

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
**Status**: Phase 1 COMPLETE, Phase 2 IN PROGRESS
**Details**: [RASTER_METADATA.md](./RASTER_METADATA.md)
**Priority**: CRITICAL - Raster is primary STAC use case

| Story | Status |
|-------|--------|
| RasterMetadata class + DDL | Done |
| RasterMetadataRepository | Done |
| Wire to extract_stac_metadata | Done |
| Enable raster rebuild | Done |
| Test: process_raster_docker populates cog_metadata | NEXT |

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
**Status**: Phase 0 COMPLETE - Data Model Unification
**Details**: [CLASSIFICATION_ENFORCEMENT.md](./CLASSIFICATION_ENFORCEMENT.md)
**Priority**: HIGH - Blocks type-safe approval workflow

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Data Model Unification (unified to AccessLevel enum) | ✅ Done (25 JAN) |
| **Phase 1** | **Enforce at Platform Level** | **NEXT** |
| Phase 2 | Fail-Fast in Pipeline Tasks | Pending |
| Phase 3 | ADF Integration Testing | Pending |

**Completed (25 JAN)**: Unified `Classification` enum into `AccessLevel` (single source of truth in `core/models/stac.py`). NOTE: RESTRICTED is defined but NOT YET SUPPORTED.

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
| **1** | E4 | **Classification Enforcement** | **Phase 1 NEXT** |
| 2 | E7→E2 | RasterMetadata + STAC Self-Healing | In Progress |
| 3 | E3 | DDH Platform Integration | In Progress |
| 4 | E9 | Pre-prepared Raster Ingest | Pending |
| -- | E8 | H3 Analytics / Building Exposure | Backlog |

**Focus**: Classification enforcement is now top priority.

---

## Current Sprint Focus

### 1. Classification Enforcement (E4) - Phase 1
See [Active Work](#classification-enforcement-e4) section above.

**Next Actions**:
1. Enforce `access_level` at Platform API layer
2. Reject submissions without valid classification
3. Wire to approval workflow

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

## Recently Completed

| Date | Item |
|------|------|
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
| [docs/epics/README.md](/docs/epics/README.md) | Master Epic/Feature/Story definitions |

---

## Workflow

1. ~~Complete Rwanda FATHOM pipeline~~ DONE
2. **F7.21 Raster Result Models** - Type safety for Docker workflow (CURRENT)
3. **E4 Classification Enforcement** - Phase 1 Platform layer (NEXT)
4. RasterMetadata + STAC Self-Healing testing
5. H3 aggregation / Building exposure (BACKLOG)
