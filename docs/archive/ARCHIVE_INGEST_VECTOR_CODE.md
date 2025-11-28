# ARCHIVED: ingest_vector Code

**Archive Date**: 28 NOV 2025
**Reason**: Replaced by `process_vector` with built-in idempotency (DELETE+INSERT pattern)
**Archived By**: Robert and Geospatial Claude Legion

---

## Why This Code Was Archived

The `ingest_vector` job was replaced by `process_vector` because:

1. **Idempotency**: `process_vector` uses DELETE+INSERT pattern with `etl_batch_id` column for true task-level idempotency. If a task retries, it deletes its previous data and re-inserts fresh data.

2. **Pre-Flight Validation**: `process_vector` includes resource validators that check blob/container existence BEFORE job creation, returning HTTP 400 instead of wasting Service Bus messages.

3. **Simpler Architecture**: Both jobs use the same 3-stage structure, but `process_vector` was written with JobBaseMixin (77% less boilerplate).

4. **No Duplicate Rows**: The original `ingest_vector` used plain INSERT, which could create duplicate rows on retry. `process_vector` prevents this.

---

## Recovery Instructions

If you need this code back:

```bash
# Option 1: Restore from git (preferred)
git log --oneline | grep "ingest_vector"
git checkout <commit-hash> -- jobs/ingest_vector.py triggers/ingest_vector.py

# Option 2: Copy from this archive file
# Then re-add registrations to jobs/__init__.py and services/__init__.py
```

---

## Archived Files

### 1. jobs/ingest_vector.py (770 lines)

