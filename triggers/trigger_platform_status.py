# ============================================================================
# PLATFORM STATUS HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - Platform status and diagnostic endpoints
# PURPOSE: Query Platform request/job status and diagnostics for gateway integration
# LAST_REVIEWED: 23 FEB 2026
# REVIEW_STATUS: V0.9.1 Clean B2B response - outputs/services/approval from Release record
# EXPORTS: platform_request_status, platform_job_status, platform_health, platform_failures, platform_lineage, platform_validate
# DEPENDENCIES: infrastructure.PlatformRepository, infrastructure.JobRepository, infrastructure.AssetRepository, infrastructure.ReleaseRepository
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
# V0.9: AssetRepository and ReleaseRepository imported lazily within functions
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
        - A release_id (V0.9 AssetRelease identifier)
        - An asset_id (V0.9 Asset identifier)
        The endpoint auto-detects which type of ID was provided.
        Query params:
            - detail=full: Include operational detail (job_result, task_summary, admin URLs)
            - verbose=true: Include full task details within detail block

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
        "asset": {"asset_id": "...", "dataset_id": "...", "resource_id": "...", "data_type": "raster", "release_count": 2},
        "release": {"release_id": "...", "version_id": "v1", "version_ordinal": 1, "approval_state": "approved", ...},
        "job_status": "completed",
        "outputs": {"blob_path": "...", "stac_item_id": "...", "stac_collection_id": "..."},
        "services": {"preview": "...", "tiles": "...", "viewer": "..."},
        "approval": null,
        "versions": [{"release_id": "...", "version_id": "v1", ...}]
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
        detail_full = req.params.get('detail', '').lower() == 'full'

        # V0.8.16.1: Reject deprecated query param lookups (09 FEB 2026)
        # Query params like ?job_id=xxx or ?request_id=xxx are not supported.
        # The correct pattern is /api/platform/status/{id} where {id} is auto-detected.
        deprecated_query_params = ['job_id', 'request_id', 'asset_id', 'release_id']
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
                        "single_lookup": "/api/platform/status/{id}  (id auto-detected as request_id, job_id, release_id, or asset_id)",
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
            # Updated 21 FEB 2026 (V0.9): request_id → job_id → release_id → asset_id
            # ================================================================
            platform_request = platform_repo.get_request(lookup_id)
            lookup_type = "request_id"
            pre_resolved_release = None  # V0.9: Track resolved release for response

            if not platform_request:
                # Try as job_id (reverse lookup)
                platform_request = platform_repo.get_request_by_job(lookup_id)
                lookup_type = "job_id"

            if not platform_request:
                # V0.9: Try as release_id
                try:
                    from infrastructure import ReleaseRepository
                    release_repo = ReleaseRepository()
                    release = release_repo.get_by_id(lookup_id)
                    if release:
                        if release.job_id:
                            platform_request = platform_repo.get_request_by_job(release.job_id)
                        lookup_type = "release_id"
                        pre_resolved_release = release
                except ImportError:
                    logger.warning("ReleaseRepository not available for release_id lookup")
                except Exception as e:
                    logger.warning(f"Release lookup failed for {lookup_id}: {e}")

            if not platform_request:
                # V0.9: Try as asset_id
                try:
                    from infrastructure import AssetRepository, ReleaseRepository
                    asset_repo = AssetRepository()
                    asset = asset_repo.get_by_id(lookup_id)
                    if asset:
                        release_repo = ReleaseRepository()
                        release = release_repo.get_latest(asset.asset_id)
                        if not release:
                            release = release_repo.get_draft(asset.asset_id)
                        if release:
                            if release.job_id:
                                platform_request = platform_repo.get_request_by_job(release.job_id)
                            lookup_type = "asset_id"
                            pre_resolved_release = release
                except ImportError:
                    logger.warning("AssetRepository/ReleaseRepository not available for asset_id lookup")
                except Exception as e:
                    logger.warning(f"Asset lookup failed for {lookup_id}: {e}")

            if not platform_request and not pre_resolved_release:
                return func.HttpResponse(
                    json.dumps({
                        "success": False,
                        "error": f"No Platform request found for ID: {lookup_id}",
                        "hint": "ID can be a request_id, job_id, release_id, or asset_id"
                    }),
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )

            logger.debug(f"Found platform request via {lookup_type}: {platform_request.request_id if platform_request else 'release-only'}")

            # Build response using shared helper (V0.9: pre_resolved_release)
            result = _build_single_status_response(
                platform_request, job_repo, task_repo,
                verbose=verbose, pre_resolved_release=pre_resolved_release,
                detail_full=detail_full
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
                    verbose=verbose, detail_full=detail_full
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
    pre_resolved_release=None,
    detail_full: bool = False
) -> dict:
    """
    Build clean B2B status response for a single Platform request.

    V0.9.1 (23 FEB 2026): Restructured for B2B clarity.
    - Reads outputs from Release record (authoritative), not job_result
    - Separates concerns: identity (asset), lifecycle (release), artifacts (outputs),
      access (services), workflow (approval)
    - ?detail=full appends operational detail: job_result, task_summary, admin URLs

    Args:
        platform_request: ApiRequest record (can be None for release/asset lookups)
        job_repo: JobRepository instance
        task_repo: TaskRepository instance
        verbose: Include full task details in task_summary
        pre_resolved_release: AssetRelease if already fetched (skips re-query)
        detail_full: If True, append job_result, task_summary, internal URLs

    Returns:
        Response dict ready for JSON serialization
    """
    from infrastructure import ReleaseRepository, AssetRepository

    # =====================================================================
    # 1. Resolve Release and Asset
    # =====================================================================
    release = pre_resolved_release
    asset = None

    if not release and platform_request and platform_request.job_id:
        try:
            release = ReleaseRepository().get_by_job_id(platform_request.job_id)
        except Exception as e:
            logger.warning(f"Release resolution from job_id failed: {e}")

    if release:
        try:
            asset = AssetRepository().get_by_id(release.asset_id)
        except Exception as e:
            logger.warning(f"Asset resolution from release failed: {e}")

    # Fallback asset from platform_request.asset_id if release didn't resolve
    if not asset and platform_request and getattr(platform_request, 'asset_id', None):
        try:
            asset = AssetRepository().get_by_id(platform_request.asset_id)
        except Exception as e:
            logger.warning(f"Asset fallback resolution failed: {e}")

    # =====================================================================
    # 2. Resolve Job status (single field, not the full result blob)
    # =====================================================================
    job = None
    job_status = "unknown"
    job_result = None
    job_id = None

    if platform_request and platform_request.job_id:
        job_id = platform_request.job_id
    elif release and release.job_id:
        job_id = release.job_id

    if job_id:
        job = job_repo.get_job(job_id)

    if job:
        job_status = job.status.value if hasattr(job.status, 'value') else job.status
        job_result = job.result_data
    elif release:
        # Use release processing_status as proxy if job not found
        job_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)

    # =====================================================================
    # 3. Determine data_type
    # =====================================================================
    data_type = None
    if asset:
        data_type = asset.data_type
    elif platform_request:
        data_type = platform_request.data_type

    # =====================================================================
    # 4. Build response
    # =====================================================================
    result = {
        "success": True,
        "request_id": platform_request.request_id if platform_request else None,
    }

    # Asset block
    if asset:
        result["asset"] = {
            "asset_id": asset.asset_id,
            "dataset_id": asset.dataset_id,
            "resource_id": asset.resource_id,
            "data_type": asset.data_type,
            "release_count": asset.release_count,
        }
    else:
        result["asset"] = None

    # Release block (with version_ordinal — new)
    if release:
        result["release"] = {
            "release_id": release.release_id,
            "version_id": release.version_id,
            "version_ordinal": release.version_ordinal,
            "revision": release.revision,
            "is_latest": release.is_latest,
            "processing_status": release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status),
            "approval_state": release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state),
            "clearance_state": release.clearance_state.value if hasattr(release.clearance_state, 'value') else str(release.clearance_state),
        }
    else:
        result["release"] = None

    # Job status (single field)
    result["job_status"] = job_status

    # Error block (25 FEB 2026): Surface structured error info when job failed.
    # The handler response in job_result already contains error_code, error_category,
    # remediation, user_fixable, detail — just not exposed in the default response.
    if job_status == "failed" and job_result and isinstance(job_result, dict):
        error_block = {}
        if job_result.get("error_code"):
            error_block["code"] = job_result["error_code"]
        if job_result.get("error_category"):
            error_block["category"] = job_result["error_category"]
        if job_result.get("message"):
            error_block["message"] = job_result["message"]
        if job_result.get("remediation"):
            error_block["remediation"] = job_result["remediation"]
        if "user_fixable" in job_result:
            error_block["user_fixable"] = job_result["user_fixable"]
        if job_result.get("detail"):
            error_block["detail"] = job_result["detail"]
        # Fallback: if handler didn't use structured errors (e.g., raster),
        # pull what we can from the flat response
        if not error_block and job_result.get("error"):
            error_block["code"] = job_result.get("error")
            error_block["message"] = job_result.get("message") or job_result.get("error")
        # Also fallback to job-level error_details string
        if not error_block and job and job.error_details:
            error_block["message"] = job.error_details

        result["error"] = error_block if error_block else None
    else:
        result["error"] = None

    # Outputs (from Release record, not job_result)
    result["outputs"] = _build_outputs_block(release, job_result)

    # Services (focused URLs)
    result["services"] = _build_services_block(release, data_type) if data_type else None

    # Approval (only when pending_review + completed)
    asset_id = asset.asset_id if asset else None
    result["approval"] = _build_approval_block(release, asset_id, data_type) if (asset_id and data_type) else None

    # Version history (always include if asset has releases)
    result["versions"] = None
    if asset:
        try:
            release_repo = ReleaseRepository()
            all_releases = release_repo.list_by_asset(asset.asset_id)
            if all_releases:
                result["versions"] = _build_version_summary(all_releases)
        except Exception as e:
            logger.warning(f"Version history resolution failed: {e}")

    # =====================================================================
    # 5. ?detail=full — append operational detail for debugging/internal use
    # =====================================================================
    if detail_full:
        result["detail"] = {
            "job_id": job_id,
            "job_type": job.job_type if job else None,
            "job_stage": job.stage if job else None,
            "job_result": job_result,
            "task_summary": _get_task_summary(task_repo, job_id, verbose=verbose) if job_id else None,
            "urls": {
                "job_status": f"/api/jobs/status/{job_id}" if job_id else None,
                "job_tasks": f"/api/dbadmin/tasks/{job_id}" if job_id else None,
            },
            "created_at": platform_request.created_at.isoformat() if platform_request and platform_request.created_at else None,
        }

    return result


