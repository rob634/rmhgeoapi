# CoreMachine Job Status Transition Fix

**Date**: 21 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: 🚧 IN PROGRESS - Changes Not Yet Applied

## Problem Summary

Multi-stage jobs have a critical bug in status transition logic that causes:
1. Schema validation errors (`PROCESSING → PROCESSING` attempted)
2. Silent exception swallowing (errors logged as warnings but execution continues)
3. Service Bus message redelivery (duplicate task processing)
4. Inconsistent database state (tasks have result_data but status=processing)

## Root Cause Analysis

### Current (Broken) Flow:

```
Stage 1 Starts:
  - Job status: QUEUED → PROCESSING ✅ (correct)
  - Tasks execute

Stage 1 Completes:
  - Last task completes
  - _handle_stage_completion() called
  - _advance_stage() called
  - Job status: stays PROCESSING ❌ (WRONG - should go to QUEUED)
  - JobQueueMessage sent to geospatial-jobs queue

Stage 2 Message Processed:
  - process_job_message() triggered
  - Tries to update: PROCESSING → PROCESSING ❌ (FAILS validation)
  - Exception caught and logged as warning ❌ (silently swallowed)
  - Execution continues anyway
  - Tasks created and queued
  - Azure Function may not complete cleanly → Service Bus redelivery
```

### Evidence from Testing:

**Test Job**: `list_container_contents` (2-stage job)
**Job ID**: `71969d412128521bf37ef4141d605376140ae3f12ba6d5647ab9a2decfb779bf`

**Timeline**:
- `19:53:53.335` - Stage 1 complete
- `19:53:53.474` - _advance_stage() called, sends Stage 2 message
- `19:53:53.479` - Stage 2 message received by process_job_message()
- `19:53:53.733` - **ERROR**: `Invalid status transition: JobStatus.PROCESSING → JobStatus.PROCESSING`
- `19:53:53.984` - Stage 2 tasks start processing (error was swallowed)
- `19:53:54.954` - Stage 2 completes
- **Result**: Job completed successfully DESPITE the error

**Log Evidence**:
```
❌ Status transition validation failed: Schema validation error in field 'status_transition':
   Status transition validation failed for JobRecord:
   Invalid status transition: JobStatus.PROCESSING → JobStatus.PROCESSING
```

## Expected (Correct) Flow:

```
PROCESSING = Tasks are actively executing
QUEUED = Waiting for tasks to begin (job message queued, ready to create tasks)

Stage 1 Starts:
  - Job message received from queue
  - Job status: QUEUED → PROCESSING ✅
  - Tasks created and queued
  - Tasks execute

Stage 1 Completes:
  - Last task completes
  - _handle_stage_completion() called
  - _advance_stage() called
  - Job status: PROCESSING → QUEUED ✅ (NEW - missing step!)
  - JobQueueMessage sent to geospatial-jobs queue

Stage 2 Message Processed:
  - process_job_message() triggered
  - Job status: QUEUED → PROCESSING ✅ (clean transition)
  - Tasks created and queued
  - Tasks execute

Stage 2 Completes:
  - Job status: PROCESSING → COMPLETED ✅
```

## Code Changes Required

### 1. Fix `_advance_stage()` - Add Missing Status Update

**File**: `core/machine.py`
**Line**: 908
**Current Code**:
```python
def _advance_stage(self, job_id: str, job_type: str, next_stage: int):
    """Queue next stage job message."""
    try:
        # Get job record for parameters
        repos = RepositoryFactory.create_repositories()
        job_record = repos['job_repo'].get_job(job_id)

        # Create job message for next stage
        next_message = JobQueueMessage(...)

        # Send to job queue
        service_bus_repo.send_message(
            self.config.job_processing_queue,
            next_message
        )
```

**Fixed Code**:
```python
def _advance_stage(self, job_id: str, job_type: str, next_stage: int):
    """Queue next stage job message."""
    try:
        # Get job record for parameters
        repos = RepositoryFactory.create_repositories()
        job_record = repos['job_repo'].get_job(job_id)

        # Update job status to QUEUED before queuing next stage message
        # This ensures process_job_message() finds QUEUED status and can do clean QUEUED → PROCESSING transition
        self.state_manager.update_job_status(job_id, JobStatus.QUEUED)
        self.logger.info(f"✅ Job {job_id[:16]} status → QUEUED (ready for stage {next_stage})")

        # Create job message for next stage
        next_message = JobQueueMessage(...)

        # Send to job queue
        service_bus_repo.send_message(
            self.config.job_processing_queue,
            next_message
        )
```

### 2. Remove Silent Exception Swallowing

