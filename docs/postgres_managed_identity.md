# Configuration for managed identity database access (eliminate passwords and key vault)

**Date**: 10 Nov 2025
**Audience**: DevOps for eservice requests in corporate environments

## ETL Identity - Updated Permissions

```sql
-- ETL identity with CREATE privileges
SELECT * FROM pgaadauth_create_principal('rmh-etl-identity', false, false);
GRANT CONNECT ON DATABASE your_database TO "rmh-etl-identity";

-- USAGE + CREATE on all schemas
GRANT USAGE, CREATE ON SCHEMA app TO "rmh-etl-identity";
GRANT USAGE, CREATE ON SCHEMA geo TO "rmh-etl-identity";
GRANT USAGE, CREATE ON SCHEMA pgstac TO "rmh-etl-identity";
GRANT USAGE, CREATE ON SCHEMA h3 TO "rmh-etl-identity";

-- Full DML permissions on existing tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO "rmh-etl-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA geo TO "rmh-etl-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pgstac TO "rmh-etl-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA h3 TO "rmh-etl-identity";

-- For future tables (auto-grant when new tables created)
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmh-etl-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmh-etl-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmh-etl-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmh-etl-identity";
```

## What CREATE Gives You

- **CREATE TABLE** in the schema
- **CREATE INDEX**
- **CREATE VIEW**
- **CREATE FUNCTION** (if needed for PostGIS operations)

This is critical for your ETL pipeline that dynamically creates PostGIS tables in the `geo` schema as data arrives.

TiTiler stays read-only with no CREATE privilege - it can't accidentally create tables. Perfect separation! ✅

-- ============================================================================
-- TiTiler Read-Only Database User Setup
-- Purpose: Enable TiTiler web application to serve map tiles from STAC catalog
-- Security Model: Microsoft Entra Managed Identity with read-only access
-- ============================================================================

-- Create PostgreSQL role for TiTiler's managed identity
-- Note: Role name must exactly match the Azure managed identity name
SELECT * FROM pgaadauth_create_principal('rmhtitiler-identity', false, false);

-- Grant database connection
GRANT CONNECT ON DATABASE <database_name> TO "rmhtitiler-identity";

-- Grant schema usage (required to see tables)
GRANT USAGE ON SCHEMA pgstac TO "rmhtitiler-identity";

-- Grant read-only access to all existing tables in pgstac schema
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "rmhtitiler-identity";

-- Grant read-only access to all future tables in pgstac schema
-- (ensures permissions persist when new tables are added)
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac 
    GRANT SELECT ON TABLES TO "rmhtitiler-identity";

-- Optional: Enable TiTiler's /register endpoint for dynamic mosaics
-- (allows storing STAC search queries - can be omitted for stricter security)
-- GRANT INSERT, UPDATE ON TABLE pgstac.searches TO "rmhtitiler-identity";

-- ============================================================================
-- Verification Query (run after setup to confirm permissions)
-- ============================================================================
SELECT 
    grantee,
    table_schema,
    table_name,
    privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'rmhtitiler-identity'
ORDER BY table_schema, table_name, privilege_type;
```

## Context for eService Request

**Authentication Method:** Microsoft Entra ID (Azure AD) Managed Identity  
**Managed Identity Name:** `rmhtitiler-identity`  
**Identity Type:** User-assigned managed identity  
**Credential Storage:** None required - tokens generated automatically by Azure platform  

**Why this approach:**
- No passwords to store, rotate, or manage
- No Key Vault required for database credentials
- Automatic token refresh by Azure platform
- Audit trail via Azure Entra ID logs
- Follows Azure security best practices for service-to-service authentication

**Connection string format:**
```
postgresql://rmhtitiler-identity@<server-name>:<token>@<server-name>.postgres.database.azure.com:5432/<database_name>?sslmode=require