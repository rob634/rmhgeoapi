# Vector Ingestion QA Hardening - Implementation Plan

**Date**: 12 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: 📋 **READY FOR IMPLEMENTATION**
**Estimated Time**: 2-3 hours total

---

## 🎯 Objectives

Harden the vector ingestion workflow for **QA environment readiness** where multiple developers will be working with the codebase. Focus on:

1. **Defensive Programming** - Graceful degradation when infrastructure fails
2. **Failure Diagnostics** - Detailed error context for debugging
3. **Data Integrity** - Prevent silent partial loads
4. **Developer Experience** - Clear error messages and actionable guidance

---

## 📊 Implementation Priority

| Priority | Task | Time | Files Changed | Risk |
|----------|------|------|---------------|------|
| **P0** | Exception Handling - Stage 2 Uploads | 45 min | 1 file | Low |
| **P0** | Failed Chunk Detail in Job Summary | 30 min | 1 file | Low |
| **P0** | Table Existence Check Error Handling | 30 min | 1 file | Low |
| **P1** | Unsupported Geometry Type Validation | 20 min | 1 file | Low |
| **P1** | Testing & Validation | 30 min | N/A | N/A |

**Total Estimated Time**: 2 hours 35 minutes

---

## 🔧 Priority 0: Critical Fixes (Must Complete)

### Task 1: Exception Handling - Stage 2 Upload Tasks

**Problem**: Stage 2 upload task has no exception handling. If PostgreSQL insert fails, CoreMachine receives unhandled exception with no diagnostic context.

**Impact**:
- Job summary shows generic failure ("1 task failed")
- No information about which chunk failed or why
- Developers waste time debugging with Application Insights queries

**File**: `services/vector/tasks.py` (lines 295-353)

**Current Code** (line 337):
```python
# 2. Insert data into PostGIS (table already created in Stage 1)
from .postgis_handler import VectorToPostGISHandler
handler = VectorToPostGISHandler()
handler.insert_features_only(chunk, table_name, schema)  # NO EXCEPTION HANDLING

return {
    "success": True,
    "result": {...}
}
```

**Proposed Fix**:
```python
# 2. Insert data into PostGIS (table already created in Stage 1)
from .postgis_handler import VectorToPostGISHandler
import psycopg
import traceback

handler = VectorToPostGISHandler()

try:
    handler.insert_features_only(chunk, table_name, schema)

except psycopg.OperationalError as e:
    # Database connectivity or timeout issues
    error_msg = f"PostgreSQL connection error uploading chunk {chunk_index}: {e}"
    logger.error(error_msg)
    return {
        "success": False,
        "error": error_msg,
        "error_type": "PostgreSQLConnectionError",
        "chunk_index": chunk_index,
        "chunk_path": chunk_path,
        "table": f"{schema}.{table_name}",
        "retryable": True  # Connection issues are often transient
    }

except psycopg.DataError as e:
    # Data validation errors (bad geometry, constraint violations)
    error_msg = f"Data validation error in chunk {chunk_index}: {e}"
    logger.error(f"{error_msg}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": error_msg,
        "error_type": "DataValidationError",
        "chunk_index": chunk_index,
        "chunk_path": chunk_path,
        "table": f"{schema}.{table_name}",
        "retryable": False  # Data errors require investigation
    }

except Exception as e:
    # Unexpected errors
    error_msg = f"Unexpected error uploading chunk {chunk_index}: {e}"
    logger.error(f"{error_msg}\n{traceback.format_exc()}")
    return {
        "success": False,
        "error": error_msg,
        "error_type": type(e).__name__,
        "chunk_index": chunk_index,
        "chunk_path": chunk_path,
        "table": f"{schema}.{table_name}",
        "traceback": traceback.format_exc(),
        "retryable": False  # Unknown errors require investigation
    }

# SUCCESS PATH
return {
    "success": True,
    "result": {
        'rows_uploaded': len(chunk),
        'chunk_path': chunk_path,
        'chunk_index': chunk_index,
        'table': f"{schema}.{table_name}",
        'pickle_retained': True
    }
}
```

