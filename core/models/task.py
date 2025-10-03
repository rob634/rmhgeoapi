# ============================================================================
# CLAUDE CONTEXT - CORE MODELS - TASK
# ============================================================================
# CATEGORY: DATA MODELS - DATABASE ENTITIES
# PURPOSE: Pydantic model mapping to PostgreSQL table/database structure
# EPOCH: Shared by all epochs (database schema)
# EXPORTS: TaskRecord, TaskDefinition - Pydantic models for task data
# INTERFACES: Inherits from TaskData (core.contracts)
# PYDANTIC_MODELS: TaskRecord (adds persistence fields), TaskDefinition
# DEPENDENCIES: pydantic, datetime, typing, core.contracts.TaskData
# SOURCE: Extracted from schema_base.py, refactored to inherit from TaskData
# SCOPE: Task record and definition data models for DATABASE boundary
# VALIDATION: Field validation via Pydantic (inherits from TaskData)
# PATTERNS: Data model pattern, Inheritance (TaskData), no business logic
# ENTRY_POINTS: from core.models.task import TaskRecord, TaskDefinition
# ARCHITECTURE: TaskRecord = TaskData + Database persistence fields
# ============================================================================

"""
Task Database Models - Persistence Boundary

This module defines TaskRecord, which represents a task in the PostgreSQL database.
It inherits from TaskData (core.contracts) and adds persistence-specific fields:
- status, result_data, error_details (execution tracking)
- retry_count, heartbeat (reliability)
- created_at, updated_at (audit trail)

Architecture:
    TaskData (core.contracts) - Base contract with essential task properties
         ↓ inherits
    TaskRecord (this file) - Database boundary specialization

The "Task" conceptual entity is composed of:
    TaskRecord (data) + TaskExecutor (behavior) = "Task" entity

See core/contracts/__init__.py for full architecture explanation.

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

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
    - heartbeat: Last heartbeat timestamp
    - next_stage_params: Parameters for next stage tasks
    - created_at, updated_at: Audit timestamps

    This is the DATA half of the "Task" entity.
    The BEHAVIOR half is TaskExecutor (services/task.py).
    They collaborate via composition in TaskExecutionService.
    """

    # Status tracking (Database-specific)
    status: TaskStatus = Field(default=TaskStatus.QUEUED, description="Current task status")

    # Data fields (Database-specific)
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Task execution results")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Task metadata")
    error_details: Optional[str] = Field(default=None, description="Error message if failed")

    # Execution tracking (Database-specific)
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    heartbeat: Optional[datetime] = Field(default=None, description="Last heartbeat timestamp")
    next_stage_params: Optional[Dict[str, Any]] = Field(default=None, description="Parameters for next stage")

    # Timestamps (Database-specific)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """
        Validate task status transitions.

        Tasks follow linear progression (no cycling):
        - QUEUED → PROCESSING → COMPLETED/FAILED
        - Terminal states → Any (retry/recovery)

        Unlike jobs, tasks don't cycle between states. Each task executes once
        per stage, following a simple linear lifecycle.

        Args:
            new_status: The proposed new status

        Returns:
            True if transition is valid, False otherwise

        Examples:
            Normal task lifecycle:
            QUEUED → PROCESSING → COMPLETED

            Failed task with retry:
            QUEUED → PROCESSING → FAILED → QUEUED → PROCESSING → COMPLETED
        """
        # Normalize current status to enum (handles string values from database)
        current = TaskStatus(self.status) if isinstance(self.status, str) else self.status

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

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskDefinition(BaseModel):
    """
    Pure data model for task definition during orchestration.

    This is a lightweight model used when creating tasks dynamically.
    It contains the minimal information needed to create a TaskRecord.
    """

    task_id: str = Field(..., description="Unique task identifier")
    task_type: str = Field(..., description="Type of task to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata")
    parent_job_id: Optional[str] = Field(default=None, description="Parent job ID")
    job_type: Optional[str] = Field(default=None, description="Job type")
    stage: Optional[int] = Field(default=None, description="Stage number")
    task_index: Optional[str] = Field(default=None, description="Task index")

    class Config:
        """Pydantic configuration."""
        extra = "forbid"  # Don't allow extra fields