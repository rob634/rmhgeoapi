# ============================================================================
# CLAUDE CONTEXT - SCHEMA
# ============================================================================
# EPOCH: SHARED - BOTH EPOCHS
# STATUS: Used by Epoch 3 and Epoch 4
# NOTE: Careful migration required
# ⚠️ LEGACY ARCHITECTURE - DO NOT USE IN NEW CODE ⚠️
# STATUS: Replaced by core/schema/updates.py (30 SEP 2025)
# USED BY: Legacy repositories, controller_service_bus_hello.py
# NEW CODE: Use `from core.schema import TaskUpdateModel, JobUpdateModel` instead
# NOTE: Legacy version imports enums from schema_base; new version uses core.models
# ============================================================================
# PURPOSE: Strongly-typed Pydantic models for repository update operations
# EXPORTS: TaskUpdateModel, JobUpdateModel, StageCompletionUpdateModel
# INTERFACES: None - pure data models for contract enforcement
# PYDANTIC_MODELS: TaskUpdateModel, JobUpdateModel, StageCompletionUpdateModel
# DEPENDENCIES: pydantic, typing, datetime, enum
# SOURCE: Controller and service layers creating updates
# SCOPE: Repository layer contract enforcement
# VALIDATION: Pydantic automatic validation with enum handling
# PATTERNS: Data Transfer Object, Contract Enforcement, Type Safety
# ENTRY_POINTS: from schema_updates import TaskUpdateModel, JobUpdateModel
# INDEX:
#   - Line 46: TaskUpdateModel - Task update contract
#   - Line 74: JobUpdateModel - Job update contract
#   - Line 98: StageCompletionUpdateModel - Stage completion update contract
# ============================================================================

"""
Repository Update Models - Contract Enforcement

This module provides strongly-typed Pydantic models for all repository
update operations, replacing Dict[str, Any] with type-safe contracts.

These models ensure:
1. Type safety at repository boundaries
2. Automatic enum to string conversion
3. Clear contracts about what fields can be updated
4. Validation of update parameters

Critical for the clean architecture that replaces BaseController's
accidental type protection with intentional contract enforcement.

Author: Robert and Geospatial Claude Legion
Date: 27 SEP 2025
"""

from typing import Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum

# Import enums from schema_base
from schema_base import TaskStatus, JobStatus, StageStatus


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


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

"""
Example usage in controllers and services:

from schema_updates import TaskUpdateModel, JobUpdateModel

# Creating a task update
task_update = TaskUpdateModel(
    status=TaskStatus.PROCESSING,  # Pass enum, not string!
    heartbeat=datetime.utcnow()
)

# Repository receives type-safe model
task_repo.update_task(task_id, task_update)

# Creating a job update with results
job_update = JobUpdateModel(
    status=JobStatus.COMPLETED,
    stage=2,
    stage_results={"files_processed": 100},
    result_data={"total_time": 45.3}
)

# Type safety enforced at boundary
job_repo.update_job(job_id, job_update)

# Pydantic prevents invalid updates
try:
    bad_update = TaskUpdateModel(
        status="invalid_status"  # TypeError: not a valid TaskStatus
    )
except ValidationError as e:
    print(f"Contract violation: {e}")
"""