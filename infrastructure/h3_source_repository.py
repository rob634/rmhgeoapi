# ============================================================================
# CLAUDE CONTEXT - H3 SOURCE CATALOG REPOSITORY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - H3 Source Catalog Data Access
# PURPOSE: CRUD operations for h3.source_catalog table
# LAST_REVIEWED: 27 DEC 2025
# EXPORTS: H3SourceRepository
# DEPENDENCIES: psycopg, infrastructure.postgresql
# ============================================================================
"""
H3 Source Catalog Repository - Safe PostgreSQL Operations for Source Metadata.

Provides repository implementation for h3.source_catalog table, which stores
comprehensive metadata for data sources used in H3 aggregation pipelines.

Key Features:
    - Safe SQL composition using psycopg.sql.Identifier()
    - Full CRUD operations for source catalog entries
    - Support for Planetary Computer, Azure Blob, URL, and PostGIS sources
    - Filtering by theme, source_type, and is_active

Usage:
    from infrastructure.h3_source_repository import H3SourceRepository

    repo = H3SourceRepository()
    source = repo.get_source('cop-dem-glo-30')
    sources = repo.list_sources(theme='terrain')
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from psycopg import sql
from datetime import datetime

from infrastructure.postgresql import PostgreSQLRepository

# Logger setup
logger = logging.getLogger(__name__)


class H3SourceRepository:
    """
    Repository for h3.source_catalog operations.

    Provides CRUD operations for managing data source metadata used in
    H3 aggregation pipelines.

    Usage:
        repo = H3SourceRepository()
        source = repo.get_source('cop-dem-glo-30')
    """

    # Valid themes (must match h3_schema.py)
    VALID_THEMES = [
        'terrain', 'water', 'climate', 'demographics',
        'infrastructure', 'landcover', 'vegetation', 'risk', 'agriculture'
    ]

    # Valid source types
    VALID_SOURCE_TYPES = ['planetary_computer', 'azure_blob', 'url', 'postgis']

    def __init__(self):
        """Initialize H3SourceRepository with PostgreSQL repository."""
        self.repo = PostgreSQLRepository()
        self.schema = os.getenv('H3_SCHEMA', 'h3')
        logger.info(f"✅ H3SourceRepository initialized (schema: {self.schema})")

    def get_source(self, source_id: str) -> Dict[str, Any]:
        """
        Get a source by ID from h3.source_catalog.

        Parameters:
        ----------
        source_id : str
            Source identifier (e.g., 'cop-dem-glo-30')

        Returns:
        -------
        Dict[str, Any]
            Source entry with all metadata

        Raises:
        ------
        ValueError: If source not found or inactive
        """
        query = sql.SQL("""
            SELECT *
            FROM {schema}.{table}
            WHERE id = %s AND is_active = true
        """).format(
            schema=sql.Identifier(self.schema),
            table=sql.Identifier('source_catalog')
        )

        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (source_id,))
                result = cur.fetchone()

        if not result:
            raise ValueError(f"Source not found or inactive: {source_id}")

        source = dict(result)
        logger.debug(f"📊 Loaded source: {source_id} (theme={source.get('theme')})")
        return source

    def list_sources(
        self,
        theme: Optional[str] = None,
        source_type: Optional[str] = None,
        is_active: bool = True
    ) -> List[Dict[str, Any]]:
        """
        List sources, optionally filtered by theme or source_type.

        Parameters:
        ----------
        theme : Optional[str]
            Filter by theme (terrain, water, etc.)
        source_type : Optional[str]
            Filter by source type (planetary_computer, azure_blob, etc.)
        is_active : bool
            Only return active sources (default: True)

        Returns:
        -------
        List[Dict[str, Any]]
            List of source entries
        """
        # Build WHERE conditions
        conditions = []
        params = []

        if is_active:
            conditions.append("is_active = true")

        if theme:
            if theme not in self.VALID_THEMES:
                raise ValueError(f"Invalid theme '{theme}'. Must be one of: {self.VALID_THEMES}")
            conditions.append("theme = %s")
            params.append(theme)

        if source_type:
            if source_type not in self.VALID_SOURCE_TYPES:
                raise ValueError(f"Invalid source_type '{source_type}'. Must be one of: {self.VALID_SOURCE_TYPES}")
            conditions.append("source_type = %s")
            params.append(source_type)

        where_clause = " AND ".join(conditions) if conditions else "true"

        query = sql.SQL("""
            SELECT *
            FROM {schema}.{table}
            WHERE """ + where_clause + """
            ORDER BY theme, display_name
        """).format(
            schema=sql.Identifier(self.schema),
            table=sql.Identifier('source_catalog')
        )

        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                results = cur.fetchall()

        sources = [dict(row) for row in results]
        logger.info(f"📊 Listed {len(sources)} sources" +
                   (f" (theme={theme})" if theme else "") +
                   (f" (source_type={source_type})" if source_type else ""))
        return sources

    def register_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """
        Register a new source in h3.source_catalog (UPSERT).

        Parameters:
        ----------
        source : Dict[str, Any]
            Source definition with required keys:
            - id: str (unique identifier)
            - display_name: str
            - source_type: str (planetary_computer, azure_blob, url, postgis)
            - theme: str (terrain, water, climate, etc.)

            Optional keys:
            - description, stac_api_url, collection_id, asset_key
            - item_id_pattern, tile_size_degrees, tile_count, tile_naming_convention
            - native_resolution_m, crs, data_type, nodata_value, value_range
            - band_count, band_info, recommended_stats, recommended_h3_res_min/max
            - aggregation_method, unit, spatial_extent, coverage_type, land_only
            - temporal_extent_start/end, is_temporal_series, update_frequency
            - avg_tile_size_mb, recommended_batch_size, requires_auth
            - source_provider, source_url, source_license, citation

        Returns:
        -------
        Dict[str, Any]
            Registered source with 'created' flag

        Raises:
        ------
        ValueError: If required fields missing or invalid values
        """
        # Validate required fields
        required_fields = ['id', 'display_name', 'source_type', 'theme']
        for field in required_fields:
            if field not in source:
                raise ValueError(f"Required field missing: {field}")

        # Validate theme
        if source['theme'] not in self.VALID_THEMES:
            raise ValueError(f"Invalid theme '{source['theme']}'. Must be one of: {self.VALID_THEMES}")

        # Validate source_type
        if source['source_type'] not in self.VALID_SOURCE_TYPES:
            raise ValueError(f"Invalid source_type '{source['source_type']}'. Must be one of: {self.VALID_SOURCE_TYPES}")

        # Convert JSONB fields
        value_range = source.get('value_range')
        if value_range and isinstance(value_range, dict):
            value_range = json.dumps(value_range)
        elif value_range:
            value_range = json.dumps(value_range)

        band_info = source.get('band_info')
        if band_info and isinstance(band_info, (list, dict)):
            band_info = json.dumps(band_info)
        elif band_info:
            band_info = json.dumps(band_info)

        query = sql.SQL("""
            INSERT INTO {schema}.{table} (
                id, display_name, description,
                source_type, stac_api_url, collection_id, asset_key,
                item_id_pattern, tile_size_degrees, tile_count, tile_naming_convention,
                native_resolution_m, crs, data_type, nodata_value, value_range,
                band_count, band_info,
                theme, recommended_stats, recommended_h3_res_min, recommended_h3_res_max,
                aggregation_method, unit,
                coverage_type, land_only,
                temporal_extent_start, temporal_extent_end, is_temporal_series, update_frequency,
                avg_tile_size_mb, recommended_batch_size, requires_auth,
                source_provider, source_url, source_license, citation,
                created_at, updated_at, is_active
            )
            VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                NOW(), NOW(), true
            )
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                source_type = EXCLUDED.source_type,
                stac_api_url = EXCLUDED.stac_api_url,
                collection_id = EXCLUDED.collection_id,
                asset_key = EXCLUDED.asset_key,
                item_id_pattern = EXCLUDED.item_id_pattern,
                tile_size_degrees = EXCLUDED.tile_size_degrees,
                tile_count = EXCLUDED.tile_count,
                tile_naming_convention = EXCLUDED.tile_naming_convention,
                native_resolution_m = EXCLUDED.native_resolution_m,
                crs = EXCLUDED.crs,
                data_type = EXCLUDED.data_type,
                nodata_value = EXCLUDED.nodata_value,
                value_range = EXCLUDED.value_range,
                band_count = EXCLUDED.band_count,
                band_info = EXCLUDED.band_info,
                theme = EXCLUDED.theme,
                recommended_stats = EXCLUDED.recommended_stats,
                recommended_h3_res_min = EXCLUDED.recommended_h3_res_min,
                recommended_h3_res_max = EXCLUDED.recommended_h3_res_max,
                aggregation_method = EXCLUDED.aggregation_method,
                unit = EXCLUDED.unit,
                coverage_type = EXCLUDED.coverage_type,
                land_only = EXCLUDED.land_only,
                temporal_extent_start = EXCLUDED.temporal_extent_start,
                temporal_extent_end = EXCLUDED.temporal_extent_end,
                is_temporal_series = EXCLUDED.is_temporal_series,
                update_frequency = EXCLUDED.update_frequency,
                avg_tile_size_mb = EXCLUDED.avg_tile_size_mb,
                recommended_batch_size = EXCLUDED.recommended_batch_size,
                requires_auth = EXCLUDED.requires_auth,
                source_provider = EXCLUDED.source_provider,
                source_url = EXCLUDED.source_url,
                source_license = EXCLUDED.source_license,
                citation = EXCLUDED.citation,
                updated_at = NOW(),
                is_active = true
            RETURNING id, theme, (xmax = 0) AS created, updated_at
        """).format(
            schema=sql.Identifier(self.schema),
            table=sql.Identifier('source_catalog')
        )

        params = (
            source['id'],
            source['display_name'],
            source.get('description'),
            source['source_type'],
            source.get('stac_api_url'),
            source.get('collection_id'),
            source.get('asset_key', 'data'),
            source.get('item_id_pattern'),
            source.get('tile_size_degrees'),
            source.get('tile_count'),
            source.get('tile_naming_convention'),
            source.get('native_resolution_m'),
            source.get('crs', 'EPSG:4326'),
            source.get('data_type'),
            source.get('nodata_value'),
            value_range,
            source.get('band_count', 1),
            band_info,
            source['theme'],
            source.get('recommended_stats', ['mean']),
            source.get('recommended_h3_res_min', 4),
            source.get('recommended_h3_res_max', 8),
            source.get('aggregation_method', 'zonal_stats'),
            source.get('unit'),
            source.get('coverage_type', 'global'),
            source.get('land_only', True),
            source.get('temporal_extent_start'),
            source.get('temporal_extent_end'),
            source.get('is_temporal_series', False),
            source.get('update_frequency'),
            source.get('avg_tile_size_mb'),
            source.get('recommended_batch_size', 500),
            source.get('requires_auth', True),
            source.get('source_provider'),
            source.get('source_url'),
            source.get('source_license'),
            source.get('citation'),
        )

        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone()
                conn.commit()

        action = "Registered" if result['created'] else "Updated"
        logger.info(f"✅ {action} source: {source['id']} (theme={source['theme']}, source_type={source['source_type']})")

        return dict(result)

    def update_source(self, source_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update specific fields of a source.

        Parameters:
        ----------
        source_id : str
            Source identifier
        updates : Dict[str, Any]
            Fields to update

        Returns:
        -------
        Dict[str, Any]
            Updated source entry

        Raises:
        ------
        ValueError: If source not found
        """
        # Get existing source first
        existing = self.get_source(source_id)

        # Merge updates into existing
        for key, value in updates.items():
            existing[key] = value

        # Re-register with merged data
        return self.register_source(existing)

    def deactivate_source(self, source_id: str) -> bool:
        """
        Soft delete a source by setting is_active = false.

        Parameters:
        ----------
        source_id : str
            Source identifier

        Returns:
        -------
        bool
            True if deactivated, False if not found
        """
        query = sql.SQL("""
            UPDATE {schema}.{table}
            SET is_active = false, updated_at = NOW()
            WHERE id = %s
            RETURNING id
        """).format(
            schema=sql.Identifier(self.schema),
            table=sql.Identifier('source_catalog')
        )

        with self.repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (source_id,))
                result = cur.fetchone()
                conn.commit()

        if result:
            logger.info(f"🗑️ Deactivated source: {source_id}")
            return True
        else:
            logger.warning(f"⚠️ Source not found for deactivation: {source_id}")
            return False

    def get_sources_for_theme(self, theme: str) -> List[Dict[str, Any]]:
        """
        Get all active sources for a specific theme.

        Parameters:
        ----------
        theme : str
            Theme name (terrain, water, etc.)

        Returns:
        -------
        List[Dict[str, Any]]
            List of sources for the theme
        """
        return self.list_sources(theme=theme, is_active=True)

    def get_planetary_computer_sources(self) -> List[Dict[str, Any]]:
        """
        Get all active Planetary Computer sources.

        Returns:
        -------
        List[Dict[str, Any]]
            List of Planetary Computer sources
        """
        return self.list_sources(source_type='planetary_computer', is_active=True)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['H3SourceRepository']
