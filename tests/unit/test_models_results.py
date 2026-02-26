"""
StageResultContract.from_task_results() tests.

Tests aggregation logic: all success, all failed, mixed,
empty, single, and error deduplication.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from core.models.results import TaskResult, StageResultContract
from core.models.enums import TaskStatus
from tests.factories.model_factories import make_task_result


def _make_result(status: TaskStatus, error: str = None) -> TaskResult:
    """Helper to build a TaskResult with specific status."""
    return TaskResult(**make_task_result(
        status=status,
        error_details=error,
        result_data={"ok": True} if status == TaskStatus.COMPLETED else None,
    ))


def _mock_error_summary(results):
    """Standalone mock for get_error_summary to avoid context module imports."""
    errors = []
    seen = set()
    for r in results:
        if r.error_details and r.error_details not in seen:
            errors.append(r.error_details)
            seen.add(r.error_details)
    return errors if errors else None


class TestStageResultFromTaskResults:

    @pytest.fixture(autouse=True)
    def _patch_error_summary(self):
        with patch("core.logic.calculations.get_error_summary", _mock_error_summary):
            yield

    def test_all_success_status_completed(self):
        results = [_make_result(TaskStatus.COMPLETED) for _ in range(3)]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.status == "completed"
        assert stage.successful_count == 3
        assert stage.failed_count == 0

    def test_all_failed_status_failed(self):
        results = [_make_result(TaskStatus.FAILED, error=f"err-{i}") for i in range(3)]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.status == "failed"
        assert stage.successful_count == 0
        assert stage.failed_count == 3

    def test_mixed_status_completed_with_errors(self):
        results = [
            _make_result(TaskStatus.COMPLETED),
            _make_result(TaskStatus.FAILED, error="some error"),
        ]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.status == "completed_with_errors"
        assert stage.successful_count == 1
        assert stage.failed_count == 1

    def test_task_count_matches_input_length(self):
        n = 5
        results = [_make_result(TaskStatus.COMPLETED) for _ in range(n)]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.task_count == n

    def test_single_success(self):
        results = [_make_result(TaskStatus.COMPLETED)]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.status == "completed"
        assert stage.task_count == 1

    def test_single_failure(self):
        results = [_make_result(TaskStatus.FAILED, error="boom")]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.status == "failed"
        assert stage.task_count == 1

    def test_error_summary_deduplicates(self):
        results = [
            _make_result(TaskStatus.FAILED, error="same error"),
            _make_result(TaskStatus.FAILED, error="same error"),
            _make_result(TaskStatus.FAILED, error="different error"),
        ]
        stage = StageResultContract.from_task_results(stage_number=1, task_results=results)
        assert stage.error_summary is not None
        assert len(stage.error_summary) == 2

    def test_stage_number_preserved(self):
        results = [_make_result(TaskStatus.COMPLETED)]
        stage = StageResultContract.from_task_results(stage_number=3, task_results=results)
        assert stage.stage == 3
