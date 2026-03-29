# Agent Pipeline Run Log

All pipeline executions in chronological order.

**Runs 1-43 (v0.9.x era)**: Condensed to `agent_docs/RUNS_HISTORY_v09.md`. Full detail docs archived to `docs/archive/agent_review/`.

**Active runs (v0.10.x)**: Below.

---

## Run 44: DB-Polling Task Dispatch (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 15 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DB-polling task dispatch subsystem — SKIP LOCKED migration from Service Bus |
| **Version** | v0.10.3.0 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 9 |
| **Findings** | 18 total: 3 CRITICAL, 4 HIGH, 6 MEDIUM, 5 LOW |
| **Fixes Applied** | 11 (all CRITICAL + HIGH + 4 MEDIUM) |
| **Accepted Risks** | 2 resolved (janitor implemented in `dag_janitor.py`, double PROCESSING write moot — SB deprecated). 1 still open: health check auth — diagnostics exception (by design for K8s probes) |
| **Verdict** | Sound architecture, critical shutdown/retry bugs fixed, deployable |

**Scope Split C — Alpha (Data Integrity) / Beta (Control Flow)**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | Data validation, enum alignment, schema evolution, datetime consistency | enums.py, task.py, transitions.py, queue.py, sql_generator.py, jobs_tasks.py |
| Beta | SKIP LOCKED atomicity, graceful shutdown, retry path, race conditions | jobs_tasks.py, machine.py, docker_service.py, transitions.py |
| Gamma | Blind spots: health check auth, status API gaps, index coverage | shared.py, defaults.py, sql_generator.py, get_job_status.py |

**Top Fixes**:

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | Connection pool destroyed while task in-flight (SIGTERM) | CRITICAL | `finalize_shutdown()` after thread join |
| 2 | `check_job_completion` ignores SKIPPED/CANCELLED | HIGH | `terminal_tasks` count |
| 3 | Non-atomic retry (two writes, conflicting backoff) | CRITICAL | Single atomic SQL function |
| 4 | PENDING_RETRY→PROCESSING bypass | CRITICAL | Transition table updated |
| 5 | `fail_tasks_for_job` overwrites settled states | HIGH | Excluded skipped/cancelled |

---

## Run 45: DB-Polling Regression (SIEGE)

| Field | Value |
|-------|-------|
| **Date** | 15 MAR 2026 |
| **Pipeline** | SIEGE (Sequential Smoke Test) |
| **Scope** | Post-deployment regression — DB-polling migration validation |
| **Version** | v0.10.3.0 |
| **Profile** | Quick |
| **Pass Rate** | **18/18 (100%)** |
| **Duration** | 1m 52s |
| **Findings** | 1 LOW (dbadmin task_counts missing 3 new statuses) |
| **Verdict** | Zero regressions. DB-polling fully functional. |

**Sequences**:

| Seq | Name | Verdict | Notes |
|-----|------|---------|-------|
| S0 | Endpoint Probes (7) | PASS | All healthy |
| S1 | Raster Lifecycle | PASS | Submit → complete → approve → catalog → TiTiler |
| S2 | Vector Lifecycle | PASS | Submit → complete → approve → catalog → OGC Features |
| S3 | Status API Validation | PASS | All 8 TaskStatus values in responses |
| S4 | Negative Tests | PASS | Ghost file → 400, fake release → 404 |

**Finding**:

| ID | Severity | Description |
|----|----------|-------------|
| SG18-F1 | LOW | `dbadmin/jobs` task_counts missing `pending_retry`, `skipped`, `cancelled` — only 4 of 8 statuses |

---

## Recurring Review Patterns

Two subsystems are designated for **regular re-review** using the COMPETE pipeline with full constitution enforcement. These are the highest-churn, highest-risk areas of the codebase — each has been the source of multiple SIEGE/TOURNAMENT findings across runs.

### Pattern A: Approval Workflow Review

**Original**: Run 4 (27 FEB 2026) — pre-constitution, 21 findings, 5 fixes
**Why recurring**: The approval lifecycle is the most-patched subsystem. Runs 4, 5, 6, 12, 14, 16, 25, 26, 27 all found or fixed approval-related issues. Every fix is a potential constitution violation introduction point.

**Scope** (7 files, ~7,000 lines):
- `triggers/trigger_approvals.py` — approve/reject/revoke endpoints
- `services/asset_approval_service.py` — approval business logic
- `infrastructure/release_repository.py` — release persistence + atomic state transitions
- `core/models/asset.py` — AssetRelease model + state machine
- `core/models/platform.py` — PlatformRequest validation
- `services/stac_materialization.py` — STAC writes at approval time
- `infrastructure/pgstac_repository.py` — pgSTAC operations

**Constitution focus**: Sections 1 (zero-tolerance), 2 (config access), 3 (error handling), 5 (platform boundaries), 6 (database patterns)

**Recommended split**: B (Internal vs External) — Internal logic/invariants vs boundary contracts/error surfaces

**Cadence**: After every deployment that touches approval files, or monthly.

### Pattern B: CoreMachine Orchestration Review

**Original**: Run 1 (26 FEB 2026) — pre-constitution, 18 findings, 5 fixes
**Why recurring**: CoreMachine is the heart of all job processing. The zero-task stage guard (added post-Run 9) and various error handling changes make this a constitution compliance hotspot. Exception swallowing patterns (accepted risk BLIND-2) should be re-evaluated against Section 3.3.

**Scope** (8 files, ~5,600 lines):
- `core/machine.py` — orchestration engine
- `core/state_manager.py` — job/task state persistence
- `core/logic/transitions.py` — state machine rules
- `jobs/base.py` — abstract job interface
- `jobs/mixins.py` — JobBaseMixin (77% boilerplate reduction)
- `services/__init__.py` — handler registry
- `triggers/service_bus/task_handler.py` — task message processing
- `triggers/service_bus/job_handler.py` — job message processing

**Constitution focus**: Sections 1 (zero-tolerance, especially 1.3 ContractViolationError, 1.4 repository pattern), 3 (error handling categories), 4 (import hierarchy), 9 (job/task patterns)

**Recommended split**: A (Design vs Runtime) — Architecture/contracts vs correctness/reliability

**Cadence**: After major CoreMachine changes, or bi-monthly.

---

## Run 46: DAG Data Layer D.1-D.4 (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 16 MAR 2026 |
| **Pipeline** | COMPETE |
| **Scope** | DAG workflow definition, models, loader/registry, initializer, parameter resolver |
| **Files** | 12 |
| **Scope Split** | C (Data vs Control Flow) |
| **Findings** | 19 total (Alpha: 9, Beta: 6+3 risks+4 edge cases, Gamma: 5 blind spots) |
| **Gamma Corrections** | Alpha-MEDIUM-2 = FALSE POSITIVE, Alpha-LOW-1 = INVALID |
| **Constitution Violations** | 2 (Section 3.1: exception hierarchy, Section 1.1: silent skip) |
| **Fixes Applied** | 5/5 — all applied during v0.10.5.x development (verified 23 MAR 2026) |
| **Output** | `agent_docs/compete_run46_dag_data_layer.md` |

**Top 5 Fixes**:

| # | Severity | Description | File |
|---|----------|-------------|------|
| 1 | HIGH | Replace `default=str` with explicit canonical serializer in `_generate_run_id` | `core/dag_initializer.py:44-56` | **FIXED** — `_canonical_json_default()` raises on unknown types |
| 2 | HIGH | Wire `WorkflowNotFoundError`/`WorkflowValidationError` into `BusinessLogicError` hierarchy | `core/workflow_registry.py:22`, `core/workflow_loader.py:27` | **FIXED** — both inherit via ResourceNotFoundError/ValidationError |
| 3 | MEDIUM | Raise `ContractViolationError` for unknown IDs in `_build_adjacency_from_tasks` | `core/dag_fan_engine.py:212-216` | **FIXED** — two explicit guards in `build_adjacency()` |
| 4 | MEDIUM | Add cross-field validation to `RetryPolicy` (initial_delay <= max_delay) | `core/models/workflow_definition.py:24-29` | **FIXED** — `@model_validator` enforces bounds |
| 5 | MEDIUM | Return fresh task state from `claim_ready_workflow_task` (stale timestamps) | `infrastructure/workflow_run_repository.py:891-892` | **FIXED** — returns WorkflowTask with RUNNING state |

