"""
Platform Request Status HTTP Trigger.

Query Platform request status by looking up CoreMachine job status using thin tracking pattern.

Endpoints (07 DEC 2025 - Phase 5 additions):
    GET /api/platform/status/{request_id} - Single request with verbose option
    GET /api/platform/status - List all requests
    GET /api/platform/health - Simplified health for DDH consumption
    GET /api/platform/stats - Aggregated job statistics
    GET /api/platform/failures - Recent failures for troubleshooting

Exports:
    platform_request_status: HTTP trigger function for GET /api/platform/status/{request_id}
    platform_health: HTTP trigger function for GET /api/platform/health
    platform_stats: HTTP trigger function for GET /api/platform/stats
    platform_failures: HTTP trigger function for GET /api/platform/failures
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import azure.functions as func

# Import infrastructure
from infrastructure import PlatformRepository, JobRepository, PostgreSQLRepository, RepositoryFactory
from config import get_config

# Configure logging
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_platform_status")


# ============================================================================
# HTTP HANDLERS
# ============================================================================

async def platform_request_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a Platform request.

    GET /api/platform/status/{request_id}
        Returns Platform request with delegated CoreMachine job status.

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
        "data_type": "raster",
        "created_at": "2025-11-22T10:00:00Z"
    }
    """
    logger.info("Platform status endpoint called")

    try:
        platform_repo = PlatformRepository()
        job_repo = JobRepository()

        # Check if specific request_id provided
        request_id = req.route_params.get('request_id')

        if request_id:
            # ================================================================
            # Single request lookup with job status delegation
            # ================================================================
            platform_request = platform_repo.get_request(request_id)

            if not platform_request:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Platform request {request_id} not found"
                    }),
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )

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
                json.dumps(result, indent=2),
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
# HELPER FUNCTIONS
# ============================================================================

