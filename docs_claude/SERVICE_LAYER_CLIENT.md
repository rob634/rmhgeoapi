# Service Layer Client Integration

**Created**: 04 FEB 2026
**Status**: PLANNED
**Priority**: MEDIUM - Enables immediate TiPG collection visibility after vector ETL
**Epic**: E1 (Vector Data Pipeline)

> **PREREQUISITE**: ✅ F1.7 (Geo Schema Table Name Validation) - COMPLETE (04 FEB 2026)
> Table names starting with digits are now prefixed with `t_` in `_slugify_for_postgres()`.

---

## Problem Statement

After vector ETL completes and creates a PostGIS table, TiPG (in the Service Layer) doesn't immediately see the new collection. TiPG caches its collection list and requires either:
1. Cache TTL expiration (default 5 minutes if enabled)
2. Application restart
3. **Manual webhook call** (the solution we're implementing)

The Service Layer (rmhtitiler) has a webhook endpoint:
```
POST /admin/refresh-collections
```

This endpoint refreshes TiPG's collection catalog immediately. We need to call this from the ETL app after vector table creation.

---

## Architecture Decision

### Why a Repository Pattern?

Following existing codebase patterns where authentication is encapsulated in repositories:
- `BlobRepository` - Azure Storage auth via `DefaultAzureCredential`
- `PostgresqlRepository` - Database auth via connection strings
- `ServiceBusRepository` - Service Bus auth via connection strings

The Service Layer client will follow the same pattern:
- **Repository** handles HTTP + Azure AD authentication internally
- **Callers** (handlers) don't manage tokens

### File Structure

```
core/models/
└── service_layer.py           # Pydantic models

infrastructure/
└── service_layer_client.py    # ServiceLayerClient repository
```

---

## Service Layer Webhook Details

### Endpoint

| Property | Value |
|----------|-------|
| **URL** | `{TITILER_BASE_URL}/admin/refresh-collections` |
| **Method** | `POST` |
| **Auth** | Azure AD Bearer token (when `ADMIN_AUTH_ENABLED=true`) |
| **Source** | `rmhtitiler/geotiler/routers/admin.py:111-189` |

### Response Schema

```json
{
    "status": "success",
    "collections_before": 42,
    "collections_after": 43,
    "new_collections": ["geo.new_table_name"],
    "removed_collections": [],
    "refresh_time": "2026-02-04T14:30:00Z"
}
```

### Authentication Requirements

When `ADMIN_AUTH_ENABLED=true` on Service Layer:

| Setting | Value |
|---------|-------|
| `ADMIN_AUTH_ENABLED` | `true` |
| `ADMIN_ALLOWED_APP_IDS` | Comma-separated MI client IDs |
| `AZURE_TENANT_ID` | Azure AD tenant ID |

The calling app (rmhgeoapi Function App or Docker Worker) must:
1. Have a Managed Identity
2. MI client ID must be in `ADMIN_ALLOWED_APP_IDS` on Service Layer
3. Acquire token for the Service Layer's app registration

---

## Implementation Plan

### Phase 1: Data Models

**File**: `core/models/service_layer.py`

```python
"""
Service Layer integration models.

Models for communicating with the Service Layer (rmhtitiler) webhooks.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class CollectionRefreshRequest(BaseModel):
    """
    Request to refresh TiPG collection catalog.

    Currently no request body needed - the endpoint refreshes all collections.
    This model exists for future extensibility (e.g., refresh specific schema).
    """
    schema_filter: Optional[str] = Field(
        default=None,
        description="Optional: Only refresh collections in this schema (future)"
    )


class CollectionRefreshResponse(BaseModel):
    """
    Response from TiPG collection refresh webhook.
    """
    status: str = Field(..., description="'success' or 'error'")
    collections_before: int = Field(default=0, description="Collection count before refresh")
    collections_after: int = Field(default=0, description="Collection count after refresh")
    new_collections: List[str] = Field(default_factory=list, description="Newly discovered collection IDs")
    removed_collections: List[str] = Field(default_factory=list, description="Removed collection IDs")
    refresh_time: datetime = Field(..., description="Timestamp of refresh")
    error: Optional[str] = Field(default=None, description="Error message if status='error'")


class ServiceLayerHealth(BaseModel):
    """
    Service Layer health status.
    """
    healthy: bool
    tipg_enabled: bool = False
    stac_api_enabled: bool = False
    version: Optional[str] = None
```

### Phase 2: Repository Implementation

**File**: `infrastructure/service_layer_client.py`

```python
"""
Service Layer Client Repository.

Handles HTTP communication with the Service Layer (rmhtitiler) webhooks.
Authentication uses DefaultAzureCredential for Managed Identity tokens.

Usage:
    from infrastructure.service_layer_client import ServiceLayerClient

    client = ServiceLayerClient()
    result = await client.refresh_tipg_collections()
    if result.status == "success":
        logger.info(f"Refreshed TiPG: {result.new_collections}")
"""

import logging
from typing import Optional
from datetime import datetime, timezone

import httpx
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AccessToken

from config import get_config
from core.models.service_layer import CollectionRefreshResponse, ServiceLayerHealth

logger = logging.getLogger(__name__)


class ServiceLayerClient:
    """
    Client for Service Layer (rmhtitiler) API calls.

    Handles:
    - Azure AD token acquisition via DefaultAzureCredential
    - HTTP calls to Service Layer webhooks
    - Response parsing into typed models

    Authentication:
    - Uses DefaultAzureCredential (same as BlobRepository)
    - Acquires tokens scoped to Service Layer app registration
    - Token refresh is automatic
    """

    # Token cache (class-level for reuse across instances)
    _token_cache: Optional[AccessToken] = None

    def __init__(self):
        """Initialize client with config."""
        self._config = get_config()
        self._credential = DefaultAzureCredential()

        # Service Layer base URL from config
        self._base_url = self._config.titiler_base_url.rstrip('/')

        # Scope for token - the Service Layer's app registration
        # Format: api://<app-id>/.default or https://<app-id-uri>/.default
        # This should be configured via environment variable
        self._token_scope = getattr(self._config, 'service_layer_token_scope', None)

    def _get_auth_headers(self) -> dict:
        """
        Get authorization headers with fresh Azure AD token.

        Returns:
            Dict with Authorization header, or empty dict if auth not configured
        """
        if not self._token_scope:
            # Auth not configured - Service Layer may have ADMIN_AUTH_ENABLED=false
            logger.debug("SERVICE_LAYER_TOKEN_SCOPE not configured, calling without auth")
            return {}

        try:
            # Check if cached token is still valid (with 5 min buffer)
            if self._token_cache:
                expires_on = datetime.fromtimestamp(self._token_cache.expires_on, tz=timezone.utc)
                if expires_on > datetime.now(timezone.utc).replace(tzinfo=timezone.utc) + timedelta(minutes=5):
                    return {"Authorization": f"Bearer {self._token_cache.token}"}

            # Acquire new token
            token = self._credential.get_token(self._token_scope)
            ServiceLayerClient._token_cache = token

            logger.debug(f"Acquired Service Layer token, expires: {datetime.fromtimestamp(token.expires_on)}")
            return {"Authorization": f"Bearer {token.token}"}

        except Exception as e:
            logger.warning(f"Failed to acquire Service Layer token: {e}")
            # Return empty - let the call fail with 401 if auth is required
            return {}

    async def refresh_tipg_collections(self) -> CollectionRefreshResponse:
        """
        Call the TiPG collection refresh webhook.

        POST /admin/refresh-collections

        Returns:
            CollectionRefreshResponse with refresh results

        Raises:
            httpx.HTTPStatusError: If request fails
        """
        url = f"{self._base_url}/admin/refresh-collections"
        headers = self._get_auth_headers()

        logger.info(f"Calling TiPG refresh webhook: {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()

            data = response.json()
            result = CollectionRefreshResponse(**data)

            logger.info(
                f"TiPG refresh complete: {result.collections_before} -> {result.collections_after} "
                f"(+{len(result.new_collections)})"
            )

            return result

    async def health_check(self) -> ServiceLayerHealth:
        """
        Check Service Layer health.

        GET /health

        Returns:
            ServiceLayerHealth with status
        """
        url = f"{self._base_url}/health"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)

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
```

### Phase 3: Configuration

**Add to `config/app_config.py`**:

```python
# Service Layer Integration (04 FEB 2026)
# ========================================================================
# For calling Service Layer webhooks (e.g., TiPG collection refresh)
# ========================================================================

service_layer_token_scope: str = Field(
    default_factory=lambda: os.environ.get(
        "SERVICE_LAYER_TOKEN_SCOPE",
        ""  # Empty = no auth (for local dev or ADMIN_AUTH_ENABLED=false)
    ),
    description="OAuth scope for Service Layer token acquisition. Format: api://<app-id>/.default"
)
```

**Environment variable**:
```bash
# Add to Function App and Docker Worker settings
SERVICE_LAYER_TOKEN_SCOPE=api://<service-layer-app-id>/.default
```

### Phase 4: Wire to Vector ETL

**Modify**: `services/handler_vector_docker_complete.py`

After Phase 4 (STAC creation), add:

```python
# Phase 5: Refresh TiPG collection catalog
# ========================================================================
# Notify Service Layer that a new collection exists so TiPG picks it up
# immediately without waiting for cache TTL or restart.
# ========================================================================
try:
    from infrastructure.service_layer_client import ServiceLayerClient

    client = ServiceLayerClient()
    refresh_result = await client.refresh_tipg_collections()

    if refresh_result.status == "success":
        logger.info(
            f"TiPG catalog refreshed: new collections = {refresh_result.new_collections}"
        )
    else:
        logger.warning(f"TiPG refresh returned error: {refresh_result.error}")

except Exception as e:
    # Non-fatal: TiPG will eventually see the collection via TTL
    logger.warning(f"Failed to refresh TiPG catalog (non-fatal): {e}")
```

### Phase 5: Documentation

1. Add to `ado_wiki/architecture/SERVICE_LAYER.md` - Section on ETL integration
2. Add to `docs_claude/ENVIRONMENT_VARIABLES.md` - New env var
3. Update rmhtitiler CLAUDE.md with integration notes

---

## Testing Plan

### Manual Test (Before Implementation)

```bash
# 1. Check current collections
curl https://<titiler-url>/vector/collections | jq '.collections | length'

# 2. Call refresh webhook (no auth if ADMIN_AUTH_ENABLED=false)
curl -X POST https://<titiler-url>/admin/refresh-collections

# 3. Verify response
{
  "status": "success",
  "collections_before": 42,
  "collections_after": 42,
  "new_collections": [],
  "removed_collections": [],
  "refresh_time": "2026-02-04T..."
}
```

### Integration Test

1. Submit vector ETL job
2. Wait for completion
3. Verify `new_collections` in job result includes the new table
4. Verify TiPG `/vector/collections` immediately shows the new collection

---

## Configuration Checklist

### Service Layer (rmhtitiler)

| Setting | Value | Notes |
|---------|-------|-------|
| `ADMIN_AUTH_ENABLED` | `true` | Enable auth for production |
| `ADMIN_ALLOWED_APP_IDS` | `<fa-mi-id>,<docker-mi-id>` | Function App + Docker Worker MIs |
| `AZURE_TENANT_ID` | `<tenant-id>` | Your Azure AD tenant |

### ETL App (rmhgeoapi)

| Setting | Value | Notes |
|---------|-------|-------|
| `SERVICE_LAYER_TOKEN_SCOPE` | `api://<app-id>/.default` | Service Layer app registration |

---

## Effort Estimate

| Phase | Description | Effort |
|-------|-------------|--------|
| Phase 1 | Data models | 15 min |
| Phase 2 | Repository implementation | 30 min |
| Phase 3 | Config + env vars | 15 min |
| Phase 4 | Wire to vector ETL | 15 min |
| Phase 5 | Documentation | 15 min |
| **Total** | | **~1.5 hours** |

Plus Azure AD configuration (if not already done):
- Create app registration for Service Layer (if needed)
- Add MI client IDs to `ADMIN_ALLOWED_APP_IDS`

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| `rmhtitiler/geotiler/routers/admin.py` | Webhook implementation |
| `rmhtitiler/geotiler/auth/admin_auth.py` | Auth middleware |
| `ado_wiki/architecture/SERVICE_LAYER.md` | Service Layer architecture |
| `docs_claude/ENVIRONMENT_VARIABLES.md` | Env var reference |

---

**Author**: Claude
**Last Updated**: 04 FEB 2026
