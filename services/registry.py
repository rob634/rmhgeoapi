# ============================================================================
# TASK REGISTRY
# ============================================================================
# STATUS: Service layer - Task handler registration system
# PURPOSE: Provide decorator-based registration for task handlers
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# EXPORTS: TASK_REGISTRY, register_task, get_task, list_registered_tasks, is_registered
# ============================================================================
"""
Task Registry - Task Handler Registration System.

Provides decorator-based registration for task handlers.
Maps task_type strings to Task classes or functions.

Supports:
    - Class-based tasks (TaskExecutor subclasses)
    - Function-based tasks (plain functions)

Usage:
    @register_task("greet")
    def greet_handler(params: dict) -> dict:
        return {"success": True, "result": {"message": "Hello"}}

    handler = get_task("greet")
    result = handler(params)

Exports:
    TASK_REGISTRY: Global registry dict
    register_task: Registration decorator
    get_task: Retrieve registered handler
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