def _generate_data_access_urls(
    platform_request,
    job_type: str,
    job_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate data access URLs for completed jobs.

    Args:
        platform_request: ApiRequest record
        job_type: Type of CoreMachine job
        job_result: Job result data

    Returns:
        Dictionary with OGC Features, STAC, TiTiler URLs as applicable
    """
    try:
        from config import get_config
        config = get_config()
    except Exception:
        base_url = "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"
    else:
        base_url = getattr(config, 'function_app_url', None) or \
            "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

    web_map_url = "https://rmhazuregeo.z13.web.core.windows.net"
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
                'collection': f"{base_url}/api/features/collections/{table_name}",
                'items': f"{base_url}/api/features/collections/{table_name}/items",
                'web_map': f"{web_map_url}/?collection={table_name}"
            }

    # Raster job → STAC + TiTiler URLs
    # Updated 04 DEC 2025: Added v2 job names (v1 jobs archived)
    elif job_type in ['process_raster_v2', 'process_large_raster_v2', 'process_raster_collection_v2']:
        collection_id = job_result.get('collection_id')
        cog_url = job_result.get('cog_url')

        if collection_id:
            urls['stac'] = {
                'collection': f"{base_url}/api/collections/{collection_id}",
                'items': f"{base_url}/api/collections/{collection_id}/items",
                'search': f"{base_url}/api/search"
            }

        if cog_url:
            urls['titiler'] = {
                'preview': f"{base_url}/cog/preview?url={cog_url}",
                'info': f"{base_url}/cog/info?url={cog_url}",
                'tiles': f"{base_url}/cog/tiles/{{z}}/{{x}}/{{y}}?url={cog_url}"
            }

    return urls


# ============================================================================
# PLATFORM STATUS ENDPOINTS FOR DDH VISIBILITY (07 DEC 2025)
# ============================================================================

async def platform_health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Simplified health endpoint for DDH consumption (07 DEC 2025).

    GET /api/platform/health

    Returns high-level system health without internal implementation details.
    Designed for DDH team visibility into geospatial processing availability.

    Response:
    {
        "status": "healthy",
        "api_version": "v1.0",
        "components": {
            "job_processing": "healthy",
            "stac_catalog": "healthy",
            "storage": "healthy"
        },
        "recent_activity": {
            "jobs_last_24h": 45,
            "success_rate": "93.3%"
        },
        "timestamp": "2025-12-07T10:00:00Z"
    }
    """
    logger.info("Platform health endpoint called")

    try:
        config = get_config()
        repos = RepositoryFactory.create_repositories()
        db_repo = repos['job_repo']

        components = {}
        overall_status = "healthy"

        # Check job processing (database connectivity)
        try:
            with db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            components["job_processing"] = "healthy"
        except Exception as e:
            components["job_processing"] = "unhealthy"
            overall_status = "degraded"
            logger.warning(f"Job processing check failed: {e}")

        # Check STAC catalog (pgstac schema exists)
        try:
            with db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) as count
                        FROM pgstac.collections
                    """)
                    row = cursor.fetchone()
                    if row:
                        components["stac_catalog"] = "healthy"
                    else:
                        components["stac_catalog"] = "healthy"  # Empty is OK
        except Exception as e:
            components["stac_catalog"] = "unavailable"
            logger.warning(f"STAC catalog check failed: {e}")

        # Check storage (implicit via config)
        if config.storage_account_name:
            components["storage"] = "healthy"
        else:
            components["storage"] = "not_configured"
            overall_status = "degraded"

        # Get recent activity statistics
        recent_activity = {}
        try:
            with db_repo._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"""
                        SELECT
                            COUNT(*) as total,
                            COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                            COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
                        FROM {config.app_schema}.jobs
                        WHERE created_at >= NOW() - INTERVAL '24 hours'
                    """)
                    stats = cursor.fetchone()
                    total = stats['total'] or 0
                    completed = stats['completed'] or 0
                    failed = stats['failed'] or 0

                    recent_activity = {
                        "jobs_last_24h": total,
                        "completed": completed,
                        "failed": failed,
                        "success_rate": f"{(completed / total * 100):.1f}%" if total > 0 else "N/A"
                    }
        except Exception as e:
            logger.warning(f"Recent activity query failed: {e}")
            recent_activity = {"error": "Unable to retrieve statistics"}

        result = {
            "status": overall_status,
            "api_version": "v1.0",
            "components": components,
            "recent_activity": recent_activity,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        status_code = 200 if overall_status == "healthy" else 503

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=status_code,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform health check failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


async def platform_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Aggregated job statistics for DDH visibility (07 DEC 2025).

    GET /api/platform/stats?hours=24

    Returns job processing statistics without exposing internal job IDs.

    Response:
    {
        "period": "24h",
        "jobs": {
            "total": 45,
            "completed": 42,
            "failed": 3,
            "processing": 0
        },
        "by_data_type": {
            "raster": {"total": 30, "completed": 28, "failed": 2},
            "vector": {"total": 15, "completed": 14, "failed": 1}
        },
        "avg_processing_time_minutes": {
            "raster": 8.5,
            "vector": 2.3
        },
        "timestamp": "2025-12-07T10:00:00Z"
    }
    """
    logger.info("Platform stats endpoint called")

    try:
        hours = int(req.params.get('hours', '24'))
        config = get_config()
        repos = RepositoryFactory.create_repositories()
        db_repo = repos['job_repo']

        stats = {
            "period": f"{hours}h",
            "hours": hours
        }

        with db_repo._get_connection() as conn:
            with conn.cursor() as cursor:
                # Overall job counts
                cursor.execute(f"""
                    SELECT
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                        COUNT(CASE WHEN status = 'processing' THEN 1 END) as processing,
                        COUNT(CASE WHEN status = 'queued' THEN 1 END) as queued
                    FROM {config.app_schema}.jobs
                    WHERE created_at >= NOW() - INTERVAL '%s hours'
                """, (hours,))
                job_stats = cursor.fetchone()

                stats["jobs"] = {
                    "total": job_stats['total'] or 0,
                    "completed": job_stats['completed'] or 0,
                    "failed": job_stats['failed'] or 0,
                    "processing": job_stats['processing'] or 0,
                    "queued": job_stats['queued'] or 0
                }

                # Stats by data type (infer from job_type)
                cursor.execute(f"""
                    SELECT
                        CASE
                            WHEN job_type LIKE '%%raster%%' THEN 'raster'
                            WHEN job_type LIKE '%%vector%%' THEN 'vector'
                            WHEN job_type LIKE '%%fathom%%' THEN 'fathom'
                            WHEN job_type LIKE '%%h3%%' THEN 'h3'
                            ELSE 'other'
                        END as data_type,
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed
                    FROM {config.app_schema}.jobs
                    WHERE created_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY data_type
                    ORDER BY total DESC
                """, (hours,))
                type_rows = cursor.fetchall()

                stats["by_data_type"] = {}
                for row in type_rows:
                    stats["by_data_type"][row['data_type']] = {
                        "total": row['total'] or 0,
                        "completed": row['completed'] or 0,
                        "failed": row['failed'] or 0
                    }

                # Average processing time by data type (completed jobs only)
                cursor.execute(f"""
                    SELECT
                        CASE
                            WHEN job_type LIKE '%%raster%%' THEN 'raster'
                            WHEN job_type LIKE '%%vector%%' THEN 'vector'
                            WHEN job_type LIKE '%%fathom%%' THEN 'fathom'
                            WHEN job_type LIKE '%%h3%%' THEN 'h3'
                            ELSE 'other'
                        END as data_type,
                        AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 60) as avg_minutes
                    FROM {config.app_schema}.jobs
                    WHERE status = 'completed'
                      AND created_at >= NOW() - INTERVAL '%s hours'
                      AND updated_at IS NOT NULL
                    GROUP BY data_type
                """, (hours,))
                time_rows = cursor.fetchall()

                stats["avg_processing_time_minutes"] = {}
                for row in time_rows:
                    if row['avg_minutes'] is not None:
                        stats["avg_processing_time_minutes"][row['data_type']] = round(row['avg_minutes'], 1)

        stats["timestamp"] = datetime.now(timezone.utc).isoformat()

        return func.HttpResponse(
            json.dumps(stats, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform stats query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


async def platform_failures(req: func.HttpRequest) -> func.HttpResponse:
    """
    Recent failures for DDH troubleshooting (07 DEC 2025).

    GET /api/platform/failures?hours=24&limit=10

    Returns sanitized failure information (no internal paths or stack traces).

    Response:
    {
        "failures": [
            {
                "request_id": "def456...",
                "dataset_id": "parcels-2024",
                "failed_at": "2025-12-07T09:15:00Z",
                "error_category": "validation_failed",
                "error_summary": "Source file not found in bronze-vectors container",
                "can_retry": true
            }
        ],
        "total_failures": 3,
        "timestamp": "2025-12-07T10:00:00Z"
    }
    """
    logger.info("Platform failures endpoint called")

    try:
        hours = int(req.params.get('hours', '24'))
        limit = int(req.params.get('limit', '10'))
        config = get_config()

        platform_repo = PlatformRepository()
        repos = RepositoryFactory.create_repositories()
        db_repo = repos['job_repo']

        failures = []

        with db_repo._get_connection() as conn:
            with conn.cursor() as cursor:
                # Get failed Platform requests with job details
                cursor.execute(f"""
                    SELECT
                        ar.request_id,
                        ar.dataset_id,
                        ar.resource_id,
                        ar.version_id,
                        ar.data_type,
                        ar.job_id,
                        j.job_type,
                        j.updated_at as failed_at,
                        j.result_data->>'error' as error_message
                    FROM platform.api_requests ar
                    JOIN {config.app_schema}.jobs j ON ar.job_id = j.id
                    WHERE j.status = 'failed'
                      AND j.created_at >= NOW() - INTERVAL '%s hours'
                    ORDER BY j.updated_at DESC
                    LIMIT %s
                """, (hours, limit))
                rows = cursor.fetchall()

                for row in rows:
                    # Categorize and sanitize error
                    error_msg = row['error_message'] or "Unknown error"
                    error_category, sanitized_error, can_retry = _categorize_error(error_msg)

                    failures.append({
                        "request_id": row['request_id'],
                        "dataset_id": row['dataset_id'],
                        "resource_id": row['resource_id'],
                        "version_id": row['version_id'],
                        "data_type": row['data_type'],
                        "failed_at": row['failed_at'].isoformat() if row['failed_at'] else None,
                        "error_category": error_category,
                        "error_summary": sanitized_error,
                        "can_retry": can_retry
                    })

                # Get total failure count
                cursor.execute(f"""
                    SELECT COUNT(*) as count
                    FROM platform.api_requests ar
                    JOIN {config.app_schema}.jobs j ON ar.job_id = j.id
                    WHERE j.status = 'failed'
                      AND j.created_at >= NOW() - INTERVAL '%s hours'
                """, (hours,))
                total_row = cursor.fetchone()
                total_failures = total_row['count'] if total_row else 0

        result = {
            "failures": failures,
            "total_failures": total_failures,
            "period": f"{hours}h",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform failures query failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )


def _categorize_error(error_message: str) -> tuple:
    """
    Categorize and sanitize error message for DDH consumption (07 DEC 2025).

    Args:
        error_message: Raw error message from job result

    Returns:
        Tuple of (error_category, sanitized_message, can_retry)
    """
    error_lower = error_message.lower()

    # Truncate long messages
    sanitized = error_message[:200] + "..." if len(error_message) > 200 else error_message

    # Remove internal paths
    import re
    sanitized = re.sub(r'/[a-zA-Z0-9_/.-]+\.py', '[internal]', sanitized)
    sanitized = re.sub(r'line \d+', '', sanitized)

    # Categorize
    if 'not found' in error_lower or 'does not exist' in error_lower:
        return "resource_not_found", sanitized, True
    elif 'validation' in error_lower or 'invalid' in error_lower:
        return "validation_failed", sanitized, False
    elif 'already exists' in error_lower:
        return "duplicate_resource", sanitized, False
    elif 'timeout' in error_lower or 'timed out' in error_lower:
        return "timeout", sanitized, True
    elif 'connection' in error_lower or 'network' in error_lower:
        return "connection_error", sanitized, True
    elif 'permission' in error_lower or 'access denied' in error_lower or 'unauthorized' in error_lower:
        return "permission_error", sanitized, False
    elif 'memory' in error_lower or 'out of memory' in error_lower:
        return "resource_exhausted", sanitized, True
    else:
        return "processing_error", sanitized, True
