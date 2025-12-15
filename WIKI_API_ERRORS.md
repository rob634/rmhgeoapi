# API Error Reference

**Date**: 29 NOV 2025
**Purpose**: Comprehensive reference for API error responses, internal error handling, and Application Insights telemetry
**Wiki**: Azure DevOps Wiki - Error handling documentation

---

## Error Response Format

All API errors follow a consistent JSON structure:

```json
{
  "error": "Error category",
  "message": "Human-readable error description",
  "request_id": "unique_request_id",
  "timestamp": "2025-11-28T17:55:08.943449+00:00"
}
```

| Field | Description |
|-------|-------------|
| `error` | Error category (e.g., "Bad request", "Internal server error") |
| `message` | Detailed description of what went wrong and how to fix it |
| `request_id` | Unique identifier for this request (useful for log correlation) |
| `timestamp` | ISO 8601 timestamp when error occurred |

---

## HTTP Status Codes

| Status | Category | Description |
|--------|----------|-------------|
| **400** | Bad Request | Invalid parameters, missing required fields, pre-flight validation failures |
| **404** | Not Found | Resource doesn't exist (job, collection, endpoint) |
| **409** | Conflict | Resource already exists (duplicate job, table conflict) |
| **422** | Unprocessable Entity | Valid JSON but business logic validation failed |
| **500** | Internal Server Error | Unexpected server-side error |
| **503** | Service Unavailable | Downstream service unavailable (database, blob storage) |

---

## Pre-Flight Validation Errors (HTTP 400)

Pre-flight validation runs BEFORE job creation to catch common issues early. These errors are returned immediately at HTTP submission time, saving queue messages and database records.

### Blob Not Found

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Pre-flight validation failed: Source file does not exist in Bronze storage. Check blob_name and container_name.",
  "request_id": "f2e53c96",
  "timestamp": "2025-11-28T17:54:36.000264+00:00"
}
```

**Causes**:
- `blob_name` doesn't exist in the specified container
- `container_name` doesn't exist in storage account
- Typo in blob path or container name

**Solutions**:
1. Verify file exists in Azure Portal → Storage Account → Containers
2. Check exact blob path (case-sensitive)
3. Verify container name is correct
4. Use Azure CLI to list container contents:
   ```bash
   az storage blob list --container-name rmhazuregeobronze --account-name rmhazuregeo --output table
   ```

**Jobs with Pre-Flight Blob Validation**:
- `process_vector` - Validates source file exists before creating job

---

### Container Not Found

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Pre-flight validation failed: Container 'invalid-container' does not exist",
  "request_id": "abc123",
  "timestamp": "2025-11-28T17:55:08.943449+00:00"
}
```

**Causes**:
- Container name is misspelled
- Container hasn't been created yet
- Using wrong storage account

**Solutions**:
1. Check available containers in Azure Portal
2. Create container if needed:
   ```bash
   az storage container create --name my-container --account-name rmhazuregeo
   ```
3. Use standard container names: `rmhazuregeobronze`, `silver-cogs`, `silver-vectors`

---

## Parameter Validation Errors (HTTP 400)

These errors occur when required parameters are missing or have invalid values.

