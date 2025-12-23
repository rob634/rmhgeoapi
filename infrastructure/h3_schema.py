# ============================================================================
# CLAUDE CONTEXT - H3 NORMALIZED SCHEMA DEPLOYER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - H3 OLTP Schema DDL
# PURPOSE: Deploy normalized H3 schema (cells, admin mappings, stats tables)
# LAST_REVIEWED: 22 DEC 2025
# EXPORTS: H3SchemaDeployer, deploy_h3_normalized_schema
# DEPENDENCIES: psycopg, pydantic
# ============================================================================
"""
H3 Normalized Schema Deployment.

OLTP System of Record for H3 hexagonal grid data. Normalized design with:
- h3.cells: Unique H3 geometry (stored once per h3_index)
- h3.cell_admin0: Country overlap mapping (1:N)
- h3.cell_admin1: Admin1/Province overlap mapping (1:N)
- h3.dataset_registry: Metadata catalog with source config (Planetary Computer, Azure, URL)
- h3.zonal_stats: Raster aggregation results, PARTITIONED BY THEME for scalability
- h3.point_stats: Point-in-polygon counts (1:N, FK to dataset_registry)

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
from config import get_config

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
        h3.dataset_registry - Metadata catalog with Planetary Computer/Azure source config
        h3.zonal_stats - Raster aggregation results, PARTITIONED BY THEME
        h3.point_stats - Point-in-polygon counts (FK to dataset_registry)
        h3.batch_progress - Resumable job tracking for cascade operations

    Partitioning Strategy (22 DEC 2025):
        zonal_stats is LIST partitioned by 'theme' column for scalability to 1B+ rows.
        Themes: terrain, water, climate, demographics, infrastructure, landcover, vegetation
        Each partition holds ~110-165M rows at 1B total, easily manageable by PostgreSQL.

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

        # Each step runs in its own connection to ensure commits are durable
        steps = [
            ("create_schema", self._deploy_schema),
            ("create_h3_cells", self._deploy_cells_table),
            ("create_h3_cell_admin0", self._deploy_cell_admin0_table),
            ("create_h3_cell_admin1", self._deploy_cell_admin1_table),
            ("create_h3_dataset_registry", self._deploy_dataset_registry_table),
            ("create_h3_zonal_stats_partitioned", self._deploy_zonal_stats_partitioned_table),
            ("create_h3_point_stats", self._deploy_point_stats_table),
            ("create_h3_batch_progress", self._deploy_batch_progress_table),
            ("grant_permissions", self._grant_permissions),
        ]

        for step_name, step_func in steps:
            try:
                with self.repo._get_connection() as conn:
                    step_func(conn, results)
                    conn.commit()
                    logger.info(f"✅ Step '{step_name}' committed successfully")
            except Exception as e:
                logger.error(f"❌ Step '{step_name}' failed: {e}")
                # Error already recorded in results by the step function
                # Continue to next step instead of aborting

        results["success"] = len(results["errors"]) == 0
        logger.info(f"H3 normalized schema deployment complete (errors: {len(results['errors'])})")

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
    # h3.dataset_registry - COMPREHENSIVE METADATA CATALOG (22 DEC 2025)
    # ========================================================================

    # Define valid themes for partitioning (used by zonal_stats)
    VALID_THEMES = [
        'terrain',        # DEM, slope, aspect
        'water',          # Flood hazard, surface water, precipitation
        'climate',        # Temperature, ERA5, CHIRPS
        'demographics',   # Population, buildings, settlements
        'infrastructure', # Roads, nighttime lights, OSM features
        'landcover',      # ESA WorldCover, NLCD, Dynamic World
        'vegetation',     # NDVI, LAI, forest cover
    ]

    def _deploy_dataset_registry_table(self, conn, results: Dict):
        """
        Create h3.dataset_registry table - comprehensive metadata catalog.

        Stores complete source configuration for Planetary Computer, Azure Blob,
        and direct URL sources. Theme column links to zonal_stats partitioning.

        Columns:
            id VARCHAR(100) PRIMARY KEY - Dataset identifier (e.g., 'copdem_glo30')
            display_name VARCHAR(255) - Human-readable name
            description TEXT - Detailed explanation
            theme VARCHAR(50) - Partition key: terrain, water, climate, demographics, etc.
            data_category VARCHAR(100) - Specific category: elevation, flood_depth, population
            source_type VARCHAR(50) - planetary_computer, azure, url
            source_config JSONB - Source-specific parameters (collection, container, etc.)
            stat_types TEXT[] - Available stat types (mean, sum, min, max, std)
            unit VARCHAR(50) - Unit of measurement
            native_resolution DOUBLE PRECISION - Native pixel size in degrees
            recommended_h3_res INTEGER[] - Recommended H3 resolutions
            nodata_value DOUBLE PRECISION - Nodata value for raster
            value_range NUMRANGE - Expected value range for validation
            is_temporal BOOLEAN - Time-series dataset flag
            temporal_resolution VARCHAR(20) - daily, monthly, yearly
            temporal_start TIMESTAMPTZ - Start of temporal extent
            temporal_end TIMESTAMPTZ - End of temporal extent
            source_name VARCHAR(255) - Data source organization
            source_url VARCHAR(500) - Link to documentation
            source_license VARCHAR(100) - SPDX license identifier
            attribution TEXT - Required citation
            last_aggregation_at TIMESTAMPTZ - Last computation time
            aggregation_job_id VARCHAR(64) - Last job ID
            cells_aggregated BIGINT - Number of cells with this stat
        """
        step = {"name": "create_h3_dataset_registry", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Primary key: dataset identifier
                        id VARCHAR(100) PRIMARY KEY,

                        -- Human-readable metadata
                        display_name VARCHAR(255) NOT NULL,
                        description TEXT,

                        -- Classification (theme is partition key for zonal_stats)
                        theme VARCHAR(50) NOT NULL
                            CONSTRAINT dataset_registry_theme_check
                            CHECK (theme IN (
                                'terrain', 'water', 'climate', 'demographics',
                                'infrastructure', 'landcover', 'vegetation'
                            )),
                        data_category VARCHAR(100) NOT NULL,

                        -- Source configuration (flexible JSONB for different source types)
                        source_type VARCHAR(50) NOT NULL
                            CONSTRAINT dataset_registry_source_type_check
                            CHECK (source_type IN ('planetary_computer', 'azure', 'url')),
                        source_config JSONB NOT NULL,
                        /* Source-specific parameters - see dataset_registry documentation */

                        -- Data characteristics
                        stat_types TEXT[] NOT NULL DEFAULT ARRAY['mean'],
                        unit VARCHAR(50),
                        native_resolution DOUBLE PRECISION,
                        recommended_h3_res INTEGER[],
                        nodata_value DOUBLE PRECISION,
                        value_range NUMRANGE,

                        -- Temporal (for time-series datasets)
                        is_temporal BOOLEAN DEFAULT FALSE,
                        temporal_resolution VARCHAR(20),
                        temporal_start TIMESTAMPTZ,
                        temporal_end TIMESTAMPTZ,

                        -- Source attribution
                        source_name VARCHAR(255),
                        source_url VARCHAR(500),
                        source_license VARCHAR(100),
                        attribution TEXT,

                        -- Aggregation state
                        last_aggregation_at TIMESTAMPTZ,
                        aggregation_job_id VARCHAR(64),
                        cells_aggregated BIGINT DEFAULT 0,

                        -- Audit
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("dataset_registry")
                ))

                # Index on theme for partition alignment queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_dataset_registry_theme
                    ON {schema}.{table}(theme)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("dataset_registry")
                ))

                # Index on source_type for source queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_dataset_registry_source_type
                    ON {schema}.{table}(source_type)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("dataset_registry")
                ))

                # Index on data_category for category queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_dataset_registry_category
                    ON {schema}.{table}(data_category)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("dataset_registry")
                ))

                # GIN index on source_config for JSONB queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_dataset_registry_config
                    ON {schema}.{table} USING GIN(source_config)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("dataset_registry")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Comprehensive metadata catalog for H3 aggregation datasets. '
                    'Stores source configuration (Planetary Computer, Azure, URL) and '
                    'links to zonal_stats via dataset_id FK. Theme column aligns with '
                    'zonal_stats partitioning for query optimization.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("dataset_registry")
                ))

            step["status"] = "success"
            logger.info("Table h3.dataset_registry created with indexes")

        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            raise
        finally:
            results["steps"].append(step)

    # ========================================================================
    # h3.zonal_stats - PARTITIONED RASTER AGGREGATION RESULTS (22 DEC 2025)
    # ========================================================================

    def _deploy_zonal_stats_partitioned_table(self, conn, results: Dict):
        """
        Create h3.zonal_stats table - PARTITIONED BY THEME for billion-row scale.

        List partitioning by theme enables:
        - 6-9 partitions of ~110-165M rows each at 1B total
        - Partition pruning when queries filter by theme
        - Independent maintenance (VACUUM, REINDEX) per partition
        - Future partition detachment for archival

        Columns:
            theme VARCHAR(50) - PARTITION KEY: terrain, water, climate, etc.
            h3_index BIGINT FK - References h3.cells
            dataset_id VARCHAR(100) FK - References h3.dataset_registry
            band VARCHAR(50) - Raster band name (default: 'band_1')
            stat_type VARCHAR(20) - Statistic type (mean, sum, min, max, count, std)
            value DOUBLE PRECISION - Computed statistic value
            pixel_count INTEGER - Number of pixels in aggregation
            nodata_count INTEGER - Pixels with nodata
            computed_at TIMESTAMPTZ - When stat was computed
            source_job_id VARCHAR(64) - Job that computed this stat

        Unique constraint on (theme, h3_index, dataset_id, band, stat_type).
        """
        step = {"name": "create_h3_zonal_stats_partitioned", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Check if table exists and is NOT partitioned (legacy table)
                cur.execute("""
                    SELECT c.relkind, c.relispartition
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'h3' AND c.relname = 'zonal_stats'
                """)
                row = cur.fetchone()

                if row:
                    relkind = row.get('relkind')
                    # 'p' = partitioned table, 'r' = regular table
                    if relkind == 'r':
                        logger.warning("⚠️ Found non-partitioned h3.zonal_stats - dropping for partitioned rebuild")
                        cur.execute(sql.SQL("DROP TABLE IF EXISTS {schema}.{table} CASCADE").format(
                            schema=sql.Identifier(self.SCHEMA_NAME),
                            table=sql.Identifier("zonal_stats")
                        ))
                        logger.info("🗑️ Dropped legacy h3.zonal_stats table")

                # Create PARTITIONED parent table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Partition key (MUST be first for partitioning)
                        theme VARCHAR(50) NOT NULL
                            CONSTRAINT zonal_stats_theme_check
                            CHECK (theme IN (
                                'terrain', 'water', 'climate', 'demographics',
                                'infrastructure', 'landcover', 'vegetation'
                            )),

                        -- Composite natural key
                        h3_index BIGINT NOT NULL,
                        dataset_id VARCHAR(100) NOT NULL,
                        band VARCHAR(50) NOT NULL DEFAULT 'band_1',
                        stat_type VARCHAR(20) NOT NULL,

                        -- Computed values
                        value DOUBLE PRECISION,
                        pixel_count INTEGER,
                        nodata_count INTEGER,

                        -- Audit
                        computed_at TIMESTAMPTZ DEFAULT NOW(),
                        source_job_id VARCHAR(64),

                        -- Primary key MUST include partition key
                        PRIMARY KEY (theme, h3_index, dataset_id, band, stat_type)
                    ) PARTITION BY LIST (theme)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Create partitions for each theme
                for theme in self.VALID_THEMES:
                    partition_name = f"zonal_stats_{theme}"
                    cur.execute(sql.SQL("""
                        CREATE TABLE IF NOT EXISTS {schema}.{partition}
                        PARTITION OF {schema}.{parent}
                        FOR VALUES IN (%s)
                    """).format(
                        schema=sql.Identifier(self.SCHEMA_NAME),
                        partition=sql.Identifier(partition_name),
                        parent=sql.Identifier("zonal_stats")
                    ), (theme,))
                    logger.info(f"  Created partition h3.{partition_name}")

                # Create indexes on parent (automatically propagated to partitions)
                # Index on h3_index for cell lookups
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_zonal_stats_h3_index
                    ON {schema}.{table}(h3_index)
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

                # Composite index for common query pattern
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_zonal_stats_dataset_stat
                    ON {schema}.{table}(dataset_id, stat_type)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Index for job tracking
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_zonal_stats_job
                    ON {schema}.{table}(source_job_id)
                    WHERE source_job_id IS NOT NULL
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Pre-computed zonal statistics from raster datasets aggregated to H3 cells. '
                    'PARTITIONED BY THEME for billion-row scalability. '
                    'Themes: terrain, water, climate, demographics, infrastructure, landcover, vegetation. '
                    'Each partition: ~110-165M rows at 1B total. '
                    'stat_type: mean, sum, min, max, count, std, median.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("zonal_stats")
                ))

            step["status"] = "success"
            step["partitions"] = self.VALID_THEMES
            logger.info(f"Table h3.zonal_stats created with {len(self.VALID_THEMES)} partitions")

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
    # h3.batch_progress - RESUMABLE JOB TRACKING
    # ========================================================================

    def _deploy_batch_progress_table(self, conn, results: Dict):
        """
        Create h3.batch_progress table - enables resumable H3 cascade jobs.

        Tracks which batches have completed so failed jobs can resume from
        where they left off rather than re-running completed work.

        Columns:
            id SERIAL PRIMARY KEY - Auto-increment ID
            job_id VARCHAR(64) - CoreMachine job ID (SHA256)
            batch_id VARCHAR(100) - Unique batch identifier
            operation_type VARCHAR(50) - Handler operation type
            stage_number INTEGER - Stage number in job
            batch_index INTEGER - Zero-based batch index
            status VARCHAR(20) - pending/processing/completed/failed
            items_processed INTEGER - Number of items processed
            items_inserted INTEGER - Number of items inserted (excludes duplicates)
            error_message TEXT - Error details for failed batches
            started_at TIMESTAMPTZ - When batch started
            completed_at TIMESTAMPTZ - When batch completed
            created_at TIMESTAMPTZ - Record creation time
            updated_at TIMESTAMPTZ - Last update time

        Unique constraint on (job_id, batch_id).
        """
        step = {"name": "create_h3_batch_progress", "status": "pending"}

        try:
            with conn.cursor() as cur:
                # Create table
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {schema}.{table} (
                        -- Primary key
                        id SERIAL PRIMARY KEY,

                        -- Job and batch identification
                        job_id VARCHAR(64) NOT NULL,
                        batch_id VARCHAR(100) NOT NULL,

                        -- Operation metadata
                        operation_type VARCHAR(50) NOT NULL DEFAULT 'cascade',
                        stage_number INTEGER NOT NULL DEFAULT 2,
                        batch_index INTEGER,

                        -- Status tracking
                        status VARCHAR(20) NOT NULL DEFAULT 'pending'
                            CONSTRAINT batch_progress_status_check
                            CHECK (status IN ('pending', 'processing', 'completed', 'failed')),

                        -- Completion metrics
                        items_processed INTEGER DEFAULT 0,
                        items_inserted INTEGER DEFAULT 0,

                        -- Error tracking
                        error_message TEXT,

                        -- Timestamps
                        started_at TIMESTAMPTZ,
                        completed_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW(),

                        -- Unique constraint for idempotency
                        CONSTRAINT batch_progress_unique UNIQUE (job_id, batch_id)
                    )
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("batch_progress")
                ))

                # Index on job_id for job queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_job_id
                    ON {schema}.{table}(job_id)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("batch_progress")
                ))

                # Index on status for incomplete batch queries
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_status
                    ON {schema}.{table}(status)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("batch_progress")
                ))

                # Composite index for common query pattern
                cur.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_job_stage
                    ON {schema}.{table}(job_id, stage_number)
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("batch_progress")
                ))

                # Table comment
                cur.execute(sql.SQL("""
                    COMMENT ON TABLE {schema}.{table} IS
                    'Batch-level completion tracking for resumable H3 cascade jobs. '
                    'When a job fails partway through, only incomplete batches are re-executed. '
                    'Part of 3-layer idempotency: DB constraints → batch tracking → handler checks.'
                """).format(
                    schema=sql.Identifier(self.SCHEMA_NAME),
                    table=sql.Identifier("batch_progress")
                ))

            step["status"] = "success"
            logger.info("Table h3.batch_progress created with indexes")

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
        """Grant permissions on H3 schema to configured admin identity."""
        step = {"name": "grant_permissions", "status": "pending"}

        try:
            # Get admin identity from config - NO HARDCODED USERS
            config = get_config()
            admin_identity = config.database.admin_identity_name
            if not admin_identity:
                raise ValueError("database.admin_identity_name not configured - cannot grant permissions")

            admin_ident = sql.Identifier(admin_identity)
            schema_ident = sql.Identifier(self.SCHEMA_NAME)

            with conn.cursor() as cur:
                # Grant schema usage
                cur.execute(sql.SQL("""
                    GRANT ALL PRIVILEGES ON SCHEMA {} TO {}
                """).format(schema_ident, admin_ident))

                # Grant table permissions
                cur.execute(sql.SQL("""
                    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {} TO {}
                """).format(schema_ident, admin_ident))

                # Grant sequence permissions
                cur.execute(sql.SQL("""
                    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {} TO {}
                """).format(schema_ident, admin_ident))

                # Default privileges for future objects
                cur.execute(sql.SQL("""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {}
                    GRANT ALL PRIVILEGES ON TABLES TO {}
                """).format(schema_ident, admin_ident))

                cur.execute(sql.SQL("""
                    ALTER DEFAULT PRIVILEGES IN SCHEMA {}
                    GRANT ALL PRIVILEGES ON SEQUENCES TO {}
                """).format(schema_ident, admin_ident))

            step["status"] = "success"
            step["admin_identity"] = admin_identity
            logger.info(f"Permissions granted on h3 schema to {admin_identity}")

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
            "batch_progress",  # No FK dependencies
            "point_stats",
            # Drop all zonal_stats partitions first
            "zonal_stats_terrain",
            "zonal_stats_water",
            "zonal_stats_climate",
            "zonal_stats_demographics",
            "zonal_stats_infrastructure",
            "zonal_stats_landcover",
            "zonal_stats_vegetation",
            "zonal_stats",  # Parent partitioned table
            "dataset_registry",  # After stats tables (they reference it)
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
        tables = ["cells", "cell_admin0", "cell_admin1", "dataset_registry", "zonal_stats", "point_stats", "batch_progress"]

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
