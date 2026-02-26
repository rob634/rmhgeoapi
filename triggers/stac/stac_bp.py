# ============================================================================
# STAC BLUEPRINT - Unified STAC API & Admin Endpoints
# ============================================================================
# STATUS: Trigger layer - Azure Functions Blueprint for all stac/* routes
# PURPOSE: Consolidate all 19 STAC endpoints into single blueprint
# CREATED: 24 JAN 2026 (V0.8 Phase 17.3)
# EXPORTS: bp
# DEPENDENCIES: azure.functions, infrastructure.pgstac_bootstrap
# ============================================================================
"""
STAC Blueprint - Unified STAC API & Admin Endpoints.

Routes (19 total):

    STAC API v1.0.0 Core (6 routes - OGC Compliant):
        GET  /stac                                    Landing page
        GET  /stac/conformance                        Conformance classes
        GET  /stac/collections                        List collections
        GET  /stac/collections/{id}                   Get collection
        GET  /stac/collections/{id}/items             List items (paginated)
        GET  /stac/collections/{id}/items/{item_id}   Get item

    Admin - Initialization (3 routes):
        POST /stac/collections/{tier}                    Create collection by tier
        POST /stac/collections/{tier}                 Create tier collection
        POST /stac/nuke                               Clear STAC data

    Admin - Repair (3 routes):
        GET  /stac/repair/test                        Test repair handler
        POST /stac/repair/inventory                   Generate inventory
        POST /stac/repair/item                        Repair single item

    Admin - Catalog Operations (2 routes):
        POST /stac/extract                            Extract raster metadata
        POST /stac/vector                             Catalog vector table

    Admin - Inspection (5 routes):
        GET  /stac/schema/info                        PgSTAC schema info
        GET  /stac/collections/summary                Quick summary
        GET  /stac/collections/{id}/stats             Collection statistics
        GET  /stac/items/{item_id}                    Item lookup shortcut
        GET  /stac/health                             Health metrics

    Admin - Materialization CRUD (6 routes, 26 FEB 2026):
        POST   /stac/admin/collections                          Create empty collection
        PUT    /stac/admin/collections/{collection_id}          Update collection metadata
        DELETE /stac/admin/collections/{collection_id}          Delete collection + items
        DELETE /stac/admin/collections/{cid}/items/{item_id}    Remove item
        POST   /stac/admin/rebuild                              Rebuild all from DB
        POST   /stac/admin/rebuild/{collection_id}              Rebuild single collection
"""

import azure.functions as func
from azure.functions import Blueprint
import json
import logging
from datetime import datetime, timezone
from typing import Any

from .config import get_stac_config
from .service import STACAPIService

