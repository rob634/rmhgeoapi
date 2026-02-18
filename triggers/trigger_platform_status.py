# ============================================================================
# PLATFORM STATUS HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - Platform status and diagnostic endpoints
# PURPOSE: Query Platform request/job status and diagnostics for gateway integration
# LAST_REVIEWED: 18 FEB 2026
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
        Accepts EITHER request_id OR job_id OR asset_id - auto-detects ID type
    GET /api/platform/status?dataset_id=X&resource_id=Y - Lookup by platform refs (18 FEB 2026)
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
from triggers.http_base import parse_request_json

# Import infrastructure
from infrastructure import PlatformRepository, JobRepository, TaskRepository, PostgreSQLRepository, RepositoryFactory
from infrastructure import GeospatialAssetRepository  # V0.8 Entity Architecture (29 JAN 2026)
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
        - An asset_id (GeospatialAsset identifier)
        The endpoint auto-detects which type of ID was provided.
        Query params:
            - verbose=true: Include full task details (default: false)

    GET /api/platform/status?dataset_id=X&resource_id=Y
        Lookup by platform identifiers (18 FEB 2026).
        Finds all assets for the dataset+resource pair, surfaces the most
        actionable one (active job > completed draft > single > most recent).
        If multiple assets exist, includes a "versions" summary array.
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

        # V0.8.16.1: Reject deprecated query param lookups (09 FEB 2026)
        # Query params like ?job_id=xxx or ?request_id=xxx are not supported.
        # The correct pattern is /api/platform/status/{id} where {id} is auto-detected.
        deprecated_query_params = ['job_id', 'request_id', 'asset_id']
        used_deprecated = [p for p in deprecated_query_params if req.params.get(p)]
        if used_deprecated and not lookup_id:
            param_name = used_deprecated[0]
            param_value = req.params.get(param_name)
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Query parameter '{param_name}' is not supported for lookups",
                    "hint": f"Use path-based lookup instead: /api/platform/status/{param_value}",
                    "correct_usage": {
                        "single_lookup": "/api/platform/status/{id}  (id auto-detected as request_id, job_id, or asset_id)",
                        "list_all": "/api/platform/status  (optional: ?limit=N&dataset_id=X)"
                    },
                    "deprecated": f"?{param_name}=... query parameter"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        if lookup_id:
            # ================================================================
            # Single request lookup with auto-detect ID type (21 JAN 2026)
            # Updated 29 JAN 2026: Also supports asset_id lookup (V0.8)
            # First try as request_id, then as job_id, then as asset_id
            # ================================================================
            platform_request = platform_repo.get_request(lookup_id)
            lookup_type = "request_id"
            pre_resolved_asset = None  # V0.8: Track resolved asset for response

            if not platform_request:
                # Try as job_id (reverse lookup)
                platform_request = platform_repo.get_request_by_job(lookup_id)
                lookup_type = "job_id"

            if not platform_request:
                # V0.8: Try as asset_id (29 JAN 2026)
                try:
                    asset_repo = GeospatialAssetRepository()
                    asset = asset_repo.get_active_by_id(lookup_id)
                    if asset and asset.current_job_id:
                        # Found asset with linked job - get platform request via job
                        platform_request = platform_repo.get_request_by_job(asset.current_job_id)
                        lookup_type = "asset_id"
                        pre_resolved_asset = asset
                except Exception as asset_err:
                    logger.debug(f"Asset lookup failed (non-fatal): {asset_err}")

            if not platform_request:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"No Platform request found for ID: {lookup_id}",
                        "hint": "ID can be a request_id, job_id, or asset_id"
                    }),
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )

            logger.debug(f"Found platform request via {lookup_type}: {platform_request.request_id}")

            # Build response using shared helper (refactored 18 FEB 2026)
            result = _build_single_status_response(
                platform_request, job_repo, task_repo,
                verbose=verbose, pre_resolved_asset=pre_resolved_asset
            )

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )

        else:
            # ================================================================
            # No path ID — check for dataset_id + resource_id query params
            # or fall through to list-all (18 FEB 2026)
            # ================================================================
            dataset_id = req.params.get('dataset_id')
            resource_id = req.params.get('resource_id')

            if dataset_id and resource_id:
                # Asset lookup by platform refs (18 FEB 2026)
                return _handle_platform_refs_lookup(
                    dataset_id, resource_id,
                    job_repo, task_repo, platform_repo,
                    verbose=verbose
                )

            # List all requests (existing behavior)
            limit = int(req.params.get('limit', 100))
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


