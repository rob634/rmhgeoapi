# SIEGE-DAG Run 5

**Date**: 01 APR 2026 (executed 02 APR 2026 UTC)
**Version**: v0.10.9.13 (all 3 apps)
**Environment**: Fresh schema rebuild + STAC nuke + app restart
**Operator**: Claude Opus 4.6 (SIEGE-DAG agent)

---

## Results Summary

| Metric | Value |
|--------|-------|
| Total sequences | 19 |
| Pass | 16 |
| Partial Pass | 1 |
| Fail | 1 |
| N/A (design note) | 1 |
| **Pass Rate** | **16/19 = 84%** (up from 53% in Run 4) |

---

## Sequence Results

| Seq | Name | Workflow | Result | Duration | Notes |
|-----|------|----------|--------|----------|-------|
| D1 | Raster Lifecycle | process_raster | **PASS** | 35s to gate, ~60s total | Full lifecycle. All 6 service probes 200. |
| D2 | Vector Lifecycle | vector_docker_etl | **PARTIAL PASS** | 23s to gate | **SIEGE-7: RESOLVED** — processing_status=completed at gate. Approval succeeded. Post-gate `register_catalog` failed: VARCHAR(100) too short. |
| D3 | NetCDF Lifecycle | ingest_zarr (NC) | **PASS** | ~30s | Encoding bug **CONFIRMED FIXED**. Full lifecycle works. |
| D4 | Native Zarr Lifecycle | ingest_zarr (Zarr) | **PASS** | ~23s | Chunk alignment bug **CONFIRMED FIXED**. Full lifecycle works. |
| D5 | Multiband Raster | process_raster | **PASS** | ~5min to gate | 8-band FATHOM flood. All tiles serve. Preview needs `bidx=1` for multiband. |
| D6 | Unpublish Raster | unpublish_raster | **PASS** | ~14s | STAC removed, is_served=false, approval_state=revoked. |
| D7 | Unpublish Vector | unpublish_vector | **FAIL** | ~15s | Table dropped but release NOT updated (still approved/is_served=true). New bug. |
| D8 | Unpublish Zarr | unpublish_zarr | **PASS** | ~27s | Full cleanup. Fan-out blob deletion. STAC removed. |
| D9 | DAG Progress Polling | process_raster | **PASS** | ~45s to gate | Monotonic: 7%→50%→57%→64%→100%. Running state observed. |
| D10 | Error Handling | process_raster | **PASS** | <1s | Pre-flight reject (blob not found). Clean, no orphans. |
| D11 | Rejection Path | process_raster | **PASS** | ~35s | approval_state=rejected, reason preserved. |
| D12 | Reject→Overwrite→Approve | process_raster | **PASS** | ~23s | revision=2, version_id=v1, STAC materialized. |
| D13 | Revoke→Overwrite→Reapprove | process_raster | **PASS** | ~36s | revision=3, version_id=v2, STAC re-materialized. |
| D14 | Overwrite Approved Guard | — | **PASS** | <1s | HTTP 409: "must be revoked before overwrite". |
| D15 | Invalid Transitions (4 cases) | — | **PASS** | <1s each | All return 400 with descriptive error messages. |
| D16 | Version Conflict | process_raster | **PASS** | ~35s | Duplicate approve returns 400 (state guard). |
| D17 | Triple Revision | process_raster | **PASS** | ~3m16s | 3 reject-overwrite cycles. revision=3, approved. |
| D18 | Overwrite Draft | process_raster | **N/A** | ~1m19s | Creates new ordinal (non-destructive). Original orphaned at pending_review. Design note, not a bug. |
| D19 | Multi-Revoke Target | process_raster | **PASS** | ~2m7s | Revoke→overwrite→approve v2. Same release_id reused. |

---

## Previously Open Bugs — Status

| Bug | Run 4 Status | Run 5 Status | Evidence |
|-----|-------------|-------------|----------|
| **SIEGE-7** (approval blocked for overwrites) | OPEN | **RESOLVED** | D2: processing_status=completed at gate, approval succeeded, revision=2 |
| **SIEGE-15** (double /vsiaz/ prefix) | OPEN | **RESOLVED** | D1: all 6 service URL probes return 200 |
| **D3** (NetCDF encoding error) | FAIL | **PASS** | Full NC→Zarr→pyramid lifecycle completes |
| **D4** (Zarr chunk alignment) | FAIL | **PASS** | Full Zarr→pyramid lifecycle completes |

---

## New Findings

### BUG: D2 — `register_catalog` VARCHAR(100) overflow

**Severity**: MEDIUM
**Sequence**: D2 (vector lifecycle, post-gate)
**Error**: `non-retryable: value too long for type character varying(100)`
**Impact**: Vector post-approval catalog registration fails. Pre-gate processing, approval, and table creation all succeed. The data IS served via TiPG but not registered in the platform catalog.
**Root cause**: A URL or identifier exceeding 100 characters is being written to a VARCHAR(100) column in the catalog table. Likely the TiTiler/TiPG service URL which includes the full schema-qualified table name (e.g., `geo.sg_dag_vector_test_cutlines_ord1`).

### BUG: D7 — Vector unpublish does not revoke release

