# ============================================================================
# CLAUDE CONTEXT - RASTER MIXIN (SHARED INFRASTRUCTURE)
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: New infrastructure - Shared schemas and helpers for raster workflows
# PURPOSE: DRY principle - Extract common raster workflow patterns for extensibility
# LAST_REVIEWED: 30 NOV 2025
# EXPORTS: RasterMixin
# INTERFACES: Mixin pattern - provides schemas and static helpers
# PYDANTIC_MODELS: None (uses declarative parameters_schema dicts)
# DEPENDENCIES: infrastructure.blob.BlobRepository, config
# SOURCE: Extracted from process_raster_v2, process_raster_collection patterns
# SCOPE: Shared across all raster processing workflows
# VALIDATION: Relies on JobBaseMixin for schema validation
# PATTERNS: Mixin pattern, DRY principle, Schema composition
# ENTRY_POINTS: Inherited by raster workflow classes
# INDEX:
#   - COMMON_RASTER_SCHEMA: line 50
#   - MOSAICJSON_SCHEMA: line 70
#   - PLATFORM_PASSTHROUGH_SCHEMA: line 85
#   - VALIDATION_BYPASS_SCHEMA: line 95
#   - _resolve_raster_config: line 105
#   - _create_validation_tasks: line 130
#   - _create_cog_tasks: line 180
# ============================================================================

"""
RasterMixin - Shared Infrastructure for Raster Workflows

This mixin provides shared parameter schemas and helper methods for all raster
processing workflows. Designed for extensibility - new raster jobs inherit
common patterns while customizing stage-specific logic.

Used by:
- ProcessRasterV2Job (single file, 3 stages)
- ProcessRasterCollectionV2Job (multi-tile, 4 stages)
- ProcessLargeRasterV2Job (large file tiling, 5 stages)
- Future raster workflows

Key Features:
- Schema composition with ** operator
- Static helper methods for fan-out task creation
- Config-aware default resolution
- Platform passthrough field support

Created: 30 NOV 2025
Author: Robert and Geospatial Claude Legion
"""

from typing import Dict, Any, List, Optional
from util_logger import LoggerFactory, ComponentType


