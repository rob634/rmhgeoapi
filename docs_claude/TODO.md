# Working Backlog - ADO Aligned

**Last Updated**: 09 FEB 2026
**Source of Truth**: [V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md)
**Structure**: EPIC → FEATURE → User Story → Tasks

---

## IMMEDIATE PRIORITY

### US 4.2.1: Approval-Aware Overwrite & Version Validation `[IMPLEMENTED]`

**Implementation Plan**: [APPROVAL_OVERWRITE_VALIDATION.md](./APPROVAL_OVERWRITE_VALIDATION.md)

**Problem**: `overwrite=True` fails validation because approval state not checked. Version lineage doesn't enforce approved predecessor.

| Task | Status | Details |
|------|--------|---------|
| T4.2.1.1: Pass overwrite to validate_version_lineage() | ✅ Done | submit.py line 302 |
| T4.2.1.2: Block overwrite if APPROVED | ✅ Done | platform_validation.py |
| T4.2.1.3: Reset approval on overwrite (REJECTED/REVOKED) | ✅ Fixed | **V0.8.16.7**: Moved from submit-time to handler completion |
| T4.2.1.4: Require approved previous for semantic versions | ✅ Done | platform_validation.py |
| T4.2.1.5: Include approval_state in lineage state | ✅ Done | asset_service.py |
| T4.2.1.6: Test revocation flow | ✅ Tested | 10 FEB 2026 |
| T4.2.1.7: Test overwrite blocked on APPROVED | ✅ Tested | 10 FEB 2026 |
| T4.2.1.8: Test semantic version requires approved | ✅ Tested | 10 FEB 2026 |

**Bug Fix V0.8.16.7** (10 FEB 2026): Approval reset was happening at submit time, not job completion. If job failed, approval state was reset but no new data existed. Fixed by moving reset to handler success callback.

**Testing Order**: Revocation → Overwrite blocked → Overwrite after revoke → Semantic version chain

**Awaiting**: Re-deploy + Re-test overwrite reset timing

---

## Quick Navigation

| Document | Purpose |
|----------|---------|
| [V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md) | **ADO work item definitions** |
| [APPROVAL_OVERWRITE_VALIDATION.md](./APPROVAL_OVERWRITE_VALIDATION.md) | **US 4.2.1 - IMMEDIATE PRIORITY** |
| [B2B_REQUEST_CONTEXT.md](./B2B_REQUEST_CONTEXT.md) | US 7.x B2B request tracking |
| [APP_MODE_ENDPOINT_REFACTOR.md](./APP_MODE_ENDPOINT_REFACTOR.md) | US 6.1 multi-app deployment |
| [DRY_RUN_IMPLEMENTATION.md](./DRY_RUN_IMPLEMENTATION.md) | US 1.x dry_run validation |
| [APPROVAL_WORKFLOW.md](./APPROVAL_WORKFLOW.md) | US 4.2 approval system |
| [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md) | US 1.1 Docker framework |
| [HISTORY.md](./HISTORY.md) | Completed work log |

---

# EPIC: Geospatial API for DDH

---

## FEATURE 1: ETL Pipeline Orchestration `[ACTIVE]`

### US 1.1: Serverless Job Orchestration `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| Job→Stage→Task workflow pattern | ✅ Done | CoreMachine implemented |
| Queue-based workload separation | ✅ Done | jobs, container-tasks, functionapp-tasks |
| Docker worker with checkpoint/resume | ✅ Done | [DOCKER_INTEGRATION.md](./DOCKER_INTEGRATION.md) |
| Docker worker as required infrastructure | ✅ Done | 06 FEB 2026 - no optional mode |
| pg_cron enabled (DEV) | ✅ Done | Extension enabled |
| pg_cron SQL setup (DEV) | 🔲 Ready | SQL in reference doc |
| pg_cron eService (QA/UAT/PROD) | 🔲 Not started | [ESERVICE_PG_CRON_REQUEST.md](/operations/ESERVICE_PG_CRON_REQUEST.md) |

### US 1.3: Job Lifecycle `[CLOSED]`

All tasks complete: job/task status, approval auto-creation, job resubmit.

### US 1.5: VirtualiZarr NetCDF Pipeline `[NEW]`

| Task | Status | Details |
|------|--------|---------|
| Kerchunk JSON references for NetCDF | 🔲 Not started | Future |
| TiTiler-xarray integration | 🔲 Not started | Future |
| STAC collection with VirtualiZarr assets | 🔲 Not started | Future |

### EN 1.2: Metadata Architecture `[CLOSED]`

All tasks complete: VectorMetadata, RasterMetadata, table_catalog, cog_metadata.

