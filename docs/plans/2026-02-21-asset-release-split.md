# Asset/Release Entity Split — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the monolithic `GeospatialAsset` (~40 columns) with `Asset` (stable identity, ~12 columns) + `AssetRelease` (versioned artifact, ~30 columns) to eliminate identity mutation, revoke-first workflow, and draft/version confusion.

**Architecture:** Two-table split. Asset = permanent container (dataset_id + resource_id). Release = versioned processing result with its own approval, clearance, and processing lifecycle. Multiple releases coexist under one asset. Clean-slate rebuild — all existing data wiped.

**Tech Stack:** Pydantic V2 models, psycopg3, PostgreSQL, Azure Functions, existing `__sql_*` ClassVar DDL generation pattern.

**Key References:**
- Design doc: `docs/plans/2026-02-21-asset-release-split-design.md`
- Architecture decision: `V0.9_REVIEW.md` (Part 2-3)
- Full specification: `V0.9_ASSET_MODEL.md`
- Current entity: `core/models/asset.py` (851 lines)
- DDL pattern: `core/schema/sql_generator.py` (uses `__sql_*` ClassVar attributes)
- Test pattern: `test/test_draft_mode.py` (dry-run tests, `_make_asset()` factory)
- Lazy imports: `infrastructure/__init__.py` (`__getattr__` pattern)
- Handler registration: `services/__init__.py` (explicit dict, no decorators)

**Environment:** Always use `conda activate azgeo` (Python 3.12, numpy 2.3.3).

---

## Phase 1: Models (New Entity Definitions)

### Task 1: Define Asset Model

**Files:**
- Create: `core/models/asset_v2.py`
- Test: `test/test_asset_release_models.py`

**Step 1: Write the failing test**

```python
# test/test_asset_release_models.py
"""
Tests for V0.9 Asset/Release entity models.
Dry-run tests — no database required.
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
        """Asset ID must NOT include version — that's on Release."""
        from core.models.asset_v2 import Asset
        id1 = Asset.generate_asset_id("ddh", "floods", "jakarta")
        # Same regardless of what version exists
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest test/test_asset_release_models.py::TestAssetModel -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.models.asset_v2'`

**Step 3: Write the Asset model**

Create `core/models/asset_v2.py` with:
- `Asset` Pydantic model (~12 fields: asset_id, platform_id, dataset_id, resource_id, platform_refs, data_type, release_count, created_at, updated_at, deleted_at, deleted_by)
- `generate_asset_id(platform_id, dataset_id, resource_id)` static method — `SHA256(platform_id|dataset_id|resource_id)[:32]`
- `__sql_table_name = "assets"`, `__sql_schema = "app"`, `__sql_primary_key = ["asset_id"]`
- `__sql_indexes`: idx on platform_id, dataset_id+resource_id (unique, partial WHERE deleted_at IS NULL), created_at desc
- `to_dict()` method
- Keep `ApprovalState`, `ClearanceState`, `ProcessingStatus` enums in this file (shared by Release)

**Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest test/test_asset_release_models.py::TestAssetModel -v`
Expected: PASS (all 7 tests)

**Step 5: Commit**

```bash
git add core/models/asset_v2.py test/test_asset_release_models.py
git commit -m "V0.9 Phase 1a: Define Asset model (stable identity container)"
```

---

### Task 2: Define AssetRelease Model

**Files:**
- Modify: `core/models/asset_v2.py`
- Modify: `test/test_asset_release_models.py`

**Step 1: Write the failing test**

Add to `test/test_asset_release_models.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest test/test_asset_release_models.py::TestAssetReleaseModel -v`
Expected: FAIL — `ImportError: cannot import name 'AssetRelease'`

**Step 3: Write the AssetRelease model**

Add `AssetRelease` to `core/models/asset_v2.py` with:
- ~30 fields covering: identity (release_id, asset_id), version (version_id, suggested_version_id, version_ordinal, revision), flags (is_latest, is_served), request link (request_id), physical outputs (blob_path, table_name, stac_item_id, stac_collection_id, stac_item_json), hashes (content_hash, source_file_hash, output_file_hash), processing (job_id, processing_status, processing_started_at, processing_completed_at, last_error, workflow_id, node_summary, priority), approval (approval_state, reviewer, reviewed_at, rejection_reason, approval_notes), clearance (clearance_state, adf_run_id, cleared_at, cleared_by, made_public_at, made_public_by), revocation (revoked_at, revoked_by, revocation_reason), timestamps (created_at, updated_at)
- `__sql_table_name = "asset_releases"`, `__sql_schema = "app"`
- `__sql_primary_key = ["release_id"]`
- `__sql_foreign_keys = {"asset_id": "app.assets(asset_id)", "job_id": "app.jobs(job_id)"}`
- `__sql_indexes`: asset_id, version_id, approval_state, processing_status, is_latest (unique per asset WHERE approval_state='approved'), job_id, stac_item_id, created_at desc
- Helper methods: `can_approve()`, `can_reject()`, `can_revoke()`, `can_overwrite()`, `is_draft()`, `to_dict()`
- `can_overwrite()` returns True only for PENDING_REVIEW or REJECTED

**Step 4: Run test to verify it passes**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest test/test_asset_release_models.py -v`
Expected: PASS (all tests in both TestAssetModel and TestAssetReleaseModel)

**Step 5: Commit**

```bash
git add core/models/asset_v2.py test/test_asset_release_models.py
git commit -m "V0.9 Phase 1b: Define AssetRelease model (versioned artifact with lifecycle)"
```

---

### Task 3: Wire Models into Package Exports and DDL

**Files:**
- Modify: `core/models/__init__.py` (lines ~147-158, ~219-364)
- Modify: `core/schema/sql_generator.py` (import section)

**Step 1: Update model exports**

In `core/models/__init__.py`:
- Add imports from `asset_v2`: `Asset`, `AssetRelease`
- Keep existing `GeospatialAsset`, `AssetRevision` imports temporarily (backward compat during migration)
- Add `Asset`, `AssetRelease` to `__all__`

**Step 2: Register models in DDL generator**

In `core/schema/sql_generator.py`:
- Add `Asset`, `AssetRelease` to the import block alongside existing models
- Verify `generate_composed_statements()` picks them up (it iterates registered models)

**Step 3: Verify DDL generation**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from core.schema.sql_generator import PydanticToSQL; gen = PydanticToSQL(); print([m.__name__ for m in gen.get_registered_models()])"`

Expected: Output includes `Asset` and `AssetRelease` alongside existing models.

**Step 4: Commit**

```bash
git add core/models/__init__.py core/schema/sql_generator.py
git commit -m "V0.9 Phase 1c: Register Asset/Release models in exports and DDL generator"
```

---

## Phase 2: Repository Layer

### Task 4: Create AssetRepository (Simplified)

**Files:**
- Create: `infrastructure/asset_repository_v2.py`
- Test: `test/test_asset_release_repos.py` (integration test — requires DB, mark with skipif)

**Step 1: Write the repository**

Create `infrastructure/asset_repository_v2.py` with class `AssetRepositoryV2(PostgreSQLRepository)`:

Methods needed (much simpler than current 1,886-line repo):
- `create(asset: Asset) -> Asset` — INSERT with advisory lock on asset_id
- `get_by_id(asset_id: str) -> Optional[Asset]`
- `get_by_identity(platform_id: str, dataset_id: str, resource_id: str) -> Optional[Asset]`
- `find_or_create(platform_id, dataset_id, resource_id, data_type) -> Tuple[Asset, str]` — returns (asset, "created"|"existing")
- `soft_delete(asset_id: str, deleted_by: str) -> bool`
- `list_active(limit: int = 100) -> List[Asset]`
- `_row_to_model(row: dict) -> Asset` — deserialize DB row

Use `psycopg.sql` for query composition. Follow pattern from existing `asset_repository.py` for connection handling.

**Step 2: Commit**

