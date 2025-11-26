# QA Database Setup - Managed Identity Configuration

**Date**: 26 NOV 2025
**Environment**: QA (ddhgeodb)
**Managed Identity**: migeoetldbadminqa

---

## Overview

This document provides instructions for setting up the PostgreSQL user and Azure AD integration for the QA environment managed identity.

---

## Step 1: Create PostgreSQL User (SQL - DBA Action)

Run as a user with CREATEROLE privilege (e.g., `sde` or Azure AD admin):

```sql
-- ============================================================
-- Create PostgreSQL user for Azure Managed Identity
-- Database: ddhgeodb
-- User: migeoetldbadminqa (must match Azure Managed Identity name exactly)
-- ============================================================

-- 1. Create the user (name MUST match managed identity name exactly)
CREATE USER migeoetldbadminqa WITH LOGIN;

-- 2. Grant permission to create schemas in this database
GRANT CREATE ON DATABASE ddhgeodb TO migeoetldbadminqa;

-- 3. Grant CREATEROLE (needed to create pgstac_admin, pgstac_ingest, pgstac_read roles)
ALTER ROLE migeoetldbadminqa CREATEROLE;

-- 4. Grant usage on public schema (for PostGIS functions)
GRANT USAGE ON SCHEMA public TO migeoetldbadminqa;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO migeoetldbadminqa;
```

---

## Step 2: Register Azure AD Principal (Azure CLI - After Step 1)

**IMPORTANT**: Step 1 (CREATE USER) must be completed BEFORE this step.

### Find the Managed Identity Object ID

```bash
az identity show \
  --resource-group <RESOURCE_GROUP> \
  --name migeoetldbadminqa \
  --query principalId -o tsv
```

### Register as Azure AD Admin on PostgreSQL Server

```bash
az postgres flexible-server ad-admin create \
  --resource-group <RESOURCE_GROUP> \
  --server-name <SERVER_NAME> \
  --display-name "migeoetldbadminqa" \
  --object-id <MANAGED_IDENTITY_OBJECT_ID> \
  --type ServicePrincipal
```

---

## Step 3: Verification Queries

Run these queries to verify the setup is correct:

```sql
-- Verify user exists and has correct permissions
SELECT rolname, rolcreaterole, rolcreatedb, rolcanlogin
FROM pg_roles
WHERE rolname = 'migeoetldbadminqa';

-- Expected output:
--     rolname          | rolcreaterole | rolcreatedb | rolcanlogin
-- ---------------------+---------------+-------------+-------------
--  migeoetldbadminqa   | t             | f           | t

-- Verify CREATE ON DATABASE permission
SELECT has_database_privilege('migeoetldbadminqa', 'ddhgeodb', 'CREATE');
-- Expected: t

-- Verify public schema access
SELECT has_schema_privilege('migeoetldbadminqa', 'public', 'USAGE');
-- Expected: t
```

---

## Permissions Summary

| Permission | SQL Command | Purpose |
|------------|-------------|---------|
| Login | `CREATE USER migeoetldbadminqa WITH LOGIN` | Allow connection |
| Create schemas | `GRANT CREATE ON DATABASE ddhgeodb TO migeoetldbadminqa` | Create `app` and `pgstac` schemas |
| Create roles | `ALTER ROLE migeoetldbadminqa CREATEROLE` | Create `pgstac_admin`, `pgstac_ingest`, `pgstac_read` roles |
| PostGIS access | `GRANT USAGE ON SCHEMA public` | Access PostGIS spatial functions |

---

## What This User Will Do

The `migeoetldbadminqa` managed identity will:

1. **Create `app` schema** - CoreMachine job/task tables (via Pydantic → SQL generator)
2. **Create `pgstac` schema** - STAC metadata catalog (via `pypgstac migrate`)
3. **Create pgstac roles** - `pgstac_admin`, `pgstac_ingest`, `pgstac_read`
4. **Execute PostGIS functions** - Spatial queries on `geo` schema data

---

## How Authentication Works

```
Azure Function App (QA)
    │
    │ 1. ManagedIdentityCredential.get_token()
    │    → Gets Azure AD token for "migeoetldbadminqa" identity
    ▼
PostgreSQL Flexible Server
    │
    │ 2. Validates token against Azure AD
    │ 3. Looks up: "Is migeoetldbadminqa registered as AD principal?" → YES
    │ 4. Looks up: "Does PostgreSQL user migeoetldbadminqa exist?" → YES
    │ 5. Grants session as that user with all its GRANTs
    ▼
Connected as migeoetldbadminqa
```

---

## Alternative: Pre-Create Everything (More Restrictive)

If InfoSec won't grant CREATEROLE or CREATE ON DATABASE, have the DBA pre-create everything:

```sql
-- DBA creates schemas and roles BEFORE app deployment
CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS pgstac;

CREATE ROLE pgstac_admin NOLOGIN;
CREATE ROLE pgstac_ingest NOLOGIN;
CREATE ROLE pgstac_read NOLOGIN;

-- Then grant ownership to the app identity
ALTER SCHEMA app OWNER TO migeoetldbadminqa;
ALTER SCHEMA pgstac OWNER TO migeoetldbadminqa;
GRANT pgstac_admin TO migeoetldbadminqa;
GRANT pgstac_ingest TO migeoetldbadminqa;
GRANT pgstac_read TO migeoetldbadminqa;

-- Now the app can manage everything WITHOUT CREATEROLE or CREATE ON DATABASE
```

This approach gives schema ownership without database-level privileges.

---

## Function App Environment Variables

The QA Function App needs these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `MANAGED_IDENTITY_CLIENT_ID` | `<client-id-of-migeoetldbadminqa>` | User-assigned identity client ID |
| `MANAGED_IDENTITY_NAME` | `migeoetldbadminqa` | PostgreSQL user name |
| `POSTGIS_HOST` | `<server>.postgres.database.azure.com` | PostgreSQL server hostname |
| `POSTGIS_DATABASE` | `ddhgeodb` | Database name |
| `POSTGIS_PORT` | `5432` | PostgreSQL port |

**Note**: No password is needed - authentication uses Azure AD tokens.

---

## Troubleshooting

### Error: "User does not exist"
- Step 1 (CREATE USER) was not completed
- User name doesn't match exactly (case-sensitive)

### Error: "Token validation failed"
- Step 2 (Azure AD registration) was not completed
- Object ID is incorrect
- Managed identity is not assigned to the Function App

### Error: "Permission denied for schema"
- Missing `GRANT CREATE ON DATABASE` permission
- Missing schema ownership for pre-created schemas

### Error: "Cannot create role"
- Missing `CREATEROLE` privilege
- Use pre-create alternative if InfoSec won't grant this

---

## Related Documentation

- [WIKI_API_DATABASE.md](WIKI_API_DATABASE.md) - General database setup guide
- [WIKI_SCHEMA_REBUILD_SQL.md](WIKI_SCHEMA_REBUILD_SQL.md) - Manual schema rebuild SQL
- [docs_claude/SCHEMA_ARCHITECTURE.md](docs_claude/SCHEMA_ARCHITECTURE.md) - Schema architecture overview

---

**Last Updated**: 26 NOV 2025
