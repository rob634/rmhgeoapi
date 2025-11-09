# Azure Configuration Quick Reference

**Date**: 5 NOV 2025
**Purpose**: One-page quick reference for Azure resource configuration
**Source**: Personal Azure tenant (`rmhazure` subscription)

---

## 🎯 Current Production Configuration (Personal Tenant)

| Resource | Name | Configuration | Region | SKU/Tier |
|----------|------|---------------|--------|----------|
| **Function App** | rmhgeoapibeta | Python 3.12, Linux | East US | Consumption |
| **Storage Account** | rmhazuregeo | Standard_RAGRS, StorageV2 | East US | Standard |
| **Service Bus** | rmhazure | Standard tier | East US | Standard |
| **PostgreSQL** | rmhpgflex | Version 17, PostGIS enabled | East US | Standard_B1ms |
| **Resource Group** | rmhazure_rg | All resources in one RG | East US | N/A |

---

## 📋 Azure CLI Quick Commands

### View Current Configuration

```bash
# Login to Azure
az login

# Function App
az functionapp show --resource-group rmhazure_rg --name rmhgeoapibeta \
  --query "{name:name, runtime:siteConfig.linuxFxVersion, region:location}"

# Storage Account
az storage account show --name rmhazuregeo \
  --query "{name:name, sku:sku.name, kind:kind, region:location}"

# Service Bus
az servicebus namespace show --resource-group rmhazure_rg --name rmhazure \
  --query "{name:name, sku:sku.tier, region:location}"

# Service Bus Queues
az servicebus queue list --resource-group rmhazure_rg --namespace-name rmhazure \
  --query "[].{name:name, lock:lockDuration, retries:maxDeliveryCount}"

# PostgreSQL
az postgres flexible-server show --resource-group rmhazure_rg --name rmhpgflex \
  --query "{name:name, version:version, sku:sku.name, region:location}"

# Storage Containers
az storage container list --account-name rmhazuregeo --auth-mode login \
  --query "[].name" -o table
```

---

## 🔐 Critical Configuration Settings

### Function App (rmhgeoapibeta)
```json
{
  "runtime": "PYTHON|3.12",
  "alwaysOn": false,
  "minTlsVersion": "1.2",
  "ftpsState": "FtpsOnly",
  "managedIdentity": "SystemAssigned (enabled)",
  "principalId": "995badc6-9b03-481f-9544-9f5957dd893d"
}
```

**App Settings**:
```bash
FUNCTIONS_WORKER_RUNTIME=python
FUNCTIONS_EXTENSION_VERSION=~4
ServiceBusConnection__fullyQualifiedNamespace=rmhazure.servicebus.windows.net
```

### Storage Account (rmhazuregeo)
```json
{
  "sku": "Standard_RAGRS",
  "kind": "StorageV2",
  "enableHttpsTrafficOnly": true,
  "allowBlobPublicAccess": true,
  "minTlsVersion": "TLS1_2"
}
```

**Key Containers**:
- `rmhazuregeobronze` - Raw data ingestion
- `rmhazuregeosilver` - Processed COGs
- `rmhazuregeogold` - GeoParquet exports
- `rmhazuregeotemp` - Temporary processing
- `silver-cogs`, `silver-tiles`, `silver-vectors`, `silver-stac-assets`

### Service Bus (rmhazure)
```json
{
  "sku": "Standard",
  "queues": [
    {
      "name": "geospatial-jobs",
      "lockDuration": "PT5M",
      "maxDeliveryCount": 3,
      "maxSizeInMegabytes": 1024
    },
    {
      "name": "geospatial-tasks",
      "lockDuration": "PT5M",
      "maxDeliveryCount": 3,
      "maxSizeInMegabytes": 1024
    }
  ]
}
```

### PostgreSQL (rmhpgflex)
```json
{
  "version": "17",
  "sku": "Standard_B1ms",
  "tier": "Burstable",
  "storageSizeGb": 32,
  "highAvailability": "Disabled",
  "extensions": ["postgis", "postgis_topology", "pgcrypto", "uuid-ossp", "hstore"],
  "schemas": ["geo", "app", "pgstac", "platform"]
}
```

**Firewall Rules**:
- `0.0.0.0` - Allow all Azure services (for Function App access)
- Multiple client IPs for direct access

---

## 🔗 Configuration Harmonization (CRITICAL!)

### Three-Layer Architecture
```
Layer 1: Service Bus (Azure Resource)
  ├─ lockDuration: PT5M (5 minutes)
  ├─ maxDeliveryCount: 3

Layer 2: Azure Functions (host.json)
  ├─ functionTimeout: "00:30:00" (30 minutes)
  ├─ maxAutoLockRenewalDuration: "00:30:00"
  ├─ maxConcurrentCalls: 1
  ├─ autoComplete: true

Layer 3: Application (config.py)
  ├─ function_timeout_minutes: 30
  ├─ task_max_retries: 3
  ├─ task_retry_base_delay: 5
```

