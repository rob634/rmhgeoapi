# ============================================================================
# EXTERNAL SERVICES BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for external service registry routes
# PURPOSE: Register, list, and manage external geospatial services
# CREATED: 22 JAN 2026
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
External Services Blueprint - Service registry administration.

Routes (8 total):
    Registration (1):
        POST /api/jobs/services/register       - Register new service with detection

    Lookup (2):
        GET  /api/jobs/services                - List all services (with filters)
        GET  /api/jobs/services/{service_id}   - Get service details

    Management (3):
        DELETE /api/jobs/services/{service_id}        - Remove service
        POST   /api/jobs/services/{service_id}/enable  - Enable health checks
        POST   /api/jobs/services/{service_id}/disable - Disable health checks

    Health (1):
        POST /api/jobs/services/{service_id}/check    - Force health check

    Statistics (1):
        GET  /api/jobs/services/stats          - Get service statistics

NOTE: Internal orchestration endpoints. Platform ACL layer will be added later.
"""

import json
import azure.functions as func
from azure.functions import Blueprint

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "admin_external_services")

bp = Blueprint()


def _service_to_dict(service) -> dict:
    """Convert ExternalService model to JSON-serializable dict."""
    return service.to_dict() if service else None


def _make_json_response(data: dict, status_code: int = 200) -> func.HttpResponse:
    """Create a JSON HTTP response."""
    return func.HttpResponse(
        body=json.dumps(data, default=str),
        status_code=status_code,
        mimetype="application/json"
    )


def _make_error_response(message: str, status_code: int = 400) -> func.HttpResponse:
    """Create an error HTTP response."""
    return _make_json_response({"error": message}, status_code)


# ============================================================================
# REGISTRATION ENDPOINT (1 route)
# ============================================================================

@bp.route(route="jobs/services/register", methods=["POST"])
def admin_service_register(req: func.HttpRequest) -> func.HttpResponse:
    """
    Register a new external service.

    POST /api/jobs/services/register

    Body (JSON):
        url: Service endpoint URL (required)
        name: Human-readable name (required)
        description: Optional description
        tags: Optional list of tags
        check_interval_minutes: Optional check interval (default: 60)

    Returns:
        Registered service with detected type and capabilities
    """
    try:
        # Parse request body
        try:
            body = req.get_json()
        except ValueError:
            return _make_error_response("Invalid JSON body", 400)

        url = body.get("url")
        name = body.get("name")

        if not url:
            return _make_error_response("url is required", 400)
        if not name:
            return _make_error_response("name is required", 400)

        description = body.get("description")
        tags = body.get("tags", [])
        check_interval_minutes = body.get("check_interval_minutes", 60)

        # Validate check_interval_minutes
        if not isinstance(check_interval_minutes, int) or check_interval_minutes < 5:
            return _make_error_response("check_interval_minutes must be an integer >= 5", 400)

        from services.external_service_health import ExternalServiceHealthService
        service = ExternalServiceHealthService()
        registered = service.register_service(
            url=url,
            name=name,
            description=description,
            tags=tags,
            check_interval_minutes=check_interval_minutes
        )

        return _make_json_response({
            "message": "Service registered successfully",
            "service": _service_to_dict(registered)
        }, 201)

    except Exception as e:
        logger.error(f"Error registering service: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# LOOKUP ENDPOINTS (2 routes)
# ============================================================================

@bp.route(route="jobs/services", methods=["GET"])
def admin_services_list(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all registered services.

    GET /api/jobs/services?status=active&type=wms&enabled=true&limit=50&offset=0

    Query Parameters:
        status: Optional status filter (active, degraded, offline, unknown)
        type: Optional service type filter
        enabled: Optional enabled filter (true/false)
        limit: Maximum results (default: 100)
        offset: Pagination offset (default: 0)

    Returns:
        List of services matching filters
    """
    try:
        from infrastructure.external_service_repository import ExternalServiceRepository
        from core.models.external_service import ServiceType, ServiceStatus

        # Parse filters
        status_str = req.params.get("status")
        type_str = req.params.get("type")
        enabled_str = req.params.get("enabled")
        limit = int(req.params.get("limit", "100"))
        offset = int(req.params.get("offset", "0"))

        # Convert to enums
        status = ServiceStatus(status_str) if status_str else None
        service_type = ServiceType(type_str) if type_str else None
        enabled = enabled_str.lower() == "true" if enabled_str else None

        repository = ExternalServiceRepository()
        services = repository.get_all(
            status=status,
            service_type=service_type,
            enabled=enabled,
            limit=limit,
            offset=offset
        )

        return _make_json_response({
            "count": len(services),
            "limit": limit,
            "offset": offset,
            "services": [_service_to_dict(s) for s in services]
        })

    except ValueError as e:
        return _make_error_response(f"Invalid parameter value: {e}", 400)
    except Exception as e:
        logger.error(f"Error listing services: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


@bp.route(route="jobs/services/{service_id}", methods=["GET"])
def admin_service_get(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get service details by ID.

    GET /api/jobs/services/{service_id}

    Path Parameters:
        service_id: Service identifier

    Returns:
        Service details or 404 if not found
    """
    try:
        service_id = req.route_params.get("service_id")
        if not service_id:
            return _make_error_response("service_id is required", 400)

        from infrastructure.external_service_repository import ExternalServiceRepository
        repository = ExternalServiceRepository()
        service = repository.get_by_id(service_id)

        if not service:
            return _make_error_response(f"Service not found: {service_id}", 404)

        return _make_json_response({
            "service": _service_to_dict(service)
        })

    except Exception as e:
        logger.error(f"Error getting service: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# MANAGEMENT ENDPOINTS (3 routes)
# ============================================================================

@bp.route(route="jobs/services/{service_id}", methods=["DELETE"])
def admin_service_delete(req: func.HttpRequest) -> func.HttpResponse:
    """
    Delete a registered service.

    DELETE /api/jobs/services/{service_id}

    Path Parameters:
        service_id: Service identifier

    Returns:
        Success message or 404 if not found
    """
    try:
        service_id = req.route_params.get("service_id")
        if not service_id:
            return _make_error_response("service_id is required", 400)

        from infrastructure.external_service_repository import ExternalServiceRepository
        repository = ExternalServiceRepository()

        # Check if exists
        service = repository.get_by_id(service_id)
        if not service:
            return _make_error_response(f"Service not found: {service_id}", 404)

        success = repository.delete(service_id)

        if success:
            return _make_json_response({
                "message": f"Service {service_id} deleted",
                "service_name": service.name
            })
        else:
            return _make_error_response(f"Failed to delete service: {service_id}", 500)

    except Exception as e:
        logger.error(f"Error deleting service: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


@bp.route(route="jobs/services/{service_id}/enable", methods=["POST"])
def admin_service_enable(req: func.HttpRequest) -> func.HttpResponse:
    """
    Enable health checks for a service.

    POST /api/jobs/services/{service_id}/enable

    Path Parameters:
        service_id: Service identifier

    Returns:
        Updated service
    """
    try:
        service_id = req.route_params.get("service_id")
        if not service_id:
            return _make_error_response("service_id is required", 400)

        from infrastructure.external_service_repository import ExternalServiceRepository
        repository = ExternalServiceRepository()

        updated = repository.update(service_id, {"enabled": True})

        if not updated:
            return _make_error_response(f"Service not found: {service_id}", 404)

        return _make_json_response({
            "message": f"Health checks enabled for {service_id}",
            "service": _service_to_dict(updated)
        })

    except Exception as e:
        logger.error(f"Error enabling service: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


@bp.route(route="jobs/services/{service_id}/disable", methods=["POST"])
def admin_service_disable(req: func.HttpRequest) -> func.HttpResponse:
    """
    Disable health checks for a service.

    POST /api/jobs/services/{service_id}/disable

    Path Parameters:
        service_id: Service identifier

    Returns:
        Updated service
    """
    try:
        service_id = req.route_params.get("service_id")
        if not service_id:
            return _make_error_response("service_id is required", 400)

        from infrastructure.external_service_repository import ExternalServiceRepository
        repository = ExternalServiceRepository()

        updated = repository.update(service_id, {"enabled": False})

        if not updated:
            return _make_error_response(f"Service not found: {service_id}", 404)

        return _make_json_response({
            "message": f"Health checks disabled for {service_id}",
            "service": _service_to_dict(updated)
        })

    except Exception as e:
        logger.error(f"Error disabling service: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# HEALTH CHECK ENDPOINT (1 route)
# ============================================================================

@bp.route(route="jobs/services/{service_id}/check", methods=["POST"])
def admin_service_check(req: func.HttpRequest) -> func.HttpResponse:
    """
    Force immediate health check for a service.

    POST /api/jobs/services/{service_id}/check

    Path Parameters:
        service_id: Service identifier

    Returns:
        Health check result
    """
    try:
        service_id = req.route_params.get("service_id")
        if not service_id:
            return _make_error_response("service_id is required", 400)

        from infrastructure.external_service_repository import ExternalServiceRepository
        from services.external_service_health import ExternalServiceHealthService

        repository = ExternalServiceRepository()
        service = repository.get_by_id(service_id)

        if not service:
            return _make_error_response(f"Service not found: {service_id}", 404)

        health_service = ExternalServiceHealthService(repository=repository)
        result = health_service.check_service(service)

        # Get updated service
        updated_service = repository.get_by_id(service_id)

        return _make_json_response({
            "check_result": {
                "service_id": result.service_id,
                "success": result.success,
                "response_ms": result.response_ms,
                "error": result.error,
                "status_before": result.status_before.value,
                "status_after": result.status_after.value,
                "triggered_notification": result.triggered_notification
            },
            "service": _service_to_dict(updated_service)
        })

    except Exception as e:
        logger.error(f"Error checking service: {e}")
        return _make_error_response(f"Internal error: {e}", 500)


# ============================================================================
# STATISTICS ENDPOINT (1 route)
# ============================================================================

@bp.route(route="jobs/services/stats", methods=["GET"])
def admin_services_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get service statistics.

    GET /api/jobs/services/stats

    Returns:
        Statistics including counts by status and type
    """
    try:
        from services.external_service_health import ExternalServiceHealthService
        health_service = ExternalServiceHealthService()
        stats = health_service.get_stats()

        return _make_json_response({
            "stats": stats
        })

    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return _make_error_response(f"Internal error: {e}", 500)
