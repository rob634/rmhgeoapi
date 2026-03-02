# SIEGE RUN 5 AUDIT REPORT
**Timestamp**: 01 MAR 2026 23:38:00 UTC
**Auditor**: Claude Code (Checkpoint Verification)
**Environment**: Production (rmhazuregeoapi + rmhheavyapi)

---

## CHECKPOINT RESULTS

### Checkpoint R1 (Raster v1) ✅ PASS
**Test Asset**: sg-raster-test (dctest) v1

**Verification Results**:
```
1. GET /api/platform/status/4e7b43a80c63969342b44a27176e29d0
   ✅ approval_state = approved
   ✅ is_latest = true (restored after unpublish of v2)
   ✅ processing_status = completed
   
2. GET /api/platform/catalog/dataset/sg-raster-test
   ✅ count = 1 (only v1 served after v2 unpublished)
   ✅ Only v1 item in results
   
3. Version Array Check
   ✅ v1: is_served=true, approval_state=approved, is_latest=true
   ✅ v2: is_served=false, approval_state=revoked, is_latest=false
```

**Result**: All R1 checks passed. No issues detected.

---

### Checkpoint V1 (Vector v1) ✅ PASS
**Test Asset**: sg-vector-test (cutlines) v1

**Verification Results**:
```
1. GET /api/platform/status/b229634318871f349a7fcb2e57c75a50
   ✅ processing_status = completed
   ✅ approval_state = approved
   ✅ data_type = vector
   
2. STAC Exclusion Check
   ✅ stac_item_id = null (vector NOT in STAC)
   ✅ stac_collection_id = null
   ✅ outputs contain only table_names, no blob_path
   
3. GET /api/stac/collections
   ✅ NO sg-vector-test collection found
   ✅ Only 2 STAC collections: sg-netcdf-test, sg-raster-test-dctest
   ✅ Confirmed vector exclusion working (LNC-1 fix validated)
```

**Result**: All V1 checks passed. Vector STAC exclusion is working correctly.

---

### Checkpoint U1 (Unpublish v2) ✅ PASS
**Test Asset**: sg-raster-test v2 (revoked)

**Verification Results**:
```
1. GET /api/platform/status/6ee458b389353065bfd4098ecb964988
   ✅ approval_state = revoked
   ✅ is_served = false
   ✅ is_latest = false (correctly reverted to v1)
   ✅ processing_status = completed
   
2. GET /api/platform/failures
   ✅ Only 1 failure in 24-hour window (expected: the Z1 zarr failure)
   ✅ No unexpected failures in unpublish flow
```

**Result**: All U1 checks passed. Unpublish correctly revoked v2 and restored v1 as latest.

---

### Checkpoint Z1 (VirtualiZarr) ⚠️ CRITICAL ISSUE DETECTED
**Test Asset**: sg-netcdf-test (spei-ssp370) v1

**Verification Results**:
```
1. GET /api/platform/status/57a042b71ed6885e2f78a687ba20a39a
   ✅ processing_status = failed (correct)
   ❌ approval_state = approved (SHOULD BE null/pending)
   ❌ is_served = true (SHOULD BE false)
   ✅ job_status = failed
   
2. Error Details
   Error: "Container 'silver-netcdf' does not exist in storage account 'rmhstorage123'"
   Stage: 1/5 (scan stage failed)
   Task: 5d68ac44-s1-scan exceeded max retries (3)
   
3. GET /api/dbadmin/jobs
   ✅ Job found with correct error details
   ✅ Task status: 1 failed, 0 completed
   ✅ Job correctly marked as failed
```

**Result**: CRITICAL FINDING SG5-1 CONFIRMED
- Processing FAILED at scan stage
- But is_served=true and approval_state=approved
- This violates platform invariant: failed pipelines should NOT be served

---

