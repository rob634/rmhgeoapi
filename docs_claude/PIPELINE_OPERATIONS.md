# PIPELINE_OPERATIONS.md - Resilience Patterns for Long-Running Jobs

**Created**: 05 JAN 2026
**Status**: DESIGN PROPOSAL
**Context**: FATHOM ETL processing revealed failure modes when scaling from Rwanda (234 COGs) to Côte d'Ivoire (1924 COGs)

---

## Table of Contents

1. [Observed Failure Modes](#observed-failure-modes)
2. [Pattern 1: Database-as-Queue for Large Payloads](#pattern-1-database-as-queue-for-large-payloads)
3. [Pattern 2: Batched Fan-In](#pattern-2-batched-fan-in)
4. [Pattern 3: Task Health Monitoring](#pattern-3-task-health-monitoring)
5. [Pattern 4: Resumable Jobs](#pattern-4-resumable-jobs)
6. [Pattern 5: Graceful Degradation](#pattern-5-graceful-degradation)
7. [Implementation Priority Matrix](#implementation-priority-matrix)

---

## Observed Failure Modes

### Failure Mode 1: Service Bus 256KB Message Limit

**Observed**: 05 JAN 2026 during CIV processing

| Attribute | Value |
|-----------|-------|
| **Symptom** | Task stuck in `pending` status indefinitely |
| **Root Cause** | Task parameters contained 1924 COG results (1.09 MB) |
| **Service Bus Limit** | 256 KB per message |
| **Error Visibility** | Silent failure - no error in task record |
| **Log Evidence** | `Message exceeds 256KB limit` in Application Insights |

**Current Architecture Problem**:
```
Stage 2 completes → CoreMachine collects 1924 results → Creates Stage 3 task with all results in params → FAILS
```

**Why It's Silent**:
- Task is created in database (status: pending)
- Task is queued to Service Bus
- Service Bus rejects oversized message
- Task remains pending forever
- No callback to update task status

---

### Failure Mode 2: Stuck Pending Tasks

**Observed**: Tasks that fail to queue remain in `pending` status with no recovery path.

| Attribute | Value |
|-----------|-------|
| **Symptom** | Job shows 1925/1926 tasks complete, 1 pending forever |
| **Root Cause** | No timeout mechanism for pending tasks |
| **Janitor Behavior** | Attempts re-queue but hits same 256KB limit |
| **Recovery** | Manual intervention required |

**Current Janitor Logic**:
```python
# Janitor finds orphaned pending tasks and re-queues them
# But if the task params are too large, it fails again
for task in orphaned_pending_tasks:
    queue.send(task)  # Fails again with same error
```

---

### Failure Mode 3: Idempotency Blocking Retries

**Observed**: Cannot easily retry a failed job because idempotency returns cached result.

| Attribute | Value |
|-----------|-------|
| **Symptom** | `"status": "already_completed"` when trying to retry |
| **Root Cause** | Job ID is hash of parameters; same params = same job |
| **Workaround Used** | `cleanup?days=0` to delete job records |
| **Problem** | Deletes all job history, loses audit trail |

**Current Idempotency Logic**:
```python
job_id = sha256(job_type + canonical_params)
if job_exists(job_id) and job.status == 'completed':
    return cached_result  # No way to force retry
```

---

### Failure Mode 4: Fan-In Single Point of Failure

**Observed**: STAC registration is a single task that processes ALL items.

| Attribute | Value |
|-----------|-------|
| **Current Design** | 1 STAC task registers 1924 items sequentially |
| **Failure Impact** | If task fails at item 1900, all 1924 items need re-registration |
| **No Partial Progress** | Task either succeeds completely or fails completely |
| **Memory Risk** | Loading 1924 item definitions into memory |

**Current Fan-In Structure**:
```
Stage 2: 1924 parallel tasks (band_stack)
    ↓
Stage 3: 1 task (stac_register) ← Single point of failure
```

---

### Failure Mode 5: No Checkpointing

**Observed**: Stage completion is binary - no intermediate saves.

| Attribute | Value |
|-----------|-------|
| **Symptom** | Stage 2 completes, Stage 3 fails, no record of Stage 2 success |
| **Root Cause** | `stage_results` only populated on job completion |
| **Recovery** | Must re-query all Stage 2 tasks to rebuild state |

---

## Pattern 1: Database-as-Queue for Large Payloads

### Status: IMPLEMENTED (05 JAN 2026)

### Concept

Instead of passing large data in task parameters, pass a reference (job_id + stage) and have the handler query the database for the actual data.

### Implementation

**Job file change** (`jobs/process_fathom_stack.py`):
```python
# BEFORE: Pass all results in params (can exceed 256KB)
return [{
    "task_id": f"{job_id[:8]}-s3-stac",
    "task_type": "fathom_stac_register",
    "parameters": {
        "cog_results": successful_cogs,  # 1.09 MB for CIV!
        ...
    }
}]

# AFTER: Pass reference, handler queries DB
return [{
    "task_id": f"{job_id[:8]}-s3-stac",
    "task_type": "fathom_stac_register",
    "parameters": {
        "job_id": job_id,           # 64 bytes
        "stage": 2,                  # 4 bytes
        "cog_count": len(successful_cogs),  # For validation
        ...
    }
}]
```

**Handler change** (`services/fathom_etl.py`):
```python
if "job_id" in params and "cog_results" not in params:
    # Query database for Stage 2 task results
    job_repo = JobRepository()
    tasks = job_repo.get_tasks_for_job(params["job_id"])

    cog_results = [
        task.result_data.get("result")
        for task in tasks
        if task.stage == params["stage"]
        and task.status.value == "completed"
        and task.result_data
    ]
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **No size limit** | Task params stay under 1KB regardless of COG count |
| **Retry-safe** | Re-querying DB always gets latest state |
| **Audit trail** | Results remain in task records |

### Limitations

| Limitation | Description |
|------------|-------------|
| **DB dependency** | Handler must have DB access |
| **Query overhead** | Additional DB query at task start |
| **Not for all patterns** | Only works when previous stage results are in DB |

### Files Modified

- `jobs/process_fathom_stack.py` (lines 250-263)
- `jobs/process_fathom_merge.py` (lines 242-255)
- `services/fathom_etl.py` (lines 1241-1265)

---

## Pattern 2: Batched Fan-In

### Status: NOT IMPLEMENTED

### Concept

Instead of a single fan-in task that processes all items, create multiple smaller fan-in tasks that each process a batch, followed by a final aggregation task.

### Current Architecture (Single Fan-In)

```
Stage 2: 1924 tasks (parallel)
         ↓ all results
Stage 3: 1 task (processes all 1924 items)
```

**Problems**:
- Single point of failure
- Memory pressure (all items in memory)
- Long-running task vulnerable to timeouts
- No partial progress

### Proposed Architecture (Batched Fan-In)

```
Stage 2: 1924 tasks (parallel)
         ↓ partitioned
Stage 3: 20 tasks (each processes ~100 items) ← Parallel batch processing
         ↓ aggregated
Stage 4: 1 task (aggregates batch results) ← Lightweight aggregation
```

### Implementation Options

#### Option A: Static Batching in Job Definition

```python
# In create_tasks_for_stage for Stage 3
BATCH_SIZE = 100

batches = [
    successful_cogs[i:i + BATCH_SIZE]
    for i in range(0, len(successful_cogs), BATCH_SIZE)
]

return [
    {
        "task_id": f"{job_id[:8]}-s3-batch-{i}",
        "task_type": "fathom_stac_register_batch",
        "parameters": {
            "batch_index": i,
            "job_id": job_id,
            "stage": 2,
            "offset": i * BATCH_SIZE,
            "limit": BATCH_SIZE,
            ...
        }
    }
    for i in range(len(batches))
]
```

#### Option B: Dynamic Batching Based on Count

```python
def calculate_batch_count(item_count: int) -> int:
    """Determine number of batches based on item count."""
    if item_count <= 100:
        return 1  # Single task OK for small sets
    elif item_count <= 500:
        return 5  # 100 items per batch
    elif item_count <= 2000:
        return 20  # 100 items per batch
    else:
        return item_count // 100 + 1  # Scale linearly
```

#### Option C: Hybrid - Batch STAC Creation, Single Collection

```python
# Stage 3a: Create STAC items in batches (parallel)
# Each batch task creates items and returns count

# Stage 3b: Single task to:
#   - Verify all items created
#   - Update collection metadata (bounds, item count)
#   - Create collection-level statistics
```

### Handler Changes Required

**New handler**: `fathom_stac_register_batch`
```python
def fathom_stac_register_batch(params: dict, context: dict = None) -> dict:
    """Register a batch of STAC items."""
    job_id = params["job_id"]
    offset = params["offset"]
    limit = params["limit"]

    # Query only this batch's worth of results
    job_repo = JobRepository()
    tasks = job_repo.get_tasks_for_job(
        job_id,
        stage=2,
        offset=offset,
        limit=limit
    )

    # Process batch
    items_created = 0
    for task in tasks:
        result = task.result_data.get("result")
        if result:
            create_stac_item(result)
            items_created += 1

    return {
        "success": True,
        "result": {
            "batch_index": params["batch_index"],
            "items_created": items_created,
            "offset": offset
        }
    }
```

### Job Schema Changes

```python
# Current: 3 stages
stages = [
    {"number": 1, "name": "inventory", ...},
    {"number": 2, "name": "band_stack", "parallelism": "fan_out"},
    {"number": 3, "name": "stac_register", "parallelism": "fan_in"},
]

# Proposed: 4 stages
stages = [
    {"number": 1, "name": "inventory", ...},
    {"number": 2, "name": "band_stack", "parallelism": "fan_out"},
    {"number": 3, "name": "stac_register_batch", "parallelism": "fan_out"},  # NEW
    {"number": 4, "name": "stac_finalize", "parallelism": "fan_in"},  # NEW
]
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Parallel STAC creation** | 20 tasks vs 1 = ~20x faster |
| **Fault isolation** | Batch 15 fails, batches 1-14 and 16-20 succeed |
| **Resumable** | Only retry failed batches |
| **Memory bounded** | Each task handles ~100 items |
| **Progress visibility** | Can see 15/20 batches complete |

### Limitations

| Limitation | Description |
|------------|-------------|
| **Added complexity** | Extra stage, new handler |
| **Collection timing** | Collection must exist before batch items |
| **Aggregation logic** | Need to merge batch results |

### Estimated Effort

- Job schema changes: 2 hours
- New batch handler: 4 hours
- Aggregation handler: 2 hours
- Testing: 4 hours
- **Total**: ~12 hours

---

## Pattern 3: Task Health Monitoring

### Status: PARTIALLY IMPLEMENTED (Janitor exists but limited)

### Concept

Proactive detection and recovery of stuck, failed, or orphaned tasks through enhanced monitoring and automatic remediation.

### Current Janitor Capabilities

```python
# Current janitor checks (runs every 5 minutes):
1. Find tasks with status='processing' and no heartbeat for 10 minutes → Mark failed
2. Find tasks with status='pending' and created > 5 minutes ago → Re-queue
3. Find jobs with status='processing' but no active tasks → Check completion
```

### Current Janitor Limitations

| Limitation | Impact |
|------------|--------|
| **Re-queue fails for large tasks** | 256KB limit causes infinite retry loop |
| **No root cause detection** | Keeps retrying same failing operation |
| **No alerting** | Silent failures require manual log checking |
| **No job-level timeout** | Jobs can run indefinitely |

### Proposed Enhancements

#### Enhancement 3.1: Intelligent Re-Queue with Size Check

```python
def requeue_pending_task(task: Task) -> bool:
    """Re-queue a pending task with size validation."""
    params_size = len(json.dumps(task.parameters))

    if params_size > 200_000:  # 200KB threshold (below 256KB limit)
        logger.error(
            f"Task {task.task_id} params too large ({params_size} bytes). "
            "Marking as failed - requires code fix."
        )
        task.status = TaskStatus.FAILED
        task.error_details = f"Parameters exceed queue limit: {params_size} bytes"
        return False

    return queue.send(task)
```

#### Enhancement 3.2: Retry Budget

```python
# Add retry tracking to task
class Task:
    retry_count: int = 0
    max_retries: int = 3
    last_retry_at: datetime = None

# Janitor respects retry budget
def should_retry_task(task: Task) -> bool:
    if task.retry_count >= task.max_retries:
        logger.error(f"Task {task.task_id} exceeded retry budget ({task.max_retries})")
        mark_task_failed(task, "Exceeded retry budget")
        return False
    return True
```

#### Enhancement 3.3: Job-Level Timeout

```python
# Add timeout tracking to job
class Job:
    created_at: datetime
    timeout_minutes: int = 120  # Default 2 hours

def check_job_timeout(job: Job) -> bool:
    elapsed = datetime.now() - job.created_at
    if elapsed.total_seconds() > job.timeout_minutes * 60:
        logger.error(f"Job {job.job_id} exceeded timeout ({job.timeout_minutes} min)")
        mark_job_failed(job, "Job timeout exceeded")
        return True
    return False
```

#### Enhancement 3.4: Stuck Task Detection Heuristics

```python
def detect_stuck_task(task: Task) -> Optional[str]:
    """Detect various stuck task conditions."""

    # Condition 1: Pending too long with queue errors
    if task.status == 'pending':
        queue_errors = get_queue_errors_for_task(task.task_id)
        if len(queue_errors) >= 3:
            return "QUEUE_REJECTION"

    # Condition 2: Processing without heartbeat
    if task.status == 'processing':
        if task.heartbeat is None or (now() - task.heartbeat) > timedelta(minutes=10):
            return "HEARTBEAT_TIMEOUT"

    # Condition 3: Completed but job still processing
    if task.status == 'completed':
        job = get_job(task.parent_job_id)
        if job.status == 'processing' and all_tasks_complete(job):
            return "STAGE_TRANSITION_STUCK"

    return None
```

#### Enhancement 3.5: Alerting Integration

```python
def janitor_alert(severity: str, message: str, context: dict):
    """Send alert for janitor-detected issues."""

    # Log to Application Insights with custom dimension
    logger.log(
        level=severity,
        message=f"[JANITOR_ALERT] {message}",
        extra={
            "customDimensions": {
                "alert_type": "janitor",
                "severity": severity,
                **context
            }
        }
    )

    # Future: Send to Azure Monitor, PagerDuty, Slack, etc.
```

### Proposed Janitor Run Logic

```python
def janitor_run():
    """Enhanced janitor with comprehensive health checks."""

    # 1. Check for jobs exceeding timeout
    for job in get_processing_jobs():
        if check_job_timeout(job):
            janitor_alert("ERROR", f"Job timeout: {job.job_id}", {"job_type": job.job_type})

    # 2. Check for stuck pending tasks
    for task in get_pending_tasks(older_than_minutes=5):
        stuck_reason = detect_stuck_task(task)
        if stuck_reason == "QUEUE_REJECTION":
            mark_task_failed(task, "Queue rejection - params too large")
            janitor_alert("ERROR", f"Task queue rejection: {task.task_id}", {})
        elif should_retry_task(task):
            if requeue_pending_task(task):
                task.retry_count += 1

    # 3. Check for orphaned processing tasks
    for task in get_processing_tasks(no_heartbeat_minutes=10):
        mark_task_failed(task, "Heartbeat timeout")
        janitor_alert("WARNING", f"Task heartbeat timeout: {task.task_id}", {})

    # 4. Check for stage transition issues
    for job in get_processing_jobs():
        if all_stage_tasks_complete(job) and job.stage < job.total_stages:
            trigger_stage_transition(job)
            janitor_alert("INFO", f"Triggered stuck stage transition: {job.job_id}", {})
```

### Database Schema Additions

```sql
-- Add to tasks table
ALTER TABLE app.tasks ADD COLUMN max_retries INTEGER DEFAULT 3;
ALTER TABLE app.tasks ADD COLUMN last_retry_at TIMESTAMP;

-- Add to jobs table
ALTER TABLE app.jobs ADD COLUMN timeout_minutes INTEGER DEFAULT 120;

-- Add janitor tracking table
CREATE TABLE app.janitor_actions (
    id SERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    action_type VARCHAR(50) NOT NULL,  -- 'requeue', 'mark_failed', 'trigger_transition'
    target_type VARCHAR(20) NOT NULL,  -- 'task' or 'job'
    target_id VARCHAR(64) NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Auto-recovery** | Most stuck tasks recovered automatically |
| **Visibility** | Clear alerts for issues requiring attention |
| **Bounded retries** | No infinite retry loops |
| **Audit trail** | All janitor actions logged |

### Estimated Effort

- Size check enhancement: 1 hour
- Retry budget: 2 hours
- Job timeout: 2 hours
- Stuck detection: 3 hours
- Alerting: 2 hours
- Schema changes: 1 hour
- Testing: 4 hours
- **Total**: ~15 hours

---

## Pattern 4: Resumable Jobs

### Status: NOT IMPLEMENTED

### Concept

Allow jobs that fail mid-execution to be resumed from the last successful stage, preserving completed work and avoiding re-processing.

### Current Behavior

```
Job fails at Stage 3
    ↓
User resubmits job
    ↓
Idempotency check: "Job already exists with status: failed"
    ↓
Options:
  A) Add force_reprocess=true → Creates NEW job ID, re-runs Stage 1 & 2
  B) Delete job record → Loses all history, re-runs everything
```

### Proposed Behavior

```
Job fails at Stage 3
    ↓
User resubmits job with resume=true
    ↓
System checks: Stage 1 ✓, Stage 2 ✓, Stage 3 ✗
    ↓
Job resumes from Stage 3 only
```

### Implementation Design

#### 4.1: Stage Checkpointing

```python
def complete_stage(job: Job, stage: int, results: dict):
    """Record stage completion with checkpoint data."""
    job.stage_results[str(stage)] = {
        "completed_at": datetime.now().isoformat(),
        "task_count": len(results),
        "success_count": len([r for r in results if r.get("success")]),
        "checkpoint": True
    }
    job.save()
```

#### 4.2: Resume Logic in Job Submission

```python
@app.route("/api/jobs/submit/<job_type>", methods=["POST"])
def submit_job(job_type: str):
    params = request.json
    resume = params.pop("resume", False)

    job_id = calculate_job_id(job_type, params)
    existing_job = get_job(job_id)

    if existing_job:
        if existing_job.status == "completed":
            return {"status": "already_completed", ...}

        if existing_job.status == "failed" and resume:
            return resume_failed_job(existing_job)

        if existing_job.status == "processing":
            return {"status": "already_processing", ...}

        if existing_job.status == "failed" and not resume:
            return {
                "status": "previously_failed",
                "message": "Job previously failed. Use resume=true to continue from last checkpoint.",
                "failed_stage": existing_job.stage,
                "completed_stages": list(existing_job.stage_results.keys())
            }

    # Create new job
    return create_new_job(job_type, params)
```

#### 4.3: Resume Failed Job Logic

```python
def resume_failed_job(job: Job) -> dict:
    """Resume a failed job from its last checkpoint."""

    # Find last completed stage
    completed_stages = [
        int(s) for s, data in job.stage_results.items()
        if data.get("checkpoint")
    ]
    last_completed_stage = max(completed_stages) if completed_stages else 0
    resume_from_stage = last_completed_stage + 1

    logger.info(f"Resuming job {job.job_id} from stage {resume_from_stage}")

    # Reset job state
    job.status = JobStatus.PROCESSING
    job.stage = resume_from_stage
    job.error_details = None
    job.metadata["resumed_at"] = datetime.now().isoformat()
    job.metadata["resume_count"] = job.metadata.get("resume_count", 0) + 1
    job.save()

    # Clear failed tasks for current stage
    clear_failed_tasks(job.job_id, stage=resume_from_stage)

    # Re-trigger stage
    if resume_from_stage == 1:
        # Queue initial task
        queue_initial_task(job)
    else:
        # Get previous stage results and create new stage tasks
        previous_results = get_stage_results(job.job_id, resume_from_stage - 1)
        create_tasks_for_stage(job, resume_from_stage, previous_results)

    return {
        "status": "resumed",
        "job_id": job.job_id,
        "resumed_from_stage": resume_from_stage,
        "resume_count": job.metadata["resume_count"]
    }
```

#### 4.4: Stage Results Retrieval

```python
def get_stage_results(job_id: str, stage: int) -> List[dict]:
    """Retrieve results from a completed stage."""
    tasks = job_repo.get_tasks_for_job(job_id)

    return [
        task.result_data
        for task in tasks
        if task.stage == stage and task.status.value == "completed"
    ]
```

### API Changes

```bash
# Current: Resubmit returns error for failed jobs
curl -X POST /api/jobs/submit/process_fathom_stack -d '{"region_code": "CIV"}'
# Response: {"status": "previously_failed", "message": "Use resume=true to continue"}

# New: Resume from checkpoint
curl -X POST /api/jobs/submit/process_fathom_stack -d '{"region_code": "CIV", "resume": true}'
# Response: {"status": "resumed", "resumed_from_stage": 3, ...}
```

### Job Status Response Enhancement

```json
{
  "jobId": "038ffc2d...",
  "status": "failed",
  "stage": 3,
  "totalStages": 3,
  "stageResults": {
    "1": {"completed_at": "2026-01-05T00:00:00Z", "checkpoint": true, "task_count": 1},
    "2": {"completed_at": "2026-01-05T00:20:00Z", "checkpoint": true, "task_count": 1924}
  },
  "resumable": true,
  "resume_from_stage": 3,
  "resume_hint": "POST /api/jobs/submit/process_fathom_stack with resume=true"
}
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **No rework** | Completed stages preserved |
| **Fast recovery** | Resume in seconds vs re-running hours |
| **Audit trail** | Resume history tracked |
| **User-friendly** | Clear guidance on how to resume |

### Limitations

| Limitation | Description |
|------------|-------------|
| **Stage boundary only** | Can't resume mid-stage |
| **Results must be in DB** | Pattern 1 is prerequisite |
| **Idempotency complexity** | Resume logic adds edge cases |

### Estimated Effort

- Stage checkpointing: 2 hours
- Resume submission logic: 4 hours
- Stage results retrieval: 2 hours
- API changes: 2 hours
- Testing: 6 hours
- **Total**: ~16 hours

---

## Pattern 5: Graceful Degradation

### Status: NOT IMPLEMENTED

### Concept

Separate job success into independent outcomes, allowing partial success and manual recovery paths for failed components.

### Current Behavior (All-or-Nothing)

```
Job: process_fathom_stack
  ↓
Stage 1: Inventory ✓
Stage 2: Band Stack ✓ (1924 COGs created in blob storage)
Stage 3: STAC Register ✗ (fails due to 256KB limit)
  ↓
Job Status: FAILED
  ↓
User sees: "Job failed"
Reality: 1924 COGs exist and are usable, just not in STAC catalog
```

### Proposed Behavior (Graceful Degradation)

```
Job: process_fathom_stack
  ↓
Stage 1: Inventory ✓
Stage 2: Band Stack ✓ (1924 COGs created)
Stage 3: STAC Register ✗
  ↓
Job Status: PARTIAL_SUCCESS
  ↓
User sees:
  - "Primary objective achieved: 1924 COGs created"
  - "Secondary objective failed: STAC registration"
  - "Manual recovery: POST /api/jobs/retry-stage/038ffc2d/3"
```

### Implementation Design

#### 5.1: Stage Classification

```python
class StageImportance(Enum):
    CRITICAL = "critical"      # Job fails if this stage fails
    IMPORTANT = "important"    # Job partially succeeds if this fails
    OPTIONAL = "optional"      # Job succeeds even if this fails

# In job definition
stages = [
    {
        "number": 1,
        "name": "inventory",
        "importance": StageImportance.CRITICAL,
        "description": "Must succeed - determines work scope"
    },
    {
        "number": 2,
        "name": "band_stack",
        "importance": StageImportance.CRITICAL,
        "description": "Primary deliverable - COG creation"
    },
    {
        "number": 3,
        "name": "stac_register",
        "importance": StageImportance.IMPORTANT,
        "description": "Secondary - catalog registration"
    }
]
```

#### 5.2: Partial Success Status

```python
class JobStatus(Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"  # NEW
    FAILED = "failed"
```

#### 5.3: Job Completion Logic

```python
def evaluate_job_completion(job: Job, failed_stage: int) -> JobStatus:
    """Determine job status based on which stage failed."""

    stage_def = job.get_stage_definition(failed_stage)
    importance = stage_def.get("importance", StageImportance.CRITICAL)

    if importance == StageImportance.CRITICAL:
        return JobStatus.FAILED

    elif importance == StageImportance.IMPORTANT:
        # Check if any critical stages succeeded
        critical_stages = [s for s in job.stages if s["importance"] == StageImportance.CRITICAL]
        critical_succeeded = all(
            str(s["number"]) in job.stage_results
            for s in critical_stages
        )

        if critical_succeeded:
            return JobStatus.PARTIAL_SUCCESS
        else:
            return JobStatus.FAILED

    elif importance == StageImportance.OPTIONAL:
        return JobStatus.COMPLETED  # Optional failure doesn't affect status
```

#### 5.4: Retry-Stage Endpoint

```python
@app.route("/api/jobs/retry-stage/<job_id>/<stage>", methods=["POST"])
def retry_stage(job_id: str, stage: int):
    """Retry a specific failed stage."""

    job = get_job(job_id)

    if job.status not in [JobStatus.FAILED, JobStatus.PARTIAL_SUCCESS]:
        return {"error": "Can only retry stages for failed/partial jobs"}

    if stage > job.stage:
        return {"error": f"Stage {stage} was never reached"}

    # Clear failed tasks for this stage
    clear_tasks(job_id, stage=stage)

    # Get previous stage results
    previous_results = get_stage_results(job_id, stage - 1) if stage > 1 else []

    # Create new tasks for this stage
    job.stage = stage
    job.status = JobStatus.PROCESSING
    job.error_details = None
    job.save()

    create_tasks_for_stage(job, stage, previous_results)

    return {
        "status": "stage_retry_initiated",
        "job_id": job_id,
        "stage": stage,
        "message": f"Stage {stage} tasks created and queued"
    }
```

#### 5.5: Enhanced Job Status Response

```json
{
  "jobId": "038ffc2d...",
  "status": "partial_success",
  "stage": 3,
  "totalStages": 3,
  "outcomes": {
    "primary": {
      "description": "COG creation",
      "status": "success",
      "details": "1924 COGs created in silver-fathom container"
    },
    "secondary": {
      "description": "STAC registration",
      "status": "failed",
      "error": "Task params exceeded queue limit",
      "recovery": "POST /api/jobs/retry-stage/038ffc2d/3"
    }
  },
  "deliverables": {
    "cogs": {
      "count": 1924,
      "location": "silver-fathom/fathom-stacked/civ/",
      "usable": true
    },
    "stac_items": {
      "count": 0,
      "collection": "fathom-flood-stacked-civ",
      "usable": false
    }
  }
}
```

### Manual Recovery Paths

#### Recovery Path A: Retry via API

```bash
# Retry just the STAC registration stage
curl -X POST /api/jobs/retry-stage/038ffc2d.../3
```

#### Recovery Path B: Manual STAC Registration

```bash
# Get COG list from completed Stage 2 tasks
curl /api/dbadmin/tasks/038ffc2d...?stage=2 > cog_results.json

# Submit standalone STAC registration job
curl -X POST /api/jobs/submit/stac_register_manual -d @cog_results.json
```

#### Recovery Path C: Direct Database Fix

```sql
-- If code is fixed, manually queue the stage 3 task
UPDATE app.tasks
SET status = 'pending', error_details = NULL, retry_count = 0
WHERE parent_job_id = '038ffc2d...' AND stage = 3;

-- Reset job to processing
UPDATE app.jobs
SET status = 'processing', error_details = NULL
WHERE job_id = '038ffc2d...';
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Preserves value** | Completed work is recognized |
| **Clear recovery paths** | User knows how to fix partial failures |
| **Reduced anxiety** | "Partial success" better than "failed" |
| **Operational flexibility** | Can fix issues without re-running everything |

### Limitations

| Limitation | Description |
|------------|-------------|
| **Complexity** | More status states to handle |
| **Stage classification** | Must correctly classify importance |
| **Testing burden** | More paths to test |

### Estimated Effort

- Stage classification: 2 hours
- Partial success logic: 3 hours
- Retry-stage endpoint: 3 hours
- Status response enhancement: 2 hours
- Testing: 6 hours
- **Total**: ~16 hours

---

## Implementation Priority Matrix

### Prioritization Criteria

| Criterion | Weight | Description |
|-----------|--------|-------------|
| **Impact** | 40% | How much does this improve reliability? |
| **Effort** | 30% | How long to implement? |
| **Risk** | 20% | Could this break existing functionality? |
| **Dependencies** | 10% | Does it require other patterns first? |

### Priority Scores

| Pattern | Impact | Effort | Risk | Deps | Score | Priority |
|---------|--------|--------|------|------|-------|----------|
| **1. DB-as-Queue** | 10 | 10 | 2 | 0 | 8.4 | ✅ DONE |
| **3. Health Monitoring** | 8 | 6 | 3 | 0 | 6.3 | **HIGH** |
| **4. Resumable Jobs** | 9 | 5 | 4 | 1 | 5.9 | **HIGH** |
| **2. Batched Fan-In** | 7 | 5 | 5 | 1 | 5.1 | MEDIUM |
| **5. Graceful Degradation** | 6 | 5 | 4 | 4 | 4.5 | MEDIUM |

### Recommended Implementation Order

```
Phase 1 (Immediate - This Week):
├── Pattern 1: Database-as-Queue ✅ COMPLETE
└── Pattern 3.1: Size check in janitor (1 hour)

Phase 2 (Short-term - Next 2 Weeks):
├── Pattern 3: Full health monitoring (15 hours)
└── Pattern 4: Resumable jobs (16 hours)

Phase 3 (Medium-term - Next Month):
├── Pattern 2: Batched fan-in (12 hours)
└── Pattern 5: Graceful degradation (16 hours)
```

### Quick Wins (< 2 Hours Each)

1. **Add size check before queue** - Prevent silent 256KB failures
2. **Add retry budget column** - Prevent infinite retry loops
3. **Add job timeout column** - Prevent jobs running forever
4. **Log queue failures loudly** - Make failures visible in Application Insights

---

## Appendix: Current CIV Job Recovery

### Immediate Recovery Steps

The CIV job (038ffc2d...) is stuck with a Stage 3 task that has old-format params. Options:

#### Option A: Delete and Recreate Task

```sql
-- Delete the stuck task
DELETE FROM app.tasks WHERE task_id = '8d471f99635793f6';

-- Reset job to trigger new task creation
UPDATE app.jobs
SET stage = 2, status = 'processing'
WHERE job_id = '038ffc2d537986c903ce8d4c5cec106b26a515d4e0398c9b22b1438c0e78e594';

-- The CoreMachine will detect stage 2 complete and create new Stage 3 task
```

#### Option B: Update Task Params Directly

```sql
-- Update task params to use new format
UPDATE app.tasks
SET parameters = jsonb_build_object(
    'job_id', '038ffc2d537986c903ce8d4c5cec106b26a515d4e0398c9b22b1438c0e78e594',
    'stage', 2,
    'cog_count', 1924,
    'region_code', 'CIV',
    'collection_id', 'fathom-flood-stacked',
    'output_container', 'silver-fathom'
),
status = 'pending',
error_details = NULL
WHERE task_id = '8d471f99635793f6';
```

#### Option C: Manual STAC Registration

```bash
# Query Stage 2 results and register STAC items manually
# This bypasses the job system entirely
```

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 05 JAN 2026 | Claude | Initial creation based on CIV failure analysis |
