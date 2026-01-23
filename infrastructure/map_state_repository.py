# ============================================================================
# MAP STATE REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Data access - PostgreSQL operations for map state storage
# PURPOSE: CRUD operations for app.map_states and app.map_state_snapshots
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# EXPORTS: MapStateRepository, get_map_state_repository
# DEPENDENCIES: psycopg, infrastructure.postgresql
# ============================================================================
"""
Map State Repository.

Provides database access for web map configurations:
- List map states (with filtering)
- Get specific map state by ID
- Create/update map states (upsert with snapshot)
- Delete map states
- Snapshot operations for version history

Uses app.map_states for current state and app.map_state_snapshots for history.

Following the same pattern as:
- RasterRenderRepository (infrastructure/raster_render_repository.py)
- OGCStylesRepository (ogc_styles/repository.py)

Created: 23 JAN 2026
"""

import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from core.models.map_state import MapState, MapStateSnapshot

logger = logging.getLogger(__name__)


# Module-level singleton
_repository_instance: Optional["MapStateRepository"] = None


def get_map_state_repository() -> "MapStateRepository":
    """
    Get singleton MapStateRepository instance.

    Returns:
        MapStateRepository singleton
    """
    global _repository_instance
    if _repository_instance is None:
        _repository_instance = MapStateRepository()
    return _repository_instance


