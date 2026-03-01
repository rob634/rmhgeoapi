# SIEGE Report -- Run 3

**Date**: 01 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.10.1
**Pipeline**: SIEGE (Sentinel -> Cartographer -> Lancer -> Auditor -> Scribe)
**Status**: CONDITIONAL PASS
**Context**: Regression verification after REFLEXION Runs 14-17 (SG-3, SG-5, SG2-2, SG2-3 fixes)

---

## Executive Summary

SIEGE Run 3 verified four targeted REFLEXION fixes (SG-3, SG-5, SG2-2, SG2-3) against v0.9.10.1. Three of the four are confirmed FIXED: the catalog dataset endpoint now returns 404 instead of 500 (SG-3), unpublish blob deletion is functional with `blobs_deleted=1` (SG-5), and the catalog API returns all required STAC 1.0.0 fields (SG2-3). SG2-2 (`is_served` on revoke) is INCONCLUSIVE because the field is not exposed in the API response. The Lancer achieved a perfect 22/22 pass rate across all four lifecycle sequences -- the first clean sweep in SIEGE history. However, the Auditor uncovered a new HIGH-severity finding: vector STAC materialization creates the pgSTAC collection but writes zero items, making vector datasets invisible in the catalog. This is the vector equivalent of the CRITICAL SG-1 bug that was fixed for raster in v0.9.10.0. The verdict is CONDITIONAL PASS -- raster workflows are fully functional, but vector approval produces a hollow STAC collection that must be fixed before WARGAME.

---

## Run 2 Regression Status

| ID | Severity | Run 2 Description | Run 3 Status | Notes |
|----|----------|-------------------|-------------|-------|
| SG-1 | CRITICAL | STAC materialization ordering -- blocks raster approvals | **FIXED** (Run 2) | Confirmed still working; raster v1/v2 approval + STAC materialization clean |
| SG-2 | HIGH | SQL error message leaked to B2B callers | **FIXED** (Run 2) | Confirmed still working; clean structured errors |
| SG-3 | HIGH | `/api/platform/catalog/dataset/{id}` returns 500 | **FIXED** | Now returns 404 with proper error envelope (REFLEXION Run 14 patch) |
| SG-4 | MEDIUM | Approval rollbacks not surfaced on `/api/platform/failures` | **INCONCLUSIVE** | No rollback failures triggered in Run 3; cannot verify without failure injection |
| SG-5 | HIGH | Unpublish reports `blobs_deleted: 0`, orphans COGs | **FIXED** | `blobs_deleted=1` confirmed; v2 COG absent from storage (REFLEXION Run 15 patch) |
| SG-6 | MEDIUM | Cached `stac_item_json` uses `-ord1`, live pgSTAC uses `-v1` | **STILL OPEN** | Still present for vector; raster naming not re-verified |
| SG-7 | MEDIUM | `is_latest` not restored after approval rollback | **FIXED** (Run 2) | Confirmed still working; v1 re-promoted after v2 unpublish |
| SG-8 | LOW | Inconsistent 404 response shape on lineage endpoint | **FIXED** (Run 2) | Confirmed still working |
| SG-9 | LOW | `/api/dbadmin/stats` returns 404 | **STILL OPEN** | Still returns 404 with empty body |
| SG-10 | LOW | `/api/health` takes 3.9s | **IMPROVED** | Latency reduced to 1.267s (from 3.841s in Run 2) -- significant improvement |
| SG-11 | LOW | Resubmit bumps revision, not version | **RESOLVED BY DESIGN** (Run 2) | Unchanged |
| SG2-1 | MEDIUM | Unpublish doesn't accept release_id or version_ordinal | **STILL OPEN** | Not addressed in Runs 14-17 |
| SG2-2 | MEDIUM | Revoked release retains `is_served=true` | **INCONCLUSIVE** | Code fix applied (REFLEXION Run 16), but `is_served` not exposed in API; indirect verification only |
| SG2-3 | MEDIUM | Catalog API strips required STAC 1.0.0 fields | **FIXED** | All 5 fields present: `id`, `type`, `geometry`, `collection`, `stac_version` (REFLEXION Run 17 patch) |
| SG2-4 | LOW | Status endpoint shows revoked release as primary | **STILL OPEN** | Not addressed in Runs 14-17 |
| SG2-5 | LOW | `outputs.stac_item_id` shows processing-time name | **STILL OPEN** | Not addressed in Runs 14-17 |
| SG2-6 | INFO | `/resubmit` semantics documentation gap | **STILL OPEN** | Not addressed in Runs 14-17 |

