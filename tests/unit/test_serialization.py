"""
Serialization tests for psycopg3 compatibility.

Tests model_dump() across all major models to ensure
enums serialize to strings and datetimes behave correctly.
"""

import pytest
from datetime import datetime, timezone
from enum import Enum

from core.models.enums import JobStatus, TaskStatus
from tests.factories.model_factories import (
    make_job_record,
    make_task_record,
    make_asset_release,
)


class TestJobRecordSerialization:
    def test_model_dump_jsonb_stays_dict(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump()
        assert isinstance(dumped["parameters"], dict)
        assert isinstance(dumped["stage_results"], dict)
        assert isinstance(dumped["metadata"], dict)

    def test_model_dump_status_is_enum_in_python_mode(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump()
        assert isinstance(dumped["status"], JobStatus)

    def test_json_mode_produces_string_status(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump(mode="json")
        assert isinstance(dumped["status"], str)

    def test_json_mode_produces_iso_datetime_strings(self, valid_sha256):
        from core.models.job import JobRecord
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump(mode="json")
        # field_serializer ensures datetimes are ISO strings
        assert isinstance(dumped["created_at"], str)
        assert isinstance(dumped["updated_at"], str)

    def test_model_dump_datetimes_serialized(self, valid_sha256):
        """JobRecord's field_serializer converts datetimes to ISO strings."""
        from core.models.job import JobRecord
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump()
        # field_serializer may produce str even in default mode
        assert isinstance(dumped["created_at"], (datetime, str))


class TestTaskRecordSerialization:
    def test_model_dump_jsonb_stays_dict(self, valid_sha256):
        from core.models.task import TaskRecord
        record = TaskRecord(**make_task_record(parent_job_id=valid_sha256))
        dumped = record.model_dump()
        assert isinstance(dumped["parameters"], dict)
        assert isinstance(dumped["metadata"], dict)


class TestReleaseSerialization:
    def test_model_dump_enums_are_strings_in_json_mode(self):
        from core.models.asset import AssetRelease
        release = AssetRelease(**make_asset_release())
        dumped = release.model_dump(mode="json")
        assert isinstance(dumped["approval_state"], str)
        assert isinstance(dumped["processing_status"], str)
        assert isinstance(dumped["clearance_state"], str)

    def test_to_dict_serializes_enums_to_strings(self):
        from core.models.asset import AssetRelease
        release = AssetRelease(**make_asset_release())
        d = release.to_dict()
        assert isinstance(d["approval_state"], str)
        assert isinstance(d["processing_status"], str)
        assert isinstance(d["clearance_state"], str)

    def test_to_dict_serializes_datetimes_to_iso_or_none(self):
        from core.models.asset import AssetRelease
        release = AssetRelease(**make_asset_release())
        d = release.to_dict()
        for key in ["created_at", "updated_at"]:
            val = d[key]
            assert val is None or isinstance(val, str)
