"""
Application Mode Configuration.

Controls deployment mode and task routing behavior for multi-Function App architecture.

Architecture (11 DEC 2025 - No Legacy Fallbacks):
- Single codebase deployable to multiple Function Apps
- Environment variable APP_MODE controls behavior
- Centralized orchestration (Platform) + Distributed execution (Workers)
- THREE queues only: geospatial-jobs, raster-tasks, vector-tasks
- NO legacy/fallback queue - all tasks must be explicitly routed

Modes:
- standalone: All queues, all endpoints (current behavior, default)
- platform_raster: HTTP + jobs + raster-tasks
- platform_vector: HTTP + jobs + vector-tasks
- platform_only: HTTP + jobs only (pure router)
- worker_raster: raster-tasks only (no HTTP)
- worker_vector: vector-tasks only (no HTTP)

Usage:
    from config.app_mode_config import AppModeConfig, AppMode

    config = AppModeConfig.from_environment()
    if config.listens_to_raster_tasks:
        # Register raster task queue trigger
        pass

Exports:
    AppMode: Enum of valid application modes
    AppModeConfig: Pydantic configuration model
"""

import os
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .defaults import AppModeDefaults


# =============================================================================
# APP MODE ENUM
# =============================================================================

class AppMode(str, Enum):
    """
    Application deployment modes.

    Each mode determines:
    - Which Service Bus queues the app listens to
    - Whether HTTP endpoints are exposed
    - How tasks are routed
    """

    STANDALONE = "standalone"           # All queues, all endpoints (default)
    PLATFORM_RASTER = "platform_raster" # HTTP + jobs + raster-tasks
    PLATFORM_VECTOR = "platform_vector" # HTTP + jobs + vector-tasks
    PLATFORM_ONLY = "platform_only"     # HTTP + jobs only (pure router)
    WORKER_RASTER = "worker_raster"     # raster-tasks only
    WORKER_VECTOR = "worker_vector"     # vector-tasks only


# =============================================================================
# APP MODE CONFIGURATION
# =============================================================================

class AppModeConfig(BaseModel):
    """
    Application mode configuration.

    Determines queue listening behavior and task routing based on deployment mode.

    Attributes:
        mode: The deployment mode (standalone, platform_*, worker_*)
        app_name: Unique identifier for this app instance (for task tracking)
        raster_app_url: External raster app URL (future cross-app HTTP calls)
        vector_app_url: External vector app URL (future cross-app HTTP calls)
    """

    mode: AppMode = Field(
        default=AppMode.STANDALONE,
        description="Application deployment mode"
    )

    app_name: str = Field(
        default=AppModeDefaults.DEFAULT_APP_NAME,
        description="Unique identifier for this app instance (tracked on tasks)"
    )

    # External app URLs (for future cross-app routing)
    raster_app_url: Optional[str] = Field(
        default=None,
        description="External raster Function App URL (future use)"
    )

    vector_app_url: Optional[str] = Field(
        default=None,
        description="External vector Function App URL (future use)"
    )

    # =========================================================================
    # QUEUE LISTENING PROPERTIES
    # =========================================================================

    @property
    def has_http_endpoints(self) -> bool:
        """Whether this mode serves HTTP endpoints."""
        # All modes have HTTP endpoints for now (per user feedback)
        # Worker modes could disable HTTP in future if needed
        return True

    @property
    def listens_to_jobs_queue(self) -> bool:
        """Whether this mode processes the jobs queue (orchestration)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
            AppMode.PLATFORM_ONLY,
        ]

    @property
    def listens_to_raster_tasks(self) -> bool:
        """Whether this mode processes raster tasks."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.PLATFORM_RASTER,
            AppMode.WORKER_RASTER,
        ]

    @property
    def listens_to_vector_tasks(self) -> bool:
        """Whether this mode processes vector tasks."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.PLATFORM_VECTOR,
            AppMode.WORKER_VECTOR,
        ]

    # =========================================================================
    # ROUTING PROPERTIES
    # =========================================================================

    @property
    def routes_raster_externally(self) -> bool:
        """Whether raster tasks should be routed to external queue (not processed locally)."""
        return self.mode in [
            AppMode.PLATFORM_VECTOR,
            AppMode.PLATFORM_ONLY,
        ]

    @property
    def routes_vector_externally(self) -> bool:
        """Whether vector tasks should be routed to external queue (not processed locally)."""
        return self.mode in [
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_ONLY,
        ]

    @property
    def is_worker_mode(self) -> bool:
        """Whether this is a worker-only mode (no orchestration)."""
        return self.mode in [
            AppMode.WORKER_RASTER,
            AppMode.WORKER_VECTOR,
        ]

    @property
    def is_platform_mode(self) -> bool:
        """Whether this mode handles job orchestration."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
            AppMode.PLATFORM_ONLY,
        ]

    # =========================================================================
    # FACTORY METHOD
    # =========================================================================

    @classmethod
    def from_environment(cls) -> "AppModeConfig":
        """
        Load configuration from environment variables.

        Environment Variables:
            APP_MODE: Deployment mode (default: standalone)
            APP_NAME: Unique app identifier (default: rmhazuregeoapi)
            RASTER_APP_URL: External raster app URL (optional)
            VECTOR_APP_URL: External vector app URL (optional)
        """
        mode_str = os.environ.get("APP_MODE", AppModeDefaults.DEFAULT_MODE)

        # Validate mode
        try:
            mode = AppMode(mode_str)
        except ValueError:
            # Invalid mode - fall back to standalone with warning
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Invalid APP_MODE '{mode_str}', valid modes: {[m.value for m in AppMode]}. "
                f"Falling back to '{AppModeDefaults.DEFAULT_MODE}'"
            )
            mode = AppMode.STANDALONE

        return cls(
            mode=mode,
            app_name=os.environ.get("APP_NAME", AppModeDefaults.DEFAULT_APP_NAME),
            raster_app_url=os.environ.get("RASTER_APP_URL"),
            vector_app_url=os.environ.get("VECTOR_APP_URL"),
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def describe(self) -> dict:
        """Return a dictionary describing the current configuration."""
        return {
            "mode": self.mode.value,
            "app_name": self.app_name,
            "queues_listening": {
                "jobs": self.listens_to_jobs_queue,
                "raster_tasks": self.listens_to_raster_tasks,
                "vector_tasks": self.listens_to_vector_tasks,
            },
            "routing": {
                "routes_raster_externally": self.routes_raster_externally,
                "routes_vector_externally": self.routes_vector_externally,
            },
            "role": {
                "is_platform": self.is_platform_mode,
                "is_worker": self.is_worker_mode,
                "has_http": self.has_http_endpoints,
            },
            "external_apps": {
                "raster_app_url": self.raster_app_url,
                "vector_app_url": self.vector_app_url,
            },
        }


# =============================================================================
# MODULE-LEVEL SINGLETON (for import-time access in function_app.py)
# =============================================================================

# Create singleton instance for use at module import time
# This is needed because Azure Functions decorators are evaluated at import
_app_mode_config: Optional[AppModeConfig] = None


def get_app_mode_config() -> AppModeConfig:
    """
    Get the singleton AppModeConfig instance.

    Lazily initializes from environment on first call.
    """
    global _app_mode_config
    if _app_mode_config is None:
        _app_mode_config = AppModeConfig.from_environment()
    return _app_mode_config


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "AppMode",
    "AppModeConfig",
    "get_app_mode_config",
]
