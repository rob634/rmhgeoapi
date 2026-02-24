# ============================================================================
# APPLICATION MODE CONFIGURATION (V0.9)
# ============================================================================
# STATUS: Configuration - Docker-only deployment modes
# PURPOSE: Control queue listening behavior and task routing per deployment
# LAST_REVIEWED: 19 FEB 2026
# ============================================================================
"""
Application Mode Configuration (V0.9 - 19 FEB 2026).

================================================================================
DEPLOYMENT MODES
================================================================================

┌─────────────────────┬───────────────────────────────┬─────────────────────────┐
│ Mode                │ Queues Listening              │ HTTP Endpoints          │
├─────────────────────┼───────────────────────────────┼─────────────────────────┤
│ STANDALONE          │ jobs + container-tasks*       │ All (dev only)          │
│ PLATFORM            │ None (send-only)              │ platform/* only         │
│ ORCHESTRATOR        │ jobs                          │ All except workers      │
│ WORKER_DOCKER       │ container-tasks               │ health only             │
└─────────────────────┴───────────────────────────────┴─────────────────────────┘

* STANDALONE listens to container-tasks only if DOCKER_WORKER_ENABLED=false

--------------------------------------------------------------------------------
MODE DETAILS
--------------------------------------------------------------------------------

1. STANDALONE (Development)
   - Single app handles everything
   - Listens: geospatial-jobs
   - Container-tasks: Only if DOCKER_WORKER_ENABLED=false

   Environment: APP_MODE=standalone

2. PLATFORM (Public Gateway)
   - HTTP gateway only, sends to jobs queue
   - Listens: Nothing (send-only)

   Environment: APP_MODE=platform

3. ORCHESTRATOR (Job Router)
   - Processes jobs queue, routes tasks to workers
   - Listens: geospatial-jobs

   Environment: APP_MODE=orchestrator

4. WORKER_DOCKER (Docker Worker)
   - Processes all ETL tasks (GDAL, geopandas, bulk SQL)
   - Listens: container-tasks
   - Runs in Docker container, not Azure Functions

   Environment: APP_MODE=worker_docker

--------------------------------------------------------------------------------
ENVIRONMENT VARIABLES
--------------------------------------------------------------------------------

Required:
    APP_MODE = standalone | platform | orchestrator | worker_docker

Optional:
    APP_NAME = {unique-app-identifier}
    DOCKER_WORKER_ENABLED = true | false
    DOCKER_WORKER_URL = https://{docker-worker}.azurewebsites.net

--------------------------------------------------------------------------------
DEPLOYMENT VERIFICATION
--------------------------------------------------------------------------------

    curl https://{app-url}/api/health

Response includes:
    "app_mode": {
        "mode": "standalone",
        "queues_listening": {
            "jobs": true,
            "functionapp_tasks": true,
            "container_tasks": false
        }
    }

--------------------------------------------------------------------------------
EXPORTS
--------------------------------------------------------------------------------

    AppMode: Enum of valid application modes
    AppModeConfig: Pydantic configuration model
    get_app_mode_config(): Singleton accessor
"""

import os
import threading
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .defaults import AppModeDefaults


# =============================================================================
# APP MODE ENUM
# =============================================================================

class AppMode(str, Enum):
    """
    Application deployment modes (V0.9 - 19 FEB 2026).

    Each mode determines:
    - Which Service Bus queues the app listens to
    - Which HTTP endpoints are exposed
    - How tasks are routed

    V0.9 Architecture - 4 Modes:
    ─────────────────────────────────────────────────────────────────────────
    Mode              │ Queues                    │ HTTP Endpoints
    ─────────────────────────────────────────────────────────────────────────
    STANDALONE        │ jobs + container-tasks    │ All (dev only)
    PLATFORM          │ None (send-only)          │ platform/* only
    ORCHESTRATOR      │ jobs                      │ All except workers
    WORKER_DOCKER     │ container-tasks           │ health only
    ─────────────────────────────────────────────────────────────────────────

    Migration Notes (V0.8 → V0.9):
    - gateway → PLATFORM
    - platform_only → ORCHESTRATOR
    - platform_raster → ORCHESTRATOR
    - platform_vector → ORCHESTRATOR
    - worker_raster → WORKER_DOCKER
    - worker_vector → WORKER_DOCKER
    - worker_functionapp → WORKER_DOCKER
    """

    STANDALONE = "standalone"                 # All queues, all endpoints (dev)
    PLATFORM = "platform"                     # HTTP only, sends to jobs queue
    ORCHESTRATOR = "orchestrator"             # Jobs queue + all HTTP
    WORKER_DOCKER = "worker_docker"           # container-tasks queue (Docker)


