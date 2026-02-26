# ============================================================================
# GEO SCHEMA MODELS - SERVICE LAYER ONLY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Models for external-replicable geo schema tables
# PURPOSE: Pydantic models for geo.table_catalog, geo.feature_collection_styles
# LAST_REVIEWED: 22 JAN 2026
# EXPORTS: GeoTableCatalog, FeatureCollectionStyles
# DEPENDENCIES: pydantic
# ============================================================================
"""
Geo Schema Models - Service Layer Only.

These models define the tables that exist in the geo schema and are safe
to replicate to external databases via Azure Data Factory.

CRITICAL DESIGN PRINCIPLE:
    The geo schema is the ONLY schema replicated to external databases.
    External services (TiPG, etc.) query the external geo schema directly.
    Therefore, geo schema tables must NOT contain any internal app concerns:
    - No ETL job IDs (use app.vector_etl_tracking instead)
    - No internal processing state
    - No Azure infrastructure references

Architecture (21 JAN 2026):
    ┌─────────────────────────────────────────────────────────────────┐
    │                    INTERNAL DATABASE                            │
    ├─────────────────────────────────────────────────────────────────┤
    │  app schema                    │  geo schema                    │
    │  ├── jobs                      │  ├── table_catalog (metadata)  │
    │  ├── tasks                     │  ├── brazilian_cities (data)   │
    │  ├── vector_etl_tracking  ◄────┼──┤── admin_boundaries (data)   │
    │  └── (internal only)           │  └── (replicable)              │
    └────────────────────────────────┴────────────────────────────────┘
                                          │
                                     Azure Data Factory
                                          │
                                          ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    EXTERNAL DATABASE                            │
    ├─────────────────────────────────────────────────────────────────┤
    │  geo schema (exact replica)                                     │
    │  ├── table_catalog              ◄─── TiPG queries this         │
    │  ├── brazilian_cities                                          │
    │  └── admin_boundaries                                          │
    └─────────────────────────────────────────────────────────────────┘

Usage:
    from core.models.geo import GeoTableCatalog

    # Create from OGC-compliant fields only
    catalog_entry = GeoTableCatalog(
        table_name="brazilian_cities",
        title="Brazilian City Boundaries",
        description="Administrative boundaries for Brazilian cities",
        geometry_type="MultiPolygon",
        feature_count=5570,
        bbox_minx=-73.98, bbox_miny=-33.75,
        bbox_maxx=-28.85, bbox_maxy=5.27
    )

    # Generate DDL
    from core.schema import PydanticToSQL
    ddl = PydanticToSQL.generate_create_table(GeoTableCatalog)

Created: 21 JAN 2026
Epic: E7 Infrastructure as Code → F7.IaC Separation of Concerns
Story: S7.IaC.1 Create Geo Schema Pydantic Models
"""

from datetime import datetime
from typing import Optional, List, Dict, Any, ClassVar
from pydantic import BaseModel, Field, ConfigDict

from .unified_metadata import Provider, ProviderRole


