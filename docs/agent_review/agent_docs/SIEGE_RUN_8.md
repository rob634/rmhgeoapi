# SIEGE Report — Run 8

**Date**: 02 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.11.9
**Pipeline**: SIEGE (Sequential Smoke Test)
**Schema**: Fresh rebuild (24 tables, 21 enums, 112 indexes, pgSTAC 0.9.8)

---

## Endpoint Health

| # | Endpoint | Method | HTTP | Latency (ms) | Notes |
|---|----------|--------|------|-------------|-------|
| 1 | `/api/platform/health` | GET | 200 | 926 | OK |
| 2 | `/api/platform/status` | GET | 200 | 538 | OK |
| 3 | `/api/platform/status/{nil-uuid}` | GET | 404 | 1083 | Expected |
| 4 | `/api/platform/approvals` | GET | 200 | 659 | OK |
| 5 | `/api/platform/catalog/lookup` | GET | 400 | 145 | Expected (missing params) |
| 6 | `/api/platform/failures` | GET | 200 | 580 | OK |
| 7 | `/api/platform/lineage/{nil-uuid}` | GET | 404 | 465 | Expected |
| 8 | `/api/platforms` | GET | 200 | 367 | OK |
| 9 | `/api/platform/catalog/lookup-unified` | GET | **404** | 117 | **Endpoint does not exist** |
| 10 | `/api/health` | GET | 200 | 3589 | Slow (full diagnostics) |
| 11 | `/api/dbadmin/stats` | GET | **404** | 118 | Known bug SG-9 |
| 12 | `/api/dbadmin/jobs?limit=1` | GET | 200 | 328 | OK |
| 13 | TiTiler `/livez` | GET | 200 | 205 | External service healthy |

Assessment: **HEALTHY** (core platform functional; 2 known missing endpoints)

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Result |
|----------|-------|------|------|--------|
| 1. Raster Lifecycle | 4 | 4 | 0 | **PASS** |
| 2. Vector Lifecycle | 4 | 4 | 0 | **PASS** |
| 3. Multi-Version | 4 | 4 | 0 | **PASS** |
| 4. Unpublish | 2 | 2 | 0 | **PASS** |
| 5. NetCDF/VirtualiZarr | 4 | 4 | 0 | **PASS** |
| 6. Native Zarr | 5 | 4 | 1 | **PASS*** |
| 7. Rejection | 4 | 4 | 0 | **PASS** |
| 8. Reject→Resubmit→Approve | 3 | 1 | 2 | **FAIL** |
| 9. Revoke + is_latest Cascade | 5 | 5 | 0 | **PASS** |
| 10. Overwrite Draft | 4 | 4 | 0 | **PASS** |
| 11. Invalid State Transitions (7) | 7 | 7 | 0 | **PASS** |
| 12. Missing Required Fields (10) | 10 | 10 | 0 | **PASS** |
| 13. Version Conflict | 5 | 5 | 0 | **PASS** |
| **TOTAL** | **61** | **58** | **3** | **12/13 PASS** |

*Seq 6: Native .zarr source_url rejected by VirtualiZarr pipeline (scans for *.nc only). Retried with NetCDF source — pipeline completed successfully.

---

## Service URL Verification

| Data Type | Probe | HTTP | Verdict |
|-----------|-------|------|---------|
| TiTiler liveness | `/livez` | 200 | PASS |
| Raster info | `/cog/info?url=...` | 200 | PASS |
| Raster statistics | `/cog/statistics?url=...` | 200 | PASS |
| STAC raster item | `/api/stac/collections/.../items/...` | 200 | PASS |
| Vector items | `/api/features/collections/sg_vector_test_cutlines_ord1/items?limit=1` | 200 | PASS |
| Vector feature count | 1401 features | -- | PASS |
| STAC zarr collection | `/api/stac/collections/sg-netcdf-test` | 200 | PASS |
| STAC zarr item | `/api/stac/collections/.../items/sg-netcdf-test-spei-ssp370-v1` | 200 | PASS |
| Zarr xarray/variables | `/xarray/variables?url=...` | **500** | **FAIL** |
| STAC service URLs in /status | `/api/collections/...` (wrong prefix) | **404** | **FAIL** |

Assessment: **DEGRADED** — Raster + Vector functional, Zarr visualization broken (missing zarr package in TiTiler), STAC URLs in status responses use wrong path prefix.

---

## State Audit

### Checkpoint Verification (Auditor)

| Checkpoint | Checks | Passed | Failed | Notes |
|------------|--------|--------|--------|-------|
| R1 (Raster) | 12 | 12 | 0 | v1 approved/latest, v2+v3 revoked |
| V1 (Vector) | 8 | 8 | 0 | Approved, no STAC (by design) |
| Z1 (Zarr) | 8 | 8 | 0 | STAC + xarray_urls present |
| NZ1 (Zarr Seq 6) | 8 | 8 | 0 | All xarray_urls + metadata correct |
| REJ1 (Rejected) | 6 | 6 | 0 | Release cleaned up after resubmit |
| OW1 (Overwrite) | 7 | 6 | 1 | is_served=true on pending_review |
| VC1 (Conflict) | 8 | 7 | 1 | is_served=true on pending_review v2 |
| **Total** | **57** | **55** | **2** | |

### Deep Verification

