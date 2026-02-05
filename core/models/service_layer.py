# ============================================================================
# CLAUDE CONTEXT - SERVICE LAYER INTEGRATION MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core model - Pydantic models for Service Layer (rmhtitiler) API
# PURPOSE: Typed request/response models for webhook and health calls
# CREATED: 05 FEB 2026 (F1.6 - TiPG Collection Refresh)
# EXPORTS: CollectionRefreshResponse, ServiceLayerHealth
# DEPENDENCIES: pydantic
# ============================================================================
"""
Service Layer Integration Models.

Models for communicating with the Service Layer (rmhtitiler) webhooks.
The Service Layer runs TiTiler + TiPG + stac-fastapi in a unified Docker
container and exposes admin webhooks for catalog management.

Models:
    CollectionRefreshResponse - Response from POST /admin/refresh-collections
    ServiceLayerHealth - Response from GET /health
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class CollectionRefreshResponse(BaseModel):
    """
    Response from TiPG collection refresh webhook.

    POST /admin/refresh-collections on the Service Layer.
    Triggers TiPG to re-scan PostGIS for new/removed collections.
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

    GET /health on the Service Layer.
    """
    healthy: bool
    tipg_enabled: bool = False
    stac_api_enabled: bool = False
    version: Optional[str] = None
