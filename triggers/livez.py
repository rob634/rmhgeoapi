# ============================================================================
# CLAUDE CONTEXT - LIVENESS CHECK HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP Trigger - Ultra-lightweight liveness probe
# PURPOSE: Fast endpoint for load balancer/Kubernetes liveness checks
# LAST_REVIEWED: 05 JAN 2026
# EXPORTS: LivenessCheckTrigger, livez_trigger
# INTERFACES: SystemMonitoringTrigger (http_base.py)
# DEPENDENCIES: azure.functions (no external service dependencies!)
# PATTERNS: Singleton trigger instance
# ENTRY_POINTS: livez_trigger.handle_request(req)
# ============================================================================
"""
Lightweight Liveness Check HTTP Trigger.

Fast endpoint for load balancer health checks and Kubernetes liveness probes.
Returns minimal response to verify the Function App process is running.

CRITICAL: This endpoint must have ZERO external dependencies.
- NO database checks
- NO Service Bus checks
- NO storage checks
- NO config validation

If this endpoint responds, the app is alive.

For comprehensive health status, use /api/health instead.

Exports:
    LivenessCheckTrigger: Liveness check trigger class
    livez_trigger: Singleton trigger instance
"""

from typing import Dict, Any, List
from datetime import datetime, timezone
import azure.functions as func
from .http_base import SystemMonitoringTrigger


class LivenessCheckTrigger(SystemMonitoringTrigger):
    """Ultra-lightweight liveness check - no external dependencies."""

    def __init__(self):
        super().__init__("livez")

    def get_allowed_methods(self) -> List[str]:
        """Liveness check only supports GET."""
        return ["GET"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Return minimal liveness status.

        No dependencies checked - confirms Function App process is running.
        For comprehensive health status, use /api/health instead.

        Args:
            req: HTTP request (not used)

        Returns:
            Minimal status dict with alive status and timestamp
        """
        return {
            "status": "alive",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Singleton instance
livez_trigger = LivenessCheckTrigger()
