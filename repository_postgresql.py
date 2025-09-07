# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: PostgreSQL-specific repository implementation with direct database access
# SOURCE: Consolidation of adapter_storage.py PostgreSQL logic without adapter abstraction
# SCOPE: PostgreSQL database operations for jobs and tasks
# VALIDATION: Uses psycopg.sql composition for SQL safety, atomic operations for race prevention
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
from datetime import datetime
from contextlib import contextmanager
import logging

from config import AppConfig, get_config
from schema_core import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    generate_job_id, generate_task_id
)
from repository_base import BaseRepository
from repository_abc import (
    IJobRepository, ITaskRepository, ICompletionDetector,
    StageAdvancementResult, TaskCompletionResult, JobCompletionResult
)

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
        # Check for complete connection string in environment
        env_conn_string = os.getenv('POSTGRESQL_CONNECTION_STRING')
        if env_conn_string:
            logger.debug("Using POSTGRESQL_CONNECTION_STRING from environment")
            return env_conn_string
        
        # Use connection string from config
        # This is built from config.postgis_* properties
        return self.config.postgis_connection_string
    
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
            conn = psycopg.connect(self.conn_string)
            yield conn
            
        except psycopg.Error as e:
            # Log connection errors with context
            logger.error(f"❌ PostgreSQL connection error: {e}")
            
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
        Execute a PostgreSQL query safely with SQL injection prevention.
        
        This is the core method for executing SQL queries. It uses psycopg's
        sql.Composed objects to prevent SQL injection by separating SQL
        structure from data values.
        
        SQL Safety:
        ----------
        - Query MUST be a sql.Composed object (not a string)
        - Parameters are always escaped/quoted by psycopg
        - Table/column names use sql.Identifier()
        - Values use parameterized queries with %s placeholders
        
        Parameters:
        ----------
        query : sql.Composed
            SQL query built using psycopg.sql composition.
            Example: sql.SQL("SELECT {} FROM {}").format(
                sql.Identifier("column"), sql.Identifier("table")
            )
        
        params : Optional[Tuple]
            Query parameters for %s placeholders. These are safely
            escaped by psycopg to prevent injection.
        
        fetch : Optional[str]
            Fetch behavior for SELECT queries:
            - None: No fetch (for INSERT/UPDATE/DELETE)
            - 'one': Fetch one row (cursor.fetchone)
            - 'all': Fetch all rows (cursor.fetchall)
            - 'many': Fetch multiple rows (cursor.fetchmany)
        
        Returns:
        -------
        Optional[Any]
            - For SELECT with fetch: Row(s) as tuple(s)
            - For INSERT/UPDATE/DELETE: Number of affected rows
            - For other operations: None
        
        Raises:
        ------
        psycopg.Error
            Database errors (constraint violations, syntax errors, etc.)
        
        ValueError
            If fetch parameter is invalid
        
        Usage Examples:
        --------------
        ```python
        # Safe SELECT with identifier and parameter
        query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(
            sql.Identifier("jobs")
        )
        result = self._execute_query(query, (job_id,), fetch='one')
        
        # Safe INSERT with return value
        query = sql.SQL("INSERT INTO {} (id, name) VALUES (%s, %s)").format(
            sql.Identifier("jobs")
        )
        rowcount = self._execute_query(query, (id, name))
        ```
        """
        with self._get_connection() as conn:
            with conn.cursor() as cursor:
                # Execute query with parameters
                cursor.execute(query, params)
                
                # Handle different fetch modes for SELECT
                if fetch == 'one':
                    return cursor.fetchone()
                elif fetch == 'all':
                    return cursor.fetchall()
                elif fetch == 'many':
                    return cursor.fetchmany()
                elif fetch:
                    raise ValueError(f"Invalid fetch parameter: {fetch}")
                
                # For DML statements (INSERT/UPDATE/DELETE)
                # cursor.description is None for non-SELECT queries
                if cursor.description is None:
                    conn.commit()
                    return cursor.rowcount  # Number of affected rows
                
                # For other operations (CREATE, ALTER, etc.)
                conn.commit()
                return None
    
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

class JobRepository(PostgreSQLRepository, IJobRepository):
    """
    PostgreSQL implementation of job repository.
    
    Handles all job-related database operations with direct PostgreSQL access.
    """
    
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
                    parameters, stage_results, result_data, error_details,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                json.dumps(job.result_data) if job.result_data else None,
                job.error_details,
                job.created_at or datetime.utcnow(),
                job.updated_at or datetime.utcnow()
            )
            
            rowcount = self._execute_query(query, params)
            created = rowcount > 0
            
            if created:
                logger.info(f"✅ Job created: {job.job_id[:16]}... type={job.job_type}")
            else:
                logger.info(f"📋 Job already exists: {job.job_id[:16]}... (idempotent)")
            
            return created
    
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

class TaskRepository(PostgreSQLRepository, ITaskRepository):
    """
    PostgreSQL implementation of task repository.
    
    Handles all task-related database operations with direct PostgreSQL access.
    """
    
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
                    task_id, parent_job_id, task_type, status, stage, task_index,
                    parameters, result_data, error_details, retry_count,
                    heartbeat, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (task_id) DO NOTHING
            """).format(
                sql.Identifier(self.schema_name),
                sql.Identifier("tasks")
            )
            
            params = (
                task.task_id,
                task.parent_job_id,
                task.task_type,
                task.status.value if isinstance(task.status, TaskStatus) else task.status,
                task.stage,
                task.task_index,
                json.dumps(task.parameters),
                json.dumps(task.result_data) if task.result_data else None,
                task.error_details,
                task.retry_count,
                task.heartbeat,
                task.created_at or datetime.utcnow(),
                task.updated_at or datetime.utcnow()
            )
            
            rowcount = self._execute_query(query, params)
            created = rowcount > 0
            
            if created:
                logger.info(f"✅ Task created: {task.task_id} type={task.task_type}")
            else:
                logger.info(f"📋 Task already exists: {task.task_id} (idempotent)")
            
            return created
    
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
                SELECT task_id, parent_job_id, task_type, status, stage, task_index,
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
                'task_type': row[2],
                'status': row[3],
                'stage': row[4],
                'task_index': row[5],
                'parameters': row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
                'result_data': row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else None,
                'error_details': row[8],
                'retry_count': row[9],
                'heartbeat': row[10],
                'created_at': row[11],
                'updated_at': row[12]
            }
            
            task_record = TaskRecord(**task_data)
            logger.debug(f"📋 Retrieved task: {task_id} status={task_record.status}")
            
            return task_record
    
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
                task_data = {
                    'task_id': row[0],
                    'parent_job_id': row[1],
                    'task_type': row[2],
                    'status': row[3],
                    'stage': row[4],
                    'task_index': row[5],
                    'parameters': row[6] if isinstance(row[6], dict) else json.loads(row[6]) if row[6] else {},
                    'result_data': row[7] if isinstance(row[7], dict) else json.loads(row[7]) if row[7] else None,
                    'error_details': row[8],
                    'retry_count': row[9],
                    'heartbeat': row[10],
                    'created_at': row[11],
                    'updated_at': row[12]
                }
                tasks.append(TaskRecord(**task_data))
            
            logger.info(f"📋 Listed {len(tasks)} tasks for job {job_id[:16]}...")
            
            return tasks


