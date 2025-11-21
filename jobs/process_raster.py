# ============================================================================
# CLAUDE CONTEXT - JOB DEFINITION
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job - Two-stage small raster processing (<= 1GB)
# PURPOSE: 2-stage workflow for processing small rasters to COGs (<= 1GB)
# LAST_REVIEWED: 3 NOV 2025
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
    3. Create STAC: Generate STAC metadata for COG
    """

    job_type: str = "process_raster"
    description: str = "Process raster to COG with STAC metadata (files <= 1GB)"

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
        },
        {
            "number": 3,
            "name": "create_stac",
            "task_type": "extract_stac_metadata",
            "description": "Create STAC metadata for COG (ready for TiTiler-pgstac)",
            "parallelism": "single"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_name": {"type": "str", "required": True},
        "container_name": {"type": "str", "required": True, "default": None},  # Uses config.storage.bronze.get_container('rasters') if None
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
        "target_crs": {
            "type": "str",
            "required": False,
            "default": "EPSG:4326",
            "description": "Target CRS for output COG (default: EPSG:4326). Common: EPSG:3857 (Web Mercator), EPSG:4326 (WGS84)"
        },
        "compression": {"type": "str", "required": False, "default": None},  # Auto-selected if None (deprecated - use output_tier)
        "jpeg_quality": {"type": "int", "required": False, "default": 85},
        "overview_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected
        "reproject_resampling": {"type": "str", "required": False, "default": None},  # Auto-selected
        "strict_mode": {"type": "bool", "required": False, "default": False},
        "in_memory": {
            "type": "bool",
            "required": False,
            "default": None,
            "description": "Process COG in-memory (True) vs disk-based (False). If not specified, uses config.raster_cog_in_memory. In-memory is faster for small files (<1GB), disk-based is better for large files."
        },
        "collection_id": {
            "type": "str",
            "required": False,
            "default": None,  # Uses config.stac_default_collection if None
            "description": "STAC collection ID for metadata (defaults to config.stac_default_collection='system-rasters')"
        },
        "item_id": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Custom STAC item ID (default: auto-generated from blob name and collection)"
        },
        "_skip_validation": {"type": "bool", "required": False, "default": False},  # TESTING ONLY
        "output_folder": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Optional output folder path (e.g., 'cogs/satellite/'). If None, writes to container root."
        },
    }

    @staticmethod
    def validate_job_parameters(params: dict) -> dict:
        """
        Validate job parameters.

        Required:
            blob_name: str - Blob path in container

        Optional:
            container_name: str - Container name (default: config.storage.bronze.get_container('rasters'))
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
            ResourceNotFoundError: If container or blob doesn't exist
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

        # Validate target_crs (optional)
        target_crs = params.get("target_crs", "EPSG:4326")
        if not isinstance(target_crs, str) or not target_crs.strip():
            raise ValueError("target_crs must be a non-empty string")
        validated["target_crs"] = target_crs.strip()

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

        # Validate collection_id (optional)
        collection_id = params.get("collection_id", "system-rasters")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise ValueError("collection_id must be a non-empty string")
        validated["collection_id"] = collection_id.strip()

        # Validate item_id (optional)
        item_id = params.get("item_id")
        if item_id is not None:
            if not isinstance(item_id, str) or not item_id.strip():
                raise ValueError("item_id must be a non-empty string")
            validated["item_id"] = item_id.strip()

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

        # ================================================================
        # NEW (11 NOV 2025): Validate container and blob exist (fail-fast)
        # Phase 1: Immediate validation with Azure ResourceNotFoundError
        # ================================================================
        from azure.core.exceptions import ResourceNotFoundError
        from infrastructure.blob import BlobRepository

        blob_repo = BlobRepository.instance()

        # Resolve container name (use config default if None)
        container_name = validated.get("container_name")
        if container_name is None:
            from config import get_config
            config = get_config()
            container_name = config.storage.bronze.get_container('rasters')
            validated["container_name"] = container_name

        blob_name = validated["blob_name"]

        # Validate container exists
        if not blob_repo.container_exists(container_name):
            raise ResourceNotFoundError(
                f"Container '{container_name}' does not exist in storage account "
                f"'{blob_repo.account_name}'. Verify container name spelling or create "
                f"container before submitting job."
            )

        # Validate blob exists
        if not blob_repo.blob_exists(container_name, blob_name):
            raise ResourceNotFoundError(
                f"File '{blob_name}' not found in existing container '{container_name}' "
                f"(storage account: '{blob_repo.account_name}'). Verify blob path spelling. "
                f"Available blobs can be listed via /api/containers/{container_name}/blobs endpoint."
            )

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
            total_stages=3,
            stage_results={},
            metadata={
                "description": "Process raster to COG with STAC metadata",
                "created_by": "ProcessRasterWorkflow",
                "blob_name": params.get("blob_name"),
                "container_name": params.get("container_name"),
                "raster_type": params.get("raster_type", "auto"),
                "output_tier": params.get("output_tier", "analysis"),
                "output_folder": params.get("output_folder"),
                "collection_id": params.get("collection_id", "system-rasters"),
                "item_id": params.get("item_id")
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
        correlation_id = str(uuid.uuid4())[:8]
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
        Stage 3: Single task to create STAC metadata (requires Stage 2 results)

        Args:
            stage: Stage number (1, 2, or 3)
            job_params: Job parameters from database
            job_id: Job ID for task ID generation
            previous_results: Results from previous stage (required for Stages 2 and 3)

        Returns:
            List of task parameter dicts

        Raises:
            ValueError: If stage requires previous_results but not provided, or invalid stage number
        """
        from core.task_id import generate_deterministic_task_id
        from config import get_config
        from infrastructure.blob import BlobRepository

        config = get_config()

        if stage == 1:
            # Stage 1: Validate raster
            # Use config default if container_name not specified
            container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')

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
            container_name = job_params.get('container_name') or config.storage.bronze.get_container('rasters')

            # Output blob name - extract filename and optionally prepend folder
            blob_name = job_params['blob_name']
            output_folder = job_params.get('output_folder')

            # Extract just the filename from input path
            filename = blob_name.split('/')[-1]

            # Generate output filename (replace or append _cog)
            if filename.lower().endswith('.tif'):
                output_filename = f"{filename[:-4]}_cog.tif"
            else:
                output_filename = f"{filename}_cog.tif"

            # Prepend output folder if specified, otherwise write to root
            if output_folder:
                output_blob_name = f"{output_folder}/{output_filename}"
            else:
                # Default: write to container root (flat structure)
                output_blob_name = output_filename

            task_id = generate_deterministic_task_id(job_id, 2, "create_cog")

            return [
                {
                    "task_id": task_id,
                    "task_type": "create_cog",
                    "parameters": {
                        "blob_name": job_params['blob_name'],
                        "container_name": container_name,
                        "source_crs": source_crs,
                        "target_crs": job_params.get('target_crs', 'EPSG:4326'),
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

        elif stage == 3:
            # Stage 3: Create STAC metadata
            # REQUIRES previous_results from Stage 2
            if not previous_results:
                raise ValueError("Stage 3 requires Stage 2 results - previous_results cannot be None")

            # Extract COG result from Stage 2 task
            stage_2_result = previous_results[0]
            if not stage_2_result.get('success'):
                raise ValueError(f"Stage 2 COG creation failed: {stage_2_result.get('error')}")

            cog_result = stage_2_result.get('result', {})

            # Get COG blob path and container from Stage 2
            cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
            # CRITICAL: Stage 2 returns 'cog_container' (not 'container') - see tasks/create_cog.py result structure
            cog_container = cog_result.get('cog_container') or config.silver_container_name

            if not cog_blob:
                raise ValueError("Stage 2 results missing COG blob path (expected 'output_blob' or 'cog_blob')")

            # Get collection ID (default to system-rasters for operational tracking)
            collection_id = job_params.get('collection_id', 'system-rasters')

            # Get custom item_id if provided
            item_id = job_params.get('item_id')

            task_id = generate_deterministic_task_id(job_id, 3, "stac")

            # Build task parameters
            task_params = {
                "container_name": cog_container,
                "blob_name": cog_blob,
                "collection_id": collection_id
            }

            # Add item_id if provided
            if item_id:
                task_params["item_id"] = item_id

            return [
                {
                    "task_id": task_id,
                    "task_type": "extract_stac_metadata",  # Reuse existing handler from stac_catalog.py
                    "parameters": task_params
                }
            ]

        else:
            raise ValueError(f"ProcessRasterWorkflow only has 3 stages, got stage {stage}")

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Create final job summary from all completed tasks.

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
        stage_3_tasks = [t for t in task_results if t.task_type == "extract_stac_metadata"]

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

        # Extract STAC results
        stac_summary = {}
        # titiler_pgstac_urls = {}  # COMMENTED OUT (7 NOV 2025) - may restore later if TiTiler-PgSTAC deployed
        vanilla_titiler_urls = {}
        share_url = None

        if stage_3_tasks and stage_3_tasks[0].result_data:
            stac_result = stage_3_tasks[0].result_data.get("result", {})
            collection_id = stac_result.get("collection_id", "cogs")
            item_id = stac_result.get("item_id")

            stac_summary = {
                "item_id": item_id,
                "collection_id": collection_id,
                "bbox": stac_result.get("bbox"),
                "inserted_to_pgstac": stac_result.get("inserted_to_pgstac", True),
                "ready_for_titiler": True
            }

            # Generate TiTiler URLs (10 NOV 2025 - Unified method)
            # Uses /cog/ endpoint with /vsiaz/ paths (correct format per TITILER-VALIDATION-TASK.md)
            from config import get_config
            config = get_config()

            titiler_urls = None
            share_url = None

            if cog_summary.get('cog_blob') and cog_summary.get('cog_container'):
                try:
                    # Generate Single COG URLs using unified method
                    titiler_urls = config.generate_titiler_urls_unified(
                        mode="cog",
                        container=cog_summary['cog_container'],
                        blob_name=cog_summary['cog_blob']
                    )
                    share_url = titiler_urls.get("viewer_url")
                except Exception as e:
                    # Failed to generate URLs - job continues without them
                    titiler_urls = None
                    share_url = None

        return {
            "job_type": "process_raster",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container_name"),
            "validation": validation_summary,
            "cog": cog_summary,
            "stac": stac_summary,
            "titiler_urls": titiler_urls,  # TiTiler visualization URLs (mode=cog)
            "share_url": share_url,  # PRIMARY URL - share this with end users!
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
