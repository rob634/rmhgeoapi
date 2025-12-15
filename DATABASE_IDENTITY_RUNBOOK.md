# Database Identity Runbook: Managed Identity Setup for Azure PostgreSQL

**Date**: 03 DEC 2025
**Status**: Production
**Purpose**: Operational runbook with actual values for setting up managed identity database access
**Audience**: DevOps, Database Administrators

---

## Overview

This runbook contains the actual commands and credentials needed to set up managed identity access for Azure PostgreSQL Flexible Server. It covers two identities:

| Identity | Purpose | Access Level |
|----------|---------|--------------|
| **rmhpgflexadmin** | ETL system, schema management | Full DDL + DML |
| **rmhpgflexreader** | Read-only APIs (OGC, TiTiler) | SELECT only |

**For conceptual overview and generic setup instructions, see**: [WIKI_API_DATABASE.md](WIKI_API_DATABASE.md)

---

## Identity Reference

### Admin Identity: rmhpgflexadmin

| Property | Value |
|----------|-------|
| **Name** | `rmhpgflexadmin` |
| **Client ID** | `a533cb80-a590-4fad-8e52-1eb1f72659d7` |
| **Principal ID (Object ID)** | `ab45e154-ae11-4e99-9e96-76da5fe51656` |
| **Resource Group** | `rmhazure_rg` |
| **Location** | eastus |
| **Tenant ID** | `086aef7e-db12-4161-8a9f-777deb499cfa` |
| **PostgreSQL Admin** | Yes (azure_pg_admin member) |
| **Assigned To** | rmhazuregeoapi (ETL Function App) |

### Reader Identity: rmhpgflexreader

| Property | Value |
|----------|-------|
| **Name** | `rmhpgflexreader` |
| **Client ID** | `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f` |
| **Principal ID (Object ID)** | `789cc11a-d667-4915-b4de-88e76eda1cfb` |
| **Resource Group** | `rmhazure_rg` |
| **Location** | eastus |
| **Tenant ID** | `086aef7e-db12-4161-8a9f-777deb499cfa` |
| **PostgreSQL Admin** | No |
| **Assigned To** | rmhogcapi, TiTiler |

### Permission Comparison

| Permission | rmhpgflexadmin | rmhpgflexreader |
|------------|----------------|-----------------|
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

## PostgreSQL Server Details

| Property | Value |
|----------|-------|
| **Server** | `rmhpgflex.postgres.database.azure.com` |
| **Database** | `geopgflex` |
| **PostgreSQL Version** | 17.6 |
| **Entra ID Auth** | Enabled |
| **Password Auth** | Enabled (hybrid mode) |

---

## Part 1: Create PostgreSQL Roles

### Prerequisites

You must be the Entra ID Administrator for the PostgreSQL server. Verify with:

```bash
az postgres flexible-server show \
    --resource-group rmhazure_rg \
    --name rmhpgflex \
    --query "authConfig" \
    --output json
```

### Step 1.1: Get Azure AD Token

```bash
# Get your current Azure user (must be Entra ID admin)
az account show --query "user.name" --output tsv
# Expected: rmhazure@rob634gmail.onmicrosoft.com

# Get access token for PostgreSQL
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

# Verify token was acquired
echo "Token acquired: ${TOKEN:0:50}..."
```

### Step 1.2: Create Admin Role (rmhpgflexadmin)

**IMPORTANT**: Run on `postgres` database, NOT `geopgflex`!

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "rmhazure@rob634gmail.onmicrosoft.com" \
    -d postgres \
    -c "SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', true, false);"
```

**Parameters**:
- `'rmhpgflexadmin'` - Role name (must match managed identity name)
- `true` - is_admin: Grants azure_pg_admin membership, CREATEROLE, CREATEDB
- `false` - is_mfa: No MFA required for service accounts

**Expected output**:
```
pgaadauth_create_principal
----------------------------------
 Created role for rmhpgflexadmin
(1 row)
```

### Step 1.3: Create Reader Role (rmhpgflexreader)

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "rmhazure@rob634gmail.onmicrosoft.com" \
    -d postgres \
    -c "SELECT * FROM pgaadauth_create_principal('rmhpgflexreader', false, false);"
```

**Parameters**:
- `'rmhpgflexreader'` - Role name
- `false` - is_admin: NOT a PostgreSQL admin
- `false` - is_mfa: No MFA required

### Step 1.4: Verify Role Creation

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "rmhazure@rob634gmail.onmicrosoft.com" \
    -d postgres \
    -c "SELECT rolname, rolcanlogin, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname LIKE 'rmhpgflex%';"
```

**Expected output**:
```
     rolname      | rolcanlogin | rolcreaterole | rolcreatedb
------------------+-------------+---------------+-------------
 rmhpgflexadmin   | t           | t             | t
 rmhpgflexreader  | t           | f             | f
(2 rows)
```

---

## Part 2: Grant Schema Permissions

### Step 2.1: Grant Admin Permissions (rmhpgflexadmin)

Connect to `geopgflex` as schema owner:

```bash
PGPASSWORD='<SCHEMA_OWNER_PASSWORD>' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d geopgflex
```

Run the following SQL:

```sql
-- ============================================================================
-- ADMIN PERMISSIONS: rmhpgflexadmin (Full DDL + DML)
-- ============================================================================

-- Schema: geo (Vector data from ETL)
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA geo TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- Schema: pgstac (STAC metadata catalog)
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA pgstac TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- Schema: h3 (H3 hexagon grids)
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA h3 TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- Schema: app (CoreMachine jobs/tasks)
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- Schema: platform (ETL orchestration)
GRANT ALL PRIVILEGES ON SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA platform TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- Schema: silver (Processed data tier)
GRANT ALL PRIVILEGES ON SCHEMA silver TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA silver TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA silver TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA silver TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;
```

### Step 2.2: Grant Reader Permissions (rmhpgflexreader)

```sql
-- ============================================================================
-- READER PERMISSIONS: rmhpgflexreader (SELECT only)
-- ============================================================================

-- Schema: geo (Vector data)
GRANT USAGE ON SCHEMA geo TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO rmhpgflexreader;

-- Schema: pgstac (STAC metadata)
GRANT USAGE ON SCHEMA pgstac TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexreader;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT EXECUTE ON FUNCTIONS TO rmhpgflexreader;

-- Schema: h3 (H3 hexagon grids)
GRANT USAGE ON SCHEMA h3 TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO rmhpgflexreader;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA h3 TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT ON TABLES TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT EXECUTE ON FUNCTIONS TO rmhpgflexreader;

-- Schema: public (for PostGIS functions)
GRANT USAGE ON SCHEMA public TO rmhpgflexreader;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO rmhpgflexreader;
```

### Step 2.3: Verify Permissions

```sql
-- Check admin permissions
SELECT
    n.nspname as schema,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'USAGE') as has_usage,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'CREATE') as has_create
FROM pg_namespace n
WHERE n.nspname IN ('geo', 'pgstac', 'h3', 'app', 'platform', 'silver', 'public')
ORDER BY n.nspname;

-- Check reader permissions
SELECT
    n.nspname as schema,
    has_schema_privilege('rmhpgflexreader', n.nspname, 'USAGE') as has_usage,
    has_schema_privilege('rmhpgflexreader', n.nspname, 'CREATE') as has_create
FROM pg_namespace n
WHERE n.nspname IN ('geo', 'pgstac', 'h3', 'public')
ORDER BY n.nspname;
```

---

## Part 3: Assign Identities to Function Apps

### Step 3.1: Assign Admin Identity to ETL App

```bash
# Get the full resource ID of the admin identity
IDENTITY_ID=$(az identity show \
    --name rmhpgflexadmin \
    --resource-group rmhazure_rg \
    --query id \
    --output tsv)

echo "Identity ID: $IDENTITY_ID"

# Assign to ETL Function App
az functionapp identity assign \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg \
    --identities "$IDENTITY_ID"
```

### Step 3.2: Assign Reader Identity to API App

```bash
# Get the full resource ID of the reader identity
IDENTITY_ID=$(az identity show \
    --name rmhpgflexreader \
    --resource-group rmhazure_rg \
    --query id \
    --output tsv)