```bash
git add infrastructure/asset_repository_v2.py
git commit -m "V0.9 Phase 2a: AssetRepositoryV2 — simplified container CRUD"
```

---

### Task 5: Create ReleaseRepository

**Files:**
- Create: `infrastructure/release_repository.py`

**Step 1: Write the repository**

Create `infrastructure/release_repository.py` with class `ReleaseRepository(PostgreSQLRepository)`:

Methods needed:
- `create(release: AssetRelease) -> AssetRelease` — INSERT
- `get_by_id(release_id: str) -> Optional[AssetRelease]`
- `get_draft(asset_id: str) -> Optional[AssetRelease]` — WHERE asset_id=X AND version_id IS NULL AND approval_state != 'revoked'
- `get_by_version(asset_id: str, version_id: str) -> Optional[AssetRelease]`
- `get_latest(asset_id: str) -> Optional[AssetRelease]` — WHERE is_latest=true AND approval_state='approved'
- `list_by_asset(asset_id: str) -> List[AssetRelease]` — ORDER BY version_ordinal
- `list_by_approval_state(state: ApprovalState, limit: int = 50) -> List[AssetRelease]`
- `list_pending_review(limit: int = 50) -> List[AssetRelease]` — WHERE approval_state='pending_review' AND processing_status='completed'
- `update_approval_state(release_id, approval_state, reviewer, reviewed_at, clearance_state=None, ...) -> bool`
- `update_revocation(release_id, revoked_at, revoked_by, revocation_reason) -> bool`
- `update_processing_status(release_id, status, started_at=None, completed_at=None, error=None) -> bool`
- `update_version_assignment(release_id, version_id, version_ordinal, is_latest) -> bool` — at approval time
- `update_overwrite(release_id, revision, processing_status='pending') -> bool` — increment revision, reset processing
- `update_stac_item_json(release_id, stac_item_json: dict) -> bool` — cache STAC dict
- `get_stac_item_json(release_id: str) -> Optional[dict]`
- `flip_is_latest(asset_id: str, new_latest_release_id: str) -> bool` — atomic: set all others false, set this one true
- `count_by_approval_state() -> Dict[str, int]`
- `_row_to_model(row: dict) -> AssetRelease`

**Step 2: Commit**

```bash
git add infrastructure/release_repository.py
git commit -m "V0.9 Phase 2b: ReleaseRepository — versioned artifact CRUD with approval lifecycle"
```

---

### Task 6: Wire Repositories into Infrastructure Package

**Files:**
- Modify: `infrastructure/__init__.py` (lazy imports)

**Step 1: Update lazy imports**

In `infrastructure/__init__.py`:
- Add `__getattr__` case for `AssetRepositoryV2` → `from .asset_repository_v2 import AssetRepositoryV2`
- Add `__getattr__` case for `ReleaseRepository` → `from .release_repository import ReleaseRepository`
- Keep existing `GeospatialAssetRepository` and `AssetRevisionRepository` temporarily
- Add to `TYPE_CHECKING` block and `__all__`