**Testing**:
1. Test normal upload (success path)
2. Test with invalid table name (DataError)
3. Test with database unavailable (OperationalError)
4. Verify error details appear in job summary

---

### Task 2: Failed Chunk Detail in Job Summary

**Problem**: Job summary shows count of failed chunks but no detail about which chunks or why they failed.

**Impact**:
- Partial data loads (18 of 20 chunks succeeded)
- No way to identify which data is missing
- Can't retry specific chunks - must rerun entire job

**File**: `jobs/ingest_vector.py` (lines 621-681)

**Current Code** (line 622):
```python
# Aggregate Stage 2 upload results
successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
failed_chunks = len(stage_2_tasks) - successful_chunks
# NO DETAIL ABOUT WHICH CHUNKS OR WHY
```

**Proposed Fix**:
```python
# Aggregate Stage 2 upload results
successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
failed_chunks = len(stage_2_tasks) - successful_chunks

# Extract failed chunk details for debugging
failed_chunks_detail = None
if failed_chunks > 0:
    failed_chunks_detail = []
    for task in stage_2_tasks:
        if task.status == TaskStatus.FAILED:
            result_data = task.result_data or {}

            # Extract error details from task result
            error_info = {
                'chunk_index': result_data.get('chunk_index'),
                'chunk_path': result_data.get('chunk_path'),
                'error': result_data.get('error', 'Unknown error'),
                'error_type': result_data.get('error_type', 'Unknown'),
                'retryable': result_data.get('retryable', False),
                'task_id': task.task_id
            }
            failed_chunks_detail.append(error_info)

    # Log warning about partial data load
    logger.warning(
        f"⚠️ PARTIAL DATA LOAD: {failed_chunks}/{len(stage_2_tasks)} chunks failed for {table_name}. "
        f"Table may have incomplete data. Failed chunks: {[c['chunk_index'] for c in failed_chunks_detail]}"
    )
```

**Add to Return Dict** (line 664):
```python
"summary": {
    "total_chunks": total_chunks,
    "chunks_uploaded": successful_chunks,
    "chunks_failed": failed_chunks,
    "total_rows_uploaded": total_rows_uploaded,
    "success_rate": f"{(successful_chunks / len(stage_2_tasks) * 100):.1f}%" if stage_2_tasks else "0%",
    "stage_1_metadata": chunk_metadata,
    # NEW: Failed chunk diagnostics
    "failed_chunks_detail": failed_chunks_detail,
    "data_complete": failed_chunks == 0  # Explicit flag for data integrity
}
```

**Testing**:
1. Submit job with valid data → Verify `data_complete: true`
2. Inject failure in chunk 5 → Verify failed_chunks_detail includes chunk 5 with error message
3. Verify warning log appears with chunk indices

---

### Task 3: Table Existence Check Error Handling

**Problem**: If `check_table_exists()` fails (DB connection issue, permissions), validation fails with cryptic database error instead of clear message.

**Impact**:
- Developers see `psycopg.OperationalError` during job submission
- Not clear if table exists or if check failed
- Job rejected when it could have proceeded (table creation would fail gracefully in Stage 2)

**File**: `jobs/ingest_vector.py` (lines 305-318)

**Current Code**:
```python
# NEW: Phase 2A (9 NOV 2025) - Check if table already exists
from infrastructure.postgis import check_table_exists

schema = validated["schema"]
table_name = validated["table_name"]

if check_table_exists(schema, table_name):
    raise ValueError(
        f"Table {schema}.{table_name} already exists. "
        f"To replace it, manually drop the table first:\n"
        f"  DROP TABLE {schema}.{table_name} CASCADE;\n"
        f"Or choose a different table_name."
    )
# NO EXCEPTION HANDLING FOR CHECK FAILURE
```

