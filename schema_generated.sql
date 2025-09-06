-- =============================================================================
-- GENERATED PostgreSQL Schema from Pydantic Models
-- Generated at: 2025-09-05T23:10:16.016278
-- =============================================================================
-- 
-- This schema is automatically generated from Pydantic models
-- The Python models are the single source of truth
-- 
-- =============================================================================

-- Create schema if not exists
CREATE SCHEMA IF NOT EXISTS app;

-- Set search path
SET search_path TO app, public;

-- JobStatus enum from schema_core
DO $$ 
BEGIN
    CREATE TYPE app.job_status AS ENUM ('queued', 'processing', 'completed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
-- TaskStatus enum from schema_core
DO $$ 
BEGIN
    CREATE TYPE app.task_status AS ENUM ('queued', 'processing', 'completed', 'failed');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- JobRecord table from schema_core
CREATE TABLE IF NOT EXISTS app.jobs (
    job_id VARCHAR NOT NULL
        CHECK (length(job_id) = 64 AND job_id ~ '^[a-f0-9]+$'),
    job_type VARCHAR NOT NULL,
    status app.job_status NOT NULL DEFAULT 'queued'::app.job_status,
    stage INTEGER NOT NULL DEFAULT 1
        CHECK (stage >= 1 AND stage <= 100),
    total_stages INTEGER NOT NULL DEFAULT 1
        CHECK (total_stages >= 1 AND total_stages <= 100),
    parameters JSONB NOT NULL DEFAULT '{}',
    stage_results JSONB NOT NULL DEFAULT '{}',
    result_data JSONB NULL,
    error_details VARCHAR NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id)
);

-- TaskRecord table from schema_core
CREATE TABLE IF NOT EXISTS app.tasks (
    task_id VARCHAR NOT NULL,
    parent_job_id VARCHAR NOT NULL
        CHECK (length(parent_job_id) = 64 AND parent_job_id ~ '^[a-f0-9]+$'),
    task_type VARCHAR NOT NULL,
    status app.task_status NOT NULL DEFAULT 'queued'::app.task_status,
    stage INTEGER NOT NULL
        CHECK (stage >= 1 AND stage <= 100),
    task_index INTEGER NOT NULL
        CHECK (task_index >= 0 AND task_index <= 10000),
    parameters JSONB NOT NULL DEFAULT '{}',
    result_data JSONB NULL,
    error_details VARCHAR NULL,
    retry_count INTEGER NOT NULL DEFAULT 0
        CHECK (retry_count >= 0 AND retry_count <= 10),
    heartbeat TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (task_id),
    FOREIGN KEY (parent_job_id) REFERENCES app.jobs(job_id) ON DELETE CASCADE
);

-- =============================================================================
-- PERFORMANCE INDEXES
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_jobs_status ON app.jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_job_type ON app.jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON app.jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON app.jobs(updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_parent_job_id ON app.tasks(parent_job_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON app.tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_job_stage ON app.tasks(parent_job_id, stage);
CREATE INDEX IF NOT EXISTS idx_tasks_job_stage_status ON app.tasks(parent_job_id, stage, status);
CREATE INDEX IF NOT EXISTS idx_tasks_heartbeat ON app.tasks(heartbeat) WHERE heartbeat IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_retry_count ON app.tasks(retry_count) WHERE retry_count > 0;

-- =============================================================================
-- ATOMIC FUNCTIONS - Critical for workflow orchestration
-- Phase 1: Using static function templates
-- =============================================================================
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
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER 
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- =============================================================================
-- TRIGGERS
-- =============================================================================

-- Update trigger for jobs
DROP TRIGGER IF EXISTS jobs_update_updated_at ON app.jobs;
CREATE TRIGGER jobs_update_updated_at 
    BEFORE UPDATE ON app.jobs
    FOR EACH ROW 
    EXECUTE FUNCTION app.update_updated_at_column();

-- Update trigger for tasks
DROP TRIGGER IF EXISTS tasks_update_updated_at ON app.tasks;
CREATE TRIGGER tasks_update_updated_at 
    BEFORE UPDATE ON app.tasks
    FOR EACH ROW 
    EXECUTE FUNCTION app.update_updated_at_column();

-- =============================================================================
-- Schema generation complete
-- =============================================================================
SELECT 'PostgreSQL schema generated from Pydantic models' AS status;
