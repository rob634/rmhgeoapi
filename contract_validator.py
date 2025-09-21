# ============================================================================
# CLAUDE CONTEXT - UTILITY
# ============================================================================
# PURPOSE: Runtime type contract enforcement decorator for boundary methods ensuring fail-fast behavior
# EXPORTS: enforce_contract decorator for automatic type validation
# INTERFACES: Decorator pattern for method validation
# PYDANTIC_MODELS: None (works with any types including Pydantic models)
# DEPENDENCIES: functools, typing, inspect, logging
# SOURCE: Python runtime type information
# SCOPE: Application-wide boundary validation
# VALIDATION: isinstance checks with detailed error messages
# PATTERNS: Decorator pattern, Fail-fast principle
# ENTRY_POINTS: @enforce_contract(params={...}, returns=Type)
# INDEX: enforce_contract:65, validate_params:150, validate_return:200
# ============================================================================

"""
Contract Validator - Runtime Type Enforcement

This module provides a decorator for enforcing type contracts at method boundaries,
ensuring that methods receive and return the expected types. This is critical for
maintaining the fail-fast principle and catching contract violations immediately
at boundaries rather than deep in business logic.

Key Features:
- Parameter type validation before method execution
- Return type validation after method execution
- Clear error messages indicating exact contract violations
- Support for Union types and None values
- Minimal performance overhead
- Can be disabled via environment variable for production

Usage:
    @enforce_contract(
        params={'job_record': JobRecord, 'stage': int},
        returns=Dict[str, Any]
    )
    def process_job_stage(self, job_record, stage):
        # Method implementation
        return results

Author: Robert and Geospatial Claude Legion
Date: 20 September 2025
"""

import os
import inspect
import logging
from functools import wraps
from typing import Type, Any, Dict, Optional, Union, get_origin, get_args

# Logger setup
logger = logging.getLogger(__name__)

# Environment variable to disable contract checking in production
CONTRACT_ENFORCEMENT_ENABLED = os.getenv('CONTRACT_ENFORCEMENT_ENABLED', 'true').lower() == 'true'


def enforce_contract(
    params: Optional[Dict[str, Type]] = None,
    returns: Optional[Type] = None
):
    """
    Decorator to enforce type contracts on method parameters and return values.

    This decorator validates that:
    1. Input parameters match expected types
    2. Return values match expected type
    3. Contract violations fail immediately with clear error messages

    Args:
        params: Dictionary mapping parameter names to expected types
                e.g., {'job_record': JobRecord, 'stage': int}
        returns: Expected return type or None
                 e.g., TaskRecord or Union[TaskRecord, None]

    Returns:
        Decorated function with contract enforcement

    Example:
        @enforce_contract(
            params={'task_def': TaskDefinition},
            returns=TaskRecord
        )
        def create_task(self, task_def):
            return task_def.to_task_record()

    Raises:
        TypeError: When parameters don't match expected types
        TypeError: When return value doesn't match expected type
    """
    def decorator(func):
        # If contract enforcement is disabled, return function unchanged
        if not CONTRACT_ENFORCEMENT_ENABLED:
            return func

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get function name for error messages
            func_name = f"{func.__module__}.{func.__qualname__}" if hasattr(func, '__qualname__') else func.__name__

            # VALIDATE INPUT PARAMETERS
            if params:
                try:
                    _validate_params(func, args, kwargs, params, func_name)
                except Exception as e:
                    logger.error(f"CONTRACT VIOLATION in {func_name}: {e}")
                    raise

            # EXECUTE FUNCTION
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                # Don't mask actual function errors
                raise

            # VALIDATE RETURN VALUE
            if returns is not None:
                try:
                    _validate_return(result, returns, func_name)
                except Exception as e:
                    logger.error(f"CONTRACT VIOLATION in {func_name}: {e}")
                    raise

            return result

        # Store contract info on wrapper for introspection
        wrapper._contract_params = params
        wrapper._contract_returns = returns

        return wrapper
    return decorator


def _validate_params(func, args, kwargs, expected_params, func_name):
    """
    Validate function parameters against expected types.

    Args:
        func: Original function
        args: Positional arguments
        kwargs: Keyword arguments
        expected_params: Dictionary of parameter names to types
        func_name: Function name for error messages

    Raises:
        TypeError: When parameter type doesn't match expectation
    """
    # Get function signature
    sig = inspect.signature(func)

    # Bind arguments to parameters
    try:
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
    except TypeError as e:
        # Let Python's normal parameter checking happen
        raise

    # Check each expected parameter
    for param_name, expected_type in expected_params.items():
        if param_name not in bound.arguments:
            # Parameter not provided (might be optional)
            continue

        value = bound.arguments[param_name]

        # Handle None values
        if value is None:
            # Check if None is allowed
            if not _is_none_allowed(expected_type):
                raise TypeError(
                    f"{func_name}() parameter '{param_name}' cannot be None. "
                    f"Expected {_format_type(expected_type)}."
                )
            continue

        # Validate type
        if not _check_type(value, expected_type):
            raise TypeError(
                f"{func_name}() parameter '{param_name}' expected {_format_type(expected_type)}, "
                f"got {type(value).__name__}. "
                f"This is a contract violation - check the calling code."
            )


