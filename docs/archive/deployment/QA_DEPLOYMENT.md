# QA Deployment Master Guide

**Date**: 15 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Master orchestration guide for QA environment deployment and code migration

---

## 🎯 Quick Start - Choose Your Scenario

### Scenario A: QA Environment Already Exists (Current Situation)
✅ **Work Azure QA environment is deployed**
✅ **ADO pipeline configured and green**
🔄 **Need to sync code from personal Mac to work environment**

**→ Go to**: [Code Sync Guide](#code-sync-work-environment-exists) (2-3 hours)

---

### Scenario B: Fresh QA Environment Setup (Future Reference)
❌ **No QA environment exists yet**
🏗️ **Need to provision Azure resources**
📋 **Need to configure everything from scratch**

**→ Go to**: [Full Deployment Guide](#full-deployment-new-environment) (1-2 days)

---

## Code Sync (Work Environment Exists)

**Status**: QA infrastructure deployed, ADO pipeline green, just need code sync

### Overview
- **Source**: Personal Mac (`/Users/robertharrison/python_builds/rmhgeoapi`)
- **Destination**: Work VS Code → Work ADO → Work Azure QA
- **Time**: 2-3 hours
- **Prerequisites**: GitHub account, work machine access, ADO access

### Step-by-Step Guide

**📘 Primary Guide**: [docs_claude/WORK_CODE_SYNC_GUIDE.md](docs_claude/WORK_CODE_SYNC_GUIDE.md)

**Quick Steps**:

1. **Personal Mac → GitHub** (30 mins)
   ```bash
   cd /Users/robertharrison/python_builds/rmhgeoapi
   git add -A
   git commit -m "QA migration - sync codebase"
   git push origin dev
   ```

2. **GitHub → Work VS Code** (30 mins)
   ```bash
   cd ~/projects/rmhgeoapi  # On work machine
   git pull origin dev
   ```

3. **Trigger ADO Deployment** (1-2 hours)
   - Push triggers auto-deploy OR
   - Manually run pipeline in ADO

4. **Verify Deployment**
   ```bash
   curl https://<work-qa-app>.azurewebsites.net/api/health
   ```

### Related Documentation

**Configuration**:
- [config.py](config.py) - All environment variables (lines 1-1747)
- [local.settings.example.json](local.settings.example.json) - Template for local dev
- [docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md](docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md) - Quick config lookup

**Environment Setup**:
- [docs_claude/WORK_MIGRATION_ASSESSMENT.md](docs_claude/WORK_MIGRATION_ASSESSMENT.md) - Full migration analysis

**Managed Identity (15 NOV 2025 - Recent Implementation)**:
- [docs_claude/MANAGED_IDENTITY_MIGRATION.md](docs_claude/MANAGED_IDENTITY_MIGRATION.md) - Complete passwordless auth migration guide
- [docs_claude/MANAGED_IDENTITY_QUICKSTART.md](docs_claude/MANAGED_IDENTITY_QUICKSTART.md) - 5-minute setup for production
- [docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md](docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md) - PostgreSQL database configuration
- [config.py](config.py) lines 1666-1747 - `get_postgres_connection_string()` helper function

**Verification**:
- [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md) - Post-deployment testing
- [docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md](docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md) - Comprehensive checklist

---

## Full Deployment (New Environment)

**Status**: No QA environment exists, need to provision everything

### Overview
- **Scope**: Azure infrastructure + code deployment + configuration
- **Time**: 1-2 days (plus approval wait time)
- **Prerequisites**: Azure subscription, permissions to create resources

### Phase 1: Infrastructure Provisioning

**📘 Primary Guide**: [docs_claude/WORK_MIGRATION_ASSESSMENT.md](docs_claude/WORK_MIGRATION_ASSESSMENT.md) - Section 3

**Azure Resources Required**:

1. **Resource Group**
   ```bash
   az group create --name <work-qa-rg> --location eastus
   ```

2. **Storage Account** (~$2/month for 100 GB)
   ```bash
   az storage account create \
     --name <workqastorage> \
     --resource-group <work-qa-rg> \
     --sku Standard_LRS
   ```
   - Containers: bronze-rasters, silver-cogs, gold-geoparquet
   - See: [MULTI_ACCOUNT_STORAGE_ARCHITECTURE.md](MULTI_ACCOUNT_STORAGE_ARCHITECTURE.md)

3. **PostgreSQL Flexible Server** (~$40/month for B2s)
   ```bash
   az postgres flexible-server create \
     --name <workqapostgres> \
     --resource-group <work-qa-rg> \
     --sku-name Standard_B2s \
     --tier Burstable \
     --storage-size 128
   ```
   - Extensions: PostGIS, pg_trgm, btree_gin
   - Schemas: geo, app, platform, pgstac
   - See: [docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md](docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md)

4. **Service Bus Namespace** (~$10/month for Basic)
   ```bash
   az servicebus namespace create \
     --name <workqaservicebus> \
     --resource-group <work-qa-rg> \
     --sku Basic
   ```
   - Queues: geospatial-jobs, geospatial-tasks
   - See: [docs_claude/AZURE_SERVICEBUS_RBAC_ROLES.md](docs_claude/AZURE_SERVICEBUS_RBAC_ROLES.md)

5. **Function App** (~$73/month for B3)
   ```bash
   az functionapp create \
     --name <workqafunctionapp> \
     --resource-group <work-qa-rg> \
     --runtime python \
     --runtime-version 3.12 \
     --os-type Linux \
     --functions-version 4 \
     --storage-account <workqastorage>
   ```
   - Plan: Basic B3 (4 vCPU, 7 GB RAM)
   - See: [docs_claude/EP1_TO_B3_MIGRATION_SUMMARY.md](docs_claude/EP1_TO_B3_MIGRATION_SUMMARY.md)

6. **Application Insights** (Included with Function App)
   - Auto-created with Function App
   - See: [docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md](docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md)

**Total Estimated Cost**: ~$125/month

**Related Documentation**:
- [docs_claude/AZURE_ARCHITECTURE_DIAGRAM.md](docs_claude/AZURE_ARCHITECTURE_DIAGRAM.md) - Visual reference
- [docs_claude/CORPORATE_AZURE_CONFIG_REQUEST.md](docs_claude/CORPORATE_AZURE_CONFIG_REQUEST.md) - Request template for IT

---

### Phase 2: Configuration

**📘 Primary Guides**:
- [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md) - Environment variables
- [docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md](docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md) - Quick lookup

**Environment Variables to Set**:

**In Function App** (Azure Portal or CLI):
```bash
az functionapp config appsettings set \
  --name <workqafunctionapp> \
  --resource-group <work-qa-rg> \
  --settings @qa-app-settings.json
```

**Create qa-app-settings.json**:
```json
[
  {"name": "STORAGE_ACCOUNT_NAME", "value": "<workqastorage>"},
  {"name": "POSTGIS_HOST", "value": "<workqapostgres>.postgres.database.azure.com"},
  {"name": "POSTGIS_USER", "value": "<db-user>"},
  {"name": "POSTGIS_DATABASE", "value": "<database>"},
  {"name": "SERVICE_BUS_NAMESPACE", "value": "<workqaservicebus>"},
  {"name": "USE_MANAGED_IDENTITY", "value": "true"},
  {"name": "LOG_LEVEL", "value": "INFO"}
]
```

**See [config.py](config.py) lines 660-1566 for complete variable list**

**Managed Identity Setup** (15 NOV 2025 - Recent Implementation):
- **Migration Guide**: [docs_claude/MANAGED_IDENTITY_MIGRATION.md](docs_claude/MANAGED_IDENTITY_MIGRATION.md) - Complete implementation guide
- **Quick Start**: [docs_claude/MANAGED_IDENTITY_QUICKSTART.md](docs_claude/MANAGED_IDENTITY_QUICKSTART.md) - 5-minute setup
- **PostgreSQL Setup**: [docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md](docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md) - Database configuration
- **Code Reference**: [config.py](config.py) lines 1666-1747 - `get_postgres_connection_string()` function
- **Benefits**: No passwords, automatic token rotation, audit logging, reduced attack surface

---

### Phase 3: ADO Pipeline Setup

**📘 Primary Guide**: [docs_claude/WORK_CODE_SYNC_GUIDE.md](docs_claude/WORK_CODE_SYNC_GUIDE.md) - Step 3

**Create Pipeline File**: `azure-pipelines.yml`

```yaml
trigger:
  branches:
    include:
      - dev      # QA environment
      - master   # Production (if configured)

pool:
  vmImage: 'ubuntu-latest'

variables:
  pythonVersion: '3.12'
  functionAppName: '<workqafunctionapp>'
  azureSubscription: '<service-connection-name>'

stages:
- stage: Build
  jobs:
  - job: BuildJob
    steps:
    - task: UsePythonVersion@0
      inputs:
        versionSpec: '$(pythonVersion)'

    - script: pip install -r requirements.txt
      displayName: 'Install dependencies'

    - task: ArchiveFiles@2
      inputs:
        rootFolderOrFile: '$(System.DefaultWorkingDirectory)'
        archiveFile: '$(Build.ArtifactStagingDirectory)/$(Build.BuildId).zip'

    - publish: '$(Build.ArtifactStagingDirectory)/$(Build.BuildId).zip'
      artifact: drop

- stage: Deploy
  jobs:
  - deployment: DeployQA
    environment: 'QA'
    strategy:
      runOnce:
        deploy:
          steps:
          - task: AzureFunctionApp@1
            inputs:
              azureSubscription: '$(azureSubscription)'
              appName: '$(functionAppName)'
              package: '$(Pipeline.Workspace)/drop/$(Build.BuildId).zip'
              runtimeStack: 'PYTHON|3.12'
```

**Service Connection**:
- In ADO → Project Settings → Service Connections
- Create Azure Resource Manager connection
- Grant permissions to Function App resource group

---

### Phase 4: Code Deployment

**📘 Primary Guide**: [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md)

**Option A - Via ADO Pipeline** (Recommended):
```bash
git push origin dev
# Pipeline auto-triggers
```

**Option B - Direct Deployment** (Quick test):
```bash
func azure functionapp publish <workqafunctionapp> --python --build remote
```

---

### Phase 5: Verification

**📘 Primary Guides**:
- [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md) - Testing procedures
- [docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md](docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md) - Comprehensive checklist

**Verification Steps**:

1. **Health Check**
   ```bash
   curl https://<workqafunctionapp>.azurewebsites.net/api/health
   ```
   Expected: `{"status": "ok", "components": {...}}`

2. **Deploy Database Schema**
   ```bash
   curl -X POST https://<workqafunctionapp>.azurewebsites.net/api/db/schema/redeploy?confirm=yes
   ```
   Expected: `{"message": "Schema redeployed successfully"}`

3. **Submit Test Job**
   ```bash
   curl -X POST https://<workqafunctionapp>.azurewebsites.net/api/jobs/submit/hello_world \
     -H "Content-Type: application/json" \
     -d '{"message": "QA test", "n": 3}'
   ```
   Expected: `{"job_id": "...", "status": "queued"}`

4. **Check Job Status**
   ```bash
   curl https://<workqafunctionapp>.azurewebsites.net/api/jobs/status/{JOB_ID}
   ```
   Expected: `{"status": "completed", "result": {...}}`

5. **Verify Application Insights**
   - Azure Portal → Function App → Application Insights
   - Check for errors in last 30 minutes
   - Verify request logs are flowing

**Success Criteria**: ✅ All 5 tests pass

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                       Azure Function App                     │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │  HTTP API  │  │ Service Bus│  │  CoreMachine Engine  │  │
│  │  Triggers  │→ │   Queues   │→ │  (Orchestration)     │  │
│  └────────────┘  └────────────┘  └──────────────────────┘  │
│         ↓               ↓                    ↓               │
└─────────────────────────────────────────────────────────────┘
          ↓               ↓                    ↓
┌─────────────────┐  ┌──────────┐  ┌─────────────────────────┐
│ Azure Storage   │  │PostgreSQL│  │    Task Processors      │
│  (Bronze/Silver │  │ PostGIS  │  │ (Vector/Raster/STAC)    │
│   /Gold Tiers)  │  │ PgSTAC   │  │                         │
└─────────────────┘  └──────────┘  └─────────────────────────┘
```

**Related Documentation**:
- [docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md](docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md) - CoreMachine design
- [docs_claude/ARCHITECTURE_REFERENCE.md](docs_claude/ARCHITECTURE_REFERENCE.md) - Technical details
- [FUNCTION_REVIEW.md](FUNCTION_REVIEW.md) - 80+ function inventory

---

## 🔐 Managed Identity for Database Connections

### Recent Implementation (15 NOV 2025)

**Status**: ✅ **Production-Ready** - Passwordless PostgreSQL authentication implemented

The codebase now supports **Azure Managed Identity** for PostgreSQL authentication, eliminating password management entirely. This is the **recommended approach for QA/Production environments**.

### Key Features

**New Helper Function**: `get_postgres_connection_string()` ([config.py](config.py) lines 1666-1747)

```python
from config import get_postgres_connection_string

# Automatically uses managed identity if enabled
conn_str = get_postgres_connection_string()
```

**Configuration Variables**:
- `USE_MANAGED_IDENTITY=true` - Enable passwordless auth
- `MANAGED_IDENTITY_NAME` - Identity name (auto-generated if not set)
- `POSTGIS_PASSWORD` - Optional fallback for local development

**Benefits**:
- ✅ **No password management** - Azure handles token lifecycle
- ✅ **Automatic token rotation** - Fresh tokens every hour
- ✅ **Audit trail** - All logins tracked in Azure AD
- ✅ **Reduced attack surface** - No credentials in configs or Key Vault

### Implementation Guides

**For QA Deployment**:
1. **Quick Setup**: [docs_claude/MANAGED_IDENTITY_QUICKSTART.md](docs_claude/MANAGED_IDENTITY_QUICKSTART.md) - 5-minute setup guide
2. **Complete Guide**: [docs_claude/MANAGED_IDENTITY_MIGRATION.md](docs_claude/MANAGED_IDENTITY_MIGRATION.md) - Full implementation steps
3. **PostgreSQL Setup**: [docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md](docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md) - Database configuration

**Quick Setup Steps**:
```bash
# 1. Enable managed identity on Function App
az functionapp identity assign \
  --name <workqafunctionapp> \
  --resource-group <work-qa-rg>

# 2. Run PostgreSQL setup script (as Entra admin)
psql "host=<workqapostgres>.postgres.database.azure.com dbname=<database> sslmode=require" \
  < scripts/setup_managed_identity_postgres.sql

# 3. Configure Function App
az functionapp config appsettings set \
  --name <workqafunctionapp> \
  --resource-group <work-qa-rg> \
  --settings USE_MANAGED_IDENTITY=true

# 4. Deploy and test
func azure functionapp publish <workqafunctionapp> --python --build remote
curl https://<workqafunctionapp>.azurewebsites.net/api/health
```

**Local Development**:
```bash
# Option 1: Use Azure CLI credentials (recommended)
az login
# Your code works unchanged!

# Option 2: Use password fallback
# Set USE_MANAGED_IDENTITY=false and POSTGIS_PASSWORD in local.settings.json
```

**Verification**:
```bash
# Check health endpoint shows managed identity
curl https://<workqafunctionapp>.azurewebsites.net/api/health | jq .database

# Expected output includes:
# "auth_method": "managed_identity"
```

---

## Configuration Reference

### Essential Configuration Files

**In Repository**:
- [config.py](config.py) - All environment variables (1,747 lines)
- [local.settings.example.json](local.settings.example.json) - Template for local dev
- [host.json](host.json) - Azure Functions runtime config
- [requirements.txt](requirements.txt) - Python dependencies
- [.funcignore](.funcignore) - Files excluded from deployment

**In docs_claude/**:
- [DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md) - Complete deployment procedures
- [AZURE_CONFIG_QUICK_REFERENCE.md](docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md) - Quick config lookup
- [MANAGED_IDENTITY_MIGRATION.md](docs_claude/MANAGED_IDENTITY_MIGRATION.md) - Passwordless auth guide

### Recent Additions (15 NOV 2025)

**Managed Identity** (Passwordless PostgreSQL):
- `USE_MANAGED_IDENTITY` - Enable managed identity auth (default: false)
- `MANAGED_IDENTITY_NAME` - Identity name (auto-generated if not set)
- Helper function: `get_postgres_connection_string()` in [config.py](config.py) lines 1666-1747

**See**: [Managed Identity Section](#-managed-identity-for-database-connections) for implementation guide

### Environment Variable Categories

**Azure Storage** (Multi-account trust zones):
- `STORAGE_ACCOUNT_NAME` - Main storage account
- `BRONZE_CONTAINER_NAME` - Raw uploads (bronze-rasters)
- `SILVER_CONTAINER_NAME` - Processed data (silver-cogs)
- `GOLD_CONTAINER_NAME` - Analytics exports (gold-geoparquet)

**PostgreSQL/PostGIS**:
- `POSTGIS_HOST` - Database server hostname
- `POSTGIS_DATABASE` - Database name
- `POSTGIS_USER` - Database user
- `POSTGIS_PASSWORD` - Password (optional with managed identity)
- `POSTGIS_SCHEMA` - Geo schema (default: geo)
- `APP_SCHEMA` - Application schema (default: app)

**Service Bus** (Parallel processing):
- `SERVICE_BUS_NAMESPACE` - Service Bus namespace
- `SERVICE_BUS_CONNECTION_STRING` - Connection string (local dev)
- `SERVICE_BUS_JOBS_QUEUE` - Jobs queue (default: geospatial-jobs)
- `SERVICE_BUS_TASKS_QUEUE` - Tasks queue (default: geospatial-tasks)

**Managed Identity** (Passwordless):
- `USE_MANAGED_IDENTITY` - Enable managed identity (default: false)
- `MANAGED_IDENTITY_NAME` - Identity name (auto-generated if not set)

**Application**:
- `LOG_LEVEL` - Logging level (DEBUG/INFO/WARNING/ERROR)
- `FUNCTION_TIMEOUT_MINUTES` - Function timeout (default: 30)
- `ENABLE_DATABASE_HEALTH_CHECK` - Enable DB health check (default: true)
- `DEBUG_MODE` - Enable debug logging (default: false)

**Complete list**: See [config.py](config.py) lines 660-1566

---

## Migration History Reference

**Previous Migrations** (for context):

### Configuration Migration (Oct 2025)
- [docs_claude/CONFIG_MIGRATION_PHASES_0_5_COMPLETE.md](docs_claude/CONFIG_MIGRATION_PHASES_0_5_COMPLETE.md) - 6-phase config refactor
- [docs_claude/DEPLOYMENT_PHASES_0_5_SUCCESS.md](docs_claude/DEPLOYMENT_PHASES_0_5_SUCCESS.md) - Deployment validation

### Tier Migration (Nov 2025)
- [docs_claude/EP1_TO_B3_MIGRATION_SUMMARY.md](docs_claude/EP1_TO_B3_MIGRATION_SUMMARY.md) - EP1 Premium → B3 Basic migration

### STAC Migration (Nov 2025)
- [docs_claude/STAC_API_MIGRATION_VERIFICATION.md](docs_claude/STAC_API_MIGRATION_VERIFICATION.md) - STAC API v1.0.0 deployment

### Platform Layer (Oct 2025)
- [docs_claude/PLATFORM_DEPLOYMENT_STATUS.md](docs_claude/PLATFORM_DEPLOYMENT_STATUS.md) - Platform layer deployment

---

## Troubleshooting

### Common Issues

**Pipeline fails with "Module not found"**
- **Cause**: Missing dependency in requirements.txt
- **Solution**: Verify `requirements.txt` is at repository root
- **Docs**: [requirements.txt](requirements.txt)

**Health endpoint returns 500**
- **Cause**: Environment variables not set or database unreachable
- **Solution**: Check Application Insights for error details
- **Docs**: [docs_claude/WORKFLOW_FAILURE_ANALYSIS.md](docs_claude/WORKFLOW_FAILURE_ANALYSIS.md)

**Database connection fails**
- **Cause**: Firewall rules or missing managed identity permissions
- **Solution**: Add Azure services to firewall, grant managed identity access
- **Docs**: [docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md](docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md)

**Service Bus connection fails**
- **Cause**: Missing RBAC permissions or invalid connection string
- **Solution**: Grant "Azure Service Bus Data Sender" role to managed identity
- **Docs**: [docs_claude/AZURE_SERVICEBUS_RBAC_ROLES.md](docs_claude/AZURE_SERVICEBUS_RBAC_ROLES.md)

**Jobs stuck in "queued" status**
- **Cause**: Service Bus queue not processing or function app not running
- **Solution**: Check Application Insights, verify Service Bus triggers
- **Docs**: [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md) - Troubleshooting section

---

## Documentation Index

### Quick Reference
- [README.md](README.md) - Project overview
- [CLAUDE.md](CLAUDE.md) - Claude-specific instructions
- [docs_claude/CLAUDE_CONTEXT.md](docs_claude/CLAUDE_CONTEXT.md) - Primary Claude context
- [docs_claude/TODO.md](docs_claude/TODO.md) - Active tasks

### Deployment & Migration
- **[docs_claude/WORK_CODE_SYNC_GUIDE.md](docs_claude/WORK_CODE_SYNC_GUIDE.md)** ⭐ Current task
- [docs_claude/WORK_MIGRATION_ASSESSMENT.md](docs_claude/WORK_MIGRATION_ASSESSMENT.md) - Full migration analysis
- [docs_claude/DEPLOYMENT_GUIDE.md](docs_claude/DEPLOYMENT_GUIDE.md) - Complete deployment procedures
- [docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md](docs_claude/PHASE_1_DEPLOYMENT_CHECKLIST.md) - Comprehensive checklist

### Configuration
- [config.py](config.py) - **Master configuration** (1,747 lines)
  - Lines 1666-1747: `get_postgres_connection_string()` helper (15 NOV 2025)
- [docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md](docs_claude/AZURE_CONFIG_QUICK_REFERENCE.md) - Quick lookup

### Managed Identity (15 NOV 2025 Implementation)
- [docs_claude/MANAGED_IDENTITY_MIGRATION.md](docs_claude/MANAGED_IDENTITY_MIGRATION.md) - **Complete migration guide**
- [docs_claude/MANAGED_IDENTITY_QUICKSTART.md](docs_claude/MANAGED_IDENTITY_QUICKSTART.md) - **5-minute setup**
- [docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md](docs_claude/POSTGRES_MANAGED_IDENTITY_SETUP.md) - **PostgreSQL configuration**

### Architecture
- [docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md](docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md) - Two-layer architecture
- [docs_claude/ARCHITECTURE_REFERENCE.md](docs_claude/ARCHITECTURE_REFERENCE.md) - Technical deep dive
- [docs_claude/AZURE_ARCHITECTURE_DIAGRAM.md](docs_claude/AZURE_ARCHITECTURE_DIAGRAM.md) - Visual reference
- [FUNCTION_REVIEW.md](FUNCTION_REVIEW.md) - 80+ function inventory

### Storage & Data
- [MULTI_ACCOUNT_STORAGE_ARCHITECTURE.md](MULTI_ACCOUNT_STORAGE_ARCHITECTURE.md) - Trust zone pattern
- [docs_claude/SERVICE_BUS_HARMONIZATION.md](docs_claude/SERVICE_BUS_HARMONIZATION.md) - Three-layer config
- [FEATURE_STAC.md](FEATURE_STAC.md) - STAC implementation
- [PGSTAC-REGISTRATION.md](PGSTAC-REGISTRATION.md) - PgSTAC setup

### Monitoring & Debugging
- [docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md](docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md) - Log queries
- [docs_claude/WORKFLOW_FAILURE_ANALYSIS.md](docs_claude/WORKFLOW_FAILURE_ANALYSIS.md) - Failure diagnostics
- [docs_claude/DEBUG_LOGGING_CHECKPOINTS.md](docs_claude/DEBUG_LOGGING_CHECKPOINTS.md) - Debug patterns

---

## Next Steps

### For Current QA Migration (Code Sync)

1. **Now**: Review [docs_claude/WORK_CODE_SYNC_GUIDE.md](docs_claude/WORK_CODE_SYNC_GUIDE.md)
2. **30 mins**: Push code to GitHub from personal Mac
3. **1 hour**: Clone/pull on work machine, configure local environment
4. **1-2 hours**: Trigger ADO deployment and verify

**Total time**: 2-3 hours

### For Future Reference (New Environment)

1. **Planning**: Review [docs_claude/WORK_MIGRATION_ASSESSMENT.md](docs_claude/WORK_MIGRATION_ASSESSMENT.md)
2. **Approval**: Submit Azure resource request to IT
3. **1-2 days**: Provision infrastructure and configure
4. **2-3 hours**: Deploy code and verify

**Total time**: 1-2 days (plus approval wait)

---

## Success Criteria

**QA environment is operational when**:

✅ Health endpoint returns OK status
✅ Database schema deploys without errors
✅ Test job (hello_world) completes successfully
✅ Service Bus queues process messages
✅ Storage containers accessible
✅ Application Insights shows no errors
✅ All endpoints respond correctly

---

## Support & Contact

**Documentation Issues**: Update relevant markdown files, commit to GitHub
**Azure Resource Issues**: Contact work IT/Azure admins
**Code Issues**: Check Application Insights, review error logs

**Key Resources**:
- Azure Portal: https://portal.azure.com
- Azure DevOps: https://<work-org>.visualstudio.com
- Application Insights: Function App → Monitoring → Application Insights

---

*Last Updated: 15 NOV 2025*
*Primary Guide for Current Task*: [docs_claude/WORK_CODE_SYNC_GUIDE.md](docs_claude/WORK_CODE_SYNC_GUIDE.md)
