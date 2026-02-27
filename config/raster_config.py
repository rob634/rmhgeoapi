# ============================================================================
# RASTER PROCESSING CONFIGURATION
# ============================================================================
# STATUS: Configuration - COG creation and raster pipeline settings
# PURPOSE: Configure GDAL/rio-cogeo parameters, routing thresholds, STAC defaults
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Check 8 Applied - Full operational deployment guide
# ============================================================================
"""
Raster Processing Pipeline Configuration.

================================================================================
CORPORATE QA/PROD DEPLOYMENT GUIDE
================================================================================

This module configures raster processing (COG creation, validation, routing).
All defaults are defined in config/defaults.py - override via environment variables.

--------------------------------------------------------------------------------
GDAL/RASTERIO DEPENDENCIES
--------------------------------------------------------------------------------

The raster pipeline requires GDAL with COG driver support.

For Azure Functions:
    GDAL is included in the Python runtime. No additional setup required.
    The Function App uses rio-cogeo for COG creation.

For Docker Workers:
    Dockerfile should include:
        FROM ghcr.io/osgeo/gdal:ubuntu-full-3.8.0
        # Or use requirements.txt with rasterio[s3]

Verify GDAL installation:
    python -c "from osgeo import gdal; print(gdal.__version__)"

--------------------------------------------------------------------------------
ENVIRONMENT VARIABLES
--------------------------------------------------------------------------------

V0.8 Architecture (24 JAN 2026):
    ALL raster processing goes to Docker worker. Tiling decision is internal.

ETL Mount Settings (26 FEB 2026):
    Moved to DockerConfig (config/docker_config.py).
    Use DOCKER_USE_ETL_MOUNT and DOCKER_ETL_MOUNT_PATH env vars.

Tiling Settings:
    RASTER_TILING_THRESHOLD_MB = 500 # Files above this produce tiled output (lowered from 2000 for testing)
    RASTER_TILE_TARGET_MB = 400       # Target tile size for large file splitting
    RASTER_COLLECTION_MAX_FILES = 1000  # Max files per collection

Processing Settings (Handler Layer):
    RASTER_COG_IN_MEMORY = false      # Use disk-based processing (safer)
    RASTER_COG_COMPRESSION = deflate  # COG compression algorithm
    RASTER_COG_TILE_SIZE = 512        # Internal COG tile size (pixels)

Validation Settings:
    RASTER_TARGET_CRS = EPSG:4326     # Target coordinate reference system
    RASTER_STRICT_VALIDATION = true   # Fail on validation warnings

STAC Settings:
    STAC_DEFAULT_COLLECTION = rasters  # Default collection for ad-hoc rasters

--------------------------------------------------------------------------------
STORAGE CONTAINERS
--------------------------------------------------------------------------------

Raster pipeline uses these containers (configure in storage_config.py):
    - bronze-rasters: Input files from DDH
    - silver-cogs: Output COG files
    - silver-tiles: Intermediate tiles (large file processing)

Service Request for new environments:
    "Create storage containers for raster processing:
     - silver-cogs (Hot tier, lifecycle: archive after 90 days)
     - silver-tiles (Hot tier, lifecycle: delete after 7 days)"

--------------------------------------------------------------------------------
MEMORY CONSIDERATIONS
--------------------------------------------------------------------------------

COG creation is memory-intensive. Settings are tuned for Azure Functions B3:

    cog_in_memory = False (default)
        - Uses disk-based processing via /tmp (Azure SSD-backed)
        - Safe for concurrent processing (maxConcurrentCalls=4)
        - 10-20% slower but prevents OOM

    cog_in_memory = True (per-job override)
        - Faster for small files (<500MB)
        - Risk of OOM with concurrent large files
        - Only use for known-small rasters

--------------------------------------------------------------------------------
EXPORTS
--------------------------------------------------------------------------------

    RasterConfig: Pydantic configuration model

Provides configuration for:
    - COG creation settings (compression, tile size, quality)
    - Raster validation settings
    - Size thresholds for pipeline selection
    - MosaicJSON configuration
    - Intermediate file storage

Exports:
    RasterConfig: Pydantic configuration model
"""

