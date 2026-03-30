# Environment Variables — QA/UAT Deployment Guide

**Last Updated**: 30 MAR 2026
**Version**: v0.10.9.7
**Source of Truth**: `config/` module (Pydantic-based, composition pattern)

---

## Overview

The Geospatial API is a 3-app architecture. All apps share the same codebase but run in different `APP_MODE`s. Environment variables control which capabilities each app activates.

| Role | App Name (Dev) | APP_MODE | Runtime | Purpose |
|------|---------------|----------|---------|---------|
| **Function App** | `rmhazuregeoapi` | `standalone` | Azure Functions (Python) | API gateway + legacy orchestration |
| **Docker Worker** | `rmhheavyapi` | `worker_docker` | Docker (Azure Web App) | Heavy ETL processing (GDAL, rasterio) |
| **DAG Brain** | `rmhdagmaster` | `orchestrator` | Docker (Azure Web App) | DAG workflow orchestration + admin UI |

**Docker Worker and DAG Brain share the same Docker image** (from ACR). `APP_MODE` selects behavior at startup.

---

## How To Use This Document

1. Create all Azure resources (DB, storage accounts, containers, Service Bus) first
2. Replace `{placeholder}` values with your environment-specific values
3. Apply settings per app using `az functionapp config appsettings set` or `az webapp config appsettings set`
4. Deploy code/image
5. Run `/api/preflight` on each app to validate configuration

---

## Shared Infrastructure Requirements

Before setting environment variables, these Azure resources must exist:

| Resource | Dev Value | QA/UAT Value |
|----------|-----------|-------------|
| PostgreSQL Flexible Server | `rmhpostgres.postgres.database.azure.com` | `{your-pg-server}.postgres.database.azure.com` |
| Database name | `geopgflex` | `{your-database}` |
| Bronze storage account | `rmhazuregeo` | `{your-bronze-account}` |
| Silver storage account | `rmhstorage123` | `{your-silver-account}` |
| Service Bus namespace | `rmhazure.servicebus.windows.net` | `{your-sb-namespace}.servicebus.windows.net` |
| Application Insights | (shared across all 3 apps) | `{your-appinsights}` |
| Container Registry | `rmhazureacr.azurecr.io` | `{your-acr}.azurecr.io` |
| TiTiler instance | `rmhtitiler-*.azurewebsites.net` | `{your-titiler-url}` |
| User-Assigned Managed Identity (DB Admin) | `rmhpgflexadmin` | `{your-db-admin-umi}` |
| User-Assigned Managed Identity (DB Reader) | `rmhpgflexreader` | `{your-db-reader-umi}` (Function App only) |

### Required Storage Containers

Create these containers in the appropriate storage accounts:

| Container | Storage Account | Purpose |
|-----------|----------------|---------|
| `rmhazuregeobronze` (or `bronze-rasters`) | Bronze | Raw uploaded rasters + vectors |
| `bronze-temp` | Bronze | Temporary processing files |
| `silver-cogs` | Silver | Cloud-Optimized GeoTIFFs + STAC assets |
| `silver-vectors` | Silver | Processed vector data |
| `silver-rasters` | Silver | Processed raster data |
| `silver-tiles` | Silver | Raster tiles |
| `silver-temp` | Silver | Temporary silver files |
| `silver-zarr` | Silver | Zarr stores (NetCDF/Zarr ingest) |

### Required Database Schemas

Created automatically by `POST /api/dbadmin/maintenance?action=rebuild&confirm=yes`:

| Schema | Owner | Purpose |
|--------|-------|---------|
| `app` | DB Admin UMI | Jobs, tasks, assets, releases, DAG tables (34 tables) |
| `pgstac` | DB Admin UMI | STAC catalog (collections, items, searches) |
| `geo` | DB Admin UMI | Vector data tables (created per-dataset) |
| `h3` | DB Admin UMI | H3 hexagonal grid indexes |

### Required Database Extensions

| Extension | Schema | Purpose |
|-----------|--------|---------|
| `postgis` | public | Spatial data types and functions |
| `h3` | public | H3 hexagonal indexing |

### Required RBAC Roles

| Principal | Role | Scope | Purpose |
|-----------|------|-------|---------|
| Each app's system-assigned managed identity | `Monitoring Metrics Publisher` | App Insights resource | Telemetry export |
| DB Admin UMI | PostgreSQL `azure_pg_admin` | Database | Schema create/drop/alter |
| DB Reader UMI | PostgreSQL read-only | Database | TiPG read access |
| Each app's system-assigned managed identity | `Storage Blob Data Contributor` | Storage accounts | Blob read/write |

