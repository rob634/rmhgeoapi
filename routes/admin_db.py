"""
Database Admin Blueprint - All dbadmin/* routes.

Consolidated DEV/QA endpoints for database administration.
These endpoints should be removed before UAT/Production deployment.

Routes (19 total):
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

    Debug (1):
        GET /api/dbadmin/debug/all

Created: 15 DEC 2025 (Blueprint refactor)
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


# ============================================================================
# DEBUG (1 route with inline code)
# ============================================================================

@bp.route(route="dbadmin/debug/all", methods=["GET"])
def debug_dump_all(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEBUG: Dump all jobs and tasks.
    GET /api/dbadmin/debug/all?limit=100
    """
    from infrastructure import RepositoryFactory, PostgreSQLRepository

    limit = int(req.params.get('limit', '100'))
    jobs = []
    tasks = []

    try:
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']

        if isinstance(job_repo, PostgreSQLRepository):
            with job_repo._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cursor:
                    # Get jobs
                    cursor.execute(f"""
                        SELECT job_id, job_type, status, stage, total_stages,
                               parameters, stage_results, result_data, error_details,
                               created_at, updated_at
                        FROM {job_repo.schema_name}.jobs
                        ORDER BY created_at DESC LIMIT %s
                    """, (limit,))

                    for row in cursor.fetchall():
                        jobs.append({
                            "job_id": row["job_id"],
                            "job_type": row["job_type"],
                            "status": row["status"],
                            "stage": row["stage"],
                            "total_stages": row["total_stages"],
                            "parameters": row["parameters"],
                            "stage_results": row["stage_results"],
                            "result_data": row["result_data"],
                            "error_details": row["error_details"],
                            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
                        })

                    # Get tasks
                    cursor.execute(f"""
                        SELECT task_id, parent_job_id, task_type, status, stage,
                               parameters, result_data, error_details, retry_count,
                               created_at, updated_at
                        FROM {job_repo.schema_name}.tasks
                        ORDER BY created_at DESC LIMIT %s
                    """, (limit,))

                    for row in cursor.fetchall():
                        tasks.append({
                            "task_id": row["task_id"],
                            "parent_job_id": row["parent_job_id"],
                            "task_type": row["task_type"],
                            "status": row["status"],
                            "stage": row["stage"],
                            "parameters": row["parameters"],
                            "result_data": row["result_data"],
                            "error_details": row["error_details"],
                            "retry_count": row["retry_count"],
                            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
                        })
        else:
            return func.HttpResponse(
                body=json.dumps({
                    "error": f"Repository type {type(job_repo).__name__} not supported",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=501,
                headers={'Content-Type': 'application/json'}
            )

        return func.HttpResponse(
            body=json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "jobs_count": len(jobs),
                "tasks_count": len(tasks),
                "jobs": jobs,
                "tasks": tasks
            }, default=str),
            status_code=200,
            headers={'Content-Type': 'application/json'}
        )

    except Exception as e:
        import traceback
        return func.HttpResponse(
            body=json.dumps({
                "error": f"Debug dump failed: {str(e)}",
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={'Content-Type': 'application/json'}
        )
