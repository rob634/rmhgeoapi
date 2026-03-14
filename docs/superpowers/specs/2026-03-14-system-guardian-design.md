# SystemGuardian — Distributed Systems Recovery Engine

**Date**: 14 MAR 2026
**Status**: Design
**Replaces**: JanitorService + 3 timer triggers (task_watchdog, job_health, orphan_detector)
**Source risks**: V10_DECISIONS.md — Risk G (non-atomic task create + send), Risk H (stage advancement failure)

---

## Problem Statement

The job orchestration pipeline has two non-atomic boundaries where a hard crash (OOM, pod eviction) between a DB write and a Service Bus send can leave the system in an unrecoverable state:

**Risk G** — `core/machine.py:_individual_queue_tasks()`: Task row inserted (PENDING) but Service Bus message never sent. Orphaned task blocks stage completion indefinitely.

**Risk H** — `core/machine.py:_advance_stage()`: Job status updated to QUEUED but next-stage message never sent. If rollback also fails, job is stuck QUEUED with no tasks and no recovery path.

Inline code handles the *normal* failure case (catch exception, mark failed or rollback). The **unrecoverable case** — hard process crash between the two operations — requires an external observer.

The existing janitor system covers these scenarios functionally but has architectural issues:
1. Three independent timer triggers (5/10/15 min) with overlapping concerns and no ordering guarantees
2. Detection in one trigger can false-positive because a fix from another trigger hasn't run yet
3. Organically evolved — 9 files, inconsistent patterns, early-development structure
4. Critical distributed systems infrastructure deserves deliberate, auditable design

---

## Design Decisions (from brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Runtime | Orchestrator only (Function App) | Janitor is orchestration, not execution. Queries shared DB. |
| Scope | Full rearchitect | Pre-production, no consumers. Exercise flexibility while we have it. |
| Cadence | Single unified sweep, 5 min | Queries are cheap (~1-2s). Single sweep gives ordering guarantees. |
| Architecture | Ordered pipeline | Deterministic phase ordering eliminates false positives for free. |

### Updated Thresholds

| Check | Old | New | Rationale |
|-------|-----|-----|-----------|
| PENDING tasks | 2 min | 2 min | Unchanged — message sent but trigger never confirmed |
| QUEUED tasks | 5 min | 5 min | Unchanged — trigger confirmed but worker never started |
| PROCESSING tasks (Function App) | 30 min | 30 min | Unchanged — Function App max execution time |
| PROCESSING tasks (Docker) | 24 hours | **3 hours** | Longest confirmed task: 90 min zarr/netcdf. 2x margin. |
| Stuck QUEUED jobs (no tasks) | 1 hour | **10 min** | Risk H: if no tasks after 10 min, advancement failed |
| Ancient stale jobs | 24 hours | **6 hours** | 2x Docker task ceiling |

---

## Architecture

### Single Entry Point

```
SystemGuardian.sweep()
  │
  ├── Phase 1: Task Recovery
  │   ├── 1a. Orphaned PENDING tasks (>2 min)
  │   ├── 1b. Orphaned QUEUED tasks (>5 min)
  │   ├── 1c. Stale PROCESSING tasks — Function App (>30 min)
  │   └── 1d. Stale PROCESSING tasks — Docker (>3 hours)
  │
  ├── Phase 2: Stage Recovery
  │   └── 2a. Zombie stages — all tasks terminal, stage not advanced
  │
  ├── Phase 3: Job Recovery
  │   ├── 3a. PROCESSING jobs with failed tasks → propagate failure
  │   ├── 3b. Stuck QUEUED jobs, no tasks (>10 min)
  │   └── 3c. Ancient stale jobs (>6 hours)
  │
  └── Phase 4: Consistency
      └── 4a. Orphaned tasks (parent job missing)
```

### Phase Ordering Rationale

The ordering is deliberate and load-bearing:

- **Phase 1 before Phase 2**: Fixing a stuck task in 1a/1b may allow it to complete naturally, which triggers stage advancement via the normal "last task turns out the lights" path. Running Phase 2 first would detect a false zombie.
- **Phase 2 before Phase 3**: Advancing a stuck stage in 2a may unblock the job entirely. Running Phase 3 first would fail a job that could have recovered.
- **Phase 3 after 1+2**: By this point, any task or stage that *could* be fixed has been. Remaining anomalies are genuinely broken.
- **Phase 4 last**: Structural inconsistencies (missing parent jobs) are rare edge cases that don't interact with the recovery phases above.

