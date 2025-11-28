# CoreMachine Debug Logging Checkpoints

**Date**: 5 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive debug logging strategy to identify silent failures in CoreMachine
**Related**: WORKFLOW_FAILURE_ANALYSIS.md (9 failure points documented)

---

## 🎯 Executive Summary

This document defines **debug logging checkpoints** throughout the CoreMachine orchestration flow to enable rapid identification of silent failures. Each checkpoint is queryable in Application Insights using structured logging with correlation IDs.

### Design Principles

1. **Correlation ID Tracking**: Every log entry includes job_id/task_id for trace reconstruction
2. **Emoji Markers**: Visual markers for quick scanning (🎬 START, ✅ SUCCESS, ❌ FAILURE)
3. **Structured Fields**: Consistent key-value pairs for Application Insights queries
4. **Checkpoint Codes**: Unique identifiers (e.g., `[JOB_START]`, `[TASK_EXEC]`) for filtering
5. **State Transitions**: Log BEFORE and AFTER every database state change
6. **Timing Metrics**: Duration tracking for performance analysis

---

## 📊 Checkpoint Hierarchy

### Level 1: Job Lifecycle (9 checkpoints)
```
[JOB_SUBMIT]     → HTTP trigger receives job submission
[JOB_VALIDATE]   → Job parameters validated
[JOB_QUEUED]     → Job message sent to Service Bus
[JOB_START]      → CoreMachine begins processing job message
[JOB_STAGE_ADV]  → Job advancing to next stage
[JOB_COMPLETE]   → Job marked as COMPLETED
[JOB_FAILED]     → Job marked as FAILED
[JOB_RETRY]      → Job retry attempt initiated
[JOB_ABANDONED]  → Job abandoned (max retries exceeded)
```

### Level 2: Task Lifecycle (11 checkpoints)
```
[TASK_CREATE]    → Task definition created by job
[TASK_QUEUED]    → Task message sent to Service Bus
[TASK_START]     → CoreMachine begins processing task message
[TASK_STATUS_UPD]→ Task status update attempted (QUEUED→PROCESSING)
[TASK_EXEC]      → Task handler execution begins
[TASK_HANDLER_OK]→ Task handler returns success
[TASK_HANDLER_ERR]→ Task handler raises exception
[TASK_COMPLETE]  → Task marked as COMPLETED in database
[TASK_FAILED]    → Task marked as FAILED in database
[TASK_RETRY]     → Task retry attempt initiated
[TASK_SQL_LOCK]  → Advisory lock acquired for completion check
```

### Level 3: Stage Lifecycle (7 checkpoints)
```
[STAGE_START]    → Stage begins execution
[STAGE_TASKS_GEN]→ Tasks generated for stage
[STAGE_BATCH_Q]  → Tasks batched and queued to Service Bus
[STAGE_LAST_TASK]→ Last task in stage detected (advisory lock)
[STAGE_AGGREGATE]→ Stage results aggregation begins
[STAGE_COMPLETE] → Stage marked as complete
[STAGE_ADV_FAIL] → Stage advancement failure (FP3)
```

### Level 4: Database Operations (6 checkpoints)
```
[DB_CONN]        → Database connection established
[DB_QUERY]       → SQL query execution begins
[DB_UPDATE]      → Database record update
[DB_ADVISORY_LOCK]→ PostgreSQL advisory lock acquired
[DB_COMMIT]      → Transaction committed
[DB_ERROR]       → Database operation failed
```

### Level 5: Service Bus Operations (5 checkpoints)
```
[SB_SEND]        → Message sent to Service Bus
[SB_BATCH]       → Batch messages sent to Service Bus
[SB_RECEIVE]     → Message received from Service Bus
[SB_COMPLETE]    → Message acknowledged (removed from queue)
[SB_ERROR]       → Service Bus operation failed
```

---

## 🔍 Implementation Pattern

### Standard Checkpoint Format

