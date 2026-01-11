# Health & Diagnostic Endpoints

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | **Health**

**Last Updated**: 11 JAN 2026
**Status**: Reference Documentation
**Purpose**: Health probes, startup validation, and diagnostic endpoints

---

## Overview

The platform provides diagnostic endpoints following Kubernetes-style health probe patterns:

| Endpoint | Purpose | Always Available |
|----------|---------|------------------|
| `/api/livez` | Liveness probe - is the process alive? | Yes |
| `/api/readyz` | Readiness probe - is the app ready for traffic? | Yes |
| `/api/health` | Comprehensive health check with component status | After startup |
| `/api/diagnostics` | Deep system diagnostics (connectivity, DNS, pools) | Yes |
| `/api/metrics/stats` | Service latency metrics statistics | Yes |
| `/api/metrics/flush` | Force flush metrics to blob storage | Yes |
| `/api/appinsights/query` | Query App Insights logs via REST API | Yes |
| `/api/appinsights/export` | Export logs to blob storage | Yes |
| `/api/appinsights/templates` | List available query templates | Yes |

---

## Quick Reference

```bash
# Check if process is alive (always 200 if running)
curl https://YOUR_APP.azurewebsites.net/api/livez

# Check if app is ready to handle requests
curl https://YOUR_APP.azurewebsites.net/api/readyz

# Full health check with component status
curl https://YOUR_APP.azurewebsites.net/api/health

# Deep system diagnostics (connectivity, DNS, pools)
curl https://YOUR_APP.azurewebsites.net/api/diagnostics

# Service metrics statistics
curl https://YOUR_APP.azurewebsites.net/api/metrics/stats

# Force flush metrics to blob storage
curl -X POST https://YOUR_APP.azurewebsites.net/api/metrics/flush

# List available App Insights query templates
curl https://YOUR_APP.azurewebsites.net/api/appinsights/templates

# Query App Insights logs
curl -X POST https://YOUR_APP.azurewebsites.net/api/appinsights/query \
  -H "Content-Type: application/json" \
  -d '{"query": "traces | take 10"}'

# Export logs to blob storage using a template
curl -X POST https://YOUR_APP.azurewebsites.net/api/appinsights/export \
  -H "Content-Type: application/json" \
  -d '{"template": "service_latency", "timespan": "24h"}'
```

---

## Endpoint Details

### GET /api/livez - Liveness Probe

**Purpose**: Detect if the Python process is alive. Used by load balancers to detect crashed processes.

**Response**: Always 200 if the process loaded successfully.

```json
{
  "status": "alive",
  "probe": "livez",
  "message": "Process is running"
}
```

**When to use**: Configure Azure Front Door or load balancer health probes to hit this endpoint.

---

### GET /api/readyz - Readiness Probe

**Purpose**: Determine if the app should receive traffic. Returns 503 with detailed errors if startup validation failed.

**Success Response (200)**:
```json
{
  "status": "ready",
  "probe": "readyz",
  "message": "All startup validations passed",
  "summary": {
    "validation_complete": true,
    "all_passed": true,
    "checks_passed": 4,
    "checks_failed": 0,
    "failed_check_names": []
  }
}
```

**Failure Response (503)**:
```json
{
  "status": "not_ready",
  "probe": "readyz",
  "message": "env_vars: 1 environment variable(s) invalid",
  "summary": {
    "validation_complete": true,
    "all_passed": false,
    "checks_passed": 3,
    "checks_failed": 1,
    "failed_check_names": ["env_vars"]
  },
  "errors": [
    {
      "name": "env_vars",
      "error_type": "ENV_VALIDATION_FAILED",
      "message": "1 environment variable(s) invalid",
      "fix": "Review the errors above and update environment variables via Azure Portal",
      "validation_errors": [
        {
          "var_name": "SERVICE_BUS_FQDN",
          "message": "Invalid format",
          "current_value": "myservicebus",
          "expected_pattern": "Must be full FQDN ending in .servicebus.windows.net",
          "fix_suggestion": "Use full URL like 'myservicebus.servicebus.windows.net'"
        }
      ]
    }
  ]
}
```

**Initializing Response (503)**:
```json
{
  "status": "initializing",
  "probe": "readyz",
  "message": "Startup validation in progress",
  "startup_time": "2026-01-08T10:30:00Z"
}
```

---

### GET /api/health - Comprehensive Health Check

