# Refactor: trigger_platform.py Split

**Created**: 27 JAN 2026
**Status**: PLANNED
**Priority**: MEDIUM - Code legibility / maintainability
**Epic**: E12 (Interface Modernization) or E7 (Pipeline Infrastructure)

---

## Problem Statement

`triggers/trigger_platform.py` has grown to **2,414 lines (~25k tokens)** and violates single-responsibility principle:

| Issue | Impact |
|-------|--------|
| **Size** | Difficult to navigate, slow IDE indexing, context window limits |
| **Mixed concerns** | HTTP handlers + translation logic + job submission + unpublish workflows |
| **Deprecated code** | ~375 lines of deprecated endpoints still present |
| **Duplication** | Nearly identical response-building patterns repeated 8+ times |
| **Testing difficulty** | Hard to unit test translation logic when coupled to HTTP handlers |

---

## Current Structure Analysis

| Section | Lines | Responsibility |
|---------|-------|----------------|
| Header & Imports | 1-71 | Module setup |
| URL Generation | 73-92 | `_generate_job_status_url()` |
| Overwrite Helper | 94-195 | `_handle_overwrite_unpublish()`, `_delete_platform_request()` |
| **Submit Handlers** | 197-683 | `platform_request_submit()`, `platform_raster_submit()`, `platform_raster_collection_submit()` |
| **Unpublish Deprecated** | 686-1061 | `platform_unpublish_vector()`, `platform_unpublish_raster()` |
| **Unpublish Consolidated** | 1064-1527 | `platform_unpublish()` + execution helpers |
| Unpublish Resolution | 1529-1823 | `_resolve_*_params()`, `_handle_collection_unpublish()` |
| **Translation Logic** | 1826-2241 | `_translate_to_coremachine()`, `_translate_single_raster()`, `_translate_raster_collection()` |
| **Job Submission** | 2244-2414 | `_create_and_submit_job()` with fallback logic |

---

## Proposed Architecture

### Target File Structure

```
triggers/
├── trigger_platform.py          # Main entry (thin, imports from submodules)
├── platform/
│   ├── __init__.py              # Re-exports for backward compatibility
│   ├── submit.py                # Submit endpoints (platform_request_submit, etc.)
│   ├── unpublish.py             # Consolidated unpublish endpoint + helpers
│   └── deprecated.py            # DEPRECATED endpoints (or DELETE entirely)
│
services/
├── platform_translation.py      # DDH → CoreMachine translation (business logic)
├── platform_job_submit.py       # Job creation + Service Bus submission
```

### Responsibility Mapping

| New Module | Contents | Lines (est.) |
|------------|----------|--------------|
| `triggers/platform/submit.py` | `platform_request_submit()`, `platform_raster_submit()`, `platform_raster_collection_submit()` | ~350 |
| `triggers/platform/unpublish.py` | `platform_unpublish()`, `_execute_*_unpublish()`, `_resolve_unpublish_data_type()`, `_handle_collection_unpublish()` | ~500 |
| `triggers/platform/deprecated.py` | `platform_unpublish_vector()`, `platform_unpublish_raster()` | ~375 (or DELETE) |
| `services/platform_translation.py` | `_translate_to_coremachine()`, `_translate_single_raster()`, `_translate_raster_collection()`, `_generate_table_name()`, `_generate_stac_item_id()` | ~450 |
| `services/platform_job_submit.py` | `_create_and_submit_job()`, `RASTER_JOB_FALLBACKS`, `_generate_unpublish_request_id()` | ~200 |
| `triggers/trigger_platform.py` | Imports + re-exports for Azure Functions registration | ~50 |

---

## Implementation Plan

### Phase 0: Decision - Delete Deprecated Code?

**Question**: The deprecated endpoints (`platform_unpublish_vector`, `platform_unpublish_raster`) have been superseded by `platform_unpublish` since 21 JAN 2026.

| Option | Pros | Cons |
|--------|------|------|
| **A: Delete immediately** | -375 lines, cleaner codebase | Breaking if any client still uses them |
| **B: Move to deprecated.py** | Preserves backward compatibility | Maintains dead code |
| **C: Delete with deprecation warning period** | Best practice | Requires tracking |

**Recommendation**: Option A (Delete) - these are internal endpoints, not used by DDH.

---

### Phase 1: Extract Translation Logic (No Breaking Changes)

**Goal**: Move pure business logic to `services/` where it can be unit tested.

**Files Created**:
- `services/platform_translation.py`
- `services/platform_job_submit.py`

**Steps**:

1. **Create `services/platform_translation.py`**
   ```python
   # Move from trigger_platform.py:
   # - _translate_to_coremachine()
   # - _translate_single_raster()
   # - _translate_raster_collection()
   # - _generate_table_name()
   # - _generate_stac_item_id()
   # - _normalize_data_type()
   # - _get_unpublish_params_from_request()
   ```

2. **Create `services/platform_job_submit.py`**
   ```python
   # Move from trigger_platform.py:
   # - RASTER_JOB_FALLBACKS
   # - _create_and_submit_job()
   # - _generate_unpublish_request_id()
   ```

3. **Update imports in `trigger_platform.py`**
   ```python
   from services.platform_translation import (
       translate_to_coremachine,
       translate_single_raster,
       translate_raster_collection,
   )
   from services.platform_job_submit import create_and_submit_job
   ```

4. **Update `services/__init__.py`** to export new modules

**Validation**:
- Run existing tests
- Deploy to dev, test submit endpoints
- No functional change expected

---

### Phase 2: Split HTTP Handlers

