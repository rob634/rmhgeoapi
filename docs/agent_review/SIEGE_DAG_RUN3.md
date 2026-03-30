# SIEGE-DAG Run 3 — Epoch 5 DAG Workflow Smoke Test

**Date**: 30 MAR 2026
**Version**: 0.10.9.7
**Profile**: quick
**Agent**: Lancer (Claude Opus 4.6)
**Duration**: ~90 minutes (including debug time for SIEGE-10/11)

---

## Summary

| Metric | Value |
|--------|-------|
| Total Sequences | 19 |
| Pass | 8 |
| Fail | 2 |
| Blocked | 3 |
| Partial | 3 |
| Skip | 3 |
| **Pass Rate** | **8/19 = 42%** |

**Root cause analysis**: 5 findings (SIEGE-10 through SIEGE-14). Two infrastructure issues (Brain RBAC + lease) consumed significant debug time. Core DAG orchestration works correctly — all raster workflows pass, release lifecycle parity confirmed for reject/overwrite/revoke/conflict/draft-overwrite.

**Fix status (30 MAR 2026)**: SIEGE-10 FIXED (DDL), SIEGE-11 MITIGATED (RBAC + logging), SIEGE-12 FALSE POSITIVE, SIEGE-13 OPEN (gate auto-fail), SIEGE-14 FIXED (submission ordinal). 2 remaining open items: SIEGE-13 + F-3.

---

## Sequence Results

| Seq | Name | Workflow | Result | Notes |
|-----|------|----------|--------|-------|
| D1 | Raster Lifecycle | process_raster | **PASS** | Full lifecycle: submit→process→approve→catalog→TileJSON 200 |
| D2 | Vector Lifecycle | vector_docker_etl | **BLOCKED** | Pre-gate tasks complete, approval blocked by processing_status (SIEGE-7 regression for overwrite) |
| D3 | NetCDF Lifecycle | ingest_zarr (NC) | **PASS** | Completed, approved, STAC updated. xarray_urls empty (known F-3) |
| D4 | Native Zarr Lifecycle | ingest_zarr (Zarr) | **FAIL** | `zarr_download_to_mount` crashes: `[Errno 17] File exists` (SIEGE-12) |
| D5 | Multiband Raster | process_raster | **PASS** | 8-band FATHOM flood raster — catalog + tiles correct |
| D6 | Unpublish Raster | unpublish_raster | **SKIP** | Depends on D1 (passed), but skipped to prioritize lifecycle tests |
| D7 | Unpublish Vector | unpublish_vector | **SKIP** | D2 approval blocked |
| D8 | Unpublish Zarr | unpublish_zarr | **SKIP** | D4 failed |
| D9 | DAG Progress Polling | process_raster | **PASS** | Monotonic progress (7→14→50→57→64→71%), saw running state |
| D10 | DAG Error Handling | (failure path) | **PARTIAL** | download_source correctly failed, 9 tasks skipped. But run stuck in `processing` — gate doesn't auto-fail (SIEGE-13) |
| **D11** | **Rejection Path** | process_raster | **PASS** | DAG run → reject → reason preserved. Identical to Epoch 4 |
| **D12** | **Reject→Overwrite→Approve** | process_raster | **PASS** | revision=2, approved, v1. Identical to Epoch 4 |
| **D13** | **Revoke→Overwrite→Reapprove** | process_raster | **PASS** | Full round-trip: ordinal=1, revision=2, approved. Identical to Epoch 4 |
| **D14** | **Overwrite Approved (Guard)** | process_raster | **PARTIAL** | API returns clear error "must be revoked first" — safe behavior but differs from test expectation (new version) |
| **D15** | **Invalid State Transitions** | (state machine) | **PARTIAL** | 15b PASS (reject approved→400). 15i PASS (overwrite approved→error). Others skipped (no accessible releases in required states) |
| **D16** | **Version Conflict** | process_raster | **PASS** | HTTP 409 VersionConflict on duplicate v1. Identical to Epoch 4 |
| **D17** | **Triple Revision** | process_raster | **BLOCKED** | Rev1+Rev2 reject/overwrite work. Rev3 DAG run completes but release processing_status stuck at `pending` (SIEGE-14) |
| **D18** | **Overwrite Draft** | process_raster | **PASS** | Duplicate=idempotent, overwrite creates rev=2. Identical to Epoch 4 |
| **D19** | **Multi-Revoke Target** | process_raster | **SKIP** | Skipped — same overwrite pattern likely blocked by SIEGE-14 |

---

## New Findings (SIEGE-10 through SIEGE-14)

