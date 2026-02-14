# EN-TD.1: Raw JSON Parsing Migration Plan

**Created**: 12 FEB 2026
**Completed**: 12 FEB 2026
**Status**: DONE
**Priority**: Medium (defensive hardening, not blocking)
**Scope**: 37 occurrences across 22 code files
**Estimated Effort**: 2-3 hours (mechanical refactor)

---

## Problem

35+ trigger files call `req.get_json()` directly, bypassing `BaseHttpTrigger.extract_json_body()`. These raw calls:

1. **No fallback** — Azure Functions' `req.get_json()` throws `ValueError` on valid JSON when `Content-Type` header is missing or wrong (PowerShell `Invoke-RestMethod`, proxy rewrites, some REST clients)
2. **No type guard** — accepts JSON arrays, strings, numbers — not just objects
3. **Inconsistent errors** — each file has its own error message format (or none)

**Discovery**: QA branch review (Rajesh Mameda, ITSES-GEOSPATIAL-ETL) — hit this in QA with PowerShell clients.

**Fix already applied**: `BaseHttpTrigger.extract_json_body()` in `triggers/http_base.py` is hardened with raw body fallback + `isinstance(dict)` guard. But only triggers inheriting `BaseHttpTrigger` benefit from it.

---

## Solution

### Step 1: Create standalone utility function

Add a module-level function to `triggers/http_base.py` that any trigger can import without inheriting `BaseHttpTrigger`:

```python
# triggers/http_base.py — add at module level (after imports, before classes)

def parse_request_json(req: func.HttpRequest, required: bool = True) -> Optional[Dict[str, Any]]:
    """
    Parse JSON from Azure Functions HTTP request with robust fallback.

    Handles content-type mismatches where req.get_json() fails but the
    raw body contains valid JSON (PowerShell, proxy rewrites).

    Args:
        req: Azure Functions HTTP request
        required: If True, raises ValueError when body is missing

    Returns:
        Parsed dict or None (if not required and body is empty)

    Raises:
        ValueError: If body is required but missing, not valid JSON, or not a dict
    """
    body = None

    try:
        body = req.get_json()
    except ValueError:
        raw = req.get_body() or b""
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception as parse_err:
                raise ValueError(f"Invalid JSON in request body: {parse_err}")

    if body is None and required:
        raise ValueError("Request body is required")

    if body is not None and not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")

    return body
```

### Step 2: Migrate each file

Replace `req.get_json()` with `parse_request_json(req)` (or `parse_request_json(req, required=False)` where the body is optional).

Add import: `from triggers.http_base import parse_request_json`

### Step 3: Update `BaseHttpTrigger.extract_json_body()` to delegate

```python
def extract_json_body(self, req, required=True):
    return parse_request_json(req, required=required)
```

---

## Migration Checklist

### Tier 1: Platform Endpoints (External-Facing — Highest Priority)

These are called by DDH and B2B clients with diverse HTTP tooling.

| # | File | Line(s) | Occurrences | Pattern | Notes |
|---|------|---------|-------------|---------|-------|
| 1 | `triggers/platform/submit.py` | 195 | 1 | `req_body = req.get_json()` | Feeds into `PlatformRequest(**req_body)` — Pydantic validates after parse |
| 2 | `triggers/platform/unpublish.py` | 128 | 1 | `req_body = req.get_json()` | Safety-critical (dry_run default) |
| 3 | `triggers/platform/resubmit.py` | 194 | 1 | `return req.get_json()` | Inside helper method |
| 4 | `triggers/trigger_platform_status.py` | 1371 | 1 | `req_body = req.get_json()` | Platform catalog search |

### Tier 2: Approval Endpoints (QA Workflow — High Priority)

Used by QA reviewers and iframe-embedded UI.

| # | File | Line(s) | Occurrences | Pattern | Notes |
|---|------|---------|-------------|---------|-------|
| 5 | `triggers/trigger_approvals.py` | 171, 346, 490 | 3 | `req_body = req.get_json()` | Approve, reject, revoke |
| 6 | `triggers/assets/asset_approvals_bp.py` | 107, 264, 398 | 3 | `req_body = req.get_json()` | Asset approve, reject, revoke |
| 7 | `triggers/admin/admin_approvals.py` | 237, 340, 426 | 3 | `body = req.get_json()` | Admin approval operations |

### Tier 3: Data Management Endpoints (Internal Admin — Medium Priority)

Used by admin UI and internal scripts.

