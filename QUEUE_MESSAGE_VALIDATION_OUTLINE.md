# Queue Message Boundary Validation & Error Handling Implementation Outline

**Date**: 21 SEP 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive plan to prevent poison queue messages through proper validation and error handling

## 📍 1. Current Queue Message Flow Analysis

### 1.1 Where Messages Are SENT (4 locations in controller_base.py)

#### Location 1: Initial Job Submission (line 762)
```python
# controller_base.py:submit_job()
queue_message = JobQueueMessage(
    job_id=job_id,
    job_type=job_type,
    stage=1,
    parameters=validated_params
)
message_json = queue_message.model_dump_json()
queue_client.send_message(message_json)  # → geospatial-jobs queue
```

#### Location 2: Task Creation for Stage (line 1409, 1657)
```python
# controller_base.py:process_job_queue_message()
task_message = task_def.to_queue_message()  # Creates TaskQueueMessage
message_json = task_message.model_dump_json()
queue_client.send_message(message_json)  # → geospatial-tasks queue
```

#### Location 3: Stage Advancement (line 2142)
```python
# controller_base.py:_handle_stage_completion()
job_message = JobQueueMessage(
    job_id=job_id,
    job_type=job_record.job_type,
    stage=next_stage,
    parameters=job_record.parameters
)
message_json = job_message.model_dump_json()
queue_client.send_message(message_json)  # → geospatial-jobs queue
```

### 1.2 Where Messages Are RECEIVED (2 queue triggers in function_app.py)

#### Trigger 1: Job Queue (line 429-463)
```python
@app.queue_trigger(queue_name="geospatial-jobs")
def process_job_queue(msg: func.QueueMessage):
    message_content = msg.get_body().decode('utf-8')
    job_message = JobQueueMessage.model_validate_json(message_content)  # ⚠️ Can fail!
    controller = JobFactory.create_controller(job_message.job_type)
    result = controller.process_job_queue_message(job_message)
```

#### Trigger 2: Task Queue (line 466-501)
```python
@app.queue_trigger(queue_name="geospatial-tasks")
def process_task_queue(msg: func.QueueMessage):
    message_content = msg.get_body().decode('utf-8')
    task_message = TaskQueueMessage.model_validate_json(message_content)  # ⚠️ Can fail!
    controller = JobFactory.create_controller(task_message.job_type)
    result = controller.process_task_queue_message(task_message)
```

## 🔍 2. Current State Assessment

### 2.1 Are Messages Using Pydantic as Intended?

**YES - Partially ✅**
- ✅ JobQueueMessage and TaskQueueMessage are Pydantic models (schema_queue.py)
- ✅ Messages are serialized with model_dump_json()
- ✅ Messages are parsed with model_validate_json()

**BUT - Missing Error Handling ❌**
- ❌ No try-catch around model_validate_json() - ValidationError goes unhandled
- ❌ No logging of raw message before parsing
- ❌ No job/task status update on parsing failure
- ❌ Generic Exception catch is too broad

### 2.2 Current Try-Except Granularity

**Current State: Too Coarse**
```python
try:
    # Parse message
    # Get controller
    # Process entire job/task (100+ lines of logic)
except ValueError as e:
    logger.error(f"❌ Invalid message or job type: {e}")
    raise  # Message goes to poison queue!
except Exception as e:
    logger.error(f"❌ Job processing failed: {e}")
    raise  # Message goes to poison queue!
```

**Problems:**
1. Can't distinguish parsing errors from business logic errors
2. No error recording in database before poison queue
3. No correlation between poison message and job/task

## 📋 3. Proposed Granular Error Handling Structure

### 3.1 Queue Trigger Improvements

