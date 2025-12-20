# Environment Variables Reference

**Last Updated**: 19 DEC 2025
**Purpose**: Complete reference for all environment variables used by the platform

---

## Quick Start

For a new deployment, you **must** configure the variables in Section 1 (Required).
Sections 2-6 have sensible defaults but can be customized.

---

## 1. REQUIRED: Environment-Specific Configuration

These variables have **no defaults** or require environment-specific values. The application will fail or behave incorrectly without them.

### 1.1 Azure Component Names

| Variable | Description | Example |
|----------|-------------|---------|
| `STORAGE_ACCOUNT_NAME` | **Bronze/Silver Storage Account** name | `mystorageaccount` |
| `SERVICE_BUS_NAMESPACE` | **Service Bus** namespace (without `.servicebus.windows.net`) | `myservicebus` |
| `POSTGIS_HOST` | **App Database** server hostname | `myserver.postgres.database.azure.com` |
| `POSTGIS_DATABASE` | **App Database** name | `geodb` |

### 1.2 Authentication

| Variable | Description | Default |
|----------|-------------|---------|
| `USE_MANAGED_IDENTITY` | Use Azure Managed Identity for auth | `true` |
| `DB_ADMIN_MANAGED_IDENTITY_NAME` | Name of **App Admin Identity** | — |
| `DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID` | Client ID of **App Admin Identity** | — |

**If `USE_MANAGED_IDENTITY=false`** (local dev only):

| Variable | Description |
|----------|-------------|
| `POSTGIS_USER` | Database username |
| `POSTGIS_PASSWORD` | Database password |

### 1.3 Service URLs

| Variable | Description | Example |
|----------|-------------|---------|
| `TITILER_BASE_URL` | **TiTiler Raster Service** URL | `https://mytitiler.azurewebsites.net` |
| `OGC_STAC_APP_URL` | **Reader Function App** URL (STAC/OGC Features) | `https://myreader.azurewebsites.net` |
| `ETL_APP_URL` | **ETL Function App** URL (self-reference for callbacks) | `https://myetl.azurewebsites.net` |

### 1.4 Service Bus Connection

One of these is required:

| Variable | Description |
|----------|-------------|
| `ServiceBusConnection` | Full connection string (Azure Functions binding) |
| `ServiceBusConnection__fullyQualifiedNamespace` | FQDN for managed identity auth |

---

## 2. Database Configuration

### 2.1 App Database (Primary)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGIS_PORT` | `5432` | PostgreSQL port |
| `POSTGIS_SCHEMA` | `geo` | PostGIS/vector data schema |
| `APP_SCHEMA` | `app` | Job/task orchestration schema |
| `PGSTAC_SCHEMA` | `pgstac` | STAC catalog schema |
| `H3_SCHEMA` | `h3` | H3 analytics schema |
| `DB_CONNECTION_TIMEOUT` | `30` | Connection timeout in seconds |

### 2.2 Business Database (Optional - Separate DB)

Set these only if using a separate database for business data:

| Variable | Default | Description |
|----------|---------|-------------|
| `BUSINESS_DB_HOST` | *(falls back to POSTGIS_HOST)* | Separate host for business data |
| `BUSINESS_DB_NAME` | `ddhgeodb` | Business database name |
| `BUSINESS_DB_PORT` | `5432` | Business database port |
| `BUSINESS_DB_SCHEMA` | `geo` | Business data schema |
| `BUSINESS_DB_CONNECTION_TIMEOUT` | `30` | Connection timeout |

---

## 3. Service Bus Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_BUS_JOBS_QUEUE` | `geospatial-jobs` | **Job Queue** name |
| `SERVICE_BUS_VECTOR_TASKS_QUEUE` | `vector-tasks` | **Vector Task Queue** name |
| `SERVICE_BUS_RASTER_TASKS_QUEUE` | `raster-tasks` | **Raster Task Queue** name |
| `SERVICE_BUS_LONG_RUNNING_RASTER_TASKS_QUEUE` | `long-running-raster-tasks` | **Long-Running Task Queue** name |
| `SERVICE_BUS_MAX_BATCH_SIZE` | `100` | Max messages per batch |
| `SERVICE_BUS_BATCH_THRESHOLD` | `10` | Threshold for batch processing |
| `SERVICE_BUS_RETRY_COUNT` | `3` | Retry attempts for failed messages |

---

## 4. Storage Configuration

### 4.1 Bronze Tier (Raw Data)

| Variable | Default | Description |
|----------|---------|-------------|
| `BRONZE_RASTERS_CONTAINER` | `bronze-rasters` | Raw raster uploads |
| `BRONZE_VECTORS_CONTAINER` | `bronze-vectors` | Raw vector uploads |
| `BRONZE_MISC_CONTAINER` | `bronze-misc` | Miscellaneous raw data |
| `BRONZE_TEMP_CONTAINER` | `bronze-temp` | Temporary processing files |

