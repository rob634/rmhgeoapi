-- PostgreSQL Functions Only - Extracted from schema_postgres.sql
-- This file contains only the function definitions needed for task completion

-- ENUMS - Type-safe status management (must exist before functions)
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
    SELECT COUNT(*) INTO v_remaining
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
    p_stage_result JSONB DEFAULT NULL
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
            WHEN p_stage_result IS NOT NULL THEN
                stage_results || jsonb_build_object(p_current_stage::text, p_stage_result)
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
    SELECT job_id, job_type, status, stage, total_stages, stage_results
    INTO v_job_record
    FROM app.jobs 
    WHERE job_id = p_job_id
    FOR UPDATE;
    
    -- If job doesn't exist, return not complete
    IF v_job_record.job_id IS NULL THEN
        RETURN QUERY SELECT 
            FALSE,              -- job_complete
            0,                  -- final_stage
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

-- Create triggers to use the function (drop first to avoid conflicts)
DROP TRIGGER IF EXISTS jobs_update_updated_at ON jobs;
CREATE TRIGGER jobs_update_updated_at 
    BEFORE UPDATE ON jobs
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS tasks_update_updated_at ON tasks;
CREATE TRIGGER tasks_update_updated_at
    BEFORE UPDATE ON tasks  
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();