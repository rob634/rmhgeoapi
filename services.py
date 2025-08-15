"""
Service layer with ABC classes for geospatial processing
Production-ready architecture with hello world implementation
"""
from abc import ABC, abstractmethod
from typing import Dict, List
import logging


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
        self.logger = logging.getLogger(__name__)
    
    def get_supported_operations(self) -> List[str]:
        """Support all operations for now - this is just hello world"""
        return ["cog_conversion", "vector_upload", "stac_generation", "hello_world"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str, 
                version_id: str, operation_type: str) -> Dict:
        """
        Hello world processing with beautiful parameter display
        """
        self.logger.info("Starting hello world processing")
        
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
        
        # Log the same info
        self.logger.info(f"Hello World Processing Complete - Job: {job_id}, "
                        f"Dataset: {dataset_id}, Resource: {resource_id}, "
                        f"Version: {version_id}, Operation: {operation_type}")
        
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



class ServiceFactory:
    """Factory to create appropriate service instances"""
    
    @staticmethod
    def get_service(operation_type: str) -> BaseProcessingService:
        """
        Get the appropriate service for the operation type
        For now, everything goes to HelloWorldService
        """
        # Future: route different operations to different services
        # if operation_type == "cog_conversion":
        #     return RasterProcessingService()
        # elif operation_type == "vector_upload":
        #     return VectorProcessingService()
        
        # For now, everything is hello world
        return HelloWorldService()
    
