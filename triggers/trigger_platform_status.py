# ============================================================================
# CLAUDE CONTEXT - API REQUEST STATUS TRIGGER (PLATFORM LAYER)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: HTTP Trigger - API request status monitoring endpoint
# PURPOSE: Query status of API requests and their associated CoreMachine jobs
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: platform_request_status (HTTP trigger function)
# INTERFACES: None
# PYDANTIC_MODELS: PlatformRequestStatus (enum)
# DEPENDENCIES: azure-functions, psycopg
# SOURCE: Database queries (app.api_requests, app.orchestration_jobs)
# SCOPE: Platform request monitoring
# VALIDATION: None
# PATTERNS: Repository
# ENTRY_POINTS: GET /api/platform/status/{request_id}
# INDEX:
#   - Imports: Line 20
#   - Repository Extension: Line 40
#   - HTTP Handler: Line 150
# ============================================================================

"""
Platform Request Status HTTP Trigger

Provides monitoring endpoints for platform requests.
Shows the status of the request and all associated CoreMachine jobs.
"""

import json
import logging
from typing import Dict, Any, Optional, List

import azure.functions as func

# Import Platform models from core (Infrastructure-as-Code pattern)
from core.models import PlatformRequestStatus
from infrastructure import PlatformStatusRepository

# Configure logging using LoggerFactory (Application Insights integration)
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "trigger_platform_status")

# ============================================================================
# REPOSITORY MOVED TO infrastructure/platform.py (29 OCT 2025)
# ============================================================================
# PlatformStatusRepository class has been moved to infrastructure/platform.py
# Now uses SQL composition pattern for injection safety.
# Imported above via: from infrastructure import PlatformStatusRepository
# ============================================================================

# ============================================================================
# HTTP HANDLERS
# ============================================================================

async def platform_request_status(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get status of a platform request.

    GET /api/platform/status/{request_id}
    GET /api/platform/status  (lists all requests)
    """
    logger.info("Platform status endpoint called")

    try:
        repo = PlatformStatusRepository()

        # Check if specific request_id provided
        request_id = req.route_params.get('request_id')

        if request_id:
            # Get specific request with job details
            result = repo.get_request_with_jobs(request_id)

            if not result:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"Platform request {request_id} not found"
                    }),
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )

            # Check and update completion status
            repo.check_and_update_completion(request_id)

            # Calculate summary statistics
            jobs = result.get('jobs', [])
            job_stats = {
                'total': len(jobs),
                'completed': sum(1 for j in jobs if j.get('status') == 'completed'),
                'failed': sum(1 for j in jobs if j.get('status') == 'failed'),
                'processing': sum(1 for j in jobs if j.get('status') == 'processing'),
                'pending': sum(1 for j in jobs if j.get('status') == 'pending')
            }

            # Add statistics to result
            result['job_statistics'] = job_stats

            # Add helpful URLs
            result['urls'] = {
                'jobs': [f"/api/jobs/status/{j['job_id']}" for j in jobs]
            }

            return func.HttpResponse(
                json.dumps(result, indent=2),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        else:
            # List all requests
            limit = int(req.params.get('limit', 100))
            status_filter = req.params.get('status')

            requests = repo.get_all_requests(limit, status_filter)

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
                "error": str(e)
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )