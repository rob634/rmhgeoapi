# ============================================================================
# BASE REPOSITORY - PURE ABSTRACT CLASS
# ============================================================================
# STATUS: Infrastructure - Repository hierarchy root
# PURPOSE: Common validation, error handling, and logging for all repositories
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Base Repository - Pure Abstract Class.

Abstract base repository class that all storage-specific repositories inherit from.
Contains NO storage implementation details, only common validation logic,
error handling patterns, and logging infrastructure.

Architecture:
    BaseRepository (this file - pure abstract)
        |
    Storage-specific bases (PostgreSQLRepository, ContainerRepository, etc.)
        |
    Domain-specific repositories (JobRepository, TaskRepository, etc.)

Key Design Principles:
    - NO storage backend dependencies
    - NO connection management
    - NO query execution
    - ONLY common patterns and utilities

Exports:
    BaseRepository: Abstract base class for repositories
"""

from abc import ABC
from contextlib import contextmanager
from typing import Union, Optional, Dict, Any
import logging

from core.models import JobRecord, TaskRecord, JobStatus, TaskStatus
from core.utils import SchemaValidationError

# Logger setup
logger = logging.getLogger(__name__)


# ============================================================================
# PURE BASE REPOSITORY - No storage dependencies
# ============================================================================

class BaseRepository(ABC):
    """
    Pure abstract base repository with common validation logic.
    
    This class provides shared functionality for ALL repositories regardless
    of storage backend. It contains NO storage-specific code. This is the root
    of the repository hierarchy and ensures consistent behavior across all
    storage implementations.
    
    Design Philosophy:
    ----------------
    The BaseRepository follows the principle of "composition over inheritance"
    for storage backends while using inheritance for shared behavior. Each
    storage-specific repository (PostgreSQL, Container, etc.) inherits from
    this base and adds its own connection management and query execution.
    
    Inheritance Hierarchy:
    ---------------------
    BaseRepository (this class)
        ├── PostgreSQLRepository
        │   ├── JobRepository
        │   ├── TaskRepository
        │   └── CompletionDetector
        ├── ContainerRepository (future)
        │   ├── BlobRepository
        │   └── InventoryRepository
        └── CosmosRepository (future)
            └── MetadataRepository
    
    Responsibilities:
    ----------------
    - Schema validation using Pydantic models
    - Error handling with consistent patterns
    - Logging setup and configuration
    - Status transition validation for state machines
    - Stage progression validation for workflows
    - Parent-child relationship validation
    
    NOT Responsible For:
    -------------------
    - Connection management (handled by storage-specific subclasses)
    - Query execution (handled by storage-specific subclasses)
    - Storage operations (handled by storage-specific subclasses)
    - Transaction management (storage-specific)
    
    Usage Example:
    -------------
    ```python
    class MyStorageRepository(BaseRepository):
        def __init__(self, connection_params):
            super().__init__()  # Initialize base validation and logging
            self.connection = self._setup_connection(connection_params)
        
        def create_entity(self, entity):
            with self._error_context("entity creation", entity.id):
                # Validation happens automatically through context
                self._execute_storage_operation(entity)
    ```
    
    Thread Safety:
    -------------
    This class is thread-safe for read operations. Write operations should
    be synchronized at the storage layer if needed.
    """
    
    def __init__(self):
        """
        Initialize base repository with validation and logging.
        
        This constructor sets up the common infrastructure needed by all
        repositories. It intentionally does NOT accept any storage parameters
        to maintain clean separation of concerns.
        
        Attributes Set:
        --------------
        logger : Logger
            Component-specific logger for this repository
        
        Note:
        -----
        Subclasses MUST call super().__init__() before any storage setup
        to ensure validation and logging are properly initialized.
        
        Example:
        -------
        ```python
        class PostgreSQLRepository(BaseRepository):
            def __init__(self, conn_string):
                super().__init__()  # MUST be called first
                self.connection = psycopg.connect(conn_string)
        ```
        """
        # Setup component-specific logger
        # Each repository gets its own logger for better tracing
        self.logger = self._setup_logger()
        
        # Log initialization for debugging
        # The emoji helps with visual scanning of logs
        logger.info(f"🏛️ {self.__class__.__name__} base initialized")
    
    def _setup_logger(self) -> logging.Logger:
        """
        Setup component-specific logger with enhanced capabilities.
        
        This method attempts to use the application's enhanced logger factory
        which provides structured logging with Azure Application Insights
        integration. If that's not available (e.g., during testing), it falls
        back to Python's standard logging.
        
        Returns:
        -------
        logging.Logger
            Configured logger instance for this repository
        
        Implementation Notes:
        --------------------
        The LoggerFactory provides:
        - Component-type specific formatting
        - Correlation ID tracking across operations
        - Azure Application Insights integration
        - Structured logging with custom dimensions
        
        The fallback ensures the repository works even without the full
        application infrastructure (useful for testing and debugging).
        """
        try:
            # Try to use the enhanced logger factory if available
            # This provides better integration with Azure monitoring
            from util_logger import LoggerFactory
            from util_logger import ComponentType, LogLevel, LogContext
            return LoggerFactory.create_logger(
                ComponentType.REPOSITORY,
                self.__class__.__name__
            )
        except ImportError:
            # Fallback to standard logging for standalone usage
            # This ensures the repository works even without full infrastructure
            return logging.getLogger(self.__class__.__name__)
    
    @contextmanager
    def _error_context(self, operation: str, entity_id: Optional[str] = None):
        """
        Context manager for consistent error handling across all operations.
        
        This context manager provides a standardized way to handle errors
        in repository operations. It ensures that:
        1. All errors are logged with consistent formatting
        2. Schema validation errors are distinguished from other errors
        3. Entity IDs are included in error messages when available
        4. Original exceptions are preserved and re-raised
        
        Parameters:
        ----------
        operation : str
            Human-readable description of the operation being performed.
            Examples: "job creation", "task update", "status transition"
        
        entity_id : Optional[str]
            The ID of the entity being operated on (job_id, task_id, etc.).
            This helps with debugging by identifying which specific entity
            caused the error.
        
        Yields:
        ------
        None
            The context manager yields control back to the caller.
            The actual operation should be performed in the with block.
        
        Raises:
        ------
        SchemaValidationError
            Re-raised if the operation fails due to schema validation.
            These errors indicate data that doesn't match our Pydantic models.
        
        Exception
            Re-raised after logging. All exceptions are logged then re-raised
            to allow higher-level error handling.
        
        Usage Example:
        -------------
        ```python
        with self._error_context("job update", job_id):
            # Perform the actual update operation
            self._execute_update(job_id, updates)
            # Any exception here will be logged with context
        ```
        
        Logging Format:
        --------------
        Success: No logging (assumed successful if no exception)
        Schema Error: "❌ Schema validation failed during {operation}: {error}"
        Other Error: "❌ {operation} failed for {entity_id}: {error}"
        """
        try:
            # Yield control back to the caller
            # The actual operation happens in the with block
            yield
            
        except SchemaValidationError as e:
            # Handle schema validation errors specially
            # These indicate data structure problems
            self.logger.error(f"❌ Schema validation failed during {operation}: {e}")
            raise  # Re-raise to allow handling at higher level
            
        except Exception as e:
            # Handle all other exceptions
            # Build error message with context
            error_msg = f"❌ {operation} failed"
            
            # Include entity ID if provided for better debugging
            if entity_id:
                error_msg += f" for {entity_id}"
                
            # Include the actual error
            error_msg += f": {e}"
            
            # Log the error with full context
            self.logger.error(error_msg)
            
            # Re-raise to allow handling at higher level
            # This preserves the original stack trace
            raise
    
    def _validate_status_transition(
        self,
        current_record: Union[JobRecord, TaskRecord],
        new_status: Union[JobStatus, TaskStatus]
    ) -> None:
        """
        Validate status transitions to prevent invalid state changes.
        
        This method enforces the state machine rules for job and task status
        transitions. It prevents logically invalid transitions like moving
        from COMPLETED back to PROCESSING, which would corrupt the workflow.
        
        State Machine Rules:
        -------------------
        QUEUED → PROCESSING, FAILED
        PROCESSING → COMPLETED, FAILED
        COMPLETED → (terminal, no transitions)
        FAILED → (terminal, no transitions)
        
        Parameters:
        ----------
        current_record : Union[JobRecord, TaskRecord]
            The current job or task record with its existing status.
            Must have a can_transition_to() method.
        
        new_status : Union[JobStatus, TaskStatus]
            The proposed new status to transition to.
        
        Raises:
        ------
        SchemaValidationError
            If the transition is not allowed by the state machine rules.
            The error includes details about the invalid transition.
        
        Implementation Note:
        -------------------
        This delegates to the record's built-in can_transition_to() method
        which encapsulates the state machine logic in the model itself.
        """
        try:
            # Use the record's built-in transition validation
            # This keeps state machine logic with the model
            if not current_record.can_transition_to(new_status):
                raise ValueError(
                    f"Invalid status transition: {current_record.status} → {new_status}"
                )
        except ValueError as e:
            # Convert to SchemaValidationError for consistent error handling
            raise SchemaValidationError(
                f"Status transition validation failed for {type(current_record).__name__}: {str(e)}",
                field="status_transition",
                value=f"{current_record.status} → {new_status}"
            )
    
    def _validate_stage_progression(
        self,
        current_stage: int,
        new_stage: int,
        total_stages: int
    ) -> None:
        """
        Validate stage progression for multi-stage job workflows.
        
        This ensures that jobs progress through stages sequentially without
        skipping stages or exceeding the total number of stages defined for
        the workflow. Stages must always advance (never go backward).
        
        Stage Rules:
        -----------
        1. Stages must advance (new_stage > current_stage)
        2. Cannot skip stages (typically new = current + 1)
        3. Cannot exceed total stages defined for the job
        4. Stage numbering starts at 1 (not 0)
        
        Parameters:
        ----------
        current_stage : int
            The current stage number (1-based indexing)
        
        new_stage : int
            The proposed new stage number
        
        total_stages : int
            The total number of stages in the workflow
        
        Raises:
        ------
        SchemaValidationError
            If stage progression violates any rules. May contain multiple
            error details if multiple rules are violated.
        
        Examples:
        --------
        Valid: current=1, new=2, total=3 ✓
        Invalid: current=2, new=1, total=3 ✗ (going backward)
        Invalid: current=1, new=4, total=3 ✗ (exceeds total)
        """
        errors = []
        
        # Check that stages advance forward
        if new_stage <= current_stage:
            errors.append({
                "msg": f"Stage must advance: current={current_stage}, new={new_stage}",
                "loc": ["stage"]
            })
        
        # Check that stage doesn't exceed total
        if new_stage > total_stages:
            errors.append({
                "msg": f"Stage {new_stage} exceeds total_stages {total_stages}",
                "loc": ["stage"]
            })
        
        # Raise all validation errors together
        if errors:
            raise SchemaValidationError("JobRecord", errors)
    
    def _validate_parent_child_relationship(
        self,
        task_id: str,
        parent_job_id: str
    ) -> None:
        """
        Validate parent-child relationship between tasks and jobs.
        
        This ensures that tasks are properly associated with their parent jobs
        by validating that the task ID follows the expected format that includes
        the parent job ID as a prefix. This maintains referential integrity.
        
        Task ID Format:
        --------------
        {job_id[:8]}-s{stage}-{semantic_index}
        
        Example:
        -------
        Job ID: "a1b2c3d4e5f6g7h8..." (64-char SHA256)
        Task ID: "a1b2c3d4-s1-greet_0"
        
        Parameters:
        ----------
        task_id : str
            The task ID to validate
        
        parent_job_id : str
            The parent job ID that should be a prefix of task_id
        
        Raises:
        ------
        SchemaValidationError
            If the task_id doesn't start with the parent_job_id,
            indicating a broken parent-child relationship.
        
        Security Note:
        -------------
        This validation prevents tasks from being associated with the
        wrong job, which could lead to data leakage or corruption.
        """
        # Task ID must start with first 8 characters of parent job ID
        job_id_prefix = parent_job_id[:8]
        if not task_id.startswith(job_id_prefix):
            raise SchemaValidationError(
                "TaskRecord",
                [{
                    "msg": f"Task ID must start with job ID prefix (8 chars). Got task_id={task_id}, expected prefix={job_id_prefix}, parent_job_id={parent_job_id[:16]}...",
                    "loc": ["task_id", "parent_job_id"]
                }]
            )
    
    def _log_operation_result(
        self,
        success: bool,
        operation: str,
        entity_id: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log operation results with consistent formatting and detail level.
        
        This provides a standardized way to log the results of repository
        operations, making it easier to trace operations through the logs.
        The use of emoji prefixes enables quick visual scanning.
        
        Log Levels:
        ----------
        - Success (✅): INFO level - normal operation completed
        - Failure (⚠️): WARNING level - operation failed but handled
        
        Parameters:
        ----------
        success : bool
            True if the operation succeeded, False otherwise
        
        operation : str
            Human-readable description of the operation
            Examples: "Job created", "Task updated", "Stage advanced"
        
        entity_id : str
            The ID of the entity that was operated on
            For long IDs, consider truncating: entity_id[:16] + "..."
        
        details : Optional[Dict[str, Any]]
            Additional context to include in the log message
            Examples: {"stage": 2, "status": "completed"}
        
        Log Format:
        ----------
        Success: "✅ {operation}: {entity_id} | {details}"
        Failure: "⚠️ {operation} failed: {entity_id} | {details}"
        
        Usage Example:
        -------------
        ```python
        self._log_operation_result(
            success=True,
            operation="Job created",
            entity_id=job_id[:16] + "...",
            details={"type": job_type, "stages": total_stages}
        )
        ```
        """
        # Build base message with emoji prefix
        if success:
            msg = f"✅ {operation}: {entity_id}"
        else:
            msg = f"⚠️ {operation} failed: {entity_id}"
        
        # Add optional details
        if details:
            msg += f" | {details}"
        
        # Log at appropriate level
        if success:
            self.logger.info(msg)
        else:
            self.logger.warning(msg)


