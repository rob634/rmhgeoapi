# SIEGE Report -- Run 1

**Date**: 01 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.9.0
**Pipeline**: SIEGE (Cartographer -> Lancer -> Auditor -> Scribe)
**Status**: FAIL

---

## Executive Summary

The Platform API surface is broadly functional but contains three categories of defect that prevent a passing verdict: (1) a SQL injection surface where raw database errors leak to callers via `/api/platform/approvals/status`, (2) a STAC materialization ordering bug that blocks all raster approvals, and (3) inconsistent error handling across catalog endpoints that returns 500 instead of 404 for missing resources. Six of eleven workflow steps passed, but the raster lifecycle and unpublish flows are fully blocked, and orphaned artifacts (127 MB COG) were left behind with no catalog reference.

---

## Endpoint Health

**Assessment**: DEGRADED

### Platform API (B2B Surface)

| # | Endpoint | Method | HTTP | Latency (s) | Status |
|---|----------|--------|------|-------------|--------|
| 1 | /api/platform/health | GET | 200 | 0.921 | OK -- Healthy, v0.9.9.0 |
| 2 | /api/platform/status | GET | 200 | 0.695 | OK -- Empty list, correct |
| 3 | /api/platform/status/{nonexistent} | GET | 404 | 1.202 | OK -- Correct 404 with hint |
| 4 | /api/platform/approvals | GET | 200 | 0.684 | OK -- Paginated, correct |
| 5 | /api/platform/approvals/status?stac_item_ids=nonexistent | GET | 200 | 0.491 | **BUG** -- SQL error leaked to caller |
| 6 | /api/platform/failures | GET | 200 | 0.603 | OK -- Zero failures |
| 7 | /api/platform/catalog/lookup?dataset_id=nonexistent | GET | 400 | 0.183 | OK -- Correct validation |
| 8 | /api/platform/catalog/dataset/nonexistent | GET | 500 | 0.997 | **BUG** -- 500 instead of 404 |
| 9 | /api/platform/catalog/item/nonexistent/nonexistent | GET | 404 | 0.317 | OK |
| 10 | /api/platforms | GET | 200 | 0.427 | OK -- 1 platform ("ddh") |
| 11 | /api/platform/validate | POST | 200 | 0.587 | OK -- Dry-run works |
| 12 | /api/platform/lineage/{nonexistent} | GET | 404 | 0.509 | **INCONSISTENCY** -- 404 missing `success` and `error_type` fields |

### Verification Endpoints

| # | Endpoint | Method | HTTP | Latency (s) | Status |
|---|----------|--------|------|-------------|--------|
| 13 | /api/health | GET | 200 | 3.869 | SLOW -- 3.9s, checks 19 subsystems |
| 14 | /api/dbadmin/stats | GET | 404 | 0.107 | **MISSING** -- Not registered in current app mode |
| 15 | /api/dbadmin/jobs?limit=1 | GET | 200 | 0.343 | OK |

**Summary**: 15 endpoints probed. 10 healthy, 2 bugs, 1 inconsistency, 1 missing, 1 slow.

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Unexpected | Notes |
|----------|-------|------|------|------------|-------|
| Raster Lifecycle | 4 | 2 | 2 | 0 | Approval blocked by STAC materialization ordering |
| Vector Lifecycle | 3 | 3 | 0 | 0 | Fully passed -- skips STAC materialization |
| Multi-Version | 2 | 1 | 0 | 1 | Resubmit bumps revision instead of creating v2 |
| Unpublish | 2 | 0 | 2 | 0 | Cascading failure from raster approval |
| **TOTAL** | **11** | **6** | **4** | **1** | **Pass rate: 54.5%** |

### Workflow Detail

**Raster Lifecycle**: Submit and processing completed successfully. Approval fails because `materialize_item()` is called before `materialize_collection()` in `stac_materialization.py`. For new collections the collection does not exist yet, so the item insert fails. The system correctly rolls the release back to `pending_review`.

**Vector Lifecycle**: Fully passed end-to-end. Vector approvals bypass STAC materialization entirely, avoiding the ordering bug.

**Multi-Version**: Resubmit with identical parameters bumps the revision on the existing release instead of creating a new version (v2). The `request_id` is deterministic (SHA256 of `dataset_id + resource_id`), so resubmission reuses the same `request_id`. This may be intentional but was flagged as unexpected because the caller likely expects a new version.

