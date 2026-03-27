# ============================================================================
# CLAUDE CONTEXT - LEASE REPOSITORY
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Infrastructure - Database lease for orchestrator mutex
# PURPOSE: Acquire, renew, and release the orchestrator_lease DB row
# LAST_REVIEWED: 26 MAR 2026
# EXPORTS: LeaseRepository, _generate_holder_id
# DEPENDENCIES: psycopg, infrastructure.db_auth, infrastructure.db_connections
# ============================================================================
"""
LeaseRepository — distributed mutex via app.orchestrator_lease.

All SQL uses psycopg.sql.SQL() and sql.Identifier() — never f-strings.
All queries return plain dicts via dict_row (set at connection level).
"""

import logging
import os
import socket
from typing import Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from exceptions import DatabaseError
from .postgresql import PostgreSQLRepository

logger = logging.getLogger(__name__)

_SCHEMA = "app"
_TABLE = "orchestrator_lease"
_LEASE_KEY = "singleton"


def _generate_holder_id() -> str:
    """Generate a unique holder ID for this process (hostname + pid)."""
    return f"{socket.gethostname()}:{os.getpid()}"


class LeaseRepository(PostgreSQLRepository):
    """
    Repository for app.orchestrator_lease — single-row distributed mutex.

    Inherits connection management from PostgreSQLRepository (Standard 1.4).
    All SQL is composed via psycopg.sql; f-strings are never used.
    """

    # =========================================================================
    # DDL: ENSURE TABLE EXISTS
    # =========================================================================

    def ensure_table(self) -> None:
        """
        Create app.orchestrator_lease if it does not already exist.

        Idempotent — safe to call on every startup.
        Raises DatabaseError on any psycopg.Error.
        """
        create_sql = sql.SQL(
            "CREATE TABLE IF NOT EXISTS {schema}.{table} ("
            "    lease_key  TEXT PRIMARY KEY DEFAULT 'singleton',"
            "    holder_id  TEXT NOT NULL,"
            "    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
            "    expires_at  TIMESTAMPTZ NOT NULL,"
            "    renewed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            ")"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(create_sql)
                conn.commit()

            logger.info("LeaseRepository.ensure_table: app.orchestrator_lease ready")

        except psycopg.Error as exc:
            logger.error(
                "DB error in LeaseRepository.ensure_table: error=%s", exc
            )
            raise DatabaseError(
                f"Failed to ensure orchestrator_lease table: {exc}"
            ) from exc

    # =========================================================================
    # WRITE: ACQUIRE
    # =========================================================================

    def try_acquire(self, holder_id: str, ttl_seconds: int = 60) -> bool:
        """
        Atomically acquire the lease for this holder.

        Inserts the singleton row if it does not exist. Updates the row if
        the existing lease has expired OR if the caller already holds it
        (idempotent re-acquire / heartbeat race).

        Returns True if the lease was acquired or already held by this holder.
        Returns False if another holder holds a valid (non-expired) lease.
        Raises DatabaseError on any psycopg.Error.
        """
        upsert_sql = sql.SQL(
            "INSERT INTO {schema}.{table} "
            "    (lease_key, holder_id, acquired_at, expires_at, renewed_at) "
            "VALUES ('singleton', %(holder_id)s, NOW(), NOW() + %(ttl)s * interval '1 second', NOW()) "
            "ON CONFLICT (lease_key) DO UPDATE "
            "SET holder_id   = %(holder_id)s, "
            "    acquired_at = NOW(), "
            "    expires_at  = NOW() + %(ttl)s * interval '1 second', "
            "    renewed_at  = NOW() "
            "WHERE {schema}.{table}.expires_at < NOW() "
            "   OR {schema}.{table}.holder_id = %(holder_id)s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        params = {"holder_id": holder_id, "ttl": ttl_seconds}

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(upsert_sql, params)
                    acquired = cur.rowcount > 0
                conn.commit()

            if acquired:
                logger.info(
                    "LeaseRepository.try_acquire: acquired holder_id=%s ttl=%ds",
                    holder_id, ttl_seconds,
                )
            else:
                logger.debug(
                    "LeaseRepository.try_acquire: lease held by another holder_id=%s",
                    holder_id,
                )

            return acquired

        except psycopg.Error as exc:
            logger.error(
                "DB error in LeaseRepository.try_acquire: holder_id=%s error=%s",
                holder_id, exc,
            )
            raise DatabaseError(
                f"Failed to acquire orchestrator lease (holder_id={holder_id}): {exc}"
            ) from exc

    # =========================================================================
    # WRITE: RENEW
    # =========================================================================

    def renew(self, holder_id: str, ttl_seconds: int = 60) -> bool:
        """
        Extend the lease TTL for the current holder.

        Called on every poll cycle by the active orchestrator to prevent expiry.
        Returns True if the renewal succeeded (this holder still owns the lease).
        Returns False on any DB exception or if the lease row was not updated
        (another instance has taken over). Treats False as lease-lost — caller
        should stop orchestrating.
        """
        renew_sql = sql.SQL(
            "UPDATE {schema}.{table} "
            "SET expires_at = NOW() + %(ttl)s * interval '1 second', "
            "    renewed_at = NOW() "
            "WHERE lease_key = 'singleton' AND holder_id = %(holder_id)s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        params = {"holder_id": holder_id, "ttl": ttl_seconds}

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(renew_sql, params)
                    renewed = cur.rowcount > 0
                conn.commit()

            if not renewed:
                logger.warning(
                    "LeaseRepository.renew: lease lost or not held — holder_id=%s",
                    holder_id,
                )

            return renewed

        except Exception as exc:
            # Treat any exception as lease-lost to be safe.
            logger.warning(
                "LeaseRepository.renew: exception during renewal, treating as lease-lost "
                "holder_id=%s error=%s",
                holder_id, exc,
            )
            return False

    # =========================================================================
    # WRITE: RELEASE
    # =========================================================================

    def release(self, holder_id: str) -> None:
        """
        Release the lease held by this holder.

        Non-fatal — logs a warning on failure rather than raising. Callers
        should not rely on this succeeding (the TTL is the ultimate safety net).
        """
        delete_sql = sql.SQL(
            "DELETE FROM {schema}.{table} "
            "WHERE lease_key = 'singleton' AND holder_id = %(holder_id)s"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(delete_sql, {"holder_id": holder_id})
                    deleted = cur.rowcount
                conn.commit()

            if deleted == 1:
                logger.info(
                    "LeaseRepository.release: released holder_id=%s", holder_id
                )
            else:
                logger.debug(
                    "LeaseRepository.release: no row deleted (already expired?) holder_id=%s",
                    holder_id,
                )

        except Exception as exc:
            logger.warning(
                "LeaseRepository.release: non-fatal error releasing lease "
                "holder_id=%s error=%s",
                holder_id, exc,
            )

    # =========================================================================
    # READ: CURRENT LEASE (health checks)
    # =========================================================================

    def get_current(self) -> Optional[dict]:
        """
        Return the current lease row, or None if no lease exists.

        Includes an `is_expired` boolean computed by the database.
        Intended for health checks and diagnostics — not on the hot path.
        Raises DatabaseError on any psycopg.Error.
        """
        query = sql.SQL(
            "SELECT *, (expires_at < NOW()) AS is_expired "
            "FROM {schema}.{table} "
            "WHERE lease_key = 'singleton'"
        ).format(
            schema=sql.Identifier(_SCHEMA),
            table=sql.Identifier(_TABLE),
        )

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query)
                    row = cur.fetchone()

            if row is None:
                return None

            return dict(row)

        except psycopg.Error as exc:
            logger.error(
                "DB error in LeaseRepository.get_current: error=%s", exc
            )
            raise DatabaseError(
                f"Failed to fetch current orchestrator lease: {exc}"
            ) from exc


__all__ = ["LeaseRepository", "_generate_holder_id"]
