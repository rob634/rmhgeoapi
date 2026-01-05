# ============================================================================
# VECTOR CONVERSION HELPERS
# ============================================================================
# STATUS: Service layer - Utility functions for vector data conversion
# PURPOSE: Convert various data formats (CSV, WKT) to GeoDataFrames
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
# DEPENDENCIES: geopandas, shapely, pandas
# ============================================================================
"""
Vector Conversion Helpers.

Utility functions for converting various data formats to GeoDataFrames.

Exports:
    xy_df_to_gdf: Convert DataFrame with lat/lon to GeoDataFrame
    wkt_df_to_gdf: Convert DataFrame with WKT column to GeoDataFrame
    extract_zip_file: Extract file from ZIP archive
    DEFAULT_CRS: Default coordinate reference system (EPSG:4326)
"""

from io import BytesIO
import os
import tempfile
import zipfile
from typing import Optional
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point
from shapely.errors import ShapelyError

DEFAULT_CRS = "EPSG:4326"


def xy_df_to_gdf(
    df: pd.DataFrame,
    lat_name: str,
    lon_name: str,
    crs: str = DEFAULT_CRS
) -> gpd.GeoDataFrame:
    """
    Convert DataFrame with lat/lon columns to GeoDataFrame.

    Args:
        df: DataFrame with coordinate columns
        lat_name: Latitude column name
        lon_name: Longitude column name
        crs: Coordinate reference system (default: EPSG:4326)

    Returns:
        GeoDataFrame with Point geometries

    Raises:
        ValueError: If coordinates are out of valid range
        KeyError: If specified columns don't exist
    """
    # Validate columns exist
    if lat_name not in df.columns:
        raise KeyError(f"Latitude column '{lat_name}' not found in DataFrame")
    if lon_name not in df.columns:
        raise KeyError(f"Longitude column '{lon_name}' not found in DataFrame")

    # Validate longitude bounds (-180 to 180)
    lon_min, lon_max = df[lon_name].min(), df[lon_name].max()
    if not (-180 <= lon_min <= 180 and -180 <= lon_max <= 180):
        raise ValueError(
            f"Longitude values out of range: min={lon_min}, max={lon_max}. "
            f"Valid range: -180 to 180"
        )

    # Validate latitude bounds (-90 to 90)
    lat_min, lat_max = df[lat_name].min(), df[lat_name].max()
    if not (-90 <= lat_min <= 90 and -90 <= lat_max <= 90):
        raise ValueError(
            f"Latitude values out of range: min={lat_min}, max={lat_max}. "
            f"Valid range: -90 to 90"
        )

    # Create Point geometries
    geometry = [Point(xy) for xy in zip(df[lon_name], df[lat_name])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)

    return gdf


def wkt_df_to_gdf(
    df: pd.DataFrame,
    wkt_column: str,
    crs: str = DEFAULT_CRS
) -> gpd.GeoDataFrame:
    """
    Convert DataFrame with WKT geometry column to GeoDataFrame.

    Args:
        df: DataFrame with WKT column
        wkt_column: WKT geometry column name
        crs: Coordinate reference system (default: EPSG:4326)

    Returns:
        GeoDataFrame with parsed geometries

    Raises:
        KeyError: If WKT column doesn't exist
        ValueError: If WKT parsing fails
    """
    # Validate column exists
    if wkt_column not in df.columns:
        raise KeyError(f"WKT column '{wkt_column}' not found in DataFrame")

    try:
        # Parse WKT strings to geometries
        geometry = df[wkt_column].apply(wkt.loads)
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
        return gdf
    except ShapelyError as e:
        raise ValueError(f"Invalid WKT in column '{wkt_column}': {e}")


def extract_zip_file(
    zip_data: BytesIO,
    target_extension: str,
    target_name: Optional[str] = None
) -> str:
    """
    Extract file from ZIP archive to temp directory.

    Args:
        zip_data: BytesIO containing ZIP data
        target_extension: File extension to find (e.g., '.shp', '.kml')
        target_name: Specific filename (optional, defaults to first match)

    Returns:
        Path to extracted file in temp directory

    Raises:
        FileNotFoundError: If target file not found in ZIP
        zipfile.BadZipFile: If data is not a valid ZIP
    """
    temp_dir = tempfile.mkdtemp()

    with zipfile.ZipFile(zip_data) as zf:
        # Extract all files
        zf.extractall(temp_dir)

        # Find target file
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                # Check for specific filename match
                if target_name and file == target_name:
                    return os.path.join(root, file)
                # Check for extension match
                elif file.lower().endswith(target_extension.lower()):
                    return os.path.join(root, file)

        # File not found
        raise FileNotFoundError(
            f"No file with extension '{target_extension}' "
            f"(target_name: {target_name}) found in ZIP archive"
        )
