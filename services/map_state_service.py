# ============================================================================
# MAP STATE SERVICE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Business logic - Map state configuration orchestration
# PURPOSE: Coordinate map state lookup, validation, and response formatting
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# EXPORTS: MapStateService, get_map_state_service
# DEPENDENCIES: infrastructure.map_state_repository
# ============================================================================
"""
Map State Service Layer.

Business logic for web map configurations:
- List map states with filtering
- Get map state (with validation)
- Create/update map states
- Snapshot management
- Response formatting with HATEOAS links

Usage:
    service = get_map_state_service()

    # List maps
    maps_list = service.list_maps(base_url)

    # Get map with links
    map_data = service.get_map("abc123", base_url)

    # Create map
    service.create_map({
        "name": "Houston Flood Analysis",
        "layers": [...]
    })

Created: 23 JAN 2026
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from core.models.map_state import MapState, MapStateSnapshot, MapLayer, MapType
from infrastructure.map_state_repository import (
    MapStateRepository,
    get_map_state_repository
)

logger = logging.getLogger(__name__)


# Module-level singleton
_service_instance: Optional["MapStateService"] = None


def get_map_state_service() -> "MapStateService":
    """
    Get singleton MapStateService instance.

    Returns:
        MapStateService singleton
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MapStateService()
    return _service_instance


