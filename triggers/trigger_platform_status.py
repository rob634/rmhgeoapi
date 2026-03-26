# ============================================================================
# PLATFORM STATUS HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - Platform status and diagnostic endpoints
# PURPOSE: Query Platform request/job status and diagnostics for gateway integration
# LAST_REVIEWED: 23 FEB 2026
# REVIEW_STATUS: V0.9.1 Clean B2B response - outputs/services/approval from Release record
# EXPORTS: platform_request_status, platform_health, platform_failures
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
Diagnostic Endpoints (F7.12 - 15 JAN 2026):
    GET /api/platform/health - Simplified system readiness check
    GET /api/platform/failures - Recent failures with sanitized errors

Exports:
    platform_request_status: HTTP trigger for GET /api/platform/status/{id}
    platform_health: HTTP trigger for GET /api/platform/health
    platform_failures: HTTP trigger for GET /api/platform/failures
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
                    "error_type": "ValidationError",
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
                        "error_type": "NotFound",
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

            # 202 while processing (keep polling), 200 when terminal
            is_processing = result.get("job_status") == "processing"
            status_code = 202 if is_processing else 200
            headers = {"Content-Type": "application/json"}
            if is_processing:
                headers["Retry-After"] = _compute_retry_after(result.get("progress"))

            return func.HttpResponse(
                json.dumps(result, indent=2, default=str),
                status_code=status_code,
                headers=headers
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
            offset = int(req.params.get('offset', 0))
            requests = platform_repo.get_all_requests(
                limit=limit, offset=offset, dataset_id=dataset_id
            )

            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "count": len(requests),
                    "limit": limit,
                    "offset": offset,
                    "has_more": len(requests) == limit,
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
            "ready": 0,
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
                "ready": 0,
                "pending_retry": 0,
                "skipped": 0,
                "cancelled": 0,
                "by_stage": {}
            }

        # Count by status (all 8 DAG-standard states)
        status_counts = {
            "total": len(tasks),
            "completed": 0,
            "failed": 0,
            "processing": 0,
            "pending": 0,
            "ready": 0,
            "pending_retry": 0,
            "skipped": 0,
            "cancelled": 0,
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
            elif status == "ready":
                status_counts["ready"] += 1
            elif status == "pending_retry":
                status_counts["pending_retry"] += 1
            elif status == "skipped":
                status_counts["skipped"] += 1
            elif status == "cancelled":
                status_counts["cancelled"] += 1

            # Update stage counts
            stage_key = str(task.stage)
            if stage_key not in by_stage:
                by_stage[stage_key] = {
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "processing": 0,
                    "pending": 0,
                    "ready": 0,
                    "pending_retry": 0,
                    "skipped": 0,
                    "cancelled": 0,
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
            elif status == "ready":
                by_stage[stage_key]["ready"] += 1
            elif status == "pending_retry":
                by_stage[stage_key]["pending_retry"] += 1
            elif status == "skipped":
                by_stage[stage_key]["skipped"] += 1
            elif status == "cancelled":
                by_stage[stage_key]["cancelled"] += 1

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

    dag_run = None  # DAG workflow run (if found)

    if job_id:
        job = job_repo.get_job(job_id)

    if job:
        job_status = job.status.value if hasattr(job.status, 'value') else job.status
        job_result = job.result_data
    else:
        # DAG fallback: job_id may be a DAG run_id (Epoch 5 workflows)
        if job_id:
            try:
                from infrastructure.workflow_run_repository import WorkflowRunRepository
                dag_run = WorkflowRunRepository().get_by_run_id(job_id)
                if dag_run:
                    job_status = dag_run.status.value if hasattr(dag_run.status, 'value') else str(dag_run.status)
                    job_result = dag_run.result_data
            except Exception as e:
                logger.debug(f"DAG run lookup failed for {job_id}: {e}")

        if not dag_run and release:
            # Use release processing_status as proxy if neither job nor DAG run found
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
            "processing_status": release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status),
            "approval_state": release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state),
            "clearance_state": release.clearance_state.value if hasattr(release.clearance_state, 'value') else str(release.clearance_state),
        }
    else:
        result["release"] = None

    # Job status (single field)
    result["job_status"] = job_status

    # Progress: lifesigns + checkpoint for in-progress jobs (19 MAR 2026)
    if job_status in ("processing", "running", "pending") and job_id:
        if dag_run:
            result["progress"] = _build_dag_progress_block(dag_run, job_id)
        else:
            result["progress"] = _build_progress_block(job, job_id)
    else:
        result["progress"] = None

    # Error block (05 MAR 2026): Surface error info when job failed.
    # Primary source: error_details (always set by fail_job()).
    # Secondary: result_data JSONB (structured ErrorResponse from handler).
    if job_status == "failed":
        error_block = {}

        # Primary: error_details string (always set on failed jobs)
        if job and job.error_details:
            error_block["message"] = job.error_details

        # Enrich from structured ErrorResponse when handler provided one
        if job_result and isinstance(job_result, dict):
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
            if job_result.get("details"):
                error_block["detail"] = job_result["details"]
            elif job_result.get("detail"):
                error_block["detail"] = job_result["detail"]
            if job_result.get("error_id"):
                error_block["error_id"] = job_result["error_id"]

        result["error"] = error_block if error_block else None
    else:
        result["error"] = None

    # Job metadata block: promote to default response on failure
    if job_status == "failed" and job:
        result["job"] = {
            "job_id": job_id,
            "job_type": job.job_type,
            "etl_version": job.etl_version,
            "stage": job.stage,
            "total_stages": job.total_stages,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "duration_seconds": round((job.updated_at - job.created_at).total_seconds(), 2) if (job.created_at and job.updated_at) else None,
        }
    else:
        result["job"] = None

    # Warnings (ERH-5/6): Surface data_warnings from handler result
    # These include NULL_GEOMETRY_DROPPED, GEOMETRY_TYPE_SPLIT, datetime issues, etc.
    warnings_list = None
    if job_result and isinstance(job_result, dict):
        inner_result = job_result.get("result", {})
        if isinstance(inner_result, dict):
            raw_warnings = inner_result.get("data_warnings")
            if raw_warnings:
                warnings_list = raw_warnings
    result["warnings"] = warnings_list

    # Outputs (from Release record, not job_result)
    result["outputs"] = _build_outputs_block(release, job_result, asset)

    # Services (focused URLs)
    result["services"] = _build_services_block(release, data_type, asset) if data_type else None

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
        if dag_run:
            result["detail"] = {
                "job_id": job_id,
                "workflow_engine": "dag",
                "workflow_name": dag_run.workflow_name,
                "job_result": job_result,
                "task_summary": _get_dag_task_summary(job_id),
                "urls": {
                    "dag_run": f"/api/dag/runs/{job_id}",
                },
                "created_at": dag_run.created_at.isoformat() if dag_run.created_at else None,
                "started_at": dag_run.started_at.isoformat() if dag_run.started_at else None,
                "completed_at": dag_run.completed_at.isoformat() if dag_run.completed_at else None,
            }
        else:
            result["detail"] = {
                "job_id": job_id,
                "workflow_engine": "coremachine",
                "job_type": job.job_type if job else None,
                "job_stage": job.stage if job else None,
                "job_result": job_result,
                "task_summary": _get_task_summary(task_repo, job_id, verbose=verbose) if job_id else None,
                "checkpoints": _get_latest_checkpoints(job_id),
                "urls": {
                    "job_status": f"/api/jobs/status/{job_id}" if job_id else None,
                    "job_tasks": f"/api/dbadmin/tasks/{job_id}" if job_id else None,
                },
                "created_at": platform_request.created_at.isoformat() if platform_request and platform_request.created_at else None,
            }

    return result


