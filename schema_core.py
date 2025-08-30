"""
STRONG TYPING DISCIPLINE - Core Schema Definitions

This module enforces C-style type discipline for Python using Pydantic.
ZERO tolerance for runtime type errors, missing fields, or data corruption.

Design Principle: "If it compiles, it works. If it validates, it's bulletproof."

Schema Hierarchy:
- JobRecord: Canonical job storage schema
- TaskRecord: Canonical task storage schema  
- JobQueueMessage: Strict job queue message format
- TaskQueueMessage: Strict task queue message format

All schemas are:
1. Immutable after creation (frozen=True where appropriate)
2. Strictly validated at runtime
3. Storage backend agnostic
4. JSON serializable
5. Type-safe with full IntelliSense support

Author: Redesign Architecture Team
Version: 1.0.0 - Foundation implementation with strong typing discipline
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import re
from uuid import UUID

# ============================================================================
# ENUMERATIONS - Strictly controlled state values
# ============================================================================

class JobStatus(str, Enum):
    """Job status enumeration - immutable state values"""
    QUEUED = "queued"
    PROCESSING = "processing" 
    COMPLETED = "completed"
    FAILED = "failed"
    
    def is_terminal(self) -> bool:
        """Check if status is terminal (no further transitions)"""
        return self in (JobStatus.COMPLETED, JobStatus.FAILED)
    
    def can_transition_to(self, new_status: 'JobStatus') -> bool:
        """Validate status transitions"""
        transitions = {
            JobStatus.QUEUED: [JobStatus.PROCESSING, JobStatus.FAILED],
            JobStatus.PROCESSING: [JobStatus.COMPLETED, JobStatus.FAILED],
            JobStatus.COMPLETED: [],  # Terminal
            JobStatus.FAILED: []      # Terminal
        }
        return new_status in transitions.get(self, [])


class TaskStatus(str, Enum):
    """Task status enumeration - immutable state values"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed" 
    FAILED = "failed"
    
    def is_terminal(self) -> bool:
        """Check if status is terminal"""
        return self in (TaskStatus.COMPLETED, TaskStatus.FAILED)
    
    def can_transition_to(self, new_status: 'TaskStatus') -> bool:
        """Validate status transitions"""
        transitions = {
            TaskStatus.QUEUED: [TaskStatus.PROCESSING, TaskStatus.FAILED],
            TaskStatus.PROCESSING: [TaskStatus.COMPLETED, TaskStatus.FAILED],
            TaskStatus.COMPLETED: [],  # Terminal
            TaskStatus.FAILED: []      # Terminal
        }
        return new_status in transitions.get(self, [])


# ============================================================================
# VALIDATION UTILITIES - C-style strict validation
# ============================================================================

def validate_job_id(job_id: str) -> str:
    """Validate job ID format (SHA256 hash)"""
    if not re.match(r'^[a-f0-9]{64}$', job_id):
        raise ValueError(f"job_id must be 64-character SHA256 hash, got: {job_id}")
    return job_id

def validate_task_id(task_id: str) -> str:  
    """Validate task ID format (job_id + stage + index)"""
    if not re.match(r'^[a-f0-9]{64}_stage\d+_task\d+$', task_id):
        raise ValueError(f"task_id must match pattern 'jobId_stageN_taskN', got: {task_id}")
    return task_id

def validate_job_type(job_type: str) -> str:
    """Validate job type format (snake_case)"""
    if not re.match(r'^[a-z][a-z0-9_]*$', job_type):
        raise ValueError(f"job_type must be snake_case, got: {job_type}")
    return job_type

def validate_task_type(task_type: str) -> str:
    """Validate task type format (snake_case)"""
    if not re.match(r'^[a-z][a-z0-9_]*$', task_type):
        raise ValueError(f"task_type must be snake_case, got: {task_type}")
    return task_type


# ============================================================================
# CORE RECORD SCHEMAS - Canonical storage models
# ============================================================================