```python
# Before operation
logger.debug(
    f"[CHECKPOINT_CODE] 🎬 Operation description",
    extra={
        'checkpoint': 'CHECKPOINT_CODE',
        'job_id': job_id,
        'task_id': task_id,
        'stage': stage_num,
        'correlation_id': correlation_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'context': {
            'param1': value1,
            'param2': value2
        }
    }
)

# After operation (success)
logger.debug(
    f"[CHECKPOINT_CODE] ✅ Operation completed successfully",
    extra={
        'checkpoint': 'CHECKPOINT_CODE_COMPLETE',
        'job_id': job_id,
        'duration_ms': duration_ms,
        'result': {
            'key1': value1
        }
    }
)

# After operation (failure)
logger.error(
    f"[CHECKPOINT_CODE] ❌ Operation failed: {error}",
    extra={
        'checkpoint': 'CHECKPOINT_CODE_FAILED',
        'job_id': job_id,
        'error_type': type(e).__name__,
        'error_message': str(e),
        'traceback': traceback.format_exc()
    }
)
```

---

## 📝 Checkpoint Implementation by File

### **File: function_app.py** (HTTP Triggers)

**Location**: `process_service_bus_job()` function (lines 1754-1766)

```python
@app.service_bus_queue_trigger(queue_name="geospatial-jobs")
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
    correlation_id = str(uuid.uuid4())
    start_time = time.time()

    # ✅ CHECKPOINT: [JOB_START]
    logger.debug(
        f"[JOB_START] 🎬 Processing job message from Service Bus",
        extra={
            'checkpoint': 'JOB_START',
            'correlation_id': correlation_id,
            'message_id': msg.message_id,
            'enqueued_time': msg.enqueued_time_utc.isoformat() if msg.enqueued_time_utc else None,
            'delivery_count': msg.delivery_count
        }
    )

    try:
        # Parse message
        message_body = msg.get_body().decode('utf-8')

        # ✅ CHECKPOINT: [JOB_VALIDATE]
        logger.debug(
            f"[JOB_VALIDATE] 🎬 Parsing job message",
            extra={
                'checkpoint': 'JOB_VALIDATE',
                'correlation_id': correlation_id,
                'message_length': len(message_body)
            }
        )

        job_message = JobQueueMessage.model_validate_json(message_body)

        # ✅ CHECKPOINT: [JOB_VALIDATE] - Success
        logger.debug(
            f"[JOB_VALIDATE] ✅ Job message parsed successfully",
            extra={
                'checkpoint': 'JOB_VALIDATE_SUCCESS',
                'correlation_id': correlation_id,
                'job_id': job_message.job_id,
                'job_type': job_message.job_type,
                'stage': job_message.stage
            }
        )

        # Process job
        result = core_machine.process_job_message(job_message)

        duration_ms = (time.time() - start_time) * 1000

        # ✅ CHECKPOINT: [JOB_START] - Complete
        logger.info(
            f"[JOB_START] ✅ Job processing complete",
            extra={
                'checkpoint': 'JOB_START_COMPLETE',
                'correlation_id': correlation_id,
                'job_id': job_message.job_id,
                'duration_ms': duration_ms,
                'result': result
            }
        )

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        # ✅ CHECKPOINT: [JOB_START] - Failed
        logger.error(
            f"[JOB_START] ❌ Job processing exception: {type(e).__name__}: {e}",
            extra={
                'checkpoint': 'JOB_START_FAILED',
                'correlation_id': correlation_id,
                'job_id': job_message.job_id if 'job_message' in locals() else None,
                'duration_ms': duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc()
            }
        )

        # FP1 FIX: Mark job as FAILED (already implemented)
        # ... existing code ...
```

**Similar pattern for**:
- `process_service_bus_task()` - Add `[TASK_START]`, `[TASK_START_COMPLETE]`, `[TASK_START_FAILED]`
- `submit_job()` - Add `[JOB_SUBMIT]`, `[JOB_VALIDATE]`, `[JOB_QUEUED]`

---

### **File: core/machine.py** (CoreMachine Orchestrator)

**Location**: `process_job_message()` method (lines ~150-250)

