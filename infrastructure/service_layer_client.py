# ============================================================================
# CLAUDE CONTEXT - SERVICE LAYER CLIENT REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - HTTP client for Service Layer (rmhtitiler) webhooks
# PURPOSE: Authenticated HTTP calls to Service Layer admin endpoints
# CREATED: 05 FEB 2026 (F1.6 - TiPG Collection Refresh)
# EXPORTS: ServiceLayerClient
# DEPENDENCIES: httpx, azure-identity, config, core.models.service_layer
# ============================================================================
"""
Service Layer Client Repository.

Handles HTTP communication with the Service Layer (rmhtitiler) webhooks.
Authentication uses DefaultAzureCredential for Managed Identity tokens
when SERVICE_LAYER_TOKEN_SCOPE is configured.

This follows the same repository pattern as BlobRepository (Azure Storage)
and PostgreSQLRepository (Database) — authentication is encapsulated in
the repository, callers don't manage tokens.

Usage:
    from infrastructure.service_layer_client import ServiceLayerClient

    client = ServiceLayerClient()
    result = client.refresh_tipg_collections()
    if result.status == "success":
        logger.info(f"Refreshed TiPG: {result.new_collections}")
"""

import logging
from typing import Optional
from datetime import datetime, timezone, timedelta

import httpx

from config import get_config
from core.models.service_layer import CollectionRefreshResponse, ServiceLayerHealth

logger = logging.getLogger(__name__)


class ServiceLayerClient:
    """
    Client for Service Layer (rmhtitiler) API calls.

    Handles:
    - Azure AD token acquisition via DefaultAzureCredential (when configured)
    - HTTP calls to Service Layer webhooks
    - Response parsing into typed Pydantic models

    Authentication:
    - When SERVICE_LAYER_TOKEN_SCOPE is set: acquires Azure AD tokens
    - When not set: calls without auth (for ADMIN_AUTH_ENABLED=false)
    - Token refresh is automatic with 5-minute buffer
    """

    # Token cache (class-level for reuse across instances)
    _token_cache = None  # Optional[AccessToken]

    def __init__(self):
        """Initialize client with config."""
        self._config = get_config()
        self._base_url = self._config.titiler_base_url.rstrip('/')

        # Token scope for Azure AD auth (empty = no auth)
        self._token_scope = getattr(self._config, 'service_layer_token_scope', None)
        if self._token_scope == '':
            self._token_scope = None

        # Lazy-init credential only when auth is needed
        self._credential = None

    def _get_auth_headers(self) -> dict:
        """
        Get authorization headers with fresh Azure AD token.

        Returns:
            Dict with Authorization header, or empty dict if auth not configured.
        """
        if not self._token_scope:
            logger.debug("SERVICE_LAYER_TOKEN_SCOPE not configured, calling without auth")
            return {}

        try:
            # Check if cached token is still valid (with 5 min buffer)
            if ServiceLayerClient._token_cache:
                expires_on = datetime.fromtimestamp(
                    ServiceLayerClient._token_cache.expires_on, tz=timezone.utc
                )
                if expires_on > datetime.now(timezone.utc) + timedelta(minutes=5):
                    return {"Authorization": f"Bearer {ServiceLayerClient._token_cache.token}"}

            # Lazy-init credential on first use
            if self._credential is None:
                from azure.identity import DefaultAzureCredential
                self._credential = DefaultAzureCredential()

            # Acquire new token
            token = self._credential.get_token(self._token_scope)
            ServiceLayerClient._token_cache = token

            logger.debug(
                f"Acquired Service Layer token, expires: "
                f"{datetime.fromtimestamp(token.expires_on, tz=timezone.utc).isoformat()}"
            )
            return {"Authorization": f"Bearer {token.token}"}

        except Exception as e:
            logger.warning(f"Failed to acquire Service Layer token: {e}")
            return {}

    def refresh_tipg_collections(self) -> CollectionRefreshResponse:
        """
        Call the TiPG collection refresh webhook.

        POST /admin/refresh-collections

        This triggers TiPG to re-scan PostGIS for new/removed geo schema
        tables and update its collection catalog immediately.

        Returns:
            CollectionRefreshResponse with before/after counts and new collections.

        Raises:
            httpx.HTTPStatusError: If the request fails with non-2xx status.
            httpx.ConnectError: If the Service Layer is unreachable.
        """
        url = f"{self._base_url}/admin/refresh-collections"
        headers = self._get_auth_headers()

        logger.info(f"Calling TiPG refresh webhook: {url}")

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers)
            response.raise_for_status()

            data = response.json()
            result = CollectionRefreshResponse(**data)

            logger.info(
                f"TiPG refresh complete: {result.collections_before} -> "
                f"{result.collections_after} (+{len(result.new_collections)})"
            )

            return result

    def health_check(self) -> ServiceLayerHealth:
        """
        Check Service Layer health.

        GET /health

        Returns:
            ServiceLayerHealth with status and enabled services.
        """
        url = f"{self._base_url}/health"

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)

                if response.status_code == 200:
                    data = response.json()
                    return ServiceLayerHealth(
                        healthy=True,
                        tipg_enabled=data.get("services", {}).get("tipg", {}).get("enabled", False),
                        stac_api_enabled=data.get("services", {}).get("stac_api", {}).get("enabled", False),
                        version=data.get("version")
                    )
                else:
                    return ServiceLayerHealth(healthy=False)

        except Exception as e:
            logger.warning(f"Service Layer health check failed: {e}")
            return ServiceLayerHealth(healthy=False)
