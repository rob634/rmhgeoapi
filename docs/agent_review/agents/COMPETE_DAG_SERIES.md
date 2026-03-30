# COMPETE DAG Series — Comprehensive Epoch 5 Review

**Purpose**: Master tracking file for a systematic COMPETE review of the entire Epoch 5 DAG implementation. Any Claude instance can pick up this file, read the target definitions, and execute a review run.

**Created**: 28 MAR 2026
**Version at creation**: v0.10.8.2
**Total scope**: ~50,000 lines across ~115 files, organized into 10 review targets (T1-T9: DAG implementation, T10: infrastructure & diagnostics).

---

## How to Use This File

1. **Pick a target** from the table below (status = NOT STARTED or NEEDS RE-REVIEW)
2. **Read the target section** for file list, line counts, split recommendation, and constitutional focus
3. **Execute the COMPETE pipeline** per `docs/agent_review/agents/COMPETE_AGENT.md`
4. **Log the run** in `docs/agent_review/AGENT_RUNS.md` (next available run number)
5. **Update the status table** below with run number, date, and findings count
6. **Apply fixes** and mark them in the target section

---

## Target Status

| # | Target | Lines | Files | Split | Prior Coverage | Status | Run # | Findings |
|---|--------|-------|-------|-------|----------------|--------|-------|----------|
| T1 | DAG Engine — Orchestration & State | 2,206 | 4+1 | A | Runs 47, 53, 54, **59** | **COVERED — ALL FIXED** | 59 | 18 found, 15 fixed (4H+11M), 3 accepted, 7 LOW in place |
| T2 | DAG Engine — Init & Param Resolution | 1,775 | 9 | C | Runs 46, 55, **60** | **COVERED — ALL FIXED** | 60 | 17 found, 10 fixed (1C+3H+6M), 5 accepted, 7 LOW in place |
| T3 | DAG Engine — Persistence & Operations | 3,936 | 6 | C | Runs 46, 47, 53, 54, 57, **62** | **COVERED — ALL FIXED** | 62 | 14 found, 3 fixed (3M), 4 accepted, 11 LOW in place |
| T4 | Raster Handler Chain | 2,939 | 10 | B | Runs 50, 51, 55, **64** | **COVERED — ALL FIXED** | 64 | 10 found, 5 fixed (1C+2H+2M), 3 accepted |
| T5 | Vector Handler Chain | 6,612 | 12 | B | Runs 48, 49, **65** | **COVERED — ALL FIXED** | 65 | 14 found, 7 fixed (2C+1H+2M+2L), 2 accepted, 1 engine gap tracked |
| T6 | Zarr + STAC Handler Chain | 2,691 | 12 | A | Runs 52, 56, **66** | **COVERED — ALL FIXED** | 66 | 13 found, 4 fixed (2H+2M), 5 accepted, 2 deferred v0.10.10 |
| T7 | Platform API Surface | 6,426 | 8 | D | Run 58 (28 MAR) | **COVERED** | 58 | 31 unique (1 CRIT, 5 HIGH, 8 MED, 5 LOW) |
| T8 | Approval & Unpublish Lifecycle | 5,935 | 8 | A | Run 61 (28 MAR) | **COVERED** | 61 | 26 unique (1 CRIT, 13 HIGH, 8 MED, 1 LOW) |
| T9 | Workflow YAML Definitions | 610 | 10 | B | Run 63 (28 MAR) | **COVERED** | 63 | 9 unique (1 CRIT backlogged, 1 HIGH, 5 MED, 2 LOW) |
| T10 | Infrastructure & Diagnostics | ~17,200 | 43 | Split into T10a-T10d | Run 67: T10c (29 MAR) | **PARTIAL — T10c COVERED** | 67 | 22 found, 18 fixed (1C+5H+9M+1refactor+2L), 4 accepted |

**Legend**: COVERED = reviewed within last 2 weeks, no outstanding CRITICALs. PARTIAL = reviewed but scope incomplete or significant code changes since. NOT STARTED = never reviewed as this target scope.

---

## Execution Order

```
Phase 1 — COMPLETED:
  T1: DAG Engine — Orchestration & State .. Run 59 (28 MAR), 18 findings, 0 CRIT ✓
  T2: DAG Engine — Init & Param Resolution  Run 60 (28 MAR), 17 findings, 1 CRIT ✓
  T7: Platform API Surface ............... Run 58 (28 MAR), 31 findings, 1 CRIT ✓
  T8: Approval & Unpublish Lifecycle ..... Run 61 (28 MAR), 26 findings, 1 CRIT ✓

Phase 2 — COMPLETED:
  T3: DAG Engine — Persistence .......... Run 62 (28 MAR), 14 findings, 0 CRIT ✓
  T4: Raster Handler Chain .............. Run 64 (29 MAR), 10 findings, 0 CRIT ✓
  T5: Vector Handler Chain .............. Run 65 (29 MAR), 14 findings, 0 CRIT ✓
  T6: Zarr + STAC Handler Chain ......... Run 66 (29 MAR), 13 findings, 0 CRIT ✓
  T9: Workflow YAML Definitions ......... Run 63 (28 MAR), 9 findings, 0 CRIT ✓

Phase 3 — NEW:
  T10a: Preflight + Health Framework .... ~5,500 lines, 16 files, Split D (Security vs Functionality)
  T10b: Docker Health + Startup ......... ~4,300 lines, 13 files, Split A (Design vs Runtime)
  T10c: Database Admin & Diagnostics .... ~4,600 lines, 4 files, Split C (Data vs Control)
  T10d: Observability & External Services ~2,800 lines, 7 files, Split B (Internal vs External)
```

**T10 is the remaining unreviewed scope.** 43 files across infrastructure/diagnostics — never COMPETE-reviewed. Split into 4 sub-targets for execution.

---

## Target Definitions

---

### T1: DAG Engine — Orchestration & State Machine

**What this is**: The "brain" of the DAG system. Pure orchestration logic — state machine transitions, fan-out/fan-in expansion, graph traversal. No I/O, no HTTP, no handlers.

**Prior coverage**: Run 47 (16 MAR), Run 53 (24 MAR), Run 54 (26 MAR), **Run 59 (28 MAR, COMPETE DAG Series T1)**. All CRITICALs resolved. All MEDIUM+ fixed.

