# Submit Idempotency and Overwrite Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the submit decision matrix — reject ambiguous resubmissions, guard overwrite against approved releases, block version advance over in-progress work.

**Architecture:** All guard logic lives in `AssetService.get_or_overwrite_release()`. The submit trigger (`submit.py`) already delegates to this method and handles `ReleaseStateError` as 409. We add a new lookup method on `ReleaseRepository`, tighten `get_or_overwrite_release()`, and update the existing idempotent response to include release context. No new files.

**Tech Stack:** Python, psycopg3, Azure Functions HTTP triggers

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `infrastructure/release_repository.py` | Modify | Add `get_current_release()` — finds newest release for asset regardless of state |
| `services/asset_service.py` | Modify | Rewrite `get_or_overwrite_release()` — implement full decision matrix |
| `triggers/platform/submit.py` | Modify | Pass `suggested_version_id` to guard; enrich 409 responses |
| `services/platform_response.py` | Modify | Add `release_exists_response()` for 409 with release context |

---

### Task 1: Add `get_current_release()` to ReleaseRepository

The decision matrix needs the newest release for an asset (any state). Existing methods are too narrow:
- `get_draft()` — only un-versioned, non-revoked
- `get_latest()` — only approved
- `get_overwrite_candidate()` — only overwritable states

We need: "give me the most recent release for this asset, period."

**Files:**
- Modify: `infrastructure/release_repository.py` (after `get_overwrite_candidate`, ~line 430)

- [ ] **Step 1: Add `get_current_release()` method**

Add after `get_overwrite_candidate()` (around line 430):

```python
def get_current_release(self, asset_id: str) -> Optional[AssetRelease]:
    """
    Get the most recent release for an asset, regardless of state.

    Used by submit guard to check if any release exists before
    creating a new one. Returns newest by created_at.

    Args:
        asset_id: Parent asset identifier

    Returns:
        AssetRelease if any release exists, None for first submission
    """
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("""
                    SELECT * FROM {}.{}
                    WHERE asset_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table)
                ),
                (asset_id,)
            )
            row = cur.fetchone()
            return AssetRelease.from_row(row) if row else None
```

- [ ] **Step 2: Verify locally**

```bash
conda activate azgeo
python -c "from infrastructure.release_repository import ReleaseRepository; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add infrastructure/release_repository.py
git commit -m "feat: add get_current_release() to ReleaseRepository for submit guard"
```

---

### Task 2: Add `release_exists_response()` to platform_response.py

The spec requires a 409 response with release context. The existing `idempotent_response()` returns 200 with a job_id hint. We need a new helper that returns 409 with `existing_release` details.

**Files:**
- Modify: `services/platform_response.py` (after `idempotent_response`, ~line 225)

- [ ] **Step 1: Add `release_exists_response()` function**

Add after `idempotent_response()`:

```python
def release_exists_response(
    request_id: str,
    release: 'AssetRelease',
    dataset_id: str,
    resource_id: str,
    version_id: str,
) -> func.HttpResponse:
    """
    Build a 409 Conflict response when a release already exists and the
    caller didn't specify overwrite or version advance.

    Includes existing release context so the caller can decide next action.
    """
    state = release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state)

    body = {
        "success": False,
        "error": (
            f"Release already exists for {dataset_id}/{resource_id} {version_id} "
            f"(state: {state}). Use processing_options.overwrite: true to revise, "
            f"or submit with a new version_id to advance version."
        ),
        "error_type": "ReleaseExistsError",
        "existing_release": {
            "release_id": release.release_id,
            "approval_state": state,
            "version_id": release.version_id,
            "version_ordinal": release.version_ordinal,
            "processing_status": release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status),
            "monitor_url": f"/api/platform/status/{request_id}",
        }
    }

    return func.HttpResponse(
        json.dumps(body),
        status_code=409,
        mimetype="application/json"
    )
```

- [ ] **Step 2: Add to imports in `submit.py`**

In `triggers/platform/submit.py`, add `release_exists_response` to the existing import block (around line 67-71):

