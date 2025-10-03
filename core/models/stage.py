# ============================================================================
# CLAUDE CONTEXT - STAGE MODEL
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component of new architecture
# PURPOSE: Simple Stage definition for workflow declarations
# EXPORTS: Stage - Pydantic model for stage definitions
# INTERFACES: Used by Workflow.define_stages()
# PYDANTIC_MODELS: Stage
# DEPENDENCIES: pydantic, typing
# SOURCE: Framework pattern from epoch4_framework.md
# SCOPE: Workflow stage definitions
# VALIDATION: Pydantic validation
# PATTERNS: Data Model
# ENTRY_POINTS: Used in jobs/workflow.py
# INDEX: Stage:30
# ============================================================================

"""
Stage Model - Workflow Stage Definition

Simple Pydantic model for defining workflow stages.
This is a simplified version focused on the framework pattern.

For complex workflow management, use core.schema.workflow.WorkflowStageDefinition.

Author: Robert and Geospatial Claude Legion
Date: 30 SEP 2025
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class Stage(BaseModel):
    """
    Simple stage definition for workflows.

    Defines a stage in a multi-stage workflow with basic orchestration info.

    Example:
        Stage(
            stage_num=1,
            stage_name="validate",
            task_types=["validate_input"],
            parallel=True
        )
    """

    stage_num: int = Field(..., ge=1, description="Stage number (1-based)")
    stage_name: str = Field(..., description="Human-readable stage name")
    task_types: List[str] = Field(..., description="Task types for this stage")
    parallel: bool = Field(default=True, description="Run tasks in parallel")
    determines_task_count: bool = Field(
        default=False,
        description="True if this stage dynamically determines task count for next stage"
    )

    class Config:
        """Pydantic configuration"""
        frozen = True  # Immutable after creation
