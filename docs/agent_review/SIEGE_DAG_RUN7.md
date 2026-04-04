# SIEGE-DAG Run 7

**Date**: 04 APR 2026
**Version**: v0.10.9.17 (all 3 apps)
**Environment**: Fresh schema rebuild before D1-D4 (Run 6). D1-D4 data live from prior run.
**Operator**: Claude Opus 4.6 (SIEGE-DAG agent)
**Scope**: D5-D19 (lifecycle, unpublish, approval state machine, revision control)

---

## Results Summary

| Metric | Value |
|--------|-------|
| Total sequences | 15 (D5-D19) |
| Pass | 12 |
| Partial Pass | 1 |
| Fail | 2 |
| **Pass Rate** | **12/15 = 80%** |

---

## Sequence Results

| Seq | Name | Workflow | Result | Duration | Notes |
|-----|------|----------|--------|----------|-------|
| D5 | Multiband Raster | process_raster (DAG) | **PASS** | ~90s to gate | 8-band FATHOM flood. Approved. Service URLs present (tilejson, preview, STAC, viewer, tiles). `is_served=true`. |
| D6 | Unpublish Raster (D1) | unpublish_raster (E4) | **PASS** | ~10s | `approval_state=revoked`, `is_served=false`. Required `force_approved=true` and `dry_run=false`. |
| D7 | Unpublish Vector (D2) | unpublish_vector (E4) | **FAIL** | ~17s | Job completed, table dropped, metadata deleted. But release NOT revoked: `approval_state=approved`, `is_served=true`. `release_revoked=false` in task result. See SIEGE-18. |
| D8 | Unpublish Zarr (D3) | unpublish_zarr (E4) | **FAIL** | stuck (14m+) | `unpublish_inventory_zarr` task failed after 3 janitor retries ("max retries exhausted"). Job stuck at `processing` despite task `failed`. Release still `approved`/`is_served=true`. See SIEGE-19. |
| D9 | DAG Progress Polling | process_raster (DAG) | **PARTIAL** | ~25s (too fast) | Workflow completed before polling could capture `running` state. All polls showed `awaiting_approval`. dctest.tif is small/cached. Monotonic increase not testable. Approved successfully. |
| D10 | Error Handling | process_raster (DAG) | **PASS** | <1s | Pre-flight rejection: "Blob 'does-not-exist.tif' does not exist in container 'rmhazuregeobronze'". Clean error, no orphans. |
| D11 | Rejection Path | process_raster (DAG) | **PASS** | ~30s | `approval_state=rejected`, `is_served=false`, `rejection_reason="SIEGE test rejection"` preserved. |
| D12 | Reject->Overwrite->Approve | process_raster (DAG) | **PASS** | ~30s | `revision=2`, `is_served=true`, `approval_state=approved`. STAC materialized. |
| D13 | Revoke->Overwrite->Reapprove | process_raster (DAG) | **PASS** | ~30s | `revision=3`, `is_served=true`, `approval_state=approved`. STAC re-materialized. |
| D14 | Overwrite Approved Guard | -- | **PASS** | <1s | ReleaseStateError: "must be revoked before it can be overwritten". |
| D15 | Invalid State Transitions | -- | **PASS** | <1s each | All 4 cases return 400: (a) approve approved, (b) reject approved, (c) revoke pending_review, (d) approve revoked. Clear error messages with remediation hints. |
| D16 | Version Conflict | process_raster (DAG) | **PASS** | <1s | Double-approve returns 400: "approval_state is 'approved', expected 'pending_review'". |
| D17 | Triple Revision | process_raster (DAG) | **PASS** | ~3m30s | 3 cycles (reject, overwrite, reject, overwrite, approve). `revision=3`, `approval_state=approved`, `is_served=true`. |
| D18 | Overwrite Draft | process_raster (DAG) | **PASS** | ~30s | Idempotent response: same `request_id` and `job_id` returned for duplicate submission. No new ordinal created. |
| D19 | Multi-Revoke Target | process_raster (DAG) | **PASS** | ~2m | v1 approved -> revoked -> v2 overwrite -> approved. `revision=2`, `is_served=true`. Same release_id reused (ordinal preserved, revision incremented). |

---

## New Findings

### SIEGE-18 (NEW): Vector unpublish does not revoke release

