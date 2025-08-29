# Azure Infrastructure Configuration

This document contains the environment variables and configuration for the rmhgeoapibeta Azure Function App.

## Function App Configuration

**Function App Name:** `rmhgeoapibeta`  
**Resource Group:** `rmhazure_rg`  
**Runtime:** Python 3.11+ with Azure Functions v4  

## Storage Configuration (Managed Identity)

The function app uses **Azure Managed Identity** for authentication instead of connection strings:

```bash
# Primary Storage Account
STORAGE_ACCOUNT_NAME=rmhazuregeo

# Managed Identity Configuration
AzureWebJobsStorage__blobServiceUri=https://rmhazuregeo.blob.core.windows.net
AzureWebJobsStorage__queueServiceUri=https://rmhazuregeo.queue.core.windows.net  
AzureWebJobsStorage__tableServiceUri=https://rmhazuregeo.table.core.windows.net
AzureWebJobsStorage__credential=managedidentity

Storage__blobServiceUri=https://rmhazuregeo.blob.core.windows.net
Storage__credential=managedidentity
```

## Container Names (Bronze→Silver→Gold ETL)

```bash
# Data Lake Containers
BRONZE_CONTAINER_NAME=rmhazuregeobronze
SILVER_CONTAINER_NAME=rmhazuregeosilver  
GOLD_CONTAINER_NAME=rmhazuregeogold
```

## PostgreSQL/PostGIS Database

```bash
# Database Configuration
POSTGIS_HOST=rmhpgflex.postgres.database.azure.com
POSTGIS_DATABASE=geopgflex
POSTGIS_USER=rob634
POSTGIS_PORT=5432
# POSTGIS_PASSWORD=[REDACTED] - Stored in Azure Key Vault or Environment
```

## Application Insights

```bash
# Monitoring and Logging
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=32ef235f-4bfc-416b-98e9-19b23fb266e1;IngestionEndpoint=https://eastus-8.in.applicationinsights.azure.com/;LiveEndpoint=https://eastus.livediagnostics.monitor.azure.com/;ApplicationId=829adb94-5f5c-46ae-9f00-18e731529222
APPLICATIONINSIGHTS_AUTHENTICATION_STRING=Authorization=AAD
```

## Azure Functions Runtime

```bash
# Runtime Configuration  
FUNCTIONS_EXTENSION_VERSION=~4
FUNCTIONS_WORKER_RUNTIME=python
BUILD_FLAGS=UseExpressBuild
ENABLE_ORYX_BUILD=true
SCM_DO_BUILD_DURING_DEPLOYMENT=1
```

## Feature Flags

```bash
# Optional Features
ENABLE_DATABASE_HEALTH_CHECK=true
WEBSITE_HEALTHCHECK_MAXPINGFAILURES=10
```

## Content Storage

```bash
# Function App Content
WEBSITE_CONTENTSHARE=rmhgeoapibetab242
# WEBSITE_CONTENTAZUREFILECONNECTIONSTRING=[REDACTED] - Contains storage key
```

## Environment Variables

```bash
# System Environment
XDG_CACHE_HOME=/tmp/.cache
```

## DefaultAzureCredential() Usage

The function app is configured to use **Azure Managed Identity** which works seamlessly with `DefaultAzureCredential()`:

1. **AzureWebJobsStorage**: Uses managed identity instead of connection strings
2. **Storage services**: All blob, queue, and table operations use managed identity  
3. **Authentication chain**: DefaultAzureCredential will use managed identity when deployed to Azure
4. **Local development**: Falls back to Azure CLI credentials or environment variables

## Required IAM Roles

The function app's managed identity should have:

- **Storage Blob Data Contributor** on rmhazuregeo storage account
- **Storage Queue Data Contributor** on rmhazuregeo storage account  
- **Storage Table Data Contributor** on rmhazuregeo storage account
- **Reader** role for resource discovery

## Security Best Practices

- ✅ **Managed Identity**: No storage keys in configuration
- ✅ **Key Vault Integration**: Sensitive values stored in Azure Key Vault
- ✅ **Connection String Rotation**: Managed by Azure platform
- ✅ **Least Privilege**: Function identity has minimal required permissions

## Local Development Setup

For local testing with DefaultAzureCredential():

1. **Azure CLI Login**: `az login` 
2. **Set Subscription**: `az account set --subscription [subscription-id]`
3. **Environment Variables**: Copy required vars to `local.settings.json`
4. **Managed Identity Simulation**: Uses your Azure CLI credentials

## Infrastructure Resources

- **Function App**: rmhgeoapibeta (East US)
- **Storage Account**: rmhazuregeo (East US)  
- **PostgreSQL**: rmhpgflex.postgres.database.azure.com (Flexible Server)
- **Application Insights**: East US region
- **Resource Group**: rmhazure_rg

---

*Generated on: 2025-08-29*  
*Source: `az functionapp config appsettings list --name rmhgeoapibeta --resource-group rmhazure_rg`*