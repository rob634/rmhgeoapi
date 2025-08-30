"""
SCHEMA VALIDATION LAYER - Centralized Type Enforcement

This module provides centralized validation for all data entering the system.
C-style discipline: "Validate early, validate often, fail fast."

Design Principles:
1. ZERO tolerance for invalid data
2. Fail fast with detailed error messages  
3. Automatic type coercion where safe
4. Structured error reporting for debugging
5. Schema evolution support for migrations

Validation Points:
- Queue message parsing (both job and task queues)
- Storage record creation/updates  
- API request/response validation
- Inter-service data transfer

Author: Strong Typing Discipline Team  
Version: 1.0.0 - Foundation implementation
"""

from typing import Union, Dict, Any, List, Optional, Type, TypeVar
import json
import logging
from datetime import datetime
from pydantic import ValidationError

from schema_core import (
    JobRecord, TaskRecord, JobQueueMessage, TaskQueueMessage,
    JobStatus, TaskStatus, SchemaValidationError
)

# Type variables for generic validation
T = TypeVar('T')

logger = logging.getLogger(__name__)


class SchemaValidator:
    """
    CENTRALIZED VALIDATION ENGINE
    
    All data entering the system MUST pass through this validator.
    Provides consistent error handling and logging across all components.
    """
    
    @staticmethod
    def validate_job_record(data: Dict[str, Any], strict: bool = True) -> JobRecord:
        """
        Validate job record with C-style strictness
        
        Args:
            data: Raw job data dictionary
            strict: If True, raises on any validation error
            
        Returns:
            Validated JobRecord instance
            
        Raises:
            SchemaValidationError: If validation fails and strict=True
        """
        try:
            logger.debug(f"Validating job record with keys: {list(data.keys())}")
            
            # Ensure datetime fields are properly formatted
            if 'createdAt' in data and isinstance(data['createdAt'], str):
                data['createdAt'] = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00'))
            if 'updatedAt' in data and isinstance(data['updatedAt'], str):
                data['updatedAt'] = datetime.fromisoformat(data['updatedAt'].replace('Z', '+00:00'))
                
            # Set defaults for required timestamp fields if missing
            now = datetime.utcnow()
            if 'createdAt' not in data:
                data['createdAt'] = now
            if 'updatedAt' not in data:
                data['updatedAt'] = now
                
            job_record = JobRecord(**data)
            logger.info(f"✅ Job record validated: {job_record.jobId[:16]}... type={job_record.jobType}")
            return job_record
            
        except ValidationError as e:
            error_msg = f"Job record validation failed: {e.json()}"
            logger.error(error_msg)
            
            if strict:
                raise SchemaValidationError("JobRecord", e.errors())
            else:
                logger.warning("Non-strict mode: returning None for invalid job record")
                return None
    
    @staticmethod 
    def validate_task_record(data: Dict[str, Any], strict: bool = True) -> TaskRecord:
        """
        Validate task record with C-style strictness
        
        Args:
            data: Raw task data dictionary  
            strict: If True, raises on any validation error
            
        Returns:
            Validated TaskRecord instance
            
        Raises:
            SchemaValidationError: If validation fails and strict=True
        """
        try:
            logger.debug(f"Validating task record with keys: {list(data.keys())}")
            
            # Ensure datetime fields are properly formatted
            if 'createdAt' in data and isinstance(data['createdAt'], str):
                data['createdAt'] = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00'))
            if 'updatedAt' in data and isinstance(data['updatedAt'], str):  
                data['updatedAt'] = datetime.fromisoformat(data['updatedAt'].replace('Z', '+00:00'))
            if 'heartbeat' in data and isinstance(data['heartbeat'], str):
                data['heartbeat'] = datetime.fromisoformat(data['heartbeat'].replace('Z', '+00:00'))
                
            # Set defaults for required timestamp fields if missing
            now = datetime.utcnow()
            if 'createdAt' not in data:
                data['createdAt'] = now
            if 'updatedAt' not in data:
                data['updatedAt'] = now
                
            task_record = TaskRecord(**data)
            logger.info(f"✅ Task record validated: {task_record.taskId} parent={task_record.parentJobId[:16]}...")
            return task_record
            
        except ValidationError as e:
            error_msg = f"Task record validation failed: {e.json()}"
            logger.error(error_msg)
            
            if strict:
                raise SchemaValidationError("TaskRecord", e.errors())
            else:
                logger.warning("Non-strict mode: returning None for invalid task record")
                return None
    
    @staticmethod
    def validate_queue_message(
        data: Union[Dict[str, Any], str], 
        message_type: str, 
        strict: bool = True
    ) -> Union[JobQueueMessage, TaskQueueMessage]:
        """
        Validate queue messages with automatic JSON parsing and type detection
        
        Args:
            data: Raw message data (dict or JSON string)
            message_type: 'job' or 'task' 
            strict: If True, raises on any validation error
            
        Returns:
            Validated queue message instance
            
        Raises:
            SchemaValidationError: If validation fails and strict=True
        """
        try:
            # Handle JSON string input
            if isinstance(data, str):
                logger.debug("Parsing JSON string queue message")
                try:
                    data = json.loads(data)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in queue message: {e}")
            
            logger.debug(f"Validating {message_type} queue message with keys: {list(data.keys())}")
            
            if message_type == 'job':
                message = JobQueueMessage(**data)
                logger.info(f"✅ Job queue message validated: {message.jobId[:16]}... type={message.jobType}")
                return message
                
            elif message_type == 'task':
                message = TaskQueueMessage(**data)
                logger.info(f"✅ Task queue message validated: {message.taskId} parent={message.parentJobId[:16]}...")
                return message
                
            else:
                raise ValueError(f"Unknown message type: {message_type}. Must be 'job' or 'task'")
                
        except ValidationError as e:
            error_msg = f"{message_type.capitalize()} queue message validation failed: {e.json()}"
            logger.error(error_msg)
            
            if strict:
                raise SchemaValidationError(f"{message_type.capitalize()}QueueMessage", e.errors())
            else:
                logger.warning("Non-strict mode: returning None for invalid queue message")
                return None
    
    @staticmethod
    def validate_status_transition(
        current_record: Union[JobRecord, TaskRecord], 
        new_status: Union[JobStatus, TaskStatus]
    ) -> bool:
        """
        Validate that status transition is legal according to state machine rules
        
        Args:
            current_record: Current job or task record
            new_status: Proposed new status
            
        Returns:
            True if transition is valid, False otherwise
            
        Raises:
            ValueError: If transition is invalid and would corrupt state
        """
        if isinstance(current_record, JobRecord):
            if not current_record.status.can_transition_to(new_status):
                raise ValueError(
                    f"Invalid job status transition: {current_record.status} → {new_status} "
                    f"for job {current_record.jobId[:16]}..."
                )
                
        elif isinstance(current_record, TaskRecord):
            if not current_record.status.can_transition_to(new_status):
                raise ValueError(
                    f"Invalid task status transition: {current_record.status} → {new_status} "
                    f"for task {current_record.taskId}"
                )
                
        else:
            raise TypeError(f"Expected JobRecord or TaskRecord, got {type(current_record)}")
        
        logger.debug(f"✅ Status transition validated: {current_record.status} → {new_status}")
        return True
    
    @staticmethod
    def validate_parent_child_relationship(job_record: JobRecord, task_record: TaskRecord) -> bool:
        """
        Validate that task properly belongs to job (foreign key relationship)
        
        Args:
            job_record: Parent job record
            task_record: Child task record  
            
        Returns:
            True if relationship is valid
            
        Raises:
            ValueError: If relationship is invalid
        """
        if task_record.parent_job_id != job_record.job_id:
            raise ValueError(
                f"Task parent_job_id mismatch: task.parent_job_id={task_record.parent_job_id} "
                f"but job.job_id={job_record.job_id}"
            )
        
        # Validate that task ID contains job ID (structural consistency)
        if not task_record.task_id.startswith(job_record.job_id):
            raise ValueError(
                f"Task ID must start with job ID: task_id={task_record.task_id} "
                f"but job_id={job_record.job_id}"
            )
        
        # Validate stage consistency
        if task_record.stage > job_record.total_stages:
            raise ValueError(
                f"Task stage ({task_record.stage}) exceeds job total_stages ({job_record.total_stages})"
            )
        
        logger.debug(f"✅ Parent-child relationship validated: job={job_record.job_id[:16]}... task={task_record.task_id}")
        return True


