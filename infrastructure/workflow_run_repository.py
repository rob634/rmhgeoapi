# ============================================================================
# CLAUDE CONTEXT - WORKFLOW RUN REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - Atomic DB operations for workflow DAG tables
# PURPOSE: Insert WorkflowRun + WorkflowTask + WorkflowTaskDep atomically in one
#          transaction; provide idempotent-safe UniqueViolation handling,
#          simple run lookup by PK, and DAG orchestrator read/write operations.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowRunRepository
# DEPENDENCIES: psycopg, psycopg.sql, psycopg.errors, psycopg.rows,
#               infrastructure.postgresql, core.models.workflow_run,
#               core.models.workflow_task, core.models.workflow_task_dep,
#               core.dag_graph_utils, exceptions
# ============================================================================

import time
from datetime import datetime, timezone
from typing import Optional

import psycopg
import psycopg.errors
from psycopg import sql
from psycopg.rows import dict_row

from core.dag_graph_utils import TaskSummary
from core.models.workflow_enums import WorkflowTaskStatus, WorkflowRunStatus
from core.models.workflow_run import WorkflowRun
from core.models.workflow_task import WorkflowTask
from core.models.workflow_task_dep import WorkflowTaskDep
from exceptions import DatabaseError
from .postgresql import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, __name__)

# Schema that holds the three DAG tables (matches WorkflowRun.__sql_schema)
_SCHEMA = "app"