def _build_single_status_response(
    platform_request,
    job_repo,
    task_repo,
    verbose: bool = False,
    pre_resolved_asset=None
) -> dict:
    """
    Build the standard status response dict for a single Platform request.

    Extracts job status, task summary, asset info, and data access URLs into
    a reusable response shape shared by all lookup paths (request_id, job_id,
    asset_id, platform_refs).

    Args:
        platform_request: ApiRequest record
        job_repo: JobRepository instance
        task_repo: TaskRepository instance
        verbose: Include full task details in task_summary
        pre_resolved_asset: GeospatialAsset if already fetched (skips re-query)

    Returns:
        Response dict ready for JSON serialization
    """
    # Get CoreMachine job status
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

    # Get task summary
    task_summary = _get_task_summary(task_repo, platform_request.job_id, verbose=verbose)

    # Build response
    result = {
        "success": True,
        "request_id": platform_request.request_id,
        "dataset_id": platform_request.dataset_id,
        "resource_id": platform_request.resource_id,
        "version_id": platform_request.version_id,
        "data_type": platform_request.data_type,
        "created_at": platform_request.created_at.isoformat() if platform_request.created_at else None,
        "job_id": platform_request.job_id,
        "job_type": job_type,
        "job_status": job_status,
        "job_stage": job_stage,
        "job_result": job_result,
        "task_summary": task_summary,
        "asset": None,
        "urls": {
            "job_status": f"/api/jobs/status/{platform_request.job_id}",
            "job_tasks": f"/api/dbadmin/tasks/{platform_request.job_id}"
        }
    }

    # Resolve asset info
    resolved_asset_id = None
    if pre_resolved_asset:
        asset = pre_resolved_asset
        result["asset"] = {
            "asset_id": asset.asset_id,
            "revision": asset.revision,
            "approval_state": asset.approval_state.value if hasattr(asset.approval_state, 'value') else str(asset.approval_state),
            "clearance_state": asset.clearance_state.value if hasattr(asset.clearance_state, 'value') else str(asset.clearance_state),
        }
        resolved_asset_id = asset.asset_id
    else:
        # Try ApiRequest.asset_id first (set at submit time)
        resolved_asset_id = platform_request.asset_id
        # Fallback to Job.asset_id
        if not resolved_asset_id and job:
            resolved_asset_id = job.asset_id
        # Fetch full asset info
        if resolved_asset_id:
            try:
                asset_repo = GeospatialAssetRepository()
                asset = asset_repo.get_by_id(resolved_asset_id)
                if asset:
                    result["asset"] = {
                        "asset_id": asset.asset_id,
                        "revision": asset.revision,
                        "approval_state": asset.approval_state.value if hasattr(asset.approval_state, 'value') else str(asset.approval_state),
                        "clearance_state": asset.clearance_state.value if hasattr(asset.clearance_state, 'value') else str(asset.clearance_state),
                    }
            except Exception:
                pass  # Non-fatal

    # Add data access URLs if job completed
    if job_status == "completed" and job_result:
        result["data_access"] = _generate_data_access_urls(
            platform_request, job_type, job_result, asset_id=resolved_asset_id
        )

    return result


