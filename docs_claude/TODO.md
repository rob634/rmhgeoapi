# Working Backlog - ADO Aligned

**Last Updated**: 18 FEB 2026
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
| [MULTI_APP_CLEANUP.md](./MULTI_APP_CLEANUP.md) | EN-TD.3 Multi-app routing cleanup |
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

### EN-TD.2: psycopg3 Type Adapter + Serialization Cleanup `[NEW 18 FEB 2026]`

**Plan**: [PYDANTIC_REVIEW.md](/PYDANTIC_REVIEW.md) (root)
**Trigger**: Production bug — `assign_version()` passed raw dict to psycopg3 `%s` param, raised `cannot adapt type 'dict'`
**Root cause**: psycopg3 (unlike psycopg2) does not auto-adapt `dict → jsonb`. Fix is to register type adapters at connection level, not scatter `json.dumps()` across 40+ call sites.
**Scope**: 2 connection creation points, then incremental cleanup of 15 repos

#### Phase 1: Register psycopg3 Type Adapters (THE FIX)

**Register once at connection level → all repos inherit automatically. Zero repo code changes.**

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.1: Register `JsonbBinaryDumper` for dict+list on single-use connections | 🔲 Ready | `infrastructure/postgresql.py` | In `_get_single_use_connection()` after line 696 (`conn = psycopg.connect(...)`), add: `conn.adapters.register_dumper(dict, psycopg.types.json.JsonbBinaryDumper)` and same for `list`. ~3 lines. |
| T-TD2.2: Register `JsonbBinaryDumper` for dict+list on pooled connections | 🔲 Ready | `infrastructure/connection_pool.py` | In `_configure_connection()` after search_path setup, add same adapter registration. ~3 lines. |
| T-TD2.3: Register Enum adapter (or add `_prepare_value()` fallback) | 🔲 Ready | `infrastructure/postgresql.py` | Option A: Custom `EnumDumper` registered for `Enum` base class. Option B: Add lightweight `_prepare_value()` static method that only handles Enum→.value (dicts handled by adapter). **Test whether psycopg3 dumper inheritance covers Enum subclasses** — if not, use Option B. |
| T-TD2.4: Verify existing code still works (no repo changes) | 🔲 Ready | N/A | After adapter registration, all existing `json.dumps()` calls still work (strings are valid for JSONB). Run: submit flow, approval flow, job creation. Zero behavior change expected. |

#### Phase 2: Revert Bandaid + Simplify asset_repository.update()

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.5: Revert isinstance dict/list check in `update()` | 🔲 Blocked by Phase 1 | `infrastructure/asset_repository.py` | Revert commit `dafc46f` lines 604-608. With adapter registered, dicts pass straight through. Also remove manual enum pre-conversion (lines 592-597). |
| T-TD2.6: Test assign_version + approval end-to-end | 🔲 Blocked by T-TD2.5 | N/A | The flow that originally triggered the bug. Must work with raw dicts and enums. |

#### Phase 3: Remove json.dumps() Across Repositories (incremental)

**With adapters registered, all `json.dumps()` calls become unnecessary — they convert dict→string, but psycopg3 now also accepts dicts. Existing calls are harmless but redundant.**

**IMPORTANT for Claude**: One repo per commit. Test after each. Do NOT batch.

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.7: GeospatialAssetRepository — remove 7 `json.dumps()` + 3 enum `.value` sites | 🔲 Blocked by Phase 1 | `infrastructure/asset_repository.py` | Replace `json.dumps(platform_refs)` → `platform_refs` everywhere. Remove enum isinstance checks. Pass raw Python objects — adapter handles serialization. |
| T-TD2.8: PostgreSQLJobRepository — remove json.dumps in create_job/update_job | 🔲 Blocked by Phase 1 | `infrastructure/postgresql.py` | 4 JSONB cols, 2 enums. |
| T-TD2.9: PostgreSQLTaskRepository — remove json.dumps in create_task/update_task | 🔲 Blocked by Phase 1 | `infrastructure/postgresql.py` | 3 JSONB cols, 1 enum. |
| T-TD2.10: ArtifactRepository — remove 6 json.dumps sites | 🔲 Blocked by Phase 1 | `infrastructure/artifact_repository.py` | |
| T-TD2.11: ExternalServiceRepository — remove 4 json.dumps + 2 enum sites | 🔲 Blocked by Phase 1 | `infrastructure/external_service_repository.py` | |
| T-TD2.12: Remaining repos — PlatformRegistry, H3, JobEvent, Metrics, Promoted | 🔲 Blocked by Phase 1 | Various | PromotedDatasetRepository: also remove `Jsonb()` wrapper (inconsistent). |

