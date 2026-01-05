# ============================================================================
# SERVICE BUS ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for /api/servicebus/* routes
# PURPOSE: DEV endpoints for Service Bus administration (remove before PROD)
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
Service Bus Admin Blueprint - All servicebus/* routes.

DEV endpoints for Service Bus administration.
These endpoints should be removed before UAT/Production deployment.

Routes (2 consolidated):
    GET /api/servicebus?type={queues|health}
    GET|POST /api/servicebus/queue/{queue_name}?type={details|peek|deadletter|nuke}

Created: 15 DEC 2025 (Blueprint refactor)
"""

import azure.functions as func
from azure.functions import Blueprint

bp = Blueprint()


# ============================================================================
# SERVICE BUS GLOBAL OPERATIONS
# ============================================================================

@bp.route(route="servicebus", methods=["GET"])
def servicebus_global(req: func.HttpRequest) -> func.HttpResponse:
    """Consolidated global ops: ?type={queues|health}"""
    from triggers.admin.servicebus import servicebus_admin_trigger
    return servicebus_admin_trigger.handle_global(req)


# ============================================================================
# SERVICE BUS QUEUE OPERATIONS
# ============================================================================

@bp.route(route="servicebus/queue/{queue_name}", methods=["GET", "POST"])
def servicebus_queue(req: func.HttpRequest) -> func.HttpResponse:
    """Consolidated queue ops: ?type={details|peek|deadletter|nuke}"""
    from triggers.admin.servicebus import servicebus_admin_trigger
    return servicebus_admin_trigger.handle_queue(req)
