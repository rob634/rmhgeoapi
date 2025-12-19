# ============================================================================
# CLAUDE CONTEXT - OGC STYLES REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Data access - PostgreSQL operations for style storage
# PURPOSE: CRUD operations for geo.feature_collection_styles table
# LAST_REVIEWED: 18 DEC 2025
# EXPORTS: OGCStylesRepository
# DEPENDENCIES: psycopg, ogc_features.config
# ============================================================================
"""
OGC Styles Repository.

Provides database access for OGC API Styles:
- List styles for a collection
- Get specific style by ID
- Create/update styles (upsert)
- Auto-generate default styles based on geometry type

Uses geo.feature_collection_styles table for CartoSym-JSON storage.

Created: 18 DEC 2025
"""

import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from ogc_features.config import OGCFeaturesConfig, get_ogc_config

logger = logging.getLogger(__name__)


class OGCStylesRepository:
    """
    PostgreSQL repository for OGC API Styles.

    Provides data access for geo.feature_collection_styles table.
    Stores styles in CartoSym-JSON format with support for
    collection-level organization and default style designation.

    Thread Safety:
    - Each method creates its own connection
    - Safe for concurrent requests in Azure Functions
    """

    def __init__(self, config: Optional[OGCFeaturesConfig] = None):
        """
        Initialize repository with configuration.

        Args:
            config: OGC Features configuration (uses singleton if not provided)
        """
        self.config = config or get_ogc_config()
        logger.info(f"OGCStylesRepository initialized (schema: {self.config.ogc_schema})")

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
                self.config.get_connection_string(),
                row_factory=dict_row
            )
            yield conn
        except psycopg.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    # ========================================================================
    # STYLE QUERIES
    # ========================================================================

    def list_styles(self, collection_id: str) -> List[Dict[str, Any]]:
        """
        List all styles for a collection.

        Args:
            collection_id: Collection identifier (table name)

        Returns:
            List of style metadata dicts with keys:
            - style_id: Style identifier
            - title: Human-readable title
            - description: Style description
            - is_default: Whether this is the default style
        """
        query = sql.SQL("""
            SELECT style_id, title, description, is_default
            FROM geo.feature_collection_styles
            WHERE collection_id = %s
            ORDER BY is_default DESC, title ASC
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id,))
                    results = cur.fetchall()
                    logger.info(f"Found {len(results)} styles for collection '{collection_id}'")
                    return results
        except psycopg.Error as e:
            logger.error(f"Error listing styles for '{collection_id}': {e}")
            raise

    def get_style(self, collection_id: str, style_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific style document.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier

        Returns:
            Style dict with style_spec (CartoSym-JSON), or None if not found
        """
        query = sql.SQL("""
            SELECT style_id, title, description, style_spec, is_default
            FROM geo.feature_collection_styles
            WHERE collection_id = %s AND style_id = %s
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id, style_id))
                    result = cur.fetchone()
                    if result:
                        logger.info(f"Retrieved style '{style_id}' for collection '{collection_id}'")
                    return result
        except psycopg.Error as e:
            logger.error(f"Error getting style '{style_id}' for '{collection_id}': {e}")
            raise

    def get_default_style(self, collection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the default style for a collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Default style dict, or None if no default exists
        """
        query = sql.SQL("""
            SELECT style_id, title, description, style_spec, is_default
            FROM geo.feature_collection_styles
            WHERE collection_id = %s AND is_default = true
            LIMIT 1
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id,))
                    return cur.fetchone()
        except psycopg.Error as e:
            logger.error(f"Error getting default style for '{collection_id}': {e}")
            raise

    def style_exists(self, collection_id: str, style_id: str) -> bool:
        """
        Check if a style exists.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier

        Returns:
            True if style exists
        """
        query = sql.SQL("""
            SELECT EXISTS(
                SELECT 1 FROM geo.feature_collection_styles
                WHERE collection_id = %s AND style_id = %s
            ) as exists
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id, style_id))
                    result = cur.fetchone()
                    return result['exists'] if result else False
        except psycopg.Error as e:
            logger.error(f"Error checking style existence: {e}")
            raise

    # ========================================================================
    # STYLE MUTATIONS
    # ========================================================================

    def create_style(
        self,
        collection_id: str,
        style_id: str,
        style_spec: Dict[str, Any],
        title: Optional[str] = None,
        description: Optional[str] = None,
        is_default: bool = False
    ) -> bool:
        """
        Create or update a style for a collection.

        Uses upsert (INSERT ... ON CONFLICT UPDATE) for idempotency.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier (url-safe)
            style_spec: CartoSym-JSON document
            title: Human-readable title
            description: Style description
            is_default: Whether this is the default style

        Returns:
            True if created/updated successfully
        """
        # If setting as default, first unset any existing default
        unset_query = sql.SQL("""
            UPDATE geo.feature_collection_styles
            SET is_default = false, updated_at = now()
            WHERE collection_id = %s AND is_default = true
        """)

        upsert_query = sql.SQL("""
            INSERT INTO geo.feature_collection_styles
            (collection_id, style_id, title, description, style_spec, is_default)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (collection_id, style_id) DO UPDATE
            SET title = EXCLUDED.title,
                description = EXCLUDED.description,
                style_spec = EXCLUDED.style_spec,
                is_default = EXCLUDED.is_default,
                updated_at = now()
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if is_default:
                        cur.execute(unset_query, (collection_id,))
                    cur.execute(upsert_query, (
                        collection_id,
                        style_id,
                        title,
                        description,
                        json.dumps(style_spec),
                        is_default
                    ))
                    conn.commit()
                    logger.info(f"Created/updated style '{style_id}' for collection '{collection_id}'")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error creating style '{style_id}' for '{collection_id}': {e}")
            raise

    def delete_style(self, collection_id: str, style_id: str) -> bool:
        """
        Delete a style.

        Args:
            collection_id: Collection identifier
            style_id: Style identifier

        Returns:
            True if deleted, False if not found
        """
        query = sql.SQL("""
            DELETE FROM geo.feature_collection_styles
            WHERE collection_id = %s AND style_id = %s
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (collection_id, style_id))
                    conn.commit()
                    deleted = cur.rowcount > 0
                    if deleted:
                        logger.info(f"Deleted style '{style_id}' from collection '{collection_id}'")
                    return deleted
        except psycopg.Error as e:
            logger.error(f"Error deleting style '{style_id}' from '{collection_id}': {e}")
            raise

    # ========================================================================
    # DEFAULT STYLE GENERATION
    # ========================================================================

    def create_default_style_for_collection(
        self,
        collection_id: str,
        geometry_type: str,
        fill_color: str = "#3388ff",
        stroke_color: str = "#2266cc"
    ) -> bool:
        """
        Create a default style for a collection based on geometry type.

        Called from ETL pipeline after table creation to auto-generate styles.

        Args:
            collection_id: Collection identifier (table name)
            geometry_type: PostGIS geometry type (Polygon, LineString, Point, etc.)
            fill_color: Fill color (hex)
            stroke_color: Stroke color (hex)

        Returns:
            True if created successfully
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

        return self.create_style(
            collection_id=collection_id,
            style_id="default",
            style_spec=style_spec,
            title=style_spec["title"],
            description=f"Auto-generated default style for {collection_id}",
            is_default=True
        )

    # ========================================================================
    # TABLE EXISTENCE CHECK
    # ========================================================================

    def styles_table_exists(self) -> bool:
        """
        Check if the geo.feature_collection_styles table exists.

        Returns:
            True if table exists
        """
        query = sql.SQL("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'geo'
                AND table_name = 'feature_collection_styles'
            ) as table_exists
        """)

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    result = cur.fetchone()
                    return result['table_exists'] if result else False
        except psycopg.Error as e:
            logger.error(f"Error checking styles table existence: {e}")
            return False
