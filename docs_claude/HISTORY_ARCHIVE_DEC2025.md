# Project History - Archive (December 2025 Cleanup)

**Last Updated**: 05 DEC 2025
**Purpose**: Archive of completed work moved from TODO.md during documentation cleanup
**See Also**: [HISTORY.md](./HISTORY.md) for the main project history log

This archive contains completed tasks that were cleaned up from TODO.md on 05 DEC 2025.

---

## 05 DEC 2025: JPEG COG Compression Fix ✅

**Status**: ✅ **FIXED**
**Priority**: **HIGH** - Was blocking visualization tier COG creation

### Problem

JPEG compression failed in Azure Functions while DEFLATE worked fine:
- Visualization tier uses JPEG (web-optimized)
- Analysis tier uses DEFLATE (lossless)
- Error: `COG_TRANSLATE_FAILED` after ~6 seconds

### Root Cause

YCbCr color encoding (used for JPEG) requires `INTERLEAVE=PIXEL` but the code was using `INTERLEAVE=BAND`.

### Solution

Fixed INTERLEAVE setting in `config/raster_config.py` for JPEG visualization tier:

```python
# BEFORE (broken)
"INTERLEAVE": "BAND"

# AFTER (fixed)
"INTERLEAVE": "PIXEL"  # Required for YCbCr encoding
```

### Files Modified

| File | Change |
|------|--------|
| `config/raster_config.py` | Fixed INTERLEAVE=PIXEL for visualization tier |

### Verification

Tested with RGB GeoTIFF (7777x5030 pixels, uint8):
- ✅ Visualization tier (JPEG): SUCCESS
- ✅ Analysis tier (DEFLATE): SUCCESS

---

## 28 NOV 2025: JSON Deserialization Error Handling ✅

**Status**: ✅ **COMPLETED**
**Priority**: **HIGH** - Data corruption prevention
**Impact**: Fail-fast on serialization errors, explicit logging

### Solution Implemented

Research found **50+ Pydantic models already exist** covering all boundaries. No new modules needed - just added explicit error handling to existing code:

1. **Service Bus** - Added try/except with dead-letter routing for malformed messages
2. **PostgreSQL** - Created `_parse_jsonb_column()` helper that logs and raises `DatabaseError` instead of silent fallbacks

### Files Modified

| File | Change |
|------|--------|
| `infrastructure/service_bus.py` | Added try/except to `receive_messages()` and `peek_messages()` |
| `infrastructure/postgresql.py` | Added `_parse_jsonb_column()` helper, updated 4 methods to use it |

### Application Insights Queries

```kql
# Find JSON deserialization errors
traces | where customDimensions.error_type == "JSONDecodeError"

# Find corrupted database records
traces | where message contains "Corrupted JSON"
```

---

## 27 NOV 2025: Pre-Flight Resource Validation Architecture ✅

**Status**: ✅ **COMPLETE** - Implemented in `infrastructure/validators.py`
**Impact**: Jobs fail fast with clear errors before wasting compute

### What Was Implemented

Created `infrastructure/validators.py` with resource validators:
- `blob_exists` - Validates blob exists in Azure Storage
- `container_exists` - Validates container exists
- `table_exists` - Validates PostGIS table exists

### Usage Pattern

```python
parameters_schema = {
    'container_name': {
        'type': 'str',
        'required': True,
        'resource_validator': 'container_exists'
    },
    'blob_path': {
        'type': 'str',
        'required': True,
        'resource_validator': 'blob_exists'
    }
}
```

Jobs using this pattern:
- `process_raster_v2` - Validates blob exists before processing
- `process_vector` - Validates source file exists

---

## 26 NOV 2025: Platform Schema Consolidation & DDH Metadata ✅

**Status**: ✅ **COMPLETED**
**Impact**: Simplified configuration, verified DDH → STAC metadata flow

### What Was Done

**1. Platform Schema Consolidation**:
- Removed unused `platform_schema` config field from `config/database_config.py`
- Confirmed `api_requests` table was already in `app` schema (no migration needed)
- Updated documentation in `infrastructure/platform.py` and `core/models/platform.py`
- Fixed `triggers/admin/db_data.py` queries to use correct schema and columns
- Deprecated `orchestration_jobs` endpoints (HTTP 410)

**2. Worker Configuration Optimization**:
- Set `FUNCTIONS_WORKER_PROCESS_COUNT=4` via Azure CLI
- Reduced `maxConcurrentCalls` from 8 to 2 in `host.json`
- Result: 4 workers × 2 calls = 8 concurrent DB connections (was 16)

**3. DDH Metadata Passthrough Verification**:
- Tested `process_raster` job with DDH identifiers (dataset_id, resource_id, version_id, access_level)
- Verified STAC items contain `platform:*` properties with DDH values
- Confirms Platform → CoreMachine → STAC metadata pipeline is operational

**Files Modified**:
- `config/database_config.py`
- `infrastructure/platform.py`
- `core/models/platform.py`
- `triggers/admin/db_data.py`
- `host.json`