class WorkflowRunRepository(PostgreSQLRepository):
    """
    Atomic DB operations for workflow DAG tables.

    Spec: Component 2 — WorkflowRunRepository.
    Inherits connection management, SQL composition helpers, and schema verification
    from PostgreSQLRepository. All SQL uses psycopg.sql.Composed — never f-strings.

    FK insertion order: workflow_runs → workflow_tasks → workflow_task_deps.
    """

    # =========================================================================
    # ATOMIC WRITE
    # =========================================================================

    def insert_run_atomic(
        self,
        run: WorkflowRun,
        tasks: list[WorkflowTask],
        deps: list[WorkflowTaskDep],
    ) -> bool:
        """
        Insert a WorkflowRun, its WorkflowTask rows, and its WorkflowTaskDep edges
        as a single atomic transaction.

        Spec: WorkflowRunRepository.insert_run_atomic — all three inserts in one
        transaction, FK order respected (runs → tasks → deps).

        Returns:
          True  — all rows inserted, transaction committed.
          False — run_id already exists (UniqueViolation on workflow_runs PK);
                  transaction rolled back, no partial state written.

        Raises:
          DatabaseError — any psycopg.Error other than UniqueViolation on the run
                          insert. Wraps the original exception.

        Handles (Operator concern O-1): partial write on task/dep insert failures
        is prevented because all three inserts share one transaction; any failure
        triggers a full rollback before re-raising.

        Handles (Critic concern C-1): UniqueViolation is caught only on the run
        INSERT, not silently swallowed — the caller receives a clear False signal.
        """
        run_insert_sql = sql.SQL(
            "INSERT INTO {schema}.workflow_runs ("
            "run_id, workflow_name, parameters, status, definition, "
            "platform_version, result_data, created_at, started_at, completed_at, "
            "request_id, asset_id, release_id, legacy_job_id, schedule_id"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
            ")"
        ).format(schema=sql.Identifier(_SCHEMA))

        task_insert_sql = sql.SQL(
            "INSERT INTO {schema}.workflow_tasks ("
            "task_instance_id, run_id, task_name, handler, status, "
            "fan_out_index, fan_out_source, when_clause, parameters, "
            "result_data, error_details, retry_count, max_retries, "
            "claimed_by, last_pulse, execute_after, "
            "started_at, completed_at, created_at, updated_at"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
            ")"
        ).format(schema=sql.Identifier(_SCHEMA))

        dep_insert_sql = sql.SQL(
            "INSERT INTO {schema}.workflow_task_deps ("
            "task_instance_id, depends_on_instance_id, optional"
            ") VALUES (%s, %s, %s)"
        ).format(schema=sql.Identifier(_SCHEMA))

        # Pre-build parameter tuples outside the transaction to keep the hot path lean
        run_params = _run_to_params(run)
        task_params_list = [_task_to_params(t) for t in tasks]
        dep_params_list = [_dep_to_params(d) for d in deps]

        try:
            with self._get_connection() as conn:
                try:
                    with conn.cursor() as cur:
                        # --- INSERT workflow_runs ---
                        try:
                            cur.execute(run_insert_sql, run_params)
                        except psycopg.errors.UniqueViolation:
                            # run_id already exists — idempotent path
                            conn.rollback()
                            logger.warning(
                                "UniqueViolation on workflow_runs insert — run already exists: run_id=%s",
                                run.run_id,
                            )
                            return False

                        # --- INSERT workflow_tasks (executemany) ---
                        if task_params_list:
                            cur.executemany(task_insert_sql, task_params_list)

                        # --- INSERT workflow_task_deps (executemany) ---
                        if dep_params_list:
                            cur.executemany(dep_insert_sql, dep_params_list)

                        conn.commit()

                except psycopg.Error as exc:
                    # Handles (Operator concern O-1): unexpected DB error after run insert —
                    # rollback prevents partial state (tasks without deps, etc.)
                    try:
                        conn.rollback()
                    except Exception as rb_exc:
                        logger.error(
                            "Rollback failed after DB error: run_id=%s rollback_error=%s",
                            run.run_id,
                            rb_exc,
                        )
                    logger.error(
                        "Unexpected DB error during atomic run insert: run_id=%s error=%s",
                        run.run_id,
                        exc,
                    )
                    raise DatabaseError(
                        f"Failed to insert workflow run atomically (run_id={run.run_id}): {exc}"
                    ) from exc

        except DatabaseError:
            raise  # already wrapped and logged above
        except Exception as exc:
            # Non-psycopg errors (e.g. connection pool exhaustion) — wrap for callers
            logger.error(
                "Non-DB error during atomic run insert: run_id=%s error=%s",
                run.run_id,
                exc,
            )
            raise DatabaseError(
                f"Unexpected error inserting workflow run (run_id={run.run_id}): {exc}"
            ) from exc

        return True

    # =========================================================================
    # LOOKUP
    # =========================================================================

    def get_by_run_id(self, run_id: str) -> Optional[WorkflowRun]:
        """
        Fetch a WorkflowRun by primary key.

        Spec: WorkflowRunRepository.get_by_run_id — SELECT by PK, None if not found.
        Used by DAGInitializer.create_run on the idempotent path to return the
        pre-existing run to the caller.
        """
        query = sql.SQL(
            "SELECT run_id, workflow_name, parameters, status, definition, "
            "platform_version, result_data, created_at, started_at, completed_at, "
            "request_id, asset_id, release_id, legacy_job_id, schedule_id "
            "FROM {schema}.workflow_runs WHERE run_id = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (run_id,))
                    row = cur.fetchone()

            if row is None:
                return None

            return WorkflowRun(**dict(row))

        except psycopg.Error as exc:
            logger.error(
                "DB error fetching workflow run: run_id=%s error=%s", run_id, exc
            )
            raise DatabaseError(
                f"Failed to fetch workflow run (run_id={run_id}): {exc}"
            ) from exc

    def list_active_runs(self) -> list[str]:
        """
        Return run_ids for all non-terminal workflow runs.

        Includes PENDING, RUNNING, and AWAITING_APPROVAL (gate-suspended).
        AWAITING_APPROVAL runs are included so the Brain's gate reconciliation
        loop can check the linked release's approval_state and resume/skip/fail.

        Used by the DAG Brain primary loop to discover runs that need
        orchestration. Returns oldest first so PENDING runs get picked up
        before long-running ones.
        """
        query = sql.SQL(
            "SELECT run_id FROM {schema}.workflow_runs "
            "WHERE status IN ('pending', 'running', 'awaiting_approval') "
            "ORDER BY created_at ASC"
        ).format(schema=sql.Identifier(_SCHEMA))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    return [row["run_id"] for row in cur.fetchall()]
        except Exception as exc:
            logger.error("DB error in list_active_runs: %s", exc)
            raise DatabaseError(f"Failed to list active runs: {exc}") from exc

    def list_runs(
        self,
        status: Optional[str] = None,
        workflow_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        List workflow runs with optional filters.

        Returns dicts with run_id, workflow_name, status, created_at,
        started_at, completed_at, request_id. Ordered by created_at DESC.
        """
        fragments = [
            sql.SQL(
                "SELECT run_id, workflow_name, status, "
                "created_at, started_at, completed_at, request_id "
                "FROM {schema}.workflow_runs"
            ).format(schema=sql.Identifier(_SCHEMA))
        ]
        params: list = []
        conditions = []

        if status:
            conditions.append(sql.SQL("status = %s"))
            params.append(status)
        if workflow_name:
            conditions.append(sql.SQL("workflow_name = %s"))
            params.append(workflow_name)

        if conditions:
            fragments.append(sql.SQL("WHERE ") + sql.SQL(" AND ").join(conditions))

        fragments.append(sql.SQL("ORDER BY created_at DESC LIMIT %s"))
        params.append(limit)

        query = sql.SQL(" ").join(fragments)

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    return cur.fetchall()
        except Exception as exc:
            logger.error("DB error in list_runs: %s", exc)
            raise DatabaseError(f"Failed to list runs: {exc}") from exc

    def get_task_status_counts(self, run_id: str) -> dict[str, int]:
        """
        Get task counts grouped by status for a run.

        Returns dict like {"ready": 3, "running": 1, "completed": 10}.
        """
        query = sql.SQL(
            "SELECT status, COUNT(*) as count "
            "FROM {schema}.workflow_tasks WHERE run_id = %s "
            "GROUP BY status"
        ).format(schema=sql.Identifier(_SCHEMA))

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (run_id,))
                    return {row["status"]: row["count"] for row in cur.fetchall()}
        except Exception as exc:
            logger.error("DB error in get_task_status_counts: %s", exc)
            raise DatabaseError(f"Failed to get task counts for run {run_id}: {exc}") from exc

    def list_task_details(
        self,
        run_id: str,
        status: Optional[str] = None,
    ) -> list[dict]:
        """
        List full task details for a run, optionally filtered by status.

        Returns dicts with all task columns. For admin/diagnostic endpoints.
        """
        base = sql.SQL(
            "SELECT task_instance_id, task_name, handler, status, "
            "fan_out_index, fan_out_source, when_clause, "
            "result_data, error_details, retry_count, max_retries, "
            "claimed_by, last_pulse, execute_after, "
            "started_at, completed_at, created_at "
            "FROM {schema}.workflow_tasks"
        ).format(schema=sql.Identifier(_SCHEMA))

        if status:
            query = base + sql.SQL(" WHERE run_id = %s AND status = %s ORDER BY created_at")
            params: tuple = (run_id, status)
        else:
            query = base + sql.SQL(" WHERE run_id = %s ORDER BY created_at")
            params = (run_id,)

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    return cur.fetchall()
        except Exception as exc:
            logger.error("DB error in list_task_details: %s", exc)
            raise DatabaseError(f"Failed to list tasks for run {run_id}: {exc}") from exc

    def get_recent_runs_for_schedule(
        self, schedule_id: str, limit: int = 5
    ) -> list[dict]:
        """
        Get recent workflow runs for a schedule, ordered newest first.
        """
        query = sql.SQL(
            "SELECT run_id, status, created_at, completed_at "
            "FROM {schema}.workflow_runs WHERE schedule_id = %s "
            "ORDER BY created_at DESC LIMIT %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (schedule_id, limit))
                    return cur.fetchall()
        except Exception as exc:
            logger.error("DB error in get_recent_runs_for_schedule: %s", exc)
            raise DatabaseError(
                f"Failed to get recent runs for schedule {schedule_id}: {exc}"
            ) from exc

    # =========================================================================
    # DAG ORCHESTRATOR READ OPERATIONS
    # =========================================================================

    def get_tasks_for_run(self, run_id: str) -> list[TaskSummary]:
        """
        Fetch all task instances for a run as lightweight TaskSummary DTOs.

        Spec: D.5 — WorkflowRunRepository.get_tasks_for_run. Returns the six
        fields required by the graph utility functions. No result_data
        deserialization beyond what psycopg delivers via dict_row (JSONB columns
        are returned as dicts by psycopg's default JSONB adapter).

        Parameters
        ----------
        run_id:
            The workflow run primary key.

        Returns
        -------
        list[TaskSummary]
            All task instances for the run, unordered.

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "SELECT task_instance_id, task_name, handler, status, result_data, "
            "fan_out_source, fan_out_index "
            "FROM {schema}.workflow_tasks WHERE run_id = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (run_id,))
                    rows = cur.fetchall()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "get_tasks_for_run: run_id=%s rows=%d elapsed_ms=%.1f",
                run_id, len(rows), elapsed_ms,
            )
            return [
                TaskSummary(
                    task_instance_id=row["task_instance_id"],
                    task_name=row["task_name"],
                    handler=row["handler"],
                    status=WorkflowTaskStatus(row["status"]),
                    result_data=row["result_data"],
                    fan_out_source=row["fan_out_source"],
                    fan_out_index=row["fan_out_index"],
                )
                for row in rows
            ]

        except psycopg.Error as exc:
            logger.error(
                "DB error in get_tasks_for_run: run_id=%s error=%s", run_id, exc
            )
            raise DatabaseError(
                f"Failed to fetch tasks for run (run_id={run_id}): {exc}"
            ) from exc

    def get_deps_for_run(self, run_id: str) -> list[tuple[str, str, bool]]:
        """
        Fetch all dependency edges for tasks belonging to a run.

        Spec: D.5 — WorkflowRunRepository.get_deps_for_run. Joins deps against
        tasks so only edges whose task_instance_id belongs to this run are
        returned (depends_on_instance_id is implicitly covered because the FK
        graph is self-contained per run).

        Parameters
        ----------
        run_id:
            The workflow run primary key.

        Returns
        -------
        list[tuple[str, str, bool]]
            Each element is (task_instance_id, depends_on_instance_id, optional).

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "SELECT d.task_instance_id, d.depends_on_instance_id, d.optional "
            "FROM {schema}.workflow_task_deps d "
            "INNER JOIN {schema}.workflow_tasks t "
            "  ON t.task_instance_id = d.task_instance_id "
            "WHERE t.run_id = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (run_id,))
                    rows = cur.fetchall()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "get_deps_for_run: run_id=%s rows=%d elapsed_ms=%.1f",
                run_id, len(rows), elapsed_ms,
            )
            return [
                (row["task_instance_id"], row["depends_on_instance_id"], row["optional"])
                for row in rows
            ]

        except psycopg.Error as exc:
            logger.error(
                "DB error in get_deps_for_run: run_id=%s error=%s", run_id, exc
            )
            raise DatabaseError(
                f"Failed to fetch deps for run (run_id={run_id}): {exc}"
            ) from exc

    def get_predecessor_outputs(
        self, run_id: str, task_name: str
    ) -> dict[str, Optional[dict]]:
        """
        Fetch result_data from completed/expanded upstream tasks for a given node.

        Spec: D.5 — WorkflowRunRepository.get_predecessor_outputs. Used by
        DAGOrchestrator to pass upstream results to fan-in handlers and to
        resolve parameter expressions (e.g. ``{{ steps.upload.result.path }}``).

        Only predecessors in COMPLETED or EXPANDED status are returned —
        SKIPPED/CANCELLED predecessors produced no output.

        Parameters
        ----------
        run_id:
            The workflow run primary key.
        task_name:
            The task node name whose upstream outputs are needed.

        Returns
        -------
        dict[str, Optional[dict]]
            Maps upstream task_name → result_data (None if the upstream stored
            a SQL NULL in result_data).

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "SELECT upstream.task_name, upstream.result_data "
            "FROM {schema}.workflow_task_deps d "
            "INNER JOIN {schema}.workflow_tasks target "
            "  ON target.task_instance_id = d.task_instance_id "
            "INNER JOIN {schema}.workflow_tasks upstream "
            "  ON upstream.task_instance_id = d.depends_on_instance_id "
            "WHERE target.run_id = %s "
            "  AND target.task_name = %s "
            "  AND upstream.status IN ('completed', 'expanded')"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (run_id, task_name))
                    rows = cur.fetchall()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "get_predecessor_outputs: run_id=%s task_name=%r predecessors=%d elapsed_ms=%.1f",
                run_id, task_name, len(rows), elapsed_ms,
            )
            return {row["task_name"]: row["result_data"] for row in rows}

        except psycopg.Error as exc:
            logger.error(
                "DB error in get_predecessor_outputs: run_id=%s task_name=%r error=%s",
                run_id, task_name, exc,
            )
            raise DatabaseError(
                f"Failed to fetch predecessor outputs "
                f"(run_id={run_id}, task_name={task_name!r}): {exc}"
            ) from exc

    # =========================================================================
    # DAG ORCHESTRATOR WRITE OPERATIONS
    # =========================================================================

    def promote_task(
        self,
        task_instance_id: str,
        from_status: WorkflowTaskStatus,
        to_status: WorkflowTaskStatus,
    ) -> bool:
        """
        Compare-and-swap status transition for a single task instance.

        Spec: D.5 — WorkflowRunRepository.promote_task. Performs an optimistic
        CAS update: the WHERE clause guards on the expected current status so
        concurrent orchestrator ticks cannot double-advance the same task.

        Parameters
        ----------
        task_instance_id:
            Primary key of the task to update.
        from_status:
            Expected current status (CAS guard).
        to_status:
            Desired new status.

        Returns
        -------
        bool
            True if exactly one row was updated (transition succeeded).
            False if the row was not found or status had already changed
            (another tick or worker beat us).

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = %s, updated_at = NOW() "
            "WHERE task_instance_id = %s AND status = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (to_status.value, task_instance_id, from_status.value),
                    )
                    updated = cur.rowcount
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if updated == 1:
                logger.info(
                    "promote_task: task_instance_id=%s %s→%s elapsed_ms=%.1f",
                    task_instance_id, from_status.value, to_status.value, elapsed_ms,
                )
                return True
            else:
                logger.debug(
                    "promote_task: guard rejected — task_instance_id=%s expected_status=%s "
                    "(already transitioned or not found)",
                    task_instance_id, from_status.value,
                )
                return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in promote_task: task_instance_id=%s error=%s",
                task_instance_id, exc,
            )
            raise DatabaseError(
                f"Failed to promote task (task_instance_id={task_instance_id}): {exc}"
            ) from exc

    def skip_task(self, task_instance_id: str) -> bool:
        """
        Transition a task to SKIPPED status if it is still pending or ready.

        Spec: D.5 — WorkflowRunRepository.skip_task. Used by DAGOrchestrator to
        skip conditional branch tasks whose when-clause evaluated to False, and
        to propagate SKIPPED status to descendants of a skipped node.

        Only transitions from PENDING or READY are permitted — if the task has
        already been claimed by a worker (RUNNING) the skip is rejected so the
        worker can complete normally.

        Parameters
        ----------
        task_instance_id:
            Primary key of the task to skip.

        Returns
        -------
        bool
            True if the task was skipped.
            False if the task was not in a skippable state (already running,
            completed, etc.).

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'skipped', updated_at = NOW() "
            "WHERE task_instance_id = %s AND status IN ('pending', 'ready')"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (task_instance_id,))
                    updated = cur.rowcount
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if updated == 1:
                logger.info(
                    "skip_task: task_instance_id=%s skipped elapsed_ms=%.1f",
                    task_instance_id, elapsed_ms,
                )
                return True
            else:
                logger.debug(
                    "skip_task: guard rejected — task_instance_id=%s "
                    "(not in pending/ready state)",
                    task_instance_id,
                )
                return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in skip_task: task_instance_id=%s error=%s",
                task_instance_id, exc,
            )
            raise DatabaseError(
                f"Failed to skip task (task_instance_id={task_instance_id}): {exc}"
            ) from exc

    def fail_task(self, task_instance_id: str, error_details: str) -> None:
        """
        Mark a task as FAILED with error details and completion timestamp.

        Spec: D.5 — WorkflowRunRepository.fail_task. Called by DAGOrchestrator
        when a worker reports failure or when the orchestrator itself detects an
        unrecoverable error during task setup (e.g. parameter resolution failure).

        Guarded on current status — only updates tasks in PENDING, READY, or
        RUNNING state. Tasks already in a terminal state (COMPLETED, FAILED,
        SKIPPED, EXPANDED) are silently left unchanged.

        Parameters
        ----------
        task_instance_id:
            Primary key of the task to fail.
        error_details:
            Human-readable error message stored for diagnostics.

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'failed', error_details = %s, "
            "completed_at = NOW(), updated_at = NOW() "
            "WHERE task_instance_id = %s "
            "AND status IN ('running', 'ready', 'pending')"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (error_details, task_instance_id))
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "fail_task: task_instance_id=%s elapsed_ms=%.1f",
                task_instance_id, elapsed_ms,
            )

        except psycopg.Error as exc:
            logger.error(
                "DB error in fail_task: task_instance_id=%s error=%s",
                task_instance_id, exc,
            )
            raise DatabaseError(
                f"Failed to mark task as failed (task_instance_id={task_instance_id}): {exc}"
            ) from exc

    def expand_fan_out(
        self,
        template_id: str,
        children: list[tuple],
        deps: list[tuple],
    ) -> bool:
        """
        Atomically mark a fan-out template as EXPANDED and insert child instances.

        Spec: D.5 — WorkflowRunRepository.expand_fan_out. All three writes
        (UPDATE template + INSERT children + INSERT deps) share one transaction.
        If the template has already been expanded (UniqueViolation on the
        (run_id, task_name, fan_out_index) unique constraint), the transaction is
        rolled back and False is returned — idempotent re-entry is safe.

        Parameters
        ----------
        template_id:
            task_instance_id of the fan-out template task to mark EXPANDED.
        children:
            List of parameter tuples for workflow_tasks INSERT, each matching
            the column order of _task_insert_sql (20 values per row).
        deps:
            List of (task_instance_id, depends_on_instance_id, optional) tuples
            for the workflow_task_deps INSERT.

        Returns
        -------
        bool
            True if expansion succeeded.
            False if a UniqueViolation occurred (already expanded — idempotent).

        Raises
        ------
        DatabaseError
            On any psycopg.Error other than UniqueViolation.
        """
        expand_sql = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'expanded', updated_at = NOW() "
            "WHERE task_instance_id = %s AND status = 'ready'"
        ).format(schema=sql.Identifier(_SCHEMA))

        child_insert_sql = sql.SQL(
            "INSERT INTO {schema}.workflow_tasks ("
            "task_instance_id, run_id, task_name, handler, status, "
            "fan_out_index, fan_out_source, when_clause, parameters, "
            "result_data, error_details, retry_count, max_retries, "
            "claimed_by, last_pulse, execute_after, "
            "started_at, completed_at, created_at, updated_at"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
            ")"
        ).format(schema=sql.Identifier(_SCHEMA))

        dep_insert_sql = sql.SQL(
            "INSERT INTO {schema}.workflow_task_deps ("
            "task_instance_id, depends_on_instance_id, optional"
            ") VALUES (%s, %s, %s)"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                try:
                    with conn.cursor() as cur:
                        # Mark template as expanded (CAS guard: only if still READY)
                        cur.execute(expand_sql, (template_id,))
                        if cur.rowcount == 0:
                            conn.rollback()
                            logger.debug(
                                "expand_fan_out: CAS guard rejected — template no longer READY: "
                                "template_id=%s",
                                template_id,
                            )
                            return False

                        # Insert child task instances
                        if children:
                            cur.executemany(child_insert_sql, children)

                        # Insert deps for child instances
                        if deps:
                            cur.executemany(dep_insert_sql, deps)

                        conn.commit()

                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    logger.debug(
                        "expand_fan_out: UniqueViolation — template already expanded: "
                        "template_id=%s",
                        template_id,
                    )
                    return False

                except psycopg.Error as exc:
                    try:
                        conn.rollback()
                    except Exception as rb_exc:
                        logger.error(
                            "expand_fan_out: rollback failed: template_id=%s rollback_error=%s",
                            template_id, rb_exc,
                        )
                    logger.error(
                        "DB error in expand_fan_out: template_id=%s error=%s",
                        template_id, exc,
                    )
                    raise DatabaseError(
                        f"Failed to expand fan-out (template_id={template_id}): {exc}"
                    ) from exc

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "expand_fan_out: template_id=%s children=%d deps=%d elapsed_ms=%.1f",
                template_id, len(children), len(deps), elapsed_ms,
            )
            return True

        except DatabaseError:
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error in expand_fan_out: template_id=%s error=%s",
                template_id, exc,
            )
            raise DatabaseError(
                f"Unexpected error expanding fan-out (template_id={template_id}): {exc}"
            ) from exc

    def set_task_parameters(self, task_instance_id: str, parameters: dict) -> None:
        """
        Persist resolved parameters onto a task instance before it is promoted to READY.

        Spec: D.5 — WorkflowRunRepository.set_task_parameters. Called by
        evaluate_transitions immediately after resolve_task_params succeeds and
        before promote_task(PENDING→READY), so the worker always finds a fully
        populated parameters column when it claims the task.

        No status guard is applied here — the caller (evaluate_transitions) is
        responsible for only calling this on tasks that are still PENDING and
        have successfully resolved parameters.

        Parameters
        ----------
        task_instance_id:
            Primary key of the task to update.
        parameters:
            Resolved parameter dict to store as JSONB. Must be JSON-serializable.

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET parameters = %s::jsonb, updated_at = NOW() "
            "WHERE task_instance_id = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (parameters, task_instance_id),
                    )
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "set_task_parameters: task_instance_id=%s keys=%s elapsed_ms=%.1f",
                task_instance_id, list(parameters.keys()), elapsed_ms,
            )

        except psycopg.Error as exc:
            logger.error(
                "DB error in set_task_parameters: task_instance_id=%s error=%s",
                task_instance_id, exc,
            )
            raise DatabaseError(
                f"Failed to set task parameters (task_instance_id={task_instance_id}): {exc}"
            ) from exc

    def set_params_and_promote(
        self,
        task_instance_id: str,
        parameters: dict,
        from_status: WorkflowTaskStatus,
        to_status: WorkflowTaskStatus,
    ) -> bool:
        """
        Atomically set resolved parameters AND promote status in a single UPDATE.

        Combines set_task_parameters + promote_task into one CAS-guarded write,
        eliminating the crash window between the two separate calls.

        Returns True if the task was updated, False if the CAS guard rejected.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET parameters = %s::jsonb, status = %s, updated_at = NOW() "
            "WHERE task_instance_id = %s AND status = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (parameters, to_status.value,
                         task_instance_id, from_status.value),
                    )
                    updated = cur.rowcount
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if updated == 1:
                logger.info(
                    "set_params_and_promote: task_instance_id=%s %s→%s elapsed_ms=%.1f",
                    task_instance_id, from_status.value, to_status.value, elapsed_ms,
                )
                return True
            else:
                logger.debug(
                    "set_params_and_promote: guard rejected — task_instance_id=%s",
                    task_instance_id,
                )
                return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in set_params_and_promote: task_instance_id=%s error=%s",
                task_instance_id, exc,
            )
            raise DatabaseError(
                f"Failed to set params and promote (task_instance_id={task_instance_id}): {exc}"
            ) from exc

    # =========================================================================
    # D.6 — WORKER CLAIM / COMPLETE / RELEASE FOR WORKFLOW TASKS
    # =========================================================================

    def claim_ready_workflow_task(self, worker_id: str) -> Optional[WorkflowTask]:
        """
        Atomically claim one workflow task via SKIP LOCKED.

        Spec: D.6 — Worker dual-poll. Mirrors claim_ready_task() from
        jobs_tasks.py but targets app.workflow_tasks instead of app.tasks.

        Only claims tasks with handler NOT in sentinel set (conditionals,
        fan-in, fan-out templates are orchestrator-managed, not worker tasks).

        Returns WorkflowTask if claimed, None if no tasks available.
        """
        select_query = sql.SQL(
            "SELECT * FROM {schema}.workflow_tasks "
            "WHERE status = 'ready' "
            "  AND handler NOT IN ('__conditional__', '__fan_out__', '__fan_in__', '__gate__') "
            "  AND (execute_after IS NULL OR execute_after < NOW()) "
            "ORDER BY created_at "
            "LIMIT 1 "
            "FOR UPDATE SKIP LOCKED"
        ).format(schema=sql.Identifier(_SCHEMA))

        update_query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'running', "
            "    claimed_by = %s, "
            "    started_at = NOW(), "
            "    last_pulse = NOW(), "
            "    updated_at = NOW() "
            "WHERE task_instance_id = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(select_query)
                    row = cur.fetchone()

                    if not row:
                        conn.commit()
                        return None

                    task_instance_id = row["task_instance_id"]
                    cur.execute(update_query, (worker_id, task_instance_id))
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            task = _workflow_task_from_row(row)
            task.status = WorkflowTaskStatus.RUNNING
            task.claimed_by = worker_id
            task.started_at = datetime.now(timezone.utc)
            task.last_pulse = datetime.now(timezone.utc)

            logger.info(
                "claim_ready_workflow_task: claimed task_instance_id=%s handler=%s "
                "worker=%s elapsed_ms=%.1f",
                task_instance_id, row["handler"], worker_id, elapsed_ms,
            )
            return task

        except psycopg.Error as exc:
            logger.error("DB error in claim_ready_workflow_task: %s", exc)
            raise DatabaseError(f"Failed to claim workflow task: {exc}") from exc

    def update_workflow_task_pulse(
        self, task_instance_id: str, progress: Optional[dict] = None
    ) -> bool:
        """
        Update last_pulse timestamp for a running workflow task.

        Called periodically by the worker's pulse thread to signal
        the task is still alive. The janitor uses last_pulse to detect
        stale tasks. Only updates if the task is still RUNNING (CAS guard).

        If progress is provided, it is merged into result_data under the
        "progress" key. Handlers report progress by writing to a shared
        dict that the pulse thread reads each cycle.

        Returns True if the pulse was written, False if the task is no
        longer RUNNING (e.g., reclaimed by janitor).
        """
        if progress:
            query = sql.SQL(
                "UPDATE {schema}.workflow_tasks "
                "SET last_pulse = NOW(), updated_at = NOW(), "
                "    result_data = jsonb_set("
                "        COALESCE(result_data, '{{}}'::jsonb), "
                "        '{{progress}}', "
                "        %s::jsonb"
                "    ) "
                "WHERE task_instance_id = %s AND status = 'running'"
            ).format(schema=sql.Identifier(_SCHEMA))
            params = (progress, task_instance_id)
        else:
            query = sql.SQL(
                "UPDATE {schema}.workflow_tasks "
                "SET last_pulse = NOW(), updated_at = NOW() "
                "WHERE task_instance_id = %s AND status = 'running'"
            ).format(schema=sql.Identifier(_SCHEMA))
            params = (task_instance_id,)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    updated = cur.rowcount > 0
                conn.commit()
            return updated
        except psycopg.Error as exc:
            logger.warning("DB error in update_workflow_task_pulse: %s", exc)
            return False

    def complete_workflow_task(
        self, task_instance_id: str, result_data: dict
    ) -> None:
        """
        Mark a workflow task as COMPLETED with result data.

        Spec: D.6 — Worker writes result after handler execution.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'completed', "
            "    result_data = %s::jsonb, "
            "    claimed_by = NULL, "
            "    completed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE task_instance_id = %s "
            "AND status = 'running'"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (result_data, task_instance_id))
                    if cur.rowcount == 0:
                        logger.warning(
                            "complete_workflow_task: CAS rejected — task no longer RUNNING: "
                            "task_instance_id=%s (may have been reclaimed by janitor)",
                            task_instance_id,
                        )
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "complete_workflow_task: task_instance_id=%s elapsed_ms=%.1f",
                task_instance_id, elapsed_ms,
            )
        except psycopg.Error as exc:
            logger.error("DB error in complete_workflow_task: %s", exc)
            raise DatabaseError(
                f"Failed to complete workflow task {task_instance_id}: {exc}"
            ) from exc

    def aggregate_fan_in(
        self, task_instance_id: str, result_data: dict
    ) -> None:
        """
        Complete a fan-in task with aggregated result data.

        Transitions from READY → COMPLETED. Fan-in tasks must be promoted
        to READY by the transition engine before aggregation.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'completed', "
            "    result_data = %s::jsonb, "
            "    completed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE task_instance_id = %s "
            "AND status = 'ready'"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (result_data, task_instance_id))
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "aggregate_fan_in: task_instance_id=%s elapsed_ms=%.1f",
                task_instance_id, elapsed_ms,
            )
        except psycopg.Error as exc:
            logger.error("DB error in aggregate_fan_in: %s", exc)
            raise DatabaseError(
                f"Failed to aggregate fan-in {task_instance_id}: {exc}"
            ) from exc

    def fail_workflow_task(
        self, task_instance_id: str, error_details: str
    ) -> None:
        """
        Mark a workflow task as FAILED with error details.

        Spec: D.6 — Worker writes error after handler failure.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'failed', "
            "    error_details = %s, "
            "    claimed_by = NULL, "
            "    completed_at = NOW(), "
            "    updated_at = NOW() "
            "WHERE task_instance_id = %s "
            "AND status = 'running'"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (error_details, task_instance_id))
                    if cur.rowcount == 0:
                        logger.warning(
                            "fail_workflow_task: CAS rejected — task no longer RUNNING: "
                            "task_instance_id=%s (may have been reclaimed by janitor)",
                            task_instance_id,
                        )
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "fail_workflow_task: task_instance_id=%s elapsed_ms=%.1f",
                task_instance_id, elapsed_ms,
            )
        except psycopg.Error as exc:
            logger.error("DB error in fail_workflow_task: %s", exc)
            raise DatabaseError(
                f"Failed to fail workflow task {task_instance_id}: {exc}"
            ) from exc

    def release_workflow_task(
        self, task_instance_id: str, worker_id: str
    ) -> None:
        """
        Release a claimed workflow task back to READY (graceful shutdown).

        Spec: D.6 — Worker releases on shutdown, only if still claimed by this worker.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'ready', "
            "    claimed_by = NULL, "
            "    started_at = NULL, "
            "    last_pulse = NULL, "
            "    updated_at = NOW() "
            "WHERE task_instance_id = %s "
            "AND status = 'running' "
            "AND claimed_by = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (task_instance_id, worker_id))
                conn.commit()
        except psycopg.Error as exc:
            logger.warning(
                "release_workflow_task failed (non-fatal): task=%s error=%s",
                task_instance_id, exc,
            )

    # =========================================================================
    # D.7 — JANITOR: STALE TASK DETECTION + RETRY
    # =========================================================================

    def get_stale_workflow_tasks(
        self, stale_threshold_seconds: int = 120, limit: int = 50
    ) -> list[dict]:
        """
        Find RUNNING workflow tasks with stale heartbeats.

        Spec: D.7 — Janitor scans for tasks where last_pulse (or started_at
        if last_pulse is NULL) is older than stale_threshold_seconds.
        """
        query = sql.SQL(
            "SELECT wt.task_instance_id, wt.task_name, wt.retry_count, wt.max_retries, "
            "       wt.last_pulse, wt.started_at, "
            "       EXTRACT(EPOCH FROM (NOW() - COALESCE(wt.last_pulse, wt.started_at))) AS seconds_stuck "
            "FROM {schema}.workflow_tasks wt "
            "JOIN {schema}.workflow_runs wr ON wr.run_id = wt.run_id "
            "WHERE wt.status = 'running' "
            "  AND wt.handler NOT IN ('__conditional__', '__fan_out__', '__fan_in__', '__gate__') "
            "  AND wr.status != 'awaiting_approval' "
            "  AND ( "
            "    (wt.last_pulse IS NOT NULL AND wt.last_pulse < NOW() - make_interval(secs => %s)) "
            "    OR "
            "    (wt.last_pulse IS NULL AND wt.started_at IS NOT NULL AND wt.started_at < NOW() - make_interval(secs => %s)) "
            "  ) "
            "ORDER BY COALESCE(wt.last_pulse, wt.started_at) ASC "
            "LIMIT %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (stale_threshold_seconds, stale_threshold_seconds, limit))
                    rows = cur.fetchall()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug(
                "get_stale_workflow_tasks: found=%d threshold=%ds elapsed_ms=%.1f",
                len(rows), stale_threshold_seconds, elapsed_ms,
            )
            return rows

        except psycopg.Error as exc:
            logger.error("DB error in get_stale_workflow_tasks: %s", exc)
            raise DatabaseError(f"Failed to query stale workflow tasks: {exc}") from exc

    def retry_workflow_task(
        self,
        task_instance_id: str,
        backoff_seconds: int = 30,
        error_details: Optional[str] = None,
    ) -> bool:
        """
        Reset a RUNNING workflow task for retry with exponential backoff.

        Used by both the janitor (stale task reclamation) and the worker
        (handler failure with retries remaining). Atomically: increment
        retry_count, set status='ready', set execute_after for backoff,
        clear claimed_by/last_pulse.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'ready', "
            "    retry_count = retry_count + 1, "
            "    execute_after = NOW() + make_interval(secs => %s), "
            "    claimed_by = NULL, "
            "    last_pulse = NULL, "
            "    started_at = NULL, "
            "    error_details = %s, "
            "    updated_at = NOW() "
            "WHERE task_instance_id = %s "
            "AND status = 'running' "
            "AND retry_count < max_retries"
        ).format(schema=sql.Identifier(_SCHEMA))

        error_msg = error_details or f"Retry (backoff={backoff_seconds}s)"
        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (backoff_seconds, error_msg, task_instance_id))
                    updated = cur.rowcount == 1
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if updated:
                logger.info(
                    "retry_workflow_task: task=%s backoff=%ds elapsed_ms=%.1f",
                    task_instance_id, backoff_seconds, elapsed_ms,
                )
            return updated

        except psycopg.Error as exc:
            logger.error("DB error in retry_workflow_task: %s", exc)
            raise DatabaseError(f"Failed to retry workflow task {task_instance_id}: {exc}") from exc

    def get_stale_legacy_tasks(
        self, stale_threshold_seconds: int = 120, limit: int = 50
    ) -> list[dict]:
        """
        Find PROCESSING legacy tasks (app.tasks) with stale heartbeats.

        Spec: D.7 — Janitor also covers legacy tasks, taking over from
        the Function App's system_guardian_sweep timer trigger.
        """
        query = sql.SQL(
            "SELECT task_id, task_type, retry_count, last_pulse, "
            "       execution_started_at, "
            "       EXTRACT(EPOCH FROM (NOW() - COALESCE(last_pulse, execution_started_at))) AS seconds_stuck "
            "FROM {schema}.tasks "
            "WHERE status = 'processing' "
            "  AND ( "
            "    (last_pulse IS NOT NULL AND last_pulse < NOW() - make_interval(secs => %s)) "
            "    OR "
            "    (last_pulse IS NULL AND execution_started_at IS NOT NULL "
            "     AND execution_started_at < NOW() - make_interval(secs => %s)) "
            "  ) "
            "ORDER BY COALESCE(last_pulse, execution_started_at) ASC "
            "LIMIT %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (stale_threshold_seconds, stale_threshold_seconds, limit))
                    rows = cur.fetchall()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.debug(
                "get_stale_legacy_tasks: found=%d threshold=%ds elapsed_ms=%.1f",
                len(rows), stale_threshold_seconds, elapsed_ms,
            )
            return rows

        except psycopg.Error as exc:
            logger.error("DB error in get_stale_legacy_tasks: %s", exc)
            raise DatabaseError(f"Failed to query stale legacy tasks: {exc}") from exc

    def complete_gate_node(
        self,
        run_id: str,
        gate_node_name: str,
        result_data: dict,
    ) -> bool:
        """
        Complete a gate node from external signal (e.g., approval API).

        Transitions the gate task from WAITING → COMPLETED and the
        workflow run from AWAITING_APPROVAL → RUNNING so the Brain
        resumes processing downstream nodes.

        Args:
            run_id: Workflow run ID
            gate_node_name: Name of the gate node (e.g., "approval_gate")
            result_data: Result dict to store on the task (contains decision, clearance_state, etc.)

        Returns:
            True if gate was completed, False if not found or wrong state
        """
        task_sql = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = %s, result_data = %s::jsonb, "
            "    completed_at = NOW(), updated_at = NOW() "
            "WHERE run_id = %s AND task_name = %s AND status = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        run_sql = sql.SQL(
            "UPDATE {schema}.workflow_runs "
            "SET status = %s "
            "WHERE run_id = %s AND status = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        task_sql,
                        (
                            WorkflowTaskStatus.COMPLETED.value,
                            result_data,
                            run_id,
                            gate_node_name,
                            WorkflowTaskStatus.WAITING.value,
                        ),
                    )
                    task_updated = cur.rowcount

                    if task_updated == 1:
                        cur.execute(
                            run_sql,
                            (
                                WorkflowRunStatus.RUNNING.value,
                                run_id,
                                WorkflowRunStatus.AWAITING_APPROVAL.value,
                            ),
                        )
                        run_updated = cur.rowcount
                        if run_updated == 0:
                            logger.warning(
                                "complete_gate_node: task completed but run status guard rejected "
                                "(run_id=%s, may not be in AWAITING_APPROVAL)", run_id
                            )

                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if task_updated == 1:
                logger.info(
                    "complete_gate_node: run_id=%s gate=%r "
                    "waiting→completed awaiting_approval→running elapsed_ms=%.1f",
                    run_id, gate_node_name, elapsed_ms,
                )
                return True
            else:
                logger.debug(
                    "complete_gate_node: guard rejected — run_id=%s gate=%r "
                    "(not found or not in waiting state)",
                    run_id, gate_node_name,
                )
                return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in complete_gate_node: run_id=%s gate=%r error=%s",
                run_id, gate_node_name, exc,
            )
            raise DatabaseError(
                f"Failed to complete gate node (run_id={run_id}, gate={gate_node_name!r}): {exc}"
            ) from exc

    def skip_gate_node(
        self,
        run_id: str,
        gate_node_name: str,
        result_data: dict,
    ) -> bool:
        """
        Skip a gate node (rejection path). Downstream nodes will be
        skip-propagated by the transition engine on next Brain poll.

        Transitions gate: WAITING → SKIPPED, run: AWAITING_APPROVAL → RUNNING.

        Args:
            run_id: Workflow run ID
            gate_node_name: Name of the gate node (e.g., "approval_gate")
            result_data: Result dict to store on the task (contains decision, reason, etc.)

        Returns:
            True if gate was skipped, False if not found or wrong state
        """
        task_sql = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = %s, result_data = %s::jsonb, "
            "    completed_at = NOW(), updated_at = NOW() "
            "WHERE run_id = %s AND task_name = %s AND status = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        run_sql = sql.SQL(
            "UPDATE {schema}.workflow_runs "
            "SET status = %s "
            "WHERE run_id = %s AND status = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        task_sql,
                        (
                            WorkflowTaskStatus.SKIPPED.value,
                            result_data,
                            run_id,
                            gate_node_name,
                            WorkflowTaskStatus.WAITING.value,
                        ),
                    )
                    task_updated = cur.rowcount

                    if task_updated == 1:
                        cur.execute(
                            run_sql,
                            (
                                WorkflowRunStatus.RUNNING.value,
                                run_id,
                                WorkflowRunStatus.AWAITING_APPROVAL.value,
                            ),
                        )
                        run_updated = cur.rowcount
                        if run_updated == 0:
                            logger.warning(
                                "skip_gate_node: task skipped but run status guard rejected "
                                "(run_id=%s, may not be in AWAITING_APPROVAL)", run_id
                            )

                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if task_updated == 1:
                logger.info(
                    "skip_gate_node: run_id=%s gate=%r "
                    "waiting→skipped awaiting_approval→running elapsed_ms=%.1f",
                    run_id, gate_node_name, elapsed_ms,
                )
                return True
            else:
                logger.debug(
                    "skip_gate_node: guard rejected — run_id=%s gate=%r "
                    "(not found or not in waiting state)",
                    run_id, gate_node_name,
                )
                return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in skip_gate_node: run_id=%s gate=%r error=%s",
                run_id, gate_node_name, exc,
            )
            raise DatabaseError(
                f"Failed to skip gate node (run_id={run_id}, gate={gate_node_name!r}): {exc}"
            ) from exc

    def get_release_for_waiting_run(self, run_id: str) -> Optional[dict]:
        """
        Look up the asset_release linked to a workflow run via workflow_id.

        Used by the Brain's gate reconciliation loop to check approval_state
        on releases linked to AWAITING_APPROVAL runs.

        Args:
            run_id: Workflow run ID (matches asset_releases.workflow_id)

        Returns:
            Dict with release_id, approval_state, clearance_state, processing_status,
            workflow_id, reviewer, version_id — or None if no release is linked.
        """
        query = sql.SQL(
            "SELECT release_id, approval_state, clearance_state, "
            "       processing_status, workflow_id, reviewer, version_id "
            "FROM {schema}.{table} "
            "WHERE workflow_id = %s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier("asset_releases"),
        )

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (run_id,))
                    row = cur.fetchone()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if row is None:
                logger.debug(
                    "get_release_for_waiting_run: no release linked to run_id=%s elapsed_ms=%.1f",
                    run_id, elapsed_ms,
                )
                return None

            logger.debug(
                "get_release_for_waiting_run: run_id=%s release_id=%s "
                "approval_state=%s elapsed_ms=%.1f",
                run_id, row["release_id"], row["approval_state"], elapsed_ms,
            )
            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in get_release_for_waiting_run: run_id=%s error=%s",
                run_id, exc,
            )
            raise DatabaseError(
                f"Failed to fetch release for waiting run (run_id={run_id}): {exc}"
            ) from exc

    def update_run_status(self, run_id: str, status: WorkflowRunStatus) -> bool:
        """
        Transition a workflow run to a new status with valid-transition guard.

        Spec: D.5 — WorkflowRunRepository.update_run_status. Only the following
        transitions are permitted (guarded via WHERE clause):

          pending            → running            (first task claimed; sets started_at)
          running            → completed          (all tasks terminal, no failures; sets completed_at)
          running            → failed             (at least one task failed/cancelled; sets completed_at)
          running            → awaiting_approval  (suspended at gate node)
          awaiting_approval  → running            (gate approved; resumes run)

        Any other combination (e.g. pending→completed, running→pending) is rejected
        by returning False without touching the database.

        started_at is set only on the pending→running transition.
        completed_at is set only on terminal transitions (completed, failed).

        Note: WorkflowRun model does NOT have an updated_at column — only
        started_at and completed_at are used here.

        Parameters
        ----------
        run_id:
            Primary key of the workflow run to update.
        status:
            Target status. Must be RUNNING, COMPLETED, FAILED, or AWAITING_APPROVAL.

        Returns
        -------
        bool
            True if the run was updated.
            False if the transition was guard-rejected (invalid or already done).

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        # Build the correct SQL based on target status
        if status == WorkflowRunStatus.RUNNING:
            # pending → running: set started_at
            # awaiting_approval → running: resume after gate approval (no started_at update)
            query = sql.SQL(
                "UPDATE {schema}.workflow_runs "
                "SET status = 'running', "
                "    started_at = CASE WHEN status = 'pending' THEN NOW() ELSE started_at END "
                "WHERE run_id = %s AND status IN ('pending', 'awaiting_approval')"
            ).format(schema=sql.Identifier(_SCHEMA))
            params = (run_id,)
            allowed_from = "pending|awaiting_approval"

        elif status == WorkflowRunStatus.AWAITING_APPROVAL:
            # running → awaiting_approval: suspend at gate node
            query = sql.SQL(
                "UPDATE {schema}.workflow_runs "
                "SET status = 'awaiting_approval' "
                "WHERE run_id = %s AND status = 'running'"
            ).format(schema=sql.Identifier(_SCHEMA))
            params = (run_id,)
            allowed_from = "running"

        elif status in (WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED):
            # running → completed | failed: set completed_at
            query = sql.SQL(
                "UPDATE {schema}.workflow_runs "
                "SET status = %s, completed_at = NOW() "
                "WHERE run_id = %s AND status = 'running'"
            ).format(schema=sql.Identifier(_SCHEMA))
            params = (status.value, run_id)
            allowed_from = "running"

        else:
            # PENDING is not a valid target — guard at Python level
            logger.debug(
                "update_run_status: guard rejected — invalid target status=%s for run_id=%s",
                status.value, run_id,
            )
            return False

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    updated = cur.rowcount
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            if updated == 1:
                logger.info(
                    "update_run_status: run_id=%s %s→%s elapsed_ms=%.1f",
                    run_id, allowed_from, status.value, elapsed_ms,
                )
                return True
            else:
                logger.debug(
                    "update_run_status: guard rejected — run_id=%s expected_status=%s "
                    "(already transitioned or not found)",
                    run_id, allowed_from,
                )
                return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in update_run_status: run_id=%s target_status=%s error=%s",
                run_id, status.value, exc,
            )
            raise DatabaseError(
                f"Failed to update run status (run_id={run_id}, status={status.value}): {exc}"
            ) from exc


# ============================================================================
# PRIVATE PARAMETER BUILDERS
# ============================================================================
# Kept private (module-level) so they can be unit-tested without instantiating
# the repository. Each returns a plain tuple matching the INSERT column order.


def _run_to_params(run: WorkflowRun) -> tuple:
    """
    Serialize WorkflowRun to a tuple matching run_insert_sql column order.

    Spec: insert_run_atomic — parameter construction for the workflow_runs INSERT.
    JSONB columns (parameters, definition, result_data) are passed as Python
    dicts/lists; psycopg3's JsonbBinaryDumper (registered via register_type_adapters)
    handles serialization automatically.
    """
    return (
        run.run_id,
        run.workflow_name,
        run.parameters,
        run.status.value,
        run.definition,
        run.platform_version,
        run.result_data if run.result_data is not None else None,
        run.created_at,
        run.started_at,
        run.completed_at,
        run.request_id,
        run.asset_id,
        run.release_id,
        run.legacy_job_id,
        run.schedule_id,
    )


def _task_to_params(task: WorkflowTask) -> tuple:
    """
    Serialize WorkflowTask to a tuple matching task_insert_sql column order.

    Spec: insert_run_atomic — parameter construction for the workflow_tasks INSERT.
    JSONB columns passed as Python dicts/lists; psycopg3 handles serialization
    via JsonbBinaryDumper. None values passed as NULL.
    """
    return (
        task.task_instance_id,
        task.run_id,
        task.task_name,
        task.handler,
        task.status.value,
        task.fan_out_index,
        task.fan_out_source,
        task.when_clause,
        task.parameters if task.parameters is not None else None,
        task.result_data if task.result_data is not None else None,
        task.error_details,
        task.retry_count,
        task.max_retries,
        task.claimed_by,
        task.last_pulse,
        task.execute_after,
        task.started_at,
        task.completed_at,
        task.created_at,
        task.updated_at,
    )


def _dep_to_params(dep: WorkflowTaskDep) -> tuple:
    """
    Serialize WorkflowTaskDep to a tuple matching dep_insert_sql column order.

    Spec: insert_run_atomic — parameter construction for the workflow_task_deps INSERT.
    """
    return (
        dep.task_instance_id,
        dep.depends_on_instance_id,
        dep.optional,
    )


# ============================================================================
# D.6 — WORKER CLAIM / COMPLETE / RELEASE FOR WORKFLOW TASKS
# ============================================================================


def _workflow_task_from_row(row: dict) -> WorkflowTask:
    """Construct WorkflowTask from a dict_row result."""
    return WorkflowTask(
        task_instance_id=row["task_instance_id"],
        run_id=row["run_id"],
        task_name=row["task_name"],
        handler=row["handler"],
        status=WorkflowTaskStatus(row["status"]),
        fan_out_index=row.get("fan_out_index"),
        fan_out_source=row.get("fan_out_source"),
        when_clause=row.get("when_clause"),
        parameters=row.get("parameters"),
        result_data=row.get("result_data"),
        error_details=row.get("error_details"),
        retry_count=row.get("retry_count", 0),
        max_retries=row.get("max_retries", 3),
        claimed_by=row.get("claimed_by"),
    )


# ============================================================================
# D.7 — JANITOR: STALE TASK DETECTION + RETRY
# ============================================================================


def _get_stale_query(schema: str, table: str, status_col: str, status_val: str,
                     pulse_col: str, started_col: str, id_col: str) -> sql.Composed:
    """Build a parameterized stale-task detection query."""
    return sql.SQL(
        "SELECT {id_col}, task_name, retry_count, max_retries, {pulse_col}, {started_col} "
        "FROM {schema}.{table} "
        "WHERE status = {status_val} "
        "  AND ( "
        "    ({pulse_col} IS NOT NULL AND {pulse_col} < NOW() - make_interval(secs => %s)) "
        "    OR "
        "    ({pulse_col} IS NULL AND {started_col} IS NOT NULL AND {started_col} < NOW() - make_interval(secs => %s)) "
        "  ) "
        "ORDER BY COALESCE({pulse_col}, {started_col}) ASC "
        "LIMIT %s"
    ).format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
        id_col=sql.Identifier(id_col),
        pulse_col=sql.Identifier(pulse_col),
        started_col=sql.Identifier(started_col),
        status_val=sql.Literal(status_val),
    )
