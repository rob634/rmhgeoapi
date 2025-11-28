# Azure Configuration Requirements for Corporate Tenant Deployment

**Date**: 5 NOV 2025
**Author**: Robert Harrison
**Purpose**: Configuration request template for deploying rmhgeoapi in corporate Azure tenant
**Source Environment**: Personal Azure (rmhazure subscription)
**Target Environment**: Corporate Azure tenant

---

## 🎯 Executive Summary

This document specifies the Azure resource configuration needed to replicate the working rmhgeoapi geospatial processing system in a corporate Azure tenant. All configurations listed below are from the currently operational production environment.

---

## 📋 Required Azure Resources

### 1. Azure Function App (Serverless Compute)

**Resource Type**: Function App (Linux, Python)
**Recommended Name**: `<company>-geoapi` or `<project>-geoapi`

**Configuration Requirements**:

```json
{
  "runtime": "Python 3.12",
  "platform": "Linux",
  "functions_extension_version": "~4",
  "plan_type": "Consumption or Premium (EP1 recommended for long-running tasks)",
  "region": "East US (or preferred corporate region)",
  "always_on": false,
  "http20_enabled": false,
  "min_tls_version": "1.2",
  "ftps_state": "FtpsOnly"
}
```

**Required App Settings**:
```bash
FUNCTIONS_WORKER_RUNTIME=python
FUNCTIONS_EXTENSION_VERSION=~4
ServiceBusConnection__fullyQualifiedNamespace=<servicebus-namespace>.servicebus.windows.net
POSTGIS_HOST=<postgres-server>.postgres.database.azure.com
POSTGIS_PORT=5432
POSTGIS_USER=<db-admin-user>
POSTGIS_PASSWORD=<secure-password>
POSTGIS_DATABASE=<database-name>
POSTGIS_SCHEMA=geo
APP_SCHEMA=app
AZURE_STORAGE_ACCOUNT=<storage-account-name>
AZURE_STORAGE_KEY=<storage-account-key>
BRONZE_CONTAINER_NAME=<bronze-container>
SILVER_CONTAINER_NAME=<silver-container>
GOLD_CONTAINER_NAME=<gold-container>
```

**Managed Identity**:
- **Type**: System-assigned managed identity (enabled)
- **Purpose**: Passwordless authentication to Service Bus, Storage, PostgreSQL
- **Principal ID**: Auto-generated upon enablement

**host.json Configuration** (deployed with code):
```json
{
  "version": "2.0",
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "prefetchCount": 0,
      "messageHandlerOptions": {
        "autoComplete": true,
        "maxConcurrentCalls": 1,
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    },
    "queues": {
      "maxPollingInterval": "00:00:02",
      "visibilityTimeout": "00:00:30",
      "batchSize": 16,
      "maxDequeueCount": 1
    }
  }
}
```

---

### 2. Azure Storage Account (Blob Storage)

**Resource Type**: Storage Account (General Purpose v2)
**Recommended Name**: `<company>geostorage` (lowercase, no hyphens)

**Configuration Requirements**:

```json
{
  "sku": "Standard_RAGRS (Read-Access Geo-Redundant Storage)",
  "kind": "StorageV2",
  "region": "East US (or preferred corporate region)",
  "enable_https_traffic_only": true,
  "allow_blob_public_access": true,
  "min_tls_version": "TLS1_2",
  "access_tier": "Hot"
}
```

**Required Blob Containers**:

| Container Name | Purpose | Public Access |
|----------------|---------|---------------|
| `<prefix>-bronze` | Raw data ingestion tier | None (private) |
| `<prefix>-silver` | Processed COGs + PostGIS data | None (private) |
| `<prefix>-gold` | GeoParquet exports (future) | None (private) |
| `<prefix>-temp` | Temporary processing files | None (private) |
| `<prefix>-inventory` | Blob inventory snapshots | None (private) |
| `<prefix>-pipelines` | Pipeline configuration/state | None (private) |
| `silver-cogs` | Cloud-Optimized GeoTIFFs | None (private) |
| `silver-tiles` | Raster tiles (XYZ, MBTiles) | None (private) |
| `silver-vectors` | Vector datasets (GeoJSON, etc.) | None (private) |
| `silver-stac-assets` | STAC metadata assets | None (private) |
| `$web` | Static website hosting (optional) | Blob (for web map) |

