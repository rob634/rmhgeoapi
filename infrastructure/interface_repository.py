# ============================================================================
# CLAUDE CONTEXT - INTERFACE
# ============================================================================
# CATEGORY: AZURE RESOURCE REPOSITORIES
# PURPOSE: Azure SDK wrapper providing data access abstraction
# EPOCH: Shared by all epochs (infrastructure layer)# PURPOSE: Abstract interfaces defining behavior contracts for repository implementations
# EXPORTS: IJobRepository, ITaskRepository, IQueueRepository, IStageCompletionRepository, IDuckDBRepository, ParamNames
# INTERFACES: ABC interfaces defining canonical repository contracts for all implementations
# PYDANTIC_MODELS: JobRecord, TaskRecord (imported from schema_base for type hints)
# DEPENDENCIES: abc, typing, enum, schema_base
# SOURCE: No data source - defines abstract interfaces and contracts
# SCOPE: Global repository pattern enforcement - all repository implementations must follow these interfaces
# VALIDATION: ABC enforcement ensures method signature compliance, type hints provide compile-time checking
# PATTERNS: Interface Segregation, Repository pattern, Protocol pattern, Parameter Object pattern
# ENTRY_POINTS: class PostgreSQLRepository(IJobRepository); must implement all abstract methods
# INDEX: ParamNames:43, IJobRepository:93, ITaskRepository:120, ICompletionDetector:146
# ============================================================================

"""
Repository Abstract Base Classes - Single Point of Truth

This module enforces EXACT method signatures across all repository implementations,
preventing parameter name mismatches that have caused bugs. All parameter names,
return types, and method signatures are defined HERE and nowhere else.

Philosophy: "Define once, enforce everywhere"

The current bug where advance_job_stage() has different signatures in different
files would be IMPOSSIBLE with this pattern.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Protocol, Final
from enum import Enum
from pydantic import BaseModel

from core.models import (
    JobRecord, TaskRecord, JobStatus, TaskStatus,
    StageAdvancementResult
)
from core.models.results import JobCompletionResult, TaskCompletionResult
from core.schema.updates import TaskUpdateModel, JobUpdateModel


# ============================================================================
# CANONICAL PARAMETER NAMES - Single source of truth
# ============================================================================

class ParamNames:
    """
    ALL parameter names used across the system.
    Using class attributes as constants ensures consistency.
    
    This prevents bugs like 'stage_results' vs 'stage_results' mismatches.
    """
    
    # Job parameters
    JOB_ID: Final[str] = "job_id"
    JOB_TYPE: Final[str] = "job_type"
    JOB_STATUS: Final[str] = "status"
    
    # Stage parameters
    CURRENT_STAGE: Final[str] = "current_stage"
    STAGE_RESULTS: Final[str] = "stage_results"  # ALWAYS plural
    STAGE_NUMBER: Final[str] = "stage"
    TOTAL_STAGES: Final[str] = "total_stages"
    
    # Task parameters
    TASK_ID: Final[str] = "task_id"
    TASK_TYPE: Final[str] = "task_type"
    TASK_STATUS: Final[str] = "status"
    PARENT_JOB_ID: Final[str] = "parent_job_id"
    
    # Result parameters
    RESULT_DATA: Final[str] = "result_data"
    ERROR_DETAILS: Final[str] = "error_details"
    
    # Return value keys
    JOB_UPDATED: Final[str] = "job_updated"
    NEW_STAGE: Final[str] = "new_stage"
    IS_FINAL_STAGE: Final[str] = "is_final_stage"
    STAGE_COMPLETE: Final[str] = "stage_complete"
    REMAINING_TASKS: Final[str] = "remaining_tasks"
    JOB_COMPLETE: Final[str] = "job_complete"
    FINAL_STAGE: Final[str] = "final_stage"
    TOTAL_TASKS: Final[str] = "total_tasks"
    COMPLETED_TASKS: Final[str] = "completed_tasks"
    TASK_RESULTS: Final[str] = "task_results"


# ============================================================================
# ABSTRACT BASE CLASSES - Enforce exact signatures
# ============================================================================
# Note: Return type models (JobCompletionResult, TaskCompletionResult, 
# StageAdvancementResult) are now imported from schema_base.py as they are
# core data models that belong in the schema layer, not the repository layer.

class IJobRepository(ABC):
    """
    Job repository interface with EXACT method signatures.
    All implementations MUST use these exact parameter names.
    """
    
    @abstractmethod
    def create_job(self, job: JobRecord) -> bool:
        """Create a new job record"""
        pass
    
    @abstractmethod
    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Get job by ID - parameter MUST be named 'job_id'"""
        pass
    
    @abstractmethod
    def update_job(self, job_id: str, updates: JobUpdateModel) -> bool:
        """Update job - parameter MUST use JobUpdateModel for type safety"""
        pass
    
    @abstractmethod
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]:
        """List jobs with optional filtering"""
        pass


class ITaskRepository(ABC):
    """
    Task repository interface with EXACT method signatures.
    """
    
    @abstractmethod
    def create_task(self, task: TaskRecord) -> bool:
        """Create a new task record"""
        pass
    
    @abstractmethod
    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Get task by ID - parameter MUST be named 'task_id'"""
        pass
    
    @abstractmethod
    def update_task(self, task_id: str, updates: TaskUpdateModel) -> bool:
        """Update task - parameter MUST use TaskUpdateModel for type safety"""
        pass
    
    @abstractmethod
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]:
        """List all tasks for a job - parameter MUST be named 'job_id'"""
        pass


class IQueueRepository(ABC):
    """
    Queue repository interface with EXACT method signatures.
    All queue operations must go through implementations of this interface.

    Implementations should handle:
    - Authentication and credential management
    - Connection pooling and reuse
    - Retry logic and error handling
    - Message encoding/decoding
    - Logging and monitoring
    """

    @abstractmethod
    def send_message(self, queue_name: str, message: BaseModel) -> str:
        """
        Send a message to specified queue.

        Args:
            queue_name: Target queue name
            message: Pydantic model to send

        Returns:
            Message ID

        Raises:
            RuntimeError: If send fails after retries
        """
        pass

    @abstractmethod
    def receive_messages(
        self,
        queue_name: str,
        max_messages: int = 1,
        visibility_timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Receive messages from queue.

        Args:
            queue_name: Queue to receive from
            max_messages: Maximum messages to receive (1-32)
            visibility_timeout: How long to hide messages (seconds)

        Returns:
            List of message dictionaries with content and metadata
        """
        pass

    @abstractmethod
    def delete_message(self, queue_name: str, message_id: str, pop_receipt: str) -> bool:
        """
        Delete a message from queue.

        Args:
            queue_name: Queue containing the message
            message_id: Message ID
            pop_receipt: Pop receipt from receive operation

        Returns:
            True if deleted successfully
        """
        pass

    @abstractmethod
    def peek_messages(self, queue_name: str, max_messages: int = 1) -> List[Dict[str, Any]]:
        """
        Peek at messages without removing them.

        Args:
            queue_name: Queue to peek at
            max_messages: Maximum messages to peek (1-32)

        Returns:
            List of message dictionaries
        """
        pass

    @abstractmethod
    def get_queue_length(self, queue_name: str) -> int:
        """
        Get approximate number of messages in queue.

        Args:
            queue_name: Queue to check

        Returns:
            Approximate message count
        """
        pass

    @abstractmethod
    def clear_queue(self, queue_name: str) -> bool:
        """
        Clear all messages from queue.

        WARNING: This deletes ALL messages. Use with extreme caution.

        Args:
            queue_name: Queue to clear

        Returns:
            True if cleared successfully
        """
        pass


class IStageCompletionRepository(ABC):
    """
    Stage completion repository interface with EXACT method signatures.

    THIS IS THE CANONICAL DEFINITION - These signatures match the SQL functions.
    Provides atomic data operations for stage transitions.
    """

    @abstractmethod
    def complete_task_and_check_stage(
        self,
        task_id: str,  # MUST be 'task_id'
        job_id: str,   # MUST be 'job_id'
        stage: int,    # MUST be 'stage'
        result_data: Optional[Dict[str, Any]] = None,  # MUST be 'result_data'
        error_details: Optional[str] = None  # MUST be 'error_details'
    ) -> TaskCompletionResult:
        """
        Atomically complete task and check stage completion.

        SQL Function Signature:
        complete_task_and_check_stage(
            p_task_id VARCHAR(100),
            p_result_data JSONB,
            p_error_details TEXT
        )
        """
        pass

    @abstractmethod
    def advance_job_stage(
        self,
        job_id: str,           # MUST be 'job_id'
        current_stage: int,    # MUST be 'current_stage'
        stage_results: Dict[str, Any]  # MUST be 'stage_results' (plural!)
    ) -> StageAdvancementResult:
        """
        Advance job to next stage.

        CRITICAL: Only 3 parameters! No 'next_stage' parameter!

        SQL Function Signature:
        advance_job_stage(
            p_job_id VARCHAR(64),
            p_current_stage INTEGER,
            p_stage_results JSONB  -- Note: only 3 parameters!
        )
        """
        pass

    @abstractmethod
    def check_job_completion(
        self,
        job_id: str  # MUST be 'job_id'
    ) -> JobCompletionResult:
        """
        Check if job is complete.

        SQL Function Signature:
        check_job_completion(p_job_id VARCHAR(64))
        """
        pass


