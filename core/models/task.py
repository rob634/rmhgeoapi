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
        'last_pulse', 'checkpoint_updated_at', 'execute_after',
        'execution_started_at', 'created_at', 'updated_at'
    )
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # Status tracking (Database-specific)
    # 15 MAR 2026: Default READY — tasks immediately available for worker pickup.
    # For V11 DAG, orchestrator creates as PENDING, promotes to READY when deps met.
    status: TaskStatus = Field(default=TaskStatus.READY, description="Current task status")

    # Data fields (Database-specific)
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Task execution results")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Task metadata")
    error_details: Optional[str] = Field(default=None, description="Error message if failed")

    # Execution tracking (Database-specific)
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    last_pulse: Optional[datetime] = Field(default=None, description="Last pulse timestamp (Docker long-running tasks)")
    next_stage_params: Optional[Dict[str, Any]] = Field(default=None, description="Parameters for next stage")

    # Checkpoint tracking (11 JAN 2026 - Docker worker resume support)
    checkpoint_phase: Optional[int] = Field(default=None, description="Current checkpoint phase number")
    checkpoint_data: Optional[Dict[str, Any]] = Field(default=None, description="Checkpoint state data (JSONB)")
    checkpoint_updated_at: Optional[datetime] = Field(default=None, description="When checkpoint was last saved")

    # Worker tracking (15 MAR 2026 - DB-polling migration)
    claimed_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Worker identity (hostname:pid) that claimed this task"
    )
    execute_after: Optional[datetime] = Field(
        default=None,
        description="Earliest time this task can be claimed (retry backoff)"
    )
    executed_by_app: Optional[str] = Field(
        default=None,
        description="APP_NAME of the app instance that processed this task"
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
        Validate task status transitions (DAG-standard lifecycle).

        15 MAR 2026: DB-polling migration — aligned with DAG executor standards.

        State machine:
            PENDING → READY → PROCESSING → COMPLETED
            PENDING → SKIPPED (when: condition false)
            PROCESSING → FAILED → PENDING_RETRY → READY (retry loop)
            PROCESSING → PENDING (janitor reset of stuck tasks)
            CANCELLED from any non-terminal state

        Args:
            new_status: The proposed new status

        Returns:
            True if transition is valid, False otherwise

        Examples:
            Normal lifecycle:
            READY → PROCESSING → COMPLETED

            DAG with dependencies (V11):
            PENDING → READY → PROCESSING → COMPLETED

            Failed task with retry:
            READY → PROCESSING → FAILED → PENDING_RETRY → READY → PROCESSING → COMPLETED
        """
        from core.logic.transitions import can_task_transition

        # Normalize current status to enum (handles string values from database)
        current = TaskStatus(self.status) if isinstance(self.status, str) else self.status
        return can_task_transition(current, new_status)


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