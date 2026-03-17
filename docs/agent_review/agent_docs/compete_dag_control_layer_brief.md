# COMPETE Brief: DAG Control Layer (D.5-D.6)

**Pipeline**: COMPETE (Adversarial Review)
**Date**: 16 MAR 2026
**Scope**: DAG orchestrator, graph traversal, transition/fan engines, worker dual-poll
**Run Number**: Assign next sequential in AGENT_RUNS.md

---

## Context for Omega

This is the **runtime control layer** of the DAG workflow orchestration system (V10 Migration). It was built across 2 stories (D.5 via 3 GREENFIELD runs, D.6 direct implementation). Each GREENFIELD run's V agent reviewed individual files — **no cross-file adversarial review has been performed on the integrated system**.

The control layer has three concerns:
1. **Graph operations** (pure functions, no DB) — adjacency, reachability, terminal detection
2. **Engine logic** (reads DB snapshots, writes state transitions via repo) — task promotion, conditional routing, fan-out expansion, fan-in aggregation
3. **Orchestrator shell** (poll loop, advisory lock, engine dispatch) — drives everything

### What to review

**Graph utilities (pure, no DB):**
- `core/dag_graph_utils.py` — TaskSummary (frozen dataclass), build_adjacency (instance_id→task_name translation), get_descendants (BFS downstream), all_predecessors_terminal (readiness gate), is_run_terminal (run completion check). _TERMINAL_TASK_STATUSES frozenset.

**Transition engine (merged D.5b+D.5d):**
- `core/dag_transition_engine.py` — evaluate_transitions(): promotes ALL PENDING tasks to READY when deps are met (all node types — including conditional, fan-out, fan-in). When-clause evaluation (resolve_dotted_path + bool(), ParameterResolutionError = wait). Parameter resolution for TaskNodes before promotion. Skip propagation via get_descendants.

**Fan engine (conditional + fan-out + fan-in):**
- `core/dag_fan_engine.py` — evaluate_conditionals(): processes READY __conditional__ tasks (branch evaluation, 14 operators, skip untaken branches + descendants). expand_fan_outs(): READY FanOutNode → N child tasks. aggregate_fan_ins(): PENDING FanInNode → aggregate when all children terminal. _eval_branch_condition (operator parser).

**Orchestrator:**
- `core/dag_orchestrator.py` — DAGOrchestrator.run(run_id): advisory lock (dedicated non-pooled connection with TCP keepalives), poll loop (max_cycles, cycle_interval), fixed dispatch order (transitions → conditionals → fan-out → fan-in), full DB reload each cycle, terminal detection, 3-consecutive-error self-FAIL, shutdown_event support. OrchestratorResult dataclass.

**Worker dual-poll (D.6):**
- `docker_service.py` — Modified _run_loop for dual-poll (legacy tasks first, then DAG workflow tasks). _claim_next_workflow_task, _process_workflow_task (direct handler execution bypassing CoreMachine), _release_workflow_task.

**Repository (shared by all above):**
- `infrastructure/workflow_run_repository.py` — 13+ methods: insert_run_atomic, get_by_run_id, get_tasks_for_run (→TaskSummary), get_deps_for_run, get_predecessor_outputs, promote_task (CAS), skip_task, fail_task, expand_fan_out (atomic transaction), aggregate_fan_in, update_run_status (transition guard), set_task_parameters, claim_ready_workflow_task (SKIP LOCKED), complete_workflow_task, fail_workflow_task, release_workflow_task.

### Recommended Omega Split: Split A (Design vs Runtime)

**Why**: This is a runtime orchestration system where the most dangerous bugs are in concurrent state transitions, race conditions between orchestrator and workers, and the interaction between the fixed dispatch order and the one-tick-lag snapshot model. Split A separates architectural review (composition, contracts, layering) from runtime correctness (races, state machines, failure recovery).

