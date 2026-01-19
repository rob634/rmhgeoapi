# ============================================================================
# PLATFORM CATALOG HTTP TRIGGERS - B2B STAC Access
# ============================================================================
# STATUS: Trigger layer - B2B catalog endpoints for DDH integration
# PURPOSE: HTTP handlers for Platform Catalog API (lookup, item, assets)
# CREATED: 16 JAN 2026
# EPIC: F12.8 API Documentation Hub - B2B STAC Catalog Access
# ============================================================================
"""
Platform Catalog HTTP Triggers - B2B STAC Access.

Provides DDH-facing HTTP endpoints for STAC catalog verification and asset URLs.
These endpoints allow DDH to:

1. Verify processing completed (lookup by DDH identifiers)
2. Retrieve full STAC item metadata
3. Get asset URLs with pre-built TiTiler visualization URLs

Endpoints:
    GET /api/platform/catalog/lookup - Lookup by DDH identifiers
    GET /api/platform/catalog/item/{collection_id}/{item_id} - Get STAC item
    GET /api/platform/catalog/assets/{collection_id}/{item_id} - Get asset URLs
    GET /api/platform/catalog/dataset/{dataset_id} - List items for dataset

Security:
    All endpoints under /api/platform/ prefix for gateway routing.
    Gateway can apply DDH-specific authentication.

Exports:
    platform_catalog_lookup: Lookup by DDH identifiers
    platform_catalog_item: Get full STAC item
    platform_catalog_assets: Get asset URLs with TiTiler
    platform_catalog_dataset: List items for dataset

Dependencies:
    services.platform_catalog_service: Business logic
"""

import json
from datetime import datetime, timezone
from typing import Optional

import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_platform_catalog")


# ============================================================================
# CATALOG LOOKUP
# ============================================================================

async def platform_catalog_lookup(req: func.HttpRequest) -> func.HttpResponse:
    """
    Lookup STAC item by DDH identifiers.

    GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z

    Verifies that a STAC item exists for the given DDH identifiers and
    returns its location in the catalog. This is the primary endpoint
    for DDH to verify processing completed.

    Query Parameters:
        dataset_id (required): DDH dataset identifier
        resource_id (required): DDH resource identifier
        version_id (required): DDH version identifier

    Response (found):
        {
            "found": true,
            "stac": {
                "collection_id": "flood-hazard-2024",
                "item_id": "magallanes-region-flood",
                "item_url": "/api/platform/catalog/item/...",
                "assets_url": "/api/platform/catalog/assets/..."
            },
            "processing": {
                "request_id": "a3f2c1b8...",
                "job_id": "abc123...",
                "completed_at": "2026-01-15T10:00:00Z"
            },
            "metadata": {
                "bbox": [-75.5, -56.5, -66.5, -49.0],
                "datetime": "2026-01-15T00:00:00Z"
            },
            "ddh_refs": {...}
        }

    Response (not found):
        {
            "found": false,
            "reason": "job_not_completed",
            "message": "Job is processing...",
            "status_url": "/api/platform/status/..."
        }
    """
    logger.info("Platform catalog lookup endpoint called")

    try:
        # Extract required parameters
        dataset_id = req.params.get('dataset_id')
        resource_id = req.params.get('resource_id')
        version_id = req.params.get('version_id')

        # Validate required parameters
        missing = []
        if not dataset_id:
            missing.append('dataset_id')
        if not resource_id:
            missing.append('resource_id')
        if not version_id:
            missing.append('version_id')

        if missing:
            return func.HttpResponse(
                json.dumps({
                    "error": "missing_parameters",
                    "message": f"Missing required query parameters: {', '.join(missing)}",
                    "required": ["dataset_id", "resource_id", "version_id"],
                    "example": "/api/platform/catalog/lookup?dataset_id=flood-data&resource_id=res-001&version_id=v1.0"
                }, indent=2),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Perform lookup
        from services.platform_catalog_service import get_platform_catalog_service
        service = get_platform_catalog_service()

        result = service.lookup_by_ddh_ids(dataset_id, resource_id, version_id)

        # Add DDH refs to response
        result["ddh_refs"] = {
            "dataset_id": dataset_id,
            "resource_id": resource_id,
            "version_id": version_id
        }
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog lookup failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "lookup_failed",
                "message": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, indent=2),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# GET STAC ITEM
# ============================================================================

