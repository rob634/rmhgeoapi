# ============================================================================
# VECTOR ETL CORE - SHARED LOGIC
# ============================================================================
# STATUS: Service layer - Shared vector ETL functions
# PURPOSE: DRY implementation of vector loading, validation, and metadata extraction
# CREATED: 26 JAN 2026
# LAST_REVIEWED: 26 JAN 2026
# EXPORTS: load_vector_source, validate_and_prepare, detect_temporal_extent,
#          extract_geometry_info, apply_column_mapping
# DEPENDENCIES: geopandas, infrastructure.blob
# ============================================================================
"""
Vector ETL Core Module.

Shared logic used by both Function App (process_vector_tasks.py) and
Docker (handler_vector_docker_complete.py) workflows. Eliminates DRY violations
by centralizing:
    - File loading and format conversion
    - Geometry validation and preparation
    - Temporal extent detection
    - Column mapping
    - Geometry type extraction

Exports:
    load_vector_source: Load file from blob and convert to GeoDataFrame
    validate_and_prepare: Validate geometries, reproject to EPSG:4326
    detect_temporal_extent: Extract temporal bounds from datetime column
    extract_geometry_info: Get geometry type and metadata
    apply_column_mapping: Rename columns with validation
    CONVERTER_MAP: Format -> converter function mapping
"""

from io import BytesIO
from typing import Dict, Any, Optional, Tuple, List, Callable
import logging

import geopandas as gpd
import pandas as pd

from util_logger import LoggerFactory, ComponentType, log_memory_checkpoint

# Component-specific logger
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_core"
)

# Reserved column names that conflict with our schema
RESERVED_COLUMNS = {'id', 'geom', 'geometry', 'etl_batch_id'}


# =============================================================================
# CONVERTER MAP
# =============================================================================

def get_converter_map() -> Dict[str, Callable]:
    """
    Get format -> converter function mapping.

    Lazy import to avoid circular dependencies.

    Returns:
        Dict mapping file extensions to converter functions
    """
    from .converters import (
        _convert_csv, _convert_geojson, _convert_geopackage,
        _convert_kml, _convert_kmz, _convert_shapefile
    )

    return {
        'csv': _convert_csv,
        'geojson': _convert_geojson,
        'json': _convert_geojson,
        'gpkg': _convert_geopackage,
        'kml': _convert_kml,
        'kmz': _convert_kmz,
        'shp': _convert_shapefile,
        'zip': _convert_shapefile
    }


# =============================================================================
# FILE LOADING
# =============================================================================

