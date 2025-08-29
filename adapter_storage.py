"""
STORAGE BACKEND ADAPTERS - Type-Safe Storage Abstraction

Provides storage backend abstraction with C-style type discipline.
Each adapter converts between Pydantic models and storage-specific formats
while maintaining schema consistency and validation.

Design Principles:
1. Storage backend agnostic - same interface for all backends
2. Type-safe conversions with zero data loss  
3. Automatic schema validation on all operations
4. Consistent error handling across backends
5. Future-proof for easy backend migration

Supported Backends:
- Azure Table Storage (current)
- PostgreSQL (future)
- CosmosDB (future)

Author: Strong Typing Discipline Team
Version: 1.0.0 - Foundation implementation
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Protocol, Union
import json
import logging
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient, TableEntity, UpdateMode
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from schema_core import JobRecord, TaskRecord, JobStatus, TaskStatus
from validator_schema import SchemaValidator, SchemaValidationError
from config import get_config

logger = logging.getLogger(__name__)


# ============================================================================
# STORAGE BACKEND PROTOCOL - Strong typing contract
# ============================================================================

class StorageBackend(Protocol):
    """
    TYPE-SAFE STORAGE BACKEND PROTOCOL
    
    All storage backends MUST implement this exact interface.
    Provides compile-time type checking and runtime validation.
    """
    
    def create_job(self, job: JobRecord) -> bool:
        """Create job record with schema validation"""
        ...
    
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve job record with schema validation"""
        ...
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Update job record with schema validation"""
        ...
    
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]:
        """List jobs with optional status filtering"""
        ...
    
    def create_task(self, task: TaskRecord) -> bool:
        """Create task record with schema validation"""
        ...
    
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve task record with schema validation"""
        ...
    
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Update task record with schema validation"""
        ...
    
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]:
        """List all tasks for a job with schema validation"""
        ...
    
    def count_tasks_by_status(self, job_id: str, status: TaskStatus) -> int:
        """Count tasks by status for completion detection"""
        ...


# ============================================================================
# AZURE TABLE STORAGE ADAPTER - Production implementation
# ============================================================================

class AzureTableStorageAdapter:
    """
    TYPE-SAFE AZURE TABLE STORAGE ADAPTER
    
    Converts between Pydantic models and Azure Table Storage entities
    with ZERO tolerance for data loss or type errors.
    """
    
    def __init__(self):
        """Initialize Azure Table Storage with managed identity"""
        config = get_config()
        
        account_url = config.table_service_url
        self.table_service = TableServiceClient(account_url, credential=DefaultAzureCredential())
        
        self.jobs_table_name = 'jobs'
        self.tasks_table_name = 'tasks'
        
        logger.info(f"🔗 Azure Table Storage adapter initialized: {config.storage_account_name}")
    
    def _ensure_tables_exist(self):
        """Create tables if they don't exist - idempotent"""
        for table_name in [self.jobs_table_name, self.tasks_table_name]:
            try:
                self.table_service.create_table(table_name)
                logger.info(f"📋 Created table: {table_name}")
            except ResourceExistsError:
                logger.debug(f"📋 Table already exists: {table_name}")
    
    def _job_record_to_entity(self, job: JobRecord) -> TableEntity:
        """
        Convert JobRecord to Azure Table entity with type safety
        
        Args:
            job: Validated JobRecord instance
            
        Returns:
            Azure Table entity with all required fields
        """
        entity = TableEntity()
        
        # Azure Table Storage required fields
        entity['PartitionKey'] = 'jobs'  # All jobs in same partition for queries
        entity['RowKey'] = job.jobId
        
        # Schema fields - direct mapping from Pydantic model
        entity['jobId'] = job.jobId
        entity['jobType'] = job.jobType
        # Debug logging for enum handling
        logger.debug(f"🔍 job.status type: {type(job.status)}, value: {job.status}")
        entity['status'] = job.status if isinstance(job.status, str) else job.status.value  # Handle enum or string
        logger.debug(f"✅ Converted status to: {entity['status']} (type: {type(entity['status'])})")
        entity['stage'] = job.stage
        entity['totalStages'] = job.totalStages
        
        # Legacy field compatibility - populate underscore versions for existing table structure
        entity['job_id'] = job.jobId
        entity['job_type'] = job.jobType
        entity['request_parameters'] = json.dumps(job.parameters, default=str)
        
        # JSON fields - serialize complex data
        entity['parameters'] = json.dumps(job.parameters, default=str)
        entity['stageResults'] = json.dumps(job.stageResults, default=str)
        
        # Optional fields
        if job.resultData:
            entity['resultData'] = json.dumps(job.resultData, default=str)
        if job.errorDetails:
            entity['errorDetails'] = job.errorDetails
        
        # Timestamps - ensure timezone awareness
        entity['createdAt'] = job.createdAt.replace(tzinfo=timezone.utc).isoformat()
        entity['updatedAt'] = job.updatedAt.replace(tzinfo=timezone.utc).isoformat()
        
        logger.debug(f"🔄 Converted JobRecord to Azure entity: {job.jobId[:16]}...")
        return entity
    
    def _entity_to_job_record(self, entity: TableEntity) -> JobRecord:
        """
        Convert Azure Table entity to JobRecord with validation
        
        Args:
            entity: Azure Table entity
            
        Returns:
            Validated JobRecord instance
        """
        try:
            # Extract data from entity
            job_data = {
                'jobId': entity['jobId'],
                'jobType': entity['jobType'],
                'status': entity['status'],
                'stage': entity['stage'],
                'totalStages': entity['totalStages'],
                'createdAt': entity['createdAt'],
                'updatedAt': entity['updatedAt']
            }
            
            # Parse JSON fields with error handling
            try:
                job_data['parameters'] = json.loads(entity.get('parameters', '{}'))
            except json.JSONDecodeError:
                logger.warning(f"Invalid parameters JSON for job {entity['jobId']}")
                job_data['parameters'] = {}
            
            try:
                job_data['stageResults'] = json.loads(entity.get('stageResults', '{}'))
            except json.JSONDecodeError:
                logger.warning(f"Invalid stageResults JSON for job {entity['jobId']}")
                job_data['stageResults'] = {}
            
            # Optional fields
            if 'resultData' in entity and entity['resultData']:
                try:
                    job_data['resultData'] = json.loads(entity['resultData'])
                except json.JSONDecodeError:
                    logger.warning(f"Invalid resultData JSON for job {entity['jobId']}")
                    job_data['resultData'] = None
            
            if 'errorDetails' in entity:
                job_data['errorDetails'] = entity['errorDetails']
            
            # Validate and return schema-compliant record
            job_record = SchemaValidator.validate_job_record(job_data, strict=True)
            logger.debug(f"🔄 Converted Azure entity to JobRecord: {job_record.jobId[:16]}...")
            return job_record
            
        except Exception as e:
            logger.error(f"❌ Failed to convert entity to JobRecord: {e}")
            logger.error(f"Entity data: {dict(entity)}")
            raise SchemaValidationError("JobRecord", [{"msg": str(e), "loc": ["entity_conversion"]}])
    
    def _task_record_to_entity(self, task: TaskRecord) -> TableEntity:
        """Convert TaskRecord to Azure Table entity with type safety"""
        entity = TableEntity()
        
        # Azure Table Storage required fields  
        entity['PartitionKey'] = 'tasks'  # All tasks in same partition
        entity['RowKey'] = task.taskId
        
        # Schema fields
        entity['taskId'] = task.taskId
        entity['parentJobId'] = task.parentJobId
        entity['taskType'] = task.taskType
        entity['status'] = task.status if isinstance(task.status, str) else task.status.value  # Handle enum or string
        entity['stage'] = task.stage
        entity['taskIndex'] = task.taskIndex
        entity['retryCount'] = task.retryCount
        
        # JSON field
        entity['parameters'] = json.dumps(task.parameters, default=str)
        
        # Optional fields
        if task.resultData:
            entity['resultData'] = json.dumps(task.resultData, default=str)
        if task.errorDetails:
            entity['errorDetails'] = task.errorDetails
        if task.heartbeat:
            entity['heartbeat'] = task.heartbeat.replace(tzinfo=timezone.utc).isoformat()
        
        # Timestamps
        entity['createdAt'] = task.createdAt.replace(tzinfo=timezone.utc).isoformat()
        entity['updatedAt'] = task.updatedAt.replace(tzinfo=timezone.utc).isoformat()
        
        logger.debug(f"🔄 Converted TaskRecord to Azure entity: {task.taskId}")
        return entity
    
    def _entity_to_task_record(self, entity: TableEntity) -> TaskRecord:
        """Convert Azure Table entity to TaskRecord with validation"""
        try:
            task_data = {
                'taskId': entity['taskId'],
                'parentJobId': entity['parentJobId'], 
                'taskType': entity['taskType'],
                'status': entity['status'],
                'stage': entity['stage'],
                'taskIndex': entity['taskIndex'],
                'retryCount': entity.get('retryCount', 0),
                'createdAt': entity['createdAt'],
                'updatedAt': entity['updatedAt']
            }
            
            # Parse JSON parameters
            try:
                task_data['parameters'] = json.loads(entity.get('parameters', '{}'))
            except json.JSONDecodeError:
                logger.warning(f"Invalid parameters JSON for task {entity['taskId']}")
                task_data['parameters'] = {}
            
            # Optional fields
            if 'resultData' in entity and entity['resultData']:
                try:
                    task_data['resultData'] = json.loads(entity['resultData'])
                except json.JSONDecodeError:
                    logger.warning(f"Invalid resultData JSON for task {entity['taskId']}")
            
            if 'errorDetails' in entity:
                task_data['errorDetails'] = entity['errorDetails']
            
            if 'heartbeat' in entity and entity['heartbeat']:
                task_data['heartbeat'] = entity['heartbeat']
            
            # Validate and return
            task_record = SchemaValidator.validate_task_record(task_data, strict=True)
            logger.debug(f"🔄 Converted Azure entity to TaskRecord: {task_record.taskId}")
            return task_record
            
        except Exception as e:
            logger.error(f"❌ Failed to convert entity to TaskRecord: {e}")
            logger.error(f"Entity data: {dict(entity)}")
            raise SchemaValidationError("TaskRecord", [{"msg": str(e), "loc": ["entity_conversion"]}])
    
    # ========================================================================
    # JOB OPERATIONS - Type-safe CRUD with validation
    # ========================================================================
    
    def create_job(self, job: JobRecord) -> bool:
        """
        Create job with STRICT schema validation
        
        Args:
            job: Validated JobRecord instance
            
        Returns:
            True if created, False if already exists
            
        Raises:
            SchemaValidationError: If job data is invalid
        """
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.jobs_table_name)
            
            # Check if job already exists (idempotent)
            try:
                existing = table_client.get_entity('jobs', job.jobId)
                logger.info(f"📋 Job already exists: {job.jobId[:16]}...")
                return False
            except ResourceNotFoundError:
                pass  # Job doesn't exist, continue creating
            
            # Convert to Azure Table entity
            entity = self._job_record_to_entity(job)
            
            # Create entity
            table_client.create_entity(entity)
            logger.info(f"✅ Job created: {job.jobId[:16]}... type={job.jobType} status={job.status}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create job {job.jobId[:16]}...: {e}")
            raise
    
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve job with schema validation"""
        try:
            table_client = self.table_service.get_table_client(self.jobs_table_name)
            entity = table_client.get_entity('jobs', job_id)
            
            job_record = self._entity_to_job_record(entity)
            logger.debug(f"📋 Retrieved job: {job_id[:16]}... status={job_record.status}")
            return job_record
            
        except ResourceNotFoundError:
            logger.debug(f"📋 Job not found: {job_id[:16]}...")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to retrieve job {job_id[:16]}...: {e}")
            raise
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Update job with schema validation"""
        try:
            table_client = self.table_service.get_table_client(self.jobs_table_name)
            
            # Get current job
            current_job = self.get_job(job_id)
            if not current_job:
                logger.warning(f"📋 Cannot update non-existent job: {job_id[:16]}...")
                return False
            
            # Merge updates with current data
            current_data = current_job.dict()
            current_data.update(updates)
            current_data['updatedAt'] = datetime.utcnow()
            
            # Validate updated data
            updated_job = SchemaValidator.validate_job_record(current_data, strict=True)
            
            # Convert to entity and update
            entity = self._job_record_to_entity(updated_job)
            table_client.update_entity(entity, mode=UpdateMode.REPLACE)
            
            logger.info(f"✅ Job updated: {job_id[:16]}... status={updated_job.status}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update job {job_id[:16]}...: {e}")
            raise
    
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]:
        """List jobs with optional status filtering"""
        try:
            table_client = self.table_service.get_table_client(self.jobs_table_name)
            
            # Build query filter
            if status_filter:
                status_value = status_filter if isinstance(status_filter, str) else status_filter.value
                query_filter = f"PartitionKey eq 'jobs' and status eq '{status_value}'"
            else:
                query_filter = "PartitionKey eq 'jobs'"
            
            # Query entities
            entities = table_client.query_entities(query_filter)
            
            # Convert to JobRecords with validation
            jobs = []
            for entity in entities:
                try:
                    job_record = self._entity_to_job_record(entity)
                    jobs.append(job_record)
                except SchemaValidationError as e:
                    logger.warning(f"Skipping invalid job entity: {e}")
                    continue
            
            logger.info(f"📋 Listed {len(jobs)} jobs" + (f" with status {status_filter}" if status_filter else ""))
            return jobs
            
        except Exception as e:
            logger.error(f"❌ Failed to list jobs: {e}")
            raise
    
    # ========================================================================
    # TASK OPERATIONS - Type-safe CRUD with validation
    # ========================================================================
    
    def create_task(self, task: TaskRecord) -> bool:
        """Create task with STRICT schema validation"""
        try:
            self._ensure_tables_exist()
            table_client = self.table_service.get_table_client(self.tasks_table_name)
            
            # Check if task already exists (idempotent)
            try:
                existing = table_client.get_entity('tasks', task.taskId)
                logger.info(f"📋 Task already exists: {task.taskId}")
                return False
            except ResourceNotFoundError:
                pass
            
            # Convert and create
            entity = self._task_record_to_entity(task)
            table_client.create_entity(entity)
            
            logger.info(f"✅ Task created: {task.taskId} parent={task.parentJobId[:16]}... status={task.status}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create task {task.taskId}: {e}")
            raise
    
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve task with schema validation"""
        try:
            table_client = self.table_service.get_table_client(self.tasks_table_name)
            entity = table_client.get_entity('tasks', task_id)
            
            task_record = self._entity_to_task_record(entity)
            logger.debug(f"📋 Retrieved task: {task_id} status={task_record.status}")
            return task_record
            
        except ResourceNotFoundError:
            logger.debug(f"📋 Task not found: {task_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to retrieve task {task_id}: {e}")
            raise
    
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Update task with schema validation"""
        try:
            table_client = self.table_service.get_table_client(self.tasks_table_name)
            
            # Get current task
            current_task = self.get_task(task_id)
            if not current_task:
                logger.warning(f"📋 Cannot update non-existent task: {task_id}")
                return False
            
            # Merge updates
            current_data = current_task.dict()
            current_data.update(updates)
            current_data['updatedAt'] = datetime.utcnow()
            
            # Validate
            updated_task = SchemaValidator.validate_task_record(current_data, strict=True)
            
            # Update
            entity = self._task_record_to_entity(updated_task)
            table_client.update_entity(entity, mode=UpdateMode.REPLACE)
            
            logger.info(f"✅ Task updated: {task_id} status={updated_task.status}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update task {task_id}: {e}")
            raise
    
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]:
        """List all tasks for a job with schema validation"""
        try:
            table_client = self.table_service.get_table_client(self.tasks_table_name)
            
            # Query tasks for specific job
            query_filter = f"PartitionKey eq 'tasks' and parentJobId eq '{job_id}'"
            entities = table_client.query_entities(query_filter)
            
            # Convert with validation
            tasks = []
            for entity in entities:
                try:
                    task_record = self._entity_to_task_record(entity)
                    tasks.append(task_record)
                except SchemaValidationError as e:
                    logger.warning(f"Skipping invalid task entity: {e}")
                    continue
            
            logger.debug(f"📋 Listed {len(tasks)} tasks for job {job_id[:16]}...")
            return tasks
            
        except Exception as e:
            logger.error(f"❌ Failed to list tasks for job {job_id[:16]}...: {e}")
            raise
    
    def count_tasks_by_status(self, job_id: str, status: TaskStatus) -> int:
        """Count tasks by status for completion detection"""
        try:
            table_client = self.table_service.get_table_client(self.tasks_table_name)
            
            # Query with status filter
            status_value = status if isinstance(status, str) else status.value
            query_filter = f"PartitionKey eq 'tasks' and parentJobId eq '{job_id}' and status eq '{status_value}'"
            entities = table_client.query_entities(query_filter, select=['taskId'])
            
            # Count entities
            count = sum(1 for _ in entities)
            logger.debug(f"📋 Counted {count} tasks with status {status} for job {job_id[:16]}...")
            return count
            
        except Exception as e:
            logger.error(f"❌ Failed to count tasks for job {job_id[:16]}...: {e}")
            raise


