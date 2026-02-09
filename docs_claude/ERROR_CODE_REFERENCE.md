# Error Code Reference

**Last Updated**: 09 FEB 2026
**Status**: Complete (BUG_REFORM Phase 6)
**Source Code**: `core/errors.py`

---

## Overview

This document provides a complete reference for all error codes in the Geospatial API. Error codes are designed to:

1. **Identify blame** - Who needs to fix the problem (user vs system)
2. **Guide retry logic** - Whether automatic retry will help
3. **Support DAG workflows** - Node-level vs workflow-level failures (v0.9 ready)
4. **Enable B2B integration** - Machine-readable error classification

---

## Quick Reference: Error Categories

| Category | Meaning | User Action | HTTP Status |
|----------|---------|-------------|-------------|
| `DATA_MISSING` | File/resource not found | Check path, ensure upload completed | 404 |
| `DATA_QUALITY` | File content is invalid | Fix the file and resubmit | 400 |
| `DATA_INCOMPATIBLE` | Collection files don't match | Make files consistent or split jobs | 400 |
| `PARAMETER_ERROR` | Request parameters are wrong | Fix parameters and resubmit | 400 |
| `SYSTEM_ERROR` | Internal server error | Contact support with error_id | 500 |
| `SERVICE_UNAVAILABLE` | Temporary outage | Retry in a few minutes | 503 |
| `CONFIGURATION` | System misconfigured | Contact support immediately | 500 |

---

## Quick Reference: Error Scopes (DAG v0.9)

| Scope | Meaning | Retry Strategy |
|-------|---------|----------------|
| `NODE` | Single processing step failed | Retry that node only |
| `WORKFLOW` | Orchestration/relationship failed | May need workflow redesign |

---

## Complete Error Code Inventory

### Shared Errors (Apply to Multiple Workflows)

#### Resource Not Found (DATA_MISSING)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `CONTAINER_NOT_FOUND` | 404 | No | NODE | Storage container doesn't exist | Verify container name spelling. Check Azure Storage configuration. |
| `FILE_NOT_FOUND` | 404 | No | NODE | File not found at specified path | Verify file path spelling. Ensure upload completed before job submission. |
| `RESOURCE_NOT_FOUND` | 404 | No | NODE | Generic resource not found | Check resource identifier. Resource may have been deleted. |

#### File/Data Errors (DATA_QUALITY)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `FILE_UNREADABLE` | 400 | Yes* | NODE | File cannot be read/parsed | Ensure file is not corrupted. Check file permissions. Re-upload if necessary. |
| `CRS_MISSING` | 400 | No | NODE | No coordinate reference system | Add `input_crs` parameter (e.g., `EPSG:4326`) or embed CRS in source file. |
| `CRS_MISMATCH` | 400 | No | NODE | File CRS doesn't match specified CRS | Remove `input_crs` to use file's CRS, or re-export file with correct CRS. |
| `INVALID_FORMAT` | 400 | No | NODE | File format not recognized | Ensure file is a supported format (GeoTIFF, Shapefile, GeoPackage, GeoJSON, CSV). |
| `CORRUPTED_FILE` | 400 | Yes* | NODE | File is damaged/truncated | Re-upload the file. Check for transmission errors. |

*Retryable in case of transient read errors; persistent errors require user action.

#### Parameter Errors (PARAMETER_ERROR)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | No | NODE | General validation failure | Check request against API schema. Review error details. |
| `INVALID_PARAMETER` | 400 | No | NODE | Parameter value is invalid | Check parameter value against allowed values. |
| `MISSING_PARAMETER` | 400 | No | NODE | Required parameter not provided | Add the missing required parameter. |

---

### Raster-Specific Errors (DATA_QUALITY)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `RASTER_UNREADABLE` | 400 | No | NODE | GDAL cannot open the file | Ensure file is a valid GeoTIFF. Do not rename other formats to .tif. |
| `RASTER_64BIT_REJECTED` | 400 | No | NODE | 64-bit data type not accepted | Re-export as 32-bit float (`float32`) or integer. 64-bit is unnecessary for geospatial data. |
| `RASTER_EMPTY` | 400 | No | NODE | File is 99%+ nodata pixels | Provide a file with actual data. This file contains almost no usable pixels. |
| `RASTER_NODATA_CONFLICT` | 400 | No | NODE | Nodata value appears in real data | Change nodata value to one not in your data, or set nodata to None. |
| `RASTER_EXTREME_VALUES` | 400 | No | NODE | DEM has extreme values (e.g., 1e38) | Set proper nodata value. Values like 3.4e38 indicate uninitialized pixels. |
| `RASTER_BAND_INVALID` | 400 | No | NODE | Invalid band count (0 or >100) | Ensure file is a valid raster, not corrupted. |
| `RASTER_TYPE_MISMATCH` | 400 | No | NODE | Specified type doesn't match detected | Remove `raster_type` parameter for auto-detection, or fix your file. |

