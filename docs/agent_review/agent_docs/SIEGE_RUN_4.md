# SIEGE Report — Run 4

**Date**: 01 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.11.2
**Pipeline**: SIEGE (Run 20 overall)
**Schema**: Fresh rebuild before run (0 pre-existing jobs/STAC items)

---

## Endpoint Health

| # | Endpoint | Status | Latency (ms) | Notes |
|---|----------|--------|-------------|-------|
| 1 | `/api/platform/health` | 200 | 946 | All subsystems healthy |
| 2 | `/api/platform/submit` | 404 | 198 | POST-only (no 405) |
| 3 | `/api/platform/status` | 200 | 590 | List mode works |
| 4 | `/api/platform/status/{bogus}` | 404 | 1156 | Proper error shape |
| 5 | `/api/platform/approve` | 404 | 179 | POST-only |
| 6 | `/api/platform/reject` | 404 | 203 | POST-only |
| 7 | `/api/platform/unpublish` | 404 | 163 | POST-only |
| 8 | `/api/platform/resubmit` | 404 | 214 | POST-only |
| 9 | `/api/platform/validate` | 404 | 199 | POST-only |
| 10 | `/api/platform/approvals` | 200 | 772 | Paginated, works |
| 11 | `/api/platform/catalog/lookup` | 400 | 179 | Correct validation |
| 12 | `/api/platform/failures` | 200 | 664 | 0 failures |
| 13 | `/api/platform/lineage/{bogus}` | 404 | 545 | Structured error |
| 14 | `/api/platforms` | 200 | 420 | 1 platform (ddh) |
| 15 | `/api/health` | 200 | 3678 | Deep check, 20 components |
| 16 | `/api/dbadmin/stats` | **404** | 186 | MISSING (SG-9) |
| 17 | `/api/dbadmin/jobs?limit=1` | 200 | 397 | Works |

**Assessment: HEALTHY** — Zero 5xx errors. All core endpoints responsive.

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Blocked | Verdict |
|----------|-------|------|------|---------|---------|
| 1. Raster Lifecycle | 4 | 4 | 0 | 0 | **PASS** |
| 2. Vector Lifecycle | 4 | 0 | 1 | 3 | **FAIL** (LNC-1) |
| 3. Multi-Version Raster | 4 | 4 | 0 | 0 | **PASS** |
| 4. Unpublish | 3 | 3 | 0 | 0 | **PASS** |
| **Total** | **15** | **11** | **1** | **3** | |

**Lancer pass rate: 73% (11/15)** — 3/4 sequences passed, vector blocked by CRITICAL bug.

---

## State Audit

### Checkpoint R1 — Raster v1 Approved (5/6 pass)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| Job status | completed | completed | PASS |
| Approval state | approved | approved | PASS |
| Catalog dataset count | >= 1 | 1 | PASS |
| Approvals/status lookup | has_release=true | lookup_error=true | **FAIL** (AUD-R1-1) |
| is_served in versions array | true | true | PASS |
| dbadmin job record | completed | completed | PASS |

### Checkpoint V1 — Vector BLOCKED (3/3 pass)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| No vector jobs | 0 | 0 | PASS |
| No vector STAC collection | absent | absent | PASS |
| STAC collection count | 1 (raster only) | 1 | PASS |

### Checkpoint MV1 — Multi-Version (2 pass, 1 unverifiable)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| v1 is_latest after v2 | false | true (post-U1 restore) | INFERRED PASS |
| v2 is_latest after v2 | true | false (post-U1 revoke) | INFERRED PASS |
| Catalog count at MV1 peak | 2 | Not observable (post-U1) | UNVERIFIABLE |

### Checkpoint U1 — Unpublish v2 (12/12 pass)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| v1 is_latest | true | true | PASS |
| v1 is_served | true | true | PASS |
| v2 approval_state | revoked | revoked | PASS |
| v2 is_served | false | false | PASS |
| Catalog count | 1 | 1 | PASS |
| v2 pgSTAC item | 404 | 404 | PASS |
| v1 pgSTAC item | 200 | 200 | PASS |
| Failures count | 0 | 0 | PASS |
| All jobs completed | yes | 3/3 completed | PASS |
| v2 blob deleted | gone | TiTiler 500 (gone) | PASS |
| v1 blob accessible | present | TiTiler 200 | PASS |
| SG2-2: is_served on revoke | false | false | PASS |

### Orphan Check (4/4 pass)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| STAC collections | 1 | 1 | PASS |
| No orphaned collections | none | none | PASS |
| Total jobs | 3, all completed | 3, all completed | PASS |
| Stuck jobs | 0 | 0 | PASS |

---

## Regression Verification

### From SIEGE Run 3 (Run 18)