**Purpose**: Full system health check including database, Service Bus, storage, and component status.

**Response includes**:
- Database connectivity
- Service Bus connectivity
- Storage account status
- Environment variable validation
- Startup validation summary
- Component capabilities

---

### GET /api/diagnostics - Deep System Diagnostics (10 JAN 2026)

**Purpose**: Deep system diagnostics for debugging opaque corporate Azure environments with VNet/ASE complexity.

**Query Parameters**:
| Parameter | Default | Description |
|-----------|---------|-------------|
| `dependencies` | `true` | Check dependency connectivity (database, storage, Service Bus) |
| `dns` | `true` | Check DNS resolution timing |
| `pools` | `true` | Check connection pool statistics |
| `instance` | `true` | Check instance/cold start information |
| `network` | `true` | Check network environment summary |
| `timeout` | `10` | Timeout for connectivity checks (max 30s) |

**Example Request**:
```bash
# Full diagnostics
curl https://YOUR_APP.azurewebsites.net/api/diagnostics

# Only dependency and DNS checks with custom timeout
curl "https://YOUR_APP.azurewebsites.net/api/diagnostics?pools=false&instance=false&timeout=5"
```

**Response (200)**:
```json
{
  "status": "ok",
  "timestamp": "2026-01-10T14:30:00Z",
  "duration_ms": 1234,
  "dependencies": {
    "database": {"status": "healthy", "latency_ms": 45},
    "service_bus": {"status": "healthy", "latency_ms": 23},
    "silver_storage": {"status": "healthy", "latency_ms": 12}
  },
  "dns": {
    "postgis_host": {"resolved": true, "latency_ms": 5, "addresses": ["10.0.0.5"]},
    "service_bus_fqdn": {"resolved": true, "latency_ms": 3, "addresses": ["40.90.1.123"]}
  },
  "pools": {
    "database": {"active": 2, "idle": 3, "max": 10}
  },
  "instance": {
    "instance_id": "abc123",
    "cold_start": false,
    "uptime_seconds": 3600
  },
  "network": {
    "private_ip": "10.0.0.50",
    "outbound_ip": "52.186.123.45"
  }
}
```

**Use case**: QA debugging when app is slow but `/api/health` shows healthy. Identifies whether the issue is DNS resolution, network latency, connection pool exhaustion, or cold start overhead.

---

### GET /api/metrics/stats - Service Latency Statistics

**Purpose**: View current service latency metrics statistics.

**Response (200)**:
```json
{
  "status": "ok",
  "metrics": {
    "enabled": true,
    "records_logged": 1523,
    "records_flushed": 1400,
    "flush_errors": 0,
    "buffer_size": 123,
    "instance_id": "abc123def456",
    "container": "applogs",
    "flush_interval": 60
  }
}
```

**Note**: Only active when `OBSERVABILITY_MODE=true` (or legacy `METRICS_DEBUG_MODE=true`). Returns `{"enabled": false}` when disabled.

---

### POST /api/metrics/flush - Force Flush Metrics

**Purpose**: Force flush buffered metrics to blob storage. Use before deployments or to ensure recent metrics are persisted for debugging.

**Response (200)**:
```json
{
  "status": "ok",
  "flush": {
    "flushed": true,
    "records_logged": 1523,
    "records_flushed": 1523,
    "flush_errors": 0,
    "buffer_remaining": 0
  },
  "stats": {
    "enabled": true,
    "container": "applogs",
    "flush_interval": 60
  }
}
```

**Blob Storage Path**: `applogs/service-metrics/{date}/{instance_id}/{timestamp}.jsonl`

**JSON Lines Format** (one record per line):
```json
{"ts": "2026-01-10T14:30:52Z", "op": "ogc.query_features", "ms": 145.2, "status": "success", "layer": "service"}
{"ts": "2026-01-10T14:30:53Z", "op": "ogc.get_collection", "ms": 23.1, "status": "success", "layer": "database", "slow": true}
```

---

### GET /api/appinsights/templates - List Query Templates (10 JAN 2026)

**Purpose**: List available predefined query templates for App Insights log export.

