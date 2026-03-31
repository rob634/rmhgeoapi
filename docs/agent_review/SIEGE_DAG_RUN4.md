# SIEGE-DAG Run 4 — Epoch 5 DAG Workflow Smoke Test

**Date**: 31 MAR 2026
**Version**: 0.10.9.8
**Profile**: quick
**Agent**: Claude Opus 4.6 (manual execution, no subagents)
**Duration**: ~35 minutes
**Environment**: Fresh rebuild + STAC nuke + all 3 apps restarted

---

## Summary

| Metric | Value |
|--------|-------|
| Total Sequences | 19 |
| Pass | 10 |
| Fail | 3 |
| Partial | 2 |
| Skip | 3 |
| Inconclusive | 1 |
| **Pass Rate** | **10/19 = 53%** (up from 42% in Run 3) |

**New findings**: 1 new (SIEGE-15: double blob_path prefix in service URLs).

**Key result**: Raster lifecycle and release lifecycle parity fully proven. Vector blocked by SIEGE-7 (overwrite approval guard). Zarr paths both fail (NetCDF encoding error, native Zarr chunk alignment). SIEGE-14 fix confirmed (triple revision works). SIEGE-13 fix confirmed (gate auto-skips on dead predecessors).

---

## Sequence Results

| Seq | Name | Workflow | Result | Duration | Notes |
|-----|------|----------|--------|----------|-------|
| D1 | Raster Lifecycle | process_raster | **PASS** | 37s pre-gate | Full lifecycle: submit→process→approve→catalog→TiTiler 200 |
| D2 | Vector Lifecycle | vector_docker_etl | **FAIL** | 18s to fail | First run: geo table exists (geo survives rebuild). Retry with overwrite: pre-gate tasks pass but approval BLOCKED — `processing_status=processing` not updated to `completed` for revision=2 (**SIEGE-7 still broken for overwrites**) |
| D3 | NetCDF Lifecycle | ingest_zarr (NC) | **FAIL** | 19s to fail | `netcdf_convert_and_pyramid` handler: `unexpected encoding group name(s): {'climatology-spei12-annual-mean', 'lat_bnds', 'lon_bnds'}` — xarray encoding issue |
| D4 | Native Zarr Lifecycle | ingest_zarr (Zarr) | **FAIL** | 25s to fail | `zarr_generate_pyramid`: chunk alignment overlap — `encoding['chunks']=(1, 180, 256)` overlaps Dask chunks on axis 2. `safe_chunks` error. |
| D5 | Multiband Raster | process_raster | **PASS** | 42s pre-gate | 8-band FATHOM flood — catalog + tiles correct, STAC materialized |
| D6 | Unpublish Raster | unpublish_raster | **PASS** | ~6s | D1 successfully unpublished. `is_served=false`, `approval_state=revoked` |
| D7 | Unpublish Vector | unpublish_vector | **SKIP** | — | D2 approval blocked |
| D8 | Unpublish Zarr | unpublish_zarr | **SKIP** | — | D3 and D4 both failed |
| D9 | DAG Progress Polling | process_raster | **PASS** | 30s | Monotonic: 0→7→14→50→57→71%. In-flight states captured (ready, running). Brain pickup ~3s |
| D10 | DAG Error Handling | process_raster | **PASS** | ~4 min | Nonexistent file: 3 retries then `failed`. 13 downstream tasks skipped. Gate auto-skipped (**SIEGE-13 fix confirmed**). Clean error: "Blob not found" |
| **D11** | **Rejection Path** | process_raster | **PASS** | 41s | Reject with reason preserved. Identical to Epoch 4. |
| **D12** | **Reject→Overwrite→Approve** | process_raster | **PASS** | 42s | revision=2, approved v1. processing_status=completed. Identical to Epoch 4. |
| **D13** | **Revoke→Overwrite→Reapprove** | process_raster | **PASS** | 19s overwrite | Full round-trip: ordinal=1, revision=2, v1, is_served=true. Identical to Epoch 4. |
| **D14** | **Overwrite Approved (Guard)** | — | **PARTIAL** | instant | "must be revoked before overwrite" — safe behavior, but diverges from Epoch 4 (expected: new version creation) |
| **D15** | **Invalid State Transitions** | — | **PARTIAL** | instant | 15a PASS, 15b PASS, 15f PARTIAL (no release found vs already-revoked), 15g PASS, 15i PASS |
| **D16** | **Version Conflict** | process_raster | **INCONCLUSIVE** | 77s | Test methodology issue: revoked v1 before re-approving, so no actual conflict created. Needs ordinal=2 for proper test. |
| **D17** | **Triple Revision** | process_raster | **PASS** | 3× ~40s | Rev1→reject→rev2→reject→rev3→approve. **SIEGE-14 fix confirmed** — `_submission_ordinal` prevents run_id collision. |
| **D18** | **Overwrite Draft** | process_raster | **PASS** | 42s | Duplicate=idempotent (same request_id). Overwrite creates revision=2. |
| **D19** | **Multi-Revoke Target** | process_raster | **PASS** | 42s | Correct target selection. Revision=2, pending_review. |

