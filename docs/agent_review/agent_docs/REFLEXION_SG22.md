# REFLEXION Pipeline: SG2-2 — Revoked Release Retains `is_served=true`

**Date**: 01 MAR 2026
**Bug ID**: SG2-2
**Severity**: HIGH
**Pipeline**: R -> F -> P -> J (Reverse Engineer, Fault Injector, Patch Author, Judge)

---

## Agent R: Reverse Engineer

### Objective
Identify every code path that transitions a release to "revoked" state and audit which fields each path updates.

### Revocation Code Paths Found: 3

#### Path 1: `ReleaseRepository.update_revocation()` (Canonical)
- **File**: `/Users/robertharrison/python_builds/rmhgeoapi/infrastructure/release_repository.py` lines 712-759
- **Caller**: `AssetApprovalService.revoke_release()` (line 538)
- **Trigger**: Manual revocation via approval service, or eager revocation in `_try_revoke_release()` (unpublish trigger)
- **SQL UPDATE sets**:
  - `approval_state = REVOKED` -- YES
  - `revoked_at = NOW()` -- YES
  - `revoked_by = %s` -- YES
  - `revocation_reason = %s` -- YES
  - `is_latest = false` -- YES
  - `updated_at = NOW()` -- YES
  - **`is_served = false`** -- **MISSING** (pre-patch)
- **WHERE guard**: `release_id = %s AND approval_state = 'approved'`

