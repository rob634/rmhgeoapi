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
    DOCKER_USE_ETL_MOUNT      = true       (mount enabled, false = degraded)
    RASTER_ETL_MOUNT_PATH     = /mount/etl-temp  (Azure Files mount path — REQUIRED)

Exports:
    DockerConfig: Pydantic configuration model
"""

import os
import logging
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import DockerDefaults

logger = logging.getLogger(__name__)


class DockerConfig(BaseModel):
    """
    Docker worker configuration - shared by raster and vector pipelines.

    Controls Azure Files mount used for temp file staging on Docker workers.
    Both raster (GDAL CPL_TMPDIR) and vector (file streaming) use this mount.

    Key Settings:
        use_etl_mount: Expected True in production (False = degraded state)
        etl_mount_path: Azure Files mount path — MUST be set via RASTER_ETL_MOUNT_PATH
    """

    use_etl_mount: bool = Field(
        default=DockerDefaults.USE_ETL_MOUNT,
        description="""Enable Azure Files mount for Docker temp files.

        Expected True in production. False indicates degraded state.

        When True (mount enabled - expected state):
        - Docker workers use mount for GDAL temp files (CPL_TMPDIR)
        - Vector files streamed to mount before loading (avoids RAM duplication)
        - No size limit for processing (mount provides ~100TB)

        When False (mount disabled - degraded state):
        - Docker startup logs warning
        - Raster: Limited to smaller files that fit in container temp space
        - Vector: Falls back to in-memory loading (BytesIO)

        Docker worker validates mount at startup.
        """
    )

    etl_mount_path: Optional[str] = Field(
        default=None,
        description="Path where Azure Files is mounted in Docker container. Set via RASTER_ETL_MOUNT_PATH."
    )

    @classmethod
    def from_environment(cls) -> "DockerConfig":
        """Load from environment variables.

        RASTER_ETL_MOUNT_PATH is REQUIRED when DOCKER_USE_ETL_MOUNT=true.
        No default path — must be set explicitly to prevent silent misconfiguration.
        """
        use_mount_raw = (
            os.environ.get("DOCKER_USE_ETL_MOUNT")
            or str(DockerDefaults.USE_ETL_MOUNT).lower()
        )
        use_mount = use_mount_raw.lower() == "true"

        mount_path = os.environ.get("RASTER_ETL_MOUNT_PATH")

        if use_mount and not mount_path:
            logger.error("=" * 60)
            logger.error("❌ RASTER_ETL_MOUNT_PATH is NOT SET")
            logger.error("=" * 60)
            logger.error("  DOCKER_USE_ETL_MOUNT=true but no mount path configured.")
            logger.error("  Please set RASTER_ETL_MOUNT_PATH to the Azure Files mount path.")
            logger.error("  Example: RASTER_ETL_MOUNT_PATH=/mount/etl-temp")
            logger.error("=" * 60)

        return cls(
            use_etl_mount=use_mount,
            etl_mount_path=mount_path,
        )

    def debug_dict(self) -> dict:
        """Return safe debug representation."""
        return {
            "use_etl_mount": self.use_etl_mount,
            "etl_mount_path": self.etl_mount_path,
        }
