# SIEGE Report — Run 5

**Date**: 01 MAR 2026
**Target**: https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
**Version**: 0.9.11.3
**Pipeline**: SIEGE (Run 21 overall)
**Schema**: Fresh rebuild before run

---

## Endpoint Health

| # | Endpoint | HTTP | Latency | Notes |
|---|----------|------|---------|-------|
| 1 | `/api/platform/health` | 200 | 840ms | All subsystems healthy |
| 2 | `/api/platform/status` | 200 | 655ms | List mode works |
| 3 | `/api/platform/status/{bogus}` | 404 | 1029ms | Proper error shape |
| 4 | `/api/platform/approvals` | 200 | 639ms | Paginated |
| 5 | `/api/platform/catalog/lookup` | 400 | 154ms | Correct validation |
| 6 | `/api/platform/failures` | 200 | 585ms | 0 failures |
| 7 | `/api/platform/lineage/{bogus}` | 404 | 474ms | Structured error |
| 8 | `/api/platforms` | 200 | 434ms | 1 platform (ddh) |
| 9 | `/api/health` | 200 | 3849ms | Deep check, slow |
| 10 | `/api/dbadmin/jobs?limit=1` | 200 | 361ms | Works |

**Assessment: HEALTHY** — Zero 5xx errors, all endpoints responsive.

---

## Workflow Results

| Sequence | Steps | Pass | Fail | Verdict |
|----------|-------|------|------|---------|
| 1. Raster Lifecycle | 4 | 4 | 0 | **PASS** |
| 2. Vector Lifecycle | 4 | 4 | 0 | **PASS** (LNC-1 FIXED) |
| 3. Multi-Version Raster | 4 | 4 | 0 | **PASS** |
| 4. Unpublish | 3 | 3 | 0 | **PASS** |
| 5. NetCDF/VirtualiZarr | 4 | 1 | 3 | **FAIL** |
| **Total** | **19** | **16** | **3** | |

**Lancer pass rate: 84% (16/19)** — 4/5 sequences passed.

---

## Key Milestone: LNC-1 FIXED

The CRITICAL bug from Run 4 — vector submit returning `AssetCreationError` due to non-Optional `stac_item_id`/`stac_collection_id` fields — is **confirmed fixed** in v0.9.11.3. The full vector lifecycle (submit → process → approve) completed successfully. Vector correctly excluded from STAC (no collection or item created, `stac_item_id=null` in status response).

---

## State Audit

### Checkpoint R1 — Raster v1 (PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| approval_state | approved | approved | PASS |
| is_latest | true (restored) | true | PASS |
| is_served | true | true | PASS |
| Catalog count | 1 | 1 | PASS |
| stac_item_id | sg-raster-test-dctest-v1 | sg-raster-test-dctest-v1 | PASS |

### Checkpoint V1 — Vector v1 (PASS — LNC-1 fix verified)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| processing_status | completed | completed | PASS |
| approval_state | approved | approved | PASS |
| stac_item_id | null | null | PASS |
| STAC collection | absent | absent | PASS |
| table_name | sg_vector_test_cutlines_v1 | present | PASS |

### Checkpoint MV1 — Multi-Version (PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| v1 is_latest | false (pre-unpublish) | Restored to true (post-unpublish) | PASS |
| v2 is_latest | true (pre-unpublish) | false (post-unpublish) | PASS |
| v2 version_ordinal | 2 | 2 | PASS |
| Output folder isolation | ord1 vs ord2 | Confirmed | PASS |

### Checkpoint U1 — Unpublish v2 (PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| v2 approval_state | revoked | revoked | PASS |
| v2 is_served | false | false | PASS |
| v1 is_latest | true (restored) | true | PASS |
| Catalog count | 1 | 1 | PASS |
| Failures | 0 | 0 | PASS |

### Checkpoint Z1 — VirtualiZarr (FAIL — SG5-1 CRITICAL)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| job_type | virtualzarr | virtualzarr | PASS |
| processing_status | completed | **failed** | FAIL |
| Error | — | Container 'silver-netcdf' does not exist | INFRA GAP |
| approval_state | should be blocked | **approved** | **FAIL (SG5-1)** |
| is_served | should be false | **true** | **FAIL (SG5-1)** |

### Orphan Check (PASS)