---

### Vector-Specific Errors (DATA_QUALITY)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `VECTOR_UNREADABLE` | 400 | No | NODE | File cannot be parsed | Ensure file is valid format. Check for truncation or encoding issues. |
| `VECTOR_NO_FEATURES` | 400 | No | NODE | No features after filtering | Source file is empty or all geometries invalid. Check source data. |
| `VECTOR_GEOMETRY_INVALID` | 400 | No | NODE | Geometry cannot be auto-repaired | Fix geometries in GIS software (e.g., use ST_MakeValid in PostGIS). |
| `VECTOR_GEOMETRY_EMPTY` | 400 | No | NODE | All features have null geometry | Ensure file contains geometry data, not just attributes. |
| `VECTOR_COORDINATE_ERROR` | 400 | No | NODE | Cannot parse lat/lon from CSV | Ensure columns contain valid numeric coordinates. Check for text/null values. |
| `VECTOR_ENCODING_ERROR` | 400 | No | NODE | Character encoding issue | Re-export file as UTF-8 encoding. |
| `VECTOR_ATTRIBUTE_ERROR` | 400 | No | NODE | Column has mixed/invalid types | Ensure column has consistent data type (all text or all numeric). |
| `VECTOR_TABLE_NAME_INVALID` | 400 | No | NODE | Invalid PostGIS table name | Use lowercase letters, numbers, underscores. Cannot start with number. Max 63 chars. |

---

### Collection-Specific Errors (DATA_INCOMPATIBLE, WORKFLOW Scope)

These errors occur when **all files are individually valid** but **incompatible together**.

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `COLLECTION_BAND_MISMATCH` | 400 | No | WORKFLOW | Files have different band counts | All files must have same band count. Remove incompatible files or submit separately. |
| `COLLECTION_DTYPE_MISMATCH` | 400 | No | WORKFLOW | Files have different data types | Convert all files to same data type before submission. |
| `COLLECTION_CRS_MISMATCH` | 400 | No | WORKFLOW | Files have different CRS | Reproject all files to same CRS before submission. |
| `COLLECTION_RESOLUTION_MISMATCH` | 400 | No | WORKFLOW | Resolution varies >20% | Resample files to consistent resolution before submission. |
| `COLLECTION_TYPE_MISMATCH` | 400 | No | WORKFLOW | Mixed raster types (RGB + DEM) | Don't mix imagery with elevation data. Submit as separate collections. |
| `COLLECTION_BOUNDS_DISJOINT` | 400 | No | WORKFLOW | Files have no spatial relationship | Ensure files are from same geographic area. Check for CRS issues. |

---

### Processing Errors (SYSTEM_ERROR)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `REPROJECTION_FAILED` | 500 | Yes | NODE | CRS transformation failed | Contact support. May indicate unusual CRS or data issue. |
| `COG_TRANSLATE_FAILED` | 500 | Yes | NODE | COG translation failed | Contact support. Check source file integrity. |
| `COG_CREATION_FAILED` | 500 | Yes | NODE | COG creation failed | Contact support. May indicate resource exhaustion. |
| `PROCESSING_FAILED` | 500 | Yes | NODE | Generic processing failure | Contact support with error_id. Check job details. |

---

### Infrastructure Errors

#### Database Errors

| Code | HTTP | Retryable | Scope | Category | Description |
|------|------|-----------|-------|----------|-------------|
| `DATABASE_ERROR` | 500 | Yes | NODE | SYSTEM_ERROR | General database error |
| `DATABASE_TIMEOUT` | 503 | Yes | NODE | SERVICE_UNAVAILABLE | Database query timed out |
| `DATABASE_CONNECTION_FAILED` | 500 | Yes | NODE | SYSTEM_ERROR | Cannot connect to database |

#### Storage Errors

| Code | HTTP | Retryable | Scope | Category | Description |
|------|------|-----------|-------|----------|-------------|
| `STORAGE_ERROR` | 500 | Yes | NODE | SYSTEM_ERROR | General storage error |
| `STORAGE_TIMEOUT` | 503 | Yes | NODE | SERVICE_UNAVAILABLE | Storage operation timed out |
| `UPLOAD_FAILED` | 500 | Yes | NODE | SYSTEM_ERROR | Failed to upload to storage |
| `DOWNLOAD_FAILED` | 500 | Yes | NODE | SYSTEM_ERROR | Failed to download from storage |

#### Queue/Message Errors

