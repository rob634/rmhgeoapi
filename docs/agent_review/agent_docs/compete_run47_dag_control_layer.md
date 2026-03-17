# COMPETE Run 47: DAG Control Layer (D.5-D.6)

**Date**: 16 MAR 2026
**Pipeline**: COMPETE (Adversarial Review)
**Scope**: DAG graph utilities, transition engine, fan engine, orchestrator, repository, worker dual-poll
**Split**: A (Design vs Runtime)
**Files Reviewed**: 6

---

## EXECUTIVE SUMMARY

The DAG workflow control layer is architecturally sound: the four-engine tick dispatch (transitions, conditionals, fan-out, fan-in) is cleanly separated, the advisory lock prevents concurrent orchestrator interference, and CAS guards on `promote_task` make the system idempotent against duplicate ticks. However, two CRITICAL bugs will cause runtime crashes or permanent DAG stalls in any workflow that uses conditional branching or fan-out. The `TaskSummary` DTO is missing the `handler` field that `evaluate_conditionals` accesses at line 280, and the worker claim query does not exclude fan-out templates, creating a race between worker claim and orchestrator expansion. Both must be fixed before any workflow using these features can run successfully.

---

## TOP 5 FIXES

### Fix 1: Add `handler` field to TaskSummary and SELECT

- **WHAT**: `TaskSummary` dataclass is missing the `handler` field that `evaluate_conditionals` accesses at line 280 (`t.handler`), causing an `AttributeError` crash on every tick that encounters a READY conditional.
- **WHY**: Any workflow with a `ConditionalNode` will crash the orchestrator. Guaranteed crash, not a race condition.
- **WHERE**: `core/dag_graph_utils.py` lines 52-66 (TaskSummary); `infrastructure/workflow_run_repository.py` lines 246-271 (get_tasks_for_run SELECT + constructor).
- **HOW**: Add `handler: str` to `TaskSummary`. Add `handler` to the SELECT column list. Add `handler=row["handler"]` to the TaskSummary constructor call.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — additive change to a frozen dataclass.

### Fix 2: Exclude fan-out templates from worker claim query

- **WHAT**: `claim_ready_workflow_task` excludes `__conditional__` and `__fan_in__` but fan-out templates use real handler names. Workers can claim templates before the orchestrator expands them, causing permanent DAG stall.
- **WHY**: Worker claims template → RUNNING. Orchestrator's `expand_fan_outs` filter (`status == READY`) never matches. Template never expanded. Fan-in waits forever.
- **WHERE**: `infrastructure/workflow_run_repository.py` lines 855-862 (claim query); `core/dag_initializer.py` line 83 (_resolve_handler for FanOutNode).
- **HOW**: Use a `__fan_out__` sentinel handler for templates (set in `_resolve_handler` at dag_initializer.py line 83), and add it to the exclusion list at repository line 858.
- **EFFORT**: Medium (1-4 hours) — coordinated changes in initializer + claim query.
- **RISK OF FIX**: Medium — touches initialization and claim paths; requires fan-out workflow test.

### Fix 3: Fix `predecessor_outputs` dict collision for fan-out children

- **WHAT**: Dict comprehension keys by `task_name`. Fan-out children share `task_name`, so last child wins. Wrong data for downstream `when` clauses and parameter resolution.
- **WHY**: Silently produces incorrect data for any workflow where non-fan-in tasks reference fan-out outputs.
- **WHERE**: `core/dag_orchestrator.py` lines 369-376 (predecessor_outputs construction).
- **HOW**: Skip fan-out children (`fan_out_source is not None`) from `predecessor_outputs`. They are consumed by fan-in directly, not by parameter resolution.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — fan-in aggregation uses separate code path.

### Fix 4: Add `_ensure_fresh_tokens()` to `_process_workflow_task`

