-- ============================================================================
-- Grant pgstac Permissions to rob634
-- ============================================================================
-- Run this ONLY if check_permissions.sql shows rob634 lacks access
-- This requires connecting as a PostgreSQL admin user (not rob634)
-- ============================================================================

\echo '========================================='
\echo 'Granting pgstac Permissions to rob634'
\echo '========================================='
\echo ''

-- Check current user
\echo 'Current user (must be admin to grant permissions):'
SELECT current_user,
       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser;

\echo ''

-- Option 1: Add rob634 to pgstac_read role (RECOMMENDED)
\echo 'Option 1: Adding rob634 to pgstac_read role...'
GRANT pgstac_read TO rob634;

\echo 'Granted pgstac_read to rob634 ✅'
\echo ''

-- Option 2: Direct permissions (if pgstac_read role doesn't exist)
-- Uncomment these if needed:

-- \echo 'Option 2: Granting direct permissions (fallback)...'
-- GRANT USAGE ON SCHEMA pgstac TO rob634;
-- GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO rob634;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO rob634;
--
-- -- Make it persist for future objects
-- ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
--   GRANT SELECT ON TABLES TO rob634;
--
-- ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
--   GRANT EXECUTE ON FUNCTIONS TO rob634;
--
-- \echo 'Direct permissions granted ✅'
-- \echo ''

-- Verify the grants worked
\echo 'Verifying permissions...'
\echo '-------------------------------------------'

SELECT
    'Schema USAGE' AS permission_type,
    has_schema_privilege('rob634', 'pgstac', 'USAGE') AS granted
UNION ALL
SELECT
    'pgstac.collections SELECT',
    has_table_privilege('rob634', 'pgstac.collections', 'SELECT')
UNION ALL
SELECT
    'pgstac.items SELECT',
    has_table_privilege('rob634', 'pgstac.items', 'SELECT')
UNION ALL
SELECT
    'pgstac.all_collections() EXECUTE',
    has_function_privilege('rob634', 'pgstac.all_collections()', 'EXECUTE');

\echo ''
\echo '========================================='
\echo 'Done! Test with rob634 connection.'
\echo '========================================='
\echo ''
\echo 'Test queries to run as rob634:'
\echo '1. SELECT * FROM pgstac.collections LIMIT 1;'
\echo '2. SELECT * FROM pgstac.all_collections();'
\echo '3. Test TiTiler: curl https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/collections'
\echo ''