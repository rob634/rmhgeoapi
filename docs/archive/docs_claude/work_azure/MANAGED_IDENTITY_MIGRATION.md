# PostgreSQL Managed Identity Migration Guide

**Date**: 15 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: Implementation Complete - Ready for Testing

## 📋 Executive Summary

Migrated PostgreSQL authentication from **password-based** to **Azure Managed Identity** (passwordless authentication). This eliminates password management, improves security posture, and aligns with Azure best practices.

### Benefits

✅ **No password management** - Azure handles token lifecycle
✅ **Automatic token rotation** - Tokens expire after 1 hour, fresh tokens = fresh security
✅ **Audit trail** - All logins tracked in Azure AD logs
✅ **Reduced attack surface** - No credentials in code, configs, or Key Vault
✅ **Azure best practice** - Recommended by Microsoft for all Azure services

### Implementation Status

- ✅ Code changes complete (`infrastructure/postgresql.py`)
- ✅ Configuration fields added (`config.py`)
- ✅ PostgreSQL setup scripts created (`scripts/setup_managed_identity_postgres.sql`)
- ✅ Documentation complete (this file)
- ⏳ **Azure configuration required** (see Step-by-Step Guide below)
- ⏳ **Testing required** (local + Azure deployment)

---

## 🏗️ Architecture Overview

### Authentication Flow

```
Azure Function App (with Managed Identity)
    ↓
1. Request access token from Azure AD
   Scope: "https://ossrdbms-aad.database.windows.net/.default"
    ↓
2. Azure AD validates identity and issues JWT token (valid ~1 hour)
    ↓
3. Pass token as PASSWORD in PostgreSQL connection string
    ↓
4. PostgreSQL validates token with Azure AD and grants access
```

### Decision Logic

The system automatically determines which authentication method to use:

```python
if USE_MANAGED_IDENTITY=true:
    Use managed identity token
elif running_in_azure AND no_password_configured:
    Auto-enable managed identity
else:
    Use password-based authentication (fallback)
```

### Local Development

Local development uses `DefaultAzureCredential` which tries multiple methods:

1. **EnvironmentCredential** - Service principal via env vars
2. **ManagedIdentityCredential** - Only works in Azure (Function Apps, VMs)
3. **AzureCliCredential** - Uses `az login` session ← **Recommended for local dev**
4. **VisualStudioCodeCredential** - VS Code Azure account
5. **InteractiveBrowserCredential** - Opens browser for login

For local development, simply run `az login` and the code works unchanged!

---

## 📝 Step-by-Step Migration Guide

### Phase 1: Azure Infrastructure Setup

#### 1.1 Enable System-Assigned Managed Identity

**Azure Portal**:
1. Navigate to Function App: `rmhazuregeoapi`
2. Settings → Identity → System assigned
3. Status = **On**
4. Click **Save**
5. Note the **Object (principal) ID** (used for verification)

**Azure CLI**:
```bash
# Enable managed identity
az functionapp identity assign \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg

# Capture the principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --query principalId -o tsv)

echo "Managed Identity Principal ID: $PRINCIPAL_ID"
```

#### 1.2 Verify Managed Identity Created

```bash
# Check identity exists
az functionapp identity show \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --query "{principalId:principalId, tenantId:tenantId}" -o table
```

Expected output:
```
PrincipalId                           TenantId
------------------------------------  ------------------------------------
xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
```

---

### Phase 2: PostgreSQL Database Setup

#### 2.1 Connect as Entra Administrator

**CRITICAL**: You must be connected as **Microsoft Entra administrator** to create managed identity users.

**Using psql**:
```bash
# Connect to geopgflex database as Entra admin
psql "host=rmhpgflex.postgres.database.azure.com \
      dbname=geopgflex \
      user=your-entra-admin@yourdomain.com \
      sslmode=require"
```

**Using Azure Cloud Shell**:
```bash
# Cloud Shell has psql pre-installed
az login  # If not already logged in
psql "host=rmhpgflex.postgres.database.azure.com \
      dbname=geopgflex \
      user=$(az account show --query user.name -o tsv) \
      sslmode=require"
```

#### 2.2 Run Setup Script

From the repository root:

```bash
# Run setup script
psql "host=rmhpgflex.postgres.database.azure.com \
      dbname=geopgflex \
      user=your-entra-admin@yourdomain.com \
      sslmode=require" \
  < scripts/setup_managed_identity_postgres.sql
```

Expected output:
```
✅ Created managed identity user: rmhazuregeoapi-identity
✅ Tables accessible: XX
✅ Functions accessible: YY
✅ Sequences accessible: ZZ
```

#### 2.3 Verify Permissions

```bash
# Run verification script
psql "host=rmhpgflex.postgres.database.azure.com \
      dbname=geopgflex \
      user=your-entra-admin@yourdomain.com \
      sslmode=require" \
  < scripts/verify_managed_identity_setup.sql
```

Review output - all checks should show "YES" or "t" (true).

---

### Phase 3: Azure Function App Configuration

#### 3.1 Add Environment Variables

