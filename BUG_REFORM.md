# BUG_REFORM.md - Error Handling & Validation Reform

**Created**: 06 FEB 2026
**Status**: PLANNING
**Priority**: HIGH - QA/B2B User Experience

---

## Executive Summary

QA testers submitting "garbage data" receive unclear error messages that look like server errors rather than input data problems. This document outlines a reform to:

1. **Enhance validation** - Catch more data quality issues before/during pipeline execution
2. **Improve error categorization** - Distinguish "your data problem" from "our system problem"
3. **Create B2B-friendly messages** - Clear, actionable error messages with remediation guidance

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Gap Analysis](#2-gap-analysis)
3. [Proposed Error Model](#3-proposed-error-model)
   - 3.1 [New Error Category System](#31-new-error-category-system)
   - 3.2 [Enhanced Error Response](#32-enhanced-error-response)
   - 3.3 [Error Code Expansion](#33-error-code-expansion)
   - 3.4 [Error-to-Category Mapping](#34-error-to-category-mapping)
   - 3.5 [Error-to-Scope Mapping (v0.9 DAG Ready)](#35-error-to-scope-mapping-v09-dag-ready)
   - 3.6 [Error-to-Category Mapping (Blame Assignment)](#36-error-to-category-mapping-blame-assignment)
4. [Error Category System](#4-error-category-system)
5. [Error Code Architecture](#5-error-code-architecture)
   - 5.1 [DAG-Oriented Error Classification](#51-dag-oriented-error-classification-v09-ready)
   - 5.2 [Hybrid Approach: Shared + Workflow-Specific](#52-hybrid-approach-shared--workflow-specific)
   - 5.3 [Workflow Error Inheritance](#53-workflow-error-inheritance)
6. [Raster Error Catalog](#6-raster-error-catalog)
7. [Vector Error Catalog](#7-vector-error-catalog)
8. [Collection Error Catalog](#8-collection-error-catalog)
9. [Debug & Traceback Handling](#9-debug--traceback-handling)
10. [Raster Collection Homogeneity](#10-raster-collection-homogeneity)
11. [Implementation Plan](#11-implementation-plan)
12. [Migration Strategy](#12-migration-strategy)

---

## 1. Current State Assessment

### 1.1 Error Code System (`core/errors.py`)

**Current ErrorCode enum** - 25 codes across three categories:

| Category | Codes | HTTP Status | Retryable |
|----------|-------|-------------|-----------|
| **VALIDATION** | `CONTAINER_NOT_FOUND`, `FILE_NOT_FOUND`, `RESOURCE_NOT_FOUND`, `FILE_UNREADABLE`, `CRS_MISSING`, `INVALID_FORMAT`, `CORRUPTED_FILE`, `VALIDATION_ERROR`, `INVALID_PARAMETER`, `MISSING_PARAMETER` | 400/404 | No |
| **PROCESSING** | `SETUP_FAILED`, `CONFIG_ERROR`, `CRS_CHECK_FAILED`, `REPROJECTION_FAILED`, `COG_TRANSLATE_FAILED`, `COG_CREATION_FAILED`, `PROCESSING_FAILED` | 500 | Mixed |
| **INFRASTRUCTURE** | `DATABASE_ERROR`, `DATABASE_TIMEOUT`, `DATABASE_CONNECTION_FAILED`, `STORAGE_ERROR`, `STORAGE_TIMEOUT`, `UPLOAD_FAILED`, `DOWNLOAD_FAILED`, `QUEUE_ERROR`, `MESSAGE_ERROR`, `MEMORY_ERROR`, `DISK_FULL`, `TIMEOUT`, `THROTTLED` | 500/503 | Yes |

**Current ErrorClassification enum**:
- `PERMANENT` - Never retry (client errors)
- `TRANSIENT` - Retry with exponential backoff
- `THROTTLING` - Retry with longer delay

### 1.2 Exception Hierarchy (`exceptions.py`)

```
Exception
├── ContractViolationError(TypeError)  ← Programming bugs, never catch
└── BusinessLogicError(Exception)       ← Expected failures, handle gracefully
    ├── ServiceBusError
    ├── DatabaseError
    ├── TaskExecutionError
    ├── ResourceNotFoundError
    └── ValidationError

ConfigurationError(Exception)           ← Fatal misconfiguration
```

### 1.3 Error Response Structure

Current `create_error_response()` returns:

```python
{
    "success": False,
    "error": "FILE_NOT_FOUND",           # ErrorCode value
    "error_type": "ResourceNotFoundError", # Exception class name
    "message": "File 'test.tif' not found...",
    "retryable": False,
    "http_status": 404,
    # ...additional context fields
}
```

### 1.4 Pre-Flight Validators (`infrastructure/validators.py`)

10 registered validators checking resource **existence**, not **content**:

| Validator | What It Checks |
|-----------|----------------|
| `blob_exists` | Blob path exists |
| `blob_exists_with_size` | Existence + size limits |
| `blob_list_exists` | All blobs in list exist |
| `blob_list_exists_with_max_size` | List + size thresholds |
| `container_exists` | Container exists |
| `table_exists` / `table_not_exists` | PostGIS table checks |
| `stac_item_exists` / `stac_collection_exists` | STAC catalog checks |
| `csv_geometry_params` | CSV has lat/lon or WKT |

### 1.5 Raster Validation (`services/raster_validation.py`)

9-step validation process with comprehensive checks:

1. Logger initialization
2. Parameter extraction
3. Pre-flight blob validation
4. Open raster with rasterio
5. Extract metadata (bands, dtype, shape, bounds, nodata)
6. Memory footprint estimation
7. CRS validation
8. Bit-depth efficiency check (samples 1000x1000 pixels)
9. Raster type detection

**Current detection capabilities**:
- RGB: 3 bands, uint8/16
- RGBA: 4 bands, alpha detection
- DEM: 1 band float/int, smoothness metric
- Categorical: <256 unique integers
- Multispectral: 5+ bands

### 1.6 Raster Collection Processing (`services/handler_raster_collection_complete.py`)

**Critical Gap**: Each file validated independently. No cross-file homogeneity check.

```python
# Line 442-454: Raster type inferred from FIRST file only
raster_type_info = {
    'detected_type': rt.get('detected_type', 'unknown'),
    'band_count': v.get('band_count', 3),
    'data_type': v.get('data_type', 'uint8'),
}
```

---

## 2. Gap Analysis

### 2.1 Error Categorization Gap

**Problem**: B2B users cannot distinguish between:
- Their data is bad (they need to fix it)
- Our system has a problem (they should retry or contact support)

**Current state**: All errors look similar - just different error codes.

**Example of confusion**:
```json
{
    "error": "PROCESSING_FAILED",
    "message": "Failed to create COG"
}
```

User thinks: "Is this my file or their server?"

### 2.2 Missing Validation Checks

| Check | Current State | Impact |
|-------|--------------|--------|
| Nodata value sanity | NOT CHECKED | Nodata matching real values creates holes |
| Value range sanity | NOT CHECKED | DEMs with 1e38 values (unset nodata) |
| Mostly-empty detection | NOT CHECKED | 99% nodata files waste resources |
| File corruption | PARTIAL | Truncated TIFFs may not be caught |
| Collection homogeneity | NOT CHECKED | Mixed band counts, dtypes, CRS |

### 2.3 Pre-Flight vs Pipeline Validation

**Architecture constraint**: Pre-flight must be fast/synchronous.

| Layer | Purpose | Can Open Files? |
|-------|---------|-----------------|
| Pre-flight | Existence, size, parameter validation | NO (too slow) |
| Pipeline | Deep content validation | YES |

**Decision**: Keep deep validation in pipeline, but make errors crystal clear.

### 2.4 Error Message Quality

**Current**: Technical, terse, operator-focused

```
"CRS mismatch: File metadata indicates EPSG:32611 but user specified EPSG:4326"
```

**Needed**: User-focused, actionable, with remediation

```
"Your file 'aerial.tif' has CRS EPSG:32611 embedded in its metadata, but you
specified EPSG:4326 in the request. Either remove the 'input_crs' parameter
to use the file's CRS, or re-export your file with the correct CRS."
```

---

## 3. Proposed Error Model

### 3.1 New Error Category System

Add `ErrorCategory` enum to distinguish blame:

```python
class ErrorCategory(str, Enum):
    """
    Who is responsible for fixing this error?

    B2B API consumers use this to determine:
    - Should they fix their input and retry?
    - Should they contact support?
    - Should they just retry later?
    """

    # USER'S PROBLEM - They need to fix their input
    DATA_QUALITY = "DATA_QUALITY"       # Bad file content (corrupt, wrong format)
    DATA_MISSING = "DATA_MISSING"       # File/resource not found
    DATA_INCOMPATIBLE = "DATA_INCOMPATIBLE"  # Collection files don't match
    PARAMETER_ERROR = "PARAMETER_ERROR"  # Bad request parameters

    # OUR PROBLEM - We need to fix or they should retry
    SYSTEM_ERROR = "SYSTEM_ERROR"       # Internal server error
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"  # Temporary outage

    # CONFIGURATION - Ops team problem
    CONFIGURATION = "CONFIGURATION"     # Missing env vars, bad config


class ErrorScope(str, Enum):
    """
    Where in the DAG did the error occur? (v0.9 Ready)

    Used for:
    - Retry strategy (node errors can retry single step)
    - Error aggregation (workflow errors affect entire job)
    - Future DAG visualization (highlight failed node vs failed edge)
    """

    NODE = "node"          # Error in single processing step (bad input data)
    WORKFLOW = "workflow"  # Error in orchestration (nodes don't fit together)
```

### 3.2 Enhanced Error Response

```python
{
    "success": False,

    # Machine-readable classification
    "error_code": "COLLECTION_BAND_MISMATCH",
    "error_category": "DATA_INCOMPATIBLE",  # ← Who's responsible
    "error_scope": "workflow",              # ← DAG scope: "node" or "workflow" (v0.9 ready)
    "retryable": False,
    "http_status": 400,

    # Human-readable explanation
    "message": "Collection contains rasters with different band counts",

    # Structured details for debugging
    "details": {
        "expected": "All files must have same band count",
        "found": [
            {"file": "image1.tif", "bands": 3, "type": "RGB"},
            {"file": "image2.tif", "bands": 1, "type": "DEM"}
        ],
        "first_mismatch_at": "image2.tif"
    },

    # Actionable guidance
    "remediation": "Remove 'image2.tif' from the collection or submit it as a separate single-raster job. All files in a collection must have the same band count.",

    # Support reference (only in debug mode for B2B, always stored in job record)
    "error_id": "ERR-2026020612345",

    # Debug section (conditional - see section 9)
    "debug": { ... }  # Only included when config.debug_mode=True
}
```

### 3.3 Error Code Expansion

New error codes needed:

```python
# DATA_QUALITY errors (user's file is bad)
RASTER_CORRUPT = "RASTER_CORRUPT"           # File truncated or damaged
RASTER_EMPTY = "RASTER_EMPTY"               # 99%+ nodata pixels
RASTER_INVALID_NODATA = "RASTER_INVALID_NODATA"  # Nodata value in actual data
RASTER_EXTREME_VALUES = "RASTER_EXTREME_VALUES"  # DEM with 1e38 values
RASTER_64BIT_REJECTED = "RASTER_64BIT_REJECTED"  # Policy violation

# DATA_INCOMPATIBLE errors (collection mismatch)
COLLECTION_BAND_MISMATCH = "COLLECTION_BAND_MISMATCH"
COLLECTION_DTYPE_MISMATCH = "COLLECTION_DTYPE_MISMATCH"
COLLECTION_CRS_MISMATCH = "COLLECTION_CRS_MISMATCH"
COLLECTION_RESOLUTION_MISMATCH = "COLLECTION_RESOLUTION_MISMATCH"
COLLECTION_DISJOINT_BOUNDS = "COLLECTION_DISJOINT_BOUNDS"
COLLECTION_TYPE_MISMATCH = "COLLECTION_TYPE_MISMATCH"  # RGB + DEM mixed
```

### 3.4 Error-to-Category Mapping

```python
_ERROR_CATEGORY: Dict[ErrorCode, ErrorCategory] = {
    # ... (see full mapping in section 5)
}

def get_error_category(error_code: ErrorCode) -> ErrorCategory:
    """Get category for an error code."""
    return _ERROR_CATEGORY.get(error_code, ErrorCategory.SYSTEM_ERROR)
```

### 3.5 Error-to-Scope Mapping (v0.9 DAG Ready)

Maps each error code to its DAG scope (NODE vs WORKFLOW):
- **NODE**: Error in single processing step - affects one input/output
- **WORKFLOW**: Error in orchestration - affects relationships between valid nodes

```python
_ERROR_SCOPE: Dict[ErrorCode, ErrorScope] = {
    # =========================================================================
    # NODE ERRORS - Single input/step failures
    # =========================================================================

    # Resource not found (single file)
    ErrorCode.CONTAINER_NOT_FOUND: ErrorScope.NODE,
    ErrorCode.FILE_NOT_FOUND: ErrorScope.NODE,
    ErrorCode.RESOURCE_NOT_FOUND: ErrorScope.NODE,

    # Bad file content (single file)
    ErrorCode.FILE_UNREADABLE: ErrorScope.NODE,
    ErrorCode.CORRUPTED_FILE: ErrorScope.NODE,
    ErrorCode.INVALID_FORMAT: ErrorScope.NODE,
    ErrorCode.CRS_MISSING: ErrorScope.NODE,

    # Raster-specific (single file)
    ErrorCode.RASTER_UNREADABLE: ErrorScope.NODE,
    ErrorCode.RASTER_64BIT_REJECTED: ErrorScope.NODE,
    ErrorCode.RASTER_EMPTY: ErrorScope.NODE,
    ErrorCode.RASTER_NODATA_CONFLICT: ErrorScope.NODE,
    ErrorCode.RASTER_EXTREME_VALUES: ErrorScope.NODE,
    ErrorCode.RASTER_BAND_INVALID: ErrorScope.NODE,
    ErrorCode.RASTER_TYPE_MISMATCH: ErrorScope.NODE,

    # Vector-specific (single file)
    ErrorCode.VECTOR_UNREADABLE: ErrorScope.NODE,
    ErrorCode.VECTOR_NO_FEATURES: ErrorScope.NODE,
    ErrorCode.VECTOR_GEOMETRY_INVALID: ErrorScope.NODE,
    ErrorCode.VECTOR_GEOMETRY_EMPTY: ErrorScope.NODE,
    ErrorCode.VECTOR_COORDINATE_ERROR: ErrorScope.NODE,
    ErrorCode.VECTOR_ENCODING_ERROR: ErrorScope.NODE,
    ErrorCode.VECTOR_ATTRIBUTE_ERROR: ErrorScope.NODE,
    ErrorCode.VECTOR_TABLE_NAME_INVALID: ErrorScope.NODE,

    # Parameter errors (single request)
    ErrorCode.VALIDATION_ERROR: ErrorScope.NODE,
    ErrorCode.INVALID_PARAMETER: ErrorScope.NODE,
    ErrorCode.MISSING_PARAMETER: ErrorScope.NODE,

    # System/infrastructure errors (single operation)
    ErrorCode.PROCESSING_FAILED: ErrorScope.NODE,
    ErrorCode.COG_CREATION_FAILED: ErrorScope.NODE,
    ErrorCode.COG_TRANSLATE_FAILED: ErrorScope.NODE,
    ErrorCode.REPROJECTION_FAILED: ErrorScope.NODE,
    ErrorCode.DATABASE_ERROR: ErrorScope.NODE,
    ErrorCode.STORAGE_ERROR: ErrorScope.NODE,
    ErrorCode.UPLOAD_FAILED: ErrorScope.NODE,
    ErrorCode.DOWNLOAD_FAILED: ErrorScope.NODE,

    # Temporary failures (single operation)
    ErrorCode.DATABASE_TIMEOUT: ErrorScope.NODE,
    ErrorCode.STORAGE_TIMEOUT: ErrorScope.NODE,
    ErrorCode.THROTTLED: ErrorScope.NODE,
    ErrorCode.TIMEOUT: ErrorScope.NODE,

    # Configuration (affects single component)
    ErrorCode.CONFIG_ERROR: ErrorScope.NODE,
    ErrorCode.SETUP_FAILED: ErrorScope.NODE,

    # =========================================================================
    # WORKFLOW ERRORS - Orchestration/relationship failures
    # =========================================================================

    # Collection homogeneity (valid files, incompatible together)
    ErrorCode.COLLECTION_BAND_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_DTYPE_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_CRS_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_RESOLUTION_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_TYPE_MISMATCH: ErrorScope.WORKFLOW,
    ErrorCode.COLLECTION_BOUNDS_DISJOINT: ErrorScope.WORKFLOW,

    # Workflow-level failures (affect entire job graph)
    # ErrorCode.WORKFLOW_TIMEOUT: ErrorScope.WORKFLOW,  # Future: overall job timeout
    # ErrorCode.WORKFLOW_DEPENDENCY_FAILED: ErrorScope.WORKFLOW,  # Future: upstream failure
}


def get_error_scope(error_code: ErrorCode) -> ErrorScope:
    """
    Get DAG scope for an error code.

    Returns:
        ErrorScope.NODE for individual step failures
        ErrorScope.WORKFLOW for orchestration failures
        Defaults to NODE if not explicitly mapped
    """
    return _ERROR_SCOPE.get(error_code, ErrorScope.NODE)
```

### 3.6 Error-to-Category Mapping (Blame Assignment)

Maps each error code to its category (who's responsible for fixing):

```python
_ERROR_CATEGORY: Dict[ErrorCode, ErrorCategory] = {
    # DATA_MISSING - User's file not found
    ErrorCode.CONTAINER_NOT_FOUND: ErrorCategory.DATA_MISSING,
    ErrorCode.FILE_NOT_FOUND: ErrorCategory.DATA_MISSING,
    ErrorCode.RESOURCE_NOT_FOUND: ErrorCategory.DATA_MISSING,

    # DATA_QUALITY - User's file content is bad
    ErrorCode.FILE_UNREADABLE: ErrorCategory.DATA_QUALITY,
    ErrorCode.CORRUPTED_FILE: ErrorCategory.DATA_QUALITY,
    ErrorCode.INVALID_FORMAT: ErrorCategory.DATA_QUALITY,
    ErrorCode.CRS_MISSING: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_UNREADABLE: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_64BIT_REJECTED: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_EMPTY: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_NODATA_CONFLICT: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_EXTREME_VALUES: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_BAND_INVALID: ErrorCategory.DATA_QUALITY,
    ErrorCode.RASTER_TYPE_MISMATCH: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_UNREADABLE: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_NO_FEATURES: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_GEOMETRY_INVALID: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_GEOMETRY_EMPTY: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_COORDINATE_ERROR: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_ENCODING_ERROR: ErrorCategory.DATA_QUALITY,
    ErrorCode.VECTOR_ATTRIBUTE_ERROR: ErrorCategory.DATA_QUALITY,

    # DATA_INCOMPATIBLE - User's collection files don't match
    ErrorCode.COLLECTION_BAND_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_DTYPE_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_CRS_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_RESOLUTION_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_TYPE_MISMATCH: ErrorCategory.DATA_INCOMPATIBLE,
    ErrorCode.COLLECTION_BOUNDS_DISJOINT: ErrorCategory.DATA_INCOMPATIBLE,

    # PARAMETER_ERROR - User's request is wrong
    ErrorCode.VALIDATION_ERROR: ErrorCategory.PARAMETER_ERROR,
    ErrorCode.INVALID_PARAMETER: ErrorCategory.PARAMETER_ERROR,
    ErrorCode.MISSING_PARAMETER: ErrorCategory.PARAMETER_ERROR,
    ErrorCode.VECTOR_TABLE_NAME_INVALID: ErrorCategory.PARAMETER_ERROR,

    # SYSTEM_ERROR - Our problem
    ErrorCode.PROCESSING_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.COG_CREATION_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.COG_TRANSLATE_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.REPROJECTION_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.DATABASE_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.STORAGE_ERROR: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.UPLOAD_FAILED: ErrorCategory.SYSTEM_ERROR,
    ErrorCode.DOWNLOAD_FAILED: ErrorCategory.SYSTEM_ERROR,

    # SERVICE_UNAVAILABLE - Temporary, retry later
    ErrorCode.DATABASE_TIMEOUT: ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCode.STORAGE_TIMEOUT: ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCode.THROTTLED: ErrorCategory.SERVICE_UNAVAILABLE,
    ErrorCode.TIMEOUT: ErrorCategory.SERVICE_UNAVAILABLE,

    # CONFIGURATION - Ops team problem
    ErrorCode.CONFIG_ERROR: ErrorCategory.CONFIGURATION,
    ErrorCode.SETUP_FAILED: ErrorCategory.CONFIGURATION,
}


def get_error_category(error_code: ErrorCode) -> ErrorCategory:
    """
    Get category for an error code (who's responsible for fixing).

    Returns:
        ErrorCategory indicating blame assignment
        Defaults to SYSTEM_ERROR if not explicitly mapped
    """
    return _ERROR_CATEGORY.get(error_code, ErrorCategory.SYSTEM_ERROR)
```

---

## 4. Error Category System

### 4.1 Category Descriptions for B2B Users

| Category | Meaning | User Action |
|----------|---------|-------------|
| `DATA_MISSING` | Your file wasn't found | Check file path, ensure upload completed |
| `DATA_QUALITY` | Your file is bad | Fix the file and resubmit |
| `DATA_INCOMPATIBLE` | Collection files don't match | Make files consistent or split into separate jobs |
| `PARAMETER_ERROR` | Your request parameters are wrong | Fix parameters and resubmit |
| `SYSTEM_ERROR` | Our system failed | Contact support with error_id |
| `SERVICE_UNAVAILABLE` | Temporary outage | Retry in a few minutes |
| `CONFIGURATION` | System misconfigured | Contact support immediately |

### 4.2 Category-Based Retry Logic

```python
def should_user_retry(category: ErrorCategory) -> bool:
    """Can the user fix this and retry?"""
    return category in {
        ErrorCategory.DATA_MISSING,
        ErrorCategory.DATA_QUALITY,
        ErrorCategory.DATA_INCOMPATIBLE,
        ErrorCategory.PARAMETER_ERROR,
    }

def should_auto_retry(category: ErrorCategory) -> bool:
    """Should the system automatically retry?"""
    return category == ErrorCategory.SERVICE_UNAVAILABLE
```

### 4.3 B2B Response Headers

```http
HTTP/1.1 400 Bad Request
X-Error-Category: DATA_QUALITY
X-Error-Code: RASTER_64BIT_REJECTED
X-Retryable: false
X-User-Fixable: true
```

---

## 5. Error Code Architecture

### 5.1 DAG-Oriented Error Classification (v0.9 Ready)

Errors are classified by **where they occur** in the execution graph:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WORKFLOW ERRORS                                    │
│   Errors at the orchestration level - relationships between valid nodes      │
│                                                                              │
│   Examples:                                                                  │
│   - COLLECTION_BAND_MISMATCH (all files valid, but incompatible together)   │
│   - COLLECTION_CRS_MISMATCH (valid rasters, different coordinate systems)   │
│   - WORKFLOW_TIMEOUT (overall job exceeded time limit)                       │
│   - WORKFLOW_DEPENDENCY_FAILED (upstream node failed)                        │
│                                                                              │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐                               │
│   │ Node 1  │────▶│ Node 2  │────▶│ Node 3  │  ← Workflow orchestrates      │
│   │ (valid) │     │ (valid) │     │ (valid) │    relationships              │
│   └─────────┘     └─────────┘     └─────────┘                               │
│                         │                                                    │
│                         ▼                                                    │
│              ❌ WORKFLOW ERROR: Nodes incompatible                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                             NODE ERRORS                                      │
│   Errors within a single processing step - the data itself is bad           │
│                                                                              │
│   Examples:                                                                  │
│   - RASTER_64BIT_REJECTED (this specific file has bad dtype)                │
│   - RASTER_CORRUPT (this specific file is damaged)                          │
│   - VECTOR_GEOMETRY_INVALID (this specific file has bad geometry)           │
│   - CRS_MISSING (this specific file lacks CRS)                              │
│                                                                              │
│   ┌─────────┐                                                               │
│   │  Node   │  ← Individual step processes single input                     │
│   │ (input) │                                                               │
│   └────┬────┘                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ❌ NODE ERROR: Input data invalid                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why This Matters for DAG (v0.9)**:

| Error Type | Scope | Retry Strategy | Affects |
|------------|-------|----------------|---------|
| **Node Error** | Single step | Retry that node only | Only failed branch |
| **Workflow Error** | Orchestration | May need workflow redesign | Entire workflow |

**Current Mapping to Error Categories**:

| Error Category | DAG Classification |
|----------------|-------------------|
| `DATA_QUALITY` | Node Error (input data bad) |
| `DATA_MISSING` | Node Error (input not found) |
| `DATA_INCOMPATIBLE` | Workflow Error (nodes don't fit together) |
| `PARAMETER_ERROR` | Can be either (depends on scope) |
| `SYSTEM_ERROR` | Node Error (infrastructure issue) |
| `SERVICE_UNAVAILABLE` | Node Error (retryable infra) |

### 5.2 Hybrid Approach: Shared + Workflow-Specific

Error codes follow a **hybrid model**:
- **Shared codes** for concepts that apply across workflows (FILE_NOT_FOUND, CRS_MISSING)
- **Prefixed codes** for workflow-specific concepts (RASTER_64BIT_REJECTED, VECTOR_GEOMETRY_INVALID)

```python
class ErrorCode(str, Enum):
    # =========================================================================
    # SHARED CODES - Apply to multiple workflows
    # =========================================================================
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_UNREADABLE = "FILE_UNREADABLE"
    CRS_MISSING = "CRS_MISSING"
    CRS_MISMATCH = "CRS_MISMATCH"
    INVALID_FORMAT = "INVALID_FORMAT"
    CORRUPTED_FILE = "CORRUPTED_FILE"

    # Parameter errors (shared)
    MISSING_PARAMETER = "MISSING_PARAMETER"
    INVALID_PARAMETER = "INVALID_PARAMETER"

    # =========================================================================
    # RASTER-SPECIFIC CODES - Concepts unique to raster data
    # =========================================================================
    RASTER_UNREADABLE = "RASTER_UNREADABLE"         # GDAL can't open
    RASTER_64BIT_REJECTED = "RASTER_64BIT_REJECTED" # Policy violation
    RASTER_EMPTY = "RASTER_EMPTY"                   # 99%+ nodata
    RASTER_NODATA_CONFLICT = "RASTER_NODATA_CONFLICT"  # Nodata in real data
    RASTER_EXTREME_VALUES = "RASTER_EXTREME_VALUES" # DEM with 1e38
    RASTER_BAND_INVALID = "RASTER_BAND_INVALID"     # 0 bands or >100 bands
    RASTER_TYPE_MISMATCH = "RASTER_TYPE_MISMATCH"   # User said RGB, detected DEM

    # =========================================================================
    # VECTOR-SPECIFIC CODES - Concepts unique to vector data
    # =========================================================================
    VECTOR_UNREADABLE = "VECTOR_UNREADABLE"         # Can't parse file
    VECTOR_NO_FEATURES = "VECTOR_NO_FEATURES"       # Empty after filtering
    VECTOR_GEOMETRY_INVALID = "VECTOR_GEOMETRY_INVALID"  # Bad geometry
    VECTOR_GEOMETRY_EMPTY = "VECTOR_GEOMETRY_EMPTY" # All null geometries
    VECTOR_COORDINATE_ERROR = "VECTOR_COORDINATE_ERROR"  # Can't parse lat/lon
    VECTOR_ENCODING_ERROR = "VECTOR_ENCODING_ERROR" # Character encoding issue
    VECTOR_ATTRIBUTE_ERROR = "VECTOR_ATTRIBUTE_ERROR"  # Column type issue
    VECTOR_TABLE_NAME_INVALID = "VECTOR_TABLE_NAME_INVALID"  # Bad table name

    # =========================================================================
    # COLLECTION-SPECIFIC CODES - Relationship between valid files
    # =========================================================================
    # Note: Individual file errors use RASTER_* codes above
    COLLECTION_BAND_MISMATCH = "COLLECTION_BAND_MISMATCH"
    COLLECTION_DTYPE_MISMATCH = "COLLECTION_DTYPE_MISMATCH"
    COLLECTION_CRS_MISMATCH = "COLLECTION_CRS_MISMATCH"
    COLLECTION_RESOLUTION_MISMATCH = "COLLECTION_RESOLUTION_MISMATCH"
    COLLECTION_TYPE_MISMATCH = "COLLECTION_TYPE_MISMATCH"  # RGB + DEM mixed
    COLLECTION_BOUNDS_DISJOINT = "COLLECTION_BOUNDS_DISJOINT"  # No spatial relationship

    # =========================================================================
    # SYSTEM CODES - Our problem, not user's data
    # =========================================================================
    # (existing codes remain)
```

### 5.3 Workflow Error Inheritance

```
Raster Collection Job
│
├── Phase 1: Download
│   └── Uses: FILE_NOT_FOUND, STORAGE_ERROR
│
├── Phase 2: Validate Each File (SHARED with single-raster workflow)
│   └── Uses: RASTER_* codes (same logic as process_raster_docker)
│
├── Phase 3: Validate Homogeneity (COLLECTION-SPECIFIC)
│   └── Uses: COLLECTION_* codes (only applies to collections)
│
├── Phase 4: COG Creation
│   └── Uses: COG_CREATION_FAILED, PROCESSING_FAILED
│
└── Phase 5: STAC Registration
    └── Uses: DATABASE_ERROR, STAC_* codes
```

This means a raster collection job can fail with:
- `RASTER_64BIT_REJECTED` - One file in the collection has bad data (same error as single-raster)
- `COLLECTION_BAND_MISMATCH` - All files are valid individually, but incompatible together

---

## 6. Raster Error Catalog

### 6.1 Single-Raster Errors (Used by both single and collection workflows)

| Error Code | Category | When It Occurs | User Message | Remediation |
|------------|----------|----------------|--------------|-------------|
| `FILE_NOT_FOUND` | DATA_MISSING | Pre-flight or download | File '{blob_name}' not found in container '{container}' | Verify file path spelling. Ensure upload completed before job submission. |
| `RASTER_UNREADABLE` | DATA_QUALITY | GDAL open fails | File '{blob_name}' is not a valid raster or is corrupted | Ensure file is a valid GeoTIFF. Do not rename other formats to .tif. |
| `CRS_MISSING` | DATA_QUALITY | No CRS in file or params | File has no coordinate reference system and no 'input_crs' parameter | Add 'input_crs' parameter (e.g., 'EPSG:4326') or embed CRS in source file. |
| `CRS_MISMATCH` | DATA_QUALITY | File CRS ≠ user CRS | File has CRS {file_crs} but you specified {user_crs} | Remove 'input_crs' to use file's CRS, or fix the file's embedded CRS. |
| `RASTER_64BIT_REJECTED` | DATA_QUALITY | Policy check | File uses 64-bit data type ({dtype}) which is not accepted | Re-export your raster as 32-bit float or integer. 64-bit is unnecessary for geospatial data. |
| `RASTER_EMPTY` | DATA_QUALITY | Sampling check | File is {percent}% nodata - effectively empty | Provide a file with actual data pixels. This file contains almost no usable data. |
| `RASTER_NODATA_CONFLICT` | DATA_QUALITY | Sampling check | Nodata value ({nodata}) appears in actual data, causing data loss | Change the nodata value to one not present in your data, or set nodata to None. |
| `RASTER_EXTREME_VALUES` | DATA_QUALITY | Value range check | DEM contains extreme values (max: {max}) suggesting corrupt or unset nodata | Set proper nodata value in file. Values like 3.4e38 indicate uninitialized pixels. |
| `RASTER_BAND_INVALID` | DATA_QUALITY | Metadata check | File has {count} bands which is invalid (expected 1-100) | Ensure file is a valid multi-band raster, not a corrupted file. |
| `RASTER_TYPE_MISMATCH` | DATA_QUALITY | Type detection | You specified raster_type='{user_type}' but file appears to be '{detected_type}' | Remove raster_type parameter for auto-detection, or fix your file. |

### 6.2 Raster Error Decision Tree

```
Can GDAL open the file?
├── NO → RASTER_UNREADABLE
└── YES → Does file have CRS?
    ├── NO → Did user provide input_crs?
    │   ├── NO → CRS_MISSING
    │   └── YES → Continue
    └── YES → Does user CRS match file CRS?
        ├── NO → CRS_MISMATCH
        └── YES → Is dtype 64-bit?
            ├── YES → RASTER_64BIT_REJECTED
            └── NO → Is file mostly nodata?
                ├── YES (>99%) → RASTER_EMPTY
                └── NO → Does nodata value appear in real data?
                    ├── YES → RASTER_NODATA_CONFLICT
                    └── NO → Are values in sane range?
                        ├── NO (DEM with 1e38) → RASTER_EXTREME_VALUES
                        └── YES → VALIDATION PASSED ✓
```

---

## 7. Vector Error Catalog

### 7.1 Vector-Specific Errors

| Error Code | Category | When It Occurs | User Message | Remediation |
|------------|----------|----------------|--------------|-------------|
| `FILE_NOT_FOUND` | DATA_MISSING | Pre-flight | File '{blob_name}' not found in container '{container}' | Verify file path and ensure upload completed. |
| `VECTOR_UNREADABLE` | DATA_QUALITY | File parse fails | File '{blob_name}' could not be parsed as {format} | Ensure file is valid {format}. Check for truncation or encoding issues. |
| `VECTOR_NO_FEATURES` | DATA_QUALITY | After filtering | File contains no features after removing invalid geometries | Source file is empty or all geometries are invalid. Check source data. |
| `VECTOR_GEOMETRY_INVALID` | DATA_QUALITY | Geometry validation | {count} features have invalid geometry that cannot be auto-repaired | Fix geometries in source file using GIS software (e.g., ST_MakeValid). |
| `VECTOR_GEOMETRY_EMPTY` | DATA_QUALITY | Geometry check | All {count} features have null or empty geometry | Ensure your file contains geometry data, not just attributes. |
| `VECTOR_COORDINATE_ERROR` | DATA_QUALITY | CSV lat/lon parsing | Cannot parse coordinates from columns '{lat_col}' and '{lon_col}' | Ensure columns contain valid numeric coordinates. Check for text or null values. |
| `VECTOR_ENCODING_ERROR` | DATA_QUALITY | Character encoding | File contains invalid characters (encoding: {detected}) | Re-export file as UTF-8 encoding. Current encoding '{detected}' has invalid bytes. |
| `VECTOR_ATTRIBUTE_ERROR` | DATA_QUALITY | Column type issue | Column '{column}' has mixed types that cannot be reconciled | Ensure column has consistent data type (all text or all numeric). |
| `VECTOR_TABLE_NAME_INVALID` | PARAMETER_ERROR | Table name validation | Table name '{name}' is invalid: {reason} | Use lowercase letters, numbers, underscores. Cannot start with number. |
| `CRS_MISSING` | DATA_QUALITY | No CRS detected | File has no coordinate reference system | Add 'input_crs' parameter or embed CRS in source file. |
| `MISSING_PARAMETER` | PARAMETER_ERROR | CSV without geometry params | CSV files require geometry parameters | Provide 'lat_name' + 'lon_name' for points, or 'wkt_column' for WKT geometry. |

### 7.2 Vector Error Decision Tree

```
Can file be parsed?
├── NO → Is it encoding issue?
│   ├── YES → VECTOR_ENCODING_ERROR
│   └── NO → VECTOR_UNREADABLE
└── YES → Does file have geometry?
    ├── NO (all null) → VECTOR_GEOMETRY_EMPTY
    └── YES → Is geometry valid?
        ├── NO (some invalid) → Can we repair?
        │   ├── YES → Continue (log warning)
        │   └── NO → VECTOR_GEOMETRY_INVALID
        └── YES → Does file have CRS?
            ├── NO → CRS_MISSING
            └── YES → Any features after filtering?
                ├── NO → VECTOR_NO_FEATURES
                └── YES → VALIDATION PASSED ✓
```

---

## 8. Collection Error Catalog

### 8.1 Collection-Specific Errors (Valid files, incompatible together)

These errors occur AFTER individual file validation passes. Each file is valid on its own,
but they cannot be processed as a collection.

| Error Code | Category | When It Occurs | User Message | Remediation |
|------------|----------|----------------|--------------|-------------|
| `COLLECTION_BAND_MISMATCH` | DATA_INCOMPATIBLE | Homogeneity check | Files have different band counts: '{file1}' has {n1} bands, '{file2}' has {n2} bands | All files must have same band count. Remove incompatible files or submit separately. |
| `COLLECTION_DTYPE_MISMATCH` | DATA_INCOMPATIBLE | Homogeneity check | Files have different data types: '{file1}' is {t1}, '{file2}' is {t2} | Convert all files to same data type before submission. |
| `COLLECTION_CRS_MISMATCH` | DATA_INCOMPATIBLE | Homogeneity check | Files have different coordinate systems: '{file1}' is {crs1}, '{file2}' is {crs2} | Reproject all files to same CRS before submission. |
| `COLLECTION_RESOLUTION_MISMATCH` | DATA_INCOMPATIBLE | Homogeneity check | Resolution varies too much: {res1}m to {res2}m ({diff}% difference, max {tol}%) | Resample files to consistent resolution before submission. |
| `COLLECTION_TYPE_MISMATCH` | DATA_INCOMPATIBLE | Homogeneity check | Collection mixes incompatible raster types: '{file1}' is {type1}, '{file2}' is {type2} | Don't mix RGB imagery with elevation DEMs. Submit as separate collections. |
| `COLLECTION_BOUNDS_DISJOINT` | DATA_INCOMPATIBLE | Homogeneity check | Files have no spatial relationship - bounds do not overlap or adjoin | Ensure files are from same geographic area. Check for CRS issues causing coordinate mismatch. |

### 8.2 Collection Error Response Structure

```json
{
    "success": false,
    "error_code": "COLLECTION_BAND_MISMATCH",
    "error_category": "DATA_INCOMPATIBLE",
    "message": "Collection contains files with different band counts",

    "details": {
        "total_files": 15,
        "compatible_files": 14,
        "incompatible_files": 1,
        "reference_file": {
            "name": "tile_001.tif",
            "band_count": 3,
            "dtype": "uint8",
            "crs": "EPSG:32611",
            "raster_type": "RGB"
        },
        "mismatches": [
            {
                "file": "tile_015.tif",
                "issue": "BAND_COUNT",
                "expected": 3,
                "found": 1,
                "likely_cause": "This appears to be a DEM (single-band elevation) mixed with RGB imagery"
            }
        ]
    },

    "remediation": "Remove 'tile_015.tif' from the collection. It has 1 band (expected 3) and appears to be a DEM rather than RGB imagery. Submit it as a separate single-raster job with raster_type='dem'."
}
```

---

## 9. Debug & Traceback Handling

### 9.1 Debug Mode Configuration

Debug information is controlled by the unified observability flag:

```python
from config import get_config
config = get_config()

# Check if debug mode is enabled
if config.observability.enabled:  # or config.debug_mode (legacy alias)
    # Include debug section in B2B response

# Environment variables (checked in priority order):
# 1. OBSERVABILITY_MODE=true  (preferred)
# 2. METRICS_DEBUG_MODE=true  (legacy)
# 3. DEBUG_MODE=true          (legacy)
```

### 9.2 Debug Info Storage Strategy

| Destination | When | What |
|-------------|------|------|
| **B2B Response** | Only when `config.debug_mode=True` | Full `debug` section |
| **Job Record `error_details`** | ALWAYS | Full debug info (for support tickets) |
| **Application Insights** | ALWAYS | Structured logging with error_id |

This means:
- **Production**: B2B gets clean error, debug stored internally for support
- **Debug mode**: B2B gets full traceback for developer integration testing

### 9.3 Separation of User Message and Debug Info

Error responses contain two distinct parts:

1. **User-facing fields** - Clean, actionable, always present
2. **Debug fields** - Technical details, conditionally included in response but always stored

```json
{
    "success": false,

    // =========================================================================
    // USER-FACING: Clean, actionable information
    // =========================================================================
    "error_code": "RASTER_64BIT_REJECTED",
    "error_category": "DATA_QUALITY",
    "message": "File uses 64-bit float data type which is not accepted",
    "remediation": "Re-export your raster as 32-bit float (float32) or integer. 64-bit precision is unnecessary for geospatial data and wastes storage.",

    "details": {
        "file": "elevation.tif",
        "current_dtype": "float64",
        "recommended_dtype": "float32",
        "size_reduction": "50%"
    },

    // =========================================================================
    // DEBUG: Technical details for support tickets (always included, nested)
    // =========================================================================
    "debug": {
        "error_id": "ERR-20260206-143052-a1b2c3",
        "timestamp": "2026-02-06T14:30:52.123Z",
        "job_id": "abc123def456...",
        "task_id": "task-789...",
        "stage": 1,
        "handler": "validate_raster",

        "exception": {
            "type": "ValueError",
            "message": "64-bit data type float64 has no legitimate use case for this organization",
            "file": "raster_validation.py",
            "line": 754,
            "function": "_check_bit_depth_efficiency"
        },

        "traceback": "Traceback (most recent call last):\n  File \"/app/services/raster_validation.py\", line 358, in validate_raster\n    bit_depth_result = _check_bit_depth_efficiency(src, dtype, strict_mode)\n  File \"/app/services/raster_validation.py\", line 754, in _check_bit_depth_efficiency\n    raise ValueError(\"64-bit data type...\")\nValueError: 64-bit data type float64 has no legitimate use case",

        "context": {
            "blob_name": "elevation.tif",
            "container": "bronze-rasters",
            "file_size_mb": 245.7,
            "band_count": 1,
            "shape": [10000, 10000]
        }
    }
}
```

### 9.2 Debug Field Specification

| Field | Type | Description |
|-------|------|-------------|
| `debug.error_id` | string | Unique error ID for support tickets (format: ERR-{date}-{time}-{random}) |
| `debug.timestamp` | ISO8601 | When the error occurred |
| `debug.job_id` | string | Parent job ID |
| `debug.task_id` | string | Task ID if applicable |
| `debug.stage` | int | Pipeline stage number |
| `debug.handler` | string | Handler function name |
| `debug.exception.type` | string | Python exception class name |
| `debug.exception.message` | string | Exception message |
| `debug.exception.file` | string | Source file where error occurred |
| `debug.exception.line` | int | Line number |
| `debug.exception.function` | string | Function name |
| `debug.traceback` | string | Full Python traceback |
| `debug.context` | object | Additional context (file info, parameters, etc.) |

### 9.3 Error ID Format

```
ERR-{YYYYMMDD}-{HHMMSS}-{random6}

Examples:
  ERR-20260206-143052-a1b2c3
  ERR-20260206-143052-x7y8z9
```

The error_id allows:
- Quick search in Application Insights
- Correlation across logs
- Reference in support tickets

### 9.4 Implementation Helper

```python
def create_error_response_v2(
    error_code: ErrorCode,
    message: str,
    remediation: str,
    details: Optional[Dict] = None,
    exception: Optional[Exception] = None,
    context: Optional[Dict] = None,
    job_id: Optional[str] = None,
    task_id: Optional[str] = None,
    stage: Optional[int] = None,
    handler: Optional[str] = None,
    include_debug_in_response: Optional[bool] = None,  # Override config
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Create enhanced error response with debug information.

    Args:
        error_code: ErrorCode enum value
        message: User-friendly error message
        remediation: How user can fix this
        details: Structured details about the error
        exception: Python exception if available
        context: Additional context (file info, etc.)
        job_id, task_id, stage, handler: Execution context
        include_debug_in_response: Override config.debug_mode

    Returns:
        Tuple of (b2b_response, full_debug_for_storage)
        - b2b_response: Response to return to B2B client (debug conditional)
        - full_debug_for_storage: Always store this in job record error_details
    """
    import traceback
    import uuid
    from datetime import datetime, timezone
    from config import get_config

    config = get_config()

    # Generate error ID
    now = datetime.now(timezone.utc)
    error_id = f"ERR-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # Base response (always returned to B2B)
    response = {
        "success": False,
        "error_code": error_code.value,
        "error_category": get_error_category(error_code).value,
        "error_scope": get_error_scope(error_code).value,  # v0.9 DAG ready
        "message": message,
        "remediation": remediation,
        "retryable": is_retryable(error_code),
        "http_status": get_http_status_code(error_code),
        "error_id": error_id,  # Always include for support reference
    }

    if details:
        response["details"] = details

    # Build full debug section (ALWAYS created, storage conditional)
    debug = {
        "error_id": error_id,
        "timestamp": now.isoformat(),
        "error_code": error_code.value,
        "error_category": get_error_category(error_code).value,
        "message": message,
        "remediation": remediation,
    }

    if job_id:
        debug["job_id"] = job_id
    if task_id:
        debug["task_id"] = task_id
    if stage is not None:
        debug["stage"] = stage
    if handler:
        debug["handler"] = handler
    if details:
        debug["details"] = details

    if exception:
        tb = traceback.extract_tb(exception.__traceback__)
        last_frame = tb[-1] if tb else None

        debug["exception"] = {
            "type": type(exception).__name__,
            "message": str(exception),
        }

        if last_frame:
            debug["exception"]["file"] = last_frame.filename.split("/")[-1]
            debug["exception"]["line"] = last_frame.lineno
            debug["exception"]["function"] = last_frame.name

        debug["traceback"] = "".join(traceback.format_exception(
            type(exception), exception, exception.__traceback__
        ))

    if context:
        debug["context"] = context

    # Determine if debug should be included in B2B response
    should_include_debug = (
        include_debug_in_response
        if include_debug_in_response is not None
        else config.debug_mode  # Uses OBSERVABILITY_MODE env var
    )

    if should_include_debug:
        response["debug"] = debug

    # Return both: B2B response AND full debug for job record storage
    return response, debug


# Usage in handler:
def handle_raster_error(error_code, message, exception, job_id, task_id):
    """Example usage showing storage pattern."""

    b2b_response, full_debug = create_error_response_v2(
        error_code=error_code,
        message=message,
        remediation="...",
        exception=exception,
        job_id=job_id,
        task_id=task_id,
    )

    # ALWAYS store full debug in job record (for support tickets)
    job_repo.update_job(job_id, {
        'error_details': json.dumps(full_debug),  # Full traceback stored
        'status': JobStatus.FAILED
    })

    # Return B2B response (debug included only if config.debug_mode=True)
    return b2b_response
```

---

## 10. Raster Collection Homogeneity

### 10.1 Validation Requirements

Before processing a raster collection, validate that ALL files are compatible:

| Property | Check | Tolerance |
|----------|-------|-----------|
| Band count | Must match exactly | 0 |
| Data type | Must match exactly | 0 |
| CRS | Must match or be compatible | Same EPSG code |
| Resolution | Must be similar | ±20% |
| Raster type | Must be same category | RGB/RGBA/DEM/etc |
| Bounds | Must have spatial relationship | Overlap or adjacency |

### 10.2 Validation Phase

Add new phase to `handler_raster_collection_complete.py`:

```
Current:                           Proposed:
┌─────────────────┐               ┌─────────────────┐
│ Phase 1: DOWNLOAD│               │ Phase 1: DOWNLOAD│
└────────┬────────┘               └────────┬────────┘
         │                                  │
         ▼                                  ▼
┌─────────────────┐               ┌─────────────────┐
│ Phase 2: COG     │               │ Phase 2: VALIDATE│ ← NEW
│ (per-file valid) │               │ (homogeneity)    │
└────────┬────────┘               └────────┬────────┘
         │                                  │
         ▼                                  ▼
┌─────────────────┐               ┌─────────────────┐
│ Phase 3: STAC    │               │ Phase 3: COG     │
└────────┬────────┘               └────────┬────────┘
         │                                  │
         ▼                                  ▼
┌─────────────────┐               ┌─────────────────┐
│ Phase 4: CLEANUP │               │ Phase 4: STAC    │
└─────────────────┘               └────────┬────────┘
                                           │
                                           ▼
                                  ┌─────────────────┐
                                  │ Phase 5: CLEANUP │
                                  └─────────────────┘
```

### 10.3 Homogeneity Check Implementation

```python
def _validate_collection_homogeneity(
    downloaded_files: List[Dict],
    job_id: str,
    task_id: str
) -> Dict[str, Any]:
    """
    Validate all files in collection have compatible properties.

    Returns:
        {
            "valid": True/False,
            "reference_file": "...",  # First file used as baseline
            "properties": {...},       # Reference properties
            "mismatches": [...]        # List of incompatibilities
        }

    Raises:
        Does not raise - returns structured result for clear error messaging
    """
    import rasterio

    if len(downloaded_files) < 2:
        return {"valid": True, "message": "Single file, no homogeneity check needed"}

    mismatches = []
    reference = None

    for idx, file_info in enumerate(downloaded_files):
        local_path = file_info['local_path']
        blob_name = file_info['blob_name']

        with rasterio.open(local_path) as src:
            props = {
                "file": blob_name,
                "band_count": src.count,
                "dtype": str(src.dtypes[0]),
                "crs": str(src.crs) if src.crs else None,
                "resolution": src.res,
                "bounds": src.bounds,
            }

            if idx == 0:
                reference = props
                continue

            # Check band count
            if props["band_count"] != reference["band_count"]:
                mismatches.append({
                    "type": "BAND_COUNT",
                    "file": blob_name,
                    "expected": reference["band_count"],
                    "found": props["band_count"],
                    "reference_file": reference["file"]
                })

            # Check dtype
            if props["dtype"] != reference["dtype"]:
                mismatches.append({
                    "type": "DTYPE",
                    "file": blob_name,
                    "expected": reference["dtype"],
                    "found": props["dtype"],
                    "reference_file": reference["file"]
                })

            # Check CRS
            if props["crs"] != reference["crs"]:
                mismatches.append({
                    "type": "CRS",
                    "file": blob_name,
                    "expected": reference["crs"],
                    "found": props["crs"],
                    "reference_file": reference["file"]
                })

            # Check resolution (±20% tolerance)
            if reference["resolution"] and props["resolution"]:
                ref_res = reference["resolution"][0]
                file_res = props["resolution"][0]
                diff_pct = abs(file_res - ref_res) / ref_res * 100
                if diff_pct > 20:
                    mismatches.append({
                        "type": "RESOLUTION",
                        "file": blob_name,
                        "expected": f"{ref_res:.2f}m",
                        "found": f"{file_res:.2f}m",
                        "difference_percent": round(diff_pct, 1),
                        "reference_file": reference["file"]
                    })

    if mismatches:
        return {
            "valid": False,
            "reference_file": reference["file"],
            "properties": reference,
            "mismatches": mismatches,
            "error_code": f"COLLECTION_{mismatches[0]['type']}_MISMATCH"
        }

    return {
        "valid": True,
        "reference_file": reference["file"],
        "properties": reference,
        "message": f"All {len(downloaded_files)} files are compatible"
    }
```

### 10.4 Error Response for Homogeneity Failure

```json
{
    "success": false,
    "error_code": "COLLECTION_BAND_MISMATCH",
    "error_category": "DATA_INCOMPATIBLE",
    "message": "Collection contains rasters with different band counts",
    "details": {
        "reference_file": "tile_001.tif",
        "reference_properties": {
            "band_count": 3,
            "dtype": "uint8",
            "crs": "EPSG:32611"
        },
        "mismatches": [
            {
                "type": "BAND_COUNT",
                "file": "tile_015.tif",
                "expected": 3,
                "found": 1
            },
            {
                "type": "DTYPE",
                "file": "tile_015.tif",
                "expected": "uint8",
                "found": "float32"
            }
        ],
        "compatible_files": 14,
        "incompatible_files": 1
    },
    "remediation": "File 'tile_015.tif' has 1 band (expected 3) and dtype float32 (expected uint8). This appears to be a DEM mixed with RGB imagery. Remove it from the collection or submit as a separate job."
}
```

---

## 11. Implementation Plan

### Phase 1: Error Category System (Priority: HIGH) ✅ COMPLETE

**Completed**: 06 FEB 2026 (Revised with Pydantic models)

**Files modified**:
- `core/errors.py` - Complete rewrite with Pydantic models

**Deliverables**:
- [x] Add `ErrorCategory` enum (7 categories)
- [x] Add `ErrorScope` enum (NODE, WORKFLOW for v0.9 DAG)
- [x] Add `ErrorResponse` Pydantic model (matches TaskResult pattern)
- [x] Add `ErrorDebug` Pydantic model (for job record storage)
- [x] Add `ExceptionInfo` Pydantic model (nested exception details)
- [x] Add `_ERROR_CATEGORY` mapping dict
- [x] Add `_ERROR_SCOPE` mapping dict
- [x] Add `get_error_category()`, `get_error_scope()`, `is_user_fixable()` functions
- [x] Update `create_error_response()` to return `ErrorResponse` model
- [x] Update `create_error_response_v2()` to return `Tuple[ErrorResponse, ErrorDebug]`
- [x] Add `generate_error_id()` for support ticket correlation

### Phase 2: New Error Codes (Priority: HIGH) ✅ COMPLETE

**Completed**: 06 FEB 2026

**Files modified**:
- `core/errors.py` - Added 21 new error codes

**Deliverables**:
- [x] Add `CRS_MISMATCH` shared error code
- [x] Add 7 raster-specific error codes (RASTER_UNREADABLE, RASTER_64BIT_REJECTED, RASTER_EMPTY, RASTER_NODATA_CONFLICT, RASTER_EXTREME_VALUES, RASTER_BAND_INVALID, RASTER_TYPE_MISMATCH)
- [x] Add 8 vector-specific error codes (VECTOR_UNREADABLE, VECTOR_NO_FEATURES, VECTOR_GEOMETRY_INVALID, VECTOR_GEOMETRY_EMPTY, VECTOR_COORDINATE_ERROR, VECTOR_ENCODING_ERROR, VECTOR_ATTRIBUTE_ERROR, VECTOR_TABLE_NAME_INVALID)
- [x] Add 6 collection error codes with WORKFLOW scope (COLLECTION_BAND_MISMATCH, COLLECTION_DTYPE_MISMATCH, COLLECTION_CRS_MISMATCH, COLLECTION_RESOLUTION_MISMATCH, COLLECTION_TYPE_MISMATCH, COLLECTION_BOUNDS_DISJOINT)
- [x] Update `_ERROR_CLASSIFICATION` mapping (all new codes → PERMANENT)
- [x] Update `_ERROR_CATEGORY` mapping (RASTER/VECTOR → DATA_QUALITY, COLLECTION → DATA_INCOMPATIBLE)
- [x] Update `_ERROR_SCOPE` mapping (COLLECTION_* → WORKFLOW, others → NODE)
- [x] Total error codes: 54 (was 25)

### Phase 3: Collection Homogeneity Validator (Priority: HIGH) ✅ COMPLETE

**Completed**: 06 FEB 2026

**Files modified**:
- `services/handler_raster_collection_complete.py` - Added validation phase

**Deliverables**:
- [x] Implement `_validate_collection_homogeneity()` function (checks band count, dtype, CRS, resolution, raster type)
- [x] Implement `_create_homogeneity_error_response()` using new ErrorResponse Pydantic model
- [x] Add Phase 2 (VALIDATE) between download and COG creation
- [x] Update phase numbers: 1=Download, 2=Validate, 3=COG, 4=STAC, 5=Cleanup
- [x] Emit JobEvents for validation (homogeneity_started, homogeneity_passed, homogeneity_failed)
- [x] Uses COLLECTION_* error codes with WORKFLOW scope
- [x] Clear error response with file-by-file mismatch details
- [x] Configurable resolution tolerance via `resolution_tolerance_percent` parameter (default 20%)
- [x] Include validation results in success response

### Phase 4: Enhanced Raster Validation (Priority: MEDIUM) ✅ COMPLETE

**Completed**: 06 FEB 2026

**Files modified**:
- `services/raster_validation.py` - Added STEP 6b data quality checks

**Deliverables**:
- [x] Add nodata sanity check (RASTER_NODATA_CONFLICT)
- [x] Add value range sanity check (RASTER_EXTREME_VALUES - DEM with 1e38 values)
- [x] Add mostly-empty detection (RASTER_EMPTY - 99%+ nodata)
- [x] Improve error messages with remediation via ErrorResponse model
- [x] New function `_check_data_quality()` performs all three checks
- [x] Configurable thresholds (EMPTY_THRESHOLD=99%, EXTREME_THRESHOLD=1e30)
- [x] Non-critical failures continue with warnings; critical failures return ErrorResponse

### Phase 5: B2B Error Message Cleanup (Priority: MEDIUM) ✅ COMPLETE

**Completed**: 06 FEB 2026

**Files modified**:
- `services/handler_vector_docker_complete.py` - Enhanced error response with ErrorResponse model
- `services/handler_raster_collection_complete.py` - Already using ErrorResponse from Phase 3

**Deliverables**:
- [x] Audit all error returns in key handlers
- [x] Add remediation to all error messages via ErrorResponse model
- [x] Ensure error_category and error_scope are set correctly
- [x] Add error_id generation for support ticket correlation
- [x] Add `_map_exception_to_error_code()` for vector error classification
- [x] Add `_get_vector_remediation()` with user-friendly guidance for each error code
- [x] Return `_debug` in error response for job record storage

### Phase 6: Documentation (Priority: LOW)

**Deliverables**:
- [ ] Error code reference documentation
- [ ] B2B integration guide for error handling
- [ ] Troubleshooting guide by error category

**Estimated effort**: 2-3 hours

---

## 12. Migration Strategy

### 12.1 Backward Compatibility

The enhanced error response is **additive** - new fields don't break existing consumers:

```python
# OLD response (still valid)
{
    "success": False,
    "error": "FILE_NOT_FOUND",
    "message": "..."
}

# NEW response (superset)
{
    "success": False,
    "error": "FILE_NOT_FOUND",
    "error_category": "DATA_MISSING",  # NEW
    "message": "...",
    "remediation": "...",               # NEW
    "details": {...}                    # NEW
}
```

### 12.2 Rollout Strategy

1. **Phase 1**: Add new fields, keep old behavior
2. **Phase 2**: Log when old-style errors are returned (deprecation warning)
3. **Phase 3**: Update all handlers to use new format
4. **Phase 4**: Document for B2B consumers

### 12.3 Testing Strategy

For each new error code:
1. Create test fixture with "garbage" input
2. Submit job and verify error response structure
3. Verify error_category is correct
4. Verify remediation is actionable
5. Verify B2B consumer can parse response

---

## Appendix A: Error Response Schema

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum

class ErrorCategory(str, Enum):
    DATA_MISSING = "DATA_MISSING"
    DATA_QUALITY = "DATA_QUALITY"
    DATA_INCOMPATIBLE = "DATA_INCOMPATIBLE"
    PARAMETER_ERROR = "PARAMETER_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    CONFIGURATION = "CONFIGURATION"

class ErrorResponse(BaseModel):
    """Standardized error response for all API endpoints."""

    success: bool = False

    # Machine-readable classification
    error_code: str = Field(..., description="Specific error code (e.g., FILE_NOT_FOUND)")
    error_category: ErrorCategory = Field(..., description="High-level error category")
    retryable: bool = Field(..., description="Whether automatic retry might succeed")
    http_status: int = Field(..., description="HTTP status code")

    # Human-readable explanation
    message: str = Field(..., description="Human-readable error description")
    remediation: Optional[str] = Field(None, description="How to fix this error")

    # Structured details
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error context")

    # Support reference
    error_id: Optional[str] = Field(None, description="Unique error ID for support tickets")
    documentation_url: Optional[str] = Field(None, description="Link to error documentation")
```

---

## Appendix B: Quick Reference

### Error Category Decision Tree

```
Is the resource missing?
├── YES → DATA_MISSING
└── NO → Is the file content bad?
    ├── YES → DATA_QUALITY
    └── NO → Are collection files incompatible?
        ├── YES → DATA_INCOMPATIBLE
        └── NO → Are request parameters wrong?
            ├── YES → PARAMETER_ERROR
            └── NO → Is this a temporary issue?
                ├── YES → SERVICE_UNAVAILABLE
                └── NO → Is this a config issue?
                    ├── YES → CONFIGURATION
                    └── NO → SYSTEM_ERROR
```

### Who Fixes What

| Category | Fixed By | SLA |
|----------|----------|-----|
| DATA_MISSING | User | Immediate (resubmit) |
| DATA_QUALITY | User | Immediate (fix file) |
| DATA_INCOMPATIBLE | User | Immediate (fix collection) |
| PARAMETER_ERROR | User | Immediate (fix request) |
| SYSTEM_ERROR | Engineering | Next business day |
| SERVICE_UNAVAILABLE | Auto-retry | Minutes |
| CONFIGURATION | Ops | Hours |

---

*Document maintained by: Engineering Team*
*Last updated: 06 FEB 2026*