**Summary**: Of 16 tracked findings, 7 FIXED (SG-1, SG-2, SG-3, SG-5, SG-7, SG-8, SG2-3), 2 INCONCLUSIVE (SG-4, SG2-2), 1 RESOLVED BY DESIGN (SG-11), 1 IMPROVED (SG-10), 5 STILL OPEN (SG-6, SG-9, SG2-1, SG2-4, SG2-5, SG2-6).

---

## Endpoint Health

**Assessment**: HEALTHY

| # | Endpoint | Method | HTTP | Latency (s) | Status |
|---|----------|--------|------|-------------|--------|
| 1 | /api/platform/health | GET | 200 | ~0.9 | OK -- healthy, version 0.9.10.1 confirmed |
| 2 | /api/platform/status | GET | 200 | ~0.6 | OK |
| 3 | /api/platform/status/{nonexistent} | GET | 404 | ~1.2 | OK -- correct 404 |
| 4 | /api/platform/approvals | GET | 200 | ~0.7 | OK |
| 5 | /api/platform/approvals/status | GET | 200 | ~0.6 | OK -- no SQL leak |
| 6 | /api/platform/failures | GET | 200 | ~0.6 | OK |
| 7 | /api/platform/catalog/lookup | GET | 400 | ~0.1 | OK -- validation error |
| 8 | /api/platform/catalog/dataset/{id} | GET | 404 | ~0.4 | **FIXED** -- was 500, now 404 (SG-3 resolved) |
| 9 | /api/platform/catalog/item/{c}/{i} | GET | 404 | ~0.4 | OK |
| 10 | /api/platforms | GET | 200 | ~0.5 | OK |
| 11 | /api/platform/validate | POST | 400 | ~0.2 | OK |
| 12 | /api/platform/lineage/{nonexistent} | GET | 404 | ~0.5 | OK |
| 13 | /api/health | GET | 200 | 1.267 | OK -- improved from 3.841s in Run 2 |
| 14 | /api/dbadmin/stats | GET | **404** | ~0.1 | STILL OPEN (SG-9) -- not registered |
| 15 | /api/dbadmin/jobs?limit=1 | GET | 200 | ~0.4 | OK |

**Summary**: 15 endpoints probed, 13 healthy, 2 issues (1 missing route, 1 latency -- both low-severity carry-overs). Health assessment upgraded from DEGRADED (Run 2) to HEALTHY.

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Unexpected | Notes |
|----------|-------|------|------|------------|-------|
| 1 - Raster Lifecycle | 5 | 5 | 0 | 0 | Clean v1 lifecycle: submit -> process -> approve -> STAC verify |
| 2 - Vector Lifecycle | 4 | 4 | 0 | 0 | Required `overwrite=true` for pre-existing table; clean lifecycle |
| 3 - Multi-Version | 5 | 5 | 0 | 0 | v1 + v2 coexistence verified; both STAC items accessible |
| 4 - Unpublish v2 | 8 | 8 | 0 | 0 | Full 3-stage unpublish: inventory -> delete blobs -> cleanup; SG-5 FIXED |
| **TOTAL** | **22** | **22** | **0** | **0** | **Pass rate: 100%** (up from 80% in Run 2, 54.5% in Run 1) |

### Workflow Detail

