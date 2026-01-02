"""
GeoTableBuilder - Standardized Geo Schema Table Creation.

Provides consistent table creation for the `geo` schema with:
    - Standard metadata columns (created_at, updated_at, source tracking)
    - Dynamic attribute columns detected from GeoDataFrame
    - Configurable geometry column name (PostGIS 'geom' vs ArcGIS 'shape')
    - Standard indexes (spatial GIST, attribute B-tree, temporal)
    - Updated_at trigger for automatic timestamp maintenance

Design Philosophy:
    - geo schema tables have UNKNOWN columns at design time
    - Standard metadata columns are ALWAYS present
    - Geometry column name is configurable for ArcGIS compatibility
    - All DDL uses psycopg.sql composition for SQL injection safety

Exports:
    GeoTableBuilder: Builder class for geo schema table DDL generation
"""

from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from psycopg import sql
import geopandas as gpd

from core.schema.ddl_utils import IndexBuilder, TriggerBuilder, CommentBuilder
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "GeoTableBuilder")


class GeometryColumnConfig(Enum):
    """
    Geometry column naming conventions.

    POSTGIS: Standard PostGIS convention ('geom')
    ARCGIS: ArcGIS Enterprise Geodatabase convention ('shape')
    """
    POSTGIS = "geom"
    ARCGIS = "shape"


