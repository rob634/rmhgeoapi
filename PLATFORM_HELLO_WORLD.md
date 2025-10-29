# Platform Layer Hello World - Reference Implementation

**Date**: 29 OCT 2025
**Author**: Robert and Geospatial Claude Legion
**Purpose**: Platform layer "hello world" - the reference implementation for external app → Platform → CoreMachine flow

## Overview

This is our **fractal pattern demo** - just like `hello_world` was the reference for CoreMachine development, this is the reference for Platform layer development.

**The Flow**:
```
External App (DDH) → Platform Request → Platform Orchestrator → CoreMachine hello_world job → Response
```

## Architecture - "Turtle Above CoreMachine"

```
┌─────────────────────────────────────────────────────────────┐
│ PLATFORM LAYER (Application-Level Orchestration)           │
│                                                             │
│  External Request → Platform Record → Job Selection        │
│  (DDH, Web UI)      (app.platform_    (What jobs needed   │
│                      requests)         for this request?)  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
            ┌──────────────────────────────┐
            │   COREMACHINE LAYER          │
            │   (Job Orchestration)        │
            │                              │
            │   hello_world job            │
            │   ├── Stage 1: greet         │
            │   └── Stage 2: farewell      │
            └──────────────────────────────┘
```

## The Reference Implementation

### 1. Platform Request Submission

**Endpoint**: `POST /api/platform/submit`

**Request Body**:
```json
{
  "dataset_id": "test-hello-world",
  "resource_id": "demo-resource",
  "version_id": "v1.0",
  "data_type": "raster",
  "source_location": "https://example.com/not-used-for-hello-world",
  "parameters": {
    "test_mode": true,
    "message": "Hello from Platform layer!"
  },
  "client_id": "test"
}
```

**Key Field**: `"test_mode": true` - This triggers Platform orchestrator to create a hello_world job

**Response**:
```json
{
  "success": true,
  "request_id": "abc123...",
  "status": "pending",
  "jobs_created": ["job_id_xyz..."],
  "message": "Platform request submitted. 1 jobs created.",
  "monitor_url": "/api/platform/status/abc123..."
}
```

### 2. Platform Orchestrator Logic

**File**: `triggers/trigger_platform.py`

**What Happens**:
```python
# 1. Validate request with Pydantic
platform_req = PlatformRequest(**req_body)

# 2. Generate deterministic request ID
request_id = generate_request_id(
    platform_req.dataset_id,
    platform_req.resource_id,
    platform_req.version_id
)

# 3. Store platform request in database
platform_record = PlatformRecord(
    request_id=request_id,
    dataset_id="test-hello-world",
    status=PlatformRequestStatus.PENDING,
    # ...
)
repo.create_request(platform_record)

# 4. Platform orchestrator determines which jobs to create
orchestrator = PlatformOrchestrator()
jobs_created = await orchestrator.process_platform_request(platform_record)

# 5. For test_mode=true, orchestrator creates hello_world job
if request.parameters.get('test_mode'):
    jobs.append({
        'job_type': 'hello_world',
        'parameters': {
            'message': request.parameters.get('message', 'Testing platform')
        }
    })
```

### 3. CoreMachine Job Creation

**Platform orchestrator creates CoreMachine job**:

```python
# triggers/trigger_platform.py:628-697
async def _create_coremachine_job(
    self,
    request: PlatformRecord,
    job_type: str,
    parameters: Dict[str, Any]
) -> Optional[str]:
    """
    Create a CoreMachine job and submit it to jobs queue.

    This duplicates trigger_job_submit.py logic intentionally
    (testing both systems independently before consolidation).
    """

    # Add platform metadata to job parameters
    job_params = {
        **parameters,
        '_platform_request_id': request.request_id,
        '_platform_dataset': request.dataset_id
    }

    # Generate job ID (SHA256 hash - FULL 64 chars!)
    job_id = self._generate_job_id(job_type, job_params)

    # Create job record (status='queued' not 'pending'!)
    job_record = JobRecord(
        job_id=job_id,
        job_type='hello_world',
        status='queued',
        parameters=job_params,
        metadata={
            'platform_request': request.request_id,
            'created_by': 'platform_orchestrator'
        }
    )

    # Store in database
    stored_job = self.job_repo.create_job(job_record)

    # Submit to Service Bus jobs queue
    await self._submit_to_queue(stored_job)

    return job_id
```

