# ============================================================================
# CLAUDE CONTEXT - DAG DIAGNOSTIC ENDPOINTS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Trigger layer - Blueprint for /api/dag/* diagnostic routes
# PURPOSE: Read-only endpoints for inspecting DAG workflow runs and tasks.
#          Temporary home in Function App until Epoch 5 fully replaces Epoch 4.
#          Completely separate from platform/* (Epoch 4) — no fallback behavior.
# LAST_REVIEWED: 17 MAR 2026
# EXPORTS: bp (Blueprint)
# DEPENDENCIES: azure.functions, infrastructure.workflow_run_repository
# ============================================================================
"""
DAG Diagnostic Blueprint — /api/dag/* routes.

Three read-only endpoints for operator/developer inspection of DAG workflow
runs and tasks. No B2B contract, no backward compatibility concerns.

Routes:
    GET /api/dag/runs                    — list runs (filter by status, limit)
    GET /api/dag/runs/{run_id}           — single run with task summary
    GET /api/dag/runs/{run_id}/tasks     — all tasks for a run
"""

import azure.functions as func
from azure.functions import Blueprint
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

bp = Blueprint()


def _json_response(data, status_code=200):
    """Build a JSON HttpResponse."""
    return func.HttpResponse(
        body=json.dumps(data, default=str),
        mimetype="application/json",
        status_code=status_code,
    )


def _error_response(message, status_code=400):
    """Build an error JSON HttpResponse."""
    return _json_response({"error": message}, status_code=status_code)


# ============================================================================
# GET /api/dag/runs — List runs
# ============================================================================

