-- ============================================================================
-- H3 GRIDS TABLE - PostGIS storage for H3 hexagonal grid cells
-- ============================================================================
-- PURPOSE: Store H3 hexagonal grids with spatial indexing for geospatial queries
-- CREATED: 9 NOV 2025
-- AUTHOR: Robert and Geospatial Claude Legion
-- SCHEMA: geo
-- DEPENDENCIES: PostGIS extension
-- ============================================================================

-- Create H3 grids table in geo schema
CREATE TABLE IF NOT EXISTS geo.h3_grids (
    id SERIAL PRIMARY KEY,

    -- H3 Identification
    h3_index BIGINT NOT NULL,                    -- H3 cell index (uint64 stored as signed bigint)
    resolution INTEGER NOT NULL,                 -- H3 resolution (0-15)

    -- Geometry (hexagon boundary)
    geom GEOMETRY(Polygon, 4326) NOT NULL,      -- Hexagon polygon in WGS84

    -- Grid Metadata
    grid_id VARCHAR(255) NOT NULL,               -- Grid identifier (e.g., "global_res4", "land_res4")
    grid_type VARCHAR(50) NOT NULL,              -- Type: "global", "land", "ocean", "custom"

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
ON geo.h3_grids USING GIST(geom);

-- B-tree index for H3 index lookups
CREATE INDEX IF NOT EXISTS idx_h3_grids_h3_index
ON geo.h3_grids (h3_index);

-- Index for resolution filtering
CREATE INDEX IF NOT EXISTS idx_h3_grids_resolution
ON geo.h3_grids (resolution);

-- Index for grid filtering
CREATE INDEX IF NOT EXISTS idx_h3_grids_grid_id
ON geo.h3_grids (grid_id);

-- Partial index for land/ocean filtering (only index non-null values)
CREATE INDEX IF NOT EXISTS idx_h3_grids_is_land
ON geo.h3_grids (is_land)
WHERE is_land IS NOT NULL;

-- Partial index for country queries (only index non-null values)
CREATE INDEX IF NOT EXISTS idx_h3_grids_country
ON geo.h3_grids (country_code)
WHERE country_code IS NOT NULL;

-- Composite index for common query pattern (grid + resolution)
CREATE INDEX IF NOT EXISTS idx_h3_grids_grid_resolution
ON geo.h3_grids (grid_id, resolution);

-- Table comment
COMMENT ON TABLE geo.h3_grids IS 'H3 hexagonal grid cells with spatial indexing for geospatial queries. Supports global grids, land-filtered grids, and custom AOI grids at resolutions 0-15.';

-- Column comments
COMMENT ON COLUMN geo.h3_grids.h3_index IS 'H3 cell index (64-bit unsigned integer stored as signed bigint)';
COMMENT ON COLUMN geo.h3_grids.resolution IS 'H3 resolution level (0=coarsest ~1100km, 15=finest ~0.5m)';
COMMENT ON COLUMN geo.h3_grids.geom IS 'Hexagon boundary polygon in WGS84 (EPSG:4326)';
COMMENT ON COLUMN geo.h3_grids.grid_id IS 'Grid identifier for grouping cells (e.g., global_res4, land_res4, user_aoi_res6)';
COMMENT ON COLUMN geo.h3_grids.grid_type IS 'Grid type classification: global, land, ocean, or custom';
COMMENT ON COLUMN geo.h3_grids.source_job_id IS 'CoreMachine job ID that created this cell';
COMMENT ON COLUMN geo.h3_grids.source_blob_path IS 'Original GeoParquet file path in Azure blob storage';
COMMENT ON COLUMN geo.h3_grids.is_land IS 'Land classification: true=land, false=ocean, null=unknown';
COMMENT ON COLUMN geo.h3_grids.land_percentage IS 'Percentage of cell covered by land (for coastal cells)';
COMMENT ON COLUMN geo.h3_grids.country_code IS 'ISO 3166-1 alpha-3 country code (from Overture Maps)';
COMMENT ON COLUMN geo.h3_grids.admin_level_1 IS 'State/province name (from Overture Maps)';

-- Grant permissions (adjust user as needed for production)
GRANT SELECT, INSERT, UPDATE, DELETE ON geo.h3_grids TO rob634;
GRANT USAGE, SELECT ON SEQUENCE geo.h3_grids_id_seq TO rob634;

-- Verification queries
SELECT
    'geo.h3_grids table created successfully' AS status,
    COUNT(*) AS row_count
FROM geo.h3_grids;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'geo' AND tablename = 'h3_grids'
ORDER BY indexname;