class GeoTableBuilder:
    """
    Standardized builder for geo schema tables.

    Combines:
    - Standard metadata columns (always present for traceability)
    - Dynamic attribute columns (detected from GeoDataFrame at runtime)
    - Configurable geometry column name (PostGIS vs ArcGIS)
    - Standard indexes and triggers

    Example:
        builder = GeoTableBuilder(geometry_column=GeometryColumnConfig.ARCGIS)
        ddl_statements = builder.create_table_ddl(
            gdf=my_geodataframe,
            table_name='countries',
            schema='geo',
            source_file='countries.shp',
            stac_item_id='countries-2024'
        )
        # Execute statements with cursor
        for stmt in ddl_statements:
            cur.execute(stmt)
    """

    # =========================================================================
    # STANDARD METADATA COLUMNS
    # =========================================================================
    # These columns are added to ALL geo tables for:
    # - Traceability (where did this data come from?)
    # - Auditing (when was it created/modified?)
    # - STAC integration (link to catalog item)
    # =========================================================================

    STANDARD_COLUMNS = {
        # Primary key
        'objectid': 'SERIAL PRIMARY KEY',  # ArcGIS-compatible name (vs 'id')

        # Timestamps for auditing
        'created_at': 'TIMESTAMP WITH TIME ZONE DEFAULT NOW()',
        'updated_at': 'TIMESTAMP WITH TIME ZONE DEFAULT NOW()',

        # Source tracking for data lineage
        'source_file': 'VARCHAR(500)',           # Original filename
        'source_format': 'VARCHAR(50)',          # shp, gpkg, geojson, etc.
        'source_crs': 'VARCHAR(50)',             # Original CRS before reprojection

        # STAC catalog integration
        'stac_item_id': 'VARCHAR(100)',          # Link to STAC item
        'stac_collection_id': 'VARCHAR(100)',    # Link to STAC collection

        # ETL metadata
        'etl_job_id': 'VARCHAR(64)',             # Link to CoreMachine job
        'etl_batch_id': 'VARCHAR(100)',          # Chunk/batch identifier
    }

    # Columns that should NOT be indexed (too wide or not query targets)
    NO_INDEX_COLUMNS = {'source_file', 'source_crs', 'etl_batch_id'}

    # =========================================================================
    # TYPE MAPPING
    # =========================================================================

    PANDAS_TO_POSTGRES = {
        'int': 'INTEGER',
        'int64': 'BIGINT',
        'int32': 'INTEGER',
        'int16': 'SMALLINT',
        'float': 'DOUBLE PRECISION',
        'float64': 'DOUBLE PRECISION',
        'float32': 'REAL',
        'bool': 'BOOLEAN',
        'datetime': 'TIMESTAMP WITH TIME ZONE',
        'datetime64': 'TIMESTAMP WITH TIME ZONE',
        'date': 'DATE',
        'object': 'TEXT',
        'string': 'TEXT',
    }

    def __init__(
        self,
        geometry_column: GeometryColumnConfig = GeometryColumnConfig.POSTGIS,
        srid: int = 4326,
        include_standard_columns: bool = True
    ):
        """
        Initialize GeoTableBuilder.

        Args:
            geometry_column: Geometry column naming convention
                - POSTGIS: 'geom' (default, standard PostGIS)
                - ARCGIS: 'shape' (ArcGIS Enterprise Geodatabase)
            srid: Spatial Reference ID (default 4326 = WGS84)
            include_standard_columns: Include metadata columns (default True)
        """
        self.geometry_column_name = geometry_column.value
        self.srid = srid
        self.include_standard_columns = include_standard_columns

        logger.info(f"🔧 GeoTableBuilder initialized:")
        logger.info(f"   Geometry column: {self.geometry_column_name}")
        logger.info(f"   SRID: {self.srid}")
        logger.info(f"   Standard columns: {self.include_standard_columns}")

    def _get_postgres_type(self, dtype) -> str:
        """
        Map pandas dtype to PostgreSQL type.

        Args:
            dtype: Pandas dtype (can be dtype object or string)

        Returns:
            PostgreSQL type string
        """
        dtype_str = str(dtype).lower()

        # Check for specific type matches
        for pandas_type, pg_type in self.PANDAS_TO_POSTGRES.items():
            if pandas_type in dtype_str:
                return pg_type

        # Default to TEXT for unknown types
        return 'TEXT'

    def _clean_column_name(self, name: str) -> str:
        """
        Clean column name for PostgreSQL compatibility.

        - Lowercase
        - Replace spaces/special chars with underscores
        - Ensure doesn't start with number

        Args:
            name: Original column name

        Returns:
            Cleaned column name
        """
        import re

        # Lowercase and replace problematic characters
        cleaned = name.lower()
        cleaned = re.sub(r'[^a-z0-9_]', '_', cleaned)
        cleaned = re.sub(r'_+', '_', cleaned)  # Collapse multiple underscores
        cleaned = cleaned.strip('_')

        # Ensure doesn't start with number
        if cleaned and cleaned[0].isdigit():
            cleaned = 'col_' + cleaned

        # Handle empty result
        if not cleaned:
            cleaned = 'unnamed_column'

        return cleaned

    def create_table_ddl(
        self,
        gdf: gpd.GeoDataFrame,
        table_name: str,
        schema: str = 'geo',
        source_file: Optional[str] = None,
        source_format: Optional[str] = None,
        source_crs: Optional[str] = None,
        stac_item_id: Optional[str] = None,
        stac_collection_id: Optional[str] = None,
        etl_job_id: Optional[str] = None
    ) -> List[sql.Composed]:
        """
        Generate CREATE TABLE DDL for a geo table.

        Combines:
        1. Standard metadata columns (if enabled)
        2. Geometry column with detected type
        3. Dynamic attribute columns from GeoDataFrame

        Args:
            gdf: GeoDataFrame to detect columns from
            table_name: Target table name
            schema: Target schema (default 'geo')
            source_file: Original filename for tracking
            source_format: File format (shp, gpkg, geojson)
            source_crs: Original CRS before reprojection
            stac_item_id: STAC item ID for catalog linkage
            stac_collection_id: STAC collection ID
            etl_job_id: CoreMachine job ID

        Returns:
            List of sql.Composed statements to execute
        """
        statements = []

        # Detect geometry type from GeoDataFrame
        geom_type = self._detect_geometry_type(gdf)

        logger.info(f"📝 Generating DDL for {schema}.{table_name}")
        logger.info(f"   Geometry type: {geom_type}")
        logger.info(f"   Geometry column: {self.geometry_column_name}")

        # Build column definitions
        column_defs = []

        # 1. Standard metadata columns (if enabled)
        if self.include_standard_columns:
            for col_name, col_type in self.STANDARD_COLUMNS.items():
                column_defs.append(f"{col_name} {col_type}")
            logger.info(f"   Standard columns: {len(self.STANDARD_COLUMNS)}")

        # 2. Geometry column
        geometry_def = f"{self.geometry_column_name} GEOMETRY({geom_type}, {self.srid})"
        column_defs.append(geometry_def)

        # 3. Dynamic attribute columns from GeoDataFrame
        dynamic_columns = []
        for col in gdf.columns:
            # Skip geometry column (handled separately)
            if col == 'geometry':
                continue

            # Skip if column name conflicts with standard columns
            cleaned_name = self._clean_column_name(col)
            if self.include_standard_columns and cleaned_name in self.STANDARD_COLUMNS:
                logger.warning(f"   ⚠️ Skipping column '{col}' - conflicts with standard column")
                continue

            pg_type = self._get_postgres_type(gdf[col].dtype)
            column_defs.append(f"{cleaned_name} {pg_type}")
            dynamic_columns.append(cleaned_name)

        logger.info(f"   Dynamic columns: {len(dynamic_columns)}")

        # Build CREATE TABLE statement
        # Using string composition for column definitions, then wrapping in sql.SQL
        columns_sql = ",\n                ".join(column_defs)

        create_table = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {schema}.{table} (
                {columns}
            )
        """).format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            columns=sql.SQL(columns_sql)
        )

        statements.append(create_table)

        # Add comment on table for documentation using CommentBuilder
        comment = f"Geo table created from {source_file or 'unknown source'}"
        if stac_item_id:
            comment += f", STAC item: {stac_item_id}"
        statements.append(CommentBuilder.table(schema, table_name, comment))

        logger.info(f"✅ Generated CREATE TABLE with {len(column_defs)} columns")

        return statements

    def _detect_geometry_type(self, gdf: gpd.GeoDataFrame) -> str:
        """
        Detect geometry type from GeoDataFrame.

        Promotes to Multi- types for consistency (PostGIS best practice).

        Args:
            gdf: GeoDataFrame to inspect

        Returns:
            PostgreSQL geometry type string (e.g., 'MULTIPOLYGON')
        """
        if len(gdf) == 0:
            logger.warning("Empty GeoDataFrame, defaulting to GEOMETRY")
            return "GEOMETRY"

        # Get unique geometry types
        geom_types = gdf.geometry.geom_type.unique()

        # If already uniform, use that type
        if len(geom_types) == 1:
            geom_type = geom_types[0].upper()
        else:
            # Mixed types - use generic GEOMETRY or most common
            logger.warning(f"Mixed geometry types detected: {geom_types.tolist()}")
            # Promote to Multi- version of the first type
            geom_type = geom_types[0].upper()

        # Promote to Multi- for consistency (PostGIS best practice)
        if not geom_type.startswith('MULTI') and geom_type in ('POINT', 'LINESTRING', 'POLYGON'):
            geom_type = 'MULTI' + geom_type
            logger.info(f"   Promoted to {geom_type} for consistency")

        return geom_type

    def create_indexes_ddl(
        self,
        table_name: str,
        schema: str = 'geo',
        gdf: Optional[gpd.GeoDataFrame] = None,
        index_config: Optional[Dict[str, Any]] = None
    ) -> List[sql.Composed]:
        """
        Generate CREATE INDEX DDL for a geo table.

        Default indexes:
        1. Spatial (GIST) on geometry column - always
        2. B-tree on stac_item_id, stac_collection_id - if standard columns
        3. B-tree on specified attribute columns
        4. B-tree DESC on temporal columns

        Args:
            table_name: Target table name
            schema: Target schema (default 'geo')
            gdf: Optional GeoDataFrame for column validation
            index_config: Optional index configuration:
                - spatial: bool (default True)
                - attributes: list of column names
                - temporal: list of column names for DESC indexes

        Returns:
            List of sql.Composed CREATE INDEX statements
        """
        statements = []
        config = index_config or {}

        logger.info(f"📇 Generating indexes for {schema}.{table_name}")

        # 1. SPATIAL INDEX (GIST on geometry column) - always
        if config.get('spatial', True):
            idx_name = f"idx_{table_name}_{self.geometry_column_name}"
            statements.append(IndexBuilder.gist(schema, table_name, self.geometry_column_name, name=idx_name))
            logger.info(f"   ✅ Spatial index: {idx_name}")

        # 2. STANDARD COLUMN INDEXES (if using standard columns)
        if self.include_standard_columns:
            standard_indexed = ['stac_item_id', 'stac_collection_id', 'etl_job_id', 'created_at']
            for col in standard_indexed:
                if col in self.NO_INDEX_COLUMNS:
                    continue
                idx_name = f"idx_{table_name}_{col}"
                statements.append(IndexBuilder.btree(schema, table_name, col, name=idx_name))
                logger.info(f"   ✅ Standard index: {idx_name}")

        # 3. ATTRIBUTE INDEXES (B-tree on specified columns)
        for col in config.get('attributes', []):
            cleaned_col = self._clean_column_name(col)
            idx_name = f"idx_{table_name}_{cleaned_col}"
            statements.append(IndexBuilder.btree(schema, table_name, cleaned_col, name=idx_name))
            logger.info(f"   ✅ Attribute index: {idx_name}")

        # 4. TEMPORAL INDEXES (B-tree DESC for time-series queries)
        for col in config.get('temporal', []):
            cleaned_col = self._clean_column_name(col)
            idx_name = f"idx_{table_name}_{cleaned_col}_desc"
            statements.append(IndexBuilder.btree(schema, table_name, cleaned_col, name=idx_name, descending=True))
            logger.info(f"   ✅ Temporal index: {idx_name}")

        logger.info(f"✅ Generated {len(statements)} indexes")

        return statements

    def create_trigger_ddl(
        self,
        table_name: str,
        schema: str = 'geo'
    ) -> List[sql.Composed]:
        """
        Generate trigger DDL for automatic updated_at maintenance.

        Creates a trigger that updates the updated_at column on every UPDATE.
        Uses TriggerBuilder from ddl_utils for consistent trigger generation.

        Args:
            table_name: Target table name
            schema: Target schema (default 'geo')

        Returns:
            List of sql.Composed statements for trigger creation
        """
        if not self.include_standard_columns:
            return []  # No trigger needed without standard columns

        # Use TriggerBuilder for consistent trigger generation
        # Returns [CREATE FUNCTION, DROP TRIGGER, CREATE TRIGGER]
        trigger_name = f"trg_{table_name}_updated_at"
        statements = TriggerBuilder.updated_at(schema, table_name)

        logger.info(f"✅ Generated updated_at trigger: {trigger_name}")

        return statements

    def create_complete_ddl(
        self,
        gdf: gpd.GeoDataFrame,
        table_name: str,
        schema: str = 'geo',
        source_file: Optional[str] = None,
        source_format: Optional[str] = None,
        source_crs: Optional[str] = None,
        stac_item_id: Optional[str] = None,
        stac_collection_id: Optional[str] = None,
        etl_job_id: Optional[str] = None,
        index_config: Optional[Dict[str, Any]] = None
    ) -> List[sql.Composed]:
        """
        Generate complete DDL for a geo table (table + indexes + trigger).

        Convenience method that combines:
        1. CREATE TABLE
        2. CREATE INDEX (multiple)
        3. CREATE TRIGGER

        Args:
            gdf: GeoDataFrame to detect columns from
            table_name: Target table name
            schema: Target schema (default 'geo')
            source_file: Original filename for tracking
            source_format: File format (shp, gpkg, geojson)
            source_crs: Original CRS before reprojection
            stac_item_id: STAC item ID for catalog linkage
            stac_collection_id: STAC collection ID
            etl_job_id: CoreMachine job ID
            index_config: Index configuration dict

        Returns:
            List of all sql.Composed DDL statements
        """
        statements = []

        # 1. CREATE TABLE
        statements.extend(self.create_table_ddl(
            gdf=gdf,
            table_name=table_name,
            schema=schema,
            source_file=source_file,
            source_format=source_format,
            source_crs=source_crs,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            etl_job_id=etl_job_id
        ))

        # 2. CREATE INDEXES
        statements.extend(self.create_indexes_ddl(
            table_name=table_name,
            schema=schema,
            gdf=gdf,
            index_config=index_config
        ))

        # 3. CREATE TRIGGER
        statements.extend(self.create_trigger_ddl(
            table_name=table_name,
            schema=schema
        ))

        logger.info(f"✅ Complete DDL generated: {len(statements)} statements for {schema}.{table_name}")

        return statements


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def get_geo_table_builder(
    arcgis_mode: bool = False,
    srid: int = 4326
) -> GeoTableBuilder:
    """
    Factory function to create GeoTableBuilder with appropriate configuration.

    Args:
        arcgis_mode: If True, use ArcGIS-compatible settings ('shape' column)
        srid: Spatial Reference ID (default 4326)

    Returns:
        Configured GeoTableBuilder instance
    """
    config = GeometryColumnConfig.ARCGIS if arcgis_mode else GeometryColumnConfig.POSTGIS
    return GeoTableBuilder(geometry_column=config, srid=srid)
