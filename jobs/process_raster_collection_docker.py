# ============================================================================
# PROCESS RASTER COLLECTION DOCKER JOB
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Jobs - Single-stage raster collection to COGs pipeline for Docker
# PURPOSE: Process multiple rasters to COGs in Docker (no timeout constraints)
# CREATED: 30 JAN 2026
# EXPORTS: ProcessRasterCollectionDockerJob
# DEPENDENCIES: jobs.base, jobs.mixins, infrastructure.blob
# ============================================================================
"""
Process Raster Collection Docker - Sequential Checkpoint-Based Job.

Processes a collection of raster files into COGs with STAC registration.
Designed for Docker worker where there are no timeout constraints.

Architecture:
    - Single stage with internal phases (checkpoint-based)
    - Downloads all source files to temp storage first (avoids OOM)
    - Sequential COG creation with per-file checkpoints
    - STAC collection creation at end (same as tiled mode)

Phases (within single stage):
    1. Download: Copy all blobs from bronze → temp mount storage
    2. COG Creation: Sequential processing with per-file checkpoints
    3. STAC: Create collection and register items (direct call mode)
    4. Cleanup: Remove temp files

Input/Output:
    - N GeoTIFFs in → N COGs out (one-to-one mapping)
    - All COGs registered in single STAC collection

JobEvents:
    - Emits checkpoint events for execution timeline visibility
    - Enables "last successful step" debugging

Exports:
    ProcessRasterCollectionDockerJob: Single-stage Docker collection job
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class ProcessRasterCollectionDockerJob(JobBaseMixin, JobBase):
    """
    Docker raster collection processing - single stage, checkpoint-based.

    Processes multiple source rasters into COGs with STAC registration.
    Uses sequential processing with checkpoints for resume capability.
    """

    job_type = "process_raster_collection_docker"
    description = "Process raster collection to COGs (Docker - sequential, checkpoint-based)"

    # Declarative ETL linkage - which unpublish job reverses this workflow
    reversed_by = "unpublish_raster"

    # Single stage - handler manages phases internally
    stages = [
        {
            "number": 1,
            "name": "process_collection",
            "task_type": "raster_collection_complete",
            "parallelism": "single"
        }
    ]

    parameters_schema = {
        # Required - Collection source
        'blob_list': {'type': 'list', 'required': True},
        'container_name': {'type': 'str', 'required': True},

        # Required - STAC
        'collection_id': {'type': 'str', 'required': True},

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

        # STAC metadata
        'collection_title': {'type': 'str', 'default': None},
        'collection_description': {'type': 'str', 'default': None},
        'license': {'type': 'str', 'default': 'proprietary'},

        # Platform passthrough (DDH integration)
        'dataset_id': {'type': 'str', 'default': None},
        'resource_id': {'type': 'str', 'default': None},
        'version_id': {'type': 'str', 'default': None},
        'access_level': {'type': 'str', 'default': None},

        # Docker-specific options
        'use_mount_storage': {'type': 'bool', 'default': True},  # Use mounted temp storage
        'cleanup_temp': {'type': 'bool', 'default': True},  # Delete temp files after

        # Behavior
        'strict_mode': {'type': 'bool', 'default': False},
    }

    # Pre-flight validation - all blobs must exist
    resource_validators = [
        {
            'type': 'container_exists',
            'container_param': 'container_name',
            'error': 'Source container does not exist'
        },
        {
            'type': 'blob_list_exists_with_max_size',
            'container_param': 'container_name',
            'blob_list_param': 'blob_list',
            'parallel': True,
            'max_parallel': 10,
            'report_all': True,
            'min_count': 1,
            'error_not_found': 'One or more rasters not found in collection. Verify blob paths.',
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: Dict[str, Any], job_id: str,
                                previous_results: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """Generate single task for the collection processing stage."""
        from core.task_id import generate_deterministic_task_id
        from config import get_config

        config = get_config()

        if stage != 1:
            raise ValueError(f"ProcessRasterCollectionDockerJob has 1 stage, got stage {stage}")

        # Resolve defaults from config
        target_crs = job_params.get('target_crs') or config.raster.target_crs
        jpeg_quality = job_params.get('jpeg_quality') or config.raster.cog_jpeg_quality
        collection_id = job_params['collection_id']

        # Generate output folder based on job_id if not provided
        output_folder = job_params.get('output_folder') or f"{job_id[:8]}"

        return [{
            'task_id': generate_deterministic_task_id(job_id, 1, "process_collection"),
            'task_type': 'raster_collection_complete',
            'parameters': {
                # Source collection
                'blob_list': job_params['blob_list'],
                'container_name': job_params['container_name'],

                # CRS
                'input_crs': job_params.get('input_crs'),
                'target_crs': target_crs,

                # Raster type
                'raster_type': job_params.get('raster_type', 'auto'),

                # COG output
                'output_folder': output_folder,
                'output_tier': job_params.get('output_tier', 'analysis'),
                'jpeg_quality': jpeg_quality,
                'overview_resampling': config.raster.overview_resampling,
                'reproject_resampling': config.raster.reproject_resampling,

                # STAC
                'collection_id': collection_id,
                'collection_title': job_params.get('collection_title') or f"Collection: {collection_id}",
                'collection_description': job_params.get('collection_description') or f"Raster collection: {collection_id}",
                'license': job_params.get('license', 'proprietary'),

                # Platform passthrough
                'dataset_id': job_params.get('dataset_id'),
                'resource_id': job_params.get('resource_id'),
                'version_id': job_params.get('version_id'),
                'access_level': job_params.get('access_level'),

                # Docker options
                'use_mount_storage': job_params.get('use_mount_storage', True),
                'cleanup_temp': job_params.get('cleanup_temp', True),

                # Behavior
                'strict_mode': job_params.get('strict_mode', False),
            }
        }]

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """
        Create final job summary from the single stage result.

        Formats the collection processing result for API response.
        """
        from core.models import TaskStatus
        from config import get_config

        task_results = context.task_results
        params = context.parameters
        config = get_config()

        # Get the single task result
        if not task_results:
            return {
                "job_type": "process_raster_collection_docker",
                "success": False,
                "error": "No task results available"
            }

        task = task_results[0]
        result_data = task.result_data or {}

        # Unwrap the 'result' key - handlers return {"success": bool, "result": {...}}
        unwrapped = result_data.get('result', {})

        # Extract key results
        download = unwrapped.get('download', {})
        cogs = unwrapped.get('cogs', {})
        stac = unwrapped.get('stac', {})
        timing = unwrapped.get('timing', {})

        # Generate STAC URLs if we have collection info
        stac_urls = None
        if stac.get('collection_id'):
            stac_base = config.stac_api_base_url.rstrip('/')
            stac_urls = {
                "collection_url": f"{stac_base}/collections/{stac['collection_id']}",
                "items_url": f"{stac_base}/collections/{stac['collection_id']}/items",
            }

        return {
            "job_type": "process_raster_collection_docker",
            "source_container": params.get("container_name"),
            "source_count": len(params.get("blob_list", [])),
            "download": download,
            "cogs": cogs,
            "stac": stac,
            "stac_urls": stac_urls,
            "timing": timing,
            "processing_mode": "docker_collection_sequential",
            "stages_completed": 1,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
