# ============================================================================
# CLAUDE CONTEXT - WORKFLOW ABC
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component of new architecture
# PURPOSE: Abstract base class for workflow/job declarations
# EXPORTS: Workflow - ABC for declarative job definitions
# INTERFACES: Defines contract that all workflows must implement
# PYDANTIC_MODELS: Uses Stage from core.models
# DEPENDENCIES: abc, typing, core.models
# SOURCE: Framework pattern from epoch4_framework.md
# SCOPE: All job declarations inherit from this
# VALIDATION: Pydantic validation in define_stages()
# PATTERNS: Abstract Base Class, Template Method
# ENTRY_POINTS: Subclass Workflow to create new job types
# INDEX: Workflow:30, define_stages:50, validate_parameters:70
# ============================================================================

"""
Workflow ABC - Declarative Job Definition Contract

This defines the contract that all job/workflow declarations must implement.
Jobs declare WHAT they do (stages, parameters), not HOW orchestration works.

Example:
    class HelloWorldWorkflow(Workflow):
        def define_stages(self) -> list[Stage]:
            return [Stage(stage_num=1, ...), ...]

        def validate_parameters(self, params: dict) -> dict:
            # Optional: custom validation
            return params

Author: Robert and Geospatial Claude Legion
Date: 30 SEP 2025
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from core.models import Stage


class Workflow(ABC):
    """
    Abstract base class for workflow/job declarations.

    Workflows are declarative - they define WHAT stages exist and WHAT
    parameters are needed, but not HOW the orchestration works (that's
    handled by core/machine.py CoreMachine).

    Subclasses must implement:
        - define_stages(): Return list of Stage definitions

    Subclasses may optionally override:
        - validate_parameters(): Custom parameter validation
        - get_batch_threshold(): Custom batching threshold (default: 50)
    """

    @abstractmethod
    def define_stages(self) -> List[Stage]:
        """
        Define the stages for this workflow.

        Returns:
            List of Stage objects defining the workflow sequence

        Example:
            return [
                Stage(
                    stage_num=1,
                    stage_name="validate",
                    task_types=["validate_input"],
                    parallel=False
                ),
                Stage(
                    stage_num=2,
                    stage_name="process",
                    task_types=["process_data"],
                    parallel=True
                )
            ]
        """
        pass

    def validate_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize job parameters.

        Override this to add custom parameter validation beyond Pydantic.

        Args:
            params: Raw parameters from job submission

        Returns:
            Validated and normalized parameters

        Raises:
            ValueError: If parameters are invalid
        """
        # Default: return params as-is
        # Subclasses can override for custom validation
        return params

    def get_batch_threshold(self) -> int:
        """
        Get the task count threshold for batch processing.

        If a stage creates >= this many tasks, use Service Bus batching.
        If < this many tasks, use Queue Storage individual messages.

        Returns:
            Task count threshold (default: 50)
        """
        return 50

    def get_job_type(self) -> str:
        """
        Get the job type identifier for this workflow.

        By default, uses the class name converted to snake_case.
        Override this to provide a custom job_type string.

        Returns:
            Job type identifier (e.g., "hello_world", "raster_ingest")
        """
        # Convert class name from PascalCase to snake_case
        # HelloWorldWorkflow → hello_world_workflow → hello_world
        name = self.__class__.__name__
        # Remove "Workflow" suffix if present
        if name.endswith('Workflow'):
            name = name[:-8]  # Remove "Workflow"

        # Convert PascalCase to snake_case
        import re
        name = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        return name
