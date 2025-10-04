"""
Container Summary Job Declaration

Single-stage job that generates aggregate statistics about a blob container.
Fast, lightweight operation suitable for dashboards and monitoring.

Author: Robert and Geospatial Claude Legion
Date: 3 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json


class ContainerSummaryWorkflow:
    """Single-stage container summary job - pure data declaration."""

    # Job metadata
    job_type: str = "summarize_container"
    description: str = "Generate aggregate statistics for a blob container"

    # Stage definitions (pure data!)
    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "analyze_container",
            "task_type": "container_summary_task",
            "description": "Scan container and compute aggregate statistics",
            "creates_tasks": lambda params, results: [
                {
                    "container_name": params["container_name"],
                    "file_limit": params.get("file_limit"),
                    "filter": params.get("filter", {})
                }
            ]
        }
    ]

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            - container_name: str

        Optional:
            - file_limit: int
            - filter: dict {prefix, extensions, min_size_mb, max_size_mb, modified_after, modified_before}
        """
        # Validate required fields
        if "container_name" not in params:
            raise ValueError("Missing required parameter: container_name")

        container_name = params["container_name"]
        if not isinstance(container_name, str) or not container_name:
            raise ValueError("container_name must be a non-empty string")

        # Validate optional fields
        if "file_limit" in params:
            file_limit = params["file_limit"]
            if not isinstance(file_limit, int) or file_limit < 1:
                raise ValueError("file_limit must be a positive integer")

        if "filter" in params:
            filter_criteria = params["filter"]
            if not isinstance(filter_criteria, dict):
                raise ValueError("filter must be a dictionary")

            # Validate filter fields if present
            if "extensions" in filter_criteria:
                if not isinstance(filter_criteria["extensions"], list):
                    raise ValueError("filter.extensions must be a list")

            for size_field in ["min_size_mb", "max_size_mb"]:
                if size_field in filter_criteria:
                    if not isinstance(filter_criteria[size_field], (int, float)):
                        raise ValueError(f"filter.{size_field} must be a number")

        # NOTE: Container existence check removed from validation to avoid timeouts
        # Container will be checked when task executes

        return params

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

        Args:
            stage: Stage number (always 1 for single-stage job)
            job_params: Job parameters
            job_id: Job ID for task ID generation

        Returns:
            List of task parameter dicts
        """
        if stage == 1:
            # Single task for container summary
            return [
                {
                    "task_id": f"{job_id[:8]}-s1-summary",
                    "task_type": "container_summary_task",
                    "parameters": {
                        "container_name": job_params["container_name"],
                        "file_limit": job_params.get("file_limit"),
                        "filter": job_params.get("filter", {})
                    }
                }
            ]
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
            job_type="summarize_container",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=1,
            stage_results={},
            metadata={
                "description": "Generate aggregate statistics for a blob container",
                "created_by": "ContainerSummaryWorkflow"
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ContainerSummaryWorkflow.queue_job")

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
            job_type="summarize_container",
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
