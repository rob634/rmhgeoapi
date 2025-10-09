"""
Converter Helper Functions - Pure utility functions for converting data to GeoDataFrames.

These functions are used by converter classes but are independent and reusable.
"""

from io import BytesIO
from math import ceil, floor
import os
import tempfile
import zipfile

from geopandas import GeoDataFrame
from pandas import DataFrame
from shapely import Point, wkt
from shapely.errors import WKTReadingError, ShapelyError

from utils import logger, DEFAULT_CRS_STRING


def xy_df_to_gdf(
    df: DataFrame,
    lat_name: str,
    lon_name: str,
    crs: str = DEFAULT_CRS_STRING
) -> GeoDataFrame:
    """
    Convert DataFrame with lat/lon columns to GeoDataFrame with Point geometries.
    
    Args:
        df: DataFrame with latitude and longitude columns
        lat_name: Name of latitude column
        lon_name: Name of longitude column
        crs: Coordinate reference system (default: EPSG:4326)
    
    Returns:
        GeoDataFrame with Point geometries
        
    Raises:
        ValueError: If columns not found or all values invalid
        
    Example:
        df = pd.DataFrame({'lat': [40.7, 34.0], 'lon': [-74.0, -118.2]})
        gdf = xy_df_to_gdf(df, 'lat', 'lon')
    """
    if not isinstance(df, DataFrame):
        raise ValueError(f"Invalid DataFrame provided: {type(df)}")
    
    # Check columns exist
    if lat_name not in df.columns:
        raise ValueError(
            f"Latitude column '{lat_name}' not found in DataFrame. "
            f"Available columns: {list(df.columns)}"
        )
    
    if lon_name not in df.columns:
        raise ValueError(
            f"Longitude column '{lon_name}' not found in DataFrame. "
            f"Available columns: {list(df.columns)}"
        )
    
    df_len = len(df)
    logger.debug(f"Validating lat/lon values in {df_len} rows")
    
    # Validate coordinate bounds (±180 for both - could be refined to ±90 for lat)
    valid_rows = df[~(
        ((df[lat_name].apply(floor) < -180) | (df[lat_name].apply(ceil) > 180)) |
        ((df[lon_name].apply(floor) < -180) | (df[lon_name].apply(ceil) > 180))
    )]
    
    valid_len = len(valid_rows)
    
    if valid_len == 0:
        raise ValueError(
            f"No valid lat/lon values found. All {df_len} rows have coordinates "
            "outside valid range (±180)"
        )
    
    if df_len > valid_len:
        bad_count = df_len - valid_len
        logger.warning(
            f"Invalid lat/lon values found in {bad_count} rows. "
            f"Dropping invalid rows. Valid rows remaining: {valid_len}"
        )
        df = valid_rows.copy()
    else:
        logger.info(f"All {df_len} rows have valid lat/lon values")
    
    # Create GeoDataFrame with Point geometries
    logger.debug(f"Building GeoDataFrame from lat/lon with {len(df)} rows")
    
    try:
        gdf = GeoDataFrame(
            df,
            geometry=[Point(xy) for xy in zip(df[lon_name], df[lat_name])],
            crs=crs
        )
        logger.info(f"GeoDataFrame created from lat/lon with {len(gdf)} rows")
        return gdf
        
    except Exception as e:
        raise ValueError(
            f"Error building GeoDataFrame from lat/lon columns "
            f"'{lat_name}', '{lon_name}': {e}"
        )


def wkt_df_to_gdf(
    df: DataFrame,
    wkt_column: str,
    crs: str = DEFAULT_CRS_STRING
) -> GeoDataFrame:
    """
    Convert DataFrame with WKT geometry column to GeoDataFrame.
    
    WKT (Well-Known Text) can represent any geometry type:
    Points, LineStrings, Polygons, MultiPolygons, etc.
    
    Args:
        df: DataFrame with WKT geometry column
        wkt_column: Name of column containing WKT strings
        crs: Coordinate reference system (default: EPSG:4326)
    
    Returns:
        GeoDataFrame with parsed geometries
        
    Raises:
        ValueError: If column not found or WKT parsing fails
        
    Example:
        df = pd.DataFrame({
            'name': ['Point A'],
            'geom': ['POINT (-74.0 40.7)']
        })
        gdf = wkt_df_to_gdf(df, 'geom')
    """
    if not isinstance(df, DataFrame):
        raise ValueError(f"Invalid DataFrame provided: {type(df)}")
    
    if wkt_column not in df.columns:
        raise ValueError(
            f"WKT column '{wkt_column}' not found in DataFrame. "
            f"Available columns: {list(df.columns)}"
        )
    
    logger.debug(f"Loading WKT data from column '{wkt_column}'")
    
    try:
        gdf = GeoDataFrame(
            df,
            geometry=df[wkt_column].apply(wkt.loads),
            crs=crs
        )
        logger.info(f"GeoDataFrame created from WKT with {len(gdf)} rows")
        return gdf
        
    except WKTReadingError as e:
        raise ValueError(
            f"WKT parsing error in column '{wkt_column}': {e}. "
            "Check that column contains valid WKT strings."
        )
    
    except ShapelyError as e:
        raise ValueError(
            f"Shapely error processing WKT in column '{wkt_column}': {e}"
        )
    
    except TypeError as e:
        raise ValueError(
            f"Type error processing WKT in column '{wkt_column}': {e}. "
            "Column may contain non-string values."
        )
    
    except Exception as e:
        raise ValueError(
            f"Error building GeoDataFrame from WKT column '{wkt_column}': {e}"
        )


