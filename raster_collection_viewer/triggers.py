"""
Raster Collection Viewer HTTP Triggers.

Azure Functions HTTP endpoint for STAC raster collection preview viewer.

Feature: F2.9 (30 DEC 2025)

Exports:
    get_raster_collection_viewer_triggers: Returns list of trigger configurations for route registration
"""

import json
import logging
from datetime import datetime, timezone
import azure.functions as func
from typing import List, Dict, Any

from raster_collection_viewer.service import RasterCollectionViewerService
from triggers.http_base import parse_request_json

logger = logging.getLogger(__name__)

# Valid QA status values
QA_STATUS_VALUES = ['pending', 'approved', 'rejected']


def get_raster_collection_viewer_triggers() -> List[Dict[str, Any]]:
    """
    Get list of raster collection viewer trigger configurations.

    Returns:
        List of dicts with:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable handler function
    """
    return [
        {
            'route': 'raster/viewer',
            'methods': ['GET'],
            'handler': raster_viewer_handler
        },
        {
            'route': 'raster/qa',
            'methods': ['POST'],
            'handler': raster_qa_handler
        }
    ]


def raster_viewer_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle raster collection viewer requests.

    Query Parameters:
        collection (required): STAC collection ID to view

    Returns:
        HTML page with Leaflet map and TiTiler integration for viewing
        raster items with band selection, rescale, and colormap controls.

    Example:
        GET /api/raster/viewer?collection=aerial-2024
    """
    try:
        # Parse query parameters
        collection_id = req.params.get('collection')

        # Validate required parameters
        if not collection_id:
            return func.HttpResponse(
                "Missing required parameter: collection",
                status_code=400
            )

        logger.info(f"Raster Viewer request: collection={collection_id}")

        # Get host URL from request for absolute API paths
        host_url = None
        if hasattr(req, 'url'):
            url_parts = req.url.split('/api/')
            if len(url_parts) > 0:
                host_url = url_parts[0]
                logger.debug(f"Detected host URL: {host_url}")

        # Initialize service
        service = RasterCollectionViewerService()

        # Generate HTML viewer
        html = service.generate_viewer_html(
            collection_id=collection_id,
            host_url=host_url
        )

        logger.info(f"Generated raster viewer for {collection_id} ({len(html)} bytes)")

        # Return HTML response
        return func.HttpResponse(
            html,
            mimetype="text/html",
            status_code=200
        )

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        return func.HttpResponse(
            f"Validation error: {str(e)}",
            status_code=400
        )

    except Exception as e:
        logger.error(f"Error generating raster viewer: {e}", exc_info=True)
        return func.HttpResponse(
            f"Error generating viewer: {str(e)}",
            status_code=500
        )


def raster_qa_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle QA status updates for STAC raster items.

    POST /api/raster/qa

    Request Body:
        {
            "item_id": "item-123",
            "collection_id": "collection-abc",
            "status": "approved" | "rejected" | "pending"
        }

    Returns:
        JSON response with update result.

    Example:
        POST /api/raster/qa
        {"item_id": "dem-2024-01", "collection_id": "elevation", "status": "approved"}
    """
    try:
        # Parse request body
        try:
            req_body = parse_request_json(req)
        except ValueError:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Invalid JSON body"}),
                status_code=400,
                mimetype="application/json"
            )

        # Validate required fields
        item_id = req_body.get('item_id')
        collection_id = req_body.get('collection_id')
        status = req_body.get('status')

        if not item_id:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Missing required field: item_id"}),
                status_code=400,
                mimetype="application/json"
            )

        if not collection_id:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Missing required field: collection_id"}),
                status_code=400,
                mimetype="application/json"
            )

        if not status:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Missing required field: status"}),
                status_code=400,
                mimetype="application/json"
            )

        if status not in QA_STATUS_VALUES:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Invalid status. Must be one of: {QA_STATUS_VALUES}"
                }),
                status_code=400,
                mimetype="application/json"
            )

        logger.info(f"QA status update: {item_id} → {status} (collection: {collection_id})")

        # Update item properties
        from infrastructure.pgstac_repository import PgStacRepository
        repo = PgStacRepository()

        # Set QA properties
        properties_update = {
            "geoetl:qa_status": status,
            "geoetl:qa_updated": datetime.now(timezone.utc).isoformat()
        }

        success = repo.update_item_properties(item_id, collection_id, properties_update)

        if success:
            logger.info(f"✅ QA status updated: {item_id} → {status}")
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "item_id": item_id,
                    "collection_id": collection_id,
                    "status": status,
                    "message": f"QA status updated to '{status}'"
                }),
                status_code=200,
                mimetype="application/json"
            )
        else:
            logger.warning(f"⚠️ Item not found: {item_id}")
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Item not found: {item_id} in collection {collection_id}"
                }),
                status_code=404,
                mimetype="application/json"
            )

    except Exception as e:
        logger.error(f"Error updating QA status: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"success": False, "error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
