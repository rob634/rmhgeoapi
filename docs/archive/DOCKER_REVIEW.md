# Docker Worker Integration Review

**Created**: 18 JAN 2026
**Current Version**: 0.7.14.8
**Target Version**: 0.8.0 (upon completion of Docker integration)
**Status**: 🟡 IN REVIEW

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Service Bus Queue Implementation](#service-bus-queue-implementation)
4. [Checkpoint/Resume Support](#checkpointresume-support)
5. [Issues and Concerns](#issues-and-concerns)
6. [Action Items for 0.8.0](#action-items-for-080)
7. [Testing Checklist](#testing-checklist)

---

## Executive Summary

The Docker worker provides long-running task processing capability that exceeds Azure Functions' 10-minute timeout limit. It uses the **same CoreMachine processing engine** as Function Apps, with the only difference being the trigger mechanism (polling vs Function trigger).

### Operating Model

| Aspect | Configuration |
|--------|---------------|
| **Concurrency** | 1 message per instance |
| **Scaling** | Horizontal (multiple container instances) |
| **Queue** | `long-running-tasks` (dedicated) |
| **Lock Renewal** | AutoLockRenewer (2-hour max) |
| **Graceful Shutdown** | SIGTERM/SIGINT handling with checkpoint support |

### Key Files

| File | Purpose |
|------|---------|
| `docker_main.py` | Pure queue worker (CLI entry point) |
| `docker_service.py` | HTTP + queue worker (container entry point) |
| `core/docker_context.py` | DockerTaskContext for handlers |
| `infrastructure/checkpoint_manager.py` | Phase-based checkpoint persistence |

---

## Architecture Overview

### Queue Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TASK ROUTING (CoreMachine)                        │
│                                                                          │
│  Task arrives → TaskRoutingDefaults determines queue:                    │
│    - Large rasters (> docker_mb threshold) → long-running-tasks          │
│    - FATHOM ETL handlers → long-running-tasks                            │
│    - Normal rasters → raster-tasks (Function App)                        │
│    - Vector tasks → vector-tasks (Function App)                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     long-running-tasks Queue                             │
│                     (Azure Service Bus)                                  │
│                                                                          │
│  Settings:                                                               │
│    - Lock Duration: 30 minutes                                           │
│    - Max Delivery Count: 3                                               │
│    - Message TTL: 30 days                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
    ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
    │ Docker Inst 1 │       │ Docker Inst 2 │       │ Docker Inst N │
    │ (Competing)   │       │ (Competing)   │       │ (Competing)   │
    └───────────────┘       └───────────────┘       └───────────────┘
```

### Entry Points

#### 1. `docker_main.py` - Pure Queue Worker
```bash
APP_MODE=worker_docker python docker_main.py
```
- No HTTP server
- Direct Service Bus polling loop
- Suitable for CLI/batch scenarios

#### 2. `docker_service.py` - HTTP + Queue Worker
```bash
uvicorn docker_service:app --host 0.0.0.0 --port 80
```
- FastAPI HTTP server for health probes
- Background thread for queue polling
- Required for Kubernetes/Azure Web App deployment

### Health Endpoints (docker_service.py)

| Endpoint | Purpose | K8s Probe |
|----------|---------|-----------|
| `/livez` | Process running? | Liveness |
| `/readyz` | Can serve traffic? | Readiness |
| `/health` | Detailed diagnostics | - |
| `/queue/status` | Queue worker status | - |

---

## Service Bus Queue Implementation

### Single-Message Competing Consumer Pattern

```python
# docker_service.py:573-576
messages = receiver.receive_messages(
    max_message_count=1,           # ONE at a time
    max_wait_time=self.max_wait_time_seconds  # 30s long poll
)
```

### Lock Renewal (Competing Consumer Protection)

```python
# docker_service.py:555-559
lock_renewer = AutoLockRenewer(max_lock_renewal_duration=7200)  # 2 hours

# docker_service.py:586-589 - Manual registration AFTER receive, BEFORE process
lock_renewer.register(receiver, message, max_lock_renewal_duration=7200)
```

**Why Manual Registration?**
- Explicit control over which messages get renewal
- Register only after successfully receiving (not speculatively)
- Prevents competing consumer race condition

### Message Lifecycle

| Outcome | Action | Result |
|---------|--------|--------|
| `success: True` | `complete_message()` | Removed from queue |
| `success: False` | `dead_letter_message()` | Moved to DLQ |
| Exception | `abandon_message()` | Returns to queue for retry |

### Graceful Shutdown Flow

```
SIGTERM received
    │
    ▼
worker_lifecycle.initiate_shutdown()
    │
    ├─→ shutdown_event.set()
    │       │
    │       ▼
    │   queue_worker sees event
    │       │
    │       ├─→ Stop accepting new messages
    │       ├─→ In-flight task checks should_stop()
    │       └─→ Save checkpoint if interrupted
    │
    └─→ ConnectionPoolManager.shutdown()
            │
            ▼
        Drain database connections
```

---

## Checkpoint/Resume Support

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  DOCKER WORKER                                                   │
│                                                                  │
│  BackgroundQueueWorker._process_message()                        │
│       │                                                          │
│       │ Creates DockerTaskContext with:                          │
│       │   - CheckpointManager (shutdown-aware)                   │
│       │   - shutdown_event (shared)                              │
│       │   - task_repo (for persistence)                          │
│       │                                                          │
│       ▼                                                          │
│  CoreMachine.process_task_message(msg, docker_context=ctx)       │
│       │                                                          │
│       │ Injects _docker_context into handler params              │
│       │                                                          │
│       ▼                                                          │
│  Handler (e.g., process_raster_complete)                         │
│       │                                                          │
│       ├─→ context.should_stop() - Check shutdown                 │
│       ├─→ checkpoint.should_skip(phase) - Resume logic           │
│       ├─→ checkpoint.save(phase, data) - Persist progress        │
│       └─→ context.report_progress() - Visibility                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### CheckpointManager API

```python
# Initialize (automatic in DockerTaskContext)
checkpoint = CheckpointManager(task_id, task_repo, shutdown_event)

# Check if phase already completed (resume scenario)
if not checkpoint.should_skip(1):
    result = do_phase_1()
    checkpoint.save(1, data={'result': result})

# Check for graceful shutdown
if checkpoint.should_stop():
    checkpoint.save(current_phase, data=progress)
    return {'success': True, 'interrupted': True}

# Convenience: save and check in one call
if checkpoint.save_and_stop_if_requested(phase, data):
    return {'interrupted': True}
```

### Database Schema

```sql
-- app.tasks columns for checkpoint
checkpoint_phase INTEGER,           -- Last completed phase (0 = not started)
checkpoint_data JSONB,              -- Phase-specific data for resume
checkpoint_updated_at TIMESTAMPTZ   -- Last checkpoint time
```

### Handler Implementation Pattern

```python
def my_docker_handler(params: Dict) -> Dict:
    docker_context = params.get('_docker_context')

    if docker_context:
        checkpoint = docker_context.checkpoint
    else:
        # Function App fallback (no checkpoint)
        checkpoint = None

    # Phase 1
    if not checkpoint or not checkpoint.should_skip(1):
        result = do_phase_1()
        if checkpoint:
            checkpoint.save(1, data={'phase1': result})

    # Check shutdown between phases
    if docker_context and docker_context.should_stop():
        return {'success': True, 'interrupted': True, 'resumable': True}

    # Phase 2
    if not checkpoint or not checkpoint.should_skip(2):
        phase1_data = checkpoint.get_data('phase1') if checkpoint else result
        result2 = do_phase_2(phase1_data)
        if checkpoint:
            checkpoint.save(2, data={'phase2': result2},
                          validate_artifact=lambda: artifact_exists())

    return {'success': True, 'result': {...}}
```

---

## Issues and Concerns

### Issue 1: Interrupted Task Completes Message (CRITICAL)

**Severity**: 🔴 HIGH
**Location**: `docker_service.py:505-526`, `docker_main.py:249-269`
**Status**: ✅ FIXED (18 JAN 2026)

**Problem**: When a handler returns `{'success': True, 'interrupted': True}` during graceful shutdown, the message was **completed** (removed from queue) rather than abandoned.

**Impact**: Checkpointed but incomplete tasks were orphaned - no one would resume them.

**Fix Applied**:
```python
if result.get('success'):
    if result.get('interrupted'):
        # Graceful shutdown - abandon so another instance can resume
        # Checkpoint was saved, delivery_count increments, message becomes visible
        logger.info(
            f"[Queue] Interrupted (checkpoint saved), abandoning for resume: "
            f"{task_id[:16]}... (phase {result.get('phase_completed', '?')})"
        )
        receiver.abandon_message(message)
        return True  # Not an error, just interrupted
    else:
        receiver.complete_message(message)
```

**Note**: Abandoning increments `delivery_count`. Current queue setting is `maxDeliveryCount=3`.
Production should consider increasing to 5-10 to handle repeated scaling events.

---

### Issue 2: No Automatic Resume Trigger

**Severity**: 🔴 HIGH

**Problem**: Even if Issue 1 is fixed, there's no mechanism to detect and resume orphaned checkpointed tasks if:
- Container crashes without graceful shutdown
- Message expires or is dead-lettered
- Task marked COMPLETED but checkpoint_phase < final phase

**Options**:
1. **Fix Issue 1** - Most cases handled by message abandonment
2. **Background scanner** - Detect tasks with `checkpoint_phase > 0` and `status = PROCESSING` for > N minutes
3. **Job-level retry** - Parent job detects incomplete stage and re-queues tasks

---

### Issue 3: CoreMachine Status Mismatch

**Severity**: 🟡 MEDIUM

**Problem**: CoreMachine marks task as COMPLETED when handler returns `success: True`, regardless of checkpoint state.

| Scenario | checkpoint_phase | task.status | Correct? |
|----------|------------------|-------------|----------|
| Normal completion | 3 | COMPLETED | ✅ |
| Interrupted at phase 1 | 1 | COMPLETED | ❌ |

**Options**:
1. Handler returns `success: False` for interrupted (changes dead-letter behavior)
2. Add `interrupted` status to task states
3. CoreMachine checks for `interrupted` flag before marking COMPLETED

---

### Issue 4: Limited Handler Adoption

**Severity**: 🟢 LOW

**Current State**: Only `handler_process_raster_complete.py` implements checkpoint pattern.

**Handlers NOT using checkpoints**:
- FATHOM ETL handlers (`fathom_phase1_band_stack`, `fathom_phase2_spatial_merge`)
- H3 bootstrap handlers
- Other Docker-routed handlers

**Action**: Audit Docker-routed handlers and add checkpoint support where beneficial.

---

### Issue 5: docker_main.py Has Same Issue

**Severity**: 🟡 MEDIUM
**Location**: `docker_main.py:249-269`
**Status**: ✅ FIXED (18 JAN 2026)

Same pattern as docker_service.py - fixed with identical change.

---

### Issue 6: execution_started_at Never Set

**Severity**: 🟡 MEDIUM
**Location**: `core/machine.py:786-810`, `core/schema/updates.py:58-60`
**Status**: ✅ FIXED (18 JAN 2026)

**Problem**: The `execution_started_at` column existed in TaskRecord but was never being set when tasks started processing. This meant:
- No way to track when Docker tasks actually started executing
- `execution_time_ms` couldn't be calculated (relies on `updated_at - execution_started_at`)
- Investigation of stuck/slow tasks was impossible

**Root Cause**: `TaskUpdateModel` was missing the `execution_started_at` field, and CoreMachine used `update_task_status_direct()` which only sets status.

**Fix Applied**:
1. Added `execution_started_at` to `TaskUpdateModel` (`core/schema/updates.py`)
2. Modified CoreMachine to set `execution_started_at` when task → PROCESSING:

```python
# core/machine.py:787-810
execution_start = datetime.now(timezone.utc)

update_model = TaskUpdateModel(
    status=TaskStatus.PROCESSING,
    execution_started_at=execution_start
)
success = self.state_manager.update_task_with_model(
    task_message.task_id,
    update_model
)
```

**Note**: `execution_time_ms` is NOT a database column - it's calculated at query time from `updated_at - execution_started_at` (see `triggers/admin/db_data.py:661-663`).

---

## Action Items for 0.8.0

### Must Have (Blocking)

| # | Item | File(s) | Status |
|---|------|---------|--------|
| 1 | Fix interrupted message handling | `docker_service.py`, `docker_main.py` | ✅ DONE |
| 2 | Fix execution_started_at tracking | `core/machine.py`, `core/schema/updates.py` | ✅ DONE |
| 3 | Add integration test for checkpoint resume | `tests/` | ⬜ TODO |
| 4 | Document checkpoint pattern for handlers | `docs_claude/` | ⬜ TODO |

### Should Have

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| 4 | Add `INTERRUPTED` task status | `core/models/task.py`, CoreMachine | Medium |
| 5 | Add checkpoint to FATHOM handlers | `services/fathom_*.py` | Medium |
| 6 | Background orphan scanner | New service | High |

### Nice to Have

| # | Item | File(s) | Effort |
|---|------|---------|--------|
| 7 | Checkpoint metrics (resume count, etc.) | Observability | Low |
| 8 | Admin endpoint to re-queue orphaned tasks | `triggers/` | Medium |

---

## Testing Checklist

### Unit Tests

- [ ] CheckpointManager.should_skip() returns correct values
- [ ] CheckpointManager.save() persists to database
- [ ] CheckpointManager.save_and_stop_if_requested() detects shutdown
- [ ] DockerTaskContext wires shutdown_event correctly

### Integration Tests

- [ ] Handler resumes from phase 1 checkpoint
- [ ] Handler resumes from phase 2 checkpoint
- [ ] Artifact validation prevents invalid checkpoint
- [ ] Graceful shutdown saves checkpoint and abandons message
- [ ] Abandoned message picked up by another instance
- [ ] Lock renewal prevents competing consumer

### Manual/E2E Tests

- [ ] Submit large raster → routed to Docker
- [ ] SIGTERM during processing → checkpoint saved
- [ ] Container restart → task resumes from checkpoint
- [ ] Multiple Docker instances → no duplicate processing

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.7.14.8 | Current | Docker worker with checkpoint support |
| 0.7.14.9 | 18 JAN 2026 | Fix: Interrupted tasks now abandon message for resume |
| 0.7.14.10 | 18 JAN 2026 | Fix: execution_started_at now set when task → PROCESSING |
| 0.8.0 | Target | Full Docker integration (remaining issues resolved) |

---

## References

- `docs_claude/SERVICE_BUS_HARMONIZATION.md` - Queue configuration
- `docs_claude/ARCHITECTURE_REFERENCE.md` - CoreMachine details
- `docs_claude/FATHOM_ETL.md` - ETL pipeline (primary Docker workload)