def extract_zip_file(
    zip_data: BytesIO,
    target_extension: str,
    target_name: str = None
) -> tuple[tempfile.TemporaryDirectory, str]:
    """
    Extract a file from a zip archive to a temporary directory.
    
    Used by KMZ and Shapefile converters to extract files from archives.
    
    Args:
        zip_data: BytesIO containing zip archive
        target_extension: File extension to find (e.g., 'kml', 'shp')
        target_name: Optional specific filename to find (with or without extension)
    
    Returns:
        Tuple of (TemporaryDirectory object, path to extracted file)
        Caller must keep temp_dir alive while using the file path
        
    Raises:
        ValueError: If target file not found in archive
        zipfile.BadZipFile: If zip_data is not a valid zip
        
    Example:
        # Extract first KML file found
        temp_dir, kml_path = extract_zip_file(kmz_data, 'kml')
        try:
            gdf = gpd.read_file(kml_path)
        finally:
            temp_dir.cleanup()
        
        # Extract specific shapefile
        temp_dir, shp_path = extract_zip_file(zip_data, 'shp', 'roads.shp')
    """
    target_ext = target_extension.lower().lstrip('.')
    
    logger.debug(f"Extracting .{target_ext} file from zip archive")
    
    # Create temporary directory
    temp_dir = tempfile.TemporaryDirectory()
    
    try:
        # Extract all contents
        with zipfile.ZipFile(zip_data) as z:
            logger.debug(f"Extracting zip contents to {temp_dir.name}")
            z.extractall(temp_dir.name)
            
            # Get list of extracted files
            file_names = z.namelist()
            logger.debug(f"Extracted files: {file_names}")
        
        # Search for target file
        matching_files = []
        
        for file_name in file_names:
            # Skip directories
            if file_name.endswith('/'):
                continue
            
            file_ext = file_name.split('.')[-1].lower() if '.' in file_name else ''
            
            # Match by name if specified
            if target_name:
                # Handle target_name with or without extension
                target_base = target_name.replace(f'.{target_ext}', '')
                file_base = file_name.replace(f'.{file_ext}', '')
                
                if target_name == file_name or target_base in file_name:
                    matching_files.append(file_name)
            
            # Match by extension
            elif file_ext == target_ext:
                matching_files.append(file_name)
        
        if not matching_files:
            temp_dir.cleanup()
            raise ValueError(
                f"No .{target_ext} file"
                f"{f' matching \"{target_name}\"' if target_name else ''} "
                f"found in zip archive. Available files: {file_names}"
            )
        
        if len(matching_files) > 1:
            logger.warning(
                f"Multiple .{target_ext} files found: {matching_files}. "
                f"Using first: {matching_files[0]}"
            )
        
        target_file = matching_files[0]
        file_path = os.path.join(temp_dir.name, target_file)
        
        logger.info(f"Extracted {target_file} to {file_path}")
        
        return temp_dir, file_path
        
    except Exception as e:
        # Clean up temp dir if extraction fails
        temp_dir.cleanup()
        raise


def list_zip_contents(zip_data: BytesIO) -> list[str]:
    """
    List contents of a zip archive.
    
    Args:
        zip_data: BytesIO containing zip archive
    
    Returns:
        List of file names in the archive
        
    Raises:
        zipfile.BadZipFile: If zip_data is not a valid zip
    
    Example:
        contents = list_zip_contents(kmz_data)
        # ['doc.kml', 'files/icon.png']
    """
    logger.debug("Listing zip archive contents")
    
    with zipfile.ZipFile(zip_data) as z:
        file_names = z.namelist()
        logger.debug(f"Zip contains {len(file_names)} files: {file_names}")
        return file_names
