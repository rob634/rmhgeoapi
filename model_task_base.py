# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Abstract task model base class for business logic execution and result handling
# SOURCE: No direct configuration - provides task execution patterns and failure recovery
# SCOPE: Task-specific business logic foundation for service and repository layer integration
# VALIDATION: Pydantic v2 task parameter validation with execution context constraints
# ============================================================================

"""
Base Task Model - Job→Stage→Task Architecture Execution

Abstract base class defining the task execution patterns for the Azure Geospatial ETL Pipeline.
Provides comprehensive business logic execution framework, parameter validation, result handling,
and failure recovery mechanisms that concrete task implementations customize for their specific
processing requirements within the Service and Repository layers.

Architecture Responsibility:
    This module defines the TASK LAYER within the Job→Stage→Task architecture:
    - Job Layer: Orchestrates multi-stage workflows with completion detection
    - Stage Layer: Coordinates parallel task execution within workflow phases  
    - Task Layer: THIS MODULE - Implements business logic for individual processing units
    - Repository Layer: Handles data persistence, storage operations, and queue management

Key Features:
- Abstract base class enforcing consistent task implementation patterns
- Service + Repository layer integration for business logic execution
- Comprehensive parameter validation with context-aware error handling
- Built-in retry mechanisms with exponential backoff for transient failures
- Task lifecycle management (creation, execution, completion, failure)
- Heartbeat system for long-running task monitoring and health tracking
- Result handling with structured success/failure response patterns
- Metrics extraction for performance monitoring and system analytics

Task Execution Responsibility:
    Tasks contain the actual work implementation - Service and Repository patterns:
    - File Processing: Parse, transform, validate geospatial data files
    - Database Operations: Query, insert, update PostgreSQL and PostGIS operations
    - API Calls: External service integration, webhook notifications
    - Data Transformation: Format conversion, coordinate system transformations
    - Storage Operations: Azure Blob operations, inventory management
    - Validation Logic: Schema validation, data integrity checks

Parallel Execution Model:
    Stage creates N tasks → Task 1 (Service + Repository logic)
                         → Task 2 (Service + Repository logic)
                         → Task n (Service + Repository logic)
                                 ↓ All complete independently
    "Last task turns out the lights" → Stage completion detection

Task Lifecycle Flow:
    1. CREATION: create_task_record() → Initial task record in storage
    2. QUEUING: create_task_queue_message() → Task queued for execution
    3. VALIDATION: validate_task_parameters() → Parameter integrity check
    4. PREPARATION: prepare_task_execution() → Setup execution context
    5. EXECUTION: execute() → Business logic implementation (ABSTRACT)
    6. SUCCESS: handle_task_success() → Result processing and storage
    7. FAILURE: handle_task_failure() → Error handling and retry logic

Retry and Recovery System:
    Task Execution → Exception → should_retry_on_failure()
                                        ↓ Yes
    Retry Queue ← calculate_retry_delay() ← Exponential backoff
                                        ↓ No
    Task Failure ← handle_task_failure() ← Final failure processing

Integration Points:
- Extended by concrete task implementations in service layer modules
- Uses TaskExecutionContext for parameter passing and execution state
- Integrates with queue systems for asynchronous parallel execution
- Connects to repository layer for data persistence and retrieval
- Provides metrics to monitoring systems for performance tracking
- Feeds results to stage layer for workflow progression

Abstract Methods (Must Implement):
- execute(): Core business logic implementation (Service + Repository work)
- validate_task_parameters(): Task-specific parameter validation

Concrete Methods (Ready to Use):
- create_task_record(): Standardized task record creation for storage
- handle_task_success(): Success result processing with metrics
- handle_task_failure(): Failure handling with retry logic
- update_heartbeat(): Long-running task health monitoring
- should_retry_on_failure(): Configurable retry decision logic

Usage Example:
    class GeospatialProcessingTask(BaseTask):
        def __init__(self):
            super().__init__("process_geotiff")
        
        def validate_task_parameters(self, context):
            return 'file_path' in context.parameters
        
        def execute(self, context):
            # Service layer: Business logic
            file_path = context.parameters['file_path']
            processed_data = self.process_geotiff(file_path)
            
            # Repository layer: Storage operations  
            result_location = self.store_processed_data(processed_data)
            
            return TaskResult(
                task_id=context.task_id,
                status=TaskStatus.COMPLETED,
                result={'output_location': result_location}
            )

Author: Azure Geospatial ETL Team
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