**Run 59 scope**: Epoch 5 only (4 DAG files). Split A (Design vs Runtime) + Single-Database Lens. Excluded Epoch 4 files (orchestration_manager.py, state_manager.py) — those are expected to have legacy Service Bus defects.

**Split used**: A (Design vs Runtime)
- Alpha: Composition, contracts, layering, Single-Database Lens (architectural scar tissue)
- Beta: Race conditions, state machine completeness, error recovery, Single-Database Lens (unnecessary guards)

| File | Lines | Role |
|------|-------|------|
| `core/dag_transition_engine.py` | 504 | PENDING→READY promotion, when-clause eval, skip propagation |
| `core/dag_orchestrator.py` | 571 | Poll-loop lifecycle (transitions → conditionals → fans) |
| `core/dag_fan_engine.py` | 790 | Fan-out expansion, fan-in aggregation |
| `core/dag_graph_utils.py` | 337 | Adjacency, predecessor lookup, terminal detection |
| **NEW** `core/dag_repository_protocol.py` | ~60 | DAGRepositoryProtocol — typed contract (13 methods) |

**Constitutional focus**: P6 (composable atomic units), P8 (database is coordination layer), P9 (correctness under concurrency), P10 (explicit data contracts), P11 (traceable state changes), S1.2 (SQL composition), S4 (import layering)

**Known accepted risks** (Run 59 — 3 remaining):
- `_skip_task_and_descendants` descendant propagation intentionally disabled — design choice, not dead code
- `all_predecessors_terminal` accepts unused `optional_deps` param — logic lives in caller (`evaluate_transitions:391-406`)
- `time.sleep` blocks thread (5s max shutdown delay) — not operationally significant

**Prior accepted risks now FIXED in Run 59**:
- ~~Stale snapshot across engines~~ → Conditional re-fetch between transition and conditional/fan phases
- ~~Per-call repo instantiation~~ → Lazy-init `_get_release_repo()` on orchestrator

**LOWs left in place** (7): `_SYSTEM_MAX_FAN_OUT` dead constant, unused `optional_deps` param, partially dead `_build_optional_deps`, disabled descendant propagation code, `name_to_task` dead variable, `time.sleep` blocks thread, `evaluate_conditionals` stores no result_data.

**Re-review trigger**: Any change to dag_orchestrator.py, dag_transition_engine.py, or dag_fan_engine.py.

---

### T2: DAG Engine — Initialization & Parameter Resolution

**What this is**: How YAML workflow definitions become live runs. Parsing, validation, deterministic ID generation, Jinja2 parameter templating.

**Prior coverage**: Run 46 (16 MAR), Run 55 (26 MAR), **Run 60 (28 MAR, COMPETE DAG Series T2)**. All MEDIUM+ fixed.

**Run 60 scope**: Split C (Data vs Control Flow) + Single-Database Lens. 9 files, ~1,775 lines.

**Split used**: C (Data vs Control Flow)
- Alpha: Parameter resolution correctness, Jinja2 edge cases, model completeness, schema alignment
- Beta: Malformed YAML handling, circular deps, missing params, ID collisions, atomic insertion

| File | Lines | Role |
|------|-------|------|
| `core/dag_initializer.py` | 420 | YAML → WorkflowRun + tasks atomically |
| `core/param_resolver.py` | 291 | Jinja2 resolution from job_params + predecessor outputs |
| `core/workflow_loader.py` | 328 | Parse + validate YAML definitions (now 11 validations) |
| `core/workflow_registry.py` | 151 | Available workflow catalog |
| `core/models/workflow_definition.py` | 200 | Pydantic schema for YAML nodes/params (now all extra='forbid') |
| `core/models/workflow_enums.py` | 81 | Status enums |
| `core/models/workflow_run.py` | 102 | WorkflowRun entity |
| `core/models/workflow_task.py` | 145 | WorkflowTask entity |
| `core/models/workflow_task_dep.py` | 57 | Dependency edges |

**Also modified** (fixes touched these files outside T2 scope):
- `infrastructure/workflow_run_repository.py` — schedule_id INSERT/SELECT fix
- `core/dag_scheduler.py` — ParameterDef default application
- `core/dag_fan_engine.py` — `strict=True` for conditional resolution
- `workflows/ingest_zarr.yaml` — undeclared release_id fix

**Constitutional focus**: P1 (explicit failure), P10 (explicit data contracts), S1.1 (zero-tolerance), S3.1 (exception hierarchy), S6 (database patterns)

**Known accepted risks** (Run 60 — 5 remaining):
- `task_instance_id` can exceed 100 chars if node name > 87 chars (all current < 30)
- `gate_type` lost in task materialization (only "approval" exists)
- `ParameterDef.type` not enforced at runtime (handlers validate own inputs)
- Incomplete cycle detection in initializer (loader catches all cycles)
- Jinja2 NativeEnvironment allows Python eval (trusted YAML only)

**Prior accepted risks from Runs 46/55** (still valid):
- Deterministic run_id causes silent resubmit rejection — Run 46
- uuid4 fan-out children (non-deterministic by design) — Run 46
- Loader doesn't validate receives dotted path depth — Run 55

**LOWs left in place (7)**: Incomplete cycle detection (mitigated), get_root_nodes() mismatch, Jinja2 syntax not validated at load, FanOut Jinja2 refs unchecked, GateNode max_retries fallthrough, NativeEnvironment (trusted YAML), singleton race (benign).

**Re-review trigger**: New workflow YAML added, or changes to param_resolver.py or dag_initializer.py.

---

### T3: DAG Engine — Persistence, Leasing & Operations

**What this is**: Database layer for DAG state. Atomic CRUD, distributed leases, background housekeeping (janitor, scheduler). The "plumbing" that makes orchestration durable.

**Prior coverage**: Runs 46, 47, 53, 54, 57, **Run 62 (28 MAR, COMPETE DAG Series T3)**. All MEDIUM+ fixed.

**Run 62 scope**: Split C (Data vs Control Flow) + Single-Database Lens. 6 files, ~3,936 lines. Epoch 5 focus — Epoch 4 bridge code noted but not analyzed.

