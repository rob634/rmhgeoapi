"""
Repository layer for Azure Table Storage
Handles job tracking and status updates
"""
import os
import logging
from typing import Optional, Dict
from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from models import JobRequest, JobStatus


class JobRepository:
    """Repository for job tracking using Azure Table Storage"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Try managed identity first, fallback to connection string for local dev
        storage_account_name = os.environ.get('STORAGE_ACCOUNT_NAME')
        
        if storage_account_name:
            # Use managed identity in production
            from azure.identity import DefaultAzureCredential
            account_url = f"https://{storage_account_name}.table.core.windows.net"
            self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        else:
            # Fallback to connection string for local development
            connection_string = os.environ.get('AzureWebJobsStorage')
            if not connection_string:
                raise ValueError("Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage environment variable must be set")
            self.table_service = TableServiceClient.from_connection_string(connection_string)
        
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
            entity['updated_at'] = JobStatus().updated_at  # Get current timestamp
            
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