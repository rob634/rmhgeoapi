# COMPETE DAG Series — Comprehensive Summary

**Date**: 28-29 MAR 2026
**Version**: v0.10.9.0 → v0.10.9.6
**Total scope**: ~33,000 lines across ~75 DAG-specific files, 9 review targets
**Status**: **ALL 9 TARGETS COVERED AND FIXED. SIEGE-DAG Run 2 pending (code analysis in progress).**

---

## Session Runs (This Conversation)

| Run | Target | Lines | CRIT | HIGH | MED | Fixed | Key Finding |
|-----|--------|-------|------|------|-----|-------|-------------|
| 59 | T1: Engine Orchestration | 2,206 | 0 | 4 | 11 | 15 | Zombie run on max_cycles_exhausted |
| 60 | T2: Init & Params | 1,775 | 1 | 3 | 6 | 10 | schedule_id silently dropped on INSERT |
| 62 | T3: Persistence & Ops | 3,936 | 0 | 0 | 3 | 3 | Missing indexes (status partial, schedule_id) |
| 64 | T4: Raster Handlers | 2,939 | 1 | 2 | 2 | 5 | Tiled path no STAC materialization |
| 65 | T5: Vector Handlers | 6,612 | 2 | 2 | 2 | 7 | row_count key mismatch + split_column nesting |
| 66 | T6: Zarr + STAC | 2,691 | 0 | 2 | 2 | 4 | ds.coords after close + missing geoetl:data_type |
| **Total** | | **20,159** | **4** | **13** | **26** | **44** | |

## Prior Session Runs (Other Conversations)

| Run | Target | CRIT | HIGH | MED | Fixes |
|-----|--------|------|------|-----|-------|
| 58 | T7: Platform API | 1 | 5 | 8 | 11 (on branch) |
| 61 | T8: Approval & Unpublish | 1 | 13 | 8 | 10 (on branch) |
| 63 | T9: Workflow YAML | 1 | 1 | 5 | 4 + 2 dead files removed |

## Grand Total

| Metric | Value |
|--------|-------|
| **Targets** | 9/9 covered |
| **Lines reviewed** | ~33,000 |
| **Total findings** | ~150 across all runs |
| **Fixes applied this session** | 44 |
| **Fixes applied other sessions** | 25 |
| **New files created** | 1 (`core/dag_repository_protocol.py`) |
| **Dead files removed** | 2 (other session) |

---

## SIEGE-DAG Integration Testing (29 MAR 2026)

### What Happened

After deploying COMPETE fixes (v0.10.9.2), SIEGE-DAG Run 2 exposed **9 integration bugs** that only manifest at deployment time — not visible in code review or local testing. These were iteratively fixed across v0.10.9.2 → v0.10.9.6.

### Bugs Found and Fixed During SIEGE

| # | Bug | Root Cause | Version Fixed |
|---|-----|-----------|---------------|
| SIEGE-1 | Brain marks every run FAILED after 1 cycle | T1 zombie-run fix fires in Brain's `max_cycles=1` single-tick mode | v0.10.9.3 |
| SIEGE-2 | Brain health: `workflows_dir` NameError | Variable never defined in `_check_workflow_registry()` | v0.10.9.3 |
| SIEGE-3 | Registry: one bad YAML blocks all workflows | `load_all()` fails fast on first error | v0.10.9.3 |
| SIEGE-4 | Brain health: `datetime - string` TypeError | `last_scan_at` is ISO string, not datetime object | v0.10.9.4 |
| SIEGE-5 | `orchestrator_lease` missing after rebuild | Table not registered in DDL generator | v0.10.9.4 |
| SIEGE-6 | `zarr_metadata` missing PRIMARY KEY | Not in DDL generator's hardcoded PK list; `ON CONFLICT` silently failed | v0.10.9.6 |
| SIEGE-7 | DAG approval blocked (`processing_status != completed`) | Guard assumes Epoch 4 model; DAG runs are `processing` at approval gate | v0.10.9.6 |
| SIEGE-8 | `download_to_mount` fails on existing directory | `Path.exists()` called on string; no overwrite for ephemeral mount data | v0.10.9.6 |
| SIEGE-9 | BS3 when-clause fails tasks instead of skipping | Skip-vs-fail logic didn't check if predecessor was SKIPPED (conditional routing) | v0.10.9.6 |

### Key Lesson

