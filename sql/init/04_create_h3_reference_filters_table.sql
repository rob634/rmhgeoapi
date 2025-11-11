-- ============================================================================
-- H3 REFERENCE FILTERS TABLE - Store parent IDs for cascading children
-- ============================================================================
-- PURPOSE: Store reference sets of parent H3 indices for cascading operations
-- CREATED: 10 NOV 2025
-- AUTHOR: Robert and Geospatial Claude Legion
-- SCHEMA: h3 (system-generated grids)
-- DEPENDENCIES: h3 schema (created by 00_create_h3_schema.sql)
-- ============================================================================

-- Create H3 reference filters table in h3 schema
CREATE TABLE IF NOT EXISTS h3.reference_filters (
    id SERIAL PRIMARY KEY,

    -- Filter Identification
    filter_name VARCHAR(255) NOT NULL UNIQUE,    -- e.g., "land_res2", "land_res3"
    description TEXT,                            -- Human-readable description

    -- Parent H3 Indices (stored as array for efficient loading)
    h3_indices BIGINT[] NOT NULL,                -- Array of parent H3 indices

    -- Metadata
    resolution INTEGER NOT NULL,                 -- Resolution of stored indices
    cell_count INTEGER NOT NULL,                 -- Number of cells in array
    source_grid_id VARCHAR(255) NOT NULL,        -- Source grid_id from h3.grids
    source_job_id VARCHAR(255),                  -- Job that created this filter

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT h3_reference_filters_resolution_check CHECK (resolution >= 0 AND resolution <= 15),
    CONSTRAINT h3_reference_filters_cell_count_check CHECK (cell_count > 0)
);

-- Index for filter name lookups (primary access pattern)
CREATE INDEX IF NOT EXISTS idx_h3_reference_filters_filter_name
ON h3.reference_filters (filter_name);

-- Index for resolution filtering
CREATE INDEX IF NOT EXISTS idx_h3_reference_filters_resolution
ON h3.reference_filters (resolution);

-- Index for source grid tracking
CREATE INDEX IF NOT EXISTS idx_h3_reference_filters_source_grid
ON h3.reference_filters (source_grid_id);

-- Table comment
COMMENT ON TABLE h3.reference_filters IS 'Reference sets of parent H3 indices for cascading children operations. Stores arrays of parent IDs loaded from h3.grids, enabling efficient batch child generation without repeated database queries. Used by bootstrap handlers to generate resolution n+1 from resolution n.';

-- Column comments
COMMENT ON COLUMN h3.reference_filters.filter_name IS 'Unique filter identifier (e.g., land_res2, land_res3). Used by handlers to load parent IDs.';
COMMENT ON COLUMN h3.reference_filters.description IS 'Human-readable description of filter purpose and contents';
COMMENT ON COLUMN h3.reference_filters.h3_indices IS 'Array of parent H3 indices (BIGINT[]). Handlers iterate this array to generate children.';
COMMENT ON COLUMN h3.reference_filters.resolution IS 'Resolution level of stored parent indices';
COMMENT ON COLUMN h3.reference_filters.cell_count IS 'Number of parent cells in h3_indices array (for validation and progress tracking)';
COMMENT ON COLUMN h3.reference_filters.source_grid_id IS 'Source grid_id from h3.grids table (e.g., land_res2)';
COMMENT ON COLUMN h3.reference_filters.source_job_id IS 'CoreMachine job ID that created this filter (bootstrap_h3_land_grid_pyramid)';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON h3.reference_filters TO rob634;
GRANT USAGE, SELECT ON SEQUENCE h3.reference_filters_id_seq TO rob634;

-- Future: Grant SELECT-only to read-only users
-- GRANT SELECT ON h3.reference_filters TO readonly_user;

-- Verification query
SELECT
    'h3.reference_filters table created successfully' AS status,
    COUNT(*) AS row_count
FROM h3.reference_filters;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'h3' AND tablename = 'reference_filters'
ORDER BY indexname;