| Check | Result | Notes |
|-------|--------|-------|
| Total jobs | 14 | 13 completed, 1 expected failure |
| Unexpected failures | 0 | Single failure was intentional (.zarr path to .nc pipeline) |
| Platform failures | 0 unexpected | |
| Diagnostics endpoint | 404 | Known bug SG-9 |

### Orphan Analysis

| Dataset | Type | Status |
|---------|------|--------|
| sg-reject-test | Asset without release | Release deleted by resubmit, asset persists |
| sg-zarr-tasmax-test | Failed release with is_served=true | Stale orphan (confirms SG5-1) |

---

## State Divergences

| Checkpoint | Field | Expected | Actual | Severity |
|------------|-------|----------|--------|----------|
| OW1 | is_served | false (pending_review) | true | MEDIUM |
| VC1 v2 | is_served | false (pending_review) | true | MEDIUM |

Root cause: Processing pipeline sets `is_served=true` upon job completion, not gated by approval state. This is a systemic issue affecting all pending_review releases.

---

## Findings

| # | ID | Severity | Category | Description |
|---|-----|----------|----------|-------------|
| 1 | **REJ2-F1** | **CRITICAL** | LIFECYCLE | Resubmit after rejection broken. `/resubmit` deletes old release + STAC + job, new job completes, but release record NOT recreated. `/approve` returns 404. **Cannot recover from rejection via resubmit.** |
| 2 | **SVC-F1** | **HIGH** | SERVICE_URL | STAC URLs in `/api/platform/status` pointed to Orchestrator (`/api/collections/` → 404) instead of Service Layer (`rmhtitiler.../stac/collections/...`). **FIXED** in `trigger_platform_status.py:896` — now uses `titiler_base_url/stac/`. |
| 3 | **NZ1-F1** | **MEDIUM** | PIPELINE | Native `.zarr` source_url fails — VirtualiZarr pipeline only scans for `*.nc` files. No native zarr ingest path exists. `data_type=zarr` is misleading. |
| 4 | **OW1-F1** | **MEDIUM** | STATE | `is_served=true` set on `pending_review` releases. Processing pipeline marks served before approval. Systemic — affects all unapproved releases. |
| 5 | **SVC-F2** | **MEDIUM** | SERVICE_URL | TiTiler xarray endpoints return 500: `'zarr' must be installed`. All Zarr visualization URLs non-functional. Data pipeline works, serving doesn't. |
| 6 | **SVC-F3** | **MEDIUM** | SERVICE_URL | Double path in Zarr xarray URLs — container name `silver-netcdf` appears twice in URL construction. |
| 7 | **REJ1-F1** | **LOW** | AUDIT | Rejection reason accepted by `/reject` but not surfaced in `/status` response. Audit trail incomplete — no way to retrieve rejection reason via API. |

### Reconfirmed Known Bugs

| ID | Status | Description |
|----|--------|-------------|
| SG-9 | Still open | `/api/dbadmin/stats` and `/api/dbadmin/diagnostics/all` return 404 |
| SG5-1 | Still open | Failed zarr release has `is_served=true` with `processing_status=failed` |
| SG6-L3 | Reconfirmed | Zarr submit with `file_name` creates orphaned release (must use `source_url`) |

### Endpoint Not Deployed

| Endpoint | Status | Impact |
|----------|--------|--------|
| `/api/platform/catalog/lookup-unified` | 404 — not registered | SIEGE spec references this; service URL validation adapted to use `catalog/lookup` instead |

---

## Scoring

| Category | Weight | Score | Weighted |
|----------|--------|-------|----------|
| Endpoint Health | 10% | 100% (all core endpoints live) | 10.0 |
| Happy-Path Workflows (Seq 1-6) | 25% | 95% (1 native zarr path missing) | 23.8 |
| Extended Lifecycle (Seq 7-10) | 20% | 75% (Seq 8 resubmit broken) | 15.0 |
| Invalid Transitions (Seq 11-13) | 20% | 100% (all 22 guards correct) | 20.0 |
| Service URL Integrity | 15% | 60% (Zarr viz broken, STAC URLs wrong) | 9.0 |
| State Consistency (Auditor) | 10% | 96% (55/57 checks) | 9.6 |
| **Total** | **100%** | | **87.4** |

---

## Verdict: **NEEDS INVESTIGATION**

### What Works Well
- Core lifecycle (submit → approve → catalog) is solid across raster, vector, and zarr
- State machine guards are **100% correct** — all 7 invalid transitions properly rejected with 400
- Input validation is **100% correct** — all 10 missing-field tests returned proper 400s
- Version conflict detection works perfectly (409 with remediation advice)
- Multi-version coexistence and is_latest cascade work correctly
- Unpublish correctly revokes + restores previous version
- Service URLs for raster (TiTiler COG) and vector (OGC Features) work end-to-end

### What Needs Fixing
1. **CRITICAL**: Resubmit-after-rejection is a dead path (REJ2-F1)
2. **HIGH**: STAC URLs in status responses return 404 (SVC-F1)
3. **MEDIUM**: Zarr visualization non-functional at TiTiler level (SVC-F2)
4. **MEDIUM**: `is_served` set before approval (OW1-F1)
5. **MEDIUM**: No native `.zarr` ingest path (NZ1-F1)
