# Vector ETL Compliance Review - Complete Summary

**Date**: 10 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Comprehensive compliance review of all vector ETL code

---

## Executive Summary

**Status**: ⚠️ PARTIAL COMPLIANCE - 1 job class needs fixes

### Files Reviewed: 8

| File | Type | Status | Issues |
|------|------|--------|--------|
| `jobs/ingest_vector.py` | Job Class | ❌ NON-COMPLIANT | 3 issues |
| `jobs/stac_catalog_vectors.py` | Job Class | ✅ COMPLIANT | None |
| `services/stac_vector_catalog.py` | Service Handler | ✅ COMPLIANT | None |
| `services/service_stac_vector.py` | Service Class | ✅ COMPLIANT | None |
| `vector/load_vector_task.py` | Legacy Task | ⚠️ DEPRECATED | Old pattern |
| `triggers/ingest_vector.py` | HTTP Trigger | ✅ COMPLIANT | None |
| `triggers/stac_vector.py` | HTTP Trigger | ⚠️ OLD PATTERN | Not using JobManagementTrigger |
| `archive/reference/oldvector.py` | Archive | ✅ ARCHIVED | Ignore |

### Critical Findings

1. **IngestVectorJob** - Missing 2 required methods, wrong aggregate signature
2. **StacCatalogVectorsWorkflow** - Perfect reference implementation (100% compliant)
3. **Service handlers** - Follow correct `dict -> dict` pattern
4. **Triggers** - IngestVectorTrigger is compliant, StacVectorTrigger uses old direct pattern

---

## Part 1: Job Classes (CoreMachine Contract)

### 1.1 IngestVectorJob ❌ NON-COMPLIANT

**File**: `jobs/ingest_vector.py`
**Status**: ❌ 3 ISSUES FOUND

#### Issue 1: Missing `create_job_record()` Method ❌

**Required by**: CoreMachine trigger flow
**Impact**: Cannot create job records in database
**Priority**: HIGH (blocks execution)

**What's Missing**:
```python
@staticmethod
def create_job_record(job_id: str, params: dict) -> dict:
    """Create job record for database storage."""
    # NOT IMPLEMENTED
```

**Required Implementation**: See VECTOR_ETL_COMPLIANCE_ISSUES.md lines 57-91

#### Issue 2: Missing `queue_job()` Method ❌

**Required by**: CoreMachine trigger flow
**Impact**: Cannot queue jobs to Service Bus
**Priority**: HIGH (blocks execution)

**What's Missing**:
```python
@staticmethod
def queue_job(job_id: str, params: dict) -> dict:
    """Queue job for processing using Service Bus."""
    # NOT IMPLEMENTED
```

**Required Implementation**: See VECTOR_ETL_COMPLIANCE_ISSUES.md lines 93-134

#### Issue 3: Wrong Aggregate Method Signature ❌

**Current** (WRONG):
```python
@staticmethod
def aggregate_results(stage: int, task_results: list) -> dict:  # Line 245
    """Aggregate task results for a stage."""
```

**Required** (CORRECT):
```python
@staticmethod
def aggregate_job_results(context) -> Dict[str, Any]:
    """Aggregate results from all completed tasks into job summary."""
```

**Problems**:
1. Method name is `aggregate_results` (should be `aggregate_job_results`)
2. Takes `(stage, task_results)` (should take `context`)
3. CoreMachine calls `aggregate_job_results(context)` - will get AttributeError

**Fix Required**: Delete old method, add new one per VECTOR_ETL_COMPLIANCE_ISSUES.md lines 158-206

#### What IS Compliant ✅

- `validate_job_parameters(params)` - Line 64 ✅
- `generate_job_id(params)` - Line 157 ✅
- `create_tasks_for_stage(stage, job_params, job_id, previous_results)` - Line 169 ✅
- `stages` attribute - Line 35 ✅
- Parameter naming uses `container_name` ✅
- Fan-out pattern correctly implemented ✅

### 1.2 StacCatalogVectorsWorkflow ✅ FULLY COMPLIANT

**File**: `jobs/stac_catalog_vectors.py`
**Status**: ✅ NO ISSUES - PERFECT REFERENCE IMPLEMENTATION

