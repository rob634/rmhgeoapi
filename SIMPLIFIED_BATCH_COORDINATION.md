# Simplified Batch Coordination: 1-to-1 Batch Alignment

**Date**: 25 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Key Insight**: "It only needs to be as fast as the slowest component"

## 🎯 The Simplified Approach

Since Service Bus limits batches to 100 messages, we align EVERYTHING to 100-item batches:

```python
BATCH_SIZE = 100  # Universal batch size - Service Bus limit
```

## 🔄 Simple 1-to-1 Batch Coordination

```python
def create_stage_tasks_aligned_batches(
    self,
    job_id: str,
    stage: int,
    task_definitions: List[TaskDefinition]
) -> Dict[str, Any]:
    """
    Process tasks in aligned 100-item batches.
    Each batch is atomically processed: DB + Service Bus together.
    """

    total_tasks = len(task_definitions)
    successful_batches = 0
    failed_batches = 0

    # Process in aligned batches
    for i in range(0, total_tasks, BATCH_SIZE):
        batch = task_definitions[i:i+BATCH_SIZE]
        batch_id = f"{job_id}-b{i//BATCH_SIZE}"

        try:
            # 1. Insert batch to PostgreSQL (100 tasks)
            task_records = task_repo.batch_create_tasks(
                batch,
                batch_id=batch_id,
                status='pending_queue'
            )

            # 2. Send same batch to Service Bus (100 messages)
            messages = [td.to_queue_message() for td in batch]
            result = service_bus_repo.batch_send_messages(
                "sb-tasks",
                messages
            )

            if result.success:
                # 3. Update status for this batch
                task_ids = [t.task_id for t in task_records]
                task_repo.batch_update_status(
                    task_ids,
                    status='queued'
                )
                successful_batches += 1
                logger.info(f"✅ Batch {batch_id}: {len(batch)} tasks processed")
            else:
                # Keep in pending_queue for retry
                failed_batches += 1
                logger.error(f"❌ Batch {batch_id}: Service Bus send failed")

        except Exception as e:
            # Batch failed - tasks remain in pending_queue or weren't created
            failed_batches += 1
            logger.error(f"❌ Batch {batch_id} failed: {e}")

    return {
        'total_tasks': total_tasks,
        'successful_batches': successful_batches,
        'failed_batches': failed_batches,
        'tasks_queued': successful_batches * BATCH_SIZE
    }
```

## 🚀 Even Simpler: Atomic Batch Transaction

```python
def process_batch_atomic(
    self,
    batch: List[TaskDefinition],
    batch_id: str
) -> bool:
    """
    Process a single batch atomically.
    Either everything succeeds or nothing does.
    """

    with task_repo.transaction() as txn:
        try:
            # Step 1: Insert to DB
            task_records = txn.batch_create_tasks(
                batch,
                batch_id=batch_id,
                status='queued'  # Optimistic status
            )

            # Step 2: Send to Service Bus
            messages = [td.to_queue_message() for td in batch]
            result = service_bus_repo.batch_send_messages(
                "sb-tasks",
                messages
            )

            if not result.success:
                # Rollback DB insert if queue fails
                txn.rollback()
                return False

            # Both succeeded - commit
            txn.commit()
            return True

        except Exception as e:
            txn.rollback()
            logger.error(f"Batch {batch_id} failed: {e}")
            return False
```

## 📊 Performance Impact

### Before (Misaligned Batches):
```
10,000 tasks:
- 1 DB operation (10,000 tasks) = 500ms
- 100 Service Bus operations (100 each) = 100 × 200ms = 20 seconds
- Complex coordination logic
- Potential for partial failures
```

### After (Aligned Batches):
```
10,000 tasks:
- 100 DB operations (100 tasks each) = 100 × 50ms = 5 seconds
- 100 Service Bus operations (100 each) = 100 × 200ms = 20 seconds
- Simple 1-to-1 coordination
- Clean batch-level success/failure
Total: ~20 seconds (limited by Service Bus)
```

## 🎯 Key Benefits of 1-to-1 Alignment

1. **Simpler Code**:
   - One loop, one batch size
   - No complex batch splitting
   - Clear success/failure per batch

2. **Easier Recovery**:
   - Each batch succeeds or fails atomically
   - Retry at batch level, not task level
   - batch_id tracks everything