def _validate_return(value, expected_type, func_name):
    """
    Validate function return value against expected type.

    Args:
        value: Return value from function
        expected_type: Expected type
        func_name: Function name for error messages

    Raises:
        TypeError: When return type doesn't match expectation
    """
    # Handle None values
    if value is None:
        if not _is_none_allowed(expected_type):
            raise TypeError(
                f"{func_name}() should return {_format_type(expected_type)}, "
                f"returned None. "
                f"This is a contract violation - method must return proper type."
            )
        return

    # Validate type
    if not _check_type(value, expected_type):
        raise TypeError(
            f"{func_name}() should return {_format_type(expected_type)}, "
            f"returned {type(value).__name__}. "
            f"This is a contract violation - check return statement."
        )


def _check_type(value: Any, expected_type: Type) -> bool:
    """
    Check if a value matches the expected type.

    Handles Union types, Optional types, and generic types.

    Args:
        value: Value to check
        expected_type: Expected type (can be Union, Optional, etc.)

    Returns:
        True if value matches expected type
    """
    # Handle Union types (including Optional which is Union[X, None])
    origin = get_origin(expected_type)
    if origin is Union:
        type_args = get_args(expected_type)
        return any(_check_type(value, t) for t in type_args)

    # Handle tuple of types (e.g., (dict, list))
    if isinstance(expected_type, tuple):
        return any(_check_type(value, t) for t in expected_type)

    # Handle generic types (List, Dict, etc.)
    if origin is not None:
        # For now, just check the origin type (e.g., list for List[str])
        # Could enhance to check element types if needed
        return isinstance(value, origin)

    # Direct type check
    try:
        return isinstance(value, expected_type)
    except TypeError:
        # Some types can't be used with isinstance
        return type(value) == expected_type


def _is_none_allowed(expected_type: Type) -> bool:
    """
    Check if None is allowed for the given type.

    Args:
        expected_type: Type specification

    Returns:
        True if None is allowed (Optional type or Union with None)
    """
    # Check if it's a tuple of types (e.g., (dict, type(None)))
    if isinstance(expected_type, tuple):
        return type(None) in expected_type

    # Check if it's Optional (Union with None)
    origin = get_origin(expected_type)
    if origin is Union:
        type_args = get_args(expected_type)
        return type(None) in type_args

    # Check if it's explicitly None type
    return expected_type is type(None)


def _format_type(type_spec: Type) -> str:
    """
    Format a type specification for display in error messages.

    Args:
        type_spec: Type to format

    Returns:
        Human-readable type string
    """
    # Handle None
    if type_spec is type(None):
        return "None"

    # Handle Union/Optional
    origin = get_origin(type_spec)
    if origin is Union:
        type_args = get_args(type_spec)
        formatted_args = [_format_type(t) for t in type_args]
        # Check if it's Optional (Union with None)
        if type(None) in type_args and len(type_args) == 2:
            other_type = [t for t in type_args if t is not type(None)][0]
            return f"Optional[{_format_type(other_type)}]"
        return f"Union[{', '.join(formatted_args)}]"

    # Handle generic types
    if origin is not None:
        type_args = get_args(type_spec)
        if type_args:
            formatted_args = [_format_type(t) for t in type_args]
            return f"{origin.__name__}[{', '.join(formatted_args)}]"
        return origin.__name__

    # Handle regular types
    if hasattr(type_spec, '__name__'):
        return type_spec.__name__

    return str(type_spec)


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

"""
Example 1: Repository boundary validation
-----------------------------------------
@enforce_contract(
    params={'job_id': str},
    returns=Optional[JobRecord]
)
def get_job(self, job_id: str) -> Optional[JobRecord]:
    row = self._execute_query(...)
    if not row:
        return None
    return JobRecord(**row)


Example 2: Complex parameter validation
----------------------------------------
@enforce_contract(
    params={
        'task_def': TaskDefinition,
        'stage': int,
        'parameters': dict
    },
    returns=TaskRecord
)
def create_task_from_definition(self, task_def, stage, parameters):
    task_record = task_def.to_task_record()
    # ... business logic ...
    return task_record


Example 3: Union type handling
-------------------------------
@enforce_contract(
    params={'result_data': Union[dict, TaskResult]},
    returns=bool
)
def process_result(self, result_data):
    # Can accept either dict or TaskResult
    # ... processing logic ...
    return True


Example 4: Optional parameters
-------------------------------
@enforce_contract(
    params={
        'job_id': str,
        'error_details': Optional[str]  # Can be str or None
    },
    returns=bool
)
def fail_job(self, job_id, error_details=None):
    # ... failure logic ...
    return True
"""