```python
@app.queue_trigger(queue_name="geospatial-jobs")
def process_job_queue(msg: func.QueueMessage) -> None:
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "QueueProcessor.Jobs")
    logger.info("🔄 Job queue trigger activated")

    # PHASE 1: Message Extraction
    try:
        message_content = msg.get_body().decode('utf-8')
        logger.debug(f"📨 Raw message content: {message_content[:500]}")  # Log first 500 chars
    except Exception as e:
        logger.error(f"❌ Failed to extract message body: {e}")
        # Can't update job - we don't know the job_id yet
        raise  # Let it go to poison queue with clear log

    # PHASE 2: Message Parsing & Validation
    job_message = None
    try:
        job_message = JobQueueMessage.model_validate_json(message_content)
        logger.info(f"✅ Parsed job message: job_id={job_message.job_id[:16]}...")
    except ValidationError as e:
        logger.error(f"❌ Invalid job message format: {e}")
        logger.error(f"📋 Failed message content: {message_content}")

        # Try to extract job_id for error recording
        try:
            import json
            raw_data = json.loads(message_content)
            job_id = raw_data.get('job_id')
            if job_id:
                _mark_job_failed_from_queue_error(job_id, f"Invalid queue message: {e}")
        except:
            pass  # Can't extract job_id, let it go to poison

        raise  # Validation errors should poison

    # PHASE 3: Controller Creation
    controller = None
    try:
        controller = JobFactory.create_controller(job_message.job_type)
    except ValueError as e:
        logger.error(f"❌ Unknown job type: {job_message.job_type}")
        _mark_job_failed_from_queue_error(
            job_message.job_id,
            f"Unknown job type: {job_message.job_type}"
        )
        raise  # Unknown job types should poison

    # PHASE 4: Job Processing
    try:
        result = controller.process_job_queue_message(job_message)
        logger.info(f"✅ Job processing complete: {result}")
    except Exception as e:
        logger.error(f"❌ Job processing failed: {e}")
        logger.debug(f"📍 Error traceback: {traceback.format_exc()}")
        # Controller should have already marked job as FAILED
        # Check if it did:
        if not _is_job_marked_failed(job_message.job_id):
            _mark_job_failed_from_queue_error(
                job_message.job_id,
                f"Processing failed: {e}"
            )
        raise  # Let processing errors poison after recording
```

### 3.2 Controller Method Improvements

