# ============================================================================
# CLAUDE CONTEXT - RASTER CONFIGURATION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New module - Phase 1 of config.py refactoring (20 NOV 2025)
# PURPOSE: Raster processing pipeline configuration
# LAST_REVIEWED: 20 NOV 2025
# EXPORTS: RasterConfig
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: RasterConfig
# DEPENDENCIES: pydantic, os, typing
# SOURCE: Environment variables (RASTER_*)
# SCOPE: Raster-specific configuration
# VALIDATION: Pydantic v2 validation with ranges
# PATTERNS: Value objects, factory methods
# ENTRY_POINTS: from config import RasterConfig
# INDEX: RasterConfig:37
# ============================================================================

"""
Raster Processing Pipeline Configuration

Provides configuration for:
- COG creation settings (compression, tile size, quality)
- Raster validation settings
- Size thresholds for pipeline selection
- MosaicJSON configuration
- Intermediate file storage

This module was extracted from config.py (lines 564-641) as part of the
god object refactoring (20 NOV 2025).
"""

import os
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================================
# RASTER CONFIGURATION
# ============================================================================

class RasterConfig(BaseModel):
    """
    Raster processing pipeline configuration.

    Controls COG creation, validation, and processing settings.
    """

    # Pipeline selection
    size_threshold_mb: int = Field(
        default=1000,  # 1 GB
        description="File size threshold (MB) for pipeline selection (small vs large file)"
    )

    # Intermediate storage
    intermediate_tiles_container: Optional[str] = Field(
        default=None,
        description="Container for intermediate raster tiles (Stage 2 output). If None, defaults to silver-tiles. Cleanup handled by separate timer trigger (NOT in ETL workflow).",
        examples=["silver-tiles", "bronze-rasters", "silver-temp"]
    )

    intermediate_prefix: str = Field(
        default="temp/raster_etl",
        description="Blob path prefix for raster ETL intermediate files (large file tiles)",
        examples=["temp/raster_etl", "intermediate/raster"]
    )

    # COG creation settings
    cog_compression: str = Field(
        default="deflate",
        description="Default compression algorithm for COG creation",
        examples=["deflate", "lzw", "zstd", "jpeg", "webp", "lerc_deflate"]
    )

    cog_jpeg_quality: int = Field(
        default=85,
        ge=1,
        le=100,
        description="JPEG quality for lossy compression (1-100, only applies to jpeg/webp)"
    )

    cog_tile_size: int = Field(
        default=512,
        description="Internal tile size for COG (pixels)"
    )

    cog_in_memory: bool = Field(
        default=True,
        description="Default setting for COG processing mode (in-memory vs disk-based). "
                    "Can be overridden per-job via 'in_memory' parameter. "
                    "In-memory (True) is faster for small files (<1GB) but uses more RAM. "
                    "Disk-based (False) uses local SSD temp storage, better for large files."
    )

    # Validation settings
    target_crs: str = Field(
        default="EPSG:4326",
        description="Target CRS for reprojection (WGS84)",
        examples=["EPSG:4326", "EPSG:3857"]
    )

    overview_resampling: str = Field(
        default="average",
        description="Resampling method for overview generation",
        examples=["average", "bilinear", "cubic", "nearest"]
    )

    reproject_resampling: str = Field(
        default="bilinear",
        description="Resampling method for reprojection",
        examples=["bilinear", "cubic", "nearest", "lanczos"]
    )

    strict_validation: bool = Field(
        default=True,
        description="Enable strict validation (fails on warnings)"
    )

    # MosaicJSON settings
    mosaicjson_maxzoom: int = Field(
        default=19,
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

    # STAC configuration
    stac_default_collection: str = Field(
        default="system-rasters",
        description="""Default STAC collection for standalone raster processing.

        Purpose:
            System-managed collection for individual raster files processed via
            process_raster job (as opposed to organized datasets in dedicated collections).

        Behavior:
            - Auto-created if missing when first raster is processed
            - Used when collection_id parameter is not specified in process_raster
            - Separate from user-defined collections for organized datasets

        Usage:
            - process_raster jobs default to this collection
            - Users can override with collection_id parameter
            - Collection is auto-created with warning if doesn't exist

        Note: This separates "ad-hoc individual files" from "organized datasets"
        """
    )

    @classmethod
    def from_environment(cls):
        """Load from environment variables."""
        return cls(
            size_threshold_mb=int(os.environ.get("RASTER_SIZE_THRESHOLD_MB", "1000")),
            intermediate_tiles_container=os.environ.get("INTERMEDIATE_TILES_CONTAINER"),
            intermediate_prefix=os.environ.get("RASTER_INTERMEDIATE_PREFIX", "temp/raster_etl"),
            cog_compression=os.environ.get("RASTER_COG_COMPRESSION", "deflate"),
            cog_jpeg_quality=int(os.environ.get("RASTER_COG_JPEG_QUALITY", "85")),
            cog_tile_size=int(os.environ.get("RASTER_COG_TILE_SIZE", "512")),
            cog_in_memory=os.environ.get("RASTER_COG_IN_MEMORY", "true").lower() == "true",
            target_crs=os.environ.get("RASTER_TARGET_CRS", "EPSG:4326"),
            overview_resampling=os.environ.get("RASTER_OVERVIEW_RESAMPLING", "average"),
            reproject_resampling=os.environ.get("RASTER_REPROJECT_RESAMPLING", "bilinear"),
            strict_validation=os.environ.get("RASTER_STRICT_VALIDATION", "true").lower() == "true",
            mosaicjson_maxzoom=int(os.environ.get("RASTER_MOSAICJSON_MAXZOOM", "19")),
            stac_default_collection=os.environ.get("STAC_DEFAULT_COLLECTION", "system-rasters")
        )
