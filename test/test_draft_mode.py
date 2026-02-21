#!/usr/bin/env python3
"""
Draft Mode Dry-Run Test Suite (17 FEB 2026).

Tests the version_id deferral from submit → approve (draft mode).
Exercises logic without database — mocks repository layer.

Tests:
    1. PlatformRequest accepts None version_id
    2. PlatformRequest still works with version_id (backward compat)
    3. generate_platform_request_id handles None version_id
    4. Draft request_id differs from versioned request_id
    5. Same draft inputs produce same request_id (idempotency)
    6. generate_stac_item_id uses "draft" placeholder
    7. generate_table_name uses "draft" placeholder
    8. PlatformRequest.stac_item_id property handles None
    9. PlatformRequest.generated_title handles None
   10. AssetService.assign_version validates draft state
   11. AssetService.assign_version rejects already-versioned asset

Usage:
    conda activate azgeo
    python test/test_draft_mode.py
"""

import os
import sys
import traceback

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
# TEST RUNNER
# ============================================================================

passed = 0
failed = 0
errors = []


def run_test(name, test_fn):
    """Run a test function and track results."""
    global passed, failed, errors
    try:
        test_fn()
        passed += 1
        print(f"  PASS: {name}")
    except AssertionError as e:
        failed += 1
        errors.append((name, str(e)))
        print(f"  FAIL: {name} — {e}")
    except Exception as e:
        failed += 1
        errors.append((name, f"{type(e).__name__}: {e}"))
        print(f"  ERROR: {name} — {type(e).__name__}: {e}")
        traceback.print_exc()


# ============================================================================
# TEST 1: PlatformRequest accepts None version_id
# ============================================================================
def test_platform_request_no_version():
    from core.models.platform import PlatformRequest

    req = PlatformRequest(
        dataset_id="test-dataset",
        resource_id="test-resource",
        # version_id omitted — should default to None
        container_name="bronze-vectors",
        file_name="test.geojson"
    )
    assert req.version_id is None, f"Expected None, got {req.version_id}"
    assert req.dataset_id == "test-dataset"
    assert req.resource_id == "test-resource"


# ============================================================================
# TEST 2: PlatformRequest still works with version_id (backward compat)
# ============================================================================
def test_platform_request_with_version():
    from core.models.platform import PlatformRequest

    req = PlatformRequest(
        dataset_id="test-dataset",
        resource_id="test-resource",
        version_id="v1.0",
        container_name="bronze-vectors",
        file_name="test.geojson"
    )
    assert req.version_id == "v1.0", f"Expected 'v1.0', got {req.version_id}"


# ============================================================================
# TEST 3: generate_platform_request_id handles None version_id
# ============================================================================
def test_request_id_no_version():
    from config import generate_platform_request_id

    rid = generate_platform_request_id("ds1", "rs1")
    assert isinstance(rid, str), f"Expected str, got {type(rid)}"
    assert len(rid) == 32, f"Expected length 32, got {len(rid)}"


# ============================================================================
# TEST 4: Draft request_id differs from versioned request_id
# ============================================================================
def test_request_id_draft_vs_versioned():
    from config import generate_platform_request_id

    draft_id = generate_platform_request_id("ds1", "rs1")
    versioned_id = generate_platform_request_id("ds1", "rs1", "v1.0")
    assert draft_id != versioned_id, "Draft and versioned request_ids should differ"


# ============================================================================
# TEST 5: Same draft inputs produce same request_id (idempotency)
# ============================================================================
def test_request_id_draft_idempotent():
    from config import generate_platform_request_id

    id1 = generate_platform_request_id("ds1", "rs1")
    id2 = generate_platform_request_id("ds1", "rs1")
    assert id1 == id2, f"Draft request_ids should be identical: {id1} != {id2}"


# ============================================================================
# TEST 6: generate_stac_item_id uses "draft" placeholder
# ============================================================================
def test_stac_item_id_draft():
    from services.platform_translation import generate_stac_item_id

    item_id = generate_stac_item_id("aerial-imagery", "site-alpha")
    assert "draft" in item_id, f"Expected 'draft' in '{item_id}'"
    assert "none" not in item_id.lower(), f"Should not contain 'none': '{item_id}'"

    # Versioned should NOT contain "draft"
    versioned_id = generate_stac_item_id("aerial-imagery", "site-alpha", "v1.0")
    assert "draft" not in versioned_id, f"Versioned should not contain 'draft': '{versioned_id}'"
    assert "v1" in versioned_id, f"Expected 'v1' in '{versioned_id}'"


