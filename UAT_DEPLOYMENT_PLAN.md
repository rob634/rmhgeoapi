# UAT Deployment Plan - Geospatial ETL Platform

**Created**: 20 JAN 2026
**Purpose**: Comprehensive from-scratch deployment guide for UAT environment
**Lessons Learned From**: DEV and QA deployments

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Access Zones](#2-access-zones)
3. [Component Inventory](#3-component-inventory)
4. [Managed Identities](#4-managed-identities)
5. [CI/CD Pipeline Patterns](#5-cicd-pipeline-patterns)
6. [Phase 1: Azure Resource Provisioning](#phase-1-azure-resource-provisioning)
7. [Phase 2: Managed Identities & RBAC](#phase-2-managed-identities--rbac)
8. [Phase 3: PostgreSQL Setup](#phase-3-postgresql-setup)
9. [Phase 4: Storage Accounts](#phase-4-storage-accounts)
10. [Phase 5: Service Bus](#phase-5-service-bus)
11. [Phase 6: Platform App Deployment](#phase-6-platform-app-deployment)
12. [Phase 7: Orchestrator App Deployment](#phase-7-orchestrator-app-deployment)
13. [Phase 8: Function Worker Deployment](#phase-8-function-worker-deployment)
14. [Phase 9: Docker Worker Deployment](#phase-9-docker-worker-deployment)
15. [Phase 10: Internal Service Layer Deployment](#phase-10-internal-service-layer-deployment)
16. [Phase 11: Azure Data Factory](#phase-11-azure-data-factory)
17. [Phase 12: External Environment](#phase-12-external-environment)
18. [Phase 13: Post-Deployment Validation](#phase-13-post-deployment-validation)
19. [Environment Variables Reference](#environment-variables-reference)
20. [Troubleshooting](#troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    ETL PIPELINES (B2B)                                               │
│                                                                                                      │
│  ┌─────────────────────────────┐                                                                    │
│  │  PLATFORM (Function App)    │  HTTP Triggers, B2B Auth (Managed Identity)                        │
│  │  • Anti-corruption layer    │  Translates external params → CoreMachine params                        │
│  │  • Request tracking         │  Writes to: geospatial-jobs queue                                  │
│  └─────────────┬───────────────┘                                                                    │
│                │ geospatial-jobs queue                                                              │
│                ▼                                                                                    │
│  ┌─────────────────────────────┐                                                                    │
│  │  ORCHESTRATOR (Function App)│  Jobs Queue Consumer                                               │
│  │  • CoreMachine              │  Job state, stage transitions, task routing                        │
│  │  • Task routing             │  Writes to: task queues                                            │
│  │  • ADF trigger              │  Triggers promotion to External                                    │
│  └─────────────┬───────────────┘                                                                    │
│                │                                                                                    │
│       ┌────────┴────────┐                                                                           │
│       ▼                 ▼                                                                           │
│  ┌─────────────┐  ┌─────────────┐                                                                   │
│  │  FUNCTION   │  │   DOCKER    │                                                                   │
│  │  WORKER     │  │   WORKER    │                                                                   │
│  │             │  │             │                                                                   │
│  │ Lightweight │  │ GDAL Full   │                                                                   │
│  │ DB ops,     │  │ Nearly ALL  │                                                                   │
│  │ parallel    │  │ geospatial  │                                                                   │
│  │             │  │ ETL         │                                                                   │
│  └──────┬──────┘  └──────┬──────┘                                                                   │
│         │                │                                                                          │
│         └────────┬───────┘                                                                          │
│                  │                                                                                  │
│         READ     │     WRITE                                                                        │
│           ┌──────┴──────┐                                                                           │
│           ▼             ▼                                                                           │
│  ┌─────────────┐  ┌─────────────┐         ┌─────────────────────────────────────────────────────┐  │
│  │   BRONZE    │  │   SILVER    │         │              INTERNAL DATABASE                       │  │
│  │  STORAGE    │  │  STORAGE    │         │  ┌─────────┬──────────┬─────────┐                   │  │
│  │ (raw data)  │  │  (COGs)     │         │  │   app   │  pgstac  │   geo   │                   │  │
│  └─────────────┘  └──────┬──────┘         │  │ (orch)  │  (STAC)  │(PostGIS)│                   │  │
│                          │                │  └─────────┴──────────┴─────────┘                   │  │
│                          │                └─────────────────────────────────────────────────────┘  │
└──────────────────────────┼──────────────────────────────────────────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              INTERNAL SERVICE LAYER (B2C Internal)                                   │
│                                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │  SERVICE LAYER APP (Docker Web App in ASE)                                                   │    │
│  │                                                                                              │    │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                              │    │
│  │  │     TiTiler     │  │      TiPG       │  │   STAC API      │                              │    │
│  │  │                 │  │                 │  │   (B2C)         │                              │    │
│  │  │ • COG tiles     │  │ • Vector API    │  │                 │                              │    │
│  │  │ • Search        │  │ • Vector tiles  │  │ • Curated       │                              │    │
│  │  │ • xarray        │  │                 │  │   metadata only │                              │    │
│  │  │                 │  │                 │  │ • No app state  │                              │    │
│  │  │                 │  │                 │  │ • No internal   │                              │    │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘                              │    │
│  │                                                                                              │    │
│  │  READ-ONLY: Silver Storage, Internal DB (pgstac + geo schemas only)                         │    │
│  │  NO ACCESS: app schema, Bronze Storage, Service Bus                                         │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                              │                                                       │
│                                              ▼                                                       │
│                                       B2C Internal Users                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘

                                              │
                              ┌───────────────┴───────────────┐
                              │   AZURE DATA FACTORY          │
                              │   (Triggered by Orchestrator) │
                              │                               │
                              │   • Silver → External Storage │
                              │   • Internal DB → External DB │
                              │   • Audit trails              │
                              └───────────────┬───────────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SERVICE LAYER (B2C External)                                   │
│                                              AIRGAPPED                                                │
│                                                                                                      │
│  ┌──────────────────────┐    ┌──────────────────────────────────────────────────────────────────┐   │
│  │  EXTERNAL STORAGE    │    │  EXTERNAL DATABASE                                                │   │
│  │  (airgapped copy)    │    │  ┌──────────┬─────────┐                                          │   │
│  │                      │    │  │  pgstac  │   geo   │  (NO app schema - external doesn't need) │   │
│  └──────────┬───────────┘    │  └──────────┴─────────┘                                          │   │
│             │                └──────────────────────────────────────────────────────────────────┘   │
│             │                                    │                                                   │
│             └────────────────┬───────────────────┘                                                   │
│                              ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │  SERVICE LAYER APP (Docker Web App in ASE) - SAME IMAGE AS INTERNAL                         │    │
│  │                                                                                              │    │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                              │    │
│  │  │     TiTiler     │  │      TiPG       │  │   STAC API      │                              │    │
│  │  │ • COG tiles     │  │ • Vector API    │  │   (B2C)         │                              │    │
│  │  │ • Search        │  │ • Vector tiles  │  │ • Curated       │                              │    │
│  │  │ • xarray        │  │                 │  │   metadata      │                              │    │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘                              │    │
│  │                                                                                              │    │
│  │  READ-ONLY: External Storage, External DB (pgstac + geo schemas only)                       │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                              │                                                       │
│                                              ▼                                                       │
│                                       B2C External Users                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Access Zones

| Zone | Type | Purpose | Components |
|------|------|---------|------------|
| **ETL Pipelines** | B2B | Data processing, job orchestration | Platform, Orchestrator, Workers |
| **Internal Service Layer** | B2C Internal | Internal user data access | Service Layer App (internal instance) |
| **External Service Layer** | B2C External | External user data access (airgapped) | Service Layer App (external instance) |

---

## 3. Component Inventory

### ETL Pipeline Apps

| App | Type | Image Source | Queue Access | Purpose |
|-----|------|--------------|--------------|---------|
| **Platform** | Function App | ACR (func publish) | WRITE: `geospatial-jobs` | B2B HTTP, anti-corruption layer |
| **Orchestrator** | Function App | ACR (func publish) | READ: `geospatial-jobs`, WRITE: task queues | CoreMachine, job/task orchestration |
| **Function Worker** | Function App | ACR (func publish) | READ: `function-tasks` | Lightweight parallelizable DB ops |
| **Docker Worker** | Container App | JFROG Artifactory | READ: `docker-tasks` | GDAL full, nearly all geospatial ETL |

### Service Layer Apps

| App | Type | Image Source | Queue Access | Purpose |
|-----|------|--------------|--------------|---------|
| **Internal Service Layer** | Docker Web App (ASE) | JFROG Artifactory | NONE | TiTiler + TiPG + STAC API (B2C) |
| **External Service Layer** | Docker Web App (ASE) | JFROG Artifactory | NONE | Same image, airgapped environment |

### Data Movement

| Component | Type | Purpose |
|-----------|------|---------|
| **Azure Data Factory** | ADF Pipeline | Silver → External promotion (storage + database) |

### Azure Resources Summary

| Resource | Count | Notes |
|----------|-------|-------|
| Resource Groups | 2 | Internal + External |
| PostgreSQL Flexible Servers | 2 | Internal (full) + External (pgstac, geo only) |
| Storage Accounts | 4 | Bronze, Silver, External, (Gold optional) |
| Service Bus Namespace | 1 | Shared by ETL pipeline |
| Function Apps | 3 | Platform, Orchestrator, Function Worker |
| Container Apps | 1 | Docker Worker |
| App Service Environment | 1 | Hosts Service Layer Docker apps |
| Web Apps (Docker) | 2 | Internal + External Service Layer |
| Azure Data Factory | 1 | Data promotion pipelines |
| Application Insights | 2 | Internal + External monitoring |

---

## 4. Managed Identities

### Identity Matrix

| Identity | Used By | Database Access | Storage Access | Service Bus |
|----------|---------|-----------------|----------------|-------------|
| `internal-db-admin` | Platform, Orchestrator, Workers | WRITE internal (app, pgstac, geo) | READ bronze, WRITE silver | YES |
| `internal-db-reader` | Internal Service Layer | READ internal (pgstac, geo only) | READ silver | NO |
| `external-db-admin` | Azure Data Factory | WRITE external (pgstac, geo) | WRITE external | NO |
| `external-db-reader` | External Service Layer | READ external (pgstac, geo only) | READ external | NO |

### Identity Details

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  internal-db-admin (User-Assigned Managed Identity)                                  │
│                                                                                      │
│  Assigned To:                                                                        │
│    • Platform Function App                                                           │
│    • Orchestrator Function App                                                       │
│    • Function Worker Function App                                                    │
│    • Docker Worker Container App                                                     │
│                                                                                      │
│  Permissions:                                                                        │
│    • PostgreSQL: Full access to app, pgstac, geo, h3 schemas                        │
│    • Storage: Storage Blob Data Contributor on Bronze + Silver                       │
│    • Service Bus: Azure Service Bus Data Owner                                       │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  internal-db-reader (User-Assigned Managed Identity)                                 │
│                                                                                      │
│  Assigned To:                                                                        │
│    • Internal Service Layer Docker Web App                                           │
│                                                                                      │
│  Permissions:                                                                        │
│    • PostgreSQL: SELECT only on pgstac + geo schemas (NO app schema)                │
│    • Storage: Storage Blob Data Reader on Silver                                     │
│    • Service Bus: NONE                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  external-db-admin (User-Assigned Managed Identity)                                  │
│                                                                                      │
│  Assigned To:                                                                        │
│    • Azure Data Factory                                                              │
│                                                                                      │
│  Permissions:                                                                        │
│    • PostgreSQL: Full access to pgstac + geo schemas on External DB                 │
│    • Storage: Storage Blob Data Contributor on External Storage                      │
│    • Service Bus: NONE                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  external-db-reader (User-Assigned Managed Identity)                                 │
│                                                                                      │
│  Assigned To:                                                                        │
│    • External Service Layer Docker Web App                                           │
│                                                                                      │
│  Permissions:                                                                        │
│    • PostgreSQL: SELECT only on pgstac + geo schemas on External DB                 │
│    • Storage: Storage Blob Data Reader on External Storage                           │
│    • Service Bus: NONE                                                               │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. CI/CD Pipeline Patterns

All deployments go through Azure DevOps (ADO) pipelines. There are two distinct patterns:

### 5.1 Docker Web App Deployment (Service Layer, Docker Worker)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  DOCKER WEB APP CI/CD FLOW                                                          │
│                                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   VS Code    │───▶│   ADO Repo   │───▶│ ADO CI       │───▶│ ADO Release  │      │
│  │              │    │              │    │ Pipeline     │    │ (Auto)       │      │
│  │  Code edits  │    │  Git push    │    │  Triggered   │    │  Triggered   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────┬───────┘      │
│                                                                      │              │
│                                                                      ▼              │
│                                          ┌──────────────┐    ┌──────────────┐      │
│                                          │   Web App    │◀───│  ACR Build   │      │
│                                          │   Updated    │    │              │      │
│                                          │              │    │  Image built │      │
│                                          └──────────────┘    │  & pushed    │      │
│                                                              └──────────────┘      │
│                                                                      ▲              │
│                                                                      │              │
│                                          ┌───────────────────────────┴────────────┐│
│                                          │  Dockerfile references base image from ││
│                                          │  JFROG Artifactory:                    ││
│                                          │  <JFROG_REGISTRY>                       ││
│                                          │  -virtual/ubuntu-full:3.10.1           ││
│                                          └────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Steps:**

1. **VS Code** → Developer makes code changes locally
2. **Git Push** → Push to Azure DevOps repository
3. **CI Pipeline** → Automatically triggered on push
   - Validates code
   - Runs any build steps
4. **Release Pipeline** → Automatically triggered when CI succeeds
   - Builds Docker image using ACR
   - Dockerfile references JFROG base image
   - Pushes to Azure Container Registry
5. **Web App** → Pulls new image and restarts

**Key Configuration:**

```dockerfile
# Dockerfile references JFROG base image
FROM <JFROG_REGISTRY>/ubuntu-full:3.10.1

# ... rest of Dockerfile
```

**ADO Pipeline YAML (Conceptual):**

```yaml
# azure-pipelines.yml (CI)
trigger:
  branches:
    include:
      - main
      - release/*

stages:
  - stage: Build
    jobs:
      - job: BuildAndTest
        steps:
          - task: Docker@2
            inputs:
              containerRegistry: 'jfrog-connection'
              repository: 'geoetl-servicelayer'
              command: 'build'
              Dockerfile: 'Dockerfile.servicelayer'

  - stage: Release
    dependsOn: Build
    condition: succeeded()
    jobs:
      - deployment: DeployToWebApp
        environment: 'UAT'
        strategy:
          runOnce:
            deploy:
              steps:
                - task: AzureWebAppContainer@1
                  inputs:
                    azureSubscription: '$(azureSubscription)'
                    appName: 'app-servicelayer-uat-internal'
                    containers: '$(acrLoginServer)/geoetl-servicelayer:$(Build.BuildId)'
```

### 5.2 Azure Function App Deployment

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  AZURE FUNCTION APP CI/CD FLOW                                                      │
│                                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   VS Code    │───▶│   ADO Repo   │───▶│ ADO Pipeline │───▶│ Function App │      │
│  │              │    │              │    │              │    │   Updated    │      │
│  │  Code edits  │    │  Git push    │    │  Build &     │    │              │      │
│  │              │    │              │    │  Deploy      │    │              │      │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                      │              │
│                                                                      ▼              │
│                                                              ┌──────────────┐      │
│                                                              │ Azure Portal │      │
│                                                              │ Deployment   │      │
│                                                              │ Logs         │      │
│                                                              │              │      │
│                                                              │ (Monitor     │      │
│                                                              │  progress)   │      │
│                                                              └──────────────┘      │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Steps:**

1. **VS Code** → Developer makes code changes locally
2. **Git Push** → Push to Azure DevOps repository
3. **ADO Pipeline** → Automatically triggered
   - Builds Python package
   - Deploys to Function App using Azure Functions Core Tools or Zip Deploy
4. **Monitor** → Check deployment logs in Azure Portal
   - Navigate to Function App → Deployment Center → Logs
   - Wait for deployment to complete

**ADO Pipeline YAML (Conceptual):**

```yaml
# azure-pipelines.yml (Function App)
trigger:
  branches:
    include:
      - main
      - release/*

variables:
  pythonVersion: '3.12'
  functionAppName: 'func-platform-uat'

stages:
  - stage: Build
    jobs:
      - job: BuildPackage
        steps:
          - task: UsePythonVersion@0
            inputs:
              versionSpec: '$(pythonVersion)'

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

  - stage: Deploy
    dependsOn: Build
    jobs:
      - deployment: DeployToFunctionApp
        environment: 'UAT'
        strategy:
          runOnce:
            deploy:
              steps:
                - task: AzureFunctionApp@2
                  inputs:
                    azureSubscription: '$(azureSubscription)'
                    appType: 'functionAppLinux'
                    appName: '$(functionAppName)'
                    package: '$(Pipeline.Workspace)/**/*.zip'
                    runtimeStack: 'PYTHON|3.12'
```

### 5.3 Deployment Comparison

| Aspect | Docker Web App | Azure Function App |
|--------|---------------|-------------------|
| **Source** | VS Code | VS Code |
| **Repository** | ADO Repo | ADO Repo |
| **CI Pipeline** | Yes (build image) | Yes (build package) |
| **Release Pipeline** | Yes (separate, auto-triggered) | Combined with CI |
| **Build Artifact** | Docker image in ACR | Zip package |
| **Base Image** | JFROG Artifactory | Azure Functions runtime |
| **Deployment Target** | Web App for Containers | Function App |
| **Monitoring** | Container logs | Deployment Center logs |

### 5.4 Monitoring Deployments

**Function App Deployment:**
```
Azure Portal → Function App → Deployment Center → Logs
```

**Docker Web App Deployment:**
```
Azure Portal → Web App → Deployment Center → Logs
  or
ADO → Pipelines → Releases → [Release Name] → Logs
```

### 5.5 Pre-Deployment Checklist (ADO)

Before first deployment to UAT:

- [ ] ADO Repository created
- [ ] Service connection to Azure subscription configured
- [ ] Service connection to JFROG Artifactory configured (for Docker apps)
- [ ] Service connection to ACR configured (for Docker apps)
- [ ] Pipeline YAML files committed to repo
- [ ] Environment variables configured in pipeline or Azure (App Settings)
- [ ] Branch policies configured (optional: require PR for main)

---

## Phase 1: Azure Resource Provisioning

### 1.1 Create Resource Groups

```bash
# Internal environment (ETL + Internal Service Layer)
az group create \
  --name rg-geoetl-uat-internal \
  --location eastus

# External environment (External Service Layer)
az group create \
  --name rg-geoetl-uat-external \
  --location eastus
```

### 1.2 Create Internal PostgreSQL Flexible Server

```bash
az postgres flexible-server create \
  --resource-group rg-geoetl-uat-internal \
  --name pg-geoetl-uat-internal \
  --location eastus \
  --sku-name Standard_D4s_v3 \
  --storage-size 128 \
  --version 16 \
  --admin-user pgadmin \
  --admin-password '<SECURE_PASSWORD>' \
  --yes

# Enable Azure AD authentication
az postgres flexible-server ad-admin create \
  --resource-group rg-geoetl-uat-internal \
  --server-name pg-geoetl-uat-internal \
  --display-name "AzureAD Admin" \
  --object-id <YOUR_AAD_ADMIN_OBJECT_ID> \
  --type User

# Allow Azure services
az postgres flexible-server firewall-rule create \
  --resource-group rg-geoetl-uat-internal \
  --name pg-geoetl-uat-internal \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Enable extensions
az postgres flexible-server parameter set \
  --resource-group rg-geoetl-uat-internal \
  --server-name pg-geoetl-uat-internal \
  --name azure.extensions \
  --value "POSTGIS,UUID-OSSP,PG_TRGM"
```

### 1.3 Create External PostgreSQL Flexible Server

```bash
az postgres flexible-server create \
  --resource-group rg-geoetl-uat-external \
  --name pg-geoetl-uat-external \
  --location eastus \
  --sku-name Standard_D2s_v3 \
  --storage-size 64 \
  --version 16 \
  --admin-user pgadmin \
  --admin-password '<SECURE_PASSWORD>' \
  --yes

# Enable Azure AD authentication
az postgres flexible-server ad-admin create \
  --resource-group rg-geoetl-uat-external \
  --server-name pg-geoetl-uat-external \
  --display-name "AzureAD Admin" \
  --object-id <YOUR_AAD_ADMIN_OBJECT_ID> \
  --type User

# Allow Azure services
az postgres flexible-server firewall-rule create \
  --resource-group rg-geoetl-uat-external \
  --name pg-geoetl-uat-external \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Enable extensions
az postgres flexible-server parameter set \
  --resource-group rg-geoetl-uat-external \
  --server-name pg-geoetl-uat-external \
  --name azure.extensions \
  --value "POSTGIS,UUID-OSSP"
```

### 1.4 Create Service Bus Namespace

```bash
az servicebus namespace create \
  --resource-group rg-geoetl-uat-internal \
  --name sb-geoetl-uat \
  --location eastus \
  --sku Standard
```

### 1.5 Create Storage Accounts

```bash
# Bronze (raw data - ETL input)
az storage account create \
  --resource-group rg-geoetl-uat-internal \
  --name stageoetluatbronze \
  --location eastus \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false

# Silver (processed COGs - ETL output, Internal Service Layer input)
az storage account create \
  --resource-group rg-geoetl-uat-internal \
  --name stageoetluatsilver \
  --location eastus \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false

# External (airgapped - External Service Layer input)
az storage account create \
  --resource-group rg-geoetl-uat-external \
  --name stageoetluatexternal \
  --location eastus \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false
```

### 1.6 Create Application Insights

```bash
# Internal monitoring
az monitor app-insights component create \
  --resource-group rg-geoetl-uat-internal \
  --app ai-geoetl-uat-internal \
  --location eastus \
  --kind web \
  --application-type web

# External monitoring
az monitor app-insights component create \
  --resource-group rg-geoetl-uat-external \
  --app ai-geoetl-uat-external \
  --location eastus \
  --kind web \
  --application-type web
```

### 1.7 Create Container Apps Environment (for Docker Worker)

```bash
az containerapp env create \
  --resource-group rg-geoetl-uat-internal \
  --name cae-geoetl-uat \
  --location eastus
```

### 1.8 Create App Service Environment (for Service Layer Docker Apps)

```bash
# Note: ASE creation is typically done via Azure Portal or ARM template
# due to VNet requirements. Below is conceptual.

az appservice ase create \
  --resource-group rg-geoetl-uat-internal \
  --name ase-geoetl-uat \
  --vnet-name vnet-geoetl-uat \
  --subnet-name subnet-ase \
  --kind ASEv3

# Create App Service Plan in ASE
az appservice plan create \
  --resource-group rg-geoetl-uat-internal \
  --name asp-servicelayer-uat \
  --app-service-environment ase-geoetl-uat \
  --sku I1V2 \
  --is-linux
```

---

## Phase 2: Managed Identities & RBAC

### 2.1 Create User-Assigned Managed Identities

```bash
# Internal DB Admin (ETL pipeline apps)
az identity create \
  --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin

# Internal DB Reader (Internal Service Layer)
az identity create \
  --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-reader

# External DB Admin (ADF)
az identity create \
  --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-admin

# External DB Reader (External Service Layer)
az identity create \
  --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-reader
```

### 2.2 Capture Identity Details

```bash
# Get all identity details
for MI in mi-geoetl-uat-internal-db-admin mi-geoetl-uat-internal-db-reader; do
  echo "=== $MI ==="
  az identity show --resource-group rg-geoetl-uat-internal --name $MI \
    --query "{name:name, clientId:clientId, principalId:principalId}" -o table
done

for MI in mi-geoetl-uat-external-db-admin mi-geoetl-uat-external-db-reader; do
  echo "=== $MI ==="
  az identity show --resource-group rg-geoetl-uat-external --name $MI \
    --query "{name:name, clientId:clientId, principalId:principalId}" -o table
done
```

### 2.3 Assign RBAC Roles - Storage

```bash
# Get Principal IDs
INTERNAL_ADMIN_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin --query principalId -o tsv)

INTERNAL_READER_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-reader --query principalId -o tsv)

EXTERNAL_ADMIN_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-admin --query principalId -o tsv)

EXTERNAL_READER_PRINCIPAL=$(az identity show --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-reader --query principalId -o tsv)

# Internal DB Admin → Bronze (read) + Silver (read/write)
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $INTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatbronze

az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $INTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatsilver

# Internal DB Reader → Silver (read-only)
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $INTERNAL_READER_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatsilver

# External DB Admin → External Storage (read/write)
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $EXTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-external/providers/Microsoft.Storage/storageAccounts/stageoetluatexternal

# External DB Reader → External Storage (read-only)
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $EXTERNAL_READER_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-external/providers/Microsoft.Storage/storageAccounts/stageoetluatexternal
```

### 2.4 Assign RBAC Roles - Service Bus

```bash
# Only Internal DB Admin needs Service Bus access
az role assignment create \
  --role "Azure Service Bus Data Owner" \
  --assignee $INTERNAL_ADMIN_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.ServiceBus/namespaces/sb-geoetl-uat
```

---

## Phase 3: PostgreSQL Setup

### 3.1 Create Internal Database

Connect as pgadmin to `pg-geoetl-uat-internal`:

```sql
-- Create database
CREATE DATABASE geoetldb;

\c geoetldb

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Verify
SELECT PostGIS_Version();
```

### 3.2 Create Internal Database Users

```sql
-- ============================================================
-- Internal DB Admin (Platform, Orchestrator, Workers)
-- Full access to all schemas
-- ============================================================
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-internal-db-admin', false, false);

GRANT CREATE ON DATABASE geoetldb TO "mi-geoetl-uat-internal-db-admin";
ALTER ROLE "mi-geoetl-uat-internal-db-admin" CREATEROLE;
GRANT USAGE ON SCHEMA public TO "mi-geoetl-uat-internal-db-admin";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "mi-geoetl-uat-internal-db-admin";

-- ============================================================
-- Internal DB Reader (Internal Service Layer)
-- Read-only access to pgstac + geo schemas (NO app schema)
-- ============================================================
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-internal-db-reader', false, false);

-- Note: Schema grants applied AFTER schemas are created by the app
-- See Phase 7 post-deployment step
```

### 3.3 Create External Database

Connect as pgadmin to `pg-geoetl-uat-external`:

```sql
-- Create database
CREATE DATABASE geoetldb;

\c geoetldb

-- Enable extensions (no h3 needed for external)
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verify
SELECT PostGIS_Version();
```

### 3.4 Create External Database Users

```sql
-- ============================================================
-- External DB Admin (Azure Data Factory)
-- Write access to pgstac + geo schemas
-- ============================================================
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-external-db-admin', false, false);

GRANT CREATE ON DATABASE geoetldb TO "mi-geoetl-uat-external-db-admin";
GRANT USAGE ON SCHEMA public TO "mi-geoetl-uat-external-db-admin";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "mi-geoetl-uat-external-db-admin";

-- ============================================================
-- External DB Reader (External Service Layer)
-- Read-only access to pgstac + geo schemas
-- ============================================================
SELECT * FROM pgaadauth_create_principal('mi-geoetl-uat-external-db-reader', false, false);

-- Note: Schema grants applied AFTER ADF creates schemas
```

### 3.5 Verify User Permissions

```sql
-- Internal DB
SELECT rolname, rolcreaterole, rolcanlogin
FROM pg_roles
WHERE rolname LIKE 'mi-geoetl-uat%';

-- Verify CREATE permission
SELECT has_database_privilege('mi-geoetl-uat-internal-db-admin', current_database(), 'CREATE');
```

---

## Phase 4: Storage Accounts

### 4.1 Create Containers

```bash
# Bronze containers (raw data input)
az storage container create --account-name stageoetluatbronze --name bronze-vectors --auth-mode login
az storage container create --account-name stageoetluatbronze --name bronze-rasters --auth-mode login
az storage container create --account-name stageoetluatbronze --name bronze-misc --auth-mode login
az storage container create --account-name stageoetluatbronze --name bronze-temp --auth-mode login

# Silver containers (processed output)
az storage container create --account-name stageoetluatsilver --name silver-cogs --auth-mode login
az storage container create --account-name stageoetluatsilver --name silver-vectors --auth-mode login
az storage container create --account-name stageoetluatsilver --name silver-tiles --auth-mode login
az storage container create --account-name stageoetluatsilver --name silver-temp --auth-mode login
az storage container create --account-name stageoetluatsilver --name pickles --auth-mode login

# External containers (airgapped - mirrors silver structure)
az storage container create --account-name stageoetluatexternal --name cogs --auth-mode login
az storage container create --account-name stageoetluatexternal --name vectors --auth-mode login
az storage container create --account-name stageoetluatexternal --name tiles --auth-mode login
```

### 4.2 Configure CORS for Service Layer

```bash
# Silver storage - for Internal Service Layer
az storage cors add \
  --account-name stageoetluatsilver \
  --services b \
  --methods GET HEAD OPTIONS \
  --origins "*" \
  --allowed-headers "*" \
  --exposed-headers "*" \
  --max-age 3600

# External storage - for External Service Layer
az storage cors add \
  --account-name stageoetluatexternal \
  --services b \
  --methods GET HEAD OPTIONS \
  --origins "*" \
  --allowed-headers "*" \
  --exposed-headers "*" \
  --max-age 3600
```

---

## Phase 5: Service Bus

### 5.1 Create Queues

**CRITICAL**: `maxDeliveryCount` MUST be 1 (retries handled by CoreMachine)

```bash
# Jobs queue (Platform → Orchestrator)
az servicebus queue create \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name geospatial-jobs \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D

# Function Worker task queue
az servicebus queue create \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name function-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D

# Docker Worker task queue
az servicebus queue create \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name docker-tasks \
  --lock-duration PT5M \
  --max-delivery-count 1 \
  --default-message-time-to-live P14D
```

### 5.2 Get Connection String

```bash
az servicebus namespace authorization-rule keys list \
  --resource-group rg-geoetl-uat-internal \
  --namespace-name sb-geoetl-uat \
  --name RootManageSharedAccessKey \
  --query primaryConnectionString -o tsv
```

### 5.3 Verify Queue Settings

```bash
for QUEUE in geospatial-jobs function-tasks docker-tasks; do
  echo "=== $QUEUE ==="
  az servicebus queue show \
    --resource-group rg-geoetl-uat-internal \
    --namespace-name sb-geoetl-uat \
    --name $QUEUE \
    --query "{name:name, lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}" -o table
done
```

---

## Phase 6: Platform App Deployment

### 6.1 Create Function App

```bash
# Create App Service Plan
az appservice plan create \
  --resource-group rg-geoetl-uat-internal \
  --name asp-platform-uat \
  --sku B2 \
  --is-linux

# Create Function App
az functionapp create \
  --resource-group rg-geoetl-uat-internal \
  --name func-platform-uat \
  --plan asp-platform-uat \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --storage-account stageoetluatsilver \
  --app-insights ai-geoetl-uat-internal
```

### 6.2 Assign Managed Identity

```bash
MI_RESOURCE_ID=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin --query id -o tsv)

az functionapp identity assign \
  --resource-group rg-geoetl-uat-internal \
  --name func-platform-uat \
  --identities $MI_RESOURCE_ID
```

### 6.3 Configure Environment Variables

```bash
az functionapp config appsettings set \
  --resource-group rg-geoetl-uat-internal \
  --name func-platform-uat \
  --settings \
    "APP_MODE=platform" \
    "APP_NAME=func-platform-uat" \
    "ENVIRONMENT=uat" \
    "POSTGIS_HOST=pg-geoetl-uat-internal.postgres.database.azure.com" \
    "POSTGIS_DATABASE=geoetldb" \
    "POSTGIS_SCHEMA=geo" \
    "APP_SCHEMA=app" \
    "PGSTAC_SCHEMA=pgstac" \
    "H3_SCHEMA=h3" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_ADMIN_MANAGED_IDENTITY_NAME=mi-geoetl-uat-internal-db-admin" \
    "DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID>" \
    "SERVICE_BUS_CONNECTION_STRING=<CONNECTION_STRING>" \
    "SERVICE_BUS_FQDN=sb-geoetl-uat.servicebus.windows.net" \
    "JOBS_QUEUE_NAME=geospatial-jobs" \
    "BRONZE_STORAGE_ACCOUNT=stageoetluatbronze" \
    "SILVER_STORAGE_ACCOUNT=stageoetluatsilver"
```

### 6.4 Deploy Code (via ADO Pipeline)

**Deployment Flow:**
```
VS Code → Git Push to ADO Repo → ADO Pipeline → Function App Updated
```

**Steps:**

1. **Commit and push** code to Azure DevOps repository:
   ```bash
   git add .
   git commit -m "Platform app deployment for UAT"
   git push origin main
   ```

2. **Monitor pipeline** in Azure DevOps:
   - Navigate to ADO → Pipelines → [Pipeline Name]
   - Watch build and deploy stages

3. **Verify deployment** in Azure Portal:
   - Navigate to Function App → Deployment Center → Logs
   - Confirm deployment succeeded

4. **Health check**:
   ```bash
   curl https://func-platform-uat.azurewebsites.net/api/health
   ```

---

## Phase 7: Orchestrator App Deployment

### 7.1 Create Function App

```bash
# Create App Service Plan (B3 for 30-minute timeout)
az appservice plan create \
  --resource-group rg-geoetl-uat-internal \
  --name asp-orchestrator-uat \
  --sku B3 \
  --is-linux

# Create Function App
az functionapp create \
  --resource-group rg-geoetl-uat-internal \
  --name func-orchestrator-uat \
  --plan asp-orchestrator-uat \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --storage-account stageoetluatsilver \
  --app-insights ai-geoetl-uat-internal
```

### 7.2 Assign Managed Identity

```bash
MI_RESOURCE_ID=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin --query id -o tsv)

az functionapp identity assign \
  --resource-group rg-geoetl-uat-internal \
  --name func-orchestrator-uat \
  --identities $MI_RESOURCE_ID
```

### 7.3 Configure Environment Variables

```bash
az functionapp config appsettings set \
  --resource-group rg-geoetl-uat-internal \
  --name func-orchestrator-uat \
  --settings \
    "APP_MODE=orchestrator" \
    "APP_NAME=func-orchestrator-uat" \
    "ENVIRONMENT=uat" \
    "POSTGIS_HOST=pg-geoetl-uat-internal.postgres.database.azure.com" \
    "POSTGIS_DATABASE=geoetldb" \
    "POSTGIS_SCHEMA=geo" \
    "APP_SCHEMA=app" \
    "PGSTAC_SCHEMA=pgstac" \
    "H3_SCHEMA=h3" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_ADMIN_MANAGED_IDENTITY_NAME=mi-geoetl-uat-internal-db-admin" \
    "DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID>" \
    "SERVICE_BUS_CONNECTION_STRING=<CONNECTION_STRING>" \
    "SERVICE_BUS_FQDN=sb-geoetl-uat.servicebus.windows.net" \
    "JOBS_QUEUE_NAME=geospatial-jobs" \
    "FUNCTION_TASKS_QUEUE_NAME=function-tasks" \
    "DOCKER_TASKS_QUEUE_NAME=docker-tasks" \
    "BRONZE_STORAGE_ACCOUNT=stageoetluatbronze" \
    "SILVER_STORAGE_ACCOUNT=stageoetluatsilver" \
    "ADF_RESOURCE_GROUP=rg-geoetl-uat-internal" \
    "ADF_FACTORY_NAME=adf-geoetl-uat"
```

### 7.4 Deploy Code (via ADO Pipeline)

**Deployment Flow:**
```
VS Code → Git Push to ADO Repo → ADO Pipeline → Function App Updated
```

**Steps:**

1. Push code to ADO repository (same repo, different app settings target)
2. Monitor pipeline in Azure DevOps
3. Verify deployment in Azure Portal → Deployment Center → Logs

### 7.5 Initialize Database Schema

```bash
# Wait for app restart
sleep 45

# Health check
curl https://func-orchestrator-uat.azurewebsites.net/api/health

# Sync schema (creates app, pgstac, geo, h3 schemas)
curl -X POST "https://func-orchestrator-uat.azurewebsites.net/api/dbadmin/maintenance?action=ensure&confirm=yes"
```

### 7.6 Grant Internal DB Reader Access to Schemas

Now that schemas exist, grant read access for the Service Layer:

```sql
-- Connect to geoetldb on internal server
GRANT USAGE ON SCHEMA geo TO "mi-geoetl-uat-internal-db-reader";
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "mi-geoetl-uat-internal-db-reader";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO "mi-geoetl-uat-internal-db-reader";

GRANT USAGE ON SCHEMA pgstac TO "mi-geoetl-uat-internal-db-reader";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "mi-geoetl-uat-internal-db-reader";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO "mi-geoetl-uat-internal-db-reader";

-- NO access to app schema for reader
```

---

## Phase 8: Function Worker Deployment

### 8.1 Create Function App

```bash
# Create App Service Plan
az appservice plan create \
  --resource-group rg-geoetl-uat-internal \
  --name asp-funcworker-uat \
  --sku B2 \
  --is-linux

# Create Function App
az functionapp create \
  --resource-group rg-geoetl-uat-internal \
  --name func-worker-uat \
  --plan asp-funcworker-uat \
  --runtime python \
  --runtime-version 3.12 \
  --functions-version 4 \
  --storage-account stageoetluatsilver \
  --app-insights ai-geoetl-uat-internal
```

### 8.2 Assign Managed Identity

```bash
MI_RESOURCE_ID=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin --query id -o tsv)

az functionapp identity assign \
  --resource-group rg-geoetl-uat-internal \
  --name func-worker-uat \
  --identities $MI_RESOURCE_ID
```

### 8.3 Configure Environment Variables

```bash
az functionapp config appsettings set \
  --resource-group rg-geoetl-uat-internal \
  --name func-worker-uat \
  --settings \
    "APP_MODE=worker_function" \
    "APP_NAME=func-worker-uat" \
    "ENVIRONMENT=uat" \
    "POSTGIS_HOST=pg-geoetl-uat-internal.postgres.database.azure.com" \
    "POSTGIS_DATABASE=geoetldb" \
    "POSTGIS_SCHEMA=geo" \
    "APP_SCHEMA=app" \
    "PGSTAC_SCHEMA=pgstac" \
    "H3_SCHEMA=h3" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_ADMIN_MANAGED_IDENTITY_NAME=mi-geoetl-uat-internal-db-admin" \
    "DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID>" \
    "SERVICE_BUS_CONNECTION_STRING=<CONNECTION_STRING>" \
    "SERVICE_BUS_FQDN=sb-geoetl-uat.servicebus.windows.net" \
    "FUNCTION_TASKS_QUEUE_NAME=function-tasks" \
    "BRONZE_STORAGE_ACCOUNT=stageoetluatbronze" \
    "SILVER_STORAGE_ACCOUNT=stageoetluatsilver"
```

### 8.4 Deploy Code (via ADO Pipeline)

**Deployment Flow:**
```
VS Code → Git Push to ADO Repo → ADO Pipeline → Function App Updated
```

**Steps:**

1. Push code to ADO repository
2. Monitor pipeline in Azure DevOps
3. Verify deployment in Azure Portal → Deployment Center → Logs

---

## Phase 9: Docker Worker Deployment

### 9.1 Deploy via ADO Pipeline

**Deployment Flow:**
```
VS Code → ADO Repo → ADO CI Pipeline → ADO Release (Auto) → ACR Build → Container App
```

The Docker Worker uses a Dockerfile that references a base image from JFROG Artifactory.

**Dockerfile (in repo):**
```dockerfile
# Base image from JFROG Artifactory
FROM <JFROG_REGISTRY>/ubuntu-full:3.10.1

# ... rest of Dockerfile (GDAL, Python dependencies, app code)
```

**Steps:**

1. **Commit and push** to ADO repository:
   ```bash
   git add .
   git commit -m "Docker Worker deployment for UAT"
   git push origin main
   ```

2. **CI Pipeline** triggers automatically:
   - Builds Docker image
   - Image references JFROG base image (pulled during build)
   - Pushes built image to ACR

3. **Release Pipeline** triggers automatically:
   - Deploys new image to Container App

4. **Monitor** in Azure DevOps:
   - ADO → Pipelines → [Pipeline Name] → Watch progress
   - ADO → Releases → [Release Name] → Deployment logs

5. **Verify** deployment:
   ```bash
   DOCKER_URL=$(az containerapp show --resource-group rg-geoetl-uat-internal \
     --name ca-docker-worker-uat --query properties.configuration.ingress.fqdn -o tsv)
   curl https://$DOCKER_URL/health
   ```

### 9.2 Container App Configuration (First-Time Setup)

The Container App is created once during initial infrastructure setup:

```bash
MI_RESOURCE_ID=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-admin --query id -o tsv)

az containerapp create \
  --resource-group rg-geoetl-uat-internal \
  --name ca-docker-worker-uat \
  --environment cae-geoetl-uat \
  --image <JFROG_REGISTRY>/geoetl-docker-worker:uat \
  --registry-server <JFROG_REGISTRY> \
  --registry-username <JFROG_USERNAME> \
  --registry-password <JFROG_PASSWORD> \
  --cpu 4 \
  --memory 16Gi \
  --min-replicas 0 \
  --max-replicas 10 \
  --user-assigned $MI_RESOURCE_ID \
  --target-port 80 \
  --ingress external \
  --env-vars \
    "APP_MODE=worker_docker" \
    "APP_NAME=ca-docker-worker-uat" \
    "ENVIRONMENT=uat" \
    "POSTGIS_HOST=pg-geoetl-uat-internal.postgres.database.azure.com" \
    "POSTGIS_DATABASE=geoetldb" \
    "POSTGIS_SCHEMA=geo" \
    "APP_SCHEMA=app" \
    "PGSTAC_SCHEMA=pgstac" \
    "H3_SCHEMA=h3" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_ADMIN_MANAGED_IDENTITY_NAME=mi-geoetl-uat-internal-db-admin" \
    "DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID>" \
    "SERVICE_BUS_NAMESPACE=sb-geoetl-uat.servicebus.windows.net" \
    "DOCKER_TASKS_QUEUE_NAME=docker-tasks" \
    "BRONZE_STORAGE_ACCOUNT=stageoetluatbronze" \
    "SILVER_STORAGE_ACCOUNT=stageoetluatsilver"
```

### 9.3 Configure Scale Rules

```bash
az containerapp update \
  --resource-group rg-geoetl-uat-internal \
  --name ca-docker-worker-uat \
  --scale-rule-name queue-scaler \
  --scale-rule-type azure-servicebus \
  --scale-rule-metadata \
    "queueName=docker-tasks" \
    "namespace=sb-geoetl-uat" \
    "messageCount=1"
```

---

## Phase 10: Internal Service Layer Deployment

### 10.1 Deploy via ADO Pipeline

**Deployment Flow:**
```
VS Code → ADO Repo → ADO CI Pipeline → ADO Release (Auto) → ACR Build → Web App
```

The Service Layer uses a Dockerfile that references a base image from JFROG Artifactory.

**Dockerfile (in repo):**
```dockerfile
# Base image from JFROG Artifactory
FROM <JFROG_REGISTRY>/ubuntu-full:3.10.1

# ... TiTiler, TiPG, STAC API configuration
```

**Steps:**

1. **Commit and push** to ADO repository:
   ```bash
   git add .
   git commit -m "Service Layer deployment for UAT"
   git push origin main
   ```

2. **CI Pipeline** triggers automatically:
   - Builds Docker image
   - Image references JFROG base image (pulled during build)
   - Pushes built image to ACR

3. **Release Pipeline** triggers automatically:
   - Deploys new image to Web App

4. **Monitor** in Azure DevOps:
   - ADO → Pipelines → [Pipeline Name] → Watch progress
   - ADO → Releases → [Release Name] → Deployment logs

5. **Verify** deployment:
   ```bash
   curl https://app-servicelayer-uat-internal.<ASE_DOMAIN>/health
   curl https://app-servicelayer-uat-internal.<ASE_DOMAIN>/docs
   ```

### 10.2 Web App Configuration (First-Time Setup)

The Web App is created once during initial infrastructure setup:

```bash
# Create Web App in ASE
az webapp create \
  --resource-group rg-geoetl-uat-internal \
  --plan asp-servicelayer-uat \
  --name app-servicelayer-uat-internal \
  --deployment-container-image-name <JFROG_REGISTRY>/geoetl-servicelayer:uat

# Assign managed identity
MI_RESOURCE_ID=$(az identity show --resource-group rg-geoetl-uat-internal \
  --name mi-geoetl-uat-internal-db-reader --query id -o tsv)

az webapp identity assign \
  --resource-group rg-geoetl-uat-internal \
  --name app-servicelayer-uat-internal \
  --identities $MI_RESOURCE_ID
```

### 10.3 Configure Environment Variables

```bash
az webapp config appsettings set \
  --resource-group rg-geoetl-uat-internal \
  --name app-servicelayer-uat-internal \
  --settings \
    "POSTGRES_HOST=pg-geoetl-uat-internal.postgres.database.azure.com" \
    "POSTGRES_PORT=5432" \
    "POSTGRES_DBNAME=geoetldb" \
    "POSTGRES_USER=mi-geoetl-uat-internal-db-reader" \
    "AZURE_STORAGE_ACCOUNT=stageoetluatsilver" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_READER_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID>" \
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.TIF,.tiff" \
    "GDAL_CACHEMAX=200" \
    "GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR" \
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES" \
    "GDAL_HTTP_MULTIPLEX=YES" \
    "GDAL_HTTP_VERSION=2" \
    "VSI_CACHE=TRUE" \
    "VSI_CACHE_SIZE=5000000" \
    "FORWARDED_ALLOW_IPS=*" \
    "CORS_ORIGINS=*"
```

### 10.4 Configure Container Registry

```bash
az webapp config container set \
  --resource-group rg-geoetl-uat-internal \
  --name app-servicelayer-uat-internal \
  --docker-registry-server-url https://<JFROG_REGISTRY> \
  --docker-registry-server-user <JFROG_USERNAME> \
  --docker-registry-server-password <JFROG_PASSWORD>
```

---

## Phase 11: Azure Data Factory

Azure Data Factory (ADF) handles data migration between security zones:
- **Blob Pipeline**: Copies COGs and GeoTIFFs from internal Silver storage to external storage
- **Vector Pipeline**: Copies PostgreSQL tables from internal to external database

The API endpoints in `/api/data-migration/*` trigger these pipelines programmatically.

### 11.1 Create Data Factory

```bash
# Create Data Factory with system-assigned managed identity
az datafactory create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --location eastus

# Verify creation and get identity info
az datafactory show \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --query "{name:name, provisioningState:provisioningState, identity:identity}"
```

### 11.2 Grant ADF Access to Resources

ADF's system-assigned managed identity needs access to storage and databases:

```bash
# Get ADF System Identity Principal ID
ADF_PRINCIPAL=$(az datafactory show \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --query identity.principalId -o tsv)

echo "ADF Principal ID: $ADF_PRINCIPAL"

# Internal Silver Storage (read COGs for promotion)
az role assignment create \
  --role "Storage Blob Data Reader" \
  --assignee $ADF_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.Storage/storageAccounts/stageoetluatsilver

# External Storage (write promoted COGs)
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee $ADF_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-external/providers/Microsoft.Storage/storageAccounts/stageoetluatexternal
```

### 11.3 Create Linked Services

Linked services define connections to data sources and sinks.

#### 11.3.1 Internal Silver Storage (Source)

```bash
# Create linked service for internal Silver storage using system-assigned MI
cat > /tmp/ls-silver-storage.json << 'EOF'
{
  "properties": {
    "type": "AzureBlobStorage",
    "typeProperties": {
      "serviceEndpoint": "https://stageoetluatsilver.blob.core.windows.net/",
      "accountKind": "StorageV2"
    }
  }
}
EOF

az datafactory linked-service create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --linked-service-name "SilverStorage" \
  --properties @/tmp/ls-silver-storage.json
```

#### 11.3.2 External Storage (Sink)

```bash
# Create linked service for external storage
cat > /tmp/ls-external-storage.json << 'EOF'
{
  "properties": {
    "type": "AzureBlobStorage",
    "typeProperties": {
      "serviceEndpoint": "https://stageoetluatexternal.blob.core.windows.net/",
      "accountKind": "StorageV2"
    }
  }
}
EOF

az datafactory linked-service create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --linked-service-name "ExternalStorage" \
  --properties @/tmp/ls-external-storage.json
```

#### 11.3.3 Internal PostgreSQL (Source)

```bash
# Create linked service for internal PostgreSQL
# Uses the DB Admin managed identity for read access
cat > /tmp/ls-internal-postgres.json << 'EOF'
{
  "properties": {
    "type": "AzurePostgreSql",
    "typeProperties": {
      "server": "pg-geoetl-uat-internal.postgres.database.azure.com",
      "port": 5432,
      "database": "geoetldb",
      "username": "mi-geoetl-uat-internal-db-admin",
      "sslMode": 1,
      "encryptedCredential": null
    }
  }
}
EOF

az datafactory linked-service create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --linked-service-name "PostgreSQL_Internal" \
  --properties @/tmp/ls-internal-postgres.json

# Note: For full Managed Identity authentication, configure via Azure Portal:
# 1. Go to ADF → Manage → Linked Services → PostgreSQL_Internal
# 2. Set Authentication type to "User-Assigned Managed Identity"
# 3. Select the mi-geoetl-uat-internal-db-admin identity
```

#### 11.3.4 External PostgreSQL (Sink)

```bash
# Create linked service for external PostgreSQL
cat > /tmp/ls-external-postgres.json << 'EOF'
{
  "properties": {
    "type": "AzurePostgreSql",
    "typeProperties": {
      "server": "pg-geoetl-uat-external.postgres.database.azure.com",
      "port": 5432,
      "database": "geoetldb",
      "username": "mi-geoetl-uat-external-db-admin",
      "sslMode": 1,
      "encryptedCredential": null
    }
  }
}
EOF

az datafactory linked-service create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --linked-service-name "PostgreSQL_External" \
  --properties @/tmp/ls-external-postgres.json
```

### 11.4 Create Datasets

Datasets define the structure of data within linked services.

#### 11.4.1 Silver Storage Dataset (COG Container)

```bash
cat > /tmp/ds-silver-cog.json << 'EOF'
{
  "properties": {
    "linkedServiceName": {
      "referenceName": "SilverStorage",
      "type": "LinkedServiceReference"
    },
    "type": "Binary",
    "typeProperties": {
      "location": {
        "type": "AzureBlobStorageLocation",
        "container": "cog"
      }
    }
  }
}
EOF

az datafactory dataset create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --dataset-name "SilverCogContainer" \
  --properties @/tmp/ds-silver-cog.json
```

#### 11.4.2 External Storage Dataset

```bash
cat > /tmp/ds-external-cog.json << 'EOF'
{
  "properties": {
    "linkedServiceName": {
      "referenceName": "ExternalStorage",
      "type": "LinkedServiceReference"
    },
    "type": "Binary",
    "typeProperties": {
      "location": {
        "type": "AzureBlobStorageLocation",
        "container": "cog"
      }
    }
  }
}
EOF

az datafactory dataset create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --dataset-name "ExternalCogContainer" \
  --properties @/tmp/ds-external-cog.json
```

### 11.5 Create Pipelines

#### 11.5.1 Blob Migration Pipeline

```bash
# Create blob copy pipeline with Copy activity
cat > /tmp/pipeline-blob.json << 'EOF'
{
  "properties": {
    "activities": [
      {
        "name": "CopyCOGsToExternal",
        "type": "Copy",
        "inputs": [
          {
            "referenceName": "SilverCogContainer",
            "type": "DatasetReference"
          }
        ],
        "outputs": [
          {
            "referenceName": "ExternalCogContainer",
            "type": "DatasetReference"
          }
        ],
        "typeProperties": {
          "source": {
            "type": "BinarySource",
            "storeSettings": {
              "type": "AzureBlobStorageReadSettings",
              "recursive": true
            }
          },
          "sink": {
            "type": "BinarySink",
            "storeSettings": {
              "type": "AzureBlobStorageWriteSettings"
            }
          }
        }
      }
    ]
  }
}
EOF

az datafactory pipeline create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --pipeline-name "blob_internal_to_external" \
  --pipeline @/tmp/pipeline-blob.json
```

#### 11.5.2 Vector Migration Pipeline

```bash
# Create vector/PostgreSQL copy pipeline
cat > /tmp/pipeline-vector.json << 'EOF'
{
  "properties": {
    "activities": [
      {
        "name": "CopyVectorTables",
        "type": "Copy",
        "inputs": [],
        "outputs": [],
        "typeProperties": {
          "source": {
            "type": "AzurePostgreSqlSource",
            "query": "SELECT * FROM geo.vector_data WHERE promoted = false"
          },
          "sink": {
            "type": "AzurePostgreSqlSink",
            "writeBatchSize": 10000
          }
        }
      }
    ],
    "parameters": {
      "sourceTable": {
        "type": "string",
        "defaultValue": "geo.vector_data"
      },
      "targetTable": {
        "type": "string",
        "defaultValue": "geo.vector_data"
      }
    }
  }
}
EOF

az datafactory pipeline create \
  --resource-group rg-geoetl-uat-internal \
  --factory-name adf-geoetl-uat \
  --pipeline-name "Postgresql_internal_to_external" \
  --pipeline @/tmp/pipeline-vector.json
```

### 11.6 Configure Function App for ADF Triggering

The Function App (or Orchestrator) needs permission to trigger ADF pipelines and environment variables to locate the ADF.

#### 11.6.1 Grant Function App ADF Trigger Permission

```bash
# Get Function App's system-assigned managed identity
FUNC_PRINCIPAL=$(az functionapp identity show \
  --resource-group rg-geoetl-uat-internal \
  --name func-orchestrator-uat \
  --query principalId -o tsv)

echo "Function App Principal ID: $FUNC_PRINCIPAL"

# Grant Data Factory Contributor role on the ADF resource
az role assignment create \
  --assignee $FUNC_PRINCIPAL \
  --role "Data Factory Contributor" \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.DataFactory/factories/adf-geoetl-uat

# Verify role assignment
az role assignment list \
  --assignee $FUNC_PRINCIPAL \
  --scope /subscriptions/<SUB_ID>/resourceGroups/rg-geoetl-uat-internal/providers/Microsoft.DataFactory/factories/adf-geoetl-uat \
  --output table
```

#### 11.6.2 Set ADF Environment Variables

```bash
# Configure Function App with ADF connection details
az functionapp config appsettings set \
  --resource-group rg-geoetl-uat-internal \
  --name func-orchestrator-uat \
  --settings \
    "ADF_SUBSCRIPTION_ID=<SUB_ID>" \
    "ADF_RESOURCE_GROUP=rg-geoetl-uat-internal" \
    "ADF_FACTORY_NAME=adf-geoetl-uat" \
    "ADF_BLOB_PIPELINE_NAME=blob_internal_to_external" \
    "ADF_VECTOR_PIPELINE_NAME=Postgresql_internal_to_external"

# Restart to pick up new settings
az functionapp restart \
  --resource-group rg-geoetl-uat-internal \
  --name func-orchestrator-uat
```

### 11.7 Test ADF API Integration

After deploying and configuring, test the data-migration endpoints:

#### 11.7.1 Trigger Blob Pipeline

```bash
# Trigger blob migration pipeline
curl -X POST "https://func-orchestrator-uat.azurewebsites.net/api/data-migration/trigger" \
  -H "Content-Type: application/json" \
  -d '{"pipeline_type": "blob"}'

# Response:
# {
#   "success": true,
#   "run_id": "abc12345-...",
#   "pipeline_name": "blob_internal_to_external",
#   "monitor_url": "/api/data-migration/status/abc12345-..."
# }
```

#### 11.7.2 Check Pipeline Status

```bash
# Check status of pipeline run
curl "https://func-orchestrator-uat.azurewebsites.net/api/data-migration/status/{run_id}"

# Response includes:
# - status: "InProgress", "Succeeded", "Failed"
# - duration_ms: execution time
# - activities: detailed activity-level status
```

#### 11.7.3 Trigger Vector Pipeline

```bash
# Trigger vector/PostgreSQL migration pipeline
curl -X POST "https://func-orchestrator-uat.azurewebsites.net/api/data-migration/trigger" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline_type": "vector",
    "parameters": {
      "sourceTable": "geo.admin0_boundaries",
      "targetTable": "geo.admin0_boundaries"
    }
  }'
```

#### 11.7.4 Cancel Running Pipeline

```bash
# Cancel a running pipeline if needed
curl -X POST "https://func-orchestrator-uat.azurewebsites.net/api/data-migration/cancel/{run_id}"
```

### 11.8 ADF Troubleshooting

| Issue | Solution |
|-------|----------|
| "Authorization failed" when triggering | Grant Function App "Data Factory Contributor" role on ADF |
| "Linked service connection failed" | Verify managed identity has access to storage/database |
| Pipeline stuck in "InProgress" | Check ADF Monitor in Azure Portal for activity errors |
| "Resource not found" error | Verify ADF_FACTORY_NAME and ADF_RESOURCE_GROUP env vars |

**Self-Hosted Integration Runtime (SHIR)**: Not required if PostgreSQL and Storage have public network access enabled. Only needed for private endpoints or on-premises resources.

### 11.9 ADF Environment Variable Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `ADF_SUBSCRIPTION_ID` | Azure subscription ID | `12345678-...` |
| `ADF_RESOURCE_GROUP` | Resource group containing ADF | `rg-geoetl-uat-internal` |
| `ADF_FACTORY_NAME` | Data Factory name | `adf-geoetl-uat` |
| `ADF_BLOB_PIPELINE_NAME` | Blob copy pipeline name | `blob_internal_to_external` |
| `ADF_VECTOR_PIPELINE_NAME` | Vector copy pipeline name | `Postgresql_internal_to_external` |

---

## Phase 12: External Environment

### 12.1 Create External Database Schemas

ADF will create schemas on first promotion, or create manually:

```sql
-- Connect to geoetldb on external server
CREATE SCHEMA IF NOT EXISTS pgstac;
CREATE SCHEMA IF NOT EXISTS geo;

-- Grant permissions to External DB Admin (ADF)
GRANT ALL ON SCHEMA pgstac TO "mi-geoetl-uat-external-db-admin";
GRANT ALL ON SCHEMA geo TO "mi-geoetl-uat-external-db-admin";
```

### 12.2 Grant External DB Reader Access

```sql
-- After schemas exist
GRANT USAGE ON SCHEMA geo TO "mi-geoetl-uat-external-db-reader";
GRANT SELECT ON ALL TABLES IN SCHEMA geo TO "mi-geoetl-uat-external-db-reader";
ALTER DEFAULT PRIVILEGES IN SCHEMA geo GRANT SELECT ON TABLES TO "mi-geoetl-uat-external-db-reader";

GRANT USAGE ON SCHEMA pgstac TO "mi-geoetl-uat-external-db-reader";
GRANT SELECT ON ALL TABLES IN SCHEMA pgstac TO "mi-geoetl-uat-external-db-reader";
ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO "mi-geoetl-uat-external-db-reader";
```

### 12.3 Create External Service Layer Web App

```bash
# Create Web App in ASE (same image as internal)
az webapp create \
  --resource-group rg-geoetl-uat-external \
  --plan asp-servicelayer-uat-external \
  --name app-servicelayer-uat-external \
  --deployment-container-image-name <JFROG_REGISTRY>/geoetl-servicelayer:uat

# Assign managed identity
MI_RESOURCE_ID=$(az identity show --resource-group rg-geoetl-uat-external \
  --name mi-geoetl-uat-external-db-reader --query id -o tsv)

az webapp identity assign \
  --resource-group rg-geoetl-uat-external \
  --name app-servicelayer-uat-external \
  --identities $MI_RESOURCE_ID
```

### 12.4 Configure External Service Layer

```bash
az webapp config appsettings set \
  --resource-group rg-geoetl-uat-external \
  --name app-servicelayer-uat-external \
  --settings \
    "POSTGRES_HOST=pg-geoetl-uat-external.postgres.database.azure.com" \
    "POSTGRES_PORT=5432" \
    "POSTGRES_DBNAME=geoetldb" \
    "POSTGRES_USER=mi-geoetl-uat-external-db-reader" \
    "AZURE_STORAGE_ACCOUNT=stageoetluatexternal" \
    "USE_MANAGED_IDENTITY=true" \
    "DB_READER_MANAGED_IDENTITY_CLIENT_ID=<CLIENT_ID>" \
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.TIF,.tiff" \
    "GDAL_CACHEMAX=200" \
    "GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR" \
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES" \
    "GDAL_HTTP_MULTIPLEX=YES" \
    "GDAL_HTTP_VERSION=2" \
    "VSI_CACHE=TRUE" \
    "VSI_CACHE_SIZE=5000000" \
    "FORWARDED_ALLOW_IPS=*" \
    "CORS_ORIGINS=*"

# Configure container registry
az webapp config container set \
  --resource-group rg-geoetl-uat-external \
  --name app-servicelayer-uat-external \
  --docker-registry-server-url https://<JFROG_REGISTRY> \
  --docker-registry-server-user <JFROG_USERNAME> \
  --docker-registry-server-password <JFROG_PASSWORD>
```

---

## Phase 13: Post-Deployment Validation

### 13.1 ETL Pipeline Health Checks

```bash
# Platform
curl https://func-platform-uat.azurewebsites.net/api/health

# Orchestrator
curl https://func-orchestrator-uat.azurewebsites.net/api/health

# Function Worker
curl https://func-worker-uat.azurewebsites.net/api/health

# Docker Worker
DOCKER_URL=$(az containerapp show --resource-group rg-geoetl-uat-internal \
  --name ca-docker-worker-uat --query properties.configuration.ingress.fqdn -o tsv)
curl https://$DOCKER_URL/health
```

### 13.2 Service Layer Health Checks

```bash
# Internal Service Layer
curl https://app-servicelayer-uat-internal.<ASE_DOMAIN>/health
curl https://app-servicelayer-uat-internal.<ASE_DOMAIN>/docs

# External Service Layer
curl https://app-servicelayer-uat-external.<ASE_DOMAIN>/health
curl https://app-servicelayer-uat-external.<ASE_DOMAIN>/docs
```

### 13.3 End-to-End Test

```bash
# 1. Submit test job via Platform
curl -X POST https://func-platform-uat.azurewebsites.net/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "test-dataset",
    "resource_id": "test-resource",
    "version_id": "v1",
    "data_type": "vector",
    "container_name": "bronze-vectors",
    "file_name": "test.geojson"
  }'

# 2. Check job status
curl https://func-orchestrator-uat.azurewebsites.net/api/jobs/status/{JOB_ID}

# 3. Query via Internal Service Layer (after job completes)
curl https://app-servicelayer-uat-internal.<ASE_DOMAIN>/collections
curl https://app-servicelayer-uat-internal.<ASE_DOMAIN>/collections/test-dataset/items
```

---

## Environment Variables Reference

### Platform App

| Variable | Value |
|----------|-------|
| `APP_MODE` | `platform` |
| `APP_NAME` | `func-platform-uat` |
| Database vars | (standard) |
| Storage vars | Bronze + Silver |
| Service Bus | `JOBS_QUEUE_NAME=geospatial-jobs` |

### Orchestrator App

| Variable | Value |
|----------|-------|
| `APP_MODE` | `orchestrator` |
| `APP_NAME` | `func-orchestrator-uat` |
| Database vars | (standard) |
| Storage vars | Bronze + Silver |
| Service Bus | All queues |
| ADF | `ADF_RESOURCE_GROUP`, `ADF_FACTORY_NAME` |

### Function Worker

| Variable | Value |
|----------|-------|
| `APP_MODE` | `worker_function` |
| `APP_NAME` | `func-worker-uat` |
| Database vars | (standard) |
| Storage vars | Bronze + Silver |
| Service Bus | `FUNCTION_TASKS_QUEUE_NAME` |

### Docker Worker

| Variable | Value |
|----------|-------|
| `APP_MODE` | `worker_docker` |
| `APP_NAME` | `ca-docker-worker-uat` |
| Database vars | (standard) |
| Storage vars | Bronze + Silver |
| Service Bus | `DOCKER_TASKS_QUEUE_NAME` |

### Service Layer (Internal & External)

| Variable | Internal | External |
|----------|----------|----------|
| `POSTGRES_HOST` | `pg-...-internal...` | `pg-...-external...` |
| `POSTGRES_USER` | `mi-...-internal-db-reader` | `mi-...-external-db-reader` |
| `AZURE_STORAGE_ACCOUNT` | `stageoetluatsilver` | `stageoetluatexternal` |
| Service Bus | NONE | NONE |

---

## Troubleshooting

### Identity Chain Validation

```bash
# Check app has identity assigned
az functionapp identity show --name <APP_NAME> --resource-group <RG>

# Check identity details
az identity show --name <IDENTITY_NAME> --resource-group <RG>

# Check PostgreSQL user exists (run in psql)
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname LIKE 'mi-geoetl%';
```

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Token acquisition failed` | MI not assigned to app | Assign identity |
| `Password authentication failed` | PG user doesn't exist | Run `pgaadauth_create_principal()` |
| `Permission denied for schema` | Missing GRANT | Run GRANT statements |
| `Duplicate task execution` | maxDeliveryCount > 1 | Set to 1 |
| `STARTUP_FAILED` | Missing env var | Check Application Insights |

---

## Deployment Checklist

### ETL Pipeline (Internal)

- [ ] Resource Group created
- [ ] PostgreSQL server + database created
- [ ] Managed identities created (internal-db-admin, internal-db-reader)
- [ ] PostgreSQL users created
- [ ] Storage accounts created (Bronze, Silver)
- [ ] Service Bus namespace + queues created
- [ ] RBAC roles assigned
- [ ] Platform App deployed
- [ ] Orchestrator App deployed
- [ ] Function Worker deployed
- [ ] Docker Worker deployed
- [ ] Database schema synced
- [ ] Reader grants applied

### Service Layer (Internal)

- [ ] ASE created
- [ ] Service Layer image pushed to JFROG
- [ ] Internal Service Layer Web App deployed
- [ ] Environment variables configured
- [ ] Health check passing

### External Environment

- [ ] Resource Group created
- [ ] PostgreSQL server + database created
- [ ] Managed identities created (external-db-admin, external-db-reader)
- [ ] PostgreSQL users created
- [ ] External Storage account created
- [ ] ADF created with linked services
- [ ] ADF pipelines created
- [ ] External Service Layer Web App deployed
- [ ] Reader grants applied

### End-to-End Validation

- [ ] Test job submitted via Platform
- [ ] Job completed successfully
- [ ] Data visible in Internal Service Layer
- [ ] ADF promotion triggered
- [ ] Data visible in External Service Layer

---

**Last Updated**: 20 JAN 2026
