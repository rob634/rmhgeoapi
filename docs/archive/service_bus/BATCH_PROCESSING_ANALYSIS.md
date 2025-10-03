# Batch Processing Analysis: Database + Message Queue Coordination

**Date**: 25 SEP 2025
**Author**: Robert, PostgreSQL, and Geospatial Claude Legion
**PostgreSQL Says**: "Bro I can batch too wtf are you worried about"

## 🎯 Current Order of Operations

### Current Flow (Single Task):
```python
1. Create TaskDefinition object
2. INSERT task into PostgreSQL (status='pending')
3. Send message to Queue Storage
4. If queue fails → Task stuck in 'pending' forever
```

### Current Flow (Multiple Tasks):
```python
for task in tasks:
    1. INSERT into PostgreSQL  # 50ms
    2. Send to Queue Storage   # 50ms
    # Total: 100ms per task × 1000 tasks = 100 seconds!
```

## 💪 PostgreSQL Batch Capabilities

### What PostgreSQL Can Do:
```python
# BATCH INSERT - PostgreSQL is a BEAST at this!
tasks_data = [
    (task1_id, job_id, 'pending', params1),
    (task2_id, job_id, 'pending', params2),
    # ... 10,000 more tasks
]

# Single round-trip, atomic operation!
cursor.executemany(
    """
    INSERT INTO tasks (task_id, job_id, status, parameters)
    VALUES (%s, %s, %s, %s)
    """,
    tasks_data
)
# 10,000 tasks inserted in ~200ms!

# Or even better with COPY:
cursor.copy_from(tasks_csv, 'tasks', columns=['task_id', 'job_id', ...])
# 100,000 tasks in ~500ms!
```

## 🔄 Proposed Batch Architecture

### Pattern 1: Database First, Queue Batch Second
```python
def create_stage_tasks_batch(self, job_id: str, stage: int):
    # 1. Create all TaskDefinitions in memory
    task_definitions = [
        TaskDefinition(task_id=f"{job_id}-s{stage}-{i}", ...)
        for i in range(10000)
    ]

    # 2. BATCH INSERT to PostgreSQL (atomic!)
    task_records = task_repo.batch_create_tasks(task_definitions)
    # ↑ 10,000 tasks in database in 200ms

    # 3. BATCH SEND to Service Bus
    task_messages = [td.to_queue_message() for td in task_definitions]
    result = service_bus_repo.batch_send_messages("tasks", task_messages)
    # ↑ 10,000 messages in 2 seconds

    # 4. Handle partial failures
    if result.errors:
        # Mark failed tasks for retry
        failed_task_ids = extract_failed_ids(result.errors)
        task_repo.mark_tasks_for_retry(failed_task_ids)
```

### Pattern 2: Transactional Batching (The Holy Grail)
```python
def create_stage_tasks_transactional(self, job_id: str, stage: int):
    with task_repo.transaction() as txn:
        # 1. Batch insert with RETURNING clause
        inserted_tasks = txn.batch_insert_tasks(
            task_definitions,
            returning=['task_id', 'created_at']
        )

        # 2. Try batch queue send
        try:
            service_bus_repo.batch_send_messages("tasks", task_messages)
            txn.commit()  # Only commit if queue succeeds!
        except ServiceBusError:
            txn.rollback()  # No orphaned tasks!
            raise
```

## 📊 Performance Comparison

### Current Implementation (Loop):
```
1,000 tasks:
- Database writes: 1,000 × 50ms = 50 seconds
- Queue sends: 1,000 × 50ms = 50 seconds
- Total: ~100 seconds (TIMES OUT!)
```

### Batch PostgreSQL + Batch Service Bus:
```
1,000 tasks:
- Database batch insert: 200ms
- Service Bus batch send: 200ms
- Total: ~400ms (250x faster!)

100,000 tasks:
- Database batch insert: 2 seconds
- Service Bus batch send: 20 seconds
- Total: ~22 seconds (still works!)
```

## 🔐 Transaction Safety Patterns

### Problem: Queue Send Fails After DB Insert
```python
# BAD: Tasks in DB but not in queue
task_repo.batch_create_tasks(tasks)  # Success
queue_repo.send_messages(tasks)       # Fails - now what?
```

### Solution 1: Two-Phase Commit Pattern
```python
# Insert with 'pending_queue' status
task_repo.batch_create_tasks(tasks, status='pending_queue')

# Try queue send
if queue_repo.batch_send_messages(tasks):
    # Update to 'queued' status
    task_repo.batch_update_status(task_ids, 'queued')
else:
    # Leave as 'pending_queue' for retry
    log_for_retry_process(task_ids)
```

