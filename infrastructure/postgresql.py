# ============================================================================
# CLAUDE CONTEXT - POSTGRESQL REPOSITORIES
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Infrastructure - PostgreSQL database repositories
# PURPOSE: PostgreSQL-specific repository implementation with direct database access and atomic operations
# LAST_REVIEWED: 29 OCT 2025
# EXPORTS: PostgreSQLRepository, PostgreSQLJobRepository, PostgreSQLTaskRepository, PostgreSQLStageCompletionRepository
# INTERFACES: BaseRepository, IJobRepository, ITaskRepository, IStageCompletionRepository
# PYDANTIC_MODELS: JobRecord, TaskRecord, StageAdvancementResult, TaskCompletionResult, JobCompletionResult
# DEPENDENCIES: psycopg, psycopg.sql, config, core.models, infrastructure.base
# SOURCE: PostgreSQL database (app schema: jobs, tasks tables)
# SCOPE: Database operations for job/task persistence and atomic completion detection
# VALIDATION: SQL injection prevention via psycopg.sql composition, transaction atomicity
# PATTERNS: Repository pattern, Unit of Work (transactions), Template Method, Connection pooling
# ENTRY_POINTS: repo = PostgreSQLJobRepository(); job = repo.get_job(job_id)
# INDEX: PostgreSQLRepository:61, PostgreSQLJobRepository:514, PostgreSQLTaskRepository:736, PostgreSQLStageCompletionRepository:949
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
from psycopg.rows import dict_row
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from contextlib import contextmanager
import logging

