# ============================================================================
# CLAUDE CONTEXT - TASK REGISTRY
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component of new architecture
# PURPOSE: Task handler registration system with decorator pattern
# EXPORTS: TASK_REGISTRY dict, register_task decorator, get_task function
# INTERFACES: Works with Task ABC or plain functions
# PYDANTIC_MODELS: None directly, works with Task subclasses and functions
# DEPENDENCIES: typing, services.task
# SOURCE: Framework pattern from epoch4_framework.md
# SCOPE: Application-wide task registration
# VALIDATION: Validates task_type uniqueness
# PATTERNS: Registry Pattern, Decorator Pattern, Adapter Pattern
# ENTRY_POINTS: @register_task decorator, get_task()
# INDEX: TASK_REGISTRY:30, register_task:50, get_task:100
# ============================================================================

"""
Task Registry - Task Handler Registration System

Provides decorator-based registration for task handlers.
Maps task_type strings to Task classes or functions for dynamic execution.

Supports two patterns:
    1. Class-based tasks (Task subclasses)
    2. Function-based tasks (plain functions)

Usage:
    # Class-based
    @register_task("greet")
    class GreetTask(Task):
        def execute(self, params): ...

    # Function-based (simpler)
    @register_task("greet")
    def greet_handler(params: dict) -> dict:
        ...

    # Later:
    handler = get_task("greet")
    result = handler(params)

"""

from typing import Dict, Callable, Any, Union, Type
from services.task import TaskExecutor


# ============================================================================
# GLOBAL REGISTRY
# ============================================================================

TASK_REGISTRY: Dict[str, Union[Type[TaskExecutor], Callable]] = {}
"""
Global registry mapping task_type → Task class or function.

Example:
    {
        "greet": GreetTask,
        "process_greeting": process_greeting_function,
        "finalize": FinalizeTask,
    }
"""


# ============================================================================
# REGISTRATION DECORATOR
# ============================================================================

def register_task(task_type: str):
    """
    Decorator to register a task handler (class or function).

    Usage (class-based):
        @register_task("greet")
        class GreetTask(Task):
            def execute(self, params):
                return {'greeting': 'Hello!'}

    Usage (function-based):
        @register_task("greet")
        def greet_handler(params: dict) -> dict:
            return {'greeting': 'Hello!'}

    Args:
        task_type: Task type identifier (e.g., "greet", "process_greeting")

    Returns:
        Decorator function

    Raises:
        ValueError: If task_type already registered
    """
    def decorator(handler: Union[Type[TaskExecutor], Callable]) -> Union[Type[TaskExecutor], Callable]:
        # Check for duplicates
        if task_type in TASK_REGISTRY:
            existing = TASK_REGISTRY[task_type]
            existing_name = getattr(existing, '__name__', str(existing))
            handler_name = getattr(handler, '__name__', str(handler))
            raise ValueError(
                f"Task type '{task_type}' already registered to {existing_name}. "
                f"Cannot register {handler_name}."
            )

        # Register it
        TASK_REGISTRY[task_type] = handler

        return handler

    return decorator


# ============================================================================
# LOOKUP FUNCTIONS
# ============================================================================

def get_task(task_type: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """
    Get a task handler by task_type.

    Returns a callable that takes params dict and returns result dict,
    regardless of whether the underlying handler is a Task class or function.

    Args:
        task_type: Task type identifier (e.g., "greet")

    Returns:
        Callable: function(params: dict) -> dict

    Raises:
        ValueError: If task_type not found in registry

    Example:
        handler = get_task("greet")
        result = handler({'name': 'World'})
    """
    if task_type not in TASK_REGISTRY:
        available = ', '.join(sorted(TASK_REGISTRY.keys()))
        raise ValueError(
            f"Unknown task type: '{task_type}'. "
            f"Available: {available or '(none registered)'}"
        )

    handler = TASK_REGISTRY[task_type]

    # Check if it's a TaskExecutor subclass
    if isinstance(handler, type) and issubclass(handler, TaskExecutor):
        # It's a class - instantiate and return execute method
        instance = handler()
        return instance.execute
    else:
        # It's a function - return directly
        return handler


def list_registered_tasks() -> list[str]:
    """
    Get list of all registered task types.

    Returns:
        Sorted list of task_type strings

    Example:
        >>> list_registered_tasks()
        ['finalize_hello', 'greet', 'process_greeting']
    """
    return sorted(TASK_REGISTRY.keys())


def is_registered(task_type: str) -> bool:
    """
    Check if a task type is registered.

    Args:
        task_type: Task type identifier

    Returns:
        True if registered, False otherwise
    """
    return task_type in TASK_REGISTRY
