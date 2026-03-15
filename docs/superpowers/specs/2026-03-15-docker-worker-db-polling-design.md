# Docker Worker DB-Polling Migration

**Created**: 15 MAR 2026
**Status**: SPEC
**Version**: v0.10.3.0 (target)
**Parent**: V10_MIGRATION.md (DAG orchestrator design)
**Scope**: Replace Service Bus `container-tasks` queue with PostgreSQL SKIP LOCKED polling

---

## Summary

Replace the Docker worker's Service Bus polling loop with direct PostgreSQL `SELECT FOR UPDATE SKIP LOCKED` task claiming. The Docker worker already has a polling loop (`BackgroundQueueWorker._run_loop()`), already creates tasks in PostgreSQL before sending SB messages, and already routes ALL tasks to the Docker worker. The SB message is a redundant notification — the task already exists in the database.

This is Phase 1 of the V10 DAG migration. No changes to B2B contract, handler signatures, stage completion, or job submission.

---

## Motivation

| Problem | Impact |
|---------|--------|
| SB message is redundant — task already in DB | Unnecessary infrastructure dependency |
| Non-atomic DB insert + SB send (Risk G in V10_DECISIONS) | Orphan PENDING tasks block stage completion |
| Double infrastructure failure during stage advance (Risk H) | Job permanently stuck in QUEUED |
| AutoLockRenewer 2-hour lock for long GDAL jobs | Lock expiry bugs, AMQP complexity |
| AMQP connection warmup bugs | Transient failures on cold start |
| DLQ monitoring overhead | Separate failure path to manage |

All eliminated by making PostgreSQL the sole coordination mechanism.

---

## Design

### 1. TaskStatus Enum — DAG-Standard Lifecycle

**File**: `core/models/enums.py`

Replace current 8-value enum with 8 DAG-standard values:

```python
class TaskStatus(Enum):
    """
    DAG-standard task lifecycle states.

    State machine (15 MAR 2026 — DB-polling migration):

        PENDING ──→ READY ──→ PROCESSING ──→ COMPLETED
            │                      │
            ↓                      ↓
          SKIPPED               FAILED ──→ PENDING_RETRY ──→ READY
                                                              (retry loop)
        CANCELLED (from any non-terminal state)

    Alignment with standard DAG executors:
        PENDING       = Airflow 'scheduled', Prefect 'Pending'
        READY         = Airflow 'queued', Prefect 'Scheduled'
        PROCESSING    = Airflow 'running', Prefect 'Running'
        COMPLETED     = Airflow 'success', Prefect 'Completed'
        FAILED        = universal
        PENDING_RETRY = Airflow 'up_for_retry'
        SKIPPED       = Airflow 'skipped'
        CANCELLED     = universal
    """
    PENDING = "pending"            # Created, dependencies not yet satisfied
    READY = "ready"                # All deps met, available for worker SKIP LOCKED
    PROCESSING = "processing"      # Claimed by worker, executing
    COMPLETED = "completed"        # Handler succeeded
    FAILED = "failed"              # Handler error
    PENDING_RETRY = "pending_retry"  # Failed, scheduled for retry with backoff
    SKIPPED = "skipped"            # when: condition false or upstream skip
    CANCELLED = "cancelled"        # Externally cancelled
```

**Removed values:**
| Value | Reason |
|-------|--------|
| `QUEUED` | Replaced by `READY` — no implied external queue |
| `RETRYING` | Redundant with `PENDING_RETRY` — one retry state is enough |

**Added values:**
| Value | Reason |
|-------|--------|
| `READY` | DAG-standard "available for pickup" — semantically distinct from PENDING |
| `SKIPPED` | DAG-standard "when: condition false" — needed for V11 YAML workflows |

**Semantic change:**
| Value | Old meaning | New meaning |
|-------|-------------|-------------|
| `PENDING` | "SB message sent, awaiting trigger confirmation" | "Created, dependencies not yet satisfied" |

### 2. Transition Rules

**File**: `core/logic/transitions.py`

