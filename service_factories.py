# ============================================================================
# CLAUDE CONTEXT - FACTORY
# ============================================================================
# PURPOSE: Registry and factory pattern for task handler discovery and execution
# EXPORTS: TaskRegistry, TaskHandlerFactory, TaskContext
# INTERFACES: Singleton registry pattern, factory methods for task handlers
# PYDANTIC_MODELS: Uses TaskQueueMessage, TaskRecord from schema_base
# DEPENDENCIES: typing, importlib, repository_postgresql
# SOURCE: Task handlers registered via decorators in service modules
# SCOPE: Task execution layer for parallel processing
# VALIDATION: Registry validates task types, ensures handler availability
# PATTERNS: Singleton Registry, Factory, Dependency Injection
# ENTRY_POINTS: TaskRegistry.instance(), TaskHandlerFactory.get_handler()
# INDEX: TaskRegistry:50, TaskHandlerFactory:200, TaskContext:350
# ============================================================================

"""
Task Handler Registry and Factory

Implements Robert's implicit lineage pattern where tasks in stage N can
automatically access their predecessor data from stage N-1 using matching
semantic indices in task IDs.

Example Flow:
    Stage 1: a1b2c3d4-s1-tile_x5_y10 → processes and stores result
    Stage 2: a1b2c3d4-s2-tile_x5_y10 → reads s1 predecessor implicitly
    Stage 3: a1b2c3d4-s3-tile_x5_y10 → reads s2 predecessor implicitly

This pattern enables:
- Parallel processing without coordination overhead
- Natural data flow through workflow stages  
- Debugging via deterministic ID patterns
- Failure isolation per semantic index

Key Components:
- TaskRegistry: Singleton for handler registration
- TaskHandlerFactory: Creates handlers with lineage context
- TaskContext: Provides predecessor data access

Author: Robert and Geospatial Claude Legion
Date: 9 September 2025
"""

from typing import Dict, Callable, Optional, Any, List
import logging
from datetime import datetime, timezone

from schema_base import TaskQueueMessage, TaskRecord, TaskResult, TaskStatus
from repository_base import BaseRepository  # Use base class for type hints
from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.FACTORY, __name__)


# ============================================================================
# TASK REGISTRY - Singleton for handler registration
# ============================================================================

