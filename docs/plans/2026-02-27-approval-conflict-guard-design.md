# Approval Conflict Guard & Atomic Rollback

**Date**: 27 FEB 2026
**Status**: APPROVED
**Origin**: QA branch comparison — ported pattern from ITSES-GEOSPATIAL-ETL V0.9.8.0

## Problem

When two reviewers concurrently approve sibling releases of the same asset with the same `version_id`, both can succeed because the existing `WHERE approval_state = 'pending_review'` guard only prevents re-approval of the *same* release, not duplicate version assignment across *sibling* releases.

Additionally, if STAC materialization or `stac_item_id` update fails after the atomic approval has committed, the release is left in an "approved-but-broken" state with no automated recovery.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Fail policy on STAC failure | Rollback approval to PENDING_REVIEW | Prevents approved-but-broken state; reviewer retries after fix |
| Conflict HTTP response | 409 with remediation hint | Standard, actionable, distinguishable from validation errors |
| Rollback scope | Full restore including is_latest sibling | Restores catalog to pre-approval state completely |
| Guard approach | Hybrid: UNIQUE partial index + NOT EXISTS SQL | Belt and suspenders — schema-level + code-level protection |

## Changes

### 1. Schema: Partial Unique Index

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_releases_unique_version_per_asset
ON app.releases (asset_id, version_id)
WHERE approval_state = 'approved';
```

Added to `database_initializer.py` so `action=ensure` picks it up. Only constrains APPROVED releases — drafts and rejected releases are unconstrained.

### 2. Repository: `release_repository.py`

**2a. `approve_release_atomic()` — NOT EXISTS guard**

Add subquery to both SQL branches (public and non-public):

```sql
WHERE release_id = %s
  AND approval_state = %s
  AND NOT EXISTS (
      SELECT 1 FROM app.releases AS sibling
      WHERE sibling.asset_id = %s
        AND sibling.release_id != %s
        AND sibling.version_id = %s
  )
```

Three extra bind parameters: `asset_id`, `release_id`, `version_id`. Returns `False` (rowcount=0) if a sibling already holds that version_id.

**2b. New method: `rollback_approval_atomic(release_id, asset_id) -> bool`**

Single-transaction rollback:
1. Reset failed release: `approval_state -> PENDING_REVIEW`, nullify `version_id`, `is_latest`, `reviewer`, `reviewed_at`, `clearance_state -> UNCLEARED`
2. Restore previous latest: find most recently approved sibling (`version_ordinal DESC`) and set `is_latest = true`
3. Commit both atomically

**2c. New helper: `get_by_version(asset_id, version_id) -> Optional[Release]`**

Simple query: `SELECT ... WHERE asset_id = %s AND version_id = %s AND approval_state = 'approved' LIMIT 1`. Used by service layer to identify the conflicting release for the 409 response.

### 3. Service: `asset_approval_service.py`

**3a. Version conflict detection** — When `approve_release_atomic()` returns `False`, probe for conflicting sibling and return `error_type: 'VersionConflict'` with remediation.

**3b. Rollback on STAC materialization failure** — Replace "log and persist last_error" with `rollback_approval_atomic()`. Returns `StacMaterializationError` (safe rollback) or `StacRollbackFailed` (inconsistent state, manual intervention).

**3c. Rollback on stac_item_id update failure** — Same rollback pattern for `update_physical_outputs()` failure.

### 4. Trigger: `trigger_approvals.py`

Propagate `error_type` and `remediation` from service result. Map error types to HTTP status codes:
- `StacRollbackFailed`, `ApprovalRollbackFailed` -> 500
- `VersionConflict` -> 409
- Everything else -> 400

## Error Types

| error_type | HTTP | Meaning | Action |
|------------|------|---------|--------|
| `VersionConflict` | 409 | Sibling already holds that version_id | Use different version_id or revoke conflicting release |
| `StacMaterializationError` | 400 | STAC failed, approval safely rolled back | Fix STAC issue and retry |
| `StacRollbackFailed` | 500 | STAC failed AND rollback failed | Manual intervention required |
| `ApprovalPostCommitUpdateFailed` | 400 | stac_item_id update failed, approval rolled back | Retry |
| `ApprovalRollbackFailed` | 500 | stac_item_id update AND rollback both failed | Manual intervention |
| `ApprovalFailed` | 400 | Generic (existing, e.g., not in pending_review) | Check release state |

## Files Modified

| File | Change |
|------|--------|
| `infrastructure/database_initializer.py` | Add partial unique index |
| `infrastructure/release_repository.py` | NOT EXISTS guard + rollback_approval_atomic() + get_by_version() |
| `services/asset_approval_service.py` | Conflict detection + STAC rollback + stac_item_id rollback |
| `triggers/trigger_approvals.py` | Error type propagation + contextual HTTP status codes |