**Goal**: Separate submit and unpublish concerns into focused modules.

**Files Created**:
- `triggers/platform/__init__.py`
- `triggers/platform/submit.py`
- `triggers/platform/unpublish.py`

**Steps**:

1. **Create `triggers/platform/` directory**

2. **Create `triggers/platform/submit.py`**
   ```python
   # Move from trigger_platform.py:
   # - platform_request_submit()
   # - platform_raster_submit()
   # - platform_raster_collection_submit()
   # - _handle_overwrite_unpublish()
   # - _delete_platform_request()
   # - _generate_job_status_url()
   ```

3. **Create `triggers/platform/unpublish.py`**
   ```python
   # Move from trigger_platform.py:
   # - platform_unpublish()
   # - _resolve_unpublish_data_type()
   # - _execute_vector_unpublish()
   # - _execute_raster_unpublish()
   # - _resolve_vector_unpublish_params()
   # - _resolve_raster_unpublish_params()
   # - _handle_collection_unpublish()
   ```

4. **Create `triggers/platform/__init__.py`**
   ```python
   """Platform triggers - Anti-Corruption Layer for DDH integration."""
   from .submit import (
       platform_request_submit,
       platform_raster_submit,
       platform_raster_collection_submit,
   )
   from .unpublish import platform_unpublish

   # Deprecated - remove in next version
   # from .deprecated import platform_unpublish_vector, platform_unpublish_raster

   __all__ = [
       'platform_request_submit',
       'platform_raster_submit',
       'platform_raster_collection_submit',
       'platform_unpublish',
   ]
   ```

5. **Update `triggers/trigger_platform.py`** (thin wrapper)
   ```python
   """
   Platform Request HTTP Trigger - Re-exports for Azure Functions.

   This module re-exports handlers from triggers/platform/ submodules
   for Azure Functions registration. Do not add logic here.
   """
   from triggers.platform import (
       platform_request_submit,
       platform_raster_submit,
       platform_raster_collection_submit,
       platform_unpublish,
   )

   __all__ = [
       'platform_request_submit',
       'platform_raster_submit',
       'platform_raster_collection_submit',
       'platform_unpublish',
   ]
   ```

6. **Update `function_app.py`** blueprint registration (if needed)

**Validation**:
- All endpoints respond correctly
- Health check passes
- Submit job, verify processing

---

### Phase 3: Delete Deprecated Code

**Goal**: Remove deprecated endpoints that have been superseded.

**Steps**:

1. **Verify no usage** of deprecated endpoints:
   - Search logs for `/api/platform/unpublish/vector` calls
   - Search logs for `/api/platform/unpublish/raster` calls
   - Confirm DDH uses consolidated `/api/platform/unpublish`

2. **Delete deprecated functions**:
   - `platform_unpublish_vector()`
   - `platform_unpublish_raster()`

3. **Remove from blueprint registration** in `function_app.py`

4. **Update API documentation** (OpenAPI spec)

---

### Phase 4: Response Builder Pattern (Optional)

**Goal**: Reduce duplication in HTTP response construction.

**Current Pattern** (repeated 8+ times):
```python
return func.HttpResponse(
    json.dumps({
        "success": True,
        "request_id": request_id,
        "job_id": job_id,
        # ... many fields
    }),
    status_code=202,
    headers={"Content-Type": "application/json"}
)
```

**Proposed Pattern**:
```python
# services/platform_response.py
def success_response(data: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"success": True, **data}),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )

def error_response(error: str, error_type: str, status_code: int = 400) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"success": False, "error": error, "error_type": error_type}),
        status_code=status_code,
        headers={"Content-Type": "application/json"}
    )
```

---

## File Dependency Graph (Post-Refactor)

```
function_app.py
    └── triggers/trigger_platform.py (re-exports)
            └── triggers/platform/__init__.py
                    ├── triggers/platform/submit.py
                    │       ├── services/platform_translation.py
                    │       └── services/platform_job_submit.py
                    │
                    └── triggers/platform/unpublish.py
                            ├── services/platform_translation.py
                            └── services/platform_job_submit.py
```

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Import path changes break Azure Functions | Keep `trigger_platform.py` as re-export facade |
| Circular imports | Translation/submission logic in `services/` has no trigger dependencies |
| Missing function during migration | Run full test suite after each phase |
| Blueprint registration breaks | Test locally with `func start` before deploy |

---

## Success Criteria

| Metric | Before | After |
|--------|--------|-------|
| `trigger_platform.py` lines | 2,414 | ~50 (re-exports only) |
| Files with platform logic | 1 | 5 (focused modules) |
| Unit testable translation logic | No | Yes |
| Deprecated code | 375 lines | 0 |

---

## Estimated Effort

| Phase | Effort | Risk |
|-------|--------|------|
| Phase 0: Decision | 5 min | None |
| Phase 1: Extract services | 2-3 hours | Low |
| Phase 2: Split handlers | 2-3 hours | Medium |
| Phase 3: Delete deprecated | 30 min | Low |
| Phase 4: Response pattern | 1 hour | Low |
| **Total** | **6-7 hours** | **Medium** |

---

## Related Documents

- [ARCHITECTURE_REFERENCE.md](./ARCHITECTURE_REFERENCE.md) - Trigger layer patterns
- [DEV_BEST_PRACTICES.md](./DEV_BEST_PRACTICES.md) - Import patterns, module organization
- [JOB_CREATION_QUICKSTART.md](./JOB_CREATION_QUICKSTART.md) - Job/handler relationship

---

## Changelog

| Date | Change |
|------|--------|
| 27 JAN 2026 | Initial plan created |
