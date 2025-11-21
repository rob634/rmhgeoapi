# ============================================================================
# CLAUDE CONTEXT - JOB HEALTH MONITOR TIMER TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Timer Trigger - Job health monitoring
# PURPOSE: Detect jobs with failed tasks and propagate failure upward
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: job_health_handler
# DEPENDENCIES: services.janitor_service, azure.functions
# SCHEDULE: Every 10 minutes (0 */10 * * * *)
# ============================================================================

"""
Job Health Monitor Timer Trigger

Runs every 10 minutes to detect jobs that have failed tasks.

In the CoreMachine architecture, jobs are ATOMIC - they either fully succeed
or fully fail. If any task fails, the entire job should be marked as failed.

However, there are race conditions and edge cases where a task fails but
the "last task turns out the lights" logic doesn't properly propagate
the failure to the job level. This monitor catches those cases.

This trigger:
1. Queries for jobs with status=PROCESSING that have failed tasks
2. Marks the job as FAILED with descriptive error message
3. Captures partial results from completed tasks (for debugging)
4. Logs the action to janitor_runs audit table

WHY CAPTURE PARTIAL RESULTS?
- Jobs are atomic, but knowing what completed helps debugging
- Can identify which stage/task caused the failure
- Enables potential manual recovery if needed
"""

import azure.functions as func
import logging
from datetime import datetime, timezone

from services.janitor_service import JanitorService
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "JobHealthMonitor")


def job_health_handler(timer: func.TimerRequest) -> None:
    """
    Timer trigger handler for job health monitoring.

    Detects jobs with failed tasks and propagates failure upward.

    Args:
        timer: Azure Functions timer request
    """
    trigger_time = datetime.now(timezone.utc)

    if timer.past_due:
        logger.warning("Job health monitor timer is past due - running immediately")

    logger.info(f"Job health monitor triggered at {trigger_time.isoformat()}")

    try:
        # Run job health check
        service = JanitorService()
        result = service.run_job_health_check()

        # Log results
        if result.success:
            if result.items_fixed > 0:
                logger.warning(
                    f"Job health check completed: found {result.items_scanned} jobs with failed tasks, "
                    f"marked {result.items_fixed} jobs as FAILED"
                )
            else:
                logger.info(
                    f"Job health check completed: no jobs with failed tasks found "
                    f"(scanned {result.items_scanned})"
                )
        else:
            logger.error(f"Job health check failed: {result.error}")

    except Exception as e:
        logger.error(f"Job health monitor unhandled exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
