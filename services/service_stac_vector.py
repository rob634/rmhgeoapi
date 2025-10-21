# ============================================================================
# CLAUDE CONTEXT - SERVICE
# ============================================================================
# PURPOSE: Extract STAC metadata from PostGIS vector tables for cataloging
# EXPORTS: StacVectorService class
# PYDANTIC_MODELS: stac_pydantic.Item, stac_pydantic.Asset
# DEPENDENCIES: stac-pydantic, psycopg, shapely
# PATTERNS: Service Layer, DRY (leverage PostGIS for metadata extraction)
# ENTRY_POINTS: StacVectorService().extract_item_from_table()
# INDEX: StacVectorService:40, extract_item_from_table:55, _get_table_extent:150
# ============================================================================

"""
STAC Vector Metadata Service

Extracts STAC Item metadata from PostGIS vector tables.
Validates with stac-pydantic for type safety and STAC spec compliance.

Strategy: DRY - Leverage PostGIS for spatial operations
- PostGIS: Geometry extent, bounds, row count, geometry types
- stac-pydantic: Validation and type safety
- Our code: Table metadata, custom properties, asset links

Author: Robert and Geospatial Claude Legion
Date: 7 OCT 2025
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import logging
import psycopg
from psycopg import sql

from stac_pydantic import Item
from stac_pydantic.shared import Asset
from shapely.geometry import box

from config import get_config
from infrastructure.stac import StacInfrastructure
from util_logger import LoggerFactory, ComponentType

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "stac_vector_service"
)


class StacVectorService:
    """
    Extract and validate STAC metadata from PostGIS vector tables.

    Uses PostGIS spatial queries for extent and metadata extraction.
    Creates STAC Items with postgis:// asset links for table access.
    """

    def __init__(self):
        """Initialize STAC vector service."""
        self.config = get_config()
        self.stac = StacInfrastructure()

    def extract_item_from_table(
        self,
        schema: str,
        table_name: str,
        collection_id: str = 'vectors',
        source_file: Optional[str] = None,
        additional_properties: Optional[Dict[str, Any]] = None
    ) -> Item:
        """
        Extract STAC Item from PostGIS table.

        Args:
            schema: PostgreSQL schema name (e.g., 'geo')
            table_name: Table name in schema
            collection_id: STAC collection ID (default: 'vectors')
            source_file: Optional source file path (e.g., blob name)
            additional_properties: Optional custom properties to add

        Returns:
            Validated stac-pydantic Item

        Raises:
            ValidationError: If extracted metadata fails STAC validation
            psycopg.Error: If table doesn't exist or query fails

        Strategy:
            1. Query PostGIS for table extent and metadata
            2. Extract geometry types and row count
            3. Build STAC Item with postgis:// asset link
            4. Validate with stac-pydantic
        """
        logger.info(f"Extracting STAC Item from {schema}.{table_name}")

        # Get table metadata from PostGIS
        metadata = self._get_table_metadata(schema, table_name)

        # Generate semantic item ID
        item_id = f"postgis-{schema}-{table_name}"

        # Build geometry from extent (bbox)
        bbox = metadata['bbox']
        geometry = {
            'type': 'Polygon',
            'coordinates': [[
                [bbox[0], bbox[1]],  # min_x, min_y
                [bbox[2], bbox[1]],  # max_x, min_y
                [bbox[2], bbox[3]],  # max_x, max_y
                [bbox[0], bbox[3]],  # min_x, max_y
                [bbox[0], bbox[1]]   # close polygon
            ]]
        }

        # Build properties
        properties = {
            'datetime': datetime.now(timezone.utc).isoformat(),
            'postgis:schema': schema,
            'postgis:table': table_name,
            'postgis:row_count': metadata['row_count'],
            'postgis:geometry_types': metadata['geometry_types'],
            'postgis:srid': metadata['srid']
        }

        # Add source file if provided
        if source_file:
            properties['source_file'] = source_file

        # Merge additional properties
        if additional_properties:
            properties.update(additional_properties)

        # Build asset with postgis:// link
        asset_href = f"postgis://{self.config.postgis_host}/{self.config.postgis_database}/{schema}.{table_name}"

        assets = {
            'data': Asset(
                href=asset_href,
                type='application/geo+json',
                title=f'PostGIS Table: {schema}.{table_name}',
                roles=['data'],
                **{'postgis:queryable': True}  # Custom property
            )
        }

        # Build STAC Item dict
        item_dict = {
            'id': item_id,
            'type': 'Feature',
            'stac_version': '1.0.0',
            'collection': collection_id,
            'geometry': geometry,
            'bbox': bbox,
            'properties': properties,
            'assets': assets,
            'links': []
        }

        # Validate with stac-pydantic
        item = Item(**item_dict)

        logger.info(f"✅ STAC Item created: {item_id} ({metadata['row_count']} rows)")

        return item

    def _get_table_metadata(self, schema: str, table_name: str) -> Dict[str, Any]:
        """
        Query PostGIS for table metadata.

        Args:
            schema: Schema name
            table_name: Table name

        Returns:
            Dict with: bbox, row_count, geometry_types, srid, created_at

        Raises:
            psycopg.Error: If table doesn't exist or query fails
        """
        logger.debug(f"Querying metadata for {schema}.{table_name}")

        with psycopg.connect(self.config.postgis_connection_string) as conn:
            with conn.cursor() as cur:
                # Check table exists
                cur.execute(
                    sql.SQL("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        )
                    """),
                    [schema, table_name]
                )
                exists = cur.fetchone()[0]

                if not exists:
                    raise ValueError(f"Table {schema}.{table_name} does not exist")

                # Get geometry column name (assume 'geom' or 'geometry')
                cur.execute(
                    sql.SQL("""
                        SELECT f_geometry_column, srid, type
                        FROM geometry_columns
                        WHERE f_table_schema = %s AND f_table_name = %s
                        LIMIT 1
                    """),
                    [schema, table_name]
                )
                geom_info = cur.fetchone()

                if not geom_info:
                    raise ValueError(f"No geometry column found in {schema}.{table_name}")

                geom_column = geom_info[0]
                srid = geom_info[1]

                # Get table extent (bbox) using ST_Extent
                cur.execute(
                    sql.SQL("""
                        SELECT
                            ST_XMin(extent) as min_x,
                            ST_YMin(extent) as min_y,
                            ST_XMax(extent) as max_x,
                            ST_YMax(extent) as max_y
                        FROM (
                            SELECT ST_Extent({geom_col}::geometry) as extent
                            FROM {schema}.{table}
                        ) subquery
                    """).format(
                        geom_col=sql.Identifier(geom_column),
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    )
                )
                extent = cur.fetchone()
                bbox = [extent[0], extent[1], extent[2], extent[3]]

                # Get row count
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    )
                )
                row_count = cur.fetchone()[0]

                # Get distinct geometry types
                cur.execute(
                    sql.SQL("""
                        SELECT DISTINCT ST_GeometryType({geom_col})
                        FROM {schema}.{table}
                        WHERE {geom_col} IS NOT NULL
                    """).format(
                        geom_col=sql.Identifier(geom_column),
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    )
                )
                geometry_types = [row[0] for row in cur.fetchall()]

                # Get table creation time (if available)
                created_at = None
                try:
                    cur.execute(
                        sql.SQL("""
                            SELECT created_at FROM {schema}.{table}
                            ORDER BY created_at ASC LIMIT 1
                        """).format(
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name)
                        )
                    )
                    result = cur.fetchone()
                    if result:
                        created_at = result[0]
                except psycopg.Error:
                    # Table might not have created_at column
                    pass

                return {
                    'bbox': bbox,
                    'row_count': row_count,
                    'geometry_types': geometry_types,
                    'srid': srid,
                    'geometry_column': geom_column,
                    'created_at': created_at
                }
