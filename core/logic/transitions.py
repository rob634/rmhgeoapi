# ============================================================================
# CLAUDE CONTEXT - CORE LOGIC - TRANSITIONS
# ============================================================================
# CATEGORY: BUSINESS LOGIC HELPERS
# PURPOSE: Shared utility functions for calculations and state transitions
# EPOCH: Shared by all epochs (business logic)# PURPOSE: State transition logic for jobs and tasks
# EXPORTS: Functions for validating state transitions
# INTERFACES: Operates on core.models data structures
# DEPENDENCIES: core.models.enums
# SOURCE: Business logic extracted from schema_base.py
# SCOPE: State transition validation
# VALIDATION: State machine rules
# PATTERNS: State machine pattern
# ENTRY_POINTS: from core.logic.transitions import can_job_transition
# ============================================================================

"""
State transition logic for jobs and tasks.

This module contains the business rules for valid state transitions.
Separated from the data models to maintain clean architecture.
"""

from typing import List

from ..models.enums import JobStatus, TaskStatus


def can_job_transition(current: JobStatus, target: JobStatus) -> bool:
    """
    Check if a job can transition from current to target status.

    Args:
        current: Current job status
        target: Target job status

    Returns:
        True if transition is valid, False otherwise
    """
    # Same status is always allowed (no-op)
    if current == target:
        return True

    # Define valid transitions
    transitions = {
        JobStatus.QUEUED: [JobStatus.PROCESSING, JobStatus.FAILED],
        JobStatus.PROCESSING: [
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.COMPLETED_WITH_ERRORS
        ],
        JobStatus.FAILED: [],  # Terminal state
        JobStatus.COMPLETED: [],  # Terminal state
        JobStatus.COMPLETED_WITH_ERRORS: []  # Terminal state
    }

    return target in transitions.get(current, [])


def can_task_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """
    Check if a task can transition from current to target status.

    Args:
        current: Current task status
        target: Target task status

    Returns:
        True if transition is valid, False otherwise
    """
    # Same status is always allowed (no-op)
    if current == target:
        return True

    # Define valid transitions
    transitions = {
        TaskStatus.QUEUED: [TaskStatus.PROCESSING, TaskStatus.CANCELLED],
        TaskStatus.PROCESSING: [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED
        ],
        TaskStatus.FAILED: [TaskStatus.RETRYING, TaskStatus.PENDING_RETRY],
        TaskStatus.RETRYING: [TaskStatus.PROCESSING],
        TaskStatus.PENDING_RETRY: [TaskStatus.PROCESSING, TaskStatus.CANCELLED],
        TaskStatus.COMPLETED: [],  # Terminal state
        TaskStatus.CANCELLED: []  # Terminal state
    }

    return target in transitions.get(current, [])


def get_job_terminal_states() -> List[JobStatus]:
    """
    Get list of terminal states for jobs.

    Returns:
        List of terminal job statuses
    """
    return [
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.COMPLETED_WITH_ERRORS
    ]


def get_job_active_states() -> List[JobStatus]:
    """
    Get list of active (non-terminal) states for jobs.

    Returns:
        List of active job statuses
    """
    return [
        JobStatus.QUEUED,
        JobStatus.PROCESSING
    ]


def get_task_terminal_states() -> List[TaskStatus]:
    """
    Get list of terminal states for tasks.

    Returns:
        List of terminal task statuses
    """
    return [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED
    ]


def get_task_active_states() -> List[TaskStatus]:
    """
    Get list of active (non-terminal) states for tasks.

    Returns:
        List of active task statuses
    """
    return [
        TaskStatus.QUEUED,
        TaskStatus.PROCESSING,
        TaskStatus.RETRYING,
        TaskStatus.PENDING_RETRY
    ]


def is_job_terminal(status: JobStatus) -> bool:
    """
    Check if a job status is terminal.

    Args:
        status: Job status to check

    Returns:
        True if status is terminal, False otherwise
    """
    return status in get_job_terminal_states()


def is_task_terminal(status: TaskStatus) -> bool:
    """
    Check if a task status is terminal.

    Args:
        status: Task status to check

    Returns:
        True if status is terminal, False otherwise
    """
    return status in get_task_terminal_states()