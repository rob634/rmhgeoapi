# Environment Variables Reference

**Created**: 26 JAN 2026
**Source of Truth**: `config/env_validation.py`
**Total Variables**: 42 validated

---

## Quick Answers

### How do I specify APP_MODE?

```bash
# Azure Function App
az functionapp config appsettings set --name rmhazuregeoapi --resource-group rmhazure_rg \
  --settings APP_MODE=standalone

# Docker Worker
docker run -e APP_MODE=worker_docker ...

# Local .env file
APP_MODE=standalone
```

**Valid values**:
| Mode | Description | Queues Listening |
|------|-------------|------------------|
| `standalone` | Single app (dev) | jobs, functionapp-tasks |
| `platform` | HTTP gateway only | None (send-only) |
| `orchestrator` | Job router | geospatial-jobs |
| `worker_functionapp` | Lightweight worker | functionapp-tasks |
| `worker_docker` | Heavy worker (Docker) | container-tasks |

### How do I enable metrics/observability?

```bash
# Enable observability mode (memory tracking, latency logging)
OBSERVABILITY_MODE=true

# Set log level
LOG_LEVEL=DEBUG  # or INFO, WARNING, ERROR

# Enable metrics collection
METRICS_ENABLED=true
METRICS_DEBUG_MODE=true  # Extra verbose metrics
```

---

## All Environment Variables

### Required (9)

These MUST be set - app will fail to start without them.

| Variable | Pattern | Example |
|----------|---------|---------|
| `SERVICE_BUS_FQDN` | `*.servicebus.windows.net` | `mybus.servicebus.windows.net` |
| `POSTGIS_HOST` | Azure FQDN or localhost | `mydb.postgres.database.azure.com` |
| `POSTGIS_DATABASE` | Alphanumeric | `geodb` |
| `POSTGIS_SCHEMA` | Lowercase | `geo` |
| `APP_SCHEMA` | Lowercase | `app` |
| `PGSTAC_SCHEMA` | Lowercase | `pgstac` |
| `H3_SCHEMA` | Lowercase | `h3` |
| `BRONZE_STORAGE_ACCOUNT` | 3-24 lowercase chars | `myappbronze` |
| `SILVER_STORAGE_ACCOUNT` | 3-24 lowercase chars | `myappsilver` |

---

### App Mode & Docker (V0.8)

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_MODE` | `standalone` | Deployment mode (see table above) |
| `DOCKER_WORKER_ENABLED` | `false` | Enable Docker worker queue validation |
| `DOCKER_WORKER_URL` | None | Docker worker health check URL |

---

### Service Bus Queues

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_BUS_JOBS_QUEUE` | `geospatial-jobs` | Main job submission queue |
| `SERVICE_BUS_CONTAINER_TASKS_QUEUE` | `container-tasks` | Docker worker queue (V0.8) |
| `SERVICE_BUS_FUNCTIONAPP_TASKS_QUEUE` | `functionapp-tasks` | FunctionApp worker queue |
| `SERVICE_BUS_RASTER_TASKS_QUEUE` | `raster-tasks` | Legacy raster queue |
| `SERVICE_BUS_VECTOR_TASKS_QUEUE` | `vector-tasks` | Legacy vector queue |
| `SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE` | `long-running-tasks` | Legacy long-running queue |

---

### Raster Processing (V0.8)

| Variable | Default | Description |
|----------|---------|-------------|
| `RASTER_USE_ETL_MOUNT` | `true` | Enable Azure Files mount for temp files |
| `RASTER_ETL_MOUNT_PATH` | `/mnt/etl` | Mount path in Docker container |
| `RASTER_TILING_THRESHOLD_MB` | `2000` | Size above which files get tiled output |
| `RASTER_TILE_TARGET_MB` | `400` | Target size per tile |
| `RASTER_COG_COMPRESSION` | `LZW` | COG compression (LZW, DEFLATE, ZSTD, JPEG) |
| `RASTER_TARGET_CRS` | `EPSG:4326` | Target CRS for reprojection |

---

### Observability & Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSERVABILITY_MODE` | `false` | Enable debug instrumentation |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | None | App Insights telemetry (recommended) |
| `ENVIRONMENT` | `dev` | Environment name for log correlation |
| `APP_NAME` | None | App name for log correlation |

