# ============================================================================
# RASTER RENDER CONFIG HTTP TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP handlers - Azure Functions triggers for render configs
# PURPOSE: Handle HTTP requests for raster render configuration CRUD
# LAST_REVIEWED: 22 JAN 2026
# EXPORTS: list_renders, get_render, create_render, delete_render, set_default_render
# DEPENDENCIES: azure.functions, services.raster_render_service
# ============================================================================
"""
Raster Render Config HTTP Triggers.

Azure Functions HTTP endpoint handlers for TiTiler render configurations.

Endpoints:
    GET    /raster/{cog_id}/renders              - List renders
    GET    /raster/{cog_id}/renders/{render_id}  - Get render (with TiTiler params)
    POST   /raster/{cog_id}/renders              - Create render
    PUT    /raster/{cog_id}/renders/{render_id}  - Update render
    DELETE /raster/{cog_id}/renders/{render_id}  - Delete render
    POST   /raster/{cog_id}/renders/{render_id}/default - Set as default

Created: 22 JAN 2026
Epic: E2 Raster Data as API → F2.11 Raster Render Configuration System
"""

import azure.functions as func
import json
import logging
from typing import Optional

from services.raster_render_service import get_raster_render_service

logger = logging.getLogger(__name__)


def _get_base_url(req: func.HttpRequest) -> str:
    """Extract base URL from request."""
    # Try to get from X-Forwarded headers first (for proxied requests)
    forwarded_host = req.headers.get("X-Forwarded-Host")
    forwarded_proto = req.headers.get("X-Forwarded-Proto", "https")

    if forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}"

    # Fall back to request URL
    url = req.url
    # Extract base (scheme + host)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _json_response(
    data: dict,
    status_code: int = 200,
    headers: Optional[dict] = None
) -> func.HttpResponse:
    """Create JSON HTTP response."""
    response_headers = {"Content-Type": "application/json"}
    if headers:
        response_headers.update(headers)

    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status_code,
        headers=response_headers
    )


def _error_response(
    code: str,
    description: str,
    status_code: int = 400
) -> func.HttpResponse:
    """Create error HTTP response."""
    return _json_response(
        {"code": code, "description": description},
        status_code=status_code
    )


# =============================================================================
# LIST RENDERS
# =============================================================================

