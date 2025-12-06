"""
TaskExecutor ABC - Task Behavior Contract.

Defines the BEHAVIOR contract for task implementations.
TaskData (core/contracts) defines what a task IS (identity, parameters).
TaskExecutor defines what a task DOES (business logic).

Usage patterns:
    Class-based: Subclass TaskExecutor and implement execute()
    Function-based: Use @register_task decorator on functions

Exports:
    TaskExecutor: Abstract base class for task implementations
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