@bp.route(route="dag/runs", methods=["GET"])
def dag_list_runs(req: func.HttpRequest) -> func.HttpResponse:
    """
    List DAG workflow runs with optional status filter.

    Query params:
        status: Filter by WorkflowRunStatus (pending, running, completed, failed)
        limit: Max results (default 50, max 200)
        workflow: Filter by workflow_name

    Returns: JSON array of run summaries.
    """
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        from psycopg import sql
        from psycopg.rows import dict_row

        status_filter = req.params.get('status', '').lower()
        workflow_filter = req.params.get('workflow', '')
        limit = min(int(req.params.get('limit', '50')), 200)

        repo = WorkflowRunRepository()

        # Build query dynamically
        conditions = []
        params = []

        if status_filter:
            conditions.append("status = %s")
            params.append(status_filter)
        if workflow_filter:
            conditions.append("workflow_name = %s")
            params.append(workflow_filter)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        query_str = (
            f"SELECT run_id, workflow_name, status, "
            f"created_at, started_at, completed_at, request_id "
            f"FROM app.workflow_runs {where_clause} "
            f"ORDER BY created_at DESC LIMIT %s"
        )

        with repo._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query_str, params)
                rows = cur.fetchall()

        runs = []
        for row in rows:
            runs.append({
                "run_id": row["run_id"],
                "workflow_name": row["workflow_name"],
                "status": row["status"],
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "request_id": row["request_id"],
            })

        return _json_response({
            "count": len(runs),
            "runs": runs,
        })

    except Exception as e:
        logger.error(f"dag_list_runs error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# GET /api/dag/runs/{run_id} — Single run with task summary
# ============================================================================

@bp.route(route="dag/runs/{run_id}", methods=["GET"])
def dag_get_run(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a single DAG workflow run with task status summary.

    Returns: Run details + task counts by status.
    """
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        from psycopg.rows import dict_row

        run_id = req.route_params.get('run_id', '')
        if not run_id:
            return _error_response("run_id is required")

        repo = WorkflowRunRepository()

        # Fetch run
        run = repo.get_by_run_id(run_id)
        if run is None:
            return _error_response(f"Run not found: {run_id}", status_code=404)

        # Fetch task status counts
        count_query = (
            "SELECT status, COUNT(*) as count "
            "FROM app.workflow_tasks WHERE run_id = %s "
            "GROUP BY status"
        )
        with repo._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(count_query, (run_id,))
                status_rows = cur.fetchall()

        task_counts = {row["status"]: row["count"] for row in status_rows}
        total_tasks = sum(task_counts.values())

        # Identify currently active tasks
        active_query = (
            "SELECT task_name, handler, status, fan_out_index "
            "FROM app.workflow_tasks WHERE run_id = %s "
            "AND status IN ('ready', 'running') "
            "ORDER BY task_name"
        )
        with repo._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(active_query, (run_id,))
                active_rows = cur.fetchall()

        active_tasks = [
            {
                "task_name": row["task_name"],
                "handler": row["handler"],
                "status": row["status"],
                "fan_out_index": row["fan_out_index"],
            }
            for row in active_rows
        ]

        return _json_response({
            "run_id": run.run_id,
            "workflow_name": run.workflow_name,
            "status": run.status.value,
            "parameters": run.parameters,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "request_id": run.request_id,
            "asset_id": run.asset_id,
            "release_id": run.release_id,
            "task_summary": {
                "total": total_tasks,
                "by_status": task_counts,
            },
            "active_tasks": active_tasks,
        })

    except Exception as e:
        logger.error(f"dag_get_run error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# GET /api/dag/runs/{run_id}/tasks — All tasks for a run
# ============================================================================

@bp.route(route="dag/runs/{run_id}/tasks", methods=["GET"])
def dag_get_run_tasks(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get all tasks for a DAG workflow run.

    Query params:
        status: Filter by task status (optional)

    Returns: JSON array of task details.
    """
    try:
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        from psycopg.rows import dict_row

        run_id = req.route_params.get('run_id', '')
        if not run_id:
            return _error_response("run_id is required")

        status_filter = req.params.get('status', '').lower()

        repo = WorkflowRunRepository()

        # Build query
        if status_filter:
            query = (
                "SELECT task_instance_id, task_name, handler, status, "
                "fan_out_index, fan_out_source, when_clause, "
                "result_data, error_details, retry_count, max_retries, "
                "claimed_by, last_pulse, execute_after, "
                "started_at, completed_at, created_at "
                "FROM app.workflow_tasks WHERE run_id = %s AND status = %s "
                "ORDER BY created_at"
            )
            params = (run_id, status_filter)
        else:
            query = (
                "SELECT task_instance_id, task_name, handler, status, "
                "fan_out_index, fan_out_source, when_clause, "
                "result_data, error_details, retry_count, max_retries, "
                "claimed_by, last_pulse, execute_after, "
                "started_at, completed_at, created_at "
                "FROM app.workflow_tasks WHERE run_id = %s "
                "ORDER BY created_at"
            )
            params = (run_id,)

        with repo._get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        tasks = []
        for row in rows:
            tasks.append({
                "task_instance_id": row["task_instance_id"],
                "task_name": row["task_name"],
                "handler": row["handler"],
                "status": row["status"],
                "fan_out_index": row["fan_out_index"],
                "fan_out_source": row["fan_out_source"],
                "when_clause": row["when_clause"],
                "result_data": row["result_data"],
                "error_details": row["error_details"],
                "retry_count": row["retry_count"],
                "max_retries": row["max_retries"],
                "claimed_by": row["claimed_by"],
                "last_pulse": row["last_pulse"],
                "execute_after": row["execute_after"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "created_at": row["created_at"],
            })

        return _json_response({
            "run_id": run_id,
            "count": len(tasks),
            "tasks": tasks,
        })

    except Exception as e:
        logger.error(f"dag_get_run_tasks error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# POST /api/dag/submit/{workflow_name} — Direct DAG workflow submission
# ============================================================================

@bp.route(route="dag/submit/{workflow_name}", methods=["POST"])
def dag_submit_workflow(req: func.HttpRequest) -> func.HttpResponse:
    """
    Submit a DAG workflow directly by workflow_name.

    D.10: Direct DAG submission endpoint — bypasses platform translation.
    Takes workflow_name from URL and parameters from JSON body.
    Creates run via DAGInitializer, launches orchestrator in background thread.

    Returns: run_id and monitor URL.
    """
    try:
        workflow_name = req.route_params.get('workflow_name', '')
        if not workflow_name:
            return _error_response("workflow_name is required")

        try:
            body = req.get_json()
        except ValueError:
            body = {}

        from services.platform_job_submit import create_and_submit_dag_run
        run_id = create_and_submit_dag_run(
            job_type=workflow_name,
            parameters=body,
            platform_request_id=f"dag-{workflow_name}-{uuid4().hex[:8]}",
        )

        return _json_response({
            "success": True,
            "run_id": run_id,
            "workflow_name": workflow_name,
            "monitor_url": f"/api/dag/runs/{run_id}",
            "message": f"DAG workflow '{workflow_name}' submitted. Orchestrator launched.",
        })

    except ValueError as e:
        return _error_response(str(e), status_code=400)
    except Exception as e:
        logger.error(f"dag_submit_workflow error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)
