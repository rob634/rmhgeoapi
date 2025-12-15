# Deployment Guide

**Date**: 05 DEC 2025
**Purpose**: Complete deployment, monitoring, and authentication guide

---

## Quick Deployment

### Primary Command
```bash
func azure functionapp publish rmhazuregeoapi --python --build remote
```

### Post-Deployment Verification
```bash
# 1. Health Check
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# 2. Full Schema Rebuild (REQUIRED after deployment!)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/full-rebuild?confirm=yes"

# 3. Submit Test Job
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "deployment test"}'

# 4. Check Job Status (use job_id from step 3)
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## Azure Resources

### Function App
- **Name**: rmhazuregeoapi
- **URL**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
- **Runtime**: Python 3.12
- **Plan**: Basic B3 (App Service Plan: ASP-rmhazure)
- **Tier**: Basic (4 vCPU, 7 GB RAM)
- **Region**: East US

### Database
- **Server**: rmhpgflex.postgres.database.azure.com
- **Database**: geopgflex
- **Schemas**: app, pgstac, geo, h3, platform
- **Version**: PostgreSQL 14
- **Extensions**: PostGIS 3.4

### Storage Account
- **Name**: rmhazuregeo
- **Containers**:
  - `rmhazuregeobronze` - Raw input data
  - `rmhazuregeosilver` - Processed COGs
  - `rmhazuregeogold` - Published datasets (future)
- **Queues**:
  - `geospatial-jobs` - Job orchestration
  - `geospatial-tasks` - Task execution
  - `*-poison` - Failed messages

### Resource Group
- **Name**: rmhazure_rg
- **Location**: East US

---

## Managed Identity Authentication

### Overview
The Function App uses User-Assigned Managed Identity for passwordless PostgreSQL authentication.

### Quick Setup (Production)

**1. Enable Managed Identity**
```bash
az functionapp identity assign \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg
```

**2. Setup PostgreSQL User**
```bash
psql "host=rmhpgflex.postgres.database.azure.com dbname=geopgflex sslmode=require" \
  < scripts/setup_managed_identity_postgres.sql
```

**3. Configure Function App**
```bash
az functionapp config appsettings set \
  --name rmhazuregeoapi \
  --resource-group rmhazure_rg \
  --settings \
    USE_MANAGED_IDENTITY=true \
    MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity
```

**4. Deploy & Test**
```bash
func azure functionapp publish rmhazuregeoapi --python --build remote
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

### Local Development

**Option 1: Azure CLI (Recommended)**
```bash
az login
# Your code works unchanged - no config needed!
```

**Option 2: Password Fallback**
```json
// local.settings.json
{
  "Values": {
    "USE_MANAGED_IDENTITY": "false",
    "POSTGIS_PASSWORD": "your-dev-password"
  }
}
```

### Verify Managed Identity
```bash
# Check logs for managed identity message
# Should show: "Using Azure Managed Identity for PostgreSQL authentication"
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health | jq .database
```

---

## Application Insights Logging

### Prerequisites
```bash
# Must be logged in to Azure CLI
az login

# Verify login
az account show --query "{subscription:name, user:user.name}" -o table
```

### Quick Query Pattern (Copy-Paste Ready)
```bash
cat > /tmp/query_ai.sh << 'EOF'
#!/bin/bash
TOKEN=$(az account get-access-token --resource https://api.applicationinsights.io --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.applicationinsights.io/v1/apps/829adb94-5f5c-46ae-9f00-18e731529222/query" \
  --data-urlencode "query=traces | where timestamp >= ago(15m) | order by timestamp desc | take 10" \
  -G
EOF
chmod +x /tmp/query_ai.sh && /tmp/query_ai.sh | python3 -m json.tool
```

### Key Identifiers
| Component | Value |
|-----------|-------|
| **App ID** | `829adb94-5f5c-46ae-9f00-18e731529222` |
| **Resource Group** | `rmhazure_rg` |
| **Function App** | `rmhazuregeoapi` |

### Common KQL Queries

**Recent Errors (Severity 3+)**
```kql
traces
| where timestamp >= ago(1h)
| where severityLevel >= 3
| project timestamp, message, severityLevel, operation_Name
| order by timestamp desc
| limit 20
```

**Retry-Related Logs**
```kql
traces
| where timestamp >= ago(15m)
| where message contains "RETRY" or message contains "retry"
| project timestamp, message, severityLevel
| order by timestamp desc
```

**Task Processing**
```kql
traces
| where timestamp >= ago(15m)
| where message contains "Processing task" or message contains "task_id"
| project timestamp, message, severityLevel
| order by timestamp desc
```

