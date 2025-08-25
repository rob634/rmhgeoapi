"""
Decorators for service layer enforcement.

This module provides decorators to enforce patterns and requirements
on service methods, particularly the requirement that services must
be called within a task context.

Author: Azure Geospatial ETL Team
Version: 1.0.0
"""
import os
import functools
from typing import Callable, Any
from logger_setup import get_logger

logger = get_logger(__name__)


def requires_task(func: Callable) -> Callable:
    """
    Decorator to enforce that service methods must be called with a task context.
    
    This decorator checks for a task_id in the kwargs and raises an error
    if it's missing. Can be disabled via environment variable for testing
    or migration purposes.
    
    Environment Variables:
        ENABLE_TASK_ENFORCEMENT: Set to 'false' to disable enforcement
        
    Usage:
        @requires_task
        def process(self, task_id: str, **kwargs):
            # Method implementation
            
    Args:
        func: The function to decorate
        
    Returns:
        Decorated function that enforces task context
        
    Raises:
        ValueError: If task_id is not provided and enforcement is enabled
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Check if enforcement is disabled
        if os.getenv('ENABLE_TASK_ENFORCEMENT', 'true').lower() == 'false':
            logger.debug(f"Task enforcement disabled for {func.__name__}")
            return func(*args, **kwargs)
        
        # Check for task_id in kwargs
        task_id = kwargs.get('task_id')
        
        # Also check if first positional arg after self is task_id
        # (handles both kwargs and positional args)
        if not task_id and len(args) > 1:
            # args[0] is self, args[1] might be task_id
            potential_task_id = args[1]
            if isinstance(potential_task_id, str) and len(potential_task_id) > 0:
                # Looks like a task_id
                task_id = potential_task_id
        
        if not task_id:
            error_msg = (
                f"{func.__name__} requires a task_id. "
                "Services must be called through controllers that create tasks. "
                "Use a controller to create a job and task, or set "
                "ENABLE_TASK_ENFORCEMENT=false to disable this check."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.debug(f"Task {task_id} executing {func.__name__}")
        return func(*args, **kwargs)
    
    return wrapper


def with_retry(max_attempts: int = 3, backoff_seconds: int = 1):
    """
    Decorator to add retry logic to service methods.
    
    Retries the decorated function on failure with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts
        backoff_seconds: Initial backoff time in seconds
        
    Usage:
        @with_retry(max_attempts=3, backoff_seconds=2)
        def process(self, **kwargs):
            # Method that might fail transiently
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import time
            
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        wait_time = backoff_seconds * (2 ** attempt)
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            
            raise last_exception
        
        return wrapper
    return decorator


def log_execution(func: Callable) -> Callable:
    """
    Decorator to log method execution with timing.
    
    Logs entry, exit, and execution time for decorated methods.
    
    Usage:
        @log_execution
        def process(self, **kwargs):
            # Method to track
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from datetime import datetime
        
        start_time = datetime.utcnow()
        class_name = args[0].__class__.__name__ if args else "Unknown"
        
        logger.info(f"Starting {class_name}.{func.__name__}")
        
        try:
            result = func(*args, **kwargs)
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            logger.info(f"Completed {class_name}.{func.__name__} in {duration:.2f}s")
            return result
            
        except Exception as e:
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            logger.error(f"Failed {class_name}.{func.__name__} after {duration:.2f}s: {e}")
            raise
    
    return wrapper


def validate_parameters(*required_params: str):
    """
    Decorator to validate required parameters are present.
    
    Args:
        *required_params: Names of required parameters
        
    Usage:
        @validate_parameters('dataset_id', 'resource_id')
        def process(self, **kwargs):
            # Method requiring specific parameters
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            missing = []
            for param in required_params:
                if param not in kwargs or kwargs[param] is None:
                    missing.append(param)
            
            if missing:
                raise ValueError(f"Missing required parameters: {', '.join(missing)}")
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator