# Approval Workflow Adversarial Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the 5 bugs identified by the adversarial review of the approval workflow (see `docs/agent_review/REVIEW_SUMMARY.md`, formerly `APPROVAL_WORKFLOW.md`).

**Architecture:** All fixes are surgical patches. Tasks 2-4 are mechanical edits. Task 1 is the only one that touches two modules (materialization + dematerialization). Task 5 adds a try/except wrapper. No new modules, no new tables, no schema migrations.

**Tech Stack:** Python 3.12, psycopg2, pytest. Tests are unit tests — no DB required for Tasks 2-4.

---

## Baseline

Confirm existing tests pass before starting:

```bash
conda run -n azgeo pytest tests/ -v --tb=short 2>&1 | tail -20
```

---

### Task 1: Fix tiled revocation deleting ALL collection items (FIX 1 — CRITICAL)

**Files:**
- Modify: `services/asset_approval_service.py:543-553` (`_delete_stac()`)
- Modify: `services/stac_materialization.py` (`_materialize_tiled_items()` — tag items at insertion)
- Test: New test file or add to existing approval service tests

**Why first:** This is the highest-severity bug — revoking one tiled release nukes STAC items belonging to other approved releases sharing the same collection.

**Root Cause:** `_delete_stac()` line 546 calls `pgstac.get_collection_item_ids(release.stac_collection_id)` which returns ALL items in the collection, then deletes every one of them. For versioned assets where multiple approved releases share one `stac_collection_id`, this is data loss.

**Step 1: Tag tiled items at materialization time**

In `services/stac_materialization.py`, function `_materialize_tiled_items()` (around line 268), when patching each existing item, add a `geoetl:release_id` property BEFORE the sanitization step strips it. Wait — sanitization strips `geoetl:*`. Instead, use a `ddh:release_id` property (B2C-safe namespace).

In the approval_props dict (line 246-252), add:
```python
approval_props['ddh:release_id'] = release.release_id
```

Also add the same tag in `_materialize_tiled_from_cog_metadata()` (line 308+) — the fallback insertion path must also tag items.

**Step 2: Filter deletion to only this release's items**

In `services/asset_approval_service.py`, function `_delete_stac()`, replace lines 543-553:

**BEFORE:**
```python
# Tiled output: delete all items for this release's tiles
if release.output_mode == 'tiled':
    pgstac = PgStacRepository()
    item_ids = pgstac.get_collection_item_ids(release.stac_collection_id)
    for item_id in item_ids:
        materializer.dematerialize_item(release.stac_collection_id, item_id)
    return {
        'success': True,
        'deleted': len(item_ids) > 0,
        'items_deleted': len(item_ids)
    }
```

**AFTER:**
```python
# Tiled output: delete only THIS release's items (not all items in collection)
if release.output_mode == 'tiled':
    pgstac = PgStacRepository()
    all_item_ids = pgstac.get_collection_item_ids(release.stac_collection_id)

    # Filter to items belonging to this release
    # Items tagged with ddh:release_id at materialization time
    release_item_ids = []
    for item_id in all_item_ids:
        item = pgstac.get_item(release.stac_collection_id, item_id)
        if item and item.get('properties', {}).get('ddh:release_id') == release.release_id:
            release_item_ids.append(item_id)

    if not release_item_ids and all_item_ids:
        # Legacy items without ddh:release_id tag — log warning and skip
        logger.warning(
            f"Tiled revocation: {len(all_item_ids)} items in collection "
            f"{release.stac_collection_id} but none tagged with release_id "
            f"{release.release_id[:16]}... — skipping deletion to prevent data loss. "
            f"Manual cleanup required."
        )
        return {
            'success': True,
            'deleted': False,
            'warning': 'Legacy items without release_id tag — manual cleanup required',
            'items_in_collection': len(all_item_ids)
        }

    for item_id in release_item_ids:
        materializer.dematerialize_item(release.stac_collection_id, item_id)

    return {
        'success': True,
        'deleted': len(release_item_ids) > 0,
        'items_deleted': len(release_item_ids)
    }
```

**Step 3: Verify `get_item()` exists on PgStacRepository**