**Accepted Risks (revised 23 MAR 2026)**: 3 of 6 remain open. RESOLVED: non-atomic param+promote (merged to `set_params_and_promote`), no RUNNING timeout (janitor 120s sweep), void fail_task (guarded by orchestrator flow). STILL OPEN: deterministic run_id resubmit (idempotent reject, no user notification), echo_test.yaml when-clause edge case, uuid4 fan-out children (non-deterministic by design).

---

## Run 47: DAG Control Layer D.5-D.6 (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 16 MAR 2026 |
| **Pipeline** | COMPETE |
| **Scope** | DAG graph utilities, transition engine, fan engine, orchestrator, repository, worker dual-poll |
| **Files** | 6 |
| **Scope Split** | A (Design vs Runtime) |
| **Findings** | 19 total (Alpha: 10, Beta: 8+3 risks+3 edge cases, Gamma: 6 blind spots) |
| **Gamma New Finds** | 2 CRITICAL (fan-out template race, TaskSummary handler field) |
| **Constitution Violations** | 2 (Section 1.1: silent skip in _build_adjacency, Section 4.1: core->infrastructure import) |
| **Fixes Applied** | 5/5 — all applied during v0.10.5.x development (verified 23 MAR 2026) |
| **Output** | `agent_docs/compete_run47_dag_control_layer.md` |

**Top 5 Fixes**:

| # | Severity | Description | File | Status |
|---|----------|-------------|------|--------|
| 1 | CRITICAL | Add `handler` field to TaskSummary + SELECT — `evaluate_conditionals` crashes with AttributeError | `core/dag_graph_utils.py:52-66`, `infrastructure/workflow_run_repository.py:246-271` | **FIXED** — handler field in TaskSummary + SELECT |
| 2 | CRITICAL | Exclude fan-out templates from worker claim — workers can claim templates before orchestrator expands, causing permanent DAG stall | `infrastructure/workflow_run_repository.py:855-862`, `core/dag_initializer.py:83` | **FIXED** — `__fan_out__`/`__conditional__`/`__fan_in__` sentinels excluded from claim SQL |
| 3 | HIGH | Fix `predecessor_outputs` dict collision — fan-out children share task_name, last child wins | `core/dag_orchestrator.py:369-376` | **FIXED** — filters out fan-out children with `fan_out_source is None` |
| 4 | MEDIUM | Add `_ensure_fresh_tokens()` to `_process_workflow_task` | `docker_service.py:581` | **FIXED** — called at start of `_process_workflow_task` |
| 5 | MEDIUM | Merge `set_task_parameters` + `promote_task` into single atomic UPDATE | `core/dag_transition_engine.py:387-394` | **FIXED** — `set_params_and_promote()` with CAS guard |

**Accepted Risks (revised 23 MAR 2026)**: 4 of 8 remain open. RESOLVED: _build_adjacency silent skip (raises ContractViolationError), no heartbeat (last_pulse + janitor), no retry mechanism (janitor exponential backoff), time.sleep (only in test handler). STILL OPEN: expand_fan_out no CAS (UniqueViolation fallback), aggregate_fan_in no CAS, stale snapshot (inherent to optimistic locking), per-call repo instantiation (connection pool pressure under load).

---

## Cumulative Token Usage

---

## Run 48: Vector Handler Decomposition (DECOMPOSE — First Production Run)

| Field | Value |
|-------|-------|
| **Date** | 19 MAR 2026 |
| **Pipeline** | DECOMPOSE (Faithful Monolith Extraction) — FIRST RUN |
| **Mode** | Guided (boundaries from V10_MIGRATION.md) |
| **Monolith** | `services/handler_vector_docker_complete.py` (1,448 lines) |
| **Target** | 3 handlers: `vector_load_source`, `vector_validate_and_clean`, `vector_create_and_load_tables` |
| **Version** | v0.10.4.1 |
| **Output** | 3 handler files (2,948 lines total) + build spec |
| **Total Tokens** | 567,878 |
| **Wall Clock** | ~25 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| R | Opus | 34,893 | 2m 39s | Reverse-engineered monolith blind (11 phases, 5 [BUG] tags) |
| X | Opus | 46,584 | 4m 01s | Designed 3 handlers from specs blind |
| D | Opus | 48,358 | 5m 47s | Diff audit: 8 matched, 20 orphaned, 9 new, 5 boundary mismatches |
| P | Opus | 53,177 | 4m 38s | Atomic purist design |
| F | Opus | 130,128 | 6m 01s | Fidelity defense + 3 R corrections (CRS, column mapping, NaT gap) |
| M | Opus | 82,893 | 9m 00s | Resolved 12 conflicts, escalated 3 |
| B1 | Sonnet | 42,316 | 1m 58s | Built vector_load_source |
| B2 | Sonnet | 56,255 | 3m 23s | Built vector_validate_and_clean |
| B3 | Sonnet | 73,274 | 4m 31s | Built vector_create_and_load_tables |

**Key Pipeline Wins**:
- F caught R's CRS error: monolith silently assigns 4326, not rejects. Would have been a regression.
- F found NaT conversion gap: `insert_chunk_idempotent` has no NaT guard. Defense-in-depth mandated.
- F clarified column mapping != sanitization: two distinct operations, both preserved.
- D found 20 orphaned behaviors: 7 assigned to existing handlers (4/5/6), 4 added to handler 3.

**GATE1 Decisions**: 20 orphans triaged. 3 CRITICAL assigned. 7 covered by existing handlers. 6 deferred to infrastructure. 3 intentionally removed. 1 dropped.

**GATE2 Decisions**: 3 escalations resolved. OGC styles → node 5. Feature count → node 5 (already handles). Validation events → skip (DAG task timestamps suffice).

**Calibration Data** (vs pipeline estimates):

| Agent | Estimated | Actual | Delta |
|-------|-----------|--------|-------|
| R | 80-120K | 35K | 71% under |
| X | 40-60K | 47K | On target |
| D | 60-100K | 48K | 35% under |
| P | 40-60K | 53K | On target |
| F | 50-80K | 130K | 63% over (reads monolith + 2 support files) |
| M | 80-120K | 83K | On target |
| B (each) | 30-50K | 42-73K | On target to 46% over |

**Scope guidance update**: F is the most expensive agent — reading monolith + support files drives token count. For future runs, F's estimate should be 100-150K for 1,500-line monoliths.

---

## Run 49: Vector Atomic Handlers Review (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 20 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | 3 DECOMPOSE-extracted vector handlers (handler_load_source, handler_validate_and_clean, handler_create_and_load_tables) |
| **Version** | v0.10.4.1 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 3 handler files + 2 support modules |
| **Findings** | 22 total: 0 CRITICAL, 3 HIGH, 12 MEDIUM, 7 LOW |
| **Fixes Applied** | 5 (Top 5 from Delta) |
| **Accepted Risks** | 3 resolved (NaT round-trip, mount cleanup via janitor Phase 3, datetime→TIMESTAMPTZ). 2 still open: multi-group partial failure, private API chaining |
| **Total Tokens** | 325,779 |
| **Wall Clock** | ~15 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| Alpha | Opus | 93,527 | 3m 23s | Data integrity review (2 HIGH, 4 MEDIUM, 1 LOW) |
| Beta | Opus | 93,148 | 4m 27s | Orchestration review (2 HIGH, 2 MEDIUM, 3 RISK, 4 EDGE) |
| Gamma | Opus | 81,953 | 4m 09s | Contradictions + 5 blind spots (SQL regex, mount cleanup, NaT→TEXT) |
| Delta | Opus | 57,151 | 2m 49s | Final report: Top 5 fixes, 5 accepted risks, 5 architecture wins |

**Top 5 Fixes Applied**:
1. Handler 2 outer try/except (contract violation)
2. `conn.rollback()` after cleanup failure (connection poisoning)
3. SQL injection regex false positive on hyphens
4. `chunk_size <= 0` validation
5. Antimeridian exception logging (silent swallows)

**DAG Infrastructure Bugs Found During Testing** (post-COMPETE, during deployment):
1. Root node parameters never resolved by initializer → fixed in `dag_initializer.py`
2. Docker worker missing `_run_id`/`_node_name` injection → fixed in `docker_service.py`
3. Hardcoded `/mnt/etl` instead of `config.docker.etl_mount_path` → fixed in handlers 1+2

**E2E Test Results** (via `POST /api/dag/test/node/{handler_name}`):

| Handler | Status | Result |
|---------|--------|--------|
| `vector_load_source` | COMPLETED | 483 rows from roads.geojson, GeoParquet on mount |
| `vector_validate_and_clean` | COMPLETED | 1 group (line), 483 rows, CRS=4326 |
| `vector_create_and_load_tables` | COMPLETED | `geo.test_roads_dag`, 483 rows, spatial index |

---

## Cumulative Statistics

---

## Run 50: Raster Handler Decomposition (DECOMPOSE — Run 2)

| Field | Value |
|-------|-------|
| **Date** | 21 MAR 2026 |
| **Pipeline** | DECOMPOSE (Faithful Monolith Extraction) — Run 2 |
| **Mode** | Guided (boundaries from V10_MIGRATION.md, single COG path only) |
| **Monolith** | `services/handler_process_raster_complete.py` (2,369 lines, single COG path) |
| **Target** | 5 handlers: download_source, validate, create_cog, upload_cog, persist_app_tables |
| **Version** | v0.10.5.0 |
| **Output** | 5 handler files (3,086 lines total) + build spec (957 lines) |
| **Total Tokens** | 672,869 |
| **Wall Clock** | ~28 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| R | Opus | 43,522 | 3m 26s | Reverse-engineered single COG path (8 phases, 7 anomalies) |
| X | Opus | 64,275 | 4m 53s | Designed 5 handlers from V10 spec |
| D | Opus | 46,991 | 5m 30s | Diff audit: 5 matched, 14 orphaned, 10 new, 4 boundary mismatches, 10 data flow gaps |
| P | Opus | 61,040 | 3m 29s | Atomic purist design |
| F | Opus | 102,531 | 5m 39s | Fidelity defense + 6 R corrections (render_config NOT dead write, column mapping, NaT gap, etc.) |
| M | Opus | 84,366 | 9m 47s | Resolved 9 conflicts, escalated 3 |
| B1 | Sonnet | 39,059 | 1m 42s | Built raster_download_source |
| B2 | Sonnet | 49,215 | 2m 27s | Built raster_validate |
| B3 | Sonnet | 75,912 | 3m 16s | Built raster_create_cog |
| B4 | Sonnet | 43,017 | 2m 18s | Built raster_upload_cog |
| B5 | Sonnet | 62,941 | 3m 04s | Built raster_persist_app_tables |

**Key Design Decision**: `raster_create_cog` extracts raster_bands/rescale_range/transform/resolution from the COG file directly (windowed reads), eliminating blob re-read in persist handler.

**GATE1**: 14 orphans triaged — 1 absorbed (ProvenanceProperties), 4 eliminated by DAG design, 9 deferred.
**GATE2**: 3 escalations resolved — skip_cleanup/skip_upload for raster_cog.py, output_blob_name required, tier suffix preserved.

---

## Run 51: Raster Atomic Handlers Review (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 21 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | 5 DECOMPOSE-extracted raster handlers |
| **Version** | v0.10.5.0 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 5 handler files + raster_cog.py (context) |
| **Findings** | 16 total: 1 CRITICAL, 4 HIGH, 6 MEDIUM, 5 LOW |
| **Fixes Applied** | 5 (Top 5 from Delta) |
| **Accepted Risks** | 5 resolved (file_checksum removed, rescale unified via `build_renders()`, degenerate guard added, node_name validated, basename prefixed with run_id[:8]). 1 still open: context param unused (future-proofing) |
| **Total Tokens** | 354,745 |
| **Wall Clock** | ~10 minutes |

**Token Usage by Agent**:

| Agent | Model | Tokens | Duration |
|-------|-------|--------|----------|
| Alpha | Opus | 111,252 | 2m 48s |
| Beta | Opus | 111,189 | 3m 39s |
| Gamma | Opus | 84,134 | 4m 00s |
| Delta | Opus | 48,170 | 2m 21s |

**Top 5 Fixes Applied**:
1. raster_cog.py: skip_cleanup + skip_upload params (CRITICAL — entire chain was non-functional)
2. handler_create_cog: output_blob_name + target_crs required params
3. handler_persist_app_tables: outer try/except for contract compliance
4. handler_create_cog: windowed block reads replace full-band ds.read() (OOM prevention)
5. handler_create_cog: bounds_4326 CRS guard via transform_bounds

---

## Run 52: Zarr + STAC Producer vs Consumer (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 23 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Zarr handlers + STAC composable handlers (producer vs consumer split) |
| **Version** | v0.10.5.7 |
| **Split** | Custom: Producers (metadata writers) vs Consumers (pgSTAC writers) |
| **Files** | 8 (zarr handlers, STAC handlers, repositories, BlobRepository) |
| **Findings** | 14 total: 2 CRITICAL, 4 HIGH, 4 MEDIUM, 4 LOW |
| **Total Tokens** | 190,680 |
| **Wall Clock** | ~5 minutes |
| **Report** | `agent_docs/compete_run52_zarr_stac_producers_consumers.md` |

**Token Usage**:

| Agent | Model | Tokens | Duration |
|-------|-------|--------|----------|
| Alpha (Producers) | Opus | 74,577 | 2m 02s |
| Beta (Consumers) | Opus | 67,869 | 2m 17s |
| Gamma+Delta (combined) | Opus | 48,234 | 2m 38s |

**Top 5 Fixes**:
1. NameError crash — `cog_metadata` undefined on zarr materialization path (CRITICAL)
2. SQL injection — f-string SQL in zarr_metadata_repository.upsert() (CRITICAL)
3. Silent exception swallowing — `except Exception: pass` in 4 locations (HIGH, systemic)
4. Global bbox fallback `[-180,-90,180,90]` masks missing spatial data (HIGH)
5. No STAC item contract validation before pgSTAC write (HIGH)

**Split effectiveness**: Producer vs Consumer split was highly productive. The contract boundary between metadata tables and pgSTAC was the primary friction point.

---

## Run 57: DAG API + Health Monitoring + Scheduler (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 26 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DAG API endpoints, health monitoring, scheduler, schedule repository, startup orchestrator |
| **Version** | v0.10.6.3 |
| **Split** | B (Internal vs External) |
| **Files** | 6 (dag_bp.py, dag_brain.py, shared.py, dag_scheduler.py, schedule_repository.py, orchestrator.py) |
| **Findings** | 17 total: 2 CRITICAL, 4 HIGH, 7 MEDIUM, 4 LOW |
| **Fixes Pending** | Top 5 recommended |
| **Report** | `agent_docs/compete_run57_dag_api_health.md` |

**Scope Split B -- Alpha (Internal Logic) / Beta (External Interfaces)**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | Scheduling logic, health check accuracy, startup sequence, state management | dag_scheduler.py, dag_brain.py, shared.py, schedule_repository.py, orchestrator.py |
| Beta | API contracts, input validation, response shapes, error surfaces, observability | dag_bp.py, dag_brain.py, shared.py, schedule_repository.py |
| Gamma | Blind spots: duplicate detection path, nonexistent method call, stale thread detection | dag_bp.py + schedule_repository.py seam, dag_scheduler.py error path |

