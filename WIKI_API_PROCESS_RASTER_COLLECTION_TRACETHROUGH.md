# PROCESS_RASTER_COLLECTION Workflow Trace-Through

**Date**: 22 NOV 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Technical workflow documentation

---

## Overview

The `process_raster_collection` job is a **four-stage fan-out/fan-in workflow** that processes multiple raster tiles into a unified collection with COG tiles, MosaicJSON virtual mosaic, and STAC collection metadata. This document traces the complete execution flow from HTTP request to job completion.

### Workflow Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 PROCESS_RASTER_COLLECTION WORKFLOW                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  HTTP Request (with blob_list)                                              │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────┐                                                         │
│  │ Stage 1: Fan-Out│  Validate all tiles in parallel (N tasks)              │
│  │ validate_raster │  OUTPUT: N validation results                          │
│  │ (N parallel)    │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 2: Fan-Out│  Create COG for each tile in parallel (N tasks)        │
│  │ create_cog      │  OUTPUT: N COG results (blob paths, bounds, metadata)  │
│  │ (N parallel)    │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 3: Fan-In │  Aggregate all COGs → Create MosaicJSON                │
│  │ create_mosaic   │  OUTPUT: MosaicJSON URL, bounds, tile count            │
│  │ (single task)   │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 4: Fan-In │  Create STAC Collection + Items + pgSTAC Search       │
│  │ create_stac_coll│  OUTPUT: Collection ID, search ID, TiTiler URLs        │
│  │ (single task)   │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │   Job Complete  │  Aggregate results, generate share URLs                │
│  │   finalize_job  │                                                         │
│  └─────────────────┘                                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Use Cases

- Process satellite tile grids (e.g., Maxar WorldView deliveries)
- Create unified collections from multi-scene acquisitions
- Build seamless mosaics from adjacent raster tiles
- Generate MosaicJSON for dynamic tiling via TiTiler
- Enable pgSTAC search-based tile serving

---

## 1. Entry Point: HTTP Request

### Endpoint: `POST /api/jobs/submit/process_raster_collection`

### File: [function_app.py:566-569](function_app.py)

The Function App routes the HTTP request to the job submission trigger:

```python
# function_app.py:566-569
@app.route(route="jobs/submit/{job_type}", methods=["POST"])
def submit_job_http(req: func.HttpRequest) -> func.HttpResponse:
    """Submit job via HTTP endpoint."""
    return submit_job_trigger.handle_request(req)
```

**Request Body Example (from API_JOB_SUBMISSION.md)**:

```json
{
    "container_name": "rmhazuregeobronze",
    "blob_list": [
        "namangan/namangan14aug2019_R1C1cog.tif",
        "namangan/namangan14aug2019_R1C2cog.tif",
        "namangan/namangan14aug2019_R2C1cog.tif",
        "namangan/namangan14aug2019_R2C2cog.tif"
    ],
    "collection_id": "namangan-full-collection",
    "output_folder": "cogs/namangan_full",
    "output_tier": "analysis",
    "target_crs": "EPSG:4326",
    "create_mosaicjson": true,
    "create_stac_collection": true
}
```

---

## 2. Job Class Lookup

### File: [triggers/submit_job.py:147-309](triggers/submit_job.py)

The `JobSubmissionTrigger` processes the request (same pattern as process_raster):

```python
# triggers/submit_job.py:147-162
def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
    # Step 1: Extract job_type from URL path
    path_params = self.extract_path_params(req, ["job_type"])
    job_type = path_params["job_type"]  # "process_raster_collection"

    # Step 2: Extract and validate JSON request body
    req_body = self.extract_json_body(req, required=True)

    # Step 3: Get controller from registry
    controller = self._get_controller_for_job_type(job_type)
```

### Job Registry:

### File: [jobs/__init__.py:68,90](jobs/__init__.py)

```python
# jobs/__init__.py:68
from .process_raster_collection import ProcessRasterCollectionWorkflow

# jobs/__init__.py:90
ALL_JOBS = {
    # ... other jobs ...
    "process_raster_collection": ProcessRasterCollectionWorkflow,
    # ... other jobs ...
}
```

---

## 3. Job Definition

### File: [jobs/process_raster_collection.py:74-116](jobs/process_raster_collection.py)

### 3.1 Class Metadata

```python
# jobs/process_raster_collection.py:74-86
class ProcessRasterCollectionWorkflow(JobBase):
    """
    Multi-tile raster collection processing workflow with MosaicJSON.
    """

    job_type: str = "process_raster_collection"
    description: str = "Process raster tile collection to COGs with MosaicJSON"
```

### 3.2 Stage Definitions

