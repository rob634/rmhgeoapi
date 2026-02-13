# ============================================================================
# PROCESS LARGE RASTER V2 JOB
# ============================================================================
# STATUS: Jobs - ARCHIVED (V0.8 - 24 JAN 2026)
# PURPOSE: Process 1-30GB rasters to tiled COG mosaic + MosaicJSON + STAC
# LAST_REVIEWED: 24 JAN 2026
# ARCHIVED: Function App raster jobs are deprecated
# ============================================================================
"""
Process Large Raster V2 Job.

⚠️ ARCHIVED (V0.8 - 24 JAN 2026)
This job is ARCHIVED and should not be used. It runs on Function App
which has a 10-minute timeout limit - unsuitable for large rasters.

V0.8 Architecture:
    - ALL raster processing goes to Docker worker
    - Use process_raster_docker - it handles tiling automatically
    - Docker has no timeout and uses Azure Files mount for temp storage

This file is kept only to prevent import errors during migration.
Do NOT use this job for new workflows.

Exports:
    ProcessLargeRasterV2Job: ARCHIVED - use process_raster_docker
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
    Large raster tiling workflow - ARCHIVED (V0.8).

    ⚠️ ARCHIVED: Do not use this job.
    This job runs on Function App which has timeout limits.
    Large rasters WILL timeout on Function App.

    V0.8 Architecture (24 JAN 2026):
        - ALL raster processing goes to Docker worker
        - Use process_raster_docker - it handles tiling automatically
        - Files > RASTER_TILING_THRESHOLD_MB produce tiled output
        - Docker has no timeout and uses Azure Files mount

    This file is kept only to prevent import errors during migration.
    """

    job_type = "process_large_raster_v2"
    description = "ARCHIVED: Use process_raster_docker instead"

    @classmethod
    def validate_parameters(cls, params):
        """Log archived warning - this job should not be used."""
        import logging
        import warnings
        logger = logging.getLogger(__name__)

        # Log archived warning
        logger.error("=" * 60)
        logger.error("❌ ARCHIVED: process_large_raster_v2")
        logger.error("  This job is ARCHIVED as of V0.8 (24 JAN 2026)")
        logger.error("  Use 'process_raster_docker' instead")
        logger.error("  It handles tiling automatically for large files")
        logger.error("=" * 60)

        # Issue warning
        warnings.warn(
            "process_large_raster_v2 is ARCHIVED. "
            "Use process_raster_docker instead - it handles tiling automatically.",
            DeprecationWarning,
            stacklevel=2
        )

        # Call parent validation
        return super().validate_parameters(params)

    stages = [
        {"number": 1, "name": "generate_tiling_scheme", "task_type": "raster_generate_tiling_scheme", "parallelism": "single"},
        {"number": 2, "name": "extract_tiles", "task_type": "raster_extract_tiles", "parallelism": "single"},
        {"number": 3, "name": "create_cogs", "task_type": "raster_create_cog", "parallelism": "fan_out"},
        {"number": 4, "name": "create_mosaicjson", "task_type": "raster_create_mosaicjson", "parallelism": "fan_in"},
        {"number": 5, "name": "create_stac", "task_type": "raster_create_stac_collection", "parallelism": "fan_in"}
    ]

    # Compose parameters schema from RasterMixin shared schemas
    parameters_schema = {
        # Shared raster parameters
        **RasterMixin.COMMON_RASTER_SCHEMA,
        **RasterMixin.MOSAICJSON_SCHEMA,
        **RasterMixin.PLATFORM_PASSTHROUGH_SCHEMA,

        # Large raster required parameters
        'blob_name': {'type': 'str', 'required': True},

        # collection_id is required (14 JAN 2026) - no more system-rasters default
        'collection_id': {'type': 'str', 'required': True},

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
                "task_type": "raster_generate_tiling_scheme",
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
                "task_type": "raster_extract_tiles",
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
                    "task_type": "raster_create_cog",
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
        tiling_tasks = [t for t in task_results if t.task_type == "raster_generate_tiling_scheme"]
        tiling_summary = {}
        if tiling_tasks and tiling_tasks[0].result_data:
            tiling_result = tiling_tasks[0].result_data.get("result", {})
            tiling_summary = {
                "scheme_blob": tiling_result.get("tiling_scheme_blob"),
                "tile_count": tiling_result.get("tile_count"),
                "grid_dimensions": tiling_result.get("grid_dimensions")
            }

        # Extract Stage 2 (extraction) summary
        extraction_tasks = [t for t in task_results if t.task_type == "raster_extract_tiles"]
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
