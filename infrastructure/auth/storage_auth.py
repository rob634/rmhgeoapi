# ============================================================================
# AZURE STORAGE OAUTH AUTHENTICATION
# ============================================================================
# STATUS: Infrastructure - Storage OAuth for Docker runtime
# PURPOSE: Managed Identity authentication for Azure Blob Storage + GDAL
# LAST_REVIEWED: 10 JAN 2026
# ============================================================================
"""
Azure Storage OAuth authentication for Docker workers.

Handles OAuth token acquisition for Azure Blob Storage using Managed Identity.
Configures GDAL environment for /vsiaz/ paths to use OAuth instead of SAS tokens.

Why This Matters for Docker:
---------------------------
GDAL uses /vsiaz/ virtual file system paths for Azure Blob Storage.
By default, GDAL expects SAS tokens or storage keys. With Managed Identity,
we need to:
1. Acquire OAuth token for storage scope
2. Set AZURE_STORAGE_ACCESS_TOKEN environment variable
3. GDAL automatically uses this token for /vsiaz/ paths

Token Refresh:
-------------
Storage tokens expire after ~1 hour. The background refresh thread
updates AZURE_STORAGE_ACCESS_TOKEN before expiry, ensuring GDAL
always has valid credentials during long-running operations.

Environment Variables Set:
-------------------------
AZURE_STORAGE_ACCOUNT - Storage account name
AZURE_STORAGE_ACCESS_TOKEN - OAuth bearer token (refreshed automatically)

Usage:
------
```python
from infrastructure.auth import initialize_storage_auth

# On startup - acquires token and configures GDAL
initialize_storage_auth()

# Now GDAL /vsiaz/ paths work:
# /vsiaz/bronze-rasters/large-file.tif
```
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from config import get_config
from .token_cache import storage_token_cache, storage_error_cache

logger = logging.getLogger(__name__)

# OAuth scope for Azure Blob Storage
STORAGE_SCOPE = "https://storage.azure.com/.default"

# Refresh tokens when less than 5 minutes until expiry
TOKEN_REFRESH_BUFFER_SECS = 300


def get_storage_token() -> Optional[str]:
    """
    Get OAuth token for Azure Storage using Managed Identity.

    Token grants access to ALL containers based on the Managed Identity's
    RBAC role assignments (e.g., Storage Blob Data Reader/Contributor).

    The token is automatically cached and refreshed 5 minutes before expiry.

    Returns:
        OAuth bearer token for Azure Storage, or None if not configured.

    Raises:
        Exception: If token acquisition fails.
    """
    config = get_config()

    # Get storage account from zone config (use silver as primary for GDAL)
    # Storage uses multi-zone architecture: bronze, silver, silverext, gold
    account_name = config.storage.silver.account_name

    # Check if storage account is configured
    if not account_name:
        logger.warning("AZURE_STORAGE_ACCOUNT_NAME not set, skipping storage auth")
        return None

    # Check cache first
    cached = storage_token_cache.get_if_valid(min_ttl_seconds=TOKEN_REFRESH_BUFFER_SECS)
    if cached:
        ttl = storage_token_cache.ttl_seconds()
        logger.debug(f"Using cached storage token, TTL: {ttl:.0f}s")
        return cached

    # Acquire new token
    logger.info("=" * 60)
    logger.info("Acquiring Azure Storage OAuth token...")
    logger.info(f"Storage Account: {account_name}")
    logger.info("=" * 60)

    try:
        from azure.identity import DefaultAzureCredential
        from azure.core.exceptions import ClientAuthenticationError

        credential = DefaultAzureCredential()
        token_response = credential.get_token(STORAGE_SCOPE)

        access_token = token_response.token
        expires_at = datetime.fromtimestamp(token_response.expires_on, tz=timezone.utc)

        # Cache the token
        storage_token_cache.set(access_token, expires_at)
        storage_error_cache.record_success()

        logger.info(f"Storage token acquired, expires: {expires_at.isoformat()}")
        logger.debug(f"Token length: {len(access_token)} characters")

        return access_token

    except ClientAuthenticationError as e:
        error_msg = f"Authentication failed: {e}"
        storage_error_cache.record_error(error_msg)
        logger.error("=" * 60)
        logger.error("FAILED TO GET STORAGE OAUTH TOKEN")
        logger.error("=" * 60)
        logger.error(f"Error: {error_msg}")
        logger.error("")
        logger.error("Troubleshooting:")
        logger.error("  - Verify Managed Identity is assigned to Container App")
        logger.error("  - Verify RBAC role: Storage Blob Data Contributor")
        logger.error(f"  - Storage account: {account_name}")
        logger.error("=" * 60)
        raise

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        storage_error_cache.record_error(error_msg)
        logger.error(f"Storage token acquisition failed: {error_msg}")
        raise


def configure_gdal_azure_auth(token: str) -> None:
    """
    Configure GDAL for Azure blob access using OAuth token.

    Sets environment variables that GDAL reads for /vsiaz/ paths.
    This must be called after acquiring a token and whenever the token
    is refreshed.

    Args:
        token: OAuth bearer token for Azure Storage.
    """
    config = get_config()

    # Get storage account from zone config (use silver as primary for GDAL)
    account_name = config.storage.silver.account_name

    if not account_name:
        logger.warning("AZURE_STORAGE_ACCOUNT not set, skipping GDAL config")
        return

    # Set environment variables (used by GDAL)
    os.environ["AZURE_STORAGE_ACCOUNT"] = account_name
    os.environ["AZURE_STORAGE_ACCESS_TOKEN"] = token

    # Also set the alternate name used by some tools
    os.environ["AZURE_STORAGE_ACCOUNT_NAME"] = account_name

    # Try to set GDAL config options directly (more reliable in some cases)
    try:
        from osgeo import gdal
        gdal.SetConfigOption("AZURE_STORAGE_ACCOUNT", account_name)
        gdal.SetConfigOption("AZURE_STORAGE_ACCESS_TOKEN", token)
        logger.debug(f"GDAL config options set for: {account_name}")
    except ImportError:
        # GDAL not available via osgeo, try rasterio
        try:
            from rasterio import _env
            _env.set_gdal_config("AZURE_STORAGE_ACCOUNT", account_name)
            _env.set_gdal_config("AZURE_STORAGE_ACCESS_TOKEN", token)
            logger.debug(f"GDAL (via rasterio) configured for: {account_name}")
        except Exception as e:
            logger.debug(f"Could not set GDAL config directly: {e}")
            # Environment variables should still work

    logger.debug(f"GDAL Azure auth configured for: {account_name}")


def initialize_storage_auth() -> Optional[str]:
    """
    Initialize storage authentication on application startup.

    Acquires initial OAuth token and configures GDAL.

    Returns:
        OAuth token if successful, None if not configured.
    """
    config = get_config()

    # Get storage account from zone config (use silver as primary)
    account_name = config.storage.silver.account_name

    if not account_name:
        logger.info("Storage account not configured, skipping storage auth")
        return None

    try:
        token = get_storage_token()
        if token:
            configure_gdal_azure_auth(token)
            logger.info("Storage OAuth + GDAL authentication initialized")
        return token
    except Exception as e:
        logger.error(f"Failed to initialize storage OAuth: {e}")
        return None


def refresh_storage_token() -> Optional[str]:
    """
    Force refresh of storage OAuth token.

    Called by background refresh thread. Updates both the cache
    and GDAL environment variables.

    Returns:
        New OAuth token if successful, None otherwise.
    """
    logger.info("Refreshing Storage OAuth token...")

    # Invalidate cache to force new token
    storage_token_cache.invalidate()

    try:
        token = get_storage_token()
        if token:
            configure_gdal_azure_auth(token)
            logger.info("Storage token refresh complete")
        return token
    except Exception as e:
        logger.error(f"Storage token refresh failed: {e}")
        return None


def get_storage_token_status() -> dict:
    """
    Get storage token status for health checks.

    Returns:
        Dict with token status and any errors.
    """
    config = get_config()

    # Get storage account from zone config (use silver as primary)
    account_name = config.storage.silver.account_name

    return {
        "storage_account": account_name,
        "token": storage_token_cache.get_status(),
        "errors": storage_error_cache.get_status(),
    }
