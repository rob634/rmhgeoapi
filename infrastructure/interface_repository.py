"""
Repository Abstract Base Classes - Single Point of Truth.

Enforces exact method signatures across all repository implementations,
preventing parameter name mismatches. All parameter names, return types,
and method signatures are defined here and nowhere else.

Philosophy: "Define once, enforce everywhere"

Exports:
    IJobRepository: Job repository interface
    ITaskRepository: Task repository interface
    IQueueRepository: Queue repository interface
    IStageCompletionRepository: Stage completion interface
    IDuckDBRepository: DuckDB repository interface
    IDataFactoryRepository: Azure Data Factory interface
    ParamNames: Canonical parameter name constants
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
# DATA FACTORY REPOSITORY INTERFACE (29 NOV 2025)
# ============================================================================

class IDataFactoryRepository(ABC):
    """
    Azure Data Factory repository interface for pipeline orchestration.

    Enables triggering ADF pipelines from CoreMachine jobs,
    monitoring execution status, and retrieving run outputs.

    Key Use Cases:
    - Database-to-database ETL operations
    - Production data promotion (staging → business)
    - Scheduled/recurring data pipelines
    - Cross-environment data movement

    Implementation Notes:
    - Uses DefaultAzureCredential for authentication
    - Follows singleton pattern for credential reuse
    - All operations are logged for Application Insights
    """

    @abstractmethod
    def trigger_pipeline(
        self,
        pipeline_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        reference_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Trigger an ADF pipeline execution.

        Args:
            pipeline_name: Name of the pipeline to execute
            parameters: Pipeline parameters to pass (e.g., table_name, job_id)
            reference_name: Optional correlation ID for tracing (usually job_id)

        Returns:
            Dict containing:
            - run_id: Pipeline run identifier
            - pipeline_name: Name of triggered pipeline
            - status: Initial status (usually "Queued")

        Raises:
            RuntimeError: If pipeline trigger fails
            ValueError: If pipeline_name not found
        """
        pass

    @abstractmethod
    def get_pipeline_run_status(
        self,
        run_id: str
    ) -> Dict[str, Any]:
        """
        Get current status of a pipeline run.

        Args:
            run_id: Pipeline run ID from trigger_pipeline

        Returns:
            Dict containing:
            - run_id: Pipeline run identifier
            - pipeline_name: Name of pipeline
            - status: Current status (Queued, InProgress, Succeeded, Failed, Cancelled)
            - message: Status message or error details
            - start_time: Run start timestamp (ISO format)
            - end_time: Run end timestamp if completed (ISO format)
            - duration_ms: Elapsed time in milliseconds

        Raises:
            RuntimeError: If status check fails
        """
        pass

    @abstractmethod
    def wait_for_pipeline_completion(
        self,
        run_id: str,
        timeout_seconds: int = 3600,
        poll_interval_seconds: int = 30
    ) -> Dict[str, Any]:
        """
        Block until pipeline completes or times out.

        Polls pipeline status at regular intervals until a terminal state
        (Succeeded, Failed, Cancelled) is reached or timeout expires.

        Args:
            run_id: Pipeline run ID from trigger_pipeline
            timeout_seconds: Maximum wait time (default: 1 hour)
            poll_interval_seconds: Polling frequency (default: 30 seconds)

        Returns:
            Final pipeline run status (same format as get_pipeline_run_status)

        Raises:
            TimeoutError: If pipeline doesn't complete within timeout
            RuntimeError: If polling fails
        """
        pass

    @abstractmethod
    def get_activity_runs(
        self,
        run_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get individual activity runs within a pipeline.

        Useful for debugging pipeline failures or understanding
        which step of the pipeline is currently executing.

        Args:
            run_id: Pipeline run ID

        Returns:
            List of activity run dictionaries containing:
            - activity_name: Name of the activity
            - activity_type: Type (Copy, Lookup, StoredProcedure, etc.)
            - status: Activity status
            - start_time: Activity start timestamp
            - end_time: Activity end timestamp
            - duration_ms: Elapsed time
            - error: Error details if failed

        Raises:
            RuntimeError: If retrieval fails
        """
        pass

    @abstractmethod
    def list_pipelines(self) -> List[Dict[str, Any]]:
        """
        List all pipelines in the Data Factory.

        Returns:
            List of pipeline info dictionaries containing:
            - name: Pipeline name
            - description: Pipeline description
            - parameters: Pipeline parameters schema

        Raises:
            RuntimeError: If listing fails
        """
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """
        Check ADF connectivity and configuration.

        Returns:
            Dict containing:
            - status: "healthy" or "unhealthy"
            - factory_name: Configured factory name
            - subscription_id: Azure subscription ID
            - pipeline_count: Number of pipelines available
            - error: Error message if unhealthy
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