**Step 2: Verify lazy import**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -c "from infrastructure import ReleaseRepository; print(ReleaseRepository)"`

Expected: `<class 'infrastructure.release_repository.ReleaseRepository'>`

**Step 3: Commit**

```bash
git add infrastructure/__init__.py
git commit -m "V0.9 Phase 2c: Register new repositories in infrastructure lazy imports"
```

---

## Phase 3: Service Layer

### Task 7: Rewrite AssetService

**Files:**
- Create: `services/asset_service_v2.py`

**Step 1: Write the new service**

Create `services/asset_service_v2.py` with class `AssetServiceV2`:

Core methods:
- `find_or_create_asset(platform_id, dataset_id, resource_id, data_type) -> Tuple[Asset, str]` — delegates to repo
- `create_release(asset_id, stac_item_id, stac_collection_id, blob_path=None, table_name=None, job_id=None, request_id=None, suggested_version_id=None, ...) -> AssetRelease` — creates draft release
- `get_or_overwrite_release(asset_id, overwrite: bool, ...) -> Tuple[AssetRelease, str]` — find existing draft, overwrite if flag set, create new if no draft
- `assign_version(release_id, version_id, reviewer) -> AssetRelease` — at approval time: set version_id, compute ordinal, flip is_latest
- `get_active_asset(asset_id) -> Optional[Asset]`
- `get_release(release_id) -> Optional[AssetRelease]`
- `get_latest_release(asset_id) -> Optional[AssetRelease]`
- `get_version_history(asset_id) -> List[AssetRelease]`
- `link_job_to_release(release_id, job_id) -> bool`
- `update_processing_status(release_id, status, ...) -> bool`

Key logic in `get_or_overwrite_release()`:
```python
def get_or_overwrite_release(self, asset_id, overwrite, **release_kwargs):
    existing_draft = self.release_repo.get_draft(asset_id)

    if existing_draft:
        if overwrite:
            if not existing_draft.can_overwrite():
                raise ValueError(f"Cannot overwrite release in state {existing_draft.approval_state}")
            self.release_repo.update_overwrite(
                existing_draft.release_id,
                revision=existing_draft.revision + 1,
            )
            updated = self.release_repo.get_by_id(existing_draft.release_id)
            return updated, "overwritten"
        else:
            return existing_draft, "existing"

    # No draft — create new release
    release = self.create_release(asset_id=asset_id, **release_kwargs)
    return release, "created"
```

**Step 2: Commit**

```bash
git add services/asset_service_v2.py
git commit -m "V0.9 Phase 3a: AssetServiceV2 — asset/release lifecycle orchestration"
```

---

### Task 8: Rewrite AssetApprovalService

**Files:**
- Create: `services/asset_approval_service_v2.py`

**Step 1: Write the new approval service**

Create `services/asset_approval_service_v2.py` with class `AssetApprovalServiceV2`:

Methods (operate on Release, not Asset):
- `approve_release(release_id, reviewer, clearance_state, version_id, notes=None) -> Dict`
  - Validate release is PENDING_REVIEW and processing_status=COMPLETED
  - Call `asset_service.assign_version()` to set version_id + ordinal + is_latest
  - Update approval_state to APPROVED
  - Materialize STAC from cached `stac_item_json` (same logic as current `_materialize_stac`)
  - Trigger ADF if PUBLIC clearance
- `reject_release(release_id, reviewer, reason) -> Dict`
- `revoke_release(release_id, revoker, reason) -> Dict`
  - Set approval_state to REVOKED
  - Delete STAC item from pgSTAC
  - Flip is_latest to next-most-recent approved release (or none)
- `list_pending_review(limit=50) -> List[AssetRelease]`
- `get_approval_stats() -> Dict[str, int]`

Key difference from V0.8: approval targets a `release_id`, not `asset_id`. The Asset entity is not mutated during approval.

**Step 2: Commit**

```bash
git add services/asset_approval_service_v2.py
git commit -m "V0.9 Phase 3b: AssetApprovalServiceV2 — approval operates on Release, not Asset"
```

---

## Phase 4: Triggers & Submit Flow

### Task 9: Rewrite Platform Submit Trigger

**Files:**
- Modify: `triggers/platform/submit.py`

**Step 1: Rewrite the submit flow**

Replace the submit logic to use new services. The new flow:

```
1. Parse request → PlatformRequest
2. Find or create Asset (dataset_id + resource_id)
3. Get or overwrite Release:
   - No existing draft → create new Release
   - Existing draft, no overwrite → idempotent return
   - Existing draft, overwrite=true → re-process (revision++)
   - Existing approved releases → untouched (no collision!)
4. Create CoreMachine job, link to release_id
5. Store ApiRequest (request_id → job_id, release_id)
```

Key removals:
- Delete `_handle_overwrite_unpublish()` — handler manages cleanup internally
- Delete revoke-first guard (`elif is_draft and existing_approved: return 409`) — no longer needed
- Delete `validate_version_lineage()` call — lineage is implicit (asset IS the lineage)
- Delete `generate_asset_id()` calls that include version_id

Key additions:
- `asset_service_v2.find_or_create_asset()`
- `asset_service_v2.get_or_overwrite_release()`
- Store `release_id` on job params (replaces `asset_id`)

**Step 2: Commit**

```bash
git add triggers/platform/submit.py
git commit -m "V0.9 Phase 4a: Rewrite platform submit — Asset/Release flow, no revoke-first"
```

---

### Task 10: Rewrite Approval Triggers

**Files:**
- Modify: `triggers/trigger_approvals.py`

**Step 1: Simplify _resolve_asset_id → _resolve_release**

Replace the 3-tier fallback with direct release lookup:

```python
def _resolve_release(release_id=None, asset_id=None, job_id=None, request_id=None):
    """Resolve release from various identifiers."""
    from infrastructure import ReleaseRepository
    release_repo = ReleaseRepository()

    # 1. Direct release_id (primary path)
    if release_id:
        release = release_repo.get_by_id(release_id)
        if release:
            return release, None
        return None, {"success": False, "error": f"Release not found: {release_id}"}

    # 2. By job_id — direct FK on Release
    if job_id:
        release = release_repo.get_by_job_id(job_id)
        if release:
            return release, None

    # 3. By request_id — stored on Release
    if request_id:
        release = release_repo.get_by_request_id(request_id)
        if release:
            return release, None

    # 4. By asset_id — get latest release (for legacy callers)
    if asset_id:
        from infrastructure import AssetRepositoryV2
        release = release_repo.get_latest(asset_id)
        if release:
            return release, None

    return None, {"success": False, "error": "Could not resolve release"}
