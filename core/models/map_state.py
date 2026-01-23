# ============================================================================
# CLAUDE CONTEXT - MAP STATE CONFIGURATION MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Saveable web map configuration storage
# PURPOSE: Pydantic models for app.map_states and app.map_state_snapshots tables
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# EXPORTS: MapLayer, MapState, MapStateSnapshot
# DEPENDENCIES: pydantic, hashlib
# ============================================================================
"""
Map State Configuration Models.

Server-side storage for web map configurations enabling users to save and
restore map states including layers, view position, and symbology references.

Architecture:
    PostgreSQL (Source of Truth)
    ├── app.map_states
    │   • map_id (SHA256(name)[:32])
    │   • layers (JSONB array with symbology refs)
    │   • view state (center, zoom, bounds)
    │   • version tracking
    │
    └── app.map_state_snapshots
        • snapshot_id (SHA256(map_id + version)[:64])
        • full state JSONB for restore
        • auto-created on updates

Layer Symbology References:
    - Rasters: render_id → app.raster_render_configs
    - Vectors: style_id → geo.feature_collection_styles

Source Types:
    - stac_item: Internal COG (references cog_id)
    - external_service: External service (references service_id)
    - vector_collection: PostGIS table (references collection_id)
    - xyz_tiles: XYZ tile service (URL in options)
    - wms: WMS service (URL + layers in options)

Usage:
    from core.models.map_state import MapState, MapLayer

    layer = MapLayer(
        layer_id="flood-layer",
        source_type="stac_item",
        source_id="fathom-flood-2020",
        name="Flood Depth",
        render_id="flood-depth"
    )

    map_state = MapState(
        name="Houston Flood Analysis",
        center_lon=-95.3698,
        center_lat=29.7604,
        zoom_level=12,
        layers=[layer.model_dump()]
    )

Created: 23 JAN 2026
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, ClassVar, Literal
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_validator
import hashlib


# ============================================================================
# ENUMS
# ============================================================================

class MapType(str, Enum):
    """Supported web map container types."""
    MAPLIBRE = "maplibre"
    LEAFLET = "leaflet"
    OPENLAYERS = "openlayers"


class LayerSourceType(str, Enum):
    """Supported layer source types."""
    STAC_ITEM = "stac_item"              # Internal COG (cog_id)
    EXTERNAL_SERVICE = "external_service"  # External geospatial service
    VECTOR_COLLECTION = "vector_collection"  # PostGIS feature collection
    XYZ_TILES = "xyz_tiles"              # XYZ tile service (OSM, Mapbox, etc.)
    WMS = "wms"                          # OGC WMS service


# ============================================================================
# LAYER MODEL (For validation)
# ============================================================================

class MapLayer(BaseModel):
    """
    Individual layer configuration within a map.

    Layers reference internal or external data sources and include
    symbology references to render configs (raster) or styles (vector).
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # Identity
    layer_id: str = Field(
        ...,
        max_length=100,
        description="Unique layer identifier within the map"
    )
    source_type: LayerSourceType = Field(
        ...,
        description="Type of data source"
    )
    source_id: str = Field(
        ...,
        max_length=255,
        description="Reference ID (cog_id, service_id, collection_id, or custom)"
    )

    # Display
    name: str = Field(
        ...,
        max_length=255,
        description="Human-readable layer name"
    )
    visible: bool = Field(
        default=True,
        description="Whether layer is visible"
    )
    opacity: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Layer opacity (0.0-1.0)"
    )
    z_index: int = Field(
        default=1,
        ge=0,
        description="Layer stacking order (0 = bottom)"
    )
    is_basemap: bool = Field(
        default=False,
        description="Whether this is the basemap layer"
    )

    # Symbology references
    render_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Raster render config ID (for stac_item sources)"
    )
    style_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Vector style ID (for vector_collection sources)"
    )

    # Layer-specific options
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Layer-specific options (url, attribution, minZoom, maxZoom, etc.)"
    )

    @classmethod
    def create_osm_basemap(cls) -> "MapLayer":
        """Create default OpenStreetMap basemap layer."""
        return cls(
            layer_id="basemap",
            source_type=LayerSourceType.XYZ_TILES,
            source_id="osm-standard",
            name="OpenStreetMap",
            visible=True,
            opacity=1.0,
            z_index=0,
            is_basemap=True,
            options={
                "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "© OpenStreetMap contributors",
                "maxZoom": 19
            }
        )


# ============================================================================
# MAP STATE MODEL
# ============================================================================

