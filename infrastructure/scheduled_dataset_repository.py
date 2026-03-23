# ============================================================================
# CLAUDE CONTEXT - SCHEDULED DATASET REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - Database access for app.scheduled_datasets
# PURPOSE: CRUD operations for schedule-managed PostGIS dataset records
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: ScheduledDatasetRepository
# DEPENDENCIES: psycopg, infrastructure.db_auth, infrastructure.db_connections
# ============================================================================
"""
ScheduledDatasetRepository — CRUD access to app.scheduled_datasets.

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
_TABLE = "scheduled_datasets"

_ALL_COLUMNS = (
    "dataset_id",
    "table_name",
    "table_schema",
    "schedule_id",
    "description",
    "source_type",
    "column_schema",
    "rebuild_strategy",
    "credential_key",
    "row_count",
    "last_sync_at",
    "last_sync_run_id",
    "created_at",
    "updated_at",
)

_SELECT_COLS = sql.SQL(", ").join(sql.Identifier(c) for c in _ALL_COLUMNS)


class ScheduledDatasetRepository:
    """
    CRUD repository for app.scheduled_datasets.

    Tracks PostGIS tables managed by scheduled workflows.
    """

    def __init__(self) -> None:
        self._cm = ConnectionManager(ManagedIdentityAuth())

    # =========================================================================
    # WRITE: CREATE
    # =========================================================================

    def create(
        self,
        dataset_id: str,
        table_name: str,
        table_schema: str = "geo",
        schedule_id: Optional[str] = None,
        description: Optional[str] = None,
        source_type: str = "api",
        column_schema: Optional[dict] = None,
        rebuild_strategy: str = "append",
        credential_key: Optional[str] = None,
    ) -> dict:
        """
        Register a new scheduled dataset.

        Returns the created row as a dict.
        Raises DatabaseError on any psycopg.Error.
        """
        insert_sql = sql.SQL(
            "INSERT INTO {schema}.{table} ("
            "dataset_id, table_name, table_schema, schedule_id, description, "
            "source_type, column_schema, rebuild_strategy, credential_key, "
            "row_count, last_sync_at, last_sync_run_id, created_at, updated_at"
            ") VALUES ("
            "%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, "
            "0, NULL, NULL, NOW(), NOW()"
            ") RETURNING {cols}"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
            cols=_SELECT_COLS,
        )

        params = (
            dataset_id,
            table_name,
            table_schema,
            schedule_id,
            description,
            source_type,
            json.dumps(column_schema or {}),
            rebuild_strategy,
            credential_key,
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(insert_sql, params)
                    row = cur.fetchone()
                conn.commit()

            logger.info(
                "ScheduledDatasetRepository.create: dataset_id=%s table=%s.%s",
                dataset_id, table_schema, table_name,
            )
            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.create: dataset_id=%s error=%s",
                dataset_id, exc,
            )
            raise DatabaseError(
                f"Failed to create scheduled dataset (dataset_id={dataset_id}): {exc}"
            ) from exc

    # =========================================================================
    # READ: GET BY ID
    # =========================================================================

    def get_by_id(self, dataset_id: str) -> Optional[dict]:
        """
        Fetch a scheduled dataset by primary key.

        Returns a dict if found, None if not found.
        """
        query = sql.SQL(
            "SELECT {cols} FROM {schema}.{table} WHERE dataset_id = %s"
        ).format(
            cols=_SELECT_COLS,
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (dataset_id,))
                    row = cur.fetchone()

            return dict(row) if row else None

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.get_by_id: dataset_id=%s error=%s",
                dataset_id, exc,
            )
            raise DatabaseError(
                f"Failed to fetch scheduled dataset (dataset_id={dataset_id}): {exc}"
            ) from exc

    # =========================================================================
    # READ: GET BY TABLE
    # =========================================================================

    def get_by_table(self, table_schema: str, table_name: str) -> Optional[dict]:
        """
        Fetch a scheduled dataset by its PostGIS table coordinates.

        Returns a dict if found, None if not found.
        """
        query = sql.SQL(
            "SELECT {cols} FROM {schema}.{table} "
            "WHERE table_schema = %s AND table_name = %s"
        ).format(
            cols=_SELECT_COLS,
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (table_schema, table_name))
                    row = cur.fetchone()

            return dict(row) if row else None

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.get_by_table: %s.%s error=%s",
                table_schema, table_name, exc,
            )
            raise DatabaseError(
                f"Failed to fetch scheduled dataset ({table_schema}.{table_name}): {exc}"
            ) from exc

    # =========================================================================
    # READ: LIST ALL
    # =========================================================================

    def list_all(self, schedule_id: Optional[str] = None) -> list[dict]:
        """
        Return all scheduled datasets, optionally filtered by schedule_id.

        Returns a list of dicts ordered by created_at DESC.
        """
        if schedule_id is not None:
            query = sql.SQL(
                "SELECT {cols} FROM {schema}.{table} "
                "WHERE schedule_id = %s ORDER BY created_at DESC"
            ).format(
                cols=_SELECT_COLS,
                schema=sql.Identifier(_SCHEMA),
                table=sql.Identifier(_TABLE),
            )
            params = (schedule_id,)
        else:
            query = sql.SQL(
                "SELECT {cols} FROM {schema}.{table} ORDER BY created_at DESC"
            ).format(
                cols=_SELECT_COLS,
                schema=sql.Identifier(_SCHEMA),
                table=sql.Identifier(_TABLE),
            )
            params = ()

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()

            return [dict(r) for r in rows]

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.list_all: error=%s", exc,
            )
            raise DatabaseError(f"Failed to list scheduled datasets: {exc}") from exc

    # =========================================================================
    # WRITE: UPDATE
    # =========================================================================

    def update(self, dataset_id: str, **fields) -> Optional[dict]:
        """
        Update one or more columns on a scheduled dataset row.

        Allowed fields: description, source_type, column_schema, rebuild_strategy,
        schedule_id. updated_at is always set to NOW().

        Returns the updated row as a dict, or None if not found.
        """
        _ALLOWED = frozenset({
            "description",
            "source_type",
            "column_schema",
            "rebuild_strategy",
            "schedule_id",
            "credential_key",
        })

        updates = {k: v for k, v in fields.items() if k in _ALLOWED}
        if not updates:
            raise ValueError(
                f"update() called with no valid fields. "
                f"Allowed: {sorted(_ALLOWED)}. Got: {sorted(fields)}"
            )

        set_fragments = []
        params = []

        for col, val in updates.items():
            if col == "column_schema":
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
        params.append(dataset_id)

        update_sql = sql.SQL(
            "UPDATE {schema}.{table} SET {sets} "
            "WHERE dataset_id = %s RETURNING {cols}"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
            sets=sql.SQL(", ").join(set_fragments),
            cols=_SELECT_COLS,
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(update_sql, params)
                    row = cur.fetchone()
                conn.commit()

            if row is None:
                return None

            logger.info(
                "ScheduledDatasetRepository.update: dataset_id=%s fields=%s",
                dataset_id, sorted(updates.keys()),
            )
            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.update: dataset_id=%s error=%s",
                dataset_id, exc,
            )
            raise DatabaseError(
                f"Failed to update scheduled dataset (dataset_id={dataset_id}): {exc}"
            ) from exc

    # =========================================================================
    # WRITE: RECORD SYNC
    # =========================================================================

    def record_sync(
        self,
        dataset_id: str,
        run_id: str,
        row_count: int,
    ) -> None:
        """
        Update sync state after a successful workflow run.

        Sets last_sync_at, last_sync_run_id, row_count, and updated_at atomically.
        """
        update_sql = sql.SQL(
            "UPDATE {schema}.{table} SET "
            "last_sync_at = NOW(), last_sync_run_id = %s, "
            "row_count = %s, updated_at = NOW() "
            "WHERE dataset_id = %s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(update_sql, (run_id, row_count, dataset_id))
                conn.commit()

            logger.info(
                "ScheduledDatasetRepository.record_sync: dataset_id=%s run_id=%s row_count=%d",
                dataset_id, run_id[:16] if run_id else "?", row_count,
            )

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.record_sync: dataset_id=%s error=%s",
                dataset_id, exc,
            )
            raise DatabaseError(
                f"Failed to record sync for dataset (dataset_id={dataset_id}): {exc}"
            ) from exc

    # =========================================================================
    # WRITE: DELETE
    # =========================================================================

    def delete(self, dataset_id: str) -> bool:
        """
        Remove a scheduled dataset registration.

        Does NOT drop the PostGIS table — only removes the metadata record.
        Returns True if deleted, False if not found.
        """
        delete_sql = sql.SQL(
            "DELETE FROM {schema}.{table} WHERE dataset_id = %s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._cm.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(delete_sql, (dataset_id,))
                    deleted = cur.rowcount > 0
                conn.commit()

            if deleted:
                logger.info(
                    "ScheduledDatasetRepository.delete: dataset_id=%s", dataset_id,
                )
            return deleted

        except psycopg.Error as exc:
            logger.error(
                "DB error in ScheduledDatasetRepository.delete: dataset_id=%s error=%s",
                dataset_id, exc,
            )
            raise DatabaseError(
                f"Failed to delete scheduled dataset (dataset_id={dataset_id}): {exc}"
            ) from exc


__all__ = ["ScheduledDatasetRepository"]
