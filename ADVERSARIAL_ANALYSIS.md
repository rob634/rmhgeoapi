# CoreMachine Adversarial Code Review

**Date**: 26 FEB 2026
**Subsystem**: Job Pipeline / CoreMachine Orchestration
**Method**: Adversarial multi-agent pipeline (Omega → Alpha + Beta parallel → Gamma → Delta)

---

## Executive Summary

The CoreMachine orchestration engine is architecturally sound — the composition pattern, advisory-lock-based "last task turns out the lights" detection, and explicit registry injection are well-designed. The biggest systemic risk is **non-atomic task creation + queueing**: a Service Bus send failure after the DB insert creates orphan PENDING tasks that permanently block stage completion with no automated cleanup path. Secondary risks cluster around the failure path: all 13 `_mark_job_failed` call sites omit `job_type`, causing the platform callback to always receive `'unknown'` and leaving `release.processing_status` stuck on failure.

---

## Pipeline Structure

| Agent | Role | Scope |
|-------|------|-------|
| **Omega** | Orchestrator | Split review into asymmetric architecture vs correctness lenses |
| **Alpha** | Architecture Reviewer | Design patterns, contracts, coupling, composition, extensibility |
| **Beta** | Correctness Reviewer | Race conditions, error recovery, atomicity, data integrity |
| **Gamma** | Adversarial Contradiction Finder | Finds where Alpha and Beta disagree, agree, or both missed something |
| **Delta** | Final Arbiter | Synthesizes into prioritized, actionable fixes |

---

## Files Reviewed (~25 files)

### Core Orchestration
- `core/machine.py` — CoreMachine universal orchestrator (~700 lines)
- `core/state_manager.py` — StateManager with advisory locks
- `core/logic/transitions.py` — State transition rules
- `core/error_handler.py` — Centralized error handling
- `core/fan_in.py` — Fan-in database reference pattern
- `core/models/enums.py` — Status enumerations
- `core/models/results.py` — Result models
- `core/schema/sql_generator.py` — PostgreSQL function definitions

### Job Definitions
- `jobs/base.py` — JobBase abstract class (6-method contract)
- `jobs/mixins.py` — JobBaseMixin (eliminates 77% boilerplate)
- `jobs/__init__.py` — Explicit job registry with import-time validation

### Infrastructure
- `infrastructure/postgresql.py` — PostgreSQL repository implementation
- `infrastructure/interface_repository.py` — Repository interfaces
- `infrastructure/jobs_tasks.py` — Job/Task repository extensions

### Triggers
- `triggers/service_bus/job_handler.py` — Job queue trigger
- `triggers/service_bus/task_handler.py` — Task queue trigger
- `services/__init__.py` — Handler registry

---

## Top 5 Fixes (Prioritized)

### Fix 1: CRITICAL — Orphan PENDING Task Cleanup

**What**: `_individual_queue_tasks()` creates DB record then sends Service Bus message. If send fails, orphan PENDING tasks block stage completion forever.

**Why**: The per-task `except` at `machine.py:1619` increments `tasks_failed` but does NOT clean up the DB record. Method returns `'partial'` status and the caller continues. Orphan PENDING tasks are never picked up, and the stage can never complete because `complete_task_and_check_stage` counts tasks `NOT IN ('completed', 'failed')`. Job hangs forever.

**Where**: `core/machine.py` lines 1585-1637 (`_individual_queue_tasks`)

**How**:
1. In the per-task `except` block (line 1619), mark the already-created task as FAILED: `self.repos['task_repo'].update_task_status_direct(task_def.task_id, TaskStatus.FAILED, error_details=str(e))`
2. In the caller (`process_job_message`), check if `tasks_queued == 0` after partial failure and fail the job immediately

**Effort**: S (add ~5 lines)
**Risk of Fix**: Low — task record already exists, updating to FAILED is safe

---

### Fix 2: HIGH — Pass job_type to _mark_job_failed

**What**: All 13 call sites omit `job_type` parameter. Platform callback always receives `'unknown'`.

**Why**: `_mark_job_failed` passes `job_type or 'unknown'` to `on_job_complete()` (line 2221). The callback uses `job_type` to update `release.processing_status`. With `'unknown'`, release status remains stuck at `'processing'` for every job failure.

**Where**: `core/machine.py` — all 13 call sites at lines 433, 573, 601, 606, 641, 732, 864, 899, 1192, 1252, 1296, 1383, 1527

**How**: Pass the available `job_type` context at every call site:
- In `process_job_message`: `self._mark_job_failed(job_id, error_msg, job_type=job_message.job_type)`
- In `process_task_message`: `self._mark_job_failed(job_id, error_msg, job_type=task_message.job_type)`

**Effort**: S (mechanical find-and-replace, no logic changes)
**Risk of Fix**: Near zero

**Note**: Both Alpha and Beta independently found this bug from different angles — highest-confidence finding.

---

