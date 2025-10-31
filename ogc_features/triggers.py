# ============================================================================
# CLAUDE CONTEXT - OGC FEATURES TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Standalone HTTP Triggers - OGC Features API endpoints
# PURPOSE: Azure Functions HTTP triggers for OGC API - Features endpoints
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: get_ogc_triggers (returns list of trigger configurations)
# INTERFACES: Azure Functions HttpRequest/HttpResponse
# PYDANTIC_MODELS: OGCQueryParameters (for validation)
# DEPENDENCIES: azure.functions, typing, json, logging, urllib.parse
# SOURCE: HTTP requests from clients (Leaflet, QGIS, curl)
# SCOPE: HTTP endpoint handlers for OGC Features API
# VALIDATION: Query parameter parsing and Pydantic validation
# PATTERNS: Trigger Pattern, Factory Pattern (get_ogc_triggers)
# ENTRY_POINTS: Function App route registration via get_ogc_triggers()
# INDEX: get_ogc_triggers:73, OGCLandingPageTrigger:231, OGCItemsTrigger:382
# ============================================================================

"""
OGC Features API HTTP Triggers - Azure Functions Handlers

Provides HTTP endpoint handlers for all OGC API - Features Core endpoints:
- GET /api/features - Landing page
- GET /api/features/conformance - Conformance classes
- GET /api/features/collections - List collections
- GET /api/features/collections/{collection_id} - Collection metadata
- GET /api/features/collections/{collection_id}/items - Query features
- GET /api/features/collections/{collection_id}/items/{feature_id} - Single feature

Each trigger:
1. Parses HTTP request parameters
2. Validates inputs (Pydantic)
3. Calls service layer
4. Returns OGC-compliant JSON/GeoJSON responses
5. Handles errors with proper HTTP status codes

Integration:
    In function_app.py:

    from ogc_features import get_ogc_triggers

    for trigger in get_ogc_triggers():
        app.route(
            route=trigger['route'],
            methods=trigger['methods'],
            auth_level=func.AuthLevel.ANONYMOUS
        )(trigger['handler'])

Author: Robert and Geospatial Claude Legion
Date: 29 OCT 2025
"""

import azure.functions as func
import json
import logging
from typing import Dict, Any, List, Optional, Callable
from urllib.parse import urlparse, parse_qs

from .config import get_ogc_config
from .service import OGCFeaturesService
from .models import OGCQueryParameters
from pydantic import ValidationError

# Setup logging
logger = logging.getLogger(__name__)


# ============================================================================
# TRIGGER REGISTRY FUNCTION
# ============================================================================

def get_ogc_triggers() -> List[Dict[str, Any]]:
    """
    Get list of OGC Features API trigger configurations for function_app.py.

    This is the ONLY integration point with the main application.
    Returns trigger configurations that can be registered with Azure Functions.

    Returns:
        List of dicts with keys:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable trigger handler

    Usage:
        from ogc_features import get_ogc_triggers

        for trigger in get_ogc_triggers():
            app.route(
                route=trigger['route'],
                methods=trigger['methods'],
                auth_level=func.AuthLevel.ANONYMOUS
            )(trigger['handler'])
    """
    return [
        {
            'route': 'features',
            'methods': ['GET'],
            'handler': OGCLandingPageTrigger().handle
        },
        {
            'route': 'features/conformance',
            'methods': ['GET'],
            'handler': OGCConformanceTrigger().handle
        },
        {
            'route': 'features/collections',
            'methods': ['GET'],
            'handler': OGCCollectionsTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}',
            'methods': ['GET'],
            'handler': OGCCollectionTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}/items',
            'methods': ['GET'],
            'handler': OGCItemsTrigger().handle
        },
        {
            'route': 'features/collections/{collection_id}/items/{feature_id}',
            'methods': ['GET'],
            'handler': OGCItemTrigger().handle
        }
    ]


# ============================================================================
# BASE TRIGGER CLASS
# ============================================================================