```python
def process_job_message(self, job_message: JobQueueMessage):
    """
    Process job message - orchestrate stage execution.

    Enhanced with debug logging checkpoints for failure diagnosis.
    """
    job_id = job_message.job_id
    job_type = job_message.job_type
    stage = job_message.stage
    start_time = time.time()

    # ✅ CHECKPOINT: [JOB_STAGE_START]
    self.logger.debug(
        f"[JOB_STAGE_START] 🎬 Processing job {job_id[:16]}... stage {stage}",
        extra={
            'checkpoint': 'JOB_STAGE_START',
            'job_id': job_id,
            'job_type': job_type,
            'stage': stage,
            'parameters': job_message.parameters
        }
    )

    try:
        # Step 1: Get job class from registry
        # ✅ CHECKPOINT: [JOB_REGISTRY_LOOKUP]
        self.logger.debug(
            f"[JOB_REGISTRY_LOOKUP] 🎬 Looking up job class for type: {job_type}",
            extra={
                'checkpoint': 'JOB_REGISTRY_LOOKUP',
                'job_id': job_id,
                'job_type': job_type
            }
        )

        if job_type not in self.jobs_registry:
            # ✅ CHECKPOINT: [JOB_REGISTRY_LOOKUP] - Failed
            error_msg = f"Unknown job type: {job_type}"
            self.logger.error(
                f"[JOB_REGISTRY_LOOKUP] ❌ {error_msg}",
                extra={
                    'checkpoint': 'JOB_REGISTRY_LOOKUP_FAILED',
                    'job_id': job_id,
                    'job_type': job_type,
                    'available_types': list(self.jobs_registry.keys())
                }
            )
            raise ValueError(error_msg)

        job_class = self.jobs_registry[job_type]

        # ✅ CHECKPOINT: [JOB_REGISTRY_LOOKUP] - Success
        self.logger.debug(
            f"[JOB_REGISTRY_LOOKUP] ✅ Job class found: {job_class.__name__}",
            extra={
                'checkpoint': 'JOB_REGISTRY_LOOKUP_SUCCESS',
                'job_id': job_id,
                'job_class': job_class.__name__
            }
        )

        # Step 2: Create tasks for stage
        # ✅ CHECKPOINT: [STAGE_TASKS_GEN]
        self.logger.debug(
            f"[STAGE_TASKS_GEN] 🎬 Generating tasks for stage {stage}",
            extra={
                'checkpoint': 'STAGE_TASKS_GEN',
                'job_id': job_id,
                'stage': stage,
                'job_class': job_class.__name__
            }
        )

        task_gen_start = time.time()

        tasks = job_class.create_tasks_for_stage(
            stage=stage,
            job_params=job_message.parameters,
            job_id=job_id,
            previous_results=job_message.stage_results.get(str(stage - 1)) if stage > 1 else None
        )

        task_gen_duration_ms = (time.time() - task_gen_start) * 1000

        # ✅ CHECKPOINT: [STAGE_TASKS_GEN] - Success
        self.logger.info(
            f"[STAGE_TASKS_GEN] ✅ Generated {len(tasks)} tasks for stage {stage}",
            extra={
                'checkpoint': 'STAGE_TASKS_GEN_SUCCESS',
                'job_id': job_id,
                'stage': stage,
                'task_count': len(tasks),
                'duration_ms': task_gen_duration_ms,
                'task_types': [t.get('task_type') for t in tasks]
            }
        )

        # Step 3: Queue tasks to Service Bus
        # ✅ CHECKPOINT: [STAGE_BATCH_Q]
        self.logger.debug(
            f"[STAGE_BATCH_Q] 🎬 Queueing {len(tasks)} tasks to Service Bus",
            extra={
                'checkpoint': 'STAGE_BATCH_Q',
                'job_id': job_id,
                'stage': stage,
                'task_count': len(tasks)
            }
        )

        queue_start = time.time()

        # Orchestration manager handles batching and queuing
        self.orchestration_manager.queue_tasks_to_service_bus(
            job_id=job_id,
            job_type=job_type,
            stage=stage,
            tasks=tasks
        )

        queue_duration_ms = (time.time() - queue_start) * 1000

        # ✅ CHECKPOINT: [STAGE_BATCH_Q] - Success
        self.logger.info(
            f"[STAGE_BATCH_Q] ✅ Tasks queued successfully",
            extra={
                'checkpoint': 'STAGE_BATCH_Q_SUCCESS',
                'job_id': job_id,
                'stage': stage,
                'task_count': len(tasks),
                'duration_ms': queue_duration_ms
            }
        )

        total_duration_ms = (time.time() - start_time) * 1000

        # ✅ CHECKPOINT: [JOB_STAGE_START] - Complete
        self.logger.info(
            f"[JOB_STAGE_START] ✅ Job stage processing complete",
            extra={
                'checkpoint': 'JOB_STAGE_START_COMPLETE',
                'job_id': job_id,
                'stage': stage,
                'total_duration_ms': total_duration_ms,
                'task_count': len(tasks)
            }
        )

        return {'success': True, 'tasks_created': len(tasks)}

    except Exception as e:
        total_duration_ms = (time.time() - start_time) * 1000

        # ✅ CHECKPOINT: [JOB_STAGE_START] - Failed
        self.logger.error(
            f"[JOB_STAGE_START] ❌ Job stage processing failed: {type(e).__name__}: {e}",
            extra={
                'checkpoint': 'JOB_STAGE_START_FAILED',
                'job_id': job_id,
                'stage': stage,
                'duration_ms': total_duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc()
            }
        )
        raise
```

