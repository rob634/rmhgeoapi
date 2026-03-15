# ============================================================================
# STATE TRANSITION LOGIC
# ============================================================================
# STATUS: Core - Valid state transition rules
# PURPOSE: Business rules for job and task state machine transitions
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
State Transition Logic for Jobs and Tasks.

Contains business rules for valid state transitions.
Separated from data models for clean architecture.

Exports:
    can_job_transition: Check if job state transition is valid
    can_task_transition: Check if task state transition is valid
    get_job_terminal_states: Get terminal states for jobs
    get_task_terminal_states: Get terminal states for tasks (stage completion)
    get_task_settled_states: Get settled states for tasks (will never change)
    get_task_active_states: Get active (non-terminal) states for tasks
    get_task_claimable_states: Get states eligible for worker SKIP LOCKED claim
    is_job_terminal: Check if job is in terminal state
    is_task_terminal: Check if task is terminal (done for stage completion)
    is_task_settled: Check if task is settled (will never change again)

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

    # NOTE: Must stay in sync with JobRecord.can_transition_to() in core/models/job.py
    transitions = {
        JobStatus.QUEUED: [JobStatus.PROCESSING, JobStatus.FAILED],
        JobStatus.PROCESSING: [
            JobStatus.QUEUED,  # Stage advancement re-queuing
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.COMPLETED_WITH_ERRORS
        ],
        # Terminal states allow recovery transitions (error recovery/retry)
        JobStatus.FAILED: [JobStatus.QUEUED],
        JobStatus.COMPLETED: [JobStatus.QUEUED],
        JobStatus.COMPLETED_WITH_ERRORS: [JobStatus.QUEUED]
    }

    return target in transitions.get(current, [])


def can_task_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """
    Check if a task can transition from current to target status.

    DAG-standard lifecycle (15 MAR 2026 — DB-polling migration):

        PENDING → READY → PROCESSING → COMPLETED
        PENDING → SKIPPED (when: condition false)
        PROCESSING → FAILED → PENDING_RETRY → READY (retry loop)
        PROCESSING → PENDING (janitor reset of stuck tasks)
        CANCELLED from any non-terminal state

    Args:
        current: Current task status
        target: Target task status

    Returns:
        True if transition is valid, False otherwise
    """
    # Same status is always allowed (no-op)
    if current == target:
        return True

    # 15 MAR 2026: DAG-standard transitions (replaces SB confirmation flow)
    transitions = {
        # PENDING: Created, dependencies not yet satisfied
        TaskStatus.PENDING: [TaskStatus.READY, TaskStatus.SKIPPED, TaskStatus.CANCELLED],
        # READY: All deps met, available for worker SKIP LOCKED
        TaskStatus.READY: [TaskStatus.PROCESSING, TaskStatus.CANCELLED],
        TaskStatus.PROCESSING: [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.PENDING  # Janitor can reset stuck PROCESSING to PENDING
        ],
        # FAILED: terminal for stage completion, but allows retry
        TaskStatus.FAILED: [TaskStatus.PENDING_RETRY, TaskStatus.CANCELLED],
        # PENDING_RETRY: scheduled for retry with execute_after backoff
        # PROCESSING added (15 MAR 2026): claim_ready_task claims PENDING_RETRY
        # directly via SKIP LOCKED — no intermediate READY state needed.
        TaskStatus.PENDING_RETRY: [TaskStatus.READY, TaskStatus.PROCESSING, TaskStatus.CANCELLED],
        # Terminal states
        TaskStatus.COMPLETED: [],
        TaskStatus.SKIPPED: [],
        TaskStatus.CANCELLED: [],
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
    Get list of terminal states for tasks (stage completion purposes).

    A task in a terminal state counts as "done" for stage completion checks.
    Note: FAILED is terminal for stage completion but allows retry transition.

    Returns:
        List of terminal task statuses
    """
    return [
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.SKIPPED,
        TaskStatus.CANCELLED,
    ]


def get_task_settled_states() -> List[TaskStatus]:
    """
    Get list of settled states for tasks (will never change again).

    Unlike terminal states, settled states cannot transition to anything.
    FAILED is excluded because it can transition to PENDING_RETRY.

    Returns:
        List of settled task statuses
    """
    return [
        TaskStatus.COMPLETED,
        TaskStatus.SKIPPED,
        TaskStatus.CANCELLED,
    ]


def get_task_active_states() -> List[TaskStatus]:
    """
    Get list of active (non-terminal) states for tasks.

    Returns:
        List of active task statuses
    """
    return [
        TaskStatus.PENDING,
        TaskStatus.READY,
        TaskStatus.PROCESSING,
        TaskStatus.PENDING_RETRY,
    ]


def get_task_claimable_states() -> List[TaskStatus]:
    """
    Get list of states eligible for worker SKIP LOCKED claim.

    Workers poll for tasks in these states where execute_after has elapsed.

    Returns:
        List of claimable task statuses
    """
    return [
        TaskStatus.READY,
        TaskStatus.PENDING_RETRY,
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
    Check if a task status is terminal (done for stage completion).

    Note: FAILED is terminal (stage can complete) but not settled
    (can still transition to PENDING_RETRY). Use is_task_settled()
    to check if a task will never change again.

    Args:
        status: Task status to check

    Returns:
        True if status is terminal, False otherwise
    """
    return status in get_task_terminal_states()


def is_task_settled(status: TaskStatus) -> bool:
    """
    Check if a task status is settled (will never change again).

    Args:
        status: Task status to check

    Returns:
        True if status is settled, False otherwise
    """
    return status in get_task_settled_states()