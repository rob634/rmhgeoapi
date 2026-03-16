# ============================================================================
# CLAUDE CONTEXT - WORKFLOW TASK DEPENDENCY MODEL (DAG EDGES)
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Core - D.2 DAG Database Tables
# PURPOSE: Pydantic model for workflow_task_deps table — DAG edge definitions
# LAST_REVIEWED: 16 MAR 2026
# EXPORTS: WorkflowTaskDep
# DEPENDENCIES: pydantic
# ============================================================================
"""
WorkflowTaskDep — DAG edge between two task instances.

Created at workflow initialization time. Each depends_on entry in YAML
becomes one row. Conditional next: pointers also become edges.

Table: app.workflow_task_deps
Primary Key: (task_instance_id, depends_on_instance_id) — composite
Foreign Keys: Both columns reference app.workflow_tasks(task_instance_id)
"""

from typing import Dict, Any, List, ClassVar
from pydantic import BaseModel, Field, ConfigDict


class WorkflowTaskDep(BaseModel):
    """DAG edge: task_instance_id depends on depends_on_instance_id."""
    model_config = ConfigDict(extra='ignore', str_strip_whitespace=True)

    # =========================================================================
    # DDL GENERATION HINTS
    # =========================================================================
    __sql_table_name: ClassVar[str] = "workflow_task_deps"
    __sql_schema: ClassVar[str] = "app"
    __sql_primary_key: ClassVar[List[str]] = ["task_instance_id", "depends_on_instance_id"]
    __sql_foreign_keys: ClassVar[Dict[str, str]] = {
        "task_instance_id": "app.workflow_tasks(task_instance_id)",
        "depends_on_instance_id": "app.workflow_tasks(task_instance_id)",
    }
    __sql_unique_constraints: ClassVar[List[Dict[str, Any]]] = []
    __sql_indexes: ClassVar[List[Dict[str, Any]]] = []

    # =========================================================================
    # EDGE DEFINITION
    # =========================================================================
    task_instance_id: str = Field(
        ..., max_length=100,
        description="The task that has this dependency"
    )
    depends_on_instance_id: str = Field(
        ..., max_length=100,
        description="The task that must complete first"
    )
    optional: bool = Field(
        default=False,
        description="If true, tolerates skipped (not failed) dependency"
    )
