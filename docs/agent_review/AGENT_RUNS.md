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
| **Accepted Risks** | 3 (no janitor — deferred v0.10.4, health check auth — diagnostics exception, double PROCESSING write — SB compat) |
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
| **Fixes Applied** | Pending — 5 recommended (all Small effort, Low risk) |
| **Output** | `agent_docs/compete_run46_dag_data_layer.md` |

**Top 5 Fixes**:

| # | Severity | Description | File |
|---|----------|-------------|------|
| 1 | HIGH | Replace `default=str` with explicit canonical serializer in `_generate_run_id` | `core/dag_initializer.py:44-56` |
| 2 | HIGH | Wire `WorkflowNotFoundError`/`WorkflowValidationError` into `BusinessLogicError` hierarchy | `core/workflow_registry.py:22`, `core/workflow_loader.py:27` |
| 3 | MEDIUM | Raise `ContractViolationError` for unknown IDs in `_build_adjacency_from_tasks` | `core/dag_fan_engine.py:212-216` |
| 4 | MEDIUM | Add cross-field validation to `RetryPolicy` (initial_delay <= max_delay) | `core/models/workflow_definition.py:24-29` |
| 5 | MEDIUM | Return fresh task state from `claim_ready_workflow_task` (stale timestamps) | `infrastructure/workflow_run_repository.py:891-892` |

**Accepted Risks**: 6 (deterministic run_id resubmit, echo_test.yaml when-clause, non-atomic param+promote, no RUNNING timeout, uuid4 fan-out children, void fail_task)

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
| **Fixes Applied** | Pending — 5 recommended (2 CRITICAL, 1 HIGH, 2 MEDIUM) |
| **Output** | `agent_docs/compete_run47_dag_control_layer.md` |

**Top 5 Fixes**:

| # | Severity | Description | File |
|---|----------|-------------|------|
| 1 | CRITICAL | Add `handler` field to TaskSummary + SELECT — `evaluate_conditionals` crashes with AttributeError | `core/dag_graph_utils.py:52-66`, `infrastructure/workflow_run_repository.py:246-271` |
| 2 | CRITICAL | Exclude fan-out templates from worker claim — workers can claim templates before orchestrator expands, causing permanent DAG stall | `infrastructure/workflow_run_repository.py:855-862`, `core/dag_initializer.py:83` |
| 3 | HIGH | Fix `predecessor_outputs` dict collision — fan-out children share task_name, last child wins | `core/dag_orchestrator.py:369-376` |
| 4 | MEDIUM | Add `_ensure_fresh_tokens()` to `_process_workflow_task` | `docker_service.py:581` |
| 5 | MEDIUM | Merge `set_task_parameters` + `promote_task` into single atomic UPDATE | `core/dag_transition_engine.py:387-394` |

**Accepted Risks**: 8 (expand_fan_out no CAS, aggregate_fan_in no CAS, _build_adjacency silent skip, time.sleep not interruptible, stale snapshot, per-call repo instantiation, no heartbeat, no retry mechanism)

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
| **Accepted Risks** | 5 (NaT round-trip documented, mount cleanup deferred, multi-group partial failure, datetime→TEXT mapping, private API chaining) |
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

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19, 28-30, 33, 39, 42, 44, 46, 47, 49 | ~3.9M+ |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944K |
| SIEGE | Runs 11, 13, 18, 20-23, 25-26, 34-35, 37-38, 40-41, 43, 45 | ~2.5M+ |
| REFLEXION | Runs 14-17, 32 | ~975K |
| TOURNAMENT | Run 27 | ~278K |
| ADVOCATE | Runs 31, 36 | ~335K |
| DECOMPOSE | Run 48 | ~568K |
| **Total** | 49 runs | **~9.5M+** |