```python
TASK_TRANSITIONS = {
    TaskStatus.PENDING:       [TaskStatus.READY, TaskStatus.SKIPPED, TaskStatus.CANCELLED],
    TaskStatus.READY:         [TaskStatus.PROCESSING, TaskStatus.CANCELLED],
    TaskStatus.PROCESSING:    [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.PENDING],
    TaskStatus.FAILED:        [TaskStatus.PENDING_RETRY, TaskStatus.CANCELLED],
    TaskStatus.PENDING_RETRY: [TaskStatus.READY, TaskStatus.CANCELLED],
    TaskStatus.COMPLETED:     [],  # Terminal
    TaskStatus.SKIPPED:       [],  # Terminal
    TaskStatus.CANCELLED:     [],  # Terminal
}
```

Key changes from current:
- `PENDING → READY` replaces `PENDING → QUEUED`
- `PENDING → SKIPPED` added for when-clause evaluation
- `PENDING_RETRY → READY` replaces `PENDING_RETRY → PROCESSING` (worker must re-claim via SKIP LOCKED)
- `PROCESSING → PENDING` kept for janitor reset of stuck tasks
- `FAILED → PENDING_RETRY` (not `FAILED → RETRYING → PROCESSING`) — single retry state

**Active states** (non-terminal): `[PENDING, READY, PROCESSING, PENDING_RETRY]`

**Terminal states** (stage completion): `[COMPLETED, FAILED, SKIPPED, CANCELLED]`

**Settled states** (will never change): `[COMPLETED, SKIPPED, CANCELLED]`

Note: `FAILED` is terminal for stage completion (counts as "done") but allows transition to `PENDING_RETRY` for retry. See section 8d for the `terminal` vs `settled` distinction and helper functions.

**Claimable states** (worker SKIP LOCKED query): `[READY, PENDING_RETRY]` — both with `execute_after` check. See section 8b for details.

### 3. TaskRecord Model Changes

**File**: `core/models/task.py`

```python
class TaskRecord(TaskData):
    # Status — default changes from PENDING to READY
    # For Phase 1 (CoreMachine stages), tasks are immediately available.
    # For V11 (DAG), orchestrator creates as PENDING, promotes to READY.
    status: TaskStatus = Field(default=TaskStatus.READY, ...)

    # REMOVE: target_queue — no queues exist
    # target_queue: Optional[str]  ← DELETE

    # ADD: Worker identity for diagnostics and stale-task detection
    claimed_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Worker identity (hostname:pid) that claimed this task"
    )

    # ADD: Retry backoff — workers skip tasks where execute_after > NOW()
    execute_after: Optional[datetime] = Field(
        default=None,
        description="Earliest time this task can be claimed (retry backoff)"
    )

    # KEEP: executed_by_app — still useful for multi-instance diagnostics
    # KEEP: All checkpoint fields — Docker resume unchanged
    # KEEP: All other fields
```

**Transition method update** — `can_transition_to()` must match new transition table.

### 4. TaskQueueMessage — Bridge Pattern

**File**: `core/schema/queue.py`

`TaskQueueMessage` stays unchanged for now. It's the contract between `BackgroundQueueWorker` and `CoreMachine.process_task_message()`. Rather than changing that interface (which touches Function App triggers too), we add a factory method:

```python
class TaskQueueMessage(TaskData):
    # ... existing fields unchanged ...

    @classmethod
    def from_task_record(cls, record: TaskRecord) -> 'TaskQueueMessage':
        """
        Construct a TaskQueueMessage from a database TaskRecord.

        Used by DB-polling workers to produce the same message contract
        that CoreMachine.process_task_message() expects.
        """
        return cls(
            task_id=record.task_id,
            parent_job_id=record.parent_job_id,
            job_type=record.job_type,
            task_type=record.task_type,
            stage=record.stage,
            task_index=record.task_index,
            parameters=record.parameters,
            retry_count=record.retry_count,
            parent_task_id=None,
            timestamp=record.created_at,
        )
```

This means `CoreMachine.process_task_message()` signature is **unchanged**. Every handler is **unchanged**.

### 5. SQL Schema Changes

**PostgreSQL enum** (`app.task_status`):

```sql
DROP TYPE IF EXISTS app.task_status CASCADE;
CREATE TYPE app.task_status AS ENUM (
    'pending', 'ready', 'processing', 'completed',
    'failed', 'pending_retry', 'skipped', 'cancelled'
);
```

