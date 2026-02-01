# Platform Submit dry_run Implementation

**Created**: 31 JAN 2026
**Status**: PHASE 1-4 COMPLETE - Ready for testing
**Priority**: CRITICAL
**Related**: V0.8 Release Control, Version Advance Validation

---

## Executive Summary

Add `dry_run` parameter to `/api/platform/submit` for pre-flight validation without job creation. Also add `previous_version_id` validation to prevent version race conditions.

---

## Current State Analysis

### Endpoints with dry_run (Already Implemented)

| Endpoint | dry_run | Notes |
|----------|---------|-------|
| `POST /api/platform/resubmit` | ✅ Yes | Returns cleanup preview |
| `POST /api/platform/unpublish` | ✅ Yes | Defaults to true (safety) |
| `POST /api/platform/submit` | ❌ No | **Needs implementation** |

### Existing Validate Endpoint

`POST /api/platform/validate` exists in `triggers/platform/platform_bp.py` with handler `platform_validate()`.

**Current behavior**: Needs review - may already provide lineage state info.

---

## Requirements

### R1: dry_run Parameter for Submit

```bash
# Validate without submitting
POST /api/platform/submit?dry_run=true

# Actually submit
POST /api/platform/submit
```

### R2: previous_version_id Validation

| `previous_version_id` | Lineage State | Result |
|-----------------------|---------------|--------|
| `null` | Empty (no versions) | ✅ OK - First version |
| `null` | Has versions (latest=v2.0) | ❌ REJECT - "v2.0 exists, specify as previous" |
| `v2.0` | Empty | ❌ REJECT - "v2.0 doesn't exist" |
| `v2.0` | Latest is v2.0 | ✅ OK - Proceed |
| `v2.0` | Latest is v3.0 | ❌ REJECT - "v2.0 is not latest" |

### R3: Consistent Response Structure

**dry_run=true Response (200 OK):**
```json
{
  "valid": true,
  "dry_run": true,
  "request_id": "abc123...",
  "would_create_job_type": "vector_docker_etl",
  "lineage_state": {
    "lineage_id": "def456...",
    "lineage_exists": true,
    "current_latest": {
      "version_id": "v2.0",
      "version_ordinal": 2
    }
  },
  "validation": {
    "data_type_detected": "vector",
    "file_exists": true,
    "previous_version_valid": true
  },
  "warnings": [],
  "suggested_params": {
    "previous_version_id": "v2.0"
  }
}
```

**dry_run=true with Validation Failure (200 OK with valid=false):**
```json
{
  "valid": false,
  "dry_run": true,
  "request_id": "abc123...",
  "lineage_state": {...},
  "validation": {
    "data_type_detected": "vector",
    "file_exists": true,
    "previous_version_valid": false
  },
  "warnings": [
    "Version v2.0 exists. Specify previous_version_id='v2.0' to submit new version."
  ],
  "suggested_params": {
    "previous_version_id": "v2.0"
  }
}
```

**Actual Submit with Validation Failure (400 Bad Request):**
```json
{
  "success": false,
  "error": "Version v2.0 exists. Specify previous_version_id='v2.0' to submit new version.",
  "error_type": "ValidationError"
}
```

---

## Implementation Plan

### Phase 1: Model Update

**File**: `core/models/platform.py`

Add `previous_version_id` to PlatformRequest:

```python
class PlatformRequest(BaseModel):
    # ... existing fields ...

    # V0.8.4 Release Control - Version validation
    previous_version_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Required for subsequent versions. Must match current latest version_id."
    )
```

**Effort**: ~5 lines

---

### Phase 2: Validation Helper

**File**: `services/platform_validation.py` (NEW)

Create centralized validation logic used by both dry_run and actual submit:

```python
def validate_version_lineage(
    platform_id: str,
    platform_refs: Dict[str, Any],
    previous_version_id: Optional[str],
    asset_service: AssetService
) -> Dict[str, Any]:
    """
    Validate version lineage for submit.

    Returns:
        {
            'valid': bool,
            'lineage_state': {...},
            'warnings': [...],
            'suggested_params': {...}
        }
    """
    nominal_refs = ["dataset_id", "resource_id"]
    lineage_state = asset_service.get_lineage_state(
        platform_id=platform_id,
        platform_refs=platform_refs,
        nominal_refs=nominal_refs
    )

    current_latest = lineage_state.get('current_latest')
    warnings = []
    valid = True

    if previous_version_id is None:
        # First version - lineage must be empty
        if current_latest:
            valid = False
            warnings.append(
                f"Version {current_latest['version_id']} exists. "
                f"Specify previous_version_id='{current_latest['version_id']}' to submit new version."
            )
    else:
        # Subsequent version - must match current latest
        if not current_latest:
            valid = False
            warnings.append(
                f"previous_version_id '{previous_version_id}' specified but no versions exist. "
                f"Omit previous_version_id for first version."
            )
        elif current_latest['version_id'] != previous_version_id:
            valid = False
            warnings.append(
                f"previous_version_id '{previous_version_id}' is not current latest. "
                f"Current latest is '{current_latest['version_id']}'."
            )

    return {
        'valid': valid,
        'lineage_state': lineage_state,
        'warnings': warnings,
        'suggested_params': {
            'previous_version_id': current_latest['version_id'] if current_latest else None
        }
    }
```

**Effort**: ~60 lines

---

### Phase 3: Update Submit Endpoint

**File**: `triggers/platform/submit.py`

Modify `platform_request_submit()`:

