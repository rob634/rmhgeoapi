# COMPETE T3 — DAG Engine Persistence, Leasing & Operations

**Run**: 62
**Date**: 28 MAR 2026
**Pipeline**: COMPETE (Adversarial Code Review)
**Series**: COMPETE DAG Series — Target T3
**Version**: v0.10.9.0
**Split**: C (Data vs Control Flow) + Single-Database Lens
**Files**: 6 (Epoch 5 focus — Epoch 4 bridge code noted but not analyzed)
**Lines**: ~3,936
**Findings**: 14 total — 0 CRITICAL, 0 HIGH actionable, 3 MEDIUM, 11 LOW (after recalibration)
**Fixes Applied**: 3 (all MEDIUM). LOWs left in place.
**Accepted Risks**: 4

---

## EXECUTIVE SUMMARY

The DAG persistence layer is well-engineered. All critical concurrency paths (lease, SKIP LOCKED, CAS guards, expand_fan_out) are correctly implemented. No data corruption risks found in production paths. The highest-priority fixes were adding `awaiting_approval` to the partial index on `workflow_runs.status` (degrades Brain loop query performance), adding a `schedule_id` index, and adding rowcount checks to `complete_workflow_task`/`fail_workflow_task` (silent CAS rejection left workers unaware of janitor reclamation). The scheduler TOCTOU is real but bounded by the single-writer Brain lease.

---

## FIXES APPLIED (28 MAR 2026)

### MEDIUM fixes (3)

| ID | Finding | File(s) Changed | Fix |
|----|---------|-----------------|-----|
| H3/G1 | Partial index excludes `awaiting_approval` | `core/models/workflow_run.py` | Added `awaiting_approval` to partial_where |
| M2 | No index on `schedule_id` | `core/models/workflow_run.py` | Added `idx_workflow_runs_schedule` partial index |
| M2+M3 | `complete_workflow_task` / `fail_workflow_task` silent CAS rejection | `workflow_run_repository.py` | Added rowcount check + warning log |

---

## ACCEPTED RISKS

| Risk | Why Acceptable | Revisit Trigger |
|------|---------------|-----------------|
| Scheduler double-fire TOCTOU (Beta H-1) | Single-writer Brain lease prevents concurrent schedulers. Minute-level request_id provides traceability. Worst case: 1 extra concurrent run. | Multiple DAG Brains or max_concurrent > 1 critical |
| Janitor retry_count off-by-one (Beta H-2) | Lease prevents concurrent janitors. One extra retry is harmless. | Never |
| Inconsistent JSONB casting (Alpha M4) | Both approaches work. Cosmetic inconsistency. | Next cleanup pass |
| holder_id hostname:pid collision (Beta E-2) | TTL-based lease prevents stale holders. Single-Brain model. | Active-active Brain deployment |

---

## LOW FINDINGS (left in place)

| ID | Finding |
|----|---------|
| Alpha H1 | `set_task_parameters` no status guard (safe alternative `set_params_and_promote` already in use) |
| Alpha H2 | `claim_ready_workflow_task` returns Python timestamps (worker doesn't use them for timing) |
| Alpha M1 | `get_predecessor_outputs` dict collision (dead code — method never called) |
| Alpha L1 | `_workflow_task_from_row` .get() defaults mask missing columns |
| Alpha L2 | `_get_stale_query` dead code |
| Alpha L3 | lease_repository dict_row redundancy |
| Beta E-4 | `aggregate_fan_in` no rowcount check (false-positive log) |

---

## ARCHITECTURE WINS

1. **CAS guards everywhere** — every state transition uses WHERE status guards. System is naturally idempotent.
2. **Single-writer Brain with lease** — eliminates entire class of concurrency bugs.
3. **SKIP LOCKED for worker claim** — gold standard PostgreSQL work queue pattern.
4. **Gate operations transactional** — task + run status updated atomically.
5. **Fan-out expansion atomic + idempotent** — single transaction + CAS + UniqueViolation fallback.
6. **Fail-open janitor/scheduler** — each phase/schedule independently caught, failures don't cascade.
7. **In-memory predecessor_outputs** — avoids N+1 queries and dict-key collision bug in dead SQL method.

---

## PIPELINE METADATA

| Agent | Duration | Tokens | Key Contribution |
|-------|----------|--------|------------------|
| Omega | — | — | Split C + Single-Database Lens, 6 files, Epoch 4 scoped out |
| Alpha | ~4.5 min | ~87K | 9 strengths, 7 concerns (3 HIGH, 4 MEDIUM, 3 LOW), 5 assumptions, 7 recommendations |
| Beta | ~3.5 min | ~75K | 12 verified safe, 2 HIGH, 3 MEDIUM, 4 risks, 5 edge cases |
| Gamma+Delta | ~6 min | ~99K | 0 contradictions, 1 agreement, 4 blind spots, 5 top fixes, 4 accepted risks |
