"""
Raster Collection Viewer HTTP Triggers.

Azure Functions HTTP endpoint for STAC raster collection preview viewer.

Feature: F2.9 (30 DEC 2025)

Exports:
    get_raster_collection_viewer_triggers: Returns list of trigger configurations for route registration
"""

import logging
import azure.functions as func
from typing import List, Dict, Any

from raster_collection_viewer.service import RasterCollectionViewerService

logger = logging.getLogger(__name__)


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
