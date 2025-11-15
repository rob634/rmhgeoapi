# PostgreSQL Managed Identity Setup - Exact SQL Commands

**Date**: 15 NOV 2025
**Function App**: `rmhazuregeoapi`
**Managed Identity Type**: **System-Assigned** ✅ (Already Enabled)
**Principal ID**: `b929d8df-8e4a-43a0-aa1f-6b8743d4ca32`
**Tenant ID**: `086aef7e-db12-4161-8a9f-777deb499cfa`

---

## ✅ Verified: System-Assigned Managed Identity Enabled

Your Function App `rmhazuregeoapi` already has system-assigned managed identity enabled:

```json
{
  "type": "SystemAssigned",
  "principalId": "b929d8df-8e4a-43a0-aa1f-6b8743d4ca32",
  "tenantId": "086aef7e-db12-4161-8a9f-777deb499cfa"
}
```

**No Azure configuration needed** - proceed directly to PostgreSQL setup below.

---

## 🔐 Identity Details

**Identity Name for PostgreSQL**: `rmhazuregeoapi-identity`

This is the default naming convention used by the code:
- Format: `{FUNCTION_APP_NAME}-identity`
- Matches PostgreSQL user that will be created below

---

## 📋 PostgreSQL Setup Commands

### Step 1: Connect to PostgreSQL as Entra Administrator

**CRITICAL**: You must connect as **Microsoft Entra (Azure AD) administrator**, not a regular PostgreSQL user.

#### Option A: Using psql (Local)

```bash
# Replace YOUR_ENTRA_ADMIN_EMAIL with your Azure AD admin email
psql "host=rmhpgflex.postgres.database.azure.com \
      port=5432 \
      dbname=geopgflex \
      user=YOUR_ENTRA_ADMIN_EMAIL \
      sslmode=require"

# Example:
# psql "host=rmhpgflex.postgres.database.azure.com \
#       port=5432 \
#       dbname=geopgflex \
#       user=rmhazure@rob634gmail.onmicrosoft.com \
#       sslmode=require"
```

#### Option B: Using Azure Cloud Shell

```bash
# Cloud Shell has psql pre-installed and you're already authenticated
az login  # If not already logged in

psql "host=rmhpgflex.postgres.database.azure.com \
      port=5432 \
      dbname=geopgflex \
      user=$(az account show --query user.name -o tsv) \
      sslmode=require"
```

#### Option C: Using pgAdmin/DBeaver

- **Host**: `rmhpgflex.postgres.database.azure.com`
- **Port**: `5432`
- **Database**: `geopgflex`
- **Username**: Your Azure AD admin email
- **Password**: Use Azure AD authentication token
- **SSL Mode**: `require`

---

### Step 2: Execute SQL Commands

Copy and paste the following SQL commands into your PostgreSQL client:

```sql
-- ============================================================================
-- CREATE MANAGED IDENTITY USER
-- ============================================================================
-- This creates a PostgreSQL role for the Function App's managed identity.
-- The name MUST be exactly: rmhazuregeoapi-identity
-- ============================================================================

SELECT pgaadauth_create_principal('rmhazuregeoapi-identity', false, false);

-- Expected output:
-- pgaadauth_create_principal
-- ----------------------------
-- Created role for "rmhazuregeoapi-identity"


-- ============================================================================
-- GRANT DATABASE CONNECTION
-- ============================================================================

GRANT CONNECT ON DATABASE geopgflex TO "rmhazuregeoapi-identity";


-- ============================================================================
-- GRANT SCHEMA PRIVILEGES
-- ============================================================================
-- Allows the identity to use and create objects in these schemas

GRANT USAGE, CREATE ON SCHEMA app TO "rmhazuregeoapi-identity";
GRANT USAGE, CREATE ON SCHEMA geo TO "rmhazuregeoapi-identity";
GRANT USAGE, CREATE ON SCHEMA pgstac TO "rmhazuregeoapi-identity";
GRANT USAGE, CREATE ON SCHEMA h3 TO "rmhazuregeoapi-identity";
GRANT USAGE ON SCHEMA platform TO "rmhazuregeoapi-identity";


-- ============================================================================
-- GRANT TABLE PRIVILEGES (All Existing Tables)
-- ============================================================================
-- Allows SELECT, INSERT, UPDATE, DELETE on all current tables

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO "rmhazuregeoapi-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA geo TO "rmhazuregeoapi-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pgstac TO "rmhazuregeoapi-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA h3 TO "rmhazuregeoapi-identity";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA platform TO "rmhazuregeoapi-identity";


-- ============================================================================
-- GRANT SEQUENCE PRIVILEGES (For Auto-Increment IDs)
-- ============================================================================
-- Required for INSERT operations on tables with SERIAL/BIGSERIAL columns

GRANT USAGE ON ALL SEQUENCES IN SCHEMA app TO "rmhazuregeoapi-identity";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA geo TO "rmhazuregeoapi-identity";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA pgstac TO "rmhazuregeoapi-identity";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA h3 TO "rmhazuregeoapi-identity";
GRANT USAGE ON ALL SEQUENCES IN SCHEMA platform TO "rmhazuregeoapi-identity";


-- ============================================================================
-- GRANT FUNCTION EXECUTION PRIVILEGES
-- ============================================================================
-- CRITICAL: Allows execution of PostgreSQL functions used by the application
-- Examples: complete_task_and_check_stage, advance_job_stage, pgstac functions

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO "rmhazuregeoapi-identity";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO "rmhazuregeoapi-identity";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA h3 TO "rmhazuregeoapi-identity";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA platform TO "rmhazuregeoapi-identity";


-- ============================================================================
-- SET DEFAULT PRIVILEGES (For Future Objects)
-- ============================================================================
-- Automatically grants permissions when new tables/functions/sequences are created

-- Future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA h3
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA platform
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "rmhazuregeoapi-identity";

-- Future sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT USAGE ON SEQUENCES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo
    GRANT USAGE ON SEQUENCES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
    GRANT USAGE ON SEQUENCES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA h3
    GRANT USAGE ON SEQUENCES TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA platform
    GRANT USAGE ON SEQUENCES TO "rmhazuregeoapi-identity";

-- Future functions
ALTER DEFAULT PRIVILEGES IN SCHEMA app
    GRANT EXECUTE ON FUNCTIONS TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac
    GRANT EXECUTE ON FUNCTIONS TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA h3
    GRANT EXECUTE ON FUNCTIONS TO "rmhazuregeoapi-identity";
ALTER DEFAULT PRIVILEGES IN SCHEMA platform
    GRANT EXECUTE ON FUNCTIONS TO "rmhazuregeoapi-identity";
```