COMPETE catches design/correctness bugs in isolation. SIEGE catches integration bugs that emerge from the interaction between components at deployment time. Both are necessary — COMPETE alone was insufficient. The 9 SIEGE bugs include:
- **3 DDL/schema gaps** (lease table, zarr PK, hardcoded PK list)
- **3 health check bugs** (NameError, datetime parse, fail-fast registry)
- **2 Epoch 4→5 design mismatches** (single-tick mode, approval guard)
- **1 handler bug** (mount overwrite)

### SIEGE-DAG Run 2 — Partial Results Before Pause

| Seq | Status | Notes |
|-----|--------|-------|
| D1 Raster | **PASS** (pre-approval) | Completed, at approval gate |
| D2 Vector | Unknown | Resubmitted on v0.10.9.6, results pending |
| D3 NetCDF | Unknown | Resubmitted on v0.10.9.6, results pending |
| D4 Native Zarr | Unknown | Resubmitted on v0.10.9.6, results pending |
| D5 Multiband | **PASS** (pre-approval) | Completed, at approval gate |
| D6-D8 Unpublish | Not attempted | Depend on D1-D3 approved |
| D9 Progress | Not attempted | |
| D10 Error | Submitted | Pending (nonexistent file retrying) |
| D11 Rejection | **PASS** | Completed + rejected successfully |
| D12-D19 Lifecycle | Not attempted | |

### What Is Verified

- Brain orchestration loop works (runs advance through tasks correctly)
- D1 raster single-COG path completes all 10 pre-approval tasks
- D5 multiband raster completes pre-approval
- D11 rejection path works end-to-end
- Schema rebuild creates all 34 tables with correct PKs
- Health check reports degraded mode with detailed error info
- Finalize handler dispatch fires at all 3 terminal paths

### What Is Unknown / Untested

1. **D2 vector approval flow** — approval guard fix deployed but never tested E2E
2. **D3 NetCDF zarr** — zarr_metadata PK fix deployed but upsert not verified E2E
3. **D4 native Zarr** — mount overwrite fix deployed but download not verified E2E
4. **D6-D8 unpublish** — never attempted
5. **D11-D19 lifecycle parity** — only D11 (rejection) completed
6. **`platform_job_submit` singleton** — changed to `get_workflow_registry()`, untested in production

### Next Steps

**SIEGE-DAG Run 2 will be rerun completely from scratch** after current code analysis and debugging work is complete. All 9 SIEGE bugs are fixed and deployed (v0.10.9.6). Clean schema rebuild + geo nuke before rerun. All D1-D19 sequences to be executed fresh.

---

## Previously Resolved (28 MAR 2026)

| Item | Source | Resolution |
|------|--------|------------|
| Finalize handler never invoked | T5 Run 65, HIGH-2 | **FIXED** — added `_dispatch_finalize()` to `dag_orchestrator.py` at all 3 terminal exit paths |
| Tiled STAC materialization (DF-RASTER-1) | T9 Run 63, CRITICAL | **FIXED** in T4 Run 64 — added `materialize_tiled_items` node |

---

## Deferred Issues (v0.10.10 or Later)

### v0.10.10 Deferred (Before DAG Switchover)

| Source | Issue | Why Deferred | Revisit |
|--------|-------|-------------|---------|
| T6 MED-2 | Post-hoc builder mutation + Azure account_name in stac_item_json | Requires materialization architecture change | Before B2C exposure |
| T6 MED-4 | Temporal interval sentinel datetime | Cosmetic, pgSTAC handles correctly | Before B2C exposure |
| T5 MED-1 | TiPG refresh returns `success: True` on total failure | Design intent, documented | If preview UX is critical |

### Accepted Risks (All Targets)

| Target | Count | Key Risks |
|--------|-------|-----------|
| T1 | 3 | Disabled descendant propagation (design), unused optional_deps param, time.sleep blocks thread |
| T2 | 5 | task_instance_id length, gate_type not persisted, ParameterDef.type unenforced, incomplete cycle detection (loader catches), Jinja2 NativeEnvironment |
| T3 | 4 | Scheduler TOCTOU (single-writer Brain), janitor retry off-by-one, JSONB casting inconsistency, holder_id collision |
| T4 | 3 | CRS string equality, no dry_run in raster handlers, upload deletes source |
| T5 | 2 | Multi-group partial failure, private API chaining |
| T6 | 5 | Non-transactional collection+item write, connection pool pressure, sentinel datetime, vnd+zarr media type, EPSG:4326 hardcoded in pyramid |
| **Total** | **22** | |

### LOWs Left in Place (All Targets)