**Split used**: C (Data vs Control Flow)
- Alpha: FK ordering, SKIP LOCKED correctness, enum alignment, schema DDL, type adapters, NULL handling
- Beta: Lease races, janitor vs active handler, scheduler double-fire, connection lifecycle, error recovery

**Known accepted risks** (Run 62 — 4 remaining):
- Scheduler double-fire TOCTOU (single-writer Brain prevents; minute-level request_id traceable)
- Janitor retry_count off-by-one (lease prevents concurrent janitors; one extra retry harmless)
- Inconsistent JSONB casting INSERT vs UPDATE (cosmetic; both work correctly)
- holder_id hostname:pid collision in containers (TTL lease prevents stale holders)

**Prior accepted risks resolved**:
- ~~expand_fan_out no CAS~~ — FIXED in T1 Run 59
- ~~schedule_id not persisted~~ — FIXED in T2 Run 60

**LOWs left in place (11)**: set_task_parameters no status guard (safe alternative in use), Python timestamps in claim (worker doesn't use for timing), get_predecessor_outputs dead code + dict collision, _workflow_task_from_row .get() defaults, _get_stale_query dead code, lease_repository dict_row redundancy, aggregate_fan_in no rowcount check.

**Re-review trigger**: Any change to workflow_run_repository.py or schema DDL.

---

### T4: Raster Handler Chain

**What this is**: End-to-end raster pipeline — download from bronze, validate CRS/bands/nodata, create COG (single or tiled), upload to silver, persist app tables, STAC materialization.

**Prior coverage**: Run 50 (DECOMPOSE, 21 MAR, extracted 5 handlers), Run 51 (COMPETE, 21 MAR, Split C, 16 findings), Run 55 (COMPETE, 26 MAR, tiled path, 16 findings). All CRITICALs resolved.

**Recommended split**: B (Internal vs External)
- Alpha: Internal correctness — COG creation, reprojection math, nodata handling, pixel windows
- Beta: External contracts — blob naming, STAC item shape, what YAML `receives` vs what handler produces

| File | Lines | Role |
|------|-------|------|
| `services/raster/handler_download_source.py` | 270 | Bronze → mount |
| `services/raster/handler_validate.py` | 388 | CRS, bands, nodata, file_size detection |
| `services/raster/handler_create_cog.py` | 571 | COG creation + reprojection |
| `services/raster/handler_upload_cog.py` | 366 | COG → silver blob storage |
| `services/raster/handler_persist_app_tables.py` | 423 | App table writes (single COG path) |
| `services/raster/handler_persist_tiled.py` | 244 | App table writes (tiled path) |
| `services/raster/handler_generate_tiling_scheme.py` | 150 | Tile grid computation |
| `services/raster/handler_process_single_tile.py` | 270 | Individual tile processing (fan-out child) |
| `services/raster/handler_finalize.py` | 83 | Mount cleanup |
| `workflows/process_raster.yaml` | 174 | Conditional routing (size-based), fan-out, approval gate, STAC |

**Constitutional focus**: P2 (deterministic materialized views), P6 (composable atomics), P10 (explicit data contracts), S9.2 (handler return contracts)

**Known accepted risks** (from Runs 51/55):
- Non-composable tile handler (create+upload in one) — Run 55
- Context param unused (future-proofing) — Run 51
- Partial persist success returns `success: True` — Run 55

**Re-review trigger**: Changes to COG creation logic, new raster processing options, or tiling scheme changes.

---

### T5: Vector Handler Chain

**What this is**: End-to-end vector pipeline — download source, validate geometry/schema, create PostGIS tables, create split views, TiPG two-phase discovery, catalog registration.

**Prior coverage**: Run 48 (DECOMPOSE, 19 MAR, extracted 3 handlers), Run 49 (COMPETE, 20 MAR, Split C, 22 findings on first 3 handlers). **Handlers 4-7 and support modules never COMPETE-reviewed.**

**Why PARTIAL**: Run 49 only covered `handler_load_source`, `handler_validate_and_clean`, `handler_create_and_load_tables`. The remaining handlers (`handler_create_split_views`, `handler_refresh_tipg`, `handler_register_catalog`, `handler_finalize`) plus the support modules (`postgis_handler.py`, `view_splitter.py`, `converters.py`, `column_sanitizer.py`) and the v3 YAML (with TiPG two-phase) have never been reviewed together.

**Recommended split**: B (Internal vs External)
- Alpha: Internal correctness — PostGIS type mapping, geometry repair, column sanitization, view creation SQL
- Beta: External contracts — TiPG two-phase (preview vs searchable), STAC registration, OGC Features compliance, handler result shapes

| File | Lines | Role |
|------|-------|------|
| `services/vector/handler_load_source.py` | 415 | File download + format detection |
| `services/vector/handler_validate_and_clean.py` | 818 | Schema validation, geometry repair |
| `services/vector/handler_create_and_load_tables.py` | 776 | PostGIS table creation + bulk COPY |
| `services/vector/handler_create_split_views.py` | 120 | Country/region split views |
| `services/vector/handler_refresh_tipg.py` | 89 | TiPG service refresh (two-phase: preview + searchable) |
| `services/vector/handler_register_catalog.py` | 181 | STAC + catalog registration |
| `services/vector/handler_finalize.py` | 83 | Mount cleanup |
| `services/vector/postgis_handler.py` | 2,618 | Core PostGIS operations engine |
| `services/vector/view_splitter.py` | 459 | View creation logic |
| `services/vector/converters.py` | 786 | Format conversion (GeoPackage, Shapefile, etc.) |
| `services/vector/column_sanitizer.py` | 175 | Column name cleaning for PostGIS |
| `workflows/vector_docker_etl.yaml` | 92 | v3: Two-phase TiPG + approval gate |

**Note**: This is the largest target (6,612 lines). If token budget is tight, split into:
- **T5a** (handlers only): 7 handler files + YAML = 2,574 lines
- **T5b** (infrastructure): postgis_handler + view_splitter + converters + column_sanitizer = 4,038 lines

**Constitutional focus**: P1 (explicit failure on bad geometry), P3 (unidirectional data flow), P5 (paired lifecycle — must have unpublish), P6 (composable atomics), S1.2 (SQL composition in PostGIS operations)

**Known accepted risks** (from Run 49):
- Multi-group partial failure — returns partial result without explicit failure status
- Private API chaining — tightly coupled handler internal method calls

**Re-review trigger**: Changes to TiPG two-phase logic, PostGIS type mapping, or view creation.

---

### T6: Zarr + STAC Handler Chain

**What this is**: Zarr ingestion pipeline (NetCDF and native Zarr paths) plus STAC materialization (shared by all data types — raster, vector, zarr).

**Prior coverage**: Run 52 (COMPETE, 23 MAR, producer/consumer split, 14 findings), Run 56 (COMPETE, 26 MAR, STAC consolidation review, 15 findings). All CRITICALs fixed.

**Recommended split**: A (Design vs Runtime)
- Alpha: Design — STAC spec compliance, pyramid store structure, spatial extent extraction, builder purity
- Beta: Runtime — xarray open failures, partial pyramid, STAC upsert races, pgSTAC write errors

| File | Lines | Role |
|------|-------|------|
| `services/zarr/handler_download_to_mount.py` | 171 | Zarr/NC → mount (prefix download) |
| `services/zarr/handler_validate_source.py` | 211 | xarray validation, spatial extent extraction |
| `services/zarr/handler_generate_pyramid.py` | 225 | Pyramid store generation (datatree) |
| `services/zarr/handler_register.py` | 292 | Zarr metadata + STAC item cache in release |
| `services/zarr/handler_batch_blobs.py` | 72 | Batch blob upload to silver |
| `services/stac/handler_materialize_item.py` | 154 | pgSTAC item upsert |
| `services/stac/handler_materialize_collection.py` | 114 | pgSTAC collection upsert |
| `services/stac/stac_item_builder.py` | 196 | STAC item JSON construction (pure function) |
| `services/stac/stac_collection_builder.py` | 58 | STAC collection JSON (pure function) |
| `services/stac_materialization.py` | 1,048 | Shared materialization logic (6-step sequence) |
| `workflows/ingest_zarr.yaml` | 108 | NC/Zarr conditional routing + pyramid + STAC |
| `workflows/unpublish_zarr.yaml` | 42 | Zarr unpublish flow |

**Constitutional focus**: P2 (deterministic materialized views), P5 (paired lifecycle), P10 (explicit data contracts), S3.1 (exception hierarchy)

**Known accepted risks** (from Runs 52/56):
- Non-transactional collection+item write (upsert is idempotent) — Run 56
- `_inject_xarray_urls` signature mismatch — Run 56 CRITICAL (verify fix)
- `_is_vector_release` fallback heuristic — Run 56 H3
- Connection pool pressure per-operation — Run 56

**Re-review trigger**: New data type support, changes to STAC builders or materialization path.

---

### T7: Platform API Surface ⚠️ PRIORITY — NEVER REVIEWED

**What this is**: The HTTP contract layer — how external systems (and the web UI) submit workflows, poll status, query catalogs, and resubmit failed runs. This is the B2B surface.

**Prior coverage**: Run 58 (28 MAR 2026, Split D, 31 findings, 11 fixes recommended). 1 CRITICAL (f-string SQL), 5 HIGH, 8 MEDIUM. Key findings: f-string SQL in platform_failures, update_workflow_id orphan risk, unpublish dry_run default contradicts docstring, sync submit blocks async event loop.

**Why this matters**: This is the external attack surface. Input validation gaps, auth bypass, parameter injection, and response shape inconsistencies all live here. Run 57 (SIEGE-DAG) found 5 bugs in this layer — there are likely more.

**Recommended split**: D (Security vs Functionality)
- Alpha (Security): Input validation, auth gate coverage, parameter injection, RBAC readiness, error information leakage
- Beta (Functionality): Status correctly reports DAG state, catalog resolves xarray URLs, resubmit handles edge cases, response shapes are consistent

| File | Lines | Role |
|------|-------|------|
| `triggers/dag/dag_bp.py` | 823 | DAG diagnostic/admin endpoints (runs, tasks, submit, test) |
| `triggers/platform/submit.py` | 545 | Platform submission (B2B contract, PlatformRequest validation) |
| `triggers/platform/resubmit.py` | 476 | Re-submission with release reuse |
| `triggers/platform/platform_bp.py` | 944 | Platform route registration + middleware |
| `triggers/trigger_platform_status.py` | 1,706 | Status aggregation (DAG + Epoch 4 dual-path) |
| `triggers/trigger_platform_catalog.py` | 540 | Catalog queries (xarray URLs, render configs) |
| `services/platform_job_submit.py` | 337 | Submit orchestration logic |
| `services/platform_catalog_service.py` | 1,055 | Catalog service layer |

**Constitutional focus**: P1 (explicit failure — no silent 200 on bad input), P10 (explicit data contracts — response shapes), S1.1 (zero-tolerance), S5.1 (platform boundary — triggers don't import core logic directly)

**Key questions for review**:
1. Does `submit.py` validate all PlatformRequest fields before forwarding to DAG?
2. Does `trigger_platform_status.py` handle the DAG/Epoch 4 dual-path without leaking internal state?
3. Does `resubmit.py` correctly reuse releases without creating orphaned artifacts?
4. Are `dag_bp.py` admin endpoints appropriately gated? (Currently: no auth — acceptable for dev, not for production)
5. Does `platform_catalog_service.py` correctly resolve xarray URLs for zarr assets?

**SIEGE-DAG findings in this layer** (already fixed, verify regression):
- F-1: Status services null for DAG runs (release not resolved from workflow_runs)
- FK-1: asset_releases.job_id FK violation on DAG submissions
- F-3: Catalog xarray_urls empty for zarr

---

### T8: Approval & Unpublish Lifecycle — REVIEWED (Run 61)

**What this is**: Constitution P5 (paired lifecycles) — every publish must have an unpublish. Approval gates, state transitions, artifact cleanup. This is where data integrity lives.

**Prior coverage**: Run 61 (28 MAR 2026, Split A, 26 findings, 17 fixes applied on `fix/compete-t7-t8-findings` branch). 1 CRITICAL (dry_run default), 13 HIGH. Key: orphaned app rows, zarr fails-open, unpublish DAG routing added, collection data-type detection, double revocation guard.

**Recommended split**: A (Design vs Runtime)
- Alpha (Design): Is every publish path paired with an unpublish? Are approval states complete? Can orphaned artifacts occur? Does the gate→approve→materialize sequence have gaps?
- Beta (Runtime): Concurrent approve + unpublish race conditions, partial unpublish failure, STAC consistency after delete, approval state machine edge cases

| File | Lines | Role |
|------|-------|------|
| `triggers/trigger_approvals.py` | 1,316 | Approval state machine (approve, reject, revoke) |
| `triggers/assets/asset_approvals_bp.py` | 775 | Approval HTTP endpoints |
| `triggers/platform/unpublish.py` | 1,276 | Unpublish endpoint + routing (DAG + Epoch 4) |
| `services/unpublish_handlers.py` | 1,366 | Raster/vector/zarr unpublish logic |
| `workflows/unpublish_raster.yaml` | 45 | Raster unpublish (fan-out COG deletion + STAC) |
| `workflows/unpublish_vector.yaml` | 40 | Vector unpublish (PostGIS drop + metadata + STAC) |
| `workflows/unpublish_zarr.yaml` | 42 | Zarr unpublish flow |

**Constitutional focus**: P5 (paired lifecycles — **primary**), P1 (explicit failure on partial unpublish), P11 (traceable state changes — audit trail), S3.1 (exception hierarchy)

**Key questions for review**:
1. Does every publish workflow (`process_raster`, `vector_docker_etl`, `ingest_zarr`) have a corresponding unpublish workflow?
2. Can an asset be approved while an unpublish is in flight? (Race condition)
3. What happens if unpublish fails halfway — are we left with orphaned STAC items? Orphaned blobs? Orphaned PostGIS tables?
4. Does the approval gate in DAG workflows correctly suspend and resume?
5. Is the audit trail complete — can we trace approve→unpublish for any asset?

**Design decision to verify**: AR-DAG-15 (TiPG two-phase discovery) — browsable pre-approval, searchable post-approval. Is this correctly implemented in `vector_docker_etl.yaml` v3?

---

### T9: Workflow YAML Definitions (REFLEXION)

**What this is**: Cross-cutting validation of all 12 workflow YAML files as a coherent set. Not a COMPETE review — uses REFLEXION (kludge hardener) to catch structural issues.

**Prior coverage**: Run 55 reviewed YAML + loader together (26 MAR, 18 findings). But focused on loader validation, not inter-workflow consistency.

**Why REFLEXION**: R agent reverse-engineers what each YAML does with zero context (no docs, no handler code). The gap between what R thinks it does and what it actually does is the signal. F agent fault-finds (missing receives, unreachable nodes, param mismatches). P agent patches. J agent judges.

| File | Lines | Role |
|------|-------|------|
| `workflows/hello_world.yaml` | 20 | Foundation test (2 nodes) |
| `workflows/echo_test.yaml` | 28 | Conditional skip test (when-clause) |
| `workflows/test_fan_out.yaml` | 29 | Fan-out/fan-in test (3 nodes) |
| `workflows/acled_sync.yaml` | 32 | API-driven scheduled workflow (3 nodes) |
| `workflows/unpublish_vector.yaml` | 40 | Vector unpublish (3 nodes, linear) |
| `workflows/unpublish_zarr.yaml` | 42 | Zarr unpublish flow |
| `workflows/unpublish_raster.yaml` | 45 | Raster unpublish (4 nodes, fan-out COG deletion) |
| `workflows/netcdf_to_zarr.yaml` | 70 | NC→Zarr conversion |
| `workflows/process_raster_single_cog.yaml` | 80 | Single COG processing (orphan — not routed) |
| `workflows/vector_docker_etl.yaml` | 92 | v3: Two-phase TiPG + approval gate (8 nodes) |
| `workflows/ingest_zarr.yaml` | 108 | NC/Zarr conditional routing + pyramid (9 nodes) |
| `workflows/process_raster.yaml` | 174 | Full raster: conditional + fan-out + fan-in + STAC (12 nodes) |

**REFLEXION focus areas**:
1. **Param coverage**: Does every handler's expected params appear in the node's `params` + `receives`?
2. **Receives resolution**: Does every `receives` dotted path point to an actual predecessor output key?
3. **Paired lifecycles**: Does every publish workflow have a `reversed_by` pointing to an unpublish workflow?
4. **Reachability**: Are there unreachable nodes? Dead branches?
5. **Fan-out/fan-in pairing**: Does every `fan_out` have a corresponding `fan_in`?
6. **Optional dep consistency**: Is `?` suffix used correctly on optional dependencies?
7. **Gate placement**: Is the approval gate correctly positioned (after persist, before STAC materialization)?

---

### T10: Infrastructure & Diagnostics — T10c COVERED (Run 67), T10a/b/d NOT STARTED

**What this is**: Everything that answers "is this environment healthy and correctly configured?" — health probes, health check plugins, preflight validation, Docker subsystem health, database admin/diagnostics, startup validation, config validation, observability pipelines, and external service monitoring. This is the system's self-awareness layer.

**Prior coverage**: None. These files have never been COMPETE-reviewed. The preflight system was built 29 MAR 2026 and had one code-review pass (2 criticals found and fixed) but no adversarial COMPETE pipeline.

**Why this matters**: This code runs in every deployment, on every health check poll, on every startup. Bugs here cause false-healthy reports (silent failures), false-unhealthy alerts (operator fatigue), information leakage (internal config exposed), or startup crashes that mask the real problem. In QA/production, operators trust these endpoints — if they lie, everything downstream is wrong.

**Total scope**: ~17,200 lines across 43 files. **Must be split** into sub-targets — too large for a single COMPETE run.

---

#### T10a: Preflight + Health Check Framework (~5,500 lines, 16 files)

**What this covers**: The complete HTTP-facing validation layer — preflight write-path tests, health check plugin architecture, readiness/liveness probes, system health cross-app view.

**Recommended split**: D (Security vs Functionality)
- Alpha (Security): Do health/preflight endpoints leak internal config, connection strings, account names, schema details? Are canary writes safe (cleanup guaranteed)? Is error text sanitized? Can an attacker use /health or /preflight to fingerprint the environment?
- Beta (Functionality): Does each check actually test what it claims? Are mode filters correct? Does schema derivation stay in sync with Pydantic models? Are remediation texts actionable and accurate?

| File | Lines | Role |
|------|-------|------|
| `triggers/preflight.py` | 135 | Preflight endpoint + `_run_preflight()` orchestrator |
| `triggers/preflight_checks/__init__.py` | 56 | Preflight check registry, mode-aware filtering |
| `triggers/preflight_checks/base.py` | 88 | PreflightCheck ABC, PreflightResult, Remediation dataclasses |
| `triggers/preflight_checks/database.py` | 523 | DB canary write, schema completeness (Pydantic-derived), extensions, pgSTAC roles |
| `triggers/preflight_checks/storage.py` | 260 | Blob CRUD canary (silver write+delete, bronze read), storage OAuth token |
| `triggers/preflight_checks/runtime.py` | 274 | Handler imports, GDAL version, ETL mount write test |
| `triggers/preflight_checks/dag.py` | 241 | Orchestrator lease, workflow registry + handler coverage, DAG tables |
| `triggers/preflight_checks/environment.py` | 61 | Env var validation (wraps config.env_validation) |
| `triggers/probes.py` | 760 | GET /livez, /readyz, /health, /diagnostics, /auth/status, /metrics |
| `triggers/health.py` | 535 | Health check orchestrator — 20+ plugin coordination with priority ordering |
| `triggers/health_checks/__init__.py` | 111 | Health check plugin registry and discovery |
| `triggers/health_checks/base.py` | 193 | HealthCheckPlugin ABC |
| `triggers/health_checks/application.py` | 287 | App mode, endpoint registration, job registry checks |
| `triggers/health_checks/startup.py` | 446 | Deployment config, startup validation, imports, runtime |
| `triggers/health_checks/observability.py` | 169 | Metrics and App Insights integration checks |
| `triggers/system_health.py` | 455 | Cross-app infrastructure view (/api/system-health) |

**Constitutional focus**: P1 (explicit failure — no false-healthy), S1.2 (SQL composition in canary writes), S3.1 (exception hierarchy — don't crash the health check), S4 (import layering — diagnostic code shouldn't import business logic)

**Key questions for review**:
1. Does the preflight schema derivation (`_derive_expected_tables`) actually match `generate_composed_statements()`? Can they drift?
2. Are canary write patterns truly idempotent? What if cleanup fails — is there canary data left behind?
3. Do health check plugins catch their own exceptions, or can one crashed plugin take down the entire /health endpoint?
4. Does `_run_preflight()` leak sensitive info in error messages (connection strings, account keys, internal paths)?
5. Is the mode filtering in `PreflightCheck.is_required()` correct for all 4 modes × 2 docker_worker_enabled states?

---

#### T10b: Docker Health + Startup Validation (~4,300 lines, 13 files)

**What this covers**: The Docker container's self-diagnosis (subsystem health architecture) and the startup validation pipeline that runs before any traffic is accepted.

**Recommended split**: A (Design vs Runtime)
- Alpha (Design): Is the subsystem architecture complete? Are all failure modes covered? Can startup validation complete with missing dependencies (graceful degradation vs hard fail)?
- Beta (Runtime): Race conditions in startup (validation vs first request), health status transitions (healthy→degraded→unhealthy), token refresh timing, connection pool initialization order

| File | Lines | Role |
|------|-------|------|
| `docker_health/__init__.py` | 126 | Subsystem registry, get_all_subsystems(), HealthAggregator export |
| `docker_health/base.py` | 149 | Subsystem ABC, health response structure |
| `docker_health/shared.py` | 441 | Database, storage, Service Bus, queue worker common checks |
| `docker_health/runtime.py` | 275 | Hardware, GDAL, imports, ETL mount, deployment config |
| `docker_health/classic_worker.py` | 235 | Queue worker lifecycle, auth tokens, job processing health |
| `docker_health/dag_brain.py` | 419 | DAG scheduler, primary loop, janitor lifecycle monitoring |
| `docker_health/aggregator.py` | 328 | Combine subsystem health into single response with component details |
| `startup/__init__.py` | 58 | Startup module exports |
| `startup/orchestrator.py` | 240 | Phase-ordered validation (env → imports → DNS → queues → auth) |
| `startup/state.py` | 360 | STARTUP_STATE singleton — persistent validation results |
| `startup/import_validator.py` | 147 | Critical module import testing at startup |
| `startup/service_bus_validator.py` | 333 | Service Bus DNS + queue existence validation |
| `config/env_validation.py` | 788 | 50+ env var regex rules, validate_environment() |

**Constitutional focus**: P1 (startup must fail loudly on missing requirements), P8 (database is coordination — health must verify DB before claiming ready), S3.1 (exception handling — startup errors must be surfaced, not swallowed)

**Key questions for review**:
1. Can /readyz return 200 before startup validation completes? (Race condition)
2. Does the HealthAggregator correctly promote status (healthy→degraded→unhealthy)? Can one subsystem mask another?
3. Does STARTUP_STATE survive module reimport? (Azure Functions cold start can reimport)
4. Does env_validation regex match the actual Azure resource naming rules? (False negatives = missed bad config)
5. Service Bus validator — is it still needed given Service Bus is being retired?

---

#### T10c: Database Admin & Diagnostics (~4,600 lines, 4 files)

**What this covers**: Admin endpoints for database health monitoring, schema management (rebuild/ensure), performance diagnostics, and external database connectivity.

**Recommended split**: C (Data vs Control)
- Alpha (Data): SQL correctness — are all queries parameterized (S1.2)? Are diagnostic queries safe (no writes on read endpoints)? Are schema rebuild steps atomic?
- Beta (Control): Error handling — what happens when rebuild fails halfway? Do diagnostic queries timeout? Can admin endpoints cause lock contention on production tables?

| File | Lines | Role |
|------|-------|------|
| `triggers/admin/db_health.py` | 621 | GET /api/dbadmin/health — connection pool, table sizes, long queries, cache ratios |
| `triggers/admin/db_maintenance.py` | 2,072 | POST /api/dbadmin/maintenance — ensure/rebuild/cleanup actions |
| `triggers/admin/db_diagnostics.py` | 1,640 | GET /api/dbadmin/diagnostics — schema analysis, data profiling, performance metrics |
| `triggers/admin/admin_external_db.py` | 294 | External database connectivity validation |

**Constitutional focus**: S1.2 (SQL composition — **critical** in admin code that generates DDL), P1 (rebuild must fail explicitly on partial completion), P8 (database operations must be atomic where possible)

**Key questions for review**:
1. Does `db_maintenance.py` rebuild use transactions correctly? What happens if step 3 of 7 fails — is schema left in broken state?
2. Are ALL SQL queries in diagnostics using `psycopg.sql` composition? (2,072 + 1,640 = 3,712 lines of admin code — high risk for f-string SQL)
3. Do diagnostic queries use statement_timeout to prevent runaway queries?
4. Can admin endpoints be called concurrently? (Two simultaneous rebuilds = corruption)
5. Does admin_external_db expose connection details in error responses?

---

#### T10d: Observability & External Services (~2,800 lines, 7 files)

**What this covers**: Application Insights export, metrics pipeline, service latency tracking, geo schema validation, external service health monitoring.

**Recommended split**: B (Internal vs External)
- Alpha (Internal): Metrics accuracy — does the pipeline measure what it claims? Are timestamps correct? Can metrics writes fail silently?
- Beta (External): App Insights query safety (injection?), external service health timeouts, geo schema validator SQL correctness

| File | Lines | Role |
|------|-------|------|
| `infrastructure/appinsights_exporter.py` | 473 | App Insights REST API query + blob export |
| `infrastructure/metrics_repository.py` | 402 | Pipeline metrics storage in PostgreSQL |
| `infrastructure/service_latency.py` | 451 | Service latency tracking and monitoring |
| `core/diagnostics/__init__.py` | 30 | Diagnostics module init |
| `core/diagnostics/geo_schema_validator.py` | 605 | PostGIS table integrity (geometry type, SRID, spatial index) |
| `services/external_service_health.py` | 531 | External microservice availability monitoring |
| `triggers/admin/admin_system.py` | 124 | System-wide admin status summary |

**Constitutional focus**: S1.2 (SQL in metrics/diagnostics), P1 (latency tracking must not mask failures), S4 (import layering — infrastructure shouldn't import services)

**Key questions for review**:
1. Does appinsights_exporter sanitize query parameters? (KQL injection risk)
2. Does metrics_repository handle connection failures gracefully? (Metrics should never block the pipeline)
3. Does geo_schema_validator use `psycopg.sql` for all PostGIS queries?
4. Does service_latency tracking add measurable overhead to request paths?
5. Are external service health checks using timeouts? (Hung external service → hung health check)

---

#### T10 Execution Order

```
T10c DONE   — Database Admin .............. Run 67 (29 MAR), 22 findings, 18 fixed ✓
T10a next   — Preflight + Health Framework (newest code, highest risk, never reviewed)
T10b third  — Docker Health + Startup (operational risk, race conditions)
T10d fourth — Observability (lowest risk, supporting infrastructure)
```

**Estimated effort per sub-target** (based on historical ~4 findings/1,000 lines):
| Sub-target | Lines | Est. Findings | Est. Tokens | Model |
|------------|-------|---------------|-------------|-------|
| T10a | ~5,500 | ~22 | ~400K | Opus |
| T10b | ~4,300 | ~17 | ~350K | Opus |
| T10c | ~4,600 | ~18 | ~350K | Opus |
| T10d | ~2,800 | ~11 | ~250K | Opus |

---

## Prior Run Cross-Reference

Which runs have already reviewed which files. Use this to identify gaps and avoid duplicate work.

| File | Reviewed In | Last Review | Notes |
|------|-------------|-------------|-------|
| `core/dag_transition_engine.py` | 47, 53, 54 | 26 MAR | Clean — 0 CRIT remaining |
| `core/dag_orchestrator.py` | 47, 53, 54 | 26 MAR | Advisory lock regression (H1) accepted |
| `core/dag_fan_engine.py` | 47, 53, 54 | 26 MAR | Type guards added (H3 fix) |
| `core/dag_graph_utils.py` | 47, 53, 54 | 26 MAR | SKIPPED terminal handling fixed (C2) |
| `core/orchestration_manager.py` | 54 | 26 MAR | Clean |
| `core/state_manager.py` | 47, 53 | 24 MAR | Thread-safe under GIL |
| `core/dag_initializer.py` | 46, 55 | 26 MAR | Canonical JSON serializer fixed |
| `core/param_resolver.py` | 46, 55 | 26 MAR | Pure function, well-tested |
| `core/workflow_loader.py` | 46, 55 | 26 MAR | 9-validation pipeline |
| `core/workflow_registry.py` | 46, 55 | 26 MAR | Clean |
| `core/dag_janitor.py` | 53, 54 | 26 MAR | Heartbeat reclaim, mount sweep |
| `core/dag_scheduler.py` | 57 | 26 MAR | `list_all()` → `list_workflows()` fixed |
| `infrastructure/workflow_run_repository.py` | 46, 47, 53, 54 | 26 MAR | Duplicate aggregate method (M2) |
| `infrastructure/lease_repository.py` | 53 | 24 MAR | Clean |
| `core/schema/orchestration.py` | 46 | 16 MAR | Needs re-review if DDL changed |
| `core/schema/workflow.py` | 55 | 26 MAR | Clean |
| `services/raster/*` | 50, 51, 55 | 26 MAR | Single + tiled paths covered |
| `services/vector/handler_load_source.py` | 48, 49 | 20 MAR | Clean |
| `services/vector/handler_validate_and_clean.py` | 48, 49 | 20 MAR | SQL regex false positive fixed |
| `services/vector/handler_create_and_load_tables.py` | 48, 49 | 20 MAR | Clean |
| `services/vector/handler_create_split_views.py` | — | **NEVER** | ⚠️ |
| `services/vector/handler_refresh_tipg.py` | — | **NEVER** | ⚠️ New TiPG two-phase |
| `services/vector/handler_register_catalog.py` | — | **NEVER** | ⚠️ |
| `services/vector/handler_finalize.py` | — | **NEVER** | ⚠️ |
| `services/vector/postgis_handler.py` | 48 (DECOMPOSE) | 19 MAR | Context only, not COMPETE |
| `services/vector/view_splitter.py` | — | **NEVER** | ⚠️ |
| `services/vector/converters.py` | — | **NEVER** | ⚠️ |
| `services/vector/column_sanitizer.py` | — | **NEVER** | ⚠️ |
| `services/zarr/*` | 52 | 23 MAR | Zarr handlers + STAC producers |
| `services/stac/*` | 52, 56 | 26 MAR | Consolidated builders reviewed |
| `services/stac_materialization.py` | 56 | 26 MAR | xarray signature fix (CRIT) |
| `triggers/dag/dag_bp.py` | 57, 58 | 28 MAR | Run 58: unauthenticated endpoints accepted (APP_MODE gated) |
| `triggers/platform/submit.py` | 58 | 28 MAR | Run 58: orphan risk, clearance dead code, STAC preflight |
| `triggers/platform/resubmit.py` | 58 | 28 MAR | Run 58: exception leakage |
| `triggers/platform/unpublish.py` | 58, 61 | 28 MAR | Run 61: dry_run CRIT fixed, DAG routing added, collection post-revoke, fails-closed |
| `triggers/platform/platform_bp.py` | 58 | 28 MAR | Run 58: _finalize_response fixed, error sanitization |
| `triggers/trigger_platform_status.py` | 58 | 28 MAR | Run 58: f-string SQL CRIT fixed, params validated |
| `triggers/trigger_platform_catalog.py` | 58 | 28 MAR | Run 58: error leakage |
| `triggers/trigger_approvals.py` | 61 | 28 MAR | Run 61: state machine sound, reject lacks audit snapshot (accepted) |
| `triggers/assets/asset_approvals_bp.py` | 61 | 28 MAR | Run 61: overlapping endpoints with divergent validation (accepted) |
| `services/unpublish_handlers.py` | 61 | 28 MAR | Run 61: 10 fixes — orphans, raw SQL, zarr fail-open, repo methods |
| `services/asset_approval_service.py` | 61 | 28 MAR | Run 61: state machine well-designed, rollback correct |
| `workflows/*.yaml` | 55 | 26 MAR | Reviewed with loader |

**All T7+T8 ⚠️ gaps resolved.** T5 vector handler gaps resolved (Run 65). **Remaining: T10 — 43 infrastructure/diagnostic files never COMPETE-reviewed.**

**T10 files (all ⚠️ NEVER REVIEWED):**

| File | Category | Lines | Notes |
|------|----------|-------|-------|
| `triggers/preflight.py` | T10a | 135 | New 29 MAR — code-reviewed, not COMPETE |
| `triggers/preflight_checks/*.py` | T10a | ~1,503 | New 29 MAR — code-reviewed, not COMPETE |
| `triggers/probes.py` | T10a | 760 | Core probes, never adversarially reviewed |
| `triggers/health.py` | T10a | 535 | Health orchestrator |
| `triggers/health_checks/*.py` | T10a | ~2,111 | 7 health plugins |
| `triggers/system_health.py` | T10a | 455 | Cross-app infra view |
| `docker_health/*.py` | T10b | ~1,973 | 7 subsystem modules |
| `startup/*.py` | T10b | ~1,138 | 5 startup validation modules |
| `config/env_validation.py` | T10b | 788 | 50+ env var regex rules |
| `triggers/admin/db_health.py` | T10c | 621 | DB performance metrics |
| `triggers/admin/db_maintenance.py` | T10c | 2,072 | Schema rebuild/ensure — **highest SQL risk** |
| `triggers/admin/db_diagnostics.py` | T10c | 1,640 | DB profiling queries |
| `triggers/admin/admin_external_db.py` | T10c | 294 | External DB connectivity |
| `infrastructure/appinsights_exporter.py` | T10d | 473 | App Insights REST + export |
| `infrastructure/metrics_repository.py` | T10d | 402 | Pipeline metrics |
| `infrastructure/service_latency.py` | T10d | 451 | Latency tracking |
| `core/diagnostics/geo_schema_validator.py` | T10d | 605 | PostGIS integrity |
| `services/external_service_health.py` | T10d | 531 | External service monitoring |
| `triggers/admin/admin_system.py` | T10d | 124 | System admin summary |

---

## Estimated Effort

Based on historical token usage across 57 runs:

| Target | Est. Tokens | Est. Duration | Model |
|--------|-------------|---------------|-------|
| T7 | ~350K | 15-20 min | Opus (all agents) |
| T8 | ~300K | 12-18 min | Opus (all agents) |
| T5 | ~400K | 18-25 min | Opus (all agents) |
| T9 | ~200K | 10-15 min | Opus (REFLEXION) |
| T10a | ~400K | 18-25 min | Opus (preflight + health framework) |
| T10b | ~350K | 15-20 min | Opus (docker health + startup) |
| T10c | ~350K | 15-20 min | Opus (DB admin — high SQL risk) |
| T10d | ~250K | 12-15 min | Opus (observability) |
| T1-T4, T6 | ~300K each | 12-18 min each | Opus (re-review only) |

**Historical density**: ~4 findings per 1,000 lines (from Runs 46-57 average).
**Expected new findings**: T7 (~25), T8 (~19), T5 (~26), T9 (~3).

---

## Notes for Executing Agents

1. **Always read the Constitution** (`docs/agent_review/CONSTITUTION.md`) before starting a run. Every finding should reference a constitutional principle or implementation standard.

2. **Read the COMPETE_AGENT.md template** (`docs/agent_review/agents/COMPETE_AGENT.md`) for the full pipeline flow: Omega → Alpha + Beta (parallel) → Gamma → Delta.

3. **Omega chooses the split.** The recommended split in each target section is guidance, not mandate. If the code suggests a different split would produce more friction, use that instead. Document why.

4. **Log every run** in `AGENT_RUNS.md` with the standard format (see existing runs for template).

5. **Update this file** after each run — change the status, add run number, and record findings count.

6. **Apply fixes immediately** where possible. Log accepted risks with rationale.

7. **Cross-reference accepted risks** from prior runs (listed in each target section). Don't re-report known accepted risks unless the rationale has changed.
