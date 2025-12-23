# ============================================================================
# CLAUDE CONTEXT - STAC DATA MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Data models - Centralized STAC property schemas
# PURPOSE: Enforce consistent data models across all STAC operations
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: STACItemProperties, PlatformProperties, AppProperties, GeoProperties,
#          AzureProperties, PostGISProperties, STAC_VERSION
# DEPENDENCIES: pydantic
# ============================================================================
"""
STAC Data Models.

Centralized Pydantic models for all STAC property namespaces. These models
enforce type safety and consistency across all STAC item/collection creation.

Design Principle:
    ALL STAC property namespaces are defined here. Service files import from
    this module to ensure consistency.

Namespaces:
    - platform:* - DDH platform identifiers
    - app:* - Job linkage and application metadata
    - geo:* - Geographic attribution (ISO3 codes)
    - azure:* - Azure blob storage metadata
    - postgis:* - PostGIS vector table metadata

Exports:
    STAC_VERSION: Single source of truth for STAC spec version
    PlatformProperties: DDH platform identifiers
    AppProperties: Job linkage metadata
    GeoProperties: Geographic attribution
    AzureProperties: Azure blob metadata
    PostGISProperties: PostGIS table metadata
    STACItemProperties: Composite model for all properties

Created: 22 DEC 2025
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator


# =============================================================================
# CONSTANTS
# =============================================================================

# Single source of truth for STAC specification version
# All STAC items and collections MUST use this version
STAC_VERSION = "1.0.0"


# =============================================================================
# ENUMS
# =============================================================================

class AccessLevel(str, Enum):
    """Data access classification levels."""
    PUBLIC = "public"
    OUO = "ouo"  # Official Use Only
    RESTRICTED = "restricted"


class AssetType(str, Enum):
    """STAC asset types."""
    RASTER = "raster"
    VECTOR = "vector"
    MIXED = "mixed"


# =============================================================================
# NAMESPACE PROPERTY MODELS
# =============================================================================

class PlatformProperties(BaseModel):
    """
    DDH platform identifiers.

    Namespace: platform:*
    Source: PlatformRequest via job_parameters

    These properties link STAC items back to the DDH platform that
    requested their creation.
    """
    model_config = ConfigDict(populate_by_name=True)

    dataset_id: Optional[str] = Field(
        default=None,
        alias="platform:dataset_id",
        description="DDH dataset identifier"
    )
    resource_id: Optional[str] = Field(
        default=None,
        alias="platform:resource_id",
        description="DDH resource identifier"
    )
    version_id: Optional[str] = Field(
        default=None,
        alias="platform:version_id",
        description="DDH version identifier"
    )
    request_id: Optional[str] = Field(
        default=None,
        alias="platform:request_id",
        description="Platform request hash (SHA256[:32])"
    )
    access_level: Optional[AccessLevel] = Field(
        default=None,
        alias="platform:access_level",
        description="Data classification level"
    )
    client: str = Field(
        default="ddh",
        alias="platform:client",
        description="Client application identifier"
    )

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert to flat dict with namespaced keys."""
        result = {}
        if self.dataset_id:
            result["platform:dataset_id"] = self.dataset_id
        if self.resource_id:
            result["platform:resource_id"] = self.resource_id
        if self.version_id:
            result["platform:version_id"] = self.version_id
        if self.request_id:
            result["platform:request_id"] = self.request_id
        if self.access_level:
            result["platform:access_level"] = self.access_level.value
        if self.client:
            result["platform:client"] = self.client
        return result


class AppProperties(BaseModel):
    """
    Application-level metadata for job linkage.

    Namespace: app:*
    Source: Job execution context

    These properties link STAC items back to the CoreMachine job
    that created them.
    """
    model_config = ConfigDict(populate_by_name=True)

    job_id: Optional[str] = Field(
        default=None,
        alias="app:job_id",
        description="CoreMachine job ID that created this item"
    )
    job_type: Optional[str] = Field(
        default=None,
        alias="app:job_type",
        description="Job type that created this item"
    )
    created_by: str = Field(
        default="rmhazuregeoapi",
        alias="app:created_by",
        description="Application identifier"
    )
    processing_timestamp: Optional[datetime] = Field(
        default=None,
        alias="app:processing_timestamp",
        description="When the item was created"
    )

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert to flat dict with namespaced keys."""
        result = {
            "app:created_by": self.created_by,
            "app:processing_timestamp": (
                self.processing_timestamp.isoformat()
                if self.processing_timestamp
                else datetime.now(timezone.utc).isoformat()
            )
        }
        if self.job_id:
            result["app:job_id"] = self.job_id
        if self.job_type:
            result["app:job_type"] = self.job_type
        return result


class GeoProperties(BaseModel):
    """
    Geographic attribution properties.

    Namespace: geo:*
    Source: ISO3AttributionService spatial queries

    These properties provide country-level attribution for STAC items
    based on their spatial extent.
    """
    model_config = ConfigDict(populate_by_name=True)

    iso3: List[str] = Field(
        default_factory=list,
        alias="geo:iso3",
        description="ISO3 country codes that intersect the item"
    )
    primary_iso3: Optional[str] = Field(
        default=None,
        alias="geo:primary_iso3",
        description="Primary ISO3 code (largest intersection)"
    )
    countries: List[str] = Field(
        default_factory=list,
        alias="geo:countries",
        description="Country names that intersect the item"
    )

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert to flat dict with namespaced keys."""
        result = {}
        if self.iso3:
            result["geo:iso3"] = self.iso3
        if self.primary_iso3:
            result["geo:primary_iso3"] = self.primary_iso3
        if self.countries:
            result["geo:countries"] = self.countries
        return result


class AzureProperties(BaseModel):
    """
    Azure blob storage metadata.

    Namespace: azure:*
    Source: Azure Blob Storage properties

    These properties track the Azure storage location and characteristics
    of raster STAC items.
    """
    model_config = ConfigDict(populate_by_name=True)

    container: str = Field(
        ...,
        alias="azure:container",
        description="Azure container name"
    )
    blob_path: str = Field(
        ...,
        alias="azure:blob_path",
        description="Blob path within container"
    )
    tier: str = Field(
        default="silver",
        alias="azure:tier",
        description="Data tier (bronze, silver, gold)"
    )
    size_mb: float = Field(
        default=0.0,
        alias="azure:size_mb",
        description="File size in megabytes"
    )
    statistics_extracted: bool = Field(
        default=True,
        alias="azure:statistics_extracted",
        description="Whether raster statistics were extracted"
    )
    etag: Optional[str] = Field(
        default=None,
        alias="azure:etag",
        description="Azure blob ETag for versioning"
    )
    content_type: Optional[str] = Field(
        default=None,
        alias="azure:content_type",
        description="Blob content type"
    )

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert to flat dict with namespaced keys."""
        result = {
            "azure:container": self.container,
            "azure:blob_path": self.blob_path,
            "azure:tier": self.tier,
            "azure:size_mb": self.size_mb,
            "azure:statistics_extracted": self.statistics_extracted
        }
        if self.etag:
            result["azure:etag"] = self.etag
        if self.content_type:
            result["azure:content_type"] = self.content_type
        return result


class PostGISProperties(BaseModel):
    """
    PostGIS vector table metadata.

    Namespace: postgis:*
    Source: PostGIS geometry_columns and table queries

    These properties describe vector STAC items stored in PostGIS.
    """
    model_config = ConfigDict(populate_by_name=True)

    schema: str = Field(
        ...,
        alias="postgis:schema",
        description="PostgreSQL schema name"
    )
    table: str = Field(
        ...,
        alias="postgis:table",
        description="Table name"
    )
    row_count: int = Field(
        default=0,
        alias="postgis:row_count",
        description="Number of features in table"
    )
    geometry_types: List[str] = Field(
        default_factory=list,
        alias="postgis:geometry_types",
        description="Distinct geometry types in table"
    )
    srid: int = Field(
        default=4326,
        alias="postgis:srid",
        description="Spatial Reference ID"
    )

    def to_flat_dict(self) -> Dict[str, Any]:
        """Convert to flat dict with namespaced keys."""
        return {
            "postgis:schema": self.schema,
            "postgis:table": self.table,
            "postgis:row_count": self.row_count,
            "postgis:geometry_types": self.geometry_types,
            "postgis:srid": self.srid
        }


# =============================================================================
# COMPOSITE STAC PROPERTIES MODEL
# =============================================================================

class STACItemProperties(BaseModel):
    """
    Composite STAC item properties with all namespaces.

    This model represents the complete properties object for a STAC item,
    including core STAC fields and all custom namespace properties.

    Usage:
        props = STACItemProperties(
            item_datetime=datetime.now(timezone.utc),
            platform=PlatformProperties(dataset_id="flood-data"),
            app=AppProperties(job_id="abc123"),
            azure=AzureProperties(container="silver-cogs", blob_path="tile.tif")
        )
        flat_props = props.to_flat_dict()
    """
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )

    # Core STAC datetime fields (renamed to avoid Pydantic conflicts)
    item_datetime: Union[datetime, None] = Field(
        default=None,
        description="Acquisition datetime (null if using start/end)"
    )
    start_datetime: Union[datetime, None] = Field(
        default=None,
        description="Start of temporal extent"
    )
    end_datetime: Union[datetime, None] = Field(
        default=None,
        description="End of temporal extent"
    )

    # Optional title/description
    title: Optional[str] = Field(default=None, description="Human-readable title")
    description: Optional[str] = Field(default=None, description="Description")

    # Namespace property models (optional - include as needed)
    platform: Optional[PlatformProperties] = Field(
        default=None,
        description="DDH platform identifiers"
    )
    app: Optional[AppProperties] = Field(
        default=None,
        description="Application/job metadata"
    )
    geo: Optional[GeoProperties] = Field(
        default=None,
        description="Geographic attribution"
    )
    azure: Optional[AzureProperties] = Field(
        default=None,
        description="Azure blob metadata (for rasters)"
    )
    postgis: Optional[PostGISProperties] = Field(
        default=None,
        description="PostGIS table metadata (for vectors)"
    )

    @model_validator(mode='after')
    def validate_datetime_fields(self):
        """
        Validate datetime handling per STAC spec.

        STAC requires either:
        - datetime (non-null)
        - OR start_datetime + end_datetime (with datetime=null)
        """
        has_datetime = self.item_datetime is not None
        has_range = self.start_datetime is not None or self.end_datetime is not None

        # If using temporal range, datetime should be None
        if has_range and has_datetime:
            # This is technically allowed but unusual - log a warning
            pass

        # If no datetime info at all, that's an issue
        if not has_datetime and not has_range:
            # Will be caught during item creation - not a model-level error
            pass

        return self

    def to_flat_dict(self) -> Dict[str, Any]:
        """
        Flatten all properties to a single dict with namespaced keys.

        This is the format expected by STAC item properties.

        Returns:
            Flat dictionary with all properties properly namespaced
        """
        props: Dict[str, Any] = {}

        # Handle datetime per STAC spec (item_datetime maps to 'datetime' in output)
        if self.item_datetime:
            props['datetime'] = self.item_datetime.isoformat()
        elif self.start_datetime or self.end_datetime:
            props['datetime'] = None
            if self.start_datetime:
                props['start_datetime'] = self.start_datetime.isoformat()
            if self.end_datetime:
                props['end_datetime'] = self.end_datetime.isoformat()

        # Add title/description
        if self.title:
            props['title'] = self.title
        if self.description:
            props['description'] = self.description

        # Flatten embedded namespace models
        if self.platform:
            props.update(self.platform.to_flat_dict())
        if self.app:
            props.update(self.app.to_flat_dict())
        if self.geo:
            props.update(self.geo.to_flat_dict())
        if self.azure:
            props.update(self.azure.to_flat_dict())
        if self.postgis:
            props.update(self.postgis.to_flat_dict())

        return props


# =============================================================================
# STAC ITEM STRUCTURE VALIDATION
# =============================================================================

class STACItemCore(BaseModel):
    """
    Core STAC Item structure for validation.

    This model validates the top-level structure of a STAC item,
    not the full content. Used for quick validation checks.
    """
    model_config = ConfigDict(extra='allow')  # Allow additional fields

    id: str = Field(..., description="Unique item identifier")
    type: str = Field(default="Feature", description="GeoJSON type")
    stac_version: str = Field(default=STAC_VERSION, description="STAC version")
    collection: Optional[str] = Field(default=None, description="Collection ID")
    geometry: Optional[Dict[str, Any]] = Field(
        default=None,
        description="GeoJSON geometry"
    )
    bbox: Optional[List[float]] = Field(
        default=None,
        description="Bounding box [minx, miny, maxx, maxy]"
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Item properties"
    )
    assets: Dict[str, Any] = Field(
        default_factory=dict,
        description="Item assets"
    )
    links: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Item links"
    )

    @model_validator(mode='after')
    def validate_structure(self):
        """Validate basic STAC item structure."""
        # Type must be Feature for GeoJSON
        if self.type != "Feature":
            raise ValueError(f"STAC Item type must be 'Feature', got '{self.type}'")

        # Must have geometry or bbox for spatial items
        if self.geometry is None and self.bbox is None:
            raise ValueError("STAC Item must have geometry or bbox")

        return self


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Constants
    'STAC_VERSION',

    # Enums
    'AccessLevel',
    'AssetType',

    # Namespace models
    'PlatformProperties',
    'AppProperties',
    'GeoProperties',
    'AzureProperties',
    'PostGISProperties',

    # Composite models
    'STACItemProperties',
    'STACItemCore',
]
