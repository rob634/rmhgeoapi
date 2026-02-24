# ============================================================================
# TASK DATABASE MODELS - PERSISTENCE BOUNDARY
# ============================================================================
# STATUS: Core - TaskRecord and TaskDefinition models
# PURPOSE: Database representation of tasks with execution and audit fields
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Task Database Models - Persistence Boundary.

Defines TaskRecord for PostgreSQL database representation.
Inherits from TaskData and adds persistence-specific fields.

Architecture:
    TaskData (core.contracts) - Base contract
    TaskRecord (this file) - Database boundary specialization

Exports:
    TaskRecord: Task database model with persistence fields
    TaskDefinition: Lightweight orchestration model for task creation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from core.contracts import TaskData
from .enums import TaskStatus


class TaskRecord(TaskData):
    """
    Database representation of a task.

    Inherits essential task properties from TaskData:
    - task_id, parent_job_id, job_type, task_type, stage, task_index, parameters

    Adds persistence-specific fields:
    - status: Current execution status
    - result_data: Task execution results
    - metadata: Additional task metadata
    - error_details: Error message if failed
    - retry_count: Number of retry attempts
    - last_pulse: Last pulse timestamp (for long-running Docker tasks)
    - next_stage_params: Parameters for next stage tasks
    - created_at, updated_at: Audit timestamps

    This is the DATA half of the "Task" entity.
    The BEHAVIOR half is TaskExecutor (services/task.py).
    They collaborate via composition in TaskExecutionService.
    """

    model_config = ConfigDict()

    @field_serializer(
        'last_pulse', 'checkpoint_updated_at', 'execution_started_at',
        'created_at', 'updated_at'
    )
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # Status tracking (Database-specific)
    # 16 DEC 2025: Default changed from QUEUED to PENDING
    # PENDING = task created, message sent but not yet confirmed by trigger
    # QUEUED = trigger confirmed message receipt
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current task status")

    # Data fields (Database-specific)
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Task execution results")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Task metadata")
    error_details: Optional[str] = Field(default=None, description="Error message if failed")

    # Execution tracking (Database-specific)
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    last_pulse: Optional[datetime] = Field(default=None, description="Last pulse timestamp (Docker long-running tasks)")
    next_stage_params: Optional[Dict[str, Any]] = Field(default=None, description="Parameters for next stage")

    # Checkpoint tracking (11 JAN 2026 - Docker worker resume support)
    # Enables resume from checkpoint if Docker task is interrupted
    checkpoint_phase: Optional[int] = Field(default=None, description="Current checkpoint phase number")
    checkpoint_data: Optional[Dict[str, Any]] = Field(default=None, description="Checkpoint state data (JSONB)")
    checkpoint_updated_at: Optional[datetime] = Field(default=None, description="When checkpoint was last saved")

    # Multi-app tracking (07 DEC 2025 - Multi-Function App Architecture)
    target_queue: Optional[str] = Field(
        default=None,
        description="Service Bus queue task was routed to (raster-tasks, vector-tasks, etc)"
    )
    executed_by_app: Optional[str] = Field(
        default=None,
        description="APP_NAME of the Function App that processed this task"
    )
    execution_started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when task processing began (for duration tracking)"
    )

    # Timestamps (Database-specific)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """
        Validate task status transitions.

        Tasks follow linear progression (no cycling):
        - PENDING → QUEUED (trigger confirms message receipt) [16 DEC 2025]
        - QUEUED → PROCESSING → COMPLETED/FAILED
        - Terminal states → Any (retry/recovery)

        Unlike jobs, tasks don't cycle between states. Each task executes once
        per stage, following a simple linear lifecycle.

        Args:
            new_status: The proposed new status

        Returns:
            True if transition is valid, False otherwise

        Examples:
            Normal task lifecycle (16 DEC 2025):
            PENDING → QUEUED → PROCESSING → COMPLETED

            Failed task with retry:
            PENDING → QUEUED → PROCESSING → FAILED → QUEUED → PROCESSING → COMPLETED
        """
        # Normalize current status to enum (handles string values from database)
        current = TaskStatus(self.status) if isinstance(self.status, str) else self.status

        # 16 DEC 2025: PENDING transitions (message confirmation)
        if current == TaskStatus.PENDING and new_status in [
            TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED
        ]:
            return True

        # Standard task lifecycle
        if current == TaskStatus.QUEUED and new_status == TaskStatus.PROCESSING:
            return True
        if current == TaskStatus.PROCESSING and new_status in [
            TaskStatus.COMPLETED, TaskStatus.FAILED
        ]:
            return True

        # Allow retry transitions from terminal states
        if current in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            return True  # Can restart from terminal states

        return False


class TaskDefinition(BaseModel):
    """
    Pure data model for task definition during orchestration.

    This is a lightweight model used when creating tasks dynamically.
    It contains the minimal information needed to create a TaskRecord.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., description="Unique task identifier")
    task_type: str = Field(..., description="Type of task to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata")
    parent_job_id: Optional[str] = Field(default=None, description="Parent job ID")
    job_type: Optional[str] = Field(default=None, description="Job type")
    stage: Optional[int] = Field(default=None, description="Stage number")
    task_index: Optional[str] = Field(default=None, description="Task index")