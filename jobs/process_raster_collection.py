# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - PROCESS RASTER COLLECTION
# ============================================================================
# PURPOSE: 4-stage workflow for processing raster tile collections to COGs + MosaicJSON
# EXPORTS: ProcessRasterCollectionWorkflow class
# INTERFACES: CoreMachine contract - create_tasks_for_stage() signature
# PYDANTIC_MODELS: None (class attributes)
# DEPENDENCIES: core.models.enums.TaskStatus
# SOURCE: Bronze container raster tiles (vendor deliveries)
# SCOPE: Multi-tile raster processing with MosaicJSON output
# VALIDATION: Stage 1 validates all tiles, Stage 2 creates COGs, Stage 3 creates MosaicJSON, Stage 4 creates STAC collection
# PATTERNS: CoreMachine compliance, fan-out/fan-in architecture
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS
# INDEX: ProcessRasterCollectionWorkflow:50, create_tasks_for_stage:150
# ============================================================================

"""
Process Raster Collection Workflow - Multi-Tile Pipeline

Four-stage workflow for converting vendor tile deliveries to COGs with MosaicJSON:

Stage 1: Validate All Tiles (Fan-out)
- Parallel validation of all tiles in collection
- Check CRS consistency across tiles
- Analyze bit-depth efficiency
- Auto-detect raster type
- Verify tiles are compatible for mosaicking

Stage 2: Create COGs (Fan-out)
- Parallel COG creation for all tiles
- Reproject + optimize in single pass
- Type-specific compression
- Upload to silver container with consistent naming

Stage 3: Create MosaicJSON (Fan-in)
- Single task aggregates all COG paths
- Generate MosaicJSON with quadkey indexing
- Auto-calculate zoom levels
- Upload MosaicJSON to silver container

Stage 4: Create STAC Collection (Fan-in)
- Single task creates collection-level STAC item
- Add MosaicJSON as primary asset
- Calculate spatial/temporal extent
- Insert into PgSTAC collections table

Key Features:
- Fan-out parallelism for tile processing (Stages 1-2)
- Fan-in aggregation for collection outputs (Stages 3-4)
- Reuses validate_raster and create_cog task handlers
- New create_mosaicjson and create_stac_collection handlers
- Compatible with vendor delivery discovery system

Author: Robert and Geospatial Claude Legion
Date: 20 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class ProcessRasterCollectionWorkflow(JobBase):
    """
    Multi-tile raster collection processing workflow with MosaicJSON.

    Stages:
    1. Validate: Parallel validation of all tiles
    2. Create COGs: Parallel COG creation
    3. Create MosaicJSON: Aggregate COGs into virtual mosaic
    4. Create STAC Collection: Collection-level STAC item
    """

    job_type: str = "process_raster_collection"
    description: str = "Process raster tile collection to COGs with MosaicJSON"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "validate_tiles",
            "task_type": "validate_raster",
            "description": "Validate all tiles in parallel",
            "parallelism": "single"  # Orchestration-time parallelism (N from blob_list)
        },
        {
            "number": 2,
            "name": "create_cogs",
            "task_type": "create_cog",
            "description": "Create COGs from all tiles in parallel",
            "parallelism": "fan_out"  # Result-driven parallelism (N from Stage 1 results)
        },
        {
            "number": 3,
            "name": "create_mosaicjson",
            "task_type": "create_mosaicjson",
            "description": "Generate MosaicJSON from COG collection",
            "parallelism": "fan_in"  # Auto-aggregation (CoreMachine creates task)
        },
        {
            "number": 4,
            "name": "create_stac_collection",
            "task_type": "create_stac_collection",
            "description": "Create STAC collection item with MosaicJSON asset",
            "parallelism": "fan_in"  # Auto-aggregation (CoreMachine creates task)
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_list": {
            "type": "list",
            "required": True,
            "description": "List of raster tile blob paths"
        },
        "collection_id": {
            "type": "str",
            "required": True,
            "description": "Unique collection identifier (e.g., 'namangan_2019_tiles')"
        },
        "collection_description": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Human-readable collection description"
        },
        "container_name": {
            "type": "str",
            "required": True,
            "default": None,
            "description": "Source container name (uses config.bronze_container_name if None)"
        },
        "input_crs": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Override CRS for all tiles (optional)"
        },
        "raster_type": {
            "type": "str",
            "required": False,
            "default": "auto",
            "allowed": ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"],
            "description": "Raster type - auto-detected if not specified"
        },
        "output_tier": {
            "type": "str",
            "required": False,
            "default": "analysis",
            "allowed": ["visualization", "analysis", "archive"],
            "description": "COG output tier (only one tier for collections)"
        },
        "output_folder": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Override output folder path (e.g., 'cogs/satellite/'). If None, mirrors input folder structure."
        },
        "create_mosaicjson": {
            "type": "bool",
            "required": False,
            "default": True,
            "description": "Create MosaicJSON virtual mosaic (Stage 3)"
        },
        "create_stac_collection": {
            "type": "bool",
            "required": False,
            "default": True,
            "description": "Create STAC collection item (Stage 4)"
        },
        "jpeg_quality": {
            "type": "int",
            "required": False,
            "default": 85,
            "description": "JPEG quality (1-100) for visualization tier"
        }
    }

    @staticmethod
    def validate_job_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate job parameters against schema.

        Args:
            params: Raw job parameters

        Returns:
            Validated parameters

        Raises:
            ValueError: Validation failure
        """
        validated = {}

        # Validate blob_list
        blob_list = params.get("blob_list")
        if not blob_list or not isinstance(blob_list, list):
            raise ValueError("blob_list must be a non-empty list")
        if len(blob_list) < 2:
            raise ValueError("Collection must contain at least 2 tiles")
        if not all(isinstance(b, str) for b in blob_list):
            raise ValueError("All blob_list items must be strings")
        validated["blob_list"] = blob_list

        # Validate collection_id
        collection_id = params.get("collection_id")
        if not collection_id or not isinstance(collection_id, str):
            raise ValueError("collection_id is required")
        validated["collection_id"] = collection_id

        # Validate collection_description
        collection_description = params.get("collection_description")
        if collection_description is None:
            # Auto-generate from collection_id
            validated["collection_description"] = f"Raster tile collection: {collection_id}"
        else:
            if not isinstance(collection_description, str):
                raise ValueError("collection_description must be a string")
            validated["collection_description"] = collection_description

        # Validate container_name
        container_name = params.get("container_name")
        if container_name is None:
            # Use config default
            from config import get_config
            config = get_config()
            validated["container_name"] = config.bronze_container_name
        else:
            if not isinstance(container_name, str):
                raise ValueError("container_name must be a string")
            validated["container_name"] = container_name

        # Validate input_crs (optional)
        input_crs = params.get("input_crs")
        if input_crs is not None:
            if not isinstance(input_crs, str):
                raise ValueError("input_crs must be a string")
            validated["input_crs"] = input_crs
        else:
            validated["input_crs"] = None

        # Validate raster_type
        raster_type = params.get("raster_type", "auto")
        allowed_types = ProcessRasterCollectionWorkflow.parameters_schema["raster_type"]["allowed"]
        if raster_type not in allowed_types:
            raise ValueError(f"raster_type must be one of {allowed_types}")
        validated["raster_type"] = raster_type

        # Validate output_tier
        output_tier = params.get("output_tier", "analysis")
        allowed_tiers = ProcessRasterCollectionWorkflow.parameters_schema["output_tier"]["allowed"]
        if output_tier not in allowed_tiers:
            raise ValueError(f"output_tier must be one of {allowed_tiers}")
        if output_tier == "all":
            raise ValueError("Collections do not support 'all' output tier - choose one tier")
        validated["output_tier"] = output_tier

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

        # Validate create_mosaicjson
        create_mosaicjson = params.get("create_mosaicjson", True)
        if not isinstance(create_mosaicjson, bool):
            raise ValueError("create_mosaicjson must be a boolean")
        validated["create_mosaicjson"] = create_mosaicjson

        # Validate create_stac_collection
        create_stac_collection = params.get("create_stac_collection", True)
        if not isinstance(create_stac_collection, bool):
            raise ValueError("create_stac_collection must be a boolean")
        validated["create_stac_collection"] = create_stac_collection

        # Validate jpeg_quality
        jpeg_quality = params.get("jpeg_quality", 85)
        if not isinstance(jpeg_quality, int) or not (1 <= jpeg_quality <= 100):
            raise ValueError("jpeg_quality must be an integer between 1 and 100")
        validated["jpeg_quality"] = jpeg_quality

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
            job_type="process_raster_collection",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=4,
            stage_results={},
            metadata={
                "description": "Process raster collection to COGs with MosaicJSON",
                "created_by": "ProcessRasterCollectionWorkflow",
                "collection_id": params.get("collection_id"),
                "tile_count": len(params.get("blob_list", [])),
                "container_name": params.get("container_name"),
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

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ProcessRasterCollectionWorkflow.queue_job")

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
            job_type="process_raster_collection",
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
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> list[dict]:
        """
        Create tasks for a specific stage.

        Args:
            stage: Stage number (1-4)
            job_params: Validated job parameters
            job_id: Job ID
            previous_results: Results from previous stage (for fan_out stages)

        Returns:
            List of task definitions (empty list for fan_in stages)

        Raises:
            ValueError: Invalid stage number or missing required data
        """
        if stage == 1:
            return ProcessRasterCollectionWorkflow._create_stage_1_tasks(job_id, job_params)
        elif stage == 2:
            return ProcessRasterCollectionWorkflow._create_stage_2_tasks(job_id, job_params, previous_results)
        elif stage == 3:
            # fan_in - CoreMachine auto-creates task with previous_results
            return []
        elif stage == 4:
            # fan_in - CoreMachine auto-creates task with previous_results
            return []
        else:
            raise ValueError(f"Invalid stage number: {stage}")

    @staticmethod
    def _create_stage_1_tasks(
        job_id: str,
        job_params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Stage 1: Create validation tasks for all tiles (fan-out).

        Args:
            job_id: Job ID
            job_params: Validated job parameters

        Returns:
            List of validate_raster task definitions
        """
        from infrastructure.blob import BlobRepository

        tasks = []
        blob_list = job_params["blob_list"]
        container_name = job_params["container_name"]

        # Get blob repository for SAS token generation
        blob_repo = BlobRepository.instance()

        for i, blob_name in enumerate(blob_list):
            # Generate blob URL with SAS token
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=blob_name,
                hours=1
            )

            task = {
                "task_id": f"{job_id[:8]}-s1-validate-{i}",
                "task_type": "validate_raster",
                "parameters": {
                    "blob_url": blob_url,  # REQUIRED by validate_raster handler
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "input_crs": job_params.get("input_crs"),
                    "raster_type": job_params.get("raster_type", "auto"),
                    "strict_mode": False,
                    "_skip_validation": False
                },
                "metadata": {
                    "tile_index": i,
                    "tile_count": len(blob_list),
                    "blob_name": blob_name,  # Use blob_name instead of tile_name
                    "collection_id": job_params["collection_id"]
                }
            }
            tasks.append(task)

        return tasks

    @staticmethod
    def _create_stage_2_tasks(
        job_id: str,
        job_params: Dict[str, Any],
        previous_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Stage 2: Create COG tasks for all validated tiles (fan-out).

        Args:
            job_id: Job ID
            job_params: Validated job parameters
            previous_results: Validation results from Stage 1

        Returns:
            List of create_cog task definitions

        Raises:
            ValueError: If validation failed for any tiles
        """
        # Check that all validations succeeded
        # Note: previous_results contains task.result_data dicts, not full task records
        failed_validations = [
            r for r in previous_results
            if not r.get("success", False)
        ]
        if failed_validations:
            raise ValueError(
                f"{len(failed_validations)} tiles failed validation. "
                f"Cannot proceed to COG creation."
            )

        from infrastructure.blob import BlobRepository

        tasks = []
        blob_list = job_params["blob_list"]
        container_name = job_params["container_name"]

        # Get blob repository for SAS token generation
        blob_repo = BlobRepository.instance()

        for i, blob_name in enumerate(blob_list):
            # Get validation result for this tile
            # Note: previous_results[i] IS the result_data, not the full task record
            validation_result_data = previous_results[i]
            validation_result = validation_result_data.get("result", {})

            # Extract source CRS from validation (REQUIRED)
            source_crs = validation_result.get("source_crs")
            if not source_crs:
                raise ValueError(f"No source_crs found in validation result for {blob_name}")

            # Extract tile identifier
            tile_name = blob_name.split('/')[-1].replace('.tif', '').replace('.TIF', '')

            # Generate blob URL with SAS token
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=blob_name,
                hours=1
            )

            # Extract raster_type dict and recommended settings from validation
            raster_type_dict = validation_result.get("raster_type", {})
            recommended_compression = validation_result.get("recommended_compression", "DEFLATE")
            recommended_resampling = validation_result.get("recommended_resampling", "bilinear")

            # Determine output blob name
            # If output_folder specified, use it; otherwise mirror input structure
            output_folder = job_params.get("output_folder")
            if output_folder:
                output_blob_name = f"{output_folder}/{tile_name}.tif"
            else:
                # Mirror input folder structure (e.g., namangan/file.tif -> namangan/file.tif)
                folder_path = '/'.join(blob_name.split('/')[:-1])
                output_blob_name = f"{folder_path}/{tile_name}.tif" if folder_path else f"{tile_name}.tif"

            task = {
                "task_id": f"{job_id[:8]}-s2-cog-{i}",
                "task_type": "create_cog",
                "parameters": {
                    "blob_url": blob_url,  # REQUIRED by create_cog handler
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "source_crs": source_crs,  # REQUIRED by create_cog handler
                    "target_crs": "EPSG:4326",
                    "raster_type": raster_type_dict,  # Pass full raster_type dict from validation
                    "output_blob_name": output_blob_name,  # REQUIRED by create_cog handler
                    "output_tier": job_params.get("output_tier", "analysis"),
                    "output_folder": job_params.get("output_folder"),
                    "compression": recommended_compression,
                    "jpeg_quality": job_params.get("jpeg_quality", 85),
                    "overview_resampling": recommended_resampling,
                    "reproject_resampling": recommended_resampling
                },
                "metadata": {
                    "tile_index": i,
                    "tile_count": len(blob_list),
                    "tile_name": tile_name,
                    "collection_id": job_params["collection_id"],
                    "validation_result": validation_result
                }
            }
            tasks.append(task)

        return tasks
