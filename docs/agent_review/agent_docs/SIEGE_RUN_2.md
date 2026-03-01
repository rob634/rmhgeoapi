# SIEGE Report -- Run 2

**Date**: 01 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.10.0
**Pipeline**: SIEGE (Sentinel -> Cartographer -> Lancer -> Auditor -> Scribe)
**Status**: CONDITIONAL PASS
**Context**: Re-run after fixes deployed for SG-1 through SG-11 from Run 1

---

## Executive Summary

SIEGE Run 2 re-tested the full B2B platform lifecycle against v0.9.10.0 to verify fixes for the 11 findings from Run 1. The CRITICAL blocker (SG-1: STAC materialization ordering) is fixed -- raster approval, multi-version coexistence, and selective unpublish all work end-to-end for the first time. Of the original 11 findings, 4 are confirmed fixed (SG-1, SG-2, SG-7, SG-8), 1 is inconclusive (SG-4), 3 remain open (SG-3, SG-5, SG-6), and 3 low-severity operational items are unchanged (SG-9, SG-10, SG-11). Three new findings emerged: the unpublish endpoint's narrow parameter acceptance, the revoked release retaining `is_served=true`, and the catalog API stripping required STAC 1.0.0 fields. The verdict is CONDITIONAL PASS -- the primary B2B workflows function correctly, but blob cleanup, catalog dataset lookup, and STAC compliance gaps must be addressed before WARGAME.

---

## Run 1 Regression Status

| ID | Severity | Run 1 Description | Run 2 Status | Notes |
|----|----------|-------------------|-------------|-------|
| SG-1 | CRITICAL | `materialize_item()` called before `materialize_collection()` -- blocks all raster approvals for new collections | **FIXED** | Raster v1 and v2 both approved successfully; STAC items materialized |
| SG-2 | HIGH | `/api/platform/approvals/status` leaks raw SQL error to B2B callers | **FIXED** | Returns structured `ValidationError` (HTTP 400) or clean `lookup_error` JSON |
| SG-3 | HIGH | `/api/platform/catalog/dataset/{id}` returns 500 instead of 404 for nonexistent datasets | **NOT FIXED** | Still returns HTTP 500 with generic "Internal server error" even for valid datasets |
| SG-4 | MEDIUM | `/api/platform/failures` does not surface approval-phase rollbacks | **INCONCLUSIVE** | No rollback failures occurred during Run 2; cannot verify without failure injection |
| SG-5 | MEDIUM | Orphaned COG blob exists with no STAC catalog reference after unpublish | **NOT FIXED** | Unpublish reports `blobs_deleted: 0` despite `unpublish_delete_blob` task completing; 127 MB orphan confirmed |
| SG-6 | MEDIUM | `stac_item_id` uses `-v1` but cached STAC JSON self-link uses `-ord1` | **NOT FIXED** | Cached `stac_item_json` self-link still uses `-ord1`; live pgSTAC item correctly uses `-v1` |
| SG-7 | MEDIUM | `is_latest` stuck at false after approval rollback | **FIXED** | After v2 unpublish, v1 correctly has `is_latest=true` |
| SG-8 | LOW | `/api/platform/lineage/{id}` 404 response missing `success` and `error_type` fields | **FIXED** | Returns `{success: false, error: "...", error_type: "NotFound", timestamp: "..."}` |
| SG-9 | LOW | `/api/dbadmin/stats` returns 404 -- not registered in current app mode | **NOT FIXED** | Still returns HTTP 404 with empty body |
| SG-10 | LOW | `/api/health` takes 3.9s -- checks 19 subsystems synchronously | **NOT FIXED** | Measured at 3.841s, essentially unchanged |
| SG-11 | LOW | Resubmit with same parameters bumps revision instead of creating v2 | **RESOLVED BY DESIGN** | `/resubmit` is retry-only (409 for approved); `/submit` with same identifiers correctly creates v2 |

