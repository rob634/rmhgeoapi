# ============================================================================
# STAC DATA MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE (Aligned with Epoch 5 patterns)
# STATUS: Core - Centralized STAC property schemas
# PURPOSE: Type-safe Pydantic models for STAC property namespaces
# LAST_REVIEWED: 16 FEB 2026
# ============================================================================
"""
STAC Data Models.

Centralized Pydantic models for all STAC property namespaces. These models
enforce type safety and consistency across all STAC item/collection creation.

Aligned with Epoch 5 (rmhdagmaster/core/models/stac_properties.py) so that
both apps produce structurally compatible items in the shared pgstac catalog.

Design Principle:
    ALL STAC property namespaces are defined here. Service files import from
    this module to ensure consistency.

Namespaces:
    - geoetl:* - Platform provenance (via APP_PREFIX, custom properties)
    - ddh:* - DDH platform identifiers (B2B passthrough)
    - geo:* - Geographic attribution (ISO3 codes)
    - postgis:* - PostGIS vector table metadata

Extension URL Constants:
    STAC_EXT_PROJECTION, STAC_EXT_RASTER, STAC_EXT_FILE,
    STAC_EXT_RENDER, STAC_EXT_PROCESSING

Created: 22 DEC 2025
V0.9 Alignment: 16 FEB 2026
"""

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, model_validator


# =============================================================================
# CONSTANTS
# =============================================================================

# Single source of truth for STAC specification version
# All STAC items and collections MUST use this version
STAC_VERSION = "1.0.0"

# App prefix — single point of change (aligned with Epoch 5 rmhdagmaster)
APP_PREFIX = "geoetl"

# STAC Extension URLs (standard extensions used by both Epoch 4 and Epoch 5)
STAC_EXT_PROJECTION = "https://stac-extensions.github.io/projection/v1.0.0/schema.json"
STAC_EXT_RASTER = "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
STAC_EXT_FILE = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
STAC_EXT_RENDER = "https://stac-extensions.github.io/render/v2.0.0/schema.json"
STAC_EXT_PROCESSING = "https://stac-extensions.github.io/processing/v1.2.0/schema.json"


# =============================================================================
# ENUMS
# =============================================================================

class AccessLevel(str, Enum):
    """
    Data access classification levels - SINGLE SOURCE OF TRUTH.

    Used across the entire codebase for data classification:
    - Pydantic models (PlatformRequest, DatasetApproval, PromotedDataset)
    - SQL ENUMs (app.access_level_enum)
    - Service Bus messages
    - STAC item properties (ddh:access_level)

    Values:
        PUBLIC: Data can be exported to external-facing storage (ADF handles this)
        OUO: Official Use Only - internal access only, no external export
        RESTRICTED: Highest restriction - no external access (FUTURE ENHANCEMENT)

    NOTE: RESTRICTED is defined for forward compatibility but is NOT YET SUPPORTED.
          Current system only enforces PUBLIC vs OUO distinction.
          Do not use RESTRICTED until E4 Phase 3 is complete.
    """
    PUBLIC = "public"
    OUO = "ouo"  # Official Use Only
    RESTRICTED = "restricted"  # NOT YET SUPPORTED - future enhancement

    # -------------------------------------------------------------------------
    # SQL DDL Generation (S4.DM.3)
    # -------------------------------------------------------------------------
    # These class methods generate SQL for schema management.
    # Since we rebuild schemas in DEV, these are mainly for documentation.
    # -------------------------------------------------------------------------

    @classmethod
    def sql_type_name(cls) -> str:
        """Return the PostgreSQL ENUM type name."""
        return "access_level_enum"

    @classmethod
    def sql_create_type(cls, schema: str = "app") -> str:
        """
        Generate CREATE TYPE statement for PostgreSQL ENUM.

        Args:
            schema: Database schema name (default: app)

        Returns:
            SQL CREATE TYPE statement
        """
        values = ", ".join(f"'{v.value}'" for v in cls)
        return f"CREATE TYPE {schema}.{cls.sql_type_name()} AS ENUM ({values});"

    @classmethod
    def supported_values(cls) -> list[str]:
        """
        Return list of currently supported values.

        NOTE: Excludes RESTRICTED which is not yet supported.
        """
        return ["public", "ouo"]  # RESTRICTED excluded until E4 Phase 3


