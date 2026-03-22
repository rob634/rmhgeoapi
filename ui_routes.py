# ============================================================================
# CLAUDE CONTEXT - DAG BRAIN ADMIN UI ROUTES
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: FastAPI Router - Admin UI pages for DAG Brain Docker app
# PURPOSE: Serve Jinja2-rendered admin pages mounted at /ui/ prefix
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: router
# DEPENDENCIES: fastapi, ui.templates_helper, infrastructure.jobs_tasks, services
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
async def job_list(request: Request, status: Optional[str] = None, hours: int = 24):
    """Job list with filtering."""
    from infrastructure.jobs_tasks import JobRepository
    job_repo = JobRepository()

    # Convert string status to JobStatus enum
    status_enum = None
    if status:
        from core.models.enums import JobStatus
        try:
            status_enum = JobStatus(status)
        except ValueError:
            pass

    jobs_raw = job_repo.list_jobs_with_filters(
        status=status_enum, hours=hours, limit=50
    )

    from ui.adapters import jobs_to_dto
    jobs = jobs_to_dto(jobs_raw) if jobs_raw else []

    return render_template(
        request,
        "pages/jobs/list.html",
        jobs=jobs,
        filters={"status": status, "hours": hours},
        nav_active="/ui/jobs",
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    """Job detail with task breakdown."""
    from infrastructure.jobs_tasks import JobRepository, TaskRepository
    job_repo = JobRepository()
    task_repo = TaskRepository()

    job_raw = job_repo.get_job(job_id)
    if not job_raw:
        return HTMLResponse(f"Job {job_id} not found", status_code=404)

    tasks_raw = task_repo.get_tasks_for_job(job_id)

    from ui.adapters import job_to_dto, tasks_to_dto
    job = job_to_dto(job_raw)
    tasks = tasks_to_dto(tasks_raw) if tasks_raw else []

    return render_template(
        request,
        "pages/jobs/detail.html",
        job=job,
        tasks=tasks,
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


def _get_dashboard_stats() -> dict:
    """Gather stats for the dashboard."""
    try:
        from infrastructure.jobs_tasks import JobRepository
        job_repo = JobRepository()
        recent = job_repo.list_jobs_with_filters(hours=24, limit=200)
        statuses = [getattr(j, 'status', None) for j in (recent or [])]
        status_vals = [s.value if hasattr(s, 'value') else str(s) for s in statuses]

        from services import ALL_HANDLERS
        handler_count = len(ALL_HANDLERS)
    except Exception as e:
        logger.warning(f"Dashboard stats failed: {e}")
        return {"active": 0, "completed": 0, "failed": 0, "handler_count": 0}

    return {
        "active": sum(1 for s in status_vals if s == "processing"),
        "completed": sum(1 for s in status_vals if s == "completed"),
        "failed": sum(1 for s in status_vals if s == "failed"),
        "handler_count": handler_count,
    }