```python
def process_job_queue_message(self, job_message: JobQueueMessage) -> Dict[str, Any]:
    """
    Enhanced with granular error handling at each critical step.
    """

    # STEP 1: Repository Setup
    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']
    except Exception as e:
        error_msg = f"Repository initialization failed: {e}"
        self.logger.error(error_msg)
        # Can't update job without repository!
        raise RuntimeError(error_msg)

    # STEP 2: Job Record Retrieval
    job_record = None
    try:
        job_record = job_repo.get_job(job_message.job_id)
        if not job_record:
            raise ValueError(f"Job not found: {job_message.job_id}")
    except Exception as e:
        error_msg = f"Failed to retrieve job: {e}"
        self.logger.error(error_msg)
        try:
            job_repo.update_job_status_with_validation(
                job_id=job_message.job_id,
                new_status=JobStatus.FAILED,
                additional_updates={'error_details': error_msg}
            )
        except:
            pass  # Best effort
        raise ValueError(error_msg)

    # STEP 3: Status Validation
    try:
        if job_record.status == JobStatus.COMPLETED:
            return {'status': 'skipped', 'reason': 'already_completed'}

        if job_record.stage > job_message.stage:
            return {'status': 'skipped', 'reason': 'stage_already_processed'}
    except Exception as e:
        error_msg = f"Status validation failed: {e}"
        self._mark_job_failed(job_message.job_id, error_msg, job_repo)
        raise

    # STEP 4: Previous Stage Results (if needed)
    previous_stage_results = None
    if job_message.stage > 1:
        try:
            previous_stage_results = self._validate_and_get_stage_results(
                job_record=job_record,
                stage_number=job_message.stage - 1
            )
        except (ValueError, KeyError) as e:
            error_msg = f"Stage {job_message.stage - 1} results invalid: {e}"
            self._mark_job_failed(job_message.job_id, error_msg, job_repo)
            raise ValueError(error_msg) from e

    # STEP 5: Task Creation
    tasks = []
    try:
        tasks = self.create_stage_tasks(
            stage_number=job_message.stage,
            job_id=job_message.job_id,
            job_parameters=job_message.parameters,
            previous_stage_results=previous_stage_results
        )
        if not tasks:
            raise RuntimeError(f"No tasks created for stage {job_message.stage}")
    except Exception as e:
        error_msg = f"Task creation failed: {e}"
        self._mark_job_failed(job_message.job_id, error_msg, job_repo)
        raise RuntimeError(error_msg) from e

    # STEP 6: Queue Setup
    queue_client = None
    try:
        credential = DefaultAzureCredential()
        queue_service = QueueServiceClient(
            account_url=config.queue_service_url,
            credential=credential
        )
        queue_client = queue_service.get_queue_client(config.task_processing_queue)
    except Exception as e:
        error_msg = f"Queue client setup failed: {e}"
        self._mark_job_failed(job_message.job_id, error_msg, job_repo)
        raise RuntimeError(error_msg)

    # STEP 7: Task Queueing (per-task error handling)
    tasks_queued = 0
    tasks_failed = 0

    for task_def in tasks:
        try:
            # Check if task exists
            existing_task = task_repo.get_task(task_def.task_id)
            if existing_task:
                if existing_task.status != TaskStatus.FAILED:
                    tasks_queued += 1
                continue

            # Create task record
            task_record = task_def.to_task_record()
            success = task_repo.create_task(task_record)
            if not success:
                raise RuntimeError(f"Database insertion failed for {task_def.task_id}")

            # Queue task message
            task_message = task_def.to_queue_message()
            message_json = task_message.model_dump_json()
            queue_client.send_message(message_json)
            tasks_queued += 1

        except Exception as e:
            self.logger.error(f"Failed to queue task {task_def.task_id}: {e}")
            tasks_failed += 1
            # Continue with other tasks

    # STEP 8: Final Status Update
    if tasks_queued > 0:
        try:
            job_repo.update_job_status_with_validation(
                job_id=job_message.job_id,
                new_status=JobStatus.PROCESSING
            )
        except Exception as e:
            self.logger.error(f"Failed to update job status: {e}")
            # Non-critical, continue

    if tasks_failed == len(tasks):
        error_msg = f"All {tasks_failed} tasks failed to queue"
        self._mark_job_failed(job_message.job_id, error_msg, job_repo)
        raise RuntimeError(error_msg)

    return {
        'status': 'success',
        'tasks_queued': tasks_queued,
        'tasks_failed': tasks_failed
    }
```

## 🛡️ 4. Poison Queue Handler Design

### 4.1 Current Situation
- **Existing**: HTTP trigger for poison queue monitoring (trigger_poison_monitor.py)
- **Missing**: Actual queue trigger for poison queues

### 4.2 Proposed Poison Queue Trigger