Check that `PgStacRepository` has a `get_item(collection_id, item_id)` method. If not, add one — it's a single SQL query against `pgstac.items`.

**Step 4: Write tests**

Test the filtering logic: mock `get_collection_item_ids` to return 3 items, mock `get_item` to return 2 with matching `ddh:release_id` and 1 without. Assert only 2 are deleted.

Test the legacy fallback: mock all items without `ddh:release_id`. Assert none are deleted and warning is logged.

**Acceptance:** Revoking a tiled release only deletes that release's items. Other releases' items in the same collection are untouched. Legacy items without tags are not deleted (fail-safe).

---

### Task 2: Sanitize exception handlers across all trigger layers (FIX 2 — HIGH)

**Files:**
- Modify: `triggers/trigger_approvals.py` (lines 362-372, 510-520, 663-673)
- Modify: `triggers/assets/asset_approvals_bp.py` (lines 235-245, 382-392, 532-542)
- Modify: `triggers/admin/admin_approvals.py` (lines 138-144, 333-339, 430-436, 527-533)

**Why second:** Mechanical find-and-replace across ~13 catch blocks. Low risk, high value.

**Root Cause:** Every `except Exception as e` block returns `str(e)` and `type(e).__name__` in the HTTP response body. This leaks internal class names, database error messages, and potentially connection strings to unauthenticated callers.

**Step 1: Add helper function to `triggers/http_base.py`**

Add a standalone function (not a class method) alongside the existing `parse_request_json()`:

```python
def safe_error_response(
    status_code: int,
    logger_instance,
    error_msg: str,
    exc: Optional[Exception] = None,
    error_type: str = "InternalError"
) -> func.HttpResponse:
    """
    Create a safe error response that does not leak internal details.

    Logs the full exception server-side, returns a generic message to the caller.
    """
    if exc:
        logger_instance.error(f"{error_msg}: {exc}", exc_info=True)
    else:
        logger_instance.error(error_msg)

    return func.HttpResponse(
        json.dumps({
            "success": False,
            "error": "An internal error occurred. Check server logs.",
            "error_type": error_type
        }),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )
```

**Step 2: Replace all 500-level catch blocks**

In each file, replace the pattern:
```python
except Exception as e:
    logger.error(f"... failed: {e}", exc_info=True)
    return func.HttpResponse(
        json.dumps({
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }),
        status_code=500,
        headers={"Content-Type": "application/json"}
    )
```

With:
```python
except Exception as e:
    return safe_error_response(500, logger, "Platform approve failed", exc=e)
```

**Specific locations (13 blocks):**

| File | Function | Lines |
|------|----------|-------|
| `trigger_approvals.py` | `platform_approve` | 362-372 |
| `trigger_approvals.py` | `platform_reject` | 510-520 |
| `trigger_approvals.py` | `platform_revoke` | 663-673 |
| `asset_approvals_bp.py` | `approve_asset` | 235-245 |
| `asset_approvals_bp.py` | `reject_asset` | 382-392 |
| `asset_approvals_bp.py` | `revoke_asset` | 532-542 |
| `admin_approvals.py` | `list_approvals` | 138-144 |
| `admin_approvals.py` | `approve_dataset` | 333-339 |
| `admin_approvals.py` | `reject_dataset` | 430-436 |
| `admin_approvals.py` | `revoke_dataset` | 527-533 |

Note: Some admin endpoints use slightly different shapes (`{'error': str(e)}` without `error_type`). Normalize all to use `safe_error_response()`.

**Step 3: Add import to each trigger file**

```python
from triggers.http_base import safe_error_response
```

**Acceptance:** No 500-level response body contains `str(e)` or `type(e).__name__`. All detailed error info is in server-side logs only. 400-level responses (validation errors, state guard failures) are unchanged — those are safe to show.

---

### Task 3: Fix `reject_release()` using wrong state guard (FIX 3 — LOW)

**Files:**
- Modify: `services/asset_approval_service.py:287-293`
- Test: Add test to verify correct guard is called

**Why third:** 2-line fix. Correctness improvement even though `can_approve()` and `can_reject()` are currently identical.

**Root Cause:** `reject_release()` calls `release.can_approve()` instead of `release.can_reject()`. Both currently check `approval_state == PENDING_REVIEW`, so no runtime bug — but semantically wrong and fragile.

