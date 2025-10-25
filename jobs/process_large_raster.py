# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - PROCESS LARGE RASTER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job workflow - Large raster tiling and processing (1-30 GB)
# PURPOSE: 4-stage workflow for tiling large rasters into COG mosaics
# LAST_REVIEWED: 24 OCT 2025
# EXPORTS: ProcessLargeRasterWorkflow class
# INTERFACES: JobBase contract - create_tasks_for_stage() signature
# PYDANTIC_MODELS: None (class attributes)
# DEPENDENCIES: core.models.enums.TaskStatus, services.tiling_scheme, services.tiling_extraction
# SOURCE: Bronze container large rasters (1-30 GB)
# SCOPE: Large file raster processing pipeline with tiling
# VALIDATION: All stages validate inputs
# PATTERNS: CoreMachine compliance, fan-out/fan-in architecture
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS
# INDEX: ProcessLargeRasterWorkflow:60, create_tasks_for_stage:200
# ============================================================================

"""
Process Large Raster Workflow - Tiling Pipeline (1-30 GB)

Four-stage workflow for converting large rasters to tiled COG mosaics:

Stage 1: Generate Tiling Scheme (Fan-in preparation)
- Single task analyzes source raster
- Generates GeoJSON tiling scheme in EPSG:4326 output space
- Defines tile grid (e.g., 17×12 = 204 tiles for 11 GB raster)
- Uploads tiling scheme to blob storage

Stage 2: Extract Tiles Sequentially (Long-running task)
- SINGLE long-running task extracts ALL tiles
- Sequential I/O is MUCH faster than parallel random access
- Reports progress via task metadata
- Uploads raw tiles to blob storage (in source CRS)
- 3-4 minutes for 204 tiles from 11 GB raster

Stage 3: Convert Tiles to COGs (Fan-out)
- Parallel COG creation for all tiles (N tasks)
- Each task: WarpedVRT reprojection + COG optimization
- Uploads to silver container
- 5-6 minutes for 204 tiles in parallel

Stage 4: Create MosaicJSON + STAC (Fan-in)
- Single task aggregates all COG paths
- Generates MosaicJSON with quadkey indexing
- Calculates global statistics for consistent rendering
- Creates STAC Item with raster:bands extension
- Uploads MosaicJSON + STAC to blob storage

Key Architecture Decisions:
- Stage 1: Tiles defined in EPSG:4326 output space (no seams)
- Stage 2: Sequential extraction (10x faster than parallel)
- Stage 3: Parallel COG conversion (Azure Functions fan-out)
- Stage 4: Pre-computed statistics (enables TiTiler stretching)

Author: Robert and Geospatial Claude Legion
Date: 24 OCT 2025
"""

from typing import List, Dict, Any
import hashlib
import json

from jobs.base import JobBase