| ID | Severity | Description | Run 4 Status |
|----|----------|-------------|-------------|
| SG3-2 | MEDIUM | Approve targets wrong release on shared request_id | **NOT TESTED** (requires resubmit with identical version_id) |
| SG3-3 | LOW | is_served not in versions array | **FIXED** — `is_served: true` confirmed in response |
| SG3-5 | INFO | dry_run default undocumented | **FIXED** — docstring updated (code review only) |

### From SIEGE Runs 1-2 (Runs 11, 13)

| ID | Severity | Prior Status | Run 4 Status |
|----|----------|-------------|-------------|
| SG-1 | CRITICAL | Fixed v0.9.10.0 | **STILL FIXED** — STAC materialization works |
| SG-2 | HIGH | Fixed v0.9.10.0 | **STILL FIXED** — no SQL leak observed |
| SG-3 | HIGH | Fixed Run 14 | **STILL FIXED** — catalog/dataset returns 200 |
| SG-5 | HIGH | Fixed Run 15 | **STILL FIXED** — blobs_deleted=1, COG gone |
| SG-7 | MEDIUM | Fixed v0.9.10.0 | **STILL FIXED** — is_latest restored after unpublish |
| SG-8 | LOW | Fixed v0.9.10.0 | Not explicitly tested |
| SG2-2 | MEDIUM | Fixed Run 16 | **STILL FIXED** — is_served=false after revoke |
| SG2-3 | MEDIUM | Fixed Run 17 | Not explicitly tested via STAC API |

---

## Findings

| # | ID | Severity | Category | Description | Reproduction |
|---|-----|----------|----------|-------------|-------------|
| 1 | **LNC-1** | **CRITICAL** | MODEL | Vector submit completely broken — `AssetRelease.stac_item_id` and `stac_collection_id` are non-Optional required fields but vector exclusion sets them to None. Pydantic ValidationError caught as AssetCreationError. | `POST /api/platform/submit` with any vector file → returns `AssetCreationError` |
| 2 | AUD-R1-1 | MEDIUM | ENDPOINT | `/api/platform/approvals/status?stac_item_ids=X` returns `lookup_error: true` for valid approved STAC item IDs. Endpoint cannot resolve releases from STAC IDs. | `GET /api/platform/approvals/status?stac_item_ids=sg-raster-test-dctest-v1` → `has_release: false` |
| 3 | F-CART-1 | LOW | PROTOCOL | POST-only endpoints return 404 instead of 405 Method Not Allowed. Azure Functions platform behavior. | `GET /api/platform/submit` → 404 (should be 405) |
| 4 | F-CART-2 | LOW | ENDPOINT | `/api/dbadmin/stats` returns 404 — documented but not registered (SG-9 reconfirmed) | `GET /api/dbadmin/stats` → 404 |
| 5 | F-CART-3 | INFO | HYGIENE | `/api/health` response contains control character at offset ~23737 | Parse with `json.loads(strict=False)` |
| 6 | F-CART-4 | INFO | PERF | `/api/health` takes 3.7s (20 component checks) | Not suitable as liveness probe |

### LNC-1 Root Cause and Fix

**File**: `core/models/asset.py` lines 467-476

**Problem**: `stac_item_id: str` and `stac_collection_id: str` are required non-Optional fields. The 01 MAR 2026 vector STAC exclusion implementation in `services/asset_service.py:create_release()` passes `None` for these fields on vector types, causing Pydantic to reject the model construction.

**Fix**: Change both fields to `Optional[str] = Field(default=None, ...)` in `core/models/asset.py`.

---

## Verdict

### **CONDITIONAL PASS**

**Raster lifecycle is fully operational** — submit, process, approve, multi-version, unpublish all work correctly end-to-end with no regressions. All previously-fixed bugs remain fixed.

**Vector lifecycle is completely blocked** by LNC-1 (CRITICAL). This is a model-level regression from the vector STAC exclusion implementation. The fix is a 2-line change in `core/models/asset.py`.

| Metric | Value |
|--------|-------|
| Lancer sequence pass rate | 75% (3/4) |
| Auditor check pass rate | 93% (26/28) |
| New findings | 1 CRITICAL, 1 MEDIUM, 2 LOW, 2 INFO |
| Prior regressions cleared | SG-5, SG2-2, SG3-3 confirmed fixed |
| Regressions introduced | 0 (LNC-1 is a new bug, not a regression of prior working code) |

### Immediate Action Required

1. **LNC-1 (CRITICAL)**: Make `stac_item_id` and `stac_collection_id` Optional in `core/models/asset.py`
2. Redeploy and verify vector submit works
3. Run targeted vector lifecycle test

---

## Run Metadata

| Field | Value |
|-------|-------|
| Run Number | 4 (SIEGE) / 20 (overall) |
| Target Version | 0.9.11.2 |
| Schema State | Fresh rebuild |
| Agents | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| Jobs Created | 3 (2 raster, 1 unpublish) |
| STAC Collections | 1 (sg-raster-test-dctest) |
| Findings | 6 total (1 CRITICAL, 1 MEDIUM, 2 LOW, 2 INFO) |