```python
    release_exists_response,
```

- [ ] **Step 3: Commit**

```bash
git add services/platform_response.py triggers/platform/submit.py
git commit -m "feat: add release_exists_response() for 409 with release context"
```

---

### Task 3: Rewrite `get_or_overwrite_release()` with full decision matrix

This is the core change. The current method has three problems:
1. No-flag resubmit silently creates a new ordinal (should reject)
2. Version advance doesn't check for in-progress work (should block)
3. Overwrite of approved releases gives a generic error (should say "revoke first")

We rewrite to implement the spec's decision matrix exactly.

**Files:**
- Modify: `services/asset_service.py:239-383` — rewrite `get_or_overwrite_release()`

- [ ] **Step 1: Add `is_version_advance` parameter and detection**

The method needs to know whether the caller is advancing version. Add `suggested_version_id` comparison. Update the signature at line 239:

```python
def get_or_overwrite_release(
    self,
    asset_id: str,
    overwrite: bool,
    stac_item_id: str,
    stac_collection_id: str,
    blob_path: Optional[str] = None,
    job_id: Optional[str] = None,
    request_id: Optional[str] = None,
    suggested_version_id: Optional[str] = None,
    data_type: Optional[str] = None
) -> Tuple[AssetRelease, str]:
```

(Signature is unchanged — `suggested_version_id` already exists.)

- [ ] **Step 2: Replace method body**

Replace the entire method body (lines 293-383) with the decision matrix implementation:

```python
    # -----------------------------------------------------------------
    # Step 1: Find current release for this asset (any state)
    # -----------------------------------------------------------------
    current = self.release_repo.get_current_release(asset_id)

    # -----------------------------------------------------------------
    # CASE A: No prior release — first submission
    # -----------------------------------------------------------------
    if current is None:
        logger.info(f"Creating first release for asset {asset_id[:16]}...")
        release = self.create_release(
            asset_id=asset_id,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            blob_path=blob_path,
            job_id=job_id,
            request_id=request_id,
            suggested_version_id=suggested_version_id,
            data_type=data_type,
            version_ordinal=1,
        )
        return release, "created"

    # -----------------------------------------------------------------
    # Determine caller intent
    # -----------------------------------------------------------------
    is_approved = current.approval_state == ApprovalState.APPROVED
    is_terminal = current.approval_state in (
        ApprovalState.APPROVED, ApprovalState.REVOKED
    )
    # Version advance = caller's version_id differs from current's
    # suggested_version_id (the DDH-provided version on the release)
    is_version_advance = (
        suggested_version_id
        and current.suggested_version_id
        and suggested_version_id != current.suggested_version_id
    )

    # -----------------------------------------------------------------
    # CASE B: Overwrite requested
    # -----------------------------------------------------------------
    if overwrite:
        if is_approved:
            raise ReleaseStateError(
                current.release_id,
                "approved",
                "pending_review, rejected, failed, or revoked",
                "overwrite. Revoke first via POST /api/platform/revoke, "
                "then resubmit with overwrite: true"
            )
        if not current.can_overwrite():
            state = f"{current.approval_state.value}/processing={current.processing_status.value}"
            raise ReleaseStateError(
                current.release_id,
                state,
                "pending_review, rejected, or revoked (and not actively processing)",
                "overwrite"
            )
        # Clean stale PostGIS table mappings before reprocessing
        from infrastructure.release_table_repository import ReleaseTableRepository
        ReleaseTableRepository().delete_for_release(current.release_id)

        self.release_repo.update_overwrite(
            current.release_id,
            revision=current.revision + 1,
        )
        updated = self.release_repo.get_by_id(current.release_id)
        logger.info(
            f"Overwritten release {current.release_id[:16]}... "
            f"(revision {updated.revision})"
        )
        return updated, "overwritten"

    # -----------------------------------------------------------------
    # CASE C: Version advance (new version_id, no overwrite)
    # -----------------------------------------------------------------
    if is_version_advance:
        if not is_terminal:
            raise ReleaseStateError(
                current.release_id,
                current.approval_state.value,
                "approved or revoked",
                f"advance version to '{suggested_version_id}'. "
                f"Current version '{current.suggested_version_id}' is in state "
                f"'{current.approval_state.value}'. Approve, reject, or "
                f"overwrite the current release first"
            )
        # Terminal state — create new version
        next_ordinal = self.release_repo.get_next_version_ordinal(asset_id)
        logger.info(
            f"Version advance for asset {asset_id[:16]}... "
            f"('{current.suggested_version_id}' -> '{suggested_version_id}', "
            f"next ordinal: {next_ordinal})"
        )
        release = self.create_release(
            asset_id=asset_id,
            stac_item_id=stac_item_id,
            stac_collection_id=stac_collection_id,
            blob_path=blob_path,
            job_id=job_id,
            request_id=request_id,
            suggested_version_id=suggested_version_id,
            data_type=data_type,
            version_ordinal=next_ordinal,
        )
        return release, "new_version"

    # -----------------------------------------------------------------
    # CASE D: No flags, release exists — idempotent rejection
    # -----------------------------------------------------------------
    # Caller resubmitted identical params without overwrite or version
    # advance. Return existing release so submit.py can build a 409.
    logger.info(
        f"Existing release found for asset {asset_id[:16]}... "
        f"(state={current.approval_state.value}, no overwrite/advance)"
    )
    return current, "existing"
```

