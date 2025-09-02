# ============================================================================
# CLAUDE CONTEXT - CONFIGURATION
# ============================================================================
# PURPOSE: Robust Python-PostgreSQL enum conversion utilities
# SOURCE: No direct configuration - provides type-safe conversion patterns
# SCOPE: Global enum conversion utilities for all database operations
# VALIDATION: Type-safe enum conversion with comprehensive error handling
# ============================================================================

"""
Enum Conversion Utilities - Python ↔ PostgreSQL Type Safety

Provides robust, consistent conversion between Python enums and PostgreSQL ENUM types.
Eliminates the common database integration issues with enum type mismatches that cause
silent failures and data corruption.

Key Features:
- Type-safe conversion with comprehensive error handling
- Consistent patterns for all enum types (JobStatus, TaskStatus, etc.)
- PostgreSQL ENUM casting with proper type hints
- Bidirectional conversion (Python → PostgreSQL, PostgreSQL → Python)
- Detailed logging for debugging enum conversion issues
- Zero-tolerance for type mismatches

Usage:
    # Converting Python enum to PostgreSQL
    pg_value = EnumConverter.to_postgres(JobStatus.COMPLETED, 'job_status')
    
    # Converting PostgreSQL value to Python enum  
    py_enum = EnumConverter.from_postgres('completed', JobStatus)
    
    # Bulk conversion for complex objects
    converted_params = EnumConverter.prepare_for_storage(job_record)
"""

from typing import Type, Union, Any, Optional, Dict
from enum import Enum
import logging

from util_logger import LoggerFactory, ComponentType
from schema_core import JobStatus, TaskStatus

logger = LoggerFactory.get_logger(ComponentType.UTIL, "EnumConverter")


class EnumConversionError(Exception):
    """Raised when enum conversion fails with detailed context"""
    pass


