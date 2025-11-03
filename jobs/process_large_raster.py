# ============================================================================
# CLAUDE CONTEXT - JOB WORKFLOW - PROCESS LARGE RASTER
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Job workflow - Large raster tiling and processing (1-30 GB)
# PURPOSE: 4-stage workflow for tiling large rasters into COG mosaics
# LAST_REVIEWED: 27 OCT 2025
# EXPORTS: ProcessLargeRasterWorkflow class
# INTERFACES: JobBase contract - create_tasks_for_stage() signature
# PYDANTIC_MODELS: None (class attributes)
# DEPENDENCIES: core.models.enums.TaskStatus, services.tiling_scheme, services.tiling_extraction
# SOURCE: Bronze container large rasters (1-30 GB)
# SCOPE: Large file raster processing pipeline with tiling
# VALIDATION: All stages validate inputs
# PATTERNS: CoreMachine compliance, fan-out/fan-in, job-scoped intermediate storage
# ENTRY_POINTS: Registered in jobs/__init__.py ALL_JOBS
# INDEX: ProcessLargeRasterWorkflow:60, create_tasks_for_stage:200
# STORAGE: Intermediate tiles in job-scoped folders ({job_id[:8]}/tiles/)
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
- Uploads raw tiles to job-scoped blob storage folder (in source CRS)
  Format: {job_id[:8]}/tiles/{blob_stem}_tile_0_0.tif
  Example: 598fc149/tiles/17apr2024wv2_tile_0_0.tif
- 3-4 minutes for 204 tiles from 11 GB raster

Stage 3: Convert Tiles to COGs (Fan-out)
- Parallel COG creation for all tiles (N tasks)
- Reads from intermediate job-scoped folder: {job_id[:8]}/tiles/
- Each task: WarpedVRT reprojection + COG optimization
- Uploads to permanent COG storage in silver container
  Format: cogs/{blob_stem}/{blob_stem}_tile_0_0_cog.tif
  Example: cogs/17apr2024wv2/17apr2024wv2_tile_0_0_cog.tif
- 5-6 minutes for 204 tiles in parallel

Stage 4: Create MosaicJSON + STAC (Fan-in)
- Single task aggregates all COG paths
- Generates MosaicJSON with quadkey indexing
- Calculates global statistics for consistent rendering
- Creates STAC Item with raster:bands extension
- Uploads MosaicJSON + STAC to blob storage

Key Architecture Decisions:
- Stage 1: Tiles defined in EPSG:4326 output space (no seams)
- Stage 2: Sequential extraction (10x faster than parallel), job-scoped folders
- Stage 3: Parallel COG conversion (Azure Functions fan-out), permanent storage
- Stage 4: Pre-computed statistics (enables TiTiler stretching)

Storage Cleanup:
- Intermediate tiles ({job_id[:8]}/tiles/) cleaned by SEPARATE timer trigger
- NOT part of ETL workflow stages
- Allows debugging of failed jobs (artifacts retained)

