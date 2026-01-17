# ============================================================================
# DOCKER CONNECTION POOL MANAGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Docker-aware connection pooling
# PURPOSE: Mode-aware database connections - pool for Docker, single-use for Functions
# LAST_REVIEWED: 16 JAN 2026
# EXPORTS: ConnectionPoolManager
# DEPENDENCIES: psycopg_pool, config.app_mode_config
# ============================================================================
"""
Connection Pool Manager for Docker Workers.

================================================================================
ARCHITECTURE
================================================================================

Docker workers have predictable lifecycles (unlike serverless Function Apps),
making connection pooling safe and beneficial:

    Function App:
    - Workers start/stop unpredictably
    - Connections may leak if worker killed mid-request
    - Single-use connections are safer

    Docker Worker:
    - Controlled lifecycle (we know when it starts/stops)
    - Long-running tasks benefit from connection reuse
    - Pool is safe - we drain on shutdown

This module provides mode-aware connection management:
- Docker mode: Connection pool with automatic refresh on token expiry
- Function App mode: Delegates to existing single-use pattern

================================================================================
TOKEN REFRESH INTEGRATION
================================================================================

OAuth tokens expire after ~1 hour. When TokenRefreshWorker refreshes tokens,
it must also recreate the connection pool with fresh credentials:

    # In infrastructure/auth/__init__.py or docker_service.py
    def refresh_all_tokens():
        refresh_postgres_token()
        refresh_storage_token()

        # IMPORTANT: Recreate pool with new credentials
        ConnectionPoolManager.recreate_pool()

The pool recreation:
1. Waits for active connections to be returned (up to 30s)
2. Closes the old pool
3. Creates new pool with fresh token on next access

================================================================================
USAGE
================================================================================

The ConnectionPoolManager is used internally by PostgreSQLRepository:

    # infrastructure/postgresql.py
    @contextmanager
    def _get_connection(self):
        if ConnectionPoolManager.is_pool_mode():
            with ConnectionPoolManager.get_connection() as conn:
                yield conn
        else:
            # Existing single-use connection logic
            ...

For testing pool status:

    from infrastructure.connection_pool import ConnectionPoolManager

    stats = ConnectionPoolManager.get_pool_stats()
    # {'mode': 'pool', 'pool_size': 5, 'pool_available': 3, ...}

================================================================================
EXPORTS
================================================================================

    ConnectionPoolManager: Class with static methods for pool management
"""

import threading
import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# CONNECTION POOL CONFIGURATION
# =============================================================================

# Default pool sizes (can be overridden via environment variables)
DEFAULT_POOL_MIN = 2
DEFAULT_POOL_MAX = 10

# Timeout for waiting for a connection from the pool (seconds)
POOL_CONNECTION_TIMEOUT = 30.0

# Max time a connection can live in the pool (seconds) - 55 minutes
# This is slightly less than the 1-hour OAuth token lifetime
POOL_MAX_LIFETIME = 55 * 60

# Timeout for draining connections on pool close (seconds)
POOL_CLOSE_TIMEOUT = 30.0


# =============================================================================
# CONNECTION POOL MANAGER
# =============================================================================