```python
# jobs/process_raster_collection.py:88-116
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

### 3.3 Parameters Schema

```python
# jobs/process_raster_collection.py:119-220
parameters_schema: Dict[str, Any] = {
    "blob_list": {
        "type": "list",
        "required": True,
        "description": "List of raster tile blob paths"
    },
    "collection_id": {
        "type": "str",
        "required": True,
        "description": "Unique collection identifier"
    },
    "collection_description": {
        "type": "str",
        "required": False,
        "default": None
    },
    "container_name": {
        "type": "str",
        "required": True,
        "default": None
    },
    "input_crs": {"type": "str", "required": False, "default": None},
    "raster_type": {
        "type": "str",
        "required": False,
        "default": "auto",
        "allowed": ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
    },
    "output_tier": {
        "type": "str",
        "required": False,
        "default": "analysis",
        "allowed": ["visualization", "analysis", "archive"]
    },
    "output_folder": {"type": "str", "required": False, "default": None},
    "output_container": {"type": "str", "required": False, "default": None},
    "mosaicjson_container": {"type": "str", "required": False, "default": None},
    "target_crs": {"type": "str", "required": False, "default": None},
    "in_memory": {"type": "bool", "required": False, "default": None},
    "maxzoom": {"type": "int", "required": False, "default": None},
    "stac_item_id": {"type": "str", "required": False, "default": None},
    "create_mosaicjson": {"type": "bool", "required": False, "default": True},
    "create_stac_collection": {"type": "bool", "required": False, "default": True}
}
```

---

## 4. Parameter Validation

### File: [jobs/process_raster_collection.py:222-382](jobs/process_raster_collection.py)

The `validate_job_parameters()` method performs validation:

```python
# jobs/process_raster_collection.py:222-382
@staticmethod
def validate_job_parameters(params: dict) -> dict:
    """
    Validate and normalize process_raster_collection parameters.
    """
    # 1. Validate required parameters
    if "blob_list" not in params:
        raise ValueError("blob_list is required")
    if "collection_id" not in params:
        raise ValueError("collection_id is required")
    if "container_name" not in params:
        raise ValueError("container_name is required")

    blob_list = params["blob_list"]
    collection_id = params["collection_id"]
    container_name = params["container_name"]

    # 2. Validate blob_list format
    if not isinstance(blob_list, list) or not blob_list:
        raise ValueError("blob_list must be a non-empty list of blob paths")

    # 3. Validate collection_id format (alphanumeric, hyphens, underscores)
    if not collection_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("collection_id must contain only alphanumeric, hyphens, and underscores")

    # 4. Validate raster_type
    allowed_types = ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
    raster_type = params.get("raster_type", "auto")
    if raster_type not in allowed_types:
        raise ValueError(f"raster_type must be one of {allowed_types}, got '{raster_type}'")

    # 5. Validate output_tier
    allowed_tiers = ["visualization", "analysis", "archive"]
    output_tier = params.get("output_tier", "analysis")
    if output_tier not in allowed_tiers:
        raise ValueError(f"output_tier must be one of {allowed_tiers}, got '{output_tier}'")

    # 6. Validate container existence
    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.instance()

    if not blob_repo.container_exists(container_name):
        raise ValueError(f"Container '{container_name}' does not exist")

    # 7. Validate blob existence (early validation for all blobs)
    missing_blobs = []
    for blob_name in blob_list:
        if not blob_repo.blob_exists(container_name, blob_name):
            missing_blobs.append(blob_name)

    if missing_blobs:
        raise ValueError(f"Blobs not found in container '{container_name}': {missing_blobs}")

    # 8. Return validated parameters
    return {
        "blob_list": blob_list,
        "collection_id": collection_id,
        "container_name": container_name,
        "collection_description": params.get("collection_description"),
        "raster_type": raster_type,
        "output_tier": output_tier,
        "output_folder": params.get("output_folder"),
        "output_container": params.get("output_container"),
        "mosaicjson_container": params.get("mosaicjson_container"),
        "target_crs": params.get("target_crs"),
        "input_crs": params.get("input_crs"),
        "in_memory": params.get("in_memory"),
        "maxzoom": params.get("maxzoom"),
        "stac_item_id": params.get("stac_item_id"),
        "create_mosaicjson": params.get("create_mosaicjson", True),
        "create_stac_collection": params.get("create_stac_collection", True)
    }
```

**Key Validation**: All blobs are checked for existence at submission time (early validation pattern).

---

## 5. Job ID Generation (Idempotency)

### File: [jobs/process_raster_collection.py:384-395](jobs/process_raster_collection.py)

```python
# jobs/process_raster_collection.py:384-395
@staticmethod
def generate_job_id(params: dict) -> str:
    """
    Generate deterministic job ID from parameters via SHA256 hash.
    Same parameters = same job ID (idempotency).
    """
    param_str = json.dumps(params, sort_keys=True)
    job_hash = hashlib.sha256(param_str.encode()).hexdigest()
    return job_hash
```

---

## 6. Job Record Creation

### File: [jobs/process_raster_collection.py:397-443](jobs/process_raster_collection.py)

```python
# jobs/process_raster_collection.py:397-443
@staticmethod
def create_job_record(job_id: str, params: dict) -> dict:
    from infrastructure import RepositoryFactory
    from core.models import JobRecord, JobStatus

    job_record = JobRecord(
        job_id=job_id,
        job_type="process_raster_collection",
        parameters=params,
        status=JobStatus.QUEUED,
        stage=1,
        total_stages=4,  # Stages: validate, COG, MosaicJSON, STAC
        stage_results={},
        metadata={
            "description": "Process raster tile collection to COGs with MosaicJSON",
            "created_by": "ProcessRasterCollectionWorkflow",
            "collection_id": params.get("collection_id"),
            "tile_count": len(params.get("blob_list", [])),
            "output_tier": params.get("output_tier", "analysis")
        }
    )

    # Persist to PostgreSQL (app schema, jobs table)
    repos = RepositoryFactory.create_repositories()
    job_repo = repos['job_repo']
    job_repo.create_job(job_record)

    return job_record.model_dump()
