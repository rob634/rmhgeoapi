# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: PostgreSQL schema management service for database initialization
# SOURCE: Environment variables for PostgreSQL connection (POSTGIS_PASSWORD)
# SCOPE: Database-specific schema creation and validation for application tables
# VALIDATION: Schema creation validation + database permission verification
# ============================================================================

"""
PostgreSQL Schema Management Service

Handles schema validation, creation, and management for the application database.
Ensures APP_SCHEMA exists and has required tables before repository operations.

Critical Features:
- Schema existence validation with automatic creation
- Table validation and initialization
- Permission verification for schema operations  
- Environment-specific schema management (dev, staging, prod)
- Comprehensive error handling for database governance

Database Governance:
- Follows principle of least privilege
- Graceful degradation when permissions insufficient
- Clear error messages for admin intervention needed
- Idempotent operations (safe to run multiple times)
"""

import psycopg
from typing import Dict, Any, List, Optional, Tuple
from psycopg import sql

from util_logger import LoggerFactory, ComponentType
from config import get_config

logger = LoggerFactory.get_logger(ComponentType.SERVICE, "SchemaManager")


class SchemaManagementError(Exception):
    """Custom exception for schema management failures"""
    pass


class InsufficientPrivilegesError(SchemaManagementError):
    """Raised when user lacks privileges for schema operations"""
    pass


