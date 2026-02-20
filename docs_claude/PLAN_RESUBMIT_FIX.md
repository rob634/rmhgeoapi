# Platform Resubmit Hardening — Implementation Plan

**Date**: 20 FEB 2026
**Status**: IMPLEMENTED (20 FEB 2026)
**SAFe Type**: Story (under STAC B2C Materialized View feature)
**Priority**: P2
**Files**: 3 modified
**Estimated Effort**: Small (< 50 lines changed)

---

## Context

`POST /api/platform/resubmit` performs a "nuclear reset" — deletes all job artifacts (tasks, STAC items, PostGIS tables, optionally blobs) then resubmits an identical job. It delegates to `JobResubmitHandler` for cleanup and resubmission.

**Problem**: The endpoint has no awareness of the asset lifecycle introduced in v0.8. It doesn't check `approval_state`, doesn't update the `GeospatialAsset` record, and doesn't update the `api_requests` tracking record. This means:

1. Resubmitting an **approved** asset silently deletes its STAC item from pgSTAC (breaks B2C catalog)
2. The asset's `current_job_id` points to a deleted job (stale FK)
3. `api_requests.job_id` still points to the deleted job (status polling breaks)

---

## Changes Required

### Change 1: Block Resubmit on Approved Assets

**File**: `triggers/platform/resubmit.py`
**Location**: `PlatformResubmitHandler.handle()`, after job lookup (line ~105), before cleanup planning

**What to add**: After fetching the job, look up the associated asset. If `approval_state == APPROVED`, return 409.

```python
# After line 111 (job lookup), before line 114 (processing check):

# Block resubmit on approved assets (20 FEB 2026: STAC B2C integrity)
if job and job.asset_id:
    from services.asset_service import AssetService
    asset_service = AssetService()
    asset = asset_service.get_active_asset(job.asset_id)
    if asset and asset.approval_state.value == 'approved':
        return self._error_response(
            f"Cannot resubmit approved asset. "
            f"Revoke approval first (POST /api/platform/revoke) then resubmit.",
            "ResubmitBlockedError",
            409
        )
```

**Also add the same check** in `triggers/jobs/resubmit.py` → `JobResubmitHandler.handle()` at the equivalent location (after job lookup, before processing check). This protects the direct `/api/jobs/{job_id}/resubmit` route too.

**Edge case**: If `job.asset_id` is NULL (legacy jobs before v0.8.16), skip the check and allow resubmit. These jobs have no asset lifecycle to protect.

---

### Change 2: Reset Asset State on Resubmit

**File**: `triggers/platform/resubmit.py`
**Location**: `PlatformResubmitHandler.handle()`, after `_resubmit_job()` returns `new_job_id` (line ~164)

**What to add**: Update the asset record with the new job_id and reset approval state.

```python
# After line 164 (new_job_id = resubmit_handler._resubmit_job(...)):

# Update asset with new job_id and reset state (20 FEB 2026)
if job and job.asset_id:
    try:
        from infrastructure.asset_repository import get_asset_repository
        asset_repo = get_asset_repository()
        asset_repo.update(job.asset_id, {
            'current_job_id': new_job_id,
            'processing_status': 'processing',
        })
        logger.info(f"Updated asset {job.asset_id[:16]} with new job_id {new_job_id[:16]}")
    except Exception as e:
        logger.warning(f"Failed to update asset after resubmit: {e}")
        # Non-fatal — job is already resubmitted
```

**Note**: Do NOT reset `approval_state` here. The asset should already be non-approved (blocked by Change 1). If the asset is `pending_review`, `rejected`, or `revoked`, those states are fine — the handler's `reset_approval_for_overwrite()` will reset to `pending_review` after the new job completes successfully.

**Also add the same update** in `triggers/jobs/resubmit.py` → `JobResubmitHandler.handle()` at the equivalent location.

---

### Change 3: Update Platform Request with New Job ID

**File**: `infrastructure/platform.py`
**Location**: `ApiRequestRepository` class

**What to add**: New method to update the job_id on an existing api_request record.