**Azure Portal**:
1. Navigate to Function App: `rmhazuregeoapi`
2. Settings → Configuration → Application settings
3. Click **+ New application setting** and add:

```bash
USE_MANAGED_IDENTITY=true
MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity
```

4. Keep existing PostgreSQL connection variables:
```bash
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_PORT=5432
POSTGIS_DATABASE=geopgflex
POSTGIS_SCHEMA=geo
APP_SCHEMA=app
```

5. **Optional**: Remove `POSTGIS_PASSWORD` (can keep as safety fallback during testing)

**Azure CLI**:
```bash
# Set managed identity configuration
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity
```

#### 3.2 Deploy Updated Code

```bash
# Deploy to Azure Functions
func azure functionapp publish rmhazuregeoapi --python --build remote
```

---

### Phase 4: Testing & Validation

#### 4.1 Health Check

```bash
# Test health endpoint
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

Expected output (partial):
```json
{
  "status": "healthy",
  "database": {
    "status": "connected",
    "auth_method": "managed_identity"
  }
}
```

#### 4.2 Database Connection Test

```bash
# Query database stats endpoint (requires DB connection)
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/db/stats
```

Expected: JSON response with job/task counts (proves database connection working)

#### 4.3 Submit Test Job

```bash
# Submit hello_world job
curl -X POST \
  https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "managed identity test"}'
```

Expected: Job ID returned and job processes successfully

#### 4.4 Monitor Application Insights

```bash
# Create query script
cat > /tmp/query_managed_identity_logs.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(30m) | where message contains 'managed identity' or message contains 'PostgreSQL connection' | order by timestamp desc | take 50" \
  -G
EOF

# Execute and format
chmod +x /tmp/query_managed_identity_logs.sh && /tmp/query_managed_identity_logs.sh | python3 -m json.tool
```

Look for log messages like:
- `"🔐 Using Azure Managed Identity for PostgreSQL authentication"`
- `"✅ Token acquired successfully (expires in ~XXXX s)"`
- `"✅ PostgreSQL connection established successfully"`

---

### Phase 5: Cleanup (After Validation Period)

After 1 week of successful operation with managed identity:

#### 5.1 Remove Password Environment Variable

```bash
# Remove password from Function App config
az functionapp config appsettings delete \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --setting-names POSTGIS_PASSWORD
```

#### 5.2 Update Documentation

- Update `CLAUDE.md` to reflect managed identity as primary auth method
- Mark Key Vault password retrieval as deprecated
- Update `local.settings.example.json` (already done)

#### 5.3 Optional: Remove Password Fallback Code

**Only after high confidence period!**

In `infrastructure/postgresql.py`, remove fallback logic from `_build_managed_identity_connection_string()`:

```python
# Remove this section:
except ClientAuthenticationError as e:
    if self.config.postgis_password:
        logger.warning("⚠️ Falling back to password authentication")
        return self.config.postgis_connection_string
    raise
```

Replace with immediate failure (forces managed identity to work).

---

## 🧪 Local Development Setup

### Option 1: Azure CLI (Recommended)

```bash
# Login to Azure
az login

# Your code works unchanged - uses AzureCliCredential
python -m pytest tests/
```

### Option 2: Password Fallback

In `local.settings.json`:
```json
{
  "Values": {
    "USE_MANAGED_IDENTITY": "false",
    "POSTGIS_PASSWORD": "your-local-dev-password"
  }
}
```

### Option 3: Service Principal (CI/CD)

```bash
# Set environment variables for service principal
export AZURE_CLIENT_ID=<app-id>
export AZURE_CLIENT_SECRET=<secret>
export AZURE_TENANT_ID=<tenant-id>

# Code uses EnvironmentCredential automatically
python your_script.py
```

---

## 🚨 Troubleshooting

### Issue: "Failed to acquire managed identity token"

**Causes**:
1. Managed identity not enabled on Function App
2. Function App not deployed correctly
3. Network connectivity issues

**Resolution**:
```bash
# Verify managed identity exists
az functionapp identity show \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg

# Check Function App logs
az functionapp log tail \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg
```

### Issue: "Authentication failed" from PostgreSQL

**Causes**:
1. Managed identity user not created in PostgreSQL
2. User name mismatch (PostgreSQL user ≠ managed identity name)
3. Insufficient permissions

**Resolution**:
```bash
# Re-run setup script
psql "host=rmhpgflex.postgres.database.azure.com dbname=geopgflex sslmode=require" \
  < scripts/setup_managed_identity_postgres.sql

# Verify permissions
psql "host=rmhpgflex.postgres.database.azure.com dbname=geopgflex sslmode=require" \
  < scripts/verify_managed_identity_setup.sql
```

### Issue: Local development fails with "No credentials available"

**Cause**: Not logged in to Azure CLI

**Resolution**:
```bash
# Login to Azure
az login

