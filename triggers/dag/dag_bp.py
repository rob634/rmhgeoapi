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
Schedule CRUD endpoints for cron-based workflow submission.
No B2B contract, no backward compatibility concerns. Admin-only (APP_MODE gated).

Routes:
    GET  /api/dag/runs                              — list runs (filter by status, limit)
    GET  /api/dag/runs/{run_id}                     — single run with task summary
    GET  /api/dag/runs/{run_id}/tasks               — all tasks for a run
    POST /api/dag/submit/{workflow_name}             — direct DAG workflow submission
    POST /api/dag/test/handler/{handler_name}        — invoke handler directly (runs on Function App)
    POST /api/dag/test/node/{handler_name}           — invoke handler via full DAG path (runs on Docker worker)
    GET  /api/dag/test/handlers                      — list all registered handlers
    POST /api/dag/schedules                          — create a cron schedule
    GET  /api/dag/schedules                          — list all schedules
    GET  /api/dag/schedules/{schedule_id}            — get single schedule
    PUT  /api/dag/schedules/{schedule_id}            — update schedule fields
    DELETE /api/dag/schedules/{schedule_id}          — delete schedule
    POST /api/dag/schedules/{schedule_id}/trigger    — fire schedule immediately
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

        from psycopg import sql as psql

        # Build query with sql.SQL composition (Standard 1.2)
        fragments = [
            psql.SQL("SELECT run_id, workflow_name, status, "
                     "created_at, started_at, completed_at, request_id "
                     "FROM {}.{}").format(
                psql.Identifier("app"), psql.Identifier("workflow_runs")
            )
        ]
        params = []

        conditions = []
        if status_filter:
            conditions.append(psql.SQL("status = %s"))
            params.append(status_filter)
        if workflow_filter:
            conditions.append(psql.SQL("workflow_name = %s"))
            params.append(workflow_filter)

        if conditions:
            fragments.append(psql.SQL("WHERE ") + psql.SQL(" AND ").join(conditions))

        fragments.append(psql.SQL("ORDER BY created_at DESC LIMIT %s"))
        params.append(limit)

        query = psql.SQL(" ").join(fragments)

        from infrastructure.db_auth import ManagedIdentityAuth
        from infrastructure.db_connections import ConnectionManager

        cm = ConnectionManager(ManagedIdentityAuth())
        with cm.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
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

        from psycopg import sql as psql
        from infrastructure.db_auth import ManagedIdentityAuth
        from infrastructure.db_connections import ConnectionManager

        cm = ConnectionManager(ManagedIdentityAuth())

        # Fetch task status counts
        count_query = psql.SQL(
            "SELECT status, COUNT(*) as count "
            "FROM {}.{} WHERE run_id = %s "
            "GROUP BY status"
        ).format(psql.Identifier("app"), psql.Identifier("workflow_tasks"))

        with cm.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(count_query, (run_id,))
                status_rows = cur.fetchall()

        task_counts = {row["status"]: row["count"] for row in status_rows}
        total_tasks = sum(task_counts.values())

        # Identify currently active tasks
        active_query = psql.SQL(
            "SELECT task_name, handler, status, fan_out_index "
            "FROM {}.{} WHERE run_id = %s "
            "AND status IN ('ready', 'running') "
            "ORDER BY task_name"
        ).format(psql.Identifier("app"), psql.Identifier("workflow_tasks"))

        with cm.get_connection() as conn:
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

        from psycopg import sql as psql
        from infrastructure.db_auth import ManagedIdentityAuth
        from infrastructure.db_connections import ConnectionManager

        cm = ConnectionManager(ManagedIdentityAuth())

        _task_cols = psql.SQL(
            "SELECT task_instance_id, task_name, handler, status, "
            "fan_out_index, fan_out_source, when_clause, "
            "result_data, error_details, retry_count, max_retries, "
            "claimed_by, last_pulse, execute_after, "
            "started_at, completed_at, created_at "
            "FROM {}.{}"
        ).format(psql.Identifier("app"), psql.Identifier("workflow_tasks"))

        if status_filter:
            query = _task_cols + psql.SQL(" WHERE run_id = %s AND status = %s ORDER BY created_at")
            params = (run_id, status_filter)
        else:
            query = _task_cols + psql.SQL(" WHERE run_id = %s ORDER BY created_at")
            params = (run_id,)

        with cm.get_connection() as conn:
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
            "message": f"DAG workflow '{workflow_name}' submitted. DAG Brain will pick it up.",
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

        # Run is PENDING in DB. DAG Brain's primary loop will drive it.
        return _json_response({
            "success": True,
            "run_id": run.run_id,
            "handler": handler_name,
            "workflow_name": workflow_name,
            "monitor_url": f"/api/dag/runs/{run.run_id}",
            "tasks_url": f"/api/dag/runs/{run.run_id}/tasks",
            "message": (
                f"Test node '{handler_name}' submitted. "
                f"DAG Brain will orchestrate, worker will execute. "
                f"Monitor via GET {'/api/dag/runs/' + run.run_id}"
            ),
        })

    except Exception as e:
        logger.error(f"dag_test_node error: {e}", exc_info=True)
        return _error_response(f"Failed to create test node run: {e}", status_code=500)


