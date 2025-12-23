"""
Process Raster Collection V2 Job.

Multi-tile raster collection processing producing COGs + MosaicJSON + STAC.

Four-stage workflow:
    1. Validate Tiles: Parallel validation of all tiles
    2. Create COGs: Parallel COG creation for all tiles
    3. Create MosaicJSON: Aggregate into virtual mosaic
    4. Create STAC Collection: Collection-level STAC item

Exports:
    ProcessRasterCollectionV2Job: Job class for multi-tile raster processing
"""

from typing import Dict, Any, List, Optional

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from jobs.raster_workflows_base import RasterWorkflowsBase
from jobs.raster_mixin import RasterMixin


class ProcessRasterCollectionV2Job(RasterMixin, RasterWorkflowsBase, JobBaseMixin, JobBase):
    """
    Multi-tile raster collection processing using JobBaseMixin.
    Clean slate implementation - no deprecated parameters.

    Four-stage workflow:
    1. validate_tiles: Parallel validation of all tiles (fan-out)
    2. create_cogs: Parallel COG creation (fan-out)
    3. create_mosaicjson: Aggregate into MosaicJSON (fan-in)
    4. create_stac: Create STAC collection (fan-in)

    Preflight Validation:
    - Container exists check
    - All blobs in blob_list exist with size capture (parallel check)
    - Collection size limit enforced (max files allowed)
    - Individual raster size threshold enforced (reject large files)

    Size-Based Routing (23 DEC 2025 - env var names updated):
        Pre-flight validation checks the count and size of each raster in the collection.

        Rejection conditions:
        1. Collection exceeds RASTER_COLLECTION_MAX_FILES (default: 20 files)
           → Submit smaller batches
        2. ANY raster exceeds RASTER_ROUTE_LARGE_MB (default: 1200 MB)
           → Large raster collection processing requires Docker worker (coming soon)

        Current behavior:
            Rejects with clear error message - large collection processing
            requires Docker worker which is not yet implemented.

        Future behavior (when Docker worker is ready):
            Routes ALL tasks to 'long-running-tasks' queue instead of
            'raster-tasks' queue. All-or-none routing prevents complexity of
            splitting tasks between queues for a single job.

        Thresholds configurable via environment variables:
        - RASTER_COLLECTION_MAX_FILES: Max files in collection (default: 20)
        - RASTER_ROUTE_LARGE_MB: Max individual file size in MB (default: 1200)
    """

    job_type = "process_raster_collection_v2"
    description = "Process raster tile collection to COGs with MosaicJSON (v2 mixin pattern)"

    stages = [
        {"number": 1, "name": "validate_tiles", "task_type": "validate_raster", "parallelism": "fan_out"},
        {"number": 2, "name": "create_cogs", "task_type": "create_cog", "parallelism": "fan_out"},
        {"number": 3, "name": "create_mosaicjson", "task_type": "create_mosaicjson", "parallelism": "fan_in"},
        {"number": 4, "name": "create_stac", "task_type": "create_stac_collection", "parallelism": "fan_in"}
    ]

    # Compose parameters schema from RasterMixin shared schemas
    parameters_schema = {
        # Shared raster parameters
        **RasterMixin.COMMON_RASTER_SCHEMA,
        **RasterMixin.MOSAICJSON_SCHEMA,
        **RasterMixin.PLATFORM_PASSTHROUGH_SCHEMA,
        **RasterMixin.VALIDATION_BYPASS_SCHEMA,

        # Collection-specific parameters
        'blob_list': {'type': 'list', 'required': True},

        # Additional optional parameters
        'mosaicjson_container': {'type': 'str', 'default': None},
        'cog_container': {'type': 'str', 'default': None},
    }

    # Preflight resource validators (13 DEC 2025 - size enforcement)
    # Uses blob_list_exists_with_max_size for parallel validation + size capture
    resource_validators = [
        {
            'type': 'container_exists',
            'container_param': 'container_name',
            'error': 'Source container does not exist'
        },
        {
            # Size-aware validator (13 DEC 2025)
            # Checks: existence, collection count limit, individual size threshold
            'type': 'blob_list_exists_with_max_size',
            'container_param': 'container_name',
            'blob_list_param': 'blob_list',
            'skip_validation_param': '_skip_blob_validation',
            'parallel': True,
            'max_parallel': 10,
            'report_all': True,
            'min_count': 2,
            # Collection count limit (from env var - 23 DEC 2025)
            'max_collection_count_env': 'RASTER_COLLECTION_MAX_FILES',
            # Individual raster size threshold (from env var - 23 DEC 2025)
            'max_individual_size_mb_env': 'RASTER_ROUTE_LARGE_MB',
            # Error messages
            'error_not_found': 'One or more tiles not found in collection. Verify blob paths.',
            'error_collection_too_large': (
                'Collection exceeds maximum file count ({limit} files). '
                'Submit smaller batches or contact support for bulk processing.'
            ),
            'error_raster_too_large': (
                'Collection contains raster(s) exceeding {threshold}MB threshold. '
                'Large raster collection processing requires Docker worker (coming soon). '
                'For now, process large files individually using process_large_raster_v2.'
            )
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

        config = get_config()

        if stage == 1:
            # Stage 1: Validate all tiles (fan-out)
            return RasterMixin._create_validation_tasks(
                job_id=job_id,
                blob_list=job_params["blob_list"],
                container_name=job_params["container_name"],
                job_params=job_params,
                stage_num=1
            )

        elif stage == 2:
            # Stage 2: Create COGs for all tiles (fan-out)
            if not previous_results:
                raise ValueError("Stage 2 requires Stage 1 validation results")

            return RasterMixin._create_cog_tasks(
                job_id=job_id,
                validation_results=previous_results,
                blob_list=job_params["blob_list"],
                job_params=job_params,
                stage_num=2
            )

        elif stage == 3:
            # Stage 3: Create MosaicJSON (fan-in)
            # CoreMachine auto-creates aggregation task with previous_results
            return []

        elif stage == 4:
            # Stage 4: Create STAC collection (fan-in)
            # CoreMachine auto-creates aggregation task with previous_results
            return []

        else:
            raise ValueError(f"ProcessRasterCollectionV2Job has 4 stages, got stage {stage}")

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Create final job summary with TiTiler URLs.

        Uses shared finalization logic from RasterWorkflowsBase.
        """
        return RasterWorkflowsBase._finalize_cog_mosaicjson_stac_stages(
            context=context,
            job_type="process_raster_collection_v2",
            cog_stage_num=2,
            mosaicjson_stage_num=3,
            stac_stage_num=4,
            extra_summaries={
                "source_container": context.parameters.get("container_name"),
                "tile_count": len(context.parameters.get("blob_list", [])),
                "validation_bypassed": context.parameters.get("_skip_blob_validation", False)
            }
        )