def list_renders(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all render configs for a COG.

    GET /api/raster/{cog_id}/renders

    Returns:
        200: List of render configs
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")
    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)

    try:
        service = get_raster_render_service()
        base_url = _get_base_url(req)

        result = service.list_renders(cog_id, base_url)
        return _json_response(result)

    except Exception as e:
        logger.error(f"Error listing renders for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# GET RENDER
# =============================================================================

def get_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a specific render config.

    GET /api/raster/{cog_id}/renders/{render_id}
    GET /api/raster/{cog_id}/renders/{render_id}?include_params=true

    Query params:
        include_params: If true, include titiler_params and stac_render

    Returns:
        200: Render config
        404: Render not found
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")
    render_id = req.route_params.get("render_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)
    if not render_id:
        return _error_response("BadRequest", "render_id is required", 400)

    include_params = req.params.get("include_params", "").lower() == "true"

    try:
        service = get_raster_render_service()

        result = service.get_render(cog_id, render_id, include_titiler_params=include_params)

        if result is None:
            return _error_response(
                "NotFound",
                f"Render '{render_id}' not found for COG '{cog_id}'",
                404
            )

        return _json_response(result)

    except Exception as e:
        logger.error(f"Error getting render '{render_id}' for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# GET DEFAULT RENDER
# =============================================================================

def get_default_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get the default render config for a COG.

    GET /api/raster/{cog_id}/renders/default

    Returns:
        200: Default render config
        404: No default render set
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)

    include_params = req.params.get("include_params", "").lower() == "true"

    try:
        service = get_raster_render_service()

        result = service.get_default_render(cog_id, include_titiler_params=include_params)

        if result is None:
            return _error_response(
                "NotFound",
                f"No default render configured for COG '{cog_id}'",
                404
            )

        return _json_response(result)

    except Exception as e:
        logger.error(f"Error getting default render for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# CREATE/UPDATE RENDER
# =============================================================================

def create_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create or update a render config.

    POST /api/raster/{cog_id}/renders
    {
        "render_id": "flood-depth",
        "title": "Flood Depth Visualization",
        "description": "Shows flood depth with blue gradient",
        "render_spec": {
            "colormap_name": "blues",
            "rescale": [[0, 5]]
        },
        "is_default": false
    }

    Returns:
        201: Created render config
        400: Invalid request
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        return _error_response("BadRequest", "Invalid JSON body", 400)

    render_id = body.get("render_id")
    if not render_id:
        return _error_response("BadRequest", "render_id is required", 400)

    render_spec = body.get("render_spec")
    if not render_spec:
        return _error_response("BadRequest", "render_spec is required", 400)

    title = body.get("title")
    description = body.get("description")
    is_default = body.get("is_default", False)

    try:
        service = get_raster_render_service()

        # Validate render_spec
        warnings = service.validate_render_spec(render_spec)
        if warnings:
            logger.warning(f"Render spec validation warnings: {warnings}")

        result = service.create_render(
            cog_id=cog_id,
            render_id=render_id,
            render_spec=render_spec,
            title=title,
            description=description,
            is_default=is_default
        )

        response_data = {
            "success": True,
            "message": f"Render '{render_id}' created for COG '{cog_id}'",
            "render": result
        }

        if warnings:
            response_data["warnings"] = warnings

        return _json_response(response_data, status_code=201)

    except ValueError as e:
        return _error_response("BadRequest", str(e), 400)
    except Exception as e:
        logger.error(f"Error creating render '{render_id}' for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)


def update_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update an existing render config.

    PUT /api/raster/{cog_id}/renders/{render_id}
    {
        "title": "Updated Title",
        "render_spec": {...},
        "is_default": true
    }

    Returns:
        200: Updated render config
        400: Invalid request
        404: Render not found
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")
    render_id = req.route_params.get("render_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)
    if not render_id:
        return _error_response("BadRequest", "render_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        return _error_response("BadRequest", "Invalid JSON body", 400)

    try:
        service = get_raster_render_service()

        # Check if render exists
        if not service.render_exists(cog_id, render_id):
            return _error_response(
                "NotFound",
                f"Render '{render_id}' not found for COG '{cog_id}'",
                404
            )

        # Get existing render to merge with updates
        existing = service.get_render(cog_id, render_id)

        render_spec = body.get("render_spec", existing.get("render_spec"))
        title = body.get("title", existing.get("title"))
        description = body.get("description", existing.get("description"))
        is_default = body.get("is_default", existing.get("is_default", False))

        result = service.create_render(
            cog_id=cog_id,
            render_id=render_id,
            render_spec=render_spec,
            title=title,
            description=description,
            is_default=is_default
        )

        return _json_response({
            "success": True,
            "message": f"Render '{render_id}' updated",
            "render": result
        })

    except ValueError as e:
        return _error_response("BadRequest", str(e), 400)
    except Exception as e:
        logger.error(f"Error updating render '{render_id}' for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# DELETE RENDER
# =============================================================================

def delete_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Delete a render config.

    DELETE /api/raster/{cog_id}/renders/{render_id}

    Returns:
        200: Deleted successfully
        404: Render not found
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")
    render_id = req.route_params.get("render_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)
    if not render_id:
        return _error_response("BadRequest", "render_id is required", 400)

    try:
        service = get_raster_render_service()

        deleted = service.delete_render(cog_id, render_id)

        if not deleted:
            return _error_response(
                "NotFound",
                f"Render '{render_id}' not found for COG '{cog_id}'",
                404
            )

        return _json_response({
            "success": True,
            "message": f"Render '{render_id}' deleted from COG '{cog_id}'"
        })

    except Exception as e:
        logger.error(f"Error deleting render '{render_id}' for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# SET DEFAULT
# =============================================================================

def set_default_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Set a render config as the default for its COG.

    POST /api/raster/{cog_id}/renders/{render_id}/default

    Returns:
        200: Set as default
        404: Render not found
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")
    render_id = req.route_params.get("render_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)
    if not render_id:
        return _error_response("BadRequest", "render_id is required", 400)

    try:
        service = get_raster_render_service()

        updated = service.set_default(cog_id, render_id)

        if not updated:
            return _error_response(
                "NotFound",
                f"Render '{render_id}' not found for COG '{cog_id}'",
                404
            )

        return _json_response({
            "success": True,
            "message": f"Render '{render_id}' set as default for COG '{cog_id}'"
        })

    except Exception as e:
        logger.error(f"Error setting default render: {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# AUTO-GENERATE DEFAULT
# =============================================================================

def create_default_render(req: func.HttpRequest) -> func.HttpResponse:
    """
    Auto-generate a default render config based on COG properties.

    POST /api/raster/{cog_id}/renders/auto-default
    {
        "dtype": "float32",
        "band_count": 1,
        "nodata": -9999
    }

    Returns:
        201: Created default render
        400: Invalid request
        500: Server error
    """
    cog_id = req.route_params.get("cog_id")

    if not cog_id:
        return _error_response("BadRequest", "cog_id is required", 400)

    try:
        body = req.get_json() if req.get_body() else {}
    except ValueError:
        body = {}

    dtype = body.get("dtype", "float32")
    band_count = body.get("band_count", 1)
    nodata = body.get("nodata")

    try:
        service = get_raster_render_service()

        result = service.create_default_for_cog(
            cog_id=cog_id,
            dtype=dtype,
            band_count=band_count,
            nodata=nodata
        )

        return _json_response({
            "success": True,
            "message": f"Default render created for COG '{cog_id}'",
            "render": result
        }, status_code=201)

    except Exception as e:
        logger.error(f"Error creating default render for '{cog_id}': {e}")
        return _error_response("InternalError", str(e), 500)
