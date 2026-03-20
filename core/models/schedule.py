# ============================================================================
# CLAUDE CONTEXT - SCHEDULE MODEL
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Core - Pydantic model for scheduled workflow execution
# PURPOSE: Maps to app.schedules table — cron-based workflow submission
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: Schedule
# DEPENDENCIES: pydantic, datetime, core.models.workflow_enums
# ============================================================================
"""
Schedule — defines a recurring cron-based workflow submission.

Table: app.schedules
Primary Key: schedule_id (SHA256 of workflow_name + sorted parameters)
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from .workflow_enums import ScheduleStatus


class Schedule(BaseModel):
    """
    Schedule — one cron-based trigger for repeated workflow submissions.

    schedule_id is derived deterministically from workflow_name and parameters
    (SHA256), so duplicate schedule definitions are idempotent.
    """
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    @field_serializer('created_at', 'updated_at', 'last_run_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "schedules"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["schedule_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {
            "columns": ["status"],
            "name": "idx_schedules_active",
            "partial_where": "status = 'active'",
        },
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    schedule_id: str = Field(
        ...,
        max_length=64,
        description="SHA256(workflow_name + sorted(parameters)) — deterministic PK",
    )
    workflow_name: str = Field(
        ...,
        max_length=100,
        description="Registered YAML workflow to submit on each firing",
    )

    # =========================================================================
    # EXECUTION CONFIGURATION
    # =========================================================================
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSONB parameters passed to workflow_run at submission time",
    )
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of what this schedule does",
    )
    cron_expression: str = Field(
        ...,
        max_length=100,
        description="5-field cron expression (UTC), e.g. '0 6 * * *'",
    )
    status: ScheduleStatus = Field(
        default=ScheduleStatus.ACTIVE,
        description="active -> paused | disabled",
    )
    max_concurrent: int = Field(
        default=1,
        ge=1,
        description="Maximum number of concurrent workflow runs allowed for this schedule",
    )

    # =========================================================================
    # RUN TRACKING
    # =========================================================================
    last_run_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of most recent successful firing",
    )
    last_run_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="run_id of the most recently submitted workflow_run",
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the schedule was created",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of most recent update",
    )