---

## 1. Function App (APP_MODE=standalone)

### Required Settings

```bash
az functionapp config appsettings set \
  --name {your-function-app} \
  --resource-group {your-rg} \
  --settings \
    APP_MODE=standalone \
    APP_NAME={your-function-app} \
    ENVIRONMENT={dev|qa|uat|prod} \
    POSTGIS_HOST={your-pg-server}.postgres.database.azure.com \
    POSTGIS_PORT=5432 \
    POSTGIS_DATABASE={your-database} \
    POSTGIS_SCHEMA=geo \
    APP_SCHEMA=app \
    PGSTAC_SCHEMA=pgstac \
    H3_SCHEMA=h3 \
    USE_MANAGED_IDENTITY=true \
    DB_ADMIN_MANAGED_IDENTITY_NAME={your-db-admin-umi} \
    DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID={your-db-admin-umi-client-id} \
    DB_READER_MANAGED_IDENTITY_NAME={your-db-reader-umi} \
    BRONZE_STORAGE_ACCOUNT={your-bronze-account} \
    BRONZE_RASTERS_CONTAINER={your-bronze-container} \
    BRONZE_VECTORS_CONTAINER={your-bronze-container} \
    SILVER_STORAGE_ACCOUNT={your-silver-account} \
    SILVER_COGS_CONTAINER=silver-cogs \
    SERVICE_BUS_FQDN={your-sb-namespace}.servicebus.windows.net \
    PLATFORM_URL=https://{your-function-app}.azurewebsites.net \
    TITILER_BASE_URL=https://{your-titiler-url} \
    DOCKER_WORKER_ENABLED=true \
    DOCKER_WORKER_URL=https://{your-docker-worker-url} \
    APPLICATIONINSIGHTS_CONNECTION_STRING={your-appinsights-connection-string} \
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING="Authorization=AAD" \
    APPINSIGHTS_APP_ID={your-appinsights-app-id} \
    LOG_LEVEL=INFO \
    OBSERVABILITY_MODE=true
```

### Optional Settings (with defaults)

| Setting | Default | Notes |
|---------|---------|-------|
| `RASTER_COLLECTION_MAX_FILES` | 20 | Max files per submission |
| `RASTER_TILE_TARGET_MB` | 400 | Target tile size (MB) |
| `ENABLE_DATABASE_HEALTH_CHECK` | true | Include DB in health check |
| `VERBOSE_LOG_DUMP` | false | Enable verbose debug logs |
| `AUTH_GATES_ENABLED` | false | Enable RBAC gates (future) |
| `PLATFORM_PRIMARY_CLIENT` | ddh | Platform client identifier |
| `PLATFORM_DEFAULT_ACCESS_LEVEL` | OUO | Default access level |

### Azure Functions Platform Settings

These are set by Azure or required for the Functions runtime — not app code:

```bash
az functionapp config appsettings set \
  --name {your-function-app} \
  --resource-group {your-rg} \
  --settings \
    FUNCTIONS_EXTENSION_VERSION=~4 \
    FUNCTIONS_WORKER_RUNTIME=python \
    SCM_DO_BUILD_DURING_DEPLOYMENT=1 \
    ENABLE_ORYX_BUILD=true \
    AzureWebJobsStorage__blobServiceUri=https://{your-storage}.blob.core.windows.net \
    AzureWebJobsStorage__credential=managedidentity \
    AzureWebJobsStorage__queueServiceUri=https://{your-storage}.queue.core.windows.net \
    AzureWebJobsStorage__tableServiceUri=https://{your-storage}.table.core.windows.net
```

### Service Bus Binding (Azure Functions)

For the Functions Service Bus trigger binding (separate from app-level `SERVICE_BUS_FQDN`):

```bash
az functionapp config appsettings set \
  --name {your-function-app} \
  --resource-group {your-rg} \
  --settings \
    ServiceBusConnection__fullyQualifiedNamespace={your-sb-namespace}.servicebus.windows.net \
    ServiceBusConnection__credential=managedidentity
```

### Optional: Azure Data Factory (for external data migration)

Only needed if using ADF pipelines for cross-environment data sync:

