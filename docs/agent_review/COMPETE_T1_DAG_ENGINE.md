# COMPETE T1 — DAG Engine Orchestration & State Machine

**Run**: 59
**Date**: 28 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Series**: COMPETE DAG Series — Target T1
**Version**: v0.10.9.0
**Split**: A (Design vs Runtime) + Single-Database Lens
**Files**: 4 (Epoch 5 only — zero Epoch 4 contact)
**Lines**: 2,206
**Findings**: 18 total — 0 CRITICAL, 4 HIGH, 11 MEDIUM, 7 LOW (after recalibration)
**Fixes Applied**: 15 (all HIGH + all MEDIUM). LOWs left in place.
**Accepted Risks**: 3 (down from 8 — 5 former accepted risks now fixed)

---

## EXECUTIVE SUMMARY

The DAG engine subsystem is architecturally sound — clean separation between graph utilities (pure functions, zero DB), transition engine, fan engine, and orchestrator loop. The fixed dispatch order, CAS-guarded DB mutations, and idempotent design make it resilient to concurrent ticks and restarts. The review found 18 issues (4 HIGH, 11 MEDIUM, 7 LOW). All HIGH and MEDIUM findings have been fixed in this session, including: a zombie-run bug where `max_cycles_exhausted` left runs in RUNNING status indefinitely, a missing CAS guard on fan-out expansion, a stale error message passed to the Release lifecycle, and a layering violation resolved by extracting a `DAGRepositoryProtocol` in core/. The stale-snapshot latency issue (previously an accepted risk) was also fixed via conditional re-fetch between dispatch phases. Three accepted risks remain (all LOW-impact design decisions). Seven LOWs (dead code, dead variables, minor documentation gaps) are left in place.

---

## TOP 5 FIXES

### Fix 1: Zombie run on max_cycles_exhausted

**WHAT**: The `for...else` block at the end of the poll loop logs a warning but never marks the run as FAILED. The run stays RUNNING forever.

**WHY**: A stuck workflow will consume a DAG Brain lease slot indefinitely. The janitor will eventually reap the lease, but the run itself remains RUNNING — no alert, no retry, no cleanup. Over time this silently accumulates zombie runs.

**WHERE**: `core/dag_orchestrator.py`, `DAGOrchestrator.run()`, lines 547-554 (the `else` clause of the `for cycle in range(max_cycles)` loop).

**HOW**: After setting `result.error = "max_cycles_exhausted"`, add:
```python
self._repo.update_run_status(run_id, WorkflowRunStatus.FAILED)
result.final_status = WorkflowRunStatus.FAILED
_handle_release_lifecycle(
    run, WorkflowRunStatus.FAILED, self._repo,
    error_message="max_cycles_exhausted",
)
```
This matches the pattern already used at lines 528-540 for `max_consecutive_errors`.

**EFFORT**: Small (< 1 hour).
**RISK OF FIX**: Low.

---

### Fix 2: expand_fan_out SQL missing CAS guard on template status

**WHAT**: The UPDATE that marks a fan-out template as EXPANDED has no `AND status = 'ready'` guard. Any concurrent process (e.g., janitor) that resets the template could have its state silently overwritten.

**WHY**: Without a status guard, a race condition exists: if the janitor fails the template (e.g., timeout) between the orchestrator's SELECT and this UPDATE, the template gets set back to EXPANDED, masking the failure.

**WHERE**: `infrastructure/workflow_run_repository.py`, `expand_fan_out()`, lines 796-799.

**HOW**: Add `AND status = 'ready'` to the WHERE clause. Check `cur.rowcount == 0` — if zero rows updated, return False (same as UniqueViolation path).

**EFFORT**: Small (< 1 hour).
**RISK OF FIX**: Low.

---

### Fix 3: Terminal FAILED passes None error_message to Release lifecycle

**WHAT**: When the orchestrator detects a terminal FAILED state, it passes `result.error` as the error_message. At that point `result.error` is None. The Release record receives "Unknown error" instead of the actual task-level failure message.

**WHY**: Violates P11 (traceable state changes). Operators looking at the Release table see "Unknown error" for legitimately failed workflows.

**WHERE**: `core/dag_orchestrator.py`, `DAGOrchestrator.run()`, lines 503-506.

**HOW**: Before calling `_handle_release_lifecycle`, extract the actual error from failed tasks:
```python
failed_tasks = [t for t in tasks if t.status == WorkflowTaskStatus.FAILED]
if failed_tasks:
    first_error = (failed_tasks[0].result_data or {}).get('error') or 'Task failed'
    error_msg = f"{len(failed_tasks)} task(s) failed. First: {first_error}"
else:
    error_msg = result.error or "Unknown terminal failure"
```

**EFFORT**: Small (< 1 hour).
**RISK OF FIX**: Low.

---

### Fix 4: Hardcoded "approval_gate" in gate reconciliation

**WHAT**: Gate reconciliation at lines 298-325 hardcodes the string `"approval_gate"` as the gate node name.

