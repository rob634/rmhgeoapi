# Batch Coordination Strategy: Database + Service Bus

**Date**: 25 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Critical Question**: How do we coordinate batch DB inserts with batch queue sends?

## 🎯 The Coordination Problem

When creating 10,000 tasks:
1. We need ALL tasks in the database (for status tracking)
2. We need ALL tasks in Service Bus (for processing)
3. If either fails, we need to handle partial success gracefully

## 🔄 Coordination Patterns

### Pattern 1: Two-Phase Commit (Recommended)

```python
def create_stage_tasks_with_coordination(
    self,
    job_id: str,
    stage: int,
    task_definitions: List[TaskDefinition]
) -> Dict[str, Any]:
    """
    Coordinate batch database insert with batch queue send.
    Uses two-phase commit pattern for consistency.
    """

    # Phase 1: Batch insert to database with 'pending_queue' status
    logger.info(f"Phase 1: Inserting {len(task_definitions)} tasks to database")

    try:
        # Batch insert with special status
        task_records = task_repo.batch_create_tasks(
            task_definitions,
            initial_status='pending_queue'  # NOT 'queued' yet!
        )
        task_ids = [t.task_id for t in task_records]
        logger.info(f"✅ Database insert successful: {len(task_ids)} tasks")

    except DatabaseError as e:
        logger.error(f"❌ Database batch insert failed: {e}")
        # Nothing to roll back - operation failed atomically
        raise

    # Phase 2: Batch send to Service Bus
    logger.info(f"Phase 2: Sending {len(task_definitions)} messages to Service Bus")

    try:
        # Convert to queue messages
        task_messages = [td.to_queue_message() for td in task_definitions]

        # Batch send
        if len(task_messages) > 100:  # Use batch for large sets
            result = service_bus_repo.batch_send_messages(
                queue_name="sb-tasks",
                messages=task_messages,
                batch_size=100
            )

            if not result.success:
                raise ServiceBusError(f"Batch send failed: {result.errors}")

            logger.info(f"✅ Service Bus batch send successful: {result.messages_sent} messages")
        else:
            # Small batch - send individually
            for msg in task_messages:
                service_bus_repo.send_message("sb-tasks", msg)

    except ServiceBusError as e:
        logger.error(f"⚠️ Service Bus send failed after database insert: {e}")

        # CRITICAL: Tasks are in DB but not in queue!
        # Mark them for retry processing
        task_repo.mark_tasks_for_retry(
            task_ids,
            error_reason=f"Queue send failed: {e}"
        )

        # Don't fail the job - let retry process handle it
        return {
            'status': 'partial_success',
            'database_tasks': len(task_ids),
            'queued_tasks': 0,
            'retry_needed': True,
            'error': str(e)
        }

    # Phase 3: Update database status to 'queued'
    logger.info(f"Phase 3: Updating task status to 'queued'")

    try:
        updated_count = task_repo.batch_update_status(
            task_ids,
            new_status='queued',
            queued_at=datetime.now(timezone.utc)
        )
        logger.info(f"✅ Status update successful: {updated_count} tasks marked as queued")

        return {
            'status': 'success',
            'database_tasks': len(task_ids),
            'queued_tasks': len(task_ids),
            'retry_needed': False
        }

    except DatabaseError as e:
        # This is okay - tasks are queued and will process
        # Status will be updated when they complete
        logger.warning(f"Status update failed but tasks are queued: {e}")

        return {
            'status': 'success_with_warning',
            'database_tasks': len(task_ids),
            'queued_tasks': len(task_ids),
            'warning': 'Status update failed but tasks will process'
        }
```

### Pattern 2: Batch Checkpointing (For Very Large Batches)

```python
def create_stage_tasks_with_checkpoints(
    self,
    job_id: str,
    stage: int,
    task_definitions: List[TaskDefinition],
    checkpoint_size: int = 1000
) -> Dict[str, Any]:
    """
    Process in checkpointed batches for resilience.
    Each checkpoint is independently committed.
    """

    total_tasks = len(task_definitions)
    successful_checkpoints = []
    failed_checkpoint = None

    # Process in checkpoint-sized chunks
    for i in range(0, total_tasks, checkpoint_size):
        checkpoint_id = f"{job_id}-cp-{i//checkpoint_size}"
        chunk = task_definitions[i:i+checkpoint_size]

        logger.info(f"Processing checkpoint {checkpoint_id}: {len(chunk)} tasks")

        try:
            # Atomic operation per checkpoint
            with task_repo.transaction() as txn:
                # Insert chunk to database
                task_records = txn.batch_create_tasks(
                    chunk,
                    batch_id=checkpoint_id,
                    status='pending_queue'
                )

                # Send chunk to Service Bus
                messages = [td.to_queue_message() for td in chunk]
                result = service_bus_repo.batch_send_messages(
                    "sb-tasks",
                    messages
                )

                if not result.success:
                    txn.rollback()
                    raise ServiceBusError(f"Checkpoint {checkpoint_id} queue send failed")

                # Update status to queued
                task_ids = [t.task_id for t in task_records]
                txn.batch_update_status(task_ids, 'queued')

                # Commit checkpoint
                txn.commit()
                successful_checkpoints.append(checkpoint_id)

                logger.info(f"✅ Checkpoint {checkpoint_id} committed successfully")

        except Exception as e:
            logger.error(f"❌ Checkpoint {checkpoint_id} failed: {e}")
            failed_checkpoint = checkpoint_id

            # Stop processing on first failure
            # Previous checkpoints are committed and will process
            break

    # Report results
    successful_tasks = len(successful_checkpoints) * checkpoint_size

    if failed_checkpoint:
        return {
            'status': 'partial_success',
            'successful_checkpoints': successful_checkpoints,
            'failed_checkpoint': failed_checkpoint,
            'tasks_committed': successful_tasks,
            'tasks_failed': total_tasks - successful_tasks,
            'recovery_possible': True
        }
    else:
        return {
            'status': 'success',
            'checkpoints': successful_checkpoints,
            'tasks_committed': successful_tasks
        }
```

