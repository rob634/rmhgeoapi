# COMPETE T2 — DAG Engine Init & Param Resolution

**Run**: 60
**Date**: 28 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Series**: COMPETE DAG Series — Target T2
**Version**: v0.10.9.0
**Split**: C (Data vs Control Flow) + Single-Database Lens
**Files**: 9 (Epoch 5 only)
**Lines**: ~1,775
**Findings**: 17 total — 1 CRITICAL, 3 HIGH, 6 MEDIUM, 7 LOW (after recalibration)
**Fixes Applied**: 10 (1 CRIT + 3 HIGH + 6 MEDIUM). LOWs left in place.
**Accepted Risks**: 5

---

## EXECUTIVE SUMMARY

The DAG engine init and param resolution subsystem is architecturally sound, with clean separation between pure functions and I/O. However, there was one critical data-loss bug: `schedule_id` was silently dropped on INSERT and SELECT in the workflow_run_repository, making scheduler-originated runs untraceable. One HIGH blocker (`ingest_zarr.yaml` referencing undeclared `release_id`) prevented that workflow from loading. The scheduler path also skipped ParameterDef default application. All CRITICAL, HIGH, and MEDIUM findings have been fixed in this session. Five accepted risks remain (all LOW-impact design decisions or mitigated by other layers).

---

## FIXES APPLIED (28 MAR 2026)

### CRITICAL fix (1)

| ID | Finding | File(s) Changed | Fix |
|----|---------|-----------------|-----|
| AR-1 | `schedule_id` silently dropped on INSERT/SELECT | `workflow_run_repository.py` | Added `schedule_id` to INSERT columns, `_run_to_params` tuple, and `get_by_run_id` SELECT |

### HIGH fixes (3)

| ID | Finding | File(s) Changed | Fix |
|----|---------|-----------------|-----|
| HIGH-2 | `ingest_zarr.yaml` references undeclared `release_id` | `workflows/ingest_zarr.yaml` | Added `release_id: {type: str, required: false}` to parameters block |
| BS-2 | DAG Scheduler skips ParameterDef defaults | `core/dag_scheduler.py` | Added default-application loop before `create_run` call |
| HIGH-3 | ParameterDef defaults only in platform_job_submit | (same as BS-2) | Scheduler path now matches platform path |

### MEDIUM fixes (6)

| ID | Finding | File(s) Changed | Fix |
|----|---------|-----------------|-----|
| F4 | Pydantic ValidationError propagates unwrapped | `core/workflow_loader.py` | Wrapped in try/except, converts to WorkflowValidationError |
| BS-1 | 7 models lack `extra='forbid'` (typos silently ignored) | `core/models/workflow_definition.py` | Added `ConfigDict(extra='forbid')` to RetryPolicy, BranchDef, FanOutTaskDef, FinalizeDef, ParameterDef, GateNode, WorkflowDefinition |
| M2+M3 | FanOutNode.source and ConditionalNode.condition not validated at load time | `core/workflow_loader.py` | Added `_check_fan_out_source_refs` and `_check_condition_refs` validations |
| M5/E3 | `resolve_param_or_predecessor` returns None for missing params (wrong for conditionals) | `core/param_resolver.py`, `core/dag_fan_engine.py` | Added `strict` kwarg; conditionals use `strict=True`, when-clauses keep `strict=False` |

---

## ACCEPTED RISKS

| ID | Finding | Why Acceptable | Revisit When |
|----|---------|----------------|--------------|
| AR-M1 | `task_instance_id` can exceed `max_length=100` if `task_name` > 87 chars | All current YAML node names < 30 chars; Pydantic will raise explicitly | Node names > 50 chars |
| AR-M4 | `gate_type` lost in task materialization | Only "approval" type exists; transition engine uses WAITING status uniformly | Second gate type introduced |
| AR-HIGH3 | `ParameterDef.type` never enforced at runtime | Handlers validate own inputs; YAML schema is documentation | External/untrusted callers submit workflows |
| AR-F2 | `_build_tasks_and_deps` incomplete cycle detection | WorkflowLoader._check_cycles (Kahn's) catches all cycles on every load | Workflows submitted without loader |
| AR-RISK1 | Jinja2 NativeEnvironment allows Python expression eval | Only admin-authored YAML loaded; checked into git | User-supplied workflow definitions accepted |

---

## LOW FINDINGS (left in place)

| ID | Finding | Confidence |
|----|---------|------------|
| C-1 | `_build_tasks_and_deps` incomplete cycle detection (mitigated by loader) | CONFIRMED |
| L1 | `get_root_nodes()` uses different root definition than initializer | CONFIRMED |
| L2 | Jinja2 template syntax not validated at load time | CONFIRMED |
| BS-3 | `_check_param_refs` doesn't validate FanOutNode Jinja2 template variables | CONFIRMED |
| E4 | GateNode falls through to max_retries=0 without explicit check | CONFIRMED |
| RISK-1 | Jinja2 NativeEnvironment (trusted YAML only) | CONFIRMED |
| RISK-2 | Singleton registry not thread-safe on first access (benign) | CONFIRMED |

---

## ARCHITECTURE WINS

1. **Deterministic run_id via `_generate_run_id`** — SHA256 of workflow_name + canonical JSON params gives free idempotency. `_canonical_json_default` raises ContractViolationError for unrecognized types.

2. **Three-pass `_build_tasks_and_deps`** — Validate refs (Pass 1), build tasks with root-node param resolution (Pass 2), build edges with deduplication (Pass 3). Pure, no I/O, fully testable.

3. **Root node param resolution at init time** — Fast-fail on missing params before DB transaction.

4. **`resolve_dotted_path` with explicit error context** — Every failure includes path, node name, segments, available keys. Trivial to debug from logs.

5. **Atomic `insert_run_atomic` with rollback** — Single transaction for run + tasks + deps. UniqueViolation handled as idempotent return.

6. **WorkflowLoader 9-validation pipeline** — Structural validations collected and reported as batch (now 11 validations with fan-out source and condition refs added).

---

## PIPELINE METADATA

| Agent | Duration | Tokens | Key Contribution |
|-------|----------|--------|------------------|
| Omega | — | — | Split C + Single-Database Lens, 9 Epoch 5 files |
| Alpha | ~5.5 min | ~84K | 8 strengths, 10 concerns (3 HIGH, 5 MEDIUM, 2 LOW), 5 assumptions, 8 recommendations |
| Beta | ~6 min | ~76K | 14 verified safe, 4 findings (1 CRITICAL, 3 MEDIUM), 2 risks, 4 edge cases |
| Gamma | ~5.5 min | ~77K | 2 contradictions, 2 agreement reinforcements, 4 blind spots, full recalibration |
| Delta | ~3 min | ~60K | Final report, 6 top fixes, 5 accepted risks, 6 architecture wins |
