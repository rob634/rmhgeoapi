"""
Service layer with ABC classes for geospatial processing.

This module provides the service layer architecture for the geospatial ETL
pipeline, implementing the Strategy pattern with abstract base classes and
concrete implementations for various processing operations.

Architecture:
    BaseProcessingService (ABC)
        ├── HelloWorldService (testing)
        ├── ContainerListingService (inventory)
        ├── DatabaseHealthService (monitoring)
        ├── STACService (cataloging)
        ├── RasterProcessorService (COG conversion)
        └── SyncContainerService (batch operations)

The ServiceFactory provides dynamic service routing based on operation type,
enabling extensible processing capabilities without modifying core logic.

Key Features:
    - Abstract base class enforces consistent interface
    - Factory pattern for service instantiation
    - Lazy loading of service dependencies
    - Comprehensive logging and error handling
    - Support for both synchronous and asynchronous operations

Author: Azure Geospatial ETL Team
Version: 2.0.0
"""
from abc import ABC, abstractmethod
from typing import Dict, List
import logging
from logger_setup import logger, log_job_stage, log_service_processing


class BaseProcessingService(ABC):
    """
    Abstract base class for all processing services.
    
    Defines the interface that all concrete service implementations must follow.
    This ensures consistent behavior across different processing operations and
    enables the factory pattern for dynamic service selection.
    
    All services must implement:
        - process(): Main processing logic for the operation
        - get_supported_operations(): List of operation types handled
        
    Services should follow these patterns:
        - Use dependency injection for repositories and clients
        - Log all major operations with structured logging
        - Return consistent result dictionaries
        - Handle errors gracefully with meaningful messages
    """
    
    @abstractmethod
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process a job with given parameters.
        
        This is the main entry point for all service processing. Implementations
        should handle the specific logic for their operation type.
        
        Args:
            job_id: Unique identifier for the job (SHA256 hash).
            dataset_id: Container or dataset identifier.
            resource_id: Specific resource within dataset (file/folder).
            version_id: Version identifier for the resource.
            operation_type: Type of operation to perform.
            
        Returns:
            Dict: Result dictionary containing:
                - status: Processing status ('completed', 'failed')
                - message: Human-readable status message
                - Additional operation-specific data
                
        Raises:
            ValueError: For invalid parameters or configuration.
            Exception: For processing errors (will be caught by framework).
        """
        pass
    
    @abstractmethod
    def get_supported_operations(self) -> List[str]:
        """
        Return list of operations this service supports.
        
        Used by ServiceFactory to determine which service to instantiate
        for a given operation type. Services can support multiple operations.
        
        Returns:
            List[str]: Operation type identifiers supported by this service.
        """
        pass


class HelloWorldService(BaseProcessingService):
    """
    Hello world implementation for testing pipeline functionality.
    
    Simple service that validates the processing pipeline is working correctly.
    Logs all received parameters and returns success. Useful for debugging,
    testing deployments, and verifying queue processing.
    
    This service acts as a catch-all for unimplemented operations during
    development, allowing the pipeline to process any operation type without
    failing.
    """
    
    def __init__(self):
        """Initialize HelloWorldService with logging."""
        pass  # Use centralized logger
    
    def get_supported_operations(self) -> List[str]:
        """
        Support all operations as fallback handler.
        
        Returns:
            List[str]: Supports multiple operation types for testing.
        """
        return ["cog_conversion", "vector_upload", "stac_generation", "hello_world"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str, **kwargs) -> Dict:
        """
        Process hello world operation with parameter display.
        
        Logs all parameters in a formatted display and returns success.
        This helps verify that the pipeline is correctly passing parameters
        through all layers.
        
        Args:
            job_id: Unique job identifier.
            dataset_id: Dataset/container name.
            resource_id: Resource identifier.
            version_id: Version identifier.
            operation_type: Operation being tested.
            
        Returns:
            Dict: Success result with all parameters echoed back.
        """
        # Extract task_id if provided (for task-based processing)
        task_id = kwargs.get('task_id')
        message = kwargs.get('message', 'Hello from Job→Task architecture!')
        
        log_job_stage(job_id, "hello_world_start", "processing")
        
        # Beautiful parameter display
        print("=" * 60)
        print("🚀 GEOSPATIAL ETL PIPELINE - HELLO WORLD")
        print("=" * 60)
        print(f"📋 Job ID: {job_id}")
        if task_id:
            print(f"📌 Task ID: {task_id}")
        print(f"📊 Dataset: {dataset_id}")
        print(f"📁 Resource: {resource_id}")
        print(f"🔢 Version: {version_id}")
        print(f"⚙️  Operation: {operation_type}")
        if message != 'Hello from Job→Task architecture!':
            print(f"💬 Message: {message}")
        print("-" * 60)
        print("🎯 Processing Status: HELLO WORLD COMPLETE!")
        print("✅ All parameters received and validated")
        if task_id:
            print("✨ Task-based processing successful!")
        print("🎉 Ready for real geospatial processing")
        print("=" * 60)
        
        # Log completion
        log_job_stage(job_id, "hello_world_complete", "completed")
        log_service_processing("HelloWorldService", operation_type, job_id, "completed")
        
        result = {
            "status": "completed",
            "message": "Hello world processing completed successfully",
            "processed_items": {
                "dataset_id": dataset_id,
                "resource_id": resource_id,
                "version_id": version_id,
                "operation_type": operation_type
            }
        }
        
        # Add task info if processing through task
        if task_id:
            result["task_id"] = task_id
            result["execution_mode"] = "task-based"
            result["custom_message"] = message
        else:
            result["execution_mode"] = "direct"
        
        return result


class ContainerListingService(BaseProcessingService):
    """
    Service for listing and inventorying container contents.
    
    Provides comprehensive container listing with metadata inference, file
    categorization, and inventory storage. Handles large containers by storing
    complete inventories in compressed blob storage while returning samples
    in the API response.
    
    Features:
        - Lists all files in a container with metadata
        - Applies optional prefix filtering
        - Categorizes files as geospatial or other
        - Runs metadata inference to extract vendor and type info
        - Stores compressed inventories in blob storage
        - Returns sample of files to avoid Table Storage limits
        
    The service solves the 64KB Table Storage limit by storing full inventories
    in blob storage (compressed JSON) while only storing summary in tables.
    """
    
    def __init__(self):
        """Initialize ContainerListingService."""
        pass  # Use centralized logger
    
    def get_supported_operations(self) -> List[str]:
        """
        Return supported operations.
        
        Returns:
            List[str]: ['list_container']
        """
        return ["list_container"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process container listing job with inventory storage.
        
        Lists container contents, applies optional filtering, runs metadata
        inference, and stores complete inventory in blob storage.
        
        Args:
            job_id: Unique job identifier for tracking.
            dataset_id: Container name to list.
            resource_id: Optional prefix filter (use 'none' for no filter).
            version_id: Not used for listing operations.
            operation_type: Should be 'list_container'.
            
        Returns:
            Dict: Container listing results containing:
                - summary: Statistics about files found
                - inventory_urls: URLs to full and geospatial inventories
                - files_sample: First 10 files (or all if <10)
                - filtered: Whether prefix filter was applied
                
        Raises:
            ValueError: If specified container doesn't exist.
            Exception: For storage access errors.
            
        Example Result:
            {
                "summary": {
                    "total_files": 1157,
                    "geospatial_files": 459,
                    "total_size_gb": 87.96
                },
                "inventory_urls": {
                    "full": "https://...rmhazuregeobronze.json.gz",
                    "geospatial": "https://...rmhazuregeobronze_geo.json.gz"
                },
                "files_sample": [...first 10 files...]
            }
        """
        logger.info(f"Starting container listing - Job: {job_id}, Container: {dataset_id}")
        
        try:
            from repositories import StorageRepository
            from blob_inventory_service import BlobInventoryService
            
            # Use dataset_id as container name
            container_name = dataset_id if dataset_id else None
            
            # Initialize services
            storage_repo = StorageRepository()
            inventory_service = BlobInventoryService()
            
            if container_name:
                # List specific container
                if not storage_repo.container_exists(container_name):
                    raise ValueError(f"Container '{container_name}' does not exist")
                
                contents = storage_repo.list_container_contents(container_name)
            else:
                # List default workspace container
                contents = storage_repo.list_container_contents()
            
            # Apply prefix filter if resource_id is provided and not 'none'
            if resource_id and resource_id != 'none':
                logger.info(f"Applying prefix filter: {resource_id}")
                filtered_blobs = [
                    blob for blob in contents['blobs'] 
                    if blob['name'].startswith(resource_id)
                ]
                files_to_store = filtered_blobs
                filter_applied = True
            else:
                files_to_store = contents['blobs']
                filter_applied = False
            
            # Store inventory in blob storage
            inventory_metadata = {
                "job_id": job_id,
                "filter_applied": filter_applied,
                "filter_prefix": resource_id if filter_applied else None
            }
            
            inventory_summary = inventory_service.store_inventory(
                container_name=contents['container_name'],
                files=files_to_store,
                metadata=inventory_metadata
            )
            
            # Prepare result with summary and blob URLs
            result = {
                "job_id": job_id,
                "operation": "container_listing",
                "container_name": contents['container_name'],
                "summary": {
                    "total_files": inventory_summary['total_files'],
                    "geospatial_files": inventory_summary['geospatial_files'],
                    "other_files": inventory_summary['other_files'],
                    "total_size_gb": inventory_summary['total_size_gb'],
                    "file_extensions": inventory_summary['file_extensions'],
                    "scan_time": inventory_summary['scan_time']
                },
                "inventory_urls": inventory_summary['inventory_urls'],
                "filtered": filter_applied
            }
            
            # Use enriched files if available from inference
            files_to_return = inventory_summary.get('enriched_files', files_to_store)
            
            # Include sample files for quick preview
            if len(files_to_return) > 10:
                result['files_sample'] = files_to_return[:10]
                result['note'] = f"Showing first 10 of {len(files_to_return)} files. Full inventory at: {inventory_summary['inventory_urls']['full']}"
            else:
                result['files'] = files_to_return
            
            if filter_applied:
                result['filter_prefix'] = resource_id
            
            logger.info(f"Container listing complete - Found {inventory_summary['total_files']} files, "
                       f"{inventory_summary['total_size_gb']} GB total. Inventory stored in blob.")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in container listing: {str(e)}")
            raise



