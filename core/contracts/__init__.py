"""
Core Data Contracts - Base Pydantic Models.

Defines foundational data structures for Task and Job entities.
Base classes capture essential identity and classification,
while specialized subclasses add boundary-specific fields.

Architecture:
    TaskData: Essential task identity (task_id, parent_job_id, parameters)
    JobData: Essential job identity (job_id, job_type, parameters)

Boundary Specializations:
    TaskRecord(TaskData): Adds persistence fields (status, timestamps)
    TaskQueueMessage(TaskData): Adds transport fields (retry_count)
    JobRecord(JobData): Adds orchestration fields (stage, status)
    JobQueueMessage(JobData): Adds transport fields

Exports:
    TaskData: Base contract for task representations
    JobData: Base contract for job representations
"""

from datetime import datetime
from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict


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

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    @field_validator('task_type')
    @classmethod
    def normalize_task_type(cls, v: str) -> str:
        """Normalize task type to lowercase with underscores."""
        return v.lower().replace('-', '_')


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

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()}
    )

    @field_validator('job_type')
    @classmethod
    def normalize_job_type(cls, v: str) -> str:
        """Normalize job type to lowercase with underscores."""
        return v.lower().replace('-', '_')


# Export all public classes
__all__ = [
    'TaskData',
    'JobData',
]