# Verify login
az account show
```

### Issue: Token expiration errors after 1 hour

**Expected Behavior**: Tokens expire after ~1 hour. Azure SDK automatically refreshes.

**If errors persist**:
- Check Application Insights for token refresh failures
- Verify managed identity still enabled on Function App
- Verify PostgreSQL user still exists

---

## 📊 Monitoring & Observability

### Key Metrics to Monitor

1. **Authentication Success Rate**
   - Query Application Insights for "managed identity" logs
   - Should see successful token acquisition every ~1 hour

2. **Database Connection Health**
   - Monitor `/api/health` endpoint
   - Should always show "connected" status

3. **Token Refresh Latency**
   - Token acquisition should be < 500ms
   - Check logs for "Token acquired successfully (expires in...)"

4. **Fallback to Password Events**
   - Should be **ZERO** in production
   - Any fallback indicates managed identity failure

### Application Insights Queries

**Managed Identity Activity**:
```kql
traces
| where timestamp >= ago(24h)
| where message contains "managed identity" or message contains "Token acquired"
| order by timestamp desc
| take 100
```

**Authentication Failures**:
```kql
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| where message contains "token" or message contains "authentication"
| order by timestamp desc
```

**Database Connection Stats**:
```kql
traces
| where timestamp >= ago(1h)
| where message contains "PostgreSQL connection"
| summarize count() by bin(timestamp, 5m)
| render timechart
```

---

## 🔐 Security Considerations

### What Changed

**Before (Password-Based)**:
- Password stored in Azure Function App environment variables
- Password rotates only when manually updated
- Password visible to anyone with Function App access
- Password theft = permanent access until rotation

**After (Managed Identity)**:
- No password stored anywhere
- Tokens rotate automatically every hour
- Tokens visible only to Function App runtime (not in config)
- Token theft = access for max 1 hour, then expires

### Audit Logging

All managed identity authentication events are logged in:

1. **Azure AD Sign-in Logs**
   - Navigate to Azure Portal → Azure Active Directory → Sign-in logs
   - Filter: Application = "Azure OSSRDBMS Database"
   - Shows all PostgreSQL authentication attempts

2. **PostgreSQL Server Logs**
   - Navigate to Azure Portal → PostgreSQL server → Monitoring → Logs
   - Query: `event_type = "login"` and `user_name = "rmhazuregeoapi-identity"`

3. **Application Insights**
   - Function App logs show token acquisition and connection success/failure
   - Detailed error logging for troubleshooting

---

## 📚 References

### Official Documentation

- [Azure Managed Identity Overview](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/overview)
- [PostgreSQL Flexible Server - Entra Authentication](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-azure-ad-authentication)
- [DefaultAzureCredential Class](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.defaultazurecredential)
- [Azure SDK for Python - Identity](https://github.com/Azure/azure-sdk-for-python/tree/main/sdk/identity/azure-identity)

### Internal Documentation

- `config.py` - Lines 707-773 (Managed Identity configuration fields)
- `infrastructure/postgresql.py` - Lines 183-399 (Authentication implementation)
- `scripts/setup_managed_identity_postgres.sql` - PostgreSQL user setup
- `scripts/verify_managed_identity_setup.sql` - Permission verification
- `local.settings.example.json` - Lines 22-32 (Configuration example)

### Related Files

- `requirements.txt` - Line 9 (`azure-identity>=1.15.0`)
- `CLAUDE.md` - Primary project documentation
- `docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md` - Log query examples

---

## ✅ Migration Checklist

Copy this checklist to track migration progress:

### Azure Infrastructure
- [ ] Enabled system-assigned managed identity on Function App
- [ ] Verified identity exists (captured Principal ID)
- [ ] Identity shows in Azure Portal under Function App → Identity

### PostgreSQL Setup
- [ ] Connected to PostgreSQL as Entra administrator
- [ ] Ran `setup_managed_identity_postgres.sql`
- [ ] Ran `verify_managed_identity_setup.sql`
- [ ] All permission checks show "YES" or "t"

### Function App Configuration
- [ ] Added `USE_MANAGED_IDENTITY=true`
- [ ] Added `MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity`
- [ ] Verified existing PostgreSQL connection variables present
- [ ] Deployed updated code to Azure Functions

### Testing
- [ ] Health endpoint returns "connected" with managed identity
- [ ] Database stats endpoint returns data
- [ ] Test job submission succeeds
- [ ] Application Insights shows successful token acquisition
- [ ] No errors in logs for 1 hour (token expiration test)

### Validation Period (1 Week)
- [ ] Monitor daily for authentication errors
- [ ] Verify no fallback to password authentication
- [ ] Check token refresh happening every hour
- [ ] All workflows (job submission, STAC queries, OGC features) working

### Cleanup
- [ ] Remove `POSTGIS_PASSWORD` from Azure config
- [ ] Update documentation to reflect managed identity as primary
- [ ] Optional: Remove password fallback code (after high confidence)

---

## 🎯 Success Criteria

Migration is considered successful when:

1. ✅ **Zero authentication errors** for 1 week
2. ✅ **No password fallbacks** in logs
3. ✅ **All endpoints functional** (health, jobs, database, STAC, OGC)
4. ✅ **Token refresh working** (check logs every hour)
5. ✅ **Local development working** with `az login`
6. ✅ **Monitoring in place** (Application Insights queries saved)

---

**End of Migration Guide**

For questions or issues, check Application Insights logs first, then review troubleshooting section above.
