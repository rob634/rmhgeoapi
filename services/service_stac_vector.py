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
    """

    def __init__(self):
        """Initialize STAC vector service."""
        self.config = get_config()
        self.stac = PgStacBootstrap()

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

        # Add ISO3 country attribution (22 NOV 2025)
        # Uses PostGIS spatial query against geo.system_admin0_boundaries
        try:
            logger.debug(f"Adding ISO3 country attribution for {schema}.{table_name}...")
            country_info = self._get_countries_for_bbox(bbox)

            if country_info['available']:
                if country_info['primary_iso3']:
                    properties['geo:primary_iso3'] = country_info['primary_iso3']
                    logger.debug(f"   Set geo:primary_iso3={country_info['primary_iso3']}")

                if country_info['iso3_codes']:
                    properties['geo:iso3'] = country_info['iso3_codes']
                    logger.debug(f"   Set geo:iso3={country_info['iso3_codes']}")

                if country_info['countries']:
                    properties['geo:countries'] = country_info['countries']
                    logger.debug(f"   Set geo:countries={country_info['countries']}")

                if country_info['attribution_method']:
                    properties['geo:attribution_method'] = country_info['attribution_method']

                logger.debug(f"Country attribution added ({country_info['attribution_method']})")
            else:
                logger.debug("Country attribution unavailable (admin0 table not ready)")
        except Exception as e:
            # Non-fatal: Log warning but continue - STAC item can exist without country codes
            logger.warning(f"Country attribution failed (non-fatal): {e}")

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

        from config import get_postgres_connection_string

        connection_string = get_postgres_connection_string()

        # Use PostgreSQLRepository for managed identity support (18 NOV 2025)
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository()

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

    def _get_countries_for_bbox(self, bbox: list) -> Dict[str, Any]:
        """
        Get ISO3 country codes for geometries intersecting the bounding box.

        Uses PostGIS spatial query against geo.system_admin0_boundaries table
        configured in config.h3.system_admin0_table.

        Args:
            bbox: Bounding box [minx, miny, maxx, maxy] in EPSG:4326

        Returns:
            Dict with:
                - iso3_codes: List of ISO3 codes for intersecting countries
                - primary_iso3: ISO3 code for country containing bbox centroid
                - countries: List of country names
                - attribution_method: 'centroid' or 'first_intersect'
                - available: bool indicating if attribution was successful

        Note:
            Returns available=False if admin0 table is not populated or query fails.
            This is a graceful degradation - STAC items can be created without country codes.
        """
        import traceback
        from infrastructure.postgresql import PostgreSQLRepository

        if not bbox or len(bbox) != 4:
            logger.warning(f"Invalid bbox for country attribution: {bbox}")
            return {
                'iso3_codes': [],
                'primary_iso3': None,
                'countries': [],
                'attribution_method': None,
                'available': False
            }

        try:
            admin0_table = self.config.h3.system_admin0_table  # "geo.system_admin0_boundaries"

            # Parse schema.table
            if '.' in admin0_table:
                schema, table = admin0_table.split('.', 1)
            else:
                schema, table = 'geo', admin0_table

            repo = PostgreSQLRepository()

            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # First check if table exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        ) as table_exists
                    """, (schema, table))
                    if not cur.fetchone()['table_exists']:
                        logger.debug(f"Admin0 table {admin0_table} not found - skipping country attribution")
                        return {
                            'iso3_codes': [],
                            'primary_iso3': None,
                            'countries': [],
                            'attribution_method': None,
                            'available': False
                        }

                    # Check for required columns
                    cur.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        AND column_name IN ('iso3', 'name_en', 'geom', 'geometry')
                    """, (schema, table))
                    columns = [row['column_name'] for row in cur.fetchall()]

                    if 'iso3' not in columns:
                        logger.warning(f"Admin0 table missing 'iso3' column - skipping country attribution")
                        return {
                            'iso3_codes': [],
                            'primary_iso3': None,
                            'countries': [],
                            'attribution_method': None,
                            'available': False
                        }

                    # Determine geometry column name
                    geom_col = 'geom' if 'geom' in columns else 'geometry' if 'geometry' in columns else None
                    if not geom_col:
                        logger.warning(f"Admin0 table missing geometry column - skipping country attribution")
                        return {
                            'iso3_codes': [],
                            'primary_iso3': None,
                            'countries': [],
                            'attribution_method': None,
                            'available': False
                        }

                    # Determine name column
                    name_col = 'name_en' if 'name_en' in columns else 'name' if 'name' in columns else None

                    minx, miny, maxx, maxy = bbox

                    # Query 1: Get all intersecting countries
                    name_select = f", {name_col}" if name_col else ""
                    intersect_query = f"""
                        SELECT iso3{name_select}
                        FROM {schema}.{table}
                        WHERE ST_Intersects(
                            {geom_col},
                            ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                        )
                        ORDER BY iso3
                    """
                    cur.execute(intersect_query, (minx, miny, maxx, maxy))
                    results = cur.fetchall()

                    if not results:
                        logger.debug(f"No countries found for bbox {bbox} - may be in ocean")
                        return {
                            'iso3_codes': [],
                            'primary_iso3': None,
                            'countries': [],
                            'attribution_method': None,
                            'available': True
                        }

                    iso3_codes = [row['iso3'] for row in results if row['iso3']]
                    countries = [row.get(name_col, '') for row in results if name_col and row.get(name_col)] if name_col else []

                    # Query 2: Get primary country (centroid method)
                    centroid_x = (minx + maxx) / 2
                    centroid_y = (miny + maxy) / 2

                    centroid_query = f"""
                        SELECT iso3
                        FROM {schema}.{table}
                        WHERE ST_Contains(
                            {geom_col},
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                        )
                        LIMIT 1
                    """
                    cur.execute(centroid_query, (centroid_x, centroid_y))
                    centroid_result = cur.fetchone()

                    primary_iso3 = None
                    attribution_method = None

                    if centroid_result and centroid_result['iso3']:
                        primary_iso3 = centroid_result['iso3']
                        attribution_method = 'centroid'
                    elif iso3_codes:
                        primary_iso3 = iso3_codes[0]
                        attribution_method = 'first_intersect'

                    logger.debug(
                        f"Country attribution: {len(iso3_codes)} countries, "
                        f"primary={primary_iso3} ({attribution_method})"
                    )

                    return {
                        'iso3_codes': iso3_codes,
                        'primary_iso3': primary_iso3,
                        'countries': countries,
                        'attribution_method': attribution_method,
                        'available': True
                    }

        except Exception as e:
            logger.warning(f"Country attribution failed (non-fatal): {e}")
            logger.debug(f"Traceback:\n{traceback.format_exc()}")
            return {
                'iso3_codes': [],
                'primary_iso3': None,
                'countries': [],
                'attribution_method': None,
                'available': False
            }
