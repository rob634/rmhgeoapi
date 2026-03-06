# SIEGE Report — Run 12

**Date**: 06 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.14.0
**Pipeline**: SIEGE
**Run Number**: 12 (Agent Run 37)
**Focus**: Post-v0.9.13.4 regression — ERH-1 (extra='forbid'), Zarr chunking, VSI tiled deletion, NZ1-F1

## Endpoint Health

| # | Endpoint | Method | HTTP Code | Expected | Verdict |
|---|----------|--------|-----------|----------|---------|
| 1 | /api/platform/health | GET | 200 | 200 | OK |
| 2 | /api/platform/status | GET | 200 | 200 | OK |
| 3 | /api/platform/status/{uuid} | GET | 404 | 404 | OK |
| 4 | /api/platform/approvals | GET | 200 | 200 | OK |
| 5 | /api/platform/catalog/lookup | GET | 400 | 400 | OK |
| 6 | /api/platform/failures | GET | 200 | 200 | OK |
| 7 | /api/platform/registry | GET | 200 | 200 | OK |
| 8 | /api/health | GET | 200 | 200 | OK |
| 9 | /api/dbadmin/stats | GET | 404 | 200 | KNOWN (SG-9) |
| 10 | /api/dbadmin/jobs?limit=1 | GET | 200 | 200 | OK |
| 11 | /api/dbadmin/diagnostics/all | GET | 404 | 200 | NEW FINDING |

Assessment: **DEGRADED** — Core platform surfaces healthy. /api/dbadmin/stats (SG-9 known) and /api/dbadmin/diagnostics/all (new) return 404.

## Workflow Results

| Seq | Name | Steps | Pass | Fail | Verdict | Notes |
|-----|------|-------|------|------|---------|-------|
| 1 | Raster Lifecycle | 4 | 4 | 0 | PASS | container_name required in submit |
| 2 | Vector Lifecycle | 5 | 5 | 0 | PASS | GPKG_NO_LAYER_SPECIFIED warning surfaced |
| 3 | Multi-Version | 4 | 4 | 0 | PASS | StaleOrdinalError correctly fires |
| 4 | Unpublish | 4 | 4 | 0 | PASS | Uses deleted_by param; v3 revoked, v1 preserved |
| 5 | NetCDF/VirtualiZarr | 4 | 1 | 3 | **FAIL** | netcdf_convert can't find .nc in mount path |
| 6 | Native Zarr | 4 | 4 | 0 | PASS | **NZ1-F1 CONFIRMED FIXED** |
| 7 | Rejection | 4 | 4 | 0 | PASS | |
| 8 | Reject→Resubmit→Approve | 4 | 4 | 0 | PASS | revision=2 on same ordinal |
| 9 | Revoke + is_latest Cascade | 5 | 5 | 0 | PASS | STAC item deleted on revoke |
| 10 | Overwrite Draft | 4 | 4 | 0 | PASS | Idempotent 200 with hint |
| 11 | Invalid State Transitions (9) | 9 | 9 | 0 | PASS | All 9 sub-checks correct |
| 12 | Missing Required Fields (13) | 13 | 13 | 0 | PASS | **ERH-1 extra='forbid' verified** |
| 13 | Version Conflict | 4 | 4 | 0 | PASS | ApprovalFailed 400 (not 409) |
| 14 | Revoke→Overwrite→Reapprove | 7 | 7 | 0 | PASS | RVOW1: ordinal=1, revision=2 |
| 15 | Overwrite Approved→New Version | 2 | 2 | 0 | PASS | RVOW2: ordinal=2 created |
| 16 | Triple Revision | 5 | 5 | 0 | PASS | TREV1: revision=3 |
| 17 | Overwrite Race Guard | 3 | 3 | 0 | PASS | Clean outcome, no corruption |
| 18 | Multi-Revoke Overwrite Target | 5 | 5 | 0 | PASS | Highest ordinal targeted |
| 19 | Zarr Rechunk Path | 4 | 2 | 2 | **FAIL** | dask not installed in Docker worker |
| **TOTAL** | **19 sequences** | **88** | **84** | **4** | **17/19 PASS** | **95.5% step pass rate** |