**Health Endpoint**
```kql
union requests, traces
| where timestamp >= ago(30m)
| where operation_Name contains "health"
| project timestamp, itemType, message, operation_Name
| take 20
```

**Managed Identity Status**
```kql
traces
| where timestamp >= ago(15m)
| where message contains "managed identity"
| take 10
```

### Azure Functions Severity Mapping Bug

**Problem**: Azure SDK incorrectly maps `logging.DEBUG` to severity 1 (INFO) instead of 0 (DEBUG).

**Workaround**: Query by message content, not severity level:
```kql
# DON'T use: where severityLevel == 0  (returns nothing)
# DO use: where message contains '"level": "DEBUG"'

traces
| where timestamp >= ago(15m)
| where message contains '"level": "DEBUG"'
| order by timestamp desc
```

### Why Script Files Work

The script file pattern works because:
1. Token acquisition happens in script's own shell environment
2. Variable properly scoped within script execution
3. Curl inherits correct environment from script
4. `--data-urlencode` handles URL encoding automatically

**Token expiration**: Tokens expire after 1 hour. The script regenerates automatically.

---

## Database Management

### Schema Management Endpoints

**Full Rebuild (Recommended)**
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/full-rebuild?confirm=yes"
```

**Redeploy App Only**
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/redeploy?confirm=yes"
```

**Redeploy pgSTAC Only**
```bash
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance/pgstac/redeploy?confirm=yes"
```

### Database Query Endpoints

**Query Jobs**
```bash
# All jobs
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs

# Failed jobs
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs?status=failed&limit=10"

# Recent jobs (last 24 hours)
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/jobs?hours=24"
```

**Query Tasks**
```bash
# Tasks for specific job
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/tasks/{JOB_ID}

# Failed tasks
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/tasks?status=failed"
```

**Database Statistics**
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/stats
```

**Diagnostics**
```bash
# Test functions
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/diagnostics/functions

# Check enums
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/diagnostics/enums

# All diagnostics
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/diagnostics/all
```

---

## Local Development

### Prerequisites
```bash
# Install Azure Functions Core Tools
brew install azure-functions-core-tools@4

# Install Python 3.12
brew install python@3.12

# Install PostgreSQL client
brew install postgresql
```

### Environment Variables
Create `local.settings.json`:
```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "BRONZE_STORAGE_ACCOUNT": "rmhazuregeo",
    "SILVER_STORAGE_ACCOUNT": "rmhazuregeo",
    "STORAGE_ACCOUNT_KEY": "[See Azure Portal]",
    "POSTGRES_HOST": "rmhpgflex.postgres.database.azure.com",
    "POSTGRES_DB": "geopgflex",
    "USE_MANAGED_IDENTITY": "false",
    "POSTGIS_PASSWORD": "your-password"
  }
}
```

### Run Locally
```bash
pip install -r requirements.txt
func start
curl http://localhost:7071/api/health
```

---

## Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| Jobs stuck in QUEUED | Check poison queue: `curl .../api/monitor/poison` |
| Tasks not completing | Check task details: `curl .../api/dbadmin/tasks/{JOB_ID}` |
| Schema mismatch errors | Redeploy schema: `POST .../api/dbadmin/maintenance/full-rebuild?confirm=yes` |
| "No credentials available" (local) | Run `az login` |
| "Authentication failed" (Azure) | Re-run PostgreSQL managed identity setup |
| Import errors | Check health endpoint for module status |

### Debugging Workflow

**Step 1: Verify Function App is Running**
```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health
```

**Step 2: Check Recent Activity**
```bash
# Use the query_ai.sh script with:
union requests, traces | where timestamp >= ago(10m) | summarize count() by itemType
```

**Step 3: Find Errors**
```bash
traces | where timestamp >= ago(30m) | where severityLevel >= 3 | take 10
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] Run tests locally with `func start`
- [ ] Verify environment variables in Azure Portal
- [ ] Check resource group and subscription

### Deployment
- [ ] Run: `func azure functionapp publish rmhazuregeoapi --python --build remote`
- [ ] Wait for "Deployment successful" message
- [ ] Check deployment logs for errors

### Post-Deployment
- [ ] Run health check endpoint
- [ ] Run full schema rebuild
- [ ] Submit test job
- [ ] Verify job completes successfully
- [ ] Check Application Insights for errors

---

## Critical Warnings

1. **NEVER** deploy to deprecated apps (rmhazurefn, rmhgeoapi, rmhgeoapifn, rmhgeoapibeta)
2. **ALWAYS** run full-rebuild after deployment
3. **NEVER** use production credentials in local development
4. **ALWAYS** check poison queues after deployment

