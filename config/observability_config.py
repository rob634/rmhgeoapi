# ============================================================================
# OBSERVABILITY CONFIGURATION
# ============================================================================
# STATUS: Configuration - Unified debug and diagnostics control
# PURPOSE: Single flag for all observability features (replaces 4 duplicate flags)
# LAST_REVIEWED: 10 JAN 2026
# EXPORTS: ObservabilityConfig
# DEPENDENCIES: pydantic
# ============================================================================
"""
Unified Observability Configuration.

================================================================================
FLAG CONSOLIDATION (10 JAN 2026 - F7.12.C)
================================================================================

BEFORE (4 duplicate flags causing confusion):
    DEBUG_MODE           → General debugging in AppConfig
    DEBUG_LOGGING        → Verbose log level in util_logger
    METRICS_DEBUG_MODE   → Service latency tracking
    METRICS_ENABLED      → ETL dashboard metrics (different purpose - kept)

AFTER (2 clear flags):
    OBSERVABILITY_MODE   → All debug instrumentation (unified)
    METRICS_ENABLED      → ETL dashboard metrics (unchanged - different purpose)

OBSERVABILITY_MODE controls:
    - Memory/CPU tracking (log_memory_checkpoint, get_memory_stats)
    - Service latency tracking (@track_latency, @track_db_operation)
    - Blob metrics logging (MetricsBlobLogger)
    - Verbose diagnostics (detailed timing, payload logging)
    - Database stats collection (get_database_stats)

BACKWARD COMPATIBILITY:
    Reads from multiple env vars in priority order:
    1. OBSERVABILITY_MODE (new preferred)
    2. METRICS_DEBUG_MODE (legacy - service latency)
    3. DEBUG_MODE (legacy - general debugging)

    This allows gradual migration without breaking existing deployments.

Usage:
------
```python
from config import get_config

config = get_config()

# Check if observability features are enabled
if config.observability.enabled:
    log_memory_checkpoint(logger, "start")

# Or use the helper method
if config.is_observability_enabled():
    tracker.emit_detailed_metrics()
```

Environment Variables:
----------------------
OBSERVABILITY_MODE: Master switch for all debug instrumentation (default: false)
                   If not set, falls back to METRICS_DEBUG_MODE or DEBUG_MODE

LOG_LEVEL: Controls logging verbosity (DEBUG, INFO, WARNING, ERROR)
          Use LOG_LEVEL=DEBUG instead of DEBUG_LOGGING=true
"""

import os
from pydantic import BaseModel, Field

from .defaults import parse_bool