echo "Identity ID: $IDENTITY_ID"

# Assign to OGC API Function App
az functionapp identity assign \
    --name rmhogcapi \
    --resource-group rmhazure_rg \
    --identities "$IDENTITY_ID"
```

### Step 3.3: Configure Application Settings

**For ETL App (rmhazuregeoapi)**:
```bash
az functionapp config appsettings set \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "AZURE_CLIENT_ID=a533cb80-a590-4fad-8e52-1eb1f72659d7" \
        "POSTGIS_USER=rmhpgflexadmin"
```

**For OGC API App (rmhogcapi)**:
```bash
az functionapp config appsettings set \
    --name rmhogcapi \
    --resource-group rmhazure_rg \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "AZURE_CLIENT_ID=1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f" \
        "POSTGIS_USER=rmhpgflexreader"
```

---

## Part 4: Application Code

### Python Token Acquisition

```python
from azure.identity import ManagedIdentityCredential

# For Admin (ETL system)
credential = ManagedIdentityCredential(
    client_id="a533cb80-a590-4fad-8e52-1eb1f72659d7"
)

# For Reader (API services)
credential = ManagedIdentityCredential(
    client_id="1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f"
)

# Get token for PostgreSQL
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")

# Use token as password in connection string
conn_string = f"postgresql://rmhpgflexadmin:{token.token}@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require"
```

### Connection String Format

```
postgresql://<IDENTITY_NAME>:<TOKEN>@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require
```

---

## Troubleshooting

### Error: "function pgaadauth_create_principal does not exist"

**Cause**: Connected to wrong database.

**Solution**: Connect to `postgres` database, NOT `geopgflex`:
```bash
# Wrong
PGPASSWORD="$TOKEN" psql -h ... -d geopgflex

# Correct
PGPASSWORD="$TOKEN" psql -h ... -d postgres
```

### Error: "password authentication failed for user"

**Cause**: Role was created as password-based, not Entra ID role.

**Solution**: Role must be created using `pgaadauth_create_principal()`, not `CREATE ROLE`.

### Error: "permission denied for schema"

**Cause**: GRANT statements not run or not run by schema owner.

**Solution**: Connect as schema owner (rob634) and re-run GRANT statements.

### Error: "Could not validate AAD user"

**Cause**: Managed identity name doesn't match PostgreSQL role name.

**Solution**: Ensure role name exactly matches the managed identity name in Azure.

### Verify pgaadauth Functions Exist

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "rmhazure@rob634gmail.onmicrosoft.com" \
    -d postgres \
    -c "SELECT proname FROM pg_proc WHERE proname LIKE 'pgaadauth%' ORDER BY proname;"
```

---

## Security Notes

1. **No passwords stored**: Authentication uses Azure AD tokens, no secrets in app settings
2. **Token expiration**: Tokens expire after ~1 hour, automatically refreshed by azure-identity SDK
3. **Audit trail**: All access logged through Azure AD and PostgreSQL logs
4. **Least privilege**: Use reader identity for apps that only need SELECT access
5. **Separate concerns**: ETL apps get admin, API apps get reader

---

## Quick Reference

### Connection Strings

**Admin (ETL)**:
```
host=rmhpgflex.postgres.database.azure.com
port=5432
dbname=geopgflex
user=rmhpgflexadmin
sslmode=require
password=<AZURE_AD_TOKEN>
```

**Reader (APIs)**:
```
host=rmhpgflex.postgres.database.azure.com
port=5432
dbname=geopgflex
user=rmhpgflexreader
sslmode=require
password=<AZURE_AD_TOKEN>
```

### Client IDs (for copy/paste)

- **Admin**: `a533cb80-a590-4fad-8e52-1eb1f72659d7`
- **Reader**: `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f`

---

## References

- [Microsoft Learn - Connect With Managed Identity](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-connect-with-managed-identity)
- [Microsoft Learn - Manage Microsoft Entra Users](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-manage-azure-ad-users)
- [Microsoft Learn - Microsoft Entra Authentication Concepts](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-azure-ad-authentication)

---

**Last Updated**: 03 DEC 2025
