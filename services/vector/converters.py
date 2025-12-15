"""
Format-Specific Vector Converters.

Private helper functions for converting various file formats to GeoDataFrame.
Called by the load_vector_file task.

Exports:
    _convert_csv: Convert CSV with lat/lon or WKT
    _convert_geojson: Convert GeoJSON/JSON files
    _convert_geopackage: Convert GeoPackage with layer selection
    _convert_kml: Convert KML files
    _convert_kmz: Convert KMZ (zipped KML) files
    _convert_shapefile: Convert Shapefile (zipped)
"""

from io import BytesIO
from typing import Optional
import logging
import pandas as pd
import geopandas as gpd
from .helpers import xy_df_to_gdf, wkt_df_to_gdf, extract_zip_file, DEFAULT_CRS
from util_logger import LoggerFactory, ComponentType

# Component-specific logger for structured logging (Application Insights)
logger = LoggerFactory.create_logger(
    ComponentType.SERVICE,
    "vector_converters"
)


def _convert_csv(
    data: BytesIO,
    lat_name: Optional[str] = None,
    lon_name: Optional[str] = None,
    wkt_column: Optional[str] = None,
    **kwargs
) -> gpd.GeoDataFrame:
    """
    Convert CSV to GeoDataFrame (lat/lon or WKT).

    Args:
        data: BytesIO containing CSV data
        lat_name: Latitude column name (for point geometry)
        lon_name: Longitude column name (for point geometry)
        wkt_column: WKT geometry column name (alternative to lat/lon)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame with geometries

    Raises:
        ValueError: If neither lat/lon nor wkt_column provided
        ValueError: If specified columns don't exist in CSV (GAP-008b)
    """
    if not (wkt_column or (lat_name and lon_name)):
        raise ValueError(
            "CSV conversion requires either 'wkt_column' or both 'lat_name' and 'lon_name'"
        )

    # Read CSV to DataFrame
    df = pd.read_csv(data)

    # GAP-008b FIX (15 DEC 2025): Validate that specified columns exist in the CSV
    # This gives a clear error message when parameters don't match file contents
    csv_columns = list(df.columns)

    if wkt_column:
        if wkt_column not in csv_columns:
            raise ValueError(
                f"WKT column '{wkt_column}' not found in CSV file. "
                f"Available columns: {csv_columns[:20]}{'...' if len(csv_columns) > 20 else ''}"
            )
    else:
        missing_cols = []
        if lat_name not in csv_columns:
            missing_cols.append(f"lat_name='{lat_name}'")
        if lon_name not in csv_columns:
            missing_cols.append(f"lon_name='{lon_name}'")

        if missing_cols:
            raise ValueError(
                f"Geometry column(s) not found in CSV file: {', '.join(missing_cols)}. "
                f"Available columns: {csv_columns[:20]}{'...' if len(csv_columns) > 20 else ''}"
            )

    logger.info(f"✅ CSV column validation passed: using {'wkt_column=' + wkt_column if wkt_column else f'lat={lat_name}, lon={lon_name}'}")

    # Convert based on provided parameters
    if wkt_column:
        return wkt_df_to_gdf(df, wkt_column)
    else:
        return xy_df_to_gdf(df, lat_name, lon_name)


def _convert_geojson(data: BytesIO, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert GeoJSON to GeoDataFrame.

    Args:
        data: BytesIO containing GeoJSON data
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame
    """
    return gpd.read_file(data)


def _convert_geopackage(data: BytesIO, layer_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert GeoPackage to GeoDataFrame.

    Args:
        data: BytesIO containing GeoPackage data
        layer_name: Layer name to extract (optional, defaults to first layer)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        ValueError: If specified layer_name does not exist in GeoPackage

    Notes:
        If layer_name not provided, reads the first available layer.
        GeoPackage files can contain multiple layers.
        Invalid layer names will raise ValueError with explicit error message.
    """
    try:
        if layer_name:
            # Explicit layer requested - will fail if layer doesn't exist
            return gpd.read_file(data, layer=layer_name)
        else:
            # Read first layer (or only layer if single-layer GPKG)
            return gpd.read_file(data)
    except Exception as e:
        # Re-raise with explicit context about layer validation
        if layer_name and ('layer' in str(e).lower() or 'not found' in str(e).lower()):
            raise ValueError(
                f"Layer '{layer_name}' not found in GeoPackage. "
                f"Original error: {type(e).__name__}: {e}"
            ) from e
        else:
            # Other errors (file corruption, etc.) - re-raise as-is
            raise


def _convert_kml(data: BytesIO, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert KML to GeoDataFrame.

    Args:
        data: BytesIO containing KML data
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame
    """
    return gpd.read_file(data)


def _convert_kmz(data: BytesIO, kml_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert KMZ (zipped KML) to GeoDataFrame.

    Args:
        data: BytesIO containing KMZ data
        kml_name: Specific KML filename in archive (optional, uses first .kml found)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame
    """
    kml_path = extract_zip_file(data, '.kml', kml_name)
    return gpd.read_file(kml_path)


def _convert_shapefile(data: BytesIO, shp_name: Optional[str] = None, **kwargs) -> gpd.GeoDataFrame:
    """
    Convert Shapefile (in ZIP) to GeoDataFrame.

    Args:
        data: BytesIO containing zipped shapefile
        shp_name: Specific .shp filename in archive (optional, uses first .shp found)
        **kwargs: Additional arguments (ignored)

    Returns:
        GeoDataFrame

    Raises:
        Exception: If shapefile cannot be read or has no geometries
    """
    shp_path = extract_zip_file(data, '.shp', shp_name)
    logger.info(f"📂 Reading shapefile from: {shp_path}")

    gdf = gpd.read_file(shp_path)

    # Log initial load stats with detailed diagnostics
    logger.info(f"📊 Shapefile loaded - diagnostics:")
    logger.info(f"   - Total rows read: {len(gdf)}")
    logger.info(f"   - Columns: {list(gdf.columns)}")
    logger.info(f"   - CRS: {gdf.crs}")

    if 'geometry' in gdf.columns:
        logger.info(f"   - Geometry column type: {gdf['geometry'].dtype}")
        null_count = gdf.geometry.isna().sum()
        logger.info(f"   - Null geometries on load: {null_count}")

        if len(gdf) > 0 and not gdf.geometry.isna().all():
            # Show geometry types if any valid geometries exist
            valid_geoms = gdf[~gdf.geometry.isna()]
            if len(valid_geoms) > 0:
                geom_types = valid_geoms.geometry.geom_type.value_counts().to_dict()
                logger.info(f"   - Geometry types found: {geom_types}")

                # Sample first few geometries for debugging
                if len(valid_geoms) > 0:
                    sample_geom = valid_geoms.iloc[0].geometry
                    logger.info(f"   - Sample geometry: type={sample_geom.geom_type}, bounds={sample_geom.bounds}")
        else:
            logger.warning(f"   - ⚠️  All {len(gdf)} rows have NULL geometries!")
    else:
        logger.error(f"   - ❌ CRITICAL: No 'geometry' column found in shapefile!")
        logger.error(f"   - Available columns: {list(gdf.columns)}")

    return gdf