| # | File | Line(s) | Occurrences | Pattern | Notes |
|---|------|---------|-------------|---------|-------|
| 8 | `triggers/stac_collections.py` | 107 | 1 | `body = req.get_json()` | STAC collection creation |
| 9 | `triggers/stac_extract.py` | 124 | 1 | `body = req.get_json()` | STAC extraction |
| 10 | `triggers/stac_vector.py` | 56 | 1 | `body = req.get_json()` | Vector STAC operations |
| 11 | `triggers/trigger_raster_renders.py` | 234, 311, 472 | 3 | `body = req.get_json()` | Render config CRUD. Line 472 uses `req.get_json() if req.get_body() else {}` — replace with `parse_request_json(req, required=False) or {}` |
| 12 | `triggers/trigger_map_states.py` | 227, 312 | 2 | `body = req.get_json()` | Map state operations |
| 13 | `triggers/promote.py` | 93, 304, 427 | 3 | `body = req.get_json()` | Data promotion |

### Tier 4: Admin/Utility Endpoints (Internal Only — Lower Priority)

Only used by platform operators.

| # | File | Line(s) | Occurrences | Pattern | Notes |
|---|------|---------|-------------|---------|-------|
| 14 | `triggers/admin/admin_data_migration.py` | 203 | 1 | `req_body = req.get_json()` | ADF trigger |
| 15 | `triggers/admin/admin_external_db.py` | 91 | 1 | `body = req.get_json()` | External DB config |
| 16 | `triggers/admin/admin_external_services.py` | 88 | 1 | `body = req.get_json()` | External service config |
| 17 | `triggers/admin/h3_datasets.py` | 202 | 1 | `body = req.get_json()` | H3 dataset operations |
| 18 | `triggers/admin/snapshot.py` | 101 | 1 | `body = req.get_json()` | Snapshot creation |
| 19 | `triggers/curated/admin.py` | 231, 293 | 2 | `body = req.get_json()` | Curated dataset admin |
| 20 | `triggers/probes.py` | 499, 593 | 2 | `body = req.get_json()` | Test/diagnostic probes |
| 21 | `triggers/jobs/resubmit.py` | 170 | 1 | `return req.get_json() or {}` | Job resubmit. Replace with `return parse_request_json(req, required=False) or {}` |

### Tier 5: Legacy/Archived (Migrate Only If Still Active)

| # | File | Line(s) | Occurrences | Pattern | Notes |
|---|------|---------|-------------|---------|-------|
| 22 | `raster_api/triggers.py` | 314 | 1 | `body = req.get_json()` | Legacy raster API — check if still registered in function_app.py |
| 23 | `raster_collection_viewer/triggers.py` | 141 | 1 | `req_body = req.get_json()` | Legacy viewer — check if still registered |

---

## Migration Pattern

### Standard replacement (required body):

**Before:**
```python
try:
    body = req.get_json()
    # ... use body ...
except ValueError:
    return func.HttpResponse(json.dumps({"error": "Invalid JSON"}), status_code=400)
```

**After:**
```python
from triggers.http_base import parse_request_json

try:
    body = parse_request_json(req)
    # ... use body ...
except ValueError as e:
    return func.HttpResponse(json.dumps({"error": str(e)}), status_code=400)
```

### Optional body replacement:

**Before:**
```python
body = req.get_json() if req.get_body() else {}
```

**After:**
```python
body = parse_request_json(req, required=False) or {}
```

### Resubmit/fallback pattern:

**Before:**
```python
return req.get_json() or {}
```

**After:**
```python
return parse_request_json(req, required=False) or {}
```

---

## Verification

After migration:

```bash
# Confirm no raw req.get_json() remains in trigger code (except http_base.py itself)
grep -rn "req\.get_json()" triggers/ --include="*.py" | grep -v http_base.py | grep -v "# raw"
```

Should return zero results.

```bash
# Also check non-trigger code files
grep -rn "req\.get_json()" raster_api/ raster_collection_viewer/ --include="*.py"
```

---

## What Does NOT Change

- `BaseHttpTrigger.extract_json_body()` — already hardened, will delegate to `parse_request_json()`
- Pydantic model validation — still happens after JSON parsing (e.g., `PlatformRequest(**body)`)
- Error response format — each trigger keeps its own response structure
- Business logic — zero changes to what happens after the JSON is parsed

---

## Risks

- **Low risk**: This is a mechanical find-and-replace. The new function has identical happy-path behavior (`req.get_json()` succeeds → same dict returned).
- **Edge case surfaced**: Triggers that accept non-dict JSON (e.g., a raw array) would start failing with `"Request body must be a JSON object"`. Review each occurrence for this. None are expected based on current API contracts.

---

*End of Migration Plan*
