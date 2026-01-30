# ============================================================================
# DOCKER HEALTH - Base Subsystem Protocol
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Base Protocol - WorkerSubsystem interface definition
# PURPOSE: Define contract for Docker Worker health subsystems
# CREATED: 29 JAN 2026
# EXPORTS: WorkerSubsystem
# DEPENDENCIES: typing
# ============================================================================
"""
Base protocol for Docker Worker health subsystems.

Each subsystem represents a logical grouping of health checks:
- SharedInfrastructureSubsystem: Common resources (database, storage)
- RuntimeSubsystem: Container environment (hardware, GDAL)
- ClassicWorkerSubsystem: Queue-based job processing
- DAGWorkerSubsystem: DAG-driven workflow processing

All subsystems implement this protocol to ensure consistent health reporting.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, List


class WorkerSubsystem(ABC):
    """
    Abstract base class for Docker Worker health subsystems.

    Each subsystem reports health for a logical grouping of components.
    Subsystems are aggregated by HealthAggregator to produce the final
    health response.

    Attributes:
        name: Unique identifier for this subsystem (e.g., "classic_worker")
        description: Human-readable description
        priority: Execution order (lower = runs first, 10/20/30/40)

    Health Response Format:
        {
            "status": "healthy" | "degraded" | "unhealthy" | "disabled",
            "components": {
                "component_name": {
                    "status": "healthy" | "warning" | "unhealthy" | "disabled",
                    "description": "Component description",
                    "checked_at": "2026-01-29T12:00:00Z",
                    "details": {...}
                }
            },
            "metrics": {...}  # Optional subsystem-specific metrics
        }
    """

    name: str
    description: str
    priority: int = 50  # Default priority

    @abstractmethod
    def get_health(self) -> Dict[str, Any]:
        """
        Return health status for this subsystem.

        Must return a dict with at minimum:
        - status: Overall subsystem status
        - components: Dict of component health checks

        Optional:
        - metrics: Subsystem-specific metrics (throughput, etc.)
        - errors: List of error messages

        Returns:
            Dict with subsystem health information
        """
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """
        Whether this subsystem is currently enabled.

        Disabled subsystems return {"status": "disabled"} without
        running any health checks.

        Returns:
            True if subsystem should run health checks
        """
        pass

    def get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def compute_status(self, components: Dict[str, Dict]) -> str:
        """
        Compute overall subsystem status from component statuses.

        Status priority (worst wins):
        1. unhealthy - Any unhealthy component
        2. degraded/warning - Any degraded or warning component
        3. healthy - All components healthy or disabled

        Args:
            components: Dict of component health results

        Returns:
            Overall status string
        """
        statuses = [c.get("status", "unknown") for c in components.values()]

        if any(s == "unhealthy" for s in statuses):
            return "unhealthy"
        if any(s in ("degraded", "warning") for s in statuses):
            return "degraded"
        if all(s in ("healthy", "disabled") for s in statuses):
            return "healthy"
        return "degraded"  # Unknown statuses treated as degraded

    def build_component(
        self,
        status: str,
        description: str,
        details: Dict[str, Any] = None,
        source: str = "docker_worker",
    ) -> Dict[str, Any]:
        """
        Build a standardized component health response.

        Args:
            status: Component status (healthy/warning/unhealthy/disabled)
            description: Human-readable description
            details: Additional component-specific details
            source: Source tag for health.js UI grouping

        Returns:
            Standardized component dict
        """
        component = {
            "status": status,
            "description": description,
            "checked_at": self.get_timestamp(),
            "_source": source,
        }
        if details:
            component["details"] = details
        return component


__all__ = ['WorkerSubsystem']
