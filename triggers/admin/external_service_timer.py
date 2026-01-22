# ============================================================================
# EXTERNAL SERVICE HEALTH TIMER
# ============================================================================
# STATUS: Trigger layer - Timer handler for external service health checks
# PURPOSE: Periodic health monitoring of registered external geospatial services
# CREATED: 22 JAN 2026
# EXPORTS: ExternalServiceHealthTimerHandler, external_service_health_timer_handler
# ============================================================================
"""
External Service Health Timer - Periodic Health Monitoring.

Timer trigger that runs hourly to check health of registered external
geospatial services and send notifications for status changes.

Schedule: Every hour at minute 0 (0 0 * * * *)

Behavior:
- Queries services where next_check_at <= NOW() AND enabled = true
- Performs service-type-specific health checks
- Updates status, consecutive_failures, health_history
- Sends notifications for outages and recoveries
- Schedules next check based on check_interval_minutes

Exports:
    ExternalServiceHealthTimerHandler: Timer handler class
    external_service_health_timer_handler: Singleton instance
"""

from typing import Dict, Any

from triggers.timer_base import TimerHandlerBase


class ExternalServiceHealthTimerHandler(TimerHandlerBase):
    """
    Timer handler for external service health checks.

    Runs hourly to check all services that are due for health checking.
    Reports outages via Application Insights and Service Bus.
    """

    name = "ExternalServiceHealth"

    def execute(self) -> Dict[str, Any]:
        """
        Execute health checks for services due for checking.

        Returns:
            Dict with:
            - success: bool
            - health_status: str
            - summary: dict with counts
            - services_checked: list of results
        """
        try:
            from services.external_service_health import ExternalServiceHealthService

            service = ExternalServiceHealthService()

            # Check all services due
            results = service.check_all_due(limit=50)

            # Aggregate results
            total_checked = len(results)
            successful = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)
            notifications = sum(1 for r in results if r.triggered_notification)

            # Count by status
            status_counts = {}
            for r in results:
                status = r.status_after.value
                status_counts[status] = status_counts.get(status, 0) + 1

            # Get overall stats
            stats = service.get_stats()

            # Determine health status
            if total_checked == 0:
                health_status = "NO_SERVICES"
            elif failed == 0:
                health_status = "HEALTHY"
            elif failed < total_checked:
                health_status = "ISSUES_DETECTED"
            else:
                health_status = "ALL_FAILED"

            return {
                "success": True,
                "health_status": health_status,
                "summary": {
                    "services_checked": total_checked,
                    "successful": successful,
                    "failed": failed,
                    "notifications_sent": notifications,
                    "total_registered": stats.get("total_services", 0),
                    "total_active": stats.get("by_status", {}).get("active", 0),
                    "total_offline": stats.get("by_status", {}).get("offline", 0),
                },
                "status_distribution": status_counts,
                "services_checked": [
                    {
                        "service_id": r.service_id,
                        "success": r.success,
                        "response_ms": r.response_ms,
                        "error": r.error,
                        "status_before": r.status_before.value,
                        "status_after": r.status_after.value,
                        "triggered_notification": r.triggered_notification
                    }
                    for r in results
                ]
            }

        except Exception as e:
            self.logger.error(f"Health check execution failed: {e}")
            return {
                "success": False,
                "health_status": "ERROR",
                "error": str(e)
            }


# Singleton instance for function_app.py to use
external_service_health_timer_handler = ExternalServiceHealthTimerHandler()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'ExternalServiceHealthTimerHandler',
    'external_service_health_timer_handler',
]
