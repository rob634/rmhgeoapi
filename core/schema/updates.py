# ============================================================================
# REPOSITORY UPDATE MODELS - CONTRACT ENFORCEMENT
# ============================================================================
# STATUS: Core - Type-safe repository update contracts
# PURPOSE: Replace Dict[str,Any] with strongly-typed update models
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Repository Update Models - Contract Enforcement.

Strongly-typed Pydantic models for repository update operations,
replacing Dict[str, Any] with type-safe contracts.

Benefits:
    - Type safety at repository boundaries
    - Automatic enum to string conversion
    - Clear contracts about updatable fields
    - Validation of update parameters

Exports:
    TaskUpdateModel: Task update contract
    JobUpdateModel: Job update contract
    StageCompletionUpdateModel: Stage completion update contract
"""

from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# Import enums from core.models (not schema_base)
from ..models import TaskStatus, JobStatus, StageStatus


class TaskUpdateModel(BaseModel):
    """
    Strongly typed task update contract.

    All task repository update methods must use this model
    instead of Dict[str, Any] to ensure type safety.

    Pydantic automatically handles enum to string conversion
    when use_enum_values is True.
    """

    model_config = ConfigDict(
        use_enum_values=True,  # Auto-convert enums to their string values
        validate_assignment=True,  # Validate on field assignment
        extra='forbid'  # Prevent unknown fields
    )

    status: Optional[TaskStatus] = None
    result_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    heartbeat: Optional[datetime] = None
    retry_count: Optional[int] = Field(None, ge=0, le=10)
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self, exclude_unset: bool = True) -> Dict[str, Any]:
        """Convert to dictionary for SQL operations."""
        return self.model_dump(exclude_unset=exclude_unset, mode='json')


class JobUpdateModel(BaseModel):
    """
    Strongly typed job update contract.

    All job repository update methods must use this model
    instead of Dict[str, Any] to ensure type safety.
    """

    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        extra='forbid'
    )

    status: Optional[JobStatus] = None
    stage: Optional[int] = Field(None, ge=1, le=100)
    stage_results: Optional[Dict[str, Any]] = None
    result_data: Optional[Dict[str, Any]] = None
    error_details: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self, exclude_unset: bool = True) -> Dict[str, Any]:
        """Convert to dictionary for SQL operations."""
        return self.model_dump(exclude_unset=exclude_unset, mode='json')


class StageCompletionUpdateModel(BaseModel):
    """
    Strongly typed stage completion update contract.

    Used for updating stage_completion records in the database.
    """

    model_config = ConfigDict(
        use_enum_values=True,
        validate_assignment=True,
        extra='forbid'
    )

    status: Optional[StageStatus] = None
    completed_at: Optional[datetime] = None
    completed_tasks: Optional[int] = Field(None, ge=0)
    failed_tasks: Optional[int] = Field(None, ge=0)

    def to_dict(self, exclude_unset: bool = True) -> Dict[str, Any]:
        """Convert to dictionary for SQL operations."""
        return self.model_dump(exclude_unset=exclude_unset, mode='json')


# Export all public classes
__all__ = [
    'TaskUpdateModel',
    'JobUpdateModel',
    'StageCompletionUpdateModel'
]