| Code | HTTP | Retryable | Scope | Category | Description |
|------|------|-----------|-------|----------|-------------|
| `QUEUE_ERROR` | 500 | Yes | NODE | SYSTEM_ERROR | Service Bus queue error |
| `MESSAGE_ERROR` | 500 | Yes | NODE | SYSTEM_ERROR | Message processing error |

#### Resource Exhaustion

| Code | HTTP | Retryable | Scope | Category | Description |
|------|------|-----------|-------|----------|-------------|
| `MEMORY_ERROR` | 500 | Yes* | NODE | SYSTEM_ERROR | Out of memory |
| `DISK_FULL` | 500 | Yes* | NODE | SYSTEM_ERROR | No disk space |
| `TIMEOUT` | 503 | Yes | NODE | SERVICE_UNAVAILABLE | Operation timed out |
| `THROTTLED` | 503 | Yes* | NODE | SERVICE_UNAVAILABLE | Rate limited |

*Retry with longer delay (THROTTLING classification).

---

### Configuration Errors (CONFIGURATION)

| Code | HTTP | Retryable | Scope | Description | Remediation |
|------|------|-----------|-------|-------------|-------------|
| `SETUP_FAILED` | 500 | No | NODE | Service initialization failed | Contact ops team. Check environment variables. |
| `CONFIG_ERROR` | 500 | No | NODE | Configuration error | Contact ops team. Check app settings. |

---

### Generic Errors

| Code | HTTP | Retryable | Scope | Category | Description |
|------|------|-----------|-------|----------|-------------|
| `UNKNOWN_ERROR` | 500 | Yes | NODE | SYSTEM_ERROR | Unknown error occurred |
| `UNEXPECTED_ERROR` | 500 | Yes | NODE | SYSTEM_ERROR | Unexpected error occurred |

---

## Error Response Structure

### Standard Response (ErrorResponse Model)

```json
{
    "success": false,

    "error_code": "RASTER_64BIT_REJECTED",
    "error_category": "DATA_QUALITY",
    "error_scope": "node",

    "retryable": false,
    "user_fixable": true,
    "http_status": 400,

    "message": "File uses 64-bit float data type which is not accepted",
    "remediation": "Re-export your raster as 32-bit float (float32). 64-bit is unnecessary for geospatial data.",

    "details": {
        "file": "elevation.tif",
        "current_dtype": "float64",
        "recommended_dtype": "float32"
    },

    "error_id": "ERR-20260209-143052-a1b2c3",

    "error": "RASTER_64BIT_REJECTED",
    "error_type": "ValueError"
}
```

### Debug Response (When Debug Mode Enabled)

When `OBSERVABILITY_MODE=true`, responses include additional debug info:

```json
{
    "success": false,
    "error_code": "RASTER_64BIT_REJECTED",
    "...": "...",

    "debug": {
        "error_id": "ERR-20260209-143052-a1b2c3",
        "timestamp": "2026-02-09T14:30:52.123Z",
        "job_id": "abc123def456...",
        "task_id": "task-789...",
        "stage": 1,
        "handler": "validate_raster",

        "exception": {
            "type": "ValueError",
            "message": "64-bit data type float64 rejected",
            "file": "raster_validation.py",
            "line": 754,
            "function": "_check_bit_depth_efficiency"
        },

        "traceback": "Traceback (most recent call last):\n  ...",

        "context": {
            "blob_name": "elevation.tif",
            "container": "bronze-rasters",
            "file_size_mb": 245.7
        }
    }
}
```

---

## Error ID Format

```
ERR-{YYYYMMDD}-{HHMMSS}-{random6}

Examples:
  ERR-20260209-143052-a1b2c3
  ERR-20260209-143052-x7y8z9
```

The error_id enables:
- Quick search in Application Insights
- Correlation across logs
- Reference in support tickets

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| **Total Error Codes** | 47 |
| **Shared Errors** | 11 |
| **Raster-Specific** | 7 |
| **Vector-Specific** | 8 |
| **Collection-Specific** | 6 |
| **Processing Errors** | 4 |
| **Infrastructure Errors** | 13 |
| **Generic Errors** | 2 |

| Category | Count |
|----------|-------|
| DATA_MISSING | 3 |
| DATA_QUALITY | 20 |
| DATA_INCOMPATIBLE | 6 |
| PARAMETER_ERROR | 4 |
| SYSTEM_ERROR | 15 |
| SERVICE_UNAVAILABLE | 4 |
| CONFIGURATION | 2 |

---

## Related Documentation

- [B2B Error Handling Guide](./B2B_ERROR_HANDLING_GUIDE.md) - Integration guide for API consumers
- [Error Troubleshooting Guide](./ERROR_TROUBLESHOOTING.md) - Organized by error category
- [BUG_REFORM.md](/BUG_REFORM.md) - Design document and implementation plan

---

*Document maintained by: Engineering Team*
*Last updated: 09 FEB 2026*
