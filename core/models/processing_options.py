# ============================================================================
# CLAUDE CONTEXT - TYPED PROCESSING OPTIONS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core model - Pydantic V2 typed processing options
# PURPOSE: Replace Dict[str, Any] with validated, typed models for platform requests
# LAST_REVIEWED: 17 FEB 2026
# EXPORTS: OutputTier, RasterType, CollectionRasterType,
#          BaseProcessingOptions, VectorProcessingOptions,
#          RasterProcessingOptions, RasterCollectionProcessingOptions
# DEPENDENCIES: pydantic
# ============================================================================
"""
Typed Processing Options for Platform Requests.

Replaces Dict[str, Any] processing_options with Pydantic V2 models that
enforce type safety at the platform boundary. Catches invalid values
(bad enums, string booleans, out-of-range ints) at HTTP parse time
instead of 30 minutes later in job handlers.

Enum values sourced from job parameters_schema:
- ProcessRasterDockerJob: 14 raster_type values
- ProcessRasterCollectionDockerJob: 7 raster_type values
- Both: 4 output_tier values

Boolean coercion handles string "true"/"false" from web forms.
CRS validation enforces EPSG:XXXX pattern.
extra='ignore' for forward compatibility (unknown keys logged and dropped).
"""

import logging
import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class OutputTier(str, Enum):
    """Output tier for raster COG generation. Controls quality/size tradeoff."""
    VISUALIZATION = "visualization"
    ANALYSIS = "analysis"
    ARCHIVE = "archive"
    ALL = "all"


class RasterType(str, Enum):
    """
    Raster type for single raster processing (process_raster_docker).

    14 values: auto + 13 domain types.
    Source: jobs/process_raster_docker.py parameters_schema
    """
    AUTO = "auto"
    RGB = "rgb"
    RGBA = "rgba"
    DEM = "dem"
    CATEGORICAL = "categorical"
    MULTISPECTRAL = "multispectral"
    NIR = "nir"
    CONTINUOUS = "continuous"
    VEGETATION_INDEX = "vegetation_index"
    FLOOD_DEPTH = "flood_depth"
    FLOOD_PROBABILITY = "flood_probability"
    HYDROLOGY = "hydrology"
    TEMPORAL = "temporal"
    POPULATION = "population"


class CollectionRasterType(str, Enum):
    """
    Raster type for collection processing (process_raster_collection_docker).

    7 values: auto + 6 physical types (no domain-specific types).
    Source: jobs/process_raster_collection_docker.py parameters_schema
    """
    AUTO = "auto"
    RGB = "rgb"
    RGBA = "rgba"
    DEM = "dem"
    CATEGORICAL = "categorical"
    MULTISPECTRAL = "multispectral"
    NIR = "nir"


# ============================================================================
# VALIDATORS (reusable)
# ============================================================================

