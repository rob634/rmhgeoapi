"""
Queue Message Schemas - Transport Boundary.

Message formats for Azure Storage Queues and Service Bus.
Inherits from TaskData/JobData and adds transport-specific fields.

Architecture:
    TaskData → TaskQueueMessage (adds transport fields)
    JobData → JobQueueMessage (adds transport fields)

Exports:
    JobQueueMessage: Job message for queue transport
    TaskQueueMessage: Task message for queue transport
"""

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict

from core.contracts import TaskData, JobData


# ============================================================================
# QUEUE MESSAGE MODELS
# ============================================================================

class JobQueueMessage(JobData):
    """
    Job queue message for Azure Storage Queue and Service Bus.

    Inherits essential job properties from JobData:
    - job_id, job_type, parameters

    Adds transport-specific fields:
    - stage: Current stage being processed
    - stage_results: Results from previous stages
    - retry_count: Message delivery attempts
    - timestamp: Message creation time

    This is the DATA representation for jobs in motion (queue messages).
    The BEHAVIOR is defined by Workflow (services/workflow.py).
    They collaborate via composition in CoreMachine.
    """

    # Transport-specific fields
    stage: int = Field(..., ge=1, le=100, description="Current stage number")
    stage_results: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Results from previous stages")
    retry_count: int = Field(default=0, ge=0, le=10, description="Number of retry attempts")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message creation time")

    correlation_id: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Correlation ID for request tracing (optional)"
    )
    """
    Optional correlation ID for tracing job execution flows across the system.

    This field supports three distinct tracing patterns at different architectural layers:

    1. **Job Submission Tracing** (Job Classes):
       - Generated when job is first submitted (stage 1)
       - Example: jobs/hello_world.py line 285
       - Purpose: Track this specific job submission through entire lifecycle

    2. **Stage Advancement Tracing** (CoreMachine):
       - Generated when CoreMachine advances job to next stage
       - Example: core/machine.py line 1044
       - Purpose: Track which CoreMachine execution created this job message

    3. **Function Invocation Tracing** (Azure Functions):
       - Generated at trigger level for log filtering
       - Example: function_app.py line 1714
       - Purpose: Filter Application Insights logs for single function execution
       - Format: `[abc12345]` prefix in log messages

    **Relationship to Platform Layer**:
    This is separate from Platform API's X-Correlation-Id HTTP header:
    - Platform: External client request tracking (HTTP header)
    - CoreMachine: Internal job/task execution tracking (queue message field)

    **When to Use**:
    - Optional for most job submissions (defaults to None)
    - Automatically set by CoreMachine during stage advancement
    - Useful for debugging multi-stage workflows

    **Application Insights Queries**:
    ```kql
    // Find all logs for specific function invocation
    traces | where message contains '[abc12345]' | order by timestamp asc

    // Find job messages created by specific CoreMachine execution
    traces
    | where customDimensions.correlation_id == 'abc12345'
    | project timestamp, message
    ```

    Examples:
        Job submission with correlation_id (jobs/hello_world.py pattern):
            >>> import uuid
            >>> msg = JobQueueMessage(
            ...     job_id="abc123",
            ...     job_type="hello_world",
            ...     stage=1,
            ...     parameters={"message": "test"},
            ...     correlation_id=str(uuid.uuid4())[:8]
            ... )
            >>> msg.correlation_id
            'a1b2c3d4'

        Stage advancement with correlation_id (core/machine.py pattern):
            >>> next_message = JobQueueMessage(
            ...     job_id=job_id,
            ...     job_type=job_type,
            ...     stage=2,
            ...     parameters=params,
            ...     correlation_id=str(uuid.uuid4())[:8]
            ... )
            >>> # Logs: "[STAGE_ADVANCE] JobQueueMessage created (correlation_id: a1b2c3d4)"

        Job submission without correlation_id (also valid):
            >>> msg = JobQueueMessage(
            ...     job_id="xyz789",
            ...     job_type="process_raster",
            ...     stage=1,
            ...     parameters={"blob_name": "test.tif"}
            ... )
            >>> msg.correlation_id is None
            True

    See Also:
        - BUG_REPORT_CORRELATION_ID.md: Why this field was added
        - DEBUG_LOGGING_CHECKPOINTS.md: How to use for debugging
        - PLATFORM_OPENAPI_RESEARCH_FINDINGS.md: Platform layer X-Correlation-Id
    """

    model_config = ConfigDict(validate_assignment=True)


class StageCompleteMessage(BaseModel):
    """
    Stage completion signal from worker to platform.

    Sent by worker apps (worker_raster, worker_vector) after completing
    all tasks in a stage, signaling the platform to advance to next stage.

    This message is sent to the jobs queue so the platform can:
    1. Detect stage completion
    2. Advance the job to the next stage
    3. Create tasks for the next stage

    Added: 10 DEC 2025 - Multi-App Architecture
    """
    message_type: str = Field(default="stage_complete", description="Message type identifier")
    job_id: str = Field(..., description="Job ID that completed a stage")
    job_type: str = Field(..., description="Type of job")
    completed_stage: int = Field(..., ge=1, description="Stage number that completed")
    completed_at: str = Field(..., description="ISO format timestamp of completion")
    completed_by_app: str = Field(..., description="App name that processed the tasks")
    correlation_id: str = Field(..., max_length=16, description="Correlation ID for tracing")

    model_config = ConfigDict(validate_assignment=True)


class TaskQueueMessage(TaskData):
    """
    Task queue message for Azure Storage Queue and Service Bus.

    Inherits essential task properties from TaskData:
    - task_id, parent_job_id, job_type, task_type, stage, task_index, parameters

    Adds transport-specific fields:
    - parent_task_id: Optional predecessor task ID
    - retry_count: Message delivery attempts
    - timestamp: Message creation time

    This is the DATA representation for tasks in motion (queue messages).
    The BEHAVIOR is defined by TaskExecutor (services/task.py).
    They collaborate via composition in TaskExecutionService.
    """

    # Transport-specific fields
    parent_task_id: Optional[str] = Field(
        None,
        max_length=100,
        description="For explicit handoff from previous stage"
    )
    retry_count: int = Field(default=0, ge=0, le=10, description="Number of retry attempts")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message creation time")

    model_config = ConfigDict(validate_assignment=True)


# Export all public classes
__all__ = [
    'JobQueueMessage',
    'TaskQueueMessage',
    'StageCompleteMessage',
]