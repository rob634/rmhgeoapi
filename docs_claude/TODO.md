# Working Backlog - ADO Aligned

**Last Updated**: 14 MAR 2026
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

### US 1.5: VirtualiZarr NetCDF Pipeline ✅ COMPLETE (v0.9.9.0)

5-stage pipeline implemented: scan → copy → validate → combine → register.
Native Zarr ingest (IngestZarr) also added in v0.9.11.8 as 3-stage pipeline.
xarray TiTiler URL injection into STAC items at materialization (v0.9.11.10).
Zarr chunking optimization for tile serving added in v0.9.13.4.

| Task | Status | Details |
|------|--------|---------|
| Kerchunk JSON references for NetCDF | ✅ Done | VirtualiZarr pipeline (v0.9.9.0) |
| TiTiler-xarray integration | ✅ Done | xarray TiTiler URLs injected at STAC materialization (v0.9.11.10) |
| STAC collection with VirtualiZarr assets | ✅ Done | Zarr STAC items created at approval |
| Native Zarr ingest pipeline | ✅ Done | IngestZarr 3-stage pipeline (v0.9.11.8) |
| Zarr chunking optimization | ✅ Done | Optimized chunking (256×256 spatial, time=1, Blosc+LZ4) in both pipelines (v0.9.13.4) |
| Zarr pipeline observability | ✅ Done | Tier 1 progress logging + Tier 2 structured CHECKPOINT events in all zarr handlers (v0.9.16.0) |
| Zarr v3 consolidated metadata fix | ✅ Done | Explicit `zarr.consolidate_metadata()` post-write for Zarr v3 stores — fixes empty variables on TiTiler (v0.9.16.1) |

### US 1.7: Multi-Table Vector Workflows ✅ COMPLETE (v0.10.0.2)

Three patterns for producing multiple TiPG endpoints from vector data:

| Pattern | Status | Description |
|---------|--------|-------------|
| **P2: Split Views** | ✅ Done | Single file → 1 table + N views by categorical column. `split_column` param on `vector_docker_etl`. **Verified end-to-end 10 MAR 2026.** |
| **P1: Multi-file** | ✅ Implemented | N files → N PostGIS tables. `vector_multi_source_docker` job type. Needs live test. |
| **P3: GPKG Multi-layer** | ✅ Implemented | 1 GPKG + `layer_names` → N tables. Same job type as P1. Needs live test. |

| Task | Status | Details |
|------|--------|---------|
| P2 split view implementation | ✅ Done | `services/vector/view_splitter.py` + Phase 3.7 in handler (v0.10.0.1) |
| P2 split view bug fix | ✅ Done | `split_views_result` scope fix in return dict (v0.10.0.2) |
| P2 end-to-end test | ✅ Done | `11_categorized.geojson` with `quadrant` column → 4 views, all live on TiPG |
| P1 multi-file implementation | ✅ Done | `handler_vector_multi_source.py` + validators (v0.10.0.1) |
| P1 end-to-end test | 🔲 Pending | Needs 2+ GeoJSON files in wargames container |
| P3 GPKG multi-layer implementation | ✅ Done | Same handler as P1, uses `pyogrio.list_layers()` (v0.10.0.1) |
| P3 end-to-end test | 🔲 Pending | Needs multi-layer GPKG in wargames container |
| Multi-source unpublish | ✅ Done | 3-stage: inventory → drop → cleanup (v0.10.0.1) |
| Design doc | ✅ Done | `docs/plans/2026-03-08-multi-source-vector-design.md` |

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

### EN-TD.5: PostgreSQL Repository Decomposition ✅ COMPLETE (v0.10.2.0, 14 MAR 2026)

**Scope**: Decompose `PostgreSQLRepository` god class (1,530 lines, 6 concerns) into composable components via internal composition.
**Design**: `docs/superpowers/specs/2026-03-14-postgresql-repository-decomposition-design.md`
**Knowledge**: `V10_POSTGRES.md` (root)

| Task | Status | File | Details |
|------|--------|------|---------|
| Extract `ManagedIdentityAuth` | ✅ Done | `infrastructure/db_auth.py` (326 lines) | Token acquisition, connection string building, auth priority chain |
| Extract `ConnectionManager` | ✅ Done | `infrastructure/db_connections.py` (260 lines) | Pooled/single-use routing, circuit breaker, retry logic |
| Extract shared utilities | ✅ Done | `infrastructure/db_utils.py` (117 lines) | Type adapters, JSONB parsing, connection string redaction |
| Wire into PostgreSQLRepository | ✅ Done | `infrastructure/postgresql.py` | Reduced from ~1,530 to ~820 lines, `conn_string` is `@property` |
| COMPETE adversarial review | ✅ Done | Run 42 | 15 findings fixed, 5 accepted risks, 4 deferred |
| Deploy V0.10.2.0 | ✅ Done | Orchestrator + Docker Worker | Both healthy, schema rebuilt |
| SIEGE regression test | ✅ Done | Run 17 (Run 43) | 92.7% pass rate, zero regressions from decomposition |

