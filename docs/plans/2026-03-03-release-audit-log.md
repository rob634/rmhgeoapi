# Spec: Release Audit Log & In-Place Ordinal Revision

**Date**: 03 MAR 2026
**Status**: DRAFT — Pending Review
**Epic**: E10 - Data Lineage & Provenance
**Trigger**: Client requirement to revoke and resubmit corrected data for any historical ordinal version

---

## Problem Statement

A client submits 5 versions of a dataset (ordinals 1-5). They discover version 2 contains incorrect data. They need to:

1. Revoke ordinal 2 (unpublish it)
2. Submit corrected data for ordinal 2
3. Have ordinal 2 re-approved with the corrected data

**Today this is impossible.** Two blockers:

- **Blocker A**: `can_overwrite()` only accepts `PENDING_REVIEW` or `REJECTED` states. `REVOKED` is terminal — no path back to reprocessing.
- **Blocker B**: The stale ordinal guard blocks approval of ordinal 2 when ordinals 3-5 exist as active (APPROVED).

Additionally, `update_overwrite()` destructively resets approval/revocation fields on the release row. If we enable overwrite on revoked releases, the revocation audit trail (who revoked, when, why) is destroyed.

## Design Principles

1. **Audit log, not a restore mechanism.** We record what happened to each ordinal's lifecycle. We do NOT snapshot blobs, store previous data, or enable rollback. This is an append-only event journal.

2. **Orthogonal to semantic versioning.** The audit log tracks release lifecycle events (approved, revoked, overwritten, re-approved). It does not participate in version numbering, ordinal assignment, or the `is_latest` chain. It is a parallel record.

3. **All three data types.** Raster, zarr, vector. The audit log operates at the `AssetRelease` level, which is data-type agnostic. No data-type-specific logic.

4. **Not the happy path.** In-place revision of a revoked ordinal is an exceptional workflow. The normal flow remains: submit → process → approve → done. This feature is the safety net for when that flow produces incorrect output.

5. **Separate from artifact registry.** The artifact registry (`core/models/artifact.py`) tracks blob-level outputs with content hashes and supersession chains. That is a different concern. The release audit log tracks release-level state transitions. They may reference each other but are independently useful.

---

## Component 1: Release Audit Event Table

### Model: `ReleaseAuditEvent`

```
Table: app.release_audit (append-only)

    audit_id        BIGSERIAL PRIMARY KEY
    release_id      VARCHAR(64) NOT NULL    -- FK to asset_releases
    asset_id        VARCHAR(64) NOT NULL    -- denormalized for query efficiency
    version_ordinal INTEGER NOT NULL        -- denormalized (ordinal at event time)
    revision        INTEGER NOT NULL        -- which revision cycle this event belongs to
    event_type      release_audit_event     -- enum (see below)
    actor           VARCHAR(200)            -- who triggered the event (user email or system ID)
    reason          TEXT                    -- human-readable reason (revocation reason, rejection reason, etc.)
    snapshot        JSONB NOT NULL          -- frozen state of the release row at event time
    metadata        JSONB DEFAULT '{}'      -- extensible event-specific data
    created_at      TIMESTAMPTZ DEFAULT NOW()
```

### Enum: `release_audit_event`

```
CREATED             -- release row first inserted
PROCESSING_STARTED  -- job picked up, processing begins
PROCESSING_COMPLETED-- processing finished successfully
PROCESSING_FAILED   -- processing finished with error
APPROVED            -- reviewer approved the release
REJECTED            -- reviewer rejected the release
REVOKED             -- approved release revoked (unpublished)
OVERWRITTEN         -- release row reset for resubmission (the destructive operation)
```

### Indexes

```sql
CREATE INDEX idx_release_audit_release_id ON app.release_audit (release_id);
CREATE INDEX idx_release_audit_asset_id ON app.release_audit (asset_id, version_ordinal);
CREATE INDEX idx_release_audit_event_type ON app.release_audit (event_type);
CREATE INDEX idx_release_audit_created_at ON app.release_audit (created_at);
```

### Snapshot Contents

The `snapshot` JSONB captures the full release row state at the moment of the event. This is the "before" state — what the row looked like before the event's mutation. For `CREATED`, the snapshot is the initial state.

Minimum fields in snapshot:

