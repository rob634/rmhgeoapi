# Deployment Guide

**Date**: 11 SEP 2025  
**Author**: Robert and Geospatial Claude Legion  
**Purpose**: Complete deployment procedures and monitoring guide

## 🚀 Quick Deployment

### Primary Command
```bash
func azure functionapp publish rmhgeoapibeta --build remote
```

### Post-Deployment Verification
```bash
# 1. Health Check (should return OK with component status)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# 2. Redeploy Database Schema (REQUIRED after code changes!)
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes

# 3. Submit Test Job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "deployment test", "n": 3}'

# 4. Check Job Status (use job_id from step 3)
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# 5. Verify Tasks Created
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

---

## 📊 Azure Resources

### Function App
- **Name**: rmhgeoapibeta
- **URL**: https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net
- **Runtime**: Python 3.12
- **Plan**: Premium (Elastic)
- **Region**: East US

### Database
- **Server**: rmhpgflex.postgres.database.azure.com
- **Database**: postgres
- **Schema**: geo
- **Version**: PostgreSQL 14
- **Extensions**: PostGIS 3.4

### Storage Account
- **Name**: rmhazuregeo
- **Containers**:
  - `rmhazuregeobronze` - Raw input data
  - `rmhazuregeosilver` - Processed data
  - `rmhazuregeogold` - Published datasets (future)
- **Queues**:
  - `geospatial-jobs` - Job orchestration
  - `geospatial-tasks` - Task execution
  - `*-poison` - Failed messages

### Resource Group
- **Name**: rmhazure_rg (NOT rmhresourcegroup)
- **Location**: East US

---

## 🔍 Monitoring & Debugging

### Application Insights Logs

#### Setup Bearer Token
1. Go to Azure Portal → rmhgeoapibeta → Application Insights
2. Navigate to API Access
3. Create API Key with Read telemetry permission
4. Copy the Application ID and API Key

#### Stream Logs via curl
```bash
# Set your credentials
APP_ID="your-application-insights-id"
API_KEY="your-api-key"

# Stream recent logs
curl -H "x-api-key: ${API_KEY}" \
  "https://api.applicationinsights.io/v1/apps/${APP_ID}/events/traces?\$top=100"

# Filter by operation
curl -H "x-api-key: ${API_KEY}" \
  "https://api.applicationinsights.io/v1/apps/${APP_ID}/events/traces?\$filter=operation/name eq 'ProcessJobQueue'"

# Get exceptions
curl -H "x-api-key: ${API_KEY}" \
  "https://api.applicationinsights.io/v1/apps/${APP_ID}/events/exceptions?\$top=50"
```

#### Using Azure CLI
```bash
# Login to Azure
az login

# Set subscription
az account set --subscription "your-subscription-id"

# Stream live logs
az webapp log tail --name rmhgeoapibeta --resource-group rmhazure_rg

# Download logs
az webapp log download --name rmhgeoapibeta --resource-group rmhazure_rg --log-file webapp_logs.zip
```

---

## 🗄️ Database Management

### Schema Management Endpoints

#### Redeploy Schema (Recommended)
```bash
# Drops and recreates all tables, enums, and functions
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

#### Nuclear Option - Drop Everything
```bash
# WARNING: Destroys all data!
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/nuke?confirm=yes
```

### Database Query Endpoints

#### Get All Jobs
```bash
# Basic query
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs

# With filters
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?status=failed&limit=10"

# Recent jobs (last 24 hours)
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?hours=24"
```

#### Get Tasks for Job
```bash
# All tasks for a specific job
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}

# Failed tasks only
curl "https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks?status=failed"
```

#### Database Statistics
```bash
# Get counts and health metrics
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Test PostgreSQL functions
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/functions/test

# Check enum types
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/enums/diagnostic
```

#### Comprehensive Debug Dump
```bash
# Get all jobs and tasks in one call
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/debug/all?limit=100
```

---

## 🔧 Local Development Setup

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
    "STORAGE_ACCOUNT_NAME": "rmhazuregeo",
    "STORAGE_ACCOUNT_KEY": "[REDACTED - See Azure Portal or Key Vault for actual key]",
    "POSTGRES_HOST": "rmhpgflex.postgres.database.azure.com",
    "POSTGRES_DB": "postgres",
    "POSTGRES_USER": "your_username",
    "POSTGRES_PASSWORD": "your_password",
    "POSTGRES_SCHEMA": "geo"
  }
}
```

### Run Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Start function app
func start

# Test local endpoint
curl http://localhost:7071/api/health
```

---

## 🚨 Troubleshooting

### Common Issues

#### 1. Jobs Stuck in QUEUED
**Check**: Queue connection and poison queue
```bash
# Check poison queue
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/monitor/poison

# Check queue metrics
az storage queue show --name geospatial-jobs --account-name rmhazuregeo
```

#### 2. Tasks Not Completing
**Check**: Database transactions and logs
```bash
# Get task details
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}

# Check Application Insights for errors
az webapp log tail --name rmhgeoapibeta --resource-group rmhazure_rg
```

#### 3. Schema Mismatch Errors
**Solution**: Redeploy schema
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

#### 4. Import Errors
**Check**: Health endpoint for module status
```bash
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

---

## 📋 Deployment Checklist

### Pre-Deployment
- [ ] Run tests locally with `func start`
- [ ] Verify all environment variables in Azure Portal
- [ ] Check resource group and subscription

### Deployment
- [ ] Run deployment command: `func azure functionapp publish rmhgeoapibeta --build remote`
- [ ] Wait for "Deployment successful" message
- [ ] Check deployment logs for errors

### Post-Deployment
- [ ] Run health check endpoint
- [ ] Redeploy database schema
- [ ] Submit test job
- [ ] Verify job completes successfully
- [ ] Check Application Insights for errors

### Rollback Procedure
```bash
# If deployment fails, restore previous version
az functionapp deployment list-publishing-profiles \
  --name rmhgeoapibeta \
  --resource-group rmhazure_rg

# Redeploy specific version
az functionapp deployment source config-zip \
  --resource-group rmhazure_rg \
  --name rmhgeoapibeta \
  --src previous_deployment.zip
```

---

## 🔐 Security Notes

### Managed Identity
- Function App uses managed identity for storage access
- No connection strings in code
- RBAC permissions configured in Azure Portal

### Key Vault (Future)
- Currently disabled, using environment variables
- Will store PostgreSQL credentials
- Requires RBAC setup completion

### Storage Access
```
Account: rmhazuregeo
Key: [REDACTED - See Azure Portal or Key Vault for actual key]
```
**Note**: This key is for development only. Production will use managed identity.

---

## ⚠️ Critical Warnings

1. **NEVER** deploy to deprecated apps (rmhazurefn, rmhgeoapi, rmhgeoapifn)
2. **ALWAYS** redeploy schema after code changes affecting models
3. **NEVER** use production credentials in local development
4. **ALWAYS** check poison queues after deployment

---

*For architecture details, see ARCHITECTURE_REFERENCE.md. For current issues, see TODO_ACTIVE.md.*