def _build_dag_progress_block(dag_run, run_id: str) -> dict:
    """Build progress block for DAG workflow runs."""
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        tasks = WorkflowRunRepository().get_tasks_for_run(run_id)
        by_status = {}
        for t in tasks:
            s = t.status.value if hasattr(t.status, 'value') else str(t.status)
            by_status[s] = by_status.get(s, 0) + 1
        total = len(tasks)
        done = by_status.get('completed', 0) + by_status.get('skipped', 0)
        return {
            "workflow_engine": "dag",
            "workflow_name": dag_run.workflow_name,
            "started_at": dag_run.started_at.isoformat() if dag_run.started_at else None,
            "tasks_total": total,
            "tasks_done": done,
            "tasks_by_status": by_status,
            "percent_complete": round(done / total * 100) if total else 0,
        }
    except Exception as e:
        logger.warning(f"DAG progress block failed: {e}")
        return {"workflow_engine": "dag", "error": str(e)}


def _get_dag_task_summary(run_id: str) -> dict:
    """Build task summary for DAG workflow runs (detail=full)."""
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        tasks = WorkflowRunRepository().get_tasks_for_run(run_id)
        by_status = {}
        task_list = []
        for t in tasks:
            s = t.status.value if hasattr(t.status, 'value') else str(t.status)
            by_status[s] = by_status.get(s, 0) + 1
            task_list.append({
                "task_name": t.task_name,
                "handler": t.handler,
                "status": s,
            })
        return {
            "total": len(tasks),
            "by_status": by_status,
            "tasks": task_list,
        }
    except Exception as e:
        logger.warning(f"DAG task summary failed: {e}")
        return {"error": str(e)}


