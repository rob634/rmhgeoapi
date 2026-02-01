# Environment Variables Reference

**Last Updated**: 01 FEB 2026
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
| `BRONZE_STORAGE_ACCOUNT` | **Bronze Storage Account** (raw uploads) | `myaboronze` |
| `SILVER_STORAGE_ACCOUNT` | **Silver Storage Account** (processed data) | `myappsilver` |
| `SERVICE_BUS_FQDN` | **Service Bus** FQDN (full URL required) | `myservicebus.servicebus.windows.net` |
| `POSTGIS_HOST` | **App Database** server hostname | `myserver.postgres.database.azure.com` |
| `POSTGIS_DATABASE` | **App Database** name | `geodb` |
| `APP_NAME` | **Function App** name for task tracking | `<platform-function-app>` |

**Note**: `STORAGE_ACCOUNT_NAME` was deprecated 08 DEC 2025. Use zone-specific accounts instead.

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

### 1.5 Database Schema Names (REQUIRED - No Defaults)

**Changed 23 DEC 2025**: Schema names now REQUIRE explicit configuration. No fallback defaults.

| Variable | Description | Standard Value |
|----------|-------------|----------------|
| `POSTGIS_SCHEMA` | PostGIS/vector data schema | `geo` |
| `APP_SCHEMA` | Job/task orchestration schema | `app` |
| `PGSTAC_SCHEMA` | STAC catalog schema | `pgstac` |

---

## 2. Database Configuration

### 2.1 App Database (Primary)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGIS_PORT` | `5432` | PostgreSQL port |
| `DB_CONNECTION_TIMEOUT` | `30` | Connection timeout in seconds |

**Note**: Schema names (`POSTGIS_SCHEMA`, `APP_SCHEMA`, `PGSTAC_SCHEMA`) moved to Section 1.5 — they are now REQUIRED with no defaults.

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
| `SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE` | `long-running-tasks` | **Long-Running Task Queue** (Docker worker) |
| `SERVICE_BUS_MAX_BATCH_SIZE` | `100` | Max messages per batch |
| `SERVICE_BUS_BATCH_THRESHOLD` | `50` | Threshold for batch processing |
| `SERVICE_BUS_RETRY_COUNT` | `3` | Retry attempts for failed messages |

**Note**: Queue renamed from `long-running-raster-tasks` to `long-running-tasks` on 22 DEC 2025.

---

## 4. Storage Configuration

### 4.0 Zone Storage Accounts

Each trust zone can have its own storage account. Required accounts are in Section 1.1.

| Variable | Default | Description |
|----------|---------|-------------|
| `BRONZE_STORAGE_ACCOUNT` | — | **REQUIRED** - Raw uploads zone |
| `SILVER_STORAGE_ACCOUNT` | — | **REQUIRED** - Processed data zone |
| `SILVEREXT_STORAGE_ACCOUNT` | *(falls back to SILVER)* | External/airgapped zone |
| `GOLD_STORAGE_ACCOUNT` | *(falls back to SILVER)* | Analytics exports zone |

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

---

## 6. Application Configuration

### 6.1 App Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `etl` | Application mode (`etl`, `reader`, `full`) |
| `APP_NAME` | `<platform-function-app>` | Application name for logging |
| `ENVIRONMENT` | `dev` | Environment name (`dev`, `qa`, `uat`, `prod`) |

### 6.2 Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `FUNCTION_TIMEOUT_MINUTES` | `30` | Azure Function timeout |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

### 6.3 Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVABILITY_MODE` | `false` | **Master switch** for all debug instrumentation |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG` for verbose logging) |
| `SERVICE_LATENCY_SLOW_MS` | `2000` | Threshold (ms) for slow operation warnings |
| `METRICS_FLUSH_INTERVAL` | `60` | Seconds between metrics blob flushes |
| `METRICS_BUFFER_SIZE` | `100` | Max records before auto-flush |
| `METRICS_BLOB_CONTAINER` | `applogs` | Container for metrics JSON files |