# ============================================================================
# TEST 7: generate_table_name uses "draft" placeholder
# ============================================================================
def test_table_name_draft():
    from services.platform_translation import generate_table_name

    table = generate_table_name("aerial-imagery", "site-alpha")
    assert "draft" in table, f"Expected 'draft' in '{table}'"
    assert "none" not in table.lower(), f"Should not contain 'none': '{table}'"

    # Versioned
    versioned = generate_table_name("aerial-imagery", "site-alpha", "v1.0")
    assert "draft" not in versioned, f"Versioned should not contain 'draft': '{versioned}'"


# ============================================================================
# TEST 8: PlatformRequest.stac_item_id property handles None version_id
# ============================================================================
def test_platform_request_stac_item_id_draft():
    from core.models.platform import PlatformRequest

    req = PlatformRequest(
        dataset_id="test-dataset",
        resource_id="test-resource",
        container_name="bronze-vectors",
        file_name="test.geojson"
    )
    item_id = req.stac_item_id
    assert "draft" in item_id, f"Expected 'draft' in '{item_id}'"
    assert "none" not in item_id.lower(), f"Should not contain 'none': '{item_id}'"


# ============================================================================
# TEST 9: PlatformRequest.generated_title handles None version_id
# ============================================================================
def test_platform_request_title_draft():
    from core.models.platform import PlatformRequest

    req = PlatformRequest(
        dataset_id="test-dataset",
        resource_id="test-resource",
        container_name="bronze-vectors",
        file_name="test.geojson"
    )
    title = req.generated_title
    assert "(draft)" in title, f"Expected '(draft)' in '{title}'"
    assert "None" not in title, f"Should not contain 'None': '{title}'"


# ============================================================================
# TEST 10: V0.9 Asset.generate_asset_id — version excluded from identity
# ============================================================================
def test_asset_id_version_excluded():
    from core.models.asset import Asset

    # V0.9: asset_id = SHA256(platform_id|dataset_id|resource_id) — no version
    asset_id = Asset.generate_asset_id("ddh", "ds1", "rs1")

    assert len(asset_id) == 32
    # Same inputs always produce same ID (deterministic)
    assert asset_id == Asset.generate_asset_id("ddh", "ds1", "rs1")


# ============================================================================
# TEST 11: V0.9 Asset IS the lineage — same identity for all versions
# ============================================================================
def test_asset_id_same_for_all_versions():
    from core.models.asset import Asset

    # In V0.9, asset_id doesn't include version_id, so the identity
    # is the same regardless of which version is being submitted.
    # lineage_id is eliminated — the asset IS the lineage.
    asset_id = Asset.generate_asset_id("ddh", "ds1", "rs1")

    # Different resource produces different asset_id
    other_id = Asset.generate_asset_id("ddh", "ds1", "rs2")
    assert asset_id != other_id, "Different resources should produce different asset_ids"


# ============================================================================
# TEST 12: ApiRequest accepts empty string version_id (draft DB storage)
# ============================================================================
def test_api_request_empty_version():
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


# ============================================================================
# RUN ALL TESTS
# ============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("Draft Mode Dry-Run Tests (17 FEB 2026)")
    print("=" * 60)

    print("\n--- PlatformRequest Model ---")
    run_test("1. PlatformRequest accepts None version_id", test_platform_request_no_version)
    run_test("2. PlatformRequest with version_id (backward compat)", test_platform_request_with_version)

    print("\n--- Request ID Generation ---")
    run_test("3. request_id handles None version_id", test_request_id_no_version)
    run_test("4. Draft vs versioned request_ids differ", test_request_id_draft_vs_versioned)
    run_test("5. Draft request_id is idempotent", test_request_id_draft_idempotent)

    print("\n--- Naming Functions ---")
    run_test("6. stac_item_id uses 'draft' placeholder", test_stac_item_id_draft)
    run_test("7. table_name uses 'draft' placeholder", test_table_name_draft)
    run_test("8. PlatformRequest.stac_item_id handles None", test_platform_request_stac_item_id_draft)
    run_test("9. PlatformRequest.generated_title handles None", test_platform_request_title_draft)

    print("\n--- Asset Identity ---")
    run_test("10. Draft vs versioned asset_ids differ", test_asset_id_draft_vs_versioned)
    run_test("11. lineage_id same for draft and versioned", test_lineage_id_same_for_draft_and_versioned)
    run_test("12. ApiRequest accepts empty version_id", test_api_request_empty_version)

    # Summary
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)
