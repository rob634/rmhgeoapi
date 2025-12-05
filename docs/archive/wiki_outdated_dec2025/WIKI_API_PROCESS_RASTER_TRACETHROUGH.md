# PROCESS_RASTER Workflow Trace-Through

**Date**: 22 NOV 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Technical workflow documentation

---

## Overview

The `process_raster` job is a **three-stage sequential workflow** that converts raster files (GeoTIFF, etc.) to Cloud-Optimized GeoTIFFs (COGs) with STAC metadata cataloging. This document traces the complete execution flow from HTTP request to job completion.

### Workflow Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROCESS_RASTER WORKFLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  HTTP Request                                                                │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────┐                                                         │
│  │ Stage 1: Single │  Validate raster: CRS, bit-depth, type detection       │
│  │ validate_raster │  OUTPUT: Validation metadata + optimal COG settings    │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 2: Single │  Reproject + create COG (single-pass via rio-cogeo)    │
│  │ create_cog      │  OUTPUT: COG blob path, bounds, metadata               │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 3: Single │  Extract STAC metadata, insert into pgSTAC             │
│  │ create_stac     │  OUTPUT: STAC item_id, TiTiler URLs                    │
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

### Supported Input Formats

| Format | Extension | Notes |
|--------|-----------|-------|
| GeoTIFF | `.tif`, `.tiff` | **Preferred format** |
| BigTIFF | `.tif` | For files > 4 GB |
| JPEG 2000 | `.jp2` | Slower processing |
| PNG | `.png` | Must be georeferenced |
| ERDAS IMAGINE | `.img` | Legacy format |
| NetCDF | `.nc` | Scientific data |

### Output Tiers

| Tier | Compression | Access Tier | Use Case | Status |
|------|-------------|-------------|----------|--------|
| `visualization` | JPEG (Q85) | Hot | Web display, TiTiler streaming | Broken |
| `analysis` | DEFLATE | Hot | Scientific analysis, lossless | Recommended |
| `archive` | LZW | Cool | Long-term storage | Working |

Note: `visualization` tier (JPEG compression) fails in Azure Functions. Use `analysis` tier (DEFLATE) as workaround.

---

## 1. Entry Point: HTTP Request

### Endpoint: `POST /api/jobs/submit/process_raster`

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
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze",
    "output_tier": "analysis",
    "output_folder": "cogs/my_test",
    "collection_id": "system-rasters",
    "target_crs": "EPSG:4326",
    "raster_type": "auto"
}
```

---

## 2. Job Class Lookup

### File: [triggers/submit_job.py:147-309](triggers/submit_job.py)

The `JobSubmissionTrigger` processes the request:

```python
# triggers/submit_job.py:147-162
def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
    # Step 1: Extract job_type from URL path
    path_params = self.extract_path_params(req, ["job_type"])
    job_type = path_params["job_type"]  # "process_raster"

    # Step 2: Extract and validate JSON request body
    req_body = self.extract_json_body(req, required=True)

    # Step 3: Get controller from registry
    controller = self._get_controller_for_job_type(job_type)
```

### Controller Lookup:

```python
# triggers/submit_job.py:272-297
def _get_controller_for_job_type(self, job_type: str):
    from jobs import ALL_JOBS

    if job_type not in ALL_JOBS:
        available = list(ALL_JOBS.keys())
        raise ValueError(
            f"Unknown job type: '{job_type}'. "
            f"Available jobs: {available}"
        )

    return ALL_JOBS[job_type]
```

### Job Registry:

### File: [jobs/__init__.py:64,89](jobs/__init__.py)

```python
# jobs/__init__.py:64
from .process_raster import ProcessRasterWorkflow

# jobs/__init__.py:89
ALL_JOBS = {
    # ... other jobs ...
    "process_raster": ProcessRasterWorkflow,
    # ... other jobs ...
}
```

---

## 3. Job Definition

### File: [jobs/process_raster.py:62-97](jobs/process_raster.py)

### 3.1 Class Metadata

```python
# jobs/process_raster.py:62-73
class ProcessRasterWorkflow(JobBase):
    """
    Small file raster processing workflow (<= 1GB).
    """

    job_type: str = "process_raster"
    description: str = "Process raster to COG with STAC metadata (files <= 1GB)"
```

### 3.2 Stage Definitions

```python
# jobs/process_raster.py:75-97
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

### 3.3 Parameters Schema

```python
# jobs/process_raster.py:99-153
parameters_schema: Dict[str, Any] = {
    "blob_name": {"type": "str", "required": True},
    "container_name": {"type": "str", "required": True, "default": None},
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
        "allowed": ["visualization", "analysis", "archive", "all"]
    },
    "target_crs": {
        "type": "str",
        "required": False,
        "default": "EPSG:4326"
    },
    "jpeg_quality": {"type": "int", "required": False, "default": 85},
    "strict_mode": {"type": "bool", "required": False, "default": False},
    "in_memory": {"type": "bool", "required": False, "default": None},
    "collection_id": {"type": "str", "required": False, "default": None},
    "item_id": {"type": "str", "required": False, "default": None},
    "output_folder": {"type": "str", "required": False, "default": None}
}
```

---

## 4. Parameter Validation

