# ============================================================================
# CLAUDE CONTEXT - SCHEMA
# ============================================================================
# PURPOSE: Unified schema for Job→Stage→Task architecture - single source of truth for all workflow components
# EXPORTS: All status enums, record models, queue messages, execution contexts, results, BaseController with completion logic
# INTERFACES: BaseController (ABC with completion methods), Pydantic BaseModel for validation, dataclasses for internals
# PYDANTIC_MODELS: JobRecord, TaskRecord, execution contexts, TaskResult (Queue models moved to schema_queue.py)
# DEPENDENCIES: pydantic, abc, dataclasses, typing, datetime, enum, hashlib, json, uuid
# SOURCE: No data source - defines all data structures and contracts for the workflow system
# SCOPE: Complete Job→Stage→Task architecture including persistence, queuing, execution, results, and completion logic
# VALIDATION: Pydantic validation at boundaries, lightweight dataclasses for internal processing
# PATTERNS: Template Method (BaseController), Value Objects, Domain Models, ABC contracts, Factory methods
# ENTRY_POINTS: from schema_base import BaseController, JobRecord, TaskRecord, JobExecutionContext, TaskDefinition
# INDEX: Enums:114, Records:180, Queues:280, Contexts:340, Definitions:620, Results:640, BaseController:850
# ============================================================================

"""
Unified Schema for Job→Stage→Task Architecture with Completion Logic

This module consolidates all data models and base controller logic for the Azure Geospatial 
ETL Pipeline into a single source of truth. It provides:
- Complete data model definitions for the workflow system
- BaseController with built-in completion logic (aggregate_stage_results, should_advance_stage)
- Execution contexts and queue messages for job orchestration

The consolidation ensures consistency across the entire job orchestration system while
maintaining proper OOP design with completion logic in the base controller class.

Architecture Layers:
1. PERSISTENCE: JobRecord, TaskRecord (Pydantic) - Database tables
2. QUEUING: JobQueueMessage, TaskQueueMessage (Pydantic) - Async messaging
3. EXECUTION: Job/Stage/TaskExecutionContext (Pydantic) - Runtime state
4. DEFINITIONS: TaskDefinition, StageDefinition (dataclass) - Internal configs
5. RESULTS: TaskResult, StageResult, JobResult (mixed) - Aggregation
6. BASE CONTROLLER: BaseController with completion methods - Template pattern

Key Features:
- BaseController.aggregate_stage_results(): Default implementation for stage result aggregation
- BaseController.should_advance_stage(): Default logic for stage advancement decisions
- Concrete controllers can override these methods for job-specific behavior
- Eliminates need for separate completion utility classes

Design Philosophy:
- Pydantic validation at system boundaries (DB, API, Queues)
- Lightweight dataclasses for internal high-performance processing
- Completion logic properly encapsulated in base controller class
- Single inheritance chain for clean OOP design
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict, field_serializer
import hashlib
import json
import uuid


# ============================================================================
# STATUS ENUMERATIONS
# ============================================================================

class JobStatus(Enum):
    """
    Job status enumeration - tracks job lifecycle.
    
    State transitions:
        QUEUED → PROCESSING → COMPLETED
                           ↘ FAILED
                           ↘ CANCELLED
    """
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"  # Waiting for dependencies
    
    @classmethod
    def terminal_states(cls) -> List['JobStatus']:
        """Return list of terminal states"""
        return [cls.COMPLETED, cls.FAILED, cls.CANCELLED]
    
    @classmethod
    def active_states(cls) -> List['JobStatus']:
        """Return list of active processing states"""
        return [cls.PROCESSING, cls.QUEUED, cls.PENDING]


class TaskStatus(Enum):
    """
    Task status enumeration - tracks task lifecycle.
    
    State transitions:
        QUEUED → PROCESSING → COMPLETED
                           ↘ FAILED
                           ↘ SKIPPED
    """
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    
    @classmethod
    def terminal_states(cls) -> List['TaskStatus']:
        """Return list of terminal states"""
        return [cls.COMPLETED, cls.FAILED, cls.SKIPPED]
    
    @classmethod
    def active_states(cls) -> List['TaskStatus']:
        """Return list of active processing states"""
        return [cls.PROCESSING, cls.QUEUED, cls.RETRYING]


class StageStatus(Enum):
    """Stage status enumeration - Stage-specific statuses"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# VALIDATION UTILITIES