**Unpublish**: Both steps failed. This is a cascading failure -- nothing was approved, so nothing existed to unpublish.

---

## State Audit

| # | Check | Expected | Actual | Verdict |
|---|-------|----------|--------|---------|
| 1 | Platform requests list | 2 requests | 2 requests (raster + vector) | PASS |
| 2 | Approval states | 1 pending_review, 1 approved | raster=pending_review (rolled back), vector=approved | PASS |
| 3 | Failures endpoint | Record of approval failure | 0 failures -- rollbacks not surfaced | ANOMALY |
| 4 | System health | Healthy | Healthy, ready_for_jobs=true | PASS |
| 5 | Raster STAC item | 404 (approval failed) | 404 | PASS |
| 6 | Vector STAC item | 404 (vector skips STAC) | 404 | EXPECTED |
| 7 | /catalog/dataset/sg-raster-test | 404 or empty | 500 Internal Server Error | FAIL |
| 8 | /catalog/dataset/sg-vector-test | 404 or empty | 500 Internal Server Error | FAIL |
| 9 | All jobs completed | 3 completed | 3 completed (raster x2, vector x1) | PASS |
| 10 | Orphaned tasks | None | /api/dbadmin/diagnostics/all returns 404 | N/A |

**Summary**: 10 checks performed. 6 passed, 2 failed, 1 anomaly, 1 not assessable.

---

## Findings

| ID | Severity | Category | Summary | Source |
|----|----------|----------|---------|--------|
| SG-1 | **CRITICAL** | STAC | `materialize_item()` called before `materialize_collection()` -- blocks all raster approvals for new collections | Lancer |
| SG-2 | **HIGH** | Security | SQL error leaked to caller on `/api/platform/approvals/status?stac_item_ids=nonexistent` -- exposes `op ANY/ALL (array) requires array on right side` | Cartographer |
| SG-3 | **HIGH** | Error Handling | `/api/platform/catalog/dataset/{id}` returns 500 for nonexistent datasets instead of 404 | Cartographer, Auditor |
| SG-4 | **MEDIUM** | Observability | `/api/platform/failures` does not surface approval-phase rollbacks -- silent failure path | Auditor |
| SG-5 | **MEDIUM** | Data Integrity | Orphaned COG blob `silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` (127 MB) exists with no STAC catalog reference | Auditor |
| SG-6 | **MEDIUM** | Data Integrity | `stac_item_id` on release uses `-v1` suffix but cached STAC JSON uses `-ord1` -- naming mismatch | Auditor |
| SG-7 | **MEDIUM** | State | `is_latest=False` on the only release for an asset -- not restored after approval rollback | Auditor |
| SG-8 | **LOW** | Consistency | `/api/platform/lineage/{id}` 404 response missing `success` and `error_type` fields -- differs from all other 404 responses | Cartographer |
| SG-9 | **LOW** | Operations | `/api/dbadmin/stats` and `/api/dbadmin/diagnostics/all` return 404 -- not registered in current app mode | Cartographer, Auditor |
| SG-10 | **LOW** | Performance | `/api/health` takes 3.9 seconds -- checks 19 subsystems synchronously | Cartographer |
| SG-11 | **LOW** | Versioning | Resubmit with same parameters bumps revision on existing release instead of creating v2 -- may surprise callers expecting distinct versions | Lancer |

---

## Orphaned Artifacts

| Artifact | Location | Size | Cause |
|----------|----------|------|-------|
| COG blob | `silver-cogs/sg-raster-test/dctest/1/dctest_cog_analysis.tif` | 127 MB | Raster processing completed but approval failed -- COG written to storage with no STAC catalog entry and no cleanup on rollback |

**Recommendation**: Implement a cleanup hook in the approval rollback path that either deletes the COG or marks it for garbage collection. Alternatively, add a periodic orphan scan job.

---

## Reproduction Commands

### SG-1: STAC Materialization Ordering (CRITICAL)

```bash
# Step 1: Submit a raster with a NEW dataset_id (forces new collection creation)
curl -s -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "sg-repro-raster",
    "resource_id": "repro-file",
    "version_id": "1",
    "platform_id": "ddh",
    "source_url": "https://rmhazuregeobronze.blob.core.windows.net/test/sample.tif",
    "data_type": "raster"
  }'

# Step 2: After processing completes, attempt approval — will fail with
# collection-not-found error in stac_materialization.py
```