### File Structure

```
services/system_guardian.py           — sweep logic, phase orchestration, config
infrastructure/guardian_repository.py — all DB queries for anomaly detection + fixes
triggers/janitor/system_guardian.py   — single 5-min timer trigger
triggers/admin/admin_janitor.py       — HTTP endpoints (updated to use SystemGuardian)
core/models/janitor.py                — audit models (reused, minor updates)
```

### Files Deleted

```
triggers/janitor/task_watchdog.py
triggers/janitor/job_health.py
triggers/janitor/orphan_detector.py
services/janitor_service.py
infrastructure/janitor_repository.py
```

---

## Component Design

### SystemGuardian (`services/system_guardian.py`)

Single class. No inheritance. Static configuration. All state flows through method parameters.

```python
@dataclass(frozen=True)
class GuardianConfig:
    """Immutable sweep configuration. All timeouts in minutes unless noted."""
    sweep_interval_minutes: int = 5
    pending_task_timeout_minutes: int = 2
    queued_task_timeout_minutes: int = 5
    processing_task_timeout_minutes: int = 30      # Function App tasks
    docker_task_timeout_minutes: int = 180          # 3 hours
    stuck_queued_job_timeout_minutes: int = 10      # Risk H detection
    ancient_job_timeout_minutes: int = 360          # 6 hours
    max_task_retries: int = 3
    enabled: bool = True
```

```python
@dataclass
class SweepResult:
    """Result of a single sweep() call. One per timer invocation."""
    sweep_id: str                    # UUID
    started_at: datetime
    completed_at: Optional[datetime]
    phases: Dict[str, PhaseResult]   # keyed by phase name
    total_scanned: int
    total_fixed: int
    success: bool
    error: Optional[str]

@dataclass
class PhaseResult:
    """Result of one phase within a sweep."""
    phase: str                       # "task_recovery", "stage_recovery", etc.
    scanned: int
    fixed: int
    actions: List[Dict[str, Any]]    # audit trail entries
    error: Optional[str]             # None if phase succeeded, error message if failed
```

```python
class SystemGuardian:
    def __init__(self, repo: GuardianRepository, queue_client: QueueClient):
        self._repo = repo
        self._queue = queue_client
        self._config = GuardianConfig()

    def sweep(self) -> SweepResult:
        """Run all phases in order. Each phase runs regardless of
        previous phase outcome (fail-open)."""
        ...

    # Phase methods — private, called by sweep() in order
    def _phase_task_recovery(self) -> PhaseResult: ...
    def _phase_stage_recovery(self) -> PhaseResult: ...
    def _phase_job_recovery(self) -> PhaseResult: ...
    def _phase_consistency(self) -> PhaseResult: ...
```

**Fail-open design**: If Phase 1 errors, Phase 2 still runs. A phase error is logged in its `PhaseResult.error` but does not abort the sweep. Rationale: a transient DB error in one query should not prevent the other phases from running.

### GuardianRepository (`infrastructure/guardian_repository.py`)

All detection queries and fix operations. Organized by phase.

```python
class GuardianRepository(PostgreSQLRepository):
    """DB operations for SystemGuardian anomaly detection and recovery."""

    # --- Phase 1: Task Recovery ---
    def get_orphaned_pending_tasks(self, timeout_minutes: int) -> List[Dict]: ...
    def get_orphaned_queued_tasks(self, timeout_minutes: int) -> List[Dict]: ...
    def get_stale_processing_tasks(self, timeout_minutes: int, exclude_types: List[str]) -> List[Dict]: ...
    def get_stale_docker_tasks(self, timeout_minutes: int, docker_types: List[str]) -> List[Dict]: ...

    # --- Phase 2: Stage Recovery ---
    def get_zombie_stages(self) -> List[Dict]: ...
        """Jobs where status=PROCESSING, all tasks for current stage are terminal,
        but stage has not advanced. This is Risk H's observable symptom."""

    # --- Phase 3: Job Recovery ---
    def get_jobs_with_failed_tasks(self) -> List[Dict]: ...
    def get_stuck_queued_jobs(self, timeout_minutes: int) -> List[Dict]: ...
    def get_ancient_stale_jobs(self, timeout_minutes: int) -> List[Dict]: ...
    def get_completed_task_results(self, job_id: str) -> List[Dict]: ...

    # --- Phase 4: Consistency ---
    def get_orphaned_tasks(self) -> List[Dict]: ...

    # --- Fix operations (shared across phases) ---
    def mark_tasks_failed(self, task_ids: List[str], error: str) -> int: ...
    def mark_job_failed(self, job_id: str, error: str, partial_results: Dict = None) -> bool: ...
    def increment_task_retry(self, task_id: str) -> int: ...

    # --- Audit ---
    def log_sweep(self, result: SweepResult) -> str: ...
    def get_recent_sweeps(self, hours: int = 24, limit: int = 50) -> List[Dict]: ...
```

