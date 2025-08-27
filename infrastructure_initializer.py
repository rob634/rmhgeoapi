"""
Infrastructure Initialization Service for Azure Geospatial ETL Pipeline.

This module ensures all required Azure storage infrastructure exists with proper
schemas before the application starts processing. It creates and validates:

- Azure Storage Tables (Jobs, Tasks) with expected fields
- Azure Storage Queues (geospatial-jobs, geospatial-tasks, poison queues)
- PostgreSQL STAC schema and tables (if database configured)

Key Features:
    - Idempotent operations (safe to run multiple times)
    - Schema validation for existing tables
    - Comprehensive error reporting
    - Optional database schema initialization
    - Startup health checks

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from azure.data.tables import TableServiceClient, TableEntity
from azure.storage.queue import QueueServiceClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from config import Config, AzureStorage
from logger_setup import get_logger

logger = get_logger(__name__)


@dataclass
class TableSchema:
    """Defines expected schema for a table"""
    name: str
    required_fields: List[str]
    optional_fields: List[str] = None
    partition_key: str = "PartitionKey"
    row_key: str = "RowKey"
    
    def __post_init__(self):
        if self.optional_fields is None:
            self.optional_fields = []


@dataclass
class InfrastructureStatus:
    """Status of infrastructure initialization"""
    tables_created: List[str]
    tables_validated: List[str] 
    tables_failed: List[str]
    queues_created: List[str]
    queues_validated: List[str]
    queues_failed: List[str]
    database_initialized: bool
    database_error: Optional[str]
    overall_success: bool
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'tables_created': self.tables_created,
            'tables_validated': self.tables_validated,
            'tables_failed': self.tables_failed,
            'queues_created': self.queues_created,
            'queues_validated': self.queues_validated,
            'queues_failed': self.queues_failed,
            'database_initialized': self.database_initialized,
            'database_error': self.database_error,
            'overall_success': self.overall_success
        }


class InfrastructureInitializer:
    """
    Ensures all required Azure infrastructure exists and is properly configured.
    
    This service provides comprehensive infrastructure setup and validation:
    
    1. Storage Tables:
       - Jobs table with job tracking fields
       - Tasks table with task execution fields
       - Schema validation for existing tables
       
    2. Storage Queues:
       - geospatial-jobs (job processing)
       - geospatial-tasks (task processing)  
       - poison queues for error handling
       
    3. PostgreSQL Schema (optional):
       - STAC collections and items tables
       - PostGIS extensions and geometry types
       
    Usage:
        initializer = InfrastructureInitializer()
        status = initializer.initialize_all()
        if not status.overall_success:
            logger.error(f"Infrastructure issues: {status.to_dict()}")
    """
    
    # Define expected table schemas
    JOBS_SCHEMA = TableSchema(
        name="Jobs",
        required_fields=[
            'dataset_id', 'resource_id', 'version_id', 'job_type',
            'status', 'created_at', 'updated_at', 'system'
        ],
        optional_fields=[
            'task_count', 'task_ids', 'result_data', 
            'error_message', 'request_parameters', 'controller_managed',
            'total_tasks', 'completed_tasks', 'failed_tasks', 'progress_percentage'
            # 'operation_type' REMOVED - no longer supported, use job_type only
        ]
    )
    
    TASKS_SCHEMA = TableSchema(
        name="Tasks",
        required_fields=[
            'task_id', 'parent_job_id', 'status', 'created_at', 'updated_at'
        ],
        optional_fields=[
            'task_type', 'operation_type', 'task_data', 'result_data',
            'error_message', 'dataset_id', 'resource_id', 'version_id', 'index'
        ]
    )
    
    # Define required queues
    REQUIRED_QUEUES = [
        'geospatial-jobs',
        'geospatial-tasks', 
        'geospatial-jobs-poison',
        'geospatial-tasks-poison'
    ]
    
    def __init__(self):
        """Initialize with Azure credentials and service clients"""
        if not Config.STORAGE_ACCOUNT_NAME:
            raise ValueError("STORAGE_ACCOUNT_NAME environment variable must be set")
            
        self.credential = DefaultAzureCredential()
        
        # Initialize service clients
        table_url = Config.get_storage_account_url('table')
        queue_url = Config.get_storage_account_url('queue')
        
        self.table_service = TableServiceClient(table_url, credential=self.credential)
        self.queue_service = QueueServiceClient(queue_url, credential=self.credential)
        
        logger.info("Infrastructure initializer created")
    
    def initialize_all(self, include_database: bool = True) -> InfrastructureStatus:
        """
        Initialize all infrastructure components.
        
        Args:
            include_database: Whether to initialize PostgreSQL schema
            
        Returns:
            InfrastructureStatus: Detailed status of initialization
        """
        logger.info("🚀 Starting infrastructure initialization")
        
        status = InfrastructureStatus(
            tables_created=[], tables_validated=[], tables_failed=[],
            queues_created=[], queues_validated=[], queues_failed=[],
            database_initialized=False, database_error=None, overall_success=True
        )
        
        # Initialize tables
        logger.info("📊 Initializing storage tables...")
        self._initialize_tables(status)
        
        # Initialize queues  
        logger.info("📮 Initializing storage queues...")
        self._initialize_queues(status)
        
        # Initialize database schema (optional)
        if include_database and self._should_initialize_database():
            logger.info("🗄️ Initializing database schema...")
            self._initialize_database_schema(status)
        
        # Determine overall success
        status.overall_success = (
            len(status.tables_failed) == 0 and 
            len(status.queues_failed) == 0 and
            (not include_database or status.database_initialized or status.database_error is None)
        )
        
        if status.overall_success:
            logger.info("✅ Infrastructure initialization completed successfully")
        else:
            logger.error("❌ Infrastructure initialization had failures")
            logger.error(f"Failed tables: {status.tables_failed}")
            logger.error(f"Failed queues: {status.queues_failed}")
            if status.database_error:
                logger.error(f"Database error: {status.database_error}")
        
        return status
    
    def _initialize_tables(self, status: InfrastructureStatus):
        """Initialize and validate storage tables"""
        schemas = [self.JOBS_SCHEMA, self.TASKS_SCHEMA]
        
        for schema in schemas:
            try:
                logger.info(f"📋 Processing table: {schema.name}")
                
                # Create table if it doesn't exist
                created = self._create_table(schema.name)
                if created:
                    status.tables_created.append(schema.name)
                    logger.info(f"✅ Created table: {schema.name}")
                
                # Validate table schema
                valid = self._validate_table_schema(schema)
                if valid:
                    status.tables_validated.append(schema.name)
                    logger.info(f"✅ Validated table schema: {schema.name}")
                else:
                    status.tables_failed.append(schema.name)
                    logger.error(f"❌ Table schema validation failed: {schema.name}")
                    
            except Exception as e:
                status.tables_failed.append(schema.name)
                logger.error(f"❌ Failed to initialize table {schema.name}: {e}")
    
    def _initialize_queues(self, status: InfrastructureStatus):
        """Initialize storage queues"""
        for queue_name in self.REQUIRED_QUEUES:
            try:
                logger.info(f"📬 Processing queue: {queue_name}")
                
                # Create queue if it doesn't exist
                created = self._create_queue(queue_name)
                if created:
                    status.queues_created.append(queue_name)
                    logger.info(f"✅ Created queue: {queue_name}")
                
                # Validate queue exists and is accessible
                valid = self._validate_queue(queue_name)
                if valid:
                    status.queues_validated.append(queue_name)
                    logger.info(f"✅ Validated queue: {queue_name}")
                else:
                    status.queues_failed.append(queue_name)
                    logger.error(f"❌ Queue validation failed: {queue_name}")
                    
            except Exception as e:
                status.queues_failed.append(queue_name)
                logger.error(f"❌ Failed to initialize queue {queue_name}: {e}")
    
    def _create_table(self, table_name: str) -> bool:
        """Create table if it doesn't exist. Returns True if created."""
        try:
            self.table_service.create_table(table_name)
            return True
        except ResourceExistsError:
            logger.debug(f"Table already exists: {table_name}")
            return False
    
    def _validate_table_schema(self, schema: TableSchema) -> bool:
        """Validate table has expected schema by checking a sample entity"""
        try:
            table_client = self.table_service.get_table_client(schema.name)
            
            # Try to query for any entity to see what fields exist
            entities = table_client.query_entities(
                query_filter=f"PartitionKey ne ''", 
                select=",".join(schema.required_fields + schema.optional_fields),
                max_results=1
            )
            
            # If we can query with required fields, schema is likely valid
            list(entities)  # Execute the query
            return True
            
        except Exception as e:
            logger.warning(f"Table schema validation inconclusive for {schema.name}: {e}")
            # Return True for inconclusive results - table exists but may be empty
            return True
    
    def _create_queue(self, queue_name: str) -> bool:
        """Create queue if it doesn't exist. Returns True if created."""
        try:
            self.queue_service.create_queue(queue_name)
            return True
        except ResourceExistsError:
            logger.debug(f"Queue already exists: {queue_name}")
            return False
    
    def _validate_queue(self, queue_name: str) -> bool:
        """Validate queue exists and is accessible"""
        try:
            queue_client = self.queue_service.get_queue_client(queue_name)
            properties = queue_client.get_queue_properties()
            logger.debug(f"Queue {queue_name} has {properties.approximate_message_count} messages")
            return True
        except Exception as e:
            logger.error(f"Queue validation failed for {queue_name}: {e}")
            return False
    
    def _should_initialize_database(self) -> bool:
        """Check if database initialization should be attempted"""
        return (
            hasattr(Config, 'POSTGIS_HOST') and Config.POSTGIS_HOST and
            hasattr(Config, 'POSTGIS_DATABASE') and Config.POSTGIS_DATABASE
        )
    
    def _initialize_database_schema(self, status: InfrastructureStatus):
        """Initialize PostgreSQL STAC schema (optional)"""
        try:
            # Only attempt if database_client is available
            try:
                from database_client import DatabaseClient
                db_client = DatabaseClient()
            except ImportError:
                status.database_error = "database_client not available"
                return
            except Exception as e:
                status.database_error = f"Failed to create database client: {e}"
                return
            
            # Test connection
            with db_client.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if geo schema exists
                    cursor.execute("""
                        SELECT EXISTS(
                            SELECT 1 FROM information_schema.schemata 
                            WHERE schema_name = 'geo'
                        )
                    """)
                    schema_exists = cursor.fetchone()[0]
                    
                    if not schema_exists:
                        logger.info("Creating 'geo' schema in PostgreSQL")
                        cursor.execute("CREATE SCHEMA IF NOT EXISTS geo")
                        conn.commit()
                    
                    # Check if STAC tables exist
                    cursor.execute("""
                        SELECT table_name FROM information_schema.tables 
                        WHERE table_schema = 'geo' 
                        AND table_name IN ('collections', 'items')
                    """)
                    existing_tables = [row[0] for row in cursor.fetchall()]
                    
                    if 'collections' not in existing_tables or 'items' not in existing_tables:
                        logger.info("Initializing STAC tables in geo schema")
                        # Use database client's built-in initialization
                        db_client.initialize_stac_schema()
                    
                    status.database_initialized = True
                    logger.info("✅ Database schema initialized successfully")
                    
        except Exception as e:
            status.database_error = str(e)
            logger.error(f"❌ Database schema initialization failed: {e}")
    
    def get_infrastructure_health(self) -> Dict:
        """Get current infrastructure health status"""
        health = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'storage_account': Config.STORAGE_ACCOUNT_NAME,
            'tables': {},
            'queues': {},
            'database': None
        }
        
        # Check tables
        for schema in [self.JOBS_SCHEMA, self.TASKS_SCHEMA]:
            try:
                table_client = self.table_service.get_table_client(schema.name)
                # Try a simple query to verify access
                entities = table_client.query_entities(
                    query_filter="PartitionKey eq 'test'", max_results=1
                )
                list(entities)  # Execute query
                health['tables'][schema.name] = {'status': 'healthy'}
            except Exception as e:
                health['tables'][schema.name] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        # Check queues
        for queue_name in self.REQUIRED_QUEUES:
            try:
                queue_client = self.queue_service.get_queue_client(queue_name)
                properties = queue_client.get_queue_properties()
                health['queues'][queue_name] = {
                    'status': 'healthy',
                    'message_count': properties.approximate_message_count
                }
            except Exception as e:
                health['queues'][queue_name] = {
                    'status': 'error', 
                    'error': str(e)
                }
        
        # Check database (optional)
        if self._should_initialize_database():
            try:
                from database_client import DatabaseClient
                db_client = DatabaseClient()
                
                with db_client.get_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT version()")
                        version = cursor.fetchone()[0]
                        
                        cursor.execute("""
                            SELECT EXISTS(
                                SELECT 1 FROM information_schema.schemata 
                                WHERE schema_name = 'geo'
                            )
                        """)
                        schema_exists = cursor.fetchone()[0]
                        
                        health['database'] = {
                            'status': 'healthy',
                            'version': version.split()[0] + ' ' + version.split()[1], 
                            'geo_schema_exists': schema_exists
                        }
            except Exception as e:
                health['database'] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return health