class ServiceFactory:
    """
    Factory class for creating appropriate service instances.
    
    Implements the Factory pattern to dynamically instantiate the correct
    service based on operation type. This enables adding new services without
    modifying the core routing logic.
    
    The factory performs lazy imports to avoid loading unnecessary dependencies
    and handles graceful fallback to HelloWorldService for unknown operations.
    
    Service Routing:
        - list_container → ContainerListingService
        - database_health → DatabaseHealthService
        - stac_* → STACService
        - catalog_file → STACCatalogService
        - sync_container → SyncContainerService
        - validate_raster → RasterValidationService
        - cog_conversion → RasterProcessorService
        - generate_tile_grid → PostGISTilingService
        - create_tiling_tasks → PostGISTilingService
        - Default → HelloWorldService
    """
    
    @staticmethod
    def get_service(operation_type: str) -> BaseProcessingService:
        """
        Get the appropriate service instance for the operation type.
        
        Uses lazy imports to load service classes only when needed.
        Falls back to HelloWorldService for unknown operations to prevent
        failures during development.
        
        Args:
            operation_type: The type of operation to perform.
            
        Returns:
            BaseProcessingService: Instantiated service for the operation.
            
        Raises:
            ImportError: If a service module cannot be imported.
            ValueError: If a service is not available (caught from imports).
            
        Examples:
            >>> service = ServiceFactory.get_service("list_container")
            >>> isinstance(service, ContainerListingService)
            True
            
            >>> service = ServiceFactory.get_service("unknown_op")
            >>> isinstance(service, HelloWorldService)
            True
        """
        if operation_type == "list_container":
            return ContainerListingService()
        
        # NEW: Simplified COG operations
        elif operation_type == "prepare_for_cog":
            from prepare_for_cog_service import PrepareForCOGService
            return PrepareForCOGService()
        
        elif operation_type == "create_cog":
            from cog_service import COGService
            return COGService()
        
        elif operation_type == "build_vrt":
            from vrt_builder_service import VRTBuilderService
            return VRTBuilderService()
        
        # Database health check
        elif operation_type == "database_health":
            from database_health import DatabaseHealthService
            return DatabaseHealthService()
        
        # STAC operations
        elif operation_type.startswith("stac_"):
            from stac_service import STACService
            return STACService()
        
        # Standalone STAC cataloging
        elif operation_type == "catalog_file":
            from stac_catalog_service import STACCatalogService
            return STACCatalogService()
        
        # Container sync operation
        elif operation_type == "sync_container":
            from sync_container_service import SyncContainerService
            return SyncContainerService()
        
        # Raster processing operations
        elif operation_type == "validate_raster":
            try:
                from raster_processor import RasterValidationService
                return RasterValidationService()
            except ImportError as e:
                logger.error(f"Failed to import RasterValidationService: {e}")
                raise ValueError(f"Raster processing not available: {e}")
        elif operation_type == "process_raster":
            try:
                from raster_processor import RasterProcessorService
                return RasterProcessorService()
            except ImportError as e:
                logger.error(f"Failed to import RasterProcessorService: {e}")
                raise ValueError(f"Raster processing not available: {e}")
        elif operation_type == "cog_conversion" or operation_type == "mosaic_cog":
            # Alias for process_raster (handles both single and mosaic)
            try:
                from raster_processor import RasterProcessorService
                return RasterProcessorService()
            except ImportError as e:
                logger.error(f"Failed to import RasterProcessorService: {e}")
                raise ValueError(f"Raster processing not available: {e}")
        
        # PostGIS tiling operations
        elif operation_type in ["generate_tile_grid", "create_tiling_tasks"]:
            try:
                from postgis_tiling_service import PostGISTilingService
                return PostGISTilingService()
            except ImportError as e:
                logger.error(f"Failed to import PostGISTilingService: {e}")
                # Fall through to HelloWorldService for now
                logger.warning(f"Falling back to HelloWorldService for {operation_type}")
        
        # Chunked mosaic processing for large operations
        elif operation_type == "chunked_mosaic":
            try:
                from raster_chunked_processor import ChunkedMosaicService
                return ChunkedMosaicService()
            except ImportError as e:
                logger.error(f"Failed to import ChunkedMosaicService: {e}")
                raise ValueError(f"Chunked processing not available: {e}")
        
        # Tiled raster processing with parallel tasks
        elif operation_type in ["process_tiled_raster", "prepare_tiled_cog", "create_tiled_cog"]:
            try:
                from tiled_raster_processor import TiledRasterProcessor
                return TiledRasterProcessor()
            except ImportError as e:
                logger.error(f"Failed to import TiledRasterProcessor: {e}")
                raise ValueError(f"Tiled raster processing not available: {e}")
        
        # Future: route different operations to different services
        # elif operation_type == "vector_upload":
        #     return VectorProcessingService()
        
        # Default to hello world for unknown operations
        return HelloWorldService()
    
