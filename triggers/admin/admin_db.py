# ============================================================================
# DATABASE ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for /api/dbadmin/* routes
# PURPOSE: DEV/QA database administration endpoints (remove before PROD)
# LAST_REVIEWED: 12 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
Database Admin Blueprint - All dbadmin/* routes.

Consolidated DEV/QA endpoints for database administration.
These endpoints should be removed before UAT/Production deployment.

Routes (18 total):
    Schema Operations (3):
        GET /api/dbadmin/schemas
        GET /api/dbadmin/schemas/{schema_name}
        GET /api/dbadmin/schemas/{schema_name}/tables

    Table Operations (1 consolidated):
        GET /api/dbadmin/tables/{table_identifier}?type={details|sample|columns|indexes}

    Query Activity (1 consolidated):
        GET /api/dbadmin/activity?type={running|slow|locks|connections}

    Health (2):
        GET /api/dbadmin/health
        GET /api/dbadmin/health/performance

    Maintenance (1 consolidated):
        POST /api/dbadmin/maintenance?action={nuke|redeploy|cleanup|full-rebuild|check-prerequisites}

    Geo Schema (1 consolidated):
        GET|POST /api/dbadmin/geo?type={tables|metadata|orphans} or ?action=unpublish

    Data Queries (8):
        GET /api/dbadmin/jobs
        GET /api/dbadmin/jobs/{job_id}
        GET /api/dbadmin/tasks
        GET /api/dbadmin/tasks/{job_id}
        GET /api/dbadmin/platform/requests
        GET /api/dbadmin/platform/requests/{request_id}
        GET /api/dbadmin/platform/orchestration
        GET /api/dbadmin/platform/orchestration/{request_id}

    Diagnostics (1 consolidated):
        GET /api/dbadmin/diagnostics?type={stats|enums|functions|all|config|errors|lineage}

Created: 15 DEC 2025 (Blueprint refactor)
Updated: 12 JAN 2026 (Removed redundant debug/all endpoint)
"""

import azure.functions as func
from azure.functions import Blueprint
import json
from datetime import datetime, timezone

bp = Blueprint()


# ============================================================================
# SCHEMA OPERATIONS (3 routes)
# ============================================================================

@bp.route(route="dbadmin/schemas", methods=["GET"])
def db_schemas_list(req: func.HttpRequest) -> func.HttpResponse:
    """List all schemas: GET /api/dbadmin/schemas"""
    from triggers.admin.db_schemas import admin_db_schemas_trigger
    return admin_db_schemas_trigger.handle_request(req)


@bp.route(route="dbadmin/schemas/{schema_name}", methods=["GET"])
def db_schema_details(req: func.HttpRequest) -> func.HttpResponse:
    """Schema details: GET /api/dbadmin/schemas/{schema_name}"""
    from triggers.admin.db_schemas import admin_db_schemas_trigger
    return admin_db_schemas_trigger.handle_request(req)


@bp.route(route="dbadmin/schemas/{schema_name}/tables", methods=["GET"])
def db_schema_tables(req: func.HttpRequest) -> func.HttpResponse:
    """Schema tables: GET /api/dbadmin/schemas/{schema_name}/tables"""
    from triggers.admin.db_schemas import admin_db_schemas_trigger
    return admin_db_schemas_trigger.handle_request(req)


# ============================================================================
# TABLE OPERATIONS (1 consolidated route)
# ============================================================================

@bp.route(route="dbadmin/tables/{table_identifier}", methods=["GET"])
def db_tables(req: func.HttpRequest) -> func.HttpResponse:
    """Consolidated table ops: ?type={details|sample|columns|indexes}"""
    from triggers.admin.db_tables import admin_db_tables_trigger
    return admin_db_tables_trigger.handle_tables(req)


# ============================================================================
# QUERY ACTIVITY (1 consolidated route)
# ============================================================================

@bp.route(route="dbadmin/activity", methods=["GET"])
def db_activity(req: func.HttpRequest) -> func.HttpResponse:
    """Consolidated DB activity: ?type={running|slow|locks|connections}"""
    from triggers.admin.db_queries import admin_db_queries_trigger
    return admin_db_queries_trigger.handle_activity(req)


# ============================================================================
# HEALTH (2 routes)
# ============================================================================

@bp.route(route="dbadmin/health", methods=["GET"])
def db_health(req: func.HttpRequest) -> func.HttpResponse:
    """Database health: GET /api/dbadmin/health"""
    from triggers.admin.db_health import admin_db_health_trigger
    return admin_db_health_trigger.handle_request(req)


@bp.route(route="dbadmin/health/performance", methods=["GET"])
def db_health_performance(req: func.HttpRequest) -> func.HttpResponse:
    """Performance metrics: GET /api/dbadmin/health/performance"""
    from triggers.admin.db_health import admin_db_health_trigger
    return admin_db_health_trigger.handle_request(req)


# ============================================================================
# MAINTENANCE (1 consolidated route)
# ============================================================================

@bp.route(route="dbadmin/maintenance", methods=["POST", "GET"])
def admin_maintenance(req: func.HttpRequest) -> func.HttpResponse:
    """
    Consolidated maintenance endpoint.

    POST /api/dbadmin/maintenance?action={nuke|redeploy|cleanup|full-rebuild|check-prerequisites}&target={app|pgstac}&confirm=yes
    """
    from triggers.admin.db_maintenance import admin_db_maintenance_trigger
    return admin_db_maintenance_trigger.handle_maintenance(req)


# ============================================================================
# GEO SCHEMA (1 consolidated route)
# ============================================================================

@bp.route(route="dbadmin/geo", methods=["GET", "POST"])
def dbadmin_geo(req: func.HttpRequest) -> func.HttpResponse:
    """Consolidated geo ops: ?type={tables|metadata|orphans} or ?action=unpublish"""
    from triggers.admin.db_maintenance import admin_db_maintenance_trigger
    return admin_db_maintenance_trigger.handle_geo(req)


# ============================================================================
# DATA QUERIES (8 routes)
# ============================================================================

@bp.route(route="dbadmin/jobs", methods=["GET"])
def admin_query_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query jobs: GET /api/dbadmin/jobs?limit=10&status=processing&hours=24"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/jobs/{job_id}", methods=["GET"])
def admin_query_job_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get job by ID: GET /api/dbadmin/jobs/{job_id}"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/tasks", methods=["GET"])
def admin_query_tasks(req: func.HttpRequest) -> func.HttpResponse:
    """Query tasks: GET /api/dbadmin/tasks?status=failed&limit=20"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/tasks/{job_id}", methods=["GET"])
def admin_query_tasks_for_job(req: func.HttpRequest) -> func.HttpResponse:
    """Tasks for job: GET /api/dbadmin/tasks/{job_id}"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/platform/requests", methods=["GET"])
def admin_query_api_requests(req: func.HttpRequest) -> func.HttpResponse:
    """Query API requests: GET /api/dbadmin/platform/requests?limit=10&status=processing"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/platform/requests/{request_id}", methods=["GET"])
def admin_query_api_request_by_id(req: func.HttpRequest) -> func.HttpResponse:
    """Get API request by ID: GET /api/dbadmin/platform/requests/{request_id}"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/platform/orchestration", methods=["GET"])
def admin_query_orchestration_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Query orchestration jobs: GET /api/dbadmin/platform/orchestration?request_id={id}"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


@bp.route(route="dbadmin/platform/orchestration/{request_id}", methods=["GET"])
def admin_query_orchestration_jobs_for_request(req: func.HttpRequest) -> func.HttpResponse:
    """Orchestration for request: GET /api/dbadmin/platform/orchestration/{request_id}"""
    from triggers.admin.db_data import admin_db_data_trigger
    return admin_db_data_trigger.handle_request(req)


# ============================================================================
# DIAGNOSTICS (1 consolidated route)
# ============================================================================

@bp.route(route="dbadmin/diagnostics", methods=["GET"])
def admin_diagnostics(req: func.HttpRequest) -> func.HttpResponse:
    """
    Consolidated diagnostics endpoint.

    GET /api/dbadmin/diagnostics?type={stats|enums|functions|all|config|errors|lineage}
    """
    from triggers.admin.db_diagnostics import admin_db_diagnostics_trigger
    return admin_db_diagnostics_trigger.handle_diagnostics(req)


# DEBUG endpoint removed 12 JAN 2026 - redundant with /api/dbadmin/jobs and /api/dbadmin/tasks