class RasterMixin:
    """
    Mixin providing shared infrastructure for raster processing workflows.

    Designed for extensibility - new raster jobs inherit common patterns
    while customizing stage-specific logic.

    Usage:
        class MyRasterJob(RasterMixin, RasterWorkflowsBase, JobBaseMixin, JobBase):
            parameters_schema = {
                **RasterMixin.COMMON_RASTER_SCHEMA,
                **RasterMixin.MOSAICJSON_SCHEMA,  # If producing MosaicJSON
                'my_custom_param': {'type': 'str', 'required': True},
            }

    Inheritance Order (CRITICAL - Python MRO):
        RasterMixin, RasterWorkflowsBase, JobBaseMixin, JobBase
        - RasterMixin: Schema constants and helpers
        - RasterWorkflowsBase: Shared finalization logic
        - JobBaseMixin: Boilerplate elimination (4 methods)
        - JobBase: ABC interface enforcement
    """

    # =========================================================================
    # SHARED PARAMETER SCHEMAS
    # =========================================================================
    # These can be composed into job-specific schemas using ** operator:
    #   parameters_schema = {**COMMON_RASTER_SCHEMA, **MOSAICJSON_SCHEMA, ...}
    # =========================================================================

    # Common parameters shared by ALL raster processing jobs.
    # 8 fields covering input/output, CRS, compression, and behavior.
    COMMON_RASTER_SCHEMA = {
        'container_name': {'type': 'str', 'required': True},
        'raster_type': {
            'type': 'str',
            'default': 'auto',
            'allowed': ['auto', 'rgb', 'rgba', 'dem', 'categorical', 'multispectral', 'nir']
        },
        'output_tier': {
            'type': 'str',
            'default': 'analysis',
            'allowed': ['visualization', 'analysis', 'archive', 'all']
        },
        'output_folder': {'type': 'str', 'default': None},
        'output_container': {'type': 'str', 'default': None},
        'target_crs': {'type': 'str', 'default': None},  # Resolved from config.raster.target_crs
        'jpeg_quality': {'type': 'int', 'default': None, 'min': 1, 'max': 100},
        'in_memory': {'type': 'bool', 'default': None},
        'input_crs': {'type': 'str', 'default': None},
    }

    # Additional parameters for jobs that produce MosaicJSON output.
    # 6 fields for collection metadata and MosaicJSON configuration.
    MOSAICJSON_SCHEMA = {
        'collection_id': {'type': 'str', 'required': True},
        'collection_description': {'type': 'str', 'default': None},
        'maxzoom': {'type': 'int', 'default': None, 'min': 0, 'max': 24},
        'stac_item_id': {'type': 'str', 'default': None},
        'create_mosaicjson': {'type': 'bool', 'default': True},
        'create_stac_collection': {'type': 'bool', 'default': True},
    }

    # DDH Platform metadata fields passed through to STAC items.
    # These fields enable integration with the Data and Deployment Hub.
    PLATFORM_PASSTHROUGH_SCHEMA = {
        'dataset_id': {'type': 'str', 'default': None},
        'resource_id': {'type': 'str', 'default': None},
        'version_id': {'type': 'str', 'default': None},
        'access_level': {'type': 'str', 'default': None},
    }

    # Preflight validation bypass for trusted sources.
    # When _skip_blob_validation=True, blob existence checks are skipped.
    VALIDATION_BYPASS_SCHEMA = {
        '_skip_blob_validation': {'type': 'bool', 'default': False},
    }

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @staticmethod
    def _resolve_raster_config(job_params: Dict[str, Any], config) -> Dict[str, Any]:
        """
        Resolve None values from raster config defaults.

        Priority: explicit param > config default

        Args:
            job_params: Job parameters (may have None values)
            config: AppConfig instance

        Returns:
            Copy of job_params with None values resolved from config
        """
        resolved = dict(job_params)

        if resolved.get('target_crs') is None:
            resolved['target_crs'] = config.raster.target_crs

        if resolved.get('jpeg_quality') is None:
            resolved['jpeg_quality'] = config.raster.cog_jpeg_quality

        if resolved.get('maxzoom') is None:
            resolved['maxzoom'] = getattr(config.raster, 'default_maxzoom', 22)

        if resolved.get('output_container') is None:
            # Modern pattern (30 NOV 2025): config.storage.silver.cogs
            resolved['output_container'] = config.storage.silver.cogs

        return resolved

    @staticmethod
    def _create_validation_tasks(
        job_id: str,
        blob_list: List[str],
        container_name: str,
        job_params: Dict[str, Any],
        stage_num: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Generate N validation tasks for blob_list (fan-out pattern).

        Used by raster collection and large raster workflows to parallelize
        validation of multiple tiles/files.

        Args:
            job_id: Parent job ID
            blob_list: List of blob paths to validate
            container_name: Azure container name
            job_params: Full job parameters
            stage_num: Stage number for task ID generation

        Returns:
            List of task dicts ready for CoreMachine

        Example:
            tasks = RasterMixin._create_validation_tasks(
                job_id="abc123...",
                blob_list=["tile1.tif", "tile2.tif"],
                container_name="bronze-rasters",
                job_params=validated_params,
                stage_num=1
            )
        """
        from infrastructure.blob import BlobRepository

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "raster_mixin")

        tasks = []
        blob_repo = BlobRepository.instance()

        for i, blob_name in enumerate(blob_list):
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=blob_name,
                hours=1
            )
            tasks.append({
                "task_id": f"{job_id[:8]}-s{stage_num}-validate-{i}",
                "task_type": "validate_raster",
                "parameters": {
                    "blob_url": blob_url,
                    "blob_name": blob_name,
                    "container_name": container_name,
                    "input_crs": job_params.get("input_crs"),
                    "raster_type": job_params.get("raster_type", "auto"),
                    "strict_mode": False
                },
                "metadata": {
                    "tile_index": i,
                    "tile_count": len(blob_list)
                }
            })

        logger.debug(f"Created {len(tasks)} validation tasks for stage {stage_num}")
        return tasks

    @staticmethod
    def _create_cog_tasks(
        job_id: str,
        validation_results: List[Dict[str, Any]],
        blob_list: List[str],
        job_params: Dict[str, Any],
        stage_num: int = 2,
        container_override: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate N COG creation tasks from validation results (fan-out pattern).

        Used by raster collection and large raster workflows to parallelize
        COG creation for multiple tiles/files.

        Args:
            job_id: Parent job ID
            validation_results: Results from validation stage (must match blob_list order)
            blob_list: List of blob paths
            job_params: Full job parameters
            stage_num: Stage number for task ID generation
            container_override: Override container for intermediate tiles (large raster)

        Returns:
            List of task dicts ready for CoreMachine

        Raises:
            ValueError: If validation failures exist or source_crs missing

        Example:
            tasks = RasterMixin._create_cog_tasks(
                job_id="abc123...",
                validation_results=stage1_results,
                blob_list=["tile1.tif", "tile2.tif"],
                job_params=validated_params,
                stage_num=2
            )
        """
        from pathlib import Path
        from config import get_config

        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "raster_mixin")
        config = get_config()

        # Check for validation failures
        failed = [r for r in validation_results if not r.get("success")]
        if failed:
            failed_count = len(failed)
            raise ValueError(f"{failed_count} tiles failed validation - cannot proceed to COG creation")

        tasks = []
        container = container_override or job_params["container_name"]
        # Modern pattern (30 NOV 2025): config.storage.silver.cogs
        output_container = job_params.get("output_container") or config.storage.silver.cogs

        # Resolve config defaults
        target_crs = job_params.get("target_crs") or config.raster.target_crs
        jpeg_quality = job_params.get("jpeg_quality") or config.raster.cog_jpeg_quality

        for i, blob_name in enumerate(blob_list):
            validation_result = validation_results[i].get("result", {})
            source_crs = validation_result.get("source_crs")

            if not source_crs:
                raise ValueError(f"No source_crs for blob {blob_name} (index {i})")

            # Generate output blob name
            tile_name = Path(blob_name).stem
            output_folder = job_params.get("output_folder")
            if output_folder:
                output_blob = f"{output_folder}/{tile_name}_cog.tif"
            else:
                output_blob = f"{tile_name}_cog.tif"

            tasks.append({
                "task_id": f"{job_id[:8]}-s{stage_num}-cog-{i}",
                "task_type": "create_cog",
                "parameters": {
                    "blob_name": blob_name,
                    "container_name": container,
                    "source_crs": source_crs,
                    "target_crs": target_crs,
                    "raster_type": validation_result.get("raster_type", {}),
                    "output_blob_name": output_blob,
                    "output_container": output_container,
                    "output_tier": job_params.get("output_tier", "analysis"),
                    "jpeg_quality": jpeg_quality,
                    "in_memory": job_params.get("in_memory", True),
                    "overview_resampling": config.raster.overview_resampling,
                    "reproject_resampling": config.raster.reproject_resampling,
                },
                "metadata": {
                    "tile_index": i,
                    "tile_count": len(blob_list)
                }
            })

        logger.debug(f"Created {len(tasks)} COG tasks for stage {stage_num}")
        return tasks

    @staticmethod
    def _resolve_in_memory(job_params: Dict[str, Any], config, default_threshold_mb: int = 500) -> bool:
        """
        Resolve in_memory setting based on file size and config.

        Priority:
        1. Explicit job parameter (user override)
        2. Size-based automatic selection (if blob size available from pre-flight)
        3. Config default (raster.cog_in_memory)

        Args:
            job_params: Job parameters (may include _blob_size_mb from pre-flight)
            config: AppConfig instance
            default_threshold_mb: Fallback threshold if not in config

        Returns:
            bool: Whether to use in-memory processing
        """
        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "raster_mixin")

        # Priority 1: Explicit job parameter
        if job_params.get('in_memory') is not None:
            return job_params['in_memory']

        # Priority 2: Size-based automatic selection
        blob_size_mb = job_params.get('_blob_size_mb')
        if blob_size_mb is not None:
            threshold = getattr(config.raster, 'in_memory_threshold_mb', default_threshold_mb)
            use_in_memory = blob_size_mb <= threshold
            logger.info(
                f"Auto in_memory={use_in_memory} (size={blob_size_mb:.1f}MB, threshold={threshold}MB)"
            )
            return use_in_memory

        # Priority 3: Config default
        return getattr(config.raster, 'cog_in_memory', True)
