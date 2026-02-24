# ============================================================================
# JANITOR HTTP TRIGGERS
# ============================================================================
# STATUS: Trigger layer - /api/admin/janitor/* endpoints
# PURPOSE: Manual janitor operations and status monitoring
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: janitor_run_handler, janitor_status_handler, janitor_history_handler
# DEPENDENCIES: services.janitor_service
# ============================================================================
"""
Janitor HTTP Triggers.

HTTP endpoints for manual janitor operations and status monitoring.

Exports:
    janitor_run_handler: HTTP trigger for POST /api/admin/janitor/run
    janitor_status_handler: HTTP trigger for GET /api/admin/janitor/status
    janitor_history_handler: HTTP trigger for GET /api/admin/janitor/history
"""

import azure.functions as func
import json
from datetime import datetime, timezone
from typing import Optional

from services.janitor_service import JanitorService, JanitorConfig
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "JanitorHTTP")


def janitor_run_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Manually trigger a janitor run.

    POST /api/admin/janitor/run?type={task_watchdog|job_health|orphan_detector|metadata_consistency|log_cleanup|all}

    Query Parameters:
        type: Which janitor to run (required)
            - task_watchdog: Detect stale PROCESSING tasks
            - job_health: Detect jobs with failed tasks
            - orphan_detector: Detect orphaned/zombie records
            - metadata_consistency: Unified metadata validation (09 JAN 2026)
            - log_cleanup: Clean up expired JSONL log files (11 JAN 2026 - F7.12.F)
            - all: Run all in sequence

    Returns:
        JSON with run results
    """
    run_type = req.params.get('type', '').lower()

    if not run_type:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": "Missing required parameter: type",
                "error_type": "ValidationError",
                "valid_types": ["task_watchdog", "job_health", "orphan_detector", "metadata_consistency", "log_cleanup", "all"],
                "usage": "POST /api/admin/janitor/run?type=task_watchdog"
            }),
            status_code=400,
            mimetype="application/json"
        )

    valid_types = ["task_watchdog", "job_health", "orphan_detector", "metadata_consistency", "log_cleanup", "all"]
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
        service = JanitorService()
        results = []

        if run_type == "task_watchdog" or run_type == "all":
            result = service.run_task_watchdog()
            results.append(result.to_dict())

        if run_type == "job_health" or run_type == "all":
            result = service.run_job_health_check()
            results.append(result.to_dict())

        if run_type == "orphan_detector" or run_type == "all":
            result = service.run_orphan_detection()
            results.append(result.to_dict())

        if run_type == "metadata_consistency" or run_type == "all":
            # Metadata consistency check (09 JAN 2026 - F7.10)
            from services.metadata_consistency import get_metadata_consistency_checker
            checker = get_metadata_consistency_checker()
            result = checker.run()
            results.append(result)

        if run_type == "log_cleanup" or run_type == "all":
            # Log cleanup (11 JAN 2026 - F7.12.F)
            from triggers.admin.log_cleanup_timer import log_cleanup_timer_handler
            result = log_cleanup_timer_handler.execute()
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
    Get current janitor status and configuration.

    GET /api/admin/janitor/status

    Returns:
        JSON with configuration and recent run statistics
    """
    try:
        service = JanitorService()
        status = service.get_status()

        response = {
            "status": "success",
            "janitor": status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        return func.HttpResponse(
            json.dumps(response, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Failed to get janitor status: {e}")
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
    Get recent janitor run history.

    GET /api/admin/janitor/history?hours=24&type=task_watchdog&limit=50

    Query Parameters:
        hours: How many hours of history (default: 24)
        type: Filter by run type (optional)
        limit: Maximum records to return (default: 50)

    Returns:
        JSON with recent janitor runs
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

        service = JanitorService()
        runs = service.repo.get_recent_janitor_runs(
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
        logger.error(f"Failed to get janitor history: {e}")
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
