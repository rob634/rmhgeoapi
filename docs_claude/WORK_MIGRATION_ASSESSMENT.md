# Work Environment Migration Assessment

**Date**: 15 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Complete assessment for migrating rmhgeoapi from personal Azure to work Azure environment

---

## Executive Summary

✅ **Environment variables are well centralized and documented**
✅ **Minimum viable CoreMachine package identified**
✅ **Full migration path defined with three phases**

This codebase is **migration-ready** with excellent documentation and centralized configuration.

---

## 1. Environment Variable Centralization Assessment

### ✅ EXCELLENT - Fully Centralized & Documented

**Configuration System Location**: [config.py](../config.py)

**Strengths**:
1. **Single Source of Truth**: All environment variables defined in `config.py` using Pydantic v2
2. **Runtime Validation**: Type checking and validation at startup
3. **Comprehensive Documentation**: Each variable has description, examples, and purpose
4. **Template Available**: `local.settings.example.json` provides complete template
5. **Computed Properties**: Derived values (connection strings, service URLs) auto-generated
6. **Managed Identity Support**: Built-in support for passwordless authentication

**Environment Variable Categories**:

#### Azure Storage (Multi-Account Trust Zones)
```bash
STORAGE_ACCOUNT_NAME=rmhazuregeo
BRONZE_CONTAINER_NAME=bronze-rasters  # Raw uploads
SILVER_CONTAINER_NAME=silver-cogs     # Processed data
GOLD_CONTAINER_NAME=gold-geoparquet   # Analytics exports
```

#### PostgreSQL/PostGIS Database
```bash
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_PORT=5432
POSTGIS_USER=rob634
POSTGIS_PASSWORD=<password>           # Optional with managed identity
POSTGIS_DATABASE=geopgflex
POSTGIS_SCHEMA=geo
APP_SCHEMA=app
```

#### Managed Identity (Passwordless Auth)
```bash
USE_MANAGED_IDENTITY=false            # Set to true in Azure
MANAGED_IDENTITY_NAME=rmhazuregeoapi-identity
```

#### Service Bus (Parallel Processing)
```bash
SERVICE_BUS_NAMESPACE=rmhazure-servicebus
SERVICE_BUS_CONNECTION_STRING=<connection-string>  # For local dev
SERVICE_BUS_JOBS_QUEUE=geospatial-jobs
SERVICE_BUS_TASKS_QUEUE=geospatial-tasks
SERVICE_BUS_MAX_BATCH_SIZE=100
```

#### STAC Configuration
```bash
STAC_DEFAULT_COLLECTION=system-rasters
```

#### Application Settings
```bash
FUNCTION_TIMEOUT_MINUTES=30
MAX_RETRY_ATTEMPTS=3
LOG_LEVEL=INFO
ENABLE_DATABASE_HEALTH_CHECK=true
DEBUG_MODE=false
```

#### API Endpoints
```bash
TITILER_BASE_URL=https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net
OGC_FEATURES_BASE_URL=https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features
TITILER_MODE=pgstac
```

### Migration Readiness: ✅ EXCELLENT

**Documentation Available**:
- ✅ `local.settings.example.json` - Complete template
- ✅ `config.py` lines 660-1566 - Full documentation
- ✅ `DEPLOYMENT_GUIDE.md` - Deployment procedures
- ✅ `MANAGED_IDENTITY_MIGRATION.md` - Passwordless auth guide

**What You Need**:
1. Copy `local.settings.example.json` to work VS Code
2. Update with work Azure resource names
3. Deploy to work Function App
4. Enable managed identity (optional but recommended)

---

## 2. Minimum Viable Package for CoreMachine Testing

### Core Components Required

