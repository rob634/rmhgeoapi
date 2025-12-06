"""
Hello World Task Handlers.

Implements the business logic for HelloWorld workflow.
Pure functions with zero orchestration code.

Each handler:
    - Receives params dict
    - Returns result dict
    - Framework handles queuing, state, and completion

Exports:
    greet_handler: Stage 1 greeting task
    process_greeting_handler: Stage 2 processing task
    finalize_hello_handler: Stage 3 finalization task

Dependencies:
    services.registry: Task registration
"""

from typing import Dict, Any
from services.registry import register_task
import time


@register_task("greet")
def greet_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 1: Generate greeting tasks (fan-out).

    This is a "determination" task that creates n parallel tasks for Stage 2.

    Args:
        params: {
            'n': int,              # Number of greetings to create
            'message': str,        # Greeting message
            'job_id': str          # Job ID (provided by framework)
        }

    Returns:
        {
            'status': 'completed',
            'greetings_created': int,
            'next_stage_tasks': [...]  # Tasks for Stage 2
        }
    """
    n = params['n']
    message = params['message']

    # Create task definitions for Stage 2 (n parallel tasks)
    next_stage_tasks = []
    for i in range(n):
        next_stage_tasks.append({
            'greeting_id': i,
            'message': message,
            'index': i
        })

    return {
        'status': 'completed',
        'greetings_created': n,
        'message': f"Created {n} greeting tasks",
        'next_stage_tasks': next_stage_tasks  # Framework uses this to create Stage 2 tasks
    }


@register_task("process_greeting")
def process_greeting_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 2: Process individual greeting (runs n times in parallel).

    Tests parallel execution and stage progression when all complete.

    Args:
        params: {
            'greeting_id': int,    # Greeting identifier
            'message': str,        # Greeting message
            'index': int,          # Task index
            'task_id': str         # Task ID (provided by framework)
        }

    Returns:
        {
            'status': 'completed',
            'greeting_id': int,
            'processed_message': str
        }
    """
    greeting_id = params['greeting_id']
    message = params['message']
    index = params['index']

    # Simulate some work
    time.sleep(0.1)

    # Process the greeting
    processed = f"{message} from task #{index}!"

    return {
        'status': 'completed',
        'greeting_id': greeting_id,
        'index': index,
        'processed_message': processed.upper(),
        'original_message': message
    }


@register_task("finalize_hello")
def finalize_hello_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 3: Finalize workflow (fan-in).

    Tests job completion logic.

    Args:
        params: {
            'job_id': str          # Job ID (provided by framework)
        }

    Returns:
        {
            'status': 'completed',
            'message': str,
            'summary': str
        }
    """
    job_id = params.get('job_id', 'unknown')

    # In a real workflow, this might:
    # - Query database for all Stage 2 results
    # - Aggregate results
    # - Create final output
    #
    # For HelloWorld, we just mark completion

    return {
        'status': 'completed',
        'message': 'Hello World workflow completed successfully!',
        'summary': f'Job {job_id} processed all greetings',
        'job_id': job_id
    }


# That's it! ~140 lines total.
# Pure business logic, zero orchestration.
# Framework handles:
# - Task queuing
# - Parallel execution
# - Stage advancement
# - Completion detection
# - Database updates
# - Error handling
