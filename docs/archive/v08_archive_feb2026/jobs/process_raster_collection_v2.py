# ============================================================================
# PROCESS RASTER COLLECTION V2 JOB
# ============================================================================
# STATUS: Jobs - ARCHIVED (V0.8 - 24 JAN 2026)
# PURPOSE: Process raster tile collections to COGs + MosaicJSON + STAC
# LAST_REVIEWED: 24 JAN 2026
# ARCHIVED: Function App raster jobs are deprecated
# ============================================================================
"""
Process Raster Collection V2 Job.

⚠️ ARCHIVED (V0.8 - 24 JAN 2026)
This job is ARCHIVED and should not be used. It runs on Function App
which has a 10-minute timeout limit.

V0.8 Architecture:
    - ALL raster processing goes to Docker worker
    - For collections, use the platform API which routes to Docker
    - This job will be removed in a future version

This file is kept only to prevent import errors during migration.
Do NOT use this job for new workflows.

Exports:
    ProcessRasterCollectionV2Job: ARCHIVED - do not use
"""

from typing import Dict, Any, List, Optional

from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from jobs.raster_workflows_base import RasterWorkflowsBase
from jobs.raster_mixin import RasterMixin


class ProcessRasterCollectionV2Job(RasterMixin, RasterWorkflowsBase, JobBaseMixin, JobBase):
    """
    Multi-tile raster collection processing - ARCHIVED (V0.8).

    ⚠️ ARCHIVED: Do not use this job.
    This job runs on Function App which has timeout limits.

    V0.8 Architecture (24 JAN 2026):
        - ALL raster processing goes to Docker worker
        - Use process_raster_docker for single files
        - For collections, use platform API which routes appropriately
        - This job will be removed in a future version
    """

    job_type = "process_raster_collection_v2"
    description = "ARCHIVED: Function App raster collection - do not use"

    @classmethod
    def validate_parameters(cls, params):
        """Log archived warning - this job should not be used."""
        import logging
        import warnings
        logger = logging.getLogger(__name__)

        # Log archived warning
        logger.error("=" * 60)
        logger.error("❌ ARCHIVED: process_raster_collection_v2")
        logger.error("  This job is ARCHIVED as of V0.8 (24 JAN 2026)")
        logger.error("  Use process_raster_docker or platform API instead")
        logger.error("  This job runs on Function App with timeout limits")
        logger.error("=" * 60)

        # Issue warning
        warnings.warn(
            "process_raster_collection_v2 is ARCHIVED. "
            "Use process_raster_docker or platform API instead.",
            DeprecationWarning,
            stacklevel=2
        )

        # Call parent validation
        return super().validate_parameters(params)

    stages = [
        {"number": 1, "name": "validate_tiles", "task_type": "raster_validate", "parallelism": "fan_out"},
        {"number": 2, "name": "create_cogs", "task_type": "raster_create_cog", "parallelism": "fan_out"},
        {"number": 3, "name": "create_mosaicjson", "task_type": "raster_create_mosaicjson", "parallelism": "fan_in"},
        {"number": 4, "name": "create_stac", "task_type": "raster_create_stac_collection", "parallelism": "fan_in"}
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
            # Size-aware validator
            # V0.8 (24 JAN 2026): Updated to use RASTER_TILING_THRESHOLD_MB
            'type': 'blob_list_exists_with_max_size',
            'container_param': 'container_name',
            'blob_list_param': 'blob_list',
            'skip_validation_param': '_skip_blob_validation',
            'parallel': True,
            'max_parallel': 10,
            'report_all': True,
            'min_count': 2,
            # Collection count limit
            'max_collection_count_env': 'RASTER_COLLECTION_MAX_FILES',
            # V0.8: Use tiling threshold instead of removed RASTER_ROUTE_LARGE_MB
            'max_individual_size_mb_env': 'RASTER_TILING_THRESHOLD_MB',
            # Error messages
            'error_not_found': 'One or more tiles not found in collection. Verify blob paths.',
            'error_collection_too_large': (
                'Collection exceeds maximum file count ({limit} files). '
                'Submit smaller batches or contact support for bulk processing.'
            ),
            'error_raster_too_large': (
                'Collection contains raster(s) exceeding {threshold}MB threshold. '
                'Use process_raster_docker instead - it handles large files automatically.'
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
