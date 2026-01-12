# ============================================================================
# JANITOR ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for /api/cleanup/* routes
# PURPOSE: Janitor/cleanup administration endpoints
# CREATED: 12 JAN 2026 (Consolidated from function_app.py)
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
Janitor Admin Blueprint - All cleanup/* routes.

Routes (4 total):
    POST /api/cleanup/run?type={task_watchdog|job_health|orphan_detector|metadata_consistency|log_cleanup|all}
    GET  /api/cleanup/metadata-health
    GET  /api/cleanup/status
    GET  /api/cleanup/history?hours=24&type={type}&limit=50

NOTE: Using /api/cleanup/* instead of /api/admin/janitor/* because Azure Functions
reserves /api/admin/* for built-in admin UI (returns 404).
"""

import azure.functions as func
from azure.functions import Blueprint
import json

bp = Blueprint()


# ============================================================================
# JANITOR HTTP TRIGGERS (4 routes)
# ============================================================================

@bp.route(route="cleanup/run", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_run(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manually trigger a cleanup (janitor) run.

    POST /api/cleanup/run?type={task_watchdog|job_health|orphan_detector|metadata_consistency|log_cleanup|all}

    Examples:
        curl -X POST "https://.../api/cleanup/run?type=task_watchdog"
        curl -X POST "https://.../api/cleanup/run?type=metadata_consistency"
        curl -X POST "https://.../api/cleanup/run?type=all"
    """
    from triggers.janitor import janitor_run_handler
    return janitor_run_handler(req)


@bp.route(route="cleanup/metadata-health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_metadata_health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get metadata consistency health status.

    GET /api/cleanup/metadata-health

    Returns comprehensive metadata integrity check results:
    - STAC <-> Metadata cross-reference
    - Broken backlinks
    - Dataset refs integrity
    - Raster blob existence

    Example:
        curl "https://.../api/cleanup/metadata-health"
    """
    from services.metadata_consistency import get_metadata_consistency_checker

    try:
        checker = get_metadata_consistency_checker()
        result = checker.run()

        status_code = 200  # Always 200, health status in body

        return func.HttpResponse(
            json.dumps(result, indent=2, default=str),
            status_code=status_code,
            mimetype="application/json"
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e), "success": False}),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(route="cleanup/status", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get current cleanup (janitor) status and configuration.

    GET /api/cleanup/status

    Returns config, enabled status, and last 24h statistics.
    """
    from triggers.janitor import janitor_status_handler
    return janitor_status_handler(req)


@bp.route(route="cleanup/history", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def cleanup_history(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get recent cleanup (janitor) run history.

    GET /api/cleanup/history?hours=24&type=task_watchdog&limit=50

    Query Parameters:
        hours: How many hours of history (default: 24, max: 168)
        type: Filter by run type (optional)
        limit: Max records to return (default: 50, max: 200)
    """
    from triggers.janitor import janitor_history_handler
    return janitor_history_handler(req)
