# ============================================================================
# MAP STATE HTTP TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP handlers - Azure Functions triggers for map states
# PURPOSE: Handle HTTP requests for map state CRUD and snapshots
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# EXPORTS: list_maps, get_map, create_map, update_map, delete_map,
#          list_snapshots, get_snapshot, restore_snapshot
# DEPENDENCIES: azure.functions, services.map_state_service
# ============================================================================
"""
Map State HTTP Triggers.

Azure Functions HTTP endpoint handlers for web map configurations.

Endpoints:
    GET    /maps                              - List maps
    GET    /maps/{map_id}                     - Get map
    POST   /maps                              - Create map
    PUT    /maps/{map_id}                     - Update map
    DELETE /maps/{map_id}                     - Delete map
    GET    /maps/{map_id}/snapshots           - List snapshots
    GET    /maps/{map_id}/snapshots/{version} - Get snapshot
    POST   /maps/{map_id}/restore/{version}   - Restore from snapshot

Created: 23 JAN 2026
"""

import azure.functions as func
import json
import logging
from typing import Optional

from services.map_state_service import get_map_state_service

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
# LIST MAPS
# =============================================================================

def list_maps(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all map states.

    GET /api/maps
    GET /api/maps?map_type=maplibre
    GET /api/maps?tags=flood,houston
    GET /api/maps?limit=20&offset=0

    Query params:
        map_type: Filter by map type (maplibre, leaflet, openlayers)
        tags: Comma-separated tags to filter by
        limit: Maximum results (default 100)
        offset: Pagination offset (default 0)

    Returns:
        200: List of map states with pagination
        500: Server error
    """
    try:
        service = get_map_state_service()
        base_url = _get_base_url(req)

        # Parse query params
        map_type = req.params.get("map_type")
        tags_param = req.params.get("tags")
        tags = tags_param.split(",") if tags_param else None
        limit = int(req.params.get("limit", "100"))
        offset = int(req.params.get("offset", "0"))

        result = service.list_maps(
            base_url=base_url,
            map_type=map_type,
            tags=tags,
            limit=limit,
            offset=offset
        )
        return _json_response(result)

    except ValueError as e:
        return _error_response("BadRequest", str(e), 400)
    except Exception as e:
        logger.error(f"Error listing maps: {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# GET MAP
# =============================================================================

def get_map(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a specific map state.

    GET /api/maps/{map_id}
    GET /api/maps/{map_id}?include_snapshots=true

    Query params:
        include_snapshots: If true, include recent snapshots list

    Returns:
        200: Map state with layers and links
        404: Map not found
        500: Server error
    """
    map_id = req.route_params.get("map_id")

    if not map_id:
        return _error_response("BadRequest", "map_id is required", 400)

    include_snapshots = req.params.get("include_snapshots", "").lower() == "true"

    try:
        service = get_map_state_service()
        base_url = _get_base_url(req)

        result = service.get_map(
            map_id=map_id,
            base_url=base_url,
            include_snapshots=include_snapshots
        )

        if result is None:
            return _error_response(
                "NotFound",
                f"Map '{map_id}' not found",
                404
            )

        return _json_response(result)

    except Exception as e:
        logger.error(f"Error getting map '{map_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# CREATE MAP
# =============================================================================

def create_map(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create a new map state.

    POST /api/maps
    {
        "name": "Houston Flood Analysis",
        "description": "Flood depth analysis for Houston area",
        "map_type": "maplibre",
        "center_lon": -95.3698,
        "center_lat": 29.7604,
        "zoom_level": 12,
        "layers": [
            {
                "layer_id": "basemap",
                "source_type": "xyz_tiles",
                "source_id": "osm-standard",
                "name": "OpenStreetMap",
                "visible": true,
                "z_index": 0,
                "is_basemap": true,
                "options": {
                    "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                }
            }
        ],
        "tags": ["flood", "houston"]
    }

    Returns:
        201: Created map state
        400: Invalid request
        409: Map with same name already exists
        500: Server error
    """
    try:
        body = req.get_json()
    except ValueError:
        return _error_response("BadRequest", "Invalid JSON body", 400)

    name = body.get("name")
    if not name:
        return _error_response("BadRequest", "name is required", 400)

    try:
        service = get_map_state_service()

        # Validate configuration
        warnings = service.validate_map_config(body)
        if warnings:
            # Check for critical errors vs warnings
            errors = [w for w in warnings if "is required" in w or "must be" in w]
            if errors:
                return _error_response("BadRequest", "; ".join(errors), 400)
            # Log non-critical warnings
            logger.warning(f"Map config warnings: {warnings}")

        result = service.create_map(
            name=name,
            description=body.get("description"),
            map_type=body.get("map_type", "maplibre"),
            center_lon=body.get("center_lon"),
            center_lat=body.get("center_lat"),
            zoom_level=body.get("zoom_level"),
            bounds=body.get("bounds"),
            layers=body.get("layers"),
            custom_attributes=body.get("custom_attributes"),
            tags=body.get("tags"),
            thumbnail_url=body.get("thumbnail_url")
        )

        response_data = {
            "success": True,
            "message": f"Map '{name}' created",
            "map": result
        }

        if warnings:
            response_data["warnings"] = warnings

        return _json_response(response_data, status_code=201)

    except ValueError as e:
        # Map already exists
        if "already exists" in str(e):
            return _error_response("Conflict", str(e), 409)
        return _error_response("BadRequest", str(e), 400)
    except Exception as e:
        logger.error(f"Error creating map '{name}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# UPDATE MAP
# =============================================================================

def update_map(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update a map state.

    PUT /api/maps/{map_id}
    {
        "center_lon": -95.4,
        "zoom_level": 14,
        "layers": [...]
    }

    Note: Creates automatic snapshot before update.

    Returns:
        200: Updated map state
        400: Invalid request
        404: Map not found
        500: Server error
    """
    map_id = req.route_params.get("map_id")

    if not map_id:
        return _error_response("BadRequest", "map_id is required", 400)

    try:
        body = req.get_json()
    except ValueError:
        return _error_response("BadRequest", "Invalid JSON body", 400)

    try:
        service = get_map_state_service()

        # Check if map exists
        if not service.map_exists(map_id):
            return _error_response(
                "NotFound",
                f"Map '{map_id}' not found",
                404
            )

        result = service.update_map(
            map_id=map_id,
            name=body.get("name"),
            description=body.get("description"),
            map_type=body.get("map_type"),
            center_lon=body.get("center_lon"),
            center_lat=body.get("center_lat"),
            zoom_level=body.get("zoom_level"),
            bounds=body.get("bounds"),
            layers=body.get("layers"),
            custom_attributes=body.get("custom_attributes"),
            tags=body.get("tags"),
            thumbnail_url=body.get("thumbnail_url")
        )

        return _json_response({
            "success": True,
            "message": f"Map '{map_id}' updated (snapshot created)",
            "map": result
        })

    except ValueError as e:
        return _error_response("BadRequest", str(e), 400)
    except Exception as e:
        logger.error(f"Error updating map '{map_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# DELETE MAP
# =============================================================================

def delete_map(req: func.HttpRequest) -> func.HttpResponse:
    """
    Delete a map state.

    DELETE /api/maps/{map_id}

    Note: Creates final snapshot before deletion.

    Returns:
        200: Deleted successfully
        404: Map not found
        500: Server error
    """
    map_id = req.route_params.get("map_id")

    if not map_id:
        return _error_response("BadRequest", "map_id is required", 400)

    try:
        service = get_map_state_service()

        deleted = service.delete_map(map_id)

        if not deleted:
            return _error_response(
                "NotFound",
                f"Map '{map_id}' not found",
                404
            )

        return _json_response({
            "success": True,
            "message": f"Map '{map_id}' deleted (final snapshot created)"
        })

    except Exception as e:
        logger.error(f"Error deleting map '{map_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# LIST SNAPSHOTS
# =============================================================================

def list_snapshots(req: func.HttpRequest) -> func.HttpResponse:
    """
    List snapshots for a map.

    GET /api/maps/{map_id}/snapshots
    GET /api/maps/{map_id}/snapshots?limit=20

    Returns:
        200: List of snapshots
        404: Map not found
        500: Server error
    """
    map_id = req.route_params.get("map_id")

    if not map_id:
        return _error_response("BadRequest", "map_id is required", 400)

    limit = int(req.params.get("limit", "50"))

    try:
        service = get_map_state_service()
        base_url = _get_base_url(req)

        # Check if map exists
        if not service.map_exists(map_id):
            return _error_response(
                "NotFound",
                f"Map '{map_id}' not found",
                404
            )

        result = service.list_snapshots(
            map_id=map_id,
            base_url=base_url,
            limit=limit
        )
        return _json_response(result)

    except Exception as e:
        logger.error(f"Error listing snapshots for '{map_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# GET SNAPSHOT
# =============================================================================

def get_snapshot(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a specific snapshot.

    GET /api/maps/{map_id}/snapshots/{version}

    Returns:
        200: Snapshot with full state
        404: Snapshot not found
        500: Server error
    """
    map_id = req.route_params.get("map_id")
    version_str = req.route_params.get("version")

    if not map_id:
        return _error_response("BadRequest", "map_id is required", 400)
    if not version_str:
        return _error_response("BadRequest", "version is required", 400)

    try:
        version = int(version_str)
    except ValueError:
        return _error_response("BadRequest", "version must be an integer", 400)

    try:
        service = get_map_state_service()
        base_url = _get_base_url(req)

        result = service.get_snapshot(
            map_id=map_id,
            version=version,
            base_url=base_url
        )

        if result is None:
            return _error_response(
                "NotFound",
                f"Snapshot v{version} not found for map '{map_id}'",
                404
            )

        return _json_response(result)

    except Exception as e:
        logger.error(f"Error getting snapshot v{version} for '{map_id}': {e}")
        return _error_response("InternalError", str(e), 500)


# =============================================================================
# RESTORE SNAPSHOT
# =============================================================================

def restore_snapshot(req: func.HttpRequest) -> func.HttpResponse:
    """
    Restore a map from a snapshot.

    POST /api/maps/{map_id}/restore/{version}

    Note: Creates snapshot of current state before restore.

    Returns:
        200: Restored successfully
        404: Snapshot not found
        500: Server error
    """
    map_id = req.route_params.get("map_id")
    version_str = req.route_params.get("version")

    if not map_id:
        return _error_response("BadRequest", "map_id is required", 400)
    if not version_str:
        return _error_response("BadRequest", "version is required", 400)

    try:
        version = int(version_str)
    except ValueError:
        return _error_response("BadRequest", "version must be an integer", 400)

    try:
        service = get_map_state_service()

        restored = service.restore_snapshot(map_id, version)

        if not restored:
            return _error_response(
                "NotFound",
                f"Snapshot v{version} not found for map '{map_id}'",
                404
            )

        return _json_response({
            "success": True,
            "message": f"Map '{map_id}' restored from snapshot v{version}"
        })

    except Exception as e:
        logger.error(f"Error restoring snapshot v{version} for '{map_id}': {e}")
        return _error_response("InternalError", str(e), 500)
