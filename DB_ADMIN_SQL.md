# Database Admin Setup: rmhpgflexadmin

This document records all steps and SQL commands for setting up the `rmhpgflexadmin` user-assigned managed identity as an admin database role for Azure PostgreSQL Flexible Server.

Status: Production

---

## Overview

The `rmhpgflexadmin` is a user-assigned managed identity (UMI) designed to provide **admin-level** database access for applications that need to create, modify, and manage database objects. This identity is intended for:

- **rmhgeoapi ETL System** - Data ingestion and processing pipelines
- **Database Migration Tools** - Schema deployments and updates
- **Admin Scripts** - Maintenance and management operations

**WARNING**: This identity has elevated privileges. Only assign to trusted applications that require write access.

---

## Prerequisites

### 1. User-Assigned Managed Identity Details

| Property | Value |
|----------|-------|
| **Name** | `rmhpgflexadmin` |
| **Client ID** | `a533cb80-a590-4fad-8e52-1eb1f72659d7` |
| **Principal ID (Object ID)** | `ab45e154-ae11-4e99-9e96-76da5fe51656` |
| **Resource Group** | `rmhazure_rg` |
| **Location** | eastus |
| **Tenant ID** | `086aef7e-db12-4161-8a9f-777deb499cfa` |

### 2. PostgreSQL Server Configuration

| Property | Value |
|----------|-------|
| **Server** | `rmhpgflex.postgres.database.azure.com` |
| **Database** | `geopgflex` |
| **PostgreSQL Version** | 17.6 |
| **Entra ID Auth** | Enabled |
| **Password Auth** | Enabled (hybrid mode) |

### 3. Entra ID Administrator

You must have an Entra ID administrator configured on the PostgreSQL server. Check with:

```bash
az postgres flexible-server show \
    --resource-group rmhazure_rg \
    --name rmhpgflex \
    --query "authConfig" \
    --output json
```

Expected output:
```json
{
  "activeDirectoryAuth": "Enabled",
  "passwordAuth": "Enabled",
  "tenantId": "086aef7e-db12-4161-8a9f-777deb499cfa"
}
```

---

## Step 1: Get Azure AD Token and Connect as Entra ID Admin

Important: The `pgaadauth_create_principal` function **MUST** be run on the `postgres` database, NOT on user databases like `geopgflex`. This is the most common mistake.

Reference: [Microsoft Learn - Manage Microsoft Entra Users](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-manage-azure-ad-users)

```bash
# Get your current Azure user (must be Entra ID admin on the PostgreSQL server)
az account show --query "user.name" --output tsv
# Output: rmhazure@rob634gmail.onmicrosoft.com

# Get access token for PostgreSQL
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

# Verify token was acquired
echo "Token acquired: ${TOKEN:0:50}..."
```

---

## Step 2: Create PostgreSQL Role as Entra ID Principal (Admin)

Connect to the **postgres** database (NOT geopgflex) and run:

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "rmhazure@rob634gmail.onmicrosoft.com" \
    -d postgres \
    -c "SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', true, false);"
```

### SQL Explanation

```sql
-- ============================================================================
-- Create Entra ID role for rmhpgflexadmin managed identity (ADMIN)
-- ============================================================================
-- This creates a PostgreSQL role linked to the Azure AD managed identity.
-- The role can only authenticate using Azure AD tokens, not passwords.
--
-- Parameters:
--   'rmhpgflexadmin'   - Role name (should match the managed identity name)
--   true               - is_admin: PostgreSQL admin (azure_pg_admin member, CREATEROLE, CREATEDB)
--   false              - is_mfa: No MFA enforcement required
--
-- NOTE: This MUST be run on the 'postgres' database, not user databases!
-- ============================================================================

SELECT * FROM pgaadauth_create_principal('rmhpgflexadmin', true, false);
```

### Expected Output

```
pgaadauth_create_principal
----------------------------------
 Created role for rmhpgflexadmin
(1 row)
```

### Verify Role Creation

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "rmhazure@rob634gmail.onmicrosoft.com" \
    -d postgres \
    -c "SELECT rolname, rolcanlogin, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = 'rmhpgflexadmin';"
```

Expected output (admin role):
```
    rolname     | rolcanlogin | rolcreaterole | rolcreatedb
----------------+-------------+---------------+-------------
 rmhpgflexadmin | t           | t             | t
(1 row)
```

---

## Step 3: Grant Admin Schema Access

Now connect to the **geopgflex** database (as the schema owner) and grant full permissions.

These grants provide **full read/write** access including INSERT, UPDATE, DELETE, and schema management.

```bash
# Connect as schema owner (rob634) to grant permissions
PGPASSWORD='B@lamb634@' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d geopgflex \
    -c "
-- ============================================================================
-- Grant ADMIN (READ/WRITE) permissions to rmhpgflexadmin
-- ============================================================================
-- Grants:
--   - ALL PRIVILEGES: Full access to all operations
--   - Includes: SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
--   - DEFAULT PRIVILEGES: Applies to future tables/functions/sequences
-- ============================================================================

-- --------------------------------------
-- Schema: geo (OGC Features API - PostGIS vector data)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA geo TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA geo TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: pgstac (STAC API - raster metadata catalog)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA pgstac TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA pgstac TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: h3 (H3 hexagon spatial indexing)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA h3 TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA h3 TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: app (CoreMachine jobs/tasks)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA app TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: platform (ETL orchestration)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA platform TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA platform TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA platform GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;

-- --------------------------------------
-- Schema: silver (Processed data tier)
-- --------------------------------------
GRANT ALL PRIVILEGES ON SCHEMA silver TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA silver TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA silver TO rmhpgflexadmin;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA silver TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL PRIVILEGES ON TABLES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL PRIVILEGES ON SEQUENCES TO rmhpgflexadmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA silver GRANT ALL PRIVILEGES ON FUNCTIONS TO rmhpgflexadmin;
"
```

### Verify Permissions

```bash
PGPASSWORD='B@lamb634@' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U rob634 \
    -d geopgflex \
    -c "
SELECT
    n.nspname as schema,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'USAGE') as has_usage,
    has_schema_privilege('rmhpgflexadmin', n.nspname, 'CREATE') as has_create
FROM pg_namespace n
WHERE n.nspname IN ('geo', 'pgstac', 'h3', 'app', 'platform', 'silver', 'public')
ORDER BY n.nspname;"
```

Expected output:
```
  schema  | has_usage | has_create
----------+-----------+------------
 app      | t         | t
 geo      | t         | t
 h3       | t         | t
 pgstac   | t         | t
 platform | t         | t
 public   | t         | f
 silver   | t         | t
(7 rows)
```

---

## Step 4: Assign Identity to Azure Function App (ETL System)

```bash
# Get the full resource ID of the managed identity
IDENTITY_ID=$(az identity show \
    --name rmhpgflexadmin \
    --resource-group rmhazure_rg \
    --query id \
    --output tsv)

echo "Identity ID: $IDENTITY_ID"
# Output: /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourcegroups/rmhazure_rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/rmhpgflexadmin

# Assign the identity to the ETL Function App (rmhazuregeoapi)
az functionapp identity assign \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg \
    --identities "$IDENTITY_ID"
```

---

## Step 5: Configure Application Settings

Update the Azure Function App settings to use the managed identity:

```bash
az functionapp config appsettings set \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "AZURE_CLIENT_ID=a533cb80-a590-4fad-8e52-1eb1f72659d7" \
        "POSTGIS_USER=rmhpgflexadmin"
```

### Settings Explanation

| Setting | Value | Description |
|---------|-------|-------------|
| `USE_MANAGED_IDENTITY` | `true` | Enable managed identity authentication |
| `AZURE_CLIENT_ID` | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | Client ID of rmhpgflexadmin UMI |
| `POSTGIS_USER` | `rmhpgflexadmin` | PostgreSQL role name (must match Entra ID role) |

---

## Step 6: Restart and Test

