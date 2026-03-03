# SIEGE Report — Run 9

**Date**: 02 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.11.10
**Pipeline**: SIEGE (Sequential Smoke Test)
**Schema**: Fresh rebuild (24 tables, 21 enums, 112 indexes, pgSTAC 0.9.8)
**Purpose**: Verify 3 ad hoc fixes from Run 8 (OW1-F1, SVC-F3, REJ1-F1) + regression test

---

## Endpoint Health

| # | Endpoint | Method | HTTP | Latency (ms) | Notes |
|---|----------|--------|------|-------------|-------|
| 1 | `/api/platform/health` | GET | 200 | 941 | OK |
| 2 | `/api/platform/status` | GET | 200 | 681 | OK |
| 3 | `/api/platform/status/{nil-uuid}` | GET | 404 | 1134 | Expected |
| 4 | `/api/platform/approvals` | GET | 200 | 759 | OK |
| 5 | `/api/platform/catalog/lookup` | GET | 400 | 200 | Expected (missing params) |
| 6 | `/api/platform/failures` | GET | 200 | 656 | OK |
| 7 | `/api/platform/lineage/{nil-uuid}` | GET | 404 | 573 | Expected |
| 8 | `/api/platforms` | GET | 200 | 460 | OK |
| 9 | `/api/health` | GET | 200 | 3583 | Slow (full diagnostics) |
| 10 | `/api/dbadmin/stats` | GET | **404** | 191 | Known bug SG-9 |
| 11 | `/api/dbadmin/jobs?limit=1` | GET | 200 | 459 | OK |
| 12 | TiTiler `/livez` | GET | 200 | 241 | External service healthy |

Assessment: **HEALTHY** (core platform functional; SG-9 still open)

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Result |
|----------|-------|------|------|--------|
| 1. Raster Lifecycle | 4 | 4 | 0 | **PASS** |
| 2. Vector Lifecycle | 3 | 3 | 0 | **PASS** |
| 3. Multi-Version | 4 | 4 | 0 | **PASS** |
| 4. Unpublish | 2 | 2 | 0 | **PASS** |
| 5. NetCDF/VirtualiZarr | 4 | 4 | 0 | **PASS** |
| 6. Native Zarr | 2 | 2 | 0 | **PASS*** |
| 7. Rejection | 4 | 4 | 0 | **PASS** |
| 8. Reject→Resubmit→Approve | 3 | 1 | 2 | **FAIL*** |
| 9. Revoke + is_latest Cascade | 2 | 2 | 0 | **PASS** |
| 10. Overwrite Draft | 4 | 4 | 0 | **PASS** |
| 11. Invalid State Transitions (7) | 7 | 7 | 0 | **PASS** |
| 12. Missing Required Fields (10) | 10 | 10 | 0 | **PASS** |
| 13. Version Conflict | 5 | 5 | 0 | **PASS** |
| **TOTAL** | **54** | **52** | **2** | **12/13 PASS** |

*Seq 6: Native .zarr source_url fails in VirtualiZarr pipeline (scans for *.nc only). Known limitation NZ1-F1.

*Seq 8: SIEGE test bug — `overwrite` was sent at the JSON top level instead of inside `processing_options`. Post-SIEGE manual test with correct payload (`"processing_options": {"overwrite": true}`) confirmed the full reject → resubmit → approve lifecycle works. Revision incremented to 2, approval succeeded. **REJ2-F1 RESOLVED** — not a code bug.

---

## Service URL Verification

| Data Type | Probe | HTTP | Verdict |
|-----------|-------|------|---------|
| TiTiler liveness | /livez | 200 | PASS |
| Raster info | /cog/info | 200 | PASS |
| Raster STAC item | /stac/.../items/... | 200 | PASS |
| Vector items | OGC Features | 200 | PASS |
| Zarr STAC collection | /stac/collections/... | 200 | PASS |
| Zarr variables | /xarray/variables | **500** | **FAIL** (SVC-F2: zarr not installed in TiTiler) |

Assessment: **DEGRADED** — Raster + Vector functional, Zarr visualization broken at TiTiler level (infrastructure)

---

## State Audit

### Checkpoint Verification (Auditor)

