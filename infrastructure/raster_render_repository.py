# ============================================================================
# RASTER RENDER CONFIG REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Data access - PostgreSQL operations for render config storage
# PURPOSE: CRUD operations for app.raster_render_configs table
# LAST_REVIEWED: 22 JAN 2026
# EXPORTS: RasterRenderRepository, get_raster_render_repository
# DEPENDENCIES: psycopg, infrastructure.postgresql
# ============================================================================
"""
Raster Render Config Repository.

Provides database access for TiTiler render configurations:
- List render configs for a COG
- Get specific render config by ID
- Create/update render configs (upsert)
- Set default render for a COG
- Delete render configs

Uses app.raster_render_configs table for TiTiler parameter storage.

Following the same pattern as:
- OGCStylesRepository (ogc_styles/repository.py)
- RasterMetadataRepository (infrastructure/raster_metadata_repository.py)

Created: 22 JAN 2026
Epic: E2 Raster Data as API → F2.11 Raster Render Configuration System
"""

import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from core.models.raster_render_config import RasterRenderConfig

logger = logging.getLogger(__name__)


# Module-level singleton
_repository_instance: Optional["RasterRenderRepository"] = None


def get_raster_render_repository() -> "RasterRenderRepository":
    """
    Get singleton RasterRenderRepository instance.

    Returns:
        RasterRenderRepository singleton
    """
    global _repository_instance
    if _repository_instance is None:
        _repository_instance = RasterRenderRepository()
    return _repository_instance


class RasterRenderRepository:
    """
    PostgreSQL repository for raster render configurations.

    Provides data access for app.raster_render_configs table.
    Stores TiTiler render parameters in JSONB format with support for
    COG-level organization and default render designation.

    Thread Safety:
        - Each method creates its own connection
        - Safe for concurrent requests in Azure Functions
    """

    def __init__(self):
        """Initialize repository with configuration."""
        from config import get_config
        self.config = get_config()
        self._schema = self.config.database.app_schema
        logger.debug(f"RasterRenderRepository initialized (schema: {self._schema})")

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
    # READ OPERATIONS
    # =========================================================================

    def list_renders(self, cog_id: str) -> List[RasterRenderConfig]:
        """
        List all render configs for a COG.

        Args:
            cog_id: COG identifier

        Returns:
            List of RasterRenderConfig instances (empty if none)
        """
        query = sql.SQL("""
            SELECT id, cog_id, render_id, title, description,
                   render_spec, is_default, created_at, updated_at
            FROM {schema}.raster_render_configs
            WHERE cog_id = %s
            ORDER BY is_default DESC, render_id ASC
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id,))
                    rows = cur.fetchall()
                    return [RasterRenderConfig.from_db_row(row) for row in rows]
        except psycopg.Error as e:
            logger.error(f"Error listing renders for '{cog_id}': {e}")
            raise

    def get_render(self, cog_id: str, render_id: str) -> Optional[RasterRenderConfig]:
        """
        Get a specific render config.

        Args:
            cog_id: COG identifier
            render_id: Render identifier

        Returns:
            RasterRenderConfig or None if not found
        """
        query = sql.SQL("""
            SELECT id, cog_id, render_id, title, description,
                   render_spec, is_default, created_at, updated_at
            FROM {schema}.raster_render_configs
            WHERE cog_id = %s AND render_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id, render_id))
                    row = cur.fetchone()
                    return RasterRenderConfig.from_db_row(row) if row else None
        except psycopg.Error as e:
            logger.error(f"Error getting render '{render_id}' for '{cog_id}': {e}")
            raise

    def get_default_render(self, cog_id: str) -> Optional[RasterRenderConfig]:
        """
        Get the default render config for a COG.

        Args:
            cog_id: COG identifier

        Returns:
            Default RasterRenderConfig or None if not set
        """
        query = sql.SQL("""
            SELECT id, cog_id, render_id, title, description,
                   render_spec, is_default, created_at, updated_at
            FROM {schema}.raster_render_configs
            WHERE cog_id = %s AND is_default = true
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id,))
                    row = cur.fetchone()
                    return RasterRenderConfig.from_db_row(row) if row else None
        except psycopg.Error as e:
            logger.error(f"Error getting default render for '{cog_id}': {e}")
            raise

    def get_renders_for_stac(self, cog_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all renders formatted for STAC asset.renders embedding.

        Args:
            cog_id: COG identifier

        Returns:
            Dict of render_id → STAC render format
            Example: {"default": {"title": "...", "colormap_name": "viridis"}}
        """
        renders = self.list_renders(cog_id)
        return {r.render_id: r.to_stac_render() for r in renders}

    def render_exists(self, cog_id: str, render_id: str) -> bool:
        """
        Check if a render config exists.

        Args:
            cog_id: COG identifier
            render_id: Render identifier

        Returns:
            True if exists
        """
        query = sql.SQL("""
            SELECT 1 FROM {schema}.raster_render_configs
            WHERE cog_id = %s AND render_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id, render_id))
                    return cur.fetchone() is not None
        except psycopg.Error as e:
            logger.error(f"Error checking render existence: {e}")
            raise

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    def create_render(
        self,
        cog_id: str,
        render_id: str,
        render_spec: Dict[str, Any],
        title: Optional[str] = None,
        description: Optional[str] = None,
        is_default: bool = False
    ) -> bool:
        """
        Create or update a render config (upsert).

        Args:
            cog_id: COG identifier
            render_id: Render identifier (URL-safe)
            render_spec: TiTiler render parameters
            title: Human-readable title
            description: Render description
            is_default: Whether this is the default render

        Returns:
            True if created/updated successfully
        """
        # If setting as default, first unset any existing default
        unset_query = sql.SQL("""
            UPDATE {schema}.raster_render_configs
            SET is_default = false, updated_at = now()
            WHERE cog_id = %s AND is_default = true
        """).format(schema=sql.Identifier(self._schema))

        upsert_query = sql.SQL("""
            INSERT INTO {schema}.raster_render_configs
            (cog_id, render_id, title, description, render_spec, is_default)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (cog_id, render_id) DO UPDATE
            SET title = EXCLUDED.title,
                description = EXCLUDED.description,
                render_spec = EXCLUDED.render_spec,
                is_default = EXCLUDED.is_default,
                updated_at = now()
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    if is_default:
                        cur.execute(unset_query, (cog_id,))
                    cur.execute(upsert_query, (
                        cog_id,
                        render_id,
                        title,
                        description,
                        json.dumps(render_spec),
                        is_default
                    ))
                    conn.commit()
                    logger.info(f"Created/updated render '{render_id}' for COG '{cog_id}'")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error creating render '{render_id}' for '{cog_id}': {e}")
            raise

    def create_from_model(self, config: RasterRenderConfig) -> bool:
        """
        Create or update a render config from a model instance.

        Args:
            config: RasterRenderConfig instance

        Returns:
            True if created/updated successfully
        """
        return self.create_render(
            cog_id=config.cog_id,
            render_id=config.render_id,
            render_spec=config.render_spec,
            title=config.title,
            description=config.description,
            is_default=config.is_default
        )

    def set_default(self, cog_id: str, render_id: str) -> bool:
        """
        Set a render config as the default for its COG.

        Args:
            cog_id: COG identifier
            render_id: Render identifier to set as default

        Returns:
            True if updated, False if render not found
        """
        # First check if render exists
        if not self.render_exists(cog_id, render_id):
            return False

        unset_query = sql.SQL("""
            UPDATE {schema}.raster_render_configs
            SET is_default = false, updated_at = now()
            WHERE cog_id = %s AND is_default = true
        """).format(schema=sql.Identifier(self._schema))

        set_query = sql.SQL("""
            UPDATE {schema}.raster_render_configs
            SET is_default = true, updated_at = now()
            WHERE cog_id = %s AND render_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(unset_query, (cog_id,))
                    cur.execute(set_query, (cog_id, render_id))
                    conn.commit()
                    logger.info(f"Set render '{render_id}' as default for COG '{cog_id}'")
                    return True
        except psycopg.Error as e:
            logger.error(f"Error setting default render: {e}")
            raise

    def delete_render(self, cog_id: str, render_id: str) -> bool:
        """
        Delete a render config.

        Args:
            cog_id: COG identifier
            render_id: Render identifier

        Returns:
            True if deleted, False if not found
        """
        query = sql.SQL("""
            DELETE FROM {schema}.raster_render_configs
            WHERE cog_id = %s AND render_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id, render_id))
                    conn.commit()
                    deleted = cur.rowcount > 0
                    if deleted:
                        logger.info(f"Deleted render '{render_id}' from COG '{cog_id}'")
                    return deleted
        except psycopg.Error as e:
            logger.error(f"Error deleting render: {e}")
            raise

    def delete_all_renders(self, cog_id: str) -> int:
        """
        Delete all render configs for a COG.

        Used when unpublishing/deleting a COG.

        Args:
            cog_id: COG identifier

        Returns:
            Number of renders deleted
        """
        query = sql.SQL("""
            DELETE FROM {schema}.raster_render_configs
            WHERE cog_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id,))
                    conn.commit()
                    deleted = cur.rowcount
                    if deleted > 0:
                        logger.info(f"Deleted {deleted} renders for COG '{cog_id}'")
                    return deleted
        except psycopg.Error as e:
            logger.error(f"Error deleting renders for COG: {e}")
            raise

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def create_default_render_for_cog(
        self,
        cog_id: str,
        dtype: str = "float32",
        band_count: int = 1,
        nodata: Optional[float] = None
    ) -> bool:
        """
        Auto-generate and save a default render config based on raster properties.

        Args:
            cog_id: COG identifier
            dtype: Numpy dtype (uint8, uint16, float32, etc.)
            band_count: Number of bands
            nodata: NoData value

        Returns:
            True if created successfully
        """
        config = RasterRenderConfig.create_default_for_cog(
            cog_id=cog_id,
            dtype=dtype,
            band_count=band_count,
            nodata=nodata
        )
        return self.create_from_model(config)

    def count_renders(self, cog_id: str) -> int:
        """
        Count render configs for a COG.

        Args:
            cog_id: COG identifier

        Returns:
            Number of render configs
        """
        query = sql.SQL("""
            SELECT COUNT(*) FROM {schema}.raster_render_configs
            WHERE cog_id = %s
        """).format(schema=sql.Identifier(self._schema))

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (cog_id,))
                    row = cur.fetchone()
                    return row['count'] if row else 0
        except psycopg.Error as e:
            logger.error(f"Error counting renders: {e}")
            raise
