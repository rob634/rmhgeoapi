# ============================================================================
# CLAUDE CONTEXT - XARRAY API HTTP TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger Layer - HTTP handlers for xarray direct access endpoints
# PURPOSE: Azure Functions HTTP handlers for xarray API
# LAST_REVIEWED: 19 DEC 2025
# EXPORTS: get_xarray_triggers
# DEPENDENCIES: azure-functions, .service
# PORTABLE: Yes - works in rmhgeoapi and rmhogcapi
# ============================================================================
"""
xarray API HTTP Triggers (SYNC VERSION).

Azure Functions HTTP handlers for xarray direct access endpoints.

Endpoints:
- GET /api/xarray/point/{collection}/{item} - Time-series at a point
- GET /api/xarray/statistics/{collection}/{item} - Regional stats over time
- GET /api/xarray/aggregate/{collection}/{item} - Temporal aggregation export

Integration (in function_app.py):
    from xarray_api import get_xarray_triggers

    _xarray_triggers = get_xarray_triggers()
    # Register with decorator pattern

SYNC VERSION (19 DEC 2025):
    Removed asyncio boilerplate - services are now synchronous.
    All handlers are simple sync functions.
"""

import azure.functions as func
import json
import logging
from typing import Dict, Any, List

from .config import get_xarray_api_config
from .service import XarrayAPIService

logger = logging.getLogger(__name__)


# ============================================================================
# TRIGGER REGISTRY FUNCTION
# ============================================================================

def get_xarray_triggers() -> List[Dict[str, Any]]:
    """
    Get list of xarray API trigger configurations for function_app.py.

    Returns:
        List of dicts with keys:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable trigger handler
    """
    return [
        {
            'route': 'xarray/point/{collection}/{item}',
            'methods': ['GET'],
            'handler': XarrayPointTrigger().handle
        },
        {
            'route': 'xarray/statistics/{collection}/{item}',
            'methods': ['GET'],
            'handler': XarrayStatisticsTrigger().handle
        },
        {
            'route': 'xarray/aggregate/{collection}/{item}',
            'methods': ['GET'],
            'handler': XarrayAggregateTrigger().handle
        },
    ]


# ============================================================================
# BASE TRIGGER CLASS
# ============================================================================

class BaseXarrayTrigger:
    """Base class for xarray API triggers."""

    def __init__(self):
        self.config = get_xarray_api_config()

    def _error_response(self, message: str, status_code: int = 400) -> func.HttpResponse:
        """Create JSON error response."""
        return func.HttpResponse(
            json.dumps({"error": message}),
            status_code=status_code,
            mimetype="application/json"
        )

    def _json_response(self, data: Dict, status_code: int = 200) -> func.HttpResponse:
        """Create JSON success response."""
        return func.HttpResponse(
            json.dumps(data, default=str),
            status_code=status_code,
            mimetype="application/json"
        )

    def _binary_response(
        self,
        data: bytes,
        content_type: str,
        status_code: int = 200
    ) -> func.HttpResponse:
        """Create binary response (image, etc.)."""
        return func.HttpResponse(
            data,
            status_code=status_code,
            mimetype=content_type
        )


# ============================================================================
# POINT TIME-SERIES TRIGGER
# ============================================================================

