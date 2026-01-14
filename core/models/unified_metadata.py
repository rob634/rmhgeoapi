# ============================================================================
# UNIFIED METADATA MODELS
# ============================================================================
# STATUS: Core - Single source of truth for dataset metadata
# PURPOSE: Pydantic models mapping to both OGC Features and STAC APIs
# LAST_REVIEWED: 09 JAN 2026
# REVIEW_STATUS: Check 8 N/A - no infrastructure config
# ============================================================================
"""
Unified Metadata Models.

Provides a single source of truth for dataset metadata that maps cleanly to:
- OGC API Features collection responses
- STAC Collection/Item responses
- geo.table_metadata database table

Design Principles:
    1. Single Source of Truth - geo.table_metadata is canonical
    2. No Duplication - STAC indexes data but doesn't duplicate metadata
    3. Consistent Structure - Same metadata from OGC or STAC endpoints
    4. STAC Alignment - Use STAC extensions and field names where possible

Architecture (from METADATA.md):
    BaseMetadata (abstract base)
        ├── VectorMetadata      → geo.table_metadata
        ├── RasterMetadata      → raster.cog_metadata (future E2)
        └── ZarrMetadata        → zarr.dataset_metadata (future E9)

Pattern for Creating New Metadata Types (S7.8.9):
    1. Create new class inheriting from BaseMetadata
    2. Add type-specific fields (e.g., band_count for raster, chunks for zarr)
    3. Implement factory method: from_db_row(row: Dict) -> "NewMetadata"
    4. Implement conversion methods:
       - to_ogc_properties() → Dict for OGC API properties block
       - to_ogc_collection(base_url) → Dict for full OGC collection
       - to_stac_collection(base_url) → Dict for STAC collection
       - to_stac_item(base_url) → Dict for STAC item
    5. Add type to DataType enum in external_refs.py
    6. Wire into STAC cataloging handlers to call dataset_refs_repository

Example RasterMetadata skeleton:
    class RasterMetadata(BaseMetadata):
        band_count: int
        dtype: str  # uint8, float32, etc.
        cog_url: str
        resolution: float

        @classmethod
        def from_db_row(cls, row: Dict) -> "RasterMetadata": ...
        def to_stac_item(self, base_url: str) -> Dict: ...

Exports:
    ProviderRole: STAC provider roles enum
    Provider: STAC provider model
    SpatialExtent: Spatial extent with bbox
    TemporalExtent: Temporal extent with interval
    Extent: Combined spatial and temporal extent
    BaseMetadata: Abstract base for all metadata types
    VectorMetadata: Vector dataset metadata (geo.table_metadata)

Created: 09 JAN 2026
Epic: E7 Pipeline Infrastructure → F7.8 Unified Metadata Architecture
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# STAC PROVIDER MODEL
# =============================================================================

class ProviderRole(str, Enum):
    """
    STAC Provider roles.

    Per STAC spec, providers can have multiple roles describing their
    relationship to the data.
    """
    LICENSOR = "licensor"      # Owns or licenses the data
    PRODUCER = "producer"      # Created the data
    PROCESSOR = "processor"    # Processed/transformed the data
    HOST = "host"              # Hosts/serves the data


class Provider(BaseModel):
    """
    STAC Provider definition.

    Represents an organization or entity involved in producing,
    processing, licensing, or hosting data.

    Example:
        Provider(
            name="FATHOM",
            roles=[ProviderRole.PRODUCER, ProviderRole.LICENSOR],
            url="https://www.fathom.global/"
        )
    """
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(..., description="Provider name")
    description: Optional[str] = Field(
        default=None,
        description="Provider description"
    )
    roles: List[ProviderRole] = Field(
        default_factory=list,
        description="Provider roles (licensor, producer, processor, host)"
    )
    url: Optional[str] = Field(
        default=None,
        description="Provider URL"
    )

    def to_stac_dict(self) -> Dict[str, Any]:
        """Convert to STAC provider format."""
        result = {"name": self.name, "roles": self.roles}
        if self.description:
            result["description"] = self.description
        if self.url:
            result["url"] = self.url
        return result


# =============================================================================
# EXTENT MODELS
# =============================================================================

class SpatialExtent(BaseModel):
    """
    Spatial extent with bounding box.

    Per OGC/STAC spec, bbox is [[minx, miny, maxx, maxy]] (nested array).
    """
    bbox: List[List[float]] = Field(
        ...,
        description="Bounding boxes [[minx, miny, maxx, maxy]]"
    )
    crs: str = Field(
        default="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        description="Coordinate reference system URI"
    )

    @classmethod
    def from_flat_bbox(
        cls,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float
    ) -> "SpatialExtent":
        """Create from flat bbox coordinates."""
        return cls(bbox=[[minx, miny, maxx, maxy]])


class TemporalExtent(BaseModel):
    """
    Temporal extent with interval.

    Per STAC spec, interval is [[start, end]] where values are ISO 8601
    strings or null for open-ended intervals.
    """
    interval: List[List[Optional[str]]] = Field(
        ...,
        description="Temporal intervals [[start, end]] in ISO 8601"
    )

    @classmethod
    def from_datetimes(
        cls,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> "TemporalExtent":
        """Create from datetime objects."""
        start_str = start.isoformat() if start else None
        end_str = end.isoformat() if end else None
        return cls(interval=[[start_str, end_str]])


class Extent(BaseModel):
    """Combined spatial and temporal extent."""
    spatial: Optional[SpatialExtent] = None
    temporal: Optional[TemporalExtent] = None


# =============================================================================
# BASE METADATA MODEL
# =============================================================================

class BaseMetadata(BaseModel):
    """
    Abstract base for all dataset metadata types.

    Contains fields common to all data types (vector, raster, zarr).
    Subclasses add type-specific fields.

    This follows the Open/Closed Principle - extend via inheritance,
    don't modify the base class.
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore'  # Ignore unknown fields from DB
    )

    # Identity
    id: str = Field(..., description="Dataset/collection identifier")

    # Core STAC fields
    title: Optional[str] = Field(
        default=None,
        description="Human-readable title"
    )
    description: Optional[str] = Field(
        default=None,
        description="Dataset description"
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="Discovery keywords"
    )
    license: Optional[str] = Field(
        default=None,
        description="SPDX license identifier (e.g., 'CC-BY-4.0', 'proprietary')"
    )

    # Providers (STAC standard)
    providers: List[Provider] = Field(
        default_factory=list,
        description="Data providers with roles"
    )

    # STAC Extensions
    stac_extensions: List[str] = Field(
        default_factory=list,
        description="STAC extension URIs"
    )

    # Extent
    extent: Optional[Extent] = Field(
        default=None,
        description="Spatial and temporal extent"
    )

    # ETL Traceability (Processing Extension)
    etl_job_id: Optional[str] = Field(
        default=None,
        description="CoreMachine job ID that created this dataset"
    )
    source_file: Optional[str] = Field(
        default=None,
        description="Original source filename"
    )
    source_format: Optional[str] = Field(
        default=None,
        description="Source file format (shp, gpkg, geojson, tif, etc.)"
    )
    source_crs: Optional[str] = Field(
        default=None,
        description="Original CRS before reprojection"
    )

    # STAC Linkage
    stac_item_id: Optional[str] = Field(
        default=None,
        description="STAC item ID (if cataloged)"
    )
    stac_collection_id: Optional[str] = Field(
        default=None,
        description="STAC collection ID (if cataloged)"
    )

    # Timestamps
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the dataset was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="When metadata was last updated"
    )

    # Scientific metadata (optional)
    sci_doi: Optional[str] = Field(
        default=None,
        description="Scientific DOI if applicable"
    )
    sci_citation: Optional[str] = Field(
        default=None,
        description="Citation text"
    )

    # Custom properties (extension point)
    custom_properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional custom properties (JSONB in database)"
    )

    def get_attribution(self) -> Optional[str]:
        """
        Get attribution string from providers.

        Returns comma-separated provider names for simple attribution display.
        """
        if not self.providers:
            return None
        return ", ".join(p.name for p in self.providers)


