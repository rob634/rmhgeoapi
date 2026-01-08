-- ============================================================================
-- PG_CRON AND AUTOVACUUM SETUP
-- ============================================================================
-- STATUS: SQL - Database maintenance configuration
-- PURPOSE: Enable pg_cron extension and configure autovacuum for large tables
-- CREATED: 08 JAN 2026
-- PREREQUISITES: pg_cron must be enabled in Azure Portal first (see TABLE_MAINTENANCE.md)
-- ============================================================================

-- ============================================================================
-- STEP 1: CREATE PG_CRON EXTENSION
-- ============================================================================
-- NOTE: Run this AFTER enabling pg_cron in Azure Portal server parameters
-- and restarting the server.

CREATE EXTENSION IF NOT EXISTS pg_cron;

-- Verify installation
SELECT extname, extversion FROM pg_extension WHERE extname = 'pg_cron';


-- ============================================================================
-- STEP 2: SCHEDULED VACUUM JOBS
-- ============================================================================

-- Nightly vacuum for H3 cells (2:00 AM UTC)
-- This is the primary large table that caused the timeout issue
SELECT cron.schedule(
    'vacuum-h3-cells-nightly',
    '0 2 * * *',
    'VACUUM ANALYZE h3.cells'
);

-- Nightly vacuum for H3 zonal stats (2:30 AM UTC)
SELECT cron.schedule(
    'vacuum-h3-zonal-stats-nightly',
    '30 2 * * *',
    'VACUUM ANALYZE h3.zonal_stats'
);

-- Nightly vacuum for geo tables (3:00 AM UTC)
-- Add table names as they are created
SELECT cron.schedule(
    'vacuum-geo-tables-nightly',
    '0 3 * * *',
    $$
    DO $$
    DECLARE
        tbl RECORD;
    BEGIN
        FOR tbl IN
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = 'geo'
            AND table_type = 'BASE TABLE'
            AND table_name != 'table_metadata'
        LOOP
            EXECUTE format('VACUUM ANALYZE %I.%I', tbl.table_schema, tbl.table_name);
        END LOOP;
    END $$;
    $$
);

-- Nightly vacuum for STAC items (4:00 AM UTC)
SELECT cron.schedule(
    'vacuum-pgstac-nightly',
    '0 4 * * *',
    'VACUUM ANALYZE pgstac.items; VACUUM ANALYZE pgstac.collections'
);

-- Nightly vacuum for app schema (4:30 AM UTC)
SELECT cron.schedule(
    'vacuum-app-schema-nightly',
    '30 4 * * *',
    'VACUUM ANALYZE app.jobs; VACUUM ANALYZE app.tasks'
);

-- Verify scheduled jobs
SELECT jobid, jobname, schedule, command, database, username, active
FROM cron.job
ORDER BY jobname;


-- ============================================================================
-- STEP 3: AUTOVACUUM TUNING FOR LARGE TABLES
-- ============================================================================
-- These settings make autovacuum more aggressive for bulk-loaded tables.
-- They trigger vacuum at lower dead tuple thresholds and run faster.

-- H3 cells table (100M+ rows expected)
ALTER TABLE h3.cells SET (
    autovacuum_vacuum_scale_factor = 0.01,      -- 1% dead tuples (default: 20%)
    autovacuum_vacuum_threshold = 10000,         -- minimum 10K dead tuples
    autovacuum_analyze_scale_factor = 0.005,     -- analyze at 0.5%
    autovacuum_analyze_threshold = 5000,         -- minimum 5K for analyze
    autovacuum_vacuum_cost_delay = 0,            -- no delay between batches
    autovacuum_vacuum_cost_limit = 1000          -- aggressive (default: 200)
);

-- H3 zonal stats (will be large with raster aggregations)
ALTER TABLE h3.zonal_stats SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_vacuum_threshold = 5000,
    autovacuum_analyze_scale_factor = 0.01,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);

-- STAC items (moderate write activity)
ALTER TABLE pgstac.items SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_analyze_scale_factor = 0.02,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 400
);

-- App jobs table (frequent writes)
ALTER TABLE app.jobs SET (
    autovacuum_vacuum_scale_factor = 0.1,
    autovacuum_vacuum_threshold = 500,
    autovacuum_vacuum_cost_delay = 2,
    autovacuum_vacuum_cost_limit = 300
);

-- App tasks table (very frequent writes)
ALTER TABLE app.tasks SET (
    autovacuum_vacuum_scale_factor = 0.05,
    autovacuum_vacuum_threshold = 1000,
    autovacuum_vacuum_cost_delay = 0,
    autovacuum_vacuum_cost_limit = 500
);


-- ============================================================================
-- STEP 4: MONITORING QUERIES
-- ============================================================================

-- View scheduled cron jobs
-- SELECT * FROM cron.job;

-- View recent job runs (last 24 hours)
-- SELECT jobid, runid, job_pid, command, status, return_message,
--        start_time, end_time, end_time - start_time as duration
-- FROM cron.job_run_details
-- WHERE start_time > NOW() - INTERVAL '24 hours'
-- ORDER BY start_time DESC;

-- View autovacuum status for our tables
-- SELECT schemaname, relname, last_vacuum, last_autovacuum,
--        last_analyze, last_autoanalyze, n_dead_tup, n_live_tup,
--        ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) as dead_pct
-- FROM pg_stat_user_tables
-- WHERE schemaname IN ('h3', 'geo', 'pgstac', 'app')
-- ORDER BY n_dead_tup DESC;

-- View current autovacuum settings for a table
-- SELECT relname, reloptions
-- FROM pg_class
-- WHERE relname = 'cells' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'h3');


-- ============================================================================
-- ROLLBACK (if needed)
-- ============================================================================

-- To disable all scheduled jobs:
-- SELECT cron.unschedule(jobid) FROM cron.job;

-- To remove pg_cron extension:
-- DROP EXTENSION pg_cron;

-- To reset autovacuum to defaults:
-- ALTER TABLE h3.cells RESET (
--     autovacuum_vacuum_scale_factor,
--     autovacuum_vacuum_threshold,
--     autovacuum_analyze_scale_factor,
--     autovacuum_analyze_threshold,
--     autovacuum_vacuum_cost_delay,
--     autovacuum_vacuum_cost_limit
-- );
