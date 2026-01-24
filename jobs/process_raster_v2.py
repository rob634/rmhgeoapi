# ============================================================================
# PROCESS RASTER V2 JOB
# ============================================================================
# STATUS: Jobs - DEPRECATED (V0.8 - 24 JAN 2026)
# PURPOSE: Process small rasters to COG + STAC metadata (Function App)
# LAST_REVIEWED: 24 JAN 2026
# DEPRECATED: Use process_raster_docker instead
# ============================================================================
"""
Process Raster V2 - Function App Raster Pipeline.

⚠️ DEPRECATED (V0.8 - 24 JAN 2026)
This job runs on Function App and is deprecated. Use `process_raster_docker`
instead, which runs on Docker worker and handles all raster sizes.

V0.8 Architecture:
    - ALL raster processing goes to Docker worker
    - Docker has no timeout limits (Function App has 10-min limit)
    - process_raster_docker handles both single COG and tiled output
    - This job is kept for backward compatibility during migration

Migration:
    OLD: job_type="process_raster_v2"
    NEW: job_type="process_raster_docker" (same parameters)

Exports:
    ProcessRasterV2Job: DEPRECATED - use ProcessRasterDockerJob
"""

from typing import Dict, Any, List, Optional
from jobs.base import JobBase
from jobs.mixins import JobBaseMixin


