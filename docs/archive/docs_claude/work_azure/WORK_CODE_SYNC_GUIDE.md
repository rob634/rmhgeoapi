# Work Code Sync Guide - QA Environment Already Deployed

**Date**: 15 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Sync codebase from personal Mac → GitHub → Work VS Code → Work ADO

---

## Situation

✅ **Work QA environment fully deployed** (Function App, PostgreSQL, Service Bus, Storage)
✅ **ADO pipeline configured and green**
🔄 **Need to sync latest codebase** from personal Mac to work environment

This is a **code migration only** - no infrastructure setup needed!

---

## Quick Assessment Answers

### 1. Environment Variables: ✅ EXCELLENT
- **Centralized**: [config.py](../config.py) with Pydantic v2
- **Template**: [local.settings.example.json](../local.settings.example.json)
- **Work Azure**: Just update values in work Function App settings (already done if green)

### 2. Minimum Viable CoreMachine Package
**For testing core orchestration**: ~35 core files
**For full functionality**: All 195 Python files

Since QA is already deployed, you likely want **full functionality** (all files).

### 3. Migration Path
**SIMPLIFIED** - Only 2 steps since QA exists:
1. Personal Mac → GitHub (push latest code)
2. GitHub → Work VS Code → ADO pipeline (pull, configure, deploy)

---

## Step-by-Step Code Sync

### Step 1: Personal Mac → GitHub (30 minutes)

**Current location**: `/Users/robertharrison/python_builds/rmhgeoapi`

1. **Verify current state**:
   ```bash
   cd /Users/robertharrison/python_builds/rmhgeoapi
   git status
   git branch  # Should be on 'dev'
   ```

2. **Commit all current work**:
   ```bash
   git add -A
   git commit -m "QA migration - sync latest codebase to work environment

   🔧 Complete codebase ready for work QA deployment
   ✅ 195 Python files with full functionality
   ✅ CoreMachine orchestration engine (core/)
   ✅ STAC API v1.0.0 (stac_api/)
   ✅ OGC Features API (ogc_features/)
   ✅ Vector ETL with 2.5M row support
   ✅ Raster processing with COG conversion
   ✅ Platform layer for DDH integration

   📋 Environment variables centralized in config.py
   📚 Complete documentation in docs_claude/

   🤖 Generated with [Claude Code](https://claude.com/claude-code)

   Co-Authored-By: Claude <noreply@anthropic.com>"
   ```

3. **Check GitHub remote**:
   ```bash
   git remote -v
   # Should show: origin https://github.com/<username>/rmhgeoapi.git

   # If no remote exists, add it:
   # git remote add origin https://github.com/<username>/rmhgeoapi.git
   ```

4. **Push to GitHub**:
   ```bash
   # Push dev branch (active development)
   git push origin dev

   # Optional: Merge to master if this is a stable checkpoint
   git checkout master
   git merge dev
   git push origin master
   git checkout dev
   ```

5. **Verify on GitHub**:
   - Go to https://github.com/<username>/rmhgeoapi
   - Check that `dev` branch has latest commit
   - Verify all files are present (195 .py files)
   - Check `docs_claude/` folder is complete

**Checkpoint**: ✅ Code is now on GitHub

---

### Step 2: GitHub → Work VS Code (1-2 hours)

**On work machine**:

1. **Clone repository** (if not already done):
   ```bash
   # Navigate to work projects folder
   cd ~/projects  # or wherever you keep code

   # Clone from GitHub
   git clone https://github.com/<username>/rmhgeoapi.git
   cd rmhgeoapi

   # Checkout dev branch
   git checkout dev
   ```

2. **If already cloned, pull latest**:
   ```bash
   cd ~/projects/rmhgeoapi  # or your path
   git checkout dev
   git pull origin dev
   ```

3. **Verify file count**:
   ```bash
   find . -name "*.py" -type f | wc -l
   # Should show: 195
   ```