**Location**: `process_task_message()` method (lines ~350-500)

```python
def process_task_message(self, task_message: TaskQueueMessage):
    """
    Process task message - execute handler and update state.

    Enhanced with debug logging checkpoints for failure diagnosis.
    """
    task_id = task_message.task_id
    job_id = task_message.parent_job_id
    start_time = time.time()

    # ✅ CHECKPOINT: [TASK_START]
    self.logger.debug(
        f"[TASK_START] 🎬 Processing task {task_id}",
        extra={
            'checkpoint': 'TASK_START',
            'task_id': task_id,
            'job_id': job_id,
            'task_type': task_message.task_type,
            'stage': task_message.stage
        }
    )

    try:
        # Step 1.5: Update task status to PROCESSING
        # ✅ CHECKPOINT: [TASK_STATUS_UPD]
        self.logger.debug(
            f"[TASK_STATUS_UPD] 🎬 Updating task status to PROCESSING",
            extra={
                'checkpoint': 'TASK_STATUS_UPD',
                'task_id': task_id,
                'job_id': job_id,
                'from_status': 'QUEUED',
                'to_status': 'PROCESSING'
            }
        )

        status_update_start = time.time()

        success = self.state_manager.update_task_status_direct(
            task_id,
            TaskStatus.PROCESSING
        )

        status_update_duration_ms = (time.time() - status_update_start) * 1000

        if success:
            # ✅ CHECKPOINT: [TASK_STATUS_UPD] - Success
            self.logger.debug(
                f"[TASK_STATUS_UPD] ✅ Task status updated to PROCESSING",
                extra={
                    'checkpoint': 'TASK_STATUS_UPD_SUCCESS',
                    'task_id': task_id,
                    'duration_ms': status_update_duration_ms
                }
            )
        else:
            # ✅ CHECKPOINT: [TASK_STATUS_UPD] - Failed (FP2 fix already in place)
            error_msg = "Failed to update task status to PROCESSING"
            self.logger.error(
                f"[TASK_STATUS_UPD] ❌ {error_msg}",
                extra={
                    'checkpoint': 'TASK_STATUS_UPD_FAILED',
                    'task_id': task_id,
                    'duration_ms': status_update_duration_ms
                }
            )
            # FP2 fix handles this - fail fast
            # ... existing code ...

        # Step 2: Execute task handler
        # ✅ CHECKPOINT: [TASK_EXEC]
        handler = self.handlers_registry.get(task_message.task_type)

        self.logger.debug(
            f"[TASK_EXEC] 🎬 Executing handler: {task_message.task_type}",
            extra={
                'checkpoint': 'TASK_EXEC',
                'task_id': task_id,
                'handler_name': task_message.task_type,
                'parameters': task_message.parameters
            }
        )

        handler_start = time.time()

        result = handler(task_message.parameters)

        handler_duration_ms = (time.time() - handler_start) * 1000

        if result.get('success'):
            # ✅ CHECKPOINT: [TASK_HANDLER_OK]
            self.logger.info(
                f"[TASK_HANDLER_OK] ✅ Handler executed successfully",
                extra={
                    'checkpoint': 'TASK_HANDLER_OK',
                    'task_id': task_id,
                    'handler_name': task_message.task_type,
                    'duration_ms': handler_duration_ms,
                    'result_keys': list(result.keys())
                }
            )
        else:
            # ✅ CHECKPOINT: [TASK_HANDLER_ERR]
            self.logger.warning(
                f"[TASK_HANDLER_ERR] ⚠️ Handler returned failure",
                extra={
                    'checkpoint': 'TASK_HANDLER_ERR',
                    'task_id': task_id,
                    'handler_name': task_message.task_type,
                    'duration_ms': handler_duration_ms,
                    'error': result.get('error')
                }
            )

        # Step 3: Complete task and check stage
        # ✅ CHECKPOINT: [TASK_COMPLETE]
        self.logger.debug(
            f"[TASK_COMPLETE] 🎬 Completing task in database",
            extra={
                'checkpoint': 'TASK_COMPLETE',
                'task_id': task_id,
                'job_id': job_id,
                'stage': task_message.stage
            }
        )

        complete_start = time.time()

        completion = self.state_manager.complete_task_with_sql(
            task_id,
            job_id,
            task_message.stage,
            result
        )

        complete_duration_ms = (time.time() - complete_start) * 1000

        # ✅ CHECKPOINT: [TASK_COMPLETE] - Success
        self.logger.info(
            f"[TASK_COMPLETE] ✅ Task completed in database",
            extra={
                'checkpoint': 'TASK_COMPLETE_SUCCESS',
                'task_id': task_id,
                'duration_ms': complete_duration_ms,
                'stage_complete': completion.stage_complete,
                'remaining_tasks': completion.remaining_tasks
            }
        )

        # Step 4: Handle stage completion (if last task)
        if completion.stage_complete:
            # ✅ CHECKPOINT: [STAGE_LAST_TASK]
            self.logger.info(
                f"[STAGE_LAST_TASK] 🎯 Last task detected - triggering stage completion",
                extra={
                    'checkpoint': 'STAGE_LAST_TASK',
                    'task_id': task_id,
                    'job_id': job_id,
                    'stage': task_message.stage,
                    'total_tasks': completion.total_tasks_in_stage
                }
            )

            # ✅ CHECKPOINT: [STAGE_COMPLETE]
            self.logger.debug(
                f"[STAGE_COMPLETE] 🎬 Handling stage completion",
                extra={
                    'checkpoint': 'STAGE_COMPLETE',
                    'job_id': job_id,
                    'stage': task_message.stage
                }
            )

            try:
                self._handle_stage_completion(
                    job_id,
                    task_message.job_type,
                    task_message.stage
                )

                # ✅ CHECKPOINT: [STAGE_COMPLETE] - Success
                self.logger.info(
                    f"[STAGE_COMPLETE] ✅ Stage completion handled successfully",
                    extra={
                        'checkpoint': 'STAGE_COMPLETE_SUCCESS',
                        'job_id': job_id,
                        'stage': task_message.stage
                    }
                )

            except Exception as stage_error:
                # ✅ CHECKPOINT: [STAGE_ADV_FAIL] (FP3 fix already in place)
                self.logger.error(
                    f"[STAGE_ADV_FAIL] ❌ Stage advancement failed: {type(stage_error).__name__}: {stage_error}",
                    extra={
                        'checkpoint': 'STAGE_ADV_FAIL',
                        'job_id': job_id,
                        'stage': task_message.stage,
                        'error_type': type(stage_error).__name__,
                        'error_message': str(stage_error),
                        'traceback': traceback.format_exc()
                    }
                )
                # FP3 fix handles this - mark job as FAILED
                # ... existing code ...

        total_duration_ms = (time.time() - start_time) * 1000

        # ✅ CHECKPOINT: [TASK_START] - Complete
        self.logger.info(
            f"[TASK_START] ✅ Task processing complete",
            extra={
                'checkpoint': 'TASK_START_COMPLETE',
                'task_id': task_id,
                'total_duration_ms': total_duration_ms
            }
        )

        return {'success': True, 'stage_complete': completion.stage_complete}

    except Exception as e:
        total_duration_ms = (time.time() - start_time) * 1000

        # ✅ CHECKPOINT: [TASK_START] - Failed
        self.logger.error(
            f"[TASK_START] ❌ Task processing failed: {type(e).__name__}: {e}",
            extra={
                'checkpoint': 'TASK_START_FAILED',
                'task_id': task_id,
                'job_id': job_id,
                'duration_ms': total_duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc()
            }
        )
        raise
```