---

## Corporate/QA Environment: DBA Prerequisites (5 DEC 2025)

### Problem

In restricted corporate environments, the managed identity (e.g., `migeoetldbadminqa`) may not have:
- `CREATEROLE` privilege to create new database roles
- Permission to run `GRANT ... TO current_user`

pypgstac migrate attempts these operations:
```sql
CREATE ROLE pgstac_admin;
GRANT pgstac_admin TO current_user;  -- FAILS without CREATEROLE
```

### Solution: DBA Pre-requisites

**A DBA must run the following SQL ONCE before first deployment:**

```sql
-- ========================================
-- DBA Prerequisites for pypgstac migrate
-- Run as superuser/DBA BEFORE application deployment
-- ========================================

-- Step 1: Check if roles already exist
SELECT rolname FROM pg_roles WHERE rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read');

-- Step 2: Create roles (SKIP any roles returned by Step 1)
CREATE ROLE pgstac_admin;
CREATE ROLE pgstac_ingest;
CREATE ROLE pgstac_read;

-- Step 3: Grant roles WITH ADMIN OPTION to managed identity
-- CRITICAL: WITH ADMIN OPTION is required (see explanation below)
-- Replace 'migeoetldbadminqa' with your managed identity name
GRANT pgstac_admin TO migeoetldbadminqa WITH ADMIN OPTION;
GRANT pgstac_ingest TO migeoetldbadminqa WITH ADMIN OPTION;
GRANT pgstac_read TO migeoetldbadminqa WITH ADMIN OPTION;

-- Step 4: Verify configuration (screenshot this for service ticket)
SELECT r.rolname AS role_name,
       m.rolname AS granted_to,
       am.admin_option AS has_admin_option
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname IN ('pgstac_admin', 'pgstac_ingest', 'pgstac_read')
AND m.rolname = 'migeoetldbadminqa'
ORDER BY r.rolname;
-- Expected: 3 rows, all with has_admin_option = true
```

**Why WITH ADMIN OPTION?**

pypgstac's migration SQL unconditionally runs `GRANT pgstac_admin TO current_user`, even if the user is already a member. To execute a GRANT statement for a role, you must either:
- Be a superuser
- Have ADMIN OPTION on that role

Simple role membership is NOT sufficient. WITH ADMIN OPTION grants only the narrow privilege to manage membership in these specific roles - it does NOT grant superuser or CREATEROLE privileges.

### Timing: Roles Can Be Created BEFORE pgstac Schema

PostgreSQL roles are **cluster-level objects** stored in `pg_roles`, completely independent of any schema. The DBA can run these commands:
- On a fresh database with no schemas
- Before the application is ever deployed
- At any time before `pypgstac migrate` runs

The roles won't have permissions until pypgstac creates the schema and applies grants to tables/functions, but they just need to **exist** and be **granted to the identity** beforehand.

### Pre-flight Check Endpoint

The application provides a pre-flight check to verify DBA prerequisites:

```python
# In your code
from infrastructure.pgstac_bootstrap import PgStacBootstrap

bootstrap = PgStacBootstrap()
prereqs = bootstrap.check_dba_prerequisites(identity_name='migeoetldbadminqa')

if not prereqs['ready']:
    print("DBA must run:")
    print(prereqs['dba_sql'])
```

### Error Detection

If pypgstac migrate fails due to permission errors, the response includes:
- `dba_action_required: True`
- `dba_sql`: The exact SQL for the DBA to run
- `missing_roles`: Roles that don't exist
- `missing_grants`: Grants that are missing

### Deployment Workflow (QA Environment)

1. **DBA runs prerequisites** (once, before first deployment)
2. **Deploy application**: `func azure functionapp publish ...`
3. **Run full-rebuild**: `POST /api/dbadmin/maintenance/full-rebuild?confirm=yes`
4. **pypgstac migrate succeeds** (roles already exist and granted)

### Verification

After DBA runs prerequisites, verify with:
```sql
-- Check roles exist
SELECT rolname FROM pg_roles WHERE rolname LIKE 'pgstac_%';

-- Check grants (replace with your identity name)
SELECT r.rolname as role, m.rolname as member
FROM pg_auth_members am
JOIN pg_roles r ON am.roleid = r.oid
JOIN pg_roles m ON am.member = m.oid
WHERE r.rolname LIKE 'pgstac_%'
AND m.rolname = 'migeoetldbadminqa';
```

---

**Last Updated**: 08 DEC 2025