**Static Website Configuration** (Optional - for OGC Features web map):
```json
{
  "enabled": true,
  "index_document": "index.html",
  "error_404_document": "404.html"
}
```

**CORS Configuration** (Required for web map):
```json
{
  "allowed_origins": ["*"],
  "allowed_methods": ["GET", "OPTIONS"],
  "allowed_headers": ["*"],
  "exposed_headers": ["*"],
  "max_age_seconds": 3600
}
```

**Access Configuration**:
- Function App Managed Identity needs "Storage Blob Data Contributor" role
- Consider private endpoints for enhanced security (optional)

---

### 3. Azure Service Bus (Message Queue)

**Resource Type**: Service Bus Namespace
**Recommended Name**: `<company>-geoapi-bus` or `<project>-servicebus`

**Configuration Requirements**:

```json
{
  "sku": "Standard",
  "region": "East US (or preferred corporate region)",
  "zone_redundant": false
}
```

**Required Queues**:

#### Queue 1: `geospatial-jobs`
```json
{
  "lock_duration": "PT5M (5 minutes)",
  "max_delivery_count": 3,
  "max_size_in_megabytes": 1024,
  "default_message_time_to_live": "P7D (7 days)",
  "enable_partitioning": false,
  "enable_dead_lettering_on_message_expiration": true
}
```

#### Queue 2: `geospatial-tasks`
```json
{
  "lock_duration": "PT5M (5 minutes)",
  "max_delivery_count": 3,
  "max_size_in_megabytes": 1024,
  "default_message_time_to_live": "P7D (7 days)",
  "enable_partitioning": false,
  "enable_dead_lettering_on_message_expiration": true
}
```

**Access Configuration**:
- Function App Managed Identity needs "Azure Service Bus Data Owner" role
- Use connection string with Managed Identity (passwordless):
  - `ServiceBusConnection__fullyQualifiedNamespace=<namespace>.servicebus.windows.net`
  - **NOT** using connection string with secrets

**Critical Configuration Notes**:
- `lockDuration: PT5M` (5 minutes max on Standard tier)
- `maxDeliveryCount: 3` allows retry logic (can reduce to 1 for dev)
- Lock renewal handled automatically by Azure Functions runtime (host.json setting)
- See `SERVICE_BUS_HARMONIZATION.md` for detailed explanation of lock duration vs function timeout

---

### 4. Azure Database for PostgreSQL (Flexible Server)

**Resource Type**: PostgreSQL Flexible Server
**Recommended Name**: `<company>-geoapi-postgres` or `<project>-pgflex`

**Configuration Requirements**:

```json
{
  "version": "17",
  "sku": "Standard_B1ms (1 vCore, 2 GB RAM - can scale up)",
  "tier": "Burstable",
  "storage_size_gb": 32,
  "backup_retention_days": 7,
  "geo_redundant_backup": "Disabled (enable for production)",
  "high_availability": "Disabled (enable ZoneRedundant for production)",
  "region": "East US (or preferred corporate region)"
}
```

**Required PostgreSQL Extensions**:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS hstore;
```

**Required Schemas**:
```sql
CREATE SCHEMA IF NOT EXISTS geo;      -- Geospatial data (PostGIS tables)
CREATE SCHEMA IF NOT EXISTS app;      -- Application state (jobs, tasks)
CREATE SCHEMA IF NOT EXISTS pgstac;   -- STAC metadata catalog
CREATE SCHEMA IF NOT EXISTS platform; -- Platform orchestration
```

**Firewall Rules**:
- Allow Azure services: `0.0.0.0` (for Function App access)
- Optional: Specific client IP addresses for direct DBeaver/pgAdmin access
- Consider private endpoints for enhanced security (optional)

**Access Configuration**:
- Function App uses password authentication (store in Key Vault or App Settings)
- Future: Enable Managed Identity for passwordless PostgreSQL access
- Admin user needs superuser privileges to create extensions

**Performance Tuning** (for production):
```sql
-- Recommended settings for geospatial workloads
ALTER SYSTEM SET shared_buffers = '512MB';
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET max_connections = 100;
```

---

## 🔐 Security & Identity Configuration

### 1. Managed Identity Setup

**Function App System-Assigned Managed Identity**:
```bash
# Enable managed identity (Azure CLI)
az functionapp identity assign \
  --resource-group <resource-group> \
  --name <function-app-name>
