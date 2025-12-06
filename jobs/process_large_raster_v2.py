# ============================================================================
# CLAUDE CONTEXT - PROCESS LARGE RASTER V2 (MIXIN PATTERN)
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: New job - Clean slate JobBaseMixin implementation (30 NOV 2025)
# PURPOSE: Large raster tiling pipeline (1-30 GB files) → tiled COG mosaic + STAC
# LAST_REVIEWED: 30 NOV 2025
# EXPORTS: ProcessLargeRasterV2Job
# INTERFACES: JobBase, JobBaseMixin, RasterMixin, RasterWorkflowsBase
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base, jobs.mixins, jobs.raster_mixin, jobs.raster_workflows_base
# SOURCE: User job submission via /api/jobs/submit/process_large_raster_v2
# SCOPE: Large file raster ETL pipeline with tiling
# VALIDATION: JobBaseMixin declarative schema + resource validators (blob_exists_with_size)
# PATTERNS: Mixin pattern (75% less boilerplate), Sequential→Fan-out→Fan-in architecture
# ENTRY_POINTS: from jobs import ALL_JOBS; ALL_JOBS["process_large_raster_v2"]
# INDEX: ProcessLargeRasterV2Job:50, create_tasks_for_stage:115, finalize_job:230
# ============================================================================

"""
Process Large Raster V2 - Clean Slate JobBaseMixin Implementation

Uses JobBaseMixin + RasterMixin pattern for 75% less boilerplate code:
- validate_job_parameters: Declarative via parameters_schema + resource_validators
- generate_job_id: Automatic SHA256 from params
- create_job_record: Automatic via mixin
- queue_job: Automatic via mixin

Five-stage workflow:
1. Generate Tiling Scheme (Single): Calculate tile grid in output CRS
2. Extract Tiles (Single): Sequential extraction (10x faster than parallel)
3. Create COGs (Fan-out): Parallel COG creation for all tiles
4. Create MosaicJSON (Fan-in): Aggregate into virtual mosaic
5. Create STAC Collection (Fan-in): Collection-level STAC item

Key improvements:
    - Clean slate parameters (no deprecated fields)
    - Preflight validation with blob_exists_with_size
    - Size range enforcement (min 100MB, max 30GB)
    - Reduced boilerplate via mixin pattern
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from jobs.raster_workflows_base import RasterWorkflowsBase
from jobs.raster_mixin import RasterMixin
from config.defaults import STACDefaults


class ProcessLargeRasterV2Job(RasterMixin, RasterWorkflowsBase, JobBaseMixin, JobBase):
    """
    Large raster tiling workflow (1-30 GB files) using JobBaseMixin.
    Clean slate implementation - no deprecated parameters.

    Five-stage workflow:
    1. generate_tiling_scheme: Calculate tile grid (single)
    2. extract_tiles: Sequential tile extraction (single, long-running)
    3. create_cogs: Parallel COG creation (fan-out)
    4. create_mosaicjson: Aggregate into MosaicJSON (fan-in)
    5. create_stac: Create STAC collection (fan-in)

    Preflight Validation:
    - Blob exists with size check (min 100MB, max 30GB)
    - Files smaller than 100MB should use process_raster_v2
    """

    job_type = "process_large_raster_v2"
    description = "Process large raster (1-30 GB) to tiled COG mosaic with STAC (v2 mixin pattern)"

    stages = [
        {"number": 1, "name": "generate_tiling_scheme", "task_type": "generate_tiling_scheme", "parallelism": "single"},
        {"number": 2, "name": "extract_tiles", "task_type": "extract_tiles", "parallelism": "single"},
        {"number": 3, "name": "create_cogs", "task_type": "create_cog", "parallelism": "fan_out"},
        {"number": 4, "name": "create_mosaicjson", "task_type": "create_mosaicjson", "parallelism": "fan_in"},
        {"number": 5, "name": "create_stac", "task_type": "create_stac_collection", "parallelism": "fan_in"}
    ]

    # Compose parameters schema from RasterMixin shared schemas
    parameters_schema = {
        # Shared raster parameters
        **RasterMixin.COMMON_RASTER_SCHEMA,
        **RasterMixin.MOSAICJSON_SCHEMA,
        **RasterMixin.PLATFORM_PASSTHROUGH_SCHEMA,

        # Large raster required parameters
        'blob_name': {'type': 'str', 'required': True},

        # Override collection_id to not be required (has default)
        'collection_id': {'type': 'str', 'default': STACDefaults.RASTER_COLLECTION},

        # Tiling-specific parameters
        'tile_size': {'type': 'int', 'default': None},  # None = auto-calculate
        'overlap': {'type': 'int', 'default': 512, 'min': 0},
        'band_names': {'type': 'dict', 'default': None},  # e.g., {"5": "Red", "3": "Green", "2": "Blue"}
        'overview_level': {'type': 'int', 'default': 2, 'min': 0},
    }

    # Preflight resource validators
    # Uses blob_exists_with_size to validate file exists and is in acceptable size range
    resource_validators = [
        {
            'type': 'blob_exists_with_size',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'min_size_mb': 100,  # Minimum size for large raster pipeline
            'max_size_mb': 30000,  # 30 GB maximum
            'error_not_found': 'Source raster file does not exist. Verify blob_name and container_name.',
            'error_too_small': 'File too small for large raster pipeline (< 100MB). Use process_raster_v2 instead.',
            'error_too_large': 'Raster file exceeds 30GB limit.'
        }
    ]

    @staticmethod
    def create_tasks_for_stage(
        stage: int,
        job_params: Dict[str, Any],
        job_id: str,
        previous_results: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Generate tasks for each stage."""
        from config import get_config
        from util_logger import LoggerFactory, ComponentType

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "process_large_raster_v2")
        config = get_config()

        if stage == 1:
            # Stage 1: Generate tiling scheme (single task)
            # Auto-detection happens in tiling_scheme.py - no hardcoded band_names default
            container = job_params.get("container_name") or config.storage.bronze.get_container('rasters')

            # Pass user's band_names if provided, otherwise None triggers auto-detection
            # FIX (01 DEC 2025): Removed hardcoded {"5": "Red", "3": "Green", "2": "Blue"} default
            # that broke standard RGB images like antigua.tif
            user_band_names = job_params.get("band_names")

            return [{
                "task_id": f"{job_id[:8]}-s1-tiling",
                "task_type": "generate_tiling_scheme",
                "parameters": {
                    "container_name": container,
                    "blob_name": job_params["blob_name"],
                    "tile_size": job_params.get("tile_size"),  # None = auto-calculate
                    "overlap": job_params.get("overlap", 512),
                    "output_container": config.storage.silver.get_container('cogs'),
                    "band_names": user_band_names,  # None = auto-detect in tiling_scheme.py
                    "target_crs": job_params.get("target_crs") or config.raster.target_crs
                }
            }]

        elif stage == 2:
            # Stage 2: Extract tiles sequentially (single long-running task)
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 1 failed - no tiling scheme generated")

            stage1_result = previous_results[0]["result"]
            tiling_scheme_blob = stage1_result["tiling_scheme_blob"]

            container = job_params.get("container_name") or config.storage.bronze.get_container('rasters')

            # FIX (01 DEC 2025): Use auto-detected band_names from Stage 1, fall back to user param
            # Priority: user param > Stage 1 auto-detected > None (process all bands)
            raster_metadata = stage1_result.get("raster_metadata", {})
            band_names = job_params.get("band_names") or raster_metadata.get("used_band_names")

            logger.info(f"Stage 2: Using band_names={band_names} (detected_type: {raster_metadata.get('detected_type', 'unknown')})")

            return [{
                "task_id": f"{job_id[:8]}-s2-extract",
                "task_type": "extract_tiles",
                "parameters": {
                    "container_name": container,
                    "blob_name": job_params["blob_name"],
                    "tiling_scheme_blob": tiling_scheme_blob,
                    "tiling_scheme_container": config.storage.silver.get_container('cogs'),
                    "output_container": config.resolved_intermediate_tiles_container,
                    "job_id": job_id,  # For folder naming: {job_id[:8]}/tiles/
                    "band_names": band_names
                }
            }]

        elif stage == 3:
            # Stage 3: Create COGs for all tiles (fan-out)
            if not previous_results or not previous_results[0].get("success"):
                raise ValueError("Stage 2 failed - no tiles extracted")

            stage2_result = previous_results[0]["result"]
            tile_blobs = stage2_result["tile_blobs"]
            source_crs = stage2_result["source_crs"]
            raster_metadata = stage2_result.get("raster_metadata", {})

            logger.info(f"Stage 3: Creating {len(tile_blobs)} COG tasks, source CRS: {source_crs}")

            # Build raster_type dict from metadata
            raster_type = {
                "detected_type": raster_metadata.get("detected_type", "unknown"),
                "band_count": raster_metadata.get("band_count", 3),
                "data_type": raster_metadata.get("data_type", "uint8"),
                "optimal_cog_settings": {}
            }

            # Extract blob_stem for path generation
            blob_stem = Path(job_params['blob_name']).stem
            output_folder = job_params.get("output_folder")

            # Resolve config defaults
            target_crs = job_params.get("target_crs") or config.raster.target_crs
            jpeg_quality = job_params.get("jpeg_quality") or config.raster.cog_jpeg_quality

            tasks = []
            for idx, tile_blob in enumerate(tile_blobs):
                # Extract tile ID from path
                tile_filename = tile_blob.split('/')[-1]
                tile_id = tile_filename.replace(f"{blob_stem}_tile_", "").replace(".tif", "")

                # Generate output filename
                output_filename = tile_filename.replace('.tif', '_cog.tif')
                if output_folder:
                    output_blob_name = f"{output_folder}/{output_filename}"
                else:
                    output_blob_name = output_filename

                tasks.append({
                    "task_id": f"{job_id[:8]}-s3-cog-{tile_id}",
                    "task_type": "create_cog",
                    "parameters": {
                        "container_name": config.resolved_intermediate_tiles_container,
                        "blob_name": tile_blob,
                        "source_crs": source_crs,
                        "target_crs": target_crs,
                        "raster_type": raster_type,
                        "output_tier": job_params.get("output_tier", "analysis"),
                        "output_blob_name": output_blob_name,
                        "output_container": config.storage.silver.get_container('cogs'),
                        "jpeg_quality": jpeg_quality,
                        "overview_resampling": config.raster.overview_resampling,
                        "reproject_resampling": config.raster.reproject_resampling,
                        "in_memory": job_params.get("in_memory", True)
                    },
                    "metadata": {
                        "tile_index": idx,
                        "tile_count": len(tile_blobs)
                    }
                })

            return tasks

        elif stage == 4:
            # Stage 4: Create MosaicJSON (fan-in)
            # CoreMachine auto-creates aggregation task with previous_results
            return []

        elif stage == 5:
            # Stage 5: Create STAC collection (fan-in)
            # CoreMachine auto-creates aggregation task with previous_results
            return []

        else:
            raise ValueError(f"ProcessLargeRasterV2Job has 5 stages, got stage {stage}")

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Create final job summary with TiTiler URLs.

        Extracts workflow-specific summaries for stages 1-2 (tiling, extraction),
        then uses shared finalization logic from RasterWorkflowsBase.
        """
        from core.models import TaskStatus

        task_results = context.task_results
        params = context.parameters

        # Extract Stage 1 (tiling) summary
        tiling_tasks = [t for t in task_results if t.task_type == "generate_tiling_scheme"]
        tiling_summary = {}
        if tiling_tasks and tiling_tasks[0].result_data:
            tiling_result = tiling_tasks[0].result_data.get("result", {})
            tiling_summary = {
                "scheme_blob": tiling_result.get("tiling_scheme_blob"),
                "tile_count": tiling_result.get("tile_count"),
                "grid_dimensions": tiling_result.get("grid_dimensions")
            }

        # Extract Stage 2 (extraction) summary
        extraction_tasks = [t for t in task_results if t.task_type == "extract_tiles"]
        extraction_summary = {}
        if extraction_tasks and extraction_tasks[0].result_data:
            extraction_result = extraction_tasks[0].result_data.get("result", {})
            extraction_summary = {
                "processing_time_seconds": extraction_result.get("processing_time_seconds"),
                "tiles_extracted": extraction_result.get("tile_count")
            }

        # Use shared finalization for Stages 3-5 (COG, MosaicJSON, STAC)
        return RasterWorkflowsBase._finalize_cog_mosaicjson_stac_stages(
            context=context,
            job_type="process_large_raster_v2",
            cog_stage_num=3,
            mosaicjson_stage_num=4,
            stac_stage_num=5,
            extra_summaries={
                "source_blob": params.get("blob_name"),
                "source_container": params.get("container_name"),
                "tiling": tiling_summary,
                "extraction": extraction_summary,
                "blob_size_mb": params.get("_blob_size_mb")  # From preflight validation
            }
        )