# =============================================================================
# VECTOR METADATA MODEL
# =============================================================================

class VectorMetadata(BaseMetadata):
    """
    Vector dataset metadata.

    Maps to geo.table_metadata table. Contains all fields needed for
    both OGC Features and STAC API responses.

    STAC Extensions:
        - table: For vector-specific fields (row_count, geometry_types)
        - processing: For ETL traceability

    Example:
        metadata = VectorMetadata(
            id="admin_boundaries_chile",
            title="Chile Administrative Boundaries",
            feature_count=156,
            geometry_type="MultiPolygon",
            extent=Extent(
                spatial=SpatialExtent.from_flat_bbox(-75.6, -55.9, -66.4, -17.5)
            ),
            providers=[Provider(name="OpenStreetMap", roles=["producer"])]
        )
    """

    # Table Extension fields (vector-specific)
    feature_count: Optional[int] = Field(
        default=None,
        description="Number of features in the table"
    )
    geometry_type: Optional[str] = Field(
        default=None,
        description="PostGIS geometry type (Point, LineString, Polygon, etc.)"
    )
    primary_geometry_column: Optional[str] = Field(
        default="geom",
        description="Name of the primary geometry column"
    )
    srid: int = Field(
        default=4326,
        description="Spatial Reference ID"
    )

    # Schema information
    schema_name: str = Field(
        default="geo",
        description="PostgreSQL schema name"
    )

    # Temporal query support
    temporal_property: Optional[str] = Field(
        default=None,
        description="Column name for temporal queries"
    )

    # Table type (curated vs user)
    table_type: str = Field(
        default="user",
        description="Table type (user, curated, system)"
    )

    # Legacy attribution (for backward compatibility)
    # Use providers instead for new code
    attribution: Optional[str] = Field(
        default=None,
        description="Legacy attribution string (use providers instead)"
    )

    # Column definitions (Table Extension)
    column_definitions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Column metadata for Table Extension"
    )

    # Processing metadata
    processing_software: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Processing software info (name, version)"
    )

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "VectorMetadata":
        """
        Create VectorMetadata from geo.table_metadata database row.

        Handles field mapping and type conversion from database format
        to Pydantic model.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            VectorMetadata instance
        """
        # Build extent from bbox columns
        extent = None
        bbox_minx = row.get('bbox_minx')
        bbox_miny = row.get('bbox_miny')
        bbox_maxx = row.get('bbox_maxx')
        bbox_maxy = row.get('bbox_maxy')

        if all(v is not None for v in [bbox_minx, bbox_miny, bbox_maxx, bbox_maxy]):
            spatial = SpatialExtent.from_flat_bbox(
                bbox_minx, bbox_miny, bbox_maxx, bbox_maxy
            )
            # Build temporal extent if present
            temporal = None
            temporal_start = row.get('temporal_start')
            temporal_end = row.get('temporal_end')
            if temporal_start or temporal_end:
                temporal = TemporalExtent.from_datetimes(temporal_start, temporal_end)

            extent = Extent(spatial=spatial, temporal=temporal)

        # Parse keywords from comma-separated string
        keywords_str = row.get('keywords')
        keywords = []
        if keywords_str:
            keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]

        # Parse providers from JSONB (if present)
        providers = []
        providers_data = row.get('providers')
        if providers_data and isinstance(providers_data, list):
            providers = [Provider(**p) for p in providers_data]
        elif row.get('attribution'):
            # Legacy: convert attribution string to single provider
            providers = [Provider(name=row['attribution'], roles=[ProviderRole.PRODUCER])]

        # Parse STAC extensions from JSONB
        stac_extensions = row.get('stac_extensions') or []

        return cls(
            id=row.get('table_name'),
            title=row.get('title'),
            description=row.get('description'),
            keywords=keywords,
            license=row.get('license'),
            providers=providers,
            stac_extensions=stac_extensions,
            extent=extent,
            etl_job_id=row.get('etl_job_id'),
            source_file=row.get('source_file'),
            source_format=row.get('source_format'),
            source_crs=row.get('source_crs'),
            stac_item_id=row.get('stac_item_id'),
            stac_collection_id=row.get('stac_collection_id'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
            sci_doi=row.get('sci_doi'),
            sci_citation=row.get('sci_citation'),
            feature_count=row.get('feature_count'),
            geometry_type=row.get('geometry_type'),
            primary_geometry_column=row.get('primary_geometry') or 'geom',
            schema_name=row.get('schema_name') or 'geo',
            temporal_property=row.get('temporal_property'),
            table_type=row.get('table_type') or 'user',
            attribution=row.get('attribution'),
            column_definitions=row.get('column_definitions'),
            processing_software=row.get('processing_software'),
            custom_properties=row.get('custom_properties') or {}
        )

    # =========================================================================
    # CONVERSION METHODS
    # =========================================================================

    def to_ogc_properties(self) -> Dict[str, Any]:
        """
        Convert to OGC Features collection properties block.

        Returns properties dict with namespaced keys for OGC API response.
        """
        props: Dict[str, Any] = {}

        # ETL traceability (source:* namespace)
        if self.etl_job_id:
            props["etl:job_id"] = self.etl_job_id
        if self.source_file:
            props["source:file"] = self.source_file
        if self.source_format:
            props["source:format"] = self.source_format
        if self.source_crs:
            props["source:crs"] = self.source_crs

        # STAC linkage (stac:* namespace)
        if self.stac_item_id:
            props["stac:item_id"] = self.stac_item_id
        if self.stac_collection_id:
            props["stac:collection_id"] = self.stac_collection_id

        # Timestamps
        if self.created_at:
            props["created"] = self.created_at.isoformat()
        if self.updated_at:
            props["updated"] = self.updated_at.isoformat()

        # Core metadata
        if self.license:
            props["license"] = self.license
        if self.keywords:
            props["keywords"] = self.keywords
        if self.feature_count is not None:
            props["feature_count"] = self.feature_count

        # Attribution (from providers or legacy field)
        attribution = self.get_attribution() or self.attribution
        if attribution:
            props["attribution"] = attribution

        # Temporal query support
        if self.temporal_property:
            props["temporal_property"] = self.temporal_property

        # Scientific metadata
        if self.sci_doi:
            props["sci:doi"] = self.sci_doi
        if self.sci_citation:
            props["sci:citation"] = self.sci_citation

        # Include any custom properties
        props.update(self.custom_properties)

        return props

    def to_ogc_collection(
        self,
        tipg_base_url: str,
        fallback_base_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Convert to full OGC Features Collection response.

        Updated 13 JAN 2026 (E8 TiPG Integration):
        - Primary links use TiPG URL pattern (high-performance Docker endpoint)
        - Fallback URL (Function App) stored in properties for redundancy

        Args:
            tipg_base_url: TiPG base URL for primary links (e.g., https://titiler.../vector)
            fallback_base_url: Optional Function App URL for secondary access
                              (e.g., https://funcapp.../api/features)

        Returns:
            Complete OGC Collection dict with TiPG as primary endpoint
        """
        # Build properties including fallback URL if provided
        properties = self.to_ogc_properties()

        # TiPG requires schema-qualified table names (14 JAN 2026)
        tipg_collection_id = f"{self.schema_name}.{self.id}"

        if fallback_base_url:
            properties["ogc:fallback_url"] = f"{fallback_base_url}/collections/{tipg_collection_id}/items"

        collection: Dict[str, Any] = {
            "id": self.id,
            "title": self.title or self.id.replace("_", " ").title(),
            "description": self.description or f"Vector dataset: {self.id}",
            "links": [
                {
                    "href": f"{tipg_base_url}/collections/{tipg_collection_id}",
                    "rel": "self",
                    "type": "application/json",
                    "title": "This collection"
                },
                {
                    "href": f"{tipg_base_url}/collections/{tipg_collection_id}/items",
                    "rel": "items",
                    "type": "application/geo+json",
                    "title": "Collection items"
                },
                {
                    "href": f"{tipg_base_url}/collections",
                    "rel": "parent",
                    "type": "application/json",
                    "title": "All collections"
                }
            ],
            "itemType": "feature",
            "crs": [
                "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
                "http://www.opengis.net/def/crs/EPSG/0/4326"
            ],
            "properties": properties
        }

        # Add extent if available
        if self.extent:
            extent_dict: Dict[str, Any] = {}
            if self.extent.spatial:
                extent_dict["spatial"] = {
                    "bbox": self.extent.spatial.bbox,
                    "crs": self.extent.spatial.crs
                }
            if self.extent.temporal:
                extent_dict["temporal"] = {
                    "interval": self.extent.temporal.interval
                }
            if extent_dict:
                collection["extent"] = extent_dict

        # Add storage CRS
        if self.srid:
            collection["storageCrs"] = f"http://www.opengis.net/def/crs/EPSG/0/{self.srid}"

        return collection

    def to_stac_collection(self, base_url: str) -> Dict[str, Any]:
        """
        Convert to STAC Collection response.

        Args:
            base_url: Base URL for link generation

        Returns:
            Complete STAC Collection dict
        """
        from core.models.stac import STAC_VERSION

        # TiPG requires schema-qualified table names (14 JAN 2026)
        tipg_collection_id = f"{self.schema_name}.{self.id}"

        collection: Dict[str, Any] = {
            "type": "Collection",
            "stac_version": STAC_VERSION,
            "stac_extensions": self.stac_extensions or [
                "https://stac-extensions.github.io/table/v1.2.0/schema.json"
            ],
            "id": self.id,
            "title": self.title or self.id.replace("_", " ").title(),
            "description": self.description or f"Vector dataset: {self.id}",
            "keywords": self.keywords or [],
            "license": self.license or "proprietary",
            "providers": [p.to_stac_dict() for p in self.providers],
            "links": [
                {
                    "rel": "self",
                    "href": f"{base_url}/api/stac/collections/{self.id}",
                    "type": "application/json"
                },
                {
                    "rel": "items",
                    "href": f"{base_url}/api/stac/collections/{self.id}/items",
                    "type": "application/geo+json"
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/items",
                    "href": f"{base_url}/api/features/collections/{tipg_collection_id}/items",
                    "type": "application/geo+json",
                    "title": "OGC Features API items"
                }
            ]
        }

        # Add extent if available
        if self.extent:
            extent_dict: Dict[str, Any] = {}
            if self.extent.spatial:
                extent_dict["spatial"] = {
                    "bbox": self.extent.spatial.bbox
                }
            if self.extent.temporal:
                extent_dict["temporal"] = {
                    "interval": self.extent.temporal.interval
                }
            collection["extent"] = extent_dict if extent_dict else {}
        else:
            collection["extent"] = {}

        # Add Table Extension summaries
        if self.feature_count or self.geometry_type:
            collection["summaries"] = {}
            if self.feature_count is not None:
                collection["summaries"]["table:row_count"] = [self.feature_count]
            if self.geometry_type:
                collection["summaries"]["table:primary_geometry_type"] = [self.geometry_type]

        return collection

    def to_stac_item(
        self,
        tipg_base_url: str,
        stac_base_url: str,
        fallback_base_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Convert to STAC Item response.

        Creates a STAC Item representing this vector dataset.

        Updated 13 JAN 2026 (E8 TiPG Integration):
        - OGC Features links use TiPG URL pattern (high-performance Docker endpoint)
        - STAC links use the STAC API base URL
        - Fallback URL (Function App) stored in properties for redundancy

        Args:
            tipg_base_url: TiPG base URL for OGC Features links (e.g., https://titiler.../vector)
            stac_base_url: STAC API base URL for self/collection links (e.g., https://funcapp.../api/stac)
            fallback_base_url: Optional Function App URL for secondary access
                              (e.g., https://funcapp.../api/features)

        Returns:
            Complete STAC Item dict with TiPG as primary OGC endpoint
        """
        from core.models.stac import STAC_VERSION

        # Build bbox from extent
        bbox = None
        geometry = None
        if self.extent and self.extent.spatial and self.extent.spatial.bbox:
            bbox = self.extent.spatial.bbox[0]  # First bbox
            minx, miny, maxx, maxy = bbox
            geometry = {
                "type": "Polygon",
                "coordinates": [[
                    [minx, miny],
                    [maxx, miny],
                    [maxx, maxy],
                    [minx, maxy],
                    [minx, miny]
                ]]
            }

        # Build properties
        properties: Dict[str, Any] = {
            "title": self.title,
            "description": self.description
        }

        # Handle datetime per STAC spec
        if self.extent and self.extent.temporal and self.extent.temporal.interval:
            interval = self.extent.temporal.interval[0]
            if interval[0] and interval[1]:
                properties["datetime"] = None
                properties["start_datetime"] = interval[0]
                properties["end_datetime"] = interval[1]
            elif interval[0]:
                properties["datetime"] = interval[0]
            else:
                properties["datetime"] = (
                    self.created_at.isoformat() if self.created_at
                    else None
                )
        else:
            properties["datetime"] = (
                self.created_at.isoformat() if self.created_at
                else None
            )

        # Table Extension properties
        if self.feature_count is not None:
            properties["table:row_count"] = self.feature_count
        if self.geometry_type:
            properties["table:primary_geometry_type"] = self.geometry_type
        if self.primary_geometry_column:
            properties["table:primary_geometry"] = self.primary_geometry_column

        # PostGIS properties
        properties["postgis:schema"] = self.schema_name
        properties["postgis:table"] = self.id
        properties["postgis:srid"] = self.srid

        # ETL traceability
        if self.etl_job_id:
            properties["processing:lineage"] = f"ETL job {self.etl_job_id}"
        if self.source_file:
            properties["processing:source_file"] = self.source_file

        # Add fallback URL if provided (13 JAN 2026 - E8 TiPG Integration)
        # TiPG requires schema-qualified table names (14 JAN 2026)
        tipg_collection_id = f"{self.schema_name}.{self.id}"
        if fallback_base_url:
            properties["ogc:fallback_url"] = f"{fallback_base_url}/collections/{tipg_collection_id}/items"

        # Build TiPG OGC Features URL (primary endpoint)
        tipg_items_url = f"{tipg_base_url}/collections/{tipg_collection_id}/items"

        item: Dict[str, Any] = {
            "type": "Feature",
            "stac_version": STAC_VERSION,
            "stac_extensions": self.stac_extensions or [
                "https://stac-extensions.github.io/table/v1.2.0/schema.json",
                "https://stac-extensions.github.io/processing/v1.1.0/schema.json"
            ],
            "id": self.stac_item_id or self.id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": properties,
            "collection": self.stac_collection_id,
            "links": [
                {
                    "rel": "self",
                    "href": f"{stac_base_url}/collections/{self.stac_collection_id}/items/{self.stac_item_id or self.id}",
                    "type": "application/geo+json"
                },
                {
                    "rel": "collection",
                    "href": f"{stac_base_url}/collections/{self.stac_collection_id}",
                    "type": "application/json"
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/items",
                    "href": tipg_items_url,
                    "type": "application/geo+json",
                    "title": "OGC Features API (TiPG)"
                }
            ],
            "assets": {
                "data": {
                    "href": tipg_items_url,
                    "type": "application/geo+json",
                    "title": "Vector features (TiPG)",
                    "roles": ["data"]
                }
            }
        }

        return item


# =============================================================================
# RASTER METADATA MODEL
# =============================================================================

class RasterMetadata(BaseMetadata):
    """
    Raster (COG) dataset metadata.

    Maps to app.cog_metadata table. Contains all fields needed for
    STAC API responses for raster data.

    STAC Extensions:
        - raster: For raster-specific fields (band_count, dtype)
        - eo: For electro-optical band metadata
        - processing: For ETL traceability
        - projection: For CRS and transform

    Example:
        metadata = RasterMetadata(
            id="fathom_fluvial_defended_2020",
            title="FATHOM Fluvial Defended 2020",
            cog_url="/vsiaz/silver-fathom/merged/fluvial_defended_2020.tif",
            container="silver-fathom",
            blob_path="merged/fluvial_defended_2020.tif",
            width=10000,
            height=8000,
            band_count=8,
            dtype="float32",
            crs="EPSG:4326",
            resolution=(0.001, 0.001),
            extent=Extent(
                spatial=SpatialExtent.from_flat_bbox(28.0, -3.5, 31.0, -1.0)
            ),
            providers=[Provider(name="FATHOM", roles=["producer", "licensor"])]
        )
    """

    # COG-specific fields (required)
    cog_url: str = Field(
        ...,
        description="Full COG URL (/vsiaz/ path or HTTPS URL)"
    )
    container: str = Field(
        ...,
        description="Azure storage container name"
    )
    blob_path: str = Field(
        ...,
        description="Path within container"
    )

    # Raster properties (required)
    width: int = Field(
        ...,
        description="Raster width in pixels"
    )
    height: int = Field(
        ...,
        description="Raster height in pixels"
    )
    band_count: int = Field(
        default=1,
        description="Number of bands"
    )
    dtype: str = Field(
        default="float32",
        description="Numpy dtype (uint8, int16, float32, etc.)"
    )
    nodata: Optional[float] = Field(
        default=None,
        description="NoData value"
    )
    crs: str = Field(
        default="EPSG:4326",
        description="CRS as EPSG code or WKT"
    )
    transform: Optional[List[float]] = Field(
        default=None,
        description="Affine transform (6 values: a, b, c, d, e, f)"
    )
    resolution: Optional[List[float]] = Field(
        default=None,
        description="Resolution [x_res, y_res] in CRS units"
    )

    # Band metadata
    band_names: List[str] = Field(
        default_factory=list,
        description="Band descriptions/names"
    )
    band_units: Optional[List[str]] = Field(
        default=None,
        description="Units per band"
    )

    # COG processing metadata
    is_cog: bool = Field(
        default=True,
        description="Cloud-optimized GeoTIFF flag"
    )
    overview_levels: Optional[List[int]] = Field(
        default=None,
        description="COG overview levels"
    )
    compression: Optional[str] = Field(
        default=None,
        description="Compression method (DEFLATE, LZW, etc.)"
    )
    blocksize: Optional[List[int]] = Field(
        default=None,
        description="Internal tile size [width, height]"
    )

    # Visualization defaults
    colormap: Optional[str] = Field(
        default=None,
        description="Default colormap name for TiTiler"
    )
    rescale_range: Optional[List[float]] = Field(
        default=None,
        description="Default rescale [min, max] for visualization"
    )

    # STAC extensions - EO band metadata
    eo_bands: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="EO extension band metadata (name, description, common_name)"
    )

    # Raster extension - per-band statistics
    raster_bands: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Raster extension band stats (min, max, mean, stddev)"
    )

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "RasterMetadata":
        """
        Create RasterMetadata from app.cog_metadata database row.

        Handles field mapping and type conversion from database format
        to Pydantic model.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            RasterMetadata instance
        """
        # Build extent from bbox columns
        extent = None
        bbox_minx = row.get('bbox_minx')
        bbox_miny = row.get('bbox_miny')
        bbox_maxx = row.get('bbox_maxx')
        bbox_maxy = row.get('bbox_maxy')

        if all(v is not None for v in [bbox_minx, bbox_miny, bbox_maxx, bbox_maxy]):
            spatial = SpatialExtent.from_flat_bbox(
                bbox_minx, bbox_miny, bbox_maxx, bbox_maxy
            )
            # Build temporal extent if present
            temporal = None
            temporal_start = row.get('temporal_start')
            temporal_end = row.get('temporal_end')
            if temporal_start or temporal_end:
                temporal = TemporalExtent.from_datetimes(temporal_start, temporal_end)

            extent = Extent(spatial=spatial, temporal=temporal)

        # Parse keywords from comma-separated string
        keywords_str = row.get('keywords')
        keywords = []
        if keywords_str:
            keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]

        # Parse providers from JSONB (if present)
        providers = []
        providers_data = row.get('providers')
        if providers_data and isinstance(providers_data, list):
            providers = [Provider(**p) for p in providers_data]

        # Parse STAC extensions from JSONB
        stac_extensions = row.get('stac_extensions') or []

        # Parse band_names from JSONB or comma-separated string
        band_names_data = row.get('band_names')
        band_names = []
        if isinstance(band_names_data, list):
            band_names = band_names_data
        elif isinstance(band_names_data, str):
            band_names = [b.strip() for b in band_names_data.split(',') if b.strip()]

        return cls(
            id=row.get('cog_id') or row.get('id'),
            title=row.get('title'),
            description=row.get('description'),
            keywords=keywords,
            license=row.get('license'),
            providers=providers,
            stac_extensions=stac_extensions,
            extent=extent,
            etl_job_id=row.get('etl_job_id'),
            source_file=row.get('source_file'),
            source_format=row.get('source_format') or 'geotiff',
            source_crs=row.get('source_crs'),
            stac_item_id=row.get('stac_item_id'),
            stac_collection_id=row.get('stac_collection_id'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at'),
            sci_doi=row.get('sci_doi'),
            sci_citation=row.get('sci_citation'),
            cog_url=row.get('cog_url') or '',
            container=row.get('container') or '',
            blob_path=row.get('blob_path') or '',
            width=row.get('width') or 0,
            height=row.get('height') or 0,
            band_count=row.get('band_count') or 1,
            dtype=row.get('dtype') or 'float32',
            nodata=row.get('nodata'),
            crs=row.get('crs') or 'EPSG:4326',
            transform=row.get('transform'),
            resolution=row.get('resolution'),
            band_names=band_names,
            band_units=row.get('band_units'),
            is_cog=row.get('is_cog', True),
            overview_levels=row.get('overview_levels'),
            compression=row.get('compression'),
            blocksize=row.get('blocksize'),
            colormap=row.get('colormap'),
            rescale_range=row.get('rescale_range'),
            eo_bands=row.get('eo_bands'),
            raster_bands=row.get('raster_bands'),
            custom_properties=row.get('custom_properties') or {}
        )

    # =========================================================================
    # CONVERSION METHODS
    # =========================================================================

    def to_stac_collection(self, base_url: str) -> Dict[str, Any]:
        """
        Convert to STAC Collection response.

        Args:
            base_url: Base URL for link generation

        Returns:
            Complete STAC Collection dict
        """
        from core.models.stac import STAC_VERSION

        # Build extension list
        extensions = self.stac_extensions or [
            "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
            "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.1.0/schema.json"
        ]
        if self.eo_bands:
            extensions.append("https://stac-extensions.github.io/eo/v1.1.0/schema.json")

        collection: Dict[str, Any] = {
            "type": "Collection",
            "stac_version": STAC_VERSION,
            "stac_extensions": extensions,
            "id": self.stac_collection_id or self.id,
            "title": self.title or self.id.replace("_", " ").title(),
            "description": self.description or f"Raster dataset: {self.id}",
            "keywords": self.keywords or [],
            "license": self.license or "proprietary",
            "providers": [p.to_stac_dict() for p in self.providers],
            "links": [
                {
                    "rel": "self",
                    "href": f"{base_url}/api/stac/collections/{self.stac_collection_id or self.id}",
                    "type": "application/json"
                },
                {
                    "rel": "items",
                    "href": f"{base_url}/api/stac/collections/{self.stac_collection_id or self.id}/items",
                    "type": "application/geo+json"
                }
            ]
        }

        # Add extent if available
        if self.extent:
            extent_dict: Dict[str, Any] = {}
            if self.extent.spatial:
                extent_dict["spatial"] = {
                    "bbox": self.extent.spatial.bbox
                }
            if self.extent.temporal:
                extent_dict["temporal"] = {
                    "interval": self.extent.temporal.interval
                }
            collection["extent"] = extent_dict if extent_dict else {}
        else:
            collection["extent"] = {}

        # Add summaries for raster-specific properties
        summaries: Dict[str, Any] = {}
        if self.band_count:
            summaries["raster:bands_count"] = [self.band_count]
        if self.dtype:
            summaries["raster:dtype"] = [self.dtype]
        if self.crs:
            summaries["proj:epsg"] = [int(self.crs.replace("EPSG:", ""))] if self.crs.startswith("EPSG:") else None
        if self.eo_bands:
            summaries["eo:bands"] = self.eo_bands
        if summaries:
            collection["summaries"] = summaries

        return collection

    def to_stac_item(self, base_url: str, titiler_base_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Convert to STAC Item response.

        Creates a STAC Item representing this raster dataset with COG assets.

        Args:
            base_url: Base URL for link generation
            titiler_base_url: Optional TiTiler base URL for visualization links

        Returns:
            Complete STAC Item dict
        """
        from core.models.stac import STAC_VERSION
        import urllib.parse

        # Build bbox from extent
        bbox = None
        geometry = None
        if self.extent and self.extent.spatial and self.extent.spatial.bbox:
            bbox = self.extent.spatial.bbox[0]  # First bbox
            minx, miny, maxx, maxy = bbox
            geometry = {
                "type": "Polygon",
                "coordinates": [[
                    [minx, miny],
                    [maxx, miny],
                    [maxx, maxy],
                    [minx, maxy],
                    [minx, miny]
                ]]
            }

        # Build properties
        properties: Dict[str, Any] = {
            "title": self.title,
            "description": self.description
        }

        # Handle datetime per STAC spec
        if self.extent and self.extent.temporal and self.extent.temporal.interval:
            interval = self.extent.temporal.interval[0]
            if interval[0] and interval[1]:
                properties["datetime"] = None
                properties["start_datetime"] = interval[0]
                properties["end_datetime"] = interval[1]
            elif interval[0]:
                properties["datetime"] = interval[0]
            else:
                properties["datetime"] = (
                    self.created_at.isoformat() if self.created_at
                    else None
                )
        else:
            properties["datetime"] = (
                self.created_at.isoformat() if self.created_at
                else None
            )

        # Projection extension
        if self.crs:
            if self.crs.startswith("EPSG:"):
                properties["proj:epsg"] = int(self.crs.replace("EPSG:", ""))
            else:
                properties["proj:wkt2"] = self.crs
        if self.transform:
            properties["proj:transform"] = self.transform
        if self.resolution:
            properties["proj:resolution"] = self.resolution

        # Raster extension
        if self.band_count:
            properties["raster:bands_count"] = self.band_count
        if self.dtype:
            properties["raster:dtype"] = self.dtype

        # EO extension - add band info
        if self.eo_bands:
            properties["eo:bands"] = self.eo_bands

        # Processing extension
        if self.etl_job_id:
            properties["processing:lineage"] = f"ETL job {self.etl_job_id}"
        if self.source_file:
            properties["processing:source_file"] = self.source_file

        # Build extension list
        extensions = self.stac_extensions or [
            "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
            "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.1.0/schema.json"
        ]
        if self.eo_bands:
            if "https://stac-extensions.github.io/eo/v1.1.0/schema.json" not in extensions:
                extensions.append("https://stac-extensions.github.io/eo/v1.1.0/schema.json")

        collection_id = self.stac_collection_id or self.id
        item_id = self.stac_item_id or self.id

        item: Dict[str, Any] = {
            "type": "Feature",
            "stac_version": STAC_VERSION,
            "stac_extensions": extensions,
            "id": item_id,
            "geometry": geometry,
            "bbox": bbox,
            "properties": properties,
            "collection": collection_id,
            "links": [
                {
                    "rel": "self",
                    "href": f"{base_url}/api/stac/collections/{collection_id}/items/{item_id}",
                    "type": "application/geo+json"
                },
                {
                    "rel": "collection",
                    "href": f"{base_url}/api/stac/collections/{collection_id}",
                    "type": "application/json"
                }
            ],
            "assets": {}
        }

        # Build COG asset URL (HTTPS for external access)
        storage_account = self.container.split("-")[0] if "-" in self.container else self.container
        # Build HTTPS URL from container and blob_path
        cog_https_url = f"https://{storage_account}.blob.core.windows.net/{self.container}/{self.blob_path}"

        # Add COG data asset
        cog_asset: Dict[str, Any] = {
            "href": cog_https_url,
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "title": "Cloud-optimized GeoTIFF",
            "roles": ["data"]
        }

        # Add raster extension band info to asset
        if self.raster_bands:
            cog_asset["raster:bands"] = self.raster_bands
        elif self.band_names:
            # Build basic raster bands from band names
            cog_asset["raster:bands"] = [
                {"name": name, "data_type": self.dtype}
                for name in self.band_names
            ]

        # Add EO bands to asset
        if self.eo_bands:
            cog_asset["eo:bands"] = self.eo_bands

        item["assets"]["data"] = cog_asset

        # Add TiTiler visualization links if base URL provided
        if titiler_base_url:
            encoded_url = urllib.parse.quote(cog_https_url, safe='')

            # Thumbnail asset
            thumbnail_params = f"url={encoded_url}"
            if self.rescale_range:
                thumbnail_params += f"&rescale={self.rescale_range[0]},{self.rescale_range[1]}"
            if self.colormap:
                thumbnail_params += f"&colormap_name={self.colormap}"

            item["assets"]["thumbnail"] = {
                "href": f"{titiler_base_url}/cog/preview.png?{thumbnail_params}",
                "type": "image/png",
                "title": "Thumbnail",
                "roles": ["thumbnail"]
            }

            # TileJSON link
            item["links"].append({
                "rel": "tiles",
                "href": f"{titiler_base_url}/cog/tilejson.json?url={encoded_url}",
                "type": "application/json",
                "title": "TileJSON"
            })

        return item


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Provider models
    'ProviderRole',
    'Provider',

    # Extent models
    'SpatialExtent',
    'TemporalExtent',
    'Extent',

    # Metadata models
    'BaseMetadata',
    'VectorMetadata',
    'RasterMetadata',
]