### Phase 2 Detail: Zombie Stage Detection (Risk H Fix)

This is the new detection that explicitly targets Risk H. The query finds jobs where:
1. Job status is PROCESSING
2. All tasks for the job's current `stage` are in terminal state (COMPLETED or FAILED)
3. The job's `stage` has not advanced

```sql
SELECT j.job_id, j.job_type, j.stage, j.parameters,
       COUNT(*) FILTER (WHERE t.status = 'completed') AS completed_tasks,
       COUNT(*) FILTER (WHERE t.status = 'failed') AS failed_tasks
FROM {schema}.jobs j
JOIN {schema}.tasks t ON t.parent_job_id = j.job_id
    AND t.stage = j.stage
WHERE j.status = 'processing'
GROUP BY j.job_id
HAVING COUNT(*) FILTER (WHERE t.status NOT IN ('completed', 'failed')) = 0
```

**Recovery action for zombie stages**:
- If any failed tasks in stage → mark job FAILED with partial results (same as current job_health behavior)
- If all tasks completed → **re-attempt stage advancement** by sending a `StageCompleteMessage` to the jobs queue. This gives `_handle_stage_completion()` another chance to run. If it fails again, the next sweep will catch it as a stuck QUEUED job (Phase 3b) and fail it.

This is the key new capability: instead of just failing zombie jobs, we **attempt recovery first** for the all-tasks-completed case.

### Phase 1 Detail: Task Retry Logic (Risk G Fix)

Retained from existing janitor but clarified:

| Task State | Condition | Action |
|------------|-----------|--------|
| PENDING, >2 min | `retry_count < max` | Re-send Service Bus message |
| PENDING, >2 min | `retry_count >= max` | Mark FAILED |
| QUEUED, >5 min | Peek queue: message exists | **Skip** (worker backlog, not orphaned) |
| QUEUED, >5 min | Peek queue: no message, `retry_count < max` | Re-send Service Bus message |
| QUEUED, >5 min | Peek queue: no message, `retry_count >= max` | Mark FAILED |
| PROCESSING, >30 min (FA) | `last_pulse is None` and `retry_count < max` | Re-queue |
| PROCESSING, >30 min (FA) | `last_pulse is not None` or `retry_count >= max` | Mark FAILED |
| PROCESSING, >3 hours (Docker) | Always | Mark FAILED (no retry for long tasks) |

**Queue peek for QUEUED tasks**: Before re-sending a message for a QUEUED task, peek the Service Bus queue to check if a message for that task already exists. If it does, the task is not orphaned — it's waiting behind a backlog. This prevents duplicate processing. Implemented via `service_bus.message_exists_for_task(queue_name, task_id)` (carried forward from existing janitor).

### Timer Trigger (`triggers/janitor/system_guardian.py`)

Single trigger, replaces three:

```python
@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer")  # Every 5 min
def system_guardian_sweep(timer: func.TimerRequest) -> None:
    guardian = _build_guardian()
    result = guardian.sweep()
    logger.info(
        f"[GUARDIAN] Sweep {result.sweep_id}: "
        f"scanned={result.total_scanned} fixed={result.total_fixed} "
        f"success={result.success}"
    )
```

### HTTP Endpoints (updated `admin_janitor.py`)

Existing endpoints updated to use SystemGuardian:

| Endpoint | Purpose |
|----------|---------|
| `POST /api/cleanup/run?type=sweep` | Trigger manual sweep |
| `POST /api/cleanup/run?type=phase_1` | Run single phase (debugging) |
| `GET /api/cleanup/status` | Config + last 24h stats |
| `GET /api/cleanup/history` | Recent sweep results |

