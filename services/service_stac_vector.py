# ============================================================================
# STAC VECTOR METADATA SERVICE
# ============================================================================
# STATUS: Service layer - STAC metadata extraction from PostGIS tables
# PURPOSE: Extract STAC Item metadata from vector tables stored in PostGIS
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: StacVectorService
# DEPENDENCIES: psycopg, stac-pydantic, shapely
# ============================================================================
"""
STAC Vector Metadata Service.

Extracts STAC Item metadata from PostGIS vector tables.
Validates with stac-pydantic for type safety and STAC spec compliance.

Uses:
    - PostGIS: Geometry extent, bounds, row count, geometry types
    - stac-pydantic: Validation and type safety

Exports:
    StacVectorService: Main service class for vector STAC metadata extraction
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

        # Fetch user-provided metadata from geo.table_metadata (09 DEC 2025)
        # This is the SOURCE OF TRUTH - same data used by OGC Features API
        user_metadata = self._get_user_metadata(table_name)
        if user_metadata:
            # Map to STAC-compliant property names
            if user_metadata.get('title'):
                properties['title'] = user_metadata['title']
            if user_metadata.get('description'):
                properties['description'] = user_metadata['description']
            if user_metadata.get('attribution'):
                properties['attribution'] = user_metadata['attribution']
            if user_metadata.get('license'):
                properties['license'] = user_metadata['license']
            if user_metadata.get('keywords'):
                properties['keywords'] = user_metadata['keywords']
            if user_metadata.get('feature_count'):
                properties['feature_count'] = user_metadata['feature_count']

            # Add temporal extent using STAC datetime convention
            temporal_start = user_metadata.get('temporal_start')
            temporal_end = user_metadata.get('temporal_end')
            if temporal_start or temporal_end:
                # STAC spec: use start_datetime/end_datetime for ranges, datetime=null
                properties['datetime'] = None
                if temporal_start:
                    properties['start_datetime'] = temporal_start
                if temporal_end:
                    properties['end_datetime'] = temporal_end
                if user_metadata.get('temporal_property'):
                    properties['temporal_property'] = user_metadata['temporal_property']

            logger.debug(f"Added user metadata to STAC properties: {list(user_metadata.keys())}")

        # Merge additional properties (after user metadata so ETL props can override)
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

    def _get_user_metadata(self, table_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch user-provided metadata from geo.table_metadata registry.

        This is the SOURCE OF TRUTH for vector metadata. STAC items should
        read from here to stay synchronized with OGC Features API.

        Added: 09 DEC 2025

        Args:
            table_name: Table name (primary key in geo.table_metadata)

        Returns:
            Dict with user-provided metadata fields, or None if not found:
            {
                "title": str,
                "description": str,
                "attribution": str,
                "license": str,
                "keywords": [str],  # Parsed from comma-separated
                "temporal_start": str,  # ISO 8601
                "temporal_end": str,    # ISO 8601
                "temporal_property": str,
                "feature_count": int
            }
        """
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository(target_database=self.target_database)

        try:
            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if geo.table_metadata exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo'
                            AND table_name = 'table_metadata'
                        ) as table_exists
                    """)
                    result = cur.fetchone()
                    if not result or not result.get('table_exists'):
                        logger.debug(f"geo.table_metadata does not exist - skipping user metadata for {table_name}")
                        return None

                    # Query user-provided metadata fields
                    cur.execute("""
                        SELECT
                            title,
                            description,
                            attribution,
                            license,
                            keywords,
                            temporal_start,
                            temporal_end,
                            temporal_property,
                            feature_count
                        FROM geo.table_metadata
                        WHERE table_name = %s
                    """, (table_name,))

                    row = cur.fetchone()
                    if not row:
                        logger.debug(f"No user metadata found in geo.table_metadata for {table_name}")
                        return None

                    # Parse keywords from comma-separated string to list
                    keywords_str = row.get('keywords')
                    keywords_list = None
                    if keywords_str:
                        keywords_list = [k.strip() for k in keywords_str.split(',') if k.strip()]

                    result = {
                        "title": row.get('title'),
                        "description": row.get('description'),
                        "attribution": row.get('attribution'),
                        "license": row.get('license'),
                        "keywords": keywords_list,
                        "temporal_start": row['temporal_start'].isoformat() if row.get('temporal_start') else None,
                        "temporal_end": row['temporal_end'].isoformat() if row.get('temporal_end') else None,
                        "temporal_property": row.get('temporal_property'),
                        "feature_count": row.get('feature_count')
                    }

                    # Remove None values
                    result = {k: v for k, v in result.items() if v is not None}

                    logger.debug(f"Retrieved user metadata for {table_name}: {list(result.keys())}")
                    return result if result else None

        except Exception as e:
            logger.warning(f"Error fetching user metadata for {table_name}: {e}")
            return None

    # _get_countries_for_bbox() REMOVED (25 NOV 2025)
    # ISO3 country attribution now handled by services/iso3_attribution.py
    # Use: from services.iso3_attribution import ISO3AttributionService
    # This eliminates ~175 lines of duplicated code
