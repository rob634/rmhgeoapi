# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Core Pydantic data models for Job→Stage→Task architecture foundation
# SOURCE: No direct configuration - provides type-safe data model definitions
# SCOPE: Global data model foundation for all workflow components and persistence
# VALIDATION: Pydantic v2 model validation with custom validators and field constraints
# ============================================================================

"""
Core Data Models - Job→Stage→Task Architecture Foundation

Comprehensive data model definitions forming the backbone of the Azure Geospatial ETL Pipeline's
strong typing discipline. Provides type-safe dataclasses, enumerations, context objects, and
result structures that enforce architectural patterns and enable reliable inter-component
communication throughout the Job→Stage→Task workflow system.

Architecture Foundation:
    This module establishes the fundamental data structures for the entire pipeline:
    - Job Layer: JobRecord, JobResult, JobExecutionContext for workflow orchestration
    - Stage Layer: StageDefinition, StageResult, StageExecutionContext for coordination
    - Task Layer: TaskDefinition, TaskResult, TaskExecutionContext for business logic
    - Queue Layer: JobQueueMessage, TaskQueueMessage for asynchronous processing
    - Storage Layer: Record classes for database persistence

Key Features:
- Comprehensive dataclass definitions with validation and property methods
- Strongly typed enumerations for status tracking across all workflow levels
- Context objects providing execution state and parameter passing mechanisms
- Result objects with built-in analytics (success rates, timing, metadata)
- Queue message formats for reliable asynchronous processing
- Database record structures with factory methods for ORM integration
- Type-safe property accessors and computed values throughout

Type Safety Benefits:
- IDE autocompletion and type checking for all model interactions
- Runtime validation through dataclass field types and constraints
- Clear contracts between components preventing integration errors
- Consistent data structures across HTTP triggers, controllers, and services
- Standardized JSON serialization with to_dict() methods

Workflow Data Flow:
    HTTP Request → JobRecord (storage) → JobQueueMessage (async)
         ↓                                      ↓
    Job Controller ← JobExecutionContext ← Queue Processor
         ↓                                      ↓
    Stage Creation → StageExecutionContext → Task Creation
         ↓                                      ↓  
    TaskQueueMessage → Task Execution → TaskResult
         ↓                                      ↓
    StageResult ← Result Aggregation ← Task Completion
         ↓                                      ↓
    JobResult → Final Storage → HTTP Response

Context Objects:
- JobExecutionContext: Orchestrates multi-stage workflow with result passing
- StageExecutionContext: Coordinates parallel task execution with completion tracking  
- TaskExecutionContext: Provides business logic execution environment with retries

Integration Points:
- Used by all controller classes for job orchestration and parameter validation
- Referenced by service layer implementations for business logic execution
- Integrated with repository layer for type-safe database operations
- Consumed by HTTP triggers for request/response transformation
- Utilized by queue processors for reliable message handling

Usage Examples:
    # Job creation with type safety
    job_context = JobExecutionContext(
        job_id="abc123",
        job_type="hello_world",
        current_stage=1,
        total_stages=2,
        parameters={"message": "Hello World"}
    )
    
    # Task execution with context
    task_context = TaskExecutionContext(
        task_id="task_001",
        parent_job_id=job_context.job_id,
        stage=1,
        task_index=0,
        parameters={"task_number": 1}
    )
    
    # Result aggregation
    task_result = TaskResult(
        task_id=task_context.task_id,
        job_id=task_context.job_id,
        stage_number=1,
        task_type="hello_world_greeting",
        status=TaskStatus.COMPLETED,
        result={"greeting": "Hello from task_1!"}
    )

Author: Azure Geospatial ETL Team
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

# Import canonical status enums from schema_core (Pydantic models)
from schema_core import JobStatus, TaskStatus


# Status enumerations moved to schema_core.py for consistency
# Import from schema_core: from schema_core import JobStatus, TaskStatus

class StageStatus(Enum):
    """Stage status enumeration - Stage-specific statuses"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Definition Classes
@dataclass
class StageDefinition:
    """Stage definition for controller configuration"""
    stage_number: int
    stage_name: str
    task_type: str
    is_final_stage: bool = False
    depends_on_stage: Optional[int] = None
    max_parallel_tasks: Optional[int] = None  # None = unlimited
    
    def __post_init__(self):
        if self.stage_number < 1:
            raise ValueError("Stage number must be >= 1")
        if self.depends_on_stage and self.depends_on_stage >= self.stage_number:
            raise ValueError(f"Stage {self.stage_number} cannot depend on stage {self.depends_on_stage}")


@dataclass
class TaskDefinition:
    """Task definition for stage execution"""
    task_id: str
    task_type: str
    stage_number: int
    job_id: str
    parameters: Dict[str, Any]
    depends_on_tasks: Optional[List[str]] = None
    retry_count: int = 0
    max_retries: int = 3


# Context Classes
@dataclass
class JobExecutionContext:
    """Context information for job execution"""
    job_id: str
    job_type: str
    current_stage: int
    total_stages: int
    parameters: Dict[str, Any]
    stage_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def get_stage_result(self, stage_number: int) -> Optional[Dict[str, Any]]:
        """Get results from a specific stage"""
        return self.stage_results.get(stage_number)
    
    def set_stage_result(self, stage_number: int, result: Dict[str, Any]):
        """Set results for a specific stage"""
        self.stage_results[stage_number] = result


