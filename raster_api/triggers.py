# ============================================================================
# CLAUDE CONTEXT - RASTER API HTTP TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger Layer - HTTP handlers for raster convenience endpoints
# PURPOSE: Azure Functions HTTP handlers for raster API
# LAST_REVIEWED: 19 DEC 2025
# EXPORTS: get_raster_triggers
# DEPENDENCIES: azure-functions, .service
# PORTABLE: Yes - works in rmhgeoapi and rmhogcapi
# ============================================================================
"""
Raster API HTTP Triggers (SYNC VERSION).

Azure Functions HTTP handlers for raster convenience endpoints.

Endpoints:
- GET /api/raster/extract/{collection}/{item} - Extract bbox as image
- GET /api/raster/point/{collection}/{item} - Point value query
- GET /api/raster/clip/{collection}/{item} - Clip to admin boundary
- GET /api/raster/preview/{collection}/{item} - Quick preview image

Integration (in function_app.py):
    from raster_api import get_raster_triggers

    _raster_triggers = get_raster_triggers()
    # Register with decorator pattern (see function_app.py for STAC API example)

SYNC VERSION (19 DEC 2025):
    Removed asyncio boilerplate - services are now synchronous.
    All handlers are simple sync functions.
"""

import azure.functions as func
import json
import logging
from typing import Dict, Any, List

from .config import get_raster_api_config
from .service import RasterAPIService

logger = logging.getLogger(__name__)


# ============================================================================
# TRIGGER REGISTRY FUNCTION
# ============================================================================

def get_raster_triggers() -> List[Dict[str, Any]]:
    """
    Get list of Raster API trigger configurations for function_app.py.

    Returns:
        List of dicts with keys:
        - route: URL route pattern
        - methods: List of HTTP methods
        - handler: Callable trigger handler
    """
    return [
        {
            'route': 'raster/extract/{collection}/{item}',
            'methods': ['GET'],
            'handler': RasterExtractTrigger().handle
        },
        {
            'route': 'raster/point/{collection}/{item}',
            'methods': ['GET'],
            'handler': RasterPointTrigger().handle
        },
        {
            'route': 'raster/clip/{collection}/{item}',
            'methods': ['GET', 'POST'],
            'handler': RasterClipTrigger().handle
        },
        {
            'route': 'raster/preview/{collection}/{item}',
            'methods': ['GET'],
            'handler': RasterPreviewTrigger().handle
        },
    ]


# ============================================================================
# BASE TRIGGER CLASS
# ============================================================================

class BaseRasterTrigger:
    """Base class for raster API triggers."""

    def __init__(self):
        self.config = get_raster_api_config()

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
            json.dumps(data),
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
# EXTRACT TRIGGER
# ============================================================================

