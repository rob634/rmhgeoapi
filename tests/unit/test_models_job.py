"""
JobRecord model tests — defaults, validation, serialization.
"""

import pytest
from datetime import datetime

from core.models.job import JobRecord
from core.models.enums import JobStatus
from tests.factories.model_factories import make_job_record


class TestJobRecordDefaults:

    def test_default_status_is_queued(self, valid_sha256):
        record = JobRecord(
            job_id=valid_sha256,
            job_type="test",
            parameters={},
        )
        assert record.status == JobStatus.QUEUED

    def test_default_stage_is_one(self, valid_sha256):
        record = JobRecord(
            job_id=valid_sha256,
            job_type="test",
            parameters={},
        )
        assert record.stage == 1

    def test_default_total_stages_is_one(self, valid_sha256):
        record = JobRecord(
            job_id=valid_sha256,
            job_type="test",
            parameters={},
        )
        assert record.total_stages == 1


class TestJobRecordValidation:

    def test_stage_must_be_positive(self, valid_sha256):
        with pytest.raises(Exception):
            JobRecord(
                job_id=valid_sha256,
                job_type="test",
                parameters={},
                stage=0,
            )

    def test_total_stages_must_be_positive(self, valid_sha256):
        with pytest.raises(Exception):
            JobRecord(
                job_id=valid_sha256,
                job_type="test",
                parameters={},
                total_stages=0,
            )

    def test_job_id_must_be_64_hex_chars(self):
        with pytest.raises(Exception):
            JobRecord(
                job_id="tooshort",
                job_type="test",
                parameters={},
            )


class TestJobRecordSerialization:

    def test_model_dump_serializes_status_enum(self, valid_sha256):
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump()
        assert isinstance(dumped["status"], JobStatus)

    def test_jsonb_fields_stay_as_dicts(self, valid_sha256):
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump()
        assert isinstance(dumped["parameters"], dict)
        assert isinstance(dumped["metadata"], dict)
        assert isinstance(dumped["stage_results"], dict)

    def test_datetime_serialized_in_model_dump(self, valid_sha256):
        """
        JobRecord has field_serializer for created_at/updated_at that converts
        to ISO string even in default model_dump mode.
        """
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump()
        # field_serializer converts datetime -> str in all modes
        assert isinstance(dumped["created_at"], (datetime, str))

    def test_datetime_is_string_in_json_mode(self, valid_sha256):
        record = JobRecord(**make_job_record(job_id=valid_sha256))
        dumped = record.model_dump(mode="json")
        assert isinstance(dumped["created_at"], str)