#### Essential Files (Must Have)
```
rmhgeoapi/
├── function_app.py              # Azure Functions entry point
├── config.py                    # Configuration management
├── requirements.txt             # Python dependencies
├── host.json                    # Azure Functions runtime config
├── local.settings.example.json  # Environment template
│
├── core/                        # CoreMachine orchestration engine
│   ├── __init__.py
│   ├── core_controller.py       # Base controller (400 lines)
│   ├── orchestration_manager.py # Task orchestration
│   ├── models/                  # Pydantic data models
│   │   ├── __init__.py
│   │   ├── enums.py            # JobStatus, TaskStatus
│   │   ├── job.py              # JobRecord
│   │   ├── task.py             # TaskRecord, TaskDefinition
│   │   ├── results.py          # TaskResult, StageResultContract
│   │   └── context.py          # JobExecutionContext
│   │
│   ├── logic/                   # Business logic utilities
│   │   ├── __init__.py
│   │   ├── calculations.py     # Stage advancement
│   │   └── transitions.py      # State transitions
│   │
│   └── schema/                  # Database schema management
│       ├── __init__.py
│       ├── deployer.py         # Schema deployment
│       └── sql_generator.py    # SQL generation
│
├── infrastructure/              # Data access layer
│   ├── __init__.py
│   ├── factory.py              # Repository factory
│   ├── jobs_tasks.py           # Job/Task repository
│   ├── postgresql.py           # PostgreSQL adapter
│   ├── service_bus.py          # Service Bus client
│   └── interface_repository.py # Repository interface
│
├── services/                    # Business logic
│   ├── hello_world.py          # Test service (minimal)
│   └── registry.py             # Service registry
│
├── triggers/                    # HTTP/Queue triggers
│   ├── __init__.py
│   ├── submit_job.py           # Job submission endpoint
│   └── get_job_status.py       # Status check endpoint
│
├── utils/                       # Utilities
│   ├── __init__.py
│   └── contract_validator.py   # Contract enforcement
│
└── exceptions.py                # Custom exceptions
```

#### Database Schema Files
```
infrastructure/
└── schema/
    └── sql/
        ├── 01_enums.sql               # Status enums
        ├── 02_jobs_table.sql          # Jobs table
        ├── 03_tasks_table.sql         # Tasks table
        └── 04_completion_functions.sql # Stage completion logic
```

#### Documentation (Recommended)
```
docs_claude/
├── CLAUDE_CONTEXT.md           # Primary context
├── TODO.md                     # Active tasks
├── DEPLOYMENT_GUIDE.md         # Deployment procedures
└── ARCHITECTURE_REFERENCE.md   # Technical details
```

### File Count Summary
- **Total Python files**: 195 files
- **Core minimum**: ~35 files
- **With full features**: ~195 files

### Testing the Minimum Package

**Step 1**: Deploy minimal package
```bash
# Copy only core/ infrastructure/ services/ triggers/ + config files
func azure functionapp publish <work-function-app> --python --build remote
```

**Step 2**: Verify health endpoint
```bash
curl https://<work-function-app>.azurewebsites.net/api/health
```