```

---

## 7. Job Queuing to Service Bus

### File: [jobs/process_raster_collection.py:445-497](jobs/process_raster_collection.py)

```python
# jobs/process_raster_collection.py:445-497
@staticmethod
def queue_job(job_id: str, params: dict) -> dict:
    from infrastructure.service_bus import ServiceBusRepository
    from core.schema.queue import JobQueueMessage
    from config import get_config

    config = get_config()
    queue_name = config.service_bus_jobs_queue  # "geospatial-jobs"

    service_bus_repo = ServiceBusRepository()

    # Create job queue message
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

---

## 8. CoreMachine: Job Message Processing

### File: [core/machine.py:312-546](core/machine.py)

When the job message arrives from Service Bus, CoreMachine processes it (same as other workflows).

---

## 9. Stage 1: Parallel Raster Validation (Fan-Out)

### 9.1 Task Creation

### File: [jobs/process_raster_collection.py:499-591](jobs/process_raster_collection.py)

```python
# jobs/process_raster_collection.py:499-591
@staticmethod
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
    if stage == 1:
        # Stage 1: Fan-out - Create one validation task per tile
        blob_list = job_params["blob_list"]
        container_name = job_params["container_name"]

        from config import get_config
        from infrastructure.blob import BlobRepository

        config = get_config()
        blob_repo = BlobRepository.instance()

        tasks = []
        for i, blob_name in enumerate(blob_list):
            # Generate SAS URL for raster (2-hour validity)
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name,
                blob_name,
                hours=2
            )

            task_id = generate_deterministic_task_id(job_id, 1, f"validate_{i}")
            tasks.append({
                "task_id": task_id,
                "task_type": "validate_raster",
                "parameters": {
                    "blob_url": blob_url,
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "input_crs": job_params.get("input_crs"),
                    "raster_type": job_params.get("raster_type", "auto"),
                    "strict_mode": False  # Collections tolerate warnings
                }
            })

        logger.info(f"Stage 1: Created {len(tasks)} validation tasks (fan-out)")
        return tasks
```

Creates N parallel validation tasks, one per tile in `blob_list`.

### 9.2 Task Handler Execution

**Handler**: `validate_raster` (same as process_raster Stage 1)

### File: [services/raster_validation.py:118-720](services/raster_validation.py)

Each tile is validated in parallel using the same validation handler as process_raster. See API_PROCESS_RASTER_TRACETHROUGH.md Section 11 for handler details.

**Validation Per Tile**:
- CRS check
- Bit-depth efficiency
- Raster type detection
- Bounds validation
- Optimal COG settings recommendation

---

## 10. Stage 2: Parallel COG Creation (Fan-Out)

### 10.1 Task Creation

### File: [jobs/process_raster_collection.py:593-751](jobs/process_raster_collection.py)

```python
# jobs/process_raster_collection.py:593-751
elif stage == 2:
    # Stage 2: Fan-out - Create one COG task per tile
    # Uses validation results from Stage 1
    if not previous_results:
        raise ValueError("Stage 2 requires Stage 1 validation results")

    from config import get_config
    config = get_config()

    # Extract configuration
    output_tier = job_params.get("output_tier", "analysis")
    output_folder = job_params.get("output_folder")
    output_container = job_params.get("output_container") or config.get_silver_container_name(output_tier)

    tasks = []
    for i, validation_result in enumerate(previous_results):
        if not validation_result.get('success'):
            logger.warning(f"Stage 2: Skipping tile {i} - validation failed")
            continue

        result_data = validation_result['result']
        blob_name = result_data['source_blob']
        source_crs = result_data['source_crs']
        raster_type = result_data.get('raster_type', {})

        # Generate output blob name
        base_name = blob_name.rsplit('.', 1)[0].replace("/", "_")
        output_blob_name = f"{output_folder}/{base_name}_cog_{output_tier}.tif" if output_folder else f"{base_name}_cog_{output_tier}.tif"

        task_id = generate_deterministic_task_id(job_id, 2, f"cog_{i}")
        tasks.append({
            "task_id": task_id,
            "task_type": "create_cog",
            "parameters": {
                "container_name": job_params["container_name"],
                "blob_name": blob_name,
                "output_blob_name": output_blob_name,
                "source_crs": source_crs,
                "target_crs": job_params.get("target_crs", "EPSG:4326"),
                "raster_type": raster_type,
                "output_tier": output_tier,
                "in_memory": job_params.get("in_memory")
            }
        })

    logger.info(f"Stage 2: Created {len(tasks)} COG creation tasks (fan-out)")
    return tasks
```

Creates N parallel COG tasks, one per successfully validated tile.

### 10.2 Task Handler Execution

**Handler**: `create_cog` (same as process_raster Stage 2)

### File: [services/raster_cog.py:60-550](services/raster_cog.py)

Each tile is converted to COG in parallel using the same COG handler as process_raster. See API_PROCESS_RASTER_TRACETHROUGH.md Section 12 for handler details.

**COG Creation Per Tile**:
- Single-pass reproject + COG creation via rio-cogeo
- Type-specific compression (JPEG, DEFLATE, LZW)
- BAND interleave for cloud-native access
- Upload to silver container

---

## 11. Stage 3: MosaicJSON Creation (Fan-In)

### 11.1 Task Creation

**NOTE**: CoreMachine automatically creates fan_in tasks based on `parallelism: "fan_in"` in stage definition. The job class does NOT need to create this task manually.

### File: [core/machine.py:400-500](core/machine.py) (CoreMachine auto-creation)

CoreMachine automatically creates a single fan_in task that receives all Stage 2 results via `previous_results` parameter.

```python
# Automatic fan_in task creation by CoreMachine
task_params = {
    "previous_results": all_stage_2_results,  # All N COG creation results
    "job_parameters": job_params  # Original job parameters
}
```

