# Vector Workflow Gap Analysis - End-to-End Platform Orchestration

**Date**: 30 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Identify gaps in Platform layer for complete vector workflow

---

## 🎯 Desired End-to-End Vector Workflow

```
User uploads vector file (GeoJSON/Shapefile/etc.)
    ↓
POST /api/platform/submit
    ↓
Platform creates 2 CoreMachine jobs:
    1. ingest_vector (PostGIS import)
    2. stac_catalog_vectors (STAC metadata creation)
    ↓
Platform returns response with:
    - PostGIS table name
    - STAC Collection ID
    - OGC Features API URL
    - STAC API URLs
    ↓
User can immediately:
    - Query via OGC Features API
    - Search via STAC API
    - View on web map: https://rmhazuregeo.z13.web.core.windows.net/
```

---

## ✅ What Already Works

### 1. Platform Trigger Infrastructure ✅
**File**: [triggers/trigger_platform.py](triggers/trigger_platform.py)

**Working**:
- ✅ HTTP endpoint: `POST /api/platform/submit`
- ✅ Request validation via Pydantic models
- ✅ Deterministic request ID generation
- ✅ Platform database record creation
- ✅ Status tracking (PENDING → PROCESSING → COMPLETED/FAILED)

### 2. Platform Orchestrator ✅
**File**: [triggers/trigger_platform.py](triggers/trigger_platform.py#L223-L375)

**Working**:
- ✅ `PlatformOrchestrator` class exists
- ✅ `_determine_jobs()` method creates job list based on data type
- ✅ Creates CoreMachine job records
- ✅ Submits jobs to Service Bus queue
- ✅ Links jobs to platform request in database

### 3. Vector Job Definition ✅
**File**: [triggers/trigger_platform.py](triggers/trigger_platform.py#L336-L351)

**Current Vector Jobs Created**:
```python
elif request.data_type == DataType.VECTOR.value:
    jobs.extend([
        {
            'job_type': 'ingest_vector',  # ✅ EXISTS
            'parameters': {
                'source_path': source,
                'dataset_id': request.dataset_id,
                'table_name': f"{request.dataset_id}_{request.resource_id}",
                'schema': 'geo'
            }
        }
    ])
```

**Status**: ✅ Creates `ingest_vector` job, but **missing STAC job**!

### 4. CoreMachine Jobs ✅
**Files**:
- [jobs/ingest_vector.py](jobs/ingest_vector.py) - ✅ EXISTS
- [jobs/stac_catalog_vectors.py](jobs/stac_catalog_vectors.py) - ✅ EXISTS

**Working**:
- ✅ `ingest_vector`: Imports vector to PostGIS (geo schema)
- ✅ `stac_catalog_vectors`: Creates STAC metadata from PostGIS table
- ✅ Both jobs registered in `jobs/__init__.py:ALL_JOBS`

---

## 🚨 GAPS IDENTIFIED

### GAP 1: Missing STAC Job in Vector Pipeline ⚠️
**Location**: [triggers/trigger_platform.py](triggers/trigger_platform.py#L336-L351)

**Problem**: Platform only creates `ingest_vector` job, NOT `stac_catalog_vectors`

**Current Code**:
```python
elif request.data_type == DataType.VECTOR.value:
    jobs.extend([
        {
            'job_type': 'ingest_vector',
            'parameters': { ... }
        }
        # ❌ MISSING: stac_catalog_vectors job!
    ])
```

**Needed**:
```python
elif request.data_type == DataType.VECTOR.value:
    table_name = f"{request.dataset_id}_{request.resource_id}"

    jobs.extend([
        {
            'job_type': 'ingest_vector',
            'parameters': {
                'source_path': source,
                'dataset_id': request.dataset_id,
                'table_name': table_name,
                'schema': 'geo'
            }
        },
        {
            'job_type': 'stac_catalog_vectors',  # ⭐ ADD THIS
            'parameters': {
                'schema': 'geo',
                'table_name': table_name,
                'collection_id': request.dataset_id,
                'source_file': source
            }
        }
    ])
```

**Impact**: STAC metadata never created, users can't search via STAC API

---

### GAP 2: Response Doesn't Include OGC/STAC URLs ⚠️
**Location**: [triggers/trigger_platform.py](triggers/trigger_platform.py#L194-L205)

**Problem**: Response only returns `request_id` and `jobs_created`, not useful URLs

**Current Response**:
```json
{
    "success": true,
    "request_id": "abc123",
    "status": "PENDING",
    "jobs_created": ["job1", "job2"],
    "message": "Platform request submitted. 2 jobs created.",
    "monitor_url": "/api/platform/status/abc123"
}
```

**Needed Response**:
```json
{
    "success": true,
    "request_id": "abc123",
    "status": "PENDING",
    "jobs_created": ["job1", "job2"],
    "message": "Platform request submitted. 2 jobs created.",
    "monitor_url": "/api/platform/status/abc123",

    // ⭐ ADD THESE:
    "data_access": {
        "postgis": {
            "schema": "geo",
            "table": "test_dataset_v1"
        },
        "ogc_features": {
            "collection_url": "https://rmhgeoapibeta-.../api/features/collections/test_dataset_v1",
            "items_url": "https://rmhgeoapibeta-.../api/features/collections/test_dataset_v1/items",
            "web_map_url": "https://rmhazuregeo.z13.web.core.windows.net/?collection=test_dataset_v1"
        },
        "stac": {
            "collection_id": "test_dataset",
            "collection_url": "https://rmhgeoapibeta-.../api/collections/test_dataset",
            "items_url": "https://rmhgeoapibeta-.../api/collections/test_dataset/items",
            "search_url": "https://rmhgeoapibeta-.../api/search"
        }
    }
}
```

**Impact**: User has to manually construct URLs, doesn't know how to access their data

---

### GAP 3: No Job Completion Callback/Aggregation ⚠️
**Location**: Platform layer has no mechanism to know when ALL jobs complete

**Problem**:
- Platform creates 2 jobs (ingest + STAC)
- Jobs run asynchronously
- Platform doesn't know when BOTH complete
- Can't update Platform request status to COMPLETED

**Current Behavior**:
```
Platform creates jobs → Jobs queued → ??? → Jobs complete eventually
                                       ↑
                                No callback to Platform!
```

**Needed Behavior**:
```
Platform creates jobs → Jobs queued → Jobs complete → Callback updates Platform
                                                       ↓
                                              Status: COMPLETED
                                              data_access URLs populated
```

**Implementation Options**:

**Option A - Poll Job Status** (Easiest):
```python
# In Platform status endpoint or background timer
def check_request_completion(request_id):
    jobs = platform_repo.get_jobs_for_request(request_id)
    all_complete = all(job.status in ['completed', 'failed'] for job in jobs)

    if all_complete:
        # Aggregate results
        table_name = extract_from_job_results(jobs, 'ingest_vector')
        collection_id = extract_from_job_results(jobs, 'stac_catalog_vectors')

        # Update platform request
        platform_repo.update_request_status(request_id, 'COMPLETED')
        platform_repo.update_data_access_urls(request_id, table_name, collection_id)
```

**Option B - Job Completion Hook** (Better):
```python
# In CoreMachine job completion handler
async def on_job_complete(job_id, job_type, result):
    # Check if job belongs to platform request
    platform_request_id = job.parameters.get('_platform_request_id')

    if platform_request_id:
        # Store job result in platform request
        platform_repo.update_job_result(platform_request_id, job_id, result)

        # Check if all jobs complete
        if platform_repo.all_jobs_complete(platform_request_id):
            # Aggregate results and update URLs
            finalize_platform_request(platform_request_id)
```

**Impact**: Platform requests stay in PROCESSING forever, never get data_access URLs

---

### GAP 4: No Idempotency Check ⚠️
**Location**: [triggers/trigger_platform.py](triggers/trigger_platform.py#L160-L186)

**Problem**: Submitting same request twice creates duplicate jobs

**Current Behavior**:
```python
# Generate deterministic request ID
request_id = generate_request_id(dataset_id, resource_id, version_id)

# Create platform record (no check if exists)
platform_record = ApiRequest(request_id=request_id, ...)
stored_record = repo.create_request(platform_record)  # ❌ Fails if exists? Creates duplicate?
```

**Needed Behavior**:
```python
# Generate deterministic request ID
request_id = generate_request_id(dataset_id, resource_id, version_id)

# Check if request already exists
existing_request = repo.get_request(request_id)

if existing_request:
    logger.info(f"Request {request_id} already exists - returning existing")
    return existing_request  # ⭐ Return existing with data_access URLs

# Create new request if doesn't exist
platform_record = ApiRequest(request_id=request_id, ...)
stored_record = repo.create_request(platform_record)
```

**Impact**: Re-uploading same file creates duplicate PostGIS tables and STAC items

---

### GAP 5: Job Dependencies Not Enforced ⚠️
**Location**: Jobs run in parallel, but STAC job needs ingest_vector to complete first

**Problem**:
- `ingest_vector` creates PostGIS table
- `stac_catalog_vectors` reads from PostGIS table
- If STAC job runs first → ERROR (table doesn't exist)

**Current Behavior**:
```
Both jobs submitted to queue simultaneously
    ↓                           ↓
ingest_vector starts      stac_catalog_vectors starts
    ↓                           ↓
Creates table              ❌ ERROR: Table doesn't exist!
```

**Needed Behavior - Option A (Sequential Submission)**:
```python
# Platform submits jobs sequentially
job1_id = await create_job('ingest_vector', ...)
await wait_for_job_completion(job1_id)  # Wait for ingest to complete

job2_id = await create_job('stac_catalog_vectors', ...)  # Only submit after ingest done
```

**Needed Behavior - Option B (Job-level Dependencies)**:
```python
# Jobs declare dependencies
{
    'job_type': 'stac_catalog_vectors',
    'parameters': {...},
    'depends_on': ['ingest_vector_job_id']  # ⭐ Don't start until this completes
}
```

**Impact**: STAC cataloging fails intermittently due to race condition

---

## 📋 Summary of Gaps

| # | Gap | Severity | Location | Impact |
|---|-----|----------|----------|--------|
| 1 | Missing STAC job | **P0 - Critical** | trigger_platform.py:336-351 | No STAC metadata created |
| 2 | No OGC/STAC URLs in response | **P0 - Critical** | trigger_platform.py:194-205 | User doesn't know how to access data |
| 3 | No job completion aggregation | **P0 - Critical** | Platform layer | Request never marked COMPLETED |
| 4 | No idempotency check | **P1 - High** | trigger_platform.py:160-186 | Duplicate data on re-upload |
| 5 | No job dependencies | **P1 - High** | Platform orchestration | Race condition failures |

---

## 🔧 Recommended Implementation Order

### Phase 1: Basic Workflow (P0)
1. ✅ Add `stac_catalog_vectors` job to vector pipeline (GAP 1)
2. ✅ Add data_access URLs to response (GAP 2) - can be static for now
3. ✅ Add job dependency handling (GAP 5) - sequential submission is easiest

**Result**: User gets URLs immediately, jobs run in correct order

### Phase 2: Completion Tracking (P0)
4. ✅ Implement job completion callback (GAP 3)
5. ✅ Update data_access URLs when jobs complete
6. ✅ Update Platform request status to COMPLETED

**Result**: Platform knows when workflow is done, URLs are accurate

### Phase 3: Idempotency (P1)
7. ✅ Add request existence check (GAP 4)
8. ✅ Return existing request if already processed

**Result**: Re-uploading same file is safe, returns existing data

---

## 🎯 Success Criteria

When all gaps are fixed:

✅ **Upload** vector file via Platform API
✅ **Receive** response with OGC Features URL, STAC URL, web map URL
✅ **Jobs** run sequentially (ingest → STAC)
✅ **Platform** request marked COMPLETED when all jobs finish
✅ **Re-upload** same file → returns existing URLs (idempotent)
✅ **View** data immediately on web map
✅ **Search** data via STAC API
✅ **Query** data via OGC Features API

---

## 📝 Files That Need Changes

1. **triggers/trigger_platform.py** (Lines 336-351, 194-205, 160-186)
   - Add STAC job to vector pipeline
   - Add data_access URLs to response
   - Add idempotency check
   - Add sequential job submission

2. **infrastructure/platform.py** (NEW METHODS NEEDED)
   - `get_request(request_id)` - Check if request exists
   - `update_data_access_urls(request_id, urls)` - Store URLs
   - `all_jobs_complete(request_id)` - Check completion
   - `finalize_request(request_id)` - Aggregate results

3. **Platform completion handler** (NEW FILE OR TIMER)
   - Poll for job completion
   - Aggregate results
   - Update Platform request with final URLs

---

## 💡 Notes

**Philosophy**: All changes in Platform/services layers, CoreMachine stays unchanged

**CoreMachine jobs already work**:
- `ingest_vector` - ✅ Tested and working
- `stac_catalog_vectors` - ✅ Tested and working

**Just need Platform orchestration to**:
1. Create both jobs (currently only creates ingest_vector)
2. Run them in order (ingest first, then STAC)
3. Return URLs in response
4. Track completion and update status

This is **entirely Platform layer work** - no CoreMachine changes needed! 🎯