**Alpha — Architecture and Design:**
- Component boundaries (graph_utils vs transition_engine vs fan_engine vs orchestrator vs repository — are they cut correctly?)
- Contract consistency (do engines match the repo method signatures? do result DTOs carry the right fields?)
- Dependency direction (does the orchestrator depend on engines, not vice versa? does graph_utils depend on nothing?)
- Handler sentinel contract (__conditional__, __fan_in__ — consistently used across all files?)
- task_name vs task_instance_id usage (graph layer uses names, DB layer uses IDs — is the translation correct everywhere?)
- Adjacency map direction convention (upstream-oriented — consistent across all callers?)
- Duplicate code: _build_adjacency_from_tasks in fan_engine vs build_adjacency in graph_utils

**Beta — Correctness and Runtime Behavior:**
- **State machine completeness**: Are all WorkflowTaskStatus transitions valid? Can a task reach an unreachable state?
- **Race conditions**: Worker claims READY task while orchestrator is about to skip it (conditional). Worker completes task while orchestrator is reading stale snapshot. Two orchestrators for different run_ids share the same pool.
- **One-tick-lag correctness**: predecessor_outputs built once per cycle — is it safe for all 4 engines to use the same stale snapshot?
- **Advisory lock lifecycle**: Connection opened before loop, closed in finally. What if the connection silently drops mid-run?
- **Fan-out atomicity**: Template→EXPANDED + INSERT children + INSERT deps in one transaction. What if UniqueViolation fires mid-batch?
- **Fan-in trigger**: aggregate_fan_ins checks all children terminal — but children were created in a previous tick. Can the children list be stale?
- **Idempotency**: Every status transition has a CAS guard (WHERE status = from_status). Are there any paths that bypass the guard?
- **Error escalation**: 3 consecutive errors → self-FAIL. Does the counter reset correctly? Does ContractViolationError bypass the counter?
- **Worker dual-poll**: Legacy-first priority. What if the DAG claim fails with a DB error — does it crash the legacy poll loop?
- **Shutdown behavior**: shutdown_event checked at cycle top. What about mid-engine shutdown?

### Key Architectural Decisions (for reviewer context)

**From ARB P (binding decisions — do not re-litigate):**
1. Advisory lock on DEDICATED non-pooled connection (not from pool)
2. Fixed dispatch order: transitions → conditionals → fan-out → fan-in
3. One transaction per engine call (separate commits, workers see intermediate state)
4. Full DB reload each cycle (no carried state between cycles)
5. workflow_def from run.definition JSONB snapshot (not registry)
6. When-clause: resolve_dotted_path + bool() — ParameterResolutionError = wait, False = skip
7. Fan-out children created as READY (not PENDING — no extra promotion needed)
8. FAILED deps block regardless of optional flag (optional only tolerates SKIPPED)
9. max_cycles_exhausted → run stays RUNNING (Guardian handles, deferred to D.7)
10. evaluate_transitions promotes ALL node types (conditionals, fan-outs, fan-ins too)

### Known Accepted Risks (do NOT re-flag these)

- One-tick lag between engine writes and predecessor_outputs (by design)
- max_cycles_exhausted leaves run RUNNING (Guardian deferred)
- No stale RUNNING task recovery yet (D.7 janitor deferred)
- aggregate_fan_in has no CAS guard (advisory lock prevents concurrent calls)
- Fan-out child name collision with manually-named nodes (edge case accepted)
- ManagedIdentityAuth() instantiated per run() call (acceptable frequency)

### Constitution Reference

Same as Data Layer brief — see `CLAUDE.md` for project rules.

### Files to Read (in this order for best context)

1. `core/dag_graph_utils.py` — foundation (pure functions)
2. `core/dag_transition_engine.py` — promotion logic
3. `core/dag_fan_engine.py` — conditional + fan-out + fan-in
4. `core/dag_orchestrator.py` — poll loop shell
5. `infrastructure/workflow_run_repository.py` — all DB methods
6. `docker_service.py` — worker dual-poll (focus on _run_loop, _claim_next_workflow_task, _process_workflow_task)