```bash
az functionapp config appsettings set \
  --name {your-function-app} \
  --resource-group {your-rg} \
  --settings \
    ADF_SUBSCRIPTION_ID={your-subscription-id} \
    ADF_RESOURCE_GROUP={your-rg} \
    ADF_FACTORY_NAME={your-adf-name} \
    ADF_BLOB_PIPELINE_NAME=blob_internal_to_external
```

### Optional: Key Vault (for health diagnostics)

Used by health checks to report credential configuration status:

```bash
az functionapp config appsettings set \
  --name {your-function-app} \
  --resource-group {your-rg} \
  --settings \
    KEY_VAULT={your-keyvault-name} \
    KEY_VAULT_DATABASE_SECRET={your-db-password-secret-name}
```

---

## 2. Docker Worker (APP_MODE=worker_docker)

### Required Settings

```bash
az webapp config appsettings set \
  --name {your-docker-worker} \
  --resource-group {your-rg} \
  --settings \
    APP_MODE=worker_docker \
    APP_NAME={your-docker-worker} \
    ENVIRONMENT={dev|qa|uat|prod} \
    POSTGIS_HOST={your-pg-server}.postgres.database.azure.com \
    POSTGIS_PORT=5432 \
    POSTGIS_DATABASE={your-database} \
    POSTGIS_SCHEMA=geo \
    APP_SCHEMA=app \
    PGSTAC_SCHEMA=pgstac \
    H3_SCHEMA=h3 \
    USE_MANAGED_IDENTITY=true \
    DB_ADMIN_MANAGED_IDENTITY_NAME={your-db-admin-umi} \
    DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID={your-db-admin-umi-client-id} \
    BRONZE_STORAGE_ACCOUNT={your-bronze-account} \
    BRONZE_RASTERS_CONTAINER={your-bronze-container} \
    BRONZE_VECTORS_CONTAINER={your-bronze-container} \
    SILVER_STORAGE_ACCOUNT={your-silver-account} \
    SILVER_COGS_CONTAINER=silver-cogs \
    SERVICE_BUS_FQDN={your-sb-namespace}.servicebus.windows.net \
    SERVICE_BUS_JOBS_QUEUE=geospatial-jobs \
    SERVICE_BUS_CONTAINER_TASKS_QUEUE=container-tasks \
    PLATFORM_URL=https://{your-function-app}.azurewebsites.net \
    TITILER_BASE_URL=https://{your-titiler-url} \
    DOCKER_WORKER_ENABLED=false \
    DOCKER_USE_ETL_MOUNT=true \
    RASTER_ETL_MOUNT_PATH=/mount/etl-temp \
    APPLICATIONINSIGHTS_CONNECTION_STRING={your-appinsights-connection-string} \
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING="Authorization=AAD" \
    LOG_LEVEL=INFO \
    OBSERVABILITY_MODE=true \
    DOCKER_DB_POOL_MIN=2 \
    DOCKER_DB_POOL_MAX=10 \
    WEBSITES_ENABLE_APP_SERVICE_STORAGE=false
```

**Note**: `DOCKER_WORKER_ENABLED=false` on the worker itself — this setting controls whether the app *delegates* to a Docker worker, not whether it *is* one. The worker does not delegate to another worker.

### Optional Settings (with defaults)

| Setting | Default | Notes |
|---------|---------|-------|
| `RASTER_COG_COMPRESSION` | DEFLATE | COG compression algorithm |
| `RASTER_TARGET_CRS` | EPSG:4326 | Target coordinate reference system |
| `RASTER_TILE_TARGET_MB` | 400 | Target tile size |
| `RASTER_TILING_THRESHOLD_MB` | 2000 | File size threshold for tiling |
| `RASTER_COLLECTION_MAX_FILES` | 20 | Max files per collection |
| `VECTOR_TARGET_SCHEMA` | geo | Target schema for vector tables |
| `PLATFORM_PRIMARY_CLIENT` | ddh | Platform client identifier |
| `PLATFORM_DEFAULT_ACCESS_LEVEL` | OUO | Default access level |
| `PLATFORM_WEBHOOK_ENABLED` | false | Enable webhooks |

### Docker Container Settings (Azure Web App)

```bash
az webapp config container set \
  --name {your-docker-worker} \
  --resource-group {your-rg} \
  --docker-custom-image-name "{your-acr}.azurecr.io/geospatial-worker:{version}" \
  --docker-registry-server-url "https://{your-acr}.azurecr.io"
```