class RasterExtractTrigger(BaseRasterTrigger):
    """
    Extract bbox from raster as image.

    GET /api/raster/extract/{collection}/{item}
        ?bbox={minx},{miny},{maxx},{maxy}
        &format=tif|png|npy
        &asset=visual|data
        &time_index=1
        &colormap=turbo
        &rescale=0,100
        &width=256
        &height=256
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle extract request."""
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

            format_param = req.params.get('format', 'png')
            asset = req.params.get('asset', 'data')
            time_index = int(req.params.get('time_index', '1'))
            colormap = req.params.get('colormap')
            rescale = req.params.get('rescale')
            width = req.params.get('width')
            height = req.params.get('height')

            # Validate format
            if format_param not in ['tif', 'png', 'npy', 'jpeg', 'webp']:
                return self._error_response(f"Invalid format: {format_param}")

            # Create service and execute (SYNC - no asyncio needed)
            service = RasterAPIService(self.config)
            response = service.extract_bbox(
                collection_id=collection,
                item_id=item,
                bbox=bbox,
                format=format_param,
                asset=asset,
                time_index=time_index,
                colormap=colormap,
                rescale=rescale,
                width=int(width) if width else None,
                height=int(height) if height else None
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            # Determine content type
            content_types = {
                'tif': 'image/tiff',
                'png': 'image/png',
                'jpeg': 'image/jpeg',
                'webp': 'image/webp',
                'npy': 'application/octet-stream'
            }

            return self._binary_response(
                response.data,
                response.content_type or content_types.get(format_param, 'application/octet-stream')
            )

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in raster extract: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()


# ============================================================================
# POINT TRIGGER
# ============================================================================

class RasterPointTrigger(BaseRasterTrigger):
    """
    Get raster value at a point.

    GET /api/raster/point/{collection}/{item}
        ?location={name}|{lon},{lat}
        &asset=data
        &time_index=1
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle point query request."""
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
            time_index = int(req.params.get('time_index', '1'))

            # Create service and execute (SYNC - no asyncio needed)
            service = RasterAPIService(self.config)
            response = service.point_query(
                collection_id=collection,
                item_id=item,
                location=location,
                asset=asset,
                time_index=time_index
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            return self._json_response(response.json_data)

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in raster point: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()


# ============================================================================
# CLIP TRIGGER
# ============================================================================

class RasterClipTrigger(BaseRasterTrigger):
    """
    Clip raster to geometry.

    GET /api/raster/clip/{collection}/{item}
        ?boundary_type=country|state|county
        &boundary_id={id}
        &format=tif|png
        &time_index=1

    POST /api/raster/clip/{collection}/{item}
        Body: GeoJSON geometry
        ?format=tif|png
        &time_index=1
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle clip request."""
        service = None
        try:
            # Get path parameters
            collection = req.route_params.get('collection')
            item = req.route_params.get('item')

            if not collection or not item:
                return self._error_response("Missing collection or item in path")

            # Get query parameters
            format_param = req.params.get('format', 'tif')
            asset = req.params.get('asset', 'data')
            time_index = int(req.params.get('time_index', '1'))
            colormap = req.params.get('colormap')
            rescale = req.params.get('rescale')

            # Get geometry - either from POST body or from boundary lookup
            geometry = None

            if req.method == 'POST':
                # POST: geometry in body
                try:
                    body = req.get_json()
                    if 'geometry' in body:
                        geometry = body['geometry']
                    elif body.get('type') in ['Polygon', 'MultiPolygon']:
                        geometry = body
                    else:
                        return self._error_response("POST body must contain GeoJSON geometry")
                except ValueError:
                    return self._error_response("Invalid JSON in request body")
            else:
                # GET: boundary lookup (simplified - would need OGC Features client)
                boundary_type = req.params.get('boundary_type')
                boundary_id = req.params.get('boundary_id')

                if not boundary_type or not boundary_id:
                    return self._error_response(
                        "GET requires boundary_type and boundary_id, or use POST with GeoJSON"
                    )

                # TODO: Look up boundary from OGC Features API
                return self._error_response(
                    "Boundary lookup not yet implemented. Use POST with GeoJSON geometry.",
                    501
                )

            if not geometry:
                return self._error_response("No geometry provided")

            # Create service and execute (SYNC - no asyncio needed)
            service = RasterAPIService(self.config)
            response = service.clip_by_geometry(
                collection_id=collection,
                item_id=item,
                geometry=geometry,
                format=format_param,
                asset=asset,
                time_index=time_index,
                colormap=colormap,
                rescale=rescale
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            content_types = {
                'tif': 'image/tiff',
                'png': 'image/png',
            }

            return self._binary_response(
                response.data,
                response.content_type or content_types.get(format_param, 'image/tiff')
            )

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in raster clip: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()


# ============================================================================
# PREVIEW TRIGGER
# ============================================================================

class RasterPreviewTrigger(BaseRasterTrigger):
    """
    Get preview image of raster.

    GET /api/raster/preview/{collection}/{item}
        ?format=png|jpeg|webp
        &asset=data
        &time_index=1
        &max_size=512
        &colormap=viridis
        &rescale=0,100
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle preview request."""
        service = None
        try:
            # Get path parameters
            collection = req.route_params.get('collection')
            item = req.route_params.get('item')

            if not collection or not item:
                return self._error_response("Missing collection or item in path")

            # Get query parameters
            format_param = req.params.get('format', 'png')
            asset = req.params.get('asset', 'data')
            time_index = int(req.params.get('time_index', '1'))
            max_size = int(req.params.get('max_size', '512'))
            colormap = req.params.get('colormap')
            rescale = req.params.get('rescale')

            # Validate format
            if format_param not in ['png', 'jpeg', 'webp']:
                return self._error_response(f"Invalid format: {format_param}")

            # Create service and execute (SYNC - no asyncio needed)
            service = RasterAPIService(self.config)
            response = service.preview(
                collection_id=collection,
                item_id=item,
                format=format_param,
                asset=asset,
                time_index=time_index,
                max_size=max_size,
                colormap=colormap,
                rescale=rescale
            )

            if not response.success:
                return self._error_response(response.error, response.status_code)

            content_types = {
                'png': 'image/png',
                'jpeg': 'image/jpeg',
                'webp': 'image/webp',
            }

            return self._binary_response(
                response.data,
                response.content_type or content_types.get(format_param, 'image/png')
            )

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}")
        except Exception as e:
            logger.exception(f"Error in raster preview: {e}")
            return self._error_response(f"Internal error: {str(e)}", 500)
        finally:
            if service:
                service.close()
