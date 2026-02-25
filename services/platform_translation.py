# ============================================================================
# PLATFORM TRANSLATION SERVICE
# ============================================================================
# STATUS: Service layer - DDH to CoreMachine translation
# PURPOSE: Anti-Corruption Layer translating DDH requests to CoreMachine parameters
# CREATED: 27 JAN 2026 (extracted from trigger_platform.py)
# EXPORTS: translate_to_coremachine, translate_single_raster, translate_raster_collection
# DEPENDENCIES: config, core.models
# ============================================================================
"""
Platform Translation Service.

Translates DDH (Data Hub) request formats to CoreMachine job parameters.
This is the core of the Anti-Corruption Layer - it isolates DDH API
from CoreMachine internals.

Exports:
    translate_to_coremachine: Generic DDH → CoreMachine translation
    translate_single_raster: Single raster file translation
    translate_raster_collection: Multiple raster files translation
    generate_table_name: DDH IDs → PostGIS table name
    generate_stac_item_id: DDH IDs → STAC item ID
    normalize_data_type: Normalize data_type string to 'vector' or 'raster'
    get_unpublish_params_from_request: Extract unpublish parameters from ApiRequest
"""

import logging
from typing import Dict, Any, Optional

from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "platform_translation")

# Import config
from config import get_config, get_app_mode_config

# Import core models
from core.models import (
    DataType,
    OperationType,
    PlatformRequest,
    ApiRequest,
)


def normalize_data_type(data_type: str) -> Optional[str]:
    """
    Normalize data_type to 'vector' or 'raster'.

    Args:
        data_type: Raw data type string from various sources

    Returns:
        'vector', 'raster', or the lowercase original if not recognized
    """
    if not data_type:
        return None
    dt_lower = data_type.lower()
    if dt_lower in ('vector', 'unpublish_vector', 'process_vector'):
        return 'vector'
    if dt_lower in ('raster', 'unpublish_raster', 'process_raster', 'process_raster_v2', 'process_raster_docker'):
        return 'raster'
    return dt_lower


def generate_table_name(
    dataset_id: str,
    resource_id: str,
    version_id: Optional[str] = None,
    version_ordinal: Optional[int] = None
) -> str:
    """
    Generate PostGIS table name from DDH identifiers.

    Uses PlatformConfig.generate_vector_table_name() for consistency.

    Args:
        dataset_id: DDH dataset identifier
        resource_id: DDH resource identifier
        version_id: DDH version identifier (None for draft mode)
        version_ordinal: Release ordinal (1, 2, 3...) for draft naming

    Returns:
        URL-safe table name
    """
    config = get_config()
    return config.platform.generate_vector_table_name(
        dataset_id, resource_id, version_id, version_ordinal=version_ordinal
    )


def generate_stac_item_id(
    dataset_id: str,
    resource_id: str,
    version_id: Optional[str] = None,
    version_ordinal: Optional[int] = None
) -> str:
    """
    Generate STAC item ID from DDH identifiers.

    Uses PlatformConfig.generate_stac_item_id() for consistency.

    Args:
        dataset_id: DDH dataset identifier
        resource_id: DDH resource identifier
        version_id: DDH version identifier (None for draft mode)
        version_ordinal: Release ordinal (1, 2, 3...) for draft naming

    Returns:
        URL-safe STAC item ID
    """
    config = get_config()
    return config.platform.generate_stac_item_id(
        dataset_id, resource_id, version_id, version_ordinal=version_ordinal
    )


def get_unpublish_params_from_request(request: ApiRequest, data_type: str) -> dict:
    """
    Extract unpublish parameters from a platform request.

    For vectors, reads stored table_name from Release record (authoritative
    source since ordinal-based naming). Falls back to reconstruction for
    pre-ordinal data only.

    Args:
        request: ApiRequest record from platform layer
        data_type: Normalized data type ('vector' or 'raster')

    Returns:
        Dict with unpublish parameters (table_name or stac_item_id/collection_id)
    """
    if data_type == "vector":
        # Read stored table_name from Release (authoritative source)
        table_name = None
        if request.job_id:
            from infrastructure import ReleaseRepository
            release_repo = ReleaseRepository()
            release = release_repo.get_by_job_id(request.job_id)
            if release and release.table_name:
                table_name = release.table_name

        if not table_name:
            # Fallback: reconstruct (pre-ordinal data only)
            table_name = generate_table_name(request.dataset_id, request.resource_id, request.version_id)
            logger.warning(f"Reconstructed table_name (no release): {table_name}")

        return {'table_name': table_name}
    elif data_type == "raster":
        stac_item_id = generate_stac_item_id(request.dataset_id, request.resource_id, request.version_id)
        collection_id = request.dataset_id
        return {'stac_item_id': stac_item_id, 'collection_id': collection_id}
    return {}