class MapStateService:
    """
    Map state configuration business logic.

    Orchestrates map state retrieval, validation, and API response formatting.
    Coordinates between repository (data access) and HTTP handlers.
    """

    def __init__(self, repository: Optional[MapStateRepository] = None):
        """
        Initialize service with optional repository.

        Args:
            repository: Map state repository (uses singleton if not provided)
        """
        self.repository = repository or get_map_state_repository()
        logger.debug("MapStateService initialized")

    # =========================================================================
    # LIST OPERATIONS
    # =========================================================================

    def list_maps(
        self,
        base_url: str,
        map_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        List map states with HATEOAS links.

        Args:
            base_url: Base URL for link generation
            map_type: Filter by map type
            tags: Filter by tags
            limit: Maximum results
            offset: Pagination offset

        Returns:
            API response dict with maps and links
        """
        maps = self.repository.list_maps(
            map_type=map_type,
            tags=tags,
            limit=limit,
            offset=offset
        )

        total = self.repository.count_maps(map_type=map_type)

        maps_url = f"{base_url}/api/maps"

        response = {
            "maps": [self._format_map_summary(m, base_url) for m in maps],
            "count": len(maps),
            "total": total,
            "limit": limit,
            "offset": offset,
            "links": [
                {
                    "rel": "self",
                    "href": maps_url,
                    "type": "application/json"
                }
            ]
        }

        # Add pagination links
        if offset > 0:
            response["links"].append({
                "rel": "prev",
                "href": f"{maps_url}?limit={limit}&offset={max(0, offset - limit)}",
                "type": "application/json"
            })
        if offset + limit < total:
            response["links"].append({
                "rel": "next",
                "href": f"{maps_url}?limit={limit}&offset={offset + limit}",
                "type": "application/json"
            })

        return response

    def _format_map_summary(self, map_state: MapState, base_url: str) -> Dict[str, Any]:
        """Format map for list response (summary only)."""
        return {
            "map_id": map_state.map_id,
            "name": map_state.name,
            "description": map_state.description,
            "map_type": map_state.map_type.value if hasattr(map_state.map_type, 'value') else map_state.map_type,
            "layer_count": len(map_state.layers),
            "tags": map_state.tags,
            "version": map_state.version,
            "thumbnail_url": map_state.thumbnail_url,
            "created_at": map_state.created_at.isoformat() if map_state.created_at else None,
            "updated_at": map_state.updated_at.isoformat() if map_state.updated_at else None,
            "links": [
                {
                    "rel": "self",
                    "href": f"{base_url}/api/maps/{map_state.map_id}",
                    "type": "application/json"
                }
            ]
        }

    # =========================================================================
    # GET OPERATIONS
    # =========================================================================

    def get_map(
        self,
        map_id: str,
        base_url: str,
        include_snapshots: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific map state with links.

        Args:
            map_id: Map identifier
            base_url: Base URL for link generation
            include_snapshots: Whether to include snapshot list

        Returns:
            Map state dict with links, or None if not found
        """
        map_state = self.repository.get_map(map_id)
        if not map_state:
            return None

        response = map_state.to_dict()
        response["links"] = [
            {
                "rel": "self",
                "href": f"{base_url}/api/maps/{map_id}",
                "type": "application/json"
            },
            {
                "rel": "snapshots",
                "href": f"{base_url}/api/maps/{map_id}/snapshots",
                "type": "application/json"
            },
            {
                "rel": "collection",
                "href": f"{base_url}/api/maps",
                "type": "application/json"
            }
        ]

        if include_snapshots:
            snapshots = self.repository.list_snapshots(map_id, limit=10)
            response["recent_snapshots"] = [
                {
                    "version": s.version,
                    "snapshot_reason": s.snapshot_reason,
                    "created_at": s.created_at.isoformat() if s.created_at else None
                }
                for s in snapshots
            ]

        return response

    def map_exists(self, map_id: str) -> bool:
        """Check if a map exists."""
        return self.repository.map_exists(map_id)

    # =========================================================================
    # CREATE/UPDATE OPERATIONS
    # =========================================================================

    def create_map(
        self,
        name: str,
        description: Optional[str] = None,
        map_type: str = "maplibre",
        center_lon: Optional[float] = None,
        center_lat: Optional[float] = None,
        zoom_level: Optional[int] = None,
        bounds: Optional[List[float]] = None,
        layers: Optional[List[Dict[str, Any]]] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        thumbnail_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new map state.

        Args:
            name: Map name
            description: Map description
            map_type: Map container type
            center_lon: Center longitude
            center_lat: Center latitude
            zoom_level: Zoom level
            bounds: Map bounds
            layers: Layer configurations (OSM basemap added if empty)
            custom_attributes: Custom attributes
            tags: Categorization tags
            thumbnail_url: Preview image URL

        Returns:
            Created map state dict

        Raises:
            ValueError: If map with same name already exists
        """
        # Generate map ID from name
        map_id = MapState.generate_map_id(name)

        # Check if already exists
        if self.repository.map_exists(map_id):
            raise ValueError(f"Map with name '{name}' already exists")

        # Validate layers through Pydantic model (trust boundary)
        if layers:
            validated_layers = self._validate_layers(layers)
        else:
            # Add default OSM basemap
            validated_layers = [MapLayer.create_osm_basemap().model_dump()]

        # Create via repository with validated data
        self.repository.create_map(
            map_id=map_id,
            name=name,
            description=description,
            map_type=map_type,
            center_lon=center_lon,
            center_lat=center_lat,
            zoom_level=zoom_level,
            bounds=bounds,
            layers=validated_layers,
            custom_attributes=custom_attributes,
            tags=tags,
            thumbnail_url=thumbnail_url
        )

        # Return the created map
        return self.repository.get_map(map_id).to_dict()

    def update_map(
        self,
        map_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        map_type: Optional[str] = None,
        center_lon: Optional[float] = None,
        center_lat: Optional[float] = None,
        zoom_level: Optional[int] = None,
        bounds: Optional[List[float]] = None,
        layers: Optional[List[Dict[str, Any]]] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        thumbnail_url: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Update a map state (creates snapshot automatically).

        Args:
            map_id: Map identifier
            name: New name (optional)
            description: New description (optional)
            map_type: New map type (optional)
            center_lon: New center longitude (optional)
            center_lat: New center latitude (optional)
            zoom_level: New zoom level (optional)
            bounds: New bounds (optional)
            layers: New layers (optional)
            custom_attributes: New custom attributes (optional)
            tags: New tags (optional)
            thumbnail_url: New thumbnail URL (optional)

        Returns:
            Updated map state dict, or None if not found
        """
        # Validate layers through Pydantic model (trust boundary)
        validated_layers = None
        if layers:
            validated_layers = self._validate_layers(layers)

        # Update via repository (auto-creates snapshot)
        updated = self.repository.update_map(
            map_id=map_id,
            name=name,
            description=description,
            map_type=map_type,
            center_lon=center_lon,
            center_lat=center_lat,
            zoom_level=zoom_level,
            bounds=bounds,
            layers=validated_layers,
            custom_attributes=custom_attributes,
            tags=tags,
            thumbnail_url=thumbnail_url
        )

        if not updated:
            return None

        # Return updated map
        return self.repository.get_map(map_id).to_dict()

    # =========================================================================
    # DELETE OPERATIONS
    # =========================================================================

    def delete_map(self, map_id: str) -> bool:
        """
        Delete a map state.

        Creates final snapshot before deletion.

        Args:
            map_id: Map identifier

        Returns:
            True if deleted, False if not found
        """
        return self.repository.delete_map(map_id)

    # =========================================================================
    # SNAPSHOT OPERATIONS
    # =========================================================================

    def list_snapshots(
        self,
        map_id: str,
        base_url: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        List snapshots for a map.

        Args:
            map_id: Map identifier
            base_url: Base URL for link generation
            limit: Maximum snapshots

        Returns:
            API response with snapshots and links
        """
        snapshots = self.repository.list_snapshots(map_id, limit)

        return {
            "map_id": map_id,
            "snapshots": [
                {
                    "version": s.version,
                    "snapshot_reason": s.snapshot_reason,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "links": [
                        {
                            "rel": "self",
                            "href": f"{base_url}/api/maps/{map_id}/snapshots/{s.version}",
                            "type": "application/json"
                        },
                        {
                            "rel": "restore",
                            "href": f"{base_url}/api/maps/{map_id}/restore/{s.version}",
                            "type": "application/json",
                            "method": "POST"
                        }
                    ]
                }
                for s in snapshots
            ],
            "count": len(snapshots),
            "links": [
                {
                    "rel": "self",
                    "href": f"{base_url}/api/maps/{map_id}/snapshots",
                    "type": "application/json"
                },
                {
                    "rel": "map",
                    "href": f"{base_url}/api/maps/{map_id}",
                    "type": "application/json"
                }
            ]
        }

    def get_snapshot(
        self,
        map_id: str,
        version: int,
        base_url: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a specific snapshot.

        Args:
            map_id: Map identifier
            version: Version number
            base_url: Base URL for link generation

        Returns:
            Snapshot dict with links, or None if not found
        """
        snapshot = self.repository.get_snapshot(map_id, version)
        if not snapshot:
            return None

        response = snapshot.to_dict()
        response["links"] = [
            {
                "rel": "self",
                "href": f"{base_url}/api/maps/{map_id}/snapshots/{version}",
                "type": "application/json"
            },
            {
                "rel": "restore",
                "href": f"{base_url}/api/maps/{map_id}/restore/{version}",
                "type": "application/json",
                "method": "POST"
            },
            {
                "rel": "map",
                "href": f"{base_url}/api/maps/{map_id}",
                "type": "application/json"
            }
        ]

        return response

    def restore_snapshot(self, map_id: str, version: int) -> bool:
        """
        Restore a map from a snapshot.

        Args:
            map_id: Map identifier
            version: Version to restore

        Returns:
            True if restored, False if snapshot not found
        """
        return self.repository.restore_snapshot(map_id, version)

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate_layers(self, layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate layer configurations through Pydantic model.

        This is the trust boundary - untrusted JSON is validated and converted
        to clean model output. Invalid data raises ValueError.

        Args:
            layers: List of layer configs from untrusted input

        Returns:
            List of validated layer dicts (from model_dump())

        Raises:
            ValueError: If any layer fails validation
        """
        validated = []

        for i, layer_data in enumerate(layers):
            try:
                layer = MapLayer(**layer_data)
                validated.append(layer.model_dump())
            except ValidationError as e:
                # Format Pydantic errors into readable message
                errors = [f"{err['loc'][0]}: {err['msg']}" for err in e.errors()]
                raise ValueError(f"Layer {i} validation failed: {'; '.join(errors)}")

        return validated

    def validate_map_config(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate a complete map configuration.

        Args:
            config: Map configuration dict

        Returns:
            List of validation messages (empty if valid)
        """
        messages = []

        if not config.get('name'):
            messages.append("name is required")

        # Validate map_type using MapType enum
        map_type = config.get('map_type')
        if map_type:
            valid_types = {e.value for e in MapType}
            if map_type not in valid_types:
                messages.append(f"Unknown map_type '{map_type}'. Valid: {', '.join(valid_types)}")

        # Validate coordinates
        if config.get('center_lon') is not None:
            lon = config['center_lon']
            if lon < -180 or lon > 180:
                messages.append("center_lon must be between -180 and 180")

        if config.get('center_lat') is not None:
            lat = config['center_lat']
            if lat < -90 or lat > 90:
                messages.append("center_lat must be between -90 and 90")

        if config.get('zoom_level') is not None:
            zoom = config['zoom_level']
            if zoom < 0 or zoom > 24:
                messages.append("zoom_level must be between 0 and 24")

        # Validate bounds
        if config.get('bounds'):
            bounds = config['bounds']
            if len(bounds) != 4:
                messages.append("bounds must be [minx, miny, maxx, maxy]")
            elif bounds[0] > bounds[2] or bounds[1] > bounds[3]:
                messages.append("bounds min values must be less than max values")

        # Validate layers through Pydantic model
        if config.get('layers'):
            try:
                self._validate_layers(config['layers'])
            except ValueError as e:
                messages.append(str(e))

        return messages