# ============================================================================

def validate_job_id(job_id: str) -> str:
    """Validate job ID is a 64-character SHA256 hash"""
    if not job_id or len(job_id) != 64:
        raise ValueError(f"Job ID must be 64 characters (SHA256), got {len(job_id) if job_id else 0}")
    return job_id

def validate_task_id(task_id: str) -> str:
    """Validate task ID format"""
    if not task_id or len(task_id) < 1 or len(task_id) > 100:
        raise ValueError(f"Task ID must be 1-100 characters, got {len(task_id) if task_id else 0}")
    return task_id

def validate_job_type(job_type: str) -> str:
    """Validate job type format"""
    if not job_type or len(job_type) < 1 or len(job_type) > 50:
        raise ValueError(f"Job type must be 1-50 characters")
    return job_type

def validate_task_type(task_type: str) -> str:
    """Validate task type format"""
    if not task_type or len(task_type) < 1 or len(task_type) > 50:
        raise ValueError(f"Task type must be 1-50 characters")
    return task_type


# ============================================================================
# ID GENERATION UTILITIES
# ============================================================================

def generate_job_id(job_type: str, parameters: Dict[str, Any]) -> str:
    """
    Generate deterministic job ID from job type and parameters.
    SHA256 hash ensures idempotency - same inputs always produce same ID.
    """
    # Create deterministic string representation
    param_str = json.dumps(parameters, sort_keys=True)
    content = f"{job_type}:{param_str}"
    
    # Generate SHA256 hash
    return hashlib.sha256(content.encode()).hexdigest()


# ============================================================================
# DATABASE RECORD MODELS (Pydantic) - For PostgreSQL persistence
# ============================================================================

class JobRecord(BaseModel):
    """
    Job database record - PostgreSQL persistence model.
    
    This is the canonical job representation in the database.
    Used by SQL generator to create the jobs table.
    """
    job_id: str = Field(..., min_length=64, max_length=64, description="SHA256 job ID")
    job_type: str = Field(..., min_length=1, max_length=50, description="Type of job")
    status: JobStatus = Field(default=JobStatus.QUEUED, description="Current job status")
    stage: int = Field(default=1, ge=1, le=100, description="Current stage number")
    total_stages: int = Field(default=1, ge=1, le=100, description="Total number of stages")
    
    # Data fields
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Job parameters")
    stage_results: Dict[str, Any] = Field(default_factory=dict, description="Results from completed stages")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Job metadata")
    result_data: Optional[Dict[str, Any]] = Field(None, description="Final job results")
    error_details: Optional[str] = Field(None, max_length=5000, description="Error details if failed")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Job creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    
    # Validators
    @field_validator('job_id')
    @classmethod
    def validate_job_id_format(cls, v):
        return validate_job_id(v)
    
    @field_validator('job_type')
    @classmethod
    def validate_job_type_format(cls, v):
        return validate_job_type(v)
    
    def can_transition_to(self, new_status: 'JobStatus') -> bool:
        """
        Validate job status transitions based on ARCHITECTURE_CORE.md state machine.
        
        Jobs cycle between QUEUED and PROCESSING for stage advancement:
        - QUEUED ⇄ PROCESSING (multi-stage cycling)
        - PROCESSING → COMPLETED/FAILED (terminal states)
        
        Args:
            new_status: The proposed new status
            
        Returns:
            True if transition is valid, False otherwise
        """
        # Normalize current status to enum (handles both string and enum values from database)
        if isinstance(self.status, str):
            current = JobStatus(self.status)
        else:
            current = self.status
        
        # Allow cycling between QUEUED and PROCESSING for stage advancement
        if current == JobStatus.QUEUED and new_status == JobStatus.PROCESSING:
            return True
        if current == JobStatus.PROCESSING and new_status == JobStatus.QUEUED:
            return True  # Stage advancement re-queuing
            
        # Allow terminal transitions from PROCESSING
        if current == JobStatus.PROCESSING and new_status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            return True
            
        # Allow error recovery transitions from terminal states
        if current in JobStatus.terminal_states():
            return True  # Can restart from any terminal state
            
        # Allow PENDING transitions (dependency management)
        if current == JobStatus.PENDING and new_status in [JobStatus.QUEUED, JobStatus.PROCESSING]:
            return True
        if current in [JobStatus.QUEUED, JobStatus.PROCESSING] and new_status == JobStatus.PENDING:
            return True
            
        return False
    
    model_config = ConfigDict(validate_assignment=True)
    
    @field_serializer('created_at', 'updated_at')
    def serialize_datetime(self, value: datetime) -> str:
        """Serialize datetime fields to ISO format"""
        return value.isoformat() if value else None
    
    # Note: Add Decimal serializer if any Decimal fields are added in future
    # @field_serializer('amount', 'price')  # Example for Decimal fields
    # def serialize_decimal(self, value: Decimal) -> float:
    #     return float(value) if value else None