def translate_to_coremachine(
    request: PlatformRequest,
    cfg=None
) -> tuple[str, Dict[str, Any]]:
    """
    Translate DDH PlatformRequest to CoreMachine job_type + parameters.

    This is the core of the Anti-Corruption Layer - it isolates DDH API
    from CoreMachine internals. If DDH changes their API, we update this
    function, not CoreMachine jobs.

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance (optional, will fetch if not provided)

    Returns:
        Tuple of (job_type, job_parameters)

    Raises:
        ValueError: If data type or operation not supported
        NotImplementedError: If operation is UPDATE/DELETE (Phase 2)
    """
    if cfg is None:
        cfg = get_config()

    operation = request.operation
    data_type = request.data_type

    # Only CREATE is implemented (Phase 1)
    if operation != OperationType.CREATE:
        raise NotImplementedError(f"{operation.value} operation coming in Phase 2")

    # Use PlatformConfig for output naming
    platform_cfg = cfg.platform

    # ========================================================================
    # VECTOR CREATE → vector_docker_etl (V0.8) or process_vector (fallback)
    # ========================================================================
    # V0.8 (24 JAN 2026): Routes to Docker by default for performance.
    # Set docker=false in processing_options to use Function App worker.
    if data_type == DataType.VECTOR:
        # Table name: use override from processing_options if provided (26 JAN 2026)
        # Otherwise auto-generate from DDH identifiers
        # This allows human-readable names when DDH IDs are numeric (e.g., "552342_2342345_v2")
        opts = request.processing_options
        table_name = opts.table_name
        if not table_name:
            table_name = platform_cfg.generate_vector_table_name(
                request.dataset_id,
                request.resource_id,
                request.version_id
            )
        else:
            # Sanitize user-provided table name for PostgreSQL
            from config.platform_config import _slugify_for_postgres
            table_name = _slugify_for_postgres(table_name)
            logger.info(f"  Using table_name override: {table_name}")

        # Generate STAC item ID
        stac_item_id = platform_cfg.generate_stac_item_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        # Detect file extension
        file_name = request.file_name
        if isinstance(file_name, list):
            file_name = file_name[0]
        file_ext = file_name.split('.')[-1].lower()

        # Build converter params if CSV/lon-lat columns specified
        # Note: Use 'lat_name'/'lon_name' keys to match job validator expectations
        converter_params = {}
        if opts.lon_column or opts.lat_column or opts.wkt_column:
            converter_params = {
                'lon_name': opts.lon_column,
                'lat_name': opts.lat_column,
                'wkt_column': opts.wkt_column
            }
        # GPKG layer selection (24 FEB 2026)
        if file_ext == 'gpkg' and opts.layer_name:
            converter_params['layer_name'] = opts.layer_name

        # Docker worker always used for GDAL operations (06 FEB 2026)
        job_type = 'vector_docker_etl'
        logger.info(f"[PLATFORM] Routing vector ETL to Docker worker")

        return job_type, {
            # File location
            'blob_name': request.file_name,
            'file_extension': file_ext,
            'container_name': request.container_name,

            # PostGIS target
            'table_name': table_name,
            'schema': cfg.vector.target_schema,

            # DDH identifiers (for STAC metadata)
            'dataset_id': request.dataset_id,
            'resource_id': request.resource_id,
            'version_id': request.version_id,

            # STAC metadata
            'stac_item_id': stac_item_id,
            'title': request.generated_title,
            'description': request.description,
            'tags': request.tags,
            'access_level': request.access_level.value,  # E4 Phase 1: enum → string

            # Processing options
            'converter_params': converter_params,
            'overwrite': opts.overwrite,

            # GPKG layer selection (24 FEB 2026)
            'layer_name': opts.layer_name,
        }

    # ========================================================================
    # RASTER CREATE → process_raster_v2 or process_raster_collection_v2
    # ========================================================================
    # Updated 04 DEC 2025: All raster jobs now use v2 mixin pattern
    # - Single raster: process_raster_v2 (with auto-fallback to process_large_raster_v2)
    # - Collection: process_raster_collection_v2
    elif data_type == DataType.RASTER:
        opts = request.processing_options

        # Generate output paths from DDH IDs
        output_folder = platform_cfg.generate_raster_output_folder(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        # Collection ID: use override from processing_options if provided (22 JAN 2026)
        # Otherwise auto-generate from DDH identifiers
        collection_id = opts.collection_id
        if not collection_id:
            collection_id = platform_cfg.generate_stac_collection_id(
                request.dataset_id,
                request.resource_id,
                request.version_id
            )
        else:
            logger.info(f"  Using collection_id override: {collection_id}")

        stac_item_id = platform_cfg.generate_stac_item_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )

        # Check if this is a raster collection (multiple files)
        if request.is_raster_collection:
            # DISABLED (25 FEB 2026): Raster collections not yet production-ready.
            # Only individual raster and vector submissions are supported.
            raise ValueError(
                "Raster collection submission is not yet implemented. "
                "Please submit individual raster files (.tif) one at a time. "
                "Multi-file raster collection support is under development."
            )
            # Multiple rasters → process_raster_collection_docker (V0.8 - 30 JAN 2026)
            # Sequential checkpoint-based processing on Docker worker
            logger.info(f"  Raster collection: {len(request.file_name)} files → process_raster_collection_docker")

            return 'process_raster_collection_docker', {
                # File location (required)
                'container_name': request.container_name,
                'blob_list': request.file_name,  # Already a list

                # Output location
                'output_folder': output_folder,

                # STAC metadata
                'collection_id': collection_id,
                'collection_title': request.generated_title,
                'collection_description': request.description,
                'license': opts.license,

                # DDH identifiers (Platform passthrough)
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,
                'access_level': request.access_level.value,  # E4 Phase 1: enum → string

                # Processing options
                'output_tier': opts.output_tier.value,
                'target_crs': opts.crs,
                'input_crs': opts.input_crs,
                'raster_type': opts.raster_type.value,
                'jpeg_quality': opts.jpeg_quality,

                # Docker options
                'use_mount_storage': opts.use_mount_storage,
                'cleanup_temp': opts.cleanup_temp,
                'strict_mode': opts.strict_mode,
            }
        else:
            # Single raster → process_raster_docker (06 FEB 2026)
            file_name = request.file_name
            if isinstance(file_name, list):
                file_name = file_name[0]

            # Docker worker always used for GDAL operations (06 FEB 2026)
            job_type = 'process_raster_docker'
            logger.info(f"  Raster processing → {job_type}")

            return job_type, {
                # File location (required)
                'blob_name': file_name,
                'container_name': request.container_name,

                # Output location
                'output_folder': output_folder,

                # STAC metadata
                'collection_id': collection_id,
                'stac_item_id': stac_item_id,
                'access_level': request.access_level.value,  # E4 Phase 1: enum → string

                # DDH identifiers (Platform passthrough)
                'dataset_id': request.dataset_id,
                'resource_id': request.resource_id,
                'version_id': request.version_id,

                # Processing options
                'output_tier': opts.output_tier.value,
                'target_crs': opts.crs,
                'raster_type': opts.raster_type.value,

                # Overwrite behavior (28 JAN 2026)
                'overwrite': opts.overwrite,
                'title': request.generated_title,
                'tags': request.tags,
            }

    # ========================================================================
    # POINTCLOUD, MESH_3D, TABULAR - Phase 2
    # ========================================================================
    elif data_type in [DataType.POINTCLOUD, DataType.MESH_3D, DataType.TABULAR]:
        raise NotImplementedError(f"{data_type.value} processing coming in Phase 2")

    else:
        raise ValueError(f"Unsupported data type: {data_type}")


