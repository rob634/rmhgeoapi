# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Single-stage container statistics generation
# PURPOSE: Generate aggregate statistics about blob container (fast, lightweight)
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: ContainerSummaryWorkflow (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict-based validation)
# DEPENDENCIES: jobs.base.JobBase, hashlib, json
# SOURCE: HTTP job submission for container statistics
# SCOPE: Container-wide aggregate statistics (file types, sizes, counts)
# VALIDATION: Container name validation, filter criteria validation
# PATTERNS: Single-stage job, Streaming aggregation (memory-efficient)
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "summarize_container"
# INDEX: ContainerSummaryWorkflow:17, stages:26, create_tasks_for_stage:52
# ============================================================================

"""
Container Summary Job Declaration

Single-stage job that generates aggregate statistics about a blob container.
Fast, lightweight operation suitable for dashboards and monitoring.

Author: Robert and Geospatial Claude Legion
Date: 3 OCT 2025
Last Updated: 29 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class ContainerSummaryWorkflow(JobBase):
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
        correlation_id = str(uuid.uuid4())[:8]
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

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Aggregate results from single container summary task.

        Since this is a single-stage, single-task job, aggregation is simple:
        just extract and pass through the comprehensive statistics from the task.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Job results with statistics from the summary task
        """
        from core.models import TaskStatus
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            "ContainerSummaryWorkflow.finalize_job"
        )

        try:
            logger.info("🔄 STEP 1: Starting result aggregation...")

            task_results = context.task_results
            params = context.parameters

            logger.info(f"   Total tasks: {len(task_results)}")
            logger.info(f"   Container: {params.get('container_name')}")

            # STEP 2: Extract single task result
            try:
                logger.info("🔄 STEP 2: Extracting task result...")

                if not task_results:
                    logger.error("   No task results found!")
                    return {
                        "job_type": "summarize_container",
                        "container_name": params.get("container_name"),
                        "error": "No task results found",
                        "success": False
                    }

                summary_task = task_results[0]  # Only one task
                logger.info(f"   Task status: {summary_task.status}")

                # Check task status
                if summary_task.status != TaskStatus.COMPLETED:
                    logger.warning(f"   Task did not complete successfully: {summary_task.status}")
                    error_msg = summary_task.result_data.get("error") if summary_task.result_data else "Unknown error"
                    return {
                        "job_type": "summarize_container",
                        "container_name": params.get("container_name"),
                        "error": error_msg,
                        "task_status": summary_task.status.value if hasattr(summary_task.status, 'value') else str(summary_task.status),
                        "success": False
                    }

                # Extract task result
                if not summary_task.result_data:
                    logger.error("   Task completed but has no result_data!")
                    return {
                        "job_type": "summarize_container",
                        "container_name": params.get("container_name"),
                        "error": "Task completed but no result data",
                        "success": False
                    }

                task_result = summary_task.result_data.get("result", {})
                logger.info(f"   Task result extracted: {len(task_result)} keys")

            except Exception as e:
                logger.error(f"❌ STEP 2 FAILED: Error extracting task result: {e}")
                return {
                    "job_type": "summarize_container",
                    "container_name": params.get("container_name"),
                    "error": f"Failed to extract task result: {e}",
                    "success": False
                }

            # STEP 3: Build aggregated result (pass-through with job metadata)
            try:
                logger.info("🔄 STEP 3: Building final result...")

                # Extract statistics from task result
                statistics = task_result.get("statistics", {})
                execution_info = task_result.get("execution_info", {})

                result = {
                    "job_type": "summarize_container",
                    "container_name": params.get("container_name"),
                    "file_limit": params.get("file_limit"),
                    "filter": params.get("filter"),
                    "analysis_timestamp": task_result.get("analysis_timestamp"),
                    "summary": statistics,  # Complete statistics from task
                    "execution_info": execution_info,
                    "stages_completed": context.current_stage,
                    "total_tasks_executed": len(task_results),
                    "task_status": summary_task.status.value if hasattr(summary_task.status, 'value') else str(summary_task.status),
                    "success": True
                }

                logger.info("✅ STEP 3: Result built successfully")
                logger.info(f"🎉 Aggregation complete: {statistics.get('total_files', 0)} files, {statistics.get('total_size_gb', 0)} GB")

                return result

            except Exception as e:
                logger.error(f"❌ STEP 3 FAILED: Error building result: {e}")
                # Return partial result
                return {
                    "job_type": "summarize_container",
                    "container_name": params.get("container_name"),
                    "error": f"Failed to build final result: {e}",
                    "raw_task_result": task_result,  # Include raw result for debugging
                    "success": False
                }

        except Exception as e:
            logger.error(f"❌ CRITICAL: Aggregation failed completely: {e}")
            return {
                "job_type": "summarize_container",
                "error": f"Critical aggregation failure: {e}",
                "fallback": True,
                "success": False
            }
