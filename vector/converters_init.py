"""
Vector File Converters - Convert various file formats to GeoDataFrames.

This package provides converters for common vector geospatial file formats.
Converters are registered via decorators and can be retrieved by file extension.

Supported Formats:
- CSV (with lat/lon or WKT)
- GeoPackage (.gpkg)
- GeoJSON (.geojson, .json)
- KML (.kml)
- KMZ (.kmz - zipped KML)
- Shapefile (.shp in .zip)

Usage:
    from converters import ConverterRegistry
    
    # Get converter by file extension
    converter = ConverterRegistry.instance().get_converter('csv')
    
    # Convert file data to GeoDataFrame
    gdf = converter.convert(file_data, lat_name='lat', lon_name='lon')
    
    # List supported extensions
    extensions = ConverterRegistry.instance().list_supported_extensions()

Architecture:
- ConverterRegistry: Singleton registry mapping extensions to converters
- Individual converters: Self-registering classes for each format
- Helper functions: Reusable utilities (xy_df_to_gdf, wkt_df_to_gdf, etc.)
"""

# Import registry first
from .registry import ConverterRegistry

# Import base protocol
from .base import VectorConverter

# Import helper functions (can be used independently)
from .helpers import (
    xy_df_to_gdf,
    wkt_df_to_gdf,
    extract_zip_file,
    list_zip_contents
)

# Import all converters - this triggers registration via decorators
from .csv_converter import CSVConverter
from .geopackage_converter import GeoPackageConverter
from .geojson_converter import GeoJSONConverter
from .kml_converter import KMLConverter
from .kmz_converter import KMZConverter
from .shapefile_converter import ShapefileConverter


__all__ = [
    # Registry
    'ConverterRegistry',
    
    # Protocol
    'VectorConverter',
    
    # Helper functions
    'xy_df_to_gdf',
    'wkt_df_to_gdf',
    'extract_zip_file',
    'list_zip_contents',
    
    # Converters
    'CSVConverter',
    'GeoPackageConverter',
    'GeoJSONConverter',
    'KMLConverter',
    'KMZConverter',
    'ShapefileConverter',
]


# Log registered converters on import
import logging
logger = logging.getLogger(__name__)

_registry = ConverterRegistry.instance()
_extensions = _registry.list_supported_extensions()

logger.info(
    f"Vector converters initialized. "
    f"Supported extensions: {', '.join(_extensions)}"
)
