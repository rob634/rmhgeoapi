"""Hello World service for testing the pipeline."""

from typing import Dict, List
from .base_service import BaseProcessingService
from utils.logger import logger, log_job_stage, log_service_processing


class HelloWorldService(BaseProcessingService):
    """Hello world implementation for testing pipeline."""
    
    def __init__(self):
        super().__init__()
    
    def get_supported_operations(self) -> List[str]:
        """Support all operations for now - this is just hello world."""
        return ["cog_conversion", "vector_upload", "stac_generation", "hello_world"]
    
    def process(
        self, 
        job_id: str, 
        dataset_id: str, 
        resource_id: str, 
        version_id: str, 
        operation_type: str
    ) -> Dict:
        """
        Hello world processing with beautiful parameter display.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Dataset or container name
            resource_id: Specific resource identifier
            version_id: Version or processing parameters
            operation_type: Type of operation to perform
            
        Returns:
            Dict with processing results
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