class ProcessLargeRasterWorkflow(JobBase):
    """
    Large raster tiling workflow (1-30 GB files).

    Stages:
    1. Generate Tiling Scheme: Single task creates tile grid
    2. Extract Tiles: Single long-running task extracts all tiles
    3. Convert to COGs: Parallel COG creation (N tasks)
    4. Create MosaicJSON + STAC: Single task aggregates outputs
    """

    job_type: str = "process_large_raster"
    description: str = "Process large raster (1-30 GB) to tiled COG mosaic"

    stages: List[Dict[str, Any]] = [
        {
            "number": 1,
            "name": "generate_tiling_scheme",
            "task_type": "generate_tiling_scheme",
            "description": "Generate GeoJSON tiling scheme in EPSG:4326 output space",
            "parallelism": "single"
        },
        {
            "number": 2,
            "name": "extract_tiles",
            "task_type": "extract_tiles",
            "description": "Sequential extraction of all tiles (long-running task)",
            "parallelism": "single"
        },
        {
            "number": 3,
            "name": "convert_to_cogs",
            "task_type": "create_cog",
            "description": "Parallel COG creation with reprojection (N tasks)",
            "parallelism": "fan_out"
        },
        {
            "number": 4,
            "name": "create_mosaicjson",
            "task_type": "create_mosaicjson_with_stats",
            "description": "Generate MosaicJSON + STAC with statistics",
            "parallelism": "fan_in"
        }
    ]

    parameters_schema: Dict[str, Any] = {
        "blob_name": {
            "type": "str",
            "required": True,
            "description": "Blob path for large raster (1-30 GB)"
        },
        "container_name": {
            "type": "str",
            "required": True,
            "default": None,
            "description": "Source container name (uses config.bronze_container_name if None)"
        },
        "tile_size": {
            "type": "int",
            "required": False,
            "default": 5000,
            "description": "Tile size in pixels (default: 5000)"
        },
        "overlap": {
            "type": "int",
            "required": False,
            "default": 512,
            "description": "Overlap in pixels (default: 512, matches COG blocksize)"
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
            "description": "COG output tier for all tiles"
        },
        "output_folder": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Override output folder path (e.g., 'cogs/antigua/'). If None, mirrors input folder structure."
        },
        "jpeg_quality": {
            "type": "int",
            "required": False,
            "default": 85,
            "description": "JPEG quality (1-100) for visualization tier"
        },
        "band_names": {
            "type": "list",
            "required": False,
            "default": ["Red", "Green", "Blue"],
            "description": "Band names for STAC raster:bands extension"
        },
        "overview_level": {
            "type": "int",
            "required": False,
            "default": 2,
            "description": "Overview level for statistics calculation (0=full res, 2=1/4 res)"
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

        # Validate blob_name (required)
        if "blob_name" not in params:
            raise ValueError("blob_name is required")

        blob_name = params["blob_name"]
        if not isinstance(blob_name, str) or not blob_name.strip():
            raise ValueError("blob_name must be a non-empty string")

        validated["blob_name"] = blob_name.strip()

        # Validate container_name (optional)
        container_name = params.get("container_name")
        if container_name:
            if not isinstance(container_name, str) or not container_name.strip():
                raise ValueError("container_name must be a non-empty string")
            validated["container_name"] = container_name.strip()
        else:
            validated["container_name"] = None  # Will use config default

        # Validate tile_size
        tile_size = params.get("tile_size", 5000)
        if not isinstance(tile_size, int) or tile_size <= 0:
            raise ValueError("tile_size must be a positive integer")
        validated["tile_size"] = tile_size

        # Validate overlap
        overlap = params.get("overlap", 512)
        if not isinstance(overlap, int) or overlap < 0:
            raise ValueError("overlap must be a non-negative integer")
        if overlap >= tile_size:
            raise ValueError(f"overlap ({overlap}) must be less than tile_size ({tile_size})")
        validated["overlap"] = overlap

        # Validate raster_type
        raster_type = params.get("raster_type", "auto")
        allowed_types = ["auto", "rgb", "rgba", "dem", "categorical", "multispectral", "nir"]
        if raster_type not in allowed_types:
            raise ValueError(f"raster_type must be one of {allowed_types}")
        validated["raster_type"] = raster_type

        # Validate output_tier
        output_tier = params.get("output_tier", "analysis")
        allowed_tiers = ["visualization", "analysis", "archive"]
        if output_tier not in allowed_tiers:
            raise ValueError(f"output_tier must be one of {allowed_tiers}")
        validated["output_tier"] = output_tier

        # Validate output_folder (optional)
        output_folder = params.get("output_folder")
        if output_folder:
            if not isinstance(output_folder, str):
                raise ValueError("output_folder must be a string")
            validated["output_folder"] = output_folder.strip()
        else:
            validated["output_folder"] = None

        # Validate jpeg_quality
        jpeg_quality = params.get("jpeg_quality", 85)
        if not isinstance(jpeg_quality, int) or not (1 <= jpeg_quality <= 100):
            raise ValueError("jpeg_quality must be an integer between 1 and 100")
        validated["jpeg_quality"] = jpeg_quality

        # Validate band_names
        band_names = params.get("band_names", ["Red", "Green", "Blue"])
        if not isinstance(band_names, list):
            raise ValueError("band_names must be a list")
        if not all(isinstance(name, str) for name in band_names):
            raise ValueError("all band_names must be strings")
        validated["band_names"] = band_names

        # Validate overview_level
        overview_level = params.get("overview_level", 2)
        if not isinstance(overview_level, int) or overview_level < 0:
            raise ValueError("overview_level must be a non-negative integer")
        validated["overview_level"] = overview_level

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
            job_type="process_large_raster",
            parameters=params,
            status=JobStatus.QUEUED,
            stage=1,
            total_stages=4,
            stage_results={},
            metadata={
                "description": "Large raster tiling workflow (1-30 GB)",
                "created_by": "ProcessLargeRasterWorkflow"
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
        Queue job to Service Bus for async processing.

        Args:
            job_id: Job ID
            params: Job parameters

        Returns:
            Queue operation result
        """
        from infrastructure.service_bus import ServiceBusRepository
        from core.schema.queue import JobQueueMessage
        from config import get_config
        import uuid

        config = get_config()
        service_bus = ServiceBusRepository()

        # Create JobQueueMessage Pydantic model
        job_message = JobQueueMessage(
            job_id=job_id,
            job_type="process_large_raster",
            stage=1,
            parameters=params,
            correlation_id=str(uuid.uuid4())[:8]
        )

        # Send message to Service Bus
        message_id = service_bus.send_message(
            queue_name=config.service_bus_jobs_queue,
            message=job_message
        )

        return {
            "job_id": job_id,
            "status": "queued",
            "queue": config.service_bus_jobs_queue,
            "message_id": message_id
        }

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: dict,
        job_id: str,
        previous_results: list = None
    ) -> List[dict]:
        """
        Create tasks for each stage.

        Stage 1: Single task to generate tiling scheme
        Stage 2: Single task to extract all tiles sequentially
        Stage 3: N tasks for parallel COG conversion (one per tile)
        Stage 4: Single task to create MosaicJSON + STAC

        Args:
            stage: Current stage (1-4)
            job_params: Job parameters
            job_id: Job ID for task generation
            previous_results: Results from previous stage

        Returns:
            List of task parameter dicts
        """
        from config import get_config

        config = get_config()

        if stage == 1:
            # Stage 1: Generate Tiling Scheme
            # Single task analyzes source raster and creates GeoJSON tiling scheme

            container_name = job_params["container_name"] or config.bronze_container_name

            return [{
                "task_id": f"{job_id[:8]}-s1-generate-tiling-scheme",
                "task_type": "generate_tiling_scheme",
                "parameters": {
                    "container_name": container_name,
                    "blob_name": job_params["blob_name"],
                    "tile_size": job_params.get("tile_size", 5000),
                    "overlap": job_params.get("overlap", 512),
                    "output_container": config.silver_container_name
                }
            }]

        elif stage == 2:
            # Stage 2: Extract Tiles Sequentially
            # Single long-running task extracts all tiles

            # Get tiling scheme from Stage 1 results
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 1 failed - no tiling scheme generated")

            stage1_result = previous_results[0]["result"]
            tiling_scheme_blob = stage1_result["tiling_scheme_blob"]

            container_name = job_params["container_name"] or config.bronze_container_name

            return [{
                "task_id": f"{job_id[:8]}-s2-extract-tiles",
                "task_type": "extract_tiles",
                "parameters": {
                    "container_name": container_name,
                    "blob_name": job_params["blob_name"],
                    "tiling_scheme_blob": tiling_scheme_blob,
                    "tiling_scheme_container": config.silver_container_name,
                    "output_container": config.silver_container_name
                }
            }]

        elif stage == 3:
            # Stage 3: Convert Tiles to COGs (Parallel)
            # Create N tasks (one per tile) for parallel COG conversion

            # Get tile list from Stage 2 results
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 2 failed - no tiles extracted")

            stage2_result = previous_results[0]["result"]
            tile_blobs = stage2_result["tile_blobs"]
            source_crs = stage2_result["source_crs"]

            # Get raster metadata passed through from Stage 1 via Stage 2
            raster_metadata = stage2_result.get("raster_metadata", {})

            # Build raster_type dict following process_raster pattern
            # Uses metadata extracted by tiling_scheme.py in Stage 1
            raster_type = {
                "detected_type": raster_metadata.get("detected_type", "unknown"),
                "band_count": raster_metadata.get("band_count", 3),
                "data_type": raster_metadata.get("data_type", "uint8"),
                "optimal_cog_settings": {}
            }

            logger.info(f"Stage 3: Creating {len(tile_blobs)} COG conversion tasks")
            logger.info(f"Raster metadata: {raster_type}")

            # Create task for each tile
            tasks = []
            for idx, tile_blob in enumerate(tile_blobs):
                # Extract tile identifier from blob path for readable task IDs
                # e.g., "antigua/tiles/tile_x5_y10.tif" → "x5_y10"
                tile_id = tile_blob.split('/')[-1].replace('tile_', '').replace('.tif', '')

                tasks.append({
                    "task_id": f"{job_id[:8]}-s3-cog-{tile_id}",
                    "task_type": "create_cog",
                    "parameters": {
                        "container_name": config.silver_container_name,
                        "blob_name": tile_blob,
                        "source_crs": source_crs,
                        "target_crs": "EPSG:4326",
                        "raster_type": raster_type,
                        "output_tier": job_params.get("output_tier", "analysis"),
                        "output_blob_name": tile_blob.replace("/tiles/", "/cogs/").replace(".tif", "_cog.tif"),
                        "jpeg_quality": job_params.get("jpeg_quality", 85)
                    }
                })

            return tasks

        elif stage == 4:
            # Stage 4: Create MosaicJSON + STAC
            # Single task aggregates all COG paths and creates outputs

            # Get COG list from Stage 3 results
            successful_cogs = [
                r["result"]["cog_blob"]
                for r in previous_results
                if r.get("success")
            ]

            if not successful_cogs:
                raise ValueError("Stage 3 failed - no COGs created")

            # Get bounds from first COG result
            first_cog_result = next(r["result"] for r in previous_results if r.get("success"))
            bounds = first_cog_result.get("bounds_4326")

            return [{
                "task_id": f"{job_id[:8]}-s4-create-mosaicjson",
                "task_type": "create_mosaicjson_with_stats",
                "parameters": {
                    "cog_blobs": successful_cogs,
                    "container_name": config.silver_container_name,
                    "job_id": job_id,
                    "bounds": bounds,
                    "band_names": job_params.get("band_names", ["Red", "Green", "Blue"]),
                    "overview_level": job_params.get("overview_level", 2),
                    "output_container": config.silver_container_name
                }
            }]

        else:
            raise ValueError(f"Invalid stage: {stage}")