**Response (200)**:
```json
{
  "status": "ok",
  "templates": {
    "recent_traces": {"query_pattern": "traces | where timestamp >= ago({timespan}) | order by timestamp desc | take {limit}"},
    "recent_errors": {"query_pattern": "traces | where severityLevel >= 3 | ..."},
    "service_latency": {"query_pattern": "traces | where message contains '[SERVICE_LATENCY]' | ..."},
    "db_latency": {"query_pattern": "traces | where message contains '[DB_LATENCY]' | ..."},
    "startup_failures": {"query_pattern": "traces | where message contains 'STARTUP_FAILED' | ..."},
    "exceptions": {"query_pattern": "exceptions | where timestamp >= ago({timespan}) | ..."},
    "slow_requests": {"query_pattern": "requests | where duration > 5000 | ..."}
  },
  "usage": "POST /api/appinsights/export with {\"template\": \"<name>\", \"timespan\": \"24h\"}"
}
```

---

### POST /api/appinsights/query - Query App Insights Logs (10 JAN 2026)

**Purpose**: Run a KQL query against Application Insights and return results.

**Request Body**:
```json
{
  "query": "traces | where timestamp >= ago(1h) | take 100",
  "timespan": "PT1H"  // Optional, ISO 8601 duration (default: PT1H)
}
```

**Response (200)**:
```json
{
  "status": "ok",
  "row_count": 100,
  "columns": ["timestamp", "message", "severityLevel", "customDimensions"],
  "rows": [
    ["2026-01-10T14:30:00Z", "Request completed", 1, {"operation": "ogc.get_features"}],
    ...
  ],
  "query_duration_ms": 1234,
  "truncated": false
}
```

**Note**: Results are limited to 100 rows in the response. Use `/api/appinsights/export` for larger exports.

**Requires**:
- `APPINSIGHTS_APP_ID` environment variable
- Function App managed identity must have **Monitoring Reader** role on Application Insights resource

---

### POST /api/appinsights/export - Export Logs to Blob Storage (10 JAN 2026)

**Purpose**: Export App Insights logs to blob storage as JSON Lines for offline analysis.

**Request Body (Template-based)**:
```json
{
  "template": "service_latency",  // One of the templates from /api/appinsights/templates
  "timespan": "24h",              // Duration without PT prefix
  "limit": 1000,                  // Optional, default 1000
  "container": "applogs"          // Optional, default "applogs"
}
```

**Request Body (Custom Query)**:
```json
{
  "query": "traces | where message contains '[SERVICE_LATENCY]' | where customDimensions.slow == true",
  "timespan": "PT24H",            // ISO 8601 duration
  "container": "applogs",         // Optional
  "prefix": "exports/custom"      // Optional blob path prefix
}
```

**Response (200)**:
```json
{
  "status": "ok",
  "blob_path": "applogs/exports/service_latency/2026-01-10/20260110T143000Z.jsonl",
  "row_count": 523,
  "query_duration_ms": 2341,
  "export_duration_ms": 3456
}
```

**Blob Storage Path**: `{container}/{prefix}/{date}/{timestamp}.jsonl`

**Use Case**: Export slow operation logs for analysis when portal access is restricted in corporate environments.

---

## Startup Validation Flow

