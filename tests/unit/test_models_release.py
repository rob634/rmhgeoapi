"""
AssetRelease model tests — defaults, validation, serialization.
"""

import pytest
from enum import Enum

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