**Summary**: 4 fixed, 3 not fixed, 1 inconclusive, 3 low-priority unchanged/by-design.

---

## Endpoint Health

**Assessment**: DEGRADED

### Platform API (B2B Surface)

| # | Endpoint | Method | HTTP | Latency (s) | Status |
|---|----------|--------|------|-------------|--------|
| 1 | /api/platform/health | GET | 200 | 0.902 | OK -- healthy, version 0.9.10.0 confirmed |
| 2 | /api/platform/status | GET | 200 | 0.575 | OK -- returns paginated request list |
| 3 | /api/platform/status/{nonexistent} | GET | 404 | 1.250 | OK -- correct 404 with helpful hint |
| 4 | /api/platform/approvals | GET | 200 | 0.714 | OK -- paginated with status_counts |
| 5 | /api/platform/approvals/status?stac_item_ids=nonexistent | GET | 200 | 0.654 | OK -- clean JSON, no SQL leak (SG-2 FIXED) |
| 6 | /api/platform/failures | GET | 200 | 0.626 | OK -- failure report structure |
| 7 | /api/platform/catalog/lookup?dataset_id=nonexistent | GET | 400 | 0.138 | OK -- correct validation error |
| 8 | /api/platform/catalog/dataset/nonexistent | GET | **500** | 0.859 | BUG -- 500 instead of 404 (SG-3 persists) |
| 9 | /api/platform/catalog/item/nonexistent/nonexistent | GET | 404 | 0.410 | OK -- correct 404 with error_type |
| 10 | /api/platforms | GET | 200 | 0.452 | OK -- DDH platform definition |
| 11 | /api/platform/validate | POST | 400 | 0.211 | OK -- validates container_name and abfs:// scheme |
| 12 | /api/platform/lineage/{nonexistent} | GET | 404 | 0.479 | OK -- consistent shape (SG-8 FIXED) |

### Verification Endpoints

| # | Endpoint | Method | HTTP | Latency (s) | Status |
|---|----------|--------|------|-------------|--------|
| 13 | /api/health | GET | 200 | 3.841 | SLOW -- 52KB JSON, ~3.8s (SG-10 persists) |
| 14 | /api/dbadmin/stats | GET | **404** | 0.114 | BUG -- not registered (SG-9 persists) |
| 15 | /api/dbadmin/jobs?limit=1 | GET | 200 | 0.360 | OK |

**Summary**: 15 endpoints probed, 12 healthy, 3 issues (1 bug, 1 missing, 1 slow).

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Unexpected | Notes |
|----------|-------|------|------|------------|-------|
| Raster Lifecycle | 5 | 5 | 0 | 0 | SG-1 FIXED -- full submit/approve/STAC verified |
| Vector Lifecycle | 4 | 3 | 1 | 0 | Orphaned release from Run 1 required overwrite; clean error msg |
| Multi-Version | 5 | 4 | 0 | 1 | /resubmit is retry-only (409); /submit creates v2 correctly |
| Unpublish | 6 | 4 | 2 | 0 | Unpublish by release_id and version_ordinal rejected; request_id works |
| **TOTAL** | **20** | **16** | **3** | **1** | **Pass rate: 80%** (up from 54.5% in Run 1) |

### Workflow Detail

**Raster Lifecycle (5 steps, all PASS)**: Submit returned HTTP 202 with `request_id`. Processing completed via Docker worker. Approval returned HTTP 200 -- the CRITICAL SG-1 bug is confirmed fixed. STAC collection `sg-raster-test-dctest` was created, and item `sg-raster-test-dctest-v1` is accessible via the catalog API with correct bbox, links, and assets. The stac_item_id was renamed from `-ord1` (processing time) to `-v1` (post-approval) as designed.

