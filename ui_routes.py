# ============================================================================
# CLAUDE CONTEXT - DAG BRAIN ADMIN UI ROUTES
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: FastAPI Router - Admin UI pages for DAG Brain Docker app
# PURPOSE: Serve Jinja2-rendered admin pages mounted at /ui/ prefix
# LAST_REVIEWED: 31 MAR 2026
# EXPORTS: router
# DEPENDENCIES: fastapi, ui.templates_helper, infrastructure.workflow_run_repository, services
# ============================================================================
"""
DAG Brain Admin UI Routes.

FastAPI APIRouter serving Jinja2-rendered admin pages.
Mounted at /ui/ prefix in docker_service.py when APP_MODE=orchestrator.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ui.templates_helper import render_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["admin-ui"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Admin dashboard with job stats and health summary."""
    stats = _get_dashboard_stats()
    return render_template(
        request,
        "pages/dashboard.html",
        stats=stats,
        nav_active="/ui/",
    )


@router.get("/jobs", response_class=HTMLResponse)
async def job_list(request: Request, status: Optional[str] = None, limit: int = 50):
    """Workflow run list with filtering."""
    from infrastructure.workflow_run_repository import WorkflowRunRepository
    repo = WorkflowRunRepository()

    runs = repo.list_runs(status=status, limit=limit)

    # Compute stats from the result set
    status_counts = {}
    for r in runs:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    stats = {
        "total": len(runs),
        "running": status_counts.get("running", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "awaiting_approval": status_counts.get("awaiting_approval", 0),
    }

    return render_template(
        request,
        "pages/jobs/list.html",
        jobs=runs,
        stats=stats,
        filters={"status": status, "limit": limit},
        nav_active="/ui/jobs",
    )


@router.get("/jobs/{run_id}", response_class=HTMLResponse)
async def job_detail(request: Request, run_id: str):
    """Workflow run detail with task breakdown."""
    from infrastructure.workflow_run_repository import WorkflowRunRepository
    repo = WorkflowRunRepository()

    run = repo.get_by_run_id(run_id)
    if not run:
        return HTMLResponse(f"Run {run_id} not found", status_code=404)

    tasks = repo.list_task_details(run_id)
    task_counts = repo.get_task_status_counts(run_id)

    return render_template(
        request,
        "pages/jobs/detail.html",
        job=run,
        tasks=tasks,
        task_counts=task_counts,
        nav_active="/ui/jobs",
    )


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    """Cross-system health dashboard."""
    return render_template(
        request,
        "pages/admin/health.html",
        nav_active="/ui/health",
    )


@router.get("/handlers", response_class=HTMLResponse)
async def handlers_page(request: Request):
    """Handler registry browser."""
    try:
        from services import ALL_HANDLERS
        handlers = sorted(ALL_HANDLERS.keys())
    except Exception:
        handlers = []

    return render_template(
        request,
        "pages/handlers.html",
        handlers=handlers,
        nav_active="/ui/handlers",
    )


@router.get("/submit", response_class=HTMLResponse)
async def submit_page(request: Request):
    """Unified submit page for raster and vector data."""
    return render_template(
        request,
        "pages/submit.html",
        nav_active="/ui/submit",
    )


@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request):
    """Asset registry — summary of all assets with approval states."""
    return render_template(
        request,
        "pages/assets.html",
        nav_active="/ui/assets",
    )


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail_page(request: Request, asset_id: str):
    """Asset detail — release history with admin actions."""
    return render_template(
        request,
        "pages/asset_detail.html",
        asset_id=asset_id,
        nav_active="/ui/assets",
    )


def _get_dashboard_stats() -> dict:
    """Gather stats for the dashboard from workflow_runs."""
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        repo = WorkflowRunRepository()
        runs = repo.list_runs(limit=200)

        status_counts = {}
        for r in runs:
            s = r.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        from services import ALL_HANDLERS
        handler_count = len(ALL_HANDLERS)
    except Exception as e:
        logger.warning(f"Dashboard stats failed: {e}")
        return {"active": 0, "completed": 0, "failed": 0, "handler_count": 0}

    return {
        "active": status_counts.get("running", 0) + status_counts.get("pending", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "handler_count": handler_count,
    }
