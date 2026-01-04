# ============================================================================
# EXECUTION CONTEXT DATA MODELS
# ============================================================================
# STATUS: Core - Pure data structures for execution context
# PURPOSE: Job, Stage, and Task execution context without business logic
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Execution Context Data Models.

Represents context in which jobs, stages, and tasks execute.
No business logic - pure data structures.

Exports:
    JobExecutionContext: Context for job execution
    StageExecutionContext: Context for stage execution
    TaskExecutionContext: Context for task execution
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .enums import JobStatus, TaskStatus


class JobExecutionContext(BaseModel):
    """
    Context for job execution.

    Contains all information needed during job processing.
    Business logic for stage results is in core.logic.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., description="Job identifier")
    job_type: str = Field(..., description="Type of job")
    current_stage: int = Field(..., ge=1, description="Current stage number")
    total_stages: int = Field(..., ge=1, description="Total number of stages")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Job parameters")
    stage_results: Dict[str, Any] = Field(default_factory=dict, description="Results from completed stages")
    task_results: List[Any] = Field(default_factory=list, description="All task results for job completion")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Job metadata")

    @field_validator('job_id')
    @classmethod
    def validate_job_id_format(cls, v):
        if not v or not v.strip():
            raise ValueError("job_id cannot be empty")
        return v


class StageExecutionContext(BaseModel):
    """
    Context for stage execution.

    Contains information about the current stage being processed.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., description="Job identifier")
    stage_number: int = Field(..., ge=1, description="Current stage number")
    total_tasks: int = Field(default=0, ge=0, description="Total tasks in stage")
    completed_tasks: int = Field(default=0, ge=0, description="Completed tasks count")
    failed_tasks: int = Field(default=0, ge=0, description="Failed tasks count")
    task_results: List[Dict[str, Any]] = Field(default_factory=list, description="Task results")
    stage_parameters: Optional[Dict[str, Any]] = Field(default=None, description="Stage-specific parameters")


class TaskExecutionContext(BaseModel):
    """
    Context for task execution.

    Contains all information available to a task during execution.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(..., description="Task identifier")
    parent_job_id: str = Field(..., description="Parent job ID")
    job_type: str = Field(..., description="Job type")
    task_type: str = Field(..., description="Task type")
    stage: int = Field(..., ge=1, description="Stage number")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    retry_count: int = Field(default=0, ge=0, description="Current retry count")
    max_retries: int = Field(default=3, ge=0, description="Maximum retries allowed")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Task metadata")
    predecessor_results: Optional[Dict[str, Any]] = Field(default=None, description="Results from predecessor")