class GeoTableCatalog(BaseModel):
    """
    Service layer metadata for PostGIS tables.

    This model maps to geo.table_catalog and contains ONLY end-user/service
    layer fields. ETL traceability fields are stored in app.vector_etl_tracking.

    Primary Key: table_name (natural key - the PostGIS table being cataloged)

    STAC/OGC Alignment:
        All fields map to STAC Collection/Item or OGC Features Collection
        standard fields. No internal ETL fields are included.

    DDL Annotations:
        The __sql_* class attributes guide DDL generation via PydanticToSQL:
        - __sql_table_name: Target table name
        - __sql_schema: Target schema name
        - __sql_primary_key: Primary key column(s)
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # DDL generation hints (ClassVar = not a model field)
    __sql_table_name: ClassVar[str] = "table_catalog"
    __sql_schema: ClassVar[str] = "geo"
    __sql_primary_key: ClassVar[List[str]] = ["table_name"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["schema_name"], "name": "idx_table_catalog_schema"},
        {"columns": ["geometry_type"], "name": "idx_table_catalog_geom_type"},
        {"columns": ["table_type"], "name": "idx_table_catalog_type"},
        {"columns": ["stac_collection_id"], "name": "idx_table_catalog_stac_coll", "partial_where": "stac_collection_id IS NOT NULL"},
        {"columns": ["created_at"], "name": "idx_table_catalog_created", "descending": True},
        {"columns": ["table_group"], "name": "idx_table_catalog_group", "partial_where": "table_group IS NOT NULL"},
    ]

    # ==========================================================================
    # IDENTITY (Primary Key)
    # ==========================================================================
    table_name: str = Field(
        ...,
        max_length=255,
        description="PostGIS table name (natural key, unique identifier)"
    )

    schema_name: str = Field(
        default="geo",
        max_length=63,
        description="PostgreSQL schema name"
    )

    # ==========================================================================
    # CORE METADATA (OGC/STAC Standard Fields)
    # ==========================================================================
    title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Human-readable title for display"
    )

    description: Optional[str] = Field(
        default=None,
        description="Full description of the dataset"
    )

    keywords: Optional[str] = Field(
        default=None,
        description="Comma-separated keywords for discovery"
    )

    license: Optional[str] = Field(
        default=None,
        max_length=100,
        description="SPDX license identifier (e.g., 'CC-BY-4.0', 'proprietary')"
    )

    attribution: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Attribution string for map display"
    )

    # ==========================================================================
    # SPATIAL EXTENT (OGC/STAC bbox)
    # ==========================================================================
    bbox_minx: Optional[float] = Field(
        default=None,
        description="Bounding box minimum X (longitude)"
    )

    bbox_miny: Optional[float] = Field(
        default=None,
        description="Bounding box minimum Y (latitude)"
    )

    bbox_maxx: Optional[float] = Field(
        default=None,
        description="Bounding box maximum X (longitude)"
    )

    bbox_maxy: Optional[float] = Field(
        default=None,
        description="Bounding box maximum Y (latitude)"
    )

    # ==========================================================================
    # TEMPORAL EXTENT (OGC/STAC temporal)
    # ==========================================================================
    temporal_start: Optional[datetime] = Field(
        default=None,
        description="Temporal extent start"
    )

    temporal_end: Optional[datetime] = Field(
        default=None,
        description="Temporal extent end"
    )

    temporal_property: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Column name for temporal queries"
    )

    # ==========================================================================
    # VECTOR-SPECIFIC FIELDS (Table Extension)
    # ==========================================================================
    geometry_type: Optional[str] = Field(
        default=None,
        max_length=50,
        description="PostGIS geometry type (Point, LineString, Polygon, etc.)"
    )

    primary_geometry: Optional[str] = Field(
        default="geom",
        max_length=100,
        description="Name of the primary geometry column"
    )

    srid: int = Field(
        default=4326,
        description="Spatial Reference ID"
    )

    feature_count: Optional[int] = Field(
        default=None,
        description="Number of features in the table"
    )

    # ==========================================================================
    # STAC INTEGRATION (Service Layer)
    # ==========================================================================
    stac_collection_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="STAC collection ID (if cataloged)"
    )

    stac_item_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="STAC item ID (if cataloged)"
    )

    stac_extensions: Optional[List[str]] = Field(
        default=None,
        description="STAC extension URIs (stored as JSONB)"
    )

    # ==========================================================================
    # PROVIDERS (STAC Standard - stored as JSONB)
    # ==========================================================================
    providers: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="STAC providers array (stored as JSONB)"
    )

    # ==========================================================================
    # SCIENTIFIC METADATA (Optional)
    # ==========================================================================
    sci_doi: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Scientific DOI if applicable"
    )

    sci_citation: Optional[str] = Field(
        default=None,
        description="Citation text"
    )

    # ==========================================================================
    # TABLE CLASSIFICATION
    # ==========================================================================
    table_type: str = Field(
        default="user",
        max_length=50,
        description="Table type: user, curated, system"
    )

    # ==========================================================================
    # COLUMN SCHEMA (Table Extension - stored as JSONB)
    # ==========================================================================
    column_definitions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Column metadata for STAC Table Extension"
    )

    # ==========================================================================
    # MULTI-TABLE GROUPING (26 FEB 2026)
    # ==========================================================================
    table_group: Optional[str] = Field(
        default=None,
        max_length=63,
        description="Groups related tables (geometry splits share same group). NULL for single-table uploads."
    )

    # ==========================================================================
    # CUSTOM PROPERTIES (Extension point - stored as JSONB)
    # ==========================================================================
    custom_properties: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional custom properties"
    )

    # ==========================================================================
    # TIMESTAMPS
    # ==========================================================================
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the catalog entry was created"
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        description="When metadata was last updated"
    )

    # ==========================================================================
    # FACTORY METHODS
    # ==========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "GeoTableCatalog":
        """
        Create GeoTableCatalog from database row.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            GeoTableCatalog instance
        """
        return cls(
            table_name=row.get('table_name'),
            schema_name=row.get('schema_name', 'geo'),
            title=row.get('title'),
            description=row.get('description'),
            keywords=row.get('keywords'),
            license=row.get('license'),
            attribution=row.get('attribution'),
            bbox_minx=row.get('bbox_minx'),
            bbox_miny=row.get('bbox_miny'),
            bbox_maxx=row.get('bbox_maxx'),
            bbox_maxy=row.get('bbox_maxy'),
            temporal_start=row.get('temporal_start'),
            temporal_end=row.get('temporal_end'),
            temporal_property=row.get('temporal_property'),
            geometry_type=row.get('geometry_type'),
            primary_geometry=row.get('primary_geometry', 'geom'),
            srid=row.get('srid', 4326),
            feature_count=row.get('feature_count'),
            stac_collection_id=row.get('stac_collection_id'),
            stac_item_id=row.get('stac_item_id'),
            stac_extensions=row.get('stac_extensions'),
            providers=row.get('providers'),
            sci_doi=row.get('sci_doi'),
            sci_citation=row.get('sci_citation'),
            table_type=row.get('table_type', 'user'),
            column_definitions=row.get('column_definitions'),
            custom_properties=row.get('custom_properties'),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

    @classmethod
    def from_vector_metadata(cls, metadata: "VectorMetadata") -> "GeoTableCatalog":
        """
        Create GeoTableCatalog from VectorMetadata (service fields only).

        This is the primary method for splitting unified metadata into
        service layer (GeoTableCatalog) and ETL layer (VectorEtlTracking).

        Args:
            metadata: Full VectorMetadata instance

        Returns:
            GeoTableCatalog with service layer fields only
        """
        # Import here to avoid circular dependency
        from .unified_metadata import VectorMetadata

        # Convert extent to flat bbox
        bbox_minx = bbox_miny = bbox_maxx = bbox_maxy = None
        if metadata.extent and metadata.extent.spatial:
            bbox = metadata.extent.spatial.bbox[0] if metadata.extent.spatial.bbox else None
            if bbox and len(bbox) >= 4:
                bbox_minx, bbox_miny, bbox_maxx, bbox_maxy = bbox[:4]

        # Convert temporal extent
        temporal_start = temporal_end = None
        if metadata.extent and metadata.extent.temporal:
            interval = metadata.extent.temporal.interval[0] if metadata.extent.temporal.interval else None
            if interval and len(interval) >= 2:
                temporal_start, temporal_end = interval[:2]

        # Convert providers to serializable dicts
        providers_data = None
        if metadata.providers:
            providers_data = [p.model_dump() for p in metadata.providers]

        # Convert keywords list to comma-separated string
        keywords_str = None
        if metadata.keywords:
            keywords_str = ", ".join(metadata.keywords)

        return cls(
            table_name=metadata.id,
            schema_name=metadata.schema_name,
            title=metadata.title,
            description=metadata.description,
            keywords=keywords_str,
            license=metadata.license,
            attribution=metadata.attribution or metadata.get_attribution(),
            bbox_minx=bbox_minx,
            bbox_miny=bbox_miny,
            bbox_maxx=bbox_maxx,
            bbox_maxy=bbox_maxy,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            temporal_property=metadata.temporal_property,
            geometry_type=metadata.geometry_type,
            primary_geometry=metadata.primary_geometry_column,
            srid=metadata.srid,
            feature_count=metadata.feature_count,
            stac_collection_id=metadata.stac_collection_id,
            stac_item_id=metadata.stac_item_id,
            stac_extensions=metadata.stac_extensions if metadata.stac_extensions else None,
            providers=providers_data,
            sci_doi=metadata.sci_doi,
            sci_citation=metadata.sci_citation,
            table_type=metadata.table_type,
            column_definitions=metadata.column_definitions,
            custom_properties=metadata.custom_properties if metadata.custom_properties else None,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database insertion.

        Returns:
            Dict suitable for INSERT/UPDATE operations
        """
        return self.model_dump(exclude_none=False, by_alias=True)

    def get_bbox_list(self) -> Optional[List[float]]:
        """
        Get bounding box as [minx, miny, maxx, maxy] list.

        Returns:
            Bbox list or None if not fully defined
        """
        if all(v is not None for v in [self.bbox_minx, self.bbox_miny,
                                        self.bbox_maxx, self.bbox_maxy]):
            return [self.bbox_minx, self.bbox_miny, self.bbox_maxx, self.bbox_maxy]
        return None

    def get_qualified_name(self) -> str:
        """
        Get schema-qualified table name.

        Returns:
            String like "geo.brazilian_cities"
        """
        return f"{self.schema_name}.{self.table_name}"


