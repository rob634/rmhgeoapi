"""Container listing service."""

from typing import Dict, List
from services.base_service import BaseProcessingService
from utils.logger import logger
from repositories.storage import StorageRepository


class ContainerListingService(BaseProcessingService):
    """Service for listing container contents with detailed file information."""
    
    def __init__(self):
        super().__init__()
    
    def get_supported_operations(self) -> List[str]:
        """Return list of supported operations."""
        return ["list_container"]
    
    def process(
        self, 
        job_id: str, 
        dataset_id: str, 
        resource_id: str, 
        version_id: str, 
        operation_type: str
    ) -> Dict:
        """
        Process container listing job.
        
        Args:
            job_id: Unique job identifier
            dataset_id: Used as container name to list
            resource_id: Optional prefix filter
            version_id: Not used for listing operations
            operation_type: Should be 'list_container'
            
        Returns:
            Dict containing container contents with file details
        """
        logger.info(f"Starting container listing - Job: {job_id}, Container: {dataset_id}")
        
        try:
            # Use dataset_id as container name
            container_name = dataset_id if dataset_id else None
            
            # Initialize storage repository
            storage_repo = StorageRepository()
            
            if container_name:
                # List specific container
                if not storage_repo.container_exists(container_name):
                    raise ValueError(f"Container '{container_name}' does not exist")
                contents = storage_repo.list_container_contents(container_name)
            else:
                # List default workspace container
                contents = storage_repo.list_container_contents()
            
            # Add file extension analysis
            extensions = {}
            total_files = len(contents['blobs'])
            
            for blob in contents['blobs']:
                # Extract extension
                if '.' in blob['name']:
                    ext = blob['name'].split('.')[-1].lower()
                    extensions[ext] = extensions.get(ext, 0) + 1
                else:
                    extensions['no_extension'] = extensions.get('no_extension', 0) + 1
            
            # Apply prefix filter if resource_id is provided and not 'none'
            if resource_id and resource_id != 'none':
                logger.info(f"Applying prefix filter: {resource_id}")
                filtered_blobs = [
                    blob for blob in contents['blobs'] 
                    if blob['name'].startswith(resource_id)
                ]
                contents['blobs'] = filtered_blobs
                contents['blob_count'] = len(filtered_blobs)
                contents['filtered'] = True
                contents['filter_prefix'] = resource_id
            else:
                contents['filtered'] = False
            
            # Add summary statistics
            result = {
                "job_id": job_id,
                "operation": "container_listing",
                "container_name": contents['container_name'],
                "summary": {
                    "total_files": contents['blob_count'],
                    "total_size_bytes": contents['total_size_bytes'],
                    "total_size_mb": contents['total_size_mb'],
                    "file_extensions": extensions,
                    "largest_file": max(contents['blobs'], key=lambda x: x['size']) if contents['blobs'] else None,
                    "newest_file": max(contents['blobs'], key=lambda x: x['last_modified'] or '1900-01-01') if contents['blobs'] else None
                },
                "files": contents['blobs'],
                "filtered": contents.get('filtered', False)
            }
            
            if contents.get('filtered'):
                result['filter_prefix'] = contents['filter_prefix']
            
            logger.info(f"Container listing complete - Found {contents['blob_count']} files, {contents['total_size_mb']} MB total")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in container listing: {str(e)}")
            raise