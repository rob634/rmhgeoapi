# ============================================================================
# CLAUDE CONTEXT - ORPHAN DETECTOR TIMER TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Timer Trigger - Orphan and zombie detection
# PURPOSE: Detect and handle orphaned tasks, zombie jobs, and ancient stale records
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: orphan_detector_handler
# DEPENDENCIES: services.janitor_service, azure.functions
# SCHEDULE: Every 15 minutes (0 */15 * * * *)
# ============================================================================

"""
Orphan Detector Timer Trigger

Runs every 15 minutes to detect orphaned tasks and zombie jobs.

This is a catch-all for edge cases that the task watchdog and job health
monitor don't cover. It handles scenarios that shouldn't happen but can
occur due to race conditions, bugs, or infrastructure failures.

Detections:
1. ORPHANED TASKS: Tasks whose parent job doesn't exist
   - Can happen if job deleted but task remained
   - Database consistency issue

2. ZOMBIE JOBS: Jobs stuck in PROCESSING but all tasks are terminal
   - Stage advancement logic failed
   - "Last task turns out the lights" didn't fire

3. STUCK QUEUED JOBS: Jobs in QUEUED state with no tasks created
   - Job processing failed before task creation
   - Service Bus message was never processed

4. ANCIENT STALE JOBS: Jobs in PROCESSING for > 24 hours
   - Something is seriously wrong
   - Even the longest jobs should complete in hours, not days

This trigger:
1. Queries for each type of anomaly
2. Marks affected records as FAILED with descriptive messages
3. Logs all actions to janitor_runs audit table
"""

import azure.functions as func
import logging
from datetime import datetime, timezone

from services.janitor_service import JanitorService
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "OrphanDetector")


def orphan_detector_handler(timer: func.TimerRequest) -> None:
    """
    Timer trigger handler for orphan detection.

    Detects and handles orphaned tasks, zombie jobs, and other edge cases.

    Args:
        timer: Azure Functions timer request
    """
    trigger_time = datetime.now(timezone.utc)

    if timer.past_due:
        logger.warning("Orphan detector timer is past due - running immediately")

    logger.info(f"Orphan detector triggered at {trigger_time.isoformat()}")

    try:
        # Run orphan detection
        service = JanitorService()
        result = service.run_orphan_detection()

        # Log results
        if result.success:
            if result.items_fixed > 0:
                logger.warning(
                    f"Orphan detection completed: scanned {result.items_scanned} records, "
                    f"fixed {result.items_fixed} anomalies"
                )

                # Log action breakdown
                action_summary = {}
                for action in result.actions_taken:
                    action_type = action.get('action', 'unknown')
                    action_summary[action_type] = action_summary.get(action_type, 0) + 1

                for action_type, count in action_summary.items():
                    logger.warning(f"  - {action_type}: {count}")
            else:
                logger.info(
                    f"Orphan detection completed: no anomalies found "
                    f"(scanned {result.items_scanned} records)"
                )
        else:
            logger.error(f"Orphan detection failed: {result.error}")

    except Exception as e:
        logger.error(f"Orphan detector unhandled exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
