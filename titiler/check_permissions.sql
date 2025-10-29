-- ============================================================================
-- PostgreSQL Permission Checker for rob634 and pgstac Schema
-- ============================================================================
-- Run this in DBeaver when connected as rob634 from your home network
-- This will show what permissions rob634 actually has
-- ============================================================================

\echo '========================================='
\echo 'PostgreSQL Permission Analysis for rob634'
\echo '========================================='
\echo ''

-- 1. Current Connection Info
\echo '1. Current Connection Info:'
\echo '-------------------------------------------'
SELECT
    current_user AS connected_as,
    current_database() AS database,
    inet_server_addr() AS server_ip,
    inet_server_port() AS server_port,
    version() AS postgres_version;

\echo ''

-- 2. Check if pgstac schema exists
\echo '2. Does pgstac schema exist?'
\echo '-------------------------------------------'
SELECT
    schema_name,
    schema_owner
FROM information_schema.schemata
WHERE schema_name = 'pgstac';

\echo ''

-- 3. Check USAGE privilege on pgstac schema
\echo '3. Does rob634 have USAGE on pgstac schema?'
\echo '-------------------------------------------'
SELECT
    has_schema_privilege('rob634', 'pgstac', 'USAGE') AS has_usage_privilege,
    has_schema_privilege('rob634', 'pgstac', 'CREATE') AS has_create_privilege;

\echo ''

-- 4. List all schemas rob634 can access
\echo '4. All schemas rob634 can access:'
\echo '-------------------------------------------'
SELECT
    schema_name,
    has_schema_privilege('rob634', schema_name, 'USAGE') AS can_use,
    has_schema_privilege('rob634', schema_name, 'CREATE') AS can_create
FROM information_schema.schemata
ORDER BY schema_name;

\echo ''

-- 5. Check rob634's roles and memberships
\echo '5. Roles and group memberships for rob634:'
\echo '-------------------------------------------'
SELECT
    r.rolname AS role_name,
    r.rolsuper AS is_superuser,
    r.rolcreaterole AS can_create_roles,
    r.rolcreatedb AS can_create_db,
    ARRAY_AGG(m.rolname) AS member_of_roles
FROM pg_roles r
LEFT JOIN pg_auth_members am ON r.oid = am.member
LEFT JOIN pg_roles m ON am.roleid = m.oid
WHERE r.rolname = 'rob634'
GROUP BY r.rolname, r.rolsuper, r.rolcreaterole, r.rolcreatedb;

\echo ''

-- 6. Check if rob634 is member of pgstac_read role
\echo '6. Is rob634 member of pgstac_read role?'
\echo '-------------------------------------------'
SELECT
    pg_has_role('rob634', 'pgstac_read', 'MEMBER') AS is_member_of_pgstac_read,
    pg_has_role('rob634', 'pgstac_ingest', 'MEMBER') AS is_member_of_pgstac_ingest,
    pg_has_role('rob634', 'pgstac_admin', 'MEMBER') AS is_member_of_pgstac_admin;

\echo ''

-- 7. List all tables in pgstac schema rob634 can see
\echo '7. Tables in pgstac schema (visibility check):'
\echo '-------------------------------------------'
SELECT
    schemaname,
    tablename,
    has_table_privilege('rob634', schemaname || '.' || tablename, 'SELECT') AS can_select,
    has_table_privilege('rob634', schemaname || '.' || tablename, 'INSERT') AS can_insert,
    has_table_privilege('rob634', schemaname || '.' || tablename, 'UPDATE') AS can_update,
    has_table_privilege('rob634', schemaname || '.' || tablename, 'DELETE') AS can_delete
FROM pg_tables
WHERE schemaname = 'pgstac'
ORDER BY tablename
LIMIT 10;

\echo ''

-- 8. Check specific critical pgstac tables
\echo '8. Permissions on critical pgstac tables:'
\echo '-------------------------------------------'
SELECT
    'pgstac.collections' AS table_name,
    has_table_privilege('rob634', 'pgstac.collections', 'SELECT') AS can_select
UNION ALL
SELECT
    'pgstac.items',
    has_table_privilege('rob634', 'pgstac.items', 'SELECT')
UNION ALL
SELECT
    'pgstac.collection_search',
    has_table_privilege('rob634', 'pgstac.collection_search', 'SELECT');

\echo ''

-- 9. Check permissions on pgstac functions
\echo '9. Can rob634 execute pgstac functions?'
\echo '-------------------------------------------'
SELECT
    routine_schema,
    routine_name,
    routine_type,
    has_function_privilege('rob634', routine_schema || '.' || routine_name || '()', 'EXECUTE') AS can_execute
FROM information_schema.routines
WHERE routine_schema = 'pgstac'
ORDER BY routine_name
LIMIT 10;

\echo ''

-- 10. Check search_path
\echo '10. Current search_path:'
\echo '-------------------------------------------'
SHOW search_path;

\echo ''

-- 11. Try to query pgstac.collections directly
\echo '11. Test query pgstac.collections (should work if permissions are correct):'
\echo '-------------------------------------------'
SELECT
    id,
    CASE
        WHEN content IS NOT NULL THEN 'Has content'
        ELSE 'No content'
    END AS content_status
FROM pgstac.collections
LIMIT 5;

\echo ''

-- 12. Try to call pgstac.all_collections() function
\echo '12. Test calling pgstac.all_collections() function (what TiTiler calls):'
\echo '-------------------------------------------'
SELECT * FROM pgstac.all_collections() LIMIT 5;

\echo ''
\echo '========================================='
\echo 'Analysis Complete!'
\echo '========================================='
\echo ''
\echo 'INTERPRETATION:'
\echo '- If Section 3 shows "has_usage_privilege = true": rob634 can access pgstac schema'
\echo '- If Section 6 shows "is_member_of_pgstac_read = true": rob634 has read permissions'
\echo '- If Section 11 works: rob634 can query tables directly'
\echo '- If Section 12 works: TiTiler should work (this is exactly what it calls)'
\echo ''
\echo 'If Section 12 fails but you see data in DBeaver:'
\echo '  → DBeaver might be using a different connection/user'
\echo '  → Check DBeaver connection properties'
\echo ''