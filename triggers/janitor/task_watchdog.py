# ============================================================================
# CLAUDE CONTEXT - TASK WATCHDOG TIMER TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Timer Trigger - Stale task detection
# PURPOSE: Detect and mark stale PROCESSING tasks as FAILED
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: task_watchdog_handler
# DEPENDENCIES: services.janitor_service, azure.functions
# SCHEDULE: Every 5 minutes (0 */5 * * * *)
# ============================================================================

"""
Task Watchdog Timer Trigger

Runs every 5 minutes to detect tasks stuck in PROCESSING state.

Azure Functions have a maximum execution time of 10-30 minutes depending
on the plan. A task that has been in PROCESSING state for longer than
30 minutes has silently failed (function timeout, uncaught exception, etc).

This trigger:
1. Queries for tasks with status=PROCESSING and updated_at > 30 min ago
2. Marks them as FAILED with descriptive error message
3. Logs the action to janitor_runs audit table

WHY 30 MINUTES?
- Consumption plan: 10 min max
- Premium plan: 30 min default, can be extended
- Dedicated plan: 30 min default, can be extended
- 30 minutes is a safe upper bound for any Azure Functions plan
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