```python
async def platform_request_submit(req: func.HttpRequest) -> func.HttpResponse:
    # ... existing setup ...

    # Check dry_run parameter
    dry_run = req.params.get('dry_run', '').lower() == 'true'

    # ... existing validation (Pydantic, data type detection) ...

    # V0.8.4 Version lineage validation
    validation_result = validate_version_lineage(
        platform_id="ddh",
        platform_refs=platform_refs,
        previous_version_id=platform_req.previous_version_id,
        asset_service=asset_service
    )

    if dry_run:
        # Return validation result without creating job
        return func.HttpResponse(
            json.dumps({
                "valid": validation_result['valid'],
                "dry_run": True,
                "request_id": request_id,
                "would_create_job_type": job_type,
                "lineage_state": validation_result['lineage_state'],
                "validation": {
                    "data_type_detected": data_type,
                    "file_exists": True,  # From pre-flight
                    "previous_version_valid": validation_result['valid']
                },
                "warnings": validation_result['warnings'],
                "suggested_params": validation_result['suggested_params']
            }),
            status_code=200,
            mimetype="application/json"
        )

    # Not dry_run - enforce validation
    if not validation_result['valid']:
        return platform_error_response(
            validation_result['warnings'][0],
            "ValidationError",
            status_code=400
        )

    # ... continue with job creation ...
```

**Effort**: ~40 lines modification

---

### Phase 4: Update/Consolidate Validate Endpoint ✅ COMPLETE (31 JAN 2026)

**File**: `triggers/trigger_platform_status.py`

**Implementation**: Rewrote `platform_validate()` to use the same validation logic as `submit?dry_run=true`:

- Now accepts full `PlatformRequest` body (same as submit)
- Calls `validate_version_lineage()` for lineage validation
- Returns identical response structure to `?dry_run=true`
- Both workflows are now consistent:
  - Workflow A: `/validate` → `/submit` (if valid)
  - Workflow B: `/submit?dry_run=true` → `/submit` (if valid)

**DRY Exemption**: Both endpoints call the same underlying validation but serve different workflows.

**Effort**: ~100 lines rewritten

---

### Phase 5: Update Tests

**File**: `V0.8_TESTING.md`

Add dry_run tests:

| ID | Test | Request | Expected |
|----|------|---------|----------|
| DRY-01 | dry_run first version | `?dry_run=true`, no previous | `valid=true` |
| DRY-02 | dry_run missing previous | `?dry_run=true`, lineage exists | `valid=false`, warning |
| DRY-03 | dry_run correct previous | `?dry_run=true`, previous matches | `valid=true` |
| DRY-04 | dry_run wrong previous | `?dry_run=true`, previous mismatch | `valid=false`, warning |
| DRY-05 | Submit without dry_run, valid | Full submit | Job created |
| DRY-06 | Submit without dry_run, invalid | Missing previous | 400 error |

**Effort**: ~50 lines documentation

---

## Files to Modify

| File | Change | Priority |
|------|--------|----------|
| `core/models/platform.py` | Add `previous_version_id` field | P1 |
| `services/platform_validation.py` | NEW - Validation helper | P1 |
| `services/__init__.py` | Export new module | P1 |
| `triggers/platform/submit.py` | Add dry_run logic + validation | P1 |
| `triggers/platform/platform_bp.py` | Review/update validate endpoint | P2 |
| `V0.8_TESTING.md` | Add dry_run tests | P2 |
| `docs_claude/TODO.md` | Track progress | P1 |

---

## Job Type Coverage

| Job Type | dry_run Impact | Notes |
|----------|----------------|-------|
| `vector_docker_etl` | ✅ Covered | Same validation |
| `process_vector` | ✅ Covered | Same validation |
| `process_raster_docker` | ✅ Covered | Same validation |
| `process_raster_v2` | ✅ Covered | Same validation |
| `process_raster_collection_docker` | ✅ Covered | Same validation |

All job types go through the same submit endpoint and validation logic.

---

## Migration Notes

### For B2B Apps (DDH)

**Before (current):**
```bash
curl -X POST /api/platform/submit -d '{"dataset_id": "X", "version_id": "v2.0", ...}'
# May fail if v1.0 exists
```

**After (recommended workflow):**
```bash
# Step 1: Validate
curl -X POST "/api/platform/submit?dry_run=true" -d '{"dataset_id": "X", "version_id": "v2.0", ...}'
# Response: {"valid": false, "warnings": ["Specify previous_version_id='v1.0'"]}

# Step 2: Submit with previous_version_id
curl -X POST /api/platform/submit -d '{"dataset_id": "X", "version_id": "v2.0", "previous_version_id": "v1.0", ...}'
# Response: {"success": true, "job_id": "..."}
```

### Backward Compatibility

- `previous_version_id` is optional for first version
- Existing workflows continue to work if lineage is empty
- New validation only triggers when lineage exists

---

## Success Criteria

- [x] `previous_version_id` field added to PlatformRequest model (31 JAN 2026)
- [x] `validate_version_lineage()` helper implemented (31 JAN 2026)
- [x] `?dry_run=true` returns validation result without job creation (31 JAN 2026)
- [x] Missing/wrong `previous_version_id` returns 400 on actual submit (31 JAN 2026)
- [ ] All 6 dry_run tests passing
- [ ] Documentation updated

---

## References

- `V0.8_RELEASE_CONTROL.md` - Version lineage design
- `V0.8_TESTING.md` - Test plan (Part 4: Release Control)
- `triggers/platform/submit.py` - Current submit implementation
- `services/asset_service.py` - `get_lineage_state()` method