The `type=task_watchdog|job_health|orphan_detector` values become aliases that map to individual phases for backward compatibility during transition, then are removed.

---

## Audit Trail

### Existing Infrastructure (carried forward)

The `app.janitor_runs` table stores audit records for all maintenance operations. Indexed on `started_at DESC` and `run_type`. Schema generated from `JanitorRun` Pydantic model in `core/models/janitor.py`.

### Two-Phase Write Pattern (carried forward, required)

The existing system uses a two-phase write that must be preserved:

1. **INSERT at sweep start** — creates audit row with `status='running'` before any phase executes. If the sweep crashes mid-run, the `running` row persists as evidence of the failure.
2. **UPDATE at sweep end** — sets `completed_at`, `duration_ms`, `status`, final `items_scanned`/`items_fixed`, `actions_taken`, and the new `phases` breakdown.

Both writes are **non-fatal** — wrapped so audit failure does not kill the sweep itself. A sweep that can't write audit records still performs recovery. Audit is observability, not a gate.

### Schema Changes

| Column | Change |
|--------|--------|
| `run_type` | New value: `sweep` (replaces task_watchdog/job_health/orphan_detector) |
| `phases` | **New JSONB column**: per-phase breakdown (see structure below) |
| `duration_ms` | Existing — carried forward, calculated at completion |
| All existing columns | Retained unchanged for backward compatibility with non-sweep run types (e.g., `queue_depth_snapshot`) |

### `phases` JSONB Structure

```json
{
    "task_recovery": {
        "scanned": 12,
        "fixed": 2,
        "actions": [
            {"action": "resend_pending_task", "task_id": "abc-123", "parent_job_id": "def-456", "reason": "pending_timeout"},
            {"action": "mark_queued_task_failed", "task_id": "ghi-789", "reason": "max_retries_exceeded"}
        ],
        "error": null
    },
    "stage_recovery": {"scanned": 3, "fixed": 1, "actions": [...], "error": null},
    "job_recovery": {"scanned": 5, "fixed": 0, "actions": [], "error": null},
    "consistency": {"scanned": 0, "fixed": 0, "actions": [], "error": null}
}
```

The flat `actions_taken` JSONB array is also retained — it aggregates all actions across all phases into a single list for simple queries like "show me everything this sweep did." The `phases` column adds structured breakdown for per-phase analysis.

### Model Updates Required

`core/models/janitor.py`:
- Add `SWEEP = "sweep"` to `JanitorRunType` enum
- Add `phases: Optional[Dict[str, Any]] = None` field to `JanitorRun` model (nullable for backward compatibility with old rows)

### Non-sweep Run Types

The audit table continues to serve non-sweep operations invoked via HTTP endpoints (`queue_depth_snapshot`, `metadata_consistency`, `log_cleanup`). These write their own rows with their own `run_type` values. The `phases` column is nullable and unused for these run types.

---

## Carried Forward from Existing Janitor

These behaviors from `JanitorService` are preserved in SystemGuardian:

### Schema readiness guard

Every `sweep()` call checks `information_schema.tables` for `app.jobs` before executing any queries. Without this, the guardian throws errors during schema rebuilds and floods logs. Implemented as `GuardianRepository.schema_ready() -> bool`, called once at the top of `sweep()`. If not ready, sweep returns immediately with `success=True, total_scanned=0` (not an error — schema rebuild is expected).

### Partial results capture

When marking a job FAILED (Phase 3a, 3c), capture completed task results first via `GuardianRepository.get_completed_task_results(job_id)`. Store in `result_data` JSONB on the job record. Structure:

```python
{
    "status": "partial_failure",
    "completed_tasks_count": int,
    "failed_tasks_count": int,
    "total_tasks_count": int,
    "failed_at_stage": int,
    "partial_results": [{"task_id": str, "task_type": str, "result_data": dict}],
    "guardian_cleanup_at": datetime_iso
}
```

### Task-to-queue routing

Re-queue operations must route tasks to the correct Service Bus queue. Use `TaskRoutingDefaults.DOCKER_TASKS` and `QueueDefaults` from `core/models/` to determine whether a task goes to the jobs queue or docker queue. The `SystemGuardian.__init__` receives a `QueueClient` that supports `send_to_queue(queue_name, message)` — the guardian resolves queue name via routing defaults, not by hardcoding queue names.

