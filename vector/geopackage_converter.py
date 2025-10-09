"""
GeoPackage to GeoDataFrame Converter.

Handles .gpkg files, which can contain multiple layers.
Requires layer name to be specified.
"""

from io import BytesIO

from geopandas import GeoDataFrame
from geopandas import read_file as gpd_read_file

from .registry import ConverterRegistry
from utils import logger


@ConverterRegistry.instance().register('gpkg')
class GeoPackageConverter:
    """
    Converts GeoPackage (.gpkg) files to GeoDataFrame.
    
    GeoPackages can contain multiple layers, so layer_name must be specified.
    
    Usage:
        converter = GeoPackageConverter()
        gdf = converter.convert(gpkg_data, layer_name='parcels')
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """File extensions handled by this converter"""
        return ['gpkg']
    
    def convert(
        self,
        data: BytesIO,
        layer_name: str,
        **kwargs
    ) -> GeoDataFrame:
        """
        Convert GeoPackage to GeoDataFrame.
        
        Args:
            data: BytesIO containing GeoPackage data
            layer_name: Name of layer to read from GeoPackage (required)
            **kwargs: Additional arguments passed to geopandas.read_file
        
        Returns:
            GeoDataFrame with geometries from specified layer
            
        Raises:
            ValueError: If layer_name not provided or layer not found
        
        Example:
            gdf = converter.convert(gpkg_data, layer_name='parcels')
        """
        if not layer_name or not isinstance(layer_name, str):
            raise ValueError(
                "layer_name is required for GeoPackage files. "
                f"Received: {layer_name}"
            )
        
        logger.debug(f"Reading GeoPackage layer: {layer_name}")
        
        try:
            gdf = gpd_read_file(data, layer=layer_name, **kwargs)
            logger.info(
                f"GeoPackage layer '{layer_name}' converted to GeoDataFrame: "
                f"{len(gdf)} rows, geometry type: {gdf.geometry.type.unique().tolist()}"
            )
            return gdf
            
        except ValueError as e:
            # GeoPandas raises ValueError if layer not found
            if "not found" in str(e).lower():
                raise ValueError(
                    f"Layer '{layer_name}' not found in GeoPackage. "
                    f"Error: {e}"
                )
            raise
            
        except Exception as e:
            raise ValueError(
                f"Error reading GeoPackage layer '{layer_name}': {e}"
            )