#### Phase 4: Cleanup Models + Documentation

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.13: Delete `to_dict()` from GeospatialAsset + AssetRevision | 🔲 Blocked by Phase 3 | `core/models/asset.py` | Dead code — no repo calls it. Only remove after Phase 3 confirms model_dump() works everywhere. |
| T-TD2.14: Remove deprecated `json_encoders` from model_config | 🔲 Blocked by Phase 3 | `core/models/asset.py` | Deprecated in Pydantic V2, was dead code already (TODO from 17 FEB 2026). |
| T-TD2.15: Verify `_parse_jsonb_column()` still needed for reads | 🔲 Blocked by Phase 3 | `infrastructure/postgresql.py` | psycopg3 `row_factory=dict_row` auto-parses JSONB on read. If so, `_parse_jsonb_column()` (line 95) is dead code. |
| T-TD2.16: Add pattern to DEV_BEST_PRACTICES.md | 🔲 Ready | `docs_claude/DEV_BEST_PRACTICES.md` | Document: "psycopg3 adapters registered at connection level. NEVER call json.dumps() or .value in repo code. Pass raw Python objects." |

#### Delegation Notes

- **Phase 1**: Ship first and alone. ~10 lines across 2 files. Test by running existing flows — zero behavior change.
- **Phase 2**: Revert the bandaid. Only after Phase 1 is deployed and verified.
- **Phase 3**: Incremental cleanup. One repo per commit. Existing json.dumps calls are harmless, so no urgency — can be done over multiple sessions.
- **Phase 4**: Only after Phase 3 complete. Low priority.
- **Models stay clean**: No `@field_serializer` needed. `model_dump()` returns native Python types. psycopg3 adapter handles serialization at the driver layer.

### EN-TD.3: Multi-App Routing Cleanup `[LOW PRIORITY]`

**Plan**: [MULTI_APP_CLEANUP.md](./MULTI_APP_CLEANUP.md)
**Trigger**: All processing consolidated to Docker worker (V0.8, 24 JAN 2026). Old multi-Function App routing artifacts remain.
**Scope**: Dead queue configs, unused app URLs, `_force_functionapp` override, `WORKER_FUNCTIONAPP` mode, obsolete TaskRecord fields (`target_queue`, `executed_by_app`, `execution_started_at`), 410 endpoint stubs.

| Task | Status | Details |
|------|--------|---------|
| T-TD3.1: Remove deprecated queue names + config fields | 🔲 Ready | `config/queue_config.py`, `config/defaults.py` — 9 dead items |
| T-TD3.2: Remove `_force_functionapp` override | 🔲 Ready | `triggers/submit_job.py`, `core/machine.py` — routes to dead queue |
| T-TD3.3: Remove unused app URLs from AppModeConfig | 🔲 Ready | `config/app_mode_config.py` — `raster_app_url`, `vector_app_url` |
| T-TD3.4: Remove `WORKER_FUNCTIONAPP` mode + `functionapp-tasks` config | 🔲 Ready | `config/app_mode_config.py`, `config/queue_config.py` |
| T-TD3.5: Remove obsolete TaskRecord fields (schema migration) | 🔲 Ready | `core/models/task.py` — requires ALTER TABLE or model-only removal |
| T-TD3.6: Remove 410 Gone endpoint stubs | 🔲 Blocked | `triggers/platform/platform_bp.py` — keep until DDH migration complete |

### EN-TD.1: Raw JSON Parsing in HTTP Triggers `[DONE 12 FEB 2026]`

Migrated 37 occurrences across 22 code files from raw `req.get_json()` to `parse_request_json(req)` with fallback + type guard. See [EN_TD1_JSON_PARSING_MIGRATION.md](./EN_TD1_JSON_PARSING_MIGRATION.md).

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
| 18 FEB 2026 | F7 | dataset_id + resource_id lookup on platform/status (v0.8.19.1) |
| 18 FEB 2026 | F7 | Fix draft self-conflict bypass (empty string vs None) |
| 18 FEB 2026 | F7 | Fix psycopg3 dict adaptation in asset_repository.update() |
| 18 FEB 2026 | EN-TD.2 | Pydantic V2 serialization review + implementation plan |
| 11 FEB 2026 | US 4.2 | Approval consolidation COMPLETE - all 5 phases + post-migration docs verified |
| 10 FEB 2026 | US 4.2.1 | Approval-aware overwrite & version validation |
| 09 FEB 2026 | F7 | Forward FK architecture (V0.8.16) |
| 09 FEB 2026 | F7 | Query param deprecation on platform/status |
| 06 FEB 2026 | US 6.1 | Docker worker required infrastructure |

*For full history, see [HISTORY.md](./HISTORY.md)*
