# ============================================================================
# CLAUDE CONTEXT - OGC STYLES HTTP TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP handlers - Azure Functions triggers for OGC Styles
# PURPOSE: Handle HTTP requests for style list and style retrieval
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: get_styles_triggers
# DEPENDENCIES: azure.functions, ogc_styles.service
# ============================================================================
"""
OGC Styles HTTP Triggers.

Azure Functions HTTP endpoint handlers for OGC API - Styles endpoints.

Endpoints:
    GET /features/collections/{id}/styles        - List styles
    GET /features/collections/{id}/styles/{sid}  - Get style (multi-format)

Created: 18 DEC 2025
"""

import azure.functions as func
import json
import logging
from typing import Any, Dict, List

from ogc_features.config import get_ogc_config
from .service import OGCStylesService

logger = logging.getLogger(__name__)


# ============================================================================
# TRIGGER REGISTRY FUNCTION
# ============================================================================

def get_styles_triggers() -> List[Dict[str, Any]]:
    """
    Get list of OGC Styles API trigger configurations for function_app.py.

    Returns:
        List of dicts with keys:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable trigger handler

    Usage:
        from ogc_styles import get_styles_triggers

        for trigger in get_styles_triggers():
            app.route(
                route=trigger['route'],
                methods=trigger['methods'],
                auth_level=func.AuthLevel.ANONYMOUS
            )(trigger['handler'])
    """
    return [
        {
            'route': 'features/collections/{collection_id}/styles',
            'methods': ['GET'],
            'handler': OGCStylesListTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}/styles/{style_id}',
            'methods': ['GET'],
            'handler': OGCStyleTrigger().handle
        }
    ]


# ============================================================================
# BASE TRIGGER CLASS
# ============================================================================

class BaseStylesTrigger:
    """
    Base class for OGC Styles API triggers.

    Provides common functionality:
    - Base URL extraction from request
    - JSON response formatting
    - Error handling
    - Logging
    """

    def __init__(self):
        """Initialize trigger with service."""
        self.config = get_ogc_config()
        self.service = OGCStylesService()

    def _get_base_url(self, req: func.HttpRequest) -> str:
        """
        Extract base URL from request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            Base URL (e.g., https://example.com)
        """
        # Try configured base URL first
        if self.config.ogc_base_url:
            return self.config.ogc_base_url.rstrip("/")

        # Auto-detect from request URL
        full_url = req.url
        if "/api/features" in full_url:
            return full_url.split("/api/features")[0]

        # Fallback
        return "http://localhost:7071"

    def _json_response(
        self,
        data: Any,
        status_code: int = 200,
        content_type: str = "application/json"
    ) -> func.HttpResponse:
        """
        Create JSON HTTP response.

        Args:
            data: Data to serialize (dict, Pydantic model, etc.)
            status_code: HTTP status code
            content_type: Response content type

        Returns:
            Azure Functions HttpResponse
        """
        # Handle Pydantic models
        if hasattr(data, 'model_dump'):
            data = data.model_dump(mode='json', exclude_none=True)

        return func.HttpResponse(
            body=json.dumps(data, indent=2),
            status_code=status_code,
            mimetype=content_type
        )

    def _error_response(
        self,
        message: str,
        status_code: int = 400,
        error_type: str = "BadRequest"
    ) -> func.HttpResponse:
        """
        Create error response.

        Args:
            message: Error message
            status_code: HTTP status code
            error_type: Error type string

        Returns:
            Azure Functions HttpResponse with error JSON
        """
        error_body = {
            "code": error_type,
            "description": message
        }
        return func.HttpResponse(
            body=json.dumps(error_body, indent=2),
            status_code=status_code,
            mimetype="application/json"
        )


# ============================================================================
# STYLES LIST TRIGGER
# ============================================================================

class OGCStylesListTrigger(BaseStylesTrigger):
    """
    Styles list trigger.

    Endpoint: GET /api/features/collections/{collection_id}/styles
    OGC Conformance: /req/core/styles-list
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle styles list request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with styles list JSON
        """
        try:
            collection_id = req.route_params.get('collection_id')
            if not collection_id:
                return self._error_response(
                    message="Collection ID is required",
                    status_code=400
                )

            base_url = self._get_base_url(req)
            styles_list = self.service.list_styles(collection_id, base_url)

            logger.info(f"Styles list requested for collection '{collection_id}'")

            return self._json_response(styles_list)

        except ValueError as e:
            logger.warning(f"Collection not found: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error listing styles: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )


# ============================================================================
# SINGLE STYLE TRIGGER
# ============================================================================

class OGCStyleTrigger(BaseStylesTrigger):
    """
    Single style trigger.

    Endpoint: GET /api/features/collections/{collection_id}/styles/{style_id}
    OGC Conformance: /req/core/style

    Supports content negotiation via:
    - Query parameter: ?f=leaflet, ?f=mapbox, ?f=cartosym
    - Accept header: application/vnd.leaflet.style+json, etc.
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle single style request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with style document in requested format
        """
        try:
            collection_id = req.route_params.get('collection_id')
            style_id = req.route_params.get('style_id')

            if not collection_id or not style_id:
                return self._error_response(
                    message="Collection ID and Style ID are required",
                    status_code=400
                )

            # Determine output format (query param takes precedence)
            format_param = req.params.get("f", "").lower() or None
            accept_header = req.headers.get("Accept", "")

            output_format = self.service.negotiate_format(accept_header, format_param)

            # Get style in requested format
            style_doc, content_type = self.service.get_style(
                collection_id=collection_id,
                style_id=style_id,
                output_format=output_format
            )

            logger.info(
                f"Style '{style_id}' requested for collection '{collection_id}' "
                f"(format: {output_format})"
            )

            return self._json_response(style_doc, content_type=content_type)

        except ValueError as e:
            logger.warning(f"Style not found or invalid format: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error getting style: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )
