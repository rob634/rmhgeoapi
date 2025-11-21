# ============================================================================
# CLAUDE CONTEXT - TASK EXECUTOR ABC
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core component of new architecture
# CATEGORY: BUSINESS LOGIC CONTRACTS - BEHAVIOR
# PURPOSE: Abstract base class defining task execution behavior
# EXPORTS: TaskExecutor - ABC for task business logic
# INTERFACES: Defines contract that all task implementations must follow
# PYDANTIC_MODELS: TaskExecutor receives/returns dicts (validated by framework)
# DEPENDENCIES: abc, typing
# SOURCE: Framework pattern from epoch4_framework.md
# SCOPE: All task implementations inherit from this (or use @register_task decorator)
# VALIDATION: Input/output validation handled by framework (Pydantic)
# PATTERNS: Abstract Base Class, Strategy Pattern, Separation of Concerns
# ENTRY_POINTS: Subclass TaskExecutor or use @register_task decorator on functions
# ARCHITECTURE: TaskExecutor (behavior) + TaskData (data) = "Task" entity (composition)
# INDEX: TaskExecutor:40, execute:65
# ============================================================================

"""
TaskExecutor ABC - Task Behavior Contract

Defines the BEHAVIOR contract for task implementations.
This is the BEHAVIOR half of the "Task" conceptual entity.
The DATA half is defined by TaskData (core/contracts).

Architecture:
    TaskData (core/contracts) - What a task IS (identity, parameters)
    TaskExecutor (this file) - What a task DOES (business logic)

    They collaborate via composition:
    ```python
    task_record = TaskRecord(task_type="greet", parameters={...})  # DATA
    executor = TASK_REGISTRY[task_record.task_type]()              # BEHAVIOR
    result = executor.execute(task_record.parameters)              # COMPOSITION
    ```

Two usage patterns:
    1. Class-based: Subclass TaskExecutor and implement execute()
    2. Function-based: Use @register_task decorator on functions

See core/contracts/__init__.py for full architecture explanation.

"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class TaskExecutor(ABC):
    """
    Abstract base class for task execution behavior.

    TaskExecutor defines WHAT TASKS DO (behavior), not what they ARE (data).
    This is the behavior contract that all task implementations must follow.

    The conceptual "Task" entity emerges from the collaboration between:
    - TaskData/TaskRecord (data) - Identity, parameters, state
    - TaskExecutor (behavior) - Business logic implementation

    They are composed together, not inherited from a common base.

    Subclasses must implement:
        - execute(): Perform the task business logic

    Example (Class-based):
        class GreetTaskExecutor(TaskExecutor):
            def execute(self, params: dict) -> dict:
                name = params['name']
                return {'greeting': f"Hello, {name}!"}

    Example (Function-based):
        @register_task("greet")
        def greet_task(params: dict) -> dict:
            name = params['name']
            return {'greeting': f"Hello, {name}!"}
    """

    @abstractmethod
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the task business logic with given parameters.

        Args:
            params: Task parameters (from TaskRecord.parameters or TaskQueueMessage.parameters)

        Returns:
            Task result dictionary (will be stored in TaskRecord.result_data)

        Raises:
            Exception: Task-specific errors (caught by framework)

        Example:
            params = {'name': 'World', 'count': 5}
            result = executor.execute(params)
            # result = {'greeting': 'Hello, World!', 'count': 5}
        """
        pass
