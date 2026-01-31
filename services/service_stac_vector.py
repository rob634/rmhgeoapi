# ============================================================================
# STAC VECTOR METADATA SERVICE
# ============================================================================
# STATUS: Service layer - STAC metadata extraction from PostGIS tables
# PURPOSE: Extract STAC Item metadata from vector tables stored in PostGIS
# LAST_REVIEWED: 09 JAN 2026
# REVIEW_STATUS: F7.8 Unified Metadata integration complete
# EXPORTS: StacVectorService
# DEPENDENCIES: psycopg, stac-pydantic, shapely, core.models.unified_metadata
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
from core.models.unified_metadata import VectorMetadata

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
        app_meta: Optional['AppMetadata'] = None,
        item_id: Optional[str] = None
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
            item_id: Optional custom STAC item ID (30 JAN 2026 - DDH format support)
                     If not provided, falls back to 'postgis-{schema}-{table_name}'

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

        # Use provided item_id or fall back to legacy format (30 JAN 2026)
        if item_id:
            logger.info(f"  Using provided item_id: {item_id}")
        else:
            item_id = f"postgis-{schema}-{table_name}"
            logger.info(f"  Using auto-generated item_id: {item_id}")

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

        # =====================================================================
        # F7.8: Fetch VectorMetadata from geo.table_metadata (09 JAN 2026)
        # This is the SOURCE OF TRUTH - same data used by OGC Features API
        # =====================================================================
        vector_metadata = self._get_vector_metadata(table_name)
        if vector_metadata:
            # Map VectorMetadata properties to STAC-compliant property names
            if vector_metadata.title:
                properties['title'] = vector_metadata.title
            if vector_metadata.description:
                properties['description'] = vector_metadata.description
            if vector_metadata.license:
                properties['license'] = vector_metadata.license
            if vector_metadata.keywords:
                properties['keywords'] = vector_metadata.keywords
            if vector_metadata.feature_count:
                properties['feature_count'] = vector_metadata.feature_count

            # Attribution from providers or legacy field
            attribution = vector_metadata.get_attribution() or vector_metadata.attribution
            if attribution:
                properties['attribution'] = attribution

            # Providers (STAC standard)
            if vector_metadata.providers:
                properties['providers'] = [p.to_stac_dict() for p in vector_metadata.providers]

            # Scientific metadata
            if vector_metadata.sci_doi:
                properties['sci:doi'] = vector_metadata.sci_doi
            if vector_metadata.sci_citation:
                properties['sci:citation'] = vector_metadata.sci_citation

            # Add temporal extent using STAC datetime convention
            if vector_metadata.extent and vector_metadata.extent.temporal:
                interval = vector_metadata.extent.temporal.interval
                if interval and interval[0]:
                    temporal_start, temporal_end = interval[0]
                    if temporal_start or temporal_end:
                        # STAC spec: use start_datetime/end_datetime for ranges, datetime=null
                        properties['datetime'] = None
                        if temporal_start:
                            properties['start_datetime'] = temporal_start
                        if temporal_end:
                            properties['end_datetime'] = temporal_end
                        if vector_metadata.temporal_property:
                            properties['temporal_property'] = vector_metadata.temporal_property

            logger.debug(f"Added VectorMetadata to STAC properties (F7.8)")

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

        # Build asset with postgis:// link (07 JAN 2026: use correct database based on target)
        if self.target_database == "public" and self.config.is_public_database_configured():
            db_host = self.config.public_database.host
            db_name = self.config.public_database.database
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

        # Build STAC Item links (28 JAN 2026 - OGC_STAC_APP_URL removed)
        # - STAC links use the STAC API base URL (ETL Function App)
        # - OGC Features link uses TiPG only (no fallback)
        stac_base_url = self.config.stac_api_base_url.rstrip('/')
        tipg_base_url = self.config.tipg_base_url

        # TiPG requires schema-qualified table names (14 JAN 2026)
        tipg_collection_id = f"{schema}.{table_name}"

        links = [
            {
                'rel': 'self',
                'href': f"{stac_base_url}/collections/{collection_id}/items/{item_id}",
                'type': 'application/geo+json',
                'title': f'STAC Item {item_id}'
            },
            {
                'rel': 'collection',
                'href': f"{stac_base_url}/collections/{collection_id}",
                'type': 'application/json',
                'title': f'Collection {collection_id}'
            },
            {
                'rel': 'http://www.opengis.net/def/rel/ogc/1.0/items',
                'href': f"{tipg_base_url}/collections/{tipg_collection_id}/items",
                'type': 'application/geo+json',
                'title': 'OGC Features API (TiPG)'
            }
        ]

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
            'links': links
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

    def _get_vector_metadata(self, table_name: str) -> Optional[VectorMetadata]:
        """
        Fetch VectorMetadata from geo.table_catalog registry.

        NOTE (21 JAN 2026): Queries geo.table_catalog (SERVICE LAYER) only.
        ETL internal fields (etl_job_id, source_file, etc.) are stored in
        app.vector_etl_tracking and are NOT returned (separation of concerns).

        This is the SOURCE OF TRUTH for service layer metadata. STAC items should
        read from here to stay synchronized with OGC Features API.

        Args:
            table_name: Table name (primary key in geo.table_catalog)

        Returns:
            VectorMetadata model (with ETL fields = None), or None if not found
        """
        from infrastructure.postgresql import PostgreSQLRepository
        repo = PostgreSQLRepository(target_database=self.target_database)

        try:
            with repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if geo.table_catalog exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'geo'
                            AND table_name = 'table_catalog'
                        ) as table_exists
                    """)
                    result = cur.fetchone()
                    if not result or not result.get('table_exists'):
                        logger.debug(f"geo.table_catalog does not exist - skipping metadata for {table_name}")
                        return None

                    # Query SERVICE LAYER metadata only from geo.table_catalog
                    # ETL fields are in app.vector_etl_tracking (not queried here)
                    cur.execute("""
                        SELECT
                            table_name,
                            schema_name,
                            title,
                            description,
                            attribution,
                            license,
                            keywords,
                            temporal_start,
                            temporal_end,
                            temporal_property,
                            feature_count,
                            geometry_type,
                            stac_item_id,
                            stac_collection_id,
                            created_at,
                            updated_at,
                            bbox_minx,
                            bbox_miny,
                            bbox_maxx,
                            bbox_maxy,
                            providers,
                            stac_extensions,
                            sci_doi,
                            sci_citation,
                            custom_properties,
                            srid,
                            primary_geometry
                        FROM geo.table_catalog
                        WHERE table_name = %s
                    """, (table_name,))

                    row = cur.fetchone()
                    if not row:
                        logger.debug(f"No metadata found in geo.table_catalog for {table_name}")
                        return None

                    # Convert row to VectorMetadata using service catalog factory
                    # ETL fields will be None (intentional - separation of concerns)
                    vector_metadata = VectorMetadata.from_service_catalog(dict(row))
                    logger.debug(f"Retrieved VectorMetadata for {table_name} from table_catalog")
                    return vector_metadata

        except Exception as e:
            logger.warning(f"Error fetching VectorMetadata for {table_name}: {e}")
            return None

    # _get_countries_for_bbox() REMOVED (25 NOV 2025)
    # ISO3 country attribution now handled by services/iso3_attribution.py
    # Use: from services.iso3_attribution import ISO3AttributionService
    # This eliminates ~175 lines of duplicated code
