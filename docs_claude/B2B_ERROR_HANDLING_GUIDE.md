# B2B Error Handling Integration Guide

**Last Updated**: 09 FEB 2026
**Status**: Complete (BUG_REFORM Phase 6)
**Audience**: DDH Platform Team, External API Consumers

---

## Overview

This guide explains how to integrate with the Geospatial API error handling system. The API provides structured error responses that enable:

1. **Automatic retry decisions** - Know when to retry vs. when to fix input
2. **User-friendly messages** - Display actionable error messages to end users
3. **Support ticket correlation** - Reference specific errors with `error_id`
4. **DAG-aware error handling** - Distinguish node failures from workflow failures

---

## Quick Start

### Parsing Error Responses

```python
import requests

response = requests.post("https://api.example.com/api/platform/submit", json=payload)

if response.status_code != 200:
    error = response.json()

    # Key fields for error handling
    error_code = error["error_code"]           # Machine-readable code
    error_category = error["error_category"]   # Who's responsible
    user_fixable = error["user_fixable"]       # Can user fix this?
    retryable = error["retryable"]             # Should system retry?
    message = error["message"]                 # Human-readable message
    remediation = error.get("remediation")     # How to fix (if user_fixable)
    error_id = error["error_id"]               # For support tickets
```

### Decision Logic

```python
def handle_api_error(error: dict) -> str:
    """Determine action based on error response."""

    category = error["error_category"]

    if category in ["DATA_MISSING", "DATA_QUALITY", "DATA_INCOMPATIBLE", "PARAMETER_ERROR"]:
        # User's problem - show remediation
        return f"Please fix: {error['remediation']}"

    elif category == "SERVICE_UNAVAILABLE":
        # Temporary - retry automatically
        return "Service temporarily unavailable. Retrying..."

    elif category in ["SYSTEM_ERROR", "CONFIGURATION"]:
        # Our problem - contact support
        return f"System error. Contact support with ID: {error['error_id']}"
```

---

## Error Response Schema

### Full Response Structure

```typescript
interface ErrorResponse {
    // Status
    success: false;

    // Classification (machine-readable)
    error_code: string;           // e.g., "RASTER_64BIT_REJECTED"
    error_category: ErrorCategory;
    error_scope: "node" | "workflow";

    // Retry guidance
    retryable: boolean;
    user_fixable: boolean;
    http_status: number;          // 400, 404, 500, 503

    // Human-readable
    message: string;
    remediation?: string;         // Only for user_fixable errors

    // Details (varies by error)
    details?: Record<string, any>;

    // Support reference
    error_id: string;             // e.g., "ERR-20260209-143052-a1b2c3"

    // Debug (only in debug mode)
    debug?: ErrorDebug;

    // Legacy fields (deprecated)
    error?: string;               // Same as error_code
    error_type?: string;          // Exception class name
}

enum ErrorCategory {
    DATA_MISSING = "DATA_MISSING",
    DATA_QUALITY = "DATA_QUALITY",
    DATA_INCOMPATIBLE = "DATA_INCOMPATIBLE",
    PARAMETER_ERROR = "PARAMETER_ERROR",
    SYSTEM_ERROR = "SYSTEM_ERROR",
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE",
    CONFIGURATION = "CONFIGURATION"
}
```

---

## Error Categories Explained

### DATA_MISSING (HTTP 404)

**Meaning**: The file or resource you referenced doesn't exist.

**User Action**: Check the path, ensure upload completed.

**Example**:
```json
{
    "error_code": "FILE_NOT_FOUND",
    "error_category": "DATA_MISSING",
    "message": "File 'datasets/countries.gpkg' not found in container 'bronze-uploads'",
    "remediation": "Verify file path spelling. Ensure upload completed before job submission.",
    "user_fixable": true,
    "retryable": false
}
```

**Integration Pattern**:
```python
if error["error_category"] == "DATA_MISSING":
    # Show file browser, highlight path input
    show_error(f"File not found: {error['details']['blob_name']}")
    show_remediation(error["remediation"])
```