class MapStateRepository:
    """
    PostgreSQL repository for map state configurations.

    Provides data access for app.map_states and app.map_state_snapshots.
    Auto-creates snapshots on updates for version history.

    Thread Safety:
        - Each method creates its own connection
        - Safe for concurrent requests in Azure Functions
    """

    def __init__(self):
        """Initialize repository with configuration."""
        from config import get_config
        self.config = get_config()
        self._schema = self.config.database.app_schema
        logger.debug(f"MapStateRepository initialized (schema: {self._schema})")

    def _get_connection_string(self) -> str:
        """Get PostgreSQL connection string with managed identity support."""
        # Use OGC Features config which has proper managed identity handling
        from ogc_features.config import get_ogc_config
        return get_ogc_config().get_connection_string()

    @contextmanager
    def _get_connection(self):
        """
        Context manager for PostgreSQL connections.

        Yields:
            psycopg connection with dict_row factory
        """
        conn = None
        try:
            conn = psycopg.connect(
                self._get_connection_string(),
                row_factory=dict_row
            )
            yield conn
        except psycopg.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    # =========================================================================
    # MAP STATE - READ OPERATIONS
    # =========================================================================

    def list_maps(
        self,
        map_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[MapState]:
        """
        List map states with optional filtering.

        Args:
            map_type: Filter by map type (maplibre, leaflet, openlayers)
            tags: Filter by tags (any match)
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of MapState instances
        """
        conditions = []
        params: List[Any] = []

        if map_type:
            conditions.append("map_type = %s")
            params.append(map_type)

        if tags:
            conditions.append("tags && %s")
            params.append(tags)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = sql.SQL("""
            SELECT map_id, name, description, map_type,
                   center_lon, center_lat, zoom_level, bounds,
                   layers, custom_attributes, tags, thumbnail_url,
                   version, created_at, updated_at
            FROM {schema}.map_states
            {where}
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT %s OFFSET %s
        """).format(
            schema=sql.Identifier(self._schema),
            where=sql.SQL(where_clause)
        )

        params.extend([limit, offset])

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    rows = cur.fetchall()
                    return [MapState.from_db_row(row) for row in rows]
        except psycopg.Error as e:
            logger.error(f"Error listing maps: {e}")
            raise

    def get_map(self, map_id: str) -> Optional[MapState]:
        """
        Get a specific map state.

        Args:
            map_id: Map identifier

        Returns:
            MapState or None if not found
        """
        query = sql.SQL("""
            SELECT map_id, name, description, map_type,
                   center_lon, center_lat, zoom_level, bounds,
                   layers, custom_attributes, tags, thumbnail_url,
                   version, created_at, updated_at
            FROM {schema}.map_states
            WHERE map_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (map_id,))
                    row = cur.fetchone()
                    return MapState.from_db_row(row) if row else None
        except psycopg.Error as e:
            logger.error(f"Error getting map '{map_id}': {e}")
            raise

    def map_exists(self, map_id: str) -> bool:
        """
        Check if a map state exists.

        Args:
            map_id: Map identifier

        Returns:
            True if exists
        """
        query = sql.SQL("""
            SELECT 1 FROM {schema}.map_states
            WHERE map_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (map_id,))
                    return cur.fetchone() is not None
        except psycopg.Error as e:
            logger.error(f"Error checking map existence: {e}")
            raise

    def count_maps(self, map_type: Optional[str] = None) -> int:
        """
        Count map states.

        Args:
            map_type: Optional filter by map type

        Returns:
            Number of maps
        """
        if map_type:
            query = sql.SQL("""
                SELECT COUNT(*) as count FROM {schema}.map_states
                WHERE map_type = %s
            """).format(schema=sql.Identifier(self._schema))
            params = (map_type,)
        else:
            query = sql.SQL("""
                SELECT COUNT(*) as count FROM {schema}.map_states
            """).format(schema=sql.Identifier(self._schema))
            params = ()

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()
                    return row['count'] if row else 0
        except psycopg.Error as e:
            logger.error(f"Error counting maps: {e}")
            raise

    # =========================================================================
    # MAP STATE - WRITE OPERATIONS
    # =========================================================================

    def create_map(
        self,
        map_id: str,
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
    ) -> bool:
        """
        Create a new map state.

        Args:
            map_id: Map identifier (SHA256 hash)
            name: Map name
            description: Map description
            map_type: Map container type
            center_lon: Center longitude
            center_lat: Center latitude
            zoom_level: Zoom level
            bounds: Map bounds [minx, miny, maxx, maxy]
            layers: Layer configurations
            custom_attributes: Custom attributes
            tags: Categorization tags
            thumbnail_url: Preview image URL

        Returns:
            True if created successfully

        Raises:
            ValueError: If map already exists
        """
        if self.map_exists(map_id):
            raise ValueError(f"Map '{map_id}' already exists. Use update_map instead.")

        query = sql.SQL("""
            INSERT INTO {schema}.map_states
            (map_id, name, description, map_type,
             center_lon, center_lat, zoom_level, bounds,
             layers, custom_attributes, tags, thumbnail_url,
             version, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, now(), now())
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (
                        map_id,
                        name,
                        description,
                        map_type,
                        center_lon,
                        center_lat,
                        zoom_level,
                        json.dumps(bounds) if bounds else None,
                        json.dumps(layers or []),
                        json.dumps(custom_attributes or {}),
                        json.dumps(tags or []),  # tags is JSONB column
                        thumbnail_url
                    ))
                    conn.commit()
                    logger.info(f"Created map '{name}' (id: {map_id})")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error creating map '{name}': {e}")
            raise

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
        thumbnail_url: Optional[str] = None,
        create_snapshot: bool = True
    ) -> bool:
        """
        Update a map state with automatic snapshot creation.

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
            create_snapshot: Whether to create a snapshot before update

        Returns:
            True if updated, False if map not found
        """
        # Get current state for snapshot
        current = self.get_map(map_id)
        if not current:
            return False

        # Create snapshot of current state before update
        if create_snapshot:
            self._create_snapshot(current, reason="auto_save")

        # Build update query
        updates = []
        params: List[Any] = []

        if name is not None:
            updates.append("name = %s")
            params.append(name)
        if description is not None:
            updates.append("description = %s")
            params.append(description)
        if map_type is not None:
            updates.append("map_type = %s")
            params.append(map_type)
        if center_lon is not None:
            updates.append("center_lon = %s")
            params.append(center_lon)
        if center_lat is not None:
            updates.append("center_lat = %s")
            params.append(center_lat)
        if zoom_level is not None:
            updates.append("zoom_level = %s")
            params.append(zoom_level)
        if bounds is not None:
            updates.append("bounds = %s")
            params.append(json.dumps(bounds))
        if layers is not None:
            updates.append("layers = %s")
            params.append(json.dumps(layers))
        if custom_attributes is not None:
            updates.append("custom_attributes = %s")
            params.append(json.dumps(custom_attributes))
        if tags is not None:
            updates.append("tags = %s")
            params.append(json.dumps(tags))
        if thumbnail_url is not None:
            updates.append("thumbnail_url = %s")
            params.append(thumbnail_url)

        # Always increment version and update timestamp
        updates.append("version = version + 1")
        updates.append("updated_at = now()")

        if not updates:
            return True  # Nothing to update

        query = sql.SQL("""
            UPDATE {schema}.map_states
            SET {updates}
            WHERE map_id = %s
        """).format(
            schema=sql.Identifier(self._schema),
            updates=sql.SQL(", ").join(sql.SQL(u) for u in updates)
        )

        params.append(map_id)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    conn.commit()
                    logger.info(f"Updated map '{map_id}'")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error updating map '{map_id}': {e}")
            raise

    def delete_map(self, map_id: str, create_snapshot: bool = True) -> bool:
        """
        Delete a map state.

        Args:
            map_id: Map identifier
            create_snapshot: Whether to create final snapshot before delete

        Returns:
            True if deleted, False if not found
        """
        # Get current state for final snapshot
        if create_snapshot:
            current = self.get_map(map_id)
            if current:
                self._create_snapshot(current, reason="before_delete")

        query = sql.SQL("""
            DELETE FROM {schema}.map_states
            WHERE map_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (map_id,))
                    conn.commit()
                    deleted = cur.rowcount > 0
                    if deleted:
                        logger.info(f"Deleted map '{map_id}'")
                    return deleted
        except psycopg.Error as e:
            logger.error(f"Error deleting map '{map_id}': {e}")
            raise

    # =========================================================================
    # SNAPSHOT OPERATIONS
    # =========================================================================

    def _create_snapshot(self, map_state: MapState, reason: str = "auto_save") -> bool:
        """
        Create a snapshot of the current map state.

        Internal method called automatically on updates/deletes.

        Args:
            map_state: Current MapState to snapshot
            reason: Reason for snapshot

        Returns:
            True if created successfully
        """
        snapshot = MapStateSnapshot.from_map_state(map_state, reason)

        query = sql.SQL("""
            INSERT INTO {schema}.map_state_snapshots
            (snapshot_id, map_id, version, state, snapshot_reason, created_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (map_id, version) DO NOTHING
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (
                        snapshot.snapshot_id,
                        snapshot.map_id,
                        snapshot.version,
                        json.dumps(snapshot.state),
                        snapshot.snapshot_reason
                    ))
                    conn.commit()
                    logger.debug(f"Created snapshot v{snapshot.version} for map '{snapshot.map_id}'")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error creating snapshot: {e}")
            raise

    def list_snapshots(self, map_id: str, limit: int = 50) -> List[MapStateSnapshot]:
        """
        List snapshots for a map.

        Args:
            map_id: Map identifier
            limit: Maximum snapshots to return

        Returns:
            List of MapStateSnapshot instances (newest first)
        """
        query = sql.SQL("""
            SELECT snapshot_id, map_id, version, state, snapshot_reason, created_at
            FROM {schema}.map_state_snapshots
            WHERE map_id = %s
            ORDER BY version DESC
            LIMIT %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (map_id, limit))
                    rows = cur.fetchall()
                    return [MapStateSnapshot.from_db_row(row) for row in rows]
        except psycopg.Error as e:
            logger.error(f"Error listing snapshots for '{map_id}': {e}")
            raise

    def get_snapshot(self, map_id: str, version: int) -> Optional[MapStateSnapshot]:
        """
        Get a specific snapshot.

        Args:
            map_id: Map identifier
            version: Version number

        Returns:
            MapStateSnapshot or None if not found
        """
        query = sql.SQL("""
            SELECT snapshot_id, map_id, version, state, snapshot_reason, created_at
            FROM {schema}.map_state_snapshots
            WHERE map_id = %s AND version = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (map_id, version))
                    row = cur.fetchone()
                    return MapStateSnapshot.from_db_row(row) if row else None
        except psycopg.Error as e:
            logger.error(f"Error getting snapshot v{version} for '{map_id}': {e}")
            raise

    def restore_snapshot(self, map_id: str, version: int) -> bool:
        """
        Restore a map state from a snapshot.

        Creates a new snapshot of current state, then restores from target version.

        Args:
            map_id: Map identifier
            version: Version to restore

        Returns:
            True if restored, False if snapshot not found
        """
        # Get the snapshot to restore
        snapshot = self.get_snapshot(map_id, version)
        if not snapshot:
            return False

        # Get current state and create snapshot
        current = self.get_map(map_id)
        if current:
            self._create_snapshot(current, reason="before_restore")

        # Restore from snapshot state
        state = snapshot.state
        query = sql.SQL("""
            UPDATE {schema}.map_states
            SET name = %s,
                description = %s,
                map_type = %s,
                center_lon = %s,
                center_lat = %s,
                zoom_level = %s,
                bounds = %s,
                layers = %s,
                custom_attributes = %s,
                tags = %s,
                thumbnail_url = %s,
                version = version + 1,
                updated_at = now()
            WHERE map_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (
                        state.get('name'),
                        state.get('description'),
                        state.get('map_type', 'maplibre'),
                        state.get('center_lon'),
                        state.get('center_lat'),
                        state.get('zoom_level'),
                        json.dumps(state.get('bounds')) if state.get('bounds') else None,
                        json.dumps(state.get('layers', [])),
                        json.dumps(state.get('custom_attributes', {})),
                        state.get('tags', []),
                        state.get('thumbnail_url'),
                        map_id
                    ))
                    conn.commit()
                    logger.info(f"Restored map '{map_id}' from snapshot v{version}")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error restoring snapshot: {e}")
            raise

    def delete_old_snapshots(self, map_id: str, keep_count: int = 10) -> int:
        """
        Delete old snapshots, keeping the most recent N.

        Args:
            map_id: Map identifier
            keep_count: Number of recent snapshots to keep

        Returns:
            Number of snapshots deleted
        """
        query = sql.SQL("""
            DELETE FROM {schema}.map_state_snapshots
            WHERE map_id = %s
            AND snapshot_id NOT IN (
                SELECT snapshot_id
                FROM {schema}.map_state_snapshots
                WHERE map_id = %s
                ORDER BY version DESC
                LIMIT %s
            )
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (map_id, map_id, keep_count))
                    conn.commit()
                    deleted = cur.rowcount
                    if deleted > 0:
                        logger.info(f"Deleted {deleted} old snapshots for map '{map_id}'")
                    return deleted
        except psycopg.Error as e:
            logger.error(f"Error deleting old snapshots: {e}")
            raise