**WHY**: Any workflow with a gate node named anything other than `"approval_gate"` will fail gate reconciliation silently — the run stays AWAITING_APPROVAL forever.

**WHERE**: `core/dag_orchestrator.py`, `DAGOrchestrator.run()`, lines 298-300 and 325-326.

**HOW**: Derive the gate node name dynamically from WAITING tasks:
```python
waiting_tasks = [t for t in self._repo.get_tasks_for_run(run_id)
                 if t.status == WorkflowTaskStatus.WAITING]
if waiting_tasks:
    gate_node_name = waiting_tasks[0].task_name
```

**EFFORT**: Small (< 1 hour).
**RISK OF FIX**: Low.

---

### Fix 5: ReleaseRepository instantiated per call — connection churn

**WHAT**: `_handle_release_lifecycle` imports and instantiates `ReleaseRepository()` on every invocation (up to 3 times per run).

**WHY**: Unnecessary connection churn under load. Also a layering violation (deferred import from infrastructure/ inside core/).

**WHERE**: `core/dag_orchestrator.py`, `_handle_release_lifecycle()`, lines 81-82.

**HOW**: Lazy-init on the orchestrator:
```python
def _get_release_repo(self):
    if self._release_repo is None:
        from infrastructure import ReleaseRepository
        self._release_repo = ReleaseRepository()
    return self._release_repo
```

**EFFORT**: Small (< 1 hour).
**RISK OF FIX**: Low.

---

## FIXES APPLIED (28 MAR 2026)

All HIGH and MEDIUM findings fixed. LOWs left in place.

### HIGH fixes (4)

| ID | Finding | File(s) Changed | Fix |
|----|---------|-----------------|-----|
| F8 | Zombie run on max_cycles_exhausted | `dag_orchestrator.py` | Added `update_run_status(FAILED)` + release lifecycle in else clause |
| BS1/F1 | expand_fan_out no CAS guard | `workflow_run_repository.py` | Added `AND status = 'ready'` + rowcount check |
| BS4 | Terminal FAILED passes None error | `dag_orchestrator.py` | Extract error from failed tasks before release lifecycle call |
| H1 | Layering violation (core→infrastructure) | New `dag_repository_protocol.py` + `dag_orchestrator.py` | Created `DAGRepositoryProtocol` in core/, orchestrator uses Protocol |

### MEDIUM fixes (11)

| ID | Finding | File(s) Changed | Fix |
|----|---------|-----------------|-----|
| H2 | `repo` untyped in engines | `dag_transition_engine.py`, `dag_fan_engine.py` | TYPE_CHECKING guard + `DAGRepositoryProtocol` type hints |
| H3+BS5 | `_cache_outputs_on_release` undocumented + no status filter | `dag_orchestrator.py` | Added COMPLETED-only filter + documented expected fields |
| AR2/F4 | Stale snapshot across dispatch phases | `dag_orchestrator.py` | Conditional re-fetch between transitions and conditionals/fans |
| AR5 | Duplicate params prefix resolution | `param_resolver.py`, `dag_transition_engine.py`, `dag_fan_engine.py` | Extracted `resolve_param_or_predecessor()` into param_resolver |
| M4 | tasks_promoted conflated | `dag_orchestrator.py` | Split into `tasks_promoted`, `conditionals_taken`, `fan_out_children`, `fan_ins_aggregated` |
| AR4 | 20-col positional tuple | `dag_fan_engine.py` | Added `_CHILD_COLUMNS` constant + `_build_child_tuple()` helper |
| BS3 | Optional SKIPPED pred + when-clause = PENDING forever | `dag_transition_engine.py` | Check all_predecessors_terminal in catch; fail task if all terminal |
| F3 | fail_task docstring mismatch | `workflow_run_repository.py` | Updated docstring to match actual SQL guard |
| AR2 (gate) | Gate reconciliation hardcoded name | `dag_orchestrator.py` | Dynamic discovery from WAITING tasks |
| AR3 | ReleaseRepository per-call | `dag_orchestrator.py` | Lazy-init `_get_release_repo()` on orchestrator |
| F7 | Gate reconciliation hardcoded (same as AR2 gate) | (merged with AR2 gate above) | — |

### New file created

| File | Purpose |
|------|---------|
| `core/dag_repository_protocol.py` | `DAGRepositoryProtocol` — typed contract for DAG repository operations (13 methods) |

---

## ACCEPTED RISKS (remaining after fixes)

| ID | Finding | Why Acceptable | Revisit When |
|----|---------|----------------|--------------|
| AR5 | `_skip_task_and_descendants` disabled descendant propagation | Intentional design — transition engine handles cascade | Never (deliberate) |
| AR6 | `all_predecessors_terminal` accepts unused `optional_deps` param | Actual optional-dep logic in caller (evaluate_transitions:391-406) | Moving optional-dep awareness into graph utils |
| AR8 | `time.sleep` blocks thread (5s max shutdown delay) | Shutdown latency not operationally significant | When shutdown responsiveness matters |

