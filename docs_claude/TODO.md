# Working Backlog - ADO Aligned

**Last Updated**: 11 FEB 2026
**Source of Truth**: [V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md)
**Structure**: EPIC → FEATURE → User Story → Tasks

---

## Quick Navigation

| Document | Purpose |
|----------|---------|
| [V0.8_ADO_WORKITEMS.md](/ado_wiki/V0.8_ADO_WORKITEMS.md) | **ADO work item definitions** |
| [D360_REQUIREMENTS_ASSESSMENT.md](./D360_REQUIREMENTS_ASSESSMENT.md) | **D360 requirements gap analysis** |
| [D360_STYLES_LEGENDS_MIGRATION.md](./D360_STYLES_LEGENDS_MIGRATION.md) | **Styles/Legends migration plan** |
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

## FEATURE 5: Service Layer (TiTiler/TiPG) `[ACTIVE]`

### US 5.5: Styles & Legends Migration `[PRIORITY]` `[NEW]`

**D360 Gap**: Only 2 unmet requirements (1.9 Legend info, 3.5 Raster legend) — both addressed here.
**Plan**: [D360_STYLES_LEGENDS_MIGRATION.md](./D360_STYLES_LEGENDS_MIGRATION.md)
**Assessment**: [D360_REQUIREMENTS_ASSESSMENT.md](./D360_REQUIREMENTS_ASSESSMENT.md)
**Cross-repo**: rmhgeoapi (ETL writes) + rmhtitiler (Service API reads/serves)

| Task | Status | Details |
|------|--------|---------|
| **Phase 1: Vector Styles to rmhtitiler** | 🔲 Ready | Copy models + translator (pure Python), rewrite repository (asyncpg), create FastAPI router |
| T5.5.1: Copy styles_models.py to rmhtitiler | 🔲 Pending | From `ogc_styles/models.py` — 163 lines, 0 deps |
| T5.5.2: Copy styles_translator.py to rmhtitiler | 🔲 Pending | From `ogc_styles/translator.py` — 384 lines, 0 deps |
| T5.5.3: Create styles_db.py (asyncpg) | 🔲 Pending | Rewrite read methods from psycopg → asyncpg |
| T5.5.4: Create legend_generator.py | 🔲 Pending | Vector + raster legend derivation from JSONB |
| T5.5.5: Create styles.py FastAPI router | 🔲 Pending | 6 endpoints: list/get/legend for vector + raster |
| T5.5.6: Register router in app.py | 🔲 Pending | `app.include_router(styles.router)` |
| **Phase 2: Database Permissions** | 🔲 Pending | GRANT SELECT on `app.raster_render_configs` to geotiler user |
| **Phase 3: Deprecate rmhgeoapi endpoints** | 🔲 Future | Add Deprecation header, eventually remove routes |

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

### EN-TD.1: Raw JSON Parsing in HTTP Triggers `[NEW 12 FEB 2026]`

**Problem**: 35 trigger files call `req.get_json()` directly, bypassing `BaseHttpTrigger.extract_json_body()`. This means they get no fallback for Azure Functions content-type mismatches (PowerShell, proxies), no `isinstance(body, dict)` type guard, and no consistent error messages.

**Root Cause**: Most triggers are standalone functions (not `BaseHttpTrigger` subclasses), so they can't call `self.extract_json_body()`.

**Fix**: Create a standalone utility function that any trigger can call:

```python
# triggers/utils.py (or add to http_base.py as module-level function)
def parse_request_json(req: func.HttpRequest, required: bool = True) -> Optional[Dict]:
    """Same logic as BaseHttpTrigger.extract_json_body() — usable without inheritance."""
```

Then find-and-replace all raw `req.get_json()` calls with `parse_request_json(req)`.

**Scope**: 35 files, ~50 occurrences. Mechanical refactor, no business logic changes.

**Files** (from QA review 12 FEB 2026 — Rajesh hit this in ITSES QA with PowerShell):

| Category | Files |
|----------|-------|
| Platform triggers | `trigger_platform_status.py`, `platform/unpublish.py`, `platform/resubmit.py` |
| Asset/Approval | `trigger_approvals.py`, `assets/asset_approvals_bp.py` |
| Admin | `admin_approvals.py`, `admin_data_migration.py`, `admin_external_db.py`, `admin_external_services.py`, `h3_datasets.py`, `snapshot.py` |
| STAC | `stac_vector.py`, `stac_collections.py`, `stac_extract.py` |
| Other | `promote.py`, `trigger_map_states.py`, `curated/admin.py`, `trigger_raster_renders.py`, `probes.py` |
| Legacy | `raster_api/triggers.py`, `raster_collection_viewer/triggers.py` |

**Previously resolved** - see below.

### Resolved Technical Debt (10 FEB 2026)

| Item | Resolution |
|------|------------|
| Refactor trigger_platform.py | ✅ Done 27 JAN 2026 - Split from 2,414 lines to 53-line facade + `triggers/platform/` submodules |
| Job version tracking | ✅ Implemented V0.8.12 - `etl_version` field on JobRecord |
| Vector revision tracking | ✅ Not needed - all vectors go through Platform API, revision tracking handled by GeospatialAsset + asset_revisions |

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
| 11 FEB 2026 | US 4.2 | Approval consolidation COMPLETE - all 5 phases + post-migration docs verified |
| 10 FEB 2026 | US 4.2.1 | Approval-aware overwrite & version validation |
| 09 FEB 2026 | F7 | Forward FK architecture (V0.8.16) |
| 09 FEB 2026 | F7 | Query param deprecation on platform/status |
| 06 FEB 2026 | US 6.1 | Docker worker required infrastructure |

*For full history, see [HISTORY.md](./HISTORY.md)*