---

### DATA_QUALITY (HTTP 400)

**Meaning**: Your file was found but has content problems.

**User Action**: Fix the file and re-upload.

**Common Errors**:
- `RASTER_64BIT_REJECTED` - 64-bit data type not accepted
- `RASTER_EMPTY` - File is mostly nodata
- `CRS_MISSING` - No coordinate reference system
- `VECTOR_GEOMETRY_INVALID` - Bad geometry

**Example**:
```json
{
    "error_code": "RASTER_64BIT_REJECTED",
    "error_category": "DATA_QUALITY",
    "message": "File uses 64-bit float data type which is not accepted",
    "remediation": "Re-export your raster as 32-bit float (float32). 64-bit is unnecessary for geospatial data.",
    "details": {
        "file": "elevation.tif",
        "current_dtype": "float64",
        "recommended_dtype": "float32"
    },
    "user_fixable": true,
    "retryable": false
}
```

**Integration Pattern**:
```python
if error["error_category"] == "DATA_QUALITY":
    # Show detailed remediation with specifics
    details = error.get("details", {})
    show_error(error["message"])
    show_remediation(error["remediation"])

    # Optionally show technical details
    if "current_dtype" in details:
        show_detail(f"Current: {details['current_dtype']}")
        show_detail(f"Required: {details['recommended_dtype']}")
```

---

### DATA_INCOMPATIBLE (HTTP 400)

**Meaning**: Individual files are valid, but they can't be processed together as a collection.

**User Action**: Make files consistent or split into separate jobs.

**Common Errors**:
- `COLLECTION_BAND_MISMATCH` - Different band counts
- `COLLECTION_CRS_MISMATCH` - Different coordinate systems
- `COLLECTION_TYPE_MISMATCH` - Mixing RGB with DEM

**Example**:
```json
{
    "error_code": "COLLECTION_BAND_MISMATCH",
    "error_category": "DATA_INCOMPATIBLE",
    "error_scope": "workflow",
    "message": "Collection contains rasters with different band counts",
    "details": {
        "reference_file": "tile_001.tif",
        "reference_properties": {
            "band_count": 3,
            "dtype": "uint8"
        },
        "mismatches": [
            {
                "file": "tile_015.tif",
                "expected": 3,
                "found": 1,
                "likely_cause": "This appears to be a DEM (single-band elevation) mixed with RGB imagery"
            }
        ],
        "compatible_files": 14,
        "incompatible_files": 1
    },
    "remediation": "Remove 'tile_015.tif' from the collection. It has 1 band (expected 3) and appears to be a DEM rather than RGB imagery.",
    "user_fixable": true,
    "retryable": false
}
```

**Integration Pattern**:
```python
if error["error_category"] == "DATA_INCOMPATIBLE":
    # This is a WORKFLOW error - show collection-level guidance
    details = error.get("details", {})

    show_error(f"Collection incompatibility: {error['message']}")
    show_remediation(error["remediation"])

    # Highlight incompatible files
    for mismatch in details.get("mismatches", []):
        highlight_file(mismatch["file"], reason=mismatch.get("likely_cause"))
```

---

### PARAMETER_ERROR (HTTP 400)

**Meaning**: Your request parameters are wrong.

**User Action**: Fix the parameters and resubmit.

**Common Errors**:
- `MISSING_PARAMETER` - Required parameter not provided
- `INVALID_PARAMETER` - Parameter value is invalid
- `VECTOR_TABLE_NAME_INVALID` - Invalid table name

**Example**:
```json
{
    "error_code": "VECTOR_TABLE_NAME_INVALID",
    "error_category": "PARAMETER_ERROR",
    "message": "Table name '123_invalid' is invalid: cannot start with a number",
    "remediation": "Use lowercase letters, numbers, underscores. Cannot start with number. Max 63 characters.",
    "details": {
        "provided": "123_invalid",
        "rule_violated": "cannot_start_with_number"
    },
    "user_fixable": true,
    "retryable": false
}
```