def _get_release_table_names(release_id: str) -> list[str]:
    """Get table names for a release from the junction table."""
    from infrastructure import ReleaseTableRepository
    repo = ReleaseTableRepository()
    return repo.get_table_names(release_id)


def _build_version_summary(releases: list) -> list:
    """
    Build compact version summary from AssetRelease objects.

    V0.9 (21 FEB 2026): Now builds from AssetRelease objects instead of
    GeospatialAsset objects. Each release carries its own approval/clearance/
    processing state and version_id.

    Args:
        releases: List of AssetRelease objects

    Returns:
        List of dicts with version info, sorted by created_at descending
    """
    summaries = []
    for release in releases:
        summaries.append({
            "release_id": release.release_id,
            "version_id": release.version_id,
            "approval_state": release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state),
            "clearance_state": release.clearance_state.value if hasattr(release.clearance_state, 'value') else str(release.clearance_state),
            "processing_status": release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status),
            "is_latest": release.is_latest,
            "version_ordinal": release.version_ordinal,
            "revision": release.revision,
            "created_at": release.created_at.isoformat() if release.created_at else None,
            "blob_path": getattr(release, 'blob_path', None),
            "table_names": _get_release_table_names(release.release_id),
            "stac_item_id": getattr(release, 'stac_item_id', None),
            "stac_collection_id": getattr(release, 'stac_collection_id', None),
        })
    # Sort by created_at descending (most recent first)
    summaries.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return summaries