### File: [jobs/process_raster.py:156-317](jobs/process_raster.py)

The `validate_job_parameters()` method performs validation:

```python
# jobs/process_raster.py:156-317
@staticmethod
def validate_job_parameters(params: dict) -> dict:
    """
    Validate and normalize process_raster parameters.
    """
    # 1. Validate required parameters
    if "blob_name" not in params:
        raise ValueError("blob_name is required")
    if "container_name" not in params:
        raise ValueError("container_name is required")

    blob_name = params["blob_name"]
    container_name = params["container_name"]

    # 2. Validate blob_name format
    if not isinstance(blob_name, str) or not blob_name.strip():
        raise ValueError("blob_name must be a non-empty string")

    # 3. Validate raster_type
    allowed_types = ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
    raster_type = params.get("raster_type", "auto")
    if raster_type not in allowed_types:
        raise ValueError(f"raster_type must be one of {allowed_types}, got '{raster_type}'")

    # 4. Validate output_tier
    allowed_tiers = ["visualization", "analysis", "archive", "all"]
    output_tier = params.get("output_tier", "analysis")
    if output_tier not in allowed_tiers:
        raise ValueError(f"output_tier must be one of {allowed_tiers}, got '{output_tier}'")

    # 5. Validate CRS format
    target_crs = params.get("target_crs", "EPSG:4326")
    if not target_crs.upper().startswith("EPSG:"):
        raise ValueError(f"target_crs must start with 'EPSG:', got '{target_crs}'")

    # 6. Validate JPEG quality
    jpeg_quality = params.get("jpeg_quality", 85)
    if not isinstance(jpeg_quality, int) or not (1 <= jpeg_quality <= 100):
        raise ValueError(f"jpeg_quality must be an integer between 1-100, got {jpeg_quality}")

    # 7. Check blob existence (early validation)
    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.instance()

    if not blob_repo.container_exists(container_name):
        raise ValueError(f"Container '{container_name}' does not exist")

    if not blob_repo.blob_exists(container_name, blob_name):
        raise ValueError(f"Blob '{blob_name}' not found in container '{container_name}'")

    # 8. Return validated parameters
    return {
        "blob_name": blob_name,
        "container_name": container_name,
        "raster_type": raster_type,
        "output_tier": output_tier,
        "target_crs": target_crs,
        "input_crs": params.get("input_crs"),
        "jpeg_quality": jpeg_quality,
        "strict_mode": params.get("strict_mode", False),
        "in_memory": params.get("in_memory"),
        "collection_id": params.get("collection_id"),
        "item_id": params.get("item_id"),
        "output_folder": params.get("output_folder")
    }
```

---

## 5. Job ID Generation (Idempotency)

### File: [jobs/process_raster.py:319-330](jobs/process_raster.py)

```python
# jobs/process_raster.py:319-330
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

Same parameters always produce same job ID, enabling idempotent operations.

---

## 6. Idempotency Check

### File: [triggers/submit_job.py:220-250](triggers/submit_job.py)

Before creating a new job, check if it already exists:

```python
# triggers/submit_job.py:220-250
from infrastructure.factory import RepositoryFactory
repos = RepositoryFactory.create_repositories()
existing_job = repos['job_repo'].get_job(job_id)

if existing_job:
    if existing_job.status.value == 'completed':
        return {
            "job_id": job_id,
            "status": "already_completed",
            "idempotent": True,
            "result_data": existing_job.result_data,
            # ... cached result returned
        }
    else:
        return {
            "job_id": job_id,
            "status": existing_job.status.value,
            "idempotent": True,
            "current_stage": existing_job.stage,
            # ... in-progress status returned
        }
```

---

## 7. Job Record Creation

### File: [jobs/process_raster.py:332-373](jobs/process_raster.py)

```python
# jobs/process_raster.py:332-373
@staticmethod
def create_job_record(job_id: str, params: dict) -> dict:
    from infrastructure import RepositoryFactory
    from core.models import JobRecord, JobStatus

    job_record = JobRecord(
        job_id=job_id,
        job_type="process_raster",
        parameters=params,
        status=JobStatus.QUEUED,
        stage=1,
        total_stages=3,  # Stage 1: validate, Stage 2: COG, Stage 3: STAC
        stage_results={},
        metadata={
            "description": "Process raster to COG with STAC metadata",
            "created_by": "ProcessRasterWorkflow",
            "blob_name": params.get("blob_name"),
            "container_name": params.get("container_name"),
            "output_tier": params.get("output_tier", "analysis"),
            "target_crs": params.get("target_crs", "EPSG:4326")
        }
    )

    # Persist to PostgreSQL (app schema, jobs table)
    repos = RepositoryFactory.create_repositories()
    job_repo = repos['job_repo']
    job_repo.create_job(job_record)

    return job_record.model_dump()
```

**Database Table**: `app.jobs`
**Columns**: job_id (PK), job_type, parameters (JSONB), status (enum), stage, total_stages, stage_results (JSONB), metadata (JSONB), created_at, updated_at

---

## 8. Job Queuing to Service Bus

### File: [jobs/process_raster.py:375-427](jobs/process_raster.py)

```python
# jobs/process_raster.py:375-427
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
        job_type="process_raster",
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

