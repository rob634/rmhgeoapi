# PROCESS_RASTER WORKFLOW - COMPLETE TRACE-THROUGH DOCUMENT

**Date Created**: 24 NOV 2025  
**Version**: 1.0  
**Status**: Complete architectural trace of process_raster job execution  

---

## TABLE OF CONTENTS

1. [Executive Summary](#executive-summary)
2. [Entry Point: HTTP Request](#entry-point-http-request)
3. [Job Definition](#job-definition)
4. [Job Submission Flow](#job-submission-flow)
5. [Service Bus Job Queue Processing](#service-bus-job-queue-processing)
6. [Task Generation and Queueing](#task-generation-and-queueing)
7. [Task Processing](#task-processing)
8. [Database Schema](#database-schema)
9. [Complete Execution Flow Diagram](#complete-execution-flow-diagram)
10. [Key Files Reference](#key-files-reference)

---

## EXECUTIVE SUMMARY

The process_raster workflow is a three-stage pipeline for converting raster files to Cloud Optimized GeoTIFFs (COGs) with STAC metadata cataloging. It demonstrates the Job→Stage→Task architecture with sequential stage advancement and atomic completion detection.

**Architecture Pattern**: Job→Stage→Task with "last task turns out the lights" atomic completion  
**Processing Type**: Sequential stages, single task per stage  
**Supported File Size**: Up to 1GB (smaller files use in-memory processing)  
**Outputs**: Cloud Optimized GeoTIFF + STAC metadata in PostGIS database

---

## ENTRY POINT: HTTP REQUEST

### HTTP Trigger Route
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/function_app.py`  
**Line**: 566-569

```python
@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """Job submission endpoint using HTTP trigger base class."""
    return submit_job_trigger.handle_request(req)
```

**Route Pattern**: `POST /api/jobs/submit/process_raster`

### Example Request
```bash
curl -X POST https://rmhazuregeoapi.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "samples/dem.tif",
    "container_name": "rmhazuregeobronze",
    "input_crs": "EPSG:32633",
    "raster_type": "dem",
    "output_tier": "analysis",
    "collection_id": "elevation-data"
  }'
```

### Response (New Job)
```json
{
    "job_id": "a3c7f8e2b1d4c6f9a2e5b8d1c4f7a0e3",
    "status": "created",
    "job_type": "process_raster",
    "message": "Job created and queued for processing",
    "parameters": {...validated_parameters...},
    "queue_info": {
        "queued": true,
        "queue_type": "service_bus",
        "queue_name": "geospatial-jobs",
        "message_id": "uuid-of-service-bus-message"
    },
    "idempotent": false
}
```

---

## JOB DEFINITION

### Job Class Definition
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/jobs/process_raster.py`  
**Lines**: 62-97

```python
class ProcessRasterWorkflow(JobBase):
    """
    Small file raster processing workflow (<= 1GB).
    """
    
    job_type: str = "process_raster"
    description: str = "Process raster to COG with STAC metadata (files <= 1GB)"
    
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "description": "Validate raster, check CRS, analyze bit-depth, detect type",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "create_cog",
            "task_type": "create_cog",
            "description": "Reproject to EPSG:4326 and create COG (single operation)",
            "parallelism": "single"
        },
        {
            "number": 3,
            "name": "create_stac",
            "task_type": "extract_stac_metadata",
            "description": "Create STAC metadata for COG (ready for TiTiler-pgstac)",
            "parallelism": "single"
        }
    ]
```

### Parameters Schema
**Lines**: 99-152

Key parameters:
- `blob_name` (required): Path to raster file in blob storage
- `container_name` (optional): Container name (defaults to config.storage.bronze.get_container('rasters'))
- `input_crs` (optional): User override for CRS
- `raster_type` (optional): Expected type - auto|rgb|rgba|dem|categorical|multispectral|nir
- `output_tier` (optional): COG output tier - visualization|analysis|archive|all
- `target_crs` (optional): Target CRS (default: EPSG:4326)
- `compression` (optional): User override
- `_skip_validation` (optional): Testing only

### Interface Contract Methods
All jobs must implement these 5 methods (enforced by `jobs/__init__.py` at import time):

1. **validate_job_parameters(params: dict) -> dict**
   - Lines: 154-335
   - Validates and normalizes parameters
   - **Critical**: Checks blob exists in storage (fail-fast validation)

2. **generate_job_id(params: dict) -> str**
   - Lines: 337-347
   - Returns SHA256 hash of parameters for idempotency
   - Same parameters = same job_id

3. **create_job_record(job_id: str, params: dict) -> dict**
   - Lines: 349-392
   - Creates JobRecord in PostgreSQL
   - Status: QUEUED
   - Total stages: 3

4. **queue_job(job_id: str, params: dict) -> dict**
   - Lines: 394-446
   - Sends JobQueueMessage to Service Bus jobs queue
   - Returns queue information

5. **create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list) -> list[dict]**
   - Lines: 448-620
   - Generates task parameters for each stage (CRITICAL - called by CoreMachine)
   - **Stage 1**: Creates single validation task
   - **Stage 2**: Requires Stage 1 results, creates COG task
   - **Stage 3**: Requires Stage 2 results, creates STAC task
   - Returns list of task dicts: `[{task_id, task_type, parameters}, ...]`

### Finalization
**Lines**: 622-724

```python
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
```
- Aggregates results from all 3 stages
- Generates TiTiler visualization URLs
- Returns comprehensive job summary

---

## JOB SUBMISSION FLOW

### Step 1: Job Validation via Submit Trigger
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/triggers/submit_job.py`  
**Class**: JobSubmissionTrigger  
**Method**: process_request (Lines: 147-309)

**Flow Steps**:

#### Step 1a: Extract Parameters (Lines: 160-187)
- Extract job_type from URL path
- Extract JSON body with all parameters
- Separate standard DDH parameters from job-specific ones

#### Step 1b: Load Job Class (Lines: 189-196)
- Look up job_type in `jobs.ALL_JOBS` registry
- For process_raster: Loads `ProcessRasterWorkflow` class

#### Step 1c: Validate Parameters (Lines: 208-218)
- Calls: `ProcessRasterWorkflow.validate_job_parameters(job_params)`
- Returns: normalized and validated parameters dict
- **Fail-Fast**: Checks blob existence immediately

#### Step 1d: Generate Job ID (Lines: 220-228)
- Calls: `ProcessRasterWorkflow.generate_job_id(validated_params)`
- Returns: SHA256 hash (e.g., "a3c7f8e2b1d4c6f9...")
- **Idempotency**: Same params = same job_id

#### Step 1e: Check for Existing Job (Lines: 231-266)
- Query database: `repos['job_repo'].get_job(job_id)`
- If job exists:
  - If COMPLETED: Return existing results (idempotent response)
  - If PROCESSING/QUEUED: Return current status (don't re-queue)

#### Step 1f: Create Job Record (Lines: 269-281)
- Calls: `ProcessRasterWorkflow.create_job_record(job_id, validated_params)`
- **Database Operation**:
  - Creates JobRecord with status=QUEUED
  - Stores in `app.jobs` table
  - Total stages: 3

#### Step 1g: Queue Job (Lines: 283-298)
- Calls: `ProcessRasterWorkflow.queue_job(job_id, validated_params)`
- **Service Bus Operation**:
  - Creates JobQueueMessage
  - Sends to `geospatial-jobs` Service Bus queue
  - Message format: `{"job_id": ..., "job_type": ..., "stage": 1, "parameters": ...}`

#### Step 1h: Return Success (Lines: 300-309)
- Returns HTTP 200 with job creation response
- Includes job_id, queue information, validated parameters

### Job Database Record
**Table**: `app.jobs` (PostgreSQL)  
**Fields**:
- job_id (primary key)
- job_type: "process_raster"
- status: "queued"
- stage: 1
- total_stages: 3
- parameters: {...validated_parameters...}
- metadata: {...}
- created_at: timestamp
- updated_at: timestamp

---

## SERVICE BUS JOB QUEUE PROCESSING

### Job Queue Trigger
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/function_app.py`  
**Lines**: 1921-2030

```python
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="geospatial-jobs",
    connection="ServiceBusConnection"
)
def process_service_bus_job(msg: func.ServiceBusMessage) -> None:
```

### Processing Flow

#### Step 1: Parse Service Bus Message (Lines: 1957-1980)
- Extract message body from Service Bus
- Deserialize JSON: `JobQueueMessage.model_validate_json(message_body)`
- Extract: job_id, job_type, stage, parameters, correlation_id

#### Step 2: Add Correlation ID (Lines: 1982-1986)
- Generate correlation_id for tracking
- Add to parameters: `_correlation_id`, `_processing_path`

#### Step 3: Invoke CoreMachine (Lines: 1988-1989)
```python
result = core_machine.process_job_message(job_message)
```
- Delegates to CoreMachine orchestrator
- CoreMachine handles all stage task generation and queueing

#### Step 4: Error Handling (Lines: 1995-2029)
- If exception: Log details and mark job as FAILED in database
- Prevents stuck jobs (FP1 FIX - 11 NOV 2025)

---

## TASK GENERATION AND QUEUEING

### CoreMachine Job Processing
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/core/machine.py`  
**Method**: process_job_message (Lines: 312-546)

This is the universal orchestrator that ALL jobs use (composition pattern).

**CRITICAL FLOW**:

#### Step 1: Load Job Class (Lines: 345-361)
```python
job_class = self.jobs_registry[job_message.job_type]  # ProcessRasterWorkflow
```

#### Step 2: Fetch Job Record (Lines: 363-373)
```python
job_record = self.repos['job_repo'].get_job(job_message.job_id)
```
- Retrieves full job record with parameters and metadata

#### Step 3: Update Job Status (Lines: 375-383)
```python
self.state_manager.update_job_status(job_message.job_id, JobStatus.PROCESSING)
```
- Transitions: QUEUED → PROCESSING

#### Step 4: Update Job Stage (Lines: 385-393)
```python
self.state_manager.update_job_stage(job_message.job_id, job_message.stage)
```
- Keeps job.stage field synchronized with actual processing stage

#### Step 5: Fetch Previous Stage Results (Lines: 395-407)
- For stages > 1: Fetch all completed tasks from previous stage
- Returns list of TaskResult objects with execution results
- **Used by**: Fan-out tasks that need previous stage output

#### Step 6: Call Job's create_tasks_for_stage (Lines: 449-472)
```python
# For process_raster Stage 1:
tasks = ProcessRasterWorkflow.create_tasks_for_stage(
    stage=1,
    job_params=job_record.parameters,
    job_id=job_message.job_id,
    previous_results=None  # Not applicable for Stage 1
)
# Returns: [{"task_id": "...", "task_type": "validate_raster", "parameters": {...}}]
```

#### Step 7: Convert to TaskDefinition Objects (Lines: 481-511)
```python
task_def = TaskDefinition(
    task_id=task_dict['task_id'],
    task_type=task_dict['task_type'],
    parameters=task_dict['parameters'],
    parent_job_id=job_message.job_id,
    job_type=job_message.job_type,
    stage=job_message.stage
)
```
- Wraps plain dicts in Pydantic models
- Adds job context metadata

#### Step 8: Queue Tasks (Lines: 513-546)
```python
result = self._individual_queue_tasks(task_definitions, job_message.job_id, job_message.stage)
```

**Queue Operation Details**:
- For each TaskDefinition:
  1. Create TaskRecord in database (INSERT into app.tasks)
  2. Create TaskQueueMessage (serialized JSON)
  3. Send to Service Bus `geospatial-tasks` queue
  4. Track success/failure

---

## TASK PROCESSING

### Task Queue Trigger
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/function_app.py`  
**Lines**: 2032-2120 (continuation of task processing)

```python
@app.service_bus_queue_trigger(
    arg_name="msg",
    queue_name="geospatial-tasks",
    connection="ServiceBusConnection"
)
def process_service_bus_task(msg: func.ServiceBusMessage) -> None:
```

### Stage 1: Validate Raster

#### Task Execution
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_validation.py`  
**Function**: validate_raster (Lines: 118-...)

**Input Parameters**:
```python
{
    "blob_url": "https://...blob_name with SAS token...",
    "blob_name": "samples/dem.tif",
    "container_name": "rmhazuregeobronze",
    "input_crs": "EPSG:32633",
    "raster_type": "dem",
    "strict_mode": False,
    "_skip_validation": False
}
```

**Processing Steps**:
1. Download raster from blob via blob_url with SAS token
2. Read with rasterio.open()
3. Validate CRS (file metadata or user override)
4. Analyze bit-depth efficiency
5. Detect raster type (RGB, DEM, categorical, etc.)
6. Determine applicable COG tiers
7. Generate optimal COG settings recommendations

**Output Result**:
```python
{
    "success": True,
    "result": {
        "source_crs": "EPSG:32633",
        "crs_source": "file_metadata",
        "bounds": [minx, miny, maxx, maxy],
        "shape": [height, width],
        "band_count": 1,
        "dtype": "float32",
        "raster_type": {
            "detected_type": "dem",
            "confidence": "HIGH",
            "evidence": ["1 band, float32 (typical DEM)"],
            "optimal_cog_settings": {
                "compression": "deflate",
                "overview_resampling": "average",
                "reproject_resampling": "bilinear"
            }
        },
        "cog_tiers": {
            "applicable_tiers": ["analysis", "archive"],
            "total_compatible": 2
        },
        "bit_depth_check": {"efficient": True, "current_dtype": "float32"},
        "warnings": []
    }
}
```

#### Task Completion
- CoreMachine marks task as COMPLETED
- Stores result in app.tasks.result_data
- **CHECK**: Is this the last task in Stage 1?
  - YES: Triggers stage advancement logic
  - NO: Wait for other tasks

### Stage 2: Create COG

#### Stage Advancement
When last task of Stage 1 completes, CoreMachine:
1. Checks all tasks in Stage 1 are complete
2. If yes: Executes fetch previous results (Stage 1 tasks)
3. Collects all Stage 1 task results into list
4. Creates new job message: stage=2, parameters=same
5. Sends to geospatial-jobs queue

#### Task Execution
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_cog.py`  
**Function**: create_cog (Lines: 60-...)

**Input Parameters** (from process_raster.py create_tasks_for_stage):
```python
{
    "blob_name": "samples/dem.tif",
    "container_name": "rmhazuregeobronze",
    "source_crs": "EPSG:32633",  # From Stage 1 result
    "target_crs": "EPSG:4326",
    "raster_type": {
        "detected_type": "dem",
        "optimal_cog_settings": {...}
    },
    "output_blob_name": "dem_cog_analysis.tif",  # Generated in create_tasks_for_stage
    "output_tier": "analysis",
    "jpeg_quality": 85,
    "overview_resampling": "average",
    "reproject_resampling": "bilinear"
}
```

**Processing Steps**:
1. Validate parameters
2. Download source raster from bronze container
3. Use rio-cogeo.cog_translate() for:
   - Single-pass reprojection (EPSG:32633 → EPSG:4326)
   - COG creation with BAND interleave
   - Compression based on output_tier (analysis=DEFLATE)
   - Overview generation
4. Upload COG to silver container
5. Clean up temporary files

**Output Result**:
```python
{
    "success": True,
    "result": {
        "cog_blob": "dem_cog_analysis.tif",
        "cog_container": "rmhazuregeosiver",  # Silver container
        "cog_tier": "analysis",
        "storage_tier": "hot",
        "source_blob": "samples/dem.tif",
        "source_container": "rmhazuregeobronze",
        "reprojection_performed": True,
        "source_crs": "EPSG:32633",
        "target_crs": "EPSG:4326",
        "bounds_4326": [-180, -90, 180, 90],
        "shape": [height, width],
        "size_mb": 45.3,
        "compression": "deflate",
        "processing_time_seconds": 23.5
    }
}
```

### Stage 3: Create STAC Metadata

#### Stage Advancement
When last task of Stage 2 completes:
1. Creates job message: stage=3
2. Sends to geospatial-jobs queue
3. CoreMachine fetches Stage 2 result (COG blob path)

#### Task Execution
**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/stac_catalog.py`  
**Function**: extract_stac_metadata (Lines: 100-...)

**Input Parameters** (from process_raster.py create_tasks_for_stage):
```python
{
    "container_name": "rmhazuregeosiver",  # Silver container
    "blob_name": "dem_cog_analysis.tif",   # COG from Stage 2
    "collection_id": "elevation-data"
}
```

**Processing Steps**:
1. Download COG from silver container
2. Extract STAC metadata (bands, CRS, bbox, etc.)
3. Create STAC Item JSON
4. Insert into PgSTAC database (pgstac.items table)
5. Record in PostGIS for spatial indexing

**Output Result**:
```python
{
    "success": True,
    "result": {
        "item_id": "dem_cog_analysis_xyz",
        "collection_id": "elevation-data",
        "bbox": [minx, miny, maxx, maxy],
        "geometry_type": "Polygon",
        "epsg": 4326,
        "inserted_to_pgstac": True,
        "stac_item": {...full STAC JSON...}
    }
}
```

### Task Completion and Job Finalization

When last task of Stage 3 completes:
1. CoreMachine detects no more stages
2. Calls: `ProcessRasterWorkflow.finalize_job(context)`
3. Aggregates all 3 stage results
4. Updates job status to COMPLETED
5. Stores result_data in database

**Final Job Result**:
```python
{
    "job_type": "process_raster",
    "source_blob": "samples/dem.tif",
    "source_container": "rmhazuregeobronze",
    "validation": {
        "source_crs": "EPSG:32633",
        "raster_type": "dem",
        "confidence": "HIGH",
        "bit_depth_efficient": True,
        "warnings": []
    },
    "cog": {
        "cog_blob": "dem_cog_analysis.tif",
        "cog_container": "rmhazuregeosiver",
        "reprojection_performed": True,
        "size_mb": 45.3,
        "compression": "deflate",
        "processing_time_seconds": 23.5
    },
    "stac": {
        "item_id": "dem_cog_analysis_xyz",
        "collection_id": "elevation-data",
        "bbox": [minx, miny, maxx, maxy],
        "inserted_to_pgstac": True,
        "ready_for_titiler": True
    },
    "titiler_urls": {
        "tilejson_url": "https://...",
        "viewer_url": "https://...",
        "cog_info_url": "https://..."
    },
    "share_url": "https://...",  # PRIMARY URL FOR END USERS
    "stages_completed": 3,
    "total_tasks_executed": 3,
    "tasks_by_status": {"completed": 3, "failed": 0}
}
```

---

## DATABASE SCHEMA

### Jobs Table (app.jobs)
**Schema**: PostgreSQL, app schema

| Column | Type | Description |
|--------|------|-------------|
| job_id | VARCHAR(255) PRIMARY KEY | SHA256 hash of parameters |
| job_type | VARCHAR(100) | "process_raster" |
| status | job_status_enum | QUEUED → PROCESSING → COMPLETED |
| stage | INTEGER | Current stage (1-3) |
| total_stages | INTEGER | 3 |
| parameters | JSONB | Validated job parameters |
| stage_results | JSONB | Results from each completed stage |
| metadata | JSONB | Job metadata |
| result_data | JSONB | Final aggregated results |
| error_details | TEXT | Error message if FAILED |
| created_at | TIMESTAMP | Job creation time |
| updated_at | TIMESTAMP | Last state change |

### Tasks Table (app.tasks)
**Schema**: PostgreSQL, app schema

| Column | Type | Description |
|--------|------|-------------|
| task_id | VARCHAR(255) PRIMARY KEY | Deterministic hash from job_id + stage + type |
| parent_job_id | VARCHAR(255) | Foreign key to jobs |
| job_type | VARCHAR(100) | "process_raster" |
| task_type | VARCHAR(100) | validate_raster, create_cog, extract_stac_metadata |
| stage | INTEGER | Which stage (1, 2, or 3) |
| status | task_status_enum | QUEUED → PROCESSING → COMPLETED/FAILED |
| parameters | JSONB | Task parameters |
| result_data | JSONB | Task execution results |
| error_details | TEXT | Error if FAILED |
| retry_count | INTEGER | Number of retry attempts |
| created_at | TIMESTAMP | Task creation time |
| updated_at | TIMESTAMP | Last state change |

### STAC Tables (pgstac schema)
**Created by**: PgSTAC installation, used by extract_stac_metadata

| Table | Purpose |
|-------|---------|
| pgstac.items | STAC items (one per COG) |
| pgstac.collections | STAC collections |
| pgstac.pgstac_settings | PgSTAC configuration |

---

## COMPLETE EXECUTION FLOW DIAGRAM

```
HTTP REQUEST (process_raster)
│
├─→ [1] submit_job_trigger.process_request()
│   ├─→ Extract: blob_name, container_name, raster_type, etc.
│   ├─→ validate_job_parameters() 
│   │   └─→ Check blob exists in storage (FAIL-FAST)
│   ├─→ generate_job_id() 
│   │   └─→ SHA256 hash of parameters
│   ├─→ Check existing job (idempotency)
│   ├─→ create_job_record()
│   │   └─→ INSERT INTO app.jobs (status=QUEUED, stage=1, total_stages=3)
│   ├─→ queue_job()
│   │   └─→ SEND to Service Bus: geospatial-jobs queue (stage 1)
│   └─→ RETURN HTTP 200 with job_id
│
├─→ [2] process_service_bus_job() ← Service Bus trigger
│   ├─→ Parse JobQueueMessage (job_id, job_type, stage=1)
│   └─→ core_machine.process_job_message()
│       │
│       ├─→ STAGE 1 TASK GENERATION
│       │   ├─→ Load ProcessRasterWorkflow class
│       │   ├─→ FETCH job record from database
│       │   ├─→ UPDATE job status: QUEUED → PROCESSING
│       │   ├─→ Call: ProcessRasterWorkflow.create_tasks_for_stage(stage=1, ...)
│       │   │   └─→ RETURN [Task 1: validate_raster with blob_url]
│       │   ├─→ Convert to TaskDefinition Pydantic objects
│       │   ├─→ SEND to Service Bus: geospatial-tasks queue (Task 1)
│       │   └─→ INSERT INTO app.tasks (task_id, task_type, status=QUEUED)
│       │
│       └─→ RETURN success result
│
├─→ [3] process_service_bus_task() ← Service Bus trigger
│   ├─→ Parse TaskQueueMessage (task_id, task_type=validate_raster)
│   ├─→ Get handler: services.validate_raster
│   │
│   ├─→ EXECUTE: validate_raster(parameters)
│   │   ├─→ Download raster from blob_url (with SAS token)
│   │   ├─→ Read with rasterio.open()
│   │   ├─→ Validate CRS (EPSG:32633)
│   │   ├─→ Detect raster type (DEM)
│   │   ├─→ Generate COG settings recommendations
│   │   └─→ RETURN {success: True, result: {...validation_data...}}
│   │
│   ├─→ Update task status: PROCESSING → COMPLETED
│   ├─→ Store result in app.tasks.result_data
│   └─→ Check: Is this the LAST task in Stage 1?
│       │
│       └─→ [ATOMIC CHECK - PostgreSQL Advisory Lock]
│           └─→ YES: Trigger stage advancement
│
├─→ [4] STAGE 1 → STAGE 2 ADVANCEMENT
│   ├─→ Fetch all Stage 1 task results
│   ├─→ Create new job message: stage=2
│   ├─→ SEND to Service Bus: geospatial-jobs queue (stage 2)
│   │
│   ├─→ process_service_bus_job() [SECOND INVOCATION]
│   │   ├─→ Create STAGE 2 TASKS
│   │   ├─→ Call: ProcessRasterWorkflow.create_tasks_for_stage(stage=2, previous_results=[Stage1Result])
│   │   │   ├─→ Extract: source_crs from Stage 1 result (EPSG:32633)
│   │   │   ├─→ Generate: output_blob_name (dem_cog_analysis.tif)
│   │   │   └─→ RETURN [Task 2: create_cog with stage 1 result data]
│   │   ├─→ SEND to Service Bus: geospatial-tasks queue (Task 2)
│   │   └─→ INSERT INTO app.tasks (task_id, task_type=create_cog)
│   │
│   └─→ RETURN success result
│
├─→ [5] EXECUTE TASK 2: create_cog
│   ├─→ process_service_bus_task() [SECOND INVOCATION]
│   ├─→ Get handler: services.create_cog
│   │
│   ├─→ EXECUTE: create_cog(parameters)
│   │   ├─→ Download source raster from bronze
│   │   ├─→ Use rio-cogeo.cog_translate():
│   │   │   ├─→ Reproject: EPSG:32633 → EPSG:4326
│   │   │   ├─→ Apply tier profile (DEFLATE for analysis)
│   │   │   ├─→ Generate overviews (bilinear resampling)
│   │   │   └─→ BAND interleave (cloud-native)
│   │   ├─→ Upload to silver container
│   │   └─→ RETURN {success: True, result: {...cog_metadata...}}
│   │
│   ├─→ Update task status: COMPLETED
│   ├─→ Store result: cog_blob, cog_container, size_mb, etc.
│   └─→ Check: Is this the LAST task in Stage 2?
│       └─→ [ATOMIC CHECK - PostgreSQL Advisory Lock]
│           └─→ YES: Trigger stage advancement
│
├─→ [6] STAGE 2 → STAGE 3 ADVANCEMENT
│   ├─→ Fetch Stage 2 task result (cog_blob, cog_container)
│   ├─→ Create new job message: stage=3
│   ├─→ SEND to Service Bus: geospatial-jobs queue (stage 3)
│   │
│   ├─→ process_service_bus_job() [THIRD INVOCATION]
│   │   ├─→ Create STAGE 3 TASKS
│   │   ├─→ Call: ProcessRasterWorkflow.create_tasks_for_stage(stage=3, previous_results=[Stage2Result])
│   │   │   ├─→ Extract: cog_blob (dem_cog_analysis.tif)
│   │   │   ├─→ Extract: cog_container (silver)
│   │   │   └─→ RETURN [Task 3: extract_stac_metadata with COG blob]
│   │   ├─→ SEND to Service Bus: geospatial-tasks queue (Task 3)
│   │   └─→ INSERT INTO app.tasks (task_id, task_type=extract_stac_metadata)
│   │
│   └─→ RETURN success result
│
├─→ [7] EXECUTE TASK 3: extract_stac_metadata
│   ├─→ process_service_bus_task() [THIRD INVOCATION]
│   ├─→ Get handler: services.extract_stac_metadata
│   │
│   ├─→ EXECUTE: extract_stac_metadata(parameters)
│   │   ├─→ Download COG from silver container
│   │   ├─→ Extract STAC metadata (bbox, CRS, bands, etc.)
│   │   ├─→ Create STAC Item JSON
│   │   ├─→ INSERT INTO pgstac.items (collection_id, item_id)
│   │   └─→ RETURN {success: True, result: {...stac_item...}}
│   │
│   ├─→ Update task status: COMPLETED
│   ├─→ Store result: item_id, collection_id, inserted_to_pgstac
│   └─→ Check: Is this the LAST task in Stage 3?
│       └─→ [ATOMIC CHECK - PostgreSQL Advisory Lock]
│           └─→ YES: ALL STAGES DONE - JOB COMPLETION
│
├─→ [8] JOB FINALIZATION
│   ├─→ No more stages (3 of 3 complete)
│   ├─→ Call: ProcessRasterWorkflow.finalize_job(context)
│   │   ├─→ Aggregate Stage 1 results (validation)
│   │   ├─→ Aggregate Stage 2 results (COG creation)
│   │   ├─→ Aggregate Stage 3 results (STAC metadata)
│   │   ├─→ Generate TiTiler URLs
│   │   └─→ RETURN {...aggregated_job_result...}
│   ├─→ UPDATE app.jobs: status=COMPLETED, result_data={...}
│   └─→ [JOB COMPLETE]
│
└─→ [9] RETRIEVE RESULTS
    ├─→ GET /api/jobs/status/{job_id}
    └─→ RETURN: {status: COMPLETED, result_data: {...final_results...}}
```

---

## KEY FILES REFERENCE

### Job Definition & Registration
| File | Lines | Purpose |
|------|-------|---------|
| jobs/process_raster.py | 62-97 | ProcessRasterWorkflow class definition |
| jobs/process_raster.py | 154-335 | validate_job_parameters() |
| jobs/process_raster.py | 337-347 | generate_job_id() |
| jobs/process_raster.py | 349-392 | create_job_record() |
| jobs/process_raster.py | 394-446 | queue_job() |
| jobs/process_raster.py | 448-620 | create_tasks_for_stage() **CRITICAL** |
| jobs/process_raster.py | 622-724 | finalize_job() |
| jobs/__init__.py | 64, 89 | Job registration in ALL_JOBS dict |

### HTTP Trigger & Job Submission
| File | Lines | Purpose |
|------|-------|---------|
| function_app.py | 566-569 | HTTP route: POST /api/jobs/submit/{job_type} |
| triggers/submit_job.py | 137-353 | JobSubmissionTrigger class |
| triggers/submit_job.py | 147-309 | process_request() method |
| triggers/submit_job.py | 311-349 | _get_controller_for_job_type() |

### Service Bus Job Queueing
| File | Lines | Purpose |
|------|-------|---------|
| function_app.py | 1921-2030 | @app.service_bus_queue_trigger for jobs queue |
| core/machine.py | 312-546 | CoreMachine.process_job_message() |
| core/machine.py | 409-472 | Task generation and queuing |

### Service Bus Task Processing
| File | Lines | Purpose |
|------|-------|---------|
| function_app.py | 2032+ | @app.service_bus_queue_trigger for tasks queue |
| core/machine.py | 552+ | CoreMachine.process_task_message() |
| services/__init__.py | 79-80, 115-116 | Task handler registration |

### Stage 1: Raster Validation
| File | Lines | Purpose |
|------|-------|---------|
| services/raster_validation.py | 118+ | validate_raster() handler |
| services/__init__.py | 79, 115 | Handler registration as "validate_raster" |

### Stage 2: COG Creation
| File | Lines | Purpose |
|------|-------|---------|
| services/raster_cog.py | 60+ | create_cog() handler |
| services/__init__.py | 80, 116 | Handler registration as "create_cog" |

### Stage 3: STAC Metadata
| File | Lines | Purpose |
|------|-------|---------|
| services/stac_catalog.py | 100+ | extract_stac_metadata() handler |
| services/__init__.py | 76, 112 | Handler registration as "extract_stac_metadata" |

### Database Models
| File | Lines | Purpose |
|------|-------|---------|
| core/models/job.py | 50-86 | JobRecord Pydantic model |
| core/models/task.py | 49-86 | TaskRecord Pydantic model |
| core/models/enums.py | - | JobStatus, TaskStatus enums |

### Database Operations
| File | Lines | Purpose |
|------|-------|---------|
| core/state_manager.py | 64+ | StateManager for all DB operations |
| infrastructure/repositories/job_repo.py | - | Job CRUD operations |
| infrastructure/repositories/task_repo.py | - | Task CRUD operations |

### Configuration
| File | Lines | Purpose |
|------|-------|---------|
| config/__init__.py | - | get_config() for runtime settings |
| config/raster_config.py | - | Raster-specific configuration |
| config/storage_config.py | - | Storage container names |

---

## EXECUTION FLOW TIMING

| Stage | Component | Typical Duration | Notes |
|-------|-----------|------------------|-------|
| Submit | HTTP Trigger | 100-500ms | Validation + DB write + queue send |
| Queue → Processing | Service Bus | 100-2000ms | Message pickup, deserialization |
| Stage 1 | validate_raster | 2-10s | Blob download + rasterio analysis |
| Stage Advancement | CoreMachine | 100-500ms | Result fetch + task generation + queue send |
| Stage 2 | create_cog | 15-60s | Blob download + rio-cogeo reprojection + upload |
| Stage 2 → 3 | CoreMachine | 100-500ms | Result fetch + task generation + queue send |
| Stage 3 | extract_stac_metadata | 5-30s | COG download + metadata extraction + DB insert |
| Finalization | CoreMachine | 100-500ms | Result aggregation + job completion |
| **Total** | All stages | **25-120 seconds** | Depends on file size and network latency |

---

## ERROR HANDLING & RECOVERY

### Contract Violations (Programming Bugs)
- **Type**: ContractViolationError
- **Handling**: NEVER caught - bubble up to crash function
- **Examples**: Wrong return type from create_tasks_for_stage, missing required field

### Business Logic Errors (Expected Runtime Failures)
- **Types**: ResourceNotFoundError, ValidationError, ServiceBusError
- **Handling**: Caught and logged, job marked FAILED
- **Examples**: Blob doesn't exist, invalid CRS, Service Bus unavailable

### Task Retry Logic
- **Retryable**: IOError, TimeoutError, ConnectionError, ServiceBusError
- **Non-retryable**: ValueError, TypeError, KeyError, ResourceNotFoundError
- **Max retries**: Configurable per deployment

---

## IDEMPOTENCY GUARANTEE

**Process**: 
1. Same parameters → same job_id (SHA256 hash)
2. Job creation is idempotent:
   - First submission: Creates job, queues for processing, returns job_id
   - Duplicate submission: Returns existing job (if completed) or status (if in-progress)
3. No duplicate work performed

**Example**:
```bash
# First request
curl POST /api/jobs/submit/process_raster -d '{"blob_name": "dem.tif"}'
→ {"job_id": "a3c7f8e2...", "status": "created", ...}

# Second request with SAME parameters
curl POST /api/jobs/submit/process_raster -d '{"blob_name": "dem.tif"}'
→ {"job_id": "a3c7f8e2...", "status": "already_completed", ...}  # Idempotent!
```

---

## KEY ARCHITECTURAL DECISIONS

### 1. Three-Stage Pipeline
**Why**: Separation of concerns
- Stage 1: Validation (discover metadata)
- Stage 2: Processing (transformation)
- Stage 3: Cataloging (STAC registration)

### 2. CoreMachine Universal Orchestrator
**Why**: Composition over inheritance
- One orchestrator for ALL job types
- Job classes define stages, CoreMachine executes them
- Reduces code duplication and coupling

### 3. PostgreSQL Advisory Locks
**Why**: Atomic "last task turns out lights" pattern
- Prevents race conditions when multiple tasks complete simultaneously
- Atomic SQL operation determines which task triggers stage advancement

### 4. Service Bus for Queueing
**Why**: Reliable message delivery at scale
- FIFO ordering (important for stage advancement)
- Dead letter queue for poison messages
- Automatic retry with exponential backoff

### 5. Fail-Fast Parameter Validation
**Why**: Catch errors before queuing
- Check blob existence during submission (not during processing)
- Provides immediate feedback to user
- Prevents wasted resource allocation

---

## DEBUGGING CHECKLIST

**Job submitted but not processing?**
1. Check Service Bus queue depth: `geospatial-jobs` queue
2. Verify job status: `GET /api/jobs/status/{job_id}`
3. Check Application Insights logs for exceptions

**Task failing?**
1. Check task status in database: `SELECT * FROM app.tasks WHERE job_id = ...`
2. Review task error_details field
3. Search Application Insights for task_id

**Stage not advancing?**
1. Verify all previous stage tasks are COMPLETED
2. Check for advisory lock deadlocks in PostgreSQL
3. Review CoreMachine logs for stage advancement logic

**Blob not found?**
1. Verify container name spelling
2. Check blob_name path format
3. Ensure blob actually exists in Azure Storage

---

**Document Generated**: 24 NOV 2025  
**Last Updated**: 24 NOV 2025  
**Version**: 1.0 - Complete

