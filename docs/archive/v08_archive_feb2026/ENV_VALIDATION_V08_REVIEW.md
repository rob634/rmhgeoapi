# Environment Variable Validation - V0.8 Review

**Created**: 26 JAN 2026
**Purpose**: Reconcile env_validation.py with V0.8 Docker Worker architecture

---

## V0.8 Architecture Summary

```
Platform App ──Queue──> Docker Worker (container-tasks)
             ──Queue──> FunctionApp Worker (functionapp-tasks)
```

**Key Changes in V0.8**:
1. Docker Worker is PRIMARY for all heavy operations
2. Single unified raster handler with automatic tiling decision
3. Vector ETL always routes to Docker
4. Mount-based temp storage for large files

---

## Current Validation Status

| Category | Required | Optional | Total |
|----------|----------|----------|-------|
| Database | 5 | 1 | 6 |
| Storage | 2 | 2 | 4 |
| Service Bus | 1 | 6 | 7 |
| Docker/Mode | 0 | 5 | 5 |
| Raster | 0 | 6 | 6 |
| Platform | 0 | 3 | 3 |
| Other | 1 | 8 | 9 |
| **Total** | **9** | **31** | **40** |

---

## GAP ANALYSIS

### Missing (Should Add)

| Variable | Priority | Used In | Why Needed |
|----------|----------|---------|------------|
| `SERVICE_BUS_CONTAINER_TASKS_QUEUE` | **CRITICAL** | queue_config.py | Docker worker queue name |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | HIGH | docker_service.py | Docker worker telemetry |

### Obsolete (Consider Removing)

| Variable | Reason | Recommendation |
|----------|--------|----------------|
| `SERVICE_BUS_RASTER_TASKS_QUEUE` | V0.8 routes to Docker, not separate raster queue | Keep for backward compat |
| `SERVICE_BUS_VECTOR_TASKS_QUEUE` | V0.8 routes to Docker, not separate vector queue | Keep for backward compat |
| `SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE` | Replaced by container-tasks | Keep for backward compat |
| `SERVICE_BUS_NAMESPACE` | Deprecated - use SERVICE_BUS_FQDN | Remove validation or add deprecation warning |
| `ETL_APP_URL` | Not used in V0.8 | Remove |
| `OGC_STAC_APP_URL` | External STAC app - rarely used | Keep but mark optional |

### Correctly Validated

| Category | Variables | Status |
|----------|-----------|--------|
| **Database** | POSTGIS_HOST, POSTGIS_DATABASE, POSTGIS_SCHEMA, APP_SCHEMA, PGSTAC_SCHEMA, H3_SCHEMA | ✅ Good |
| **Storage** | BRONZE_STORAGE_ACCOUNT, SILVER_STORAGE_ACCOUNT | ✅ Good |
| **Service Bus** | SERVICE_BUS_FQDN | ✅ Good |
| **Docker** | DOCKER_WORKER_ENABLED, DOCKER_WORKER_URL, APP_MODE | ✅ Good |
| **Raster V0.8** | RASTER_USE_ETL_MOUNT, RASTER_ETL_MOUNT_PATH, RASTER_TILING_THRESHOLD_MB | ✅ Good |
| **Platform** | PLATFORM_DEFAULT_ACCESS_LEVEL, PLATFORM_PRIMARY_CLIENT | ✅ Good |

---

## RECOMMENDATIONS

### 1. Add SERVICE_BUS_CONTAINER_TASKS_QUEUE (CRITICAL)

This is the Docker worker queue and must be validated:

```python
"SERVICE_BUS_CONTAINER_TASKS_QUEUE": EnvVarRule(
    pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
    pattern_description="Queue name for Docker container tasks",
    required=False,
    fix_suggestion="Set queue name for Docker worker or use default 'container-tasks'",
    example="container-tasks",
    default_value="container-tasks",
),
```

### 2. Add APPLICATIONINSIGHTS_CONNECTION_STRING (HIGH)

Docker worker needs telemetry:

```python
"APPLICATIONINSIGHTS_CONNECTION_STRING": EnvVarRule(
    pattern=re.compile(r"^InstrumentationKey=[a-f0-9-]{36}.*$"),
    pattern_description="Application Insights connection string",
    required=False,
    fix_suggestion="Set connection string from Application Insights resource",
    example="InstrumentationKey=00000000-0000-0000-0000-000000000000;...",
    default_value=None,
    warn_on_default=True,  # Warn if telemetry disabled
),
```

### 3. Mark SERVICE_BUS_NAMESPACE as Deprecated

Add deprecation warning:

```python
"SERVICE_BUS_NAMESPACE": EnvVarRule(
    pattern=_SERVICE_BUS_FQDN,
    pattern_description="DEPRECATED - use SERVICE_BUS_FQDN instead",
    required=False,
    fix_suggestion="Rename to SERVICE_BUS_FQDN",
    example="myservicebus.servicebus.windows.net",
    warn_on_default=False,  # Don't warn - just deprecation note
),
```

### 4. Remove Unused Variables

These are not used in V0.8:
- `ETL_APP_URL` - Was for multi-app HTTP routing, now uses queues
- `OGC_STAC_APP_URL` - External STAC rarely used

---

## V0.8 Minimum Required Variables

For a working V0.8 deployment, these are truly required:

| Variable | Purpose |
|----------|---------|
| `SERVICE_BUS_FQDN` | Queue connectivity |
| `POSTGIS_HOST` | Database host |
| `POSTGIS_DATABASE` | Database name |
| `POSTGIS_SCHEMA` | PostGIS schema |
| `APP_SCHEMA` | Application schema |
| `PGSTAC_SCHEMA` | STAC schema |
| `H3_SCHEMA` | H3 analytics schema |
| `BRONZE_STORAGE_ACCOUNT` | Input storage |
| `SILVER_STORAGE_ACCOUNT` | Output storage |

Everything else has safe defaults.

---

## Docker Worker Specific Variables

For Docker Worker (`APP_MODE=worker_docker`):

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `APP_MODE` | No | standalone | Set to `worker_docker` |
| `RASTER_USE_ETL_MOUNT` | No | true | Enable mount for temp files |
| `RASTER_ETL_MOUNT_PATH` | No | /mnt/etl | Mount path |
| `SERVICE_BUS_CONTAINER_TASKS_QUEUE` | No | container-tasks | Queue to listen on |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Recommended | None | Telemetry |
| `ENVIRONMENT` | No | dev | For log correlation |
| `APP_NAME` | No | docker-worker | For log correlation |

---

## Action Items

- [x] Add RASTER_ETL_MOUNT_PATH validation (Done 26 JAN)
- [x] Add SERVICE_BUS_FUNCTIONAPP_TASKS_QUEUE validation (Done 26 JAN)
- [x] Add PLATFORM_DEFAULT_ACCESS_LEVEL validation (Done 26 JAN)
- [x] Add SERVICE_BUS_CONTAINER_TASKS_QUEUE validation (Done 26 JAN)
- [x] Add APPLICATIONINSIGHTS_CONNECTION_STRING validation (Done 26 JAN)
- [ ] Consider removing ETL_APP_URL, OGC_STAC_APP_URL (Low priority)

---

## Summary

**Total validation rules: 42**

All V0.8 critical variables are now validated. The validation file is up to date with V0.8 Docker Worker architecture requirements.