- **WHAT**: Legacy `_process_task` calls `_ensure_fresh_tokens()` before handler execution. DAG `_process_workflow_task` does not.
- **WHY**: Managed Identity tokens expire after ~1 hour. DAG tasks may fail with auth errors.
- **WHERE**: `docker_service.py` line 581 (_process_workflow_task) — add call before handler lookup.
- **HOW**: Add `self._ensure_fresh_tokens()` as the first line, mirroring `_process_task` line 544.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — idempotent, already called on every legacy task.

### Fix 5: Merge `set_task_parameters` + `promote_task` into single atomic UPDATE

- **WHAT**: Two separate DB calls create a crash window where params are set but task stays PENDING.
- **WHY**: Process crash between the two calls leaves task with params but not promoted. Self-healing on next tick but wasteful.
- **WHERE**: `core/dag_transition_engine.py` lines 387-394; `infrastructure/workflow_run_repository.py` lines 783-837 and 411-484.
- **HOW**: Create `set_params_and_promote()` in WorkflowRunRepository: `UPDATE SET parameters = %s, status = 'ready', updated_at = NOW() WHERE task_instance_id = %s AND status = 'pending'`.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low — single atomic UPDATE is strictly safer.

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| `expand_fan_out` no CAS guard on template status | UniqueViolation on children provides idempotency. Advisory lock prevents concurrent calls. | Advisory lock removed |
| `aggregate_fan_in` no CAS guard | Deterministic aggregation + advisory lock. Double-call overwrites with identical data. | Advisory lock removed |
| `_build_adjacency_from_tasks` silently skips unknown IDs | Used only for skip-propagation where partial data is expected after fan-out expansion. | Used for correctness-critical decisions |
| `time.sleep` not interruptible by `shutdown_event` | Max 5s shutdown delay acceptable for background process. | cycle_interval increases |
| Stale tasks snapshot across all 4 engines | By design — fixed dispatch order trades one-tick latency for snapshot consistency. | Never |
| `WorkflowRunRepository` instantiated per-call in worker | Lightweight init, no connection until `_get_connection`. | Init gains expensive setup |
| No heartbeat/pulse for DAG tasks | Advisory lock + 3-error failsafe provide liveness. | Implementing stale-task reaper |
| `_process_workflow_task` has no retry mechanism | Deferred to D.7 handler retry story. | Before production deployment |

---

## ARCHITECTURE WINS

1. **Advisory lock pattern** — Dedicated non-pooled connection with TCP keepalives, 63-bit hash derivation, try/finally cleanup. Textbook implementation.

2. **Four-engine fixed dispatch order** — `transitions → conditionals → fan-outs → fan-ins` eliminates ordering bugs. Each engine is a pure function over snapshot + repo handle. No shared mutable state.

3. **CAS guards on all critical transitions** — `promote_task` (from_status), `skip_task` (pending/ready), `fail_task` (running/ready/pending), `complete_workflow_task` (running). Naturally idempotent.

4. **Clean separation: graph logic has zero DB imports** — `dag_graph_utils.py` is pure functions. Engines contain no SQL. All mutations go through `repo`. Unit-testable with mock repos.

5. **`is_run_terminal` defensive guard** — Rejects empty task lists with `ContractViolationError` rather than returning `(True, COMPLETED)`. Prevents false completion on DB query bugs.

6. **Fan-out `for/else` pattern** — Aborts entire expansion if any child's param resolution fails. No partial child sets persisted.

---

## AGENT STATISTICS

| Agent | Findings | Constitution Violations | Token Usage |
|-------|----------|------------------------|-------------|
| Alpha | 10 (3H, 5M, 2L) | 2 (Section 1.1, 4.1) | 80k |
| Beta | 8 findings + 3 risks + 3 edge cases | 0 | 81k |
| Gamma | 6 blind spots + 3 contradictions + 3 agreements | 0 new (confirmed Alpha's 2) | 74k |
| Delta | Top 5 fixes + 8 accepted risks | — | 65k |

**Gamma key finds**: BS1 (fan-out template race) = CRITICAL. BS2 (predecessor_outputs collision) = HIGH. Both missed by Alpha and Beta individually.