bp = Blueprint()
logger = logging.getLogger(__name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_base_url(req: func.HttpRequest) -> str:
    """Extract base URL from request."""
    config = get_stac_config()
    if config.stac_base_url:
        return config.stac_base_url.rstrip("/")

    full_url = req.url
    if "/api/stac" in full_url:
        return full_url.split("/api/stac")[0]

    return "http://localhost:7071"


def _json_response(
    data: Any,
    status_code: int = 200,
    content_type: str = "application/json"
) -> func.HttpResponse:
    """Create JSON HTTP response."""
    if hasattr(data, 'model_dump'):
        data = data.model_dump(mode='json', exclude_none=True)

    return func.HttpResponse(
        body=json.dumps(data, indent=2, default=str),
        status_code=status_code,
        mimetype=content_type
    )


def _error_response(
    message: str,
    status_code: int = 400,
    error_type: str = "BadRequest"
) -> func.HttpResponse:
    """Create error response."""
    return func.HttpResponse(
        body=json.dumps({"code": error_type, "description": message}, indent=2),
        status_code=status_code,
        mimetype="application/json"
    )


# ============================================================================
# STAC API v1.0.0 CORE (6 routes)
# ============================================================================

@bp.route(route="stac", methods=["GET"])
def stac_landing(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API v1.0.0 landing page.

    GET /api/stac

    Returns:
        STAC Catalog object with links to conformance, collections, etc.
    """
    try:
        logger.info("STAC API Landing Page requested")
        config = get_stac_config()
        service = STACAPIService(config)
        base_url = _get_base_url(req)
        catalog = service.get_catalog(base_url)
        return _json_response(catalog)
    except Exception as e:
        logger.error(f"Error generating STAC landing page: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/conformance", methods=["GET"])
def stac_conformance(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API v1.0.0 conformance classes.

    GET /api/stac/conformance

    Returns:
        Conformance object listing supported STAC/OGC specifications.
    """
    try:
        logger.info("STAC API Conformance requested")
        config = get_stac_config()
        service = STACAPIService(config)
        conformance = service.get_conformance()
        return _json_response(conformance)
    except Exception as e:
        logger.error(f"Error generating STAC conformance: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/collections", methods=["GET"])
def stac_collections_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API v1.0.0 collections list.

    GET /api/stac/collections

    Returns:
        Collections object with array of STAC collections.
    """
    try:
        logger.info("STAC API Collections list requested")
        config = get_stac_config()
        service = STACAPIService(config)
        base_url = _get_base_url(req)
        collections = service.get_collections(base_url)

        if 'error' in collections:
            return _error_response(collections['error'], 500, "InternalServerError")

        return _json_response(collections)
    except Exception as e:
        logger.error(f"Error retrieving collections: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/collections/{collection_id}", methods=["GET"])
def stac_collection_detail(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API v1.0.0 collection detail.

    GET /api/stac/collections/{collection_id}

    Returns:
        Single STAC Collection object.
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return _error_response("collection_id is required", 400)

        logger.info(f"STAC API Collection detail requested: {collection_id}")
        config = get_stac_config()
        service = STACAPIService(config)
        base_url = _get_base_url(req)
        collection = service.get_collection(collection_id, base_url)

        if 'error' in collection:
            status = 404 if 'not found' in collection['error'].lower() else 500
            error_type = "NotFound" if status == 404 else "InternalServerError"
            return _error_response(collection['error'], status, error_type)

        return _json_response(collection)
    except Exception as e:
        logger.error(f"Error retrieving collection: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/collections/{collection_id}/items", methods=["GET"])
def stac_items_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API v1.0.0 items list (paginated).

    GET /api/stac/collections/{collection_id}/items?limit=10&offset=0&bbox=...

    Query Parameters:
        limit: Max items to return (1-1000, default: 10)
        offset: Pagination offset (default: 0)
        bbox: Bounding box filter (minx,miny,maxx,maxy)

    Returns:
        GeoJSON FeatureCollection with STAC Items.
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return _error_response("collection_id is required", 400)

        # Parse query parameters
        limit = int(req.params.get('limit', 10))
        offset = int(req.params.get('offset', 0))
        bbox = req.params.get('bbox')

        if limit < 1 or limit > 1000:
            return _error_response("limit must be between 1 and 1000", 400)
        if offset < 0:
            return _error_response("offset must be >= 0", 400)

        logger.info(f"STAC API Items requested: collection={collection_id}, limit={limit}")
        config = get_stac_config()
        service = STACAPIService(config)
        base_url = _get_base_url(req)
        items = service.get_items(collection_id, base_url, limit, offset, bbox)

        if 'error' in items:
            status = 404 if 'not found' in items['error'].lower() else 500
            return _error_response(items['error'], status)

        return _json_response(items, content_type="application/geo+json")
    except ValueError as e:
        return _error_response(str(e), 400)
    except Exception as e:
        logger.error(f"Error retrieving items: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/collections/{collection_id}/items/{item_id}", methods=["GET"])
def stac_item_detail(req: func.HttpRequest) -> func.HttpResponse:
    """
    STAC API v1.0.0 item detail.

    GET /api/stac/collections/{collection_id}/items/{item_id}

    Returns:
        Single STAC Item (GeoJSON Feature).
    """
    try:
        collection_id = req.route_params.get('collection_id')
        item_id = req.route_params.get('item_id')

        if not collection_id:
            return _error_response("collection_id is required", 400)
        if not item_id:
            return _error_response("item_id is required", 400)

        logger.info(f"STAC API Item detail requested: {collection_id}/{item_id}")
        config = get_stac_config()
        service = STACAPIService(config)
        base_url = _get_base_url(req)
        item = service.get_item(collection_id, item_id, base_url)

        if 'error' in item:
            status = 404 if 'not found' in item['error'].lower() else 500
            return _error_response(item['error'], status)

        return _json_response(item, content_type="application/geo+json")
    except Exception as e:
        logger.error(f"Error retrieving item: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


# ============================================================================
# ADMIN - INITIALIZATION
# ============================================================================

@bp.route(route="stac/collections/{tier}", methods=["POST"])
def stac_collections_tier(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create STAC collection for Bronze/Silver/Gold tier.

    POST /api/stac/collections/{tier} where tier is: bronze, silver, or gold

    Body:
        {
            "container": "<bronze-container>",  // Required
            "collection_id": "custom-id",       // Optional
            "title": "Custom Title",            // Optional
            "description": "Custom description" // Optional
        }

    Returns:
        Collection creation result with collection_id.
    """
    from triggers.stac_collections import stac_collections_trigger
    return stac_collections_trigger.handle_request(req)


@bp.route(route="stac/nuke", methods=["POST"])
def stac_nuke(req: func.HttpRequest) -> func.HttpResponse:
    """
    NUCLEAR: Clear STAC items/collections (DEV/TEST ONLY).

    POST /api/stac/nuke?confirm=yes&mode=all

    Query Parameters:
        confirm: Must be "yes" (required)
        mode: "items", "collections", or "all" (default: "all")

    Returns:
        Deletion results with counts and execution time.

    WARNING: This clears STAC data but preserves pgstac schema.
    """
    from triggers.stac_nuke import stac_nuke_trigger
    return stac_nuke_trigger.handle_request(req)


# ============================================================================
# ADMIN - CATALOG OPERATIONS (2 routes)
# ============================================================================

@bp.route(route="stac/extract", methods=["POST"])
def stac_extract(req: func.HttpRequest) -> func.HttpResponse:
    """
    Extract STAC metadata from raster blob and insert into PgSTAC.

    POST /api/stac/extract

    Body:
        {
            "container": "<bronze-container>",     // Required
            "blob_name": "test/file.tif",          // Required
            "collection_id": "dev",                // Optional (default: "dev")
            "insert": true                         // Optional (default: true)
        }

    Returns:
        STAC Item metadata and insertion result.
    """
    from triggers.stac_extract import stac_extract_trigger
    return stac_extract_trigger.handle_request(req)


# ============================================================================
# ADMIN - INSPECTION (5 routes)
# ============================================================================

@bp.route(route="stac/schema/info", methods=["GET"])
def stac_schema_info(req: func.HttpRequest) -> func.HttpResponse:
    """
    Deep inspection of pgstac schema structure.

    GET /api/stac/schema/info

    Returns:
        Detailed schema information including:
        - Tables (with row counts, sizes, indexes)
        - Functions (first 20)
        - Roles
        - Total schema size
    """
    try:
        from infrastructure.pgstac_bootstrap import get_schema_info
        result = get_schema_info()
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in /stac/schema/info: {e}")
        return _json_response({'error': str(e)}, 500)


@bp.route(route="stac/collections/summary", methods=["GET"])
def stac_collections_summary(req: func.HttpRequest) -> func.HttpResponse:
    """
    Quick summary of all collections with statistics.

    GET /api/stac/collections/summary

    Returns:
        Summary with total counts and per-collection item counts.
    """
    try:
        from infrastructure.pgstac_bootstrap import get_collections_summary
        result = get_collections_summary()
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in /stac/collections/summary: {e}")
        return _json_response({'error': str(e)}, 500)


@bp.route(route="stac/collections/{collection_id}/stats", methods=["GET"])
def stac_collection_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Detailed statistics for a specific collection.

    GET /api/stac/collections/{collection_id}/stats

    Returns:
        Collection statistics including:
        - Item count
        - Spatial extent (actual bbox from items)
        - Temporal extent
        - Asset types and counts
        - Recent items
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return _json_response({'error': 'collection_id required'}, 400)

        from infrastructure.pgstac_bootstrap import get_collection_stats
        result = get_collection_stats(collection_id)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in /stac/collections/{{collection_id}}/stats: {e}")
        return _json_response({'error': str(e)}, 500)


@bp.route(route="stac/items/{item_id}", methods=["GET"])
def stac_item_lookup(req: func.HttpRequest) -> func.HttpResponse:
    """
    Look up a single STAC item by ID (shortcut - no collection required).

    GET /api/stac/items/{item_id}?collection_id={optional}

    Path Parameters:
        item_id: STAC item ID to retrieve

    Query Parameters:
        collection_id: Optional collection ID to narrow search

    Returns:
        STAC Item JSON or error if not found.
    """
    try:
        item_id = req.route_params.get('item_id')
        if not item_id:
            return _json_response({'error': 'item_id required'}, 400)

        collection_id = req.params.get('collection_id')

        from infrastructure.pgstac_bootstrap import get_item_by_id
        result = get_item_by_id(item_id, collection_id)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in /stac/items/{{item_id}}: {e}")
        return _json_response({'error': str(e)}, 500)


@bp.route(route="stac/health", methods=["GET"])
def stac_health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Overall pgstac health check with metrics.

    GET /api/stac/health

    Returns:
        Health status including:
        - Status (healthy/warning/error)
        - Version
        - Collection/item counts
        - Database size
        - Issues detected
    """
    try:
        from infrastructure.pgstac_bootstrap import get_health_metrics
        result = get_health_metrics()
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in /stac/health: {e}")
        return _json_response({'error': str(e)}, 500)


# ============================================================================
# ADMIN - STAC MATERIALIZATION CRUD (26 FEB 2026)
# ============================================================================
# These endpoints provide admin-level STAC management:
# - Create/update/delete collections
# - Add/remove items
# - Rebuild catalog from internal DB
# ============================================================================

@bp.route(route="stac/admin/collections", methods=["POST"])
def stac_admin_create_collection(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create an empty STAC collection.

    POST /api/stac/admin/collections

    Body:
        {
            "collection_id": "my-dataset-my-resource",
            "description": "Optional description",
            "bbox": [-180, -90, 180, 90],
            "license": "proprietary"
        }

    Returns:
        {"success": true, "collection_id": "my-dataset-my-resource"}
    """
    try:
        body = req.get_json()
        collection_id = body.get('collection_id')
        if not collection_id:
            return _error_response("collection_id is required", 400)

        config = get_stac_config()
        service = STACAPIService(config)
        result = service.admin_create_collection(
            collection_id=collection_id,
            description=body.get('description'),
            bbox=body.get('bbox', [-180, -90, 180, 90]),
            license_val=body.get('license', 'proprietary'),
        )
        status = 201 if result.get('success') else 400
        return _json_response(result, status)
    except Exception as e:
        logger.error(f"Error in POST /stac/admin/collections: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/admin/collections/{collection_id}", methods=["PUT"])
def stac_admin_update_collection(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update collection metadata.

    PUT /api/stac/admin/collections/{collection_id}

    Body:
        {
            "description": "Updated description",
            "bbox": [-70, -56, -69, -55]
        }

    Returns:
        {"success": true, "collection_id": "..."}
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return _error_response("collection_id is required", 400)

        body = req.get_json()
        config = get_stac_config()
        service = STACAPIService(config)
        result = service.admin_update_collection(collection_id, body)
        status = 200 if result.get('success') else 404
        return _json_response(result, status)
    except Exception as e:
        logger.error(f"Error in PUT /stac/admin/collections: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/admin/collections/{collection_id}", methods=["DELETE"])
def stac_admin_delete_collection(req: func.HttpRequest) -> func.HttpResponse:
    """
    Delete a collection and all its items from pgSTAC.

    DELETE /api/stac/admin/collections/{collection_id}?confirm=yes

    Returns:
        {"success": true, "collection_id": "...", "items_deleted": N}
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return _error_response("collection_id is required", 400)

        confirm = req.params.get('confirm', '')
        if confirm != 'yes':
            return _error_response(
                "Add ?confirm=yes to confirm deletion", 400
            )

        config = get_stac_config()
        service = STACAPIService(config)
        result = service.admin_delete_collection(collection_id)
        status = 200 if result.get('success') else 404
        return _json_response(result, status)
    except Exception as e:
        logger.error(f"Error in DELETE /stac/admin/collections: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/admin/collections/{collection_id}/items/{item_id}", methods=["DELETE"])
def stac_admin_delete_item(req: func.HttpRequest) -> func.HttpResponse:
    """
    Remove an item from a collection (with extent recalculation).

    DELETE /api/stac/admin/collections/{collection_id}/items/{item_id}?confirm=yes

    Returns:
        {"success": true, "deleted": true, "collection_action": "extent_recalculated"|"deleted_empty"}
    """
    try:
        collection_id = req.route_params.get('collection_id')
        item_id = req.route_params.get('item_id')
        if not collection_id or not item_id:
            return _error_response("collection_id and item_id are required", 400)

        confirm = req.params.get('confirm', '')
        if confirm != 'yes':
            return _error_response(
                "Add ?confirm=yes to confirm deletion", 400
            )

        config = get_stac_config()
        service = STACAPIService(config)
        result = service.admin_delete_item(collection_id, item_id)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in DELETE /stac/admin/items: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/admin/rebuild", methods=["POST"])
def stac_admin_rebuild_all(req: func.HttpRequest) -> func.HttpResponse:
    """
    Rebuild entire STAC catalog from internal DB.

    POST /api/stac/admin/rebuild?confirm=yes

    Returns:
        {"success": true, "collections_rebuilt": N, "items_rebuilt": N}
    """
    try:
        confirm = req.params.get('confirm', '')
        if confirm != 'yes':
            return _error_response(
                "Add ?confirm=yes to confirm full catalog rebuild", 400
            )

        config = get_stac_config()
        service = STACAPIService(config)
        result = service.admin_rebuild_all()
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in POST /stac/admin/rebuild: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")


@bp.route(route="stac/admin/rebuild/{collection_id}", methods=["POST"])
def stac_admin_rebuild_collection(req: func.HttpRequest) -> func.HttpResponse:
    """
    Rebuild a single STAC collection from internal DB.

    POST /api/stac/admin/rebuild/{collection_id}?confirm=yes

    Returns:
        {"success": true, "collection_id": "...", "items_created": N}
    """
    try:
        collection_id = req.route_params.get('collection_id')
        if not collection_id:
            return _error_response("collection_id is required", 400)

        confirm = req.params.get('confirm', '')
        if confirm != 'yes':
            return _error_response(
                "Add ?confirm=yes to confirm collection rebuild", 400
            )

        config = get_stac_config()
        service = STACAPIService(config)
        result = service.admin_rebuild_collection(collection_id)
        return _json_response(result)
    except Exception as e:
        logger.error(f"Error in POST /stac/admin/rebuild/{collection_id}: {e}", exc_info=True)
        return _error_response(str(e), 500, "InternalServerError")
