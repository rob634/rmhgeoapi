# ============================================================================
# CLAUDE CONTEXT - CORE ORCHESTRATOR
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component - Universal orchestrator for all workflows
# PURPOSE: Universal job orchestrator using composition to avoid God Class
# EXPORTS: CoreMachine - coordinates all workflows without job-specific logic
# INTERFACES: Uses Workflow ABC, Task ABC, StateManager, repositories
# PYDANTIC_MODELS: TaskQueueMessage, JobQueueMessage, TaskResult
# DEPENDENCIES: jobs.registry, services.registry, core, infrastructure
# SOURCE: Extracted from controller_service_bus_hello.py (1,019 lines → 450)
# SCOPE: Universal coordination for ALL jobs via delegation
# VALIDATION: Contract enforcement for type safety
# PATTERNS: Coordinator pattern, Composition over Inheritance
# ENTRY_POINTS: process_job_message(), process_task_message()
# INDEX: CoreMachine:50, Job Processing:150, Task Processing:350
# ============================================================================

"""
CoreMachine - Universal Job Orchestrator

This is the heart of Epoch 4's declarative architecture. It avoids the God Class
anti-pattern by using composition and delegation instead of inheritance.

Key Principles:
1. **Composition**: All dependencies injected, none created internally
2. **Single Responsibility**: ONLY coordinate, never execute business logic
3. **Delegation**: Specialized components handle all actual work
4. **Stateless**: No job-specific state stored in CoreMachine

Size Comparison:
- BaseController (God Class): 2,290 lines, 34 methods
- CoreMachine (Coordinator): ~450 lines, 6 methods (80% reduction)

The difference? BaseController does everything. CoreMachine coordinates everything.

Author: Robert and Geospatial Claude Legion
Date: 30 SEP 2025
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import time
import traceback

# REMOVED: Decorator-based registries (caused import timing failures)
# from jobs.registry import get_workflow
# from services.registry import get_task
#
# Now using explicit registration - registries passed to constructor

# Core components (composition, not inheritance)
from core import StateManager, OrchestrationManager

# Pydantic models
from core.models import (
    JobRecord,
    TaskRecord,
    TaskDefinition,
    JobStatus,
    TaskStatus,
    TaskResult,
    JobExecutionContext
)
from core.schema.queue import JobQueueMessage, TaskQueueMessage

# Infrastructure
from infrastructure import RepositoryFactory

# Configuration
from config import AppConfig

# Logging
from util_logger import LoggerFactory, ComponentType

# Exceptions
from exceptions import (
    ContractViolationError,
    BusinessLogicError,
    TaskExecutionError
)


class CoreMachine:
    """
    Universal job orchestrator using composition to avoid God Class.

    This class ONLY coordinates. All actual work is delegated to:
    - Workflow instances (define stages and parameters)
    - Task handlers (execute business logic)
    - StateManager (database operations)
    - Repositories (external services)

    Usage:
        machine = CoreMachine()

        # Process job message from queue
        machine.process_job_message(job_message)

        # Process task message from queue
        machine.process_task_message(task_message)

    Implementation Details:
    - NO job-specific code (all via Workflow instances)
    - NO task execution logic (all via Task handlers)
    - NO database operations (all via StateManager)
    - ONLY coordination and error handling
    """

    # Batch configuration (applied universally)
    BATCH_SIZE = 100  # Service Bus limit
    DEFAULT_BATCH_THRESHOLD = 50  # Use batch if >= 50 tasks

    def __init__(
        self,
        all_jobs: Dict[str, Any],
        all_handlers: Dict[str, callable],
        state_manager: Optional[StateManager] = None,
        config: Optional[AppConfig] = None
    ):
        """
        Initialize CoreMachine with EXPLICIT registries (no decorator magic!).

        CRITICAL: Registries must be passed explicitly to avoid import timing issues.
        Previous decorator-based approach failed because modules weren't imported (10 SEP 2025).

        Args:
            all_jobs: ALL_JOBS dict from jobs/__init__.py (explicit job registry)
            all_handlers: ALL_HANDLERS dict from services/__init__.py (explicit handler registry)
            state_manager: Database state manager (injected for testability)
            config: Application configuration (injected for testability)
        """
        # EXPLICIT REGISTRIES - No decorator magic!
        self.jobs_registry = all_jobs
        self.handlers_registry = all_handlers

        # Composition: Inject dependencies
        self.state_manager = state_manager or StateManager()
        self.config = config or AppConfig.from_environment()

        # Logging
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "CoreMachine"
        )

        self.logger.info(f"🤖 CoreMachine initialized - {len(all_jobs)} jobs, {len(all_handlers)} handlers registered")
        self.logger.debug(f"   Registered jobs: {list(all_jobs.keys())}")
        self.logger.debug(f"   Registered handlers: {list(all_handlers.keys())}")

    # ========================================================================
    # JOB PROCESSING - Entry point for job queue messages
    # ========================================================================

    def process_job_message(self, job_message: JobQueueMessage) -> Dict[str, Any]:
        """
        Process job message by creating and queuing stage tasks.

        This is called when a job message arrives from the job queue.
        It creates tasks for the specified stage and queues them.

        Flow:
        1. Get workflow definition via registry
        2. Validate parameters
        3. Create tasks for current stage
        4. Queue tasks (batch or individual)
        5. Update job status to PROCESSING

        Args:
            job_message: Message from job queue

        Returns:
            Result dict with success status and metadata

        Raises:
            ContractViolationError: If message is wrong type
            BusinessLogicError: If workflow or queuing fails
        """
        # CONTRACT ENFORCEMENT
        if not isinstance(job_message, JobQueueMessage):
            raise ContractViolationError(
                f"job_message must be JobQueueMessage, got {type(job_message).__name__}"
            )

        self.logger.info(f"🎬 COREMACHINE STEP 1: Starting process_job_message")
        self.logger.info(f"   job_id={job_message.job_id[:16]}..., job_type={job_message.job_type}, stage={job_message.stage}")

        # Step 1: Get job class from EXPLICIT registry
        try:
            self.logger.debug(f"📋 COREMACHINE STEP 2: Looking up job_type '{job_message.job_type}' in registry...")
            if job_message.job_type not in self.jobs_registry:
                available = list(self.jobs_registry.keys())
                error_msg = f"Unknown job type: '{job_message.job_type}'. Available: {available}"
                self.logger.error(f"❌ COREMACHINE STEP 2 FAILED: {error_msg}")
                self._mark_job_failed(job_message.job_id, error_msg)
                raise BusinessLogicError(error_msg)

            job_class = self.jobs_registry[job_message.job_type]
            self.logger.info(f"✅ COREMACHINE STEP 2: Job class found - {job_class.__name__}")
        except BusinessLogicError:
            raise
        except Exception as e:
            self.logger.error(f"❌ COREMACHINE STEP 2 FAILED: Registry lookup error: {e}")
            raise

        # Step 2: Get job record from database
        try:
            self.logger.debug(f"💾 COREMACHINE STEP 3: Fetching job record from database...")
            repos = RepositoryFactory.create_repositories()
            job_record = repos['job_repo'].get_job(job_message.job_id)
            if not job_record:
                raise ValueError(f"Job {job_message.job_id} not found in database")
            self.logger.info(f"✅ COREMACHINE STEP 3: Job record retrieved - parameters={list(job_record.parameters.keys())}")
        except Exception as e:
            self.logger.error(f"❌ COREMACHINE STEP 3 FAILED: Database error: {e}")
            raise BusinessLogicError(f"Job record not found: {e}")

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
            # Continue - not critical

        # Step 4: Fetch previous stage results (for fan-out pattern)
        previous_results = None
        if job_message.stage > 1:
            try:
                self.logger.debug(f"📊 COREMACHINE STEP 4.5: Fetching Stage {job_message.stage - 1} results for fan-out...")
                previous_results = self._get_completed_stage_results(
                    job_message.job_id,
                    job_message.stage - 1
                )
                self.logger.info(f"✅ COREMACHINE STEP 4.5: Retrieved {len(previous_results)} completed task results from Stage {job_message.stage - 1}")
            except Exception as e:
                self.logger.warning(f"⚠️ COREMACHINE STEP 4.5: Could not fetch previous results: {e}")
                # Continue without previous results - job may not need them

        # Step 5: Generate task definitions (in-memory only, not persisted yet)
        try:
            self.logger.debug(f"🏗️ COREMACHINE STEP 5: Generating task definitions for stage {job_message.stage}...")
            tasks = job_class.create_tasks_for_stage(
                job_message.stage,
                job_record.parameters,
                job_message.job_id,
                previous_results=previous_results  # NEW: Pass previous results for fan-out
            )
            self.logger.info(f"✅ COREMACHINE STEP 5: Generated {len(tasks)} task definitions (in-memory)")
            self.logger.debug(f"   Task IDs: {[t['task_id'] for t in tasks]}")
        except Exception as e:
            self.logger.error(f"❌ COREMACHINE STEP 5 FAILED: Task generation error: {e}")
            self.logger.error(f"   Traceback: {traceback.format_exc()}")
            self._mark_job_failed(job_message.job_id, f"Task generation failed: {e}")
            raise BusinessLogicError(f"Failed to generate tasks: {e}")

        # Step 5: Convert plain dicts to TaskDefinition objects (Pydantic validation)
        try:
            self.logger.debug(f"🔄 COREMACHINE STEP 6: Converting {len(tasks)} task dicts to TaskDefinition objects...")

            task_definitions = []
            for idx, task_dict in enumerate(tasks):
                # Convert plain dict → TaskDefinition (adds context + validates with Pydantic)
                task_def = TaskDefinition(
                    task_id=task_dict['task_id'],
                    task_type=task_dict['task_type'],
                    parameters=task_dict['parameters'],
                    metadata=task_dict.get('metadata', {}),
                    # Add context from job message (missing from plain dicts)
                    parent_job_id=job_message.job_id,
                    job_type=job_message.job_type,
                    stage=job_message.stage,
                    task_index=str(idx)
                )
                task_definitions.append(task_def)

            self.logger.info(f"✅ COREMACHINE STEP 6: Converted {len(task_definitions)} dicts to TaskDefinition (Pydantic validated)")

        except KeyError as e:
            self.logger.error(f"❌ COREMACHINE STEP 6 FAILED: Task dict missing required field: {e}")
            self.logger.error(f"   Task dict structure: {list(tasks[0].keys()) if tasks else 'N/A'}")
            self._mark_job_failed(job_message.job_id, f"Task dict missing field: {e}")
            raise BusinessLogicError(f"Invalid task dict structure: {e}")
        except Exception as e:
            self.logger.error(f"❌ COREMACHINE STEP 6 FAILED: TaskDefinition conversion error: {e}")
            self.logger.error(f"   Traceback: {traceback.format_exc()}")
            self._mark_job_failed(job_message.job_id, f"TaskDefinition conversion failed: {e}")
            raise BusinessLogicError(f"Failed to convert tasks to TaskDefinition: {e}")

        # Step 6: Queue tasks (database + Service Bus) using existing helper
        try:
            self.logger.debug(f"📤 COREMACHINE STEP 7: Queueing {len(task_definitions)} tasks...")

            # Use individual queueing helper (batch helper exists for high-volume jobs)
            # This helper handles:
            # 1. TaskDefinition → TaskRecord (database persistence)
            # 2. TaskDefinition → TaskQueueMessage (Service Bus queueing)
            # 3. Error handling and rollback
            result = self._individual_queue_tasks(
                task_definitions,
                job_message.job_id,
                job_message.stage
            )

            # Check result
            if result['status'] == 'partial':
                self.logger.warning(f"⚠️ COREMACHINE STEP 7: Partial success - {result['tasks_queued']}/{result['total_tasks']} tasks queued")
            else:
                self.logger.info(f"✅ COREMACHINE STEP 7: All {result['tasks_queued']} tasks queued successfully")

            return {
                'success': True,
                'job_id': job_message.job_id,
                'stage': job_message.stage,
                'tasks_created': result['tasks_queued'],
                'tasks_failed': result.get('tasks_failed', 0)
            }

        except Exception as e:
            self.logger.error(f"❌ COREMACHINE STEP 7 FAILED: Task queueing error: {e}")
            self.logger.error(f"   Traceback: {traceback.format_exc()}")
            self._mark_job_failed(job_message.job_id, f"Task queueing failed: {e}")
            raise BusinessLogicError(f"Failed to queue tasks: {e}")

    # ========================================================================
    # TASK PROCESSING - Entry point for task queue messages
    # ========================================================================

    def process_task_message(self, task_message: TaskQueueMessage) -> Dict[str, Any]:
        """
        Process task message by executing the task handler.

        This is called when a task message arrives from the task queue.
        It executes the task, updates state, and checks for stage/job completion.

        Flow:
        1. Get task handler via registry
        2. Execute task handler
        3. Complete task and check stage (atomic via advisory lock)
        4. If stage complete: advance to next stage OR complete job

        Args:
            task_message: Message from task queue

        Returns:
            Result dict with success status and metadata

        Raises:
            ContractViolationError: If message or result is wrong type
        """
        # CONTRACT ENFORCEMENT
        if not isinstance(task_message, TaskQueueMessage):
            raise ContractViolationError(
                f"task_message must be TaskQueueMessage, got {type(task_message).__name__}"
            )

        self.logger.info(f"🔧 Processing task: {task_message.task_id[:16]}... "
                        f"(job: {task_message.parent_job_id[:16]}..., stage {task_message.stage})")

        # Step 1: Get task handler from EXPLICIT registry (direct dict lookup - no magic!)
        if task_message.task_type not in self.handlers_registry:
            available = list(self.handlers_registry.keys())
            error_msg = f"Unknown task type: '{task_message.task_type}'. Available: {available}"
            self.logger.error(f"❌ {error_msg}")
            raise BusinessLogicError(error_msg)

        handler = self.handlers_registry[task_message.task_type]
        self.logger.debug(f"✅ Retrieved handler: {handler.__name__}")

        # Step 1.5: Update task status to PROCESSING before execution
        try:
            success = self.state_manager.update_task_status_direct(
                task_message.task_id,
                TaskStatus.PROCESSING
            )
            if success:
                self.logger.debug(f"✅ Task {task_message.task_id[:16]} → PROCESSING")
            else:
                self.logger.warning(f"⚠️ Failed to update task status to PROCESSING (returned False)")
        except Exception as e:
            self.logger.error(f"❌ Exception updating task status to PROCESSING: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            # Don't fail the whole task - just log and continue

        # Step 2: Execute task handler
        result = None
        try:
            self.logger.debug(f"▶️ Executing handler for task {task_message.task_id[:16]}...")
            start_time = time.time()

            # Execute handler (returns dict or TaskResult)
            raw_result = handler(task_message.parameters)

            elapsed = time.time() - start_time
            self.logger.debug(f"✅ Handler executed in {elapsed:.2f}s")

            # Convert dict to TaskResult if needed
            if isinstance(raw_result, dict):
                result = TaskResult(
                    task_id=task_message.task_id,
                    task_type=task_message.task_type,
                    status=TaskStatus.COMPLETED if raw_result.get('success', False) else TaskStatus.FAILED,
                    result_data=raw_result,
                    execution_time_ms=int(elapsed * 1000),  # Convert seconds to milliseconds
                    timestamp=datetime.now(timezone.utc)
                )
            elif isinstance(raw_result, TaskResult):
                result = raw_result
            else:
                raise ContractViolationError(
                    f"Task handler '{task_message.task_type}' returned "
                    f"{type(raw_result).__name__} instead of dict or TaskResult"
                )

        except ContractViolationError:
            # Contract violations bubble up (programming bugs)
            raise
        except TaskExecutionError as e:
            # Business logic failure (expected)
            self.logger.warning(f"⚠️ Task execution failed (business logic): {e}")
            result = TaskResult(
                task_id=task_message.task_id,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={'error': str(e), 'error_type': 'business_logic'},
                error_details=str(e),
                timestamp=datetime.now(timezone.utc)
            )
        except Exception as e:
            # Unexpected error
            self.logger.error(f"❌ Unexpected error executing task: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            result = TaskResult(
                task_id=task_message.task_id,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={'error': str(e), 'error_type': 'unexpected'},
                error_details=str(e),
                timestamp=datetime.now(timezone.utc)
            )

        # Step 3: Complete task and check stage (atomic)
        if result.status == TaskStatus.COMPLETED:
            try:
                completion = self.state_manager.complete_task_with_sql(
                    task_message.task_id,
                    task_message.parent_job_id,
                    task_message.stage,
                    result
                )

                self.logger.debug(f"✅ Task completed (stage_complete: {completion.stage_complete}, "
                                f"remaining: {completion.remaining_tasks})")

                # Step 4: Handle stage completion
                if completion.stage_complete:
                    self._handle_stage_completion(
                        task_message.parent_job_id,
                        task_message.job_type,
                        task_message.stage
                    )

                return {
                    'success': True,
                    'task_id': task_message.task_id,
                    'stage_complete': completion.stage_complete
                }

            except Exception as e:
                self.logger.error(f"❌ Failed to complete task: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                raise
        else:
            # Task failed - check if retry needed
            self.logger.warning(f"⚠️ Task failed: {result.error_details}")
            self.logger.warning(f"🔄 RETRY LOGIC STARTING for task {task_message.task_id[:16]}")

            # DEBUGGING: Update error_details to confirm we reached retry logic
            try:
                self.state_manager.update_task_status_direct(
                    task_message.task_id,
                    TaskStatus.FAILED,
                    error_details=f"[RETRY LOGIC REACHED] {result.error_details}"
                )
                self.logger.info(f"✅ Updated error_details to confirm retry logic execution")
            except Exception as debug_e:
                self.logger.error(f"❌ Failed to update error_details for debugging: {debug_e}")

            # Get config for retry settings
            from config import get_config
            from infrastructure import RepositoryFactory
            config = get_config()
            self.logger.debug(f"📋 Retry config: max_retries={config.task_max_retries}, base_delay={config.task_retry_base_delay}s")

            # Get current task to check retry count
            repos = RepositoryFactory.create_repositories()
            task_repo = repos['task_repo']
            task_record = task_repo.get_task(task_message.task_id)

            if task_record is None:
                self.logger.error(f"❌ CRITICAL: task_record is NONE for task_id={task_message.task_id}")
                self.logger.error(f"❌ Cannot retry - task not found in database!")
            else:
                self.logger.info(f"📋 Task found: retry_count={task_record.retry_count}, max={config.task_max_retries}")

            if task_record and task_record.retry_count < config.task_max_retries:
                self.logger.warning(f"🔄 RETRY CONDITION MET: retry_count ({task_record.retry_count}) < max_retries ({config.task_max_retries})")
                # Retry needed - calculate exponential backoff delay
                retry_attempt = task_record.retry_count + 1
                delay_seconds = min(
                    config.task_retry_base_delay * (2 ** task_record.retry_count),
                    config.task_retry_max_delay
                )

                self.logger.warning(
                    f"🔄 RETRY SCHEDULED - Task {task_message.task_id[:16]} failed (attempt {retry_attempt}/"
                    f"{config.task_max_retries}) - will retry in {delay_seconds}s"
                )

                try:
                    # Increment retry count and reset to QUEUED
                    self.logger.debug(f"📝 Incrementing retry_count from {task_record.retry_count} to {retry_attempt}")
                    self.state_manager.increment_task_retry_count(task_message.task_id)
                    self.logger.debug(f"✅ retry_count incremented successfully")

                    # Re-queue with delay using Service Bus scheduled delivery
                    from infrastructure.service_bus import ServiceBusRepository
                    service_bus_repo = ServiceBusRepository()

                    message_id = service_bus_repo.send_message_with_delay(
                        config.service_bus_tasks_queue,
                        task_message,
                        delay_seconds
                    )

                    self.logger.info(
                        f"✅ Task retry scheduled - attempt {retry_attempt}, "
                        f"delay: {delay_seconds}s, message_id: {message_id}"
                    )

                    return {
                        'success': False,
                        'retry_scheduled': True,
                        'retry_attempt': retry_attempt,
                        'delay_seconds': delay_seconds,
                        'task_id': task_message.task_id
                    }

                except Exception as e:
                    self.logger.error(f"❌ Failed to schedule retry: {e}")
                    self.logger.error(f"Traceback: {traceback.format_exc()}")
                    # Fall through to mark as FAILED

            # Max retries exceeded or retry scheduling failed - mark as permanently FAILED
            try:
                self.state_manager.update_task_status_direct(
                    task_message.task_id,
                    TaskStatus.FAILED,
                    error_details=result.error_details
                )
                if task_record and task_record.retry_count >= config.task_max_retries:
                    self.logger.error(
                        f"❌ Task {task_message.task_id[:16]} exceeded max retries "
                        f"({config.task_max_retries}) - marking as FAILED"
                    )
                else:
                    self.logger.info(f"✅ Task {task_message.task_id[:16]} marked as FAILED in database")
            except Exception as e:
                self.logger.error(f"❌ Failed to update task status to FAILED: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")

            return {
                'success': False,
                'error': result.error_details or 'Task execution failed',
                'error_type': 'task_failure',
                'task_id': task_message.task_id,
                'max_retries_exceeded': task_record and task_record.retry_count >= config.task_max_retries
            }

    # ========================================================================
    # PRIVATE METHODS - Internal coordination logic
    # ========================================================================

    def _queue_stage_tasks(
        self,
        job_id: str,
        stage_number: int,
        job_type: str,
        job_parameters: Dict[str, Any],
        stage_definition: Any  # Stage model from workflow
    ) -> Dict[str, Any]:
        """
        Create and queue tasks for a stage.

        Determines batch vs individual queuing based on task count.
        """
        self.logger.info(f"📦 Creating tasks for stage {stage_number}")

        # Get workflow to create tasks
        # Get workflow class from explicit registry
        if job_type not in self.jobs_registry:
            raise BusinessLogicError(f"Unknown job type: {job_type}. Available: {list(self.jobs_registry.keys())}")
        workflow = self.jobs_registry[job_type]

        # Get previous stage results if needed
        previous_results = None
        if stage_number > 1:
            try:
                previous_results = self.state_manager.get_stage_results(
                    job_id, stage_number - 1
                )
            except Exception as e:
                self.logger.warning(f"⚠️ No previous stage results: {e}")

        # Create task definitions (delegate to workflow)
        from core.models import TaskDefinition
        task_defs = []

        for task_type in stage_definition.task_types:
            # For now, create single task per task_type
            # TODO: Handle fan-out where Stage 1 determines count
            task_def = TaskDefinition(
                task_id=f"{job_id[:8]}-s{stage_number}-{task_type}-{len(task_defs):04d}",
                job_id=job_id,
                job_type=job_type,
                task_type=task_type,
                stage_number=stage_number,
                parameters=job_parameters.copy()
            )
            task_defs.append(task_def)

        if not task_defs:
            return {'tasks_created': 0, 'message': 'No tasks to create'}

        self.logger.info(f"📊 Created {len(task_defs)} task definitions")

        # Decide batch vs individual
        batch_threshold = workflow.get_batch_threshold()
        task_count = len(task_defs)

        if task_count >= batch_threshold:
            self.logger.info(f"🚀 Using batch processing for {task_count} tasks")
            return self._batch_queue_tasks(task_defs, job_id, stage_number)
        else:
            self.logger.info(f"📝 Using individual processing for {task_count} tasks")
            return self._individual_queue_tasks(task_defs, job_id, stage_number)

    def _batch_queue_tasks(
        self,
        task_defs: list,
        job_id: str,
        stage_number: int
    ) -> Dict[str, Any]:
        """Queue tasks in batches to Service Bus."""
        start_time = time.time()
        total_tasks = len(task_defs)
        successful_batches = []
        failed_batches = []

        # Get repositories
        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']
        service_bus_repo = RepositoryFactory.create_service_bus_repository()
        queue_name = self.config.task_processing_queue

        # Process in batches of 100
        for i in range(0, total_tasks, self.BATCH_SIZE):
            batch = task_defs[i:i + self.BATCH_SIZE]
            batch_id = f"{job_id[:8]}-s{stage_number}-b{i//self.BATCH_SIZE:03d}"

            try:
                # Create task records in DB
                task_records = task_repo.batch_create_tasks(
                    batch, batch_id=batch_id, initial_status='pending_queue'
                )

                # Send to Service Bus
                messages = [td.to_queue_message() for td in batch]
                result = service_bus_repo.batch_send_messages(queue_name, messages)

                if not result.success:
                    raise RuntimeError(f"Batch send failed: {result.errors}")

                # Update status to queued
                task_ids = [tr.task_id for tr in task_records]
                task_repo.batch_update_status(
                    task_ids, 'queued',
                    {'queued_at': datetime.now(timezone.utc).isoformat()}
                )

                successful_batches.append({
                    'batch_id': batch_id,
                    'size': len(batch)
                })

                self.logger.debug(f"✅ Batch {batch_id}: {len(batch)} tasks")

            except Exception as e:
                self.logger.error(f"❌ Batch {batch_id} failed: {e}")
                failed_batches.append({
                    'batch_id': batch_id,
                    'size': len(batch),
                    'error': str(e)
                })

        elapsed_ms = (time.time() - start_time) * 1000
        tasks_queued = sum(b['size'] for b in successful_batches)

        return {
            'status': 'completed' if not failed_batches else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'batches': {
                'successful': len(successful_batches),
                'failed': len(failed_batches)
            },
            'elapsed_ms': elapsed_ms
        }

    def _individual_queue_tasks(
        self,
        task_defs: list,
        job_id: str,
        stage_number: int
    ) -> Dict[str, Any]:
        """Queue tasks individually to Service Bus."""
        start_time = time.time()
        total_tasks = len(task_defs)
        tasks_queued = 0
        tasks_failed = 0

        # Get repositories
        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']
        service_bus_repo = RepositoryFactory.create_service_bus_repository()
        queue_name = self.config.task_processing_queue

        for idx, task_def in enumerate(task_defs):
            try:
                # Create task record (TaskDefinition → TaskRecord for database)
                task_record = TaskRecord(
                    task_id=task_def.task_id,
                    parent_job_id=task_def.parent_job_id,  # Fixed: was task_def.job_id
                    job_type=task_def.job_type,
                    task_type=task_def.task_type,
                    status=TaskStatus.QUEUED,
                    stage=task_def.stage,  # Fixed: was task_def.stage_number
                    task_index=str(idx),
                    parameters=task_def.parameters,
                    metadata=task_def.metadata or {},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )

                task_repo.create_task(task_record)

                # Send to Service Bus (TaskDefinition → TaskQueueMessage for Service Bus)
                queue_message = TaskQueueMessage(
                    task_id=task_def.task_id,
                    parent_job_id=task_def.parent_job_id,
                    job_type=task_def.job_type,
                    task_type=task_def.task_type,
                    stage=task_def.stage,
                    parameters=task_def.parameters,
                    correlation_id=str(uuid.uuid4())[:8]
                )
                service_bus_repo.send_message(queue_name, queue_message)

                tasks_queued += 1

            except Exception as e:
                tasks_failed += 1
                self.logger.error(f"❌ Failed to queue task {task_def.task_id}: {e}")

        elapsed_ms = (time.time() - start_time) * 1000

        return {
            'status': 'completed' if tasks_failed == 0 else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'tasks_failed': tasks_failed,
            'method': 'individual',
            'elapsed_ms': elapsed_ms
        }

    def _handle_stage_completion(
        self,
        job_id: str,
        job_type: str,
        completed_stage: int
    ):
        """
        Handle stage completion by advancing or completing job.

        This is the "last task turns out lights" pattern.
        """
        self.logger.info(f"🎯 Stage {completed_stage} complete for job {job_id[:16]}...")

        # Get workflow to check if we should advance
        # Get workflow class from explicit registry
        if job_type not in self.jobs_registry:
            raise BusinessLogicError(f"Unknown job type: {job_type}. Available: {list(self.jobs_registry.keys())}")
        workflow = self.jobs_registry[job_type]
        # Get stages from class attribute (pure data approach)
        stages = workflow.stages if hasattr(workflow, 'stages') else []

        if completed_stage < len(stages):
            # Advance to next stage
            self.logger.info(f"➡️ Advancing to stage {completed_stage + 1}")
            self._advance_stage(job_id, job_type, completed_stage + 1)
        else:
            # Complete job
            self.logger.info(f"🏁 Job complete - no more stages")
            self._complete_job(job_id, job_type)

    def _advance_stage(self, job_id: str, job_type: str, next_stage: int):
        """Queue next stage job message."""
        try:
            # Get job record for parameters
            repos = RepositoryFactory.create_repositories()
            job_record = repos['job_repo'].get_job(job_id)

            # Create job message for next stage
            next_message = JobQueueMessage(
                job_id=job_id,
                job_type=job_type,
                parameters=job_record.parameters,
                stage=next_stage,
                correlation_id=str(uuid.uuid4())[:8]
            )

            # Send to job queue
            service_bus_repo = RepositoryFactory.create_service_bus_repository()
            service_bus_repo.send_message(
                self.config.job_processing_queue,
                next_message
            )

            self.logger.info(f"✅ Advanced to stage {next_stage}")

        except Exception as e:
            self.logger.error(f"❌ Failed to advance stage: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    def _complete_job(self, job_id: str, job_type: str):
        """Complete job by aggregating results."""
        try:
            self.logger.info(f"🏁 Completing job {job_id[:16]}...")

            # Get all task records
            repos = RepositoryFactory.create_repositories()
            task_records = repos['task_repo'].get_tasks_for_job(job_id)

            if not task_records:
                raise RuntimeError(f"No tasks found for job {job_id}")

            # Convert to TaskResults
            task_results = []
            self.logger.debug(f"Converting {len(task_records)} task records to TaskResult objects")
            for idx, tr in enumerate(task_records):
                try:
                    task_result = TaskResult(
                        task_id=tr.task_id,
                        task_type=tr.task_type,
                        status=tr.status,
                        result_data=tr.result_data or {},
                        error_details=tr.error_details,
                        timestamp=tr.updated_at or tr.created_at
                    )
                    task_results.append(task_result)
                except Exception as e:
                    self.logger.error(f"❌ Failed to create TaskResult for task {idx}: {tr.task_id}")
                    self.logger.error(f"   Error: {e}")
                    self.logger.error(f"   Task data: status={tr.status}, updated_at={tr.updated_at}, created_at={tr.created_at}")
                    raise

            # Get job record
            job_record = repos['job_repo'].get_job(job_id)

            # Create context
            context = JobExecutionContext(
                job_id=job_id,
                job_type=job_type,
                current_stage=job_record.stage,
                total_stages=job_record.total_stages,
                parameters=job_record.parameters
            )
            context.task_results = task_results

            # Aggregate results (delegate to workflow)
            # Get workflow class from explicit registry
            if job_type not in self.jobs_registry:
                raise BusinessLogicError(f"Unknown job type: {job_type}. Available: {list(self.jobs_registry.keys())}")
            workflow = self.jobs_registry[job_type]
            if hasattr(workflow, 'aggregate_job_results'):
                final_result = workflow.aggregate_job_results(context)
            else:
                # Default aggregation
                final_result = {
                    'job_type': job_type,
                    'total_tasks': len(task_results),
                    'message': 'Job completed successfully'
                }

            # Complete job in database
            self.state_manager.complete_job(job_id, final_result)

            self.logger.info(f"✅ Job {job_id[:16]}... completed successfully")

        except Exception as e:
            self.logger.error(f"❌ CRITICAL: Job completion failed: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise  # Must re-raise to fail the message

    def _mark_job_failed(self, job_id: str, error_message: str):
        """Mark job as failed."""
        try:
            self.logger.info(f"🚫 Marking job {job_id[:16]}... as FAILED")
            self.state_manager.update_job_status(job_id, JobStatus.FAILED)
            self.logger.info(f"✅ Job marked as FAILED: {error_message}")
        except Exception as e:
            self.logger.error(f"❌ Failed to mark job as FAILED: {e}")
            # Best effort - don't raise

    def _get_completed_stage_results(self, job_id: str, stage: int) -> list[dict]:
        """
        Get completed task results from a specific stage.

        Used for fan-out pattern where Stage N+1 needs Stage N results.

        Args:
            job_id: Parent job ID
            stage: Stage number to fetch results from

        Returns:
            List of task result_data dicts from completed tasks

        Raises:
            RuntimeError: If no completed tasks found for stage
        """
        from infrastructure import RepositoryFactory

        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']

        # Get all tasks for this job and stage
        all_tasks = task_repo.get_tasks_for_job(job_id)
        stage_tasks = [t for t in all_tasks if t.stage == stage and t.status == TaskStatus.COMPLETED]

        if not stage_tasks:
            raise RuntimeError(
                f"No completed tasks found for job {job_id} stage {stage}. "
                f"Cannot generate tasks for next stage."
            )

        # Extract result_data from each task
        results = []
        for task in stage_tasks:
            if task.result_data:
                results.append(task.result_data)

        self.logger.debug(f"Retrieved {len(results)} completed task results from stage {stage}")
        return results
