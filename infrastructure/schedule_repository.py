# ============================================================================
# CLAUDE CONTEXT - SCHEDULE REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - Database access for app.schedules
# PURPOSE: CRUD operations for scheduled workflow execution records
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: ScheduleRepository
# DEPENDENCIES: psycopg, infrastructure.db_auth, infrastructure.db_connections
# ============================================================================
"""
ScheduleRepository — CRUD access to app.schedules.

All SQL uses psycopg.sql.SQL() and sql.Identifier() — never f-strings.
All queries return plain dicts via dict_row cursor factory (Standard 6.1).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from exceptions import DatabaseError
from infrastructure.db_auth import ManagedIdentityAuth
from infrastructure.db_connections import ConnectionManager

logger = logging.getLogger(__name__)

_SCHEMA = "app"
_TABLE = "schedules"

# All columns in table-definition order — used by SELECT * equivalent
_ALL_COLUMNS = (
    "schedule_id",
    "workflow_name",
    "parameters",
    "description",
    "cron_expression",
    "status",
    "last_run_at",
    "last_run_id",
    "max_concurrent",
    "created_at",
    "updated_at",
)

_SELECT_COLS = ", ".join(_ALL_COLUMNS)


class ScheduleRepository:
    """
    CRUD repository for app.schedules.

    Uses ConnectionManager(ManagedIdentityAuth()) — same auth path as all
    other repositories in this project. All SQL is composed via psycopg.sql;
    f-strings are never used for SQL construction.
    """

    def __init__(self) -> None:
        self._cm = ConnectionManager(ManagedIdentityAuth())

    # =========================================================================
    # WRITE: CREATE
    # =========================================================================

    def create(
        self,
        schedule_id: str,
        workflow_name: str,
        parameters: dict,
        cron_expression: str,
        description: Optional[str] = None,
        max_concurrent: int = 1,
    ) -> dict:
        """
        Insert a new schedule row.

        Returns the created row as a dict.
        Raises DatabaseError on any psycopg.Error.
        """
        insert_sql = sql.SQL(
            "INSERT INTO {schema}.{table} ("
            "schedule_id, workflow_name, parameters, description, "
            "cron_expression, status, last_run_at, last_run_id, "
            "max_concurrent, created_at, updated_at"
            ") VALUES ("
            "%s, %s, %s::jsonb, %s, %s, %s, NULL, NULL, %s, NOW(), NOW()"
            ") RETURNING " + _SELECT_COLS
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        params = (
            schedule_id,
            workflow_name,
            json.dumps(parameters),
            description,
            cron_expression,
            "active",
            max_concurrent,
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(insert_sql, params)
                    row = cur.fetchone()
                conn.commit()

            logger.info(
                "ScheduleRepository.create: schedule_id=%s workflow=%s",
                schedule_id, workflow_name,
            )
            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.create: schedule_id=%s error=%s",
                schedule_id, exc,
            )
            raise DatabaseError(
                f"Failed to create schedule (schedule_id={schedule_id}): {exc}"
            ) from exc

    # =========================================================================
    # READ: GET BY ID
    # =========================================================================

    def get_by_id(self, schedule_id: str) -> Optional[dict]:
        """
        Fetch a schedule by primary key.

        Returns a dict if found, None if not found.
        Raises DatabaseError on any psycopg.Error.
        """
        query = sql.SQL(
            "SELECT " + _SELECT_COLS + " "
            "FROM {schema}.{table} "
            "WHERE schedule_id = %s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (schedule_id,))
                    row = cur.fetchone()

            if row is None:
                return None

            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.get_by_id: schedule_id=%s error=%s",
                schedule_id, exc,
            )
            raise DatabaseError(
                f"Failed to fetch schedule (schedule_id={schedule_id}): {exc}"
            ) from exc

    # =========================================================================
    # READ: LIST ALL / LIST ACTIVE
    # =========================================================================

    def list_all(self, status: Optional[str] = None) -> list[dict]:
        """
        Return all schedules, optionally filtered by status.

        Args:
            status: If provided, filter to rows matching this status value
                    (e.g. 'active', 'paused', 'disabled').

        Returns a list of dicts ordered by created_at DESC.
        Raises DatabaseError on any psycopg.Error.
        """
        if status is not None:
            query = sql.SQL(
                "SELECT " + _SELECT_COLS + " "
                "FROM {schema}.{table} "
                "WHERE status = %s "
                "ORDER BY created_at DESC"
            ).format(
                schema=sql.Identifier(_SCHEMA),
                table=sql.Identifier(_TABLE),
            )
            params = (status,)
        else:
            query = sql.SQL(
                "SELECT " + _SELECT_COLS + " "
                "FROM {schema}.{table} "
                "ORDER BY created_at DESC"
            ).format(
                schema=sql.Identifier(_SCHEMA),
                table=sql.Identifier(_TABLE),
            )
            params = ()

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

            logger.debug(
                "ScheduleRepository.list_all: status=%s count=%d",
                status, len(rows),
            )
            return [dict(r) for r in rows]

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.list_all: status=%s error=%s",
                status, exc,
            )
            raise DatabaseError(
                f"Failed to list schedules (status={status}): {exc}"
            ) from exc

    def list_active(self) -> list[dict]:
        """
        Return all schedules with status='active'.

        Uses the partial index idx_schedules_active for efficiency.
        Returns a list of dicts ordered by created_at DESC.
        Raises DatabaseError on any psycopg.Error.
        """
        return self.list_all(status="active")

    # =========================================================================
    # WRITE: UPDATE
    # =========================================================================

    def update(self, schedule_id: str, **fields) -> Optional[dict]:
        """
        Update one or more columns on a schedule row.

        Only the following fields may be updated: workflow_name, parameters,
        description, cron_expression, status, max_concurrent.
        updated_at is always set to NOW().

        Returns the updated row as a dict, or None if schedule_id not found.
        Raises DatabaseError on any psycopg.Error.
        Raises ValueError if no valid fields are provided.
        """
        _ALLOWED = frozenset({
            "workflow_name",
            "parameters",
            "description",
            "cron_expression",
            "status",
            "max_concurrent",
        })

        updates = {k: v for k, v in fields.items() if k in _ALLOWED}
        if not updates:
            raise ValueError(
                f"update() called with no valid fields. "
                f"Allowed: {sorted(_ALLOWED)}. Got: {sorted(fields)}"
            )

        # Build SET clause: col = %s, ..., updated_at = NOW()
        set_fragments = []
        params = []

        for col, val in updates.items():
            if col == "parameters":
                set_fragments.append(
                    sql.SQL("{col} = %s::jsonb").format(col=sql.Identifier(col))
                )
                params.append(json.dumps(val))
            else:
                set_fragments.append(
                    sql.SQL("{col} = %s").format(col=sql.Identifier(col))
                )
                params.append(val)

        set_fragments.append(sql.SQL("updated_at = NOW()"))
        params.append(schedule_id)

        query = sql.SQL(
            "UPDATE {schema}.{table} SET {sets} "
            "WHERE schedule_id = %s "
            "RETURNING " + _SELECT_COLS
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
            sets=sql.SQL(", ").join(set_fragments),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()
                conn.commit()

            if row is None:
                logger.debug(
                    "ScheduleRepository.update: not found schedule_id=%s", schedule_id
                )
                return None

            logger.info(
                "ScheduleRepository.update: schedule_id=%s fields=%s",
                schedule_id, sorted(updates),
            )
            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.update: schedule_id=%s error=%s",
                schedule_id, exc,
            )
            raise DatabaseError(
                f"Failed to update schedule (schedule_id={schedule_id}): {exc}"
            ) from exc

    # =========================================================================
    # WRITE: DELETE
    # =========================================================================

    def delete(self, schedule_id: str) -> bool:
        """
        Delete a schedule by primary key.

        Returns True if a row was deleted, False if schedule_id was not found.
        Raises DatabaseError on any psycopg.Error.
        """
        query = sql.SQL(
            "DELETE FROM {schema}.{table} WHERE schedule_id = %s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (schedule_id,))
                    deleted = cur.rowcount
                conn.commit()

            if deleted == 1:
                logger.info(
                    "ScheduleRepository.delete: deleted schedule_id=%s", schedule_id
                )
                return True

            logger.debug(
                "ScheduleRepository.delete: not found schedule_id=%s", schedule_id
            )
            return False

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.delete: schedule_id=%s error=%s",
                schedule_id, exc,
            )
            raise DatabaseError(
                f"Failed to delete schedule (schedule_id={schedule_id}): {exc}"
            ) from exc

    # =========================================================================
    # WRITE: RECORD RUN (atomic post-fire update)
    # =========================================================================

    def record_run(self, schedule_id: str, run_id: str) -> None:
        """
        Atomically update last_run_at = NOW() and last_run_id after firing.

        Called by the scheduler immediately after successfully submitting
        a workflow_run for this schedule.
        Raises DatabaseError on any psycopg.Error.
        """
        query = sql.SQL(
            "UPDATE {schema}.{table} "
            "SET last_run_at = NOW(), "
            "    last_run_id = %s, "
            "    updated_at = NOW() "
            "WHERE schedule_id = %s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (run_id, schedule_id))
                conn.commit()

            logger.info(
                "ScheduleRepository.record_run: schedule_id=%s run_id=%s",
                schedule_id, run_id,
            )

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.record_run: "
                "schedule_id=%s run_id=%s error=%s",
                schedule_id, run_id, exc,
            )
            raise DatabaseError(
                f"Failed to record run for schedule "
                f"(schedule_id={schedule_id}, run_id={run_id}): {exc}"
            ) from exc

    # =========================================================================
    # READ: ACTIVE RUN COUNT (concurrency guard)
    # =========================================================================

    def get_active_run_count(self, schedule_id: str) -> int:
        """
        Count workflow_runs for this schedule that are in pending or running status.

        Used by the scheduler to enforce max_concurrent before firing.
        Queries workflow_runs.schedule_id directly — works for any max_concurrent value.

        Returns the count (int >= 0).
        Raises DatabaseError on any psycopg.Error.
        """
        query = sql.SQL(
            "SELECT COUNT(*) AS run_count "
            "FROM {schema}.{runs_table} "
            "WHERE schedule_id = %s "
            "  AND status IN ('pending', 'running')"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            runs_table=sql.Identifier("workflow_runs"),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (schedule_id,))
                    row = cur.fetchone()

            count = row["run_count"] if row else 0
            logger.debug(
                "ScheduleRepository.get_active_run_count: schedule_id=%s count=%d",
                schedule_id, count,
            )
            return int(count)

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduleRepository.get_active_run_count: "
                "schedule_id=%s error=%s",
                schedule_id, exc,
            )
            raise DatabaseError(
                f"Failed to count active runs for schedule "
                f"(schedule_id={schedule_id}): {exc}"
            ) from exc


__all__ = ["ScheduleRepository"]
