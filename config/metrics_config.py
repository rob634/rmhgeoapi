# ============================================================================
# METRICS CONFIGURATION
# ============================================================================
# STATUS: Configuration - Pipeline Observability Settings
# PURPOSE: Configure real-time metrics for long-running jobs
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no Azure resources)
# ============================================================================
"""
Pipeline Observability Metrics Configuration.

This module configures real-time metrics collection for long-running jobs
with massive task counts (H3 aggregation, FATHOM ETL, raster collections).

Features:
---------
- Debug mode: Chattery stdout logging for development
- Metrics collection: PostgreSQL storage for dashboard polling
- Rate calculation: Tasks/minute, items/second tracking
- ETA estimation: Time remaining based on current rate
- Context-specific: H3 cells, FATHOM tiles, raster files

Environment Variables:
----------------------
METRICS_ENABLED: Master switch for metrics collection (default: true)
METRICS_DEBUG_MODE: Enable chattery stdout logging (default: false)
METRICS_SAMPLE_INTERVAL: Seconds between snapshots (default: 5)
METRICS_RETENTION_MINUTES: Auto-cleanup old metrics (default: 60)

Usage:
------
```python
from config import get_config

config = get_config()

if config.metrics.debug_mode:
    print(f"[METRICS] Processing batch {batch_id}")

if config.metrics.enabled:
    tracker.emit_snapshot()
```

Debug Output Example (when METRICS_DEBUG_MODE=true):
----------------------------------------------------
```
[METRICS] Job abc123 started: h3_raster_aggregation
[METRICS] Stage 2/3: compute_stats (5 tasks)
[METRICS]   Task batch-0 started
[METRICS]     Batch 0: 1000 cells
[METRICS]     ✓ 4000 stats @ 842 cells/sec
[METRICS]   Progress: 2000/68597 cells (2.9%), ETA: 74s
```
"""

import os
from pydantic import BaseModel, Field


class MetricsConfig(BaseModel):
    """
    Pipeline observability metrics configuration.

    Controls real-time metrics collection for long-running jobs with
    massive task counts. Provides visibility into progress, throughput,
    and estimated completion time.

    Configuration Fields:
    ---------------------
    enabled: Master switch for metrics collection
        - True: Collect metrics and store in PostgreSQL
        - False: Skip all metrics (minimal overhead)
        - Default: True

    debug_mode: Enable chattery stdout logging
        - True: Log detailed progress to stdout (development)
        - False: Silent operation (production)
        - Default: False
        - Use for debugging pipeline issues

    sample_interval: Seconds between metric snapshots
        - Lower = more granular but higher overhead
        - Default: 5 seconds
        - Range: 1-60 seconds

    retention_minutes: How long to keep metrics before cleanup
        - Older metrics auto-deleted by janitor
        - Default: 60 minutes
        - Range: 10-1440 minutes (up to 24 hours)

    log_prefix: Prefix for debug log messages
        - Default: "[METRICS]"
        - Helps filter logs in Application Insights
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Master switch for metrics collection. "
            "True = Collect and store metrics in PostgreSQL. "
            "False = Skip all metrics collection (minimal overhead)."
        )
    )

    debug_mode: bool = Field(
        default=False,
        description=(
            "Enable chattery stdout logging for development. "
            "True = Log detailed progress messages to stdout. "
            "False = Silent operation (production mode). "
            "Set METRICS_DEBUG_MODE=true to enable."
        )
    )

    sample_interval: int = Field(
        default=5,
        ge=1,
        le=60,
        description=(
            "Seconds between metric snapshots written to PostgreSQL. "
            "Lower values = more granular but higher database overhead. "
            "Default: 5 seconds."
        )
    )

    retention_minutes: int = Field(
        default=60,
        ge=10,
        le=1440,
        description=(
            "How long to retain metrics before auto-cleanup (minutes). "
            "Older metrics deleted by janitor process. "
            "Default: 60 minutes. Max: 1440 (24 hours)."
        )
    )

    log_prefix: str = Field(
        default="[METRICS]",
        description=(
            "Prefix for debug log messages. "
            "Helps filter metrics logs in Application Insights. "
            "Default: '[METRICS]'"
        )
    )

    @classmethod
    def from_environment(cls) -> "MetricsConfig":
        """
        Load metrics configuration from environment variables.

        Environment Variables:
        ---------------------
        METRICS_ENABLED: Master switch (default: "true")
        METRICS_DEBUG_MODE: Chattery logging (default: "false")
        METRICS_SAMPLE_INTERVAL: Snapshot frequency in seconds (default: "5")
        METRICS_RETENTION_MINUTES: Cleanup threshold (default: "60")
        METRICS_LOG_PREFIX: Log message prefix (default: "[METRICS]")

        Returns:
            MetricsConfig: Configured metrics settings
        """
        def parse_bool(value: str) -> bool:
            """Parse boolean from environment variable."""
            return value.lower() in ("true", "1", "yes")

        return cls(
            enabled=parse_bool(
                os.environ.get("METRICS_ENABLED", "true")
            ),
            debug_mode=parse_bool(
                os.environ.get("METRICS_DEBUG_MODE", "false")
            ),
            sample_interval=int(
                os.environ.get("METRICS_SAMPLE_INTERVAL", "5")
            ),
            retention_minutes=int(
                os.environ.get("METRICS_RETENTION_MINUTES", "60")
            ),
            log_prefix=os.environ.get("METRICS_LOG_PREFIX", "[METRICS]")
        )

    def debug_dict(self) -> dict:
        """
        Return debug-friendly configuration dictionary.

        Returns:
            dict: Configuration with all fields visible
        """
        return {
            "enabled": self.enabled,
            "debug_mode": self.debug_mode,
            "sample_interval": self.sample_interval,
            "retention_minutes": self.retention_minutes,
            "log_prefix": self.log_prefix
        }

    def should_log(self) -> bool:
        """
        Check if debug logging should be performed.

        Returns:
            bool: True if both enabled and debug_mode are True
        """
        return self.enabled and self.debug_mode


# Export
__all__ = ["MetricsConfig"]
