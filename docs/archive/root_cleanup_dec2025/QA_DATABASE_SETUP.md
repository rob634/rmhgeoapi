# App Database Setup - Managed Identity for Infrastructure-as-Code

**Date**: 30 NOV 2025
**Purpose**: Create PostgreSQL user for Azure User-Assigned Managed Identity with full IaC permissions

---

## Overview

This document covers setup for the **App Database** only - the database containing `app`, `pgstac`, `geo`, and `h3` schemas that can be wiped and rebuilt via Infrastructure-as-Code.

**Managed Identity**: `rmhpgflexadmin` (already exists in Azure)

---

## Step 1: Create PostgreSQL User (SQL)

Connect as database admin and run:

```sql
-- ============================================================
-- Create PostgreSQL user for Azure Managed Identity
-- User: rmhpgflexadmin (must match Azure Managed Identity name exactly)
-- ============================================================

-- 1. Create the user
CREATE USER rmhpgflexadmin WITH LOGIN;

-- 2. Grant CREATE ON DATABASE (required for CREATE/DROP SCHEMA)
GRANT CREATE ON DATABASE <DATABASE_NAME> TO rmhpgflexadmin;

-- 3. Grant CREATEROLE (required for pypgstac to create pgstac_admin/ingest/read roles)
ALTER ROLE rmhpgflexadmin CREATEROLE;

-- 4. Grant PostGIS access
GRANT USAGE ON SCHEMA public TO rmhpgflexadmin;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO rmhpgflexadmin;
```

---

## Step 2: Register Azure AD Principal (Azure CLI)

**IMPORTANT**: Run AFTER Step 1 completes.

```bash
# Get the managed identity's Object ID
az identity show \
  --resource-group <RESOURCE_GROUP> \
  --name rmhpgflexadmin \
  --query principalId -o tsv

# Register as Azure AD admin on PostgreSQL server
az postgres flexible-server ad-admin create \
  --resource-group <RESOURCE_GROUP> \
  --server-name <SERVER_NAME> \
  --display-name "rmhpgflexadmin" \
  --object-id <OBJECT_ID_FROM_ABOVE> \
  --type ServicePrincipal
```

---

## Step 3: Verify Setup

```sql
-- Check user exists with correct permissions
SELECT rolname, rolcreaterole, rolcreatedb, rolcanlogin
FROM pg_roles
WHERE rolname = 'rmhpgflexadmin';

-- Expected: rolcreaterole=t, rolcreatedb=f, rolcanlogin=t

-- Check CREATE ON DATABASE
SELECT has_database_privilege('rmhpgflexadmin', current_database(), 'CREATE');
-- Expected: t
```

---

## Permissions Summary

| Permission | SQL | Purpose |
|------------|-----|---------|
| Login | `CREATE USER rmhpgflexadmin WITH LOGIN` | Allow token-based connection |
| Create/Drop Schemas | `GRANT CREATE ON DATABASE` | IaC: `DROP SCHEMA app CASCADE`, `CREATE SCHEMA app` |
| Create Roles | `ALTER ROLE rmhpgflexadmin CREATEROLE` | pypgstac creates `pgstac_admin`, `pgstac_ingest`, `pgstac_read` |
| PostGIS Functions | `GRANT USAGE ON SCHEMA public` | Spatial operations |

---

## What This Enables

With these permissions, the Function App can:

1. **Full-rebuild endpoint** (`/api/dbadmin/maintenance/full-rebuild?confirm=yes`)
   - `DROP SCHEMA app CASCADE`
   - `DROP SCHEMA pgstac CASCADE`
   - `CREATE SCHEMA app` + deploy tables from Pydantic
   - `pypgstac migrate` to deploy pgstac schema
   - Create pgstac roles

2. **Schema-specific rebuilds**
   - `/api/dbadmin/maintenance/redeploy?confirm=yes` (app schema)
   - `/api/dbadmin/maintenance/pgstac/redeploy?confirm=yes` (pgstac schema)

---

## Function App Environment Variables

```bash
MANAGED_IDENTITY_CLIENT_ID=<client-id-of-rmhpgflexadmin>
MANAGED_IDENTITY_NAME=rmhpgflexadmin
POSTGIS_HOST=<server>.postgres.database.azure.com
POSTGIS_DATABASE=<database_name>
POSTGIS_PORT=5432
USE_MANAGED_IDENTITY=true
```

No password required - authentication uses Azure AD tokens.

---

## Alternate Workflow: SQL Function Approach

Instead of using Azure CLI (Step 2 above), you can use the built-in `pgaadauth_create_principal` function directly in SQL. This is convenient when you're already in a SQL session.

### Prerequisites

Ensure the `azure_ad` extension is enabled (usually enabled by default on Azure PostgreSQL Flexible Server):

```sql
-- Check if extension is available
SELECT * FROM pg_available_extensions WHERE name = 'azure_ad';

-- Enable if needed (requires azure_pg_admin role)
CREATE EXTENSION IF NOT EXISTS azure_ad;
```

### Complete SQL-Only Workflow

```sql
-- ============================================================
-- Create PostgreSQL user for Azure Managed Identity (SQL-Only)
-- User: rmhpgflexadmin (must match Azure Managed Identity name exactly)
-- ============================================================

-- 1. Create user AND register as AAD principal in one step
-- Parameters: (principal_name, is_admin, is_mfa)
SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', false, false);

-- 2. Grant CREATE ON DATABASE (required for CREATE/DROP SCHEMA)
GRANT CREATE ON DATABASE <DATABASE_NAME> TO rmhpgflexadmin;

-- 3. Grant CREATEROLE (required for pypgstac to create pgstac_admin/ingest/read roles)
ALTER ROLE rmhpgflexadmin CREATEROLE;

-- 4. Grant PostGIS access
GRANT USAGE ON SCHEMA public TO rmhpgflexadmin;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO rmhpgflexadmin;
```

### Function Parameters Explained

```sql
pgaadauth_create_principal(
    'rmhpgflexadmin',  -- Principal name (must match Azure Managed Identity name)
    false,              -- is_admin: false = regular user, true = azure_pg_admin member
    false               -- is_mfa: MFA requirement (not applicable for managed identities)
)
```

### When to Use Each Approach

| Approach | Best For |
|----------|----------|
| **Azure CLI** (Step 2) | Automation scripts, Terraform/Bicep, CI/CD pipelines |
| **SQL Function** | Interactive setup, already in psql/DBeaver session |

Both approaches achieve the same result - the managed identity can authenticate via Azure AD token.

---

**Last Updated**: 30 NOV 2025
