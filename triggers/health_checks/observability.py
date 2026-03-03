# ============================================================================
# OBSERVABILITY HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Plugin - Observability pipeline components
# PURPOSE: Metrics pipeline status, App Insights ingestion freshness
# CREATED: 03 MAR 2026
# EXPORTS: ObservabilityHealthChecks
# DEPENDENCIES: base.HealthCheckPlugin, infrastructure.metrics_blob_logger,
#               infrastructure.appinsights_exporter
# ============================================================================
"""
Observability Health Checks Plugin.

Monitors observability pipeline:
- Metrics blob logger pipeline (buffer, flush errors)
- Application Insights ingestion freshness
"""

import os
from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class ObservabilityHealthChecks(HealthCheckPlugin):
    """
    Health checks for observability infrastructure.

    Checks:
    - metrics_pipeline: Blob metrics logger status (enabled, flush errors, buffer)
    - appinsights_ingestion: App Insights data freshness (query latency)
    """

    name = "observability"
    description = "Metrics pipeline and App Insights ingestion"
    priority = 35  # After infrastructure (30), before database (40)

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return observability health checks."""
        return [
            ("metrics_pipeline", self.check_metrics_pipeline),
            ("appinsights_ingestion", self.check_appinsights_ingestion),
        ]

    def get_parallel_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """App Insights check involves HTTP — run in parallel."""
        return [
            ("appinsights_ingestion", self.check_appinsights_ingestion),
        ]

    def is_enabled(self, config) -> bool:
        """Observability checks are always enabled."""
        return True

    # =========================================================================
    # CHECK: Metrics Pipeline
    # =========================================================================

    def check_metrics_pipeline(self) -> Dict[str, Any]:
        """
        Check metrics blob logger pipeline health.

        Verifies:
        - Logger is enabled and initialized
        - No excessive flush errors
        - Buffer size is within bounds

        Returns:
            Dict with metrics pipeline health status
        """
        def check_metrics():
            from infrastructure.metrics_blob_logger import get_metrics_stats

            stats = get_metrics_stats()

            result = {
                "stats": stats,
            }

            # Check for flush errors
            flush_errors = stats.get("flush_errors", 0)
            if flush_errors > 0:
                result["_status"] = "warning"
                result["error"] = f"{flush_errors} flush error(s) detected"

            # Check buffer size — warn if growing too large
            buffer_size = stats.get("buffer_size", 0)
            if buffer_size > 1000:
                result["_status"] = "warning"
                result["error"] = result.get("error", "") + f"; buffer_size={buffer_size} (>1000)"

            return result

        return self.check_component_health(
            "metrics_pipeline",
            check_metrics,
            description="Blob-based metrics logger pipeline status"
        )

    # =========================================================================
    # CHECK: App Insights Ingestion
    # =========================================================================

    def check_appinsights_ingestion(self) -> Dict[str, Any]:
        """
        Check Application Insights ingestion freshness.

        Runs a minimal query (traces | take 1) to verify:
        - App Insights is reachable
        - Data is being ingested (freshness within 15 min)

        Skipped if APPINSIGHTS_APP_ID is not configured.

        Returns:
            Dict with App Insights ingestion health status
        """
        def check_appinsights():
            app_id = os.environ.get("APPINSIGHTS_APP_ID")
            if not app_id:
                return {
                    "_status": "disabled",
                    "reason": "APPINSIGHTS_APP_ID not set",
                    "skip": True,
                }

            import time
            from infrastructure.appinsights_exporter import AppInsightsExporter

            exporter = AppInsightsExporter(app_id)

            start = time.time()
            query_result = exporter.query_logs(
                "traces | take 1 | project timestamp",
                timespan="PT15M",
                timeout=10
            )
            latency_ms = round((time.time() - start) * 1000, 1)

            result = {
                "app_id": app_id,
                "query_latency_ms": latency_ms,
            }

            if query_result.success:
                result["reachable"] = True
                result["row_count"] = query_result.row_count
                if query_result.row_count == 0:
                    result["_status"] = "warning"
                    result["error"] = "No traces in last 15 minutes — ingestion may be stale"
            else:
                result["reachable"] = False
                result["error"] = query_result.error or "Query failed"

            return result

        return self.check_component_health(
            "appinsights_ingestion",
            check_appinsights,
            description="Application Insights data ingestion freshness"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ObservabilityHealthChecks']
