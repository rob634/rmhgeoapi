# ============================================================================
# GUARDIAN AUDIT MODELS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Core - Maintenance operation audit trail
# PURPOSE: Track SystemGuardian sweeps and legacy janitor runs
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: JanitorRun, JanitorRunType, JanitorRunStatus
# DEPENDENCIES: pydantic
# ============================================================================
"""
Guardian/Janitor Audit Models.

Pydantic models for janitor_runs audit table. Logs all SystemGuardian
sweep operations and legacy maintenance runs for audit and monitoring.

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
    """Types of maintenance runs."""
    SWEEP = "sweep"
    TASK_WATCHDOG = "task_watchdog"       # Legacy
    JOB_HEALTH = "job_health"             # Legacy
    ORPHAN_DETECTOR = "orphan_detector"   # Legacy


class JanitorRunStatus(str, Enum):
    """Status of a maintenance run."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JanitorRun(BaseModel):
    """
    Database representation of a maintenance run.

    Records all SystemGuardian sweep operations for audit trail and monitoring.
    Each sweep() call creates one JanitorRun record.

    Fields:
    - run_id: Unique identifier (UUID)
    - run_type: Type of operation (sweep for SystemGuardian)
    - started_at: When the run started
    - completed_at: When the run completed (optional until done)
    - status: Current status (running/completed/failed)
    - items_scanned: Number of records examined
    - items_fixed: Number of records updated/fixed
    - actions_taken: Flat list of all actions performed
    - phases: Per-phase breakdown (sweep runs only)
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
        description="Type of run (sweep, task_watchdog, job_health, orphan_detector)"
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
    phases: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-phase breakdown for sweep runs"
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