### EN 1.6: DAG Orchestration Migration `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| DAG readiness assessment | ✅ Done | [V0.8_DAG_READINESS.md](/V0.8_DAG_READINESS.md) |
| DAG workflow engine | 🔲 Future | Epoch 5 |
| Conditional branching | 🔲 Future | Epoch 5 |

---

## FEATURE 2: Raster Data Pipeline `[CLOSED]`

All User Stories complete (US 2.1, 2.2, 2.3).

**Related implementation docs:**
- [RASTER_RESULT_MODELS.md](./RASTER_RESULT_MODELS.md) - Type safety
- [RASTER_METADATA.md](./RASTER_METADATA.md) - cog_metadata population

---

## FEATURE 3: Vector Data Pipeline `[CLOSED]`

All User Stories complete (US 3.1, 3.2, 3.3).

**07 FEB 2026**: STAC cataloging is now optional for vectors. Provide `collection_id` to create STAC item.
See [HISTORY.md](./HISTORY.md) for details.

---

## FEATURE 4: Data Governance & Classification `[ACTIVE]`

### US 4.1: Classification Enforcement `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| T4.1.1: Create AccessLevel enum | ✅ Done | 25 JAN 2026 |
| T4.1.2: Pydantic validator on PlatformRequest | ✅ Done | 26 JAN 2026 |
| T4.1.3: Fail-fast in pipeline tasks | 🔲 Optional | Defense-in-depth |

### US 4.2: Approval Workflow `[ACTIVE]`

Core approval complete. Sub-story US 4.2.1 (approval-aware validation) is **IMMEDIATE PRIORITY**.

See: [APPROVAL_OVERWRITE_VALIDATION.md](./APPROVAL_OVERWRITE_VALIDATION.md)

### US 4.3: Governed External Delivery `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| T4.3.1: AzureDataFactoryRepository | ✅ Done | Code complete |
| T4.3.2: Wire to ApprovalService | ✅ Done | Classification check |
| T4.3.3: Submit eService for ADF instance | 🔲 Not started | Blocks T4.3.4-5 |
| T4.3.4: Configure environment variables | 🔲 Blocked | By T4.3.3 |
| T4.3.5: Create ADF pipeline | 🔲 Blocked | By T4.3.3 |

---

## FEATURE 5: Service Layer (TiTiler/TiPG) `[ACTIVE]`

### US 5.1-5.3, 5.5-5.8 `[CLOSED]`

All complete: COG tiles, data access, multidimensional, OGC Features, vector tiles, STAC API, infrastructure.

### US 5.4: pgSTAC Mosaic Searches `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| Mosaic search registration | ✅ Done | |
| Tiles from search results | ✅ Done | |
| Temporal queries | ✅ Done | |
| Dynamic CQL queries | 🔲 Not started | Future enhancement |

---

## FEATURE 6: Admin & Developer Portal `[ACTIVE]`

### US 6.1: Admin Portal `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| System health dashboard | ✅ Done | FA + Docker + queues + DB |
| Job submission/monitoring UI | ✅ Done | |
| STAC browser | ✅ Done | |
| Vector data browser with map | ✅ Done | MapLibre + TiPG |
| Approval workflow UI | ✅ Done | 25 JAN 2026 |
| Multi-app deployment (APP_MODE) | 🔄 In Progress | [APP_MODE_ENDPOINT_REFACTOR.md](./APP_MODE_ENDPOINT_REFACTOR.md) |
| DAG workflow visualization | 🔲 Future | After EN 1.6 |

#### US 6.1 Sub-tasks: APP_MODE Endpoint Refactor

| Task | Status | Details |
|------|--------|---------|
| Gateway Function App deployed | ✅ Done | rmhgeogateway |
| has_*_endpoints properties | ✅ Done | 05 FEB 2026 |
| Three-tier health endpoints | ✅ Done | /health, /platform/health, /system-health |
| Docker worker always checked | ✅ Done | 06 FEB 2026 |
| Wrap endpoint registration with mode checks | 🔲 Pending | Phase 3 |
| Deploy and test on gateway | 🔲 Pending | Phase 4 |
| Apply to other APP_MODEs | 🔲 Pending | Phase 5 |

### US 6.2: Developer Integration Portal `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| Swagger UI | ✅ Done | /api/interface/swagger |
| ReDoc | ✅ Done | /api/interface/redoc |
| OpenAPI 3.0 spec | ✅ Done | /api/openapi.json |
| CURL examples | ✅ Done | In Swagger |
| Integration quick-start guide | 🔲 Not started | |

---

## FEATURE 7: DDH Platform Integration `[ACTIVE]`

