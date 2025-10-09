"""
Ingest Vector Job Declaration - Two-Stage Fan-Out for Vector → PostGIS

This file declares a two-stage job that:
- Stage 1: Load file, validate, chunk, pickle to blob storage (single task)
- Stage 2: Upload chunks to PostGIS in parallel (N tasks)

Uses pickle intermediate storage to avoid Service Bus 256KB message size limit.
Each Stage 2 task receives blob reference, loads pickle, uploads to PostGIS.

Author: Robert and Geospatial Claude Legion
Date: 7 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json


class IngestVectorJob:
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
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "file_extension": {"type": "str", "required": True},
        "table_name": {"type": "str", "required": True},
        "container_name": {"type": "str", "default": "bronze"},
        "schema": {"type": "str", "default": "geo"},
        "chunk_size": {"type": "int", "default": None},  # Auto-calculate if None
        "converter_params": {"type": "dict", "default": {}}
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
            container_name: str - Source container (default: 'bronze')
            schema: str - Target PostgreSQL schema (default: 'geo')
            chunk_size: int - Rows per chunk (default: None = auto-calculate)
            converter_params: dict - Format-specific parameters
                CSV: lat_name, lon_name OR wkt_column
                GPKG: layer_name
                KMZ/Shapefile: optional file name in archive

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
        validated["container_name"] = params.get("container_name", "bronze")

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
                        "converter_params": job_params.get("converter_params", {})
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

        else:
            return []

    @staticmethod
    def aggregate_results(stage: int, task_results: list) -> dict:
        """
        Aggregate task results for a stage.

        Stage 1: Return chunk metadata
        Stage 2: Aggregate rows uploaded across all chunks

        Args:
            stage: Stage number
            task_results: List of task result dicts

        Returns:
            Aggregated results
        """
        if stage == 1:
            # Stage 1: Single task, just pass through
            if task_results:
                return task_results[0].get('result', {})
            return {}

        elif stage == 2:
            # Stage 2: Aggregate rows uploaded
            total_rows = sum(
                result.get('result', {}).get('rows_uploaded', 0)
                for result in task_results
            )
            successful_chunks = sum(
                1 for result in task_results
                if result.get('success', False)
            )

            return {
                "total_rows_uploaded": total_rows,
                "chunks_processed": successful_chunks,
                "total_chunks": len(task_results)
            }

        return {}
