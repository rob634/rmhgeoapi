# ============================================================================
# SERVICE LATENCY TRACKING
# ============================================================================
# STATUS: Infrastructure - Service layer response time instrumentation
# PURPOSE: Track latency for OGC Features, STAC API, and other service calls
# LAST_REVIEWED: 09 JAN 2026
# EXPORTS: track_latency, track_db_operation, ServiceLatencyTracker
# DEPENDENCIES: config.metrics
# ============================================================================
"""
Service Layer Latency Tracking.

Provides conditional instrumentation for service layer calls (OGC Features,
STAC API, etc.) to diagnose slow operations in corporate Azure environments
with VNet/ASE network complexity.

Key Design:
-----------
- Zero overhead when METRICS_DEBUG_MODE=false (early return, no timing)
- Full timing + structured logging when enabled
- Slow operation alerting (configurable threshold)
- Designed for Application Insights Kusto queries

Environment Variables:
----------------------
METRICS_DEBUG_MODE: Enable service latency tracking (default: false)
SERVICE_LATENCY_SLOW_MS: Threshold for slow operation warnings (default: 2000)

Usage:
------
```python
from infrastructure.service_latency import track_latency, track_db_operation

class OGCFeaturesService:

    @track_latency("ogc.get_features")
    def get_features(self, collection_id: str, **params):
        # ... implementation
        pass

class OGCFeaturesRepository:

    @track_db_operation("ogc.query_features")
    def query_features(self, collection_id: str, bbox=None):
        # ... database query
        pass
```

Application Insights Queries:
-----------------------------
```kusto
-- Find slow service operations
traces
| where message contains "[SERVICE_LATENCY]"
| extend duration_ms = todouble(customDimensions.duration_ms)
| where duration_ms > 1000
| project timestamp, customDimensions.operation, duration_ms

-- P90 latency by operation
traces
| where message contains "[SERVICE_LATENCY]"
| extend op = tostring(customDimensions.operation)
| extend duration_ms = todouble(customDimensions.duration_ms)
| summarize p90=percentile(duration_ms, 90) by op
```
"""

import logging
import os
import time
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Any, Optional, Dict

logger = logging.getLogger(__name__)

# Slow operation threshold (milliseconds)
SLOW_THRESHOLD_MS = int(os.environ.get("SERVICE_LATENCY_SLOW_MS", "2000"))


def _is_latency_tracking_enabled() -> bool:
    """
    Check if latency tracking is enabled.

    Uses METRICS_DEBUG_MODE to control service latency tracking.
    Lazy evaluation to avoid import-time config loading.

    Returns:
        bool: True if METRICS_DEBUG_MODE=true
    """
    from config import get_config
    return get_config().metrics.debug_mode