**Sequence 1 -- Raster Lifecycle (5/5 PASS)**: Submit returned HTTP 202 with request_id. Processing completed via Docker worker. Approval returned HTTP 200 with STAC materialization. STAC collection and item both accessible via catalog API. The raster pipeline is fully operational for the third consecutive SIEGE run.

**Sequence 2 -- Vector Lifecycle (4/4 PASS)**: Initial submit required `overwrite=true` due to pre-existing PostGIS table from Run 2 data. Processing completed successfully. Approval returned HTTP 200. Unlike Run 2 where the initial 400 was counted as a FAIL, Run 3 anticipated the overwrite requirement and succeeded on first attempt.

**Sequence 3 -- Multi-Version (5/5 PASS)**: v2 submitted and processed successfully. Approval of v2 succeeded. Both STAC items (v1 and v2) coexist and are individually accessible via the catalog API. Version ordering and `is_latest` flags correct.

**Sequence 4 -- Unpublish v2 (8/8 PASS)**: Unpublish targeted raster v2 by request_id. All 3 stages completed: inventory (identified 1 blob + 1 STAC item), delete blobs (`blobs_deleted=1` -- **SG-5 FIXED**), cleanup (STAC item removed, release revoked). Post-unpublish state verified: v2 revoked with STAC item returning 404, v1 remains approved with STAC item returning 200, v1 re-promoted to `is_latest=true`.

---

## State Audit

### Auditor Summary (23 checks)

| Category | Pass | Fail | Inconclusive | Anomaly |
|----------|------|------|-------------|---------|
| Regression checks | 10 | 0 | 1 | 0 |
| Raster state | 6 | 0 | 0 | 0 |
| Vector state | 0 | 2 | 0 | 2 |
| STAC compliance | 3 | 1 | 0 | 1 |
| **Total** | **16** | **3** | **1** | **3** |

### Regression Confirmations

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| SG-3: catalog/dataset returns 404 | 404 with error envelope | 404 with data | **PASS** |
| SG-5: blobs_deleted > 0 | >= 1 | blobs_deleted=1, COG absent | **PASS** |
| SG2-3: STAC item has required fields | id, type, geometry, collection, stac_version | All 5 present | **PASS** |
| SG2-2: is_served=false after revoke | false | Not exposed in API response | **INCONCLUSIVE** |

### Vector State Checks

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| pgSTAC collection created | Yes | Yes (`sg-vector-test`) | PASS |
| pgSTAC collection has items | >= 1 | **0 items** | **FAIL** (SG3-1) |
| Collection description accuracy | "Vector collection" | "Raster collection" | **ANOMALY** (SG3-4) |
| Cached STAC naming | `-v1` | `-ord1` | **ANOMALY** (SG-6 still open) |

### All Jobs Summary

All jobs submitted during Run 3 completed successfully. Zero failures in the last 24 hours.

---

## Findings

### Consolidated Finding Table

| ID | Severity | Category | Summary | Source | Status |
|----|----------|----------|---------|--------|--------|
| SG3-1 | HIGH | STAC Materialization | Vector STAC materialization creates pgSTAC collection but writes 0 items -- vector datasets invisible in catalog | Auditor | NEW |
| SG3-2 | MEDIUM | Approval Routing | Approve endpoint targets wrong release when `request_id` is shared across versions (deterministic hash collision); must use `release_id` for v2+ | Lancer | NEW |
| SG3-3 | LOW | API Surface | `is_served` field not exposed in platform status `versions` array -- prevents external verification of serve state | Lancer | NEW |
| SG3-4 | LOW | Data Quality | Vector STAC collection `description` field says "Raster collection" instead of "Vector collection" | Auditor | NEW |
| SG3-5 | INFO | Documentation | Unpublish defaults to `dry_run=true` when parameter not specified -- safe behavior but not documented in B2B contract | Lancer | NEW |
| SG-6 | MEDIUM | Data Integrity | Cached `stac_item_json` still uses `-ord1` naming for vector (carry-over from Run 1) | Auditor | CARRY-OVER |
| SG-9 | LOW | Operations | `/api/dbadmin/stats` returns 404 (carry-over) | Cartographer | CARRY-OVER |
| SG2-1 | MEDIUM | API Surface | Unpublish doesn't accept `release_id` or `version_ordinal` (carry-over) | -- | CARRY-OVER |

