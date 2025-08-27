"""
State management models for job and task tracking - Phase 0 POC
"""
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
import json


class JobState(Enum):
    """Job states with clear transitions"""
    INITIALIZED = "INITIALIZED"
    PLANNING = "PLANNING"
    PROCESSING = "PROCESSING"
    FINALIZING = "FINALIZING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"  # Circuit breaker triggered


class TaskState(Enum):
    """Task states"""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobType(Enum):
    """Job types with processing patterns"""
    SIMPLE_COG = "simple_cog"  # Single file < 4GB
    MONSTER_COG = "monster_cog"  # Single file > 10GB requiring chunks
    MULTI_MERGE_COG = "multi_merge_cog"  # Multiple files to merge


class TaskType(Enum):
    """Task types that can be executed"""
    ANALYZE_INPUT = "analyze_input"
    PROCESS_CHUNK = "process_chunk"
    ASSEMBLE_CHUNKS = "assemble_chunks"
    BUILD_VRT = "build_vrt"
    CREATE_COG = "create_cog"
    VALIDATE = "validate"


class ValidationLevel(Enum):
    """Validation strictness levels"""
    STRICT = "STRICT"
    STANDARD = "STANDARD"
    LENIENT = "LENIENT"


@dataclass
class JobRecord:
    """Job tracking record for Table Storage"""
    job_id: str
    status: JobState
    operation_type: JobType
    input_paths: List[str]
    output_path: str
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    created_at: datetime = None
    updated_at: datetime = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata_blob: Optional[str] = None  # Reference to blob for large metadata
    validation_level: ValidationLevel = ValidationLevel.STANDARD
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()
    
    def to_entity(self) -> Dict[str, Any]:
        """Convert to Table Storage entity"""
        entity = {
            'PartitionKey': 'job',
            'RowKey': self.job_id,
            'status': self.status.value,
            'operation_type': self.operation_type.value,
            'input_paths': json.dumps(self.input_paths),
            'output_path': self.output_path,
            'total_tasks': self.total_tasks,
            'completed_tasks': self.completed_tasks,
            'failed_tasks': self.failed_tasks,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'error_message': self.error_message,
            'metadata_blob': self.metadata_blob,
            'validation_level': self.validation_level.value
        }
        return entity
    
    @classmethod
    def from_entity(cls, entity: Dict[str, Any]) -> 'JobRecord':
        """Create from Table Storage entity"""
        return cls(
            job_id=entity['RowKey'],
            status=JobState(entity['status']),
            operation_type=JobType(entity['operation_type']),
            input_paths=json.loads(entity['input_paths']),
            output_path=entity['output_path'],
            total_tasks=entity.get('total_tasks', 0),
            completed_tasks=entity.get('completed_tasks', 0),
            failed_tasks=entity.get('failed_tasks', 0),
            created_at=datetime.fromisoformat(entity['created_at']) if entity.get('created_at') else None,
            updated_at=datetime.fromisoformat(entity['updated_at']) if entity.get('updated_at') else None,
            completed_at=datetime.fromisoformat(entity['completed_at']) if entity.get('completed_at') else None,
            error_message=entity.get('error_message'),
            metadata_blob=entity.get('metadata_blob'),
            validation_level=ValidationLevel(entity.get('validation_level', 'STANDARD'))
        )


@dataclass
class TaskRecord:
    """Task tracking record for Table Storage"""
    task_id: str
    job_id: str
    status: TaskState
    task_type: TaskType
    sequence_number: int
    input_path: str
    output_path: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    processing_metadata_blob: Optional[str] = None  # Reference to detailed logs
    
    def to_entity(self) -> Dict[str, Any]:
        """Convert to Table Storage entity"""
        entity = {
            'PartitionKey': self.job_id,
            'RowKey': self.task_id,
            'status': self.status.value,
            'task_type': self.task_type.value,
            'sequence_number': self.sequence_number,
            'input_path': self.input_path,
            'output_path': self.output_path,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': self.duration_seconds,
            'retry_count': self.retry_count,
            'error_message': self.error_message,
            'processing_metadata_blob': self.processing_metadata_blob
        }
        return entity
    
    @classmethod
    def from_entity(cls, entity: Dict[str, Any]) -> 'TaskRecord':
        """Create from Table Storage entity"""
        return cls(
            task_id=entity['RowKey'],
            job_id=entity['PartitionKey'],
            status=TaskState(entity['status']),
            task_type=TaskType(entity['task_type']),
            sequence_number=entity.get('sequence_number', 0),
            input_path=entity['input_path'],
            output_path=entity['output_path'],
            started_at=datetime.fromisoformat(entity['started_at']) if entity.get('started_at') else None,
            completed_at=datetime.fromisoformat(entity['completed_at']) if entity.get('completed_at') else None,
            duration_seconds=entity.get('duration_seconds'),
            retry_count=entity.get('retry_count', 0),
            error_message=entity.get('error_message'),
            processing_metadata_blob=entity.get('processing_metadata_blob')
        )


@dataclass
class JobMessage:
    """Message for job queue"""
    job_id: str
    operation_type: str
    input_paths: List[str]
    output_path: str
    parameters: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'JobMessage':
        return cls(**data)


@dataclass 
class TaskMessage:
    """Message for task queue"""
    task_id: str
    job_id: str
    task_type: str
    sequence_number: int = 0
    parameters: Dict[str, Any] = None
    # Allow additional fields from controller task data
    dataset_id: Optional[str] = None
    resource_id: Optional[str] = None
    version_id: Optional[str] = None
    operation: Optional[str] = None
    parent_job_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskMessage':
        # Handle flexible task data from controllers
        # Extract known fields first
        known_fields = {
            'task_id', 'job_id', 'task_type', 'sequence_number', 'parameters',
            'dataset_id', 'resource_id', 'version_id', 'operation', 'parent_job_id'
        }
        
        task_msg_data = {}
        extra_parameters = {}
        
        for key, value in data.items():
            if key in known_fields:
                task_msg_data[key] = value
            else:
                # Put unknown fields in parameters
                extra_parameters[key] = value
        
        # Merge extra parameters into the parameters dict
        if extra_parameters:
            existing_params = task_msg_data.get('parameters', {}) or {}
            existing_params.update(extra_parameters)
            task_msg_data['parameters'] = existing_params
            
        return cls(**task_msg_data)


# State transition rules
STATE_TRANSITIONS = {
    JobState.INITIALIZED: [JobState.PLANNING, JobState.FAILED, JobState.REQUIRES_REVIEW],
    JobState.PLANNING: [JobState.PROCESSING, JobState.FAILED],
    JobState.PROCESSING: [JobState.FINALIZING, JobState.VALIDATING, JobState.FAILED],
    JobState.FINALIZING: [JobState.VALIDATING, JobState.FAILED],
    JobState.VALIDATING: [JobState.COMPLETED, JobState.FAILED],
    JobState.COMPLETED: [],
    JobState.FAILED: [JobState.INITIALIZED],  # Can retry
    JobState.REQUIRES_REVIEW: [JobState.INITIALIZED, JobState.FAILED]  # Manual intervention
}


def can_transition(from_state: JobState, to_state: JobState) -> bool:
    """Check if state transition is valid"""
    return to_state in STATE_TRANSITIONS.get(from_state, [])