**Step 3**: Deploy database schema
```bash
curl -X POST https://<work-function-app>.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

**Step 4**: Submit test job
```bash
curl -X POST https://<work-function-app>.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "work environment test", "n": 3}'
```

**Step 5**: Check job status
```bash
curl https://<work-function-app>.azurewebsites.net/api/jobs/status/{JOB_ID}
```

---

## 3. Full Migration Path

### Phase 1: GitHub Setup (Personal Mac → GitHub)

**Prerequisites**:
- ✅ Git repository initialized (already done)
- ✅ GitHub repository created (if not, create now)

**Steps**:
1. **Verify current git status**:
   ```bash
   cd /Users/robertharrison/python_builds/rmhgeoapi
   git status
   git branch  # Confirm on 'dev' branch
   ```

2. **Commit all current work**:
   ```bash
   git add -A
   git commit -m "Pre-migration commit - QA migration preparation

   🔧 Preparing codebase for work environment migration
   ✅ All 195 Python files included
   ✅ Configuration centralized in config.py
   ✅ Documentation updated with migration guide

   🤖 Generated with [Claude Code](https://claude.com/claude-code)

   Co-Authored-By: Claude <noreply@anthropic.com>"
   ```

3. **Push to GitHub** (if remote not set):
   ```bash
   # Check if remote exists
   git remote -v

   # If no remote, add GitHub remote
   git remote add origin https://github.com/<your-username>/rmhgeoapi.git

   # Push dev branch
   git push -u origin dev

   # Push master branch (stable milestones)
   git checkout master
   git merge dev  # Merge if dev is stable
   git push -u origin master
   git checkout dev
   ```

**Verification**:
- ✅ Both `dev` and `master` branches pushed to GitHub
- ✅ All files visible on GitHub web interface
- ✅ `docs_claude/` folder contains all documentation

---

### Phase 2: Work Environment Setup (GitHub → Work VS Code)

**Prerequisites on Work Machine**:
- Visual Studio Code installed
- Azure Functions Core Tools v4 installed
- Python 3.12 installed
- Azure CLI installed
- Git configured

**Steps**:

1. **Clone repository on work machine**:
   ```bash
   # Clone to work machine
   cd ~/projects  # Or your preferred location
   git clone https://github.com/<your-username>/rmhgeoapi.git
   cd rmhgeoapi
   git checkout dev  # Work on dev branch
   ```

2. **Create work environment variables**:
   ```bash
   # Copy template
   cp local.settings.example.json local.settings.json

   # Edit with work Azure resources
   code local.settings.json
   ```

3. **Update `local.settings.json` with work values**:
   ```json
   {
     "IsEncrypted": false,
     "Values": {
       "AzureWebJobsStorage": "UseDevelopmentStorage=true",
       "FUNCTIONS_WORKER_RUNTIME": "python",

       "STORAGE_ACCOUNT_NAME": "<work-storage-account>",
       "BRONZE_CONTAINER_NAME": "bronze-rasters",
       "SILVER_CONTAINER_NAME": "silver-cogs",
       "GOLD_CONTAINER_NAME": "gold-geoparquet",

       "POSTGIS_HOST": "<work-postgres-server>.postgres.database.azure.com",
       "POSTGIS_PORT": "5432",
       "POSTGIS_USER": "<work-db-user>",
       "POSTGIS_PASSWORD": "<work-db-password>",
       "POSTGIS_DATABASE": "<work-database-name>",
       "POSTGIS_SCHEMA": "geo",
       "APP_SCHEMA": "app",

       "SERVICE_BUS_NAMESPACE": "<work-servicebus-namespace>",
       "SERVICE_BUS_CONNECTION_STRING": "<work-connection-string>",
       "SERVICE_BUS_JOBS_QUEUE": "geospatial-jobs",
       "SERVICE_BUS_TASKS_QUEUE": "geospatial-tasks",

       "LOG_LEVEL": "INFO",
       "FUNCTION_TIMEOUT_MINUTES": "30",
       "ENABLE_DATABASE_HEALTH_CHECK": "true"
     }
   }
   ```

4. **Install Python dependencies**:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

5. **Test locally on work machine**:
   ```bash
   func start

   # In another terminal, test health endpoint
   curl http://localhost:7071/api/health
   ```

**Verification**:
- ✅ Local function app starts without errors
- ✅ Health endpoint returns status
- ✅ Database connection works (if work PostgreSQL accessible from local)

---

### Phase 3: Azure Deployment (Work VS Code → Work Azure)

**Prerequisites in Work Azure**:
1. **Resource Group** created (e.g., `work-geoapi-rg`)
2. **Storage Account** created (e.g., `workgeostorage`)
3. **PostgreSQL Flexible Server** created (e.g., `workgeopostgres`)
4. **Service Bus Namespace** created (e.g., `workgeoservicebus`)
5. **Function App** created:
   - Runtime: Python 3.12
   - Plan: Basic B3 or higher (recommended)
   - Region: Same as other resources

**Important**: Get approval from work IT/Azure admins for resource creation

**Steps**:

1. **Login to work Azure subscription**:
   ```bash
   az login
   az account set --subscription "<work-subscription-id>"
   az account show  # Verify correct subscription
   ```

2. **Configure Function App settings** (via Azure Portal or CLI):
   ```bash
   # Set environment variables in Function App
   az functionapp config appsettings set \
     --name <work-function-app-name> \
     --resource-group <work-resource-group> \
     --settings \
       STORAGE_ACCOUNT_NAME=<work-storage> \
       POSTGIS_HOST=<work-postgres>.postgres.database.azure.com \
       POSTGIS_USER=<work-db-user> \
       POSTGIS_PASSWORD=<work-db-password> \
       POSTGIS_DATABASE=<work-database> \
       SERVICE_BUS_NAMESPACE=<work-servicebus> \
       # ... add all required settings
   ```

3. **Enable managed identity** (recommended):
   ```bash
   # Enable system-assigned managed identity
   az functionapp identity assign \
     --name <work-function-app> \
     --resource-group <work-resource-group>

   # Grant Storage Blob Data Contributor role
   az role assignment create \
     --assignee <managed-identity-principal-id> \
     --role "Storage Blob Data Contributor" \
     --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.Storage/storageAccounts/<storage-account>

   # Grant Service Bus Data Sender role
   az role assignment create \
     --assignee <managed-identity-principal-id> \
     --role "Azure Service Bus Data Sender" \
     --scope /subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.ServiceBus/namespaces/<servicebus-namespace>
   ```

4. **Create PostgreSQL database and schema**:
   ```sql
   -- Connect to work PostgreSQL server
   psql "host=<work-postgres>.postgres.database.azure.com user=<admin-user> dbname=postgres sslmode=require"

   -- Create database if needed
   CREATE DATABASE <work-database>;

   -- Create schemas
   \c <work-database>
   CREATE SCHEMA IF NOT EXISTS geo;
   CREATE SCHEMA IF NOT EXISTS app;
   CREATE SCHEMA IF NOT EXISTS platform;
   CREATE SCHEMA IF NOT EXISTS pgstac;

   -- Install PostGIS extension
   CREATE EXTENSION IF NOT EXISTS postgis SCHEMA geo;
   CREATE EXTENSION IF NOT EXISTS postgis_topology;

   -- Grant permissions to application user
   GRANT USAGE ON SCHEMA geo TO <work-db-user>;
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA geo TO <work-db-user>;
   GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA geo TO <work-db-user>;

   GRANT USAGE ON SCHEMA app TO <work-db-user>;
   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA app TO <work-db-user>;
   GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA app TO <work-db-user>;
   ```

5. **Create Service Bus queues**:
   ```bash
   # Create jobs queue
   az servicebus queue create \
     --name geospatial-jobs \
     --namespace-name <work-servicebus> \
     --resource-group <work-resource-group> \
     --max-delivery-count 3 \
     --lock-duration PT5M

   # Create tasks queue
   az servicebus queue create \
     --name geospatial-tasks \
     --namespace-name <work-servicebus> \
     --resource-group <work-resource-group> \
     --max-delivery-count 3 \
     --lock-duration PT5M
   ```

6. **Create storage containers**:
   ```bash
   # Create Bronze tier containers
   az storage container create --name bronze-rasters --account-name <work-storage>
   az storage container create --name bronze-vectors --account-name <work-storage>

   # Create Silver tier containers
   az storage container create --name silver-cogs --account-name <work-storage>
   az storage container create --name silver-vectors --account-name <work-storage>
   az storage container create --name silver-mosaicjson --account-name <work-storage>

   # Create Gold tier containers
   az storage container create --name gold-geoparquet --account-name <work-storage>
   ```

7. **Deploy function app**:
   ```bash
   # Deploy from work VS Code
   func azure functionapp publish <work-function-app-name> --python --build remote
   ```

8. **Post-deployment verification**:
   ```bash
   # 1. Health check
   curl https://<work-function-app>.azurewebsites.net/api/health

   # 2. Deploy database schema
   curl -X POST https://<work-function-app>.azurewebsites.net/api/db/schema/redeploy?confirm=yes

   # 3. Submit test job
   curl -X POST https://<work-function-app>.azurewebsites.net/api/jobs/submit/hello_world \
     -H "Content-Type: application/json" \
     -d '{"message": "work environment test", "n": 3}'

   # 4. Check job status
   curl https://<work-function-app>.azurewebsites.net/api/jobs/status/{JOB_ID}
   ```

**Verification Checklist**:
- ✅ Function app deployed successfully
- ✅ Health endpoint returns OK status
- ✅ Database schema deployed (no errors)
- ✅ Test job completes successfully
- ✅ Service Bus queues processing messages
- ✅ Storage containers accessible

---

## 4. Environment-Specific Considerations

### Azure DevOps (ADO) Deployment

If work uses Azure DevOps pipelines instead of direct deployment:

1. **Create `azure-pipelines.yml`**:
   ```yaml
   trigger:
     branches:
       include:
         - master
         - dev

   pool:
     vmImage: 'ubuntu-latest'

   variables:
     pythonVersion: '3.12'
     functionAppName: '<work-function-app-name>'
     azureSubscription: '<work-service-connection>'

   steps:
   - task: UsePythonVersion@0
     inputs:
       versionSpec: '$(pythonVersion)'
     displayName: 'Use Python $(pythonVersion)'

   - script: |
       python -m pip install --upgrade pip
       pip install -r requirements.txt
     displayName: 'Install dependencies'

   - task: ArchiveFiles@2
     inputs:
       rootFolderOrFile: '$(System.DefaultWorkingDirectory)'
       includeRootFolder: false
       archiveType: 'zip'
       archiveFile: '$(Build.ArtifactStagingDirectory)/$(Build.BuildId).zip'
       replaceExistingArchive: true

   - task: AzureFunctionApp@1
     inputs:
       azureSubscription: '$(azureSubscription)'
       appType: 'functionAppLinux'
       appName: '$(functionAppName)'
       package: '$(Build.ArtifactStagingDirectory)/$(Build.BuildId).zip'
       runtimeStack: 'PYTHON|3.12'
       deploymentMethod: 'zipDeploy'
   ```

2. **Set pipeline variables** in ADO:
   - All environment variables from `local.settings.json`
   - Mark secrets as "secret" variables

3. **Create service connection** in ADO:
   - Type: Azure Resource Manager
   - Scope: Subscription or Resource Group
   - Grant permissions to Function App

---

## 5. Key Differences: Personal Azure vs Work Azure

### Personal Azure (Current)
- **Subscription**: Personal subscription
- **Resource Group**: `rmhazure_rg`
- **Function App**: `rmhazuregeoapi`
- **Storage**: `rmhazuregeo`
- **PostgreSQL**: `rmhpgflex.postgres.database.azure.com`
- **Service Bus**: `rmhazure-servicebus`
- **Deployment**: Direct via `func` CLI

### Work Azure (Target)
- **Subscription**: Corporate subscription (requires approval)
- **Resource Group**: `<work-resource-group>` (TBD)
- **Function App**: `<work-function-app>` (TBD)
- **Storage**: `<work-storage>` (TBD)
- **PostgreSQL**: `<work-postgres>.postgres.database.azure.com` (TBD)
- **Service Bus**: `<work-servicebus>` (TBD)
- **Deployment**: ADO pipelines or `func` CLI

### Required Work Azure Resources

**Minimum Requirements**:
1. **Function App**: Basic B3 tier or higher (4 vCPU, 7 GB RAM)
2. **PostgreSQL Flexible Server**:
   - Tier: Burstable B2s or General Purpose D2s_v3
   - Storage: 128 GB minimum
   - Extensions: PostGIS, pg_trgm, btree_gin
3. **Storage Account**: Standard LRS or GRS
4. **Service Bus Namespace**: Basic or Standard tier
5. **Application Insights**: For monitoring

**Estimated Monthly Cost** (East US region):
- Function App B3: ~$73/month
- PostgreSQL B2s: ~$40/month
- Storage (100 GB): ~$2/month
- Service Bus Basic: ~$10/month
- **Total**: ~$125/month

---

## 6. Migration Checklist

### Pre-Migration (Personal Mac)
- [ ] Verify git repository is clean (`git status`)
- [ ] Commit all current work to `dev` branch
- [ ] Merge stable changes to `master` branch
- [ ] Push both branches to GitHub
- [ ] Verify all files on GitHub web interface
- [ ] Export current Azure configuration (backup)

### Work Environment Setup
- [ ] Clone repository to work machine
- [ ] Install prerequisites (Python 3.12, Azure Functions Core Tools, Azure CLI)
- [ ] Create `local.settings.json` with work values
- [ ] Install Python dependencies (`pip install -r requirements.txt`)
- [ ] Test locally (`func start`)

### Azure Resource Creation (Work)
- [ ] Get IT/Azure admin approval
- [ ] Create Resource Group
- [ ] Create Storage Account
- [ ] Create storage containers (bronze/silver/gold)
- [ ] Create PostgreSQL Flexible Server
- [ ] Create database and schemas (geo, app, platform, pgstac)
- [ ] Install PostGIS extension
- [ ] Create Service Bus Namespace
- [ ] Create Service Bus queues (jobs, tasks)
- [ ] Create Function App (Python 3.12, Basic B3)
- [ ] Create Application Insights

### Configuration (Work Azure)
- [ ] Set Function App environment variables
- [ ] Enable managed identity on Function App
- [ ] Grant RBAC roles (Storage, Service Bus)
- [ ] Configure PostgreSQL firewall rules
- [ ] Set up ADO pipeline (if required)

### Deployment (Work Azure)
- [ ] Deploy function app (`func azure functionapp publish`)
- [ ] Verify health endpoint
- [ ] Deploy database schema (`/api/db/schema/redeploy`)
- [ ] Submit test job
- [ ] Verify job completion
- [ ] Check Application Insights logs

### Post-Migration
- [ ] Document work Azure resource names
- [ ] Update `docs_claude/CLAUDE_CONTEXT.md` with work URLs
- [ ] Test all endpoints (health, jobs, database)
- [ ] Monitor Application Insights for errors
- [ ] Commit work configuration to `work-config` branch

---

## 7. Rollback Plan

If migration fails or issues arise:

1. **Personal Azure remains operational** (no changes made)
2. **Work Azure can be deleted** (no production dependencies)
3. **GitHub repository has full history** (revert if needed)

**Rollback Steps**:
```bash
# On work machine, revert to previous commit
git log --oneline  # Find commit hash
git checkout <previous-commit-hash>

# Or delete work Azure resources
az group delete --name <work-resource-group> --yes
```

---

## 8. Success Criteria

Migration is successful when:

✅ **Health endpoint** returns OK status in work Azure
✅ **Database schema** deploys without errors
✅ **Test job** completes successfully (hello_world with n=3)
✅ **Service Bus queues** process messages correctly
✅ **Storage containers** accessible via managed identity
✅ **Application Insights** shows no errors
✅ **Documentation updated** with work Azure URLs

---

## 9. Support Resources

**Documentation**:
- `docs_claude/CLAUDE_CONTEXT.md` - Primary context
- `docs_claude/DEPLOYMENT_GUIDE.md` - Deployment procedures
- `docs_claude/MANAGED_IDENTITY_MIGRATION.md` - Passwordless auth guide
- `docs_claude/SERVICE_BUS_HARMONIZATION.md` - Service Bus config
- `docs_claude/ARCHITECTURE_REFERENCE.md` - Technical details

**Configuration**:
- `config.py` - All environment variables documented
- `local.settings.example.json` - Complete template

**Testing Endpoints**:
- `/api/health` - System health check
- `/api/db/schema/redeploy` - Schema deployment
- `/api/jobs/submit/hello_world` - Test job submission
- `/api/jobs/status/{job_id}` - Job status check

---

## 10. Next Steps

1. **Immediate**: Review this assessment with work IT/Azure admins
2. **Planning**: Get approval for Azure resource creation
3. **Phase 1**: Push code to GitHub (can do today)
4. **Phase 2**: Clone to work machine and test locally
5. **Phase 3**: Deploy to work Azure after resources created

**Estimated Timeline**:
- Phase 1 (GitHub): 1 hour
- Phase 2 (Work setup): 2-4 hours
- Phase 3 (Azure deployment): 4-8 hours (depends on resource creation approval)

**Total**: 1-2 days (excluding approval wait time)

---

*For questions or issues during migration, refer to this guide and the referenced documentation files.*