```python
def update_job_id(self, request_id: str, new_job_id: str) -> bool:
    """
    Update the job_id on a platform request record.

    20 FEB 2026: Used by platform/resubmit to keep status polling working
    after a job is deleted and resubmitted.

    Args:
        request_id: Platform request ID
        new_job_id: New job ID to associate

    Returns:
        True if updated, False if request not found
    """
    with self._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("""
                    UPDATE {}.api_requests
                    SET job_id = %s, updated_at = NOW()
                    WHERE request_id = %s
                """).format(sql.Identifier(self.config.app_schema)),
                (new_job_id, request_id)
            )
            conn.commit()
            return cur.rowcount > 0
```

**Then wire it** in `triggers/platform/resubmit.py` → `PlatformResubmitHandler.handle()`, after the asset update (Change 2):

```python
# Update platform request with new job_id (20 FEB 2026)
if platform_refs and platform_refs.get('request_id'):
    try:
        self.platform_repo.update_job_id(
            platform_refs['request_id'], new_job_id
        )
        logger.info(f"Updated platform request {platform_refs['request_id'][:16]} with new job_id")
    except Exception as e:
        logger.warning(f"Failed to update platform request: {e}")
        # Non-fatal — job is already resubmitted
```

**Note**: This only applies to the platform resubmit path (not the direct job resubmit), since only platform requests have tracking records.

---

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `triggers/platform/resubmit.py` | Add approval guard, asset update, platform_request update | ~25 lines |
| `triggers/jobs/resubmit.py` | Add approval guard, asset update (same pattern) | ~15 lines |
| `infrastructure/platform.py` | Add `update_job_id()` method | ~15 lines |

---

## What This Does NOT Change

- **Cleanup logic** (`_plan_cleanup`, `_execute_cleanup`) — unchanged, works correctly
- **`_resubmit_job`** — unchanged, deterministic job ID generation is fine
- **STAC cache** (`cog_metadata.stac_item_json`) — not cleaned up. The new processing run naturally overwrites it with fresh data for the same `cog_id`.
- **Direct job resubmit route** (`/api/jobs/{job_id}/resubmit`) — gets the approval guard and asset update but NOT the platform_request update (no platform context available)

---

## Verification

After implementing, test this sequence:

```bash
BASE_URL="https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net"

# 1. Submit draft, wait for completion
curl -X POST "$BASE_URL/api/platform/submit" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"qa-resubmit-test","resource_id":"test1","data_type":"raster","container_name":"rmhazuregeobronze","file_name":"dctest.tif"}'
# Wait for job_status=completed

# 2. Resubmit dry_run (should work — asset is pending_review)
curl -X POST "$BASE_URL/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"{REQUEST_ID}","dry_run":true}'
# EXPECTED: 200 with cleanup plan

# 3. Resubmit execute
curl -X POST "$BASE_URL/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"{REQUEST_ID}"}'
# EXPECTED: 202 with new_job_id
# VERIFY: status polling returns new job info

# 4. Wait for new job to complete, then approve with v1
curl -X POST "$BASE_URL/api/platform/approve" \
  -H "Content-Type: application/json" \
  -d '{"asset_id":"{ASSET_ID}","reviewer":"test@rmh.com","clearance_level":"ouo","version_id":"v1"}'
# EXPECTED: 200, STAC item materialized

# 5. Try resubmit on approved asset (should be BLOCKED)
curl -X POST "$BASE_URL/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"{REQUEST_ID}"}'
# EXPECTED: 409 "Cannot resubmit approved asset. Revoke first."

# 6. Revoke, then resubmit (should work)
curl -X POST "$BASE_URL/api/platform/revoke" \
  -H "Content-Type: application/json" \
  -d '{"asset_id":"{ASSET_ID}","revoker":"test@rmh.com","reason":"resubmit test"}'
curl -X POST "$BASE_URL/api/platform/resubmit" \
  -H "Content-Type: application/json" \
  -d '{"request_id":"{REQUEST_ID}"}'
# EXPECTED: 202 with new_job_id
```

---

## Dependencies

- Requires v0.8.20.0 deployed (STAC materialization, revoke-first workflow)
- `api_requests` table must have `job_id` and `updated_at` columns (both exist since v0.8)
- `GeospatialAsset` must have `current_job_id` field (exists since v0.8.16)
