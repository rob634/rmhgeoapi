# ============================================================================
# PLATFORM STATUS HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - Platform status and diagnostic endpoints
# PURPOSE: Query Platform request/job status and diagnostics for gateway integration
# LAST_REVIEWED: 21 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: platform_request_status, platform_job_status, platform_health, platform_failures, platform_lineage, platform_validate
# DEPENDENCIES: infrastructure.PlatformRepository, infrastructure.JobRepository
# ============================================================================
"""
Platform Status and Diagnostic HTTP Triggers.

Query Platform request/job status and diagnostics. These endpoints are designed for
gateway integration where only /api/platform/* endpoints are exposed externally.

Status Endpoints:
    GET /api/platform/status/{id} - Consolidated status endpoint (21 JAN 2026)
        Accepts EITHER request_id OR job_id - auto-detects ID type
    GET /api/platform/status - List all platform requests
    GET /api/platform/jobs/{job_id}/status - DEPRECATED (use /status/{job_id})

Diagnostic Endpoints (F7.12 - 15 JAN 2026):
    GET /api/platform/health - Simplified system readiness check
    GET /api/platform/failures - Recent failures with sanitized errors
    GET /api/platform/lineage/{request_id} - Data lineage trace
    POST /api/platform/validate - Pre-flight validation before submission

Exports:
    platform_request_status: HTTP trigger for GET /api/platform/status/{id}
    platform_job_status: DEPRECATED - HTTP trigger for GET /api/platform/jobs/{job_id}/status
    platform_health: HTTP trigger for GET /api/platform/health
    platform_failures: HTTP trigger for GET /api/platform/failures
    platform_lineage: HTTP trigger for GET /api/platform/lineage/{request_id}
    platform_validate: HTTP trigger for POST /api/platform/validate
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import azure.functions as func

# Import infrastructure
from infrastructure import PlatformRepository, JobRepository, TaskRepository, PostgreSQLRepository, RepositoryFactory
from config import get_config

# Configure logging
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_platform_status")


# ============================================================================
# HTTP HANDLERS
# ============================================================================

async def platform_request_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a Platform request or job.

    GET /api/platform/status/{id}
        Returns Platform request with delegated CoreMachine job status.
        The {id} parameter can be EITHER:
        - A request_id (Platform request identifier)
        - A job_id (CoreMachine job identifier)
        The endpoint auto-detects which type of ID was provided.
        Query params:
            - verbose=true: Include full task details (default: false)

    GET /api/platform/status
        Lists all Platform requests with optional filtering.

    Response for single request:
    {
        "success": true,
        "request_id": "a3f2c1b8...",
        "dataset_id": "aerial-2024",
        "resource_id": "site-alpha",
        "version_id": "v1.0",
        "job_id": "abc123...",
        "job_status": "completed",
        "job_stage": 3,
        "job_result": {...},
        "task_summary": {
            "total": 5,
            "completed": 4,
            "failed": 0,
            "processing": 1,
            "pending": 0,
            "by_stage": {
                "1": {"total": 3, "completed": 3},
                "2": {"total": 2, "completed": 1, "processing": 1}
            }
        },
        "data_type": "raster",
        "created_at": "2025-11-22T10:00:00Z"
    }
    """
    logger.info("Platform status endpoint called")

    try:
        platform_repo = PlatformRepository()
        job_repo = JobRepository()
        task_repo = TaskRepository()

        # Check if specific ID provided (can be request_id OR job_id)
        lookup_id = req.route_params.get('request_id')
        verbose = req.params.get('verbose', 'false').lower() == 'true'

        if lookup_id:
            # ================================================================
            # Single request lookup with auto-detect ID type (21 JAN 2026)
            # First try as request_id, then as job_id
            # ================================================================
            platform_request = platform_repo.get_request(lookup_id)
            lookup_type = "request_id"

            if not platform_request:
                # Try as job_id (reverse lookup)
                platform_request = platform_repo.get_request_by_job(lookup_id)
                lookup_type = "job_id"

            if not platform_request:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"No Platform request found for ID: {lookup_id}",
                        "hint": "ID can be either a request_id or job_id"
                    }),
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )

            logger.debug(f"Found platform request via {lookup_type}: {platform_request.request_id}")

            # Get CoreMachine job status (delegation)
            job = job_repo.get_job(platform_request.job_id)

            if job:
                job_status = job.status.value if hasattr(job.status, 'value') else job.status
                job_stage = job.stage
                job_result = job.result_data
                job_type = job.job_type
            else:
                job_status = "unknown"
                job_stage = None
                job_result = None
                job_type = None
                logger.warning(f"CoreMachine job {platform_request.job_id} not found")

            # Get task summary (09 DEC 2025)
            task_summary = _get_task_summary(task_repo, platform_request.job_id, verbose=verbose)

            # Build response
            result = {
                "success": True,
                # Platform identifiers
                "request_id": platform_request.request_id,
                "dataset_id": platform_request.dataset_id,
                "resource_id": platform_request.resource_id,
                "version_id": platform_request.version_id,
                "data_type": platform_request.data_type,
                "created_at": platform_request.created_at.isoformat() if platform_request.created_at else None,

                # CoreMachine job status (delegated)
                "job_id": platform_request.job_id,
                "job_type": job_type,
                "job_status": job_status,
                "job_stage": job_stage,
                "job_result": job_result,

                # Task summary (09 DEC 2025)
                "task_summary": task_summary,

                # Helpful URLs
                "urls": {
                    "job_status": f"/api/jobs/status/{platform_request.job_id}",
                    "job_tasks": f"/api/dbadmin/tasks/{platform_request.job_id}"
                }
            }

            # Add data access URLs if job completed
            if job_status == "completed" and job_result:
                result["data_access"] = _generate_data_access_urls(
                    platform_request,
                    job_type,
                    job_result
                )

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        else:
            # ================================================================
            # List all requests
            # ================================================================
            limit = int(req.params.get('limit', 100))
            dataset_id = req.params.get('dataset_id')

            requests = platform_repo.get_all_requests(limit=limit, dataset_id=dataset_id)

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "count": len(requests),
                    "requests": requests
                }, indent=2),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

    except Exception as e:
        logger.error(f"Platform status query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


# ============================================================================
# DIRECT JOB STATUS (14 JAN 2026)
# ============================================================================
# DEPRECATED: Use /api/platform/status/{job_id} instead (21 JAN 2026)
# This endpoint is maintained for backward compatibility but will be removed.
# The consolidated /api/platform/status/{id} endpoint accepts either request_id
# or job_id and returns the full Platform response with DDH identifiers.
# ============================================================================

async def platform_job_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    DEPRECATED: Get status of a CoreMachine job directly by job_id.

    ⚠️ DEPRECATED (21 JAN 2026): Use GET /api/platform/status/{job_id} instead.
    The consolidated endpoint accepts either request_id or job_id and returns
    the full Platform response with DDH identifiers.

    GET /api/platform/jobs/{job_id}/status
        Returns job status with task summary - same format as /api/jobs/status/{job_id}.
        Query params:
            - verbose=true: Include full task details (default: false)

    Response:
    {
        "jobId": "abc123...",
        "jobType": "process_raster_v2",
        "status": "completed",
        "stage": 3,
        "totalStages": 3,
        "parameters": {...},
        "stageResults": {...},
        "createdAt": "2025-01-14T10:00:00Z",
        "updatedAt": "2025-01-14T10:05:00Z",
        "resultData": {...},
        "taskSummary": {
            "total": 5,
            "completed": 5,
            "failed": 0,
            "byStage": {...}
        },
        "_deprecated": "Use /api/platform/status/{job_id} instead"
    }
    """
    # Log deprecation warning
    logger.warning("DEPRECATED: /api/platform/jobs/{job_id}/status called - use /api/platform/status/{id} instead")

    try:
        job_repo = JobRepository()
        task_repo = TaskRepository()

        # Extract job_id from route
        job_id = req.route_params.get('job_id')
        verbose = req.params.get('verbose', 'false').lower() == 'true'

        if not job_id:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": "job_id is required"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        logger.debug(f"🔍 Retrieving job status for: {job_id}")

        # Retrieve job record
        job_record = job_repo.get_job(job_id)

        if not job_record:
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Job not found: {job_id}"
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        logger.debug(f"📋 Job found: {job_id[:16]}... status={job_record.status}")

        # Format job response (camelCase for API compatibility)
        response_data = _format_job_response(job_record)

        # Add task summary
        task_summary = _get_task_summary(task_repo, job_id, verbose=verbose)
        response_data["taskSummary"] = task_summary

        # Add deprecation notice to response (21 JAN 2026)
        response_data["_deprecated"] = "Use /api/platform/status/{job_id} instead"
        response_data["_migration_url"] = f"/api/platform/status/{job_id}"

        return func.HttpResponse(
            json.dumps(response_data, indent=2, default=str),
            status_code=200,
            headers={
                "Content-Type": "application/json",
                "Deprecation": "true",
                "Sunset": "2026-04-01",
                "Link": f'</api/platform/status/{job_id}>; rel="successor-version"'
            }
        )

    except Exception as e:
        logger.error(f"Platform job status query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def _format_job_response(job_record) -> Dict[str, Any]:
    """
    Format job record for API response.

    Converts internal snake_case fields to camelCase for JavaScript compatibility.
    Matches the format of /api/jobs/status/{job_id} for consistency.

    Args:
        job_record: JobRecord from repository

    Returns:
        API response dictionary with camelCase fields
    """
    # Basic job information (camelCase for API compatibility)
    response = {
        "jobId": job_record.job_id,
        "jobType": job_record.job_type,
        "status": job_record.status.value if hasattr(job_record.status, 'value') else str(job_record.status),
        "stage": job_record.stage,
        "totalStages": job_record.total_stages,
        "parameters": job_record.parameters,
        "stageResults": job_record.stage_results,
        "createdAt": job_record.created_at.isoformat() if job_record.created_at else None,
        "updatedAt": job_record.updated_at.isoformat() if job_record.updated_at else None
    }

    # Optional fields
    if job_record.result_data:
        response["resultData"] = job_record.result_data

    if job_record.error_details:
        response["errorDetails"] = job_record.error_details

    return response


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_task_summary(
    task_repo: 'TaskRepository',
    job_id: str,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Get task summary for a job (09 DEC 2025).

    Args:
        task_repo: TaskRepository instance
        job_id: Job identifier
        verbose: If True, include full task details

    Returns:
        Dictionary with task counts and optional task details:
        {
            "total": 5,
            "completed": 4,
            "failed": 0,
            "processing": 1,
            "pending": 0,
            "queued": 0,
            "by_stage": {
                "1": {"total": 3, "completed": 3, "task_types": ["handler_raster_validate"]},
                "2": {"total": 2, "completed": 1, "processing": 1, "task_types": ["handler_raster_create_cog"]}
            },
            "tasks": [...]  # Only if verbose=True
        }
    """
    try:
        tasks = task_repo.get_tasks_for_job(job_id)

        if not tasks:
            return {
                "total": 0,
                "completed": 0,
                "failed": 0,
                "processing": 0,
                "pending": 0,
                "queued": 0,
                "by_stage": {}
            }

        # Count by status
        status_counts = {
            "total": len(tasks),
            "completed": 0,
            "failed": 0,
            "processing": 0,
            "pending": 0,
            "queued": 0
        }

        # Group by stage
        by_stage = {}

        for task in tasks:
            # Get status string
            status = task.status.value if hasattr(task.status, 'value') else str(task.status)

            # Update overall counts
            if status == "completed":
                status_counts["completed"] += 1
            elif status == "failed":
                status_counts["failed"] += 1
            elif status == "processing":
                status_counts["processing"] += 1
            elif status == "pending":
                status_counts["pending"] += 1
            elif status == "queued":
                status_counts["queued"] += 1

            # Update stage counts
            stage_key = str(task.stage)
            if stage_key not in by_stage:
                by_stage[stage_key] = {
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "processing": 0,
                    "pending": 0,
                    "queued": 0,
                    "task_types": set()
                }

            by_stage[stage_key]["total"] += 1
            by_stage[stage_key]["task_types"].add(task.task_type)

            if status == "completed":
                by_stage[stage_key]["completed"] += 1
            elif status == "failed":
                by_stage[stage_key]["failed"] += 1
            elif status == "processing":
                by_stage[stage_key]["processing"] += 1
            elif status == "pending":
                by_stage[stage_key]["pending"] += 1
            elif status == "queued":
                by_stage[stage_key]["queued"] += 1

        # Convert task_types sets to lists and remove zero counts
        for stage_key in by_stage:
            by_stage[stage_key]["task_types"] = list(by_stage[stage_key]["task_types"])
            # Remove zero counts for cleaner output
            by_stage[stage_key] = {
                k: v for k, v in by_stage[stage_key].items()
                if v != 0 or k in ["total", "task_types"]
            }

        result = {
            **status_counts,
            "by_stage": by_stage
        }

        # Add verbose task details if requested
        if verbose:
            result["tasks"] = [
                {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "stage": task.stage,
                    "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                    "error": task.result_data.get("error") if task.result_data else None
                }
                for task in tasks
            ]

        return result

    except Exception as e:
        logger.warning(f"Failed to get task summary for job {job_id}: {e}")
        return {
            "error": str(e),
            "total": 0
        }


def _generate_data_access_urls(
    platform_request,
    job_type: str,
    job_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate data access URLs for completed jobs.

    Uses config properties to build URLs for the correct services:
    - OGC Features: OGC_STAC_APP_URL (dedicated OGC/STAC app)
    - STAC API: OGC_STAC_APP_URL (dedicated OGC/STAC app)
    - TiTiler: TITILER_BASE_URL (dedicated tile server)
    - Vector Viewer: ETL_APP_URL (admin/ETL app)

    Args:
        platform_request: ApiRequest record
        job_type: Type of CoreMachine job
        job_result: Job result data

    Returns:
        Dictionary with OGC Features, STAC, TiTiler URLs as applicable
    """
    from config import get_config
    config = get_config()

    # Get service URLs from config (no hardcoded fallbacks - fail-fast design)
    # ogc_features_base_url = OGC_STAC_APP_URL + "/api/features"
    ogc_features_base = config.ogc_features_base_url

    # For STAC, we need the app base URL (without /api/stac suffix)
    # stac_api_base_url includes /api/stac, but STAC endpoints are at /api/collections
    # So we derive the base from ogc_features_base_url by stripping /api/features
    ogc_stac_app_base = ogc_features_base.replace("/api/features", "")

    # TiTiler and ETL app URLs
    titiler_base = config.titiler_base_url
    etl_app_base = config.etl_app_base_url

    urls = {}

    # Vector job → OGC Features URLs
    if job_type == 'process_vector':
        table_name = job_result.get('table_name')
        if table_name:
            urls['postgis'] = {
                'schema': 'geo',
                'table': table_name
            }
            urls['ogc_features'] = {
                'collection': f"{ogc_features_base}/collections/{table_name}",
                'items': f"{ogc_features_base}/collections/{table_name}/items",
                'viewer': f"{etl_app_base}/api/vector/viewer?collection={table_name}"
            }

    # Raster job → STAC + TiTiler URLs
    # Updated 04 DEC 2025: Added v2 job names (v1 jobs archived)
    elif job_type in ['process_raster_v2', 'process_large_raster_v2', 'process_raster_collection_v2']:
        collection_id = job_result.get('collection_id')
        cog_url = job_result.get('cog_url')

        if collection_id:
            urls['stac'] = {
                'collection': f"{ogc_stac_app_base}/api/collections/{collection_id}",
                'items': f"{ogc_stac_app_base}/api/collections/{collection_id}/items",
                'search': f"{ogc_stac_app_base}/api/search"
            }

        if cog_url:
            urls['titiler'] = {
                'preview': f"{titiler_base}/cog/preview?url={cog_url}",
                'info': f"{titiler_base}/cog/info?url={cog_url}",
                'tiles': f"{titiler_base}/cog/tiles/{{z}}/{{x}}/{{y}}?url={cog_url}"
            }

    return urls


# ============================================================================
# PLATFORM DIAGNOSTICS FOR EXTERNAL APPS (15 JAN 2026 - F7.12)
# ============================================================================
# These endpoints provide simplified, external-facing diagnostics for service
# layer apps that submit ETL jobs. They hide internal details and sanitize
# error messages for security.
# ============================================================================

async def platform_health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Simplified system readiness check for external apps (F7.12 S7.12.1).

    GET /api/platform/health

    Returns a simplified health status focused on whether the system is
    ready to accept jobs. Hides internal details (enum errors, storage
    account names, etc.) that are only relevant for internal debugging.

    Response:
    {
        "status": "healthy|degraded|unavailable",
        "ready_for_jobs": true,
        "summary": {
            "database": "healthy",
            "storage": "healthy",
            "service_bus": "healthy"
        },
        "jobs": {
            "queue_backlog": 5,
            "processing": 2,
            "failed_last_24h": 1,
            "avg_completion_minutes": 15.3
        },
        "timestamp": "2026-01-15T10:00:00Z"
    }
    """
    logger.info("Platform health endpoint called")

    try:
        config = get_config()
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']

        # Overall status
        status = "healthy"
        ready_for_jobs = True
        component_status = {}

        # Check database connectivity
        try:
            if isinstance(job_repo, PostgreSQLRepository):
                with job_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                component_status["database"] = "healthy"
        except Exception as db_err:
            logger.warning(f"Database health check failed: {db_err}")
            component_status["database"] = "unavailable"
            status = "degraded"
            ready_for_jobs = False

        # Check storage connectivity (simplified - just check config exists)
        try:
            if config.storage and config.storage.bronze_account:
                component_status["storage"] = "healthy"
            else:
                component_status["storage"] = "not_configured"
                status = "degraded"
        except Exception:
            component_status["storage"] = "unavailable"
            status = "degraded"

        # Check Service Bus (simplified)
        try:
            if config.queues and config.queues.service_bus_fqdn:
                component_status["service_bus"] = "healthy"
            else:
                component_status["service_bus"] = "not_configured"
        except Exception:
            component_status["service_bus"] = "unknown"

        # Get job statistics
        job_stats = {}
        try:
            if isinstance(job_repo, PostgreSQLRepository):
                with job_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Queue backlog (pending + queued jobs)
                        cur.execute(f"""
                            SELECT
                                COUNT(*) FILTER (WHERE status IN ('queued', 'pending')) as backlog,
                                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                                COUNT(*) FILTER (WHERE status = 'failed'
                                    AND updated_at >= NOW() - INTERVAL '24 hours') as failed_24h,
                                AVG(EXTRACT(EPOCH FROM (updated_at - created_at))/60)
                                    FILTER (WHERE status = 'completed'
                                    AND updated_at >= NOW() - INTERVAL '24 hours') as avg_minutes
                            FROM {config.app_schema}.jobs
                            WHERE created_at >= NOW() - INTERVAL '7 days'
                        """)
                        row = cur.fetchone()
                        job_stats = {
                            "queue_backlog": row['backlog'] or 0,
                            "processing": row['processing'] or 0,
                            "failed_last_24h": row['failed_24h'] or 0,
                            "avg_completion_minutes": round(float(row['avg_minutes']), 1) if row['avg_minutes'] else None
                        }

                        # If backlog is high, mark as degraded
                        if job_stats["queue_backlog"] > 50:
                            status = "degraded"

        except Exception as stats_err:
            logger.warning(f"Failed to get job stats: {stats_err}")
            job_stats = {"error": "unavailable"}

        result = {
            "status": status,
            "ready_for_jobs": ready_for_jobs,
            "summary": component_status,
            "jobs": job_stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform health check failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "status": "unavailable",
                "ready_for_jobs": False,
                "error": "Health check failed",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


async def platform_failures(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recent failures with sanitized error summaries (F7.12 S7.12.2).

    GET /api/platform/failures?hours=24&limit=20

    Returns recent job failures with sanitized error messages (no internal
    paths, secrets, or stack traces). Groups errors by pattern for quick
    diagnosis.

    Query Parameters:
        hours: Time window (default: 24)
        limit: Max recent failures to return (default: 20)

    Response:
    {
        "period_hours": 24,
        "total_failures": 5,
        "failure_rate": "3.2%",
        "common_patterns": [
            {"pattern": "File not found", "count": 3},
            {"pattern": "Invalid CRS", "count": 2}
        ],
        "recent_failures": [
            {
                "job_id": "abc123...",
                "job_type": "process_raster_v2",
                "failed_at": "2026-01-15T10:00:00Z",
                "error_category": "file_not_found",
                "error_summary": "Source file not accessible",
                "request_id": "req-456..."
            }
        ],
        "timestamp": "2026-01-15T10:00:00Z"
    }
    """
    logger.info("Platform failures endpoint called")

    try:
        hours = int(req.params.get('hours', '24'))
        limit = int(req.params.get('limit', '20'))

        config = get_config()
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']

        result = {
            "period_hours": hours,
            "total_failures": 0,
            "total_jobs": 0,
            "failure_rate": "0%",
            "common_patterns": [],
            "recent_failures": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        if not isinstance(job_repo, PostgreSQLRepository):
            return func.HttpResponse(
                json.dumps(result),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        with job_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Get overall stats
                cur.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed
                    FROM {config.app_schema}.jobs
                    WHERE created_at >= NOW() - INTERVAL '%s hours'
                """, (hours,))
                stats = cur.fetchone()
                total = stats['total'] or 0
                failed = stats['failed'] or 0

                result["total_jobs"] = total
                result["total_failures"] = failed
                result["failure_rate"] = f"{(failed/total*100):.1f}%" if total > 0 else "0%"

                # Get common error patterns (sanitized)
                cur.execute(f"""
                    SELECT
                        CASE
                            WHEN result_data->>'error' ILIKE '%%not found%%' THEN 'File or resource not found'
                            WHEN result_data->>'error' ILIKE '%%permission%%' THEN 'Permission denied'
                            WHEN result_data->>'error' ILIKE '%%timeout%%' THEN 'Operation timed out'
                            WHEN result_data->>'error' ILIKE '%%crs%%' OR result_data->>'error' ILIKE '%%projection%%' THEN 'Invalid CRS/projection'
                            WHEN result_data->>'error' ILIKE '%%memory%%' THEN 'Memory limit exceeded'
                            WHEN result_data->>'error' ILIKE '%%connection%%' THEN 'Connection error'
                            WHEN result_data->>'error' ILIKE '%%invalid%%' THEN 'Invalid input data'
                            ELSE 'Other error'
                        END as pattern,
                        COUNT(*) as count
                    FROM {config.app_schema}.jobs
                    WHERE status = 'failed'
                      AND created_at >= NOW() - INTERVAL '%s hours'
                      AND result_data->>'error' IS NOT NULL
                    GROUP BY pattern
                    ORDER BY count DESC
                    LIMIT 10
                """, (hours,))
                patterns = cur.fetchall()
                result["common_patterns"] = [
                    {"pattern": row['pattern'], "count": row['count']}
                    for row in patterns
                ]

                # Get recent failures with sanitized details
                cur.execute(f"""
                    SELECT
                        j.id as job_id,
                        j.job_type,
                        j.updated_at as failed_at,
                        j.result_data->>'error' as raw_error,
                        j.parameters->>'container_name' as container,
                        j.parameters->>'blob_name' as blob,
                        p.request_id
                    FROM {config.app_schema}.jobs j
                    LEFT JOIN {config.app_schema}.api_requests p ON j.id = p.job_id
                    WHERE j.status = 'failed'
                      AND j.created_at >= NOW() - INTERVAL '%s hours'
                    ORDER BY j.updated_at DESC
                    LIMIT %s
                """, (hours, limit))
                failures = cur.fetchall()

                for row in failures:
                    # Sanitize error message
                    raw_error = row['raw_error'] or "Unknown error"
                    error_summary, error_category = _sanitize_error(raw_error)

                    result["recent_failures"].append({
                        "job_id": row['job_id'],
                        "job_type": row['job_type'],
                        "failed_at": row['failed_at'].isoformat() if row['failed_at'] else None,
                        "error_category": error_category,
                        "error_summary": error_summary,
                        "request_id": row['request_id'],
                        "source": f"{row['container']}/{row['blob']}" if row['container'] and row['blob'] else None
                    })

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform failures query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Failed to retrieve failure data",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def _sanitize_error(raw_error: str) -> tuple:
    """
    Sanitize error message for external consumption.

    Removes internal paths, stack traces, and sensitive information.
    Returns (sanitized_message, category).
    """
    error_lower = raw_error.lower()

    # Categorize and sanitize
    if 'not found' in error_lower or 'does not exist' in error_lower:
        return "Source file or resource not found", "file_not_found"
    elif 'permission' in error_lower or 'access denied' in error_lower:
        return "Permission denied accessing resource", "permission_denied"
    elif 'timeout' in error_lower:
        return "Operation timed out", "timeout"
    elif 'crs' in error_lower or 'projection' in error_lower or 'srid' in error_lower:
        return "Invalid or unsupported coordinate reference system", "invalid_crs"
    elif 'memory' in error_lower or 'oom' in error_lower:
        return "File too large - memory limit exceeded", "memory_exceeded"
    elif 'connection' in error_lower or 'network' in error_lower:
        return "Connection error - please retry", "connection_error"
    elif 'invalid' in error_lower or 'corrupt' in error_lower:
        return "Invalid or corrupted input data", "invalid_input"
    elif 'format' in error_lower:
        return "Unsupported file format", "unsupported_format"
    else:
        # Generic sanitization - truncate and remove paths
        sanitized = raw_error[:100]
        # Remove anything that looks like a path
        import re
        sanitized = re.sub(r'/[a-zA-Z0-9_/\-\.]+', '[path]', sanitized)
        sanitized = re.sub(r'[A-Z]:\\[a-zA-Z0-9_\\\-\.]+', '[path]', sanitized)
        return sanitized, "other"


async def platform_lineage(req: func.HttpRequest) -> func.HttpResponse:
    """
    Data lineage trace by Platform request ID (F7.12 S7.12.3).

    GET /api/platform/lineage/{request_id}

    Returns the complete data lineage for a Platform request:
    source file → processing stages → output locations.

    Response:
    {
        "request_id": "req-123...",
        "job_id": "job-456...",
        "data_type": "raster",
        "status": "completed",
        "source": {
            "container": "bronze-rasters",
            "blob": "imagery.tif",
            "file_size_mb": 250
        },
        "processing": {
            "job_type": "process_raster_v2",
            "stages_completed": 3,
            "total_stages": 3,
            "duration_minutes": 15.5
        },
        "outputs": {
            "cog_url": "https://...",
            "stac_collection": "...",
            "stac_item": "..."
        },
        "data_access": {
            "stac": {...},
            "titiler": {...}
        },
        "timestamp": "2026-01-15T10:00:00Z"
    }
    """
    logger.info("Platform lineage endpoint called")

    try:
        request_id = req.route_params.get('request_id')

        if not request_id:
            return func.HttpResponse(
                json.dumps({
                    "error": "request_id is required",
                    "usage": "GET /api/platform/lineage/{request_id}"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        platform_repo = PlatformRepository()
        job_repo = JobRepository()

        # Get Platform request
        platform_request = platform_repo.get_request(request_id)

        if not platform_request:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Platform request {request_id} not found",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        # Get job details
        job = job_repo.get_job(platform_request.job_id)

        if not job:
            return func.HttpResponse(
                json.dumps({
                    "request_id": request_id,
                    "job_id": platform_request.job_id,
                    "error": "Associated job not found",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=404,
                headers={"Content-Type": "application/json"}
            )

        job_status = job.status.value if hasattr(job.status, 'value') else str(job.status)
        params = job.parameters or {}
        result_data = job.result_data or {}

        # Build source info
        source = {}
        if params.get('container_name'):
            source['container'] = params['container_name']
        if params.get('blob_name'):
            source['blob'] = params['blob_name']
        if result_data.get('file_size_mb'):
            source['file_size_mb'] = result_data['file_size_mb']

        # Build processing info
        duration_minutes = None
        if job.created_at and job.updated_at:
            duration_seconds = (job.updated_at - job.created_at).total_seconds()
            duration_minutes = round(duration_seconds / 60, 1)

        processing = {
            "job_type": job.job_type,
            "stages_completed": job.stage,
            "total_stages": result_data.get('total_stages') or job.stage,
            "duration_minutes": duration_minutes
        }

        # Build outputs info
        outputs = {}
        if result_data.get('cog_url'):
            outputs['cog_url'] = result_data['cog_url']
        if result_data.get('collection_id'):
            outputs['stac_collection'] = result_data['collection_id']
        if result_data.get('stac_item_id'):
            outputs['stac_item'] = result_data['stac_item_id']
        if result_data.get('table_name'):
            outputs['table_name'] = result_data['table_name']
            outputs['schema'] = 'geo'

        # Generate data access URLs
        data_access = {}
        if job_status == "completed":
            data_access = _generate_data_access_urls(platform_request, job.job_type, result_data)

        lineage = {
            "request_id": request_id,
            "job_id": platform_request.job_id,
            "data_type": platform_request.data_type,
            "status": job_status,
            "source": source if source else None,
            "processing": processing,
            "outputs": outputs if outputs else None,
            "data_access": data_access if data_access else None,
            "created_at": platform_request.created_at.isoformat() if platform_request.created_at else None,
            "completed_at": job.updated_at.isoformat() if job_status == "completed" and job.updated_at else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(lineage, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform lineage query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Failed to retrieve lineage data",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


async def platform_validate(req: func.HttpRequest) -> func.HttpResponse:
    """
    Pre-flight validation before job submission (F7.12 S7.12.4).

    POST /api/platform/validate

    Validates a file before submitting an ETL job. Checks if the file
    exists, is readable, and returns recommended job type and estimated
    processing time.

    Request Body:
    {
        "data_type": "raster",  // or "vector"
        "container_name": "bronze-rasters",
        "blob_name": "imagery.tif"
    }

    Response:
    {
        "valid": true,
        "file_exists": true,
        "file_size_mb": 250.5,
        "recommended_job_type": "process_raster_v2",
        "processing_mode": "function",  // or "docker"
        "estimated_minutes": 15,
        "warnings": [],
        "timestamp": "2026-01-15T10:00:00Z"
    }
    """
    logger.info("Platform validate endpoint called")

    try:
        # Parse request body
        try:
            body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({
                    "error": "Invalid JSON body",
                    "usage": {
                        "data_type": "raster or vector",
                        "container_name": "container name",
                        "blob_name": "blob path"
                    }
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        data_type = body.get('data_type')
        container_name = body.get('container_name')
        blob_name = body.get('blob_name')

        # Validate required fields
        if not all([data_type, container_name, blob_name]):
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required fields: data_type, container_name, blob_name",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        if data_type not in ['raster', 'vector']:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Invalid data_type: {data_type}. Must be 'raster' or 'vector'",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        config = get_config()
        warnings = []

        # Check if file exists and get size
        file_exists = False
        file_size_mb = None

        try:
            from azure.storage.blob import BlobServiceClient
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            account_url = f"https://{config.storage.bronze_account}.blob.core.windows.net"
            blob_service = BlobServiceClient(account_url=account_url, credential=credential)

            container_client = blob_service.get_container_client(container_name)
            blob_client = container_client.get_blob_client(blob_name)

            props = blob_client.get_blob_properties()
            file_exists = True
            file_size_mb = round(props.size / (1024 * 1024), 2)

        except Exception as blob_err:
            error_str = str(blob_err).lower()
            if 'not found' in error_str or 'does not exist' in error_str:
                file_exists = False
            else:
                warnings.append(f"Could not verify file: {type(blob_err).__name__}")
                logger.warning(f"Blob validation error: {blob_err}")

        # Determine recommended job type and processing mode
        recommended_job_type = None
        processing_mode = None
        estimated_minutes = None

        if data_type == 'raster':
            # ================================================================
            # V0.8 ARCHITECTURE (24 JAN 2026)
            # ================================================================
            # - ALL raster operations go to Docker worker (container-tasks queue)
            # - Single job: process_raster_docker handles both single COG and tiled output
            # - ETL mount is EXPECTED in production (False = degraded state)
            # - Tiling decision based on raster_tiling_threshold_mb
            # ================================================================
            import math
            raster_config = config.raster
            mount_enabled = raster_config.use_etl_mount
            tiling_threshold_mb = raster_config.raster_tiling_threshold_mb
            tile_target_mb = raster_config.raster_tile_target_mb

            # All raster goes to Docker
            processing_mode = "docker"
            recommended_job_type = "process_raster_docker"

            # Determine output mode (single COG vs tiled)
            output_mode = "single_cog"
            estimated_tiles = 1

            if file_size_mb is not None:
                if file_size_mb > tiling_threshold_mb:
                    output_mode = "tiled"
                    estimated_tiles = math.ceil(file_size_mb / tile_target_mb)
                    warnings.append(f"Large file ({file_size_mb:.1f}MB) - will produce ~{estimated_tiles} tiles")

                # Estimate processing time (rough: ~50MB/min for Docker)
                estimated_minutes = max(2, int(file_size_mb / 50) + 2)
            else:
                warnings.append("Could not determine file size")

            # V0.8: Mount is expected - warn if disabled
            if not mount_enabled:
                warnings.append("WARNING: ETL mount disabled - system in degraded state")

        elif data_type == 'vector':
            recommended_job_type = "process_vector"
            processing_mode = "function"
            if file_size_mb:
                estimated_minutes = max(2, int(file_size_mb / 50) + 1)
            else:
                estimated_minutes = 5

        # V0.8: Include raster-specific output mode info
        result = {
            "valid": file_exists and recommended_job_type is not None,
            "file_exists": file_exists,
            "file_size_mb": file_size_mb,
            "data_type": data_type,
            "recommended_job_type": recommended_job_type,
            "processing_mode": processing_mode,
            "estimated_minutes": estimated_minutes,
            "warnings": warnings if warnings else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Add raster-specific V0.8 fields
        if data_type == 'raster':
            result["etl_mount_enabled"] = config.raster.use_etl_mount
            result["output_mode"] = output_mode if 'output_mode' in dir() else "single_cog"
            result["estimated_tiles"] = estimated_tiles if 'estimated_tiles' in dir() else 1
            result["tiling_threshold_mb"] = config.raster.raster_tiling_threshold_mb

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform validate failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Validation failed",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )
