# Database Reader Setup: rmhpgflexreader

This document records all steps and SQL commands for setting up the `rmhpgflexreader` user-assigned managed identity as a read-only database role for Azure PostgreSQL Flexible Server.

Status: Production

---

## Overview

The `rmhpgflexreader` is a user-assigned managed identity (UMI) designed to provide **read-only** database access for applications that only need to query data, not modify it. This identity can be shared across multiple applications:

- **rmhogcapi** - OGC Features & STAC API Service
- **TiTiler** - Dynamic tile server
- Other read-only API consumers

---

## Prerequisites

### 1. User-Assigned Managed Identity Details

| Property | Value |
|----------|-------|
| **Name** | `rmhpgflexreader` |
| **Client ID** | `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f` |
| **Principal ID (Object ID)** | `789cc11a-d667-4915-b4de-88e76eda1cfb` |
| **Resource Group** | `rmhazure_rg` |

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
# Output: {managed_identity}@{tenant}.onmicrosoft.com

# Get access token for PostgreSQL
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

# Verify token was acquired
echo "Token acquired: ${TOKEN:0:50}..."
```

---

## Step 2: Create PostgreSQL Role as Entra ID Principal

Connect to the **postgres** database (NOT geopgflex) and run:

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "{managed_identity}@{tenant}.onmicrosoft.com" \
    -d postgres \
    -c "SELECT * FROM pgaadauth_create_principal('rmhpgflexreader', false, false);"
```

### SQL Explanation

```sql
-- ============================================================================
-- Create Entra ID role for rmhpgflexreader managed identity
-- ============================================================================
-- This creates a PostgreSQL role linked to the Azure AD managed identity.
-- The role can only authenticate using Azure AD tokens, not passwords.
--
-- Parameters:
--   'rmhpgflexreader'  - Role name (should match the managed identity name)
--   false              - is_admin: Not a PostgreSQL admin (no azure_pg_admin membership)
--   false              - is_mfa: No MFA enforcement required
--
-- NOTE: This MUST be run on the 'postgres' database, not user databases!
-- ============================================================================

SELECT * FROM pgaadauth_create_principal('rmhpgflexreader', false, false);
```

### Expected Output

```
pgaadauth_create_principal
----------------------------------
 Created role for rmhpgflexreader
(1 row)
```

### Verify Role Creation

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "{managed_identity}@{tenant}.onmicrosoft.com" \
    -d postgres \
    -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'rmhpgflexreader';"
```

Expected output:
```
     rolname      | rolcanlogin
------------------+-------------
 rmhpgflexreader  | t
(1 row)
```

---

## Step 3: Grant Read-Only Schema Access

Now connect to the **geopgflex** database (as the schema owner) and grant permissions.

These grants provide **SELECT-only** access. No INSERT, UPDATE, DELETE, or CREATE permissions are granted.

```bash
# Connect as schema owner ({db_superuser}) to grant permissions
PGPASSWORD='{db_password}' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U {db_superuser} \
    -d geopgflex \
    -c "
-- ============================================================================
-- Grant READ-ONLY permissions to rmhpgflexreader
-- ============================================================================
-- Grants:
--   - USAGE ON SCHEMA: Allows accessing objects in the schema
--   - SELECT ON ALL TABLES: Allows reading table data (READ-ONLY)
--   - EXECUTE ON ALL FUNCTIONS: Allows calling stored functions
--   - DEFAULT PRIVILEGES: Applies to future tables/functions
--
-- NOT granted:
--   - INSERT, UPDATE, DELETE on tables
--   - CREATE on schemas
--   - TRUNCATE, REFERENCES, TRIGGER
-- ============================================================================

-- --------------------------------------
-- Schema: geo (OGC Features API - PostGIS vector data)
-- --------------------------------------
GRANT USAGE ON SCHEMA geo TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO rmhpgflexreader;

-- --------------------------------------
-- Schema: pgstac (STAC API - raster metadata catalog)
-- --------------------------------------
GRANT USAGE ON SCHEMA pgstac TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO rmhpgflexreader;

-- Grant execute on pgstac functions (required for STAC queries)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT EXECUTE ON FUNCTIONS TO rmhpgflexreader;

-- --------------------------------------
-- Schema: h3 (H3 hexagon spatial indexing)
-- --------------------------------------
GRANT USAGE ON SCHEMA h3 TO rmhpgflexreader;
GRANT SELECT ON ALL TABLES IN SCHEMA h3 TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT SELECT ON TABLES TO rmhpgflexreader;

-- Grant execute on h3 functions (required for hex queries)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA h3 TO rmhpgflexreader;
ALTER DEFAULT PRIVILEGES IN SCHEMA h3 GRANT EXECUTE ON FUNCTIONS TO rmhpgflexreader;
"
```

### Expected Output

```
GRANT
GRANT
ALTER DEFAULT PRIVILEGES
GRANT
GRANT
ALTER DEFAULT PRIVILEGES
GRANT
ALTER DEFAULT PRIVILEGES
GRANT
GRANT
ALTER DEFAULT PRIVILEGES
GRANT
ALTER DEFAULT PRIVILEGES
```

### Verify Permissions

```bash
PGPASSWORD='{db_password}' psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U {db_superuser} \
    -d geopgflex \
    -c "
SELECT
    n.nspname as schema,
    has_schema_privilege('rmhpgflexreader', n.nspname, 'USAGE') as has_usage
FROM pg_namespace n
WHERE n.nspname IN ('geo', 'pgstac', 'h3', 'public')
ORDER BY n.nspname;"
```

Expected output:
```
 schema | has_usage
--------+-----------
 geo    | t
 h3     | t
 pgstac | t
 public | t
(4 rows)
```

---

## Step 4: Assign Identity to Azure Function App

```bash
# Get the full resource ID of the managed identity
IDENTITY_ID=$(az identity show \
    --name rmhpgflexreader \
    --resource-group rmhazure_rg \
    --query id \
    --output tsv)

echo "Identity ID: $IDENTITY_ID"
# Output: /subscriptions/fc7a176b-9a1d-47eb-8a7f-08cc8058fcfa/resourcegroups/rmhazure_rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/rmhpgflexreader

# Assign the identity to the Function App
az functionapp identity assign \
    --name rmhgeoapifn \
    --resource-group rmhazure_rg \
    --identities "$IDENTITY_ID"
```

### Expected Output

```
PrincipalId                           TenantId
------------------------------------  ------------------------------------
e2035966-db57-40cf-b22e-b5cacb827c59  086aef7e-db12-4161-8a9f-777deb499cfa
```

### Verify Identity Assignment

```bash
az functionapp identity show \
    --name rmhgeoapifn \
    --resource-group rmhazure_rg \
    --query "userAssignedIdentities" \
    --output json
```

---

## Step 5: Configure Application Settings

Update the Azure Function App settings to use the managed identity:

```bash
az functionapp config appsettings set \
    --name rmhgeoapifn \
    --resource-group rmhazure_rg \
    --settings \
        "USE_MANAGED_IDENTITY=true" \
        "AZURE_CLIENT_ID=1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f" \
        "POSTGIS_USER=rmhpgflexreader"
```

### Settings Explanation

| Setting | Value | Description |
|---------|-------|-------------|
| `USE_MANAGED_IDENTITY` | `true` | Enable managed identity authentication |
| `AZURE_CLIENT_ID` | `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f` | Client ID of rmhpgflexreader UMI |
| `POSTGIS_USER` | `rmhpgflexreader` | PostgreSQL role name (must match Entra ID role) |

---

## Step 6: Restart and Test

```bash
# Restart the Function App to pick up new settings
az functionapp restart \
    --name rmhgeoapifn \
    --resource-group rmhazure_rg

# Wait for restart
sleep 15

# Test health endpoint
curl -s "https://rmhgeoapifn-dydhe8dddef4f7bd.eastus-01.azurewebsites.net/api/health" | jq '.'

