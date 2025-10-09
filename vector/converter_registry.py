"""
Converter Registry - Singleton registry for vector file converters.

Maps file extensions to converter classes using decorator-based registration.
Similar pattern to JobRegistry and TaskRegistry.
"""

from typing import Dict, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import VectorConverter

from utils import logger


class ConverterRegistry:
    """
    Singleton registry mapping file extensions to converter classes.
    
    Usage:
        # Register a converter
        @ConverterRegistry.instance().register('csv')
        class CSVConverter:
            def convert(self, data, **kwargs):
                ...
        
        # Get a converter
        converter = ConverterRegistry.instance().get_converter('csv')
        gdf = converter.convert(file_data, lat_name='lat', lon_name='lon')
    """
    
    _instance = None
    
    def __init__(self):
        """Private constructor - use instance() instead"""
        self._converters: Dict[str, Type['VectorConverter']] = {}
        logger.info("ConverterRegistry initialized")
    
    @classmethod
    def instance(cls) -> 'ConverterRegistry':
        """
        Get singleton instance of ConverterRegistry.
        
        Returns:
            ConverterRegistry singleton instance
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, *extensions: str):
        """
        Decorator to register a converter for one or more file extensions.
        
        Args:
            *extensions: File extensions this converter handles (e.g., 'csv', 'gpkg')
        
        Returns:
            Decorator function
            
        Example:
            @ConverterRegistry.instance().register('csv')
            class CSVConverter:
                def convert(self, data, **kwargs):
                    ...
            
            # Register for multiple extensions
            @ConverterRegistry.instance().register('geojson', 'json')
            class GeoJSONConverter:
                def convert(self, data, **kwargs):
                    ...
        """
        def decorator(converter_class: Type['VectorConverter']):
            for ext in extensions:
                ext_clean = ext.lower().lstrip('.')
                
                if ext_clean in self._converters:
                    logger.warning(
                        f"Overwriting existing converter for .{ext_clean}: "
                        f"{self._converters[ext_clean].__name__} → {converter_class.__name__}"
                    )
                
                self._converters[ext_clean] = converter_class
                logger.debug(f"Registered {converter_class.__name__} for .{ext_clean}")
            
            return converter_class
        
        return decorator
    
    def get_converter(self, extension: str) -> 'VectorConverter':
        """
        Get converter instance for a file extension.
        
        Args:
            extension: File extension (with or without leading dot)
        
        Returns:
            Instantiated converter object
            
        Raises:
            ValueError: If no converter registered for extension
            
        Example:
            converter = registry.get_converter('csv')
            gdf = converter.convert(file_data, lat_name='lat', lon_name='lon')
        """
        ext_clean = extension.lower().lstrip('.')
        
        if ext_clean not in self._converters:
            available = ', '.join(sorted(self._converters.keys()))
            raise ValueError(
                f"No converter registered for '.{ext_clean}'. "
                f"Available: {available}"
            )
        
        converter_class = self._converters[ext_clean]
        logger.debug(f"Retrieved {converter_class.__name__} for .{ext_clean}")
        
        return converter_class()
    
    def is_supported(self, extension: str) -> bool:
        """
        Check if a file extension is supported.
        
        Args:
            extension: File extension to check
        
        Returns:
            True if supported, False otherwise
        """
        ext_clean = extension.lower().lstrip('.')
        return ext_clean in self._converters
    
    def list_supported_extensions(self) -> list[str]:
        """
        Get list of all supported file extensions.
        
        Returns:
            Sorted list of supported extensions
        """
        return sorted(self._converters.keys())
    
    def clear(self):
        """Clear all registered converters (useful for testing)"""
        self._converters.clear()
        logger.debug("ConverterRegistry cleared")
