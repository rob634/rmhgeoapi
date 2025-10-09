"""
KMZ to GeoDataFrame Converter.

Handles .kmz (compressed KML) files.
KMZ is a zipped KML file, commonly used by Google Earth.
"""

from io import BytesIO

from geopandas import GeoDataFrame
from geopandas import read_file as gpd_read_file

from .registry import ConverterRegistry
from .helpers import extract_zip_file
from utils import logger


@ConverterRegistry.instance().register('kmz')
class KMZConverter:
    """
    Converts KMZ (compressed KML) files to GeoDataFrame.
    
    KMZ is a zipped archive containing one or more KML files.
    This converter extracts the KML and converts it.
    
    Usage:
        converter = KMZConverter()
        
        # Use first KML found
        gdf = converter.convert(kmz_data)
        
        # Use specific KML file
        gdf = converter.convert(kmz_data, kml_name='doc.kml')
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this converter"""
        return ['kmz']
    
    def convert(
        self,
        data: BytesIO,
        kml_name: str = None,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert KMZ to GeoDataFrame.
        
        Args:
            data: BytesIO containing KMZ (zipped KML) data
            kml_name: Optional name of specific KML file in archive.
                     If not provided, uses first KML found.
            **kwargs: Additional arguments passed to geopandas.read_file
        
        Returns:
            GeoDataFrame with geometries from extracted KML
            
        Raises:
            ValueError: If no KML file found in archive
        
        Examples:
            # Use first KML found
            gdf = converter.convert(kmz_data)
            
            # Use specific KML
            gdf = converter.convert(kmz_data, kml_name='my_data.kml')
        """
        logger.debug(
            f"Extracting KML from KMZ"
            f"{f' (looking for {kml_name})' if kml_name else ''}"
        )
        
        try:
            # Extract KML from zip archive
            temp_dir, kml_path = extract_zip_file(
                data,
                target_extension='kml',
                target_name=kml_name
            )
            
            try:
                # Read extracted KML
                logger.debug(f"Reading extracted KML from {kml_path}")
                gdf = gpd_read_file(kml_path, **kwargs)
                logger.info(
                    f"KMZ converted to GeoDataFrame: {len(gdf)} rows, "
                    f"geometry type: {gdf.geometry.type.unique().tolist()}"
                )
                return gdf
                
            finally:
                # Clean up temp directory
                temp_dir.cleanup()
                logger.debug("Cleaned up temporary directory")
                
        except ValueError:
            # Re-raise ValueError from extract_zip_file (no KML found)
            raise
            
        except Exception as e:
            raise ValueError(f"Error reading KMZ file: {e}")