**Top Fixes**:

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | `ScheduleRepository.create()` never returns `None` -- 409 duplicate detection is dead code, returns 500 instead | CRITICAL | Catch `UniqueViolation` specifically in repo, return `None` |
| 2 | `registry.list_all()` called in scheduler error path -- method does not exist (`list_workflows()` is correct) | CRITICAL | One-line fix: `list_all()` -> `list_workflows()` |
| 3 | 4 endpoints in dag_bp.py create raw DB connections bypassing repository pattern (Standard 1.4) | HIGH | Move queries to repository methods |
| 4 | `limit` query param not validated for non-numeric input -- returns 500 instead of 400 | HIGH | Add try/except around `int()` cast |
| 5 | Health check does not detect stuck primary loop thread (only checks `is_alive()`, no staleness) | HIGH | Add last_scan_at staleness check |

**Regression vs Run 50**: f-string SQL (Run 50 Fix 3) confirmed fixed -- now uses `sql.SQL()` composition. `get_workflow_registry` crash (Run 50 Fix 1) confirmed fixed -- now uses `WorkflowRegistry` with `.has()`. `get_active_run_count` join bug (Run 50 Fix 2) confirmed fixed -- now queries `workflow_runs.schedule_id` directly. Two new findings in this review (duplicate detection, `list_all`).

---

## Cumulative Statistics

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19, 28-30, 33, 39, 42, 44, 46, 47, 49, 51-55, 58 | ~5.1M+ |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944K |
| SIEGE | Runs 11, 13, 18, 20-23, 25-26, 34-35, 37-38, 40-41, 43, 45 | ~2.5M+ |
| SIEGE-DAG | Run 57 | ~50K |
| REFLEXION | Runs 14-17, 32 | ~975K |
| TOURNAMENT | Run 27 | ~278K |
| ADVOCATE | Runs 31, 36 | ~335K |
| DECOMPOSE | Runs 48, 50 | ~1.24M |
| **Total** | 58 runs | **~11.4M+** |

---

## Open Issues Summary (verified 23 MAR 2026)

### Pending Fixes: ALL RESOLVED

All 10 pending fixes from Runs 46 + 47 were applied during v0.10.5.x development:

| Run | Fix | Severity | Status |
|-----|-----|----------|--------|
| 46 | Canonical JSON serializer | HIGH | Fixed in `_canonical_json_default()` |
| 46 | Error class hierarchy | HIGH | Fixed — both inherit from BusinessLogicError |
| 46 | ContractViolationError for unknown IDs | MEDIUM | Fixed in `build_adjacency()` |
| 46 | RetryPolicy cross-field validation | MEDIUM | Fixed — `@model_validator` |
| 46 | Fresh task state from claim | MEDIUM | Fixed — returns WorkflowTask |
| 47 | TaskSummary handler field | CRITICAL | Fixed — handler in SELECT + TaskSummary |
| 47 | Exclude fan-out templates from claim | CRITICAL | Fixed — sentinel handler exclusion |
| 47 | predecessor_outputs collision | HIGH | Fixed — `fan_out_source is None` filter |
| 47 | `_ensure_fresh_tokens()` | MEDIUM | Fixed — called at start of workflow task processing |
| 47 | Atomic set_params_and_promote | MEDIUM | Fixed — single CAS-guarded UPDATE |

### Accepted Risks Still Open (11 of 30)

**Architectural / By Design (6)** — these are conscious trade-offs, not bugs:

| Run | Risk | Rationale |
|-----|------|-----------|
| 44 | Health check auth exception | K8s probes + monitoring need unauthenticated access |
| 46 | Deterministic run_id resubmit | Idempotent reject on PK collision; no user notification on duplicate |
| 46 | uuid4 fan-out children | Non-deterministic IDs required — deterministic would need canonical expansion order |
| 47 | Stale snapshot | Inherent to optimistic locking; pessimistic locking too expensive |
| 47 | Per-call repo instantiation | Avoids shared state; connection pool pressure acceptable at current scale |
| 51 | Context param unused | Future-proofing for worker-provided context injection |

**Deferred / Low Priority (5)** — real gaps, low blast radius:

| Run | Risk | Impact |
|-----|------|--------|
| 46 | echo_test.yaml when-clause edge case | Test workflow only, not production |
| 47 | expand_fan_out no CAS | Second concurrent expand gets UniqueViolation (non-fatal) |
| 47 | aggregate_fan_in no CAS | Concurrent aggregation could double-complete (unlikely, non-fatal) |
| 49 | Multi-group partial failure | Partial result returned without explicit failure status |
| 49 | Private API chaining | Tightly coupled handlers call internal methods |

**Technical Debt (0)** — all resolved 23 MAR 2026:

~~Mount cleanup deferred~~ → Janitor Phase 3 added to `dag_janitor.py` (30-day threshold, `JANITOR_MOUNT_MAX_AGE_DAYS` env override)
~~datetime→TEXT mapping~~ → `postgis_handler._get_postgres_type()` now returns `TIMESTAMP WITH TIME ZONE` (requires schema rebuild for existing tables)

### Accepted Risks Resolved Since Original Runs (19 of 30)

| Run | Risk | How Resolved |
|-----|------|-------------|
| 44 | No janitor | `dag_janitor.py` — background sweep with exponential backoff |
| 44 | Double PROCESSING write | Moot — Service Bus deprecated, DB-polling only |
| 46 | Non-atomic param+promote | Merged to `set_params_and_promote` with CAS |
| 46 | No RUNNING timeout | Janitor enforces 120s stale threshold |
| 46 | Void fail_task | Guarded by orchestrator flow; only called on RUNNING tasks |
| 47 | _build_adjacency silent skip | Raises `ContractViolationError` for unknown IDs |
| 47 | time.sleep not interruptible | Only used in test handler (`hello_world.py`) |
| 47 | No heartbeat | `last_pulse` field + janitor sweep |
| 47 | No retry mechanism | Janitor exponential backoff with max_retries |
| 49 | NaT round-trip | Fixed via `.astype(object)` before `to_parquet()` |
| 51 | file_checksum not computed | Removed — no consumer for SHA-256 |
| 51 | Rescale divergence | Unified via canonical `build_renders()` from `stac_renders.py` |
| 51 | Degenerate rescale | Guard for `[0.0, 0.0]` returns None |
| 51 | node_name inconsistency | Both `_run_id` + `_node_name` validated as required |
| 51 | Basename collision | `run_id[:8]` prefix on downloaded filenames |
| 52 | NameError on zarr path | `cog_metadata = None` before try block |
| 52 | SQL injection in zarr repo | Parameterized SQL with column whitelist |
| 49 | Mount cleanup deferred | Janitor Phase 3: `_sweep_mount_dirs()` removes dirs older than 30 days |
| 49 | datetime→TEXT mapping | `postgis_handler._get_postgres_type()` → `TIMESTAMP WITH TIME ZONE` |

---

## Run 53: DAG Brain Primary Loop + Orchestration (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 24 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DAG Brain primary loop (new), orchestrator dispatch engines, worker claim path, repository |
| **Version** | v0.10.5.8 |
| **Context** | Removed all per-submission orchestrator thread spawning. Built DAGBrainPrimaryLoop as single source of orchestration. Function App only writes to DB. |
| **Split** | 3-way: Primary Loop / Dispatch Engines / Worker+Repo |
| **Files** | 7 (docker_service.py, dag_orchestrator.py, dag_transition_engine.py, dag_fan_engine.py, dag_graph_utils.py, dag_janitor.py, workflow_run_repository.py) |
| **Findings** | 22 total: 3 CRITICAL, 5 HIGH, 6 MEDIUM, 3 LOW, 5 confirmed OK |
| **Fixes Applied** | 3 (C1, C2, C3 — in progress) |

