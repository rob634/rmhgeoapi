# ============================================================================
# CLAUDE CONTEXT - POSTGIS HANDLER
# ============================================================================
# PURPOSE: Handle GeoDataFrame validation, chunking, and upload to PostGIS
# EXPORTS: VectorToPostGISHandler class
# INTERFACES: None (concrete implementation)
# PYDANTIC_MODELS: None (operates on GeoDataFrames)
# DEPENDENCIES: geopandas, psycopg, config
# SOURCE: Called by validate_vector and upload_vector_chunk tasks
# SCOPE: Service layer - PostGIS integration
# VALIDATION: Geometry validation, CRS reprojection, column name cleaning
# PATTERNS: Handler class with single responsibility methods
# ENTRY_POINTS: from services.vector.postgis_handler import VectorToPostGISHandler
# INDEX:
#   - __init__ (line 39): Initialize with PostgreSQL connection
#   - prepare_gdf (line 49): Validate and prepare GeoDataFrame
#   - calculate_optimal_chunk_size (line 108): Auto-calculate chunk size based on data
#   - chunk_gdf (line 185): Split GeoDataFrame into chunks (auto or manual size)
#   - upload_chunk (line 213): Upload chunk to PostGIS
#   - _get_postgres_type (line 250): Map pandas dtypes to PostgreSQL types
#   - _create_table_if_not_exists (line 270): Create PostGIS table
#   - _insert_features (line 320): Insert GeoDataFrame rows
# ============================================================================

"""
VectorToPostGISHandler - GeoDataFrame validation and PostGIS upload.

Handles the complete workflow of preparing and uploading vector data to PostGIS:
1. prepare_gdf: Validate geometries, reproject to EPSG:4326, clean column names
2. chunk_gdf: Split large GeoDataFrames for parallel processing
3. upload_chunk: Create table and insert features into PostGIS geo schema
"""

from typing import List, Dict, Any
import geopandas as gpd
import pandas as pd
import psycopg
from psycopg import sql
from config import get_config


class VectorToPostGISHandler:
    """Handles GeoDataFrame → PostGIS operations."""

    def __init__(self):
        """Initialize with PostgreSQL connection string."""
        config = get_config()
        self.conn_string = config.postgis_connection_string

    def prepare_gdf(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Validate, reproject, and clean GeoDataFrame.

        Operations:
        1. Remove null geometries
        2. Fix invalid geometries (buffer(0) trick)
        3. Reproject to EPSG:4326 if needed
        4. Clean column names (lowercase, replace spaces with underscores)
        5. Remove geometry column from attributes

        Args:
            gdf: Input GeoDataFrame

        Returns:
            Cleaned and validated GeoDataFrame

        Raises:
            ValueError: If GeoDataFrame has no valid geometries
        """
        # Remove null geometries
        original_count = len(gdf)
        gdf = gdf[~gdf.geometry.isna()].copy()

        if len(gdf) == 0:
            raise ValueError("GeoDataFrame has no valid geometries after removing nulls")

        if len(gdf) < original_count:
            removed = original_count - len(gdf)
            print(f"Removed {removed} null geometries ({removed/original_count*100:.1f}%)")

        # Fix invalid geometries
        invalid_mask = ~gdf.geometry.is_valid
        invalid_count = invalid_mask.sum()
        if invalid_count > 0:
            print(f"Fixing {invalid_count} invalid geometries using buffer(0)")
            gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].buffer(0)

        # Reproject to EPSG:4326 if needed
        if gdf.crs and gdf.crs != "EPSG:4326":
            print(f"Reprojecting from {gdf.crs} to EPSG:4326")
            gdf = gdf.to_crs("EPSG:4326")
        elif not gdf.crs:
            print("No CRS defined, assuming EPSG:4326")
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
        avg_coords = sample_geoms.apply(
            lambda g: len(g.coords) if hasattr(g, 'coords')
            else (len(g.exterior.coords) if hasattr(g, 'exterior')
            else sum(len(p.exterior.coords) for p in g.geoms) if hasattr(g, 'geoms')
            else 10)  # Default for complex geometries
        ).mean()

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

        print(f"Calculated optimal chunk size: {optimal_size} rows")
        print(f"  Factors: columns={col_factor:.1f}, types={type_factor:.1f}, geometry={geom_factor:.1f}")

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

        print(f"Split GeoDataFrame into {len(chunks)} chunks of up to {chunk_size} rows")
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
        with psycopg.connect(self.conn_string) as conn:
            with conn.cursor() as cur:
                # Create table if not exists
                self._create_table_if_not_exists(cur, chunk, table_name, schema)

                # Insert features
                self._insert_features(cur, chunk, table_name, schema)

                conn.commit()
                print(f"Uploaded {len(chunk)} rows to {schema}.{table_name}")

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
        schema: str
    ):
        """
        Create PostGIS table if it doesn't exist.

        Args:
            cur: psycopg cursor
            chunk: Sample GeoDataFrame for schema detection
            table_name: Table name
            schema: Schema name
        """
        # Get geometry type from first feature
        geom_type = chunk.geometry.iloc[0].geom_type.upper()

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

        # Create spatial index
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
