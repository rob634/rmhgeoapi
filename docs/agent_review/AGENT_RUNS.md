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

| Pipeline | Runs | Total Tokens |
|----------|------|-------------|
| COMPETE | Runs 1-6, 9, 12, 19, 28-30, 33, 39, 42, 44, 46, 47 | ~3.6M+ |
| GREENFIELD | Runs 7, 8, 10, 24 | ~944K |
| SIEGE | Runs 11, 13, 18, 20-23, 25-26, 34-35, 37-38, 40-41, 43, 45 | ~2.5M+ |
| REFLEXION | Runs 14-17, 32 | ~975K |
| TOURNAMENT | Run 27 | ~278K |
| ADVOCATE | Runs 31, 36 | ~335K |
| **Total** | 47 runs | **~8.6M+** |
