# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Centralized validation system providing strict type enforcement and data integrity
# SOURCE: No direct configuration - provides validation utilities and type enforcement patterns
# SCOPE: Global validation infrastructure for all system components and data operations
# VALIDATION: Pydantic v2 validation with C-style discipline and fail-fast error handling
# ============================================================================

"""
Schema Validation Layer - Job→Stage→Task Architecture Type Enforcement

Comprehensive validation system providing centralized type enforcement and data integrity
for the Azure Geospatial ETL Pipeline. Implements strict C-style validation discipline
with "validate early, validate often, fail fast" principles to ensure bulletproof
type safety across all system components.

Key Features:
- Centralized validation engine with consistent error handling
- Queue message validation for both job and task messages
- Storage record validation with automatic type coercion
- Status transition validation following state machine rules
- Parent-child relationship validation for job-task hierarchies
- Schema migration support for backward compatibility
- Validation middleware decorators for automatic enforcement
- Structured error reporting with detailed debugging information

Design Principles:
- ZERO tolerance for invalid data entering the system
- Fail fast with detailed error messages for debugging
- Automatic type coercion where safe and appropriate
- Structured error reporting for operational monitoring
- Schema evolution support for smooth migrations
- Comprehensive logging for validation audit trails

Validation Points:
The validator operates at critical system boundaries:
- Queue message parsing (job queue and task queue messages)
- Storage record creation and updates (JobRecord, TaskRecord)
- API request/response validation (HTTP endpoints)
- Inter-service data transfer (between controllers, services, repositories)
- State transitions (job status changes, task status changes)
- Relationship integrity (parent-child job-task relationships)

Architecture Integration:
This validation layer integrates with the Job→Stage→Task architecture by:
- Validating job creation parameters before stage orchestration
- Ensuring task parameters are valid before service layer execution
- Enforcing status transition rules throughout job lifecycle
- Maintaining parent-child integrity between jobs and tasks
- Supporting schema evolution without breaking existing workflows

Usage Examples:
    # Validate job record from storage
    job_record = SchemaValidator.validate_job_record(raw_data)
    
    # Validate task record with strict mode
    task_record = SchemaValidator.validate_task_record(task_data, strict=True)
    
    # Validate queue message with automatic type detection
    message = SchemaValidator.validate_queue_message(queue_data, 'job')
    
    # Check status transition validity
    is_valid = SchemaValidator.validate_status_transition(current_job, new_status)
    
    # Migrate legacy data to current schema
    migrated_job = SchemaEvolution.migrate_legacy_job(legacy_data)
    
    # Use validation middleware decorators
    @ValidationMiddleware.validate_input(JobRecord)
    def process_job(job_record):
        # Function receives validated JobRecord instance
        pass

Error Handling:
The validator provides comprehensive error handling:
- SchemaValidationError: Structured validation failure information
- Detailed field-level error messages with context
- Non-strict mode for graceful degradation scenarios
- Comprehensive logging for debugging and monitoring
- Clear error paths for operational alerting

Integration Points:
- schema_core.py: Uses Pydantic models for type definitions
- model_core.py: Validates against core data models
- repository_data.py: Storage layer validation
- trigger_*.py: HTTP endpoint request/response validation
- function_app.py: Queue message validation
- controller_*.py: Job parameter validation
- service_*.py: Business logic input/output validation

Author: Azure Geospatial ETL Team
"""

from typing import Union, Dict, Any, List, Optional, Type, TypeVar
import json
from datetime import datetime
from pydantic import ValidationError

from util_logger import LoggerFactory, ComponentType

from schema_core import (
    JobRecord, TaskRecord, JobQueueMessage, TaskQueueMessage,
    JobStatus, TaskStatus, SchemaValidationError
)

# Type variables for generic validation
T = TypeVar('T')

