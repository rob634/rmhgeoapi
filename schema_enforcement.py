"""
Schema enforcement system for hierarchical parameter validation.

This module provides strict schema validation with clear error messages
to enforce consistency across controllers, services, and repositories.
Follows the principle: Explicit errors over fallbacks.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Set, List, Optional, Type, Union
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SchemaViolationType(Enum):
    """Types of schema violations"""
    MISSING_REQUIRED = "MISSING_REQUIRED"
    INVALID_TYPE = "INVALID_TYPE"
    UNKNOWN_PARAMETER = "UNKNOWN_PARAMETER"
    INVALID_VALUE = "INVALID_VALUE"
    DEPRECATED_PARAMETER = "DEPRECATED_PARAMETER"


@dataclass
class SchemaViolation:
    """Represents a schema violation"""
    type: SchemaViolationType
    parameter: str
    expected: str
    actual: str
    message: str
    
    def __str__(self) -> str:
        return f"{self.type.value}: {self.parameter} - {self.message}"


class SchemaValidationError(Exception):
    """
    Raised when schema validation fails.
    
    Contains detailed information about all violations to help
    developers fix issues quickly.
    """
    
    def __init__(self, violations: List[SchemaViolation], context: str = ""):
        self.violations = violations
        self.context = context
        
        # Create detailed error message
        violation_details = "\n".join([
            f"  • {violation}" for violation in violations
        ])
        
        message = f"Schema validation failed{(' in ' + context) if context else ''}\n"
        message += f"Found {len(violations)} violation(s):\n{violation_details}\n\n"
        message += "🚨 FIX REQUIRED: Update your code to use the correct schema.\n"
        message += "See schema documentation or base class definitions."
        
        super().__init__(message)


class ParameterCategory(Enum):
    """Categories of parameters"""
    CORE = "CORE"              # Always required (job_type)  
    DDH = "DDH"                # Data Discovery Hub - required for silver layer ETL
    SYSTEM = "SYSTEM"          # System/operational parameters
    CUSTOM = "CUSTOM"          # Controller-specific parameters


@dataclass
class ParameterSchema:
    """Defines schema for a parameter"""
    name: str
    type: Type
    required: bool = True
    deprecated: bool = False
    deprecated_use_instead: Optional[str] = None
    description: str = ""
    allowed_values: Optional[Set[Any]] = None
    category: ParameterCategory = ParameterCategory.CUSTOM
    ddh_required_for: Optional[Set[str]] = None  # Job types that require DDH parameters
    
    def validate(self, value: Any) -> List[SchemaViolation]:
        """Validate a parameter value against this schema"""
        violations = []
        
        # Check if deprecated
        if self.deprecated:
            replacement = f" Use '{self.deprecated_use_instead}' instead." if self.deprecated_use_instead else ""
            violations.append(SchemaViolation(
                type=SchemaViolationType.DEPRECATED_PARAMETER,
                parameter=self.name,
                expected="non-deprecated parameter",
                actual=f"deprecated: {self.name}",
                message=f"Parameter '{self.name}' is deprecated.{replacement}"
            ))
        
        # Type checking
        if value is not None and not isinstance(value, self.type):
            violations.append(SchemaViolation(
                type=SchemaViolationType.INVALID_TYPE,
                parameter=self.name,
                expected=self.type.__name__,
                actual=type(value).__name__,
                message=f"Expected {self.type.__name__}, got {type(value).__name__}"
            ))
        
        # Value checking
        if self.allowed_values and value not in self.allowed_values:
            violations.append(SchemaViolation(
                type=SchemaViolationType.INVALID_VALUE,
                parameter=self.name,
                expected=f"one of {self.allowed_values}",
                actual=str(value),
                message=f"Value '{value}' not in allowed values: {self.allowed_values}"
            ))
            
        return violations


class SchemaDefinition:
    """Defines complete schema for a component"""
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.parameters: Dict[str, ParameterSchema] = {}
        
    def add_parameter(self, param: ParameterSchema) -> 'SchemaDefinition':
        """Add a parameter to this schema (fluent interface)"""
        self.parameters[param.name] = param
        return self
        
    def require(self, name: str, type_: Type, description: str = "", 
                allowed_values: Optional[Set[Any]] = None, 
                category: ParameterCategory = ParameterCategory.CORE) -> 'SchemaDefinition':
        """Add required parameter (fluent interface)"""
        return self.add_parameter(ParameterSchema(
            name=name, type=type_, required=True, description=description,
            allowed_values=allowed_values, category=category
        ))
        
    def optional(self, name: str, type_: Type, description: str = "",
                 allowed_values: Optional[Set[Any]] = None,
                 category: ParameterCategory = ParameterCategory.CUSTOM) -> 'SchemaDefinition':
        """Add optional parameter (fluent interface)"""
        return self.add_parameter(ParameterSchema(
            name=name, type=type_, required=False, description=description,
            allowed_values=allowed_values, category=category
        ))
        
    def ddh_parameter(self, name: str, type_: Type, description: str = "",
                      required_for_jobs: Optional[Set[str]] = None) -> 'SchemaDefinition':
        """Add DDH parameter (required for silver layer ETL operations)"""
        return self.add_parameter(ParameterSchema(
            name=name, type=type_, required=False, description=description,
            category=ParameterCategory.DDH, ddh_required_for=required_for_jobs or set()
        ))
        
    def deprecated(self, name: str, type_: Type, use_instead: str) -> 'SchemaDefinition':
        """Add deprecated parameter (fluent interface)"""
        return self.add_parameter(ParameterSchema(
            name=name, type=type_, required=False, deprecated=True,
            deprecated_use_instead=use_instead
        ))
    
    def validate(self, data: Dict[str, Any], strict: bool = True) -> List[SchemaViolation]:
        """
        Validate data against this schema with DDH-aware validation.
        
        Args:
            data: Data to validate
            strict: If True, unknown parameters cause violations
            
        Returns:
            List of violations (empty if valid)
        """
        violations = []
        provided_params = set(data.keys())
        schema_params = set(self.parameters.keys())
        
        # Get job type and system flag for DDH validation
        job_type = data.get('job_type', '')
        is_system_operation = data.get('system', False)
        
        # Check for missing required parameters (CORE category)
        required_params = {name for name, param in self.parameters.items() 
                          if param.required and param.category == ParameterCategory.CORE}
        missing_required = required_params - provided_params
        
        for param_name in missing_required:
            violations.append(SchemaViolation(
                type=SchemaViolationType.MISSING_REQUIRED,
                parameter=param_name,
                expected="required parameter",
                actual="missing",
                message=f"Required parameter '{param_name}' is missing"
            ))
        
        # Check for missing DDH parameters (conditional based on job type and system flag)
        if not is_system_operation:  # DDH parameters only required for non-system operations
            ddh_params = {name: param for name, param in self.parameters.items() 
                         if param.category == ParameterCategory.DDH}
            
            for param_name, param in ddh_params.items():
                param_required = (
                    param.ddh_required_for is None or  # Required for all jobs
                    job_type in param.ddh_required_for  # Required for specific job types
                )
                
                if param_required and param_name not in provided_params:
                    violations.append(SchemaViolation(
                        type=SchemaViolationType.MISSING_REQUIRED,
                        parameter=param_name,
                        expected="DDH parameter (required for silver layer ETL)",
                        actual="missing",
                        message=f"DDH parameter '{param_name}' is required for ETL operations. Use 'system': true to bypass DDH requirements."
                    ))
        
        # Check for unknown parameters (if strict)
        if strict:
            unknown_params = provided_params - schema_params
            for param_name in unknown_params:
                violations.append(SchemaViolation(
                    type=SchemaViolationType.UNKNOWN_PARAMETER,
                    parameter=param_name,
                    expected="known parameter",
                    actual=f"unknown: {param_name}",
                    message=f"Unknown parameter '{param_name}' not in schema"
                ))
        
        # Validate individual parameters
        for param_name, value in data.items():
            if param_name in self.parameters:
                param_violations = self.parameters[param_name].validate(value)
                violations.extend(param_violations)
                
        return violations
    
    def validate_or_raise(self, data: Dict[str, Any], context: str = "", strict: bool = True):
        """Validate and raise exception if violations found"""
        violations = self.validate(data, strict=strict)
        if violations:
            raise SchemaValidationError(violations, context or self.name)


class BaseSchemaEnforcer(ABC):
    """Base class for components that enforce schemas"""
    
    def __init__(self):
        self._schema: Optional[SchemaDefinition] = None
        
    @abstractmethod
    def define_schema(self) -> SchemaDefinition:
        """Define the schema for this component"""
        pass
    
    def get_schema(self) -> SchemaDefinition:
        """Get cached schema definition"""
        if self._schema is None:
            self._schema = self.define_schema()
        return self._schema
    
    def validate_parameters(self, data: Dict[str, Any], context: str = "", strict: bool = True):
        """Validate parameters and raise exception if invalid"""
        schema = self.get_schema()
        schema.validate_or_raise(data, context=context or self.__class__.__name__, strict=strict)


# Standard schemas for common components
def create_job_request_schema() -> SchemaDefinition:
    """Standard schema for job requests with DDH parameter categorization"""
    return SchemaDefinition("JobRequest", "Standard job request parameters") \
        .require("job_type", str, "Type of job to perform (hello_world, sync_container, etc.)", 
                category=ParameterCategory.CORE) \
        .ddh_parameter("dataset_id", str, 
                      "DDH Dataset identifier - required for silver layer ETL operations", 
                      required_for_jobs={"sync_container", "catalog_file", "cog_conversion"}) \
        .ddh_parameter("resource_id", str, 
                      "DDH Resource identifier - required for silver layer ETL operations",
                      required_for_jobs={"sync_container", "catalog_file", "cog_conversion"}) \
        .ddh_parameter("version_id", str, 
                      "DDH Version identifier - required for silver layer ETL operations",
                      required_for_jobs={"sync_container", "catalog_file", "cog_conversion"}) \
        .optional("system", bool, "System operation flag (bypasses DDH requirements)", 
                 category=ParameterCategory.SYSTEM) \
        .deprecated("operation_type", str, "job_type")


def create_task_data_schema() -> SchemaDefinition:
    """Standard schema for task data"""
    return SchemaDefinition("TaskData", "Standard task data structure") \
        .require("task_type", str, "Type of task to execute") \
        .require("dataset_id", str, "Dataset identifier") \
        .require("resource_id", str, "Resource identifier") \
        .optional("version_id", str, "Version identifier") \
        .optional("parent_job_id", str, "Parent job identifier") \
        .optional("priority", int, "Task priority (higher = more important)") \
        .deprecated("operation", str, "task_type") \
        .deprecated("operation_type", str, "task_type")


# Example usage for controllers
class StrictJobController(BaseSchemaEnforcer):
    """Example of controller with strict schema enforcement"""
    
    def define_schema(self) -> SchemaDefinition:
        return create_job_request_schema() \
            .optional("custom_param", str, "Controller-specific parameter")
    
    def process_job(self, request: Dict[str, Any]) -> Dict[str, Any]:
        # This will throw detailed SchemaValidationError if invalid
        self.validate_parameters(
            request, 
            context=f"{self.__class__.__name__}.process_job",
            strict=True
        )
        
        # Continue with processing...
        return {"status": "processed"}


# Example of correct vs deprecated parameter usage
class ParameterMigrationExample:
    """Examples showing correct parameter usage with DDH categorization"""
    
    @staticmethod
    def correct_system_operation():
        """✅ CORRECT: System operation (no DDH parameters required)"""
        return {
            "job_type": "hello_world",      # ✅ CORE: Always required
            "system": True                  # ✅ SYSTEM: Bypasses DDH requirements
            # No DDH parameters needed for system operations
        }
    
    @staticmethod
    def correct_etl_operation():
        """✅ CORRECT: ETL operation (DDH parameters required)"""
        return {
            "job_type": "sync_container",   # ✅ CORE: Always required
            "dataset_id": "rmhazuregeobronze",   # ✅ DDH: Required for silver layer ETL
            "resource_id": "geospatial_files",  # ✅ DDH: Required for silver layer ETL  
            "version_id": "v1.0",               # ✅ DDH: Required for silver layer ETL
            "system": False                     # Default: DDH validation applies
        }
    
    @staticmethod
    def system_operation_bypasses_ddh():
        """✅ CORRECT: System flag bypasses DDH requirements"""
        return {
            "job_type": "sync_container",   # ✅ CORE: Always required
            "system": True                  # ✅ SYSTEM: Bypasses DDH requirements
            # DDH parameters optional when system=True
        }
    
    @staticmethod
    def deprecated_job_request():
        """❌ DEPRECATED: operation_type is too vague"""
        return {
            "operation_type": "hello_world",  # ❌ Deprecated - unclear if job or task
            "dataset_id": "test", 
            "resource_id": "test_resource"
        }
    
    @staticmethod
    def correct_task_data():
        """✅ CORRECT: Use task_type (specific to task execution)"""
        return {
            "task_type": "hello_world",     # ✅ Primary field for tasks
            "dataset_id": "test",
            "resource_id": "test_resource"
        }


class DDHParameterGuide:
    """
    Guide to Data Discovery Hub (DDH) parameter usage.
    
    DDH Parameters (dataset_id, resource_id, version_id) are metadata fields
    required by the Data Discovery Hub for tracking ETL operations that 
    create new data in the silver layer (silver container or PostGIS silver).
    
    Parameter Categories:
    • CORE: Always required (job_type)
    • DDH: Required for silver layer ETL operations (dataset_id, resource_id, version_id)
    • SYSTEM: System/operational flags (system)
    • CUSTOM: Controller-specific parameters (n, message, etc.)
    
    DDH Parameter Requirements:
    • Required for: sync_container, catalog_file, cog_conversion (silver layer ETL)
    • Optional for: hello_world, database_health, list_collections (non-ETL operations)
    • Bypassed when: system=True (system operations bypass DDH requirements)
    
    Examples:
    
    ✅ Silver Layer ETL (DDH required):
    {
        "job_type": "sync_container",
        "dataset_id": "rmhazuregeobronze",  # DDH: Source dataset
        "resource_id": "geospatial_files",  # DDH: Resource being processed
        "version_id": "v1.0"                # DDH: Data version
    }
    
    ✅ System Operation (DDH bypassed):
    {
        "job_type": "sync_container",
        "system": True                      # Bypasses DDH requirements
    }
    
    ✅ Non-ETL Operation (DDH optional):
    {
        "job_type": "hello_world",
        "dataset_id": "test"                # Optional, for testing purposes
    }
    
    ❌ Silver Layer ETL without DDH:
    {
        "job_type": "sync_container"        # Missing required DDH parameters
        # Error: DDH parameters required for silver layer ETL operations
    }
    """
    
    @staticmethod
    def silver_layer_etl_jobs() -> Set[str]:
        """Job types that require DDH parameters for silver layer ETL"""
        return {"sync_container", "catalog_file", "cog_conversion", "vector_processing"}
    
    @staticmethod
    def system_jobs() -> Set[str]:
        """Job types that are typically system operations"""
        return {"hello_world", "database_health", "list_collections", "verify_stac_tables"}


# Schema validation decorators for convenience
def validate_schema(schema: SchemaDefinition, strict: bool = True):
    """Decorator to validate function parameters against schema"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Assume first argument after self is the data dict
            if len(args) > 1 and isinstance(args[1], dict):
                data = args[1]
                schema.validate_or_raise(data, context=f"{func.__name__}()", strict=strict)
            return func(*args, **kwargs)
        return wrapper
    return decorator