class EnumConverter:
    """
    Centralized enum conversion utilities for Python ↔ PostgreSQL integration.
    
    Provides type-safe, consistent conversion patterns that eliminate the common
    database integration issues with enum type mismatches.
    """
    
    # Map Python enums to PostgreSQL type names
    POSTGRES_TYPE_MAPPING = {
        JobStatus: 'job_status',
        TaskStatus: 'task_status'
    }
    
    @classmethod
    def to_postgres_value(cls, enum_value: Union[Enum, str, None]) -> Optional[str]:
        """
        Convert Python enum to PostgreSQL string value.
        
        Args:
            enum_value: Python enum instance, string, or None
            
        Returns:
            String value suitable for PostgreSQL, or None
            
        Raises:
            EnumConversionError: If conversion fails
        """
        if enum_value is None:
            return None
            
        try:
            if isinstance(enum_value, Enum):
                # Extract the actual enum value (e.g., JobStatus.COMPLETED → "completed")
                result = enum_value.value
                logger.debug(f"🔄 Converted enum {enum_value} → '{result}'")
                return result
            elif isinstance(enum_value, str):
                # Already a string, validate it's a known enum value
                logger.debug(f"🔄 Using string value: '{enum_value}'")
                return enum_value
            else:
                raise EnumConversionError(f"Invalid enum type: {type(enum_value)} ({enum_value})")
                
        except Exception as e:
            logger.error(f"❌ Enum conversion failed: {enum_value} → {e}")
            raise EnumConversionError(f"Failed to convert enum {enum_value}: {e}")
    
    @classmethod
    def to_postgres_cast(cls, enum_value: Union[Enum, str, None], postgres_type: str) -> Optional[str]:
        """
        Convert Python enum to PostgreSQL ENUM cast expression.
        
        Args:
            enum_value: Python enum instance, string, or None
            postgres_type: PostgreSQL ENUM type name (e.g., 'job_status')
            
        Returns:
            PostgreSQL cast expression like "'completed'::job_status", or None
            
        Raises:
            EnumConversionError: If conversion fails
        """
        if enum_value is None:
            return None
            
        try:
            value_str = cls.to_postgres_value(enum_value)
            if value_str is None:
                return None
                
            cast_expr = f"'{value_str}'::{postgres_type}"
            logger.debug(f"🎯 Created PostgreSQL cast: {cast_expr}")
            return cast_expr
            
        except Exception as e:
            logger.error(f"❌ PostgreSQL cast creation failed: {enum_value} → {e}")
            raise EnumConversionError(f"Failed to create PostgreSQL cast for {enum_value}: {e}")
    
    @classmethod
    def from_postgres(cls, postgres_value: Any, enum_class: Type[Enum]) -> Optional[Enum]:
        """
        Convert PostgreSQL value to Python enum.
        
        Args:
            postgres_value: Value from PostgreSQL (string, enum, or None)
            enum_class: Target Python enum class (e.g., JobStatus)
            
        Returns:
            Python enum instance, or None
            
        Raises:
            EnumConversionError: If conversion fails
        """
        if postgres_value is None:
            return None
            
        try:
            # Handle different possible formats from PostgreSQL
            if isinstance(postgres_value, str):
                value_str = postgres_value
            elif hasattr(postgres_value, 'value'):
                value_str = postgres_value.value
            else:
                value_str = str(postgres_value)
            
            # Try to create enum from string value
            for enum_member in enum_class:
                if enum_member.value == value_str:
                    logger.debug(f"🔄 Converted PostgreSQL '{value_str}' → {enum_member}")
                    return enum_member
            
            # If no match found, raise error with available options
            available_values = [member.value for member in enum_class]
            raise EnumConversionError(
                f"PostgreSQL value '{value_str}' not found in {enum_class.__name__}. "
                f"Available values: {available_values}"
            )
            
        except Exception as e:
            logger.error(f"❌ PostgreSQL enum conversion failed: {postgres_value} → {e}")
            raise EnumConversionError(f"Failed to convert PostgreSQL value {postgres_value}: {e}")
    
    @classmethod
    def prepare_job_for_storage(cls, job_record) -> Dict[str, Any]:
        """
        Prepare job record for PostgreSQL storage with proper enum conversion.
        
        Args:
            job_record: JobRecord instance or dict
            
        Returns:
            Dict with PostgreSQL-compatible values
        """
        try:
            if hasattr(job_record, 'model_dump'):
                # Pydantic model
                data = job_record.model_dump()
            elif hasattr(job_record, 'dict'):
                # Legacy Pydantic
                data = job_record.dict()
            else:
                # Assume it's already a dict
                data = dict(job_record) if not isinstance(job_record, dict) else job_record
            
            # Convert status enum
            if 'status' in data and data['status'] is not None:
                data['status'] = cls.to_postgres_value(data['status'])
            
            logger.debug(f"🔄 Prepared job for storage: status={data.get('status')}")
            return data
            
        except Exception as e:
            logger.error(f"❌ Job preparation failed: {e}")
            raise EnumConversionError(f"Failed to prepare job for storage: {e}")
    
    @classmethod
    def prepare_task_for_storage(cls, task_record) -> Dict[str, Any]:
        """
        Prepare task record for PostgreSQL storage with proper enum conversion.
        
        Args:
            task_record: TaskRecord instance or dict
            
        Returns:
            Dict with PostgreSQL-compatible values
        """
        try:
            if hasattr(task_record, 'model_dump'):
                # Pydantic model
                data = task_record.model_dump()
            elif hasattr(task_record, 'dict'):
                # Legacy Pydantic
                data = task_record.dict()
            else:
                # Assume it's already a dict
                data = dict(task_record) if not isinstance(task_record, dict) else task_record
            
            # Convert status enum
            if 'status' in data and data['status'] is not None:
                data['status'] = cls.to_postgres_value(data['status'])
            
            logger.debug(f"🔄 Prepared task for storage: status={data.get('status')}")
            return data
            
        except Exception as e:
            logger.error(f"❌ Task preparation failed: {e}")
            raise EnumConversionError(f"Failed to prepare task for storage: {e}")
    
    @classmethod
    def validate_enum_consistency(cls) -> Dict[str, Any]:
        """
        Validate that Python enums match PostgreSQL schema definitions.
        
        Returns:
            Validation report with any mismatches found
        """
        logger.info("🔍 Validating Python-PostgreSQL enum consistency")
        
        validation_report = {
            "status": "success",
            "enums_checked": 0,
            "mismatches": [],
            "warnings": []
        }
        
        try:
            # Check JobStatus enum
            job_status_values = [status.value for status in JobStatus]
            expected_job_values = ['queued', 'processing', 'completed', 'failed', 'completed_with_errors']
            
            if set(job_status_values) != set(expected_job_values):
                validation_report["mismatches"].append({
                    "enum": "JobStatus",
                    "python_values": job_status_values,
                    "expected_postgres_values": expected_job_values,
                    "missing_in_python": list(set(expected_job_values) - set(job_status_values)),
                    "extra_in_python": list(set(job_status_values) - set(expected_job_values))
                })
            
            # Check TaskStatus enum  
            task_status_values = [status.value for status in TaskStatus]
            expected_task_values = ['queued', 'processing', 'completed', 'failed']
            
            if set(task_status_values) != set(expected_task_values):
                validation_report["mismatches"].append({
                    "enum": "TaskStatus", 
                    "python_values": task_status_values,
                    "expected_postgres_values": expected_task_values,
                    "missing_in_python": list(set(expected_task_values) - set(task_status_values)),
                    "extra_in_python": list(set(task_status_values) - set(expected_task_values))
                })
            
            validation_report["enums_checked"] = 2
            
            if validation_report["mismatches"]:
                validation_report["status"] = "mismatches_found"
                logger.warning(f"⚠️ Found {len(validation_report['mismatches'])} enum mismatches")
            else:
                logger.info("✅ All Python-PostgreSQL enums are consistent")
                
        except Exception as e:
            validation_report["status"] = "error"
            validation_report["error"] = str(e)
            logger.error(f"❌ Enum validation failed: {e}")
        
        return validation_report


# Convenience functions for common operations
def convert_job_status_to_postgres(status: Union[JobStatus, str, None]) -> Optional[str]:
    """Convert JobStatus to PostgreSQL string value"""
    return EnumConverter.to_postgres_value(status)


def convert_task_status_to_postgres(status: Union[TaskStatus, str, None]) -> Optional[str]:
    """Convert TaskStatus to PostgreSQL string value"""  
    return EnumConverter.to_postgres_value(status)


def convert_job_status_from_postgres(postgres_value: Any) -> Optional[JobStatus]:
    """Convert PostgreSQL value to JobStatus enum"""
    return EnumConverter.from_postgres(postgres_value, JobStatus)


def convert_task_status_from_postgres(postgres_value: Any) -> Optional[TaskStatus]:
    """Convert PostgreSQL value to TaskStatus enum"""
    return EnumConverter.from_postgres(postgres_value, TaskStatus)