**Integration Pattern**:
```python
if error["error_category"] == "PARAMETER_ERROR":
    # Highlight the specific field
    details = error.get("details", {})
    field_name = details.get("field") or error["error_code"].split("_")[-1].lower()

    highlight_form_field(field_name)
    show_field_error(field_name, error["remediation"])
```

---

### SERVICE_UNAVAILABLE (HTTP 503)

**Meaning**: Temporary service issue. Will likely resolve on its own.

**User Action**: Wait and retry automatically.

**Common Errors**:
- `DATABASE_TIMEOUT` - Database query timed out
- `STORAGE_TIMEOUT` - Storage operation timed out
- `THROTTLED` - Rate limited

**Example**:
```json
{
    "error_code": "DATABASE_TIMEOUT",
    "error_category": "SERVICE_UNAVAILABLE",
    "message": "Database query timed out",
    "retryable": true,
    "user_fixable": false,
    "http_status": 503
}
```

**Integration Pattern**:
```python
if error["error_category"] == "SERVICE_UNAVAILABLE":
    # Implement exponential backoff
    if retry_count < MAX_RETRIES:
        delay = min(2 ** retry_count * BASE_DELAY, MAX_DELAY)
        show_status(f"Service temporarily unavailable. Retrying in {delay}s...")
        time.sleep(delay)
        return retry_request()
    else:
        show_error("Service unavailable after multiple retries. Please try later.")
```

---

### SYSTEM_ERROR (HTTP 500)

**Meaning**: Internal server error. Our problem, not yours.

**User Action**: Contact support with `error_id`.

**Example**:
```json
{
    "error_code": "COG_CREATION_FAILED",
    "error_category": "SYSTEM_ERROR",
    "message": "Failed to create Cloud Optimized GeoTIFF",
    "error_id": "ERR-20260209-143052-a1b2c3",
    "retryable": true,
    "user_fixable": false
}
```

**Integration Pattern**:
```python
if error["error_category"] == "SYSTEM_ERROR":
    error_id = error["error_id"]

    # Try automatic retry first (might be transient)
    if error["retryable"] and retry_count < MAX_RETRIES:
        return retry_request()

    # Show support message with error ID
    show_error("An internal error occurred.")
    show_support_link(f"Please contact support with reference: {error_id}")

    # Log for monitoring
    log_system_error(error_id, error["error_code"])
```

---

### CONFIGURATION (HTTP 500)

**Meaning**: System misconfiguration. Ops team needs to fix.

**User Action**: Contact support immediately.

**Example**:
```json
{
    "error_code": "CONFIG_ERROR",
    "error_category": "CONFIGURATION",
    "message": "Service configuration error",
    "error_id": "ERR-20260209-143052-a1b2c3",
    "retryable": false,
    "user_fixable": false
}
```

---

## Retry Strategy

### Recommended Retry Logic

```python
def should_retry(error: dict, retry_count: int) -> bool:
    """Determine if request should be retried."""

    # Never retry more than 3 times
    if retry_count >= 3:
        return False

    # Only retry if the API says it's retryable
    if not error.get("retryable", False):
        return False

    # User-fixable errors won't fix themselves
    if error.get("user_fixable", False):
        return False

    # SERVICE_UNAVAILABLE should always retry
    if error["error_category"] == "SERVICE_UNAVAILABLE":
        return True

    # SYSTEM_ERROR might be transient
    if error["error_category"] == "SYSTEM_ERROR":
        return True

    return False


def get_retry_delay(error: dict, retry_count: int) -> float:
    """Calculate delay before retry (exponential backoff)."""

    base_delay = 1.0  # seconds
    max_delay = 30.0

    # Longer delay for throttling
    if error["error_code"] == "THROTTLED":
        base_delay = 5.0
        max_delay = 60.0

    delay = min(base_delay * (2 ** retry_count), max_delay)

    # Add jitter to prevent thundering herd
    import random
    jitter = random.uniform(0, delay * 0.1)

    return delay + jitter
```