**Tasks table changes:**

```sql
-- Remove target_queue column
-- Add claimed_by and execute_after columns

ALTER TABLE app.tasks
    DROP COLUMN IF EXISTS target_queue,
    ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(200),
    ADD COLUMN IF NOT EXISTS execute_after TIMESTAMPTZ;
```

Since we rebuild eagerly, these are expressed in the model and applied via `action=rebuild`.

**New partial index for worker polling:**

```sql
CREATE INDEX idx_tasks_claimable
ON app.tasks (created_at)
WHERE status IN ('ready', 'pending_retry')
  AND (execute_after IS NULL OR execute_after < NOW());
```

This is a partial index — only indexes claimable tasks (READY + PENDING_RETRY with elapsed backoff), stays tiny even with millions of historical rows.

### 6. CoreMachine Send-Side Changes

**File**: `core/machine.py`

`_individual_queue_tasks()` currently does:
1. `INSERT task (status=PENDING)`
2. `service_bus.send_message(queue_name, message)`
3. `record_task_event(TASK_QUEUED)`

Becomes:
1. `INSERT task (status=READY)`
2. ~~service_bus.send_message~~ **DELETED**
3. `record_task_event(TASK_QUEUED)` — event name kept for backward compat in logs

`_task_definition_to_record()`:
- Remove `target_queue` parameter
- Set `status=TaskStatus.READY` (not PENDING)

`_task_definition_to_message()`:
- **DELETE entirely** — no longer needed on send side

`_get_queue_for_task()`:
- **DELETE entirely** — no queue routing needed

### 7. BackgroundQueueWorker — Poll PostgreSQL

**File**: `docker_service.py`

Replace the SB polling loop with DB polling. The structure is identical — `while not stop_event: claim → process → repeat`.

#### 7a. Remove SB Dependencies

| Remove | Reason |
|--------|--------|
| `_get_sb_client()` | No SB client needed |
| `AutoLockRenewer` setup | No message locks — DB row lock is implicit |
| `receiver.complete_message()` | Task status updated in DB by CoreMachine |
| `receiver.abandon_message()` | On interrupt: task stays PROCESSING, janitor reclaims |
| `receiver.dead_letter_message()` | On failure: task marked FAILED in DB by CoreMachine |
| `ServiceBusConnectionError` handling | No AMQP errors possible |

#### 7b. New Claim Method

```python
def _claim_next_task(self) -> Optional[TaskRecord]:
    """
    Atomically claim one READY task via SKIP LOCKED.

    Returns TaskRecord if claimed, None if no tasks available.
    Worker identity recorded for diagnostics and stale-task detection.
    """
    # Uses a dedicated method on TaskRepository
    return self._task_repo.claim_ready_task(
        worker_id=self._worker_id  # hostname:pid
    )
```

#### 7c. New Polling Loop

```python
def _run_loop(self):
    self._ensure_initialized()
    self._worker_id = f"{socket.gethostname()}:{os.getpid()}"

    while not self._stop_event.is_set():
        try:
            task_record = self._claim_next_task()

            if task_record is None:
                # No tasks available — poll again after interval
                self._stop_event.wait(self.poll_interval_seconds)  # 5s
                continue

            if self._stop_event.is_set():
                # Shutdown between claim and process — release task
                self._release_task(task_record.task_id)
                break

            task_message = TaskQueueMessage.from_task_record(task_record)
            self._process_task(task_message)

        except Exception as e:
            self._last_error = str(e)
            logger.warning(f"[Queue Worker] Error: {e}")
            self._stop_event.wait(self.poll_interval_on_error)  # 5s
```

#### 7d. Process Method (Simplified)