**Step 1: Fix the guard call and error message**

**BEFORE (line 287-293):**
```python
        # Validate state
        if not release.can_approve():
            return {
                'success': False,
                'error': (
                    f"Cannot reject: approval_state is '{release.approval_state.value}', "
                    f"expected 'pending_review'"
                )
            }
```

**AFTER:**
```python
        # Validate state
        if not release.can_reject():
            return {
                'success': False,
                'error': (
                    f"Cannot reject: approval_state is '{release.approval_state.value}', "
                    f"expected 'pending_review'"
                )
            }
```

Note: The error message text is already correct (says "Cannot reject"). Only the method call changes.

**Acceptance:** `reject_release()` calls `can_reject()`. Behavior is identical today but correct for future state machine divergence.

---

### Task 4: Clear `rejection_reason` on approval (FIX 4 — MEDIUM)

**Files:**
- Modify: `infrastructure/release_repository.py:1201-1266` (`approve_release_atomic()`)
- Test: Verify `rejection_reason = NULL` appears in both SQL branches

**Why fourth:** Small SQL change, two places.

**Root Cause:** When a previously rejected release is re-submitted and then approved, `approve_release_atomic()` does not set `rejection_reason = NULL`. The stale rejection reason from the previous review cycle survives into the approved state. `update_overwrite()` already clears it, so this is belt-and-suspenders — but the atomic approval should be self-contained.

**Step 1: Add `rejection_reason = NULL` to the PUBLIC branch**

In the PUBLIC SQL (lines 1204-1235), add `rejection_reason = NULL,` after the `approval_notes = %s,` line:

```sql
SET version_id = %s,
    version_ordinal = %s,
    is_latest = true,
    approval_state = %s,
    reviewer = %s,
    reviewed_at = %s,
    approval_notes = %s,
    rejection_reason = NULL,
    clearance_state = %s,
    ...
```

**Step 2: Add `rejection_reason = NULL` to the non-PUBLIC branch**

Same change in the non-PUBLIC SQL (lines 1237-1266):

```sql
SET version_id = %s,
    version_ordinal = %s,
    is_latest = true,
    approval_state = %s,
    reviewer = %s,
    reviewed_at = %s,
    approval_notes = %s,
    rejection_reason = NULL,
    clearance_state = %s,
    ...
```

Note: `rejection_reason = NULL` is a literal — no parameter needed. The parameter tuple does not change.

**Acceptance:** After approving a previously-rejected release, `rejection_reason` is NULL. Verified by reading the SQL.

---

### Task 5: Wrap post-atomic STAC operations with error capture (FIX 5 — HIGH)

**Files:**
- Modify: `services/asset_approval_service.py:179-199` (`approve_release()`)
- Modify: `infrastructure/release_repository.py` (add `update_last_error()` method)

**Why last:** This is the only task that adds a new repository method and touches the approval happy path.

**Root Cause:** After `approve_release_atomic()` commits, three follow-on operations happen in separate transactions: `update_physical_outputs()` (stac_item_id), `_materialize_stac()`, and optionally `_trigger_adf_pipeline()`. If any of these fail, the release is APPROVED in the DB but STAC is stale/missing. There is no error capture, no retry mechanism, and no way to discover which releases have this problem.

**Approach:** Simpler option — wrap the post-atomic operations in try/except, log CRITICAL, and persist the error to `last_error` on the release so it can be queried. We already have `last_error` as a field on `AssetRelease` (used by processing pipeline).

**Step 1: Verify `last_error` field exists and has a repo update method**

Check if `release_repository.py` has an `update_last_error()` or similar. If not, add one — single UPDATE setting `last_error` and `updated_at`.

**Step 2: Wrap post-atomic operations**