def _build_progress_block(job, job_id: str) -> dict:
    """
    Build progress block with lifesigns for in-progress jobs (19 MAR 2026).

    Provides duration indicators so B2B polling clients can determine:
    - How long the job has been running (elapsed_seconds, started_at)
    - Whether the job is still alive (updated_at recency)
    - Last known checkpoint (if any)

    Args:
        job: Job object (may be None)
        job_id: Job identifier

    Returns:
        Dict with lifesigns and optional checkpoint
    """
    now = datetime.now(timezone.utc)

    started_at = None
    updated_at = None
    elapsed_seconds = None

    if job:
        if job.created_at:
            started_at = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
            elapsed_seconds = round((now - started_at).total_seconds(), 1)
        if job.updated_at:
            updated_at = job.updated_at if job.updated_at.tzinfo else job.updated_at.replace(tzinfo=timezone.utc)

    progress = {
        "started_at": started_at.isoformat() if started_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "elapsed_seconds": elapsed_seconds,
        "checkpoint": None,
        "checkpoint_at": None,
    }

    # Overlay latest checkpoint if available
    checkpoint = _get_latest_checkpoint(job_id)
    if checkpoint:
        progress["checkpoint"] = checkpoint["checkpoint"]
        progress["checkpoint_at"] = checkpoint["at"]

    return progress


def _compute_retry_after(progress: dict | None) -> str:
    """
    Compute Retry-After value based on how long the job has been running.

    Short intervals early (job may finish quickly), longer as it ages
    (long-running ETL, avoid hammering).

    Returns:
        Retry-After header value in seconds (as string)
    """
    elapsed = (progress or {}).get("elapsed_seconds") or 0
    if elapsed < 30:
        return "5"
    elif elapsed < 120:
        return "10"
    elif elapsed < 600:
        return "15"
    else:
        return "30"