class AssetType(str, Enum):
    """STAC asset types."""
    RASTER = "raster"
    VECTOR = "vector"
    MIXED = "mixed"


# =============================================================================
# ACCESS LEVEL FIELD HELPER (S4.DM.6)
# =============================================================================

def normalize_access_level(value: Any) -> AccessLevel:
    """
    Normalize access level input to AccessLevel enum.

    Accepts case-insensitive strings and AccessLevel instances.
    NOTE: RESTRICTED is accepted but not yet supported in the system.

    Args:
        value: String or AccessLevel value

    Returns:
        AccessLevel enum value

    Raises:
        ValueError: If value is not a valid access level
    """
    if isinstance(value, AccessLevel):
        return value
    if isinstance(value, str):
        try:
            return AccessLevel(value.lower())
        except ValueError:
            valid = ", ".join(v.value for v in AccessLevel)
            raise ValueError(
                f"Invalid access_level '{value}'. Must be one of: {valid}. "
                f"NOTE: 'restricted' is not yet supported."
            )
    raise ValueError(f"access_level must be string or AccessLevel, got {type(value).__name__}")


# =============================================================================
# NAMESPACE PROPERTY MODELS
# =============================================================================

class ProvenanceProperties(BaseModel):
    """
    Custom platform provenance properties.

    Namespace: geoetl:* (via APP_PREFIX)
    Only properties that have NO standard STAC extension equivalent.
    Uses APP_PREFIX for dynamic namespace (one-line change when app is named).

    Aligned with Epoch 5: rmhdagmaster/core/models/stac_properties.py

    Properties:
        job_id: Which processing job created this item
        managed_by: Which system manages this item (multi-producer catalog)
        epoch: Processing system version (internal versioning)
        raster_type: Domain-specific type classification (dem, rgb, categorical...)
        processing_seconds: How long processing took
        statistics_extracted: Whether band stats were computed
    """
    model_config = ConfigDict(populate_by_name=True)

    job_id: Optional[str] = Field(default=None)
    managed_by: str = Field(default=APP_PREFIX)  # "geoetl" — the ETL system
    epoch: int = Field(default=4)                # this codebase is Epoch 4
    raster_type: Optional[str] = Field(default=None)
    processing_seconds: Optional[float] = Field(default=None)
    statistics_extracted: Optional[bool] = Field(default=None)

    def to_prefixed_dict(self) -> dict:
        """Serialize with APP_PREFIX, excluding None values."""
        raw = self.model_dump(exclude_none=True)
        return {f"{APP_PREFIX}:{k}": v for k, v in raw.items()}


class PlatformProperties(BaseModel):
    """
    DDH platform identifiers — B2B passthrough.

    Namespace: ddh:*
    These are external identifiers from the upstream platform.
    Always use 'ddh:' prefix (not configurable — it's the platform name).

    Aligned with Epoch 5: rmhdagmaster/core/models/stac_properties.py
    """
    model_config = ConfigDict(populate_by_name=True)

    dataset_id: Optional[str] = Field(default=None, alias="ddh:dataset_id")
    resource_id: Optional[str] = Field(default=None, alias="ddh:resource_id")
    version_id: Optional[str] = Field(default=None, alias="ddh:version_id")
    access_level: Optional[str] = Field(default=None, alias="ddh:access_level")


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
    'APP_PREFIX',
    'STAC_EXT_PROJECTION',
    'STAC_EXT_RASTER',
    'STAC_EXT_FILE',
    'STAC_EXT_RENDER',
    'STAC_EXT_PROCESSING',

    # Enums
    'AccessLevel',
    'AssetType',

    # Helpers
    'normalize_access_level',

    # Namespace models
    'ProvenanceProperties',   # NEW (geoetl:*)
    'PlatformProperties',     # REWRITTEN (ddh:*)
    'GeoProperties',          # UNCHANGED (geo:*)
    'PostGISProperties',      # UNCHANGED (postgis:*)

    # Structural validation
    'STACItemCore',           # UNCHANGED
]