class IDuckDBRepository(ABC):
    """
    DuckDB repository interface for analytical operations.

    Enables dependency injection and testing/mocking of DuckDB operations.
    All DuckDB repositories must implement this interface.

    Key Features:
    - Serverless queries over Azure Blob Storage (NO DOWNLOAD!)
    - Spatial analytics with PostGIS-like ST_* functions
    - GeoParquet export for Gold tier data products
    - In-memory or persistent database connections
    """

    @abstractmethod
    def get_connection(self):
        """
        Get or create DuckDB connection with extensions loaded.

        Returns:
            DuckDB connection ready for queries
        """
        pass

    @abstractmethod
    def query(self, sql: str, parameters: Optional[List[Any]] = None):
        """
        Execute SQL query with optional parameters.

        Args:
            sql: SQL query string
            parameters: Optional list of parameter values for ? placeholders

        Returns:
            DuckDB relation (lazy evaluation)
        """
        pass

    @abstractmethod
    def query_to_df(self, sql: str, parameters: Optional[List[Any]] = None):
        """
        Execute SQL query and return pandas DataFrame.

        Args:
            sql: SQL query string
            parameters: Optional list of parameter values

        Returns:
            pandas DataFrame with query results
        """
        pass

    @abstractmethod
    def execute(self, sql: str, parameters: Optional[List[Any]] = None) -> None:
        """
        Execute SQL statement without returning results.

        Used for CREATE TABLE, INSERT, UPDATE, DELETE, etc.

        Args:
            sql: SQL statement
            parameters: Optional list of parameter values
        """
        pass

    @abstractmethod
    def read_parquet_from_blob(self, container: str, blob_pattern: str):
        """
        Read Parquet files from Azure Blob Storage (serverless query).

        NO DATA DOWNLOAD! DuckDB queries blob storage directly using
        the Azure extension. This is 10-100x faster than downloading.

        Args:
            container: Azure blob container name
            blob_pattern: Blob path with wildcards (e.g., "path/*.parquet")

        Returns:
            DuckDB relation (lazy evaluation)
        """
        pass

    @abstractmethod
    def export_geoparquet(self, data: Any, output_path: str) -> Dict[str, Any]:
        """
        Export data to GeoParquet format.

        Args:
            data: pandas DataFrame, GeoPandas GeoDataFrame, or DuckDB relation
            output_path: Output file path (.parquet)

        Returns:
            Dict with export metadata (path, size, row_count)
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Close DuckDB connection and cleanup resources.

        Note: Singleton instance will remain, but connection will be closed.
        Next get_connection() call will create a new connection.
        """
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Check DuckDB health and extension availability.

        Returns:
            Dict with health status, extensions, and connection info
        """
        pass


# ============================================================================
# PROTOCOL DEFINITIONS - For type checking
# ============================================================================

class RepositoryProtocol(Protocol):
    """
    Protocol combining all repository interfaces.
    Used for type checking that implementations provide all methods.
    """
    
    # From IJobRepository
    def create_job(self, job: JobRecord) -> bool: ...
    def get_job(self, job_id: str) -> Optional[JobRecord]: ...
    def update_job(self, job_id: str, updates: JobUpdateModel) -> bool: ...
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[JobRecord]: ...

    # From ITaskRepository
    def create_task(self, task: TaskRecord) -> bool: ...
    def get_task(self, task_id: str) -> Optional[TaskRecord]: ...
    def update_task(self, task_id: str, updates: TaskUpdateModel) -> bool: ...
    def list_tasks_for_job(self, job_id: str) -> List[TaskRecord]: ...
    
    # From ICompletionDetector
    def complete_task_and_check_stage(
        self, task_id: str, job_id: str, stage: int, 
        result_data: Optional[Dict[str, Any]] = None,
        error_details: Optional[str] = None
    ) -> TaskCompletionResult: ...
    
    def advance_job_stage(
        self, job_id: str, current_stage: int, stage_results: Dict[str, Any]
    ) -> StageAdvancementResult: ...
    
    def check_job_completion(self, job_id: str) -> JobCompletionResult: ...


# ============================================================================
# USAGE EXAMPLE - How implementations should use this
# ============================================================================

"""
Example implementation in repository_postgresql.py:

# Import the interfaces from this module
from interface_repository import (
    IJobRepository, ITaskRepository, ICompletionDetector,
    ParamNames
)
from core.models import StageAdvancementResult
from core.models.results import TaskCompletionResult, JobCompletionResult

class PostgreSQLJobRepository(IJobRepository):
    
    def advance_job_stage(
        self,
        job_id: str,
        current_stage: int, 
        stage_results: Dict[str, Any]  # MUST match ABC signature!
    ) -> StageAdvancementResult:
        
        # Build SQL with canonical parameter names
        sql = f'''
            SELECT {ParamNames.JOB_UPDATED}, 
                   {ParamNames.NEW_STAGE},
                   {ParamNames.IS_FINAL_STAGE}
            FROM app.advance_job_stage(%s, %s, %s)
        '''
        
        cursor.execute(sql, (job_id, current_stage, json.dumps(stage_results)))
        result = cursor.fetchone()
        
        # Return strongly-typed result
        return StageAdvancementResult(
            job_updated=result[0],
            new_stage=result[1],
            is_final_stage=result[2]
        )

This pattern makes parameter mismatches IMPOSSIBLE because:
1. ABC enforces exact method signatures
2. ParamNames provides single source of truth for names
3. Typed return values ensure consistent structure
4. Any deviation causes immediate type checker errors
"""