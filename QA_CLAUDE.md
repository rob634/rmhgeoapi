# DDH Claude document

**Date**: 30 NOV 2025
**Purpose**: Enable VS Code Claude on QA environment to understand and validate infrastructure components
**Audience**: Claude Code in QA environment
## Context 
Development Data Hub (DDH) is World Bank's (WB) data repository that manages metadata and access etc etc and it needs a geospatial platform. This application is designed to be a stand-alone geospatial backend that we can integrate into other applications through our Platform abstraction layer. 
Your mission is to deploy this application in the QA environment in our World Bank Azure tenant. This application works in Azure sandbox environment and must be deployed in WB Azure tenant. Your first task is to read this document in detail to understand the application. We then want to configure basic files in this folder. Finally, I will *copy the code* into the folder and we will begin configuration review. 

---

## Table of Contents

1. [Application Overview](#application-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Inventory](#component-inventory)
4. [Azure Function Apps](#1-azure-function-apps)
5. [TiTiler Web App](#2-titiler-web-app-raster-tile-server)
6. [Azure Service Bus](#3-azure-service-bus)
7. [Azure PostgreSQL Flexible Server](#4-azure-postgresql-flexible-server)
8. [Storage Accounts](#5-storage-accounts)
9. [Managed Identities](#6-managed-identities)
10. [Identity Chain Validation](#identity-chain-validation)
11. [Configuration Harmonization](#configuration-harmonization)
12. [Environment Variables Reference](#environment-variables-reference)
13. [Validation Checklist](#validation-checklist)
14. [Common Issues](#common-issues)

---

## Application Overview

### What This System Does

**Geospatial ETL Platform** - A serverless data processing system that:

1. **Ingests** vector data (CSV, GeoJSON, Shapefile, GeoPackage, KML/KMZ) into PostGIS
2. **Converts** raster data (GeoTIFF) to Cloud-Optimized GeoTIFFs (COGs)
3. **Catalogs** all data in STAC (SpatioTemporal Asset Catalog) for discovery
4. **Serves** vector data via OGC Features API (standards-compliant REST)
5. **Serves** raster tiles via TiTiler dynamic tile server

### Two-Layer Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                   LAYER 1: PLATFORM SERVICE                       │
│                   (Client-Agnostic REST API)                      │
│                                                                   │
│  Purpose: "Give me data, I'll give you API endpoints"            │
│                                                                   │
│  Endpoints:                                                       │
│  • POST /api/platform/process/vector - Ingest vector data        │
│  • POST /api/platform/process/raster - Process raster to COG     │
│  • GET /api/platform/request/{id} - Check processing status      │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                   LAYER 2: COREMACHINE                            │
│              (Universal Job Orchestration Engine)                 │
│                                                                   │
│  Pattern: Job → Stage → Task                                     │
│                                                                   │
│  • Jobs are blueprints (define WHAT to do)                       │
│  • CoreMachine handles HOW (queuing, execution, completion)      │
│  • Service Bus provides reliable async messaging                 │
│  • PostgreSQL stores all state (jobs, tasks, stage results)      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AZURE RESOURCES                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┐     ┌─────────────────────┐                       │
│  │  Function App #1    │     │  Function App #2    │                       │
│  │  (ETL Processing)   │     │  (Read-Only APIs)   │                       │
│  │                     │     │                     │                       │
│  │  • Job submission   │     │  • OGC Features API │                       │
│  │  • Task processing  │     │  • STAC API         │                       │
│  │  • Schema admin     │     │  • Health checks    │                       │
│  │  • Platform API     │     │                     │                       │
│  └──────────┬──────────┘     └──────────┬──────────┘                       │
│             │                           │                                   │
│             └───────────┬───────────────┘                                   │
│                         │                                                   │
│                         ▼                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     Azure Service Bus Namespace                       │  │
│  │  ┌─────────────────────┐    ┌─────────────────────┐                  │  │
│  │  │ geospatial-jobs     │    │ geospatial-tasks    │                  │  │
│  │  │ (job orchestration) │    │ (task execution)    │                  │  │
│  │  └─────────────────────┘    └─────────────────────┘                  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                         │                                                   │
│                         ▼                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │              Azure PostgreSQL Flexible Server                         │  │
│  │                                                                       │  │
│  │  Database Schemas:                                                    │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                │  │
│  │  │   app    │ │   geo    │ │  pgstac  │ │   h3     │                │  │
│  │  │          │ │          │ │          │ │          │                │  │
│  │  │ • jobs   │ │ • vector │ │ • items  │ │ • grids  │                │  │
│  │  │ • tasks  │ │   tables │ │ • colls  │ │ (future) │                │  │
│  │  │ • api_   │ │ • PostGIS│ │ • search │ │          │                │  │
│  │  │   reqs   │ │   geom   │ │          │ │          │                │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘                │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                         │                                                   │
│                         ▼                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     Azure Storage Accounts                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │  │
│  │  │   Bronze    │  │   Silver    │  │   Pickles   │                   │  │
│  │  │ (raw input) │  │ (COGs)      │  │ (ETL temp)  │                   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────┐                                                   │
│  │  Web App (TiTiler)  │◄── Vanilla TiTiler for raster tile serving       │
│  │  • /cog/tiles/...   │    Direct /vsiaz/ access to COGs                 │
│  │  • /cog/viewer      │    No database dependency                         │
│  └─────────────────────┘                                                   │
│                                                                             │
│  ┌─────────────────────┐                                                   │
│  │  Managed Identity   │◄── User-assigned identity for all apps           │
│  │  (shared across     │    • PostgreSQL authentication                   │
│  │   Function Apps)    │    • Storage access (future)                     │
│  └─────────────────────┘                                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Inventory

| Component | Type | Purpose | Critical |
|-----------|------|---------|----------|
| Function App #1 | Azure Functions | ETL processing, job orchestration | Yes |
| Function App #2 | Azure Functions | Read-only OGC/STAC APIs | Yes |
| TiTiler Web App | Azure Web App | Raster tile serving | Yes |
| Service Bus Namespace | Azure Service Bus | Async job/task queuing | Yes |
| PostgreSQL Server | Azure Database | State storage, PostGIS, pgstac | Yes |
| Storage Account(s) | Azure Storage | Bronze/Silver/Pickles containers | Yes |
| Managed Identity | Azure Identity | Passwordless auth to PostgreSQL | Yes |

---

## 1. Azure Function Apps

### Discovery Commands

```bash
# List function apps in resource group
az functionapp list --resource-group <RG_NAME> \
  --query "[].{name:name, state:state, defaultHostName:defaultHostName}" -o table

# Get function app details
az functionapp show --name <FUNCTION_APP_NAME> --resource-group <RG_NAME>

# Check managed identity assignment
az functionapp identity show --name <FUNCTION_APP_NAME> --resource-group <RG_NAME>

# List app settings (environment variables)
az functionapp config appsettings list --name <FUNCTION_APP_NAME> --resource-group <RG_NAME> -o table
```

### Function App #1: ETL Processing

**Purpose**: Main processing engine - job submission, task execution, database admin

**Expected Endpoints**:
- `POST /api/jobs/submit/{job_type}` - Submit processing jobs
- `GET /api/jobs/status/{job_id}` - Check job status
- `POST /api/platform/process/vector` - Platform API for vector ingestion
- `POST /api/dbadmin/maintenance/redeploy` - Schema administration
- `GET /api/health` - Health check

**Expected Configuration**:
| Setting | Value |
|---------|-------|
| Runtime | Python 3.12 |
| Plan | B3 Basic (or Premium for production) |
| Identity | User-Assigned Managed Identity |
| Service Bus | Connected via connection string |

**Critical Environment Variables**:
```
POSTGIS_HOST=<server>.postgres.database.azure.com
POSTGIS_DATABASE=<database_name>
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_NAME=<identity_name>
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<client_id>
SERVICE_BUS_CONNECTION_STRING=Endpoint=sb://...
SERVICE_BUS_NAMESPACE=<namespace_name>
JOBS_QUEUE_NAME=geospatial-jobs
TASKS_QUEUE_NAME=geospatial-tasks
BRONZE_STORAGE_ACCOUNT=<storage_account>
SILVER_STORAGE_ACCOUNT=<storage_account>
```

### Function App #2: Read-Only APIs

**Purpose**: Serve data via standards-compliant APIs (no write operations)

**Expected Endpoints**:
- `GET /api/features` - OGC Features landing page
- `GET /api/features/collections` - List vector collections
- `GET /api/features/collections/{id}/items` - Query features
- `GET /api/stac` - STAC API landing page
- `GET /api/stac/collections` - List STAC collections
- `GET /api/health` - Health check

**Expected Configuration**:
| Setting | Value |
|---------|-------|
| Runtime | Python 3.12 |
| Plan | B1/B2 Basic (lighter load) |
| Identity | Same User-Assigned Managed Identity |

**Critical Environment Variables**:
```
POSTGIS_HOST=<server>.postgres.database.azure.com
POSTGIS_DATABASE=<database_name>
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_NAME=<identity_name>
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<client_id>
```

---

## 2. TiTiler Web App (Raster Tile Server)

### Discovery Commands

```bash
# List web apps
az webapp list --resource-group <RG_NAME> \
  --query "[].{name:name, state:state, defaultHostName:defaultHostName}" -o table

# Get web app details
az webapp show --name <WEBAPP_NAME> --resource-group <RG_NAME>

# Check container configuration
az webapp config container show --name <WEBAPP_NAME> --resource-group <RG_NAME>

# List app settings
az webapp config appsettings list --name <WEBAPP_NAME> --resource-group <RG_NAME> -o table
```

### Expected Configuration

**Docker Image**: `ghcr.io/developmentseed/titiler:latest` (Vanilla TiTiler)

**Purpose**: Dynamic tile server for Cloud-Optimized GeoTIFFs

**Key Endpoints**:
- `GET /cog/viewer?url=/vsiaz/{container}/{blob}` - Interactive map viewer
- `GET /cog/tiles/{z}/{x}/{y}?url=/vsiaz/{container}/{blob}` - XYZ tiles
- `GET /cog/info?url=/vsiaz/{container}/{blob}` - COG metadata
- `GET /docs` - Swagger API documentation

**Critical Environment Variables**:
```
# Azure Storage (GDAL /vsiaz/ driver)
AZURE_STORAGE_ACCOUNT=<storage_account>
AZURE_STORAGE_ACCESS_KEY=<storage_key>

# GDAL Performance
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif,.TIF,.tiff
GDAL_CACHEMAX=200
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES
GDAL_HTTP_MULTIPLEX=YES
GDAL_HTTP_VERSION=2
VSI_CACHE=TRUE
VSI_CACHE_SIZE=5000000

# HTTPS Fix (CRITICAL)
FORWARDED_ALLOW_IPS=*
TITILER_CORS_ORIGINS=*
```

**Note**: TiTiler does NOT connect to PostgreSQL. It accesses COGs directly from blob storage via GDAL's `/vsiaz/` driver.

---

## 3. Azure Service Bus

### Discovery Commands

```bash
# List Service Bus namespaces
az servicebus namespace list --resource-group <RG_NAME> \
  --query "[].{name:name, sku:sku.name}" -o table

# List queues in namespace
az servicebus queue list --namespace-name <NAMESPACE> --resource-group <RG_NAME> \
  --query "[].{name:name, status:status}" -o table

# Get queue configuration (CRITICAL for debugging)
az servicebus queue show --namespace-name <NAMESPACE> --resource-group <RG_NAME> \
  --name <QUEUE_NAME> \
  --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, defaultMessageTimeToLive:defaultMessageTimeToLive}"
```

### Expected Queues

| Queue Name | Purpose | Lock Duration | Max Delivery |
|------------|---------|---------------|--------------|
| `geospatial-jobs` | Job orchestration messages | PT5M (5 min) | 1 |
| `geospatial-tasks` | Task execution messages | PT5M (5 min) | 1 |

### Critical Configuration

**Service Bus retries MUST be disabled** (`maxDeliveryCount: 1`). All retries are handled by CoreMachine at the application level.

```bash
# Verify queue settings
az servicebus queue show --namespace-name <NAMESPACE> --resource-group <RG_NAME> \
  --name geospatial-tasks \
  --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}"

# Expected output:
# {
#   "lockDuration": "PT5M",
#   "maxDeliveryCount": 1
# }
```

**If maxDeliveryCount > 1**, you will get race conditions and duplicate task execution!

---

## 4. Azure PostgreSQL Flexible Server

### Discovery Commands

```bash
# List PostgreSQL servers
az postgres flexible-server list --resource-group <RG_NAME> \
  --query "[].{name:name, state:state, version:version}" -o table

# Get server details
az postgres flexible-server show --name <SERVER_NAME> --resource-group <RG_NAME>

# Check Azure AD admins
az postgres flexible-server ad-admin list --server-name <SERVER_NAME> --resource-group <RG_NAME>

# Check firewall rules
az postgres flexible-server firewall-rule list --name <SERVER_NAME> --resource-group <RG_NAME> -o table
```

### Expected Configuration

| Setting | Value |
|---------|-------|
| Version | 16 (or 15+) |
| Authentication | Azure AD + PostgreSQL |
| SSL | Required |

### Database Schemas

| Schema | Purpose | Owner |
|--------|---------|-------|
| `app` | Job/task orchestration tables | Managed Identity |
| `geo` | Vector data tables (PostGIS geometries) | Managed Identity |
| `pgstac` | STAC metadata catalog | Managed Identity |
| `h3` | H3 hexagonal grids (future) | Managed Identity |
| `public` | PostGIS functions, extensions | postgres |

### Required Extensions

```sql
-- Verify extensions are enabled
SELECT extname, extversion FROM pg_extension;

-- Expected:
-- postgis    | 3.4.x
-- uuid-ossp  | 1.1
-- pg_trgm    | 1.6 (optional)
```

### PostgreSQL User Verification

```sql
-- Check managed identity user exists
SELECT rolname, rolcreaterole, rolcreatedb, rolcanlogin
FROM pg_roles
WHERE rolname = '<MANAGED_IDENTITY_NAME>';

-- Expected: rolcreaterole=t, rolcreatedb=f, rolcanlogin=t

-- Check CREATE ON DATABASE permission
SELECT has_database_privilege('<MANAGED_IDENTITY_NAME>', current_database(), 'CREATE');
-- Expected: t

-- Check schema permissions
SELECT has_schema_privilege('<MANAGED_IDENTITY_NAME>', 'geo', 'CREATE');
SELECT has_schema_privilege('<MANAGED_IDENTITY_NAME>', 'app', 'CREATE');
-- Expected: t for both
```

---

## 5. Storage Accounts

### Discovery Commands

```bash
# List storage accounts
az storage account list --resource-group <RG_NAME> \
  --query "[].{name:name, kind:kind, sku:sku.name}" -o table

# List containers in a storage account
az storage container list --account-name <STORAGE_ACCOUNT> --auth-mode login \
  --query "[].name" -o table

# Check CORS settings (important for TiTiler)
az storage cors list --account-name <STORAGE_ACCOUNT> --services b
```

### Expected Containers
#note bronze container will be in a separate storage account (blast radius) our storage accounts are ours- read only access for DDH App
| Container | Purpose | Access |
|-----------|---------|--------|
| `bronze`  | Raw input files (CSV, GeoJSON, GeoTIFF) | Function Apps write |
| `silver-cogs` | Processed Cloud-Optimized GeoTIFFs | TiTiler reads |
| `pickles` | Intermediate chunked data for vector ETL | Function Apps read/write |

### Storage Access Methods

| Component | Access Method |
|-----------|---------------|
| Function Apps | Managed Identity (future) or Account Key |
| TiTiler | Account Key (GDAL /vsiaz/ driver) |

---

## 6. Managed Identities

### Discovery Commands

```bash
# List managed identities in resource group
az identity list --resource-group <RG_NAME> \
  --query "[].{name:name, clientId:clientId, principalId:principalId}" -o table

# Get specific identity details
az identity show --name <IDENTITY_NAME> --resource-group <RG_NAME>

# Check role assignments for the identity
az role assignment list --assignee <PRINCIPAL_ID> \
  --query "[].{role:roleDefinitionName, scope:scope}" -o table
```

### Key Properties to Capture

| Property | Used For |
|----------|----------|
| `name` | PostgreSQL user name (must match exactly) |
| `clientId` | `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` environment variable |
| `principalId` | Azure RBAC role assignments |

### Expected RBAC Assignments

| Role | Scope | Purpose |
|------|-------|---------|
| `Storage Blob Data Contributor` | Storage account | Read/write blobs |
| (Future) `Key Vault Secrets User` | Key Vault | Read secrets |

---

## Identity Chain Validation

This is the **most critical** validation. All three must match:

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Function App Identity Assignment                             │
│                                                                 │
│    az functionapp identity show --name <FUNC_APP> -g <RG>      │
│    → Look for userAssignedIdentities containing your MI        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼ MUST match
┌─────────────────────────────────────────────────────────────────┐
│ 2. Managed Identity Properties                                  │
│                                                                 │
│    az identity show --name <MI_NAME> -g <RG>                   │
│    → name: <MI_NAME> (this becomes PostgreSQL user)            │
│    → clientId: <CLIENT_ID> (used in env var)                   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼ MUST match
┌─────────────────────────────────────────────────────────────────┐
│ 3. PostgreSQL User                                              │
│                                                                 │
│    SELECT rolname FROM pg_roles WHERE rolname = '<MI_NAME>';   │
│    → User must exist with same name as managed identity        │
│    → Created via: SELECT * FROM pgaadauth_create_principal(...) │
└─────────────────────────────────────────────────────────────────┘
```

### Quick Validation Script

```bash
#!/bin/bash
# Run this to validate the identity chain

RG="<resource_group>"
FUNC_APP="<function_app_name>"
MI_NAME="<managed_identity_name>"

echo "=== 1. Function App Identity ==="
az functionapp identity show --name $FUNC_APP --resource-group $RG \
  --query "userAssignedIdentities" -o json

echo ""
echo "=== 2. Managed Identity Details ==="
az identity show --name $MI_NAME --resource-group $RG \
  --query "{name:name, clientId:clientId, principalId:principalId}" -o table

echo ""
echo "=== 3. PostgreSQL User (run in psql) ==="
echo "SELECT rolname, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname = '$MI_NAME';"
```

---

## Configuration Harmonization

Azure Functions + Service Bus must be configured as **one system**:

### Three-Layer Configuration

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Azure Service Bus (Azure Portal/CLI)               │
│                                                             │
│   lockDuration: PT5M (5 minutes)                           │
│   maxDeliveryCount: 1 (disable SB retries!)                │
└───────────────────────────┬─────────────────────────────────┘
                            │ must be ≤
┌───────────────────────────▼─────────────────────────────────┐
│ Layer 2: host.json (deployed with code)                     │
│                                                             │
│   functionTimeout: 00:30:00                                │
│   maxAutoLockRenewalDuration: 00:30:00                     │
│   maxConcurrentCalls: 4                                    │
└───────────────────────────┬─────────────────────────────────┘
                            │ should equal
┌───────────────────────────▼─────────────────────────────────┐
│ Layer 3: config.py / Environment Variables                  │
│                                                             │
│   function_timeout_minutes: 30                             │
│   task_max_retries: 3 (CoreMachine retries)                │
└─────────────────────────────────────────────────────────────┘
```

### Verify Service Bus Configuration

```bash
# Check both queues
for QUEUE in geospatial-jobs geospatial-tasks; do
  echo "=== $QUEUE ==="
  az servicebus queue show \
    --namespace-name <NAMESPACE> \
    --resource-group <RG> \
    --name $QUEUE \
    --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}"
done

# Expected for BOTH:
# {
#   "lockDuration": "PT5M",
#   "maxDeliveryCount": 1
# }
```

---

## Environment Variables Reference

### Function App #1 (ETL Processing)

| Variable | Example | Required | Purpose |
|----------|---------|----------|---------|
| `POSTGIS_HOST` | `server.postgres.database.azure.com` | Yes | PostgreSQL hostname |
| `POSTGIS_DATABASE` | `geoetldb` | Yes | Database name |
| `POSTGIS_PORT` | `5432` | No | Default: 5432 |
| `USE_MANAGED_IDENTITY` | `true` | Yes | Enable MI auth |
| `DB_ADMIN_MANAGED_IDENTITY_NAME` | `migeoetldbadminqa` | Yes | PG user name |
| `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | `abc123-...` | Yes* | For user-assigned MI |
| `SERVICE_BUS_CONNECTION_STRING` | `Endpoint=sb://...` | Yes | Service Bus connection |
| `SERVICE_BUS_NAMESPACE` | `rmhazure` | Yes | Namespace name |
| `JOBS_QUEUE_NAME` | `geospatial-jobs` | Yes | Jobs queue |
| `TASKS_QUEUE_NAME` | `geospatial-tasks` | Yes | Tasks queue |
| `BRONZE_STORAGE_ACCOUNT` | `rmhazuregeo` | Yes | Bronze tier storage |
| `SILVER_STORAGE_ACCOUNT` | `rmhazuregeo` | Yes | Silver tier storage |
| `STORAGE_ACCOUNT_KEY` | `...` | Yes** | Storage access |

*Required for user-assigned managed identity
**Use MI instead when possible

### Function App #2 (Read-Only APIs)

| Variable | Example | Required | Purpose |
|----------|---------|----------|---------|
| `POSTGIS_HOST` | `server.postgres.database.azure.com` | Yes | PostgreSQL hostname |
| `POSTGIS_DATABASE` | `geoetldb` | Yes | Database name |
| `USE_MANAGED_IDENTITY` | `true` | Yes | Enable MI auth |
| `DB_ADMIN_MANAGED_IDENTITY_NAME` | `migeoetldbadminqa` | Yes | PG user name |
| `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | `abc123-...` | Yes* | For user-assigned MI |

### TiTiler Web App

| Variable | Example | Required | Purpose |
|----------|---------|----------|---------|
| `AZURE_STORAGE_ACCOUNT` | `rmhazuregeo` | Yes | Storage for COGs |
| `AZURE_STORAGE_ACCESS_KEY` | `...` | Yes | GDAL auth |
| `FORWARDED_ALLOW_IPS` | `*` | Yes | HTTPS fix |
| `TITILER_CORS_ORIGINS` | `*` | Yes | CORS |
| `GDAL_HTTP_VERSION` | `2` | Yes | Performance |

---

## Validation Checklist

### Pre-Deployment Checklist

- [ ] **Managed Identity** exists and has correct name
- [ ] **PostgreSQL user** created matching identity name
- [ ] **PostgreSQL permissions** granted (CREATE ON DATABASE, CREATEROLE)
- [ ] **PostGIS extension** enabled
- [ ] **Service Bus queues** exist with correct settings
- [ ] **Storage containers** exist (bronze, silver-cogs, pickles)
- [ ] **Function Apps** have identity assigned

### Post-Deployment Checklist

- [ ] **Health endpoint** responds: `GET /api/health`
- [ ] **Database connection** works (health shows DB status)
- [ ] **Queue connection** works (submit test job)
- [ ] **Storage access** works (process_vector job completes)
- [ ] **TiTiler** serves tiles from COGs

### Test Commands

```bash
# 1. Health check (Function App #1)
curl https://<FUNC_APP_URL>/api/health

# 2. Submit test job
curl -X POST https://<FUNC_APP_URL>/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "QA test"}'

# 3. Check job status (use job_id from step 2)
curl https://<FUNC_APP_URL>/api/jobs/status/{JOB_ID}

# 4. Test OGC Features (Function App #2)
curl https://<FUNC_APP_2_URL>/api/features/collections

# 5. Test TiTiler
curl https://<TITILER_URL>/cog/info?url=/vsiaz/silver-cogs/test.tif
```

---

## Common Issues

### 1. "Token acquisition failed"

**Cause**: Managed identity not properly assigned to Function App

**Check**:
```bash
az functionapp identity show --name <FUNC_APP> --resource-group <RG>
```

**Fix**: Assign the user-assigned managed identity to the Function App

### 2. "Password authentication failed for user X"

**Cause**: PostgreSQL user doesn't exist or name mismatch

**Check** (in psql):
```sql
SELECT rolname FROM pg_roles WHERE rolname = '<MI_NAME>';
```

**Fix**: Create user with `pgaadauth_create_principal`

### 3. "Permission denied for schema"

**Cause**: Missing GRANT statements

**Check**:
```sql
SELECT has_schema_privilege('<MI_NAME>', 'geo', 'CREATE');
SELECT has_database_privilege('<MI_NAME>', current_database(), 'CREATE');
```

**Fix**: Grant permissions (see QA_DATABASE_SETUP.md)

### 4. "Extension postgis is not available"

**Cause**: Extension not allowlisted or not created

**Check**:
```sql
SELECT * FROM pg_available_extensions WHERE name = 'postgis';
SELECT PostGIS_Version();
```

**Fix**: Enable in Azure Portal (Server Parameters → azure.extensions) then `CREATE EXTENSION postgis`

### 5. Duplicate task execution / Race conditions

**Cause**: Service Bus `maxDeliveryCount` > 1

**Check**:
```bash
az servicebus queue show --namespace-name <NS> --resource-group <RG> --name geospatial-tasks \
  --query "maxDeliveryCount"
```

**Fix**: Set to 1:
```bash
az servicebus queue update --namespace-name <NS> --resource-group <RG> --name geospatial-tasks \
  --max-delivery-count 1
```

### 6. TiTiler mixed content errors

**Cause**: `FORWARDED_ALLOW_IPS` not set

**Fix**:
```bash
az webapp config appsettings set --name <TITILER_APP> --resource-group <RG> \
  --settings FORWARDED_ALLOW_IPS=*
az webapp restart --name <TITILER_APP> --resource-group <RG>
```

---

## PostgreSQL User Setup Reference

For the managed identity to connect to PostgreSQL:

```sql
-- 1. Enable PostGIS (run first, requires azure_pg_admin)
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Create user and register as AAD principal
SELECT * FROM pgaadauth_create_principal('<MI_NAME>', false, false);

-- 3. Grant permissions
GRANT CREATE ON DATABASE <DB_NAME> TO <MI_NAME>;
ALTER ROLE <MI_NAME> CREATEROLE;
GRANT USAGE ON SCHEMA public TO <MI_NAME>;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO <MI_NAME>;

-- 4. Verify
SELECT rolname, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname = '<MI_NAME>';
SELECT has_database_privilege('<MI_NAME>', current_database(), 'CREATE');
```

See `QA_DATABASE_SETUP.md` for complete setup instructions.

---

**Last Updated**: 30 NOV 2025
