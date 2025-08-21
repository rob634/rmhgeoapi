"""Service factory for creating appropriate service instances."""

from typing import Optional
from services.base_service import BaseProcessingService
from core.constants import Operations
import logging

logger = logging.getLogger(__name__)


class ServiceFactory:
    """Factory for creating processing service instances."""
    
    @staticmethod
    def get_service(operation_type: str) -> Optional[BaseProcessingService]:
        """
        Get the appropriate service for the given operation type.
        
        Args:
            operation_type: Type of operation to perform
            
        Returns:
            Service instance or None if not found
        """
        logger.info(f"Getting service for operation: {operation_type}")
        
        # Import services as needed to avoid circular imports
        if operation_type == Operations.LIST_CONTAINER:
            from services.container import ContainerListingService
            return ContainerListingService()
            
        elif operation_type == Operations.DATABASE_INTROSPECTION:
            from services.database.introspection import DatabaseIntrospectionService
            return DatabaseIntrospectionService()
            
        elif operation_type in Operations.get_stac_operations():
            from services.stac_item import STACItemService
            return STACItemService()
            
        elif operation_type in [Operations.COG_CONVERSION]:
            # Raster processing not yet implemented
            # from services.raster_processing import RasterProcessingService
            from services.hello_world import HelloWorldService  # Temporary fallback
            return HelloWorldService()
            
        else:
            # Default to hello world for unknown operations
            from services.hello_world import HelloWorldService
            return HelloWorldService()
    
    @staticmethod
    def get_all_operations() -> list:
        """Get list of all supported operations."""
        return [
            Operations.HELLO_WORLD,
            Operations.LIST_CONTAINER,
            Operations.DATABASE_INTROSPECTION,
            Operations.COG_CONVERSION,
            Operations.VECTOR_UPLOAD,
        ] + Operations.get_stac_operations()