### SG-2: SQL Error Leak (HIGH)

```bash
# Passes a bare string instead of an array to the ANY/ALL operator
curl -s "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/approvals/status?stac_item_ids=nonexistent"
```

### SG-3: 500 on Missing Dataset (HIGH)

```bash
# Should return 404, returns 500
curl -s -o /dev/null -w "%{http_code}" \
  "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/catalog/dataset/nonexistent"
```

### SG-4: Failures Endpoint Missing Rollbacks (MEDIUM)

```bash
# After a failed raster approval, this still shows 0 failures
curl -s "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/failures"
```

### SG-6: stac_item_id Naming Mismatch (MEDIUM)

```bash
# Check release stac_item_id vs cached STAC JSON
# Compare the -v1 suffix on release.stac_item_id against -ord1 in release.stac_json_cache
curl -s "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/status" | python3 -m json.tool
```

---

## Pipeline Chain Recommendations

### Feed into COMPETE

| Finding | Target Files | Rationale |
|---------|-------------|-----------|
| SG-1 | `services/stac_materialization.py` | Generate competing fix strategies: (A) reorder to collection-first, (B) upsert-or-create guard, (C) lazy collection creation. COMPETE evaluates tradeoffs. |
| SG-6 | `services/platform_translation.py`, `core/models/release.py` | Competing naming strategies: unify on `-ord` vs `-v` suffix. COMPETE evaluates downstream impact on STAC clients. |

### Feed into REFLEXION

| Finding | Target Files | Rationale |
|---------|-------------|-----------|
| SG-2 | `triggers/platform/approvals_status.py` (or equivalent handler) | REFLEXION self-corrects: parse `stac_item_ids` as comma-separated list into array before passing to SQL. Validate input shape. |
| SG-3 | `services/platform_catalog.py` (or equivalent handler) | REFLEXION self-corrects: wrap dataset lookup in try/except, return 404 with standard error envelope when dataset not found. |
| SG-4 | `services/approval_handler.py` (or equivalent) | REFLEXION self-corrects: on approval rollback, write a record to the failures table with `failure_type=approval_rollback`. |
| SG-7 | `core/models/release.py` | REFLEXION self-corrects: approval rollback should restore `is_latest=True` when the release is the only one for its asset. |
| SG-8 | `triggers/platform/lineage.py` (or equivalent handler) | REFLEXION self-corrects: add `success` and `error_type` fields to 404 response to match API-wide contract. |

### Defer (Low Priority)

| Finding | Action |
|---------|--------|
| SG-9 | Register `/api/dbadmin/stats` and `/api/dbadmin/diagnostics/all` in standalone app mode, or document that they are worker-only endpoints. |
| SG-10 | Consider parallelizing the 19 subsystem checks in `/api/health`, or adding a lightweight `/api/health/ping` endpoint. |
| SG-11 | Document the resubmit-bumps-revision behavior in the B2B API contract. If v2 creation is desired, require an explicit `version_id` bump from the caller. |

---

## Verdict

**FAIL**

The system fails the SIEGE assessment due to one CRITICAL and two HIGH severity findings:

1. **SG-1 (CRITICAL)**: Raster approval is completely broken for new collections. The STAC materialization ordering bug in `stac_materialization.py` calls `materialize_item()` before the parent collection exists, causing all first-time raster approvals to fail and roll back. This blocks the primary B2B workflow.

2. **SG-2 (HIGH)**: Raw SQL error messages are leaked to external callers through the approvals status endpoint, exposing internal database schema details. This is both a security risk and a contract violation.

3. **SG-3 (HIGH)**: The catalog dataset endpoint returns 500 Internal Server Error for missing resources instead of 404, violating HTTP semantics and making it impossible for callers to distinguish between "not found" and "server error."

Additionally, five MEDIUM findings indicate gaps in observability (silent approval rollbacks), data integrity (orphaned COGs, naming mismatches), and state management (incorrect `is_latest` flag after rollback).

**Recommended next step**: Fix SG-1 first (unblocks raster lifecycle), then SG-2 and SG-3 (security and correctness). Route through COMPETE for SG-1 and REFLEXION for SG-2/SG-3 as detailed above.
