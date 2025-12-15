-- ============================================================================
-- H3 GRIDS TABLE - PostGIS storage for H3 hexagonal grid cells
-- ============================================================================
-- PURPOSE: Store H3 hexagonal grids with spatial indexing for geospatial queries
-- CREATED: 9 NOV 2025
-- UPDATED: 10 NOV 2025 - Moved to h3 schema, added parent tracking columns
-- SCHEMA: h3 (system-generated grids, separate from user data in geo schema)
-- DEPENDENCIES: PostGIS extension, h3 schema (created by 00_create_h3_schema.sql)
-- ============================================================================

-- Create H3 grids table in h3 schema
CREATE TABLE IF NOT EXISTS h3.grids (
    id SERIAL PRIMARY KEY,

    -- H3 Identification
    h3_index BIGINT NOT NULL,                    -- H3 cell index (uint64 stored as signed bigint)
    resolution INTEGER NOT NULL,                 -- H3 resolution (0-15)

    -- Geometry (hexagon boundary)
    geom GEOMETRY(Polygon, 4326) NOT NULL,      -- Hexagon polygon in WGS84

    -- Grid Metadata
    grid_id VARCHAR(255) NOT NULL,               -- Grid identifier (e.g., "global_res4", "land_res4")
    grid_type VARCHAR(50) NOT NULL,              -- Type: "global", "land", "ocean", "custom"

    -- Hierarchical Tracking (CRITICAL for GeoParquet partitioning)
    parent_res2 BIGINT DEFAULT NULL,             -- Top-level parent H3 index at resolution 2 (for GeoParquet partitioning)
    parent_h3_index BIGINT DEFAULT NULL,         -- Immediate parent H3 index (resolution n-1)

    -- Source Information
    source_job_id VARCHAR(255),                  -- Job that created this cell
    source_blob_path TEXT,                       -- Original GeoParquet path in blob storage

    -- Classification (for land grids)
    is_land BOOLEAN DEFAULT NULL,                -- NULL = unknown, true = land, false = ocean
    land_percentage DECIMAL(5,2) DEFAULT NULL,   -- % land coverage (for coastal cells)

    -- Administrative Attributes (optional, populated from Overture)
    country_code VARCHAR(3),                     -- ISO 3166-1 alpha-3
    admin_level_1 VARCHAR(255),                  -- State/province

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT h3_grids_unique_cell UNIQUE (h3_index, grid_id),
    CONSTRAINT h3_grids_resolution_check CHECK (resolution >= 0 AND resolution <= 15),
    CONSTRAINT h3_grids_land_pct_check CHECK (land_percentage IS NULL OR (land_percentage >= 0 AND land_percentage <= 100))
);

-- Spatial index (GIST) for fast spatial queries
CREATE INDEX IF NOT EXISTS idx_h3_grids_geom
ON h3.grids USING GIST(geom);

-- B-tree index for H3 index lookups
CREATE INDEX IF NOT EXISTS idx_h3_grids_h3_index
ON h3.grids (h3_index);

-- Index for resolution filtering
CREATE INDEX IF NOT EXISTS idx_h3_grids_resolution
ON h3.grids (resolution);

-- Index for grid filtering
CREATE INDEX IF NOT EXISTS idx_h3_grids_grid_id
ON h3.grids (grid_id);

-- Index for parent_res2 (CRITICAL for GeoParquet partition routing)
CREATE INDEX IF NOT EXISTS idx_h3_grids_parent_res2
ON h3.grids (parent_res2)
WHERE parent_res2 IS NOT NULL;

-- Index for parent lookups (cascading children)
CREATE INDEX IF NOT EXISTS idx_h3_grids_parent_h3_index
ON h3.grids (parent_h3_index)
WHERE parent_h3_index IS NOT NULL;

-- Partial index for land/ocean filtering (only index non-null values)
CREATE INDEX IF NOT EXISTS idx_h3_grids_is_land
ON h3.grids (is_land)
WHERE is_land IS NOT NULL;

-- Partial index for country queries (only index non-null values)
CREATE INDEX IF NOT EXISTS idx_h3_grids_country
ON h3.grids (country_code)
WHERE country_code IS NOT NULL;

-- Composite index for common query pattern (grid + resolution)
CREATE INDEX IF NOT EXISTS idx_h3_grids_grid_resolution
ON h3.grids (grid_id, resolution);

-- Table comment
COMMENT ON TABLE h3.grids IS 'System-generated H3 hexagonal grid cells (resolutions 2-7) for Agricultural Geography Platform. Bootstrap data created via cascading hierarchy (res 2→3→4→5→6→7). Read-only for users.';

-- Column comments
COMMENT ON COLUMN h3.grids.h3_index IS 'H3 cell index (64-bit unsigned integer stored as signed bigint)';
COMMENT ON COLUMN h3.grids.resolution IS 'H3 resolution level (0=coarsest ~1100km, 15=finest ~0.5m). Bootstrap creates resolutions 2-7 only.';
COMMENT ON COLUMN h3.grids.geom IS 'Hexagon boundary polygon in WGS84 (EPSG:4326)';
COMMENT ON COLUMN h3.grids.grid_id IS 'Grid identifier (e.g., land_res2, land_res3, ..., land_res7)';
COMMENT ON COLUMN h3.grids.grid_type IS 'Grid type classification: land (default for bootstrap grids)';
COMMENT ON COLUMN h3.grids.parent_res2 IS 'Top-level parent H3 index at resolution 2 (CRITICAL for GeoParquet partitioning). Propagates down hierarchy for spatial locality in exports.';
COMMENT ON COLUMN h3.grids.parent_h3_index IS 'Immediate parent H3 index (resolution n-1). Used for hierarchical queries and validation.';
COMMENT ON COLUMN h3.grids.source_job_id IS 'CoreMachine job ID that created this cell (bootstrap_h3_land_grid_pyramid)';
COMMENT ON COLUMN h3.grids.source_blob_path IS 'Original GeoParquet file path in Azure blob storage (for imported grids)';
COMMENT ON COLUMN h3.grids.is_land IS 'Land classification: true=land (set at res 2 via spatial join with geo.countries), propagates to children';
COMMENT ON COLUMN h3.grids.land_percentage IS 'Percentage of cell covered by land (for coastal cells, future enhancement)';
COMMENT ON COLUMN h3.grids.country_code IS 'ISO 3166-1 alpha-3 country code (set at res 2 via ST_Intersects with geo.countries, propagates to children)';
COMMENT ON COLUMN h3.grids.admin_level_1 IS 'State/province name (future enhancement from Overture Maps)';

-- Grant permissions (system user has full control, setup for future read-only users)
GRANT SELECT, INSERT, UPDATE, DELETE ON h3.grids TO rob634;
GRANT USAGE, SELECT ON SEQUENCE h3.grids_id_seq TO rob634;

-- Future: Grant SELECT-only to read-only users
-- GRANT SELECT ON h3.grids TO readonly_user;

-- Verification queries
SELECT
    'h3.grids table created successfully' AS status,
    COUNT(*) AS row_count
FROM h3.grids;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'h3' AND tablename = 'grids'
ORDER BY indexname;
