# ============================================================================
# PROCESS LARGE RASTER DOCKER JOB
# ============================================================================
# STATUS: Jobs - Single-stage large raster tiling pipeline for Docker worker
# PURPOSE: Process large rasters (100MB-30GB) in Docker with slice/dice/COG
# CREATED: 13 JAN 2026 - F7.18 Docker Large Raster Pipeline
# ============================================================================
"""
Process Large Raster Docker - Consolidated Single-Stage Job.

Designed for Docker worker where there are no timeout constraints.
Consolidates all 5 stages of process_large_raster_v2 into a single handler:
    - Phase 1: Generate tiling scheme
    - Phase 2: Extract tiles (sequential)
    - Phase 3: Create COGs (sequential in Docker)
    - Phase 4: Create MosaicJSON
    - Phase 5: Create STAC collection

Why Single Stage:
    - Docker has no timeout limits (unlike 10-min Function App limit)
    - No stage progression overhead
    - Simpler debugging and monitoring
    - Same CoreMachine contract - just one stage instead of five
    - Checkpoint/resume support for crash recovery

Target Use Cases:
    - Large rasters (100MB-30GB) that need tiling
    - Complex multi-band imagery requiring band selection
    - Production batch processing of satellite imagery

Exports:
    ProcessLargeRasterDockerJob: Single-stage Docker large raster job
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin
from config.defaults import STACDefaults


class ProcessLargeRasterDockerJob(JobBaseMixin, JobBase):
    """
    Docker large raster processing - single stage, no timeout constraints.

    Consolidates tiling → extraction → COG → MosaicJSON → STAC into one handler.
    Uses same parameters as process_large_raster_v2 for compatibility.
    """

    job_type = "process_large_raster_docker"
    description = "Process large raster (100MB-30GB) to tiled COG mosaic (Docker - no timeout)"

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

        # Extract sub-results
        tiling = result_data.get('tiling', {})
        extraction = result_data.get('extraction', {})
        cogs = result_data.get('cogs', {})
        mosaicjson = result_data.get('mosaicjson', {})
        stac = result_data.get('stac', {})

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
            "processing_mode": "docker_large_raster_single_stage",
            "stages_completed": 1,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
