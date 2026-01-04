# ============================================================================
# STAGE MODEL - REFERENCE SCHEMA (NOT USED BY JOBS)
# ============================================================================
# STATUS: Core - Reference schema documentation only
# PURPOSE: Pydantic Stage model for potential runtime validation
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# NOTE: Production jobs use plain dicts for stages, not this Pydantic model.
#       Kept as reference and for potential future CoreMachine validation.
# ============================================================================

"""
Stage Model - Pydantic Stage Definition (NOT USED BY JOBS)

⚠️ WARNING: This Pydantic model is NOT used by production jobs! ⚠️

This model represents the Pydantic Stage schema that was planned for use with
the Workflow ABC pattern, but production jobs use plain dicts instead.

For actual job stage definitions, see:
- jobs/hello_world.py (stages as plain dicts)
- jobs/create_h3_base.py (stages as plain dicts)
- jobs/process_raster.py (stages as plain dicts)

This file is kept as reference documentation to show the expected structure
of stage definitions, and could be used for future runtime validation.
"""

from pydantic import BaseModel, Field, ConfigDict
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

    model_config = ConfigDict(frozen=True)

    stage_num: int = Field(..., ge=1, description="Stage number (1-based)")
    stage_name: str = Field(..., description="Human-readable stage name")
    task_types: List[str] = Field(..., description="Task types for this stage")
    parallel: bool = Field(default=True, description="Run tasks in parallel")
    determines_task_count: bool = Field(
        default=False,
        description="True if this stage dynamically determines task count for next stage"
    )