---

### **File: core/state_manager.py** (Database Operations)

**Location**: `complete_task_with_sql()` method (lines ~540-620)

```python
def complete_task_with_sql(
    self,
    task_id: str,
    job_id: str,
    stage: int,
    result: dict
):
    """
    Atomically complete task and check if stage is done.

    Enhanced with debug logging for SQL operation tracking.
    """
    # ✅ CHECKPOINT: [DB_ADVISORY_LOCK]
    self.logger.debug(
        f"[DB_ADVISORY_LOCK] 🎬 Acquiring advisory lock for job {job_id[:16]}... stage {stage}",
        extra={
            'checkpoint': 'DB_ADVISORY_LOCK',
            'task_id': task_id,
            'job_id': job_id,
            'stage': stage
        }
    )

    lock_start = time.time()

    try:
        repos = RepositoryFactory.create_repositories()
        completion_repo = repos['completion_detector']

        # Call PostgreSQL function with advisory lock
        completion = completion_repo.complete_task_and_check_stage(
            task_id=task_id,
            job_id=job_id,
            stage=stage,
            result_data=result
        )

        lock_duration_ms = (time.time() - lock_start) * 1000

        # ✅ CHECKPOINT: [DB_ADVISORY_LOCK] - Success
        self.logger.debug(
            f"[DB_ADVISORY_LOCK] ✅ Advisory lock acquired and released",
            extra={
                'checkpoint': 'DB_ADVISORY_LOCK_SUCCESS',
                'task_id': task_id,
                'job_id': job_id,
                'stage': stage,
                'duration_ms': lock_duration_ms,
                'stage_complete': completion.stage_complete,
                'remaining_tasks': completion.remaining_tasks
            }
        )

        return completion

    except Exception as e:
        lock_duration_ms = (time.time() - lock_start) * 1000

        # ✅ CHECKPOINT: [DB_ADVISORY_LOCK] - Failed
        self.logger.error(
            f"[DB_ADVISORY_LOCK] ❌ Advisory lock operation failed: {type(e).__name__}: {e}",
            extra={
                'checkpoint': 'DB_ADVISORY_LOCK_FAILED',
                'task_id': task_id,
                'job_id': job_id,
                'stage': stage,
                'duration_ms': lock_duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc()
            }
        )
        raise
```

