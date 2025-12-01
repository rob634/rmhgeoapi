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
# UPDATED: 29 NOV 2025 - Added target_database parameter for dual database support
# DUAL_DATABASE: Vector tables in business db (ddhgeodb), STAC catalog in app db (geopgflex)
# ============================================================================

"""
STAC Vector Metadata Service

Extracts STAC Item metadata from PostGIS vector tables.
Validates with stac-pydantic for type safety and STAC spec compliance.

Strategy: DRY - Leverage PostGIS for spatial operations
- PostGIS: Geometry extent, bounds, row count, geometry types
- stac-pydantic: Validation and type safety
- Our code: Table metadata, custom properties, asset links

"""

from typing import Dict, Any, Optional, List, Literal
from datetime import datetime, timezone
import logging
import psycopg
from psycopg import sql

from stac_pydantic import Item
from stac_pydantic.shared import Asset
from shapely.geometry import box

from config import get_config
from infrastructure.pgstac_bootstrap import PgStacBootstrap
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

    Dual Database Architecture (29 NOV 2025):
        - Vector tables: Default to app database (geopgflex) geo schema
        - STAC catalog: Stored in app database (geopgflex) pgstac schema
        - Business database (ddhgeodb): Available for future dedicated ETL database
    """

    def __init__(self, target_database: Literal["app", "business"] = "app"):
        """
        Initialize STAC vector service.

        Args:
            target_database: Which database contains the vector tables (29 NOV 2025):
                - "app" (default): App database (geopgflex) - ETL vector outputs in geo schema
                - "business": Business database (ddhgeodb) - for future dedicated ETL database

        Note: STAC items are always inserted into app database (pgstac schema).
        """
        self.config = get_config()
        self.stac = PgStacBootstrap()  # Always uses app database for pgstac
        self.target_database = target_database

    def extract_item_from_table(
        self,
        schema: str,
        table_name: str,
        collection_id: str = 'vectors',
        source_file: Optional[str] = None,
        additional_properties: Optional[Dict[str, Any]] = None,
        platform_meta: Optional['PlatformMetadata'] = None,
        app_meta: Optional['AppMetadata'] = None
    ) -> Item:
        """
        Extract STAC Item from PostGIS table.

        Args:
            schema: PostgreSQL schema name (e.g., 'geo')
            table_name: Table name in schema
            collection_id: STAC collection ID (default: 'vectors')
            source_file: Optional source file path (e.g., blob name)
            additional_properties: Optional custom properties to add
            platform_meta: Optional PlatformMetadata for DDH identifiers (25 NOV 2025)
            app_meta: Optional AppMetadata for job linkage (25 NOV 2025)

        Returns:
            Validated stac-pydantic Item

        Raises:
            ValidationError: If extracted metadata fails STAC validation
            psycopg.Error: If table doesn't exist or query fails

        Strategy:
            1. Query PostGIS for table extent and metadata
            2. Extract geometry types and row count
            3. Build STAC Item with postgis:// asset link
            4. Add platform/app/geo metadata via STACMetadataHelper (25 NOV 2025)
            5. Validate with stac-pydantic
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

        # Add metadata via STACMetadataHelper (25 NOV 2025)
        # Adds: platform:*, app:*, geo:* properties
        # Note: Vector items don't need TiTiler COG links (they're PostGIS tables)
        try:
            logger.debug(f"Adding metadata via STACMetadataHelper for {schema}.{table_name}...")
            from services.stac_metadata_helper import STACMetadataHelper

            metadata_helper = STACMetadataHelper()

            # Build temporary item dict for enrichment
            temp_item = {'properties': properties, 'bbox': bbox}
            temp_item = metadata_helper.augment_item(
                item_dict=temp_item,
                bbox=bbox,
                platform=platform_meta,
                app=app_meta,
                include_iso3=True,
                include_titiler=False  # Vector items don't need TiTiler COG links
            )
            # Merge enriched properties back
            properties.update(temp_item.get('properties', {}))
            logger.debug("Metadata enrichment complete (platform, app, geo)")
        except Exception as e:
            # Non-fatal: Log warning but continue - STAC item can exist without enrichment
            logger.warning(f"Metadata enrichment failed (non-fatal): {e}")

        # Build asset with postgis:// link (29 NOV 2025: use correct database based on target)
        if self.target_database == "business" and self.config.is_business_database_configured():
            db_host = self.config.business_database.host
            db_name = self.config.business_database.database
        else:
            db_host = self.config.postgis_host
            db_name = self.config.postgis_database
        asset_href = f"postgis://{db_host}/{db_name}/{schema}.{table_name}"

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

        # Use PostgreSQLRepository for managed identity support (18 NOV 2025)
        # Note: Removed dead code calling get_postgres_connection_string() - 24 NOV 2025
        # Use target_database to route to correct database (29 NOV 2025)
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository(target_database=self.target_database)
        logger.debug(f"Using target_database={self.target_database} for table metadata query")

        with repo._get_connection() as conn:
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
                result = cur.fetchone()
                exists = result['exists']

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

                geom_column = geom_info['f_geometry_column']
                srid = geom_info['srid']

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
                bbox = [extent['min_x'], extent['min_y'], extent['max_x'], extent['max_y']]

                # Get row count
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    )
                )
                result = cur.fetchone()
                row_count = result['count']

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
                geometry_types = [row['st_geometrytype'] for row in cur.fetchall()]

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

    # _get_countries_for_bbox() REMOVED (25 NOV 2025)
    # ISO3 country attribution now handled by services/iso3_attribution.py
    # Use: from services.iso3_attribution import ISO3AttributionService
    # This eliminates ~175 lines of duplicated code