# ============================================================================
# FEATURE COLLECTION STYLES (OGC API Styles)
# ============================================================================

class FeatureCollectionStyles(BaseModel):
    """
    OGC API Styles storage model.

    Stores CartoSym-JSON styles for OGC Features collections. Each collection
    can have multiple styles, with one designated as default.

    Maps to: geo.feature_collection_styles

    OGC Conformance:
        - /req/core/styles-list
        - /req/core/style

    CartoSym-JSON (stored in style_spec):
        {
            "name": "protected-areas",
            "title": "Protected Areas by Category",
            "stylingRules": [
                {
                    "name": "category-ia",
                    "selector": {"op": "=", "args": [{"property": "iucn_cat"}, "Ia"]},
                    "symbolizer": {
                        "type": "Polygon",
                        "fill": {"color": "#1a9850", "opacity": 0.7},
                        "stroke": {"color": "#006837", "width": 1.5}
                    }
                }
            ]
        }

    Usage:
        from core.models.geo import FeatureCollectionStyles

        style = FeatureCollectionStyles(
            collection_id="protected_areas",
            style_id="by-category",
            title="Protected Areas by Category",
            style_spec=cartosym_json,
            is_default=True
        )

    Created: 22 JAN 2026
    Epic: E7 Infrastructure as Code → OGC Styles DDL Migration
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # DDL generation hints (ClassVar = not a model field)
    __sql_table_name: ClassVar[str] = "feature_collection_styles"
    __sql_schema: ClassVar[str] = "geo"
    __sql_primary_key: ClassVar[List[str]] = ["id"]
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["collection_id", "style_id"], "name": "uq_styles_collection_style"}
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["collection_id"], "name": "idx_styles_collection"},
        # Partial unique index: only one default per collection
        {"columns": ["collection_id"], "name": "idx_styles_default", "partial_where": "is_default = true", "unique": True},
    ]

    # ==========================================================================
    # IDENTITY
    # ==========================================================================
    id: Optional[int] = Field(
        default=None,
        description="Auto-generated primary key (SERIAL)"
    )

    collection_id: str = Field(
        ...,
        max_length=255,
        description="OGC Features collection identifier (table name)"
    )

    style_id: str = Field(
        ...,
        max_length=100,
        description="URL-safe style identifier (e.g., 'default', 'by-category')"
    )

    # ==========================================================================
    # METADATA
    # ==========================================================================
    title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Human-readable style title"
    )

    description: Optional[str] = Field(
        default=None,
        description="Style description"
    )

    # ==========================================================================
    # STYLE SPECIFICATION (CartoSym-JSON)
    # ==========================================================================
    style_spec: Dict[str, Any] = Field(
        ...,
        description="CartoSym-JSON style document (stored as JSONB)"
    )

    # ==========================================================================
    # FLAGS
    # ==========================================================================
    is_default: bool = Field(
        default=False,
        description="Whether this is the default style for the collection"
    )

    # ==========================================================================
    # TIMESTAMPS
    # ==========================================================================
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the style was created"
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        description="When the style was last updated"
    )

    # ==========================================================================
    # FACTORY METHODS
    # ==========================================================================

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "FeatureCollectionStyles":
        """
        Create FeatureCollectionStyles from database row.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            FeatureCollectionStyles instance
        """
        return cls(
            id=row.get('id'),
            collection_id=row.get('collection_id'),
            style_id=row.get('style_id'),
            title=row.get('title'),
            description=row.get('description'),
            style_spec=row.get('style_spec', {}),
            is_default=row.get('is_default', False),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

    @classmethod
    def create_default_for_geometry(
        cls,
        collection_id: str,
        geometry_type: str,
        fill_color: str = "#3388ff",
        stroke_color: str = "#2266cc"
    ) -> "FeatureCollectionStyles":
        """
        Create a default style for a collection based on geometry type.

        Args:
            collection_id: Collection identifier (table name)
            geometry_type: PostGIS geometry type (Polygon, LineString, Point, etc.)
            fill_color: Fill color (hex)
            stroke_color: Stroke color (hex)

        Returns:
            FeatureCollectionStyles instance with default CartoSym-JSON
        """
        # Normalize geometry type
        geom_type_map = {
            "POLYGON": "Polygon",
            "MULTIPOLYGON": "Polygon",
            "LINESTRING": "Line",
            "MULTILINESTRING": "Line",
            "POINT": "Point",
            "MULTIPOINT": "Point"
        }
        sym_type = geom_type_map.get(geometry_type.upper(), "Polygon")

        # Build CartoSym-JSON based on geometry type
        if sym_type == "Polygon":
            style_spec = {
                "name": f"{collection_id}-default",
                "title": f"Default style for {collection_id}",
                "stylingRules": [{
                    "name": "default",
                    "symbolizer": {
                        "type": "Polygon",
                        "fill": {"color": fill_color, "opacity": 0.6},
                        "stroke": {"color": stroke_color, "width": 1.5}
                    }
                }]
            }
        elif sym_type == "Line":
            style_spec = {
                "name": f"{collection_id}-default",
                "title": f"Default style for {collection_id}",
                "stylingRules": [{
                    "name": "default",
                    "symbolizer": {
                        "type": "Line",
                        "stroke": {"color": stroke_color, "width": 2}
                    }
                }]
            }
        else:  # Point
            style_spec = {
                "name": f"{collection_id}-default",
                "title": f"Default style for {collection_id}",
                "stylingRules": [{
                    "name": "default",
                    "symbolizer": {
                        "type": "Point",
                        "marker": {
                            "size": 8,
                            "fill": {"color": fill_color},
                            "stroke": {"color": stroke_color, "width": 1}
                        }
                    }
                }]
            }

        return cls(
            collection_id=collection_id,
            style_id="default",
            title=style_spec["title"],
            description=f"Auto-generated default style for {collection_id}",
            style_spec=style_spec,
            is_default=True
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database insertion.

        Returns:
            Dict suitable for INSERT/UPDATE operations
        """
        return self.model_dump(exclude_none=False, by_alias=True)