def _build_version_summary(assets: list) -> list:
    """
    Build compact version summary for multi-asset responses.

    Args:
        assets: List of GeospatialAsset objects

    Returns:
        List of dicts with version info, sorted by created_at descending
    """
    summaries = []
    for asset in assets:
        summaries.append({
            "asset_id": asset.asset_id,
            "version_id": getattr(asset, 'version_id', None) or (
                asset.platform_refs.get('version_id') if asset.platform_refs else None
            ),
            "approval_state": asset.approval_state.value if hasattr(asset.approval_state, 'value') else str(asset.approval_state),
            "clearance_state": asset.clearance_state.value if hasattr(asset.clearance_state, 'value') else str(asset.clearance_state),
            "processing_status": asset.processing_status.value if hasattr(asset.processing_status, 'value') else str(asset.processing_status),
            "is_latest": getattr(asset, 'is_latest', False),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        })
    # Sort by created_at descending (most recent first)
    summaries.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return summaries


def _handle_platform_refs_lookup(
    dataset_id: str,
    resource_id: str,
    job_repo,
    task_repo,
    platform_repo,
    verbose: bool = False
) -> func.HttpResponse:
    """
    Lookup status by dataset_id + resource_id (platform refs).

    Finds all assets matching the dataset/resource pair, selects the most
    actionable one (active job > completed draft > single > most recent),
    and returns the standard status response shape.

    Priority logic:
        1. Asset with active job (PENDING or PROCESSING) — currently running
        2. Completed draft (no version_id, processing done) — awaiting approval
        3. Only one asset total — unambiguous
        4. All approved — pick most recent, add workflow_status hint

    Added 18 FEB 2026 for DDH QA team workflow.

    Args:
        dataset_id: Platform dataset identifier
        resource_id: Platform resource identifier
        job_repo: JobRepository instance
        task_repo: TaskRepository instance
        platform_repo: PlatformRepository instance
        verbose: Include full task details

    Returns:
        func.HttpResponse with status JSON
    """
    from core.models.asset import ProcessingStatus, ApprovalState

    asset_repo = GeospatialAssetRepository()
    refs_filter = {"dataset_id": dataset_id, "resource_id": resource_id}
    assets = asset_repo.list_by_platform_refs("ddh", refs_filter)

    if not assets:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"No assets found for dataset_id={dataset_id}, resource_id={resource_id}",
                "hint": "Check dataset_id and resource_id values, or submit a new request via /api/platform/submit"
            }),
            status_code=404,
            headers={"Content-Type": "application/json"}
        )

    # Classify assets by state
    active_job_assets = []      # PENDING or PROCESSING
    completed_draft_assets = []  # Completed, no version_id (awaiting approval)
    approved_assets = []         # Approved
    other_assets = []

    for asset in assets:
        proc_status = asset.processing_status.value if hasattr(asset.processing_status, 'value') else str(asset.processing_status)
        approval = asset.approval_state.value if hasattr(asset.approval_state, 'value') else str(asset.approval_state)
        version_id = (asset.platform_refs or {}).get('version_id', '')

        if proc_status in ('pending', 'processing'):
            active_job_assets.append(asset)
        elif proc_status == 'completed' and approval != 'approved' and not version_id:
            completed_draft_assets.append(asset)
        elif approval == 'approved':
            approved_assets.append(asset)
        else:
            other_assets.append(asset)

    # Priority select primary asset
    primary_asset = None
    workflow_status = None
    workflow_message = None

    if active_job_assets:
        # Pick the most recent active job
        primary_asset = max(active_job_assets, key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc))
    elif completed_draft_assets:
        # Pick the most recent completed draft (awaiting approval)
        primary_asset = max(completed_draft_assets, key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc))
    elif len(assets) == 1:
        primary_asset = assets[0]
    else:
        # All approved or mixed — pick most recent
        primary_asset = max(assets, key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc))
        # Check if all are approved (no open workflow)
        if all(
            (a.approval_state.value if hasattr(a.approval_state, 'value') else str(a.approval_state)) == 'approved'
            for a in assets
        ):
            workflow_status = "no_open_workflow"
            workflow_message = "All versions approved. No active draft or processing job."

    # Reverse-lookup: asset → ApiRequest via current_job_id
    platform_request = None
    if primary_asset.current_job_id:
        platform_request = platform_repo.get_request_by_job(primary_asset.current_job_id)

    if platform_request:
        result = _build_single_status_response(
            platform_request, job_repo, task_repo,
            verbose=verbose, pre_resolved_asset=primary_asset
        )
    else:
        # Edge case: no ApiRequest found — build response from asset + job fields
        job = job_repo.get_job(primary_asset.current_job_id) if primary_asset.current_job_id else None
        result = {
            "success": True,
            "request_id": None,
            "dataset_id": dataset_id,
            "resource_id": resource_id,
            "version_id": (primary_asset.platform_refs or {}).get('version_id'),
            "data_type": primary_asset.data_type,
            "created_at": primary_asset.created_at.isoformat() if primary_asset.created_at else None,
            "job_id": primary_asset.current_job_id,
            "job_type": job.job_type if job else None,
            "job_status": (job.status.value if hasattr(job.status, 'value') else str(job.status)) if job else "unknown",
            "job_stage": job.stage if job else None,
            "job_result": job.result_data if job else None,
            "task_summary": _get_task_summary(task_repo, primary_asset.current_job_id, verbose=verbose) if primary_asset.current_job_id else {"total": 0},
            "asset": {
                "asset_id": primary_asset.asset_id,
                "revision": primary_asset.revision,
                "approval_state": primary_asset.approval_state.value if hasattr(primary_asset.approval_state, 'value') else str(primary_asset.approval_state),
                "clearance_state": primary_asset.clearance_state.value if hasattr(primary_asset.clearance_state, 'value') else str(primary_asset.clearance_state),
            },
            "urls": {
                "job_status": f"/api/jobs/status/{primary_asset.current_job_id}" if primary_asset.current_job_id else None,
                "job_tasks": f"/api/dbadmin/tasks/{primary_asset.current_job_id}" if primary_asset.current_job_id else None,
            }
        }
        # Add data access URLs if job completed
        if job and (job.status.value if hasattr(job.status, 'value') else str(job.status)) == "completed" and job.result_data:
            result["data_access"] = _generate_data_access_urls(
                platform_request, job.job_type, job.result_data, asset_id=primary_asset.asset_id
            )

    # Add lookup_type
    result["lookup_type"] = "platform_refs"

    # Add workflow_status if applicable
    if workflow_status:
        result["workflow_status"] = workflow_status
        result["message"] = workflow_message

    # Add version summary if multiple assets
    if len(assets) > 1:
        result["versions"] = _build_version_summary(assets)

    return func.HttpResponse(
        json.dumps(result, indent=2, default=str),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )


def _generate_data_access_urls(
    platform_request,
    job_type: str,
    job_result: Dict[str, Any],
    asset_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate data access URLs for completed jobs.

    Uses config properties to build URLs for the correct services:
    - OGC Features: TiPG at {TITILER_BASE_URL}/vector (28 JAN 2026)
    - STAC API: ETL_APP_URL/api/stac (on ETL Function App)
    - TiTiler: TITILER_BASE_URL (dedicated tile server)
    - Vector Viewer: ETL_APP_URL (admin/ETL app)
    - Approval UI: PLATFORM_URL/api/interface/* with embed mode (07 FEB 2026)
    - Approve Action: POST endpoint for B2B apps to approve (09 FEB 2026)

    URL Configuration:
        PLATFORM_URL: Public URL for this app instance. Used for approval URLs
                      that B2B clients will embed in iframes. Falls back to
                      ETL_APP_URL if not set. Gateway and Orchestrator each
                      set their own PLATFORM_URL.

    Args:
        platform_request: ApiRequest record
        job_type: Type of CoreMachine job
        job_result: Job result data
        asset_id: GeospatialAsset ID for approval workflow (09 FEB 2026)

    Returns:
        Dictionary with OGC Features, STAC, TiTiler, approval URLs as applicable
    """
    from config import get_config
    config = get_config()

    # Get service URLs from config (no hardcoded fallbacks - fail-fast design)
    # TiPG provides OGC Features at {TITILER_BASE_URL}/vector (28 JAN 2026)
    tipg_base = config.tipg_base_url

    # STAC API on ETL Function App
    etl_app_base = config.etl_app_base_url

    # TiTiler for raster tiles
    titiler_base = config.titiler_base_url

    # Platform URL for B2B-facing responses (07 FEB 2026)
    # This is the public URL for THIS app instance (Gateway or Orchestrator)
    # Used for approval iframe URLs that B2B apps will embed
    platform_base = config.platform_url.rstrip('/')

    urls = {}

    # Vector job → TiPG OGC Features URLs + approval UI
    # Updated 07 FEB 2026: Added vector_docker_etl (current active job type)
    if job_type in ['process_vector', 'vector_docker_etl']:
        table_name = job_result.get('table_name')
        if table_name:
            # TiPG requires schema-qualified names
            qualified_name = f"geo.{table_name}" if '.' not in table_name else table_name
            urls['postgis'] = {
                'schema': 'geo',
                'table': table_name
            }
            urls['ogc_features'] = {
                'collection': f"{tipg_base}/collections/{qualified_name}",
                'items': f"{tipg_base}/collections/{qualified_name}/items",
                'viewer': f"{etl_app_base}/api/interface/vector?collection={table_name}"
            }
            # Approval UI for B2B iframe embedding (07 FEB 2026, updated 09 FEB 2026)
            # Uses platform_base (PLATFORM_URL) for B2B-accessible URLs
            # Vector viewer at /api/interface/vector-viewer with asset_id for approve/reject
            # Native viewer uses OGC Features endpoint (TiPG /vector)
            approval_urls = {
                'viewer': f"{tipg_base}/collections/{qualified_name}",  # Native OGC Features
                'embed': f"{platform_base}/api/interface/vector-viewer?collection={table_name}&embed=true"
            }
            # Add asset_id to viewer URLs if available (enables approve/reject buttons)
            if asset_id:
                approval_urls['embed'] = f"{platform_base}/api/interface/vector-viewer?collection={table_name}&asset_id={asset_id}&embed=true"
                approval_urls['approve'] = f"{platform_base}/api/platform/approve"
                approval_urls['approve_asset_id'] = asset_id  # B2B knows what to POST
            urls['approval'] = approval_urls

    # Raster job → STAC + TiTiler URLs + approval UI
    # Updated 07 FEB 2026: Added process_raster_docker (current active job type)
    # Updated 09 FEB 2026: Handle nested result structure (cog.cog_blob, stac.item_id)
    elif job_type in ['process_raster_v2', 'process_large_raster_v2', 'process_raster_collection_v2',
                      'process_raster_docker', 'process_large_raster_docker', 'process_raster_collection_docker']:
        collection_id = job_result.get('collection_id')

        # Extract COG URL - try nested structure first (current), then flat (legacy)
        cog_url = None
        cog_data = job_result.get('cog', {})
        if isinstance(cog_data, dict):
            # Current nested structure: job_result.cog.cog_blob
            cog_blob = cog_data.get('cog_blob') or cog_data.get('cog_url')
            if cog_blob:
                cog_url = cog_blob
        if not cog_url:
            # Legacy flat structure or fallback
            cog_url = job_result.get('cog_url') or job_result.get('cog_blob')

        # Extract STAC item ID - try nested structure first, then flat
        stac_item_id = None
        stac_data = job_result.get('stac', {})
        if isinstance(stac_data, dict):
            # Current nested structure: job_result.stac.item_id
            stac_item_id = stac_data.get('item_id') or stac_data.get('stac_item_id')
        if not stac_item_id:
            # Legacy flat structure
            stac_item_id = job_result.get('stac_item_id') or job_result.get('item_id')

        # Also get collection_id from nested if not at top level
        if not collection_id and isinstance(stac_data, dict):
            collection_id = stac_data.get('collection_id')

        if collection_id:
            urls['stac'] = {
                'collection': f"{etl_app_base}/api/collections/{collection_id}",
                'items': f"{etl_app_base}/api/collections/{collection_id}/items",
                'search': f"{etl_app_base}/api/search"
            }

        if cog_url:
            urls['titiler'] = {
                'preview': f"{titiler_base}/cog/preview?url={cog_url}",
                'info': f"{titiler_base}/cog/info?url={cog_url}",
                'tiles': f"{titiler_base}/cog/tiles/{{z}}/{{x}}/{{y}}?url={cog_url}"
            }

            # Approval UI for B2B iframe embedding (07 FEB 2026, updated 09 FEB 2026)
            # Uses platform_base (PLATFORM_URL) for B2B-accessible URLs
            # Native viewer uses TiTiler /cog endpoint
            from urllib.parse import quote
            encoded_url = quote(cog_url, safe='')
            approval_urls = {
                'viewer': f"{titiler_base}/cog/viewer?url={encoded_url}",  # Native COG viewer
                'embed': f"{platform_base}/api/interface/raster-viewer?url={encoded_url}&embed=true"
            }
            # Add asset_id for approve/reject workflow
            if asset_id:
                approval_urls['embed'] = f"{platform_base}/api/interface/raster-viewer?url={encoded_url}&asset_id={asset_id}&embed=true"
                approval_urls['approve'] = f"{platform_base}/api/platform/approve"
                approval_urls['approve_asset_id'] = asset_id

            # If STAC item ID available, prefer that for approval workflow
            if stac_item_id:
                approval_urls['viewer'] = f"{titiler_base}/stac/viewer?item_id={stac_item_id}"  # Native STAC viewer
                approval_urls['embed'] = f"{platform_base}/api/interface/raster-viewer?item_id={stac_item_id}&embed=true"
                if asset_id:
                    approval_urls['embed'] = f"{platform_base}/api/interface/raster-viewer?item_id={stac_item_id}&asset_id={asset_id}&embed=true"

            urls['approval'] = approval_urls

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
        "version": "0.7.35.5",
        "uptime_seconds": 3600,
        "summary": {
            "database": "healthy",
            "storage": "healthy",
            "service_bus": "healthy",
            "docker_worker": "healthy"
        },
        "jobs": {
            "queue_backlog": 5,
            "processing": 2,
            "failed_last_24h": 1,
            "avg_completion_minutes": 15.3
        },
        "timestamp": "2026-01-15T10:00:00Z"
    }

    Updated 29 JAN 2026: Added version, uptime_seconds, docker_worker status.
    Fixed storage/service_bus config checks.
    """
    import requests
    import psutil
    from config import __version__, get_app_mode_config

    logger.info("Platform health endpoint called")

    try:
        config = get_config()
        app_mode_config = get_app_mode_config()
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']

        # Overall status
        status = "healthy"
        ready_for_jobs = True
        component_status = {}

        # Get uptime
        try:
            process = psutil.Process()
            uptime_seconds = int((datetime.now(timezone.utc) - datetime.fromtimestamp(process.create_time(), tz=timezone.utc)).total_seconds())
        except Exception:
            uptime_seconds = None

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

        # Check storage connectivity (fixed 29 JAN 2026 - correct config path)
        try:
            if config.storage and config.storage.bronze and config.storage.bronze.account_name:
                component_status["storage"] = "healthy"
            else:
                component_status["storage"] = "not_configured"
                status = "degraded"
        except Exception as storage_err:
            logger.warning(f"Storage config check failed: {storage_err}")
            component_status["storage"] = "unavailable"
            status = "degraded"

        # Check Service Bus (fixed 29 JAN 2026 - correct config path)
        try:
            if config.queues and config.queues.service_bus_fqdn:
                component_status["service_bus"] = "healthy"
            else:
                component_status["service_bus"] = "not_configured"
        except Exception:
            component_status["service_bus"] = "unknown"

        # Check Docker worker (added 29 JAN 2026)
        try:
            if app_mode_config.docker_worker_enabled and app_mode_config.docker_worker_url:
                worker_url = app_mode_config.docker_worker_url.rstrip('/')
                try:
                    resp = requests.get(f"{worker_url}/health", timeout=10)
                    if resp.status_code == 200:
                        component_status["docker_worker"] = "healthy"
                    else:
                        component_status["docker_worker"] = "degraded"
                        status = "degraded"
                except requests.exceptions.RequestException:
                    component_status["docker_worker"] = "unavailable"
                    status = "degraded"
            else:
                component_status["docker_worker"] = "disabled"
        except Exception:
            component_status["docker_worker"] = "unknown"

        # Get job statistics
        job_stats = {}
        try:
            if isinstance(job_repo, PostgreSQLRepository):
                with job_repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Queue backlog (pending + queued jobs)
                        # Use parameterized schema name via psycopg.sql for safety
                        from psycopg import sql
                        query = sql.SQL("""
                            SELECT
                                COUNT(*) FILTER (WHERE status::text IN ('queued', 'pending')) as backlog,
                                COUNT(*) FILTER (WHERE status::text = 'processing') as processing,
                                COUNT(*) FILTER (WHERE status::text = 'failed'
                                    AND updated_at >= NOW() - INTERVAL '24 hours') as failed_24h,
                                AVG(EXTRACT(EPOCH FROM (updated_at - created_at))/60)
                                    FILTER (WHERE status::text = 'completed'
                                    AND updated_at >= NOW() - INTERVAL '24 hours') as avg_minutes
                            FROM {schema}.jobs
                            WHERE created_at >= NOW() - INTERVAL '7 days'
                        """).format(schema=sql.Identifier(config.app_schema))
                        cur.execute(query)
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
            "version": __version__,
            "uptime_seconds": uptime_seconds,
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
                        j.job_id as job_id,
                        j.job_type,
                        j.updated_at as failed_at,
                        j.result_data->>'error' as raw_error,
                        j.parameters->>'container_name' as container,
                        j.parameters->>'blob_name' as blob,
                        p.request_id
                    FROM {config.app_schema}.jobs j
                    LEFT JOIN {config.app_schema}.api_requests p ON j.job_id = p.job_id
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

        # Build outputs info (09 FEB 2026: handle nested structure for raster jobs)
        outputs = {}

        # COG URL - try nested structure first, then flat
        cog_data = result_data.get('cog', {})
        if isinstance(cog_data, dict) and (cog_data.get('cog_blob') or cog_data.get('cog_url')):
            outputs['cog_url'] = cog_data.get('cog_blob') or cog_data.get('cog_url')
        elif result_data.get('cog_url'):
            outputs['cog_url'] = result_data['cog_url']

        # STAC collection/item - try nested structure first, then flat
        stac_data = result_data.get('stac', {})
        if isinstance(stac_data, dict):
            if stac_data.get('collection_id'):
                outputs['stac_collection'] = stac_data['collection_id']
            if stac_data.get('item_id'):
                outputs['stac_item'] = stac_data['item_id']
        if not outputs.get('stac_collection') and result_data.get('collection_id'):
            outputs['stac_collection'] = result_data['collection_id']
        if not outputs.get('stac_item') and result_data.get('stac_item_id'):
            outputs['stac_item'] = result_data['stac_item_id']

        # Vector outputs
        if result_data.get('table_name'):
            outputs['table_name'] = result_data['table_name']
            outputs['schema'] = 'geo'

        # Generate data access URLs (V0.8.12: include asset_id for approval - 09 FEB 2026)
        data_access = {}
        if job_status == "completed":
            # Get asset_id from job record if available
            lineage_asset_id = getattr(job, 'asset_id', None)
            data_access = _generate_data_access_urls(platform_request, job.job_type, result_data, asset_id=lineage_asset_id)

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
    Pre-flight validation before job submission (V0.8 Release Control - 31 JAN 2026).

    POST /api/platform/validate

    Validates a platform request BEFORE submission. This endpoint returns the
    same response as POST /api/platform/submit?dry_run=true for workflow flexibility.

    Use Cases:
    - Workflow A: Call /validate first, then /submit if valid
    - Workflow B: Call /submit?dry_run=true, then /submit if valid

    Both approaches use the same underlying validation logic.

    Request Body (same as /api/platform/submit):
    {
        "dataset_id": "floods",
        "resource_id": "jakarta",
        "version_id": "v2.0",
        "container_name": "bronze-rasters",
        "file_name": "jakarta_flood.tif",
        "previous_version_id": "v1.0"  // Required for version advances
    }

    Response (same structure as dry_run=true):
    {
        "valid": true,
        "dry_run": true,
        "request_id": "abc123...",
        "would_create_job_type": "process_raster_docker",
        "lineage_state": {
            "lineage_id": "def456...",
            "lineage_exists": true,
            "current_latest": {"version_id": "v1.0", ...}
        },
        "validation": {
            "data_type_detected": "raster",
            "previous_version_valid": true
        },
        "warnings": [],
        "suggested_params": {
            "previous_version_id": "v1.0",
            "version_ordinal": 2
        }
    }
    """
    logger.info("Platform validate endpoint called")

    try:
        # Parse request body
        try:
            req_body = parse_request_json(req)
        except ValueError as e:
            return func.HttpResponse(
                json.dumps({
                    "valid": False,
                    "error": str(e),
                    "usage": "Same request body as POST /api/platform/submit"
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Import models and services
        from core.models import PlatformRequest
        from services.asset_service import AssetService
        from services.platform_validation import validate_version_lineage
        from services.platform_translation import translate_to_coremachine
        from config import generate_platform_request_id

        config = get_config()

        # Parse as PlatformRequest (validates required fields)
        try:
            platform_req = PlatformRequest(**req_body)
        except Exception as validation_err:
            return func.HttpResponse(
                json.dumps({
                    "valid": False,
                    "error": f"Invalid request: {validation_err}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Generate deterministic request ID
        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id
        )

        # Translate to get job type
        try:
            job_type, _ = translate_to_coremachine(platform_req, config)
        except Exception as translate_err:
            return func.HttpResponse(
                json.dumps({
                    "valid": False,
                    "request_id": request_id,
                    "error": f"Translation failed: {translate_err}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )

        # Build platform_refs
        platform_refs = {
            "dataset_id": platform_req.dataset_id,
            "resource_id": platform_req.resource_id,
            "version_id": platform_req.version_id
        }

        # Run version lineage validation
        asset_service = AssetService()
        validation_result = validate_version_lineage(
            platform_id="ddh",
            platform_refs=platform_refs,
            previous_version_id=platform_req.previous_version_id,
            asset_service=asset_service
        )

        # Build response (same structure as dry_run=true)
        result = {
            "valid": validation_result.valid,
            "dry_run": True,
            "request_id": request_id,
            "would_create_job_type": job_type,
            "lineage_state": {
                "lineage_id": validation_result.lineage_id,
                "lineage_exists": validation_result.lineage_exists,
                "current_latest": validation_result.current_latest
            },
            "validation": {
                "data_type_detected": platform_req.data_type.value,
                "previous_version_valid": validation_result.valid
            },
            "warnings": validation_result.warnings,
            "suggested_params": validation_result.suggested_params,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"Platform validate failed: {e}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "error": "Validation failed",
                "error_type": type(e).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )
