"""
Platform Request Status HTTP Trigger.

Query Platform request status by looking up CoreMachine job status using thin tracking pattern.

Exports:
    platform_request_status: HTTP trigger function for GET /api/platform/status/{request_id}
"""

import json
import logging
from typing import Dict, Any, Optional

import azure.functions as func

# Import infrastructure
from infrastructure import PlatformRepository, JobRepository

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
