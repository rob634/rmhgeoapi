# ============================================================================
# GUARDIAN REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - SystemGuardian DB operations
# PURPOSE: Detection queries and fix operations for distributed systems recovery
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: GuardianRepository
# DEPENDENCIES: postgresql, psycopg
# ============================================================================
"""
Guardian Repository - Phase-organized database queries for SystemGuardian.

Replaces scattered JanitorRepository queries with a single repository
organized by recovery phase:

    Phase 1: Task Recovery (orphaned pending/queued, stale processing)
    Phase 2: Stage Recovery (zombie stages)
    Phase 3: Job Recovery (failed tasks, stuck queued, ancient stale)
    Phase 4: Consistency (orphaned tasks)

Also provides fix operations and two-phase audit logging.

Exports:
    GuardianRepository: All SystemGuardian DB operations
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from psycopg import sql

from .postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)


class GuardianRepository(PostgreSQLRepository):
    """
    Repository for SystemGuardian sweep operations.

    Provides phase-organized detection queries, fix operations,
    and two-phase audit logging for the guardian_sweeps table.
    """

    def __init__(self):
        """Initialize guardian repository."""
        super().__init__()
        self.schema_name = "app"
        logger.info("[GUARDIAN] GuardianRepository initialized")

    # ====================================================================
    # SCHEMA READINESS
    # ====================================================================

    def schema_ready(self) -> bool:
        """
        Check if the app schema has the jobs table.

        Used by SystemGuardian to skip sweeps before schema deployment.

        Returns:
            True if app.jobs table exists, False otherwise.
        """
        query = sql.SQL("""
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_name = 'jobs'
            LIMIT 1
        """)
        try:
            with self._error_context("schema readiness check"):
                result = self._execute_query(query, (self.schema_name,), fetch='one')
                ready = result is not None
                logger.debug(f"[GUARDIAN] Schema ready: {ready}")
                return ready
        except Exception as e:
            logger.warning(f"[GUARDIAN] Schema readiness check failed: {e}")
            return False

    # ====================================================================
    # PHASE 1: TASK RECOVERY
    # ====================================================================

    def get_orphaned_pending_tasks(
        self,
        timeout_minutes: int = 2,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find tasks stuck in PENDING state beyond timeout.

        PENDING tasks should transition to QUEUED within seconds.
        If stuck, the Service Bus message was likely lost.

        Args:
            timeout_minutes: Minutes after which PENDING is considered orphaned.
            limit: Maximum tasks to return.

        Returns:
            List of orphaned task dicts.
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
            WHERE t.status = 'pending'
              AND t.created_at < NOW() - make_interval(mins => %s)
            ORDER BY t.created_at ASC
            LIMIT %s
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get orphaned pending tasks"):
            result = self._execute_query(query, (timeout_minutes, limit), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} orphaned PENDING tasks (>{timeout_minutes}min)")
            return result or []

    def get_orphaned_queued_tasks(
        self,
        timeout_minutes: int = 10,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Find tasks stuck in QUEUED state beyond timeout.

        QUEUED tasks should be picked up by a trigger within minutes.
        If stuck, the queue message was lost or the trigger is down.

        Args:
            timeout_minutes: Minutes after which QUEUED is considered orphaned.
            limit: Maximum tasks to return.

        Returns:
            List of orphaned task dicts.
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

        with self._error_context("get orphaned queued tasks"):
            result = self._execute_query(query, (timeout_minutes, limit), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} orphaned QUEUED tasks (>{timeout_minutes}min)")
            return result or []

    def get_stale_processing_tasks(
        self,
        timeout_minutes: int = 30,
        exclude_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Find Function App tasks stuck in PROCESSING beyond timeout.

        Azure Functions have a max execution time of 10-30 minutes.
        Tasks beyond this threshold have silently failed.

        Args:
            timeout_minutes: Minutes after which PROCESSING is stale.
            exclude_types: Task types to exclude (e.g., Docker tasks).

        Returns:
            List of stale task dicts.
        """
        if exclude_types:
            exclusion_clause = sql.SQL(" AND NOT (t.task_type = ANY(%s))")
            query = sql.SQL("""
                SELECT
                    t.task_id,
                    t.parent_job_id,
                    t.job_type,
                    t.task_type,
                    t.stage,
                    t.task_index,
                    t.status,
                    t.last_pulse,
                    t.parameters,
                    t.updated_at,
                    t.created_at,
                    t.retry_count,
                    EXTRACT(EPOCH FROM (NOW() - t.updated_at)) / 60 AS minutes_stuck
                FROM {schema}.tasks t
                WHERE t.status = 'processing'
                  AND t.updated_at < NOW() - make_interval(mins => %s)
            """).format(schema=sql.Identifier(self.schema_name)) + exclusion_clause + sql.SQL("""
                ORDER BY t.updated_at ASC
            """)
            params = (timeout_minutes, exclude_types)
        else:
            query = sql.SQL("""
                SELECT
                    t.task_id,
                    t.parent_job_id,
                    t.job_type,
                    t.task_type,
                    t.stage,
                    t.task_index,
                    t.status,
                    t.last_pulse,
                    t.parameters,
                    t.updated_at,
                    t.created_at,
                    t.retry_count,
                    EXTRACT(EPOCH FROM (NOW() - t.updated_at)) / 60 AS minutes_stuck
                FROM {schema}.tasks t
                WHERE t.status = 'processing'
                  AND t.updated_at < NOW() - make_interval(mins => %s)
                ORDER BY t.updated_at ASC
            """).format(schema=sql.Identifier(self.schema_name))
            params = (timeout_minutes,)

        excluded_info = f", excluding {len(exclude_types)} types" if exclude_types else ""
        with self._error_context("get stale processing tasks"):
            result = self._execute_query(query, params, fetch='all')
            count = len(result) if result else 0
            logger.info(
                f"[GUARDIAN] Found {count} stale FA PROCESSING tasks "
                f"(>{timeout_minutes}min){excluded_info}"
            )
            return result or []

    def get_stale_docker_tasks(
        self,
        timeout_minutes: int = 1440,
        docker_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Find Docker tasks stuck in PROCESSING beyond timeout.

        Docker tasks can legitimately run for hours. Uses a much longer
        timeout than Function App tasks.

        Args:
            timeout_minutes: Minutes after which Docker tasks are stale.
            docker_types: Task types that run on Docker.

        Returns:
            List of stale Docker task dicts.
        """
        if docker_types is None:
            from config.defaults import TaskRoutingDefaults
            docker_types = list(TaskRoutingDefaults.DOCKER_TASKS)

        if not docker_types:
            logger.debug("[GUARDIAN] No Docker task types configured")
            return []

        query = sql.SQL("""
            SELECT
                t.task_id,
                t.parent_job_id,
                t.job_type,
                t.task_type,
                t.stage,
                t.task_index,
                t.status,
                t.last_pulse,
                t.parameters,
                t.updated_at,
                t.created_at,
                t.retry_count,
                EXTRACT(EPOCH FROM (NOW() - t.updated_at)) / 60 AS minutes_stuck
            FROM {schema}.tasks t
            WHERE t.status = 'processing'
              AND t.task_type = ANY(%s)
              AND t.updated_at < NOW() - make_interval(mins => %s)
            ORDER BY t.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get stale docker tasks"):
            result = self._execute_query(query, (docker_types, timeout_minutes), fetch='all')
            count = len(result) if result else 0
            logger.info(
                f"[GUARDIAN] Found {count} stale Docker PROCESSING tasks "
                f"(>{timeout_minutes}min)"
            )
            return result or []

    # ====================================================================
    # PHASE 2: STAGE RECOVERY
    # ====================================================================

    def get_zombie_stages(self) -> List[Dict[str, Any]]:
        """
        Find jobs where all tasks for the current stage are terminal
        but the stage hasn't advanced.

        Uses JOIN (not LEFT JOIN) on t.stage = j.stage to only examine
        tasks belonging to the current stage.

        Returns:
            List of zombie stage dicts with job and task counts.
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
            JOIN {schema}.tasks t
              ON t.parent_job_id = j.job_id
             AND t.stage = j.stage
            WHERE j.status = 'processing'
            GROUP BY j.job_id
            HAVING NOT EXISTS (
                SELECT 1 FROM {schema}.tasks t2
                WHERE t2.parent_job_id = j.job_id
                  AND t2.stage = j.stage
                  AND t2.status IN ('pending', 'queued', 'processing')
            )
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get zombie stages"):
            result = self._execute_query(query, fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} zombie stages")
            return result or []

    # ====================================================================
    # PHASE 3: JOB RECOVERY
    # ====================================================================

    def get_jobs_with_failed_tasks(self) -> List[Dict[str, Any]]:
        """
        Find PROCESSING jobs that have at least one failed task.

        Returns:
            List of job dicts with failure statistics.
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

        with self._error_context("get jobs with failed tasks"):
            result = self._execute_query(query, fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} PROCESSING jobs with failed tasks")
            return result or []

    def get_stuck_queued_jobs(
        self,
        timeout_minutes: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Find QUEUED jobs with no tasks created.

        Indicates a failure during job processing before task creation.

        Args:
            timeout_minutes: Minutes after which QUEUED jobs are stuck.

        Returns:
            List of stuck job dicts.
        """
        query = sql.SQL("""
            SELECT
                j.job_id,
                j.job_type,
                j.stage,
                j.status,
                j.created_at,
                j.updated_at,
                EXTRACT(EPOCH FROM (NOW() - j.created_at)) / 60 AS minutes_stuck
            FROM {schema}.jobs j
            WHERE j.status = 'queued'
              AND j.created_at < NOW() - make_interval(mins => %s)
              AND NOT EXISTS (
                  SELECT 1 FROM {schema}.tasks t
                  WHERE t.parent_job_id = j.job_id
              )
            ORDER BY j.created_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get stuck queued jobs"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} stuck QUEUED jobs (>{timeout_minutes}min)")
            return result or []

    def get_ancient_stale_jobs(
        self,
        timeout_minutes: int = 1440
    ) -> List[Dict[str, Any]]:
        """
        Find PROCESSING jobs past the hard backstop timeout.

        Jobs stuck for this long are almost certainly failed.

        Args:
            timeout_minutes: Minutes after which PROCESSING jobs are ancient.

        Returns:
            List of ancient stale job dicts.
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
                EXTRACT(EPOCH FROM (NOW() - j.updated_at)) / 60 AS minutes_stuck,
                (SELECT COUNT(*) FROM {schema}.tasks t
                 WHERE t.parent_job_id = j.job_id) AS task_count
            FROM {schema}.jobs j
            WHERE j.status = 'processing'
              AND j.updated_at < NOW() - make_interval(mins => %s)
            ORDER BY j.updated_at ASC
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("get ancient stale jobs"):
            result = self._execute_query(query, (timeout_minutes,), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} ancient stale jobs (>{timeout_minutes}min)")
            return result or []

    def get_completed_task_results(
        self,
        job_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get results from completed tasks for partial result capture.

        Args:
            job_id: Job ID to fetch completed task results for.

        Returns:
            List of task result dicts (task_id, stage, result_data).
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

    # ====================================================================
    # PHASE 4: CONSISTENCY
    # ====================================================================

    def get_orphaned_tasks(self) -> List[Dict[str, Any]]:
        """
        Find tasks whose parent job does not exist.

        Uses LEFT JOIN to detect missing parent jobs.

        Returns:
            List of orphaned task dicts (max 100).
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
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Found {count} orphaned tasks")
            return result or []

    # ====================================================================
    # FIX OPERATIONS
    # ====================================================================

    def mark_tasks_failed(
        self,
        task_ids: List[str],
        error: str
    ) -> int:
        """
        Batch mark tasks as FAILED.

        Args:
            task_ids: List of task IDs to mark failed.
            error: Error message to store.

        Returns:
            Number of tasks updated.
        """
        if not task_ids:
            return 0

        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET
                status = 'failed',
                error_details = %s,
                updated_at = NOW()
            WHERE task_id = ANY(%s)
            RETURNING task_id
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("mark tasks failed"):
            result = self._execute_query(query, (error, task_ids), fetch='all')
            count = len(result) if result else 0
            logger.info(f"[GUARDIAN] Marked {count} tasks as FAILED: {error[:80]}")
            return count

    def mark_job_failed(
        self,
        job_id: str,
        error: str,
        partial_results: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Mark a job as FAILED with error and optional partial results.

        Args:
            job_id: Job ID to mark failed.
            error: Error message.
            partial_results: Optional partial results from completed tasks.

        Returns:
            True if job was updated.
        """
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
            params = (error, json.dumps(partial_results), job_id)
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
            params = (error, job_id)

        with self._error_context("mark job failed"):
            result = self._execute_query(query, params, fetch='one')
            success = result is not None
            if success:
                logger.info(f"[GUARDIAN] Marked job {job_id[:16]}... as FAILED")
            return success

    def increment_task_retry(self, task_id: str) -> int:
        """
        Increment retry_count for a task and return new value.

        Args:
            task_id: Task to increment retry count for.

        Returns:
            New retry_count value, or -1 if task not found.
        """
        query = sql.SQL("""
            UPDATE {schema}.tasks
            SET
                retry_count = retry_count + 1,
                updated_at = NOW()
            WHERE task_id = %s
            RETURNING retry_count
        """).format(schema=sql.Identifier(self.schema_name))

        with self._error_context("increment task retry"):
            result = self._execute_query(query, (task_id,), fetch='one')
            if result:
                new_count = result['retry_count']
                logger.info(f"[GUARDIAN] Task {task_id[:16]}... retry_count -> {new_count}")
                return new_count
            return -1

    # ====================================================================
    # AUDIT LOGGING (two-phase)
    # ====================================================================

    def log_sweep_start(
        self,
        sweep_id: str,
        started_at: datetime
    ) -> Optional[str]:
        """
        Insert a new sweep audit record with status='running'.

        Phase 1 of two-phase audit: creates the record at sweep start.
        Non-fatal - logs warning and returns None on failure.

        Args:
            sweep_id: UUID for this sweep.
            started_at: When the sweep started.

        Returns:
            The sweep_id if inserted, None on failure.
        """
        query = sql.SQL("""
            INSERT INTO {schema}.janitor_runs (
                run_id,
                run_type,
                started_at,
                status,
                items_scanned,
                items_fixed,
                actions_taken
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("log sweep start"):
                result = self._execute_query(
                    query,
                    (sweep_id, 'sweep', started_at, 'running', 0, 0, json.dumps([])),
                    fetch='one'
                )
                if result:
                    logger.info(f"[GUARDIAN] Sweep {sweep_id[:8]}... audit record created")
                    return str(result['run_id'])
                return None
        except Exception as e:
            logger.warning(f"[GUARDIAN] Failed to log sweep start (non-fatal): {e}")
            return None

    def log_sweep_end(
        self,
        sweep_id: str,
        completed_at: datetime,
        items_scanned: int,
        items_fixed: int,
        actions_taken: List[Dict[str, Any]],
        phases: Optional[Dict[str, Any]],
        status: str,
        error_details: Optional[str] = None
    ) -> bool:
        """
        Update an existing sweep audit record with final results.

        Phase 2 of two-phase audit: updates the record at sweep end.
        Non-fatal - logs warning and returns False on failure.

        Args:
            sweep_id: UUID of the sweep to update.
            completed_at: When the sweep completed.
            items_scanned: Total items examined.
            items_fixed: Total items fixed.
            actions_taken: Flat list of all actions.
            phases: Per-phase breakdown dict.
            status: Final status (completed/failed).
            error_details: Error message if failed.

        Returns:
            True if updated, False on failure.
        """
        query = sql.SQL("""
            UPDATE {schema}.janitor_runs
            SET
                completed_at = %s,
                items_scanned = %s,
                items_fixed = %s,
                actions_taken = %s::jsonb,
                phases = %s::jsonb,
                status = %s,
                error_details = %s,
                duration_ms = EXTRACT(EPOCH FROM (%s - started_at)) * 1000
            WHERE run_id = %s
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("log sweep end"):
                result = self._execute_query(
                    query,
                    (
                        completed_at,
                        items_scanned,
                        items_fixed,
                        json.dumps(actions_taken),
                        json.dumps(phases) if phases else None,
                        status,
                        error_details,
                        completed_at,  # For duration calculation
                        sweep_id
                    ),
                    fetch='one'
                )
                if result:
                    logger.info(
                        f"[GUARDIAN] Sweep {sweep_id[:8]}... completed: "
                        f"status={status}, scanned={items_scanned}, fixed={items_fixed}"
                    )
                    return True
                else:
                    logger.warning(f"[GUARDIAN] No sweep record found for {sweep_id[:8]}...")
                    return False
        except Exception as e:
            logger.warning(f"[GUARDIAN] Failed to log sweep end (non-fatal): {e}")
            return False

    def get_recent_sweeps(
        self,
        hours: int = 24,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent sweep audit records for monitoring.

        Args:
            hours: How many hours of history to fetch.
            limit: Maximum records to return.

        Returns:
            List of sweep dicts, newest first.
        """
        query = sql.SQL("""
            SELECT *
            FROM {schema}.janitor_runs
            WHERE started_at > NOW() - make_interval(hours => %s)
              AND run_type = 'sweep'
            ORDER BY started_at DESC
            LIMIT %s
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("get recent sweeps"):
                result = self._execute_query(query, (hours, limit), fetch='all')
                return result or []
        except Exception as e:
            logger.warning(f"[GUARDIAN] Could not get recent sweeps: {e}")
            return []

    def get_recent_runs(
        self,
        hours: int = 24,
        run_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get recent janitor_runs records (all types) for monitoring/history.

        Args:
            hours: How many hours of history to fetch.
            run_type: Optional filter by run_type.
            limit: Maximum records to return.

        Returns:
            List of run dicts, newest first.
        """
        if run_type:
            query = sql.SQL("""
                SELECT *
                FROM {schema}.janitor_runs
                WHERE started_at > NOW() - make_interval(hours => %s)
                  AND run_type = %s
                ORDER BY started_at DESC
                LIMIT %s
            """).format(schema=sql.Identifier(self.schema_name))
            params = (hours, run_type, limit)
        else:
            query = sql.SQL("""
                SELECT *
                FROM {schema}.janitor_runs
                WHERE started_at > NOW() - make_interval(hours => %s)
                ORDER BY started_at DESC
                LIMIT %s
            """).format(schema=sql.Identifier(self.schema_name))
            params = (hours, limit)

        try:
            with self._error_context("get recent runs"):
                result = self._execute_query(query, params, fetch='all')
                return result or []
        except Exception as e:
            logger.warning(f"[GUARDIAN] Could not get recent runs: {e}")
            return []

    def log_run(
        self,
        run_type: str,
        started_at,
        completed_at,
        items_scanned: int,
        items_fixed: int,
        actions_taken: List[Dict[str, Any]],
        status: str = "completed",
        error_details: Optional[str] = None
    ) -> Optional[str]:
        """
        Log a maintenance run to the janitor_runs audit table.

        Generic run logger used by non-sweep operations (e.g. queue_depth_snapshot).

        Args:
            run_type: Type of run.
            started_at: When the run started.
            completed_at: When the run completed.
            items_scanned: Number of items scanned.
            items_fixed: Number of items fixed.
            actions_taken: List of actions taken.
            status: Run status.
            error_details: Error message if failed.

        Returns:
            Run ID if created, None if failed.
        """
        run_id = str(uuid.uuid4())
        if completed_at and started_at:
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        else:
            duration_ms = None

        query = sql.SQL("""
            INSERT INTO {schema}.janitor_runs (
                run_id,
                run_type,
                started_at,
                completed_at,
                status,
                items_scanned,
                items_fixed,
                actions_taken,
                error_details,
                duration_ms
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING run_id
        """).format(schema=sql.Identifier(self.schema_name))

        try:
            with self._error_context("log run"):
                result = self._execute_query(
                    query,
                    (
                        run_id, run_type, started_at, completed_at,
                        status, items_scanned, items_fixed,
                        json.dumps(actions_taken), error_details, duration_ms
                    ),
                    fetch='one'
                )
                if result:
                    logger.info(
                        f"[GUARDIAN] Logged run: type={run_type}, "
                        f"scanned={items_scanned}, fixed={items_fixed}"
                    )
                    return str(result['run_id'])
                return None
        except Exception as e:
            logger.warning(f"[GUARDIAN] Failed to log run (non-fatal): {e}")
            return None

    def record_queue_depth_snapshot(self) -> Dict[str, Any]:
        """
        Capture queue depth snapshot using janitor_runs infrastructure.

        Records Service Bus queue depths as a run of type
        'queue_depth_snapshot'. The actions_taken field stores per-queue
        message counts for time-series trending.

        Returns:
            Dict with snapshot results (success, queue_depths, etc.)
        """
        from datetime import timedelta
        started_at = datetime.now(timezone.utc)
        actions = []
        total_messages = 0

        try:
            from infrastructure.service_bus import ServiceBusRepository
            from config import get_config

            config = get_config()
            sb_repo = ServiceBusRepository()

            queue_names = [
                config.queues.jobs_queue,
                config.queues.container_tasks_queue,
            ]

            for queue_name in queue_names:
                if not queue_name:
                    continue
                try:
                    count = sb_repo.get_queue_length(queue_name)
                    actions.append({
                        "queue": queue_name,
                        "active_messages": count,
                        "status": "ok",
                    })
                    total_messages += count
                except Exception as e:
                    actions.append({
                        "queue": queue_name,
                        "active_messages": -1,
                        "status": "error",
                        "error": str(e)[:200],
                    })

            completed_at = datetime.now(timezone.utc)

            run_id = self.log_run(
                run_type="queue_depth_snapshot",
                started_at=started_at,
                completed_at=completed_at,
                items_scanned=len(queue_names),
                items_fixed=0,
                actions_taken=actions,
                status="completed",
            )

            return {
                "success": True,
                "run_type": "queue_depth_snapshot",
                "run_id": run_id,
                "items_scanned": len(queue_names),
                "items_fixed": 0,
                "total_messages": total_messages,
                "queue_depths": actions,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
            }

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            logger.warning(f"[GUARDIAN] Queue depth snapshot failed: {e}")

            self.log_run(
                run_type="queue_depth_snapshot",
                started_at=started_at,
                completed_at=completed_at,
                items_scanned=0,
                items_fixed=0,
                actions_taken=actions,
                status="failed",
                error_details=str(e)[:500],
            )

            return {
                "success": False,
                "run_type": "queue_depth_snapshot",
                "error": str(e)[:500],
                "items_scanned": 0,
                "items_fixed": 0,
            }


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = ['GuardianRepository']
