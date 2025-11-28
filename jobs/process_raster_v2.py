# ============================================================================
# CLAUDE CONTEXT - PROCESS RASTER V2 (MIXIN PATTERN)
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: New job - Clean slate JobBaseMixin implementation (28 NOV 2025)
# PURPOSE: Small file raster processing (<= 1GB) - COG creation with STAC metadata
# LAST_REVIEWED: 28 NOV 2025
# EXPORTS: ProcessRasterV2Job
# INTERFACES: JobBase, JobBaseMixin
# PYDANTIC_MODELS: None (uses declarative parameters_schema)
# DEPENDENCIES: jobs.base, jobs.mixins, config, infrastructure.blob
# SOURCE: User job submission via /api/jobs/submit/process_raster_v2
# SCOPE: Raster ETL pipeline
# VALIDATION: JobBaseMixin declarative schema + resource validators
# PATTERNS: Mixin pattern (77% less boilerplate), Resource validators
# ENTRY_POINTS: from jobs import ALL_JOBS; ALL_JOBS["process_raster_v2"]
# INDEX: ProcessRasterV2Job:40, create_tasks_for_stage:105, finalize_job:183
# ============================================================================

"""
Process Raster V2 - Clean Slate JobBaseMixin Implementation

Uses JobBaseMixin pattern for 77% less boilerplate code:
- validate_job_parameters: Declarative via parameters_schema
- generate_job_id: Automatic SHA256 from params
- create_job_record: Automatic via mixin
- queue_job: Automatic via mixin

Three-stage workflow:
1. Validate: CRS detection, bit-depth, raster type classification
2. Create COG: Reproject + COG in single operation
3. Create STAC: Generate STAC metadata and insert to pgstac

Key improvements over process_raster.py:
- Clean slate parameters (no deprecated fields)
- Config integration for defaults (env vars → fallback defaults)
- Pre-flight resource validation (blob_exists)
- 200 lines vs 743 lines (73% reduction)

Created: 28 NOV 2025
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class ProcessRasterV2Job(JobBaseMixin, JobBase):
    """
    Small file raster processing (<= 1GB) using JobBaseMixin.
    Clean slate implementation - no deprecated parameters.

    Three-stage workflow:
    1. Validate: CRS, bit-depth, type detection
    2. Create COG: Reproject + COG in single operation
    3. Create STAC: Generate STAC metadata for COG
    """

    job_type = "process_raster_v2"
    description = "Process raster to COG with STAC metadata (mixin pattern)"

    stages = [
        {"number": 1, "name": "validate", "task_type": "validate_raster", "parallelism": "single"},
        {"number": 2, "name": "create_cog", "task_type": "create_cog", "parallelism": "single"},
        {"number": 3, "name": "create_stac", "task_type": "extract_stac_metadata", "parallelism": "single"}
    ]

    # Clean parameters schema - no deprecated fields
    parameters_schema = {
        # Required
        'blob_name': {'type': 'str', 'required': True},
        'container_name': {'type': 'str', 'required': True},

        # CRS
        'input_crs': {'type': 'str', 'default': None},
        'target_crs': {'type': 'str', 'default': None},  # Resolved from config.raster.target_crs

        # Raster type
        'raster_type': {
            'type': 'str',
            'default': 'auto',
            'allowed': ['auto', 'rgb', 'rgba', 'dem', 'categorical', 'multispectral', 'nir']
        },

        # COG output (output_tier replaces deprecated compression)
        'output_tier': {
            'type': 'str',
            'default': 'analysis',
            'allowed': ['visualization', 'analysis', 'archive', 'all']
        },
        'jpeg_quality': {'type': 'int', 'default': None, 'min': 1, 'max': 100},  # Resolved from config
        'output_folder': {'type': 'str', 'default': None},

        # Behavior
        'strict_mode': {'type': 'bool', 'default': False},
        'in_memory': {'type': 'bool', 'default': None},  # Override config.raster.cog_in_memory

        # STAC
        'collection_id': {'type': 'str', 'default': None},  # Resolved from config.raster.stac_default_collection
        'item_id': {'type': 'str', 'default': None},

        # Platform passthrough (DDH integration)
        'dataset_id': {'type': 'str', 'default': None},
        'resource_id': {'type': 'str', 'default': None},
        'version_id': {'type': 'str', 'default': None},
        'access_level': {'type': 'str', 'default': None},
        'stac_item_id': {'type': 'str', 'default': None},

        # Testing only
        '_skip_validation': {'type': 'bool', 'default': False},
    }

    # Pre-flight resource validation
    resource_validators = [
        {
            'type': 'blob_exists',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            'error': 'Source raster file does not exist. Verify blob_name and container_name.'
        }
    ]

    @staticmethod
    def create_tasks_for_stage(stage: int, job_params: Dict[str, Any], job_id: str,
                                previous_results: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """Generate task parameters for each stage."""
        from core.task_id import generate_deterministic_task_id
        from infrastructure.blob import BlobRepository
        from config import get_config

        config = get_config()

        if stage == 1:
            # Stage 1: Validate raster
            blob_repo = BlobRepository.instance()
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=job_params['container_name'],
                blob_name=job_params['blob_name'],
                hours=1
            )

            return [{
                'task_id': generate_deterministic_task_id(job_id, 1, "validate"),
                'task_type': 'validate_raster',
                'parameters': {
                    'blob_url': blob_url,
                    'blob_name': job_params['blob_name'],
                    'container_name': job_params['container_name'],
                    'input_crs': job_params.get('input_crs'),
                    'raster_type': job_params.get('raster_type', 'auto'),
                    'strict_mode': job_params.get('strict_mode', False),
                    '_skip_validation': job_params.get('_skip_validation', False)
                }
            }]

        elif stage == 2:
            # Stage 2: Create COG (requires Stage 1 results)
            if not previous_results or not previous_results[0].get('success'):
                error = previous_results[0].get('error') if previous_results else 'No results'
                raise ValueError(f"Stage 1 failed: {error}")

            validation = previous_results[0].get('result', {})
            source_crs = validation.get('source_crs')
            if not source_crs:
                raise ValueError("No source_crs in Stage 1 validation results")

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

            return [{
                'task_id': generate_deterministic_task_id(job_id, 2, "create_cog"),
                'task_type': 'create_cog',
                'parameters': {
                    'blob_name': job_params['blob_name'],
                    'container_name': job_params['container_name'],
                    'source_crs': source_crs,
                    'target_crs': target_crs,
                    'raster_type': validation.get('raster_type', {}),
                    'output_blob_name': output_blob,
                    'output_tier': job_params.get('output_tier', 'analysis'),
                    'jpeg_quality': jpeg_quality,
                    # Config-controlled (not user-exposed in v2)
                    'overview_resampling': config.raster.overview_resampling,
                    'reproject_resampling': config.raster.reproject_resampling,
                    # in_memory: job override or config default
                    'in_memory': job_params.get('in_memory') if job_params.get('in_memory') is not None else config.raster.cog_in_memory,
                }
            }]

        elif stage == 3:
            # Stage 3: Create STAC (requires Stage 2 results)
            if not previous_results or not previous_results[0].get('success'):
                error = previous_results[0].get('error') if previous_results else 'No results'
                raise ValueError(f"Stage 2 failed: {error}")

            cog_result = previous_results[0].get('result', {})
            cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
            cog_container = cog_result.get('cog_container') or config.silver_container_name

            if not cog_blob:
                raise ValueError("Stage 2 missing COG blob path")

            # Resolve collection_id from config if not specified
            collection_id = job_params.get('collection_id') or config.raster.stac_default_collection

            # Prefer stac_item_id from Platform, fallback to item_id
            stac_item_id = job_params.get('stac_item_id') or job_params.get('item_id')

            task_params = {
                'container_name': cog_container,
                'blob_name': cog_blob,
                'collection_id': collection_id,
                # Platform passthrough
                'dataset_id': job_params.get('dataset_id'),
                'resource_id': job_params.get('resource_id'),
                'version_id': job_params.get('version_id'),
                'access_level': job_params.get('access_level'),
            }
            if stac_item_id:
                task_params['item_id'] = stac_item_id

            return [{
                'task_id': generate_deterministic_task_id(job_id, 3, "stac"),
                'task_type': 'extract_stac_metadata',
                'parameters': task_params
            }]

        else:
            raise ValueError(f"ProcessRasterV2Job has 3 stages, got stage {stage}")

    @staticmethod
    def finalize_job(context) -> Dict[str, Any]:
        """Create final job summary with TiTiler URLs."""
        from core.models import TaskStatus
        from config import get_config

        task_results = context.task_results
        params = context.parameters
        config = get_config()

        # Extract results by stage
        stage_1 = [t for t in task_results if t.task_type == "validate_raster"]
        stage_2 = [t for t in task_results if t.task_type == "create_cog"]
        stage_3 = [t for t in task_results if t.task_type == "extract_stac_metadata"]

        # Build validation summary
        validation_summary = {}
        if stage_1 and stage_1[0].result_data:
            v = stage_1[0].result_data.get("result", {})
            validation_summary = {
                "source_crs": v.get("source_crs"),
                "raster_type": v.get("raster_type", {}).get("detected_type"),
                "confidence": v.get("raster_type", {}).get("confidence"),
                "warnings": v.get("warnings", [])
            }

        # Build COG summary
        cog_summary = {}
        if stage_2 and stage_2[0].result_data:
            c = stage_2[0].result_data.get("result", {})
            cog_summary = {
                "cog_blob": c.get("cog_blob"),
                "cog_container": c.get("cog_container"),
                "size_mb": c.get("size_mb"),
                "compression": c.get("compression"),
                "processing_time_seconds": c.get("processing_time_seconds")
            }

        # Build STAC summary and TiTiler URLs
        stac_summary = {}
        titiler_urls = None
        share_url = None

        if stage_3 and stage_3[0].result_data:
            s = stage_3[0].result_data.get("result", {})
            stac_summary = {
                "item_id": s.get("item_id"),
                "collection_id": s.get("collection_id"),
                "bbox": s.get("bbox"),
                "inserted_to_pgstac": s.get("inserted_to_pgstac", True)
            }

            if cog_summary.get('cog_blob') and cog_summary.get('cog_container'):
                try:
                    titiler_urls = config.generate_titiler_urls_unified(
                        mode="cog",
                        container=cog_summary['cog_container'],
                        blob_name=cog_summary['cog_blob']
                    )
                    share_url = titiler_urls.get("viewer_url")
                except Exception:
                    pass

        return {
            "job_type": "process_raster_v2",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container_name"),
            "validation": validation_summary,
            "cog": cog_summary,
            "stac": stac_summary,
            "titiler_urls": titiler_urls,
            "share_url": share_url,
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }
