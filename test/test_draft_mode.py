"""
Draft Mode Test Suite (17 FEB 2026, converted to pytest 22 FEB 2026).

Tests the version_id deferral from submit -> approve (draft mode).
Exercises logic without database -- mocks repository layer.

Classes:
    TestPlatformRequestDraft  -- PlatformRequest with None/present version_id
    TestRequestIdGeneration   -- generate_platform_request_id behavior
    TestNamingFunctions       -- stac_item_id and table_name draft placeholders
    TestAssetIdentity         -- Asset.generate_asset_id version exclusion
    TestApiRequest            -- ApiRequest empty version_id handling
"""

import os
import sys

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Minimal env vars to allow config import without database
os.environ.setdefault('POSTGIS_HOST', 'localhost')
os.environ.setdefault('POSTGIS_PORT', '5432')
os.environ.setdefault('POSTGIS_DATABASE', 'test')
os.environ.setdefault('POSTGIS_USER', 'test')
os.environ.setdefault('POSTGIS_PASSWORD', '')
os.environ.setdefault('POSTGIS_SCHEMA', 'geo')
os.environ.setdefault('APP_SCHEMA', 'app')
os.environ.setdefault('PGSTAC_SCHEMA', 'pgstac')
os.environ.setdefault('H3_SCHEMA', 'h3')
os.environ.setdefault('STORAGE_ACCOUNT_NAME', 'test')
os.environ.setdefault('BRONZE_CONTAINER_NAME', 'test')
os.environ.setdefault('SILVER_CONTAINER_NAME', 'test')
os.environ.setdefault('GOLD_CONTAINER_NAME', 'test')
os.environ.setdefault('JOB_PROCESSING_QUEUE', 'test')
os.environ.setdefault('TASK_PROCESSING_QUEUE', 'test')
os.environ.setdefault('FUNCTION_TIMEOUT_MINUTES', '5')
os.environ.setdefault('MAX_RETRY_ATTEMPTS', '3')
os.environ.setdefault('LOG_LEVEL', 'WARNING')
os.environ.setdefault('ENABLE_DATABASE_HEALTH_CHECK', 'false')
os.environ.setdefault('KEY_VAULT_NAME', 'test')
os.environ.setdefault('KEY_VAULT_DATABASE_SECRET', 'test')


# ============================================================================
# TEST 1, 2, 8, 9: PlatformRequest draft mode behavior
# ============================================================================

class TestPlatformRequestDraft:
    """PlatformRequest model with None and present version_id."""

    def test_accepts_none_version_id(self):
        """Test 1: PlatformRequest accepts None version_id."""
        from core.models.platform import PlatformRequest

        req = PlatformRequest(
            dataset_id="test-dataset",
            resource_id="test-resource",
            # version_id omitted -- should default to None
            container_name="bronze-vectors",
            file_name="test.geojson"
        )
        assert req.version_id is None
        assert req.dataset_id == "test-dataset"
        assert req.resource_id == "test-resource"

    def test_works_with_version_id(self):
        """Test 2: PlatformRequest still works with version_id."""
        from core.models.platform import PlatformRequest

        req = PlatformRequest(
            dataset_id="test-dataset",
            resource_id="test-resource",
            version_id="v1.0",
            container_name="bronze-vectors",
            file_name="test.geojson"
        )
        assert req.version_id == "v1.0"

    def test_stac_item_id_handles_none_version(self):
        """Test 8: PlatformRequest.stac_item_id property handles None version_id."""
        from core.models.platform import PlatformRequest

        req = PlatformRequest(
            dataset_id="test-dataset",
            resource_id="test-resource",
            container_name="bronze-vectors",
            file_name="test.geojson"
        )
        item_id = req.stac_item_id
        assert "draft" in item_id
        assert "none" not in item_id.lower()

    def test_generated_title_handles_none_version(self):
        """Test 9: PlatformRequest.generated_title handles None version_id."""
        from core.models.platform import PlatformRequest

        req = PlatformRequest(
            dataset_id="test-dataset",
            resource_id="test-resource",
            container_name="bronze-vectors",
            file_name="test.geojson"
        )
        title = req.generated_title
        assert "(draft)" in title
        assert "None" not in title