class ConnectionPoolManager:
    """
    Mode-aware connection pool manager.

    Provides pooled connections for Docker mode, delegates to single-use
    connections for Function App mode. Handles token refresh with pool
    recreation.

    Class-level state is used because:
    1. Pool should be shared across all repository instances
    2. Only one pool per process is needed
    3. Thread-safe via lock

    Usage:
        # Check if pooling is active
        if ConnectionPoolManager.is_pool_mode():
            with ConnectionPoolManager.get_connection() as conn:
                cursor = conn.cursor()
                ...

        # Get pool statistics
        stats = ConnectionPoolManager.get_pool_stats()

        # Recreate pool (called by token refresh)
        ConnectionPoolManager.recreate_pool()
    """

    # Class-level pool (shared across all instances)
    _pool: Optional[ConnectionPool] = None
    _pool_lock = threading.Lock()
    _pool_config: Optional[Dict[str, Any]] = None

    # Track initialization state
    _initialized = False
    _shutdown_requested = False

    @classmethod
    def _get_pool_config(cls) -> Dict[str, Any]:
        """
        Get pool configuration from environment.

        Loads configuration lazily on first access.
        """
        if cls._pool_config is None:
            import os

            cls._pool_config = {
                'min_size': int(os.environ.get('DOCKER_DB_POOL_MIN', DEFAULT_POOL_MIN)),
                'max_size': int(os.environ.get('DOCKER_DB_POOL_MAX', DEFAULT_POOL_MAX)),
                'timeout': POOL_CONNECTION_TIMEOUT,
                'max_lifetime': POOL_MAX_LIFETIME,
            }

            logger.info(
                f"Connection pool config: min={cls._pool_config['min_size']}, "
                f"max={cls._pool_config['max_size']}, "
                f"max_lifetime={cls._pool_config['max_lifetime']}s"
            )

        return cls._pool_config

    @classmethod
    def is_pool_mode(cls) -> bool:
        """
        Check if connection pooling should be used.

        Returns True only in Docker worker mode.
        """
        from config.app_mode_config import get_app_mode_config

        app_mode = get_app_mode_config()
        return app_mode.is_docker_mode

    @classmethod
    def _build_connection_string(cls) -> str:
        """
        Build connection string for pool.

        Uses the same logic as PostgreSQLRepository but returns raw string
        for pool initialization.
        """
        from config import get_config
        from infrastructure.auth import get_postgres_token

        config = get_config()
        db_config = config.database

        # Get OAuth token for managed identity auth
        token = get_postgres_token()

        if not token:
            raise RuntimeError(
                "Failed to get PostgreSQL token for connection pool. "
                "Ensure managed identity is configured."
            )

        # Build connection string
        conn_string = (
            f"host={db_config.host} "
            f"port={db_config.port} "
            f"dbname={db_config.database} "
            f"user={db_config.managed_identity_name} "
            f"password={token} "
            f"sslmode=require"
        )

        return conn_string

    @classmethod
    def _configure_connection(cls, conn) -> None:
        """
        Configure a connection after it's created by the pool.

        Called by the pool for each new connection.
        """
        # Set row factory to return dicts
        conn.row_factory = dict_row

        # Set search path to include common schemas
        from config import get_config
        config = get_config()

        schemas = [
            config.database.app_schema,
            config.database.schema,  # geo schema
        ]

        # Only add pgstac and h3 if they're configured
        if hasattr(config.database, 'pgstac_schema') and config.database.pgstac_schema:
            schemas.append(config.database.pgstac_schema)
        if hasattr(config.database, 'h3_schema') and config.database.h3_schema:
            schemas.append(config.database.h3_schema)

        search_path = ', '.join(schemas)
        conn.execute(f"SET search_path TO {search_path}")

    @classmethod
    def _create_pool(cls) -> ConnectionPool:
        """
        Create a new connection pool.

        Called internally when pool is first needed or after recreation.
        """
        config = cls._get_pool_config()
        conn_string = cls._build_connection_string()

        logger.info(
            f"Creating connection pool: min={config['min_size']}, max={config['max_size']}"
        )

        pool = ConnectionPool(
            conninfo=conn_string,
            min_size=config['min_size'],
            max_size=config['max_size'],
            timeout=config['timeout'],
            max_lifetime=config['max_lifetime'],
            configure=cls._configure_connection,
            open=True,  # Open pool immediately
        )

        logger.info("Connection pool created successfully")
        return pool

    @classmethod
    def _get_or_create_pool(cls) -> ConnectionPool:
        """
        Get existing pool or create a new one.

        Thread-safe via double-check locking.
        """
        if cls._pool is None:
            with cls._pool_lock:
                if cls._pool is None:
                    cls._pool = cls._create_pool()
                    cls._initialized = True

        return cls._pool

    @classmethod
    @contextmanager
    def get_connection(cls):
        """
        Get a connection from the pool.

        Usage:
            with ConnectionPoolManager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")

        The connection is automatically returned to the pool when the
        context exits.

        Raises:
            RuntimeError: If not in Docker mode (pooling not available)
            PoolTimeout: If no connection available within timeout
        """
        if not cls.is_pool_mode():
            raise RuntimeError(
                "ConnectionPoolManager.get_connection() called but not in Docker mode. "
                "Use PostgreSQLRepository._get_connection() instead."
            )

        if cls._shutdown_requested:
            raise RuntimeError(
                "Connection pool is shutting down. Cannot get new connections."
            )

        pool = cls._get_or_create_pool()

        with pool.connection() as conn:
            yield conn

    @classmethod
    def recreate_pool(cls) -> None:
        """
        Recreate the connection pool with fresh credentials.

        Called by token refresh worker when OAuth token is refreshed.
        This ensures connections use the new token.

        The process:
        1. Mark old pool for closure
        2. Wait for active connections to be returned
        3. Close old pool
        4. Clear reference (new pool created on next access)
        """
        if not cls.is_pool_mode():
            logger.debug("Not in Docker mode, skipping pool recreation")
            return

        with cls._pool_lock:
            old_pool = cls._pool
            cls._pool = None

            if old_pool:
                logger.info("Recreating connection pool with fresh credentials...")
                try:
                    # Close old pool, waiting for connections to be returned
                    old_pool.close(timeout=POOL_CLOSE_TIMEOUT)
                    logger.info("Old connection pool closed successfully")
                except Exception as e:
                    logger.warning(f"Error closing old pool (non-fatal): {e}")

        # Create new pool immediately to warm up connections
        if cls.is_pool_mode():
            cls._get_or_create_pool()
            logger.info("New connection pool created with fresh credentials")

    @classmethod
    def shutdown(cls) -> None:
        """
        Gracefully shutdown the connection pool.

        Called during Docker worker shutdown (SIGTERM handling).

        Drains all connections and prevents new connections from being
        acquired.
        """
        cls._shutdown_requested = True

        with cls._pool_lock:
            if cls._pool:
                logger.info("Shutting down connection pool...")
                try:
                    cls._pool.close(timeout=POOL_CLOSE_TIMEOUT)
                    logger.info("Connection pool shutdown complete")
                except Exception as e:
                    logger.warning(f"Error during pool shutdown: {e}")
                finally:
                    cls._pool = None

    @classmethod
    def get_pool_stats(cls) -> Dict[str, Any]:
        """
        Get connection pool statistics.

        Returns information about pool state for monitoring and debugging.
        Useful for health endpoints and diagnostics.

        Returns:
            dict with keys:
                - mode: 'pool' or 'single_use'
                - initialized: whether pool has been created
                - shutdown_requested: whether shutdown is in progress
                - pool_size: current number of connections (if pooled)
                - pool_available: available connections (if pooled)
                - pool_min: minimum pool size
                - pool_max: maximum pool size
        """
        stats = {
            'mode': 'pool' if cls.is_pool_mode() else 'single_use',
            'initialized': cls._initialized,
            'shutdown_requested': cls._shutdown_requested,
        }

        if cls.is_pool_mode() and cls._pool is not None:
            try:
                pool_stats = cls._pool.get_stats()
                stats.update({
                    'pool_size': pool_stats.pool_size,
                    'pool_available': pool_stats.pool_available,
                    'requests_waiting': pool_stats.requests_waiting,
                    'connections_num': pool_stats.connections_num,
                })
            except Exception as e:
                stats['pool_stats_error'] = str(e)

        config = cls._get_pool_config()
        stats.update({
            'pool_min': config['min_size'],
            'pool_max': config['max_size'],
            'max_lifetime_seconds': config['max_lifetime'],
        })

        return stats

    @classmethod
    def reset_for_testing(cls) -> None:
        """
        Reset pool state for testing.

        WARNING: Only use in tests! This does not properly drain connections.
        """
        with cls._pool_lock:
            if cls._pool:
                try:
                    cls._pool.close(timeout=5)
                except Exception:
                    pass
            cls._pool = None
            cls._pool_config = None
            cls._initialized = False
            cls._shutdown_requested = False


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'ConnectionPoolManager',
]