class SchemaEvolution:
    """
    SCHEMA MIGRATION AND BACKWARD COMPATIBILITY
    
    Handles evolution of schemas over time while maintaining strict validation.
    """
    
    @staticmethod
    def migrate_legacy_job(legacy_data: Dict[str, Any]) -> JobRecord:
        """
        Migrate legacy job data to current schema format
        
        Args:
            legacy_data: Job data in legacy format
            
        Returns:
            JobRecord in current schema format
        """
        logger.info("Migrating legacy job data to current schema")
        
        # Handle common legacy field mappings
        migrated_data = {}
        
        # Map legacy field names to current schema
        field_mappings = {
            'job_id': 'jobId',
            'job_type': 'jobType',  # Legacy field name
            'job_type': 'jobType',        # Current field name
            'created_at': 'createdAt',
            'updated_at': 'updatedAt',
            'stage_results': 'stageResults',
            'result_data': 'resultData',  
            'error_details': 'errorDetails',
            'total_stages': 'totalStages'
        }
        
        for legacy_key, current_key in field_mappings.items():
            if legacy_key in legacy_data:
                migrated_data[current_key] = legacy_data[legacy_key]
        
        # Copy all other fields directly
        for key, value in legacy_data.items():
            if key not in field_mappings:
                migrated_data[key] = value
        
        # Validate and return migrated record
        return SchemaValidator.validate_job_record(migrated_data, strict=True)
    
    @staticmethod  
    def migrate_legacy_task(legacy_data: Dict[str, Any]) -> TaskRecord:
        """
        Migrate legacy task data to current schema format
        
        Args:
            legacy_data: Task data in legacy format
            
        Returns:
            TaskRecord in current schema format
        """
        logger.info("Migrating legacy task data to current schema")
        
        # Handle common legacy field mappings
        migrated_data = {}
        
        field_mappings = {
            'task_id': 'taskId',
            'parent_job_id': 'parentJobId',
            'job_type': 'taskType',  # Legacy task type field
            'task_type': 'taskType',       # Current task type field
            'stage_number': 'stage',       # Legacy stage field
            'task_index': 'taskIndex',
            'created_at': 'createdAt',
            'updated_at': 'updatedAt',
            'result_data': 'resultData',
            'error_details': 'errorDetails',
            'retry_count': 'retryCount'
        }
        
        for legacy_key, current_key in field_mappings.items():
            if legacy_key in legacy_data:
                migrated_data[current_key] = legacy_data[legacy_key]
        
        # Handle task_data JSON blob (common in legacy systems)
        if 'task_data' in legacy_data and isinstance(legacy_data['task_data'], str):
            try:
                task_data_json = json.loads(legacy_data['task_data'])
                if 'parameters' not in migrated_data:
                    migrated_data['parameters'] = task_data_json
            except json.JSONDecodeError:
                logger.warning("Failed to parse legacy task_data JSON")
        
        # Copy remaining fields
        for key, value in legacy_data.items():
            if key not in field_mappings and key != 'task_data':
                migrated_data[key] = value
        
        # Validate and return migrated record
        return SchemaValidator.validate_task_record(migrated_data, strict=True)


