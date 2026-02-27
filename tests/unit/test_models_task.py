"""
TaskRecord model tests — defaults, validation, serialization.
"""

import pytest
from datetime import datetime

from core.models.task import TaskRecord
from core.models.enums import TaskStatus
from tests.factories.model_factories import make_task_record


class TestTaskRecordDefaults:

    def test_default_status_is_pending(self, valid_sha256):
        record = TaskRecord(
            task_id="test-task-1",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
        )
        assert record.status == TaskStatus.PENDING

    def test_default_retry_count_is_zero(self, valid_sha256):
        record = TaskRecord(
            task_id="test-task-1",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
        )
        assert record.retry_count == 0


class TestTaskRecordValidation:

    def test_retry_count_cannot_be_negative(self, valid_sha256):
        with pytest.raises(Exception):
            TaskRecord(
                task_id="test-task-1",
                parent_job_id=valid_sha256,
                job_type="test",
                task_type="test_handler",
                stage=1,
                retry_count=-1,
            )

    def test_stage_must_be_positive(self, valid_sha256):
        with pytest.raises(Exception):
            TaskRecord(
                task_id="test-task-1",
                parent_job_id=valid_sha256,
                job_type="test",
                task_type="test_handler",
                stage=0,
            )

    def test_target_queue_is_optional(self, valid_sha256):
        record = TaskRecord(
            task_id="test-task-1",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
        )
        assert record.target_queue is None

    def test_executed_by_app_is_optional(self, valid_sha256):
        record = TaskRecord(
            task_id="test-task-1",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="test_handler",
            stage=1,
        )
        assert record.executed_by_app is None


class TestTaskRecordSerialization:

    def test_model_dump_preserves_jsonb_as_dict(self, valid_sha256):
        record = TaskRecord(**make_task_record(parent_job_id=valid_sha256))
        dumped = record.model_dump()
        assert isinstance(dumped["parameters"], dict)
        assert isinstance(dumped["metadata"], dict)

    def test_json_mode_serializes_status(self, valid_sha256):
        record = TaskRecord(**make_task_record(parent_job_id=valid_sha256))
        dumped = record.model_dump(mode="json")
        assert isinstance(dumped["status"], str)

    def test_task_type_normalized_to_lowercase(self, valid_sha256):
        record = TaskRecord(
            task_id="test-task-1",
            parent_job_id=valid_sha256,
            job_type="test",
            task_type="My-Handler",
            stage=1,
        )
        assert record.task_type == "my_handler"