**Proposed Fix**:
```python
# NEW: Phase 2A (9 NOV 2025) - Check if table already exists
from infrastructure.postgis import check_table_exists
import psycopg

schema = validated["schema"]
table_name = validated["table_name"]

try:
    table_exists = check_table_exists(schema, table_name)

    if table_exists:
        raise ValueError(
            f"Table {schema}.{table_name} already exists. "
            f"To replace it, drop the table first:\n"
            f"  DROP TABLE {schema}.{table_name} CASCADE;\n"
            f"Or choose a different table_name."
        )

except ValueError:
    # Re-raise table exists error (expected case)
    raise

except psycopg.OperationalError as e:
    # Database connection issue - log warning but allow job to proceed
    # If table truly exists, Stage 2 will fail gracefully with clear error
    logger.warning(
        f"⚠️ Could not verify table existence for {schema}.{table_name}: {e}. "
        f"Job will proceed - if table exists, Stage 2 will fail with clear error."
    )
    # Don't raise - allow job to be submitted

except Exception as e:
    # Unexpected error during validation
    logger.error(f"Unexpected error checking table existence: {e}")
    raise ValueError(
        f"Unable to validate table name '{table_name}'. "
        f"Check database connectivity. Error: {type(e).__name__}: {e}"
    )
```

**Testing**:
1. Test with existing table → Verify clear "table exists" message
2. Test with DB unavailable → Verify warning logged, job still accepted
3. Test with valid new table → Verify job proceeds normally

---

## 🟡 Priority 1: Important Enhancements

### Task 4: Unsupported Geometry Type Validation

**Problem**: PostGIS supports limited geometry types. Files with GEOMETRYCOLLECTION or other complex types fail at Stage 2 with cryptic error: `"type GEOMETRYCOLLECTION does not exist"`.

**Impact**:
- Wasted processing (file loaded, validated, chunked, pickled before failure)
- Cryptic error message doesn't explain problem
- User doesn't know how to fix the file

**File**: `services/vector/postgis_handler.py` (after line 203 in `prepare_gdf()`)

**Proposed Fix** (add after Multi* normalization):
```python
# After Multi* geometry normalization (line 203)
# Log after normalization
type_counts_after = gdf.geometry.geom_type.value_counts().to_dict()
logger.info(f"Geometry types after normalization: {type_counts_after}")

# ========================================================================
# VALIDATE POSTGIS GEOMETRY TYPE SUPPORT (12 NOV 2025)
# ========================================================================
# PostGIS CREATE TABLE only supports specific geometry types.
# GEOMETRYCOLLECTION and other complex types must be filtered out.
# This validation prevents wasted processing and provides clear user guidance.
# ========================================================================
SUPPORTED_GEOM_TYPES = {
    'MultiPoint', 'MultiLineString', 'MultiPolygon',
    'Point', 'LineString', 'Polygon'  # Should be rare after normalization
}

unique_types = set(gdf.geometry.geom_type.unique())
unsupported = unique_types - SUPPORTED_GEOM_TYPES

if unsupported:
    error_msg = (
        f"❌ Unsupported geometry types detected: {', '.join(unsupported)}\n"
        f"   PostGIS CREATE TABLE supports: {', '.join(sorted(SUPPORTED_GEOM_TYPES))}\n"
        f"   \n"
        f"   Common causes:\n"
        f"   - GeometryCollection in source file (mixed geometry types)\n"
        f"   - Complex KML with multiple geometry types per feature\n"
        f"   - GeoJSON FeatureCollection with mixed types\n"
        f"   \n"
        f"   Solutions:\n"
        f"   1. Explode GeometryCollections to single-type features in QGIS/ArcGIS\n"
        f"   2. Filter source data to single geometry type (polygons only, lines only, etc.)\n"
        f"   3. Split source file into multiple files by geometry type\n"
        f"   \n"
        f"   Affected features: {sum(gdf.geometry.geom_type.isin(unsupported))} of {len(gdf)}"
    )
    logger.error(error_msg)
    raise ValueError(error_msg)

logger.info(f"✅ All geometry types supported by PostGIS: {unique_types}")
```

**Testing**:
1. Test with all MultiPolygon → Success
2. Test with file containing GeometryCollection → Clear error with guidance
3. Verify error appears during validation (Stage 1), not upload (Stage 2)

---

## 🧪 Testing Plan (Priority 1)

### Test Suite 1: Exception Handling