def load_vector_source(
    blob_name: str,
    container_name: str,
    file_extension: str,
    converter_params: Optional[Dict[str, Any]] = None,
    job_id: str = "unknown",
    blob_repo=None
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
    """
    Load vector file from blob storage and convert to GeoDataFrame.

    Handles:
        - Blob download
        - BytesIO wrapping for converters
        - Format-specific conversion
        - Memory logging

    Args:
        blob_name: Source file path in container
        container_name: Blob container name
        file_extension: File format (csv, geojson, gpkg, kml, kmz, shp, zip)
        converter_params: Format-specific parameters (e.g., lat_name, lon_name for CSV)
        job_id: Job ID for logging
        blob_repo: Optional BlobRepository instance (creates one if not provided)

    Returns:
        Tuple of (GeoDataFrame, load_info dict)

    Raises:
        ValueError: If file format is unsupported or file is empty
    """
    from infrastructure.blob import BlobRepository

    # Normalize extension
    file_extension = file_extension.lower().lstrip('.')

    # Get converter
    converter_map = get_converter_map()
    converter = converter_map.get(file_extension)

    if not converter:
        supported = list(converter_map.keys())
        raise ValueError(
            f"Unsupported file format: '{file_extension}'. "
            f"Supported formats: {supported}"
        )

    # Initialize blob repo if not provided
    if blob_repo is None:
        blob_repo = BlobRepository.for_zone("bronze")

    # Download file
    logger.info(f"[{job_id[:8]}] Downloading {blob_name} from {container_name}")
    file_bytes = blob_repo.read_blob(container_name, blob_name)
    file_size_mb = len(file_bytes) / (1024 * 1024)

    log_memory_checkpoint(
        logger, "After file download",
        context_id=job_id,
        file_size_mb=round(file_size_mb, 1),
        file_extension=file_extension
    )

    # Wrap in BytesIO for converters (they expect file-like objects)
    file_buffer = BytesIO(file_bytes)

    # Convert to GeoDataFrame
    # Converters use **kwargs so we unpack converter_params
    params = converter_params or {}
    gdf = converter(file_buffer, **params)

    # Capture original CRS before any transformations
    original_crs = str(gdf.crs) if gdf.crs else "unknown"

    logger.info(
        f"[{job_id[:8]}] Loaded {len(gdf):,} features "
        f"(CRS: {original_crs}, {file_size_mb:.1f}MB)"
    )

    log_memory_checkpoint(
        logger, "After format conversion",
        context_id=job_id,
        feature_count=len(gdf),
        original_crs=original_crs
    )

    # Validate not empty
    if len(gdf) == 0:
        raise ValueError(
            f"Source file '{blob_name}' contains 0 features. "
            f"File may be empty, corrupted, or in wrong format for extension '{file_extension}'."
        )

    load_info = {
        'file_size_mb': round(file_size_mb, 1),
        'original_crs': original_crs,
        'feature_count': len(gdf),
        'columns': list(gdf.columns)
    }

    return gdf, load_info


def build_csv_converter_params(
    parameters: Dict[str, Any],
    existing_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build converter params for CSV files, merging top-level params.

    Top-level params (lat_name, lon_name, wkt_column) take precedence
    over nested converter_params for API discoverability.

    Args:
        parameters: Full job parameters
        existing_params: Existing converter_params dict to merge into

    Returns:
        Merged converter params dict
    """
    params = dict(existing_params or {})

    # Top-level params override nested ones
    if parameters.get('lat_name'):
        params['lat_name'] = parameters['lat_name']
    if parameters.get('lon_name'):
        params['lon_name'] = parameters['lon_name']
    if parameters.get('wkt_column'):
        params['wkt_column'] = parameters['wkt_column']

    return params


# =============================================================================
# VALIDATION AND PREPARATION
# =============================================================================

def validate_and_prepare(
    gdf: gpd.GeoDataFrame,
    geometry_params: Optional[Dict[str, Any]] = None,
    job_id: str = "unknown"
) -> Tuple[gpd.GeoDataFrame, Dict[str, Any], List[str]]:
    """
    Validate geometries and prepare GeoDataFrame for PostGIS.

    Handles:
        - Geometry validation via VectorToPostGISHandler.prepare_gdf()
        - Empty result detection
        - Filtered feature warnings
        - Data warnings capture

    Args:
        gdf: Input GeoDataFrame
        geometry_params: Geometry validation parameters
        job_id: Job ID for logging

    Returns:
        Tuple of (validated_gdf, validation_info, warnings_list)

    Raises:
        ValueError: If all features are filtered out during validation
    """
    from .postgis_handler import VectorToPostGISHandler

    original_count = len(gdf)

    # Validate and reproject to EPSG:4326
    handler = VectorToPostGISHandler()
    validated_gdf = handler.prepare_gdf(gdf, geometry_params=geometry_params or {})

    # Capture any warnings from prepare_gdf
    data_warnings = handler.last_warnings.copy() if hasattr(handler, 'last_warnings') and handler.last_warnings else []

    validated_count = len(validated_gdf)

    log_memory_checkpoint(
        logger, "After validation",
        context_id=job_id,
        validated_features=validated_count
    )

    # Check for empty result
    if validated_count == 0:
        raise ValueError(
            f"All {original_count} features filtered out during geometry validation. "
            f"geometry_params: {geometry_params}. "
            f"Common causes: all NULL geometries, invalid coordinates, CRS reprojection failures."
        )

    # Warn about filtered features
    if validated_count < original_count:
        filtered_count = original_count - validated_count
        pct_filtered = filtered_count / original_count * 100
        warning_msg = (
            f"{filtered_count} features ({pct_filtered:.1f}%) filtered out during validation. "
            f"{validated_count} features remaining."
        )
        logger.warning(f"[{job_id[:8]}] {warning_msg}")
        data_warnings.append(warning_msg)

    validation_info = {
        'original_count': original_count,
        'validated_count': validated_count,
        'filtered_count': original_count - validated_count
    }

    return validated_gdf, validation_info, data_warnings


# =============================================================================
# COLUMN MAPPING
# =============================================================================

def apply_column_mapping(
    gdf: gpd.GeoDataFrame,
    mapping: Dict[str, str],
    job_id: str = "unknown"
) -> gpd.GeoDataFrame:
    """
    Apply column renames to GeoDataFrame with validation.

    Validates that all source columns exist before renaming.

    Args:
        gdf: Source GeoDataFrame
        mapping: {source_column: target_column} rename mapping
        job_id: Job ID for logging

    Returns:
        GeoDataFrame with renamed columns

    Raises:
        ValueError: If any source columns in mapping are not found
    """
    if not mapping:
        return gdf

    # Get available columns (exclude geometry)
    available_cols = [c for c in gdf.columns if c != 'geometry']

    # Check for missing source columns
    missing = [col for col in mapping.keys() if col not in gdf.columns]

    if missing:
        raise ValueError(
            f"Column mapping failed. Source columns not found: {missing}. "
            f"Available columns: {available_cols}"
        )

    # Apply renames
    gdf = gdf.rename(columns=mapping)

    # Log the mapping
    renamed_pairs = [f"'{src}' -> '{tgt}'" for src, tgt in mapping.items()]
    logger.info(f"[{job_id[:8]}] Applied column mapping: {', '.join(renamed_pairs)}")

    return gdf


def filter_reserved_columns(
    columns: List[str],
    job_id: str = "unknown"
) -> Tuple[List[str], List[str]]:
    """
    Filter out reserved column names from column list.

    Reserved columns (id, geom, geometry, etl_batch_id) are created
    by our schema and cannot be user-defined.

    Args:
        columns: List of column names
        job_id: Job ID for logging

    Returns:
        Tuple of (filtered_columns, skipped_columns)
    """
    skipped = [c for c in columns if c.lower() in RESERVED_COLUMNS]
    filtered = [c for c in columns if c.lower() not in RESERVED_COLUMNS]

    if skipped:
        logger.warning(
            f"[{job_id[:8]}] Reserved columns will be skipped: {skipped}. "
            f"These are created by our schema (id=PRIMARY KEY, geom=GEOMETRY, etl_batch_id=IDEMPOTENCY)."
        )

    return filtered, skipped


# =============================================================================
# GEOMETRY INFO EXTRACTION
# =============================================================================

def extract_geometry_info(gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
    """
    Extract geometry type and related metadata from GeoDataFrame.

    Args:
        gdf: GeoDataFrame to analyze

    Returns:
        Dict with geometry_type, is_multi, unique_types
    """
    if len(gdf) == 0:
        return {
            'geometry_type': 'GEOMETRY',
            'is_multi': False,
            'unique_types': []
        }

    # Get unique geometry types
    geom_types = gdf.geometry.geom_type.unique().tolist()

    # Determine primary type
    if len(geom_types) == 1:
        geometry_type = geom_types[0].upper()
    else:
        # Mixed geometry types
        geometry_type = 'GEOMETRY'

    # Check if multi-geometry
    is_multi = geometry_type.startswith('MULTI')

    return {
        'geometry_type': geometry_type,
        'is_multi': is_multi,
        'unique_types': geom_types
    }


# =============================================================================
# TEMPORAL EXTENT DETECTION
# =============================================================================

def detect_temporal_extent(
    gdf: gpd.GeoDataFrame,
    temporal_property: Optional[str],
    job_id: str = "unknown"
) -> Tuple[Optional[str], Optional[str]]:
    """
    Detect temporal extent from a datetime column.

    Args:
        gdf: GeoDataFrame to analyze
        temporal_property: Column name containing datetime values
        job_id: Job ID for logging

    Returns:
        Tuple of (temporal_start, temporal_end) as ISO strings, or (None, None)
    """
    if not temporal_property:
        return None, None

    if temporal_property not in gdf.columns:
        logger.warning(
            f"[{job_id[:8]}] temporal_property '{temporal_property}' not found in columns: "
            f"{list(gdf.columns)}"
        )
        return None, None

    try:
        # Try to parse as datetime
        temporal_col = pd.to_datetime(gdf[temporal_property], errors='coerce')
        valid_dates = temporal_col.dropna()

        if len(valid_dates) == 0:
            logger.warning(
                f"[{job_id[:8]}] temporal_property '{temporal_property}' found but no valid dates parsed"
            )
            return None, None

        temporal_start = valid_dates.min().isoformat() + "Z"
        temporal_end = valid_dates.max().isoformat() + "Z"

        logger.info(
            f"[{job_id[:8]}] Temporal extent: {temporal_start} to {temporal_end}"
        )

        return temporal_start, temporal_end

    except Exception as e:
        logger.warning(
            f"[{job_id[:8]}] Failed to parse temporal_property '{temporal_property}': {e}"
        )
        return None, None


# =============================================================================
# MEMORY LOGGING
# =============================================================================

def log_gdf_memory(
    gdf: gpd.GeoDataFrame,
    label: str,
    job_id: str = "unknown"
) -> float:
    """
    Log GeoDataFrame memory usage.

    Args:
        gdf: GeoDataFrame to measure
        label: Description of measurement point
        job_id: Job ID for logging

    Returns:
        Memory usage in MB
    """
    mem_bytes = gdf.memory_usage(deep=True).sum()
    mem_mb = mem_bytes / (1024 * 1024)
    logger.info(f"[{job_id[:8]}] Memory ({label}): {mem_mb:.1f}MB ({len(gdf):,} rows)")
    return mem_mb