def _coerce_bool(v):
    """
    Coerce string booleans to Python bool.

    Handles web form values ("true"/"false" strings) that would otherwise
    be truthy in Python (e.g., "false" is truthy as a non-empty string).

    Args:
        v: Input value (bool, str, or other)

    Returns:
        bool

    Raises:
        ValueError: If string is not "true" or "false"
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        lower = v.strip().lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        raise ValueError(
            f"Cannot coerce '{v}' to bool. Use true/false (not '{v}')"
        )
    return bool(v)


def _validate_crs(v: Optional[str]) -> Optional[str]:
    """
    Validate and normalize CRS string to EPSG:XXXX format.

    Args:
        v: CRS string like "epsg:4326" or "EPSG:32617"

    Returns:
        Normalized uppercase "EPSG:XXXX" or None

    Raises:
        ValueError: If CRS doesn't match EPSG:digits pattern
    """
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f"CRS must be a string, got {type(v).__name__}")
    normalized = v.strip().upper()
    if not re.match(r'^EPSG:\d+$', normalized):
        raise ValueError(
            f"Invalid CRS '{v}'. Must be EPSG:XXXX format (e.g., EPSG:4326)"
        )
    return normalized


def _normalize_enum_str(v):
    """Normalize string to lowercase for enum matching."""
    if isinstance(v, str):
        return v.strip().lower()
    return v


# ============================================================================
# MODELS
# ============================================================================

class BaseProcessingOptions(BaseModel):
    """
    Base processing options shared by all data types.

    Fields:
        overwrite: Force reprocessing (bool, coerced from strings)
        collection_id: Custom STAC collection ID override
        expected_data_type: Validate detected data type matches expectation
    """
    model_config = ConfigDict(extra='ignore')

    overwrite: bool = Field(default=False, description="Force reprocessing of existing data")
    collection_id: Optional[str] = Field(default=None, description="Custom STAC collection ID override")
    expected_data_type: Optional[str] = Field(default=None, description="Expected data type for validation")

    @field_validator('overwrite', mode='before')
    @classmethod
    def coerce_overwrite(cls, v):
        return _coerce_bool(v)

    @model_validator(mode='after')
    def _log_ignored_fields(self):
        """Log any fields that were silently ignored (extra='ignore')."""
        # This runs after construction; Pydantic has already dropped extras.
        # We can't access them here, but the model_validator on PlatformRequest
        # logs the raw dict keys vs model fields before dispatch.
        return self


class VectorProcessingOptions(BaseProcessingOptions):
    """
    Processing options for vector data (GeoJSON, GPKG, SHP, CSV, etc.).

    Fields:
        table_name: Custom PostGIS table name (slugified)
        lat_column: CSV latitude column name
        lon_column: CSV longitude column name
        wkt_column: CSV WKT geometry column name
    """
    table_name: Optional[str] = Field(default=None, description="Custom PostGIS table name")
    lat_column: Optional[str] = Field(default=None, description="CSV latitude column name")
    lon_column: Optional[str] = Field(default=None, description="CSV longitude column name")
    wkt_column: Optional[str] = Field(default=None, description="CSV WKT geometry column name")


class RasterProcessingOptions(BaseProcessingOptions):
    """
    Processing options for single raster files (process_raster_docker).

    Fields:
        crs: Target CRS in EPSG:XXXX format
        raster_type: One of 14 raster types (auto, rgb, dem, etc.)
        output_tier: COG quality tier (visualization, analysis, archive, all)
    """
    crs: Optional[str] = Field(default=None, description="Target CRS (EPSG:XXXX)")
    raster_type: RasterType = Field(default=RasterType.AUTO, description="Raster data type")
    output_tier: OutputTier = Field(default=OutputTier.ANALYSIS, description="COG output quality tier")

    @field_validator('crs', mode='before')
    @classmethod
    def validate_crs(cls, v):
        return _validate_crs(v)

    @field_validator('raster_type', mode='before')
    @classmethod
    def normalize_raster_type(cls, v):
        return _normalize_enum_str(v)

    @field_validator('output_tier', mode='before')
    @classmethod
    def normalize_output_tier(cls, v):
        return _normalize_enum_str(v)


class RasterCollectionProcessingOptions(BaseProcessingOptions):
    """
    Processing options for raster collections (process_raster_collection_docker).

    Fields:
        crs: Target CRS in EPSG:XXXX format
        input_crs: Source CRS override (when source has no CRS metadata)
        raster_type: One of 7 raster types (auto, rgb, dem, etc.)
        output_tier: COG quality tier
        jpeg_quality: JPEG compression quality (1-100)
        license: STAC license string
        use_mount_storage: Use Azure mount storage for temp files
        cleanup_temp: Clean up temp files after processing
        strict_mode: Fail on warnings instead of continuing
    """
    crs: Optional[str] = Field(default=None, description="Target CRS (EPSG:XXXX)")
    input_crs: Optional[str] = Field(default=None, description="Source CRS override (EPSG:XXXX)")
    raster_type: CollectionRasterType = Field(
        default=CollectionRasterType.AUTO,
        description="Raster data type (7 types for collections)"
    )
    output_tier: OutputTier = Field(default=OutputTier.ANALYSIS, description="COG output quality tier")
    jpeg_quality: Optional[int] = Field(default=None, ge=1, le=100, description="JPEG quality (1-100)")
    license: str = Field(default="proprietary", description="STAC license identifier")
    use_mount_storage: bool = Field(default=True, description="Use Azure mount storage for temp files")
    cleanup_temp: bool = Field(default=True, description="Clean up temp files after processing")
    strict_mode: bool = Field(default=False, description="Fail on warnings")

    @field_validator('crs', 'input_crs', mode='before')
    @classmethod
    def validate_crs(cls, v):
        return _validate_crs(v)

    @field_validator('raster_type', mode='before')
    @classmethod
    def normalize_raster_type(cls, v):
        return _normalize_enum_str(v)

    @field_validator('output_tier', mode='before')
    @classmethod
    def normalize_output_tier(cls, v):
        return _normalize_enum_str(v)

    @field_validator('use_mount_storage', 'cleanup_temp', 'strict_mode', mode='before')
    @classmethod
    def coerce_bools(cls, v):
        return _coerce_bool(v)
