"""
Enum count and property assertions.

Anti-overfitting: Count assertions catch silent additions/removals.
"""

import pytest

from core.models.enums import JobStatus, TaskStatus, StageStatus
from core.models.asset import ApprovalState, ClearanceState, ProcessingStatus


class TestJobStatusEnum:
    def test_has_exactly_5_values(self):
        assert len(JobStatus) == 5

    def test_all_values_are_lowercase(self):
        for status in JobStatus:
            assert status.value == status.value.lower()

    def test_expected_members(self):
        names = {s.name for s in JobStatus}
        assert names == {"QUEUED", "PROCESSING", "COMPLETED", "FAILED", "COMPLETED_WITH_ERRORS"}


class TestTaskStatusEnum:
    def test_has_exactly_8_values(self):
        assert len(TaskStatus) == 8

    def test_all_values_are_lowercase(self):
        for status in TaskStatus:
            assert status.value == status.value.lower()

    def test_expected_members(self):
        names = {s.name for s in TaskStatus}
        assert names == {
            "PENDING", "QUEUED", "PROCESSING", "COMPLETED",
            "FAILED", "RETRYING", "PENDING_RETRY", "CANCELLED",
        }


class TestStageStatusEnum:
    def test_has_exactly_5_values(self):
        assert len(StageStatus) == 5

    def test_expected_members(self):
        names = {s.name for s in StageStatus}
        assert names == {"PENDING", "PROCESSING", "COMPLETED", "FAILED", "COMPLETED_WITH_ERRORS"}


class TestApprovalStateEnum:
    def test_has_exactly_4_values(self):
        assert len(ApprovalState) == 4

    def test_is_str_enum(self):
        assert isinstance(ApprovalState.PENDING_REVIEW, str)

    def test_rejects_invalid_string(self):
        with pytest.raises(ValueError):
            ApprovalState("nonexistent_state")


class TestClearanceStateEnum:
    def test_has_exactly_3_values(self):
        assert len(ClearanceState) == 3

    def test_is_str_enum(self):
        assert isinstance(ClearanceState.UNCLEARED, str)


class TestProcessingStatusEnum:
    def test_has_exactly_4_values(self):
        assert len(ProcessingStatus) == 4

    def test_is_str_enum(self):
        assert isinstance(ProcessingStatus.COMPLETED, str)

    def test_expected_members(self):
        names = {s.name for s in ProcessingStatus}
        assert names == {"PENDING", "PROCESSING", "COMPLETED", "FAILED"}