---

### Step 3: Verify Setup

After executing the SQL commands above, run these verification queries:

```sql
-- Check that user exists
SELECT rolname, rolcanlogin
FROM pg_roles
WHERE rolname = 'rmhazuregeoapi-identity';

-- Expected output:
--        rolname          | rolcanlogin
-- ------------------------+-------------
-- rmhazuregeoapi-identity | t


-- Check schema privileges
SELECT
    nspname AS schema,
    has_schema_privilege('rmhazuregeoapi-identity', nspname, 'USAGE') AS has_usage,
    has_schema_privilege('rmhazuregeoapi-identity', nspname, 'CREATE') AS has_create
FROM pg_namespace
WHERE nspname IN ('app', 'geo', 'pgstac', 'h3', 'platform')
ORDER BY nspname;

-- Expected output: All should show 't' (true) for has_usage and has_create


-- Check table privileges (sample)
SELECT
    table_schema,
    COUNT(*) AS tables_with_privileges
FROM information_schema.role_table_grants
WHERE grantee = 'rmhazuregeoapi-identity'
    AND table_schema IN ('app', 'geo', 'pgstac', 'h3', 'platform')
GROUP BY table_schema
ORDER BY table_schema;

-- Expected output: Should show counts for each schema with tables


-- Check function privileges
SELECT
    routine_schema,
    COUNT(*) AS functions_with_execute
FROM information_schema.routine_privileges
WHERE grantee = 'rmhazuregeoapi-identity'
    AND routine_schema IN ('app', 'pgstac', 'h3', 'platform')
GROUP BY routine_schema
ORDER BY routine_schema;

-- Expected output: Should show counts for schemas with functions
```

---

## 🚀 Next Steps: Enable Managed Identity in Azure Function App

After PostgreSQL setup is complete, configure the Function App:

### Step 1: Add Environment Variables

```bash
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity
```

### Step 2: Deploy Code

```bash
func azure functionapp publish rmhazuregeoapi --python --build remote
```

### Step 3: Test

```bash
# Health check
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Should show: "database": {"status": "connected", "auth_method": "managed_identity"}
```

---

## 🔍 Monitoring

Check Application Insights for successful token acquisition:

```bash
# Create monitoring script
cat > /tmp/check_managed_identity.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(30m) | where message contains 'managed identity' or message contains 'Token acquired' | order by timestamp desc | take 20" \
  -G | python3 -m json.tool
EOF

chmod +x /tmp/check_managed_identity.sh && /tmp/check_managed_identity.sh
```

Look for:
- `"🔐 Using Azure Managed Identity for PostgreSQL authentication"`
- `"✅ Token acquired successfully (expires in ~XXXX s)"`
- `"✅ PostgreSQL connection established successfully"`

---

## 🚨 Troubleshooting

### Issue: "role 'rmhazuregeoapi-identity' already exists"

**Cause**: User already created (safe to ignore)

**Resolution**: Skip user creation, proceed with GRANT statements

### Issue: "permission denied for schema"

**Cause**: Not connected as Entra administrator

**Resolution**: Disconnect and reconnect using Azure AD admin credentials

### Issue: "function pgaadauth_create_principal does not exist"

**Cause**: Not using Azure PostgreSQL Flexible Server with Entra authentication enabled

**Resolution**: Verify server is Azure PostgreSQL Flexible Server and Entra auth is enabled in Azure Portal

---

## 📚 Reference Information

**Managed Identity Details**:
- **Type**: System-Assigned (lifetime tied to Function App)
- **Principal ID**: `b929d8df-8e4a-43a0-aa1f-6b8743d4ca32`
- **Tenant ID**: `086aef7e-db12-4161-8a9f-777deb499cfa`
- **PostgreSQL User Name**: `rmhazuregeoapi-identity`

**Connection Details**:
- **Host**: `rmhpgflex.postgres.database.azure.com`
- **Port**: `5432`
- **Database**: `geopgflex`
- **Schemas**: `app`, `geo`, `pgstac`, `h3`, `platform`

**Token Scope**: `https://ossrdbms-aad.database.windows.net/.default` (fixed for all Azure PostgreSQL)

**Token Lifetime**: ~1 hour (auto-refreshed by Azure SDK)

---

## ✅ Checklist

- [x] Verified system-assigned managed identity enabled on Function App
- [ ] Connected to PostgreSQL as Entra administrator
- [ ] Executed SQL to create managed identity user
- [ ] Executed GRANT statements for all schemas
- [ ] Verified permissions with verification queries
- [ ] Added `USE_MANAGED_IDENTITY=true` to Function App config
- [ ] Deployed updated code
- [ ] Tested health endpoint
- [ ] Verified logs in Application Insights

---

**Ready to proceed?** Copy the SQL commands from Step 2 above and execute them in your PostgreSQL client.
