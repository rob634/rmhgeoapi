# ============================================================================
# APPLICATION MODE CONFIGURATION
# ============================================================================
# STATUS: Configuration - Multi-Function App deployment modes
# PURPOSE: Control queue listening behavior and task routing per deployment
# LAST_REVIEWED: 15 JAN 2026
# REVIEW_STATUS: Gateway/Orchestrator separation - multi-app architecture
# ============================================================================
"""
Application Mode Configuration.

================================================================================
CORPORATE QA/PROD DEPLOYMENT GUIDE
================================================================================

This module controls deployment modes for multi-Function App architecture.
The APP_MODE environment variable determines queue listening and routing behavior.

--------------------------------------------------------------------------------
DEPLOYMENT MODES
--------------------------------------------------------------------------------

1. STANDALONE (Default - Development)
   ---------------------------------
   Single Function App handles everything:
   - Listens to: geospatial-jobs, raster-tasks, vector-tasks
   - Serves: All HTTP endpoints
   - Use case: Development, small deployments

   Environment:
       APP_MODE = standalone

2. GATEWAY (Public Entry Point - 15 JAN 2026)
   -------------------------------------------
   Public-facing HTTP gateway - sends to jobs queue:
   - Listens to: NOTHING (send-only)
   - Serves: platform/* HTTP endpoints only
   - Use case: Public-facing API, walled off from internal services

   Environment:
       APP_MODE = gateway

3. ORCHESTRATOR (Internal Job Router - 15 JAN 2026)
   -------------------------------------------------
   Internal jobs queue processor - admin HTTP only:
   - Listens to: geospatial-jobs only
   - Serves: dbadmin/*, admin/*, jobs/* HTTP endpoints (internal)
   - Routes: Tasks to worker queues
   - Use case: Internal orchestration, not publicly accessible

   Environment:
       APP_MODE = orchestrator

4. PLATFORM_ONLY (Legacy Combined Mode)
   ------------------------------------
   Combined gateway + orchestrator (original design):
   - Listens to: geospatial-jobs only
   - Serves: All HTTP endpoints (platform/*, jobs/*, admin/*)
   - Routes: Raster/vector tasks to external queues

   Environment:
       APP_MODE = platform_only

5. WORKER_RASTER / WORKER_VECTOR (Dedicated Workers)
   --------------------------------------------------
   Headless workers - no HTTP endpoints:
   - Listens to: raster-tasks OR vector-tasks only
   - No HTTP: Service Bus triggered only
   - Use case: Scale-out architecture

   Environment:
       APP_MODE = worker_raster
       APP_MODE = worker_vector

6. WORKER_DOCKER (Long-Running Tasks)
   -----------------------------------
   Docker container for tasks exceeding Function App timeout:
   - Listens to: long-running-tasks queue only
   - No Function App timeout constraints (can run hours)
   - Cannot run in Azure Functions runtime (validated at startup)

   Environment:
       APP_MODE = worker_docker

   Note: Requires custom Docker deployment, not Azure Functions.

--------------------------------------------------------------------------------
MULTI-APP ARCHITECTURE (Scale-Out)
--------------------------------------------------------------------------------

Service Request Template for QA/PROD:
    "Deploy multi-Function App geospatial architecture:

     Platform App (Orchestrator):
     - Name: {app-name}-platform
     - APP_MODE: platform_only
     - SKU: B2 Basic (orchestration is lightweight)

     Raster Worker App:
     - Name: {app-name}-raster
     - APP_MODE: worker_raster
     - SKU: B3 Premium (memory-intensive GDAL)

     Vector Worker App:
     - Name: {app-name}-vector
     - APP_MODE: worker_vector
     - SKU: B2 Basic (DB-bound operations)

     All apps share:
     - Same Service Bus namespace
     - Same PostgreSQL database
     - Same Storage account"

--------------------------------------------------------------------------------
ENVIRONMENT VARIABLES
--------------------------------------------------------------------------------

Required:
    APP_MODE = standalone | gateway | orchestrator | platform_only | platform_raster | platform_vector | worker_raster | worker_vector | worker_docker

Optional:
    APP_NAME = {unique-app-identifier}  # Tracked on tasks for debugging
    RASTER_APP_URL = https://{raster-app}.azurewebsites.net  # Future cross-app routing
    VECTOR_APP_URL = https://{vector-app}.azurewebsites.net  # Future cross-app routing
    DOCKER_WORKER_ENABLED = true | false  # Enable long-running-tasks queue validation (default: false)

--------------------------------------------------------------------------------
DEPLOYMENT VERIFICATION
--------------------------------------------------------------------------------

Check app mode after deployment:

    curl https://{app-url}/api/health

Expected response includes:
    "app_mode": {
        "mode": "standalone",
        "queues_listening": {
            "jobs": true,
            "raster_tasks": true,
            "vector_tasks": true
        }
    }

Common Failure Messages:
    ValueError: Invalid APP_MODE='{value}'
        → Set APP_MODE to one of the valid modes

    ValueError: APP_MODE='worker_docker' cannot run in Azure Functions
        → Deploy WORKER_DOCKER mode in Docker container only

--------------------------------------------------------------------------------
EXPORTS
--------------------------------------------------------------------------------

    AppMode: Enum of valid application modes
    AppModeConfig: Pydantic configuration model
    get_app_mode_config(): Singleton accessor

--------------------------------------------------------------------------------
USAGE EXAMPLE
--------------------------------------------------------------------------------

    from config.app_mode_config import AppModeConfig, AppMode

    config = AppModeConfig.from_environment()
    if config.listens_to_raster_tasks:
        # Register raster task queue trigger
        pass
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
    - Which HTTP endpoints are exposed
    - How tasks are routed

    Multi-App Architecture (15 JAN 2026):
    - GATEWAY: Public-facing, HTTP only, sends to jobs queue (no listeners)
    - ORCHESTRATOR: Internal, listens to jobs queue, admin HTTP only

    Docker Worker Mode (22 DEC 2025):
    - WORKER_DOCKER: Runs in Docker container, listens to long-running-raster-tasks queue
    - No Azure Functions timeout constraints (can run hours/days)
    - Uses same CoreMachine.process_task_message() as Function App workers
    - Signals stage_complete to jobs queue when last task completes
    """

    STANDALONE = "standalone"           # All queues, all endpoints (default)
    GATEWAY = "gateway"                 # HTTP only (platform/*), sends to jobs queue, no listeners
    ORCHESTRATOR = "orchestrator"       # Jobs queue listener, admin HTTP only (internal)
    PLATFORM_RASTER = "platform_raster" # HTTP + jobs + raster-tasks
    PLATFORM_VECTOR = "platform_vector" # HTTP + jobs + vector-tasks
    PLATFORM_ONLY = "platform_only"     # HTTP + jobs only (pure router)
    WORKER_RASTER = "worker_raster"     # raster-tasks only
    WORKER_VECTOR = "worker_vector"     # vector-tasks only
    WORKER_DOCKER = "worker_docker"     # long-running-raster-tasks only (Docker)


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

    # Docker worker integration (08 JAN 2026)
    docker_worker_enabled: bool = Field(
        default=False,
        description="Whether a Docker worker is deployed for long-running tasks. "
                    "When False, standalone mode skips long-running-tasks queue validation."
    )

    docker_worker_url: Optional[str] = Field(
        default=None,
        description="URL of the Docker worker for health checks (e.g., https://rmhheavyapi.azurewebsites.net). "
                    "Used by health interface to fetch Docker worker status."
    )

    # =========================================================================
    # QUEUE LISTENING PROPERTIES
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
            AppMode.GATEWAY,          # Gateway's primary purpose
            AppMode.PLATFORM_ONLY,    # Legacy combined mode
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
        ]

    @property
    def has_jobs_endpoints(self) -> bool:
        """Whether this mode exposes jobs/* endpoints (submit, status, logs)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,     # Internal job management
            AppMode.PLATFORM_ONLY,    # Legacy combined mode
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
        ]

    @property
    def has_admin_endpoints(self) -> bool:
        """Whether this mode exposes admin endpoints (dbadmin/*, admin/*)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,
            AppMode.PLATFORM_ONLY,    # Legacy
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
            AppMode.WORKER_RASTER,    # Workers may need admin for debugging
            AppMode.WORKER_VECTOR,
        ]

    @property
    def listens_to_jobs_queue(self) -> bool:
        """Whether this mode processes the jobs queue (orchestration)."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,     # Orchestrator listens to jobs queue
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
            AppMode.PLATFORM_ONLY,
            # GATEWAY NOT included - sends to jobs queue but doesn't listen
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

    @property
    def listens_to_long_running_tasks(self) -> bool:
        """
        Whether this mode processes long-running tasks (Docker worker queue).

        In STANDALONE mode, this is only True if docker_worker_enabled=True.
        This avoids validating the long-running-tasks queue when no Docker
        worker is deployed.
        """
        if self.mode == AppMode.WORKER_DOCKER:
            # Docker worker always listens to its queue
            return True
        if self.mode == AppMode.STANDALONE and self.docker_worker_enabled:
            # Standalone only listens if Docker worker integration is enabled
            return True
        return False

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
            AppMode.WORKER_DOCKER,
        ]

    @property
    def is_platform_mode(self) -> bool:
        """Whether this mode handles job orchestration."""
        return self.mode in [
            AppMode.STANDALONE,
            AppMode.ORCHESTRATOR,     # Orchestrator is a platform mode (processes jobs queue)
            AppMode.PLATFORM_RASTER,
            AppMode.PLATFORM_VECTOR,
            AppMode.PLATFORM_ONLY,
        ]

    @property
    def is_gateway_mode(self) -> bool:
        """Whether this is the Gateway-only mode (public-facing, HTTP only)."""
        return self.mode == AppMode.GATEWAY

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
            RASTER_APP_URL: External raster app URL (optional)
            VECTOR_APP_URL: External vector app URL (optional)
            DOCKER_WORKER_ENABLED: Enable long-running-tasks queue validation (default: False)
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

            # Now raise with detailed message for local debugging
            raise ValueError(
                f"\n{'='*80}\n"
                f"FATAL: Invalid APP_MODE environment variable\n"
                f"{'='*80}\n"
                f"Provided: APP_MODE='{mode_str}'\n"
                f"Valid modes: {valid_modes}\n"
                f"\n"
                f"Mode descriptions:\n"
                f"  standalone      - All queues, all HTTP endpoints (single app)\n"
                f"  gateway         - HTTP only (platform/*), sends to jobs queue (public-facing)\n"
                f"  orchestrator    - Jobs queue listener, admin HTTP only (internal)\n"
                f"  platform_only   - HTTP + jobs queue only (legacy combined mode)\n"
                f"  platform_raster - HTTP + jobs + raster-tasks queues\n"
                f"  platform_vector - HTTP + jobs + vector-tasks queues\n"
                f"  worker_raster   - raster-tasks queue only (no HTTP)\n"
                f"  worker_vector   - vector-tasks queue only (no HTTP)\n"
                f"  worker_docker   - long-running-tasks queue (Docker container)\n"
                f"\n"
                f"Fix: Set APP_MODE to one of the valid modes in your environment.\n"
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
                f"For Azure Functions, use: standalone, platform_*, or worker_raster/worker_vector."
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

        return cls(
            mode=mode,
            app_name=os.environ.get("APP_NAME", AppModeDefaults.DEFAULT_APP_NAME),
            raster_app_url=os.environ.get("RASTER_APP_URL"),
            vector_app_url=os.environ.get("VECTOR_APP_URL"),
            docker_worker_enabled=docker_worker_enabled,
            docker_worker_url=docker_worker_url,
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
                "raster_tasks": self.listens_to_raster_tasks,
                "vector_tasks": self.listens_to_vector_tasks,
                "long_running_tasks": self.listens_to_long_running_tasks,
            },
            "endpoints": {
                "has_platform": self.has_platform_endpoints,
                "has_jobs": self.has_jobs_endpoints,
                "has_admin": self.has_admin_endpoints,
            },
            "routing": {
                "routes_raster_externally": self.routes_raster_externally,
                "routes_vector_externally": self.routes_vector_externally,
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
                "raster_app_url": self.raster_app_url,
                "vector_app_url": self.vector_app_url,
                "docker_worker_url": self.docker_worker_url,
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
