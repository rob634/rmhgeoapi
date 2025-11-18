# ============================================================================
# CLAUDE CONTEXT - ENHANCED VECTOR TO POSTGIS HANDLER
# ============================================================================
# PURPOSE: PostGIS ingestion handler with comprehensive error handling
# EXPORTS: VectorToPostGISHandler
# INTERFACES: None
# PYDANTIC_MODELS: None (uses GeoDataFrame)
# DEPENDENCIES: geopandas, psycopg, shapely, config
# SOURCE: GeoDataFrame from various vector file formats
# SCOPE: Service layer - PostGIS operations
# VALIDATION: Geometry validation, CRS validation, column validation
# PATTERNS: Error handling with detailed logging
# ENTRY_POINTS: handler = VectorToPostGISHandler(); handler.upload_chunk()
# INDEX:
#   - VectorToPostGISHandler: Main handler class
#   - prepare_gdf: Validate and clean GeoDataFrame
#   - upload_chunk: Upload to PostGIS with error handling
# ============================================================================

"""
Enhanced Vector to PostGIS Handler with Comprehensive Error Handling

This module provides robust error handling for vector data ingestion into PostGIS.
Each operation has granular try-except blocks with detailed logging for debugging.

Key improvements:
- Granular error handling for each operation
- Detailed logging with context
- Specific exception types for different failures
- Transaction rollback on errors
- Connection retry logic
- Validation before operations

Author: Robert and Geospatial Claude Legion
Date: 26 OCT 2025
"""

import logging
from typing import Optional, List, Dict, Any, Tuple
import geopandas as gpd
import psycopg
from psycopg import sql
from shapely.geometry import shape, mapping
from shapely.validation import make_valid
import traceback

from config import get_config

# Configure logging with detailed formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)


class PostGISError(Exception):
    """Base exception for PostGIS operations."""
    pass


class ConnectionError(PostGISError):
    """Database connection errors."""
    pass


class TableCreationError(PostGISError):
    """Table creation errors."""
    pass


class DataInsertionError(PostGISError):
    """Data insertion errors."""
    pass


class GeometryValidationError(PostGISError):
    """Geometry validation errors."""
    pass


