# ============================================================================
# VECTOR TO POSTGIS HANDLER
# ============================================================================
# STATUS: Service layer - PostGIS vector upload handler
# PURPOSE: Prepare, validate, and upload vector data to PostGIS geo schema
# LAST_REVIEWED: 15 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: VectorToPostGISHandler
# DEPENDENCIES: geopandas, psycopg
# ============================================================================
"""
Vector to PostGIS Handler.

Handles the complete workflow of preparing and uploading vector data to PostGIS:
    1. prepare_gdf: Validate geometries, reproject to EPSG:4326, clean column names
    2. chunk_gdf: Split large GeoDataFrames for parallel processing
    3. upload_chunk: Create table and insert features into PostGIS geo schema

Exports:
    VectorToPostGISHandler: Main handler class for PostGIS vector operations

Dependencies:
    geopandas: GeoDataFrame handling
    psycopg: PostgreSQL database access
    config: Application configuration
    util_logger: Structured logging
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
        if target_database == "public" and config.is_public_database_configured():
            logger.info(f"📊 VectorToPostGISHandler: Using PUBLIC database ({config.public_database.database})")
        else:
            logger.info(f"📊 VectorToPostGISHandler: Using APP database (fallback or explicit)")

        # Warnings from last prepare_gdf call (30 DEC 2025)
        # Callers can check this after prepare_gdf() to include warnings in job results
        self.last_warnings = []

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

        # ========================================================================
        # FIX INVALID GEOMETRIES - Using make_valid() (15 JAN 2026)
        # ========================================================================
        # Shapely's make_valid() is more robust than buffer(0) because:
        # - buffer(0) can collapse thin geometries to nothing
        # - buffer(0) may produce unexpected results with self-intersecting polygons
        # - make_valid() mirrors PostGIS ST_MakeValid() behavior
        # - make_valid() properly handles bowtie polygons, self-intersections, etc.
        #
        # Requires Shapely 1.8+ (available in azgeo environment)
        # ========================================================================
        from shapely.validation import make_valid

        invalid_mask = ~gdf.geometry.is_valid
        invalid_count = invalid_mask.sum()
        if invalid_count > 0:
            logger.warning(f"⚠️  Fixing {invalid_count} invalid geometries using make_valid()")
            gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].apply(make_valid)

            # Verify repair was successful
            still_invalid = (~gdf.geometry.is_valid).sum()
            if still_invalid > 0:
                logger.warning(f"   - {still_invalid} geometries still invalid after make_valid() - may be unfixable")
            else:
                logger.info(f"   - ✅ All {invalid_count} invalid geometries repaired successfully")

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

        # ========================================================================
        # ANTIMERIDIAN FIX - Split geometries crossing 180° longitude (15 JAN 2026)
        # ========================================================================
        # Geometries that cross the antimeridian (dateline) render incorrectly in
        # web maps - their edges span the entire globe instead of wrapping.
        #
        # This fix detects and splits such geometries:
        # - Coords > 180 (data stored in 0-360 range)
        # - Coords < -180 (rare)
        # - Bbox width > 180° (geometry spans the discontinuity)
        #
        # Result: MultiPolygon with parts on each side of the antimeridian,
        # all coordinates in [-180, 180] range.
        # ========================================================================
        from shapely.geometry import LineString, GeometryCollection
        from shapely.ops import split, transform
        from shapely.affinity import translate
        import numpy as np

        def fix_antimeridian(geom):
            """
            Fix geometries that cross the antimeridian (180° longitude).

            Returns: (fixed_geometry, was_fixed)
            """
            bounds = geom.bounds  # (minx, miny, maxx, maxy)
            minx, miny, maxx, maxy = bounds
            width = maxx - minx

            # Detection conditions
            needs_fix = maxx > 180 or minx < -180 or width > 180

            if not needs_fix:
                return geom, False

            # Handle coords > 180: split at antimeridian and shift eastern parts
            if maxx > 180:
                antimeridian = LineString([(180, -90), (180, 90)])
                try:
                    result = split(geom, antimeridian)
                    fixed_parts = []
                    for part in result.geoms:
                        if part.bounds[0] >= 180:
                            part = translate(part, xoff=-360)
                        fixed_parts.append(part)
                    return _combine_antimeridian_parts(fixed_parts), True
                except Exception:
                    return geom, False

            # Handle coords < -180: shift to positive range and recurse
            if minx < -180:
                shifted = translate(geom, xoff=360)
                return fix_antimeridian(shifted)

            # Handle wide bbox (coords jump from ~179 to ~-179)
            if width > 180:
                def unwrap_coords(x, y):
                    """Shift negative longitudes to positive (add 360)"""
                    x = np.array(x)
                    y = np.array(y)
                    x = np.where(x < 0, x + 360, x)
                    return x, y

                unwrapped = transform(unwrap_coords, geom)
                antimeridian = LineString([(180, -90), (180, 90)])
                try:
                    result = split(unwrapped, antimeridian)
                    fixed_parts = []
                    for part in result.geoms:
                        if part.bounds[0] >= 180:
                            part = translate(part, xoff=-360)
                        fixed_parts.append(part)
                    return _combine_antimeridian_parts(fixed_parts), True
                except Exception:
                    return geom, False

            return geom, False

        def _combine_antimeridian_parts(parts):
            """Combine split parts into appropriate geometry type."""
            if len(parts) == 1:
                return parts[0]

            # Flatten nested multi-geometries
            all_geoms = []
            for p in parts:
                if hasattr(p, 'geoms'):
                    all_geoms.extend(p.geoms)
                else:
                    all_geoms.append(p)

            if all(g.geom_type == 'Polygon' for g in all_geoms):
                return MultiPolygon(all_geoms)
            elif all(g.geom_type == 'LineString' for g in all_geoms):
                return MultiLineString(all_geoms)
            elif all(g.geom_type == 'Point' for g in all_geoms):
                return MultiPoint(all_geoms)
            return GeometryCollection(all_geoms)

        # Apply antimeridian fix to all geometries
        fixed_results = gdf.geometry.apply(fix_antimeridian)
        fixed_geoms = fixed_results.apply(lambda x: x[0])
        fixed_flags = fixed_results.apply(lambda x: x[1])
        antimeridian_count = fixed_flags.sum()

        if antimeridian_count > 0:
            gdf['geometry'] = fixed_geoms
            logger.warning(f"🌍 Fixed {antimeridian_count} geometries crossing the antimeridian (180° longitude)")
        else:
            logger.debug("No antimeridian-crossing geometries detected")

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
        # POLYGON WINDING ORDER - Enforce CCW exterior rings (15 JAN 2026)
        # ========================================================================
        # MVT (Mapbox Vector Tile) specification requires:
        # - Exterior rings: counter-clockwise (CCW)
        # - Interior rings (holes): clockwise (CW)
        #
        # TiPG generates MVT tiles, so incorrect winding order can cause:
        # - Rendering artifacts
        # - Invisible polygons
        # - Fill/hole inversion
        #
        # Shapely's orient() with sign=1.0 enforces this convention.
        # Only applies to Polygon and MultiPolygon geometries.
        # ========================================================================
        from shapely.geometry.polygon import orient

        def orient_polygon(geom):
            """
            Orient polygon rings for MVT compatibility.

            Uses Shapely's orient() which:
            - Sets exterior rings to CCW (sign=1.0)
            - Sets interior rings (holes) to CW
            - Returns non-polygon geometries unchanged
            """
            geom_type = geom.geom_type

            if geom_type == 'Polygon':
                return orient(geom, sign=1.0)
            elif geom_type == 'MultiPolygon':
                # Orient each polygon in the MultiPolygon
                oriented_polys = [orient(p, sign=1.0) for p in geom.geoms]
                from shapely.geometry import MultiPolygon
                return MultiPolygon(oriented_polys)
            else:
                # Points and LineStrings don't have winding order
                return geom

        # Check if we have any polygon geometries to orient
        polygon_types = {'Polygon', 'MultiPolygon'}
        has_polygons = any(t in polygon_types for t in type_counts_after.keys())

        if has_polygons:
            logger.info("🔄 Enforcing polygon winding order (CCW exterior, CW holes) for MVT compatibility")
            gdf['geometry'] = gdf.geometry.apply(orient_polygon)
            logger.info("✅ Polygon winding order normalized")

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

        # ========================================================================
        # DATETIME VALIDATION - Sanitize out-of-range timestamps (30 DEC 2025)
        # ========================================================================
        # KML/KMZ and other garbage files may contain timestamps with invalid years
        # (e.g., year 48113). PostgreSQL accepts these (max year 294276) but Python
        # datetime only supports years 1-9999. This causes psycopg to crash when
        # reading data back from the database.
        #
        # Solution: Set out-of-range datetime values to NULL (NaT) with warning.
        # Warnings are stored in self.last_warnings for inclusion in job results.
        # ========================================================================
        self.last_warnings = []  # Clear warnings from previous calls

        # Python datetime valid range
        MIN_YEAR = 1
        MAX_YEAR = 9999

        for col in gdf.columns:
            if col == 'geometry':
                continue

            # Check if column is datetime type
            if pd.api.types.is_datetime64_any_dtype(gdf[col]):
                # Find out-of-range values
                # pandas datetime64 stores as nanoseconds, can handle wider range than Python
                # We need to check the actual year values
                try:
                    years = gdf[col].dt.year
                    invalid_mask = (years < MIN_YEAR) | (years > MAX_YEAR)
                    invalid_count = invalid_mask.sum()

                    if invalid_count > 0:
                        # Get sample of invalid values for logging
                        invalid_samples = gdf.loc[invalid_mask, col].head(3).tolist()
                        sample_str = ", ".join(str(v) for v in invalid_samples)

                        warning_msg = (
                            f"Column '{col}': {invalid_count} datetime values outside Python range "
                            f"(years {MIN_YEAR}-{MAX_YEAR}) set to NULL. Samples: {sample_str}"
                        )
                        logger.warning(f"⚠️  {warning_msg}")
                        self.last_warnings.append(warning_msg)

                        # Set invalid values to NaT (pandas null for datetime)
                        gdf.loc[invalid_mask, col] = pd.NaT

                except Exception as e:
                    # If year extraction fails, the column might have mixed types
                    logger.warning(f"⚠️  Could not validate datetime column '{col}': {e}")

        if self.last_warnings:
            logger.info(f"📋 {len(self.last_warnings)} datetime warning(s) recorded for job results")

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
                # GAP-010 FIX (16 DEC 2025): Log batch_id at DELETE phase for idempotency verification
                logger.info(
                    f"[{batch_id}] DELETE+INSERT: Starting idempotent upsert "
                    f"for batch_id={batch_id} into {schema}.{table_name}, inserting {len(chunk)} rows"
                )

                delete_stmt = sql.SQL("""
                    DELETE FROM {schema}.{table}
                    WHERE etl_batch_id = %s
                """).format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name)
                )
                cur.execute(delete_stmt, (batch_id,))
                rows_deleted = cur.rowcount

                # GAP-010 FIX (16 DEC 2025): Always log DELETE result for audit trail
                logger.info(
                    f"[{batch_id}] DELETE phase: removed {rows_deleted} existing rows "
                    f"from {schema}.{table_name}"
                )

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
    # TABLE METADATA REGISTRY (21 JAN 2026 - Split Architecture)
    # =========================================================================
    # Writes to TWO tables with separation of concerns:
    #   - geo.table_catalog: Service layer metadata (replicable to external DB)
    #   - app.vector_etl_tracking: ETL internals (internal only, never replicated)
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
        temporal_property: str = None,
        # Custom properties (13 JAN 2026 - E8 TiPG Integration)
        custom_properties: dict = None
    ) -> None:
        """
        Register table metadata in BOTH geo.table_catalog AND app.vector_etl_tracking.

        21 JAN 2026 ARCHITECTURE (Separation of Concerns):
        - geo.table_catalog: Service layer fields (title, description, bbox, etc.)
          → Replicated to external DB via Azure Data Factory
          → Queried by OGC Features, TiPG, external services
        - app.vector_etl_tracking: ETL internal fields (etl_job_id, source_file, etc.)
          → NEVER replicated to external DB
          → Used for debugging, audit, data lineage

        Uses INSERT ... ON CONFLICT UPDATE for idempotency - safe to call
        multiple times (e.g., on job re-run).

        Args:
            table_name: Target table name (PRIMARY KEY in both tables)
            schema: Target schema (default 'geo')
            etl_job_id: Full 64-char job ID for traceability (ETL INTERNAL)
            source_file: Original filename (ETL INTERNAL)
            source_format: File format (ETL INTERNAL)
            source_crs: Original CRS before reprojection (ETL INTERNAL)
            feature_count: Total number of features
            geometry_type: PostGIS geometry type
            bbox: Bounding box tuple (minx, miny, maxx, maxy)
            title: User-friendly display name
            description: Full dataset description
            attribution: Data source attribution
            license: SPDX license identifier
            keywords: Comma-separated tags
            temporal_start: Start of temporal extent ISO8601
            temporal_end: End of temporal extent ISO8601
            temporal_property: Column name containing date data
            custom_properties: Additional JSONB properties
        """
        # Handle None or invalid bbox gracefully
        bbox_values = (None, None, None, None)
        if bbox is not None and len(bbox) >= 4:
            bbox_values = (bbox[0], bbox[1], bbox[2], bbox[3])

        # Convert custom_properties to JSON for psycopg
        import json
        custom_props_json = json.dumps(custom_properties) if custom_properties else None

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # =============================================================
                # STEP 1: Write SERVICE LAYER fields to geo.table_catalog
                # =============================================================
                cur.execute("""
                    INSERT INTO geo.table_catalog (
                        table_name, schema_name, feature_count, geometry_type,
                        bbox_minx, bbox_miny, bbox_maxx, bbox_maxy,
                        title, description, attribution, license, keywords,
                        temporal_start, temporal_end, temporal_property,
                        custom_properties,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s,
                        NOW(), NOW()
                    )
                    ON CONFLICT (table_name) DO UPDATE SET
                        schema_name = EXCLUDED.schema_name,
                        feature_count = EXCLUDED.feature_count,
                        geometry_type = EXCLUDED.geometry_type,
                        bbox_minx = EXCLUDED.bbox_minx,
                        bbox_miny = EXCLUDED.bbox_miny,
                        bbox_maxx = EXCLUDED.bbox_maxx,
                        bbox_maxy = EXCLUDED.bbox_maxy,
                        title = COALESCE(EXCLUDED.title, geo.table_catalog.title),
                        description = COALESCE(EXCLUDED.description, geo.table_catalog.description),
                        attribution = COALESCE(EXCLUDED.attribution, geo.table_catalog.attribution),
                        license = COALESCE(EXCLUDED.license, geo.table_catalog.license),
                        keywords = COALESCE(EXCLUDED.keywords, geo.table_catalog.keywords),
                        temporal_start = COALESCE(EXCLUDED.temporal_start, geo.table_catalog.temporal_start),
                        temporal_end = COALESCE(EXCLUDED.temporal_end, geo.table_catalog.temporal_end),
                        temporal_property = COALESCE(EXCLUDED.temporal_property, geo.table_catalog.temporal_property),
                        custom_properties = COALESCE(EXCLUDED.custom_properties, geo.table_catalog.custom_properties),
                        updated_at = NOW()
                """, (
                    table_name, schema, feature_count, geometry_type,
                    bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3],
                    title, description, attribution, license, keywords,
                    temporal_start, temporal_end, temporal_property,
                    custom_props_json
                ))

                # =============================================================
                # STEP 2: Write ETL INTERNAL fields to app.vector_etl_tracking
                # =============================================================
                # This table is INTERNAL ONLY - never replicated to external DB
                cur.execute("""
                    INSERT INTO app.vector_etl_tracking (
                        table_name, etl_job_id, source_file, source_format,
                        source_crs, status, rows_written, target_crs,
                        processing_completed_at, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'completed', %s, 'EPSG:4326',
                        NOW(), NOW()
                    )
                    ON CONFLICT (table_name, etl_job_id) DO UPDATE SET
                        source_file = EXCLUDED.source_file,
                        source_format = EXCLUDED.source_format,
                        source_crs = EXCLUDED.source_crs,
                        status = 'completed',
                        rows_written = EXCLUDED.rows_written,
                        processing_completed_at = NOW()
                """, (
                    table_name, etl_job_id, source_file, source_format,
                    source_crs, feature_count
                ))

                conn.commit()

        logger.info(f"✅ Registered metadata for {schema}.{table_name} in table_catalog + etl_tracking (job: {etl_job_id[:8]}...)")

    def update_table_stac_link(
        self,
        table_name: str,
        stac_item_id: str,
        stac_collection_id: str
    ) -> bool:
        """
        Update table_catalog with STAC item linkage after Stage 3 completion.

        Called after successful STAC item creation to establish the backlink
        from PostGIS table → STAC catalog item.

        NOTE (21 JAN 2026): Updates geo.table_catalog (service layer) only.
        STAC linkage is service layer metadata, not ETL internal.

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
                    UPDATE geo.table_catalog
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
            logger.warning(f"⚠️ No metadata found for {table_name} in table_catalog - STAC link not recorded")
            return False

    # =========================================================================
    # GEOMETRY OPTIMIZATION - ST_Subdivide for complex polygons (15 JAN 2026)
    # =========================================================================
    # PostGIS ST_Subdivide splits complex polygons into smaller pieces, which
    # significantly improves vector tile generation performance. TiPG must clip
    # each polygon to tile boundaries - smaller polygons = faster clipping.
    # =========================================================================

    def subdivide_complex_polygons(
        self,
        table_name: str,
        schema: str = "geo",
        max_vertices: int = 256,
        geometry_column: str = "geom",
        create_tile_view: bool = True
    ) -> Dict[str, Any]:
        """
        Subdivide complex polygons using PostGIS ST_Subdivide for vector tile optimization.

        This optimization improves vector tile generation performance by splitting
        large polygons with many vertices into smaller pieces. Benefits:
        - Faster tile clipping (TiPG/ST_AsMVT)
        - Better spatial index utilization
        - Reduced memory usage during tile generation

        MODES OF OPERATION:

        1. create_tile_view=True (DEFAULT, RECOMMENDED):
           Creates a materialized view '{table_name}_tiles' with subdivided geometries.
           - Original table preserved for OGC Features API queries
           - Tile view optimized for TiPG vector tile serving
           - Both appear in TiPG collection list (e.g., 'countries' and 'countries_tiles')
           - Use '_tiles' suffix tables for MapLibre/vector tile viewers

        2. create_tile_view=False:
           Modifies the original table in-place (DESTRUCTIVE).
           - Feature count increases as polygons are split
           - Attributes duplicated across subdivisions
           - Only use for visualization-only tables

        When to use:
        - Tables with polygons having >1000 vertices (coastlines, admin boundaries)
        - Tables used heavily for vector tile serving
        - When tile generation is slow due to complex geometries

        When NOT to use:
        - Point or line geometries (no effect)
        - Simple polygons (adds overhead without benefit)

        Args:
            table_name: Target table name
            schema: Target schema (default: 'geo')
            max_vertices: Maximum vertices per subdivided polygon (default: 256)
                         Lower = more splits = faster tiles but more rows
                         Recommended: 256 for web tiles, 512 for detailed views
            geometry_column: Geometry column name (default: 'geom')
            create_tile_view: If True (default), create a materialized view '{table}_tiles'
                             preserving the original table. If False, modify in-place.

        Returns:
            Dict with results:
            {
                'success': bool,
                'mode': str,                # 'materialized_view' or 'in_place'
                'original_table': str,      # Original table name
                'tile_view': str,           # Tile view name (if create_tile_view=True)
                'original_count': int,      # Rows in original table
                'tile_count': int,          # Rows in tile view/modified table
                'polygons_split': int,      # Number of complex polygons that were split
                'execution_time_ms': float  # Time taken
            }

        Example:
            handler = VectorToPostGISHandler()

            # Recommended: Create tile-optimized view (preserves original)
            result = handler.subdivide_complex_polygons(
                table_name='countries',
                max_vertices=256
            )
            # TiPG now serves both:
            #   - geo.countries (original, for OGC Features)
            #   - geo.countries_tiles (subdivided, for vector tiles)

            # Alternative: Modify in-place (visualization-only tables)
            result = handler.subdivide_complex_polygons(
                table_name='basemap_water',
                max_vertices=256,
                create_tile_view=False
            )
        """
        import time
        start_time = time.time()

        tile_view_name = f"{table_name}_tiles"
        mode = "materialized_view" if create_tile_view else "in_place"

        logger.info(f"🔪 Starting ST_Subdivide on {schema}.{table_name} (max_vertices={max_vertices}, mode={mode})")

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Get original row count
                cur.execute(sql.SQL("""
                    SELECT COUNT(*) as cnt FROM {schema}.{table}
                """).format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name)
                ))
                result = cur.fetchone()
                original_count = result['cnt'] if result else 0

                # Count complex polygons (those that will be split)
                cur.execute(sql.SQL("""
                    SELECT COUNT(*) as cnt
                    FROM {schema}.{table}
                    WHERE ST_NPoints({geom}) > %s
                    AND GeometryType({geom}) IN ('POLYGON', 'MULTIPOLYGON')
                """).format(
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name),
                    geom=sql.Identifier(geometry_column)
                ), (max_vertices,))
                result = cur.fetchone()
                complex_count = result['cnt'] if result else 0

                if complex_count == 0:
                    logger.info(f"   No complex polygons found (none with >{max_vertices} vertices)")
                    return {
                        'success': True,
                        'mode': mode,
                        'original_table': f"{schema}.{table_name}",
                        'tile_view': None,
                        'original_count': original_count,
                        'tile_count': original_count,
                        'polygons_split': 0,
                        'execution_time_ms': (time.time() - start_time) * 1000,
                        'message': 'No complex polygons to subdivide'
                    }

                logger.info(f"   Found {complex_count} complex polygons to subdivide")

                # Get all column names except geometry and id
                cur.execute(sql.SQL("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    AND column_name NOT IN ('id', %s)
                    ORDER BY ordinal_position
                """), (schema, table_name, geometry_column))
                columns = [row['column_name'] for row in cur.fetchall()]

                # Build column list for SELECT
                if columns:
                    select_cols = sql.SQL(', ').join([sql.Identifier(c) for c in columns])
                else:
                    select_cols = None

                # ================================================================
                # MODE 1: Create Materialized View (RECOMMENDED)
                # ================================================================
                if create_tile_view:
                    logger.info(f"   Creating materialized view: {schema}.{tile_view_name}")

                    # Drop existing view if it exists
                    cur.execute(sql.SQL("""
                        DROP MATERIALIZED VIEW IF EXISTS {schema}.{view} CASCADE
                    """).format(
                        schema=sql.Identifier(schema),
                        view=sql.Identifier(tile_view_name)
                    ))

                    # Create materialized view with subdivided geometries
                    # Uses UNION ALL with LATERAL for ST_Subdivide (set-returning function)
                    # Simple geometries pass through unchanged, complex ones are subdivided
                    # Table alias 't' used in LATERAL query to disambiguate column refs
                    # Note: PostgreSQL doesn't allow bind parameters in CREATE MATERIALIZED VIEW,
                    # so we use sql.Literal to embed the max_vertices value directly
                    max_vertices_lit = sql.Literal(max_vertices)
                    if select_cols:
                        # Build qualified column list for LATERAL query (t.col1, t.col2, ...)
                        qualified_cols = sql.SQL(', ').join([
                            sql.SQL('t.') + sql.Identifier(c) for c in columns
                        ])
                        cur.execute(sql.SQL("""
                            CREATE MATERIALIZED VIEW {schema}.{view} AS
                            -- Simple geometries (no subdivision needed)
                            SELECT {geom}, {cols}
                            FROM {schema}.{table}
                            WHERE ST_NPoints({geom}) <= {max_v}
                               OR GeometryType({geom}) NOT IN ('POLYGON', 'MULTIPOLYGON')
                            UNION ALL
                            -- Complex geometries (subdivided via LATERAL)
                            SELECT subdivided.geom AS {geom}, {qualified_cols}
                            FROM {schema}.{table} t,
                                 LATERAL ST_Subdivide(t.{geom}, {max_v}) AS subdivided(geom)
                            WHERE ST_NPoints(t.{geom}) > {max_v}
                              AND GeometryType(t.{geom}) IN ('POLYGON', 'MULTIPOLYGON')
                        """).format(
                            schema=sql.Identifier(schema),
                            view=sql.Identifier(tile_view_name),
                            table=sql.Identifier(table_name),
                            geom=sql.Identifier(geometry_column),
                            cols=select_cols,
                            qualified_cols=qualified_cols,
                            max_v=max_vertices_lit
                        ))
                    else:
                        cur.execute(sql.SQL("""
                            CREATE MATERIALIZED VIEW {schema}.{view} AS
                            -- Simple geometries (no subdivision needed)
                            SELECT {geom}
                            FROM {schema}.{table}
                            WHERE ST_NPoints({geom}) <= {max_v}
                               OR GeometryType({geom}) NOT IN ('POLYGON', 'MULTIPOLYGON')
                            UNION ALL
                            -- Complex geometries (subdivided via LATERAL)
                            SELECT subdivided.geom AS {geom}
                            FROM {schema}.{table} t,
                                 LATERAL ST_Subdivide(t.{geom}, {max_v}) AS subdivided(geom)
                            WHERE ST_NPoints(t.{geom}) > {max_v}
                              AND GeometryType(t.{geom}) IN ('POLYGON', 'MULTIPOLYGON')
                        """).format(
                            schema=sql.Identifier(schema),
                            view=sql.Identifier(tile_view_name),
                            table=sql.Identifier(table_name),
                            geom=sql.Identifier(geometry_column),
                            max_v=max_vertices_lit
                        ))

                    # Create spatial index on the materialized view
                    index_name = f"idx_{tile_view_name}_{geometry_column}"
                    cur.execute(sql.SQL("""
                        CREATE INDEX {idx} ON {schema}.{view} USING GIST ({geom})
                    """).format(
                        idx=sql.Identifier(index_name),
                        schema=sql.Identifier(schema),
                        view=sql.Identifier(tile_view_name),
                        geom=sql.Identifier(geometry_column)
                    ))

                    logger.info(f"   ✅ Created spatial index: {index_name}")

                    # Get tile view row count
                    cur.execute(sql.SQL("""
                        SELECT COUNT(*) as cnt FROM {schema}.{view}
                    """).format(
                        schema=sql.Identifier(schema),
                        view=sql.Identifier(tile_view_name)
                    ))
                    result = cur.fetchone()
                    tile_count = result['cnt'] if result else 0

                    conn.commit()

                    execution_time = (time.time() - start_time) * 1000

                    logger.info(f"✅ Materialized view created: {schema}.{tile_view_name}")
                    logger.info(f"   Original table: {original_count} rows (preserved)")
                    logger.info(f"   Tile view: {tile_count} rows (subdivided)")
                    logger.info(f"   Execution time: {execution_time:.1f}ms")

                    return {
                        'success': True,
                        'mode': 'materialized_view',
                        'original_table': f"{schema}.{table_name}",
                        'tile_view': f"{schema}.{tile_view_name}",
                        'original_count': original_count,
                        'tile_count': tile_count,
                        'polygons_split': complex_count,
                        'execution_time_ms': execution_time
                    }

                # ================================================================
                # MODE 2: In-Place Modification (DESTRUCTIVE)
                # ================================================================
                else:
                    logger.info(f"   ⚠️  Modifying table in-place (original data will be changed)")

                    # Build column list for INSERT
                    if columns:
                        cols_sql = sql.SQL(', ').join([sql.Identifier(c) for c in columns])
                        cols_with_geom = sql.SQL('{geom}, {cols}').format(
                            geom=sql.Identifier(geometry_column),
                            cols=cols_sql
                        )
                    else:
                        cols_with_geom = sql.Identifier(geometry_column)
                        cols_sql = None

                    # Strategy: Create temp table with subdivided geometries, then swap
                    temp_table = f"_temp_subdivide_{table_name}"

                    # Create temp table with same structure
                    cur.execute(sql.SQL("""
                        CREATE TEMP TABLE {temp} AS
                        SELECT * FROM {schema}.{table} WHERE 1=0
                    """).format(
                        temp=sql.Identifier(temp_table),
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    ))

                    # Insert simple polygons unchanged
                    if cols_sql:
                        cur.execute(sql.SQL("""
                            INSERT INTO {temp} ({cols_with_geom})
                            SELECT {geom}, {cols}
                            FROM {schema}.{table}
                            WHERE ST_NPoints({geom}) <= %s
                            OR GeometryType({geom}) NOT IN ('POLYGON', 'MULTIPOLYGON')
                        """).format(
                            temp=sql.Identifier(temp_table),
                            cols_with_geom=cols_with_geom,
                            geom=sql.Identifier(geometry_column),
                            cols=cols_sql,
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name)
                        ), (max_vertices,))
                    else:
                        cur.execute(sql.SQL("""
                            INSERT INTO {temp} ({geom})
                            SELECT {geom}
                            FROM {schema}.{table}
                            WHERE ST_NPoints({geom}) <= %s
                            OR GeometryType({geom}) NOT IN ('POLYGON', 'MULTIPOLYGON')
                        """).format(
                            temp=sql.Identifier(temp_table),
                            geom=sql.Identifier(geometry_column),
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name)
                        ), (max_vertices,))

                    simple_inserted = cur.rowcount
                    logger.info(f"   Copied {simple_inserted} simple geometries unchanged")

                    # Insert subdivided complex polygons
                    if cols_sql:
                        cur.execute(sql.SQL("""
                            INSERT INTO {temp} ({cols_with_geom})
                            SELECT ST_Subdivide({geom}, %s), {cols}
                            FROM {schema}.{table}
                            WHERE ST_NPoints({geom}) > %s
                            AND GeometryType({geom}) IN ('POLYGON', 'MULTIPOLYGON')
                        """).format(
                            temp=sql.Identifier(temp_table),
                            cols_with_geom=cols_with_geom,
                            geom=sql.Identifier(geometry_column),
                            cols=cols_sql,
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name)
                        ), (max_vertices, max_vertices))
                    else:
                        cur.execute(sql.SQL("""
                            INSERT INTO {temp} ({geom})
                            SELECT ST_Subdivide({geom}, %s)
                            FROM {schema}.{table}
                            WHERE ST_NPoints({geom}) > %s
                            AND GeometryType({geom}) IN ('POLYGON', 'MULTIPOLYGON')
                        """).format(
                            temp=sql.Identifier(temp_table),
                            geom=sql.Identifier(geometry_column),
                            schema=sql.Identifier(schema),
                            table=sql.Identifier(table_name)
                        ), (max_vertices, max_vertices))

                    subdivided_inserted = cur.rowcount
                    logger.info(f"   Created {subdivided_inserted} subdivided geometries from {complex_count} complex polygons")

                    # Truncate original and insert from temp
                    cur.execute(sql.SQL("""
                        TRUNCATE {schema}.{table}
                    """).format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name)
                    ))

                    # Insert all from temp back to original
                    cur.execute(sql.SQL("""
                        INSERT INTO {schema}.{table} ({cols_with_geom})
                        SELECT {cols_with_geom} FROM {temp}
                    """).format(
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name),
                        cols_with_geom=cols_with_geom,
                        temp=sql.Identifier(temp_table)
                    ))

                    tile_count = cur.rowcount

                    # Drop temp table
                    cur.execute(sql.SQL("DROP TABLE IF EXISTS {temp}").format(
                        temp=sql.Identifier(temp_table)
                    ))

                    conn.commit()

                    execution_time = (time.time() - start_time) * 1000

                    logger.info(f"✅ In-place subdivision complete: {original_count} → {tile_count} rows ({execution_time:.1f}ms)")

                    return {
                        'success': True,
                        'mode': 'in_place',
                        'original_table': f"{schema}.{table_name}",
                        'tile_view': None,
                        'original_count': original_count,
                        'tile_count': tile_count,
                        'polygons_split': complex_count,
                        'execution_time_ms': execution_time
                    }

    def refresh_tile_view(
        self,
        table_name: str,
        schema: str = "geo",
        concurrently: bool = True
    ) -> Dict[str, Any]:
        """
        Refresh a tile-optimized materialized view after source table updates.

        Call this method after updating the source table to sync the tile view.
        Uses CONCURRENTLY by default to avoid locking during refresh.

        Args:
            table_name: Source table name (without _tiles suffix)
            schema: Target schema (default: 'geo')
            concurrently: If True (default), refresh without locking reads.
                         Requires an existing unique index on the view.
                         If False, locks the view during refresh.

        Returns:
            Dict with results:
            {
                'success': bool,
                'tile_view': str,           # Full view name
                'refresh_mode': str,        # 'concurrent' or 'blocking'
                'execution_time_ms': float
            }

        Example:
            # After updating geo.countries...
            handler.refresh_tile_view('countries')
            # geo.countries_tiles is now synced
        """
        import time
        start_time = time.time()

        tile_view_name = f"{table_name}_tiles"

        logger.info(f"🔄 Refreshing materialized view: {schema}.{tile_view_name}")

        with self._pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if view exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_matviews
                        WHERE schemaname = %s AND matviewname = %s
                    ) as view_exists
                """, (schema, tile_view_name))
                result = cur.fetchone()
                exists = result['view_exists'] if result else False

                if not exists:
                    logger.warning(f"⚠️  Materialized view {schema}.{tile_view_name} does not exist")
                    return {
                        'success': False,
                        'tile_view': f"{schema}.{tile_view_name}",
                        'error': 'Materialized view does not exist'
                    }

                # Refresh the view
                if concurrently:
                    try:
                        cur.execute(sql.SQL("""
                            REFRESH MATERIALIZED VIEW CONCURRENTLY {schema}.{view}
                        """).format(
                            schema=sql.Identifier(schema),
                            view=sql.Identifier(tile_view_name)
                        ))
                        refresh_mode = 'concurrent'
                    except Exception as e:
                        # CONCURRENTLY requires unique index - fall back to blocking
                        logger.warning(f"   Concurrent refresh failed, using blocking refresh: {e}")
                        cur.execute(sql.SQL("""
                            REFRESH MATERIALIZED VIEW {schema}.{view}
                        """).format(
                            schema=sql.Identifier(schema),
                            view=sql.Identifier(tile_view_name)
                        ))
                        refresh_mode = 'blocking'
                else:
                    cur.execute(sql.SQL("""
                        REFRESH MATERIALIZED VIEW {schema}.{view}
                    """).format(
                        schema=sql.Identifier(schema),
                        view=sql.Identifier(tile_view_name)
                    ))
                    refresh_mode = 'blocking'

                conn.commit()

        execution_time = (time.time() - start_time) * 1000

        logger.info(f"✅ Refreshed {schema}.{tile_view_name} ({refresh_mode}, {execution_time:.1f}ms)")

        return {
            'success': True,
            'tile_view': f"{schema}.{tile_view_name}",
            'refresh_mode': refresh_mode,
            'execution_time_ms': execution_time
        }