### 11.2 Task Handler Execution

### File: [services/raster_mosaicjson.py:46-450](services/raster_mosaicjson.py)

```python
# services/raster_mosaicjson.py:46-450
def create_mosaicjson(params: dict, context: dict = None) -> dict:
    """
    Create MosaicJSON from COG collection (fan_in task handler).

    Receives all Stage 2 COG creation results via params["previous_results"].
    """
    # Extract parameters
    previous_results = params.get("previous_results", [])  # All N COG results
    job_parameters = params.get("job_parameters", {})

    collection_id = job_parameters.get("collection_id")
    mosaicjson_container = job_parameters.get("mosaicjson_container") or config.resolved_intermediate_tiles_container
    cog_container = job_parameters.get("cog_container") or job_parameters.get("output_container")
    output_folder = job_parameters.get("output_folder")
    maxzoom = job_parameters.get("maxzoom") or config.raster_mosaicjson_maxzoom  # Default: 19

    logger.info(f"MosaicJSON: Aggregating {len(previous_results)} COG results")

    # STEP 1: Extract COG blob paths from previous_results
    cog_blobs = []
    for result in previous_results:
        if result.get('success'):
            cog_blob = result.get('result', {}).get('cog_blob')
            if cog_blob:
                cog_blobs.append(cog_blob)

    logger.info(f"   Extracted {len(cog_blobs)} COG blob paths")

    # STEP 2: Generate full /vsiaz/ URLs for cogeo-mosaic
    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.instance()

    cog_urls = []
    for cog_blob in cog_blobs:
        # Generate SAS URL with 24-hour validity for MosaicJSON
        sas_url = blob_repo.get_blob_url_with_sas(cog_container, cog_blob, hours=24)
        # Convert to /vsiaz/ GDAL virtual filesystem URL
        vsiaz_url = f"/vsiaz/{cog_container}/{cog_blob}"
        cog_urls.append(vsiaz_url)

    # STEP 3: Create MosaicJSON using cogeo-mosaic library
    from cogeo_mosaic.mosaic import MosaicJSON
    from cogeo_mosaic.backends import FileBackend

    # Create temporary MosaicJSON file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
        mosaic = MosaicJSON.from_urls(
            cog_urls,
            minzoom=None,  # Auto-calculate
            maxzoom=maxzoom
        )

        # Write MosaicJSON to temp file
        json.dump(mosaic.model_dump(exclude_none=True), tmp, indent=2)
        tmp_path = tmp.name

    # STEP 4: Upload MosaicJSON to blob storage
    mosaic_blob_name = f"{output_folder}/{collection_id}.json" if output_folder else f"{collection_id}.json"

    with open(tmp_path, 'rb') as f:
        mosaic_data = f.read()

    blob_repo.write_blob(mosaicjson_container, mosaic_blob_name, mosaic_data)

    # STEP 5: Generate public URL
    mosaic_url = blob_repo.get_blob_url(mosaicjson_container, mosaic_blob_name)

    # STEP 6: Extract metadata
    bounds = mosaic.bounds  # [minx, miny, maxx, maxy]
    center = mosaic.center  # [lon, lat, zoom]
    minzoom = mosaic.minzoom
    maxzoom_actual = mosaic.maxzoom
    quadkey_count = len(mosaic.tiles)

    # Cleanup temp file
    os.unlink(tmp_path)

    # SUCCESS
    return {
        "success": True,
        "result": {
            "mosaicjson_blob": mosaic_blob_name,
            "mosaicjson_url": mosaic_url,
            "tile_count": len(cog_blobs),
            "bounds": bounds,
            "center": center,
            "minzoom": minzoom,
            "maxzoom": maxzoom_actual,
            "quadkey_count": quadkey_count,
            "cog_blobs": cog_blobs,  # Pass to Stage 4 for STAC items
            "cog_container": cog_container  # Pass to Stage 4
        }
    }
```

**MosaicJSON Features**:
- Quadkey-based spatial indexing
- Automatic zoom level calculation
- COG URL references (not embedded data)
- Standards-compliant JSON format
- TiTiler-compatible

---

## 12. Stage 4: STAC Collection Creation (Fan-In)

### 12.1 Task Creation

**NOTE**: CoreMachine automatically creates this fan_in task based on `parallelism: "fan_in"` in stage definition.

### 12.2 Task Handler Execution

### File: [services/stac_collection.py:60-550](services/stac_collection.py)