```python
def _process_task(self, task_message: TaskQueueMessage) -> bool:
    """Process a claimed task via CoreMachine."""
    docker_context = create_docker_context(
        task_id=task_message.task_id,
        job_id=task_message.parent_job_id,
        job_type=task_message.job_type,
        stage=task_message.stage,
        shutdown_event=self._stop_event,
        task_repo=self._task_repo,
        auto_start_pulse=True,
        enable_memory_watchdog=True,
        memory_threshold_percent=80,
    )

    try:
        result = self._core_machine.process_task_message(
            task_message,
            docker_context=docker_context
        )

        if result.get('success'):
            if result.get('interrupted'):
                # Graceful shutdown — release task for another worker
                self._release_task(task_message.task_id)
            # else: CoreMachine already marked COMPLETED
            self._messages_processed += 1
            return True
        else:
            # CoreMachine already marked FAILED
            return False

    finally:
        docker_context.stop_pulse()
        docker_context.stop_memory_watchdog()
```

#### 7e. Release Method (Replaces abandon_message)

```python
def _release_task(self, task_id: str):
    """Release a claimed task back to READY for another worker."""
    self._task_repo.release_task(task_id)  # UPDATE status='ready', claimed_by=NULL
```

### 8. TaskRepository — New Methods

**File**: `infrastructure/jobs_tasks.py`

```python
def claim_ready_task(self, worker_id: str) -> Optional[TaskRecord]:
    """
    Atomically claim one READY task via SKIP LOCKED.

    SQL:
        BEGIN;
        SELECT * FROM app.tasks
        WHERE status = 'ready'
          AND (execute_after IS NULL OR execute_after < NOW())
        ORDER BY created_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED;

        UPDATE app.tasks
        SET status = 'processing',
            claimed_by = %(worker_id)s,
            execution_started_at = NOW(),
            last_pulse = NOW(),
            updated_at = NOW()
        WHERE task_id = %(task_id)s;
        COMMIT;

    Returns:
        TaskRecord if claimed, None if no tasks available.
    """

def release_task(self, task_id: str) -> None:
    """
    Release a claimed task back to READY.

    Used during graceful shutdown when a task was claimed but
    processing hasn't started (or was interrupted before any
    side effects).

    SQL:
        UPDATE app.tasks
        SET status = 'ready',
            claimed_by = NULL,
            execution_started_at = NULL,
            last_pulse = NULL,
            updated_at = NOW()
        WHERE task_id = %(task_id)s
          AND status = 'processing';
    """
```

### 8b. Retry Flow

**Current**: When a task fails and is retry-eligible, CoreMachine calls `service_bus.send_message_with_delay()` to re-enqueue with exponential backoff. The `increment_task_retry_count` SQL function hardcodes `status = 'queued'::task_status`.

**New**: Retry is a DB-only operation using `execute_after` for backoff:

1. CoreMachine detects failed task with `retry_count < max_retries`
2. Sets task to `PENDING_RETRY` with `execute_after = NOW() + backoff`
3. Worker poll query already excludes tasks where `execute_after > NOW()`
4. When `execute_after` elapses, the task becomes eligible for pickup — but it's still `PENDING_RETRY`, not `READY`
5. **Promotion**: The worker poll query matches `status IN ('ready', 'pending_retry')` — no separate promotion step needed. `PENDING_RETRY` with elapsed `execute_after` is directly claimable.

```python
# CoreMachine retry path (replaces SB send_message_with_delay)
def _schedule_task_retry(self, task_id: str, retry_count: int):
    backoff_seconds = min(30 * (2 ** retry_count), 600)  # 30s, 60s, 120s, 240s, 600s max
    self.repos['task_repo'].schedule_retry(
        task_id=task_id,
        execute_after=datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
    )
```

```python
# TaskRepository.schedule_retry()
def schedule_retry(self, task_id: str, execute_after: datetime) -> None:
    """
    SQL:
        UPDATE app.tasks
        SET status = 'pending_retry',
            execute_after = %(execute_after)s,
            claimed_by = NULL,
            updated_at = NOW()
        WHERE task_id = %(task_id)s;
    """
```

**Worker claim query update** — match both READY and PENDING_RETRY:

```sql
SELECT * FROM app.tasks
WHERE status IN ('ready', 'pending_retry')
  AND (execute_after IS NULL OR execute_after < NOW())
ORDER BY created_at
LIMIT 1
FOR UPDATE SKIP LOCKED;
```

**Partial index update** to cover both statuses:

```sql
CREATE INDEX idx_tasks_claimable
ON app.tasks (created_at)
WHERE status IN ('ready', 'pending_retry')
  AND (execute_after IS NULL OR execute_after < NOW());
```

