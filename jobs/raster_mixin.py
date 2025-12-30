"""
Raster Mixin - Shared Infrastructure for Raster Workflows.

Provides shared parameter schemas and helper methods for all raster
processing workflows. Designed for extensibility.

Used by:
    - ProcessRasterV2Job (single file, 3 stages)
    - ProcessRasterCollectionV2Job (multi-tile, 4 stages)
    - ProcessLargeRasterV2Job (large file tiling, 5 stages)

Exports:
    RasterMixin: Mixin class with shared schemas and helpers
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
        # Use Bronze zone for input rasters (08 DEC 2025)
        blob_repo = BlobRepository.for_zone("bronze")

        for i, blob_name in enumerate(blob_list):
            blob_url = blob_repo.get_blob_url_with_sas(
                container_name=container_name,
                blob_name=blob_name,
                hours=1
            )
            tasks.append({
                "task_id": f"{job_id[:8]}-s{stage_num}-validate-{i}",
                "task_type": "raster_validate",
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
                "task_type": "raster_create_cog",
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
    def _get_default_band_names(detected_type: str, band_count: int) -> Optional[Dict[int, str]]:
        """
        Get default band_names mapping based on detected raster type.

        Returns None for single-band types (DEM, categorical) or unknown types,
        since no band selection is needed - all bands are processed.

        This enables auto-detection to work correctly across:
        - Standard RGB images (bands 1, 2, 3)
        - RGBA with alpha (bands 1, 2, 3, 4)
        - RGB + NIR (bands 1, 2, 3, 4)
        - Multispectral Landsat/Sentinel (bands 5, 3, 2 → RGB)

        Args:
            detected_type: Type detected by _detect_raster_type() (e.g., "rgb", "multispectral")
            band_count: Actual number of bands in the raster file

        Returns:
            Dict mapping band indices to names, or None if all bands should be processed

        Example:
            >>> RasterMixin._get_default_band_names("rgb", 3)
            {1: "Red", 2: "Green", 3: "Blue"}

            >>> RasterMixin._get_default_band_names("multispectral", 8)
            {5: "Red", 3: "Green", 2: "Blue"}

            >>> RasterMixin._get_default_band_names("dem", 1)
            None  # Process all bands
        """
        logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, "raster_mixin")

        # Default band mappings by raster type
        BAND_NAMES_BY_TYPE = {
            "rgb": {1: "Red", 2: "Green", 3: "Blue"},
            "rgba": {1: "Red", 2: "Green", 3: "Blue", 4: "Alpha"},
            "nir": {1: "Red", 2: "Green", 3: "Blue", 4: "NIR"},
            "multispectral": {5: "Red", 3: "Green", 2: "Blue"},  # Landsat/Sentinel B5,B3,B2 → RGB
            "dem": None,
            "categorical": None,
            "unknown": None,
        }

        default = BAND_NAMES_BY_TYPE.get(detected_type)

        # Validate band_names against actual band count
        if default and isinstance(default, dict):
            # Filter out bands that don't exist in the file
            valid_bands = {k: v for k, v in default.items() if k <= band_count}
            if len(valid_bands) < len(default):
                logger.warning(
                    f"⚠️ Band mismatch: {detected_type} expects bands {list(default.keys())} "
                    f"but file has only {band_count} bands. Using {list(valid_bands.keys())}"
                )
            return valid_bands if valid_bands else None

        return default

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

        Args:
            job_params: Job parameters
            config: AppConfig instance

        Returns:
            bool: Whether to use in-memory processing
        """
        # Priority 1: Explicit job parameter
        if job_params.get('in_memory') is not None:
            return job_params['in_memory']

        # Priority 2: Config default (False = disk-based, safer)
        return getattr(config.raster, 'cog_in_memory', False)