class ObservabilityConfig(BaseModel):
    """
    Unified observability configuration.

    Controls all debug instrumentation features from a single flag.

    Configuration Fields:
    ---------------------
    enabled: Master switch for observability features
        - True: Enable memory tracking, latency logging, diagnostics
        - False: Minimal overhead, production mode
        - Default: False

        Controlled by environment variables (checked in order):
        1. OBSERVABILITY_MODE
        2. METRICS_DEBUG_MODE (legacy)
        3. DEBUG_MODE (legacy)

    verbose_log_dump: Enable verbose JSONL log dumps (11 JAN 2026 - F7.12.F)
        - When true (with enabled=true), dumps ALL logs to blob
        - When false, only dumps janitor/timer + WARNING+

    app_name: Application identifier for multi-app log filtering
        - Set via APP_NAME env var
        - Used in global log context

    app_instance: Instance identifier (Azure WEBSITE_INSTANCE_ID)
        - Automatically populated from Azure environment
        - Truncated to 16 chars for readability

    environment: Deployment environment (dev, qa, prod)
        - Set via ENVIRONMENT env var
        - Used in global log context

    JSONL Log Retention (11 JAN 2026 - F7.12.F):
        debug_retention_days: Days to keep verbose/debug logs (default: 7)
        warning_retention_days: Days to keep warning+ logs (default: 30)
        metrics_retention_days: Days to keep metrics logs (default: 14)
    """

    enabled: bool = Field(
        default=False,
        description=(
            "Master switch for observability features. "
            "True = Enable memory tracking, service latency, blob metrics. "
            "False = Minimal overhead for production. "
            "Reads from OBSERVABILITY_MODE, METRICS_DEBUG_MODE, or DEBUG_MODE."
        )
    )

    verbose_log_dump: bool = Field(
        default=False,
        description=(
            "Enable verbose JSONL log dumps (11 JAN 2026 - F7.12.F). "
            "When true (with enabled=true), dumps ALL logs including DEBUG to blob storage. "
            "When false, only dumps janitor/timer logs + WARNING+ from everything else. "
            "Set via VERBOSE_LOG_DUMP environment variable."
        )
    )

    app_name: str = Field(
        default="unknown",
        description=(
            "Application name for multi-app log filtering. "
            "Set via APP_NAME environment variable. "
            "Appears in every log entry when observability is enabled."
        )
    )

    app_instance: str = Field(
        default="local",
        description=(
            "Instance identifier for distinguishing Azure instances. "
            "Automatically populated from WEBSITE_INSTANCE_ID. "
            "Truncated to 16 characters for readability."
        )
    )

    environment: str = Field(
        default="dev",
        description=(
            "Deployment environment (dev, qa, prod). "
            "Set via ENVIRONMENT env var. "
            "Used for log filtering and alerting rules."
        )
    )

    # JSONL Log Retention Settings (11 JAN 2026 - F7.12.F)
    debug_retention_days: int = Field(
        default=7,
        description=(
            "Days to keep verbose/debug logs in blob storage. "
            "Set via JSONL_DEBUG_RETENTION_DAYS. "
            "Applies to applogs/logs/verbose/ directory."
        )
    )

    warning_retention_days: int = Field(
        default=30,
        description=(
            "Days to keep warning+ logs in blob storage. "
            "Set via JSONL_WARNING_RETENTION_DAYS. "
            "Applies to applogs/logs/default/ directory."
        )
    )

    metrics_retention_days: int = Field(
        default=14,
        description=(
            "Days to keep metrics logs in blob storage. "
            "Set via JSONL_METRICS_RETENTION_DAYS. "
            "Applies to applogs/service-metrics/ directory."
        )
    )

    @classmethod
    def from_environment(cls) -> "ObservabilityConfig":
        """
        Load observability configuration from environment variables.

        Checks multiple env vars for backward compatibility:
        1. OBSERVABILITY_MODE (new preferred)
        2. METRICS_DEBUG_MODE (legacy - service latency)
        3. DEBUG_MODE (legacy - general debugging)

        Returns:
            ObservabilityConfig with enabled status from environment
        """
        def parse_int(value: str, default: int) -> int:
            """Parse integer from environment variable."""
            try:
                return int(value) if value else default
            except ValueError:
                return default

        # Check env vars in priority order for backward compatibility
        observability_mode = os.environ.get("OBSERVABILITY_MODE", "").lower()
        metrics_debug_mode = os.environ.get("METRICS_DEBUG_MODE", "").lower()
        debug_mode = os.environ.get("DEBUG_MODE", "").lower()

        # Priority: OBSERVABILITY_MODE > METRICS_DEBUG_MODE > DEBUG_MODE
        if observability_mode:
            enabled = parse_bool(observability_mode)
        elif metrics_debug_mode:
            enabled = parse_bool(metrics_debug_mode)
        elif debug_mode:
            enabled = parse_bool(debug_mode)
        else:
            enabled = False

        # Verbose log dump (11 JAN 2026 - F7.12.F)
        verbose_log_dump = parse_bool(os.environ.get("VERBOSE_LOG_DUMP", ""))

        # Retention settings (11 JAN 2026 - F7.12.F)
        debug_retention = parse_int(os.environ.get("JSONL_DEBUG_RETENTION_DAYS", ""), 7)
        warning_retention = parse_int(os.environ.get("JSONL_WARNING_RETENTION_DAYS", ""), 30)
        metrics_retention = parse_int(os.environ.get("JSONL_METRICS_RETENTION_DAYS", ""), 14)

        return cls(
            enabled=enabled,
            verbose_log_dump=verbose_log_dump,
            app_name=os.environ.get("APP_NAME", "unknown"),
            app_instance=os.environ.get("WEBSITE_INSTANCE_ID", "local")[:16],
            environment=os.environ.get("ENVIRONMENT", "dev"),
            debug_retention_days=debug_retention,
            warning_retention_days=warning_retention,
            metrics_retention_days=metrics_retention,
        )

    def debug_dict(self) -> dict:
        """
        Return debug-friendly configuration dictionary.

        Returns:
            dict: Configuration with all fields visible
        """
        return {
            "enabled": self.enabled,
            "verbose_log_dump": self.verbose_log_dump,
            "app_name": self.app_name,
            "app_instance": self.app_instance,
            "environment": self.environment,
            "debug_retention_days": self.debug_retention_days,
            "warning_retention_days": self.warning_retention_days,
            "metrics_retention_days": self.metrics_retention_days,
        }

    def get_global_context(self) -> dict:
        """
        Get global log context fields.

        These fields are injected into every log entry for:
        - Multi-app filtering (which function app?)
        - Multi-instance filtering (which Azure instance?)
        - Environment-based alerting (prod vs dev)

        Returns:
            dict with app_name, app_instance, environment
        """
        return {
            "app_name": self.app_name,
            "app_instance": self.app_instance,
            "environment": self.environment,
        }


# Export
__all__ = ["ObservabilityConfig"]