**SQL function update**: `increment_task_retry_count` in `sql_generator.py` must change from `status = 'queued'::task_status` to `status = 'pending_retry'::task_status` with the `execute_after` backoff.

### 8c. Stage Completion SQL

**Current**: `complete_task_and_check_stage` in `sql_generator.py` counts remaining tasks as:
```sql
AND status NOT IN ('completed', 'failed')
```

**New**: Must account for `SKIPPED` and `CANCELLED` as terminal:
```sql
AND status NOT IN ('completed', 'failed', 'skipped', 'cancelled')
```

Without this fix, `SKIPPED` or `CANCELLED` tasks would block stage completion forever.

### 8d. FAILED Status — Terminal Semantics

`FAILED` is dual-purpose:
- **Terminal for stage completion** — a failed task counts as "done" (stage can complete)
- **Non-terminal for retry** — allows transition to `PENDING_RETRY`

To avoid ambiguity, introduce two helper functions:

```python
def get_task_terminal_states():
    """States that count as 'done' for stage completion."""
    return [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED]

def get_task_settled_states():
    """States that will never change again (no retry possible)."""
    return [TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.CANCELLED]
```

Callers that need "is this task done forever" use `settled`. Callers that need "has this task finished its current attempt" use `terminal`. The guardian uses `terminal` to decide if a task needs recovery.

### 8e. System Guardian Changes — DEFERRED (15 MAR 2026)

**Decision**: Guardian updates are **not blocking** for DB-polling deploy. Deferred to Phase 2 (v0.10.4) when the orchestrator moves to a timer trigger — the guardian runs on the orchestrator, so both changes happen together.

**Why safe to defer**: All guardian phases are fail-open (try/except per phase). After DB-polling deploy:
- Phases 1a/1b: Dead code — queries for `status='pending'`/`status='queued'` return 0 rows (tasks now created as READY, QUEUED removed from enum). No harm.
- Phase 1c: Recovery action calls `_send_task_message()` (sends to SB queue workers no longer poll). Broken recovery path, but stale PROCESSING tasks are still caught by Phase 3c ancient stale backstop (6 hours). Acceptable gap.
- Phase 2: Zombie stage detection has stale `'queued'` string in NOT IN clause — should be `'ready'`. Could cause false positives (detects non-zombie stages). Low risk since READY tasks drain in seconds.
- Phase 3: `'queued'` in task count filter — cosmetic, affects reporting not recovery.
- Phase 4: No SB dependency. Works as-is.

**Files**: `services/system_guardian.py`, `infrastructure/guardian_repository.py`

**When this lands (v0.10.4)**, the changes are:

| Phase | Current | New |
|-------|---------|-----|
| 1a: Orphaned PENDING tasks | Re-sends SB message via `_send_task_message()` | **REMOVE** — tasks are created as READY, no orphan PENDING possible |
| 1b: Orphaned QUEUED tasks | Peeks SB queue, re-sends | **REMOVE** — no queue to peek |
| 1c: Stale PROCESSING tasks | Marks FAILED | **UPDATE** — check `claimed_by` + `last_pulse`. If worker is dead and retry budget remains, set `PENDING_RETRY` with `execute_after`. If retries exhausted, mark FAILED. |
| 1d: Stale PROCESSING check | Same as 1c | **MERGE** with 1c |
| Phase 2 zombie SQL | `'queued'` in NOT IN | **UPDATE** — `'queued'` → `'ready'` |
| Phase 3 task counts | `'queued'` filter | **UPDATE** — `'queued'` → `'ready'` |
| `_send_task_message()` | Sends to SB | **REPLACE** with `_reset_task_to_ready()` (~10 lines) |
| NEW: Retry promotion | N/A | **Not needed** — worker poll query handles PENDING_RETRY directly |

`guardian_repository.py` method `get_orphaned_pending_tasks()` queries `status = 'pending'` — this now means "dependencies not satisfied" (V11 DAG semantics), not "SB message lost." Remove or repurpose for V11.

### 9. SB Confirmation Trigger — Remove

**File**: `triggers/service_bus/task_handler.py`

