"""
Vector to PostGIS Handler.

Handles the complete workflow of preparing and uploading vector data to PostGIS:
    1. prepare_gdf: Validate geometries, reproject to EPSG:4326, clean column names
    2. chunk_gdf: Split large GeoDataFrames for parallel processing
    3. upload_chunk: Create table and insert features into PostGIS geo schema

Exports:
    VectorToPostGISHandler: Main handler class for PostGIS vector operations
"""

from typing import List, Dict, Any, Literal
import logging
import geopandas as gpd
import pandas as pd
import psycopg
from psycopg import sql
from config import get_config
from util_logger import LoggerFactory, ComponentType

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "postgis_handler"
)


class VectorToPostGISHandler:
    """Handles GeoDataFrame → PostGIS operations."""

    def __init__(self, target_database: Literal["app", "business"] = "app"):
        """
        Initialize with PostgreSQL repository for managed identity support.

        Args:
            target_database: Which database to connect to (29 NOV 2025):
                - "app" (default): App database (geopgflex) - geo schema for ETL outputs
                - "business": Business database (ddhgeodb) - for future dedicated ETL database

                Default is "app" to maintain backward compatibility with existing behavior.
        """
        from infrastructure.postgresql import PostgreSQLRepository

        config = get_config()
        # Use PostgreSQLRepository with target_database for dual database support (29 NOV 2025)
        self._pg_repo = PostgreSQLRepository(target_database=target_database)
        self.target_database = target_database
        # Keep conn_string for backward compatibility (deprecated)
        self.conn_string = self._pg_repo.conn_string

        # Log which database we're using
        if target_database == "business" and config.is_business_database_configured():
            logger.info(f"📊 VectorToPostGISHandler: Using BUSINESS database ({config.business_database.database})")
        else:
            logger.info(f"📊 VectorToPostGISHandler: Using APP database (fallback or explicit)")

    def prepare_gdf(self, gdf: gpd.GeoDataFrame, geometry_params: dict = None) -> gpd.GeoDataFrame:
        """
        Validate, reproject, clean, and optionally process GeoDataFrame geometries.

        Operations:
        1. Remove null geometries
        2. Fix invalid geometries (buffer(0) trick)
        3. Reproject to EPSG:4326 if needed
        4. Clean column names (lowercase, replace spaces with underscores)
        5. Remove geometry column from attributes
        6. Apply geometry processing (simplification, quantization) if requested

        Args:
            gdf: Input GeoDataFrame
            geometry_params: Optional geometry processing settings:
                - simplify: dict with tolerance, preserve_topology
                - quantize: dict with snap_to_grid

        Returns:
            Cleaned and validated GeoDataFrame

        Raises:
            ValueError: If GeoDataFrame has no valid geometries
        """
        # Remove null geometries with detailed diagnostics
        original_count = len(gdf)
        null_mask = gdf.geometry.isna()
        null_count = null_mask.sum()

        logger.info(f"📊 Geometry validation starting:")
        logger.info(f"   - Total features loaded: {original_count}")
        logger.info(f"   - Null geometries found: {null_count}")

        if null_count > 0:
            # Sample some null geometry rows to see what data exists
            null_samples = gdf[null_mask].head(5)
            logger.warning(f"   - Sample rows with null geometries (first 5):")
            for idx, row in null_samples.iterrows():
                # Show non-geometry columns to help diagnose data issues
                non_geom_cols = [col for col in gdf.columns if col != 'geometry']
                sample_data = {col: row[col] for col in non_geom_cols[:3]}  # First 3 columns
                logger.warning(f"      Row {idx}: {sample_data}")

        gdf = gdf[~null_mask].copy()

        if len(gdf) == 0:
            error_msg = (
                f"❌ GeoDataFrame has no valid geometries after removing nulls\n"
                f"   - Original feature count: {original_count}\n"
                f"   - Null geometries: {null_count} (100%)\n"
                f"   - Valid geometries remaining: 0\n"
                f"   - This typically indicates:\n"
                f"     1. Corrupted shapefile (geometry column empty)\n"
                f"     2. Incompatible format (not a spatial file)\n"
                f"     3. Invalid layer selected in GeoPackage\n"
                f"     4. File extraction failed (ZIP issues)"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        if len(gdf) < original_count:
            removed = original_count - len(gdf)
            logger.warning(f"   - ⚠️  Removed {removed} null geometries ({removed/original_count*100:.1f}%)")
            logger.info(f"   - ✅ Valid geometries remaining: {len(gdf)}")

        # Fix invalid geometries
        invalid_mask = ~gdf.geometry.is_valid
        invalid_count = invalid_mask.sum()
        if invalid_count > 0:
            logger.warning(f"Fixing {invalid_count} invalid geometries using buffer(0)")
            gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].buffer(0)

        # ========================================================================
        # FORCE 2D GEOMETRIES - Remove Z and M dimensions
        # ========================================================================
        # This system only supports 2D geometries. KML/KMZ files often contain
        # 3D (Z) or measured (M) coordinates which must be stripped.
        #
        # Shapely's force_2d() removes both Z and M dimensions:
        # - Point(x, y, z) → Point(x, y)
        # - LineString with Z → LineString without Z
        # - Polygon with Z → Polygon without Z
        # ========================================================================
        from shapely import force_2d

        # Check if any geometries have Z or M dimensions
        has_z = gdf.geometry.has_z.any()
        has_m = gdf.geometry.has_m.any() if hasattr(gdf.geometry, 'has_m') else False

        if has_z or has_m:
            dims = []
            if has_z:
                dims.append('Z')
            if has_m:
                dims.append('M')
            logger.info(f"⚠️  Detected {'/'.join(dims)} dimension(s) in geometries - forcing to 2D")

            # Force 2D and rebuild GeoDataFrame to ensure geometry column has no Z/M
            crs_before = gdf.crs
            geoms_2d = gdf.geometry.apply(force_2d)

            # Recreate GeoDataFrame with 2D geometries only
            # This ensures the geometry column metadata is correct
            gdf = gpd.GeoDataFrame(
                gdf.drop(columns=['geometry']),
                geometry=geoms_2d,
                crs=crs_before
            )

            logger.info(f"✅ Successfully converted all geometries to 2D and rebuilt GeoDataFrame")

        # Normalize to Multi- geometry types for ArcGIS compatibility
        # This ensures uniform geometry types in PostGIS tables
        from shapely.geometry import MultiPolygon, MultiLineString, MultiPoint

        def to_multi(geom):
            """
            Convert single-part geometries to Multi- variants.

            Polygon → MultiPolygon([polygon])
            LineString → MultiLineString([linestring])
            Point → MultiPoint([point])
            Multi-* → unchanged
            """
            geom_type = geom.geom_type

            if geom_type == 'Polygon':
                return MultiPolygon([geom])
            elif geom_type == 'LineString':
                return MultiLineString([geom])
            elif geom_type == 'Point':
                return MultiPoint([geom])
            else:
                # Already Multi- or GeometryCollection - unchanged
                return geom

        # Log geometry type distribution before normalization
        type_counts = gdf.geometry.geom_type.value_counts().to_dict()
        logger.info(f"Geometry types before normalization: {type_counts}")

        # Normalize all geometries
        gdf['geometry'] = gdf.geometry.apply(to_multi)

        # Log after normalization
        type_counts_after = gdf.geometry.geom_type.value_counts().to_dict()
        logger.info(f"Geometry types after normalization: {type_counts_after}")

        # ========================================================================
        # VALIDATE POSTGIS GEOMETRY TYPE SUPPORT (12 NOV 2025)
        # ========================================================================
        # PostGIS CREATE TABLE only supports specific geometry types.
        # GEOMETRYCOLLECTION and other complex types must be filtered out.
        # This validation prevents wasted processing and provides clear user guidance.
        # ========================================================================
        SUPPORTED_GEOM_TYPES = {
            'MultiPoint', 'MultiLineString', 'MultiPolygon',
            'Point', 'LineString', 'Polygon'  # Should be rare after normalization
        }

        unique_types = set(gdf.geometry.geom_type.unique())
        unsupported = unique_types - SUPPORTED_GEOM_TYPES

        if unsupported:
            error_msg = (
                f"❌ Unsupported geometry types detected: {', '.join(unsupported)}\n"
                f"   PostGIS CREATE TABLE supports: {', '.join(sorted(SUPPORTED_GEOM_TYPES))}\n"
                f"   \n"
                f"   Common causes:\n"
                f"   - GeometryCollection in source file (mixed geometry types)\n"
                f"   - Complex KML with multiple geometry types per feature\n"
                f"   - GeoJSON FeatureCollection with mixed types\n"
                f"   \n"
                f"   Solutions:\n"
                f"   1. Explode GeometryCollections to single-type features in QGIS/ArcGIS\n"
                f"   2. Filter source data to single geometry type (polygons only, lines only, etc.)\n"
                f"   3. Split source file into multiple files by geometry type\n"
                f"   \n"
                f"   Affected features: {sum(gdf.geometry.geom_type.isin(unsupported))} of {len(gdf)}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        logger.info(f"✅ All geometry types supported by PostGIS: {unique_types}")

        # Reproject to EPSG:4326 if needed
        if gdf.crs and gdf.crs != "EPSG:4326":
            logger.info(f"Reprojecting from {gdf.crs} to EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")
        elif not gdf.crs:
            logger.warning("No CRS defined, assuming EPSG:4326")
            gdf = gdf.set_crs("EPSG:4326")

        # Clean column names (lowercase, replace spaces/special chars)
        gdf.columns = [
            col.lower()
            .replace(' ', '_')
            .replace('-', '_')
            .replace('.', '_')
            .replace('(', '')
            .replace(')', '')
            for col in gdf.columns
        ]

        # ========================================================================
        # GEOMETRY PROCESSING - Simplification & Quantization (Phase 2 - 9 NOV 2025)
        # ========================================================================
        # Apply optional geometry processing for generalized tables
        # Used for creating web-optimized versions with reduced vertex counts
        # ========================================================================
        if geometry_params:
            # Simplification (Douglas-Peucker algorithm)
            if geometry_params.get("simplify"):
                simplify = geometry_params["simplify"]
                tolerance = simplify.get("tolerance", 0.001)  # Default: ~111m at equator
                preserve_topology = simplify.get("preserve_topology", True)

                logger.info(f"🔧 SIMPLIFICATION: tolerance={tolerance}, preserve_topology={preserve_topology}")

                # Count vertices before simplification
                def _count_vertices(geom):
                    """Count total vertices in any geometry type."""
                    geom_type = geom.geom_type

                    if geom_type in ('Point', 'LineString'):
                        return len(geom.coords)
                    elif geom_type == 'Polygon':
                        total = len(geom.exterior.coords)
                        total += sum(len(interior.coords) for interior in geom.interiors)
                        return total
                    elif geom_type in ('MultiPoint', 'MultiLineString', 'MultiPolygon', 'GeometryCollection'):
                        return sum(_count_vertices(g) for g in geom.geoms)
                    return 0

                vertices_before = gdf.geometry.apply(_count_vertices).sum()

                # Apply simplification
                gdf['geometry'] = gdf.geometry.simplify(tolerance, preserve_topology=preserve_topology)

                # Count vertices after
                vertices_after = gdf.geometry.apply(_count_vertices).sum()
                reduction = (1 - vertices_after / vertices_before) * 100 if vertices_before > 0 else 0

                logger.info(f"✅ Simplified: {vertices_before:,} → {vertices_after:,} vertices ({reduction:.1f}% reduction)")

            # Quantization (coordinate precision reduction)
            if geometry_params.get("quantize"):
                quantize = geometry_params["quantize"]
                snap_to_grid = quantize.get("snap_to_grid", 0.0001)  # Default: ~11m precision

                logger.info(f"📐 QUANTIZATION: snap_to_grid={snap_to_grid}")

                try:
                    from shapely import set_precision

                    # Set coordinate precision (Shapely 2.0+)
                    gdf['geometry'] = gdf.geometry.apply(lambda g: set_precision(g, grid_size=snap_to_grid))

                    logger.info(f"✅ Quantized coordinates to grid: {snap_to_grid}")

                except ImportError:
                    logger.warning("⚠️  Shapely 2.0+ required for quantization - skipping (install: pip install shapely>=2.0)")

        return gdf

    def calculate_optimal_chunk_size(self, gdf: gpd.GeoDataFrame) -> int:
        """
        Calculate optimal chunk size based on data characteristics.

        Considers:
        - Number of columns (more columns = smaller chunks)
        - Column types (text/geometry = smaller chunks, numeric = larger)
        - Geometry complexity (points vs polygons)
        - Target memory footprint (~10-50MB per chunk)

        Args:
            gdf: GeoDataFrame to analyze

        Returns:
            Optimal chunk size (rows per chunk)
        """
        # Base chunk size
        base_size = 1000

        # Factor 1: Column count
        # More columns = more data per row = smaller chunks
        num_cols = len(gdf.columns) - 1  # Exclude geometry column
        if num_cols > 50:
            col_factor = 0.3
        elif num_cols > 20:
            col_factor = 0.5
        elif num_cols > 10:
            col_factor = 0.7
        else:
            col_factor = 1.0

        # Factor 2: Column types
        # Text columns use more memory than numeric
        text_cols = sum(1 for col in gdf.columns
                       if col != 'geometry' and gdf[col].dtype == 'object')
        numeric_cols = num_cols - text_cols

        if text_cols > numeric_cols:
            type_factor = 0.6  # Mostly text = smaller chunks
        elif text_cols > 0:
            type_factor = 0.8  # Mixed = moderate chunks
        else:
            type_factor = 1.0  # All numeric = larger chunks

        # Factor 3: Geometry complexity
        # Sample first 100 geometries to determine complexity
        sample_size = min(100, len(gdf))
        sample_geoms = gdf.geometry.iloc[:sample_size]

        # Average number of coordinates per geometry
        def _count_coords(geom):
            """
            Count coordinates in any geometry type safely.

            Handles single-part (Point, LineString, Polygon) and
            multi-part (MultiPoint, MultiLineString, MultiPolygon) geometries.
            """
            geom_type = geom.geom_type

            if geom_type in ['Point', 'LineString']:
                return len(geom.coords)
            elif geom_type == 'Polygon':
                return len(geom.exterior.coords)
            elif geom_type in ['MultiPoint', 'MultiLineString', 'MultiPolygon', 'GeometryCollection']:
                # Multi-part geometries - recursively count coords from all parts
                return sum(_count_coords(part) for part in geom.geoms)
            else:
                return 10  # Default for unknown geometry types

        avg_coords = sample_geoms.apply(_count_coords).mean()

        if avg_coords > 1000:
            geom_factor = 0.3  # Complex polygons
        elif avg_coords > 100:
            geom_factor = 0.5  # Moderate complexity
        elif avg_coords > 10:
            geom_factor = 0.8  # Simple polygons/lines
        else:
            geom_factor = 1.0  # Points

        # Calculate optimal chunk size
        optimal_size = int(base_size * col_factor * type_factor * geom_factor)

        # Enforce bounds (minimum 100, maximum 5000)
        optimal_size = max(100, min(5000, optimal_size))

        logger.info(f"Calculated optimal chunk size: {optimal_size} rows")
        logger.info(f"  Factors: columns={col_factor:.1f}, types={type_factor:.1f}, geometry={geom_factor:.1f}")

        return optimal_size

    def chunk_gdf(self, gdf: gpd.GeoDataFrame, chunk_size: int = None) -> List[gpd.GeoDataFrame]:
        """
        Split GeoDataFrame into chunks for parallel upload.

        If chunk_size not provided, automatically calculates optimal size based on:
        - Column count and types
        - Geometry complexity
        - Memory considerations

        Args:
            gdf: GeoDataFrame to split
            chunk_size: Rows per chunk (default: None, auto-calculate)

        Returns:
            List of GeoDataFrame chunks
        """
        # Auto-calculate if not provided
        if chunk_size is None:
            chunk_size = self.calculate_optimal_chunk_size(gdf)

        chunks = []
        for i in range(0, len(gdf), chunk_size):
            chunk = gdf.iloc[i:i + chunk_size].copy()
            chunks.append(chunk)

        logger.info(f"Split GeoDataFrame into {len(chunks)} chunks of up to {chunk_size} rows")
        return chunks

    def upload_chunk(self, chunk: gpd.GeoDataFrame, table_name: str, schema: str = "geo"):
        """
        Upload GeoDataFrame chunk to PostGIS using psycopg.

        Creates table if it doesn't exist, then inserts features.
        Uses COPY for efficient bulk inserts.

        Args:
            chunk: GeoDataFrame chunk to upload
            table_name: Target table name
            schema: Target schema (default: 'geo')

        Raises:
            psycopg.Error: If database operation fails
        """
        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Create table if not exists
                self._create_table_if_not_exists(cur, chunk, table_name, schema)

                # Insert features
                self._insert_features(cur, chunk, table_name, schema)

                conn.commit()
                logger.info(f"Uploaded {len(chunk)} rows to {schema}.{table_name}")

    def create_table_only(self, chunk: gpd.GeoDataFrame, table_name: str, schema: str = "geo", indexes: dict = None):
        """
        Create PostGIS table without inserting data (DDL only).

        Used for serialized table creation in Stage 1 aggregation to avoid
        PostgreSQL deadlocks during parallel inserts in Stage 2.

        Args:
            chunk: Sample GeoDataFrame for schema detection (first chunk recommended)
            table_name: Target table name
            schema: Target schema (default: 'geo')
            indexes: Index configuration dict with keys:
                - spatial: bool (default True)
                - attributes: list of column names for B-tree indexes
                - temporal: list of column names for DESC B-tree indexes

        Raises:
            psycopg.Error: If table creation fails
        """
        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                self._create_table_if_not_exists(cur, chunk, table_name, schema, indexes)
                conn.commit()
                logger.info(f"Created table {schema}.{table_name} (DDL only, no data inserted)")

    def insert_features_only(self, chunk: gpd.GeoDataFrame, table_name: str, schema: str = "geo"):
        """
        Insert features into existing PostGIS table (DML only).

        Used for parallel inserts in Stage 2 after table has been created in Stage 1.
        Assumes table already exists - will fail if table doesn't exist.

        Args:
            chunk: GeoDataFrame chunk to insert
            table_name: Target table name (must already exist)
            schema: Target schema (default: 'geo')

        Raises:
            psycopg.Error: If insert fails or table doesn't exist
        """
        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                self._insert_features(cur, chunk, table_name, schema)
                conn.commit()
                logger.info(f"Inserted {len(chunk)} rows into {schema}.{table_name} (DML only, table already exists)")

    def _get_postgres_type(self, dtype) -> str:
        """
        Map pandas dtype to PostgreSQL type.

        Args:
            dtype: Pandas dtype

        Returns:
            PostgreSQL type string
        """
        dtype_str = str(dtype)

        if 'int' in dtype_str:
            return 'INTEGER'
        elif 'float' in dtype_str:
            return 'DOUBLE PRECISION'
        elif 'bool' in dtype_str:
            return 'BOOLEAN'
        elif 'datetime' in dtype_str:
            return 'TIMESTAMP'
        elif 'date' in dtype_str:
            return 'DATE'
        else:
            return 'TEXT'

    def _create_table_if_not_exists(
        self,
        cur: psycopg.Cursor,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str,
        indexes: dict = None
    ):
        """
        Create PostGIS table if it doesn't exist.

        Args:
            cur: psycopg cursor
            chunk: Sample GeoDataFrame for schema detection
            table_name: Table name
            schema: Schema name
            indexes: Index configuration (spatial, attributes, temporal)
        """
        # Get geometry type from first feature
        # After normalization, all geometries should be uniform Multi- types
        geom_type = chunk.geometry.iloc[0].geom_type.upper()

        # Verify uniform geometry type (should always be true after normalization)
        unique_types = chunk.geometry.geom_type.unique()
        if len(unique_types) > 1:
            logger.warning(f" Mixed geometry types detected in chunk: {unique_types.tolist()}")
            logger.info(f"Using {geom_type} for table definition")
        else:
            logger.info(f"Creating table with geometry type: {geom_type}")

        # Build column definitions
        columns = []
        for col in chunk.columns:
            if col == 'geometry':
                continue

            pg_type = self._get_postgres_type(chunk[col].dtype)
            columns.append(sql.Identifier(col) + sql.SQL(f" {pg_type}"))

        # Create table with geometry column
        create_table = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {schema}.{table} (
                id SERIAL PRIMARY KEY,
                geom GEOMETRY({geom_type}, 4326),
                {columns}
            )
        """).format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            geom_type=sql.SQL(geom_type),
            columns=sql.SQL(', ').join(columns) if columns else sql.SQL('')
        )

        cur.execute(create_table)

        # Create indexes (spatial, attribute, temporal)
        # Use provided index configuration or defaults
        index_config = indexes if indexes is not None else {
            'spatial': True,
            'attributes': [],
            'temporal': []
        }

        # Get column names for validation
        column_names = [col for col in chunk.columns if col != 'geometry']

        self._create_indexes(
            cur=cur,
            table_name=table_name,
            schema=schema,
            index_config=index_config,
            columns=column_names
        )

    def _create_indexes(
        self,
        cur: psycopg.Cursor,
        table_name: str,
        schema: str,
        index_config: dict,
        columns: list
    ):
        """
        Create database indexes based on configuration.

        Supports three types of indexes:
        1. Spatial (GIST) - On geometry column for spatial queries
        2. Attribute (B-tree) - On specified columns for WHERE clause performance
        3. Temporal (B-tree DESC) - On date/time columns for time-series queries

        Args:
            cur: psycopg cursor
            table_name: Table name
            schema: Schema name
            index_config: Index configuration dict with keys:
                - spatial: bool (default True)
                - attributes: list of column names
                - temporal: list of column names for DESC indexes
            columns: List of available column names for validation

        Example config:
            {
                'spatial': True,
                'attributes': ['country', 'event_type'],
                'temporal': ['event_date', 'timestamp']
            }
        """
        # 1. SPATIAL INDEX (GIST on geometry column)
        if index_config.get('spatial', True):
            index_name = f"idx_{table_name}_geom"
            create_index = sql.SQL("""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {schema}.{table}
                USING GIST (geom)
            """).format(
                index_name=sql.Identifier(index_name),
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name)
            )
            cur.execute(create_index)
            logger.info(f"✅ Created spatial index: {index_name}")

        # 2. ATTRIBUTE INDEXES (B-tree on specified columns)
        attribute_columns = index_config.get('attributes', [])
        for col in attribute_columns:
            if col not in columns:
                logger.warning(f"⚠️ Skipping index on '{col}' - column not found in table")
                continue

            index_name = f"idx_{table_name}_{col}"
            create_index = sql.SQL("""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {schema}.{table} ({column})
            """).format(
                index_name=sql.Identifier(index_name),
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                column=sql.Identifier(col)
            )
            cur.execute(create_index)
            logger.info(f"✅ Created attribute index: {index_name} on {col}")

        # 3. TEMPORAL INDEXES (B-tree DESC for time-series queries)
        temporal_columns = index_config.get('temporal', [])
        for temp_col in temporal_columns:
            if temp_col not in columns:
                logger.warning(f"⚠️ Skipping temporal index - column '{temp_col}' not found")
                continue

            index_name = f"idx_{table_name}_{temp_col}_desc"
            create_index = sql.SQL("""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {schema}.{table} ({column} DESC)
            """).format(
                index_name=sql.Identifier(index_name),
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                column=sql.Identifier(temp_col)
            )
            cur.execute(create_index)
            logger.info(f"✅ Created temporal index: {index_name} on {temp_col} DESC")

    def _insert_features(
        self,
        cur: psycopg.Cursor,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str
    ):
        """
        Insert GeoDataFrame features into PostGIS table.

        Args:
            cur: psycopg cursor
            chunk: GeoDataFrame to insert
            table_name: Table name
            schema: Schema name
        """
        # Get attribute columns (exclude geometry)
        attr_cols = [col for col in chunk.columns if col != 'geometry']

        # Build INSERT statement
        if attr_cols:
            cols_sql = sql.SQL(', ').join([sql.Identifier(col) for col in attr_cols])
            placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(attr_cols))

            insert_stmt = sql.SQL("""
                INSERT INTO {schema}.{table} (geom, {cols})
                VALUES (ST_GeomFromText(%s, 4326), {placeholders})
            """).format(
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                cols=cols_sql,
                placeholders=placeholders
            )
        else:
            insert_stmt = sql.SQL("""
                INSERT INTO {schema}.{table} (geom)
                VALUES (ST_GeomFromText(%s, 4326))
            """).format(
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name)
            )

        # Insert each feature
        for idx, row in chunk.iterrows():
            geom_wkt = row.geometry.wkt

            if attr_cols:
                values = [geom_wkt] + [row[col] for col in attr_cols]
            else:
                values = [geom_wkt]

            cur.execute(insert_stmt, values)

    # =========================================================================
    # NEW: GeoTableBuilder Integration (24 NOV 2025)
    # =========================================================================
    # These methods use GeoTableBuilder for standardized table creation with:
    # - Standard metadata columns (created_at, source_file, stac_item_id, etc.)
    # - ArcGIS Enterprise Geodatabase compatibility ('shape' column option)
    # - Automatic triggers for updated_at
    # =========================================================================

    def create_table_with_metadata(
        self,
        gdf: gpd.GeoDataFrame,
        table_name: str,
        schema: str = "geo",
        source_file: str = None,
        source_format: str = None,
        source_crs: str = None,
        stac_item_id: str = None,
        stac_collection_id: str = None,
        etl_job_id: str = None,
        index_config: dict = None,
        arcgis_mode: bool = False
    ):
        """
        Create PostGIS table with standard metadata columns using GeoTableBuilder.

        This method creates tables with:
        - Standard metadata columns (objectid, created_at, updated_at, source_file, etc.)
        - STAC catalog linkage columns (stac_item_id, stac_collection_id)
        - ETL traceability (etl_job_id, etl_batch_id)
        - Automatic updated_at trigger
        - Configurable geometry column name (PostGIS 'geom' vs ArcGIS 'shape')

        Args:
            gdf: Sample GeoDataFrame for schema detection
            table_name: Target table name
            schema: Target schema (default 'geo')
            source_file: Original filename for tracking
            source_format: File format (shp, gpkg, geojson)
            source_crs: Original CRS before reprojection
            stac_item_id: STAC item ID for catalog linkage
            stac_collection_id: STAC collection ID
            etl_job_id: CoreMachine job ID for traceability
            index_config: Index configuration dict:
                - spatial: bool (default True)
                - attributes: list of column names
                - temporal: list of column names for DESC indexes
            arcgis_mode: If True, use 'shape' column name for ArcGIS compatibility

        Returns:
            dict with table creation result:
                - success: bool
                - table_name: str
                - schema: str
                - columns: list of column names
                - geometry_column: str ('geom' or 'shape')

        Raises:
            psycopg.Error: If table creation fails
        """
        from core.schema.geo_table_builder import GeoTableBuilder, GeometryColumnConfig

        # Create builder with appropriate configuration
        geom_config = GeometryColumnConfig.ARCGIS if arcgis_mode else GeometryColumnConfig.POSTGIS
        builder = GeoTableBuilder(geometry_column=geom_config)

        logger.info(f"🏗️ Creating table with GeoTableBuilder:")
        logger.info(f"   Table: {schema}.{table_name}")
        logger.info(f"   ArcGIS mode: {arcgis_mode}")
        logger.info(f"   Geometry column: {builder.geometry_column_name}")

        # Generate complete DDL
        ddl_statements = builder.create_complete_ddl(
            gdf=gdf,
            table_name=table_name,
            schema=schema,
            source_file=source_file,
            source_format=source_format,
            source_crs=source_crs,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            etl_job_id=etl_job_id,
            index_config=index_config
        )

        # Execute DDL
        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                for stmt in ddl_statements:
                    cur.execute(stmt)
                conn.commit()

        logger.info(f"✅ Created table {schema}.{table_name} with {len(ddl_statements)} DDL statements")

        return {
            'success': True,
            'table_name': table_name,
            'schema': schema,
            'geometry_column': builder.geometry_column_name,
            'arcgis_mode': arcgis_mode,
            'ddl_count': len(ddl_statements)
        }

    def insert_features_with_metadata(
        self,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str = "geo",
        source_file: str = None,
        source_format: str = None,
        source_crs: str = None,
        stac_item_id: str = None,
        stac_collection_id: str = None,
        etl_job_id: str = None,
        etl_batch_id: str = None,
        arcgis_mode: bool = False
    ):
        """
        Insert features with standard metadata columns populated.

        This method inserts features AND populates the standard metadata columns
        created by create_table_with_metadata().

        Args:
            chunk: GeoDataFrame to insert
            table_name: Target table name
            schema: Target schema (default 'geo')
            source_file: Original filename
            source_format: File format
            source_crs: Original CRS
            stac_item_id: STAC item ID
            stac_collection_id: STAC collection ID
            etl_job_id: CoreMachine job ID
            etl_batch_id: Chunk/batch identifier
            arcgis_mode: If True, use 'shape' column name

        Returns:
            dict with insert result:
                - success: bool
                - rows_inserted: int
                - table_name: str

        Raises:
            psycopg.Error: If insert fails
        """
        geom_col = 'shape' if arcgis_mode else 'geom'

        # Get attribute columns (exclude geometry)
        attr_cols = [col for col in chunk.columns if col != 'geometry']

        # Clean column names to match table
        import re
        def clean_col(name):
            cleaned = name.lower()
            cleaned = re.sub(r'[^a-z0-9_]', '_', cleaned)
            cleaned = re.sub(r'_+', '_', cleaned).strip('_')
            if cleaned and cleaned[0].isdigit():
                cleaned = 'col_' + cleaned
            return cleaned or 'unnamed_column'

        cleaned_attr_cols = [clean_col(col) for col in attr_cols]

        # Build column list including metadata
        all_cols = [geom_col]  # Geometry first
        all_cols.extend(cleaned_attr_cols)  # Dynamic attributes

        # Add metadata columns
        metadata_cols = ['source_file', 'source_format', 'source_crs',
                        'stac_item_id', 'stac_collection_id',
                        'etl_job_id', 'etl_batch_id']
        all_cols.extend(metadata_cols)

        # Build INSERT statement
        cols_sql = sql.SQL(', ').join([sql.Identifier(col) for col in all_cols])
        placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(all_cols))

        insert_stmt = sql.SQL("""
            INSERT INTO {schema}.{table} ({cols})
            VALUES ({placeholders})
        """).format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            cols=cols_sql,
            placeholders=placeholders
        )

        # Insert each feature with metadata
        rows_inserted = 0
        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                for idx, row in chunk.iterrows():
                    # Geometry as WKT with ST_GeomFromText
                    geom_wkt = row.geometry.wkt

                    # Build values list
                    values = [f"SRID=4326;{geom_wkt}"]  # EWKT format

                    # Add attribute values
                    for col in attr_cols:
                        values.append(row[col])

                    # Add metadata values
                    values.extend([
                        source_file,
                        source_format,
                        source_crs,
                        stac_item_id,
                        stac_collection_id,
                        etl_job_id,
                        etl_batch_id
                    ])

                    # Use ST_GeomFromEWKT for geometry
                    insert_with_geom = sql.SQL("""
                        INSERT INTO {schema}.{table} ({cols})
                        VALUES (ST_GeomFromEWKT(%s), {attr_placeholders}, %s, %s, %s, %s, %s, %s, %s)
                    """).format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name),
                        cols=cols_sql,
                        attr_placeholders=sql.SQL(', ').join([sql.Placeholder()] * len(attr_cols))
                    )

                    cur.execute(insert_with_geom, values)
                    rows_inserted += 1

                conn.commit()

        logger.info(f"✅ Inserted {rows_inserted} rows with metadata into {schema}.{table_name}")

        return {
            'success': True,
            'rows_inserted': rows_inserted,
            'table_name': table_name,
            'schema': schema
        }

    def upload_chunk_with_metadata(
        self,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str = "geo",
        source_file: str = None,
        source_format: str = None,
        source_crs: str = None,
        stac_item_id: str = None,
        stac_collection_id: str = None,
        etl_job_id: str = None,
        etl_batch_id: str = None,
        index_config: dict = None,
        arcgis_mode: bool = False
    ):
        """
        Complete upload with table creation and metadata (convenience method).

        Combines create_table_with_metadata() and insert_features_with_metadata()
        for simple single-chunk uploads. For parallel uploads, use the separate
        methods to avoid table creation race conditions.

        Args:
            chunk: GeoDataFrame to upload
            table_name: Target table name
            schema: Target schema (default 'geo')
            source_file: Original filename
            source_format: File format
            source_crs: Original CRS
            stac_item_id: STAC item ID
            stac_collection_id: STAC collection ID
            etl_job_id: CoreMachine job ID
            etl_batch_id: Chunk/batch identifier
            index_config: Index configuration dict
            arcgis_mode: If True, use 'shape' column for ArcGIS

        Returns:
            dict with upload result

        Raises:
            psycopg.Error: If operation fails
        """
        # Create table
        create_result = self.create_table_with_metadata(
            gdf=chunk,
            table_name=table_name,
            schema=schema,
            source_file=source_file,
            source_format=source_format,
            source_crs=source_crs,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            etl_job_id=etl_job_id,
            index_config=index_config,
            arcgis_mode=arcgis_mode
        )

        # Insert features
        insert_result = self.insert_features_with_metadata(
            chunk=chunk,
            table_name=table_name,
            schema=schema,
            source_file=source_file,
            source_format=source_format,
            source_crs=source_crs,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            etl_job_id=etl_job_id,
            etl_batch_id=etl_batch_id,
            arcgis_mode=arcgis_mode
        )

        return {
            'success': True,
            'table_name': table_name,
            'schema': schema,
            'rows_inserted': insert_result['rows_inserted'],
            'geometry_column': create_result['geometry_column'],
            'arcgis_mode': arcgis_mode
        }

    # =========================================================================
    # IDEMPOTENT CHUNK OPERATIONS (26 NOV 2025)
    # =========================================================================
    # Methods for process_vector workflow with built-in idempotency via
    # DELETE+INSERT pattern using etl_batch_id column.
    # =========================================================================

    def create_table_with_batch_tracking(
        self,
        table_name: str,
        schema: str,
        gdf: gpd.GeoDataFrame,
        indexes: dict = None
    ) -> None:
        """
        Create PostGIS table with etl_batch_id column for idempotent chunk tracking.

        IDEMPOTENT: Uses IF NOT EXISTS - safe to call multiple times.

        Schema includes:
        - id: SERIAL PRIMARY KEY
        - geom: GEOMETRY (auto-detected type, 4326)
        - etl_batch_id: TEXT (for DELETE+INSERT pattern)
        - [user columns from GeoDataFrame]

        Indexes created:
        - idx_{table}_geom: GIST spatial index (if indexes.spatial=True)
        - idx_{table}_etl_batch_id: BTREE for fast DELETE lookups
        - idx_{table}_{col}: BTREE for each column in indexes.attributes

        Args:
            table_name: Target table name
            schema: Target schema (default: 'geo')
            gdf: Sample GeoDataFrame for schema detection
            indexes: Index configuration dict with keys:
                - spatial: bool (default True)
                - attributes: list of column names
                - temporal: list of column names for DESC indexes
        """
        # Default index config
        if indexes is None:
            indexes = {'spatial': True, 'attributes': [], 'temporal': []}

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Detect geometry type from first feature
                geom_type = gdf.geometry.iloc[0].geom_type.upper()

                # Build column definitions
                # RESERVED COLUMNS: These are created by our schema, skip if in source data
                reserved_cols = {'id', 'geom', 'geometry', 'etl_batch_id'}

                columns = []
                skipped_cols = []
                for col in gdf.columns:
                    if col == 'geometry':
                        continue
                    # Skip reserved column names to avoid "column specified more than once" error
                    if col.lower() in reserved_cols:
                        skipped_cols.append(col)
                        continue
                    pg_type = self._get_postgres_type(gdf[col].dtype)
                    columns.append(sql.Identifier(col) + sql.SQL(f" {pg_type}"))

                if skipped_cols:
                    logger.warning(f"⚠️ Skipped reserved columns from source data: {skipped_cols}")

                # Create table with id, geom, etl_batch_id, and user columns
                create_table = sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        id SERIAL PRIMARY KEY,
                        geom GEOMETRY({geom_type}, 4326),
                        etl_batch_id TEXT,
                        {columns}
                    )
                """).format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name),
                    geom_type=sql.SQL(geom_type),
                    columns=sql.SQL(', ').join(columns) if columns else sql.SQL('')
                )
                cur.execute(create_table)

                # Get column names for index validation
                column_names = [col for col in gdf.columns if col != 'geometry']

                # Create spatial index
                if indexes.get('spatial', True):
                    cur.execute(sql.SQL("""
                        CREATE INDEX IF NOT EXISTS {idx_name}
                        ON {schema}.{table} USING GIST (geom)
                    """).format(
                        idx_name=sql.Identifier(f"idx_{table_name}_geom"),
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    ))

                # Create etl_batch_id index (CRITICAL for DELETE performance)
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {schema}.{table} (etl_batch_id)
                """).format(
                    idx_name=sql.Identifier(f"idx_{table_name}_etl_batch_id"),
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name)
                ))

                # Create attribute indexes
                for attr_col in indexes.get('attributes', []):
                    if attr_col in column_names:
                        cur.execute(sql.SQL("""
                            CREATE INDEX IF NOT EXISTS {idx_name}
                            ON {schema}.{table} ({col})
                        """).format(
                            idx_name=sql.Identifier(f"idx_{table_name}_{attr_col}"),
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name),
                            col=sql.Identifier(attr_col)
                        ))

                # Create temporal indexes (DESC for time-series queries)
                for temp_col in indexes.get('temporal', []):
                    if temp_col in column_names:
                        cur.execute(sql.SQL("""
                            CREATE INDEX IF NOT EXISTS {idx_name}
                            ON {schema}.{table} ({col} DESC)
                        """).format(
                            idx_name=sql.Identifier(f"idx_{table_name}_{temp_col}_desc"),
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name),
                            col=sql.Identifier(temp_col)
                        ))

                conn.commit()
                logger.info(f"✅ Created table {schema}.{table_name} with etl_batch_id tracking")

    def insert_chunk_idempotent(
        self,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str,
        batch_id: str
    ) -> Dict[str, int]:
        """
        Insert GeoDataFrame chunk with DELETE+INSERT idempotency pattern.

        IDEMPOTENCY MECHANISM:
        1. DELETE all rows WHERE etl_batch_id = batch_id
        2. INSERT new rows with that batch_id

        Both operations in single transaction - atomic success or failure.

        This ensures re-running the same task:
        - Deletes the partial/complete previous attempt
        - Inserts fresh data
        - Results in exactly the same final state

        Args:
            chunk: GeoDataFrame chunk to insert
            table_name: Target table
            schema: Target schema
            batch_id: Unique identifier for this chunk (job_id[:8]-chunk-N)

        Returns:
            {'rows_deleted': int, 'rows_inserted': int}
        """
        rows_deleted = 0
        rows_inserted = 0

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Step 1: DELETE existing rows for this batch (IDEMPOTENCY)
                delete_stmt = sql.SQL("""
                    DELETE FROM {schema}.{table}
                    WHERE etl_batch_id = %s
                """).format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name)
                )
                cur.execute(delete_stmt, (batch_id,))
                rows_deleted = cur.rowcount

                if rows_deleted > 0:
                    logger.info(f"🔄 Deleted {rows_deleted} existing rows for batch {batch_id} (idempotent re-run)")

                # Step 2: INSERT new rows with batch_id
                # Skip reserved columns that we create in our schema
                reserved_cols = {'id', 'geom', 'geometry', 'etl_batch_id'}
                attr_cols = [col for col in chunk.columns if col != 'geometry' and col.lower() not in reserved_cols]

                if attr_cols:
                    cols_sql = sql.SQL(', ').join([sql.Identifier(col) for col in attr_cols])
                    placeholders = sql.SQL(', ').join([sql.Placeholder()] * len(attr_cols))

                    insert_stmt = sql.SQL("""
                        INSERT INTO {schema}.{table} (geom, etl_batch_id, {cols})
                        VALUES (ST_GeomFromText(%s, 4326), %s, {placeholders})
                    """).format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name),
                        cols=cols_sql,
                        placeholders=placeholders
                    )
                else:
                    insert_stmt = sql.SQL("""
                        INSERT INTO {schema}.{table} (geom, etl_batch_id)
                        VALUES (ST_GeomFromText(%s, 4326), %s)
                    """).format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    )

                # Insert each row with batch_id
                for idx, row in chunk.iterrows():
                    geom_wkt = row.geometry.wkt

                    if attr_cols:
                        values = [geom_wkt, batch_id] + [row[col] for col in attr_cols]
                    else:
                        values = [geom_wkt, batch_id]

                    cur.execute(insert_stmt, values)
                    rows_inserted += 1

                conn.commit()

        logger.info(f"✅ Chunk {batch_id}: deleted={rows_deleted}, inserted={rows_inserted}")
        return {'rows_deleted': rows_deleted, 'rows_inserted': rows_inserted}

    # =========================================================================
    # TABLE METADATA REGISTRY (06 DEC 2025)
    # =========================================================================
    # Methods for managing geo.table_metadata - the source of truth for
    # vector table metadata. STAC copies this for catalog convenience.
    # =========================================================================

    def register_table_metadata(
        self,
        table_name: str,
        schema: str,
        etl_job_id: str,
        source_file: str,
        source_format: str,
        source_crs: str,
        feature_count: int,
        geometry_type: str,
        bbox: tuple,
        # New optional metadata fields (09 DEC 2025)
        title: str = None,
        description: str = None,
        attribution: str = None,
        license: str = None,
        keywords: str = None,
        temporal_start: str = None,
        temporal_end: str = None,
        temporal_property: str = None
    ) -> None:
        """
        Register or update table metadata in geo.table_metadata registry.

        This is the SOURCE OF TRUTH for vector table metadata. STAC items
        copy this information for catalog convenience.

        Uses INSERT ... ON CONFLICT UPDATE for idempotency - safe to call
        multiple times (e.g., on job re-run).

        Args:
            table_name: Target table name (PRIMARY KEY in registry)
            schema: Target schema (default 'geo')
            etl_job_id: Full 64-char job ID for traceability
            source_file: Original filename (e.g., 'countries.shp')
            source_format: File format (shp, gpkg, geojson, csv, etc.)
            source_crs: Original CRS string before reprojection (e.g., 'EPSG:32610')
            feature_count: Total number of features in table
            geometry_type: PostGIS geometry type (e.g., 'MULTIPOLYGON')
            bbox: Bounding box tuple (minx, miny, maxx, maxy) for pre-computed extent
            title: User-friendly display name (optional, 09 DEC 2025)
            description: Full dataset description (optional, 09 DEC 2025)
            attribution: Data source attribution (optional, 09 DEC 2025)
            license: SPDX license identifier e.g. CC-BY-4.0 (optional, 09 DEC 2025)
            keywords: Comma-separated tags for discoverability (optional, 09 DEC 2025)
            temporal_start: Start of temporal extent ISO8601 (optional, 09 DEC 2025)
            temporal_end: End of temporal extent ISO8601 (optional, 09 DEC 2025)
            temporal_property: Column name containing date data (optional, 09 DEC 2025)
        """
        # Handle None or invalid bbox gracefully
        bbox_values = (None, None, None, None)
        if bbox is not None and len(bbox) >= 4:
            bbox_values = (bbox[0], bbox[1], bbox[2], bbox[3])

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO geo.table_metadata (
                        table_name, schema_name, etl_job_id, source_file,
                        source_format, source_crs, feature_count, geometry_type,
                        bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                        title, description, attribution, license, keywords,
                        temporal_start, temporal_end, temporal_property,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        NOW(), NOW()
                    )
                    ON CONFLICT (table_name) DO UPDATE SET
                        schema_name = EXCLUDED.schema_name,
                        etl_job_id = EXCLUDED.etl_job_id,
                        source_file = EXCLUDED.source_file,
                        source_format = EXCLUDED.source_format,
                        source_crs = EXCLUDED.source_crs,
                        feature_count = EXCLUDED.feature_count,
                        geometry_type = EXCLUDED.geometry_type,
                        bbox_minx = EXCLUDED.bbox_minx,
                        bbox_miny = EXCLUDED.bbox_miny,
                        bbox_maxx = EXCLUDED.bbox_maxx,
                        bbox_maxy = EXCLUDED.bbox_maxy,
                        title = COALESCE(EXCLUDED.title, geo.table_metadata.title),
                        description = COALESCE(EXCLUDED.description, geo.table_metadata.description),
                        attribution = COALESCE(EXCLUDED.attribution, geo.table_metadata.attribution),
                        license = COALESCE(EXCLUDED.license, geo.table_metadata.license),
                        keywords = COALESCE(EXCLUDED.keywords, geo.table_metadata.keywords),
                        temporal_start = COALESCE(EXCLUDED.temporal_start, geo.table_metadata.temporal_start),
                        temporal_end = COALESCE(EXCLUDED.temporal_end, geo.table_metadata.temporal_end),
                        temporal_property = COALESCE(EXCLUDED.temporal_property, geo.table_metadata.temporal_property),
                        updated_at = NOW()
                """, (
                    table_name, schema, etl_job_id, source_file,
                    source_format, source_crs, feature_count, geometry_type,
                    bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3],
                    title, description, attribution, license, keywords,
                    temporal_start, temporal_end, temporal_property
                ))
                conn.commit()

        logger.info(f"✅ Registered metadata for {schema}.{table_name} (job: {etl_job_id[:8]}...)")

    def update_table_stac_link(
        self,
        table_name: str,
        stac_item_id: str,
        stac_collection_id: str
    ) -> bool:
        """
        Update table_metadata with STAC item linkage after Stage 3 completion.

        Called after successful STAC item creation to establish the backlink
        from PostGIS table → STAC catalog item.

        Args:
            table_name: Table name (must already exist in registry)
            stac_item_id: STAC item ID created in pgstac
            stac_collection_id: STAC collection ID (e.g., 'system-vectors')

        Returns:
            True if row was updated, False if table_name not found in registry
        """
        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE geo.table_metadata
                    SET stac_item_id = %s,
                        stac_collection_id = %s,
                        updated_at = NOW()
                    WHERE table_name = %s
                """, (stac_item_id, stac_collection_id, table_name))
                conn.commit()
                rows_updated = cur.rowcount

        if rows_updated > 0:
            logger.info(f"✅ Linked {table_name} → STAC item {stac_item_id}")
            return True
        else:
            logger.warning(f"⚠️ No metadata found for {table_name} - STAC link not recorded")
            return False
