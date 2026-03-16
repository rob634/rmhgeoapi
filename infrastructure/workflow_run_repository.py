# ============================================================================
# CLAUDE CONTEXT - WORKFLOW RUN REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - Atomic DB operations for workflow DAG tables
# PURPOSE: Insert WorkflowRun + WorkflowTask + WorkflowTaskDep atomically in one
#          transaction; provide idempotent-safe UniqueViolation handling and
#          simple run lookup by PK.
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowRunRepository
# DEPENDENCIES: psycopg, psycopg.sql, psycopg.errors, psycopg.rows,
#               infrastructure.postgresql, core.models.workflow_run,
#               core.models.workflow_task, core.models.workflow_task_dep,
#               exceptions
# ============================================================================

import json
import logging
from typing import Optional

import psycopg
import psycopg.errors
from psycopg import sql
from psycopg.rows import dict_row

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
