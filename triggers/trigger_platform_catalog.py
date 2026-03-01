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


def _catalog_error_response(status_code: int, error: str, error_type: str = "server_error") -> func.HttpResponse:
    """Standard error response for catalog endpoints."""
    return func.HttpResponse(
        json.dumps({"success": False, "error": error, "error_type": error_type}, indent=2),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )


# ============================================================================
# CATALOG LOOKUP (UNIFIED - 10 FEB 2026)
# ============================================================================

async def platform_catalog_lookup(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified lookup by DDH identifiers - works for BOTH raster and vector.

    GET /api/platform/catalog/lookup?dataset_id=X&resource_id=Y&version_id=Z

    V0.8 UNIFIED (10 FEB 2026):
    This endpoint now queries app.geospatial_assets directly (source of truth),
    bypassing STAC and OGC Features APIs. Works for both rasters AND vectors.

    Query Parameters:
        dataset_id (required): DDH dataset identifier
        resource_id (required): DDH resource identifier
        version_id (required): DDH version identifier

    Response (found - vector):
        {
            "found": true,
            "asset_id": "a7803a5e9160779290f54877fc65fbe0",
            "data_type": "vector",
            "status": {"processing": "completed", "approval": "approved", ...},
            "metadata": {"bbox": [...], "title": "...", ...},
            "vector": {
                "table_name": "eleventhhourtest_v8_testing_v10",
                "feature_count": 3301,
                "geometry_type": "MultiPolygon",
                "tiles": {"mvt": "...", "tilejson": "..."}
            },
            "ddh_refs": {...}
        }

    Response (found - raster):
        {
            "found": true,
            "asset_id": "...",
            "data_type": "raster",
            "metadata": {"bbox": [...], ...},
            "raster": {
                "blob_path": "...",
                "band_count": 3,
                "tiles": {"xyz": "...", "preview": "..."}
            },
            "ddh_refs": {...}
        }

    Response (not found):
        {
            "found": false,
            "reason": "asset_not_found",
            "message": "No asset found for these DDH identifiers...",
            "suggestion": "Submit the data via POST /api/platform/submit"
        }
    """
    logger.info("Platform catalog lookup endpoint called (unified)")

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
            return _catalog_error_response(
                400,
                f"Missing required query parameters: {', '.join(missing)}",
                "ValidationError"
            )

        # Perform unified lookup (works for both raster and vector)
        from services.platform_catalog_service import get_platform_catalog_service
        service = get_platform_catalog_service()

        result = service.lookup_unified(dataset_id, resource_id, version_id)

        # Return 404 for not-found results
        if not result.get("found", True):
            result["success"] = False
            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        result["success"] = True
        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog lookup failed: {e}", exc_info=True)
        return _catalog_error_response(500, "Internal server error")


# ============================================================================
# CATALOG LOOKUP BY ASSET ID (NEW - 10 FEB 2026)
# ============================================================================

async def platform_catalog_asset_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get asset details and service URLs by asset_id.

    GET /api/platform/catalog/asset/{asset_id}

    V0.8 UNIFIED (10 FEB 2026):
    Returns asset details with appropriate service URLs based on data_type.

    Path Parameters:
        asset_id: GeospatialAsset identifier (SHA256 hash)

    Response (vector):
        {
            "found": true,
            "asset_id": "a7803a5e9160779290f54877fc65fbe0",
            "data_type": "vector",
            "vector": {"table_name": "...", "tiles": {...}},
            "ddh_refs": {...}
        }

    Response (raster):
        {
            "found": true,
            "asset_id": "...",
            "data_type": "raster",
            "raster": {"blob_path": "...", "tiles": {...}},
            "ddh_refs": {...}
        }
    """
    logger.info("Platform catalog asset by ID endpoint called")

    try:
        # Extract path parameter
        asset_id = req.route_params.get('asset_id')

        if not asset_id:
            return func.HttpResponse(
                json.dumps({
                    "error": "missing_parameters",
                    "message": "asset_id is required in path",
                    "example": "/api/platform/catalog/asset/{asset_id}"
                }, indent=2),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        logger.debug(f"Getting asset by ID: {asset_id[:16]}...")

        # Get asset URLs from service
        from services.platform_catalog_service import get_platform_catalog_service
        service = get_platform_catalog_service()

        result = service.get_unified_urls(asset_id)

        # Check if not found
        if not result.get("found", True):
            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog asset by ID failed: {e}", exc_info=True)
        return _catalog_error_response(500, "Internal server error")


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
            return _catalog_error_response(
                404,
                f"STAC item '{item_id}' not found in collection '{collection_id}'",
                "NotFound"
            )

        # Return the full STAC item
        return func.HttpResponse(
            json.dumps(item, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform catalog item failed: {e}", exc_info=True)
        return _catalog_error_response(500, "Internal server error")


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
        return _catalog_error_response(500, "Internal server error")


# ============================================================================
# LIST ASSETS FOR DATASET (UNIFIED - 10 FEB 2026)
# ============================================================================

async def platform_catalog_dataset(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all assets for a DDH dataset - works for BOTH raster and vector.

    GET /api/platform/catalog/dataset/{dataset_id}
    GET /api/platform/catalog/dataset/{dataset_id}?limit=50&offset=0

    V0.8 UNIFIED (10 FEB 2026):
    This endpoint now queries app.geospatial_assets directly (source of truth),
    returning all assets (rasters AND vectors) for a dataset.

    Path Parameters:
        dataset_id: DDH dataset identifier

    Query Parameters:
        limit: Maximum items to return (default: 100, max: 1000)
        offset: Pagination offset (default: 0)

    Response:
        {
            "dataset_id": "eleventhhourtest",
            "count": 3,
            "limit": 100,
            "offset": 0,
            "items": [
                {
                    "asset_id": "a7803a5e9160779290f54877fc65fbe0",
                    "data_type": "vector",
                    "bbox": [-66.45, -56.32, -64.77, -54.68],
                    "processing_status": "completed",
                    "approval_state": "approved",
                    "table_name": "eleventhhourtest_v8_testing_v10",
                    "feature_count": 3301,
                    "ddh_refs": {"dataset_id": "...", "resource_id": "...", "version_id": "..."}
                },
                {
                    "asset_id": "b8914b6f0271880391e65988gd76gcf1",
                    "data_type": "raster",
                    "bbox": [...],
                    "stac_item_id": "...",
                    "stac_collection_id": "...",
                    "ddh_refs": {...}
                }
            ],
            "timestamp": "2026-02-10T21:05:59Z"
        }
    """
    logger.info("Platform catalog dataset endpoint called (unified)")

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

        # Parse optional limit and offset
        try:
            limit = min(int(req.params.get('limit', '100')), 1000)
        except ValueError:
            limit = 100

        try:
            offset = max(int(req.params.get('offset', '0')), 0)
        except ValueError:
            offset = 0

        logger.debug(f"Listing assets for dataset: {dataset_id}, limit={limit}, offset={offset}")

        # Get items from unified service
        from services.platform_catalog_service import get_platform_catalog_service
        service = get_platform_catalog_service()

        result = service.list_dataset_unified(dataset_id, limit, offset)

        if result["count"] == 0 and offset == 0:
            return _catalog_error_response(404, f"Dataset '{dataset_id}' not found", "NotFound")

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        error_type = type(e).__name__
        ds_id = locals().get('dataset_id', 'unknown')
        logger.error(f"Platform catalog dataset failed: {e}", exc_info=True)
        return _catalog_error_response(
            500,
            f"Internal server error retrieving dataset '{ds_id}'. "
            f"Error type: {error_type}. Contact support with this dataset_id for investigation."
        )


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'platform_catalog_lookup',
    'platform_catalog_asset_by_id',  # NEW: Get by asset_id (10 FEB 2026)
    'platform_catalog_item',         # STAC item access (preserved for backward compat)
    'platform_catalog_assets',       # STAC assets access (preserved for backward compat)
    'platform_catalog_dataset'
]
