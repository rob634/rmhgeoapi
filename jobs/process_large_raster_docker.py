# ============================================================================
# PROCESS LARGE RASTER DOCKER JOB
# ============================================================================
# STATUS: Jobs - DEPRECATED (V0.8 - 24 JAN 2026)
# PURPOSE: Process large rasters (100MB-30GB) in Docker with slice/dice/COG
# CREATED: 13 JAN 2026 - F7.18 Docker Large Raster Pipeline
# DEPRECATED: 24 JAN 2026 - Use process_raster_docker instead
# ============================================================================
"""
Process Large Raster Docker - DEPRECATED.

⚠️ DEPRECATED (V0.8 - 24 JAN 2026)
This job is deprecated. Use `process_raster_docker` instead, which handles
both single COG and tiled output internally based on file size.

V0.8 Architecture:
    - ALL raster processing goes through process_raster_docker
    - Tiling decision is made internally based on raster_tiling_threshold_mb
    - Files > threshold produce tiled output, files <= threshold produce single COG
    - One job type handles all raster sizes

This file is kept for backward compatibility during migration period.
After migration, remove this file and update references.

Migration:
    OLD: Submit job with job_type="process_large_raster_docker"
    NEW: Submit job with job_type="process_raster_docker" (same parameters)

The new job will automatically detect large files and produce tiled output.

Exports:
    ProcessLargeRasterDockerJob: DEPRECATED - use ProcessRasterDockerJob
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config.defaults import STACDefaults


class ProcessLargeRasterDockerJob(JobBaseMixin, JobBase):
    """
    Docker large raster processing - DEPRECATED (V0.8).

    ⚠️ DEPRECATED: Use process_raster_docker instead.
    This job is kept for backward compatibility during migration.

    V0.8 Architecture (24 JAN 2026):
        - process_raster_docker now handles both single COG and tiled output
        - Tiling decision is automatic based on file size vs threshold
        - This job will be removed in a future version
    """

    job_type = "process_large_raster_docker"
    description = "DEPRECATED: Use process_raster_docker instead (tiling is now automatic)"

    @classmethod
    def validate_parameters(cls, params):
        """Log deprecation warning before processing."""
        import logging
        import warnings
        logger = logging.getLogger(__name__)

        # Log deprecation warning
        logger.warning("=" * 60)
        logger.warning("⚠️ DEPRECATED: process_large_raster_docker")
        logger.warning("  This job type is deprecated as of V0.8 (24 JAN 2026)")
        logger.warning("  Use 'process_raster_docker' instead")
        logger.warning("  Tiling is now automatic based on file size")
        logger.warning("=" * 60)

        # Also issue Python deprecation warning
        warnings.warn(
            "process_large_raster_docker is deprecated. "
            "Use process_raster_docker instead - it handles tiling automatically.",
            DeprecationWarning,
            stacklevel=2
        )

        # Call parent validation
        return super().validate_parameters(params)

    # Single stage - handler does everything
    stages = [
        {
            "number": 1,
            "name": "process_large_complete",
            "task_type": "raster_process_large_complete",
            "parallelism": "single"
        }
    ]

    # Parameters - compatible with process_large_raster_v2
    parameters_schema = {
        # Required
        'blob_name': {'type': 'str', 'required': True},
        'container_name': {'type': 'str', 'required': True},

        # CRS
        'input_crs': {'type': 'str', 'default': None},
        'target_crs': {'type': 'str', 'default': None},

        # Raster type
        'raster_type': {
            'type': 'str',
            'default': 'auto',
            'allowed': ['auto', 'rgb', 'rgba', 'dem', 'categorical', 'multispectral', 'nir']
        },

        # COG output
        'output_tier': {
            'type': 'str',
            'default': 'analysis',
            'allowed': ['visualization', 'analysis', 'archive', 'all']
        },
        'jpeg_quality': {'type': 'int', 'default': None, 'min': 1, 'max': 100},
        'output_folder': {'type': 'str', 'default': None},

        # Tiling parameters
        'tile_size': {'type': 'int', 'default': None},  # None = auto-calculate
        'overlap': {'type': 'int', 'default': 512, 'min': 0},
        'band_names': {'type': 'dict', 'default': None},  # e.g., {"5": "Red", "3": "Green", "2": "Blue"}

        # STAC
        'collection_id': {'type': 'str', 'required': True},  # Required (14 JAN 2026)
        'item_id': {'type': 'str', 'default': None},

        # Platform passthrough (DDH integration)
        'dataset_id': {'type': 'str', 'default': None},
        'resource_id': {'type': 'str', 'default': None},
        'version_id': {'type': 'str', 'default': None},
        'access_level': {'type': 'str', 'default': None},
    }

    # Pre-flight validation - blob must exist with size in range
    resource_validators = [
        {
            'type': 'blob_exists_with_size',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'min_size_mb': 100,
            'max_size_mb': 30000,  # 30 GB max
            'error_not_found': 'Source raster file does not exist.',
            'error_too_small': 'File too small for large raster pipeline (< 100MB). Use process_raster_docker instead.',
            'error_too_large': 'Raster file exceeds 30GB limit.',
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: Dict[str, Any], job_id: str,
                                previous_results: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """Generate single task for the complete large raster processing stage."""
        from core.task_id import generate_deterministic_task_id
        from infrastructure.blob import BlobRepository
        from config import get_config

        config = get_config()

        if stage != 1:
            raise ValueError(f"ProcessLargeRasterDockerJob has 1 stage, got stage {stage}")

        # Get SAS URL for source blob (from bronze zone)
        blob_repo = BlobRepository.for_zone("bronze")
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=job_params['container_name'],
            blob_name=job_params['blob_name'],
            hours=48  # Long-lived for large raster Docker processing
        )

        # Resolve defaults from config
        target_crs = job_params.get('target_crs') or config.raster.target_crs
        jpeg_quality = job_params.get('jpeg_quality') or config.raster.cog_jpeg_quality
        collection_id = job_params['collection_id']  # Required (14 JAN 2026)

        return [{
            'task_id': generate_deterministic_task_id(job_id, 1, "process_large_complete"),
            'task_type': 'raster_process_large_complete',
            'parameters': {
                # Source
                'blob_url': blob_url,
                'blob_name': job_params['blob_name'],
                'container_name': job_params['container_name'],

                # CRS
                'input_crs': job_params.get('input_crs'),
                'target_crs': target_crs,

                # Raster type
                'raster_type': job_params.get('raster_type', 'auto'),

                # COG output
                'output_tier': job_params.get('output_tier', 'analysis'),
                'output_folder': job_params.get('output_folder'),
                'jpeg_quality': jpeg_quality,
                'overview_resampling': config.raster.overview_resampling,
                'reproject_resampling': config.raster.reproject_resampling,

                # Tiling
                'tile_size': job_params.get('tile_size'),
                'overlap': job_params.get('overlap', 512),
                'band_names': job_params.get('band_names'),

                # STAC
                'collection_id': collection_id,
                'item_id': job_params.get('item_id'),

                # Platform passthrough
                'dataset_id': job_params.get('dataset_id'),
                'resource_id': job_params.get('resource_id'),
                'version_id': job_params.get('version_id'),
                'access_level': job_params.get('access_level'),

                # Job context
                '_job_id': job_id,
                '_blob_size_mb': job_params.get('_blob_size_mb'),
            }
        }]

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """Create final job summary from the single stage result."""
        from core.models import TaskStatus
        from config import get_config

        task_results = context.task_results
        params = context.parameters
        config = get_config()

        # Get the single task result
        if not task_results:
            return {
                "job_type": "process_large_raster_docker",
                "success": False,
                "error": "No task results available"
            }

        task = task_results[0]
        result_data = task.result_data or {}

        # Unwrap the 'result' key - handlers return {"success": bool, "result": {...}}
        unwrapped = result_data.get('result', {})

        # Extract sub-results from unwrapped data
        tiling = unwrapped.get('tiling', {})
        extraction = unwrapped.get('extraction', {})
        cogs = unwrapped.get('cogs', {})
        mosaicjson = unwrapped.get('mosaicjson', {})
        stac = unwrapped.get('stac', {})
        resources = unwrapped.get('resources', {})
        artifact_id = unwrapped.get('artifact_id')  # Artifact registry (21 JAN 2026)

        # Generate TiTiler URLs if we have MosaicJSON
        titiler_urls = None
        share_url = None
        if mosaicjson.get('mosaicjson_blob'):
            try:
                titiler_urls = config.generate_titiler_urls_unified(
                    mode="mosaicjson",
                    container=mosaicjson.get('mosaicjson_container'),
                    blob_name=mosaicjson.get('mosaicjson_blob')
                )
                share_url = titiler_urls.get("viewer_url")
            except Exception:
                pass

        # Generate STAC URLs if we have collection info
        stac_urls = None
        if stac.get('collection_id'):
            stac_base = config.stac_api_base_url.rstrip('/')
            stac_urls = {
                "collection_url": f"{stac_base}/collections/{stac['collection_id']}",
            }
            if stac.get('item_id'):
                stac_urls["item_url"] = f"{stac_base}/collections/{stac['collection_id']}/items/{stac['item_id']}"

        return {
            "job_type": "process_large_raster_docker",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container_name"),
            "blob_size_mb": params.get("_blob_size_mb"),
            "tiling": tiling,
            "extraction": extraction,
            "cogs": cogs,
            "mosaicjson": mosaicjson,
            "stac": stac,
            "stac_urls": stac_urls,
            "titiler_urls": titiler_urls,
            "share_url": share_url,
            "artifact_id": artifact_id,  # Artifact registry (21 JAN 2026)
            "resources": resources,  # F7.20 resource metrics
            "processing_mode": "docker_large_raster_single_stage",
            "stages_completed": 1,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