```

Update approve/reject/revoke endpoints to pass `release_id` to `AssetApprovalServiceV2`.

**Step 2: Update approval request body**

Accept `release_id` (preferred) or `asset_id` (resolves to latest draft):

```python
# POST /api/platform/approve
{
    "release_id": "...",      # preferred — direct
    "version_id": "v1",       # assigned at approval
    "clearance_level": "ouo",
    "reviewer": "reviewer@org.gov"
}
```

**Step 3: Commit**

```bash
git add triggers/trigger_approvals.py
git commit -m "V0.9 Phase 4b: Approval targets Release — simplified resolution, no 3-tier fallback"
```

---

### Task 11: Update Platform Status Trigger

**Files:**
- Modify: `triggers/trigger_platform_status.py`

**Step 1: Update status queries**

Status endpoint returns Asset + its Releases:

```python
# GET /api/platform/status/{request_id}
# Response includes:
{
    "asset": { "asset_id": "...", "dataset_id": "floods", "resource_id": "jakarta" },
    "release": { "release_id": "...", "version_id": "v1", "approval_state": "approved", ... },
    "versions": [
        { "version_id": "v1", "approval_state": "approved", "is_latest": true },
        { "version_id": null, "approval_state": "pending_review", "is_latest": false }
    ]
}
```

Add version listing: `GET /api/platform/status/{dataset_id}/{resource_id}/versions`

**Step 2: Commit**

```bash
git add triggers/trigger_platform_status.py
git commit -m "V0.9 Phase 4c: Status endpoint returns Asset + Release + version history"
```

---

### Task 12: Update Resubmit Triggers

**Files:**
- Modify: `triggers/platform/resubmit.py`
- Modify: `triggers/jobs/resubmit.py`

**Step 1: Update resubmit to target Release**

Platform resubmit creates a new Release (or overwrites existing draft). Job resubmit retries the existing Release's job.

**Step 2: Commit**

```bash
git add triggers/platform/resubmit.py triggers/jobs/resubmit.py
git commit -m "V0.9 Phase 4d: Resubmit targets Release — new release or retry existing"
```

---

## Phase 5: Handlers & Consumers

### Task 13: Update Process Raster Complete Handler

**Files:**
- Modify: `services/handler_process_raster_complete.py`

**Step 1: Replace asset_id with release_id**

- Job params now contain `release_id` instead of `asset_id`
- `update_processing_status()` targets release
- STAC caching (`update_stac_item_json()`) targets release via `release_repo`
- `reset_approval_for_overwrite()` operates on release

**Step 2: Commit**

```bash
git add services/handler_process_raster_complete.py
git commit -m "V0.9 Phase 5a: Raster handler uses release_id — processing updates on Release"
```

---

### Task 14: Update Process Vector Complete Handler

**Files:**
- Modify: `services/handler_vector_docker_complete.py`

Same pattern as Task 13 — replace `asset_id` with `release_id` in job params and processing updates.

**Step 1: Commit**

```bash
git add services/handler_vector_docker_complete.py
git commit -m "V0.9 Phase 5b: Vector handler uses release_id"
```

---

### Task 15: Update STAC Catalog Service

**Files:**
- Modify: `services/stac_catalog.py`

**Step 1: Update STAC caching**

STAC item dict cached on Release (`stac_item_json` column) instead of `cog_metadata`. At approval, `AssetApprovalServiceV2._materialize_stac()` reads from Release.

**Step 2: Commit**

```bash
git add services/stac_catalog.py
git commit -m "V0.9 Phase 5c: STAC caching targets Release entity"
```

---

### Task 16: Update Unpublish Handlers

**Files:**
- Modify: `services/unpublish_handlers.py`
- Modify: `triggers/platform/unpublish.py`

**Step 1: Revoke targets Release**

Unpublish calls `asset_approval_service_v2.revoke_release(release_id)`. If revoking the `is_latest` release, `flip_is_latest` to next approved release.

**Step 2: Commit**

```bash
git add services/unpublish_handlers.py triggers/platform/unpublish.py
git commit -m "V0.9 Phase 5d: Unpublish revokes Release — is_latest auto-flips"
```

---

### Task 17: Update Platform Catalog Service

**Files:**
- Modify: `services/platform_catalog_service.py`

**Step 1: Update catalog queries**

Catalog lists Assets with their latest approved Release metadata (bbox, feature_count, etc.). JOIN pattern: `assets JOIN asset_releases ON asset_id WHERE is_latest=true AND approval_state='approved'`.

**Step 2: Commit**

```bash
git add services/platform_catalog_service.py
git commit -m "V0.9 Phase 5e: Catalog queries join Asset + latest approved Release"
```

---

### Task 18: Update Platform Validation

**Files:**
- Modify: `services/platform_validation.py`

**Step 1: Simplify version lineage validation**

`validate_version_lineage()` becomes much simpler:
- Lineage = all releases under an asset
- No separate `lineage_id` to compute
- Check: does a release with this version_id already exist under this asset?
- No approval-state-aware logic needed (multiple approved releases allowed)

May be reducible to a simple existence check. Consider whether this file is still needed or can be inlined.

**Step 2: Commit**

```bash
git add services/platform_validation.py
git commit -m "V0.9 Phase 5f: Simplify version validation — lineage is implicit"
```

---

## Phase 6: Schema Rebuild, Cleanup & Verification

### Task 19: Remove Old Entity Model

**Files:**
- Rename: `core/models/asset_v2.py` → `core/models/asset.py` (replace old)
- Delete: `infrastructure/revision_repository.py`
- Rename: `infrastructure/asset_repository_v2.py` → `infrastructure/asset_repository.py` (replace old)
- Rename: `services/asset_service_v2.py` → `services/asset_service.py` (replace old)
- Rename: `services/asset_approval_service_v2.py` → `services/asset_approval_service.py` (replace old)
- Modify: `core/models/__init__.py` — remove old imports, clean up
- Modify: `infrastructure/__init__.py` — remove old lazy imports, clean up

**Step 1: Rename files**

Move `_v2` files to replace originals. Update all import paths. Archive old files to `docs/archive/v09_archive_feb2026/`.

**Step 2: Full grep sweep**

Search for all remaining references to:
- `GeospatialAsset` (should be zero outside archive)
- `AssetRevision` (should be zero)
- `lineage_id` (should be zero in active code)
- `generate_lineage_id` (should be zero)
- `assign_version` (should only be in asset_service.py)
- `previous_asset_id` (should be zero — now `previous_release_id`)
- `geospatial_assets` (should be zero — now `assets`)
- `asset_revisions` (should be zero — now part of `asset_releases`)

**Step 3: Commit**

```bash
git add -A
git commit -m "V0.9 Phase 6a: Replace old entity model — rename _v2 files, remove dead code"
```

---

### Task 20: Update Tests

**Files:**
- Modify: `test/test_draft_mode.py` — update for Asset/Release
- Modify: `test/test_model_serializers.py` — update for new model names
- Delete tests that reference `GeospatialAsset` directly (replace with `Asset`/`AssetRelease` tests)

**Step 1: Run all tests**

Run: `cd /Users/robertharrison/python_builds/rmhgeoapi && conda run -n azgeo python -m pytest test/ -v --tb=short`

Fix any failures from import changes.

**Step 2: Commit**

```bash
git add test/
git commit -m "V0.9 Phase 6b: Update all tests for Asset/Release models"
```

---

### Task 21: Schema Rebuild and Verification

**Step 1: Deploy and rebuild**

```bash
# Deploy to orchestrator
./deploy.sh orchestrator