**Similar pattern for**:
- `create_job_record()` - Add `[DB_QUERY]`, `[DB_COMMIT]` checkpoints
- `update_task_status_direct()` - Add `[DB_UPDATE]` checkpoints
- `mark_job_failed()` - Add `[JOB_FAILED]` checkpoint

---

### **File: infrastructure/service_bus.py** (Service Bus Operations)

**Location**: `send_message()` and `send_batch_messages()` methods

```python
def send_message(self, queue_name: str, message: str):
    """
    Send single message to Service Bus queue.

    Enhanced with debug logging for Service Bus tracking.
    """
    # ✅ CHECKPOINT: [SB_SEND]
    self.logger.debug(
        f"[SB_SEND] 🎬 Sending message to queue: {queue_name}",
        extra={
            'checkpoint': 'SB_SEND',
            'queue_name': queue_name,
            'message_length': len(message)
        }
    )

    send_start = time.time()

    try:
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            with client.get_queue_sender(queue_name) as sender:
                sender.send_messages(ServiceBusMessage(message))

        send_duration_ms = (time.time() - send_start) * 1000

        # ✅ CHECKPOINT: [SB_SEND] - Success
        self.logger.debug(
            f"[SB_SEND] ✅ Message sent successfully",
            extra={
                'checkpoint': 'SB_SEND_SUCCESS',
                'queue_name': queue_name,
                'duration_ms': send_duration_ms
            }
        )

    except Exception as e:
        send_duration_ms = (time.time() - send_start) * 1000

        # ✅ CHECKPOINT: [SB_SEND] - Failed
        self.logger.error(
            f"[SB_SEND] ❌ Failed to send message: {type(e).__name__}: {e}",
            extra={
                'checkpoint': 'SB_SEND_FAILED',
                'queue_name': queue_name,
                'duration_ms': send_duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e)
            }
        )
        raise

def send_batch_messages(self, queue_name: str, messages: List[str]):
    """
    Send batch of messages to Service Bus queue.

    Enhanced with debug logging for batch tracking.
    """
    # ✅ CHECKPOINT: [SB_BATCH]
    self.logger.debug(
        f"[SB_BATCH] 🎬 Sending batch of {len(messages)} messages to queue: {queue_name}",
        extra={
            'checkpoint': 'SB_BATCH',
            'queue_name': queue_name,
            'message_count': len(messages)
        }
    )

    batch_start = time.time()

    try:
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            with client.get_queue_sender(queue_name) as sender:
                batch = sender.create_message_batch()
                for message in messages:
                    batch.add_message(ServiceBusMessage(message))
                sender.send_messages(batch)

        batch_duration_ms = (time.time() - batch_start) * 1000

        # ✅ CHECKPOINT: [SB_BATCH] - Success
        self.logger.info(
            f"[SB_BATCH] ✅ Batch sent successfully",
            extra={
                'checkpoint': 'SB_BATCH_SUCCESS',
                'queue_name': queue_name,
                'message_count': len(messages),
                'duration_ms': batch_duration_ms,
                'messages_per_second': len(messages) / (batch_duration_ms / 1000)
            }
        )

    except Exception as e:
        batch_duration_ms = (time.time() - batch_start) * 1000

        # ✅ CHECKPOINT: [SB_BATCH] - Failed
        self.logger.error(
            f"[SB_BATCH] ❌ Failed to send batch: {type(e).__name__}: {e}",
            extra={
                'checkpoint': 'SB_BATCH_FAILED',
                'queue_name': queue_name,
                'message_count': len(messages),
                'duration_ms': batch_duration_ms,
                'error_type': type(e).__name__,
                'error_message': str(e)
            }
        )
        raise
```

