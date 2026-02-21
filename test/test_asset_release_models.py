# ============================================================================
# TESTS FOR V0.9 ASSET/RELEASE ENTITY MODELS
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Test - Dry-run tests for Asset V2 model (no database required)
# PURPOSE: Validate Asset model as stable identity container
# LAST_REVIEWED: 21 FEB 2026
# EXPORTS: TestAssetModel
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