**Severity**: HIGH
**Component**: `unpublish_drop_table` handler (Epoch 4)
**Symptom**: Vector unpublish job completes successfully (table dropped, metadata deleted, TiPG refreshed) but release remains `approval_state=approved`, `is_served=true`.
**Evidence**: Task result shows `"release_revoked": false`. The handler has revocation logic (SIEGE-17 fix from Run 5) but it does not execute.
**Root cause**: Likely the Epoch 4 `unpublish_drop_table` handler's release revocation path is not triggered when `release_id` lookup fails or is not wired correctly for vector data type.
**Impact**: After unpublish, the system reports the vector as still served even though the underlying table is gone. Stale services would return errors.
**Note**: D6 raster unpublish DID revoke the release successfully, so this is vector-specific.

### SIEGE-19 (NEW): Zarr unpublish Epoch 4 task fails on janitor reclaim

**Severity**: HIGH
**Component**: `unpublish_inventory_zarr` handler (Epoch 4)
**Symptom**: Task reclaimed by janitor 3 times then marked failed. Job stuck at `processing` (never transitions to `failed`).
**Evidence**: Task error: "Janitor: max retries exhausted (3/3)". Job `updated_at` never changes after initial creation. Zero heartbeat updates.
**Root cause**: The `unpublish_inventory_zarr` handler likely hangs or times out during execution. Known issue pattern: execution exceeds heartbeat threshold, janitor reclaims.
**Impact**: Zarr data cannot be unpublished via Epoch 4 path. Release remains `approved`/`is_served=true`.
**Secondary**: Job status stays `processing` indefinitely despite all tasks being `failed` -- Epoch 4 CoreMachine does not detect terminal task failure as job failure.

### D9 Progress Observation

Small cached files (dctest.tif) complete too fast for progress polling. The DAG workflow goes from `running` to `awaiting_approval` within the first poll interval. Progress monotonicity could not be verified. Use larger files for progress polling tests.

---

## API Notes

- `clearance_state` at approval must be `"ouo"` or `"public"`, not `"cleared"` (D5 first attempt returned validation error).
- Revoke endpoint requires both `reviewer` and `reason` fields (not just reviewer).
- Unpublish endpoint requires `dry_run=false` explicitly (defaults to `true`).
- Unpublish of approved releases requires `force_approved=true`.
- `data_type` is NOT a valid field in the submit payload (extra='forbid' on PlatformRequest model). Data type is auto-detected from file extension.
- `workflow_engine` IS accepted (popped before Pydantic validation, restored for routing).

---

## Comparison with Run 5

| Aspect | Run 5 | Run 7 |
|--------|-------|-------|
| Version | v0.10.9.13 | v0.10.9.17 |
| Pass rate | 84% (16/19) | 80% (12/15) |
| D5 Multiband | PASS | PASS |
| D6 Raster unpublish | PASS | PASS |
| D7 Vector unpublish | FAIL (release not updated) | FAIL (same issue persists -- SIEGE-18) |
| D8 Zarr unpublish | PASS | FAIL (task hangs, janitor reclaim -- SIEGE-19) |
| D10 Error handling | PASS | PASS |
| D11 Rejection | PASS | PASS |
| D12 Reject->Overwrite->Approve | PASS | PASS |
| D13 Revoke->Overwrite->Reapprove | PASS | PASS |
| D14 Overwrite guard | PASS | PASS |
| D15 Invalid transitions | PASS | PASS |
| D16 Version conflict | PASS | PASS |
| D17 Triple revision | PASS | PASS |
| D18 Overwrite draft | N/A (design note) | PASS (idempotent) |
| D19 Multi-revoke | PASS | PASS |

**Regression**: D8 (zarr unpublish) passed in Run 5 but fails in Run 7. Possible regression in `unpublish_inventory_zarr` handler or environment change.

---

## Deferred Fix Candidates

| ID | Finding | Severity | Recommendation |
|----|---------|----------|----------------|
| DF-UNPUB-2 | Vector unpublish does not revoke release (SIEGE-18) | HIGH | Wire release_id lookup in `unpublish_drop_table` for vector path |
| DF-UNPUB-3 | Zarr unpublish E4 task hangs (SIEGE-19) | HIGH | Investigate heartbeat failure in `unpublish_inventory_zarr`; also fix E4 job status propagation |
| DF-JOB-1 | E4 job stuck at `processing` when all tasks failed | MEDIUM | CoreMachine should detect terminal task failure and transition job to `failed` |
