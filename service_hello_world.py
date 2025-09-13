# ============================================================================
# CLAUDE CONTEXT - SERVICE
# ============================================================================
# PURPOSE: HelloWorld service implementing task handlers for two-stage workflow using TaskRegistry pattern
# EXPORTS: create_greeting_handler, create_reply_handler (registered with @TaskRegistry decorators)
# INTERFACES: TaskRegistry pattern with handler functions returning dicts
# PYDANTIC_MODELS: None - uses dict-based parameter passing and results
# DEPENDENCIES: service_factories (TaskRegistry, TaskContext), datetime, typing
# SOURCE: Task parameters from queue messages via TaskHandlerFactory
# SCOPE: Task-level business logic execution for HelloWorld greeting and reply stages
# VALIDATION: Parameter validation within handler functions
# PATTERNS: Registry pattern (TaskRegistry), Factory pattern, Robert's implicit lineage pattern
# ENTRY_POINTS: Handlers auto-registered via @TaskRegistry decorators for hello_world_greeting/reply
# INDEX: create_greeting_handler:95, create_reply_handler:140, Implementation Notes:50
# ============================================================================

"""
Hello World Service - Task Handler Implementation

Service layer implementation demonstrating the task handler pattern within the
Job→Stage→Task architecture. Uses the TaskRegistry pattern for automatic
handler discovery and registration.

This file serves as a TEMPLATE for future service implementations.

Architecture Position:
    - Job Layer (Controller): HelloWorldController orchestrates stages
    - Stage Layer (Controller): Creates parallel tasks for execution  
    - Task Layer (Service): THIS MODULE - Business logic execution
    - Repository Layer: Data persistence handled by framework

Key Features:
    - Decorator-based handler registration with @TaskRegistry
    - Robert's implicit lineage pattern for multi-stage data access
    - Simple dict-based parameter and result passing
    - Automatic predecessor data access for stage N from stage N-1

Workflow Pattern:
    STAGE 1 (Greeting Stage):
    ├── hello_world_greeting handler (parallel)
    ├── hello_world_greeting handler (parallel)
    └── hello_world_greeting handler (parallel)
                ↓ All tasks complete
    STAGE 2 (Reply Stage):
    ├── hello_world_reply handler (parallel)
    ├── hello_world_reply handler (parallel) 
    └── hello_world_reply handler (parallel)
                ↓ All tasks complete
    JOB COMPLETION (Controller aggregates results)

Implementation Notes:
    - Handlers are functions that return functions (factory pattern)
    - Outer function is called once at registration time
    - Inner function is called for each task execution
    - TaskContext provides automatic lineage tracking and predecessor access
    - Results are simple dicts - framework handles TaskResult wrapping

Lineage Pattern Example:
    Stage 1, Task 3: job123-s1-task_3 → stores result
    Stage 2, Task 3: job123-s2-task_3 → automatically gets s1-task_3 data

Usage Pattern for New Services:
    1. Import TaskRegistry and TaskContext from task_factory
    2. Define handler factory function with @TaskRegistry.instance().register("task_type")
    3. Factory returns actual handler function that processes params
    4. Use context.has_predecessor() and context.get_predecessor_result() for lineage
    5. Return dict with results - framework handles the rest

Author: Robert and Geospatial Claude Legion
Date: 9 December 2025
"""

from datetime import datetime, timezone

# Import the TaskRegistry for handler registration
# This provides the decorator pattern and lineage support
from task_factory import TaskRegistry, TaskContext


# ============================================================================
# STAGE 1: GREETING HANDLER
# ============================================================================
# Demonstrates basic task handler for first stage (no predecessor data)

@TaskRegistry.instance().register("hello_world_greeting")
def create_greeting_handler():
    """
    Factory for hello_world_greeting task handler.
    
    Creates a handler function for Stage 1 greeting tasks.
    Stage 1 has no predecessor, so this demonstrates the base pattern.
    
    Returns:
        Handler function that processes greeting task parameters
        
    Pattern:
        - Factory function (this) is called once at registration
        - Handler function (inner) is called for each task execution
        - Results are returned as simple dicts
    """
    def handle_greeting(params: dict, context: TaskContext) -> dict:
        """
        Execute greeting task.
        
        Args:
            params: Task parameters from queue message
                - task_number: Task index for identification
                - message: Base message content
                - greeting: Greeting text to use
                - total_tasks: Total tasks in this stage
            context: Task context with lineage support
            
        Returns:
            Dict with greeting results and metadata
        """
        # Extract parameters with defaults
        task_number = params.get('task_number', 1)
        message = params.get('message', 'Hello')
        greeting = params.get('greeting', 'World')
        total_tasks = params.get('total_tasks', 1)
        
        # Stage 1 typically has no predecessor, but we check for completeness
        # This demonstrates the pattern even though not used in stage 1
        if context.has_predecessor():
            # This wouldn't normally happen for stage 1
            # Could use predecessor data if it existed
            _ = context.get_predecessor_result()
        
        # Create greeting result (business logic)
        greeting_text = f"{message} from task_{task_number}!"
        
        # Return result as dict
        # Framework handles wrapping in TaskResult
        result = {
            "task_number": task_number,
            "greeting": greeting_text,
            "message": f"Task {task_number}/{total_tasks}: {greeting}",
            "stage": "greeting",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True
        }
        
        return result
    
    return handle_greeting


# ============================================================================
# STAGE 2: REPLY HANDLER
# ============================================================================
# Demonstrates Robert's implicit lineage pattern for accessing predecessor data

@TaskRegistry.instance().register("hello_world_reply")  
def create_reply_handler():
    """
    Factory for hello_world_reply task handler.
    
    Creates a handler function for Stage 2 reply tasks.
    Demonstrates Robert's implicit lineage pattern where tasks
    automatically access their predecessor's data.
    
    Returns:
        Handler function that processes reply task parameters
        
    Lineage Pattern:
        - Task ID format: {job_id}-s{stage}-{index}
        - Stage 2 task automatically gets matching Stage 1 task data
        - Example: job123-s2-task_3 gets data from job123-s1-task_3
    """
    def handle_reply(params: dict, context: TaskContext) -> dict:
        """
        Execute reply task with predecessor data access.
        
        Args:
            params: Task parameters from queue message
                - task_number: Task index for identification
                - total_tasks: Total tasks in this stage
                - replying_to: Optional explicit greeting to reply to
            context: Task context with automatic lineage support
            
        Returns:
            Dict with reply results including lineage information
        """
        # Extract parameters
        task_number = params.get('task_number', 1)
        total_tasks = params.get('total_tasks', 1)
        replying_to = params.get('replying_to', None)
        
        # Demonstrate lineage pattern - automatically get stage 1 result
        reply_message = "Hello from reply stage!"
        original_greeting = None
        
        if context.has_predecessor():
            # Automatically retrieves the matching task from previous stage
            # e.g., s2-task_3 gets data from s1-task_3
            predecessor_data = context.get_predecessor_result()
            if predecessor_data:
                original_greeting = predecessor_data.get('greeting', '')
                reply_message = f"Reply to: {original_greeting}"
        elif replying_to:
            # Fallback to explicit parameter if provided
            original_greeting = replying_to
            reply_message = f"Reply to: {replying_to}"
        
        # Create reply result
        result = {
            "task_number": task_number,
            "reply": reply_message,
            "original_greeting": original_greeting,
            "message": f"Reply task {task_number}/{total_tasks} completed",
            "stage": "reply",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lineage": context.get_lineage_chain(),  # Full lineage chain
            "success": True
        }
        
        return result
    
    return handle_reply


# ============================================================================
# TEMPLATE NOTES FOR FUTURE SERVICES
# ============================================================================

"""
Template for Creating New Service Handlers:

1. Import Requirements:
   from task_factory import TaskRegistry, TaskContext
   from datetime import datetime, timezone
   from typing import Dict, Any

2. Basic Handler Structure:

@TaskRegistry.instance().register("your_task_type")
def create_your_handler():
    '''Factory for your task handler.'''
    
    def handle_task(params: dict, context: TaskContext) -> dict:
        '''Execute your task logic.'''
        
        # Get parameters
        param1 = params.get('param1', 'default')
        
        # Check for predecessor (if stage > 1)
        if context.has_predecessor():
            prev_data = context.get_predecessor_result()
            # Use predecessor data
        
        # Your business logic here
        result = process_something(param1)
        
        # Return results as dict
        return {
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True
        }
    
    return handle_task

3. Multi-Stage Pattern:
   - Stage 1: No predecessor, initialize data
   - Stage 2+: Access predecessor via context
   - Lineage is automatic based on task ID pattern

4. Error Handling:
   - Return {"success": False, "error": "message"} on failure
   - Framework handles TaskResult wrapping and status updates

5. Best Practices:
   - Keep handlers focused on single responsibility
   - Use context for lineage, not explicit parameters
   - Return simple dicts, let framework handle complexity
   - Include timestamp and success flag in results
"""