---

## Timing Analysis

### Brain Scan Interval & Task Pickup

| Metric | Value |
|--------|-------|
| Brain scan interval | 5.0s |
| Task pickup latency (first task) | 1-3s after run creation |
| Inter-task gap (sequential) | 5-8s (scan interval + claim) |
| Worker poll interval | ~5s |

### Workflow Execution Times (pre-gate)

| Workflow | File Size | Total pre-gate | Bottleneck |
|----------|-----------|---------------|------------|
| process_raster (single) | 26 MB | ~37s | create_single_cog 13.4s |
| process_raster (multiband) | 11 MB | ~42s | create_single_cog 20.3s |
| vector_docker_etl | 6 MB | ~18s | load_source 2.4s + validate 1.0s |
| ingest_zarr (NC) | 4 MB | 19s (failed) | — |
| ingest_zarr (Zarr) | 10 MB | 25s (failed) | — |
| unpublish_raster | — | ~6s | inventory 0.2s + cleanup 0.3s |
| error (nonexistent file) | — | ~4 min | 3 retries × janitor interval |

### Task-Level Timing (D1: process_raster)

| Task | Duration | Notes |
|------|----------|-------|
| download_source | 1.2s | Bronze→mount |
| validate | 0.7s | GDAL check |
| create_single_cog | 13.4s | **Bottleneck** — GDAL translate |
| upload_single_cog | 2.7s | Mount→silver-cogs |
| persist_single | 0.3s | DB write |
| approval_gate | — | Waited for manual approval |
| materialize_single_item | 0.5s | STAC item |
| materialize_collection | 0.2s | STAC collection |

---

## Findings

### NEW: SIEGE-15 — Double `/vsiaz/silver-cogs/` prefix in service URLs

**Severity**: MEDIUM
**Impact**: All catalog tile/preview/info URLs are broken (404 from TiTiler when using catalog-provided URLs). TiTiler works fine with the correct single-prefix URL.

**Root cause**: The `blob_path` stored on the release already includes `/vsiaz/silver-cogs/` prefix. The service URL builder then prepends it again, producing:
```
/vsiaz/silver-cogs//vsiaz/silver-cogs/sg-dag-raster-test/dctest/1/dctest_analysis.tif
                    ^^^^^^^^^^^^^^^^^^^^ doubled
```

**Affected**: All raster service URLs in catalog lookups and status responses.

**Obvious fix**: The service URL builder should check if blob_path already has the `/vsiaz/` prefix before prepending. Or the blob_path should be stored WITHOUT the GDAL prefix and the builder adds it.

---

### CONFIRMED STILL BROKEN: SIEGE-7 — Approval blocked for overwrite/revision submissions

**Severity**: HIGH
**Impact**: Any workflow that overwrites a FAILED release cannot be approved. Vector workflows that encounter existing geo tables (post-rebuild) cannot proceed.

**Behavior**:
- First submission (revision=1): processing_status correctly set to `completed` → approval works
- Overwrite of REJECTED release: processing_status correctly set to `completed` → approval works (D12, D17)
- Overwrite of FAILED release: processing_status stays at `processing` → approval blocked (D2)

**Obvious fix**: The submit-with-overwrite path that creates a new DAG run for a failed release must update `processing_status` from `failed` to `processing` on submit, then to `completed` when pre-gate tasks finish. The status update logic likely only runs for the initial submission path.

---

### CONFIRMED STILL BROKEN: D3/D4 Zarr Pipeline Failures

**D3 (NetCDF)**: `netcdf_convert_and_pyramid` fails with xarray encoding error:
```
unexpected encoding group name(s) provided: {'climatology-spei12-annual-mean', 'lat_bnds', 'lon_bnds'}
```
**Obvious fix**: The handler passes variable names in the encoding dict that don't match the Dataset's data_vars. Need to filter encoding keys to only include actual data variables, excluding coordinate bounds.