**When `OBSERVABILITY_MODE=true`:**
- Memory/CPU tracking enabled (`log_memory_checkpoint`)
- Service latency tracking (`[SERVICE_LATENCY]` logs)
- Database latency tracking (`[DB_LATENCY]` logs)
- Metrics buffered and written to blob storage as JSON Lines
- Blob path: `applogs/service-metrics/{date}/{instance_id}/{timestamp}.jsonl`

**Legacy Flags (backward compatible):**

| Variable | Status | Replacement |
|----------|--------|-------------|
| `DEBUG_MODE` | Legacy | Use `OBSERVABILITY_MODE` |
| `METRICS_DEBUG_MODE` | Legacy | Use `OBSERVABILITY_MODE` |
| `DEBUG_LOGGING` | Removed | Use `LOG_LEVEL=DEBUG` |

**Use for QA debugging** in opaque corporate Azure environments where VNet/ASE complexity may cause performance issues. Zero overhead when disabled.

### 6.4 Platform Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM_PRIMARY_CLIENT` | `ddh` | Primary client identifier |
| `PLATFORM_DEFAULT_ACCESS_LEVEL` | `OUO` | Default data access level |
| `PLATFORM_ACCESS_LEVELS` | `public,OUO,restricted` | Allowed access levels |
| `PLATFORM_REQUEST_ID_LENGTH` | `32` | Length of request IDs |
| `PLATFORM_WEBHOOK_ENABLED` | `false` | Enable job completion webhooks |
| `PLATFORM_WEBHOOK_RETRY_COUNT` | `3` | Webhook retry attempts |
| `PLATFORM_WEBHOOK_RETRY_DELAY` | `5` | Webhook retry delay (seconds) |

### 6.5 STAC Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `STAC_DEFAULT_COLLECTION` | `system-rasters` | Default STAC collection |

### 6.6 TiTiler Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `TITILER_MODE` | `pgstac` | TiTiler mode (`pgstac`, `cog`) |

---

## 7. Data Factory (E4: Data Externalization)

| Variable | Default | Description |
|----------|---------|-------------|
| `ADF_SUBSCRIPTION_ID` | — | Azure subscription ID |
| `ADF_RESOURCE_GROUP` | `<resource-group>` | Resource group for ADF |
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

## 9. Docker Worker (V0.8 Heavy Processing)

The Docker Worker handles memory-intensive operations (large rasters, vector ETL) in a dedicated container with blob storage mount.

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKER_WORKER_ENABLED` | `false` | Enable routing to Docker Worker |
| `DOCKER_WORKER_URL` | — | Docker Worker base URL (required if enabled) |

**Example:**
```
DOCKER_WORKER_ENABLED=true
DOCKER_WORKER_URL=https://myheavyapi.azurewebsites.net
```

**When `DOCKER_WORKER_ENABLED=true`:**
- Vector ETL jobs route to `long-running-tasks` queue
- Large raster processing routes to Docker Worker
- Docker Worker must have blob storage mounted at `/mnt/azure`

**Docker Worker Container Settings** (set on the Web App, not Function App):

| Variable | Description |
|----------|-------------|
| `WEBSITES_ENABLE_APP_SERVICE_STORAGE` | Set to `false` for container apps |
| `AZURE_STORAGE_ACCOUNT` | Storage account for blob mount |
| `AZURE_STORAGE_ACCESS_KEY` | Storage account access key |

See [DOCKER_INTEGRATION.md](../architecture/DOCKER_INTEGRATION.md) for full setup guide.

---

## Environment-Specific Templates

### Local Development (`local.settings.json`)

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",

    "BRONZE_STORAGE_ACCOUNT": "your-storage-account",
    "SILVER_STORAGE_ACCOUNT": "your-storage-account",
    "POSTGIS_HOST": "localhost",
    "POSTGIS_DATABASE": "geodb",
    "POSTGIS_USER": "postgres",
    "POSTGIS_PASSWORD": "your-password",
    "USE_MANAGED_IDENTITY": "false",

    "POSTGIS_SCHEMA": "geo",
    "APP_SCHEMA": "app",
    "PGSTAC_SCHEMA": "pgstac",

    "APP_NAME": "local-dev",
    "SERVICE_BUS_FQDN": "your-servicebus.servicebus.windows.net",
    "ServiceBusConnection": "Endpoint=sb://...",

    "ENVIRONMENT": "dev",
    "DEBUG_MODE": "true",
    "LOG_LEVEL": "DEBUG"
  }
}
```

