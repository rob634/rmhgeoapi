"""
Repository layer for Azure Table Storage
Handles job tracking and status updates
"""
import logging
from datetime import datetime
from typing import Optional, Dict
from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from models import JobRequest, JobStatus
from config import Config


class JobRepository:
    """Repository for job tracking using Azure Table Storage"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Try managed identity first, fallback to connection string for local dev
        if Config.STORAGE_ACCOUNT_NAME:
            # Use managed identity in production
            account_url = Config.get_storage_account_url('table')
            self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        else:
            # Fallback to connection string for local development
            Config.validate_storage_config()
            self.table_service = TableServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
        
        self.table_name = "jobs"
        # Don't create table at initialization - will be created when first used
    
    def _ensure_table_exists(self):
        """Create jobs table if it doesn't exist"""
        try:
            self.table_service.create_table(self.table_name)
            self.logger.info(f"Created table: {self.table_name}")
        except ResourceExistsError:
            self.logger.debug(f"Table already exists: {self.table_name}")
    
    def save_job(self, job_request: JobRequest) -> bool:
        """
        Save job request to table storage
        Returns True if new job, False if job already exists (idempotency)
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Check if job already exists
            existing_job = self.get_job_status(job_request.job_id)
            if existing_job:
                self.logger.info(f"Job already exists: {job_request.job_id}")
                return False
            
            # Create table entity
            entity = TableEntity()
            entity['PartitionKey'] = 'jobs'  # All jobs in same partition for now
            entity['RowKey'] = job_request.job_id
            
            # Job data
            entity['dataset_id'] = job_request.dataset_id
            entity['resource_id'] = job_request.resource_id
            entity['version_id'] = job_request.version_id
            entity['operation_type'] = job_request.operation_type
            entity['status'] = JobStatus.PENDING
            entity['created_at'] = job_request.created_at
            entity['updated_at'] = job_request.created_at
            
            table_client.create_entity(entity)
            self.logger.info(f"Saved new job: {job_request.job_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving job {job_request.job_id}: {str(e)}")
            raise
    
    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Get job status by job ID"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            job_status = JobStatus(job_id, entity.get('status', JobStatus.PENDING))
            job_status.updated_at = entity.get('updated_at', entity.get('created_at'))
            job_status.error_message = entity.get('error_message')
            
            # Parse result_data if it exists
            result_data_str = entity.get('result_data')
            if result_data_str:
                import json
                job_status.result_data = json.loads(result_data_str)
            
            return job_status
            
        except ResourceNotFoundError:
            self.logger.warning(f"Job not found: {job_id}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting job status {job_id}: {str(e)}")
            raise
    
    def update_job_status(self, job_id: str, status: str, 
                         error_message: str = None, result_data: Dict = None):
        """Update job status in table storage"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Get existing entity
            entity = table_client.get_entity('jobs', job_id)
            
            # Update status fields
            entity['status'] = status
            entity['updated_at'] = datetime.utcnow().isoformat()  # Get current timestamp
            
            if error_message:
                entity['error_message'] = error_message
            
            if result_data:
                import json
                entity['result_data'] = json.dumps(result_data)
            
            table_client.update_entity(entity)
            self.logger.info(f"Updated job status: {job_id} -> {status}")
            
        except ResourceNotFoundError:
            self.logger.error(f"Cannot update non-existent job: {job_id}")
            raise
        except Exception as e:
            self.logger.error(f"Error updating job status {job_id}: {str(e)}")
            raise
    
    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get full job details including original parameters"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            # Convert entity to dictionary
            result = {
                'job_id': job_id,
                'dataset_id': entity.get('dataset_id'),
                'resource_id': entity.get('resource_id'),
                'version_id': entity.get('version_id'),
                'operation_type': entity.get('operation_type'),
                'status': entity.get('status'),
                'created_at': entity.get('created_at'),
                'updated_at': entity.get('updated_at'),
                'error_message': entity.get('error_message'),
            }
            
            # Parse result_data if it exists
            result_data_str = entity.get('result_data')
            if result_data_str:
                import json
                result['result_data'] = json.loads(result_data_str)
            
            return result
            
        except ResourceNotFoundError:
            return None
        except Exception as e:
            self.logger.error(f"Error getting job details {job_id}: {str(e)}")
            raise


class StorageRepository:
    """Repository for Azure Storage operations"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def list_container_contents(self, container_name: str = None) -> Dict:
        """
        List contents of a storage container
        
        Args:
            container_name: Name of container to list (defaults to bronze container)
            
        Returns:
            Dict with container contents and metadata
        """
        try:
            from azure.storage.blob import BlobServiceClient
            
            # Use provided container or default to bronze
            if not container_name:
                container_name = Config.BRONZE_CONTAINER_NAME
            
            self.logger.info(f"Listing contents of container: {container_name}")
            
            # Get blob service client
            if Config.STORAGE_ACCOUNT_NAME:
                account_url = Config.get_storage_account_url('blob')
                blob_service = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            else:
                Config.validate_storage_config()
                blob_service = BlobServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
            
            # Get container client
            container_client = blob_service.get_container_client(container_name)
            
            # List blobs
            blobs = []
            total_size = 0
            
            for blob in container_client.list_blobs():
                blob_info = {
                    'name': blob.name,
                    'size': blob.size,
                    'last_modified': blob.last_modified.isoformat() if blob.last_modified else None,
                    'content_type': blob.content_settings.content_type if blob.content_settings else None,
                    'etag': blob.etag,
                    'creation_time': blob.creation_time.isoformat() if blob.creation_time else None
                }
                blobs.append(blob_info)
                total_size += blob.size if blob.size else 0
            
            result = {
                'container_name': container_name,
                'blob_count': len(blobs),
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'blobs': blobs
            }
            
            self.logger.info(f"Listed {len(blobs)} blobs in container {container_name}, total size: {result['total_size_mb']} MB")
            return result
            
        except Exception as e:
            self.logger.error(f"Error listing container contents: {str(e)}")
            raise