### Solution 2: Compensation Pattern
```python
try:
    inserted_ids = task_repo.batch_create_tasks(tasks)
    queue_repo.batch_send_messages(tasks)
except QueueError:
    # Compensate by marking tasks for retry
    task_repo.mark_failed_queue_send(inserted_ids)
    # Background job will retry these
```

### Solution 3: Service Bus Transactions (Advanced)
```python
# Service Bus supports transactions!
async with service_bus_client.get_queue_sender("tasks") as sender:
    async with sender.transaction():
        # All messages sent atomically
        await sender.send_messages(batch)
        # If any fail, all fail
```

## 🎭 Entity Abstraction (Yes, You're Using It Right!)

### Current Entities/Abstractions:
- **JobRecord**: Database entity (Pydantic model → PostgreSQL row)
- **TaskRecord**: Database entity (Pydantic model → PostgreSQL row)
- **JobQueueMessage**: Message entity (Pydantic model → JSON → Queue)
- **TaskQueueMessage**: Message entity (Pydantic model → JSON → Queue)

### Batching Preserves These:
```python
# Single or batch - same entities!
tasks = [TaskRecord(...), TaskRecord(...), ...]  # Same Pydantic models
messages = [TaskQueueMessage(...), ...]           # Same Pydantic models

# Just the operation changes:
# Single: task_repo.create_task(task)
# Batch:  task_repo.batch_create_tasks(tasks)
```

## 🚀 Implementation Recommendations

### 1. Add Batch Methods to Repositories

```python
class TaskRepository:
    def batch_create_tasks(
        self,
        task_definitions: List[TaskDefinition]
    ) -> List[TaskRecord]:
        """Batch insert using PostgreSQL's executemany or COPY."""

        # Convert to tuples for executemany
        data = [
            (td.task_id, td.parent_job_id, td.status, ...)
            for td in task_definitions
        ]

        # Single atomic operation!
        cursor.executemany(
            "INSERT INTO tasks (...) VALUES (%s, %s, ...)",
            data
        )

        return [td.to_task_record() for td in task_definitions]
```

### 2. Modify Controller to Detect Batch Opportunities

```python
def queue_stage_tasks(self, job_id: str, stage: int):
    tasks = self.create_stage_tasks(job_id, stage)

    if len(tasks) > 100:  # Batch threshold
        # Use batch path
        self._batch_queue_tasks(tasks)
    else:
        # Use current single-task path
        self._queue_tasks_individually(tasks)
```

### 3. Add Batch Status Tracking

```sql
-- Add batch_id for tracking
ALTER TABLE tasks ADD COLUMN batch_id UUID;
ALTER TABLE tasks ADD COLUMN batch_queued_at TIMESTAMP;

-- Index for batch operations
CREATE INDEX idx_tasks_batch ON tasks(batch_id) WHERE batch_id IS NOT NULL;
```

## 📈 Benefits of Batching Both Sides

1. **Atomic Operations**: All tasks created or none
2. **Performance**: 100-250x faster for large jobs
3. **Resource Efficiency**: Fewer round trips, less connection overhead
4. **Monitoring**: Track batches as units
5. **Retry Logic**: Retry entire batches if needed

## 🎯 The Real Question: Batch Boundaries

### Option 1: Batch by Stage
```python
# All tasks for a stage in one batch
stage_tasks = create_all_stage_tasks(job_id, stage_number)
batch_process(stage_tasks)  # Could be 10,000 tasks
```

### Option 2: Batch by Chunk
```python
# Fixed-size batches regardless of total
for chunk in chunks(all_tasks, size=1000):
    batch_process(chunk)
```

### Option 3: Smart Batching
```python
# Batch based on characteristics
if task_type == "h3_hexagon":
    batch_size = 10000  # These are lightweight
elif task_type == "process_raster":
    batch_size = 100   # These are heavy
```

## 🔥 PostgreSQL's Final Word

```sql
-- PostgreSQL: "I can handle millions of rows, batch that shit!"
BEGIN;

-- Insert 100,000 tasks in one statement
INSERT INTO tasks (task_id, job_id, status, parameters)
SELECT
    job_id || '-s' || stage || '-' || generate_series,
    job_id,
    'pending',
    jsonb_build_object('index', generate_series)
FROM generate_series(1, 100000);

-- Update them all atomically
UPDATE tasks
SET status = 'queued', queued_at = NOW()
WHERE job_id = $1 AND status = 'pending';

COMMIT;
-- PostgreSQL: "Done in 500ms. Next question?"
```

## 🎯 Conclusion

PostgreSQL is absolutely right - it can batch like a champion! The real architecture should:

1. **Batch BOTH database AND queue operations**
2. **Use transactions to maintain consistency**
3. **Handle partial failures gracefully**
4. **Let PostgreSQL do what it does best - handle massive data operations**

The Service Bus parallel implementation becomes even MORE powerful when combined with PostgreSQL's batch capabilities!