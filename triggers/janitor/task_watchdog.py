# ============================================================================
# TASK WATCHDOG TIMER TRIGGER
# ============================================================================
# STATUS: Trigger layer - Timer trigger (every 5 minutes)
# PURPOSE: Detect and mark stale PROCESSING tasks as FAILED
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: task_watchdog_handler
# DEPENDENCIES: services.janitor_service
# ============================================================================
"""
Task Watchdog Timer Trigger.

Detects and marks stale PROCESSING tasks as FAILED.

Exports:
    task_watchdog_handler: Timer trigger function (runs every 5 minutes)
"""

import azure.functions as func
import logging
from datetime import datetime, timezone

from services.janitor_service import JanitorService
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "TaskWatchdog")


def task_watchdog_handler(timer: func.TimerRequest) -> None:
    """
    Timer trigger handler for task watchdog.

    Detects and marks stale PROCESSING tasks as FAILED.

    Args:
        timer: Azure Functions timer request
    """
    trigger_time = datetime.now(timezone.utc)

    # Check if timer is past due (ran late)
    if timer.past_due:
        logger.warning("Task watchdog timer is past due - running immediately")

    logger.info(f"Task watchdog triggered at {trigger_time.isoformat()}")

    try:
        # Run task watchdog
        service = JanitorService()
        result = service.run_task_watchdog()

        # Log results
        if result.success:
            if result.items_fixed > 0:
                logger.warning(
                    f"Task watchdog completed: found {result.items_scanned} stale tasks, "
                    f"marked {result.items_fixed} as FAILED"
                )
            else:
                logger.info(
                    f"Task watchdog completed: no stale tasks found "
                    f"(scanned {result.items_scanned})"
                )
        else:
            logger.error(f"Task watchdog failed: {result.error}")

    except Exception as e:
        logger.error(f"Task watchdog unhandled exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
