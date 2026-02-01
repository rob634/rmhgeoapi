# Database Identity Runbook: Managed Identity Setup for Azure PostgreSQL

**Date**: 05 JAN 2026
**Status**: Production
**Purpose**: Operational runbook for setting up managed identity database access with minimal permissions
**Audience**: DevOps, Database Administrators

---

## Overview

This runbook provides the minimal permissions needed for managed identity access to Azure PostgreSQL Flexible Server.

**Key Principle**: Managed identities do NOT require `azure_pg_admin`. They only need:
- `CREATE ON DATABASE` - to create schemas
- `WITH ADMIN OPTION` on pgstac roles - for pypgstac migrate
- Schema ownership (automatic when identity creates the schema)

### Four Managed Identities

| Identity | Environment | Purpose | Access Level |
|----------|-------------|---------|--------------|
| **Internal DB Admin** | DEV/Sandbox | ETL system, schema management | Full DDL + DML |
| **Internal DB Reader** | DEV/Sandbox | Read-only APIs (OGC, STAC) | SELECT only |
| **External DB Admin** | QA/PROD | ETL system, schema management | Full DDL + DML |
| **External DB Reader** | QA/PROD | Read-only APIs (OGC, STAC) | SELECT only |

**Internal** = Personal Azure tenant (sandbox development)
**External** = Corporate Azure tenant (QA/PROD deployment)

### Permission Comparison

| Permission | DB Admin | DB Reader |
|------------|----------|-----------|
| SELECT | ✅ | ✅ |
| INSERT | ✅ | ❌ |
| UPDATE | ✅ | ❌ |
| DELETE | ✅ | ❌ |
| CREATE TABLE | ✅ | ❌ |
| DROP TABLE | ✅ | ❌ |
| CREATE SCHEMA | ✅ | ❌ |
| DROP SCHEMA | ✅ | ❌ |
| EXECUTE functions | ✅ | ✅ |

---

## Part 1: DBA Prerequisites (One-Time Setup)

These commands require `azure_pg_admin` and are run ONCE by the DBA before application deployment.

### Step 1.1: Create Extensions

**Must be run by azure_pg_admin** - the managed identity cannot create extensions.

```sql
-- ============================================================================
-- EXTENSIONS (requires azure_pg_admin)
-- Run on: geoapp database
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Verify
SELECT extname, extversion FROM pg_extension
WHERE extname IN ('postgis', 'btree_gist', 'unaccent');
```

### Step 1.2: Create pgSTAC Roles

The pypgstac library expects these roles to exist. They must be created by DBA.

```sql
-- ============================================================================
-- PGSTAC ROLES (run once by DBA)
-- These roles are used by pypgstac library
-- ============================================================================

DO $$ BEGIN CREATE ROLE pgstac_admin; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE pgstac_ingest; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE pgstac_read; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Verify
SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac%';
```

---

## Part 2: Create Managed Identity Users

### Step 2.1: Create Admin Identity

**IMPORTANT**: Use `is_admin=false` - we do NOT want azure_pg_admin membership.

```sql
-- ============================================================================
-- CREATE ADMIN IDENTITY (NOT as azure_pg_admin!)
-- Run on: postgres database (pgaadauth functions are in postgres DB)
-- ============================================================================

-- Parameters: (principal_name, is_admin, is_mfa)
-- is_admin=false: Does NOT grant azure_pg_admin (correct!)
-- is_mfa=false: No MFA for service accounts
SELECT * FROM pgaadauth_create_principal('<admin_identity_name>', false, false);
```

### Step 2.2: Create Reader Identity

```sql
-- ============================================================================
-- CREATE READER IDENTITY
-- Run on: postgres database
-- ============================================================================

SELECT * FROM pgaadauth_create_principal('<reader_identity_name>', false, false);
```

### Step 2.3: Verify Users Created

```sql
-- Verify both users exist (run on postgres database)
SELECT rolname, rolcanlogin, rolcreaterole, rolcreatedb
FROM pg_roles
WHERE rolname IN ('<admin_identity_name>', '<reader_identity_name>');

-- Expected output:
--      rolname           | rolcanlogin | rolcreaterole | rolcreatedb
-- -----------------------+-------------+---------------+-------------
--  <admin_identity_name> | t           | f             | f
--  <reader_identity_name>| t           | f             | f
```

