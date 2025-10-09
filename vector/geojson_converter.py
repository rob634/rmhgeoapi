"""
GeoJSON to GeoDataFrame Converter.

Handles .geojson and .json files containing GeoJSON data.
GeoJSON is self-describing, so no additional parameters needed.
"""

from io import BytesIO

from geopandas import GeoDataFrame
from geopandas import read_file as gpd_read_file

from .registry import ConverterRegistry
from utils import logger


@ConverterRegistry.instance().register('geojson', 'json')
class GeoJSONConverter:
    """
    Converts GeoJSON files to GeoDataFrame.
    
    GeoJSON is self-describing - contains geometry type, CRS, and features.
    No additional parameters required.
    
    Usage:
        converter = GeoJSONConverter()
        gdf = converter.convert(geojson_data)
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this converter"""
        return ['geojson', 'json']
    
    def convert(
        self,
        data: BytesIO,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert GeoJSON to GeoDataFrame.
        
        Args:
            data: BytesIO containing GeoJSON data
            **kwargs: Additional arguments passed to geopandas.read_file
        
        Returns:
            GeoDataFrame with geometries
            
        Raises:
            ValueError: If data is not valid GeoJSON
        
        Example:
            gdf = converter.convert(geojson_data)
        """
        logger.debug("Reading GeoJSON file")
        
        try:
            gdf = gpd_read_file(data, **kwargs)
            logger.info(
                f"GeoJSON converted to GeoDataFrame: {len(gdf)} rows, "
                f"geometry type: {gdf.geometry.type.unique().tolist()}"
            )
            return gdf
            
        except Exception as e:
            raise ValueError(f"Error reading GeoJSON file: {e}")