**Service Bus Queue**: `geospatial-jobs`
**Message Type**: `JobQueueMessage` (Pydantic model)

---

## 9. HTTP Response

### File: [triggers/submit_job.py:252-268](triggers/submit_job.py)

```python
# triggers/submit_job.py:252-268
return {
    "job_id": job_id,
    "status": "created",
    "job_type": "process_raster",
    "message": "Job created and queued for processing",
    "parameters": validated_params,
    "queue_info": queue_result,
    "idempotent": False
}
```

---

## 10. CoreMachine: Job Message Processing

### File: [core/machine.py:312-546](core/machine.py)

When the job message arrives from Service Bus, CoreMachine processes it:

```python
# core/machine.py:312-546
def process_job_message(self, job_message: JobQueueMessage) -> Dict[str, Any]:
    # Step 1: Get job class from registry
    job_class = self.jobs_registry[job_message.job_type]  # ProcessRasterWorkflow

    # Step 2: Get job record from database
    job_record = self.repos['job_repo'].get_job(job_message.job_id)

    # Step 3: Update job status to PROCESSING
    self.state_manager.update_job_status(job_message.job_id, JobStatus.PROCESSING)

    # Step 4: Fetch previous stage results (if not stage 1)
    previous_results = None
    if job_message.stage > 1:
        previous_results = self._get_completed_stage_results(
            job_message.job_id,
            job_message.stage - 1
        )

    # Step 5: Generate task definitions for current stage
    tasks = job_class.create_tasks_for_stage(
        job_message.stage,
        job_record.parameters,
        job_message.job_id,
        previous_results=previous_results
    )

    # Step 6: Convert to TaskDefinition objects and queue tasks
    result = self._individual_queue_tasks(task_definitions, job_message.job_id, job_message.stage)
```

---

## 11. Stage 1: Validate Raster

### 11.1 Task Creation

### File: [jobs/process_raster.py:429-473](jobs/process_raster.py)

```python
# jobs/process_raster.py:429-473
@staticmethod
def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None):
    if stage == 1:
        # Stage 1: Single task to validate raster
        from config import get_config
        from infrastructure.blob import BlobRepository

        config = get_config()
        blob_repo = BlobRepository.instance()

        # Generate SAS URL for raster (2-hour validity)
        blob_url = blob_repo.get_blob_url_with_sas(
            job_params['container_name'],
            job_params['blob_name'],
            hours=2
        )

        task_id = generate_deterministic_task_id(job_id, 1, "validate")
        return [
            {
                "task_id": task_id,
                "task_type": "validate_raster",
                "parameters": {
                    "blob_url": blob_url,
                    "blob_name": job_params["blob_name"],
                    "container_name": job_params["container_name"],
                    "input_crs": job_params.get("input_crs"),
                    "raster_type": job_params.get("raster_type", "auto"),
                    "strict_mode": job_params.get("strict_mode", False)
                }
            }
        ]
```

### 11.2 Task Handler Execution

### File: [services/raster_validation.py:118-550](services/raster_validation.py)

```python
# services/raster_validation.py:118-550
def validate_raster(params: dict) -> dict:
    """
    Validate raster file for COG pipeline processing.

    Checks:
    - File readability
    - CRS presence and validity
    - Bit-depth efficiency (flags 64-bit data)
    - Raster type detection
    - Bounds sanity checks
    """
    blob_url = params.get("blob_url")
    blob_name = params.get("blob_name")
    input_crs = params.get("input_crs")
    raster_type_param = params.get("raster_type", "auto")
    strict_mode = params.get("strict_mode", False)

    # STEP 1: Open raster using rasterio with /vsicurl/
    with rasterio.open(f"/vsicurl/{blob_url}") as src:
        # STEP 2: CRS validation
        source_crs = None
        crs_source = None

        if src.crs:
            source_crs = str(src.crs)
            crs_source = "file_metadata"
        elif input_crs:
            source_crs = input_crs
            crs_source = "user_override"
        else:
            raise ValueError("CRS_CHECK_FAILED: No CRS in file and no input_crs provided")

        # STEP 3: Extract metadata
        band_count = src.count
        dtype = str(src.dtypes[0])
        shape = [src.height, src.width]
        bounds = list(src.bounds)

        # STEP 4: Bit-depth efficiency check
        bit_depth_efficient = dtype not in ['float64', 'int64', 'uint64']
        if not bit_depth_efficient:
            warnings.append(f"64-bit data type ({dtype}) - organizational policy violation")

        # STEP 5: Raster type detection
        detected_type = _detect_raster_type(src)

        # STEP 6: Type mismatch check
        if raster_type_param != "auto" and detected_type != raster_type_param:
            warnings.append(f"TYPE_MISMATCH: Expected {raster_type_param}, detected {detected_type}")

        # STEP 7: Generate optimal COG settings
        optimal_settings = _get_optimal_cog_settings(detected_type, dtype, band_count)

        # STEP 8: Determine applicable COG tiers
        cog_tiers = config.determine_applicable_tiers(band_count, dtype, detected_type)

    # SUCCESS
    return {
        "success": True,
        "result": {
            "valid": True,
            "source_blob": blob_name,
            "band_count": band_count,
            "dtype": dtype,
            "source_crs": source_crs,
            "crs_source": crs_source,
            "bounds": bounds,
            "shape": shape,
            "raster_type": {
                "detected_type": detected_type,
                "confidence": confidence,
                "optimal_cog_settings": optimal_settings
            },
            "cog_tiers": cog_tiers,
            "bit_depth_check": {
                "efficient": bit_depth_efficient,
                "current_dtype": dtype
            },
            "warnings": warnings
        }
    }
```

### Raster Type Detection Logic:

```python
# services/raster_validation.py:600-720
def _detect_raster_type(src):
    """Auto-detect raster type from band count, dtype, and color interpretation."""
    band_count = src.count
    dtype = src.dtypes[0]
    colorinterp = src.colorinterp

    # RGB: 3 bands, uint8, RGB color interpretation
    if band_count == 3 and dtype == 'uint8' and colorinterp == (ColorInterp.red, ColorInterp.green, ColorInterp.blue):
        return "rgb"

    # RGBA: 4 bands, uint8, RGBA color interpretation
    if band_count == 4 and dtype == 'uint8':
        return "rgba"

    # DEM: 1 band, float32
    if band_count == 1 and dtype in ['float32', 'float64']:
        return "dem"

    # Categorical: 1 band, uint8/uint16
    if band_count == 1 and dtype in ['uint8', 'uint16']:
        return "categorical"

    # Multispectral: > 3 bands
    if band_count > 3:
        return "multispectral"

    return "unknown"
```

---

## 12. Stage 2: Create COG

### 12.1 Task Creation

### File: [jobs/process_raster.py:475-540](jobs/process_raster.py)

```python
# jobs/process_raster.py:475-540
elif stage == 2:
    # Stage 2: Single task to create COG
    # Uses validation results from Stage 1
    if not previous_results:
        raise ValueError("Stage 2 requires Stage 1 validation results")

    validation_result = previous_results[0]
    if not validation_result.get('success'):
        raise ValueError(f"Stage 1 validation failed: {validation_result.get('error')}")

    result_data = validation_result['result']

    # Extract validated metadata
    source_crs = result_data['source_crs']
    raster_type = result_data.get('raster_type', {})

    # Generate output blob name
    from config import get_config
    config = get_config()

    blob_name = job_params['blob_name']
    output_tier = job_params.get('output_tier', 'analysis')
    output_folder = job_params.get('output_folder')

    # Generate output path: cogs/{folder}/{name}_cog_{tier}.tif
    base_name = blob_name.rsplit('.', 1)[0]
    output_blob_name = f"{output_folder}/{base_name}_cog_{output_tier}.tif" if output_folder else f"{base_name}_cog_{output_tier}.tif"

    task_id = generate_deterministic_task_id(job_id, 2, "create_cog")
    return [
        {
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
                "jpeg_quality": job_params.get("jpeg_quality", 85),
                "in_memory": job_params.get("in_memory")
            }
        }
    ]
```

### 12.2 Task Handler Execution

### File: [services/raster_cog.py:60-550](services/raster_cog.py)

```python
# services/raster_cog.py:60-550
def create_cog(params: dict) -> dict:
    """
    Create Cloud Optimized GeoTIFF with optional reprojection.

    Uses rio-cogeo single-pass reprojection + COG creation.
    """
    container_name = params['container_name']
    blob_name = params['blob_name']
    output_blob_name = params['output_blob_name']
    source_crs = params['source_crs']
    target_crs = params.get('target_crs', 'EPSG:4326')
    raster_type = params.get('raster_type', {}).get('detected_type', 'unknown')
    optimal_settings = params.get('raster_type', {}).get('optimal_cog_settings', {})
    output_tier = params.get('output_tier', 'analysis')

    # STEP 1: Get tier-specific COG profile
    from config import get_config
    config = get_config()
    tier_profile = config.get_tier_profile(output_tier, raster_type)

    # STEP 2: Generate SAS URL for input blob
    blob_repo = BlobRepository.instance()
    blob_url = blob_repo.get_blob_url_with_sas(container_name, blob_name, hours=2)

    # STEP 3: Build COG profile
    from rio_cogeo.profiles import cog_profiles
    cog_profile = cog_profiles.get("lzw")  # Base profile
    cog_profile.update({
        "compress": tier_profile['compression'],
        "interleave": "band",  # Cloud-native selective band access
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512
    })

    if tier_profile['compression'] == "jpeg":
        cog_profile["jpeg_quality"] = params.get("jpeg_quality", 85)

    # STEP 4: Single-pass reproject + COG creation
    from rio_cogeo.cogeo import cog_translate
    from rasterio.enums import Resampling

    reproject_method = optimal_settings.get('reproject_resampling', 'bilinear')
    overview_method = optimal_settings.get('overview_resampling', 'average')

    in_memory = params.get('in_memory', config.raster_cog_in_memory)

    if in_memory:
        # In-memory processing (faster for small files <1GB)
        with rasterio.MemoryFile() as memfile:
            cog_translate(
                f"/vsicurl/{blob_url}",
                memfile.name,
                cog_profile,
                dst_kwargs={"crs": target_crs},
                resampling=Resampling[reproject_method],
                overview_resampling=Resampling[overview_method],
                in_memory=True
            )
            cog_data = memfile.read()
    else:
        # Disk-based processing (better for large files >1GB)
        with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
            cog_translate(
                f"/vsicurl/{blob_url}",
                tmp.name,
                cog_profile,
                dst_kwargs={"crs": target_crs},
                resampling=Resampling[reproject_method],
                overview_resampling=Resampling[overview_method]
            )
            with open(tmp.name, 'rb') as f:
                cog_data = f.read()
            os.unlink(tmp.name)

    # STEP 5: Upload COG to silver container
    silver_container = config.get_silver_container_name(output_tier)
    blob_repo.write_blob(silver_container, output_blob_name, cog_data)

    # STEP 6: Extract bounds in EPSG:4326
    with rasterio.open(io.BytesIO(cog_data)) as cog_src:
        bounds_4326 = list(cog_src.bounds)
        shape = [cog_src.height, cog_src.width]
        size_mb = len(cog_data) / (1024 * 1024)

    # SUCCESS
    return {
        "success": True,
        "result": {
            "cog_blob": output_blob_name,
            "cog_container": silver_container,
            "cog_tier": output_tier,
            "storage_tier": tier_profile['storage_tier'],
            "source_blob": blob_name,
            "source_container": container_name,
            "reprojection_performed": source_crs != target_crs,
            "source_crs": source_crs,
            "target_crs": target_crs,
            "bounds_4326": bounds_4326,
            "shape": shape,
            "size_mb": round(size_mb, 2),
            "compression": tier_profile['compression'],
            "raster_type": raster_type
        }
    }
```