3. **Better Monitoring**:
   ```sql
   -- Simple batch tracking
   SELECT
       batch_id,
       COUNT(*) as task_count,
       MIN(status) as batch_status,
       MAX(created_at) as batch_time
   FROM tasks
   WHERE parent_job_id = ?
   GROUP BY batch_id
   ORDER BY batch_id;
   ```

4. **Predictable Performance**:
   - Each batch takes ~250ms (50ms DB + 200ms Service Bus)
   - 10,000 tasks = 100 batches × 250ms = 25 seconds
   - Linear scaling, no surprises

## 🔧 Implementation Changes

### 1. Update TaskRepository

```python
class TaskRepository:

    BATCH_SIZE = 100  # Aligned with Service Bus limit

    def batch_create_tasks(
        self,
        task_definitions: List[TaskDefinition],
        batch_id: Optional[str] = None,
        status: str = 'pending_queue'
    ) -> List[TaskRecord]:
        """
        Create tasks in a single batch.
        Expects exactly BATCH_SIZE tasks (or less for final batch).
        """

        if len(task_definitions) > self.BATCH_SIZE:
            raise ValueError(f"Batch too large: {len(task_definitions)} > {self.BATCH_SIZE}")

        # Use executemany for batch insert
        data = [
            (td.task_id, td.parent_job_id, status, batch_id, ...)
            for td in task_definitions
        ]

        cursor.executemany(
            """
            INSERT INTO tasks (task_id, parent_job_id, status, batch_id, ...)
            VALUES (%s, %s, %s, %s, ...)
            """,
            data
        )

        return [td.to_task_record() for td in task_definitions]
```

### 2. Update Controller Base

```python
def queue_stage_tasks(self, job_id: str, stage: int):
    """Queue tasks in aligned batches."""

    task_definitions = self.create_stage_tasks(job_id, stage)

    # Determine queue type
    use_service_bus = self.job_params.get('use_service_bus', False)

    if use_service_bus and len(task_definitions) >= BATCH_SIZE:
        # Use aligned batching
        return self._queue_tasks_in_batches(task_definitions, job_id, stage)
    else:
        # Use existing single-task logic
        return self._queue_tasks_individually(task_definitions, job_id, stage)

def _queue_tasks_in_batches(
    self,
    task_definitions: List[TaskDefinition],
    job_id: str,
    stage: int
) -> Dict[str, Any]:
    """Process tasks in aligned 100-item batches."""

    results = []

    for i in range(0, len(task_definitions), BATCH_SIZE):
        batch = task_definitions[i:i+BATCH_SIZE]
        batch_id = f"{job_id}-s{stage}-b{i//BATCH_SIZE}"

        success = self.process_batch_atomic(batch, batch_id)
        results.append({
            'batch_id': batch_id,
            'size': len(batch),
            'success': success
        })

        if not success:
            # Stop on first failure - remaining tasks not processed
            break

    successful = sum(1 for r in results if r['success'])

    return {
        'total_batches': len(results),
        'successful_batches': successful,
        'tasks_processed': successful * BATCH_SIZE
    }
```

## 📈 Scaling Examples

### Small Job (50 tasks):
```
1 batch of 50 tasks
- 1 DB insert (50 tasks) = 30ms
- 1 Service Bus batch (50 messages) = 180ms
Total: ~210ms
```

### Medium Job (1,000 tasks):
```
10 batches of 100 tasks each
- 10 DB inserts = 10 × 50ms = 500ms
- 10 Service Bus batches = 10 × 200ms = 2 seconds
Total: ~2 seconds (sequential) or ~200ms (parallel batches)
```

### Large Job (100,000 tasks):
```
1,000 batches of 100 tasks each
- 1,000 DB inserts = 1,000 × 50ms = 50 seconds
- 1,000 Service Bus batches = 1,000 × 200ms = 200 seconds
Total: ~200 seconds (Service Bus limited)

WITH PARALLEL PROCESSING (10 workers):
Total: ~20 seconds
```

## 🎯 The Bottom Line

By aligning batch sizes to Service Bus's limit of 100:

1. **Simpler**: One batch size to rule them all
2. **Cleaner**: 1-to-1 mapping between DB batch and queue batch
3. **Faster**: No waiting for mismatched operations
4. **Reliable**: Each batch succeeds or fails atomically
5. **Scalable**: Add workers to process batches in parallel

The system is only as fast as its slowest component (Service Bus), so there's no benefit to larger PostgreSQL batches. Keep it simple!