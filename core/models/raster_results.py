# ============================================================================
# RASTER WORKFLOW RESULT MODELS (F7.21)
# ============================================================================
# STATUS: Core - Pure result data structures for raster pipeline
# PURPOSE: Type-safe Pydantic models for raster validation, COG creation, STAC
# CREATED: 25 JAN 2026
# PATTERN: Follows ProcessVectorStage1Data in core/models/results.py
# ============================================================================
"""
Raster Workflow Result Models - Type-Safe Pipeline Results.

F7.21: Addresses the gap where raster workflow passed untyped dicts between
database, Python, and Service Bus with no Pydantic validation.

These models enable:
    - Compile-time validation of structure changes
    - IDE autocomplete for all result fields
    - Type-safe checkpoint resume
    - Consistent serialization between phases

Phase 1 Models (CRITICAL):
    - RasterValidationData / RasterValidationResult
    - COGCreationData / COGCreationResult
    - STACCreationData / STACCreationResult

See docs_claude/RASTER_RESULT_MODELS.md for full implementation plan.

Exports:
    RasterTypeInfo, COGTierInfo, BitDepthCheck, MemoryEstimation
    RasterValidationData, RasterValidationResult
    COGCreationData, COGCreationResult
    STACCreationData, STACCreationResult
    TierProfileInfo
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# PHASE 1: VALIDATION RESULT MODELS
# ============================================================================

class RasterTypeInfo(BaseModel):
    """
    Raster type detection results from validation phase.

    Contains detected raster type (RGB, DEM, etc.) with confidence
    and evidence used for the detection.
    """
    model_config = ConfigDict(extra="allow")

    detected_type: str = Field(
        ...,
        description="Detected raster type: rgb, rgba, dem, categorical, multispectral, nir, unknown"
    )
    confidence: str = Field(
        default="UNKNOWN",
        description="Detection confidence: VERY_HIGH, HIGH, MEDIUM, LOW, UNKNOWN"
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Evidence strings supporting the type detection"
    )
    type_source: str = Field(
        default="auto_detected",
        description="Source of type: auto_detected, user_specified"
    )
    optimal_cog_settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Recommended COG settings for this raster type"
    )
    band_count: Optional[int] = Field(
        default=None,
        description="Number of bands (for tier detection)"
    )
    data_type: Optional[str] = Field(
        default=None,
        description="Data type string (for tier detection)"
    )


class COGTierInfo(BaseModel):
    """
    COG tier compatibility information.

    Determines which output tiers (visualization, analysis, archive)
    are compatible with this raster based on band count and data type.
    """
    model_config = ConfigDict(extra="allow")

    applicable_tiers: List[str] = Field(
        default_factory=list,
        description="Compatible COG tiers: visualization, analysis, archive"
    )
    total_compatible: int = Field(
        default=0,
        ge=0,
        description="Number of compatible tiers"
    )
    incompatible_reason: Optional[str] = Field(
        default=None,
        description="Reason if some tiers are incompatible (e.g., JPEG requires RGB)"
    )


class BitDepthCheck(BaseModel):
    """
    Bit-depth efficiency analysis result.

    Flags inefficient storage (e.g., float32 for categorical data)
    with recommendations for optimization.
    """
    model_config = ConfigDict(extra="allow")

    efficient: bool = Field(
        default=True,
        description="Whether bit-depth is appropriate for the data"
    )
    current_dtype: str = Field(
        ...,
        description="Current data type (e.g., uint8, float32)"
    )
    reason: str = Field(
        default="Unknown",
        description="Explanation of efficiency assessment"
    )
    recommended_dtype: Optional[str] = Field(
        default=None,
        description="Recommended data type if inefficient"
    )
    potential_savings_percent: Optional[float] = Field(
        default=None,
        ge=0,
        le=100,
        description="Potential size reduction percentage"
    )


class MemoryEstimation(BaseModel):
    """
    Memory footprint estimation for processing strategy.

    Used to determine single-pass vs chunked processing based on
    available system RAM and estimated peak memory usage.
    """
    model_config = ConfigDict(extra="allow")

    uncompressed_gb: Optional[float] = Field(
        default=None,
        ge=0,
        description="Uncompressed raster size in GB"
    )
    estimated_peak_gb: Optional[float] = Field(
        default=None,
        ge=0,
        description="Estimated peak memory during processing in GB"
    )
    system_ram_gb: Optional[float] = Field(
        default=None,
        ge=0,
        description="Detected system RAM in GB"
    )
    cpu_count: Optional[int] = Field(
        default=None,
        ge=1,
        description="Detected CPU count"
    )
    safe_threshold_gb: Optional[float] = Field(
        default=None,
        ge=0,
        description="Safe memory threshold for processing"
    )
    processing_strategy: Optional[str] = Field(
        default=None,
        description="Recommended strategy: single_pass, single_pass_conservative, chunked"
    )
    gdal_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Recommended GDAL configuration settings"
    )
    warnings: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Memory-related warnings"
    )


class WarningInfo(BaseModel):
    """
    Structured warning from validation phase.

    Captures warnings that don't fail validation but indicate
    potential issues (e.g., suspicious bounds, inefficient bit-depth).
    """
    model_config = ConfigDict(extra="allow")

    type: str = Field(..., description="Warning type code")
    severity: str = Field(
        default="INFO",
        description="Severity: INFO, MEDIUM, HIGH, CRITICAL"
    )
    message: str = Field(..., description="Human-readable warning message")


class RasterValidationData(BaseModel):
    """
    Validated structure for raster validation phase output.

    This is the 'result' field inside RasterValidationResult.
    Stored in TaskRecord.checkpoint_data after validation phase.
    Consumed by COG creation phase.

    Mirrors the dict structure from validate_raster() lines 470-516.
    """
    model_config = ConfigDict(extra="allow")

    # Core validation result
    valid: bool = Field(..., description="Whether raster passed validation")

    # Source file info
    source_blob: str = Field(..., description="Source blob path")
    container_name: str = Field(..., description="Source container name")

    # CRS info
    source_crs: str = Field(..., description="CRS string (e.g., EPSG:4326)")
    crs_source: str = Field(
        default="file_metadata",
        description="Source of CRS: file_metadata, user_override, user_confirmed"
    )

    # Geometry info
    bounds: List[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Bounding box [minx, miny, maxx, maxy]"
    )
    shape: List[int] = Field(
        ...,
        min_length=2,
        max_length=2,
        description="Raster shape [height, width]"
    )

    # Band info
    band_count: int = Field(..., ge=1, description="Number of bands")
    dtype: str = Field(..., description="Data type (e.g., uint8, float32)")
    data_type: Optional[str] = Field(
        default=None,
        description="Alias for dtype (tier compatibility)"
    )
    nodata: Optional[Any] = Field(default=None, description="NoData value")

    # File info
    size_mb: float = Field(default=0, ge=0, description="File size in MB")

    # Nested analysis results (Optional for header-only validation)
    raster_type: Optional[RasterTypeInfo] = Field(
        default=None,
        description="Raster type detection results (populated by data phase)"
    )
    cog_tiers: Optional[COGTierInfo] = Field(
        default=None,
        description="COG tier compatibility info (populated by data phase)"
    )
    bit_depth_check: Optional[BitDepthCheck] = Field(
        default=None,
        description="Bit-depth efficiency analysis (populated by data phase)"
    )
    memory_estimation: Optional[MemoryEstimation] = Field(
        default=None,
        description="Memory footprint estimation"
    )

    # Warnings (non-fatal issues)
    warnings: List[Any] = Field(
        default_factory=list,
        description="Validation warnings (WarningInfo or dict)"
    )

    # Testing flag
    validation_skipped: Optional[bool] = Field(
        default=None,
        description="True if validation was skipped (testing only)"
    )


class RasterValidationResult(BaseModel):
    """
    Full task result wrapper for validation phase.

    This is the complete return value from validate_raster().

    Example:
        {
            "success": True,
            "result": {
                "valid": True,
                "source_blob": "path/to/file.tif",
                ...
            }
        }
    """
    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="Whether validation succeeded")
    result: Optional[RasterValidationData] = Field(
        default=None,
        description="Validation output data (present if success=True)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error code if validation failed"
    )
    message: Optional[str] = Field(
        default=None,
        description="Error message if validation failed"
    )
    error_type: Optional[str] = Field(
        default=None,
        description="Exception type name if failed"
    )
    traceback: Optional[str] = Field(
        default=None,
        description="Stack trace if failed (debug mode)"
    )


# ============================================================================
# PHASE 1: COG CREATION RESULT MODELS
# ============================================================================

class TierProfileInfo(BaseModel):
    """
    COG tier profile information.

    Describes the compression profile used for COG creation.
    """
    model_config = ConfigDict(extra="allow")

    tier: str = Field(..., description="Tier name: visualization, analysis, archive")
    compression: str = Field(..., description="Compression method: JPEG, DEFLATE, LZW")
    storage_tier: str = Field(..., description="Azure storage tier: hot, cool, archive")
    use_case: Optional[str] = Field(default=None, description="Intended use case")
    description: Optional[str] = Field(default=None, description="Tier description")


class COGCreationData(BaseModel):
    """
    Validated structure for COG creation phase output.

    This is the 'result' field inside COGCreationResult.
    Stored in TaskRecord.checkpoint_data after COG creation phase.
    Consumed by STAC creation phase.

    Mirrors the dict structure from create_cog() lines 1018-1060.
    """
    model_config = ConfigDict(extra="allow")

    # Output file info
    cog_blob: str = Field(..., description="Output COG blob path in silver container")
    cog_container: str = Field(..., description="Silver container name")
    cog_tier: str = Field(
        default="analysis",
        description="COG tier: visualization, analysis, archive"
    )
    storage_tier: str = Field(
        default="hot",
        description="Azure storage tier: hot, cool, archive"
    )

    # Source info
    source_blob: str = Field(..., description="Source blob path")
    source_container: str = Field(..., description="Source container name")

    # Reprojection info
    reprojection_performed: bool = Field(
        default=False,
        description="Whether reprojection was performed"
    )
    source_crs: str = Field(..., description="Source CRS string")
    target_crs: str = Field(default="EPSG:4326", description="Target CRS string")

    # Output geometry
    bounds_4326: Optional[List[float]] = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="Bounding box in EPSG:4326 [minx, miny, maxx, maxy]"
    )
    shape: List[int] = Field(
        default_factory=list,
        description="Output shape [height, width]"
    )

    # COG creation settings
    size_mb: float = Field(default=0, ge=0, description="Output file size in MB")
    compression: str = Field(default="deflate", description="Compression method used")
    jpeg_quality: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="JPEG quality (if JPEG compression)"
    )
    tile_size: List[int] = Field(
        default_factory=lambda: [512, 512],
        description="Tile dimensions [width, height]"
    )
    overview_levels: List[int] = Field(
        default_factory=list,
        description="Overview levels generated"
    )
    overview_resampling: str = Field(
        default="cubic",
        description="Overview resampling method"
    )
    reproject_resampling: Optional[str] = Field(
        default=None,
        description="Reprojection resampling method (if reprojected)"
    )

    # Raster type info (passed through from validation)
    raster_type: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raster type info from validation phase"
    )

    # Performance metrics
    processing_time_seconds: float = Field(
        default=0,
        ge=0,
        description="COG creation time in seconds"
    )

    # Tier profile details
    tier_profile: Optional[TierProfileInfo] = Field(
        default=None,
        description="COG tier profile used"
    )

    # STAC-compliant checksum (F7.9)
    file_checksum: Optional[str] = Field(
        default=None,
        description="SHA-256 multihash hex string"
    )
    file_size: Optional[int] = Field(
        default=None,
        ge=0,
        description="File size in bytes"
    )

    # Azure versioning
    blob_version_id: Optional[str] = Field(
        default=None,
        description="Azure Blob Storage version ID"
    )

    # Processing mode indicator (V0.8)
    processing_mode: Optional[str] = Field(
        default=None,
        description="Processing mode: disk_based or in_memory"
    )


class COGCreationResult(BaseModel):
    """
    Full task result wrapper for COG creation phase.

    This is the complete return value from create_cog().
    """
    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="Whether COG creation succeeded")
    result: Optional[COGCreationData] = Field(
        default=None,
        description="COG creation output data (present if success=True)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error code if COG creation failed"
    )
    message: Optional[str] = Field(
        default=None,
        description="Error message if failed"
    )
    traceback: Optional[str] = Field(
        default=None,
        description="Stack trace if failed (debug mode)"
    )


# ============================================================================
# PHASE 1: STAC CREATION RESULT MODELS
# ============================================================================

class STACCreationData(BaseModel):
    """
    Validated structure for STAC creation phase output.

    Contains collection and item IDs after STAC registration.
    Mirrors the result structure from extract_stac_metadata().
    """
    model_config = ConfigDict(extra="allow")

    # Core identifiers
    collection_id: str = Field(..., description="STAC collection ID")
    item_id: Optional[str] = Field(
        default=None,
        description="STAC item ID (single item mode)"
    )
    blob_name: Optional[str] = Field(
        default=None,
        description="Source blob name"
    )

    # Spatial/geometry info
    bbox: Optional[List[float]] = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="Bounding box [minx, miny, maxx, maxy]"
    )
    geometry_type: Optional[str] = Field(
        default=None,
        description="Geometry type (e.g., Polygon)"
    )
    epsg: Optional[int] = Field(
        default=None,
        description="EPSG code"
    )
    bands_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of raster bands"
    )

    # JSON fallback
    stac_item_json_blob: Optional[str] = Field(
        default=None,
        description="Blob path for JSON fallback"
    )
    stac_item_json_url: Optional[str] = Field(
        default=None,
        description="URL to JSON fallback"
    )

    # pgSTAC status
    inserted_to_pgstac: Optional[bool] = Field(
        default=None,
        description="Whether item was inserted to pgSTAC"
    )
    pgstac_available: Optional[bool] = Field(
        default=None,
        description="Whether pgSTAC was available"
    )
    item_skipped: Optional[bool] = Field(
        default=None,
        description="Whether insertion was skipped (already exists)"
    )
    skip_reason: Optional[str] = Field(
        default=None,
        description="Reason for skipping insertion"
    )

    # Timing
    execution_time_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="Total execution time"
    )
    extract_time_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="STAC extraction time"
    )
    insert_time_seconds: Optional[float] = Field(
        default=None,
        ge=0,
        description="pgSTAC insertion time"
    )

    # Full STAC item (for reference/debugging)
    stac_item: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full STAC item dict"
    )

    # Tiled mode fields
    item_count: int = Field(
        default=1,
        ge=0,
        description="Number of STAC items created"
    )
    spatial_extent: Optional[List[float]] = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="Spatial extent [minx, miny, maxx, maxy]"
    )
    temporal_extent: Optional[List[Optional[str]]] = Field(
        default=None,
        description="Temporal extent [start, end] as ISO strings"
    )
    viewer_url: Optional[str] = Field(
        default=None,
        description="URL to view the collection in STAC browser"
    )
    stac_api_url: Optional[str] = Field(
        default=None,
        description="STAC API endpoint for this collection"
    )


class STACCreationResult(BaseModel):
    """
    Full task result wrapper for STAC creation phase.
    """
    model_config = ConfigDict(extra="allow")

    success: bool = Field(..., description="Whether STAC creation succeeded")
    degraded: Optional[bool] = Field(
        default=None,
        description="True if running in degraded mode (pgSTAC unavailable)"
    )
    warning: Optional[str] = Field(
        default=None,
        description="Warning message for degraded mode"
    )
    result: Optional[STACCreationData] = Field(
        default=None,
        description="STAC creation output data (present if success=True)"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error code if STAC creation failed"
    )
    message: Optional[str] = Field(
        default=None,
        description="Error message if failed"
    )
    error_type: Optional[str] = Field(
        default=None,
        description="Exception type name if failed"
    )
    traceback: Optional[str] = Field(
        default=None,
        description="Stack trace if failed"
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Validation sub-models
    'RasterTypeInfo',
    'COGTierInfo',
    'BitDepthCheck',
    'MemoryEstimation',
    'WarningInfo',
    # Validation results
    'RasterValidationData',
    'RasterValidationResult',
    # COG creation sub-models
    'TierProfileInfo',
    # COG creation results
    'COGCreationData',
    'COGCreationResult',
    # STAC creation results
    'STACCreationData',
    'STACCreationResult',
]
