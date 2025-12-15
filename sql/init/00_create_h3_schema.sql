-- ============================================================================
-- H3 SCHEMA - System-generated H3 grids (Bootstrap Data)
-- ============================================================================
-- PURPOSE: Dedicated schema for H3 hexagonal grids (resolutions 2-7)
-- SEPARATION: h3 schema = system data, geo schema = user data
-- CREATED: 10 NOV 2025
-- CONTEXT: Agricultural Geography Platform - H3 Grid Bootstrap
-- ============================================================================
--
-- This schema contains:
-- - h3.grids: H3 hexagonal grid cells (resolutions 2-7, ~55.8M land cells)
-- - h3.reference_filters: Parent ID sets for child generation (e.g., land_res2)
-- - h3.grid_metadata: Bootstrap progress tracking and status
--
-- WHY SEPARATE SCHEMA?
-- - Clean separation: System H3 data vs user-uploaded geospatial data
-- - Access control: Users get SELECT-only on h3.*, full control on geo.*
-- - Backup strategy: Can backup h3 schema separately (rarely changes)
-- - Namespace clarity: h3.grids vs geo.countries vs geo.user_table
--
-- SECURITY MODEL:
-- - System user (rob634): Full control on h3 schema
-- - Future read-only users: SELECT-only on h3.* (no modifications)
-- - User data remains in geo schema (ingest_vector workflows)
--
-- ============================================================================

-- Create h3 schema if not exists (idempotent - safe to re-run)
CREATE SCHEMA IF NOT EXISTS h3;

-- Grant full permissions to system user
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rob634;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA h3 TO rob634;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA h3 TO rob634;

-- Set default privileges for future tables in h3 schema
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON TABLES TO rob634;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON SEQUENCES TO rob634;

-- Future: Grant SELECT-only to read-only users (uncomment when needed)
-- GRANT USAGE ON SCHEMA h3 TO readonly_user;
-- GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO readonly_user;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT ON TABLES TO readonly_user;

-- Schema comment (describes purpose and ownership)
COMMENT ON SCHEMA h3 IS 'System-generated H3 hexagonal grids (resolutions 2-7) for Agricultural Geography Platform. Bootstrap data - read-only for users. Managed by CoreMachine bootstrap jobs.';

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify schema creation
SELECT
    schema_name,
    schema_owner,
    'Schema created successfully' as status
FROM information_schema.schemata
WHERE schema_name = 'h3';

-- Verify permissions
SELECT
    nspname as schema_name,
    nspowner::regrole as owner,
    has_schema_privilege('rob634', nspname, 'USAGE') as has_usage,
    has_schema_privilege('rob634', nspname, 'CREATE') as has_create
FROM pg_namespace
WHERE nspname = 'h3';

-- Display success message
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'h3') THEN
        RAISE NOTICE '✅ H3 SCHEMA CREATED SUCCESSFULLY';
        RAISE NOTICE '   Schema: h3';
        RAISE NOTICE '   Owner: rob634';
        RAISE NOTICE '   Purpose: System-generated H3 grids (resolutions 2-7)';
        RAISE NOTICE '   Next Step: Create tables (02_create_h3_grids_table.sql)';
    ELSE
        RAISE EXCEPTION '❌ H3 schema creation failed';
    END IF;
END $$;

-- ============================================================================
-- DEPLOYMENT INSTRUCTIONS
-- ============================================================================
--
-- To deploy this schema:
--
-- psql -h rmhpgflex.postgres.database.azure.com -U rob634 -d geopgflex \
--   < sql/init/00_create_h3_schema.sql
--
-- Or using PGPASSWORD:
--
-- PGPASSWORD='B@lamb634@' psql -h rmhpgflex.postgres.database.azure.com \
--   -U rob634 -d geopgflex < sql/init/00_create_h3_schema.sql
--
-- Verify deployment:
--
-- SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'h3';
--
-- Expected output: h3
--
-- ============================================================================