### 4.2 Silver Tier (Processed Data)

| Variable | Default | Description |
|----------|---------|-------------|
| `SILVER_COGS_CONTAINER` | `silver-cogs` | Cloud-Optimized GeoTIFFs |
| `SILVER_RASTERS_CONTAINER` | `silver-rasters` | Processed rasters |
| `SILVER_VECTORS_CONTAINER` | `silver-vectors` | Processed vectors |
| `SILVER_TILES_CONTAINER` | `silver-tiles` | Pre-rendered tiles |
| `SILVER_MOSAICJSON_CONTAINER` | `silver-mosaicjson` | MosaicJSON definitions |
| `SILVER_STAC_ASSETS_CONTAINER` | `silver-stac-assets` | STAC asset storage |
| `SILVER_MISC_CONTAINER` | `silver-misc` | Miscellaneous processed data |
| `SILVER_TEMP_CONTAINER` | `silver-temp` | Temporary processing files |

### 4.3 Silver-External Tier (Partner Access)

| Variable | Default | Description |
|----------|---------|-------------|
| `SILVEREXT_COGS_CONTAINER` | `silverext-cogs` | COGs for external access |
| `SILVEREXT_RASTERS_CONTAINER` | `silverext-rasters` | Rasters for external access |
| `SILVEREXT_VECTORS_CONTAINER` | `silverext-vectors` | Vectors for external access |
| `SILVEREXT_TILES_CONTAINER` | `silverext-tiles` | Tiles for external access |
| `SILVEREXT_MOSAICJSON_CONTAINER` | `silverext-mosaicjson` | MosaicJSON for external access |
| `SILVEREXT_STAC_ASSETS_CONTAINER` | `silverext-stac-assets` | STAC assets for external access |

### 4.4 Gold Tier (Analytics/Export)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOLD_GEOPARQUET_CONTAINER` | `gold-geoparquet` | GeoParquet exports |
| `GOLD_H3_GRIDS_CONTAINER` | `gold-h3-grids` | H3 grid exports |
| `GOLD_TEMP_CONTAINER` | `gold-temp` | Temporary export files |

---

## 5. Processing Configuration

### 5.1 Raster Processing

| Variable | Default | Description |
|----------|---------|-------------|
| `RASTER_TARGET_CRS` | `EPSG:4326` | Target coordinate reference system |
| `RASTER_COG_COMPRESSION` | `lzw` | COG compression (`lzw`, `deflate`, `jpeg`, `webp`) |
| `RASTER_COG_TILE_SIZE` | `512` | COG internal tile size |
| `RASTER_COG_JPEG_QUALITY` | `85` | JPEG quality (1-100) |
| `RASTER_COG_IN_MEMORY` | `true` | Process COGs in memory |
| `RASTER_OVERVIEW_RESAMPLING` | `average` | Overview resampling method |
| `RASTER_REPROJECT_RESAMPLING` | `bilinear` | Reprojection resampling method |
| `RASTER_STRICT_VALIDATION` | `true` | Strict input validation |
| `RASTER_INTERMEDIATE_PREFIX` | `intermediate/` | Temp file prefix |
| `RASTER_MOSAICJSON_MAXZOOM` | `14` | Max zoom for MosaicJSON |
| `RASTER_SIZE_THRESHOLD_MB` | `100` | Size threshold for large raster handling |
| `RASTER_MAX_FILE_SIZE_MB` | `2048` | Maximum file size (2GB) |
| `RASTER_IN_MEMORY_THRESHOLD_MB` | `500` | Threshold for in-memory processing |
| `RASTER_COLLECTION_SIZE_LIMIT` | `1000` | Max items in a collection |

