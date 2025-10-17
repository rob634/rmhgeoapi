# ============================================================================
# CLAUDE CONTEXT - CORE MODELS - RESULTS
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core models - Execution result data structures
# PURPOSE: Pure data models for execution results
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: TaskResult, StageResult, JobResult, StageAdvancementResult, TaskCompletionResult, JobCompletionResult
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: Various result models for atomic operations
# DEPENDENCIES: pydantic, datetime, typing
# SOURCE: Extracted from schema_base.py (data structure only)
# SCOPE: Result data models for task/stage/job completion
# VALIDATION: Field validation via Pydantic
# PATTERNS: Data model pattern, no business logic
# ENTRY_POINTS: from core.models.results import TaskResult, StageAdvancementResult
# ============================================================================

"""
Pure data models for execution results.

These models represent the results of job, stage, and task execution.
No business logic - just data structures.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator

from .enums import TaskStatus


class TaskResult(BaseModel):
    """
    Result from task execution.

    Pure data structure - success/failure logic is in core.logic.
    """

    task_id: str = Field(..., description="Task identifier")
    task_type: str = Field(..., description="Type of task")
    status: TaskStatus = Field(..., description="Task execution status")
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Task output data")
    error_details: Optional[str] = Field(default=None, description="Error message if failed")
    execution_time_ms: Optional[int] = Field(default=None, description="Execution time in milliseconds")
    timestamp: datetime = Field(..., description="Completion timestamp")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")

    @property
    def success(self) -> bool:
        """Check if task completed successfully."""
        return self.status == TaskStatus.COMPLETED

    class Config:
        """Pydantic configuration."""
        # Removed use_enum_values - enums should remain as enums for type safety
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class StageResultContract(BaseModel):
    """
    Contract for stage result data.

    Ensures consistent structure for stage results stored in the database.
    """

    stage: int = Field(..., ge=1, description="Stage number")
    status: str = Field(..., description="Stage completion status")
    task_count: int = Field(..., ge=0, description="Total tasks in stage")
    successful_count: int = Field(..., ge=0, description="Successful tasks")
    failed_count: int = Field(..., ge=0, description="Failed tasks")
    task_results: List[Dict[str, Any]] = Field(default_factory=list, description="Individual task results")
    aggregated_data: Optional[Dict[str, Any]] = Field(default=None, description="Aggregated stage data")
    error_summary: Optional[List[str]] = Field(default=None, description="Summary of errors")
    completion_time: Optional[datetime] = Field(default=None, description="Stage completion time")

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        valid_statuses = ['completed', 'failed', 'completed_with_errors', 'partial']
        if v not in valid_statuses:
            raise ValueError(f"Invalid status: {v}. Must be one of {valid_statuses}")
        return v

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class StageAdvancementResult(BaseModel):
    """
    Result from stage advancement operation.

    Returned by PostgreSQL function or stage advancement logic.
    """

    job_updated: bool = Field(..., description="Whether job was updated")
    new_stage: int = Field(..., description="New stage number")
    is_final_stage: bool = Field(..., description="Whether this is the final stage")
    all_tasks_complete: Optional[bool] = Field(default=None, description="Whether all tasks completed")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Advancement timestamp")

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TaskCompletionResult(BaseModel):
    """
    Result from PostgreSQL complete_task_and_check_stage() function.

    Represents the contract between SQL and Python layers.
    """
    task_updated: bool = Field(..., description="Whether task was updated")
    stage_complete: bool = Field(..., description="Whether stage is complete")
    job_id: Optional[str] = Field(default=None, description="Job ID")
    stage_number: Optional[int] = Field(default=None, description="Stage number")
    remaining_tasks: int = Field(default=0, description="Remaining tasks in stage")

    class Config:
        """Pydantic configuration."""
        extra = "forbid"


class JobCompletionResult(BaseModel):
    """
    Result from job completion check.

    Used to track final job state and aggregated results.
    """

    job_complete: bool = Field(..., description="Whether job is complete")
    final_stage: int = Field(..., description="Final stage number")
    total_tasks: int = Field(..., description="Total tasks across all stages")
    completed_tasks: int = Field(..., description="Number of completed tasks")
    task_results: Optional[Dict[str, Any]] = Field(default=None, description="Aggregated task results")

    class Config:
        """Pydantic configuration."""
        extra = "forbid"