```python
# services/stac_collection.py:60-550
def create_stac_collection(params: dict, context: dict = None) -> dict:
    """
    Create STAC collection (fan_in task handler).

    Receives Stage 3 MosaicJSON result via params["previous_results"].
    """
    # Extract parameters
    previous_results = params.get("previous_results", [])  # Single MosaicJSON result
    job_parameters = params.get("job_parameters", {})

    collection_id = job_parameters.get("collection_id")
    stac_item_id = job_parameters.get("stac_item_id") or collection_id
    description = job_parameters.get("collection_description") or f"Raster collection: {collection_id}"

    logger.info(f"STAC Collection: Creating collection for {collection_id}")

    # STEP 1: Extract MosaicJSON result from Stage 3
    if not previous_results:
        raise ValueError("No MosaicJSON result from Stage 3")

    mosaic_result = previous_results[0]
    if not mosaic_result.get("success"):
        raise ValueError(f"Stage 3 MosaicJSON failed: {mosaic_result.get('error')}")

    result_data = mosaic_result.get('result', {})
    mosaicjson_url = result_data.get('mosaicjson_url')
    bounds = result_data.get('bounds')  # [minx, miny, maxx, maxy]
    tile_count = result_data.get('tile_count')
    cog_blobs = result_data.get('cog_blobs', [])
    cog_container = result_data.get('cog_container')

    # STEP 2: Create STAC Collection object
    from pystac import Collection, Extent, SpatialExtent, TemporalExtent, Asset

    spatial_extent = SpatialExtent(bboxes=[bounds])
    temporal_extent = TemporalExtent(intervals=[[datetime.now(timezone.utc), None]])
    extent = Extent(spatial=spatial_extent, temporal=temporal_extent)

    collection = Collection(
        id=stac_item_id,
        description=description,
        license="proprietary",
        extent=extent,
        title=f"{collection_id} Collection",
        keywords=["raster", "cog", "mosaicjson"],
        providers=[]
    )

    # STEP 3: Add MosaicJSON as primary asset
    collection.add_asset(
        "mosaicjson",
        Asset(
            href=mosaicjson_url,
            title="MosaicJSON Index",
            media_type="application/json",
            roles=["index", "mosaic"]
        )
    )

    # STEP 4: Insert collection into pgSTAC
    from infrastructure.pgstac_repository import PgStacRepository
    pgstac_repo = PgStacRepository()

    collection_dict = collection.to_dict()
    pgstac_id = pgstac_repo.insert_collection(collection_dict)

    # STEP 5: Create STAC Items for each COG
    items_created = 0
    for i, cog_blob in enumerate(cog_blobs):
        # Create STAC Item for this COG
        item = create_stac_item_from_cog(
            cog_container,
            cog_blob,
            collection_id=stac_item_id,
            item_id=f"{stac_item_id}-tile-{i:04d}"
        )
        pgstac_repo.insert_item(item.to_dict(), collection_id=stac_item_id)
        items_created += 1

    # STEP 6: Register pgSTAC search for collection
    from services.pgstac_search_registration import PgSTACSearchRegistration
    search_reg = PgSTACSearchRegistration()

    search_id = search_reg.register_search(
        collection_id=stac_item_id,
        bounds=bounds,
        metadata={"tile_count": tile_count}
    )

    # STEP 7: Generate TiTiler URLs
    from config import get_config
    config = get_config()

    titiler_base_url = config.titiler_base_url
    titiler_urls = {
        "viewer_url": f"{titiler_base_url}/searches/{search_id}/WebMercatorQuad/map.html?assets=data",
        "tilejson_url": f"{titiler_base_url}/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data",
        "tiles_url": f"{titiler_base_url}/searches/{search_id}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?assets=data",
        "info_url": f"{titiler_base_url}/searches/{search_id}/info",
        "statistics_url": f"{titiler_base_url}/searches/{search_id}/statistics"
    }

    share_url = titiler_urls['viewer_url']

    # SUCCESS
    return {
        "success": True,
        "result": {
            "collection_id": stac_item_id,
            "stac_id": stac_item_id,
            "pgstac_id": pgstac_id,
            "search_id": search_id,
            "tile_count": tile_count,
            "items_created": items_created,
            "spatial_extent": bounds,
            "mosaicjson_url": mosaicjson_url,
            "inserted_to_pgstac": True,
            "ready_for_titiler": True,
            "titiler_urls": titiler_urls,
            "share_url": share_url
        }
    }
```

**STAC Collection Features**:
- Collection-level STAC item (not individual tile items initially)
- MosaicJSON as primary asset
- Spatial/temporal extent from collection bounds
- Individual STAC Items created for each COG tile
- pgSTAC search registration for TiTiler integration
- TiTiler visualization URLs generated

---

## 13. Job Completion and Result Aggregation

### File: [jobs/process_raster_collection.py:754-905](jobs/process_raster_collection.py)

```python
# jobs/process_raster_collection.py:754-905
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Aggregate results from all completed tasks into job summary.
    """
    task_results = context.task_results
    params = context.parameters

    # Separate tasks by stage
    validation_tasks = [t for t in task_results if t.task_type == "validate_raster"]
    cog_tasks = [t for t in task_results if t.task_type == "create_cog"]
    mosaic_tasks = [t for t in task_results if t.task_type == "create_mosaicjson"]
    stac_tasks = [t for t in task_results if t.task_type == "create_stac_collection"]

    # Stage 1: Validation summary
    tiles_validated = len(validation_tasks)
    tiles_valid = sum(1 for t in validation_tasks if t.status == TaskStatus.COMPLETED)

    # Stage 2: COG creation summary
    cogs_created = sum(1 for t in cog_tasks if t.status == TaskStatus.COMPLETED)
    cogs_failed = sum(1 for t in cog_tasks if t.status == TaskStatus.FAILED)
    total_size_mb = sum(
        t.result_data.get('result', {}).get('size_mb', 0)
        for t in cog_tasks if t.status == TaskStatus.COMPLETED
    )

    # Stage 3: MosaicJSON metadata
    mosaic_result = mosaic_tasks[0].result_data.get('result', {}) if mosaic_tasks else {}
    mosaicjson_url = mosaic_result.get('mosaicjson_url')
    mosaic_bounds = mosaic_result.get('bounds')
    mosaic_tile_count = mosaic_result.get('tile_count')

    # Stage 4: STAC collection metadata
    stac_result = stac_tasks[0].result_data.get('result', {}) if stac_tasks else {}
    collection_id = stac_result.get('collection_id')
    pgstac_id = stac_result.get('pgstac_id')
    search_id = stac_result.get('search_id')
    items_created = stac_result.get('items_created', 0)
    titiler_urls = stac_result.get('titiler_urls', {})
    share_url = stac_result.get('share_url')

    return {
        "job_type": "process_raster_collection",
        "collection_id": params.get("collection_id"),
        "validation": {
            "tiles_validated": tiles_validated,
            "tiles_valid": tiles_valid,
            "success_rate": f"{(tiles_valid / tiles_validated * 100):.1f}%" if tiles_validated > 0 else "0.0%"
        },
        "cogs": {
            "successful": cogs_created,
            "failed": cogs_failed,
            "total_size_mb": round(total_size_mb, 2)
        },
        "mosaicjson": {
            "url": mosaicjson_url,
            "bounds": mosaic_bounds,
            "tile_count": mosaic_tile_count
        },
        "stac": {
            "collection_id": collection_id,
            "pgstac_id": pgstac_id,
            "search_id": search_id,
            "items_created": items_created,
            "inserted_to_pgstac": True,
            "ready_for_titiler": True
        },
        "share_url": share_url,
        "titiler_urls": titiler_urls,
        "stages_completed": context.current_stage,
        "total_tasks_executed": len(task_results),
        "tasks_by_status": {
            "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
            "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
        }
    }
```