```json
{
    "release_id": "...",
    "asset_id": "...",
    "version_ordinal": 2,
    "revision": 1,
    "version_id": "v2",
    "approval_state": "approved",
    "processing_status": "completed",
    "is_latest": false,
    "is_served": false,
    "reviewer": "jane@example.com",
    "reviewed_at": "2026-03-01T14:30:00Z",
    "revoked_by": "admin@example.com",
    "revocation_reason": "Incorrect source data used for processing",
    "revoked_at": "2026-03-03T09:15:00Z",
    "job_id": "abc123...",
    "blob_path": "...",
    "table_name": "...",
    "stac_item_json": { ... }
}
```

This is derived from `release.to_dict()` — no new serialization logic needed.

---

## Component 2: Audit Event Emission

### When to Emit

Events are emitted **before the destructive mutation** where applicable. The audit log captures the state that is about to be changed.

| Event | Trigger Location | Snapshot Timing |
|-------|-----------------|-----------------|
| `CREATED` | `release_repository.create()` | After insert (initial state) |
| `PROCESSING_STARTED` | `release_repository.update_processing_status(PROCESSING)` | Before update |
| `PROCESSING_COMPLETED` | `release_repository.update_processing_status(COMPLETED)` | Before update |
| `PROCESSING_FAILED` | `release_repository.update_processing_status(FAILED)` | Before update |
| `APPROVED` | `release_repository.approve_release_atomic()` | Before update |
| `REJECTED` | `asset_approval_service.reject_release()` | Before update |
| `REVOKED` | `release_repository.update_revocation()` | Before update |
| `OVERWRITTEN` | `release_repository.update_overwrite()` | Before reset (CRITICAL — this is the event that preserves revocation audit trail) |

### Emission Pattern

```python
# In release_repository.py, before destructive operations:
def update_overwrite(self, release_id: str, revision: int) -> bool:
    # Snapshot BEFORE reset
    release = self.get_by_id(release_id)
    if release:
        self.audit_repo.record_event(
            release_id=release_id,
            asset_id=release.asset_id,
            version_ordinal=release.version_ordinal,
            revision=release.revision,
            event_type=ReleaseAuditEvent.OVERWRITTEN,
            actor="system",  # or passed from caller
            reason="Release overwritten for resubmission",
            snapshot=release.to_dict()
        )

    # Then proceed with destructive reset
    ...
```

### Non-Fatal Emission

Audit event emission MUST be non-fatal. If the audit insert fails, log a warning and proceed with the operation. The audit log is observability — it must not block the pipeline.

```python
try:
    self.audit_repo.record_event(...)
except Exception as e:
    logger.warning(f"Audit event emission failed (non-fatal): {e}")
```

---

## Component 3: In-Place Revision of Revoked Releases

### Change 1: `can_overwrite()` accepts REVOKED

**File**: `core/models/asset.py:656-662`

```python
# Before:
def can_overwrite(self) -> bool:
    if self.approval_state not in (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED):
        return False
    if self.processing_status == ProcessingStatus.PROCESSING:
        return False
    return True

# After:
def can_overwrite(self) -> bool:
    allowed = (ApprovalState.PENDING_REVIEW, ApprovalState.REJECTED, ApprovalState.REVOKED)
    if self.approval_state not in allowed:
        return False
    if self.processing_status == ProcessingStatus.PROCESSING:
        return False
    return True
```

### Change 2: `update_overwrite()` clears revocation fields

**File**: `infrastructure/release_repository.py:970-1014`

When overwriting a REVOKED release, the revocation fields (`revoked_at`, `revoked_by`, `revocation_reason`) must also be cleared. The audit log preserves the original values.

```sql
UPDATE app.asset_releases
SET revision = %s,
    processing_status = 'pending',
    approval_state = 'pending_review',
    rejection_reason = NULL,
    reviewer = NULL,
    reviewed_at = NULL,
    revoked_at = NULL,          -- NEW: clear revocation fields
    revoked_by = NULL,          -- NEW
    revocation_reason = NULL,   -- NEW
    job_id = NULL,
    processing_started_at = NULL,
    processing_completed_at = NULL,
    last_error = NULL,
    is_served = FALSE,          -- NEW: ensure not served after reset
    updated_at = NOW()
WHERE release_id = %s
```

### Change 3: Stale ordinal guard exemption for previously-approved ordinals

**File**: `services/asset_approval_service.py:166-186`

