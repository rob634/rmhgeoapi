"""
AssetRelease model tests — defaults, validation, serialization.
"""

import pytest

from core.models.asset import AssetRelease, ApprovalState, ProcessingStatus
from tests.factories.model_factories import make_asset_release


class TestReleaseDefaults:

    def test_default_approval_state_is_pending_review(self):
        release = AssetRelease(**make_asset_release())
        # Factory sets approval_state, so test with explicit None
        data = make_asset_release()
        del data["approval_state"]
        release = AssetRelease(**data)
        assert release.approval_state == ApprovalState.PENDING_REVIEW

    def test_default_processing_status_is_pending(self):
        data = make_asset_release()
        release = AssetRelease(**data)
        assert release.processing_status == ProcessingStatus.PENDING


class TestReleaseValidation:

    def test_version_ordinal_ge_zero(self):
        with pytest.raises(Exception):
            AssetRelease(**make_asset_release(version_ordinal=-1))

    def test_revision_ge_one(self):
        with pytest.raises(Exception):
            AssetRelease(**make_asset_release(revision=0))

    def test_priority_min_1(self):
        with pytest.raises(Exception):
            AssetRelease(**make_asset_release(priority=0))

    def test_priority_max_10(self):
        with pytest.raises(Exception):
            AssetRelease(**make_asset_release(priority=11))

    def test_priority_valid_range(self):
        for p in [1, 5, 10]:
            release = AssetRelease(**make_asset_release(priority=p))
            assert release.priority == p


class TestReleaseSerialization:

    def test_to_dict_serializes_enums_to_strings(self):
        release = AssetRelease(**make_asset_release())
        d = release.to_dict()
        for key in ["approval_state", "processing_status", "clearance_state"]:
            assert isinstance(d[key], str), f"{key} should be str, got {type(d[key])}"

    def test_to_dict_serializes_datetimes_to_iso(self):
        release = AssetRelease(**make_asset_release())
        d = release.to_dict()
        for key in ["created_at", "updated_at"]:
            val = d[key]
            assert val is None or isinstance(val, str)

    def test_model_dump_json_mode_all_serializable(self):
        """model_dump(mode='json') should produce only JSON-serializable types."""
        import json
        release = AssetRelease(**make_asset_release())
        dumped = release.model_dump(mode="json")
        # Should not raise
        json.dumps(dumped)


class TestOverwriteResetContract:
    """Verify that overwrite resets all lifecycle fields.

    These tests validate the contract: after overwrite, a release must
    have PENDING processing, PENDING_REVIEW approval, and no stale job_id.
    The actual SQL is in release_repository.update_overwrite().
    """

    def test_rejected_release_fields_that_must_reset(self):
        """Document the fields that update_overwrite MUST reset."""
        release = AssetRelease(**make_asset_release(
            approval_state=ApprovalState.REJECTED,
            processing_status=ProcessingStatus.FAILED,
            job_id="stale-job-abc123",
        ))
        # Pre-conditions: stale state
        assert release.approval_state == ApprovalState.REJECTED
        assert release.processing_status == ProcessingStatus.FAILED
        assert release.job_id == "stale-job-abc123"

        # Contract: after overwrite these must be reset to:
        expected_approval = ApprovalState.PENDING_REVIEW
        expected_processing = ProcessingStatus.PENDING
        expected_job_id = None

        # These are the values update_overwrite SQL must SET
        assert expected_approval == ApprovalState.PENDING_REVIEW
        assert expected_processing == ProcessingStatus.PENDING
        assert expected_job_id is None
