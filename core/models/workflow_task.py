# ============================================================================
# CLAUDE CONTEXT - WORKFLOW TASK MODEL (DAG NODE EXECUTION)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - D.2 DAG Database Tables
# PURPOSE: Pydantic model for workflow_tasks table — individual node executions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowTask
# DEPENDENCIES: pydantic, datetime
# ============================================================================
"""
WorkflowTask — one task instance within a workflow run.

Each YAML node becomes one WorkflowTask row when the DAG is initialized.
Fan-out nodes expand into N rows (one per array element) with fan_out_index.

Table: app.workflow_tasks
Primary Key: task_instance_id
Foreign Key: run_id -> app.workflow_runs(run_id)
Unique: (run_id, task_name, fan_out_index)
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict, field_serializer

from .workflow_enums import WorkflowTaskStatus


class WorkflowTask(BaseModel):
    """
    Workflow task instance — runtime execution of a YAML node.

    Workers claim ready tasks via SELECT FOR UPDATE SKIP LOCKED,
    same pattern as app.tasks (v0.10.3 DB-polling).
    """
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    @field_serializer(
        'last_pulse', 'execute_after', 'started_at', 'completed_at',
        'created_at', 'updated_at'
    )
    @classmethod
    def serialize_datetime(cls, v: datetime) -> Optional[str]:
        return v.isoformat() if v else None

    # =========================================================================
    # DDL GENERATION HINTS
    # =========================================================================
    __sql_table_name: ClassVar[str] = "workflow_tasks"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["task_instance_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "run_id": "app.workflow_runs(run_id)",
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = [
        {
            "columns": ["run_id", "task_name", "fan_out_index"],
            "name": "uq_workflow_task_identity",
        }
    ]
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = [
        {"columns": ["run_id"], "name": "idx_workflow_tasks_run"},
        {"columns": ["status"], "name": "idx_workflow_tasks_status",
         "partial_where": "status IN ('pending', 'ready', 'running')"},
        {"columns": ["status", "last_pulse"], "name": "idx_workflow_tasks_stale",
         "partial_where": "status = 'running'"},
        {"columns": ["status", "execute_after", "created_at"],
         "name": "idx_workflow_tasks_ready_poll",
         "partial_where": "status = 'ready'"},
    ]

    # =========================================================================
    # IDENTITY
    # =========================================================================
    task_instance_id: str = Field(..., max_length=100, description="Unique task instance ID")
    run_id: str = Field(..., max_length=64, description="FK to workflow_runs")
    task_name: str = Field(..., max_length=100, description="Node name from YAML")
    handler: str = Field(..., max_length=100, description="Handler name from ALL_HANDLERS")

    # =========================================================================
    # EXECUTION STATE
    # =========================================================================
    status: WorkflowTaskStatus = Field(
        default=WorkflowTaskStatus.PENDING,
        description="Task lifecycle status"
    )

    # =========================================================================
    # FAN-OUT TRACKING
    # =========================================================================
    fan_out_index: Optional[int] = Field(
        default=None, description="0..N for fan-out instances, NULL for regular tasks"
    )
    fan_out_source: Optional[str] = Field(
        default=None, max_length=100,
        description="Node name that produced the fan-out array"
    )

    # =========================================================================
    # CONDITIONAL / SKIP
    # =========================================================================
    when_clause: Optional[str] = Field(
        default=None, max_length=500,
        description="Condition expression from YAML (NULL = unconditional)"
    )

    # =========================================================================
    # PARAMETERS & RESULTS
    # =========================================================================
    parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="Resolved parameters at execution time"
    )
    result_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Handler output"
    )
    error_details: Optional[str] = Field(default=None, description="Error message if failed")

    # =========================================================================
    # RETRY
    # =========================================================================
    retry_count: int = Field(default=0, ge=0, description="Number of retry attempts")
    max_retries: int = Field(default=3, ge=0, description="Max retries before permanent failure")

    # =========================================================================
    # WORKER CLAIM (DB-POLLING)
    # =========================================================================
    claimed_by: Optional[str] = Field(
        default=None, max_length=100,
        description="Worker ID that claimed this task (NULL when unclaimed)"
    )
    last_pulse: Optional[datetime] = Field(
        default=None, description="Heartbeat from worker during execution"
    )
    execute_after: Optional[datetime] = Field(
        default=None, description="Scheduled execution time (NULL = immediate, set for retry backoff)"
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    started_at: Optional[datetime] = Field(default=None, description="When worker started execution")
    completed_at: Optional[datetime] = Field(default=None, description="When task finished")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
