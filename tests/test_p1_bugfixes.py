"""Tests for P1 bug fixes from Architecture Review 24 FEB 2026."""
import pytest
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestStageResultContract:
    """C1.1: StageResultContract.from_task_results() must exist and work."""

    def test_from_task_results_classmethod_exists(self):
        from core.models.results import StageResultContract
        assert hasattr(StageResultContract, 'from_task_results')
        assert callable(StageResultContract.from_task_results)

    def test_from_task_results_all_success(self):
        from core.models.results import StageResultContract, TaskResult
        from core.models.enums import TaskStatus
        from datetime import datetime, timezone

        results = [
            TaskResult(
                task_id="t1", task_type="test",
                status=TaskStatus.COMPLETED,
                timestamp=datetime.now(timezone.utc)
            ),
            TaskResult(
                task_id="t2", task_type="test",
                status=TaskStatus.COMPLETED,
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        stage = StageResultContract.from_task_results(1, results)
        assert stage.status == 'completed'
        assert stage.task_count == 2
        assert stage.successful_count == 2
        assert stage.failed_count == 0

    def test_from_task_results_all_fail(self):
        from core.models.results import StageResultContract, TaskResult
        from core.models.enums import TaskStatus
        from datetime import datetime, timezone

        results = [
            TaskResult(
                task_id="t1", task_type="test",
                status=TaskStatus.FAILED,
                error_details="Error",
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        stage = StageResultContract.from_task_results(1, results)
        assert stage.status == 'failed'
        assert stage.failed_count == 1

    def test_from_task_results_mixed(self):
        from core.models.results import StageResultContract, TaskResult
        from core.models.enums import TaskStatus
        from datetime import datetime, timezone

        results = [
            TaskResult(
                task_id="t1", task_type="test",
                status=TaskStatus.COMPLETED,
                timestamp=datetime.now(timezone.utc)
            ),
            TaskResult(
                task_id="t2", task_type="test",
                status=TaskStatus.FAILED,
                error_details="Something broke",
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        stage = StageResultContract.from_task_results(1, results)
        assert stage.status == 'completed_with_errors'
        assert stage.successful_count == 1
        assert stage.failed_count == 1
        assert stage.error_summary == ["Something broke"]


class TestErrorDetailsAttribute:
    """C1.2: calculations.py must use error_details, not error_message."""

    def test_get_error_summary_uses_error_details(self):
        from core.logic.calculations import get_error_summary
        from core.models.results import TaskResult
        from core.models.enums import TaskStatus
        from datetime import datetime, timezone

        results = [
            TaskResult(
                task_id="t1", task_type="test",
                status=TaskStatus.FAILED,
                error_details="Error A",
                timestamp=datetime.now(timezone.utc)
            ),
            TaskResult(
                task_id="t2", task_type="test",
                status=TaskStatus.FAILED,
                error_details="Error B",
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        errors = get_error_summary(results)
        assert errors == ["Error A", "Error B"]

    def test_get_error_summary_deduplicates(self):
        from core.logic.calculations import get_error_summary
        from core.models.results import TaskResult
        from core.models.enums import TaskStatus
        from datetime import datetime, timezone

        results = [
            TaskResult(
                task_id="t1", task_type="test",
                status=TaskStatus.FAILED,
                error_details="Same error",
                timestamp=datetime.now(timezone.utc)
            ),
            TaskResult(
                task_id="t2", task_type="test",
                status=TaskStatus.FAILED,
                error_details="Same error",
                timestamp=datetime.now(timezone.utc)
            ),
        ]
        errors = get_error_summary(results)
        assert errors == ["Same error"]  # Deduplicated


class TestStateTransitions:
    """C1.3: transitions.py must agree with JobRecord.can_transition_to()."""

    def test_processing_to_queued_allowed(self):
        """Stage advancement re-queuing must be allowed."""
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.PROCESSING, JobStatus.QUEUED)

    def test_failed_to_queued_recovery_allowed(self):
        """Error recovery from terminal states must be allowed."""
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.FAILED, JobStatus.QUEUED)

    def test_completed_to_queued_recovery_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.COMPLETED, JobStatus.QUEUED)

    def test_completed_with_errors_to_queued_recovery_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.COMPLETED_WITH_ERRORS, JobStatus.QUEUED)

    def test_queued_to_processing_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.QUEUED, JobStatus.PROCESSING)

    def test_processing_to_completed_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.PROCESSING, JobStatus.COMPLETED)

    def test_same_status_always_allowed(self):
        from core.logic.transitions import can_job_transition
        from core.models.enums import JobStatus
        assert can_job_transition(JobStatus.PROCESSING, JobStatus.PROCESSING)