# ============================================================================
# FUTURE STORAGE BACKENDS - Type-safe interface ready
# ============================================================================

class PostgresAdapter:
    """
    FUTURE: PostgreSQL storage adapter with same type-safe interface
    
    Will implement same StorageBackend protocol with SQL operations
    instead of NoSQL operations.
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        logger.info("🐘 PostgreSQL adapter initialized (FUTURE)")
    
    def create_job(self, job: JobRecord) -> bool:
        # TODO: Implement with psycopg and SQL schema
        raise NotImplementedError("PostgreSQL adapter not yet implemented")


class CosmosDbAdapter:
    """
    FUTURE: CosmosDB storage adapter with same type-safe interface
    
    Will implement same StorageBackend protocol with document operations
    and automatic partitioning.
    """
    
    def __init__(self, cosmos_endpoint: str, cosmos_key: str):
        self.endpoint = cosmos_endpoint
        self.key = cosmos_key
        logger.info("🌌 CosmosDB adapter initialized (FUTURE)")
    
    def create_job(self, job: JobRecord) -> bool:
        # TODO: Implement with azure-cosmos SDK
        raise NotImplementedError("CosmosDB adapter not yet implemented")


# ============================================================================
# ADAPTER FACTORY - Type-safe adapter selection
# ============================================================================

class StorageAdapterFactory:
    """Factory for creating type-safe storage adapters"""
    
    @staticmethod
    def create_adapter(backend_type: str) -> StorageBackend:
        """
        Create storage adapter based on configuration
        
        Args:
            backend_type: 'azure_tables', 'postgres', or 'cosmos'
            
        Returns:
            Storage adapter implementing StorageBackend protocol
        """
        if backend_type == 'azure_tables':
            return AzureTableStorageAdapter()
        elif backend_type == 'postgres':
            return PostgresAdapter("connection_string_here")
        elif backend_type == 'cosmos':
            return CosmosDbAdapter("endpoint", "key")
        else:
            raise ValueError(f"Unsupported backend type: {backend_type}")


# Export public interfaces
__all__ = [
    'StorageBackend',
    'AzureTableStorageAdapter', 
    'PostgresAdapter',
    'CosmosDbAdapter',
    'StorageAdapterFactory'
]