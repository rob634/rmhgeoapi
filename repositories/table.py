"""Repository for Azure Table Storage operations."""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from azure.data.tables import TableServiceClient, TableEntity
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from core.models import JobRequest, JobStatus
from core.config import Config
from core.constants import TableNames
from utils.logger import logger


class TableRepository:
    """Repository for Azure Table Storage operations."""
    
    def __init__(self, table_name: str = None):
        """
        Initialize table repository.
        
        Args:
            table_name: Name of the table to work with
        """
        # Always use managed identity in Azure Functions
        if not Config.STORAGE_ACCOUNT_NAME:
            raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set for managed identity")
        
        account_url = Config.get_storage_account_url('table')
        self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        self.table_name = table_name or TableNames.JOBS
    
    def _ensure_table_exists(self):
        """Create table if it doesn't exist."""
        try:
            self.table_service.create_table(self.table_name)
            logger.info(f"Created table: {self.table_name}")
        except ResourceExistsError:
            logger.debug(f"Table already exists: {self.table_name}")
    
    def insert_entity(self, entity: Dict[str, Any]) -> bool:
        """
        Insert an entity into the table.
        
        Args:
            entity: Entity data with PartitionKey and RowKey
            
        Returns:
            True if successful
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            table_client.create_entity(entity=entity)
            return True
        except ResourceExistsError:
            logger.debug(f"Entity already exists: {entity.get('RowKey')}")
            return False
        except Exception as e:
            logger.error(f"Failed to insert entity: {e}")
            raise
    
    def update_entity(self, entity: Dict[str, Any]) -> bool:
        """
        Update an existing entity.
        
        Args:
            entity: Entity data with PartitionKey and RowKey
            
        Returns:
            True if successful
        """
        try:
            table_client = self.table_service.get_table_client(self.table_name)
            table_client.update_entity(entity=entity, mode='merge')
            return True
        except Exception as e:
            logger.error(f"Failed to update entity: {e}")
            raise
    
    def get_entity(self, partition_key: str, row_key: str) -> Optional[Dict[str, Any]]:
        """
        Get an entity by partition and row key.
        
        Args:
            partition_key: Partition key
            row_key: Row key
            
        Returns:
            Entity data or None if not found
        """
        try:
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity(partition_key=partition_key, row_key=row_key)
            return dict(entity)
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Failed to get entity: {e}")
            raise
    
    def query_entities(self, filter_query: str = None, select: str = None) -> list:
        """
        Query entities with optional filter.
        
        Args:
            filter_query: OData filter query
            select: Comma-separated list of properties to select
            
        Returns:
            List of matching entities
        """
        try:
            table_client = self.table_service.get_table_client(self.table_name)
            
            kwargs = {}
            if filter_query:
                kwargs['filter'] = filter_query
            if select:
                kwargs['select'] = select
            
            entities = table_client.query_entities(**kwargs)
            return [dict(entity) for entity in entities]
        except Exception as e:
            logger.error(f"Failed to query entities: {e}")
            raise
    
    def delete_entity(self, partition_key: str, row_key: str) -> bool:
        """
        Delete an entity.
        
        Args:
            partition_key: Partition key
            row_key: Row key
            
        Returns:
            True if successful
        """
        try:
            table_client = self.table_service.get_table_client(self.table_name)
            table_client.delete_entity(partition_key=partition_key, row_key=row_key)
            return True
        except ResourceNotFoundError:
            logger.warning(f"Entity not found for deletion: {row_key}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete entity: {e}")
            raise


class JobRepository(TableRepository):
    """Specialized repository for job tracking."""
    
    def __init__(self):
        """Initialize job repository with jobs table."""
        super().__init__(TableNames.JOBS)
    
    def save_job(self, job_request: JobRequest) -> bool:
        """
        Save job request to table storage.
        
        Args:
            job_request: Job request object
            
        Returns:
            True if new job, False if job already exists (idempotency)
        """
        entity = TableEntity(
            PartitionKey='jobs',
            RowKey=job_request.job_id,
            dataset_id=job_request.dataset_id,
            resource_id=job_request.resource_id,
            version_id=job_request.version_id,
            operation_type=job_request.operation_type,
            system=job_request.system,
            status=JobStatus.PENDING.value,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            request_parameters=str(job_request.to_dict())
        )
        
        return self.insert_entity(entity)
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job by ID.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Job data or None if not found
        """
        return self.get_entity('jobs', job_id)
    
    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str = None,
        result_data: Dict = None
    ) -> bool:
        """
        Update job status and optionally add error or result data.
        
        Args:
            job_id: Job identifier
            status: New job status
            error_message: Optional error message
            result_data: Optional result data
            
        Returns:
            True if successful
        """
        entity = {
            'PartitionKey': 'jobs',
            'RowKey': job_id,
            'status': status.value,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        if error_message:
            entity['error_message'] = error_message[:1000]  # Limit error message size
        
        if result_data:
            entity['result_data'] = str(result_data)[:32000]  # Limit result size
        
        return self.update_entity(entity)