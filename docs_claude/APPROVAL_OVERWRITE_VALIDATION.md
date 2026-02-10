# Approval-Aware Overwrite & Version Validation

**Created**: 09 FEB 2026
**Status**: Implementation Ready
**Priority**: Immediate (Next Priority)
**Related**: [APPROVAL_WORKFLOW.md](./APPROVAL_WORKFLOW.md), [DRY_RUN_IMPLEMENTATION.md](./DRY_RUN_IMPLEMENTATION.md)

---

## Problem Statement

The current `validate_version_lineage()` function doesn't receive the `overwrite` parameter, causing submissions with `overwrite=True` to fail validation when a version already exists. Additionally, the approval workflow state must be considered before allowing overwrites.

**Current Bug Location**: `triggers/platform/submit.py` lines 295-300

```python
# BUG: overwrite not passed to validation
validation_result = validate_version_lineage(
    platform_id="ddh",
    platform_refs=platform_refs,
    previous_version_id=platform_req.previous_version_id,
    asset_service=asset_service  # <-- missing: overwrite parameter
)
```

---

## Business Rules

### Overwrite Logic (Same Version Replacement)

| Current Approval State | Action | Rationale |
|------------------------|--------|-----------|
| **APPROVED** | REJECT with message | Approved data is "locked". User must explicitly revoke first. Prevents accidental replacement of production data. |
| **PENDING_REVIEW** | ALLOW overwrite | Keep PENDING_REVIEW. QA will review the new data. |
| **REJECTED** | ALLOW overwrite | Reset to PENDING_REVIEW. Fresh start for resubmission. |
| **REVOKED** | ALLOW overwrite | Reset to PENDING_REVIEW. Approval workflow begins anew. |

**Error Message for APPROVED state:**
```
"Asset is approved. Revoke approval before overwriting. Use POST /api/platform/revoke first."
```

### Semantic Version Logic (New Version in Lineage)

| Previous Version State | Action | Rationale |
|-----------------------|--------|-----------|
| **APPROVED** | ALLOW | Only approved versions can be predecessors. Quality gate. |
| **PENDING_REVIEW** | REJECT | Previous version not yet vetted. |
| **REJECTED** | REJECT | Previous version failed QA. |
| **REVOKED** | REJECT | Previous version withdrawn. |
| **Does not exist** | REJECT | Invalid reference. |

**Error Message for non-approved previous:**
```
"Previous version '{version_id}' must be approved before creating a new version. Current state: {state}"
```

---

## Implementation Plan

### Phase 1: Fix Overwrite Validation Bug

#### Task 1.1: Update `validate_version_lineage()` signature

**File**: `services/platform_validation.py`

```python
def validate_version_lineage(
    platform_id: str,
    platform_refs: Dict[str, Any],
    previous_version_id: Optional[str],
    asset_service: Optional[AssetService] = None,
    overwrite: bool = False  # NEW PARAMETER
) -> VersionValidationResult:
```

#### Task 1.2: Add approval state check for overwrite

**File**: `services/platform_validation.py`

Add logic after lineage state retrieval:

```python
# Check approval state for overwrite scenarios
if overwrite and lineage_state.get('version_exists'):
    existing_asset = lineage_state.get('existing_asset', {})
    approval_state = existing_asset.get('approval_state', 'pending_review')

    if approval_state == 'approved':
        valid = False
        warnings.append(
            "Asset is approved. Revoke approval before overwriting. "
            "Use POST /api/platform/revoke first."
        )
    elif approval_state in ('rejected', 'revoked'):
        # Will reset to pending_review - add info message
        warnings.append(
            f"Asset state '{approval_state}' will be reset to 'pending_review' after overwrite."
        )
    # pending_review: no message needed, just proceed
```

#### Task 1.3: Update submit trigger to pass overwrite

**File**: `triggers/platform/submit.py`

```python
validation_result = validate_version_lineage(
    platform_id="ddh",
    platform_refs=platform_refs,
    previous_version_id=platform_req.previous_version_id,
    asset_service=asset_service,
    overwrite=overwrite  # ADD THIS
)
```

### Phase 2: Semantic Version Validation

#### Task 2.1: Add previous version approval check

**File**: `services/platform_validation.py`

Modify the "Subsequent version case" logic:

```python
else:
    # Subsequent version case - previous version must exist AND be approved
    if not current_latest:
        valid = False
        warnings.append(
            f"previous_version_id '{previous_version_id}' specified but no versions exist. "
            f"Omit previous_version_id for first version."
        )
    elif current_latest.get('version_id') != previous_version_id:
        valid = False
        latest_version = current_latest.get('version_id')
        warnings.append(
            f"previous_version_id '{previous_version_id}' is not the current latest version. "
            f"Current latest is '{latest_version}'."
        )
    else:
        # Previous version exists and matches - check approval state
        prev_approval_state = current_latest.get('approval_state', 'pending_review')
        if prev_approval_state != 'approved':
            valid = False
            warnings.append(
                f"Previous version '{previous_version_id}' must be approved before creating "
                f"a new version. Current state: '{prev_approval_state}'."
            )
```

