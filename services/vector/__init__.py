# ============================================================================
# VECTOR ETL SERVICES PACKAGE
# ============================================================================
# STATUS: Service layer - Package init for vector ETL services
# PURPOSE: Export vector file conversion and PostGIS loading capabilities
# LAST_REVIEWED: 13 FEB 2026
# EXPORTS: xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS,
#          VectorToPostGISHandler, load_vector_source, validate_and_prepare
# ============================================================================
"""
Vector ETL services package.

Provides vector file format conversion and PostGIS loading capabilities.

Modules:
    helpers: Conversion utility functions (xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file)
    converters: Format-specific converters (CSV, GeoJSON, GPKG, KML, KMZ, Shapefile)
    core: Shared ETL logic used by Docker vector workflow
    postgis_handler: VectorToPostGISHandler for database operations

Archived (13 FEB 2026):
    process_vector_tasks → docs/archive/v08_archive_feb2026/services/
"""

from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from .postgis_handler import VectorToPostGISHandler

# Core shared functions (26 JAN 2026 - DRY refactor)
from .core import (
    load_vector_source,
    validate_and_prepare,
    get_converter_map,
    build_csv_converter_params,
    apply_column_mapping,
    filter_reserved_columns,
    extract_geometry_info,
    detect_temporal_extent,
    log_gdf_memory,
)

__all__ = [
    # Helpers
    'xy_df_to_gdf',
    'wkt_df_to_gdf',
    'extract_zip_file',
    'DEFAULT_CRS',
    # Handler class
    'VectorToPostGISHandler',
    # Core shared functions (used by Docker workflow)
    'load_vector_source',
    'validate_and_prepare',
    'get_converter_map',
    'build_csv_converter_params',
    'apply_column_mapping',
    'filter_reserved_columns',
    'extract_geometry_info',
    'detect_temporal_extent',
    'log_gdf_memory',
]