#### Path 2: Inline SQL in `delete_stac_and_audit()` (Defense-in-Depth)
- **File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/unpublish_handlers.py` lines 1086-1101
- **Caller**: Stage 3 of unpublish pipeline, runs inside same transaction as STAC item delete
- **SQL UPDATE sets**:
  - `approval_state = 'revoked'` -- YES
  - **`is_served = false`** -- **MISSING** (pre-patch)
  - **`is_latest = false`** -- **MISSING** (pre-patch)
  - **`revoked_at = NOW()`** -- **MISSING** (pre-patch)
  - `revoked_by` -- MISSING (no actor available in handler context)
  - `revocation_reason` -- MISSING (no reason field in handler context)
  - `updated_at` -- MISSING
- **WHERE guard**: `release_id = %s` (no state guard -- intentional, this is a fallback)

#### Path 3: `_try_revoke_release()` (Eager Revocation)
- **File**: `/Users/robertharrison/python_builds/rmhgeoapi/triggers/platform/unpublish.py` lines 211-244
- **Mechanism**: Calls `AssetApprovalService.revoke_release()` which delegates to Path 1
- **This is NOT an independent path** -- it is a wrapper that calls Path 1. No separate SQL.
- **Non-fatal**: catches exceptions and logs warning; Stage 3 (Path 2) is fallback.

### Summary Table

| Field | Expected for Revoked | Path 1 (repo) | Path 2 (inline) | Path 3 (eager) |
|-------|---------------------|----------------|------------------|-----------------|
| `approval_state = REVOKED` | YES | SET | SET | via Path 1 |
| `is_latest = false` | YES | SET | **MISSED** | via Path 1 |
| `is_served = false` | YES | **MISSED** | **MISSED** | via Path 1 |
| `revoked_at = timestamp` | YES | SET | **MISSED** | via Path 1 |
| `revoked_by = actor` | YES | SET | MISSED (no actor) | via Path 1 |
| `revocation_reason` | YES | SET | MISSED (no reason) | via Path 1 |
| `updated_at = NOW()` | YES | SET | MISSED | via Path 1 |

### Key Finding
Both independent revocation code paths (Path 1 and Path 2) fail to set `is_served = false`. This means **every** revocation in the system leaves the release with `is_served = true`, creating a data integrity violation where the release claims to be served but its STAC item has been deleted.

---

## Agent F: Fault Injector

### Fault Scenarios

#### F1: Primary revocation via approval service leaves `is_served = true`
- **Trigger**: User revokes a release through the approval UI or API
- **Code path**: `AssetApprovalService.revoke_release()` -> `ReleaseRepository.update_revocation()`
- **Effect**: Release row has `approval_state=revoked, is_latest=false, is_served=true`
- **Impact**: Downstream catalog queries return `is_served: true` for a revoked release

#### F2: Unpublish pipeline inline revocation leaves `is_served = true` AND `is_latest` unchanged
- **Trigger**: Stage 3 of unpublish pipeline deletes STAC item and atomically revokes
- **Code path**: `delete_stac_and_audit()` inline SQL
- **Effect**: Release row has `approval_state=revoked, is_latest=<unchanged>, is_served=true`
- **Impact**: Worse than F1 -- both `is_served` AND `is_latest` remain stale. A revoked release could still appear as `is_latest=true` if it was the latest when revoked via this path.
- **Additional**: Missing `revoked_at` means no audit timestamp for when revocation occurred.

#### F3: Double revocation (Path 3 succeeds, then Path 2 runs)
- **Trigger**: `_try_revoke_release()` succeeds (Path 1), then Stage 3 handler also runs (Path 2)
- **Code path**: Path 2's WHERE clause has no `AND approval_state = 'approved'` guard
- **Effect**: Path 2 would re-UPDATE an already-revoked release. Pre-patch this was a no-op on `approval_state` but could theoretically create a second audit log line. Post-patch, the UPDATE still fires but is idempotent (setting fields to values they already hold).
- **Impact**: LOW -- the fields converge to the same values. The missing `approval_state = 'approved'` guard in Path 2 is intentional defense-in-depth.

### Downstream Consumers of `is_served`

1. **`services/platform_catalog_service.py`** (lines 649, 733, 781, 914):
   - `is_served` is returned in the `lineage` block of all catalog API responses (`_build_vector_response`, `_build_raster_response`, `_build_generic_response`, and the unified listing query).
   - B2B consumers (DDH platform) rely on `is_served` to determine if a dataset version is available for serving.
   - **With stale `is_served=true`**: A revoked dataset appears as "still served" in catalog responses, misleading downstream systems that may try to access deleted STAC items.

2. **`infrastructure/release_repository.py`** (line 92, 118, 1559):
   - `is_served` is part of the INSERT column list (line 92), INSERT values (line 118), and row-to-model hydration (line 1559, defaults to `True`).
   - These are CRUD plumbing, not decision logic. No filtering by `is_served` occurs in the repository.

3. **`services/asset_service.py`** (line 212):
   - Sets `is_served=True` when creating a new release. This is correct -- new releases should default to served.

4. **`core/models/asset.py`** (line 448-451, 703):
   - Field definition and `to_dict()` serialization. No logic depends on the value.

5. **Archive files** (docs/archive/v09_archive_feb2026/):
   - The old v0.8 asset model had `is_served` with partial index `WHERE is_served = true AND deleted_at IS NULL`, and `update_is_served()` method. These are ARCHIVED and not in the active codebase.

### Verdict
No active code path uses `is_served` as a WHERE filter or branch condition. The field is purely informational, surfaced in catalog API responses. However, the stale value is **semantically incorrect** and misleads B2B consumers. The fix is essential for data integrity.

---

## Agent P: Patch Author

### Patch 1: `ReleaseRepository.update_revocation()`

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/infrastructure/release_repository.py`
**Lines affected**: 738-746 (SQL UPDATE statement)
**Change**: Added `is_served = false,` to the SET clause.

```diff
 SET approval_state = %s,
     revoked_at = NOW(),
     revoked_by = %s,
     revocation_reason = %s,
     is_latest = false,
+    is_served = false,
     updated_at = NOW()
 WHERE release_id = %s
   AND approval_state = %s
```

Also updated the docstring to document the new behavior:
```diff
-Sets approval_state to REVOKED and is_latest to false.
+Sets approval_state to REVOKED, is_latest to false, and
+is_served to false (SG2-2 fix: revoked releases must not
+remain served).
```

### Patch 2: `delete_stac_and_audit()` inline SQL

**File**: `/Users/robertharrison/python_builds/rmhgeoapi/services/unpublish_handlers.py`
**Lines affected**: 1094-1096 (inline SQL UPDATE)
**Change**: Extended the UPDATE to also set `is_served = false`, `is_latest = false`, and `revoked_at = NOW()`.

```diff
-"UPDATE app.asset_releases SET approval_state = 'revoked' WHERE release_id = %s"
+"UPDATE app.asset_releases SET approval_state = 'revoked', is_served = false, is_latest = false, revoked_at = NOW() WHERE release_id = %s"
```

**Rationale for additional fields in Patch 2**: Path 2 is a defense-in-depth fallback that runs when Path 1 may have failed or been skipped. It must set all state fields to their correct revoked values to avoid partial state. The fields `revoked_by` and `revocation_reason` are intentionally omitted because the handler context does not have actor/reason information, and NULL values for those audit fields are acceptable for a system-driven cleanup path.

