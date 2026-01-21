# ============================================================================
# PROCESS RASTER DOCKER JOB
# ============================================================================
# STATUS: Jobs - Single-stage raster to COG pipeline for Docker worker
# PURPOSE: Process rasters in Docker container (no timeout constraints)
# LAST_REVIEWED: 11 JAN 2026
# ============================================================================
"""
Process Raster Docker - Consolidated Single-Stage Job.

Designed for Docker worker where there are no timeout constraints.
Consolidates all 3 stages of process_raster_v2 into a single handler:
    - Validation (CRS, type detection)
    - COG creation (reproject + compress)
    - STAC metadata (catalog registration)

Why Single Stage:
    - Docker has no timeout limits (unlike 10-min Function App limit)
    - No stage progression overhead
    - Simpler debugging and monitoring
    - Same CoreMachine contract - just one stage instead of three

Target Use Cases:
    - Large rasters (>1GB) that need windowed processing
    - Complex projections requiring full GDAL
    - Production batch processing

Exports:
    ProcessRasterDockerJob: Single-stage Docker raster job
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class ProcessRasterDockerJob(JobBaseMixin, JobBase):
    """
    Docker raster processing - single stage, no timeout constraints.

    Consolidates validate → COG → STAC into one handler execution.
    Uses same parameters as process_raster_v2 for compatibility.
    """

    job_type = "process_raster_docker"
    description = "Process raster to COG (Docker - single stage, no timeout)"

    # Single stage - handler does everything
    stages = [
        {
            "number": 1,
            "name": "process_complete",
            "task_type": "raster_process_complete",
            "parallelism": "single"
        }
    ]

    # Same parameters as process_raster_v2 for compatibility
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

        # Behavior
        'strict_mode': {'type': 'bool', 'default': False},

        # STAC
        'collection_id': {'type': 'str', 'required': True},  # Required (14 JAN 2026)
        'item_id': {'type': 'str', 'default': None},
        'collection_must_exist': {'type': 'bool', 'default': False},  # Fail if collection doesn't exist (12 JAN 2026)

        # Platform passthrough (DDH integration)
        'dataset_id': {'type': 'str', 'default': None},
        'resource_id': {'type': 'str', 'default': None},
        'version_id': {'type': 'str', 'default': None},
        'access_level': {'type': 'str', 'default': None},
        'stac_item_id': {'type': 'str', 'default': None},

        # Docker-specific options
        'use_windowed_read': {'type': 'bool', 'default': True},  # For giant rasters
        'chunk_size_mb': {'type': 'int', 'default': 256},  # Window size for chunked processing
    }

    # Pre-flight validation - blob must exist
    resource_validators = [
        {
            'type': 'blob_exists_with_size',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'error_not_found': 'Source raster file does not exist.',
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: Dict[str, Any], job_id: str,
                                previous_results: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """Generate single task for the complete processing stage."""
        from core.task_id import generate_deterministic_task_id
        from infrastructure.blob import BlobRepository
        from config import get_config

        config = get_config()

        if stage != 1:
            raise ValueError(f"ProcessRasterDockerJob has 1 stage, got stage {stage}")

        # Get SAS URL for source blob (from bronze zone)
        blob_repo = BlobRepository.for_zone("bronze")
        blob_url = blob_repo.get_blob_url_with_sas(
            container_name=job_params['container_name'],
            blob_name=job_params['blob_name'],
            hours=24  # Long-lived for Docker processing
        )

        # Generate output blob name
        blob_name = job_params['blob_name']
        filename = blob_name.split('/')[-1]
        if filename.lower().endswith('.tif'):
            output_filename = f"{filename[:-4]}_cog.tif"
        else:
            output_filename = f"{filename}_cog.tif"

        output_folder = job_params.get('output_folder')
        output_blob = f"{output_folder}/{output_filename}" if output_folder else output_filename

        # Resolve defaults from config
        target_crs = job_params.get('target_crs') or config.raster.target_crs
        jpeg_quality = job_params.get('jpeg_quality') or config.raster.cog_jpeg_quality
        collection_id = job_params['collection_id']  # Required (14 JAN 2026)

        return [{
            'task_id': generate_deterministic_task_id(job_id, 1, "process_complete"),
            'task_type': 'raster_process_complete',
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
                'output_blob_name': output_blob,
                'output_tier': job_params.get('output_tier', 'analysis'),
                'jpeg_quality': jpeg_quality,
                'overview_resampling': config.raster.overview_resampling,
                'reproject_resampling': config.raster.reproject_resampling,

                # Behavior
                'strict_mode': job_params.get('strict_mode', False),

                # STAC
                'collection_id': collection_id,
                'item_id': job_params.get('stac_item_id') or job_params.get('item_id'),

                # Platform passthrough
                'dataset_id': job_params.get('dataset_id'),
                'resource_id': job_params.get('resource_id'),
                'version_id': job_params.get('version_id'),
                'access_level': job_params.get('access_level'),

                # Docker-specific
                'use_windowed_read': job_params.get('use_windowed_read', True),
                'chunk_size_mb': job_params.get('chunk_size_mb', 256),
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
                "job_type": "process_raster_docker",
                "success": False,
                "error": "No task results available"
            }

        task = task_results[0]
        result_data = task.result_data or {}

        # Unwrap the 'result' key - handlers return {"success": bool, "result": {...}}
        unwrapped = result_data.get('result', {})

        # Extract sub-results from unwrapped data
        validation = unwrapped.get('validation', {})
        cog = unwrapped.get('cog', {})
        stac = unwrapped.get('stac', {})
        resources = unwrapped.get('resources', {})
        artifact_id = unwrapped.get('artifact_id')  # Artifact registry (21 JAN 2026)

        # Generate TiTiler URLs if we have COG info
        titiler_urls = None
        share_url = None
        if cog.get('cog_blob') and cog.get('cog_container'):
            try:
                titiler_urls = config.generate_titiler_urls_unified(
                    mode="cog",
                    container=cog['cog_container'],
                    blob_name=cog['cog_blob']
                )
                share_url = titiler_urls.get("viewer_url")

                # DEM-specific visualization
                if validation.get('raster_type') == 'dem' and share_url:
                    titiler_urls["dem_terrain_viewer"] = f"{share_url}&colormap_name=terrain"
                    share_url = titiler_urls["dem_terrain_viewer"]
            except Exception:
                pass

        # Generate STAC URLs if we have item info
        stac_urls = None
        if stac.get('item_id') and stac.get('collection_id'):
            stac_base = config.stac_api_base_url.rstrip('/')
            stac_urls = {
                "item_url": f"{stac_base}/collections/{stac['collection_id']}/items/{stac['item_id']}",
                "collection_url": f"{stac_base}/collections/{stac['collection_id']}",
            }

        return {
            "job_type": "process_raster_docker",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container_name"),
            "validation": validation,
            "cog": cog,
            "stac": stac,
            "stac_urls": stac_urls,
            "titiler_urls": titiler_urls,
            "share_url": share_url,
            "artifact_id": artifact_id,  # Artifact registry (21 JAN 2026)
            "resources": resources,  # F7.20 resource metrics
            "processing_mode": "docker_single_stage",
            "stages_completed": 1,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