- [ ] **Step 3: Verify import of ApprovalState is present**

Check that `ApprovalState` is imported at the top of `services/asset_service.py`. It should already be there — verify:

```python
from core.models.asset import ApprovalState, ProcessingStatus, ...
```

- [ ] **Step 4: Commit**

```bash
git add services/asset_service.py
git commit -m "feat: rewrite get_or_overwrite_release() with full decision matrix"
```

---

### Task 4: Update submit.py to handle "existing" with 409

Currently, the "existing" case at line 296-331 in `submit.py` checks for `job_id` to detect orphans and otherwise returns an `idempotent_response` (HTTP 200). With the new matrix, "existing" always means "reject with 409" — the orphan cleanup is still needed but the happy path is gone.

**Files:**
- Modify: `triggers/platform/submit.py:296-331`

- [ ] **Step 1: Replace the "existing" handler block**

Replace lines 296-331 (the `if release_op == "existing":` block) with:

```python
            # Step 4: Handle "existing" — release exists, no overwrite/advance
            if release_op == "existing":
                if not release.job_id and not release.workflow_id:
                    # Orphaned release: prior attempt created Release but job creation failed.
                    # Auto-clean and create fresh release instead of returning 409. (03 MAR 2026)
                    logger.warning(
                        f"Orphaned release {release.release_id[:16]}... — "
                        f"no job_id/workflow_id, auto-cleaning and re-creating"
                    )
                    try:
                        asset_service.cleanup_orphaned_release(release.release_id, asset.asset_id)
                        release, release_op = asset_service.get_or_overwrite_release(
                            asset_id=asset.asset_id,
                            overwrite=False,
                            stac_item_id=generate_stac_item_id(platform_req.dataset_id, platform_req.resource_id, platform_req.version_id),
                            stac_collection_id=job_params.get('collection_id', platform_req.dataset_id.lower()),
                            blob_path=None,
                            request_id=request_id,
                            suggested_version_id=platform_req.version_id,
                        )
                        logger.info(f"  Orphan cleaned, fresh release {release_op}: {release.release_id[:16]}...")
                    except Exception as cleanup_err:
                        logger.error(f"Orphan auto-cleanup failed: {cleanup_err}", exc_info=True)
                        return error_response(
                            "Prior submission left an orphaned release and cleanup failed. "
                            "Resubmit with processing_options.overwrite=true to force cleanup.",
                            "OrphanedReleaseError",
                            status_code=409
                        )
                else:
                    # Release exists with a real job/workflow — reject with context
                    return release_exists_response(
                        request_id=request_id,
                        release=release,
                        dataset_id=platform_req.dataset_id,
                        resource_id=platform_req.resource_id,
                        version_id=platform_req.version_id or "(draft)",
                    )
```

