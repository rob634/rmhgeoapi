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
    
    The factory pattern provides several benefits:
        1. Decouples controller creation from usage
        2. Centralizes operation routing decisions
        3. Enables easy addition of new controllers
        4. Supports gradual migration from services to controllers
    
    Current Implementation Status:
        Phase 1 (COMPLETE):
            - hello_world → HelloWorldController ✅
            - test → HelloWorldController ✅
            
        Phase 2 (IN PROGRESS):
            - list_container → ContainerController ✅ DEPLOYED
            - sync_container → ContainerController ✅ DEPLOYED
            - catalog_file → STACController (TODO - Next Priority)
            
        Phase 3 (PLANNED):
            - cog_conversion → RasterController
            - validate_raster → RasterController
            - process_tiled_raster → TiledRasterController
    
    Usage:
        >>> controller = ControllerFactory.get_controller('hello_world')
        >>> job_id = controller.process_job(request)
    """
    
    # Class-level cache for controller instances (singleton pattern)
    _controller_cache = {}
    
    @staticmethod
    def get_controller(operation_type: str) -> BaseJobController:
        """
        Get the appropriate controller for the operation type.
        
        Uses a singleton pattern with caching to avoid recreating controllers
        for repeated requests. Controllers are stateless and thread-safe.
        
        Args:
            operation_type: Type of operation to perform (e.g., 'hello_world', 
                          'list_container', 'cog_conversion')
            
        Returns:
            BaseJobController: Instantiated controller ready to process jobs
            
        Raises:
            ControllerNotFoundError: If no controller exists for the operation.
                                   The error includes the operation type and
                                   suggests falling back to direct service.
        
        Example:
            >>> try:
            ...     controller = ControllerFactory.get_controller('hello_world')
            ...     job_id = controller.process_job(request)
            ... except ControllerNotFoundError:
            ...     # Fall back to direct service call
            ...     service = ServiceFactory.get_service('hello_world')
            ...     result = service.process(request)
        """
        logger.info(f"Getting controller for operation: {operation_type}")
        
        # Check cache first for efficiency
        if operation_type in ControllerFactory._controller_cache:
            logger.debug(f"Returning cached controller for {operation_type}")
            return ControllerFactory._controller_cache[operation_type]
        
        controller = None
        
        # Hello World operations (Phase 1 - COMPLETE)
        if operation_type in ['hello_world', 'test']:
            from hello_world_controller import HelloWorldController
            controller = HelloWorldController()
        
        # Container operations (Phase 2 - IMPLEMENTED)
        elif operation_type in ['list_container', 'sync_container']:
            from container_controller import ContainerController
            controller = ContainerController()
            logger.info(f"Using ContainerController for {operation_type}")
        
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
        
        # Tiled raster operations (to be added in Phase 2)
        elif operation_type in ['process_tiled_raster', 'prepare_tiled_cog', 'create_tiled_cog']:
            # Phase 2: Will fix TiledRasterProcessor issues
            logger.warning(f"Controller not yet implemented for {operation_type}, falling back to direct service")
            raise ControllerNotFoundError(operation_type)
        
        # Cache the controller if one was created
        if controller:
            ControllerFactory._controller_cache[operation_type] = controller
            logger.debug(f"Cached new controller for {operation_type}")
            return controller
        
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
            list: Operation types with implemented controllers
            
        Example:
            >>> available = ControllerFactory.list_available_controllers()
            >>> print(f"Available controllers: {', '.join(available)}")
            Available controllers: hello_world, test
        """
        # Phase 1 - COMPLETE
        # Phase 2 - IN PROGRESS
        implemented = [
            'hello_world',
            'test',
            'list_container',
            'sync_container'
        ]
        
        # Phase 2 - IN PROGRESS (will be added as implemented)
        # upcoming = [
        #     'list_container',
        #     'sync_container', 
        #     'catalog_file',
        #     'stac_item_quick', 
        #     'stac_item_full', 
        #     'stac_item_smart'
        # ]
        
        # Phase 3 - PLANNED
        # planned = [
        #     'cog_conversion',
        #     'validate_raster',
        #     'process_raster',
        #     'process_tiled_raster',
        #     'prepare_tiled_cog',
        #     'create_tiled_cog'
        # ]
        
        return implemented
    
    @staticmethod
    def clear_cache() -> None:
        """
        Clear the controller cache.
        
        Useful for testing or when controllers need to be reinitialized.
        Controllers are stateless, so this is generally safe to call.
        
        Example:
            >>> ControllerFactory.clear_cache()
            >>> # Next get_controller() call will create fresh instance
        """
        ControllerFactory._controller_cache.clear()
        logger.info("Controller cache cleared")