---

## 🔍 Application Insights Queries

### Query 1: Job Execution Timeline

```kql
// Reconstruct full job execution timeline with all checkpoints
traces
| where timestamp >= ago(1h)
| where customDimensions.job_id == "YOUR_JOB_ID"
| extend checkpoint = tostring(customDimensions.checkpoint)
| extend duration_ms = todouble(customDimensions.duration_ms)
| project timestamp, checkpoint, duration_ms, message
| order by timestamp asc
```

### Query 2: Failed Jobs Without FAILED Checkpoint

```kql
// Find jobs that disappeared without reaching [JOB_COMPLETE] or [JOB_FAILED]
let started_jobs = traces
| where timestamp >= ago(1h)
| where customDimensions.checkpoint == "JOB_START"
| extend job_id = tostring(customDimensions.job_id)
| project job_id, start_time = timestamp;

let completed_jobs = traces
| where timestamp >= ago(1h)
| where customDimensions.checkpoint in ("JOB_COMPLETE", "JOB_FAILED")
| extend job_id = tostring(customDimensions.job_id)
| project job_id;

started_jobs
| join kind=leftanti completed_jobs on job_id
| project job_id, start_time
| order by start_time desc
```

### Query 3: Task Processing Bottlenecks

```kql
// Find tasks with longest processing times
traces
| where timestamp >= ago(1h)
| where customDimensions.checkpoint == "TASK_EXEC"
| extend task_id = tostring(customDimensions.task_id)
| extend handler_name = tostring(customDimensions.handler_name)
| extend duration_ms = todouble(customDimensions.duration_ms)
| project timestamp, task_id, handler_name, duration_ms
| order by duration_ms desc
| take 20
```

### Query 4: Stage Advancement Failures (FP3)

```kql
// Find all stage advancement failures
traces
| where timestamp >= ago(1h)
| where customDimensions.checkpoint == "STAGE_ADV_FAIL"
| extend job_id = tostring(customDimensions.job_id)
| extend stage = toint(customDimensions.stage)
| extend error_type = tostring(customDimensions.error_type)
| project timestamp, job_id, stage, error_type, message
| order by timestamp desc
```

### Query 5: Service Bus Send Failures

```kql
// Find Service Bus communication failures
traces
| where timestamp >= ago(1h)
| where customDimensions.checkpoint in ("SB_SEND_FAILED", "SB_BATCH_FAILED")
| extend queue_name = tostring(customDimensions.queue_name)
| extend error_type = tostring(customDimensions.error_type)
| project timestamp, queue_name, error_type, message
| order by timestamp desc
```

### Query 6: "Last Task" Detection Events