```python
@app.queue_trigger(
    arg_name="msg",
    queue_name="geospatial-jobs-poison",  # Poison queue for jobs
    connection="AzureWebJobsStorage")
def process_poison_job_queue(msg: func.QueueMessage) -> None:
    """
    Handle poison job messages with comprehensive logging and database updates.

    CRITICAL LOGIC:
    - Check if job is already FAILED = Expected poison (our error handling worked)
    - Job NOT failed = UNHANDLED ERROR (requires special attention)

    Goals:
    1. Distinguish between expected and unexpected poison messages
    2. Extract as much information as possible
    3. Update job record ONLY if not already failed
    4. Send alert for unhandled errors
    5. Clean up related resources
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PoisonHandler.Jobs")
    logger.error("☠️ POISON JOB MESSAGE RECEIVED")

    # Extract raw content
    try:
        message_content = msg.get_body().decode('utf-8')
        logger.error(f"☠️ Poison message content: {message_content}")
    except:
        logger.error("☠️ Could not decode poison message body")
        return

    # Try to extract job_id
    job_id = None
    job_type = None
    stage = None
    error_reason = "Message moved to poison queue after 5 failed attempts"

    try:
        # Attempt JSON parsing
        import json
        data = json.loads(message_content)
        job_id = data.get('job_id')
        job_type = data.get('job_type')
        stage = data.get('stage')

        logger.error(f"☠️ Poison job identified: id={job_id}, type={job_type}, stage={stage}")

    except json.JSONDecodeError as e:
        logger.error(f"☠️ Poison message is not valid JSON: {e}")
        error_reason = f"Invalid JSON in queue message: {e}"

    except Exception as e:
        logger.error(f"☠️ Failed to parse poison message: {e}")
        error_reason = f"Failed to parse message: {e}"

    # Update job if we have an ID
    if job_id:
        try:
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']

            # CRITICAL: Check current job status FIRST
            job = job_repo.get_job(job_id)

            if not job:
                logger.error(f"☠️🚨 CRITICAL: Poison message for non-existent job {job_id}")
                # This should never happen - indicates data corruption
                await send_critical_alert(f"Poison message for non-existent job {job_id}")
                return

            if job.status == JobStatus.FAILED:
                # EXPECTED POISON - Our error handling worked correctly
                logger.info(f"☠️✅ Expected poison message for already-failed job {job_id}")
                logger.debug(f"Job was failed with: {job.error_details}")
                # Just dispose of the message, no action needed
                return

            elif job.status == JobStatus.COMPLETED:
                # UNEXPECTED - Completed jobs shouldn't have poison messages
                logger.warning(f"☠️⚠️ WARNING: Poison message for COMPLETED job {job_id}")
                logger.warning(f"This indicates a logic error - investigating...")
                # Don't update the job, but log for investigation
                await send_warning_alert(f"Poison message for completed job {job_id}")
                return

            else:
                # UNHANDLED ERROR - Job is QUEUED/PROCESSING but message went to poison
                logger.error(f"☠️🚨 CRITICAL UNHANDLED ERROR: Job {job_id} status={job.status}")
                logger.error(f"☠️🚨 This job was NOT marked as failed before poison queue!")

                # This is the critical case - our error handling missed something
                job_repo.update_job_status_with_validation(
                    job_id=job_id,
                    new_status=JobStatus.FAILED,
                    additional_updates={
                        'error_details': f"UNHANDLED POISON QUEUE ERROR: {error_reason}",
                        'poison_queue_at': datetime.now(timezone.utc).isoformat(),
                        'poison_message': message_content[:1000],  # Store first 1000 chars
                        'unhandled_error': True  # Flag for investigation
                    }
                )

                # Send critical alert
                await send_critical_alert(
                    f"UNHANDLED POISON: Job {job_id} reached poison queue without being marked failed. "
                    f"Previous status: {job.status}. This indicates a gap in error handling."
                )

                logger.error(f"☠️ Job {job_id} marked as FAILED due to UNHANDLED poison queue error")

            # Mark all pending tasks as failed
            task_repo = repos['task_repo']
            tasks = task_repo.list_tasks_for_job(job_id)
            for task in tasks:
                if task.status in [TaskStatus.QUEUED, TaskStatus.PROCESSING]:
                    task_repo.update_task(
                        task_id=task.task_id,
                        updates={
                            'status': TaskStatus.FAILED,
                            'error_details': 'Job failed - poison queue'
                        }
                    )

        except Exception as e:
            logger.error(f"☠️ Failed to update job/tasks for poison message: {e}")

    # Send alert (future enhancement)
    # await send_poison_alert(job_id, job_type, error_reason)

    # Log to monitoring system
    logger.error(
        f"☠️ POISON QUEUE SUMMARY: job_id={job_id}, type={job_type}, "
        f"stage={stage}, reason={error_reason}"
    )

@app.queue_trigger(
    arg_name="msg",
    queue_name="geospatial-tasks-poison",  # Poison queue for tasks
    connection="AzureWebJobsStorage")
def process_poison_task_queue(msg: func.QueueMessage) -> None:
    """
    Handle poison task messages.
    """
    logger = LoggerFactory.create_logger(ComponentType.SERVICE, "PoisonHandler.Tasks")
    logger.error("☠️ POISON TASK MESSAGE RECEIVED")

    # Similar structure to job poison handler
    # Extract task_id, update task and parent job if needed
```