class TaskRecord(BaseModel):
    """
    Task database record - PostgreSQL persistence model.
    
    This is the canonical task representation in the database.
    Used by SQL generator to create the tasks table.
    """
    task_id: str = Field(..., min_length=1, max_length=100, description="Unique task ID")
    parent_job_id: str = Field(..., min_length=64, max_length=64, description="Parent job ID")
    job_type: str = Field(..., min_length=1, max_length=50, description="Parent job type for controller routing")
    task_type: str = Field(..., min_length=1, max_length=50, description="Type of task")
    status: TaskStatus = Field(default=TaskStatus.QUEUED, description="Current task status")
    
    # Hierarchy
    stage: int = Field(..., ge=1, le=100, description="Stage number")
    task_index: str = Field(default="0", max_length=50, description="Can be semantic like 'tile_x5_y10'")
    
    # Data fields
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    result_data: Optional[Dict[str, Any]] = Field(None, description="Task results")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Task metadata")
    error_details: Optional[str] = Field(None, max_length=5000, description="Error details if failed")
    
    # Execution tracking
    retry_count: int = Field(default=0, ge=0, le=10, description="Number of retries")
    heartbeat: Optional[datetime] = Field(None, description="Last heartbeat for long-running tasks")
    
    # Task handoff
    next_stage_params: Optional[Dict[str, Any]] = Field(None, description="Explicit handoff to next stage task")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Task creation time")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update time")
    
    # Validators
    @field_validator('task_id')
    @classmethod
    def validate_task_id_format(cls, v):
        return validate_task_id(v)
    
    @field_validator('parent_job_id')
    @classmethod
    def validate_parent_job_id_format(cls, v):
        return validate_job_id(v)
    
    @field_validator('task_type')
    @classmethod
    def validate_task_type_format(cls, v):
        return validate_task_type(v)
    
    def can_transition_to(self, new_status: 'TaskStatus') -> bool:
        """
        Validate task status transitions based on simple lifecycle.
        
        Tasks follow linear progression (no cycling back):
        - QUEUED → PROCESSING → COMPLETED/FAILED/SKIPPED
        
        Args:
            new_status: The proposed new status
            
        Returns:
            True if transition is valid, False otherwise
        """
        # Normalize current status to enum (handles both string and enum values from database)
        if isinstance(self.status, str):
            current = TaskStatus(self.status)
        else:
            current = self.status
        
        # Standard task lifecycle
        if current == TaskStatus.QUEUED and new_status == TaskStatus.PROCESSING:
            return True
        if current == TaskStatus.PROCESSING and new_status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED]:
            return True
            
        # Allow retry transitions from terminal states
        if current in TaskStatus.terminal_states() and new_status in [TaskStatus.QUEUED, TaskStatus.PROCESSING, TaskStatus.RETRYING]:
            return True  # Can restart from terminal states
            
        # Allow RETRYING transitions
        if current == TaskStatus.RETRYING and new_status in [TaskStatus.QUEUED, TaskStatus.PROCESSING]:
            return True
        if current in [TaskStatus.FAILED, TaskStatus.PROCESSING] and new_status == TaskStatus.RETRYING:
            return True
            
        return False
    
    model_config = ConfigDict(validate_assignment=True)
    
    @field_serializer('created_at', 'updated_at', 'heartbeat')
    def serialize_datetime(self, value: datetime) -> str:
        """Serialize datetime fields to ISO format"""
        return value.isoformat() if value else None