# Test OGC Features (uses geo schema)
curl -s "https://rmhgeoapifn-dydhe8dddef4f7bd.eastus-01.azurewebsites.net/api/features/collections" | jq '.collections | length'

# Test STAC API (uses pgstac schema)
curl -s "https://rmhgeoapifn-dydhe8dddef4f7bd.eastus-01.azurewebsites.net/api/stac/collections" | jq '.collections | length'
```

### Expected Results (Verified Working 22 NOV 2025)

```json
// Health endpoint
{
  "status": "healthy",
  "app": "rmhogcapi",
  "description": "OGC Features & STAC API Service",
  "apis": {
    "ogc_features": {
      "available": true,
      "schema": "geo",
      "endpoints": 6
    },
    "stac": {
      "available": true,
      "schema": "pgstac",
      "endpoints": 6
    }
  }
}

// OGC Features: 5 collections found
// STAC API: 4 collections found
```

---

## Step 7: Remove Password from Settings (Optional)

Once managed identity is confirmed working, remove the password:

```bash
az functionapp config appsettings delete \
    --name rmhgeoapifn \
    --resource-group rmhazure_rg \
    --setting-names "POSTGIS_PASSWORD"
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

### Error: "Could not validate AAD user"

**Cause**: The managed identity name doesn't match what Azure AD expects.

**Solution**: Ensure the role name in PostgreSQL exactly matches the managed identity name in Azure.

### Error: "permission denied for schema"

**Cause**: The GRANT statements haven't been run or weren't run by the schema owner.

**Solution**: Re-run the GRANT statements as the schema owner (usually the user who created the schema).

### Verify Available pgaadauth Functions

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken --output tsv)

PGPASSWORD="$TOKEN" psql \
    -h rmhpgflex.postgres.database.azure.com \
    -U "{managed_identity}@{tenant}.onmicrosoft.com" \
    -d postgres \
    -c "SELECT proname FROM pg_proc WHERE proname LIKE 'pgaadauth%' ORDER BY proname;"
```

Expected functions:
```
pgaadauth_create_principal
pgaadauth_create_principal_with_oid
pgaadauth_drop_principal_if_exists
pgaadauth_list_principals
... (and more)
```

---

## Related Identities

| Identity | Client ID | Purpose | Status |
|----------|-----------|---------|--------|
| `rmhpgflexreader` | `1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f` | Read-only access for APIs | **ACTIVE** |
| `rmhpgflexadmin` | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | Admin access for ETL/management | Available |
| `rmhtitileridentity` | `191869d4-fd0b-4b18-a058-51adc2dbd54b` | Legacy (password-based) | Deprecated |

---

## Security Notes

1. **Read-only by design**: This identity can only SELECT data, never modify it
2. **No password stored**: Authentication uses Azure AD tokens, no secrets in app settings
3. **Shared identity**: Can be assigned to multiple apps that need the same access pattern
4. **Audit trail**: All access is logged through Azure AD and PostgreSQL logs
5. **Token expiration**: Tokens expire after ~1 hour, automatically refreshed by azure-identity SDK

---

## Application Code Requirements

The application must use the `azure-identity` package to acquire tokens:

```python
from azure.identity import ManagedIdentityCredential

# User-assigned managed identity requires client_id
credential = ManagedIdentityCredential(client_id="1c79a2fe-42cb-4f30-8fe9-c1dfc04f142f")

# Get token for PostgreSQL
token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")

# Use token as password in connection string
conn_string = f"postgresql://rmhpgflexreader:{token.token}@rmhpgflex.postgres.database.azure.com:5432/geopgflex?sslmode=require"
```

---

## References

- [Microsoft Learn - Connect With Managed Identity](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-connect-with-managed-identity)
- [Microsoft Learn - Manage Microsoft Entra Users](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-manage-azure-ad-users)
- [Microsoft Learn - Microsoft Entra Authentication Concepts](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-azure-ad-authentication)
- [Azure PostgreSQL Flexible Server Entra ID Authentication](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-configure-sign-in-azure-ad-authentication)