### 4. CoreMachine Execution

**Once job is in Service Bus jobs queue, CoreMachine takes over**:

```
Service Bus Jobs Queue → trigger_job_processor.py → CoreMachine.process_job()
                                                           ↓
                                                    hello_world job
                                                           ↓
                                                    Stage 1: greet task
                                                           ↓
                                                    Stage 2: farewell task
                                                           ↓
                                                    Job completion
```

**This is identical to direct job submission** - Platform just acts as a relay with business logic.

### 5. Monitoring Platform Request

**Endpoint**: `GET /api/platform/status/{request_id}`

**Response**:
```json
{
  "success": true,
  "request": {
    "request_id": "abc123...",
    "dataset_id": "test-hello-world",
    "status": "processing",
    "job_ids": ["job_xyz..."],
    "created_at": "2025-10-29T...",
    "metadata": {
      "client_id": "test",
      "source_location": "..."
    }
  },
  "jobs": [
    {
      "job_id": "job_xyz...",
      "job_type": "hello_world",
      "status": "completed",
      "stage": 2,
      "result_data": {
        "stage_1_greeting": "Hello from Platform layer!",
        "stage_2_farewell": "Goodbye!"
      }
    }
  ]
}
```

## Database Schema

### Platform Requests Table

**Table**: `app.platform_requests`

```sql
CREATE TABLE app.platform_requests (
    request_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    data_type TEXT NOT NULL,
    status TEXT NOT NULL,
    job_ids TEXT[] DEFAULT '{}',
    parameters JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    result_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Platform-Job Association Table

**Table**: `app.platform_jobs`

```sql
CREATE TABLE app.platform_jobs (
    request_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (request_id, job_id),
    FOREIGN KEY (request_id) REFERENCES app.platform_requests(request_id),
    FOREIGN KEY (job_id) REFERENCES app.jobs(job_id)
);
```

## Testing Commands

### 1. Submit Platform Request (test_mode)

```bash
curl -X POST 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/submit' \
  -H 'Content-Type: application/json' \
  -d '{
    "dataset_id": "test-hello-world",
    "resource_id": "demo-resource",
    "version_id": "v1.0",
    "data_type": "raster",
    "source_location": "https://example.com/dummy",
    "parameters": {
      "test_mode": true,
      "message": "Hello from Platform layer!"
    },
    "client_id": "test"
  }' | python3 -m json.tool
```

**Expected Output**:
```json
{
  "success": true,
  "request_id": "abc123...",
  "status": "pending",
  "jobs_created": ["job_xyz..."],
  "message": "Platform request submitted. 1 jobs created.",
  "monitor_url": "/api/platform/status/abc123..."
}
```

### 2. Check Platform Request Status

```bash
# Use request_id from step 1
curl -s 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/status/{REQUEST_ID}' \
  | python3 -m json.tool
```

### 3. Check CoreMachine Job Status

```bash
# Use job_id from step 1 response
curl -s 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}' \
  | python3 -m json.tool
```

### 4. Query Platform Requests List

```bash
curl -s 'https://rmhgeoapibeta-dzd8gyasenbkaqax.eastus-01.azurewebsites.net/api/platform/status' \
  | python3 -m json.tool
