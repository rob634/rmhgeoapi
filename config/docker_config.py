# ============================================================================
# DOCKER WORKER CONFIGURATION
# ============================================================================
# STATUS: Configuration - Shared Docker worker settings
# PURPOSE: Configure ETL mount settings shared by raster and vector pipelines
# LAST_REVIEWED: 26 FEB 2026
# ============================================================================
"""
Docker Worker Configuration.

Configures Azure Files mount settings used by both raster and vector
pipelines on the Docker worker. Extracted from RasterConfig (V0.9, 26 FEB 2026)
so vector processing can use the same mount for large file streaming.

Environment Variables:
    DOCKER_USE_ETL_MOUNT      = true       (mount enabled, false = degraded)
    DOCKER_ETL_MOUNT_PATH     = /mounts/etl-temp  (Azure Files mount path)

Exports:
    DockerConfig: Pydantic configuration model
"""

import os
from pydantic import BaseModel, Field

from .defaults import DockerDefaults


class DockerConfig(BaseModel):
    """
    Docker worker configuration - shared by raster and vector pipelines.

    Controls Azure Files mount used for temp file staging on Docker workers.
    Both raster (GDAL CPL_TMPDIR) and vector (file streaming) use this mount.

    Key Settings:
        use_etl_mount: Expected True in production (False = degraded state)
        etl_mount_path: Azure Files mount path in Docker container
    """

    use_etl_mount: bool = Field(
        default=DockerDefaults.USE_ETL_MOUNT,
        description="""Enable Azure Files mount for Docker temp files.

        Expected True in production. False indicates degraded state.

        When True (mount enabled - expected state):
        - Docker workers use /mounts/etl-temp for GDAL temp files (CPL_TMPDIR)
        - Vector files streamed to mount before loading (avoids RAM duplication)
        - No size limit for processing (mount provides ~100TB)

        When False (mount disabled - degraded state):
        - Docker startup logs warning
        - Raster: Limited to smaller files that fit in container temp space
        - Vector: Falls back to in-memory loading (BytesIO)

        Docker worker validates mount at startup.
        """
    )

    etl_mount_path: str = Field(
        default=DockerDefaults.ETL_MOUNT_PATH,
        description="Path where Azure Files is mounted in Docker container"
    )

    @classmethod
    def from_environment(cls) -> "DockerConfig":
        """Load from environment variables."""
        use_mount_raw = (
            os.environ.get("DOCKER_USE_ETL_MOUNT")
            or str(DockerDefaults.USE_ETL_MOUNT).lower()
        )
        mount_path = (
            os.environ.get("DOCKER_ETL_MOUNT_PATH")
            or DockerDefaults.ETL_MOUNT_PATH
        )

        return cls(
            use_etl_mount=use_mount_raw.lower() == "true",
            etl_mount_path=mount_path,
        )

    def debug_dict(self) -> dict:
        """Return safe debug representation."""
        return {
            "use_etl_mount": self.use_etl_mount,
            "etl_mount_path": self.etl_mount_path,
        }
