# ============================================================================
# DAG WORKER CONTRACTS
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Message schemas for DAG tasks
# PURPOSE: Define TaskMessage (input) and TaskResult (output) schemas
# CREATED: 29 JAN 2026
# ============================================================================
"""
DAG Worker Contracts

Message schemas that match the orchestrator's expectations.
These are the contract between orchestrator and worker.

TaskMessage: What the orchestrator sends (via Service Bus)
TaskResult: What the worker reports back (via HTTP callback)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task execution status."""
    RECEIVED = "received"      # Worker received message
    RUNNING = "running"        # Handler executing
    COMPLETED = "completed"    # Success
    FAILED = "failed"          # Error


class TaskMessage(BaseModel):
    """
    Message received from the orchestrator via Service Bus.

    This is what the worker receives when a task is dispatched.
    """
    # Identity
    task_id: str = Field(..., max_length=128)
    job_id: str = Field(..., max_length=64)
    node_id: str = Field(..., max_length=64)

    # What to execute
    handler: str = Field(..., max_length=64, description="Handler function name")
    params: Dict[str, Any] = Field(default_factory=dict)

    # Execution constraints
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    retry_count: int = Field(default=0, ge=0)

    # Dispatch metadata
    dispatched_at: Optional[datetime] = None
    correlation_id: Optional[str] = None

    @classmethod
    def from_queue_message(cls, data: Dict[str, Any]) -> "TaskMessage":
        """
        Deserialize from Service Bus message body.

        Args:
            data: Parsed JSON from message body

        Returns:
            TaskMessage instance
        """
        # Handle datetime parsing
        if isinstance(data.get("dispatched_at"), str):
            data["dispatched_at"] = datetime.fromisoformat(
                data["dispatched_at"].replace("Z", "+00:00")
            )
        return cls(**data)


class TaskResult(BaseModel):
    """
    Result reported back to the orchestrator.

    Workers POST this to the orchestrator's callback endpoint.
    """
    # Identity (echo back from TaskMessage)
    task_id: str = Field(..., max_length=128)
    job_id: str = Field(..., max_length=64)
    node_id: str = Field(..., max_length=64)

    # Result
    status: TaskStatus
    output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Handler result data (on success)"
    )
    error_message: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Error details (on failure)"
    )

    # Execution metadata
    worker_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Identifier of this worker instance"
    )
    execution_duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="How long execution took"
    )

    # Timestamp
    reported_at: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def success(
        cls,
        task: TaskMessage,
        output: Dict[str, Any],
        duration_ms: int,
        worker_id: Optional[str] = None,
    ) -> "TaskResult":
        """Factory for successful result."""
        return cls(
            task_id=task.task_id,
            job_id=task.job_id,
            node_id=task.node_id,
            status=TaskStatus.COMPLETED,
            output=output,
            worker_id=worker_id,
            execution_duration_ms=duration_ms,
        )

    @classmethod
    def failure(
        cls,
        task: TaskMessage,
        error_message: str,
        duration_ms: int,
        worker_id: Optional[str] = None,
    ) -> "TaskResult":
        """Factory for failed result."""
        return cls(
            task_id=task.task_id,
            job_id=task.job_id,
            node_id=task.node_id,
            status=TaskStatus.FAILED,
            error_message=error_message[:2000],
            worker_id=worker_id,
            execution_duration_ms=duration_ms,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for HTTP POST."""
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "node_id": self.node_id,
            "status": self.status.value,
            "output": self.output,
            "error_message": self.error_message,
            "worker_id": self.worker_id,
            "execution_duration_ms": self.execution_duration_ms,
        }