### Azure Files Mount (ETL Processing)

The Docker Worker requires an Azure Files mount for large file processing:

```bash
az webapp config storage-account add \
  --name {your-docker-worker} \
  --resource-group {your-rg} \
  --custom-id etl-temp \
  --storage-type AzureFiles \
  --share-name {your-file-share} \
  --account-name {your-storage-account} \
  --mount-path /mount/etl-temp
```

---

## 3. DAG Brain (APP_MODE=orchestrator)

### Required Settings

```bash
az webapp config appsettings set \
  --name {your-dag-brain} \
  --resource-group {your-rg} \
  --settings \
    APP_MODE=orchestrator \
    APP_NAME={your-dag-brain} \
    ENVIRONMENT={dev|qa|uat|prod} \
    POSTGIS_HOST={your-pg-server}.postgres.database.azure.com \
    POSTGIS_PORT=5432 \
    POSTGIS_DATABASE={your-database} \
    POSTGIS_SCHEMA=geo \
    APP_SCHEMA=app \
    PGSTAC_SCHEMA=pgstac \
    H3_SCHEMA=h3 \
    USE_MANAGED_IDENTITY=true \
    DB_ADMIN_MANAGED_IDENTITY_NAME={your-db-admin-umi} \
    DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID={your-db-admin-umi-client-id} \
    BRONZE_STORAGE_ACCOUNT={your-bronze-account} \
    BRONZE_RASTERS_CONTAINER={your-bronze-container} \
    BRONZE_VECTORS_CONTAINER={your-bronze-container} \
    SILVER_STORAGE_ACCOUNT={your-silver-account} \
    SERVICE_BUS_FQDN={your-sb-namespace}.servicebus.windows.net \
    SERVICE_BUS_JOBS_QUEUE=geospatial-jobs \
    SERVICE_BUS_CONTAINER_TASKS_QUEUE=container-tasks \
    PLATFORM_URL=https://{your-function-app}.azurewebsites.net \
    ORCHESTRATOR_URL=https://{your-function-app}.azurewebsites.net \
    TITILER_BASE_URL=https://{your-titiler-url} \
    DOCKER_WORKER_ENABLED=false \
    DOCKER_USE_ETL_MOUNT=true \
    APPLICATIONINSIGHTS_CONNECTION_STRING={your-appinsights-connection-string} \
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING="Authorization=AAD" \
    LOG_LEVEL=INFO \
    OBSERVABILITY_MODE=true \
    DOCKER_DB_POOL_MIN=1 \
    DOCKER_DB_POOL_MAX=3 \
    WEBSITES_ENABLE_APP_SERVICE_STORAGE=false
```

**Note**: `ORCHESTRATOR_URL` points to the **Function App** (not itself). The DAG Brain admin UI proxies API calls to the Function App via this URL.

### Docker Container Settings

Same image as the Docker Worker — `APP_MODE` selects behavior:

```bash
az webapp config container set \
  --name {your-dag-brain} \
  --resource-group {your-rg} \
  --docker-custom-image-name "{your-acr}.azurecr.io/geospatial-worker:{version}" \
  --docker-registry-server-url "https://{your-acr}.azurecr.io"
```

---

## 4. Optional: External Database (Cross-Environment Sync)

If the environment needs to replicate data to an external database:

```bash
# Apply to Function App and/or Docker Worker as needed
EXTERNAL_DB_HOST={external-pg-server}.postgres.database.azure.com
EXTERNAL_DB_NAME={external-database}
EXTERNAL_DB_PORT=5432
EXTERNAL_DB_SCHEMA=geo
EXTERNAL_DB_PGSTAC_SCHEMA=pgstac
EXTERNAL_DB_USE_MANAGED_IDENTITY=true
EXTERNAL_DB_MANAGED_IDENTITY_NAME={external-db-umi}
EXTERNAL_DB_MANAGED_IDENTITY_CLIENT_ID={external-db-umi-client-id}
EXTERNAL_STORAGE_ACCOUNT={external-storage-account}
EXTERNAL_TITILER_URL=https://{external-titiler-url}
```

---

## Validation

After deploying all 3 apps, run the preflight check on each:

```bash
# Function App
curl -s https://{your-function-app}.azurewebsites.net/api/preflight | python3 -m json.tool

# Docker Worker
curl -s https://{your-docker-worker}.azurewebsites.net/preflight | python3 -m json.tool

# DAG Brain
curl -s https://{your-dag-brain}.azurewebsites.net/preflight | python3 -m json.tool
```

