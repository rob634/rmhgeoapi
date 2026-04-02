"""
Local UI preview server — no database, no Docker, no Azure.

Run:  python ui_preview.py
View: http://localhost:8090/ui/

Serves the DAG Brain admin UI with mock workflow run data.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Set minimal env vars before any imports
os.environ.setdefault("APP_MODE", "orchestrator")
os.environ.setdefault("ENVIRONMENT", "preview")

import uvicorn
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ui.templates_helper import render_template

# ============================================================================
# MOCK DATA
# ============================================================================

_NOW = datetime.now(timezone.utc)

MOCK_RUNS = [
    {
        "run_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6abcd",
        "workflow_name": "ingest_raster",
        "status": "completed",
        "created_at": _NOW - timedelta(hours=2),
        "started_at": _NOW - timedelta(hours=2, minutes=-1),
        "completed_at": _NOW - timedelta(hours=1, minutes=45),
        "request_id": "req_abc123def456ghi7",
    },
    {
        "run_id": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6bcde",
        "workflow_name": "ingest_vector",
        "status": "running",
        "created_at": _NOW - timedelta(minutes=10),
        "started_at": _NOW - timedelta(minutes=9),
        "completed_at": None,
        "request_id": "req_xyz789uvw012rst3",
    },
    {
        "run_id": "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6cdef",
        "workflow_name": "ingest_raster",
        "status": "failed",
        "created_at": _NOW - timedelta(hours=5),
        "started_at": _NOW - timedelta(hours=5, minutes=-1),
        "completed_at": _NOW - timedelta(hours=4, minutes=50),
        "request_id": None,
    },
    {
        "run_id": "d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2defg",
        "workflow_name": "ingest_zarr",
        "status": "awaiting_approval",
        "created_at": _NOW - timedelta(hours=1),
        "started_at": _NOW - timedelta(minutes=55),
        "completed_at": None,
        "request_id": "req_zarr456abc789de0",
    },
    {
        "run_id": "e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3efgh",
        "workflow_name": "unpublish_raster",
        "status": "pending",
        "created_at": _NOW - timedelta(minutes=2),
        "started_at": None,
        "completed_at": None,
        "request_id": None,
    },
]

MOCK_TASKS = [
    {
        "task_instance_id": "a1b2c3d4e5f6-validate",
        "task_name": "validate",
        "handler": "validate_raster",
        "status": "completed",
        "fan_out_index": None,
        "fan_out_source": None,
        "when_clause": None,
        "result_data": {"valid": True, "bands": 1, "crs": "EPSG:4326"},
        "error_details": None,
        "retry_count": 0,
        "max_retries": 3,
        "claimed_by": "worker-01:1234",
        "last_pulse": _NOW - timedelta(hours=1, minutes=50),
        "execute_after": None,
        "started_at": _NOW - timedelta(hours=2, minutes=-1),
        "completed_at": _NOW - timedelta(hours=1, minutes=55),
        "created_at": _NOW - timedelta(hours=2),
    },
    {
        "task_instance_id": "a1b2c3d4e5f6-convert",
        "task_name": "convert_to_cog",
        "handler": "convert_raster_to_cog",
        "status": "completed",
        "fan_out_index": None,
        "fan_out_source": None,
        "when_clause": None,
        "result_data": {"output_path": "silver-cogs/flood/2024/output.tif", "size_mb": 42.5},
        "error_details": None,
        "retry_count": 0,
        "max_retries": 3,
        "claimed_by": "worker-01:1234",
        "last_pulse": _NOW - timedelta(hours=1, minutes=48),
        "execute_after": None,
        "started_at": _NOW - timedelta(hours=1, minutes=55),
        "completed_at": _NOW - timedelta(hours=1, minutes=48),
        "created_at": _NOW - timedelta(hours=2),
    },
    {
        "task_instance_id": "a1b2c3d4e5f6-stac",
        "task_name": "materialize_stac",
        "handler": "stac_materialize_item",
        "status": "completed",
        "fan_out_index": None,
        "fan_out_source": None,
        "when_clause": None,
        "result_data": {"collection_id": "flood-depth", "item_id": "flood-depth_site-alpha_v1"},
        "error_details": None,
        "retry_count": 0,
        "max_retries": 3,
        "claimed_by": "worker-01:1234",
        "last_pulse": _NOW - timedelta(hours=1, minutes=46),
        "execute_after": None,
        "started_at": _NOW - timedelta(hours=1, minutes=48),
        "completed_at": _NOW - timedelta(hours=1, minutes=45),
        "created_at": _NOW - timedelta(hours=2),
    },
    {
        "task_instance_id": "a1b2c3d4e5f6-gate",
        "task_name": "approval_gate",
        "handler": "__gate__",
        "status": "waiting",
        "fan_out_index": None,
        "fan_out_source": None,
        "when_clause": None,
        "result_data": None,
        "error_details": None,
        "retry_count": 0,
        "max_retries": 0,
        "claimed_by": None,
        "last_pulse": None,
        "execute_after": None,
        "started_at": None,
        "completed_at": None,
        "created_at": _NOW - timedelta(hours=2),
    },
]

MOCK_TASK_COUNTS = {"completed": 3, "waiting": 1}

MOCK_DEFINITION = {
    "workflow": "process_raster",
    "nodes": {
        "download_source": {"type": "task", "handler": "raster_download_source", "depends_on": []},
        "validate": {"type": "task", "handler": "raster_validate_atomic", "depends_on": ["download_source"]},
        "route_by_size": {
            "type": "conditional",
            "depends_on": ["validate"],
            "condition": "download_source.result.file_size_bytes",
            "branches": [
                {"name": "large", "condition": "gt 2000000000", "default": False, "next": ["generate_tiling_scheme"]},
                {"name": "standard", "default": True, "next": ["create_single_cog"]},
            ],
        },
        "create_single_cog": {"type": "task", "handler": "raster_create_cog_atomic", "depends_on": []},
        "upload_single_cog": {"type": "task", "handler": "raster_upload_cog", "depends_on": ["create_single_cog"]},
        "persist_single": {"type": "task", "handler": "raster_persist_app_tables", "depends_on": ["upload_single_cog"]},
        "generate_tiling_scheme": {"type": "task", "handler": "raster_generate_tiling_scheme_atomic", "depends_on": []},
        "process_tiles": {
            "type": "fan_out",
            "depends_on": ["generate_tiling_scheme"],
            "source": "generate_tiling_scheme.result.tile_specs",
            "task": {"handler": "raster_process_single_tile", "params": {}},
        },
        "aggregate_tiles": {"type": "fan_in", "depends_on": ["process_tiles"], "aggregation": "collect"},
        "persist_tiled": {"type": "task", "handler": "raster_persist_tiled", "depends_on": ["aggregate_tiles"]},
        "approval_gate": {"type": "gate", "depends_on": ["persist_single?", "persist_tiled?"], "gate_type": "approval"},
        "materialize_single_item": {"type": "task", "handler": "stac_materialize_item", "depends_on": ["approval_gate"]},
        "materialize_collection": {"type": "task", "handler": "stac_materialize_collection", "depends_on": ["materialize_single_item?"]},
    },
}


# Fake WorkflowRun-like object for detail page (needs attribute access)
class MockRun:
    def __init__(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)
        # Fields the detail template expects from WorkflowRun model
        if not hasattr(self, "parameters"):
            self.parameters = {"dataset_id": "flood-depth", "resource_id": "site-alpha", "container_name": "bronze-rasters", "file_name": "flood/2024/depth_100yr.tif"}
        if not hasattr(self, "result_data"):
            self.result_data = {"stac_item_id": "flood-depth_site-alpha_v1", "collection_id": "flood-depth"}
        if not hasattr(self, "platform_version"):
            self.platform_version = "0.10.9.9"
        if not hasattr(self, "asset_id"):
            self.asset_id = "asset_abc123def456"
        if not hasattr(self, "release_id"):
            self.release_id = None
        if not hasattr(self, "schedule_id"):
            self.schedule_id = None
        if not hasattr(self, "definition"):
            self.definition = {}
        if not hasattr(self, "legacy_job_id"):
            self.legacy_job_id = None

    class status_proxy:
        """Mimics enum with .value attribute."""
        def __init__(self, val):
            self.value = val
        def __str__(self):
            return self.value


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(title="UI Preview")

# Static files
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# UI routes
router = APIRouter(prefix="/ui", tags=["preview"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    status_counts = {}
    for r in MOCK_RUNS:
        s = r["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    stats = {
        "active": status_counts.get("running", 0) + status_counts.get("pending", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "handler_count": 57,
    }
    return render_template(request, "pages/dashboard.html", stats=stats, nav_active="/ui/")


@router.get("/jobs", response_class=HTMLResponse)
async def job_list(request: Request, status: Optional[str] = None):
    runs = MOCK_RUNS
    if status:
        runs = [r for r in runs if r["status"] == status]

    status_counts = {}
    for r in runs:
        s = r["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    stats = {
        "total": len(runs),
        "running": status_counts.get("running", 0),
        "completed": status_counts.get("completed", 0),
        "failed": status_counts.get("failed", 0),
        "awaiting_approval": status_counts.get("awaiting_approval", 0),
    }
    return render_template(
        request, "pages/jobs/list.html",
        jobs=runs, stats=stats, filters={"status": status}, nav_active="/ui/jobs",
    )


@router.get("/jobs/{run_id}", response_class=HTMLResponse)
async def job_detail(request: Request, run_id: str):
    run_data = next((r for r in MOCK_RUNS if r["run_id"] == run_id), MOCK_RUNS[0])

    run = MockRun(run_data)
    run.status = MockRun.status_proxy(run_data["status"])
    run.definition = MOCK_DEFINITION

    # Build DAG graph with mock statuses
    from ui.dag_graph import definition_to_graph
    task_statuses = {t["task_name"]: t["status"] for t in MOCK_TASKS}
    dag_graph = definition_to_graph(MOCK_DEFINITION, task_statuses=task_statuses)

    return render_template(
        request, "pages/jobs/detail.html",
        job=run, tasks=MOCK_TASKS, task_counts=MOCK_TASK_COUNTS,
        dag_graph=dag_graph, nav_active="/ui/jobs",
    )


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    return render_template(request, "pages/admin/health.html", nav_active="/ui/health")


@router.get("/handlers", response_class=HTMLResponse)
async def handlers_page(request: Request):
    mock_handlers = [
        "convert_raster_to_cog", "download_to_mount", "ingest_vector_to_postgis",
        "stac_materialize_item", "stac_dematerialize_item", "validate_raster",
        "validate_vector", "zarr_cloud_passthrough", "approval_gate",
    ]
    return render_template(request, "pages/handlers.html", handlers=mock_handlers, nav_active="/ui/handlers")


@router.get("/submit", response_class=HTMLResponse)
async def submit_page(request: Request):
    return render_template(request, "pages/submit.html", nav_active="/ui/submit")


@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request):
    return render_template(request, "pages/assets.html", nav_active="/ui/assets")


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail_page(request: Request, asset_id: str):
    return render_template(request, "pages/asset_detail.html", asset_id=asset_id, nav_active="/ui/assets")


# Stub API endpoints so JS fetch calls don't 404
@router.get("/api/assets/stats")
async def stub_asset_stats():
    return JSONResponse({"success": True, "stats": {"pending_review": 2, "approved": 5, "rejected": 1, "revoked": 0}, "total": 8})


@router.get("/api/assets/by-state")
async def stub_assets_by_state(state: str = "all"):
    return JSONResponse({"success": True, "releases": [], "count": 0})


@router.get("/api/assets/{asset_id}")
async def stub_asset_detail(asset_id: str):
    return JSONResponse({"success": False, "error": "Preview mode — no database"}, status_code=503)


app.include_router(router)


@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/ui/")


if __name__ == "__main__":
    print("\n  DAG Brain UI Preview")
    print("  http://localhost:8090/ui/\n")
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="warning")
