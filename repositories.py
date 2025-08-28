"""
Repository layer for Azure Table Storage and Blob Storage operations.

This module provides data access abstractions for the Job→Task architecture,
handling persistent storage of jobs, tasks, and blob operations with proper
Azure managed identity authentication.

Components:
    - JobRepository: Job lifecycle management in Azure Table Storage
    - TaskRepository: Task tracking and status management
    - StorageRepository: Blob storage operations with SAS token generation
    
Key Features:
    - Managed identity authentication (no connection strings)
    - Job and task result data storage with JSON serialization
    - Comprehensive status tracking (queued → processing → completed/failed)
    - Idempotent operations with proper error handling
    - Enhanced result data aggregation for job completion
    - Batch operations for efficiency

Architecture Integration:
    - Used by controllers for job/task persistence
    - Integrates with TaskManager for distributed completion detection
    - Provides blob access for services and processing operations
    - Handles Azure Functions queue message generation

Performance Considerations:
    - Table operations optimized for high-frequency status updates
    - JSON serialization for complex result data structures
    - Proper indexing on PartitionKey/RowKey for efficient queries
    - Connection pooling via managed identity

Author: Azure Geospatial ETL Team
Version: 1.2.0 - Enhanced with result data aggregation support
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict
from azure.data.tables import TableServiceClient, TableEntity, UpdateMode
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from models import JobRequest, JobStatus
from config import Config
from logger_setup import logger


class JobRepository:
    """
    Repository for job lifecycle management using Azure Table Storage.
    
    Handles persistent storage of job records throughout their lifecycle,
    from creation through completion. Supports the enhanced Job→Task 
    architecture with comprehensive result data aggregation.
    
    Key Responsibilities:
        - Job creation with idempotency checks
        - Status transitions (queued → processing → completed/failed)
        - Result data storage with JSON serialization
        - Enhanced completion metadata from task aggregation
        - Error message tracking for failed jobs
        
    Table Schema:
        PartitionKey: 'jobs' (for efficient querying)
        RowKey: job_id (SHA256 hash for uniqueness)
        Status: queued | processing | completed | failed | completed_with_errors
        result_data: JSON string with task results and completion metadata
        error_message: Error details for failed jobs
        created_at, updated_at: ISO timestamps
        
    Enhanced Features (August 2025):
        - Comprehensive result_data populated from task results
        - Metadata parameter for flexible field updates
        - Proper JSON serialization for complex data structures
        - Support for completed_with_errors status (partial failures)
        - Legacy parameter support for backward compatibility
        
    Usage:
        repo = JobRepository()
        
        # Create new job
        is_new = repo.save_job(job_request)
        
        # Update with task results
        success = repo.update_job_status(
            job_id, 'completed', 
            result_data={'task_results': [...], 'summary': {...}}
        )
    """
    
    def __init__(self):
        
        # Always use managed identity in Azure Functions
        if not Config.STORAGE_ACCOUNT_NAME:
            raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set for managed identity")
        
        account_url = Config.get_storage_account_url('table')
        self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        
        from config import AzureStorage
        self.table_name = AzureStorage.JOB_TRACKING_TABLE
        # Don't create table at initialization - will be created when first used
    
    def _ensure_table_exists(self):
        """Create jobs table if it doesn't exist"""
        try:
            self.table_service.create_table(self.table_name)
            logger.info(f"Created table: {self.table_name}")
        except ResourceExistsError:
            logger.debug(f"Table already exists: {self.table_name}")
    
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
                logger.info(f"Job already exists: {job_request.job_id}")
                return False
            
            # Create table entity
            entity = TableEntity()
            entity['PartitionKey'] = 'jobs'  # All jobs in same partition for now
            entity['RowKey'] = job_request.job_id
            
            # Job data - individual fields for easy querying
            entity['dataset_id'] = job_request.dataset_id
            entity['resource_id'] = job_request.resource_id
            entity['version_id'] = job_request.version_id
            entity['job_type'] = job_request.operation_type  # Store as job_type in table (primary field)
            # entity['operation_type'] = job_request.operation_type  # REMOVED: No more operation_type field
            entity['system'] = job_request.system
            entity['status'] = JobStatus.PENDING
            entity['created_at'] = job_request.created_at
            entity['updated_at'] = job_request.created_at
            
            # Stage tracking fields (MANDATORY for job chaining framework)
            import json
            entity['stages'] = 1  # Default single stage for non-sequential jobs
            entity['current_stage_n'] = 1  # Start at stage 1
            entity['current_stage'] = job_request.operation_type  # Default stage name = operation type
            entity['stage_sequence'] = json.dumps({1: job_request.operation_type})  # Single stage mapping
            entity['stage_data'] = json.dumps({})  # Empty initial stage data
            entity['stage_history'] = json.dumps([])  # Empty initial history
            
            # Store complete request parameters as JSON for full tracking
            import json
            entity['request_parameters'] = json.dumps(job_request.to_dict())
            
            table_client.create_entity(entity)
            logger.info(f"Saved new job: {job_request.job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving job {job_request.job_id}: {str(e)}")
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
            logger.warning(f"Job not found: {job_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting job status {job_id}: {str(e)}")
            raise
    
    def update_job_status(self, job_id: str, status: str, 
                         metadata: Dict = None, error_message: str = None, result_data: Dict = None) -> bool:
        """
        Update job status in table storage.
        
        Args:
            job_id: Job identifier
            status: New status
            metadata: Optional metadata dict (preferred, can contain error_message, result_data, etc.)
            error_message: Legacy parameter for error message
            result_data: Legacy parameter for result data
            
        Returns:
            bool: True if updated successfully
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Get existing entity
            entity = table_client.get_entity('jobs', job_id)
            
            # Update status fields
            entity['status'] = status
            entity['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Handle metadata dict (preferred)
            if metadata:
                for key, value in metadata.items():
                    if isinstance(value, (dict, list)):
                        import json
                        entity[key] = json.dumps(value)
                    else:
                        entity[key] = value
            
            # Handle legacy parameters
            if error_message:
                entity['error_message'] = error_message
            
            if result_data:
                import json
                entity['result_data'] = json.dumps(result_data)
            
            table_client.update_entity(entity)
            logger.info(f"Updated job status: {job_id} -> {status}")
            return True
            
        except ResourceNotFoundError:
            logger.error(f"Cannot update non-existent job: {job_id}")
            return False
        except Exception as e:
            logger.error(f"Error updating job status {job_id}: {str(e)}")
            return False
    
    def update_job_field(self, job_id: str, field_name: str, field_value: str) -> bool:
        """
        Update a specific field in a job record.
        
        Args:
            job_id: Job identifier
            field_name: Field name to update
            field_value: New field value
            
        Returns:
            bool: True if updated successfully
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Get existing job
            entity = table_client.get_entity('jobs', job_id)
            
            # Update the specific field
            entity[field_name] = field_value
            entity['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Save back to storage
            table_client.update_entity(entity)
            logger.debug(f"Updated field {field_name} for job {job_id}")
            return True
            
        except ResourceNotFoundError:
            logger.error(f"Job {job_id} not found for field update")
            return False
        except Exception as e:
            logger.error(f"Failed to update field {field_name} for job {job_id}: {e}")
            return False
    
    def create_job(self, job_id: str, job_data: Dict) -> bool:
        """
        Create a new job record (for controller compatibility).
        
        Args:
            job_id: Unique job identifier
            job_data: Job data dictionary
            
        Returns:
            bool: True if created, False if already exists
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Validate that job_type is provided (required field)
            job_type = job_data.get('job_type')
            if not job_type:
                # Check if caller is using deprecated operation_type
                operation_type = job_data.get('operation_type')
                if operation_type:
                    logger.error(f"Job creation failed: operation_type provided but job_type required")
                    logger.error(f"Please use 'job_type' instead of 'operation_type' for job {job_id}")
                    raise ValueError(f"job_type is required (found operation_type: {operation_type})")
                else:
                    logger.error(f"Job creation failed: job_type is required for job {job_id}")
                    raise ValueError("job_type is required for job creation")
            
            logger.debug(f"Creating job {job_id} with job_type: {job_type}")
            
            # Check if job already exists
            try:
                existing = table_client.get_entity('jobs', job_id)
                logger.debug(f"Job already exists: {job_id}")
                return False
            except ResourceNotFoundError:
                pass  # Job doesn't exist, proceed to create
            
            # Create entity
            entity = TableEntity()
            entity['PartitionKey'] = 'jobs'
            entity['RowKey'] = job_id
            
            # Add all job data fields (excluding deprecated operation_type)
            for key, value in job_data.items():
                if key == 'operation_type' and key != 'job_type':
                    # Skip deprecated operation_type field
                    logger.debug(f"Skipping deprecated operation_type field in job data")
                    continue
                    
                if isinstance(value, (dict, list)):
                    import json
                    entity[key] = json.dumps(value)
                else:
                    entity[key] = value
            
            # Ensure standard fields
            entity['status'] = job_data.get('status', JobStatus.PENDING)
            entity['created_at'] = job_data.get('created_at', datetime.now(timezone.utc).isoformat())
            
            table_client.create_entity(entity)
            logger.info(f"Created job: {job_id}")
            return True
            
        except ResourceExistsError:
            logger.debug(f"Job already exists (race condition): {job_id}")
            return False
        except Exception as e:
            logger.error(f"Error creating job {job_id}: {str(e)}")
            raise
    
    def get_job(self, job_id: str) -> Optional[Dict]:
        """
        Get job as dictionary (for controller compatibility).
        
        Args:
            job_id: Job identifier
            
        Returns:
            Dict or None if not found
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            # Convert entity to dict
            result = dict(entity)
            
            # Parse JSON fields
            if 'request' in result and isinstance(result['request'], str):
                import json
                result['request'] = json.loads(result['request'])
            if 'task_ids' in result and isinstance(result['task_ids'], str):
                import json
                result['task_ids'] = json.loads(result['task_ids'])
            
            return result
            
        except ResourceNotFoundError:
            logger.debug(f"Job not found: {job_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting job {job_id}: {str(e)}")
            return None
    
    def get_job_details(self, job_id: str) -> Optional[Dict]:
        """Get full job details including original parameters"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            # Validate that job_type exists (required field)
            job_type = entity.get('job_type')
            if not job_type:
                # Check if this is an old record with operation_type
                operation_type = entity.get('operation_type')
                if operation_type:
                    logger.warning(f"Job {job_id} has operation_type but no job_type - legacy record detected")
                    logger.warning("Please migrate legacy jobs to use job_type field")
                    # job_type = operation_type  # COMMENTED OUT: No fallback allowed
                    raise ValueError(f"Job {job_id} missing required job_type field (found operation_type: {operation_type})")
                else:
                    raise ValueError(f"Job {job_id} missing required job_type field")
            
            # Convert entity to dictionary
            result = {
                'job_id': job_id,
                'dataset_id': entity.get('dataset_id'),
                'resource_id': entity.get('resource_id'),
                'version_id': entity.get('version_id'),
                'job_type': job_type,  # Required field, no fallback
                'operation_type': job_type,  # For API compatibility, return job_type as operation_type
                'system': entity.get('system', False),  # Default to False for backwards compatibility
                'status': entity.get('status'),
                'created_at': entity.get('created_at'),
                'updated_at': entity.get('updated_at'),
                'error_message': entity.get('error_message'),
                # Controller-managed job fields
                'controller_managed': entity.get('controller_managed', False),
                'task_count': entity.get('task_count', 0),
                'total_tasks': entity.get('total_tasks', 0),
                'completed_tasks': entity.get('completed_tasks', 0),
                'failed_tasks': entity.get('failed_tasks', 0),
                'progress_percentage': entity.get('progress_percentage', 0.0),
            }
            
            # Parse result_data if it exists
            result_data_str = entity.get('result_data')
            if result_data_str:
                import json
                result['result_data'] = json.loads(result_data_str)
            
            # Parse and include complete request parameters if available
            request_params_str = entity.get('request_parameters')
            if request_params_str:
                import json
                result['request_parameters'] = json.loads(request_params_str)
            
            return result
            
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting job details {job_id}: {str(e)}")
            raise


class TaskRepository:
    """Repository for task tracking using Azure Table Storage"""
    
    def __init__(self):
        # Always use managed identity in Azure Functions
        if not Config.STORAGE_ACCOUNT_NAME:
            raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set for managed identity")
        
        account_url = Config.get_storage_account_url('table')
        self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        
        self.table_name = 'tasks'  # Separate table for tasks
    
    def _ensure_table_exists(self):
        """Create tasks table if it doesn't exist"""
        try:
            self.table_service.create_table(self.table_name)
            logger.info(f"Created table: {self.table_name}")
        except ResourceExistsError:
            logger.debug(f"Table already exists: {self.table_name}")
    
    def create_task(self, task_id: str, parent_job_id: str, task_data: dict) -> bool:
        """
        Create a new task associated with a parent job
        
        Args:
            task_id: Unique task identifier
            parent_job_id: ID of the parent job that created this task
            task_data: Dictionary containing task details
            
        Returns:
            True if task created, False if already exists
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Check if task already exists
            try:
                existing = table_client.get_entity('tasks', task_id)
                logger.debug(f"Task already exists: {task_id}")
                return False
            except ResourceNotFoundError:
                pass  # Task doesn't exist, continue creating
            
            # Create table entity
            entity = TableEntity()
            entity['PartitionKey'] = 'tasks'
            entity['RowKey'] = task_id
            
            # Task metadata
            entity['task_id'] = task_id
            entity['parent_job_id'] = parent_job_id
            entity['status'] = 'queued'
            entity['created_at'] = datetime.now(timezone.utc).isoformat()
            entity['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Set both task_type and operation_type fields for compatibility
            task_type_value = task_data.get('task_type')
            if task_type_value:
                entity['task_type'] = task_type_value
                entity['operation_type'] = task_type_value  # Legacy compatibility
                logger.info(f"Setting task_type and operation_type to: {task_type_value}")
            else:
                logger.warning(f"task_type is None in task_data: {task_data}")
            entity['dataset_id'] = task_data.get('dataset_id')
            entity['resource_id'] = task_data.get('resource_id')
            entity['version_id'] = task_data.get('version_id')
            
            # Optional fields
            if 'file_size' in task_data:
                entity['file_size'] = task_data['file_size']
            if 'file_path' in task_data:
                entity['file_path'] = task_data['file_path']
            if 'priority' in task_data:
                entity['priority'] = task_data['priority']
            
            # Store full task data as JSON
            entity['task_data'] = json.dumps(task_data)
            
            table_client.create_entity(entity)
            logger.info(f"Created task: {task_id} for job: {parent_job_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating task {task_id}: {str(e)}")
            raise
    
    def update_task_status(self, task_id: str, status: str, metadata: dict = None) -> bool:
        """
        Update task status with optional metadata.
        
        Args:
            task_id: Task identifier
            status: New status
            metadata: Optional metadata dict (can contain error_message, result_data, etc.)
            
        Returns:
            bool: True if updated successfully
        """
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Get existing entity
            entity = table_client.get_entity('tasks', task_id)
            
            # Update fields
            entity['status'] = status
            entity['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Apply metadata if provided
            if metadata:
                if 'error_message' in metadata:
                    entity['error_message'] = metadata['error_message']
                if 'result_data' in metadata:
                    entity['result_data'] = json.dumps(metadata['result_data'])
                # Allow any other metadata fields
                for key, value in metadata.items():
                    if key not in ['error_message', 'result_data']:
                        if isinstance(value, (dict, list)):
                            entity[key] = json.dumps(value)
                        else:
                            entity[key] = value
            
            # If completed or failed, add completion time
            if status in ['completed', 'failed']:
                entity['completed_at'] = datetime.now(timezone.utc).isoformat()
            
            table_client.update_entity(entity, mode=UpdateMode.MERGE)
            logger.info(f"Updated task status: {task_id} -> {status}")
            return True
            
        except ResourceNotFoundError:
            logger.error(f"Task not found: {task_id}")
            return False
        except Exception as e:
            logger.error(f"Error updating task status {task_id}: {str(e)}")
            return False
    
    def get_task(self, task_id: str) -> dict:
        """Get task details"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            entity = table_client.get_entity('tasks', task_id)
            
            # Parse JSON fields
            result = dict(entity)
            if 'task_data' in result and isinstance(result['task_data'], str):
                result['task_data'] = json.loads(result['task_data'])
            if 'result_data' in result and isinstance(result['result_data'], str):
                result['result_data'] = json.loads(result['result_data'])
            
            # If task_type column is empty, try to get it from task_data JSON
            if not result.get('task_type') and result.get('task_data'):
                task_data = result['task_data']
                if isinstance(task_data, dict):
                    json_task_type = task_data.get('task_type')
                    if json_task_type:
                        result['task_type'] = json_task_type
                        # Also populate operation_type for compatibility
                        if not result.get('operation_type'):
                            result['operation_type'] = json_task_type
                        logger.info(f"Populated task_type from JSON: {json_task_type} for task {result.get('task_id', 'unknown')}")
                    else:
                        logger.warning(f"task_type not found in task_data JSON for task {result.get('task_id', 'unknown')}")
                else:
                    logger.warning(f"task_data is not a dict for task {result.get('task_id', 'unknown')}: {type(task_data)}")
            
            return result
            
        except ResourceNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting task {task_id}: {str(e)}")
            raise
    
    def get_tasks_for_job(self, parent_job_id: str) -> list:
        """Get all tasks for a parent job"""
        try:
            self._ensure_table_exists()
            table_client = self.table_service.get_table_client(self.table_name)
            
            # Query tasks by parent job ID
            filter_query = f"parent_job_id eq '{parent_job_id}'"
            entities = table_client.query_entities(filter_query)
            
            tasks = []
            for entity in entities:
                task = dict(entity)
                if 'task_data' in task and isinstance(task['task_data'], str):
                    task['task_data'] = json.loads(task['task_data'])
                if 'result_data' in task and isinstance(task['result_data'], str):
                    task['result_data'] = json.loads(task['result_data'])
                
                # If task_type column is empty, try to get it from task_data JSON
                if not task.get('task_type') and task.get('task_data'):
                    task_data = task['task_data']
                    if isinstance(task_data, dict):
                        json_task_type = task_data.get('task_type')
                        if json_task_type:
                            task['task_type'] = json_task_type
                            # Also populate operation_type for compatibility
                            if not task.get('operation_type'):
                                task['operation_type'] = json_task_type
                            logger.info(f"Populated task_type from JSON: {json_task_type} for task {task.get('task_id', 'unknown')}")
                        else:
                            logger.warning(f"task_type not found in task_data JSON for task {task.get('task_id', 'unknown')}")
                    else:
                        logger.warning(f"task_data is not a dict for task {task.get('task_id', 'unknown')}: {type(task_data)}")
                
                tasks.append(task)
            
            return tasks
            
        except Exception as e:
            logger.error(f"Error getting tasks for job {parent_job_id}: {str(e)}")
            raise
    
    def get_task_summary_for_job(self, parent_job_id: str) -> dict:
        """Get summary of tasks for a job"""
        try:
            tasks = self.get_tasks_for_job(parent_job_id)
            
            summary = {
                'total': len(tasks),
                'queued': sum(1 for t in tasks if t.get('status') == 'queued'),
                'processing': sum(1 for t in tasks if t.get('status') == 'processing'),
                'completed': sum(1 for t in tasks if t.get('status') == 'completed'),
                'failed': sum(1 for t in tasks if t.get('status') == 'failed')
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting task summary for job {parent_job_id}: {str(e)}")
            raise


class StorageRepository:
    """Repository for Azure Storage operations with comprehensive blob management"""
    
    # Valid file extensions for geospatial data
    VALID_EXTENSIONS = [
        "7z", "csv", "gdb", "geojson", "geotif", "geotiff", "gpkg", 
        "json", "kml", "kmz", "osm", "shp", "tif", "tiff", "txt", 
        "xml", "zip", "parquet", "delta", "orc"
    ]
    
    def __init__(self, workspace_container_name: str = None):
        
        # Initialize blob service client
        self._init_blob_service_client()
        
        # Set workspace container
        if workspace_container_name:
            self.workspace_container_name = workspace_container_name
        else:
            # Validate bronze container is configured before using it
            Config.validate_container_config()
            self.workspace_container_name = Config.BRONZE_CONTAINER_NAME
        
        # Validate workspace container exists
        if self.workspace_container_name:
            if not self.container_exists(self.workspace_container_name):
                logger.error(f"Workspace container {self.workspace_container_name} not found")
                raise ValueError(f"Workspace container {self.workspace_container_name} not found")
            logger.info(f"StorageRepository initialized with workspace container: {self.workspace_container_name}")
    
    def _init_blob_service_client(self):
        """Initialize the blob service client with appropriate authentication"""
        try:
            # Prioritize managed identity for Azure Functions
            # Check for STORAGE_ACCOUNT_NAME which indicates Azure environment
            if Config.STORAGE_ACCOUNT_NAME:
                # Use managed identity in Azure Functions
                account_url = Config.get_storage_account_url('blob')
                self.blob_service_client = BlobServiceClient(account_url, credential=DefaultAzureCredential())
                logger.info(f"BlobServiceClient initialized with managed identity for {Config.STORAGE_ACCOUNT_NAME}")
            elif Config.AZURE_WEBJOBS_STORAGE:
                # Fall back to connection string for local development
                self.blob_service_client = BlobServiceClient.from_connection_string(Config.AZURE_WEBJOBS_STORAGE)
                logger.info(f"BlobServiceClient initialized with connection string (local development)")
            else:
                raise ValueError("Either STORAGE_ACCOUNT_NAME or AzureWebJobsStorage must be set")
        except Exception as e:
            logger.error(f"Error initializing BlobServiceClient: {e}")
            raise
    
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
            
            logger.info(f"Listing contents of container: {container_name}")
            
            # Use managed identity for blob service client
            if not Config.STORAGE_ACCOUNT_NAME:
                raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set for managed identity")
            
            account_url = Config.get_storage_account_url('blob')
            blob_service = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            
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
            
            logger.info(f"Listed {len(blobs)} blobs in container {container_name}, total size: {result['total_size_mb']} MB")
            return result
            
        except Exception as e:
            logger.error(f"Error listing container contents: {str(e)}")
            raise
    
    def container_exists(self, container_name: str) -> bool:
        """Check if a container exists in the storage account"""
        try:
            if not isinstance(container_name, str):
                raise ValueError(f"Container name must be a string, got {type(container_name)}")
            
            logger.debug(f"Checking if container {container_name} exists")
            container_client = self.blob_service_client.get_container_client(container_name)
            exists = container_client.exists()
            
            if exists:
                logger.debug(f"Container {container_name} exists")
            else:
                logger.warning(f"Container {container_name} not found")
            
            return exists
            
        except Exception as e:
            logger.error(f"Error checking container {container_name}: {e}")
            raise
    
    def list_containers(self) -> list:
        """List all containers in the storage account"""
        try:
            container_list = self.blob_service_client.list_containers()
            names = [container.name for container in container_list]
            logger.info(f"Found containers: {', '.join(names)}")
            return names
        except Exception as e:
            logger.error(f"Error listing containers: {e}")
            raise
    
    def blob_exists(self, blob_name: str, container_name: str = None) -> bool:
        """Check if a blob exists in the specified container"""
        try:
            if not isinstance(blob_name, str):
                raise ValueError(f"Blob name must be a string, got {type(blob_name)}")
            
            container_name = container_name or self.workspace_container_name
            if not container_name:
                raise ValueError("Container name must be provided")
            
            logger.debug(f"Checking if blob {blob_name} exists in {container_name}")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )
            exists = blob_client.exists()
            
            if exists:
                logger.debug(f"Blob {blob_name} exists in {container_name}")
            else:
                logger.debug(f"Blob {blob_name} not found in {container_name}")
            
            return exists
            
        except Exception as e:
            logger.error(f"Error checking blob {blob_name} in {container_name}: {e}")
            raise
    
    def download_blob(self, blob_name: str, container_name: str = None) -> bytes:
        """Download blob content as bytes"""
        try:
            container_name = container_name or self.workspace_container_name
            if not self.blob_exists(blob_name, container_name):
                raise ResourceNotFoundError(f"Blob {blob_name} not found in {container_name}")
            
            logger.debug(f"Downloading blob {blob_name} from {container_name}")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=blob_name
            )
            blob_data = blob_client.download_blob().readall()
            
            logger.info(f"Downloaded blob {blob_name} from {container_name}")
            return blob_data
            
        except Exception as e:
            logger.error(f"Error downloading blob {blob_name} from {container_name}: {e}")
            raise
    
    def upload_blob(self, blob_name: str, data: bytes, container_name: str = None, overwrite: bool = False) -> str:
        """Upload blob data to container"""
        try:
            container_name = container_name or self.workspace_container_name
            if not container_name:
                raise ValueError("Container name must be provided")
            
            # Validate file name and extension
            validated_name = self._validate_file_name(blob_name)
            
            logger.debug(f"Uploading blob {validated_name} to {container_name}")
            
            # Check if blob already exists
            if self.blob_exists(validated_name, container_name):
                if overwrite:
                    logger.warning(f"Overwriting existing blob {validated_name} in {container_name}")
                else:
                    raise ResourceExistsError(f"Blob {validated_name} already exists in {container_name}")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, blob=validated_name
            )
            blob_client.upload_blob(data=data, overwrite=overwrite)
            
            logger.info(f"Uploaded blob {validated_name} to {container_name}")
            return validated_name
            
        except Exception as e:
            logger.error(f"Error uploading blob {blob_name} to {container_name}: {e}")
            raise
    
    def delete_blob(self, blob_name: str, container_name: str = None) -> bool:
        """Delete a blob from container"""
        try:
            container_name = container_name or self.workspace_container_name
            if not isinstance(blob_name, str):
                raise ValueError(f"Blob name must be a string, got {type(blob_name)}")
            
            if self.blob_exists(blob_name, container_name):
                blob_client = self.blob_service_client.get_blob_client(
                    container=container_name, blob=blob_name
                )
                blob_client.delete_blob()
                logger.info(f"Deleted blob {blob_name} from {container_name}")
                return True
            else:
                logger.debug(f"Blob {blob_name} does not exist in {container_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error deleting blob {blob_name} from {container_name}: {e}")
            raise
    
    def copy_blob(self, source_blob_name: str, dest_blob_name: str, 
                  source_container_name: str = None, dest_container_name: str = None, 
                  overwrite: bool = False) -> str:
        """Copy blob from source to destination"""
        try:
            source_container_name = source_container_name or self.workspace_container_name
            dest_container_name = dest_container_name or self.workspace_container_name
            
            # Validate source exists
            if not self.blob_exists(source_blob_name, source_container_name):
                raise ResourceNotFoundError(f"Source blob {source_blob_name} not found in {source_container_name}")
            
            # Check destination
            if self.blob_exists(dest_blob_name, dest_container_name):
                if not overwrite:
                    raise ResourceExistsError(f"Destination blob {dest_blob_name} already exists in {dest_container_name}")
                logger.warning(f"Overwriting {dest_blob_name} in {dest_container_name}")
            
            logger.debug(f"Copying {source_blob_name} from {source_container_name} to {dest_blob_name} in {dest_container_name}")
            
            # Get source blob URL
            source_blob_client = self.blob_service_client.get_blob_client(
                container=source_container_name, blob=source_blob_name
            )
            source_url = source_blob_client.url
            
            # Start copy operation
            dest_blob_client = self.blob_service_client.get_blob_client(
                container=dest_container_name, blob=dest_blob_name
            )
            dest_blob_client.start_copy_from_url(source_url)
            
            logger.info(f"Copy initiated: {source_container_name}/{source_blob_name} -> {dest_container_name}/{dest_blob_name}")
            return dest_blob_name
            
        except Exception as e:
            logger.error(f"Error copying blob: {e}")
            raise
    
    def list_blobs_with_prefix(self, prefix: str, container_name: str = None) -> list:
        """List blobs with a specific prefix"""
        try:
            container_name = container_name or self.workspace_container_name
            container_client = self.blob_service_client.get_container_client(container_name)
            
            blob_list = container_client.list_blobs(name_starts_with=prefix)
            blob_names = [blob.name for blob in blob_list]
            
            logger.info(f"Found {len(blob_names)} blobs with prefix '{prefix}' in {container_name}")
            return blob_names
            
        except Exception as e:
            logger.error(f"Error listing blobs with prefix {prefix}: {e}")
            raise
    
    def get_blob_sas_url(self, container_name: str, blob_name: str, expiry_hours: int = 1) -> str:
        """
        Generate a SAS URL for direct blob access using User Delegation Key with managed identity
        or account key if available
        
        Args:
            container_name: Container name
            blob_name: Blob name
            expiry_hours: Hours until SAS token expires
            
        Returns:
            Full URL with SAS token for blob access
        """
        try:
            from datetime import datetime, timedelta, timezone
            from azure.storage.blob import (
                BlobSasPermissions, 
                generate_blob_sas
            )
            import os
            
            # Get blob client first
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, 
                blob=blob_name
            )
            
            # Check if blob exists
            if not self.blob_exists(blob_name, container_name):
                logger.error(f"Blob {blob_name} not found in container {container_name}")
                # Return the direct URL even if blob doesn't exist (might be useful for error tracking)
                return blob_client.url
            
            # Get account name
            account_name = None
            if hasattr(self.blob_service_client, 'account_name'):
                account_name = self.blob_service_client.account_name
            else:
                # Try to extract from URL
                import re
                match = re.search(r'https://([^.]+)\.blob\.core\.windows\.net', blob_client.url)
                if match:
                    account_name = match.group(1)
            
            if not account_name:
                logger.error("Cannot determine storage account name")
                return blob_client.url
            
            # Initialize both keys as None
            account_key = None
            user_delegation_key = None
            
            # Determine if we're using managed identity or connection string
            # If initialized with managed identity, always use user delegation
            using_managed_identity = False
            
            # Check if blob service client has a credential (managed identity) vs connection string
            if hasattr(self.blob_service_client, 'credential'):
                # Check if it's a DefaultAzureCredential or similar (not account key)
                if not hasattr(self.blob_service_client.credential, 'account_key'):
                    using_managed_identity = True
                    logger.debug("Using managed identity authentication")
            
            if using_managed_identity:
                # Use user delegation for managed identity
                try:
                    user_delegation_key = self.blob_service_client.get_user_delegation_key(
                        key_start_time=datetime.now(timezone.utc),
                        key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
                    )
                    logger.info(f"Successfully got user delegation key for managed identity")
                except Exception as e:
                    logger.error(f"Error getting user delegation key: {e}")
                    raise  # Fail fast if we can't get delegation key with managed identity
            else:
                # Try to get account key from connection string
                conn_str = os.environ.get('AzureWebJobsStorage', '')
                if conn_str and 'AccountKey=' in conn_str:
                    for part in conn_str.split(';'):
                        if part.startswith('AccountKey='):
                            account_key = part.split('=', 1)[1]
                            logger.debug("Using account key from connection string")
                            break
                
                # Also check if credential has account_key
                if not account_key and hasattr(self.blob_service_client, 'credential'):
                    if hasattr(self.blob_service_client.credential, 'account_key'):
                        account_key = self.blob_service_client.credential.account_key
                        logger.debug("Using account key from credential")
            
            # Generate SAS token with whichever key we have
            if account_key or user_delegation_key:
                try:
                    auth_method = "account key" if account_key else "user delegation"
                    logger.debug(f"Generating SAS using {auth_method}")
                    
                    sas_token = generate_blob_sas(
                        account_name=account_name,
                        container_name=container_name,
                        blob_name=blob_name,
                        account_key=account_key,  # Will be None if using user delegation
                        user_delegation_key=user_delegation_key,  # Will be None if using account key
                        permission=BlobSasPermissions(read=True),
                        expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
                    )
                    
                    sas_url = f"{blob_client.url}?{sas_token}"
                    logger.info(f"SAS URI generated for {blob_name} using {auth_method}")
                    return sas_url
                    
                except Exception as e:
                    logger.error(f"Error generating SAS token: {e}")
            
            # If all else fails, return direct URL
            logger.warning(f"Cannot generate SAS token for {blob_name}, returning direct URL")
            return blob_client.url
            
        except Exception as e:
            logger.error(f"Error generating SAS URL for {blob_name}: {e}")
            return blob_client.url
    
    def get_blob_properties(self, container_name: str, blob_name: str) -> Optional[Dict]:
        """
        Get blob properties including size and metadata
        
        Args:
            container_name: Container name
            blob_name: Blob name
            
        Returns:
            Dictionary with blob properties or None if not found
        """
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, 
                blob=blob_name
            )
            
            properties = blob_client.get_blob_properties()
            
            return {
                'size': properties.size,
                'last_modified': properties.last_modified.isoformat() if properties.last_modified else None,
                'content_type': properties.content_settings.content_type if properties.content_settings else None,
                'etag': properties.etag,
                'metadata': properties.metadata
            }
            
        except Exception as e:
            logger.error(f"Error getting properties for blob {blob_name}: {e}")
            return None
    
    def _validate_file_name(self, file_name: str) -> str:
        """Validate file name and extension"""
        try:
            if not isinstance(file_name, str):
                raise TypeError("File name must be a string")
            
            if "." not in file_name:
                raise ValueError("File name must have an extension")
            
            name_parts = file_name.split(".")
            ext = name_parts[-1].lower()
            
            if ext not in self.VALID_EXTENSIONS:
                raise ValueError(f"Invalid file extension: .{ext}. Valid extensions: {', '.join(self.VALID_EXTENSIONS)}")
            
            # Clean up multiple dots
            if len(name_parts) > 2:
                logger.warning(f"File name {file_name} has multiple dots, cleaning up")
                name_base = "_".join(name_parts[:-1])  # Use underscore to join parts
                validated_name = f"{name_base}.{ext}"
            else:
                validated_name = file_name
            
            logger.debug(f"Validated file name: {validated_name}")
            return validated_name
            
        except Exception as e:
            logger.error(f"Error validating file name {file_name}: {e}")
            raise
    
    def queue_message(self, queue_name: str, message_data: Dict) -> bool:
        """
        Send a message to an Azure Storage Queue.
        
        Args:
            queue_name: Name of the queue (e.g., 'geospatial-tasks')
            message_data: Dictionary to send as message
            
        Returns:
            bool: True if message sent successfully
        """
        try:
            from azure.storage.queue import QueueServiceClient
            from azure.identity import DefaultAzureCredential
            import json
            import base64
            
            # Initialize queue service
            account_url = Config.get_storage_account_url('queue')
            queue_service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
            
            # Get queue client
            queue_client = queue_service.get_queue_client(queue_name)
            
            # Ensure queue exists
            try:
                queue_client.create_queue()
            except:
                pass  # Queue already exists
            
            # Encode message to Base64 as expected by Azure Functions
            message_json = json.dumps(message_data)
            encoded_message = base64.b64encode(message_json.encode('utf-8')).decode('ascii')
            
            # Send message
            queue_client.send_message(encoded_message)
            
            logger.info(f"Queued message to {queue_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to queue message to {queue_name}: {e}")
            return False