```bash
# Restart the Function App to pick up new settings
az functionapp restart \
    --name rmhazuregeoapi \
    --resource-group rmhazure_rg

# Wait for restart
sleep 15

# Test with an appropriate admin endpoint
curl -s "https://rmhazuregeoapi-xxx.azurewebsites.net/api/health" | jq '.'
```

---

## Troubleshooting

### Error: "function pgaadauth_create_principal does not exist"

**Cause**: You're connected to the wrong database. The `pgaadauth_*` functions only exist in the `postgres` database.

**Solution**: Connect to the `postgres` database, not `geopgflex`:

```bash
# Wrong - connects to geopgflex
PGPASSWORD="$TOKEN" psql -h ... -d geopgflex -c "SELECT * FROM pgaadauth_create_principal(...);"

# Correct - connects to postgres
PGPASSWORD="$TOKEN" psql -h ... -d postgres -c "SELECT * FROM pgaadauth_create_principal(...);"
```

### Error: "password authentication failed for user"

**Cause**: The PostgreSQL role exists but was created as a regular password-based role, not an Entra ID role.

**Solution**: The role must be created using `pgaadauth_create_principal()` on the postgres database, not using `CREATE ROLE`.

### Error: "permission denied for schema"

**Cause**: The GRANT statements haven't been run or weren't run by the schema owner.

**Solution**: Re-run the GRANT statements as the schema owner (usually the user who created the schema).

---

## Comparison: Admin vs Reader Identities

| Feature | rmhpgflexadmin | rmhpgflexreader |
|---------|----------------|-----------------|
| **Client ID** | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f` |
| **Principal ID** | `ab45e154-ae11-4e99-9e96-76da5fe51656` | `789cc11a-d667-4915-b4de-88e76eda1cfb` |
| **PostgreSQL Admin** | Yes (azure_pg_admin) | No |
| **SELECT** | Yes | Yes |
| **INSERT/UPDATE/DELETE** | Yes | No |
| **CREATE/DROP** | Yes | No |
| **Use Case** | ETL, migrations | APIs, read-only queries |
| **Target Apps** | rmhazuregeoapi | rmhogcapi, TiTiler |

---

## Security Notes

1. **Admin privileges by design**: This identity can create, modify, and delete database objects
2. **No password stored**: Authentication uses Azure AD tokens, no secrets in app settings
3. **Limited assignment**: Only assign to applications that genuinely need write access
4. **Audit trail**: All access is logged through Azure AD and PostgreSQL logs
5. **Token expiration**: Tokens expire after ~1 hour, automatically refreshed by azure-identity SDK
6. **Separate concerns**: Use `rmhpgflexreader` for read-only applications

---

## Application Code Requirements

The application must use the `azure-identity` package to acquire tokens:

```python
from azure.identity import ManagedIdentityCredential

# User-assigned managed identity requires client_id
credential = ManagedIdentityCredential(client_id="a533cb80-a590-4fad-8e52-1eb1f72659d7")

# Get token for PostgreSQL
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")

# Use token as password in connection string
conn_string = f"postgresql://rmhpgflexadmin:{token.token}@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require"
```

---

## Related Identities

| Identity | Client ID | Purpose | Status |
|----------|-----------|---------|--------|
| `rmhpgflexadmin` | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | Admin access for ETL/management | **DOCUMENTATION READY** |
| `rmhpgflexreader` | `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f` | Read-only access for APIs | **ACTIVE** |
| `rmhtitileridentity` | `191869d4-fd0b-4b18-a058-51adc2dbd54b` | Legacy (password-based) | Deprecated |

---

## References

- [Microsoft Learn - Connect With Managed Identity](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-connect-with-managed-identity)
- [Microsoft Learn - Manage Microsoft Entra Users](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-manage-azure-ad-users)
- [Microsoft Learn - Microsoft Entra Authentication Concepts](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-azure-ad-authentication)
- [Azure PostgreSQL Flexible Server Entra ID Authentication](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-configure-sign-in-azure-ad-authentication)
