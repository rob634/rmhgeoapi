"""
Exhaustive state machine transition tests.

Anti-overfitting: Every (current, target) enum pair is tested.
No cherry-picked transitions — all combinations covered.
"""

import pytest

from core.models.enums import JobStatus, TaskStatus
from core.logic.transitions import (
    can_job_transition,
    can_task_transition,
    get_job_terminal_states,
    get_job_active_states,
    get_task_terminal_states,
    get_task_active_states,
    is_job_terminal,
    is_task_terminal,
)


# ============================================================================
# DATA: Expected transition maps (source of truth for tests)
# ============================================================================

# Job transitions: (current, target) -> expected bool
# Built from transitions.py lines 48-60
_JOB_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.PROCESSING, JobStatus.FAILED},
    JobStatus.PROCESSING: {
        JobStatus.QUEUED, JobStatus.COMPLETED,
        JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS,
    },
    JobStatus.FAILED: {JobStatus.QUEUED},
    JobStatus.COMPLETED: {JobStatus.QUEUED},
    JobStatus.COMPLETED_WITH_ERRORS: {JobStatus.QUEUED},
}

# Task transitions: (current, target) -> expected bool
# Built from transitions.py lines 81-97
_TASK_TRANSITIONS = {
    TaskStatus.PENDING: {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.QUEUED: {TaskStatus.PROCESSING, TaskStatus.CANCELLED},
    TaskStatus.PROCESSING: {
        TaskStatus.COMPLETED, TaskStatus.FAILED,
        TaskStatus.CANCELLED, TaskStatus.PENDING,
    },
    TaskStatus.FAILED: {TaskStatus.RETRYING, TaskStatus.PENDING_RETRY},
    TaskStatus.RETRYING: {TaskStatus.PROCESSING},
    TaskStatus.PENDING_RETRY: {TaskStatus.PROCESSING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}

ALL_JOB_STATUSES = list(JobStatus)
ALL_TASK_STATUSES = list(TaskStatus)

# Build exhaustive param lists
_JOB_PAIRS = [
    (current, target) for current in ALL_JOB_STATUSES for target in ALL_JOB_STATUSES
]

_TASK_PAIRS = [
    (current, target) for current in ALL_TASK_STATUSES for target in ALL_TASK_STATUSES
]


def _expected_job_transition(current: JobStatus, target: JobStatus) -> bool:
    """Compute expected result for a job transition."""
    if current == target:
        return True
    return target in _JOB_TRANSITIONS.get(current, set())


def _expected_task_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Compute expected result for a task transition."""
    if current == target:
        return True
    return target in _TASK_TRANSITIONS.get(current, set())


# ============================================================================
# TestJobTransitionsExhaustive
# ============================================================================

class TestJobTransitionsExhaustive:
    """Exhaustive tests for can_job_transition()."""

    @pytest.mark.parametrize("current,target", _JOB_PAIRS,
                             ids=[f"{c.value}->{t.value}" for c, t in _JOB_PAIRS])
    def test_transition_pair(self, current, target):
        expected = _expected_job_transition(current, target)
        result = can_job_transition(current, target)
        assert result == expected, (
            f"can_job_transition({current.value}, {target.value}) "
            f"returned {result}, expected {expected}"
        )

    @pytest.mark.parametrize("status", ALL_JOB_STATUSES,
                             ids=[s.value for s in ALL_JOB_STATUSES])
    def test_same_status_always_allowed(self, status):
        assert can_job_transition(status, status) is True

    def test_terminal_states_are_exactly_three(self):
        terminal = get_job_terminal_states()
        assert len(terminal) == 3
        assert set(terminal) == {
            JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS
        }

    def test_active_states_are_exactly_two(self):
        active = get_job_active_states()
        assert len(active) == 2
        assert set(active) == {JobStatus.QUEUED, JobStatus.PROCESSING}

    def test_active_and_terminal_are_disjoint(self):
        active = set(get_job_active_states())
        terminal = set(get_job_terminal_states())
        assert active & terminal == set()

    def test_active_plus_terminal_covers_all_statuses(self):
        active = set(get_job_active_states())
        terminal = set(get_job_terminal_states())
        assert active | terminal == set(ALL_JOB_STATUSES)

    def test_queued_has_exactly_two_valid_targets(self):
        valid = {t for t in ALL_JOB_STATUSES
                 if t != JobStatus.QUEUED and can_job_transition(JobStatus.QUEUED, t)}
        assert valid == {JobStatus.PROCESSING, JobStatus.FAILED}

    def test_processing_has_exactly_four_valid_targets(self):
        valid = {t for t in ALL_JOB_STATUSES
                 if t != JobStatus.PROCESSING and can_job_transition(JobStatus.PROCESSING, t)}
        assert valid == {
            JobStatus.QUEUED, JobStatus.COMPLETED,
            JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS,
        }

    @pytest.mark.parametrize("terminal", [
        JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS
    ])
    def test_terminal_states_can_recover_to_queued(self, terminal):
        assert can_job_transition(terminal, JobStatus.QUEUED) is True

    @pytest.mark.parametrize("status", ALL_JOB_STATUSES,
                             ids=[s.value for s in ALL_JOB_STATUSES])
    def test_is_job_terminal_agrees_with_terminal_list(self, status):
        assert is_job_terminal(status) == (status in get_job_terminal_states())


# ============================================================================
# TestTaskTransitionsExhaustive
# ============================================================================

class TestTaskTransitionsExhaustive:
    """Exhaustive tests for can_task_transition()."""

    @pytest.mark.parametrize("current,target", _TASK_PAIRS,
                             ids=[f"{c.value}->{t.value}" for c, t in _TASK_PAIRS])
    def test_transition_pair(self, current, target):
        expected = _expected_task_transition(current, target)
        result = can_task_transition(current, target)
        assert result == expected, (
            f"can_task_transition({current.value}, {target.value}) "
            f"returned {result}, expected {expected}"
        )

    @pytest.mark.parametrize("status", ALL_TASK_STATUSES,
                             ids=[s.value for s in ALL_TASK_STATUSES])
    def test_same_status_always_allowed(self, status):
        assert can_task_transition(status, status) is True

    def test_terminal_states_are_exactly_three(self):
        terminal = get_task_terminal_states()
        assert len(terminal) == 3
        assert set(terminal) == {
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
        }

    def test_active_states_are_exactly_five(self):
        active = get_task_active_states()
        assert len(active) == 5
        assert set(active) == {
            TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.PROCESSING,
            TaskStatus.RETRYING, TaskStatus.PENDING_RETRY,
        }

    def test_active_and_terminal_are_disjoint(self):
        active = set(get_task_active_states())
        terminal = set(get_task_terminal_states())
        assert active & terminal == set()

    def test_active_plus_terminal_covers_all(self):
        active = set(get_task_active_states())
        terminal = set(get_task_terminal_states())
        assert active | terminal == set(ALL_TASK_STATUSES)

    def test_pending_valid_targets_are_exactly(self):
        valid = {t for t in ALL_TASK_STATUSES
                 if t != TaskStatus.PENDING and can_task_transition(TaskStatus.PENDING, t)}
        assert valid == {TaskStatus.QUEUED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    def test_completed_has_no_valid_targets(self):
        """COMPLETED is truly terminal — no outgoing transitions."""
        valid = {t for t in ALL_TASK_STATUSES
                 if t != TaskStatus.COMPLETED and can_task_transition(TaskStatus.COMPLETED, t)}
        assert valid == set()

    def test_cancelled_has_no_valid_targets(self):
        """CANCELLED is truly terminal — no outgoing transitions."""
        valid = {t for t in ALL_TASK_STATUSES
                 if t != TaskStatus.CANCELLED and can_task_transition(TaskStatus.CANCELLED, t)}
        assert valid == set()

    def test_failed_has_recovery_paths(self):
        """FAILED can transition to RETRYING and PENDING_RETRY."""
        valid = {t for t in ALL_TASK_STATUSES
                 if t != TaskStatus.FAILED and can_task_transition(TaskStatus.FAILED, t)}
        assert valid == {TaskStatus.RETRYING, TaskStatus.PENDING_RETRY}

    def test_is_task_terminal_true_for_failed(self):
        """is_task_terminal(FAILED) returns True (for stage completion detection)."""
        assert is_task_terminal(TaskStatus.FAILED) is True

    def test_failed_can_still_transition_to_retrying(self):
        """
        FAILED is terminal for stage detection BUT has recovery transitions.
        These test different concepts: stage completion vs recovery paths.
        """
        assert is_task_terminal(TaskStatus.FAILED) is True
        assert can_task_transition(TaskStatus.FAILED, TaskStatus.RETRYING) is True

    @pytest.mark.parametrize("status", ALL_TASK_STATUSES,
                             ids=[s.value for s in ALL_TASK_STATUSES])
    def test_is_task_terminal_agrees_with_terminal_list(self, status):
        assert is_task_terminal(status) == (status in get_task_terminal_states())

    def test_processing_can_reset_to_pending(self):
        """Janitor can reset stuck PROCESSING tasks to PENDING."""
        assert can_task_transition(TaskStatus.PROCESSING, TaskStatus.PENDING) is True

    def test_queued_transitions_to_processing_and_cancelled(self):
        valid = {t for t in ALL_TASK_STATUSES
                 if t != TaskStatus.QUEUED and can_task_transition(TaskStatus.QUEUED, t)}
        assert valid == {TaskStatus.PROCESSING, TaskStatus.CANCELLED}


# ============================================================================
# TestJobRecordCanTransitionTo
# ============================================================================

class TestJobRecordCanTransitionTo:
    """
    Verify JobRecord.can_transition_to() behavior.

    KNOWN DIVERGENCE: JobRecord.can_transition_to() allows ANY transition
    from terminal states (COMPLETED, FAILED, COMPLETED_WITH_ERRORS) -> any target.
    can_job_transition() only allows terminal -> QUEUED.
    This is by design: JobRecord is more permissive for error recovery.
    """

    def test_queued_to_processing_allowed(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(job_id=valid_sha256, job_type="test", parameters={},
                           status=JobStatus.QUEUED)
        assert record.can_transition_to(JobStatus.PROCESSING) is True

    def test_queued_to_failed_allowed(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(job_id=valid_sha256, job_type="test", parameters={},
                           status=JobStatus.QUEUED)
        assert record.can_transition_to(JobStatus.FAILED) is True

    def test_processing_to_completed_allowed(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(job_id=valid_sha256, job_type="test", parameters={},
                           status=JobStatus.PROCESSING)
        assert record.can_transition_to(JobStatus.COMPLETED) is True

    def test_processing_to_queued_allowed(self, valid_sha256):
        """Stage advancement re-queuing."""
        from core.models.job import JobRecord
        record = JobRecord(job_id=valid_sha256, job_type="test", parameters={},
                           status=JobStatus.PROCESSING)
        assert record.can_transition_to(JobStatus.QUEUED) is True

    def test_terminal_states_allow_any_transition(self, valid_sha256):
        """JobRecord is more permissive: terminal states allow any target."""
        from core.models.job import JobRecord
        for terminal in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.COMPLETED_WITH_ERRORS]:
            record = JobRecord(job_id=valid_sha256, job_type="test", parameters={},
                               status=terminal)
            for target in ALL_JOB_STATUSES:
                assert record.can_transition_to(target) is True, (
                    f"JobRecord({terminal.value}).can_transition_to({target.value}) should be True"
                )

    def test_queued_to_completed_not_allowed(self, valid_sha256):
        """Cannot go directly from QUEUED to COMPLETED."""
        from core.models.job import JobRecord
        record = JobRecord(job_id=valid_sha256, job_type="test", parameters={},
                           status=JobStatus.QUEUED)
        assert record.can_transition_to(JobStatus.COMPLETED) is False


# ============================================================================
# TestTaskRecordCanTransitionTo
# ============================================================================

class TestTaskRecordCanTransitionTo:
    """Verify TaskRecord.can_transition_to() behavior."""

    def test_pending_to_queued(self, valid_sha256):
        from core.models.task import TaskRecord

        record = TaskRecord(
            task_id="test-task",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
            status="pending",
        )
        assert record.can_transition_to(TaskStatus.QUEUED) is True

    def test_processing_to_completed(self, valid_sha256):
        from core.models.task import TaskRecord

        record = TaskRecord(
            task_id="test-task",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
            status="processing",
        )
        assert record.can_transition_to(TaskStatus.COMPLETED) is True

    def test_completed_allows_retry(self, valid_sha256):
        """TaskRecord.can_transition_to allows restart from terminal states."""
        from core.models.task import TaskRecord

        record = TaskRecord(
            task_id="test-task",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
            status="completed",
        )
        # TaskRecord allows transitions from terminal states (recovery)
        assert record.can_transition_to(TaskStatus.QUEUED) is True