def track_latency(operation_name: str):
    """
    Decorator to track latency for service layer operations.

    Zero overhead when METRICS_DEBUG_MODE=false - the original function
    is called directly without any timing or logging.

    When enabled, logs structured JSON with:
    - operation: Operation name for filtering
    - duration_ms: Execution time in milliseconds
    - status: 'success' or 'error'
    - slow: True if duration > SERVICE_LATENCY_SLOW_MS

    Args:
        operation_name: Identifier for this operation (e.g., 'ogc.get_features')

    Returns:
        Decorated function with conditional latency tracking

    Example:
        @track_latency("stac.search")
        def search_items(self, collection_id: str, bbox=None):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Fast path: no overhead when disabled
            if not _is_latency_tracking_enabled():
                return func(*args, **kwargs)

            # Slow path: full timing when enabled
            start = time.perf_counter()
            status = "success"
            error_msg = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                is_slow = duration_ms > SLOW_THRESHOLD_MS

                # Structured log for Application Insights
                extra = {
                    "custom_dimensions": {
                        "operation": operation_name,
                        "duration_ms": round(duration_ms, 2),
                        "status": status,
                        "slow": is_slow
                    }
                }

                if error_msg:
                    extra["custom_dimensions"]["error"] = error_msg[:200]

                if is_slow:
                    logger.warning(
                        f"[SERVICE_LATENCY] SLOW {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )
                else:
                    logger.info(
                        f"[SERVICE_LATENCY] {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )

        return wrapper
    return decorator


def track_db_operation(operation_name: str):
    """
    Decorator specifically for database operations.

    Similar to track_latency but uses [DB_LATENCY] prefix for easier
    filtering when diagnosing connection vs query time issues.

    Args:
        operation_name: Identifier for this DB operation (e.g., 'ogc.query_features')

    Returns:
        Decorated function with conditional latency tracking
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Fast path: no overhead when disabled
            if not _is_latency_tracking_enabled():
                return func(*args, **kwargs)

            # Slow path: full timing when enabled
            start = time.perf_counter()
            status = "success"
            error_msg = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                is_slow = duration_ms > SLOW_THRESHOLD_MS

                extra = {
                    "custom_dimensions": {
                        "operation": operation_name,
                        "duration_ms": round(duration_ms, 2),
                        "status": status,
                        "slow": is_slow,
                        "layer": "database"
                    }
                }

                if error_msg:
                    extra["custom_dimensions"]["error"] = error_msg[:200]

                if is_slow:
                    logger.warning(
                        f"[DB_LATENCY] SLOW {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )
                else:
                    logger.info(
                        f"[DB_LATENCY] {operation_name}: {duration_ms:.0f}ms",
                        extra=extra
                    )

        return wrapper
    return decorator


@contextmanager
def timed_section(section_name: str, context: Optional[Dict[str, Any]] = None):
    """
    Context manager for timing arbitrary code sections.

    Useful for decomposing a large operation into sub-timings to identify
    which specific part is slow.

    Args:
        section_name: Identifier for this section
        context: Optional dict of additional context to log

    Yields:
        None - use as context manager

    Example:
        with timed_section("fetch_from_storage", {"blob": "data.json"}):
            data = blob_client.download()

        with timed_section("parse_geojson"):
            features = json.loads(data)
    """
    if not _is_latency_tracking_enabled():
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        is_slow = duration_ms > SLOW_THRESHOLD_MS

        extra = {
            "custom_dimensions": {
                "section": section_name,
                "duration_ms": round(duration_ms, 2),
                "slow": is_slow,
                **(context or {})
            }
        }

        if is_slow:
            logger.warning(
                f"[SECTION_LATENCY] SLOW {section_name}: {duration_ms:.0f}ms",
                extra=extra
            )
        else:
            logger.debug(
                f"[SECTION_LATENCY] {section_name}: {duration_ms:.0f}ms",
                extra=extra
            )


class ServiceLatencyTracker:
    """
    Stateful tracker for multi-phase service operations.

    Use when a service call involves multiple sequential steps and you
    want to track each phase separately plus the total.

    Example:
        tracker = ServiceLatencyTracker("ogc.get_collection_features")

        tracker.start_phase("validate_params")
        # ... validation ...
        tracker.end_phase()

        tracker.start_phase("query_database")
        # ... database query ...
        tracker.end_phase()

        tracker.start_phase("format_response")
        # ... formatting ...
        tracker.end_phase()

        tracker.finish()  # Logs total + all phases
    """

    def __init__(self, operation_name: str):
        """
        Initialize tracker for an operation.

        Args:
            operation_name: Identifier for the overall operation
        """
        self.operation_name = operation_name
        self.enabled = _is_latency_tracking_enabled()
        self.phases: Dict[str, float] = {}
        self.current_phase: Optional[str] = None
        self.phase_start: Optional[float] = None
        self.total_start = time.perf_counter() if self.enabled else None

    def start_phase(self, phase_name: str) -> None:
        """Start timing a phase."""
        if not self.enabled:
            return
        if self.current_phase:
            self.end_phase()  # Auto-end previous phase
        self.current_phase = phase_name
        self.phase_start = time.perf_counter()

    def end_phase(self) -> None:
        """End current phase and record duration."""
        if not self.enabled or not self.current_phase:
            return
        duration_ms = (time.perf_counter() - self.phase_start) * 1000
        self.phases[self.current_phase] = round(duration_ms, 2)
        self.current_phase = None
        self.phase_start = None

    def finish(self, status: str = "success", error: Optional[str] = None) -> Dict[str, Any]:
        """
        Finish tracking and log results.

        Args:
            status: 'success' or 'error'
            error: Optional error message

        Returns:
            Dict with total_ms and phase breakdown
        """
        if not self.enabled:
            return {}

        if self.current_phase:
            self.end_phase()

        total_ms = (time.perf_counter() - self.total_start) * 1000
        is_slow = total_ms > SLOW_THRESHOLD_MS

        result = {
            "total_ms": round(total_ms, 2),
            "phases": self.phases,
            "status": status
        }

        extra = {
            "custom_dimensions": {
                "operation": self.operation_name,
                "duration_ms": round(total_ms, 2),
                "phases": self.phases,
                "status": status,
                "slow": is_slow
            }
        }

        if error:
            extra["custom_dimensions"]["error"] = error[:200]

        # Find slowest phase
        if self.phases:
            slowest = max(self.phases.items(), key=lambda x: x[1])
            extra["custom_dimensions"]["slowest_phase"] = slowest[0]
            extra["custom_dimensions"]["slowest_phase_ms"] = slowest[1]

        if is_slow:
            logger.warning(
                f"[SERVICE_LATENCY] SLOW {self.operation_name}: {total_ms:.0f}ms "
                f"(slowest: {slowest[0]}={slowest[1]:.0f}ms)" if self.phases else "",
                extra=extra
            )
        else:
            logger.info(
                f"[SERVICE_LATENCY] {self.operation_name}: {total_ms:.0f}ms",
                extra=extra
            )

        return result


# Export
__all__ = [
    "track_latency",
    "track_db_operation",
    "timed_section",
    "ServiceLatencyTracker",
    "SLOW_THRESHOLD_MS"
]