#### All Required Methods Present ✅

| Method | Line | Signature | Status |
|--------|------|-----------|--------|
| `validate_job_parameters(params)` | 49 | ✅ Correct | ✅ |
| `generate_job_id(params)` | 108 | ✅ Correct | ✅ |
| `create_tasks_for_stage(...)` | 120 | ✅ Correct | ✅ |
| `create_job_record(job_id, params)` | 156 | ✅ Correct | ✅ |
| `queue_job(job_id, params)` | 197 | ✅ Correct | ✅ |
| `aggregate_job_results(context)` | 251 | ✅ Correct signature! | ✅ |
| `stages` attribute | 30 | ✅ Present | ✅ |

#### Why This is the Reference Implementation

1. **Complete** - Has ALL 7 required methods
2. **Correct signatures** - Matches CoreMachine contract exactly
3. **Proper naming** - `aggregate_job_results(context)` not `aggregate_results`
4. **Clean code** - Well-documented, follows patterns
5. **Works** - Deployed and tested

**Recommendation**: Use this as template for fixing IngestVectorJob!

---

## Part 2: Service Layer (Handler Pattern)

### 2.1 stac_vector_catalog.py ✅ COMPLIANT

**File**: `services/stac_vector_catalog.py`
**Status**: ✅ FOLLOWS CORRECT HANDLER PATTERN

#### Handler: `extract_vector_stac_metadata(params) -> dict`

**Signature**: ✅ `def handler(params: dict) -> dict`
**Pattern**: ✅ Returns `{"success": True/False, "result": {...}, "error": "..."}`

**Key Features** (Lines 15-197):
- ✅ Lazy imports (StacVectorService imported in function, not module level)
- ✅ Step-by-step logging (STEP 0, 1, 2, 3, 4, 5)
- ✅ Explicit error handling with traceback
- ✅ Idempotency check before PgSTAC insertion
- ✅ Returns comprehensive result dict

**Follows Raster Pattern**: Yes - matches `extract_stac_metadata()` from raster STAC

**Example Usage** (from job):
```python
# Stage 1 task calls this handler
{
    "task_type": "extract_vector_stac_metadata",
    "parameters": {
        "schema": "geo",
        "table_name": "parcels",
        "collection_id": "vectors"
    }
}
```

### 2.2 service_stac_vector.py ✅ COMPLIANT

**File**: `services/service_stac_vector.py`
**Status**: ✅ SERVICE CLASS FOLLOWS PATTERNS

#### Class: `StacVectorService`

**Purpose**: Extract STAC metadata from PostGIS tables
**Pattern**: Service class (not handler function)

**Key Methods**:
- `extract_item_from_table()` - Lines 57-158
  - Queries PostGIS for table metadata
  - Builds STAC Item with postgis:// asset link
  - Returns validated `stac_pydantic.Item`

- `_get_table_metadata()` - Lines 160-282
  - Queries extent, row count, geometry types
  - Uses `psycopg` with `sql.SQL()` composition (SQL injection safe)
  - Returns comprehensive metadata dict

**Comparison to Raster**:
- Raster: `StacMetadataService` uses `rio-stac` + `rasterio`
- Vector: `StacVectorService` uses PostGIS queries + `psycopg`
- Same pattern: Service class with `extract_item_from_*()` method

**Note**: This is called BY the handler (`extract_vector_stac_metadata`), not a handler itself.

### 2.3 load_vector_task.py ⚠️ DEPRECATED PATTERN

**File**: `vector/load_vector_task.py`
**Status**: ⚠️ USES OLD TASK PATTERN (NOT CoreMachine)

#### Old Pattern Detected

```python
class LoadVectorFileTask:
    def execute(self, task_definition: 'TaskDefinition') -> Dict[str, Any]:
        # OLD PATTERN - task classes with execute() method
```

**Problems**:
1. Uses `TaskDefinition` class (old pattern)
2. Has `execute()` method (not handler function pattern)
3. References `create_stage_1_tasks(context)` in comments (deprecated)
4. Not compatible with CoreMachine contract