**Vector Lifecycle (4 steps, 3 PASS / 1 FAIL)**: Initial submit returned HTTP 400 with `OrphanedReleaseError` -- an orphaned release from SIEGE Run 1. The error message was clean and actionable ("Resubmit with processing_options.overwrite=true to retry"), confirming SG-2 fix. Resubmit with overwrite succeeded. Vector processing completed in ~20s. Approval returned HTTP 200. The initial 400 is counted as a FAIL but is expected cleanup from the prior run, not a product bug.

**Multi-Version (5 steps, 4 PASS / 1 UNEXPECTED)**: The `/resubmit` endpoint returned 409 for the already-approved raster, correctly enforcing retry-only semantics. Fresh `/submit` with `overwrite=true` created v2 (version_ordinal=2). Processing completed after 4 polls (~40s). Approval of v2 succeeded. Both STAC items coexist: `sg-raster-test-dctest-v1` and `sg-raster-test-dctest-v2` both return HTTP 200. The UNEXPECTED verdict on `/resubmit` reflects a semantic clarification, not a bug.

**Unpublish (6 steps, 4 PASS / 2 FAIL)**: Unpublish by `version_ordinal` and by `release_id` both returned HTTP 400 -- neither parameter is recognized by the endpoint. Unpublish by `request_id` succeeded (HTTP 200), targeting the latest release (v2). The unpublish job completed all 3 stages. Post-unpublish state is correct: v2 is revoked with STAC item removed (404), v1 remains approved with STAC item intact (200). The 2 FAILs indicate a gap in the unpublish API's parameter flexibility.

---

## State Audit

### Checkpoint R1: Raster v1 Approved (12 checks, 12 PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| request_id | 6207de49b0ea4c987304bbc114ca2277 | matches | PASS |
| asset_id | 8d1f79aa42b31e436dcb713b4360fa5b | matches | PASS |
| release_id (v1) | 753386c51d26b715c4aa454b8c9100ad | matches | PASS |
| v1 approval_state | approved | approved | PASS |
| v1 version_ordinal | 1 | 1 | PASS |
| v1 is_latest | true | true | PASS |
| v1 processing_status | completed | completed | PASS |
| v1 stac_item_id | sg-raster-test-dctest-v1 | sg-raster-test-dctest-v1 | PASS |
| v1 stac_collection_id | sg-raster-test-dctest | sg-raster-test-dctest | PASS |
| STAC item v1 HTTP | 200 | 200 | PASS |
| STAC item v1 self-link | contains sg-raster-test-dctest-v1 | correct | PASS |
| v1 COG exists | yes | 127.07 MB in silver-cogs | PASS |

### Checkpoint V1: Vector v1 Approved (11 checks, 11 PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| request_id | 761f7dc6b60d9c39bd727235d8c991ee | matches | PASS |
| asset_id | 1790a5e0d2dd484a4505ba14a26b61fd | matches | PASS |
| release_id | 912791ed788abaaef11c9d57335ea5d3 | matches | PASS |
| approval_state | approved | approved | PASS |
| version_ordinal | 1 | 1 | PASS |
| is_latest | true | true | PASS |
| processing_status | completed | completed | PASS |
| job_status | completed | completed | PASS |
| data_type | vector | vector | PASS |
| table_names | sg_vector_test_cutlines_ord1 | matches | PASS |
| release_count | 1 | 1 | PASS |

### Checkpoint MV1: Multi-Version (6 checks, 6 PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| v1 release_id | 753386c51d26b715c4aa454b8c9100ad | matches | PASS |
| v1 approval_state | approved | approved | PASS |
| v2 release_id | add6224638fdeb65a2b0e0032418120a | matches | PASS |
| v2 approval_state | revoked (post-unpublish) | revoked | PASS |
| release_count | 2 | 2 | PASS |
| versions array length | 2 | 2 | PASS |