**Validation Rule**:
```
lockDuration (PT5M) ≤ maxAutoLockRenewalDuration (00:30:00)
                    = functionTimeout (00:30:00)
                    = function_timeout_minutes (30)
```

---

## 🔐 Managed Identity & RBAC

### Function App Managed Identity
- **Type**: System-assigned
- **Principal ID**: `995badc6-9b03-481f-9544-9f5957dd893d`

### Required Role Assignments
```bash
# Storage access
az role assignment create \
  --assignee 995badc6-9b03-481f-9544-9f5957dd893d \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/<sub>/resourceGroups/rmhazure_rg/providers/Microsoft.Storage/storageAccounts/rmhazuregeo

# Service Bus access
az role assignment create \
  --assignee 995badc6-9b03-481f-9544-9f5957dd893d \
  --role "Azure Service Bus Data Owner" \
  --scope /subscriptions/<sub>/resourceGroups/rmhazure_rg/providers/Microsoft.ServiceBus/namespaces/rmhazure
```

---

## 🚀 Deployment Commands

### Deploy Function App
```bash
cd /path/to/rmhgeoapi
func azure functionapp publish rmhgeoapibeta --python --build remote
```

### Deploy Database Schema
```bash
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/schema/redeploy?confirm=yes
```

### Test Deployment
```bash
# Health check
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health

# Submit test job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/hello_world \
  -H "Content-Type: application/json" \
  -d '{"message": "test", "n": 3}'
```

---

## 📊 Resource Costs (Current Environment)

| Resource | SKU | Est. Cost/Month |
|----------|-----|-----------------|
| Function App (Consumption) | Pay-per-execution | $5-20 |
| Storage (Standard_RAGRS) | ~100 GB | $30-50 |
| Service Bus (Standard) | 2 queues | $10 |
| PostgreSQL (B1ms) | 1 vCore, 32 GB | $30-40 |
| **Total** | | **~$75-120/month** |

---

## 🔍 Monitoring & Debugging

### Application Insights
- **App ID**: `829adb94-5f5c-46ae-9f00-18e731529222`
- **Access**: Via Azure Portal or Azure CLI

### Key Monitoring Endpoints
```bash
# Database stats
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/stats

# Job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/jobs?limit=10

# Task status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/db/tasks/{JOB_ID}
```

### Service Bus Queue Depth
```bash
az servicebus queue show \
  --resource-group rmhazure_rg \
  --namespace-name rmhazure \
  --name geospatial-tasks \
  --query "countDetails.{active:activeMessageCount, deadletter:deadLetterMessageCount}"
```

---

## 📚 Related Documentation

- **CORPORATE_AZURE_CONFIG_REQUEST.md** - Full corporate deployment guide
- **SERVICE_BUS_HARMONIZATION.md** - Three-layer config architecture
- **DEPLOYMENT_GUIDE.md** - Deployment procedures
- **CLAUDE_CONTEXT.md** - System overview

---

## ✅ Pre-Deployment Checklist

**Azure Resources**:
- [ ] Resource group created
- [ ] Function App created with Python 3.12 runtime
- [ ] Storage Account created (Standard_RAGRS or better)
- [ ] Service Bus namespace created (Standard tier)
- [ ] PostgreSQL Flexible Server created (version 17+)
- [ ] Managed identity enabled on Function App

**Configuration**:
- [ ] Service Bus queues created (`geospatial-jobs`, `geospatial-tasks`)
- [ ] Service Bus lock duration = PT5M
- [ ] Service Bus max delivery count = 3
- [ ] Storage containers created (bronze, silver, gold, temp)
- [ ] PostgreSQL firewall rules configured
- [ ] PostgreSQL extensions installed (postgis, pgcrypto, etc.)
- [ ] RBAC roles assigned to managed identity

**Deployment**:
- [ ] Code deployed via `func azure functionapp publish`
- [ ] Database schema deployed via `/api/db/schema/redeploy`
- [ ] Health endpoint responding
- [ ] Test job submitted successfully

**Validation**:
- [ ] host.json `functionTimeout` = 00:30:00
- [ ] host.json `maxAutoLockRenewalDuration` = 00:30:00
- [ ] config.py `function_timeout_minutes` = 30
- [ ] Service Bus `lockDuration` ≤ `maxAutoLockRenewalDuration`

---

**Document Status**: Ready for Use
**Last Updated**: 5 NOV 2025