### EN-TD.2: psycopg3 Type Adapter + Serialization Cleanup `[NEW 18 FEB 2026]`

**Plan**: [PYDANTIC_REVIEW.md](/PYDANTIC_REVIEW.md) (root)
**Trigger**: Production bug — `assign_version()` passed raw dict to psycopg3 `%s` param, raised `cannot adapt type 'dict'`
**Root cause**: psycopg3 (unlike psycopg2) does not auto-adapt `dict → jsonb`. Fix is to register type adapters at connection level, not scatter `json.dumps()` across 40+ call sites.
**Scope**: 2 connection creation points, then incremental cleanup of 15 repos

#### Phase 1: Register psycopg3 Type Adapters (THE FIX) ✅ COMPLETE

**Completed ~FEB 2026. Adapters registered at both connection paths — all repos inherit automatically.**
**Note**: As of V0.10.2.0, adapters are now in `infrastructure/db_utils.py:register_type_adapters()` (extracted from postgresql.py during EN-TD.5 decomposition).

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.1: Register `JsonbBinaryDumper` for dict+list on single-use connections | ✅ Done | `infrastructure/db_connections.py` | `register_type_adapters(conn)` called in `ConnectionManager._get_single_use_connection()` |
| T-TD2.2: Register `JsonbBinaryDumper` for dict+list on pooled connections | ✅ Done | `infrastructure/connection_pool.py:240-241` | `register_type_adapters(conn)` called in `_configure_connection()` |
| T-TD2.3: Register Enum adapter | ✅ Done | `infrastructure/db_utils.py:35-39` | Custom `_EnumDumper` class registered for `Enum` base class (Option A). |
| T-TD2.4: Verify existing code still works (no repo changes) | ✅ Done | N/A | Deployed and verified — submit, approval, job creation all work. Existing `json.dumps()` calls are harmless. |

**Implementation**: `register_type_adapters()` function in `infrastructure/db_utils.py` registers dict→`JsonbBinaryDumper`, list→`JsonbBinaryDumper`, Enum→`_EnumDumper`.

#### Phase 2: Revert Bandaid + Simplify asset_repository.update()

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.5: Revert isinstance dict/list check in `update()` | 🔲 Ready | `infrastructure/asset_repository.py` | Revert commit `dafc46f` lines 604-608. With adapter registered, dicts pass straight through. Also remove manual enum pre-conversion (lines 592-597). |
| T-TD2.6: Test assign_version + approval end-to-end | 🔲 Ready | N/A | The flow that originally triggered the bug. Must work with raw dicts and enums. |

#### Phase 3: Remove json.dumps() Across Repositories (incremental)

**With adapters registered, all `json.dumps()` calls become unnecessary — they convert dict→string, but psycopg3 now also accepts dicts. Existing calls are harmless but redundant. ~50+ sites across infrastructure repos.**

**IMPORTANT for Claude**: One repo per commit. Test after each. Do NOT batch.

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.7: GeospatialAssetRepository — remove 7 `json.dumps()` + 3 enum `.value` sites | 🔲 Ready | `infrastructure/asset_repository.py` | Replace `json.dumps(platform_refs)` → `platform_refs` everywhere. Remove enum isinstance checks. Pass raw Python objects — adapter handles serialization. |
| T-TD2.8: PostgreSQLJobRepository — remove ~10 json.dumps in job/task CRUD | 🔲 Ready | `infrastructure/postgresql.py` | 4 JSONB cols in create_job, 3 in create_task, plus update paths. |
| T-TD2.9: MapStateRepository — remove ~10 json.dumps sites | 🔲 Ready | `infrastructure/map_state_repository.py` | bounds, layers, custom_attributes, tags, state fields. |
| T-TD2.10: ArtifactRepository — remove 5 json.dumps sites | 🔲 Ready | `infrastructure/artifact_repository.py` | client_refs, metadata fields. |
| T-TD2.11: ExternalServiceRepository — remove 5 json.dumps sites | 🔲 Ready | `infrastructure/external_service_repository.py` | tags, detected_capabilities, health_history, metadata. |
| T-TD2.12: Remaining repos — PlatformRegistry, H3, JobEvent, Janitor, ReleaseAudit, JobsTasks, RasterRender, RasterMetadata | 🔲 Ready | Various | ~15 sites across 8 repos. |