| Target | Count | Examples |
|--------|-------|---------|
| T1 | 7 | Dead constant, dead variable, disabled propagation code, no result_data on conditionals |
| T2 | 7 | Incomplete cycle detection (mitigated), get_root_nodes mismatch, Jinja2 syntax not load-validated |
| T3 | 11 | set_task_parameters no guard (safe alternative in use), Python timestamps in claim, dead code (2 methods) |
| T4 | 0 | (all LOW findings rejected or subsumed) |
| T5 | 3 | Epoch 4 flags (NaT, trailing comma, mutable set) |
| T6 | 0 | (all LOW findings accepted as risks) |
| **Total** | **~28** | |

---

## Epoch 4 Flags (Not Fixed — Expected Defects)

These were found in Epoch 4 bridge code within Epoch 5 files. Not fixed because Epoch 4 is in maintenance mode (S5.4). They will be removed with the strangler fig completion (v0.11.0).

| File | Issue |
|------|-------|
| `postgis_handler.py` | `insert_features_with_metadata` no NaT-to-None protection |
| `postgis_handler.py` | Empty column list trailing comma in `_create_table_if_not_exists` |
| `postgis_handler.py` | Mutable set for reserved columns |
| `dag_janitor.py` | `_sweep_legacy_tasks` instantiates TaskRepository per sweep |
| `workflow_run_repository.py` | `get_stale_legacy_tasks` and `legacy_job_id` column |

---

## Single-Database Lens Results

The core principle — "state lives in one database and that database solves 80% of distributed system problems" — was validated across all 6 targets reviewed this session:

| Target | Verdict |
|--------|---------|
| T1 | **Clean** — no Service Bus scar tissue. Engines are pure logic, DB mutations via CAS-guarded repo. |
| T2 | **Clean** — atomic insertion, deterministic IDs, YAML→DB in single transaction. |
| T3 | **Gold standard** — SKIP LOCKED, advisory locks, CAS guards, lease-based single-writer. The DB IS doing the coordination. |
| T4 | **Clean** — no broker patterns. State flows through handler params + PostgreSQL + pgSTAC. |
| T5 | **Clean** — PostGIS IS the database. Per-chunk commit with batch IDs. SQL injection guards. |
| T6 | **Clean** — pgSTAC upsert idempotent. STAC materialization is a DB projection of internal metadata. |

**Overall**: The Epoch 5 DAG implementation has successfully eliminated Service Bus coordination. The database is the single source of truth for workflow state, task dispatch, and coordination.

---

## Files Modified This Session

| Category | Files |
|----------|-------|
| **Core engine** | `dag_orchestrator.py`, `dag_transition_engine.py`, `dag_fan_engine.py`, `dag_graph_utils.py`, `param_resolver.py`, `dag_scheduler.py` |
| **New file** | `dag_repository_protocol.py` |
| **Infrastructure** | `workflow_run_repository.py` |
| **Models** | `workflow_definition.py`, `workflow_run.py` |
| **Loader** | `workflow_loader.py` |
| **Raster handlers** | `handler_create_cog.py`, `handler_process_single_tile.py`, `handler_persist_tiled.py` |
| **Vector handlers** | `handler_register_catalog.py`, `handler_create_split_views.py`, `handler_validate_and_clean.py`, `postgis_handler.py`, `view_splitter.py` |
| **Zarr/STAC handlers** | `handler_register.py`, `handler_materialize_item.py` |
| **Workflows** | `process_raster.yaml`, `ingest_zarr.yaml`, `vector_docker_etl.yaml` |

---

## Report Files

| Target | Report |
|--------|--------|
| T1 | `docs/agent_review/COMPETE_T1_DAG_ENGINE.md` |
| T2 | `docs/agent_review/COMPETE_T2_DAG_INIT.md` |
| T3 | `docs/agent_review/COMPETE_T3_DAG_PERSISTENCE.md` |
| T4 | `docs/agent_review/COMPETE_T4_RASTER.md` |
| T5 | `docs/agent_review/COMPETE_T5_VECTOR.md` |
| T6 | `docs/agent_review/COMPETE_T6_ZARR_STAC.md` |
| T7 | (other session — on branch `fix/compete-t7-t8-findings`) |
| T8 | (other session — on branch `fix/compete-t7-t8-findings`) |
| T9 | (other session) |
| **Series tracker** | `docs/agent_review/agents/COMPETE_DAG_SERIES.md` |
| **Run log** | `docs/agent_review/AGENT_RUNS.md` (Runs 59, 60, 62, 64, 65, 66) |