```

**Role Assignments Required**:

| Resource | Role | Scope | Purpose |
|----------|------|-------|---------|
| Storage Account | Storage Blob Data Contributor | Storage account level | Read/write blobs |
| Service Bus Namespace | **Azure Service Bus Data Owner** (recommended) | Namespace level | Send/receive messages |
| Service Bus Namespace | *OR* Azure Service Bus Data Sender + Data Receiver | Namespace level | Send/receive (least privilege) |
| PostgreSQL Server | (Future) PostgreSQL AAD Admin | Server level | Passwordless DB access |

**Important**: Function App needs **BOTH send and receive** permissions on Service Bus because:
- It **sends** job messages to `geospatial-jobs` queue
- It **receives** job messages to process them
- It **sends** task messages to `geospatial-tasks` queue
- It **receives** task messages to execute them

See [AZURE_SERVICEBUS_RBAC_ROLES.md](AZURE_SERVICEBUS_RBAC_ROLES.md) for detailed role comparison.

**Azure CLI Commands**:
```bash
# Storage access
az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<storage-account>

# Service Bus access (Option 1 - Recommended for simplicity)
az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Azure Service Bus Data Owner" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<servicebus-namespace>

# Service Bus access (Option 2 - Least privilege, requires BOTH commands)
az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Azure Service Bus Data Sender" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<servicebus-namespace>

az role assignment create \
  --assignee <function-app-principal-id> \
  --role "Azure Service Bus Data Receiver" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.ServiceBus/namespaces/<servicebus-namespace>
```

---

### 2. Network Security (Optional - Enhanced Security)

**Virtual Network Integration** (Recommended for corporate environments):
- Function App integrated into VNet subnet
- Storage Account private endpoint
- PostgreSQL private endpoint
- Service Bus private endpoint

**Configuration Steps** (if using VNets):
```bash
# Create VNet and subnet
az network vnet create \
  --resource-group <resource-group> \
  --name <vnet-name> \
  --address-prefix 10.0.0.0/16 \
  --subnet-name functions-subnet \
  --subnet-prefix 10.0.1.0/24

# Enable VNet integration for Function App
az functionapp vnet-integration add \
  --resource-group <resource-group> \
  --name <function-app-name> \
  --vnet <vnet-name> \
  --subnet functions-subnet
```

---

## 🔧 Configuration Harmonization Checklist

**CRITICAL**: Three-layer configuration must be harmonized to prevent race conditions!

### Layer 1: Azure Service Bus
```bash
# Verify queue settings
az servicebus queue show \
  --resource-group <resource-group> \
  --namespace-name <servicebus-namespace> \
  --name geospatial-tasks \
  --query "{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount}"

# Expected:
# lockDuration: PT5M (5 minutes)
# maxDeliveryCount: 3 (or 1 for dev)
```

### Layer 2: Azure Functions (host.json)
```json
{
  "functionTimeout": "00:30:00",
  "extensions": {
    "serviceBus": {
      "messageHandlerOptions": {
        "maxAutoLockRenewalDuration": "00:30:00"
      }
    }
  }
}
```

### Layer 3: Application (config.py)
```python
function_timeout_minutes: int = 30  # Must match host.json
```

**Validation Rule**:
```
Service Bus lockDuration (PT5M)
  ≤
host.json maxAutoLockRenewalDuration (00:30:00)
  =
host.json functionTimeout (00:30:00)
  =
