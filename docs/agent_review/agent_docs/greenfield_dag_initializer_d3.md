# GREENFIELD Run: D.3 DAG Initializer

**Date**: 16 MAR 2026
**Pipeline**: GREENFIELD (S → A+C+O → M → B → V)
**Status**: M complete, B pending
**Story**: D.3 — DAG Initializer

---

## Open Questions Resolved

| Question | Resolution | Agent |
|----------|-----------|-------|
| Q1: Handler for non-worker nodes | Sentinels: `__conditional__`, `__fan_in__`. FanOutNode uses `node.task.handler`. Handler stays NOT NULL. | A (confirmed by M) |
| Q2: Conditional nodes as task rows | YES — create as WorkflowTask rows. Needed for dep edges, result storage, branch tracking. Transitions managed by D.5 orchestrator. | A (confirmed by M) |
| Q3: Timestamp in run_id | NO — pure content-addressing. Same workflow+params = same run_id. Resubmission of FAILED runs deferred (D-1). | A (confirmed by M, C flagged risk) |

## Key Design Decisions from M

1. **Two files, not four**: `core/dag_initializer.py` (logic) + `infrastructure/workflow_run_repository.py` (DB). A proposed 4 files; Constraint 10 enforced single-file for logic.
2. **No pre-flight idempotency check**: A's check-then-insert replaced by insert-catch-UniqueViolation pattern (C's E4 TOCTOU race).
3. **Root detection ignores `get_root_nodes()`**: Compute full incoming-edge set including conditional `branch.next` targets (C's A2/CF-4).
4. **Structural validation in initializer**: `depends_on` and `branch.next` references validated even though D.1 should catch them (Constraint 1: fail explicitly).
5. **Empty-roots guard for cycles**: If no root nodes found after edge computation, raise ContractViolationError. Full Kahn's algorithm deferred (D-2).
6. **Conditional edges**: target node depends_on conditional node (not the other way around).
7. **FAILED run resubmission**: Returns existing FAILED run. Caller must inspect status. Retry endpoint deferred (D-1).

## Conflicts Resolved (11)

| # | Conflict | Resolution |
|---|----------|-----------|
| CF-1 | A's 4-file decomposition vs Constraint 10 | Two files: core/ + infrastructure/ |
| CF-2 | Repository in infrastructure/ | Kept per Constraint 5 |
| CF-3 | TOCTOU on idempotency | Insert-then-catch-UniqueViolation |
| CF-4 | Root detection vs conditional next: edges | Compute full incoming-edge set |
| CF-5 | Conditional next: edge direction | Target depends_on conditional |
| CF-6 | FAILED run resubmission | Return existing, caller handles |
| CF-7 | Operator endpoint | Deferred (D-3) |
| CF-8 | depends_on validation | Explicit validation in initializer |
| CF-9 | Cycle detection | Empty-roots guard, full topo sort deferred |
| CF-10 | execute_after on READY tasks | NULL (immediately eligible) |
| CF-11 | task_instance_id uniqueness | DB UNIQUE constraint + deterministic format |

## Deferred Decisions (6)

| # | Decision | Trigger to Revisit |
|---|----------|-------------------|
| D-1 | Retry/reset for FAILED runs | User-facing retry button needed |
| D-2 | Full topological sort cycle detection | Before first production deployment |
| D-3 | GET /api/dbadmin/runs/{run_id} endpoint | First time operator needs to debug a run |
| D-4 | WorkflowTaskDep index | Before orchestrator ships (D.5) |
| D-5 | Fan-out expansion (template → N children) | D.5 orchestrator story |
| D-6 | asset_id/release_id referential integrity | When orchestrator needs to look up assets |

## Risk Register (7)

| # | Risk | L | I | Mitigation |
|---|------|---|---|-----------|
| RK-1 | Schema tables missing at runtime | HIGH | HIGH | Startup health check + docs |
| RK-2 | FAILED run idempotent return confuses caller | MED | MED | Include status in response |
| RK-3 | Duplicate dep edges from overlapping next: + depends_on | LOW | MED | Dedup set in _build_tasks_and_deps |
| RK-4 | Large workflow (100+ nodes) long transaction | LOW | MED | Batch executemany at scale |
| RK-5 | JSON canonicalization produces different forms | LOW | HIGH | sort_keys=True + default=str (Python 3.7+ deterministic) |
| RK-6 | Handler sentinels conflict with real handler names | LOW | HIGH | Startup validation: no __*__ handlers |
| RK-7 | JSONB snapshot exceeds row size | LOW | LOW | Not a concern (<10KB typical) |

## Design Tensions (3)

| # | Tension | Enforced | Future Signal |
|---|---------|----------|--------------|
| DT-1 | A's 4-class decomposition vs Constraint 10 (single file) | Constraint 10 | Revisit when dag_initializer.py > 300 lines |
| DT-2 | A's rich repository inheritance vs lightweight needs | PostgreSQLRepository used | Consider lighter base for DAG repos |
| DT-3 | Pure content-addressed run_id vs operational retry need | Constraint 1 (no backwards compat) | Revisit when retry API built |