---

## HTTP Response Headers

The API also sets response headers for quick classification:

```http
HTTP/1.1 400 Bad Request
X-Error-Category: DATA_QUALITY
X-Error-Code: RASTER_64BIT_REJECTED
X-Error-Id: ERR-20260209-143052-a1b2c3
X-Retryable: false
X-User-Fixable: true
```

These can be used for:
- Quick routing decisions in middleware
- Monitoring dashboards
- Load balancer retry logic

---

## Error Handling Best Practices

### 1. Always Check `error_category`

```python
# Good - handles all categories
if error["error_category"] in ["DATA_MISSING", "DATA_QUALITY", "DATA_INCOMPATIBLE", "PARAMETER_ERROR"]:
    show_user_error(error)
else:
    show_system_error(error)

# Bad - only checks error_code
if error["error_code"] == "FILE_NOT_FOUND":
    # Misses other DATA_MISSING errors
```

### 2. Always Store `error_id`

```python
# Good - store for support tickets
def log_job_failure(job_id: str, error: dict):
    db.store({
        "job_id": job_id,
        "error_id": error["error_id"],
        "error_code": error["error_code"],
        "timestamp": datetime.utcnow()
    })
```

### 3. Display Remediation for User-Fixable Errors

```python
# Good - actionable message
if error["user_fixable"] and error.get("remediation"):
    show_message(error["message"])
    show_action(error["remediation"])
else:
    show_message(error["message"])
```

### 4. Use `error_scope` for DAG Workflows

```python
# Good - different handling for node vs workflow errors
if error["error_scope"] == "workflow":
    # Entire collection has a problem
    show_collection_error(error)
elif error["error_scope"] == "node":
    # Single file has a problem
    show_file_error(error)
```

---

## Testing Error Handling

### Test Endpoints

```bash
# Trigger FILE_NOT_FOUND
curl -X POST https://api.example.com/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "nonexistent.tif", "container": "bronze-uploads"}'

# Trigger MISSING_PARAMETER
curl -X POST https://api.example.com/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Mock Error Responses

Use these mock responses for integration testing:

```json
// DATA_QUALITY mock
{
    "success": false,
    "error_code": "RASTER_64BIT_REJECTED",
    "error_category": "DATA_QUALITY",
    "error_scope": "node",
    "retryable": false,
    "user_fixable": true,
    "http_status": 400,
    "message": "File uses 64-bit float data type",
    "remediation": "Re-export as 32-bit float.",
    "error_id": "ERR-TEST-000001"
}

// SERVICE_UNAVAILABLE mock
{
    "success": false,
    "error_code": "DATABASE_TIMEOUT",
    "error_category": "SERVICE_UNAVAILABLE",
    "error_scope": "node",
    "retryable": true,
    "user_fixable": false,
    "http_status": 503,
    "message": "Database timeout",
    "error_id": "ERR-TEST-000002"
}
```

---

## Support Escalation

When escalating to support, include:

1. **error_id** - The unique error identifier
2. **Timestamp** - When the error occurred
3. **Job ID** - If available in the response
4. **Request payload** - What was submitted (redact sensitive data)
5. **Steps to reproduce** - If the error is consistent

Example support ticket:
```
Subject: API Error ERR-20260209-143052-a1b2c3

Error ID: ERR-20260209-143052-a1b2c3
Error Code: COG_CREATION_FAILED
Timestamp: 2026-02-09T14:30:52Z
Job ID: abc123def456

Request:
  Container: bronze-uploads
  File: large_dem.tif

The job fails consistently with the same error.
```

---

## Related Documentation

- [Error Code Reference](./ERROR_CODE_REFERENCE.md) - Complete error code inventory
- [Error Troubleshooting Guide](./ERROR_TROUBLESHOOTING.md) - Fix common errors
- [API Documentation](./API.md) - Full API reference

---

*Document maintained by: Engineering Team*
*Last updated: 09 FEB 2026*
