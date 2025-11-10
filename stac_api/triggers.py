"""
STAC API HTTP Triggers

Azure Functions HTTP handlers for STAC API v1.0.0 endpoints.

Endpoints:
- GET /api/stac - Landing page (catalog root)
- GET /api/stac/conformance - Conformance classes
- GET /api/stac/collections - Collections list

Integration (in function_app.py):
    from stac_api import get_stac_triggers

    for trigger in get_stac_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Author: Robert and Geospatial Claude Legion
Date: 10 NOV 2025
"""

import azure.functions as func
import json
import logging
from typing import Dict, Any, List

from .config import get_stac_config
from .service import STACAPIService

logger = logging.getLogger(__name__)


# ============================================================================
# TRIGGER REGISTRY FUNCTION
# ============================================================================

def get_stac_triggers() -> List[Dict[str, Any]]:
    """
    Get list of STAC API trigger configurations for function_app.py.

    This is the ONLY integration point with the main application.
    Returns trigger configurations that can be registered with Azure Functions.

    Returns:
        List of dicts with keys:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable trigger handler

    Usage:
        from stac_api import get_stac_triggers

        for trigger in get_stac_triggers():
            app.route(
                route=trigger['route'],
                methods=trigger['methods'],
                auth_level=func.AuthLevel.ANONYMOUS
            )(trigger['handler'])
    """
    return [
        {
            'route': 'stac',
            'methods': ['GET'],
            'handler': STACLandingPageTrigger().handle
        },
        {
            'route': 'stac/conformance',
            'methods': ['GET'],
            'handler': STACConformanceTrigger().handle
        },
        {
            'route': 'stac/collections',
            'methods': ['GET'],
            'handler': STACCollectionsTrigger().handle
        }
    ]


# ============================================================================
# BASE TRIGGER CLASS
# ============================================================================

class BaseSTACTrigger:
    """
    Base class for STAC API triggers.

    Provides common functionality:
    - Base URL extraction from request
    - JSON response formatting
    - Error handling
    - Logging
    """

    def __init__(self):
        """Initialize trigger with service."""
        self.config = get_stac_config()
        self.service = STACAPIService(self.config)

    def _get_base_url(self, req: func.HttpRequest) -> str:
        """
        Extract base URL from request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            Base URL (e.g., https://example.com)
        """
        # Try configured base URL first
        if self.config.stac_base_url:
            return self.config.stac_base_url.rstrip("/")

        # Auto-detect from request URL
        full_url = req.url
        if "/api/stac" in full_url:
            return full_url.split("/api/stac")[0]

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
            data: Data to serialize (dict or Pydantic model)
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
# ENDPOINT TRIGGERS
# ============================================================================

class STACLandingPageTrigger(BaseSTACTrigger):
    """
    Landing page trigger.

    Endpoint: GET /api/stac
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle landing page request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC Catalog JSON response
        """
        try:
            logger.info("STAC API Landing Page requested")

            base_url = self._get_base_url(req)
            catalog = self.service.get_catalog(base_url)

            logger.info("STAC API landing page generated successfully")
            return self._json_response(catalog)

        except Exception as e:
            logger.error(f"Error generating STAC API landing page: {e}", exc_info=True)
            return self._error_response(
                message=str(e),
                status_code=500,
                error_type="InternalServerError"
            )


class STACConformanceTrigger(BaseSTACTrigger):
    """
    Conformance classes trigger.

    Endpoint: GET /api/stac/conformance
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle conformance request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC conformance JSON response
        """
        try:
            logger.info("STAC API Conformance requested")

            conformance = self.service.get_conformance()

            logger.info("STAC API conformance generated successfully")
            return self._json_response(conformance)

        except Exception as e:
            logger.error(f"Error generating STAC API conformance: {e}", exc_info=True)
            return self._error_response(
                message=str(e),
                status_code=500,
                error_type="InternalServerError"
            )


class STACCollectionsTrigger(BaseSTACTrigger):
    """
    Collections list trigger.

    Endpoint: GET /api/stac/collections
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle collections list request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC collections JSON response
        """
        try:
            logger.info("STAC API Collections list requested")

            collections = self.service.get_collections()

            # Check for errors from infrastructure layer
            if 'error' in collections:
                logger.error(f"Error retrieving collections: {collections['error']}")
                return self._error_response(
                    message=collections['error'],
                    status_code=500,
                    error_type="InternalServerError"
                )

            collections_count = len(collections.get('collections', []))
            logger.info(f"Returning {collections_count} STAC collections")

            return self._json_response(collections)

        except Exception as e:
            logger.error(f"Error processing collections request: {e}", exc_info=True)
            return self._error_response(
                message=str(e),
                status_code=500,
                error_type="InternalServerError"
            )
