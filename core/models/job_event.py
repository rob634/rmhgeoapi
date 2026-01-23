# ============================================================================
# CLAUDE CONTEXT - JOB EVENT TRACKING MODELS
# ============================================================================
# STATUS: Core - Execution timeline tracking for CoreMachine workflow
# PURPOSE: Track each execution step in job/task lifecycle for debugging
# CREATED: 23 JAN 2026
# LAST_REVIEWED: 23 JAN 2026
# ============================================================================
"""
Job Event Tracking Models.

Provides granular tracking of CoreMachine execution steps to enable
"last successful checkpoint" debugging for silent failures.

Key Features:
    - Tracks each execution step in job/task lifecycle
    - Enables execution timeline visualization
    - Correlates with Application Insights checkpoints
    - Supports identifying "last successful step" for debugging

Event Types:
    - Job lifecycle: created, started, completed, failed
    - Task lifecycle: queued, started, completed, failed, retrying
    - Stage transitions: stage_started, stage_completed
    - Callbacks: callback_started, callback_success, callback_failed

Exports:
    JobEventType: Event type enum
    JobEventStatus: Event outcome status
    JobEvent: Database model for event records

Dependencies:
    pydantic: Data validation
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, ClassVar
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# ENUMS
# ============================================================================

class JobEventType(str, Enum):
    """
    Types of events tracked in job/task execution.

    These correlate with checkpoint names in Application Insights
    for cross-referencing logs with database events.
    """
    # Job lifecycle events
    JOB_CREATED = "job_created"
    JOB_MESSAGE_RECEIVED = "job_message_received"
    JOB_STARTED = "job_started"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"

    # Stage events
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_ADVANCEMENT_FAILED = "stage_advancement_failed"

    # Task lifecycle events
    TASK_QUEUED = "task_queued"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_RETRYING = "task_retrying"
    TASK_NOT_FOUND = "task_not_found"

    # Callback events
    CALLBACK_STARTED = "callback_started"
    CALLBACK_SUCCESS = "callback_success"
    CALLBACK_FAILED = "callback_failed"

    # Status updates
    STATUS_UPDATE = "status_update"
    CHECKPOINT = "checkpoint"


class JobEventStatus(str, Enum):
    """
    Outcome status for tracked events.
    """
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"
    INFO = "info"
    PENDING = "pending"


# ============================================================================
# DATABASE MODELS
# ============================================================================

class JobEvent(BaseModel):
    """
    Job execution event database model.

    Tracks individual execution steps in the CoreMachine workflow
    to enable debugging of "silent failures" and visualization of
    job execution timelines.

    Auto-generates:
        CREATE TABLE app.job_events (
            event_id SERIAL PRIMARY KEY,
            job_id VARCHAR(64) NOT NULL,
            task_id VARCHAR(64),
            stage INTEGER,
            event_type VARCHAR(50) NOT NULL,
            event_status VARCHAR(20) DEFAULT 'info',
            checkpoint_name VARCHAR(100),
            event_data JSONB DEFAULT '{}',
            error_message VARCHAR(1000),
            duration_ms INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT fk_job FOREIGN KEY (job_id) REFERENCES app.jobs(job_id)
        );
    """

    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )

    # ========================================================================
    # SQL DDL METADATA (Used by PydanticToSQL generator)
    # ========================================================================
    __sql_table_name: ClassVar[str] = "job_events"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["event_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "job_id": "app.jobs(job_id)"
    }
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"name": "idx_job_events_job_id", "columns": ["job_id"]},
        {"name": "idx_job_events_task_id", "columns": ["task_id"],
         "partial_where": "task_id IS NOT NULL"},
        {"name": "idx_job_events_created_at", "columns": ["created_at"],
         "descending": True},
        {"name": "idx_job_events_event_type", "columns": ["event_type"]},
        {"name": "idx_job_events_checkpoint", "columns": ["checkpoint_name"],
         "partial_where": "checkpoint_name IS NOT NULL"},
        {"name": "idx_job_events_job_time", "columns": ["job_id", "created_at"],
         "descending": True},
    ]

    # ========================================================================
    # PRIMARY KEY (Auto-increment)
    # ========================================================================
    event_id: Optional[int] = Field(
        None,
        description="Auto-increment event ID (SERIAL)"
    )

    # ========================================================================
    # FOREIGN KEYS
    # ========================================================================
    job_id: str = Field(
        ...,
        max_length=64,
        description="Job ID this event belongs to"
    )
    task_id: Optional[str] = Field(
        None,
        max_length=64,
        description="Task ID if this is a task-level event"
    )
    stage: Optional[int] = Field(
        None,
        description="Stage number if relevant to event"
    )

    # ========================================================================
    # EVENT CLASSIFICATION
    # ========================================================================
    event_type: JobEventType = Field(
        ...,
        description="Type of event (job_created, task_completed, etc.)"
    )
    event_status: JobEventStatus = Field(
        default=JobEventStatus.INFO,
        description="Outcome status of the event"
    )
    checkpoint_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Application Insights checkpoint name for correlation"
    )

    # ========================================================================
    # EVENT DATA
    # ========================================================================
    event_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional event data (parameters, results, context)"
    )
    error_message: Optional[str] = Field(
        None,
        max_length=1000,
        description="Error message if event represents a failure"
    )
    duration_ms: Optional[int] = Field(
        None,
        description="Duration of operation in milliseconds (if measured)"
    )

    # ========================================================================
    # TIMESTAMPS
    # ========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when event occurred"
    )

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'event_id': self.event_id,
            'job_id': self.job_id,
            'task_id': self.task_id,
            'stage': self.stage,
            'event_type': self.event_type.value if isinstance(self.event_type, JobEventType) else self.event_type,
            'event_status': self.event_status.value if isinstance(self.event_status, JobEventStatus) else self.event_status,
            'checkpoint_name': self.checkpoint_name,
            'event_data': self.event_data,
            'error_message': self.error_message,
            'duration_ms': self.duration_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def create_job_event(
        cls,
        job_id: str,
        event_type: JobEventType,
        event_status: JobEventStatus = JobEventStatus.INFO,
        checkpoint_name: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
    ) -> "JobEvent":
        """
        Factory method for creating job-level events.

        Args:
            job_id: Job ID
            event_type: Type of event
            event_status: Outcome status
            checkpoint_name: Optional App Insights checkpoint correlation
            event_data: Additional event data
            error_message: Error message if failure

        Returns:
            JobEvent instance ready for database insertion
        """
        return cls(
            job_id=job_id,
            event_type=event_type,
            event_status=event_status,
            checkpoint_name=checkpoint_name,
            event_data=event_data or {},
            error_message=error_message
        )

    @classmethod
    def create_task_event(
        cls,
        job_id: str,
        task_id: str,
        stage: int,
        event_type: JobEventType,
        event_status: JobEventStatus = JobEventStatus.INFO,
        checkpoint_name: Optional[str] = None,
        event_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> "JobEvent":
        """
        Factory method for creating task-level events.

        Args:
            job_id: Parent job ID
            task_id: Task ID
            stage: Stage number
            event_type: Type of event
            event_status: Outcome status
            checkpoint_name: Optional App Insights checkpoint correlation
            event_data: Additional event data
            error_message: Error message if failure
            duration_ms: Operation duration

        Returns:
            JobEvent instance ready for database insertion
        """
        return cls(
            job_id=job_id,
            task_id=task_id,
            stage=stage,
            event_type=event_type,
            event_status=event_status,
            checkpoint_name=checkpoint_name,
            event_data=event_data or {},
            error_message=error_message,
            duration_ms=duration_ms
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'JobEventType',
    'JobEventStatus',
    'JobEvent',
]