The current guard blocks approval of ordinal N when ordinal N+1+ exists in a non-terminal state. For in-place revision, ordinal 2 needs to be re-approvable even though ordinals 3-5 are APPROVED.

The distinction: the guard should block approval of **never-before-approved** lower ordinals (out-of-order first approval), but allow **re-approval of previously-approved ordinals** (in-place revision after revocation).

Detection: if the release's `revision > 1`, it has been overwritten at least once. This is the signal that this is a re-approval, not a first-time out-of-order approval.

```python
# Block approval of stale ordinals when a newer ordinal exists (SG5-1/LA-1)
# Exception: revision > 1 means this ordinal was previously approved and is being re-approved
# after revocation + overwrite (in-place revision workflow)
if release.version_ordinal and release.revision == 1:
    newer = self.release_repo.has_newer_active_ordinal(
        release.asset_id, release.version_ordinal
    )
    if newer:
        return {
            'success': False,
            'error': (
                f"Cannot approve ordinal {release.version_ordinal}: "
                f"newer ordinal {newer['version_ordinal']} exists "
                f"(status: {newer['processing_status']}, "
                f"approval: {newer['approval_state']})"
            ),
            'error_type': 'StaleOrdinal',
            ...
        }
```

**Edge case**: What if someone submits a brand new ordinal 2 (not overwrite, not revision) and the guard allows it because revision=2? This can't happen — `get_next_version_ordinal` always returns `MAX+1`. You can't get ordinal 2 assigned to a new release when ordinals 3-5 exist. The only way ordinal 2 gets revision > 1 is via the overwrite path on an existing release.

### Change 4: Submission flow for revoked releases

**File**: `triggers/platform/submit.py` (or `services/asset_service.py`)

When a submission arrives with `overwrite=true` and the target release is REVOKED:

1. Emit `OVERWRITTEN` audit event (captures revocation state)
2. Call `update_overwrite()` (clears all fields, increments revision)
3. Proceed with normal processing pipeline (copy → validate → convert → register)

The existing overwrite flow in `asset_service.py:297-315` already handles `can_overwrite()` checks and calls `update_overwrite()`. Adding `REVOKED` to the allowed states is the only change needed.

### Change 5: Re-approval version_id handling

When ordinal 2 is re-approved, it should retain `version_id = "v2"`. The approval flow at `release_repository.py:approve_release_atomic()` assigns `version_id` based on ordinal. Since the ordinal hasn't changed, `version_id` will be correctly re-assigned as "v2".

Verify: the `NOT EXISTS` guard in `approve_release_atomic` that prevents duplicate `version_id` assignment — does it exclude REVOKED releases? If it checks for `approval_state = APPROVED AND version_id = 'v2'`, and the old ord 2 was REVOKED, the guard should pass. Need to confirm.

---

## Component 4: Query Interface

### Repository Methods

```python
class ReleaseAuditRepository:
    def record_event(self, release_id, asset_id, version_ordinal,
                     revision, event_type, actor, reason, snapshot,
                     metadata=None) -> int  # returns audit_id

    def get_events_for_release(self, release_id) -> List[ReleaseAuditEvent]

    def get_events_for_ordinal(self, asset_id, version_ordinal) -> List[ReleaseAuditEvent]

    def get_events_by_type(self, event_type, limit=50) -> List[ReleaseAuditEvent]

    def get_recent_events(self, hours=24, limit=100) -> List[ReleaseAuditEvent]
```

### Admin Endpoint (optional, low priority)

```
GET /api/admin/audit/release/{release_id}     -- all events for a release
GET /api/admin/audit/ordinal/{asset_id}/{ord}  -- all events for an ordinal across revisions
GET /api/admin/audit/recent?hours=24           -- recent audit events
```

---

## Scenario Walkthrough

**Asset: aerial-imagery / site-alpha, ordinals 1-5 all APPROVED**

### Step 1: Revoke ordinal 2

```
POST /api/platform/revoke
{
    "release_id": "rel-ord2-rev1",
    "reason": "Source data contained incorrect elevation values"
}
```

Audit log emits:
```
REVOKED | release=rel-ord2 | ordinal=2 | revision=1 | actor=admin@wb.org
  reason: "Source data contained incorrect elevation values"
  snapshot: { approval_state: "approved", reviewer: "jane@wb.org", ... }
```

