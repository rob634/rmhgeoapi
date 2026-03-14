# ============================================================================
# JANITOR HTTP TRIGGERS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger layer - /api/admin/janitor/* endpoints
# PURPOSE: Manual sweep operations and status monitoring via SystemGuardian
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: janitor_run_handler, janitor_status_handler, janitor_history_handler
# DEPENDENCIES: services.system_guardian, infrastructure.guardian_repository
# ============================================================================
"""
Janitor HTTP Triggers.

HTTP endpoints for manual maintenance operations and status monitoring.
Uses SystemGuardian for sweep operations, GuardianRepository for status/history.

Exports:
    janitor_run_handler: HTTP trigger for POST /api/admin/janitor/run
    janitor_status_handler: HTTP trigger for GET /api/admin/janitor/status
    janitor_history_handler: HTTP trigger for GET /api/admin/janitor/history
"""

import azure.functions as func
import json
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "JanitorHTTP")


def _build_guardian():
    """Construct SystemGuardian with repository and queue client."""
    from services.system_guardian import SystemGuardian, GuardianConfig
    from infrastructure.guardian_repository import GuardianRepository
    from infrastructure.service_bus import ServiceBusRepository

    repo = GuardianRepository()
    queue = ServiceBusRepository()
    config = GuardianConfig.from_environment()
    return SystemGuardian(repo, queue, config)


def _build_repo():
    """Construct GuardianRepository for status/history queries."""
    from infrastructure.guardian_repository import GuardianRepository
    return GuardianRepository()


# Legacy types that now map to a full sweep
_LEGACY_SWEEP_TYPES = {"task_watchdog", "job_health", "orphan_detector"}