config.py function_timeout_minutes (30)
```

**See**: `SERVICE_BUS_HARMONIZATION.md` for detailed explanation

---

## 📊 Resource Sizing Recommendations

### Development/Testing Environment
| Resource | SKU | Cost (Est/Month) |
|----------|-----|------------------|
| Function App | Consumption Plan | $0-50 (pay per execution) |
| Storage Account | Standard_LRS | $20-50 |
| Service Bus | Standard | $10 |
| PostgreSQL | Standard_B1ms | $25-40 |
| **Total** | | **~$55-150/month** |

### Production Environment
| Resource | SKU | Cost (Est/Month) |
|----------|-----|------------------|
| Function App | Premium EP1 | $150-200 |
| Storage Account | Standard_RAGRS | $100-200 |
| Service Bus | Standard | $10-20 |
| PostgreSQL | GeneralPurpose_D4s_v3 | $300-500 |
| **Total** | | **~$560-920/month** |

**Scaling Considerations**:
- Function App: Premium plan supports 30-min timeout (required for large raster processing)
- PostgreSQL: Scale up to 4+ vCores for concurrent job processing
- Storage: RAGRS provides geo-redundancy for critical geospatial datasets

---

## 🚀 Deployment Workflow

### Step 1: Create Resources (Azure Portal or CLI)
```bash
# Example: Create resource group
az group create --name <resource-group> --location eastus

# Create Function App
az functionapp create \
  --resource-group <resource-group> \
  --name <function-app-name> \
  --storage-account <storage-account> \
  --functions-version 4 \
  --runtime python \
  --runtime-version 3.12 \
  --os-type Linux \
  --consumption-plan-location eastus

# Create Storage Account
az storage account create \
  --name <storage-account> \
  --resource-group <resource-group> \
  --location eastus \
  --sku Standard_RAGRS \
  --kind StorageV2

# Create Service Bus Namespace
az servicebus namespace create \
  --resource-group <resource-group> \
  --name <servicebus-namespace> \
  --location eastus \
  --sku Standard

# Create PostgreSQL Flexible Server
az postgres flexible-server create \
  --resource-group <resource-group> \
  --name <postgres-server> \
  --location eastus \
  --admin-user <admin-user> \
  --admin-password <secure-password> \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 17 \
  --storage-size 32
```

### Step 2: Configure Resources
```bash
# Enable managed identity
az functionapp identity assign \
  --resource-group <resource-group> \
  --name <function-app-name>

# Create Service Bus queues
az servicebus queue create \
  --resource-group <resource-group> \
  --namespace-name <servicebus-namespace> \
  --name geospatial-jobs \
  --lock-duration PT5M \
  --max-delivery-count 3

az servicebus queue create \
  --resource-group <resource-group> \
  --namespace-name <servicebus-namespace> \
  --name geospatial-tasks \
  --lock-duration PT5M \
  --max-delivery-count 3

# Create storage containers
az storage container create \
  --account-name <storage-account> \
  --name <bronze-container> \
  --auth-mode login

# Enable PostgreSQL extensions
psql -h <postgres-server>.postgres.database.azure.com -U <admin-user> -d postgres -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

### Step 3: Deploy Function App Code
```bash
# From local development environment
cd /path/to/rmhgeoapi
func azure functionapp publish <function-app-name> --python --build remote
```

### Step 4: Deploy Database Schema
```bash
# After Function App deployment
curl -X POST https://<function-app-name>.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

---

## 🔍 Testing & Verification

### Health Check Endpoints
```bash
# 1. Basic health check
curl https://<function-app-name>.azurewebsites.net/api/health

# 2. Database statistics
curl https://<function-app-name>.azurewebsites.net/api/db/stats

# 3. Submit test job
curl -X POST https://<function-app-name>.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 3}'

# 4. Check job status (use job_id from step 3)
curl https://<function-app-name>.azurewebsites.net/api/jobs/status/{JOB_ID}
```

### Service Bus Queue Monitoring
```bash
# Check queue depth
az servicebus queue show \
  --resource-group <resource-group> \
  --namespace-name <servicebus-namespace> \
  --name geospatial-tasks \
  --query "countDetails.activeMessageCount"
```

### PostgreSQL Health Check
```bash
# Test database connection
psql -h <postgres-server>.postgres.database.azure.com \
     -U <admin-user> \
     -d <database-name> \
     -c "SELECT version(); SELECT postgis_version();"