**File**: `core/machine.py`
**Line**: 220-230
**Current Code**:
```python
# Step 3: Update job status to PROCESSING
try:
    self.logger.debug(f"📝 COREMACHINE STEP 4: Updating job status to PROCESSING...")
    self.state_manager.update_job_status(
        job_message.job_id,
        JobStatus.PROCESSING
    )
    self.logger.info(f"✅ COREMACHINE STEP 4: Job status updated to PROCESSING")
except Exception as e:
    self.logger.warning(f"⚠️ COREMACHINE STEP 4 WARNING: Failed to update job status: {e}")
    # Continue - not critical  ❌ WRONG - schema validation errors ARE critical!
```

**Fixed Code**:
```python
# Step 3: Update job status to PROCESSING
# After fix #1, this will always find job in QUEUED status (clean transition)
self.logger.debug(f"📝 COREMACHINE STEP 4: Updating job status to PROCESSING...")
self.state_manager.update_job_status(
    job_message.job_id,
    JobStatus.PROCESSING
)
self.logger.info(f"✅ COREMACHINE STEP 4: Job status updated to PROCESSING")
# Note: No try/except - if this fails, the function SHOULD crash
# Schema validation errors are critical and must not be silently swallowed
```

## Why This Matters

### 1. **Schema Validation Errors Are Critical**
If a status transition fails validation, it indicates a bug in the workflow logic. These errors must cause the function to fail so we can identify and fix them, not continue execution.

### 2. **Service Bus Message Acknowledgement**
When Azure Functions don't complete cleanly (due to exceptions), Service Bus messages aren't properly acknowledged and get redelivered after the visibility timeout (default 5 minutes), causing:
- Duplicate task processing
- Race conditions
- Wasted compute resources
- Inconsistent database state

### 3. **Proper State Machine Semantics**
- `QUEUED` = Job message is queued, waiting for orchestration
- `PROCESSING` = Tasks are actively executing
- The transition between stages should go through QUEUED state

## Validation Plan

After implementing fixes:

1. **Redeploy schema** to clear existing data
2. **Submit multi-stage job** (list_container_contents)
3. **Monitor Application Insights** for:
   - No `PROCESSING → PROCESSING` errors
   - Clean `PROCESSING → QUEUED → PROCESSING` transitions
   - No schema validation errors
4. **Verify database state**:
   - Job completes with status=completed
   - All tasks show status=completed
   - No tasks stuck in processing
5. **Check Service Bus**:
   - No message redelivery
   - Clean message acknowledgement
   - No poison queue messages

## Related Issues

This fix addresses the root cause of:
- Issue observed in `process_raster_collection` job where Stage 2 tasks got stuck
- Duplicate task processing (tasks processed 2+ times with 3-5 minute gaps)
- Tasks with result_data but status still showing "processing"
- Service Bus message redelivery causing duplicate work

## References

- **Job Status Transitions Already Allowed**: `core/models/job.py` line 118-119 already allows `PROCESSING → QUEUED` for stage advancement
- **Architecture Design**: Multi-stage jobs documented in `docs_claude/ARCHITECTURE_REFERENCE.md`
- **Test Evidence**: Application Insights logs from job `71969d412128521b...` on 21 OCT 2025 19:53:53 UTC

## Status

- [x] Problem identified and root cause analyzed
- [x] Solution designed and documented
- [x] Changes implemented in code
- [x] Tests passed with clean status transitions
- [x] Documentation updated
- [x] Changes committed to git

---

## Validation Results (21 OCT 2025 20:25 UTC)

**Test Job**: `list_container_contents` (2-stage workflow)
- Job ID: `0dee3b56db16f574c78a27da7a2b18e5f2116cf93310d24d86bd82ca799761d5`
- Container: `rmhazuregeosilver`

**Status Transition Timeline**:
1. **20:24:59.650** - Stage 1 starts: Status → PROCESSING ✅
2. **20:25:01.102** - Stage 1 completes: Status → QUEUED ✅ (Fix working!)
3. **20:25:01.104** - Log: "Job 0dee3b56 status → QUEUED (ready for stage 2)" ✅
4. **20:25:01.393** - Stage 2 starts: Status → PROCESSING ✅
5. **20:25:03.048** - Job completes ✅

**Validation Checks**:
- ✅ No "Invalid status transition: PROCESSING → PROCESSING" errors
- ✅ Clean PROCESSING → QUEUED → PROCESSING cycle between stages
- ✅ New log message confirms QUEUED state before next stage
- ✅ ~300ms gap between QUEUED and next PROCESSING (normal queue processing time)
- ✅ No Service Bus message redelivery
- ✅ Job completed successfully (despite unrelated aggregation error in controller)

**Conclusion**: Both fixes working as designed. CoreMachine framework now correctly handles multi-stage job status transitions.