class XarrayPointTrigger(BaseXarrayTrigger):
    """
    Get time-series at a point.

    GET /api/xarray/point/{collection}/{item}
        ?location={name}|{lon},{lat}
        &asset=data
        &start_time=2015-01-01
        &end_time=2015-12-31
        &aggregation=none|daily|monthly|yearly
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle point time-series request."""
        service = None
        try:
            # Get path parameters
            collection = req.route_params.get('collection')
            item = req.route_params.get('item')

            if not collection or not item:
                return self._error_response("Missing collection or item in path")

            # Get query parameters
            location = req.params.get('location')
            if not location:
                return self._error_response("Missing required parameter: location")

            asset = req.params.get('asset', 'data')
            start_time = req.params.get('start_time')
            end_time = req.params.get('end_time')
            aggregation = req.params.get('aggregation', 'none')

            # Validate aggregation
            if aggregation not in ['none', 'daily', 'monthly', 'yearly']:
                return self._error_response(
                    f"Invalid aggregation: {aggregation}. Use none, daily, monthly, or yearly."
                )

            # Create service and execute (SYNC - no asyncio needed)
            service = XarrayAPIService(self.config)
            response = service.point_timeseries(
                collection_id=collection,
                item_id=item,
                location=location,
                asset=asset,
                start_time=start_time,
                end_time=end_time,
                aggregation=aggregation
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            return self._json_response(response.json_data)

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in xarray point: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()


# ============================================================================
# REGIONAL STATISTICS TRIGGER
# ============================================================================

class XarrayStatisticsTrigger(BaseXarrayTrigger):
    """
    Get regional statistics over time.

    GET /api/xarray/statistics/{collection}/{item}
        ?bbox={minx},{miny},{maxx},{maxy}
        &asset=data
        &start_time=2015-01-01
        &end_time=2015-12-31
        &temporal_resolution=daily|monthly|yearly
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle regional statistics request."""
        service = None
        try:
            # Get path parameters
            collection = req.route_params.get('collection')
            item = req.route_params.get('item')

            if not collection or not item:
                return self._error_response("Missing collection or item in path")

            # Get query parameters
            bbox = req.params.get('bbox')
            if not bbox:
                return self._error_response("Missing required parameter: bbox")

            asset = req.params.get('asset', 'data')
            start_time = req.params.get('start_time')
            end_time = req.params.get('end_time')
            temporal_resolution = req.params.get('temporal_resolution', 'monthly')

            # Validate temporal_resolution
            if temporal_resolution not in ['daily', 'monthly', 'yearly']:
                return self._error_response(
                    f"Invalid temporal_resolution: {temporal_resolution}. Use daily, monthly, or yearly."
                )

            # Create service and execute (SYNC - no asyncio needed)
            service = XarrayAPIService(self.config)
            response = service.regional_statistics(
                collection_id=collection,
                item_id=item,
                bbox=bbox,
                asset=asset,
                start_time=start_time,
                end_time=end_time,
                temporal_resolution=temporal_resolution
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            return self._json_response(response.json_data)

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in xarray statistics: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()


# ============================================================================
# TEMPORAL AGGREGATION TRIGGER
# ============================================================================

class XarrayAggregateTrigger(BaseXarrayTrigger):
    """
    Compute temporal aggregation and export.

    GET /api/xarray/aggregate/{collection}/{item}
        ?bbox={minx},{miny},{maxx},{maxy}
        &asset=data
        &start_time=2015-01-01
        &end_time=2015-12-31
        &aggregation=mean|max|min|sum
        &format=json|tif|png|npy
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle temporal aggregation request."""
        service = None
        try:
            # Get path parameters
            collection = req.route_params.get('collection')
            item = req.route_params.get('item')

            if not collection or not item:
                return self._error_response("Missing collection or item in path")

            # Get query parameters
            bbox = req.params.get('bbox')
            if not bbox:
                return self._error_response("Missing required parameter: bbox")

            asset = req.params.get('asset', 'data')
            start_time = req.params.get('start_time')
            end_time = req.params.get('end_time')
            aggregation = req.params.get('aggregation', 'mean')
            format_param = req.params.get('format', 'json')

            # Validate aggregation
            if aggregation not in ['mean', 'max', 'min', 'sum']:
                return self._error_response(
                    f"Invalid aggregation: {aggregation}. Use mean, max, min, or sum."
                )

            # Validate format
            if format_param not in ['json', 'tif', 'png', 'npy']:
                return self._error_response(
                    f"Invalid format: {format_param}. Use json, tif, png, or npy."
                )

            # Create service and execute (SYNC - no asyncio needed)
            service = XarrayAPIService(self.config)
            response = service.temporal_aggregation(
                collection_id=collection,
                item_id=item,
                bbox=bbox,
                asset=asset,
                start_time=start_time,
                end_time=end_time,
                aggregation=aggregation,
                format=format_param
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            if response.json_data:
                return self._json_response(response.json_data)
            else:
                return self._binary_response(
                    response.binary_data,
                    response.content_type
                )

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in xarray aggregate: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()
