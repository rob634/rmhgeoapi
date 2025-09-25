# ============================================================================
# CLAUDE CONTEXT - REGISTRATION CATALOGS
# ============================================================================
# PURPOSE: Non-singleton catalogs for explicit registration without import-time side effects
# EXPORTS: JobCatalog, TaskCatalog - instance-based registries for controllers and handlers
# INTERFACES: None (these are concrete implementations, not interfaces)
# PYDANTIC_MODELS: None (uses dictionaries for metadata storage)
# DEPENDENCIES: typing, logging
# SOURCE: Controllers and services provide static metadata dictionaries
# SCOPE: Function App instance-specific (not global)
# VALIDATION: Duplicate registration detection, missing type errors
# PATTERNS: Instance-based registry (NOT singleton), explicit registration
# ENTRY_POINTS: JobCatalog.register_controller(), TaskCatalog.register_handler()
# INDEX:
#   - JobCatalog: Line 35
#   - TaskCatalog: Line 115
#   - Usage Examples: Line 195
# ============================================================================

"""
Registration catalogs for job controllers and task handlers.

This module provides non-singleton, instance-based registries that replace
the problematic decorator-based registration pattern. Each Function App
creates its own catalog instances, allowing for:
- Explicit registration timing
- No import-time side effects
- Clean testing without global state
- Easy migration to microservices

Author: Robert and Geospatial Claude Legion
Date: 23 SEP 2025
"""

from typing import Dict, Type, Any, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


class JobCatalog:
    """
    Non-singleton registry for job controllers.

    This replaces the anti-pattern JobRegistry singleton with an instance-based
    catalog that each Function App creates and manages independently.

    Key Features:
    - No global state or singletons
    - Explicit registration with metadata
    - Duplicate detection
    - Clean error messages for missing types

    Usage:
        catalog = JobCatalog()
        catalog.register_controller(
            job_type="hello_world",
            controller_class=HelloWorldController,
            metadata={'description': 'Test controller', 'timeout': 300}
        )

        # Later, retrieve controller
        controller_class = catalog.get_controller("hello_world")
    """

    def __init__(self):
        """Initialize empty catalog."""
        self._controllers: Dict[str, Dict[str, Any]] = {}
        logger.info("📚 Created new JobCatalog instance")

    def register_controller(
        self,
        job_type: str,
        controller_class: Type,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Register a controller with metadata.

        Args:
            job_type: Unique identifier for the job type
            controller_class: The controller class to register
            metadata: Optional metadata dictionary containing:
                - workflow: WorkflowDefinition object
                - description: Human-readable description
                - max_parallel_tasks: Maximum parallel task execution
                - timeout_minutes: Job timeout in minutes
                - required_env_vars: List of required environment variables

        Raises:
            ValueError: If job_type is already registered
        """
        if job_type in self._controllers:
            existing = self._controllers[job_type]['class'].__name__
            new = controller_class.__name__
            raise ValueError(
                f"Controller for '{job_type}' already registered. "
                f"Existing: {existing}, Attempted: {new}"
            )

        self._controllers[job_type] = {
            'class': controller_class,
            'metadata': metadata or {}
        }

        logger.info(f"✅ Registered controller: {job_type} -> {controller_class.__name__}")
        logger.debug(f"   Metadata: {metadata}")

    def get_controller(self, job_type: str) -> Type:
        """
        Get controller class for job type.

        Args:
            job_type: The job type to look up

        Returns:
            The controller class

        Raises:
            ValueError: If no controller registered for job_type
        """
        if job_type not in self._controllers:
            available = ', '.join(sorted(self._controllers.keys()))
            raise ValueError(
                f"No controller registered for job type: '{job_type}'. "
                f"Available types: {available or 'none'}"
            )

        return self._controllers[job_type]['class']

    def get_metadata(self, job_type: str) -> Dict[str, Any]:
        """
        Get metadata for a registered controller.

        Args:
            job_type: The job type to look up

        Returns:
            The metadata dictionary for the controller

        Raises:
            ValueError: If no controller registered for job_type
        """
        if job_type not in self._controllers:
            raise ValueError(f"No controller registered for job type: '{job_type}'")

        return self._controllers[job_type]['metadata']

    def list_job_types(self) -> List[str]:
        """
        List all registered job types.

        Returns:
            Sorted list of registered job type strings
        """
        return sorted(self._controllers.keys())

    def clear(self) -> None:
        """
        Clear all registrations.

        Useful for testing or resetting the catalog.
        """
        count = len(self._controllers)
        self._controllers.clear()
        logger.info(f"🗑️ Cleared {count} controller registrations")


class TaskCatalog:
    """
    Non-singleton registry for task handlers.

    This replaces the anti-pattern TaskRegistry singleton with an instance-based
    catalog for task handler functions.

    Key Features:
    - Registers handler functions (not classes)
    - Stores handler metadata
    - No global state
    - Support for factory functions that return handlers

    Usage:
        catalog = TaskCatalog()
        catalog.register_handler(
            task_type="hello_world_greeting",
            handler_factory=create_greeting_handler,
            metadata={'description': 'Generate greeting', 'timeout': 30}
        )

        # Later, retrieve handler
        handler_func = catalog.get_handler("hello_world_greeting")
    """

    def __init__(self):
        """Initialize empty catalog."""
        self._handlers: Dict[str, Dict[str, Any]] = {}
        logger.info("📚 Created new TaskCatalog instance")

    def register_handler(
        self,
        task_type: str,
        handler_factory: Callable,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Register a task handler with metadata.

        Args:
            task_type: Unique identifier for the task type
            handler_factory: Function that returns the handler
            metadata: Optional metadata dictionary containing:
                - description: Human-readable description
                - timeout_seconds: Task timeout in seconds
                - max_retries: Maximum retry attempts
                - required_services: List of required service names

        Raises:
            ValueError: If task_type is already registered
        """
        if task_type in self._handlers:
            existing = self._handlers[task_type]['factory'].__name__
            new = handler_factory.__name__
            raise ValueError(
                f"Handler for '{task_type}' already registered. "
                f"Existing: {existing}, Attempted: {new}"
            )

        self._handlers[task_type] = {
            'factory': handler_factory,
            'metadata': metadata or {}
        }

        logger.info(f"✅ Registered handler: {task_type} -> {handler_factory.__name__}")
        logger.debug(f"   Metadata: {metadata}")

    def get_handler(self, task_type: str) -> Callable:
        """
        Get handler factory function for task type.

        Args:
            task_type: The task type to look up

        Returns:
            The handler factory function (not called yet)

        Raises:
            ValueError: If no handler registered for task_type
        """
        if task_type not in self._handlers:
            available = ', '.join(sorted(self._handlers.keys()))
            raise ValueError(
                f"No handler registered for task type: '{task_type}'. "
                f"Available types: {available or 'none'}"
            )

        # Return the factory function (don't call it)
        # The TaskHandlerFactory will call it when needed
        factory = self._handlers[task_type]['factory']
        return factory

    def get_metadata(self, task_type: str) -> Dict[str, Any]:
        """
        Get metadata for a registered handler.

        Args:
            task_type: The task type to look up

        Returns:
            The metadata dictionary for the handler

        Raises:
            ValueError: If no handler registered for task_type
        """
        if task_type not in self._handlers:
            raise ValueError(f"No handler registered for task type: '{task_type}'")

        return self._handlers[task_type]['metadata']

    def list_task_types(self) -> List[str]:
        """
        List all registered task types.

        Returns:
            Sorted list of registered task type strings
        """
        return sorted(self._handlers.keys())

    def clear(self) -> None:
        """
        Clear all registrations.

        Useful for testing or resetting the catalog.
        """
        count = len(self._handlers)
        self._handlers.clear()
        logger.info(f"🗑️ Cleared {count} handler registrations")


# ============================================================================
# USAGE EXAMPLES (for documentation)
# ============================================================================

"""
Example: Registering Controllers in Function App

# function_app.py
from registration import JobCatalog
from controller_hello_world import HelloWorldController

# Create catalog for this Function App instance
job_catalog = JobCatalog()

# Register controllers explicitly at startup
def initialize_controllers():
    # Use static metadata from controller
    job_catalog.register_controller(
        job_type=HelloWorldController.REGISTRATION_INFO['job_type'],
        controller_class=HelloWorldController,
        metadata=HelloWorldController.REGISTRATION_INFO
    )

# HTTP trigger uses catalog
@app.route(route="jobs/submit/{job_type}")
def submit_job(req):
    job_type = req.route_params.get('job_type')
    controller_class = job_catalog.get_controller(job_type)
    controller = controller_class()
    return controller.process(req.get_json())


Example: Registering Task Handlers

# function_app.py
from registration import TaskCatalog
from service_hello_world import create_greeting_handler, HELLO_GREETING_INFO

# Create catalog for task handlers
task_catalog = TaskCatalog()

# Register handlers at startup
def initialize_handlers():
    task_catalog.register_handler(
        task_type=HELLO_GREETING_INFO['task_type'],
        handler_factory=create_greeting_handler,
        metadata=HELLO_GREETING_INFO
    )

# Queue trigger uses catalog
@app.queue_trigger(arg_name="msg", queue_name="tasks")
def process_task(msg):
    task_data = json.loads(msg)
    handler = task_catalog.get_handler(task_data['task_type'])
    return handler(task_data)
"""