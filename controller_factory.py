"""
Factory for creating job controllers.

This module provides a factory pattern for instantiating the appropriate
controller based on operation type, similar to ServiceFactory but for
the controller layer.

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
from typing import Optional

from base_controller import BaseJobController
from controller_exceptions import ControllerNotFoundError
from logger_setup import get_logger

logger = get_logger(__name__)


class ControllerFactory:
    """
    Factory class for creating appropriate controller instances.
    
    Maps operation types to controller classes and handles instantiation.
    This enables adding new controllers without modifying routing logic.
    
    Current Mappings:
        - hello_world → HelloWorldController
        - test → HelloWorldController
        - (more to be added in Phase 2)
    """
    
    @staticmethod
    def get_controller(operation_type: str) -> BaseJobController:
        """
        Get the appropriate controller for the operation type.
        
        Args:
            operation_type: Type of operation to perform
            
        Returns:
            BaseJobController: Instantiated controller
            
        Raises:
            ControllerNotFoundError: If no controller exists for operation
        """
        logger.info(f"Getting controller for operation: {operation_type}")
        
        # Hello World operations (for testing)
        if operation_type in ['hello_world', 'test']:
            from hello_world_controller import HelloWorldController
            return HelloWorldController()
        
        # Container operations (to be added in Phase 2)
        elif operation_type == 'list_container':
            # Phase 2: Will wrap ContainerListingService
            logger.warning(f"Controller not yet implemented for {operation_type}, falling back to direct service")
            raise ControllerNotFoundError(operation_type)
        
        # STAC operations (to be added in Phase 2)
        elif operation_type in ['stac_item_quick', 'stac_item_full', 'stac_item_smart', 'catalog_file']:
            # Phase 2: Will wrap STACService
            logger.warning(f"Controller not yet implemented for {operation_type}, falling back to direct service")
            raise ControllerNotFoundError(operation_type)
        
        # Raster operations (to be added in Phase 2)
        elif operation_type in ['cog_conversion', 'validate_raster', 'process_raster']:
            # Phase 2: Will wrap RasterProcessorService
            logger.warning(f"Controller not yet implemented for {operation_type}, falling back to direct service")
            raise ControllerNotFoundError(operation_type)
        
        # Container sync (to be added in Phase 2)
        elif operation_type == 'sync_container':
            # Phase 2: Will create multiple tasks for container sync
            logger.warning(f"Controller not yet implemented for {operation_type}, falling back to direct service")
            raise ControllerNotFoundError(operation_type)
        
        # Tiled raster operations (to be added in Phase 2)
        elif operation_type in ['process_tiled_raster', 'prepare_tiled_cog', 'create_tiled_cog']:
            # Phase 2: Will fix TiledRasterProcessor issues
            logger.warning(f"Controller not yet implemented for {operation_type}, falling back to direct service")
            raise ControllerNotFoundError(operation_type)
        
        # Default: No controller found
        else:
            logger.error(f"No controller found for operation type: {operation_type}")
            raise ControllerNotFoundError(operation_type)
    
    @staticmethod
    def has_controller(operation_type: str) -> bool:
        """
        Check if a controller exists for the operation type.
        
        Args:
            operation_type: Operation to check
            
        Returns:
            bool: True if controller exists
        """
        try:
            ControllerFactory.get_controller(operation_type)
            return True
        except ControllerNotFoundError:
            return False
    
    @staticmethod
    def list_available_controllers() -> list:
        """
        List all available controller operation types.
        
        Returns:
            list: Operation types with controllers
        """
        # For now, just hello_world is implemented
        return [
            'hello_world',
            'test'
        ]
        # Phase 2 will add:
        # 'list_container',
        # 'stac_item_quick', 'stac_item_full', 'stac_item_smart', 'catalog_file',
        # 'cog_conversion', 'validate_raster', 'process_raster',
        # 'sync_container',
        # 'process_tiled_raster', 'prepare_tiled_cog', 'create_tiled_cog'