**Recommendation**:
- ⚠️ Mark as deprecated
- Don't use this pattern for new code
- If needed, rewrite as handler function:
  ```python
  def load_vector_file(params: dict) -> dict:
      """Handler function following current pattern."""
  ```

---

## Part 3: Triggers (HTTP Endpoints)

### 3.1 ingest_vector.py ✅ COMPLIANT

**File**: `triggers/ingest_vector.py`
**Status**: ✅ FOLLOWS JobManagementTrigger PATTERN

#### Class: `IngestVectorTrigger(JobManagementTrigger)`

**Inheritance**: ✅ Inherits from `JobManagementTrigger` base class
**Pattern**: ✅ Template Method pattern with explicit job registry

**Key Implementation** (Lines 84-213):

```python
class IngestVectorTrigger(JobManagementTrigger):
    def __init__(self):
        super().__init__("ingest_vector")  # Job type passed to base

    def get_allowed_methods(self) -> List[str]:
        return ["POST"]  # Only POST allowed

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        # Extract parameters
        # Get job class from registry (explicit, not magic)
        # Validate parameters
        # Generate job ID
        # Check idempotency
        # Create job record + queue job
        # Return response
```

**Follows Pattern**: ✅ Matches raster trigger pattern
**Idempotency**: ✅ Checks for existing jobs before creating
**Error Handling**: ✅ Clear validation messages
**Registry Usage**: ✅ Explicit `from jobs import ALL_JOBS`

**Critical Feature - Idempotency Check** (Lines 159-189):
```python
existing_job = repos['job_repo'].get_job(job_id)

if existing_job:
    if existing_job.status.value == 'completed':
        return {"status": "already_completed", "idempotent": True, ...}
    else:
        return {"status": existing_job.status.value, "idempotent": True, ...}
```

### 3.2 stac_vector.py ⚠️ OLD DIRECT PATTERN

**File**: `triggers/stac_vector.py`
**Status**: ⚠️ NOT USING JobManagementTrigger BASE CLASS

#### Direct Function Pattern (Old)

```python
def handle_request(req: func.HttpRequest) -> func.HttpResponse:
    """Direct HTTP handler - doesn't use job system."""
    # Directly calls StacVectorService
    # Directly inserts to PgSTAC
    # Returns HTTP response immediately
```

**Problems**:
1. ❌ NOT using `JobManagementTrigger` base class
2. ❌ NOT creating job records
3. ❌ NOT queuing to Service Bus
4. ❌ NOT going through CoreMachine
5. ❌ Synchronous execution (blocks HTTP request)

**Why This Exists**:
- Quick ad-hoc STAC cataloging endpoint
- Direct execution without job tracking
- Used for testing/debugging

**Recommendation**:
- ⚠️ Keep for ad-hoc usage BUT document as non-job endpoint
- If production workflow needed, create `StacCatalogVectorTrigger(JobManagementTrigger)` instead
- Already have job class (`StacCatalogVectorsWorkflow`) - just need proper trigger

**Note**: The job class `StacCatalogVectorsWorkflow` exists and is compliant. This trigger is just a legacy direct endpoint.

---

## Part 4: Comparison to Raster ETL Success

### Pattern Compliance Matrix

| Pattern Element | Raster ETL | IngestVectorJob | StacCatalogVectorsWorkflow |
|----------------|------------|-----------------|---------------------------|
| `validate_job_parameters(params)` | ✅ | ✅ | ✅ |
| `generate_job_id(params)` | ✅ | ✅ | ✅ |
| `create_tasks_for_stage(...)` | ✅ | ✅ | ✅ |
| `create_job_record(job_id, params)` | ✅ | ❌ **MISSING** | ✅ |
| `queue_job(job_id, params)` | ✅ | ❌ **MISSING** | ✅ |
| `aggregate_job_results(context)` | ✅ | ❌ **WRONG** | ✅ |
| `stages` attribute | ✅ | ✅ | ✅ |
| Parameter naming (`container_name`) | ✅ | ✅ | ✅ |
| No fallback logic | ✅ | ✅ | ✅ |

### Service Handler Compliance