### Checkpoint U1: After Unpublish of Raster v2 (13 checks, 13 PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| v1 approval_state | approved | approved | PASS |
| v1 is_latest | true | true | PASS |
| v2 approval_state | revoked | revoked | PASS |
| v2 is_latest | false | false | PASS |
| v2 revoked_at | not null | 2026-03-01T03:21:52.982285 | PASS |
| v2 revoked_by | platform_unpublish | platform_unpublish | PASS |
| v2 revocation_reason | present | "Unpublished via platform endpoint" | PASS |
| STAC item v1 | 200 | 200 | PASS |
| STAC item v2 | 404 | 404 | PASS |
| Unpublish job status | completed | completed | PASS |
| Unpublish stages | 3/3 | 3/3 | PASS |
| Unpublish inventory task | completed | completed | PASS |
| Unpublish delete_stac task | completed | completed | PASS |

### All Jobs Summary

| Job ID (prefix) | Type | Status | Stages | Verdict |
|-----------------|------|--------|--------|---------|
| d21f4894... | unpublish_raster | completed | 3/3 | PASS |
| f0092a87... | process_raster_docker | completed | 1/1 | PASS |
| cd86d72f... | vector_docker_etl | completed | 1/1 | PASS |
| 241dbefb... | process_raster_docker | completed | 1/1 | PASS |

4 jobs executed, 4 completed. Zero failures in the last 24 hours.

### Audit Totals

| Metric | Count |
|--------|-------|
| Checks performed | 52 |
| Passed | 47 |
| Failed | 3 |
| Anomalies | 5 |

---

## Findings

### Consolidated Finding Table

| ID | Severity | Category | Summary | Source | Status |
|----|----------|----------|---------|--------|--------|
| SG-3 | HIGH | Error Handling | `/api/platform/catalog/dataset/{id}` returns HTTP 500 instead of 404 -- even for datasets that exist as assets | Cartographer, Auditor | CARRY-OVER (not fixed) |
| SG-5 | HIGH | Data Integrity | Unpublish pipeline reports `blobs_deleted: 0` despite `unpublish_delete_blob` task completing -- 127 MB orphan COG in silver-cogs | Auditor | CARRY-OVER (upgraded from MEDIUM) |
| SG-6 | MEDIUM | Data Integrity | Cached `stac_item_json` self-link uses `-ord1` naming; live pgSTAC item uses `-v1` -- inconsistency between cached and materialized state | Auditor | CARRY-OVER (not fixed) |
| SG-9 | LOW | Operations | `/api/dbadmin/stats` returns 404 -- route not registered in standalone app mode | Cartographer | CARRY-OVER (not fixed) |
| SG-10 | LOW | Performance | `/api/health` takes 3.84s (52KB response, 19 subsystem checks) -- unsuitable as load balancer probe | Cartographer | CARRY-OVER (not fixed) |
| SG2-1 | MEDIUM | API Surface | Unpublish endpoint does not accept `release_id` or `version_ordinal` as lookup parameters -- only `request_id`, `job_id`, or DDH identifiers (dataset_id + resource_id + version_id) | Lancer | NEW |
| SG2-2 | MEDIUM | State | Revoked release retains `is_served=true` -- semantically incorrect for a revoked/unpublished release | Auditor | NEW |
| SG2-3 | MEDIUM | STAC Compliance | Catalog API (`/api/platform/catalog/item`) returns STAC items missing required STAC 1.0.0 fields (`id`, `type`, `geometry`, `stac_version`) at top level -- only returns `bbox`, `links`, `assets`, `properties`, `stac_extensions` | Auditor | NEW |
| SG2-4 | LOW | State | Status endpoint shows revoked v2 release as the primary `release` object instead of the active v1; `versions` array is correct but top-level response is misleading | Auditor | NEW |
| SG2-5 | LOW | Naming | Status endpoint `outputs.stac_item_id` shows processing-time name (`-ord1`) rather than post-approval name (`-v1`); callers must use `versions[].stac_item_id` for the correct name | Lancer | NEW |
| SG2-6 | INFO | Semantics | `/api/platform/resubmit` returns 409 for approved releases -- semantics are retry-only (failed/pending_review), not new-version creation | Lancer | NEW (documentation gap) |

