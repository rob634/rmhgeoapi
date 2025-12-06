"""
Core Business Logic Package.

Contains business logic that operates on pure data models.
Separated from models to maintain clean architecture.

Exports:
    State transitions: can_job_transition, can_task_transition, is_job_terminal, is_task_terminal
    Calculations: calculate_success_rate, is_stage_complete, aggregate_task_results
"""

# State transitions
from .transitions import (
    can_job_transition,
    can_task_transition,
    get_job_terminal_states,
    get_job_active_states,
    get_task_terminal_states,
    get_task_active_states,
    is_job_terminal,
    is_task_terminal
)

# Calculations
from .calculations import (
    calculate_success_rate,
    calculate_completion_percentage,
    is_stage_complete,
    stage_success_rate,
    count_successful_tasks,
    count_failed_tasks,
    aggregate_task_results,
    needs_retry,
    all_tasks_succeeded,
    get_error_summary
)

__all__ = [
    # State transitions
    'can_job_transition',
    'can_task_transition',
    'get_job_terminal_states',
    'get_job_active_states',
    'get_task_terminal_states',
    'get_task_active_states',
    'is_job_terminal',
    'is_task_terminal',

    # Calculations
    'calculate_success_rate',
    'calculate_completion_percentage',
    'is_stage_complete',
    'stage_success_rate',
    'count_successful_tasks',
    'count_failed_tasks',
    'aggregate_task_results',
    'needs_retry',
    'all_tasks_succeeded',
    'get_error_summary'
]