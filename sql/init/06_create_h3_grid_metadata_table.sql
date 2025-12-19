-- ============================================================================
-- ⚠️  DEPRECATED - DO NOT USE DIRECTLY
-- ============================================================================
-- This SQL file is DEPRECATED as of 17 DEC 2025.
-- USE: POST /api/dbadmin/maintenance?action=full-rebuild&confirm=yes
-- The H3 schema is now deployed via H3SchemaDeployer with managed identity.
-- This file is retained for HISTORICAL REFERENCE ONLY.
-- ============================================================================

-- ============================================================================
-- H3 GRID METADATA TABLE - Track bootstrap progress and grid statistics
-- ============================================================================
-- PURPOSE: Store metadata about H3 grids for bootstrap status tracking and verification
-- CREATED: 10 NOV 2025
-- DEPRECATED: 17 DEC 2025 - Use H3SchemaDeployer instead
-- SCHEMA: h3 (system-generated grids)
-- DEPENDENCIES: h3 schema (created by 00_create_h3_schema.sql)
-- ============================================================================

-- Create H3 grid metadata table in h3 schema
CREATE TABLE IF NOT EXISTS h3.grid_metadata (
    id SERIAL PRIMARY KEY,

    -- Grid Identification
    grid_id VARCHAR(255) NOT NULL UNIQUE,        -- Grid identifier (e.g., "land_res2", "land_res3")
    resolution INTEGER NOT NULL,                 -- H3 resolution (2-7 for bootstrap)

    -- Status Tracking
    status VARCHAR(50) NOT NULL,                 -- "pending", "processing", "completed", "failed"
    progress_percentage DECIMAL(5,2) DEFAULT 0,  -- 0.00 to 100.00

    -- Cell Statistics
    cell_count BIGINT DEFAULT 0,                 -- Number of cells in this grid
    expected_cell_count BIGINT DEFAULT NULL,     -- Expected cell count (for validation)
    land_cell_count BIGINT DEFAULT NULL,         -- Cells with is_land=true
    country_count INTEGER DEFAULT NULL,          -- Number of unique countries

    -- Spatial Extent (for quick map rendering)
    bbox_minx DECIMAL(10, 6) DEFAULT NULL,       -- Bounding box min longitude
    bbox_miny DECIMAL(10, 6) DEFAULT NULL,       -- Bounding box min latitude
    bbox_maxx DECIMAL(10, 6) DEFAULT NULL,       -- Bounding box max longitude
    bbox_maxy DECIMAL(10, 6) DEFAULT NULL,       -- Bounding box max latitude

    -- Source Information
    source_job_id VARCHAR(255),                  -- Bootstrap job ID
    parent_grid_id VARCHAR(255) DEFAULT NULL,    -- Parent grid (for cascade tracking)

    -- Processing Metrics
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    completed_at TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    processing_duration_seconds INTEGER DEFAULT NULL,

    -- Error Tracking
    error_message TEXT DEFAULT NULL,
    retry_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT h3_grid_metadata_resolution_check CHECK (resolution >= 0 AND resolution <= 15),
    CONSTRAINT h3_grid_metadata_status_check CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT h3_grid_metadata_progress_check CHECK (progress_percentage >= 0 AND progress_percentage <= 100),
    CONSTRAINT h3_grid_metadata_cell_count_check CHECK (cell_count >= 0),
    CONSTRAINT h3_grid_metadata_bbox_check CHECK (
        (bbox_minx IS NULL AND bbox_miny IS NULL AND bbox_maxx IS NULL AND bbox_maxy IS NULL) OR
        (bbox_minx IS NOT NULL AND bbox_miny IS NOT NULL AND bbox_maxx IS NOT NULL AND bbox_maxy IS NOT NULL AND
         bbox_minx >= -180 AND bbox_minx <= 180 AND
         bbox_miny >= -90 AND bbox_miny <= 90 AND
         bbox_maxx >= -180 AND bbox_maxx <= 180 AND
         bbox_maxy >= -90 AND bbox_maxy <= 90 AND
         bbox_minx <= bbox_maxx AND bbox_miny <= bbox_maxy)
    )
);