```kql
// Track "last task turns out lights" pattern
traces
| where timestamp >= ago(1h)
| where customDimensions.checkpoint == "STAGE_LAST_TASK"
| extend job_id = tostring(customDimensions.job_id)
| extend stage = toint(customDimensions.stage)
| extend total_tasks = toint(customDimensions.total_tasks)
| project timestamp, job_id, stage, total_tasks
| order by timestamp desc
```

---

## 📊 Checkpoint Summary Matrix

| Checkpoint | File | Method | Success Criteria | Failure Indicator |
|-----------|------|--------|-----------------|------------------|
| `[JOB_SUBMIT]` | function_app.py | submit_job() | Job record created | Exception before DB insert |
| `[JOB_VALIDATE]` | function_app.py | submit_job() | Parameters validated | Pydantic ValidationError |
| `[JOB_QUEUED]` | function_app.py | submit_job() | Message sent to SB | ServiceBusError |
| `[JOB_START]` | function_app.py | process_service_bus_job() | Message parsed | Parsing exception |
| `[JOB_REGISTRY_LOOKUP]` | core/machine.py | process_job_message() | Job class found | Unknown job_type |
| `[STAGE_TASKS_GEN]` | core/machine.py | process_job_message() | Tasks created | ValueError from job class |
| `[STAGE_BATCH_Q]` | core/machine.py | process_job_message() | Tasks queued | ServiceBusError |
| `[TASK_START]` | function_app.py | process_service_bus_task() | Message parsed | Parsing exception |
| `[TASK_STATUS_UPD]` | core/machine.py | process_task_message() | Status → PROCESSING | DB update failed (FP2) |
| `[TASK_EXEC]` | core/machine.py | process_task_message() | Handler executed | Handler exception |
| `[TASK_HANDLER_OK]` | core/machine.py | process_task_message() | result.success=True | result.success=False |
| `[TASK_COMPLETE]` | core/machine.py | process_task_message() | Task marked COMPLETED | DB error |
| `[DB_ADVISORY_LOCK]` | core/state_manager.py | complete_task_with_sql() | Lock acquired | psycopg error |
| `[STAGE_LAST_TASK]` | core/machine.py | process_task_message() | Last task detected | Race condition (prevented by lock) |
| `[STAGE_COMPLETE]` | core/machine.py | _handle_stage_completion() | Stage advanced | Stage advancement error (FP3) |
| `[SB_SEND]` | infrastructure/service_bus.py | send_message() | Message sent | ServiceBusError |
| `[SB_BATCH]` | infrastructure/service_bus.py | send_batch_messages() | Batch sent | ServiceBusError |

---

## 🚀 Quick Start: Enable Debug Logging

### 1. Set Environment Variable

```bash
# Azure Functions Configuration Portal
DEBUG_LOGGING=true
AZURE_FUNCTIONS_LOGGING_LEVEL=DEBUG
```

### 2. Update Logging Configuration

**File**: `util_logger.py`

```python
import os

def create_logger(component_type: ComponentType, name: str):
    """Create logger with debug checkpoints enabled."""
    logger = logging.getLogger(f"{component_type.value}.{name}")

    # Check if debug logging enabled
    if os.getenv('DEBUG_LOGGING', 'false').lower() == 'true':
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    return logger
```

### 3. Deploy and Test

```bash
# Deploy to Azure
func azure functionapp publish rmhgeoapibeta --python --build remote

# Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "debug test", "n": 3}'

# Query logs in Application Insights
az monitor app-insights query \
  --app 829adb94-5f5c-46ae-9f00-18e731529222 \
  --analytics-query "traces | where timestamp >= ago(15m) | where message contains 'CHECKPOINT' | order by timestamp desc" \
  --offset 0h
```

---

## ⚡ Performance Impact

**Estimated overhead per job**:
- **Checkpoints logged**: ~40-60 (depending on stages/tasks)
- **Average log size**: 500 bytes per checkpoint
- **Total data**: ~20-30 KB per job
- **Latency impact**: <50ms total (2-3ms per checkpoint)

**Recommendation**: Enable debug logging in DEV/TEST environments only. For production, use INFO level and enable DEBUG only when investigating specific issues.

---

**Last Updated**: 5 NOV 2025
**Status**: Ready for implementation
**Related**: WORKFLOW_FAILURE_ANALYSIS.md (9 failure points, FP1-3 already fixed)
**Next**: Implement checkpoints in core/machine.py and function_app.py