The app validates configuration in phases to ensure diagnostic endpoints are always available:

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: Register Probes (FIRST)                                │
│   • /api/livez and /api/readyz registered immediately           │
│   • Always available, even if later phases fail                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: Soft Validation (stores errors, doesn't crash)         │
│   1. Import validation - can Python load critical modules?      │
│   2. Env var validation - format checking with regex patterns   │
│   3. Service Bus DNS - does namespace resolve?                  │
│   4. Service Bus ports - are 5671/443 reachable?                │
│   5. Queue validation - do required queues exist?               │
│                                                                 │
│   Results stored in STARTUP_STATE (not raised as exceptions)    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STARTUP_STATE.finalize()                                        │
│   • Sets validation_complete = True                             │
│   • Computes all_passed = all checks passed?                    │
│   • Sets critical_error = first failure message                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: Conditional Registration                               │
│   IF all_passed:                                                │
│     • Register Service Bus triggers                             │
│     • App fully operational                                     │
│   ELSE:                                                         │
│     • Skip Service Bus triggers                                 │
│     • Only diagnostic endpoints available                       │
│     • readyz returns 503 with error details                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Environment Variable Validation (08 JAN 2026)

Environment variables are validated at startup with **regex patterns** to catch format errors early.

### Validated Variables

| Variable | Pattern | Example |
|----------|---------|---------|
| `SERVICE_BUS_FQDN` | Must end in `.servicebus.windows.net` | `mybus.servicebus.windows.net` |
| `POSTGIS_HOST` | Must be `localhost` or end in `.postgres.database.azure.com` | `myserver.postgres.database.azure.com` |
| `BRONZE_STORAGE_ACCOUNT` | Lowercase alphanumeric, 3-24 chars | `myappbronze` |
| `SILVER_STORAGE_ACCOUNT` | Lowercase alphanumeric, 3-24 chars | `myappsilver` |
| `POSTGIS_DATABASE` | Alphanumeric with underscore/hyphen | `geodb` |
| `POSTGIS_SCHEMA` | Lowercase letters/numbers/underscore | `geo` |
| `APP_SCHEMA` | Lowercase letters/numbers/underscore | `app` |
| `PGSTAC_SCHEMA` | Lowercase letters/numbers/underscore | `pgstac` |
| `H3_SCHEMA` | Lowercase letters/numbers/underscore | `h3` |

### Common Validation Errors

**SERVICE_BUS_FQDN missing suffix**:
```
SERVICE_BUS_FQDN: Invalid format
  Current: 'myservicebus'
  Expected: Must be full FQDN ending in .servicebus.windows.net
  Fix: Use full URL like 'myservicebus.servicebus.windows.net' (not just 'myservicebus')
```

**POSTGIS_HOST missing Azure suffix**:
```
POSTGIS_HOST: Invalid format
  Current: 'myserver'
  Expected: Must be 'localhost' or Azure FQDN ending in .postgres.database.azure.com
  Fix: Use full Azure FQDN like 'myserver.postgres.database.azure.com'
```

---

## Troubleshooting

### App returns 404 on all endpoints

**Cause**: Startup failed before any HTTP routes were registered.

**Solution**:
1. Check `/api/livez` - if 404, the process crashed during import
2. Check Application Insights for `STARTUP_FAILED` logs:
   ```kusto
   traces
   | where message contains "STARTUP_FAILED"
   | order by timestamp desc
   | take 5
   ```
3. Common causes:
   - Missing Python package in requirements.txt
   - Circular import issue
   - Invalid APP_MODE value

### readyz returns 503 "not_ready"

**Cause**: Startup validation detected a configuration problem.

**Solution**:
1. Check the `errors` array in the response
2. Look for `validation_errors` field for detailed env var issues
3. Fix the configuration in Azure Portal → Function App → Configuration
4. Restart the app

### readyz returns 503 "initializing"

**Cause**: App is still starting up.

**Solution**: Wait 30-60 seconds for cold start to complete. Azure Functions can take time to initialize Python environment.

### Service Bus DNS validation fails

**Cause**: DNS resolution failed for the Service Bus namespace.

**Possible issues**:
1. `SERVICE_BUS_FQDN` has wrong format (missing `.servicebus.windows.net`)
2. VNet/Private Endpoint DNS not configured
3. Namespace doesn't exist

**Solution**: Check the `validation_errors` in readyz response for specific guidance.

### Port connectivity check shows 5671 blocked

**Cause**: Corporate firewall blocking AMQP port.

**Response shows**:
```json
{
  "port_connectivity": {
    "5671": {"protocol": "AMQP", "reachable": false},
    "443": {"protocol": "AMQP-over-WebSockets", "reachable": true}
  },
  "recommended_transport": "AMQP-over-WebSockets (port 443)",
  "transport_warning": "Standard AMQP port 5671 blocked - consider configuring WebSocket transport"
}
```

**Solution**: Configure Service Bus client to use WebSocket transport.

---

## Integration with Monitoring

### Azure Front Door Health Probe

Configure health probe:
- Path: `/api/livez`
- Interval: 30 seconds
- Protocol: HTTPS
- Expected status: 200

### Kubernetes Deployment

```yaml
livenessProbe:
  httpGet:
    path: /api/livez
    port: 80
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /api/readyz
    port: 80
  initialDelaySeconds: 30
  periodSeconds: 10
```

### Application Insights Availability Test

Create availability test:
- URL: `https://YOUR_APP.azurewebsites.net/api/health`
- Frequency: 5 minutes
- Alert on: Status code != 200

---

## Related Documentation

- [Environment Variables](WIKI_ENVIRONMENT_VARIABLES.md) - All configuration options
- [Service Bus](WIKI_API_SERVICE_BUS.md) - Queue configuration
- [Errors](WIKI_API_ERRORS.md) - Error codes and troubleshooting
- [Quick Start](WIKI_QUICK_START.md) - Getting started guide