class SchemaManager:
    """
    PostgreSQL schema manager for application database governance.
    
    Responsibilities:
    1. Validate APP_SCHEMA exists
    2. Create schema if missing (with permission checks)
    3. Validate required tables exist
    4. Initialize schema with tables/functions if needed
    5. Provide clear error messages for admin intervention
    """
    
    def __init__(self):
        """Initialize schema manager with database configuration."""
        logger.debug("🔧 Initializing SchemaManager")
        
        self.config = get_config()
        self.app_schema = self.config.app_schema
        
        logger.debug(f"🔧 Schema configuration loaded:")
        logger.debug(f"   app_schema: {self.app_schema}")
        logger.debug(f"   postgis_host: {self.config.postgis_host}")
        logger.debug(f"   postgis_port: {self.config.postgis_port}")
        logger.debug(f"   postgis_database: {self.config.postgis_database}")
        logger.debug(f"   postgis_user: {self.config.postgis_user}")
        # logger.debug(f"   key_vault_name: {self.config.key_vault_name}")  # Key Vault disabled
        
        self.connection_string = self._build_connection_string()
        logger.info(f"🏗️ SchemaManager initialized for schema: {self.app_schema}")
        logger.debug(f"🔧 Connection string built (password masked)")
    
    def _build_connection_string(self) -> str:
        """Build secure connection string using environment variable by default."""
        logger.debug("🔐 Building database connection string")
        
        # Debug environment variables
        import os
        env_password = os.environ.get('POSTGIS_PASSWORD')
        logger.debug(f"🔍 POSTGIS_PASSWORD env var: {'SET' if env_password else 'NOT SET'}")
        logger.debug(f"🔍 config.postgis_password: {'SET' if self.config.postgis_password else 'NOT SET'}")
        
        # Use environment variable only (Key Vault causing DNS issues)
        password = self.config.postgis_password
        if not password:
            logger.error("❌ POSTGIS_PASSWORD environment variable not set")
            raise SchemaManagementError("POSTGIS_PASSWORD environment variable is required")
        
        logger.info("🔐 Using password from environment variable (POSTGIS_PASSWORD)")
        logger.debug("🔐 Environment password retrieval successful")
        
        # Build connection string (mask password in logs)
        logger.debug(f"🔍 Building connection with host: {self.config.postgis_host}")
        logger.debug(f"🔍 Building connection with port: {self.config.postgis_port}")
        logger.debug(f"🔍 Building connection with user: {self.config.postgis_user}")
        logger.debug(f"🔍 Building connection with database: {self.config.postgis_database}")
        
        connection_parts = {
            'host': self.config.postgis_host,
            'port': self.config.postgis_port,
            'database': self.config.postgis_database,
            'user': self.config.postgis_user
        }
        
        logger.debug(f"🔐 Connection parameters: {connection_parts}")
        
        # Build connection string in same format as health endpoint
        conn_str = (
            f"host={self.config.postgis_host} "
            f"dbname={self.config.postgis_database} "
            f"user={self.config.postgis_user} "
            f"password={password} "
            f"port={self.config.postgis_port}"
        )
        
        # Log masked connection string  
        masked_conn_str = conn_str.replace(password, "***MASKED***")
        logger.debug(f"🔗 Connection string: {masked_conn_str}")
        
        return conn_str
    
    def validate_and_initialize_schema(self) -> Dict[str, Any]:
        """
        Main entry point: Validate schema exists and initialize if needed.
        
        Returns:
            Dictionary with validation results and actions taken
            
        Raises:
            SchemaManagementError: If schema cannot be validated/created
            InsufficientPrivilegesError: If user lacks required permissions
        """
        logger.info(f"🔍 Starting schema validation for: {self.app_schema}")
        
        results = {
            'schema_name': self.app_schema,
            'schema_exists': False,
            'schema_created': False,
            'tables_exist': False,
            'tables_created': False,
            'functions_exist': False,
            'functions_created': False,
            'validation_successful': False,
            'actions_taken': [],
            'warnings': [],
            'errors': []
        }
        
        try:
            logger.debug(f"🔗 Attempting database connection to: {self.config.postgis_host}:{self.config.postgis_port}")
            with psycopg.connect(self.connection_string) as conn:
                logger.debug("🔗 Database connection established successfully")
                
                # Step 1: Check if schema exists
                logger.debug(f"🔍 Step 1: Checking if schema '{self.app_schema}' exists")
                schema_exists = self._check_schema_exists(conn)
                results['schema_exists'] = schema_exists
                logger.debug(f"🔍 Schema exists check result: {schema_exists}")
                
                if not schema_exists:
                    # Step 2: Attempt to create schema
                    logger.debug(f"🏗️ Step 2: Attempting to create schema '{self.app_schema}'")
                    created = self._create_schema(conn)
                    results['schema_created'] = created
                    logger.debug(f"🏗️ Schema creation result: {created}")
                    
                    if created:
                        results['actions_taken'].append(f'Created schema: {self.app_schema}')
                    else:
                        logger.error(f"❌ Failed to create schema '{self.app_schema}' - insufficient privileges")
                        raise InsufficientPrivilegesError(
                            f"Schema '{self.app_schema}' does not exist and cannot be created. "
                            "Admin intervention required."
                        )
                else:
                    logger.debug(f"✅ Schema '{self.app_schema}' already exists")
                
                # Step 3: Validate required tables exist
                logger.debug(f"🔍 Step 3: Validating tables in schema '{self.app_schema}'")
                tables_status = self._validate_tables(conn)
                results.update(tables_status)
                logger.debug(f"🔍 Tables validation result: {tables_status}")
                
                # Step 4: Validate required functions exist
                logger.debug(f"🔍 Step 4: Validating functions in schema '{self.app_schema}'")
                functions_status = self._validate_functions(conn)  
                results.update(functions_status)
                logger.debug(f"🔍 Functions validation result: {functions_status}")
                
                results['validation_successful'] = True
                logger.info(f"✅ Schema validation completed successfully for: {self.app_schema}")
                logger.debug(f"🔍 Final validation results: {results}")
                
        except psycopg.OperationalError as e:
            error_msg = f"Database connection failed: {e}"
            logger.error(f"❌ {error_msg}")
            results['errors'].append(error_msg)
            raise SchemaManagementError(error_msg)
            
        except InsufficientPrivilegesError:
            raise  # Re-raise as-is
            
        except Exception as e:
            error_msg = f"Unexpected schema validation error: {e}"
            logger.error(f"❌ {error_msg}")
            results['errors'].append(error_msg)
            raise SchemaManagementError(error_msg)
        
        return results
    
    def _check_schema_exists(self, conn: psycopg.Connection) -> bool:
        """Check if the application schema exists."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)",
                    (self.app_schema,)
                )
                exists = cur.fetchone()[0]
                logger.debug(f"🔍 Schema '{self.app_schema}' exists: {exists}")
                return exists
                
        except Exception as e:
            logger.error(f"❌ Failed to check schema existence: {e}")
            raise SchemaManagementError(f"Schema existence check failed: {e}")
    
    def _create_schema(self, conn: psycopg.Connection) -> bool:
        """
        Attempt to create the application schema.
        
        Returns:
            True if schema was created successfully, False if insufficient privileges
        """
        try:
            with conn.cursor() as cur:
                # Use sql.Identifier for safe schema name injection
                cur.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        sql.Identifier(self.app_schema)
                    )
                )
                conn.commit()
                logger.info(f"✅ Created schema: {self.app_schema}")
                return True
                
        except psycopg.errors.InsufficientPrivilege as e:
            logger.warning(f"⚠️ Insufficient privileges to create schema '{self.app_schema}': {e}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Failed to create schema '{self.app_schema}': {e}")
            raise SchemaManagementError(f"Schema creation failed: {e}")
    
    def _validate_tables(self, conn: psycopg.Connection) -> Dict[str, Any]:
        """Validate that required application tables exist."""
        required_tables = ['jobs', 'tasks']
        results = {
            'tables_exist': False,
            'tables_created': False,
            'missing_tables': [],
            'existing_tables': []
        }
        
        try:
            with conn.cursor() as cur:
                # Check which tables exist
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s AND table_name = ANY(%s)
                """, (self.app_schema, required_tables))
                
                existing_tables = [row[0] for row in cur.fetchall()]
                missing_tables = [t for t in required_tables if t not in existing_tables]
                
                results['existing_tables'] = existing_tables
                results['missing_tables'] = missing_tables
                results['tables_exist'] = len(missing_tables) == 0
                
                if missing_tables:
                    logger.warning(f"⚠️ Missing tables in schema '{self.app_schema}': {missing_tables}")
                    # Try to create missing tables with complete schema
                    created_tables = self._create_complete_tables(conn, missing_tables)
                    results['tables_created'] = created_tables
                    results['actions_taken'] = [f"Created missing tables: {created_tables}"]
                    if created_tables:
                        logger.info(f"✅ Created missing tables: {created_tables}")
                        results['tables_exist'] = True
                else:
                    logger.info(f"✅ All required tables exist in schema: {self.app_schema}")
                    # Verify existing tables have complete schema
                    schema_issues = self._validate_table_schema(conn, existing_tables)
                    if schema_issues:
                        logger.warning(f"⚠️ Existing tables have schema issues: {schema_issues}")
                        results['schema_issues'] = schema_issues
                
        except Exception as e:
            logger.error(f"❌ Failed to validate tables: {e}")
            raise SchemaManagementError(f"Table validation failed: {e}")
        
        return results
    
    def _validate_functions(self, conn: psycopg.Connection) -> Dict[str, Any]:
        """Validate that required PostgreSQL functions exist."""
        required_functions = ['complete_task_and_check_stage', 'advance_job_stage']
        results = {
            'functions_exist': False,
            'functions_created': False,
            'missing_functions': [],
            'existing_functions': []
        }
        
        try:
            with conn.cursor() as cur:
                # Check which functions exist
                cur.execute("""
                    SELECT routine_name
                    FROM information_schema.routines
                    WHERE routine_schema = %s AND routine_name = ANY(%s)
                """, (self.app_schema, required_functions))
                
                existing_functions = [row[0] for row in cur.fetchall()]
                missing_functions = [f for f in required_functions if f not in existing_functions]
                
                results['existing_functions'] = existing_functions
                results['missing_functions'] = missing_functions
                results['functions_exist'] = len(missing_functions) == 0
                
                if missing_functions:
                    logger.warning(f"⚠️ Missing functions in schema '{self.app_schema}': {missing_functions}")
                    results['actions_taken'] = [f"Schema '{self.app_schema}' missing functions: {missing_functions}"]
                else:
                    logger.info(f"✅ All required functions exist in schema: {self.app_schema}")
                
        except Exception as e:
            logger.error(f"❌ Failed to validate functions: {e}")
            raise SchemaManagementError(f"Function validation failed: {e}")
        
        return results
    
    def get_schema_info(self) -> Dict[str, Any]:
        """
        Get comprehensive schema information for debugging.
        
        Returns:
            Dictionary with schema configuration and status
        """
        try:
            validation_results = self.validate_and_initialize_schema()
            
            return {
                'configuration': {
                    'app_schema': self.app_schema,
                    'postgis_host': self.config.postgis_host,
                    'postgis_port': self.config.postgis_port,
                    'postgis_database': self.config.postgis_database,
                    'postgis_user': self.config.postgis_user,
                },
                'validation_results': validation_results,
                'connection_status': 'successful' if validation_results['validation_successful'] else 'failed'
            }
            
        except Exception as e:
            return {
                'configuration': {
                    'app_schema': self.app_schema,
                    'error': str(e)
                },
                'validation_results': None,
                'connection_status': 'failed'
            }
    
    def initialize_schema_tables(self) -> bool:
        """
        Initialize schema with tables and functions from schema_postgres.sql.
        
        This method should only be called by admin users or during deployment.
        
        Returns:
            True if initialization successful
            
        Raises:
            SchemaManagementError: If initialization fails
            InsufficientPrivilegesError: If user lacks required privileges
        """
        logger.info(f"🏗️ Initializing schema tables for: {self.app_schema}")
        
        try:
            with psycopg.connect(self.connection_string) as conn:
                with conn.cursor() as cur:
                    # Read the schema SQL file
                    try:
                        with open('schema_postgres.sql', 'r') as f:
                            schema_sql = f.read()
                    except FileNotFoundError:
                        raise SchemaManagementError("schema_postgres.sql file not found")
                    
                    # Replace 'geo' schema with app_schema in the SQL
                    schema_sql = schema_sql.replace('SET search_path TO geo, public;', 
                                                  f'SET search_path TO {self.app_schema}, public;')
                    
                    # Execute the schema creation SQL
                    cur.execute(schema_sql)
                    conn.commit()
                    
                    logger.info(f"✅ Successfully initialized schema: {self.app_schema}")
                    return True
                    
        except psycopg.errors.InsufficientPrivilege as e:
            error_msg = f"Insufficient privileges to initialize schema '{self.app_schema}': {e}"
            logger.error(f"❌ {error_msg}")
            raise InsufficientPrivilegesError(error_msg)
            
        except Exception as e:
            error_msg = f"Failed to initialize schema '{self.app_schema}': {e}"
            logger.error(f"❌ {error_msg}")
            raise SchemaManagementError(error_msg)
    
    def _create_complete_tables(self, conn: psycopg.Connection, missing_tables: List[str]) -> List[str]:
        """Create missing tables with complete schema matching schema_postgres.sql"""
        created_tables = []
        
        try:
            with conn.cursor() as cur:
                # First create ENUM types if they don't exist
                logger.info(f"🔧 Creating ENUM types in schema '{self.app_schema}'")
                cur.execute(f"SET search_path TO {self.app_schema}, public")
                
                # Create job_status enum
                cur.execute("""
                    DO $$ BEGIN
                        CREATE TYPE job_status AS ENUM (
                            'queued', 'processing', 'completed', 'failed', 'completed_with_errors'
                        );
                    EXCEPTION
                        WHEN duplicate_object THEN null;
                    END $$;
                """)
                
                # Create task_status enum  
                cur.execute("""
                    DO $$ BEGIN
                        CREATE TYPE task_status AS ENUM (
                            'queued', 'processing', 'completed', 'failed'
                        );
                    EXCEPTION
                        WHEN duplicate_object THEN null;
                    END $$;
                """)
                
                # Create jobs table with complete schema
                if 'jobs' in missing_tables:
                    logger.info(f"🔧 Creating jobs table with complete schema")
                    jobs_sql = f"""
                        CREATE TABLE {self.app_schema}.jobs (
                            job_id VARCHAR(64) PRIMARY KEY 
                                CHECK (length(job_id) = 64 AND job_id ~ '^[a-f0-9]+$'),
                            job_type VARCHAR(50) NOT NULL
                                CHECK (length(job_type) >= 1 AND job_type ~ '^[a-z_]+$'),
                            status job_status NOT NULL DEFAULT 'queued',
                            stage INTEGER NOT NULL DEFAULT 1
                                CHECK (stage >= 1 AND stage <= 100),
                            total_stages INTEGER NOT NULL DEFAULT 1  
                                CHECK (total_stages >= 1 AND total_stages <= 100),
                            parameters JSONB NOT NULL DEFAULT '{{}}',
                            stage_results JSONB NOT NULL DEFAULT '{{}}',  
                            result_data JSONB NULL,
                            error_details TEXT NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                            CONSTRAINT jobs_stage_consistency 
                                CHECK (stage <= total_stages),
                            CONSTRAINT jobs_completed_has_result
                                CHECK (
                                    (status = 'completed' AND result_data IS NOT NULL) OR 
                                    (status != 'completed')
                                ),
                            CONSTRAINT jobs_failed_has_error
                                CHECK (
                                    (status = 'failed' AND error_details IS NOT NULL) OR
                                    (status != 'failed')
                                )
                        )
                    """
                    cur.execute(jobs_sql)
                    created_tables.append('jobs')
                
                # Create tasks table with complete schema
                if 'tasks' in missing_tables:
                    logger.info(f"🔧 Creating tasks table with complete schema")
                    tasks_sql = f"""
                        CREATE TABLE {self.app_schema}.tasks (
                            task_id VARCHAR(100) PRIMARY KEY
                                CHECK (length(task_id) >= 1),
                            parent_job_id VARCHAR(64) NOT NULL 
                                REFERENCES {self.app_schema}.jobs(job_id) ON DELETE CASCADE
                                CHECK (length(parent_job_id) = 64 AND parent_job_id ~ '^[a-f0-9]+$'),
                            task_type VARCHAR(50) NOT NULL
                                CHECK (length(task_type) >= 1 AND task_type ~ '^[a-z_]+$'),
                            status task_status NOT NULL DEFAULT 'queued',
                            stage INTEGER NOT NULL 
                                CHECK (stage >= 1 AND stage <= 100),
                            task_index INTEGER NOT NULL 
                                CHECK (task_index >= 0 AND task_index <= 10000),
                            parameters JSONB NOT NULL DEFAULT '{{}}',
                            result_data JSONB NULL,
                            error_details TEXT NULL,
                            retry_count INTEGER NOT NULL DEFAULT 0
                                CHECK (retry_count >= 0 AND retry_count <= 10),
                            heartbeat TIMESTAMP NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                        )
                    """
                    cur.execute(tasks_sql)
                    created_tables.append('tasks')
                
                # Create indexes
                if created_tables:
                    logger.info(f"🔧 Creating indexes for tables: {created_tables}")
                    index_sql = f"""
                        CREATE INDEX IF NOT EXISTS idx_jobs_status ON {self.app_schema}.jobs(status);
                        CREATE INDEX IF NOT EXISTS idx_jobs_job_type ON {self.app_schema}.jobs(job_type);  
                        CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON {self.app_schema}.jobs(created_at);
                        CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON {self.app_schema}.jobs(updated_at);
                        CREATE INDEX IF NOT EXISTS idx_tasks_parent_job_id ON {self.app_schema}.tasks(parent_job_id);
                        CREATE INDEX IF NOT EXISTS idx_tasks_status ON {self.app_schema}.tasks(status);
                        CREATE INDEX IF NOT EXISTS idx_tasks_job_stage ON {self.app_schema}.tasks(parent_job_id, stage);  
                        CREATE INDEX IF NOT EXISTS idx_tasks_job_stage_status ON {self.app_schema}.tasks(parent_job_id, stage, status);
                        CREATE INDEX IF NOT EXISTS idx_tasks_heartbeat ON {self.app_schema}.tasks(heartbeat) WHERE heartbeat IS NOT NULL;
                        CREATE INDEX IF NOT EXISTS idx_tasks_retry_count ON {self.app_schema}.tasks(retry_count) WHERE retry_count > 0;
                    """
                    cur.execute(index_sql)
                
                conn.commit()
                logger.info(f"✅ Successfully created complete tables: {created_tables}")
                
        except Exception as e:
            logger.error(f"❌ Failed to create complete tables: {e}")
            conn.rollback()
            raise SchemaManagementError(f"Table creation failed: {e}")
        
        return created_tables
    
    def _validate_table_schema(self, conn: psycopg.Connection, existing_tables: List[str]) -> Dict[str, List[str]]:
        """Validate that existing tables have complete schema"""
        schema_issues = {}
        
        try:
            with conn.cursor() as cur:
                for table in existing_tables:
                    issues = []
                    
                    # Check if table has all required columns
                    cur.execute("""
                        SELECT column_name, data_type, is_nullable, column_default
                        FROM information_schema.columns 
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                    """, (self.app_schema, table))
                    
                    columns = {row[0]: {'type': row[1], 'nullable': row[2], 'default': row[3]} 
                             for row in cur.fetchall()}
                    
                    if table == 'jobs':
                        required_columns = [
                            'job_id', 'job_type', 'status', 'stage', 'total_stages',
                            'parameters', 'stage_results', 'result_data', 'error_details',
                            'created_at', 'updated_at'
                        ]
                        missing = [col for col in required_columns if col not in columns]
                        if missing:
                            issues.append(f"missing_columns: {missing}")
                    
                    elif table == 'tasks':
                        required_columns = [
                            'task_id', 'parent_job_id', 'task_type', 'status', 'stage',
                            'task_index', 'parameters', 'result_data', 'error_details',
                            'retry_count', 'heartbeat', 'created_at', 'updated_at'
                        ]
                        missing = [col for col in required_columns if col not in columns]
                        if missing:
                            issues.append(f"missing_columns: {missing}")
                    
                    if issues:
                        schema_issues[table] = issues
                        
        except Exception as e:
            logger.error(f"❌ Failed to validate table schema: {e}")
            
        return schema_issues


# Factory for creating SchemaManager instances
class SchemaManagerFactory:
    """Factory for creating SchemaManager instances."""
    
    @staticmethod
    def create_schema_manager() -> SchemaManager:
        """Create SchemaManager instance with current configuration."""
        return SchemaManager()


# Export public interfaces
__all__ = [
    'SchemaManager',
    'SchemaManagerFactory',
    'SchemaManagementError',
    'InsufficientPrivilegesError'
]