### 5.2 Vector Processing

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_TARGET_SCHEMA` | `geo` | Target PostGIS schema |
| `VECTOR_DEFAULT_CHUNK_SIZE` | `1000` | Rows per chunk |
| `VECTOR_AUTO_CHUNK_SIZING` | `true` | Auto-adjust chunk size |
| `VECTOR_CREATE_SPATIAL_INDEXES` | `true` | Create spatial indexes |
| `VECTOR_PICKLE_CONTAINER` | `bronze-temp` | Container for pickle files |
| `VECTOR_PICKLE_PREFIX` | `temp/vector_etl` | Prefix for pickle files |

### 5.3 H3 Analytics

| Variable | Default | Description |
|----------|---------|-------------|
| `H3_DEFAULT_RESOLUTION` | `4` | Default H3 resolution (0-15) |
| `H3_ENABLE_LAND_FILTER` | `true` | Filter to land cells only |
| `H3_SYSTEM_ADMIN0_TABLE` | `geo.admin0` | Admin0 boundaries table |
| `H3_SPATIAL_FILTER_TABLE` | `geo.land_mask` | Land mask table |

---

## 6. Application Configuration

### 6.1 App Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `etl` | Application mode (`etl`, `reader`, `full`) |
| `APP_NAME` | `rmhazuregeoapi` | Application name for logging |
| `ENVIRONMENT` | `dev` | Environment name (`dev`, `qa`, `uat`, `prod`) |

### 6.2 Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `FUNCTION_TIMEOUT_MINUTES` | `30` | Azure Function timeout |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `DEBUG_MODE` | `false` | Enable debug mode |
| `DEBUG_LOGGING` | `false` | Enable verbose debug logging |

### 6.3 Platform Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM_PRIMARY_CLIENT` | `ddh` | Primary client identifier |
| `PLATFORM_DEFAULT_ACCESS_LEVEL` | `OUO` | Default data access level |
| `PLATFORM_ACCESS_LEVELS` | `public,OUO,restricted` | Allowed access levels |
| `PLATFORM_REQUEST_ID_LENGTH` | `32` | Length of request IDs |
| `PLATFORM_WEBHOOK_ENABLED` | `false` | Enable job completion webhooks |
| `PLATFORM_WEBHOOK_RETRY_COUNT` | `3` | Webhook retry attempts |
| `PLATFORM_WEBHOOK_RETRY_DELAY` | `5` | Webhook retry delay (seconds) |

### 6.4 STAC Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `STAC_DEFAULT_COLLECTION` | `system-rasters` | Default STAC collection |

### 6.5 TiTiler Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `TITILER_MODE` | `pgstac` | TiTiler mode (`pgstac`, `cog`) |

---

## 7. Data Factory (E4: Data Externalization)

| Variable | Default | Description |
|----------|---------|-------------|
| `ADF_SUBSCRIPTION_ID` | — | Azure subscription ID |
| `ADF_RESOURCE_GROUP` | `rmhazure_rg` | Resource group for ADF |
| `ADF_FACTORY_NAME` | — | **Data Factory Instance** name |

---

## 8. DuckDB (Analytics Export)

| Variable | Default | Description |
|----------|---------|-------------|
| `DUCKDB_CONNECTION_TYPE` | `memory` | Connection type (`memory`, `file`) |
| `DUCKDB_DATABASE_PATH` | — | Path for file-based DuckDB |
| `DUCKDB_MEMORY_LIMIT` | `4GB` | Memory limit |
| `DUCKDB_THREADS` | `4` | Worker threads |
| `DUCKDB_ENABLE_SPATIAL` | `true` | Enable spatial extension |
| `DUCKDB_ENABLE_HTTPFS` | `true` | Enable HTTP filesystem |
| `DUCKDB_ENABLE_AZURE` | `true` | Enable Azure blob access |

---

## Environment-Specific Templates

### Local Development (`local.settings.json`)

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",

    "STORAGE_ACCOUNT_NAME": "your-storage-account",
    "POSTGIS_HOST": "localhost",
    "POSTGIS_DATABASE": "geodb",
    "POSTGIS_USER": "postgres",
    "POSTGIS_PASSWORD": "your-password",
    "USE_MANAGED_IDENTITY": "false",

    "SERVICE_BUS_NAMESPACE": "your-servicebus",
    "ServiceBusConnection": "Endpoint=sb://...",

    "ENVIRONMENT": "dev",
    "DEBUG_MODE": "true",
    "LOG_LEVEL": "DEBUG"
  }
}
```

### Azure Function App (Required Settings)

```
STORAGE_ACCOUNT_NAME=prodstorageaccount
POSTGIS_HOST=prodserver.postgres.database.azure.com
POSTGIS_DATABASE=geodb
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<guid>
SERVICE_BUS_NAMESPACE=prodservicebus
ServiceBusConnection__fullyQualifiedNamespace=prodservicebus.servicebus.windows.net
TITILER_BASE_URL=https://prodtitiler.azurewebsites.net
ENVIRONMENT=prod
```

---

## Validation

The `/api/health` endpoint shows configuration status:

```json
{
  "config": {
    "storage_account": "configured",
    "database": "connected",
    "service_bus": "connected",
    "managed_identity": "enabled"
  },
  "warnings": []
}
```

If required variables are missing, warnings will appear:
- `"using_defaults": true` — Environment-specific values not set
- `"missing_required": ["STORAGE_ACCOUNT_NAME"]` — Critical variables missing

---

**See Also**:
- [Component Glossary](./EPICS.md#component-glossary) — Abstract component names
- [WIKI_ONBOARDING.md](./WIKI_ONBOARDING.md) — Full setup guide