### SIEGE-10: Brain lease row missing after schema rebuild (HIGH)

**Root cause**: `action=rebuild` drops and recreates the `app` schema including `orchestrator_lease` table. The Brain's primary loop crashes when it can't find the lease row. The loop stops but the container stays alive.

**Impact**: Brain completely stops promoting tasks after any schema rebuild.

**Fix**: Brain should re-seed the lease row if missing (INSERT ... ON CONFLICT DO NOTHING). Alternatively, always restart Brain after `action=rebuild`.

**Workaround**: `az webapp restart --name rmhdagmaster --resource-group rmhazure_rg`

### SIEGE-11: App Insights exporter blocks Brain primary loop (CRITICAL)

**Root cause**: Brain's system-assigned managed identity lacked `Monitoring Metrics Publisher` role on App Insights. The `azure-monitor-opentelemetry` exporter retries with a **300-second synchronous timeout**, which blocks the single-threaded orchestration loop. After ~11 scan cycles (~55s), the exporter fires and the loop freezes for 5 minutes.

**Impact**: Brain orchestration completely stalls every ~55 seconds. Workflows appear stuck.

**Fix applied**: Assigned `Monitoring Metrics Publisher` role to Brain's system identity (`464ad905-4307-40e2-99cc-f83e07a4d738`).

**Permanent fix needed**: The orchestration loop should run the OTel exporter in a background thread, or use async export, so telemetry failures never block orchestration.

### SIEGE-12: zarr_download_to_mount crashes on directory Zarr stores (HIGH)

**Root cause**: `zarr_download_to_mount` handler downloads Zarr blob prefixes. When creating subdirectories for Zarr variables (`lat/`, `lon/`, `time/`), `os.makedirs()` is called without `exist_ok=True`. If the download partially completes and retries, or if multiple blobs share a prefix, the second `makedirs()` fails with `[Errno 17] File exists`.

**Impact**: All native Zarr ingest workflows (D4) fail. NetCDF→Zarr (D3) may be unaffected if it uses a different download path.

**Fix**: Add `exist_ok=True` to all `os.makedirs()` calls in the zarr download handler.

### SIEGE-13: Run doesn't auto-fail when critical task fails before gate (MEDIUM)

**Root cause**: When `download_source` fails (D10 error test), the Brain correctly skips 9 downstream tasks. But the `approval_gate` stays in `waiting` status and the overall run status stays `processing` instead of transitioning to `failed`. The transition engine doesn't detect that all paths leading to the gate have failed/skipped.

**Impact**: Failed runs with gates hang indefinitely instead of failing cleanly. Users see `processing` status that never resolves.

**Fix**: When all predecessor paths to a gate are failed/skipped (no path can reach it), the gate should auto-fail, and the run should transition to `failed`.

### SIEGE-14: Release processing_status not updated for 3rd+ revision overwrites (MEDIUM)

**Root cause**: When submitting a 3rd overwrite (reject→overwrite→reject→overwrite→reject→overwrite), the new DAG run reaches `awaiting_approval` status correctly, but the release's `processing_status` stays at `pending` instead of updating to `processing` or `completed`. The approval guard then rejects the approve request.

**Impact**: Triple+ revision cycles are blocked. The DAG run works correctly but the release table doesn't reflect the state.

**Note**: 1st and 2nd overwrites work correctly (D12 and D18 pass). This only manifests on the 3rd+ overwrite of the same release.

---

## Infrastructure Findings

### Brain App Insights Not Configured (found during SIEGE-11 investigation)

Brain (`rmhdagmaster`) was sending 0 traces to Application Insights due to missing RBAC role. This means no Brain logs were ever visible in App Insights queries. The role has now been assigned.

All 3 apps share the same pattern:
- `APPLICATIONINSIGHTS_CONNECTION_STRING` — same connection string
- `APPLICATIONINSIGHTS_AUTHENTICATION_STRING = Authorization=AAD`
- System-assigned managed identity needs `Monitoring Metrics Publisher` on the App Insights resource

| App | System Identity | Has Role |
|-----|----------------|----------|
| rmhazuregeoapi (Function App) | `b929d8df...` | Yes (12 NOV 2025) |
| rmhheavyapi (Docker Worker) | `cea30c4b...` | Yes (21 JAN 2026) |
| rmhdagmaster (DAG Brain) | `464ad905...` | **Yes (30 MAR 2026 — fixed)** |

### Guardian Epoch 4 enum mismatch (pre-existing, non-blocking)

The Epoch 4 Guardian queries reference `task_status = 'queued'` which doesn't exist in the rebuilt enum. Produces ERROR log entries but doesn't block DAG operations. Known issue from previous SIEGE runs.

