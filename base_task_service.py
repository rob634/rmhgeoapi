"""
Base task service extending BaseProcessingService.

This module provides the abstract base class for task-level services,
enforcing that all processing must happen within a task context.

Key Features:
    - Extends BaseProcessingService for compatibility
    - Adds task-specific validation and execution flow
    - Enforces task context for all operations
    - Provides standard task execution pattern

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime

from services import BaseProcessingService
from repositories import TaskRepository
from logger_setup import get_logger

logger = get_logger(__name__)


class BaseTaskService(BaseProcessingService):
    """
    Abstract base class for all task-level services.
    
    Extends BaseProcessingService to add task-specific behavior while
    maintaining compatibility with existing service infrastructure.
    
    All task services must:
        - Be called with a task_id
        - Validate inputs before processing
        - Validate outputs after processing
        - Update task status appropriately
        
    Subclasses must implement:
        - validate_inputs(): Check if task can be processed
        - execute(): Perform the actual work
        - validate_outputs(): Verify results are correct
    """
    
    def __init__(self):
        """Initialize task service with repository."""
        super().__init__()
        self.task_repo = TaskRepository()
        self.logger = get_logger(self.__class__.__name__)
    
    @abstractmethod
    def validate_inputs(self, **kwargs) -> bool:
        """
        Validate that task inputs are correct and processable.
        
        Args:
            **kwargs: Task parameters
            
        Returns:
            bool: True if inputs are valid
            
        Raises:
            ValueError: If inputs are invalid
        """
        pass
    
    @abstractmethod
    def execute(self, task_id: str, **kwargs) -> Dict[str, Any]:
        """
        Execute the actual task processing.
        
        This is where the real work happens. Must be atomic and idempotent.
        
        Args:
            task_id: Task identifier
            **kwargs: Task parameters
            
        Returns:
            Dict: Task execution results
        """
        pass
    
    @abstractmethod
    def validate_outputs(self, outputs: Dict[str, Any]) -> bool:
        """
        Validate task outputs before marking complete.
        
        Args:
            outputs: Results from execute()
            
        Returns:
            bool: True if outputs are valid
            
        Raises:
            ValueError: If outputs are invalid
        """
        pass
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str, **kwargs) -> Dict:
        """
        Process method for compatibility with BaseProcessingService.
        
        This adapts the BaseProcessingService interface to our task-based
        pattern. It expects task_id to be in kwargs.
        
        Args:
            job_id: Job identifier (may be same as task_id for single-task jobs)
            dataset_id: Dataset/container name
            resource_id: Resource identifier
            version_id: Version identifier
            operation_type: Operation type
            **kwargs: Additional parameters including task_id
            
        Returns:
            Dict: Processing results
            
        Raises:
            ValueError: If task_id not provided
        """
        # Extract task_id from kwargs
        task_id = kwargs.get('task_id')
        if not task_id:
            # For backward compatibility, use job_id as task_id
            task_id = job_id
            self.logger.warning(f"No task_id provided, using job_id as task_id: {task_id}")
        
        # Build full parameter set
        params = {
            'job_id': job_id,
            'dataset_id': dataset_id,
            'resource_id': resource_id,
            'version_id': version_id,
            'operation_type': operation_type,
            **kwargs
        }
        
        # Execute using task pattern
        return self.execute_task(task_id, **params)
    
    def execute_task(self, task_id: str, **kwargs) -> Dict[str, Any]:
        """
        Standard task execution flow.
        
        Implements the standard pattern:
        1. Validate inputs
        2. Update status to processing
        3. Execute task
        4. Validate outputs
        5. Update status to completed/failed
        
        Args:
            task_id: Task identifier
            **kwargs: Task parameters
            
        Returns:
            Dict: Task results
            
        Raises:
            Exception: If task execution fails
        """
        start_time = datetime.utcnow()
        
        try:
            # Step 1: Get task from repository
            task = self.task_repo.get_task(task_id)
            if not task:
                self.logger.warning(f"Task not found in repository: {task_id}")
                # Continue anyway for backward compatibility
            
            # Step 2: Validate inputs
            self.logger.info(f"Validating inputs for task {task_id}")
            if not self.validate_inputs(**kwargs):
                raise ValueError(f"Input validation failed for task {task_id}")
            
            # Step 3: Update status to processing
            self.task_repo.update_task_status(task_id, 'processing', {
                'started_at': start_time.isoformat()
            })
            
            # Step 4: Execute the task
            self.logger.info(f"Executing task {task_id}")
            result = self.execute(task_id, **kwargs)
            
            # Step 5: Validate outputs
            self.logger.info(f"Validating outputs for task {task_id}")
            if not self.validate_outputs(result):
                raise ValueError(f"Output validation failed for task {task_id}")
            
            # Step 6: Update status to completed
            end_time = datetime.utcnow()
            duration_seconds = (end_time - start_time).total_seconds()
            
            self.task_repo.update_task_status(task_id, 'completed', {
                'completed_at': end_time.isoformat(),
                'duration_seconds': duration_seconds,
                'result': result
            })
            
            self.logger.info(f"Task {task_id} completed successfully in {duration_seconds}s")
            return result
            
        except Exception as e:
            # Update status to failed
            self.logger.error(f"Task {task_id} failed: {e}")
            
            end_time = datetime.utcnow()
            self.task_repo.update_task_status(task_id, 'failed', {
                'failed_at': end_time.isoformat(),
                'error': str(e),
                'error_type': type(e).__name__
            })
            
            # Re-raise the exception
            raise
    
    def get_supported_operations(self):
        """
        Default implementation returns empty list.
        
        Subclasses should override if they support specific operations.
        """
        return []