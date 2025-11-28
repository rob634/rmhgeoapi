# INGEST_VECTOR Workflow Trace-Through

**Date**: 22 NOV 2025
**Status**: Reference Documentation
**Wiki**: Azure DevOps Wiki - Technical workflow documentation

---

## Overview

The `ingest_vector` job is a **three-stage fan-out workflow** that ingests vector files into PostGIS with parallel chunk uploads and STAC cataloging. This document traces the complete execution flow from HTTP request to job completion.

### Workflow Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INGEST_VECTOR WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  HTTP Request                                                                │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────────────┐                                                         │
│  │ Stage 1: Single │  Load file, validate, chunk, pickle to blob storage     │
│  │ prepare_chunks  │  OUTPUT: List of chunk paths                            │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 2: Fan-Out│  Create table ONCE, then N parallel tasks upload chunks │
│  │ upload_chunks   │  OUTPUT: N task results with rows_uploaded              │
│  │ (N parallel)    │                                                         │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Stage 3: Single │  Create STAC Item in pgstac for PostGIS table           │
│  │ create_stac     │  OUTPUT: STAC item_id, bbox, feature_count              │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │   Job Complete  │  Aggregate results, generate OGC Features URLs          │
│  │   finalize_job  │                                                         │
│  └─────────────────┘                                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Supported File Formats

| Format | Extension | Converter Parameters |
|--------|-----------|---------------------|
| CSV | `.csv` | `lat_name`, `lon_name` OR `wkt_column` |
| GeoJSON | `.geojson`, `.json` | None required |
| GeoPackage | `.gpkg` | `layer_name` (required) |
| KML | `.kml` | None required |
| KMZ | `.kmz` | None required |
| Shapefile | `.shp`, `.zip` | None required |

---

## 1. Entry Point: HTTP Request

### File: [triggers/ingest_vector.py](triggers/ingest_vector.py)
### Endpoint: `POST /api/jobs/ingest_vector`

The HTTP trigger receives a JSON request body and routes it through validation to job creation.

**Request Body Example:**
```json
{
    "blob_name": "data/parcels.gpkg",
    "file_extension": "gpkg",
    "table_name": "parcels_2025",
    "container_name": "rmhazuregeobronze",
    "schema": "geo",
    "chunk_size": 1000,
    "converter_params": {
        "layer_name": "parcels"
    },
    "indexes": {
        "spatial": true,
        "attributes": ["county"],
        "temporal": []
    }
}
```

**Trigger Class Definition:**

```python
# triggers/ingest_vector.py:85-89
class IngestVectorTrigger(JobManagementTrigger):
    """Vector ingest HTTP trigger implementation."""

    def __init__(self):
        super().__init__("ingest_vector")
```

**Request Processing:**

```python
# triggers/ingest_vector.py:95-112
def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
    # Extract and validate request body
    req_body = self.extract_json_body(req, required=True)

    # Validate required fields
    self.validate_required_fields(req_body, ["blob_name", "file_extension", "table_name"])

    # Extract parameters
    blob_name = req_body["blob_name"]
    file_extension = req_body["file_extension"]
    table_name = req_body["table_name"]
    container_name = req_body.get("container_name", "rmhazuregeobronze")
    schema = req_body.get("schema", "geo")
    chunk_size = req_body.get("chunk_size")  # None = auto-calculate
    converter_params = req_body.get("converter_params", {})
```

---

## 2. Job Class Lookup

### File: [jobs/__init__.py](jobs/__init__.py)

The trigger looks up the job class from the explicit registry:

```python
# triggers/ingest_vector.py:128-137
from jobs import ALL_JOBS

if "ingest_vector" not in ALL_JOBS:
    raise ValueError(
        "Vector ingest job not registered. Available jobs: "
        f"{', '.join(ALL_JOBS.keys())}"
    )

job_class = ALL_JOBS["ingest_vector"]
```

**Job Registry Definition:**

```python
# jobs/__init__.py:62,87
from .ingest_vector import IngestVectorJob

ALL_JOBS = {
    # ... other jobs ...
    "ingest_vector": IngestVectorJob,
    # ... other jobs ...
}
```