async def platform_catalog_item(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get full STAC item by collection and item ID.

    GET /api/platform/catalog/item/{collection_id}/{item_id}

    Retrieves the complete STAC item including all metadata and assets.
    This is a B2B-friendly wrapper around the STAC API that:
    - Doesn't require knowledge of STAC API conventions
    - Returns consistent error formats
    - Adds platform-specific metadata

    Path Parameters:
        collection_id: STAC collection ID
        item_id: STAC item ID

    Response (found):
        Standard STAC Item (GeoJSON Feature) with:
        - type: "Feature"
        - stac_version: "1.0.0"
        - id, collection, geometry, bbox
        - properties (including platform:* identifiers)
        - assets
        - links

    Response (not found):
        {
            "error": "item_not_found",
            "message": "STAC item 'X' not found in collection 'Y'",
            "collection_id": "Y",
            "item_id": "X"
        }
    """
    logger.info("Platform catalog item endpoint called")

    try:
        # Extract path parameters
        collection_id = req.route_params.get('collection_id')
        item_id = req.route_params.get('item_id')

        if not collection_id or not item_id:
            return func.HttpResponse(
                json.dumps({
                    "error": "missing_parameters",
                    "message": "Both collection_id and item_id are required in path",
                    "example": "/api/platform/catalog/item/{collection_id}/{item_id}"
                }, indent=2),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        logger.debug(f"Getting item: {collection_id}/{item_id}")

        # Get item from repository
        from infrastructure.pgstac_repository import PgStacRepository
        repo = PgStacRepository()

        item = repo.get_item(item_id, collection_id)

        if not item:
            return func.HttpResponse(
                json.dumps({
                    "error": "item_not_found",
                    "message": f"STAC item '{item_id}' not found in collection '{collection_id}'",
                    "collection_id": collection_id,
                    "item_id": item_id,
                    "suggestion": "Use /api/platform/catalog/lookup to verify item exists"
                }, indent=2),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        # Return the full STAC item
        return func.HttpResponse(
            json.dumps(item, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog item failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "get_item_failed",
                "message": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, indent=2),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# GET ASSET URLS
# ============================================================================

async def platform_catalog_assets(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get asset URLs with pre-built TiTiler visualization URLs.

    GET /api/platform/catalog/assets/{collection_id}/{item_id}
    GET /api/platform/catalog/assets/{collection_id}/{item_id}?include_titiler=false

    Retrieves asset URLs from a STAC item and generates pre-built TiTiler
    URLs for visualization. This is the primary endpoint for DDH to get
    URLs for displaying data in their UI.

    Path Parameters:
        collection_id: STAC collection ID
        item_id: STAC item ID

    Query Parameters:
        include_titiler: Include TiTiler URLs (default: true)

    Response:
        {
            "item_id": "magallanes-region-flood",
            "collection_id": "flood-hazard-2024",
            "bbox": [-75.5, -56.5, -66.5, -49.0],
            "assets": {
                "data": {
                    "href": "https://storage.blob.../cog.tif",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "size_mb": 125.5
                }
            },
            "titiler": {
                "preview": "https://titiler.example.com/cog/preview?url=...",
                "tiles": "https://titiler.example.com/cog/tiles/{z}/{x}/{y}?url=...",
                "info": "https://titiler.example.com/cog/info?url=...",
                "tilejson": "https://titiler.example.com/cog/tilejson.json?url=..."
            },
            "temporal": {
                "datetime": "2026-01-15T00:00:00Z"
            },
            "platform_refs": {
                "dataset_id": "flood-data",
                "resource_id": "res-001",
                "version_id": "v1.0"
            }
        }
    """
    logger.info("Platform catalog assets endpoint called")

    try:
        # Extract path parameters
        collection_id = req.route_params.get('collection_id')
        item_id = req.route_params.get('item_id')

        if not collection_id or not item_id:
            return func.HttpResponse(
                json.dumps({
                    "error": "missing_parameters",
                    "message": "Both collection_id and item_id are required in path",
                    "example": "/api/platform/catalog/assets/{collection_id}/{item_id}"
                }, indent=2),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Parse optional query parameter
        include_titiler = req.params.get('include_titiler', 'true').lower() == 'true'

        logger.debug(f"Getting assets: {collection_id}/{item_id}, titiler={include_titiler}")

        # Get asset URLs from service
        from services.platform_catalog_service import get_platform_catalog_service
        service = get_platform_catalog_service()

        result = service.get_asset_urls(collection_id, item_id, include_titiler)

        # Check for error response
        if "error" in result:
            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        # Add timestamp
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog assets failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "get_assets_failed",
                "message": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, indent=2),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# LIST ITEMS FOR DATASET
# ============================================================================

async def platform_catalog_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all STAC items for a DDH dataset.

    GET /api/platform/catalog/dataset/{dataset_id}
    GET /api/platform/catalog/dataset/{dataset_id}?limit=50

    Returns all STAC items that have the specified platform:dataset_id.
    Useful for DDH to see all versions/resources within a dataset.

    Path Parameters:
        dataset_id: DDH dataset identifier

    Query Parameters:
        limit: Maximum items to return (default: 100, max: 1000)

    Response:
        {
            "dataset_id": "flood-data",
            "count": 5,
            "items": [
                {
                    "item_id": "flood-item-1",
                    "collection_id": "flood-collection",
                    "bbox": [...],
                    "datetime": "2026-01-15T00:00:00Z",
                    "resource_id": "res-001",
                    "version_id": "v1.0"
                },
                ...
            ],
            "timestamp": "..."
        }
    """
    logger.info("Platform catalog dataset endpoint called")

    try:
        # Extract path parameter
        dataset_id = req.route_params.get('dataset_id')

        if not dataset_id:
            return func.HttpResponse(
                json.dumps({
                    "error": "missing_parameters",
                    "message": "dataset_id is required in path",
                    "example": "/api/platform/catalog/dataset/{dataset_id}"
                }, indent=2),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Parse optional limit
        try:
            limit = min(int(req.params.get('limit', '100')), 1000)
        except ValueError:
            limit = 100

        logger.debug(f"Listing items for dataset: {dataset_id}, limit={limit}")

        # Get items from service
        from services.platform_catalog_service import get_platform_catalog_service
        service = get_platform_catalog_service()

        result = service.list_items_for_dataset(dataset_id, limit)
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog dataset failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "list_dataset_failed",
                "message": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, indent=2),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'platform_catalog_lookup',
    'platform_catalog_item',
    'platform_catalog_assets',
    'platform_catalog_dataset'
]
