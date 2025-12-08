"""
CoreMachine - Universal Job Orchestrator.

Universal job orchestrator using composition to avoid the God Class anti-pattern.
Coordinates all workflows without containing job-specific logic.

Key Principles:
    1. Composition: All dependencies injected, none created internally
    2. Single Responsibility: Only coordinate, never execute business logic
    3. Delegation: Specialized components handle all actual work
    4. Stateless: No job-specific state stored in CoreMachine

Exports:
    CoreMachine: Universal orchestrator class

Dependencies:
    jobs.registry: Job workflow definitions
    services.registry: Task handler implementations
    core: StateManager, OrchestrationManager
    infrastructure: Repository implementations

Entry Points:
    process_job_message(): Process job queue messages
    process_task_message(): Process task queue messages
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
from config.defaults import TaskRoutingDefaults
from config.app_mode_config import get_app_mode_config, AppMode

# Logging
from util_logger import LoggerFactory, ComponentType

# Error handling (13 NOV 2025 - Part 1 Task 1.3, 28 NOV 2025 - nested error logging)
from core.error_handler import CoreMachineErrorHandler, log_nested_error

# Exception categorization for retry decisions (13 NOV 2025 - Part 2 Task 2.4)
from exceptions import (
    BusinessLogicError,
    ServiceBusError,
    DatabaseError,
    ResourceNotFoundError,
    ContractViolationError,
    TaskExecutionError
)

# Exceptions worth retrying (transient failures)
RETRYABLE_EXCEPTIONS = (
    IOError,           # File system temporary issues
    OSError,           # OS-level errors (often transient)
    TimeoutError,      # Network/operation timeouts
    ConnectionError,   # Database/API connection issues
    ServiceBusError,   # Service Bus transient failures
    DatabaseError,     # Database operation failures (connection, deadlock, etc.)
)

# Exceptions NOT worth retrying (permanent failures)
PERMANENT_EXCEPTIONS = (
    ValueError,        # Invalid parameters (won't fix on retry)
    TypeError,         # Wrong type (programming bug)
    KeyError,          # Missing expected key (programming bug)
    AttributeError,    # Missing attribute (programming bug)
    ContractViolationError,  # Programming bug
    ResourceNotFoundError,   # Resource doesn't exist (won't appear on retry)
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
        config: Optional[AppConfig] = None,
        on_job_complete: Optional[callable] = None
    ):
        """
        Initialize CoreMachine with EXPLICIT registries (no decorator magic).

        CRITICAL: Registries must be passed explicitly to avoid import timing issues.
        Previous decorator-based approach failed because modules weren't imported (10 SEP 2025).

        Args:
            all_jobs: ALL_JOBS dict from jobs/__init__.py (explicit job registry)
            all_handlers: ALL_HANDLERS dict from services/__init__.py (explicit handler registry)
            state_manager: Database state manager (injected for testability)
            config: Application configuration (injected for testability)
            on_job_complete: Optional callback(job_id, job_type, status, result) called when job completes/fails
                            Used by Platform layer for job orchestration and chaining (30 OCT 2025)
        """
        # EXPLICIT REGISTRIES - No decorator magic.
        self.jobs_registry = all_jobs
        self.handlers_registry = all_handlers

        # Composition: Inject dependencies
        self.state_manager = state_manager or StateManager()
        self.config = config or AppConfig.from_environment()

        # App mode configuration (07 DEC 2025 - Multi-App Architecture)
        self.app_mode_config = get_app_mode_config()

        # Completion callback (Platform layer integration - 30 OCT 2025)
        self.on_job_complete = on_job_complete

        # Lazy-loaded repository caches (13 NOV 2025 - Part 1 Task 1.1)
        self._repos = None
        self._service_bus_repo = None

        # Logging
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "CoreMachine"
        )

        self.logger.info(f"CoreMachine initialized - {len(all_jobs)} jobs, {len(all_handlers)} handlers registered")
        self.logger.debug(f"   Registered jobs: {list(all_jobs.keys())}")
        self.logger.debug(f"   Registered handlers: {list(all_handlers.keys())}")
        if on_job_complete:
            self.logger.info(f"   ✅ Job completion callback registered (Platform integration)")

    # ========================================================================
    # LAZY-LOADED REPOSITORY PROPERTIES (13 NOV 2025 - Part 1 Task 1.1)
    # ========================================================================

    @property
    def repos(self) -> Dict[str, Any]:
        """
        Lazy-loaded repository bundle (job_repo, task_repo, etc.).

        Reuses same repositories across function invocation for connection pooling.
        Invalidates on Azure Functions cold start (instance recreation).

        Returns:
            Dict containing job_repo, task_repo, and other repositories

        Usage:
            job_record = self.repos['job_repo'].get_job(job_id)
            self.repos['task_repo'].create_task(task_record)
        """
        if self._repos is None:
            self._repos = RepositoryFactory.create_repositories()
            self.logger.debug("✅ Repository bundle created (lazy load)")
        return self._repos

    @property
    def service_bus(self):
        """
        Lazy-loaded Service Bus repository.

        Reuses connection for better performance across multiple sends.

        Returns:
            ServiceBusRepository instance

        Usage:
            self.service_bus.send_message(queue_name, message)
        """
        if self._service_bus_repo is None:
            self._service_bus_repo = RepositoryFactory.create_service_bus_repository()
            self.logger.debug("✅ Service Bus repository created (lazy load)")
        return self._service_bus_repo

    # ========================================================================
    # TASK ROUTING (07 DEC 2025 - Multi-App Architecture)
    # ========================================================================

    def _get_queue_for_task(self, task_type: str) -> str:
        """
        Route task to appropriate queue based on task type.

        Uses TaskRoutingDefaults to determine queue category:
        - RASTER_TASKS → raster_tasks_queue (GDAL operations, low concurrency)
        - VECTOR_TASKS → vector_tasks_queue (DB operations, high concurrency)
        - Default → tasks_queue (legacy/fallback)

        Args:
            task_type: The task_type field from TaskDefinition

        Returns:
            Queue name string (e.g., "raster-tasks", "vector-tasks", "geospatial-tasks")

        Used by:
            - _batch_queue_tasks() - groups tasks by target queue
            - _individual_queue_tasks() - routes each task

        Example:
            queue = self._get_queue_for_task("handler_raster_create_cog")
            # Returns: "raster-tasks"
        """
        # Determine task category
        if task_type in TaskRoutingDefaults.RASTER_TASKS:
            queue_name = self.config.queues.raster_tasks_queue
            self.logger.debug(f"📤 Task type '{task_type}' → raster queue: {queue_name}")
        elif task_type in TaskRoutingDefaults.VECTOR_TASKS:
            queue_name = self.config.queues.vector_tasks_queue
            self.logger.debug(f"📤 Task type '{task_type}' → vector queue: {queue_name}")
        else:
            # Fallback to legacy tasks queue
            queue_name = self.config.queues.tasks_queue
            self.logger.debug(f"📤 Task type '{task_type}' → default queue: {queue_name}")

        return queue_name

    # ========================================================================
    # TASK CONVERSION HELPERS (13 NOV 2025 - Part 1 Task 1.2)
    # ========================================================================

    def _task_definition_to_record(
        self,
        task_def: TaskDefinition,
        task_index: int,
        target_queue: Optional[str] = None
    ) -> TaskRecord:
        """
        Convert TaskDefinition to TaskRecord for database persistence.

        Single source of truth for TaskRecord creation. Ensures consistent
        status, timestamps, and field mapping across batch and individual queueing.

        Args:
            task_def: TaskDefinition from job's create_tasks_for_stage()
            task_index: Index in task list (for task_index field)
            target_queue: Queue name this task will be sent to (07 DEC 2025)

        Returns:
            TaskRecord ready for database insertion

        Used by:
            - _individual_queue_tasks() (individual task creation)
            - _batch_queue_tasks() (batch task creation)

        Example:
            queue_name = self._get_queue_for_task(task_def.task_type)
            task_record = self._task_definition_to_record(task_def, 0, queue_name)
            self.repos['task_repo'].create_task(task_record)
        """
        return TaskRecord(
            task_id=task_def.task_id,
            parent_job_id=task_def.parent_job_id,
            job_type=task_def.job_type,
            task_type=task_def.task_type,
            status=TaskStatus.QUEUED,  # Always QUEUED (not 'pending_queue')
            stage=task_def.stage,
            task_index=str(task_index),
            parameters=task_def.parameters,
            metadata=task_def.metadata or {},
            target_queue=target_queue,  # Multi-app tracking (07 DEC 2025)
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

    def _task_definition_to_message(
        self,
        task_def: TaskDefinition
    ) -> TaskQueueMessage:
        """
        Convert TaskDefinition to TaskQueueMessage for Service Bus.

        Single source of truth for queue message creation. Generates fresh
        correlation_id for tracing individual task execution.

        Args:
            task_def: TaskDefinition from job's create_tasks_for_stage()

        Returns:
            TaskQueueMessage ready for Service Bus

        Used by:
            - _individual_queue_tasks() (individual task queueing)
            - _batch_queue_tasks() (batch task queueing - via to_queue_message())

        Example:
            queue_message = self._task_definition_to_message(task_def)
            self.service_bus.send_message(queue_name, queue_message)
        """
        return TaskQueueMessage(
            task_id=task_def.task_id,
            parent_job_id=task_def.parent_job_id,
            job_type=task_def.job_type,
            task_type=task_def.task_type,
            stage=task_def.stage,
            parameters=task_def.parameters,
            correlation_id=str(uuid.uuid4())[:8]  # Fresh correlation_id
        )

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
        self.logger.debug(f"💾 COREMACHINE STEP 3: Fetching job record from database...")
        with CoreMachineErrorHandler.handle_operation(
            self.logger,
            "fetch job record from database",
            job_id=job_message.job_id
        ):
            job_record = self.repos['job_repo'].get_job(job_message.job_id)
            if not job_record:
                raise ValueError(f"Job {job_message.job_id} not found in database")
        self.logger.info(f"✅ COREMACHINE STEP 3: Job record retrieved - parameters={list(job_record.parameters.keys())}")

        # Step 3: Update job status to PROCESSING
        # NOTE: This will raise exception if status transition is invalid (e.g., PROCESSING → PROCESSING)
        # which is CORRECT behavior - invalid transitions indicate bugs in stage advancement logic
        self.logger.debug(f"📝 COREMACHINE STEP 4: Updating job status to PROCESSING...")
        self.state_manager.update_job_status(
            job_message.job_id,
            JobStatus.PROCESSING
        )
        self.logger.info(f"✅ COREMACHINE STEP 4: Job status updated to PROCESSING")

        # Step 3.1: Update job stage to match message stage (for monitoring/status queries)
        # FIX: 14 NOV 2025 - Job stage field was not advancing even though Stage 2+ tasks were processing
        # This keeps the job record stage field synchronized with actual processing stage
        if job_record.stage != job_message.stage:
            self.logger.debug(
                f"📝 COREMACHINE STEP 4.1: Updating job stage {job_record.stage} → {job_message.stage}..."
            )
            self.state_manager.update_job_stage(job_message.job_id, job_message.stage)
            self.logger.info(f"✅ COREMACHINE STEP 4.1: Job stage updated to {job_message.stage}")

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
        # ====================================================================================
        # JOB INTERFACE CONTRACT: Method 5 of 5
        # ====================================================================================
        # create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list) -> List[dict]
        # - Returns list of plain dicts with keys: task_id, task_type, parameters
        # - CoreMachine converts dicts → TaskDefinition Pydantic objects (next step)
        # - Enforced at import time by: jobs/__init__.py validate_job_registry()
        # ====================================================================================

        # ====================================================================================
        # PARALLELISM PATTERN DETECTION (16 OCT 2025)
        # ====================================================================================
        # Three parallelism patterns (defined in stage_definition["parallelism"]):
        #
        # 1. "single": Orchestration-time parallelism
        #    - Job creates tasks BEFORE any execution
        #    - N from params (n=10) OR hardcoded (always 1 task)
        #    - Example: Create N tiles from params, OR create 1 analysis task
        #
        # 2. "fan_out": Result-driven parallelism
        #    - Job creates tasks FROM previous stage execution results
        #    - N discovered at runtime (previous_results contains list)
        #    - Example: Stage 1 lists files → Stage 2 creates task per file
        #
        # 3. "fan_in": Auto-aggregation (CoreMachine handles)
        #    - CoreMachine auto-creates 1 task (job does nothing)
        #    - Task receives ALL previous results
        #    - Example: Stage 2 has N tasks → Stage 3 aggregates all N
        # ====================================================================================

        # Extract stage definition from job class metadata
        stage_definition = None
        if hasattr(job_class, 'stages') and job_class.stages:
            stage_definition = job_class.stages[job_message.stage - 1] if job_message.stage <= len(job_class.stages) else None

        # Check if this is a fan-in stage (auto-aggregation pattern)
        is_fan_in = stage_definition and stage_definition.get("parallelism") == "fan_in"

        try:
            self.logger.debug(f"🏗️ COREMACHINE STEP 5: Generating task definitions for stage {job_message.stage}...")

            if is_fan_in:
                # Pattern 3: Fan-In (CoreMachine auto-creates aggregation task)
                self.logger.info(f"🔷 FAN-IN PATTERN: Auto-creating aggregation task for stage {job_message.stage}")
                tasks = self._create_fan_in_task(
                    job_message.job_id,
                    job_message.stage,
                    previous_results,
                    stage_definition,
                    job_record.parameters
                )
                self.logger.info(f"✅ COREMACHINE STEP 5: Auto-generated 1 fan-in aggregation task")
            else:
                # Pattern 1 or 2: Job creates tasks (single or fan_out)
                # Job decides: "single" = N from params/hardcoded, "fan_out" = N from previous_results
                tasks = job_class.create_tasks_for_stage(
                    job_message.stage,
                    job_record.parameters,
                    job_message.job_id,
                    previous_results=previous_results  # For fan-out: previous stage results
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
    # STAGE COMPLETE PROCESSING - Entry point for stage_complete messages
    # ========================================================================

    def process_stage_complete_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process stage_complete message from worker apps.

        This is called when a stage_complete message arrives from the jobs queue.
        Worker apps send these after completing the last task of a stage.
        Platform app handles stage advancement/job completion.

        Message format:
            {
                'message_type': 'stage_complete',
                'job_id': str,
                'job_type': str,
                'completed_stage': int,
                'completed_at': str (ISO timestamp),
                'completed_by_app': str,
                'correlation_id': str
            }

        Args:
            message: Stage complete message dict

        Returns:
            Result dict with success status and metadata

        Raises:
            BusinessLogicError: If stage advancement fails

        Added: 07 DEC 2025 - Multi-App Architecture
        """
        job_id = message.get('job_id')
        job_type = message.get('job_type')
        completed_stage = message.get('completed_stage')
        completed_by_app = message.get('completed_by_app', 'unknown')
        correlation_id = message.get('correlation_id', 'unknown')

        self.logger.info(
            f"📬 [STAGE_COMPLETE_RECV] Received stage_complete message "
            f"(job: {job_id[:16]}..., stage: {completed_stage}, from: {completed_by_app})",
            extra={
                'checkpoint': 'STAGE_COMPLETE_MESSAGE_RECEIVED',
                'job_id': job_id,
                'job_type': job_type,
                'completed_stage': completed_stage,
                'completed_by_app': completed_by_app,
                'correlation_id': correlation_id,
                'app_mode': self.app_mode_config.mode.value
            }
        )

        try:
            # Handle stage completion (advance or finalize)
            self._handle_stage_completion(job_id, job_type, completed_stage)

            self.logger.info(
                f"✅ [STAGE_COMPLETE_RECV] Successfully processed stage_complete",
                extra={
                    'checkpoint': 'STAGE_COMPLETE_MESSAGE_SUCCESS',
                    'job_id': job_id,
                    'completed_stage': completed_stage
                }
            )

            return {
                'success': True,
                'message': f'Stage {completed_stage} complete, advanced job',
                'job_id': job_id,
                'completed_stage': completed_stage,
                'completed_by_app': completed_by_app
            }

        except Exception as e:
            self.logger.error(
                f"❌ [STAGE_COMPLETE_RECV] Failed to process stage_complete: {e}",
                extra={
                    'checkpoint': 'STAGE_COMPLETE_MESSAGE_FAILED',
                    'job_id': job_id,
                    'completed_stage': completed_stage,
                    'error': str(e)
                }
            )

            # Try to mark job as failed
            try:
                self._mark_job_failed(
                    job_id,
                    f"Stage complete processing failed: {e}"
                )
            except Exception as cleanup_error:
                self.logger.error(f"❌ Failed to mark job as failed: {cleanup_error}")

            raise BusinessLogicError(f"Stage complete processing failed: {e}")

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
            # DIAGNOSTIC: Get current status before attempting update (11 NOV 2025)
            current_status = self.state_manager.get_task_current_status(task_message.task_id)
            self.logger.debug(
                f"🔍 [STATUS-UPDATE] Task {task_message.task_id[:16]} current status: {current_status}, "
                f"attempting update to PROCESSING..."
            )

            success = self.state_manager.update_task_status_direct(
                task_message.task_id,
                TaskStatus.PROCESSING
            )
            if success:
                self.logger.debug(f"✅ Task {task_message.task_id[:16]} → PROCESSING (update successful)")
            else:
                # FP2 FIX: Fail-fast if status update fails (don't execute handler)
                error_msg = (
                    f"Failed to update task status to PROCESSING (returned False) - "
                    f"current_status={current_status}, possible causes: task not found, "
                    f"concurrent modification, or database constraint"
                )
                self.logger.error(f"❌ {error_msg}")

                # Mark task and job as FAILED
                # Create a RuntimeError to preserve context if cleanup fails
                primary_error = RuntimeError(error_msg)
                try:
                    self.state_manager.mark_task_failed(task_message.task_id, error_msg)
                    self.state_manager.mark_job_failed(
                        task_message.parent_job_id,
                        f"Task {task_message.task_id} failed to enter PROCESSING state: {error_msg}"
                    )
                    self.logger.error(f"❌ Task and job marked as FAILED - handler will NOT execute")
                except Exception as cleanup_error:
                    # 28 NOV 2025: Preserve both primary and cleanup error context
                    log_nested_error(
                        self.logger,
                        primary_error=primary_error,
                        cleanup_error=cleanup_error,
                        operation="mark_task_and_job_failed_after_status_update_failure",
                        job_id=task_message.parent_job_id,
                        task_id=task_message.task_id
                    )

                # Return failure - do NOT execute task handler
                return {
                    'success': False,
                    'error': error_msg,
                    'task_id': task_message.task_id,
                    'handler_executed': False
                }

        except Exception as e:
            # FP2 FIX: Exception during status update - fail-fast
            error_msg = f"Exception updating task status to PROCESSING: {e}"
            self.logger.error(f"❌ {error_msg}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")

            # Mark task and job as FAILED
            # Create primary error for context preservation
            primary_error = RuntimeError(error_msg)
            try:
                self.state_manager.mark_task_failed(task_message.task_id, error_msg)
                self.state_manager.mark_job_failed(
                    task_message.parent_job_id,
                    f"Task {task_message.task_id} status update exception: {e}"
                )
            except Exception as cleanup_error:
                # 28 NOV 2025: Preserve both primary and cleanup error context
                log_nested_error(
                    self.logger,
                    primary_error=primary_error,
                    cleanup_error=cleanup_error,
                    operation="mark_task_and_job_failed_after_status_update_exception",
                    job_id=task_message.parent_job_id,
                    task_id=task_message.task_id
                )

            # Return failure - do NOT execute handler
            return {
                'success': False,
                'error': error_msg,
                'task_id': task_message.task_id,
                'handler_executed': False
            }

        # Step 2: Execute task handler
        result = None
        try:
            self.logger.debug(f"▶️ Executing handler for task {task_message.task_id[:16]}...")
            start_time = time.time()

            # Inject job context into parameters (underscore prefix = system-injected)
            # This allows handlers to access job_id, job_type, stage without modifying every job definition
            #
            # NOTE: _heartbeat_fn DISABLED (2 DEC 2025) - Token expiration issues
            # When re-enabling, add this to enriched_params:
            #   '_heartbeat_fn': lambda tid=task_id: self.repos['task_repo'].update_task_heartbeat(tid),
            # See services/raster_cog.py HeartbeatWrapper class for usage
            task_id = task_message.task_id
            enriched_params = {
                **task_message.parameters,
                '_job_id': task_message.parent_job_id,
                '_job_type': task_message.job_type,
                '_stage': task_message.stage,
                '_task_id': task_id,
                # '_heartbeat_fn': DISABLED - see note above
            }

            # Execute handler (returns dict or TaskResult)
            raw_result = handler(enriched_params)

            elapsed = time.time() - start_time
            self.logger.debug(f"✅ Handler executed in {elapsed:.2f}s")

            # Convert dict to TaskResult if needed
            if isinstance(raw_result, dict):
                # ENFORCE CONTRACT: Task handlers MUST return {'success': True/False, ...}
                if 'success' not in raw_result:
                    raise ContractViolationError(
                        f"Task handler '{task_message.task_type}' returned dict without 'success' field. "
                        f"Required format: {{'success': True/False, 'result': {{...}}}} or {{'success': False, 'error': '...'}}"
                    )

                # Validate success field is boolean
                if not isinstance(raw_result['success'], bool):
                    raise ContractViolationError(
                        f"Task handler '{task_message.task_type}' returned non-boolean 'success' field: "
                        f"{type(raw_result['success']).__name__}. Must be True or False."
                    )

                # Extract error message from dict if handler failed
                error_msg = raw_result.get('error') if not raw_result['success'] else None

                result = TaskResult(
                    task_id=task_message.task_id,
                    task_type=task_message.task_type,
                    status=TaskStatus.COMPLETED if raw_result['success'] else TaskStatus.FAILED,
                    result_data=raw_result,
                    error_details=error_msg,
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

        # Exception categorization (13 NOV 2025 - Part 2 Task 2.4)
        except RETRYABLE_EXCEPTIONS as e:
            # Transient failures worth retrying (network, I/O, etc.)
            self.logger.warning(f"⚠️ Retryable failure ({type(e).__name__}): {e}")
            result = TaskResult(
                task_id=task_message.task_id,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={
                    'error': str(e),
                    'error_type': 'transient',
                    'exception_class': type(e).__name__,
                    'retryable': True
                },
                error_details=str(e),
                timestamp=datetime.now(timezone.utc)
            )

        except PERMANENT_EXCEPTIONS as e:
            # Permanent failures - retry won't help (bad params, programming bugs)
            self.logger.error(f"❌ Permanent failure ({type(e).__name__}): {e}")
            result = TaskResult(
                task_id=task_message.task_id,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={
                    'error': str(e),
                    'error_type': 'permanent',
                    'exception_class': type(e).__name__,
                    'retryable': False
                },
                error_details=str(e),
                timestamp=datetime.now(timezone.utc)
            )

        except TaskExecutionError as e:
            # Business logic failure (expected, typically retryable)
            self.logger.warning(f"⚠️ Task execution failed (business logic): {e}")
            result = TaskResult(
                task_id=task_message.task_id,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={
                    'error': str(e),
                    'error_type': 'business_logic',
                    'exception_class': 'TaskExecutionError',
                    'retryable': True
                },
                error_details=str(e),
                timestamp=datetime.now(timezone.utc)
            )

        except Exception as e:
            # Unknown exception - retry cautiously (err on side of retry)
            self.logger.error(f"❌ Unknown exception ({type(e).__name__}): {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            result = TaskResult(
                task_id=task_message.task_id,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={
                    'error': str(e),
                    'error_type': 'unknown',
                    'exception_class': type(e).__name__,
                    'retryable': True  # Err on side of retry for unknown exceptions
                },
                error_details=str(e),
                timestamp=datetime.now(timezone.utc)
            )

        # Step 3: Complete task and check stage (atomic)
        if result.status == TaskStatus.COMPLETED:
            try:
                self.logger.debug(
                    f"📝 [TASK_COMPLETE] Marking task {task_message.task_id[:16]} as COMPLETED in database... (core/machine.py:process_task_message)",
                    extra={
                        'checkpoint': 'TASK_COMPLETE',
                        'task_id': task_message.task_id,
                        'job_id': task_message.parent_job_id,
                        'stage': task_message.stage
                    }
                )
                completion = self.state_manager.complete_task_with_sql(
                    task_message.task_id,
                    task_message.parent_job_id,
                    task_message.stage,
                    result
                )

                self.logger.info(
                    f"✅ [TASK_COMPLETE] Task marked COMPLETED (stage_complete: {completion.stage_complete}, "
                    f"remaining: {completion.remaining_tasks}) (core/machine.py:process_task_message)",
                    extra={
                        'checkpoint': 'TASK_COMPLETE_SUCCESS',
                        'task_id': task_message.task_id,
                        'job_id': task_message.parent_job_id,
                        'stage': task_message.stage,
                        'stage_complete': completion.stage_complete,
                        'remaining_tasks': completion.remaining_tasks,
                        'is_last_task': completion.stage_complete
                    }
                )

                # Step 4: Handle stage completion
                if completion.stage_complete:
                    self.logger.info(
                        f"🎯 [TASK_COMPLETE] Last task for stage {task_message.stage} - triggering stage completion (core/machine.py:process_task_message)",
                        extra={
                            'checkpoint': 'TASK_COMPLETE_LAST_TASK',
                            'task_id': task_message.task_id,
                            'job_id': task_message.parent_job_id,
                            'stage': task_message.stage,
                            'last_task_detected': True,
                            'app_mode': self.app_mode_config.mode.value
                        }
                    )
                    # FP3 FIX: Wrap stage advancement in try-catch to prevent orphaned jobs
                    try:
                        # Multi-App Architecture (07 DEC 2025):
                        # - Worker modes: Signal stage_complete to centralized jobs queue
                        # - Other modes: Handle stage completion locally
                        if self._should_signal_stage_complete():
                            self.logger.info(
                                f"📤 [WORKER_MODE] Signaling stage_complete to jobs queue "
                                f"(mode: {self.app_mode_config.mode.value})"
                            )
                            self._send_stage_complete_signal(
                                task_message.parent_job_id,
                                task_message.job_type,
                                task_message.stage
                            )
                        else:
                            # Local handling (standalone, platform_* modes)
                            self._handle_stage_completion(
                                task_message.parent_job_id,
                                task_message.job_type,
                                task_message.stage
                            )
                        self.logger.info(
                            f"✅ [TASK_COMPLETE] Stage {task_message.stage} advancement complete (core/machine.py:process_task_message)",
                            extra={
                                'checkpoint': 'TASK_COMPLETE_STAGE_ADVANCEMENT_SUCCESS',
                                'task_id': task_message.task_id,
                                'job_id': task_message.parent_job_id,
                                'stage': task_message.stage,
                                'stage_advanced': True,
                                'signaled_to_platform': self._should_signal_stage_complete()
                            }
                        )

                    except Exception as stage_error:
                        # Stage advancement failed - mark job as FAILED
                        self.logger.error(f"❌ Stage advancement failed: {stage_error}")
                        self.logger.error(f"Traceback: {traceback.format_exc()}")

                        error_msg = (
                            f"Stage {task_message.stage} completed but advancement to "
                            f"stage {task_message.stage + 1} failed: {type(stage_error).__name__}: {stage_error}"
                        )

                        try:
                            self.state_manager.mark_job_failed(
                                task_message.parent_job_id,
                                error_msg
                            )
                            self.logger.error(
                                f"❌ Job {task_message.parent_job_id[:16]}... marked as FAILED "
                                f"due to stage advancement failure"
                            )
                        except Exception as cleanup_error:
                            # 28 NOV 2025: Preserve both primary and cleanup error context
                            log_nested_error(
                                self.logger,
                                primary_error=stage_error,
                                cleanup_error=cleanup_error,
                                operation="mark_job_failed_after_stage_advancement_failure",
                                job_id=task_message.parent_job_id,
                                task_id=task_message.task_id,
                                stage=task_message.stage
                            )

                        # Do NOT re-raise - task is completed, just log failure
                        # Return failure status but don't crash function
                        return {
                            'success': True,  # Task itself succeeded
                            'task_completed': True,
                            'stage_complete': True,
                            'stage_advancement_failed': True,
                            'error': str(stage_error)
                        }

                return {
                    'success': True,
                    'task_id': task_message.task_id,
                    'stage_complete': completion.stage_complete
                }

            except Exception as e:
                # Task completion SQL failed (different from stage advancement)
                self.logger.error(f"❌ Failed to complete task SQL: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")

                # Try to mark task and job as failed
                try:
                    self.state_manager.mark_task_failed(task_message.task_id, str(e))
                    self.state_manager.mark_job_failed(
                        task_message.parent_job_id,
                        f"Task {task_message.task_id} completion SQL failed: {e}"
                    )
                except Exception as cleanup_error:
                    # 28 NOV 2025: Preserve both primary and cleanup error context
                    log_nested_error(
                        self.logger,
                        primary_error=e,
                        cleanup_error=cleanup_error,
                        operation="mark_task_and_job_failed_after_completion_sql_failure",
                        job_id=task_message.parent_job_id,
                        task_id=task_message.task_id
                    )

                # Do NOT re-raise - prevents infinite Service Bus retries
                return {
                    'success': False,
                    'error': str(e),
                    'task_id': task_message.task_id,
                    'sql_completion_failed': True
                }
        else:
            # Task failed - check if retry needed
            self.logger.warning(f"⚠️ Task failed: {result.error_details}")

            # Check if exception is retryable (13 NOV 2025 - Part 2 Task 2.4)
            is_retryable = result.result_data.get('retryable', True) if result.result_data else True
            error_type = result.result_data.get('error_type', 'unknown') if result.result_data else 'unknown'

            if not is_retryable:
                self.logger.error(
                    f"❌ Task failed with permanent error ({error_type}) - NOT retrying: "
                    f"{result.error_details}"
                )
                # Mark task as permanently failed (no retry)
                return {
                    'success': False,
                    'error': result.error_details,
                    'error_type': error_type,
                    'retryable': False,
                    'task_id': task_message.task_id,
                    'permanent_failure': True
                }

            self.logger.info(
                f"🔄 RETRY LOGIC STARTING for task {task_message.task_id[:16]} (error_type: {error_type})",
                extra={
                    'checkpoint': 'RETRY_LOGIC_START',
                    'error_source': 'orchestration',
                    'task_id': task_message.task_id,
                    'job_id': task_message.parent_job_id,
                    'error_type': error_type,
                    'retry_event': 'start'
                }
            )

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
            config = get_config()
            self.logger.debug(f"📋 Retry config: max_retries={config.task_max_retries}, base_delay={config.task_retry_base_delay}s")

            # Get current task to check retry count
            task_record = self.repos['task_repo'].get_task(task_message.task_id)

            if task_record is None:
                self.logger.error(f"❌ CRITICAL: task_record is NONE for task_id={task_message.task_id}")
                self.logger.error(f"❌ Cannot retry - task not found in database!")
            else:
                self.logger.info(f"📋 Task found: retry_count={task_record.retry_count}, max={config.task_max_retries}")

            if task_record and task_record.retry_count < config.task_max_retries:
                self.logger.info(
                    f"🔄 RETRY CONDITION MET: retry_count ({task_record.retry_count}) < max_retries ({config.task_max_retries})",
                    extra={
                        'checkpoint': 'RETRY_CONDITION_MET',
                        'error_source': 'orchestration',
                        'task_id': task_message.task_id,
                        'job_id': task_message.parent_job_id,
                        'current_retry_count': task_record.retry_count,
                        'max_retries': config.task_max_retries,
                        'retries_remaining': config.task_max_retries - task_record.retry_count,
                        'retry_event': 'condition_met'
                    }
                )
                # Retry needed - calculate exponential backoff delay
                retry_attempt = task_record.retry_count + 1
                delay_seconds = min(
                    config.task_retry_base_delay * (2 ** task_record.retry_count),
                    config.task_retry_max_delay
                )

                self.logger.info(
                    f"🔄 RETRY SCHEDULED - Task {task_message.task_id[:16]} failed (attempt {retry_attempt}/"
                    f"{config.task_max_retries}) - will retry in {delay_seconds}s",
                    extra={
                        'checkpoint': 'RETRY_SCHEDULED',
                        'error_source': 'orchestration',
                        'task_id': task_message.task_id,
                        'job_id': task_message.parent_job_id,
                        'task_type': task_message.task_type,
                        'retry_attempt': retry_attempt,
                        'max_retries': config.task_max_retries,
                        'delay_seconds': delay_seconds,
                        'base_delay': config.task_retry_base_delay,
                        'retry_event': 'scheduled'
                    }
                )

                try:
                    # Increment retry count and reset to QUEUED
                    self.logger.debug(f"📝 Incrementing retry_count from {task_record.retry_count} to {retry_attempt}")
                    self.state_manager.increment_task_retry_count(task_message.task_id)
                    self.logger.debug(f"✅ retry_count incremented successfully")

                    # Re-queue with delay using Service Bus scheduled delivery
                    # Modern pattern (30 NOV 2025): config.queues.tasks_queue
                    message_id = self.service_bus.send_message_with_delay(
                        config.queues.tasks_queue,
                        task_message,
                        delay_seconds
                    )

                    self.logger.info(
                        f"✅ Task retry scheduled - attempt {retry_attempt}, "
                        f"delay: {delay_seconds}s, message_id: {message_id}",
                        extra={
                            'checkpoint': 'RETRY_QUEUED_SUCCESS',
                            'error_source': 'orchestration',
                            'task_id': task_message.task_id,
                            'job_id': task_message.parent_job_id,
                            'task_type': task_message.task_type,
                            'retry_attempt': retry_attempt,
                            'delay_seconds': delay_seconds,
                            'message_id': message_id,
                            'retry_event': 'queued'
                        }
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
                        f"({config.task_max_retries}) - marking task and job as FAILED",
                        extra={
                            'checkpoint': 'RETRY_MAX_EXCEEDED',
                            'error_source': 'orchestration',
                            'task_id': task_message.task_id,
                            'job_id': task_message.parent_job_id,
                            'task_type': task_message.task_type,
                            'final_retry_count': task_record.retry_count,
                            'max_retries': config.task_max_retries,
                            'error_details': result.error_details,
                            'retry_event': 'max_exceeded'
                        }
                    )

                    # Mark the parent job as FAILED since task cannot be recovered
                    job_error_msg = (
                        f"Job failed due to task {task_message.task_id} exceeding max retries "
                        f"({config.task_max_retries}). Task error: {result.error_details}"
                    )
                    self.state_manager.mark_job_failed(
                        task_message.parent_job_id,
                        job_error_msg
                    )
                    self.logger.error(
                        f"❌ Job {task_message.parent_job_id[:16]} marked as FAILED "
                        f"due to task failure",
                        extra={
                            'checkpoint': 'JOB_FAILED_MAX_RETRIES',
                            'error_source': 'orchestration',
                            'job_id': task_message.parent_job_id,
                            'task_id': task_message.task_id,
                            'task_type': task_message.task_type,
                            'final_retry_count': task_record.retry_count,
                            'retry_event': 'job_failed'
                        }
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
        """
        Queue tasks in batches to Service Bus, routing by task type.

        Groups tasks by target queue (raster/vector/default) and sends
        each group to the appropriate queue. This enables multi-app
        architecture where different Function Apps process different task types.

        Updated: 07 DEC 2025 - Multi-App Architecture
        """
        start_time = time.time()
        total_tasks = len(task_defs)
        successful_batches = []
        failed_batches = []

        # Group tasks by target queue (07 DEC 2025 - Multi-App Architecture)
        tasks_by_queue: Dict[str, list] = {}
        for task_def in task_defs:
            queue_name = self._get_queue_for_task(task_def.task_type)
            if queue_name not in tasks_by_queue:
                tasks_by_queue[queue_name] = []
            tasks_by_queue[queue_name].append(task_def)

        # Log routing summary
        for queue, tasks in tasks_by_queue.items():
            self.logger.info(f"📤 Routing {len(tasks)} tasks to queue: {queue}")

        # Process each queue's tasks in batches
        global_task_idx = 0  # Track global index for task_index field
        for queue_name, queue_tasks in tasks_by_queue.items():
            queue_total = len(queue_tasks)

            for i in range(0, queue_total, self.BATCH_SIZE):
                batch = queue_tasks[i:i + self.BATCH_SIZE]
                batch_id = f"{job_id[:8]}-s{stage_number}-{queue_name[:6]}-b{i//self.BATCH_SIZE:03d}"

                try:
                    # Create task records with target_queue tracking
                    task_records = [
                        self._task_definition_to_record(
                            task_def,
                            global_task_idx + idx,
                            target_queue=queue_name
                        )
                        for idx, task_def in enumerate(batch)
                    ]
                    self.repos['task_repo'].batch_create_tasks(task_records)

                    # Send to Service Bus using helper (consistent message format)
                    messages = [
                        self._task_definition_to_message(task_def)
                        for task_def in batch
                    ]
                    result = self.service_bus.batch_send_messages(queue_name, messages)

                    if not result.success:
                        raise RuntimeError(f"Batch send failed: {result.errors}")

                    successful_batches.append({
                        'batch_id': batch_id,
                        'size': len(batch),
                        'queue': queue_name
                    })

                    self.logger.debug(f"✅ Batch {batch_id}: {len(batch)} tasks → {queue_name}")
                    global_task_idx += len(batch)

                except Exception as e:
                    self.logger.error(f"❌ Batch {batch_id} failed: {e}")
                    failed_batches.append({
                        'batch_id': batch_id,
                        'size': len(batch),
                        'queue': queue_name,
                        'error': str(e)
                    })

        elapsed_ms = (time.time() - start_time) * 1000
        tasks_queued = sum(b['size'] for b in successful_batches)

        # Build routing summary for return
        routing_summary = {
            queue: len(tasks) for queue, tasks in tasks_by_queue.items()
        }

        return {
            'status': 'completed' if not failed_batches else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'routing': routing_summary,  # NEW: Shows distribution across queues
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
        """
        Queue tasks individually to Service Bus, routing by task type.

        Routes each task to the appropriate queue (raster/vector/default)
        based on task_type. Used for small task batches below batch_threshold.

        Updated: 07 DEC 2025 - Multi-App Architecture
        """
        start_time = time.time()
        total_tasks = len(task_defs)
        tasks_queued = 0
        tasks_failed = 0

        # Track routing distribution (07 DEC 2025)
        routing_counts: Dict[str, int] = {}

        for idx, task_def in enumerate(task_defs):
            try:
                # Route task to appropriate queue based on task_type
                queue_name = self._get_queue_for_task(task_def.task_type)

                # Track routing distribution
                routing_counts[queue_name] = routing_counts.get(queue_name, 0) + 1

                # Create task record with target_queue tracking
                task_record = self._task_definition_to_record(
                    task_def, idx, target_queue=queue_name
                )
                self.repos['task_repo'].create_task(task_record)

                # Send to Service Bus using helper (single source of truth)
                queue_message = self._task_definition_to_message(task_def)
                self.service_bus.send_message(queue_name, queue_message)

                tasks_queued += 1

            except Exception as e:
                tasks_failed += 1
                self.logger.error(f"❌ Failed to queue task {task_def.task_id}: {e}")

        elapsed_ms = (time.time() - start_time) * 1000

        # Log routing summary
        for queue, count in routing_counts.items():
            self.logger.info(f"📤 Routed {count} tasks to queue: {queue}")

        return {
            'status': 'completed' if tasks_failed == 0 else 'partial',
            'total_tasks': total_tasks,
            'tasks_queued': tasks_queued,
            'tasks_failed': tasks_failed,
            'routing': routing_counts,  # NEW: Shows distribution across queues
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

        Location: core/machine.py:_handle_stage_completion()
        """
        self.logger.info(
            f"🎯 [STAGE_COMPLETE] Stage {completed_stage} complete for job {job_id[:16]}... (core/machine.py:_handle_stage_completion)",
            extra={
                'checkpoint': 'STAGE_COMPLETE',
                'job_id': job_id,
                'job_type': job_type,
                'completed_stage': completed_stage,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        )

        # Get workflow to check if we should advance
        # Get workflow class from explicit registry
        self.logger.debug(
            f"📋 [STAGE_COMPLETE] Looking up job_type '{job_type}' in registry...",
            extra={
                'checkpoint': 'STAGE_COMPLETE_LOOKUP_WORKFLOW',
                'job_id': job_id,
                'job_type': job_type
            }
        )
        if job_type not in self.jobs_registry:
            raise BusinessLogicError(f"Unknown job type: {job_type}. Available: {list(self.jobs_registry.keys())}")
        workflow = self.jobs_registry[job_type]
        self.logger.debug(
            f"✅ [STAGE_COMPLETE] Found workflow: {workflow.__name__}",
            extra={
                'checkpoint': 'STAGE_COMPLETE_LOOKUP_WORKFLOW_SUCCESS',
                'job_id': job_id,
                'workflow_name': workflow.__name__
            }
        )

        # Get stages from class attribute (pure data approach)
        stages = workflow.stages if hasattr(workflow, 'stages') else []
        total_stages = len(stages)
        self.logger.debug(
            f"📊 [STAGE_COMPLETE] Workflow has {total_stages} total stages, just completed stage {completed_stage}",
            extra={
                'checkpoint': 'STAGE_COMPLETE_CHECK_STAGES',
                'job_id': job_id,
                'total_stages': total_stages,
                'completed_stage': completed_stage,
                'has_more_stages': completed_stage < total_stages
            }
        )

        if completed_stage < len(stages):
            # Advance to next stage
            next_stage = completed_stage + 1
            self.logger.info(
                f"➡️ [STAGE_ADVANCE] Advancing from stage {completed_stage} → {next_stage} (core/machine.py:_advance_stage)",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_INIT',
                    'job_id': job_id,
                    'job_type': job_type,
                    'from_stage': completed_stage,
                    'to_stage': next_stage,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            )
            self._advance_stage(job_id, job_type, next_stage)
        else:
            # Complete job
            self.logger.info(
                f"🏁 [JOB_COMPLETE] All {total_stages} stages complete - finalizing job (core/machine.py:_complete_job)",
                extra={
                    'checkpoint': 'JOB_COMPLETE_INIT',
                    'job_id': job_id,
                    'job_type': job_type,
                    'total_stages': total_stages,
                    'all_stages_complete': True
                }
            )
            self._complete_job(job_id, job_type)

    def _send_stage_complete_signal(
        self,
        job_id: str,
        job_type: str,
        completed_stage: int
    ):
        """
        Send stage_complete message to centralized jobs queue.

        Used by worker apps (worker_raster, worker_vector) to signal stage
        completion back to the Platform app for orchestration.

        In multi-app architecture:
        - Workers process tasks from specialized queues
        - On last task completion, worker sends stage_complete to jobs queue
        - Platform app receives stage_complete and handles advancement

        Args:
            job_id: The job identifier
            job_type: The job type (for lookup in Platform registry)
            completed_stage: The stage number that just completed

        Added: 07 DEC 2025 - Multi-App Architecture
        """
        self.logger.info(
            f"📤 [STAGE_COMPLETE_SIGNAL] Sending stage_complete to jobs queue "
            f"(job: {job_id[:16]}..., stage: {completed_stage})",
            extra={
                'checkpoint': 'STAGE_COMPLETE_SIGNAL_SEND',
                'job_id': job_id,
                'job_type': job_type,
                'completed_stage': completed_stage,
                'app_mode': self.app_mode_config.mode.value,
                'app_name': self.app_mode_config.app_name
            }
        )

        # Create stage_complete message for jobs queue
        stage_complete_message = {
            'message_type': 'stage_complete',
            'job_id': job_id,
            'job_type': job_type,
            'completed_stage': completed_stage,
            'completed_at': datetime.now(timezone.utc).isoformat(),
            'completed_by_app': self.app_mode_config.app_name,
            'correlation_id': str(uuid.uuid4())[:8]
        }

        # Send to centralized jobs queue
        jobs_queue = self.config.queues.jobs_queue
        self.service_bus.send_message(jobs_queue, stage_complete_message)

        self.logger.info(
            f"✅ [STAGE_COMPLETE_SIGNAL] Message sent to {jobs_queue} "
            f"(correlation: {stage_complete_message['correlation_id']})",
            extra={
                'checkpoint': 'STAGE_COMPLETE_SIGNAL_SENT',
                'job_id': job_id,
                'queue': jobs_queue,
                'correlation_id': stage_complete_message['correlation_id']
            }
        )

    def _should_signal_stage_complete(self) -> bool:
        """
        Determine if this app should signal stage completion to jobs queue.

        Returns True for worker modes (worker_raster, worker_vector) which
        process tasks but don't handle stage orchestration locally.

        Returns False for modes that handle orchestration locally:
        - standalone: Does everything
        - platform_*: Handles jobs queue

        Added: 07 DEC 2025 - Multi-App Architecture
        """
        return self.app_mode_config.mode in [
            AppMode.WORKER_RASTER,
            AppMode.WORKER_VECTOR
        ]

    def _advance_stage(self, job_id: str, job_type: str, next_stage: int):
        """
        Queue next stage job message.

        Location: core/machine.py:_advance_stage()
        """
        try:
            self.logger.debug(
                f"📝 [STAGE_ADVANCE] Step 1: Fetching job record from database... (core/machine.py:_advance_stage)",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_GET_JOB',
                    'job_id': job_id,
                    'next_stage': next_stage
                }
            )
            # Get job record for parameters
            job_record = self.repos['job_repo'].get_job(job_id)
            self.logger.debug(
                f"✅ [STAGE_ADVANCE] Job record retrieved - has {len(job_record.parameters)} parameters",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_GET_JOB_SUCCESS',
                    'job_id': job_id,
                    'parameter_count': len(job_record.parameters),
                    'current_stage': job_record.stage
                }
            )

            self.logger.debug(
                f"📝 [STAGE_ADVANCE] Step 2: Updating job status PROCESSING → QUEUED... (core/machine.py:_advance_stage)",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_STATUS_UPDATE',
                    'job_id': job_id,
                    'from_status': 'PROCESSING',
                    'to_status': 'QUEUED',
                    'next_stage': next_stage
                }
            )
            # Update job status to QUEUED before queuing next stage message
            # This allows clean QUEUED → PROCESSING transition when process_job_message() is triggered
            self.state_manager.update_job_status(job_id, JobStatus.QUEUED)
            self.logger.info(
                f"✅ [STAGE_ADVANCE] Job {job_id[:16]} status → QUEUED (ready for stage {next_stage})",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_STATUS_UPDATE_SUCCESS',
                    'job_id': job_id,
                    'status': 'QUEUED',
                    'next_stage': next_stage,
                    'ready_for_processing': True
                }
            )

            self.logger.debug(
                f"📝 [STAGE_ADVANCE] Step 3: Creating JobQueueMessage for stage {next_stage}... (core/machine.py:_advance_stage)",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_CREATE_MESSAGE',
                    'job_id': job_id,
                    'job_type': job_type,
                    'stage': next_stage
                }
            )

            # Create job message for next stage
            # correlation_id: Tracks which CoreMachine execution created this stage advancement
            # - Generated fresh for each stage transition (8-char UUID)
            # - Used for debugging: "Which execution advanced job to stage 2?"
            # - Different from function trigger correlation_id (log prefix [abc12345])
            # - Can be queried in Application Insights: customDimensions.correlation_id
            # - See core/schema/queue.py for full correlation_id documentation
            next_message = JobQueueMessage(
                job_id=job_id,
                job_type=job_type,
                parameters=job_record.parameters,
                stage=next_stage,
                correlation_id=str(uuid.uuid4())[:8]  # Stage advancement tracing
            )
            self.logger.debug(
                f"✅ [STAGE_ADVANCE] JobQueueMessage created (correlation_id: {next_message.correlation_id})",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_CREATE_MESSAGE_SUCCESS',
                    'job_id': job_id,
                    'message_correlation_id': next_message.correlation_id,
                    'stage': next_stage,
                    'message_created': True
                }
            )

            self.logger.debug(
                f"📝 [STAGE_ADVANCE] Step 4: Sending message to Service Bus queue '{self.config.queues.jobs_queue}'... (core/machine.py:_advance_stage)",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_QUEUE_MESSAGE',
                    'job_id': job_id,
                    'queue_name': self.config.queues.jobs_queue,
                    'stage': next_stage
                }
            )
            # Send to job queue (modern pattern - 30 NOV 2025)
            self.service_bus.send_message(
                self.config.queues.jobs_queue,
                next_message
            )
            self.logger.info(
                f"✅ [STAGE_ADVANCE] Message queued for stage {next_stage} - job will restart at stage {next_stage}",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_QUEUE_MESSAGE_SUCCESS',
                    'job_id': job_id,
                    'queue_name': self.config.queues.jobs_queue,
                    'stage': next_stage,
                    'message_queued': True
                }
            )

        except Exception as e:
            self.logger.error(
                f"❌ [STAGE_ADVANCE] Failed to advance stage: {e} (core/machine.py:_advance_stage)",
                extra={
                    'checkpoint': 'STAGE_ADVANCE_FAILED',
                    'error_source': 'orchestration',  # 29 NOV 2025: For Application Insights filtering
                    'job_id': job_id,
                    'job_type': job_type,
                    'next_stage': next_stage,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                    'traceback': traceback.format_exc()
                }
            )
            raise

    def _complete_job(self, job_id: str, job_type: str):
        """
        Complete job by aggregating results.

        Location: core/machine.py:_complete_job()
        """
        try:
            self.logger.info(f"🏁 [JOB_COMPLETE] Starting job completion for {job_id[:16]}... (core/machine.py:_complete_job)")

            self.logger.debug(f"📝 [JOB_COMPLETE] Step 1: Fetching all task records from database... (core/machine.py:_complete_job)")
            # Get all task records
            task_records = self.repos['task_repo'].get_tasks_for_job(job_id)

            if not task_records:
                raise RuntimeError(f"No tasks found for job {job_id}")

            self.logger.debug(f"✅ [JOB_COMPLETE] Found {len(task_records)} task records")

            # Convert to TaskResults
            task_results = []
            self.logger.debug(f"📝 [JOB_COMPLETE] Step 2: Converting {len(task_records)} task records to TaskResult objects... (core/machine.py:_complete_job)")
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
                    self.logger.error(f"❌ [JOB_COMPLETE] Failed to create TaskResult for task {idx}: {tr.task_id}")
                    self.logger.error(f"   Error: {e}")
                    self.logger.error(f"   Task data: status={tr.status}, updated_at={tr.updated_at}, created_at={tr.created_at}")
                    raise

            self.logger.debug(f"✅ [JOB_COMPLETE] All {len(task_results)} TaskResult objects created")

            self.logger.debug(f"📝 [JOB_COMPLETE] Step 3: Fetching job record from database... (core/machine.py:_complete_job)")
            # Get job record
            job_record = self.repos['job_repo'].get_job(job_id)

            self.logger.debug(f"✅ [JOB_COMPLETE] Job record retrieved")

            self.logger.debug(f"📝 [JOB_COMPLETE] Step 4: Creating JobExecutionContext... (core/machine.py:_complete_job)")
            # Create context
            context = JobExecutionContext(
                job_id=job_id,
                job_type=job_type,
                current_stage=job_record.stage,
                total_stages=job_record.total_stages,
                parameters=job_record.parameters
            )
            context.task_results = task_results
            self.logger.debug(f"✅ [JOB_COMPLETE] Context created with {len(task_results)} task results")

            self.logger.debug(f"📝 [JOB_COMPLETE] Step 5: Looking up workflow '{job_type}' for finalization... (core/machine.py:_complete_job)")
            # Finalize job (delegate to workflow for custom summary)
            # Get workflow class from explicit registry
            if job_type not in self.jobs_registry:
                raise BusinessLogicError(f"Unknown job type: {job_type}. Available: {list(self.jobs_registry.keys())}")
            workflow = self.jobs_registry[job_type]
            self.logger.debug(f"✅ [JOB_COMPLETE] Found workflow: {workflow.__name__}")

            self.logger.info(f"📝 [JOB_COMPLETE] Step 6: Calling {workflow.__name__}.finalize_job()... (jobs/{job_type}.py:finalize_job)")
            # Call finalize_job() with fallback handling (13 NOV 2025 - Part 2 Task 2.5)
            try:
                final_result = workflow.finalize_job(context)
                self.logger.debug(f"✅ [JOB_COMPLETE] finalize_job() returned {len(final_result)} keys: {list(final_result.keys())}")
            except Exception as finalize_error:
                # Finalization failed - create minimal fallback result to prevent zombie jobs
                self.logger.error(
                    f"❌ finalize_job() failed for {job_type}: {finalize_error}",
                    extra={
                        'checkpoint': 'JOB_FINALIZE_FAILED',
                        'error_source': 'orchestration',  # 29 NOV 2025: For Application Insights filtering
                        'job_id': job_id,
                        'job_type': job_type,
                        'finalization_error': str(finalize_error),
                        'error_type': type(finalize_error).__name__,
                        'task_count': len(task_results)
                    }
                )
                self.logger.error(f"Traceback: {traceback.format_exc()}")

                # Create fallback result with error details
                final_result = {
                    'job_type': job_type,
                    'status': 'completed_with_errors',
                    'finalization_error': str(finalize_error),
                    'error_type': type(finalize_error).__name__,
                    'task_count': len(task_results),
                    'completed_tasks': sum(1 for tr in task_results if tr.status == TaskStatus.COMPLETED),
                    'failed_tasks': sum(1 for tr in task_results if tr.status == TaskStatus.FAILED),
                    'message': (
                        f'Job completed but finalization failed: {finalize_error}. '
                        f'Check task results manually.'
                    )
                }
                self.logger.warning(
                    f"⚠️ Using fallback result for job {job_id[:16]} - "
                    f"job will be marked COMPLETED with errors"
                )

            self.logger.debug(
                f"📝 [JOB_COMPLETE] Step 7: Marking job as COMPLETED in database... (core/machine.py:_complete_job)",
                extra={
                    'checkpoint': 'JOB_COMPLETE_MARK_COMPLETE',
                    'job_id': job_id,
                    'job_type': job_type
                }
            )
            # Complete job in database
            self.state_manager.complete_job(job_id, final_result)
            self.logger.info(
                f"✅ [JOB_COMPLETE] Job marked as COMPLETED in database",
                extra={
                    'checkpoint': 'JOB_COMPLETE_MARK_COMPLETE_SUCCESS',
                    'job_id': job_id,
                    'job_type': job_type,
                    'status': 'COMPLETED',
                    'result_keys': list(final_result.keys()) if final_result else []
                }
            )

            # Invoke completion callback if registered (Platform integration - 30 OCT 2025)
            if self.on_job_complete:
                try:
                    self.logger.debug(f"📝 [JOB_COMPLETE] Step 8: Invoking Platform completion callback... (core/machine.py:_complete_job)")
                    self.on_job_complete(
                        job_id=job_id,
                        job_type=job_type,
                        status='completed',
                        result=final_result
                    )
                    self.logger.debug(f"✅ [JOB_COMPLETE] Platform callback completed successfully")
                except Exception as e:
                    # Callback failure should not fail the job
                    self.logger.warning(f"⚠️ [JOB_COMPLETE] Platform callback failed (non-fatal): {e}")
                    self.logger.warning(f"   Job {job_id[:16]} is still marked as completed")

            self.logger.info(
                f"✅ [JOB_COMPLETE] Job {job_id[:16]}... completed successfully! (core/machine.py:_complete_job)",
                extra={
                    'checkpoint': 'JOB_COMPLETE_SUCCESS',
                    'job_id': job_id,
                    'job_type': job_type,
                    'total_stages': total_stages if 'total_stages' in locals() else None,
                    'completion_confirmed': True
                }
            )

        except Exception as e:
            self.logger.error(
                f"❌ CRITICAL: Job completion failed: {e}",
                extra={
                    'checkpoint': 'JOB_COMPLETE_FAILED',
                    'error_source': 'orchestration',  # 29 NOV 2025: For Application Insights filtering
                    'job_id': job_id,
                    'job_type': job_type,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                    'traceback': traceback.format_exc()
                }
            )
            raise  # Must re-raise to fail the message

    def _mark_job_failed(self, job_id: str, error_message: str):
        """Mark job as failed."""
        try:
            self.logger.info(f"🚫 Marking job {job_id[:16]}... as FAILED")
            self.state_manager.update_job_status(job_id, JobStatus.FAILED)
            self.logger.info(f"✅ Job marked as FAILED: {error_message}")

            # Invoke completion callback for failures (Platform integration - 30 OCT 2025)
            if self.on_job_complete:
                try:
                    self.logger.debug(f"Invoking job failure callback for {job_id[:16]}...")
                    self.on_job_complete(
                        job_id=job_id,
                        job_type='unknown',  # job_type not available in this context
                        status='failed',
                        result={'error': error_message}
                    )
                except Exception as e:
                    # Callback failure should not affect failure handling
                    self.logger.warning(f"⚠️ Job failure callback failed (non-fatal): {e}")

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
        # Get all tasks for this job and stage
        all_tasks = self.repos['task_repo'].get_tasks_for_job(job_id)
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

    def _create_fan_in_task(
        self,
        job_id: str,
        stage: int,
        previous_results: list[dict],
        stage_definition: dict,
        job_parameters: dict
    ) -> list[dict]:
        """
        Auto-create single aggregation task for fan-in stage.

        This method is called when a stage has parallelism="fan_in".
        CoreMachine automatically creates a single task that receives ALL
        results from the previous stage for aggregation.

        Example:
            Stage 1: 1 task  → Lists files
            Stage 2: N tasks → Processes each file (fan-out)
            Stage 3: 1 task  → Aggregates N results (fan-in) ← THIS METHOD

        Args:
            job_id: Job ID
            stage: Current stage number (the fan-in stage)
            previous_results: All results from previous stage (N results from fan-out)
            stage_definition: Stage definition dict from job.stages
            job_parameters: Original job parameters

        Returns:
            List with single task dict containing:
            - task_id: Deterministic ID for aggregation task
            - task_type: From stage_definition["task_type"]
            - parameters: Includes previous_results + job_parameters

        Raises:
            ValueError: If previous_results is empty (nothing to aggregate)
            KeyError: If stage_definition missing required "task_type"
        """
        from core.task_id import generate_deterministic_task_id

        # Validation
        if not previous_results:
            raise ValueError(
                f"Fan-in stage {stage} requires previous stage results, "
                f"but previous_results is empty. Cannot aggregate nothing."
            )

        if "task_type" not in stage_definition:
            raise KeyError(
                f"Fan-in stage {stage} definition missing required 'task_type' field. "
                f"Stage definition: {stage_definition}"
            )

        task_type = stage_definition["task_type"]

        self.logger.info(
            f"🔷 Fan-In Stage {stage}: Creating aggregation task of type '{task_type}' "
            f"to aggregate {len(previous_results)} results from Stage {stage - 1}"
        )

        # Generate deterministic task ID
        task_id = generate_deterministic_task_id(job_id, stage, "fan_in_aggregate")

        # Create single aggregation task
        # Task handler receives ALL previous results + job parameters
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "parameters": {
                "previous_results": previous_results,  # All N results from Stage N-1
                "job_parameters": job_parameters,      # Original job parameters
                "aggregation_metadata": {
                    "stage": stage,
                    "previous_stage": stage - 1,
                    "result_count": len(previous_results),
                    "pattern": "fan_in"
                }
            }
        }

        self.logger.debug(f"   Task ID: {task_id}")
        self.logger.debug(f"   Task Type: {task_type}")
        self.logger.debug(f"   Aggregating: {len(previous_results)} results")

        return [task]
