-- ============================================================================
-- Grant pgstac Permissions to {db_superuser}
-- ============================================================================
-- Run this ONLY if check_permissions.sql shows {db_superuser} lacks access
-- This requires connecting as a PostgreSQL admin user (not {db_superuser})
-- ============================================================================

\echo '========================================='
\echo 'Granting pgstac Permissions to {db_superuser}'
\echo '========================================='
\echo ''

-- Check current user
\echo 'Current user (must be admin to grant permissions):'
SELECT current_user,
       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser;

\echo ''

-- Option 1: Add {db_superuser} to pgstac_read role (RECOMMENDED)
\echo 'Option 1: Adding {db_superuser} to pgstac_read role...'
GRANT pgstac_read TO {db_superuser};

\echo 'Granted pgstac_read to {db_superuser} ✅'
\echo ''

-- Option 2: Direct permissions (if pgstac_read role doesn't exist)
-- Uncomment these if needed:

-- \echo 'Option 2: Granting direct permissions (fallback)...'
-- GRANT USAGE ON SCHEMA pgstac TO {db_superuser};
-- GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO {db_superuser};
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO {db_superuser};
--
-- -- Make it persist for future objects
-- ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
--   GRANT SELECT ON TABLES TO {db_superuser};
--
-- ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
--   GRANT EXECUTE ON FUNCTIONS TO {db_superuser};
--
-- \echo 'Direct permissions granted ✅'
-- \echo ''

-- Verify the grants worked
\echo 'Verifying permissions...'
\echo '-------------------------------------------'

SELECT
    'Schema USAGE' AS permission_type,
    has_schema_privilege('{db_superuser}', 'pgstac', 'USAGE') AS granted
UNION ALL
SELECT
    'pgstac.collections SELECT',
    has_table_privilege('{db_superuser}', 'pgstac.collections', 'SELECT')
UNION ALL
SELECT
    'pgstac.items SELECT',
    has_table_privilege('{db_superuser}', 'pgstac.items', 'SELECT')
UNION ALL
SELECT
    'pgstac.all_collections() EXECUTE',
    has_function_privilege('{db_superuser}', 'pgstac.all_collections()', 'EXECUTE');

\echo ''
\echo '========================================='
\echo 'Done! Test with {db_superuser} connection.'
\echo '========================================='
\echo ''
\echo 'Test queries to run as {db_superuser}:'
\echo '1. SELECT * FROM pgstac.collections LIMIT 1;'
\echo '2. SELECT * FROM pgstac.all_collections();'
\echo '3. Test TiTiler: curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections'
\echo ''