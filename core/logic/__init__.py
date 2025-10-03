# ============================================================================
# CLAUDE CONTEXT - CORE LOGIC PACKAGE
# ============================================================================
# CATEGORY: BUSINESS LOGIC HELPERS
# PURPOSE: Shared utility functions for calculations and state transitions
# EPOCH: Shared by all epochs (business logic)# PURPOSE: Export business logic functions from the core.logic package
# EXPORTS: Transition and calculation functions
# AZURE FUNCTIONS: Required for package imports
# ============================================================================

"""
Core business logic package.

This package contains business logic that operates on the pure data models.
Separated from models to maintain clean architecture.
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