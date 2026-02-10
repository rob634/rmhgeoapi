# Working Backlog - ADO Aligned

**Last Updated**: 10 FEB 2026
**Source of Truth**: [V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md)
**Structure**: EPIC → FEATURE → User Story → Tasks

---

## Quick Navigation

| Document | Purpose |
|----------|---------|
| [V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md) | **ADO work item definitions** |
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

### US 1.1: Serverless Job Orchestration - Remaining Tasks

| Task | Status | Details |
|------|--------|---------|
| pg_cron SQL setup (DEV) | 🔲 Ready | SQL in reference doc |
| pg_cron eService (QA/UAT/PROD) | 🔲 Not started | [ESERVICE_PG_CRON_REQUEST.md](/operations/ESERVICE_PG_CRON_REQUEST.md) |

### US 1.5: VirtualiZarr NetCDF Pipeline `[FUTURE]`

| Task | Status | Details |
|------|--------|---------|
| Kerchunk JSON references for NetCDF | 🔲 Not started | Future |
| TiTiler-xarray integration | 🔲 Not started | Future |
| STAC collection with VirtualiZarr assets | 🔲 Not started | Future |

### EN 1.6: DAG Orchestration Migration `[FUTURE]`

| Task | Status | Details |
|------|--------|---------|
| DAG workflow engine | 🔲 Future | Epoch 5 |
| Conditional branching | 🔲 Future | Epoch 5 |

---

## FEATURE 4: Data Governance & Classification `[ACTIVE]`

### US 4.1: Classification Enforcement - Remaining

| Task | Status | Details |
|------|--------|---------|
| T4.1.3: Fail-fast in pipeline tasks | 🔲 Optional | Defense-in-depth |

### US 4.3: Governed External Delivery `[BLOCKED]`

| Task | Status | Details |
|------|--------|---------|
| T4.3.3: Submit eService for ADF instance | 🔲 Not started | Blocks T4.3.4-5 |
| T4.3.4: Configure environment variables | 🔲 Blocked | By T4.3.3 |
| T4.3.5: Create ADF pipeline | 🔲 Blocked | By T4.3.3 |

---

## FEATURE 5: Service Layer (TiTiler/TiPG) - Remaining

### US 5.4: pgSTAC Mosaic Searches

| Task | Status | Details |
|------|--------|---------|
| Dynamic CQL queries | 🔲 Not started | Future enhancement |

---

## FEATURE 6: Admin & Developer Portal `[ACTIVE]`

### US 6.1: Admin Portal - Remaining

| Task | Status | Details |
|------|--------|---------|
| Multi-app deployment (APP_MODE) | 🔄 In Progress | [APP_MODE_ENDPOINT_REFACTOR.md](./APP_MODE_ENDPOINT_REFACTOR.md) |
| DAG workflow visualization | 🔲 Future | After EN 1.6 |

#### APP_MODE Endpoint Refactor - Remaining Phases

| Task | Status | Details |
|------|--------|---------|
| Wrap endpoint registration with mode checks | 🔲 Pending | Phase 3 |
| Deploy and test on gateway | 🔲 Pending | Phase 4 |
| Apply to other APP_MODEs | 🔲 Pending | Phase 5 |

### US 6.2: Developer Integration Portal - Remaining

| Task | Status | Details |
|------|--------|---------|
| Integration quick-start guide | 🔲 Not started | |

---

## FEATURE 7: DDH Platform Integration `[ACTIVE]`

### US 7.1: API Contract Documentation

| Task | Status | Details |
|------|--------|---------|
| T7.1.3: Review with DDH team | 🔄 In Progress | |

### US 7.3: Environment Provisioning `[NEW]`

| Task | Status | Details |
|------|--------|---------|
| QA environment configuration | 🔲 Not started | |
| UAT environment provisioned | 🔲 Not started | |
| Production environment provisioned | 🔲 Not started | |

### EN 7.4: Integration Test Suite (Optional)

| Task | Status | Details |
|------|--------|---------|
| Vector publish round-trip test | 🔲 Not started | |
| Raster publish round-trip test | 🔲 Not started | |
| OGC Features query test | 🔲 Not started | |
| Job status polling test | 🔲 Not started | |

### US 7.x: B2B Request Context Tracking

**Not yet in ADO** - Propose as new User Story under F7.

| Task | Status | Details |
|------|--------|---------|
| Extend ApiRequest model with client fields | 🔲 Pending | [B2B_REQUEST_CONTEXT.md](./B2B_REQUEST_CONTEXT.md) |
| Create request_context.py extractor | 🔲 Pending | Azure AD appid + User-Agent |
| Wire to platform/submit and validate | 🔲 Pending | |
| Update internal UI User-Agents | 🔲 Pending | RMH-Orchestrator-UI, RMH-Gateway-UI |

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
| 10 FEB 2026 | US 4.2.1 | Approval-aware overwrite & version validation |
| 09 FEB 2026 | F7 | Forward FK architecture (V0.8.16) |
| 09 FEB 2026 | F7 | Query param deprecation on platform/status |
| 06 FEB 2026 | US 6.1 | Docker worker required infrastructure |

*For full history, see [HISTORY.md](./HISTORY.md)*
