# ============================================================================
# CLAUDE CONTEXT - CONTROLLER
# ============================================================================
# PURPOSE: Abstract base controller implementing Job→Stage→Task orchestration pattern for complex workflows
# EXPORTS: BaseController (abstract base class for all workflow controllers)
# INTERFACES: ABC (Abstract Base Class) - defines controller contract for job orchestration
# PYDANTIC_MODELS: JobRecord, TaskRecord, JobExecutionContext, StageExecutionContext, TaskDefinition, TaskResult
# DEPENDENCIES: abc, hashlib, json, azure.storage.queue, azure.identity, repository_factory, task_factory
# SOURCE: Workflow definitions from schema_workflow, job parameters from HTTP requests via Azure Queues
# SCOPE: Job orchestration across all workflow types - defines stage sequences and task coordination
# VALIDATION: Pydantic contracts enforced - NO defensive programming, fail fast on contract violations
# PATTERNS: Template Method (abstract methods), Factory (task creation), Singleton (registries)
# ENTRY_POINTS: process_job_queue_message(), process_task_queue_message(), concrete controllers inherit
# INDEX: BaseController:100, Abstract Methods:134, Job Lifecycle:286, Queue Processing:1270, Stage Management:678
# ============================================================================

"""
Abstract Base Controller - Job→Stage→Task Architecture

Abstract base class implementing the sophisticated Job→Stage→Task orchestration pattern
for complex geospatial workflows. Controllers define job types, coordinate sequential stages,
and manage parallel task execution with distributed completion detection.

Architecture Pattern:
    JOB (Controller Layer - Orchestration)
     ├── STAGE 1 (Sequential coordination)
     │   ├── Task A (Service + Repository Layer - Parallel)
     │   ├── Task B (Service + Repository Layer - Parallel) 
     │   └── Task C (Service + Repository Layer - Parallel)
     │                     ↓ Last task completes stage
     ├── STAGE 2 (Sequential coordination)
     │   ├── Task D (Service + Repository Layer - Parallel)
     │   └── Task E (Service + Repository Layer - Parallel)
     │                     ↓ Last task completes stage
     └── COMPLETION (job_type specific aggregation)

Key Features:
- Pydantic workflow definitions with stage sequences
- Sequential stages with parallel task execution within stages
- Idempotent job processing with SHA256-based deduplication
- "Last task turns out the lights" atomic completion detection
- Strong typing discipline with explicit error handling
- Centralized workflow validation and parameter schemas

Controller Responsibilities:
- Define job_type and workflow stages (orchestration only)
- Create and coordinate sequential stage transitions
- Fan-out parallel tasks within each stage
- Aggregate final job results from all task outputs
- Handle job completion and result formatting

Integration Points:
- Used by HTTP triggers for job submission
- Creates JobRecord and TaskDefinition objects
- Interfaces with RepositoryFactory for data persistence
- Routes to Service layer for business logic execution
- Integrates with queue system for asynchronous processing

Usage Example:
    class MyController(BaseController):
        def get_job_type(self) -> str:
            return "my_operation"
            
        def process_job_stage(self, job_record, stage, parameters, stage_results):
            # Stage coordination logic here
            pass

Author: Azure Geospatial ETL Team
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
import json
import re
import traceback
from typing import List, Dict, Any, Optional

# Local application imports
from config import get_config
from repositories import RepositoryFactory
from repositories import StageCompletionRepository
from task_factory import TaskHandlerFactory
from util_logger import LoggerFactory
from util_logger import ComponentType, LogLevel, LogContext
from schema_base import (
    JobStatus, TaskStatus, JobRecord,
    JobExecutionContext, StageExecutionContext,
    TaskDefinition, TaskResult, TaskRecord,
    StageResultContract  # Added for stage result validation
)
from schema_orchestration import (
    OrchestrationInstruction,
    OrchestrationAction,
    FileOrchestrationItem
)
from schema_queue import JobQueueMessage, TaskQueueMessage
from schema_workflow import WorkflowDefinition, get_workflow_definition
from utils import enforce_contract  # Added for queue boundary contracts


class BaseController(ABC):
    """
    Abstract base controller for all job types in the Job→Stage→Task architecture.

    CONTROLLER LAYER RESPONSIBILITY (Orchestration Only):
    - Defines job_type and sequential stages
    - Orchestrates stage transitions with "last task turns out lights" pattern
    - Aggregates final job results from all task outputs
    - Does NOT contain business logic (that lives in Service/Repository layers)

    CONTRACT ENFORCEMENT (Updated 20 SEP 2025):
    - NO defensive programming - fail fast on contract violations
    - Pydantic models required at all boundaries (no dict fallbacks)
    - Factory methods mandatory for object creation
    - Single repository creation pattern enforced

    Implements the Job → Stage → Task pattern:
    - Job: One or more stages executing sequentially
    - Stage: Creates parallel tasks, advances when all complete
    - Task: Atomic work units with business logic in Service layer
    """

    def __init__(self):
        """Initialize controller with workflow definition and logging.

        Enforces that all controllers MUST have workflow definitions.
        No fallback behavior - fails if workflow not found.
        """
        # Get job type from concrete controller implementation
        self.job_type = self.get_job_type()

        # Load workflow definition - REQUIRED, no fallbacks
        try:
            self.workflow_definition = get_workflow_definition(self.job_type)
        except ValueError as e:
            # CONTRACT: All controllers must have workflow definitions
            raise ValueError(f"No workflow definition found for job_type '{self.job_type}'. "
                           f"All controllers must have workflow definitions defined in schema_workflow.py. "
                           f"Error: {e}")

        # Initialize logging for this controller
        self.logger = LoggerFactory.create_logger(ComponentType.CONTROLLER, self.__class__.__name__)
        self.logger.info(f"Loaded workflow definition for {self.job_type} with {len(self.workflow_definition.stages)} stages")

    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by concrete controllers
    # ========================================================================
    
    @abstractmethod
    def get_job_type(self) -> str:
        """
        Return the unique job type identifier for this controller.

        This identifies the controller and determines routing.
        Must be unique across all controllers in the system.

        Example:
            return "process_raster"  # Unique identifier for raster processing
        """
        pass


    @abstractmethod
    def create_stage_tasks(
        self,
        stage_number: int,
        job_id: str,
        job_parameters: Dict[str, Any],
        previous_stage_results: Optional[Dict[str, Any]] = None
    ) -> List[TaskDefinition]:
        """
        Create tasks for a specific stage - THE CORE ORCHESTRATION METHOD.

        This method defines what parallel tasks should be created for each stage.
        Tasks contain the business logic (Service + Repository layers).

        CRITICAL: Each TaskDefinition MUST include 'task_index' in parameters.
        The task_index provides semantic meaning for cross-stage data flow.

        Args:
            stage_number: The stage to create tasks for (1-based)
            job_id: The parent job ID (SHA256 hash)
            job_parameters: Original job parameters from HTTP request
            previous_stage_results: Aggregated results from previous stage (None for stage 1)

        Returns:
            List of TaskDefinition objects for parallel execution.
            Empty list means no tasks for this stage (stage completes immediately).
        """
        pass

    @abstractmethod
    def aggregate_job_results(self, context: JobExecutionContext) -> Dict[str, Any]:
        """
        Aggregate results from all stages into final job result.

        This is the job_type specific completion method that creates
        the final result after all stages are complete.

        Called automatically when the final stage completes via
        the "last task turns out the lights" pattern.

        Args:
            context: Job execution context with results from ALL stages.
                    Access via context.stage_results[stage_num]

        Returns:
            Final aggregated job result dictionary to store in JobRecord.result_data
        """
        pass

    # ========================================================================
    # COMPLETION METHODS - Can be overridden for job-specific logic
    # ========================================================================

    @enforce_contract(
        params={
            'stage_number': int,
            'task_results': list
        },
        returns=dict
    )
    def aggregate_stage_results(
        self,
        stage_number: int,
        task_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Aggregate results from all tasks in a stage using StageResultContract.

        Called automatically when all tasks in a stage complete ("last task" pattern).
        The aggregated results are stored in JobRecord.stage_results[str(stage_number)]
        and passed to next stage via previous_stage_results parameter.

        This default implementation uses StageResultContract to ensure consistent
        structure. Controllers can override to add job-specific aggregation logic
        while still using the contract as a foundation.

        CONTRACT:
        - Results are stored with STRING keys in stage_results dict
        - Structure follows StageResultContract specification

        Args:
            stage_number: The stage that completed (1-based)
            task_results: Results from all tasks in the stage

        Returns:
            Aggregated results dictionary following StageResultContract structure.
            This becomes previous_stage_results for next stage.
        """
        from schema_base import StageResultContract, TaskResult

        # Convert task_results dicts to TaskResult objects if needed
        # This handles the case where task results come as dicts from database
        task_result_objects = []
        for task_data in task_results:
            if isinstance(task_data, TaskResult):
                task_result_objects.append(task_data)
            elif isinstance(task_data, dict):
                # Try to convert dict to TaskResult
                try:
                    # Create a minimal TaskResult from dict data
                    task_result = TaskResult(
                        task_id=task_data.get('task_id', 'unknown'),
                        status=task_data.get('status', TaskStatus.FAILED.value),
                        message=task_data.get('message', ''),
                        data=task_data.get('data', task_data)
                    )
                    task_result_objects.append(task_result)
                except Exception as e:
                    self.logger.warning(f"Could not convert task result to TaskResult: {e}")
                    # Create a failed TaskResult as fallback
                    task_result = TaskResult(
                        task_id=task_data.get('task_id', 'unknown'),
                        status=TaskStatus.FAILED.value,
                        message=f"Conversion error: {str(e)}",
                        data=task_data
                    )
                    task_result_objects.append(task_result)

        # === CREATING STAGE RESULTS FOR STORAGE ===
        #
        # NOTE ON STAGE NUMBERS:
        # - stage_number is an INTEGER here (e.g., 1, 2, 3)
        # - StageResultContract stores it as an integer internally
        # - BUT when this gets stored in stage_results dict, it will use STRING key
        #
        # STORAGE PATTERN:
        # - We return: {"stage_number": 2, "task_results": [...], ...}
        # - Controller stores as: stage_results["2"] = {...}
        #                        ^^^^ string key   ^^^^ our returned dict
        #
        # Use StageResultContract factory method to create properly structured result
        stage_result = StageResultContract.from_task_results(
            stage_number=stage_number,  # INTEGER passed in
            task_results=task_result_objects
        )

        # Convert to dict for storage (excludes stage_key since that becomes the dict key)
        return stage_result.to_dict_for_storage()
    
    @enforce_contract(
        params={
            'stage_number': int,
            'stage_results': dict
        },
        returns=bool
    )
    def should_advance_stage(
        self,
        stage_number: int,
        stage_results: Dict[str, Any]
    ) -> bool:
        """
        Determine if job should advance to next stage.

        Default implementation: advance if at least one task succeeded.
        Controllers can override for stricter requirements (e.g., all tasks must succeed).

        Called by stage completion handler after aggregating stage results.

        Args:
            stage_number: Current stage number (1-based)
            stage_results: Aggregated results from current stage

        Returns:
            True if should advance to next stage, False if job should fail
        """
        # Check if stage completely failed - no tasks succeeded
        if stage_results.get('status') == TaskStatus.FAILED.value:
            return False

        # Ensure at least one task succeeded
        if stage_results.get('successful_tasks', 0) == 0:
            return False

        # Check if we're at the final stage (no more stages to advance to)
        if self.is_final_stage(stage_number):
            return False  # This is the final stage

        # Default policy: advance if any tasks succeeded
        # Controllers can override for stricter requirements
        return True

    # ========================================================================
    # CONCRETE METHODS - Provided by base class for all controllers
    # ========================================================================

    def generate_job_id(self, parameters: Dict[str, Any]) -> str:
        """
        Generate idempotent job ID from parameters hash.

        CRITICAL: Same parameters always generate same job ID.
        This provides natural deduplication - duplicate job submissions
        return the existing job rather than creating a new one.

        Args:
            parameters: Job parameters that uniquely identify the work

        Returns:
            64-character SHA256 hash as job ID
        """
        # Sort parameters for deterministic JSON representation
        sorted_params = json.dumps(parameters, sort_keys=True, default=str)

        # Combine job type and parameters for unique hash
        hash_input = f"{self.job_type}:{sorted_params}"

        # Generate SHA256 hash as job ID (64 chars)
        job_id = hashlib.sha256(hash_input.encode()).hexdigest()

        self.logger.debug(f"Generated job_id {job_id[:12]}... for job_type {self.job_type}")
        return job_id

    def generate_task_id(self, job_id: str, stage: int, semantic_index: str) -> str:
        """
        Generate semantic task ID for cross-stage lineage tracking.
        
        This is a STAGE-LEVEL operation that belongs in the Controller layer
        because Controllers orchestrate stages and understand semantic meaning
        of task indices for cross-stage data flow.
        
        Format: {job_id[:8]}-s{stage}-{semantic_index} (URL-safe characters only)
        
        Examples:
            job_id="a1b2c3d4...", stage=1, semantic_index="greet-0" 
            → "a1b2c3d4-s1-greet-0"
            
            job_id="a1b2c3d4...", stage=2, semantic_index="tile-x5-y10"
            → "a1b2c3d4-s2-tile-x5-y10"
        
        Cross-Stage Lineage:
            Tasks in stage N can automatically reference stage N-1 data by
            constructing the expected predecessor task ID using the same
            semantic_index but previous stage number.
        
        Args:
            job_id: Parent job ID (64-char SHA256 hash)
            stage: Stage number (1-based)
            semantic_index: Semantic task identifier (URL-safe: hyphens, alphanumeric only)
            
        Returns:
            Deterministic task ID enabling cross-stage lineage tracking
        """
        # Sanitize semantic_index to ensure URL-safe characters only
        # Replace underscores and other problematic chars with hyphens
        safe_semantic_index = re.sub(r'[^a-zA-Z0-9\-]', '-', semantic_index)
        
        # Use first 8 chars of job ID for readability while maintaining uniqueness
        readable_id = f"{job_id[:8]}-s{stage}-{safe_semantic_index}"
        
        # Ensure it fits in database field (100 chars max)
        if len(readable_id) <= 100:
            return readable_id
        
        # Fallback for very long semantic indices (shouldn't happen in practice)
        content = f"{job_id}-{stage}-{safe_semantic_index}"
        hash_id = hashlib.sha256(content.encode()).hexdigest()
        return f"{hash_id[:8]}-s{stage}-{hash_id[8:16]}"

    def validate_job_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize job parameters using workflow definition.

        CONTRACT: All controllers MUST have workflow definitions.
        Validation is mandatory - no fallbacks or defaults.

        Args:
            parameters: Raw job parameters from HTTP request

        Returns:
            Validated and normalized parameters

        Raises:
            ValueError: If parameters fail validation
        """
        # CONTRACT: Parameters must be a dictionary
        if not isinstance(parameters, dict):
            raise ValueError("Job parameters must be a dictionary")

        # Ensure job_type matches this controller if specified
        if parameters.get('job_type') and parameters['job_type'] != self.job_type:
            raise ValueError(f"Job type mismatch: expected {self.job_type}, got {parameters.get('job_type')}")

        # Create copy to avoid mutating original
        parameters = parameters.copy()

        # Delegate to workflow definition for validation - NO FALLBACKS
        try:
            validated_params = self.workflow_definition.validate_job_parameters(parameters)
            self.logger.debug(f"Workflow validation successful for job_type {self.job_type}")
            return validated_params
        except Exception as e:
            self.logger.error(f"Workflow parameter validation failed: {e}")
            raise ValueError(f"Parameter validation failed: {e}")
    
    def validate_stage_parameters(self, stage_number: int, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate parameters for a specific stage using workflow definition
        
        Returns validated parameters with defaults applied
        """
        try:
            validated_params = self.workflow_definition.validate_stage_parameters(stage_number, parameters)
            self.logger.debug(f"Stage {stage_number} parameters validated successfully")
            return validated_params
        except Exception as e:
            self.logger.error(f"Stage {stage_number} parameter validation failed: {e}")
            raise ValueError(f"Stage {stage_number} parameter validation failed: {e}")
    
    def get_workflow_stage_definition(self, stage_number: int):
        """Get workflow stage definition for a stage number"""
        return self.workflow_definition.get_stage_by_number(stage_number)
    
    def get_next_stage_number(self, current_stage: int) -> Optional[int]:
        """Get the next stage number in the workflow sequence"""
        next_stage = self.workflow_definition.get_next_stage(current_stage)
        return next_stage.stage_number if next_stage else None
    
    def is_final_stage(self, stage_number: int) -> bool:
        """Check if a stage is the final stage in the workflow"""
        stage_def = self.workflow_definition.get_stage_by_number(stage_number)
        return stage_def.is_final_stage if stage_def else False

    # ============================================================================
    # DYNAMIC ORCHESTRATION SUPPORT
    # ============================================================================

    def supports_dynamic_orchestration(self) -> bool:
        """
        Override in child controllers to enable dynamic orchestration.

        When True, Stage 1 is expected to return an OrchestrationInstruction
        that determines how Stage 2 tasks are created.

        Returns:
            bool: False by default, override to return True for dynamic controllers
        """
        return False

    def parse_orchestration_instruction(self, stage_results: Dict[str, Any]) -> Optional['OrchestrationInstruction']:
        """
        Parse orchestration instruction from Stage 1 results.

        Args:
            stage_results: Results from Stage 1 aggregate_stage_results

        Returns:
            OrchestrationInstruction if found and valid, None otherwise
        """
        self.logger.debug(f"🔍 Parsing orchestration instruction from stage results")

        if not self.supports_dynamic_orchestration():
            self.logger.debug("❌ Controller does not support dynamic orchestration")
            return None

        self.logger.debug("✅ Controller supports dynamic orchestration")

        # Check for orchestration data in metadata field (StageResultContract compliance)
        # Stage results now follow StageResultContract with custom data in 'metadata' field
        metadata = stage_results.get('metadata', {})
        orchestration_data = metadata.get('orchestration') or stage_results.get('orchestration')

        if not orchestration_data:
            self.logger.warning("⚠️ Dynamic orchestration enabled but no 'orchestration' key in Stage 1 metadata or top-level results")
            self.logger.debug(f"Stage result keys: {list(stage_results.keys())}")
            if metadata:
                self.logger.debug(f"Metadata keys: {list(metadata.keys())}")
            return None

        self.logger.debug(f"📦 Found orchestration data of type: {type(orchestration_data)}")

        try:
            # Import here to avoid circular dependency
            from schema_orchestration import OrchestrationInstruction, FileOrchestrationItem

            # Handle both dict and OrchestrationInstruction objects
            if isinstance(orchestration_data, dict):
                self.logger.debug(f"📋 Orchestration data is dict with keys: {list(orchestration_data.keys())}")

                # Convert items to FileOrchestrationItem objects if they're dicts
                if 'items' in orchestration_data:
                    items = orchestration_data['items']
                    converted_items = []
                    for item in items:
                        if isinstance(item, dict):
                            # Log what fields we have
                            self.logger.debug(f"Item fields: {list(item.keys())}")
                            # Try to create FileOrchestrationItem from dict
                            # Check if it has required fields for FileOrchestrationItem
                            if 'container' in item and 'path' in item:
                                self.logger.debug(f"Converting dict to FileOrchestrationItem: {item.get('item_id', 'no_id')}")
                                converted_items.append(FileOrchestrationItem(**item))
                            elif 'container' in item and 'name' in item:
                                # Handle case where 'name' is present instead of 'path'
                                self.logger.debug(f"Found 'name' field, converting to 'path': {item.get('item_id', 'no_id')}")
                                item['path'] = item.pop('name')  # Rename 'name' to 'path'
                                converted_items.append(FileOrchestrationItem(**item))
                            else:
                                # Fall back to generic OrchestrationItem
                                self.logger.warning(f"Item missing required fields, using generic: {item.get('item_id', 'no_id')}")
                                self.logger.warning(f"Item fields: {list(item.keys())}")
                                converted_items.append(item)
                        else:
                            # Already an object, keep as-is
                            converted_items.append(item)
                    orchestration_data['items'] = converted_items

                instruction = OrchestrationInstruction(**orchestration_data)
                self.logger.info(f"✅ Created OrchestrationInstruction with action={instruction.action}, items={len(instruction.items)}")
                return instruction
            elif hasattr(orchestration_data, 'action'):  # Duck typing for OrchestrationInstruction
                self.logger.debug("📦 Orchestration data is already an OrchestrationInstruction object")
                return orchestration_data
            else:
                self.logger.error(f"❌ Invalid orchestration data type: {type(orchestration_data)}")
                return None
        except Exception as e:
            self.logger.error(f"❌ Failed to parse orchestration instruction: {e}")
            self.logger.debug(f"Orchestration data that failed: {orchestration_data}")
            return None

    def create_tasks_from_orchestration(
        self,
        orchestration: 'OrchestrationInstruction',
        job_id: str,
        stage_number: int,
        job_parameters: Dict[str, Any]
    ) -> List['TaskDefinition']:
        """
        Create Stage 2 tasks based on orchestration instruction.

        This is a helper method for controllers using dynamic orchestration.
        Override this method to customize task creation from orchestration items.

        Args:
            orchestration: Parsed orchestration instruction from Stage 1
            job_id: Parent job ID
            stage_number: Current stage (usually 2)
            job_parameters: Original job parameters

        Returns:
            List of TaskDefinition objects
        """
        self.logger.debug(f"🏗️ Creating tasks from orchestration instruction for stage {stage_number}")

        # OrchestrationAction already imported at top

        if orchestration.action != OrchestrationAction.CREATE_TASKS:
            self.logger.info(f"⏭️ Orchestration action is {orchestration.action}, not creating tasks")
            return []

        self.logger.debug(f"✅ Orchestration action is CREATE_TASKS")

        if not orchestration.items:
            self.logger.warning("⚠️ No items in orchestration instruction")
            return []

        self.logger.debug(f"📊 Found {len(orchestration.items)} items to process")

        tasks = []
        for idx, item in enumerate(orchestration.items):
            # Generate unique task ID based on item
            task_id = self.generate_task_id(job_id, stage_number, f"item-{idx:04d}")
            self.logger.debug(f"🔑 Generated task_id: {task_id} for item {idx}")

            # Merge item metadata with stage 2 parameters
            task_params = {
                **job_parameters,  # Original job parameters
                **orchestration.stage_2_parameters,  # Stage 2 specific parameters
                'item_id': item.item_id,
                'item_type': item.item_type,
                'item_metadata': item.metadata,
                'task_index': f"item-{idx:04d}"
            }

            # Add item-specific fields if present
            if item.name:
                task_params['item_name'] = item.name
                self.logger.debug(f"  Added item_name: {item.name}")
            if item.size is not None:
                task_params['item_size'] = item.size
                self.logger.debug(f"  Added item_size: {item.size}")
            if item.location:
                task_params['item_location'] = item.location
                self.logger.debug(f"  Added item_location: {item.location}")

            task = TaskDefinition(
                task_id=task_id,
                job_type=self.get_job_type(),
                task_type=self.workflow_definition.get_stage_by_number(stage_number).task_type,
                stage_number=stage_number,
                job_id=job_id,
                parameters=task_params
            )
            tasks.append(task)

        self.logger.info(f"✅ Created {len(tasks)} tasks from orchestration instruction")
        return tasks

    def create_job_context(self, job_id: str, parameters: Dict[str, Any], 
                          current_stage: int = 1, stage_results: Dict[int, Dict[str, Any]] = None) -> JobExecutionContext:
        """Create job execution context for orchestration"""
        # Get total stages from workflow definition
        total_stages = len(self.workflow_definition.stages)
        
        return JobExecutionContext(
            job_id=job_id,
            job_type=self.job_type,
            current_stage=current_stage,
            total_stages=total_stages,
            parameters=parameters,
            stage_results=stage_results or {}
        )

    def create_stage_context(self, job_context: JobExecutionContext, stage_number: int) -> StageExecutionContext:
        """Create stage execution context from job context"""
        stage = self.workflow_definition.get_stage_by_number(stage_number)
        if not stage:
            raise ValueError(f"Stage {stage_number} not found in job_type {self.job_type}")
        
        # Get results from previous stage if available
        previous_stage_results = None
        if stage_number > 1:
            previous_stage_results = job_context.get_stage_result(stage_number - 1)
        
        return StageExecutionContext(
            job_id=job_context.job_id,
            stage_number=stage_number,
            stage_name=stage.stage_name,
            task_type=stage.task_type,
            job_parameters=job_context.parameters,
            previous_stage_results=previous_stage_results
        )

    def create_job_record(self, job_id: str, parameters: Dict[str, Any]) -> JobRecord:
        """Create and store the initial job record for database storage.

        Creates JobRecord in PostgreSQL with initial QUEUED status.
        This establishes the job in the system before any tasks are created.

        Args:
            job_id: The generated job ID (SHA256 hash)
            parameters: Validated job parameters

        Returns:
            JobRecord instance stored in database
        """
        self.logger.debug(f"🔧 Creating job record for job_id: {job_id[:16]}...")
        self.logger.debug(f"  Job type: {self.job_type}")
        self.logger.debug(f"  Total stages: {len(self.workflow_definition.stages)}")

        # Get repository instances via singleton factory
        self.logger.debug("🏭 Creating repository instances via RepositoryFactory...")
        repos = RepositoryFactory.create_repositories()
        self.logger.debug("✅ Repositories created successfully")

        # Extract specific repositories
        job_repo = repos['job_repo']
        # Note: task_repo and stage_completion_repo not used here but available

        # Create job record in PostgreSQL
        self.logger.debug("📝 Creating job record in database...")
        job_record = job_repo.create_job_from_params(
            job_type=self.job_type,
            parameters=parameters,
            total_stages=len(self.workflow_definition.stages)
        )

        self.logger.info(f"Job record created and stored: {job_id[:16]}...")
        return job_record

    def create_job_queue_message(self, job_id: str, parameters: Dict[str, Any], 
                               stage: int = 1, stage_results: Dict[int, Dict[str, Any]] = None) -> JobQueueMessage:
        """Create message for jobs queue"""
        return JobQueueMessage(
            job_id=job_id,
            job_type=self.job_type,
            stage=stage,
            parameters=parameters,
            stage_results=stage_results or {}
        )

    def queue_job(self, job_id: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Queue job for processing using Azure Storage Queue.

        Creates a JobQueueMessage and sends it to the geospatial-jobs queue
        for asynchronous processing. This initiates the job execution flow.

        Uses QueueRepository singleton for managed queue access.

        Args:
            job_id: The unique job identifier (SHA256 hash)
            parameters: Validated job parameters

        Returns:
            Dictionary with queue operation results including job_id and queue_name

        Raises:
            RuntimeError: If queue operations fail
        """
        
        config = get_config()
        
        # Create job queue message
        queue_message = self.create_job_queue_message(job_id, parameters)
        
        # Send to queue
        try:
            # Use QueueRepository singleton - credential reused across all invocations!
            self.logger.debug(f"📦 Getting QueueRepository singleton instance")
            try:
                queue_repo = RepositoryFactory.create_queue_repository()
                self.logger.debug(f"✅ QueueRepository obtained (singleton reused)")
            except Exception as repo_error:
                self.logger.error(f"❌ CRITICAL: Failed to get QueueRepository: {repo_error}")
                raise RuntimeError(f"CRITICAL CONFIGURATION ERROR - Queue repository initialization failed: {repo_error}")

            # Send message to queue using repository (handles encoding automatically)
            self.logger.debug(f"📤 Sending job message to queue: {config.job_processing_queue}")
            try:
                message_id = queue_repo.send_message(config.job_processing_queue, queue_message)
                self.logger.debug(f"✅ Message sent successfully. ID: {message_id}")
            except Exception as send_error:
                self.logger.error(f"❌ Failed to send message to queue: {send_error}")
                raise RuntimeError(f"Failed to queue job message: {send_error}")
            
            self.logger.info(f"Job {job_id[:16]}... queued successfully to {config.job_processing_queue}")
            
            return {
                "queued": True,
                "queue_name": config.job_processing_queue,
                "job_id": job_id,
                "stage": 1
            }
            
        except Exception as e:
            self.logger.error(f"Failed to queue job {job_id}: {e}")
            raise RuntimeError(f"Failed to queue job: {e}")

    # ========================================================================
    # TASK AND STAGE MANAGEMENT METHODS - Enhanced visibility and control
    # ========================================================================

    def list_stage_tasks(self, job_id: str, stage_number: int) -> List[Dict[str, Any]]:
        """
        List all tasks for a specific stage.
        
        Provides visibility into task progress within a stage.
        Useful for debugging, monitoring, and progress reporting.
        
        Args:
            job_id: The job identifier
            stage_number: The stage number to query
            
        Returns:
            List of task records for the specified stage
        """
        
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']
        tasks = task_repo.get_tasks_by_stage(job_id, stage_number)
        
        self.logger.debug(f"Found {len(tasks)} tasks in stage {stage_number} for job {job_id[:16]}...")
        return tasks

    def get_job_tasks(self, job_id: str) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get all tasks grouped by stage.
        
        Provides complete visibility into job task structure across all stages.
        Essential for job monitoring and progress tracking.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary mapping stage numbers to lists of task records
        """
        tasks_by_stage = {}
        
        for stage in self.workflow_definition.stages:
            stage_tasks = self.list_stage_tasks(job_id, stage.stage_number)
            tasks_by_stage[stage.stage_number] = stage_tasks
        
        total_tasks = sum(len(tasks) for tasks in tasks_by_stage.values())
        self.logger.debug(f"Retrieved {total_tasks} tasks across {len(tasks_by_stage)} stages for job {job_id[:16]}...")
        
        return tasks_by_stage

    def get_task_progress(self, job_id: str) -> Dict[str, Any]:
        """
        Get task completion progress by stage.
        
        Provides detailed progress metrics for monitoring and UI display.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary with progress statistics by stage and overall job
        """
        tasks_by_stage = self.get_job_tasks(job_id)
        
        progress = {
            'job_id': job_id,
            'job_type': self.job_type,
            'total_stages': len(self.workflow_definition.stages),
            'stages': {},
            'overall': {
                'total_tasks': 0,
                'completed_tasks': 0,
                'failed_tasks': 0,
                'processing_tasks': 0,
                'pending_tasks': 0
            }
        }
        
        for stage_num, tasks in tasks_by_stage.items():
            stage_progress = {
                'stage_number': stage_num,
                'stage_name': f"stage_{stage_num}",
                'total_tasks': len(tasks),
                'completed_tasks': 0,
                'failed_tasks': 0,
                'processing_tasks': 0,
                'pending_tasks': 0
            }
            
            # Count task statuses
            for task in tasks:
                task_status = task.get('status', TaskStatus.PENDING.value)
                if task_status == TaskStatus.COMPLETED.value:
                    stage_progress['completed_tasks'] += 1
                    progress['overall']['completed_tasks'] += 1
                elif task_status == TaskStatus.FAILED.value:
                    stage_progress['failed_tasks'] += 1
                    progress['overall']['failed_tasks'] += 1
                elif task_status == TaskStatus.PROCESSING.value:
                    stage_progress['processing_tasks'] += 1
                    progress['overall']['processing_tasks'] += 1
                else:
                    stage_progress['pending_tasks'] += 1
                    progress['overall']['pending_tasks'] += 1
                
                progress['overall']['total_tasks'] += 1
            
            # Calculate percentages
            if stage_progress['total_tasks'] > 0:
                stage_progress['completion_percentage'] = (
                    stage_progress['completed_tasks'] / stage_progress['total_tasks']
                ) * 100
                stage_progress['is_complete'] = stage_progress['completed_tasks'] == stage_progress['total_tasks']
            else:
                stage_progress['completion_percentage'] = 0.0
                stage_progress['is_complete'] = False
            
            progress['stages'][stage_num] = stage_progress
        
        # Calculate overall percentage
        if progress['overall']['total_tasks'] > 0:
            progress['overall']['completion_percentage'] = (
                progress['overall']['completed_tasks'] / progress['overall']['total_tasks']
            ) * 100
        else:
            progress['overall']['completion_percentage'] = 0.0
        
        return progress

    def list_job_stages(self) -> List[Dict[str, Any]]:
        """
        List all stages for this job type from workflow definition.
        
        Provides stage metadata for job planning and monitoring.
        
        Returns:
            List of stage definition dictionaries
        """
        stages = []
        for stage in self.workflow_definition.stages:
            stage_info = {
                'stage_number': stage.stage_number,
                'stage_name': stage.stage_name,
                'task_type': stage.task_type,
                'is_final_stage': stage.is_final_stage,
                'description': getattr(stage, 'description', f'Stage {stage.stage_number} - {stage.stage_name}')
            }
            stages.append(stage_info)
        
        return stages

    def get_stage_status(self, job_id: str) -> Dict[int, str]:
        """
        Get completion status of each stage.
        
        Args:
            job_id: The job identifier
            
        Returns:
            Dictionary mapping stage numbers to status strings
        """
        progress = self.get_task_progress(job_id)
        stage_status = {}
        
        for stage_num, stage_info in progress['stages'].items():
            if stage_info['is_complete']:
                if stage_info['failed_tasks'] > 0:
                    stage_status[stage_num] = 'completed_with_errors'
                else:
                    stage_status[stage_num] = 'completed'
            elif stage_info['processing_tasks'] > 0:
                stage_status[stage_num] = 'processing'
            elif stage_info['failed_tasks'] > 0 and stage_info['processing_tasks'] == 0:
                stage_status[stage_num] = 'failed'
            else:
                stage_status[stage_num] = 'pending'
        
        return stage_status

    def get_completed_stages(self, job_id: str) -> List[int]:
        """
        List completed stage numbers.
        
        Args:
            job_id: The job identifier
            
        Returns:
            List of stage numbers that have completed
        """
        stage_status = self.get_stage_status(job_id)
        completed = [
            stage_num for stage_num, status in stage_status.items() 
            if status in ['completed', 'completed_with_errors']
        ]
        
        self.logger.debug(f"Job {job_id[:16]}... has {len(completed)} completed stages: {completed}")
        return completed

    # ========================================================================
    # EXPLICIT JOB COMPLETION METHOD - Cleaner separation of concerns
    # ========================================================================

    def complete_job(self, job_id: str, all_task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Explicit job completion with full workflow context.
        
        This method provides a clear completion flow that:
        1. Creates complete job execution context from all task results
        2. Calls the abstract aggregate_job_results() for job-specific aggregation
        3. Updates job status to COMPLETED in database
        4. Returns the final aggregated result
        
        This is typically called by the "last task" completion detection.
        
        Args:
            job_id: The job identifier
            all_task_results: List of task results from all stages
            
        Returns:
            Final aggregated job result dictionary
        """
        self.logger.info(f"Starting explicit job completion for {job_id[:16]}... with {len(all_task_results)} task results")
        
        # Create job execution context from task results
        context = self._create_completion_context(job_id, all_task_results)
        self.logger.debug(f"Created completion context with {len(context.stage_results)} stage results")
        
        # Use the abstract method for job-specific aggregation
        self.logger.debug(f"Calling job-specific aggregate_job_results()")
        final_result = self.aggregate_job_results(context)
        self.logger.debug(f"Job aggregation complete: {list(final_result.keys()) if isinstance(final_result, dict) else 'non-dict result'}")
        
        # Store completion in database
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        
        self.logger.debug(f"Updating job status to COMPLETED in database")
        success = job_repo.complete_job(job_id, final_result)
        
        if success:
            self.logger.info(f"✅ Job {job_id[:16]}... completed successfully with {len(all_task_results)} tasks")
        else:
            self.logger.error(f"❌ Failed to update job completion status for {job_id[:16]}...")
            raise RuntimeError(f"Failed to complete job {job_id} in database")
        
        return final_result

    def _create_completion_context(self, job_id: str, all_task_results: List[Dict[str, Any]]) -> JobExecutionContext:
        """
        Create JobExecutionContext from task results for job completion.
        
        Args:
            job_id: The job identifier
            all_task_results: All task results from all stages
            
        Returns:
            JobExecutionContext with stage results populated
        """
        # Group task results by stage
        stage_results = {}
        
        for task_result in all_task_results:
            stage_num = task_result.get('stage_number', task_result.get('stage', 1))
            stage_key = str(stage_num)  # Always use string key for consistency

            if stage_key not in stage_results:
                stage_results[stage_key] = {
                    'stage_number': stage_num,
                    'stage_name': f"stage_{stage_num}",
                    'task_results': [],
                    'stage_status': 'completed',
                    'total_tasks': 0,
                    'successful_tasks': 0,
                    'failed_tasks': 0
                }
            
            stage_results[stage_key]['task_results'].append(task_result)
            stage_results[stage_key]['total_tasks'] += 1

            if task_result.get('status') == TaskStatus.COMPLETED.value:
                stage_results[stage_key]['successful_tasks'] += 1
            else:
                stage_results[stage_key]['failed_tasks'] += 1
        
        # Calculate success rates and stage status
        for stage_key, stage_data in stage_results.items():
            total = stage_data['total_tasks']
            successful = stage_data['successful_tasks']
            
            stage_data['success_rate'] = (successful / total * 100) if total > 0 else 0.0
            
            if stage_data['failed_tasks'] == 0:
                stage_data['stage_status'] = 'completed'
            elif stage_data['successful_tasks'] == 0:
                stage_data['stage_status'] = 'failed'
            else:
                stage_data['stage_status'] = 'completed_with_errors'
        
        # Get job parameters (would normally come from job record)
        # For now, create minimal context
        job_context = JobExecutionContext(
            job_id=job_id,
            job_type=self.job_type,
            current_stage=max(stage_results.keys()) if stage_results else 1,
            total_stages=len(self.workflow_definition.stages),
            parameters={'job_type': self.job_type},  # Minimal parameters
            stage_results=stage_results
        )
        
        return job_context

    def _validate_and_get_stage_results(
        self,
        job_record: JobRecord,
        stage_number: int
    ) -> Dict[str, Any]:
        """
        Safely retrieve and validate stage results with CONTRACT enforcement.

        This helper method ensures stage results exist and have the expected structure,
        failing fast with clear errors if results are missing or malformed.

        Args:
            job_record: The job record containing stage_results
            stage_number: Stage number to retrieve (1-based)

        Returns:
            Stage results dictionary with guaranteed structure

        Raises:
            ValueError: If stage_results missing or invalid
            KeyError: If requested stage not found
        """
        # StageResultContract already imported at top

        # === THE CRITICAL STRING CONVERSION ===
        #
        # THIS IS WHERE THE BOUNDARY CONTRACT IS ENFORCED!
        #
        # INPUT: stage_number is an INTEGER (e.g., 1, 2, 3)
        # OUTPUT: stage_key is a STRING (e.g., "1", "2", "3")
        #
        # WHY?
        # - PostgreSQL stores stage_results as JSONB
        # - JSON specification REQUIRES object keys to be strings
        # - When we store {1: "data"}, PostgreSQL converts to {"1": "data"}
        # - So we MUST use string keys for lookups
        #
        # EXAMPLE:
        # - Requesting stage_number = 1 (integer)
        # - Convert to stage_key = "1" (string)
        # - Lookup: job_record.stage_results["1"]
        #
        stage_key = str(stage_number)  # THE BOUNDARY CONVERSION

        # Check if any stage results exist
        if not job_record.stage_results:
            raise ValueError(
                f"Job {job_record.job_id[:16]}... has no stage_results at all. "
                f"This is a contract violation - completed stages should have results."
            )

        # Check if specific stage exists
        if stage_key not in job_record.stage_results:
            available_stages = list(job_record.stage_results.keys())
            raise KeyError(
                f"Stage {stage_number} results missing from job {job_record.job_id[:16]}... "
                f"Available stages: {available_stages}. "
                f"This indicates Stage {stage_number} hasn't completed yet or failed to store results."
            )

        stage_data = job_record.stage_results[stage_key]

        # Validate structure matches StageResultContract
        try:
            # Try to parse as StageResultContract to validate structure
            validated = StageResultContract(**stage_data)
            self.logger.debug(
                f"✓ Stage {stage_number} results validated: "
                f"{validated.task_count} tasks, "
                f"{validated.successful_tasks} successful, "
                f"status={validated.status}"
            )
        except Exception as e:
            # Log what fields are present for debugging
            available_fields = list(stage_data.keys()) if isinstance(stage_data, dict) else []
            raise ValueError(
                f"Stage {stage_number} results have invalid structure. "
                f"Available fields: {available_fields}. "
                f"Validation error: {e}. "
                f"Results must follow StageResultContract format."
            )

        return stage_data

    @enforce_contract(
        params={
            'job_record': JobRecord,
            'stage': int,
            'parameters': dict,
            'stage_results': Optional[dict]
        },
        returns=dict
    )
    def process_job_stage(self, job_record: 'JobRecord', stage: int, parameters: Dict[str, Any], stage_results: Dict[int, Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a specific stage by creating and queueing tasks.

        CRITICAL METHOD: This is the main orchestration point for stage execution.
        Creates tasks for the stage and queues them for parallel processing.
        Called by job queue processor when a job needs to execute a stage.

        CONTRACT: job_record MUST be JobRecord type (no dicts).

        Flow:
        1. Extract job info from record
        2. Create stage context
        3. Generate tasks via create_stage_tasks()
        4. Store tasks in database
        5. Queue tasks for execution

        Args:
            job_record: The job record from database (MUST be JobRecord type)
            stage: Stage number to process (1-based)
            parameters: Job parameters
            stage_results: Results from previous stages (keyed by stage number)

        Returns:
            Dictionary with stage processing results and task counts
        """
        # ENFORCE CONTRACT: job_record must be JobRecord type
        if not hasattr(job_record, 'job_id'):
            raise TypeError(
                f"job_record must be JobRecord type, got {type(job_record).__name__}. "
                f"Repository must return JobRecord objects, not dicts."
            )

        job_id = job_record.job_id
        job_type_from_record = job_record.job_type
            
        self.logger.info(f"Processing stage {stage} for job {job_id[:16]}... type={self.job_type} (record_type={job_type_from_record})")
        
        # Create job and stage contexts
        job_context = self.create_job_context(
            job_id=job_id, 
            parameters=parameters,
            current_stage=stage, 
            stage_results=stage_results or {}
        )
        
        stage_context = self.create_stage_context(job_context, stage)
        
        # === CRITICAL: Create tasks for this stage via controller's abstract method ===
        try:
            # Extract previous stage results if this is stage 2+
            # Previous stage results enable data flow between stages
            # Note: stage_results uses string keys (JSON boundary requirement) but stage is int (domain logic)
            previous_stage_results = stage_results.get(str(stage - 1)) if stage_results and stage > 1 else None

            # Call the concrete controller's implementation to create tasks
            # This is where job-specific orchestration logic lives
            task_definitions = self.create_stage_tasks(
                stage_number=stage,
                job_id=job_id,
                job_parameters=parameters,
                previous_stage_results=previous_stage_results
            )
            self.logger.info(f"Created {len(task_definitions)} task definitions for stage {stage}")
            
            # DEBUG: Log all task definitions created
            self.logger.debug(f"🔍 TASK DEFINITIONS CREATED:")
            for i, task_def in enumerate(task_definitions):
                self.logger.debug(f"  [{i+1}] Task ID: {task_def.task_id}")
                self.logger.debug(f"  [{i+1}] Task Type: {task_def.task_type}")
                self.logger.debug(f"  [{i+1}] Stage: {task_def.stage_number}")
                self.logger.debug(f"  [{i+1}] Job ID: {task_def.job_id[:16]}...")
                self.logger.debug(f"  [{i+1}] Parameters: {task_def.parameters}")
                self.logger.debug(f"  [{i+1}] ---")
        except Exception as e:
            self.logger.error(f"Failed to create stage tasks: {e}")
            raise RuntimeError(f"Failed to create tasks for stage {stage}: {e}")
        
        # Create and store task records, then queue them
        self.logger.debug(f"🏗️ Starting task creation and queueing process")
        try:
                self.logger.debug(f"📦 RepositoryFactory import successful")
        except Exception as repo_import_error:
            self.logger.error(f"❌ CRITICAL: Failed to import RepositoryFactory: {repo_import_error}")
            self.logger.error(f"📍 RepositoryFactory import traceback: {traceback.format_exc()}")
            raise RuntimeError(f"Failed to import RepositoryFactory: {repo_import_error}")
        
        try:
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
            task_repo = repos['task_repo']
            self.logger.debug(f"✅ Repositories created successfully: task_repo={type(task_repo)}")
        except Exception as repo_create_error:
            self.logger.error(f"❌ CRITICAL: Failed to create repositories: {repo_create_error}")
            self.logger.error(f"📍 Repository creation traceback: {traceback.format_exc()}")
            raise RuntimeError(f"Failed to create repositories: {repo_create_error}")
        
        # Initialize counters and task processing
        queued_tasks = 0
        failed_tasks = 0
        task_creation_failures = 0
        task_queueing_failures = 0
        
        self.logger.info(f"🚀 Processing {len(task_definitions)} task definitions for stage {stage}")
        
        for i, task_def in enumerate(task_definitions):
            self.logger.debug(f"📋 Processing task {i+1}/{len(task_definitions)}: {task_def.task_id}")
            
            try:
                # === STEP 1: CREATE TASK RECORD IN DATABASE ===
                self.logger.debug(f"💾 Creating task record in database for: {task_def.task_id}")
                try:
                    # CONTRACT: Every task MUST have semantic task_index for cross-stage tracking
                    # The task_index enables tasks in stage N to find their data from stage N-1
                    if 'task_index' not in task_def.parameters:
                        raise ValueError(
                            f"TaskDefinition missing required 'task_index' parameter. "
                            f"Controller must provide semantic task index (e.g., 'greet_0', 'tile_x5_y10'). "
                            f"Found parameters: {list(task_def.parameters.keys())}"
                        )

                    # Validate task_index is non-empty string
                    semantic_task_index = task_def.parameters['task_index']
                    if not isinstance(semantic_task_index, str) or not semantic_task_index.strip():
                        raise ValueError(
                            f"TaskDefinition 'task_index' must be non-empty string. "
                            f"Got: {semantic_task_index} (type: {type(semantic_task_index)})"
                        )
                    
                    # CONTRACT ENFORCEMENT: Use factory method instead of direct creation
                    # The TaskDefinition already has all required fields including job_type
                    # from when it was created in create_stage_tasks()
                    self.logger.debug(f"🔍 Using TaskDefinition factory method for task creation:")
                    self.logger.debug(f"    task_id: {task_def.task_id}")
                    self.logger.debug(f"    parent_job_id: {task_def.job_id[:16]}...")
                    self.logger.debug(f"    job_type: {task_def.job_type}")
                    self.logger.debug(f"    task_type: {task_def.task_type}")
                    self.logger.debug(f"    stage: {task_def.stage_number}")
                    self.logger.debug(f"    task_index: {semantic_task_index}")
                    self.logger.debug(f"    parameters: {task_def.parameters}")

                    # Use factory method - this is the ONLY way to create tasks
                    task_record = task_repo.create_task_from_definition(task_def)
                    
                    # DEBUG: Log task record creation result
                    self.logger.debug(f"✅ Task record created successfully: {task_def.task_id}")
                    self.logger.debug(f"🔍 RETURNED task_record details:")
                    self.logger.debug(f"    task_record.task_id: {task_record.task_id}")
                    self.logger.debug(f"    task_record.parent_job_id: {task_record.parent_job_id[:16]}...")
                    self.logger.debug(f"    task_record.status: {task_record.status}")
                    self.logger.debug(f"    task_record.created_at: {task_record.created_at}")
                    self.logger.debug(f"📊 Task record type: {type(task_record)}, index={i}")
                except Exception as task_create_error:
                    self.logger.error(f"❌ CRITICAL: Failed to create task record: {task_def.task_id}")
                    self.logger.error(f"❌ Task creation error: {task_create_error}")
                    self.logger.error(f"🔍 Task creation error type: {type(task_create_error).__name__}")
                    self.logger.error(f"📍 Task creation traceback: {traceback.format_exc()}")
                    self.logger.error(f"📋 Task definition details: {task_def}")
                    task_creation_failures += 1
                    failed_tasks += 1
                    continue  # Skip to next task
                
                # === STEP 2: CREATE TASK QUEUE MESSAGE ===
                self.logger.debug(f"📨 Creating task queue message for: {task_record.task_id}")
                try:
                    task_message = TaskQueueMessage(
                        task_id=task_record.task_id,
                        parent_job_id=task_record.parent_job_id,
                        task_type=task_record.task_type,
                        stage=task_record.stage,
                        task_index=task_record.task_index,
                        parameters=task_record.parameters
                    )
                    self.logger.debug(f"✅ Task queue message created successfully")
                    self.logger.debug(f"📊 Message details: parent_job_id={task_message.parent_job_id[:16]}..., task_type={task_message.task_type}")
                except Exception as message_create_error:
                    self.logger.error(f"❌ CRITICAL: Failed to create task queue message: {task_def.task_id}")
                    self.logger.error(f"❌ Message creation error: {message_create_error}")
                    self.logger.error(f"🔍 Message creation error type: {type(message_create_error).__name__}")
                    self.logger.error(f"📍 Message creation traceback: {traceback.format_exc()}")
                    task_queueing_failures += 1
                    failed_tasks += 1
                    continue  # Skip to next task
                
                # === STEP 3: SETUP AZURE QUEUE CLIENT ===
                self.logger.debug(f"🔗 Setting up Azure Queue client for task: {task_record.task_id}")
                try:
                    
                    config = get_config()
                    account_url = config.queue_service_url
                    self.logger.debug(f"🌐 Queue service URL: {account_url}")
                    self.logger.debug(f"📤 Target task queue: {config.task_processing_queue}")
                    
                    # Create credential (reuse from RBAC configuration)
                    # Use QueueRepository singleton for task queue operations
                    self.logger.debug(f"📦 Getting QueueRepository singleton for task operations")
                    queue_repo = RepositoryFactory.create_queue_repository()
                    self.logger.debug(f"✅ QueueRepository obtained for tasks (singleton reused)")
                    
                except Exception as queue_setup_error:
                    self.logger.error(f"❌ CRITICAL: Failed to setup Azure Queue client for task: {task_record.task_id}")
                    self.logger.error(f"❌ Queue setup error: {queue_setup_error}")
                    self.logger.error(f"🔍 Queue setup error type: {type(queue_setup_error).__name__}")
                    self.logger.error(f"📍 Queue setup traceback: {traceback.format_exc()}")
                    self.logger.error(f"🌐 Account URL: {account_url if 'account_url' in locals() else 'undefined'}")
                    self.logger.error(f"📤 Task queue name: {config.task_processing_queue if 'config' in locals() else 'undefined'}")
                    task_queueing_failures += 1
                    failed_tasks += 1
                    continue  # Skip to next task
                
                # === STEP 4: SEND MESSAGE TO QUEUE ===
                self.logger.debug(f"📨 Sending task message to queue: {task_record.task_id}")
                try:
                    # Send using QueueRepository (handles encoding automatically)
                    self.logger.debug(f"🔍 Sending task to queue via QueueRepository: {task_record.task_id}")
                    self.logger.debug(f"    Queue: {config.task_processing_queue}")

                    message_id = queue_repo.send_message(config.task_processing_queue, task_message)

                    # DEBUG: Log queue send result
                    self.logger.debug(f"✅ Task message sent successfully to queue: {task_record.task_id}")
                    self.logger.debug(f"📨 Message ID: {message_id}")
                    
                    queued_tasks += 1
                    self.logger.info(f"✅ Task {i+1}/{len(task_definitions)} completed successfully: {task_record.task_id}")
                    self.logger.debug(f"📊 Running totals - Queued: {queued_tasks}, Failed: {failed_tasks}")
                    
                except Exception as message_send_error:
                    self.logger.error(f"❌ CRITICAL: Failed to send task message to queue: {task_record.task_id}")
                    self.logger.error(f"❌ Message send error: {message_send_error}")
                    self.logger.error(f"🔍 Message send error type: {type(message_send_error).__name__}")
                    self.logger.error(f"📍 Message send traceback: {traceback.format_exc()}")
                    self.logger.error(f"📋 Message JSON length: {len(message_json) if 'message_json' in locals() else 'undefined'}")
                    task_queueing_failures += 1
                    failed_tasks += 1
                    continue  # Skip to next task
                
            except Exception as overall_task_error:
                # Use task_record.task_id if available, otherwise fall back to task_def.task_id
                task_id_for_error = getattr(locals().get('task_record'), 'task_id', task_def.task_id) if 'task_record' in locals() else task_def.task_id
                self.logger.error(f"❌ CRITICAL: Unexpected error processing task {task_id_for_error}: {overall_task_error}")
                self.logger.error(f"🔍 Overall task error type: {type(overall_task_error).__name__}")
                self.logger.error(f"📍 Overall task error traceback: {traceback.format_exc()}")
                failed_tasks += 1
        
        # === COMPREHENSIVE RESULTS LOGGING ===
        self.logger.info(f"🏁 Task processing complete for stage {stage}")
        self.logger.info(f"📊 SUMMARY: {queued_tasks}/{len(task_definitions)} tasks queued successfully")
        self.logger.info(f"📊 FAILURES: {failed_tasks} total failures")
        self.logger.info(f"📊 BREAKDOWN: {task_creation_failures} database failures, {task_queueing_failures} queue failures")
        
        if failed_tasks > 0:
            self.logger.error(f"❌ CRITICAL: {failed_tasks} tasks failed during stage {stage} processing")
            self.logger.error(f"❌ Task creation failures: {task_creation_failures}")
            self.logger.error(f"❌ Task queueing failures: {task_queueing_failures}")
        
        if queued_tasks == 0:
            self.logger.error(f"❌ CRITICAL: NO TASKS were successfully queued for stage {stage}")
            self.logger.error(f"❌ This will cause the job to remain stuck in processing status")
        else:
            self.logger.info(f"✅ Successfully queued {queued_tasks} tasks for stage {stage}")
            self.logger.info(f"🎯 Tasks should now process via geospatial-tasks queue trigger")
        
        stage_results = {
            "stage_number": stage,
            "stage_name": stage_context.stage_name,
            "tasks_created": len(task_definitions),
            "tasks_queued": queued_tasks,
            "tasks_failed_to_queue": failed_tasks,
            "processing_status": "tasks_queued" if queued_tasks > 0 else "failed"
        }
        
        self.logger.info(f"Stage {stage} processing complete: {queued_tasks}/{len(task_definitions)} tasks queued successfully")
        return stage_results

    # ========================================================================
    # QUEUE ORCHESTRATION METHODS - Moved from function_app.py
    # ========================================================================
    # These methods handle the full lifecycle of queue message processing,
    # delegating to appropriate controllers and services for execution.
    # Added 12 SEP 2025 as part of function_app.py modularization effort.
    
    @enforce_contract(
        params={'job_message': JobQueueMessage},
        returns=dict
    )
    def process_job_queue_message(self, job_message: 'JobQueueMessage') -> Dict[str, Any]:
        """
        Process a job queue message by creating and queuing tasks for the current stage.

        This method orchestrates the job processing flow:
        1. Validates the job message
        2. Loads the job record from database
        3. Creates tasks for the current stage
        4. Queues tasks for execution
        5. Updates job status
        6. On failure, marks job as FAILED with error details

        ENHANCED (21 SEP 2025): Granular error handling at each step

        Args:
            job_message: Validated JobQueueMessage from queue

        Returns:
            Dict with processing results including task creation status

        Raises:
            ValueError: If job validation fails
            RuntimeError: If task creation or queueing fails
        """
        import traceback
        import time
        start_time = time.time()

        config = get_config()

        # Extract correlation ID if present
        correlation_id = job_message.parameters.get('_correlation_id', 'unknown') if job_message.parameters else 'unknown'
        self._current_correlation_id = correlation_id
        self.logger.info(f"[{correlation_id}] 🎬 Starting job stage processing for {job_message.job_id[:16]}... stage {job_message.stage}")

        # STEP 1: Repository Setup
        self.logger.debug(f"[{correlation_id}] STEP 1: Repository initialization")
        repos = None
        job_repo = None
        task_repo = None

        try:
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']
            task_repo = repos['task_repo']
            self.logger.debug(f"[{correlation_id}] ✅ Repositories initialized")
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"Repository initialization failed after {elapsed:.3f}s: {e}"
            self.logger.error(f"[{correlation_id}] ❌ {error_msg}")
            # Can't mark job as failed without repository
            raise RuntimeError(error_msg)

        # STEP 2: Job Record Retrieval
        self.logger.debug(f"[{correlation_id}] STEP 2: Job record retrieval")
        job_record = None

        try:
            job_record = job_repo.get_job(job_message.job_id)
            if not job_record:
                raise ValueError(f"Job not found: {job_message.job_id}")
            self.logger.debug(f"[{correlation_id}] ✅ Job record retrieved, status={job_record.status}")
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"Failed to retrieve job after {elapsed:.3f}s: {e}"
            self.logger.error(f"[{correlation_id}] ❌ {error_msg}")
            self._safe_mark_job_failed(job_message.job_id, error_msg, job_repo)
            raise ValueError(error_msg)
        
        # STEP 3: Status Validation
        self.logger.debug(f"[{correlation_id}] STEP 3: Status validation")

        try:
            if job_record.status == JobStatus.COMPLETED:
                self.logger.info(f"[{correlation_id}] ⏭ Job already completed, skipping stage {job_message.stage}")
                return {
                    'status': 'skipped',
                    'reason': 'job_already_completed',
                    'job_status': job_record.status.value,
                    'message': f'Job already completed with results',
                    'correlation_id': correlation_id
                }

            if job_record.stage > job_message.stage:
                self.logger.info(f"[{correlation_id}] ⏭ Job at stage {job_record.stage}, skipping stage {job_message.stage}")
                return {
                    'status': 'skipped',
                    'reason': 'stage_already_processed',
                    'current_stage': job_record.stage,
                    'requested_stage': job_message.stage,
                    'message': f'Job already advanced past stage {job_message.stage}',
                    'correlation_id': correlation_id
                }

            self.logger.debug(f"[{correlation_id}] ✅ Status validated, proceeding with stage {job_message.stage}")
        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = f"Status validation failed after {elapsed:.3f}s: {e}"
            self.logger.error(f"[{correlation_id}] ❌ {error_msg}")
            self._safe_mark_job_failed(job_message.job_id, error_msg, job_repo)
            raise ValueError(error_msg)
        
        # Get previous stage results if not first stage
        # === RETRIEVING PREVIOUS STAGE RESULTS ===
        #
        # STAGE KEY BOUNDARY CONTRACT IN ACTION:
        #
        # WHAT'S HAPPENING HERE:
        # - job_message.stage is an INTEGER (e.g., stage = 2)
        # - We need results from the previous stage (stage - 1 = 1)
        # - But stage_results uses STRING keys because of JSON
        #
        # THE MATH:
        # - Current stage: 2 (integer from message)
        # - Previous stage: 2 - 1 = 1 (integer arithmetic)
        # - Inside _validate_and_get_stage_results: str(1) = "1" (string key)
        #
        # WHY CHECK stage > 1?
        # - Stage 1 has no previous stage (it's the first stage)
        # - Stage 2+ need results from their previous stage
        #
        # VALIDATION:
        # _validate_and_get_stage_results will:
        # 1. Convert stage_number to string key: str(stage_number)
        # 2. Check if that key exists in stage_results
        # 3. Validate the structure matches StageResultContract
        # 4. Return the validated results or throw error
        #
        previous_stage_results = None
        if job_message.stage > 1:
            # Use validation helper to ensure stage results exist and are valid
            try:
                previous_stage_results = self._validate_and_get_stage_results(
                    job_record=job_record,
                    stage_number=job_message.stage - 1  # INTEGER arithmetic, converted to string inside
                )
                self.logger.debug(
                    f"✓ Retrieved and validated stage {job_message.stage - 1} results"
                )
            except (ValueError, KeyError) as e:
                # Mark job as FAILED when stage validation fails
                error_msg = f"Cannot process stage {job_message.stage} - previous stage results invalid: {e}"
                self.logger.error(f"[JOB_STAGE_VALIDATION_FAILED] {error_msg}")

                try:
                    job_repo.update_job_status_with_validation(
                        job_id=job_message.job_id,
                        new_status=JobStatus.FAILED,
                        additional_updates={'error_details': error_msg}
                    )
                    self.logger.error(f"[JOB_FAILED] Job {job_message.job_id[:16]}... marked as FAILED due to stage validation error")
                except Exception as update_error:
                    self.logger.error(f"[JOB_FAILED_UPDATE_ERROR] Failed to mark job as FAILED: {update_error}")

                # Re-raise with additional context
                raise ValueError(error_msg) from e

        # Create tasks for current stage
        try:
            tasks = self.create_stage_tasks(
                stage_number=job_message.stage,
                job_id=job_message.job_id,
                job_parameters=job_message.parameters,
                previous_stage_results=previous_stage_results
            )

            if not tasks:
                raise RuntimeError(f"No tasks created for stage {job_message.stage}")

        except Exception as task_creation_error:
            # Mark job as FAILED when task creation fails
            error_msg = f"Failed to create tasks for stage {job_message.stage}: {str(task_creation_error)}"
            self.logger.error(f"[JOB_TASK_CREATION_FAILED] {error_msg}")
            self.logger.error(f"[JOB_TASK_CREATION_FAILED] Traceback: {traceback.format_exc()}")

            try:
                job_repo.update_job_status_with_validation(
                    job_id=job_message.job_id,
                    new_status=JobStatus.FAILED,
                    additional_updates={'error_details': error_msg}
                )
                self.logger.error(f"[JOB_FAILED] Job {job_message.job_id[:16]}... marked as FAILED due to task creation error")
            except Exception as update_error:
                self.logger.error(f"[JOB_FAILED_UPDATE_ERROR] Failed to mark job as FAILED: {update_error}")

            raise RuntimeError(error_msg) from task_creation_error
        
        self.logger.info(f"Created {len(tasks)} tasks for stage {job_message.stage}")
        
        # Queue all tasks
        tasks_queued = 0
        tasks_failed = 0
        
        # Get QueueRepository singleton for task queue operations
        queue_repo = RepositoryFactory.create_queue_repository()
        self.logger.debug(f"📦 Using QueueRepository for task submission (singleton reused)")
        
        for task_def in tasks:
            try:
                # Check if task already exists (idempotency)
                existing_task = task_repo.get_task(task_def.task_id)
                if existing_task:
                    self.logger.info(f"Task {task_def.task_id} already exists with status {existing_task.status}, skipping creation")
                    # If task exists and is not failed, consider it queued
                    if existing_task.status != TaskStatus.FAILED:
                        tasks_queued += 1
                    continue

                # ENFORCE CONTRACT: Use factory methods only
                task_record = task_def.to_task_record()
                success = task_repo.create_task(task_record)

                if not success:
                    # Contract violation - task creation should succeed or throw
                    raise RuntimeError(f"Failed to create task record for {task_def.task_id}")

                task_message = task_def.to_queue_message()
                # Send using QueueRepository (handles encoding automatically)
                message_id = queue_repo.send_message(config.task_processing_queue, task_message)
                self.logger.debug(f"📨 Task queued with message ID: {message_id}")
                tasks_queued += 1
                
            except Exception as e:
                self.logger.error(f"Failed to queue task {task_def.task_id}: {e}")
                tasks_failed += 1
        
        # Update job status based on results
        if tasks_queued > 0:
            # Only update status if not already PROCESSING (e.g., Stage 2+ messages)
            if job_record.status != JobStatus.PROCESSING:
                job_repo.update_job_status_with_validation(
                    job_id=job_message.job_id,
                    new_status=JobStatus.PROCESSING
                )
            result = {
                'status': 'success',
                'tasks_created': len(tasks),
                'tasks_queued': tasks_queued,
                'tasks_failed': tasks_failed
            }
        else:
            job_repo.update_job_status_with_validation(
                job_id=job_message.job_id,
                new_status=JobStatus.FAILED,
                additional_updates={'error_details': 'No tasks successfully queued'}
            )
            raise RuntimeError(f"Failed to queue any tasks for stage {job_message.stage}")
        
        return result
    
    @enforce_contract(
        params={'task_message': TaskQueueMessage},
        returns=dict
    )
    def process_task_queue_message(self, task_message: 'TaskQueueMessage') -> Dict[str, Any]:
        """
        Process a task queue message by executing the task and handling completion.

        CRITICAL METHOD: Implements the "last task turns out the lights" pattern.
        When a task completes, checks if it's the last task in its stage.
        If so, triggers stage advancement or job completion.

        Flow:
        1. Validate task is in QUEUED status (no retries)
        2. Update to PROCESSING status
        3. Execute task via TaskHandlerFactory (Service layer)
        4. Call PostgreSQL completion function (atomic check)
        5. If last task in stage, handle stage/job completion

        Args:
            task_message: Validated TaskQueueMessage from queue

        Returns:
            Dict with task execution results and completion status
        """
        
        # ENFORCE CONTRACT: Single repository creation pattern
        repos = RepositoryFactory.create_repositories()
        job_repo = repos['job_repo']
        task_repo = repos['task_repo']
        stage_completion_repo = repos['stage_completion_repo']
        
        # DEBUG: Query task state BEFORE updating
        self.logger.debug(f"[TASK_COMPLETION_DEBUG] Starting processing for task {task_message.task_id}")
        existing_task = task_repo.get_task(task_message.task_id)
        if not existing_task:
            error_msg = f"Task {task_message.task_id} does not exist in database"
            self.logger.error(f"[TASK_COMPLETION_ERROR] {error_msg}")
            raise ValueError(error_msg)
        
        self.logger.debug(f"[TASK_COMPLETION_DEBUG] Task {task_message.task_id} current status: {existing_task.status}")
        
        # Enhanced logging for status validation debugging
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] Checking task status for {task_message.task_id}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] existing_task.status type: {type(existing_task.status)}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] existing_task.status value: {existing_task.status}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] existing_task.status repr: {repr(existing_task.status)}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] TaskStatus.QUEUED type: {type(TaskStatus.QUEUED)}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] TaskStatus.QUEUED value: {TaskStatus.QUEUED}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] TaskStatus.QUEUED repr: {repr(TaskStatus.QUEUED)}")
        
        # Test the comparison explicitly
        comparison_result = existing_task.status != TaskStatus.QUEUED
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] Comparison (status != QUEUED): {comparison_result}")
        self.logger.debug(f"[STATUS_VALIDATION_DEBUG] Are they equal? (status == QUEUED): {existing_task.status == TaskStatus.QUEUED}")
        
        # ENFORCE CONTRACT: Task must be in QUEUED status
        if existing_task.status != TaskStatus.QUEUED:
            # No defensive handling - fail fast and loud
            raise ValueError(
                f"Task {task_message.task_id} has invalid status for processing: "
                f"{existing_task.status} (expected: {TaskStatus.QUEUED}). "
                f"This indicates a contract violation - tasks should only be processed once."
            )
        
        # Update task status to processing before execution
        self.logger.info(f"[TASK_COMPLETION] Updating task {task_message.task_id} from {existing_task.status} to PROCESSING")
        task_updated = task_repo.update_task(
            task_id=task_message.task_id,
            updates={'status': TaskStatus.PROCESSING}
        )
        
        if not task_updated:
            error_msg = f"Failed to update task {task_message.task_id} to processing status"
            self.logger.error(f"[TASK_COMPLETION_ERROR] {error_msg}")
            raise RuntimeError(error_msg)
        
        # DEBUG: Verify update succeeded
        updated_task = task_repo.get_task(task_message.task_id)
        self.logger.debug(f"[TASK_COMPLETION_DEBUG] Task {task_message.task_id} status after update: {updated_task.status}")
        
        # === EXECUTE TASK VIA SERVICE LAYER ===
        # Task execution is delegated to Service layer via TaskHandlerFactory
        # Service layer contains all business logic, controller just orchestrates
        task_result = None
        self.logger.debug(f"[TASK_EXECUTION_DEBUG] Starting execution for task {task_message.task_id}")

        try:
            # Get appropriate service handler for this task type
            # Factory pattern routes to correct Service implementation
            handler = TaskHandlerFactory.get_handler(task_message, task_repo)
            self.logger.debug(f"[TASK_EXECUTION_DEBUG] Got handler for task type: {task_message.task_type}")

            # Execute the business logic - returns TaskResult
            import time
            start_time = time.time()
            task_result = handler(task_message.parameters)
            execution_time = time.time() - start_time
            
            self.logger.debug(f"[TASK_EXECUTION_DEBUG] Task {task_message.task_id} execution completed in {execution_time:.3f}s")
            self.logger.debug(f"[TASK_EXECUTION_DEBUG] Task result success: {task_result.success}, has error: {task_result.error_details is not None}")
            
        except Exception as exec_error:
            error_msg = f"Task execution failed for {task_message.task_id}: {type(exec_error).__name__}: {str(exec_error)}"
            self.logger.error(f"[TASK_EXECUTION_ERROR] {error_msg}")
            self.logger.error(f"[TASK_EXECUTION_ERROR] Traceback: {traceback.format_exc()}")
            
            # No fallback - create explicit failure result
            task_result = TaskResult(
                task_id=task_message.task_id,
                job_id=task_message.parent_job_id,
                stage_number=task_message.stage,
                task_type=task_message.task_type,
                status=TaskStatus.FAILED,
                result_data={},
                error_details=error_msg,
                execution_time_seconds=0.0
            )
        
        # === CRITICAL: ATOMIC COMPLETION CHECK ("Last Task Turns Out Lights") ===
        # This PostgreSQL function atomically:
        # 1. Updates task status to COMPLETED/FAILED
        # 2. Checks if this was the last task in the stage
        # 3. Returns stage completion status
        # Using advisory locks to prevent race conditions
        stage_completion = None
        self.logger.debug(f"[TASK_COMPLETION_SQL_DEBUG] Starting SQL completion for task {task_message.task_id}")

        # Verify task is still PROCESSING before completion
        pre_sql_task = task_repo.get_task(task_message.task_id)
        self.logger.debug(f"[TASK_COMPLETION_SQL_DEBUG] Task status before SQL function: {pre_sql_task.status}")
        
        if pre_sql_task.status != TaskStatus.PROCESSING:
            error_msg = f"Task {task_message.task_id} has unexpected status before SQL completion: {pre_sql_task.status} (expected: PROCESSING)"
            self.logger.error(f"[TASK_COMPLETION_SQL_ERROR] {error_msg}")
            raise RuntimeError(error_msg)
        
        try:
            # Log SQL function parameters
            sql_params = {
                'task_id': task_message.task_id,
                'job_id': task_message.parent_job_id,
                'stage': task_message.stage,
                'has_result_data': task_result.result_data is not None if task_result else False,
                'has_error': task_result.error_details is not None if task_result else True,
                'task_success': task_result.success if task_result else False
            }
            self.logger.debug(f"[TASK_COMPLETION_SQL_DEBUG] SQL function params: {sql_params}")
            
            if task_result and task_result.success:
                self.logger.debug(f"[TASK_COMPLETION_SQL_DEBUG] Calling SQL completion for successful task")
                stage_completion = stage_completion_repo.complete_task_and_check_stage(
                    task_id=task_message.task_id,
                    job_id=task_message.parent_job_id,
                    stage=task_message.stage,
                    result_data=task_result.result_data if task_result.result_data else {},
                    error_details=None
                )
            else:
                error_msg = task_result.error_details if task_result else 'Task execution failed - no result object'
                self.logger.debug(f"[TASK_COMPLETION_SQL_DEBUG] Calling SQL completion for failed task: {error_msg[:100]}")
                stage_completion = stage_completion_repo.complete_task_and_check_stage(
                    task_id=task_message.task_id,
                    job_id=task_message.parent_job_id,
                    stage=task_message.stage,
                    result_data={},
                    error_details=error_msg
                )
            
            # Log SQL function results
            self.logger.debug(f"[TASK_COMPLETION_SQL_DEBUG] SQL function returned:")
            self.logger.debug(f"  - task_updated: {stage_completion.task_updated}")
            self.logger.debug(f"  - stage_complete: {stage_completion.stage_complete}")
            self.logger.debug(f"  - job_id: {stage_completion.job_id}")
            self.logger.debug(f"  - stage_number: {stage_completion.stage_number}")
            self.logger.debug(f"  - remaining_tasks: {stage_completion.remaining_tasks}")
                
            # Check if task was actually updated
            if not stage_completion.task_updated:
                error_msg = f"SQL function failed to update task {task_message.task_id}"
                self.logger.error(f"[TASK_COMPLETION_SQL_ERROR] {error_msg}")
                
                # Query current task state for debugging
                current_task = task_repo.get_task(task_message.task_id)
                self.logger.error(f"[TASK_COMPLETION_SQL_ERROR] Current task status: {current_task.status if current_task else 'NOT FOUND'}")
                
                raise RuntimeError(error_msg)
                
        except Exception as completion_error:
            error_msg = f"Task completion SQL failed for {task_message.task_id}: {type(completion_error).__name__}: {str(completion_error)}"
            self.logger.error(f"[TASK_COMPLETION_SQL_ERROR] {error_msg}")
            self.logger.error(f"[TASK_COMPLETION_SQL_ERROR] Traceback: {traceback.format_exc()}")
            
            # No fallback - raise the error
            raise RuntimeError(error_msg) from completion_error
        
        # Handle stage completion
        stage_advancement_result = None
        if stage_completion and stage_completion.stage_complete:
            self.logger.info(f"[STAGE_ADVANCEMENT] Stage {task_message.stage} complete - handling advancement")
            self.logger.debug(f"[STAGE_ADVANCEMENT_DEBUG] Stage completion detected with 0 remaining tasks")
            
            try:
                stage_advancement_result = self._handle_stage_completion(
                    job_id=task_message.parent_job_id,
                    stage=task_message.stage,
                    job_repo=job_repo,
                    stage_completion_repo=stage_completion_repo
                )
                self.logger.debug(f"[STAGE_ADVANCEMENT_DEBUG] Stage advancement result: {stage_advancement_result}")
            except Exception as stage_error:
                error_msg = f"Stage advancement failed: {type(stage_error).__name__}: {str(stage_error)}"
                self.logger.error(f"[STAGE_ADVANCEMENT_ERROR] {error_msg}")
                self.logger.error(f"[STAGE_ADVANCEMENT_ERROR] Traceback: {traceback.format_exc()}")

                # CRITICAL: Mark job as FAILED when stage advancement fails
                try:
                    job_repo.update_job_status_with_validation(
                        job_id=task_message.parent_job_id,
                        new_status=JobStatus.FAILED,
                        additional_updates={'error_details': error_msg}
                    )
                    self.logger.error(f"[JOB_FAILED] Job {task_message.parent_job_id[:16]}... marked as FAILED due to stage advancement error")
                except Exception as update_error:
                    self.logger.error(f"[JOB_FAILED_UPDATE_ERROR] Failed to mark job as FAILED: {update_error}")

                raise RuntimeError(error_msg) from stage_error
        else:
            self.logger.debug(f"[STAGE_ADVANCEMENT_DEBUG] Stage not complete - remaining tasks: {stage_completion.remaining_tasks if stage_completion else 'N/A'}")
        
        # Build response with all debug info
        result = {
            'task_id': task_message.task_id,
            'status': 'completed' if task_result and task_result.success else 'failed',
            'stage_complete': stage_completion.stage_complete if stage_completion else False,
            'remaining_tasks': stage_completion.remaining_tasks if stage_completion else 0
        }
        
        # Add stage advancement details if stage completed
        if stage_advancement_result:
            result['stage_advancement'] = stage_advancement_result
        
        self.logger.info(f"✅ Task processing complete: {result}")    
        return result
    
    def _handle_stage_completion(
        self,
        job_id: str,
        stage: int,
        job_repo: Any,  # Repository type
        stage_completion_repo: 'StageCompletionRepository'
    ) -> Dict[str, Any]:
        """
        Handle stage completion by advancing to next stage or completing job.

        CRITICAL: This is the SINGLE ORCHESTRATION POINT for stage completion.
        All orchestration logic lives here in the Controller layer.

        The stage_completion_repo provides only atomic database operations:
        - check_job_completion() returns completion status
        - advance_job_stage() atomically increments stage
        - No business logic in repository layer!

        Decision tree:
        - If final stage: Complete the job
        - If tasks failed: Mark job as failed
        - Otherwise: Advance to next stage and queue new job message

        Args:
            job_id: The job ID (SHA256 hash)
            stage: The completed stage number (1-based)
            job_repo: Job repository instance
            stage_completion_repo: Provides atomic SQL operations only

        Returns:
            Dict with completion status and next actions
        """
        
        config = get_config()
        
        # Get job record
        job_record = job_repo.get_job(job_id)
        if not job_record:
            raise ValueError(f"Job not found: {job_id}")
        
        # Check if final stage
        if stage >= job_record.total_stages:
            # Final stage - complete the job
            self.logger.info(f"Final stage complete - completing job {job_id[:16]}...")
            
            # Get all task results
            job_completion = stage_completion_repo.check_job_completion(job_id)
            
            if not job_completion.job_complete:
                raise RuntimeError(f"Job completion check failed: {job_id}")
            
            # ENFORCE CONTRACT: Repository must return TaskResult objects
            task_results = []
            has_failed_tasks = False
            for task_result in job_completion.task_results or []:
                if not isinstance(task_result, TaskResult):
                    raise TypeError(
                        f"Repository returned {type(task_result).__name__} instead of TaskResult. "
                        f"Repository must convert database records to Pydantic models."
                    )
                if task_result.status == TaskStatus.FAILED:
                    has_failed_tasks = True
                task_results.append(task_result)
            
            # Aggregate results
            aggregated_results = self.aggregate_stage_results(
                stage_number=stage,
                task_results=task_results
            )
            
            # Determine final job status based on task results
            if has_failed_tasks:
                final_status = JobStatus.FAILED
                self.logger.warning(f"Job {job_id[:16]}... has failed tasks - marking as FAILED")
            else:
                final_status = JobStatus.COMPLETED
                self.logger.info(f"Job {job_id[:16]}... completed successfully")
            
            # Update job with final status
            job_repo.update_job_status_with_validation(
                job_id=job_id,
                new_status=final_status,
                additional_updates={'result_data': aggregated_results}
            )
            
            # FUTURE ENHANCEMENT: Outbound HTTP webhook notifications
            # When job completes, send HTTP POST to external applications
            # This will enable:
            # - Real-time notifications to client systems  
            # - Integration with external workflows
            # - Event-driven architecture patterns
            # - Async result delivery to subscribers
            # 
            # Example implementation:
            # if job_record.parameters.get('webhook_url'):
            #     webhook_payload = {
            #         'job_id': job_id,
            #         'status': 'completed',
            #         'results': aggregated_results,
            #         'timestamp': datetime.now(timezone.utc).isoformat()
            #     }
            #     send_webhook_notification(
            #         url=job_record.parameters['webhook_url'],
            #         payload=webhook_payload,
            #         hmac_secret=config.webhook_secret
            #     )
            
            # Return completion result
            return {
                'status': 'completed',
                'job_id': job_id,
                'final_stage': stage,
                'total_stages': job_record.total_stages,
                'aggregated_results': aggregated_results,
                'message': f'Job {job_id[:16]}... completed all {job_record.total_stages} stages successfully'
            }
            
        else:
            # Not final stage - check if we should advance to next stage
            next_stage = stage + 1
            
            # Get current stage results and check for failures
            stage_completion = stage_completion_repo.check_job_completion(job_id)
            stage_results = {
                'stage_number': stage,
                'completed_tasks': len(stage_completion.task_results or []),
                'task_results': stage_completion.task_results or [],
                'completed_at': datetime.now(timezone.utc).isoformat()
            }
            
            # Check if any tasks in this stage failed
            has_failed_tasks = False
            for task_data in stage_completion.task_results or []:
                if isinstance(task_data, dict):
                    task_status = task_data.get('status', TaskStatus.COMPLETED.value)
                    if task_status == TaskStatus.FAILED.value or task_status == 'failed':
                        has_failed_tasks = True
                        break
            
            if has_failed_tasks:
                # Stage has failed tasks - mark job as failed
                self.logger.warning(f"Stage {stage} has failed tasks - marking job {job_id[:16]}... as FAILED")
                
                # Update job to failed status
                job_repo.update_job_status_with_validation(
                    job_id=job_id,
                    new_status=JobStatus.FAILED,
                    additional_updates={
                        'result_data': stage_results,
                        'error_details': f'Stage {stage} failed with one or more task failures'
                    }
                )
                
                return {
                    'status': 'job_failed',
                    'job_id': job_id,
                    'failed_stage': stage,
                    'stage_results': stage_results,
                    'message': f'Job {job_id[:16]}... failed at stage {stage} due to task failures'
                }
            
            # No failures - advance to next stage
            self.logger.info(f"Advancing job {job_id[:16]}... to stage {next_stage}")

            # ENFORCE CONTRACT: Repository must return TaskResult objects
            task_results = []
            for task_result in stage_completion.task_results or []:
                if not isinstance(task_result, TaskResult):
                    raise TypeError(
                        f"Repository returned {type(task_result).__name__} instead of TaskResult. "
                        f"Repository must convert database records to Pydantic models."
                    )
                task_results.append(task_result)

            # Call the controller's aggregate_stage_results to get properly formatted results
            aggregated_stage_results = self.aggregate_stage_results(
                stage_number=stage,
                task_results=task_results
            )

            self.logger.debug(f"Aggregated stage {stage} results: {list(aggregated_stage_results.keys()) if isinstance(aggregated_stage_results, dict) else 'non-dict'}")

            # Advance stage with the aggregated results
            advancement = stage_completion_repo.advance_job_stage(
                job_id=job_id,
                current_stage=stage,
                stage_results=aggregated_stage_results
            )
            
            if not advancement.job_updated:
                raise RuntimeError(f"Failed to advance job {job_id} to stage {next_stage}")
            
            # Queue job for next stage processing using QueueRepository
            queue_repo = RepositoryFactory.create_queue_repository()
            self.logger.debug(f"📦 Using QueueRepository for stage advancement (singleton reused)")

            # Create job message for next stage
            job_message = JobQueueMessage(
                job_id=job_id,
                job_type=job_record.job_type,
                stage=next_stage,
                parameters=job_record.parameters
            )

            # Send using QueueRepository (handles encoding automatically)
            message_id = queue_repo.send_message(config.job_processing_queue, job_message)
            self.logger.debug(f"📨 Next stage job queued with message ID: {message_id}")
            
            self.logger.info(f"Job {job_id[:16]}... queued for stage {next_stage}")
            
            # Return stage advancement result
            return {
                'status': 'stage_advanced',
                'job_id': job_id,
                'completed_stage': stage,
                'next_stage': next_stage,
                'stage_results': stage_results,
                'message': f'Job {job_id[:16]}... advanced from stage {stage} to stage {next_stage}'
            }

    def _safe_mark_job_failed(self, job_id: str, error_msg: str, job_repo=None) -> None:
        """Safely attempt to mark job as failed, don't raise if it fails.

        Args:
            job_id: Job ID to mark as failed
            error_msg: Error message to record
            job_repo: Optional repository instance to reuse
        """
        # Extract correlation ID if available
        correlation_id = 'unknown'
        try:
            if hasattr(self, '_current_correlation_id'):
                correlation_id = self._current_correlation_id
        except:
            pass

        try:
            if not job_repo:
                repos = RepositoryFactory.create_repositories()
                job_repo = repos['job_repo']

            # Check current status first
            job = job_repo.get_job(job_id)
            if job and job.status not in [JobStatus.FAILED, JobStatus.COMPLETED]:
                job_repo.update_job_status_with_validation(
                    job_id=job_id,
                    new_status=JobStatus.FAILED,
                    additional_updates={
                        'error_details': error_msg,
                        'failed_at': datetime.now(timezone.utc).isoformat(),
                        'correlation_id': correlation_id
                    }
                )
                self.logger.info(f"[{correlation_id}] 📝 Job {job_id[:16]}... marked as FAILED: {error_msg[:100]}")
            elif job and job.status == JobStatus.FAILED:
                self.logger.debug(f"[{correlation_id}] Job {job_id[:16]}... already FAILED")
            elif job and job.status == JobStatus.COMPLETED:
                self.logger.warning(f"[{correlation_id}] Job {job_id[:16]}... is COMPLETED, not updating")
        except Exception as e:
            self.logger.error(f"[{correlation_id}] Failed to mark job {job_id[:16]}... as FAILED: {e}")

    def _safe_mark_task_failed(self, task_id: str, error_msg: str, task_repo=None) -> None:
        """Safely attempt to mark task as failed, don't raise if it fails.

        Args:
            task_id: Task ID to mark as failed
            error_msg: Error message to record
            task_repo: Optional repository instance to reuse
        """
        # Extract correlation ID if available
        correlation_id = 'unknown'
        try:
            if hasattr(self, '_current_correlation_id'):
                correlation_id = self._current_correlation_id
        except:
            pass

        try:
            if not task_repo:
                repos = RepositoryFactory.create_repositories()
                task_repo = repos['task_repo']

            # Check current status first
            task = task_repo.get_task(task_id)
            if task and task.status not in [TaskStatus.FAILED, TaskStatus.COMPLETED]:
                task_repo.update_task(
                    task_id=task_id,
                    updates={
                        'status': TaskStatus.FAILED,
                        'error_details': error_msg,
                        'correlation_id': correlation_id
                    }
                )
                self.logger.info(f"[{correlation_id}] 📝 Task {task_id} marked as FAILED: {error_msg[:100]}")
            elif task and task.status == TaskStatus.FAILED:
                self.logger.debug(f"[{correlation_id}] Task {task_id} already FAILED")
            elif task and task.status == TaskStatus.COMPLETED:
                self.logger.warning(f"[{correlation_id}] Task {task_id} is COMPLETED, not updating")
        except Exception as e:
            self.logger.error(f"[{correlation_id}] Failed to mark task {task_id} as FAILED: {e}")

    def __repr__(self):
        return f"<{self.__class__.__name__}(job_type='{self.job_type}', stages={len(self.workflow_definition.stages)})>"