---

## 14. Handler Registry

### File: [services/__init__.py:104-138](services/__init__.py)

All task handlers are explicitly registered:

```python
# services/__init__.py:104-138
from .raster_validation import validate_raster
from .raster_cog import create_cog
from .raster_mosaicjson import create_mosaicjson
from .stac_collection import create_stac_collection

ALL_HANDLERS = {
    # ... other handlers ...
    "validate_raster": validate_raster,              # Stage 1 (parallel)
    "create_cog": create_cog,                        # Stage 2 (parallel)
    "create_mosaicjson": create_mosaicjson,          # Stage 3 (fan-in)
    "create_stac_collection": create_stac_collection, # Stage 4 (fan-in)
    # ... other handlers ...
}
```

---

## 15. Complete Execution Flow Diagram

```
HTTP POST /api/jobs/submit/process_raster_collection (with 4 tiles)
    ↓
[JobSubmissionTrigger.process_request]
    ↓
1. Extract job_type="process_raster_collection"
2. Extract JSON body (blob_list, collection_id, etc.)
3. Get ProcessRasterCollectionWorkflow from ALL_JOBS registry
4. Call validate_job_parameters()
   ├─ Validate blob_list (required, non-empty list)
   ├─ Validate collection_id (alphanumeric + hyphens/underscores)
   ├─ Check container existence
   └─ Check all blobs exist (early validation)
    ↓
5. Call generate_job_id() → SHA256 hash
6. Check for existing job (idempotency)
7. Call create_job_record() → PostgreSQL app.jobs
8. Call queue_job() → Service Bus geospatial-jobs queue
9. Return HTTP 200 with job_id

═══════════════════════════════════════════════════════════════════

Service Bus triggers JobProcessor
    ↓
[CoreMachine.process_job_message]
    ↓
1. Load JobRecord from PostgreSQL
2. Call ProcessRasterCollectionWorkflow.create_tasks_for_stage(stage=1, ...)
   └─ Returns 4 tasks: validate_raster (one per tile)
    ↓
3. Create 4 TaskRecords in PostgreSQL app.tasks
4. Send 4 TaskQueueMessages to Service Bus geospatial-tasks queue
5. Update JobRecord.stage = 1, status = 'processing'

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor (4 parallel executions)
    ↓
STAGE 1 TASK EXECUTION (PARALLEL - 4 tasks):
    ├─ Get handler: ALL_HANDLERS['validate_raster']
    ├─ Call validate_raster(parameters) for each tile (parallel)
    │   ├─ Open raster via /vsicurl/ + SAS URL
    │   ├─ Validate CRS
    │   ├─ Check bit-depth efficiency
    │   ├─ Auto-detect raster type
    │   └─ Generate optimal COG settings
    ├─ Update 4 TaskRecords.status = 'completed'
    └─ Atomic: Last task checks (SELECT COUNT(*) WHERE status != 'completed') = 1
               If true, mark job as advancing to Stage 2

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Auto-triggered for Stage 2
    ↓
1. Load JobRecord (stage=1)
2. Call ProcessRasterCollectionWorkflow.create_tasks_for_stage(stage=2, previous_results=[...4 validation results])
   ├─ Extract validation metadata from each result
   ├─ Generate output COG blob names
   └─ Returns 4 tasks: create_cog (one per validated tile)
    ↓
3. Create 4 TaskRecords in PostgreSQL app.tasks
4. Send 4 TaskQueueMessages to Service Bus geospatial-tasks queue
5. Update JobRecord.stage = 2

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor (4 parallel executions)
    ↓
STAGE 2 TASK EXECUTION (PARALLEL - 4 tasks):
    ├─ Get handler: ALL_HANDLERS['create_cog']
    ├─ Call create_cog(parameters) for each tile (parallel)
    │   ├─ Get tier-specific COG profile
    │   ├─ Generate SAS URL for input blob
    │   ├─ Single-pass reproject + COG creation via rio-cogeo
    │   ├─ Upload COG to silver container
    │   └─ Extract bounds in EPSG:4326
    ├─ Update 4 TaskRecords.status = 'completed'
    └─ Atomic: Last task → advance to Stage 3

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Auto-triggered for Stage 3
    ↓
1. Load JobRecord (stage=2)
2. CoreMachine AUTO-CREATES fan_in task (parallelism="fan_in" in stage definition)
   ├─ Aggregates all 4 Stage 2 COG results into previous_results
   ├─ Passes job_parameters for collection_id, output_folder, etc.
   └─ Returns 1 task: create_mosaicjson (AUTO-CREATED by CoreMachine)
    ↓
3. Create 1 TaskRecord in PostgreSQL app.tasks
4. Send 1 TaskQueueMessage to Service Bus geospatial-tasks queue
5. Update JobRecord.stage = 3

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor
    ↓
STAGE 3 TASK EXECUTION (FAN-IN):
    ├─ Get handler: ALL_HANDLERS['create_mosaicjson']
    ├─ Call create_mosaicjson(params={previous_results: [...4 COG results], job_parameters: {...}})
    │   ├─ Extract COG blob paths from all 4 results
    │   ├─ Generate /vsiaz/ URLs for cogeo-mosaic
    │   ├─ Create MosaicJSON using cogeo-mosaic library
    │   ├─ Upload MosaicJSON to mosaicjson container
    │   └─ Extract metadata (bounds, zoom levels, quadkey count)
    ├─ Update TaskRecord.status = 'completed'
    └─ Atomic: Last task → advance to Stage 4

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Auto-triggered for Stage 4
    ↓
1. Load JobRecord (stage=3)
2. CoreMachine AUTO-CREATES fan_in task (parallelism="fan_in" in stage definition)
   ├─ Passes single Stage 3 MosaicJSON result
   ├─ Passes job_parameters for collection_id, description, etc.
   └─ Returns 1 task: create_stac_collection (AUTO-CREATED by CoreMachine)
    ↓
3. Create 1 TaskRecord in PostgreSQL app.tasks
4. Send 1 TaskQueueMessage to Service Bus geospatial-tasks queue
5. Update JobRecord.stage = 4

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor
    ↓
STAGE 4 TASK EXECUTION (FAN-IN):
    ├─ Get handler: ALL_HANDLERS['create_stac_collection']
    ├─ Call create_stac_collection(params={previous_results: [mosaic_result], job_parameters: {...}})
    │   ├─ Extract MosaicJSON URL and bounds from Stage 3 result
    │   ├─ Create STAC Collection object with extent
    │   ├─ Add MosaicJSON as primary asset
    │   ├─ Insert collection into pgSTAC collections table
    │   ├─ Create STAC Items for each COG tile (4 items)
    │   ├─ Register pgSTAC search for collection
    │   └─ Generate TiTiler URLs (viewer, tilejson, tiles)
    ├─ Update TaskRecord.status = 'completed'
    └─ Atomic: Last task → mark job as 'completed'

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Final job completion
    ↓
1. Load JobRecord (all stages complete)
2. Call ProcessRasterCollectionWorkflow.finalize_job(context)
   ├─ Separate tasks by stage (validation, COG, mosaic, STAC)
   ├─ Calculate validation success rate
   ├─ Calculate COG statistics (count, size, success/failed)
   ├─ Extract MosaicJSON metadata (URL, bounds, tile count)
   ├─ Extract STAC metadata (collection_id, search_id, items_created)
   ├─ Extract TiTiler URLs (share_url as primary)
   └─ Return comprehensive job result
    ↓
3. Update JobRecord.status = 'completed', result_data = {...}

═══════════════════════════════════════════════════════════════════

End-to-End Result:
  - Bronze container: Original 4 tiles preserved
  - Silver container: 4 COG tiles created with cloud-optimized structure
  - MosaicJSON container: Virtual mosaic JSON index for seamless tiling
  - pgSTAC: Collection + 4 individual STAC items registered
  - pgSTAC search: Registered with collection bounds for TiTiler integration
  - TiTiler: Ready for dynamic tile serving via /searches/{search_id} endpoint
  - HTTP Response: Complete with share_url (auto-zoom to collection extent)
```

---

## 16. Key Files Reference

| Component | File | Key Lines |
|-----------|------|-----------|
| HTTP Trigger | [function_app.py](function_app.py) | 566-569 |
| Job Submission | [triggers/submit_job.py](triggers/submit_job.py) | 147-309 |
| Job Definition | [jobs/process_raster_collection.py](jobs/process_raster_collection.py) | 74-905 |
| Job Registry | [jobs/__init__.py](jobs/__init__.py) | 68, 90 |
| Stage 1 Handler | [services/raster_validation.py](services/raster_validation.py) | 118-720 |
| Stage 2 Handler | [services/raster_cog.py](services/raster_cog.py) | 60-550 |
| Stage 3 Handler | [services/raster_mosaicjson.py](services/raster_mosaicjson.py) | 46-450 |
| Stage 4 Handler | [services/stac_collection.py](services/stac_collection.py) | 60-550 |
| Handler Registry | [services/__init__.py](services/__init__.py) | 104-138 |
| CoreMachine | [core/machine.py](core/machine.py) | 312-1742 |
| Job Base Class | [jobs/base.py](jobs/base.py) | Full file |

---

## 17. Key Design Patterns

### 17.1 Job → Stage → Task Abstraction with Fan-Out/Fan-In

```
JOB (Controller Layer - Orchestration)
 ├── STAGE 1 (validate_tiles - Fan-Out)
 │   ├── Task: validate_raster (tile 0)
 │   ├── Task: validate_raster (tile 1)
 │   ├── Task: validate_raster (tile 2)
 │   └── Task: validate_raster (tile 3)
 │                     ↓ Last task completes stage
 ├── STAGE 2 (create_cogs - Fan-Out)
 │   ├── Task: create_cog (tile 0, uses Stage 1 result 0)
 │   ├── Task: create_cog (tile 1, uses Stage 1 result 1)
 │   ├── Task: create_cog (tile 2, uses Stage 1 result 2)
 │   └── Task: create_cog (tile 3, uses Stage 1 result 3)
 │                     ↓ Last task completes stage
 ├── STAGE 3 (create_mosaicjson - Fan-In)
 │   └── Task: create_mosaicjson (receives ALL 4 Stage 2 results)
 │                     ↓ Stage 3 completes
 ├── STAGE 4 (create_stac_collection - Fan-In)
 │   └── Task: create_stac_collection (receives Stage 3 result)
 │                     ↓ Stage 4 completes
 └── COMPLETION (finalize_job aggregation)
```