---

## 25 NOV 2025: config.py Refactor - God Object Elimination ✅

**Status**: ✅ **COMPLETED**
**Impact**: Modular configuration, easier testing, cleaner imports

### What Was Done

Split monolithic `config.py` (2,000+ lines) into modular configuration:

```
config/
├── __init__.py          # Re-exports for backward compatibility
├── defaults.py          # Environment defaults
├── app_config.py        # Application settings
├── database_config.py   # PostgreSQL configuration
├── queue_config.py      # Service Bus configuration
├── raster_config.py     # COG processing settings
├── storage_config.py    # Azure Blob configuration
└── vector_config.py     # Vector processing settings
```

**Backward Compatibility**: `from config import get_config` still works.

---

## 25 NOV 2025: STAC Metadata Encapsulation ✅

**Status**: ✅ **COMPLETED**
**Impact**: Clean separation between DDH metadata and STAC properties

### What Was Done

Ensured DDH identifiers flow through the entire pipeline:
- Platform layer receives `dataset_id`, `resource_id`, `version_id`, `access_level`
- CoreMachine passes through job parameters
- STAC items store as `platform:dataset_id`, `platform:resource_id`, etc.

### STAC Item Properties

```json
{
  "properties": {
    "platform:dataset_id": "biodiversity_2024",
    "platform:resource_id": "tree_cover",
    "platform:version_id": "v1.0.0",
    "platform:access_level": "internal"
  }
}
```

---

## 25 NOV 2025: pgSTAC search_tohash() Function Failure ✅

**Status**: ✅ **RESOLVED** - Workaround implemented + full-rebuild available

### Problem

`pypgstac migrate` deployment sometimes leaves pgSTAC in broken state where `search_tohash()` function fails.

### Solution

Created `/api/dbadmin/maintenance/full-rebuild?confirm=yes` endpoint that:
1. Atomically drops BOTH app + pgstac schemas
2. Redeploys app schema via PydanticToSQL
3. Redeploys pgstac schema via pypgstac migrate
4. Verifies all functions work

This is now the **recommended post-deployment step**.

---

## 25 NOV 2025: STAC Collection Description Validation Error ✅

**Status**: ✅ **RESOLVED**

### Problem

STAC collections were failing validation due to empty description field.

### Solution

Added default description generation in collection creation:
- Uses collection ID if description not provided
- Validates description is non-empty string

---

## 24 NOV 2025: SQL Generator Invalid Index Bug ✅

**Status**: ✅ **FIXED**
**Fix Location**: `core/schema/sql_generator.py:478-491`

### What Was Fixed

The `generate_indexes_composed()` method was creating an invalid `idx_api_requests_status` index for the `api_requests` table, which does NOT have a `status` column.

**Fix Applied** (sql_generator.py:479-481):
```python
elif table_name == "api_requests":
    # Platform Layer indexes (added 16 NOV 2025, FIXED 24 NOV 2025)
    # NOTE: api_requests does NOT have a status column (removed 22 NOV 2025)
    # Status is delegated to CoreMachine job_id lookup
```

Now only valid indexes are generated:
- `idx_api_requests_dataset_id`
- `idx_api_requests_created_at`

---

## 22 NOV 2025: Managed Identity - User-Assigned Pattern ✅

**Status**: ✅ **COMPLETE**
**Impact**: Passwordless PostgreSQL authentication in production

### What Was Done

Implemented User-Assigned Managed Identity pattern:
- Created `rmhpgflexadmin` identity (ETL operations)
- Created `rmhpgflexreader` identity (read-only API access)
- Configured PostgreSQL roles via `pgaadauth_create_principal()`
- Updated Function App settings for managed identity auth

### Key Configuration

```bash
USE_MANAGED_IDENTITY=true
AZURE_CLIENT_ID=<admin_identity_client_id>
POSTGIS_USER=rmhpgflexadmin
```

**Documentation**: See `DATABASE_IDENTITY_RUNBOOK.md` for operational details.

---

## 19 NOV 2025: STAC API Fixed & Validated ✅

**Status**: ✅ **RESOLVED** - STAC API fully operational with live data

### What Was Fixed

1. Fixed pgSTAC migration deployment order
2. Verified STAC collections and items serving correctly
3. Tested with real raster data (COGs)

### Endpoints Verified

- `GET /api/stac/` - Landing page
- `GET /api/stac/collections` - List collections
- `GET /api/stac/collections/{id}` - Get collection
- `GET /api/stac/collections/{id}/items` - Get items

---

## 25 NOV 2025: ISO3 Country Attribution in STAC Items ✅

**Status**: ✅ **COMPLETED** (as part of STAC Metadata Encapsulation)

### What Was Done

Added ISO3 country code attribution to STAC items:
- Spatial intersection with admin0 boundaries
- Stored as `admin:iso3` property
- Enables filtering by country

---

**Last Updated**: 05 DEC 2025