### CRITICAL

| ID | Finding | File | Impact |
|----|---------|------|--------|
| C1 | No heartbeat for DAG workflow tasks during execution — `last_pulse` set once at claim, never updated. Janitor reclaims anything running >120s | `docker_service.py:_process_workflow_task` | Tasks killed mid-execution, duplicate processing |
| C2 | SKIPPED mandatory dep blocks downstream forever — conditional branch not taken → target SKIPPED → join node with mandatory dep deadlocks | `dag_graph_utils.py:all_predecessors_terminal` | Deadlocked runs on any reconvergent conditional |
| C3 | One run's error skips remaining runs in same scan — try/except wraps entire for-loop not each iteration | `docker_service.py:DAGBrainPrimaryLoop._loop` | One bad run starves all others for 5s |

### HIGH

| ID | Finding | File | Impact |
|----|---------|------|--------|
| H1 | Lock connection churn — each scan opens+closes dedicated TCP connection per active run for advisory lock | `dag_orchestrator.py:_open_lock_connection` | Connection exhaustion under load |
| H2 | Legacy tasks starve DAG tasks — dual-poll always tries legacy first | `docker_service.py:_run_loop` | DAG workflows blocked during transition |
| H3 | `contains`/`not_contains` crash on non-iterable — `in` on int/bool/None raises TypeError | `dag_fan_engine.py:192-195` | Unhandled crash fails entire run |
| H4 | max_cycles=1 adds 5s latency per sequential node — 10-node workflow = 50s pure wait | `docker_service.py:DAGBrainPrimaryLoop` | Slow workflows |
| H5 | Fan-out children corrupt `task_by_name` graph structures — children share template name | `dag_graph_utils.py:build_adjacency` | Latent corruption if non-fan-in depends on fan-out |

### MEDIUM

| ID | Finding | File | Impact |
|----|---------|------|--------|
| M1 | Stale snapshot across engine dispatch — each engine sees pre-mutation state | `dag_orchestrator.py:495-509` | +5s latency per state transition |
| M2 | Fan-in can aggregate from PENDING (skipping READY state) | `dag_fan_engine.py:650-654` | State machine violation |
| M3 | No thread join on shutdown — pool torn down while loop mid-query | `docker_service.py` lifespan | Crash on shutdown |
| M4 | New WorkflowRunRepository per poll cycle instead of cached | `docker_service.py:_claim_next_workflow_task` | Wasted allocations |
| M5 | Shared repo instance across threads — auth token thread safety unverified | `docker_service.py` lifespan | Theoretical race on token refresh |
| M6 | No size limit on result_data JSONB — fan-in of 1000 tiles could be huge | `workflow_run_repository.py` | Memory/network pressure |

### LOW

| ID | Finding | File |
|----|---------|------|
| L1 | Counter fields read/written across threads (safe under CPython GIL) | `docker_service.py:DAGBrainPrimaryLoop` |
| L2 | `in`/`not_in` operators crash on non-iterable operand (same pattern as H3) | `dag_fan_engine.py:188-191` |
| L3 | Worker ID not unique across container restarts (hostname:PID reuse) | `docker_service.py:655` |

### Confirmed OK

| ID | Checked | Verdict |
|----|---------|---------|
| OK1 | `is_run_terminal` + fan-out children | Correct — re-fetches tasks before terminal check |
| OK2 | Idempotency of engine dispatch | Correct — CAS guards in repository prevent double-promotion |
| OK3 | Claim atomicity (SELECT...FOR UPDATE SKIP LOCKED) | Correct — single transaction, no window for partial claims |
| OK4 | `update_run_status` transition guards | Correct — SQL WHERE prevents invalid transitions |
| OK5 | `list_active_runs` index support | Correct — partial index on status IN ('pending','running') |

### Fixes Applied (24 MAR 2026)

All CRITICAL and HIGH findings fixed. M2, M3, M4 also fixed. M1/M5/M6 accepted, L1-L3 accepted (L2 covered by H3 fix).

| ID | Severity | Fix | Commit |
|----|----------|-----|--------|
| C1 | CRITICAL | Heartbeat pulse thread in `_process_workflow_task` + `update_workflow_task_pulse` repo method | (session) |
| C2 | CRITICAL | SKIPPED treated as terminal in `all_predecessors_terminal` for all deps | (session) |
| C3 | CRITICAL | Per-run try/except in `DAGBrainPrimaryLoop._loop` | (session) |
| H3 | HIGH | TypeError guard on in/not_in/contains/not_contains operators | `2df00a21` |
| H5 | HIGH | Filter fan-out children from task_by_name + adjacency maps | `daff9cfa` |
| H2 | HIGH | Alternating legacy/DAG poll priority | `8e908022` |
| H4 | HIGH | Fast rescan when orchestrator makes progress (skip sleep) | `e1b1fe78` |
| H1 | HIGH | Transaction-level advisory locks via pooled connection | `960a2d8a` |
| M2 | MEDIUM | Fan-in only aggregates from READY + CAS guard on repo method | (session) |
| M3 | MEDIUM | Thread join on shutdown for primary loop, janitor, scheduler | (session) |
| M4 | MEDIUM | Cached WorkflowRunRepository in worker | (session) |

### Accepted Risks

| ID | Severity | Why Accepted |
|----|----------|-------------|
| M1 | MEDIUM | Stale snapshot: correctness OK, H4 fast rescan mitigates latency |
| M5 | MEDIUM | Token access is atomic reference swap under CPython GIL |
| M6 | MEDIUM | No size limit on result_data: not urgent, add warning log later |
| L1 | LOW | Counter fields: safe under GIL |
| L2 | LOW | Already fixed by H3 (same try/except block) |
| L3 | LOW | Worker ID collision: narrow edge case, correct behavior anyway |

---

## Run 54: DAG Orchestrator + Transition Engine Re-Review (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 26 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | DAG Orchestrator, Transition Engine, Fan Engine, Graph Utils, Janitor, Orchestration Manager, Workflow Run Repository |
| **Version** | v0.10.6.3 |
| **Context** | Re-review of Run 47 scope (16 MAR 2026) + Run 53 fixes. 5 bug fixes applied since Run 47: advisory locks, fast rescan, failure propagation, fan-out filtering, conditional type guards |
| **Split** | A (Design vs Runtime) -- same as Run 47 for regression comparison |
| **Files** | 7 (dag_orchestrator.py, dag_transition_engine.py, dag_fan_engine.py, dag_graph_utils.py, dag_janitor.py, orchestration_manager.py, workflow_run_repository.py) |
| **Findings** | 15 total: 0 CRITICAL, 1 HIGH, 5 MEDIUM, 4 LOW, 5 verified safe |
| **Bug Fix Verification** | 4/5 correct, 1 regression (advisory lock) |
| **Constitution Violations** | 2 (Section 1.3/3.3: ContractViolationError swallowed in release lifecycle) |
| **Output** | `agent_docs/compete_run54_dag_orchestrator_rereview.md` |

### Bug Fix Verification (v0.10.5.8-5.10)

| Fix | Commit | Verdict |
|-----|--------|---------|
| Advisory lock session->transaction | `960a2d8a` | **REGRESSION** -- lock releases on commit, provides no concurrent protection |
| Fast rescan on progress | `e1b1fe78` | **PROBABLE OK** -- not in orchestrator, likely in docker_service.py |
| Failure propagation through dead branches | `250cbdae` | **CORRECT** -- dead required predecessors cascade SKIPPED |
| Fan-out children filtering | `daff9cfa` | **CORRECT** -- children excluded from adjacency/task_by_name |
| Conditional type guards | `2df00a21` | **CORRECT** -- TypeError caught, returns False |

### Top 5 Fixes