```python
# ============================================================================
# PRODUCTION READY - Corporate Deployment Approved
# ============================================================================
# WORKFLOW: ingest_vector
# TESTED: 14 NOV 2025 - 2.5 million row CSV (ACLED conflict data)
# CAPABILITY: 6 formats (CSV, GeoJSON, GeoPackage, KML, KMZ, Shapefile)
# ============================================================================

# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Job - Two-stage vector ETL with pickle-based intermediate storage
# PURPOSE: Ingest vector files to PostGIS using fan-out parallelism for chunk uploads
# LAST_REVIEWED: 22 NOV 2025
# EXPORTS: IngestVectorJob (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict-based validation)
# DEPENDENCIES: jobs.base.JobBase, util_logger, hashlib, json
# SOURCE: HTTP job submission via POST /api/jobs/ingest_vector (6 supported formats: csv, geojson, gpkg, kml, kmz, shp)
# SCOPE: Vector ETL with parallel PostGIS uploads
# VALIDATION: File extension, table name, blob path, chunk size validation
# PATTERNS: Two-stage fan-out, Pickle intermediate storage (avoid Service Bus 256KB limit), Parallel uploads
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "ingest_vector"
# INDEX: IngestVectorJob:31, stages:46, create_tasks_for_stage:80
# ============================================================================

"""
Ingest Vector Job Declaration - Two-Stage Fan-Out for Vector -> PostGIS

This file declares a two-stage job that:
- Stage 1: Load file, validate, chunk, pickle to blob storage (single task)
- Stage 2: Upload chunks to PostGIS in parallel (N tasks)

Uses pickle intermediate storage to avoid Service Bus 256KB message size limit.
Each Stage 2 task receives blob reference, loads pickle, uploads to PostGIS.

Supported Formats (6 total):
- CSV (lat/lon or WKT geometry)
- GeoJSON
- GeoPackage (GPKG)
- KML
- KMZ (zipped KML)
- Shapefile (zipped)

Updated: 15 OCT 2025 - Phase 2: Migrated to JobBase ABC
Last Updated: 29 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json
import logging

from jobs.base import JobBase
from util_logger import LoggerFactory, ComponentType

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.CONTROLLER,
    "ingest_vector_job"
)


class IngestVectorJob(JobBase):
    """
    Two-stage vector ETL workflow with pickle-based intermediate storage.

    Stage 1: Single task loads, validates, chunks, and pickles
    Stage 2: N parallel tasks upload chunks to PostGIS

    Handles timeout risk by fan-out parallelism.
    """

    # Job metadata
    job_type: str = "ingest_vector"
    description: str = "Load vector file and ingest to PostGIS with parallel chunked uploads"

    # Stage definitions
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

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "file_extension": {"type": "str", "required": True},
        "table_name": {"type": "str", "required": True},
        "container_name": {"type": "str", "default": "rmhazuregeobronze"},
        "schema": {"type": "str", "default": "geo"},
        "chunk_size": {"type": "int", "default": None},
        "converter_params": {"type": "dict", "default": {}},
        "indexes": {"type": "dict", "default": {
            "spatial": True,
            "attributes": [],
            "temporal": []
        }},
        "geometry_params": {"type": "dict", "default": {}, "description": "Geometry processing options"},
        "render_params": {"type": "dict", "default": {}, "description": "Future: Rendering optimization parameters"}
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            blob_name: str - Path to vector file in blob storage
            file_extension: str - File extension (csv, gpkg, geojson, kml, kmz, shp)
            table_name: str - Target PostGIS table name

        Optional:
            container_name: str - Source container (default: 'rmhazuregeobronze')
            schema: str - Target PostgreSQL schema (default: 'geo')
            chunk_size: int - Rows per chunk (default: None = auto-calculate)
            converter_params: dict - Format-specific parameters
            indexes: dict - Database index configuration
            geometry_params: dict - Geometry processing options
            render_params: dict - Future: Rendering optimizations
        """
        validated = {}

        # Required: blob_name
        if "blob_name" not in params:
            raise ValueError("blob_name is required")
        blob_name = params["blob_name"]
        if not isinstance(blob_name, str) or not blob_name.strip():
            raise ValueError("blob_name must be a non-empty string")
        validated["blob_name"] = blob_name.strip()

        # Required: file_extension
        if "file_extension" not in params:
            raise ValueError("file_extension is required")
        file_extension = params["file_extension"]
        if not isinstance(file_extension, str) or not file_extension.strip():
            raise ValueError("file_extension must be a non-empty string")

        # Validate supported extensions
        supported = ['csv', 'geojson', 'json', 'gpkg', 'kml', 'kmz', 'shp', 'zip']
        ext = file_extension.lower().lstrip('.')
        if ext not in supported:
            raise ValueError(f"file_extension '{ext}' not supported. Supported: {', '.join(supported)}")
        validated["file_extension"] = ext

        # Required: table_name
        if "table_name" not in params:
            raise ValueError("table_name is required")
        table_name = params["table_name"]
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError("table_name must be a non-empty string")
        if not table_name[0].isalpha():
            raise ValueError("table_name must start with a letter")
        if not all(c.isalnum() or c == '_' for c in table_name):
            raise ValueError("table_name must contain only letters, numbers, and underscores")
        validated["table_name"] = table_name.lower()

        # Optional: container_name
        validated["container_name"] = params.get("container_name", "rmhazuregeobronze")

        # Optional: schema
        schema = params.get("schema", "geo")
        if schema not in ["geo", "public"]:
            raise ValueError(f"schema must be 'geo' or 'public', got '{schema}'")
        validated["schema"] = schema

        # Optional: chunk_size
        chunk_size = params.get("chunk_size")
        if chunk_size is not None:
            if not isinstance(chunk_size, int):
                try:
                    chunk_size = int(chunk_size)
                except (ValueError, TypeError):
                    raise ValueError(f"chunk_size must be an integer, got {type(chunk_size).__name__}")
            if chunk_size < 100 or chunk_size > 500000:
                raise ValueError(f"chunk_size must be between 100 and 500000, got {chunk_size}")
            validated["chunk_size"] = chunk_size
        else:
            validated["chunk_size"] = None

        # Optional: converter_params
        converter_params = params.get("converter_params", {})
        if not isinstance(converter_params, dict):
            raise ValueError("converter_params must be a dictionary")
        validated["converter_params"] = converter_params

        # Optional: indexes
        indexes = params.get("indexes", {"spatial": True, "attributes": [], "temporal": []})
        if not isinstance(indexes, dict):
            raise ValueError("indexes must be a dictionary")

        if "spatial" in indexes and not isinstance(indexes["spatial"], bool):
            raise ValueError(f"indexes.spatial must be a boolean")

        if "attributes" in indexes:
            if not isinstance(indexes["attributes"], list):
                raise ValueError(f"indexes.attributes must be a list")
            for attr in indexes["attributes"]:
                if not isinstance(attr, str) or not attr.strip():
                    raise ValueError(f"indexes.attributes must contain non-empty strings")

        if "temporal" in indexes:
            if not isinstance(indexes["temporal"], list):
                raise ValueError(f"indexes.temporal must be a list")
            for temp_col in indexes["temporal"]:
                if not isinstance(temp_col, str) or not temp_col.strip():
                    raise ValueError(f"indexes.temporal must contain non-empty strings")

        validated["indexes"] = {
            "spatial": indexes.get("spatial", True),
            "attributes": indexes.get("attributes", []),
            "temporal": indexes.get("temporal", [])
        }

        # Optional: geometry_params
        geometry_params = params.get("geometry_params", {})
        if not isinstance(geometry_params, dict):
            raise ValueError("geometry_params must be a dictionary")
        validated["geometry_params"] = geometry_params

        # Optional: render_params
        render_params = params.get("render_params", {})
        if not isinstance(render_params, dict):
            raise ValueError("render_params must be a dictionary")
        validated["render_params"] = render_params

        # Check if table already exists
        from infrastructure.postgis import check_table_exists
        import psycopg

        schema = validated["schema"]
        table_name = validated["table_name"]

        try:
            table_exists = check_table_exists(schema, table_name)
            if table_exists:
                raise ValueError(
                    f"Table {schema}.{table_name} already exists. "
                    f"To replace it, drop the table first or choose a different table_name."
                )
        except ValueError:
            raise
        except psycopg.OperationalError as e:
            logger.warning(f"Could not verify table existence: {e}. Job will proceed.")
        except Exception as e:
            logger.error(f"Unexpected error checking table existence: {e}")
            raise ValueError(f"Unable to validate table name '{table_name}'. Error: {e}")

        # Validate container and blob exist
        from azure.core.exceptions import ResourceNotFoundError
        from infrastructure.blob import BlobRepository

        blob_repo = BlobRepository.instance()
        container_name = validated["container_name"]
        blob_name = validated["blob_name"]

        if not blob_repo.container_exists(container_name):
            raise ResourceNotFoundError(f"Container '{container_name}' does not exist")

        if not blob_repo.blob_exists(container_name, blob_name):
            raise ResourceNotFoundError(f"File '{blob_name}' not found in container '{container_name}'")

        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """Generate deterministic job ID from parameters."""
        param_str = json.dumps(params, sort_keys=True)
        job_hash = hashlib.sha256(param_str.encode()).hexdigest()
        return job_hash

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """Create job record for database storage."""
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        job_record = JobRecord(
            job_id=job_id,
            job_type="ingest_vector",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=3,
            stage_results={},
            metadata={
                "description": "Load vector file and ingest to PostGIS with parallel chunked uploads + STAC cataloging",
                "created_by": "IngestVectorJob",
                "blob_name": params.get("blob_name"),
                "table_name": params.get("table_name"),
                "file_extension": params.get("file_extension"),
                "container_name": params.get("container_name")
            }
        )

        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job_repo.create_job(job_record)

        return job_record.model_dump()

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """Queue job for processing using Service Bus."""
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        import uuid

        config = get_config()
        queue_name = config.service_bus_jobs_queue

        service_bus_repo = ServiceBusRepository()

        correlation_id = str(uuid.uuid4())[:8]
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type="ingest_vector",
            stage=1,
            parameters=params,
            correlation_id=correlation_id
        )

        message_id = service_bus_repo.send_message(queue_name, job_message)

        return {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
        """Generate task parameters for a stage."""
        from core.task_id import generate_deterministic_task_id

        if stage == 1:
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
                        "indexes": job_params.get("indexes", {"spatial": True, "attributes": [], "temporal": []}),
                        "geometry_params": job_params.get("geometry_params", {}),
                        "render_params": job_params.get("render_params", {})
                    }
                }
            ]

        elif stage == 2:
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results for fan-out")

            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            chunk_paths = stage_1_result['result']['chunk_paths']
            table_name = stage_1_result['result']['table_name']
            schema = stage_1_result['result']['schema']

            # DEADLOCK FIX: Create table ONCE before parallel inserts
            from infrastructure.blob import BlobRepository
            from config import get_config
            import pickle

            config = get_config()
            first_chunk_path = chunk_paths[0]

            blob_repo = BlobRepository.instance()
            blob_data = blob_repo.read_blob(config.vector_pickle_container, first_chunk_path)
            first_chunk = pickle.loads(blob_data)

            from services.vector.postgis_handler import VectorToPostGISHandler
            postgis_handler = VectorToPostGISHandler()

            indexes = job_params.get("indexes", {"spatial": True, "attributes": [], "temporal": []})
            postgis_handler.create_table_only(first_chunk, table_name, schema, indexes)

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

        elif stage == 3:
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            stage_2_result = previous_results[0]
            if not stage_2_result.get('success'):
                raise ValueError(f"Stage 2 failed: {stage_2_result.get('error')}")

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

        else:
            return []

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """Aggregate results from all completed tasks into job summary."""
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        stage_1_tasks = [t for t in task_results if t.task_type == "prepare_vector_chunks"]
        stage_2_tasks = [t for t in task_results if t.task_type == "upload_pickled_chunk"]
        stage_3_tasks = [t for t in task_results if t.task_type == "create_vector_stac"]

        total_chunks = 0
        chunk_metadata = {}
        if stage_1_tasks and stage_1_tasks[0].result_data:
            stage_1_result = stage_1_tasks[0].result_data.get("result", {})
            total_chunks = stage_1_result.get("chunk_count", 0)
            chunk_metadata = {
                "chunk_count": total_chunks,
                "total_features": stage_1_result.get("total_features", 0),
                "chunk_paths": stage_1_result.get("chunk_paths", [])
            }

        successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
        failed_chunks = len(stage_2_tasks) - successful_chunks

        total_rows_uploaded = sum(
            t.result_data.get("result", {}).get("rows_uploaded", 0)
            for t in stage_2_tasks
            if t.result_data
        )

        stac_summary = {}
        if stage_3_tasks and stage_3_tasks[0].result_data:
            stac_result = stage_3_tasks[0].result_data.get("result", {})
            stac_summary = {
                "collection_id": stac_result.get("collection_id", "system-vectors"),
                "stac_id": stac_result.get("stac_id"),
                "pgstac_id": stac_result.get("pgstac_id"),
                "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
                "feature_count": stac_result.get("feature_count"),
                "bbox": stac_result.get("bbox")
            }

        from config import get_config
        config = get_config()
        table_name = params.get("table_name")
        ogc_features_url = config.generate_ogc_features_url(table_name)
        viewer_url = config.generate_vector_viewer_url(table_name)

        return {
            "job_type": "ingest_vector",
            "blob_name": params.get("blob_name"),
            "file_extension": params.get("file_extension"),
            "table_name": table_name,
            "schema": params.get("schema"),
            "container_name": params.get("container_name"),
            "summary": {
                "total_chunks": total_chunks,
                "chunks_uploaded": successful_chunks,
                "chunks_failed": failed_chunks,
                "total_rows_uploaded": total_rows_uploaded,
                "success_rate": f"{(successful_chunks / len(stage_2_tasks) * 100):.1f}%" if stage_2_tasks else "0%",
                "stage_1_metadata": chunk_metadata,
                "data_complete": failed_chunks == 0
            },
            "stac": stac_summary,
            "ogc_features_url": ogc_features_url,
            "viewer_url": viewer_url,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED),
                "queued": sum(1 for t in task_results if t.status == TaskStatus.QUEUED)
            }
        }
```