**Severity**: HIGH
**Sequence**: D7 (unpublish vector)
**Impact**: After `unpublish_vector` workflow completes, the geo table is physically dropped and TiPG is refreshed, but the release record still shows `approval_state=approved` and `is_served=true`. The catalog shows the data as available even though it's gone — a ghost entry.
**Root cause**: Raster and zarr unpublish paths update the release via STAC item deletion side-effect (in `unpublish_delete_stac` handler). Vector has no STAC item (uses OGC Features/TiPG), so the release update code path is never reached. The `unpublish_vector` workflow needs an explicit release-update node.
**Note**: The DAG run for unpublish workflows has `asset_id=null` and `release_id=null`, confirming the release linkage is missing from the unpublish submission path.

### Cosmetic: Submit response message

**Severity**: LOW
**Impact**: All DAG submissions return "CoreMachine job created" in the response message even when `workflow_engine=dag` was specified and the DAG engine was actually used. The status endpoint correctly shows `workflow_engine: "dag"`. Cosmetic only — no functional impact.

### Design Note: D18 — Overwrite during processing

When overwriting a release that is still in `processing` state, the system creates a new version ordinal rather than blocking or cancelling the in-flight run. This means:
- Original ordinal remains at `pending_review` as an orphan
- New ordinal processes independently and can be approved
- No cancellation of the original workflow

This is non-destructive behavior, not a bug. May want to document or address orphan cleanup in a future iteration.

---

## Run Comparison

| Metric | Run 3 (v0.10.9.7) | Run 4 (v0.10.9.8) | Run 5 (v0.10.9.13) |
|--------|-------------------|-------------------|---------------------|
| Pass rate | 42% (8/19) | 53% (10/19) | **84% (16/19)** |
| SIEGE-7 | OPEN | OPEN | **RESOLVED** |
| D3 (NetCDF) | FAIL | FAIL | **PASS** |
| D4 (Zarr) | FAIL | FAIL | **PASS** |
| SIEGE-15 | — | OPEN | **RESOLVED** |
| New bugs | — | 1 (SIEGE-15) | 2 (VARCHAR overflow, vector unpublish revoke) |

---

## Blocking Issues for v0.10.10 Gate

| # | Issue | Severity | Sequences Affected | Status |
|---|-------|----------|--------------------|--------|
| 1 | D7: Vector unpublish does not revoke release | HIGH | D7 | **FIXED** (02 APR 2026) |
| 2 | D2: register_catalog VARCHAR(100) overflow | MEDIUM | D2 post-gate | **FIXED** (02 APR 2026) |

### Fix: D2 — CRS WKT overflow (SIEGE-16)

**Root cause**: `str(gdf.crs)` returns full WKT2 representation (~800 chars for EPSG:4326). This flows from `handler_validate_and_clean.py:133` → workflow receives → `register_catalog` → `register_table_metadata()` → INSERT into `app.vector_etl_tracking.source_crs` VARCHAR(100).

**Fix**: Normalize to EPSG code via `crs.to_epsg()` (e.g., `"EPSG:4326"`). Falls back to truncated WKT for non-EPSG CRS (extreme edge case).

**Files changed**:
- `services/vector/handler_validate_and_clean.py:132-137` — EPSG normalization
- `services/vector/postgis_handler.py:615-620` — same pattern in monolith path

### Fix: D7 — Vector unpublish state machine (SIEGE-17)

**Root cause**: The `release_id` never reached the handler that revokes the release. Two breaks:
1. Inventory handler didn't look up the release_id from `app.release_tables`
2. Workflow YAML didn't wire it to downstream nodes

Additionally, the revocation happened in a separate handler (`cleanup`) with its own transaction, not atomic with the table DROP.

**Fix**:
1. Inventory handler looks up `release_id` via `ReleaseTableRepository.get_by_table_name()`
2. `drop_postgis_table` handler revokes the release in the **same transaction** as DROP TABLE + metadata cleanup — one `conn.commit()`, fully atomic
3. Workflow YAML wires `release_id` from inventory → drop_table (primary) and inventory → cleanup (safety net)

**Files changed**:
- `services/unpublish_handlers.py` — inventory lookup (line ~358) + drop_table revoke (line ~1024)
- `workflows/unpublish_vector.yaml` — receives wiring for release_id

---

## Remaining Items for v0.10.10

### Must verify (deploy + rerun D2/D7)

| Item | Description | Status |
|------|-------------|--------|
| D2 retest | Deploy SIEGE-16 fix, rerun D2 vector lifecycle | PENDING deploy |
| D7 retest | Deploy SIEGE-17 fix, rerun D7 unpublish vector | PENDING deploy |

### Non-blocking (cosmetic / deferred)

1. **D18 orphan ordinals**: Overwrite during processing creates orphaned releases. Consider janitor cleanup or documented behavior.
2. **Multiband preview**: D5 preview returns 500 without `bidx` parameter. TiTiler limitation, not platform bug.
3. **Submit message cosmetic**: All DAG submits say "CoreMachine job created". Low priority.
4. **STAC sentinel datetime**: `0001-01-01T00:00:00Z` used for non-temporal assets. Expected behavior (DF-STAC-6 deferred).
5. **D10 error_type naming**: Pre-flight blob-not-found returns `error_type: "WorkflowNotFound"` instead of a more descriptive type.

### Deferred from earlier (v0.10.9 COMPETE series)

| Item | Description | Status |
|------|-------------|--------|
| DF-STAC-5 | STAC builder mutation — `account_name` leaks via `xarray:open_kwargs` in cached stac_item_json | Open |
| DF-STAC-6 | Sentinel datetime `0001-01-01T00:00:00Z` for non-temporal assets | Open (cosmetic) |
| DF-TIPG-1 | TiPG refresh returns success even on total failure | Open |