---

## 3. Job Definition

### File: [jobs/ingest_vector.py](jobs/ingest_vector.py)

### 3.1 Class Metadata

```python
# jobs/ingest_vector.py:65-77
class IngestVectorJob(JobBase):
    """
    Two-stage vector ETL workflow with pickle-based intermediate storage.
    """

    # Job metadata
    job_type: str = "ingest_vector"
    description: str = "Load vector file and ingest to PostGIS with parallel chunked uploads"
```

### 3.2 Stage Definitions

```python
# jobs/ingest_vector.py:80-102
stages: List[Dict[str, Any]] = [
    {
        "number": 1,
        "name": "prepare_chunks",
        "task_type": "prepare_vector_chunks",
        "description": "Load file, validate, chunk, pickle to blob storage",
        "parallelism": "single"
    },
    {
        "number": 2,
        "name": "upload_chunks",
        "task_type": "upload_pickled_chunk",
        "description": "Upload pickled chunks to PostGIS in parallel",
        "parallelism": "fan_out"
    },
    {
        "number": 3,
        "name": "create_stac_record",
        "task_type": "create_vector_stac",
        "description": "Create internal STAC record for PostGIS table",
        "parallelism": "single"
    }
]
```

### 3.3 Parameters Schema

```python
# jobs/ingest_vector.py:105-120
parameters_schema: Dict[str, Any] = {
    "blob_name": {"type": "str", "required": True},
    "file_extension": {"type": "str", "required": True},
    "table_name": {"type": "str", "required": True},
    "container_name": {"type": "str", "default": "rmhazuregeobronze"},
    "schema": {"type": "str", "default": "geo"},
    "chunk_size": {"type": "int", "default": None},  # Auto-calculate if None
    "converter_params": {"type": "dict", "default": {}},
    "indexes": {"type": "dict", "default": {
        "spatial": True,
        "attributes": [],
        "temporal": []
    }},
    "geometry_params": {"type": "dict", "default": {}},
    "render_params": {"type": "dict", "default": {}}
}
```

---

## 4. Parameter Validation

### File: [jobs/ingest_vector.py:122-379](jobs/ingest_vector.py)

The `validate_job_parameters()` method performs comprehensive validation:

### 4.1 Required Fields Validation

```python
# jobs/ingest_vector.py:161-194
# Required: blob_name
if "blob_name" not in params:
    raise ValueError("blob_name is required")
blob_name = params["blob_name"]
if not isinstance(blob_name, str) or not blob_name.strip():
    raise ValueError("blob_name must be a non-empty string")

# Required: file_extension - validate supported formats
supported = ['csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip']
ext = file_extension.lower().lstrip('.')
if ext not in supported:
    raise ValueError(f"file_extension '{ext}' not supported. Supported: {', '.join(supported)}")

# Required: table_name - PostgreSQL identifier rules
if not table_name[0].isalpha():
    raise ValueError("table_name must start with a letter")
if not all(c.isalnum() or c == '_' for c in table_name):
    raise ValueError("table_name must contain only letters, numbers, and underscores")
```

### 4.2 Table Existence Check (Early Validation)

```python
# jobs/ingest_vector.py:311-350
from infrastructure.postgis import check_table_exists

table_exists = check_table_exists(schema, table_name)

if table_exists:
    raise ValueError(
        f"Table {schema}.{table_name} already exists. "
        f"To replace it, drop the table first:\n"
        f"  DROP TABLE {schema}.{table_name} CASCADE;\n"
        f"Or choose a different table_name."
    )
```

### 4.3 Blob Existence Check (Early Validation)

```python
# jobs/ingest_vector.py:352-377
from infrastructure.blob import BlobRepository

blob_repo = BlobRepository.instance()

# Validate container exists
if not blob_repo.container_exists(container_name):
    raise ResourceNotFoundError(
        f"Container '{container_name}' does not exist"
    )

# Validate blob exists
if not blob_repo.blob_exists(container_name, blob_name):
    raise ResourceNotFoundError(
        f"File '{blob_name}' not found in container '{container_name}'"
    )
```

---

## 5. Job ID Generation (Idempotency)