4. **Check ADO pipeline configuration**:
   ```bash
   # Should exist at root
   ls azure-pipelines.yml

   # If doesn't exist, you'll need to create it (see below)
   ```

**Checkpoint**: ✅ Latest code is on work machine

---

### Step 3: Configure ADO Pipeline (if not already done)

**Check if pipeline exists** in Azure DevOps:
1. Go to work Azure DevOps project
2. Navigate to Pipelines
3. Look for existing pipeline for this repo

**If pipeline already exists and is green**: Skip to Step 4!

**If pipeline needs creation**:

Create `azure-pipelines.yml` at repository root:

```yaml
# Azure Pipelines configuration for rmhgeoapi QA deployment
# Deploys Python 3.12 Function App to work Azure environment

trigger:
  branches:
    include:
      - dev      # Auto-deploy dev branch to QA
      - master   # Auto-deploy master to production (if configured)

pool:
  vmImage: 'ubuntu-latest'

variables:
  pythonVersion: '3.12'
  functionAppName: '<work-qa-function-app-name>'  # UPDATE THIS
  azureSubscription: '<work-service-connection>'  # UPDATE THIS
  resourceGroup: '<work-resource-group>'          # UPDATE THIS

stages:
- stage: Build
  displayName: 'Build Python Function App'
  jobs:
  - job: BuildJob
    displayName: 'Build and Package'
    steps:
    - task: UsePythonVersion@0
      inputs:
        versionSpec: '$(pythonVersion)'
      displayName: 'Use Python $(pythonVersion)'

    - script: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
      displayName: 'Install Python dependencies'

    - task: ArchiveFiles@2
      inputs:
        rootFolderOrFile: '$(System.DefaultWorkingDirectory)'
        includeRootFolder: false
        archiveType: 'zip'
        archiveFile: '$(Build.ArtifactStagingDirectory)/$(Build.BuildId).zip'
        replaceExistingArchive: true
      displayName: 'Archive Function App files'

    - publish: '$(Build.ArtifactStagingDirectory)/$(Build.BuildId).zip'
      artifact: drop
      displayName: 'Publish build artifact'

- stage: Deploy
  displayName: 'Deploy to Azure Function App'
  dependsOn: Build
  condition: succeeded()
  jobs:
  - deployment: DeployJob
    displayName: 'Deploy to QA'
    environment: 'QA'  # Create this environment in ADO if needed
    strategy:
      runOnce:
        deploy:
          steps:
          - task: AzureFunctionApp@1
            inputs:
              azureSubscription: '$(azureSubscription)'
              appType: 'functionAppLinux'
              appName: '$(functionAppName)'
              package: '$(Pipeline.Workspace)/drop/$(Build.BuildId).zip'
              runtimeStack: 'PYTHON|3.12'
              deploymentMethod: 'zipDeploy'
            displayName: 'Deploy to Azure Function App'

          - script: |
              echo "Deployment completed successfully!"
              echo "Function App: https://$(functionAppName).azurewebsites.net"
            displayName: 'Post-deployment message'
```

**Update these variables**:
- `functionAppName`: Your work QA Function App name
- `azureSubscription`: ADO service connection name
- `resourceGroup`: Work resource group name

**Commit pipeline file**:
```bash
git add azure-pipelines.yml
git commit -m "Add ADO pipeline configuration for QA deployment"
git push origin dev
```

**Checkpoint**: ✅ ADO pipeline configured

---

### Step 4: Set Up ADO Service Connection (if needed)

**Check if service connection exists**:
1. Go to Azure DevOps project settings
2. Navigate to Service Connections
3. Look for connection to work Azure subscription

**If doesn't exist, create it**:
1. Click "New service connection"
2. Select "Azure Resource Manager"
3. Choose "Service principal (automatic)"
4. Select work subscription
5. Scope to resource group (recommended)
6. Name it (e.g., "work-azure-qa")
7. Grant permissions to Function App

