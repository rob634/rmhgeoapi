# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Two-stage small raster processing (<= 1GB)
# PURPOSE: 2-stage workflow for processing small rasters to COGs (<= 1GB)
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: ProcessRasterWorkflow (JobBase implementation)
# INTERFACES: JobBase (implements 5-method contract)
# PYDANTIC_MODELS: None (uses dict-based validation)
# DEPENDENCIES: jobs.base.JobBase, core.models.enums.TaskStatus
# SOURCE: HTTP job submission for small raster processing (Bronze container)
# SCOPE: Small file raster processing pipeline (<= 1GB files)
# VALIDATION: Stage 1 validates raster, Stage 2 creates COG
# PATTERNS: Two-stage workflow, Direct COG conversion (no tiling)
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS as "process_raster"
# INDEX: ProcessRasterWorkflow:30, stages:42, create_tasks_for_stage:68
# MIGRATION: 9 OCT 2025 - Removed create_stage_X_tasks, added create_tasks_for_stage
# ============================================================================

"""
Process Raster Workflow - Small File Pipeline (<= 1GB)

Two-stage workflow for converting rasters to Cloud Optimized GeoTIFFs:

Stage 1: Validate Raster
- Check CRS (file metadata, user override, or fail)
- Analyze bit-depth efficiency (flag 64-bit as CRITICAL)
- Auto-detect raster type (RGB, RGBA, DEM, categorical, etc.)
- Validate type match if user specified
- Recommend optimal COG settings

Stage 2: Reproject + Create COG
- Single-pass reprojection + COG creation using rio-cogeo
- Auto-select compression and resampling based on raster type
- Upload to silver container
- No intermediate storage needed

Key Innovation:
- rio-cogeo combines reprojection + COG creation in one pass
- Eliminates intermediate files
- Type-specific optimization (JPEG for RGB, WebP for RGBA, LERC for DEM)

Author: Robert and Geospatial Claude Legion
Date: 9 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class ProcessRasterWorkflow(JobBase):
    """
    Small file raster processing workflow (<= 1GB).

    Stages:
    1. Validate: CRS, bit-depth, type detection
    2. Create COG: Reproject + COG in single operation
    """

    job_type: str = "process_raster"
    description: str = "Process raster to COG (files <= 1GB)"

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
        "output_tier": {
            "type": "str",
            "required": False,
            "default": "analysis",
            "allowed": ["visualization", "analysis", "archive", "all"],
            "description": "COG output tier: visualization (JPEG/hot), analysis (DEFLATE/hot), archive (LZW/cool), or all (create all applicable tiers)"
        },
        "compression": {"type": "str", "required": False, "default": None},  # Auto-selected if None (deprecated - use output_tier)
        "jpeg_quality": {"type": "int", "required": False, "default": 85},
        "overview_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected
        "reproject_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected
        "strict_mode": {"type": "bool", "required": False, "default": False},
        "_skip_validation": {"type": "bool", "required": False, "default": False},  # TESTING ONLY
        "output_folder": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Override output folder path (e.g., 'cogs/satellite/'). If None, mirrors input folder structure."
        },
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
            output_tier: str - COG output tier (visualization, analysis, archive, all)
            compression: str - Compression method override (deprecated - use output_tier)
            jpeg_quality: int - JPEG quality (1-100)
            overview_resampling: str - Resampling method for overviews
            reproject_resampling: str - Resampling method for reprojection
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

        # Validate output_tier (optional)
        output_tier = params.get("output_tier", "analysis")
        allowed_tiers = ["visualization", "analysis", "archive", "all"]
        if output_tier not in allowed_tiers:
            raise ValueError(f"output_tier must be one of {allowed_tiers}, got {output_tier}")
        validated["output_tier"] = output_tier

        # Validate compression (optional)
        compression = params.get("compression")
        if compression is not None:
            if not isinstance(compression, str):
                raise ValueError("compression must be a string")
            validated["compression"] = compression

        # Validate jpeg_quality (optional)
        jpeg_quality = params.get("jpeg_quality", 85)
        if not isinstance(jpeg_quality, int):
            try:
                jpeg_quality = int(jpeg_quality)
            except (ValueError, TypeError):
                raise ValueError("jpeg_quality must be an integer")
        if jpeg_quality < 1 or jpeg_quality > 100:
            raise ValueError(f"jpeg_quality must be between 1 and 100, got {jpeg_quality}")
        validated["jpeg_quality"] = jpeg_quality

        # Validate overview_resampling (optional)
        overview_resampling = params.get("overview_resampling")
        if overview_resampling is not None:
            if not isinstance(overview_resampling, str):
                raise ValueError("overview_resampling must be a string")
            validated["overview_resampling"] = overview_resampling

        # Validate reproject_resampling (optional)
        reproject_resampling = params.get("reproject_resampling")
        if reproject_resampling is not None:
            if not isinstance(reproject_resampling, str):
                raise ValueError("reproject_resampling must be a string")
            validated["reproject_resampling"] = reproject_resampling

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

        # Validate output_folder (optional)
        output_folder = params.get("output_folder")
        if output_folder is not None:
            if not isinstance(output_folder, str):
                raise ValueError("output_folder must be a string")
            # Remove leading/trailing slashes for consistency
            output_folder = output_folder.strip().strip('/')
            if output_folder:  # Only set if non-empty after stripping
                validated["output_folder"] = output_folder
            else:
                validated["output_folder"] = None
        else:
            validated["output_folder"] = None

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
            job_type="process_raster",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=2,
            stage_results={},
            metadata={
                "description": "Process raster to COG pipeline",
                "created_by": "ProcessRasterWorkflow",
                "blob_name": params.get("blob_name"),
                "container_name": params.get("container_name"),
                "raster_type": params.get("raster_type", "auto"),
                "output_tier": params.get("output_tier", "analysis"),
                "output_folder": params.get("output_folder")
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ProcessRasterWorkflow.queue_job")

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
            job_type="process_raster",
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

        CRITICAL: This is the ONLY method CoreMachine calls. Old create_stage_X_tasks methods REMOVED.

        Stage 1: Single task to validate raster
        Stage 2: Single task to create COG (requires Stage 1 results)

        Args:
            stage: Stage number (1 or 2)
            job_params: Job parameters from database
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage (required for Stage 2)

        Returns:
            List of task parameter dicts

        Raises:
            ValueError: If Stage 2 called without previous_results or invalid stage number
        """
        from core.task_id import generate_deterministic_task_id
        from config import get_config
        from infrastructure.blob import BlobRepository

        config = get_config()

        if stage == 1:
            # Stage 1: Validate raster
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

        elif stage == 2:
            # Stage 2: Create COG
            # REQUIRES previous_results from Stage 1
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 results - previous_results cannot be None")

            # Extract validation result from Stage 1 task
            stage_1_result = previous_results[0]
            if not stage_1_result.get('success'):
                raise ValueError(f"Stage 1 validation failed: {stage_1_result.get('error')}")

            validation_result = stage_1_result.get('result', {})

            # Get source CRS from validation (REQUIRED)
            source_crs = validation_result.get('source_crs')
            if not source_crs:
                raise ValueError("No source_crs found in Stage 1 validation results")

            # Use config default if container_name not specified
            container_name = job_params.get('container_name') or config.bronze_container_name

            # Build blob URL with SAS token
            blob_repo = BlobRepository.instance()
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=job_params['blob_name'],
                hours=1
            )

            # Output blob name - configurable folder or mirror input structure
            blob_name = job_params['blob_name']
            output_folder = job_params.get('output_folder')

            if output_folder:
                # User specified output folder - use just filename in that folder
                filename = blob_name.split('/')[-1]
                if filename.lower().endswith('.tif'):
                    output_blob_name = f"{output_folder}/{filename[:-4]}_cog.tif"
                else:
                    output_blob_name = f"{output_folder}/{filename}_cog.tif"
            else:
                # Default: mirror input folder structure
                if blob_name.lower().endswith('.tif'):
                    output_blob_name = blob_name[:-4] + '_cog.tif'
                else:
                    output_blob_name = blob_name + '_cog.tif'

            task_id = generate_deterministic_task_id(job_id, 2, "create_cog")

            return [
                {
                    "task_id": task_id,
                    "task_type": "create_cog",
                    "parameters": {
                        "blob_url": blob_url,
                        "blob_name": job_params['blob_name'],
                        "container_name": container_name,
                        "source_crs": source_crs,
                        "target_crs": "EPSG:4326",
                        "raster_type": validation_result.get('raster_type', {}),
                        "output_blob_name": output_blob_name,
                        "output_tier": job_params.get('output_tier', 'analysis'),  # COG tier selection
                        "compression": job_params.get('compression'),  # User override or None (deprecated)
                        "jpeg_quality": job_params.get('jpeg_quality', 85),
                        "overview_resampling": job_params.get('overview_resampling'),  # User override or None
                        "reproject_resampling": job_params.get('reproject_resampling'),  # User override or None
                    }
                }
            ]

        else:
            raise ValueError(f"ProcessRasterWorkflow only has 2 stages, got stage {stage}")

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
        stage_1_tasks = [t for t in task_results if t.task_type == "validate_raster"]
        stage_2_tasks = [t for t in task_results if t.task_type == "create_cog"]

        # Extract validation results
        validation_summary = {}
        if stage_1_tasks and stage_1_tasks[0].result_data:
            validation_result = stage_1_tasks[0].result_data.get("result", {})
            validation_summary = {
                "source_crs": validation_result.get("source_crs"),
                "raster_type": validation_result.get("raster_type", {}).get("detected_type"),
                "confidence": validation_result.get("raster_type", {}).get("confidence"),
                "bit_depth_efficient": validation_result.get("bit_depth_check", {}).get("efficient"),
                "warnings": validation_result.get("warnings", [])
            }

        # Extract COG results
        cog_summary = {}
        if stage_2_tasks and stage_2_tasks[0].result_data:
            cog_result = stage_2_tasks[0].result_data.get("result", {})
            cog_summary = {
                "cog_blob": cog_result.get("cog_blob"),
                "cog_container": cog_result.get("cog_container"),
                "reprojection_performed": cog_result.get("reprojection_performed"),
                "size_mb": cog_result.get("size_mb"),
                "compression": cog_result.get("compression"),
                "processing_time_seconds": cog_result.get("processing_time_seconds")
            }

        return {
            "job_type": "process_raster",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container_name"),
            "validation": validation_summary,
            "cog": cog_summary,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
