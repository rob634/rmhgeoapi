# ============================================================================
# TIMER HANDLER BASE CLASS
# ============================================================================
# STATUS: Trigger layer - Base class for timer trigger handlers
# PURPOSE: DRY extraction of common timer handling patterns
# CREATED: 09 JAN 2026
# EPIC: E7 Pipeline Infrastructure → F7.10 Metadata Consistency
# ============================================================================
"""
Timer Handler Base Class.

Provides consistent patterns for all timer trigger handlers:
- Past due detection and logging
- Standard execution flow with timing
- Result interpretation and logging
- Exception handling with traceback

Usage:
    class MyTimerHandler(TimerHandlerBase):
        name = "MyHandler"

        def execute(self) -> Dict[str, Any]:
            # Do work, return result dict with 'success' key
            return {"success": True, "items_processed": 42}

    my_handler = MyTimerHandler()

    # In function_app.py:
    @app.timer_trigger(schedule="0 */5 * * * *", ...)
    def my_timer(timer: func.TimerRequest) -> None:
        my_handler.handle(timer)

Exports:
    TimerHandlerBase: Abstract base class for timer handlers
"""

import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import azure.functions as func

from util_logger import LoggerFactory, ComponentType


class TimerHandlerBase(ABC):
    """
    Abstract base class for timer trigger handlers.

    Provides:
    - Consistent past_due handling
    - Standard logging structure (start, complete, error)
    - Result interpretation with health status
    - Exception wrapping with traceback capture

    Subclasses must:
    - Set `name` class attribute
    - Implement `execute()` method returning dict with 'success' key
    """

    name: str = "UnnamedTimer"  # Override in subclass

    def __init__(self):
        """Initialize handler with logger."""
        self._logger = None

    @property
    def logger(self):
        """Lazy-load logger to avoid import issues at module load."""
        if self._logger is None:
            self._logger = LoggerFactory.create_logger(
                ComponentType.TRIGGER,
                self.name
            )
        return self._logger

    def handle(self, timer: func.TimerRequest) -> Dict[str, Any]:
        """
        Standard timer handling with logging and error handling.

        Args:
            timer: Azure Functions TimerRequest

        Returns:
            Result dict from execute() or error dict on failure
        """
        trigger_time = datetime.now(timezone.utc)

        # Past due check
        if timer.past_due:
            self.logger.warning(f"⏰ {self.name}: Timer is past due - running immediately")

        self.logger.info(f"⏰ {self.name}: Triggered at {trigger_time.isoformat()}")

        try:
            # Execute subclass implementation
            start_time = datetime.now(timezone.utc)
            result = self.execute()
            end_time = datetime.now(timezone.utc)

            # Add timing if not present
            if "duration_seconds" not in result:
                result["duration_seconds"] = round(
                    (end_time - start_time).total_seconds(), 2
                )

            # Log result
            self._log_result(result)

            return result

        except Exception as e:
            self.logger.error(f"❌ {self.name}: Unhandled exception: {e}")
            self.logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }

    @abstractmethod
    def execute(self) -> Dict[str, Any]:
        """
        Execute the timer's work.

        Override in subclass to implement actual logic.

        Returns:
            Dict with at least 'success' key (bool).
            Optional keys:
            - 'health_status': str ("HEALTHY", "ISSUES_DETECTED", etc.)
            - 'summary': dict with metrics
            - 'error': str if success=False
            - 'items_scanned': int
            - 'items_fixed': int
        """
        raise NotImplementedError("Subclass must implement execute()")

    def _log_result(self, result: Dict[str, Any]) -> None:
        """
        Log execution result with appropriate level.

        Args:
            result: Result dict from execute()
        """
        success = result.get("success", False)
        health_status = result.get("health_status", "UNKNOWN")
        duration = result.get("duration_seconds", 0)

        if not success:
            error = result.get("error", "Unknown error")
            self.logger.error(f"❌ {self.name}: Failed - {error}")
            return

        # Success - check health status for log level
        summary = result.get("summary", {})
        summary_str = self._format_summary(summary)

        if health_status == "HEALTHY":
            self.logger.info(
                f"✅ {self.name}: Complete - {health_status} "
                f"({duration}s){summary_str}"
            )
        elif health_status in ("ISSUES_DETECTED", "ORPHANS_DETECTED"):
            self.logger.warning(
                f"⚠️ {self.name}: Complete - {health_status} "
                f"({duration}s){summary_str}"
            )
        else:
            # Unknown status - log as info
            self.logger.info(
                f"⏰ {self.name}: Complete - status={health_status} "
                f"({duration}s){summary_str}"
            )

    def _format_summary(self, summary: Dict[str, Any]) -> str:
        """Format summary dict for logging."""
        if not summary:
            return ""

        parts = []
        for key, value in summary.items():
            if isinstance(value, (int, float, str, bool)):
                parts.append(f"{key}={value}")

        if parts:
            return " | " + ", ".join(parts)
        return ""


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = ['TimerHandlerBase']