class MapState(BaseModel):
    """
    Web map configuration state.

    Maps to: app.map_states

    Stores complete map configuration including:
    - View state (center, zoom, bounds)
    - Layers with symbology references
    - Custom attributes for future extensions

    Following the same IaC pattern as:
    - RasterRenderConfig (app.raster_render_configs)
    - FeatureCollectionStyles (geo.feature_collection_styles)
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "map_states"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["map_id"]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["name"], "name": "idx_map_states_name"},
        {"columns": ["map_type"], "name": "idx_map_states_type"},
        {"columns": ["tags"], "name": "idx_map_states_tags", "type": "gin"},
        {"columns": ["created_at"], "name": "idx_map_states_created", "descending": True},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    map_id: str = Field(
        ...,
        max_length=32,
        description="SHA256(name)[:32] - unique map identifier"
    )
    name: str = Field(
        ...,
        max_length=255,
        description="Human-readable map name"
    )
    description: Optional[str] = Field(
        default=None,
        description="Map description"
    )

    # =========================================================================
    # MAP CONFIGURATION
    # =========================================================================
    map_type: MapType = Field(
        default=MapType.MAPLIBRE,
        description="Map container type"
    )
    center_lon: Optional[float] = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Map center longitude"
    )
    center_lat: Optional[float] = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Map center latitude"
    )
    zoom_level: Optional[int] = Field(
        default=None,
        ge=0,
        le=24,
        description="Map zoom level"
    )
    bounds: Optional[List[float]] = Field(
        default=None,
        description="Map bounds [minx, miny, maxx, maxy]"
    )

    # =========================================================================
    # LAYERS
    # =========================================================================
    layers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Ordered array of layer configurations"
    )

    # =========================================================================
    # EXTENSION POINT
    # =========================================================================
    custom_attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Custom attributes for future extensions"
    )

    # =========================================================================
    # METADATA
    # =========================================================================
    tags: List[str] = Field(
        default_factory=list,
        description="Tags for categorization"
    )
    thumbnail_url: Optional[str] = Field(
        default=None,
        description="Optional preview image URL"
    )

    # =========================================================================
    # VERSIONING
    # =========================================================================
    version: int = Field(
        default=1,
        ge=1,
        description="Map state version (increments on update)"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the map was created"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="When the map was last updated"
    )

    # =========================================================================
    # VALIDATORS
    # =========================================================================
    @field_validator('bounds')
    @classmethod
    def validate_bounds(cls, v):
        """Validate bounds format."""
        if v is not None:
            if len(v) != 4:
                raise ValueError("bounds must be [minx, miny, maxx, maxy]")
            if v[0] > v[2] or v[1] > v[3]:
                raise ValueError("bounds min values must be less than max values")
        return v

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================
    @staticmethod
    def generate_map_id(name: str) -> str:
        """
        Generate deterministic map_id from name.

        Uses SHA256 hash truncated to 32 chars.

        Args:
            name: Map name

        Returns:
            32-character hex string
        """
        return hashlib.sha256(name.encode()).hexdigest()[:32]

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "MapState":
        """
        Create MapState from database row.

        Args:
            row: Database row as dict (from psycopg dict_row)

        Returns:
            MapState instance
        """
        return cls(
            map_id=row.get('map_id'),
            name=row.get('name'),
            description=row.get('description'),
            map_type=row.get('map_type', 'maplibre'),
            center_lon=row.get('center_lon'),
            center_lat=row.get('center_lat'),
            zoom_level=row.get('zoom_level'),
            bounds=row.get('bounds'),
            layers=row.get('layers') or [],
            custom_attributes=row.get('custom_attributes') or {},
            tags=row.get('tags') or [],
            thumbnail_url=row.get('thumbnail_url'),
            version=row.get('version', 1),
            created_at=row.get('created_at'),
            updated_at=row.get('updated_at')
        )

    @classmethod
    def create_new(
        cls,
        name: str,
        description: Optional[str] = None,
        map_type: MapType = MapType.MAPLIBRE,
        center_lon: Optional[float] = None,
        center_lat: Optional[float] = None,
        zoom_level: Optional[int] = None,
        layers: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[str]] = None
    ) -> "MapState":
        """
        Create a new MapState with auto-generated ID and default basemap.

        Args:
            name: Map name
            description: Map description
            map_type: Map container type
            center_lon: Center longitude
            center_lat: Center latitude
            zoom_level: Zoom level
            layers: Layer configurations (OSM basemap added if empty)
            tags: Categorization tags

        Returns:
            New MapState instance
        """
        map_id = cls.generate_map_id(name)

        # Add default basemap if no layers provided
        if not layers:
            layers = [MapLayer.create_osm_basemap().model_dump()]

        return cls(
            map_id=map_id,
            name=name,
            description=description,
            map_type=map_type,
            center_lon=center_lon,
            center_lat=center_lat,
            zoom_level=zoom_level,
            layers=layers,
            tags=tags or [],
            version=1
        )

    # =========================================================================
    # CONVERSION METHODS
    # =========================================================================
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for API responses.

        Returns:
            Dict representation of the map state
        """
        return {
            "map_id": self.map_id,
            "name": self.name,
            "description": self.description,
            "map_type": self.map_type.value if isinstance(self.map_type, MapType) else self.map_type,
            "center_lon": self.center_lon,
            "center_lat": self.center_lat,
            "zoom_level": self.zoom_level,
            "bounds": self.bounds,
            "layers": self.layers,
            "custom_attributes": self.custom_attributes,
            "tags": self.tags,
            "thumbnail_url": self.thumbnail_url,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

    def to_snapshot_state(self) -> Dict[str, Any]:
        """
        Convert to JSONB for snapshot storage.

        Excludes timestamps (snapshot has its own created_at).

        Returns:
            Dict for snapshot state column
        """
        return {
            "name": self.name,
            "description": self.description,
            "map_type": self.map_type.value if isinstance(self.map_type, MapType) else self.map_type,
            "center_lon": self.center_lon,
            "center_lat": self.center_lat,
            "zoom_level": self.zoom_level,
            "bounds": self.bounds,
            "layers": self.layers,
            "custom_attributes": self.custom_attributes,
            "tags": self.tags,
            "thumbnail_url": self.thumbnail_url,
            "version": self.version
        }


# ============================================================================
# MAP STATE SNAPSHOT MODEL
# ============================================================================

class MapStateSnapshot(BaseModel):
    """
    Historical snapshot of a map state.

    Maps to: app.map_state_snapshots

    Stores complete map state at a point in time for restore operations.
    Automatically created when map state is updated.
    """
    model_config = ConfigDict(
        use_enum_values=True,
        extra='ignore',
        str_strip_whitespace=True
    )

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "map_state_snapshots"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["snapshot_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "map_id": "app.map_states(map_id)"
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["map_id", "version"], "name": "uq_snapshot_map_version"}
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["map_id"], "name": "idx_snapshot_map_id"},
        {"columns": ["created_at"], "name": "idx_snapshot_created", "descending": True},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    snapshot_id: str = Field(
        ...,
        max_length=64,
        description="SHA256(map_id + version)[:64] - unique snapshot identifier"
    )
    map_id: str = Field(
        ...,
        max_length=32,
        description="Parent map identifier (FK)"
    )
    version: int = Field(
        ...,
        ge=1,
        description="Version number at time of snapshot"
    )

    # =========================================================================
    # STATE
    # =========================================================================
    state: Dict[str, Any] = Field(
        ...,
        description="Complete map state as JSONB"
    )

    # =========================================================================
    # METADATA
    # =========================================================================
    snapshot_reason: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Reason for snapshot (auto_save, manual, before_delete)"
    )

    # =========================================================================
    # TIMESTAMP
    # =========================================================================
    created_at: Optional[datetime] = Field(
        default=None,
        description="When the snapshot was created"
    )

    # =========================================================================
    # FACTORY METHODS
    # =========================================================================
    @staticmethod
    def generate_snapshot_id(map_id: str, version: int) -> str:
        """
        Generate deterministic snapshot_id from map_id and version.

        Args:
            map_id: Map identifier
            version: Version number

        Returns:
            64-character hex string
        """
        return hashlib.sha256(f"{map_id}:{version}".encode()).hexdigest()[:64]

    @classmethod
    def from_map_state(
        cls,
        map_state: MapState,
        reason: str = "auto_save"
    ) -> "MapStateSnapshot":
        """
        Create snapshot from current map state.

        Args:
            map_state: MapState to snapshot
            reason: Reason for snapshot

        Returns:
            MapStateSnapshot instance
        """
        return cls(
            snapshot_id=cls.generate_snapshot_id(map_state.map_id, map_state.version),
            map_id=map_state.map_id,
            version=map_state.version,
            state=map_state.to_snapshot_state(),
            snapshot_reason=reason
        )

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "MapStateSnapshot":
        """
        Create MapStateSnapshot from database row.

        Args:
            row: Database row as dict

        Returns:
            MapStateSnapshot instance
        """
        return cls(
            snapshot_id=row.get('snapshot_id'),
            map_id=row.get('map_id'),
            version=row.get('version'),
            state=row.get('state') or {},
            snapshot_reason=row.get('snapshot_reason'),
            created_at=row.get('created_at')
        )

    # =========================================================================
    # CONVERSION METHODS
    # =========================================================================
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for API responses.

        Returns:
            Dict representation of the snapshot
        """
        return {
            "snapshot_id": self.snapshot_id,
            "map_id": self.map_id,
            "version": self.version,
            "state": self.state,
            "snapshot_reason": self.snapshot_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'MapType',
    'LayerSourceType',
    'MapLayer',
    'MapState',
    'MapStateSnapshot',
]