---

## Part 3: Grant Admin Identity Permissions

### Step 3.1: Database-Level Permissions

```sql
-- ============================================================================
-- ADMIN: DATABASE PERMISSIONS
-- Run on: geoapp database
-- ============================================================================

-- Allow creating schemas (this is how the app creates app/geo/pgstac schemas)
GRANT CREATE ON DATABASE geoapp TO "<admin_identity_name>";

-- Verify
SELECT has_database_privilege('<admin_identity_name>', 'geoapp', 'CREATE') as can_create;
-- Expected: true
```

### Step 3.2: pgSTAC Role Grants (CRITICAL)

**This is the key permission for pypgstac migrate.** The `WITH ADMIN OPTION` is required because pypgstac runs `GRANT pgstac_admin TO current_user` even if already granted.

```sql
-- ============================================================================
-- ADMIN: PGSTAC ROLE GRANTS WITH ADMIN OPTION
-- CRITICAL: pypgstac migrate will fail without ADMIN OPTION
-- ============================================================================

GRANT pgstac_admin TO "<admin_identity_name>" WITH ADMIN OPTION;
GRANT pgstac_ingest TO "<admin_identity_name>" WITH ADMIN OPTION;
GRANT pgstac_read TO "<admin_identity_name>" WITH ADMIN OPTION;

-- Verify (all should show has_admin_option = true)
SELECT r.rolname AS role_name,
       m.rolname AS granted_to,
       am.admin_option AS has_admin_option
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read')
AND m.rolname = '<admin_identity_name>'
ORDER BY r.rolname;

-- Expected: 3 rows, all with has_admin_option = true
```

### Step 3.3: PostGIS Function Access

```sql
-- ============================================================================
-- ADMIN: POSTGIS ACCESS
-- Required for spatial operations
-- ============================================================================

GRANT USAGE ON SCHEMA public TO "<admin_identity_name>";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "<admin_identity_name>";
```

---

## Part 4: Grant Reader Identity Permissions

The reader identity only needs SELECT access. These grants use `DEFAULT PRIVILEGES` to ensure future tables are accessible.

### Step 4.1: Schema Access

```sql
-- ============================================================================
-- READER: SCHEMA ACCESS
-- Run AFTER admin identity has created the schemas
-- ============================================================================

-- geo schema (vector data)
GRANT USAGE ON SCHEMA geo TO "<reader_identity_name>";
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "<reader_identity_name>";

-- pgstac schema (STAC metadata)
GRANT USAGE ON SCHEMA pgstac TO "<reader_identity_name>";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "<reader_identity_name>";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO "<reader_identity_name>";

-- public schema (PostGIS functions)
GRANT USAGE ON SCHEMA public TO "<reader_identity_name>";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "<reader_identity_name>";

-- pgstac_read role (for STAC search functions)
GRANT pgstac_read TO "<reader_identity_name>";
```

### Step 4.2: Default Privileges for Future Tables

**Run as the ADMIN identity** to ensure tables it creates are accessible to reader:

```sql
-- ============================================================================
-- DEFAULT PRIVILEGES FOR FUTURE TABLES
-- Run as: <admin_identity_name> (or have DBA run FOR ROLE)
-- ============================================================================

ALTER DEFAULT PRIVILEGES FOR ROLE "<admin_identity_name>" IN SCHEMA geo
    GRANT SELECT ON TABLES TO "<reader_identity_name>";

ALTER DEFAULT PRIVILEGES FOR ROLE "<admin_identity_name>" IN SCHEMA pgstac
    GRANT SELECT ON TABLES TO "<reader_identity_name>";
```

---

## Part 5: Verification Queries

### Step 5.1: Admin Permissions Check