def _get_latest_checkpoint(job_id: str) -> dict | None:
    """Get the single most recent CHECKPOINT for a processing job."""
    try:
        from infrastructure.job_event_repository import JobEventRepository
        from core.models.job_event import JobEventType
        events = JobEventRepository().get_events_for_job(
            job_id, limit=1, event_types=[JobEventType.CHECKPOINT]
        )
        if events:
            e = events[0]
            return {
                "checkpoint": e.checkpoint_name,
                "data": e.event_data,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
    except Exception:
        pass
    return None


def _get_latest_checkpoints(job_id: str, limit: int = 10) -> list:
    """Get recent CHECKPOINT events for a job."""
    if not job_id:
        return []
    try:
        from infrastructure.job_event_repository import JobEventRepository
        from core.models.job_event import JobEventType
        events = JobEventRepository().get_events_for_job(
            job_id, limit=limit, event_types=[JobEventType.CHECKPOINT]
        )
        return [
            {
                "name": e.checkpoint_name,
                "data": e.event_data,
                "at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ] if events else []
    except Exception:
        return []


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
            "version_ordinal": release.version_ordinal,
            "revision": release.revision,
            "created_at": release.created_at.isoformat() if release.created_at else None,
            "blob_path": getattr(release, 'blob_path', None),
            "table_names": _get_release_table_names(release.release_id),
            "stac_item_id": getattr(release, 'stac_item_id', None),
            "stac_collection_id": getattr(release, 'stac_collection_id', None),
            "is_served": release.is_served,
            "reviewer": getattr(release, 'reviewer', None),
            "reviewed_at": release.reviewed_at.isoformat() if getattr(release, 'reviewed_at', None) else None,
            "rejection_reason": getattr(release, 'rejection_reason', None),
            "approval_notes": getattr(release, 'approval_notes', None),
        })
    # Sort by created_at descending (most recent first)
    summaries.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return summaries


def _build_outputs_block(release, job_result: Optional[dict] = None, asset=None) -> Optional[dict]:
    """
    Build the outputs block from Release physical fields.

    Reads blob_path, table_name, stac_item_id, stac_collection_id directly
    from the Release record. Falls back to job_result for container name
    (not stored on Release).

    Args:
        release: AssetRelease object
        job_result: Optional job result dict for supplementary fields
        asset: Optional Asset object for data_type-based container inference

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

    # Raster/Zarr outputs
    if release.blob_path:
        outputs["blob_path"] = release.blob_path
        # Container from job_result (not stored on release)
        container = None
        if job_result:
            cog_data = job_result.get('cog', {})
            if isinstance(cog_data, dict):
                container = cog_data.get('cog_container')
            if not container:
                zarr_url = job_result.get('zarr_store_url', '')
                if zarr_url and zarr_url.startswith('abfs://'):
                    container = zarr_url.replace('abfs://', '').split('/')[0]
        # SG13-4: Default based on asset data_type or blob_path prefix
        if not container:
            asset_data_type = getattr(asset, 'data_type', None) if asset else None
            dt_val = asset_data_type.value if hasattr(asset_data_type, 'value') else str(asset_data_type or '')
            if dt_val in ('zarr', 'raster_zarr'):
                container = "silver-zarr"
            elif release.blob_path.startswith("zarr/"):
                container = "silver-zarr"
            else:
                container = "silver-cogs"
        outputs["container"] = container

    # Vector outputs
    table_names = _get_release_table_names(release.release_id)
    if table_names:
        outputs["table_names"] = table_names
        outputs["table_name"] = table_names[0]  # Primary for backward-compat in API response
        outputs["schema"] = "geo"

    return outputs


def _build_zarr_url(release, config) -> Optional[str]:
    """Build abfs:// URL for zarr store from release fields."""
    blob_path = release.blob_path
    if not blob_path:
        return None
    output_mode = getattr(release, 'output_mode', '') or ''
    if output_mode == 'zarr_store':
        container = config.storage.silver.zarr
    else:
        container = config.storage.silver.netcdf
    return f"abfs://{container}/{blob_path}"


def _infer_raster_container(release, asset, config) -> str:
    """Infer the correct silver container for raster COGs."""
    asset_data_type = getattr(asset, 'data_type', None) if asset else None
    dt_val = asset_data_type.value if hasattr(asset_data_type, 'value') else str(asset_data_type or '')
    if dt_val in ('zarr', 'raster_zarr'):
        return config.storage.silver.zarr
    if release.blob_path and release.blob_path.startswith("zarr/"):
        return config.storage.silver.zarr
    return config.storage.silver.cogs


def _build_services_block(release, data_type: str, asset=None) -> Optional[dict]:
    """
    Build normalized service URLs for accessing the output data.

    Returns a consistent shape with 6 guaranteed keys (service_url, preview,
    stac_collection, stac_item, viewer, tiles) regardless of data type.
    Zarr adds a bonus 'variables' key; vector multi-table adds 'tables'.

    Args:
        release: AssetRelease object
        data_type: "raster", "vector", or "zarr"
        asset: GeospatialAsset object (used for container inference)

    Returns:
        Dict with service URLs, or None if no outputs
    """
    if not release:
        return None

    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    from config import get_config
    from urllib.parse import quote
    config = get_config()

    # Initialize consistent shape — all keys present for every data type
    services = {
        "service_url": None,
        "preview": None,
        "stac_collection": None,
        "stac_item": None,
        "viewer": None,
        "tiles": None,
    }

    if data_type == "raster" and release.blob_path:
        titiler_base = config.titiler_base_url.rstrip('/')
        container = _infer_raster_container(release, asset, config)
        cog_url = quote(f"/vsiaz/{container}/{release.blob_path}", safe='')
        services["service_url"] = f"{titiler_base}/cog/WebMercatorQuad/tilejson.json?url={cog_url}"
        services["preview"] = f"{titiler_base}/cog/preview.png?url={cog_url}&max_size=512"
        services["tiles"] = f"{titiler_base}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={cog_url}"
        services["viewer"] = f"{titiler_base}/cog/WebMercatorQuad/map.html?url={cog_url}"

    elif data_type == "vector":
        table_names = _get_release_table_names(release.release_id)
        if table_names:
            tipg_base = config.tipg_base_url
            # Primary table populates top-level keys
            primary = f"geo.{table_names[0]}"
            services["service_url"] = f"{tipg_base}/collections/{primary}"
            # preview: TiPG built-in viewer (future: custom platform viewer)
            services["preview"] = f"{tipg_base}/collections/{primary}/tiles/WebMercatorQuad/map"
            services["viewer"] = f"{tipg_base}/collections/{primary}/tiles/WebMercatorQuad/map"
            services["tiles"] = f"{tipg_base}/collections/{primary}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.pbf"
            # Vector has no STAC
            services["stac_collection"] = None
            services["stac_item"] = None
            # Multi-table: include all tables
            if len(table_names) > 1:
                services["tables"] = []
                for tn in table_names:
                    qualified = f"geo.{tn}"
                    services["tables"].append({
                        "table_name": tn,
                        "service_url": f"{tipg_base}/collections/{qualified}",
                        "tiles": f"{tipg_base}/collections/{qualified}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.pbf",
                    })

    elif data_type == "zarr" and release.blob_path:
        zarr_url = _build_zarr_url(release, config)
        if zarr_url:
            xarray_urls = config.generate_xarray_tile_urls(zarr_url)
            services["service_url"] = xarray_urls["tilejson"]
            services["preview"] = xarray_urls["preview"]
            services["viewer"] = xarray_urls["viewer"]
            services["tiles"] = xarray_urls["tiles"]
            services["variables"] = xarray_urls["variables"]

    # STAC URLs via Service Layer (titiler-pgstac STAC API)
    # The Service Layer Docker app hosts STAC at /stac/ — this is the B2C endpoint.
    # Vector has no STAC — skip if already set to None above.
    # SG14-1: STAC URLs are only exposed AFTER approval. TiTiler serves raster/zarr
    # tiles directly (via /vsiaz/ and abfs:// URLs) without needing STAC. STAC
    # materialization to pgSTAC happens at approval time, so showing STAC URLs
    # before approval would point to non-existent STAC items.
    approval_state = release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state)
    if data_type != "vector" and release.stac_collection_id and approval_state == 'approved':
        stac_base = f"{config.titiler_base_url.rstrip('/')}/stac"
        services["stac_collection"] = f"{stac_base}/collections/{release.stac_collection_id}"
        if release.stac_item_id:
            services["stac_item"] = f"{stac_base}/collections/{release.stac_collection_id}/items/{release.stac_item_id}"

    # =========================================================================
    # DEPRECATED: "collection" is a backward-compatibility alias for
    # "service_url". B2B consumers may reference services.collection.
    # Canonical key is "service_url" — all new integrations MUST use that.
    # TODO: Remove "collection" once all B2B consumers have migrated.
    # DEPRECATED since v0.9.16.0 (08 MAR 2026)
    # =========================================================================
    services["collection"] = services["service_url"]  # DEPRECATED — use service_url

    # Return None only if no service_url was populated (no outputs to show)
    return services if services["service_url"] else None


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
        container = _infer_raster_container(release, None, config)
        cog_url = quote(f"/vsiaz/{container}/{release.blob_path}", safe='')
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

    elif data_type == "zarr" and release.blob_path:
        from urllib.parse import quote
        # Build zarr preview URL for reviewer
        # No {variable} substitution — reviewer selects variable interactively in TiTiler map UI
        zarr_url = _build_zarr_url(release, config)
        if zarr_url:
            encoded = quote(zarr_url, safe='')
            titiler_base = config.titiler_base_url.rstrip('/')
            approval["viewer_url"] = f"{titiler_base}/xarray/WebMercatorQuad/map.html?url={encoded}&decode_times=false"

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
            if (r.approval_state.value if hasattr(r.approval_state, 'value') else str(r.approval_state)) == 'approved':
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

    is_processing = result.get("job_status") == "processing"
    status_code = 202 if is_processing else 200
    headers = {"Content-Type": "application/json"}
    if is_processing:
        headers["Retry-After"] = _compute_retry_after(result.get("progress"))

    return func.HttpResponse(
        json.dumps(result, indent=2, default=str),
        status_code=status_code,
        headers=headers
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
            "success": True,
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
                "success": False,
                "status": "unavailable",
                "ready_for_jobs": False,
                "error": "Health check failed",
                "error_type": "HealthCheckError",
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
            "success": True,
            "period_hours": hours,
            "limit": limit,
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
                "success": False,
                "error": "Failed to retrieve failure data",
                "error_type": "QueryError",
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
