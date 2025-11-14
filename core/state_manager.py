# ============================================================================
# CLAUDE CONTEXT - STATE MANAGEMENT
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component - Database state management with advisory locks
# PURPOSE: Manages all database state operations with advisory locks for atomic operations
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: StateManager - handles job/task state transitions and completion logic
# INTERFACES: Uses repositories for database access, provides atomic state management
# PYDANTIC_MODELS: JobRecord, TaskRecord, JobExecutionContext, StageAdvancementResult (from core.models)
# DEPENDENCIES: core.models, repositories, schema_updates, util_logger, typing
# SOURCE: Extracted from BaseController to enable composition-based architecture
# SCOPE: All database state mutations and advisory lock operations
# VALIDATION: Database constraints and atomic operations via PostgreSQL
# PATTERNS: Repository pattern, Unit of Work, Advisory Locks for race prevention
# ENTRY_POINTS: Used by controllers via composition for state management
# INDEX: StateManager:100, Job Operations:300, Stage Completion:600, Task Completion:900
# ============================================================================

"""
State Manager - Database State Management with Advisory Locks

Manages all database state operations including the critical "last task turns
out the lights" pattern using PostgreSQL advisory locks. This component is
ESSENTIAL for both Queue Storage and Service Bus to prevent race conditions.

Key Responsibilities:
- Job state transitions (QUEUED → PROCESSING → COMPLETED/FAILED)
- Task state transitions with atomic completion checks
- Stage advancement with advisory locks
- Job completion and result aggregation
- Database record creation and updates

Critical Pattern:
The "last task turns out the lights" pattern uses PostgreSQL advisory locks
to atomically determine when all tasks in a stage are complete, preventing
race conditions when multiple tasks complete simultaneously.

Author: Robert and Geospatial Claude Legion
Date: 26 SEP 2025
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import logging
import json

# Repositories for database access
from infrastructure import RepositoryFactory, StageCompletionRepository

# Pydantic models - using new core.models structure
from core.models import (
    JobRecord,
    TaskRecord,
    JobStatus,
    TaskStatus,
    JobExecutionContext,
    TaskResult,
    StageAdvancementResult
)
from core.schema import TaskUpdateModel, JobUpdateModel

# Logging
from util_logger import LoggerFactory, ComponentType


class StateManager:
    """
    Manages all database state operations with advisory locks.

    This component handles all database mutations related to job and task
    state, ensuring atomic operations and preventing race conditions through
    PostgreSQL advisory locks.

    Key Features:
    - Atomic state transitions with advisory locks
    - "Last task turns out lights" pattern for stage completion
    - Job and task record creation
    - Stage advancement logic
    - Result aggregation and storage

    Usage:
        state_manager = StateManager()

        # Create job record
        job_record = state_manager.create_job_record(job_id, params)

        # Complete task with atomic check
        completion = state_manager.complete_task_with_sql(task_id, result)
        if completion.stage_complete:
            # This task was the last one - advance stage
            state_manager.handle_stage_completion(job_id, stage)
    """

    def __init__(self):
        """Initialize state manager with logging and repository access."""
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "StateManager"
        )

        # Lazy-loaded repository cache (13 NOV 2025 - Part 1 Task 1.1)
        self._repos = None

        self.logger.info("StateManager initialized with lazy repository loading")

    # ========================================================================
    # LAZY-LOADED REPOSITORY PROPERTY (13 NOV 2025 - Part 1 Task 1.1)
    # ========================================================================

    @property
    def repos(self) -> Dict[str, Any]:
        """
        Lazy-loaded repository bundle (job_repo, task_repo, etc.).

        Reuses same repositories across state manager operations.
        Created on first access, then cached for subsequent calls.

        Returns:
            Dict containing job_repo, task_repo, and other repositories

        Usage:
            job_record = self.repos['job_repo'].get_job(job_id)
            self.repos['task_repo'].update_task_status(task_id, status)
        """
        if self._repos is None:
            from infrastructure import RepositoryFactory
            self._repos = RepositoryFactory.create_repositories()
            self.logger.debug("✅ Repository bundle created (lazy load)")
        return self._repos

    # ========================================================================
    # JOB RECORD OPERATIONS
    # ========================================================================

    def create_job_record(
        self,
        job_id: str,
        job_type: str,
        parameters: Dict[str, Any],
        total_stages: int
    ) -> JobRecord:
        """
        Create and store initial job record in database.

        Creates JobRecord in PostgreSQL with initial QUEUED status.
        This establishes the job in the system before any tasks are created.

        Args:
            job_id: Generated job ID (SHA256 hash)
            job_type: Type of job (e.g., "hello_world")
            parameters: Validated job parameters
            total_stages: Number of stages in workflow

        Returns:
            JobRecord instance stored in database

        Raises:
            RuntimeError: If database operation fails
        """
        self.logger.debug(f"Creating job record for {job_id[:16]}...")

        try:
            # Create job record
            job_record = self.repos['job_repo'].create_job_from_params(
                job_type=job_type,
                parameters=parameters,
                total_stages=total_stages
            )

            self.logger.info(f"Job record created: {job_id[:16]}... (status: QUEUED)")
            return job_record

        except Exception as e:
            self.logger.error(f"Failed to create job record: {e}")
            raise RuntimeError(f"Job record creation failed: {e}")

    def create_job_record(self, job_record: JobRecord) -> bool:
        """
        Create a new job record in the database.

        Args:
            job_record: JobRecord instance to store

        Returns:
            True if creation successful

        Raises:
            ContractViolationError: If job_record is not a JobRecord or has invalid types
            DatabaseError: If database operation fails
        """
        from exceptions import ContractViolationError, DatabaseError

        # CONTRACT ENFORCEMENT - Validate types
        # Note: JobRecord and JobStatus already imported from core.models at top
        if not isinstance(job_record, JobRecord):
            raise ContractViolationError(
                f"Contract violation: create_job_record requires JobRecord, "
                f"got {type(job_record).__name__}"
            )

        if not isinstance(job_record.status, JobStatus):
            raise ContractViolationError(
                f"Contract violation: JobRecord.status must be JobStatus enum, "
                f"got {type(job_record.status).__name__} with value '{job_record.status}'"
            )

        # BUSINESS LOGIC - Handle database errors gracefully
        try:
            self.repos['job_repo'].create_job(job_record)
            self.logger.info(f"Job record created: {job_record.job_id[:16]}...")
            return True
        except Exception as e:
            self.logger.error(f"Database error creating job record: {e}")
            raise DatabaseError(f"Failed to create job record: {e}") from e

    def get_job_record(self, job_id: str) -> Optional[JobRecord]:
        """
        Retrieve job record from database.

        Args:
            job_id: Job identifier

        Returns:
            JobRecord or None if not found
        """
        try:
            return self.repos['job_repo'].get_job(job_id)
        except Exception as e:
            self.logger.error(f"Failed to get job record: {e}")
            return None

    def update_job_status(
        self,
        job_id: str,
        new_status: JobStatus,
        error_details: Optional[str] = None
    ) -> bool:
        """
        Update job status in database.

        Args:
            job_id: Job identifier
            new_status: New job status
            error_details: Error message if status is FAILED

        Returns:
            True if update successful
        """
        try:

            if new_status == JobStatus.FAILED and error_details:
                self.repos['job_repo'].mark_job_failed(job_id, error_details)
            else:
                self.repos['job_repo'].update_job_status_with_validation(job_id, new_status)

            self.logger.info(f"Job {job_id[:16]}... status updated to {new_status}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to update job status: {e}")
            return False

    def update_job_with_model(
        self,
        job_id: str,
        update: JobUpdateModel
    ) -> bool:
        """
        Update job using type-safe Pydantic model.

        This method directly uses the Pydantic update model for type safety.

        Args:
            job_id: Job identifier
            update: JobUpdateModel with fields to update

        Returns:
            True if update successful
        """
        try:

            success = self.repos['job_repo'].update_job(job_id, update)
            if success:
                self.logger.info(f"Job {job_id[:16]}... updated with model")
            return success

        except Exception as e:
            self.logger.error(f"Failed to update job with model: {e}")
            return False

    def update_task_with_model(
        self,
        task_id: str,
        update: TaskUpdateModel
    ) -> bool:
        """
        Update task using type-safe Pydantic model.

        This method directly uses the Pydantic update model for type safety.

        Args:
            task_id: Task identifier
            update: TaskUpdateModel with fields to update

        Returns:
            True if update successful
        """
        try:

            success = self.repos['task_repo'].update_task(task_id, update)
            if success:
                self.logger.info(f"Task {task_id} updated with model")
            else:
                # FIX: Log when update returns False (11 NOV 2025)
                self.logger.warning(
                    f"⚠️ Task {task_id[:16]} update returned False - "
                    f"repository update_task() affected 0 rows"
                )
            return success

        except Exception as e:
            self.logger.error(f"Failed to update task with model: {e}")
            return False

    def update_task_status_direct(
        self,
        task_id: str,
        status: TaskStatus,
        error_details: Optional[str] = None
    ) -> bool:
        """
        Update task status using type-safe Pydantic model.

        This is a convenience method that creates the Pydantic model internally.

        Args:
            task_id: Task identifier
            status: New task status
            error_details: Optional error message

        Returns:
            True if update successful
        """
        update = TaskUpdateModel(
            status=status,
            error_details=error_details
        )
        return self.update_task_with_model(task_id, update)

    def get_task_current_status(self, task_id: str) -> Optional[TaskStatus]:
        """
        Get current task status for diagnostic purposes.

        Args:
            task_id: Task identifier

        Returns:
            Current TaskStatus or None if task not found
        """
        try:

            task = self.repos['task_repo'].get_task(task_id)
            return task.status if task else None

        except Exception as e:
            self.logger.error(f"Failed to get task status for {task_id}: {e}")
            return None

    def increment_task_retry_count(self, task_id: str) -> bool:
        """
        Increment retry count and reset status to QUEUED for retry.

        This delegates to TaskRepository which performs the atomic operation.

        Args:
            task_id: Task identifier

        Returns:
            True if updated successfully
        """
        return self.self.repos['task_repo'].increment_task_retry_count(task_id)

    def update_task_result(
        self,
        task_id: str,
        result_data: Dict[str, Any],
        status: Optional[TaskStatus] = None
    ) -> bool:
        """
        Update task result using type-safe Pydantic model.

        Args:
            task_id: Task identifier
            result_data: Result data to store
            status: Optional status to set

        Returns:
            True if update successful
        """
        update = TaskUpdateModel(
            result_data=result_data,
            status=status
        )
        return self.update_task_with_model(task_id, update)

    # ========================================================================
    # JOB COMPLETION
    # ========================================================================

    def complete_job(
        self,
        job_id: str,
        result_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Complete job with aggregated results.

        Marks job as COMPLETED and stores the final aggregated results.
        This signature matches JobRepository.complete_job for consistency.

        Args:
            job_id: Job identifier
            result_data: Already aggregated results from controller

        Returns:
            Completion status dictionary
        """
        self.logger.info(f"Completing job {job_id[:16]}...")

        try:

            # Get job record
            job_record = self.repos['job_repo'].get_job(job_id)
            if not job_record:
                raise ValueError(f"Job not found: {job_id}")

            # Pass the aggregated result directly to repository
            # (controller has already done the aggregation)
            success = self.repos['job_repo'].complete_job(job_id, result_data)

            if success:
                self.logger.info(f"Job {job_id[:16]}... completed successfully")
                return {"status": "completed", "job_id": job_id}
            else:
                raise RuntimeError("Failed to mark job as completed")

        except Exception as e:
            self.logger.error(f"Failed to complete job: {e}")
            raise RuntimeError(f"Job completion failed: {e}")

    # ========================================================================
    # STAGE COMPLETION & ADVANCEMENT
    # ========================================================================

    def handle_stage_completion(
        self,
        job_id: str,
        stage: int,
        total_stages: int
    ) -> Dict[str, Any]:
        """
        Handle stage completion and determine next action.

        This is called when a stage completes (all tasks done).
        Decides whether to advance to next stage or complete job.

        Args:
            job_id: Job identifier
            stage: Completed stage number
            total_stages: Total number of stages

        Returns:
            Dict with action (advance_stage or complete_job)
        """
        self.logger.info(f"Handling stage {stage} completion for job {job_id[:16]}...")

        try:
            stage_completion_repo = self.repos['stage_completion_repo']

            # Check if this is the final stage
            if stage >= total_stages:
                # Final stage - complete the job
                self.logger.info(f"Final stage complete - completing job {job_id[:16]}...")

                # Get all task results for final aggregation
                job_completion = stage_completion_repo.check_job_completion(job_id)

                if job_completion.job_complete:
                    # Create simple aggregated result
                    # (Controllers do more sophisticated aggregation)
                    aggregated_result = {
                        "total_tasks": job_completion.total_tasks,
                        "completed_tasks": job_completion.completed_tasks,
                        "final_stage": job_completion.final_stage,
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "task_count": len(job_completion.task_results),
                        "summary": "Job completed successfully"
                    }

                    # Mark job as completed with aggregated result
                    self.complete_job(job_id, aggregated_result)
                    return {"action": "job_completed", "job_id": job_id}
                else:
                    raise RuntimeError(f"Job completion check failed: {job_id}")

            else:
                # Not final stage - advance to next stage
                next_stage = stage + 1
                self.logger.info(f"Advancing job {job_id[:16]}... to stage {next_stage}")

                # Atomically advance stage in database
                advanced = stage_completion_repo.advance_job_stage(job_id, next_stage)

                if advanced:
                    return {
                        "action": "stage_advanced",
                        "job_id": job_id,
                        "next_stage": next_stage
                    }
                else:
                    raise RuntimeError(f"Failed to advance stage: {job_id}")

        except Exception as e:
            self.logger.error(f"Stage completion handling failed: {e}")
            raise RuntimeError(f"Stage completion failed: {e}")

    # ========================================================================
    # TASK COMPLETION WITH ADVISORY LOCKS (CRITICAL!)
    # ========================================================================

    def complete_task_with_sql(
        self,
        task_id: str,
        job_id: str,
        stage: int,
        task_result: Optional[TaskResult] = None
    ) -> StageAdvancementResult:
        """
        Complete task with atomic stage completion check.

        CRITICAL: This implements the "last task turns out the lights" pattern
        using PostgreSQL advisory locks to prevent race conditions.

        The PostgreSQL function atomically:
        1. Updates task status to COMPLETED/FAILED
        2. Checks if this was the last task in the stage
        3. Returns stage completion status

        Args:
            task_id: Task identifier
            job_id: Parent job identifier
            stage: Stage number
            task_result: Task execution result (None = failure)

        Returns:
            StageAdvancementResult indicating if stage is complete

        Raises:
            RuntimeError: If SQL operation fails
        """
        self.logger.debug(f"Starting SQL completion for task {task_id}")

        try:
            # Get repositories
            stage_completion_repo = self.repos['stage_completion_repo']

            # Verify task is in PROCESSING state
            task = self.repos['task_repo'].get_task(task_id)
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            if task.status != TaskStatus.PROCESSING:
                raise RuntimeError(
                    f"Task {task_id} has unexpected status: {task.status} "
                    f"(expected: PROCESSING)"
                )

            # Call PostgreSQL function with advisory lock
            if task_result and task_result.success:
                self.logger.debug(f"Completing successful task {task_id}")
                stage_completion = stage_completion_repo.complete_task_and_check_stage(
                    task_id=task_id,
                    job_id=job_id,
                    stage=stage,
                    result_data=task_result.result_data or {},
                    error_details=None
                )
            else:
                error_msg = (
                    task_result.error_details if task_result
                    else "Task execution failed - no result"
                )
                self.logger.debug(f"Completing failed task {task_id}: {error_msg[:100]}")
                stage_completion = stage_completion_repo.complete_task_and_check_stage(
                    task_id=task_id,
                    job_id=job_id,
                    stage=stage,
                    result_data={},
                    error_details=error_msg
                )

            # Log results
            self.logger.debug(f"SQL completion result for {task_id}:")
            self.logger.debug(f"  - task_updated: {stage_completion.task_updated}")
            self.logger.debug(f"  - stage_complete: {stage_completion.stage_complete}")
            self.logger.debug(f"  - remaining_tasks: {stage_completion.remaining_tasks}")

            if not stage_completion.task_updated:
                raise RuntimeError(f"SQL function failed to update task {task_id}")

            # Return completion status (caller handles stage advancement)
            return stage_completion

        except Exception as e:
            self.logger.error(f"Task completion SQL failed: {e}")
            raise RuntimeError(f"Task SQL completion failed: {e}")

    # ========================================================================
    # STAGE RESULTS MANAGEMENT
    # ========================================================================

    def get_stage_results(
        self,
        job_id: str,
        stage_number: Optional[int] = None
    ) -> Dict[int, Dict[str, Any]]:
        """
        Get aggregated results for job stages.

        Args:
            job_id: Job identifier
            stage_number: Specific stage or None for all stages

        Returns:
            Dictionary of stage results keyed by stage number
        """
        try:

            # Get job record
            job_record = self.repos['job_repo'].get_job(job_id)
            if not job_record:
                return {}

            # PostgreSQL stores stage_results with string keys
            # Convert back to integer keys for internal use
            stage_results = {}
            if job_record.stage_results:
                for key, value in job_record.stage_results.items():
                    try:
                        stage_num = int(key)
                        if stage_number is None or stage_num == stage_number:
                            stage_results[stage_num] = value
                    except (ValueError, TypeError):
                        self.logger.warning(f"Invalid stage key: {key}")

            return stage_results

        except Exception as e:
            self.logger.error(f"Failed to get stage results: {e}")
            return {}

    def store_stage_results(
        self,
        job_id: str,
        stage_number: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Store aggregated results for a completed stage.

        Args:
            job_id: Job identifier
            stage_number: Stage number
            stage_results: Aggregated stage results

        Returns:
            True if storage successful
        """
        try:

            # Update stage results in job record
            # Note: PostgreSQL will store with string key
            success = self.repos['job_repo'].update_stage_results(job_id, stage_number, stage_results)

            if success:
                self.logger.info(f"Stored results for stage {stage_number} of job {job_id[:16]}...")

            return success

        except Exception as e:
            self.logger.error(f"Failed to store stage results: {e}")
            return False

    # ========================================================================
    # MONITORING & STATUS QUERIES
    # ========================================================================

    def get_completed_stages(self, job_id: str) -> List[int]:
        """
        Get list of completed stages for a job.

        Args:
            job_id: Job identifier

        Returns:
            List of completed stage numbers
        """
        try:

            # Query completed stages
            completed = self.repos['task_repo'].get_completed_stages(job_id)
            return sorted(completed)

        except Exception as e:
            self.logger.error(f"Failed to get completed stages: {e}")
            return []

    def get_stage_status(self, job_id: str) -> Dict[int, str]:
        """
        Get status of all stages for a job.

        Args:
            job_id: Job identifier

        Returns:
            Dictionary mapping stage number to status
        """
        try:

            # Query stage statuses
            return self.repos['task_repo'].get_stage_statuses(job_id)

        except Exception as e:
            self.logger.error(f"Failed to get stage statuses: {e}")
            return {}

    # ========================================================================
    # ERROR HANDLING
    # ========================================================================

    def mark_job_failed(
        self,
        job_id: str,
        error_msg: str
    ) -> bool:
        """
        Mark job as failed with error details.

        Safe method that won't raise exceptions.

        Args:
            job_id: Job identifier
            error_msg: Error message

        Returns:
            True if marked successfully
        """
        try:

            self.repos['job_repo'].fail_job(job_id, error_msg)
            self.logger.info(f"Job {job_id[:16]}... marked as FAILED")
            return True

        except Exception as e:
            self.logger.error(f"Failed to mark job as failed: {e}")
            return False

    def mark_task_failed(
        self,
        task_id: str,
        error_msg: str
    ) -> bool:
        """
        Mark task as failed with error details.

        Safe method that won't raise exceptions.

        Args:
            task_id: Task identifier
            error_msg: Error message

        Returns:
            True if marked successfully
        """
        try:

            self.repos['task_repo'].mark_task_failed(task_id, error_msg)
            self.logger.info(f"Task {task_id} marked as FAILED")
            return True

        except Exception as e:
            self.logger.error(f"Failed to mark task as failed: {e}")
            return False