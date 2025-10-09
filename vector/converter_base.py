"""
Base Protocol for Vector Converters.

This defines the interface that all converters should implement.
It's a Protocol (not a base class) - converters don't inherit from it,
but it provides type hints and documentation.
"""

from io import BytesIO
from typing import Protocol, runtime_checkable

from geopandas import GeoDataFrame


@runtime_checkable
class VectorConverter(Protocol):
    """
    Protocol defining the interface for vector file converters.
    
    All converters must implement:
    - convert() method that takes BytesIO and returns GeoDataFrame
    - supported_extensions property listing handled file extensions
    
    Converters do NOT inherit from this class - it's just a protocol
    for type checking and documentation.
    
    Example:
        @ConverterRegistry.instance().register('csv')
        class CSVConverter:  # No inheritance!
            
            @property
            def supported_extensions(self) -> list[str]:
                return ['csv']
            
            def convert(self, data: BytesIO, **kwargs) -> GeoDataFrame:
                # Implementation here
                pass
    """
    
    @property
    def supported_extensions(self) -> list[str]:
        """
        List of file extensions this converter handles.
        
        Returns:
            List of extensions (without leading dots)
            
        Example:
            ['csv'] or ['geojson', 'json']
        """
        ...
    
    def convert(self, data: BytesIO, **kwargs) -> GeoDataFrame:
        """
        Convert file data to GeoDataFrame.
        
        Args:
            data: BytesIO object containing file data
            **kwargs: Format-specific parameters
                     (e.g., lat_name/lon_name for CSV, layer_name for GPKG)
        
        Returns:
            GeoDataFrame with geometries
            
        Raises:
            ValueError: If conversion fails or required parameters missing
            
        Example:
            converter = CSVConverter()
            gdf = converter.convert(
                file_data,
                lat_name='latitude',
                lon_name='longitude'
            )
        """
        ...