### Finding Details

**SG-3 (HIGH -- CARRY-OVER)**: The `/api/platform/catalog/dataset/{id}` endpoint returns HTTP 500 with `error_type: "server_error"` for both nonexistent and valid dataset IDs. This prevents B2B callers from looking up dataset metadata and makes it impossible to distinguish "not found" from "server broken." This is a B2B contract violation that has persisted across both SIEGE runs.

**SG-5 (HIGH -- CARRY-OVER, UPGRADED)**: Severity upgraded from MEDIUM to HIGH. The unpublish pipeline's blob deletion stage completes successfully but deletes zero blobs. The `unpublish_delete_blob` task finishes with `blobs_deleted: 0`, leaving a 127.07 MB COG orphaned in `silver-cogs/sg-raster-test/dctest/2/`. The STAC reference is correctly removed (HTTP 404), so the blob is unreachable via catalog -- but it consumes storage indefinitely. At scale, this causes unbounded storage growth.

**SG-6 (MEDIUM -- CARRY-OVER)**: The cached `stac_item_json` stored on the release record is generated at processing time using ordinal naming (`-ord1` in self-link). The approval flow creates the live pgSTAC item with version naming (`-v1`). The cached JSON is never updated to reflect the final name. B2B consumers who use the cached JSON for reconciliation will see a naming mismatch against the live catalog.

**SG2-1 (MEDIUM -- NEW)**: The unpublish endpoint accepts only three lookup mechanisms: `request_id`, `job_id`, or DDH identifiers (`dataset_id` + `resource_id` + `version_id`). It does not accept `release_id` or `version_ordinal`, which are primary identifiers used throughout the rest of the platform API. A B2B caller that tracks releases by `release_id` cannot unpublish without first resolving to a `request_id`.

**SG2-2 (MEDIUM -- NEW)**: After unpublishing raster v2, the release record has `approval_state=revoked` but `is_served=true`. A revoked release should have `is_served=false` since it is no longer accessible via the catalog. Downstream systems checking serve status would incorrectly believe the content is still being served.

**SG2-3 (MEDIUM -- NEW)**: The catalog API at `/api/platform/catalog/item/{collection}/{item}` returns STAC items that are missing required STAC 1.0.0 specification fields at the top level. The response contains `bbox`, `links`, `assets`, `properties`, and `stac_extensions`, but is missing `id`, `type` (should be `"Feature"`), `geometry`, `collection`, and `stac_version`. The full STAC structure exists in the cached `stac_item_json` on the release record, suggesting the catalog API strips these fields during serialization.

---

## Orphaned Artifacts

| Artifact | Location | Size | Cause |
|----------|----------|------|-------|
| COG blob (raster v2) | `silver-cogs/sg-raster-test/dctest/2/dctest_cog_analysis.tif` | 127.07 MB | Unpublish job completed 3/3 stages but `blobs_deleted=0` -- blob deletion handler does not actually delete (SG-5) |

**Note**: The v1 COG at `silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` (127.07 MB) is NOT orphaned -- it is properly referenced by the active STAC item `sg-raster-test-dctest-v1`.

---

## Improvements Since Run 1

- **SG-1 FIXED (CRITICAL)**: Raster approval works end-to-end. STAC materialization now creates the collection before inserting items. This was the single highest priority fix and unblocks the entire raster lifecycle for new datasets.
- **SG-2 FIXED (HIGH)**: No more SQL error leakage to B2B callers. The approvals/status endpoint returns structured JSON with proper error types. Error messages across the platform are clean and actionable (e.g., `OrphanedReleaseError` provides clear recovery instructions).
- **SG-7 FIXED (MEDIUM)**: The `is_latest` flag is correctly restored after unpublish. When v2 is revoked, v1 is re-promoted to `is_latest=true`.
- **SG-8 FIXED (LOW)**: The lineage endpoint 404 response now includes `success`, `error_type`, and `timestamp` fields, matching the API-wide contract.
- **SG-11 CLARIFIED**: The `/resubmit` vs `/submit` semantics are now understood. `/resubmit` is for retrying failed releases; `/submit` with the same identifiers creates new versions. This is correct behavior, though it should be documented.
- **Overall pass rate improved from 54.5% (Run 1) to 80% (Run 2)**.
- **All 4 lifecycle sequences completed successfully** (Run 1 had 2 blocked sequences).
- **Multi-version coexistence verified** for the first time -- v1 and v2 STAC items coexist correctly.
- **Selective unpublish verified** for the first time -- v2 removed while v1 preserved.

