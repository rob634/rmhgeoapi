"""
CSV to GeoDataFrame Converter.

Handles CSV files with either:
1. Separate latitude and longitude columns (creates Point geometries)
2. WKT geometry column (any geometry type)
"""

from io import BytesIO

from geopandas import GeoDataFrame
from pandas import read_csv

from .registry import ConverterRegistry
from .helpers import xy_df_to_gdf, wkt_df_to_gdf
from utils import logger, DEFAULT_CRS_STRING


@ConverterRegistry.instance().register('csv')
class CSVConverter:
    """
    Converts CSV files to GeoDataFrame.
    
    Supports two modes:
    1. Lat/lon columns: Creates Point geometries from separate coordinate columns
    2. WKT column: Parses WKT strings into any geometry type
    
    Usage:
        converter = CSVConverter()
        
        # Lat/lon mode
        gdf = converter.convert(csv_data, lat_name='lat', lon_name='lon')
        
        # WKT mode
        gdf = converter.convert(csv_data, wkt_column='geometry')
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this converter"""
        return ['csv']
    
    def convert(
        self,
        data: BytesIO,
        lat_name: str = None,
        lon_name: str = None,
        wkt_column: str = None,
        crs: str = DEFAULT_CRS_STRING,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert CSV to GeoDataFrame.
        
        Args:
            data: BytesIO containing CSV data
            lat_name: Latitude column name (required if not using wkt_column)
            lon_name: Longitude column name (required if not using wkt_column)
            wkt_column: WKT geometry column name (required if not using lat/lon)
            crs: Coordinate reference system (default: EPSG:4326)
            **kwargs: Additional arguments passed to pandas.read_csv
        
        Returns:
            GeoDataFrame with geometries
            
        Raises:
            ValueError: If neither lat/lon nor wkt_column provided,
                       or if required columns not found in CSV
        
        Examples:
            # Lat/lon mode
            gdf = converter.convert(
                csv_data,
                lat_name='latitude',
                lon_name='longitude'
            )
            
            # WKT mode
            gdf = converter.convert(
                csv_data,
                wkt_column='geometry'
            )
        """
        # Validate parameters
        has_latlon = lat_name and lon_name
        has_wkt = wkt_column
        
        if not has_latlon and not has_wkt:
            raise ValueError(
                "Must provide either (lat_name AND lon_name) OR wkt_column. "
                "Received: lat_name={}, lon_name={}, wkt_column={}".format(
                    lat_name, lon_name, wkt_column
                )
            )
        
        if has_latlon and has_wkt:
            logger.warning(
                f"Both lat/lon ({lat_name}/{lon_name}) and wkt_column ({wkt_column}) "
                "provided. Using wkt_column."
            )
        
        # Read CSV to DataFrame
        logger.debug("Reading CSV file")
        df = read_csv(data, **kwargs)
        logger.info(f"DataFrame created from CSV with {len(df)} rows")
        
        # Convert based on mode
        if wkt_column:
            logger.debug(f"Converting CSV using WKT column: {wkt_column}")
            gdf = wkt_df_to_gdf(df, wkt_column, crs=crs)
            
        else:  # lat/lon mode
            logger.debug(f"Converting CSV using lat/lon: {lat_name}, {lon_name}")
            gdf = xy_df_to_gdf(df, lat_name, lon_name, crs=crs)
        
        logger.info(
            f"CSV converted to GeoDataFrame: {len(gdf)} rows, "
            f"geometry type: {gdf.geometry.type.unique().tolist()}"
        )
        
        return gdf