---

## ARCHITECTURE WINS

1. **Fixed dispatch order** (transitions → conditionals → fan-outs → fan-ins) at `dag_orchestrator.py:433-447`. Documented as deliberate ARB decision. Eliminates ordering bugs, makes tick behavior deterministic.

2. **Pure graph utilities with zero DB access** in `dag_graph_utils.py`. `build_adjacency`, `get_descendants`, `all_predecessors_terminal`, `is_run_terminal` are all stateless pure functions. Trivially testable.

3. **CAS-guarded mutations throughout**. `promote_task`, `skip_task`, `set_params_and_promote` all use `WHERE status = X` guards. Orchestrator is genuinely idempotent.

4. **Lease-agnostic orchestrator design**. Accepts `lease_check` callable rather than owning lease logic. Clean separation: Brain manages leases, orchestrator manages DAG state. Testable with `lease_check=None`.

5. **Non-fatal Release lifecycle handling**. Entire `_handle_release_lifecycle` (lines 59-122) wrapped in try/except that logs but never crashes the orchestrator. Release DB failure does not abort workflow run.

6. **ContractViolationError propagation policy**. Every catch block re-raises CVE immediately. Programming bugs are never swallowed.

7. **Frozen TaskSummary dataclass** (`dag_graph_utils.py:53`). Immutability prevents accidental mutation across engine boundaries within a single tick.

---

## FULL FINDINGS (Gamma-Recalibrated)

### HIGH

| ID | Source | Finding | Confidence |
|----|--------|---------|------------|
| F8 | Beta | `max_cycles_exhausted` does NOT mark run FAILED — zombie run | CONFIRMED |
| BS1/F1 | Gamma+Beta | `expand_fan_out` SQL no CAS guard on template status | CONFIRMED |
| H1 | Alpha | Layering violation: `dag_orchestrator.py:48` imports infrastructure/ | CONFIRMED |
| BS4 | Gamma | Terminal FAILED passes None error_message to Release lifecycle | CONFIRMED |

### MEDIUM

| ID | Source | Finding | Confidence |
|----|--------|---------|------------|
| F4/BS2 | Beta+Gamma | Stale snapshot adds 1 cycle latency per transition boundary | CONFIRMED |
| H2 | Alpha | `repo` parameter untyped — no Protocol/ABC (P10) | CONFIRMED |
| H3 | Alpha | `_cache_outputs_on_release` depends on undocumented handler output fields (P10) | CONFIRMED |
| AR2 | Both | Gate reconciliation hardcodes "approval_gate" | CONFIRMED |
| AR3 | Both | ReleaseRepository() per call — connection churn | CONFIRMED |
| AR5 | Alpha | Duplicate `params.` prefix resolution (DRY) | CONFIRMED |
| M4 | Alpha | `OrchestratorResult.tasks_promoted` conflates distinct event types | CONFIRMED |
| AR4 | Both | 20-element positional tuple coupled to repo internals | CONFIRMED |
| BS3 | Gamma | Optional SKIPPED predecessor + when-clause = PENDING forever | PROBABLE |
| BS5 | Gamma | `_cache_outputs_on_release` may cache FAILED task's partial results | PROBABLE |
| F3 | Beta | `fail_task` docstring contradicts actual SQL guard | CONFIRMED |

### LOW

| ID | Source | Finding | Confidence |
|----|--------|---------|------------|
| AR1 | Both | `_SYSTEM_MAX_FAN_OUT` dead constant | CONFIRMED |
| H4 | Alpha | `all_predecessors_terminal` accepts unused `optional_deps` | CONFIRMED |
| L2 | Alpha | `_build_optional_deps` partially dead path | CONFIRMED |
| M2 | Alpha | Intentionally disabled descendant propagation (26 lines unreachable) | CONFIRMED |
| F5 | Beta | `name_to_task` dead variable | CONFIRMED |
| R3 | Beta | `time.sleep` blocks thread — could use `shutdown_event.wait()` | CONFIRMED |
| L3 | Alpha | `evaluate_conditionals` stores no result_data (branch taken not queryable) | CONFIRMED |

---

## PIPELINE METADATA

| Agent | Duration | Tokens | Key Contribution |
|-------|----------|--------|------------------|
| Omega | — | — | Split A + Single-Database Lens, scoped to 4 Epoch 5 files |
| Alpha | ~2.5 min | ~66K | 8 strengths, 6 concerns (3 HIGH, 4 MEDIUM, 3 LOW), 5 assumptions, 7 recommendations |
| Beta | ~2.5 min | ~75K | 10 verified safe, 8 findings (2 HIGH, 6 MEDIUM), 3 risks, 4 edge cases |
| Gamma | ~3 min | ~71K | 3 contradictions, 5 agreement reinforcements, 6 blind spots, full recalibration |
| Delta | ~1.5 min | ~55K | Final report, top 5 fixes, 8 accepted risks, 7 architecture wins |
