"""
Job Health Monitor Timer Trigger.

Detects jobs with failed tasks and propagates failure upward.

Exports:
    job_health_handler: Timer trigger function (runs every 10 minutes)
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
