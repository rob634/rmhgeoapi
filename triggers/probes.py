# ============================================================================
# KUBERNETES-STYLE HEALTH PROBES
# ============================================================================
# STATUS: Trigger - Diagnostic endpoints for startup validation
# PURPOSE: Provide livez/readyz endpoints that work even when startup fails
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: New file - part of STARTUP_REFORM.md implementation
# ============================================================================
"""
Kubernetes-Style Health Probes.

These endpoints have MINIMAL dependencies and are registered FIRST in
function_app.py to ensure they're always available for diagnostics,
even when startup validation fails.

Endpoints:
    GET /api/livez  - Liveness probe (always 200 if process alive)
    GET /api/readyz - Readiness probe (200 if ready, 503 if not)

Design Principles:
    1. ZERO dependencies on other project modules (except startup_state)
    2. Registered BEFORE any validation runs
    3. Never crash - always return a response
    4. Provide actionable error information

Usage in function_app.py:
    # At the VERY TOP, before any imports that might fail:
    from triggers.probes import bp as probes_bp
    app.register_functions(probes_bp)

See STARTUP_REFORM.md for full design documentation.

Exports:
    bp: Blueprint with livez/readyz routes
    get_probe_status(): Helper for health endpoint integration
"""

import json
import azure.functions as func
from azure.functions import Blueprint

# Import startup state - this module has zero dependencies
from startup_state import STARTUP_STATE

# Create Blueprint for probe endpoints
bp = Blueprint()


class LivezProbe:
    """
    Liveness Probe - Is the process alive?

    Always returns 200 if the Python process loaded successfully.
    Used by load balancers and orchestrators to detect crashed processes.

    This endpoint should NEVER fail. If it returns anything other than 200,
    the process should be restarted.
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/livez request."""
        return func.HttpResponse(
            json.dumps({
                "status": "alive",
                "probe": "livez",
                "message": "Process is running"
            }),
            status_code=200,
            mimetype="application/json"
        )


class ReadyzProbe:
    """
    Readiness Probe - Is the app ready to handle requests?

    Returns:
        200: All startup validations passed, app is ready for traffic
        503: Validation failed or still in progress, with error details

    This endpoint is used by load balancers to determine if the app
    should receive traffic. A 503 response means "don't send requests here".
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/readyz request."""

        # Check if validation is still in progress
        if not STARTUP_STATE.validation_complete:
            return func.HttpResponse(
                json.dumps({
                    "status": "initializing",
                    "probe": "readyz",
                    "message": "Startup validation in progress",
                    "startup_time": STARTUP_STATE.startup_time
                }),
                status_code=503,
                mimetype="application/json"
            )

        # Check if all validations passed
        if STARTUP_STATE.all_passed:
            return func.HttpResponse(
                json.dumps({
                    "status": "ready",
                    "probe": "readyz",
                    "message": "All startup validations passed",
                    "summary": STARTUP_STATE.get_summary()
                }),
                status_code=200,
                mimetype="application/json"
            )

        # Validation failed - return 503 with details
        failed_checks = STARTUP_STATE.get_failed_checks()

        # Build error response with actionable information
        errors = []
        for check in failed_checks:
            error_info = {
                "name": check.name,
                "error_type": check.error_type,
                "message": check.error_message
            }
            # Include fix suggestions if available
            if check.details and "likely_causes" in check.details:
                error_info["likely_causes"] = check.details["likely_causes"]
            if check.details and "fix" in check.details:
                error_info["fix"] = check.details["fix"]
            errors.append(error_info)

        return func.HttpResponse(
            json.dumps({
                "status": "not_ready",
                "probe": "readyz",
                "message": STARTUP_STATE.critical_error or "Startup validation failed",
                "summary": STARTUP_STATE.get_summary(),
                "errors": errors
            }, indent=2),
            status_code=503,
            mimetype="application/json"
        )


# Singleton instances
_livez_probe = LivezProbe()
_readyz_probe = ReadyzProbe()


# ============================================================================
# BLUEPRINT ROUTES
# ============================================================================
# These routes are registered via Blueprint pattern for consistency with
# other trigger modules (admin_db.py, admin_servicebus.py, h3_sources).
# ============================================================================

@bp.route(
    route="livez",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def livez(req: func.HttpRequest) -> func.HttpResponse:
    """
    Liveness probe - Is the process alive?

    Always returns 200 if the Python process loaded successfully.
    Used by load balancers to detect crashed processes.

    Returns:
        200: {"status": "alive", "probe": "livez"}
    """
    return _livez_probe.handle(req)


@bp.route(
    route="readyz",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def readyz(req: func.HttpRequest) -> func.HttpResponse:
    """
    Readiness probe - Is the app ready to handle requests?

    Returns 200 if all startup validations passed.
    Returns 503 if any validation failed (with error details).

    Returns:
        200: {"status": "ready", "probe": "readyz", ...}
        503: {"status": "not_ready", "probe": "readyz", "errors": [...]}
    """
    return _readyz_probe.handle(req)


def get_probe_status() -> dict:
    """
    Get current probe status for inclusion in other endpoints.

    Useful for including probe information in /api/health response.

    Returns:
        Dict with livez and readyz status
    """
    return {
        "livez": "alive",  # Always alive if this code runs
        "readyz": "ready" if STARTUP_STATE.all_passed else "not_ready",
        "validation_complete": STARTUP_STATE.validation_complete,
        "startup_time": STARTUP_STATE.startup_time
    }