| # | Severity | Description | File | Effort |
|---|----------|-------------|------|--------|
| 1 | HIGH | Advisory lock releases immediately -- `pg_try_advisory_xact_lock` acquired and released within same `with` block due to `conn.commit()`. CAS guards compensate but lock provides zero protection. | `dag_orchestrator.py:230-255` | Medium |
| 2 | MEDIUM | Duplicate `aggregate_fan_in` method -- second definition (line 1059) accepts PENDING, contradicting Run 53 M2 fix | `workflow_run_repository.py:753-812, 1059-1095` | Small |
| 3 | MEDIUM | ContractViolationError swallowed in `_handle_release_lifecycle` and `_cache_outputs_on_release` (Constitution 1.3/3.3) | `dag_orchestrator.py:114, 145` | Small |
| 4 | LOW | Dead code in `_skip_task_and_descendants` -- descendant propagation disabled but iteration code remains | `dag_transition_engine.py:170-212` | Small |
| 5 | LOW | `get_tasks_for_run` and `get_deps_for_run` log at INFO (48+ lines/min/run) | `workflow_run_repository.py:283, 348` | Small |

### Accepted Risks

| ID | Severity | Why Accepted |
|----|----------|-------------|
| No wall-clock timeout | MEDIUM | max_cycles=1000 provides cycle ceiling; shutdown_event provides external escape |
| Stale snapshot across engines | MEDIUM | One extra cycle latency; terminal check uses fresh fetch |
| Double DB fetch per cycle | LOW | Second fetch needed for accurate terminal detection |

### Architecture Wins

- Pure graph functions in `dag_graph_utils.py` (zero DB, frozen DTOs)
- Fixed dispatch order (ARB decision, eliminates ordering bugs)
- CAS-guarded mutations throughout (defense-in-depth against concurrent access)
- Failure propagation through dead conditional branches (elegant handling of diamond DAGs)
- Fan-out/fan-in lifecycle (UniqueViolation idempotency, sorted aggregation, 5 modes)

### Comparison with Run 47

| Metric | Run 47 (16 MAR 2026) | Run 54 (26 MAR 2026) |
|--------|----------------------|----------------------|
| CRITICAL findings | 2 | 0 |
| HIGH findings | 3 | 1 (advisory lock regression) |
| MEDIUM findings | 2 | 5 (3 new, 2 carried) |
| Fixes since | 10 applied | 5 new verified |
| Constitution violations | 2 | 2 (different locations) |
| Overall health | Needs work | Substantially improved |

All 10 Run 47 fixes verified in codebase. 4 of 5 new fixes correct. Advisory lock regression is the primary remaining issue -- mitigated by CAS guards and single-replica deployment.

---

## Run 55: Workflow YAML Definitions + Loader/Registry/Initializer (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 26 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Workflow YAML definitions (11 files) + loader, registry, initializer, param resolver (4 Python modules) |
| **Version** | v0.10.6.3 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 15 (11 YAML workflows + `workflow_loader.py`, `workflow_registry.py`, `dag_initializer.py`, `param_resolver.py`) |
| **Findings** | 18 total: 0 CRITICAL, 2 HIGH, 6 MEDIUM, 10 LOW |
| **Constitution Violations** | 1 (Principle 5: missing `reversed_by` on `process_raster.yaml`) |
| **Output** | `agent_docs/compete_run53_yaml_workflows.md` |

**Scope Split C -- Alpha (Data Integrity) / Beta (Control Flow)**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | YAML schema correctness, parameter contracts, data validation, paired lifecycles | All 11 YAML files + `workflow_definition.py` |
| Beta | Loader validation gaps, initialization sequence, dependency resolution, error handling | `workflow_loader.py`, `workflow_registry.py`, `dag_initializer.py`, `param_resolver.py` |
| Gamma | Cross-scope blind spots: when-clause validation, result structure convention, conditional evaluator | All files |

**Top 5 Fixes**:

| # | Severity | Description | File |
|---|----------|-------------|------|
| 1 | HIGH | `aggregate_tiles.results` should be `aggregate_tiles.items` -- fan-in COLLECT mode stores under `items` key | `workflows/process_raster.yaml:138` |
| 2 | MEDIUM | Add `reversed_by: unpublish_raster` to `process_raster.yaml` (Principle 5 violation) | `workflows/process_raster.yaml:3` |
| 3 | LOW | `get_leaf_nodes()` does not strip `?` suffix from optional deps | `core/models/workflow_definition.py:165` |
| 4 | MEDIUM | Add loader validation for fan-out template Jinja2 variable references | `core/workflow_loader.py` (new method) |
| 5 | MEDIUM | Add STAC materialization nodes to `process_raster_single_cog.yaml` | `workflows/process_raster_single_cog.yaml` |

**Accepted Risks**:

| Risk | Severity | Why Accepted |
|------|----------|-------------|
| Inconsistent handler result structure (root vs `result` wrapper) | LOW | Each workflow correctly matches its handler; convention issue |
| Loader does not validate receives dotted path depth | MEDIUM | Runtime `resolve_dotted_path` provides clear errors |
| `resolve_task_params` raises on optional params | MEDIUM | Submission layer should apply defaults before initializer |
| `"truthy"` condition keyword in `ingest_zarr.yaml` | MEDIUM | Needs E2E verification when zarr ingest is first tested |
| Jinja2 NativeEnvironment template execution | LOW | Templates from trusted YAML files only |

**Architecture Wins**:
- 9-validation loader pipeline (cycle detection, reachability, fan-in pairing, handler verification)
- Deterministic run ID (SHA256 with explicit canonical JSON serializer)
- Three-pass task/dep builder (validate, build tasks, build edges with deduplication)
- Pure function parameter resolution (no DB, no I/O, independently testable)
- Conditional branch + optional dep convergence pattern (`process_raster.yaml`)

---

## Run 55: Tiled Raster Handlers (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 26 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Tiled raster handlers (never reviewed -- single COG path was Run 51) |
| **Version** | v0.10.6.3 |
| **Split** | C (Data vs Control Flow) |
| **Files** | 3 handler files + 4 context files |
| **Findings** | 16 total: 0 CRITICAL, 5 HIGH, 5 MEDIUM, 1 LOW, 5 blind spots |
| **Constitution Violations** | 2 (Principle 1: bbox [0,0,0,0] fallback; Principles 1+10: unvalidated fan-in results) |
| **Output** | `agent_docs/compete_run55_tiled_raster_handlers.md` |

**Scope Split C -- Alpha (Data Integrity) / Beta (Control Flow)**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | Pixel window correctness, COG metadata, nodata, spatial bounds, CRS handling | handler_generate_tiling_scheme, handler_process_single_tile, handler_persist_tiled, tiling_scheme.py |
| Beta | Fan-out/fan-in boundary, parallel execution safety, temp file isolation, partial failure | handler_process_single_tile, handler_persist_tiled, process_raster.yaml |
| Gamma | Blind spots: non-composable tile handler, container fallback, unvalidated fan-in, pixel_window validation | All files |

**Top 5 Fixes**:

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | Output-space pixel windows applied to source-space raster when CRS differs | HIGH | Add CRS guard or WarpedVRT for tile extraction |
| 2 | Fan-in result structure unvalidated -- tiles silently dropped | HIGH | Validate required keys, log/count skipped tiles |
| 3 | `[0,0,0,0]` bbox fallback masks missing spatial data (Constitution P1 violation) | HIGH | Fail explicitly when bounds missing |
| 4 | Tile dimensions discarded (width=0, height=0 in cog_metadata) | HIGH | Propagate pixel dimensions from fan-out results |
| 5 | Redundant double COG stamp after upload | MEDIUM | Remove second stamp block (create_cog already stamps) |

**Accepted Risks**:

