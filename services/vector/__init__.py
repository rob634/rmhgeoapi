"""
Vector ETL services package.

Provides vector file format conversion and PostGIS loading capabilities.

Modules:
    helpers: Conversion utility functions (xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file)
    converters: Format-specific converters (CSV, GeoJSON, GPKG, KML, KMZ, Shapefile)
    tasks: TaskRegistry task handlers
        - load_vector_file: Single-stage load (legacy)
        - validate_vector: Validation task (legacy)
        - upload_vector_chunk: Upload task (legacy)
        - prepare_vector_chunks: Stage 1 - Load, validate, chunk, pickle (NEW)
        - upload_pickled_chunk: Stage 2 - Upload pickled chunk to PostGIS (NEW)
    postgis_handler: VectorToPostGISHandler for database operations
"""

from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from .tasks import (
    load_vector_file,
    validate_vector,
    upload_vector_chunk,
    prepare_vector_chunks,
    upload_pickled_chunk
)
from .postgis_handler import VectorToPostGISHandler

__all__ = [
    # Helpers
    'xy_df_to_gdf',
    'wkt_df_to_gdf',
    'extract_zip_file',
    'DEFAULT_CRS',
    # Tasks (legacy single-stage)
    'load_vector_file',
    'validate_vector',
    'upload_vector_chunk',
    # Tasks (two-stage with pickle intermediate)
    'prepare_vector_chunks',
    'upload_pickled_chunk',
    # Handler
    'VectorToPostGISHandler',
]