**Update pipeline** with service connection name:
```yaml
azureSubscription: 'work-azure-qa'  # Match service connection name
```

**Checkpoint**: ✅ Service connection configured

---

### Step 5: Configure Function App Environment Variables

**These should already be set** if QA is green, but verify:

**Via Azure Portal**:
1. Go to work Function App
2. Settings → Configuration → Application settings
3. Verify these critical variables exist:

```
STORAGE_ACCOUNT_NAME=<work-storage>
POSTGIS_HOST=<work-postgres>.postgres.database.azure.com
POSTGIS_USER=<work-db-user>
POSTGIS_PASSWORD=<work-password>
POSTGIS_DATABASE=<work-database>
SERVICE_BUS_NAMESPACE=<work-servicebus>
SERVICE_BUS_CONNECTION_STRING=<work-connection-string>
```

**Via Azure CLI** (to bulk set):
```bash
az functionapp config appsettings set \
  --name <work-function-app> \
  --resource-group <work-resource-group> \
  --settings \
    STORAGE_ACCOUNT_NAME=<work-storage> \
    POSTGIS_HOST=<work-postgres>.postgres.database.azure.com \
    POSTGIS_USER=<work-db-user> \
    POSTGIS_PASSWORD=<work-password> \
    POSTGIS_DATABASE=<work-database> \
    SERVICE_BUS_NAMESPACE=<work-servicebus> \
    # ... etc
```

**Or use ADO pipeline variables** (recommended for secrets):
1. In ADO pipeline, go to Variables
2. Add secrets as "secret" variables
3. Reference in pipeline: `$(POSTGIS_PASSWORD)`

**Checkpoint**: ✅ Environment variables configured

---

### Step 6: Deploy via ADO Pipeline

**Trigger deployment**:

**Option A - Automatic** (if trigger configured):
```bash
# Just push to dev branch
git push origin dev
# Pipeline will auto-trigger
```

**Option B - Manual**:
1. Go to Azure DevOps → Pipelines
2. Select your pipeline
3. Click "Run pipeline"
4. Select branch: `dev`
5. Click "Run"

**Monitor deployment**:
1. Watch pipeline logs in ADO
2. Check for build errors
3. Verify deployment succeeds
4. Note Function App URL from logs

**Checkpoint**: ✅ Code deployed to work QA

---

### Step 7: Verify Deployment

**Run post-deployment tests**:

```bash
# 1. Health check
curl https://<work-function-app>.azurewebsites.net/api/health

# Expected: {"status": "ok", "components": {...}}

# 2. Redeploy database schema (if schema changed)
curl -X POST https://<work-function-app>.azurewebsites.net/api/db/schema/redeploy?confirm=yes

# Expected: {"message": "Schema redeployed successfully"}

# 3. Submit test job
curl -X POST https://<work-function-app>.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "work QA test", "n": 3}'

# Expected: {"job_id": "...", "status": "queued", ...}

# 4. Check job status (replace {JOB_ID})
curl https://<work-function-app>.azurewebsites.net/api/jobs/status/{JOB_ID}

# Expected: {"status": "completed", "result": {...}}

# 5. Query database
curl https://<work-function-app>.azurewebsites.net/api/db/jobs?limit=5

# Expected: Array of recent jobs
```

**Check Application Insights**:
1. Go to work Function App → Application Insights
2. Check for errors in last 30 minutes
3. Verify requests are being logged

**Checkpoint**: ✅ Deployment verified and working

---

## Ongoing Workflow

After initial sync, use this workflow:

### Personal Mac (Development)
```bash
# Make changes
# Test locally with: func start

# Commit to dev branch
git add -A
git commit -m "Feature: description"
git push origin dev
```

### ADO Pipeline (Automatic)
- Detects push to `dev` branch
- Builds Python Function App
- Deploys to work QA automatically
- Sends notification (if configured)

