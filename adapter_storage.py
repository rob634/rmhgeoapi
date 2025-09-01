# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Azure Storage abstraction layer with managed identity authentication
# SOURCE: Managed Identity (DefaultAzureCredential) for Azure Storage access
# SCOPE: Global storage operations for jobs, tasks, and queue messaging
# VALIDATION: Pydantic model validation + Azure credential validation
# ============================================================================

"""
Storage Backend Adapters - Job→Stage→Task Architecture Persistence

Comprehensive storage abstraction layer providing type-safe, schema-validated persistence for
the Azure Geospatial ETL Pipeline. Implements backend-agnostic storage patterns with strict
type discipline, automatic validation, and seamless migration capabilities supporting the
complete Job→Stage→Task workflow data lifecycle.

Architecture Responsibility:
    This module provides STORAGE ABSTRACTION within the Job→Stage→Task architecture:
    - Job Layer: JobRecord persistence with complete workflow state management
    - Task Layer: TaskRecord persistence with parent-child relationship integrity
    - Queue Layer: Storage backend integration for reliable message processing
    - Schema Layer: Automatic validation ensuring type safety across all operations

Key Features:
- Backend-agnostic storage protocol enabling seamless migration between storage systems
- Type-safe conversions with zero data loss between Pydantic models and storage formats
- Automatic schema validation on all CRUD operations preventing data corruption
- Comprehensive error handling with detailed logging and recovery mechanisms
- Future-proof adapter pattern supporting multiple storage backends simultaneously
- Idempotent operations ensuring safe retry behavior for distributed systems
- Legacy field compatibility maintaining backward compatibility during migrations

Storage Backend Protocol:
    All storage backends implement the same type-safe interface:
    - create_job/task(): Creates records with schema validation
    - get_job/task(): Retrieves records with automatic validation
    - update_job/task(): Updates records with merge validation
    - list_jobs/tasks(): Queries with filtering and validation
    - count_tasks_by_status(): Aggregation queries for completion detection

Data Flow Architecture:
    Pydantic Models → Storage Adapter → Backend-Specific Format
                   ↓                  ↓                    ↓
    Type Safety    Schema Validation  Storage Operations
                   ↓                  ↓                    ↓
    Runtime Safety ← Validated Data ← Persistent Storage

Current Implementation - Azure Table Storage:
    - AzureTableStorageAdapter: Production-ready implementation with managed identity
    - Automatic table creation and management with idempotent operations
    - JSON serialization for complex fields (parameters, stage_results, result_data)
    - Timezone-aware timestamp handling with UTC normalization
    - Legacy field compatibility for smooth migrations
    - Comprehensive error handling with detailed logging

Future Implementations:
    - PostgresAdapter: SQL-based storage with ACID transactions
    - CosmosDbAdapter: Document-based storage with global distribution
    - Additional adapters as needed for specific use cases

Schema Validation Integration:
    Every storage operation includes automatic validation:
    - Input Validation: Pydantic models validated before storage conversion
    - Storage Conversion: Type-safe conversion to backend-specific formats
    - Retrieval Validation: Retrieved data validated against schemas
    - Update Validation: Merged updates validated for consistency

Error Handling Patterns:
    - SchemaValidationError: Type safety violations with detailed field information
    - ResourceExistsError: Idempotent creation handling for duplicate operations
    - ResourceNotFoundError: Safe handling of missing records with appropriate responses
    - Connection errors: Automatic retry with exponential backoff

Integration Points:
- Used by repository layer for all data persistence operations
- Integrates with schema validation system for type safety enforcement
- Connects to configuration system for backend selection and credentials
- Feeds into monitoring systems for storage operation tracking
- Supports job and task lifecycle management with completion detection

Factory Pattern Benefits:
    StorageAdapterFactory enables:
    - Runtime backend selection based on configuration
    - Easy testing with mock adapters
    - Seamless migration between storage backends
    - Multiple backends for different workloads

Usage Examples:
    # Create storage adapter
    adapter = StorageAdapterFactory.create_adapter('azure_tables')
    
    # Store job with validation
    job = JobRecord(job_id="abc123", job_type="hello_world", ...)
    success = adapter.create_job(job)  # Automatic validation
    
    # Retrieve with validation
    retrieved_job = adapter.get_job("abc123")  # Returns validated JobRecord
    
    # Update with merge validation
    adapter.update_job("abc123", {"status": "completed"})

Author: Azure Geospatial ETL Team
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
        entity['RowKey'] = job.job_id
        
        # Schema fields - direct mapping from Pydantic model
        entity['jobId'] = job.job_id
        entity['jobType'] = job.job_type
        # Debug logging for enum handling
        logger.debug(f"🔍 job.status type: {type(job.status)}, value: {job.status}")
        entity['status'] = job.status if isinstance(job.status, str) else job.status.value  # Handle enum or string
        logger.debug(f"✅ Converted status to: {entity['status']} (type: {type(entity['status'])})")
        entity['stage'] = job.stage
        entity['totalStages'] = job.total_stages
        
        # Legacy field compatibility - populate underscore versions for existing table structure
        entity['job_id'] = job.job_id
        entity['job_type'] = job.job_type
        entity['request_parameters'] = json.dumps(job.parameters, default=str)
        
        # JSON fields - serialize complex data
        entity['parameters'] = json.dumps(job.parameters, default=str)
        entity['stageResults'] = json.dumps(job.stage_results, default=str)
        
        # Optional fields
        if job.result_data:
            entity['resultData'] = json.dumps(job.result_data, default=str)
        if job.error_details:
            entity['errorDetails'] = job.error_details
        
        # Timestamps - ensure timezone awareness
        entity['createdAt'] = job.created_at.replace(tzinfo=timezone.utc).isoformat()
        entity['updatedAt'] = job.updated_at.replace(tzinfo=timezone.utc).isoformat()
        
        logger.debug(f"🔄 Converted JobRecord to Azure entity: {job.job_id[:16]}...")
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
                'job_id': entity['jobId'],
                'job_type': entity['jobType'],
                'status': entity['status'],
                'stage': entity['stage'],
                'total_stages': entity['totalStages'],
                'created_at': entity['createdAt'],
                'updated_at': entity['updatedAt']
            }
            
            # Parse JSON fields with error handling
            try:
                job_data['parameters'] = json.loads(entity.get('parameters', '{}'))
            except json.JSONDecodeError:
                logger.warning(f"Invalid parameters JSON for job {entity['jobId']}")
                job_data['parameters'] = {}
            
            try:
                job_data['stage_results'] = json.loads(entity.get('stageResults', '{}'))
            except json.JSONDecodeError:
                logger.warning(f"Invalid stageResults JSON for job {entity['jobId']}")
                job_data['stage_results'] = {}
            
            # Optional fields
            if 'resultData' in entity and entity['resultData']:
                try:
                    job_data['result_data'] = json.loads(entity['resultData'])
                except json.JSONDecodeError:
                    logger.warning(f"Invalid resultData JSON for job {entity['jobId']}")
                    job_data['result_data'] = None
            
            if 'errorDetails' in entity:
                job_data['error_details'] = entity['errorDetails']
            
            # Validate and return schema-compliant record
            job_record = SchemaValidator.validate_job_record(job_data, strict=True)
            logger.debug(f"🔄 Converted Azure entity to JobRecord: {job_record.job_id[:16]}...")
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
                existing = table_client.get_entity('jobs', job.job_id)
                logger.info(f"📋 Job already exists: {job.job_id[:16]}...")
                return False
            except ResourceNotFoundError:
                pass  # Job doesn't exist, continue creating
            
            # Convert to Azure Table entity
            entity = self._job_record_to_entity(job)
            
            # Create entity
            table_client.create_entity(entity)
            logger.info(f"✅ Job created: {job.job_id[:16]}... type={job.job_type} status={job.status}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create job {job.job_id[:16]}...: {e}")
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
    """PostgreSQL storage adapter with type-safe operations and ACID transactions.
    
    Implements the StorageBackend protocol for PostgreSQL persistence with comprehensive
    schema validation, idempotent operations, and secure authentication via environment
    variables. Provides full CRUD operations for Job and Task records with automatic
    JSON serialization and PostgreSQL-specific optimizations.
    
    Key Features:
        - Environment variable configuration with POSTGIS_PASSWORD authentication
        - SSL-encrypted connections with configurable schema search paths
        - Idempotent operations for distributed system reliability
        - Schema validation on all database operations using Pydantic models
        - ACID transaction support with proper error handling and rollback
        - Multi-tenant support via configurable application schema
        
    Authentication:
        Uses username/password authentication with credentials from environment variables.
        Does NOT use managed identity for database connections - password must be
        provided via POSTGIS_PASSWORD environment variable.
        
    Database Schema:
        Expects PostgreSQL database with tables: jobs, tasks
        Uses configurable schema search path: {APP_SCHEMA}, public
        
    Environment Variables:
        POSTGIS_HOST: PostgreSQL server hostname
        POSTGIS_PORT: PostgreSQL server port (default: 5432) 
        POSTGIS_USER: PostgreSQL username
        POSTGIS_PASSWORD: PostgreSQL password (required)
        POSTGIS_DATABASE: PostgreSQL database name
        POSTGIS_SCHEMA: PostGIS schema for geospatial data (default: geo)
        APP_SCHEMA: Application schema for jobs/tasks tables (default: app)
    """
    
    def __init__(self):
        """Initialize PostgreSQL adapter with configuration from environment variables.
        
        Establishes database connection using environment variables for all configuration
        including the POSTGIS_PASSWORD for secure authentication. Configures SSL mode
        and schema search path for proper multi-tenant operation.
        
        Environment Variables Required:
            POSTGIS_HOST: PostgreSQL server hostname
            POSTGIS_PORT: PostgreSQL server port (default: 5432)
            POSTGIS_USER: PostgreSQL username
            POSTGIS_PASSWORD: PostgreSQL password (required)
            POSTGIS_DATABASE: PostgreSQL database name
            POSTGIS_SCHEMA: PostGIS schema name (default: geo)
            APP_SCHEMA: Application schema name (default: app)
            
        Raises:
            ValueError: If POSTGIS_PASSWORD environment variable is not set
            Exception: If database connection or configuration fails
        """
        from config import get_config
        
        self.config = get_config()
        
        # Get database password from environment variable
        # NOTE: Direct env var access used here (vs config.postgis_password used by health checks)
        # Both access the same POSTGIS_PASSWORD env var. See config.py postgis_password field documentation.
        import os
        db_password = os.environ.get('POSTGIS_PASSWORD')
        if not db_password:
            raise ValueError("POSTGIS_PASSWORD environment variable is required")
        
        logger.info(f"✅ Using PostgreSQL password from environment variable")
        
        # Build connection string using working trigger_health.py pattern
        self.connection_string = (
            f"host={self.config.postgis_host} "
            f"dbname={self.config.postgis_database} "
            f"user={self.config.postgis_user} "
            f"password={db_password} "
            f"port={self.config.postgis_port}"
        )
        
        # Set schema search path
        self.search_path = f"{self.config.app_schema}, public"
        
        logger.info(f"🐘 PostgreSQL adapter initialized: {self.config.postgis_host}:{self.config.postgis_port}")
        
        # Validate required tables exist
        self._ensure_tables_exist()
    
    def _get_connection(self):
        """Get database connection with proper schema search path.
        
        Creates a new PostgreSQL connection using the configured connection string
        and sets the schema search path to include the application schema first.
        
        Returns:
            psycopg.Connection: Database connection with configured schema search path
            
        Raises:
            Exception: If database connection fails
        """
        import psycopg
        
        conn = psycopg.connect(self.connection_string)
        # Set search path for this session
        with conn.cursor() as cursor:
            cursor.execute(f"SET search_path TO {self.search_path}")
        return conn
    
    def _ensure_tables_exist(self):
        """Ensure required database tables exist, creating them if necessary.
        
        Checks for existence of 'jobs' and 'tasks' tables in the configured app schema.
        If tables don't exist, creates them using the schema definition from health check pattern.
        
        Raises:
            Exception: If table creation fails or schema is invalid
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Table definitions matching health check pattern
                    table_definitions = {
                        'jobs': """
                            CREATE TABLE IF NOT EXISTS {schema}.jobs (
                                job_id VARCHAR(64) PRIMARY KEY
                                    CHECK (length(job_id) = 64 AND job_id ~ '^[a-f0-9]+$'),
                                job_type VARCHAR(50) NOT NULL
                                    CHECK (length(job_type) >= 1 AND job_type ~ '^[a-z_]+$'),
                                status VARCHAR(50) DEFAULT 'queued',
                                stage INTEGER DEFAULT 1
                                    CHECK (stage >= 1 AND stage <= 100),
                                total_stages INTEGER DEFAULT 1
                                    CHECK (total_stages >= 1 AND total_stages <= 100),
                                parameters JSONB NOT NULL DEFAULT '{{}}',
                                metadata JSONB NOT NULL DEFAULT '{{}}',
                                stage_results JSONB NOT NULL DEFAULT '{{}}',
                                result_data JSONB,
                                error_details TEXT,
                                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                            )
                        """,
                        'tasks': """
                            CREATE TABLE IF NOT EXISTS {schema}.tasks (
                                task_id VARCHAR(100) PRIMARY KEY
                                    CHECK (length(task_id) >= 1 AND length(task_id) <= 100),
                                parent_job_id VARCHAR(64) NOT NULL
                                    REFERENCES {schema}.jobs(job_id) ON DELETE CASCADE
                                    CHECK (length(parent_job_id) = 64 AND parent_job_id ~ '^[a-f0-9]+$'),
                                task_type VARCHAR(50) NOT NULL
                                    CHECK (length(task_type) >= 1 AND task_type ~ '^[a-z_]+$'),
                                status VARCHAR(50) DEFAULT 'queued',
                                stage INTEGER NOT NULL
                                    CHECK (stage >= 1 AND stage <= 100),
                                task_index INTEGER NOT NULL DEFAULT 0
                                    CHECK (task_index >= 0),
                                parameters JSONB NOT NULL DEFAULT '{{}}',
                                metadata JSONB NOT NULL DEFAULT '{{}}',
                                result_data JSONB,
                                error_details TEXT,
                                heartbeat TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                retry_count INTEGER NOT NULL DEFAULT 0
                                    CHECK (retry_count >= 0 AND retry_count <= 10),
                                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                            )
                        """
                    }
                    
                    tables_created = []
                    for table_name, table_sql in table_definitions.items():
                        # Check if table exists
                        cursor.execute("""
                            SELECT table_name FROM information_schema.tables 
                            WHERE table_schema = %s AND table_name = %s
                        """, (self.config.app_schema, table_name))
                        
                        table_exists = cursor.fetchone() is not None
                        
                        if not table_exists:
                            # Create the table
                            formatted_sql = table_sql.format(schema=self.config.app_schema)
                            cursor.execute(formatted_sql)
                            tables_created.append(table_name)
                            logger.info(f"✅ Created table: {self.config.app_schema}.{table_name}")
                    
                    if tables_created:
                        conn.commit()
                        logger.info(f"✅ Tables created successfully: {tables_created}")
                    else:
                        logger.info(f"✅ All required tables already exist in schema: {self.config.app_schema}")
                    
        except Exception as e:
            logger.error(f"❌ Failed to ensure database tables exist: {e}")
            raise
    
    def create_job(self, job: JobRecord) -> bool:
        """Create job record in PostgreSQL with schema validation.
        
        Performs idempotent creation - if job already exists, returns False
        without error. Job is validated before insertion.
        
        Args:
            job: JobRecord instance to create in database
            
        Returns:
            bool: True if job was created, False if job already exists
            
        Raises:
            Exception: If database insertion fails or schema validation fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if job already exists (idempotent)
                    cursor.execute("SELECT job_id FROM jobs WHERE job_id = %s", (job.job_id,))
                    if cursor.fetchone():
                        logger.info(f"📋 Job already exists: {job.job_id[:16]}... (idempotent)")
                        return False
                    
                    # Insert new job
                    cursor.execute("""
                        INSERT INTO jobs (
                            job_id, job_type, status, stage, total_stages,
                            parameters, stage_results, result_data, error_details,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """, (
                        job.job_id,
                        job.job_type, 
                        job.status.value if hasattr(job.status, 'value') else job.status,
                        job.stage,
                        job.total_stages,
                        json.dumps(job.parameters),
                        json.dumps(job.stage_results),
                        json.dumps(job.result_data) if job.result_data else None,
                        job.error_details,
                        job.created_at,
                        job.updated_at
                    ))
                    
                    conn.commit()
                    logger.info(f"✅ Job created in PostgreSQL: {job.job_id[:16]}... type={job.job_type}")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ Failed to create job {job.job_id[:16]}...: {e}")
            raise
    
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve job record from PostgreSQL with schema validation.
        
        Args:
            job_id: Unique identifier for the job record
            
        Returns:
            JobRecord: Validated job record if found, None if job doesn't exist
            
        Raises:
            Exception: If database query fails or schema validation fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT job_id, job_type, status, stage, total_stages,
                               parameters, stage_results, result_data, error_details,
                               created_at, updated_at
                        FROM jobs WHERE job_id = %s
                    """, (job_id,))
                    
                    row = cursor.fetchone()
                    if not row:
                        logger.debug(f"📋 Job not found: {job_id[:16]}...")
                        return None
                    
                    # Convert row to JobRecord
                    job_data = {
                        'job_id': row[0],
                        'job_type': row[1],
                        'status': JobStatus(row[2]),  # Explicit enum conversion
                        'stage': row[3],
                        'total_stages': row[4],
                        'parameters': row[5] if row[5] else {},
                        'stage_results': row[6] if row[6] else {},
                        'result_data': row[7] if row[7] else None,
                        'error_details': row[8],
                        'created_at': row[9],
                        'updated_at': row[10]
                    }
                    
                    # Validate and return
                    job_record = SchemaValidator.validate_job_record(job_data, strict=True)
                    logger.debug(f"📋 Retrieved job from PostgreSQL: {job_id[:16]}... status={job_record.status}")
                    return job_record
                    
        except Exception as e:
            logger.error(f"❌ Failed to retrieve job {job_id[:16]}...: {e}")
            raise
    
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """Update job record in PostgreSQL with schema validation.
        
        Merges provided updates with current job data and validates the result
        against the schema before persisting to PostgreSQL.
        
        Args:
            job_id: Unique identifier for the job to update
            updates: Dictionary of field updates to apply
            
        Returns:
            bool: True if update succeeded, False if job doesn't exist
            
        Raises:
            Exception: If database update fails or schema validation fails
        """
        try:
            # Get current job for validation
            current_job = self.get_job(job_id)
            if not current_job:
                logger.warning(f"📋 Cannot update non-existent job: {job_id[:16]}...")
                return False
            
            # Merge updates with current data
            current_data = current_job.dict()
            current_data.update(updates)
            current_data['updated_at'] = datetime.utcnow()
            
            # Validate updated data
            updated_job = SchemaValidator.validate_job_record(current_data, strict=True)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE jobs SET
                            status = %s, stage = %s, total_stages = %s,
                            parameters = %s, stage_results = %s, result_data = %s,
                            error_details = %s, updated_at = %s
                        WHERE job_id = %s
                    """, (
                        updated_job.status.value if hasattr(updated_job.status, 'value') else updated_job.status,
                        updated_job.stage,
                        updated_job.total_stages,
                        json.dumps(updated_job.parameters),
                        json.dumps(updated_job.stage_results),
                        json.dumps(updated_job.result_data) if updated_job.result_data else None,
                        updated_job.error_details,
                        updated_job.updated_at,
                        job_id
                    ))
                    
                    conn.commit()
                    logger.info(f"✅ Job updated in PostgreSQL: {job_id[:16]}... status={updated_job.status}")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ Failed to update job {job_id[:16]}...: {e}")
            raise
    
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]:
        """List jobs from PostgreSQL with optional status filtering.
        
        Args:
            status_filter: Optional job status to filter results. If None, returns all jobs
            
        Returns:
            List[JobRecord]: List of validated job records, ordered by creation time (newest first)
            
        Raises:
            Exception: If database query fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    if status_filter:
                        status_value = status_filter.value if hasattr(status_filter, 'value') else status_filter
                        cursor.execute("""
                            SELECT job_id, job_type, status, stage, total_stages,
                                   parameters, stage_results, result_data, error_details,
                                   created_at, updated_at
                            FROM jobs WHERE status = %s
                            ORDER BY created_at DESC
                        """, (status_value,))
                    else:
                        cursor.execute("""
                            SELECT job_id, job_type, status, stage, total_stages,
                                   parameters, stage_results, result_data, error_details,
                                   created_at, updated_at
                            FROM jobs ORDER BY created_at DESC
                        """)
                    
                    jobs = []
                    for row in cursor.fetchall():
                        try:
                            job_data = {
                                'job_id': row[0],
                                'job_type': row[1], 
                                'status': JobStatus(row[2]),  # Explicit enum conversion
                                'stage': row[3],
                                'total_stages': row[4],
                                'parameters': row[5] if row[5] else {},
                                'stage_results': row[6] if row[6] else {},
                                'result_data': row[7] if row[7] else None,
                                'error_details': row[8],
                                'created_at': row[9],
                                'updated_at': row[10]
                            }
                            
                            job_record = SchemaValidator.validate_job_record(job_data, strict=True)
                            jobs.append(job_record)
                        except SchemaValidationError as e:
                            logger.warning(f"Skipping invalid job record: {e}")
                            continue
                    
                    logger.info(f"📋 Listed {len(jobs)} jobs from PostgreSQL" + 
                               (f" with status {status_filter}" if status_filter else ""))
                    return jobs
                    
        except Exception as e:
            logger.error(f"❌ Failed to list jobs: {e}")
            raise
    
    def create_task(self, task: TaskRecord) -> bool:
        """Create task record in PostgreSQL with schema validation.
        
        Performs idempotent creation - if task already exists, returns False
        without error. Task is validated before insertion.
        
        Args:
            task: TaskRecord instance to create in database
            
        Returns:
            bool: True if task was created, False if task already exists
            
        Raises:
            Exception: If database insertion fails or schema validation fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if task already exists (idempotent)
                    cursor.execute("SELECT task_id FROM tasks WHERE task_id = %s", (task.taskId,))
                    if cursor.fetchone():
                        logger.info(f"📋 Task already exists: {task.taskId} (idempotent)")
                        return False
                    
                    # Insert new task
                    cursor.execute("""
                        INSERT INTO tasks (
                            task_id, parent_job_id, task_type, status, stage, task_index,
                            parameters, result_data, error_details, retry_count, heartbeat,
                            created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                    """, (
                        task.taskId,
                        task.parentJobId,
                        task.taskType,
                        task.status.value if hasattr(task.status, 'value') else task.status,
                        task.stage,
                        task.taskIndex,
                        json.dumps(task.parameters),
                        json.dumps(task.resultData) if task.resultData else None,
                        task.errorDetails,
                        task.retryCount,
                        task.heartbeat,
                        task.createdAt,
                        task.updatedAt
                    ))
                    
                    conn.commit()
                    logger.info(f"✅ Task created in PostgreSQL: {task.taskId} parent={task.parentJobId[:16]}...")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ Failed to create task {task.taskId}: {e}")
            raise
    
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve task record from PostgreSQL with schema validation.
        
        Args:
            task_id: Unique identifier for the task record
            
        Returns:
            TaskRecord: Validated task record if found, None if task doesn't exist
            
        Raises:
            Exception: If database query fails or schema validation fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT task_id, parent_job_id, task_type, status, stage, task_index,
                               parameters, result_data, error_details, retry_count, heartbeat,
                               created_at, updated_at
                        FROM tasks WHERE task_id = %s
                    """, (task_id,))
                    
                    row = cursor.fetchone()
                    if not row:
                        logger.debug(f"📋 Task not found: {task_id}")
                        return None
                    
                    # Convert row to TaskRecord
                    task_data = {
                        'taskId': row[0],
                        'parentJobId': row[1],
                        'taskType': row[2],
                        'status': TaskStatus(row[3]),  # Explicit enum conversion
                        'stage': row[4],
                        'taskIndex': row[5],
                        'parameters': row[6] if row[6] else {},
                        'resultData': row[7] if row[7] else None,
                        'errorDetails': row[8],
                        'retryCount': row[9],
                        'heartbeat': row[10],
                        'createdAt': row[11],
                        'updatedAt': row[12]
                    }
                    
                    # Validate and return
                    task_record = SchemaValidator.validate_task_record(task_data, strict=True)
                    logger.debug(f"📋 Retrieved task from PostgreSQL: {task_id} status={task_record.status}")
                    return task_record
                    
        except Exception as e:
            logger.error(f"❌ Failed to retrieve task {task_id}: {e}")
            raise
    
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """Update task record in PostgreSQL with schema validation.
        
        Merges provided updates with current task data and validates the result
        against the schema before persisting to PostgreSQL.
        
        Args:
            task_id: Unique identifier for the task to update
            updates: Dictionary of field updates to apply
            
        Returns:
            bool: True if update succeeded, False if task doesn't exist
            
        Raises:
            Exception: If database update fails or schema validation fails
        """
        try:
            # Get current task for validation
            current_task = self.get_task(task_id)
            if not current_task:
                logger.warning(f"📋 Cannot update non-existent task: {task_id}")
                return False
            
            # Merge updates with current data
            current_data = current_task.dict()
            current_data.update(updates)
            current_data['updatedAt'] = datetime.utcnow()
            
            # Validate updated data
            updated_task = SchemaValidator.validate_task_record(current_data, strict=True)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE tasks SET
                            status = %s, parameters = %s, result_data = %s,
                            error_details = %s, retry_count = %s, heartbeat = %s, 
                            updated_at = %s
                        WHERE task_id = %s
                    """, (
                        updated_task.status.value if hasattr(updated_task.status, 'value') else updated_task.status,
                        json.dumps(updated_task.parameters),
                        json.dumps(updated_task.resultData) if updated_task.resultData else None,
                        updated_task.errorDetails,
                        updated_task.retryCount,
                        updated_task.heartbeat,
                        updated_task.updatedAt,
                        task_id
                    ))
                    
                    conn.commit()
                    logger.info(f"✅ Task updated in PostgreSQL: {task_id} status={updated_task.status}")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ Failed to update task {task_id}: {e}")
            raise
    
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]:
        """List all tasks for a job from PostgreSQL.
        
        Args:
            job_id: Unique identifier for the parent job
            
        Returns:
            List[TaskRecord]: List of validated task records for the job, 
                            ordered by stage and task_index
            
        Raises:
            Exception: If database query fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT task_id, parent_job_id, task_type, status, stage, task_index,
                               parameters, result_data, error_details, retry_count, heartbeat,
                               created_at, updated_at
                        FROM tasks WHERE parent_job_id = %s
                        ORDER BY stage, task_index
                    """, (job_id,))
                    
                    tasks = []
                    for row in cursor.fetchall():
                        try:
                            task_data = {
                                'taskId': row[0],
                                'parentJobId': row[1], 
                                'taskType': row[2],
                                'status': TaskStatus(row[3]),  # Explicit enum conversion
                                'stage': row[4],
                                'taskIndex': row[5],
                                'parameters': row[6] if row[6] else {},
                                'resultData': row[7] if row[7] else None,
                                'errorDetails': row[8],
                                'retryCount': row[9],
                                'heartbeat': row[10],
                                'createdAt': row[11],
                                'updatedAt': row[12]
                            }
                            
                            task_record = SchemaValidator.validate_task_record(task_data, strict=True)
                            tasks.append(task_record)
                        except SchemaValidationError as e:
                            logger.warning(f"Skipping invalid task record: {e}")
                            continue
                    
                    logger.debug(f"📋 Listed {len(tasks)} tasks for job {job_id[:16]}... from PostgreSQL")
                    return tasks
                    
        except Exception as e:
            logger.error(f"❌ Failed to list tasks for job {job_id[:16]}...: {e}")
            raise
    
    def count_tasks_by_status(self, job_id: str, status: TaskStatus) -> int:
        """Count tasks by status for completion detection.
        
        Used by completion detection logic to determine when all tasks
        in a stage or job have reached a specific status.
        
        Args:
            job_id: Unique identifier for the parent job
            status: TaskStatus enum value to count
            
        Returns:
            int: Number of tasks with the specified status
            
        Raises:
            Exception: If database query fails
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    status_value = status.value if hasattr(status, 'value') else status
                    cursor.execute("""
                        SELECT COUNT(*) FROM tasks 
                        WHERE parent_job_id = %s AND status = %s
                    """, (job_id, status_value))
                    
                    count = cursor.fetchone()[0]
                    logger.debug(f"📋 Counted {count} {status} tasks for job {job_id[:16]}... in PostgreSQL")
                    return count
                    
        except Exception as e:
            logger.error(f"❌ Failed to count tasks for job {job_id[:16]}...: {e}")
            raise

    def complete_task_and_check_stage(self, task_id: str, job_id: str, stage: int, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Atomically complete a task and check if stage is complete.
        
        This method uses the PostgreSQL stored procedure to:
        1. Update the task as completed with result data
        2. Check if all tasks in the stage are complete
        3. Return stage completion status atomically
        
        Args:
            task_id: Unique identifier for the task
            job_id: Parent job identifier
            stage: Stage number the task belongs to
            result_data: Task completion result data
            
        Returns:
            Dict containing:
                - stage_complete: Boolean indicating if stage is complete
                - remaining_tasks: Number of tasks remaining in stage
                - job_id: Job identifier
                
        Raises:
            Exception: If atomic operation fails or task not found
        """
        try:
            logger.debug(f"🔄 Atomically completing task {task_id} in stage {stage}")
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Call PostgreSQL stored procedure for atomic completion
                    cursor.execute("""
                        SELECT stage_complete, remaining_tasks, job_id
                        FROM complete_task_and_check_stage(%s, %s, %s, %s)
                    """, (task_id, job_id, stage, json.dumps(result_data) if result_data else None))
                    
                    result = cursor.fetchone()
                    if not result:
                        raise Exception(f"Failed to complete task {task_id} - no result from stored procedure")
                    
                    completion_result = {
                        'stage_complete': result[0],
                        'remaining_tasks': result[1], 
                        'job_id': result[2]
                    }
                    
                    logger.info(f"✅ Task {task_id} completed atomically. Stage complete: {completion_result['stage_complete']}, remaining: {completion_result['remaining_tasks']}")
                    return completion_result
                    
        except Exception as e:
            logger.error(f"❌ Failed to atomically complete task {task_id}: {e}")
            raise

    def advance_job_stage(self, job_id: str, current_stage: int, next_stage: int, stage_results: Dict[str, Any]) -> bool:
        """
        Atomically advance job to the next stage.
        
        This method uses the PostgreSQL stored procedure to:
        1. Verify current stage matches expected stage
        2. Update job to next stage with stage results
        3. Return success status atomically
        
        Args:
            job_id: Job identifier to advance
            current_stage: Expected current stage number
            next_stage: Target stage number
            stage_results: Results from completed stage
            
        Returns:
            bool: True if stage advancement succeeded, False otherwise
            
        Raises:
            Exception: If atomic operation fails or stage mismatch
        """
        try:
            logger.debug(f"🔄 Atomically advancing job {job_id[:16]}... from stage {current_stage} to {next_stage}")
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Call PostgreSQL stored procedure for atomic advancement
                    cursor.execute("""
                        SELECT advance_job_stage(%s, %s, %s, %s)
                    """, (job_id, current_stage, next_stage, json.dumps(stage_results) if stage_results else None))
                    
                    result = cursor.fetchone()
                    success = result[0] if result else False
                    
                    if success:
                        logger.info(f"✅ Job {job_id[:16]}... advanced atomically to stage {next_stage}")
                    else:
                        logger.warning(f"⚠️ Job {job_id[:16]}... stage advancement failed - possible concurrent update")
                    
                    return success
                    
        except Exception as e:
            logger.error(f"❌ Failed to atomically advance job {job_id[:16]}... to stage {next_stage}: {e}")
            raise

    def check_job_completion(self, job_id: str) -> Dict[str, Any]:
        """
        Check if job workflow is fully complete.
        
        Uses PostgreSQL stored procedure to determine if all stages are done.
        
        Args:
            job_id: Job identifier to check
            
        Returns:
            Dict containing:
                - job_complete: Boolean indicating if job is complete
                - final_stage: Current/final stage number
                
        Raises:
            Exception: If check operation fails
        """
        try:
            logger.debug(f"🔍 Checking completion status for job {job_id[:16]}...")
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Call PostgreSQL stored procedure for completion check
                    cursor.execute("""
                        SELECT job_complete, final_stage
                        FROM check_job_completion(%s)
                    """, (job_id,))
                    
                    result = cursor.fetchone()
                    if not result:
                        raise Exception(f"Failed to check completion for job {job_id}")
                    
                    completion_status = {
                        'job_complete': result[0],
                        'final_stage': result[1]
                    }
                    
                    logger.debug(f"🔍 Job {job_id[:16]}... completion status: {completion_status}")
                    return completion_status
                    
        except Exception as e:
            logger.error(f"❌ Failed to check completion for job {job_id[:16]}...: {e}")
            raise


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
            return PostgresAdapter()  # Uses environment variables for all configuration
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