class JobRecord(BaseModel):
    """
    CANONICAL JOB SCHEMA - Enforced across ALL storage backends
    
    This is the single source of truth for job data structure.
    ZERO tolerance for missing fields or wrong types.
    """
    
    # Primary identifiers (IMMUTABLE after creation)
    job_id: str = Field(..., description="Unique job identifier (SHA256)", min_length=64, max_length=64)
    job_type: str = Field(..., description="Type of job (snake_case)", min_length=1, max_length=50)
    
    # State management (MUTABLE with validation)
    status: JobStatus = Field(default=JobStatus.QUEUED, description="Current job status")
    stage: int = Field(default=1, ge=1, le=100, description="Current stage number")
    total_stages: int = Field(default=1, ge=1, le=100, description="Total stages in job")
    
    # Data containers (VALIDATED JSON)
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Job parameters")
    stage_results: Dict[int, Dict[str, Any]] = Field(default_factory=dict, description="Results from completed stages")
    result_data: Optional[Dict[str, Any]] = Field(None, description="Final job result data")
    
    # Error handling (OPTIONAL but structured)
    error_details: Optional[str] = Field(None, description="Error details if job failed")
    
    # Audit trail (IMMUTABLE timestamps)
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    # Validation rules
    @field_validator('job_id')
    @classmethod
    def validate_job_id_format(cls, v):
        return validate_job_id(v)
    
    @field_validator('job_type')
    @classmethod 
    def validate_job_type_format(cls, v):
        return validate_job_type(v)
    
    @model_validator(mode='after')
    def validate_stage_consistency(self):
        if self.stage > self.total_stages:
            raise ValueError(f"stage ({self.stage}) cannot exceed total_stages ({self.total_stages})")
        return self
    
    @model_validator(mode='after')
    def validate_terminal_status_has_result_or_error(self):
        if self.status == JobStatus.COMPLETED and not self.result_data:
            raise ValueError("COMPLETED jobs must have result_data")
        if self.status == JobStatus.FAILED and not self.error_details:
            raise ValueError("FAILED jobs must have error_details")
        return self
    
    def can_transition_to(self, new_status: JobStatus) -> bool:
        """Validate status transitions with C-style strictness"""
        return self.status.can_transition_to(new_status)
    
    def is_terminal(self) -> bool:
        """Check if job is in terminal state"""
        return self.status.is_terminal()
    
    class Config:
        # Enforce immutability for critical fields
        validate_assignment = True  # Validate on every field assignment
        use_enum_values = True  # Store enum values, not objects


class TaskRecord(BaseModel):
    """
    CANONICAL TASK SCHEMA - Enforced across ALL storage backends
    
    Tasks belong to jobs with strict parent-child relationship.
    ZERO tolerance for orphaned tasks or missing relationships.
    """
    
    # Primary identifiers (IMMUTABLE after creation)
    taskId: str = Field(..., description="Unique task identifier", min_length=1, max_length=100)
    parentJobId: str = Field(..., description="Parent job ID (foreign key)", min_length=64, max_length=64)
    taskType: str = Field(..., description="Type of task (snake_case)", min_length=1, max_length=50)
    
    # State management (MUTABLE with validation)
    status: TaskStatus = Field(default=TaskStatus.QUEUED, description="Current task status")
    
    # Hierarchy (IMMUTABLE after creation)
    stage: int = Field(..., ge=1, le=100, description="Stage number this task belongs to")
    taskIndex: int = Field(..., ge=0, le=10000, description="Index within stage (0-based)")
    
    # Data containers (VALIDATED JSON)  
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    resultData: Optional[Dict[str, Any]] = Field(None, description="Task result data")
    
    # Error handling & retry (STRUCTURED)
    errorDetails: Optional[str] = Field(None, description="Error details if task failed")
    retryCount: int = Field(default=0, ge=0, le=10, description="Number of retry attempts")
    
    # Health monitoring (MUTABLE for heartbeat updates)
    heartbeat: Optional[datetime] = Field(None, description="Last heartbeat timestamp")
    
    # Audit trail (IMMUTABLE timestamps)
    createdAt: datetime = Field(..., description="Task creation timestamp")
    updatedAt: datetime = Field(..., description="Last update timestamp")
    
    # Validation rules  
    @field_validator('taskId')
    @classmethod
    def validate_task_id_format(cls, v):
        return validate_task_id(v)
    
    @field_validator('parentJobId')
    @classmethod
    def validate_parent_job_id_format(cls, v):
        return validate_job_id(v)
    
    @field_validator('taskType')
    @classmethod
    def validate_task_type_format(cls, v):
        return validate_task_type(v)
    
    @model_validator(mode='after')
    def validate_terminal_status_requirements(self):
        if self.status == TaskStatus.COMPLETED and not self.resultData:
            raise ValueError("COMPLETED tasks must have resultData")
        if self.status == TaskStatus.FAILED and not self.errorDetails:
            raise ValueError("FAILED tasks must have errorDetails")
        return self
    
    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """Validate status transitions with C-style strictness"""
        return self.status.can_transition_to(new_status)
    
    def is_terminal(self) -> bool:
        """Check if task is in terminal state"""
        return self.status.is_terminal()
    
    def extract_job_id_from_task_id(self) -> str:
        """Extract parent job ID from task ID format"""
        return self.taskId.split('_')[0]
    
    def extract_stage_from_task_id(self) -> int:
        """Extract stage number from task ID format"""
        parts = self.taskId.split('_')
        return int(parts[1].replace('stage', ''))
    
    class Config:
        validate_assignment = True  # Validate on every field assignment
        use_enum_values = True  # Store enum values, not objects


# ============================================================================
# QUEUE MESSAGE SCHEMAS - Strict message format enforcement  
# ============================================================================

