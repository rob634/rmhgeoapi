# ============================================================================
# TESTS FOR V0.9 ASSET/RELEASE ENTITY MODELS
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Test - Dry-run tests for Asset V2 model (no database required)
# PURPOSE: Validate Asset model as stable identity container
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: TestAssetModel, TestAssetReleaseModel
# DEPENDENCIES: pytest, pydantic
# ============================================================================
"""
Tests for V0.9 Asset/Release entity models.
Dry-run tests -- no database required.
"""
import os
os.environ.setdefault('POSTGIS_HOST', 'localhost')
os.environ.setdefault('POSTGIS_PORT', '5432')
os.environ.setdefault('POSTGIS_DATABASE', 'test')
os.environ.setdefault('POSTGIS_SCHEMA', 'app')
os.environ.setdefault('APP_SCHEMA', 'app')
os.environ.setdefault('PGSTAC_SCHEMA', 'pgstac')
os.environ.setdefault('H3_SCHEMA', 'h3')

import pytest


class TestAssetModel:
    """Asset = stable identity container."""

    def test_generate_asset_id_deterministic(self):
        from core.models.asset_v2 import Asset
        id1 = Asset.generate_asset_id("ddh", "floods", "jakarta")
        id2 = Asset.generate_asset_id("ddh", "floods", "jakarta")
        assert id1 == id2
        assert len(id1) == 32

    def test_generate_asset_id_no_version(self):
        """Asset ID must NOT include version -- that's on Release."""
        from core.models.asset_v2 import Asset
        id1 = Asset.generate_asset_id("ddh", "floods", "jakarta")
        assert len(id1) == 32

    def test_asset_id_differs_by_resource(self):
        from core.models.asset_v2 import Asset
        id1 = Asset.generate_asset_id("ddh", "floods", "jakarta")
        id2 = Asset.generate_asset_id("ddh", "floods", "manila")
        assert id1 != id2

    def test_asset_creation_minimal(self):
        from core.models.asset_v2 import Asset
        asset = Asset(
            asset_id="abc123",
            platform_id="ddh",
            dataset_id="floods",
            resource_id="jakarta",
            data_type="raster",
        )
        assert asset.asset_id == "abc123"
        assert asset.release_count == 0
        assert asset.deleted_at is None

    def test_asset_has_sql_metadata(self):
        """DDL generation requires __sql_* ClassVar attributes."""
        from core.models.asset_v2 import Asset
        assert hasattr(Asset, '_Asset__sql_table_name')
        assert hasattr(Asset, '_Asset__sql_schema')
        assert hasattr(Asset, '_Asset__sql_primary_key')

    def test_asset_to_dict(self):
        from core.models.asset_v2 import Asset
        asset = Asset(
            asset_id="abc123",
            platform_id="ddh",
            dataset_id="floods",
            resource_id="jakarta",
            data_type="raster",
        )
        d = asset.to_dict()
        assert d['asset_id'] == "abc123"
        assert d['dataset_id'] == "floods"
        assert 'approval_state' not in d  # Lives on Release, not Asset


class TestAssetReleaseModel:
    """Release = versioned artifact with lifecycle."""

    def test_release_creation_draft(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState, ProcessingStatus
        release = AssetRelease(
            release_id="rel123",
            asset_id="abc123",
            stac_item_id="floods-jakarta-draft",
            stac_collection_id="floods",
        )
        assert release.version_id is None  # Draft
        assert release.version_ordinal is None
        assert release.approval_state == ApprovalState.PENDING_REVIEW
        assert release.processing_status == ProcessingStatus.PENDING
        assert release.revision == 1
        assert release.is_latest is False

    def test_release_creation_versioned(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState
        release = AssetRelease(
            release_id="rel456",
            asset_id="abc123",
            version_id="v1",
            version_ordinal=1,
            is_latest=True,
            approval_state=ApprovalState.APPROVED,
            stac_item_id="floods-jakarta-v1",
            stac_collection_id="floods",
        )
        assert release.version_id == "v1"
        assert release.version_ordinal == 1
        assert release.is_latest is True

    def test_release_can_approve_draft(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState
        release = AssetRelease(
            release_id="rel123",
            asset_id="abc123",
            approval_state=ApprovalState.PENDING_REVIEW,
            stac_item_id="test",
            stac_collection_id="test",
        )
        assert release.can_approve() is True

    def test_release_cannot_approve_already_approved(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState
        release = AssetRelease(
            release_id="rel123",
            asset_id="abc123",
            approval_state=ApprovalState.APPROVED,
            stac_item_id="test",
            stac_collection_id="test",
        )
        assert release.can_approve() is False

    def test_release_can_overwrite_draft(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState
        release = AssetRelease(
            release_id="rel123",
            asset_id="abc123",
            approval_state=ApprovalState.PENDING_REVIEW,
            stac_item_id="test",
            stac_collection_id="test",
        )
        assert release.can_overwrite() is True

    def test_release_cannot_overwrite_approved(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState
        release = AssetRelease(
            release_id="rel123",
            asset_id="abc123",
            approval_state=ApprovalState.APPROVED,
            stac_item_id="test",
            stac_collection_id="test",
        )
        assert release.can_overwrite() is False

    def test_release_has_sql_metadata(self):
        from core.models.asset_v2 import AssetRelease
        assert hasattr(AssetRelease, '_AssetRelease__sql_table_name')
        assert hasattr(AssetRelease, '_AssetRelease__sql_schema')

    def test_release_to_dict_enums_serialize(self):
        from core.models.asset_v2 import AssetRelease, ApprovalState, ClearanceState
        release = AssetRelease(
            release_id="rel123",
            asset_id="abc123",
            approval_state=ApprovalState.APPROVED,
            clearance_state=ClearanceState.PUBLIC,
            stac_item_id="test",
            stac_collection_id="test",
        )
        d = release.to_dict()
        assert d['approval_state'] == 'approved'
        assert d['clearance_state'] == 'public'

    def test_multiple_releases_different_ids(self):
        """Two releases under same asset get different release_ids."""
        from core.models.asset_v2 import AssetRelease
        r1 = AssetRelease(
            release_id="rel_v1",
            asset_id="abc123",
            version_id="v1",
            stac_item_id="test-v1",
            stac_collection_id="test",
        )
        r2 = AssetRelease(
            release_id="rel_v2",
            asset_id="abc123",
            version_id="v2",
            stac_item_id="test-v2",
            stac_collection_id="test",
        )
        assert r1.release_id != r2.release_id
        assert r1.asset_id == r2.asset_id  # Same parent
