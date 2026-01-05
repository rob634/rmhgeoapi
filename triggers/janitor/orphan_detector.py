# ============================================================================
# ORPHAN DETECTOR TIMER TRIGGER
# ============================================================================
# STATUS: Trigger layer - Timer trigger (every 15 minutes)
# PURPOSE: Detect orphaned tasks, zombie jobs, and ancient stale records
# LAST_REVIEWED: 05 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: orphan_detector_handler
# DEPENDENCIES: services.janitor_service
# ============================================================================
"""
Orphan Detector Timer Trigger.

Detects and handles orphaned tasks, zombie jobs, and ancient stale records.

Exports:
    orphan_detector_handler: Timer trigger function (runs every 15 minutes)
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