---

## 13. Stage 3: Create STAC Metadata

### 13.1 Task Creation

### File: [jobs/process_raster.py:542-609](jobs/process_raster.py)

```python
# jobs/process_raster.py:542-609
elif stage == 3:
    # Stage 3: Single task to create STAC metadata
    # Uses COG results from Stage 2
    if not previous_results:
        raise ValueError("Stage 3 requires Stage 2 COG results")

    cog_result = previous_results[0]
    if not cog_result.get('success'):
        raise ValueError(f"Stage 2 COG creation failed: {cog_result.get('error')}")

    result_data = cog_result['result']

    # Extract COG metadata
    cog_blob = result_data['cog_blob']
    cog_container = result_data['cog_container']

    # Get collection ID from params or use default
    from config import get_config
    config = get_config()
    collection_id = job_params.get('collection_id') or config.stac_default_collection

    # Generate custom item_id if provided
    item_id = job_params.get('item_id')

    task_id = generate_deterministic_task_id(job_id, 3, "create_stac")
    return [
        {
            "task_id": task_id,
            "task_type": "extract_stac_metadata",
            "parameters": {
                "container_name": cog_container,
                "blob_name": cog_blob,
                "collection_id": collection_id,
                "item_id": item_id
            }
        }
    ]
```

### 13.2 Task Handler Execution

### File: [services/stac_catalog.py:100-450](services/stac_catalog.py)

```python
# services/stac_catalog.py:100-450
def extract_stac_metadata(params: dict) -> dict[str, Any]:
    """
    Stage 3: Extract STAC metadata for a single raster file.

    Extracts STAC Item metadata and inserts into PgSTAC database.
    """
    container_name = params["container_name"]
    blob_name = params["blob_name"]
    collection_id = params.get("collection_id", "dev")
    item_id = params.get("item_id")  # Optional custom ID

    # STEP 1: Initialize STAC service
    from .service_stac_metadata import StacMetadataService
    stac_service = StacMetadataService()

    # STEP 2: Extract STAC Item from COG
    item = stac_service.extract_item_from_blob(
        container_name=container_name,
        blob_name=blob_name,
        collection_id=collection_id,
        item_id=item_id
    )

    # STEP 3: Initialize PgSTAC infrastructure
    from infrastructure.pgstac_bootstrap import PgStacBootstrap
    stac_infra = PgStacBootstrap()

    # STEP 4: Insert into PgSTAC (with idempotency check)
    if stac_infra.item_exists(item.id, collection_id):
        insert_result = {
            'success': True,
            'skipped': True,
            'reason': 'Item already exists (idempotent operation)'
        }
    else:
        insert_result = stac_infra.insert_item(item, collection_id)

    # STEP 5: Extract metadata for response
    item_dict = item.model_dump(mode='json', by_alias=True)
    bbox = item.bbox

    # SUCCESS
    return {
        "success": True,
        "result": {
            "item_id": item.id,
            "blob_name": blob_name,
            "collection_id": collection_id,
            "bbox": bbox,
            "inserted_to_pgstac": insert_result.get('success', False),
            "item_skipped": insert_result.get('skipped', False),
            "stac_item": item_dict
        }
    }
```

---

## 14. CoreMachine: Task Message Processing

### File: [core/machine.py:552-1038](core/machine.py)

Each task is processed by CoreMachine:

```python
# core/machine.py:552-900
def process_task_message(self, task_message: TaskQueueMessage) -> Dict[str, Any]:
    # Step 1: Get task handler from registry
    handler = self.handlers_registry[task_message.task_type]

    # Step 2: Update task status to PROCESSING
    self.state_manager.update_task_status_direct(task_message.task_id, TaskStatus.PROCESSING)

    # Step 3: Execute task handler
    raw_result = handler(task_message.parameters)

    # Step 4: Convert dict to TaskResult
    result = TaskResult(
        task_id=task_message.task_id,
        task_type=task_message.task_type,
        status=TaskStatus.COMPLETED if raw_result['success'] else TaskStatus.FAILED,
        result_data=raw_result,
    )

    # Step 5: Complete task and check stage (atomic)
    completion = self.state_manager.complete_task_with_sql(
        task_message.task_id,
        task_message.parent_job_id,
        task_message.stage,
        result
    )

    # Step 6: Handle stage completion (last task completion detection)
    if completion.stage_complete:
        self._handle_stage_completion(
            task_message.parent_job_id,
            task_message.job_type,
            task_message.stage
        )
```

---

## 15. Stage Completion: Advance to Next Stage

### File: [core/machine.py:1217-1430](core/machine.py)

```python
# core/machine.py:1217-1304
def _handle_stage_completion(self, job_id, job_type, completed_stage):
    """
    Handle stage completion by advancing or completing job.
    """
    # Get workflow to check total stages
    workflow = self.jobs_registry[job_type]
    stages = workflow.stages
    total_stages = len(stages)

    if completed_stage < total_stages:
        # Advance to next stage
        next_stage = completed_stage + 1
        self._advance_stage(job_id, job_type, next_stage)
    else:
        # Complete job (all stages done)
        self._complete_job(job_id, job_type)
```

### Stage Advancement:

```python
# core/machine.py:1306-1430
def _advance_stage(self, job_id, job_type, next_stage):
    # Update job status to QUEUED
    self.state_manager.update_job_status(job_id, JobStatus.QUEUED)

    # Create job message for next stage
    next_message = JobQueueMessage(
        job_id=job_id,
        job_type=job_type,
        parameters=job_record.parameters,
        stage=next_stage,
        correlation_id=str(uuid.uuid4())[:8]
    )

    # Send to job queue
    self.service_bus.send_message(self.config.job_processing_queue, next_message)
```

---

## 16. Job Completion and Result Aggregation

### File: [jobs/process_raster.py:611-758](jobs/process_raster.py)

```python
# jobs/process_raster.py:611-758
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
    stac_tasks = [t for t in task_results if t.task_type == "extract_stac_metadata"]

    # Extract validation metadata
    validation_result = validation_tasks[0].result_data.get('result', {})
    warnings = validation_result.get('warnings', [])
    raster_type = validation_result.get('raster_type', {}).get('detected_type', 'unknown')

    # Extract COG metadata
    cog_result = cog_tasks[0].result_data.get('result', {})
    cog_blob = cog_result.get('cog_blob')
    cog_container = cog_result.get('cog_container')
    size_mb = cog_result.get('size_mb')
    compression = cog_result.get('compression')
    reprojection_performed = cog_result.get('reprojection_performed', False)

    # Extract STAC metadata
    stac_result = stac_tasks[0].result_data.get('result', {})
    item_id = stac_result.get('item_id')
    bbox = stac_result.get('bbox')
    collection_id = stac_result.get('collection_id')
    inserted_to_pgstac = stac_result.get('inserted_to_pgstac', False)

    # Generate TiTiler URLs
    from config import get_config
    config = get_config()
    titiler_urls = config.generate_titiler_urls(collection_id, item_id)
    share_url = titiler_urls.get('viewer_url')

    return {
        "job_type": "process_raster",
        "source_blob": params.get("blob_name"),
        "source_container": params.get("container_name"),
        "validation": {
            "warnings": warnings,
            "raster_type": raster_type,
            "source_crs": validation_result.get('source_crs'),
            "bit_depth_efficient": validation_result.get('bit_depth_check', {}).get('efficient')
        },
        "cog": {
            "cog_blob": cog_blob,
            "cog_container": cog_container,
            "size_mb": size_mb,
            "compression": compression,
            "reprojection_performed": reprojection_performed
        },
        "stac": {
            "item_id": item_id,
            "collection_id": collection_id,
            "bbox": bbox,
            "inserted_to_pgstac": inserted_to_pgstac,
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

## 17. Handler Registry

### File: [services/__init__.py:104-138](services/__init__.py)

All task handlers are explicitly registered:

```python
# services/__init__.py:104-138
from .raster_validation import validate_raster
from .raster_cog import create_cog
from .stac_catalog import extract_stac_metadata

ALL_HANDLERS = {
    # ... other handlers ...
    "validate_raster": validate_raster,           # Stage 1
    "create_cog": create_cog,                     # Stage 2
    "extract_stac_metadata": extract_stac_metadata,  # Stage 3
    # ... other handlers ...
}
```

---

## 18. Complete Execution Flow Diagram

```
HTTP POST /api/jobs/submit/process_raster
    ↓
[JobSubmissionTrigger.process_request]
    ↓
1. Extract job_type from URL path ("process_raster")
2. Extract JSON body (blob_name, container_name, output_tier, etc.)
3. Get ProcessRasterWorkflow from ALL_JOBS registry
4. Call ProcessRasterWorkflow.validate_job_parameters()
   ├─ Validate required parameters
   ├─ Check blob existence (early validation)
   └─ Return validated parameters
    ↓
