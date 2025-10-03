# ============================================================================
# CLAUDE CONTEXT - CORE CONTRACTS
# ============================================================================
# CATEGORY: DATA CONTRACTS - BASE DEFINITIONS
# PURPOSE: Base Pydantic models that define the essential data structure of entities
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core architectural foundation
#
# EXPORTS: TaskData, JobData - Base contracts for data hierarchy
# INTERFACES: Pydantic BaseModel
# PYDANTIC_MODELS: TaskData (task identity), JobData (job identity)
# DEPENDENCIES: pydantic, typing, datetime
# SOURCE: Extracted common fields from TaskRecord/TaskQueueMessage duplication
# SCOPE: Foundation for all task/job data representations
# VALIDATION: Field validation via Pydantic (inherited by specializations)
# PATTERNS: Data Contract Pattern, DRY principle, Composition over Inheritance
# ENTRY_POINTS:
#   - from core.contracts import TaskData, JobData
#   - Inherited by TaskRecord, TaskQueueMessage, JobRecord, JobQueueMessage
#
# ARCHITECTURE PHILOSOPHY:
#   "Task" as a conceptual entity is composed of TWO orthogonal concerns:
#
#   1. DATA (this file) - TaskData defines "what a task IS"
#      - Identity: task_id, parent_job_id
#      - Classification: job_type, task_type, stage
#      - Instructions: parameters
#
#   2. BEHAVIOR (services/task.py) - TaskExecutor defines "what a task DOES"
#      - Abstract method: execute(params) -> result
#      - Concrete implementations: ValidateRasterTask, GreetTask, etc.
#
#   These are NOT combined via inheritance (no God class)!
#   They collaborate via composition in TaskExecutionService:
#
#   ```python
#   # The "Task" entity emerges from collaboration:
#   task_record = TaskRecord(task_type="greet", params={...})  # DATA
#   executor = TASK_REGISTRY[task_record.task_type]()          # BEHAVIOR
#   result = executor.execute(task_record.parameters)          # COMPOSITION
#   ```
#
#   The task_type field is the BRIDGE linking data to behavior.
#
# WHY SEPARATE DATA AND BEHAVIOR?
#   ✅ Can swap data format without touching business logic
#   ✅ Can test behavior without database/queue infrastructure
#   ✅ Prevents tight coupling (Single Responsibility Principle)
#   ✅ TaskData crosses boundaries (DB, Queue) - behavior stays internal
#
# BOUNDARY SPECIALIZATIONS:
#   - TaskRecord(TaskData) - Adds persistence fields (status, timestamps, results)
#   - TaskQueueMessage(TaskData) - Adds transport fields (retry_count, timestamp)
#
# INDEX:
#   - TaskData: line 85
#   - JobData: line 135
# ============================================================================

"""
Core Data Contracts - Base Pydantic Models

This module defines the foundational data structures for Task and Job entities.
These base classes capture the ESSENTIAL identity and classification of entities,
while specialized subclasses add boundary-specific fields.

Philosophy: "Favor composition over inheritance"
- Data (this file) and Behavior (services/*.py) are separate pillars
- They meet in the middle via composition (TaskExecutionService)
- The conceptual entity emerges from their collaboration

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from datetime import datetime
from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# TASK DATA CONTRACT
# ============================================================================

class TaskData(BaseModel):
    """
    Base data contract for all Task representations.

    Defines the ESSENTIAL properties that identify and classify a task:
    - Identity: task_id, parent_job_id
    - Classification: job_type, task_type, stage, task_index
    - Instructions: parameters

    This is NOT the complete "Task" entity - it's the DATA half.
    The BEHAVIOR half is defined by TaskExecutor (ABC) in services/task.py.

    The conceptual "Task" entity = TaskData + TaskExecutor (composition)

    Specialized boundaries inherit from this:
    - TaskRecord: Adds persistence fields (status, result_data, timestamps)
    - TaskQueueMessage: Adds transport fields (retry_count, timestamp)

    Example:
        ```python
        # Base contract captures essentials:
        task_data = TaskData(
            task_id="abc123-s1-0",
            parent_job_id="def456...",
            job_type="hello_world",
            task_type="greet",
            stage=1,
            parameters={"message": "Hello"}
        )

        # Specialization adds boundary-specific fields:
        task_record = TaskRecord(
            **task_data.model_dump(),
            status=TaskStatus.QUEUED,  # Database-specific
            created_at=datetime.now()   # Database-specific
        )
        ```
    """

    # Identity
    task_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique task identifier (format: {job_id[:8]}-s{stage}-{index})"
    )

    parent_job_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Parent job ID (SHA256 hash)"
    )

    # Classification
    job_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Type of parent job (links to workflow)"
    )

    task_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Type of task (links to TaskExecutor via registry)"
    )

    stage: int = Field(
        ...,
        ge=1,
        description="Stage number this task belongs to"
    )

    task_index: str = Field(
        default="0",
        max_length=50,
        description="Semantic index (e.g., 'tile_x5_y10', '0', 'chunk_A')"
    )

    # Instructions
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Task input parameters (passed to TaskExecutor.execute())"
    )

    @field_validator('task_type')
    @classmethod
    def normalize_task_type(cls, v: str) -> str:
        """Normalize task type to lowercase with underscores."""
        return v.lower().replace('-', '_')

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# ============================================================================
# JOB DATA CONTRACT
# ============================================================================

class JobData(BaseModel):
    """
    Base data contract for all Job representations.

    Defines the ESSENTIAL properties that identify and classify a job:
    - Identity: job_id (SHA256 of parameters for idempotency)
    - Classification: job_type
    - Instructions: parameters

    This is NOT the complete "Job" entity - it's the DATA half.
    The BEHAVIOR half is defined by Workflow (ABC) in services/workflow.py.

    The conceptual "Job" entity = JobData + Workflow (composition)

    Specialized boundaries inherit from this:
    - JobRecord: Adds orchestration fields (status, stage, result_data, timestamps)
    - JobQueueMessage: Adds transport fields (stage_results, retry_count, timestamp)

    Example:
        ```python
        # Base contract captures essentials:
        job_data = JobData(
            job_id="abc123def456...",  # SHA256 hash
            job_type="hello_world",
            parameters={"message": "Hello", "n": 3}
        )

        # Specialization adds boundary-specific fields:
        job_record = JobRecord(
            **job_data.model_dump(),
            status=JobStatus.QUEUED,  # Database-specific
            stage=1,                   # Database-specific
            created_at=datetime.now()  # Database-specific
        )
        ```
    """

    # Identity (SHA256 hash for idempotency)
    job_id: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Job ID (SHA256 hash of job_type + parameters)"
    )

    # Classification
    job_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Type of job (links to Workflow via registry)"
    )

    # Instructions
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Job input parameters"
    )

    @field_validator('job_id')
    @classmethod
    def validate_job_id_format(cls, v: str) -> str:
        """Validate job_id is a valid SHA256 hash."""
        v = v.lower()
        if len(v) != 64:
            raise ValueError(f"job_id must be 64 characters (SHA256), got {len(v)}")
        if not all(c in '0123456789abcdef' for c in v):
            raise ValueError(f"job_id must be hexadecimal, got: {v}")
        return v

    @field_validator('job_type')
    @classmethod
    def normalize_job_type(cls, v: str) -> str:
        """Normalize job type to lowercase with underscores."""
        return v.lower().replace('-', '_')

    class Config:
        """Pydantic configuration."""
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# Export all public classes
__all__ = [
    'TaskData',
    'JobData',
]
