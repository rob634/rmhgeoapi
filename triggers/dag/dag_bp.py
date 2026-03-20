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
DAG Blueprint — /api/dag/* routes.

Diagnostic and testing endpoints for DAG workflow runs, tasks, and handlers.
No B2B contract, no backward compatibility concerns. Admin-only (APP_MODE gated).

Routes:
    GET  /api/dag/runs                              — list runs (filter by status, limit)
    GET  /api/dag/runs/{run_id}                     — single run with task summary
    GET  /api/dag/runs/{run_id}/tasks               — all tasks for a run
    POST /api/dag/submit/{workflow_name}             — direct DAG workflow submission
    POST /api/dag/test/handler/{handler_name}        — invoke handler directly (runs on Function App)
    POST /api/dag/test/node/{handler_name}           — invoke handler via full DAG path (runs on Docker worker)
    GET  /api/dag/test/handlers                      — list all registered handlers
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


# ============================================================================
# POST /api/dag/test/handler/{handler_name} — Direct handler invocation
# ============================================================================

@bp.route(route="dag/test/handler/{handler_name}", methods=["POST"])
def dag_test_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Invoke a registered handler directly for unit testing.

    No workflow, no DAG orchestration, no DB state management.
    Calls handler(params) and returns the raw result with execution timing.
    Validates handlers work in the Azure environment (managed identity,
    blob access, PostGIS) before they're wired into workflows.

    Body:
        {
            "params": { ... handler parameters ... },
            "dry_run": false   (optional, passed to handler if present)
        }

    Returns:
        {
            "handler": "handler_name",
            "success": true/false,
            "result": { ... },
            "execution_time_ms": 1234
        }
    """
    import time
    from services import get_handler, ALL_HANDLERS

    handler_name = req.route_params.get('handler_name', '')
    if not handler_name:
        return _error_response("handler_name is required")

    # Validate handler exists before parsing body
    try:
        handler_fn = get_handler(handler_name)
    except ValueError as e:
        return _error_response(str(e), status_code=404)

    # Parse request body
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    params = body.get('params', {})
    dry_run = body.get('dry_run', False)

    if dry_run:
        params['_dry_run'] = True

    # Execute handler with timing
    start_time = time.monotonic()
    try:
        result = handler_fn(params)
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)

        handler_success = result.get('success', False) if isinstance(result, dict) else False

        return _json_response({
            "handler": handler_name,
            "success": handler_success,
            "result": result,
            "execution_time_ms": elapsed_ms,
            "dry_run": dry_run,
        })

    except Exception as e:
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 1)
        logger.error(f"dag_test_handler '{handler_name}' raised: {e}", exc_info=True)

        return _json_response({
            "handler": handler_name,
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "execution_time_ms": elapsed_ms,
            "dry_run": dry_run,
        }, status_code=200)  # 200 not 500 — handler failure is a valid test result


# ============================================================================
# GET /api/dag/test/handlers — List available handlers
# ============================================================================

@bp.route(route="dag/test/handlers", methods=["GET"])
def dag_list_handlers(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all registered handlers available for testing.

    Returns handler names grouped for quick reference.
    """
    from services import ALL_HANDLERS

    handler_names = sorted(ALL_HANDLERS.keys())

    # Group by prefix for readability
    groups = {}
    for name in handler_names:
        prefix = name.split('_')[0]
        groups.setdefault(prefix, []).append(name)

    return _json_response({
        "total": len(handler_names),
        "handlers": handler_names,
        "by_prefix": groups,
    })


# ============================================================================
# POST /api/dag/test/node/{handler_name} — Execute handler via full DAG path
# ============================================================================

@bp.route(route="dag/test/node/{handler_name}", methods=["POST"])
def dag_test_node(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unit-test a single handler through the full DAG execution path.

    Builds a single-node WorkflowDefinition programmatically, submits it
    via DAGInitializer, and launches the orchestrator. The Docker worker
    claims and executes the task on the real mount with real infrastructure.

    Unlike /api/dag/test/handler/{name} (which runs locally on the Function
    App), this endpoint proves the handler works in the Docker environment
    with mount, connection pool, and managed identity.

    Body:
        {
            "params": { ... handler parameters ... }
        }

    Returns:
        {
            "success": true,
            "run_id": "...",
            "handler": "handler_name",
            "monitor_url": "/api/dag/runs/{run_id}",
            "tasks_url": "/api/dag/runs/{run_id}/tasks"
        }
    """
    import threading

    handler_name = req.route_params.get('handler_name', '')
    if not handler_name:
        return _error_response("handler_name is required")

    # Validate handler exists
    from services import ALL_HANDLERS
    if handler_name not in ALL_HANDLERS:
        return _error_response(
            f"Unknown handler: '{handler_name}'. Available: {sorted(ALL_HANDLERS.keys())}",
            status_code=404,
        )

    # Parse request body
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    params = body.get('params', {})

    # Build a single-node WorkflowDefinition programmatically.
    # Declare each user param as a workflow parameter so the param resolver
    # can extract them for the root node. The initializer now resolves root
    # node params at creation time (no longer null).
    from core.models.workflow_definition import (
        WorkflowDefinition, TaskNode, ParameterDef,
    )

    workflow_name = f"_test_node_{handler_name}"

    # Build parameter declarations from the user's params
    param_defs = {}
    param_names = []
    for key, value in params.items():
        # Infer type from value for the ParameterDef
        if isinstance(value, bool):
            ptype = "bool"
        elif isinstance(value, int):
            ptype = "int"
        elif isinstance(value, float):
            ptype = "float"
        elif isinstance(value, dict):
            ptype = "dict"
        elif isinstance(value, list):
            ptype = "list"
        else:
            ptype = "str"
        param_defs[key] = ParameterDef(type=ptype, required=False, default=value)
        param_names.append(key)

    workflow_def = WorkflowDefinition(
        workflow=workflow_name,
        description=f"Unit test for handler '{handler_name}'",
        version=1,
        parameters=param_defs,
        nodes={
            "test": TaskNode(
                type="task",
                handler=handler_name,
                params=param_names,  # Extract these keys from job_params
            ),
        },
    )

    # Create the run via DAGInitializer (root node params resolved at init)
    try:
        from core.dag_initializer import DAGInitializer
        from infrastructure.workflow_run_repository import WorkflowRunRepository
        from config import __version__

        repo = WorkflowRunRepository()
        initializer = DAGInitializer(repo)

        run = initializer.create_run(
            workflow_def=workflow_def,
            parameters=params,  # User's params as job_params — resolver extracts them
            platform_version=__version__,
            request_id=f"test-node-{handler_name}-{uuid4().hex[:8]}",
        )

        # Launch orchestrator in background thread
        from core.dag_orchestrator import DAGOrchestrator
        orchestrator = DAGOrchestrator(repo)

        def _drive_run():
            try:
                result = orchestrator.run(run.run_id, cycle_interval=3.0)
                logger.info(
                    f"Test node orchestrator finished: run_id={run.run_id[:16]}... "
                    f"handler={handler_name} status={result.final_status.value}"
                )
            except Exception as exc:
                logger.error(f"Test node orchestrator error: {exc}", exc_info=True)

        t = threading.Thread(
            target=_drive_run,
            name=f"test-node-{run.run_id[:8]}",
            daemon=True,
        )
        t.start()

        return _json_response({
            "success": True,
            "run_id": run.run_id,
            "handler": handler_name,
            "workflow_name": workflow_name,
            "monitor_url": f"/api/dag/runs/{run.run_id}",
            "tasks_url": f"/api/dag/runs/{run.run_id}/tasks",
            "message": (
                f"Test node '{handler_name}' submitted via DAG. "
                f"Docker worker will claim and execute. "
                f"Monitor via GET {'/api/dag/runs/' + run.run_id}"
            ),
        })

    except Exception as e:
        logger.error(f"dag_test_node error: {e}", exc_info=True)
        return _error_response(f"Failed to create test node run: {e}", status_code=500)
