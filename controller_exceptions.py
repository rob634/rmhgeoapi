"""
Custom exceptions for controller layer.

This module defines controller-specific exceptions to provide clear
error handling and meaningful messages throughout the job orchestration
process.

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""


class ControllerException(Exception):
    """Base exception for all controller errors."""
    pass


class InvalidRequestError(ControllerException):
    """Raised when request validation fails."""
    
    def __init__(self, message: str, field: str = None, value = None):
        """
        Initialize validation error with details.
        
        Args:
            message: Error description
            field: Field that failed validation
            value: Invalid value provided
        """
        self.field = field
        self.value = value
        if field:
            message = f"Invalid {field}: {message}"
        super().__init__(message)


class TaskCreationError(ControllerException):
    """Raised when task creation fails."""
    
    def __init__(self, message: str, job_id: str = None):
        """
        Initialize task creation error.
        
        Args:
            message: Error description
            job_id: Related job ID
        """
        self.job_id = job_id
        if job_id:
            message = f"Failed to create tasks for job {job_id}: {message}"
        super().__init__(message)


class JobProcessingError(ControllerException):
    """Raised when job processing encounters an error."""
    
    def __init__(self, message: str, job_id: str = None, phase: str = None):
        """
        Initialize job processing error.
        
        Args:
            message: Error description
            job_id: Job that failed
            phase: Processing phase where error occurred
        """
        self.job_id = job_id
        self.phase = phase
        if job_id and phase:
            message = f"Job {job_id} failed at {phase}: {message}"
        elif job_id:
            message = f"Job {job_id} failed: {message}"
        super().__init__(message)


class TaskNotFoundError(ControllerException):
    """Raised when a required task cannot be found."""
    
    def __init__(self, task_id: str):
        """
        Initialize task not found error.
        
        Args:
            task_id: Missing task ID
        """
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")


class JobNotFoundError(ControllerException):
    """Raised when a required job cannot be found."""
    
    def __init__(self, job_id: str):
        """
        Initialize job not found error.
        
        Args:
            job_id: Missing job ID
        """
        self.job_id = job_id
        super().__init__(f"Job not found: {job_id}")


class ControllerNotFoundError(ControllerException):
    """Raised when no controller exists for an operation type."""
    
    def __init__(self, operation_type: str):
        """
        Initialize controller not found error.
        
        Args:
            operation_type: Operation with no controller
        """
        self.operation_type = operation_type
        super().__init__(f"No controller found for operation: {operation_type}")