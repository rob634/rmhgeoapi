"""
State Transition Logic for Jobs and Tasks.

Contains business rules for valid state transitions.
Separated from data models for clean architecture.

Exports:
    can_job_transition: Check if job state transition is valid
    can_task_transition: Check if task state transition is valid
    get_job_terminal_states: Get terminal states for jobs
    get_task_terminal_states: Get terminal states for tasks
    is_job_terminal: Check if job is in terminal state
    is_task_terminal: Check if task is in terminal state

Dependencies:
    core.models.enums: JobStatus, TaskStatus
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

    # Define valid transitions (16 DEC 2025 - PENDING added)
    transitions = {
        # PENDING: Task created, awaiting trigger confirmation
        TaskStatus.PENDING: [TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED],
        # QUEUED: Trigger confirmed receipt, ready for processing
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
        TaskStatus.PENDING,  # 16 DEC 2025: Task created, awaiting trigger confirmation
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