# Wait for restart
sleep 60

# Health check
curl -sf https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

# Rebuild schema (wipes all data — clean slate)
curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/maintenance?action=rebuild&confirm=yes"
```

**Step 2: Verify new tables exist**

```bash
# Check tables
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/dbadmin/stats
```

Expected: `app.assets` and `app.asset_releases` in table list. `app.geospatial_assets` and `app.asset_revisions` gone.

**Step 3: Smoke test**

```bash
# Submit a test raster (creates Asset + draft Release)
curl -X POST https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/submit \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "test-floods", "resource_id": "jakarta", "data_type": "raster", "container_name": "silver-cogs", "file_name": "test.tif"}'

# Check status — should show asset + draft release
curl https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/status/{request_id}
```

**Step 4: Commit and tag**

```bash
git add -A
git commit -m "V0.9 Phase 6c: Schema rebuild verified — Asset/Release split complete"
```

---

## Phase Summary

| Phase | Tasks | Files | Description |
|-------|-------|-------|-------------|
| **1: Models** | 1-3 | 3 create, 2 modify | Define Asset + AssetRelease Pydantic models with DDL hints |
| **2: Repositories** | 4-6 | 2 create, 1 modify | AssetRepositoryV2 (simple) + ReleaseRepository (lifecycle) |
| **3: Services** | 7-8 | 2 create | AssetServiceV2 + AssetApprovalServiceV2 |
| **4: Triggers** | 9-12 | 4 modify | Submit, approval, status, resubmit |
| **5: Consumers** | 13-18 | 6 modify | Handlers, STAC, unpublish, catalog, validation |
| **6: Cleanup** | 19-21 | Many | Rename, delete old, rebuild schema, verify |

**Total: 21 tasks, ~7 create/rename, ~15 modify, ~3 delete**

**Estimated effort**: 5-7 working sessions (with subagent parallelism on independent tasks)

---

## Decisions Reference (Quick Lookup)

| Question | Answer |
|----------|--------|
| version_id assigned when? | At approval by reviewer |
| Can submitter suggest version_id? | Yes, stored as `suggested_version_id` (metadata) |
| What does overwrite do? | Re-processes same Release (revision++), requires `overwrite=true` |
| Can you overwrite approved? | No — must create new Release |
| Can v1 + v2 both be approved? | Yes — `is_latest` controls `/latest` resolution |
| What about `lineage_id`? | Eliminated. Asset IS the lineage. |
| What about `AssetRevision`? | Eliminated. Release IS the revision history. |
| Migration strategy? | Clean-slate rebuild. Wipe all data. `action=rebuild` creates new tables. |
| Where does `stac_item_json` live? | On Release (not cog_metadata). |
| How does `/latest` resolve? | `WHERE asset_id=X AND is_latest=true AND approval_state='approved'` |
