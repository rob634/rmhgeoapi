# ============================================================================
# HEALTH CHECK PLUGIN BASE CLASS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Base class for health check plugins
# PURPOSE: Modular health check architecture
# CREATED: 29 JAN 2026
# EXPORTS: HealthCheckPlugin
# DEPENDENCIES: None (intentionally minimal)
# ============================================================================
"""
Health Check Plugin Base Class.

Provides the foundation for modular health checks. Each plugin represents
a category of related health checks (infrastructure, database, etc.).

Usage:
    class MyHealthChecks(HealthCheckPlugin):
        name = "my_checks"
        description = "My custom health checks"
        priority = 50

        def get_checks(self):
            return [
                ("check_one", self.check_one),
                ("check_two", self.check_two),
            ]

        def check_one(self):
            return {"status": "healthy", "details": {...}}
"""

from typing import Dict, Any, List, Tuple, Callable, Optional
from abc import ABC, abstractmethod
from datetime import datetime, timezone


class HealthCheckPlugin(ABC):
    """
    Base class for health check plugins.

    Each plugin represents a category of related health checks.
    Plugins are automatically discovered and registered via __init__.py.

    Attributes:
        name: Plugin identifier (e.g., "infrastructure", "database")
        description: Human-readable description
        priority: Execution order (lower = runs earlier, default 100)
    """

    # Plugin metadata (override in subclasses)
    name: str = "unknown"
    description: str = ""
    priority: int = 100  # Lower = runs earlier

    def __init__(self, logger=None):
        """
        Initialize the plugin.

        Args:
            logger: Optional logger instance for error reporting
        """
        self.logger = logger

    @abstractmethod
    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """
        Return list of (check_name, check_method) tuples.

        Each check_method should return a dict with at minimum:
        - component: str - The component name
        - status: str - "healthy", "unhealthy", "warning", "error", "disabled"
        - checked_at: str - ISO timestamp

        Returns:
            List of (name, callable) tuples

        Example:
            return [
                ("storage_containers", self.check_storage_containers),
                ("service_bus", self.check_service_bus),
            ]
        """
        raise NotImplementedError

    def is_enabled(self, config) -> bool:
        """
        Whether this plugin should run.

        Override to conditionally disable plugins based on config.
        Default: always enabled.

        Args:
            config: AppConfig instance

        Returns:
            True if plugin should run, False to skip
        """
        return True

    def get_parallel_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """
        Return checks that can run in parallel (I/O-bound).

        By default returns empty list. Override for plugins with
        external HTTP calls that benefit from parallel execution.

        Returns:
            List of (name, callable) tuples for parallel execution
        """
        return []

    def check_component_health(
        self,
        component_name: str,
        check_func: Callable[[], Dict[str, Any]],
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Standard wrapper for health checks with error handling.

        Wraps a check function with:
        - Error handling and logging
        - Standardized result structure
        - Automatic timestamp

        Args:
            component_name: Name of the component being checked
            check_func: Function that performs the actual check
            description: Human-readable description

        Returns:
            Standardized health check result dict with keys:
            - component: str
            - status: str ("healthy", "unhealthy", "warning", "error", "disabled")
            - checked_at: str (ISO timestamp)
            - description: str (if provided)
            - Plus any keys returned by check_func
        """
        try:
            result = check_func()

            # Ensure required fields
            if "component" not in result:
                result["component"] = component_name
            if "checked_at" not in result:
                result["checked_at"] = datetime.now(timezone.utc).isoformat()

            # Determine status from result
            # Allow explicit _status override (e.g., for warning vs unhealthy)
            status = result.get("_status")
            if not status:
                if result.get("error"):
                    status = "unhealthy"
                else:
                    status = "healthy"
            result["status"] = status

            # Remove internal _status key if present
            result.pop("_status", None)

            if description:
                result["description"] = description

            return result

        except Exception as e:
            if self.logger:
                self.logger.error(f"Health check '{component_name}' failed: {e}")
            return {
                "component": component_name,
                "status": "error",
                "error": str(e)[:500],
                "error_type": type(e).__name__,
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

    def _log_error(self, message: str):
        """Log an error message if logger is available."""
        if self.logger:
            self.logger.error(message)

    def _log_warning(self, message: str):
        """Log a warning message if logger is available."""
        if self.logger:
            self.logger.warning(message)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['HealthCheckPlugin']
