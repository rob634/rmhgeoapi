# ============================================================================
# DOCKER AUTHENTICATION MODULE
# ============================================================================
# STATUS: Infrastructure - OAuth token management for Docker runtime
# PURPOSE: Managed Identity authentication for long-running Docker workers
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
"""
Docker Authentication Module.

Provides OAuth token management for Docker workers that run for extended periods.
Unlike Azure Functions (short-lived), Docker workers need proactive token refresh.

Architecture:
------------
This module is ONLY used by Docker workers (docker_main.py, workers_entrance.py).
Azure Functions continue using the existing infrastructure/postgresql.py approach
which acquires tokens per-request (short-lived instances don't need refresh).

Components:
-----------
- TokenCache: Thread-safe token caching with TTL tracking
- PostgresAuth: PostgreSQL OAuth token acquisition and refresh
- StorageAuth: Azure Storage OAuth + GDAL /vsiaz/ configuration

Token Lifecycle:
---------------
Azure AD tokens expire after ~1 hour (3600 seconds).
This module refreshes tokens 5 minutes before expiry to ensure
continuous connectivity during long-running operations.

Usage:
------
```python
from infrastructure.auth import (
    initialize_docker_auth,
    refresh_all_tokens,
    get_postgres_connection_string,
)

# On startup
initialize_docker_auth()

# Periodically (every 45 minutes)
refresh_all_tokens()

# When connecting to database
conn_str = get_postgres_connection_string()
```

Environment Variables:
---------------------
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<guid>  # User-assigned MI
DB_ADMIN_MANAGED_IDENTITY_NAME=<identity-name>
AZURE_STORAGE_ACCOUNT_NAME=<storage-account>
"""

from .credential import get_azure_credential
from .token_cache import TokenCache, ErrorCache
from .postgres_auth import (
    get_postgres_token,
    get_postgres_connection_string,
    refresh_postgres_token,
    POSTGRES_SCOPE,
)
from .storage_auth import (
    get_storage_token,
    configure_gdal_azure_auth,
    refresh_storage_token,
    initialize_storage_auth,
    STORAGE_SCOPE,
)

# Token refresh timing constants
TOKEN_REFRESH_BUFFER_SECS: int = 300  # Refresh 5 min before expiry
BACKGROUND_REFRESH_INTERVAL_SECS: int = 45 * 60  # Background refresh every 45 min


def initialize_docker_auth() -> dict:
    """
    Initialize all authentication for Docker worker startup.

    Acquires initial tokens for PostgreSQL and Storage, configures GDAL.

    Returns:
        dict with initialization status for each component
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("DOCKER AUTH - Initializing")
    logger.info("=" * 60)

    status = {
        "postgres": {"initialized": False, "error": None},
        "storage": {"initialized": False, "error": None},
    }

    # PostgreSQL token
    try:
        token = get_postgres_token()
        if token:
            status["postgres"]["initialized"] = True
            logger.info("PostgreSQL OAuth: initialized")
    except Exception as e:
        status["postgres"]["error"] = str(e)
        logger.error(f"PostgreSQL OAuth: FAILED - {e}")

    # Storage token + GDAL config
    try:
        token = initialize_storage_auth()
        if token:
            status["storage"]["initialized"] = True
            logger.info("Storage OAuth + GDAL: initialized")
    except Exception as e:
        status["storage"]["error"] = str(e)
        logger.error(f"Storage OAuth: FAILED - {e}")

    logger.info("=" * 60)
    return status


def refresh_all_tokens() -> dict:
    """
    Refresh all OAuth tokens and recreate connection pool.

    Called periodically by background refresh thread.
    After refreshing tokens, recreates the connection pool (if in Docker mode)
    to ensure connections use the fresh PostgreSQL token.

    Returns:
        dict with refresh status for each component
    """
    import logging
    logger = logging.getLogger(__name__)

    status = {
        "postgres": {"refreshed": False, "error": None},
        "storage": {"refreshed": False, "error": None},
        "connection_pool": {"recreated": False, "error": None},
    }

    # PostgreSQL
    try:
        token = refresh_postgres_token()
        if token:
            status["postgres"]["refreshed"] = True
    except Exception as e:
        status["postgres"]["error"] = str(e)
        logger.warning(f"PostgreSQL token refresh failed: {e}")

    # Storage
    try:
        token = refresh_storage_token()
        if token:
            status["storage"]["refreshed"] = True
    except Exception as e:
        status["storage"]["error"] = str(e)
        logger.warning(f"Storage token refresh failed: {e}")

    # Recreate connection pool with fresh credentials (Docker mode only)
    # This must happen AFTER postgres token refresh
    if status["postgres"]["refreshed"]:
        try:
            from infrastructure.connection_pool import ConnectionPoolManager
            ConnectionPoolManager.recreate_pool()
            status["connection_pool"]["recreated"] = True
            logger.info("Connection pool recreated with fresh credentials")
        except Exception as e:
            status["connection_pool"]["error"] = str(e)
            logger.warning(f"Connection pool recreation failed: {e}")

    return status


def get_token_status() -> dict:
    """
    Get current status of all cached tokens.

    Returns:
        dict with TTL and status for each token
    """
    from .token_cache import postgres_token_cache, storage_token_cache

    return {
        "postgres": postgres_token_cache.get_status(),
        "storage": storage_token_cache.get_status(),
    }


__all__ = [
    # Shared credential
    "get_azure_credential",
    # Cache classes
    "TokenCache",
    "ErrorCache",
    # PostgreSQL
    "get_postgres_token",
    "get_postgres_connection_string",
    "refresh_postgres_token",
    "POSTGRES_SCOPE",
    # Storage
    "get_storage_token",
    "configure_gdal_azure_auth",
    "refresh_storage_token",
    "initialize_storage_auth",
    "STORAGE_SCOPE",
    # High-level functions
    "initialize_docker_auth",
    "refresh_all_tokens",
    "get_token_status",
    # Constants
    "TOKEN_REFRESH_BUFFER_SECS",
    "BACKGROUND_REFRESH_INTERVAL_SECS",
]
