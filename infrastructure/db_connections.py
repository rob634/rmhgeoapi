# ============================================================================
# CLAUDE CONTEXT - CONNECTION_MANAGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Database connection lifecycle
# PURPOSE: PostgreSQL connection lifecycle — pooled and single-use modes
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: ConnectionManager
# DEPENDENCIES: db_auth, db_utils, circuit_breaker, connection_pool, psycopg
# ============================================================================
"""
PostgreSQL connection lifecycle management.

Routes between pooled (Docker) and single-use (Functions) connection modes.
Integrates circuit breaker for cascade failure prevention. Handles retry
with token refresh on auth failure.

Import graph:
    db_connections.py <- postgresql.py
    db_connections.py -> db_auth.py, db_utils.py, circuit_breaker.py, connection_pool.py
"""

import logging
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from infrastructure.db_auth import ManagedIdentityAuth
from infrastructure.db_utils import register_type_adapters

logger = logging.getLogger(__name__)

# Shared error markers — used by both is_transient_error() and _get_pooled_connection()
_TRANSIENT_MARKERS = frozenset([
    "connection is closed",
    "the connection is lost",
    "could not connect to server",
    "connection refused",
    "connection timed out",
    "ssl syscall error",
    "broken pipe",
    "connection reset",
    "server closed the connection unexpectedly",
])


class ConnectionManager:
    """
    PostgreSQL connection lifecycle manager.

    Provides get_connection() context manager that routes to pooled (Docker)
    or single-use (Functions) connections. Integrates circuit breaker and
    handles retry with token refresh on auth failure.
    """

    def __init__(self, auth: ManagedIdentityAuth):
        """
        Initialize with auth provider.

        Args:
            auth: ManagedIdentityAuth instance for connection strings and token refresh.
        """
        self._auth = auth

    @contextmanager
    def get_connection(self):
        """
        Context manager for PostgreSQL database connections.

        Routes to pooled (Docker) or single-use (Functions) based on runtime mode.
        Checks circuit breaker before connecting. Records success/failure for
        circuit breaker state transitions.

        Yields:
            psycopg.Connection — active PostgreSQL connection.
        """
        from infrastructure.circuit_breaker import CircuitBreaker
        from infrastructure.connection_pool import ConnectionPoolManager

        breaker = CircuitBreaker.get_instance()
        breaker.check()  # Raises CircuitBreakerOpenError if OPEN

        connected = False
        try:
            if ConnectionPoolManager.is_pool_mode():
                with self._get_pooled_connection() as conn:
                    connected = True
                    breaker.record_success()
                    yield conn
            else:
                with self._get_single_use_connection() as conn:
                    connected = True
                    breaker.record_success()
                    yield conn
        except Exception:
            if not connected:
                breaker.record_failure()
            raise

    @contextmanager
    def get_cursor(self, conn=None):
        """
        Context manager for cursors with mode-dependent transaction handling.

        With conn (caller provides):  No auto-commit. Caller controls transaction.
        Without conn (creates new):   Auto-commits on success, rollback on error.

        Args:
            conn: Existing connection. If None, creates a new auto-committing connection.
        """
        if conn:
            with conn.cursor() as cursor:
                yield cursor
        else:
            with self.get_connection() as new_conn:
                with new_conn.cursor() as cursor:
                    yield cursor
                    new_conn.commit()

    @staticmethod
    def is_transient_error(error: Exception) -> bool:
        """
        Return True when error looks like a transient connection issue
        that may succeed on retry (network blip, server restart, etc.).
        """
        for candidate in (error, getattr(error, '__cause__', None), getattr(error, '__context__', None)):
            if candidate is None:
                continue
            msg = str(candidate).lower()
            if any(marker in msg for marker in _TRANSIENT_MARKERS):
                return True
        return False

    # ------------------------------------------------------------------ #
    # Internal — connection mode implementations
    # ------------------------------------------------------------------ #

    @contextmanager
    def _get_pooled_connection(self):
        """
        Get connection from pool (Docker mode).

        On auth failure or dead pool, refreshes credentials/pool and retries once.
        """
        from infrastructure.connection_pool import ConnectionPoolManager

        logger.debug("Getting connection from pool...")
        use_managed_identity = self._auth.is_active()
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            try:
                with ConnectionPoolManager.get_connection() as conn:
                    pid = conn.info.backend_pid
                    logger.info(f"[CONN] Acquired pooled connection pid={pid}")
                    try:
                        yield conn
                    finally:
                        logger.info(f"[CONN] Released pooled connection pid={pid}")
                    return
            except Exception as e:
                error_str = str(e).lower()
                logger.error(f"Pool connection error: {e}")

                is_dead_pool = any(marker in error_str for marker in _TRANSIENT_MARKERS)

                can_retry = (
                    attempt < max_attempts
                    and (
                        (use_managed_identity and ManagedIdentityAuth.is_auth_error(e))
                        or is_dead_pool
                    )
                )

                if not can_retry:
                    raise

                if is_dead_pool:
                    logger.warning(
                        f"Dead pool detected ({type(e).__name__}); "
                        f"recreating connection pool and retrying"
                    )
                    ConnectionPoolManager.recreate_pool()
                else:
                    logger.warning(
                        "Pooled managed identity auth failed; "
                        "refreshing token, recreating pool, retrying once"
                    )
                    self._auth.refresh_pool_credentials()

    @contextmanager
    def _get_single_use_connection(self):
        """
        Create single-use connection (Function App mode).

        On auth failure, refreshes token via self._auth.refresh() and retries.
        On transient error, waits 2s and retries.
        """
        conn = None
        use_managed_identity = self._auth.is_active()
        max_attempts = 2

        try:
            for attempt in range(1, max_attempts + 1):
                current_conn_string = self._auth.get_connection_string()

                logger.debug(f"Attempting PostgreSQL connection (attempt {attempt}/{max_attempts})...")

                try:
                    conn = psycopg.connect(current_conn_string, row_factory=dict_row)
                    register_type_adapters(conn)
                    pid = conn.info.backend_pid
                    logger.info(f"[CONN] Opened single-use connection pid={pid}")
                    yield conn
                    return

                except psycopg.Error as e:
                    logger.error(f"PostgreSQL connection error: {e}")

                    if "Name or service not known" in str(e) or "could not translate host name" in str(e):
                        logger.error("DNS Resolution Error - Cannot resolve database hostname")

                    if conn:
                        conn.rollback()
                        conn.close()
                        conn = None

                    is_auth_error = use_managed_identity and ManagedIdentityAuth.is_auth_error(e)
                    is_transient = self.is_transient_error(e)

                    can_retry = attempt < max_attempts and (is_auth_error or is_transient)

                    if not can_retry:
                        raise

                    if is_auth_error:
                        logger.warning("Managed identity auth failed; refreshing token and retrying")
                        self._auth.refresh()
                    else:
                        logger.warning(f"Transient connection error ({type(e).__name__}); retrying in 2s")
                        import time
                        time.sleep(2)

        except psycopg.Error:
            if conn:
                conn.rollback()
            raise

        finally:
            if conn:
                try:
                    pid = conn.info.backend_pid
                except Exception:
                    pid = "unknown"
                conn.close()
                logger.info(f"[CONN] Closed single-use connection pid={pid}")


__all__ = ['ConnectionManager']