### Missing Required Parameter

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Parameter 'blob_name' is required",
  "request_id": "ae476af1",
  "timestamp": "2025-11-28T17:52:47.942187+00:00"
}
```

**Common Required Parameters by Job Type**:

| Job Type | Required Parameters |
|----------|---------------------|
| `hello_world` | None (all optional) |
| `process_vector` | `blob_name`, `file_extension`, `table_name` |
| `process_raster` | `blob_name`, `container_name` |
| `process_raster_collection` | `blob_list`, `container_name` |

**Solution**: Include all required parameters in your request body.

---

### Invalid Parameter Type

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Parameter 'chunk_size' must be type int, got str",
  "request_id": "xyz789",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Expected Types by Common Parameters**:

| Parameter | Expected Type | Example |
|-----------|---------------|---------|
| `blob_name` | string | `"data.geojson"` |
| `table_name` | string | `"my_table"` |
| `chunk_size` | integer | `5000` |
| `failure_rate` | float | `0.3` |
| `indexes` | dict | `{"spatial": true}` |
| `blob_list` | list | `["file1.tif", "file2.tif"]` |

---

### Invalid Parameter Value

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Parameter 'file_extension' must be one of: csv, geojson, json, gpkg, kml, kmz, shp, zip",
  "request_id": "def456",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Allowed Values for Common Parameters**:

| Parameter | Allowed Values |
|-----------|----------------|
| `file_extension` | `csv`, `geojson`, `json`, `gpkg`, `kml`, `kmz`, `shp`, `zip` |
| `output_tier` | `visualization`, `analysis`, `archive`, `all` |
| `raster_type` | `auto`, `rgb`, `rgba`, `dem`, `categorical`, `multispectral`, `nir` |

---

### Parameter Out of Range

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Parameter 'chunk_size' must be between 100 and 500000, got 50",
  "request_id": "ghi012",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Common Parameter Ranges**:

| Parameter | Min | Max | Default |
|-----------|-----|-----|---------|
| `chunk_size` | 100 | 500,000 | Auto-calculated |
| `n` (hello_world) | 1 | 1,000 | 1 |
| `failure_rate` | 0.0 | 1.0 | 0.0 |
| `jpeg_quality` | 1 | 100 | 85 |

---

## Job Status Errors

These errors are returned by the `/api/jobs/status/{job_id}` endpoint.

### Job Not Found

**Error Response**:
```json
{
  "error": "Not found",
  "message": "Job with ID 'invalid-job-id' not found",
  "request_id": "jkl345",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Causes**:
- Job ID is incorrect
- Job was cleaned up by maintenance
- Job was never created (submission failed)

**Solutions**:
1. Check the job_id returned from your submit request
2. Query recent jobs: `GET /api/dbadmin/jobs?limit=10`

---

### Job Failed

Jobs that fail during execution have status `"failed"` with error details:

**Status Response**:
```json
{
  "jobId": "abc123...",
  "status": "failed",
  "errorDetails": "Task execution failed: Connection refused to database",
  "stage": 2,
  "totalStages": 3
}
```

**Common Failure Causes**:
- Database connection issues
- Blob storage access errors
- Invalid data in source file
- Memory limits exceeded

---

## CSV-Specific Errors

### Missing Geometry Configuration

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "CSV conversion requires either 'wkt_column' or both 'lat_name' and 'lon_name' in converter_params",
  "request_id": "mno678",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Solution**: Add `converter_params` with geometry column configuration:

```json
{
  "blob_name": "data.csv",
  "file_extension": "csv",
  "table_name": "my_table",
  "converter_params": {
    "lat_name": "latitude",
    "lon_name": "longitude"
  }
}
```

Or for WKT geometry:
```json
{
  "converter_params": {
    "wkt_column": "geometry"
  }
}
```

---

### Invalid Column Name

**Error Response**:
```json
{
  "error": "Bad request",
  "message": "Column 'latitude' not found in CSV. Available columns: lat, lon, name, value",
  "request_id": "pqr901",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Solution**: Check exact column names in your CSV (case-sensitive) and update `converter_params`.

---

## Database Errors (HTTP 500/503)

### Connection Pool Exhausted

**Error Response**:
```json
{
  "error": "Internal server error",
  "message": "Database connection pool exhausted. Retry after 30 seconds.",
  "request_id": "stu234",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Causes**:
- Too many concurrent requests
- Long-running queries holding connections
- Database under heavy load

**Solutions**:
1. Wait and retry after 30 seconds
2. Reduce concurrent job submissions
3. Check database health: `GET /api/dbadmin/stats`

---

### Table Already Exists

**Error Response**:
```json
{
  "error": "Conflict",
  "message": "Table 'geo.my_table' already exists. Use a different table_name or drop existing table.",
  "request_id": "vwx567",
  "timestamp": "2025-11-28T18:00:00.000000+00:00"
}
```

**Solutions**:
1. Use a different `table_name`
2. Drop existing table manually if you want to replace it
3. `process_vector` with same parameters will reuse existing table (idempotent)

---

## STAC/Raster Errors

### COG Translation Failed

**Error Response**:
```json
{
  "status": "failed",
  "errorDetails": "COG_TRANSLATE_FAILED: JPEG compression failed for 4-band raster"
}
```

**Causes**:
- JPEG compression doesn't support alpha channel
- File format incompatible with requested output_tier

**Solutions**:
1. Use `output_tier: "analysis"` (DEFLATE compression) instead of `visualization` (JPEG)
2. For RGBA images, use `analysis` or `archive` tier

---

### CRS Check Failed

**Error Response**:
```json
{
  "status": "failed",
  "errorDetails": "CRS_CHECK_FAILED: No coordinate reference system found in raster metadata"
}
```

**Solution**: Specify `input_crs` parameter:
```json
{
  "blob_name": "image.tif",
  "container_name": "rmhazuregeobronze",
  "input_crs": "EPSG:4326"
}
```

---

## Troubleshooting Guide

### 1. Identify the Error Category

| Error Prefix | Meaning | Action |
|--------------|---------|--------|
| "Parameter X is required" | Missing required field | Add the parameter |
| "Parameter X must be type Y" | Wrong data type | Check JSON formatting |
| "Pre-flight validation failed" | Resource doesn't exist | Verify blob/container exists |
| "Table already exists" | Naming conflict | Use different name or drop table |
| "Connection pool exhausted" | System overloaded | Wait and retry |

### 2. Use Request ID for Log Correlation

Every error includes a `request_id`. Use this to find related logs:

```bash
# Query Application Insights by request_id
traces | where customDimensions.request_id == "f2e53c96" | order by timestamp desc
```

### 3. Check Job Status for Execution Errors

If job was created but failed during execution:

```bash
# Get job details including error
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Get task-level details
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/tasks/{JOB_ID}
```

---

---

# Internal Error Handling (29 NOV 2025)

This section documents the internal error handling architecture for developers and operators.

---

## Exception Hierarchy

### Contract Violations vs Business Errors

The platform distinguishes between two fundamental error categories:

| Category | Base Class | Handling | When |
|----------|------------|----------|------|
| **Contract Violations** | `ContractViolationError(TypeError)` | NEVER catch - bubble up | Programming bugs (wrong types, missing fields) |
| **Business Logic Errors** | `BusinessLogicError(Exception)` | Catch and handle gracefully | Expected runtime failures |

### Exception Classes (`exceptions.py`)

```
ContractViolationError (TypeError) - NEVER CATCH, indicates bugs
├── Wrong types passed to functions
├── Missing required fields
└── Interface contract violations

BusinessLogicError (Exception) - Base for expected runtime failures
├── ServiceBusError        - Queue communication failures
├── DatabaseError          - PostgreSQL operation failures
├── TaskExecutionError     - Task failed during execution
├── ResourceNotFoundError  - Blob/job/queue not found
└── ValidationError        - Business rule validation failed

ConfigurationError (Exception) - Fatal misconfiguration
├── Missing environment variables
├── Invalid connection strings
└── Malformed configuration files
```

### Error Classification for Retry Decisions

```python
# From core/machine.py
RETRYABLE_EXCEPTIONS = (
    IOError, OSError, TimeoutError, ConnectionError,
    ServiceBusError, DatabaseError
)

PERMANENT_EXCEPTIONS = (
    ValueError, TypeError, KeyError, AttributeError,
    ContractViolationError, ResourceNotFoundError
)
```

---

## Error Source Identification

All structured error logs include an `error_source` field for filtering in Application Insights:

| error_source | Layer | Files |
|--------------|-------|-------|
| `orchestration` | Job/Task coordination | `core/machine.py` |
| `state` | State management | `core/state_manager.py` |
| `infrastructure` | External services | `infrastructure/service_bus.py` |

### Filtering by Error Source

```kql
-- Find all orchestration errors
traces | where customDimensions.error_source == "orchestration"

-- Find all infrastructure errors (Service Bus, PostgreSQL)
traces | where customDimensions.error_source == "infrastructure"

-- Find all state management errors
traces | where customDimensions.error_source == "state"

-- Count errors by source
traces
| where severityLevel >= 3
| summarize count() by tostring(customDimensions.error_source)
```

---

## Structured Logging Checkpoints

### Orchestration Checkpoints (`core/machine.py`)

| Checkpoint | Severity | Description |
|------------|----------|-------------|
| `STAGE_ADVANCE_FAILED` | ERROR | Failed to advance to next stage |
| `JOB_FINALIZE_FAILED` | ERROR | finalize_job() threw exception |
| `JOB_COMPLETE_FAILED` | ERROR | Job completion process failed |
| `RETRY_LOGIC_START` | INFO | Retry logic triggered |
| `RETRY_CONDITION_MET` | INFO | Task eligible for retry |
| `RETRY_SCHEDULED` | INFO | Retry message prepared |
| `RETRY_QUEUED_SUCCESS` | INFO | Retry message sent to queue |
| `RETRY_MAX_EXCEEDED` | ERROR | Max retries reached |
| `JOB_FAILED_MAX_RETRIES` | ERROR | Job failed due to task max retries |

### State Management Checkpoints (`core/state_manager.py`)

| Checkpoint | Severity | Description |
|------------|----------|-------------|
| `STATE_JOB_COMPLETE_FAILED` | ERROR | Failed to mark job complete |
| `STATE_STAGE_COMPLETE_FAILED` | ERROR | Stage completion handling failed |
| `STATE_TASK_COMPLETE_SQL_FAILED` | ERROR | Task completion SQL failed |
| `STATE_MARK_JOB_FAILED_ERROR` | ERROR | Failed to mark job as failed |
| `STATE_MARK_TASK_FAILED_ERROR` | ERROR | Failed to mark task as failed |

### Infrastructure Checkpoints (`infrastructure/service_bus.py`)

| error_category | Retryable | Description |
|----------------|-----------|-------------|
| `auth` | No | Authentication/authorization failed |
| `config` | No | Queue/entity not found |
| `quota` | No | Service Bus quota exceeded |
| `validation` | No | Message size exceeded (256KB) |
| `transient` | Yes | Timeout, server busy, connection error |
| `connection` | Yes | Connection/communication error |
| `service_bus_other` | Yes | Other Service Bus errors |
| `unexpected` | No | Non-Service Bus errors |

---

## Retry Telemetry

### Retry Event Flow

```
Task Fails
    ↓
RETRY_LOGIC_START (retry_event: 'start')
    ↓
[Check retry count < max]
    ↓
RETRY_CONDITION_MET (retry_event: 'condition_met')
    ↓
[Calculate exponential backoff]
    ↓
RETRY_SCHEDULED (retry_event: 'scheduled')
    ↓
[Send to Service Bus with delay]
    ↓
RETRY_QUEUED_SUCCESS (retry_event: 'queued')

--- OR if max exceeded ---

RETRY_MAX_EXCEEDED (retry_event: 'max_exceeded')
    ↓
JOB_FAILED_MAX_RETRIES (retry_event: 'job_failed')
```

### Retry Configuration

| Setting | Default | Environment Variable |
|---------|---------|---------------------|
| Max Retries | 3 | `TASK_MAX_RETRIES` |
| Base Delay | 5s | `TASK_RETRY_BASE_DELAY` |
| Max Delay | 300s | `TASK_RETRY_MAX_DELAY` |

**Exponential Backoff Formula**:
```python
delay = min(base_delay * (2 ** retry_count), max_delay)
# Retry 1: 5s, Retry 2: 10s, Retry 3: 20s (capped at max_delay)
```

### Retry Analysis Queries

```kql
-- Retry frequency by task type
traces
| where customDimensions.retry_event == "scheduled"
| summarize retry_count=count() by tostring(customDimensions.task_type)
| order by retry_count desc

-- Retry success rate
traces
| where customDimensions.retry_event in ("scheduled", "max_exceeded")
| summarize
    scheduled=countif(customDimensions.retry_event == "scheduled"),
    max_exceeded=countif(customDimensions.retry_event == "max_exceeded")
| extend success_rate = 100.0 * (scheduled - max_exceeded) / scheduled

-- Retry timeline for specific job
traces
| where customDimensions.job_id contains "abc123"
| where customDimensions.retry_event != ""
| project timestamp,
    customDimensions.retry_event,
    customDimensions.retry_attempt,
    customDimensions.delay_seconds
| order by timestamp asc

-- Tasks exceeding max retries (need investigation)
traces
| where customDimensions.checkpoint == "RETRY_MAX_EXCEEDED"
| project timestamp,
    customDimensions.task_id,
    customDimensions.task_type,
    customDimensions.error_details
| order by timestamp desc
| take 50
```

---

## Service Bus Error Categories

### Permanent Errors (Never Retry)

| Exception | error_category | Action |
|-----------|----------------|--------|
| `ServiceBusAuthenticationError` | `auth` | Check credentials/identity |
| `ServiceBusAuthorizationError` | `auth` | Check RBAC permissions |
| `MessagingEntityNotFoundError` | `config` | Queue doesn't exist |
| `ServiceBusQuotaExceededError` | `quota` | Upgrade tier or reduce load |
| `MessageSizeExceededError` | `validation` | Reduce message size (<256KB) |

### Transient Errors (Auto-Retry)

| Exception | error_category | Default Retries |
|-----------|----------------|-----------------|
| `OperationTimeoutError` | `transient` | 3 with exponential backoff |
| `ServiceBusServerBusyError` | `transient` | 3 with exponential backoff |
| `ServiceBusConnectionError` | `connection` | 3 with exponential backoff |
| `ServiceBusCommunicationError` | `connection` | 3 with exponential backoff |

---

## Nested Error Handling

When cleanup operations fail after a primary error, both errors are logged with `log_nested_error()`:

```python
except Exception as stage_error:
    try:
        self.state_manager.mark_job_failed(job_id, str(stage_error))
    except Exception as cleanup_error:
        log_nested_error(
            self.logger,
            primary_error=stage_error,
            cleanup_error=cleanup_error,
            operation="stage_advancement",
            job_id=job_id
        )
```

### Finding Nested Errors

```kql
-- All nested errors (cleanup failed after primary error)
traces
| where customDimensions.nested_error == true
| project timestamp,
    customDimensions.operation,
    customDimensions.primary_error_type,
    customDimensions.primary_error,
    customDimensions.cleanup_error_type,
    customDimensions.cleanup_error,
    customDimensions.job_id
| order by timestamp desc
```

---

## Application Insights Dashboard Queries

### Error Overview Dashboard

```kql
// Error count by source (last 24h)
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| summarize count() by tostring(customDimensions.error_source)
| render piechart

// Error timeline
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| summarize count() by bin(timestamp, 1h), tostring(customDimensions.error_source)
| render timechart

// Top 10 error types
traces
| where timestamp >= ago(24h)
| where severityLevel >= 3
| summarize count() by tostring(customDimensions.error_type)
| top 10 by count_
| render barchart
```

### Job Health Dashboard

```kql
// Failed jobs in last 24h
traces
| where timestamp >= ago(24h)
| where customDimensions.checkpoint in ("JOB_COMPLETE_FAILED", "JOB_FAILED_MAX_RETRIES")
| project timestamp,
    customDimensions.job_id,
    customDimensions.job_type,
    customDimensions.error_message
| order by timestamp desc

// Job completion rate
traces
| where timestamp >= ago(24h)
| where customDimensions.checkpoint in ("JOB_COMPLETE_SUCCESS", "JOB_COMPLETE_FAILED", "JOB_FAILED_MAX_RETRIES")
| summarize
    completed=countif(customDimensions.checkpoint == "JOB_COMPLETE_SUCCESS"),
    failed=countif(customDimensions.checkpoint != "JOB_COMPLETE_SUCCESS")
| extend success_rate = 100.0 * completed / (completed + failed)
```

### Service Bus Health Dashboard

```kql
// Service Bus errors by category
traces
| where timestamp >= ago(24h)
| where customDimensions.error_source == "infrastructure"
| where customDimensions.error_category != ""
| summarize count() by tostring(customDimensions.error_category)
| render piechart

// Queue-specific errors
traces
| where timestamp >= ago(24h)
| where customDimensions.error_source == "infrastructure"
| summarize count() by tostring(customDimensions.queue)
| order by count_ desc
```

---

## Debugging Workflows

### Investigating a Failed Job

1. **Find the job**:
```kql
traces
| where customDimensions.job_id contains "abc123"
| order by timestamp asc
| project timestamp, message, customDimensions
```

2. **Check for retry attempts**:
```kql
traces
| where customDimensions.job_id contains "abc123"
| where customDimensions.retry_event != ""
| order by timestamp asc
```

3. **Find root cause error**:
```kql
traces
| where customDimensions.job_id contains "abc123"
| where severityLevel >= 3
| project timestamp, customDimensions.checkpoint, customDimensions.error_message
| take 10
```

### Investigating Infrastructure Issues

1. **Service Bus connectivity**:
```kql
traces
| where timestamp >= ago(1h)
| where customDimensions.error_category in ("connection", "transient")
| summarize count() by bin(timestamp, 5m)
| render timechart
```

2. **Authentication failures**:
```kql
traces
| where timestamp >= ago(1h)
| where customDimensions.error_category == "auth"
| project timestamp, message, customDimensions.queue
```

---

## Error Handling Files Reference

| File | Purpose |
|------|---------|
| `exceptions.py` | Exception class hierarchy |
| `core/machine.py` | CoreMachine orchestration + retry logic |
| `core/state_manager.py` | Job/task state management |
| `core/error_handler.py` | Centralized error handling utilities |
| `infrastructure/service_bus.py` | Service Bus operations + error handling |
| `infrastructure/postgresql.py` | Database operations + error handling |

---

## Related Documentation

- **Job Submission**: `WIKI_API_JOB_SUBMISSION.md` - Full API reference
- **Architecture**: `docs_claude/CLAUDE_CONTEXT.md` - System architecture
- **Log Access**: `docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md` - Querying logs
- **Error Handling Plan**: `.claude/plans/keen-dazzling-muffin.md` - Implementation details

---

**Last Updated**: 29 NOV 2025