The `_confirm_task_queued()` method updates `PENDING → QUEUED` when the Function App trigger confirms SB message receipt. This entire flow is eliminated:

- Tasks are created as `READY` — no confirmation step
- The SB trigger for `container-tasks` is no longer registered

The `geospatial-jobs` queue trigger (job orchestration) is **unchanged** in this phase.

### 10. Health Checks

**File**: `docker_health/shared.py`

Replace Service Bus health check with PostgreSQL polling health:

```python
# OLD: Check SB namespace connectivity, queue existence, permissions
# NEW: Check that claim_ready_task query executes without error
#      (already covered by PostgreSQL health check)
```

The `/readyz` endpoint checks `queue_worker.is_healthy()` — this stays but the health criteria change from "SB client connected" to "last poll completed without error."

### 11. Config Changes

**File**: `config/defaults.py`

`TaskRoutingDefaults.DOCKER_TASKS` — **KEEP as-is**. Still used by CoreMachine to validate task types. No routing decision needed (all tasks go to DB), but the frozenset serves as a registry of valid task types.

`QueueDefaults.CONTAINER_TASKS_QUEUE` — **Remove** or deprecate. No longer referenced.

### 12. Status Reporting — String References

Three files compare task status as raw strings. Update string literals:

| File | Old strings | New strings |
|------|-------------|-------------|
| `triggers/get_job_status.py` | `"pending"`, `"queued"` | `"pending"`, `"ready"` |
| `triggers/trigger_platform_status.py` | `"pending"`, `"queued"` | `"pending"`, `"ready"` |
| `triggers/admin/admin_system.py` | `"queued"` | `"ready"` |

---

## Blast Radius

### Files Changed

| File | Change | Risk |
|------|--------|------|
| `core/models/enums.py` | TaskStatus enum values | LOW — rebuild clears DB |
| `core/models/task.py` | TaskRecord fields + transitions | LOW — model only |
| `core/logic/transitions.py` | Transition table + state helpers + new settled/terminal distinction | LOW — logic only |
| `core/schema/queue.py` | Add `from_task_record()` classmethod | LOW — additive |
| `core/machine.py` | Remove SB send, change task status to READY, replace retry path | MEDIUM — orchestration |
| `core/state_manager.py` | Update status comparisons | LOW — string changes |
| `core/contracts/__init__.py` | Update docstring example | LOW — docs only |
| `core/schema/sql_generator.py` | Enum values + `complete_task_and_check_stage` terminal list + `increment_task_retry_count` status | MEDIUM — SQL correctness |
| `docker_service.py` | Replace SB polling with DB polling | MEDIUM — main change |
| `infrastructure/jobs_tasks.py` | Add `claim_ready_task()`, `release_task()`, `schedule_retry()` + update ~6 hardcoded `'queued'` strings in SQL | MEDIUM — additive + string changes |
| `infrastructure/postgresql.py` | Remove PENDING default reference | LOW — one line |
| `services/system_guardian.py` | Remove SB-dependent phases 1a/1b, update 1c stale detection | MEDIUM — recovery logic |
| `infrastructure/guardian_repository.py` | Remove orphaned PENDING/QUEUED queries, update stale PROCESSING query | MEDIUM — paired with guardian |
| `triggers/service_bus/task_handler.py` | Remove PENDING→QUEUED confirmation | LOW — delete code |
| `triggers/get_job_status.py` | Update string comparisons | LOW — cosmetic |
| `triggers/trigger_platform_status.py` | Update string comparisons | LOW — cosmetic |
| `triggers/admin/admin_system.py` | Update string comparisons | LOW — cosmetic |
| `triggers/admin/db_diagnostics.py` | Update hardcoded stale enum string in diagnostic output | LOW — cosmetic |
| `web_interfaces/base.py` | Add `status-ready` CSS class (replaces `status-queued`) | LOW — cosmetic |
| `docker_health/shared.py` | Remove SB health check | LOW — health only |
| `config/defaults.py` | Remove CONTAINER_TASKS_QUEUE | LOW — config only |

### Files Unchanged

