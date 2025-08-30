"""
Base Stage Model - Job→Stage→Task Architecture Coordination

Abstract base class defining the stage coordination patterns for the Azure Geospatial ETL Pipeline.
Provides comprehensive stage execution logic, parallel task creation and management, completion
detection, and result aggregation patterns that concrete stage implementations customize for
their specific coordination requirements within multi-stage workflows.

Architecture Responsibility:
    This module defines the STAGE LAYER within the Job→Stage→Task architecture:
    - Job Layer: Orchestrates multi-stage workflows with stage transition logic
    - Stage Layer: THIS MODULE - Coordinates parallel task execution within workflow phases
    - Task Layer: Implements business logic for individual processing units
    - Repository Layer: Handles persistent storage and queue message management

Key Features:
- Abstract base class enforcing consistent stage implementation patterns
- Parallel task creation with customizable task parameter generation
- Stage prerequisite validation and conditional execution logic
- Fan-out task creation with configurable parallelism limits
- Stage completion detection through task result aggregation
- Flexible stage skipping logic based on context and previous results
- Comprehensive error handling for partial stage failures
- Result aggregation patterns for inter-stage data passing

Stage Execution Flow:
    1. VALIDATION: validate_prerequisites() → Ensure stage can execute
    2. PREPARATION: prepare_stage_execution() → Setup stage context
    3. CONDITIONAL: should_skip_stage() → Determine if stage needed
    4. TASK CREATION: create_tasks() → Fan-out to parallel tasks
    5. TASK EXECUTION: Tasks execute in parallel (handled by queue system)
    6. RESULT AGGREGATION: aggregate_stage_results() → Consolidate task outputs
    7. COMPLETION: Stage marked complete, results passed to next stage

Parallel Task Coordination:
    Stage → create_tasks(n) → Task 1 (parallel)
                           → Task 2 (parallel)
                           → Task n (parallel)
                                  ↓ All complete
    Stage ← aggregate_stage_results() ← Task Results

Fan-Out/Fan-In Pattern:
    Previous Stage Results
            ↓
    Stage.create_tasks() → Multiple parallel tasks
            ↓                      ↓
    Task Parameters ← calculate_task_parameters()
            ↓                      ↓
    Parallel Execution → Task Results
            ↓                      ↓
    aggregate_stage_results() → Next Stage Input

Integration Points:
- Extended by concrete stage implementations within controller workflows
- Uses StageExecutionContext for parameter passing and result coordination
- Integrates with task queue systems for parallel task execution
- Connects to repository layer for task creation and status tracking
- Provides results to job layer for workflow progression decisions

Abstract Methods (Must Implement):
- create_tasks(): Stage-specific task creation logic with parallelism
- should_skip_stage(): Conditional stage execution based on context
- validate_prerequisites(): Stage execution prerequisite validation

Concrete Methods (Ready to Use):
- prepare_stage_execution(): Pre-execution setup and context modification
- calculate_task_parameters(): Standardized task parameter generation
- aggregate_stage_results(): Default result aggregation with task collection
- handle_stage_failure(): Error handling for partial failures
- is_stage_complete(): Completion detection based on task counts

Usage Example:
    class CustomStage(BaseStage):
        def __init__(self):
            super().__init__(stage_number=1, stage_name="Processing", task_type="process_item")
        
        def create_tasks(self, context):
            tasks = []
            for i, item in enumerate(context.job_parameters['items']):
                task_params = self.calculate_task_parameters(context, i)
                task_params.update({'item': item})
                tasks.append(task_params)
            return tasks
        
        def validate_prerequisites(self, context):
            return 'items' in context.job_parameters

Author: Azure Geospatial ETL Team
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class StageStatus(Enum):
    """Stage status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StageExecutionContext:
    """Context information for stage execution"""
    job_id: str
    stage_number: int
    stage_name: str
    job_parameters: Dict[str, Any]
    previous_stage_results: Optional[Dict[str, Any]] = None
    task_count: int = 0
    completed_tasks: int = 0


class BaseStage(ABC):
    """
    Abstract base class for stage execution logic.
    
    Stages are sequential operations that form part of a job chain.
    Each stage can create multiple tasks that execute in parallel.
    """

    def __init__(self, stage_number: int, stage_name: str, task_type: str):
        self.stage_number = stage_number
        self.stage_name = stage_name
        self.task_type = task_type

    @abstractmethod
    def create_tasks(self, context: StageExecutionContext) -> List[Dict[str, Any]]:
        """
        Create tasks for this stage.
        
        Args:
            context: Stage execution context with job parameters and previous results
            
        Returns:
            List of task definitions to be executed in parallel
        """
        pass

    @abstractmethod
    def should_skip_stage(self, context: StageExecutionContext) -> bool:
        """
        Determine if this stage should be skipped based on context.
        
        Args:
            context: Stage execution context
            
        Returns:
            True if stage should be skipped, False otherwise
        """
        pass

    @abstractmethod
    def validate_prerequisites(self, context: StageExecutionContext) -> bool:
        """
        Validate that prerequisites for this stage are met.
        
        Args:
            context: Stage execution context
            
        Returns:
            True if prerequisites are met, False otherwise
        """
        pass

    def prepare_stage_execution(self, context: StageExecutionContext) -> StageExecutionContext:
        """
        Prepare the stage for execution.
        
        This method can modify the context before task creation.
        Base implementation returns context unchanged.
        """
        return context

    def calculate_task_parameters(self, context: StageExecutionContext, task_index: int) -> Dict[str, Any]:
        """
        Calculate parameters for a specific task within this stage.
        
        Args:
            context: Stage execution context
            task_index: Index of the task being created (0-based)
            
        Returns:
            Parameters dictionary for the task
        """
        base_params = {
            'job_id': context.job_id,
            'stage_number': context.stage_number,
            'stage_name': context.stage_name,
            'task_type': self.task_type,
            'task_index': task_index,
            'job_parameters': context.job_parameters
        }
        
        # Include previous stage results if available
        if context.previous_stage_results:
            base_params['previous_stage_results'] = context.previous_stage_results
            
        return base_params

    def generate_task_id(self, job_id: str, stage_number: int, task_index: int) -> str:
        """Generate unique task ID for this stage and task index"""
        return f"{job_id}_stage{stage_number}_task{task_index}"

    def is_stage_complete(self, completed_tasks: int, total_tasks: int) -> bool:
        """Check if all tasks in this stage are complete"""
        return completed_tasks >= total_tasks

    def aggregate_stage_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregate results from all tasks in this stage.
        
        Base implementation collects all task results.
        Concrete stages can override for custom aggregation.
        """
        return {
            'stage_number': self.stage_number,
            'stage_name': self.stage_name,
            'task_count': len(task_results),
            'task_results': task_results,
            'stage_status': StageStatus.COMPLETED.value
        }

    def handle_stage_failure(self, failed_tasks: List[Dict[str, Any]], 
                           successful_tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Handle stage failure when some tasks fail.
        
        Base implementation marks stage as failed.
        Concrete stages can override for custom failure handling.
        """
        return {
            'stage_number': self.stage_number,
            'stage_name': self.stage_name,
            'stage_status': StageStatus.FAILED.value,
            'failed_task_count': len(failed_tasks),
            'successful_task_count': len(successful_tasks),
            'failed_tasks': failed_tasks,
            'successful_tasks': successful_tasks
        }

    def __repr__(self):
        return f"<{self.__class__.__name__}(stage={self.stage_number}, name='{self.stage_name}', task_type='{self.task_type}')>"