logger = LoggerFactory.get_logger(ComponentType.VALIDATOR, "SchemaValidator")


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
            if 'created_at' in data and isinstance(data['created_at'], str):
                data['created_at'] = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
            if 'updated_at' in data and isinstance(data['updated_at'], str):
                data['updated_at'] = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
                
            # Set defaults for required timestamp fields if missing
            now = datetime.utcnow()
            if 'created_at' not in data:
                data['created_at'] = now
            if 'updated_at' not in data:
                data['updated_at'] = now
                
            job_record = JobRecord(**data)
            logger.info(f"✅ Job record validated: {job_record.job_id[:16]}... type={job_record.job_type}")
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
        Validate task record with C-style strictness and comprehensive debugging
        
        Args:
            data: Raw task data dictionary  
            strict: If True, raises on any validation error
            
        Returns:
            Validated TaskRecord instance
            
        Raises:
            SchemaValidationError: If validation fails and strict=True
        """
        # 🚨 FORCED LOGGING: Using ERROR level to ensure visibility in Application Insights
        logger.error(f"🔧 VALIDATION START: TaskRecord with {len(data)} fields")
        logger.error(f"📋 Input data keys: {sorted(data.keys())}")
        logger.error(f"📊 Input data types: {[(k, type(v).__name__) for k, v in data.items()]}")
        
        # Additional context for Application Insights
        logger.error(f"🔍 RAW DATA DUMP: {data}")
        
        # Force immediate flush to Application Insights
        import logging
        logging.getLogger().handlers[0].flush() if logging.getLogger().handlers else None
        
        try:
            # Create a working copy to avoid modifying the original
            validation_data = data.copy()
            logger.debug(f"📝 Created validation copy with keys: {list(validation_data.keys())}")
            
            # ENHANCED DATETIME FIELD PROCESSING with detailed logging
            datetime_fields = ['created_at', 'updated_at', 'heartbeat']
            for field in datetime_fields:
                if field in validation_data:
                    field_value = validation_data[field]
                    logger.debug(f"⏰ Processing {field}: {field_value} (type: {type(field_value).__name__})")
                    
                    try:
                        if isinstance(field_value, str):
                            # Handle ISO format strings
                            processed_value = datetime.fromisoformat(field_value.replace('Z', '+00:00'))
                            validation_data[field] = processed_value
                            logger.debug(f"✅ Converted {field} from string to datetime: {processed_value}")
                        elif isinstance(field_value, datetime):
                            logger.debug(f"✅ {field} already datetime: {field_value}")
                        elif field_value is None:
                            logger.debug(f"⚪ {field} is None (allowed)")
                        else:
                            logger.warning(f"⚠️ Unexpected {field} type: {type(field_value).__name__} = {field_value}")
                    except Exception as dt_error:
                        logger.error(f"❌ Failed to process datetime field {field}: {dt_error}")
                        logger.error(f"🔍 Raw value: {repr(field_value)}")
                        raise ValueError(f"Invalid datetime format for {field}: {field_value}")
            
            # Set defaults for missing required timestamp fields
            now = datetime.utcnow()
            if 'created_at' not in validation_data or validation_data['created_at'] is None:
                validation_data['created_at'] = now
                logger.debug(f"🕐 Set default created_at: {now}")
            if 'updated_at' not in validation_data or validation_data['updated_at'] is None:
                validation_data['updated_at'] = now
                logger.debug(f"🕑 Set default updated_at: {now}")
            
            # DETAILED FIELD VALIDATION with comprehensive logging
            logger.debug(f"🎯 FINAL VALIDATION: Attempting TaskRecord(**data) with fields:")
            for key, value in validation_data.items():
                logger.debug(f"  📌 {key}: {type(value).__name__} = {repr(value)[:100]}{'...' if len(repr(value)) > 100 else ''}")
            
            # Attempt Pydantic model creation with enhanced error capture
            try:
                task_record = TaskRecord(**validation_data)
                logger.info(f"✅ TaskRecord validation SUCCESS: {task_record.task_id} (parent: {task_record.parent_job_id[:16]}...)")
                logger.debug(f"📊 Validated TaskRecord fields: {list(task_record.__dict__.keys())}")
                return task_record
                
            except ValidationError as pydantic_error:
                logger.error(f"❌ PYDANTIC VALIDATION ERROR in TaskRecord creation:")
                logger.error(f"🔍 Error count: {len(pydantic_error.errors())}")
                
                # 🚨 ENHANCED ERROR LOGGING: Show exact failing field and value
                for i, error in enumerate(pydantic_error.errors(), 1):
                    logger.error(f"  📍 Error {i}: {error}")
                    if 'loc' in error:
                        field_path = ' -> '.join(str(x) for x in error['loc'])
                        field_name = error['loc'][-1] if error['loc'] else 'unknown'
                        logger.error(f"     🔥 FAILING FIELD: {field_path}")
                        
                        # Show actual vs expected value
                        if field_name in validation_data:
                            actual_value = validation_data[field_name]
                            logger.error(f"     📊 ACTUAL VALUE: {repr(actual_value)} (type: {type(actual_value).__name__})")
                        else:
                            logger.error(f"     📊 FIELD MISSING from input data")
                            
                    if 'msg' in error:
                        logger.error(f"     💬 MESSAGE: {error['msg']}")
                    if 'type' in error:
                        logger.error(f"     🏷️ ERROR TYPE: {error['type']}")
                
                # Show expected schema for failing field (use module import to avoid UnboundLocalError)
                import schema_core
                if hasattr(schema_core.TaskRecord, '__fields__'):
                    logger.error(f"📋 TaskRecord schema fields: {list(schema_core.TaskRecord.__fields__.keys())}")
                elif hasattr(schema_core.TaskRecord, 'model_fields'):
                    logger.error(f"📋 TaskRecord schema fields: {list(schema_core.TaskRecord.model_fields.keys())}")
                        
                # Log the raw JSON error for debugging
                logger.error(f"📋 Full Pydantic error JSON: {pydantic_error.json()}")
                
                # Force immediate flush before raising
                logging.getLogger().handlers[0].flush() if logging.getLogger().handlers else None
                raise pydantic_error
                
        except ValidationError as e:
            error_msg = f"TaskRecord validation failed with {len(e.errors())} errors"
            logger.error(f"❌ {error_msg}")
            logger.error(f"🔍 Original data keys: {list(data.keys())}")
            logger.error(f"🔍 Error details: {e.json()}")
            
            if strict:
                logger.error(f"🚨 STRICT MODE: Raising SchemaValidationError")
                raise SchemaValidationError("TaskRecord", e.errors())
            else:
                logger.warning(f"⚠️ NON-STRICT MODE: Returning None for invalid task record")
                return None
                
        except Exception as unexpected_error:
            logger.error(f"❌ UNEXPECTED ERROR in TaskRecord validation: {type(unexpected_error).__name__}")
            logger.error(f"🔍 Error message: {str(unexpected_error)}")
            logger.error(f"📋 Input data: {data}")
            
            # Re-raise with context
            if strict:
                raise RuntimeError(f"TaskRecord validation failed: {unexpected_error}") from unexpected_error
            else:
                logger.warning(f"⚠️ NON-STRICT MODE: Returning None after unexpected error")
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
                logger.info(f"✅ Job queue message validated: {message.job_id[:16]}... type={message.job_type}")
                return message
                
            elif message_type == 'task':
                message = TaskQueueMessage(**data)
                logger.info(f"✅ Task queue message validated: {message.task_id} parent={message.job_id[:16]}...")
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
                    f"for job {current_record.job_id[:16]}..."
                )
                
        elif isinstance(current_record, TaskRecord):
            if not current_record.status.can_transition_to(new_status):
                raise ValueError(
                    f"Invalid task status transition: {current_record.status} → {new_status} "
                    f"for task {current_record.task_id}"
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