### File: [jobs/ingest_vector.py:381-391](jobs/ingest_vector.py)

Job ID is deterministically generated from parameters using SHA256:

```python
# jobs/ingest_vector.py:381-391
@staticmethod
def generate_job_id(params: dict) -> str:
    """
    Generate deterministic job ID from parameters.
    Same parameters = same job ID (idempotency).
    """
    param_str = json.dumps(params, sort_keys=True)
    job_hash = hashlib.sha256(param_str.encode()).hexdigest()
    return job_hash
```

Same parameters always produce the same job ID, enabling:
- Duplicate submission detection
- Idempotent operations (return existing job if already completed)

---

## 6. Idempotency Check

### File: [triggers/ingest_vector.py:160-190](triggers/ingest_vector.py)

Before creating a new job, check if it already exists:

```python
# triggers/ingest_vector.py:160-190
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

### File: [jobs/ingest_vector.py:393-433](jobs/ingest_vector.py)

Create and persist the job record to PostgreSQL:

```python
# jobs/ingest_vector.py:393-433
@staticmethod
def create_job_record(job_id: str, params: dict) -> dict:
    from infrastructure import RepositoryFactory
    from core.models import JobRecord, JobStatus

    job_record = JobRecord(
        job_id=job_id,
        job_type="ingest_vector",
        parameters=params,
        status=JobStatus.QUEUED,
        stage=1,
        total_stages=3,  # Stage 1: prepare, Stage 2: upload, Stage 3: STAC
        stage_results={},
        metadata={
            "description": "Load vector file and ingest to PostGIS...",
            "created_by": "IngestVectorJob",
            "blob_name": params.get("blob_name"),
            "table_name": params.get("table_name"),
            "file_extension": params.get("file_extension"),
            "container_name": params.get("container_name")
        }
    )

    # Persist to database
    repos = RepositoryFactory.create_repositories()
    job_repo = repos['job_repo']
    job_repo.create_job(job_record)

    return job_record.model_dump()
```

**Database Table**: `app.jobs`
**Columns**: job_id (PK), job_type, parameters (JSONB), status (enum), stage, total_stages, stage_results (JSONB), metadata (JSONB), created_at, updated_at

---

## 8. Job Queuing to Service Bus

### File: [jobs/ingest_vector.py:435-487](jobs/ingest_vector.py)

Queue the job message to Service Bus for processing:

```python
# jobs/ingest_vector.py:435-487
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
        job_type="ingest_vector",
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

### File: [triggers/ingest_vector.py:201-209](triggers/ingest_vector.py)

The trigger returns the job creation response:

```python
# triggers/ingest_vector.py:201-209
return {
    "job_id": job_id,
    "status": "created",
    "job_type": "ingest_vector",
    "message": "Vector ETL job created and queued for processing",
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
    job_class = self.jobs_registry[job_message.job_type]

    # Step 2: Get job record from database
    job_record = self.repos['job_repo'].get_job(job_message.job_id)

    # Step 3: Update job status to PROCESSING
    self.state_manager.update_job_status(job_message.job_id, JobStatus.PROCESSING)

    # Step 4: Fetch previous stage results (for fan-out pattern)
    previous_results = None
    if job_message.stage > 1:
        previous_results = self._get_completed_stage_results(
            job_message.job_id,
            job_message.stage - 1
        )

    # Step 5: Generate task definitions
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

## 11. Stage 1: Prepare Vector Chunks

### 11.1 Task Creation

### File: [jobs/ingest_vector.py:511-536](jobs/ingest_vector.py)

```python
# jobs/ingest_vector.py:511-536
if stage == 1:
    # Stage 1: Single task to load, validate, chunk, pickle
    task_id = generate_deterministic_task_id(job_id, 1, "prepare")
    return [
        {
            "task_id": task_id,
            "task_type": "prepare_vector_chunks",
            "parameters": {
                "job_id": job_id,
                "blob_name": job_params["blob_name"],
                "container_name": job_params["container_name"],
                "file_extension": job_params["file_extension"],
                "table_name": job_params["table_name"],
                "schema": job_params["schema"],
                "chunk_size": job_params.get("chunk_size"),
                "converter_params": job_params.get("converter_params", {}),
                "indexes": job_params.get("indexes", {...}),
                "geometry_params": job_params.get("geometry_params", {}),
            }
        }
    ]