Release row: `approval_state=REVOKED, revoked_by=admin@wb.org, revoked_at=NOW()`

STAC item deleted, routes deleted, `is_latest` unaffected (ordinal 5 is latest).

### Step 2: Submit corrected data for ordinal 2

```
POST /api/platform/submit
{
    "dataset_id": "aerial-imagery",
    "resource_id": "site-alpha",
    "processing_options": { "overwrite": true },
    ...
}
```

System finds existing release for this asset at ordinal 2 (state: REVOKED).
`can_overwrite()` returns True (REVOKED is now allowed).

Audit log emits:
```
OVERWRITTEN | release=rel-ord2 | ordinal=2 | revision=1 | actor=system
  reason: "Release overwritten for resubmission"
  snapshot: { approval_state: "revoked", revoked_by: "admin@wb.org", ... }
```

`update_overwrite()` resets row: `revision=2, approval_state=PENDING_REVIEW, processing_status=PENDING, revoked_by=NULL, ...`

Processing pipeline runs: copy → validate → convert → register.

### Step 3: Approve corrected ordinal 2

```
POST /api/platform/approve
{
    "release_id": "rel-ord2",
    "reviewer": "jane@wb.org"
}
```

Stale ordinal guard: `release.revision == 2 > 1` → guard is skipped (in-place revision).

Approval proceeds normally. `version_id = "v2"` re-assigned.

Audit log emits:
```
APPROVED | release=rel-ord2 | ordinal=2 | revision=2 | actor=jane@wb.org
  snapshot: { approval_state: "pending_review", revision: 2, ... }
```

### Result

- Ordinal 2 is now APPROVED at revision 2 with corrected data
- Ordinals 1, 3, 4, 5 untouched
- Ordinal 5 remains `is_latest`
- Full audit trail preserved: created → approved (rev 1) → revoked → overwritten → approved (rev 2)

---

## Files Modified

| File | Change | Size |
|------|--------|------|
| `core/models/audit.py` | **NEW** — `ReleaseAuditEvent` model + enum | ~100 lines |
| `infrastructure/release_audit_repository.py` | **NEW** — append-only CRUD | ~150 lines |
| `core/models/asset.py` | `can_overwrite()` accepts REVOKED | 1 line |
| `infrastructure/release_repository.py` | `update_overwrite()` clears revocation fields + emits audit | ~15 lines |
| `infrastructure/release_repository.py` | Audit emission hooks on state transitions | ~40 lines |
| `services/asset_approval_service.py` | Stale ordinal guard exemption for revision > 1 | ~5 lines |
| `core/schema/sql_generator.py` | Register new model for table generation | ~5 lines |

**Estimated total**: ~350 lines new, ~60 lines modified

---

## Out of Scope

- **Blob-level restore**: No mechanism to recover previous blob data. The audit log records that ordinal 2 was overwritten; it does not store the old COG/Zarr/vector data.
- **Automatic re-processing**: The overwrite still requires a new submission with corrected source data. There is no "undo revocation" button.
- **Artifact registry changes**: The existing artifact system (`core/models/artifact.py`) is unchanged. It will independently track the new blob output for ordinal 2 revision 2 via its own supersession chain.
- **UI for audit trail**: Admin endpoints are optional/low priority. The audit table is queryable via SQL.
- **Retention policy**: No automatic cleanup of old audit events. Append-only, grow forever (rows are small).

---

## Open Questions

1. **Overwrite target resolution**: When `overwrite=true` arrives, how does the submission flow determine WHICH release to overwrite? Today it finds the draft for the asset. For the revoked-ordinal case, we need to target a specific ordinal. Does the caller pass `version_ordinal` explicitly, or do we find the most recently revoked release?

2. **Multiple revoked ordinals**: If ordinals 2 AND 3 are both revoked, and the client submits with `overwrite=true`, which one gets overwritten? First-revoked? Most-recently-revoked? Should the client specify?

3. **`version_id` conflict guard**: The atomic approval SQL has a `NOT EXISTS` check preventing duplicate `version_id` assignment. When re-approving ordinal 2 as "v2", does the guard correctly exclude REVOKED releases from the conflict check? Needs code verification.

4. **STAC re-materialization**: When ordinal 2 is re-approved, a new STAC item is created. The old one was deleted at revocation. Should the STAC item ID be identical to the original, or should it reflect the revision?