The preflight response includes a `punch_list` array with exact eService requests for any failures:

```json
{
  "status": "fail",
  "mode": "standalone",
  "checks_run": 13,
  "checks_passed": 11,
  "checks_failed": 2,
  "punch_list": [
    {
      "check": "storage_token",
      "action": "Assign role",
      "azure_role": "Storage Blob Data Contributor",
      "scope": "Storage account: {account}",
      "eservice_summary": "Request 'Storage Blob Data Contributor' role for {app} system identity on storage account {account}"
    }
  ]
}
```

### Schema Initialization

After the Function App is healthy, initialize the database:

```bash
# Create all schemas and tables (DESTRUCTIVE — only for fresh environments)
curl -X POST "https://{your-function-app}.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&confirm=yes"

# Verify schema
curl -s "https://{your-function-app}.azurewebsites.net/api/dbadmin/diagnostics?type=stats"
```

### Health Check Endpoints

| App | Health | Liveness | Readiness |
|-----|--------|----------|-----------|
| Function App | `/api/health` | `/api/livez` | `/api/readyz` |
| Docker Worker | `/health` | `/livez` | `/readyz` |
| DAG Brain | `/health` | `/livez` | `/readyz` |

---

## Settings NOT Required (Common Mistakes)

These settings are **not needed** and should NOT be set. They are either deprecated or Azure-internal:

| Setting | Reason |
|---------|--------|
| `STORAGE_ACCOUNT_NAME` | Deprecated 08 DEC 2025 — use zone-specific accounts |
| `SILVER_CONTAINER_NAME` | Never used by code |
| `ETL_APP_URL` | Deprecated 24 MAR 2026 — replaced by `PLATFORM_URL` |
| `RASTER_ROUTE_DOCKER_MB` | Removed V0.8 (24 JAN 2026) |
| `RASTER_ROUTE_LARGE_MB` | Removed V0.8 (24 JAN 2026) |
| `RASTER_ROUTE_REJECT_MB` | Removed V0.8 (24 JAN 2026) |
| `RASTER_SIZE_THRESHOLD_MB` | Not in config code |
| `RASTER_MAX_FILE_SIZE_MB` | Not in config code |
| `RASTER_IN_MEMORY_THRESHOLD_MB` | Not in config code |
| `RASTER_WINDOWED_THRESHOLD_MB` | Not in config code |
| `RASTER_USE_ETL_MOUNT` | Legacy — use `DOCKER_USE_ETL_MOUNT` |
| `DEBUG_MODE` | Legacy — use `OBSERVABILITY_MODE` |
| `AZURE_STORAGE_ACCOUNT_NAME` | Set automatically by storage auth module |
| `POSTGIS_USER` / `POSTGIS_PASSWORD` | Not needed with managed identity |

---

## Quick Diff: Dev vs QA Template

| Setting | Dev (rmh*) | QA Template |
|---------|-----------|-------------|
| `POSTGIS_HOST` | `rmhpostgres.postgres.database.azure.com` | `{your-pg-server}.postgres.database.azure.com` |
| `POSTGIS_DATABASE` | `geopgflex` | `{your-database}` |
| `BRONZE_STORAGE_ACCOUNT` | `rmhazuregeo` | `{your-bronze-account}` |
| `BRONZE_RASTERS_CONTAINER` | `rmhazuregeobronze` | `{your-bronze-container}` |
| `BRONZE_VECTORS_CONTAINER` | `rmhazuregeobronze` | `{your-bronze-container}` |
| `SILVER_STORAGE_ACCOUNT` | `rmhstorage123` | `{your-silver-account}` |
| `SERVICE_BUS_FQDN` | `rmhazure.servicebus.windows.net` | `{your-sb}.servicebus.windows.net` |
| `DB_ADMIN_MANAGED_IDENTITY_NAME` | `rmhpgflexadmin` | `{your-db-admin-umi}` |
| `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | `a533cb80-a590-4fad-8e52-1eb1f72659d7` | `{your-umi-client-id}` |
| `TITILER_BASE_URL` | `https://rmhtitiler-*.azurewebsites.net` | `https://{your-titiler}` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | *(masked)* | `{your-appinsights-conn-string}` |
| `LOG_LEVEL` | `DEBUG` | `INFO` |