class TaskRegistry:
    """
    Singleton registry for task handlers.
    
    Service modules register their task handlers using the decorator pattern,
    similar to JobRegistry for controllers. Ensures all task types have
    registered handlers before execution.
    
    Usage:
        @TaskRegistry.instance().register("process_tile")
        def create_tile_processor():
            return process_tile_handler
    """
    
    _instance: Optional['TaskRegistry'] = None
    _handlers: Dict[str, Callable] = {}
    
    def __new__(cls):
        """Ensure singleton instance"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
        return cls._instance
    
    @classmethod
    def instance(cls) -> 'TaskRegistry':
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, task_type: str) -> Callable:
        """
        Decorator for registering task handler factories.
        
        Args:
            task_type: Unique identifier for the task type
            
        Returns:
            Decorator function that registers the handler factory
            
        Example:
            @TaskRegistry.instance().register("hello_world_greeting")
            def create_greeting_handler():
                return lambda params: {"greeting": f"Hello {params['name']}"}
        """
        def decorator(handler_factory: Callable) -> Callable:
            if task_type in self._handlers:
                logger.warning(
                    f"Task handler for '{task_type}' already registered, overwriting",
                    extra={"task_type": task_type}
                )
            
            self._handlers[task_type] = handler_factory
            logger.info(
                f"Registered task handler for '{task_type}'",
                extra={"task_type": task_type}
            )
            return handler_factory
        
        return decorator
    
    def get_handler_factory(self, task_type: str) -> Callable:
        """
        Get handler factory for a task type.
        
        Args:
            task_type: Task type to get handler for
            
        Returns:
            Handler factory function
            
        Raises:
            ValueError: If task_type not registered
        """
        if task_type not in self._handlers:
            available = list(self._handlers.keys())
            raise ValueError(
                f"No handler registered for task_type '{task_type}'. "
                f"Available types: {available}"
            )
        return self._handlers[task_type]
    
    def is_registered(self, task_type: str) -> bool:
        """Check if task type has registered handler"""
        return task_type in self._handlers
    
    def list_task_types(self) -> List[str]:
        """Get list of all registered task types"""
        return list(self._handlers.keys())
    
    def clear(self) -> None:
        """Clear all registrations (mainly for testing)"""
        self._handlers.clear()


# ============================================================================
# TASK HANDLER FACTORY - Creates handlers with context
# ============================================================================

class TaskHandlerFactory:
    """
    Factory for creating task handlers with lineage context.
    
    Implements Robert's implicit lineage pattern by injecting predecessor
    data access into task handlers. Handles both stateless functions and
    stateful handler classes.
    """
    
    @staticmethod
    def get_handler(
        task_message: TaskQueueMessage,
        repository: Optional[BaseRepository] = None
    ) -> Callable:
        """
        Get task handler with lineage context injected.
        
        For tasks in stage > 1, automatically provides access to predecessor
        task results using the implicit ID pattern.
        
        Args:
            task_message: Queue message with task details
            repository: Database repository for lineage queries
            
        Returns:
            Handler function ready for execution
            
        Raises:
            ValueError: If task_type not registered
        """
        registry = TaskRegistry.instance()
        
        # Get the handler factory
        handler_factory = registry.get_handler_factory(task_message.task_type)
        
        # Create base handler
        base_handler = handler_factory()
        
        # Create context with lineage support
        context = TaskContext(
            task_id=task_message.task_id,
            job_id=task_message.parent_job_id,
            stage=task_message.stage,
            task_type=task_message.task_type,
            repository=repository
        )
        
        # Wrap handler with context injection
        def handler_with_context(params: Dict[str, Any]) -> TaskResult:
            """Execute handler with lineage context"""
            try:
                # Load predecessor data if not first stage
                if context.stage > 1:
                    context._load_predecessor_data()
                
                # Execute the handler
                if callable(base_handler):
                    # Function-based handler
                    result_data = base_handler(params, context)
                else:
                    # Class-based handler
                    result_data = base_handler.execute(params, context)
                
                # Return success result
                return TaskResult(
                    task_id=context.task_id,
                    success=True,
                    result_data=result_data,
                    error_message=None,
                    completed_at=datetime.now(timezone.utc)
                )
                
            except Exception as e:
                logger.error(
                    f"Task execution failed: {e}",
                    extra={
                        "task_id": context.task_id,
                        "task_type": context.task_type,
                        "error": str(e)
                    }
                )
                
                # Return failure result
                return TaskResult(
                    task_id=context.task_id,
                    success=False,
                    result_data=None,
                    error_message=str(e),
                    completed_at=datetime.now(timezone.utc)
                )
        
        return handler_with_context
    
    @staticmethod
    def validate_handler_availability(task_types: List[str]) -> Dict[str, bool]:
        """
        Validate that handlers exist for given task types.
        
        Args:
            task_types: List of task types to validate
            
        Returns:
            Dict mapping task_type to availability (True/False)
        """
        registry = TaskRegistry.instance()
        return {
            task_type: registry.is_registered(task_type)
            for task_type in task_types
        }


# ============================================================================
# TASK CONTEXT - Lineage and metadata access
# ============================================================================

class TaskContext:
    """
    Execution context providing access to task metadata and lineage.
    
    Implements Robert's implicit lineage pattern where tasks automatically
    access predecessor data based on ID structure:
    - Current: a1b2c3d4-s2-tile_x5_y10
    - Predecessor: a1b2c3d4-s1-tile_x5_y10
    
    This enables natural data flow without explicit handoff mechanisms.
    """
    
    def __init__(
        self,
        task_id: str,
        job_id: str,
        stage: int,
        task_type: str,
        repository: Optional[BaseRepository] = None
    ):
        """
        Initialize task context.
        
        Args:
            task_id: Current task ID with structure job-stage-index
            job_id: Parent job ID
            stage: Current stage number
            task_type: Type of task being executed
            repository: Database repository for queries
        """
        self.task_id = task_id
        self.job_id = job_id
        self.stage = stage
        self.task_type = task_type
        self.repository = repository
        
        # Parse semantic index from task ID
        self.semantic_index = self._parse_semantic_index(task_id)
        
        # Lazy-loaded predecessor data
        self._predecessor_data: Optional[Dict[str, Any]] = None
        self._predecessor_loaded = False
    
    def _parse_semantic_index(self, task_id: str) -> str:
        """
        Extract semantic index from task ID.
        
        Examples:
            a1b2c3d4-s2-tile_x5_y10 → tile_x5_y10
            a1b2c3d4-s1-calculate → calculate
        """
        parts = task_id.split('-s')
        if len(parts) < 2:
            return ""
        
        stage_and_index = parts[1].split('-', 1)
        return stage_and_index[1] if len(stage_and_index) > 1 else ""
    
    def get_predecessor_id(self) -> Optional[str]:
        """
        Calculate predecessor task ID using implicit pattern.
        
        Returns:
            Predecessor task ID for stage > 1, None for stage 1
        """
        if self.stage <= 1:
            return None
        
        # Parse current ID structure
        parts = self.task_id.split('-s')
        if len(parts) < 2:
            return None
        
        job_prefix = parts[0]
        
        # Build predecessor ID with stage - 1
        return f"{job_prefix}-s{self.stage - 1}-{self.semantic_index}"
    
    def _load_predecessor_data(self) -> None:
        """Load predecessor task result data from database"""
        if self._predecessor_loaded:
            return
        
        self._predecessor_loaded = True
        
        if not self.repository:
            logger.warning(
                "No repository available for predecessor lookup",
                extra={"task_id": self.task_id}
            )
            return
        
        predecessor_id = self.get_predecessor_id()
        if not predecessor_id:
            return
        
        try:
            # Query predecessor task
            predecessor_task = self.repository.get_task(predecessor_id)
            if predecessor_task and predecessor_task.get('result_data'):
                self._predecessor_data = predecessor_task['result_data']
                logger.debug(
                    f"Loaded predecessor data from {predecessor_id}",
                    extra={
                        "task_id": self.task_id,
                        "predecessor_id": predecessor_id
                    }
                )
        except Exception as e:
            logger.error(
                f"Failed to load predecessor data: {e}",
                extra={
                    "task_id": self.task_id,
                    "predecessor_id": predecessor_id,
                    "error": str(e)
                }
            )
    
    def get_predecessor_result(self) -> Optional[Dict[str, Any]]:
        """
        Get predecessor task result data.
        
        Implements Robert's lineage pattern - automatically retrieves
        result_data from the task with same semantic index in previous stage.
        
        Returns:
            Predecessor's result_data or None if stage 1 or not found
        """
        if not self._predecessor_loaded:
            self._load_predecessor_data()
        return self._predecessor_data
    
    def has_predecessor(self) -> bool:
        """Check if this task has a predecessor (stage > 1)"""
        return self.stage > 1
    
    def get_lineage_chain(self) -> List[str]:
        """
        Get full lineage chain of task IDs.
        
        Returns:
            List of task IDs from stage 1 to current stage
            
        Example:
            For a1b2c3d4-s3-tile_x5_y10:
            [
                "a1b2c3d4-s1-tile_x5_y10",
                "a1b2c3d4-s2-tile_x5_y10", 
                "a1b2c3d4-s3-tile_x5_y10"
            ]
        """
        lineage = []
        
        # Parse job prefix
        parts = self.task_id.split('-s')
        if len(parts) < 2:
            return [self.task_id]
        
        job_prefix = parts[0]
        
        # Build lineage chain
        for stage_num in range(1, self.stage + 1):
            task_id = f"{job_prefix}-s{stage_num}-{self.semantic_index}"
            lineage.append(task_id)
        
        return lineage


# ============================================================================
# AUTO-REGISTRATION HELPER
# ============================================================================

def auto_discover_handlers():
    """
    Auto-discover and import service modules to trigger handler registration.
    
    This function can be called during startup to ensure all service modules
    are imported and their handlers registered via decorators.
    """
    import glob
    import os
    
    # Find all service_*.py files
    service_files = glob.glob(os.path.join(os.path.dirname(__file__), "service_*.py"))
    
    for filepath in service_files:
        module_name = os.path.basename(filepath)[:-3]  # Remove .py
        try:
            # Import module to trigger decorator registration
            __import__(module_name)
            logger.debug(f"Auto-discovered service module: {module_name}")
        except Exception as e:
            logger.error(f"Failed to import {module_name}: {e}")


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

"""
Example Registration in service_hello_world.py:

@TaskRegistry.instance().register("hello_world_greeting")
def create_greeting_handler():
    def handle_greeting(params: dict, context: TaskContext) -> dict:
        name = params.get('name', 'World')
        
        # Check for predecessor data (if stage > 1)
        if context.has_predecessor():
            prev_data = context.get_predecessor_result()
            previous_message = prev_data.get('message', '')
            return {
                "greeting": f"Hello {name}!",
                "previous": previous_message
            }
        
        return {"greeting": f"Hello {name}!"}
    
    return handle_greeting


Example Usage in function_app.py:

# Replace hardcoded logic with:
handler = TaskHandlerFactory.get_handler(task_message, repository)
result = handler(task_message.parameters)

# Complete task with result
repository.complete_task(
    task_message.task_id,
    result.success,
    result.result_data,
    result.error_message
)
"""