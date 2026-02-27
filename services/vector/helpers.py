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
from pathlib import Path
import os
import tempfile
import zipfile
from typing import Optional, Union
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

    # Parse WKT strings to geometries, handling per-row errors
    def _safe_wkt_load(val):
        if pd.isna(val) or val == '':
            return None
        try:
            return wkt.loads(val)
        except (ShapelyError, Exception):
            return None

    geometry = df[wkt_column].apply(_safe_wkt_load)
    bad_mask = geometry.isna()
    bad_count = bad_mask.sum()

    if bad_count == len(df):
        raise ValueError(
            f"All {len(df)} rows have invalid or empty WKT in column '{wkt_column}'. "
            f"No valid geometries to process."
        )

    if bad_count > 0:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Dropped {bad_count}/{len(df)} rows with invalid WKT in column '{wkt_column}'"
        )
        df = df[~bad_mask].copy()
        geometry = geometry[~bad_mask]

    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
    return gdf


def extract_zip_file(
    zip_data: Union[BytesIO, str, Path],
    target_extension: str,
    target_name: Optional[str] = None,
    extract_dir: Optional[str] = None,
) -> str:
    """
    Extract file from ZIP archive to temp or mount directory.

    Args:
        zip_data: BytesIO containing ZIP data, or file path string (mount-based).
            zipfile.ZipFile() accepts both natively.
        target_extension: File extension to find (e.g., '.shp', '.kml')
        target_name: Specific filename (optional, defaults to first match)
        extract_dir: Optional extraction directory (mount subdir). If provided,
            used instead of tempfile.mkdtemp(). Created with exist_ok=True.
            Mount dirs are cleaned up by the calling handler's finally block.

    Returns:
        Path to extracted file in extract directory

    Raises:
        FileNotFoundError: If target file not found in ZIP
        zipfile.BadZipFile: If data is not a valid ZIP
    """
    if extract_dir:
        os.makedirs(extract_dir, exist_ok=True)
        dest_dir = extract_dir
    else:
        dest_dir = tempfile.mkdtemp()

    # zipfile.ZipFile accepts both BytesIO and file path strings natively
    zip_target = str(zip_data) if isinstance(zip_data, Path) else zip_data

    with zipfile.ZipFile(zip_target) as zf:
        # Extract all files
        zf.extractall(dest_dir)

        # Find target file
        for root, dirs, files in os.walk(dest_dir):
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
