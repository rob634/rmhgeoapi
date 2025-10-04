"""
Container List Job Declaration - Two-Stage Fan-Out Pattern

This file declares a two-stage job that:
- Stage 1: Lists all blobs in a container
- Stage 2: Analyzes each blob individually (fan-out parallelism)

Results stored in task.result_data JSONB fields for SQL querying.

Author: Robert and Geospatial Claude Legion
Date: 4 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json


class ListContainerContentsWorkflow:
    """
    Two-stage fan-out job for detailed container inventory.

    Stage 1: Single task lists all blobs in container
    Stage 2: N parallel tasks (one per blob) analyze and store metadata

    Results: Each blob's metadata stored in Stage 2 task.result_data
    """

    # Job metadata
    job_type: str = "list_container_contents"
    description: str = "Detailed file-by-file analysis of container contents"

    # Stage definitions
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "list_blobs",
            "task_type": "list_container_blobs",
            "description": "Enumerate all blobs in container",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "analyze_blobs",
            "task_type": "analyze_single_blob",
            "description": "Analyze individual blob metadata and store in task.result_data",
            "parallelism": "fan_out"
        }
    ]

    # Parameter schema
    parameters_schema: Dict[str, Any] = {
        "container_name": {"type": "str", "required": True},
        "file_limit": {"type": "int", "min": 1, "max": 10000, "default": None},
        "filter": {"type": "dict", "default": {}}
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            container_name: str - Azure storage container name

        Optional:
            file_limit: int - Max files to process (1-10000, default: None = all)
            filter: dict - Filter criteria (extensions, prefix, size, dates)

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

        # Validate filter (optional)
        filter_criteria = params.get("filter", {})
        if filter_criteria and not isinstance(filter_criteria, dict):
            raise ValueError("filter must be a dictionary")

        # Validate filter sub-fields
        if filter_criteria:
            if "prefix" in filter_criteria:
                if not isinstance(filter_criteria["prefix"], str):
                    raise ValueError("filter.prefix must be a string")

            if "extensions" in filter_criteria:
                if not isinstance(filter_criteria["extensions"], list):
                    raise ValueError("filter.extensions must be a list")

            for size_field in ["min_size_mb", "max_size_mb"]:
                if size_field in filter_criteria:
                    if not isinstance(filter_criteria[size_field], (int, float)):
                        raise ValueError(f"filter.{size_field} must be a number")

        validated["filter"] = filter_criteria

        # NOTE: Container existence check removed from validation to avoid timeouts
        # Container will be checked when Stage 1 task executes

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

        Stage 1: Single task to list all blobs
        Stage 2: Fan-out - one task per blob from Stage 1 results

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
            # Stage 1: Single task to list blobs
            task_id = generate_deterministic_task_id(job_id, 1, "list")
            return [
                {
                    "task_id": task_id,
                    "task_type": "list_container_blobs",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "file_limit": job_params.get("file_limit"),
                        "filter": job_params.get("filter", {})
                    }
                }
            ]

        elif stage == 2:
            # Stage 2: FAN-OUT - Create one task per blob
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results for fan-out")

            # Extract blob names from Stage 1 result
            stage_1_result = previous_results[0]  # Single Stage 1 task
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 failed: {stage_1_result.get('error')}")

            blob_names = stage_1_result['result']['blob_names']

            # Create one task per blob with deterministic ID
            tasks = []
            for blob_name in blob_names:
                task_id = generate_deterministic_task_id(job_id, 2, blob_name)
                tasks.append({
                    "task_id": task_id,
                    "task_type": "analyze_single_blob",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "blob_name": blob_name
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
            job_type="list_container_contents",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=2,
            stage_results={},
            metadata={
                "description": "Detailed file-by-file container inventory",
                "created_by": "ListContainerContentsWorkflow"
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ListContainerContentsWorkflow.queue_job")

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
            job_type="list_container_contents",
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