**BEFORE (lines 179-199):**
```python
        # Update stac_item_id to final versioned form (draft-N -> version_id)
        from services.platform_translation import generate_stac_item_id
        from infrastructure import AssetRepository
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(release.asset_id)
        if asset:
            final_stac_item_id = generate_stac_item_id(
                asset.dataset_id, asset.resource_id, version_id
            )
            if final_stac_item_id != release.stac_item_id:
                self.release_repo.update_physical_outputs(
                    release_id=release_id,
                    stac_item_id=final_stac_item_id
                )
                logger.info(
                    f"Updated stac_item_id: {release.stac_item_id} -> {final_stac_item_id}"
                )
                release.stac_item_id = final_stac_item_id

        # Materialize STAC item to pgSTAC from cached stac_item_json
        stac_result = self._materialize_stac(release, reviewer, clearance_state)
```

**AFTER:**
```python
        # Post-atomic operations: stac_item_id update + STAC materialization.
        # These run AFTER the atomic approval commit. If they fail, the release
        # is APPROVED in the DB but STAC is stale/missing. We capture the error
        # on the release so it can be queried and retried.
        stac_result = {'success': False, 'error': 'STAC materialization not attempted'}
        try:
            # Update stac_item_id to final versioned form (draft-N -> version_id)
            from services.platform_translation import generate_stac_item_id
            from infrastructure import AssetRepository
            asset_repo = AssetRepository()
            asset = asset_repo.get_by_id(release.asset_id)
            if asset:
                final_stac_item_id = generate_stac_item_id(
                    asset.dataset_id, asset.resource_id, version_id
                )
                if final_stac_item_id != release.stac_item_id:
                    self.release_repo.update_physical_outputs(
                        release_id=release_id,
                        stac_item_id=final_stac_item_id
                    )
                    logger.info(
                        f"Updated stac_item_id: {release.stac_item_id} -> {final_stac_item_id}"
                    )
                    release.stac_item_id = final_stac_item_id

            # Materialize STAC item to pgSTAC from cached stac_item_json
            stac_result = self._materialize_stac(release, reviewer, clearance_state)

        except Exception as e:
            logger.critical(
                f"STAC_MATERIALIZATION_FAILED for approved release {release_id[:16]}...: {e}",
                exc_info=True
            )
            stac_result = {'success': False, 'error': f'STAC_MATERIALIZATION_FAILED: {e}'}
            # Persist error on release for queryability
            try:
                self.release_repo.update_last_error(
                    release_id=release_id,
                    last_error=f"STAC_MATERIALIZATION_FAILED: {e}"
                )
            except Exception as persist_err:
                logger.error(f"Failed to persist STAC error to release: {persist_err}")
```

**Step 3: Add `update_last_error()` to ReleaseRepository (if missing)**

```python
def update_last_error(self, release_id: str, last_error: str) -> bool:
    """Update last_error field on a release."""
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("""
                    UPDATE {}.{}
                    SET last_error = %s, updated_at = %s
                    WHERE release_id = %s
                """).format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table)
                ),
                (last_error, datetime.now(timezone.utc), release_id)
            )
            conn.commit()
            return cur.rowcount > 0
```

**Acceptance:** If STAC materialization fails after atomic approval, the release still shows as APPROVED (correct), `last_error` contains `STAC_MATERIALIZATION_FAILED`, and a CRITICAL log entry is written. The approval response includes `stac_updated: false`. No crash, no silent failure.

---

## Task Order & Dependencies

```
Task 3 (can_reject guard) ──── no dependencies, 5 min
Task 4 (rejection_reason NULL) ── no dependencies, 15 min
Task 2 (error sanitization) ──── no dependencies, 30-45 min
Task 5 (STAC error capture) ──── no dependencies, 30 min
Task 1 (tiled revocation) ────── no dependencies, 2-3 hrs
```

Tasks 2, 3, and 4 are independent and can run in parallel.
Task 5 is independent but touches `approve_release()` (same file as Task 3).
Task 1 is the largest and should run last to avoid merge conflicts.

**Recommended execution order:** 3 → 4 → 2 → 5 → 1

---

## Post-Implementation

After all 5 fixes:

```bash
# Run all tests
conda run -n azgeo pytest tests/ -v --tb=short

# Verify no regressions
conda run -n azgeo pytest tests/ -v --tb=short 2>&1 | grep -E "FAILED|ERROR|passed"
```

Update `docs/agent_review/REVIEW_SUMMARY.md` (formerly `APPROVAL_WORKFLOW.md`) — fixes already marked RESOLVED.