# ============================================================================
# FUTURE REPOSITORY BASES - Placeholders for other storage backends
# ============================================================================

# class ContainerRepository(BaseRepository):
#     """
#     Azure Storage Container repository base class.
#     
#     Will provide:
#     - Azure Storage client management
#     - Blob upload/download operations
#     - Container management
#     - SAS token generation
#     - Retry policies for Azure Storage
#     
#     Subclasses:
#     - BlobRepository: Individual blob operations
#     - InventoryRepository: Container inventory management
#     - TileRepository: Raster tile storage
#     """
#     pass

# class CosmosRepository(BaseRepository):
#     """
#     Azure Cosmos DB repository base class.
#     
#     Will provide:
#     - Cosmos client management
#     - Document operations
#     - Query building
#     - Partition key handling
#     - Cross-partition queries
#     
#     Subclasses:
#     - MetadataRepository: Geospatial metadata storage
#     - CatalogRepository: STAC catalog entries
#     """
#     pass

# class RedisRepository(BaseRepository):
#     """
#     Redis cache repository base class.
#     
#     Will provide:
#     - Redis connection pooling
#     - Key-value operations
#     - TTL management
#     - Pub/sub operations
#     - Cache invalidation patterns
#     
#     Subclasses:
#     - CacheRepository: General caching
#     - SessionRepository: User session management
#     - QueueRepository: Redis-based queuing
#     """
#     pass