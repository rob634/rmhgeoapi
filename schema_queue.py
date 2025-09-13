# ============================================================================
# CLAUDE CONTEXT - SCHEMA
# ============================================================================
# PURPOSE: Queue-specific message schemas for Azure Queue Storage
# EXPORTS: JobQueueMessage, TaskQueueMessage
# INTERFACES: None - pure data models
# PYDANTIC_MODELS: JobQueueMessage, TaskQueueMessage
# DEPENDENCIES: pydantic, typing, datetime
# SOURCE: Queue messages from Azure Storage Queues
# SCOPE: Queue message validation and serialization
# VALIDATION: Pydantic v2 field validators and constraints
# PATTERNS: Data model pattern, Message pattern
# ENTRY_POINTS: from schema_queue import JobQueueMessage, TaskQueueMessage
# INDEX: JobQueueMessage:55, TaskQueueMessage:85
# ============================================================================

"""
Queue Message Schemas - Azure Queue Storage Integration

This module defines the message formats for job and task queues,
separating queue-specific schemas from database schemas.

Philosophy: "Queue messages are transient contracts between services"

The separation from schema_base.py ensures:
1. Queue schemas can evolve independently from database schemas
2. Clear distinction between persistent (DB) and transient (queue) data
3. Smaller, focused modules that are easier to maintain
"""

from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


# ============================================================================
# VALIDATION UTILITIES
# ============================================================================

def validate_job_id(v: str) -> str:
    """
    Validate job ID format (SHA256 hash).
    
    Args:
        v: Job ID to validate
        
    Returns:
        Validated job ID
        
    Raises:
        ValueError: If job ID format is invalid
    """
    if not v or len(v) != 64:
        raise ValueError(f"Job ID must be 64 characters (SHA256 hash), got {len(v) if v else 0}")
    if not all(c in '0123456789abcdef' for c in v.lower()):
        raise ValueError(f"Job ID must be hexadecimal, got: {v}")
    return v.lower()


# ============================================================================
# QUEUE MESSAGE MODELS
# ============================================================================

class JobQueueMessage(BaseModel):
    """
    Job queue message for Azure Queue Storage.
    
    This message format is used to queue jobs for processing by the
    job orchestration system. It contains all information needed to
    start processing a job without additional database lookups.
    
    Attributes:
        job_id: SHA256 hash of job parameters (64 chars)
        job_type: Type of job to execute (e.g., 'hello_world')
        stage: Current stage number (1-based)
        parameters: Job-specific parameters
        stage_results: Results from previous stages
        retry_count: Number of retry attempts
        timestamp: Message creation time
    """
    job_id: str = Field(..., min_length=64, max_length=64)
    job_type: str = Field(..., min_length=1, max_length=50)
    stage: int = Field(..., ge=1, le=100)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    stage_results: Optional[Dict[str, Any]] = Field(default_factory=dict)
    retry_count: int = Field(default=0, ge=0, le=10)
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message creation time")
    
    @field_validator('job_id')
    @classmethod
    def validate_job_id_format(cls, v):
        return validate_job_id(v)
    
    model_config = ConfigDict(validate_assignment=True)


class TaskQueueMessage(BaseModel):
    """
    Task queue message for Azure Queue Storage.
    
    This message format is used to queue individual tasks for execution
    by task processors. Each message represents a single unit of work
    within a job stage.
    
    Attributes:
        task_id: Unique task identifier (format: {job_id[:8]}-s{stage}-{index})
        parent_job_id: Full job ID this task belongs to (64 chars)
        task_type: Type of task to execute
        stage: Stage number this task belongs to
        task_index: Semantic index (e.g., 'tile_x5_y10' or '0')
        parameters: Task-specific parameters
        parent_task_id: Optional ID of predecessor task for lineage
        retry_count: Number of retry attempts
        timestamp: Message creation time
    """
    task_id: str = Field(..., min_length=1, max_length=100)
    parent_job_id: str = Field(..., min_length=64, max_length=64)
    job_type: str = Field(..., min_length=1, max_length=50, description="Parent job type for controller routing")
    task_type: str = Field(..., min_length=1, max_length=50)
    stage: int = Field(..., ge=1, le=100)
    task_index: str = Field(default="0", max_length=50, description="Can be semantic like 'tile_x5_y10'")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    parent_task_id: Optional[str] = Field(None, max_length=100, description="For explicit handoff from previous stage")
    retry_count: int = Field(default=0, ge=0, le=10)
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Message creation time")
    
    @field_validator('parent_job_id')
    @classmethod
    def validate_parent_job_id_format(cls, v):
        return validate_job_id(v)
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

"""
Example usage in function_app.py:

from schema_queue import JobQueueMessage, TaskQueueMessage

# Creating a job queue message
job_msg = JobQueueMessage(
    job_id="abc123...",  # 64-char SHA256
    job_type="process_raster",
    stage=1,
    parameters={"file": "input.tif"}
)

# Creating a task queue message
task_msg = TaskQueueMessage(
    task_id="abc123-s1-tile_x5_y10",
    parent_job_id="abc123...",  # Full 64-char ID
    task_type="reproject_tile",
    stage=1,
    task_index="tile_x5_y10",
    parameters={"bounds": [5, 10, 6, 11]}
)

# Serialization for queue
queue_client.send_message(job_msg.model_dump_json())

# Deserialization from queue
message = queue_client.receive_message()
job_msg = JobQueueMessage.model_validate_json(message.content)
"""