@dataclass 
class StageExecutionContext:
    """Context information for stage execution"""
    job_id: str
    stage_number: int
    stage_name: str
    task_type: str
    job_parameters: Dict[str, Any]
    previous_stage_results: Optional[Dict[str, Any]] = None
    task_count: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    
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


@dataclass
class TaskExecutionContext:
    """Context information for task execution"""
    task_id: str
    parent_job_id: str  # For compatibility with queue messages
    stage: int  # For compatibility with queue messages
    task_index: int
    parameters: Dict[str, Any]
    parent_stage_results: Optional[Dict[str, Any]] = None
    retry_count: int = 0
    max_retries: int = 3
    
    # Properties for compatibility with BaseTask expectations
    @property
    def job_id(self) -> str:
        """Alias for parent_job_id"""
        return self.parent_job_id
    
    @property
    def stage_number(self) -> int:
        """Alias for stage"""
        return self.stage
    
    @property
    def stage_name(self) -> str:
        """Extract stage name from parameters if available"""
        return self.parameters.get('stage_name', f'Stage_{self.stage}')
    
    @property
    def task_type(self) -> str:
        """Extract task type from parameters"""
        return self.parameters.get('task_type', 'unknown')
    
    @property
    def job_parameters(self) -> Dict[str, Any]:
        """Extract job-level parameters from parameters"""
        return self.parameters.get('job_parameters', self.parameters)
    
    @property
    def previous_stage_results(self) -> Optional[Dict[str, Any]]:
        """Alias for parent_stage_results"""
        return self.parent_stage_results
    
    @property
    def is_retry(self) -> bool:
        """Check if this is a retry attempt"""
        return self.retry_count > 0
    
    @property
    def can_retry(self) -> bool:
        """Check if task can be retried"""
        return self.retry_count < self.max_retries


# Record Classes (for database storage)
@dataclass
class JobRecord:
    """Job record for database storage"""
    id: str
    job_type: str
    status: str
    stage: int
    parameters: Dict[str, Any]
    metadata: Dict[str, Any]
    result_data: Optional[str] = None  # JSON string
    error_details: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JobRecord':
        """Create JobRecord from dictionary"""
        return cls(
            id=data['id'],
            job_type=data['job_type'],
            status=data['status'],
            stage=data['stage'],
            parameters=data['parameters'],
            metadata=data['metadata'],
            result_data=data.get('result_data'),
            error_details=data.get('error_details'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at')
        )


# TaskRecord has been moved to schema_core.py as a Pydantic model
# Import from schema_core instead: from schema_core import TaskRecord


# Queue Message Classes
@dataclass
class JobQueueMessage:
    """Message for jobs queue"""
    job_id: str
    job_type: str
    stage: int
    parameters: Dict[str, Any]
    stage_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for queue message"""
        return {
            'job_id': self.job_id,
            'job_type': self.job_type,
            'stage': self.stage,
            'parameters': self.parameters,
            'stage_results': self.stage_results,
            'retry_count': self.retry_count
        }


@dataclass
class TaskQueueMessage:
    """Message for tasks queue"""
    task_id: str
    job_id: str
    task_type: str
    stage_number: int
    parameters: Dict[str, Any]
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for queue message"""
        return {
            'task_id': self.task_id,
            'job_id': self.job_id,
            'task_type': self.task_type,
            'stage_number': self.stage_number,
            'parameters': self.parameters,
            'retry_count': self.retry_count
        }


# Completion Result Classes
@dataclass
class JobCompletionResult:
    """Result from job completion check"""
    is_complete: bool
    final_stage: int
    total_tasks: int
    completed_tasks: int
    task_results: List[Dict[str, Any]] = field(default_factory=list)
    
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


# Result Classes
@dataclass
class TaskResult:
    """Result from task execution"""
    task_id: str
    job_id: str
    stage_number: int
    task_type: str
    status: TaskStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    processed_items: int = 0
    completed_at: Optional[str] = None
    
    @property
    def success(self) -> bool:
        """Check if task completed successfully"""
        return self.status == TaskStatus.COMPLETED
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'task_id': self.task_id,
            'job_id': self.job_id,
            'stage_number': self.stage_number,
            'task_type': self.task_type,
            'status': self.status.value,
            'result': self.result,
            'error': self.error,
            'execution_time_seconds': self.execution_time_seconds,
            'memory_usage_mb': self.memory_usage_mb,
            'processed_items': self.processed_items,
            'completed_at': self.completed_at,
            'success': self.success
        }


@dataclass
class StageResult:
    """Result from stage execution"""
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
            'task_results': [task.to_dict() for task in self.task_results]
        }


@dataclass
class JobResult:
    """Final result from job execution"""
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
    def overall_success_rate(self) -> float:
        """Overall success rate percentage"""
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
            'overall_success_rate': self.overall_success_rate,
            'execution_time_seconds': self.execution_time_seconds,
            'completed_at': self.completed_at,
            'stage_results': [stage.to_dict() for stage in self.stage_results]
        }