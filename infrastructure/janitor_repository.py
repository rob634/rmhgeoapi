"""
Janitor Repository - Maintenance Database Queries.

Provides database queries for the janitor maintenance system:
    - Detect stale tasks (PROCESSING beyond timeout)
    - Detect jobs with failed tasks
    - Detect orphaned tasks and zombie jobs
    - Batch update operations for marking failures
    - Audit logging to janitor_runs table

This is a standalone repository that operates via timer triggers
with direct database access, independent of CoreMachine orchestration.

Exports:
    JanitorRepository: Maintenance query repository
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
import logging

from psycopg import sql

from .postgresql import PostgreSQLRepository
from core.models import JobRecord, TaskRecord, JobStatus, TaskStatus
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "JanitorRepository")


class JanitorRepository(PostgreSQLRepository):
    """
    Repository for janitor maintenance operations.

    Provides efficient queries for detecting:
    - Stale tasks (stuck in PROCESSING)
    - Jobs with failed tasks
    - Orphaned tasks and zombie jobs
    - Ancient stale jobs
    """

    def __init__(self):
        """Initialize janitor repository."""
        super().__init__()
        self.schema_name = "app"
        logger.info("JanitorRepository initialized")

    # ========================================================================
    # STALE TASK DETECTION (Task Watchdog)
    # ========================================================================

    def get_orphaned_queued_tasks(
        self,
        timeout_minutes: int = 10,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find tasks stuck in QUEUED state beyond timeout (orphaned queue messages).

        These are tasks where:
        - Status is QUEUED (task created, message sent to Service Bus)
        - Created more than timeout_minutes ago
        - Message was likely lost (SDK reported success but never arrived)

        This is part of the retry logic for distributed system resilience.
        The janitor will re-queue these tasks with incremented retry_count.

        Added: 14 DEC 2025 - Defense in depth for message loss

        Args:
            timeout_minutes: Minutes after which QUEUED tasks are considered orphaned
            limit: Maximum number of tasks to return

        Returns:
            List of orphaned task dicts with full task details for re-queuing
        """
        query = sql.SQL("""
            SELECT
                t.task_id,
                t.parent_job_id,
                t.job_type,
                t.task_type,
                t.stage,
                t.task_index,
                t.status,
                t.parameters,
                t.retry_count,
                t.created_at,
                t.updated_at,
                EXTRACT(EPOCH FROM (NOW() - t.created_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'queued'
              AND t.created_at < NOW() - make_interval(mins => %s)
            ORDER BY t.created_at ASC
            LIMIT %s
        """).format(schema=sql.Identifier(self.schema_name))

        logger.debug(
            f"[JANITOR] get_orphaned_queued_tasks: Executing query with timeout={timeout_minutes} minutes"
        )
        with self._error_context("get orphaned queued tasks"):
            result = self._execute_query(query, (timeout_minutes, limit), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[JANITOR] Found {count} orphaned QUEUED tasks (>{timeout_minutes}min)")
            return result or []

    def get_stale_processing_tasks(
        self,
        timeout_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Find tasks stuck in PROCESSING state beyond timeout.

        Azure Functions have a max execution time of 10-30 minutes depending
        on the plan. Tasks in PROCESSING for longer have silently failed.

        Args:
            timeout_minutes: Minutes after which PROCESSING tasks are considered stale

        Returns:
            List of stale task dicts with task_id, parent_job_id, job_type, etc.
        """
        query = sql.SQL("""
            SELECT
                t.task_id,
                t.parent_job_id,
                t.job_type,
                t.task_type,
                t.stage,
                t.status,
                t.updated_at,
                t.created_at,
                t.retry_count,
                EXTRACT(EPOCH FROM (NOW() - t.updated_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'processing'
              AND t.updated_at < NOW() - make_interval(mins => %s)
            ORDER BY t.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        logger.debug(
            f"[JANITOR] get_stale_processing_tasks: Executing query with timeout={timeout_minutes} minutes"
        )
        with self._error_context("get stale processing tasks"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            logger.debug(f"[JANITOR] get_stale_processing_tasks: Query returned {count} rows")
            logger.info(f"[JANITOR] Found {count} stale PROCESSING tasks (>{timeout_minutes}min)")
            return result or []

    def mark_tasks_as_failed(
        self,
        task_ids: List[str],
        error_message: str
    ) -> int:
        """
        Batch mark multiple tasks as FAILED.

        Args:
            task_ids: List of task IDs to mark as failed
            error_message: Error message to store

        Returns:
            Number of tasks updated
        """
        if not task_ids:
            logger.debug("[JANITOR] mark_tasks_as_failed: No task_ids provided, returning 0")
            return 0

        logger.debug(f"[JANITOR] mark_tasks_as_failed: Preparing batch UPDATE for {len(task_ids)} tasks")

        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET
                status = 'failed',
                error_details = %s,
                updated_at = NOW()
            WHERE task_id = ANY(%s)
            RETURNING task_id
        """).format(schema=sql.Identifier(self.schema_name))

        logger.debug(f"[JANITOR] mark_tasks_as_failed: Executing UPDATE with task_ids={task_ids[:5]}{'...' if len(task_ids) > 5 else ''}")
        with self._error_context("mark tasks as failed"):
            result = self._execute_query(query, (error_message, task_ids), fetch='all')
            count = len(result) if result else 0
            logger.debug(f"[JANITOR] mark_tasks_as_failed: UPDATE affected {count} rows")
            logger.info(f"[JANITOR] Marked {count} tasks as FAILED: {error_message[:80]}...")
            return count

    # ========================================================================
    # JOB HEALTH MONITORING (Job Health Monitor)
    # ========================================================================

    def get_processing_jobs_with_failed_tasks(self) -> List[Dict[str, Any]]:
        """
        Find PROCESSING jobs that have failed tasks.

        Returns jobs where:
        - Job status is PROCESSING
        - At least one task has FAILED status

        Returns:
            List of job dicts with failure statistics
        """
        query = sql.SQL("""
            SELECT
                j.job_id,
                j.job_type,
                j.stage,
                j.total_stages,
                j.status,
                j.parameters,
                j.stage_results,
                j.created_at,
                j.updated_at,
                COUNT(t.*) FILTER (WHERE t.status = 'failed') AS failed_count,
                COUNT(t.*) FILTER (WHERE t.status = 'completed') AS completed_count,
                COUNT(t.*) FILTER (WHERE t.status = 'processing') AS processing_count,
                COUNT(t.*) FILTER (WHERE t.status = 'queued') AS queued_count,
                COUNT(t.*) AS total_tasks,
                ARRAY_AGG(t.task_id) FILTER (WHERE t.status = 'failed') AS failed_task_ids,
                ARRAY_AGG(t.error_details) FILTER (WHERE t.status = 'failed') AS failed_task_errors
            FROM {schema}.jobs j
            JOIN {schema}.tasks t ON t.parent_job_id = j.job_id
            WHERE j.status = 'processing'
            GROUP BY j.job_id
            HAVING COUNT(t.*) FILTER (WHERE t.status = 'failed') > 0
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get processing jobs with failed tasks"):
            result = self._execute_query(query, fetch='all')
            logger.info(f"Found {len(result) if result else 0} PROCESSING jobs with failed tasks")
            return result or []

    def get_completed_task_results_for_job(
        self,
        job_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get results from completed tasks for a job (for partial result capture).

        Args:
            job_id: Job ID to fetch completed task results for

        Returns:
            List of task results (task_id, stage, result_data)
        """
        query = sql.SQL("""
            SELECT
                task_id,
                task_type,
                stage,
                result_data,
                updated_at
            FROM {schema}.tasks
            WHERE parent_job_id = %s
              AND status = 'completed'
            ORDER BY stage, task_id
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get completed task results"):
            result = self._execute_query(query, (job_id,), fetch='all')
            return result or []

    def mark_job_as_failed(
        self,
        job_id: str,
        error_details: str,
        partial_results: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Mark a job as FAILED with error details and optional partial results.

        Args:
            job_id: Job ID to mark as failed
            error_details: Error message
            partial_results: Optional dict with partial results from completed tasks

        Returns:
            True if job was updated
        """
        import json

        if partial_results:
            query = sql.SQL("""
                UPDATE {schema}.jobs
                SET
                    status = 'failed',
                    error_details = %s,
                    result_data = %s::jsonb,
                    updated_at = NOW()
                WHERE job_id = %s
                RETURNING job_id
            """).format(schema=sql.Identifier(self.schema_name))
            params = (error_details, json.dumps(partial_results), job_id)
        else:
            query = sql.SQL("""
                UPDATE {schema}.jobs
                SET
                    status = 'failed',
                    error_details = %s,
                    updated_at = NOW()
                WHERE job_id = %s
                RETURNING job_id
            """).format(schema=sql.Identifier(self.schema_name))
            params = (error_details, job_id)

        with self._error_context("mark job as failed"):
            result = self._execute_query(query, params, fetch='one')
            success = result is not None
            if success:
                logger.info(f"Marked job {job_id[:16]}... as FAILED")
            return success

    # ========================================================================
    # ORPHAN DETECTION (Orphan Detector)
    # ========================================================================

    def get_orphaned_tasks(self) -> List[Dict[str, Any]]:
        """
        Find tasks whose parent job doesn't exist.

        This can happen if a job record is deleted but tasks remain,
        or due to a database consistency issue.

        Returns:
            List of orphaned task dicts
        """
        query = sql.SQL("""
            SELECT
                t.task_id,
                t.parent_job_id,
                t.task_type,
                t.status,
                t.created_at,
                t.updated_at
            FROM {schema}.tasks t
            LEFT JOIN {schema}.jobs j ON t.parent_job_id = j.job_id
            WHERE j.job_id IS NULL
            ORDER BY t.created_at DESC
            LIMIT 100
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get orphaned tasks"):
            result = self._execute_query(query, fetch='all')
            logger.info(f"Found {len(result) if result else 0} orphaned tasks")
            return result or []

    def get_zombie_jobs(self) -> List[Dict[str, Any]]:
        """
        Find zombie jobs: PROCESSING status but all tasks are in terminal state.

        This indicates a failure in the "last task turns out lights" logic
        or a stage advancement failure.

        Returns:
            List of zombie job dicts
        """
        query = sql.SQL("""
            SELECT
                j.job_id,
                j.job_type,
                j.stage,
                j.total_stages,
                j.status,
                j.created_at,
                j.updated_at,
                COUNT(t.*) AS total_tasks,
                COUNT(t.*) FILTER (WHERE t.status = 'completed') AS completed_tasks,
                COUNT(t.*) FILTER (WHERE t.status = 'failed') AS failed_tasks
            FROM {schema}.jobs j
            LEFT JOIN {schema}.tasks t ON t.parent_job_id = j.job_id
            WHERE j.status = 'processing'
            GROUP BY j.job_id
            HAVING NOT EXISTS (
                SELECT 1 FROM {schema}.tasks t2
                WHERE t2.parent_job_id = j.job_id
                  AND t2.status IN ('queued', 'processing')
            )
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get zombie jobs"):
            result = self._execute_query(query, fetch='all')
            logger.info(f"Found {len(result) if result else 0} zombie jobs")
            return result or []

    def get_stuck_queued_jobs(
        self,
        timeout_hours: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Find jobs stuck in QUEUED state without any tasks created.

        This indicates a failure in job processing before task creation.

        Args:
            timeout_hours: Hours after which QUEUED jobs are considered stuck

        Returns:
            List of stuck job dicts
        """
        query = sql.SQL("""
            SELECT
                j.job_id,
                j.job_type,
                j.stage,
                j.status,
                j.created_at,
                j.updated_at,
                EXTRACT(EPOCH FROM (NOW() - j.created_at)) / 3600 AS hours_stuck
            FROM {schema}.jobs j
            WHERE j.status = 'queued'
              AND j.created_at < NOW() - INTERVAL %s
              AND NOT EXISTS (
                  SELECT 1 FROM {schema}.tasks t
                  WHERE t.parent_job_id = j.job_id
              )
            ORDER BY j.created_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        interval_str = f'{timeout_hours} hours'

        with self._error_context("get stuck queued jobs"):
            result = self._execute_query(query, (interval_str,), fetch='all')
            logger.info(f"Found {len(result) if result else 0} stuck QUEUED jobs (>{timeout_hours}h)")
            return result or []

    def get_ancient_stale_jobs(
        self,
        timeout_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Find jobs stuck in PROCESSING for an unreasonably long time.

        Jobs should complete within hours, not days. Jobs older than 24h
        in PROCESSING are almost certainly failed.

        Args:
            timeout_hours: Hours after which PROCESSING jobs are considered ancient

        Returns:
            List of ancient stale job dicts
        """
        query = sql.SQL("""
            SELECT
                j.job_id,
                j.job_type,
                j.stage,
                j.total_stages,
                j.status,
                j.created_at,
                j.updated_at,
                EXTRACT(EPOCH FROM (NOW() - j.updated_at)) / 3600 AS hours_stuck,
                (SELECT COUNT(*) FROM {schema}.tasks t WHERE t.parent_job_id = j.job_id) AS task_count
            FROM {schema}.jobs j
            WHERE j.status = 'processing'
              AND j.updated_at < NOW() - INTERVAL %s
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        interval_str = f'{timeout_hours} hours'

        with self._error_context("get ancient stale jobs"):
            result = self._execute_query(query, (interval_str,), fetch='all')
            logger.info(f"Found {len(result) if result else 0} ancient stale jobs (>{timeout_hours}h)")
            return result or []

    # ========================================================================
    # AUDIT LOGGING
    # ========================================================================

    def log_janitor_run(
        self,
        run_type: str,
        started_at: datetime,
        completed_at: datetime,
        items_scanned: int,
        items_fixed: int,
        actions_taken: List[Dict[str, Any]],
        status: str = "completed",
        error_details: Optional[str] = None
    ) -> Optional[str]:
        """
        Log a janitor run to the audit table.

        Args:
            run_type: Type of janitor run ('task_watchdog', 'job_health', 'orphan_detector')
            started_at: When the run started
            completed_at: When the run completed
            items_scanned: Number of items scanned
            items_fixed: Number of items fixed
            actions_taken: List of actions taken
            status: Run status ('completed', 'failed')
            error_details: Error message if failed

        Returns:
            Run ID if created, None if failed
        """
        import json

        # Calculate duration only if both timestamps are available
        # At start of run, completed_at will be None
        if completed_at and started_at:
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        else:
            duration_ms = None

        query = sql.SQL("""
            INSERT INTO {schema}.janitor_runs (
                run_type,
                started_at,
                completed_at,
                status,
                items_scanned,
                items_fixed,
                actions_taken,
                error_details,
                duration_ms
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("log janitor run"):
                result = self._execute_query(
                    query,
                    (
                        run_type,
                        started_at,
                        completed_at,
                        status,
                        items_scanned,
                        items_fixed,
                        json.dumps(actions_taken),
                        error_details,
                        duration_ms
                    ),
                    fetch='one'
                )

                if result:
                    run_id = str(result['run_id'])
                    logger.info(
                        f"Logged janitor run: type={run_type}, scanned={items_scanned}, "
                        f"fixed={items_fixed}, duration={duration_ms}ms"
                    )
                    return run_id
                return None

        except Exception as e:
            # Don't fail the janitor if audit logging fails
            logger.warning(f"Failed to log janitor run (non-fatal): {e}")
            return None

    def update_janitor_run(
        self,
        run_id: str,
        completed_at: datetime,
        items_scanned: int,
        items_fixed: int,
        actions_taken: List[Dict[str, Any]],
        status: str,
        error_details: Optional[str]
    ) -> bool:
        """
        Update an existing janitor run with final results.

        Args:
            run_id: UUID of the run to update
            completed_at: When the run completed
            items_scanned: Total items scanned
            items_fixed: Total items fixed
            actions_taken: List of actions taken
            status: Final status ('completed', 'failed')
            error_details: Error message if failed

        Returns:
            True if updated successfully, False otherwise
        """
        import json

        # Calculate duration if we have both start and completion times
        query = sql.SQL("""
            UPDATE {schema}.janitor_runs
            SET
                completed_at = %s,
                items_scanned = %s,
                items_fixed = %s,
                actions_taken = %s::jsonb,
                status = %s,
                error_details = %s,
                duration_ms = EXTRACT(EPOCH FROM (%s - started_at)) * 1000
            WHERE run_id = %s
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("update janitor run"):
                result = self._execute_query(
                    query,
                    (
                        completed_at,
                        items_scanned,
                        items_fixed,
                        json.dumps(actions_taken),
                        status,
                        error_details,
                        completed_at,  # For duration calculation
                        run_id
                    ),
                    fetch='one'
                )

                if result:
                    logger.info(
                        f"Updated janitor run: run_id={run_id}, status={status}, "
                        f"scanned={items_scanned}, fixed={items_fixed}"
                    )
                    return True
                else:
                    logger.warning(f"No janitor run found with run_id={run_id}")
                    return False

        except Exception as e:
            # Don't fail the janitor if audit logging fails
            logger.warning(f"Failed to update janitor run (non-fatal): {e}")
            return False

    def get_recent_janitor_runs(
        self,
        hours: int = 24,
        run_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent janitor runs for monitoring.

        Args:
            hours: How many hours of history to fetch
            run_type: Optional filter by run type
            limit: Maximum number of runs to return

        Returns:
            List of janitor run dicts
        """
        if run_type:
            query = sql.SQL("""
                SELECT *
                FROM {schema}.janitor_runs
                WHERE started_at > NOW() - INTERVAL %s
                  AND run_type = %s
                ORDER BY started_at DESC
                LIMIT %s
            """).format(schema=sql.Identifier(self.schema_name))
            params = (f'{hours} hours', run_type, limit)
        else:
            query = sql.SQL("""
                SELECT *
                FROM {schema}.janitor_runs
                WHERE started_at > NOW() - INTERVAL %s
                ORDER BY started_at DESC
                LIMIT %s
            """).format(schema=sql.Identifier(self.schema_name))
            params = (f'{hours} hours', limit)

        try:
            with self._error_context("get recent janitor runs"):
                result = self._execute_query(query, params, fetch='all')
                return result or []
        except Exception as e:
            # Table might not exist yet
            logger.warning(f"Could not get janitor runs: {e}")
            return []


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = ['JanitorRepository']