| File | Why |
|------|-----|
| All 24 domain repository subclasses | Don't reference TaskStatus |
| All 30+ handler functions | `handler(params) → {success, result}` unchanged |
| `core/schema/deployer.py` | Schema deployment unchanged |
| `infrastructure/factory.py` | RepositoryFactory unchanged |
| `jobs/*.py` (all 14 job definitions) | `create_tasks_for_stage()` returns TaskDefinition unchanged |
| `triggers/platform/*` | B2B submission/status unchanged |
| `geospatial-jobs` queue trigger | Job orchestration queue unchanged (Phase 2) |
| `infrastructure/service_bus.py` | Still used for geospatial-jobs queue |

### B2B Contract

**Zero changes.** Gateway writes to DB → orchestrator processes → B2B polls status from DB. Service Bus was never in the B2B path.

---

## Risks Eliminated

| Risk | Description | How |
|------|-------------|-----|
| **G** (V10_DECISIONS) | Non-atomic task create + SB send | DB insert is atomic — task is READY or doesn't exist |
| **H** (V10_DECISIONS) | Double infrastructure failure during stage advance | No second system to fail |
| Lock expiry on long tasks | 2-hour AutoLockRenewer for GDAL jobs | DB row lock is implicit, no timeout |
| AMQP warmup bugs | ServiceBusConnectionError on cold start | PostgreSQL connection already established |
| DLQ management | Dead-letter queue monitoring | Task failure is a DB status, not a separate queue |

## New Risks Introduced

| Risk | Severity | Mitigation |
|------|----------|------------|
| Polling latency (5s vs SB push) | LOW | 5s worst-case delay is acceptable for ETL workloads |
| DB load from polling | LOW | Partial index on `status='ready'` keeps query sub-millisecond. N workers × 1 query/5s = trivial |
| Stale PROCESSING tasks (worker crash) | MEDIUM | Existing pulse mechanism + janitor reclaims tasks with stale `last_pulse`. Same pattern as today. |
| SKIP LOCKED requires PostgreSQL 9.5+ | NONE | We're on PostgreSQL 16 |

---

## Polling Interval Design

| Scenario | Interval | Rationale |
|----------|----------|-----------|
| No tasks available | 5 seconds | Balances responsiveness vs DB load |
| Task claimed and processed | Immediate next poll | Don't sleep between tasks — drain the queue |
| Error during claim | 5 seconds | Backoff before retry |
| Shutdown signal | Immediate exit | `stop_event.wait(5)` returns immediately when set |

Workers process tasks sequentially (one at a time), same as current SB behavior. Horizontal scaling via N worker instances, each independently claiming tasks via SKIP LOCKED.

---

## Deployment

### Prerequisites

1. `action=rebuild` to deploy new enum values and column changes
2. No in-flight jobs (rebuild drops app schema)

### Sequence

1. Stop Docker workers (drain current SB messages)
2. Deploy new code to all 3 apps (orchestrator, gateway, Docker)
3. Run `action=rebuild` on orchestrator
4. Start Docker workers — they now poll PostgreSQL
5. Verify with hello_world job

### Rollback

Revert code, run `action=rebuild` with old enum. Clean rollback since rebuild drops and recreates.

---

## Testing Plan

1. **Unit**: TaskStatus transitions — verify all valid/invalid paths
2. **Unit**: `TaskQueueMessage.from_task_record()` — round-trip fidelity
3. **Unit**: `claim_ready_task()` — returns record, sets PROCESSING
4. **Integration**: Submit hello_world job → task created as READY → worker claims → handler executes → stage completes
5. **Integration**: Multiple workers — submit 10-task job, verify SKIP LOCKED distributes evenly
6. **Integration**: Graceful shutdown — SIGTERM during processing → task released to READY
7. **SIEGE regression**: Run existing SIEGE suite against new code

---

## Non-Goals (This Phase)

- Replacing `geospatial-jobs` queue (job orchestration) — Phase 2
- YAML workflow definitions — V11
- DAG dependency resolution (PENDING → READY promotion) — V11
- `when:` clause evaluation (PENDING → SKIPPED) — V11
- Advisory lock orchestrator pattern — V11
- Removing `infrastructure/service_bus.py` — still used for geospatial-jobs

---

*Author: Claude + Robert Harrison*
*Date: 15 MAR 2026*