**Note**: `pgstac_repository.py` and `pgstac_bootstrap.py` use `json.dumps()` to build JSON strings for pgSTAC SQL functions — these are NOT redundant and must be kept.

#### Phase 4: Cleanup Models + Documentation

| Task | Status | File | Details |
|------|--------|------|---------|
| T-TD2.13: Delete `to_dict()` from GeospatialAsset + AssetRevision | 🔲 Blocked by Phase 3 | `core/models/asset.py` | Dead code — no repo calls it. Only remove after Phase 3 confirms model_dump() works everywhere. |
| T-TD2.14: Remove deprecated `json_encoders` from model_config | 🔲 Blocked by Phase 3 | `core/models/asset.py` | Deprecated in Pydantic V2, was dead code already (TODO from 17 FEB 2026). |
| T-TD2.15: Verify `_parse_jsonb_column()` still needed for reads | 🔲 Blocked by Phase 3 | `infrastructure/postgresql.py` | psycopg3 `row_factory=dict_row` auto-parses JSONB on read. If so, `_parse_jsonb_column()` (line 128) is dead code. |
| T-TD2.16: Add pattern to DEV_BEST_PRACTICES.md | 🔲 Ready | `docs_claude/DEV_BEST_PRACTICES.md` | Document: "psycopg3 adapters registered at connection level. NEVER call json.dumps() or .value in repo code. Pass raw Python objects." |

#### Delegation Notes

- **Phase 1**: ✅ COMPLETE. Deployed and verified.
- **Phase 2**: Revert the bandaid. Ready now that Phase 1 is live.
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
| T-TD3.6: Remove 410 Gone endpoint stubs | ✅ Done | `triggers/platform/platform_bp.py` — deleted 04 MAR 2026 in platform cleanup (commit `88d7793`) |

### EN-TD.4: Core Orchestration Refactors `[DEFERRED 24 FEB 2026]`

**Source**: Architecture Review 24 FEB 2026 — findings C1.5, C1.8, C2.8
**Reason deferred**: Noncritical changes to core orchestration code paths — high risk, low urgency