def translate_single_raster(
    request: PlatformRequest,
    cfg=None
) -> tuple[str, Dict[str, Any]]:
    """
    Translate DDH request to single raster job parameters.

    Used by /api/platform/raster endpoint.
    Returns process_raster_v2 by default, or process_raster_docker if
    processing_mode="docker" is specified.

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance (optional, will fetch if not provided)

    Returns:
        Tuple of (job_type, job_parameters)
        - job_type: 'process_raster_v2' or 'process_raster_docker'
    """
    if cfg is None:
        cfg = get_config()

    platform_cfg = cfg.platform
    opts = request.processing_options

    output_folder = platform_cfg.generate_raster_output_folder(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    # Collection ID: use override from processing_options if provided (22 JAN 2026)
    # Otherwise auto-generate from DDH identifiers
    collection_id = opts.collection_id
    if not collection_id:
        collection_id = platform_cfg.generate_stac_collection_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )
    else:
        logger.info(f"  Using collection_id override: {collection_id}")

    stac_item_id = platform_cfg.generate_stac_item_id(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    # file_name is guaranteed to be a string by endpoint validation
    file_name = request.file_name
    if isinstance(file_name, list):
        file_name = file_name[0]

    # Docker worker always used for GDAL operations (06 FEB 2026)
    job_type = 'process_raster_docker'
    logger.info(f"  Raster processing → {job_type}")

    return job_type, {
        # File location (required)
        'blob_name': file_name,
        'container_name': request.container_name,

        # Output location
        'output_folder': output_folder,

        # STAC metadata
        'collection_id': collection_id,
        'stac_item_id': stac_item_id,
        'access_level': request.access_level.value,  # E4 Phase 1: enum → string

        # DDH identifiers (Platform passthrough)
        'dataset_id': request.dataset_id,
        'resource_id': request.resource_id,
        'version_id': request.version_id,

        # Processing options
        'output_tier': opts.output_tier.value,
        'target_crs': opts.crs,
        'raster_type': opts.raster_type.value,

        # Overwrite behavior (28 JAN 2026)
        'overwrite': opts.overwrite,
        'title': request.generated_title,
        'tags': request.tags,
    }


def translate_raster_collection(
    request: PlatformRequest,
    cfg=None
) -> tuple[str, Dict[str, Any]]:
    """
    Translate DDH request to raster collection job parameters.

    Used by /api/platform/raster-collection endpoint.

    V0.8 (30 JAN 2026): Routes to process_raster_collection_docker.
    Sequential checkpoint-based processing on Docker worker.

    Args:
        request: PlatformRequest from DDH
        cfg: AppConfig instance (optional, will fetch if not provided)

    Returns:
        Tuple of ('process_raster_collection_docker', job_parameters)
    """
    if cfg is None:
        cfg = get_config()

    platform_cfg = cfg.platform
    opts = request.processing_options

    output_folder = platform_cfg.generate_raster_output_folder(
        request.dataset_id,
        request.resource_id,
        request.version_id
    )

    # Collection ID: use override from processing_options if provided (22 JAN 2026)
    # Otherwise auto-generate from DDH identifiers
    collection_id = opts.collection_id
    if not collection_id:
        collection_id = platform_cfg.generate_stac_collection_id(
            request.dataset_id,
            request.resource_id,
            request.version_id
        )
    else:
        logger.info(f"  Using collection_id override: {collection_id}")

    logger.info(f"  Raster collection: {len(request.file_name)} files → process_raster_collection_docker")

    return 'process_raster_collection_docker', {
        # File location (required)
        'container_name': request.container_name,
        'blob_list': request.file_name,  # Already validated as list by endpoint

        # Output location
        'output_folder': output_folder,

        # STAC metadata
        'collection_id': collection_id,
        'collection_title': request.generated_title,
        'collection_description': request.description,
        'license': opts.license,

        # DDH identifiers (Platform passthrough)
        'dataset_id': request.dataset_id,
        'resource_id': request.resource_id,
        'version_id': request.version_id,
        'access_level': request.access_level.value,  # E4 Phase 1: enum → string

        # Processing options
        'output_tier': opts.output_tier.value,
        'target_crs': opts.crs,
        'input_crs': opts.input_crs,
        'raster_type': opts.raster_type.value,
        'jpeg_quality': opts.jpeg_quality,

        # Docker options
        'use_mount_storage': opts.use_mount_storage,
        'cleanup_temp': opts.cleanup_temp,
        'strict_mode': opts.strict_mode,
    }