## 📊 5. Implementation Priority & Testing

### 5.1 Implementation Order

1. **IMMEDIATE - Add Logging**
   - Log raw messages before parsing
   - Add correlation IDs
   - Log each phase of processing

2. **HIGH - Granular Try-Catch in Triggers**
   - Separate parsing from processing
   - Add helper functions for error recording
   - Ensure database updates before poison

3. **HIGH - Granular Try-Catch in Controllers**
   - Break down process_job_queue_message()
   - Break down process_task_queue_message()
   - Add _mark_job_failed() helper method

4. **MEDIUM - Poison Queue Handlers**
   - Implement poison queue triggers
   - Extract maximum information
   - Update records retroactively

5. **LOW - Monitoring & Alerts**
   - Dashboard for poison queue stats
   - Automated alerts for poison messages
   - Retry mechanisms for transient errors

### 5.2 Testing Strategy

#### Test Cases:
1. **Malformed JSON** - Send invalid JSON to queue
2. **Missing Fields** - Send JSON without required fields
3. **Invalid Types** - Send wrong data types in fields
4. **Unknown Job Type** - Send non-existent job_type
5. **Database Errors** - Simulate repository failures
6. **Queue Errors** - Simulate queue client failures
7. **Task Creation Errors** - Force task creation to fail
8. **Concurrent Processing** - Send duplicate messages

#### Success Criteria:
- ✅ Every poison message has corresponding error in job/task record
- ✅ Clear log trail from receipt to error recording
- ✅ Poison queue handler can recover partial information
- ✅ No silent failures - all errors logged and recorded

## 🔑 Key Helper Functions to Add

```python
def _mark_job_failed_from_queue_error(job_id: str, error_msg: str) -> None:
    """Helper to mark job as failed when queue processing fails."""
    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job_repo.update_job_status_with_validation(
            job_id=job_id,
            new_status=JobStatus.FAILED,
            additional_updates={
                'error_details': f"Queue processing error: {error_msg}",
                'failed_at': datetime.now(timezone.utc).isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as failed: {e}")

def _is_job_marked_failed(job_id: str) -> bool:
    """Check if job is already marked as failed."""
    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job = job_repo.get_job(job_id)
        return job and job.status == JobStatus.FAILED
    except:
        return False

def _extract_job_id_from_raw_message(message_content: str) -> Optional[str]:
    """Try to extract job_id from potentially malformed message."""
    try:
        import json
        data = json.loads(message_content)
        return data.get('job_id')
    except:
        # Try regex as fallback
        import re
        match = re.search(r'"job_id"\s*:\s*"([^"]+)"', message_content)
        if match:
            return match.group(1)
    return None
```

## 📝 Summary

**Current Gaps:**
1. No logging of raw messages before parsing
2. Too coarse try-catch blocks
3. No error recording before poison queue
4. No poison queue processing

**Proposed Solutions:**
1. Add comprehensive logging at entry points
2. Implement granular try-catch with phases
3. Always update job/task records before raising
4. Add poison queue triggers for recovery

**Expected Outcome:**
Zero messages in poison queue without corresponding database error records.