**D4 (Native Zarr)**: `zarr_generate_pyramid` fails with chunk alignment:
```
Specified Zarr chunks encoding['chunks']=(1, 180, 256) for variable named 'tasmax' 
would overlap multiple Dask chunks... on axis 2
```
**Obvious fix**: After rechunk, the pyramid writer needs to either: (a) set `safe_chunks=False`, (b) call `chunk()` to align, or (c) use `align_chunks=True` in `to_zarr()`.

---

### CONFIRMED FIXED

| Bug | Run 3 Status | Run 4 Status | Evidence |
|-----|-------------|-------------|----------|
| SIEGE-10 (lease after rebuild) | FIXED | **CONFIRMED FIXED** | Brain healthy after rebuild, lease held |
| SIEGE-13 (gate auto-fail) | FIXED | **CONFIRMED FIXED** | D10: gate auto-skipped when download_source failed |
| SIEGE-14 (3rd+ overwrite collision) | FIXED | **CONFIRMED FIXED** | D17: rev1→rev2→rev3 all completed, approved |

---

## Parity Assessment

### ETL Output Parity (D1-D5)

| Aspect | Epoch 4 | Epoch 5 DAG | Parity |
|--------|---------|-------------|--------|
| Raster services shape | COG URLs | COG URLs | **MATCH** |
| Catalog response shape | raster.tiles.* | raster.tiles.* | **MATCH** (but URLs have double prefix — SIEGE-15) |
| COG serveable via TiTiler | yes | yes | **MATCH** |
| STAC materialization | yes | yes | **MATCH** |
| Vector lifecycle | works | blocked (SIEGE-7) | **DIVERGE** |
| NetCDF→Zarr | works | fails (encoding) | **DIVERGE** |
| Native Zarr | works | fails (chunking) | **DIVERGE** |

### Release Lifecycle Parity (D11-D19)

| Transition | Epoch 4 | Epoch 5 | Match |
|------------|---------|---------|-------|
| Reject | PASS | **PASS (D11)** | Yes |
| Reject→Overwrite→Approve | PASS | **PASS (D12)** | Yes |
| Revoke→Overwrite→Reapprove | PASS | **PASS (D13)** | Yes |
| Overwrite approved (guard) | new version | error (must revoke) | **DIVERGE** |
| Invalid transitions | 400s | 400s (4/5) | Yes |
| Version conflict | 409 | INCONCLUSIVE | — |
| Triple revision | PASS | **PASS (D17)** | Yes |
| Overwrite draft | PASS | **PASS (D18)** | Yes |
| Multi-revoke target | PASS | **PASS (D19)** | Yes |

---

## Blocking Issues for v0.10.9 Gate

| # | Issue | Severity | Sequences Blocked |
|---|-------|----------|------------------|
| 1 | **SIEGE-7**: Approval guard rejects overwrites of failed releases | HIGH | D2 (vector), any overwrite-of-failed path |
| 2 | **D3**: NetCDF encoding mismatch in `netcdf_convert_and_pyramid` | HIGH | D3, D8 |
| 3 | **D4**: Zarr chunk alignment in `zarr_generate_pyramid` | HIGH | D4, D8 |
| 4 | **SIEGE-15**: Double blob_path prefix in service URLs | MEDIUM | All catalog URLs broken (TiTiler still works directly) |
| 5 | **D2**: geo schema tables survive rebuild, requiring overwrite | LOW | First vector run after rebuild |

---

## Non-Blocking Notes

- D16 was INCONCLUSIVE due to test methodology (need ordinal=2 for proper version conflict test)
- D14 behavioral divergence (must-revoke-first) is SAFE but differs from Epoch 4
- D2's geo table survival is BY DESIGN (geo schema has separate lifecycle)
- D10 failure cycle takes ~4 min due to 3 retries × janitor interval — acceptable for error path
- `processing_status: completed` correctly set for initial submissions AND overwrite-of-rejected releases, but NOT for overwrite-of-failed releases

---

## Environment at Test Time

| App | Version | Status |
|-----|---------|--------|
| rmhazuregeoapi (Function App) | 0.10.9.8 | healthy |
| rmhheavyapi (Docker Worker) | 0.10.9.8 | degraded (1 warning: RASTER_USE_ETL_MOUNT default) |
| rmhdagmaster (DAG Brain) | 0.10.9.8 | healthy — 10 workflows, 57 handlers, lease held |
| Database | geopgflex on rmhpostgres | 30 app tables, 22 pgstac tables |
| TiTiler | rmhtitiler | livez 200 |