def _build_outputs_block(release, job_result: Optional[dict] = None) -> Optional[dict]:
    """
    Build the outputs block from Release physical fields.

    Reads blob_path, table_name, stac_item_id, stac_collection_id directly
    from the Release record. Falls back to job_result for container name
    (not stored on Release).

    Args:
        release: AssetRelease object
        job_result: Optional job result dict for supplementary fields

    Returns:
        Dict with output artifact locations, or None if no outputs yet
    """
    if not release:
        return None

    # No outputs if processing hasn't completed
    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    outputs = {
        "stac_item_id": release.stac_item_id,
        "stac_collection_id": release.stac_collection_id,
    }

    # Raster outputs
    if release.blob_path:
        outputs["blob_path"] = release.blob_path
        # Container from job_result (not stored on release)
        container = None
        if job_result:
            cog_data = job_result.get('cog', {})
            if isinstance(cog_data, dict):
                container = cog_data.get('cog_container')
        outputs["container"] = container or "silver-cogs"

    # Vector outputs
    table_names = _get_release_table_names(release.release_id)
    if table_names:
        outputs["table_names"] = table_names
        outputs["table_name"] = table_names[0]  # Primary for backward-compat in API response
        outputs["schema"] = "geo"

    return outputs


def _build_services_block(release, data_type: str) -> Optional[dict]:
    """
    Build focused service URLs for accessing the output data.

    Raster: preview, tiles, viewer (from titiler)
    Vector: collection, items (from OGC Features/TiPG)

    Args:
        release: AssetRelease object
        data_type: "raster" or "vector"

    Returns:
        Dict with service URLs, or None if no outputs
    """
    if not release:
        return None

    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    from config import get_config
    config = get_config()

    services = {}

    if data_type == "raster" and release.blob_path:
        titiler_base = config.titiler_base_url
        from urllib.parse import quote
        cog_url = quote(f"/vsiaz/silver-cogs/{release.blob_path}", safe='')
        services["collection"] = f"{titiler_base}/cog/WebMercatorQuad/tilejson.json?url={cog_url}"
        services["preview"] = f"{titiler_base}/cog/preview.png?url={cog_url}&max_size=512"
        services["tiles"] = f"{titiler_base}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={cog_url}"
        services["viewer"] = f"{titiler_base}/cog/WebMercatorQuad/map.html?url={cog_url}"

    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            tipg_base = config.tipg_base_url
            # Return URLs for ALL tables (multi-table releases)
            if len(table_names) == 1:
                qualified = f"geo.{table_names[0]}"
                services["collection"] = f"{tipg_base}/collections/{qualified}"
                services["items"] = f"{tipg_base}/collections/{qualified}/items"
            else:
                services["collections"] = []
                for tn in table_names:
                    qualified = f"geo.{tn}"
                    services["collections"].append({
                        "table_name": tn,
                        "collection": f"{tipg_base}/collections/{qualified}",
                        "items": f"{tipg_base}/collections/{qualified}/items",
                    })

    # STAC URLs (both raster and vector)
    if release.stac_collection_id:
        etl_base = config.etl_app_base_url
        services["stac_collection"] = f"{etl_base}/api/collections/{release.stac_collection_id}"
        if release.stac_item_id:
            services["stac_item"] = f"{etl_base}/api/collections/{release.stac_collection_id}/items/{release.stac_item_id}"

    return services if services else None


