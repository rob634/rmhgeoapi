# COMPETE Brief: DAG Data Layer (D.1-D.4)

**Pipeline**: COMPETE (Adversarial Review)
**Date**: 16 MAR 2026
**Scope**: DAG workflow definition, models, initialization, and parameter resolution
**Run Number**: Assign next sequential in AGENT_RUNS.md

---

## Context for Omega

This is the **data foundation** of a new DAG-based workflow orchestration system (V10 Migration). It was built across 4 stories (D.1-D.4) using GREENFIELD pipelines. Each story's V agent reviewed it in isolation — **no cross-story adversarial review has been performed**.

The system replaces 14 Python job classes with YAML workflow definitions. A `WorkflowDefinition` (YAML) is parsed by the loader, validated structurally, instantiated into database rows by the initializer, and parameters are resolved at runtime by the resolver.

### What to review

These files form a pipeline: YAML → Pydantic models → DB rows → resolved parameters.

**Core model files:**
- `core/models/workflow_enums.py` — NodeType, AggregationMode, BackoffStrategy, WorkflowRunStatus (4 values), WorkflowTaskStatus (8 values)
- `core/models/workflow_definition.py` — WorkflowDefinition, TaskNode, ConditionalNode, FanOutNode, FanInNode (discriminated union), RetryPolicy, BranchDef, FanOutTaskDef, ParameterDef, ValidatorDef, FinalizeDef
- `core/models/workflow_run.py` — WorkflowRun Pydantic model with __sql_* DDL metadata
- `core/models/workflow_task.py` — WorkflowTask Pydantic model with __sql_* DDL metadata
- `core/models/workflow_task_dep.py` — WorkflowTaskDep Pydantic model (DAG edges)

**Loader + Registry:**
- `core/workflow_loader.py` — WorkflowLoader.load() — YAML parse → Pydantic validate → 10 structural validations
- `core/workflow_registry.py` — WorkflowRegistry — in-memory cache, loaded at startup

**Initializer:**
- `core/dag_initializer.py` — DAGInitializer.create_run() — converts WorkflowDefinition into WorkflowRun + WorkflowTask rows + WorkflowTaskDep edges atomically. Pure _build_tasks_and_deps function for in-memory construction.

**Parameter Resolver:**
- `core/param_resolver.py` — resolve_task_params (dotted-path + job params merge), resolve_fan_out_params (Jinja2 NativeEnvironment), resolve_dotted_path (JSONB navigation). ParameterResolutionError exception.

**Supporting:**
- `core/errors/workflow_errors.py` — WorkflowValidationError, WorkflowNotFoundError
- `exceptions.py` — ContractViolationError, BusinessLogicError, DatabaseError hierarchy
- `workflows/hello_world.yaml` — minimal test workflow
- `workflows/echo_test.yaml` — parameter passing test workflow (if exists)

### Recommended Omega Split: Split C (Data vs Control)

**Why**: This is a data pipeline (YAML → models → DB → resolved params). Split C separates data integrity concerns (schema correctness, type safety, validation completeness) from flow control concerns (initialization ordering, idempotency, error propagation).

**Alpha — Data Integrity**: Model field types, enum completeness, __sql_* DDL metadata correctness, YAML schema validation coverage, parameter type preservation (Jinja2 NativeEnvironment), dotted-path navigation edge cases, JSONB serialization fidelity.

**Beta — Control Flow**: Initialization atomicity (transaction boundaries), idempotency (SHA256 run_id + UniqueViolation), error propagation (ContractViolationError vs ParameterResolutionError vs WorkflowValidationError), structural validation ordering (what D.1 catches vs what D.3 re-validates), handler sentinel strings (__conditional__, __fan_in__), root node detection correctness.

### Key Architectural Decisions (for reviewer context)

1. **Handler sentinels**: ConditionalNode → `__conditional__`, FanInNode → `__fan_in__`. FanOutNode uses `node.task.handler`. All stored in `WorkflowTask.handler` (NOT NULL).
2. **All node types as WorkflowTask rows**: Including conditional and fan-in nodes that are orchestrator-managed, not worker-executed.
3. **No "result" sentinel in dotted paths**: `"node_name.field"` navigates raw result_data directly (M rejected A's proposal for `"node_name.result.field"`).
4. **Deterministic run_id**: `SHA256(json.dumps({"workflow": name, "parameters": params}, sort_keys=True, default=str))`.
5. **Fan-out child IDs**: `f"{run_id[:12]}-{task_name}-fo{index}"` (decided by ARB P).
6. **Root detection**: Computed from full incoming-edge set including conditional `branch.next` targets (not from `WorkflowDefinition.get_root_nodes()`).
7. **when_clause scope**: `resolve_dotted_path + bool()` only — no Jinja2.

### Known Accepted Risks (do NOT re-flag these)

- D-2 (D.3): Full topological sort cycle detection deferred — empty-roots guard only
- Fan-out expansion at init time is out of scope (D.5 handles it)
- `WorkflowRun` has no `updated_at` column (by design)
- `ParameterResolutionError` on when_clause = "wait" (leave PENDING), not "fail"

### Constitution Reference

The project's architectural rules are in `CLAUDE.md`. Key rules:
- No backward compatibility — fail explicitly
- Models are data, behavior is separate
- Repository pattern for all DB access
- `ContractViolationError` for programming bugs, `BusinessLogicError` for expected failures