### Fix 3: HIGH — Fix TOCTOU Race in complete_task_with_sql

**What**: Python-level status check and SQL-level `UPDATE WHERE status = 'processing'` are not atomic. Two duplicate messages can both pass the Python guard.

**Why**: Both duplicates see `task.status == PROCESSING`. First `UPDATE` succeeds. Second returns `task_updated=False`. Line 633 raises `RuntimeError("SQL function failed to update task")`. This propagates to `process_task_message` line 1244, which calls `_mark_job_failed` — potentially failing a job that already completed successfully.

**Where**: `core/state_manager.py` lines 595-634 (`complete_task_with_sql`)

**How**: When `task_updated=False`, re-check task status before raising:
```python
if not stage_completion.task_updated:
    # Re-check: task may have been completed by another message
    current = self.repos['task_repo'].get_task(task_id)
    if current and current.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        return TaskCompletionResult(task_updated=False, stage_complete=False, ...)
    raise RuntimeError(f"SQL function failed to update task {task_id}")
```

**Effort**: S (5-line change in one method)
**Risk of Fix**: Low — only changes behavior on the `task_updated=False` error path

---

### Fix 4: MEDIUM — Move fail_all_job_tasks to TaskRepository

**What**: `StateManager.fail_all_job_tasks()` bypasses repository pattern with raw SQL and hardcoded `"app"` schema.

**Why**: Accesses `task_repo._get_connection()` (private method), hardcodes schema name (line 873), and constructs SQL directly. If schema name changes, this function silently targets wrong tables. Only method in StateManager that writes raw SQL.

**Where**: `core/state_manager.py` lines 838-877

**How**: Add `fail_tasks_for_job(job_id, error_msg)` method to `TaskRepository` using `self.schema_name`. Replace raw SQL in StateManager with: `self.repos['task_repo'].fail_tasks_for_job(job_id, error_msg)`

**Effort**: M (new method on TaskRepository, update StateManager)
**Risk of Fix**: Low-medium — must test with concurrent task completions

---

### Fix 5: MEDIUM — Share Repos with _confirm_task_queued

**What**: `task_handler.py` line 173 creates fresh repository bundle per task message.

**Why**: Each call creates new DB connections. Under load, multiplies connection count. Combined with CoreMachine and StateManager repos, up to 4 independent connection sources per task.

**Where**: `triggers/service_bus/task_handler.py` line 173

**How**: Pass `core_machine.repos['task_repo']` into `_confirm_task_queued` instead of creating new repos.

**Effort**: S (modify function signature and one call site)
**Risk of Fix**: Low

---

## Full Findings (Gamma's Recalibrated Severity)

| Rank | ID | Severity | Finding |
|------|-----|----------|---------|
| 1 | Beta BUG-2 + Gamma BLIND-6 | **CRITICAL** | Non-atomic task creation + queueing; orphan PENDING tasks hang jobs permanently |
| 2 | Beta BUG-1 | **HIGH** | TOCTOU race in idempotency check can mark COMPLETED job as FAILED |
| 3 | Alpha C3 + Beta EDGE-3 | **HIGH** | _mark_job_failed missing job_type in all 13 call sites |
| 4 | Gamma BLIND-2 | **HIGH** | Exception swallowing prevents dead-lettering; double-failure = permanently stuck job |
| 5 | Gamma BLIND-3 | **HIGH** | Stage advancement PROCESSING→QUEUED→PROCESSING rollback race |
| 6 | Alpha C1 | **MEDIUM** | Duplicate repository bundles in CoreMachine and StateManager |
| 7 | Beta BUG-3 + Gamma CONTRADICTION-1 | **MEDIUM** | _confirm_task_queued and fan_in.py create standalone repository instances |
| 8 | Alpha C2 + Beta EDGE-4 | **MEDIUM** | StateManager dual role; fail_all_job_tasks bypasses repository with hardcoded schema |
| 9 | Alpha C4 | **MEDIUM** | Transition rules duplicated between transitions.py and model methods |
| 10 | Beta BUG-5 | **MEDIUM** | Retry creates duplicate messages without deduplication IDs |
| 11 | Beta RISK-1 | **MEDIUM** | Service Bus lock expiration during long tasks causes duplicate handler execution |
| 12 | Alpha C7 | **MEDIUM** | process_task_message() is 812 lines with deep nesting |
| 13 | Beta BUG-4 | **LOW** | Failed tasks don't trigger stage completion check (blocks COMPLETED_WITH_ERRORS) |
| 14 | Gamma BLIND-1 | **LOW** | SQL function body uses .format() for schema (latent injection vector) |
| 15 | Alpha C5 | **LOW** | StateManager.handle_stage_completion() signature mismatch with interface |
| 16 | Alpha C6 | **LOW** | JobBase @staticmethod vs JobBaseMixin @classmethod tension |
| 17 | Beta RISK-2 | **LOW** | Managed identity token caching expires after ~1 hour in Docker workers |
| 18 | Beta RISK-3 + RISK-4 | **LOW** | store_stage_results() and monitoring methods swallow exceptions |
| 19 | Alpha C8 | **LOW** | Event recording has 10+ identical try/except blocks |
| 20 | Gamma BLIND-4 | **LOW** | total_stages always None in completion logs |
| 21 | Gamma BLIND-5 | **LOW** | Truncated lock token in logs (minimal security exposure) |
| 22 | Alpha C9 | **LOW** | fan_in.py creates its own repository, bypassing factory |
| 23-25 | Beta EDGE-1,2,5 | **LOW** | Edge cases: QUEUED status race, negative stage, second handler continues |