class BaseOGCTrigger:
    """
    Base class for OGC Features API triggers.

    Provides common functionality:
    - Base URL extraction from request
    - JSON response formatting
    - Error handling
    - Logging
    """

    def __init__(self):
        """Initialize trigger with service."""
        self.config = get_ogc_config()
        self.service = OGCFeaturesService(self.config)

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
# ENDPOINT TRIGGERS
# ============================================================================

class OGCLandingPageTrigger(BaseOGCTrigger):
    """
    Landing page trigger.

    Endpoint: GET /api/features
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle landing page request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with landing page JSON
        """
        try:
            base_url = self._get_base_url(req)
            landing_page = self.service.get_landing_page(base_url)

            logger.info("Landing page requested")

            return self._json_response(landing_page)

        except Exception as e:
            logger.error(f"Error generating landing page: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )


class OGCConformanceTrigger(BaseOGCTrigger):
    """
    Conformance classes trigger.

    Endpoint: GET /api/features/conformance
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle conformance request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with conformance JSON
        """
        try:
            conformance = self.service.get_conformance()

            logger.info("Conformance classes requested")

            return self._json_response(conformance)

        except Exception as e:
            logger.error(f"Error generating conformance: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )


class OGCCollectionsTrigger(BaseOGCTrigger):
    """
    Collections list trigger.

    Endpoint: GET /api/features/collections
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle collections list request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with collections list JSON
        """
        try:
            base_url = self._get_base_url(req)
            collections = self.service.list_collections(base_url)

            logger.info(f"Collections list requested ({len(collections.collections)} collections)")

            return self._json_response(collections)

        except Exception as e:
            logger.error(f"Error listing collections: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )


class OGCCollectionTrigger(BaseOGCTrigger):
    """
    Single collection metadata trigger.

    Endpoint: GET /api/features/collections/{collection_id}
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle collection metadata request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with collection metadata JSON
        """
        try:
            # Extract collection_id from route parameters
            collection_id = req.route_params.get('collection_id')
            if not collection_id:
                return self._error_response(
                    message="Collection ID is required",
                    status_code=400
                )

            base_url = self._get_base_url(req)
            collection = self.service.get_collection(collection_id, base_url)

            logger.info(f"Collection metadata requested for '{collection_id}'")

            return self._json_response(collection)

        except ValueError as e:
            # Collection not found
            logger.warning(f"Collection not found: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error getting collection metadata: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )


class OGCItemsTrigger(BaseOGCTrigger):
    """
    Features query trigger (main endpoint).

    Endpoint: GET /api/features/collections/{collection_id}/items

    Query Parameters:
    - limit: Max features to return (1-10000, default 100)
    - offset: Pagination offset (default 0)
    - bbox: Bounding box (minx,miny,maxx,maxy)
    - datetime: Temporal filter (ISO 8601)
    - datetime_property: Datetime column name (optional)
    - sortby: OGC sortby syntax (+col1,-col2)
    - precision: Coordinate precision (0-15, default 6)
    - simplify: Simplification tolerance in meters
    - <property>=<value>: Attribute filters (simple equality)
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle feature query request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with GeoJSON FeatureCollection
        """
        try:
            # Extract collection_id from route
            collection_id = req.route_params.get('collection_id')
            if not collection_id:
                return self._error_response(
                    message="Collection ID is required",
                    status_code=400
                )

            # Parse query parameters
            query_params = self._parse_query_parameters(req)

            # Separate OGC standard params from property filters
            ogc_param_names = {
                'limit', 'offset', 'bbox', 'datetime', 'datetime_property',
                'sortby', 'precision', 'simplify', 'crs'
            }

            property_filters = {
                k: v for k, v in query_params.items()
                if k not in ogc_param_names
            }

            # Build OGCQueryParameters model
            try:
                params = OGCQueryParameters(**{
                    k: v for k, v in query_params.items()
                    if k in ogc_param_names
                })
            except ValidationError as e:
                return self._error_response(
                    message=f"Invalid query parameters: {str(e)}",
                    status_code=400
                )

            # Query features via service
            base_url = self._get_base_url(req)
            feature_collection = self.service.query_features(
                collection_id=collection_id,
                params=params,
                base_url=base_url,
                property_filters=property_filters if property_filters else None
            )

            logger.info(
                f"Feature query: collection='{collection_id}', "
                f"returned={feature_collection.numberReturned}, "
                f"total={feature_collection.numberMatched}"
            )

            return self._json_response(
                feature_collection,
                content_type="application/geo+json"
            )

        except ValueError as e:
            # Collection not found or invalid parameters
            logger.warning(f"Query error: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error querying features: {e}", exc_info=True)
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )

    def _parse_query_parameters(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Parse and normalize query parameters from request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            Dict of parsed parameters with proper types
        """
        params = {}

        # Pagination
        if 'limit' in req.params:
            try:
                params['limit'] = int(req.params['limit'])
            except ValueError:
                pass  # Will be caught by Pydantic validation

        if 'offset' in req.params:
            try:
                params['offset'] = int(req.params['offset'])
            except ValueError:
                pass

        # Spatial filter (bbox)
        if 'bbox' in req.params:
            try:
                bbox_str = req.params['bbox']
                bbox_parts = bbox_str.split(',')
                params['bbox'] = [float(x) for x in bbox_parts]
            except (ValueError, AttributeError):
                pass  # Will be caught by Pydantic validation

        # Temporal filter
        if 'datetime' in req.params:
            params['datetime'] = req.params['datetime']

        if 'datetime_property' in req.params:
            params['datetime_property'] = req.params['datetime_property']

        # Sorting
        if 'sortby' in req.params:
            params['sortby'] = req.params['sortby']

        # Geometry optimization
        if 'precision' in req.params:
            try:
                params['precision'] = int(req.params['precision'])
            except ValueError:
                pass

        if 'simplify' in req.params:
            try:
                params['simplify'] = float(req.params['simplify'])
            except ValueError:
                pass

        # CRS
        if 'crs' in req.params:
            params['crs'] = req.params['crs']

        # Attribute filters (all other params)
        for key in req.params:
            if key not in params:
                # Try to parse as number, otherwise keep as string
                value = req.params[key]
                try:
                    # Try int first
                    params[key] = int(value)
                except ValueError:
                    try:
                        # Try float
                        params[key] = float(value)
                    except ValueError:
                        # Keep as string
                        params[key] = value

        return params


class OGCItemTrigger(BaseOGCTrigger):
    """
    Single feature trigger.

    Endpoint: GET /api/features/collections/{collection_id}/items/{feature_id}
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Handle single feature request.

        Args:
            req: Azure Functions HTTP request

        Returns:
            HttpResponse with GeoJSON Feature
        """
        try:
            # Extract route parameters
            collection_id = req.route_params.get('collection_id')
            feature_id = req.route_params.get('feature_id')

            if not collection_id or not feature_id:
                return self._error_response(
                    message="Collection ID and Feature ID are required",
                    status_code=400
                )

            # Get precision from query params (optional)
            precision = 6
            if 'precision' in req.params:
                try:
                    precision = int(req.params['precision'])
                except ValueError:
                    pass

            # Get feature via service
            base_url = self._get_base_url(req)
            feature = self.service.get_feature(
                collection_id=collection_id,
                feature_id=feature_id,
                precision=precision,
                base_url=base_url
            )

            logger.info(f"Feature requested: collection='{collection_id}', id='{feature_id}'")

            return self._json_response(
                feature,
                content_type="application/geo+json"
            )

        except ValueError as e:
            # Feature not found
            logger.warning(f"Feature not found: {e}")
            return self._error_response(
                message=str(e),
                status_code=404,
                error_type="NotFound"
            )
        except Exception as e:
            logger.error(f"Error getting feature: {e}")
            return self._error_response(
                message=f"Internal server error: {str(e)}",
                status_code=500,
                error_type="InternalServerError"
            )