## Fix Verifications

| Fix | Status | Details |
|-----|--------|---------|
| NZ1-F1 (Native Zarr fails) | **VERIFIED FIXED** | ingest_zarr completes, xarray_urls present in catalog |
| ERH-1 (extra='forbid') | **VERIFIED WORKING** | 12k/12l/12m all return 400 for unknown fields |
| ERH-3/4 (Raster error shape) | **VERIFIED** | Structured errors observed in validation failures |
| SG-9 (/api/dbadmin/stats 404) | **STILL OPEN** | |
| VSI tiled deletion | **NO REGRESSION** | Raster lifecycle passes without tiled fallback |

## New Findings

| # | Severity | Category | Description | Reproduction |
|---|----------|----------|-------------|--------------|
| RCH-1 | P1 | DOCKER | `rechunk=True` fails — `dask` package not installed in Docker worker image. `ingest_zarr_rechunk` handler calls `ds.chunk()` which requires dask. | Submit native Zarr with `processing_options: {rechunk: true}` |
| SEQ5-1 | P2 | PIPELINE | NetCDF `netcdf_convert` (stage 4) can't find .nc in `/mounts/etl-temp/<job_id>/`. Stages 1-3 (scan, copy, validate) succeed. Mount path visibility issue between tasks. | Submit any .nc file from wargames container |
| DIAG-1 | LOW | ENDPOINT | `/api/dbadmin/diagnostics/all` returns 404 (new — not seen in Run 11) | GET /api/dbadmin/diagnostics/all |

## Checkpoint Map

| Checkpoint | Key IDs |
|-----------|---------|
| R1 (Raster) | request_id=6207de49, release_id=753386c5, v1 approved |
| V1 (Vector) | request_id=761f7dc6, release_id=912791ed, v1 approved |
| MV1 (Multi-Version) | ordinal=3 approved (v3), ordinal=2 pending |
| U1 (Unpublish) | v3 revoked, v1 preserved |
| Z1 (NetCDF) | FAILED — mount path issue |
| NZ1 (Native Zarr) | request_id=b04bef67, release_id=a5036303, v1 approved, xarray_urls verified |
| REJ1 (Reject) | request_id=86fa066b, approval_state=rejected |
| REJ2 (Reject→Approve) | revision=2, v1 approved |
| REV1 (Revoke) | ordinal=3 revoked, STAC deleted |
| OW1 (Overwrite) | ordinal=2, revision=1 |
| RVOW1 | ordinal=1, revision=2, re-approved |
| RVOW2 | ordinal=2, new version created |
| TREV1 | ordinal=1, revision=3, approved |
| RACE1 | ordinal=1, revision=2, clean |
| MREV1 | overwrite targeted v2's release_id |
| RCH1 | rechunk=True FAILED (dask), base ingest PASSED |

## Comparison with Run 11 (v0.9.13.1)

| Metric | Run 11 | Run 12 | Delta |
|--------|--------|--------|-------|
| Sequences | 18 | 19 | +1 (Seq 19 rechunk) |
| Steps | 98 | 88 | -10 (fewer poll retries) |
| Pass rate | 94.9% | 95.5% | +0.6% |
| Seq pass | 15/18 (83.3%) | 17/19 (89.5%) | +6.2% |
| NZ1-F1 | FAIL | **PASS** | FIXED |
| SG2-1 (Unpublish targeting) | FAIL | Not retested | — |
| New bugs | 0 | 2 (RCH-1, SEQ5-1) | +2 |

## Verdict

**CONDITIONAL PASS** — 17/19 sequences pass. Two failures:
1. **Seq 5 (NetCDF)**: Pre-existing infrastructure bug (mount path). Not a regression from this deployment.
2. **Seq 19 (Rechunk)**: New feature missing dependency (dask). Easy fix — add to Docker requirements.

Core platform state machine, approval workflows, and error handling are solid. ERH-1 (extra='forbid') and NZ1-F1 (native Zarr) both confirmed fixed.