# ============================================================================
# COMPLETION DETECTOR - Atomic PostgreSQL operations
# ============================================================================

class CompletionDetector(PostgreSQLRepository, ICompletionDetector):
    """
    PostgreSQL implementation of completion detection.
    
    Provides atomic operations for task completion and stage advancement
    to prevent race conditions in distributed processing.
    """
    
    def complete_task_and_check_stage(
        self,
        task_id: str,
        job_id: str,
        stage: int,
        result_data: Dict[str, Any]
    ) -> TaskCompletionResult:
        """
        Atomically complete a task and check if stage is complete.
        
        Uses PostgreSQL function for atomic operation.
        
        Args:
            task_id: Task to complete
            job_id: Parent job ID (for validation)
            stage: Current stage number
            result_data: Task results
            
        Returns:
            TaskCompletionResult with completion status
        """
        with self._error_context("task completion", task_id):
            query = sql.SQL("""
                SELECT * FROM {}.complete_task_and_check_stage(%s, %s, %s)
            """).format(sql.Identifier(self.schema_name))
            
            params = (
                task_id,
                json.dumps(result_data) if result_data else None,
                None  # error_details is NULL for successful completion
            )
            
            row = self._execute_query(query, params, fetch='one')
            
            if not row:
                logger.error(f"❌ Task completion failed: {task_id}")
                return TaskCompletionResult(
                    task_updated=False,
                    stage_complete=False,
                    job_id=None,
                    stage_number=None,
                    remaining_tasks=0
                )
            
            result = TaskCompletionResult(
                task_updated=row[0],
                stage_complete=row[1],  # is_last_task_in_stage from SQL
                job_id=row[2],
                stage_number=row[3],
                remaining_tasks=row[4]
            )
            
            if result.task_updated:
                logger.info(f"✅ Task completed: {task_id} (remaining in stage: {result.remaining_tasks})")
                if result.stage_complete:
                    logger.info(f"🎯 Stage {result.stage_number} complete for job {result.job_id[:16]}...")
            
            return result
    
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
            
            # Parse task_results from JSONB
            task_results = row[4] if isinstance(row[4], list) else json.loads(row[4]) if row[4] else []
            
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