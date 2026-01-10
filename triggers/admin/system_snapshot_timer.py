# ============================================================================
# SYSTEM SNAPSHOT TIMER HANDLER
# ============================================================================
# STATUS: Trigger layer - Timer trigger handler for system configuration snapshots
# PURPOSE: Capture system configuration and detect drift
# CREATED: 09 JAN 2026 (Extracted from function_app.py for DRY)
# SCHEDULE: Every hour on the hour
# ============================================================================
"""
System Snapshot Timer Handler.

Timer trigger handler for capturing system configuration snapshots and
detecting configuration drift. Uses TimerHandlerBase for consistent
logging and error handling.

Captures:
- Network/VNet settings
- Instance info
- Config sources
- Environment variables

Compares to previous snapshot and logs if configuration drift is detected.

Usage:
    # In function_app.py:
    from triggers.admin.system_snapshot_timer import system_snapshot_timer_handler

    @app.timer_trigger(schedule="0 0 * * * *", ...)
    def system_snapshot_timer(timer: func.TimerRequest) -> None:
        system_snapshot_timer_handler.handle(timer)

Exports:
    SystemSnapshotTimerHandler: Handler class
    system_snapshot_timer_handler: Singleton instance
"""

from typing import Dict, Any

from triggers.timer_base import TimerHandlerBase


class SystemSnapshotTimerHandler(TimerHandlerBase):
    """
    Timer handler for system configuration snapshots.

    Wraps snapshot_service.capture_scheduled_snapshot() with standard
    timer handling patterns. Adds drift detection logging.
    """

    name = "SystemSnapshot"

    def execute(self) -> Dict[str, Any]:
        """
        Execute system snapshot capture.

        Returns:
            Result dict from snapshot_service with health_status added
        """
        from services.snapshot_service import snapshot_service

        result = snapshot_service.capture_scheduled_snapshot()

        # Map result to standard format for base class logging
        if result.get("success"):
            # Determine health status based on drift
            if result.get("has_drift"):
                result["health_status"] = "DRIFT_DETECTED"
                # Log drift warning explicitly (in addition to base class logging)
                self.logger.warning(
                    f"⚠️ DRIFT DETECTED: Configuration changed since last snapshot! "
                    f"snapshot_id={result.get('snapshot_id')}"
                )
            else:
                result["health_status"] = "HEALTHY"

            # Build summary for logging
            result["summary"] = {
                "snapshot_id": result.get("snapshot_id"),
                "has_drift": result.get("has_drift", False),
            }

        return result


# Singleton instance
system_snapshot_timer_handler = SystemSnapshotTimerHandler()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['SystemSnapshotTimerHandler', 'system_snapshot_timer_handler']
