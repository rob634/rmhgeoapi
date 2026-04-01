# ============================================================================
# DOCKER WORKER CONFIGURATION
# ============================================================================
# STATUS: Configuration - Shared Docker worker settings
# PURPOSE: Configure ETL mount settings shared by raster and vector pipelines
# LAST_REVIEWED: 05 MAR 2026
# ============================================================================
"""
Docker Worker Configuration.

Configures Azure Files mount settings used by both raster and vector
pipelines on the Docker worker. Extracted from RasterConfig (V0.9, 26 FEB 2026)
so vector processing can use the same mount for large file streaming.

Environment Variables:
    RASTER_ETL_MOUNT_PATH     = /mount/etl-temp  (Azure Files mount path)

Mount availability is derived from APP_MODE:
    worker_docker  → RASTER_ETL_MOUNT_PATH is REQUIRED (reports unhealthy without it)
    anything else  → no mount, etl_mount_path is None

Exports:
    DockerConfig: Pydantic configuration model
"""

import os
import logging
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DockerConfig(BaseModel):
    """
    Docker worker configuration - shared by raster and vector pipelines.

    Controls Azure Files mount used for temp file staging on Docker workers.
    Both raster (GDAL CPL_TMPDIR) and vector (file streaming) use this mount.

    Mount availability is derived from APP_MODE, not a toggle:
        worker_docker  → etl_mount_path is REQUIRED (health reports unhealthy without it)
        anything else  → etl_mount_path is None

    The app NEVER fails to start. Missing mount → /health reports unhealthy with
    actionable error messages. /livez stays responsive (infrastructure probe).
    """

    etl_mount_path: Optional[str] = Field(
        default=None,
        description="Path where Azure Files is mounted in Docker container. Set via RASTER_ETL_MOUNT_PATH."
    )

    mount_error: Optional[str] = Field(
        default=None,
        description="Set when APP_MODE=worker_docker but RASTER_ETL_MOUNT_PATH is missing."
    )

    @classmethod
    def from_environment(cls) -> "DockerConfig":
        """Load from environment variables.

        APP_MODE=worker_docker → RASTER_ETL_MOUNT_PATH is REQUIRED.
        Any other APP_MODE     → no mount, etl_mount_path stays None.

        Never raises — missing config is surfaced via mount_error and /health.
        """
        app_mode = os.environ.get("APP_MODE", "").lower()

        if app_mode != "worker_docker":
            return cls(etl_mount_path=None)

        # Docker worker: mount path is mandatory
        mount_path = os.environ.get("RASTER_ETL_MOUNT_PATH")
        if not mount_path:
            error_msg = (
                "RASTER_ETL_MOUNT_PATH is required for APP_MODE=worker_docker. "
                "Set RASTER_ETL_MOUNT_PATH to the Azure Files mount path "
                "(e.g. /mount/etl-temp)."
            )
            logger.error("=" * 60)
            logger.error("❌ RASTER_ETL_MOUNT_PATH is NOT SET")
            logger.error("=" * 60)
            logger.error("  APP_MODE=worker_docker requires an ETL mount.")
            logger.error("  Set RASTER_ETL_MOUNT_PATH to the Azure Files mount path.")
            logger.error("  Example: RASTER_ETL_MOUNT_PATH=/mount/etl-temp")
            logger.error("  /health will report UNHEALTHY until this is fixed.")
            logger.error("=" * 60)
            return cls(etl_mount_path=None, mount_error=error_msg)

        return cls(etl_mount_path=mount_path)

    def debug_dict(self) -> dict:
        """Return safe debug representation."""
        return {
            "etl_mount_path": self.etl_mount_path,
        }
