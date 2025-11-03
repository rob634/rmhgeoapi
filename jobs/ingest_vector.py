# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Two-stage vector ETL with pickle-based intermediate storage
# PURPOSE: Ingest vector files to PostGIS using fan-out parallelism for chunk uploads
# LAST_REVIEWED: 3 NOV 2025
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
Ingest Vector Job Declaration - Two-Stage Fan-Out for Vector → PostGIS

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

Author: Robert and Geospatial Claude Legion
Date: 7 OCT 2025
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
        "container_name": {"type": "str", "default": "rmhazuregeobronze"},  # TODO: Parameterize via env var
        "schema": {"type": "str", "default": "geo"},
        "chunk_size": {"type": "int", "default": None},  # Auto-calculate if None
        "converter_params": {"type": "dict", "default": {}},
        "indexes": {"type": "dict", "default": {
            "spatial": True,      # Always create spatial GIST index on geom
            "attributes": [],     # List of attribute column names for B-tree indexes
            "temporal": []        # List of temporal columns for DESC B-tree indexes
        }}
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
                CSV: lat_name, lon_name OR wkt_column
                GPKG: layer_name
                KMZ/Shapefile: optional file name in archive
            indexes: dict - Database index configuration (optional)
                spatial: bool - Create GIST index on geometry (default: True)
                attributes: list - Column names for B-tree indexes (default: [])
                temporal: list - Column names for DESC B-tree indexes (default: [])

        Returns:
            Validated parameters dict

        Raises:
            ValueError: If parameters are invalid
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
        # Validate PostgreSQL identifier rules (alphanumeric + underscore, start with letter)
        if not table_name[0].isalpha():
            raise ValueError("table_name must start with a letter")
        if not all(c.isalnum() or c == '_' for c in table_name):
            raise ValueError("table_name must contain only letters, numbers, and underscores")
        validated["table_name"] = table_name.lower()

        # Optional: container_name
        # TODO: Parameterize via env var instead of hardcoded default
        validated["container_name"] = params.get("container_name", "rmhazuregeobronze")

        # Optional: schema
        schema = params.get("schema", "geo")
        if schema not in ["geo", "public"]:  # Whitelist allowed schemas
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
            if chunk_size < 100 or chunk_size > 10000:
                raise ValueError(f"chunk_size must be between 100 and 10000, got {chunk_size}")
            validated["chunk_size"] = chunk_size
        else:
            validated["chunk_size"] = None  # Auto-calculate

        # Optional: converter_params
        converter_params = params.get("converter_params", {})
        if not isinstance(converter_params, dict):
            raise ValueError("converter_params must be a dictionary")
        validated["converter_params"] = converter_params

        # Optional: indexes (database index configuration)
        indexes = params.get("indexes", {
            "spatial": True,
            "attributes": [],
            "temporal": []
        })
        if not isinstance(indexes, dict):
            raise ValueError("indexes must be a dictionary")

        # Validate indexes.spatial
        if "spatial" in indexes:
            if not isinstance(indexes["spatial"], bool):
                raise ValueError(f"indexes.spatial must be a boolean, got {type(indexes['spatial']).__name__}")

        # Validate indexes.attributes
        if "attributes" in indexes:
            if not isinstance(indexes["attributes"], list):
                raise ValueError(f"indexes.attributes must be a list, got {type(indexes['attributes']).__name__}")
            # Validate each attribute column name
            for attr in indexes["attributes"]:
                if not isinstance(attr, str) or not attr.strip():
                    raise ValueError(f"indexes.attributes must contain non-empty strings, got {attr}")

        # Validate indexes.temporal
        if "temporal" in indexes:
            if not isinstance(indexes["temporal"], list):
                raise ValueError(f"indexes.temporal must be a list, got {type(indexes['temporal']).__name__}")
            # Validate each temporal column name
            for temp_col in indexes["temporal"]:
                if not isinstance(temp_col, str) or not temp_col.strip():
                    raise ValueError(f"indexes.temporal must contain non-empty strings, got {temp_col}")

        validated["indexes"] = {
            "spatial": indexes.get("spatial", True),
            "attributes": indexes.get("attributes", []),
            "temporal": indexes.get("temporal", [])
        }

        return validated

    @staticmethod
    def generate_job_id(params: dict) -> str:
        """
        Generate deterministic job ID from parameters.

        Same parameters = same job ID (idempotency).
        """
        # Sort keys for consistent hashing
        param_str = json.dumps(params, sort_keys=True)
        job_hash = hashlib.sha256(param_str.encode()).hexdigest()
        return job_hash

    @staticmethod
    def create_job_record(job_id: str, params: dict) -> dict:
        """
        Create job record for database storage.

        Args:
            job_id: Generated job ID
            params: Validated parameters

        Returns:
            Job record dict
        """
        from infrastructure import RepositoryFactory
        from core.models import JobRecord, JobStatus

        # Create job record object
        job_record = JobRecord(
            job_id=job_id,
            job_type="ingest_vector",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=3,  # Stage 1: prepare, Stage 2: upload, Stage 3: STAC
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

        # Persist to database
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        job_repo.create_job(job_record)

        # Return as dict
        return job_record.model_dump()

    @staticmethod
    def queue_job(job_id: str, params: dict) -> dict:
        """
        Queue job for processing using Service Bus.

        Args:
            job_id: Job ID
            params: Validated parameters

        Returns:
            Queue result information
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        from util_logger import LoggerFactory, ComponentType
        import uuid

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "IngestVectorJob.queue_job")

        logger.info(f"🚀 Starting queue_job for job_id={job_id}")

        # Get config for queue name
        config = get_config()
        queue_name = config.service_bus_jobs_queue

        # Create Service Bus repository
        service_bus_repo = ServiceBusRepository()

        # Create job queue message
        correlation_id = str(uuid.uuid4())
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type="ingest_vector",
            stage=1,
            parameters=params,
            correlation_id=correlation_id
        )

        # Send to Service Bus jobs queue
        message_id = service_bus_repo.send_message(queue_name, job_message)
        logger.info(f"✅ Message sent successfully - message_id={message_id}")

        result = {
            "queued": True,
            "queue_type": "service_bus",
            "queue_name": queue_name,
            "message_id": message_id,
            "job_id": job_id
        }

        logger.info(f"🎉 Job queued successfully - {result}")
        return result

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
        """
        Generate task parameters for a stage.

        Stage 1: Single task to prepare chunks
        Stage 2: Fan-out - one task per chunk from Stage 1 results

        Args:
            stage: Stage number (1 or 2)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Results from Stage 1 (required for Stage 2)

        Returns:
            List of task parameter dicts

        Raises:
            ValueError: If Stage 2 called without previous_results
        """
        from core.task_id import generate_deterministic_task_id

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
                        "indexes": job_params.get("indexes", {
                            "spatial": True,
                            "attributes": [],
                            "temporal": []
                        })
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: FAN-OUT - Create one task per pickled chunk
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results for fan-out")

            # Extract chunk paths from Stage 1 result
            stage_1_result = previous_results[0]  # Single Stage 1 task
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            chunk_paths = stage_1_result['result']['chunk_paths']
            table_name = stage_1_result['result']['table_name']
            schema = stage_1_result['result']['schema']

            # ========================================================================
            # DEADLOCK FIX (17 OCT 2025): Create table ONCE before parallel inserts
            # ========================================================================
            # CRITICAL: Serialize table creation here to avoid PostgreSQL deadlocks
            # during parallel INSERT operations in Stage 2 tasks.
            #
            # Problem: Multiple Stage 2 tasks calling CREATE TABLE IF NOT EXISTS
            # simultaneously caused lock contention and deadlocks.
            #
            # Solution: Create table once HERE (before task creation), then Stage 2
            # tasks only INSERT data (no DDL operations).
            # ========================================================================
            logger.info(f"🔧 DEADLOCK FIX: Creating table {schema}.{table_name} before parallel uploads...")

            # Load first chunk to get schema using BlobRepository singleton
            from infrastructure.blob import BlobRepository
            from config import get_config
            import pickle

            config = get_config()
            first_chunk_path = chunk_paths[0]

            # BlobRepository.read_blob(container, blob_path) returns bytes
            blob_repo = BlobRepository.instance()
            blob_data = blob_repo.read_blob(config.vector_pickle_container, first_chunk_path)
            first_chunk = pickle.loads(blob_data)

            # Create table using PostGIS handler with index configuration
            from services.vector.postgis_handler import VectorToPostGISHandler
            postgis_handler = VectorToPostGISHandler()

            # Extract indexes configuration from job parameters
            indexes = job_params.get("indexes", {
                "spatial": True,
                "attributes": [],
                "temporal": []
            })

            postgis_handler.create_table_only(first_chunk, table_name, schema, indexes)

            logger.info(f"✅ Table {schema}.{table_name} created successfully with indexes: {indexes}")

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

        elif stage == 3:
            # Stage 3: Create STAC Record - Single task to catalog PostGIS table
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results")

            # Extract table details from Stage 2 results (any task will have the info)
            stage_2_result = previous_results[0]  # All Stage 2 tasks reference same table
            if not stage_2_result.get('success'):
                raise ValueError(f"Stage 2 failed: {stage_2_result.get('error')}")

            result_data = stage_2_result['result']
            table_name = result_data['table'].split('.')[-1]  # Extract table name from "schema.table"
            schema = result_data['table'].split('.')[0]  # Extract schema from "schema.table"

            logger.info(f"📊 Stage 3: Creating STAC record for {schema}.{table_name}")

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
                        "job_id": job_id
                    }
                }
            ]

        else:
            return []

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Aggregate results from all completed tasks into job summary.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Aggregated job results dict including OGC Features API URLs
        """
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Separate tasks by stage
        stage_1_tasks = [t for t in task_results if t.task_type == "prepare_vector_chunks"]
        stage_2_tasks = [t for t in task_results if t.task_type == "upload_pickled_chunk"]
        stage_3_tasks = [t for t in task_results if t.task_type == "create_vector_stac"]

        # Extract metadata from Stage 1
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

        # Aggregate Stage 2 upload results
        successful_chunks = sum(1 for t in stage_2_tasks if t.status == TaskStatus.COMPLETED)
        failed_chunks = len(stage_2_tasks) - successful_chunks

        total_rows_uploaded = sum(
            t.result_data.get("result", {}).get("rows_uploaded", 0)
            for t in stage_2_tasks
            if t.result_data
        )

        # Extract STAC results from Stage 3
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

        # Generate OGC Features URL for vector access
        from config import get_config
        config = get_config()
        table_name = params.get("table_name")
        ogc_features_url = config.generate_ogc_features_url(table_name)

        logger.info(
            f"✅ Vector ingest job {context.job_id[:16]} completed: "
            f"{total_rows_uploaded} rows uploaded to {params.get('schema')}.{table_name}, "
            f"STAC cataloged, OGC Features URL generated"
        )

        # Build aggregated result
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
                "stage_1_metadata": chunk_metadata
            },
            "stac": stac_summary,
            "ogc_features_url": ogc_features_url,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED),
                "queued": sum(1 for t in task_results if t.status == TaskStatus.QUEUED)
            }
        }