### Pattern 3: Optimistic Batching with Recovery

```python
def create_stage_tasks_optimistic(
    self,
    job_id: str,
    stage: int,
    task_definitions: List[TaskDefinition]
) -> Dict[str, Any]:
    """
    Optimistically batch both operations, with recovery on failure.
    Fastest pattern but requires careful error handling.
    """

    # Step 1: Batch database insert (fully committed)
    task_records = task_repo.batch_create_tasks(
        task_definitions,
        status='queued'  # Optimistic - assume queue will succeed
    )
    task_ids = [t.task_id for t in task_records]

    # Step 2: Batch queue send
    try:
        messages = [td.to_queue_message() for td in task_definitions]
        result = service_bus_repo.batch_send_messages("sb-tasks", messages)

        if result.success:
            return {'status': 'success', 'tasks': len(task_ids)}
        else:
            # Partial failure - some messages didn't send
            failed_indices = parse_failed_indices(result.errors)
            failed_task_ids = [task_ids[i] for i in failed_indices]

            # Mark failed tasks for retry
            task_repo.batch_update_status(
                failed_task_ids,
                status='pending_retry',
                error='Queue send failed'
            )

            return {
                'status': 'partial_success',
                'total_tasks': len(task_ids),
                'queued_tasks': len(task_ids) - len(failed_task_ids),
                'retry_tasks': len(failed_task_ids)
            }

    except ServiceBusError as e:
        # Complete failure - all tasks need recovery
        task_repo.batch_update_status(
            task_ids,
            status='pending_retry',
            error=f'Queue send failed: {e}'
        )

        # Schedule recovery job
        schedule_recovery_job(job_id, stage, task_ids)

        return {
            'status': 'failed_needs_recovery',
            'tasks_in_database': len(task_ids),
            'recovery_scheduled': True
        }
```

## 📊 Status Tracking Strategy

### Database Schema Updates

```sql
-- Add coordination tracking columns
ALTER TABLE tasks ADD COLUMN batch_id UUID;
ALTER TABLE tasks ADD COLUMN batch_status VARCHAR(20);
-- Values: 'pending_queue', 'queued', 'pending_retry', 'processing', 'completed', 'failed'

ALTER TABLE tasks ADD COLUMN queue_attempt_count INT DEFAULT 0;
ALTER TABLE tasks ADD COLUMN last_queue_error TEXT;
ALTER TABLE tasks ADD COLUMN queued_at TIMESTAMP;

-- Index for batch operations
CREATE INDEX idx_tasks_batch_status ON tasks(batch_id, batch_status);
CREATE INDEX idx_tasks_pending_retry ON tasks(batch_status) WHERE batch_status = 'pending_retry';
```

### Task Status Lifecycle

```
NEW TASK
    ↓
[pending_queue] ← Database insert
    ↓
[queued] ← Successful queue send
    ↓
[processing] ← Worker picks up task
    ↓
[completed/failed] ← Final state

OR if queue fails:

[pending_queue] ← Database insert
    ↓
[pending_retry] ← Queue send failed
    ↓
[queued] ← Retry successful
    ↓
[processing] → [completed/failed]
```

## 🔧 Recovery Mechanisms

### Background Retry Job

```python
@app.timer_trigger(schedule="0 */5 * * * *")  # Every 5 minutes
def retry_pending_tasks(context: func.TimerRequest) -> None:
    """
    Find and retry tasks that failed to queue.
    """

    # Find tasks stuck in pending_retry
    pending_tasks = task_repo.get_tasks_by_status(
        status='pending_retry',
        max_age_minutes=30,  # Don't retry very old failures
        limit=1000
    )

    if not pending_tasks:
        return

    logger.info(f"Found {len(pending_tasks)} tasks to retry")

    # Group by job for efficient batching
    tasks_by_job = group_by_job(pending_tasks)

    for job_id, tasks in tasks_by_job.items():
        # Convert back to queue messages
        messages = [
            TaskQueueMessage(
                task_id=t.task_id,
                parent_job_id=t.parent_job_id,
                task_type=t.task_type,
                parameters=t.parameters,
                stage=t.stage_number
            )
            for t in tasks
        ]

        # Try batch send
        try:
            result = service_bus_repo.batch_send_messages(
                "sb-tasks",
                messages
            )

            if result.success:
                # Update status to queued
                task_ids = [t.task_id for t in tasks]
                task_repo.batch_update_status(
                    task_ids,
                    status='queued',
                    queue_attempt_count=F('queue_attempt_count') + 1
                )

                logger.info(f"✅ Retried {len(tasks)} tasks for job {job_id}")
            else:
                # Update error info
                task_repo.update_queue_error(
                    [t.task_id for t in tasks],
                    error=str(result.errors),
                    attempt_count=F('queue_attempt_count') + 1
                )

        except Exception as e:
            logger.error(f"Retry failed for job {job_id}: {e}")

            # Mark tasks as failed after too many retries
            for task in tasks:
                if task.queue_attempt_count >= 3:
                    task_repo.update_status(
                        task.task_id,
                        status='failed',
                        error='Max queue retries exceeded'
                    )
```