### Orphan Check ✅ PASS
**STAC Catalog State**:
```
Collections Found: 2
  1. sg-netcdf-test
     - total_items: 0 (no approved zarr items)
     - created: 2026-03-01T23:36:06
     
  2. sg-raster-test-dctest
     - total_items: 1 (v1 approved)
     - created: 2026-03-01T23:25:05

Job Summary:
  - Total jobs in 24h: 5
  - Failed jobs: 1 (Z1 virtualzarr)
  - Stuck jobs: 0
  - No orphaned/incomplete assets detected
```

**Result**: No orphans. Z1 failure is tracked and visible. However, the approval_state bug allows it to appear "served" despite failure.

---

## SUMMARY

| Checkpoint | Status | Finding |
|-----------|--------|---------|
| **R1** | ✅ PASS | Raster v1 restoration working correctly |
| **V1** | ✅ PASS | Vector STAC exclusion (LNC-1) working correctly |
| **U1** | ✅ PASS | Unpublish revocation and restore working correctly |
| **Z1** | ⚠️ FAIL | **SG5-1 CRITICAL**: Failed zarr approved with is_served=true |
| **Orphan Check** | ✅ PASS | No orphaned assets; failure tracking intact |

---

## CRITICAL ISSUE: SG5-1 - Approval Allows Failed Processing

**Issue**: VirtualiZarr pipeline failed at scan stage, but:
- `approval_state` = `approved` (SHOULD BE null or pending)
- `is_served` = `true` (SHOULD BE false)
- `processing_status` = `failed` (confirmed in job logs)

**Impact**: System shows failed pipeline as "served" to consumers, violating data integrity guarantees. Downstream consumers may attempt to use non-existent zarr stores.

**Root Cause**: CONFIRMED IN CODE
File: `/services/asset_approval_service.py` lines 154-159

```python
# Warn if processing is not complete (don't block)
if release.processing_status != ProcessingStatus.COMPLETED:
    logger.warning(
        f"Approving release with processing_status={release.processing_status.value} "
        f"(expected COMPLETED) - proceeding anyway"
    )
```

The approval flow **warns but does NOT block** if `processing_status != COMPLETED`. This is a design flaw that allows failed pipelines to be approved.

**Verification**: Confirmed in audit response showing release with:
- `processing_status` = `failed` (job failed at scan stage)
- `approval_state` = `approved` (approval succeeded despite failure)
- `is_served` = `true` (marked as served)
- Error: "Container 'silver-netcdf' does not exist in storage account"

**Remediation Required**:

1. **CRITICAL FIX**: Change line 155 in `/services/asset_approval_service.py` from warn-only to BLOCK
   ```python
   # WRONG (current code):
   if release.processing_status != ProcessingStatus.COMPLETED:
       logger.warning(...)  # Warning only, continues

   # CORRECT (should be):
   if release.processing_status != ProcessingStatus.COMPLETED:
       return {
           'success': False,
           'error': f"Cannot approve: processing_status is '{release.processing_status.value}', expected 'completed'",
           'error_type': 'ApprovalFailed',
           'remediation': 'Wait for processing to complete before approving'
       }
   ```

2. **IMMEDIATE ACTION**: Revoke the failed release
   ```bash
   curl -X POST "https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/platform/approvals/{release_id}/revoke" \
     -H "Content-Type: application/json" \
     -d '{"revoker": "auditor", "reason": "EMERGENCY: Failed processing approved due to SG5-1 bug"}'
   ```

3. **Deploy Fix**: Update approval service with blocking check, test in dev, deploy to production v0.9.11.4+

4. **Audit Trail**: Record this finding in ERRORS_AND_FIXES.md as APP-001

---

## LANCER CHECKPOINT VALIDATIONS COMPLETE
**Status**: 4/5 checkpoints passed. 1 critical issue in Z1.
**Root Cause**: Design flaw in approval service (lines 154-159 of asset_approval_service.py).
**Action Required**: Code fix + immediate revocation of SG5-1 release.
**Timestamp**: 01 MAR 2026 23:38:01 UTC