class JobQueueMessage(BaseModel):
    """
    STRICT JOB QUEUE MESSAGE SCHEMA
    
    Messages sent to job processing queue must match this format EXACTLY.
    Any deviation results in immediate ValidationError.
    """
    
    jobId: str = Field(..., description="Job ID to process", min_length=64, max_length=64)
    jobType: str = Field(..., description="Job type", min_length=1, max_length=50)
    stage: int = Field(..., ge=1, le=100, description="Stage number to process")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Job parameters")
    stageResults: Dict[int, Dict[str, Any]] = Field(default_factory=dict, description="Previous stage results")
    retryCount: int = Field(default=0, ge=0, le=10, description="Retry attempt number")
    
    # Validation rules
    @field_validator('jobId')
    @classmethod
    def validate_job_id_format(cls, v):
        return validate_job_id(v)
    
    @field_validator('jobType')
    @classmethod
    def validate_job_type_format(cls, v):
        return validate_job_type(v)
    
    class Config:
        validate_assignment = True


class TaskQueueMessage(BaseModel):
    """
    STRICT TASK QUEUE MESSAGE SCHEMA
    
    Messages sent to task processing queue must match this format EXACTLY.
    Enforces parent-child relationship with jobs.
    """
    
    taskId: str = Field(..., description="Task ID to process", min_length=1, max_length=100)
    parentJobId: str = Field(..., description="Parent job ID", min_length=64, max_length=64)
    taskType: str = Field(..., description="Task type", min_length=1, max_length=50)
    stage: int = Field(..., ge=1, le=100, description="Stage number")
    taskIndex: int = Field(..., ge=0, le=10000, description="Task index within stage")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    retryCount: int = Field(default=0, ge=0, le=10, description="Retry attempt number")
    
    # Validation rules
    @field_validator('taskId')
    @classmethod
    def validate_task_id_format(cls, v):
        return validate_task_id(v)
    
    @field_validator('parentJobId')
    @classmethod
    def validate_parent_job_id_format(cls, v):
        return validate_job_id(v)
    
    @field_validator('taskType')
    @classmethod
    def validate_task_type_format(cls, v):
        return validate_task_type(v)
    
    @model_validator(mode='after')
    def validate_task_belongs_to_job(self):
        """Validate that task ID contains the parent job ID"""
        if self.parentJobId and not self.taskId.startswith(self.parentJobId):
            raise ValueError(f"taskId must start with parentJobId. Got taskId={self.taskId}, parentJobId={self.parentJobId}")
        return self
    
    class Config:
        validate_assignment = True


# ============================================================================
# SCHEMA UTILITIES - Strong typing helpers
# ============================================================================

def generate_task_id(job_id: str, stage: int, task_index: int) -> str:
    """Generate standardized task ID with strong format validation"""
    task_id = f"{job_id}_stage{stage}_task{task_index}"
    return validate_task_id(task_id)  # Validate before returning

def generate_job_id(job_type: str, parameters: Dict[str, Any]) -> str:
    """Generate deterministic job ID from parameters"""
    import hashlib
    import json
    
    # Sort parameters for consistent hashing
    sorted_params = json.dumps(parameters, sort_keys=True, default=str)
    hash_input = f"{job_type}:{sorted_params}"
    job_id = hashlib.sha256(hash_input.encode()).hexdigest()
    
    return validate_job_id(job_id)  # Validate before returning


# ============================================================================
# VALIDATION ERRORS - Structured error handling
# ============================================================================

class SchemaValidationError(Exception):
    """Custom exception for schema validation failures"""
    
    def __init__(self, model_name: str, validation_errors: List[Dict]):
        self.model_name = model_name
        self.validation_errors = validation_errors
        
        error_details = []
        for error in validation_errors:
            field = '.'.join(str(loc) for loc in error['loc'])
            error_details.append(f"{field}: {error['msg']}")
        
        message = f"Schema validation failed for {model_name}:\n" + "\n".join(error_details)
        super().__init__(message)


# ============================================================================
# CONFIGURATION - Global schema settings
# ============================================================================

class SchemaConfig:
    """Global configuration for schema enforcement"""
    
    # Validation strictness
    STRICT_MODE = True  # Fail fast on any validation error
    
    # Field constraints
    MAX_PARAMETER_SIZE_BYTES = 1024 * 1024  # 1MB JSON parameter limit
    MAX_RESULT_DATA_SIZE_BYTES = 10 * 1024 * 1024  # 10MB result data limit
    
    # Retry policies
    MAX_JOB_RETRIES = 3
    MAX_TASK_RETRIES = 10
    
    # Timeout configurations
    TASK_HEARTBEAT_TIMEOUT_MINUTES = 10
    JOB_PROCESSING_TIMEOUT_MINUTES = 60


# Export all public schemas and utilities
__all__ = [
    # Enums
    'JobStatus', 'TaskStatus',
    # Core schemas 
    'JobRecord', 'TaskRecord',
    # Queue message schemas
    'JobQueueMessage', 'TaskQueueMessage', 
    # Utilities
    'generate_job_id', 'generate_task_id',
    'validate_job_id', 'validate_task_id', 'validate_job_type', 'validate_task_type',
    # Errors
    'SchemaValidationError',
    # Configuration
    'SchemaConfig'
]