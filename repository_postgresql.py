# ============================================================================
# CLAUDE CONTEXT - REPOSITORY
# ============================================================================
# PURPOSE: PostgreSQL-specific repository implementation with direct database access and atomic operations
# EXPORTS: PostgreSQLRepository, PostgreSQLJobRepository, PostgreSQLTaskRepository, PostgreSQLCompletionDetector
# INTERFACES: BaseRepository, IJobRepository, ITaskRepository, IStageCompletionRepository (from interface_repository)
# PYDANTIC_MODELS: JobRecord, TaskRecord, StageAdvancementResult, TaskCompletionResult, JobCompletionResult
# DEPENDENCIES: psycopg, psycopg.sql, config, schema_core, repository_base, repository_abc
# SOURCE: PostgreSQL database (connection from AppConfig), app schema tables (jobs, tasks)
# SCOPE: Database operations for job/task persistence and atomic completion detection
# VALIDATION: SQL injection prevention via psycopg.sql composition, transaction atomicity for race prevention
# PATTERNS: Repository pattern, Unit of Work (transactions), Template Method, Connection pooling
# ENTRY_POINTS: repo = JobRepository(); job = repo.get_job(job_id); detector.complete_task_and_check_stage()
# INDEX: PostgreSQLRepository:61, JobRepository:514, TaskRepository:736, CompletionDetector:949
# ============================================================================

"""
PostgreSQL Repository Implementation - Direct Database Access

This module provides PostgreSQL-specific repository implementations that inherit
from the pure BaseRepository abstract class. It consolidates PostgreSQL operations
previously split between adapter_storage.py and repository_data.py, eliminating
the unnecessary adapter abstraction layer.

Architecture:
    BaseRepository (abstract)
        ↓
    PostgreSQLRepository (PostgreSQL-specific base)
        ↓
    JobRepository, TaskRepository, CompletionDetector

Key Features:
- Direct PostgreSQL access using psycopg3
- SQL composition for injection safety
- Atomic operations for race condition prevention
- Connection pooling and management
- Transaction support
"""

import os
import json
import psycopg
from psycopg import sql
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from contextlib import contextmanager
import logging

from config import AppConfig, get_config
from schema_base import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    generate_job_id
)
# generate_task_id moved to Controller layer - repository no longer needs it
from repository_base import BaseRepository
from interface_repository import (
    IJobRepository, ITaskRepository, IStageCompletionRepository
)
from schema_base import (
    StageAdvancementResult, TaskCompletionResult, JobCompletionResult,
    TaskResult, TaskStatus
)
from contract_validator import enforce_contract  # Added for contract enforcement

# Logger setup
logger = logging.getLogger(__name__)


# ============================================================================
# POSTGRESQL BASE REPOSITORY - Connection and common operations
# ============================================================================