```

---

## 📚 Configuration Reference Documents

### Internal Documentation (in `/docs_claude/`)
1. **CLAUDE_CONTEXT.md** - Primary system overview
2. **SERVICE_BUS_HARMONIZATION.md** - Three-layer configuration architecture
3. **ARCHITECTURE_REFERENCE.md** - Deep technical specifications
4. **DEPLOYMENT_GUIDE.md** - Deployment procedures

### Azure Documentation
1. **Azure Functions**: https://learn.microsoft.com/en-us/azure/azure-functions/
2. **Service Bus**: https://learn.microsoft.com/en-us/azure/service-bus-messaging/
3. **PostgreSQL Flexible Server**: https://learn.microsoft.com/en-us/azure/postgresql/
4. **Managed Identity**: https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/

---

## 🚨 Critical Notes for Corporate IT

### 1. Naming Conventions
- Replace `rmhazure` prefix with corporate standard naming convention
- Ensure all resource names comply with corporate policies
- Document naming in corporate CMDB

### 2. Cost Management
- Set up Azure Cost Management alerts
- Tag all resources with project/cost-center tags
- Monitor storage account costs (blob storage can grow large with geospatial data)

### 3. Compliance & Governance
- Ensure PostgreSQL backup retention meets corporate RTO/RPO requirements
- Configure Azure Policy compliance (if required)
- Enable diagnostic logs for all resources
- Configure Azure Monitor alerts for failures

### 4. Security Requirements
- Consider private endpoints for all resources (adds cost but enhances security)
- Enable Azure Defender for Cloud (if required)
- Implement Network Security Groups (NSGs) if using VNets
- Store secrets in Azure Key Vault (database passwords, storage keys)

### 5. High Availability (Production)
- PostgreSQL: Enable Zone-Redundant High Availability
- Function App: Use Premium plan with multiple instances
- Storage: Use RAGRS (Read-Access Geo-Redundant Storage)
- Service Bus: Enable zone redundancy (requires Premium tier)

---

## ✅ Configuration Validation Checklist

### Pre-Deployment
- [ ] All resource names approved per corporate naming convention
- [ ] Resource group created in approved region
- [ ] Budgets and cost alerts configured
- [ ] Tags applied to all resources (project, cost-center, environment)

### Post-Resource Creation
- [ ] Function App managed identity enabled
- [ ] Storage Account RBAC roles assigned to managed identity
- [ ] Service Bus RBAC roles assigned to managed identity
- [ ] PostgreSQL firewall rules configured
- [ ] PostgreSQL extensions installed (postgis, pgcrypto, etc.)
- [ ] Storage containers created
- [ ] Service Bus queues created with correct settings

### Post-Code Deployment
- [ ] Function App deployed successfully (`func azure functionapp publish`)
- [ ] Health endpoint responding (`/api/health`)
- [ ] Database schema deployed (`/api/db/schema/redeploy`)
- [ ] Test job submitted and completed successfully
- [ ] Application Insights logs visible
- [ ] Service Bus queues processing messages

### Configuration Harmonization
- [ ] Service Bus `lockDuration` = PT5M
- [ ] Service Bus `maxDeliveryCount` = 3 (or 1 for dev)
- [ ] host.json `functionTimeout` = 00:30:00
- [ ] host.json `maxAutoLockRenewalDuration` = 00:30:00
- [ ] config.py `function_timeout_minutes` = 30

---

## 📞 Support & Contact

**Original Environment Owner**: Robert Harrison
**Documentation Source**: rmhgeoapi GitHub repository
**Azure Subscription**: rmhazure (personal tenant)
**Target Deployment**: Corporate Azure tenant

**For Questions**:
- Configuration issues: Refer to `SERVICE_BUS_HARMONIZATION.md`
- Architecture questions: Refer to `ARCHITECTURE_REFERENCE.md`
- Deployment issues: Refer to `DEPLOYMENT_GUIDE.md`

---

**Document Version**: 1.0
**Last Updated**: 5 NOV 2025
**Status**: Ready for Corporate IT Review