| Task | Status | File | Details |
|------|--------|------|---------|
| C1.5: Consolidate repository bundles | 🔲 Deferred | `core/machine.py`, `core/state_manager.py` | Both create independent repo instances via `RepositoryFactory` — works correctly but duplicates objects |
| C1.8: Decompose `process_task_message` | 🔲 Deferred | `core/machine.py:746-1556` | 811-line method (success path + failure path) — most critical code path in the system |
| C2.8: Remove legacy AppConfig property aliases | 🔲 Deferred | `config/app_config.py` | 50+ callers use legacy aliases — too many call sites for safe batch update |
| C8.4: Split `base.py` monolith | 🔲 Deferred | `web_interfaces/base.py` (3,100 lines) | Extract CSS → `design_system.py`, JS → `common_js.py`, navbar → `navbar.py` |

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
| 14 MAR 2026 | Infrastructure | **PostgreSQL decomposition deployed** — god class split into db_auth.py, db_connections.py, db_utils.py. COMPETE reviewed (Run 42), SIEGE regression-free (Run 43). V0.10.2.0. |
| 14 MAR 2026 | Infrastructure | **Connection pool hardening** — orphan-and-sweep pattern, thread-safe drain, circuit breaker integration (v0.10.1.1) |
| 14 MAR 2026 | SIEGE | **SIEGE Run 17** (Run 43): 92.7% pass rate, 101/109 steps. Zero regressions from PostgreSQL decomposition. |
| 13 MAR 2026 | SIEGE | **SIEGE Run 16** (Run 41): Post-deploy smoke test v0.10.0.3, found PostgreSQL OOM + SSL instability |
| 10 MAR 2026 | Vector ETL | **P2 Split Views verified end-to-end** — single file + `split_column` → N PostgreSQL VIEWs as independent TiPG endpoints (v0.10.0.2) |
| 10 MAR 2026 | Vector ETL | Multi-source vector ETL (P1 multi-file + P3 GPKG multi-layer) implemented and deployed (v0.10.0.1) |
| 09 MAR 2026 | Zarr Pipeline | Zarr v3 consolidated metadata fix — explicit `zarr.consolidate_metadata()` post-write, fixes TiTiler empty variables (v0.9.16.1) |
| 09 MAR 2026 | Observability | Zarr pipeline observability — Tier 1 progress logging + Tier 2 CHECKPOINT events in all zarr handlers, `progress` field on platform status (v0.9.16.0) |
| 08 MAR 2026 | SIEGE | SIEGE Run 14 (Run 40): 98.0% pass rate, 17/19 sequences PASS. SG14-1 to SG14-5 findings, 4/5 fixed. |
| 07 MAR 2026 | SIEGE | SIEGE Run 13 (Run 38): 94.9% pass rate. SG13-1 Blosc codec fix, SG13-4 container inference, SG13-6 zarr_format. |
| 05 MAR 2026 | Zarr Pipeline | Zarr chunking optimization — `_build_zarr_encoding()` helper, `ingest_zarr_rechunk` handler, 5 new `ZarrProcessingOptions` fields (v0.9.13.4) |
| 05 MAR 2026 | Error Handling | ERH-5/6: Vector data warnings — structured `NULL_GEOMETRY_DROPPED` + `GEOMETRY_TYPE_SPLIT` in postgis_handler.py, `warnings` field in platform status response |
| 05 MAR 2026 | Raster Pipeline | Deleted `_process_raster_tiled` (~435 lines) — obsolete VSI tiling for Function Apps. Docker worker always uses mount-based tiling. |
| 05 MAR 2026 | Error Handling | ERH-3: Raster error shape parity — `error_code` + `error_category`, `remediation`, `user_fixable` on 27 return paths across raster_validation.py + handler |
| 05 MAR 2026 | Error Handling | ERH-4: Raster misdiagnosis — zero-byte pre-check, error branch reorder, softened network message |
| 05 MAR 2026 | Error Handling | ERH-1: Unknown field rejection — `extra='forbid'` on Pydantic models + `validate_no_extra_fields()` allowlists on 4 raw-dict endpoints |
| 05 MAR 2026 | Error Handling | ADV-8: Platform status `error: null` fix — `error_details` primary source + job metadata block on failure |
| 05 MAR 2026 | Review | ADVOCATE Run 2 (Run 36): Error handling audit — 34 test vectors, 13 findings, score 52% |
| 04 MAR 2026 | Platform | ADV-11: Idempotent submit response includes `job_type` — matches fresh submit shape |
| 04 MAR 2026 | Platform | ADV-12: Fix catalog 500s — `list_dataset_unified()` missing `dict_row` cursor |
| 04 MAR 2026 | OpenAPI | ADV-15: Spec bumped to 0.9.12, +4 endpoints (registry x2, approvals/{id}, catalog/asset/{id}), stale copy deleted |
| 04 MAR 2026 | STAC | ADV-17: Materialization cleans up empty shell collections on item failure |
| 04 MAR 2026 | Platform | ADV-18: Status list enriched with `processing_status`, `approval_state`, `clearance_state` via JOIN |
| 04 MAR 2026 | Platform | ADV-3: Normalize platform response contracts — all `/platform/*` guarantee `{success, error, error_type}` |
| 04 MAR 2026 | Platform | Remove 5 dead endpoints (lineage, validate, 3x deprecated 410s) — ~568 lines deleted |
| 04 MAR 2026 | Platform | ADV-1: Remove dead `job_status_url`, make `monitor_url` absolute |
| 04 MAR 2026 | Audit | Release audit trail — append-only `ReleaseAuditEvent` model + repository |
| 04 MAR 2026 | Approval | Stale ordinal guard fix (positional row indexing) + in-place revision exemption |
| 04 MAR 2026 | Approval | `can_overwrite()` accepts REVOKED for in-place ordinal revision |
| 03 MAR 2026 | EN-TD.2 | Phase 1 COMPLETE: psycopg3 type adapters registered at connection level |
| 02 MAR 2026 | Reliability | DB token refresh fix for Docker worker (startup + per-message freshness) |
| 02 MAR 2026 | Reliability | Compensating cleanup for orphaned releases on job creation failure |
| 02 MAR 2026 | Observability | OBSERVATORY diagnostic gaps — 3 P0 bugs + 5 observability enhancements |
| 01 MAR 2026 | Zarr | Zarr service layer: native ingest pipeline + xarray TiTiler URLs |
| 01 MAR 2026 | Zarr | B2C/B2B route models for URL resolution |
| 28 FEB 2026 | Dashboard | Web dashboard submit form with file browser (GREENFIELD Run 24) |
| 28 FEB 2026 | Dashboard | Storage browser + Queue monitoring panels (v0.9.11.7) |
| 27 FEB 2026 | Dashboard | Web dashboard v1 (GREENFIELD Run 19) — 4 tabs, HTMX SPA |
| 26 FEB-04 MAR | Review | Agent review campaign: 33 runs, 7 pipelines, ~6.5M tokens |
| 18 FEB 2026 | F7 | dataset_id + resource_id lookup on platform/status (v0.8.19.1) |
| 18 FEB 2026 | EN-TD.2 | Pydantic V2 serialization review + implementation plan |
| 11 FEB 2026 | US 4.2 | Approval consolidation COMPLETE - all 5 phases + post-migration docs verified |

*For full history, see [HISTORY.md](./HISTORY.md)*