---

## Accepted Risks

**Exception swallowing prevents dead-lettering (Gamma BLIND-2)**: Both `job_handler.py` and `task_handler.py` catch all exceptions and return dicts instead of re-raising. This is intentional — re-raising causes automatic redelivery which can create infinite retry loops for non-transient errors. The janitor process detects stuck jobs by timeout. The risk (if `mark_job_failed()` also fails, job is stuck) is real but the alternative (uncontrolled retries) is worse.

**Stage advancement rollback race (Gamma BLIND-3)**: The PROCESSING→QUEUED→PROCESSING dance has a theoretical double-failure mode (send fails AND rollback fails). The C1.6 fix (24 FEB 2026) already handles the primary case. The double-failure requires simultaneous Service Bus and PostgreSQL outages. Logged with checkpoint `STAGE_ADVANCE_ROLLBACK_FAILED`. Janitor covers this.

**Duplicated transition rules (Alpha C4)**: `transitions.py` and `JobRecord.can_transition_to()` both define rules. This is defense-in-depth. The DB enforces authoritative transitions. Low divergence risk.

**812-line process_task_message() (Alpha C7)**: Battle-tested. Refactor in a future iteration when orchestration logic stabilizes. The well-labeled sections and step numbering mitigate the readability concern.

**Retry message deduplication (Beta BUG-5)**: Service Bus configuration concern (`RequiresDuplicateDetection` on queue), not a code bug. The idempotency handling in `complete_task_with_sql` (once Fix #3 is applied) correctly handles duplicate processing.

---

## Architecture Wins (Preserve These)

**Advisory-lock stage completion**: The `complete_task_and_check_stage` PostgreSQL function uses `pg_advisory_xact_lock` keyed on `job_id:stage` to serialize the final count without row-level locks. Correct approach for "last task turns out the lights."

**Composition + explicit registry injection**: CoreMachine receives all dependencies via constructor. `ALL_JOBS` and `ALL_HANDLERS` dicts are validated at import time with `validate_job_registry()` and `validate_task_routing_coverage()`. Fail-fast pattern.

**RETRYABLE vs PERMANENT exception categorization**: Module-level tuples (lines 97-114) with corresponding handler branches make retry behavior predictable. Transient failures retry; permanent failures fail fast.

**Checkpoint-based observability**: Every significant state transition logged with structured `extra` dicts. Application Insights queries are straightforward (e.g., `customDimensions.checkpoint == 'STAGE_ADVANCE_SEND_FAILED_ROLLBACK'`).

**JobBase + JobBaseMixin split**: Template Method pattern via mixin — ABC defines contract, mixin provides 4/6 default implementations. 77% boilerplate reduction per job.

---

## Gamma's Key Contradictions

### Alpha said "composition well-executed" — Beta found composition leaking
Alpha S1 praised dependency injection. Beta BUG-3 found `_confirm_task_queued()` creates independent repos outside the injected graph. Alpha C9 found `fan_in.py` does the same. The *architecture* calls for composition; the *implementation* has bypass paths.

### Beta "verified safe" advisory locks — Gamma found TOCTOU gap
The SQL function itself IS correctly implemented. But the Python-layer idempotency check at `state_manager.py:554` has a time-of-check-to-time-of-use gap that the SQL function's `task_updated=False` exposes. Beta was right about the SQL; wrong about the full path being safe.

### Alpha praised "transition rules cleanly separated" — then contradicted itself
S4 praised the separation into pure functions. C4 complained about duplication with `JobRecord.can_transition_to()`. Both are true simultaneously.

---

## Methodology Notes

This review used an adversarial multi-agent pipeline adapted from `adversarial.py` in this repo. Instead of building code from asymmetric specs, we reviewed existing code from asymmetric lenses:

- **Information asymmetry**: Alpha saw only architecture concerns; Beta saw only correctness concerns. Neither could confirm whether a "well-designed" pattern was also "correctly implemented" or vice versa.
- **Gamma's value**: Found 6 blind spots neither reviewer caught, including the most critical finding (orphan PENDING tasks). Also identified where reviewers contradicted each other or themselves.
- **Execution**: All agents ran as Claude Code subagents within a single conversation. No API key required.