### Patches NOT applied

- **Path 3** (`_try_revoke_release`): No patch needed. This is a wrapper that delegates to `AssetApprovalService.revoke_release()` which calls Path 1. Patch 1 covers it.
- **`asset_service.py` default `is_served=True`**: No change. New releases should default to `is_served=True`. The field is only set to `false` on revocation.
- **`approve_release_atomic()`**: Reviewed. Does not touch `is_served` but does not need to -- approval does not change serving status (it was already `True` from creation).

---

## Agent J: Judge

### Patch 1 Verdict: ACCEPT

| Criterion | Assessment |
|-----------|------------|
| **Correctness** | PASS. Adding `is_served = false` to the SET clause is the minimal correct fix. The WHERE guard (`AND approval_state = 'approved'`) ensures only approved releases are affected, so non-revoked releases are untouched. |
| **Safety** | PASS. The SET clause is additive -- it does not remove or reorder existing columns. The parameterized query structure is unchanged. No new parameters are introduced (it's a literal `false`). |
| **Scope** | PASS. Single line added to SQL, docstring updated. No behavioral change for any non-revocation code path. |
| **Conflicts** | NONE. No other code path sets `is_served` on existing releases. The approval path (`approve_release_atomic`) does not touch `is_served`, so there is no race condition. |
| **Idempotency** | PASS. If called twice (e.g., double-click), the second call matches 0 rows (WHERE guard requires `approval_state = 'approved'`, but it's already `'revoked'`). |
| **Regression risk** | NEGLIGIBLE. The only consumers of `is_served` are catalog response builders that return it as-is. They will now correctly show `false` for revoked releases. |

### Patch 2 Verdict: ACCEPT WITH NOTE

| Criterion | Assessment |
|-----------|------------|
| **Correctness** | PASS. Adding `is_served = false, is_latest = false, revoked_at = NOW()` makes the inline SQL consistent with Path 1's behavior. This is critical because Path 2 is a fallback that may run when Path 1 was skipped. |
| **Safety** | PASS. The UPDATE is still within the same transaction as the STAC delete, maintaining atomicity. Adding more SET columns does not change transactional behavior. |
| **Scope** | PASS. Single-line SQL change. No structural changes to the handler. |
| **Conflicts** | LOW RISK. If Path 1 already ran successfully (via `_try_revoke_release`), Path 2's UPDATE fires but is idempotent -- it sets fields to values they already hold. The missing `AND approval_state = 'approved'` guard means it will UPDATE even if Path 1 already revoked, but this is harmless (sets `'revoked'` to `'revoked'`, `false` to `false`). |
| **Remaining gaps** | `revoked_by` and `revocation_reason` are still not set by Path 2. This is ACCEPTABLE because: (1) Path 2 is a system-driven cleanup, not a user action; (2) the handler has no actor context; (3) NULL audit fields for system actions are a documented pattern in this codebase. If Path 1 ran first, these fields are already populated. |
| **Idempotency** | PASS. Re-running the UPDATE on an already-revoked release is a no-op in effect (same values). |
| **Regression risk** | NEGLIGIBLE. The `revoked_at = NOW()` addition means if Path 2 runs after Path 1, `revoked_at` gets overwritten with a slightly later timestamp. This is acceptable -- it reflects the time of the STAC deletion, which is the more operationally relevant timestamp for unpublish audits. |

### Overall Verdict: **ACCEPT BOTH PATCHES**

Both patches are minimal, surgical, and correct. They close the SG2-2 bug by ensuring all revocation paths set `is_served = false`. The patches do not affect happy-path behavior (non-revoked releases are unaffected), and they are idempotent under concurrent execution.

### Recommended Follow-Up (Non-Blocking)

1. **Data migration**: Existing revoked releases in the database still have `is_served = true`. A one-time UPDATE should be run:
   ```sql
   UPDATE app.asset_releases
   SET is_served = false
   WHERE approval_state = 'revoked'
     AND is_served = true;
   ```
   This is safe to run at any time and is idempotent.

2. **Path 2 audit completeness**: Consider adding `updated_at = NOW()` to the inline SQL in Path 2 for consistency with Path 1. This is non-blocking.

3. **Integration test**: Add a test that revokes a release and asserts `is_served = false` in the resulting row.
