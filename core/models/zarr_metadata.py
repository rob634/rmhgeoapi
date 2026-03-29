# ============================================================================
# CLAUDE CONTEXT - ZARR METADATA MODEL
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6)
# STATUS: Model - Database record for app.zarr_metadata table
# PURPOSE: Source of truth for Zarr store metadata. Caches stac_item_json for
#          STAC materialization. Mirrors cog_metadata pattern for raster.
# LAST_REVIEWED: 22 MAR 2026
# EXPORTS: ZarrMetadataRecord
# DEPENDENCIES: pydantic
# ============================================================================
"""
Zarr Metadata Record — database model for app.zarr_metadata.

Stores metadata for Zarr stores (both native ingest and NetCDF-to-Zarr
converted). Each record represents one Zarr store in silver storage.

Key fields:
    zarr_id: Primary key (deterministic from collection_id + store_prefix)
    store_url: abfs:// URL to Zarr store in silver
    stac_item_json: Cached STAC item dict (source of truth for pgSTAC rebuild)

Table created by sql_generator.py via action=ensure (additive, no data loss).
"""

from datetime import datetime
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ZarrMetadataRecord(BaseModel):
    """
    Database record for app.zarr_metadata table.

    Table: app.zarr_metadata
    Primary Key: zarr_id
    """
    model_config = ConfigDict(use_enum_values=True)

    # DDL generation hints
    __sql_table_name: ClassVar[str] = "zarr_metadata"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["zarr_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = []

    # Primary Key
    zarr_id: str = Field(
        ...,
        max_length=255,
        description="Zarr store identifier (deterministic from collection + prefix)"
    )

    # Store Location
    container: str = Field(
        ...,
        max_length=100,
        description="Silver storage container name"
    )
    store_prefix: str = Field(
        ...,
        max_length=500,
        description="Blob prefix path within container"
    )
    store_url: str = Field(
        ...,
        max_length=1000,
        description="Full store URL (abfs:// path for fsspec/xarray)"
    )

    # Zarr Properties
    zarr_format: Optional[int] = Field(
        default=None,
        description="Zarr format version (2 or 3)"
    )
    variables: Optional[List[str]] = Field(
        default=None,
        description="Data variable names in the store"
    )
    dimensions: Optional[Dict[str, int]] = Field(
        default=None,
        description="Dimension names and sizes (e.g., {'time': 365, 'y': 1000, 'x': 1000})"
    )
    chunks: Optional[Dict[str, int]] = Field(
        default=None,
        description="Chunk sizes per dimension"
    )
    compression: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Compression codec (e.g., 'blosc_lz4', 'zstd')"
    )

    # Spatial
    bbox_minx: Optional[float] = Field(default=None)
    bbox_miny: Optional[float] = Field(default=None)
    bbox_maxx: Optional[float] = Field(default=None)
    bbox_maxy: Optional[float] = Field(default=None)
    crs: Optional[str] = Field(default=None, max_length=50, description="CRS string (e.g., EPSG:4326)")

    # Temporal
    time_start: Optional[str] = Field(default=None, max_length=50, description="ISO8601 start time")
    time_end: Optional[str] = Field(default=None, max_length=50, description="ISO8601 end time")
    time_steps: Optional[int] = Field(default=None, description="Number of time steps")

    # Size
    total_size_bytes: Optional[int] = Field(default=None, description="Total store size in bytes")
    chunk_count: Optional[int] = Field(default=None, description="Total number of chunk files")

    # STAC linkage
    stac_item_id: Optional[str] = Field(default=None, max_length=255)
    stac_collection_id: Optional[str] = Field(default=None, max_length=255)

    # Cached STAC item (source of truth for pgSTAC rebuild)
    stac_item_json: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Complete STAC item dict — stac_materialize_item reads this"
    )

    # ETL provenance
    pipeline: Optional[str] = Field(default=None, max_length=50, description="ingest_zarr or netcdf_to_zarr")
    etl_job_id: Optional[str] = Field(default=None, max_length=100)
    source_file: Optional[str] = Field(default=None, max_length=500)
    source_format: Optional[str] = Field(default=None, max_length=20, description="zarr or netcdf")

    # Timestamps
    created_at: Optional[datetime] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None)