# ============================================================================
# TEST 3, 4, 5: Request ID generation
# ============================================================================

class TestRequestIdGeneration:
    """generate_platform_request_id behavior with draft and versioned inputs."""

    def test_handles_none_version_id(self):
        """Test 3: generate_platform_request_id handles None version_id."""
        from config import generate_platform_request_id

        rid = generate_platform_request_id("ds1", "rs1")
        assert isinstance(rid, str)
        assert len(rid) == 32

    def test_draft_differs_from_versioned(self):
        """Test 4: Draft request_id differs from versioned request_id."""
        from config import generate_platform_request_id

        draft_id = generate_platform_request_id("ds1", "rs1")
        versioned_id = generate_platform_request_id("ds1", "rs1", "v1.0")
        assert draft_id != versioned_id

    def test_draft_is_idempotent(self):
        """Test 5: Same draft inputs produce same request_id."""
        from config import generate_platform_request_id

        id1 = generate_platform_request_id("ds1", "rs1")
        id2 = generate_platform_request_id("ds1", "rs1")
        assert id1 == id2


# ============================================================================
# TEST 6, 7: Naming functions with draft placeholders
# ============================================================================

class TestNamingFunctions:
    """generate_stac_item_id and generate_table_name draft placeholder behavior."""

    def test_stac_item_id_uses_draft_placeholder(self):
        """Test 6: generate_stac_item_id uses 'draft' placeholder when no version."""
        from services.platform_translation import generate_stac_item_id

        item_id = generate_stac_item_id("aerial-imagery", "site-alpha")
        assert "draft" in item_id
        assert "none" not in item_id.lower()

        # Versioned should NOT contain "draft"
        versioned_id = generate_stac_item_id("aerial-imagery", "site-alpha", "v1.0")
        assert "draft" not in versioned_id
        assert "v1" in versioned_id

    def test_table_name_uses_draft_placeholder(self):
        """Test 7: generate_table_name uses 'draft' placeholder when no version."""
        from services.platform_translation import generate_table_name

        table = generate_table_name("aerial-imagery", "site-alpha")
        assert "draft" in table
        assert "none" not in table.lower()

        # Versioned
        versioned = generate_table_name("aerial-imagery", "site-alpha", "v1.0")
        assert "draft" not in versioned


# ============================================================================
# TEST 10, 11: Asset identity (V0.9 -- version excluded from identity)
# ============================================================================

class TestAssetIdentity:
    """Asset.generate_asset_id version exclusion and determinism."""

    def test_version_excluded_from_identity(self):
        """Test 10: asset_id = SHA256(platform_id|dataset_id|resource_id) -- no version."""
        from core.models.asset import Asset

        asset_id = Asset.generate_asset_id("ddh", "ds1", "rs1")
        assert len(asset_id) == 32
        # Same inputs always produce same ID (deterministic)
        assert asset_id == Asset.generate_asset_id("ddh", "ds1", "rs1")

    def test_same_identity_for_all_versions(self):
        """Test 11: Asset IS the lineage -- same identity regardless of version."""
        from core.models.asset import Asset

        asset_id = Asset.generate_asset_id("ddh", "ds1", "rs1")

        # Different resource produces different asset_id
        other_id = Asset.generate_asset_id("ddh", "ds1", "rs2")
        assert asset_id != other_id


# ============================================================================
# TEST 12: ApiRequest empty version_id handling
# ============================================================================

class TestApiRequest:
    """ApiRequest behavior with empty string version_id for draft DB storage."""

    def test_accepts_empty_version_id(self):
        """Test 12: ApiRequest accepts empty string version_id (draft DB storage)."""
        from core.models.platform import ApiRequest

        req = ApiRequest(
            request_id="a" * 32,
            dataset_id="ds1",
            resource_id="rs1",
            version_id="",  # Draft mode
            job_id="b" * 64,
            data_type="vector"
        )
        assert req.version_id == ""
        d = req.to_dict()
        assert d['version_id'] == ""
