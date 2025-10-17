# ============================================================================
# CLAUDE CONTEXT - CORE MODELS - CONTEXT
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core models - Execution context data structures
# PURPOSE: Pure data models for execution contexts
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: JobExecutionContext, StageExecutionContext, TaskExecutionContext
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: Various execution context models
# DEPENDENCIES: pydantic, datetime, typing
# SOURCE: Extracted from schema_base.py (data structure only)
# SCOPE: Execution context data models
# VALIDATION: Field validation via Pydantic
# PATTERNS: Data model pattern, no business logic
# ENTRY_POINTS: from core.models.context import JobExecutionContext
# ============================================================================

"""
Pure data models for execution contexts.

These models represent the context in which jobs, stages, and tasks execute.
No business logic - just data structures.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field, field_validator

from .enums import JobStatus, TaskStatus


class JobExecutionContext(BaseModel):
    """
    Context for job execution.

    Contains all information needed during job processing.
    Business logic for stage results is in core.logic.
    """

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

    class Config:
        """Pydantic configuration."""
        extra = "forbid"


class StageExecutionContext(BaseModel):
    """
    Context for stage execution.

    Contains information about the current stage being processed.
    """

    job_id: str = Field(..., description="Job identifier")
    stage_number: int = Field(..., ge=1, description="Current stage number")
    total_tasks: int = Field(default=0, ge=0, description="Total tasks in stage")
    completed_tasks: int = Field(default=0, ge=0, description="Completed tasks count")
    failed_tasks: int = Field(default=0, ge=0, description="Failed tasks count")
    task_results: List[Dict[str, Any]] = Field(default_factory=list, description="Task results")
    stage_parameters: Optional[Dict[str, Any]] = Field(default=None, description="Stage-specific parameters")

    class Config:
        """Pydantic configuration."""
        extra = "forbid"


class TaskExecutionContext(BaseModel):
    """
    Context for task execution.

    Contains all information available to a task during execution.
    """

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

    class Config:
        """Pydantic configuration."""
        extra = "forbid"