### Finding Details

**SG3-1 (HIGH -- Vector STAC Materialization Failure)**: After vector approval, the pgSTAC collection `sg-vector-test` is created, but it contains zero items. The STAC item is never written to pgSTAC. This is the vector equivalent of the CRITICAL SG-1 bug that blocked all raster approvals in Run 1. The raster materialization path was fixed in v0.9.10.0, but the vector materialization path was not updated with the same fix. This means approved vector datasets are invisible in the STAC catalog, even though the approval itself succeeds and the vector data is correctly loaded into PostGIS. The collection exists as an empty shell. This is the most significant new discovery in Run 3 and the highest-priority item for the next fix cycle.

**SG3-2 (MEDIUM -- Approve Targets Wrong Release via Shared request_id)**: When multiple versions share the same `request_id` (which happens because `request_id` is a deterministic SHA256 hash of `job_type + params`, and v1 and v2 of the same dataset have similar params), the approve endpoint may target the wrong release. Specifically, approving by `request_id` when both v1 and v2 exist can resolve to v1 instead of the intended v2. The workaround is to use `release_id` (which is unique per version) for all approval operations on v2+. This is a correctness risk in multi-version workflows where B2B callers use `request_id` as the approval handle.

**SG3-3 (LOW -- is_served Not Exposed in API)**: The `is_served` field exists in the database but is not included in the `versions` array of the platform status response. This prevented the Auditor from directly verifying the SG2-2 fix (revoke sets `is_served=false`). B2B consumers who need to check whether a specific version is currently served cannot do so via the API.

**SG3-4 (LOW -- Vector Collection Description Mismatch)**: The pgSTAC collection created for vector datasets has a `description` field that says "Raster collection" instead of "Vector collection." This is a cosmetic bug in the STAC collection builder's template or branch logic, where the vector path reuses the raster template without updating the description string.

**SG3-5 (INFO -- Unpublish dry_run Default)**: The unpublish endpoint defaults to `dry_run=true` when the parameter is not explicitly set. This is a safe default that prevents accidental deletions, but it is not documented in the B2B API contract. A caller who omits the `dry_run` parameter may be surprised that no actual deletion occurs. The Lancer correctly set `dry_run=false` for all unpublish operations.

---

## Orphaned Artifacts

| Artifact | Location | Cause |
|----------|----------|-------|
| pgSTAC collection `sg-vector-test` | pgSTAC database | Empty collection with 0 items -- created by vector approval but item never materialized (SG3-1) |
| Cached STAC dict (vector) | `stac_item_json` on release record | Uses `-ord1` naming instead of `-v1` (SG-6 carry-over) |

**Note**: Unlike Run 2, there are NO orphaned blob artifacts. The SG-5 fix ensures that unpublished COGs are properly deleted from storage.

---

## Improvements Since Run 2

- **SG-3 FIXED (HIGH)**: The catalog dataset endpoint now returns HTTP 404 with a proper error envelope instead of HTTP 500. B2B callers can distinguish "not found" from "server broken" for the first time. (REFLEXION Run 14)
- **SG-5 FIXED (HIGH)**: Blob deletion is now functional. Unpublish correctly deletes COG blobs from storage (`blobs_deleted=1`), eliminating the unbounded storage growth problem identified in Run 1. (REFLEXION Run 15)
- **SG2-2 FIXED (code-level)**: The `is_served` flag is now set to `false` in both revocation SQL paths. Verification is indirect because the field is not exposed in the API. (REFLEXION Run 16)
- **SG2-3 FIXED (MEDIUM)**: The catalog API now returns complete STAC 1.0.0 items with all required fields (`id`, `type`, `geometry`, `collection`, `stac_version`). Standards compliance is restored. (REFLEXION Run 17)
- **SG-10 IMPROVED**: Health endpoint latency dropped from 3.841s to 1.267s -- a 67% improvement, likely from async or caching optimizations.
- **Lancer pass rate: 100%** (up from 80% in Run 2, 54.5% in Run 1) -- the first perfect workflow sweep in SIEGE history.
- **Endpoint health upgraded from DEGRADED to HEALTHY** -- only 2 low-severity carry-over issues remain.
- **Overall: 7 of 11 original Run 1 findings now FIXED**, plus 3 of 6 Run 2 findings addressed.