-- Index for grid_id lookups (primary access pattern)
CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_grid_id
ON h3.grid_metadata (grid_id);

-- Index for resolution filtering
CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_resolution
ON h3.grid_metadata (resolution);

-- Index for status filtering (bootstrap progress queries)
CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_status
ON h3.grid_metadata (status);

-- Index for job tracking
CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_source_job
ON h3.grid_metadata (source_job_id)
WHERE source_job_id IS NOT NULL;

-- Index for parent tracking (cascade hierarchy)
CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_parent_grid
ON h3.grid_metadata (parent_grid_id)
WHERE parent_grid_id IS NOT NULL;

-- Composite index for common query pattern (resolution + status)
CREATE INDEX IF NOT EXISTS idx_h3_grid_metadata_resolution_status
ON h3.grid_metadata (resolution, status);

-- Table comment
COMMENT ON TABLE h3.grid_metadata IS 'Metadata tracking for H3 bootstrap grids (resolutions 2-7). Tracks progress, statistics, spatial extent, and errors for each grid. Used by bootstrap status endpoint and finalization handlers.';

-- Column comments
COMMENT ON COLUMN h3.grid_metadata.grid_id IS 'Unique grid identifier (e.g., land_res2). Matches grid_id in h3.grids table.';
COMMENT ON COLUMN h3.grid_metadata.resolution IS 'H3 resolution level (2-7 for bootstrap)';
COMMENT ON COLUMN h3.grid_metadata.status IS 'Bootstrap status: pending (not started), processing (in progress), completed (success), failed (error)';
COMMENT ON COLUMN h3.grid_metadata.progress_percentage IS 'Progress 0.00 to 100.00 (for long-running operations)';
COMMENT ON COLUMN h3.grid_metadata.cell_count IS 'Actual number of cells in h3.grids for this grid_id';
COMMENT ON COLUMN h3.grid_metadata.expected_cell_count IS 'Expected cell count (for validation, e.g., parent_count × 7 for children)';
COMMENT ON COLUMN h3.grid_metadata.land_cell_count IS 'Number of cells with is_land=true';
COMMENT ON COLUMN h3.grid_metadata.country_count IS 'Number of unique countries in this grid (from country_code)';
COMMENT ON COLUMN h3.grid_metadata.bbox_minx IS 'Bounding box minimum longitude (WGS84)';
COMMENT ON COLUMN h3.grid_metadata.bbox_miny IS 'Bounding box minimum latitude (WGS84)';
COMMENT ON COLUMN h3.grid_metadata.bbox_maxx IS 'Bounding box maximum longitude (WGS84)';
COMMENT ON COLUMN h3.grid_metadata.bbox_maxy IS 'Bounding box maximum latitude (WGS84)';
COMMENT ON COLUMN h3.grid_metadata.source_job_id IS 'CoreMachine job ID that created this grid (bootstrap_h3_land_grid_pyramid)';
COMMENT ON COLUMN h3.grid_metadata.parent_grid_id IS 'Parent grid_id for cascade tracking (e.g., land_res2 is parent of land_res3)';
COMMENT ON COLUMN h3.grid_metadata.started_at IS 'Timestamp when bootstrap processing started';
COMMENT ON COLUMN h3.grid_metadata.completed_at IS 'Timestamp when bootstrap processing completed';
COMMENT ON COLUMN h3.grid_metadata.processing_duration_seconds IS 'Total processing time in seconds';
COMMENT ON COLUMN h3.grid_metadata.error_message IS 'Error message if status=failed';
COMMENT ON COLUMN h3.grid_metadata.retry_count IS 'Number of retry attempts (for transient failures)';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON h3.grid_metadata TO {db_superuser};
GRANT USAGE, SELECT ON SEQUENCE h3.grid_metadata_id_seq TO {db_superuser};

-- Future: Grant SELECT-only to read-only users
-- GRANT SELECT ON h3.grid_metadata TO readonly_user;

-- Verification query
SELECT
    'h3.grid_metadata table created successfully' AS status,
    COUNT(*) AS row_count
FROM h3.grid_metadata;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'h3' AND tablename = 'grid_metadata'
ORDER BY indexname;