**Test 1.1: Normal Upload Success**
```bash
# Submit job with valid GeoJSON
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test_valid.geojson",
    "file_extension": "geojson",
    "table_name": "test_success"
  }'

# Expected: Job completes, data_complete: true, no failed chunks
```

**Test 1.2: Database Connection Failure** (Simulated)
```python
# Temporarily break PostgreSQL connection string in config
# Submit job → Expect Stage 2 tasks to fail with "PostgreSQLConnectionError"
# Verify failed_chunks_detail includes error_type and retryable: true
```

**Test 1.3: Data Validation Error** (Real Test)
```bash
# Create GeoJSON with invalid geometry (self-intersecting polygon)
# Submit job → Expect Stage 2 to fail with "DataValidationError"
# Verify failed_chunks_detail includes error message
```

### Test Suite 2: Failed Chunk Diagnostics

**Test 2.1: Partial Upload (18 of 20 chunks succeed)**
```python
# Inject failure in chunk indices 5 and 17 (modify handler temporarily)
# Verify job summary includes:
# - failed_chunks: 2
# - failed_chunks_detail: [{chunk_index: 5, error: ...}, {chunk_index: 17, error: ...}]
# - data_complete: false
# - Warning log: "PARTIAL DATA LOAD: 2/20 chunks failed"
```

**Test 2.2: Complete Upload Success**
```bash
# Normal job → Verify:
# - failed_chunks: 0
# - failed_chunks_detail: null
# - data_complete: true
```

### Test Suite 3: Table Existence Check

**Test 3.1: Table Already Exists**
```bash
# Create table manually
psql -h rmhpgflex.postgres.database.azure.com -U {db_superuser} -d geopgflex -c \
  "CREATE TABLE geo.test_exists (id SERIAL PRIMARY KEY);"

# Submit job with table_name: "test_exists"
# Expected: Validation error with clear "table exists" message
```

**Test 3.2: Database Unavailable During Validation**
```python
# Temporarily break connection string
# Submit job → Expect warning log but job accepted
# Verify job fails gracefully at Stage 2 with connection error
```

### Test Suite 4: Geometry Type Validation

**Test 4.1: Unsupported GeometryCollection**
```python
# Create GeoJSON with GeometryCollection features
# Submit job → Expect validation error with guidance
# Verify error message includes:
# - "Unsupported geometry types: GeometryCollection"
# - Solutions list (explode in QGIS, filter to single type)
# - Affected feature count
```

**Test 4.2: Mixed Geometry Types**
```python
# Create GeoJSON with Points AND Polygons (before normalization)
# Submit job → Should succeed (normalization converts to MultiPoint and MultiPolygon)
# Verify table has uniform Multi* types
```

---

## 📂 Files Modified Summary

| File | Lines Changed | Type of Change |
|------|---------------|----------------|
| `services/vector/tasks.py` | ~40 lines | Exception handling added |
| `jobs/ingest_vector.py` | ~30 lines | Failed chunk diagnostics + table check error handling |
| `services/vector/postgis_handler.py` | ~30 lines | Geometry type validation |
| **Total** | **~100 lines** | **Defensive programming** |

---

## 🚀 Deployment Plan

### Step 1: Implementation (2 hours)
1. Task 1: Exception handling in `upload_pickled_chunk` (45 min)
2. Task 2: Failed chunk detail in `finalize_job` (30 min)
3. Task 3: Table existence check error handling (30 min)
4. Task 4: Geometry type validation (20 min)

### Step 2: Testing (30 minutes)
- Run all 4 test suites
- Verify Application Insights logs
- Check job summaries for detail