---

## Pipeline Chain Recommendations

### Feed into REFLEXION

| Finding | Target Files | Rationale |
|---------|-------------|-----------|
| SG-3 | Catalog trigger/handler for `/api/platform/catalog/dataset/{id}` | REFLEXION self-corrects: wrap dataset lookup in try/except, return 404 with standard error envelope when dataset not found. May also need route registration fix if the handler is not wired correctly. |
| SG-5 | `services/unpublish_handlers.py` -- `unpublish_delete_blob` handler | REFLEXION self-corrects: the task completes with `blobs_deleted: 0`. Debug the blob path construction and `BlobRepository.delete_blob()` call. Likely a path mismatch or permission issue. |
| SG2-2 | Release state transition logic (approval/revocation handler) | REFLEXION self-corrects: when setting `approval_state=revoked`, also set `is_served=false`. |
| SG2-3 | Catalog item serialization in `services/platform_catalog.py` or equivalent | REFLEXION self-corrects: ensure the catalog API returns the full STAC item structure including `id`, `type`, `geometry`, `collection`, and `stac_version` fields. |

### Feed into COMPETE

| Finding | Target Files | Rationale |
|---------|-------------|-----------|
| SG-6 | `services/platform_translation.py`, STAC materialization | Competing strategies for cached vs live naming: (A) update cached JSON at approval time, (B) generate cached JSON lazily on first access, (C) deprecate cached JSON in favor of live pgSTAC queries. COMPETE evaluates storage vs latency tradeoffs. |
| SG2-1 | `triggers/platform/unpublish.py` | Competing strategies: (A) add `release_id` as a first-class lookup parameter, (B) add a resolver that maps `release_id` to `request_id`, (C) document current limitations and require callers to use `request_id`. |

### Defer (Low Priority)

| Finding | Action |
|---------|--------|
| SG-9 | Register `/api/dbadmin/stats` in standalone app mode or document as worker-only. |
| SG-10 | Add lightweight `/api/health/ping` endpoint for load balancer probes; keep full health check for diagnostics. |
| SG2-4 | Consider returning the most recent *active* release as the primary `release` object in status responses, not the most recent overall. |
| SG2-5 | Update `outputs.stac_item_id` in status response after approval to reflect the final post-approval name. |
| SG2-6 | Document `/resubmit` vs `/submit` semantics in B2B API contract. |

---

## Verdict

**CONDITIONAL PASS**

The primary B2B lifecycle -- submit, process, approve, multi-version, and selective unpublish -- functions correctly for the first time. The CRITICAL SG-1 STAC materialization ordering bug is fixed, unblocking raster approvals. The HIGH SG-2 SQL leak is eliminated. The pass rate improved from 54.5% to 80%, and all four lifecycle sequences completed successfully.

However, three findings prevent a full PASS: SG-5 (blob deletion does not execute, causing unbounded storage orphans -- upgraded to HIGH), SG-3 (catalog dataset endpoint still returns 500 -- a B2B contract violation), and SG2-3 (catalog API returns STAC items missing required spec fields -- a standards compliance gap). These must be fixed before advancing to WARGAME.

The system is safe to proceed to targeted REFLEXION runs for SG-3, SG-5, SG2-2, and SG2-3. A WARGAME assessment should be scheduled after those fixes land.
