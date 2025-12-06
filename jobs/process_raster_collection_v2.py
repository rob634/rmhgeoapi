# ============================================================================
# CLAUDE CONTEXT - PROCESS RASTER COLLECTION V2 (MIXIN PATTERN)
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: New job - Clean slate JobBaseMixin implementation (30 NOV 2025)
# PURPOSE: Multi-tile raster collection processing → COGs + MosaicJSON + STAC
# LAST_REVIEWED: 30 NOV 2025
# EXPORTS: ProcessRasterCollectionV2Job
# INTERFACES: JobBase, JobBaseMixin, RasterMixin, RasterWorkflowsBase
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base, jobs.mixins, jobs.raster_mixin, jobs.raster_workflows_base
# SOURCE: User job submission via /api/jobs/submit/process_raster_collection_v2
# SCOPE: Multi-tile raster ETL pipeline
# VALIDATION: JobBaseMixin declarative schema + resource validators (blob_list_exists)
# PATTERNS: Mixin pattern (77% less boilerplate), Fan-out/fan-in architecture
# ENTRY_POINTS: from jobs import ALL_JOBS; ALL_JOBS["process_raster_collection_v2"]
# INDEX: ProcessRasterCollectionV2Job:45, create_tasks_for_stage:95, finalize_job:145
# ============================================================================

"""
Process Raster Collection V2 - Clean Slate JobBaseMixin Implementation

Uses JobBaseMixin + RasterMixin pattern for 83% less boilerplate code:
- validate_job_parameters: Declarative via parameters_schema + resource_validators
- generate_job_id: Automatic SHA256 from params
- create_job_record: Automatic via mixin
- queue_job: Automatic via mixin

Four-stage workflow:
1. Validate Tiles (Fan-out): Parallel validation of all tiles
2. Create COGs (Fan-out): Parallel COG creation for all tiles
3. Create MosaicJSON (Fan-in): Aggregate into virtual mosaic
4. Create STAC Collection (Fan-in): Collection-level STAC item

Key improvements:
    - Clean slate parameters (no deprecated fields)
    - Preflight validation with blob_list_exists
    - Validation bypass option (_skip_blob_validation=True)
    - Reduced boilerplate via mixin pattern
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
    - All blobs in blob_list exist (parallel check, can bypass)
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

    # Preflight resource validators
    # Uses blob_list_exists for efficient parallel validation of all tiles
    resource_validators = [
        {
            'type': 'container_exists',
            'container_param': 'container_name',
            'error': 'Source container does not exist'
        },
        {
            'type': 'blob_list_exists',
            'container_param': 'container_name',
            'blob_list_param': 'blob_list',
            'skip_validation_param': '_skip_blob_validation',
            'parallel': True,
            'max_parallel': 10,
            'report_all': True,
            'min_count': 2,
            'error_not_found': 'One or more tiles not found in collection. Verify blob paths.'
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