```sql
-- ============================================================================
-- VERIFY ADMIN PERMISSIONS
-- ============================================================================

-- Database CREATE permission
SELECT has_database_privilege('<admin_identity_name>', 'geoapp', 'CREATE') as can_create_schema;

-- pgstac roles with ADMIN OPTION
SELECT r.rolname AS role_name,
       am.admin_option AS has_admin_option
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname LIKE 'pgstac%'
AND m.rolname = '<admin_identity_name>';

-- Expected: can_create_schema=true, 3 rows with has_admin_option=true
```

### Step 5.2: Reader Permissions Check

```sql
-- ============================================================================
-- VERIFY READER PERMISSIONS
-- ============================================================================

SELECT
    n.nspname as schema,
    has_schema_privilege('<reader_identity_name>', n.nspname, 'USAGE') as has_usage
FROM pg_namespace n
WHERE n.nspname IN ('geo', 'pgstac', 'public')
ORDER BY n.nspname;

-- Expected: all has_usage = true
```

---

## Part 6: Application Configuration

### Function App Environment Variables

**ETL Function App (uses Admin Identity)**:
```
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_NAME=<admin_identity_name>
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<admin_client_id>
POSTGIS_HOST=<server>.postgres.database.azure.com
POSTGIS_DATABASE=geoapp
```

**API Function App (uses Reader Identity)**:
```
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_NAME=<reader_identity_name>
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<reader_client_id>
POSTGIS_HOST=<server>.postgres.database.azure.com
POSTGIS_DATABASE=geoapp
```

---

## Troubleshooting

### Error: "permission denied to grant role pgstac_admin"

**Cause**: Missing `WITH ADMIN OPTION` on pgstac roles.

**Solution**:
```sql
GRANT pgstac_admin TO "<admin_identity_name>" WITH ADMIN OPTION;
GRANT pgstac_ingest TO "<admin_identity_name>" WITH ADMIN OPTION;
GRANT pgstac_read TO "<admin_identity_name>" WITH ADMIN OPTION;
```

### Error: "permission denied to create schema"

**Cause**: Missing `CREATE ON DATABASE` permission.

**Solution**:
```sql
GRANT CREATE ON DATABASE geoapp TO "<admin_identity_name>";
```

### Error: "type geometry does not exist"

**Cause**: PostGIS extension not created.

**Solution**: Have `azure_pg_admin` run:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

### Error: "Could not validate AAD user"

**Cause**: Managed identity name doesn't match PostgreSQL role name.

**Solution**: Ensure role name exactly matches the managed identity name in Azure.

---

## Quick Reference: Complete DBA Script

```sql
-- ============================================================================
-- COMPLETE DBA SETUP SCRIPT
-- Run as: azure_pg_admin
-- Database: geoapp
-- Replace: <admin_identity>, <reader_identity>
-- ============================================================================

-- 1. Extensions (requires azure_pg_admin)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- 2. Create pgstac roles
DO $$ BEGIN CREATE ROLE pgstac_admin; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE pgstac_ingest; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE pgstac_read; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 3. Create AAD principals (run on postgres database!)
-- \c postgres
-- SELECT * FROM pgaadauth_create_principal('<admin_identity>', false, false);
-- SELECT * FROM pgaadauth_create_principal('<reader_identity>', false, false);
-- \c geoapp

-- 4. Admin permissions
GRANT CREATE ON DATABASE geoapp TO "<admin_identity>";
GRANT pgstac_admin TO "<admin_identity>" WITH ADMIN OPTION;
GRANT pgstac_ingest TO "<admin_identity>" WITH ADMIN OPTION;
GRANT pgstac_read TO "<admin_identity>" WITH ADMIN OPTION;
GRANT USAGE ON SCHEMA public TO "<admin_identity>";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "<admin_identity>";

-- 5. Reader permissions (run AFTER schemas exist)
GRANT USAGE ON SCHEMA public TO "<reader_identity>";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "<reader_identity>";
-- Additional reader grants after app creates schemas (see Part 4)
```

---

## References

- [Microsoft Learn - Connect With Managed Identity](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-connect-with-managed-identity)
- [Microsoft Learn - Manage Microsoft Entra Users](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-manage-azure-ad-users)
- [pypgstac Documentation](https://stac-utils.github.io/pgstac/)

---

**Last Updated**: 05 JAN 2026