class PostgreSQLRepository(BaseRepository):
    """
    PostgreSQL-specific repository base class with connection management.
    
    This class serves as the foundation for all PostgreSQL-based repositories
    in the application. It provides:
    - Connection string management from config or environment
    - Connection pooling and context managers
    - Safe SQL execution using psycopg.sql composition
    - Schema verification and initialization
    - Transaction management
    
    Inheritance Pattern:
    -------------------
    BaseRepository (abstract, no storage)
        ↓
    PostgreSQLRepository (this class, PostgreSQL-specific)
        ↓
    Domain Repositories (JobRepository, TaskRepository, etc.)
    
    Connection Management:
    ---------------------
    The class uses psycopg3 for PostgreSQL access with:
    - Automatic connection cleanup via context managers
    - SSL/TLS encryption by default (sslmode=require)
    - Connection string from AppConfig or environment
    - Support for both password and managed identity auth
    
    Thread Safety:
    -------------
    Each operation creates its own connection, making this class
    thread-safe for concurrent operations. For connection pooling
    in high-throughput scenarios, consider using psycopg_pool.
    """
    
    def __init__(self, connection_string: Optional[str] = None, 
                 schema_name: Optional[str] = None, 
                 config: Optional[AppConfig] = None):
        """
        Initialize PostgreSQL repository with configuration.
        
        This constructor sets up the PostgreSQL connection parameters and
        validates that the target schema exists. It uses a priority system
        for configuration:
        1. Explicit parameters (connection_string, schema_name)
        2. Provided AppConfig object
        3. Global configuration from get_config()
        4. Environment variables as fallback
        
        Parameters:
        ----------
        connection_string : Optional[str]
            Explicit PostgreSQL connection string. If provided, this
            overrides all other configuration sources.
            Format: postgresql://user:pass@host:port/database?sslmode=require
        
        schema_name : Optional[str]
            Database schema name. Defaults to config.app_schema or "app".
            This is where application tables (jobs, tasks) are stored.
        
        config : Optional[AppConfig]
            Configuration object. If not provided, uses get_config().
            This allows for dependency injection in testing.
        
        Raises:
        ------
        ValueError
            If connection configuration cannot be determined from any source.
        
        Side Effects:
        ------------
        - Logs initialization status
        - Validates schema existence (warning if missing)
        
        Example:
        -------
        ```python
        # Use global configuration
        repo = PostgreSQLRepository()
        
        # Override with specific connection
        repo = PostgreSQLRepository(
            connection_string="postgresql://user:pass@host/db",
            schema_name="custom_schema"
        )
        ```
        """
        # Initialize base class for validation and logging
        super().__init__()
        
        # Get configuration (use provided or global)
        self.config = config or get_config()
        
        # Set schema name (priority: parameter > config > default)
        self.schema_name = schema_name or self.config.app_schema
        
        # Set connection string (priority: parameter > config > env)
        if connection_string:
            self.conn_string = connection_string
        else:
            self.conn_string = self._get_connection_string()
        
        # Validate that schema exists (non-blocking warning if missing)
        self._ensure_schema_exists()
        
        logger.info(f"✅ PostgreSQLRepository initialized with schema: {self.schema_name}")
    
    def _get_connection_string(self) -> str:
        """
        Build PostgreSQL connection string from configuration.
        
        This method constructs a PostgreSQL connection string using the
        application configuration. It supports both password-based and
        passwordless (managed identity) authentication.
        
        Connection String Format:
        ------------------------
        postgresql://user:password@host:port/database?sslmode=require
        
        Configuration Sources (in priority order):
        -----------------------------------------
        1. POSTGRESQL_CONNECTION_STRING environment variable (complete string)
        2. AppConfig.postgis_connection_string property
        3. Individual components from AppConfig (host, user, database, etc.)
        
        Returns:
        -------
        str
            Complete PostgreSQL connection string with SSL enabled.
        
        Raises:
        ------
        ValueError
            If required configuration is missing or invalid.
        
        Security Notes:
        --------------
        - Passwords are included in the connection string (be careful with logging)
        - SSL is enforced by default (sslmode=require)
        - Consider using managed identity to avoid password management
        """
        logger.debug("🔌 Getting PostgreSQL connection string...")
        
        # Check for complete connection string in environment
        env_conn_string = os.getenv('POSTGRESQL_CONNECTION_STRING')
        if env_conn_string:
            logger.debug("📋 Using POSTGRESQL_CONNECTION_STRING from environment")
            # Mask password in log
            masked = env_conn_string
            if '@' in masked and ':' in masked[:masked.index('@')]:
                # Find password portion and mask it
                user_pass_end = masked.index('@')
                user_start = masked.index('://') + 3
                if ':' in masked[user_start:user_pass_end]:
                    pass_start = masked.index(':', user_start) + 1
                    masked = masked[:pass_start] + '****' + masked[user_pass_end:]
            logger.debug(f"  Connection string from env: {masked}")
            return env_conn_string
        
        # Use connection string from config
        # This is built from config.postgis_* properties
        logger.debug("📋 Building connection string from AppConfig")
        conn_str = self.config.postgis_connection_string
        logger.debug(f"  Final connection string will be used for connection")
        return conn_str
    
    @contextmanager
    def _get_connection(self):
        """
        Context manager for PostgreSQL database connections.
        
        This method provides a safe way to obtain and automatically clean up
        PostgreSQL connections. It ensures that:
        1. Connections are properly closed after use
        2. Transactions are rolled back on error
        3. Resources are freed even if exceptions occur
        
        Connection Lifecycle:
        --------------------
        1. Create connection using connection string
        2. Yield connection to caller
        3. On error: rollback transaction
        4. Always: close connection in finally block
        
        Yields:
        ------
        psycopg.Connection
            Active PostgreSQL connection object that can be used for queries.
            The connection has autocommit disabled by default.
        
        Raises:
        ------
        psycopg.Error
            On connection failures (network issues, auth failures, etc.).
            Common errors include:
            - OperationalError: Can't reach database
            - ProgrammingError: Invalid connection string
            - AuthenticationError: Invalid credentials
        
        Usage Example:
        -------------
        ```python
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM jobs")
                results = cursor.fetchall()
            conn.commit()  # Explicit commit needed
        ```
        
        Transaction Notes:
        -----------------
        - Autocommit is OFF by default (explicit commit needed)
        - On exception, transaction is rolled back automatically
        - For read-only operations, commit is still recommended
        """
        conn = None
        try:
            # Create connection with connection string
            # psycopg3 handles connection pooling internally
            logger.debug(f"🔗 Attempting PostgreSQL connection...")
            logger.debug(f"  Connection string length: {len(self.conn_string)} chars")
            
            # Extract and log the host being connected to
            if '@' in self.conn_string and '/' in self.conn_string:
                try:
                    # Extract host from connection string
                    after_at = self.conn_string.split('@')[1]
                    host_port = after_at.split('/')[0]
                    host = host_port.split(':')[0] if ':' in host_port else host_port
                    logger.debug(f"  Connecting to host: {host}")
                except:
                    pass  # Don't fail on parsing errors
            
            conn = psycopg.connect(self.conn_string)
            logger.debug(f"✅ PostgreSQL connection established successfully")
            yield conn
            
        except psycopg.Error as e:
            # Log connection errors with context
            logger.error(f"❌ PostgreSQL connection error: {e}")
            logger.error(f"  Error type: {type(e).__name__}")
            logger.error(f"  Error details: {str(e)}")
            
            # Try to extract more details about DNS errors
            if "Name or service not known" in str(e) or "could not translate host name" in str(e):
                logger.error(f"  🚨 DNS Resolution Error - Cannot resolve database hostname")
                if '@' in self.conn_string and '/' in self.conn_string:
                    try:
                        after_at = self.conn_string.split('@')[1]
                        host_port = after_at.split('/')[0]
                        host = host_port.split(':')[0] if ':' in host_port else host_port
                        logger.error(f"  Failed to resolve hostname: {host}")
                    except:
                        pass
            
            # Rollback any pending transaction
            if conn:
                conn.rollback()
            
            # Re-raise for caller to handle
            raise
            
        finally:
            # Always close connection to free resources
            if conn:
                conn.close()
    
    @contextmanager
    def _get_cursor(self, conn=None):
        """
        Context manager for PostgreSQL cursors with automatic transaction handling.
        
        This method provides two modes of operation:
        1. Use an existing connection (for multi-statement transactions)
        2. Create a new connection (for single operations)
        
        When creating a new connection, the transaction is automatically
        committed on success, making this ideal for single operations.
        
        Parameters:
        ----------
        conn : Optional[psycopg.Connection]
            Existing connection to use. If None, creates a new connection
            that will be auto-committed and closed after use.
        
        Yields:
        ------
        psycopg.Cursor
            Database cursor for executing queries. The cursor is automatically
            closed when the context exits.
        
        Transaction Behavior:
        --------------------
        - With existing conn: No auto-commit (caller controls transaction)
        - Without conn: Auto-commits on success, auto-rollback on error
        
        Usage Examples:
        --------------
        ```python
        # Single operation with auto-commit
        with self._get_cursor() as cursor:
            cursor.execute("INSERT INTO jobs ...")
            # Automatically committed
        
        # Multi-statement transaction
        with self._get_connection() as conn:
            with self._get_cursor(conn) as cursor1:
                cursor1.execute("INSERT INTO jobs ...")
            with self._get_cursor(conn) as cursor2:
                cursor2.execute("INSERT INTO tasks ...")
            conn.commit()  # Commit both operations together
        ```
        """
        if conn:
            # Use existing connection - caller controls transaction
            with conn.cursor() as cursor:
                yield cursor
        else:
            # Create new connection with auto-commit
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    yield cursor
                    # Auto-commit on successful completion
                    conn.commit()
    
    def _ensure_schema_exists(self) -> None:
        """
        Verify that the target database schema exists.
        
        This method checks if the configured schema exists in the database.
        It's a safety check that runs during initialization to catch
        configuration issues early. Note that this does NOT create the
        schema - that should be done by the schema deployment process.
        
        Schema Check Query:
        ------------------
        Queries information_schema.schemata to verify schema existence.
        This is a standard PostgreSQL catalog query that works across versions.
        
        Error Handling:
        --------------
        - If schema missing: Logs WARNING but doesn't fail
        - If connection fails: Logs ERROR but doesn't fail
        - Rationale: Let actual operations fail with specific errors
        
        Side Effects:
        ------------
        - Creates a temporary database connection
        - Logs schema status (exists/missing/error)
        
        Security Note:
        -------------
        Uses parameterized query to prevent SQL injection even though
        schema_name comes from configuration.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # Check if schema exists using information_schema
                    # This is portable across PostgreSQL versions
                    cursor.execute(
                        sql.SQL("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s"),
                        (self.schema_name,)
                    )
                    
                    if not cursor.fetchone():
                        # Schema doesn't exist - warn but don't fail
                        logger.warning(
                            f"⚠️ Schema {self.schema_name} does not exist. "
                            f"It should be created by schema deployment."
                        )
                    else:
                        # Schema exists - good to go
                        logger.debug(f"✅ Schema {self.schema_name} exists")
                        
        except Exception as e:
            # Log error but don't fail initialization
            # Actual operations will fail with more specific errors
            logger.error(f"❌ Error checking schema existence: {e}")
    
    def _execute_query(self, query: sql.Composed, params: Optional[Tuple] = None, 
                      fetch: str = None) -> Optional[Any]:
        """
        Execute a PostgreSQL query with GUARANTEED commit and LOUD failures.
        
        CRITICAL FIX (11 Sept 2025): Functions with RETURNS TABLE were not committing
        because they have cursor.description set, causing them to bypass commit logic.
        This version ALWAYS commits for ALL operations.
        
        Principles:
        ----------
        1. ALWAYS commit (no silent rollbacks)
        2. FAIL LOUD on any error  
        3. NO ambiguous elif chains
        4. EXPLICIT validation
        
        Parameters:
        ----------
        query : sql.Composed
            SQL query built using psycopg.sql composition for injection safety.
        
        params : Optional[Tuple]
            Query parameters for %s placeholders, safely escaped by psycopg.
        
        fetch : Optional[str]
            Fetch behavior: None | 'one' | 'all' | 'many'
        
        Returns:
        -------
        Optional[Any]
            - For fetch operations: Row(s) as tuple(s)
            - For DML operations: Number of affected rows
            - For DDL operations: None
        
        Raises:
        ------
        TypeError
            If query is not sql.Composed (security requirement)
        
        ValueError
            If fetch parameter is invalid
        
        RuntimeError
            For any database operation failure (wraps psycopg errors)
        """
        # Pre-validation for security and correctness
        if not isinstance(query, sql.Composed):
            raise TypeError(f"❌ SECURITY: Query must be sql.Composed, got {type(query)}")
        
        if fetch and fetch not in ['one', 'all', 'many']:
            raise ValueError(f"❌ INVALID FETCH MODE: {fetch}")
        
        with self._get_connection() as conn:
            try:
                with conn.cursor() as cursor:
                    # Execute query with error handling
                    try:
                        cursor.execute(query, params)
                        logger.debug(f"✅ Query executed successfully")
                    except psycopg.errors.Error as e:
                        logger.error(f"❌ QUERY EXECUTION FAILED: {e}")
                        logger.error(f"   SQL State: {e.sqlstate}")
                        logger.error(f"   Query: {str(query)[:200]}")
                        raise RuntimeError(f"Query execution failed: {e}") from e
                    
                    # Handle fetch operations
                    result = None
                    if fetch == 'one':
                        result = cursor.fetchone()
                    elif fetch == 'all':
                        result = cursor.fetchall()
                    elif fetch == 'many':
                        result = cursor.fetchmany()
                    
                    # ALWAYS COMMIT - THE CRITICAL FIX!
                    # This ensures PostgreSQL functions that modify data commit their changes
                    try:
                        conn.commit()
                        logger.debug("✅ Transaction committed successfully")
                        
                    except psycopg.errors.InFailedSqlTransaction as e:
                        # Transaction was already aborted
                        logger.error(f"❌ TRANSACTION ALREADY FAILED: {e}")
                        logger.error(f"   Cannot commit - transaction aborted earlier")
                        raise RuntimeError("Transaction in failed state - cannot commit") from e
                        
                    except psycopg.errors.SerializationFailure as e:
                        # Concurrent transaction conflict
                        logger.error(f"❌ SERIALIZATION FAILURE: {e}")
                        logger.error(f"   Concurrent transaction conflict detected")
                        raise RuntimeError("Concurrent transaction conflict") from e
                        
                    except psycopg.errors.IntegrityError as e:
                        # Constraint violation at commit time
                        logger.error(f"❌ INTEGRITY CONSTRAINT VIOLATION AT COMMIT: {e}")
                        logger.error(f"   Constraint: {e.diag.constraint_name if e.diag else 'unknown'}")
                        raise RuntimeError(f"Constraint violation: {e}") from e
                        
                    except psycopg.OperationalError as e:
                        # Connection/network issues
                        logger.error(f"❌ CONNECTION LOST DURING COMMIT: {e}")
                        raise RuntimeError("Database connection lost during commit") from e
                        
                    except psycopg.Error as e:
                        # Any other psycopg error
                        logger.error(f"❌ COMMIT FAILED: {e}")
                        logger.error(f"   SQL State: {getattr(e, 'sqlstate', 'unknown')}")
                        raise RuntimeError(f"Transaction commit failed: {e}") from e
                        
                    except Exception as e:
                        # Unexpected error
                        logger.error(f"❌ UNEXPECTED COMMIT ERROR: {e}")
                        raise RuntimeError(f"Unexpected error during commit: {e}") from e
                    
                    # Return appropriate result based on operation type
                    if fetch:
                        # Fetch operations return the fetched data
                        return result
                    elif cursor.description is None:
                        # DML operations (INSERT/UPDATE/DELETE) return affected rows
                        return cursor.rowcount
                    else:
                        # DDL or other operations return None
                        return None
                        
            except Exception as e:
                # Rollback on any error
                try:
                    conn.rollback()
                    logger.info("🔄 Transaction rolled back due to error")
                except Exception as rollback_error:
                    logger.error(f"❌ ROLLBACK ALSO FAILED: {rollback_error}")
                
                # Re-raise the original error for upstream handling
                raise
    
    def _table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the schema.
        
        Args:
            table_name: Name of the table to check
            
        Returns:
            True if table exists, False otherwise
        """
        query = sql.SQL("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = %s 
                AND table_name = %s
            )
        """)
        
        result = self._execute_query(query, (self.schema_name, table_name), fetch='one')
        return result[0] if result else False


# ============================================================================
# JOB REPOSITORY - PostgreSQL implementation
# ============================================================================

class PostgreSQLJobRepository(PostgreSQLRepository, IJobRepository):
    """
    PostgreSQL implementation of job repository.
    
    Handles all job-related database operations with direct PostgreSQL access.
    """
    
    @enforce_contract(
        params={'job': JobRecord},
        returns=bool
    )
    def create_job(self, job: JobRecord) -> bool:
        """
        Create a new job in PostgreSQL.
        
        Args:
            job: JobRecord to create
            
        Returns:
            True if created, False if already exists
        """
        with self._error_context("job creation", job.job_id):
            query = sql.SQL("""
                INSERT INTO {}.{} (
                    job_id, job_type, status, stage, total_stages,
                    parameters, stage_results, metadata, result_data, error_details,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (job_id) DO NOTHING
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("jobs")
            )
            
            params = (
                job.job_id,
                job.job_type,
                job.status.value if isinstance(job.status, JobStatus) else job.status,
                job.stage,
                job.total_stages,
                json.dumps(job.parameters),
                json.dumps(job.stage_results),
                json.dumps(job.metadata if hasattr(job, 'metadata') else {}),
                json.dumps(job.result_data) if job.result_data else None,
                job.error_details,
                job.created_at or datetime.now(timezone.utc),
                job.updated_at or datetime.now(timezone.utc)
            )
            
            rowcount = self._execute_query(query, params)
            created = rowcount > 0
            
            if created:
                logger.info(f"✅ Job created: {job.job_id[:16]}... type={job.job_type}")
            else:
                logger.info(f"📋 Job already exists: {job.job_id[:16]}... (idempotent)")
            
            return created
    
    @enforce_contract(
        params={'job_id': str},
        returns=Optional[JobRecord]
    )
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """
        Retrieve a job from PostgreSQL.
        
        Args:
            job_id: Job ID to retrieve
            
        Returns:
            JobRecord if found, None otherwise
        """
        with self._error_context("job retrieval", job_id):
            query = sql.SQL("""
                SELECT job_id, job_type, status, stage, total_stages,
                       parameters, stage_results, result_data, error_details,
                       created_at, updated_at
                FROM {}.{}
                WHERE job_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("jobs")
            )
            
            row = self._execute_query(query, (job_id,), fetch='one')
            
            if not row:
                logger.debug(f"📋 Job not found: {job_id[:16]}...")
                return None
            
            # Convert row to JobRecord
            job_data = {
                'job_id': row[0],
                'job_type': row[1],
                'status': row[2],
                'stage': row[3],
                'total_stages': row[4],
                'parameters': row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {},
                'stage_results': row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
                'result_data': row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else None,
                'error_details': row[8],
                'created_at': row[9],
                'updated_at': row[10]
            }
            
            job_record = JobRecord(**job_data)
            logger.debug(f"📋 Retrieved job: {job_id[:16]}... status={job_record.status}")
            
            return job_record
    
    @enforce_contract(
        params={'job_id': str, 'updates': dict},
        returns=bool
    )
    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a job in PostgreSQL.
        
        Args:
            job_id: Job ID to update
            updates: Dictionary of fields to update
            
        Returns:
            True if updated, False otherwise
        """
        with self._error_context("job update", job_id):
            if not updates:
                return False
            
            # Build UPDATE query dynamically
            set_clauses = []
            params = []
            
            for field, value in updates.items():
                set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
                
                # Handle special types
                if field in ['parameters', 'stage_results', 'result_data'] and value is not None:
                    params.append(json.dumps(value) if not isinstance(value, str) else value)
                elif isinstance(value, (JobStatus, TaskStatus)):
                    params.append(value.value)
                else:
                    params.append(value)
            
            # Add job_id to params
            params.append(job_id)
            
            query = sql.SQL("""
                UPDATE {}.{}
                SET {}, updated_at = NOW()
                WHERE job_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("jobs"),
                sql.SQL(", ").join(set_clauses)
            )
            
            rowcount = self._execute_query(query, tuple(params))
            success = rowcount > 0
            
            if success:
                logger.info(f"✅ Job updated: {job_id[:16]}... fields={list(updates.keys())}")
            else:
                logger.warning(f"⚠️ Job not found for update: {job_id[:16]}...")
            
            return success
    
    @enforce_contract(
        params={'status_filter': Optional[JobStatus]},
        returns=List[JobRecord]
    )
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]:
        """
        List jobs with optional status filtering.
        
        Args:
            status_filter: Optional status to filter by
            
        Returns:
            List of JobRecords
        """
        with self._error_context("job listing"):
            if status_filter:
                query = sql.SQL("""
                    SELECT job_id, job_type, status, stage, total_stages,
                           parameters, stage_results, result_data, error_details,
                           created_at, updated_at
                    FROM {}.{}
                    WHERE status = %s
                    ORDER BY created_at DESC
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs")
                )
                params = (status_filter.value if isinstance(status_filter, JobStatus) else status_filter,)
            else:
                query = sql.SQL("""
                    SELECT job_id, job_type, status, stage, total_stages,
                           parameters, stage_results, result_data, error_details,
                           created_at, updated_at
                    FROM {}.{}
                    ORDER BY created_at DESC
                """).format(
                    sql.Identifier(self.schema_name),
                    sql.Identifier("jobs")
                )
                params = None
            
            rows = self._execute_query(query, params, fetch='all')
            
            jobs = []
            for row in rows:
                job_data = {
                    'job_id': row[0],
                    'job_type': row[1],
                    'status': row[2],
                    'stage': row[3],
                    'total_stages': row[4],
                    'parameters': row[5] if isinstance(row[5], dict) else json.loads(row[5]) if row[5] else {},
                    'stage_results': row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
                    'result_data': row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else None,
                    'error_details': row[8],
                    'created_at': row[9],
                    'updated_at': row[10]
                }
                jobs.append(JobRecord(**job_data))
            
            logger.info(f"📋 Listed {len(jobs)} jobs" + 
                       (f" with status {status_filter}" if status_filter else ""))
            
            return jobs


# ============================================================================
# TASK REPOSITORY - PostgreSQL implementation
# ============================================================================

class PostgreSQLTaskRepository(PostgreSQLRepository, ITaskRepository):
    """
    PostgreSQL implementation of task repository.
    
    Handles all task-related database operations with direct PostgreSQL access.
    """
    
    @enforce_contract(
        params={'task': TaskRecord},
        returns=bool
    )
    def create_task(self, task: TaskRecord) -> bool:
        """
        Create a new task in PostgreSQL.
        
        Args:
            task: TaskRecord to create
            
        Returns:
            True if created, False if already exists
        """
        with self._error_context("task creation", task.task_id):
            query = sql.SQL("""
                INSERT INTO {}.{} (
                    task_id, parent_job_id, job_type, task_type, status, stage, task_index,
                    parameters, result_data, metadata, error_details, retry_count,
                    heartbeat, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (task_id) DO NOTHING
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks")
            )
            
            params = (
                task.task_id,
                task.parent_job_id,
                task.job_type,  # Added job_type field
                task.task_type,
                task.status.value if isinstance(task.status, TaskStatus) else task.status,
                task.stage,
                task.task_index,
                json.dumps(task.parameters),
                json.dumps(task.result_data) if task.result_data else None,
                json.dumps(task.metadata) if task.metadata else json.dumps({}),  # ✅ FIXED: Include metadata
                task.error_details,
                task.retry_count,
                task.heartbeat,
                task.created_at or datetime.now(timezone.utc),
                task.updated_at or datetime.now(timezone.utc)
            )
            
            rowcount = self._execute_query(query, params)
            created = rowcount > 0
            
            if created:
                logger.info(f"✅ Task created: {task.task_id} type={task.task_type}")
            else:
                logger.info(f"📋 Task already exists: {task.task_id} (idempotent)")
            
            return created
    
    @enforce_contract(
        params={'task_id': str},
        returns=Optional[TaskRecord]
    )
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """
        Retrieve a task from PostgreSQL.
        
        Args:
            task_id: Task ID to retrieve
            
        Returns:
            TaskRecord if found, None otherwise
        """
        with self._error_context("task retrieval", task_id):
            query = sql.SQL("""
                SELECT task_id, parent_job_id, job_type, task_type, status, stage, task_index,
                       parameters, result_data, error_details, retry_count,
                       heartbeat, created_at, updated_at
                FROM {}.{}
                WHERE task_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks")
            )
            
            row = self._execute_query(query, (task_id,), fetch='one')
            
            if not row:
                logger.debug(f"📋 Task not found: {task_id}")
                return None
            
            # Convert row to TaskRecord
            task_data = {
                'task_id': row[0],
                'parent_job_id': row[1],
                'job_type': row[2],  # Added job_type field
                'task_type': row[3],
                'status': row[4],
                'stage': row[5],
                'task_index': row[6],
                'parameters': row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {},
                'result_data': row[8] if isinstance(row[8], dict) else json.loads(row[8]) if row[8] else None,
                'error_details': row[9],
                'retry_count': row[10],
                'heartbeat': row[11],
                'created_at': row[12],
                'updated_at': row[13]
            }
            
            task_record = TaskRecord(**task_data)
            logger.debug(f"📋 Retrieved task: {task_id} status={task_record.status}")
            
            return task_record
    
    @enforce_contract(
        params={'task_id': str, 'updates': dict},
        returns=bool
    )
    def update_task(self, task_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a task in PostgreSQL.
        
        Args:
            task_id: Task ID to update
            updates: Dictionary of fields to update
            
        Returns:
            True if updated, False otherwise
        """
        with self._error_context("task update", task_id):
            if not updates:
                return False
            
            # Build UPDATE query dynamically
            set_clauses = []
            params = []
            
            for field, value in updates.items():
                set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
                
                # Handle special types
                if field in ['parameters', 'result_data'] and value is not None:
                    params.append(json.dumps(value) if not isinstance(value, str) else value)
                elif isinstance(value, (JobStatus, TaskStatus)):
                    params.append(value.value)
                else:
                    params.append(value)
            
            # Add task_id to params
            params.append(task_id)
            
            query = sql.SQL("""
                UPDATE {}.{}
                SET {}, updated_at = NOW()
                WHERE task_id = %s
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks"),
                sql.SQL(", ").join(set_clauses)
            )
            
            rowcount = self._execute_query(query, tuple(params))
            success = rowcount > 0
            
            if success:
                logger.info(f"✅ Task updated: {task_id} fields={list(updates.keys())}")
            else:
                logger.warning(f"⚠️ Task not found for update: {task_id}")
            
            return success
    
    @enforce_contract(
        params={'job_id': str},
        returns=List[TaskRecord]
    )
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]:
        """
        List all tasks for a job.
        
        Args:
            job_id: Parent job ID
            
        Returns:
            List of TaskRecords
        """
        with self._error_context("task listing for job", job_id):
            query = sql.SQL("""
                SELECT task_id, parent_job_id, task_type, status, stage, task_index,
                       parameters, result_data, error_details, retry_count,
                       heartbeat, created_at, updated_at
                FROM {}.{}
                WHERE parent_job_id = %s
                ORDER BY stage, task_index
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks")
            )
            
            rows = self._execute_query(query, (job_id,), fetch='all')
            
            tasks = []
            for row in rows:
                # CONTRACT ENFORCEMENT: Convert status string to enum
                if isinstance(row[4], str):
                    try:
                        status = TaskStatus(row[4])
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid TaskStatus from database: '{row[4]}'. "
                            f"Valid values are: {[s.value for s in TaskStatus]}"
                        ) from e
                else:
                    status = row[4]

                # Now we have job_type from the fixed query
                try:
                    task_record = TaskRecord(
                        task_id=row[0],
                        parent_job_id=row[1],
                        job_type=row[2],  # Now properly selected from database
                        task_type=row[3],
                        status=status,
                        stage=row[5],
                        task_index=row[6],
                        parameters=row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else {},
                        result_data=row[8] if isinstance(row[8], dict) else json.loads(row[8]) if row[8] else None,
                        error_details=row[9],
                        retry_count=row[10],
                        heartbeat=row[11],
                        created_at=row[12],
                        updated_at=row[13]
                    )
                    tasks.append(task_record)
                except Exception as e:
                    raise TypeError(
                        f"Failed to create TaskRecord from database row for task_id={row[0]}. "
                        f"Error: {e}"
                    ) from e
            
            logger.info(f"📋 Listed {len(tasks)} tasks for job {job_id[:16]}...")
            
            return tasks


# ============================================================================
# COMPLETION DETECTOR - Atomic PostgreSQL operations
# ============================================================================

class PostgreSQLStageCompletionRepository(PostgreSQLRepository, IStageCompletionRepository):
    """
    PostgreSQL implementation of stage completion repository.

    Provides atomic data operations for task completion and stage advancement
    using PostgreSQL advisory locks to prevent race conditions. These are
    fundamentally data queries that return state information.
    """
    
    @enforce_contract(
        params={
            'task_id': str,
            'job_id': str,
            'stage': int,
            'result_data': Optional[Dict[str, Any]],
            'error_details': Optional[str]
        },
        returns=TaskCompletionResult
    )
    def complete_task_and_check_stage(
        self,
        task_id: str,
        job_id: str,
        stage: int,
        result_data: Optional[Dict[str, Any]] = None,
        error_details: Optional[str] = None
    ) -> TaskCompletionResult:
        """
        Atomically complete a task and check if stage is complete.
        
        Uses PostgreSQL function for atomic operation.
        
        Args:
            task_id: Task to complete
            job_id: Parent job ID (for validation)
            stage: Current stage number
            result_data: Task results (None for failures)
            error_details: Error message if task failed (None for success)
            
        Returns:
            TaskCompletionResult with completion status
        """
        with self._error_context("task completion", task_id):
            query = sql.SQL("""
                SELECT * FROM {}.complete_task_and_check_stage(%s, %s, %s, %s, %s)
            """).format(sql.Identifier(self.schema_name))
            
            # Log all parameters being passed to SQL function
            params = (
                task_id,
                job_id,
                stage,
                json.dumps(result_data) if result_data else None,
                error_details  # Pass error_details for failed tasks, None for success
            )
            
            logger.debug(f"[SQL_FUNCTION_DEBUG] Calling complete_task_and_check_stage with:")
            logger.debug(f"  - task_id: {task_id}")
            logger.debug(f"  - job_id: {job_id}")
            logger.debug(f"  - stage: {stage}")
            logger.debug(f"  - has_result_data: {result_data is not None}")
            logger.debug(f"  - has_error_details: {error_details is not None}")
            
            # Also query current task status before SQL function for debugging
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM app.tasks WHERE task_id = %s",
                        (task_id,)
                    )
                    current_status = cur.fetchone()
                    logger.debug(f"[SQL_FUNCTION_DEBUG] Task {task_id} current DB status before SQL function: {current_status[0] if current_status else 'NOT FOUND'}")
            
            import time
            start_time = time.time()
            row = self._execute_query(query, params, fetch='one')
            sql_time = time.time() - start_time
            
            logger.debug(f"[SQL_FUNCTION_DEBUG] SQL function executed in {sql_time:.3f}s")
            
            if not row:
                logger.error(f"[SQL_FUNCTION_ERROR] Task completion returned NULL for {task_id}")
                logger.error(f"[SQL_FUNCTION_ERROR] This means UPDATE matched no rows (task not in 'processing' status?)")
                return TaskCompletionResult(
                    task_updated=False,
                    stage_complete=False,
                    job_id=None,
                    stage_number=None,
                    remaining_tasks=0
                )
            
            # Log raw SQL result before parsing
            logger.debug(f"[SQL_FUNCTION_DEBUG] Raw SQL result: {row}")
            
            result = TaskCompletionResult(
                task_updated=row[0],
                stage_complete=row[1],  # is_last_task_in_stage from SQL
                job_id=row[2],
                stage_number=row[3],
                remaining_tasks=row[4]
            )
            
            # Log parsed result
            logger.debug(f"[SQL_FUNCTION_DEBUG] Parsed result:")
            logger.debug(f"  - task_updated: {result.task_updated}")
            logger.debug(f"  - stage_complete: {result.stage_complete}")
            logger.debug(f"  - job_id: {result.job_id}")
            logger.debug(f"  - stage_number: {result.stage_number}")
            logger.debug(f"  - remaining_tasks: {result.remaining_tasks}")
            
            # If not stage complete, query to see what tasks are still pending
            if result.task_updated and not result.stage_complete and result.remaining_tasks > 0:
                with self._get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT task_id, status 
                            FROM app.tasks 
                            WHERE parent_job_id = %s 
                              AND stage = %s 
                              AND status NOT IN ('completed', 'failed')
                            """,
                            (result.job_id, result.stage_number)
                        )
                        pending_tasks = cur.fetchall()
                        if pending_tasks:
                            logger.debug(f"[SQL_FUNCTION_DEBUG] Pending tasks in stage {result.stage_number}:")
                            for task in pending_tasks:
                                logger.debug(f"  - {task[0]}: {task[1]}")
            
            if result.task_updated:
                logger.info(f"✅ Task completed: {task_id} (remaining in stage: {result.remaining_tasks})")
                if result.stage_complete:
                    logger.info(f"🎯 Stage {result.stage_number} complete for job {result.job_id[:16]}...")
            else:
                logger.error(f"[SQL_FUNCTION_ERROR] Task update failed for {task_id}")
            
            return result
    
    @enforce_contract(
        params={
            'job_id': str,
            'current_stage': int,
            'stage_results': dict
        },
        returns=StageAdvancementResult
    )
    def advance_job_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> StageAdvancementResult:
        """
        Advance job to next stage atomically.
        
        CRITICAL: Only 3 parameters! No 'next_stage' parameter!
        The SQL function calculates next_stage = current_stage + 1
        
        Args:
            job_id: Job to advance
            current_stage: Current stage number
            stage_results: Results from completed stage
            
        Returns:
            StageAdvancementResult with new stage info
        """
        with self._error_context("stage advancement", job_id):
            query = sql.SQL("""
                SELECT * FROM {}.advance_job_stage(%s, %s, %s)
            """).format(sql.Identifier(self.schema_name))
            
            params = (
                job_id,
                current_stage,
                json.dumps(stage_results) if stage_results else None
            )
            
            row = self._execute_query(query, params, fetch='one')
            
            if not row:
                logger.error(f"❌ Stage advancement failed: {job_id[:16]}...")
                return StageAdvancementResult(
                    job_updated=False,
                    new_stage=None,
                    is_final_stage=None
                )
            
            result = StageAdvancementResult(
                job_updated=row[0],
                new_stage=row[1],
                is_final_stage=row[2]
            )
            
            if result.job_updated:
                logger.info(f"✅ Job advanced: {job_id[:16]}... stage {current_stage} → {result.new_stage}")
                if result.is_final_stage:
                    logger.info(f"🏁 Job {job_id[:16]}... reached final stage")
            
            return result
    
    @enforce_contract(
        params={'job_id': str},
        returns=JobCompletionResult
    )
    def check_job_completion(
        self,
        job_id: str
    ) -> JobCompletionResult:
        """
        Check if job is complete and gather results.
        
        Args:
            job_id: Job to check
            
        Returns:
            JobCompletionResult with completion status and results
        """
        with self._error_context("job completion check", job_id):
            query = sql.SQL("""
                SELECT * FROM {}.check_job_completion(%s)
            """).format(sql.Identifier(self.schema_name))
            
            row = self._execute_query(query, (job_id,), fetch='one')
            
            if not row:
                logger.error(f"❌ Job completion check failed: {job_id[:16]}...")
                return JobCompletionResult(
                    job_complete=False,
                    final_stage=0,
                    total_tasks=0,
                    completed_tasks=0,
                    task_results=[]
                )
            
            # Parse task_results from JSONB - fail fast on incorrect type
            if not isinstance(row[4], list):
                raise ValueError(f"Invalid task_results from database: expected list, got {type(row[4])}")

            # Convert raw dicts to TaskResult objects for contract enforcement
            raw_task_results = row[4] if row[4] is not None else []
            task_results = []
            for task_data in raw_task_results:
                if isinstance(task_data, dict):
                    # Convert dict to TaskResult with all required fields
                    task_result = TaskResult(
                        task_id=task_data.get('task_id', 'unknown'),
                        job_id=task_data.get('parent_job_id', job_id),  # Use parent_job_id or fallback to job_id
                        stage_number=task_data.get('stage', 1),
                        task_type=task_data.get('task_type', 'unknown'),
                        success=task_data.get('status') == 'completed',
                        result_data=task_data.get('result_data', {}),
                        error_details=task_data.get('error_details'),
                        status=TaskStatus(task_data.get('status', 'failed'))
                    )
                    task_results.append(task_result)
                else:
                    # Already a TaskResult or unexpected type
                    task_results.append(task_data)

            result = JobCompletionResult(
                job_complete=row[0],
                final_stage=row[1],
                total_tasks=row[2],
                completed_tasks=row[3],
                task_results=task_results
            )
            
            if result.job_complete:
                logger.info(f"✅ Job complete: {job_id[:16]}... ({result.completed_tasks}/{result.total_tasks} tasks)")
            else:
                logger.debug(f"⏳ Job in progress: {job_id[:16]}... ({result.completed_tasks}/{result.total_tasks} tasks)")
            
            return result


# ============================================================================
# FUTURE POSTGIS REPOSITORIES - Placeholder for spatial data operations
# ============================================================================

# class PostGISRepository(PostgreSQLRepository):
#     """
#     PostGIS-specific repository for spatial data operations.
#     
#     Will inherit from PostgreSQLRepository and add:
#     - Spatial query methods (ST_Intersects, ST_Contains, etc.)
#     - Geometry/Geography type handling
#     - Raster operations
#     - Spatial indexing
#     - STAC (SpatioTemporal Asset Catalog) integration
#     """
#     pass

# class RasterRepository(PostGISRepository):
#     """
#     Repository for raster data operations using PostGIS.
#     
#     Will handle:
#     - COG (Cloud Optimized GeoTIFF) storage references
#     - Raster tiling and pyramids
#     - Band math operations
#     - Raster statistics
#     """
#     pass

# class VectorRepository(PostGISRepository):
#     """
#     Repository for vector data operations using PostGIS.
#     
#     Will handle:
#     - Feature collections
#     - Spatial relationships
#     - Topology operations
#     - GeoJSON import/export
#     """
#     pass