# =============================================================================
# APP MODE CONFIGURATION
# =============================================================================

class AppModeConfig(BaseModel):
    """
    Application mode configuration.

    Determines queue listening behavior and task routing based on deployment mode.

    Attributes:
        mode: The deployment mode (standalone, platform, orchestrator, worker_docker)
        app_name: Unique identifier for this app instance (for task tracking)
    """

    mode: AppMode = Field(
        default=AppMode.STANDALONE,
        description="Application deployment mode"
    )

    app_name: str = Field(
        default=AppModeDefaults.DEFAULT_APP_NAME,
        description="Unique identifier for this app instance (tracked on tasks)"
    )

    # Docker worker integration (08 JAN 2026)
    docker_worker_enabled: bool = Field(
        default=False,
        description="Whether a Docker worker is deployed for long-running tasks. "
                    "When False, standalone mode skips long-running-tasks queue validation."
    )

    docker_worker_url: Optional[str] = Field(
        default=None,
        description="URL of the Docker worker for health checks (e.g., https://{worker-app}.azurewebsites.net). "
                    "Used by health interface to fetch Docker worker status."
    )

    # Orchestrator URL for platform mode (06 FEB 2026)
    orchestrator_url: Optional[str] = Field(
        default=None,
        description="URL of the orchestrator app for API calls (e.g., https://{orchestrator-app}.azurewebsites.net). "
                    "Used by platform mode UI to fetch job data from orchestrator's dbadmin endpoints."
    )

    # =========================================================================
    # QUEUE LISTENING PROPERTIES (V0.8 - 24 JAN 2026)
    # =========================================================================

    @property
    def has_http_endpoints(self) -> bool:
        """Whether this mode serves HTTP endpoints."""
        # Docker worker has no HTTP - it's a background polling process
        if self.mode == AppMode.WORKER_DOCKER:
            return False
        # All other modes have HTTP endpoints for now (per user feedback)
        return True

    @property
    def has_platform_endpoints(self) -> bool:
        """Whether this mode exposes platform/* endpoints (public DDH integration)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.PLATFORM,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_jobs_endpoints(self) -> bool:
        """Whether this mode exposes jobs/* endpoints (submit, status, logs)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_admin_endpoints(self) -> bool:
        """Whether this mode exposes admin endpoints (dbadmin/*, admin/*)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_interface_endpoints(self) -> bool:
        """Whether this mode exposes /api/interface/* endpoints (Web UI)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.PLATFORM,       # Gateway serves UI
            AppMode.ORCHESTRATOR,   # Admin UI access
        ]

    @property
    def has_ogc_endpoints(self) -> bool:
        """Whether this mode exposes OGC Features API (/api/features/*)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_raster_endpoints(self) -> bool:
        """Whether this mode exposes /api/raster/* endpoints."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_storage_endpoints(self) -> bool:
        """Whether this mode exposes /api/storage/* endpoints."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_maps_endpoints(self) -> bool:
        """Whether this mode exposes /api/maps/* endpoints."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_curated_endpoints(self) -> bool:
        """Whether this mode exposes /api/curated/* endpoints."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_system_health_endpoint(self) -> bool:
        """
        Whether this mode exposes /api/system-health (admin infrastructure view).

        Only ORCHESTRATOR and STANDALONE - NOT exposed on PLATFORM (gateway).
        Admins use orchestrator for infrastructure health monitoring.
        """
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def has_timer_triggers(self) -> bool:
        """Whether this mode should register timer triggers (maintenance, monitoring).

        Timer triggers run scheduled maintenance (janitor, geo checks, snapshots,
        log cleanup, external service health). Only standalone and orchestrator
        modes should run these -- the gateway (platform) and Docker worker do not
        need background timers.
        """
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def listens_to_jobs_queue(self) -> bool:
        """Whether this mode processes the jobs queue (orchestration)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def listens_to_container_tasks(self) -> bool:
        """
        Whether this mode processes container-tasks queue (Docker worker).

        In STANDALONE mode, this is only True if docker_worker_enabled=False
        (meaning no Docker worker is deployed, so standalone handles container tasks).
        """
        if self.mode == AppMode.WORKER_DOCKER:
            return True
        if self.mode == AppMode.STANDALONE and not self.docker_worker_enabled:
            return True
        return False

    # =========================================================================
    # ROUTING PROPERTIES
    # =========================================================================

    @property
    def routes_tasks_externally(self) -> bool:
        """
        Whether tasks should be routed to external queues (not processed locally).

        In Platform mode, all tasks route to jobs queue for orchestrator.
        In Orchestrator mode, tasks route to container-tasks or functionapp-tasks.
        """
        return self.mode in [
            AppMode.PLATFORM,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def is_worker_mode(self) -> bool:
        """Whether this is a worker-only mode (no orchestration)."""
        return self.mode == AppMode.WORKER_DOCKER

    @property
    def is_platform_mode(self) -> bool:
        """Whether this mode handles job orchestration."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
        ]

    @property
    def is_gateway_mode(self) -> bool:
        """Whether this is the Platform/Gateway mode (public-facing, HTTP only)."""
        return self.mode == AppMode.PLATFORM

    @property
    def is_orchestrator_mode(self) -> bool:
        """Whether this is the Orchestrator-only mode (internal, jobs queue listener)."""
        return self.mode == AppMode.ORCHESTRATOR

    # =========================================================================
    # FACTORY METHOD
    # =========================================================================

    @classmethod
    def from_environment(cls) -> "AppModeConfig":
        """
        Load configuration from environment variables.

        Environment Variables:
            APP_MODE: Deployment mode (default: AppModeDefaults.DEFAULT_MODE)
            APP_NAME: Unique app identifier (default: AppModeDefaults.DEFAULT_APP_NAME)
            DOCKER_WORKER_ENABLED: Enable container-tasks queue validation (default: False)
                                   Set to "true" when a Docker worker is deployed.

        Raises:
            ValueError: If APP_MODE is not a valid mode
            ValueError: If WORKER_DOCKER mode is used in Azure Functions runtime
        """
        mode_str = os.environ.get("APP_MODE", AppModeDefaults.DEFAULT_MODE)

        # Validate mode - NO FALLBACKS, fail explicitly on invalid config
        try:
            mode = AppMode(mode_str)
        except ValueError:
            valid_modes = [m.value for m in AppMode]

            # Log to Application Insights BEFORE raising exception
            # This ensures the error is queryable even after the app fails to start
            # Query with: traces | where message contains 'STARTUP_FAILED'
            import logging
            startup_logger = logging.getLogger("startup")
            startup_logger.critical(
                f"❌ STARTUP_FAILED: Invalid APP_MODE='{mode_str}'. "
                f"Valid modes: {valid_modes}"
            )

            # Provide migration hints for deprecated modes
            migration_hints = {
                "gateway": "platform",
                "platform_only": "orchestrator",
                "platform_raster": "orchestrator",
                "platform_vector": "orchestrator",
                "worker_raster": "worker_docker",
                "worker_vector": "worker_docker",
                "worker_functionapp": "worker_docker",
            }
            migration_msg = ""
            if mode_str in migration_hints:
                migration_msg = f"\n\nMIGRATION: '{mode_str}' was deprecated in V0.8. Use '{migration_hints[mode_str]}' instead.\n"

            raise ValueError(
                f"\n{'='*80}\n"
                f"FATAL: Invalid APP_MODE environment variable\n"
                f"{'='*80}\n"
                f"Provided: APP_MODE='{mode_str}'\n"
                f"Valid modes: {valid_modes}\n"
                f"{migration_msg}"
                f"\nV0.9 Modes (19 FEB 2026):\n"
                f"  standalone         - All queues, all HTTP (development)\n"
                f"  platform           - HTTP gateway only, sends to jobs queue\n"
                f"  orchestrator       - Jobs queue listener + all HTTP endpoints\n"
                f"  worker_docker      - container-tasks queue (Docker container)\n"
                f"\n"
                f"Fix: Set APP_MODE to one of the valid modes.\n"
                f"{'='*80}\n"
            )

        # Runtime environment validation (22 DEC 2025)
        # Detect Azure Functions runtime via FUNCTIONS_WORKER_RUNTIME env var
        is_azure_functions = os.environ.get("FUNCTIONS_WORKER_RUNTIME") is not None

        if mode == AppMode.WORKER_DOCKER and is_azure_functions:
            # Log to Application Insights BEFORE raising exception
            startup_logger.critical(
                f"❌ STARTUP_FAILED: APP_MODE='worker_docker' cannot run in Azure Functions. "
                f"FUNCTIONS_WORKER_RUNTIME='{os.environ.get('FUNCTIONS_WORKER_RUNTIME')}'"
            )
            raise ValueError(
                f"INVALID CONFIGURATION: APP_MODE='{mode.value}' cannot be used in Azure Functions. "
                f"WORKER_DOCKER mode is only valid in Docker containers. "
                f"Detected FUNCTIONS_WORKER_RUNTIME='{os.environ.get('FUNCTIONS_WORKER_RUNTIME')}'. "
                f"For Azure Functions, use: standalone, platform, or orchestrator."
            )

        if mode != AppMode.WORKER_DOCKER and not is_azure_functions:
            # Not in Azure Functions and not Docker mode - log warning (might be local dev)
            import logging
            logger = logging.getLogger(__name__)
            logger.info(
                f"APP_MODE='{mode.value}' running outside Azure Functions runtime. "
                f"This is expected for local development or Docker with non-Docker mode."
            )

        # Docker worker integration (08 JAN 2026)
        # Parse as boolean: "true", "1", "yes" → True, anything else → False
        docker_worker_str = os.environ.get("DOCKER_WORKER_ENABLED", "").lower()
        docker_worker_enabled = docker_worker_str in ("true", "1", "yes")
        docker_worker_url = os.environ.get("DOCKER_WORKER_URL")

        # Orchestrator URL for platform mode (06 FEB 2026)
        orchestrator_url = os.environ.get("ORCHESTRATOR_URL")

        return cls(
            mode=mode,
            app_name=os.environ.get("APP_NAME", AppModeDefaults.DEFAULT_APP_NAME),
            docker_worker_enabled=docker_worker_enabled,
            docker_worker_url=docker_worker_url,
            orchestrator_url=orchestrator_url,
        )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @property
    def is_docker_mode(self) -> bool:
        """Whether this is the Docker worker mode."""
        return self.mode == AppMode.WORKER_DOCKER

    def describe(self) -> dict:
        """Return a dictionary describing the current configuration."""
        return {
            "mode": self.mode.value,
            "app_name": self.app_name,
            "docker_worker_enabled": self.docker_worker_enabled,
            "queues_listening": {
                "jobs": self.listens_to_jobs_queue,
                "container_tasks": self.listens_to_container_tasks,
            },
            "endpoints": {
                "has_platform": self.has_platform_endpoints,
                "has_jobs": self.has_jobs_endpoints,
                "has_admin": self.has_admin_endpoints,
                "has_interface": self.has_interface_endpoints,
                "has_ogc": self.has_ogc_endpoints,
                "has_raster": self.has_raster_endpoints,
                "has_storage": self.has_storage_endpoints,
                "has_maps": self.has_maps_endpoints,
                "has_curated": self.has_curated_endpoints,
                "has_system_health": self.has_system_health_endpoint,
            },
            "routing": {
                "routes_tasks_externally": self.routes_tasks_externally,  # V0.8
            },
            "role": {
                "is_gateway": self.is_gateway_mode,
                "is_orchestrator": self.is_orchestrator_mode,
                "is_platform": self.is_platform_mode,
                "is_worker": self.is_worker_mode,
                "is_docker": self.is_docker_mode,
                "has_http": self.has_http_endpoints,
            },
            "external_apps": {
                "docker_worker_url": self.docker_worker_url,
                "orchestrator_url": self.orchestrator_url,
            },
        }


# =============================================================================
# MODULE-LEVEL SINGLETON (for import-time access in function_app.py)
# =============================================================================

# Create singleton instance for use at module import time
# This is needed because Azure Functions decorators are evaluated at import
_app_mode_config: Optional[AppModeConfig] = None
_app_mode_lock = threading.Lock()


def get_app_mode_config() -> AppModeConfig:
    """
    Get the singleton AppModeConfig instance.

    Lazily initializes from environment on first call.
    Thread-safe via double-checked locking pattern.
    """
    global _app_mode_config
    if _app_mode_config is None:
        with _app_mode_lock:
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