### Environment variable overrides

`GuardianConfig` supports construction from environment variables for operational flexibility:

```python
@classmethod
def from_environment(cls) -> 'GuardianConfig':
    """Override defaults from GUARDIAN_* env vars."""
    return cls(
        pending_task_timeout_minutes=int(os.getenv('GUARDIAN_PENDING_TIMEOUT_MINUTES', 2)),
        queued_task_timeout_minutes=int(os.getenv('GUARDIAN_QUEUED_TIMEOUT_MINUTES', 5)),
        processing_task_timeout_minutes=int(os.getenv('GUARDIAN_PROCESSING_TIMEOUT_MINUTES', 30)),
        docker_task_timeout_minutes=int(os.getenv('GUARDIAN_DOCKER_TIMEOUT_MINUTES', 180)),
        stuck_queued_job_timeout_minutes=int(os.getenv('GUARDIAN_STUCK_JOB_TIMEOUT_MINUTES', 10)),
        ancient_job_timeout_minutes=int(os.getenv('GUARDIAN_ANCIENT_JOB_TIMEOUT_MINUTES', 360)),
        max_task_retries=int(os.getenv('GUARDIAN_MAX_TASK_RETRIES', 3)),
        enabled=os.getenv('GUARDIAN_ENABLED', 'true').lower() == 'true',
    )
```

### Non-sweep utilities retained separately

These existing capabilities are NOT part of the sweep pipeline but are retained in the HTTP endpoints:

- **`metadata_consistency`** — Unified metadata validation (09 JAN 2026)
- **`log_cleanup`** — Clean up expired JSONL log files (11 JAN 2026)
- **`queue_depth_snapshot`** — Snapshot Service Bus queue depths for trending (03 MAR 2026)

These move to standalone functions called from the HTTP trigger, not from `SystemGuardian`. They are monitoring/maintenance operations, not distributed systems recovery.

---

## Audit Trail Schema Change

The `phases` JSONB column addition to `app.janitor_runs` must be added to the table definition in `core/schema/sql_generator.py`. This is an additive change — deployable via `action=ensure`.

---

## What This Design Does NOT Change

- **`core/machine.py`** — No changes. The inline error handling (catch + fail task, catch + rollback) stays. SystemGuardian is defense-in-depth for the cases inline code can't handle (hard crash).
- **`core/schema/sql_generator.py`** — No changes. `complete_task_and_check_stage()` SQL function unchanged.
- **`infrastructure/postgresql.py`** — No changes to connection or query infrastructure.
- **Docker worker** — No janitor code added. Orchestrator handles everything.
- **Existing audit data** — Old `janitor_runs` rows preserved. New sweeps write new-format rows.

---

## Migration Path

1. Build `SystemGuardian` + `GuardianRepository` as new files
2. Build new timer trigger in `triggers/janitor/system_guardian.py`
3. Update HTTP endpoints in `admin_janitor.py` to use SystemGuardian
4. Add `phases` JSONB column to `janitor_runs` table definition in `core/schema/sql_generator.py`
5. Delete old files: `task_watchdog.py`, `job_health.py`, `orphan_detector.py`, `janitor_service.py`, `janitor_repository.py`
6. **Single atomic commit**: New files + deletions + schema change deployed together so no window exists where old triggers are gone but new trigger isn't registered
7. Deploy and run `action=ensure` for the new column
8. Verify via manual `POST /api/cleanup/run?type=sweep`

---

## Success Criteria

1. **Risk G covered**: Orphaned PENDING/QUEUED tasks detected and re-queued or failed within 2 sweeps (10 min)
2. **Risk H covered**: Zombie stages detected and recovery attempted within 2 sweeps; stuck QUEUED jobs failed within 3 sweeps (15 min)
3. **No false positives from phase ordering**: Phase 1 task fixes prevent Phase 2/3 false detections
4. **Full audit trail**: Every sweep logged with per-phase breakdown
5. **Single timer trigger**: Replaces 3 independent triggers
6. **Threshold accuracy**: Docker tasks tolerate 90-min zarr/netcdf without false timeout
7. **HTTP manual trigger works**: `POST /api/cleanup/run?type=sweep` for on-demand execution