class ProcessRasterV2Job(JobBaseMixin, JobBase):
    """
    Function App raster processing - DEPRECATED (V0.8).

    ⚠️ DEPRECATED: Use process_raster_docker instead.
    This job is kept for backward compatibility during migration.

    V0.8 Architecture (24 JAN 2026):
        - process_raster_docker is the primary raster workflow
        - It runs on Docker worker with no timeout limits
        - This Function App job will be removed in a future version
    """

    job_type = "process_raster_v2"
    description = "DEPRECATED: Use process_raster_docker instead"

    @classmethod
    def validate_parameters(cls, params):
        """Log deprecation warning before processing."""
        import logging
        import warnings
        logger = logging.getLogger(__name__)

        # Log deprecation warning
        logger.warning("=" * 60)
        logger.warning("⚠️ DEPRECATED: process_raster_v2")
        logger.warning("  This job type is deprecated as of V0.8 (24 JAN 2026)")
        logger.warning("  Use 'process_raster_docker' instead")
        logger.warning("  Docker worker has no timeout and handles all sizes")
        logger.warning("=" * 60)

        # Also issue Python deprecation warning
        warnings.warn(
            "process_raster_v2 is deprecated. "
            "Use process_raster_docker instead - it runs on Docker with no timeout.",
            DeprecationWarning,
            stacklevel=2
        )

        # Call parent validation
        return super().validate_parameters(params)

    stages = [
        {"number": 1, "name": "validate", "task_type": "raster_validate", "parallelism": "single"},
        {"number": 2, "name": "create_cog", "task_type": "raster_create_cog", "parallelism": "single"},
        {"number": 3, "name": "create_stac", "task_type": "raster_extract_stac_metadata", "parallelism": "single"}
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
        'collection_id': {'type': 'str', 'required': True},  # Must specify target collection
        'item_id': {'type': 'str', 'default': None},
        'collection_must_exist': {'type': 'bool', 'default': False},  # Fail if collection doesn't exist (12 JAN 2026)

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
    # V0.8 (24 JAN 2026): Removed size limit - all sizes go to Docker
    # This validator just checks blob exists and stores size for informational purposes
    resource_validators = [
        {
            'type': 'blob_exists_with_size',
            'container_param': 'container_name',
            'blob_param': 'blob_name',
            # V0.8: No max_size_env - Docker handles all sizes
            'error_not_found': 'Source raster file does not exist. Verify blob_name and container_name.',
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
            # Use Bronze zone for input rasters (08 DEC 2025)
            blob_repo = BlobRepository.for_zone("bronze")
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=job_params['container_name'],
                blob_name=job_params['blob_name'],
                hours=1
            )

            return [{
                'task_id': generate_deterministic_task_id(job_id, 1, "validate"),
                'task_type': 'raster_validate',
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
                'task_type': 'raster_create_cog',
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
                    # in_memory: Automatic based on file size (29 NOV 2025)
                    # Priority: 1) explicit job param, 2) size-based auto, 3) config default
                    'in_memory': ProcessRasterV2Job._resolve_in_memory(job_params, config),
                }
            }]

        elif stage == 3:
            # Stage 3: Create STAC (requires Stage 2 results)
            if not previous_results or not previous_results[0].get('success'):
                error = previous_results[0].get('error') if previous_results else 'No results'
                raise ValueError(f"Stage 2 failed: {error}")

            cog_result = previous_results[0].get('result', {})
            cog_blob = cog_result.get('output_blob') or cog_result.get('cog_blob')
            # Modern pattern (30 NOV 2025): config.storage.silver.cogs
            cog_container = cog_result.get('cog_container') or config.storage.silver.cogs

            if not cog_blob:
                raise ValueError("Stage 2 missing COG blob path")

            # collection_id is required (14 JAN 2026) - no more system-rasters fallback
            collection_id = job_params['collection_id']

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
                # Raster visualization metadata (01 JAN 2026) - for DEM colormap in STAC preview
                'raster_type': cog_result.get('raster_type'),
                # STAC file extension (21 JAN 2026) - checksum from COG creation
                'file_checksum': cog_result.get('file_checksum'),
                'file_size': cog_result.get('file_size'),
            }
            if stac_item_id:
                task_params['item_id'] = stac_item_id

            return [{
                'task_id': generate_deterministic_task_id(job_id, 3, "stac"),
                'task_type': 'raster_extract_stac_metadata',
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
        stage_1 = [t for t in task_results if t.task_type == "raster_validate"]
        stage_2 = [t for t in task_results if t.task_type == "raster_create_cog"]
        stage_3 = [t for t in task_results if t.task_type == "raster_extract_stac_metadata"]

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
                "processing_time_seconds": c.get("processing_time_seconds"),
                # STAC file extension compliant (21 JAN 2026)
                "file_checksum": c.get("file_checksum"),
                "file_size": c.get("file_size"),
            }

        # Build STAC summary and TiTiler URLs (with degraded mode detection - 6 DEC 2025)
        stac_summary = {}
        stac_urls = None
        titiler_urls = None
        app_urls = None  # App viewer URLs (30 DEC 2025)
        share_url = None
        degraded_mode = False
        degraded_warnings = []

        if stage_3 and stage_3[0].result_data:
            stac_data = stage_3[0].result_data
            s = stac_data.get("result", {})

            # Check for degraded mode (pgSTAC unavailable)
            if stac_data.get("degraded"):
                degraded_mode = True
                degraded_warnings.append(stac_data.get("warning", "STAC cataloging skipped"))
                stac_summary = {
                    "degraded": True,
                    "stac_item_created": True,  # JSON always created now!
                    "stac_item_json_blob": s.get("stac_item_json_blob"),
                    "stac_item_json_url": s.get("stac_item_json_url"),
                    "inserted_to_pgstac": False,
                    "titiler_available": True,
                    "degraded_reason": s.get("degraded_reason") or "pgSTAC unavailable - JSON fallback is authoritative"
                }
            else:
                item_id = s.get("item_id")
                collection_id = s.get("collection_id")

                stac_summary = {
                    "item_id": item_id,
                    "collection_id": collection_id,
                    "bbox": s.get("bbox"),
                    "stac_item_json_blob": s.get("stac_item_json_blob"),
                    "stac_item_json_url": s.get("stac_item_json_url"),
                    "inserted_to_pgstac": s.get("inserted_to_pgstac", True)
                }

                # Generate STAC API URLs (uses OGC_STAC_APP_URL from config)
                # Only when STAC is not in degraded mode
                if item_id and collection_id:
                    stac_base = config.stac_api_base_url.rstrip('/')
                    stac_urls = {
                        "item_url": f"{stac_base}/collections/{collection_id}/items/{item_id}",
                        "collection_url": f"{stac_base}/collections/{collection_id}",
                        "items_url": f"{stac_base}/collections/{collection_id}/items",
                        "catalog_url": stac_base
                    }

                    # Generate App URLs for viewers (30 DEC 2025)
                    # Uses ETL_APP_URL from config for the raster collection viewer
                    etl_base = config.etl_app_base_url.rstrip('/')
                    app_urls = {
                        "collection_viewer": f"{etl_base}/api/raster/viewer?collection={collection_id}",
                        "item_viewer": f"{etl_base}/api/raster/viewer?collection={collection_id}&item={item_id}"
                    }

        # Generate TiTiler URLs regardless of STAC status (works in degraded mode)
        if cog_summary.get('cog_blob') and cog_summary.get('cog_container'):
            try:
                titiler_urls = config.generate_titiler_urls_unified(
                    mode="cog",
                    container=cog_summary['cog_container'],
                    blob_name=cog_summary['cog_blob']
                )
                share_url = titiler_urls.get("viewer_url")

                # Add DEM-specific visualization URLs with terrain colormap
                detected_type = validation_summary.get("raster_type")
                if detected_type == "dem" and titiler_urls.get("viewer_url"):
                    base_url = titiler_urls["viewer_url"]
                    # Add terrain visualization URLs (rescale will be auto from statistics endpoint)
                    titiler_urls["dem_terrain_viewer"] = f"{base_url}&colormap_name=terrain"
                    titiler_urls["dem_viridis_viewer"] = f"{base_url}&colormap_name=viridis"
                    titiler_urls["dem_gist_earth_viewer"] = f"{base_url}&colormap_name=gist_earth"

                    # Set share_url to terrain colormap for DEMs
                    share_url = titiler_urls["dem_terrain_viewer"]

                    # Add preview URLs with colormaps
                    if titiler_urls.get("preview_url"):
                        preview_base = titiler_urls["preview_url"]
                        titiler_urls["dem_terrain_preview"] = f"{preview_base}&colormap_name=terrain"
                        titiler_urls["dem_hillshade_note"] = "Use TiTiler /cog/DEM endpoint for hillshade"

            except Exception:
                pass

        # =====================================================================
        # ARTIFACT REGISTRY (21 JAN 2026)
        # =====================================================================
        # Create artifact record for lineage tracking with checksum
        artifact_id = None
        try:
            from services.artifact_service import ArtifactService

            # Build client_refs from platform parameters
            client_refs = {}
            if params.get('dataset_id'):
                client_refs['dataset_id'] = params['dataset_id']
            if params.get('resource_id'):
                client_refs['resource_id'] = params['resource_id']
            if params.get('version_id'):
                client_refs['version_id'] = params['version_id']

            # Only create artifact if we have client refs (platform job)
            if client_refs and cog_summary.get('cog_blob'):
                artifact_service = ArtifactService()
                artifact = artifact_service.create_artifact(
                    storage_account=config.storage.silver.account_name,
                    container=cog_summary.get('cog_container'),
                    blob_path=cog_summary.get('cog_blob'),
                    client_type='ddh',  # Platform client type
                    client_refs=client_refs,
                    stac_collection_id=stac_summary.get('collection_id'),
                    stac_item_id=stac_summary.get('item_id'),
                    source_job_id=context.job_id,
                    source_task_id=None,  # Multi-stage job, no single task
                    content_hash=cog_summary.get('file_checksum'),
                    size_bytes=cog_summary.get('file_size'),
                    content_type='image/tiff; application=geotiff; profile=cloud-optimized',
                    metadata={
                        'compression': cog_summary.get('compression'),
                        'raster_type': validation_summary.get('raster_type'),
                    },
                    overwrite=True  # Platform jobs always overwrite
                )
                artifact_id = str(artifact.artifact_id)
                logger.info(f"📦 Artifact created: {artifact_id} (revision {artifact.revision})")
            else:
                logger.debug("Skipping artifact creation - no client_refs or cog_blob")
        except Exception as e:
            # Artifact creation is non-fatal - log warning but continue
            logger.warning(f"⚠️ Artifact creation failed (non-fatal): {e}")

        # Build result with degraded mode info if applicable (6 DEC 2025)
        result = {
            "job_type": "process_raster_v2",
            "source_blob": params.get("blob_name"),
            "source_container": params.get("container_name"),
            "validation": validation_summary,
            "cog": cog_summary,
            "stac": stac_summary,
            "stac_urls": stac_urls,
            "titiler_urls": titiler_urls,
            "app_urls": app_urls,  # Raster collection viewer URLs (30 DEC 2025)
            "share_url": share_url,
            "artifact_id": artifact_id,  # Artifact registry (21 JAN 2026)
            "stages_completed": context.current_stage,
            "total_tasks_executed": len(task_results),
            "tasks_by_status": {
                "completed": sum(1 for t in task_results if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in task_results if t.status == TaskStatus.FAILED)
            }
        }

        # Add degraded mode info if applicable (6 DEC 2025)
        if degraded_mode:
            result["degraded_mode"] = True
            result["warnings"] = degraded_warnings
            result["available_capabilities"] = ["TiTiler COG viewing", "COG tile serving"]
            result["unavailable_capabilities"] = ["STAC API discovery"]

        return result

    @staticmethod
    def _resolve_in_memory(job_params: Dict[str, Any], config) -> bool:
        """
        Resolve in_memory setting for COG creation.

        Priority:
        1. Explicit job parameter (user override)
        2. Config default (raster.cog_in_memory, default: False)

        Simplified (23 DEC 2025):
        - Removed size-based auto-selection (was based on removed raster_in_memory_threshold_mb)
        - in_memory=False (disk-based /tmp) is safer with concurrency
        - User can override per-job if needed for testing
        """
        # Priority 1: Explicit job parameter
        if job_params.get('in_memory') is not None:
            return job_params['in_memory']

        # Priority 2: Config default (False = disk-based, safer)
        return config.raster.cog_in_memory