### US 7.1: API Contract Documentation `[ACTIVE]`

| Task | Status | Details |
|------|--------|---------|
| T7.1.1: Generate OpenAPI spec | ✅ Done | |
| T7.1.2: Deploy Swagger UI | ✅ Done | |
| T7.1.3: Review with DDH team | 🔄 In Progress | |

### US 7.2: Identity & Access Configuration `[CLOSED]`

All complete: DDH Managed Identity access to Bronze Storage, Platform API, Service Layer.

### US 7.3: Environment Provisioning `[NEW]`

| Task | Status | Details |
|------|--------|---------|
| QA environment configuration | 🔲 Not started | |
| UAT environment provisioned | 🔲 Not started | |
| Production environment provisioned | 🔲 Not started | |

### EN 7.4: Integration Test Suite `[NEW]` (Optional)

| Task | Status | Details |
|------|--------|---------|
| Vector publish round-trip test | 🔲 Not started | |
| Raster publish round-trip test | 🔲 Not started | |
| OGC Features query test | 🔲 Not started | |
| Job status polling test | 🔲 Not started | |

### US 7.x: B2B Request Context Tracking `[NEW]`

**Not yet in ADO** - Propose as new User Story under F7.

| Task | Status | Details |
|------|--------|---------|
| Extend ApiRequest model with client fields | 🔲 Pending | [B2B_REQUEST_CONTEXT.md](./B2B_REQUEST_CONTEXT.md) |
| Create request_context.py extractor | 🔲 Pending | Azure AD appid + User-Agent |
| Wire to platform/submit | 🔲 Pending | |
| Wire to platform/validate | 🔲 Pending | |
| Update internal UI User-Agents | 🔲 Pending | RMH-Orchestrator-UI, RMH-Gateway-UI |
| Database migration | 🔲 Pending | action=ensure |

### US 7.x: Platform Submit Validation `[NEW]`

**Not yet in ADO** - Propose as new User Story under F7.

| Task | Status | Details |
|------|--------|---------|
| Add previous_version_id to PlatformRequest | 🔲 Pending | [DRY_RUN_IMPLEMENTATION.md](./DRY_RUN_IMPLEMENTATION.md) |
| Create validate_version_lineage() helper | 🔲 Pending | |
| Add ?dry_run=true to submit endpoint | 🔲 Pending | |
| Update/consolidate validate endpoint | 🔲 Pending | |

---

# BACKLOG (Not in ADO)

Items below are tracked here but not yet added to ADO. Add to ADO when prioritized.

## H3 Analytics / GeoAnalytics

**Rationale**: Infrastructure ready but not current priority. Add to ADO when client funding secured.

| Item | Status | Notes |
|------|--------|-------|
| H3 Rwanda aggregation | Deferred | pg_cron prerequisite |
| Building flood exposure | Deferred | Depends on H3 |
| FATHOM full inventory | Deferred | Client funding needed |

## Performance Optimizations

| Item | Status | Notes |
|------|--------|-------|
| AzCopy integration | Planned | [V0.8_COPY.md](/V0.8_COPY.md) - 5-10x speedup |
| Mount-based resumable workflow | Planned | [Plan file](/Users/robertharrison/.claude/plans/async-squishing-reddy.md) |

## Technical Debt

| Item | Status | Notes |
|------|--------|-------|
| Refactor trigger_platform.py | Planned | [REFACTOR_TRIGGER_PLATFORM.md](./REFACTOR_TRIGGER_PLATFORM.md) |
| Vector revision tracking | Planned | app.vector_revisions table |
| Job version tracking | Planned | Capture app version in job metadata |

---

# Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done |
| 🔄 | In Progress |
| 🔲 | Not Started / Pending |
| ⏸️ | Blocked |

---

# Recently Completed

| Date | Feature | Task |
|------|---------|------|
| 06 FEB 2026 | US 6.1 | Docker worker required infrastructure |
| 06 FEB 2026 | US 6.1 | System-health always checks docker worker |
| 05 FEB 2026 | US 6.1 | Three-tier health endpoints |
| 04 FEB 2026 | US 3.1 | Geo schema table name validation |
| 31 JAN 2026 | EN 1.2 | RasterMetadata + STAC self-healing |
| 26 JAN 2026 | US 4.1 | Classification enforcement Phase 1 |
| 25 JAN 2026 | EN 1.2 | Raster result models (type safety) |
| 25 JAN 2026 | US 6.1 | Vector curator interface |
| 25 JAN 2026 | US 4.2 | Approval workflow UI |

*For full history, see [HISTORY.md](./HISTORY.md)*
