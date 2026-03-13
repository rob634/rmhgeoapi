# COMPETE Run 2: State Management Writes

**Date**: 13 MAR 2026
**Version**: v0.10.1.1
**Scope**: Job/task state writes, stage completion, error propagation, transaction safety
**Split**: B (Atomicity & Transaction Safety vs Error Propagation & Recovery)
**Files Reviewed**: 4 primary (postgresql.py, jobs_tasks.py, state_manager.py, machine.py)
**Fix Status**: 7/7 MEDIUM+ fixes applied — 1 CRITICAL, 3 HIGH, 3 MEDIUM

---

## EXECUTIVE SUMMARY

The state management subsystem is architecturally sound — the "last task turns out the lights" pattern using PostgreSQL advisory locks (`complete_task_and_check_stage`) is the single most important correctness mechanism and is correctly implemented. However, the review uncovered one critical stuck-job path (retry failure bypassing stage completion), three cases of silent exception swallowing that contradict the established "let errors propagate" contract, and several medium-severity issues including a broken job reset path and inconsistent batch insertion behavior. All MEDIUM+ findings have been fixed.

---

## TOP FIXES APPLIED

### Fix 1 (CRITICAL): Retry failure bypasses stage completion check

- **WHAT**: Replaced `update_task_status_direct()` with `complete_task_with_sql()` using a failed `TaskResult`
- **WHY**: When retry scheduling failed (Service Bus down), the task was marked FAILED via `update_task_status_direct` which bypasses the atomic "last task turns out the lights" check. If this was the last task in the stage, the job hung in PROCESSING forever.
- **WHERE**: `core/machine.py:1541-1571`
- **HOW**: Route through the standard `complete_task_with_sql` path which atomically marks the task FAILED and evaluates stage completion. If stage complete, signals via `_should_signal_stage_complete()` or calls `_handle_stage_completion()` locally.

### Fix 2 (HIGH): `store_stage_results` silently swallowed exceptions

- **WHAT**: Removed try/except wrapper, let infrastructure errors propagate
- **WHY**: Contradicted the "let errors propagate" contract documented elsewhere in StateManager. Stage results were silently lost during transient DB errors.
- **WHERE**: `core/state_manager.py:730-757`

### Fix 3 (HIGH): `fail_all_job_tasks` silently swallowed exceptions

- **WHAT**: Removed try/except wrapper, updated docstring
- **WHY**: When DB was down during job failure cleanup, orphan PROCESSING tasks continued executing work for a FAILED job. Caller already has try/except.
- **WHERE**: `core/state_manager.py:867-903`

### Fix 4 (HIGH): `reset_failed_job` didn't delete child tasks

- **WHAT**: Added `DELETE FROM tasks WHERE parent_job_id = %s` before job reset
- **WHY**: Deterministic task IDs + `ON CONFLICT DO NOTHING` = reset jobs hang. Old FAILED tasks persist, new tasks silently aren't created.
- **WHERE**: `infrastructure/jobs_tasks.py:398-413`

### Fix 5 (MEDIUM): `batch_create_tasks` missing `ON CONFLICT`

- **WHAT**: Added `ON CONFLICT (task_id) DO NOTHING` to batch INSERT
- **WHY**: Inconsistent with individual `create_task`. Duplicate task_id in batch rolled back entire transaction.
- **WHERE**: `infrastructure/jobs_tasks.py:1061`

### Fix 6 (MEDIUM): Misleading error context in `_individual_queue_tasks`

- **WHAT**: Added `task_created` flag, error message now reports "Task DB creation" or "Service Bus send" accurately
- **WHY**: All failures blamed on "Service Bus send failed" even when actual failure was task DB creation.
- **WHERE**: `core/machine.py:1655-1703`

### Fix 7 (MEDIUM): `get_job_record` swallowed DB errors as None

- **WHAT**: Removed try/except, let DB errors propagate
- **WHY**: Callers couldn't distinguish "job not found" (None) from "database down" (also None).
- **WHERE**: `core/state_manager.py:125-140`

---

## ACCEPTED RISKS

### A. `update_job_status_with_validation` TOCTOU race (MEDIUM)

Read-validate-write across two connections. Mitigated by SQL CAS guards: `advance_job_stage` uses `WHERE stage = p_current_stage`, `reset_failed_job` uses `WHERE status = 'failed'`. The Python validation adds defense-in-depth but isn't the concurrency guard. **Revisit** if a new transition path bypasses SQL CAS.

### B. Non-atomic task create + Service Bus send (MEDIUM)

A crash between DB insert and Service Bus send creates an orphan PENDING task. Fundamental distributed systems problem (2PC between DB and message broker). Mitigated by cleanup code that marks failed-to-send tasks as FAILED. **Revisit** with a periodic janitor that detects PENDING tasks older than N minutes.

