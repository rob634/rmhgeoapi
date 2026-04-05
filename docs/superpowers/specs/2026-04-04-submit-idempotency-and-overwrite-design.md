# Submit Idempotency and Overwrite Validation Spec

**Date**: 04 APR 2026
**Status**: DRAFT
**Scope**: `POST /api/platform/submit` — guard logic for duplicate submissions, overwrites, and version advances

---

## Problem

Identical resubmissions without explicit intent create ambiguous state. The submit path must distinguish three intents:

1. **First submission** — no prior release exists. Create and process.
2. **Revision (overwrite)** — caller wants to reprocess the same version slot. Requires `overwrite: true`.
3. **Version advance** — caller wants a new semantic version. Requires a new `version_id` that differs from the current one.

An identical resubmission with no flags should be **rejected with a descriptive error**, not silently create a new ordinal.

---

## Overwrite Gate: Two States

From the overwrite flag's perspective, there are exactly two states:

| State | `overwrite: true` | Rationale |
|-------|-------------------|-----------|
| **Approved** | BLOCKED | Sacred state. Must revoke first. |
| **Not approved** | ALLOWED | Includes: `pending_review`, `rejected`, `failed`, `revoked` |

### Why approved is blocked

An approved release is "out there" — STAC items are published, service URLs are live, consumers may depend on it. Casual overwriting would silently replace published data. The caller must explicitly revoke (which deletes STAC, removes routes, creates audit trail) before reprocessing.

---

## Decision Matrix

Given a submission with `(dataset_id, resource_id, version_id)` that matches an existing release:

| Existing release state | No flags | `overwrite: true` | New `version_id` |
|------------------------|----------|--------------------|-------------------|
| `pending_review` | REJECT | ALLOW — reprocess same slot | REJECT — complete or reject current first |
| `rejected` | REJECT | ALLOW — reprocess same slot | REJECT — complete or reject current first |
| `failed` | REJECT | ALLOW — reprocess same slot | REJECT — complete or reject current first |
| `approved` | REJECT | REJECT — revoke first | ALLOW — new ordinal |
| `revoked` | REJECT | ALLOW — reprocess same slot | ALLOW — new ordinal |
| *(no release)* | ALLOW — first submission | N/A | N/A |

### Rejection messages

| Scenario | Message |
|----------|---------|
| Identical resubmit, release exists, no flags | `"Release already exists for {dataset_id}/{resource_id} {version_id} (state: {state}). Use overwrite: true to revise, or submit with a new version_id to advance version."` |
| `overwrite: true` but release is approved | `"Cannot overwrite approved release. Revoke first via POST /api/platform/revoke, then resubmit with overwrite: true."` |
| New `version_id` but unapproved release exists for current version | `"Cannot advance version while {version_id} is in state '{state}'. Approve, reject, or overwrite the current release first."` |

---

## Overwrite Behavior (Not Approved States)

When `overwrite: true` and the target is not approved:

| State | Cleanup required | Notes |
|-------|------------------|-------|
| `pending_review` | Cancel/fail running workflow if active. Delete structural STAC (state 2). | Active workflow may have partial outputs on mount/blob. |
| `rejected` | Delete structural STAC if present. | Clean slate — prior processing already stopped. |
| `failed` | No cleanup — prior run already terminated. | May have partial blobs; new run overwrites. |
| `revoked` | No cleanup — revoke already deleted STAC and routes. | Slot is clean. |

After cleanup, the overwrite path:
1. Resets `processing_status` to `pending`
2. Increments `revision` counter (same `version_ordinal`)
3. Submits new workflow run
4. Links new `workflow_id` to release

---

## Version Advance Behavior

When `version_id` differs from the current release's version and the current release is in a terminal state (`approved` or `revoked`):

1. Creates new release at next `version_ordinal`
2. `revision` starts at 1
3. Submits new workflow run
4. Independent lifecycle — prior version unaffected

### Guard: No version advance over in-progress work

If the current release is `pending_review`, `rejected`, or `failed`, a version advance is blocked. The caller must resolve the current version first (approve it, reject it, or overwrite it). This prevents orphaned releases.

---

## Idempotent Response (No Flags, Release Exists)

When the submission matches an existing release and no action flags are provided, return HTTP 409:

```json
{
    "success": false,
    "error": "Release already exists for dc-imagery/dctest-apr04b v1 (state: approved). Use overwrite: true to revise, or submit with a new version_id to advance version.",
    "error_type": "ReleaseExistsError",
    "existing_release": {
        "release_id": "18947cfa...",
        "approval_state": "approved",
        "version_id": "v1",
        "version_ordinal": 1,
        "monitor_url": "/api/platform/status/eca83c3f..."
    }
}
```

This gives the caller full context to decide their next action.

---

## Implementation Checklist

### Guard in submit path (`triggers/platform/submit.py`)

- [ ] After asset/release lookup, before job creation: check if release exists for this `(asset_id, version_id)` triple
- [ ] If release exists and no `overwrite` flag and no version advance: return 409 with descriptive error
- [ ] If `overwrite: true` and release is `approved`: return 409 with "revoke first" message
- [ ] If new `version_id` and current release is not terminal: return 409 with "resolve current first" message

### Overwrite cleanup

- [ ] Cancel active workflow run if `pending_review` (set run status to FAILED, let janitor clean up)
- [ ] Delete structural STAC items (state 2) from pgSTAC
- [ ] Reset release: `processing_status=pending`, increment `revision`, clear `workflow_id`

### Version advance guard

- [ ] Verify no in-progress (non-terminal) release exists for this asset before creating new ordinal
- [ ] New `version_id` must differ from all existing version_ids for this asset

### Tests (SIEGE-DAG sequences)

- [ ] D-IDEM-1: Identical submit, no flags, release exists → 409
- [ ] D-IDEM-2: `overwrite: true`, release `pending_review` → new workflow, same ordinal
- [ ] D-IDEM-3: `overwrite: true`, release `approved` → 409 "revoke first"
- [ ] D-IDEM-4: `overwrite: true`, release `revoked` → new workflow, same ordinal
- [ ] D-IDEM-5: New `version_id`, prior approved → new ordinal
- [ ] D-IDEM-6: New `version_id`, prior `pending_review` → 409 "resolve current first"
- [ ] D-IDEM-7: First submission, no prior release → normal create