5. Call ProcessRasterWorkflow.generate_job_id() → SHA256 hash
    ↓
6. Check for existing job (idempotency)
   ├─ If completed: return cached result
   └─ If in-progress: return current status
    ↓
7. Call ProcessRasterWorkflow.create_job_record()
   └─ Persist JobRecord to PostgreSQL app.jobs
    ↓
8. Call ProcessRasterWorkflow.queue_job()
   └─ Send JobQueueMessage to Service Bus geospatial-jobs queue
    ↓
9. Return HTTP 200 with job_id and queue_info

═══════════════════════════════════════════════════════════════════

Service Bus triggers JobProcessor (timer or HTTP)
    ↓
[CoreMachine.process_job_message]
    ↓
1. Load JobRecord from PostgreSQL
2. Call ProcessRasterWorkflow.create_tasks_for_stage(stage=1, ...)
   └─ Returns 1 task: validate_raster (with SAS URL)
    ↓
3. Create TaskRecord in PostgreSQL app.tasks
    ↓
4. Send TaskQueueMessage to Service Bus geospatial-tasks queue
    ↓
5. Update JobRecord.stage = 1, status = 'processing'

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor (timer or HTTP)
    ↓
[CoreMachine.process_task_message]
    ↓
STAGE 1 TASK EXECUTION:
    ├─ Get handler: ALL_HANDLERS['validate_raster']
    ├─ Call validate_raster(parameters)
    │   ├─ Open raster via /vsicurl/ + SAS URL
    │   ├─ Validate CRS (file metadata or user override)
    │   ├─ Check bit-depth efficiency (flag 64-bit)
    │   ├─ Auto-detect raster type (RGB, DEM, etc.)
    │   ├─ Generate optimal COG settings
    │   └─ Determine applicable COG tiers
    ├─ Update TaskRecord.status = 'completed', result_data = {...}
    └─ Atomic: Check if last task in stage → advance to Stage 2

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Auto-triggered for Stage 2
    ↓
1. Load JobRecord (stage=1)
2. Call ProcessRasterWorkflow.create_tasks_for_stage(stage=2, previous_results=[stage1_result])
   ├─ Extract validation metadata (source_crs, raster_type, optimal_settings)
   ├─ Generate output blob name (cogs/{folder}/{name}_cog_{tier}.tif)
   └─ Returns 1 task: create_cog
    ↓
3. Create TaskRecord in PostgreSQL app.tasks
    ↓
4. Send TaskQueueMessage to Service Bus geospatial-tasks queue
    ↓
5. Update JobRecord.stage = 2

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor
    ↓
STAGE 2 TASK EXECUTION:
    ├─ Get handler: ALL_HANDLERS['create_cog']
    ├─ Call create_cog(parameters)
    │   ├─ Get tier-specific COG profile (compression, resampling)
    │   ├─ Generate SAS URL for input blob
    │   ├─ Build rio-cogeo profile (BAND interleave, 512x512 tiles)
    │   ├─ Single-pass reproject + COG creation via cog_translate()
    │   ├─ Upload COG to silver container
    │   └─ Extract bounds in EPSG:4326
    ├─ Update TaskRecord.status = 'completed', result_data = {...}
    └─ Atomic: Check if last task in stage → advance to Stage 3

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Auto-triggered for Stage 3
    ↓
1. Load JobRecord (stage=2)
2. Call ProcessRasterWorkflow.create_tasks_for_stage(stage=3, previous_results=[stage2_result])
   ├─ Extract COG metadata (cog_blob, cog_container)
   ├─ Get collection_id from params or config
   └─ Returns 1 task: extract_stac_metadata
    ↓
3. Create TaskRecord in PostgreSQL app.tasks
    ↓
4. Send TaskQueueMessage to Service Bus geospatial-tasks queue
    ↓
5. Update JobRecord.stage = 3

═══════════════════════════════════════════════════════════════════

Service Bus triggers TaskProcessor
    ↓
STAGE 3 TASK EXECUTION:
    ├─ Get handler: ALL_HANDLERS['extract_stac_metadata']
    ├─ Call extract_stac_metadata(parameters)
    │   ├─ Initialize StacMetadataService
    │   ├─ Extract STAC Item from COG blob
    │   ├─ Initialize PgStacBootstrap
    │   ├─ Check if item exists (idempotency)
    │   └─ Insert into pgSTAC database (if not exists)
    ├─ Update TaskRecord.status = 'completed'
    └─ Atomic: Last task → mark job as 'completed'

═══════════════════════════════════════════════════════════════════

[CoreMachine.process_job_message] - Final job completion
    ↓
1. Load JobRecord (all stages complete)
2. Call ProcessRasterWorkflow.finalize_job(context)
   ├─ Separate tasks by stage
   ├─ Extract validation warnings and raster type
   ├─ Extract COG metadata (blob path, size, compression)
   ├─ Extract STAC metadata (item_id, bbox, collection_id)
   ├─ Generate TiTiler URLs (viewer, tilejson, tiles)
   └─ Return comprehensive job result
    ↓
3. Update JobRecord.status = 'completed', result_data = {...}

═══════════════════════════════════════════════════════════════════

