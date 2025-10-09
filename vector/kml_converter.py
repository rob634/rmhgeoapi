"""
KML to GeoDataFrame Converter.

Handles .kml (Keyhole Markup Language) files.
KML is commonly used by Google Earth and other mapping applications.
"""

from io import BytesIO

from geopandas import GeoDataFrame
from geopandas import read_file as gpd_read_file

from .registry import ConverterRegistry
from utils import logger


@ConverterRegistry.instance().register('kml')
class KMLConverter:
    """
    Converts KML files to GeoDataFrame.
    
    KML (Keyhole Markup Language) is an XML-based format used by
    Google Earth and other mapping applications.
    
    Usage:
        converter = KMLConverter()
        gdf = converter.convert(kml_data)
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this converter"""
        return ['kml']
    
    def convert(
        self,
        data: BytesIO,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert KML to GeoDataFrame.
        
        Args:
            data: BytesIO containing KML data
            **kwargs: Additional arguments passed to geopandas.read_file
        
        Returns:
            GeoDataFrame with geometries
            
        Raises:
            ValueError: If data is not valid KML
        
        Example:
            gdf = converter.convert(kml_data)
        """
        logger.debug("Reading KML file")
        
        try:
            gdf = gpd_read_file(data, **kwargs)
            logger.info(
                f"KML converted to GeoDataFrame: {len(gdf)} rows, "
                f"geometry type: {gdf.geometry.type.unique().tolist()}"
            )
            return gdf
            
        except Exception as e:
            raise ValueError(f"Error reading KML file: {e}")
