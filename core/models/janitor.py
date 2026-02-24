# ============================================================================
# JANITOR AUDIT MODELS
# ============================================================================
# STATUS: Core - Maintenance operation audit trail
# PURPOSE: Track janitor runs for task watchdog, job health, orphan detection
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Janitor Audit Models.

Pydantic models for janitor_runs audit table. Logs all janitor
maintenance operations for audit and monitoring purposes.

Exports:
    JanitorRun: Audit record for maintenance operations
    JanitorRunType: Types of maintenance runs
    JanitorRunStatus: Run status enumeration
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, field_serializer
import uuid


class JanitorRunType(str, Enum):
    """Types of janitor maintenance runs."""
    TASK_WATCHDOG = "task_watchdog"
    JOB_HEALTH = "job_health"
    ORPHAN_DETECTOR = "orphan_detector"


class JanitorRunStatus(str, Enum):
    """Status of a janitor run."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JanitorRun(BaseModel):
    """
    Database representation of a janitor maintenance run.

    Records all janitor operations for audit trail and monitoring.
    Each timer trigger execution creates one JanitorRun record.

    Fields:
    - run_id: Unique identifier (UUID)
    - run_type: Type of janitor operation
    - started_at: When the run started
    - completed_at: When the run completed (optional until done)
    - status: Current status (running/completed/failed)
    - items_scanned: Number of records examined
    - items_fixed: Number of records updated/fixed
    - actions_taken: Detailed list of actions performed
    - error_details: Error message if run failed
    - duration_ms: Run duration in milliseconds
    """

    model_config = ConfigDict()

    @field_serializer('started_at', 'completed_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # Primary key
    run_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique run identifier (UUID)"
    )

    # Run classification
    run_type: str = Field(
        ...,
        description="Type of janitor run (task_watchdog, job_health, orphan_detector)"
    )

    # Timing
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the run started"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the run completed"
    )
    duration_ms: Optional[int] = Field(
        default=None,
        description="Run duration in milliseconds"
    )

    # Status
    status: str = Field(
        default="running",
        description="Run status (running, completed, failed)"
    )

    # Statistics
    items_scanned: int = Field(
        default=0,
        ge=0,
        description="Number of records scanned"
    )
    items_fixed: int = Field(
        default=0,
        ge=0,
        description="Number of records fixed"
    )

    # Details
    actions_taken: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of actions taken during the run"
    )
    error_details: Optional[str] = Field(
        default=None,
        description="Error message if the run failed"
    )


# Module exports
__all__ = [
    'JanitorRun',
    'JanitorRunType',
    'JanitorRunStatus'
]