### Work VS Code (Optional)
```bash
# Pull latest if you want to work from work machine
git pull origin dev

# Test locally
func start

# Push changes
git add -A
git commit -m "Fix: description"
git push origin dev
# Triggers ADO pipeline automatically
```

---

## Environment Variable Checklist

**Critical variables** (verify in work Function App):

**Azure Storage**:
- [ ] STORAGE_ACCOUNT_NAME
- [ ] BRONZE_CONTAINER_NAME
- [ ] SILVER_CONTAINER_NAME
- [ ] GOLD_CONTAINER_NAME

**PostgreSQL**:
- [ ] POSTGIS_HOST
- [ ] POSTGIS_PORT
- [ ] POSTGIS_USER
- [ ] POSTGIS_PASSWORD (or USE_MANAGED_IDENTITY=true)
- [ ] POSTGIS_DATABASE
- [ ] POSTGIS_SCHEMA
- [ ] APP_SCHEMA

**Service Bus**:
- [ ] SERVICE_BUS_NAMESPACE
- [ ] SERVICE_BUS_CONNECTION_STRING (for local) or managed identity
- [ ] SERVICE_BUS_JOBS_QUEUE
- [ ] SERVICE_BUS_TASKS_QUEUE

**Application**:
- [ ] FUNCTION_TIMEOUT_MINUTES
- [ ] LOG_LEVEL
- [ ] ENABLE_DATABASE_HEALTH_CHECK

**See [config.py](../config.py) lines 660-1566 for complete list**

---

## Troubleshooting

### Pipeline fails with "Module not found"
**Solution**: Check `requirements.txt` is at repository root
```bash
ls requirements.txt
pip install -r requirements.txt  # Test locally
```

### Health endpoint returns 500
**Solution**: Check Application Insights for error details
```bash
# Check environment variables are set
az functionapp config appsettings list \
  --name <work-function-app> \
  --resource-group <work-resource-group>
```

### Database connection fails
**Solution**: Verify PostgreSQL firewall allows Azure services
```bash
# Add Azure services to firewall
az postgres flexible-server firewall-rule create \
  --resource-group <work-resource-group> \
  --name <work-postgres> \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

### Service Bus connection fails
**Solution**: Verify connection string or managed identity permissions
```bash
# Grant Service Bus Data Sender role
az role assignment create \
  --assignee <function-app-identity-id> \
  --role "Azure Service Bus Data Sender" \
  --scope /subscriptions/<subscription>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<namespace>
```

---

## Success Criteria

Migration is successful when:

✅ Code pushed to GitHub (both `dev` and `master` branches)
✅ Work VS Code has latest code
✅ ADO pipeline runs successfully
✅ Function App deployment completes
✅ Health endpoint returns OK
✅ Test job completes successfully
✅ Database queries work
✅ Application Insights shows no errors

---

## Quick Reference

**Personal Mac Commands**:
```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
git add -A
git commit -m "Description"
git push origin dev
```

**Work VS Code Commands**:
```bash
cd ~/projects/rmhgeoapi
git pull origin dev
func start  # Test locally
```

**Work Function App URL**:
```
https://<work-function-app>.azurewebsites.net
```

**Key Endpoints**:
- `/api/health` - Health check
- `/api/jobs/submit/hello_world` - Test job
- `/api/db/schema/redeploy` - Schema deployment
- `/api/db/jobs` - Database query

---

## Next Steps

1. **Now**: Push code to GitHub from personal Mac
2. **Work machine**: Pull code and verify file count
3. **ADO**: Trigger pipeline deployment
4. **Verify**: Run test job and check health endpoint
5. **Document**: Update work Function App URL in docs

**Estimated time**: 2-3 hours total

---

*For full environment variable documentation, see [config.py](../config.py). For architecture details, see [CLAUDE_CONTEXT.md](CLAUDE_CONTEXT.md).*