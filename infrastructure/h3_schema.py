# ============================================================================
# CLAUDE CONTEXT - H3 NORMALIZED SCHEMA DEPLOYER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - H3 OLTP Schema DDL
# PURPOSE: Deploy normalized H3 schema (cells, admin mappings, stats tables)
# LAST_REVIEWED: 17 DEC 2025
# EXPORTS: H3SchemaDeployer, deploy_h3_normalized_schema
# DEPENDENCIES: psycopg, pydantic
# ============================================================================
"""
H3 Normalized Schema Deployment.

OLTP System of Record for H3 hexagonal grid data. Normalized design with:
- h3.cells: Unique H3 geometry (stored once per h3_index)
- h3.cell_admin0: Country overlap mapping (1:N)
- h3.cell_admin1: Admin1/Province overlap mapping (1:N)
- h3.stat_registry: Metadata catalog for aggregation datasets
- h3.zonal_stats: Raster aggregation results (1:N, FK to stat_registry)
- h3.point_stats: Point-in-polygon counts (1:N, FK to stat_registry)

Architecture:
    OLTP (PostgreSQL) -> ETL Export -> OLAP (GeoParquet/DuckDB/Databricks)

Design Principles:
- Single source of truth for H3 geometry
- Sparse mapping tables (only store actual overlaps)
- Foreign keys enforce referential integrity
- Composite unique constraints on natural keys

Usage:
    from infrastructure.h3_schema import H3SchemaDeployer

    deployer = H3SchemaDeployer()
    result = deployer.deploy_all()
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from psycopg import sql
import traceback

from infrastructure.postgresql import PostgreSQLRepository
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.REPOSITORY, "h3_schema")


# ============================================================================
# H3 SCHEMA DEPLOYER
# ============================================================================

class H3SchemaDeployer:
    """
    Deploy normalized H3 schema using psycopg SQL composition.

    Tables:
        h3.cells - Core H3 grid (unique geometry per h3_index)
        h3.cell_admin0 - Country overlap mapping
        h3.cell_admin1 - Admin1/Province overlap mapping
        h3.stat_registry - Metadata catalog for aggregation datasets
        h3.zonal_stats - Raster aggregation results (FK to stat_registry)
        h3.point_stats - Point-in-polygon counts (FK to stat_registry)

    All DDL uses psycopg.sql composition for injection safety.
    """

    SCHEMA_NAME = "h3"

    def __init__(self):
        """Initialize deployer with PostgreSQL repository."""
        self.repo = PostgreSQLRepository()
        logger.info(f"H3SchemaDeployer initialized for schema: {self.SCHEMA_NAME}")

    def deploy_all(self) -> Dict[str, Any]:
        """
        Deploy complete normalized H3 schema.

        Executes in order:
        1. Create schema (if not exists)
        2. Create h3.cells table
        3. Create h3.cell_admin0 table
        4. Create h3.cell_admin1 table
        5. Create h3.stat_registry table (metadata catalog)
        6. Create h3.zonal_stats table (FK to stat_registry)
        7. Create h3.point_stats table (FK to stat_registry)
        8. Grant permissions

        Returns:
            Dict with deployment results and any errors
        """
        results = {
            "schema": self.SCHEMA_NAME,
            "timestamp": datetime.utcnow().isoformat(),
            "steps": [],
            "success": False,
            "errors": []
        }

        try:
            with self.repo._get_connection() as conn:
                # Step 1: Create schema
                self._deploy_schema(conn, results)

                # Step 2: Create h3.cells (core table)
                self._deploy_cells_table(conn, results)

                # Step 3: Create h3.cell_admin0 (country mapping)
                self._deploy_cell_admin0_table(conn, results)

                # Step 4: Create h3.cell_admin1 (admin1 mapping)
                self._deploy_cell_admin1_table(conn, results)

                # Step 5: Create h3.stat_registry (metadata catalog - BEFORE stats tables)
                self._deploy_stat_registry_table(conn, results)

                # Step 6: Create h3.zonal_stats (raster aggregations - FK to stat_registry)
                self._deploy_zonal_stats_table(conn, results)

                # Step 7: Create h3.point_stats (point counts - FK to stat_registry)
                self._deploy_point_stats_table(conn, results)

                # Step 8: Grant permissions
                self._grant_permissions(conn, results)

                conn.commit()
                results["success"] = True
                logger.info(f"H3 normalized schema deployed successfully")

        except Exception as e:
            logger.error(f"H3 schema deployment failed: {e}")
            logger.error(traceback.format_exc())
            results["errors"].append(str(e))
            results["success"] = False

        return results

    # ========================================================================
    # SCHEMA CREATION
    # ========================================================================

    def _deploy_schema(self, conn, results: Dict):
        """Create h3 schema if not exists."""
        step = {"name": "create_schema", "status": "pending"}

        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("""
                    CREATE SCHEMA IF NOT EXISTS {}
                """).format(sql.Identifier(self.SCHEMA_NAME)))

                cur.execute(sql.SQL("""
                    COMMENT ON SCHEMA {} IS
                    'Normalized H3 hexagonal grid schema - OLTP system of record. '
                    'Unique geometry per h3_index with sparse mapping tables for '
                    'political boundaries and aggregation results.'
                """).format(sql.Identifier(self.SCHEMA_NAME)))

            step["status"] = "success"
            logger.info(f"Schema {self.SCHEMA_NAME} created/verified")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.cells - CORE H3 GRID (Unique Geometry)
    # ========================================================================

    def _deploy_cells_table(self, conn, results: Dict):
        """
        Create h3.cells table - unique H3 geometry stored once per h3_index.

        This is the core table. All other tables reference this via FK.

        Columns:
            h3_index BIGINT PRIMARY KEY - H3 cell index (64-bit)
            resolution SMALLINT - H3 resolution (0-15)
            geom GEOMETRY(Polygon, 4326) - Cell boundary
            parent_h3_index BIGINT - Immediate parent (res n-1)
            is_land BOOLEAN - Land/water classification
            created_at TIMESTAMPTZ - Creation timestamp
        """
        step = {"name": "create_h3_cells", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Primary key: H3 index (unique geometry)
                        h3_index BIGINT PRIMARY KEY,

                        -- H3 metadata
                        resolution SMALLINT NOT NULL
                            CONSTRAINT cells_resolution_check
                            CHECK (resolution >= 0 AND resolution <= 15),

                        -- Geometry (stored ONCE per h3_index)
                        geom GEOMETRY(Polygon, 4326) NOT NULL,

                        -- Hierarchy
                        parent_h3_index BIGINT REFERENCES {schema}.{table}(h3_index),

                        -- Classification
                        is_land BOOLEAN,

                        -- Audit
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        source_job_id VARCHAR(64)
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cells")
                ))

                # Spatial index (GiST)
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cells_geom
                    ON {schema}.{table} USING GIST(geom)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cells")
                ))

                # Resolution index (for filtering by level)
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cells_resolution
                    ON {schema}.{table}(resolution)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cells")
                ))

                # Parent index (for hierarchy queries)
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cells_parent
                    ON {schema}.{table}(parent_h3_index)
                    WHERE parent_h3_index IS NOT NULL
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cells")
                ))

                # Land filter index
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cells_is_land
                    ON {schema}.{table}(is_land)
                    WHERE is_land IS NOT NULL
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cells")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Core H3 hexagonal grid - unique geometry per h3_index. '
                    'OLTP system of record. All mapping tables reference this via FK.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cells")
                ))

            step["status"] = "success"
            logger.info("Table h3.cells created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.cell_admin0 - COUNTRY OVERLAP MAPPING
    # ========================================================================

    def _deploy_cell_admin0_table(self, conn, results: Dict):
        """
        Create h3.cell_admin0 table - maps H3 cells to countries.

        Sparse table: Only stores actual overlaps (not "cell X is NOT in Brazil").
        One cell can map to multiple countries (border cells).

        Columns:
            h3_index BIGINT FK - References h3.cells
            iso3 VARCHAR(3) - ISO 3166-1 alpha-3 country code
            coverage_pct NUMERIC(5,4) - Fraction of cell in country (0.0-1.0)

        Unique constraint on (h3_index, iso3).
        """
        step = {"name": "create_h3_cell_admin0", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Composite natural key
                        h3_index BIGINT NOT NULL
                            REFERENCES {schema}.cells(h3_index) ON DELETE CASCADE,
                        iso3 VARCHAR(3) NOT NULL,

                        -- Coverage fraction (0.0 to 1.0)
                        coverage_pct NUMERIC(5,4)
                            CONSTRAINT cell_admin0_coverage_check
                            CHECK (coverage_pct IS NULL OR (coverage_pct >= 0 AND coverage_pct <= 1)),

                        -- Audit
                        created_at TIMESTAMPTZ DEFAULT NOW(),

                        -- Unique constraint on natural key
                        CONSTRAINT cell_admin0_unique UNIQUE (h3_index, iso3)
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin0")
                ))

                # Index on iso3 for country queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cell_admin0_iso3
                    ON {schema}.{table}(iso3)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin0")
                ))

                # Index on h3_index for cell lookups
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cell_admin0_h3_index
                    ON {schema}.{table}(h3_index)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin0")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'H3 cell to country (admin0) mapping. Sparse table - only stores '
                    'actual overlaps. One cell can belong to multiple countries (borders). '
                    'coverage_pct indicates fraction of cell area within country.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin0")
                ))

            step["status"] = "success"
            logger.info("Table h3.cell_admin0 created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.cell_admin1 - STATE/PROVINCE OVERLAP MAPPING
    # ========================================================================

    def _deploy_cell_admin1_table(self, conn, results: Dict):
        """
        Create h3.cell_admin1 table - maps H3 cells to states/provinces.

        Columns:
            h3_index BIGINT FK - References h3.cells
            admin1_id VARCHAR(50) - Admin1 identifier (e.g., "US-CA", "GR-A")
            iso3 VARCHAR(3) - Parent country code
            admin1_name VARCHAR(255) - Human-readable name
            coverage_pct NUMERIC(5,4) - Fraction of cell in admin1

        Unique constraint on (h3_index, admin1_id).
        """
        step = {"name": "create_h3_cell_admin1", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Composite natural key
                        h3_index BIGINT NOT NULL
                            REFERENCES {schema}.cells(h3_index) ON DELETE CASCADE,
                        admin1_id VARCHAR(50) NOT NULL,

                        -- Parent country
                        iso3 VARCHAR(3) NOT NULL,

                        -- Human-readable name
                        admin1_name VARCHAR(255),

                        -- Coverage fraction (0.0 to 1.0)
                        coverage_pct NUMERIC(5,4)
                            CONSTRAINT cell_admin1_coverage_check
                            CHECK (coverage_pct IS NULL OR (coverage_pct >= 0 AND coverage_pct <= 1)),

                        -- Audit
                        created_at TIMESTAMPTZ DEFAULT NOW(),

                        -- Unique constraint on natural key
                        CONSTRAINT cell_admin1_unique UNIQUE (h3_index, admin1_id)
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin1")
                ))

                # Index on admin1_id for region queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cell_admin1_admin1_id
                    ON {schema}.{table}(admin1_id)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin1")
                ))

                # Index on iso3 for country filtering
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cell_admin1_iso3
                    ON {schema}.{table}(iso3)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin1")
                ))

                # Index on h3_index for cell lookups
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_cell_admin1_h3_index
                    ON {schema}.{table}(h3_index)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin1")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'H3 cell to admin1 (state/province) mapping. Sparse table - only '
                    'stores actual overlaps. admin1_id format: ISO3-CODE (e.g., US-CA).'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("cell_admin1")
                ))

            step["status"] = "success"
            logger.info("Table h3.cell_admin1 created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.stat_registry - METADATA CATALOG FOR AGGREGATION DATASETS
    # ========================================================================

    def _deploy_stat_registry_table(self, conn, results: Dict):
        """
        Create h3.stat_registry table - metadata catalog for aggregation datasets.

        Documents all statistics datasets with human-readable metadata, source
        attribution, and provenance tracking. Referenced by zonal_stats and
        point_stats via FK for data validation and discoverability.

        Columns:
            id VARCHAR(100) PRIMARY KEY - Dataset identifier (e.g., 'worldpop_2020')
            stat_category VARCHAR(50) - Category: raster_zonal, vector_point, etc.
            display_name VARCHAR(255) - Human-readable name
            description TEXT - Detailed explanation
            source_name VARCHAR(255) - Data source organization
            source_url VARCHAR(500) - Link to original data
            source_license VARCHAR(100) - License (CC-BY-4.0, etc.)
            resolution_range INT[] - Available H3 resolutions
            stat_types VARCHAR[] - Available stat types
            unit VARCHAR(50) - Unit of measurement
            last_aggregation_at TIMESTAMPTZ - Last computation time
            last_aggregation_job_id VARCHAR(64) - Last job ID
            cell_count INTEGER - Number of cells with this stat
        """
        step = {"name": "create_h3_stat_registry", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Primary key: dataset identifier
                        id VARCHAR(100) PRIMARY KEY,

                        -- Classification
                        stat_category VARCHAR(50) NOT NULL
                            CONSTRAINT stat_registry_category_check
                            CHECK (stat_category IN (
                                'raster_zonal', 'vector_point', 'vector_line',
                                'vector_polygon', 'planetary_computer', 'band_math'
                            )),

                        -- Human-readable metadata
                        display_name VARCHAR(255) NOT NULL,
                        description TEXT,

                        -- Source attribution
                        source_name VARCHAR(255),
                        source_url VARCHAR(500),
                        source_license VARCHAR(100),

                        -- Technical metadata
                        resolution_range INTEGER[],
                        stat_types VARCHAR(50)[],
                        unit VARCHAR(50),

                        -- Provenance
                        last_aggregation_at TIMESTAMPTZ,
                        last_aggregation_job_id VARCHAR(64),
                        cell_count INTEGER,

                        -- Audit
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("stat_registry")
                ))

                # Index on category for filtering
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_stat_registry_category
                    ON {schema}.{table}(stat_category)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("stat_registry")
                ))

                # Index on source for attribution queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_stat_registry_source
                    ON {schema}.{table}(source_name)
                    WHERE source_name IS NOT NULL
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("stat_registry")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Metadata catalog for H3 aggregation datasets. Documents all statistics '
                    'with human-readable names, source attribution, and provenance tracking. '
                    'Referenced by zonal_stats.dataset_id and point_stats.source_id via FK.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("stat_registry")
                ))

            step["status"] = "success"
            logger.info("Table h3.stat_registry created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.zonal_stats - RASTER AGGREGATION RESULTS
    # ========================================================================

    def _deploy_zonal_stats_table(self, conn, results: Dict):
        """
        Create h3.zonal_stats table - raster aggregation results per cell.

        Stores pre-computed zonal statistics from raster datasets (COGs).
        One cell can have multiple stats (different datasets, bands, stat types).

        Columns:
            h3_index BIGINT FK - References h3.cells
            dataset_id VARCHAR(100) - Dataset identifier (e.g., 'worldpop_2020')
            band VARCHAR(50) - Raster band name (default: 'default')
            stat_type VARCHAR(20) - Statistic type (mean, sum, min, max, count, std)
            value DOUBLE PRECISION - Computed statistic value
            pixel_count INTEGER - Number of pixels in aggregation
            computed_at TIMESTAMPTZ - When stat was computed

        Unique constraint on (h3_index, dataset_id, band, stat_type).
        """
        step = {"name": "create_h3_zonal_stats", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Composite natural key
                        h3_index BIGINT NOT NULL
                            REFERENCES {schema}.cells(h3_index) ON DELETE CASCADE,
                        dataset_id VARCHAR(100) NOT NULL,
                        band VARCHAR(50) NOT NULL DEFAULT 'default',
                        stat_type VARCHAR(20) NOT NULL,

                        -- Computed values
                        value DOUBLE PRECISION,
                        pixel_count INTEGER,
                        nodata_count INTEGER,

                        -- Audit
                        computed_at TIMESTAMPTZ DEFAULT NOW(),
                        source_job_id VARCHAR(64),

                        -- Unique constraint on natural key
                        CONSTRAINT zonal_stats_unique
                            UNIQUE (h3_index, dataset_id, band, stat_type)
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Index on dataset_id for dataset queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_zonal_stats_dataset
                    ON {schema}.{table}(dataset_id)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Index on h3_index for cell lookups
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_zonal_stats_h3_index
                    ON {schema}.{table}(h3_index)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Composite index for common query pattern
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_zonal_stats_dataset_stat
                    ON {schema}.{table}(dataset_id, stat_type)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Pre-computed zonal statistics from raster datasets aggregated to H3 cells. '
                    'Supports multiple datasets, bands, and stat types per cell. '
                    'stat_type: mean, sum, min, max, count, std, median.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

            step["status"] = "success"
            logger.info("Table h3.zonal_stats created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.point_stats - POINT-IN-POLYGON COUNTS
    # ========================================================================

    def _deploy_point_stats_table(self, conn, results: Dict):
        """
        Create h3.point_stats table - point-in-polygon aggregation results.

        Stores counts of points within each H3 cell, grouped by source and category.

        Columns:
            h3_index BIGINT FK - References h3.cells
            source_id VARCHAR(100) - Data source (e.g., 'osm_pois', 'overture_places')
            category VARCHAR(100) - Point category (e.g., 'restaurant', 'hospital')
            count INTEGER - Number of points in cell
            computed_at TIMESTAMPTZ - When count was computed

        Unique constraint on (h3_index, source_id, category).
        """
        step = {"name": "create_h3_point_stats", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Composite natural key
                        h3_index BIGINT NOT NULL
                            REFERENCES {schema}.cells(h3_index) ON DELETE CASCADE,
                        source_id VARCHAR(100) NOT NULL,
                        category VARCHAR(100),

                        -- Computed values
                        count INTEGER NOT NULL DEFAULT 0,

                        -- Audit
                        computed_at TIMESTAMPTZ DEFAULT NOW(),
                        source_job_id VARCHAR(64),

                        -- Unique constraint on natural key
                        CONSTRAINT point_stats_unique
                            UNIQUE (h3_index, source_id, category)
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("point_stats")
                ))

                # Index on source_id for source queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_point_stats_source
                    ON {schema}.{table}(source_id)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("point_stats")
                ))

                # Index on h3_index for cell lookups
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_point_stats_h3_index
                    ON {schema}.{table}(h3_index)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("point_stats")
                ))

                # Index on category for category filtering
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_point_stats_category
                    ON {schema}.{table}(category)
                    WHERE category IS NOT NULL
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("point_stats")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Point-in-polygon aggregation results - counts of points within H3 cells. '
                    'Grouped by data source and category. Supports Overture, OSM, custom sources.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("point_stats")
                ))

            step["status"] = "success"
            logger.info("Table h3.point_stats created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # PERMISSIONS
    # ========================================================================

    def _grant_permissions(self, conn, results: Dict):
        """Grant permissions on H3 schema to system user."""
        step = {"name": "grant_permissions", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Grant schema usage
                cur.execute(sql.SQL("""
                    GRANT ALL PRIVILEGES ON SCHEMA {} TO rob634
                """).format(sql.Identifier(self.SCHEMA_NAME)))

                # Grant table permissions
                cur.execute(sql.SQL("""
                    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} TO rob634
                """).format(sql.Identifier(self.SCHEMA_NAME)))

                # Grant sequence permissions
                cur.execute(sql.SQL("""
                    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} TO rob634
                """).format(sql.Identifier(self.SCHEMA_NAME)))

                # Default privileges for future objects
                cur.execute(sql.SQL("""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {}
                    GRANT ALL PRIVILEGES ON TABLES TO rob634
                """).format(sql.Identifier(self.SCHEMA_NAME)))

            step["status"] = "success"
            logger.info("Permissions granted on h3 schema")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def drop_all(self, confirm: bool = False) -> Dict[str, Any]:
        """
        Drop all normalized H3 tables (preserves legacy h3.grids).

        WARNING: Destructive operation - requires confirm=True.

        Args:
            confirm: Must be True to execute drop

        Returns:
            Dict with drop results
        """
        if not confirm:
            return {
                "error": "Drop requires confirm=True",
                "warning": "This will delete h3.cells, cell_admin0, cell_admin1, zonal_stats, point_stats"
            }

        results = {
            "operation": "drop_normalized_tables",
            "timestamp": datetime.utcnow().isoformat(),
            "dropped": [],
            "errors": []
        }

        tables_to_drop = [
            "point_stats",
            "zonal_stats",
            "stat_registry",  # After stats tables (they reference it)
            "cell_admin1",
            "cell_admin0",
            "cells"  # Must be last (FK dependencies)
        ]

        try:
            with self.repo._get_connection() as conn:
                with conn.cursor() as cur:
                    for table in tables_to_drop:
                        try:
                            cur.execute(sql.SQL("""
                                DROP TABLE IF EXISTS {schema}.{table} CASCADE
                            """).format(
                                schema=sql.Identifier(self.SCHEMA_NAME),
                                table=sql.Identifier(table)
                            ))
                            results["dropped"].append(table)
                            logger.info(f"Dropped table h3.{table}")
                        except Exception as e:
                            results["errors"].append(f"{table}: {e}")

                conn.commit()

        except Exception as e:
            results["errors"].append(str(e))

        return results

    def get_table_counts(self) -> Dict[str, int]:
        """Get row counts for all normalized H3 tables."""
        counts = {}
        tables = ["cells", "cell_admin0", "cell_admin1", "stat_registry", "zonal_stats", "point_stats"]

        try:
            with self.repo._get_connection() as conn:
                with conn.cursor() as cur:
                    for table in tables:
                        try:
                            cur.execute(sql.SQL("""
                                SELECT COUNT(*) FROM {schema}.{table}
                            """).format(
                                schema=sql.Identifier(self.SCHEMA_NAME),
                                table=sql.Identifier(table)
                            ))
                            counts[table] = cur.fetchone()['count']
                        except Exception:
                            counts[table] = -1  # Table doesn't exist

        except Exception as e:
            logger.error(f"Failed to get table counts: {e}")

        return counts


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def deploy_h3_normalized_schema() -> Dict[str, Any]:
    """
    Deploy normalized H3 schema.

    Convenience function for use in deployment scripts.

    Returns:
        Dict with deployment results
    """
    deployer = H3SchemaDeployer()
    return deployer.deploy_all()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'H3SchemaDeployer',
    'deploy_h3_normalized_schema'
]
