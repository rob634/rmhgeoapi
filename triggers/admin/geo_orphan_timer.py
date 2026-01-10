# ============================================================================
# GEO ORPHAN TIMER HANDLER
# ============================================================================
# STATUS: Trigger layer - Timer trigger handler for geo schema orphan detection
# PURPOSE: Detect orphaned tables and metadata in geo schema
# CREATED: 09 JAN 2026 (Extracted from function_app.py for DRY)
# SCHEDULE: Every 6 hours at minute 0
# ============================================================================
"""
Geo Orphan Timer Handler.

Timer trigger handler for detecting orphaned tables and metadata records
in the geo schema. Uses TimerHandlerBase for consistent logging and
error handling.

Detects:
1. Orphaned Tables: Tables in geo schema without metadata records
2. Orphaned Metadata: Metadata records for non-existent tables

Detection only - does NOT auto-delete. Logs findings to Application Insights.

Usage:
    # In function_app.py:
    from triggers.admin.geo_orphan_timer import geo_orphan_timer_handler

    @app.timer_trigger(schedule="0 0 */6 * * *", ...)
    def geo_orphan_check_timer(timer: func.TimerRequest) -> None:
        geo_orphan_timer_handler.handle(timer)

Exports:
    GeoOrphanTimerHandler: Handler class
    geo_orphan_timer_handler: Singleton instance
"""

from typing import Dict, Any

from triggers.timer_base import TimerHandlerBase


class GeoOrphanTimerHandler(TimerHandlerBase):
    """
    Timer handler for geo schema orphan detection.

    Wraps GeoOrphanDetector from janitor_service with standard
    timer handling patterns.
    """

    name = "GeoOrphanCheck"

    def execute(self) -> Dict[str, Any]:
        """
        Execute geo orphan detection.

        Returns:
            Result dict from GeoOrphanDetector.run()
        """
        from services.janitor_service import geo_orphan_detector

        result = geo_orphan_detector.run()

        # Ensure result has expected structure for base class logging
        if "health_status" not in result and "summary" in result:
            result["health_status"] = result["summary"].get("health_status", "UNKNOWN")

        return result


# Singleton instance
geo_orphan_timer_handler = GeoOrphanTimerHandler()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['GeoOrphanTimerHandler', 'geo_orphan_timer_handler']