### Step 3: Git Commit (5 minutes)
```bash
git add services/vector/tasks.py jobs/ingest_vector.py services/vector/postgis_handler.py
git commit -m "Harden vector ingestion for QA environment

🔧 Exception Handling:
- Add PostgreSQL error handling to Stage 2 uploads
- Catch connection errors, data errors, and unexpected exceptions
- Return detailed error context for debugging

📊 Failure Diagnostics:
- Add failed_chunks_detail to job summary
- Include chunk index, error message, error type, retryable flag
- Add data_complete flag for data integrity checking
- Log warnings for partial data loads

🛡️ Defensive Programming:
- Wrap table existence check with exception handling
- Allow jobs to proceed if DB connectivity check fails
- Add geometry type validation (detect unsupported types early)
- Provide clear user guidance for unsupported geometry types

🧪 Testing:
- Validated exception paths with simulated failures
- Verified failed chunk diagnostics with partial uploads
- Tested table existence check with DB unavailable
- Confirmed geometry type validation catches GeometryCollection

🎯 QA Readiness:
- Graceful degradation when infrastructure fails
- Detailed error context for multi-developer debugging
- Data integrity protection (partial load detection)
- Clear user-facing error messages with actionable guidance

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Step 4: Deployment (10 minutes)
```bash
# Push to dev branch
git push origin dev

# Deploy to Azure Functions
func azure functionapp publish rmhgeoapibeta --python --build remote

# Verify deployment
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/health
```

### Step 5: Post-Deployment Validation (15 minutes)
```bash
# Test 1: Submit valid job
curl -X POST https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "test.geojson", "file_extension": "geojson", "table_name": "qa_validation_test"}'

# Test 2: Check job status
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}

# Test 3: Verify OGC Features URL works
curl https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/features/collections/qa_validation_test/items?limit=5

# Test 4: Query Application Insights for error logs (verify exception handling works)
# See docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md
```

---

## 📈 Success Criteria

### Functional Requirements
- ✅ All vector ingestion jobs complete successfully with valid data
- ✅ Failed uploads return detailed error context
- ✅ Partial data loads are detected and logged
- ✅ Unsupported geometry types rejected with clear guidance
- ✅ Database connectivity issues handled gracefully

### Developer Experience
- ✅ Error messages are actionable (explain what to do)
- ✅ Failed chunk diagnostics identify exactly what failed
- ✅ Logs provide sufficient context for debugging
- ✅ No cryptic psycopg errors exposed to users

### Data Integrity
- ✅ `data_complete` flag indicates 100% upload success
- ✅ Partial loads clearly marked in job summary
- ✅ Warning logs for any incomplete data
- ✅ Failed chunk details allow targeted retry (future enhancement)

---

## 🔍 Monitoring & Observability

### Key Metrics to Track

**After Deployment, Monitor**:
1. **Job Success Rate**: Should remain ≥95% for valid data
2. **Failed Chunk Frequency**: Should be <1% of total chunks
3. **Error Type Distribution**: Track most common error_type values
4. **Partial Load Incidents**: Any job with `data_complete: false` requires investigation

### Application Insights Queries

**Query 1: Failed Upload Tasks**
```kql
traces
| where timestamp >= ago(24h)
| where message contains "PostgreSQL" and message contains "error"
| where severityLevel >= 3
| project timestamp, message, customDimensions
| order by timestamp desc
```

**Query 2: Partial Data Loads**
```kql
traces
| where timestamp >= ago(24h)
| where message contains "PARTIAL DATA LOAD"
| project timestamp, message
| order by timestamp desc
```

**Query 3: Geometry Type Validation Failures**
```kql
traces
| where timestamp >= ago(24h)
| where message contains "Unsupported geometry types"
| project timestamp, message
| order by timestamp desc
```

---

## 📚 Related Documentation

- **Vector Ingestion Workflow**: `VECTOR_INGEST_QA_HARDENING_PLAN.md` (this file)
- **Vector ETL Architecture**: `docs_claude/VECTOR_ETL_IMPLEMENTATION_PLAN.md`
- **OGC Features API**: `ogc_features/README.md`
- **Application Insights Queries**: `docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md`
- **Testing Guide**: `docs_claude/DEPLOYMENT_GUIDE.md`

---

## ✅ Ready for Implementation

All tasks are well-defined with:
- Clear problem statements
- Specific code changes
- Testing procedures
- Success criteria

**Next Step**: Begin implementation starting with Priority 0, Task 1.

**Questions or Concerns**: Review this plan and provide feedback before starting implementation.