```

## Critical Implementation Details

### ✅ FIXED Issues (29 OCT 2025)

1. **Job Type Validation** - Platform now uses actual job types from `jobs/__init__.py:ALL_JOBS`:
   - ✅ `hello_world` (test mode)
   - ✅ `validate_raster_job` (not `validate_raster`)
   - ✅ `process_raster` (not `create_cog`)
   - ✅ `ingest_vector` (not `validate_vector` + `import_to_postgis`)

2. **Job ID Length** - Platform generates FULL SHA256 hash (64 chars):
   - ✅ `hashlib.sha256(...).hexdigest()` (not `[:32]`)
   - ✅ Passes JobRecord validation (minLength=64)

3. **Status Enum** - Platform uses correct JobStatus enum values:
   - ✅ `status='queued'` (not `'pending'`)
   - ✅ Matches JobStatus enum in core/models/job.py

### 🚧 PENDING Implementation

1. **Platform Request Completion Detection** - Need to monitor when all associated jobs complete
2. **Result Aggregation** - Collect results from all CoreMachine jobs into platform_requests.result_data
3. **Error Propagation** - If any CoreMachine job fails, mark platform request as failed
4. **Timer Cleanup** - Monitor stuck platform requests (similar to job/task cleanup)

## Success Criteria

**Phase 1: Hello World Working** ✅ (Target: 29 OCT 2025)
- [ ] Platform request creates hello_world job successfully
- [ ] Job appears in Service Bus jobs queue
- [ ] CoreMachine processes job (Stage 1 + Stage 2)
- [ ] Job completes successfully
- [ ] Platform status endpoint shows completed job
- [ ] No errors in Application Insights

**Phase 2: Real Workflows** (Future)
- [ ] Platform request creates validate_raster_job + process_raster
- [ ] Multiple jobs execute in correct order
- [ ] Platform request marked complete when all jobs done
- [ ] Results aggregated from all jobs

## Files Involved

### Platform Layer
- `triggers/trigger_platform.py` - HTTP trigger for platform request submission
- `triggers/trigger_platform_status.py` - HTTP trigger for platform status queries
- `infrastructure/platform.py` - PlatformRepository (database operations)

### CoreMachine Layer (Unchanged)
- `triggers/trigger_job_processor.py` - Service Bus trigger for job processing
- `core/machine.py` - CoreMachine orchestration engine
- `jobs/hello_world.py` - Hello world job definition
- `services/hello_world.py` - Hello world service implementation

### Database
- `app.platform_requests` - Platform request records
- `app.platform_jobs` - Platform-to-job associations
- `app.jobs` - CoreMachine job records (existing)
- `app.tasks` - CoreMachine task records (existing)

## Why This Pattern?

**Platform layer is "turtle above CoreMachine" in our fractal pattern**:

1. **External apps** (DDH, web UI) don't know about CoreMachine jobs
2. **Platform layer** translates business requests into job workflows
3. **CoreMachine** executes jobs without knowing about platform requests
4. **Results** flow back up: CoreMachine → Platform → External App

**Example Real Workflow**:
```
DDH Request: "Ingest this Landsat scene"
     ↓
Platform: "I need validate_raster_job + process_raster + create_stac_item"
     ↓
CoreMachine: "Execute these 3 jobs sequentially"
     ↓
Platform: "All jobs done, here's your STAC item URL"
     ↓
DDH: "Thanks, added to catalog!"
```

## Comparison: Direct Job Submission vs Platform

### Direct Job Submission (CoreMachine Only)
```bash
# User must know job type and parameters
curl -X POST '/api/jobs/submit/hello_world' \
  -d '{"message": "Hello"}'
```

### Platform Submission (Application Layer)
```bash
# User describes WHAT they want (business logic)
curl -X POST '/api/platform/submit' \
  -d '{
    "dataset_id": "my-data",
    "data_type": "raster",
    "parameters": {"test_mode": true}
  }'

# Platform determines HOW (creates hello_world job)
```

**Platform adds business logic layer** - user doesn't need to know about jobs, just describes what they want.

---

**Next Steps**:
1. Deploy current Platform fixes (SHA256 full hash, status='queued')
2. Test hello_world creation via Platform
3. Verify job executes successfully
4. Document any issues in TODO.md
5. Use as reference for real raster/vector workflows