| Pattern Element | Raster | Vector |
|----------------|--------|--------|
| Handler signature `(params: dict) -> dict` | ✅ | ✅ |
| Returns `{"success": True/False, "result": {...}}` | ✅ | ✅ |
| Lazy imports of heavy dependencies | ✅ | ✅ |
| Step-by-step logging | ✅ | ✅ |
| Explicit error handling with traceback | ✅ | ✅ |
| Idempotency checks | ✅ | ✅ |

**Conclusion**: Service layer is 100% compliant with raster patterns!

---

## Part 5: Priority Fix List

### High Priority (Blocks Execution)

1. **IngestVectorJob.create_job_record()** - Add method
   - **Impact**: Cannot create jobs without this
   - **Effort**: Copy from StacCatalogVectorsWorkflow (lines 156-194)
   - **Change**: Update `job_type="ingest_vector"`, `total_stages=2`

2. **IngestVectorJob.queue_job()** - Add method
   - **Impact**: Cannot queue jobs without this
   - **Effort**: Copy from StacCatalogVectorsWorkflow (lines 197-248)
   - **Change**: Update `job_type="ingest_vector"`

3. **IngestVectorJob.aggregate_results()** - Fix signature
   - **Impact**: CoreMachine calls wrong method name
   - **Effort**: Delete old method, add new with correct signature
   - **Reference**: ProcessRasterWorkflow.aggregate_job_results (jobs/process_raster.py:431)

### Medium Priority (Cleanup)

4. **vector/load_vector_task.py** - Mark as deprecated
   - **Impact**: Confusion about which pattern to use
   - **Action**: Add deprecation notice at top of file
   - **Note**: Don't delete (might be referenced), just document as old

5. **triggers/stac_vector.py** - Document as non-job endpoint
   - **Impact**: Confusion about job vs direct endpoints
   - **Action**: Add comment explaining this is direct (non-job) endpoint
   - **Note**: Keep for ad-hoc usage, but clarify it's not part of job system

### Low Priority (Enhancement)

6. **StacCatalogVectorTrigger** - Create proper job trigger
   - **Impact**: Currently no job-based trigger for vector STAC cataloging
   - **Action**: Create `StacCatalogVectorTrigger(JobManagementTrigger)`
   - **Note**: Job class exists, just need trigger wrapper
   - **Reference**: Copy pattern from `IngestVectorTrigger`

---

## Part 6: Testing Strategy

### Phase 1: Local Import Tests

```bash
# Test IngestVectorJob compliance (after fixes)
python3 -c "
from jobs.ingest_vector import IngestVectorJob

# Test all required methods exist
required_methods = [
    'validate_job_parameters',
    'generate_job_id',
    'create_tasks_for_stage',
    'create_job_record',      # Currently missing
    'queue_job',              # Currently missing
    'aggregate_job_results'   # Wrong signature
]

for method in required_methods:
    assert hasattr(IngestVectorJob, method), f'Missing method: {method}'
    print(f'✅ {method}')

# Verify old method removed
assert not hasattr(IngestVectorJob, 'aggregate_results'), 'Old aggregate_results still exists!'
print('✅ Old aggregate_results method removed')

print('\\n✅ IngestVectorJob COMPLIANCE VERIFIED')
"

# Test StacCatalogVectorsWorkflow (should already pass)
python3 -c "
from jobs.stac_catalog_vectors import StacCatalogVectorsWorkflow

required_methods = [
    'validate_job_parameters',
    'generate_job_id',
    'create_tasks_for_stage',
    'create_job_record',
    'queue_job',
    'aggregate_job_results'
]

for method in required_methods:
    assert hasattr(StacCatalogVectorsWorkflow, method), f'Missing method: {method}'
    print(f'✅ {method}')

print('\\n✅ StacCatalogVectorsWorkflow ALREADY COMPLIANT')
"
```

### Phase 2: Job Registration Test

```python
# Test both jobs are registered
python3 -c "
from jobs import ALL_JOBS

assert 'ingest_vector' in ALL_JOBS, 'ingest_vector not registered'
assert 'stac_catalog_vectors' in ALL_JOBS, 'stac_catalog_vectors not registered'

print(f'✅ Registered jobs: {len(ALL_JOBS)}')
print(f'✅ Vector jobs: ingest_vector, stac_catalog_vectors')
"
```

