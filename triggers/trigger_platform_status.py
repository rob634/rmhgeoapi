"""
Platform Request Status HTTP Trigger.

Query Platform request status by looking up CoreMachine job status using thin tracking pattern.

Endpoints:
    GET /api/platform/status/{request_id} - Single request with verbose option
    GET /api/platform/status - List all requests

REMOVED (19 DEC 2025):
    GET /api/platform/health - Use /api/health instead
    GET /api/platform/stats - Use /api/health instead
    GET /api/platform/failures - Use /api/dbadmin/jobs?status=failed instead

Exports:
    platform_request_status: HTTP trigger function for GET /api/platform/status/{request_id}
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
    Get status of a Platform request.

    GET /api/platform/status/{request_id}
        Returns Platform request with delegated CoreMachine job status.
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

        # Check if specific request_id provided
        request_id = req.route_params.get('request_id')
        verbose = req.params.get('verbose', 'false').lower() == 'true'

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
# REMOVED (19 DEC 2025): platform_health, platform_stats, platform_failures
# ============================================================================
# These endpoints were broken and redundant with /api/health:
#   - platform_health: Used non-existent config.storage_account_name attribute
#   - platform_stats: Decimal serialization bug, duplicated /api/health stats
#   - platform_failures: Referenced non-existent platform.api_requests table
#
# Use /api/health instead - it provides comprehensive system health checks.
# ============================================================================