def _build_approval_block(release, asset_id: str, data_type: str) -> Optional[dict]:
    """
    Build approval workflow URLs.

    Only included when the release is in pending_review state.

    Args:
        release: AssetRelease object
        asset_id: Asset ID for approve/reject POST
        data_type: "raster" or "vector"

    Returns:
        Dict with approval URLs, or None if not pending
    """
    if not release:
        return None

    approval_state = release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state)
    if approval_state != 'pending_review':
        return None

    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    from config import get_config
    config = get_config()
    platform_base = config.platform_url.rstrip('/')

    approval = {
        "approve_url": f"{platform_base}/api/platform/approve",
        "asset_id": asset_id,
    }

    if data_type == "raster" and release.blob_path:
        from urllib.parse import quote
        # Always use direct COG URL (?url=) for approval preview.
        # STAC item doesn't exist yet — it's materialized AFTER approval.
        # TiTiler works directly from blob_path, no STAC needed.
        cog_url = quote(f"/vsiaz/silver-cogs/{release.blob_path}", safe='')
        approval["viewer_url"] = f"{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={asset_id}"
        approval["embed_url"] = f"{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={asset_id}&embed=true"

    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            # Use first/primary table for viewer URLs
            primary_table = table_names[0]
            approval["viewer_url"] = f"{platform_base}/api/interface/vector-viewer?collection={primary_table}&asset_id={asset_id}"
            approval["embed_url"] = f"{platform_base}/api/interface/vector-viewer?collection={primary_table}&asset_id={asset_id}&embed=true"
            if len(table_names) > 1:
                approval["all_tables"] = table_names

    return approval