---

### 2. triggers/ingest_vector.py (213 lines)

```python
# ============================================================================
# CLAUDE CONTEXT - HTTP TRIGGER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: HTTP Trigger - Vector ETL job submission endpoint
# PURPOSE: Vector ingest HTTP trigger for POST /api/jobs/ingest_vector
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: IngestVectorTrigger, ingest_vector_trigger (singleton instance)
# INTERFACES: JobManagementTrigger (inherited from http_base)
# ============================================================================

"""
Vector Ingest HTTP Trigger - Azure Geospatial ETL Pipeline

HTTP endpoint for submitting vector file ETL jobs to PostGIS.

Supports 6 file formats:
- CSV (lat/lon or WKT)
- GeoJSON
- GeoPackage
- KML
- KMZ (zipped KML)
- Shapefile (zipped)

API Endpoint:
    POST /api/jobs/ingest_vector
"""

from typing import Dict, Any, List
import azure.functions as func
from .http_base import JobManagementTrigger


class IngestVectorTrigger(JobManagementTrigger):
    """Vector ingest HTTP trigger implementation."""

    def __init__(self):
        super().__init__("ingest_vector")

    def get_allowed_methods(self) -> List[str]:
        """Vector ingest only supports POST."""
        return ["POST"]

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """Process vector ingest request."""
        req_body = self.extract_json_body(req, required=True)
        self.validate_required_fields(req_body, ["blob_name", "file_extension", "table_name"])

        blob_name = req_body["blob_name"]
        file_extension = req_body["file_extension"]
        table_name = req_body["table_name"]
        container_name = req_body.get("container_name", "rmhazuregeobronze")
        schema = req_body.get("schema", "geo")
        chunk_size = req_body.get("chunk_size")
        converter_params = req_body.get("converter_params", {})

        from jobs import ALL_JOBS

        if "ingest_vector" not in ALL_JOBS:
            raise ValueError(f"Vector ingest job not registered. Available: {', '.join(ALL_JOBS.keys())}")

        job_class = ALL_JOBS["ingest_vector"]

        job_params = {
            "blob_name": blob_name,
            "file_extension": file_extension,
            "table_name": table_name,
            "container_name": container_name,
            "schema": schema,
            "chunk_size": chunk_size,
            "converter_params": converter_params
        }

        validated_params = job_class.validate_job_parameters(job_params)
        job_id = job_class.generate_job_id(validated_params)

        from infrastructure.factory import RepositoryFactory
        repos = RepositoryFactory.create_repositories()
        existing_job = repos['job_repo'].get_job(job_id)

        if existing_job:
            if existing_job.status.value == 'completed':
                return {
                    "job_id": job_id,
                    "status": "already_completed",
                    "job_type": "ingest_vector",
                    "message": "Vector ETL job already completed (idempotency)",
                    "parameters": validated_params,
                    "result_data": existing_job.result_data,
                    "idempotent": True
                }
            else:
                return {
                    "job_id": job_id,
                    "status": existing_job.status.value,
                    "job_type": "ingest_vector",
                    "message": f"Vector ETL job in progress (idempotency)",
                    "parameters": validated_params,
                    "current_stage": existing_job.stage,
                    "total_stages": existing_job.total_stages,
                    "idempotent": True
                }

        job_record = job_class.create_job_record(job_id, validated_params)
        queue_result = job_class.queue_job(job_id, validated_params)

        return {
            "job_id": job_id,
            "status": "created",
            "job_type": "ingest_vector",
            "message": "Vector ETL job created and queued for processing",
            "parameters": validated_params,
            "queue_info": queue_result,
            "idempotent": False
        }


# Singleton instance
ingest_vector_trigger = IngestVectorTrigger()
```

---

## Registry Entries That Were Removed

### jobs/__init__.py

```python
# REMOVED LINE:
from .ingest_vector import IngestVectorJob

# REMOVED FROM ALL_JOBS:
"ingest_vector": IngestVectorJob,
```

### services/__init__.py

```python
# REMOVED IMPORTS:
from .vector.tasks import prepare_vector_chunks, upload_pickled_chunk

# REMOVED FROM ALL_HANDLERS:
"prepare_vector_chunks": prepare_vector_chunks,
"upload_pickled_chunk": upload_pickled_chunk,
```

---

## Related Documentation Archived

The file `WIKI_API_INGEST_VECTOR_TRACETHROUGH.md` (1,125 lines) contained a complete execution trace of the ingest_vector workflow. This documentation has been archived alongside this code.

---

**End of Archive**
