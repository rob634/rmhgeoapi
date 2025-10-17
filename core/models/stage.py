# ============================================================================
# ⚠️ PYDANTIC MODEL - NOT USED BY ACTUAL JOBS ⚠️
# ============================================================================
# EPOCH: 4 - REFERENCE ONLY
# STATUS: Unused by jobs - kept as reference schema documentation
# PURPOSE: Pydantic Stage model (planned but not used by production jobs)
# ACTUAL USAGE: Jobs use List[Dict[str, Any]] for stages, not List[Stage]
#
# THIS PYDANTIC MODEL EXISTS BUT IS NOT USED BY JOBS!
# Production jobs use plain dicts for stages. CoreMachine reads these dicts
# directly without Pydantic validation (could be added in future).
#
# PLANNED ARCHITECTURE (Workflow ABC pattern - unused):
#   from core.models import Stage
#
#   class HelloWorldWorkflow(Workflow):
#       def define_stages(self) -> List[Stage]:  # ← This Pydantic model
#           return [
#               Stage(stage_num=1, stage_name="greeting", task_types=["greet"])
#           ]
#
# ACTUAL ARCHITECTURE (Pattern B - used by all 10 jobs):
#   class HelloWorldJob:
#       stages: List[Dict[str, Any]] = [  # ← Plain dicts!
#           {
#               "number": 1,
#               "name": "greeting",
#               "task_type": "hello_world_greeting",
#               "parallelism": "dynamic"
#           }
#       ]
#
# WHY PLAIN DICTS:
# 1. Simpler for job authors (no Pydantic imports in job files)
# 2. Jobs focus on declarative blueprints (WHAT to do)
# 3. CoreMachine handles orchestration (HOW to do it)
# 4. Pydantic used at CoreMachine boundaries (TaskDefinition, TaskResult)
# 5. All 10 production jobs work perfectly with plain dicts
#
# PYDANTIC IS STILL USED FOR TYPE SAFETY:
# - Jobs output plain dicts → CoreMachine converts to Pydantic
# - TaskDefinition (Pydantic) - task specifications
# - TaskResult (Pydantic) - handler results
# - JobRecord/TaskRecord (Pydantic) - database models
# - SQL ↔ Python ↔ Service Bus all use Pydantic for type safety
#
# FUTURE ENHANCEMENT (OPTIONAL):
# Could add runtime validation in CoreMachine.__init__():
#   from core.models.stage import Stage
#
#   for job_type, job_class in all_jobs.items():
#       for stage_dict in job_class.stages:
#           Stage(**stage_dict)  # Validates structure, fails fast on startup
#
# This would give Pydantic validation without requiring jobs to import Stage.
# Jobs stay simple (plain dicts), CoreMachine ensures type safety.
#
# Author: Robert and Geospatial Claude Legion
# Date: 30 SEP 2025 (created), 15 OCT 2025 (documented as unused by jobs)
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
