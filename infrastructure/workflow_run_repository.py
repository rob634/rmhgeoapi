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

import json
import logging
import time
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

logger = logging.getLogger(__name__)

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
            "request_id, asset_id, release_id, legacy_job_id"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
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
            "request_id, asset_id, release_id, legacy_job_id "
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
            "SELECT task_instance_id, task_name, status, result_data, "
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

        No guard is applied on the current status — the caller (orchestrator or
        worker) is responsible for only calling this on tasks in RUNNING state.

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
            "WHERE task_instance_id = %s"
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
                        # Mark template as expanded
                        cur.execute(expand_sql, (template_id,))

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

    def aggregate_fan_in(
        self, task_instance_id: str, result_data: dict
    ) -> None:
        """
        Store aggregated fan-in results and mark the task COMPLETED.

        Spec: D.5 — WorkflowRunRepository.aggregate_fan_in. Called by
        DAGOrchestrator after it has collected and merged the result_data from
        all upstream fan-out child instances using the configured AggregationMode.
        The merged dict is stored as JSONB.

        Parameters
        ----------
        task_instance_id:
            Primary key of the fan-in task to finalize.
        result_data:
            Merged results dict to store. Must be JSON-serializable.

        Raises
        ------
        DatabaseError
            On any psycopg.Error.
        """
        query = sql.SQL(
            "UPDATE {schema}.workflow_tasks "
            "SET status = 'completed', result_data = %s::jsonb, "
            "completed_at = NOW(), updated_at = NOW() "
            "WHERE task_instance_id = %s"
        ).format(schema=sql.Identifier(_SCHEMA))

        t0 = time.perf_counter()
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (json.dumps(result_data), task_instance_id),
                    )
                conn.commit()

            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "aggregate_fan_in: task_instance_id=%s elapsed_ms=%.1f",
                task_instance_id, elapsed_ms,
            )

        except psycopg.Error as exc:
            logger.error(
                "DB error in aggregate_fan_in: task_instance_id=%s error=%s",
                task_instance_id, exc,
            )
            raise DatabaseError(
                f"Failed to aggregate fan-in (task_instance_id={task_instance_id}): {exc}"
            ) from exc

    def update_run_status(self, run_id: str, status: WorkflowRunStatus) -> bool:
        """
        Transition a workflow run to a new status with valid-transition guard.

        Spec: D.5 — WorkflowRunRepository.update_run_status. Only the following
        transitions are permitted (guarded via WHERE clause):

          pending  → running     (first task claimed; sets started_at)
          running  → completed   (all tasks terminal, no failures; sets completed_at)
          running  → failed      (at least one task failed/cancelled; sets completed_at)

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
            Target status. Must be RUNNING, COMPLETED, or FAILED.

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
            query = sql.SQL(
                "UPDATE {schema}.workflow_runs "
                "SET status = 'running', started_at = NOW() "
                "WHERE run_id = %s AND status = 'pending'"
            ).format(schema=sql.Identifier(_SCHEMA))
            params = (run_id,)
            allowed_from = "pending"

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
    JSONB columns (parameters, definition, result_data) are serialized to JSON strings
    so psycopg passes them as text, letting PostgreSQL cast to JSONB.
    """
    return (
        run.run_id,
        run.workflow_name,
        json.dumps(run.parameters),
        run.status.value,
        json.dumps(run.definition),
        run.platform_version,
        json.dumps(run.result_data) if run.result_data is not None else None,
        run.created_at,
        run.started_at,
        run.completed_at,
        run.request_id,
        run.asset_id,
        run.release_id,
        run.legacy_job_id,
    )


def _task_to_params(task: WorkflowTask) -> tuple:
    """
    Serialize WorkflowTask to a tuple matching task_insert_sql column order.

    Spec: insert_run_atomic — parameter construction for the workflow_tasks INSERT.
    JSONB columns serialized to JSON strings; None values passed as NULL.
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
        json.dumps(task.parameters) if task.parameters is not None else None,
        json.dumps(task.result_data) if task.result_data is not None else None,
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