### Azure Function App (Required Settings)

```
# Storage (zone-based)
BRONZE_STORAGE_ACCOUNT=myappbronze
SILVER_STORAGE_ACCOUNT=myappsilver

# Database
POSTGIS_HOST=prodserver.postgres.database.azure.com
POSTGIS_DATABASE=geodb
POSTGIS_SCHEMA=geo
APP_SCHEMA=app
PGSTAC_SCHEMA=pgstac

# Authentication
USE_MANAGED_IDENTITY=true
DB_ADMIN_MANAGED_IDENTITY_CLIENT_ID=<guid>

# Service Bus (use FQDN - full URL)
SERVICE_BUS_FQDN=prodservicebus.servicebus.windows.net
# Note: ServiceBusConnection__fullyQualifiedNamespace is set automatically by Azure Functions bindings

# Service URLs
TITILER_BASE_URL=https://prodtitiler.azurewebsites.net
ETL_APP_URL=https://prodetl.azurewebsites.net
OGC_STAC_APP_URL=https://prodogcstac.azurewebsites.net

# App Identity
APP_NAME=<platform-function-app>
ENVIRONMENT=prod
```

---

## Validation (08 JAN 2026 - Regex-based)

Environment variables are validated at startup with **regex patterns** to catch format errors, not just missing values. This prevents silent misconfigurations like setting `SERVICE_BUS_FQDN=myservicebus` instead of `SERVICE_BUS_FQDN=myservicebus.servicebus.windows.net`.

### Validation Rules

| Variable | Pattern | Example |
|----------|---------|---------|
| `SERVICE_BUS_FQDN` | Must end in `.servicebus.windows.net` | `mybus.servicebus.windows.net` |
| `POSTGIS_HOST` | Must be `localhost` or end in `.postgres.database.azure.com` | `myserver.postgres.database.azure.com` |
| `BRONZE_STORAGE_ACCOUNT` | Lowercase alphanumeric, 3-24 chars | `myappbronze` |
| `*_SCHEMA` | Lowercase letters/numbers/underscore | `geo`, `app`, `pgstac` |

### Health Check Validation

The `/api/health` and `/api/readyz` endpoints show validation status:

```json
{
  "env_vars": {
    "passed": true,
    "details": {
      "message": "All environment variables validated successfully",
      "required_vars_checked": 9
    }
  }
}
```

### Validation Errors

If validation fails, you'll see detailed error messages in Azure Portal → Function App → Log stream:

```
❌ STARTUP: Environment variable validation failed (1 errors):
  - SERVICE_BUS_FQDN: Invalid format
    Current: 'myservicebus'
    Expected: Must be full FQDN ending in .servicebus.windows.net
    Fix: Use full URL like 'myservicebus.servicebus.windows.net' (not just 'myservicebus')
```

You can also check the `/api/readyz` endpoint which returns detailed validation errors in the response body.

### Adding New Validation Rules

Validation rules are defined in `config/env_validation.py`:

```python
from config.env_validation import ENV_VAR_RULES, EnvVarRule
import re

# Add a new rule
ENV_VAR_RULES["MY_NEW_VAR"] = EnvVarRule(
    pattern=re.compile(r"^[a-z]+$"),
    pattern_description="Lowercase letters only",
    required=True,
    fix_suggestion="Use lowercase letters",
    example="myvalue",
)
```

---

## Related Documentation

- [Health Endpoints](../api-reference/HEALTH.md) — Startup validation and `/api/readyz` error details
- [Platform API](../api-reference/PLATFORM_API.md) — API reference
- [Quick Start](../getting-started/QUICK_START.md) — Getting started guide