import os
from typing import Optional
from pydantic import BaseModel, Field

from .defaults import RasterDefaults, STACDefaults


# ============================================================================
# RASTER CONFIGURATION
# ============================================================================

class RasterConfig(BaseModel):
    """
    Raster processing pipeline configuration.

    Controls COG creation, validation, and processing settings.

    V0.8 Architecture (24 JAN 2026):
        - ALL raster operations run on Docker worker
        - ETL mount (Azure Files) is REQUIRED for production
        - Single workflow (process_raster_docker) handles both single COG and tiled output
        - Tiling decision is internal based on raster_tiling_threshold_mb

    Key Settings:
        raster_tiling_threshold_mb: When to produce tiled output vs single COG
        raster_tile_target_mb: Target size per tile when tiling

    Note (26 FEB 2026):
        ETL mount settings (use_etl_mount, etl_mount_path) moved to DockerConfig.
        Access via config.docker.use_etl_mount / config.docker.etl_mount_path.
    """

    # ==========================================================================
    # TILING SETTINGS (V0.8 - 24 JAN 2026)
    # ==========================================================================

    raster_tiling_threshold_mb: int = Field(
        default=RasterDefaults.RASTER_TILING_THRESHOLD_MB,
        description="File size threshold (MB) for tiled output vs single COG. "
                    "Files above this produce N tiles, below produces single COG."
    )

    raster_tile_target_mb: int = Field(
        default=RasterDefaults.RASTER_TILE_TARGET_MB,
        description="Target size (MB) per tile when tiling large rasters."
    )

    raster_collection_max_files: int = Field(
        default=RasterDefaults.RASTER_COLLECTION_MAX_FILES,
        description="Max files allowed in a raster collection submission."
    )

    # Intermediate storage
    intermediate_tiles_container: Optional[str] = Field(
        default=None,
        description="Container for intermediate raster tiles (Stage 2 output). If None, defaults to silver-tiles. Cleanup handled by separate timer trigger (NOT in ETL workflow).",
        examples=["silver-tiles", "bronze-rasters", "silver-temp"]
    )

    intermediate_prefix: str = Field(
        default=RasterDefaults.INTERMEDIATE_PREFIX,
        description="Blob path prefix for raster ETL intermediate files (large file tiles)",
        examples=["temp/raster_etl", "intermediate/raster"]
    )

    # COG creation settings
    cog_compression: str = Field(
        default=RasterDefaults.COG_COMPRESSION,
        description="Default compression algorithm for COG creation",
        examples=["deflate", "lzw", "zstd", "jpeg", "webp", "lerc_deflate"]
    )

    cog_jpeg_quality: int = Field(
        default=RasterDefaults.COG_JPEG_QUALITY,
        ge=1,
        le=100,
        description="JPEG quality for lossy compression (1-100, only applies to jpeg/webp)"
    )

    cog_tile_size: int = Field(
        default=RasterDefaults.COG_TILE_SIZE,
        description="Internal tile size for COG (pixels)"
    )

    cog_in_memory: bool = Field(
        default=RasterDefaults.COG_IN_MEMORY,
        description="""Default setting for COG processing mode (in-memory vs disk-based).

        WHY FALSE (29 NOV 2025):
        - With maxConcurrentCalls=4, multiple raster jobs can run simultaneously
        - Each in-memory raster can use 2+ GB RAM during reprojection
        - 4 concurrent × 2 GB = 8 GB = OOM risk on 8 GB plan
        - Disk-based uses Azure Functions SSD-backed /tmp (fast, safe)
        - 10-20% speed penalty is worth the stability

        Can be overridden per-job via 'in_memory' parameter.
        In-memory (True) is faster for small files (<500MB) but risky with concurrency.
        Disk-based (False) uses local SSD temp storage, handles any file size safely.
        """
    )

    # Validation settings
    target_crs: str = Field(
        default=RasterDefaults.TARGET_CRS,
        description="Target CRS for reprojection (WGS84)",
        examples=["EPSG:4326", "EPSG:3857"]
    )

    overview_resampling: str = Field(
        default=RasterDefaults.OVERVIEW_RESAMPLING,
        description="Resampling method for overview generation",
        examples=["average", "bilinear", "cubic", "nearest"]
    )

    reproject_resampling: str = Field(
        default=RasterDefaults.REPROJECT_RESAMPLING,
        description="Resampling method for reprojection",
        examples=["bilinear", "cubic", "nearest", "lanczos"]
    )

    strict_validation: bool = Field(
        default=RasterDefaults.STRICT_VALIDATION,
        description="Enable strict validation (fails on warnings)"
    )

    # MosaicJSON settings
    mosaicjson_maxzoom: int = Field(
        default=RasterDefaults.MOSAICJSON_MAXZOOM,
        ge=0,
        le=24,
        description="Default maximum zoom level for MosaicJSON tile serving. "
                    "Can be overridden per-job via 'maxzoom' parameter. "
                    "Zoom 18 = 0.60m/pixel (standard satellite), "
                    "Zoom 19 = 0.30m/pixel (high-res satellite), "
                    "Zoom 20 = 0.15m/pixel (drone imagery), "
                    "Zoom 21 = 0.07m/pixel (very high-res drone). "
                    "Set based on your imagery's native resolution."
    )

    # stac_default_collection removed (14 JAN 2026)
    # collection_id is now a required parameter for all raster jobs - no more "system-rasters" catch-all

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(
            # ETL mount settings moved to DockerConfig (26 FEB 2026)
            # V0.8 Tiling settings (24 JAN 2026)
            raster_tiling_threshold_mb=int(os.environ.get(
                "RASTER_TILING_THRESHOLD_MB",
                str(RasterDefaults.RASTER_TILING_THRESHOLD_MB)
            )),
            raster_tile_target_mb=int(os.environ.get(
                "RASTER_TILE_TARGET_MB",
                str(RasterDefaults.RASTER_TILE_TARGET_MB)
            )),
            raster_collection_max_files=int(os.environ.get(
                "RASTER_COLLECTION_MAX_FILES",
                str(RasterDefaults.RASTER_COLLECTION_MAX_FILES)
            )),
            # Intermediate storage
            intermediate_tiles_container=os.environ.get("INTERMEDIATE_TILES_CONTAINER"),
            intermediate_prefix=os.environ.get("RASTER_INTERMEDIATE_PREFIX", RasterDefaults.INTERMEDIATE_PREFIX),
            # COG settings
            cog_compression=os.environ.get("RASTER_COG_COMPRESSION", RasterDefaults.COG_COMPRESSION),
            cog_jpeg_quality=int(os.environ.get("RASTER_COG_JPEG_QUALITY", str(RasterDefaults.COG_JPEG_QUALITY))),
            cog_tile_size=int(os.environ.get("RASTER_COG_TILE_SIZE", str(RasterDefaults.COG_TILE_SIZE))),
            cog_in_memory=os.environ.get("RASTER_COG_IN_MEMORY", str(RasterDefaults.COG_IN_MEMORY).lower()).lower() == "true",
            # Validation settings
            target_crs=os.environ.get("RASTER_TARGET_CRS", RasterDefaults.TARGET_CRS),
            overview_resampling=os.environ.get("RASTER_OVERVIEW_RESAMPLING", RasterDefaults.OVERVIEW_RESAMPLING),
            reproject_resampling=os.environ.get("RASTER_REPROJECT_RESAMPLING", RasterDefaults.REPROJECT_RESAMPLING),
            strict_validation=os.environ.get("RASTER_STRICT_VALIDATION", str(RasterDefaults.STRICT_VALIDATION).lower()).lower() == "true",
            # MosaicJSON
            mosaicjson_maxzoom=int(os.environ.get("RASTER_MOSAICJSON_MAXZOOM", str(RasterDefaults.MOSAICJSON_MAXZOOM))),
            # stac_default_collection removed (14 JAN 2026) - collection_id required
        )
