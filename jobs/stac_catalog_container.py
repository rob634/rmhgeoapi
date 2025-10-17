"""
STAC Catalog Container Job Declaration - Two-Stage Fan-Out Pattern

This file declares a two-stage job that:
- Stage 1: Lists all raster files in a container
- Stage 2: Extracts STAC metadata for each file and inserts into PgSTAC (fan-out parallelism)

Leverages existing StacMetadataService for metadata extraction.

Author: Robert and Geospatial Claude Legion
Date: 6 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class StacCatalogContainerWorkflow(JobBase):
    """
    Two-stage fan-out job for bulk STAC cataloging.

    Stage 1: Single task lists all raster files in container
    Stage 2: N parallel tasks (one per file) extract STAC metadata and insert to PgSTAC

    Results: Each file's STAC Item stored in PgSTAC database + task.result_data
    """

    # Job metadata
    job_type: str = "stac_catalog_container"
    description: str = "Bulk STAC metadata extraction and cataloging with parallel fan-out"

    # Stage definitions
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "list_rasters",
            "task_type": "list_raster_files",
            "description": "Enumerate all raster files in container with extension filter",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "extract_stac",
            "task_type": "extract_stac_metadata",
            "description": "Extract STAC metadata and insert into PgSTAC (parallel per file)",
            "parallelism": "fan_out"
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "container_name": {"type": "str", "required": True},
        "collection_id": {"type": "str", "required": True, "default": "dev"},
        "extension_filter": {"type": "str", "default": ".tif"},
        "file_limit": {"type": "int", "min": 1, "max": 10000, "default": None},
        "prefix": {"type": "str", "default": ""}
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            container_name: str - Azure storage container name
            collection_id: str - STAC collection to insert items into

        Optional:
            extension_filter: str - File extension to filter (default: ".tif")
            file_limit: int - Max files to process (1-10000, default: None = all)
            prefix: str - Blob path prefix filter (default: "")

        Returns:
            Validated parameters dict

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}

        # Validate container_name (required)
        if "container_name" not in params:
            raise ValueError("container_name is required")

        container_name = params["container_name"]
        if not isinstance(container_name, str) or not container_name.strip():
            raise ValueError("container_name must be a non-empty string")

        validated["container_name"] = container_name.strip()

        # Validate collection_id (required)
        collection_id = params.get("collection_id", "dev")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise ValueError("collection_id must be a non-empty string")

        # Validate collection_id is one of the valid production collections
        valid_collections = ["dev", "cogs", "vectors", "geoparquet"]
        if collection_id not in valid_collections:
            raise ValueError(f"collection_id must be one of {valid_collections}, got '{collection_id}'")

        validated["collection_id"] = collection_id.strip()

        # Validate extension_filter (optional)
        extension_filter = params.get("extension_filter", ".tif")
        if not isinstance(extension_filter, str):
            raise ValueError("extension_filter must be a string")

        if not extension_filter.startswith("."):
            extension_filter = f".{extension_filter}"

        validated["extension_filter"] = extension_filter.lower()

        # Validate file_limit (optional)
        file_limit = params.get("file_limit")
        if file_limit is not None:
            if not isinstance(file_limit, int):
                try:
                    file_limit = int(file_limit)
                except (ValueError, TypeError):
                    raise ValueError(f"file_limit must be an integer, got {type(file_limit).__name__}")

            if file_limit < 1 or file_limit > 10000:
                raise ValueError(f"file_limit must be between 1 and 10000, got {file_limit}")

            validated["file_limit"] = file_limit
        else:
            validated["file_limit"] = None

        # Validate prefix (optional)
        prefix = params.get("prefix", "")
        if not isinstance(prefix, str):
            raise ValueError("prefix must be a string")

        validated["prefix"] = prefix.strip()

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

        Stage 1: Single task to list all raster files
        Stage 2: Fan-out - one task per raster file from Stage 1 results

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
            # Stage 1: Single task to list raster files
            task_id = generate_deterministic_task_id(job_id, 1, "list_rasters")
            return [
                {
                    "task_id": task_id,
                    "task_type": "list_raster_files",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "extension_filter": job_params.get("extension_filter", ".tif"),
                        "prefix": job_params.get("prefix", ""),
                        "file_limit": job_params.get("file_limit")
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: FAN-OUT - Create one task per raster file
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results for fan-out")

            # Extract raster file names from Stage 1 result
            stage_1_result = previous_results[0]  # Single Stage 1 task
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            raster_files = stage_1_result['result']['raster_files']

            if not raster_files:
                # No files to process - return empty list
                return []

            # Create one task per raster file with deterministic ID
            tasks = []
            for raster_file in raster_files:
                task_id = generate_deterministic_task_id(job_id, 2, raster_file)
                tasks.append({
                    "task_id": task_id,
                    "task_type": "extract_stac_metadata",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "blob_name": raster_file,
                        "collection_id": job_params.get("collection_id", "dev")
                    }
                })

            return tasks

        else:
            return []

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
            job_type="stac_catalog_container",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=2,
            stage_results={},
            metadata={
                "description": "Bulk STAC metadata extraction and cataloging",
                "created_by": "StacCatalogContainerWorkflow",
                "collection_id": params.get("collection_id", "dev"),
                "extension_filter": params.get("extension_filter", ".tif")
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "StacCatalogContainerWorkflow.queue_job")

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
            job_type="stac_catalog_container",
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
    def aggregate_job_results(context) -> Dict[str, Any]:
        """
        Aggregate results from all completed tasks into job summary.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Aggregated job results dict
        """
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Separate by stage
        stage_1_tasks = [t for t in task_results if t.task_type == "list_raster_files"]
        stage_2_tasks = [t for t in task_results if t.task_type == "extract_stac_metadata"]

        # Extract file list from Stage 1
        total_files_found = 0
        if stage_1_tasks and stage_1_tasks[0].result_data:
            stage_1_result = stage_1_tasks[0].result_data.get("result", {})
            total_files_found = stage_1_result.get("total_count", 0)

        # Count successful STAC insertions from Stage 2
        successful_insertions = 0
        failed_insertions = 0
        for task in stage_2_tasks:
            if task.status == TaskStatus.COMPLETED and task.result_data:
                result = task.result_data.get("result", {})
                if result.get("inserted_to_pgstac"):
                    successful_insertions += 1
                else:
                    failed_insertions += 1
            elif task.status == TaskStatus.FAILED:
                failed_insertions += 1

        # Build aggregated result
        return {
            "job_type": "stac_catalog_container",
            "collection_id": params.get("collection_id", "dev"),
            "container_name": params.get("container_name"),
            "extension_filter": params.get("extension_filter", ".tif"),
            "prefix": params.get("prefix", ""),
            "summary": {
                "total_files_found": total_files_found,
                "files_processed": len(stage_2_tasks),
                "successful_insertions": successful_insertions,
                "failed_insertions": failed_insertions,
                "success_rate": f"{(successful_insertions / len(stage_2_tasks) * 100):.1f}%" if stage_2_tasks else "0%"
            },
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
