# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# CATEGORY: STATE MANAGEMENT & ORCHESTRATION
# PURPOSE: Core architectural component for job/task lifecycle management
# EPOCH: Shared by all epochs (may evolve with architecture changes)# PURPOSE: Minimal abstract base controller with only inherited methods for clean architecture
# EXPORTS: CoreController - lean base class for composition-based controllers
# INTERFACES: ABC (Abstract Base Class) - defines minimal controller contract
# PYDANTIC_MODELS: JobExecutionContext, StageResultContract, TaskDefinition, TaskResult
# DEPENDENCIES: abc, hashlib, json, logging, typing, pydantic
# SOURCE: Extracted from BaseController to enable parallel implementation
# SCOPE: Core controller abstractions without queue-specific logic
# VALIDATION: Pydantic contracts with @enforce_contract decorator
# PATTERNS: Abstract Base Class, Template Method, Composition over Inheritance
# ENTRY_POINTS: Inherited by ServiceBusController and future clean controllers
# INDEX: CoreController:50, Abstract Methods:100, ID Generation:250, Validation:350
# ============================================================================

"""
Core Controller - Minimal Abstract Base

This is the clean abstraction extracted from BaseController, containing only
the methods that should be inherited. This enables parallel implementation
of Service Bus controllers without the Queue Storage baggage.

Architecture:
- 5 abstract methods (core contract)
- 2 ID generation methods (use controller's job_type)
- 2 validation methods (controller-specific)
- Total: approximately 400 lines vs BaseController's 2,290 lines

Usage:
    from controller_core import CoreController
    from state_manager import StateManager

    class ServiceBusController(CoreController):
        def __init__(self):
            super().__init__()
            self.state_manager = StateManager()  # Composition
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import List, Dict, Any, Optional

# Logging
from util_logger import LoggerFactory, ComponentType

# Pydantic models for contracts - using new core.models structure
from core.models import (
    JobExecutionContext,
    StageExecutionContext,
    TaskDefinition,
    TaskResult,
    StageResultContract
)
from core.schema import WorkflowDefinition, get_workflow_definition
from utils.contract_validator import enforce_contract


class CoreController(ABC):
    """
    Minimal abstract base controller with only inherited methods.

    This is the clean abstraction for all controllers, containing:
    - Abstract methods that define the controller contract
    - ID generation that uses controller's job_type
    - Validation methods for parameters

    Everything else (state management, queue processing, workflow management)
    should be handled through composition, not inheritance.

    Key Design Principles:
    - Composition over inheritance
    - Single responsibility per component
    - Explicit contracts with Pydantic models
    - No queue-specific logic
    """

    def __init__(self):
        """
        Initialize core controller with minimal setup.

        Sets up:
        - Logging
        - Job type (set by concrete controller)
        - Workflow definition loading
        """
        # Create logger for this controller
        self.logger = LoggerFactory.create_logger(
            ComponentType.CONTROLLER,
            self.__class__.__name__
        )

        # Job type set by concrete implementation
        self._job_type = None

        # Workflow definition loaded on demand
        self._workflow_definition = None

        self.logger.info(f"Initialized {self.__class__.__name__}")

    # ========================================================================
    # ABSTRACT METHODS - Core Controller Contract
    # ========================================================================

    @abstractmethod
    def get_job_type(self) -> str:
        """
        Return the job type identifier for this controller.

        This identifies what type of job this controller handles
        (e.g., "hello_world", "process_raster", "stage_vector").

        Returns:
            Job type string identifier
        """
        pass

    @abstractmethod
    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize job parameters.

        Each controller defines its own parameter validation logic.
        This is called before job creation to ensure parameters are valid.

        Args:
            parameters: Raw job parameters from user

        Returns:
            Validated and normalized parameters

        Raises:
            ValueError: If parameters are invalid
        """
        pass

    @abstractmethod
    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[List[Dict[str, Any]]] = None
    ) -> List[TaskDefinition]:
        """
        Create task definitions for a specific stage.

        This is the core business logic where controllers define
        what tasks need to be executed for each stage.

        Args:
            stage_number: Current stage number (1-based)
            job_id: Parent job ID
            job_parameters: Validated job parameters
            previous_stage_results: Results from previous stage (if any)

        Returns:
            List of TaskDefinition objects to be queued
        """
        pass

    @abstractmethod
    def should_advance_stage(
        self,
        job_id: str,
        current_stage: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Determine if job should advance to the next stage.

        Controllers can implement custom logic to decide whether
        to proceed to the next stage or complete the job.

        Args:
            job_id: Job identifier
            current_stage: Current stage number
            stage_results: Aggregated results from current stage

        Returns:
            True to advance to next stage, False to complete job
        """
        pass

    @abstractmethod
    def aggregate_job_results(
        self,
        context: JobExecutionContext
    ) -> Dict[str, Any]:
        """
        Aggregate all stage results into final job result.

        Called when job completes to produce the final output.

        Args:
            context: Job execution context with all stage results

        Returns:
            Final aggregated job results
        """
        pass

    # ========================================================================
    # ID GENERATION - Uses controller's job_type (inherited)
    # ========================================================================

    def generate_job_id(self, parameters: Dict[str, Any]) -> str:
        """
        Generate deterministic job ID using SHA256.

        Creates idempotent job IDs - same parameters always generate
        the same ID, providing natural deduplication.

        Args:
            parameters: Job parameters that uniquely identify the work

        Returns:
            64-character SHA256 hash as job ID
        """
        # Get job type from controller
        job_type = self.get_job_type()

        # Create canonical representation
        canonical_params = {
            "job_type": job_type,
            "parameters": parameters
        }

        # Sort for deterministic JSON
        canonical_json = json.dumps(canonical_params, sort_keys=True, default=str)

        # Generate SHA256 hash
        job_id = hashlib.sha256(canonical_json.encode()).hexdigest()

        self.logger.debug(f"Generated job_id {job_id[:12]}... for job_type {job_type}")
        return job_id

    def generate_task_id(self, job_id: str, stage: int, semantic_index: str) -> str:
        """
        Generate semantic task ID for cross-stage lineage tracking.

        Format: {job_id[:8]}-s{stage}-{semantic_index}

        This enables tasks in later stages to reference outputs
        from earlier stages by reconstructing the task ID.

        Args:
            job_id: Parent job ID (64-char SHA256)
            stage: Stage number (1-based)
            semantic_index: Semantic identifier (e.g., "tile-x5-y10")

        Returns:
            Deterministic task ID enabling cross-stage lineage

        Examples:
            >>> generate_task_id("a1b2c3d4...", 1, "greet-0")
            'a1b2c3d4-s1-greet-0'

            >>> generate_task_id("a1b2c3d4...", 2, "tile-x5-y10")
            'a1b2c3d4-s2-tile-x5-y10'
        """
        # Sanitize semantic_index to ensure URL-safe characters
        safe_semantic_index = re.sub(r'[^a-zA-Z0-9\-]', '-', semantic_index)

        # Use first 8 chars of job ID for readability
        readable_id = f"{job_id[:8]}-s{stage}-{safe_semantic_index}"

        # Ensure it fits in database field (100 chars max)
        if len(readable_id) <= 100:
            return readable_id

        # Fallback for very long semantic indices
        content = f"{job_id}-{stage}-{safe_semantic_index}"
        hash_id = hashlib.sha256(content.encode()).hexdigest()
        return f"{hash_id[:8]}-s{stage}-{hash_id[8:16]}"

    # ========================================================================
    # VALIDATION - Controller-specific (inherited)
    # ========================================================================

    def validate_stage_parameters(
        self,
        stage_number: int,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate parameters for a specific stage.

        Default implementation just returns parameters unchanged.
        Controllers can override for stage-specific validation.

        Args:
            stage_number: Stage to validate for
            parameters: Stage parameters

        Returns:
            Validated parameters
        """
        # Default: no stage-specific validation
        return parameters

    # ========================================================================
    # DEFAULT IMPLEMENTATIONS - Can be overridden
    # ========================================================================

    @enforce_contract(
        params={
            'job_id': str,
            'stage_number': int,
            'task_results': list
        },
        returns=Dict[str, Any]
    )
    def aggregate_stage_results(
        self,
        job_id: str,
        stage_number: int,
        task_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Default implementation for aggregating stage results.

        Uses StageResultContract to ensure consistent structure.
        Controllers can override for custom aggregation logic.

        Args:
            job_id: Job identifier
            stage_number: Stage number
            task_results: List of task results to aggregate

        Returns:
            Aggregated results following StageResultContract

        Raises:
            TypeError: If task_results contain non-TaskResult objects
        """
        # Import custom exception
        from exceptions import ContractViolationError

        # CONTRACT ENFORCEMENT - All task results must be TaskResult objects
        validated_results = []

        for idx, task_data in enumerate(task_results):
            if not isinstance(task_data, TaskResult):
                # This is a contract violation - task processors must return TaskResult
                task_info = "unknown"
                if isinstance(task_data, dict):
                    task_info = task_data.get('task_id', f'index_{idx}')

                raise ContractViolationError(
                    f"Contract violation in {self.__class__.__name__}.aggregate_stage_results: "
                    f"Task processor returned {type(task_data).__name__} instead of TaskResult. "
                    f"Task: {task_info}, Stage: {stage_number}. "
                    f"All task processors MUST return TaskResult objects."
                )
            validated_results.append(task_data)

        # Use StageResultContract for consistent structure
        stage_result = StageResultContract.from_task_results(
            stage_number=stage_number,
            task_results=validated_results,
            metadata={"job_id": job_id}
        )

        # Return as JSON-serializable dict
        return stage_result.model_dump(mode='json')

    # ========================================================================
    # PROPERTIES - Lazy loading
    # ========================================================================

    @property
    def job_type(self) -> str:
        """Get job type (cached)."""
        if self._job_type is None:
            self._job_type = self.get_job_type()
        return self._job_type

    @property
    def workflow_definition(self) -> WorkflowDefinition:
        """Get workflow definition (lazy loaded)."""
        if self._workflow_definition is None:
            self._workflow_definition = get_workflow_definition(self.job_type)
        return self._workflow_definition

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(job_type={self.job_type})"