# ============================================================================
# POST /api/dag/schedules — Create schedule
# ============================================================================

@bp.route(route="dag/schedules", methods=["POST"])
def dag_create_schedule(req: func.HttpRequest) -> func.HttpResponse:
    """
    Create a cron-based schedule for a workflow.

    Body:
        workflow_name     (required) — registered workflow name
        cron_expression   (required) — standard 5-field cron (e.g. "0 */6 * * *")
        parameters        (optional) — workflow parameters dict, default {}
        description       (optional) — human-readable description
        max_concurrent    (optional) — max simultaneous runs, default 1

    Returns: 201 with created schedule dict, 409 if duplicate.
    """
    import hashlib
    try:
        try:
            body = req.get_json()
        except ValueError:
            return _error_response("Request body must be valid JSON")

        workflow_name = body.get("workflow_name", "").strip()
        cron_expression = body.get("cron_expression", "").strip()
        parameters = body.get("parameters", {})
        description = body.get("description")
        max_concurrent = body.get("max_concurrent", 1)

        if not workflow_name:
            return _error_response("workflow_name is required")
        if not cron_expression:
            return _error_response("cron_expression is required")

        # Validate workflow exists
        from core.workflow_registry import WorkflowRegistry
        from pathlib import Path
        workflows_dir = Path(__file__).resolve().parents[2] / "workflows"
        registry = WorkflowRegistry(workflows_dir)
        registry.load_all()
        if not registry.has(workflow_name):
            return _error_response(
                f"Unknown workflow: '{workflow_name}'", status_code=400
            )

        # Validate cron expression
        from croniter import croniter
        try:
            croniter(cron_expression)
        except (ValueError, KeyError) as e:
            return _error_response(f"Invalid cron_expression: {e}")

        # Generate deterministic schedule_id
        sorted_params = dict(sorted(parameters.items()))
        schedule_id = hashlib.sha256(
            json.dumps(
                {"workflow_name": workflow_name, "parameters": sorted_params},
                sort_keys=True,
            ).encode()
        ).hexdigest()[:16]

        from infrastructure.schedule_repository import ScheduleRepository
        repo = ScheduleRepository()

        created = repo.create(
            schedule_id=schedule_id,
            workflow_name=workflow_name,
            cron_expression=cron_expression,
            parameters=parameters,
            description=description,
            max_concurrent=max_concurrent,
        )
        if created is None:
            return _error_response(
                f"Schedule already exists: {schedule_id}", status_code=409
            )

        return _json_response(created, status_code=201)

    except Exception as e:
        logger.error(f"dag_create_schedule error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# GET /api/dag/schedules — List schedules
# ============================================================================

@bp.route(route="dag/schedules", methods=["GET"])
def dag_list_schedules(req: func.HttpRequest) -> func.HttpResponse:
    """
    List all cron schedules with optional status filter.

    Query params:
        status: Filter by schedule status (active, paused, disabled)

    Returns: 200 with list of schedule dicts, each including next_run_at.
    """
    try:
        from croniter import croniter
        from infrastructure.schedule_repository import ScheduleRepository

        status_filter = req.params.get("status", "").strip() or None
        repo = ScheduleRepository()
        schedules = repo.list_all(status=status_filter)

        now = datetime.now(timezone.utc)
        for schedule in schedules:
            try:
                cron = croniter(schedule["cron_expression"], now)
                schedule["next_run_at"] = cron.get_next(datetime).isoformat()
            except Exception:
                schedule["next_run_at"] = None

        return _json_response({"count": len(schedules), "schedules": schedules})

    except Exception as e:
        logger.error(f"dag_list_schedules error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# GET /api/dag/schedules/{schedule_id} — Get single schedule
# ============================================================================

@bp.route(route="dag/schedules/{schedule_id}", methods=["GET"])
def dag_get_schedule(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get a single schedule by ID, including next_run_at and recent runs.

    Returns: 200 with schedule dict, 404 if not found.
    """
    try:
        from croniter import croniter
        from infrastructure.schedule_repository import ScheduleRepository
        from psycopg.rows import dict_row

        schedule_id = req.route_params.get("schedule_id", "").strip()
        if not schedule_id:
            return _error_response("schedule_id is required")

        repo = ScheduleRepository()
        schedule = repo.get_by_id(schedule_id)
        if schedule is None:
            return _error_response(f"Schedule not found: {schedule_id}", status_code=404)

        # Compute next_run_at
        now = datetime.now(timezone.utc)
        try:
            cron = croniter(schedule["cron_expression"], now)
            schedule["next_run_at"] = cron.get_next(datetime).isoformat()
        except Exception:
            schedule["next_run_at"] = None

        # Fetch recent runs
        from psycopg import sql as psql
        from infrastructure.db_auth import ManagedIdentityAuth
        from infrastructure.db_connections import ConnectionManager

        recent_query = psql.SQL(
            "SELECT run_id, status, created_at, completed_at "
            "FROM {}.{} WHERE schedule_id = %s "
            "ORDER BY created_at DESC LIMIT 5"
        ).format(psql.Identifier("app"), psql.Identifier("workflow_runs"))

        cm = ConnectionManager(ManagedIdentityAuth())
        with cm.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(recent_query, (schedule_id,))
                recent_rows = cur.fetchall()

        schedule["recent_runs"] = [dict(row) for row in recent_rows]

        return _json_response(schedule)

    except Exception as e:
        logger.error(f"dag_get_schedule error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# PUT /api/dag/schedules/{schedule_id} — Update schedule
# ============================================================================

@bp.route(route="dag/schedules/{schedule_id}", methods=["PUT"])
def dag_update_schedule(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update updatable fields on an existing schedule.

    Body (all optional):
        cron_expression   — new cron string (validated before save)
        description       — human-readable description
        status            — lifecycle status (active, paused, disabled)
        max_concurrent    — max simultaneous runs

    Returns: 200 with updated schedule dict, 404 if not found.
    """
    try:
        schedule_id = req.route_params.get("schedule_id", "").strip()
        if not schedule_id:
            return _error_response("schedule_id is required")

        try:
            body = req.get_json()
        except ValueError:
            return _error_response("Request body must be valid JSON")

        updatable = ("cron_expression", "description", "status", "max_concurrent")
        fields = {k: body[k] for k in updatable if k in body}

        if not fields:
            return _error_response("No updatable fields provided")

        # Validate cron if present
        if "cron_expression" in fields:
            from croniter import croniter
            try:
                croniter(fields["cron_expression"])
            except (ValueError, KeyError) as e:
                return _error_response(f"Invalid cron_expression: {e}")

        from infrastructure.schedule_repository import ScheduleRepository
        repo = ScheduleRepository()
        updated = repo.update(schedule_id, **fields)
        if updated is None:
            return _error_response(f"Schedule not found: {schedule_id}", status_code=404)

        return _json_response(updated)

    except Exception as e:
        logger.error(f"dag_update_schedule error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# DELETE /api/dag/schedules/{schedule_id} — Delete schedule
# ============================================================================

@bp.route(route="dag/schedules/{schedule_id}", methods=["DELETE"])
def dag_delete_schedule(req: func.HttpRequest) -> func.HttpResponse:
    """
    Delete a schedule by ID.

    Returns: 200 with {"deleted": schedule_id}, 404 if not found.
    """
    try:
        from infrastructure.schedule_repository import ScheduleRepository

        schedule_id = req.route_params.get("schedule_id", "").strip()
        if not schedule_id:
            return _error_response("schedule_id is required")

        repo = ScheduleRepository()
        deleted = repo.delete(schedule_id)
        if not deleted:
            return _error_response(f"Schedule not found: {schedule_id}", status_code=404)

        return _json_response({"deleted": schedule_id})

    except Exception as e:
        logger.error(f"dag_delete_schedule error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)


# ============================================================================
# POST /api/dag/schedules/{schedule_id}/trigger — Fire immediately
# ============================================================================

@bp.route(route="dag/schedules/{schedule_id}/trigger", methods=["POST"])
def dag_trigger_schedule(req: func.HttpRequest) -> func.HttpResponse:
    """
    Fire a scheduled workflow immediately, outside its cron cadence.

    Fetches the schedule's workflow_name and parameters, submits a run,
    and records the run against the schedule.

    Returns: 200 with {"triggered": schedule_id, "run_id": run_id}, 404 if not found.
    """
    try:
        from infrastructure.schedule_repository import ScheduleRepository

        schedule_id = req.route_params.get("schedule_id", "").strip()
        if not schedule_id:
            return _error_response("schedule_id is required")

        repo = ScheduleRepository()
        schedule = repo.get_by_id(schedule_id)
        if schedule is None:
            return _error_response(f"Schedule not found: {schedule_id}", status_code=404)

        workflow_name = schedule["workflow_name"]
        parameters = schedule.get("parameters") or {}

        from services.platform_job_submit import create_and_submit_dag_run
        run_id = create_and_submit_dag_run(
            job_type=workflow_name,
            parameters=parameters,
            platform_request_id=f"sched-trigger-{schedule_id}-{uuid4().hex[:8]}",
        )

        repo.record_run(schedule_id, run_id)

        return _json_response({"triggered": schedule_id, "run_id": run_id})

    except ValueError as e:
        return _error_response(str(e), status_code=400)
    except Exception as e:
        logger.error(f"dag_trigger_schedule error: {e}", exc_info=True)
        return _error_response("Internal error. Check server logs.", status_code=500)
