# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Single-stage raster validation (no processing)
# PURPOSE: Single-stage workflow for validating rasters without processing
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: ValidateRasterJob (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict-based validation)
# DEPENDENCIES: jobs.base.JobBase
# SOURCE: HTTP job submission for raster validation (Bronze container)
# SCOPE: Standalone raster validation for any raster file
# VALIDATION: CRS, bit-depth, data type detection, bounds checking, NoData value
# PATTERNS: Single-stage workflow, Read-only validation, No file modification
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "validate_raster"
# INDEX: ValidateRasterJob:28, stages:40, create_tasks_for_stage:60
# ============================================================================

"""
Validate Raster Job - Standalone Validation

Single-stage workflow for validating raster files without COG processing.

Use Cases:
- Quick validation check before committing to COG pipeline
- Testing raster files for CRS, bit-depth, type issues
- Batch validation of multiple files
- Pre-flight checks for large datasets

Stage 1 (Only): Validate Raster
- Check CRS (file metadata, user override, or fail)
- Analyze bit-depth efficiency (flag 64-bit as CRITICAL)
- Auto-detect raster type (RGB, RGBA, DEM, categorical, etc.)
- Validate type match if user specified
- Return validation results without processing

Author: Robert and Geospatial Claude Legion
Date: 9 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class ValidateRasterJob(JobBase):
    """
    Standalone raster validation job.

    Single stage that validates a raster file and returns results.
    Does not create COG or modify the file.
    """

    job_type: str = "validate_raster_job"
    description: str = "Validate raster file (CRS, bit-depth, type detection)"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate",
            "task_type": "validate_raster",
            "description": "Validate raster: CRS, bit-depth, type detection, bounds",
            "parallelism": "single"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "container_name": {"type": "str", "required": True, "default": None},  # Uses config.bronze_container_name if None
        "input_crs": {"type": "str", "required": False, "default": None},
        "raster_type": {
            "type": "str",
            "required": False,
            "default": "auto",
            "allowed": ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
        },
        "strict_mode": {"type": "bool", "required": False, "default": False},
        "_skip_validation": {"type": "bool", "required": False, "default": False},  # TESTING ONLY
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            blob_name: str - Blob path in container

        Optional:
            container_name: str - Container name (default: config.bronze_container_name)
            input_crs: str - User-provided CRS override
            raster_type: str - Expected type for validation
            strict_mode: bool - Fail on warnings
            _skip_validation: bool - TESTING ONLY

        Returns:
            Validated parameters dict

        Raises:
            ValueError: If parameters are invalid
        """
        validated = {}

        # Validate blob_name (required)
        if "blob_name" not in params:
            raise ValueError("blob_name is required")

        blob_name = params["blob_name"]
        if not isinstance(blob_name, str) or not blob_name.strip():
            raise ValueError("blob_name must be a non-empty string")

        validated["blob_name"] = blob_name.strip()

        # Validate container_name (optional)
        container_name = params.get("container_name")
        if container_name is not None:
            if not isinstance(container_name, str) or not container_name.strip():
                raise ValueError("container_name must be a non-empty string")
            validated["container_name"] = container_name.strip()
        else:
            validated["container_name"] = None

        # Validate input_crs (optional)
        input_crs = params.get("input_crs")
        if input_crs is not None:
            if not isinstance(input_crs, str) or not input_crs.strip():
                raise ValueError("input_crs must be a non-empty string")
            validated["input_crs"] = input_crs.strip()

        # Validate raster_type (optional)
        raster_type = params.get("raster_type", "auto")
        allowed_types = ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
        if raster_type not in allowed_types:
            raise ValueError(f"raster_type must be one of {allowed_types}, got {raster_type}")
        validated["raster_type"] = raster_type

        # Validate strict_mode (optional)
        strict_mode = params.get("strict_mode", False)
        if not isinstance(strict_mode, bool):
            raise ValueError("strict_mode must be boolean")
        validated["strict_mode"] = strict_mode

        # Validate _skip_validation (optional, testing only)
        skip_validation = params.get("_skip_validation", False)
        if not isinstance(skip_validation, bool):
            raise ValueError("_skip_validation must be boolean")
        validated["_skip_validation"] = skip_validation

        return validated

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: dict, job_id: str, previous_results: list = None) -> list[dict]:
        """
        Generate task parameters for stage.

        Stage 1 (Only): Single task to validate raster

        Args:
            stage: Stage number (only 1 for this job)
            job_params: Job parameters
            job_id: Job ID for task ID generation
            previous_results: Not used (single stage)

        Returns:
            List with single task parameter dict

        Raises:
            ValueError: If stage != 1
        """
        from core.task_id import generate_deterministic_task_id
        from config import get_config
        from infrastructure.blob import BlobRepository

        if stage != 1:
            raise ValueError(f"ValidateRasterJob only has 1 stage, got stage {stage}")

        config = get_config()

        # Use config default if container_name not specified
        container_name = job_params.get('container_name') or config.bronze_container_name

        # Build blob URL with SAS token
        blob_repo = BlobRepository.instance()
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=container_name,
            blob_name=job_params['blob_name'],
            hours=1
        )

        task_id = generate_deterministic_task_id(job_id, 1, "validate")

        return [
            {
                "task_id": task_id,
                "task_type": "validate_raster",
                "parameters": {
                    "blob_url": blob_url,
                    "blob_name": job_params['blob_name'],
                    "container_name": container_name,
                    "input_crs": job_params.get('input_crs'),
                    "raster_type": job_params.get('raster_type', 'auto'),
                    "strict_mode": job_params.get('strict_mode', False),
                    "_skip_validation": job_params.get('_skip_validation', False)
                }
            }
        ]

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
            job_type="validate_raster_job",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=1,
            stage_results={},
            metadata={
                "description": "Standalone raster validation",
                "created_by": "ValidateRasterJob",
                "blob_name": params.get("blob_name"),
                "container_name": params.get("container_name"),
                "raster_type": params.get("raster_type", "auto")
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ValidateRasterJob.queue_job")

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
            job_type="validate_raster_job",
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
        Aggregate results from completed task into job summary.

        Args:
            context: JobExecutionContext with task results

        Returns:
            Aggregated job results dict
        """
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Single task - Stage 1
        if task_results and task_results[0].result_data:
            result = task_results[0].result_data.get("result", {})
            # Handler returns "valid" field
            validation_status = "passed" if result.get("valid") else "failed"

            return {
                "job_type": "validate_raster_job",
                "blob_name": params.get("blob_name"),
                "container_name": params.get("container_name"),
                "validation_status": validation_status,
                "validation_result": result,
                "tasks_executed": len(task_results),
                "task_status": task_results[0].status.value if hasattr(task_results[0].status, 'value') else str(task_results[0].status)
            }
        else:
            return {
                "job_type": "validate_raster_job",
                "blob_name": params.get("blob_name"),
                "container_name": params.get("container_name"),
                "validation_status": "failed",
                "error": "No task results available"
            }
