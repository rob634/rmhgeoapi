"""
Asset model tests — generate_asset_id, model validation, helper methods.

Anti-overfitting: Property assertions (32 hex chars), not exact values.
Multiple different inputs tested for determinism and collision resistance.
"""

import pytest
import re

from core.models.asset import Asset
from tests.factories.model_factories import make_asset


class TestAssetGenerateId:
    """Tests for Asset.generate_asset_id() static method."""

    def test_result_is_32_char_hex(self):
        result = Asset.generate_asset_id("ddh", "floods", "jakarta")
        assert len(result) == 32
        assert re.match(r"^[0-9a-f]{32}$", result)

    def test_deterministic(self):
        a = Asset.generate_asset_id("ddh", "floods", "jakarta")
        b = Asset.generate_asset_id("ddh", "floods", "jakarta")
        assert a == b

    def test_different_inputs_different_ids(self):
        id1 = Asset.generate_asset_id("ddh", "floods", "jakarta")
        id2 = Asset.generate_asset_id("ddh", "floods", "manila")
        id3 = Asset.generate_asset_id("ddh", "elevation", "jakarta")
        assert len({id1, id2, id3}) == 3

    def test_order_matters(self):
        id1 = Asset.generate_asset_id("ddh", "alpha", "beta")
        id2 = Asset.generate_asset_id("ddh", "beta", "alpha")
        assert id1 != id2

    def test_separator_prevents_collisions(self):
        """("a","bc","d") != ("ab","c","d") due to pipe separator."""
        id1 = Asset.generate_asset_id("a", "bc", "d")
        id2 = Asset.generate_asset_id("ab", "c", "d")
        assert id1 != id2

    def test_empty_platform_id_raises(self):
        with pytest.raises(ValueError, match="platform_id"):
            Asset.generate_asset_id("", "floods", "jakarta")

    def test_empty_dataset_id_raises(self):
        with pytest.raises(ValueError, match="dataset_id"):
            Asset.generate_asset_id("ddh", "", "jakarta")

    def test_empty_resource_id_raises(self):
        with pytest.raises(ValueError, match="resource_id"):
            Asset.generate_asset_id("ddh", "floods", "")


class TestAssetModel:
    """Tests for Asset Pydantic model validation and helpers."""

    def test_is_active_when_not_deleted(self):
        asset = Asset(**make_asset(deleted_at=None))
        assert asset.is_active() is True

    def test_not_active_when_deleted(self):
        from datetime import datetime, timezone
        asset = Asset(**make_asset(deleted_at=datetime.now(timezone.utc)))
        assert asset.is_active() is False

    def test_data_type_rejects_invalid(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            Asset(**make_asset(data_type="pointcloud"))

    def test_data_type_accepts_raster(self):
        asset = Asset(**make_asset(data_type="raster"))
        assert asset.data_type == "raster"

    def test_data_type_accepts_vector(self):
        asset = Asset(**make_asset(data_type="vector"))
        assert asset.data_type == "vector"

    def test_release_count_cannot_be_negative(self):
        with pytest.raises(Exception):
            Asset(**make_asset(release_count=-1))

    def test_to_dict_excludes_approval_fields(self):
        asset = Asset(**make_asset())
        d = asset.to_dict()
        assert "approval_state" not in d
        assert "clearance_state" not in d
        assert "processing_status" not in d

    def test_to_dict_includes_identity_triple(self):
        asset = Asset(**make_asset())
        d = asset.to_dict()
        assert "platform_id" in d
        assert "dataset_id" in d
        assert "resource_id" in d
        assert "asset_id" in d
