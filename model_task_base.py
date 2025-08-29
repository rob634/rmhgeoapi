"""
Base Task - Redesign Architecture

Defines the abstract base class for task execution logic.

TASK LAYER RESPONSIBILITY (Service + Repository):
- Contains the business logic (Service + Repository layers)
- Executes parallelizable operations within stages
- Does NOT handle orchestration (that's Controller layer)

Tasks are where the actual work happens:
- File processing, database operations, API calls
- Parallel execution within each stage
- "Last task turns out the lights" completion pattern
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
import time
from datetime import datetime

from model_core import (
    TaskStatus, TaskExecutionContext, TaskRecord, TaskQueueMessage, TaskResult
)


class BaseTask(ABC):
    """
    Abstract base class for task execution logic.
    
    SERVICE + REPOSITORY LAYER RESPONSIBILITY:
    - Contains actual business logic (file processing, DB ops, API calls)
    - Executes parallelizable operations within stages
    - Multiple tasks within a stage run concurrently
    - Implements "last task turns out the lights" completion detection
    
    The task layer is where Service and Repository patterns live.
    Controllers orchestrate, Tasks execute.
    """

    def __init__(self, task_type: str):
        self.task_type = task_type
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    # ========================================================================
    # ABSTRACT METHODS - Must be implemented by concrete tasks
    # ========================================================================

    @abstractmethod
    def execute(self, context: TaskExecutionContext) -> TaskResult:
        """
        Execute the task with the given context.
        
        This is where the business logic lives - Service and Repository layers.
        Examples: process files, query databases, call APIs, transform data.
        
        Args:
            context: Task execution context with all necessary parameters
            
        Returns:
            TaskResult with execution outcome and data
        """
        pass

    @abstractmethod
    def validate_task_parameters(self, context: TaskExecutionContext) -> bool:
        """
        Validate that task parameters are correct for execution.
        
        Args:
            context: Task execution context
            
        Returns:
            True if parameters are valid, False otherwise
        """
        pass

    def prepare_task_execution(self, context: TaskExecutionContext) -> TaskExecutionContext:
        """
        Prepare the task for execution.
        
        This method can modify the context before execution.
        Base implementation returns context unchanged.
        """
        return context

    def create_task_record(self, context: TaskExecutionContext) -> Dict[str, Any]:
        """Create the initial task record for storage"""
        return {
            'id': context.task_id,
            'job_id': context.job_id,
            'task_type': context.task_type,
            'stage': context.stage_number,
            'status': TaskStatus.QUEUED.value,
            'parameters': context.parameters,
            'created_at': None,  # Will be set by repository
            'updated_at': None,  # Will be set by repository
            'heartbeat': None,
            'retry_count': 0,
            'metadata': {
                'stage_name': context.stage_name,
                'task_index': context.task_index
            },
            'result_data': None,
            'error_details': None
        }

    def create_task_queue_message(self, context: TaskExecutionContext) -> Dict[str, Any]:
        """Create message for tasks queue"""
        return {
            'task_id': context.task_id,
            'job_id': context.job_id,
            'task_type': context.task_type,
            'stage_number': context.stage_number,
            'parameters': context.parameters
        }

    def handle_task_success(self, context: TaskExecutionContext, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle successful task completion.
        
        Prepares the result for storage and potential use by subsequent stages.
        """
        return {
            'task_id': context.task_id,
            'job_id': context.job_id,
            'stage_number': context.stage_number,
            'task_type': context.task_type,
            'status': TaskStatus.COMPLETED.value,
            'result': result,
            'completed_at': datetime.utcnow().isoformat(),
            'execution_time_seconds': result.get('execution_time_seconds', 0)
        }

    def handle_task_failure(self, context: TaskExecutionContext, error: Exception, 
                           retry_count: int = 0) -> Dict[str, Any]:
        """
        Handle task failure.
        
        Prepares the failure information for storage and retry logic.
        """
        return {
            'task_id': context.task_id,
            'job_id': context.job_id,
            'stage_number': context.stage_number,
            'task_type': context.task_type,
            'status': TaskStatus.FAILED.value,
            'error_type': error.__class__.__name__,
            'error_message': str(error),
            'retry_count': retry_count,
            'failed_at': datetime.utcnow().isoformat()
        }

    def update_heartbeat(self, task_id: str) -> Dict[str, Any]:
        """Update task heartbeat to indicate it's still processing"""
        return {
            'task_id': task_id,
            'heartbeat': datetime.utcnow().isoformat(),
            'status': TaskStatus.PROCESSING.value
        }

    def should_retry_on_failure(self, error: Exception, retry_count: int, max_retries: int = 3) -> bool:
        """
        Determine if task should be retried on failure.
        
        Base implementation allows retries for transient errors.
        Concrete tasks can override for custom retry logic.
        """
        if retry_count >= max_retries:
            return False
        
        # List of retryable error types
        retryable_errors = (
            ConnectionError,
            TimeoutError,
            # Add more retryable error types as needed
        )
        
        return isinstance(error, retryable_errors)

    def calculate_retry_delay(self, retry_count: int) -> int:
        """Calculate retry delay in seconds using exponential backoff"""
        base_delay = 30  # 30 seconds base delay
        return min(base_delay * (2 ** retry_count), 300)  # Max 5 minutes

    def extract_task_metrics(self, context: TaskExecutionContext, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract metrics from task execution for monitoring.
        
        Base implementation extracts basic metrics.
        Concrete tasks can override for custom metrics.
        """
        return {
            'task_type': context.task_type,
            'stage_number': context.stage_number,
            'execution_time_seconds': result.get('execution_time_seconds', 0),
            'memory_usage_mb': result.get('memory_usage_mb', 0),
            'processed_items': result.get('processed_items', 0),
            'success': result.get('success', True)
        }

    def __repr__(self):
        return f"<{self.__class__.__name__}(task_type='{self.task_type}')>"