# ============================================================================
# NOTE: Queue message models moved to schema_queue.py for better separation
# Import from schema_queue: JobQueueMessage, TaskQueueMessage
# ============================================================================

# ============================================================================
# EXECUTION CONTEXT MODELS (Pydantic) - Runtime state management
# ============================================================================

class JobExecutionContext(BaseModel):
    """
    Job execution context with Pydantic validation.
    
    Runtime state for job orchestration with validation.
    """
    job_id: str = Field(..., min_length=64, max_length=64)
    job_type: str = Field(..., min_length=1, max_length=50)
    current_stage: int = Field(..., ge=1, le=100)
    total_stages: int = Field(..., ge=1, le=100)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    stage_results: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    
    @field_validator('job_id')
    @classmethod
    def validate_job_id_format(cls, v):
        return validate_job_id(v)
    
    def get_stage_result(self, stage_number: int) -> Optional[Dict[str, Any]]:
        """Get results from a specific stage"""
        return self.stage_results.get(stage_number)
    
    def set_stage_result(self, stage_number: int, result: Dict[str, Any]) -> None:
        """Set results for a specific stage"""
        self.stage_results[stage_number] = result
    
    model_config = ConfigDict(validate_assignment=True)


class StageExecutionContext(BaseModel):
    """
    Stage execution context with Pydantic validation.
    
    Runtime state for stage coordination with validation.
    """
    job_id: str = Field(..., min_length=64, max_length=64)
    stage_number: int = Field(..., ge=1, le=100)
    stage_name: str = Field(..., min_length=1, max_length=100)
    task_type: str = Field(..., min_length=1, max_length=50)
    job_parameters: Dict[str, Any] = Field(default_factory=dict)
    previous_stage_results: Optional[Dict[str, Any]] = Field(None)
    task_count: int = Field(default=0, ge=0)
    completed_tasks: int = Field(default=0, ge=0)
    failed_tasks: int = Field(default=0, ge=0)
    
    @property
    def is_stage_complete(self) -> bool:
        """Check if all tasks in stage are complete"""
        return self.completed_tasks + self.failed_tasks >= self.task_count
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate for completed tasks"""
        total_finished = self.completed_tasks + self.failed_tasks
        if total_finished == 0:
            return 0.0
        return (self.completed_tasks / total_finished) * 100.0
    
    model_config = ConfigDict(validate_assignment=True)


class TaskExecutionContext(BaseModel):
    """
    Task execution context with Pydantic validation.
    
    Runtime state for task execution with validation.
    """
    task_id: str = Field(..., min_length=1, max_length=100)
    parent_job_id: str = Field(..., min_length=64, max_length=64)
    stage: int = Field(..., ge=1, le=100)
    task_index: str = Field(default="0", max_length=50, description="Can be semantic like 'tile_x5_y10'")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    parent_stage_results: Optional[Dict[str, Any]] = Field(None)
    retry_count: int = Field(default=0, ge=0, le=10)
    max_retries: int = Field(default=3, ge=0, le=10)
    
    @property
    def job_id(self) -> str:
        """Alias for parent_job_id"""
        return self.parent_job_id
    
    @property
    def stage_number(self) -> int:
        """Alias for stage"""
        return self.stage
    
    @property
    def is_retry(self) -> bool:
        """Check if this is a retry attempt"""
        return self.retry_count > 0
    
    @property
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.retry_count < self.max_retries
    
    model_config = ConfigDict(validate_assignment=True)


# ============================================================================
# WORKFLOW DEFINITION MODELS (Pydantic) - Configuration with validation
# ============================================================================

class StageDefinition(BaseModel):
    """
    Stage definition for controller configuration - validated configuration model.
    
    Defines a single stage within a job workflow, including task type, 
    parallelization limits, and dependencies on previous stages.
    Used as building block for WorkflowDefinition.
    """
    stage_number: int = Field(..., ge=1, le=100, description="Stage number in workflow")
    stage_name: str = Field(..., min_length=1, max_length=100, description="Human-readable stage name")
    task_type: str = Field(..., min_length=1, max_length=50, description="Type of tasks in this stage")
    max_parallel_tasks: int = Field(default=100, ge=1, le=1000, description="Max parallel tasks")
    timeout_minutes: int = Field(default=30, ge=1, le=600, description="Stage timeout in minutes")
    depends_on_stage: Optional[int] = Field(None, ge=1, le=99, description="Previous stage dependency")
    is_final_stage: bool = Field(default=False, description="Is this the last stage?")
    
    @field_validator('depends_on_stage')
    @classmethod
    def validate_dependency(cls, v, info):
        """Validate stage dependency is earlier stage"""
        if v is not None and 'stage_number' in info.data:
            if v >= info.data['stage_number']:
                raise ValueError(f"Stage {info.data['stage_number']} cannot depend on stage {v} (must depend on earlier stage)")
        return v
    
    model_config = ConfigDict(validate_assignment=True)


class WorkflowDefinition(BaseModel):
    """
    Complete workflow definition for a job type.
    
    Defines the entire multi-stage workflow for a specific job type,
    including all stages, their dependencies, and job-level configuration.
    Used by controllers to orchestrate job execution.
    """
    job_type: str = Field(..., min_length=1, max_length=50, description="Unique job type identifier")
    description: str = Field(..., min_length=1, max_length=500, description="Human-readable workflow description")
    total_stages: int = Field(..., ge=1, le=100, description="Total number of stages in workflow")
    stages: List[StageDefinition] = Field(..., description="Ordered list of stage definitions")
    max_parallel_tasks: int = Field(default=100, ge=1, le=1000, description="Max parallel tasks across all stages")
    timeout_minutes: int = Field(default=60, ge=1, le=1440, description="Total workflow timeout in minutes")
    
    @field_validator('stages')
    @classmethod
    def validate_stages(cls, v, info):
        """Validate stages are properly numbered and configured"""
        if not v:
            raise ValueError("Workflow must have at least one stage")
        
        # Check stage numbers are sequential
        stage_numbers = [s.stage_number for s in v]
        expected = list(range(1, len(v) + 1))
        if sorted(stage_numbers) != expected:
            raise ValueError(f"Stage numbers must be sequential from 1 to {len(v)}")
        
        # Validate total_stages matches
        if 'total_stages' in info.data and info.data['total_stages'] != len(v):
            raise ValueError(f"total_stages ({info.data['total_stages']}) must match number of stages ({len(v)})")
        
        # Ensure only last stage is marked as final
        for i, stage in enumerate(v):
            if stage.is_final_stage and i != len(v) - 1:
                raise ValueError(f"Only the last stage can be marked as final (stage {stage.stage_number})")
        
        return v
    
    model_config = ConfigDict(validate_assignment=True)


class JobRegistration(BaseModel):
    """
    Registration metadata for a job type.
    
    Captures all metadata about a registered job type including its
    controller class, workflow definition, and runtime configuration.
    Used by JobRegistry to track available job types.
    """
    job_type: str = Field(..., min_length=1, max_length=50, description="Unique job type identifier")
    controller_class: str = Field(..., description="Fully qualified controller class name")
    workflow: WorkflowDefinition = Field(..., description="Complete workflow definition")
    description: str = Field(..., min_length=1, max_length=500, description="Job type description")
    max_parallel_tasks: int = Field(default=100, ge=1, le=1000, description="Max parallel tasks for this job type")
    timeout_minutes: int = Field(default=60, ge=1, le=1440, description="Job timeout in minutes")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Registration timestamp")
    
    model_config = ConfigDict(validate_assignment=True)
    
    @field_serializer('created_at')
    def serialize_datetime(self, value: datetime) -> str:
        """Serialize datetime fields to ISO format"""
        return value.isoformat() if value else None


# Singleton instance holder (outside class to avoid Pydantic issues)
_job_registry_instance: Optional['JobRegistry'] = None


class JobRegistry(BaseModel):
    """
    Central registry for all job types (Singleton pattern).
    
    Maintains a registry of all available job types and their configurations.
    Supports decorator-based registration and factory pattern for job creation.
    This is a singleton - use JobRegistry.instance() to access.
    
    Example:
        @JobRegistry.instance().register(
            job_type="process_raster",
            workflow=ProcessRasterWorkflow()
        )
        class ProcessRasterController(BaseController):
            pass
    """
    registered_jobs: Dict[str, JobRegistration] = Field(
        default_factory=dict,
        description="Map of job_type to JobRegistration"
    )
    
    model_config = ConfigDict(validate_assignment=True)
    
    @classmethod
    def instance(cls) -> 'JobRegistry':
        """Get or create the singleton registry instance"""
        global _job_registry_instance
        if _job_registry_instance is None:
            _job_registry_instance = cls()
        return _job_registry_instance
    
    def register(self, job_type: str, workflow: WorkflowDefinition, **kwargs):
        """
        Decorator to register a controller class with the registry.
        
        Args:
            job_type: Unique identifier for the job type
            workflow: WorkflowDefinition for this job type
            **kwargs: Additional registration metadata
            
        Returns:
            Decorator function that registers the controller class
        """
        def decorator(controller_class):
            # Create registration entry
            registration = JobRegistration(
                job_type=job_type,
                controller_class=f"{controller_class.__module__}.{controller_class.__name__}",
                workflow=workflow,
                **kwargs
            )
            
            # Store in registry
            self.registered_jobs[job_type] = registration
            
            # Add metadata to the class itself for introspection
            controller_class._job_type = job_type
            controller_class._workflow = workflow
            controller_class._registration = registration
            
            return controller_class
        
        return decorator
    
    def get_registration(self, job_type: str) -> Optional[JobRegistration]:
        """Get registration for a specific job type"""
        return self.registered_jobs.get(job_type)
    
    def list_job_types(self) -> List[str]:
        """List all registered job types"""
        return list(self.registered_jobs.keys())
    
    def is_registered(self, job_type: str) -> bool:
        """Check if a job type is registered"""
        return job_type in self.registered_jobs


# ============================================================================
# INTERNAL DEFINITION MODELS (Dataclasses) - Lightweight internal configs
# ============================================================================

@dataclass
class TaskDefinition:
    """
    Task definition for stage execution - lightweight internal model.
    
    Now includes factory methods for converting to TaskRecord and TaskQueueMessage,
    ensuring consistency across all task data structures.
    """
    task_id: str
    job_type: str  # Added for controller routing
    task_type: str
    stage_number: int
    job_id: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on_tasks: Optional[List[str]] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def to_task_record(self, status: TaskStatus = TaskStatus.QUEUED) -> 'TaskRecord':
        """
        Convert TaskDefinition to TaskRecord for database storage.
        
        Args:
            status: Initial task status (default: QUEUED)
            
        Returns:
            TaskRecord ready for database insertion
        """
        return TaskRecord(
            task_id=self.task_id,
            parent_job_id=self.job_id,
            job_type=self.job_type,
            task_type=self.task_type,
            status=status,
            stage=self.stage_number,
            task_index=self.parameters.get('task_index', '0'),
            parameters=self.parameters,
            metadata={},
            retry_count=self.retry_count
        )
    
    def to_queue_message(self) -> 'TaskQueueMessage':
        """
        Convert TaskDefinition to TaskQueueMessage for queue processing.
        
        Returns:
            TaskQueueMessage ready for Azure Queue
        """
        # Import here to avoid circular dependency
        from schema_queue import TaskQueueMessage
        
        return TaskQueueMessage(
            task_id=self.task_id,
            parent_job_id=self.job_id,
            job_type=self.job_type,
            task_type=self.task_type,
            stage=self.stage_number,
            task_index=self.parameters.get('task_index', '0'),
            parameters=self.parameters,
            retry_count=self.retry_count
        )


# ============================================================================
# RESULT MODELS (Mixed) - Aggregation and completion tracking
# ============================================================================

class TaskResult(BaseModel):
    """
    Result from task execution with Pydantic validation.
    
    Validated task results for aggregation.
    Field names aligned with JobRecord/TaskRecord for consistency.
    """
    task_id: str = Field(..., min_length=1, max_length=100)
    job_id: str = Field(..., min_length=64, max_length=64)
    stage_number: int = Field(..., ge=1, le=100)
    task_type: str = Field(..., min_length=1, max_length=50)
    status: TaskStatus
    result_data: Optional[Dict[str, Any]] = Field(None, description="Task execution results")
    error_details: Optional[str] = Field(None, max_length=5000, description="Error details if failed")
    execution_time_seconds: float = Field(default=0.0, ge=0.0)
    memory_usage_mb: float = Field(default=0.0, ge=0.0)
    processed_items: int = Field(default=0, ge=0)
    completed_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    large_metadata_path: Optional[str] = Field(None, max_length=500, description="Blob storage path for large results")
    
    @property
    def success(self) -> bool:
        """Check if task completed successfully"""
        # Status should always be a TaskStatus enum, not a string
        return self.status == TaskStatus.COMPLETED
    
    model_config = ConfigDict(validate_assignment=True)
        # Removed use_enum_values - enums should remain as enums for type safety


@dataclass
class StageResult:
    """Result from stage execution - lightweight internal aggregation"""
    stage_number: int
    stage_name: str
    status: StageStatus
    task_results: List[TaskResult]
    execution_time_seconds: float = 0.0
    completed_at: Optional[str] = None
    
    @property
    def task_count(self) -> int:
        """Total number of tasks in stage"""
        return len(self.task_results)
    
    @property
    def successful_tasks(self) -> int:
        """Number of successful tasks"""
        return sum(1 for task in self.task_results if task.success)
    
    @property
    def failed_tasks(self) -> int:
        """Number of failed tasks"""
        return sum(1 for task in self.task_results if not task.success)
    
    @property
    def success_rate(self) -> float:
        """Success rate percentage"""
        if self.task_count == 0:
            return 0.0
        return (self.successful_tasks / self.task_count) * 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'stage_number': self.stage_number,
            'stage_name': self.stage_name,
            'status': self.status.value,
            'task_count': self.task_count,
            'successful_tasks': self.successful_tasks,
            'failed_tasks': self.failed_tasks,
            'success_rate': self.success_rate,
            'execution_time_seconds': self.execution_time_seconds,
            'completed_at': self.completed_at,
            'task_results': [task.model_dump() if hasattr(task, 'model_dump') else task.to_dict() for task in self.task_results]
        }


@dataclass
class JobResult:
    """Final result from job execution - lightweight internal aggregation"""
    job_id: str
    job_type: str
    status: JobStatus
    stage_results: List[StageResult]
    execution_time_seconds: float = 0.0
    completed_at: Optional[str] = None
    
    @property
    def total_stages(self) -> int:
        """Total number of stages"""
        return len(self.stage_results)
    
    @property
    def successful_stages(self) -> int:
        """Number of successful stages"""
        return sum(1 for stage in self.stage_results if stage.status == StageStatus.COMPLETED)
    
    @property
    def total_tasks(self) -> int:
        """Total number of tasks across all stages"""
        return sum(stage.task_count for stage in self.stage_results)
    
    @property
    def successful_tasks(self) -> int:
        """Total number of successful tasks"""
        return sum(stage.successful_tasks for stage in self.stage_results)
    
    @property
    def failed_tasks(self) -> int:
        """Total number of failed tasks"""
        return sum(stage.failed_tasks for stage in self.stage_results)
    
    @property
    def overall_success_rate(self) -> float:
        """Overall success rate across all tasks"""
        if self.total_tasks == 0:
            return 0.0
        return (self.successful_tasks / self.total_tasks) * 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'job_id': self.job_id,
            'job_type': self.job_type,
            'status': self.status.value,
            'total_stages': self.total_stages,
            'successful_stages': self.successful_stages,
            'total_tasks': self.total_tasks,
            'successful_tasks': self.successful_tasks,
            'failed_tasks': self.failed_tasks,
            'overall_success_rate': self.overall_success_rate,
            'execution_time_seconds': self.execution_time_seconds,
            'completed_at': self.completed_at,
            'stage_results': [stage.to_dict() for stage in self.stage_results]
        }


class JobCompletionResult(BaseModel):
    """
    Result from PostgreSQL check_job_completion() function.
    Represents the contract between SQL and Python layers.
    """
    job_complete: bool  # Standardized field name (was is_complete)
    final_stage: int
    total_tasks: int
    completed_tasks: int
    task_results: List[Dict[str, Any]] = Field(default_factory=list)
    
    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage"""
        if self.total_tasks == 0:
            return 100.0
        return (self.completed_tasks / self.total_tasks) * 100.0
    
    @property
    def remaining_tasks(self) -> int:
        """Number of tasks remaining"""
        return max(0, self.total_tasks - self.completed_tasks)