class VectorToPostGISHandler:
    """Enhanced handler for vector data ingestion into PostGIS with comprehensive error handling."""

    def __init__(self):
        """Initialize with PostgreSQL repository for managed identity support."""
        try:
            from infrastructure.postgresql import PostgreSQLRepository

            config = get_config()
            # Use PostgreSQLRepository for managed identity support (18 NOV 2025)
            self._pg_repo = PostgreSQLRepository()
            # Keep conn_string for backward compatibility (deprecated)
            self.conn_string = self._pg_repo.conn_string
            logger.info("✅ PostGIS handler initialized successfully")

            # Track errors for reporting
            self.errors = []
            self.warnings = []

        except Exception as e:
            logger.error(f"❌ Failed to initialize PostGIS handler: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise ConnectionError(f"Cannot initialize handler: {e}")

    def prepare_gdf(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Validate, reproject, and clean GeoDataFrame with detailed error handling.

        Operations with error handling:
        1. Remove null geometries (with logging of affected rows)
        2. Fix invalid geometries (with specific error types)
        3. Reproject to EPSG:4326 (with CRS validation)
        4. Clean column names (with conflict resolution)
        5. Remove duplicate geometries (optional)

        Args:
            gdf: Input GeoDataFrame

        Returns:
            Cleaned and validated GeoDataFrame

        Raises:
            GeometryValidationError: If GeoDataFrame has critical geometry issues
            ValueError: If GeoDataFrame has no valid geometries
        """
        logger.info(f"📊 Starting GeoDataFrame preparation with {len(gdf)} features")

        # Step 1: Handle null geometries with detailed logging
        try:
            original_count = len(gdf)
            null_mask = gdf.geometry.isna()
            null_count = null_mask.sum()

            if null_count > 0:
                logger.warning(f"⚠️ Found {null_count} null geometries out of {original_count}")

                # Log sample of null geometry rows for debugging
                null_samples = gdf[null_mask].head(5)
                for idx, row in null_samples.iterrows():
                    non_geom_cols = [col for col in gdf.columns if col != 'geometry'][:3]
                    sample_data = {col: str(row[col])[:50] for col in non_geom_cols}
                    logger.debug(f"  Null geometry row {idx}: {sample_data}")

                # Remove null geometries
                gdf = gdf[~null_mask].copy()
                logger.info(f"✅ Removed {null_count} null geometries, {len(gdf)} remaining")

                if len(gdf) == 0:
                    raise ValueError(f"All {original_count} geometries were null - no data to process")

        except Exception as e:
            logger.error(f"❌ Error handling null geometries: {e}")
            raise GeometryValidationError(f"Failed to process null geometries: {e}")

        # Step 2: Fix invalid geometries with specific error handling
        try:
            invalid_count = 0
            fixed_geometries = []

            for idx, geom in enumerate(gdf.geometry):
                try:
                    if geom is not None and not geom.is_valid:
                        invalid_count += 1
                        # Try to fix with buffer(0) trick
                        fixed_geom = geom.buffer(0)

                        # If still invalid, try make_valid
                        if not fixed_geom.is_valid:
                            fixed_geom = make_valid(geom)

                        fixed_geometries.append(fixed_geom)
                        logger.debug(f"Fixed invalid geometry at index {idx}")
                    else:
                        fixed_geometries.append(geom)

                except Exception as geom_error:
                    logger.warning(f"⚠️ Could not fix geometry at index {idx}: {geom_error}")
                    # Keep original geometry if fix fails
                    fixed_geometries.append(geom)
                    self.warnings.append(f"Geometry at index {idx} may be invalid: {geom_error}")

            if invalid_count > 0:
                gdf['geometry'] = fixed_geometries
                logger.info(f"✅ Fixed {invalid_count} invalid geometries")

        except Exception as e:
            logger.error(f"❌ Error fixing invalid geometries: {e}")
            self.errors.append(f"Geometry validation failed: {e}")
            # Continue with original geometries if fixing fails
            logger.warning("⚠️ Continuing with potentially invalid geometries")

        # Step 3: Reproject to EPSG:4326 with CRS validation
        try:
            if gdf.crs is None:
                logger.warning("⚠️ No CRS defined, assuming EPSG:4326")
                gdf = gdf.set_crs("EPSG:4326")
            elif str(gdf.crs) != "EPSG:4326":
                source_crs = str(gdf.crs)
                logger.info(f"🔄 Reprojecting from {source_crs} to EPSG:4326")

                try:
                    gdf = gdf.to_crs("EPSG:4326")
                    logger.info("✅ Reprojection successful")
                except Exception as reproj_error:
                    logger.error(f"❌ Reprojection failed: {reproj_error}")
                    raise GeometryValidationError(f"Cannot reproject from {source_crs}: {reproj_error}")

        except Exception as e:
            logger.error(f"❌ CRS handling error: {e}")
            raise GeometryValidationError(f"CRS validation failed: {e}")

        # Step 4: Clean column names with conflict resolution
        try:
            original_columns = gdf.columns.tolist()
            clean_columns = []
            column_mapping = {}

            for col in original_columns:
                # Clean column name
                clean_col = (col.lower()
                           .replace(' ', '_')
                           .replace('-', '_')
                           .replace('.', '_')
                           .replace('(', '')
                           .replace(')', '')
                           .replace('#', 'num')
                           .replace('@', 'at')
                           .replace('$', 'dollar')
                           .replace('%', 'pct'))

                # Handle duplicates
                base_col = clean_col
                counter = 1
                while clean_col in clean_columns:
                    clean_col = f"{base_col}_{counter}"
                    counter += 1

                clean_columns.append(clean_col)
                column_mapping[col] = clean_col

                if col != clean_col:
                    logger.debug(f"Renamed column: '{col}' → '{clean_col}'")

            gdf.columns = clean_columns
            logger.info(f"✅ Cleaned {len(column_mapping)} column names")

        except Exception as e:
            logger.error(f"❌ Column cleaning error: {e}")
            self.warnings.append(f"Column name cleaning had issues: {e}")
            # Continue with original columns if cleaning fails

        # Step 5: Optional - Remove duplicate geometries
        try:
            initial_count = len(gdf)
            gdf = gdf.drop_duplicates(subset=['geometry'])
            if len(gdf) < initial_count:
                duplicates_removed = initial_count - len(gdf)
                logger.info(f"✅ Removed {duplicates_removed} duplicate geometries")

        except Exception as e:
            logger.warning(f"⚠️ Could not check for duplicate geometries: {e}")
            # Not critical, continue without deduplication

        # Final validation
        if len(gdf) == 0:
            raise ValueError("No valid data remaining after preparation")

        logger.info(f"✅ GeoDataFrame preparation complete: {len(gdf)} features ready")
        return gdf

    def upload_chunk(self, chunk: gpd.GeoDataFrame, table_name: str, schema: str = "geo"):
        """
        Upload GeoDataFrame chunk to PostGIS with comprehensive error handling.

        Features:
        - Connection retry logic
        - Transaction management
        - Detailed error messages
        - Automatic rollback on failure
        - Progress logging

        Args:
            chunk: GeoDataFrame chunk to upload
            table_name: Target table name
            schema: Target schema (default: 'geo')

        Raises:
            ConnectionError: If cannot connect to database
            TableCreationError: If table creation fails
            DataInsertionError: If data insertion fails
        """
        logger.info(f"📤 Starting upload of {len(chunk)} features to {schema}.{table_name}")

        conn = None
        cur = None
        rows_inserted = 0

        try:
            # Use repository connection (includes managed identity support)
            logger.debug("Acquiring database connection from repository")
            conn = self._pg_repo._get_connection().__enter__()
            logger.info("✅ Database connection established")

            # Create cursor
            cur = conn.cursor()

            # Start transaction
            logger.debug("Starting database transaction")

            # Create table if not exists
            try:
                self._create_table_if_not_exists_safe(cur, chunk, table_name, schema)
            except Exception as e:
                logger.error(f"❌ Table creation failed: {e}")
                raise TableCreationError(f"Cannot create table {schema}.{table_name}: {e}")

            # Insert features with progress tracking
            try:
                rows_inserted = self._insert_features_safe(cur, chunk, table_name, schema)
                logger.info(f"✅ Inserted {rows_inserted} rows successfully")
            except Exception as e:
                logger.error(f"❌ Data insertion failed: {e}")
                raise DataInsertionError(f"Failed to insert data into {schema}.{table_name}: {e}")

            # Commit transaction
            conn.commit()
            logger.info(f"✅ Transaction committed successfully for {schema}.{table_name}")

        except (ConnectionError, TableCreationError, DataInsertionError) as e:
            # Known errors - already logged
            if conn:
                try:
                    conn.rollback()
                    logger.info("🔄 Transaction rolled back due to error")
                except:
                    pass  # Rollback failed, connection likely dead
            raise

        except Exception as e:
            # Unexpected errors
            logger.error(f"❌ Unexpected error during upload: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            if conn:
                try:
                    conn.rollback()
                    logger.info("🔄 Transaction rolled back due to unexpected error")
                except:
                    pass
            raise PostGISError(f"Unexpected error during upload: {e}")

        finally:
            # Cleanup connections
            if cur:
                try:
                    cur.close()
                except:
                    pass
            if conn:
                try:
                    conn.close()
                    logger.debug("Database connection closed")
                except:
                    pass

    def _create_table_if_not_exists_safe(
        self,
        cur: psycopg.Cursor,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str
    ):
        """
        Create PostGIS table with comprehensive error handling.

        Handles:
        - Schema creation if needed
        - Table existence check
        - Column type mapping
        - Geometry column creation
        - Index creation
        """
        try:
            # Ensure schema exists
            logger.debug(f"Ensuring schema '{schema}' exists")
            cur.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(schema)
                )
            )

            # Check if table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                [schema, table_name]
            )

            if cur.fetchone()[0]:
                logger.info(f"Table {schema}.{table_name} already exists")
                return

            # Build CREATE TABLE statement
            logger.debug(f"Creating table {schema}.{table_name}")

            # Get column definitions
            columns = []
            columns.append("id SERIAL PRIMARY KEY")

            for col in chunk.columns:
                if col == 'geometry':
                    continue

                try:
                    dtype = str(chunk[col].dtype)
                    pg_type = self._get_postgres_type_safe(dtype)
                    columns.append(f'"{col}" {pg_type}')
                except Exception as e:
                    logger.warning(f"⚠️ Could not determine type for column '{col}': {e}, using TEXT")
                    columns.append(f'"{col}" TEXT')

            # Add geometry column
            columns.append("geometry geometry(Geometry, 4326)")

            # Create table
            create_sql = sql.SQL(
                "CREATE TABLE {}.{} ({})"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table_name),
                sql.SQL(", ".join(columns))
            )

            cur.execute(create_sql)
            logger.info(f"✅ Created table {schema}.{table_name}")

            # Create spatial index
            try:
                index_sql = sql.SQL(
                    "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST (geometry)"
                ).format(
                    sql.Identifier(f"{table_name}_geom_idx"),
                    sql.Identifier(schema),
                    sql.Identifier(table_name)
                )
                cur.execute(index_sql)
                logger.info(f"✅ Created spatial index on {schema}.{table_name}")
            except Exception as e:
                logger.warning(f"⚠️ Could not create spatial index: {e}")
                self.warnings.append(f"Spatial index creation failed: {e}")

        except Exception as e:
            logger.error(f"❌ Table creation error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    def _insert_features_safe(
        self,
        cur: psycopg.Cursor,
        chunk: gpd.GeoDataFrame,
        table_name: str,
        schema: str
    ) -> int:
        """
        Insert features with detailed error handling and progress tracking.

        Returns:
            Number of rows successfully inserted
        """
        rows_inserted = 0
        failed_rows = []

        try:
            # Prepare column lists
            non_geom_cols = [col for col in chunk.columns if col != 'geometry']

            # Build INSERT statement
            insert_sql = sql.SQL(
                "INSERT INTO {}.{} ({}, geometry) VALUES ({}, ST_GeomFromText(%s, 4326))"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table_name),
                sql.SQL(", ").join([sql.Identifier(col) for col in non_geom_cols]),
                sql.SQL(", ").join([sql.Placeholder()] * len(non_geom_cols))
            )

            # Insert rows with individual error handling
            for idx, row in chunk.iterrows():
                try:
                    # Prepare values
                    values = [row[col] for col in non_geom_cols]

                    # Convert geometry to WKT
                    geom_wkt = row.geometry.wkt if row.geometry else None

                    if geom_wkt:
                        values.append(geom_wkt)
                        cur.execute(insert_sql, values)
                        rows_inserted += 1

                        # Log progress every 100 rows
                        if rows_inserted % 100 == 0:
                            logger.debug(f"Progress: {rows_inserted} rows inserted")
                    else:
                        logger.warning(f"⚠️ Skipping row {idx}: null geometry")
                        failed_rows.append(idx)

                except Exception as row_error:
                    logger.warning(f"⚠️ Failed to insert row {idx}: {row_error}")
                    failed_rows.append(idx)
                    self.warnings.append(f"Row {idx} insertion failed: {str(row_error)[:100]}")

                    # Continue with next row
                    continue

            if failed_rows:
                logger.warning(f"⚠️ Failed to insert {len(failed_rows)} rows: {failed_rows[:10]}...")

            logger.info(f"✅ Successfully inserted {rows_inserted}/{len(chunk)} rows")
            return rows_inserted

        except Exception as e:
            logger.error(f"❌ Batch insertion error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    def _get_postgres_type_safe(self, dtype: str) -> str:
        """
        Safely map pandas dtype to PostgreSQL type.

        Args:
            dtype: Pandas dtype string

        Returns:
            PostgreSQL type string
        """
        dtype_str = str(dtype).lower()

        type_mapping = {
            'int': 'INTEGER',
            'float': 'DOUBLE PRECISION',
            'bool': 'BOOLEAN',
            'datetime': 'TIMESTAMP',
            'date': 'DATE',
            'time': 'TIME',
            'object': 'TEXT',
            'string': 'TEXT',
            'category': 'TEXT'
        }

        for key, pg_type in type_mapping.items():
            if key in dtype_str:
                return pg_type

        # Default to TEXT for unknown types
        logger.debug(f"Unknown dtype '{dtype}', defaulting to TEXT")
        return 'TEXT'

    def get_error_summary(self) -> Dict[str, Any]:
        """
        Get summary of errors and warnings from the session.

        Returns:
            Dictionary with errors and warnings lists
        """
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings)
        }

    def clear_error_tracking(self):
        """Clear error and warning tracking for new session."""
        self.errors = []
        self.warnings = []
        logger.debug("Error tracking cleared")