Author: Robert and Geospatial Claude Legion
Date: 27 OCT 2025
"""

from typing import List, Dict, Any
from pathlib import Path
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
    description: str = "Process large raster (1-30 GB) to tiled COG mosaic with STAC"

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
            "task_type": "create_mosaicjson",
            "description": "Generate MosaicJSON with quadkey index and spatial statistics",
            "parallelism": "fan_in"
        },
        {
            "number": 5,
            "name": "create_stac",
            "task_type": "create_stac_collection",
            "description": "Create STAC collection with MosaicJSON asset (ready for TiTiler-pgstac)",
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
            "description": "Source container name (uses config.storage.bronze.get_container('rasters') if None)"
        },
        "tile_size": {
            "type": "int",
            "required": False,
            "default": None,
            "description": "Tile size in pixels (None = auto-calculate based on band count + bit depth, default: None)"
        },
        "overlap": {
            "type": "int",
            "required": False,
            "default": 512,
            "description": "Overlap in pixels (default: 512, matches COG blocksize) - CRITICAL: Must be 512 for production to align with COG internal tiles"
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
            "description": "Optional output folder path (e.g., 'cogs/antigua/'). If None, writes to container root."
        },
        "jpeg_quality": {
            "type": "int",
            "required": False,
            "default": 85,
            "description": "JPEG quality (1-100) for visualization tier"
        },
        "compression": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Compression method override (deprecated - use output_tier instead). If None, uses tier default."
        },
        "overview_resampling": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Resampling method for overviews (e.g., 'cubic', 'bilinear', 'nearest'). If None, auto-selected based on raster type."
        },
        "reproject_resampling": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Resampling method for reprojection (e.g., 'cubic', 'bilinear', 'nearest'). If None, auto-selected based on raster type."
        },
        "band_names": {
            "type": "dict",
            "required": False,
            "default": {"5": "Red", "3": "Green", "2": "Blue"},
            "description": "Band index → name mapping (1-based indexing), e.g., {'5': 'Red', '3': 'Green', '2': 'Blue'} for WorldView-2 RGB"
        },
        "collection_id": {
            "type": "str",
            "required": False,
            "default": "system-rasters",
            "description": "STAC collection ID for metadata (default: system-rasters for operational tracking)"
        },
        "stac_item_id": {
            "type": "str",
            "required": False,
            "default": None,
            "description": "Custom STAC collection item ID (default: auto-generated from blob name and collection)"
        },
        "overview_level": {
            "type": "int",
            "required": False,
            "default": 2,
            "description": "Overview level for statistics calculation (0=full res, 2=1/4 res)"
        },
        "target_crs": {
            "type": "str",
            "required": False,
            "default": "EPSG:4326",
            "description": "Target CRS for output COGs and tiling scheme (default: EPSG:4326). Common: EPSG:3857 (Web Mercator), EPSG:4326 (WGS84)"
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

        # Validate tile_size (None = auto-calculate)
        tile_size = params.get("tile_size", None)
        if tile_size is not None and (not isinstance(tile_size, int) or tile_size <= 0):
            raise ValueError("tile_size must be a positive integer or None (auto-calculate)")
        validated["tile_size"] = tile_size

        # Validate overlap
        overlap = params.get("overlap", 512)
        if not isinstance(overlap, int) or overlap < 0:
            raise ValueError("overlap must be a non-negative integer")
        if tile_size is not None and overlap >= tile_size:
            raise ValueError(f"overlap ({overlap}) must be less than tile_size ({tile_size})")
        # NOTE: overlap != 512 is FOR TESTING ONLY - production must use 512 to match COG blocksize
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

        # Validate compression (optional override)
        compression = params.get("compression")
        if compression is not None:
            if not isinstance(compression, str) or not compression.strip():
                raise ValueError("compression must be a non-empty string or None")
            validated["compression"] = compression.strip()
        else:
            validated["compression"] = None

        # Validate overview_resampling (optional override)
        overview_resampling = params.get("overview_resampling")
        if overview_resampling is not None:
            if not isinstance(overview_resampling, str) or not overview_resampling.strip():
                raise ValueError("overview_resampling must be a non-empty string or None")
            validated["overview_resampling"] = overview_resampling.strip()
        else:
            validated["overview_resampling"] = None

        # Validate reproject_resampling (optional override)
        reproject_resampling = params.get("reproject_resampling")
        if reproject_resampling is not None:
            if not isinstance(reproject_resampling, str) or not reproject_resampling.strip():
                raise ValueError("reproject_resampling must be a non-empty string or None")
            validated["reproject_resampling"] = reproject_resampling.strip()
        else:
            validated["reproject_resampling"] = None

        # Validate band_names (dict mapping band index → name)
        # Use Pydantic model for automatic JSON string key → int conversion
        from models.band_mapping import BandNames
        from pydantic import ValidationError

        band_names_raw = params.get("band_names", {"5": "Red", "3": "Green", "2": "Blue"})  # WorldView-2 RGB default

        try:
            band_names_model = BandNames(mapping=band_names_raw)
            validated["band_names"] = band_names_model.mapping  # dict[int, str]
        except ValidationError as e:
            # Extract first error message for cleaner user feedback
            error_msg = e.errors()[0]['msg'] if e.errors() else str(e)
            raise ValueError(f"Invalid band_names: {error_msg}")

        # Validate overview_level
        overview_level = params.get("overview_level", 2)
        if not isinstance(overview_level, int) or overview_level < 0:
            raise ValueError("overview_level must be a non-negative integer")
        validated["overview_level"] = overview_level

        # Validate collection_id (optional)
        collection_id = params.get("collection_id", "system-rasters")
        if not isinstance(collection_id, str) or not collection_id.strip():
            raise ValueError("collection_id must be a non-empty string")
        validated["collection_id"] = collection_id.strip()

        # Validate stac_item_id (optional)
        stac_item_id = params.get("stac_item_id")
        if stac_item_id is not None:
            if not isinstance(stac_item_id, str) or not stac_item_id.strip():
                raise ValueError("stac_item_id must be a non-empty string")
            validated["stac_item_id"] = stac_item_id.strip()

        # Validate target_crs (optional)
        target_crs = params.get("target_crs", "EPSG:4326")
        if not isinstance(target_crs, str) or not target_crs.strip():
            raise ValueError("target_crs must be a non-empty string")
        validated["target_crs"] = target_crs.strip()

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
            total_stages=5,
            stage_results={},
            metadata={
                "description": "Large raster tiling workflow with STAC (1-30 GB)",
                "created_by": "ProcessLargeRasterWorkflow",
                "blob_name": params.get("blob_name"),
                "container_name": params.get("container_name"),
                "output_folder": params.get("output_folder"),
                "collection_id": params.get("collection_id", "system-rasters"),
                "stac_item_id": params.get("stac_item_id")
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

            container_name = job_params["container_name"] or config.storage.bronze.get_container('rasters')

            return [{
                "task_id": f"{job_id[:8]}-s1-generate-tiling-scheme",
                "task_type": "generate_tiling_scheme",
                "parameters": {
                    "container_name": container_name,
                    "blob_name": job_params["blob_name"],
                    "tile_size": job_params.get("tile_size"),  # None = auto-calculate
                    "overlap": job_params.get("overlap", 512),
                    "output_container": config.storage.silver.get_container('tiles'),
                    "band_names": job_params.get("band_names", {5: "Red", 3: "Green", 2: "Blue"}),  # For tile size calculation
                    "target_crs": job_params.get("target_crs", "EPSG:4326")  # Tiling scheme calculated in target CRS
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

            container_name = job_params["container_name"] or config.storage.bronze.get_container('rasters')

            return [{
                "task_id": f"{job_id[:8]}-s2-extract-tiles",
                "task_type": "extract_tiles",
                "parameters": {
                    "container_name": container_name,
                    "blob_name": job_params["blob_name"],
                    "tiling_scheme_blob": tiling_scheme_blob,
                    "tiling_scheme_container": config.storage.silver.get_container('tiles'),
                    "output_container": config.resolved_intermediate_tiles_container,  # Use config for intermediate tiles
                    "job_id": job_id,  # Pass job_id for folder naming ({job_id[:8]}/tiles/)
                    "band_names": job_params.get("band_names", {5: "Red", 3: "Green", 2: "Blue"})  # Pass band selection for efficient reading
                }
            }]

        elif stage == 3:
            # Stage 3: Convert Tiles to COGs (Parallel)
            # Create N tasks (one per tile) for parallel COG conversion

            # DEBUG: Log previous_results structure
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"🔍 [STAGE3_DEBUG] Creating Stage 3 tasks for job {job_id[:16]}...")
            logger.info(f"🔍 [STAGE3_DEBUG] previous_results type: {type(previous_results)}")
            logger.info(f"🔍 [STAGE3_DEBUG] previous_results length: {len(previous_results) if previous_results else 0}")

            if previous_results and len(previous_results) > 0:
                logger.info(f"🔍 [STAGE3_DEBUG] previous_results[0] keys: {previous_results[0].keys()}")
                logger.info(f"🔍 [STAGE3_DEBUG] previous_results[0]['success']: {previous_results[0].get('success')}")
                if "result" in previous_results[0]:
                    logger.info(f"🔍 [STAGE3_DEBUG] previous_results[0]['result'] keys: {previous_results[0]['result'].keys()}")
                    result = previous_results[0]['result']
                    if "tile_blobs" in result:
                        logger.info(f"🔍 [STAGE3_DEBUG] tile_blobs count: {len(result['tile_blobs'])}")
                        logger.info(f"🔍 [STAGE3_DEBUG] First 3 tile_blobs: {result['tile_blobs'][:3]}")

            # Get tile list from Stage 2 results
            if not previous_results or not previous_results[0].get("success"):
                error_msg = f"Stage 2 failed - no tiles extracted. previous_results: {previous_results}"
                logger.error(f"❌ [STAGE3_DEBUG] {error_msg}")
                raise ValueError(error_msg)

            stage2_result = previous_results[0]["result"]

            # Validate stage2_result has required fields
            if "tile_blobs" not in stage2_result:
                error_msg = f"Stage 2 result missing 'tile_blobs' field. Keys: {stage2_result.keys()}"
                logger.error(f"❌ [STAGE3_DEBUG] {error_msg}")
                raise ValueError(error_msg)

            if "source_crs" not in stage2_result:
                error_msg = f"Stage 2 result missing 'source_crs' field. Keys: {stage2_result.keys()}"
                logger.error(f"❌ [STAGE3_DEBUG] {error_msg}")
                raise ValueError(error_msg)

            tile_blobs = stage2_result["tile_blobs"]
            source_crs = stage2_result["source_crs"]

            logger.info(f"✅ [STAGE3_DEBUG] Stage 2 validation passed - {len(tile_blobs)} tiles, CRS: {source_crs}")

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

            # Stage 3: Creating N COG conversion tasks (one per tile)

            # Extract blob_stem for path generation
            blob_stem = Path(job_params['blob_name']).stem

            # Determine output folder
            output_folder = job_params.get("output_folder")

            # Create task for each tile
            tasks = []
            for idx, tile_blob in enumerate(tile_blobs):
                # Extract tile identifier from blob path for readable task IDs
                # New pattern: "598fc149/tiles/17apr2024wv2_tile_0_0.tif" → "0_0"
                tile_filename = tile_blob.split('/')[-1]  # e.g., "17apr2024wv2_tile_0_0.tif"
                # Remove blob_stem prefix and "tile_" to get grid coordinates
                tile_id = tile_filename.replace(f"{blob_stem}_tile_", "").replace(".tif", "")

                # Generate output filename with _cog suffix
                output_filename = tile_filename.replace('.tif', '_cog.tif')

                # Build output path - respect output_folder or write to root
                if output_folder:
                    # User specified folder (e.g., "cogs/antigua")
                    output_blob_name = f"{output_folder}/{output_filename}"
                else:
                    # Default: write to container root (flat structure)
                    output_blob_name = output_filename

                tasks.append({
                    "task_id": f"{job_id[:8]}-s3-cog-{tile_id}",
                    "task_type": "create_cog",
                    "parameters": {
                        "container_name": config.resolved_intermediate_tiles_container,  # Read from intermediate tiles container
                        "blob_name": tile_blob,
                        "source_crs": source_crs,
                        "target_crs": job_params.get("target_crs", "EPSG:4326"),
                        "raster_type": raster_type,
                        "output_tier": job_params.get("output_tier", "analysis"),
                        "output_blob_name": output_blob_name,
                        "jpeg_quality": job_params.get("jpeg_quality", 85),
                        "compression": job_params.get("compression"),  # User override or None
                        "overview_resampling": job_params.get("overview_resampling"),  # User override or None
                        "reproject_resampling": job_params.get("reproject_resampling"),  # User override or None
                    }
                })

            return tasks

        elif stage == 4:
            # Stage 4: Create MosaicJSON
            # Single task aggregates all COG paths and creates MosaicJSON index

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

            # Extract collection_id from blob_name (e.g., "17apr2024wv2.tif" → "17apr2024wv2")
            blob_name = job_params.get("blob_name", "")
            collection_id = Path(blob_name).stem if blob_name else "unknown"

            return [{
                "task_id": f"{job_id[:8]}-s4-create-mosaicjson",
                "task_type": "create_mosaicjson",
                "parameters": {
                    "cog_blobs": successful_cogs,
                    "container_name": config.storage.silver.get_container('cogs'),
                    "job_id": job_id,
                    "bounds": bounds,
                    "band_names": job_params.get("band_names", {5: "Red", 3: "Green", 2: "Blue"}),  # dict[int, str] format
                    "overview_level": job_params.get("overview_level", 2),
                    "output_container": config.storage.silver.get_container('mosaicjson'),
                    "collection_id": collection_id,
                    "output_folder": None  # Flat namespace - write to container root
                }
            }]

        elif stage == 5:
            # Stage 5: Create STAC collection
            # fan_in - CoreMachine auto-creates task with previous_results from Stage 4
            return []

        else:
            raise ValueError(f"Invalid stage: {stage}. ProcessLargeRasterWorkflow has 5 stages.")

    @staticmethod
    def finalize_job(context=None) -> Dict[str, Any]:
        """
        Create final job summary from all completed tasks.

        TODO (3 NOV 2025): Implement rich pattern to extract:
        - MosaicJSON location and metadata (Stage 4 results)
        - STAC collection ID and item count (Stage 5 results)
        - Total COG count and size (Stage 3 results)
        - Tiling statistics (Stage 2 results)

        Reference: jobs/process_raster.py lines 573-650 for rich pattern example

        Args:
            context: JobExecutionContext with task results

        Returns:
            Job summary dict
        """
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "ProcessLargeRasterWorkflow.finalize_job")

        # Minimal implementation for now
        if context:
            logger.info(f"✅ Job {context.job_id} completed with {len(context.task_results)} tasks")
        else:
            logger.info("✅ ProcessLargeRaster job completed")

        return {
            "job_type": "process_large_raster",
            "status": "completed"
        }
