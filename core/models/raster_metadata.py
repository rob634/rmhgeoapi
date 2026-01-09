# ============================================================================
# RASTER METADATA MODELS
# ============================================================================
# STATUS: Core - COG metadata database record
# PURPOSE: Pydantic model for app.cog_metadata table DDL generation
# LAST_REVIEWED: 09 JAN 2026
# REVIEW_STATUS: Check 8 N/A - no infrastructure config
# ============================================================================
"""
Raster Metadata Database Record Model.

Provides the Pydantic model for app.cog_metadata table DDL generation.
This is the DATABASE RECORD model used by sql_generator.py.

The corresponding DOMAIN MODEL (RasterMetadata) is in unified_metadata.py
and provides business logic, STAC conversion, etc.

Architecture (F7.9):
    RasterMetadata (unified_metadata.py)  <- Domain model with business logic
         ↓ from_db_row()
    app.cog_metadata (database)
         ↓ DDL from
    CogMetadataRecord (this file)        <- DB record model for DDL generation

Table: app.cog_metadata
Primary Key: cog_id

Usage:
    This model is imported by sql_generator.py to generate the DDL for
    the app.cog_metadata table during schema deployment.

Exports:
    CogMetadataRecord: Database record model for DDL generation

Created: 09 JAN 2026
Epic: E7 Pipeline Infrastructure -> F7.9 RasterMetadata Implementation
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# DATABASE RECORD MODEL (for SQL generation)
# =============================================================================

class CogMetadataRecord(BaseModel):
    """
    Database record model for app.cog_metadata table.

    This model is used by sql_generator.py to create the database table.
    It has proper max_length constraints for DDL generation.

    The corresponding domain model (RasterMetadata) in unified_metadata.py
    provides from_db_row() and to_stac_*() conversion methods.

    Table: app.cog_metadata
    Primary Key: cog_id
    """
    model_config = ConfigDict(use_enum_values=True)

    # Primary Key
    cog_id: str = Field(
        ...,
        max_length=255,
        description="COG identifier (typically: collection_scenario_year_etc)"
    )

    # COG Location
    container: str = Field(
        ...,
        max_length=100,
        description="Azure storage container name"
    )
    blob_path: str = Field(
        ...,
        max_length=500,
        description="Path within container"
    )
    cog_url: str = Field(
        ...,
        max_length=1000,
        description="Full COG URL (/vsiaz/ path or HTTPS URL)"
    )

    # Raster Properties (required)
    width: int = Field(
        ...,
        description="Raster width in pixels"
    )
    height: int = Field(
        ...,
        description="Raster height in pixels"
    )
    band_count: Optional[int] = Field(
        default=1,
        description="Number of bands"
    )
    dtype: Optional[str] = Field(
        default="float32",
        max_length=20,
        description="Numpy dtype (uint8, int16, float32, etc.)"
    )
    nodata: Optional[float] = Field(
        default=None,
        description="NoData value"
    )
    crs: Optional[str] = Field(
        default="EPSG:4326",
        max_length=100,
        description="CRS as EPSG code or WKT"
    )
    transform: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Affine transform (JSONB: [a, b, c, d, e, f])"
    )
    resolution: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Resolution (JSONB: [x_res, y_res])"
    )

    # Band metadata
    band_names: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Band descriptions/names (JSONB array)"
    )
    band_units: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Units per band (JSONB array)"
    )

    # Extent (for fast STAC queries)
    bbox_minx: Optional[float] = Field(default=None, description="Bounding box min X")
    bbox_miny: Optional[float] = Field(default=None, description="Bounding box min Y")
    bbox_maxx: Optional[float] = Field(default=None, description="Bounding box max X")
    bbox_maxy: Optional[float] = Field(default=None, description="Bounding box max Y")

    # Temporal extent
    temporal_start: Optional[datetime] = Field(default=None, description="Temporal extent start")
    temporal_end: Optional[datetime] = Field(default=None, description="Temporal extent end")

    # COG Processing metadata
    is_cog: Optional[bool] = Field(default=True, description="Cloud-optimized GeoTIFF flag")
    overview_levels: Optional[Dict[str, Any]] = Field(
        default=None,
        description="COG overview levels (JSONB array)"
    )
    compression: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Compression method (DEFLATE, LZW, etc.)"
    )
    blocksize: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Internal tile size (JSONB: [width, height])"
    )

    # Visualization defaults
    colormap: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Default colormap name for TiTiler"
    )
    rescale_range: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Default rescale range (JSONB: [min, max])"
    )

    # STAC extensions - EO and Raster band metadata
    eo_bands: Optional[Dict[str, Any]] = Field(
        default=None,
        description="EO extension band metadata (JSONB)"
    )
    raster_bands: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raster extension band stats (JSONB)"
    )

    # Descriptive metadata
    title: Optional[str] = Field(default=None, max_length=500, description="Human-readable title")
    description: Optional[str] = Field(default=None, description="Dataset description (TEXT)")
    keywords: Optional[str] = Field(default=None, description="Comma-separated tags (TEXT)")
    license: Optional[str] = Field(default=None, max_length=100, description="SPDX license identifier")

    # Providers and extensions
    providers: Optional[Dict[str, Any]] = Field(
        default=None,
        description="STAC providers (JSONB array)"
    )
    stac_extensions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="STAC extension URIs (JSONB array)"
    )

    # STAC Linkage
    stac_item_id: Optional[str] = Field(default=None, max_length=255, description="STAC item ID")
    stac_collection_id: Optional[str] = Field(default=None, max_length=255, description="STAC collection ID")

    # ETL Traceability
    etl_job_id: Optional[str] = Field(default=None, max_length=64, description="CoreMachine job ID")
    source_file: Optional[str] = Field(default=None, max_length=500, description="Original source filename")
    source_format: Optional[str] = Field(default=None, max_length=50, description="Source file format")
    source_crs: Optional[str] = Field(default=None, max_length=50, description="Original CRS before reprojection")

    # Scientific metadata
    sci_doi: Optional[str] = Field(default=None, max_length=200, description="Scientific DOI")
    sci_citation: Optional[str] = Field(default=None, description="Citation text (TEXT)")

    # Custom properties (extension point)
    custom_properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional custom properties (JSONB)"
    )

    # Timestamps
    created_at: Optional[datetime] = Field(default=None, description="Record creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Record last update timestamp")


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    'CogMetadataRecord',
]