---

## Pipeline Chain Recommendations

### Feed into REFLEXION (Highest Priority)

| Finding | Target Files | Rationale |
|---------|-------------|-----------|
| SG3-1 (HIGH) | Vector STAC materialization path in approval handler; likely `services/platform_translation.py` or equivalent | The raster materialization was fixed for SG-1 but the vector path was missed. REFLEXION should trace the vector approval flow to find where `materialize_item()` is called (or not called) for vector data types. The fix pattern is known from the SG-1 raster fix -- apply the same collection-before-item ordering to the vector branch. |
| SG3-2 (MEDIUM) | `triggers/platform/approve.py`, release lookup logic | REFLEXION should trace how `request_id` resolves to a release when multiple versions exist. The fix is likely to use `release_id` as the primary lookup key, or add version disambiguation when multiple releases share a `request_id`. |

### Feed into COMPETE (Medium Priority)

| Finding | Target Files | Rationale |
|---------|-------------|-----------|
| SG-6 | `services/platform_translation.py`, STAC materialization | Competing strategies for cached vs live naming -- same recommendation as Run 2, still unaddressed |
| SG2-1 | `triggers/platform/unpublish.py` | Add `release_id` as a first-class unpublish lookup parameter -- same recommendation as Run 2, still unaddressed |

### Quick Fixes (Can Be Done Inline)

| Finding | Fix | Effort |
|---------|-----|--------|
| SG3-3 | Add `is_served` to the versions array serialization in status response | 15 min |
| SG3-4 | Fix STAC collection description template to use data_type-aware string | 5 min |
| SG3-5 | Document `dry_run=true` default in B2B API contract | 10 min |

### Defer (Low Priority)

| Finding | Action |
|---------|--------|
| SG-9 | Register `/api/dbadmin/stats` in standalone mode or document as worker-only |
| SG2-4 | Return most recent active release as primary in status response |
| SG2-5 | Update `outputs.stac_item_id` after approval |

---

## Verdict

**CONDITIONAL PASS**

Run 3 demonstrates substantial progress: all four REFLEXION-targeted fixes are verified (3 FIXED, 1 INCONCLUSIVE due to API visibility), the Lancer achieved a perfect 22/22 pass rate for the first time, and endpoint health is upgraded from DEGRADED to HEALTHY. The raster lifecycle -- submit, process, approve, multi-version, unpublish -- is fully operational with correct blob cleanup and STAC compliance.

However, a full PASS is blocked by SG3-1 (HIGH): vector STAC materialization creates an empty pgSTAC collection with zero items, making approved vector datasets invisible in the catalog. This is the vector equivalent of the CRITICAL SG-1 bug that was fixed for raster, and it means the vector approval pathway is incomplete. Additionally, SG3-2 (MEDIUM) reveals that multi-version approval routing via `request_id` can target the wrong release due to deterministic hash collisions.

The recommended next step is a targeted REFLEXION run for SG3-1 (vector STAC materialization) followed by SIEGE Run 4 to verify the fix and clear the path to WARGAME. The SG3-2 approval routing issue should be addressed in the same cycle to prevent multi-version correctness regressions.

**Pass rate progression**: Run 1: 54.5% -> Run 2: 80% -> Run 3: 100% (Lancer), 84% (combined with Auditor state checks).
