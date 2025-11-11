"""
STAC API HTTP Triggers

Azure Functions HTTP handlers for STAC API v1.0.0 endpoints.

Endpoints:
- GET /api/stac - Landing page (catalog root)
- GET /api/stac/conformance - Conformance classes
- GET /api/stac/collections - Collections list
- GET /api/stac/collections/{collection_id} - Collection detail
- GET /api/stac/collections/{collection_id}/items - Items list (with pagination)
- GET /api/stac/collections/{collection_id}/items/{item_id} - Item detail

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
Updated: 11 NOV 2025 - Added all STAC v1.0.0 endpoints
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
        },
        {
            'route': 'stac/collections/{collection_id}',
            'methods': ['GET'],
            'handler': STACCollectionDetailTrigger().handle
        },
        {
            'route': 'stac/collections/{collection_id}/items',
            'methods': ['GET'],
            'handler': STACItemsTrigger().handle
        },
        {
            'route': 'stac/collections/{collection_id}/items/{item_id}',
            'methods': ['GET'],
            'handler': STACItemDetailTrigger().handle
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

            base_url = self._get_base_url(req)
            collections = self.service.get_collections(base_url)

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


class STACCollectionDetailTrigger(BaseSTACTrigger):
    """
    Collection detail trigger.

    Endpoint: GET /api/stac/collections/{collection_id}
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle collection detail request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC collection JSON response
        """
        try:
            # Extract collection_id from route params
            collection_id = req.route_params.get('collection_id')
            if not collection_id:
                return self._error_response(
                    message="collection_id is required",
                    status_code=400,
                    error_type="BadRequest"
                )

            logger.info(f"STAC API Collection detail requested: {collection_id}")

            base_url = self._get_base_url(req)
            collection = self.service.get_collection(collection_id, base_url)

            # Check for errors from infrastructure layer
            if 'error' in collection:
                logger.error(f"Error retrieving collection: {collection['error']}")
                return self._error_response(
                    message=collection['error'],
                    status_code=404 if 'not found' in collection['error'].lower() else 500,
                    error_type="NotFound" if 'not found' in collection['error'].lower() else "InternalServerError"
                )

            logger.info(f"Returning STAC collection: {collection_id}")
            return self._json_response(collection)

        except Exception as e:
            logger.error(f"Error processing collection detail request: {e}", exc_info=True)
            return self._error_response(
                message=str(e),
                status_code=500,
                error_type="InternalServerError"
            )


class STACItemsTrigger(BaseSTACTrigger):
    """
    Collection items list trigger.

    Endpoint: GET /api/stac/collections/{collection_id}/items
    Query params: limit, offset, bbox
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle collection items request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC items FeatureCollection JSON response
        """
        try:
            # Extract collection_id from route params
            collection_id = req.route_params.get('collection_id')
            if not collection_id:
                return self._error_response(
                    message="collection_id is required",
                    status_code=400,
                    error_type="BadRequest"
                )

            # Parse query parameters
            limit = int(req.params.get('limit', 10))
            offset = int(req.params.get('offset', 0))
            bbox = req.params.get('bbox')  # Optional: minx,miny,maxx,maxy

            # Validate pagination params
            if limit < 1 or limit > 1000:
                return self._error_response(
                    message="limit must be between 1 and 1000",
                    status_code=400,
                    error_type="BadRequest"
                )

            if offset < 0:
                return self._error_response(
                    message="offset must be >= 0",
                    status_code=400,
                    error_type="BadRequest"
                )

            logger.info(f"STAC API Items requested: collection={collection_id}, limit={limit}, offset={offset}, bbox={bbox}")

            base_url = self._get_base_url(req)
            items = self.service.get_items(
                collection_id=collection_id,
                base_url=base_url,
                limit=limit,
                offset=offset,
                bbox=bbox
            )

            # Check for errors from infrastructure layer
            if 'error' in items:
                logger.error(f"Error retrieving items: {items['error']}")
                return self._error_response(
                    message=items['error'],
                    status_code=404 if 'not found' in items['error'].lower() else 500,
                    error_type="NotFound" if 'not found' in items['error'].lower() else "InternalServerError"
                )

            feature_count = len(items.get('features', []))
            logger.info(f"Returning {feature_count} items for collection {collection_id}")

            return self._json_response(items, content_type="application/geo+json")

        except ValueError as e:
            logger.warning(f"Invalid query parameter: {e}")
            return self._error_response(
                message=str(e),
                status_code=400,
                error_type="BadRequest"
            )
        except Exception as e:
            logger.error(f"Error processing items request: {e}", exc_info=True)
            return self._error_response(
                message=str(e),
                status_code=500,
                error_type="InternalServerError"
            )


class STACItemDetailTrigger(BaseSTACTrigger):
    """
    Item detail trigger.

    Endpoint: GET /api/stac/collections/{collection_id}/items/{item_id}
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle item detail request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            STAC item JSON response
        """
        try:
            # Extract route params
            collection_id = req.route_params.get('collection_id')
            item_id = req.route_params.get('item_id')

            if not collection_id:
                return self._error_response(
                    message="collection_id is required",
                    status_code=400,
                    error_type="BadRequest"
                )

            if not item_id:
                return self._error_response(
                    message="item_id is required",
                    status_code=400,
                    error_type="BadRequest"
                )

            logger.info(f"STAC API Item detail requested: collection={collection_id}, item={item_id}")

            base_url = self._get_base_url(req)
            item = self.service.get_item(collection_id, item_id, base_url)

            # Check for errors from infrastructure layer
            if 'error' in item:
                logger.error(f"Error retrieving item: {item['error']}")
                return self._error_response(
                    message=item['error'],
                    status_code=404 if 'not found' in item['error'].lower() else 500,
                    error_type="NotFound" if 'not found' in item['error'].lower() else "InternalServerError"
                )

            logger.info(f"Returning STAC item: {item_id}")
            return self._json_response(item, content_type="application/geo+json")

        except Exception as e:
            logger.error(f"Error processing item detail request: {e}", exc_info=True)
            return self._error_response(
                message=str(e),
                status_code=500,
                error_type="InternalServerError"
            )