def _handle_platform_refs_lookup(
    dataset_id: str,
    resource_id: str,
    job_repo,
    task_repo,
    platform_repo,
    verbose: bool = False,
    detail_full: bool = False
) -> func.HttpResponse:
    """
    Lookup status by dataset_id + resource_id (platform refs).

    V0.9.1 (23 FEB 2026): Simplified — delegates to _build_single_status_response()
    which now handles None platform_request and always includes versions.

    Priority logic for selecting the primary release:
        1. Release with active processing (PENDING or PROCESSING)
        2. Completed draft (no version_id, processing done)
        3. Latest approved release
        4. Most recent release overall

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
    from infrastructure import AssetRepository, ReleaseRepository

    asset_repo = AssetRepository()
    release_repo = ReleaseRepository()

    # Find asset by identity triple
    asset = asset_repo.get_by_identity("ddh", dataset_id, resource_id)
    if not asset:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"No asset found for dataset_id={dataset_id}, resource_id={resource_id}",
                "hint": "Check dataset_id and resource_id values, or submit a new request via /api/platform/submit"
            }),
            status_code=404,
            headers={"Content-Type": "application/json"}
        )

    # Get all releases for this asset
    releases = release_repo.list_by_asset(asset.asset_id)
    if not releases:
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "asset": {
                    "asset_id": asset.asset_id,
                    "dataset_id": asset.dataset_id,
                    "resource_id": asset.resource_id,
                    "data_type": asset.data_type,
                    "release_count": asset.release_count,
                },
                "releases": [],
                "message": "Asset exists but has no releases"
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    # Priority: active processing > completed draft > latest approved > most recent
    primary_release = None

    for r in releases:
        proc = r.processing_status.value if hasattr(r.processing_status, 'value') else str(r.processing_status)
        if proc in ('pending', 'processing'):
            primary_release = r
            break
    if not primary_release:
        for r in releases:
            if r.is_draft() and (r.processing_status.value if hasattr(r.processing_status, 'value') else str(r.processing_status)) == 'completed':
                primary_release = r
                break
    if not primary_release:
        for r in releases:
            if r.is_latest:
                primary_release = r
                break
    if not primary_release:
        primary_release = releases[0]

    # Get platform request for primary release's job
    platform_request = None
    if primary_release.job_id:
        platform_request = platform_repo.get_request_by_job(primary_release.job_id)

    # Build response using shared builder
    result = _build_single_status_response(
        platform_request, job_repo, task_repo,
        verbose=verbose, pre_resolved_release=primary_release,
        detail_full=detail_full
    )

    # Add lookup_type marker
    result["lookup_type"] = "platform_refs"

    return func.HttpResponse(
        json.dumps(result, indent=2, default=str),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )


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

        # Check Service Bus (fixed 24 FEB 2026 - field is 'namespace', not 'service_bus_fqdn')
        try:
            if config.queues and (config.queues.namespace or config.queues.connection_string):
                component_status["service_bus"] = "healthy"
            else:
                component_status["service_bus"] = "not_configured"
                status = "degraded"
        except Exception:
            component_status["service_bus"] = "unknown"

        # Check Docker worker (always deployed in 3-app architecture)
        try:
            worker_url = (
                (app_mode_config.docker_worker_url or "").rstrip('/')
                or "https://rmhheavyapi-ebdffqhkcsevg7f3.eastus-01.azurewebsites.net"
            )
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
                        "source": f"{row['container']}/{row['blob']}" if row['container'] and row['blob'] else None,
                        "failure_type": "job_failure"
                    })

                # Query approval rollbacks from asset_releases
                cur.execute(f"""
                    SELECT
                        r.release_id,
                        r.asset_id,
                        r.stac_item_id,
                        r.last_error,
                        r.updated_at as failed_at
                    FROM {config.app_schema}.asset_releases r
                    WHERE r.last_error LIKE 'ROLLBACK:%%'
                      AND r.updated_at >= NOW() - INTERVAL '%s hours'
                    ORDER BY r.updated_at DESC
                    LIMIT %s
                """, (hours, limit))
                rollbacks = cur.fetchall()

                for row in rollbacks:
                    raw_error = row['last_error'] or "Unknown rollback error"
                    error_summary, error_category = _sanitize_error(raw_error)

                    result["recent_failures"].append({
                        "release_id": row['release_id'],
                        "asset_id": row['asset_id'],
                        "stac_item_id": row['stac_item_id'],
                        "failed_at": row['failed_at'].isoformat() if row['failed_at'] else None,
                        "error_category": error_category,
                        "error_summary": error_summary,
                        "failure_type": "approval_rollback"
                    })

                # Sort merged list by failed_at descending
                result["recent_failures"].sort(
                    key=lambda x: x.get("failed_at") or "", reverse=True
                )

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
                    "success": False,
                    "error": "request_id is required",
                    "error_type": "ValidationError",
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
                    "success": False,
                    "error": f"Platform request {request_id} not found",
                    "error_type": "NotFound",
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
                    "success": False,
                    "error": "Associated job not found",
                    "error_type": "NotFound",
                    "request_id": request_id,
                    "job_id": platform_request.job_id,
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

        # Generate data access URLs via Release-based helpers (V0.9.1 - 23 FEB 2026)
        data_access = {}
        if job_status == "completed":
            try:
                from infrastructure import ReleaseRepository
                lineage_release = ReleaseRepository().get_by_job_id(job.job_id)
                if lineage_release:
                    data_type = platform_request.data_type if platform_request else None
                    services = _build_services_block(lineage_release, data_type) if data_type else None
                    if services:
                        data_access = services
            except Exception as e:
                logger.debug(f"Could not resolve release for lineage data_access: {e}")

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

        # Run version lineage validation (V0.9: no longer needs AssetService)
        validation_result = validate_version_lineage(
            platform_id="ddh",
            platform_refs=platform_refs,
            previous_version_id=platform_req.previous_version_id,
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

        # Return 400 when validation fails (18 FEB 2026)
        status_code = 200 if validation_result.valid else 400

        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=status_code,
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
