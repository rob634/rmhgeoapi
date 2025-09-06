-- =============================================================================
-- Azure Geospatial ETL Pipeline - PostgreSQL Schema Definition
-- =============================================================================
-- 
-- Job→Task Architecture Database Schema for Azure Functions
-- Based on Pydantic models in schema_core.py
-- 
-- Design Principles:
-- - Explicit constraints prevent silent failures
-- - Foreign keys enforce data integrity
-- - Atomic operations prevent race conditions
-- - JSONB for flexible parameter storage
-- - Proper indexing for Azure Functions scale
--
-- Usage: Execute against rmhpgflex.postgres.database.azure.com geo schema
-- =============================================================================

-- Create application schema if it doesn't exist
-- Note: Schema name will be replaced by APP_SCHEMA environment variable
CREATE SCHEMA IF NOT EXISTS app;

-- Set default schema for this session  
-- Note: This will be dynamically replaced with actual APP_SCHEMA value
SET search_path TO app, public;

-- =============================================================================
-- ENUMS - Type-safe status management
-- =============================================================================

-- Job status enum matching JobStatus in schema_core.py
DO $$ BEGIN
    CREATE TYPE job_status AS ENUM (
        'queued',               -- Initial state after creation
        'processing',           -- Job is actively processing stages
        'completed',           -- All stages completed successfully
        'failed',              -- Job failed with unrecoverable error
        'completed_with_errors' -- Job completed but some tasks had errors
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Task status enum matching TaskStatus in schema_core.py
DO $$ BEGIN
    CREATE TYPE task_status AS ENUM (
        'queued',      -- Task created but not started
        'processing',  -- Task actively running
        'completed',   -- Task finished successfully
        'failed'       -- Task failed with error
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- JOBS TABLE - Primary job orchestration
-- =============================================================================

CREATE TABLE jobs (
    -- Primary identifiers (IMMUTABLE)
    job_id VARCHAR(64) PRIMARY KEY 
        CHECK (length(job_id) = 64 AND job_id ~ '^[a-f0-9]+$'),
        -- SHA256 hash format validation
    
    job_type VARCHAR(50) NOT NULL
        CHECK (length(job_type) >= 1 AND job_type ~ '^[a-z_]+$'),
        -- snake_case format validation
    
    -- State management (MUTABLE with constraints)
    status job_status NOT NULL DEFAULT 'queued',
    
    stage INTEGER NOT NULL DEFAULT 1
        CHECK (stage >= 1 AND stage <= 100),
        -- Current stage being processed
    
    total_stages INTEGER NOT NULL DEFAULT 1  
        CHECK (total_stages >= 1 AND total_stages <= 100),
        -- Total number of stages in workflow
    
    -- Data containers (VALIDATED JSONB)
    parameters JSONB NOT NULL DEFAULT '{}',
        -- Job input parameters, validated by Pydantic
    
    stage_results JSONB NOT NULL DEFAULT '{}',  
        -- Results from completed stages {stage_number: result_data}
    
    result_data JSONB NULL,
        -- Final aggregated job results (NULL until completion)
    
    -- Error handling (STRUCTURED)
    error_details TEXT NULL,
        -- Detailed error information if job failed
    
    -- Audit trail (IMMUTABLE timestamps)
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Table constraints
    CONSTRAINT jobs_stage_consistency 
        CHECK (stage <= total_stages),
        -- Current stage cannot exceed total stages
    
    CONSTRAINT jobs_completed_has_result
        CHECK (
            (status = 'completed' AND result_data IS NOT NULL) OR 
            (status != 'completed')
        ),
        -- Completed jobs must have result_data
        
    CONSTRAINT jobs_failed_has_error
        CHECK (
            (status = 'failed' AND error_details IS NOT NULL) OR
            (status != 'failed')
        )
        -- Failed jobs must have error details
);

-- =============================================================================
-- TASKS TABLE - Individual task execution units  
-- =============================================================================

CREATE TABLE tasks (
    -- Primary identifiers (IMMUTABLE)
    task_id VARCHAR(100) PRIMARY KEY
        CHECK (length(task_id) >= 1),
        -- Unique task identifier (can include job_id prefix)
    
    parent_job_id VARCHAR(64) NOT NULL 
        REFERENCES jobs(job_id) ON DELETE CASCADE
        CHECK (length(parent_job_id) = 64 AND parent_job_id ~ '^[a-f0-9]+$'),
        -- Foreign key to jobs table with cascade delete
    
    task_type VARCHAR(50) NOT NULL
        CHECK (length(task_type) >= 1 AND task_type ~ '^[a-z_]+$'),
        -- snake_case task type validation
    
    -- State management (MUTABLE with constraints)
    status task_status NOT NULL DEFAULT 'queued',
    
    -- Hierarchy (IMMUTABLE after creation)
    stage INTEGER NOT NULL 
        CHECK (stage >= 1 AND stage <= 100),
        -- Stage number this task belongs to
    
    task_index INTEGER NOT NULL 
        CHECK (task_index >= 0 AND task_index <= 10000),
        -- Index within stage (0-based for parallel tasks)
    
    -- Data containers (VALIDATED JSONB)
    parameters JSONB NOT NULL DEFAULT '{}',
        -- Task-specific parameters, validated by Pydantic
    
    result_data JSONB NULL,
        -- Task execution results (NULL until completion)
    
    -- Error handling & retry (STRUCTURED)
    error_details TEXT NULL,
        -- Detailed error information if task failed
    
    retry_count INTEGER NOT NULL DEFAULT 0
        CHECK (retry_count >= 0 AND retry_count <= 10),
        -- Number of retry attempts
    
    -- Health monitoring (MUTABLE for heartbeat updates)
    heartbeat TIMESTAMP NULL,
        -- Last heartbeat for long-running tasks
    
    -- Audit trail (IMMUTABLE timestamps)
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    
    -- Note: Removed tasks_stage_matches_job constraint as PostgreSQL doesn't allow subqueries in CHECK constraints
);

-- =============================================================================
-- PERFORMANCE INDEXES - Optimized for Azure Functions workload
-- =============================================================================

-- Jobs table indexes
CREATE INDEX idx_jobs_status ON jobs(status);
    -- Fast filtering by status for monitoring

CREATE INDEX idx_jobs_job_type ON jobs(job_type);  
    -- Fast filtering by job type for analytics

CREATE INDEX idx_jobs_created_at ON jobs(created_at);
    -- Time-based queries for cleanup and monitoring

CREATE INDEX idx_jobs_updated_at ON jobs(updated_at);
    -- Recently updated jobs

-- Tasks table indexes  
CREATE INDEX idx_tasks_parent_job_id ON tasks(parent_job_id);
    -- Fast lookup of all tasks for a job (most common query)

CREATE INDEX idx_tasks_status ON tasks(status);
    -- Fast filtering by status for processing

CREATE INDEX idx_tasks_job_stage ON tasks(parent_job_id, stage);  
    -- Fast lookup of tasks by job and stage (completion detection)

CREATE INDEX idx_tasks_job_stage_status ON tasks(parent_job_id, stage, status);
    -- Optimized for "last task turns out lights" queries

CREATE INDEX idx_tasks_heartbeat ON tasks(heartbeat) WHERE heartbeat IS NOT NULL;
    -- Monitor stale tasks (partial index for performance)

CREATE INDEX idx_tasks_retry_count ON tasks(retry_count) WHERE retry_count > 0;
    -- Monitor tasks that required retries (partial index)

-- =============================================================================
-- ATOMIC COMPLETION FUNCTIONS - Race condition prevention
-- =============================================================================

-- Function to atomically complete a task and detect stage completion
CREATE OR REPLACE FUNCTION complete_task_and_check_stage(
    p_task_id VARCHAR(100),
    p_result_data JSONB DEFAULT NULL,
    p_error_details TEXT DEFAULT NULL
)
RETURNS TABLE (
    task_updated BOOLEAN,
    is_last_task_in_stage BOOLEAN,
    job_id VARCHAR(64),
    stage_number INTEGER,
    remaining_tasks INTEGER
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id VARCHAR(64);
    v_stage INTEGER;
    v_remaining INTEGER;
    v_task_status task_status;
BEGIN
    -- Get task info and update atomically
    UPDATE app.tasks 
    SET 
        status = CASE 
            WHEN p_error_details IS NOT NULL THEN 'failed'::task_status
            ELSE 'completed'::task_status
        END,
        result_data = p_result_data,
        error_details = p_error_details,
        updated_at = NOW()
    WHERE 
        task_id = p_task_id 
        AND status = 'processing'  -- Only update if currently processing
    RETURNING parent_job_id, stage, status
    INTO v_job_id, v_stage, v_task_status;
    
    -- Check if task was actually updated
    IF v_job_id IS NULL THEN
        RETURN QUERY SELECT FALSE, FALSE, NULL::VARCHAR(64), NULL::INTEGER, NULL::INTEGER;
        RETURN;
    END IF;
    
    -- Count remaining non-completed tasks in the same stage
    SELECT COUNT(*)::INTEGER INTO v_remaining
    FROM app.tasks 
    WHERE parent_job_id = v_job_id 
      AND stage = v_stage 
      AND status NOT IN ('completed', 'failed');
    
    -- Return results
    RETURN QUERY SELECT 
        TRUE,                           -- task_updated
        v_remaining = 0,               -- is_last_task_in_stage  
        v_job_id,                      -- job_id
        v_stage,                       -- stage_number
        v_remaining;                   -- remaining_tasks
END;
$$;

-- Function to atomically advance job to next stage
CREATE OR REPLACE FUNCTION advance_job_stage(
    p_job_id VARCHAR(64),
    p_current_stage INTEGER,
    p_stage_results JSONB DEFAULT NULL
)
RETURNS TABLE (
    job_updated BOOLEAN,
    new_stage INTEGER,
    is_final_stage BOOLEAN
)
LANGUAGE plpgsql  
AS $$
DECLARE
    v_total_stages INTEGER;
    v_new_stage INTEGER;
BEGIN
    -- Update job stage and stage results atomically
    UPDATE app.jobs
    SET 
        stage = stage + 1,
        stage_results = CASE 
            WHEN p_stage_results IS NOT NULL THEN
                stage_results || jsonb_build_object(p_current_stage::text, p_stage_results)
            ELSE stage_results
        END,
        status = CASE 
            WHEN stage + 1 > total_stages THEN 'completed'::job_status
            ELSE 'processing'::job_status
        END,
        updated_at = NOW()
    WHERE 
        job_id = p_job_id 
        AND stage = p_current_stage  -- Only update if stage matches
    RETURNING stage, total_stages
    INTO v_new_stage, v_total_stages;
    
    -- Check if job was actually updated
    IF v_new_stage IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::INTEGER, NULL::BOOLEAN;
        RETURN;
    END IF;
    
    -- Return results
    RETURN QUERY SELECT 
        TRUE,                              -- job_updated
        v_new_stage,                      -- new_stage
        v_new_stage > v_total_stages;     -- is_final_stage
END;
$$;

-- Function to check if job is complete and gather results
-- CRITICAL: This function prevents race conditions in "last task turns out lights" pattern
CREATE OR REPLACE FUNCTION check_job_completion(
    p_job_id VARCHAR(64)
)
RETURNS TABLE (
    job_complete BOOLEAN,
    final_stage INTEGER,
    total_tasks BIGINT,
    completed_tasks BIGINT,
    task_results JSONB
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_record RECORD;
    v_task_counts RECORD;
BEGIN
    -- Get job info with row-level lock to prevent race conditions
    -- FOR UPDATE prevents other transactions from checking completion simultaneously
    SELECT job_id, job_type, status, stage, total_stages, stage_results
    INTO v_job_record
    FROM app.jobs 
    WHERE job_id = p_job_id
    FOR UPDATE;
    
    -- If job doesn't exist, return not complete
    IF v_job_record.job_id IS NULL THEN
        RETURN QUERY SELECT 
            FALSE,              -- job_complete
            0::INTEGER,         -- final_stage
            0::BIGINT,          -- total_tasks
            0::BIGINT,          -- completed_tasks  
            '[]'::jsonb;        -- task_results
        RETURN;
    END IF;
    
    -- Count tasks for this job atomically
    SELECT 
        COUNT(*) as total_tasks,
        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_tasks,
        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_tasks,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'task_id', task_id,
                    'task_type', task_type,
                    'stage', stage,
                    'task_index', task_index,
                    'status', status::text,
                    'result_data', result_data,
                    'error_details', error_details
                )
            ) FILTER (WHERE result_data IS NOT NULL OR error_details IS NOT NULL), 
            '[]'::jsonb
        ) as task_results
    INTO v_task_counts
    FROM app.tasks 
    WHERE parent_job_id = p_job_id;
    
    -- Determine completion status
    -- Job is complete when:
    -- 1. There are tasks (total_tasks > 0)
    -- 2. All tasks are either completed or failed (no queued/processing tasks)
    -- 3. Job has reached its final stage
    RETURN QUERY SELECT 
        (
            v_task_counts.total_tasks > 0 AND 
            (v_task_counts.completed_tasks + v_task_counts.failed_tasks) = v_task_counts.total_tasks AND
            v_job_record.stage >= v_job_record.total_stages
        ) as job_complete,
        v_job_record.stage as final_stage,
        v_task_counts.total_tasks,
        v_task_counts.completed_tasks,
        v_task_counts.task_results;
END;
$$;

-- =============================================================================
-- TRIGGERS - Automatic timestamp updates
-- =============================================================================

-- Trigger function for updating updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER 
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- Apply triggers to both tables
CREATE TRIGGER jobs_update_updated_at 
    BEFORE UPDATE ON jobs
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER tasks_update_updated_at
    BEFORE UPDATE ON tasks  
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- GRANTS - Permissions for Azure Functions
-- =============================================================================

-- Note: Actual grants will depend on your Azure PostgreSQL user setup
-- These are examples - adjust based on your authentication method

-- GRANT SELECT, INSERT, UPDATE, DELETE ON jobs TO your_function_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON tasks TO your_function_user;
-- GRANT EXECUTE ON FUNCTION complete_task_and_check_stage TO your_function_user;
-- GRANT EXECUTE ON FUNCTION advance_job_stage TO your_function_user;
-- GRANT EXECUTE ON FUNCTION check_job_completion TO your_function_user;

-- =============================================================================
-- SAMPLE QUERIES - Testing and validation
-- =============================================================================

-- Uncomment for testing:
/*
-- Test job creation
INSERT INTO jobs (job_id, job_type, total_stages, parameters) 
VALUES (
    'test123456789012345678901234567890123456789012345678901234567890ab',
    'hello_world',
    2,
    '{"n": 3, "message": "test"}'::jsonb
);

-- Test task creation  
INSERT INTO tasks (task_id, parent_job_id, task_type, stage, task_index, parameters)
VALUES (
    'test_job_stage1_task1',
    'test123456789012345678901234567890123456789012345678901234567890ab',
    'hello_world_greeting', 
    1,
    0,
    '{"task_number": 1}'::jsonb
);

-- Test completion detection
SELECT * FROM complete_task_and_check_stage('test_job_stage1_task1', '{"greeting": "Hello!"}'::jsonb);

-- Cleanup test data
DELETE FROM jobs WHERE job_id = 'test123456789012345678901234567890123456789012345678901234567890ab';
*/

-- =============================================================================
-- SCHEMA VALIDATION - Ensure consistency with Pydantic models
-- =============================================================================

COMMENT ON TABLE jobs IS 'Job orchestration table - matches JobRecord in schema_core.py';
COMMENT ON TABLE tasks IS 'Task execution table - matches TaskRecord in schema_core.py'; 
COMMENT ON FUNCTION complete_task_and_check_stage IS 'Atomic task completion with race condition prevention';
COMMENT ON FUNCTION advance_job_stage IS 'Atomic job stage advancement';
COMMENT ON FUNCTION check_job_completion IS 'Atomic job completion detection with task result aggregation';

-- Schema creation complete
SELECT 'PostgreSQL schema for Azure Geospatial ETL Pipeline created successfully!' AS status;