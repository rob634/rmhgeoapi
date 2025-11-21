# ============================================================================
# CLAUDE CONTEXT - VECTOR VIEWER TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone HTTP Trigger - Vector Collection Viewer endpoint
# PURPOSE: Azure Functions HTTP trigger for vector collection preview viewer
# LAST_REVIEWED: 13 NOV 2025
# EXPORTS: get_vector_viewer_triggers (returns list of trigger configurations)
# INTERFACES: Azure Functions HttpRequest/HttpResponse
# PYDANTIC_MODELS: None (simple query parameter parsing)
# DEPENDENCIES: azure.functions, logging
# SOURCE: HTTP requests from data curators (browser)
# SCOPE: HTTP endpoint handler for vector viewer
# VALIDATION: Query parameter validation
# PATTERNS: Trigger Pattern, Factory Pattern (get_vector_viewer_triggers)
# ENTRY_POINTS: Function App route registration via get_vector_viewer_triggers()
# INDEX: get_vector_viewer_triggers:45, vector_viewer_handler:80
# ============================================================================

"""
Vector Viewer HTTP Trigger - Azure Functions Handler

Provides HTTP endpoint for vector collection preview viewer:
- GET /api/vector/viewer?collection={id}

Returns self-contained HTML page with Leaflet map for visual QA.

Integration:
    In function_app.py:

    from vector_viewer import get_vector_viewer_triggers

    for trigger in get_vector_viewer_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

"""

import logging
import azure.functions as func
from typing import List, Dict, Any, Callable
from .service import VectorViewerService

logger = logging.getLogger(__name__)


def get_vector_viewer_triggers() -> List[Dict[str, Any]]:
    """
    Get list of vector viewer trigger configurations.

    Returns:
        List of dicts with:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable handler function
    """
    return [
        {
            'route': 'vector/viewer',
            'methods': ['GET'],
            'handler': vector_viewer_handler
        }
    ]


def vector_viewer_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle vector collection viewer requests.

    Query Parameters:
        collection (required): Collection ID (PostGIS table name)

    Returns:
        HTML page with Leaflet map showing vector features and metadata

    Example:
        GET /api/vector/viewer?collection=qa_test_chunk_5000
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

        logger.info(f"Vector Viewer request: collection={collection_id}")

        # Get host URL from request for absolute API paths
        # Azure Functions provides this in req.url
        host_url = None
        if hasattr(req, 'url'):
            # Extract protocol and host from full URL
            # Example: https://rmhazuregeoapi-.../api/vector/viewer?...
            url_parts = req.url.split('/api/')
            if len(url_parts) > 0:
                host_url = url_parts[0]
                logger.debug(f"Detected host URL: {host_url}")

        # Initialize service
        service = VectorViewerService()

        # Generate HTML viewer
        html = service.generate_viewer_html(
            collection_id=collection_id,
            host_url=host_url
        )

        logger.info(f"Generated viewer for {collection_id} ({len(html)} bytes)")

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
        logger.error(f"Error generating vector viewer: {e}", exc_info=True)
        return func.HttpResponse(
            f"Error generating viewer: {str(e)}",
            status_code=500
        )
