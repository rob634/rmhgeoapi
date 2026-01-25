# CoreMachine Gap Analysis & Job Events Table

**Last Updated**: 24 JAN 2026
**Epic**: E7 Pipeline Infrastructure
**Status**: GAPS FIXED - Ready for events table implementation
**Goal**: Add checkpoints/handling for silent failure points, then create job_events table for execution timeline UI

---

## Background

CoreMachine workflow has several potential "silent failure" points where errors could occur but not be properly logged or tracked. Need to:
1. Fix identified gaps in error handling
2. Create `app.job_events` table to track each execution step
3. Build UI to visualize execution timeline and identify "last successful step"

---

## CoreMachine Execution Flow

```
POST /api/platform/submit
  ↓
1. Job Creation (platform_service.submit_job)
   - Creates job record (QUEUED)
   - Creates stage records
   - Sends job message to Service Bus
   ↓
2. Job Message Processing (CoreMachine.handle_job_message)
   - Validates job exists
   - Creates tasks for stage 1
   - Sends task messages to Service Bus
   - Updates job status → PROCESSING
   ↓
3. Task Processing (CoreMachine.handle_task_message)
   - Executes task handler
   - Updates task status → COMPLETED/FAILED
   - Checks for stage completion ("last task turns out lights")
   ↓
4. Stage Advancement (CoreMachine._advance_to_next_stage)
   - Called when all tasks in stage complete
   - Creates tasks for next stage OR finalizes job
   ↓
5. Job Completion (CoreMachine._finalize_job)
   - Updates job status → COMPLETED
   - Calls on_job_complete callback (approval records, etc.)
```

---

## Gap Analysis

| Gap | Location | Issue | Severity | Status |
|-----|----------|-------|----------|--------|
| GAP-1 | Task status update | Task execution succeeds but DB update fails | Already handled | Existing checkpoint logs |
| GAP-2 | Stage advancement | Stage advance fails after tasks complete | MEDIUM | Fixed - checkpoint added |
| GAP-3 | mark_job_failed() | Return value not checked | HIGH | Fixed - return check + checkpoint |
| GAP-4 | Retry logic | task_record None causes silent fall-through | HIGH | Fixed - explicit None handling |
| GAP-5 | Task result conversion | Result parsing fails | Already handled | try/except with logging |
| GAP-6 | Job finalization | Finalization errors | Design decision | Keep non-fatal (job already COMPLETED) |
| GAP-7 | Completion callback | Callback failure not tracked | MEDIUM | Fixed - checkpoint for callback status |

---

## Implementation Stories

### Story 1: Fix GAP-3 - Check mark_job_failed Return Value

**File**: `core/machine.py` ~line 1245
**Change**: Check return value and add checkpoint
**Status**: COMPLETE

### Story 2: Fix GAP-4 - Handle task_record None in Retry Logic

**File**: `core/machine.py` ~line 1350
**Change**: Add explicit early return with error checkpoint
**Status**: COMPLETE

### Story 3: Fix GAP-7 - Add Checkpoint for Callback Failure

**File**: `core/machine.py` ~line 2095
**Change**: Add checkpoint logging for callback success/failure
**Status**: COMPLETE

### Story 4: Add GAP-2 Checkpoint for Stage Advancement

**File**: `core/machine.py` ~line 1100
**Change**: Add checkpoint before and after stage advancement
**Status**: COMPLETE

---

## Pending: Job Events Table (Story 5)

**Status**: Waiting - complete gap fixes first

### Table Design

```sql
CREATE TABLE app.job_events (
    event_id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64),
    event_type VARCHAR(50) NOT NULL,  -- job_created, task_started, task_completed, etc.
    event_status VARCHAR(20),         -- success, failure, warning
    event_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_job FOREIGN KEY (job_id) REFERENCES app.jobs(job_id)
);
CREATE INDEX idx_job_events_job ON app.job_events(job_id);
CREATE INDEX idx_job_events_time ON app.job_events(created_at);
```

### Event Types

| Event Type | Description |
|------------|-------------|
| `job_created` | Job record created |
| `job_queued` | Message sent to Service Bus |
| `stage_started` | Stage X began processing |
| `task_started` | Task picked up by worker |
| `task_completed` | Task finished successfully |
| `task_failed` | Task failed |
| `stage_completed` | All tasks in stage done |
| `job_completed` | Job finalized |
| `job_failed` | Job failed |
| `callback_executed` | on_job_complete callback ran |

---

## Pending: Execution Timeline UI (Story 6)

**Status**: Waiting - complete events table first

### Requirements

- Visual timeline of job execution
- Show each event with timestamp
- Highlight failures/warnings
- Show "last successful step" for debugging
- Integrate with existing job detail page

### Mockup

```
Job: abc123 - process_raster_v2
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
10:00:00  ● job_created
10:00:01  ● job_queued
10:00:05  ● stage_started (stage 1)
10:00:06  ● task_started (task-001)
10:00:15  ● task_completed (task-001)
10:00:16  ● stage_completed (stage 1)
10:00:17  ● stage_started (stage 2)
10:00:18  ● task_started (task-002)
10:01:45  ✗ task_failed (task-002)  ← ERROR HERE
10:01:46  ✗ job_failed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Last successful: task_started (task-002) at 10:00:18
```

---

## Key Files

| File | Purpose |
|------|---------|
| `core/machine.py` | CoreMachine with gap fixes |
| `core/schema/sql_generator.py` | DDL for job_events table (pending) |
| `web_interfaces/jobs/interface.py` | Job detail UI (pending timeline) |