End-to-End Result:
  - Bronze container: Original raster preserved
  - Silver container: COG created with cloud-optimized structure
  - pgSTAC: STAC item registered for metadata search
  - TiTiler: Ready for dynamic tile serving via /cog endpoint
  - HTTP Response: Complete with share URL and TiTiler endpoints
```

---

## 19. Key Files Reference

| Component | File | Key Lines |
|-----------|------|-----------|
| HTTP Trigger | [function_app.py](function_app.py) | 566-569 |
| Job Submission | [triggers/submit_job.py](triggers/submit_job.py) | 147-309 |
| Job Definition | [jobs/process_raster.py](jobs/process_raster.py) | 62-758 |
| Job Registry | [jobs/__init__.py](jobs/__init__.py) | 64, 89 |
| Stage 1 Handler | [services/raster_validation.py](services/raster_validation.py) | 118-720 |
| Stage 2 Handler | [services/raster_cog.py](services/raster_cog.py) | 60-550 |
| Stage 3 Handler | [services/stac_catalog.py](services/stac_catalog.py) | 100-450 |
| Handler Registry | [services/__init__.py](services/__init__.py) | 104-138 |
| CoreMachine | [core/machine.py](core/machine.py) | 312-1742 |
| Job Base Class | [jobs/base.py](jobs/base.py) | Full file |

---

## 20. Key Design Patterns

### 20.1 Job → Stage → Task Abstraction

```
JOB (Controller Layer - Orchestration)
 ├── STAGE 1 (validate_raster - Single Task)
 │   └── Task: validate_raster
 │                     ↓ Stage 1 completes
 ├── STAGE 2 (create_cog - Single Task)
 │   └── Task: create_cog (uses Stage 1 results)
 │                     ↓ Stage 2 completes
 ├── STAGE 3 (create_stac - Single Task)
 │   └── Task: extract_stac_metadata (uses Stage 2 results)
 │                     ↓ Stage 3 completes
 └── COMPLETION (finalize_job aggregation)
```

### 20.2 Idempotency via SHA256

- Same parameters always produce same `job_id`
- Duplicate submissions return existing job
- Prevents wasted compute on re-submissions

### 20.3 Data Flow Between Stages

- **Stage 1 → Stage 2**: Validation metadata (CRS, raster type, optimal settings)
- **Stage 2 → Stage 3**: COG metadata (blob path, bounds, container)
- **Stage 3 → Finalization**: STAC metadata (item_id, collection_id, bbox)

### 20.4 Early Validation Pattern

- Blob existence checked at job submission time
- Container existence checked at job submission time
- Errors raised before any Service Bus messages queued

### 20.5 Single-Pass COG Creation

- `rio-cogeo.cog_translate()` combines reprojection + COG creation
- No intermediate files needed
- Optimal for files <= 1GB

### 20.6 Type-Specific Optimization

- **RGB**: JPEG compression (97% reduction), cubic resampling
- **RGBA**: WebP compression (supports alpha), cubic resampling
- **DEM**: LERC+DEFLATE (lossless scientific), bilinear reproject
- **Categorical**: DEFLATE, mode overviews, nearest reproject

### 20.7 Cloud-Native BAND Interleave

- Allows selective band access via HTTP range requests
- Optimal for multispectral analysis
- Replaces legacy PIXEL interleave (all bands read even when querying one)

---

## 21. Testing the Workflow

### Submit a Job:

```bash
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/submit/process_raster \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "dctest.tif",
    "container_name": "rmhazuregeobronze",
    "output_tier": "analysis",
    "output_folder": "cogs/my_test"
  }'
```

### Check Job Status:

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

### Access COG via TiTiler:

```bash
# Interactive viewer (from result.share_url)
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/map.html?url=%2Fvsiaz%2Fsilver-cogs%2Fcogs%2Fmy_test%2Fdctest_cog_analysis.tif

# Preview thumbnail (512px)
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/preview.png?url=%2Fvsiaz%2Fsilver-cogs%2Fcogs%2Fmy_test%2Fdctest_cog_analysis.tif&max_size=512

# TileJSON spec
https://rmhtitiler-ghcyd7g0bxdvc2hc.eastus-01.azurewebsites.net/cog/WebMercatorQuad/tilejson.json?url=%2Fvsiaz%2Fsilver-cogs%2Fcogs%2Fmy_test%2Fdctest_cog_analysis.tif
```

---

## 22. Execution Timing

**Real Example** (21 NOV 2025 - dctest.tif 27 MB RGB GeoTIFF):

| Stage | Operation | Duration | Notes |
|-------|-----------|----------|-------|
| 1 | Validate raster | ~3 seconds | CRS check, type detection, bit-depth analysis |
| 2 | Create COG | ~10 seconds | Single-pass reproject + COG (DEFLATE compression) |
| 3 | Create STAC | ~9 seconds | Extract metadata + insert into pgSTAC |
| **Total** | **End-to-end** | **~22 seconds** | Bronze → Silver (COG) + STAC cataloging |

**Output**:
- COG Size: 127.58 MB (DEFLATE compression)
- STAC Inserted: Yes
- TiTiler URLs: 9 endpoints generated (viewer, preview, tiles, etc.)

---