from config import AppConfig, get_config
from core.models import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    StageAdvancementResult, TaskResult
)
from core.utils import generate_job_id
from core.models.results import TaskCompletionResult, JobCompletionResult
# generate_task_id moved to Controller layer - repository no longer needs it
from .base import BaseRepository
from .interface_repository import (
    IJobRepository, ITaskRepository, IStageCompletionRepository
)
from core.schema.updates import TaskUpdateModel, JobUpdateModel
from utils import enforce_contract  # Added for contract enforcement

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
        Password: postgresql://user:password@host:port/database?sslmode=require
        Managed Identity: host=hostname port=5432 dbname=database user=identity_name password=token sslmode=require

        Configuration Sources (in priority order):
        -----------------------------------------
        1. POSTGRESQL_CONNECTION_STRING environment variable (complete string)
        2. Managed Identity (if USE_MANAGED_IDENTITY=true)
        3. AppConfig.postgis_connection_string property (password-based)
        4. Individual components from AppConfig (host, user, database, etc.)

        Returns:
        -------
        str
            Complete PostgreSQL connection string with SSL enabled.

        Raises:
        ------
        ValueError
            If required configuration is missing or invalid.

        RuntimeError
            If managed identity token acquisition fails.

        Security Notes:
        --------------
        - Managed identity tokens are valid for ~1 hour (auto-refreshed by Azure SDK)
        - Passwords are included in the connection string (be careful with logging)
        - SSL is enforced by default (sslmode=require)
        - Managed identity is recommended for production (passwordless authentication)
        """
        logger.debug("🔌 Getting PostgreSQL connection string...")

        # Check if managed identity is enabled
        use_managed_identity = self._should_use_managed_identity()

        if use_managed_identity:
            logger.info("🔐 Using Azure Managed Identity for PostgreSQL authentication")
            return self._build_managed_identity_connection_string()
        else:
            # Use password-based authentication
            logger.debug("📋 Building connection string from AppConfig (password-based)")
            conn_str = self.config.postgis_connection_string
            logger.debug(f"  Final connection string will be used for connection")
            return conn_str

    def _should_use_managed_identity(self) -> bool:
        """
        Determine if managed identity authentication should be used.

        Decision Logic:
        --------------
        1. Explicit flag: USE_MANAGED_IDENTITY environment variable
        2. Auto-detect: Running in Azure Functions without password configured
        3. Fallback: Use password authentication

        Returns:
        -------
        bool
            True if managed identity should be used, False for password auth.

        Environment Variables:
        ---------------------
        USE_MANAGED_IDENTITY: "true" or "false" (case-insensitive)
        WEBSITE_INSTANCE_ID: Present when running in Azure Functions
        """
        # Check explicit flag
        use_mi_env = os.getenv("USE_MANAGED_IDENTITY", "false").lower()
        if use_mi_env == "true":
            logger.debug("✅ USE_MANAGED_IDENTITY=true - managed identity enabled")
            return True
        elif use_mi_env == "false":
            logger.debug("❌ USE_MANAGED_IDENTITY=false - password authentication")
            return False

        # Auto-detect Azure environment without password
        in_azure = bool(os.getenv("WEBSITE_INSTANCE_ID"))
        has_password = bool(self.config.postgis_password)

        if in_azure and not has_password:
            logger.info("🔍 Auto-detected Azure Functions without password - using managed identity")
            return True

        # Default to password authentication
        return False

    def _build_managed_identity_connection_string(self) -> str:
        """
        Build PostgreSQL connection string using Azure Managed Identity.

        This method acquires an access token from Azure AD and uses it as
        the password in the PostgreSQL connection string. The token is valid
        for approximately 1 hour and is automatically refreshed by the Azure SDK.

        Token Acquisition:
        -----------------
        Uses DefaultAzureCredential which tries in order:
        1. EnvironmentCredential (service principal via env vars)
        2. ManagedIdentityCredential (Azure Functions, VMs, etc.)
        3. AzureCliCredential (local development with `az login`)
        4. Visual Studio Code credential
        5. Interactive browser login

        Connection String Format:
        ------------------------
        host=hostname port=5432 dbname=database user=identity_name password=token sslmode=require

        Returns:
        -------
        str
            PostgreSQL connection string with managed identity token.

        Raises:
        ------
        RuntimeError
            If token acquisition fails and no password fallback available.

        Environment Variables:
        ---------------------
        MANAGED_IDENTITY_NAME: Override default identity name (optional)
        POSTGIS_PASSWORD: Fallback password if token acquisition fails (optional)

        Security Notes:
        --------------
        - Tokens are short-lived (1 hour) and automatically refreshed
        - Token is logged in masked form for debugging
        - No passwords stored in configuration or Key Vault
        """
        from azure.identity import DefaultAzureCredential
        from azure.core.exceptions import ClientAuthenticationError

        try:
            logger.debug("🔑 Acquiring Azure Managed Identity token...")

            # Create credential (cached internally by Azure SDK)
            credential = DefaultAzureCredential()

            # Get access token for PostgreSQL
            # Scope is fixed for all Azure PostgreSQL Flexible Servers
            token_response = credential.get_token(
                "https://ossrdbms-aad.database.windows.net/.default"
            )
            token = token_response.token

            logger.debug(f"✅ Token acquired successfully (expires in ~{token_response.expires_on - __import__('time').time():.0f}s)")

            # Get managed identity name (matches PostgreSQL user)
            # Default: rmhazuregeoapi-identity (same as Function App name)
            managed_identity_name = os.getenv(
                "MANAGED_IDENTITY_NAME",
                f"{os.getenv('WEBSITE_SITE_NAME', 'rmhazuregeoapi')}-identity"
            )

            logger.debug(f"👤 Using managed identity: {managed_identity_name}")

            # Build connection string with token as password
            # Use psycopg3 format (key=value pairs)
            conn_str = (
                f"host={self.config.postgis_host} "
                f"port={self.config.postgis_port} "
                f"dbname={self.config.postgis_database} "
                f"user={managed_identity_name} "
                f"password={token} "
                f"sslmode=require"
            )

            # Log connection details (with token masked)
            masked_str = (
                f"host={self.config.postgis_host} "
                f"port={self.config.postgis_port} "
                f"dbname={self.config.postgis_database} "
                f"user={managed_identity_name} "
                f"password=***TOKEN({len(token)} chars)*** "
                f"sslmode=require"
            )
            logger.debug(f"🔗 Managed identity connection string: {masked_str}")

            return conn_str

        except ClientAuthenticationError as e:
            logger.error(f"❌ Failed to acquire managed identity token: {e}")
            logger.error(f"   Error type: {type(e).__name__}")
            logger.error(f"   Error details: {str(e)}")

            # Check if password fallback is available
            if self.config.postgis_password:
                logger.warning("⚠️ Falling back to password authentication")
                return self.config.postgis_connection_string
            else:
                error_msg = (
                    "Managed identity token acquisition failed and no password available. "
                    "Ensure Function App has managed identity enabled and assigned to PostgreSQL."
                )
                logger.error(f"❌ {error_msg}")
                raise RuntimeError(error_msg) from e

        except Exception as e:
            logger.error(f"❌ Unexpected error acquiring managed identity token: {e}")
            logger.error(f"   Error type: {type(e).__name__}")

            # Check if password fallback is available
            if self.config.postgis_password:
                logger.warning("⚠️ Falling back to password authentication")
                return self.config.postgis_connection_string
            else:
                error_msg = f"Unexpected error during token acquisition: {e}"
                logger.error(f"❌ {error_msg}")
                raise RuntimeError(error_msg) from e
    
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
            
            conn = psycopg.connect(self.conn_string, row_factory=dict_row)
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
            ) as exists
        """)

        result = self._execute_query(query, (self.schema_name, table_name), fetch='one')
        return result['exists'] if result else False


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
                job.status.value,  # Require JobStatus enum
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
            
            # Convert row to JobRecord (row is now a dict thanks to dict_row)
            job_data = {
                'job_id': row['job_id'],
                'job_type': row['job_type'],
                'status': row['status'],
                'stage': row['stage'],
                'total_stages': row['total_stages'],
                'parameters': row['parameters'] if isinstance(row['parameters'], dict) else json.loads(row['parameters']) if row['parameters'] else {},
                'stage_results': row['stage_results'] if isinstance(row['stage_results'], dict) else json.loads(row['stage_results']) if row['stage_results'] else {},
                'result_data': row['result_data'] if isinstance(row['result_data'], dict) else json.loads(row['result_data']) if row['result_data'] else None,
                'error_details': row['error_details'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
            
            job_record = JobRecord(**job_data)
            logger.debug(f"📋 Retrieved job: {job_id[:16]}... status={job_record.status}")
            
            return job_record
    
    @enforce_contract(
        params={'job_id': str, 'updates': JobUpdateModel},
        returns=bool
    )
    def update_job(self, job_id: str, updates: JobUpdateModel) -> bool:
        """
        Update a job in PostgreSQL using type-safe Pydantic model.

        Args:
            job_id: Job ID to update
            updates: JobUpdateModel with fields to update

        Returns:
            True if updated, False otherwise
        """
        with self._error_context("job update", job_id):
            # Convert Pydantic model to dict, excluding unset fields
            update_dict = updates.to_dict(exclude_unset=True)

            if not update_dict:
                return False

            # Build UPDATE query dynamically
            set_clauses = []
            params = []

            for field, value in update_dict.items():
                set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))

                # Handle special types
                if field in ['parameters', 'stage_results', 'result_data', 'metadata'] and value is not None:
                    params.append(json.dumps(value) if not isinstance(value, str) else value)
                else:
                    # Pydantic has already converted enums to strings
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
                logger.info(f"✅ Job updated: {job_id[:16]}... fields={list(update_dict.keys())}")
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
                params = (status_filter.value,)  # Require JobStatus enum
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
                    'job_id': row['job_id'],
                    'job_type': row['job_type'],
                    'status': row['status'],
                    'stage': row['stage'],
                    'total_stages': row['total_stages'],
                    'parameters': row['parameters'] if isinstance(row['parameters'], dict) else json.loads(row['parameters']) if row['parameters'] else {},
                    'stage_results': row['stage_results'] if isinstance(row['stage_results'], dict) else json.loads(row['stage_results']) if row['stage_results'] else {},
                    'result_data': row['result_data'] if isinstance(row['result_data'], dict) else json.loads(row['result_data']) if row['result_data'] else None,
                    'error_details': row['error_details'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
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
                task.status.value,  # Require TaskStatus enum
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
                'task_id': row['task_id'],
                'parent_job_id': row['parent_job_id'],
                'job_type': row['job_type'],
                'task_type': row['task_type'],
                'status': row['status'],
                'stage': row['stage'],
                'task_index': row['task_index'],
                'parameters': row['parameters'] if isinstance(row['parameters'], dict) else json.loads(row['parameters']) if row['parameters'] else {},
                'result_data': row['result_data'] if isinstance(row['result_data'], dict) else json.loads(row['result_data']) if row['result_data'] else None,
                'error_details': row['error_details'],
                'retry_count': row['retry_count'],
                'heartbeat': row['heartbeat'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
            
            task_record = TaskRecord(**task_data)
            logger.debug(f"📋 Retrieved task: {task_id} status={task_record.status}")
            
            return task_record
    
    @enforce_contract(
        params={'task_id': str, 'updates': TaskUpdateModel},
        returns=bool
    )
    def update_task(self, task_id: str, updates: TaskUpdateModel) -> bool:
        """
        Update a task in PostgreSQL using type-safe Pydantic model.

        Args:
            task_id: Task ID to update
            updates: TaskUpdateModel with fields to update

        Returns:
            True if updated, False otherwise
        """
        with self._error_context("task update", task_id):
            # Convert Pydantic model to dict, excluding unset fields
            update_dict = updates.to_dict(exclude_unset=True)

            if not update_dict:
                return False

            # DIAGNOSTIC: Get current task state before update (11 NOV 2025)
            current_task = self.get_task(task_id)
            if current_task:
                logger.debug(
                    f"🔍 [PRE-UPDATE] Task {task_id[:16]} current state: "
                    f"status={current_task.status}, "
                    f"stage={current_task.stage}, "
                    f"retry_count={current_task.retry_count}"
                )
                logger.debug(f"🔍 [PRE-UPDATE] Attempting to update fields: {list(update_dict.keys())}")
            else:
                logger.warning(f"⚠️ [PRE-UPDATE] Task {task_id} not found in database before update attempt")

            # Build UPDATE query dynamically
            set_clauses = []
            params = []

            for field, value in update_dict.items():
                set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))

                # Handle special types
                if field in ['parameters', 'result_data', 'metadata'] and value is not None:
                    params.append(json.dumps(value) if not isinstance(value, str) else value)
                else:
                    # Pydantic has already converted enums to strings
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
                logger.info(f"✅ Task updated: {task_id[:16]} fields={list(update_dict.keys())} (rowcount={rowcount})")
            else:
                # DIAGNOSTIC: Enhanced error logging when update affects 0 rows (11 NOV 2025)
                logger.error(
                    f"❌ [UPDATE-FAILED] Task update affected 0 rows - task_id={task_id[:16]}, "
                    f"fields_attempted={list(update_dict.keys())}"
                )
                if current_task:
                    logger.error(
                        f"❌ [UPDATE-FAILED] Task exists but UPDATE matched 0 rows - "
                        f"possible cause: WHERE clause mismatch or concurrent modification"
                    )
                else:
                    logger.error(f"❌ [UPDATE-FAILED] Task {task_id[:16]} does not exist in database")

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
                SELECT task_id, parent_job_id, job_type, task_type, status, stage, task_index,
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
                if isinstance(row['status'], str):
                    try:
                        status = TaskStatus(row['status'])
                    except ValueError as e:
                        raise ValueError(
                            f"Invalid TaskStatus from database: '{row['status']}'. "
                            f"Valid values are: {[s.value for s in TaskStatus]}"
                        ) from e
                else:
                    status = row['status']

                # Now we have job_type from the fixed query
                try:
                    task_record = TaskRecord(
                        task_id=row['task_id'],
                        parent_job_id=row['parent_job_id'],
                        job_type=row['job_type'],
                        task_type=row['task_type'],
                        status=status,
                        stage=row['stage'],
                        task_index=row['task_index'],
                        parameters=row['parameters'] if isinstance(row['parameters'], dict) else json.loads(row['parameters']) if row['parameters'] else {},
                        result_data=row['result_data'] if isinstance(row['result_data'], dict) else json.loads(row['result_data']) if row['result_data'] else None,
                        error_details=row['error_details'],
                        retry_count=row['retry_count'],
                        heartbeat=row['heartbeat'],
                        created_at=row['created_at'],
                        updated_at=row['updated_at']
                    )
                    tasks.append(task_record)
                except Exception as e:
                    raise TypeError(
                        f"Failed to create TaskRecord from database row for task_id={row['task_id']}. "
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
                    logger.debug(f"[SQL_FUNCTION_DEBUG] Task {task_id} current DB status before SQL function: {current_status['status'] if current_status else 'NOT FOUND'}")
            
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
                task_updated=row['task_updated'],
                stage_complete=row['is_last_task_in_stage'],
                job_id=row['job_id'],
                stage_number=row['stage_number'],
                remaining_tasks=row['remaining_tasks']
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
                                logger.debug(f"  - {task['task_id']}: {task['status']}")
            
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
                job_updated=row['job_updated'],
                new_stage=row['new_stage'],
                is_final_stage=row['is_final_stage']
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
            if not isinstance(row['task_results'], list):
                raise ValueError(f"Invalid task_results from database: expected list, got {type(row['task_results'])}")

            # Convert raw dicts to TaskResult objects for contract enforcement
            raw_task_results = row['task_results'] if row['task_results'] is not None else []
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
                job_complete=row['job_complete'],
                final_stage=row['final_stage'],
                total_tasks=row['total_tasks'],
                completed_tasks=row['completed_tasks'],
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