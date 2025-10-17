# ============================================================================
# CLAUDE CONTEXT - CORE LOGIC PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Core logic - Business logic helpers
# PURPOSE: Export business logic functions from the core.logic package
# LAST_REVIEWED: 16 OCT 2025
# EXPORTS: Transition and calculation functions
# INTERFACES: Package initialization only
# PYDANTIC_MODELS: None - operates on data models
# DEPENDENCIES: Core logic submodules
# AZURE_FUNCTIONS: Required for package imports
# PATTERNS: Package initialization, Separation of concerns
# ENTRY_POINTS: from core.logic import can_job_transition, can_task_transition
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