def janitor_run_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manually trigger a maintenance run.

    POST /api/admin/janitor/run?type={sweep|task_watchdog|job_health|orphan_detector|metadata_consistency|log_cleanup|queue_depth_snapshot|all}

    Query Parameters:
        type: Which operation to run (required)
            - sweep: Run SystemGuardian 4-phase sweep
            - task_watchdog: DEPRECATED — maps to sweep
            - job_health: DEPRECATED — maps to sweep
            - orphan_detector: DEPRECATED — maps to sweep
            - metadata_consistency: Unified metadata validation
            - log_cleanup: Clean up expired JSONL log files
            - queue_depth_snapshot: Capture queue depths for trending
            - all: Run sweep + metadata_consistency + log_cleanup + queue_depth_snapshot

    Returns:
        JSON with run results
    """
    run_type = req.params.get('type', '').lower()

    valid_types = [
        "sweep", "task_watchdog", "job_health", "orphan_detector",
        "metadata_consistency", "log_cleanup", "queue_depth_snapshot", "all"
    ]

    if not run_type:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Missing required parameter: type",
                "error_type": "ValidationError",
                "valid_types": valid_types,
                "usage": "POST /api/admin/janitor/run?type=sweep"
            }),
            status_code=400,
            mimetype="application/json"
        )

    if run_type not in valid_types:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"Invalid type: {run_type}",
                "error_type": "ValidationError",
                "valid_types": valid_types
            }),
            status_code=400,
            mimetype="application/json"
        )

    logger.info(f"Manual janitor run requested: type={run_type}")

    try:
        results = []

        # Sweep: runs for sweep, legacy types, or all
        if run_type == "sweep" or run_type in _LEGACY_SWEEP_TYPES or run_type == "all":
            if run_type in _LEGACY_SWEEP_TYPES:
                logger.warning(
                    f"[JANITOR] Deprecated type '{run_type}' — "
                    f"use 'sweep' instead. Running full SystemGuardian sweep."
                )

            guardian = _build_guardian()
            sweep_result = guardian.sweep()
            results.append({
                "run_type": "sweep",
                "success": sweep_result.success,
                "sweep_id": sweep_result.sweep_id,
                "items_scanned": sweep_result.total_scanned,
                "items_fixed": sweep_result.total_fixed,
                "phases": sweep_result.phases_dict,
                "error": sweep_result.error,
            })

        if run_type == "metadata_consistency" or run_type == "all":
            from services.metadata_consistency import get_metadata_consistency_checker
            checker = get_metadata_consistency_checker()
            result = checker.run()
            results.append(result)

        if run_type == "log_cleanup" or run_type == "all":
            from triggers.admin.log_cleanup_timer import log_cleanup_timer_handler
            result = log_cleanup_timer_handler.execute()
            results.append(result)

        if run_type == "queue_depth_snapshot" or run_type == "all":
            repo = _build_repo()
            result = repo.record_queue_depth_snapshot()
            results.append(result)

        # Summary
        total_scanned = sum(r.get('items_scanned', 0) for r in results)
        total_fixed = sum(r.get('items_fixed', 0) for r in results)
        all_success = all(r.get('success', False) for r in results)

        response = {
            "status": "success" if all_success else "partial_failure",
            "run_type": run_type,
            "summary": {
                "total_scanned": total_scanned,
                "total_fixed": total_fixed,
                "runs_completed": len(results),
                "all_success": all_success
            },
            "results": results,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "triggered_by": "http_manual"
        }

        logger.info(f"Manual janitor run complete: scanned={total_scanned}, fixed={total_fixed}")

        return func.HttpResponse(
            json.dumps(response, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Manual janitor run failed: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "InternalError",
                "run_type": run_type
            }),
            status_code=500,
            mimetype="application/json"
        )


def janitor_status_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get current guardian status and configuration.

    GET /api/admin/janitor/status

    Returns:
        JSON with configuration and recent sweep statistics
    """
    try:
        from services.system_guardian import GuardianConfig

        repo = _build_repo()
        config = GuardianConfig.from_environment()

        recent_sweeps = repo.get_recent_sweeps(hours=24, limit=10)

        total_runs = len(recent_sweeps)
        failed_runs = sum(1 for r in recent_sweeps if r.get('status') == 'failed')
        total_fixed = sum(r.get('items_fixed', 0) for r in recent_sweeps)

        response = {
            "status": "success",
            "guardian": {
                "enabled": config.enabled,
                "config": {
                    "sweep_interval_minutes": config.sweep_interval_minutes,
                    "processing_task_timeout_minutes": config.processing_task_timeout_minutes,
                    "docker_task_timeout_minutes": config.docker_task_timeout_minutes,
                    "ancient_job_timeout_minutes": config.ancient_job_timeout_minutes,
                    "max_task_retries": config.max_task_retries,
                },
                "last_24_hours": {
                    "total_sweeps": total_runs,
                    "failed_sweeps": failed_runs,
                    "total_items_fixed": total_fixed
                },
                "recent_sweeps": [
                    {
                        "run_type": r.get('run_type'),
                        "status": r.get('status'),
                        "items_scanned": r.get('items_scanned', 0),
                        "items_fixed": r.get('items_fixed', 0),
                        "phases": r.get('phases'),
                        "started_at": r.get('started_at'),
                        "duration_ms": r.get('duration_ms')
                    }
                    for r in recent_sweeps[:5]
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(response, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Failed to get guardian status: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "InternalError"
            }),
            status_code=500,
            mimetype="application/json"
        )


def janitor_history_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get recent maintenance run history.

    GET /api/admin/janitor/history?hours=24&type=sweep&limit=50

    Query Parameters:
        hours: How many hours of history (default: 24)
        type: Filter by run type (optional, e.g. 'sweep', 'queue_depth_snapshot')
        limit: Maximum records to return (default: 50)

    Returns:
        JSON with recent maintenance runs
    """
    try:
        hours = int(req.params.get('hours', '24'))
        run_type = req.params.get('type')
        limit = int(req.params.get('limit', '50'))

        # Validate
        if hours < 1 or hours > 168:  # 1 hour to 1 week
            hours = 24
        if limit < 1 or limit > 200:
            limit = 50

        repo = _build_repo()
        runs = repo.get_recent_runs(
            hours=hours,
            run_type=run_type,
            limit=limit
        )

        # Calculate statistics
        total_runs = len(runs)
        successful_runs = sum(1 for r in runs if r.get('status') == 'completed')
        failed_runs = sum(1 for r in runs if r.get('status') == 'failed')
        total_fixed = sum(r.get('items_fixed', 0) for r in runs)

        response = {
            "status": "success",
            "query": {
                "hours": hours,
                "type": run_type,
                "limit": limit
            },
            "statistics": {
                "total_runs": total_runs,
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "total_items_fixed": total_fixed
            },
            "runs": [
                {
                    "run_id": str(r.get('run_id', '')),
                    "run_type": r.get('run_type'),
                    "status": r.get('status'),
                    "items_scanned": r.get('items_scanned', 0),
                    "items_fixed": r.get('items_fixed', 0),
                    "phases": r.get('phases'),
                    "duration_ms": r.get('duration_ms'),
                    "started_at": r.get('started_at').isoformat() if r.get('started_at') else None,
                    "error_details": r.get('error_details')
                }
                for r in runs
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(response, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Failed to get maintenance history: {e}")
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": str(e),
                "error_type": "InternalError"
            }),
            status_code=500,
            mimetype="application/json"
        )


# Module exports
__all__ = [
    'janitor_run_handler',
    'janitor_status_handler',
    'janitor_history_handler'
]