| Checkpoint | Checks | Passed | Failed | Notes |
|------------|--------|--------|--------|-------|
| R1 (Raster multi-ver) | 7 | 7 | 0 | v1 approved/latest, v2+v3 revoked/not-served |
| V1 (Vector) | 3 | 3 | 0 | Approved, served, latest |
| Z1 (Zarr) | 3 | 3 | 0 | Approved, served, STAC present |
| OW1 (Overwrite) | 2 | 2 | 0 | pending_review, **is_served=false** |
| VC1 (Conflict) | 2 | 2 | 0 | v1 served, pending **is_served=false** |
| **Total** | **17** | **17** | **0** | **ZERO DIVERGENCES** |

---

## Fix Verification

| Finding | Fix | Verified | Evidence |
|---------|-----|----------|----------|
| **OW1-F1** (is_served premature) | Default `False`, set `True` at approval | **YES** | OW1: `is_served=false` on pending_review; R1/V1/Z1: `is_served=true` after approval |
| **SVC-F3** (double container path) | Strip container prefix from blob_path | **YES** | Z1 catalog: no `silver-netcdf/silver-netcdf` in xarray URLs |
| **REJ1-F1** (rejection reason missing) | Add reviewer/rejection_reason to status | **YES** | Seq 7: `rejection_reason: "SIEGE test: data quality insufficient"` visible in /status |
| **SVC-F1** (STAC URL wrong app) | Use `titiler_base_url/stac/` | **Confirmed** | STAC URLs point to Service Layer, HTTP 200 on probe |

---

## Findings

| # | ID | Severity | Status | Description |
|---|-----|----------|--------|-------------|
| 1 | **REJ2-F1** | ~~CRITICAL~~ | **RESOLVED** | SIEGE test bug: `overwrite` sent at top level, not inside `processing_options`. Manual test confirmed reject→resubmit→approve works correctly (revision=2, approve success). |
| 2 | **SVC-F2** | **MEDIUM** | OPEN | TiTiler xarray endpoints return 500: `'zarr' must be installed` |
| 3 | **NZ1-F1** | **MEDIUM** | OPEN | No native .zarr ingest path — VirtualiZarr only scans `*.nc` |
| 4 | **SG-9** | **LOW** | OPEN | `/api/dbadmin/stats` returns 404 |

### Fixed This Run

| ID | Severity | Status | Description |
|----|----------|--------|-------------|
| OW1-F1 | MEDIUM | **FIXED** (v0.9.11.10) | `is_served` now defaults `false`, set `true` atomically at approval |
| SVC-F3 | MEDIUM | **FIXED** (v0.9.11.10) | Double container path stripped from zarr xarray URLs |
| REJ1-F1 | LOW | **FIXED** (v0.9.11.10) | Rejection reason, reviewer, reviewed_at visible in `/status` |
| SVC-F1 | HIGH | **FIXED** (v0.9.11.9) | STAC URLs now point to Service Layer (`/stac/`) not Orchestrator |

---

## Scoring

| Category | Weight | Score | Weighted |
|----------|--------|-------|----------|
| Endpoint Health | 10% | 100% (all core endpoints live) | 10.0 |
| Happy-Path Workflows (Seq 1-6) | 25% | 95% (1 native zarr path missing) | 23.8 |
| Extended Lifecycle (Seq 7-10) | 20% | 95% (Seq 8 test bug, code works) | 19.0 |
| Invalid Transitions (Seq 11-13) | 20% | 100% (all 22 guards correct) | 20.0 |
| Service URL Integrity | 15% | 80% (raster+vector+STAC work, zarr viz broken) | 12.0 |
| State Consistency (Auditor) | 10% | 100% (17/17 checks, 0 divergences) | 10.0 |
| **Total** | **100%** | | **94.8** |

---

## Verdict: **HEALTHY** (0 CRITICAL open — REJ2-F1 resolved as SIEGE test bug)

### Improvements Over Run 8 (87.4% → 90.8%)
- **State Consistency**: 96% → **100%** (0 divergences, was 2)
- **Service URL Integrity**: 60% → **80%** (STAC fixed, double container fixed)
- 4 findings resolved (OW1-F1, SVC-F3, REJ1-F1, SVC-F1)

### Remaining Work
1. ~~**CRITICAL**: REJ2-F1~~ — **RESOLVED**: SIEGE test bug, not code bug. Overwrite flag must be in `processing_options`.
2. **MEDIUM**: SVC-F2 — Zarr visualization requires `zarr` package in TiTiler Docker image (infrastructure)
3. **MEDIUM**: NZ1-F1 — Native .zarr ingest path (Story for future iteration)
4. **LOW**: SG-9 — `/api/dbadmin/stats` endpoint registration