## 🎯 Recommended Approach

### For Most Cases: Pattern 1 (Two-Phase Commit)

**Pros:**
- Clear separation between database and queue operations
- Easy to understand and debug
- Handles failures gracefully
- No orphaned messages in queue

**Cons:**
- Slightly slower (3 operations instead of 2)
- Tasks may be in database but not queue temporarily

### For Very Large Batches (>10,000 tasks): Pattern 2 (Checkpointing)

**Pros:**
- Resilient to failures
- Can resume from last checkpoint
- Memory efficient
- Progress tracking

**Cons:**
- More complex implementation
- Multiple transactions
- Partial completion possible

### For Maximum Performance: Pattern 3 (Optimistic)

**Pros:**
- Fastest execution
- Minimal operations
- Simple happy path

**Cons:**
- Requires robust recovery mechanism
- More complex error handling
- Tasks may process before status updated

## 🔍 Monitoring & Observability

### Key Metrics to Track

```python
# Add to task creation
metrics = {
    'job_id': job_id,
    'stage': stage,
    'batch_size': len(task_definitions),
    'db_insert_time_ms': db_elapsed_ms,
    'queue_send_time_ms': queue_elapsed_ms,
    'status_update_time_ms': update_elapsed_ms,
    'total_time_ms': total_elapsed_ms,
    'pattern_used': 'two_phase_commit',
    'retry_needed': False
}

logger.info(f"Batch coordination metrics: {json.dumps(metrics)}")

# Track in Application Insights
telemetry_client.track_event(
    'BatchTaskCreation',
    properties=metrics,
    measurements={
        'TaskCount': len(task_definitions),
        'ElapsedMs': total_elapsed_ms
    }
)
```

### Dashboard Queries

```sql
-- Tasks needing retry
SELECT
    parent_job_id,
    COUNT(*) as pending_tasks,
    MIN(created_at) as oldest_task,
    MAX(queue_attempt_count) as max_attempts
FROM tasks
WHERE batch_status = 'pending_retry'
GROUP BY parent_job_id;

-- Batch success rate
SELECT
    DATE(created_at) as date,
    COUNT(DISTINCT batch_id) as total_batches,
    COUNT(DISTINCT batch_id) FILTER (WHERE batch_status = 'queued') as successful_batches,
    AVG(queue_attempt_count) as avg_attempts
FROM tasks
WHERE batch_id IS NOT NULL
GROUP BY DATE(created_at);

-- Queue lag monitoring
SELECT
    parent_job_id,
    COUNT(*) FILTER (WHERE batch_status = 'pending_queue') as pending,
    COUNT(*) FILTER (WHERE batch_status = 'queued') as queued,
    COUNT(*) FILTER (WHERE batch_status = 'processing') as processing,
    COUNT(*) FILTER (WHERE batch_status = 'completed') as completed
FROM tasks
WHERE created_at > NOW() - INTERVAL '1 hour'
GROUP BY parent_job_id;
```

## 🚀 Implementation Priority

1. **Start with Pattern 1** (Two-Phase Commit)
   - Simplest to implement correctly
   - Good enough for 90% of cases
   - Easy to debug

2. **Add Recovery Job**
   - Essential for production resilience
   - Handles edge cases automatically
   - Provides safety net

3. **Monitor and Optimize**
   - Collect metrics
   - Identify bottlenecks
   - Consider Pattern 2/3 if needed

## 💡 Key Insights

1. **Database First, Queue Second**
   - Always ensure tasks exist in database
   - Queue is just a trigger for processing
   - Database is source of truth

2. **Status Transitions Are Critical**
   - 'pending_queue' → tasks exist but not queued
   - 'queued' → tasks are in Service Bus
   - 'pending_retry' → temporary failure state

3. **Batch Size Matters**
   - PostgreSQL: Can handle 10,000+ in one operation
   - Service Bus: Limited to 100 per batch
   - May need multiple Service Bus batches per DB batch

4. **Recovery Is Not Optional**
   - Network failures will happen
   - Service Bus may throttle
   - Must have automatic recovery

5. **Monitoring Prevents Disasters**
   - Track pending_retry tasks
   - Alert on growing queue lag
   - Monitor batch success rates