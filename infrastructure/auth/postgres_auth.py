# ============================================================================
# POSTGRESQL OAUTH AUTHENTICATION
# ============================================================================
# STATUS: Infrastructure - PostgreSQL OAuth for Docker runtime
# PURPOSE: Managed Identity authentication for Azure PostgreSQL
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
"""
PostgreSQL OAuth authentication for Docker workers.

Acquires OAuth tokens for Azure Database for PostgreSQL using Managed Identity.
Tokens are cached and refreshed automatically before expiry.

Authentication Flow:
-------------------
1. Docker worker starts → initialize_docker_auth() called
2. ManagedIdentityCredential acquires token for PostgreSQL scope
3. Token cached with expiry time
4. Background thread refreshes every 45 minutes
5. get_postgres_connection_string() returns conn string with current token

Environment Variables:
---------------------
USE_MANAGED_IDENTITY=true (required)
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<guid>  # User-assigned MI (recommended)
DB_ADMIN_MANAGED_IDENTITY_NAME=<identity-name>  # PostgreSQL user name
POSTGIS_HOST=<server>.postgres.database.azure.com
POSTGIS_DATABASE=<database>
POSTGIS_PORT=5432

Usage:
------
```python
from infrastructure.auth import get_postgres_connection_string

# Get connection string with current token
conn_str = get_postgres_connection_string()

# Use with psycopg
conn = psycopg.connect(conn_str)
```
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

from config import get_config
from .token_cache import postgres_token_cache, db_error_cache

logger = logging.getLogger(__name__)

# OAuth scope for Azure Database for PostgreSQL
POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"

# Refresh tokens when less than 5 minutes until expiry
TOKEN_REFRESH_BUFFER_SECS = 300


def get_postgres_token() -> Optional[str]:
    """
    Get PostgreSQL OAuth token using Managed Identity.

    Uses caching with automatic refresh when token is within 5 minutes of expiry.

    Returns:
        OAuth bearer token for Azure Database for PostgreSQL.

    Raises:
        Exception: If token acquisition fails.
    """
    config = get_config()

    # Check if managed identity is enabled
    if not config.database.use_managed_identity:
        logger.debug("Managed identity disabled, using password auth")
        return None

    # Check cache first
    cached = postgres_token_cache.get_if_valid(min_ttl_seconds=TOKEN_REFRESH_BUFFER_SECS)
    if cached:
        ttl = postgres_token_cache.ttl_seconds()
        logger.debug(f"Using cached PostgreSQL token, TTL: {ttl:.0f}s")
        return cached

    # Acquire new token
    logger.info("=" * 60)
    logger.info("Acquiring PostgreSQL OAuth token...")
    logger.info(f"Host: {config.database.host}")
    logger.info(f"Database: {config.database.database}")
    logger.info(f"Identity: {config.database.effective_identity_name}")
    logger.info("=" * 60)

    try:
        from azure.identity import ManagedIdentityCredential, DefaultAzureCredential
        from azure.core.exceptions import ClientAuthenticationError

        # Use user-assigned MI if client ID is set
        client_id = config.database.managed_identity_client_id

        if client_id:
            logger.info(f"Using user-assigned Managed Identity: {client_id[:8]}...")
            credential = ManagedIdentityCredential(client_id=client_id)
        else:
            logger.info("Using DefaultAzureCredential (system MI or az login)")
            credential = DefaultAzureCredential()

        token_response = credential.get_token(POSTGRES_SCOPE)

        access_token = token_response.token
        expires_at = datetime.fromtimestamp(token_response.expires_on, tz=timezone.utc)

        # Cache the token
        postgres_token_cache.set(access_token, expires_at)
        db_error_cache.record_success()

        logger.info(f"PostgreSQL token acquired, expires: {expires_at.isoformat()}")
        logger.debug(f"Token length: {len(access_token)} characters")

        return access_token

    except ClientAuthenticationError as e:
        error_msg = f"Authentication failed: {e}"
        db_error_cache.record_error(error_msg)
        logger.error("=" * 60)
        logger.error("FAILED TO GET POSTGRESQL OAUTH TOKEN")
        logger.error("=" * 60)
        logger.error(f"Error: {error_msg}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("  - Verify Managed Identity is assigned to Container App")
        logger.error("  - Verify database user exists and matches MI name")
        logger.error(f"  - Expected user: {config.database.effective_identity_name}")
        logger.error("  - Run: SELECT * FROM pgaadauth_list_principals();")
        logger.error("=" * 60)
        raise

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        db_error_cache.record_error(error_msg)
        logger.error(f"PostgreSQL token acquisition failed: {error_msg}")
        raise


def get_postgres_connection_string() -> str:
    """
    Build PostgreSQL connection string with OAuth token.

    Returns:
        PostgreSQL connection string with current OAuth token.

    Raises:
        ValueError: If managed identity is not configured.
        Exception: If token acquisition fails.
    """
    config = get_config()

    if not config.database.use_managed_identity:
        # Fall back to password auth
        if not config.database.password:
            raise ValueError(
                "No PostgreSQL authentication configured. "
                "Set USE_MANAGED_IDENTITY=true or provide POSTGIS_PASSWORD"
            )
        return (
            f"host={config.database.host} "
            f"port={config.database.port} "
            f"dbname={config.database.database} "
            f"user={config.database.user} "
            f"password={config.database.password} "
            f"sslmode=require"
        )

    # Get OAuth token
    token = get_postgres_token()
    if not token:
        raise ValueError("Failed to acquire PostgreSQL OAuth token")

    # Build connection string with token as password
    identity_name = config.database.effective_identity_name

    return (
        f"host={config.database.host} "
        f"port={config.database.port} "
        f"dbname={config.database.database} "
        f"user={identity_name} "
        f"password={token} "
        f"sslmode=require"
    )


def refresh_postgres_token() -> Optional[str]:
    """
    Force refresh of PostgreSQL OAuth token.

    Called by background refresh thread.

    Returns:
        New OAuth token if successful, None otherwise.
    """
    config = get_config()

    if not config.database.use_managed_identity:
        logger.debug("PostgreSQL token refresh skipped (not using managed identity)")
        return None

    logger.info("Refreshing PostgreSQL OAuth token...")

    # Invalidate cache to force new token
    postgres_token_cache.invalidate()

    try:
        token = get_postgres_token()
        logger.info("PostgreSQL token refresh complete")
        return token
    except Exception as e:
        logger.error(f"PostgreSQL token refresh failed: {e}")
        return None


def get_postgres_token_status() -> dict:
    """
    Get PostgreSQL token status for health checks.

    Returns:
        Dict with token status and any errors.
    """
    return {
        "token": postgres_token_cache.get_status(),
        "errors": db_error_cache.get_status(),
    }
