# ============================================================================
# STATE MANAGER - DATABASE STATE MANAGEMENT
# ============================================================================
# STATUS: Core - Job/Task state transitions with advisory locks
# PURPOSE: Atomic state management for "last task turns out the lights" pattern
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
State Manager - Database State Management with Advisory Locks.

Manages all database state operations including the critical "last task turns
out the lights" pattern using PostgreSQL advisory locks.

Key Responsibilities:
    - Job state transitions (QUEUED → PROCESSING → COMPLETED/FAILED)
    - Task state transitions with atomic completion checks
    - Stage advancement with advisory locks
    - Job completion and result aggregation
    - Database record creation and updates

Critical Method:
    complete_task_with_sql(): Atomic task completion using PostgreSQL function
    - Prevents race conditions via advisory locks
    - Detects when last task completes stage
    - Handles idempotent duplicate message delivery

Exports:
    StateManager: Handles job/task state transitions and completion logic
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

        Infrastructure errors propagate as exceptions so they can be properly
        recorded in job error_details.

        Args:
            job_id: Job identifier
            new_status: New job status
            error_details: Error message if status is FAILED

        Returns:
            True if update successful

        Raises:
            psycopg.Error: Database connection/query errors
            RuntimeError: Infrastructure failures
        """
        # Let infrastructure errors propagate - don't swallow them!
        if new_status == JobStatus.FAILED and error_details:
            self.repos['job_repo'].mark_job_failed(job_id, error_details)
        else:
            self.repos['job_repo'].update_job_status_with_validation(job_id, new_status)

        self.logger.info(f"Job {job_id[:16]}... status updated to {new_status}")
        return True

    def update_job_stage(self, job_id: str, new_stage: int) -> bool:
        """
        Update job stage field in database.

        This ensures the job record's stage field stays synchronized with
        the actual processing stage when advancing through the workflow.
        Infrastructure errors propagate as exceptions.

        Args:
            job_id: Job identifier
            new_stage: New stage number

        Returns:
            True if update successful

        Raises:
            psycopg.Error: Database connection/query errors
            RuntimeError: Infrastructure failures

        Added: 14 NOV 2025 - Fix job stage advancement bug
        """
        # Let infrastructure errors propagate - don't swallow them!
        from core.schema import JobUpdateModel
        update = JobUpdateModel(stage=new_stage)

        success = self.repos['job_repo'].update_job(job_id, update)

        if success:
            self.logger.debug(f"✅ Job {job_id[:16]} stage updated to {new_stage}")
        else:
            self.logger.warning(
                f"⚠️ Job {job_id[:16]} stage update returned False - "
                f"repository update_job() affected 0 rows"
            )

        return success

    def update_job_with_model(
        self,
        job_id: str,
        update: JobUpdateModel
    ) -> bool:
        """
        Update job using type-safe Pydantic model.

        This method directly uses the Pydantic update model for type safety.
        Infrastructure errors (connection failures, etc.) propagate as exceptions
        so they can be properly recorded in job error_details.

        Args:
            job_id: Job identifier
            update: JobUpdateModel with fields to update

        Returns:
            True if update successful, False if no rows affected (job not found)

        Raises:
            psycopg.Error: Database connection/query errors
            RuntimeError: Infrastructure failures
        """
        # Let infrastructure errors propagate - don't swallow them!
        # This ensures PostgreSQL connection errors (like "remaining connection
        # slots are reserved") appear in job error_details instead of being
        # hidden as "Failed to update" generic messages.
        success = self.repos['job_repo'].update_job(job_id, update)
        if success:
            self.logger.info(f"Job {job_id[:16]}... updated with model")
        else:
            self.logger.warning(
                f"⚠️ Job {job_id[:16]} update returned False - "
                f"repository update_job() affected 0 rows"
            )
        return success

    def update_task_with_model(
        self,
        task_id: str,
        update: TaskUpdateModel
    ) -> bool:
        """
        Update task using type-safe Pydantic model.

        This method directly uses the Pydantic update model for type safety.
        Infrastructure errors (connection failures, etc.) propagate as exceptions
        so they can be properly recorded in job error_details.

        Args:
            task_id: Task identifier
            update: TaskUpdateModel with fields to update

        Returns:
            True if update successful, False if no rows affected (task not found)

        Raises:
            psycopg.Error: Database connection/query errors
            RuntimeError: Infrastructure failures
        """
        # Let infrastructure errors propagate - don't swallow them!
        # This ensures PostgreSQL connection errors (like "remaining connection
        # slots are reserved") appear in job error_details instead of being
        # hidden as "Failed to update task status to PROCESSING" generic messages.
        success = self.repos['task_repo'].update_task(task_id, update)
        if success:
            self.logger.info(f"Task {task_id} updated with model")
        else:
            self.logger.warning(
                f"⚠️ Task {task_id[:16]} update returned False - "
                f"repository update_task() affected 0 rows"
            )
        return success

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
        return self.repos['task_repo'].increment_task_retry_count(task_id)

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
            self.logger.error(
                f"Failed to complete job: {e}",
                extra={
                    'checkpoint': 'STATE_JOB_COMPLETE_FAILED',
                    'error_source': 'state',  # 29 NOV 2025: For Application Insights filtering
                    'job_id': job_id,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }
            )
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
            self.logger.error(
                f"Stage completion handling failed: {e}",
                extra={
                    'checkpoint': 'STATE_STAGE_COMPLETE_FAILED',
                    'error_source': 'state',  # 29 NOV 2025: For Application Insights filtering
                    'job_id': job_id,
                    'stage': stage,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }
            )
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

            # Verify task exists and check status
            task = self.repos['task_repo'].get_task(task_id)
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            # Handle idempotent completion - already completed is OK (duplicate message delivery)
            # This handles the race condition where Azure Service Bus message lock expires
            # during long-running tasks (>5 min), causing duplicate message delivery.
            if task.status == TaskStatus.COMPLETED:
                self.logger.info(
                    f"Task {task_id} already completed (idempotent - duplicate message delivery). "
                    f"Returning existing completion status.",
                    extra={
                        'checkpoint': 'STATE_TASK_ALREADY_COMPLETED',
                        'task_id': task_id,
                        'job_id': job_id,
                        'stage': stage
                    }
                )
                # Return a "no-op" result - task was already done
                from core.models.results import TaskCompletionResult
                return TaskCompletionResult(
                    task_updated=False,  # We didn't update it
                    stage_complete=False,  # Don't trigger stage advancement again
                    job_id=job_id,
                    stage_number=stage,
                    remaining_tasks=0  # Already counted in original completion
                )

            if task.status == TaskStatus.FAILED:
                self.logger.info(
                    f"Task {task_id} already marked as failed (idempotent - duplicate message delivery). "
                    f"Returning existing failure status.",
                    extra={
                        'checkpoint': 'STATE_TASK_ALREADY_FAILED',
                        'task_id': task_id,
                        'job_id': job_id,
                        'stage': stage
                    }
                )
                from core.models.results import TaskCompletionResult
                return TaskCompletionResult(
                    task_updated=False,
                    stage_complete=False,
                    job_id=job_id,
                    stage_number=stage,
                    remaining_tasks=0
                )

            if task.status != TaskStatus.PROCESSING:
                # Only raise for truly unexpected states (PENDING, QUEUED, etc.)
                raise RuntimeError(
                    f"Task {task_id} has unexpected status: {task.status} "
                    f"(expected: PROCESSING, COMPLETED, or FAILED)"
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
                # Preserve result_data for failed tasks (contains traceback for debugging)
                stage_completion = stage_completion_repo.complete_task_and_check_stage(
                    task_id=task_id,
                    job_id=job_id,
                    stage=stage,
                    result_data=task_result.result_data if task_result else {},
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
            self.logger.error(
                f"Task completion SQL failed: {e}",
                extra={
                    'checkpoint': 'STATE_TASK_COMPLETE_SQL_FAILED',
                    'error_source': 'state',  # 29 NOV 2025: For Application Insights filtering
                    'task_id': task_id,
                    'job_id': job_id,
                    'stage': stage,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }
            )
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
        error_msg: str,
        result_data: dict = None
    ) -> None:
        """
        Mark job as failed with error details.

        25 FEB 2026: No longer swallows exceptions. If the job can't be marked
        failed, callers MUST know — silent failure creates orphaned jobs.

        Args:
            job_id: Job identifier
            error_msg: Error message
            result_data: Optional structured error response from handler

        Raises:
            Exception: If database update fails (propagated to caller)
        """
        self.repos['job_repo'].fail_job(job_id, error_msg, result_data=result_data)
        self.logger.info(
            f"Job {job_id[:16]}... marked as FAILED",
            extra={
                'checkpoint': 'JOB_MARKED_FAILED',
                'error_source': 'state',
                'job_id': job_id
            }
        )

    def mark_task_failed(
        self,
        task_id: str,
        error_msg: str
    ) -> None:
        """
        Mark task as failed with error details.

        25 FEB 2026: No longer swallows exceptions. If the task can't be marked
        failed, callers MUST know — silent failure creates orphaned tasks.

        Args:
            task_id: Task identifier
            error_msg: Error message

        Raises:
            Exception: If database update fails (propagated to caller)
        """
        self.repos['task_repo'].fail_task(task_id, error_msg)
        self.logger.info(
            f"Task {task_id} marked as FAILED",
            extra={
                'checkpoint': 'TASK_MARKED_FAILED',
                'error_source': 'state',
                'task_id': task_id
            }
        )

    def fail_all_job_tasks(
        self,
        job_id: str,
        error_msg: str
    ) -> int:
        """
        Mark all non-terminal tasks for a job as FAILED.

        GAP-004 FIX (15 DEC 2025): When a job is marked failed (e.g., due to stage
        advancement failure), sibling tasks in PROCESSING or QUEUED state should
        also be failed to prevent orphan tasks and wasted compute.

        Safe method that won't raise exceptions.

        Args:
            job_id: Job identifier
            error_msg: Error message to set on all failed tasks

        Returns:
            Number of tasks marked as failed
        """
        try:
            from psycopg import sql

            with self.repos['task_repo']._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("""
                            UPDATE {schema}.tasks
                            SET status = 'failed',
                                error_details = %s,
                                updated_at = NOW()
                            WHERE parent_job_id = %s
                              AND status NOT IN ('completed', 'failed')
                            RETURNING task_id, status
                        """).format(schema=sql.Identifier("app")),
                        (error_msg, job_id)
                    )
                    failed_tasks = cur.fetchall()
                    conn.commit()

                    failed_count = len(failed_tasks)
                    if failed_count > 0:
                        self.logger.warning(
                            f"GAP-004: Marked {failed_count} orphan tasks as FAILED for job {job_id[:16]}...",
                            extra={
                                'checkpoint': 'STATE_ORPHAN_TASKS_FAILED',
                                'job_id': job_id,
                                'failed_count': failed_count,
                                'task_ids': [t['task_id'] for t in failed_tasks[:10]]  # Log first 10
                            }
                        )
                    return failed_count

        except Exception as e:
            self.logger.error(
                f"Failed to fail orphan tasks for job {job_id[:16]}...: {e}",
                extra={
                    'checkpoint': 'STATE_FAIL_ORPHAN_TASKS_ERROR',
                    'error_source': 'state',
                    'job_id': job_id,
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                }
            )
            return 0