#### Task 2.2: Update `get_lineage_state()` to include approval_state

**File**: `services/asset_service.py`

Ensure `current_latest` dict includes approval_state:

```python
if current_latest:
    result['current_latest'] = {
        'version_id': current_latest.platform_refs.get('version_id'),
        'version_ordinal': current_latest.version_ordinal,
        'asset_id': current_latest.asset_id,
        'is_served': current_latest.is_served,
        'approval_state': current_latest.approval_state.value,  # ADD THIS
        'created_at': current_latest.created_at.isoformat() if current_latest.created_at else None
    }
```

Also update `existing_asset` to include approval_state:

```python
if existing_version:
    result['existing_asset'] = {
        'version_id': existing_version.platform_refs.get('version_id'),
        'asset_id': existing_version.asset_id,
        'processing_status': existing_version.processing_status.value,
        'approval_state': existing_version.approval_state.value,  # ADD THIS
        'is_latest': existing_version.is_latest,
        'is_served': existing_version.is_served
    }
```

### Phase 3: Reset Approval on Overwrite

#### Task 3.1: Reset approval state in asset upsert

**File**: `services/asset_service.py` or `infrastructure/asset_repository.py`

When overwrite=True and approval_state is REJECTED or REVOKED, reset to PENDING_REVIEW:

```python
# In create_or_update_asset() after upsert
if overwrite and operation == 'updated':
    current_asset = self._asset_repo.get_by_id(asset_id)
    if current_asset and current_asset.approval_state in (
        ApprovalState.REJECTED, ApprovalState.REVOKED
    ):
        self._asset_repo.update(asset_id, {
            'approval_state': ApprovalState.PENDING_REVIEW,
            'reviewer': None,
            'reviewed_at': None,
            'rejection_reason': None,
            'revoked_at': None,
            'revoked_by': None,
            'revocation_reason': None
        })
        logger.info(f"Reset approval state to PENDING_REVIEW for {asset_id}")
```

---

## Testing Plan

### Test 1: Revocation Flow
1. Submit job → Complete → Approve with OUO
2. Query `/api/platform/status/{request_id}` → Verify approved
3. POST `/api/platform/revoke` with reason
4. Query status → Verify revoked state
5. Verify STAC item still exists but flagged

### Test 2: Overwrite Blocked on APPROVED
1. Submit job → Complete → Approve
2. Re-submit same params with `overwrite=true`
3. Expected: HTTP 400 with message "Asset is approved. Revoke approval before overwriting."

### Test 3: Overwrite After REVOKE
1. Submit job → Complete → Approve → Revoke
2. Re-submit same params with `overwrite=true`
3. Expected: HTTP 202 accepted
4. Query status → Verify `approval_state: pending_review`

### Test 4: Overwrite PENDING_REVIEW
1. Submit job → Complete (stays pending_review)
2. Re-submit same params with `overwrite=true`
3. Expected: HTTP 202 accepted, old data replaced
4. Query status → Verify still `pending_review`

### Test 5: Semantic Version Requires Approved Previous
1. Submit v1.0 → Complete (stays pending_review)
2. Submit v2.0 with `previous_version_id=v1.0`
3. Expected: HTTP 400 with message "Previous version 'v1.0' must be approved"
4. Approve v1.0
5. Re-submit v2.0 with `previous_version_id=v1.0`
6. Expected: HTTP 202 accepted

### Test 6: Semantic Version Chain
1. Submit v1.0 → Complete → Approve
2. Submit v2.0 with `previous_version_id=v1.0` → Complete → Approve
3. Submit v3.0 with `previous_version_id=v2.0`
4. Expected: HTTP 202 accepted
5. Verify lineage: v3.0 → v2.0 → v1.0

---

## Files to Modify

| File | Changes |
|------|---------|
| `services/platform_validation.py` | Add `overwrite` param, approval state checks |
| `services/asset_service.py` | Include approval_state in lineage state, reset on overwrite |
| `triggers/platform/submit.py` | Pass overwrite to validation |
| `infrastructure/asset_repository.py` | (If needed) reset fields helper |

---

## Approval State Transitions

```
                    ┌─────────────┐
         Submit     │             │
        ─────────►  │  PENDING    │
                    │  REVIEW     │
                    │             │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            │
        ┌──────────┐ ┌──────────┐       │
        │          │ │          │       │
        │ APPROVED │ │ REJECTED │       │
        │          │ │          │       │
        └────┬─────┘ └────┬─────┘       │
             │            │             │
             │            │  Overwrite  │
             │ Revoke     └─────────────┘
             │                    │
             ▼                    │
        ┌──────────┐              │
        │          │   Overwrite  │
        │ REVOKED  │──────────────┘
        │          │
        └──────────┘
```

---

## Definition of Done

- [ ] All 6 test scenarios pass
- [ ] Error messages are clear and actionable
- [ ] Approval state correctly resets on overwrite (REJECTED/REVOKED → PENDING_REVIEW)
- [ ] APPROVED assets cannot be overwritten without explicit revoke
- [ ] Semantic versions require approved predecessor
- [ ] UI shows appropriate validation errors
- [ ] OpenAPI spec updated if new error responses added