### Phase 3: Deployment Tests

```bash
# After deployment, test job submission

# 1. IngestVectorJob
curl -X POST https://rmhgeoapibeta-.../api/jobs/submit/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "test.csv",
    "file_extension": "csv",
    "table_name": "test_vector",
    "converter_params": {"lat_name": "lat", "lon_name": "lon"}
  }'

# Expected: {"job_id": "...", "status": "created", ...}

# 2. StacCatalogVectorsWorkflow
curl -X POST https://rmhgeoapibeta-.../api/jobs/submit/stac_catalog_vectors \
  -H "Content-Type: application/json" \
  -d '{
    "schema": "geo",
    "table_name": "test_vector"
  }'

# Expected: {"job_id": "...", "status": "created", ...}
```

---

## Part 7: Success Criteria

### IngestVectorJob Compliance Checklist

- [ ] `create_job_record()` method added
- [ ] `queue_job()` method added
- [ ] `aggregate_results()` method removed
- [ ] `aggregate_job_results(context)` method added with correct signature
- [ ] Local import test passes
- [ ] Job registration test passes
- [ ] Can submit job via API
- [ ] Job creates database record
- [ ] Job queues to Service Bus
- [ ] CoreMachine can process job without AttributeError

### Vector ETL Overall Compliance

- [ ] All job classes CoreMachine compliant
- [ ] All service handlers follow `dict -> dict` pattern
- [ ] All triggers inherit from `JobManagementTrigger` (except documented direct endpoints)
- [ ] Old patterns documented as deprecated
- [ ] Local tests passing
- [ ] Deployment tests passing

---

## Part 8: Files to Modify

### Must Fix (High Priority)

1. **jobs/ingest_vector.py**
   - Add `create_job_record()` method (after line 166)
   - Add `queue_job()` method (after `create_job_record`)
   - Delete `aggregate_results()` method (lines 245-282)
   - Add `aggregate_job_results(context)` method (replace old one)

### Should Document (Medium Priority)

2. **vector/load_vector_task.py**
   - Add deprecation notice at top
   - Note: Use handler function pattern instead

3. **triggers/stac_vector.py**
   - Add comment: "Direct endpoint (non-job), for ad-hoc STAC cataloging"
   - Note: See `stac_catalog_vectors` job for job-based workflow

---

## Part 9: Reference Implementations

### Perfect Reference: StacCatalogVectorsWorkflow

**Use this as template for ALL vector job fixes:**

```python
# Copy these methods from jobs/stac_catalog_vectors.py
# Only change job_type and metadata

create_job_record()     # Lines 156-194
queue_job()             # Lines 197-248
aggregate_job_results() # Lines 251-294
```

### Handler Pattern Reference: extract_vector_stac_metadata

**Use this as template for new vector handlers:**

```python
# Pattern from services/stac_vector_catalog.py

def handler_name(params: dict) -> dict[str, Any]:
    """Handler docstring."""

    # STEP 0: Lazy imports
    from util_logger import LoggerFactory, ComponentType
    logger = LoggerFactory.create_logger(...)

    # STEP 1: Extract parameters
    param1 = params.get("param1")
    if not param1:
        return {"success": False, "error": "Missing param1"}

    # STEP 2-N: Execute work with logging
    logger.info("STEP 2: Doing work...")
    result = do_work()

    # Success
    return {
        "success": True,
        "result": {
            "data": result,
            ...
        }
    }
```

---

## Conclusion

### Summary Stats

**Files Reviewed**: 8
**Compliance Issues**: 3 (all in IngestVectorJob)
**Critical Blocks**: 3 (all high priority)
**Reference Implementation**: StacCatalogVectorsWorkflow (perfect)

### Work Required

**Estimated Time**: 30-45 minutes
- Add 2 methods (copy from reference): 15 min
- Fix aggregate method: 15 min
- Test locally: 10 min
- Commit and document: 5 min

### Confidence Level

**HIGH** - All fixes are straightforward copies from working reference implementation (StacCatalogVectorsWorkflow). No new patterns to learn, just apply existing proven patterns.

---

**End of Comprehensive Compliance Review**
