# ============================================================================
# SYSTEM GUARDIAN TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger - SystemGuardian timer handler
# PURPOSE: Single 5-minute timer trigger for distributed systems recovery
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: system_guardian_handler
# DEPENDENCIES: system_guardian, guardian_repository, service_bus
# ============================================================================
"""
SystemGuardian Timer Trigger.

Single trigger replaces task_watchdog, job_health, and orphan_detector.
Runs sweep() which executes 4 ordered phases.
"""

import logging
from datetime import datetime, timezone

import azure.functions as func

logger = logging.getLogger(__name__)


def _build_guardian():
    """Construct SystemGuardian with repository and queue client."""
    from services.system_guardian import SystemGuardian, GuardianConfig
    from infrastructure.guardian_repository import GuardianRepository
    from infrastructure.service_bus import ServiceBusRepository

    repo = GuardianRepository()
    queue = ServiceBusRepository()
    config = GuardianConfig.from_environment()
    return SystemGuardian(repo, queue, config)


def system_guardian_handler(timer: func.TimerRequest) -> None:
    """Timer trigger handler for SystemGuardian sweep."""
    trigger_time = datetime.now(timezone.utc)

    if timer.past_due:
        logger.warning("[GUARDIAN] Timer is past due — running immediately")

    logger.info(f"[GUARDIAN] Sweep triggered at {trigger_time.isoformat()}")

    try:
        guardian = _build_guardian()
        result = guardian.sweep()

        if result.total_fixed > 0:
            logger.warning(
                f"[GUARDIAN] Sweep {result.sweep_id[:8]}: "
                f"scanned={result.total_scanned} fixed={result.total_fixed}"
            )
        else:
            logger.info(
                f"[GUARDIAN] Sweep {result.sweep_id[:8]}: clean (no anomalies)"
            )

    except Exception as e:
        logger.error(f"[GUARDIAN] Sweep unhandled exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