**Metrics-specific** (not validated, have safe defaults):
| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_ENABLED` | `true` | Enable metrics collection |
| `METRICS_DEBUG_MODE` | `false` | Extra verbose metrics |
| `METRICS_SAMPLE_INTERVAL` | `5` | Sample interval in seconds |

---

### Platform / Classification

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM_DEFAULT_ACCESS_LEVEL` | `internal` | Default data classification |
| `PLATFORM_PRIMARY_CLIENT` | `ddh` | Primary client identifier |
| `PLATFORM_WEBHOOK_ENABLED` | `false` | Enable DDH webhooks |

---

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGIS_PORT` | `5432` | PostgreSQL port |
| `USE_MANAGED_IDENTITY` | `true` | Use Azure Managed Identity for auth |
| `DB_ADMIN_MANAGED_IDENTITY_NAME` | None | Managed identity name |

---

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `SILVEREXT_STORAGE_ACCOUNT` | Falls back to SILVER | External silver storage |
| `GOLD_STORAGE_ACCOUNT` | Falls back to SILVER | Gold tier storage |

---

### Vector Processing

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_TARGET_SCHEMA` | `geo` | Target PostgreSQL schema |

---

### Service URLs

| Variable | Default | Description |
|----------|---------|-------------|
| `TITILER_BASE_URL` | None | TiTiler service URL |
| `ETL_APP_URL` | None | (Obsolete in V0.8) |
| `OGC_STAC_APP_URL` | None | External STAC API URL |

---

## Example Configurations

### Local Development

```bash
# .env file
APP_MODE=standalone
ENVIRONMENT=dev
LOG_LEVEL=DEBUG
OBSERVABILITY_MODE=true

# Required
SERVICE_BUS_FQDN=mybus.servicebus.windows.net
POSTGIS_HOST=localhost
POSTGIS_DATABASE=geodb
POSTGIS_SCHEMA=geo
APP_SCHEMA=app
PGSTAC_SCHEMA=pgstac
H3_SCHEMA=h3
BRONZE_STORAGE_ACCOUNT=mydevbronze
SILVER_STORAGE_ACCOUNT=mydevsilver
```

### Azure Function App (Production)

```bash
az functionapp config appsettings set --name rmhazuregeoapi --resource-group rmhazure_rg --settings \
  APP_MODE=standalone \
  ENVIRONMENT=prod \
  LOG_LEVEL=INFO \
  DOCKER_WORKER_ENABLED=true \
  DOCKER_WORKER_URL=https://rmhheavyapi-xxx.azurewebsites.net \
  SERVICE_BUS_FQDN=mybus.servicebus.windows.net \
  POSTGIS_HOST=mydb.postgres.database.azure.com \
  POSTGIS_DATABASE=geodb \
  POSTGIS_SCHEMA=geo \
  APP_SCHEMA=app \
  PGSTAC_SCHEMA=pgstac \
  H3_SCHEMA=h3 \
  BRONZE_STORAGE_ACCOUNT=mybronze \
  SILVER_STORAGE_ACCOUNT=mysilver \
  USE_MANAGED_IDENTITY=true
```

### Docker Worker

```bash
docker run -e APP_MODE=worker_docker \
  -e ENVIRONMENT=prod \
  -e SERVICE_BUS_FQDN=mybus.servicebus.windows.net \
  -e POSTGIS_HOST=mydb.postgres.database.azure.com \
  -e POSTGIS_DATABASE=geodb \
  -e POSTGIS_SCHEMA=geo \
  -e APP_SCHEMA=app \
  -e PGSTAC_SCHEMA=pgstac \
  -e H3_SCHEMA=h3 \
  -e BRONZE_STORAGE_ACCOUNT=mybronze \
  -e SILVER_STORAGE_ACCOUNT=mysilver \
  -e APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=..." \
  -e RASTER_USE_ETL_MOUNT=true \
  -e RASTER_ETL_MOUNT_PATH=/mnt/etl \
  myacr.azurecr.io/geospatial-worker:latest
```

---

## Validation

The app validates environment variables at startup. To see validation status:

```bash
# Check via health endpoint
curl https://myapp.azurewebsites.net/api/health | jq '.environment_validation'

# Or run validation locally
python -c "from config.env_validation import get_validation_summary; import json; print(json.dumps(get_validation_summary(), indent=2))"
```

---

## Adding New Variables

To add a new validated environment variable, edit `config/env_validation.py`:

```python
"MY_NEW_VAR": EnvVarRule(
    pattern=re.compile(r"^[a-z]+$"),  # Regex pattern
    pattern_description="Lowercase letters only",
    required=False,  # True = app fails if not set
    fix_suggestion="Set to a valid value like 'example'",
    example="example",
    default_value="default",  # Used if not set
    warn_on_default=True,  # Emit warning when using default
),
```
