# ============================================================================
# CLAUDE CONTEXT - WORKFLOW RUN MODEL (DAG EXECUTION TRACKING)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - D.2 DAG Database Tables
# PURPOSE: Pydantic model for workflow_runs table — tracks DAG workflow executions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowRun
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
WorkflowRun — tracks execution of a YAML workflow DAG.

Replaces app.jobs for DAG workflows. Legacy jobs remain in app.jobs
during the strangler fig migration.

Table: app.workflow_runs
Primary Key: run_id
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from .workflow_enums import WorkflowRunStatus


class WorkflowRun(BaseModel):
    """
    Workflow run — one execution of a YAML workflow definition.

    The definition JSONB is a snapshot of the YAML at submission time,
    making each run self-contained and immune to workflow file changes.
    """
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    @field_serializer('created_at', 'started_at', 'completed_at')
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS (ClassVar = not a model field)
    # =========================================================================
    __sql_table_name: ClassVar[str] = "workflow_runs"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["run_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {}
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["workflow_name"], "name": "idx_workflow_runs_workflow_name"},
        {"columns": ["status"], "name": "idx_workflow_runs_status",
         "partial_where": "status IN ('pending', 'running')"},
        {"columns": ["created_at"], "name": "idx_workflow_runs_created", "descending": True},
        {"columns": ["request_id"], "name": "idx_workflow_runs_request",
         "partial_where": "request_id IS NOT NULL"},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    run_id: str = Field(..., max_length=64, description="Unique run identifier")
    workflow_name: str = Field(..., max_length=100, description="Workflow identifier from YAML")

    # =========================================================================
    # EXECUTION STATE
    # =========================================================================
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Validated input parameters")
    status: WorkflowRunStatus = Field(
        default=WorkflowRunStatus.PENDING,
        description="pending -> running -> completed | failed"
    )
    definition: Dict[str, Any] = Field(
        default_factory=dict,
        description="YAML snapshot at submission time (immutable)"
    )
    platform_version: str = Field(..., max_length=20, description="App version at submission")
    result_data: Optional[Dict[str, Any]] = Field(default=None, description="Final workflow results")

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = Field(default=None, description="When first task claimed")
    completed_at: Optional[datetime] = Field(default=None, description="When workflow finished")

    # =========================================================================
    # PLATFORM INTEGRATION
    # =========================================================================
    request_id: Optional[str] = Field(default=None, max_length=100, description="B2B request_id for status lookups")
    asset_id: Optional[str] = Field(default=None, max_length=64, description="Linked asset")
    release_id: Optional[str] = Field(default=None, max_length=64, description="Linked release")

    # =========================================================================
    # SCHEDULER INTEGRATION
    # =========================================================================
    schedule_id: Optional[str] = Field(default=None, max_length=64, description="Source schedule (NULL = platform-submitted or manual)")

    # =========================================================================
    # MIGRATION BRIDGE
    # =========================================================================
    legacy_job_id: Optional[str] = Field(default=None, max_length=64, description="Link to app.jobs during strangler fig")