| Risk | Severity | Why Accepted |
|------|----------|-------------|
| Non-composable tile handler (create+upload in one handler) | MEDIUM | Design inconsistency with single COG path, not a bug |
| Non-retryable tiles (`retryable: False`) | MEDIUM | DAG framework handles retry at task level |
| Azure Files IOPS for 24+ concurrent reads | LOW | Within Premium tier limits at current scale |
| `cog_container` property equivalence assumed | LOW | Verify if storage config refactored |
| Partial persist success returns `success: True` | MEDIUM | Visible after Fix 2; all-or-nothing semantics deferred |

**Architecture Wins**: Fan-out temp file isolation (Bug #16 fix confirmed), deterministic STAC item IDs, stateless tiling scheme, consistent handler return contracts.

---

## Run 56: STAC Consolidated Builders + Materialization Path (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 26 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | STAC consolidated builders and materialization path (post-consolidation review) |
| **Version** | v0.10.6.3 |
| **Context** | Major STAC consolidation completed -- multiple builders replaced with canonical `build_stac_item` + `build_stac_collection` + `materialize_to_pgstac`. Verifying nothing was lost. |
| **Split** | B (Internal vs External) |
| **Files** | 10 (builders, handlers, materializer, pgstac_repository, search registration, stac_renders, stac models) |
| **Findings** | 15 total: 1 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW, 4 blind spots |
| **Constitution Violations** | 3 (Principle 1: silent datetime fallthrough, get_collection error masking, vector heuristic fallback) |
| **Output** | `agent_docs/compete_run56_stac_consolidated.md` |

**Scope Split B -- Alpha (Internal) / Beta (External)**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | STAC item/collection building, metadata correctness, render key generation, caller validation | stac_item_builder.py, stac_collection_builder.py, stac_preview.py, stac_renders.py, core/models/stac.py, handler callers |
| Beta | pgSTAC write path, TiTiler contract, search registration, error handling at boundary | stac_materialization.py, pgstac_repository.py, pgstac_search_registration.py, materialize handlers |
| Gamma | Blind spots: xarray signature mismatch, preview items, STAC validation gap, orphaned Epoch 4 builders | All files |

**Top 5 Fixes**:

| # | Severity | Description | File |
|---|----------|-------------|------|
| 1 | CRITICAL | `_inject_xarray_urls` called with 2 args but signature accepts 1 -- TypeError on all zarr Epoch 5 materialization | `stac_materialization.py:175 vs :991` |
| 2 | HIGH | `get_collection` returns None on DB error, causing spurious collection auto-create | `pgstac_repository.py:344-346` |
| 3 | HIGH | `_is_vector_release` fallback heuristic silently misclassifies raster as vector on DB error | `stac_materialization.py:860-869` |
| 4 | HIGH | Partial `start_datetime` without `end_datetime` silently falls to sentinel | `stac_item_builder.py:63-71` |
| 5 | MEDIUM | No STAC item validation before pgSTAC write (`STACItemCore` exists but unused) | `stac_materialization.py:195` |

**Accepted Risks**:

| Risk | Severity | Why Accepted |
|------|----------|-------------|
| Non-transactional collection+item write | MEDIUM | Upsert is idempotent; orphan shells recoverable |
| Preview items lack render extension | LOW | By design; replaced at approval time |
| Orphaned `to_stac_item()` in Epoch 4 | LOW | Frozen per Standard 5.4; removed at v0.11.0 |
| Connection pool pressure (per-operation connections) | MEDIUM | Acceptable at current scale (24 tiles max) |
| Search registration failure non-fatal | LOW | Items still accessible; mosaic preview is optional |

**Architecture Wins**:
- Pure function builders (no I/O, no side effects, independently testable)
- Single canonical write path (`materialize_to_pgstac` 6-step sequence)
- B2C sanitization as structural guarantee (geoetl:* never leaks)
- Idempotent upserts throughout (safe for retry, resubmit, concurrent access)
- Clean strangler fig: old builders deleted, Epoch 4 `to_stac_item()` frozen with TODO markers

---

## Run 57: SIEGE-DAG Run 1 — Epoch 5 DAG Workflow Smoke Test (SIEGE-DAG)

| Field | Value |
|-------|-------|
| **Date** | 28 MAR 2026 |
| **Pipeline** | SIEGE-DAG (new — Epoch 5 only) |
| **Scope** | DAG workflow E2E: raster, vector, NC→zarr, native zarr, unpublish |
| **Version** | v0.10.8.2 |
| **Sequences** | D1-D7 (of 10) |
| **Findings** | 5 total: 1 CRITICAL, 1 HIGH, 2 MEDIUM, 1 LOW |
| **Fixes Applied** | 8 (F-1 through F-5 + 3 earlier session fixes) |
| **Accepted Risks** | 0 |

**Results**: 24/30 steps PASS (80%)

| Seq | Name | Workflow | Result |
|-----|------|----------|--------|
| D1 | Raster Lifecycle | `process_raster` (13 tasks) | **PASS** — COG served via TiTiler |
| D2 | Vector Lifecycle | `vector_docker_etl` (6 tasks) | **PASS** — PostGIS table created |
| D3 | NetCDF Lifecycle | `ingest_zarr` NC path (9 tasks) | **PASS** — pyramid + STAC |
| D4 | Native Zarr Lifecycle | `ingest_zarr` Zarr path | **FAIL** — download_to_mount can't handle .zarr prefix |
| D6 | Unpublish Raster | CoreMachine (DAG not wired) | **PASS** |
| D7 | Unpublish Vector | CoreMachine (DAG not wired) | **PASS** |

**Findings and Fixes Applied (same session)**:

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| F-1 | MEDIUM | Status `services` block null for DAG runs — release not resolved from `workflow_runs` | `trigger_platform_status.py`: resolve release via `dag_run.release_id` |
| F-3 | MEDIUM | Catalog `xarray_urls` empty — `zarr_register_metadata` doesn't cache stac_item_json in release | `handler_register.py`: add `update_stac_item_json()` call; `ingest_zarr.yaml`: add `release_id` to params |
| F-4 | HIGH | `download_to_mount` misclassifies `.zarr` as single file (dot in name) | `etl_mount.py`: `.zarr` suffix treated as directory store |
| FK-1 | CRITICAL | `asset_releases.job_id` FK violation — DAG run_id not in jobs table | `submit.py`: guard `link_job_to_release` with `if workflow_engine != 'dag'` |
| SX-1 | MEDIUM | Spatial extent uses global bbox fallback for pyramid stores | `handler_validate_source.py`: extract bbox, pass via YAML receives to register |

**Additional fixes from plan (5 remaining bugs)**:

| Fix | File | Change |
|-----|------|--------|
| TiPG two-phase discovery | `vector_docker_etl.yaml` v2→v3 | `refresh_tipg_preview` pre-approval (browsable), `register_catalog` + `refresh_tipg` post-approval (searchable) |
| `file_size_bytes` None | `handler_validate.py` | `os.path.getsize()` fallback when header size is 0 |
| `materialize_collection` skipped | `process_raster.yaml` | Removed `?` from `materialize_single_item` dependency |

**Report**: `docs/archive/agent_review/SIEGE_DAG_RUN_1.md`
**Template**: `docs/agent_review/agents/SIEGE_DAG_AGENT.md`

---

## Run 58: Platform API Surface (COMPETE — T7)

| Field | Value |
|-------|-------|
| **Date** | 28 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Scope** | Platform API surface — submission, status, catalog, DAG admin, resubmit |
| **Version** | v0.10.8.2 |
| **Split** | D (Security vs Functionality) |
| **Files** | 8 (submit.py, dag_bp.py, platform_bp.py, platform_job_submit.py, trigger_platform_status.py, trigger_platform_catalog.py, platform_catalog_service.py, resubmit.py) |
| **Series** | T7 in `COMPETE_DAG_SERIES.md` |
| **Findings** | 31 unique (after dedup): 1 CRITICAL, 5 HIGH, 8 MEDIUM, 5 LOW + 6 Gamma corrections |
| **Fixes Recommended** | 11 (Top 10 + G2 unaccepted) |
| **Accepted Risks** | 16 |
| **Total Tokens** | ~379K |
| **Wall Clock** | ~9.5 minutes |

**Scope Split D — Alpha (Functionality) / Beta (Security)**:

| Agent | Model | Tokens | Duration | Role |
|-------|-------|--------|----------|------|
| Alpha | Opus | 84K | 3m 20s | Feature completeness, business rules, state management, error handling |
| Beta | Opus | 131K | 3m 23s | Input validation, auth, injection, trust boundaries, error leakage |
| Gamma | Opus | 120K | 3m 07s | Contradictions, false positives, blind spots |
| Delta | Opus | 44K | 2m 57s | Synthesis and prioritization |

### Top 11 Fixes

| # | Severity | Title | File | Effort |
|---|----------|-------|------|--------|
| 1 | CRITICAL | F-string SQL in `platform_failures` (4 places) | `trigger_platform_status.py:1540-1631` | Small |
| 2 | HIGH | DAG `update_workflow_id` failure orphans run + release | `submit.py:440-456` | Medium |
| 3 | HIGH | Unpublish `dry_run` defaults False, docstring says True | `unpublish.py:161` | Small |
| 4 | HIGH | Unvalidated `limit`/`offset`/`hours` params | `trigger_platform_status.py:232,1511` | Small |
| 5 | HIGH | Exception messages leaked in 500 responses (3 endpoints) | `platform_bp.py`, `resubmit.py`, `unpublish.py` | Small |
| 6 | HIGH | Sync `platform_submit` blocks async event loop under concurrent load | `platform_bp.py:228` | Medium |
| 7 | MEDIUM | `clearance_level` parsed but never forwarded (dead code) | `submit.py:163-171` | Medium |
| 8 | MEDIUM | `_finalize_response`: double parse + overly broad except | `platform_bp.py:83-105` | Small |
| 9 | MEDIUM | `dag_trigger_schedule` ignores `max_concurrent` | `dag_bp.py:784-823` | Medium |
| 10 | MEDIUM | Silent `except: pass` in STAC preflight | `submit.py:239-240` | Small |
| 11 | MEDIUM | YAML registry re-loaded every DAG submission | `platform_job_submit.py:284-286` | Small |

### Accepted Risks

| ID | Title | Rationale |
|----|-------|-----------|
| B-C2/C3 | Unauthenticated DAG handler execution + schedule CRUD | APP_MODE gated + Easy Auth on Function App. RBAC hardening planned as separate epic. |
| A2 | `_with_cache` shim with no callers | Dead code, harmless. Remove in next cleanup. |
| A3 | Registry endpoints bypass `_finalize_response` | MEDIUM (Gamma downgrade). Only missing X-Request-Id + error normalization on admin endpoints. |
| A9/B-L3 | Inconsistent error envelopes DAG vs platform | Separate API contracts; unify at v0.11.0 strangler completion. |
| B-H6 | Resubmit defaults dry_run=False | Gamma downgraded: resubmit is retry, not destructive in same sense as unpublish. |
| B-H7 | workflow_engine bypass of Pydantic validation | Gamma downgraded to MEDIUM: deliberate routing mechanism, not exploitable. |
| B-M1 | Raw `_get_connection` in health/failures | Diagnostic endpoints legitimately need raw DB. Low risk. |
| G3 | INTERVAL parameter fragility | psycopg2 parameterization works correctly here. Theoretical only. |
| G4 | `_get_latest_checkpoint` silent exception swallow | Best-effort enrichment; checkpoint failure should not block status. |
| G6 | Deprecated `services["collection"]` alias | Tech debt. Remove at v0.11.0. |

### Gamma Corrections

| Finding | Original | Corrected | Reason |
|---------|----------|-----------|--------|
| Alpha-2 | HIGH | LOW | Dead code, not functional defect |
| Alpha-3 | HIGH | MEDIUM | Only X-Request-Id gap, not full middleware bypass |
| Beta-H6 | HIGH | LOW | Resubmit is retry, not destructive op |
| Beta-H7 | HIGH | MEDIUM | Deliberate routing, inelegant not exploitable |
| Beta-M5 | MEDIUM | LOW | Admin-only behind APP_MODE gate |
| Gamma-G2 | Accepted→Fix | HIGH | User unaccepted: sync submit blocking event loop under concurrent load |

### Architecture Wins

1. Compensating action pattern on submit failure (orphan cleanup)
2. `_finalize_response` middleware consolidation
3. Error sanitization in failures endpoint (CASE-based bucketing)
4. APP_MODE gating for admin blueprints
5. Dry-run validation pathway on submit
6. YAML-based workflow registry (no code deploy for workflow changes)

---

## Run 59: T1 DAG Engine — Orchestration & State Machine (COMPETE)

| Field | Value |
|-------|-------|
| **Date** | 28 MAR 2026 |
| **Pipeline** | COMPETE (Adversarial Code Review) |
| **Series** | COMPETE DAG Series — Target T1 |
| **Scope** | DAG engine orchestration: transition engine, fan engine, graph utils, orchestrator |
| **Version** | v0.10.9.0 |
| **Split** | A (Design vs Runtime) + Single-Database Lens |
| **Files** | 4 (Epoch 5 only) |
| **Lines** | 2,206 |
| **Findings** | 18 total: 0 CRITICAL, 4 HIGH, 11 MEDIUM, 7 LOW |
| **Fixes Applied** | 15 (all 4 HIGH + all 11 MEDIUM). 7 LOWs left in place. |
| **Accepted Risks** | 3 (down from 8) |
| **New File** | `core/dag_repository_protocol.py` — DAGRepositoryProtocol (13 methods) |
| **Verdict** | Architecturally sound. Zombie run bug fixed. All MEDIUM+ resolved. |

**Scope Split A — Alpha (Design) / Beta (Correctness) + Single-Database Lens**:

| Agent | Scope | Focus |
|-------|-------|-------|
| Alpha | Architecture, contracts, composition, layering | All 4 files, emphasis on DTO contracts and engine coupling |
| Beta | Correctness, concurrency, state machine, error recovery | All 4 files, emphasis on race conditions and terminal detection |
| Gamma | Contradictions, blind spots, cross-file interactions | Priority: dag_graph_utils.py, tick ordering interactions |

**Top 5 Fixes**:

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | `max_cycles_exhausted` doesn't mark run FAILED — zombie run | HIGH | Add `update_run_status(FAILED)` in else clause |
| 2 | `expand_fan_out` SQL no CAS guard on template status | HIGH | Add `AND status = 'ready'` to WHERE clause |
| 3 | Terminal FAILED passes None error_message to Release | HIGH | Extract error from failed tasks before calling Release lifecycle |
| 4 | Gate reconciliation hardcodes `"approval_gate"` | MEDIUM | Discover gate name from WAITING tasks dynamically |
| 5 | ReleaseRepository() instantiated per call | MEDIUM | Lazy-init on orchestrator instance |

**Accepted Risks (3)**:

| ID | Risk | Rationale |
|----|------|-----------|
| AR5 | Disabled descendant propagation in `_skip_task_and_descendants` | Intentional design — transition engine handles cascade correctly |
| AR6 | `all_predecessors_terminal` accepts unused `optional_deps` param | Actual logic lives in caller (evaluate_transitions:391-406) |
| AR8 | `time.sleep` blocks thread (5s max shutdown delay) | Not operationally significant |

**LOWs left in place (7)**: `_SYSTEM_MAX_FAN_OUT` dead constant, unused `optional_deps` param, partially dead `_build_optional_deps`, disabled descendant propagation code (26 lines), `name_to_task` dead variable, `time.sleep` blocks thread, `evaluate_conditionals` stores no result_data.

**Report**: `docs/agent_review/COMPETE_T1_DAG_ENGINE.md`
**Series Tracker**: `docs/agent_review/agents/COMPETE_DAG_SERIES.md`