```

### 11.2 Task Handler Execution

### File: [services/vector/tasks.py:175-292](services/vector/tasks.py)

```python
# services/vector/tasks.py:175-292
def prepare_vector_chunks(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 1 Task: Load, validate, chunk, and pickle GeoDataFrame.
    """
    # 1. Load vector file from blob storage
    blob_repo = BlobRepository.instance()
    file_data = blob_repo.read_blob_to_stream(container_name, blob_name)

    # 2. Convert to GeoDataFrame using format-specific converter
    converters = {
        'csv': _convert_csv,
        'geojson': _convert_geojson,
        'gpkg': _convert_geopackage,
        'kml': _convert_kml,
        'kmz': _convert_kmz,
        'shp': _convert_shapefile,
        'zip': _convert_shapefile
    }
    gdf = converters[file_extension](file_data, **converter_params)

    # 3. Validate, prepare, and optionally process geometries
    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params)

    # 4. Calculate optimal chunk size and split
    chunks = handler.chunk_gdf(validated_gdf, chunk_size)

    # 5. Pickle each chunk to temp blob storage
    chunk_paths = []
    for i, chunk in enumerate(chunks):
        chunk_path = f"{config.vector_pickle_prefix}/{job_id}/chunk_{i}.pkl"
        pickled = pickle.dumps(chunk, protocol=5)
        blob_repo.write_blob(config.vector_pickle_container, chunk_path, pickled)
        chunk_paths.append(chunk_path)

    return {
        "success": True,
        "result": {
            'chunk_paths': chunk_paths,
            'table_name': table_name,
            'schema': schema,
            'total_rows': len(validated_gdf),
            'chunk_count': len(chunks),
        }
    }
```

### 11.3 GeoDataFrame Validation

### File: [services/vector/postgis_handler.py:63-325](services/vector/postgis_handler.py)

The `prepare_gdf()` method performs comprehensive geometry validation:

```python
# services/vector/postgis_handler.py:63-325
def prepare_gdf(self, gdf: gpd.GeoDataFrame, geometry_params: dict = None):
    """
    Operations:
    1. Remove null geometries
    2. Fix invalid geometries (buffer(0) trick)
    3. Force 2D geometries (remove Z/M dimensions)
    4. Normalize to Multi- geometry types (ArcGIS compatibility)
    5. Validate PostGIS supported geometry types
    6. Reproject to EPSG:4326 if needed
    7. Clean column names (lowercase, replace spaces)
    8. Apply optional simplification or quantization
    """
```

---

## 12. Stage 2: Upload Chunks (Fan-Out Parallel)

### 12.1 Task Creation with Deadlock Fix

### File: [jobs/ingest_vector.py:538-609](jobs/ingest_vector.py)

```python
# jobs/ingest_vector.py:538-609
elif stage == 2:
    # Stage 2: FAN-OUT - Create one task per pickled chunk
    if not previous_results:
        raise ValueError("Stage 2 requires Stage 1 results for fan-out")

    # Extract chunk paths from Stage 1 result
    stage_1_result = previous_results[0]
    chunk_paths = stage_1_result['result']['chunk_paths']
    table_name = stage_1_result['result']['table_name']
    schema = stage_1_result['result']['schema']

    # Serialize table creation to avoid PostgreSQL deadlocks
    # during parallel INSERT operations in Stage 2 tasks.
    logger.info(f"Creating table {schema}.{table_name}...")

    # Load first chunk to get schema
    blob_repo = BlobRepository.instance()
    blob_data = blob_repo.read_blob(config.vector_pickle_container, chunk_paths[0])
    first_chunk = pickle.loads(blob_data)

    # Create table using PostGIS handler with index configuration
    postgis_handler = VectorToPostGISHandler()
    postgis_handler.create_table_only(first_chunk, table_name, schema, indexes)

    logger.info(f"Table {schema}.{table_name} created successfully")

    # Create one task per chunk with deterministic ID
    tasks = []
    for i, chunk_path in enumerate(chunk_paths):
        task_id = generate_deterministic_task_id(job_id, 2, f"chunk_{i}")
        tasks.append({
            "task_id": task_id,
            "task_type": "upload_pickled_chunk",
            "parameters": {
                "chunk_path": chunk_path,
                "table_name": table_name,
                "schema": schema,
                "chunk_index": i
            }
        })

    return tasks
```

### 12.2 Table Creation (DDL Only)

### File: [services/vector/postgis_handler.py:472-495](services/vector/postgis_handler.py)

```python
# services/vector/postgis_handler.py:472-495
def create_table_only(self, chunk, table_name, schema, indexes=None):
    """
    Create PostGIS table without inserting data (DDL only).
    Used for serialized table creation to avoid deadlocks.
    """
    with self._pg_repo._get_connection() as conn:
        with conn.cursor() as cur:
            self._create_table_if_not_exists(cur, chunk, table_name, schema, indexes)
            conn.commit()
```

### 12.3 Task Handler Execution (Parallel)

### File: [services/vector/tasks.py:296-405](services/vector/tasks.py)

```python
# services/vector/tasks.py:296-405
def upload_pickled_chunk(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 2 Task: Load pickled chunk and upload to PostGIS.
    """
    chunk_path = parameters["chunk_path"]
    table_name = parameters["table_name"]
    schema = parameters.get("schema", "geo")
    chunk_index = parameters.get("chunk_index", 0)

    # 1. Load pickled chunk from blob storage
    blob_repo = BlobRepository.instance()
    pickled_data = blob_repo.read_blob(config.vector_pickle_container, chunk_path)
    chunk = pickle.loads(pickled_data)

    # 2. Insert data into PostGIS (table already created in Stage 2 setup)
    handler = VectorToPostGISHandler()
    handler.insert_features_only(chunk, table_name, schema)

    return {
        "success": True,
        "result": {
            'rows_uploaded': len(chunk),
            'chunk_path': chunk_path,
            'chunk_index': chunk_index,
            'table': f"{schema}.{table_name}",
        }
    }
```

---

## 13. Stage 3: Create STAC Record

### 13.1 Task Creation

### File: [jobs/ingest_vector.py:611-642](jobs/ingest_vector.py)

```python
# jobs/ingest_vector.py:611-642
elif stage == 3:
    # Stage 3: Create STAC Record - Single task to catalog PostGIS table
    if not previous_results:
        raise ValueError("Stage 3 requires Stage 2 results")

    stage_2_result = previous_results[0]
    result_data = stage_2_result['result']
    table_name = result_data['table'].split('.')[-1]
    schema = result_data['table'].split('.')[0]

    task_id = generate_deterministic_task_id(job_id, 3, "create_stac")
    return [
        {
            "task_id": task_id,
            "task_type": "create_vector_stac",
            "parameters": {
                "schema": schema,
                "table_name": table_name,
                "collection_id": "system-vectors",
                "source_file": job_params.get("blob_name"),
                "source_format": job_params.get("file_extension"),
                "job_id": job_id,
                "geometry_params": job_params.get("geometry_params", {})
            }
        }
    ]
```

### 13.2 Task Handler Execution

### File: [services/stac_vector_catalog.py:22-171](services/stac_vector_catalog.py)

```python
# services/stac_vector_catalog.py:22-171
def create_vector_stac(params: dict) -> dict[str, Any]:
    """
    Create System STAC Item for completed PostGIS table.
    """
    # STEP 1: Extract STAC Item from PostGIS table
    stac_service = StacVectorService()

    additional_properties = {
        "etl:job_id": job_id,
        "vector:source_format": source_format,
        "vector:source_file": source_file,
        "system:reserved": collection_id == "system-vectors",
        "created": datetime.utcnow().isoformat() + "Z"
    }

    item = stac_service.extract_item_from_table(
        schema=schema,
        table_name=table_name,
        collection_id=collection_id,
        additional_properties=additional_properties
    )

    # STEP 2: Insert into PgSTAC (with idempotency check)
    stac_infra = PgStacBootstrap()

    if stac_infra.item_exists(item.id, collection_id):
        insert_result = {'success': True, 'skipped': True}
    else:
        insert_result = stac_infra.insert_item(item, collection_id)

    return {
        "success": True,
        "result": {
            "item_id": item.id,
            "collection_id": collection_id,
            "bbox": bbox,
            "row_count": row_count,
            "inserted_to_pgstac": insert_result.get('success', False),
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

    # Step 6: Handle stage completion ("last task turns out lights")
    if completion.stage_complete:
        self._handle_stage_completion(
            task_message.parent_job_id,
            task_message.job_type,
            task_message.stage
        )
```

---

## 15. Stage Completion: Last Task Completion Detection Pattern

### File: [core/machine.py:1217-1304](core/machine.py)

When the last task in a stage completes, CoreMachine advances to the next stage or completes the job:

```python
# core/machine.py:1217-1304
def _handle_stage_completion(self, job_id, job_type, completed_stage):
    """
    Handle stage completion by advancing or completing job.
    This is the last task completion detection pattern.
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
    # Get job record for parameters
    job_record = self.repos['job_repo'].get_job(job_id)

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

### File: [core/machine.py:1432-1596](core/machine.py)

```python
# core/machine.py:1432-1596
def _complete_job(self, job_id, job_type):
    # Get all task records
    task_records = self.repos['task_repo'].get_tasks_for_job(job_id)

    # Convert to TaskResults
    task_results = [TaskResult(...) for tr in task_records]

    # Create context
    context = JobExecutionContext(
        job_id=job_id,
        job_type=job_type,
        current_stage=job_record.stage,
        total_stages=job_record.total_stages,
        parameters=job_record.parameters
    )
    context.task_results = task_results

    # Call job's finalize_job() method
    workflow = self.jobs_registry[job_type]
    final_result = workflow.finalize_job(context)

    # Complete job in database
    self.state_manager.complete_job(job_id, final_result)
```

### finalize_job() Implementation:

### File: [jobs/ingest_vector.py:647-771](jobs/ingest_vector.py)

```python
# jobs/ingest_vector.py:647-771
@staticmethod
def finalize_job(context) -> Dict[str, Any]:
    """
    Aggregate results from all completed tasks into job summary.
    """
    task_results = context.task_results
    params = context.parameters

    # Separate tasks by stage
    stage_1_tasks = [t for t in task_results if t.task_type == "prepare_vector_chunks"]
    stage_2_tasks = [t for t in task_results if t.task_type == "upload_pickled_chunk"]
    stage_3_tasks = [t for t in task_results if t.task_type == "create_vector_stac"]

    # Extract metadata from Stage 1
    total_chunks = stage_1_result.get("chunk_count", 0)

    # Aggregate Stage 2 upload results
    successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
    total_rows_uploaded = sum(t.result_data.get("result", {}).get("rows_uploaded", 0) for t in stage_2_tasks)

    # Extract STAC results from Stage 3
    stac_summary = {
        "collection_id": stac_result.get("collection_id"),
        "stac_id": stac_result.get("stac_id"),
        "bbox": stac_result.get("bbox")
    }

    # Generate OGC Features URL
    ogc_features_url = config.generate_ogc_features_url(table_name)
    viewer_url = config.generate_vector_viewer_url(table_name)

    return {
        "job_type": "ingest_vector",
        "blob_name": params.get("blob_name"),
        "table_name": table_name,
        "summary": {
            "total_chunks": total_chunks,
            "chunks_uploaded": successful_chunks,
            "total_rows_uploaded": total_rows_uploaded,
            "success_rate": f"{(successful_chunks / len(stage_2_tasks) * 100):.1f}%",
            "data_complete": failed_chunks == 0
        },
        "stac": stac_summary,
        "ogc_features_url": ogc_features_url,
        "viewer_url": viewer_url,
        "stages_completed": context.current_stage,
        "total_tasks_executed": len(task_results),
    }
```

---

## 17. Handler Registry

### File: [services/__init__.py:89-138](services/__init__.py)

All task handlers are explicitly registered:

```python
# services/__init__.py:89-138
from .vector.tasks import prepare_vector_chunks, upload_pickled_chunk
from .stac_vector_catalog import create_vector_stac

ALL_HANDLERS = {
    # ... other handlers ...
    # Vector ETL handlers (17 OCT 2025)
    "prepare_vector_chunks": prepare_vector_chunks,  # Stage 1
    "upload_pickled_chunk": upload_pickled_chunk,    # Stage 2 (parallel)
    "create_vector_stac": create_vector_stac,        # Stage 3
    # ... other handlers ...
}
```

---

## 18. Key Design Patterns

### 18.1 Job → Stage → Task Abstraction

```
JOB (Controller Layer - Orchestration)
 ├── STAGE 1 (prepare_chunks - Single Task)
 │   └── Task: prepare_vector_chunks
 │                     ↓ Stage 1 completes
 ├── STAGE 2 (upload_chunks - Parallel Fan-Out)
 │   ├── Task: upload_pickled_chunk (chunk 0)
 │   ├── Task: upload_pickled_chunk (chunk 1)
 │   ├── Task: upload_pickled_chunk (chunk N)
 │   └── ... (N tasks in parallel)
 │                     ↓ Last task completes stage
 ├── STAGE 3 (create_stac - Single Task)
 │   └── Task: create_vector_stac
 │                     ↓ Stage 3 completes
 └── COMPLETION (finalize_job aggregation)
```

### 18.2 Idempotency via SHA256

- Same parameters always produce same `job_id`
- Duplicate submissions return existing job
- Prevents wasted compute on re-submissions

### 18.3 Pickle Intermediate Storage

- Avoids Service Bus 256KB message size limit
- Large GeoDataFrame chunks stored in blob storage
- Stage 2 tasks load pickles, not pass data through queue

### 18.4 Deadlock Prevention

- Table created ONCE in Stage 2 task creation (before parallel uploads)
- Parallel tasks only INSERT data (no DDL operations)
- Prevents PostgreSQL lock contention

### 18.5 Last Task Completion Detection Pattern

- Atomic SQL operation detects stage completion
- Only the last task to complete triggers stage advancement
- Prevents race conditions in parallel task completion

### 18.6 Early Validation Pattern

- Table existence checked at job submission time
- Blob existence checked at job submission time
- Errors raised before any Service Bus messages queued

---

## 19. Key Files Reference

| Component | File | Key Lines |
|-----------|------|-----------|
| HTTP Trigger | [triggers/ingest_vector.py](triggers/ingest_vector.py) | 85-213 |
| Job Definition | [jobs/ingest_vector.py](jobs/ingest_vector.py) | 65-771 |
| Job Registry | [jobs/__init__.py](jobs/__init__.py) | 62, 87 |
| Stage 1 Handler | [services/vector/tasks.py](services/vector/tasks.py) | 175-292 |
| Stage 2 Handler | [services/vector/tasks.py](services/vector/tasks.py) | 296-405 |
| Stage 3 Handler | [services/stac_vector_catalog.py](services/stac_vector_catalog.py) | 22-171 |
| PostGIS Operations | [services/vector/postgis_handler.py](services/vector/postgis_handler.py) | Full file |
| Handler Registry | [services/__init__.py](services/__init__.py) | 89-138 |
| CoreMachine | [core/machine.py](core/machine.py) | 312-1742 |
| Job Base Class | [jobs/base.py](jobs/base.py) | Full file |

---

## 20. Testing the Workflow

### Submit a Job:

```bash
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/ingest_vector \
  -H "Content-Type: application/json" \
  -d '{
    "blob_name": "data/test_parcels.gpkg",
    "file_extension": "gpkg",
    "table_name": "test_parcels_v1",
    "container_name": "rmhazuregeobronze",
    "schema": "geo",
    "converter_params": {
      "layer_name": "parcels"
    },
    "indexes": {
      "spatial": true,
      "attributes": ["county"],
      "temporal": []
    }
  }'
```

### Check Job Status:

```bash
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/jobs/status/{JOB_ID}
```

### Query via OGC Features API:

```bash
curl "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/features/collections/test_parcels_v1/items?limit=10"
```

---