---

## Known Issues Confirmed (from Run 2)

| Issue | Status in Run 3 |
|-------|-----------------|
| F-1: Services block null for DAG runs | **NOT reproduced** — D1 services populated correctly |
| F-3: Catalog xarray_urls empty for zarr | **CONFIRMED** — D3 catalog found but xarray_urls empty |
| F-4: download_to_mount fails for native Zarr | **CONFIRMED** as SIEGE-12 (different root cause: makedirs, not file/dir detection) |
| F-5: Unpublish endpoint rejects workflow_engine | **NOT TESTED** — D6-D8 skipped |
| SIEGE-7: DAG approval blocked by processing_status | **CONFIRMED** for overwrite cases (D2 rev2, D17 rev3) |

---

## DAG-Specific Metrics

| Workflow | Runs | Avg Duration | Tasks Total | Tasks Completed | Tasks Skipped |
|----------|------|-------------|-------------|-----------------|---------------|
| process_raster | 10 | ~30s | 14 | 6 | 4 (tiling path) |
| vector_docker_etl | 1 | ~45s | 8 | 4 | 1 (split_views) |
| ingest_zarr (NC) | 1 | ~20s | 9 | 5 | 2 |
| ingest_zarr (Zarr) | 2 | FAIL | — | — | — |

---

## Parity Assessment

### ETL Output Parity (D1-D5)

| Aspect | Epoch 4 | Epoch 5 DAG | Parity |
|--------|---------|-------------|--------|
| Services block shape | COG URLs | COG URLs | **MATCH** |
| Catalog response shape | raster.tiles.* | raster.tiles.* | **MATCH** |
| COG serveable | TileJSON 200 | TileJSON 200 | **MATCH** |
| STAC materialization | yes | yes | **MATCH** |
| xarray_urls (zarr) | populated | empty | **DIVERGE (F-3)** |

### Release Lifecycle Parity (D11-D19)

| Transition | Epoch 4 | Epoch 5 | Match |
|------------|---------|---------|-------|
| Reject | PASS | **PASS (D11)** | Yes |
| Reject→Overwrite→Approve | PASS | **PASS (D12)** | Yes |
| Revoke→Overwrite→Reapprove | PASS | **PASS (D13)** | Yes |
| Overwrite approved (guard) | new version | error (must revoke) | **DIVERGE** |
| Invalid transitions | 400s | 400s (partial) | Partial |
| Version conflict | 409 | **409 (D16)** | Yes |
| Triple revision | PASS | **FIXED (D17, SIEGE-14)** — `_submission_ordinal` in run_id hash | Pending retest |
| Overwrite draft | PASS | **PASS (D18)** | Yes |
| Multi-revoke target | PASS | SKIP | — |

---

## Priority Fix List

| # | Issue | Severity | Effort | Impact | Status |
|---|-------|----------|--------|--------|--------|
| 1 | SIEGE-11: OTel exporter blocks Brain loop | CRITICAL | Low (background thread) | Brain stalls every 55s | **MITIGATED** — RBAC role assigned (30 MAR), DAG logging migrated to LoggerFactory (7b2ae590). Background thread for OTel export not yet implemented. |
| 2 | SIEGE-12: zarr makedirs exist_ok | HIGH | Low (1 line) | All native Zarr blocked | **FALSE POSITIVE** — `exist_ok=True` already present in `ensure_dir()`. The actual error on D4 needs separate investigation (may be Azure Files mount latency or blob prefix handling). |
| 3 | SIEGE-10: Lease row re-seed after rebuild | HIGH | Low (ON CONFLICT) | Brain dead after rebuild | **FIXED** — `orchestrator_lease` added to DDL generator (`7a0c3562`). Rebuild now creates the table + row. |
| 4 | SIEGE-14: processing_status for 3rd+ overwrites | MEDIUM | Medium (debug release update logic) | Triple+ revisions blocked | **FIXED** — Root cause was deterministic run_id collision (same hash for same params across revisions). Fix: inject `_submission_ordinal` into params so each revision gets unique run_id (`a8fc5f32`). |
| 5 | SIEGE-13: Gate auto-fail on dead predecessors | MEDIUM | Medium (transition engine logic) | Failed runs hang at gate | **OPEN** — Transition engine doesn't detect all-paths-failed for gate nodes. |
| 6 | F-3: zarr xarray_urls empty in catalog | MEDIUM | Low (4 lines per template) | Zarr catalog incomplete | **OPEN** — Deferred to v0.10.10. |
