# COMPETE Run 46: DAG Data Layer (D.1-D.4)

**Date**: 16 MAR 2026
**Pipeline**: COMPETE (Adversarial Review)
**Scope**: DAG workflow definition, models, initialization, and parameter resolution
**Split**: C (Data vs Control Flow)
**Files Reviewed**: 12

---

## EXECUTIVE SUMMARY

The DAG workflow data layer is structurally sound. The YAML-to-Pydantic-to-DB pipeline follows a clean three-pass algorithm with proper deduplication, atomic persistence, and deterministic ID generation. Two HIGH-severity issues require attention before this subsystem goes live: the `default=str` serializer in `_generate_run_id` undermines the core idempotency guarantee, and the custom exception classes bypass the project's established exception hierarchy, creating silent catch-block misses. The remaining findings are MEDIUM or LOW severity and none are blockers. The codebase shows strong engineering discipline -- 9 structural validations in the loader, Kahn's cycle detection, and explicit `ContractViolationError` usage throughout.

---

## TOP 5 FIXES

### Fix 1: Replace `default=str` in `_generate_run_id` with explicit serializer

- **WHAT**: Replace `default=str` in `json.dumps()` with a whitelist serializer that handles known types deterministically.
- **WHY**: `default=str` produces `repr()`-style output for arbitrary objects, which is non-deterministic across Python versions and object instances. A `datetime` object serializes differently depending on microsecond precision. This breaks the idempotency guarantee -- the same logical parameters can produce different run_ids.
- **WHERE**: `core/dag_initializer.py`, function `_generate_run_id`, lines 44-56.
- **HOW**: Define a `_canonical_default(obj)` function that explicitly handles `datetime` (→ ISO 8601), `UUID` (→ hex string), `Decimal` (→ `str()`), `Enum` (→ `.value`), and raises `ContractViolationError` for anything else. Pass it as `default=_canonical_default`.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low

### Fix 2: Wire `WorkflowNotFoundError` and `WorkflowValidationError` into exception hierarchy

- **WHAT**: Make `WorkflowNotFoundError` inherit from `ResourceNotFoundError` and `WorkflowValidationError` inherit from `ValidationError`.
- **WHY**: Any caller catching `BusinessLogicError` will miss these exceptions. They inherit from bare `Exception`, which means they bypass error-handling middleware and could surface as unhandled 500s.
- **WHERE**: `core/workflow_registry.py` line 22, `core/workflow_loader.py` line 27.
- **HOW**: `class WorkflowNotFoundError(ResourceNotFoundError)` and `class WorkflowValidationError(ValidationError)`. Import from `exceptions`.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low

### Fix 3: Raise `ContractViolationError` for unknown IDs in `_build_adjacency_from_tasks`

- **WHAT**: Replace silent `if task_name and dep_name:` guard with an explicit error.
- **WHY**: Unknown task_instance_ids indicate data integrity violation. Silently skipping hides bugs and can cause incorrect skip-propagation.
- **WHERE**: `core/dag_fan_engine.py`, function `_build_adjacency_from_tasks`, lines 212-216.
- **HOW**: Check `if task_iid not in id_to_name or dep_iid not in id_to_name: raise ContractViolationError(...)`. Remove the `if task_name and dep_name:` guard.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low. If this fires, it indicates a real bug currently being masked.

### Fix 4: Add cross-field validation to `RetryPolicy`

- **WHAT**: Add a Pydantic `model_validator` that rejects `initial_delay_seconds > max_delay_seconds`.
- **WHY**: Without this, YAML authors can write nonsensical retry configurations that are silently accepted.
- **WHERE**: `core/models/workflow_definition.py`, class `RetryPolicy`, lines 24-29.
- **HOW**: Add `@model_validator(mode='after')` that raises `ValueError` if `self.initial_delay_seconds > self.max_delay_seconds`.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low

### Fix 5: Return fresh task state from `claim_ready_workflow_task`

- **WHAT**: Build the returned `WorkflowTask` with actual post-UPDATE field values instead of stale SELECT row.
- **WHY**: `started_at`, `last_pulse`, `claimed_by` are all stale (None) in the returned object despite being set by the UPDATE's NOW(). Any caller inspecting these gets wrong data.
- **WHERE**: `infrastructure/workflow_run_repository.py`, method `claim_ready_workflow_task`, lines 891-892.
- **HOW**: Use `UPDATE ... RETURNING *` and build from the RETURNING row, or patch `task.started_at`, `task.last_pulse`, `task.claimed_by` alongside the existing `task.status` patch.
- **EFFORT**: Small (< 1 hour)
- **RISK OF FIX**: Low

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit When |
|------|---------------|--------------|
| `when: "params.uppercase"` in echo_test.yaml deadlocks (Beta-F4) | Per spec — when-clause resolves predecessor outputs only. Test fixture, not production. | Writing user docs or if used as template |
| Deterministic run_id prevents re-running failed workflows (Beta-F1) | Prevents duplicate submissions (higher priority). Resubmit endpoint can add nonce later. | Implementing resubmit user story |
| set_task_parameters + promote_task non-atomic (Beta-F2) | Self-heals on next tick. Advisory lock prevents concurrent orchestrators. | Never — acceptable by design |
| No timeout detection for RUNNING tasks (Beta-F6) | Legacy backstop pattern exists. Planned for D.7/Guardian. | Before production deployment |
| Fan-out child IDs use uuid4() (Beta-F3) | Template-level CAS guard prevents double-expansion. | Never — acceptable |
| fail_task returns void (Beta-F5) | Status guard makes no-op UPDATEs safe. All callers log and continue. | If used in critical paths |

---

## ARCHITECTURE WINS

1. **Three-pass `_build_tasks_and_deps`** (dag_initializer.py:123-270): Clean separation of validation → construction → edge-building with deduplication via `seen_edges` set.

2. **Discriminated union for node types** (workflow_definition.py:117-120): Pydantic `Field(discriminator='type')` with `extra='forbid'` gives automatic deserialization, exhaustive type matching, and typo detection at parse time.

3. **Nine structural validations in WorkflowLoader** (workflow_loader.py:66-82): Kahn's cycle detection, BFS reachability, ref validation, handler checks — all collect errors rather than failing on first.

4. **Pure functions for all graph logic**: `_generate_run_id`, `_build_tasks_and_deps`, `_resolve_handler` are stateless. Trivially testable without DB fixtures.

5. **Consistent exception philosophy**: `ContractViolationError` for bugs, `BusinessLogicError` for runtime failures. Never caught, always bubbled (once Fix 2 applied).

6. **Atomic DB persistence**: Single-transaction write of run + tasks + deps with `UniqueViolation` idempotency. No partial state possible.

---

## AGENT STATISTICS

| Agent | Findings | Constitution Violations | Token Usage |
|-------|----------|------------------------|-------------|
| Alpha | 9 (3H, 4M, 2L) | 0 | 64k |
| Beta | 6 (1H, 4M, 1L) + 3 risks + 4 edge cases | 0 | 88k |
| Gamma | 5 blind spots + 2 contradictions + 2 constitution violations | 2 (Section 3.1, Section 1.1) | 86k |
| Delta | Top 5 fixes + 6 accepted risks | — | 53k |

**Gamma corrections**: Alpha-MEDIUM-2 (model_dump enum) = FALSE POSITIVE. Alpha-LOW-1 (missing CANCELLED) = INVALID (by design).