| Check | Expected | Actual | Verdict |
|-------|----------|--------|---------|
| STAC collections | 1 (raster) | 1 | PASS |
| No orphaned collections | none | none | PASS |
| Total jobs | 5 (2 raster, 1 vector, 1 unpublish, 1 zarr) | 5 | PASS |
| Stuck jobs | 0 | 0 | PASS |

---

## Regression Verification

### LNC-1 (from Run 4)

| Item | Status |
|------|--------|
| Vector submit | **FIXED** — returns HTTP 202 |
| Vector processing | **WORKS** — completes successfully |
| Vector approval | **WORKS** — approved, stac_item_id=null |
| Vector STAC exclusion | **WORKS** — no collection/item created |

### Prior SIEGE Bugs

| ID | Severity | Run 5 Status |
|----|----------|-------------|
| SG-1 | CRITICAL | Still fixed — STAC materialization works |
| SG-5 | HIGH | Still fixed — blobs_deleted=1 |
| SG2-2 | MEDIUM | Still fixed — is_served=false after revoke |
| SG3-3 | LOW | Still fixed — is_served in versions array |

---

## Findings

| # | ID | Severity | Category | Description |
|---|-----|----------|----------|-------------|
| 1 | **SG5-1** | **CRITICAL** | APPROVAL | Approval endpoint approved a release with `processing_status=failed`. The approval service logs a warning but does not block. Phantom STAC entry created — `is_served=true` for data that was never produced. |
| 2 | SG5-2 | MEDIUM | LIFECYCLE | Orphaned release created on validation failure — first zarr submit failed (missing `source_url` param) but left a release record, requiring `overwrite=true` on retry. |
| 3 | SG5-3 | LOW | INFRA | `silver-netcdf` storage container does not exist. VirtualiZarr pipeline fails at Stage 1 (scan). Infrastructure provisioning gap. |

### SG5-1 Root Cause

**File**: `services/asset_approval_service.py` lines 154-159

The approval service warns but does NOT block when `processing_status != COMPLETED`:
```python
if release.processing_status != ProcessingStatus.COMPLETED:
    logger.warning(...)  # Warning only — continues to approve!
```

**Fix**: Change from warning to hard rejection:
```python
if release.processing_status != ProcessingStatus.COMPLETED:
    raise BusinessLogicError(
        f"Cannot approve release with processing_status='{release.processing_status}'. "
        f"Only completed releases can be approved."
    )
```

### SG5-3 Infrastructure Fix

Provision the `silver-netcdf` container:
```bash
az storage container create --name silver-netcdf --account-name rmhstorage123 --auth-mode login
```

---

## Verdict

### **CONDITIONAL PASS**

**4/5 lifecycle sequences passed.** The core platform workflows (raster, vector, multi-version, unpublish) are all fully operational. This is the first SIEGE run where **all four original sequences passed**, including the first-ever successful vector lifecycle test (LNC-1 fix confirmed).

The NetCDF/VirtualiZarr sequence failed due to a missing storage container (infrastructure gap) and exposed a CRITICAL approval guard bug (SG5-1).

| Metric | Value |
|--------|-------|
| Lancer sequence pass rate | 80% (4/5) |
| Lancer step pass rate | 84% (16/19) |
| Auditor check pass rate | 89% (24/27) |
| New findings | 1 CRITICAL, 1 MEDIUM, 1 LOW |
| LNC-1 regression | **FIXED** |
| Prior regressions | 0 (all prior fixes hold) |

### Immediate Actions

1. **SG5-1 (CRITICAL)**: Add processing_status guard to approval service
2. **SG5-3 (LOW)**: Provision `silver-netcdf` container
3. Redeploy + rerun NetCDF sequence to verify VirtualiZarr pipeline

---

## Run Metadata

| Field | Value |
|-------|-------|
| Run Number | 5 (SIEGE) / 21 (overall) |
| Target Version | 0.9.11.3 |
| Schema State | Fresh rebuild |
| Agents | Sentinel → Cartographer → Lancer → Auditor → Scribe |
| Jobs Created | 5 (2 raster, 1 vector, 1 unpublish, 1 zarr) |
| STAC Collections | 1 (sg-raster-test-dctest) |
| Findings | 3 total (1 CRITICAL, 1 MEDIUM, 1 LOW) |