- [ ] **Step 2: Commit**

```bash
git add triggers/platform/submit.py
git commit -m "feat: reject ambiguous resubmissions with 409 and release context"
```

---

### Task 5: Verify end-to-end with curl

Run through the 7 SIEGE test sequences from the spec against the live deployment. These are manual verification steps — no code changes.

**Pre-requisite:** Deploy to orchestrator after committing Tasks 1-4.

- [ ] **Step 1: D-IDEM-7 — First submission (no prior release)**

```bash
curl -s -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "idem-test",
    "resource_id": "case7-first",
    "version_id": "v1",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "title": "IDEM-7 First Submit"
  }' | python3 -m json.tool
```

Expected: `{"success": true, ...}` — creates release, starts workflow.

- [ ] **Step 2: D-IDEM-1 — Identical submit, no flags, release exists**

Resubmit the exact same payload:

```bash
# Same curl as Step 1 — identical payload
```

Expected: HTTP 409 with `"error_type": "ReleaseExistsError"` and `existing_release` block.

- [ ] **Step 3: D-IDEM-2 ��� Overwrite pending_review release**

```bash
curl -s -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "idem-test",
    "resource_id": "case7-first",
    "version_id": "v1",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "title": "IDEM-2 Overwrite",
    "processing_options": {"overwrite": true}
  }' | python3 -m json.tool
```

Expected: `{"success": true, ...}` — new workflow, same ordinal, revision incremented.

- [ ] **Step 4: D-IDEM-3 — Overwrite approved release (should fail)**

First approve the release from Step 3, then attempt overwrite:

```bash
# Approve (after workflow reaches gate)
curl -s -X POST "{BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{"asset_id": "{ASSET_ID}", "reviewer": "test@example.com", "clearance_state": "ouo"}'

# Attempt overwrite
curl -s -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "idem-test",
    "resource_id": "case7-first",
    "version_id": "v1",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "processing_options": {"overwrite": true}
  }' | python3 -m json.tool
```

Expected: HTTP 409 with `"ReleaseStateError"` — "Revoke first".

- [ ] **Step 5: D-IDEM-5 — Version advance (new version_id, prior approved)**

```bash
curl -s -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "idem-test",
    "resource_id": "case7-first",
    "version_id": "v2",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "title": "IDEM-5 Version Advance"
  }' | python3 -m json.tool
```

Expected: `{"success": true, ...}` — new ordinal, version_id="v2".

- [ ] **Step 6: D-IDEM-6 — Version advance over in-progress work (should fail)**

While v2 is still `pending_review`, attempt v3:

```bash
curl -s -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "idem-test",
    "resource_id": "case7-first",
    "version_id": "v3",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "title": "IDEM-6 Should Fail"
  }' | python3 -m json.tool
```

Expected: HTTP 409 with `"ReleaseStateError"` — "Current version 'v2' is in state 'pending_review'".

- [ ] **Step 7: D-IDEM-4 — Overwrite revoked release**

Approve v2, then revoke it, then overwrite:

```bash
# Approve v2
curl -s -X POST "{BASE_URL}/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{"asset_id": "{ASSET_ID}", "reviewer": "test@example.com", "clearance_state": "ouo"}'

# Revoke v2
curl -s -X POST "{BASE_URL}/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{"asset_id": "{ASSET_ID}", "reviewer": "test@example.com", "reason": "IDEM-4 test"}'

# Overwrite revoked
curl -s -X POST "{BASE_URL}/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "idem-test",
    "resource_id": "case7-first",
    "version_id": "v2",
    "container_name": "rmhazuregeobronze",
    "file_name": "dctest.tif",
    "processing_options": {"overwrite": true}
  }' | python3 -m json.tool
```

Expected: `{"success": true, ...}` — reprocesses same slot.

- [ ] **Step 8: Commit verification notes**

Document results and commit.
