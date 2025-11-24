# PROCESS_RASTER_COLLECTION WORKFLOW - COMPLETE TRACE-THROUGH

**Date Created**: 24 NOV 2025  
**Last Reviewed**: 24 NOV 2025  
**Status**: PRODUCTION READY (Tested 21 NOV 2025 with multi-tile vendor deliveries)  
**Document Type**: Comprehensive execution flow trace with code snippets  

---

## TABLE OF CONTENTS

1. [Overview & Architecture](#overview--architecture)
2. [Entry Point: HTTP Submission](#entry-point-http-submission)
3. [Job Definition](#job-definition)
4. [Job Submission Flow](#job-submission-flow)
5. [Service Bus Queuing](#service-bus-queuing)
6. [CoreMachine Job Processing](#coremachine-job-processing)
7. [Stage 1: Parallel Raster Validation](#stage-1-parallel-raster-validation)
8. [Stage 2: Parallel COG Creation](#stage-2-parallel-cog-creation)
9. [Stage 3: MosaicJSON Aggregation](#stage-3-mosaicjson-aggregation)
10. [Stage 4: STAC Collection Creation](#stage-4-stac-collection-creation)
11. [Job Completion & Finalization](#job-completion--finalization)
12. [Database Schema](#database-schema)
13. [Error Handling](#error-handling)

---

## OVERVIEW & ARCHITECTURE

### What is process_raster_collection?

A four-stage workflow for processing **raster tile collections** (multi-tile vendor deliveries) to:
- **Stage 1**: Validate all tiles in parallel
- **Stage 2**: Create Cloud Optimized GeoTIFFs (COGs) in parallel
- **Stage 3**: Generate MosaicJSON virtual mosaic (aggregation)
- **Stage 4**: Create STAC collection item (metadata)

**Use Case**: Convert vendor tile deliveries (e.g., 100 TIF files) → COG collection + MosaicJSON + pgSTAC searchable collection

### Four-Stage Architecture

```
HTTP Request
     ↓
[submit_job trigger] ← POST /api/jobs/process_raster_collection
     ↓
Validate parameters → Generate job ID (SHA256 hash)
     ↓
Create JobRecord → Queue to Service Bus
     ↓
CoreMachine processes JobQueueMessage
     ↓
Stage 1: validate_raster (parallel - N tasks, one per tile)
     ↓ [Previous results extracted]
Stage 2: create_cog (parallel - N tasks, one per tile)
     ↓ [All results aggregated by CoreMachine]
Stage 3: create_mosaicjson (fan_in - 1 task, receives all Stage 2 results)
     ↓ [MosaicJSON result passed]
Stage 4: create_stac_collection (fan_in - 1 task, receives MosaicJSON)
     ↓
finalize_job() → Return summary with TiTiler URLs
```

---

## ENTRY POINT: HTTP SUBMISSION

### HTTP Endpoint

```
POST /api/jobs/process_raster_collection
Content-Type: application/json

{
  "blob_list": ["tile_1.tif", "tile_2.tif", ..., "tile_100.tif"],
  "collection_id": "namangan_2019_tiles",
  "collection_description": "Namangan satellite tiles 2019",
  "container_name": "rmhazuregeo-rasters",
  "raster_type": "rgb",
  "output_tier": "analysis",
  "maxzoom": 18
}
```

### Route Registration

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/function_app.py`  
**Lines**: ~350-370 (estimated)

```python
@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP endpoint for job submission."""
    return submit_job_trigger.handle_request(req)
```

### Trigger Class

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/triggers/submit_job.py`  
**Lines**: 137-349

The `JobSubmissionTrigger` class orchestrates the entire job submission flow:

```python
class JobSubmissionTrigger(JobManagementTrigger):
    """Job submission HTTP trigger implementation."""
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Process job submission request.
        
        Flow:
        1. Extract job_type from URL path
        2. Extract and validate JSON request body
        3. Get controller for job_type from ALL_JOBS registry
        4. Call controller.validate_job_parameters()  [Interface Contract #1]
        5. Call controller.generate_job_id()          [Interface Contract #2]
        6. Check for existing job (idempotency)
        7. Call controller.create_job_record()        [Interface Contract #3]
        8. Call controller.queue_job()                [Interface Contract #4]
        9. Return success response
        """
```

---

## JOB DEFINITION

### Job Class Definition

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/jobs/process_raster_collection.py`  
**Lines**: 74-906

#### Class Header
```python
class ProcessRasterCollectionWorkflow(JobBase):
    """
    Multi-tile raster collection processing workflow with MosaicJSON.

    Stages:
    1. Validate: Parallel validation of all tiles
    2. Create COGs: Parallel COG creation
    3. Create MosaicJSON: Aggregate COGs into virtual mosaic
    4. Create STAC Collection: Collection-level STAC item
    """

    job_type: str = "process_raster_collection"
    description: str = "Process raster tile collection to COGs with MosaicJSON"
```

#### Stage Definitions (Lines 88-117)

```python
stages: List[Dict[str, Any]] = [
    {
        "number": 1,
        "name": "validate_tiles",
        "task_type": "validate_raster",
        "description": "Validate all tiles in parallel",
        "parallelism": "single"  # Orchestration-time parallelism (N from blob_list)
    },
    {
        "number": 2,
        "name": "create_cogs",
        "task_type": "create_cog",
        "description": "Create COGs from all tiles in parallel",
        "parallelism": "fan_out"  # Result-driven parallelism (N from Stage 1 results)
    },
    {
        "number": 3,
        "name": "create_mosaicjson",
        "task_type": "create_mosaicjson",
        "description": "Generate MosaicJSON from COG collection",
        "parallelism": "fan_in"  # Auto-aggregation (CoreMachine creates task)
    },
    {
        "number": 4,
        "name": "create_stac_collection",
        "task_type": "create_stac_collection",
        "description": "Create STAC collection item with MosaicJSON asset",
        "parallelism": "fan_in"  # Auto-aggregation (CoreMachine creates task)
    }
]
```

#### Parameters Schema (Lines 119-224)

**Key Parameters**:
- `blob_list` (list, required): Paths to raster tiles in container
- `collection_id` (str, required): Unique collection identifier
- `collection_description` (str, optional): Human-readable description
- `container_name` (str): Source container (defaults to config)
- `output_container` (str): COG output container (defaults to config)
- `mosaicjson_container` (str): MosaicJSON output container (defaults to config)
- `raster_type` (str): Auto-detected or user-specified (auto/rgb/rgba/dem/categorical/multispectral/nir)
- `output_tier` (str): COG tier (visualization/analysis/archive) - only one for collections
- `target_crs` (str): Target projection (defaults to EPSG:4326)
- `maxzoom` (int): MosaicJSON max zoom level (0-24, default 19)
- `create_mosaicjson` (bool): Generate MosaicJSON file (default: True)
- `create_stac_collection` (bool): Create STAC collection (default: True)

---

## JOB SUBMISSION FLOW

### Step 1: Parameter Validation

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/jobs/process_raster_collection.py`  
**Method**: `validate_job_parameters()` (Lines 226-440)  
**Called by**: `triggers/submit_job.py` (Line 217)

```python
@staticmethod
def validate_job_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate job parameters against schema.
    
    Validates:
    - blob_list: Non-empty list of 2+ items
    - collection_id: Required string
    - collection_description: Auto-generated if not provided
    - Containers: Validated against Azure storage (exist check)
    - All blobs: Exist in container (fail-fast, report all missing)
    - Raster type: One of allowed values
    - Output tier: One of allowed values (no "all" for collections)
    - CRS, zoom levels, etc.
    
    Returns: Validated parameters dict with defaults applied
    Raises: ValueError for invalid params, ResourceNotFoundError for missing blobs
    """
```

**Example Validation Logic** (Line 244-251):
```python
# Validate blob_list
blob_list = params.get("blob_list")
if not blob_list or not isinstance(blob_list, list):
    raise ValueError("blob_list must be a non-empty list")
if len(blob_list) < 2:
    raise ValueError("Collection must contain at least 2 tiles")
if not all(isinstance(b, str) for b in blob_list):
    raise ValueError("All blob_list items must be strings")
validated["blob_list"] = blob_list
```

**Container & Blob Validation** (Lines 407-438):
```python
from azure.core.exceptions import ResourceNotFoundError
from infrastructure.blob import BlobRepository

blob_repo = BlobRepository.instance()
container_name = validated["container_name"]
blob_list = validated["blob_list"]

# Validate container exists
if not blob_repo.container_exists(container_name):
    raise ResourceNotFoundError(
        f"Container '{container_name}' does not exist..."
    )

# Validate ALL blobs in collection exist (fail-fast, report all missing)
missing_blobs = []
for blob_name in blob_list:
    if not blob_repo.blob_exists(container_name, blob_name):
        missing_blobs.append(blob_name)

if missing_blobs:
    # Report ALL missing blobs in error message
    missing_list = "\n  - ".join(missing_blobs)
    raise ResourceNotFoundError(
        f"Collection validation failed: {len(missing_blobs)} file(s) not found..."
    )
```

### Step 2: Generate Job ID (Idempotency)

**Method**: `generate_job_id()` (Lines 442-452)  
**Called by**: `triggers/submit_job.py` (Line 228)

```python
@staticmethod
def generate_job_id(params: dict) -> str:
    """
    Generate deterministic job ID from parameters.
    
    Same parameters = same job ID (idempotency).
    
    Uses: SHA256 hash of sorted JSON parameters
    Result: Hex string (64 characters)
    """
    import hashlib
    import json
    
    param_str = json.dumps(params, sort_keys=True)
    job_hash = hashlib.sha256(param_str.encode()).hexdigest()
    return job_hash
```

**Idempotency Pattern** (Lines 231-266 in submit_job.py):
```python
# Check if job already exists
existing_job = repos['job_repo'].get_job(job_id)

if existing_job:
    if existing_job.status.value == 'completed':
        # Return existing results without re-running
        return {
            "job_id": job_id,
            "status": "already_completed",
            "result_data": existing_job.result_data,
            "idempotent": True
        }
    else:
        # Job in progress - return current status
        return {
            "job_id": job_id,
            "status": existing_job.status.value,
            "current_stage": existing_job.stage,
            "total_stages": existing_job.total_stages,
            "idempotent": True
        }
```

### Step 3: Create Job Record

**Method**: `create_job_record()` (Lines 454-500)  
**Called by**: `triggers/submit_job.py` (Line 280)

```python
@staticmethod
def create_job_record(job_id: str, params: dict) -> dict:
    """
    Create job record for database storage.
    
    Creates JobRecord Pydantic model with:
    - job_id: Generated ID
    - job_type: "process_raster_collection"
    - status: JobStatus.QUEUED
    - stage: 1
    - total_stages: 4
    - Metadata: collection_id, tile_count, containers, etc.
    
    Persists to PostgreSQL app.jobs table via job_repo.
    """
    from infrastructure import RepositoryFactory
    from core.models import JobRecord, JobStatus

    job_record = JobRecord(
        job_id=job_id,
        job_type="process_raster_collection",
        parameters=params,
        status=JobStatus.QUEUED,
        stage=1,
        total_stages=4,
        stage_results={},
        metadata={
            "description": "Process raster collection to COGs with MosaicJSON and STAC",
            "created_by": "ProcessRasterCollectionWorkflow",
            "collection_id": params.get("collection_id"),
            "tile_count": len(params.get("blob_list", [])),
            "container_name": params.get("container_name"),
            "output_container": params.get("output_container"),
            "mosaicjson_container": params.get("mosaicjson_container"),
            "target_crs": params.get("target_crs"),
            "output_tier": params.get("output_tier", "analysis"),
            "output_folder": params.get("output_folder"),
            "stac_item_id": params.get("stac_item_id")
        }
    )

    # Persist to database
    repos = RepositoryFactory.create_repositories()
    job_repo = repos['job_repo']
    job_repo.create_job(job_record)

    return job_record.model_dump()
```

**Database Table**: `app.jobs`
**Columns**:
- `job_id` (text, primary key)
- `job_type` (text): "process_raster_collection"
- `status` (enum): QUEUED → PROCESSING → COMPLETED or FAILED
- `stage` (integer): Current stage (1-4)
- `total_stages` (integer): 4
- `parameters` (jsonb): Full validated parameters
- `stage_results` (jsonb): Per-stage aggregated results
- `result_data` (jsonb): Final finalized job results
- `metadata` (jsonb): Job metadata
- `created_at` (timestamp): Creation time
- `updated_at` (timestamp): Last update time

### Step 4: Queue Job for Processing

**Method**: `queue_job()` (Lines 501-553)  
**Called by**: `triggers/submit_job.py` (Line 293)

```python
@staticmethod
def queue_job(job_id: str, params: dict) -> dict:
    """
    Queue job for processing using Service Bus.
    
    Creates JobQueueMessage and sends to Service Bus jobs queue.
    This triggers CoreMachine to process the job.
    
    Returns: Queue confirmation with message_id
    """
    from infrastructure.service_bus import ServiceBusRepository
    from core.schema.queue import JobQueueMessage
    from config import get_config
    import uuid

    config = get_config()
    queue_name = config.service_bus_jobs_queue  # "jobs" queue

    service_bus_repo = ServiceBusRepository()
    
    correlation_id = str(uuid.uuid4())[:8]
    job_message = JobQueueMessage(
        job_id=job_id,
        job_type="process_raster_collection",
        stage=1,
        parameters=params,
        correlation_id=correlation_id
    )

    # Send to Service Bus jobs queue
    message_id = service_bus_repo.send_message(queue_name, job_message)

    return {
        "queued": True,
        "queue_type": "service_bus",
        "queue_name": queue_name,
        "message_id": message_id,
        "job_id": job_id
    }
```

**Service Bus Message Structure**:
```python
class JobQueueMessage(BaseModel):
    job_id: str
    job_type: str = "process_raster_collection"
    stage: int = 1
    parameters: dict
    correlation_id: str  # For tracing
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

---

## SERVICE BUS QUEUING

### Message Queue

**Queue Name**: Determined by config (typically `jobs`)  
**Queue Type**: Azure Service Bus  
**Message Lifetime**: Default 14 days (configurable)

**Message Contents**:
```json
{
  "job_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6...",
  "job_type": "process_raster_collection",
  "stage": 1,
  "correlation_id": "a1b2c3d4",
  "parameters": {
    "blob_list": ["tile_1.tif", "tile_2.tif", ...],
    "collection_id": "namangan_2019_tiles",
    ...
  },
  "timestamp": "2025-11-24T12:00:00.000Z"
}
```

### Queue Processing Trigger

**File**: `function_app.py` (estimated ~420 lines)

```python
@app.queue_trigger(
    arg_name="job_message",
    queue_name="jobs"
)
def process_jobs_queue(job_message: func.InputStream) -> None:
    """
    Queue trigger that processes job messages from Service Bus.
    
    Invoked by Azure Functions runtime when message arrives in jobs queue.
    Deserializes message and passes to CoreMachine for processing.
    """
    message_body = job_message.read().decode('utf-8')
    job_msg = JobQueueMessage.parse_raw(message_body)
    
    # CoreMachine processes the job
    core_machine.process_job_message(job_msg)
```

---

## COREMACHINE JOB PROCESSING

### Job Processing Entry Point

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/core/machine.py`  
**Method**: `process_job_message()` (Lines 312+)

```python
def process_job_message(self, job_message: JobQueueMessage) -> Dict[str, Any]:
    """
    Process job from queue message.
    
    Flow:
    1. Extract job_id and load JobRecord from database
    2. For current stage: Call job.create_tasks_for_stage()
    3. Persist tasks to database
    4. Queue tasks to Service Bus
    5. Update job status to PROCESSING
    
    When all tasks complete (via "last task turns out lights"):
    1. Aggregate stage results
    2. Advance to next stage (if more stages exist)
    3. On final stage completion: Call job.finalize_job()
    """
```

### Stage Task Creation

**For process_raster_collection**:
- Stage 1: `create_tasks_for_stage(stage=1)` returns list of validate_raster tasks
- Stage 2: `create_tasks_for_stage(stage=2, previous_results=...)` returns list of create_cog tasks
- Stage 3: `create_tasks_for_stage(stage=3)` returns empty list (fan_in - CoreMachine auto-creates)
- Stage 4: `create_tasks_for_stage(stage=4)` returns empty list (fan_in - CoreMachine auto-creates)

---

## STAGE 1: PARALLEL RASTER VALIDATION

### Task Creation

**Method**: `_create_stage_1_tasks()` (Lines 591-643)

```python
@staticmethod
def _create_stage_1_tasks(
    job_id: str,
    job_params: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Stage 1: Create validation tasks for all tiles (fan-out).
    
    One task per tile in blob_list.
    Each task calls validate_raster handler with SAS URL.
    """
    from infrastructure.blob import BlobRepository

    tasks = []
    blob_list = job_params["blob_list"]
    container_name = job_params["container_name"]

    blob_repo = BlobRepository.instance()

    for i, blob_name in enumerate(blob_list):
        # Generate SAS URL for Azure authentication (1-hour validity)
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=container_name,
            blob_name=blob_name,
            hours=1
        )

        task = {
            "task_id": f"{job_id[:8]}-s1-validate-{i}",
            "task_type": "validate_raster",
            "parameters": {
                "blob_url": blob_url,           # REQUIRED by validate_raster handler
                "blob_name": blob_name,
                "container_name": container_name,
                "input_crs": job_params.get("input_crs"),
                "raster_type": job_params.get("raster_type", "auto"),
                "strict_mode": False,
                "_skip_validation": False
            },
            "metadata": {
                "tile_index": i,
                "tile_count": len(blob_list),
                "blob_name": blob_name,
                "collection_id": job_params["collection_id"]
            }
        }
        tasks.append(task)

    return tasks
```

**Example**: For 100 tiles, creates 100 tasks with IDs like:
- `a1b2c3d4-s1-validate-0`
- `a1b2c3d4-s1-validate-1`
- ...
- `a1b2c3d4-s1-validate-99`

### Validation Handler

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_validation.py`  
**Function**: `validate_raster()` (Lines 118+)

```python
def validate_raster(params: dict) -> dict:
    """
    Validate raster file for COG pipeline processing.
    
    Checks:
    1. File readability (can open with rasterio)
    2. CRS presence and validity (EPSG code or WKT)
    3. Bit-depth efficiency (flags 64-bit as CRITICAL)
    4. Raster type detection (RGB/RGBA/DEM/categorical/multispectral)
    5. Type mismatch validation (user vs detected)
    6. Bounds sanity checks
    7. Optimal COG settings recommendation
    8. COG tier compatibility (visualization/analysis/archive)
    
    Returns:
    {
        "success": True,
        "result": {
            "valid": True,
            "source_crs": "EPSG:4326",
            "crs_source": "file_metadata",
            "bounds": [-180, -90, 180, 90],
            "shape": [1000, 1000],
            "band_count": 3,
            "dtype": "uint8",
            "raster_type": {
                "detected_type": "rgb",
                "confidence": "HIGH",
                "optimal_cog_settings": {
                    "compression": "jpeg",
                    "jpeg_quality": 85,
                    "overview_resampling": "cubic"
                }
            },
            "cog_tiers": {
                "applicable_tiers": ["visualization", "analysis", "archive"],
                "total_compatible": 3
            }
        }
    }
    """
```

### Task Queue for Execution

**Queue Name**: `tasks`  
**Type**: Service Bus  

Each validation task is sent to the tasks queue for parallel execution.

### Parallel Execution

CoreMachine queues all 100 tasks to the tasks queue immediately. Azure Functions runtime processes them in parallel based on concurrency settings.

**For 100 tiles**:
- If concurrency = 10, processes 10 tiles at a time
- Each takes ~30-60 seconds to validate
- Total Stage 1 time: ~300-600 seconds (parallel benefit)

### Stage 1 Completion

"Last task turns out lights" pattern:
- When the 100th task completes, it triggers stage advancement
- CoreMachine collects all 100 result_data dicts
- Stores aggregated results in `job.stage_results[1]`
- Advances job to stage=2

---

## STAGE 2: PARALLEL COG CREATION

### Task Creation

**Method**: `_create_stage_2_tasks()` (Lines 646-751)

```python
@staticmethod
def _create_stage_2_tasks(
    job_id: str,
    job_params: Dict[str, Any],
    previous_results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Stage 2: Create COG tasks for all validated tiles (fan-out).
    
    Receives Stage 1 results and creates one create_cog task per validated tile.
    
    Key Flow:
    1. Check that all validations succeeded
    2. For each validation result, extract source_crs
    3. Create create_cog task with validation metadata
    4. Generate SAS URL for input raster
    5. Determine output blob name (with optional folder structure)
    """
    
    # Check that all validations succeeded
    failed_validations = [
        r for r in previous_results
        if not r.get("success", False)
    ]
    if failed_validations:
        raise ValueError(
            f"{len(failed_validations)} tiles failed validation. "
            f"Cannot proceed to COG creation."
        )

    from infrastructure.blob import BlobRepository

    tasks = []
    blob_list = job_params["blob_list"]
    container_name = job_params["container_name"]
    blob_repo = BlobRepository.instance()

    for i, blob_name in enumerate(blob_list):
        # Get validation result for this tile
        # previous_results[i] IS the result_data dict from Stage 1
        validation_result_data = previous_results[i]
        validation_result = validation_result_data.get("result", {})

        # Extract source CRS from validation (REQUIRED)
        source_crs = validation_result.get("source_crs")
        if not source_crs:
            raise ValueError(f"No source_crs found in validation result for {blob_name}")

        # Extract tile identifier from blob name
        tile_name = blob_name.split('/')[-1].replace('.tif', '').replace('.TIF', '')

        # Generate SAS URL (1-hour validity)
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=container_name,
            blob_name=blob_name,
            hours=1
        )

        # Extract raster_type dict and recommended settings from validation
        raster_type_dict = validation_result.get("raster_type", {})
        recommended_compression = validation_result.get("recommended_compression", "DEFLATE")
        recommended_resampling = validation_result.get("recommended_resampling", "bilinear")

        # Determine output blob name
        output_folder = job_params.get("output_folder")
        if output_folder:
            output_blob_name = f"{output_folder}/{tile_name}.tif"
        else:
            output_blob_name = f"{tile_name}.tif"

        task = {
            "task_id": f"{job_id[:8]}-s2-cog-{i}",
            "task_type": "create_cog",
            "parameters": {
                "blob_url": blob_url,
                "blob_name": blob_name,
                "container_name": container_name,
                "source_crs": source_crs,          # REQUIRED by create_cog handler
                "target_crs": job_params.get("target_crs", "EPSG:4326"),
                "raster_type": raster_type_dict,  # Full dict from validation
                "output_blob_name": output_blob_name,  # REQUIRED by create_cog handler
                "output_tier": job_params.get("output_tier", "analysis"),
                "output_container": job_params.get("output_container"),
                "compression": recommended_compression,
                "jpeg_quality": job_params.get("jpeg_quality", 85),
                "overview_resampling": recommended_resampling,
                "reproject_resampling": recommended_resampling,
                "in_memory": job_params.get("in_memory", True)
            },
            "metadata": {
                "tile_index": i,
                "tile_count": len(blob_list),
                "tile_name": tile_name,
                "collection_id": job_params["collection_id"],
                "validation_result": validation_result
            }
        }
        tasks.append(task)

    return tasks
```

### COG Creation Handler

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_cog.py`  
**Function**: `create_cog()` (Lines 60+)

```python
def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF with optional reprojection.
    
    Single-pass operation using rio-cogeo:
    1. Download source raster from Azure Blob (via SAS URL)
    2. Reproject + create COG in one pass (if CRS differs)
    3. Create overviews for fast zoom level access
    4. Upload to silver container
    5. Clean up temporary files
    
    Returns:
    {
        "success": True,
        "result": {
            "cog_blob": "tile_name_analysis.tif",    # ← KEY FIELD for Stage 3
            "cog_container": "silver-cogs",           # ← Container name for MosaicJSON
            "cog_tier": "analysis",
            "source_blob": "tile_name.tif",
            "source_crs": "EPSG:3857",
            "target_crs": "EPSG:4326",
            "bounds_4326": [-180, -90, 180, 90],
            "shape": [1000, 1000],
            "size_mb": 42.5,
            "compression": "deflate",
            "overview_levels": [2, 4, 8, 16],
            "processing_time_seconds": 45.2
        }
    }
    
    Error Return:
    {
        "success": False,
        "error": "Error message",
        "error_type": "ValueError"
    }
    """
```

**Key Implementation Details**:
- Uses `rio_cogeo.cog_translate()` for single-pass operation
- Supports BAND interleave for cloud-native access
- Type-specific compression:
  - RGB: JPEG (97% reduction)
  - RGBA: WebP (supports alpha channel)
  - DEM: LERC+DEFLATE (lossless scientific)
  - Categorical: DEFLATE (preserves classes)
  - Multispectral: DEFLATE (lossless)

### Stage 2 Completion

When all COG tasks complete:
- CoreMachine collects all 100 result_data dicts
- Stores aggregated results in `job.stage_results[2]`
- Each result contains `result.cog_blob` and `result.cog_container`
- Advances job to stage=3

**Example Result Structure**:
```json
{
  "success": true,
  "result": {
    "cog_blob": "tile_1_analysis.tif",
    "cog_container": "silver-cogs",
    "size_mb": 42.5,
    ...
  }
}
```

---

## STAGE 3: MOSAICJSON AGGREGATION

### Fan-In Pattern

Stage 3 uses **fan_in** parallelism:
- Job definition specifies: `"parallelism": "fan_in"`
- `create_tasks_for_stage(stage=3)` returns **empty list** `[]`
- CoreMachine automatically creates **1 aggregation task** that receives all Stage 2 results

### Auto-Created Aggregation Task

CoreMachine logic (pseudo-code):
```python
# In CoreMachine.process_job_message() for fan_in stage
if stage_definition["parallelism"] == "fan_in":
    # Don't call job.create_tasks_for_stage()
    # Instead, auto-create aggregation task
    
    aggregation_task = {
        "task_id": f"{job_id[:8]}-s3-aggregate",
        "task_type": "create_mosaicjson",
        "parameters": {
            "previous_results": [100 Stage 2 result_data dicts],
            "job_parameters": job_params
        }
    }
    
    # Queue single task with all previous results
    self.queue_tasks([aggregation_task])
```

### MosaicJSON Handler

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/raster_mosaicjson.py`  
**Function**: `create_mosaicjson()` (Lines 46+)

```python
def create_mosaicjson(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create MosaicJSON from COG collection (fan_in task handler).
    
    Receives all Stage 2 COG results via params["previous_results"].
    
    Args:
        params: {
            "previous_results": [
                {
                    "success": True,
                    "result": {
                        "cog_blob": "path/to/tile_1_analysis.tif",
                        "cog_container": "silver-cogs",
                        ...
                    }
                },
                ...  # 100 items total
            ],
            "job_parameters": {
                "collection_id": "namangan_2019_tiles",
                "mosaicjson_container": "silver-tiles",
                "cog_container": "silver-cogs",
                "maxzoom": 19,
                ...
            }
        }
    
    Returns:
    {
        "success": True,
        "mosaicjson_blob": "mosaics/namangan_2019_tiles.json",
        "mosaicjson_url": "https://..../namangan_2019_tiles.json?sv=...",
        "tile_count": 100,
        "bounds": [-73.5, 39.8, -73.2, 40.1],
        "minzoom": 8,
        "maxzoom": 19,
        "quadkey_count": 4521,
        "center": [-73.35, 39.95, 13],
        "cog_blobs": ["tile_1_analysis.tif", "tile_2_analysis.tif", ...]
    }
    """
```

**Implementation Details**:
- Extracts COG blob paths from Stage 2 results
- Creates MosaicJSON using cogeo-mosaic library
- Quadkey-based spatial indexing (client-side tile selection)
- Auto-calculates zoom levels based on tile resolution
- Uploads MosaicJSON to silver-tiles container
- Generates SAS URL for MosaicJSON file

### Stage 3 Completion

When aggregation task completes:
- CoreMachine collects result_data with MosaicJSON metadata
- Stores in `job.stage_results[3]`
- Advances job to stage=4

---

## STAGE 4: STAC COLLECTION CREATION

### Auto-Created Fan-In Task

Similar to Stage 3, CoreMachine auto-creates 1 task:
```python
aggregation_task = {
    "task_id": f"{job_id[:8]}-s4-stac",
    "task_type": "create_stac_collection",
    "parameters": {
        "previous_results": [Stage 3 MosaicJSON result],
        "job_parameters": job_params
    }
}
```

### STAC Collection Handler

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/stac_collection.py`  
**Function**: `create_stac_collection()` (Lines 60+)

```python
def create_stac_collection(
    params: dict,
    context: dict = None
) -> dict:
    """
    Create STAC collection (fan_in task handler).
    
    Receives Stage 3 MosaicJSON result.
    Creates STAC Collection item and inserts to pgSTAC collections table.
    
    Args:
        params: {
            "previous_results": [
                {
                    "success": True,
                    "mosaicjson_blob": "mosaics/namangan_2019_tiles.json",
                    "mosaicjson_url": "https://...",
                    "bounds": [-73.5, 39.8, -73.2, 40.1],
                    "cog_blobs": [...],
                    ...
                }
            ],
            "job_parameters": {
                "collection_id": "namangan_2019_tiles",
                "collection_description": "Namangan satellite tiles 2019",
                "stac_item_id": "namangan_2019",
                ...
            }
        }
    
    Returns:
    {
        "success": True,
        "collection_id": "namangan_2019_tiles",
        "stac_id": "namangan_2019",
        "pgstac_id": 12345,
        "inserted_to_pgstac": True,
        "search_id": "search_12345",
        "viewer_url": "https://titiler.../search/{search_id}",
        "tilejson_url": "https://titiler.../search/{search_id}/tilejson.json",
        "tiles_url": "https://titiler.../search/{search_id}/tiles/{z}/{x}/{y}.png",
        "items_created": 100,
        "items_failed": 0
    }
    """
```

**STAC Pattern** (NEW 11 NOV 2025):
- Creates STAC Items for each COG tile (searchable, with geometry/datetime)
- Creates STAC Collection with MosaicJSON as primary asset
- Items linked to Collection via `collection_id` field
- Inserts to PgSTAC `collections` and `items` tables

**PgSTAC Registration** (NEW 17 NOV 2025 - Option A):
- Direct database registration via PgSTACSearchRegistration
- Creates pgSTAC search record that can be served by TiTiler
- Returns search_id that enables visualization URLs

### Stage 4 Completion

When STAC collection task completes:
- CoreMachine collects result_data with STAC metadata
- Stores in `job.stage_results[4]`
- Detects final stage complete (stage == total_stages)
- Calls `job.finalize_job(context)` to create final summary

---

## JOB COMPLETION & FINALIZATION

### Finalize Job Method

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/jobs/process_raster_collection.py`  
**Method**: `finalize_job()` (Lines 754-905)

```python
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Create final job summary from all completed tasks.
    
    Extracts:
    - Per-tile COG statistics (Stage 2)
    - MosaicJSON metadata (Stage 3)
    - STAC collection details (Stage 4)
    - TiTiler visualization URLs
    
    Args:
        context: JobExecutionContext with:
            - job_id: Job identifier
            - current_stage: Final stage (4)
            - parameters: Original job parameters
            - task_results: All completed task records
    """
    
    # Extract COG results (Stage 2)
    cog_tasks = [t for t in context.task_results if t.task_type == "create_cog"]
    successful_cogs = [t for t in cog_tasks if t.status == TaskStatus.COMPLETED]
    failed_cogs = [t for t in cog_tasks if t.status == TaskStatus.FAILED]
    
    # Calculate total size
    total_size_mb = sum(
        t.result_data.get("result", {}).get("size_mb", 0)
        for t in successful_cogs
    )
    
    cog_summary = {
        "total_count": len(successful_cogs),
        "successful": len(successful_cogs),
        "failed": len(failed_cogs),
        "total_size_mb": round(total_size_mb, 2)
    }
    
    # Extract MosaicJSON result (Stage 3)
    mosaicjson_tasks = [t for t in context.task_results if t.task_type == "create_mosaicjson"]
    mosaicjson_summary = {}
    if mosaicjson_tasks and mosaicjson_tasks[0].result_data:
        mosaicjson_result = mosaicjson_tasks[0].result_data
        mosaicjson_summary = {
            "blob_path": mosaicjson_result.get("mosaicjson_blob"),
            "url": mosaicjson_result.get("mosaicjson_url"),
            "bounds": mosaicjson_result.get("bounds"),
            "tile_count": mosaicjson_result.get("tile_count")
        }
    
    # Extract STAC result (Stage 4)
    stac_tasks = [t for t in context.task_results if t.task_type == "create_stac_collection"]
    stac_summary = {}
    titiler_urls = None
    share_url = None
    
    if stac_tasks and stac_tasks[0].result_data:
        stac_result = stac_tasks[0].result_data
        collection_id = stac_result.get("collection_id", "cogs")
        item_id = stac_result.get("stac_id") or stac_result.get("pgstac_id")
        
        # Extract pgSTAC search URLs
        search_id = stac_result.get("search_id")
        viewer_url = stac_result.get("viewer_url")
        
        stac_summary = {
            "collection_id": collection_id,
            "stac_id": item_id,
            "pgstac_id": stac_result.get("pgstac_id"),
            "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
            "search_id": search_id,
            "items_created": stac_result.get("items_created", 0),
            "items_failed": stac_result.get("items_failed", 0)
        }
        
        # Use pgSTAC search URLs for visualization
        if search_id:
            titiler_urls = {
                "viewer_url": stac_result.get("viewer_url"),
                "tilejson_url": stac_result.get("tilejson_url"),
                "tiles_url": stac_result.get("tiles_url"),
                "search_id": search_id
            }
            share_url = stac_result.get("viewer_url")
    
    return {
        "job_type": "process_raster_collection",
        "job_id": context.job_id,
        "collection_id": context.parameters.get("collection_id"),
        "cogs": cog_summary,
        "mosaicjson": mosaicjson_summary,
        "stac": stac_summary,
        "titiler_urls": titiler_urls,      # All TiTiler endpoints
        "share_url": share_url,             # PRIMARY URL for end users
        "stages_completed": context.current_stage,
        "total_tasks_executed": len(context.task_results),
        "tasks_by_status": {
            "completed": sum(1 for t in context.task_results if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in context.task_results if t.status == TaskStatus.FAILED)
        }
    }
```

### Return to Client

The final job summary is:
1. Stored in `app.jobs.result_data` (PostgreSQL)
2. Returned to HTTP client (if still waiting)
3. Used to update Platform request status (if callback registered)

**Response Example**:
```json
{
  "job_type": "process_raster_collection",
  "job_id": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6...",
  "collection_id": "namangan_2019_tiles",
  "cogs": {
    "total_count": 100,
    "successful": 100,
    "failed": 0,
    "total_size_mb": 4250.0
  },
  "mosaicjson": {
    "blob_path": "mosaics/namangan_2019_tiles.json",
    "url": "https://...",
    "bounds": [-73.5, 39.8, -73.2, 40.1],
    "tile_count": 100
  },
  "stac": {
    "collection_id": "namangan_2019_tiles",
    "stac_id": "namangan_2019",
    "pgstac_id": 12345,
    "inserted_to_pgstac": true,
    "search_id": "search_12345",
    "items_created": 100,
    "items_failed": 0
  },
  "titiler_urls": {
    "viewer_url": "https://titiler.../search/search_12345",
    "tilejson_url": "https://titiler.../search/search_12345/tilejson.json",
    "tiles_url": "https://titiler.../search/search_12345/tiles/{z}/{x}/{y}.png",
    "search_id": "search_12345"
  },
  "share_url": "https://titiler.../search/search_12345",
  "stages_completed": 4,
  "total_tasks_executed": 201,
  "tasks_by_status": {
    "completed": 201,
    "failed": 0
  }
}
```

---

## DATABASE SCHEMA

### Core Tables

**Table**: `app.jobs`
```sql
CREATE TABLE app.jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status app.job_status_enum NOT NULL,
    stage INTEGER NOT NULL,
    total_stages INTEGER NOT NULL,
    parameters JSONB NOT NULL,
    stage_results JSONB DEFAULT '{}',
    result_data JSONB,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX: (job_type, status),
    INDEX: (created_at DESC)
);
```

**Table**: `app.tasks`
```sql
CREATE TABLE app.tasks (
    task_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES app.jobs(job_id),
    task_type TEXT NOT NULL,
    status app.task_status_enum NOT NULL,
    stage INTEGER NOT NULL,
    task_index INTEGER NOT NULL,
    parameters JSONB NOT NULL,
    result_data JSONB,
    retry_count INTEGER DEFAULT 0,
    heartbeat TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    INDEX: (job_id, status),
    INDEX: (task_type, status),
    INDEX: (heartbeat)
);
```

### STAC Tables (PgSTAC)

**Table**: `pgstac.collections` (auto-created by pgstac schema)
- Stores STAC collection metadata
- Insert via pgSTAC API

**Table**: `pgstac.items` (auto-created by pgstac schema)
- Stores individual STAC items (one per COG tile)
- Linked to collection via `collection` field

### Geospatial Tables

**Table**: `geo.spatial_data` (Custom schema)
- Can be used to store geometry bounds from STAC items
- Or queried from pgSTAC items table

---

## ERROR HANDLING

### Contract Violations (Programming Bugs)

**Type**: `ContractViolationError` (inherits from `TypeError`)  
**When**: Wrong types passed, missing required fields, interface violations  
**Handling**: NEVER catch - let bubble up to crash function  
**Purpose**: Find bugs during development

**Examples**:
```python
# Contract violation - wrong type
if not isinstance(blob_url, str):
    raise ContractViolationError(f"blob_url must be str, got {type(blob_url).__name__}")

# Contract violation - missing required field
if "cog_blob" not in result_data:
    raise ContractViolationError("Handler returned result without required 'cog_blob' field")
```

### Business Logic Errors (Expected Runtime Failures)

**Type**: `BusinessLogicError` and subclasses  
**When**: Normal failures during operation (missing resources, network issues)  
**Handling**: Catch and handle gracefully  
**Purpose**: Keep system running despite expected issues

**Subclasses**:
- `ResourceNotFoundError`: Blob doesn't exist, container missing
- `ServiceBusError`: Queue unavailable
- `DatabaseError`: PostgreSQL connection failed
- `TaskExecutionError`: Task failed during processing

**Examples**:
```python
# Business error - Blob not found
try:
    blob_url = blob_repo.get_blob_url_with_sas(container, blob)
except ResourceNotFoundError as e:
    return {"success": False, "error": str(e), "error_type": "ResourceNotFoundError"}

# Business error - Service Bus unavailable
try:
    service_bus_repo.send_message(queue, message)
except ServiceBusError as e:
    logger.warning(f"Service Bus temporarily unavailable: {e}")
    # Retry logic here
```

### Validation Failures

**Stage 1 - validate_raster**:
- CRS not found or invalid → ValueError (task fails)
- Raster type mismatch (RGB expected, got RGBA) → ValueError (task fails)
- 64-bit data → Warning but continues (configurable)
- File unreadable → Returns `{"success": False, "error": "..."}`

**Stage 2 - create_cog**:
- Source CRS missing from validation → Raises ValueError (task fails)
- Reprojection fails → Returns `{"success": False, "error": "..."}`
- Output blob upload fails → Raises exception (task fails)

**Stage 3 - create_mosaicjson**:
- No COG results from Stage 2 → Returns `{"success": False, "error": "..."}`
- MosaicJSON creation fails → Returns `{"success": False, "error": "..."}`
- Container write failed → Raises exception (task fails)

**Stage 4 - create_stac_collection**:
- No MosaicJSON result from Stage 3 → Returns `{"success": False, "error": "..."}`
- pgSTAC insertion fails → Raises exception (task fails)

### Retry Logic

**Task Retries**:
- Transient failures (IOError, TimeoutError, ConnectionError): Retry up to 3 times
- Permanent failures (ValueError, ResourceNotFoundError): Fail immediately
- Max retry count: 3 (configurable)

**Job Retries**:
- If stage fails (all tasks failed): Job marked as FAILED
- Entire job can be resubmitted (idempotency via SHA256 job ID)

---

## EXECUTION TIMELINE EXAMPLE

**For 100-tile collection**:

```
T=0s: HTTP POST /api/jobs/process_raster_collection
  ✓ Validate parameters
  ✓ Generate job ID
  ✓ Check idempotency (not found)
  ✓ Create JobRecord (status=QUEUED)
  ✓ Queue JobQueueMessage
  → Return 200 OK with job_id

T=1s: Service Bus triggers CoreMachine
  ✓ Load JobRecord (status=QUEUED)
  ✓ Call job.create_tasks_for_stage(1)
  ✓ Create 100 validate_raster tasks
  ✓ Queue to tasks queue
  ✓ Update JobRecord (status=PROCESSING, stage=1)

T=5s: Tasks queue processes validation tasks
  ✓ 100 validate_raster tasks queued (processed in parallel)
  ✓ Each takes ~30-60s to validate

T=65s: Last validation task completes
  ✓ CoreMachine detects stage 1 complete
  ✓ Aggregate 100 result_data dicts
  ✓ Load job.create_tasks_for_stage(2, previous_results=...)
  ✓ Create 100 create_cog tasks (with source_crs from validation)
  ✓ Queue to tasks queue
  ✓ Update JobRecord (stage=2)

T=70s: Tasks queue processes COG creation
  ✓ 100 create_cog tasks queued (processed in parallel)
  ✓ Each takes ~60-120s to create COG

T=190s: Last COG task completes
  ✓ CoreMachine detects stage 2 complete
  ✓ Aggregate 100 result_data dicts
  ✓ Load job.create_tasks_for_stage(3) → returns []
  ✓ CoreMachine auto-creates 1 create_mosaicjson task
  ✓ Queue to tasks queue
  ✓ Update JobRecord (stage=3)

T=195s: MosaicJSON creation starts
  ✓ create_mosaicjson handler receives 100 COG results
  ✓ Creates virtual mosaic with cogeo-mosaic
  ✓ Uploads MosaicJSON to silver-tiles
  ✓ Returns result with blob_path, URL, bounds

T=210s: MosaicJSON task completes
  ✓ CoreMachine detects stage 3 complete
  ✓ Load job.create_tasks_for_stage(4) → returns []
  ✓ CoreMachine auto-creates 1 create_stac_collection task
  ✓ Queue to tasks queue
  ✓ Update JobRecord (stage=4)

T=215s: STAC collection creation starts
  ✓ create_stac_collection handler receives MosaicJSON result
  ✓ Creates STAC Collection item
  ✓ Creates STAC Items for 100 COG tiles
  ✓ Inserts to pgSTAC collections and items tables
  ✓ Registers search in PgSTAC Search
  ✓ Returns search_id, viewer_url, tiles_url

T=225s: STAC collection task completes
  ✓ CoreMachine detects all stages complete (stage=4, total_stages=4)
  ✓ Call job.finalize_job(context)
  ✓ Create final job summary with TiTiler URLs
  ✓ Store result_data in JobRecord
  ✓ Update JobRecord (status=COMPLETED)
  ✓ Call on_job_complete callback (Platform integration)

T=226s: Client polls /api/jobs/status/{job_id}
  ✓ Return completed job with:
    - 100 COGs created (4.25 GB total)
    - MosaicJSON with 100 tiles
    - STAC collection in pgSTAC
    - Viewer URL: https://titiler.../search/search_12345
    - Tiles URL: https://titiler.../search/search_12345/tiles/{z}/{x}/{y}.png

TOTAL TIME: ~226 seconds (3.8 minutes)
  Stage 1: 64s (parallel validation)
  Stage 2: 125s (parallel COG creation)
  Stage 3: 15s (single MosaicJSON)
  Stage 4: 10s (single STAC)
  Overhead: 12s (queuing, database, etc.)
```

---

## SUMMARY

The **process_raster_collection** workflow demonstrates the four-stage architecture:

1. **Stage 1 (Fan-out)**: Parallel validation of all tiles
2. **Stage 2 (Fan-out)**: Parallel COG creation using validation results
3. **Stage 3 (Fan-in)**: Aggregates all COGs into virtual MosaicJSON
4. **Stage 4 (Fan-in)**: Creates STAC collection with pgSTAC registration

**Key Design Features**:
- ✅ Idempotent job creation (SHA256-based deduplication)
- ✅ Parallel task execution (100 tiles → 100 concurrent validators)
- ✅ Fan-in aggregation (Stage 3-4 receive all previous results)
- ✅ Database persistence (PostgreSQL app.jobs, app.tasks)
- ✅ Service Bus orchestration (Async job/task queuing)
- ✅ STAC/pgSTAC integration (Searchable collection)
- ✅ TiTiler visualization URLs (Browser-ready sharing)

**Production Ready** for vendor tile deliveries, multi-dataset ingestion, and large-scale raster processing.