class ValidationMiddleware:
    """
    MIDDLEWARE FOR AUTOMATIC VALIDATION
    
    Decorators and context managers for enforcing validation at function boundaries.
    """
    
    @staticmethod
    def validate_input(schema_class: Type[T]):
        """
        Decorator to validate function input parameters
        
        Args:
            schema_class: Pydantic model class to validate against
            
        Returns:
            Decorator function
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                try:
                    # Validate first argument if it's a dict
                    if args and isinstance(args[0], dict):
                        validated_data = schema_class(**args[0])
                        args = (validated_data,) + args[1:]
                    
                    return func(*args, **kwargs)
                    
                except ValidationError as e:
                    logger.error(f"Input validation failed for {func.__name__}: {e.json()}")
                    raise SchemaValidationError(schema_class.__name__, e.errors())
            
            return wrapper
        return decorator
    
    @staticmethod  
    def validate_output(schema_class: Type[T]):
        """
        Decorator to validate function output
        
        Args:
            schema_class: Pydantic model class to validate against
            
        Returns:
            Decorator function
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                
                try:
                    if isinstance(result, dict):
                        validated_result = schema_class(**result)
                        return validated_result
                    
                    return result
                    
                except ValidationError as e:
                    logger.error(f"Output validation failed for {func.__name__}: {e.json()}")
                    raise SchemaValidationError(schema_class.__name__, e.errors())
            
            return wrapper
        return decorator


# Export public validation interface
__all__ = [
    'SchemaValidator',
    'SchemaEvolution', 
    'ValidationMiddleware',
    'SchemaValidationError'
]