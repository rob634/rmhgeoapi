-- ============================================================================
-- H3 BATCH PROGRESS TABLE - Batch-level idempotency tracking
-- ============================================================================
-- PURPOSE: Track completion status of H3 operation batches for resumable jobs
-- CREATED: 26 NOV 2025
-- AUTHOR: Robert and Geospatial Claude Legion
-- SCHEMA: h3 (system-generated grids, separate from user data in geo schema)
-- DEPENDENCIES: h3 schema (created by 00_create_h3_schema.sql)
-- ============================================================================
--
-- IDEMPOTENCY PATTERN:
--   This table enables batch-level resume for H3 operations. When a job fails
--   partway through Stage 2 (cascade fan-out with ~200 batches), only incomplete
--   batches are re-executed on retry instead of all batches.
--
-- WORKFLOW:
--   1. Job creates N batch tasks (each gets a unique batch_id)
--   2. Handler calls start_batch() → creates row with status='processing'
--   3. Handler completes → complete_batch() sets status='completed'
--   4. On job restart, create_tasks_for_stage() queries completed batches
--   5. Only incomplete batches get new tasks created
--
-- EXTENSIBILITY:
--   Same table works for grid generation AND future aggregation jobs.
--   Use operation_type to distinguish: 'cascade_h3_descendants', 'zonal_stats', etc.
--
-- ============================================================================

CREATE TABLE IF NOT EXISTS h3.batch_progress (
    id SERIAL PRIMARY KEY,

    -- Batch Identification
    job_id VARCHAR(64) NOT NULL,              -- CoreMachine job ID (SHA256 hash)
    batch_id VARCHAR(100) NOT NULL,           -- Unique batch ID (e.g., "abc123-s2-batch42")
    operation_type VARCHAR(50) NOT NULL,      -- Operation: 'cascade_h3_descendants', 'zonal_stats', etc.
    stage_number INT NOT NULL,                -- Stage this batch belongs to (e.g., 2 for cascade)
    batch_index INT NOT NULL,                 -- Batch number (0, 1, 2, ..., N-1)

    -- Status Tracking
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Results (stored for debugging/verification)
    items_processed INT DEFAULT 0,            -- Number of items processed (parent cells, raster tiles, etc.)
    items_inserted INT DEFAULT 0,             -- Number of items inserted (excludes ON CONFLICT skips)
    error_message TEXT,                       -- Error details if status='failed'

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Constraints
    CONSTRAINT h3_batch_progress_unique UNIQUE (job_id, batch_id),
    CONSTRAINT h3_batch_status_check CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    ),
    CONSTRAINT h3_batch_index_check CHECK (batch_index >= 0),
    CONSTRAINT h3_batch_stage_check CHECK (stage_number >= 1)
);

-- Index for job-level queries (get all batches for a job)
CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_job_id
ON h3.batch_progress (job_id);

-- Index for job+stage queries (get completed batches for Stage 2)
CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_job_stage
ON h3.batch_progress (job_id, stage_number);

-- Partial index for incomplete batches (fast resume query)
CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_incomplete
ON h3.batch_progress (job_id, stage_number)
WHERE status NOT IN ('completed');

-- Index for status monitoring (find all failed batches)
CREATE INDEX IF NOT EXISTS idx_h3_batch_progress_status
ON h3.batch_progress (status)
WHERE status IN ('failed', 'processing');

-- Table comment
COMMENT ON TABLE h3.batch_progress IS 'Batch-level completion tracking for H3 operations. Enables resumable jobs - only incomplete batches re-execute on retry. Used by cascade_h3_descendants and future aggregation handlers.';

-- Column comments
COMMENT ON COLUMN h3.batch_progress.job_id IS 'CoreMachine job ID (SHA256 hash of job parameters)';
COMMENT ON COLUMN h3.batch_progress.batch_id IS 'Unique batch identifier (format: {job_id[:8]}-s{stage}-batch{index})';
COMMENT ON COLUMN h3.batch_progress.operation_type IS 'Handler operation type: cascade_h3_descendants, zonal_stats, aggregate_raster, etc.';
COMMENT ON COLUMN h3.batch_progress.stage_number IS 'CoreMachine stage number (e.g., 2 for Stage 2 cascade fan-out)';
COMMENT ON COLUMN h3.batch_progress.batch_index IS 'Zero-based batch index within the stage (0, 1, 2, ..., N-1)';
COMMENT ON COLUMN h3.batch_progress.status IS 'Batch status: pending (created), processing (started), completed (success), failed (error)';
COMMENT ON COLUMN h3.batch_progress.items_processed IS 'Number of items processed (e.g., parent cells for cascade, raster tiles for aggregation)';
COMMENT ON COLUMN h3.batch_progress.items_inserted IS 'Number of items actually inserted (excludes ON CONFLICT duplicates)';
COMMENT ON COLUMN h3.batch_progress.error_message IS 'Error details if batch failed (for debugging and retry decisions)';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON h3.batch_progress TO rob634;
GRANT USAGE, SELECT ON SEQUENCE h3.batch_progress_id_seq TO rob634;

-- Verification query
SELECT
    'h3.batch_progress table created successfully' AS status,
    COUNT(*) AS row_count
FROM h3.batch_progress;