class TaskCompletionResult(BaseModel):
    """
    Result from PostgreSQL complete_task_and_check_stage() function.
    Represents the contract between SQL and Python layers.
    """
    task_updated: bool
    stage_complete: bool
    job_id: Optional[str] = None
    stage_number: Optional[int] = None
    remaining_tasks: int = 0


class StageAdvancementResult(BaseModel):
    """
    Result from PostgreSQL advance_job_stage() function.
    Represents the contract between SQL and Python layers.
    """
    job_updated: bool
    new_stage: Optional[int] = None
    is_final_stage: Optional[bool] = None


# ============================================================================
# BASE CLASSES WITH CONTRACTS (Pydantic + ABC) - Unified data & behavior
# ============================================================================

# Note: BaseController has been moved to controller_base.py to avoid duplication
# Import from controller_base when needed: from controller_base import BaseController

# NOTE: BaseTask, BaseJob, and BaseStage classes removed (11 Sept 2025)
# These mixed data+behavior classes violated separation of concerns.
# Use schema_* files for data models and controller_* files for behavior.


# ============================================================================
# EXCEPTIONS
# ============================================================================

class SchemaValidationError(Exception):
    """Custom exception for schema validation errors"""
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        self.field = field
        self.value = value
        super().__init__(message)


# ============================================================================
# CONFIGURATION
# ============================================================================

class SchemaConfig:
    """Global schema configuration settings"""
    MAX_PARAMETER_SIZE_BYTES = 65536  # 64KB max for parameters
    MAX_RESULT_DATA_SIZE_BYTES = 1048576  # 1MB max for results
    MAX_ERROR_MESSAGE_LENGTH = 5000
    MAX_RETRIES = 10
    DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes
    HEARTBEAT_INTERVAL_SECONDS = 30