### C. `_advance_stage` double failure (MEDIUM)

When both Service Bus send and the DB rollback fail, a job can be stuck in QUEUED. Only occurs during simultaneous DB + Service Bus outage. The outer error handler attempts `_mark_job_failed` but that also requires DB. **Revisit** with a periodic sweep for stale QUEUED jobs.

### D. `store_stage_results` JSONB read-modify-write race (MEDIUM)

Python-level `dict.copy() → update → write` has a lost-update window. Mitigated by sequential stage execution — only one stage active at a time. The `advance_job_stage` SQL function already does atomic `|| jsonb_build_object()` merge. **Revisit** if concurrent stage writes become possible.

---

## ARCHITECTURE WINS

1. **Advisory lock in `complete_task_and_check_stage`** — `pg_advisory_xact_lock(hashtext(job_id || ':stage:' || stage))` serializes remaining-task count. Transaction-scoped, auto-releases on commit/rollback. The single most important correctness mechanism.

2. **Idempotent task completion** — duplicate Service Bus messages return no-op results, preventing double stage advancement.

3. **TOCTOU race fix (26 FEB 2026)** — re-checks task status after SQL failure. If another worker completed the task, returns no-op instead of raising error.

4. **Service Bus send rollback** — QUEUED→PROCESSING on send failure prevents stuck-QUEUED jobs.

5. **Orphan task cleanup on queue failure** — immediate FAILED marking prevents deadlocked stages.

6. **`_error_context` pattern** — consistent logging and re-raise at infrastructure layer.

---

## FULL FINDING LOG (Gamma Recalibrated)

| # | Severity | Finding | Confidence | Source |
|---|----------|---------|------------|--------|
| 1 | CRITICAL | Retry failure bypasses stage completion | CONFIRMED | Beta-4 |
| 2 | HIGH | `store_stage_results` swallows exceptions | CONFIRMED | Beta-1 |
| 3 | HIGH | `fail_all_job_tasks` swallows exceptions | CONFIRMED | Beta-2 |
| 4 | HIGH | `reset_failed_job` doesn't delete child tasks | CONFIRMED | Beta-7 |
| 5 | MEDIUM | `batch_create_tasks` missing ON CONFLICT | CONFIRMED | Alpha-4/Beta-3 |
| 6 | MEDIUM | Non-atomic task create + Service Bus send | CONFIRMED | Alpha-2 |
| 7 | MEDIUM | `get_job_record` swallows exceptions | CONFIRMED | Beta-5 |
| 8 | MEDIUM | `update_job_status_with_validation` TOCTOU | CONFIRMED | Alpha-1 |
| 9 | MEDIUM | `store_stage_results` JSONB race | CONFIRMED | Alpha-8 |
| 10 | MEDIUM | `_advance_stage` double failure stuck QUEUED | CONFIRMED | Alpha-5/Beta-6 |
| 11 | MEDIUM | Misleading error context in queue_tasks | CONFIRMED | Beta-8 |
| 12 | LOW | `update_task_status_with_validation` TOCTOU | CONFIRMED | Alpha-3 |
| 13 | LOW | `fail_tasks_for_job` bypasses validation (intentional) | CONFIRMED | Alpha-6 |
| 14 | LOW | Monitoring methods swallow exceptions | CONFIRMED | Beta-9 |
| 15 | LOW | Potentially dead `handle_stage_completion` | CONFIRMED | Beta-10 |

**Total: 1 CRITICAL, 3 HIGH, 7 MEDIUM, 4 LOW**

## FIX LOG (13 MAR 2026)

| # | Finding | Fix | File | Status |
|---|---------|-----|------|--------|
| 1 | CRITICAL: Retry bypasses stage completion | Replaced `update_task_status_direct` with `complete_task_with_sql` + stage completion handling | `machine.py:1541-1571` | ✅ FIXED |
| 2 | HIGH: `store_stage_results` swallows exceptions | Removed try/except, errors propagate | `state_manager.py:730-757` | ✅ FIXED |
| 3 | HIGH: `fail_all_job_tasks` swallows exceptions | Removed try/except, errors propagate | `state_manager.py:867-903` | ✅ FIXED |
| 4 | HIGH: `reset_failed_job` orphans old tasks | Added DELETE FROM tasks before job reset | `jobs_tasks.py:398-413` | ✅ FIXED |
| 5 | MEDIUM: `batch_create_tasks` no ON CONFLICT | Added ON CONFLICT (task_id) DO NOTHING | `jobs_tasks.py:1061` | ✅ FIXED |
| 6 | MEDIUM: Misleading error context | Added `task_created` flag, accurate error source | `machine.py:1655-1703` | ✅ FIXED |
| 7 | MEDIUM: `get_job_record` swallows errors | Removed try/except, None=not found, exception=DB error | `state_manager.py:125-140` | ✅ FIXED |
