"""
Shapefile to GeoDataFrame Converter.

Handles .shp files within .zip archives.
Shapefiles consist of multiple files (.shp, .shx, .dbf, etc.) that must be
kept together, so they're typically distributed as zip archives.
"""

from io import BytesIO

from geopandas import GeoDataFrame
from geopandas import read_file as gpd_read_file

from .registry import ConverterRegistry
from .helpers import extract_zip_file
from utils import logger


@ConverterRegistry.instance().register('shp', 'zip')
class ShapefileConverter:
    """
    Converts Shapefile (.shp in .zip) to GeoDataFrame.
    
    Shapefiles are multi-file formats (.shp, .shx, .dbf, .prj, etc.) that
    are typically distributed as zip archives. This converter extracts the
    shapefile and converts it.
    
    Note: Registered for both 'shp' and 'zip' extensions.
    
    Usage:
        converter = ShapefileConverter()
        
        # Use first shapefile found
        gdf = converter.convert(zip_data)
        
        # Use specific shapefile
        gdf = converter.convert(zip_data, shp_name='roads.shp')
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this converter"""
        return ['shp', 'zip']
    
    def convert(
        self,
        data: BytesIO,
        shp_name: str = None,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert Shapefile (in zip) to GeoDataFrame.
        
        Args:
            data: BytesIO containing zip archive with shapefile
            shp_name: Optional name of specific .shp file in archive.
                     If not provided, uses first .shp found.
                     Can be provided with or without .shp extension.
            **kwargs: Additional arguments passed to geopandas.read_file
        
        Returns:
            GeoDataFrame with geometries from shapefile
            
        Raises:
            ValueError: If no shapefile found in archive
        
        Examples:
            # Use first shapefile found
            gdf = converter.convert(zip_data)
            
            # Use specific shapefile
            gdf = converter.convert(zip_data, shp_name='roads.shp')
            
            # Can also omit .shp extension
            gdf = converter.convert(zip_data, shp_name='roads')
        """
        logger.debug(
            f"Extracting shapefile from zip"
            f"{f' (looking for {shp_name})' if shp_name else ''}"
        )
        
        try:
            # Extract shapefile from zip archive
            temp_dir, shp_path = extract_zip_file(
                data,
                target_extension='shp',
                target_name=shp_name
            )
            
            try:
                # Read extracted shapefile
                # GeoPandas will automatically find companion files (.shx, .dbf, etc.)
                logger.debug(f"Reading extracted shapefile from {shp_path}")
                gdf = gpd_read_file(shp_path, **kwargs)
                logger.info(
                    f"Shapefile converted to GeoDataFrame: {len(gdf)} rows, "
                    f"geometry type: {gdf.geometry.type.unique().tolist()}"
                )
                return gdf
                
            finally:
                # Clean up temp directory
                temp_dir.cleanup()
                logger.debug("Cleaned up temporary directory")
                
        except ValueError:
            # Re-raise ValueError from extract_zip_file (no shapefile found)
            raise
            
        except Exception as e:
            raise ValueError(f"Error reading shapefile from zip: {e}")
