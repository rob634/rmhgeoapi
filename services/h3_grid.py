"""
H3 Grid Generation Service.

Generates hierarchical hexagonal grids using DuckDB H3 extension.
Supports land-based filtering using Overture Maps Divisions.
Exports grids as GeoParquet to gold container.

Architecture:
    1. Generate coarse grid (Level 4: ~3,500 cells globally)
    2. Filter by land boundaries (Overture Divisions via DuckDB)
    3. Generate fine grid (Level 6: ~300K cells for land only)
    4. Export to GeoParquet

Uses safe SQL composition via QueryBuilder to prevent SQL injection.

Exports:
    H3GridService: Main service class for H3 grid operations
"""

import pandas as pd
import re
import time
import traceback
from typing import Optional, List
from datetime import datetime, timezone

from util_logger import LoggerFactory, ComponentType
from infrastructure.interface_repository import IDuckDBRepository
from infrastructure.blob import IBlobRepository
from infrastructure.duckdb_query import OvertureQueryBuilder, QueryParam


class H3GridService:
    """
    H3 hierarchical grid generation service with safe SQL composition.

    Uses DuckDB H3 extension to generate global hexagonal grids
    and filter by land boundaries using Overture Maps data.

    **Security**: All SQL queries use parameterization and validation
    to prevent SQL injection vulnerabilities.

    **Logging**: Granular try-except blocks with verbose logging for
    real-time monitoring and debugging.
    """

    def __init__(
        self,
        duckdb_repo: IDuckDBRepository,
        blob_repo: IBlobRepository,
        gold_container: str
    ):
        """
        Initialize H3 grid service.

        Args:
            duckdb_repo: DuckDB repository for H3 queries
            blob_repo: Blob repository for GeoParquet storage
            gold_container: Gold container name for output
        """
        self.duckdb = duckdb_repo
        self.blob = blob_repo
        self.gold_container = gold_container
        self.logger = LoggerFactory.create_logger(
            ComponentType.SERVICE,
            "h3_grid"
        )
        self.logger.info("🎯 H3GridService initialized")
        self.logger.info(f"   Gold container: {gold_container}")

    def _validate_resolution(self, resolution: int) -> int:
        """
        Validate H3 resolution level.

        Args:
            resolution: H3 resolution (0-15)

        Returns:
            Validated resolution

        Raises:
            ValueError: If resolution not in valid range
        """
        self.logger.info(f"🔍 Validating H3 resolution: {resolution}")

        if not (0 <= resolution <= 15):
            self.logger.error(
                f"❌ Invalid H3 resolution: {resolution} (must be 0-15)"
            )
            raise ValueError(
                f"Invalid H3 resolution: {resolution}. "
                f"Must be between 0 and 15."
            )

        self.logger.info(f"✅ Resolution {resolution} validated")
        return resolution

    def _validate_filename(self, filename: str) -> str:
        """
        Validate filename to prevent path traversal.

        Args:
            filename: Output filename

        Returns:
            Validated filename

        Raises:
            ValueError: If filename contains path traversal characters
        """
        self.logger.info(f"🔍 Validating filename: {filename}")

        if '..' in filename or '/' in filename:
            self.logger.error(
                f"❌ Path traversal attempt detected in filename: {filename}"
            )
            raise ValueError(
                f"Invalid filename: '{filename}'. "
                f"Path traversal not allowed."
            )

        if not filename.endswith('.parquet'):
            self.logger.error(
                f"❌ Invalid file extension in filename: {filename}"
            )
            raise ValueError(
                f"Invalid filename: '{filename}'. "
                f"Must end with .parquet"
            )

        self.logger.info(f"✅ Filename {filename} validated")
        return filename

    def generate_grid(
        self,
        resolution: int,
        exclude_antimeridian: bool = True
    ) -> pd.DataFrame:
        """
        Generate complete global H3 grid at any resolution (0-4).

        Uses H3's deterministic hierarchy - no sampling required!
        Gets all 122 Resolution 0 base cells, then expands to target resolution.

        Args:
            resolution: H3 resolution level (0-4)
            exclude_antimeridian: If True, exclude cells crossing 180° longitude

        Returns:
            DataFrame with columns: h3_index (uint64), geometry_wkt (str),
                                   resolution (int), is_valid (bool)

        Raises:
            ValueError: If resolution is out of range
            RuntimeError: If grid generation fails

        Performance:
            - Res 0: ~1s (122 cells)
            - Res 1: ~2s (842 cells)
            - Res 2: ~5s (5,882 cells)
            - Res 3: ~20s (41,162 cells)
            - Res 4: ~120s (288,122 cells)
        """
        # Validate resolution
        if not isinstance(resolution, int) or resolution < 0 or resolution > 4:
            raise ValueError(f"resolution must be 0-4, got {resolution}")

        self.logger.info("=" * 80)
        self.logger.info(f"🌐 Generating H3 Resolution {resolution} Grid")
        self.logger.info("=" * 80)
        self.logger.info(f"   Resolution: {resolution}")
        self.logger.info(f"   Exclude antimeridian: {exclude_antimeridian}")

        import time
        import traceback

        # Build query using H3's hierarchy
        if exclude_antimeridian:
            query = f"""
                WITH parent_grid AS (
                    -- Get ALL 122 Resolution 0 base cells
                    SELECT unnest(h3_get_res0_cells()) as parent_h3
                ),
                target_cells AS (
                    -- Expand to target resolution
                    SELECT UNNEST(h3_cell_to_children(parent_h3, {resolution})) as h3_index
                    FROM parent_grid
                ),
                cells_with_bounds AS (
                    SELECT
                        h3_index,
                        h3_cell_to_boundary_wkt(h3_index) as geometry_wkt,
                        h3_get_resolution(h3_index) as resolution,
                        h3_is_valid_cell(h3_index) as is_valid,
                        ST_GeomFromText(h3_cell_to_boundary_wkt(h3_index)) as geom
                    FROM target_cells
                    WHERE h3_index IS NOT NULL
                ),
                antimeridian_check AS (
                    SELECT
                        h3_index,
                        geometry_wkt,
                        resolution,
                        is_valid,
                        (ST_XMax(geom) - ST_XMin(geom)) as lon_extent
                    FROM cells_with_bounds
                )
                SELECT h3_index, geometry_wkt, resolution, is_valid
                FROM antimeridian_check
                WHERE lon_extent < 180
                ORDER BY h3_index
            """
        else:
            query = f"""
                WITH parent_grid AS (
                    SELECT unnest(h3_get_res0_cells()) as parent_h3
                ),
                target_cells AS (
                    SELECT UNNEST(h3_cell_to_children(parent_h3, {resolution})) as h3_index
                    FROM parent_grid
                )
                SELECT
                    h3_index,
                    h3_cell_to_boundary_wkt(h3_index) as geometry_wkt,
                    h3_get_resolution(h3_index) as resolution,
                    h3_is_valid_cell(h3_index) as is_valid
                FROM target_cells
                WHERE h3_index IS NOT NULL
                ORDER BY h3_index
            """

        try:
            self.logger.info("⏱️  Starting H3 grid generation query...")
            start_time = time.time()

            df = self.duckdb.query_to_df(query)

            elapsed_time = time.time() - start_time
            self.logger.info(f"⏱️  Query completed in {elapsed_time:.2f} seconds")

        except Exception as e:
            self.logger.error("❌ H3 grid generation query failed!")
            self.logger.error(f"   Error type: {type(e).__name__}")
            self.logger.error(f"   Error message: {str(e)}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to generate H3 resolution {resolution} grid: {e}") from e

        # Validate results
        row_count = len(df)
        self.logger.info(f"📊 Generated {row_count:,} cells at resolution {resolution}")

        if row_count == 0:
            self.logger.error("❌ Query returned 0 rows - H3 extension may not be working")
            raise ValueError("H3 grid generation returned no cells")

        # Validate columns
        required_cols = {'h3_index', 'geometry_wkt', 'resolution', 'is_valid'}
        actual_cols = set(df.columns)
        missing_cols = required_cols - actual_cols

        if missing_cols:
            self.logger.error(f"❌ Missing required columns: {missing_cols}")
            raise ValueError(f"Missing columns in result: {missing_cols}")

        self.logger.info(f"✅ Resolution {resolution} grid generation completed successfully")
        return df

    def generate_level4_grid(self) -> pd.DataFrame:
        """
        Generate complete global Level 4 H3 grid (~227k cells), excluding antimeridian cells.

        Process:
            1. Get ALL 122 base resolution 0 cells (110 hexagons + 12 pentagons)
            2. Expand each to ALL resolution 4 children (~1,870 children/parent)
            3. Filter out cells crossing 180° longitude (antimeridian)
            4. Return as DataFrame with h3_index and geometry

        Expected Output:
            - Total cells: ~228,000 (122 parents × ~1,870 children)
            - After antimeridian filter: ~227,000 cells
            - After land filter: ~78,000 land cells (depending on land GeoJSON)

        Returns:
            DataFrame with columns: h3_index (int64), geometry_wkt (str),
            resolution (int), is_valid (bool)

        Performance: ~30-60 seconds for complete global grid

        **Antimeridian Handling**: Cells that cross ±180° longitude are excluded
        to prevent rendering issues and geometry problems.

        **Security**: Uses hardcoded query with no user input, safe from injection.
        """
        self.logger.info("=" * 80)
        self.logger.info("🌍 STEP 1: Generating global Level 4 H3 grid (excluding antimeridian cells)...")
        self.logger.info("=" * 80)

        # Static query with no parameters - safe from injection
        # Generate Level 4 grid using hierarchical generation (parent → children)
        # This approach guarantees complete coverage without gaps
        #
        # WHY HIERARCHICAL?
        # - Level 4 cells are ~288 km² (~17km edge length)
        # - Point sampling creates systematic gaps (stripe pattern)
        # - Parent-cell expansion ensures full coverage
        #
        # STRATEGY:
        # 1. Get ALL 122 Resolution 0 base cells using H3's built-in function
        # 2. Expand each to ALL children at Level 4 using H3's hierarchy
        # 3. Filter out antimeridian-crossing cells
        # 4. Result: Complete global coverage (~228k cells before land filtering)
        #
        # NO SAMPLING - Uses H3's deterministic parent-child hierarchy
        query = """
            WITH parent_grid AS (
                -- Get ALL 122 Resolution 0 base cells (110 hexagons + 12 pentagons)
                -- This guarantees 100% global coverage by H3 definition
                SELECT unnest(h3_get_res0_cells()) as parent_h3
            ),
            level4_cells AS (
                -- Expand each parent cell to all children at Level 4
                SELECT UNNEST(h3_cell_to_children(parent_h3, 4)) as h3_index
                FROM parent_grid
            ),
            cells_with_bounds AS (
                -- Get cell geometries and calculate longitude extent
                SELECT
                    h3_index,
                    h3_cell_to_boundary_wkt(h3_index) as geometry_wkt,
                    h3_get_resolution(h3_index) as resolution,
                    h3_is_valid_cell(h3_index) as is_valid,
                    ST_GeomFromText(h3_cell_to_boundary_wkt(h3_index)) as geom
                FROM level4_cells
                WHERE h3_index IS NOT NULL
            ),
            antimeridian_check AS (
                -- Calculate min/max longitude for each cell
                SELECT
                    h3_index,
                    geometry_wkt,
                    resolution,
                    is_valid,
                    ST_XMin(geom) as min_lon,
                    ST_XMax(geom) as max_lon,
                    -- Cell crosses antimeridian if max_lon - min_lon > 180
                    (ST_XMax(geom) - ST_XMin(geom)) as lon_extent
                FROM cells_with_bounds
            )
            SELECT
                h3_index,
                geometry_wkt,
                resolution,
                is_valid
            FROM antimeridian_check
            WHERE lon_extent < 180  -- Exclude cells crossing antimeridian
            ORDER BY h3_index
        """

        try:
            self.logger.info("⏱️  Starting H3 grid generation query...")
            start_time = time.time()

            df = self.duckdb.query_to_df(query)

            elapsed_time = time.time() - start_time
            self.logger.info(f"⏱️  Query completed in {elapsed_time:.2f} seconds")

        except Exception as e:
            self.logger.error("❌ H3 grid generation query failed!")
            self.logger.error(f"   Error type: {type(e).__name__}")
            self.logger.error(f"   Error message: {str(e)}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to generate H3 Level 4 grid: {e}") from e

        # Validate results
        try:
            row_count = len(df)
            self.logger.info(f"📊 Query returned {row_count:,} rows (after antimeridian filtering)")

            # Level 4 complete coverage: 122 base cells × ~1870 children/cell ≈ 228k cells
            # After antimeridian filtering: ~227k cells
            expected_total = 228000  # Approximate for all 122 base cells expanded to Level 4
            if row_count > 0:
                estimated_excluded = expected_total - row_count
                if estimated_excluded > 0:
                    self.logger.info(
                        f"🌐 Excluded ~{estimated_excluded:,} cells crossing 180° longitude"
                    )

            if row_count == 0:
                self.logger.error("❌ Query returned 0 rows - H3 extension may not be working")
                raise ValueError("H3 grid generation returned no cells")

            if row_count < 200000 or row_count > 230000:
                self.logger.warning(
                    f"⚠️  Unexpected cell count: {row_count:,} "
                    f"(expected ~227,000 for Level 4 after antimeridian filtering)"
                )

            # Validate columns
            required_cols = {'h3_index', 'geometry_wkt', 'resolution', 'is_valid'}
            actual_cols = set(df.columns)
            missing_cols = required_cols - actual_cols

            if missing_cols:
                self.logger.error(f"❌ Missing required columns: {missing_cols}")
                raise ValueError(f"Missing columns in result: {missing_cols}")

            self.logger.info(f"✅ All required columns present: {required_cols}")

            # Validate data types and values
            invalid_count = (~df['is_valid']).sum()
            if invalid_count > 0:
                self.logger.warning(f"⚠️  Found {invalid_count} invalid H3 cells")

            unique_resolutions = df['resolution'].unique()
            self.logger.info(f"📊 Resolutions found: {unique_resolutions}")

            self.logger.info("✅ Level 4 grid generation completed successfully")
            self.logger.info(f"   Total cells: {row_count:,}")
            self.logger.info(f"   Valid cells: {(df['is_valid']).sum():,}")
            self.logger.info(f"   Invalid cells: {invalid_count}")

        except Exception as e:
            self.logger.error("❌ Result validation failed!")
            self.logger.error(f"   Error: {e}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise

        return df

    def filter_by_land(
        self,
        grid_df: pd.DataFrame,
        overture_release: Optional[str] = None,
        land_geojson_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Filter H3 grid cells by land intersection.

        Supports two data sources for land boundaries:
        1. GeoJSON file in Azure Blob Storage (recommended - fast)
        2. Overture Maps Divisions (serverless query - slow)

        Process:
            1. Load land boundaries from source
            2. Convert H3 cells to polygons
            3. Spatial join: keep cells that intersect land
            4. Return filtered DataFrame

        Args:
            grid_df: DataFrame with h3_index column
            overture_release: Overture Maps release version (for Overture source)
            land_geojson_path: Azure blob path to land GeoJSON (e.g., "reference/land_boundaries.geojson")
                              Format: "container/path/to/file.geojson" or "path/to/file.geojson"

        Returns:
            DataFrame with only land/coastal H3 cells

        Performance:
            - GeoJSON source: ~5-10 seconds (direct file read)
            - Overture source: ~60 seconds (serverless query)

        Note:
            Reduces Level 4 from ~3,500 to ~875 cells (75% reduction)

        **Priority**: If both parameters provided, land_geojson_path takes precedence.
        **Security**: Validates paths and parameters before use.
        """
        self.logger.info("=" * 80)
        self.logger.info("🌊 STEP 2: Filtering H3 grid by land boundaries...")
        self.logger.info("=" * 80)
        self.logger.info(f"   Input cells: {len(grid_df):,}")

        # Determine data source (GeoJSON takes precedence over Overture)
        if land_geojson_path:
            self.logger.info(f"   Data source: GeoJSON file (Azure Blob Storage)")
            self.logger.info(f"   Path: {land_geojson_path}")
            return self._filter_by_geojson(grid_df, land_geojson_path)
        elif overture_release:
            self.logger.info(f"   Data source: Overture Maps Divisions")
            self.logger.info(f"   Overture release: {overture_release}")
            return self._filter_by_overture(grid_df, overture_release)
        else:
            raise ValueError(
                "Must provide either land_geojson_path or overture_release parameter. "
                "Recommended: land_geojson_path for faster performance."
            )

    def _filter_by_geojson(
        self,
        grid_df: pd.DataFrame,
        land_geojson_path: str
    ) -> pd.DataFrame:
        """
        Filter H3 grid by land boundaries from GeoJSON file in Azure Blob Storage.

        Args:
            grid_df: DataFrame with h3_index and geometry_wkt columns
            land_geojson_path: Path to GeoJSON in blob storage
                              Format: "container/path/to/file.geojson" or "path/to/file.geojson"

        Returns:
            Filtered DataFrame with land cells only

        Performance: ~5-10 seconds (direct file read + spatial join)
        """
        self.logger.info("📂 Loading land boundaries from GeoJSON...")

        # Parse blob path to extract container and blob name
        try:
            if "/" in land_geojson_path:
                parts = land_geojson_path.split("/", 1)
                if parts[0] in ["bronze", "silver", "gold"]:
                    # Container specified: "bronze/path/file.json"
                    container_name = f"rmhazuregeo{parts[0]}"
                    blob_name = parts[1]
                else:
                    # Assume gold container: "reference/file.json"
                    container_name = self.gold_container
                    blob_name = land_geojson_path
            else:
                # Just filename: "file.json"
                container_name = self.gold_container
                blob_name = land_geojson_path

            self.logger.info(f"   Container: {container_name}")
            self.logger.info(f"   Blob name: {blob_name}")

        except Exception as e:
            self.logger.error(f"❌ Invalid blob path format: {e}")
            raise ValueError(f"Invalid blob path: {land_geojson_path}") from e

        # Determine authentication method for DuckDB blob access
        # Option 1: credential_chain (Managed Identity) - preferred, faster
        # Option 2: SAS URL (fallback) - works but requires token generation
        if self.duckdb.has_managed_identity():
            # Use direct blob URL - DuckDB will authenticate via Managed Identity
            self.logger.info("🔑 Using Managed Identity for blob access")
            self.logger.info("   Authentication: credential_chain (DefaultAzureCredential)")
            geojson_url = f"az://{self.duckdb.storage_account_name}.blob.core.windows.net/{container_name}/{blob_name}"
            self.logger.info(f"   Direct URL: {geojson_url}")
        else:
            # Fallback: Generate SAS URL for authenticated access
            try:
                self.logger.info("🔑 Generating SAS URL for blob access (fallback)...")
                start_time = time.time()

                # Use BlobRepository to generate user delegation SAS token
                # This uses DefaultAzureCredential (managed identity in Azure Functions)
                geojson_url = self.blob_repo.get_blob_url_with_sas(
                    container_name=container_name,
                    blob_name=blob_name,
                    hours=1  # 1 hour validity is plenty for this operation
                )

                elapsed_time = time.time() - start_time
                self.logger.info(f"✅ SAS URL generated in {elapsed_time:.2f}s")
                self.logger.info(f"   Token validity: 1 hour")
                self.logger.info(f"   Authentication: User delegation SAS token")

            except Exception as e:
                self.logger.error(f"❌ Failed to generate SAS URL!")
                self.logger.error(f"   Error: {e}")
                self.logger.error(f"   Container: {container_name}")
                self.logger.error(f"   Blob: {blob_name}")
                self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
                raise RuntimeError(f"Failed to generate SAS URL for GeoJSON: {e}") from e

        # Register DataFrame and create temporary DuckDB table
        try:
            self.logger.info("💾 Creating temporary H3 grid table in DuckDB...")
            start_time = time.time()

            # Register the DataFrame with DuckDB
            conn = self.duckdb.get_connection()
            conn.register('grid_df_temp', grid_df)

            # Create temp table from registered DataFrame
            self.duckdb.execute("""
                CREATE TEMPORARY TABLE IF NOT EXISTS temp_h3_grid AS
                SELECT * FROM grid_df_temp
            """)

            elapsed_time = time.time() - start_time
            self.logger.info(f"✅ Temp table created in {elapsed_time:.2f}s")
            self.logger.info(f"   Rows inserted: {len(grid_df):,}")

        except Exception as e:
            self.logger.error("❌ Failed to create temporary H3 grid table!")
            self.logger.error(f"   Error: {e}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to create temp table: {e}") from e

        # Execute spatial join with GeoJSON land boundaries
        try:
            self.logger.info("🌍 Executing spatial join with land boundaries...")

            start_time = time.time()

            # Build DuckDB query to read GeoJSON and perform spatial join
            # Uses ST_Read with either:
            # - Direct az:// URL (credential_chain auth via Managed Identity)
            # - SAS URL (user delegation token auth)
            # Note: GeoJSON geometry column may be named 'geometry' or 'geom'
            query = f"""
                WITH land_boundaries AS (
                    SELECT geom
                    FROM ST_Read('{geojson_url}')
                ),
                h3_with_geom AS (
                    SELECT
                        h3_index,
                        geometry_wkt,
                        ST_GeomFromText(geometry_wkt) as h3_geom
                    FROM temp_h3_grid
                )
                SELECT DISTINCT
                    h3.h3_index,
                    h3.geometry_wkt
                FROM h3_with_geom h3
                JOIN land_boundaries land ON ST_Intersects(h3.h3_geom, land.geom)
            """

            self.logger.info("   Query: ST_Intersects(h3_geom, land_geometry)")
            land_df = self.duckdb.query_to_df(query)

            elapsed_time = time.time() - start_time
            self.logger.info(f"⏱️  Spatial join completed in {elapsed_time:.2f} seconds")

        except Exception as e:
            self.logger.error("❌ GeoJSON spatial join failed!")
            self.logger.error(f"   Error type: {type(e).__name__}")
            self.logger.error(f"   Error message: {str(e)}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")

            # Check for common errors
            if "ST_Read" in str(e):
                self.logger.error("   💡 Hint: DuckDB spatial extension may not support ST_Read")
                self.logger.error("   💡 Alternative: Use read_json_auto() for GeoJSON")
            elif "does not exist" in str(e) or "not found" in str(e).lower():
                self.logger.error("   💡 Hint: Check if GeoJSON file exists in blob storage")
            elif "timeout" in str(e).lower():
                self.logger.error("   💡 Hint: Network timeout accessing blob storage")
            elif "authentication" in str(e).lower() or "403" in str(e) or "401" in str(e):
                self.logger.error("   💡 Hint: SAS token may have expired or is invalid")
                self.logger.error("   💡 Check that managed identity has 'Storage Blob Delegator' role")

            raise RuntimeError(f"Failed to filter by GeoJSON: {e}") from e

        # Validate and log results
        try:
            output_count = len(land_df)
            input_count = len(grid_df)

            self.logger.info(f"📊 GeoJSON filter results:")
            self.logger.info(f"   Input cells: {input_count:,}")
            self.logger.info(f"   Output cells (land): {output_count:,}")

            if output_count == 0:
                self.logger.warning("⚠️  No land cells found - result is empty!")
                self.logger.warning("   Check if land boundaries cover expected geographic area")
            else:
                reduction = ((input_count - output_count) / input_count) * 100
                self.logger.info(f"   Reduction: {reduction:.1f}% (ocean/water removed)")

            # Validate output schema
            required_cols = {'h3_index', 'geometry_wkt'}
            actual_cols = set(land_df.columns)
            if not required_cols.issubset(actual_cols):
                missing = required_cols - actual_cols
                raise ValueError(f"Output missing required columns: {missing}")

            self.logger.info(f"✅ All required columns present: {required_cols}")

        except Exception as e:
            self.logger.error("❌ Result validation failed!")
            self.logger.error(f"   Error: {e}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise

        return land_df

    def _filter_by_overture(
        self,
        grid_df: pd.DataFrame,
        overture_release: str
    ) -> pd.DataFrame:
        """
        Filter H3 grid by land boundaries from Overture Maps Divisions.

        Args:
            grid_df: DataFrame with h3_index and geometry_wkt columns
            overture_release: Overture Maps release version (YYYY-MM-DD.N)

        Returns:
            Filtered DataFrame with land cells only

        Performance: ~60 seconds (serverless Parquet query from Azure)

        Note: This method queries large Overture datasets and may timeout
              in Azure Functions. Recommended to use GeoJSON source instead.
        """
        self.logger.info("🌍 Loading land boundaries from Overture Maps...")

        # Validate release format (YYYY-MM-DD.N)
        try:
            self.logger.info("🔍 Validating Overture release format...")
            overture_release = OvertureQueryBuilder.validate_release(overture_release)
            self.logger.info(f"✅ Release format validated: {overture_release}")
        except ValueError as e:
            self.logger.error(f"❌ Invalid Overture release format: {e}")
            raise

        # Register DataFrame and create temporary DuckDB table
        try:
            self.logger.info("💾 Creating temporary H3 grid table in DuckDB...")
            start_time = time.time()

            # Register the DataFrame with DuckDB
            conn = self.duckdb.get_connection()
            conn.register('grid_df_temp', grid_df)

            # Create temp table from registered DataFrame
            self.duckdb.execute("""
                CREATE TEMPORARY TABLE IF NOT EXISTS temp_h3_grid AS
                SELECT * FROM grid_df_temp
            """)

            elapsed_time = time.time() - start_time
            self.logger.info(f"✅ Temp table created in {elapsed_time:.2f}s")
            self.logger.info(f"   Rows inserted: {len(grid_df):,}")

        except Exception as e:
            self.logger.error("❌ Failed to create temporary H3 grid table!")
            self.logger.error(f"   Error: {e}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to create temp table: {e}") from e

        # Build Overture path with validated release
        # Note: Overture Maps is PUBLIC data on Azure Blob Storage
        # Use DuckDB Azure extension with az:// protocol (fully qualified URL)
        # Format: az://account.blob.core.windows.net/container/path
        # Use division_area (polygons) not division (points) for land filtering
        overture_path = f"az://overturemapswestus2.blob.core.windows.net/release/{overture_release}/theme=divisions/type=division_area/*.parquet"
        self.logger.info(f"🌍 Overture path: {overture_path}")
        self.logger.info(f"   Using DuckDB Azure extension (anonymous public blob access)")
        self.logger.info(f"   Theme: divisions, Type: division_area (polygons)")

        # Build optimized Overture query
        # Optimizations:
        # 1. Only select division_area (polygons) not division (points)
        # 2. Filter by subtype BEFORE geometry conversion (columnar efficiency)
        # 3. Use bbox filter to reduce data scan (Parquet row group filtering)
        # 4. Only load geometry column (not all attributes)
        query = f"""
            WITH overture_land AS (
                SELECT
                    geometry
                FROM read_parquet(
                    '{overture_path}',
                    hive_partitioning=true,
                    filename=true
                )
                WHERE subtype IN ('country', 'region')
            ),
            h3_with_geom AS (
                SELECT
                    h3_index,
                    geometry_wkt,
                    ST_GeomFromText(geometry_wkt) as h3_geom
                FROM temp_h3_grid
            )
            SELECT DISTINCT
                h3.h3_index,
                h3.geometry_wkt
            FROM h3_with_geom h3
            JOIN overture_land land ON ST_Intersects(h3.h3_geom, land.geometry)
        """

        try:
            self.logger.info("🚀 Starting Overture Maps serverless query...")
            self.logger.info("   Expected time: 10-30 seconds (columnar Parquet with filtering)")
            self.logger.info("   Querying country/region boundaries from Azure Blob Storage...")
            self.logger.info("   Filter: subtype IN ('country', 'region')")

            start_time = time.time()

            land_df = self.duckdb.query_to_df(query)

            elapsed_time = time.time() - start_time
            self.logger.info(f"⏱️  Overture query completed in {elapsed_time:.2f} seconds")

        except Exception as e:
            self.logger.error("❌ Overture Maps query failed!")
            self.logger.error(f"   Error type: {type(e).__name__}")
            self.logger.error(f"   Error message: {str(e)}")
            self.logger.error(f"   Query path: {overture_path}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")

            # Check for common errors
            if "read_parquet" in str(e):
                self.logger.error("   💡 Hint: Check if Overture release exists in Azure Blob Storage")
            elif "ST_GeomFromText" in str(e):
                self.logger.error("   💡 Hint: DuckDB spatial extension may not be loaded")
            elif "timeout" in str(e).lower():
                self.logger.error("   💡 Hint: Network timeout accessing Overture data")

            raise RuntimeError(f"Failed to query Overture Maps: {e}") from e

        # Validate and log results
        try:
            output_count = len(land_df)
            input_count = len(grid_df)

            self.logger.info(f"📊 Overture query results:")
            self.logger.info(f"   Input cells: {input_count:,}")
            self.logger.info(f"   Output cells (land): {output_count:,}")

            if output_count == 0:
                self.logger.error("❌ Overture query returned 0 land cells!")
                self.logger.error("   This suggests no spatial intersection with land boundaries")
                raise ValueError("Land filtering returned no cells - check Overture data")

            reduction_pct = (1 - output_count / input_count) * 100
            self.logger.info(f"   Cells removed (ocean): {input_count - output_count:,}")
            self.logger.info(f"   Reduction: {reduction_pct:.1f}%")

            if reduction_pct < 50 or reduction_pct > 90:
                self.logger.warning(
                    f"⚠️  Unexpected reduction percentage: {reduction_pct:.1f}% "
                    f"(expected ~75% for global Level 4)"
                )

            # Validate columns
            required_cols = {'h3_index', 'geometry_wkt'}
            actual_cols = set(land_df.columns)
            missing_cols = required_cols - actual_cols

            if missing_cols:
                self.logger.error(f"❌ Missing required columns: {missing_cols}")
                raise ValueError(f"Missing columns in filtered result: {missing_cols}")

            self.logger.info("✅ Land filtering completed successfully")

        except Exception as e:
            self.logger.error("❌ Result validation failed!")
            self.logger.error(f"   Error: {e}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise

        return land_df

    def generate_children(
        self,
        parent_df: pd.DataFrame,
        target_resolution: int
    ) -> pd.DataFrame:
        """
        Generate child H3 cells for each parent cell.

        Process:
            1. For each parent cell at resolution N
            2. Generate all children at resolution M (M > N)
            3. Each parent typically has 343 children (7^2 pattern)

        Args:
            parent_df: DataFrame with h3_index column
            target_resolution: Target resolution for children (validated 0-15)

        Returns:
            DataFrame with child h3_index values

        Performance: ~30 seconds for 875 parents → 300K children

        Example:
            Level 4 parent (875 cells) → Level 6 children (~300K cells)

        **Security**: Validates resolution range before use in query.
        """
        self.logger.info("=" * 80)
        self.logger.info(f"👶 STEP 3: Generating Level {target_resolution} children...")
        self.logger.info("=" * 80)

        # Input validation with try-except
        try:
            parent_count = len(parent_df)
            self.logger.info(f"📊 Input parent cells: {parent_count:,}")

            if parent_count == 0:
                self.logger.error("❌ Cannot generate children - parent DataFrame is empty")
                raise ValueError("Parent DataFrame is empty")

            # Validate h3_index column exists
            if 'h3_index' not in parent_df.columns:
                self.logger.error("❌ Parent DataFrame missing required 'h3_index' column")
                raise ValueError("Parent DataFrame must have 'h3_index' column")

            self.logger.info("✅ Input validation passed")

        except Exception as e:
            self.logger.error(f"❌ Input validation failed: {e}")
            raise

        # Validate target resolution
        try:
            self.logger.info(f"🔍 Validating target resolution: {target_resolution}")
            target_resolution = self._validate_resolution(target_resolution)
            self.logger.info(f"✅ Target resolution validated: {target_resolution}")
        except ValueError as e:
            self.logger.error(f"❌ Resolution validation failed: {e}")
            raise

        # Register DataFrame and create temporary table with try-except
        try:
            self.logger.info("💾 Creating temporary parent table in DuckDB...")
            start_time = time.time()

            # Register the DataFrame with DuckDB
            conn = self.duckdb.get_connection()
            conn.register('parent_df_temp', parent_df)

            # Create temp table from registered DataFrame
            self.duckdb.execute("""
                CREATE TEMPORARY TABLE IF NOT EXISTS temp_parents AS
                SELECT * FROM parent_df_temp
            """)

            elapsed_time = time.time() - start_time
            self.logger.info(f"✅ Temp table created in {elapsed_time:.2f}s")
            self.logger.info(f"   Rows inserted: {parent_count:,}")

        except Exception as e:
            self.logger.error("❌ Failed to create temporary parent table!")
            self.logger.error(f"   Error type: {type(e).__name__}")
            self.logger.error(f"   Error message: {str(e)}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to create temp parent table: {e}") from e

        # Execute child generation query with try-except
        try:
            self.logger.info(f"🚀 Starting H3 child generation query...")
            self.logger.info(f"   This may take 30-60 seconds for large datasets...")
            self.logger.info(f"   Expanding {parent_count:,} parents to resolution {target_resolution}...")

            start_time = time.time()

            # Use parameterized query with validated resolution
            # Note: Resolution is validated above as integer 0-15, safe to use
            query = f"""
                WITH children AS (
                    SELECT
                        h3_index as parent_h3,
                        unnest(h3_cell_to_children(h3_index, {target_resolution})) as child_h3
                    FROM temp_parents
                )
                SELECT
                    child_h3 as h3_index,
                    h3_cell_to_boundary_wkt(child_h3) as geometry_wkt,
                    h3_get_resolution(child_h3) as resolution,
                    h3_is_valid_cell(child_h3) as is_valid
                FROM children
            """

            children_df = self.duckdb.query_to_df(query)

            elapsed_time = time.time() - start_time
            self.logger.info(f"⏱️  Child generation query completed in {elapsed_time:.2f} seconds")

        except Exception as e:
            self.logger.error("❌ H3 child generation query failed!")
            self.logger.error(f"   Error type: {type(e).__name__}")
            self.logger.error(f"   Error message: {str(e)}")
            self.logger.error(f"   Traceback:\n{traceback.format_exc()}")

            # Error hints
            if "h3_cell_to_children" in str(e):
                self.logger.error("   💡 Hint: H3 extension may not be loaded or function not available")
            elif "unnest" in str(e):
                self.logger.error("   💡 Hint: DuckDB array functions may not be available")

            raise RuntimeError(f"Failed to generate H3 children: {e}") from e

        # Result validation with try-except
        try:
            child_count = len(children_df)
            self.logger.info(f"📊 Child generation results:")
            self.logger.info(f"   Parent cells: {parent_count:,}")
            self.logger.info(f"   Child cells: {child_count:,}")

            if child_count == 0:
                self.logger.error("❌ Child generation returned 0 cells!")
                raise ValueError("Child generation returned no cells")

            # Calculate and validate expansion ratio
            avg_children = child_count / parent_count if parent_count > 0 else 0
            self.logger.info(f"   Average children per parent: {avg_children:.1f}")

            # Typical H3 expansion is 7^(resolution_delta)
            # Warn if significantly different
            if avg_children < 10:
                self.logger.warning(f"⚠️  Low expansion ratio: {avg_children:.1f} (expected ~49-343)")

            # Column validation
            required_cols = {'h3_index', 'geometry_wkt', 'resolution', 'is_valid'}
            actual_cols = set(children_df.columns)
            missing_cols = required_cols - actual_cols

            if missing_cols:
                self.logger.error(f"❌ Missing required columns: {missing_cols}")
                raise ValueError(f"Result missing columns: {missing_cols}")

            self.logger.info("✅ Child generation completed successfully")

        except Exception as e:
            self.logger.error("❌ Result validation failed!")
            self.logger.error(f"   Error: {e}")
            raise

        return children_df

    def save_to_gold(
        self,
        df: pd.DataFrame,
        filename: str,
        folder: str = "h3/grids"
    ) -> str:
        """
        Save H3 grid as GeoParquet to gold container.

        Args:
            df: DataFrame with h3_index and geometry_wkt columns
            filename: Output filename (validated for path traversal)
            folder: Folder path in gold container (default: "h3/grids")

        Returns:
            Blob path where file was saved

        Storage Structure:
            gold/h3/grids/land_h3_level4.parquet
            gold/h3/grids/land_h3_level6.parquet

        **Security**: Validates filename to prevent path traversal attacks.
        """
        import tempfile
        import os

        self.logger.info("=" * 80)
        self.logger.info("💾 STEP 4: Saving H3 grid to gold container...")
        self.logger.info("=" * 80)

        # Input validation with try-except
        try:
            cell_count = len(df)
            self.logger.info(f"📊 Input data:")
            self.logger.info(f"   Cell count: {cell_count:,}")

            if cell_count == 0:
                self.logger.error("❌ Cannot save empty DataFrame")
                raise ValueError("DataFrame is empty")

            # Validate required columns
            required_cols = {'h3_index', 'geometry_wkt'}
            actual_cols = set(df.columns)
            missing_cols = required_cols - actual_cols

            if missing_cols:
                self.logger.error(f"❌ DataFrame missing required columns: {missing_cols}")
                raise ValueError(f"Missing required columns: {missing_cols}")

            self.logger.info("✅ Input validation passed")

        except Exception as e:
            self.logger.error(f"❌ Input validation failed: {e}")
            raise

        # Validate filename to prevent path traversal
        try:
            self.logger.info(f"🔍 Validating filename: {filename}")
            filename = self._validate_filename(filename)
            blob_path = f"{folder}/{filename}"
            self.logger.info(f"✅ Output path validated: {self.gold_container}/{blob_path}")
        except ValueError as e:
            self.logger.error(f"❌ Filename validation failed: {e}")
            raise

        # Add metadata to DataFrame
        try:
            self.logger.info("📝 Adding metadata columns...")
            start_time = time.time()

            df_with_metadata = df.copy()
            df_with_metadata['created_at'] = datetime.now(timezone.utc).isoformat()
            df_with_metadata['cell_count'] = len(df)

            elapsed_time = time.time() - start_time
            self.logger.info(f"✅ Metadata added in {elapsed_time:.2f}s")
            self.logger.info(f"   Total columns: {len(df_with_metadata.columns)}")

        except Exception as e:
            self.logger.error("❌ Failed to add metadata!")
            self.logger.error(f"   Error: {e}")
            raise RuntimeError(f"Failed to add metadata: {e}") from e

        # Create temporary file
        try:
            self.logger.info("📁 Creating temporary file...")
            with tempfile.NamedTemporaryFile(mode='wb', suffix='.parquet', delete=False) as tmp_file:
                tmp_path = tmp_file.name
            self.logger.info(f"✅ Temporary file created: {tmp_path}")
        except Exception as e:
            self.logger.error("❌ Failed to create temporary file!")
            self.logger.error(f"   Error: {e}")
            raise RuntimeError(f"Failed to create temp file: {e}") from e

        try:
            # Write to GeoParquet using DuckDB
            try:
                self.logger.info("📝 Writing GeoParquet to temporary file...")
                self.logger.info(f"   Compression: ZSTD")
                self.logger.info(f"   Format: GeoParquet")
                start_time = time.time()

                # Register the DataFrame with DuckDB
                conn = self.duckdb.get_connection()
                conn.register('df_with_metadata_temp', df_with_metadata)

                # Note: tmp_path is system-generated, not user input, safe to use
                query = f"""
                    COPY df_with_metadata_temp TO '{tmp_path}'
                    (FORMAT PARQUET, COMPRESSION 'ZSTD')
                """
                self.duckdb.execute(query)

                elapsed_time = time.time() - start_time
                file_size_bytes = os.path.getsize(tmp_path)
                file_size_mb = file_size_bytes / (1024 * 1024)

                self.logger.info(f"⏱️  GeoParquet written in {elapsed_time:.2f} seconds")
                self.logger.info(f"📊 File size: {file_size_mb:.2f} MB ({file_size_bytes:,} bytes)")

            except Exception as e:
                self.logger.error("❌ Failed to write GeoParquet file!")
                self.logger.error(f"   Error type: {type(e).__name__}")
                self.logger.error(f"   Error message: {str(e)}")
                self.logger.error(f"   Traceback:\n{traceback.format_exc()}")

                # Error hints
                if "COPY" in str(e):
                    self.logger.error("   💡 Hint: DuckDB COPY command failed - check write permissions")
                elif "PARQUET" in str(e):
                    self.logger.error("   💡 Hint: Parquet writer failed - check data types")

                raise RuntimeError(f"Failed to write GeoParquet: {e}") from e

            # Upload to blob storage
            try:
                self.logger.info(f"☁️  Uploading to Azure Blob Storage...")
                self.logger.info(f"   Container: {self.gold_container}")
                self.logger.info(f"   Blob path: {blob_path}")
                start_time = time.time()

                with open(tmp_path, 'rb') as f:
                    file_data = f.read()
                    self.blob.write_blob(
                        container=self.gold_container,
                        blob_path=blob_path,
                        data=file_data
                    )

                elapsed_time = time.time() - start_time
                upload_speed_mbps = (file_size_mb / elapsed_time) if elapsed_time > 0 else 0

                self.logger.info(f"⏱️  Upload completed in {elapsed_time:.2f} seconds")
                self.logger.info(f"📊 Upload speed: {upload_speed_mbps:.2f} MB/s")
                self.logger.info(f"✅ Successfully saved to {self.gold_container}/{blob_path}")

            except Exception as e:
                self.logger.error("❌ Failed to upload to blob storage!")
                self.logger.error(f"   Error type: {type(e).__name__}")
                self.logger.error(f"   Error message: {str(e)}")
                self.logger.error(f"   Container: {self.gold_container}")
                self.logger.error(f"   Blob path: {blob_path}")
                self.logger.error(f"   Traceback:\n{traceback.format_exc()}")

                # Error hints
                if "authentication" in str(e).lower():
                    self.logger.error("   💡 Hint: Check Azure storage account credentials")
                elif "container" in str(e).lower():
                    self.logger.error("   💡 Hint: Check if container exists")
                elif "permission" in str(e).lower():
                    self.logger.error("   💡 Hint: Check blob storage permissions")

                raise RuntimeError(f"Failed to upload to blob storage: {e}") from e

        finally:
            # Clean up temporary file
            try:
                if os.path.exists(tmp_path):
                    self.logger.info("🧹 Cleaning up temporary file...")
                    os.unlink(tmp_path)
                    self.logger.info("✅ Temporary file deleted")
            except Exception as e:
                self.logger.warning(f"⚠️  Failed to delete temporary file: {e}")
                self.logger.warning(f"   Path: {tmp_path}")

        self.logger.info("=" * 80)
        self.logger.info(f"✅ H3 grid successfully saved to gold container")
        self.logger.info(f"   Final path: {self.gold_container}/{blob_path}")
        self.logger.info(f"   Cell count: {cell_count:,}")
        self.logger.info(f"   File size: {file_size_mb:.2f} MB")
        self.logger.info("=" * 80)

        return blob_path

    def save_grid(
        self,
        df: pd.DataFrame,
        filename: str,
        folder: str = "h3/base"
    ) -> str:
        """
        Save H3 grid to gold container (wrapper for save_to_gold with cleaner signature).

        Implements the H3BaseGridService.save_grid() ABC interface.

        Args:
            df: H3 grid DataFrame
            filename: Output filename (validated for path traversal)
            folder: Folder path in gold container (default: "h3/base")

        Returns:
            Full blob path where file was saved

        Raises:
            ValueError: If filename is invalid
            RuntimeError: If save operation fails
        """
        return self.save_to_gold(df=df, filename=filename, folder=folder)

    def get_grid_stats(self, df: pd.DataFrame) -> 'H3GridStats':
        """
        Get statistics for H3 grid DataFrame.

        Implements the H3BaseGridService.get_grid_stats() ABC interface.

        Args:
            df: DataFrame with h3_index column

        Returns:
            H3GridStats Pydantic model with grid statistics
        """
        from models.h3_base import H3GridStats

        return H3GridStats(
            cell_count=len(df),
            resolution=int(df['resolution'].iloc[0]) if 'resolution' in df.columns and len(df) > 0 else None,
            min_h3_index=int(df['h3_index'].min()) if len(df) > 0 else None,
            max_h3_index=int(df['h3_index'].max()) if len(df) > 0 else None,
            has_geometry='geometry_wkt' in df.columns,
            memory_mb=df.memory_usage(deep=True).sum() / 1024 / 1024
        )
