"""
Service layer with ABC classes for geospatial processing
Production-ready architecture with hello world implementation
"""
from abc import ABC, abstractmethod
from typing import Dict, List
import logging
from logger_setup import logger, log_job_stage, log_service_processing


class BaseProcessingService(ABC):
    """Abstract base class for all processing services"""
    
    @abstractmethod
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process a job with given parameters
        
        Returns:
            Dict with status and result information
        """
        pass
    
    @abstractmethod
    def get_supported_operations(self) -> List[str]:
        """Return list of operations this service supports"""
        pass


class HelloWorldService(BaseProcessingService):
    """Hello world implementation for testing pipeline"""
    
    def __init__(self):
        pass  # Use centralized logger
    
    def get_supported_operations(self) -> List[str]:
        """Support all operations for now - this is just hello world"""
        return ["cog_conversion", "vector_upload", "stac_generation", "hello_world"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Hello world processing with beautiful parameter display
        """
        log_job_stage(job_id, "hello_world_start", "processing")
        
        # Beautiful parameter display
        print("=" * 60)
        print("🚀 GEOSPATIAL ETL PIPELINE - HELLO WORLD")
        print("=" * 60)
        print(f"📋 Job ID: {job_id}")
        print(f"📊 Dataset: {dataset_id}")
        print(f"📁 Resource: {resource_id}")
        print(f"🔢 Version: {version_id}")
        print(f"⚙️  Operation: {operation_type}")
        print("-" * 60)
        print("🎯 Processing Status: HELLO WORLD COMPLETE!")
        print("✅ All parameters received and validated")
        print("🎉 Ready for real geospatial processing")
        print("=" * 60)
        
        # Log completion
        log_job_stage(job_id, "hello_world_complete", "completed")
        log_service_processing("HelloWorldService", operation_type, job_id, "completed")
        
        return {
            "status": "completed",
            "message": "Hello world processing completed successfully",
            "processed_items": {
                "dataset_id": dataset_id,
                "resource_id": resource_id,
                "version_id": version_id,
                "operation_type": operation_type
            }
        }


class ContainerListingService(BaseProcessingService):
    """Service for listing container contents with detailed file information"""
    
    def __init__(self):
        pass  # Use centralized logger
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations"""
        return ["list_container"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Process container listing job
        
        Args:
            job_id: Unique job identifier
            dataset_id: Used as container name to list
            resource_id: Optional prefix filter
            version_id: Not used for listing operations
            operation_type: Should be 'list_container'
            
        Returns:
            Dict containing container summary and blob inventory URLs
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
            
            # Include sample files for quick preview
            if len(files_to_store) > 10:
                result['files_sample'] = files_to_store[:10]
                result['note'] = f"Showing first 10 of {len(files_to_store)} files. Full inventory at: {inventory_summary['inventory_urls']['full']}"
            else:
                result['files'] = files_to_store
            
            if filter_applied:
                result['filter_prefix'] = resource_id
            
            logger.info(f"Container listing complete - Found {inventory_summary['total_files']} files, "
                       f"{inventory_summary['total_size_gb']} GB total. Inventory stored in blob.")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in container listing: {str(e)}")
            raise



class ServiceFactory:
    """Factory to create appropriate service instances"""
    
    @staticmethod
    def get_service(operation_type: str) -> BaseProcessingService:
        """
        Get the appropriate service for the operation type
        """
        if operation_type == "list_container":
            return ContainerListingService()
        
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
        elif operation_type == "cog_conversion":
            # Alias for process_raster
            try:
                from raster_processor import RasterProcessorService
                return RasterProcessorService()
            except ImportError as e:
                logger.error(f"Failed to import RasterProcessorService: {e}")
                raise ValueError(f"Raster processing not available: {e}")
        
        # Future: route different operations to different services
        # elif operation_type == "vector_upload":
        #     return VectorProcessingService()
        
        # Default to hello world for unknown operations
        return HelloWorldService()
    
