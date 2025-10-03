# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# EPOCH: 3 - DEPRECATED ⚠️
# STATUS: Replaced by Epoch 4 CoreMachine
# MIGRATION: Will be archived after Storage Queue triggers migrated
# PURPOSE: Service Bus HelloWorld controller using clean architecture components
# EXPORTS: ServiceBusHelloWorldController - HelloWorld with clean architecture
# INTERFACES: Extends CoreController (not BaseController) with composition
# PYDANTIC_MODELS: TaskDefinition, TaskRecord, JobExecutionContext
# DEPENDENCIES: controller_core, state_manager, orchestration_manager
# SOURCE: Clean architecture implementation without God Class inheritance
# SCOPE: HelloWorld test implementation for Service Bus
# VALIDATION: Pydantic models and parameter validation
# PATTERNS: Composition over inheritance, no God Class
# ENTRY_POINTS: Used when job_type = 'sb_hello_world_clean'
# INDEX: ServiceBusHelloWorldController:100, create_stage_tasks:200
# ============================================================================

"""
Service Bus HelloWorld Controller - Clean Architecture

This is the CLEAN implementation that uses:
- CoreController (minimal inheritance)
- StateManager (composition for DB operations)
- No God Class inheritance

Compare with the old controller_service_bus.py which inherits
from BaseController (2,290 lines).

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import time
import traceback
import uuid

# Clean architecture components
from core import CoreController, StateManager, OrchestrationManager

# Pydantic models - using new core.models structure
from core.models import (
    TaskDefinition,
    JobExecutionContext,
    JobRecord,
    JobStatus
)
from schema_queue import TaskQueueMessage, JobQueueMessage

# Repositories
from infrastructure.factory import RepositoryFactory
from infrastructure.service_bus import BatchResult

# Task handling
from task_factory import TaskHandlerFactory

# Utilities
from config import AppConfig
from util_logger import LoggerFactory, ComponentType

# Custom exceptions
from exceptions import TaskExecutionError


class ServiceBusHelloWorldController(CoreController):
    """
    Clean Service Bus HelloWorld controller.

    Uses composition instead of inheriting from BaseController:
    - Inherits only from CoreController (5 abstract methods)
    - Uses StateManager for database operations (composition)
    - Uses OrchestrationManager for dynamic tasks (composition)

    This proves Service Bus doesn't need the 2,290-line God Class!
    """

    REGISTRATION_INFO = {
        'job_type': 'sb_hello_world',
        'queue_type': 'service_bus',  # Uses Azure Service Bus
        'description': 'Service Bus HelloWorld with clean architecture',
        'version': '2.0.0',  # v2 = clean architecture
        'supported_parameters': ['n', 'message'],
        'stages': 2
    }

    # Batch configuration
    BATCH_SIZE = 100  # Aligned with Service Bus
    BATCH_THRESHOLD = 50  # Use batching if >= 50 tasks

    def __init__(self):
        """Initialize with clean architecture components."""
        super().__init__()

        # Composition: Use components instead of inheritance
        self.state_manager = StateManager()
        self.orchestrator = OrchestrationManager('sb_hello_world')

        # Configuration
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "ServiceBusHelloWorld"
        )
        self.batch_metrics = []
        self.processing_path = 'service_bus'

    # ========================================================================
    # IMPLEMENT ABSTRACT METHODS FROM CoreController
    # ========================================================================

    def get_job_type(self) -> str:
        """Return the job type identifier."""
        return 'sb_hello_world'

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate HelloWorld parameters."""
        validated = {}
        validated['n'] = max(1, min(1000, parameters.get('n', 3)))
        validated['message'] = parameters.get('message', 'Hello from Clean Architecture')
        validated['use_service_bus'] = True  # Force Service Bus
        return validated

    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[List[Dict[str, Any]]] = None
    ) -> List[TaskDefinition]:
        """
        Create HelloWorld tasks for each stage.

        Stage 1: Create greeting tasks
        Stage 2: Create reply tasks
        """
        n = job_parameters.get('n', 3)
        message = job_parameters.get('message', 'Hello')

        tasks = []

        if stage_number == 1:
            # Stage 1: Greeting tasks
            for i in range(n):
                task = TaskDefinition(
                    task_id=f"{job_id[:8]}-s1-greet-{i:04d}",
                    job_id=job_id,
                    job_type=self.get_job_type(),
                    task_type='hello_world_greeting',
                    stage_number=1,
                    parameters={
                        'index': i,
                        'name': f"User_{i}",
                        'message': message
                    }
                )
                tasks.append(task)

        elif stage_number == 2:
            # Stage 2: Reply tasks
            for i in range(n):
                task = TaskDefinition(
                    task_id=f"{job_id[:8]}-s2-reply-{i:04d}",
                    job_id=job_id,
                    job_type=self.get_job_type(),
                    task_type='hello_world_reply',
                    stage_number=2,
                    parameters={
                        'index': i,
                        'greeting': f"Hello User_{i} (from Stage 1)"
                    }
                )
                tasks.append(task)

        self.logger.info(f"Created {len(tasks)} tasks for stage {stage_number}")
        return tasks

    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """Determine if job should advance to next stage."""
        # HelloWorld has 2 stages
        return current_stage < 2

    def aggregate_job_results(self, context: JobExecutionContext) -> Dict[str, Any]:
        """
        Aggregate results from all stages.

        This is called when the job completes.
        """
        # Count tasks from context
        task_counts = {
            'stage_1': 0,
            'stage_2': 0,
            'total': 0
        }

        # Get task results from context (passed by StateManager)
        if hasattr(context, 'task_results'):
            for task in context.task_results:
                # TaskResult is a Pydantic model, use attribute access
                stage = task.stage_number if hasattr(task, 'stage_number') else 0
                if stage == 1:
                    task_counts['stage_1'] += 1
                elif stage == 2:
                    task_counts['stage_2'] += 1
                task_counts['total'] += 1

        return {
            'job_type': self.get_job_type(),
            'processing_path': self.processing_path,
            'architecture': 'clean',  # Mark as clean architecture
            'stages_completed': 2,
            'task_counts': task_counts,
            'performance': self.get_performance_summary(),
            'message': f"Clean HelloWorld completed {task_counts['total']} tasks without God Class!"
        }

    # ========================================================================
    # JOB RECORD MANAGEMENT (Required for job submission)
    # ========================================================================

    def create_job_record(self, job_id: str, parameters: Dict[str, Any]):
        """
        Create and store the initial job record.

        NOTE: Due to repository layer hardcoding, job starts as QUEUED.
        We'll need to handle this differently - either:
        1. Don't create job record until after Service Bus send succeeds
        2. Or modify the repository layer to support initial status parameter

        This is required for job submission but wasn't in CoreController.
        Should eventually be moved to trigger layer.
        """
        # PROBLEM: The repository layer hardcodes JobStatus.QUEUED
        # We can't use PENDING without modifying the repository
        # For now, we'll create with QUEUED but add metadata to track actual state
        job_record = JobRecord(
            job_id=job_id,
            job_type=self.get_job_type(),
            status=JobStatus.QUEUED,  # Repository forces this to QUEUED anyway
            stage=1,
            parameters=parameters,
            metadata={
                'processing_path': self.processing_path,
                'architecture': 'clean',
                'actual_status': 'pending_queue_send'  # Track real status in metadata
            },
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        # Store in database via StateManager
        self.state_manager.create_job_record(job_record)
        self.logger.info(f"Created job record (will be QUEUED due to repository layer): {job_id}")

        return job_record

    # ========================================================================
    # SERVICE BUS SPECIFIC METHODS (Not from BaseController!)
    # ========================================================================

    def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue job to Service Bus.

        This replaces BaseController's queue_job method.
        Uses Service Bus repository directly.

        IMPORTANT: Job is already marked as QUEUED in database due to
        repository layer hardcoding. If Service Bus send fails, we should
        update status to FAILED to prevent false QUEUED status.
        """
        # CONTRACT ENFORCEMENT - Type validation
        from exceptions import ContractViolationError

        if not isinstance(job_id, str):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.queue_job: "
                f"job_id must be str, got {type(job_id).__name__}"
            )

        if not isinstance(parameters, dict):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.queue_job: "
                f"parameters must be dict, got {type(parameters).__name__}"
            )

        self.logger.info(f"🚌 Queueing job {job_id} to Service Bus (clean)")

        # Step 1: Get configuration (minimal try block)
        try:
            config = AppConfig.from_environment()
            queue_name = config.job_processing_queue
            self.logger.debug(f"📮 Target queue: {queue_name}")
        except Exception as e:
            self.logger.error(f"❌ Failed to get configuration: {e}")
            self._mark_job_failed(job_id, f"Configuration error: {e}")
            raise RuntimeError(f"Configuration error: {e}")

        # Step 2: Create message (no try block needed - Pydantic validates)
        queue_message = JobQueueMessage(
            job_id=job_id,
            job_type=self.get_job_type(),
            parameters=parameters,
            stage=1,
            correlation_id=self._generate_correlation_id()
        )
        self.logger.debug(f"📦 Created queue message for job {job_id}")

        # Step 3: Get Service Bus repository (minimal try block)
        service_bus_repo = None
        try:
            service_bus_repo = RepositoryFactory.create_service_bus_repository()
            self.logger.debug(f"✅ Service Bus repository obtained")
        except Exception as e:
            self.logger.error(f"❌ Failed to get Service Bus repository: {e}")
            self._mark_job_failed(job_id, f"Repository creation failed: {e}")
            raise RuntimeError(f"Service Bus repository creation failed: {e}")

        # Step 4: Send message (minimal try block)
        try:
            self.logger.debug(f"📤 Attempting to send message to Service Bus...")
            message_id = service_bus_repo.send_message(queue_name, queue_message)
            self.logger.info(f"✅ Message sent to Service Bus. Message ID: {message_id}")
            self.logger.info(f"✅ Job {job_id} successfully queued with message ID: {message_id}")

            return {
                "queued": True,
                "message_id": message_id,
                "queue": queue_name,
                "processing_path": self.processing_path,
                "architecture": "clean"
            }
        except Exception as e:
            self.logger.error(f"❌ Failed to send message to Service Bus: {e}")
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
            self._mark_job_failed(job_id, f"Message send failed: {e}")
            raise RuntimeError(f"Service Bus send failed: {e}")

    def _mark_job_failed(self, job_id: str, error_message: str):
        """Mark job as failed when queue send fails."""
        try:
            self.logger.info(f"🚫 Marking job {job_id} as FAILED due to queue send failure")

            # Update job status to FAILED
            self.state_manager.update_job_status(job_id, JobStatus.FAILED)

            self.logger.info(f"✅ Job {job_id} marked as FAILED - Error: {error_message}")
        except Exception as update_error:
            self.logger.error(f"❌ Failed to mark job as FAILED: {update_error}")
            # Don't raise - this is best effort

    def queue_stage_tasks(
        self,
        job_id: str,
        stage_number: int,
        job_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Queue stage tasks with batch optimization.

        This replaces BaseController's queue_stage_tasks.
        Uses composition instead of inheritance.
        """
        self.logger.info(f"📦 Creating tasks for stage {stage_number} (clean)")

        # Get previous stage results if needed
        previous_results = None
        if stage_number > 1:
            previous_results = self.state_manager.get_stage_results(
                job_id, stage_number - 1
            )

        # Create task definitions
        task_definitions = self.create_stage_tasks(
            stage_number=stage_number,
            job_id=job_id,
            job_parameters=job_parameters,
            previous_stage_results=previous_results
        )

        if not task_definitions:
            return {
                "tasks_created": 0,
                "message": "No tasks to create"
            }

        # Decide on processing strategy
        task_count = len(task_definitions)
        self.logger.info(f"📊 Stage {stage_number} has {task_count} tasks")

        if task_count >= self.BATCH_THRESHOLD:
            # Use batch processing
            self.logger.info(f"🚀 Using batch processing for {task_count} tasks")
            return self._batch_queue_tasks(
                task_definitions, job_id, stage_number
            )
        else:
            # Use individual processing
            self.logger.info(f"📝 Using individual processing for {task_count} tasks")
            return self._individual_queue_tasks(
                task_definitions, job_id, stage_number
            )

    def _batch_queue_tasks(
        self,
        task_definitions: List[TaskDefinition],
        job_id: str,
        stage_number: int
    ) -> Dict[str, Any]:
        """
        Process tasks in aligned 100-item batches.

        Uses composition with StateManager and Service Bus repository.
        """
        start_time = time.time()
        total_tasks = len(task_definitions)
        successful_batches = []
        failed_batches = []

        # Step 1: Get repositories (outside loop)
        try:
            repos = RepositoryFactory.create_repositories()
            task_repo = repos['task_repo']
            service_bus_repo = RepositoryFactory.create_service_bus_repository()
        except Exception as e:
            self.logger.error(f"Failed to initialize repositories: {e}")
            return {
                'status': 'failed',
                'error': f'Repository initialization failed: {e}',
                'total_tasks': total_tasks,
                'architecture': 'clean'
            }

        # Step 2: Get configuration (outside loop)
        try:
            config = AppConfig.from_environment()
            queue_name = config.task_processing_queue
        except Exception as e:
            self.logger.error(f"Failed to get configuration: {e}")
            return {
                'status': 'failed',
                'error': f'Configuration error: {e}',
                'total_tasks': total_tasks,
                'architecture': 'clean'
            }

        # Step 3: Process each batch with individual error handling
        for i in range(0, total_tasks, self.BATCH_SIZE):
            batch = task_definitions[i:i + self.BATCH_SIZE]
            batch_id = f"{job_id[:8]}-s{stage_number}-b{i//self.BATCH_SIZE:03d}"

            batch_result = self._process_single_batch(
                batch, batch_id, task_repo, service_bus_repo, queue_name
            )

            if batch_result['success']:
                successful_batches.append(batch_result)
            else:
                failed_batches.append(batch_result)

        # Calculate metrics
        elapsed_ms = (time.time() - start_time) * 1000
        tasks_queued = sum(b['size'] for b in successful_batches)
        tasks_failed = sum(b['size'] for b in failed_batches)

        # Store metrics
        self.batch_metrics.append({
            'job_id': job_id,
            'stage': stage_number,
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'elapsed_ms': elapsed_ms
        })

        return {
            'status': 'completed' if not failed_batches else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'tasks_failed': tasks_failed,
            'batches': {
                'successful': len(successful_batches),
                'failed': len(failed_batches)
            },
            'elapsed_ms': elapsed_ms,
            'architecture': 'clean'
        }

    def _process_single_batch(self, batch: List[TaskDefinition], batch_id: str,
                              task_repo, service_bus_repo, queue_name: str) -> Dict:
        """Process a single batch with granular error handling."""
        batch_start = time.time()
        task_records = None

        # Phase 1: Database insert (minimal try block)
        try:
            self.logger.debug(f"📥 Inserting batch {batch_id}: {len(batch)} tasks")
            task_records = task_repo.batch_create_tasks(
                batch, batch_id=batch_id, initial_status='pending_queue'
            )
        except Exception as e:
            self.logger.error(f"❌ Batch {batch_id} DB insert failed: {e}")
            return {
                'success': False,
                'batch_id': batch_id,
                'size': len(batch),
                'error': f'Database insert failed: {e}',
                'phase': 'database'
            }

        # Phase 2: Service Bus send (minimal try block)
        try:
            self.logger.debug(f"📤 Sending batch {batch_id} to Service Bus")
            messages = [td.to_queue_message() for td in batch]
            result = service_bus_repo.batch_send_messages(queue_name, messages)

            if not result.success:
                raise RuntimeError(f"Batch send failed: {result.errors}")

        except Exception as e:
            self.logger.error(f"❌ Batch {batch_id} Service Bus send failed: {e}")
            # Rollback: Mark tasks as failed in DB
            self._rollback_batch_tasks(task_records, 'send_failed')
            return {
                'success': False,
                'batch_id': batch_id,
                'size': len(batch),
                'error': f'Service Bus send failed: {e}',
                'phase': 'service_bus'
            }

        # Phase 3: Update status to queued (minimal try block)
        try:
            task_ids = [tr.task_id for tr in task_records]
            task_repo.batch_update_status(
                task_ids, 'queued',
                {'queued_at': datetime.now(timezone.utc).isoformat()}
            )
        except Exception as e:
            self.logger.warning(f"⚠️ Batch {batch_id} status update failed: {e}")
            # Don't fail - tasks are already in Service Bus

        batch_time = (time.time() - batch_start) * 1000
        self.logger.info(f"✅ Batch {batch_id}: {len(batch)} tasks in {batch_time:.0f}ms")

        return {
            'success': True,
            'batch_id': batch_id,
            'size': len(batch),
            'elapsed_ms': batch_time
        }

    def _rollback_batch_tasks(self, task_records, reason: str):
        """Rollback batch tasks by marking them as failed."""
        if not task_records:
            return
        try:
            task_ids = [tr.task_id for tr in task_records]
            repos = RepositoryFactory.create_repositories()
            task_repo = repos['task_repo']
            task_repo.batch_update_status(
                task_ids, 'failed',
                {'failed_reason': reason, 'failed_at': datetime.now(timezone.utc).isoformat()}
            )
            self.logger.info(f"Rolled back {len(task_ids)} tasks due to: {reason}")
        except Exception as e:
            self.logger.error(f"Failed to rollback tasks: {e}")
            # Best effort - don't raise

    def _individual_queue_tasks(
        self,
        task_definitions: List[TaskDefinition],
        job_id: str,
        stage_number: int
    ) -> Dict[str, Any]:
        """Queue tasks individually for small batches."""
        start_time = time.time()
        total_tasks = len(task_definitions)
        tasks_queued = 0
        tasks_failed = 0
        errors = []

        # Get repositories
        repos = RepositoryFactory.create_repositories()
        task_repo = repos['task_repo']
        service_bus_repo = RepositoryFactory.create_service_bus_repository()

        # Get queue name
        config = AppConfig.from_environment()
        queue_name = config.task_processing_queue

        # Process tasks individually
        for idx, task_def in enumerate(task_definitions):
            try:
                # Step 1: Convert TaskDefinition to TaskRecord for database
                from core.models import TaskRecord, TaskStatus
                task_record = TaskRecord(
                    task_id=task_def.task_id,
                    parent_job_id=task_def.job_id,
                    job_type=task_def.job_type,
                    task_type=task_def.task_type,
                    status=TaskStatus.QUEUED,
                    stage=task_def.stage_number,
                    task_index=str(idx),
                    parameters=task_def.parameters,
                    metadata=task_def.metadata if hasattr(task_def, 'metadata') and task_def.metadata else {},
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )

                # Step 2: Create task record in database
                self.logger.debug(f"Creating task {task_def.task_id} in database")
                created_task = task_repo.create_task(task_record)

                # Step 3: Send to Service Bus
                self.logger.debug(f"Sending task {task_def.task_id} to Service Bus")
                queue_message = task_def.to_queue_message()
                message_id = service_bus_repo.send_message(queue_name, queue_message)

                # Step 4: Update task status to queued (already set in TaskRecord)
                # task_repo.update_task_status(task_def.task_id, 'queued')  # Not needed, already QUEUED

                tasks_queued += 1
                self.logger.debug(f"✅ Task {task_def.task_id} queued successfully")

            except Exception as e:
                tasks_failed += 1
                errors.append({
                    'task_id': task_def.task_id,
                    'error': str(e)
                })
                self.logger.error(f"❌ Failed to queue task {task_def.task_id}: {e}")

        # Calculate metrics
        elapsed_ms = (time.time() - start_time) * 1000

        # Update job status to PROCESSING once tasks are queued
        if tasks_queued > 0:
            try:
                self.state_manager.update_job_status(job_id, JobStatus.PROCESSING)
                self.logger.info(f"Updated job {job_id} to PROCESSING status")
            except Exception as e:
                self.logger.error(f"Failed to update job status: {e}")

        return {
            'status': 'completed' if tasks_failed == 0 else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'tasks_failed': tasks_failed,
            'method': 'individual',
            'elapsed_ms': elapsed_ms,
            'errors': errors if errors else None,
            'architecture': 'clean'
        }

    # ========================================================================
    # QUEUE MESSAGE PROCESSING (Required by function_app)
    # ========================================================================

    def process_job_queue_message(self, job_message) -> Dict[str, Any]:
        """
        Process a job queue message by creating and queuing tasks.

        Required by function_app for job queue processing.
        Uses granular error handling for better debugging.
        """
        self.logger.info(f"Processing job message: {job_message.job_id}")

        # Step 1: Get repositories (minimal try block)
        try:
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
        except Exception as e:
            self.logger.error(f"Failed to get repositories: {e}")
            return {'success': False, 'error': str(e), 'error_type': 'repository_init'}

        # Step 2: Get job record (minimal try block)
        job_record = None
        try:
            job_record = job_repo.get_job(job_message.job_id)
            if not job_record:
                raise ValueError(f"Job {job_message.job_id} not found")
        except Exception as e:
            self.logger.error(f"Failed to get job record: {e}")
            self._update_job_status_safe(job_message.job_id, JobStatus.FAILED, str(e))
            return {'success': False, 'error': str(e), 'error_type': 'job_not_found'}

        # Step 3: Update job status to PROCESSING (minimal try block)
        try:
            self.state_manager.update_job_status(
                job_message.job_id,
                JobStatus.PROCESSING
            )
        except Exception as e:
            self.logger.warning(f"Failed to update job status to PROCESSING: {e}")
            # Don't fail - continue processing

        # Step 4: Get previous results if needed (minimal try block)
        previous_results = None
        if job_message.stage > 1:
            try:
                previous_results = self.state_manager.get_stage_results(
                    job_message.job_id,
                    job_message.stage - 1
                )
                self.logger.debug(f"Retrieved previous stage results")
            except Exception as e:
                self.logger.warning(f"Failed to get previous stage results: {e}")
                # Continue without previous results - may be acceptable

        # Step 5: Queue stage tasks (minimal try block)
        try:
            result = self.queue_stage_tasks(
                job_message.job_id,
                job_message.stage,
                job_record.parameters
            )

            return {
                'success': True,
                'job_id': job_message.job_id,
                'stage': job_message.stage,
                **result
            }
        except Exception as e:
            self.logger.error(f"Failed to queue stage tasks: {e}")
            self._update_job_status_safe(job_message.job_id, JobStatus.FAILED, str(e))
            return {'success': False, 'error': str(e), 'error_type': 'task_queue_failure'}

    def _update_job_status_safe(self, job_id: str, status: JobStatus, error: str = None):
        """Safely update job status without raising exceptions."""
        try:
            if error:
                self.logger.debug(f"Updating job {job_id} to {status} with error: {error}")
            else:
                self.logger.debug(f"Updating job {job_id} to {status}")
            self.state_manager.update_job_status(job_id, status, error)
        except Exception as e:
            self.logger.error(f"Failed to update job status: {e}")
            # Best effort - don't raise

    def process_task_queue_message(self, task_message) -> Dict[str, Any]:
        """
        Process a task queue message by executing the task.

        Required by function_app for task queue processing.
        Implements "last task turns out the lights" pattern.
        """
        # CONTRACT ENFORCEMENT - Validate message type
        from exceptions import ContractViolationError
        from schema_queue import TaskQueueMessage
        from core.models import TaskResult

        if not isinstance(task_message, TaskQueueMessage):
            raise ContractViolationError(
                f"Contract violation in {self.__class__.__name__}.process_task_queue_message: "
                f"task_message must be TaskQueueMessage, got {type(task_message).__name__}"
            )

        self.logger.info(f"Processing task message: {task_message.task_id}")

        # Step 1: Get repositories (minimal try block)
        try:
            from infrastructure import RepositoryFactory  # Fixed import - not infra.factories
            repos = RepositoryFactory.create_repositories()
            task_repo = repos['task_repo']
        except Exception as e:
            self.logger.error(f"Failed to get repositories: {e}")
            return {'success': False, 'error': str(e), 'error_type': 'repository_init'}

        # Step 2: Get task handler (minimal try block)
        try:
            handler = TaskHandlerFactory.get_handler(task_message, task_repo)
        except Exception as e:
            self.logger.error(f"Failed to get task handler: {e}")
            return {'success': False, 'error': str(e), 'error_type': 'handler_init'}

        # Step 3: Execute task (minimal try block)
        result = None
        try:
            result = handler(task_message.parameters)

            # CONTRACT ENFORCEMENT - TaskHandlerFactory always returns TaskResult
            if not isinstance(result, TaskResult):
                raise ContractViolationError(
                    f"Contract violation: Task handler '{task_message.task_type}' returned "
                    f"{type(result).__name__} instead of TaskResult. "
                    f"Task ID: {task_message.task_id}"
                )
        except ContractViolationError:
            # Contract violations should bubble up - they indicate bugs
            raise
        except TaskExecutionError as e:
            # Business logic failure - expected runtime issue
            self.logger.warning(f"Task execution failed (business logic): {e}")
            # Create a failed TaskResult
            from core.models import TaskStatus
            result = TaskResult(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                stage_number=task_message.stage,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={'error': str(e), 'error_type': 'business_logic'},
                error_details=str(e)
            )
        except Exception as e:
            # Unexpected error during task execution
            self.logger.error(f"Unexpected error executing task: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            # Create a failed TaskResult
            from core.models import TaskStatus
            result = TaskResult(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                stage_number=task_message.stage,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={'error': str(e), 'error_type': 'unexpected'},
                error_details=str(e)
            )

        # Step 4: Complete task and check stage (only if task succeeded)
        completion = None
        # TaskHandlerFactory ALWAYS returns TaskResult objects
        # Check if task was successful based on status
        task_success = False
        if result and isinstance(result, TaskResult):
            from core.models import TaskStatus
            task_success = result.status == TaskStatus.COMPLETED

        if task_success:
            try:
                # Complete task with "last task turns out lights"
                # state_manager expects TaskResult object
                completion = self.state_manager.complete_task_with_sql(
                    task_message.task_id,
                    task_message.parent_job_id,  # Fixed: use parent_job_id, not job_id
                    task_message.stage,
                    result  # Pass the TaskResult object directly
                )
            except Exception as e:
                self.logger.error(f"Failed to complete task and check stage: {e}")
                return {'success': False, 'error': str(e), 'error_type': 'task_completion'}

            # Step 5: Handle stage completion (only if stage is complete)
            if completion and completion.stage_complete:
                self.logger.info(f"🎯 Stage {task_message.stage} complete for job {task_message.parent_job_id}")

                # Get job record to check if we should advance
                job_record = None
                try:
                    job_repo = repos['job_repo']
                    job_record = job_repo.get_job(task_message.parent_job_id)  # Fixed: use parent_job_id
                except Exception as e:
                    self.logger.error(f"Failed to get job record: {e}")
                    # Don't fail the task - it completed successfully
                    return {
                        'success': True,
                        'task_id': task_message.task_id,
                        'stage_complete': True,
                        'warning': f'Could not fetch job record: {e}'
                    }

                # Check if we should advance to next stage
                should_advance = self.should_advance_stage(
                    task_message.parent_job_id,  # Fixed: use parent_job_id
                    task_message.stage,
                    {}
                )

                self.logger.info(f"📊 Should advance from stage {task_message.stage}? {should_advance}")
                self.logger.info(f"📊 Current stage: {task_message.stage}, Logic: {task_message.stage} < 2 = {task_message.stage < 2}")

                if should_advance:
                    # Step 6: Queue next stage (separate try block)
                    try:
                        next_message = JobQueueMessage(
                            job_id=task_message.parent_job_id,  # Fixed: use parent_job_id
                            job_type=self.get_job_type(),
                            parameters=job_record.parameters,
                            stage=task_message.stage + 1,
                            correlation_id=str(uuid.uuid4())[:8]
                        )

                        # Queue via Service Bus
                        config = AppConfig.from_environment()
                        service_bus_repo = RepositoryFactory.create_service_bus_repository()
                        service_bus_repo.send_message(
                            config.job_processing_queue,
                            next_message
                        )

                        self.logger.info(f"✅ Advanced to stage {task_message.stage + 1}")
                    except Exception as e:
                        self.logger.error(f"Failed to queue next stage: {e}")
                        import traceback
                        self.logger.error(f"Traceback: {traceback.format_exc()}")
                        # Don't fail - task completed, we'll retry stage advance later
                else:
                    # Step 7: Complete job (CRITICAL - must not be swallowed)
                    self.logger.info(f"🏁 Job {task_message.parent_job_id} completed - no more stages")
                    self.logger.info(f"🏁 ENTERING JOB COMPLETION BLOCK")

                    # Job completion is CRITICAL - any error MUST bubble up to fail the message
                    # Otherwise the job will be stuck in PROCESSING forever
                    try:
                        # Step 7a: Get all task records
                        self.logger.info(f"Step 7a: Fetching task records for job {task_message.parent_job_id[:16]}...")
                        task_repo = repos['task_repo']
                        task_records = task_repo.get_tasks_for_job(task_message.parent_job_id)
                        self.logger.info(f"Step 7a: Found {len(task_records)} task records")

                        # Validate we have tasks - empty would indicate data inconsistency
                        if not task_records:
                            self.logger.error(f"❌ No tasks found for job {task_message.parent_job_id} during completion")
                            raise RuntimeError(f"Data inconsistency: No tasks found for job being completed")

                        # Step 7b: Convert TaskRecords to TaskResults
                        from core.models import TaskResult
                        self.logger.info("Step 7b: Converting TaskRecords to TaskResults...")
                        task_results = []
                        for task_record in task_records:
                            task_result = TaskResult(
                                task_id=task_record.task_id,
                                job_id=task_record.parent_job_id,
                                stage_number=task_record.stage,
                                task_type=task_record.task_type,
                                status=task_record.status,
                                result_data=task_record.result_data or {},
                                error_details=task_record.error_details,  # Fixed field name
                                execution_time_seconds=0.0,  # Default value
                                memory_usage_mb=0.0  # Default value
                            )
                            task_results.append(task_result)

                        self.logger.info(f"Step 7b: Converted {len(task_results)} TaskResults")

                        # Step 7c: Create context
                        self.logger.info("Step 7c: Creating JobExecutionContext...")
                        context = JobExecutionContext(
                            job_id=task_message.parent_job_id,
                            job_type=self.get_job_type(),
                            current_stage=job_record.stage,
                            total_stages=job_record.total_stages,
                            parameters=job_record.parameters
                        )

                        # Add task results to context for aggregation
                        context.task_results = task_results
                        self.logger.info("Step 7c: Context created with task results")

                        # Step 7d: Aggregate results
                        self.logger.info("Step 7d: Calling aggregate_job_results...")
                        final_result = self.aggregate_job_results(context)
                        self.logger.info(f"Step 7d: Aggregated results: {list(final_result.keys()) if isinstance(final_result, dict) else type(final_result)}")

                        # Step 7e: Complete job
                        self.logger.info("Step 7e: Calling state_manager.complete_job...")
                        self.state_manager.complete_job(
                            task_message.parent_job_id,
                            final_result
                        )

                        self.logger.info(f"✅ Step 7e: Job {task_message.parent_job_id} marked as COMPLETED")
                        self.logger.info(f"✅ JOB COMPLETION SUCCESSFUL")

                    except Exception as e:
                        # CRITICAL: Log the error but MUST re-raise to fail the message
                        # Otherwise job stays stuck in PROCESSING
                        self.logger.error(f"❌ CRITICAL JOB COMPLETION FAILURE for {task_message.parent_job_id}: {e}")
                        self.logger.error(f"Exception type: {type(e).__name__}")
                        import traceback
                        self.logger.error(f"Full traceback:\n{traceback.format_exc()}")
                        # CRITICAL: Re-raise to ensure message fails and can be retried
                        raise
            else:
                self.logger.debug(f"Task {task_message.task_id} completed but stage not complete (remaining: {completion.remaining_tasks})")

            return {
                'success': True,
                'task_id': task_message.task_id,
                'stage_complete': completion.stage_complete if hasattr(completion, 'stage_complete') else False
            }
        else:
            # Task failed - return failure dict
            # Extract error info from TaskResult
            if result and isinstance(result, TaskResult):
                return {
                    'success': False,
                    'error': result.error_details or 'Task execution failed',
                    'error_type': 'task_failure',
                    'task_id': task_message.task_id
                }
            else:
                # Should not happen but handle gracefully
                return {
                    'success': False,
                    'error': 'Task processing failed - no result',
                    'error_type': 'unknown',
                    'task_id': task_message.task_id
                }

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _generate_correlation_id(self) -> str:
        """Generate correlation ID for tracking."""
        return str(uuid.uuid4())[:8]

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary."""
        if not self.batch_metrics:
            return {
                'message': 'No batch operations performed',
                'architecture': 'clean'
            }

        total_tasks = sum(m['total_tasks'] for m in self.batch_metrics)
        total_time = sum(m['elapsed_ms'] for m in self.batch_metrics)

        return {
            'architecture': 'clean',
            'operations': len(self.batch_metrics),
            'total_tasks': total_tasks,
            'total_time_ms': total_time,
            'avg_throughput': total_tasks / (total_time / 1000) if total_time > 0 else 0
        }