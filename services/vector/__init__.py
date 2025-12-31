"""
Vector ETL services package.

Provides vector file format conversion and PostGIS loading capabilities.

Modules:
    helpers: Conversion utility functions (xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file)
    converters: Format-specific converters (CSV, GeoJSON, GPKG, KML, KMZ, Shapefile)
    process_vector_tasks: Active Stage 1 & 2 handlers
    postgis_handler: VectorToPostGISHandler for database operations
"""

from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from .process_vector_tasks import process_vector_prepare, process_vector_upload
from .postgis_handler import VectorToPostGISHandler

__all__ = [
    # Helpers
    'xy_df_to_gdf',
    'wkt_df_to_gdf',
    'extract_zip_file',
    'DEFAULT_CRS',
    # Active handlers
    'process_vector_prepare',
    'process_vector_upload',
    # Handler class
    'VectorToPostGISHandler',
]