### 17.2 Fan-Out: Parallel Processing

- **Stage 1**: N validation tasks (one per tile)
- **Stage 2**: N COG creation tasks (one per validated tile)
- Each task runs independently in parallel
- Last task completion detection triggers stage advancement

### 17.3 Fan-In: Aggregation

- **Stage 3**: Single MosaicJSON task receives ALL Stage 2 COG results
- **Stage 4**: Single STAC collection task receives Stage 3 MosaicJSON result
- CoreMachine automatically creates fan_in tasks based on `parallelism: "fan_in"`
- No manual task creation needed for fan_in stages

### 17.4 Data Flow Between Stages

- **Stage 1 → Stage 2**: Validation metadata (CRS, raster type, optimal settings) for each tile
- **Stage 2 → Stage 3**: COG metadata (blob paths, bounds, container) for all tiles
- **Stage 3 → Stage 4**: MosaicJSON metadata (URL, bounds, tile count)
- **Stage 4 → Finalization**: STAC metadata (collection_id, search_id, TiTiler URLs)

### 17.5 Idempotency via SHA256

- Same parameters (blob_list, collection_id, etc.) always produce same `job_id`
- Duplicate submissions return existing job
- Prevents wasted compute on re-submissions

### 17.6 Early Validation Pattern

- All blobs checked for existence at job submission time
- Container existence checked at job submission time
- Errors raised before any Service Bus messages queued

### 17.7 MosaicJSON Virtual Mosaic

- Quadkey-based spatial indexing for efficient tile selection
- COG URL references (not embedded data)
- Client-side tile selection (no server-side processing)
- TiTiler-compatible for dynamic tiling

### 17.8 STAC Collection + Search Integration

- Collection-level STAC item with MosaicJSON as primary asset
- Individual STAC Items created for each COG tile
- pgSTAC search registration enables TiTiler integration
- Auto-zoom feature: viewer opens at collection extent (not world zoom)

---

## 18. Testing the Workflow

### Submit a Job (4-tile collection):

```bash
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster_collection \
  -H "Content-Type: application/json" \
  -d '{
    "container_name": "rmhazuregeobronze",
    "blob_list": [
      "namangan/namangan14aug2019_R1C1cog.tif",
      "namangan/namangan14aug2019_R1C2cog.tif",
      "namangan/namangan14aug2019_R2C1cog.tif",
      "namangan/namangan14aug2019_R2C2cog.tif"
    ],
    "collection_id": "namangan-full-collection",
    "output_folder": "cogs/namangan_full"
  }'
```

### Check Job Status:

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

### Access Collection via TiTiler:

```bash
# Interactive viewer (from result.share_url - auto-zooms to collection)
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/{search_id}/WebMercatorQuad/map.html?assets=data

# TileJSON spec
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/{search_id}/WebMercatorQuad/tilejson.json?assets=data

# XYZ tiles template
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/searches/{search_id}/tiles/WebMercatorQuad/{z}/{x}/{y}?assets=data
```

---

## 19. Execution Timing

**Real Example** (22 NOV 2025 - Namangan 4-tile collection, 1.7 GB total):

| Stage | Operation | Duration | Notes |
|-------|-----------|----------|-------|
| 1 | Validate 4 tiles (parallel) | ~20 seconds | CRS check, type detection (4 tasks in parallel) |
| 2 | Create 4 COGs (parallel) | ~540 seconds (9 min) | Single-pass reproject + COG (4 tasks in parallel, ~135s each) |
| 3 | Create MosaicJSON (fan-in) | ~15 seconds | Aggregate 4 COG paths, generate quadkey index |
| 4 | Create STAC collection (fan-in) | ~10 seconds | Create collection + 4 items + search registration |
| **Total** | **End-to-end** | **~585 seconds (~9.8 min)** | Bronze → 4 Silver COGs + MosaicJSON + STAC |

**Output**:
- COGs Created: 4 (1654.49 MB total)
- MosaicJSON: Virtual mosaic with 4 tiles, quadkey indexing
- STAC Collection: 1 collection + 4 items in pgSTAC
- TiTiler URLs: 5 endpoints (viewer, tilejson, tiles, info, statistics)
- Auto-Zoom Feature: Viewer opens directly at Namangan, Uzbekistan extent

**Scaling Notes**:
- **10 tiles**: ~25 minutes (Stage 2 bottleneck)
- **100 tiles**: ~4 hours (Stage 2 bottleneck - 100 parallel COG tasks)
- **1000 tiles**: Use `process_large_raster` instead (tiling-based approach)

---
