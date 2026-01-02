# API Error Reference

> **Navigation**: [Quick Start](WIKI_QUICK_START.md) | [Platform API](WIKI_PLATFORM_API.md) | [All Jobs](WIKI_API_JOB_SUBMISSION.md) | [Errors](WIKI_API_ERRORS.md) | [Glossary](WIKI_API_GLOSSARY.md)

**Date**: 29 DEC 2025
**Purpose**: Reference for API error responses and troubleshooting
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

## Related Documentation

- **Internal Error Handling**: [WIKI_DEV_ERROR_HANDLING.md](WIKI_DEV_ERROR_HANDLING.md) - Exception hierarchy, retry telemetry, Application Insights queries
- **Job Submission**: [WIKI_API_JOB_SUBMISSION.md](WIKI_API_JOB_SUBMISSION.md) - Full API reference
- **Glossary**: [WIKI_API_GLOSSARY.md](WIKI_API_GLOSSARY.md) - Technical terminology

---

**Last Updated**: 29 DEC 2025
