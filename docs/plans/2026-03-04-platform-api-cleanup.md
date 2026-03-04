# Platform API Cleanup — Dead Endpoint Removal + Response Normalization

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove 3 dead endpoints (validate, lineage, 3x deprecated 410s) and normalize the remaining `/platform/*` error responses to guarantee `{success, error, error_type}` on every response.

**Architecture:** Delete dead code from `trigger_platform_status.py` and `platform_bp.py`, remove route registrations, clean up OpenAPI specs. Then fix the 5 remaining error responses that are missing `error_type` or `success` fields.

**Tech Stack:** Python/Azure Functions, OpenAPI JSON

---

## Batch 1: Remove Dead Endpoints

### Task 1: Remove `platform_lineage` function

**Files:**
- Modify: `triggers/trigger_platform_status.py` (delete lines 1344-1531)
- Modify: `triggers/trigger_platform_status.py` (update header lines 8, 25, 32)

**Step 1: Update the EXPORTS header (line 8)**

Remove `platform_lineage` from the EXPORTS comment:
```python
# Before:
# EXPORTS: platform_request_status, platform_health, platform_failures, platform_lineage, platform_validate

# After:
# EXPORTS: platform_request_status, platform_health, platform_failures
```

**Step 2: Remove lineage from the docstring (lines 25 and 32)**

Delete these two lines:
```
    GET /api/platform/lineage/{request_id} - Data lineage trace
```
```
    platform_lineage: HTTP trigger for GET /api/platform/lineage/{request_id}
```

**Step 3: Delete the `platform_lineage` function (lines 1344-1531)**

Delete the entire function — 188 lines from `async def platform_lineage` through the closing `)` of its exception handler.

**Step 4: Verify syntax**

Run: `python -m py_compile triggers/trigger_platform_status.py`
Expected: No output (clean compile)

---

### Task 2: Remove `platform_validate` function

**Files:**
- Modify: `triggers/trigger_platform_status.py` (delete lines 1533-1695, now renumbered after Task 1)
- Note: After Task 1 deletes 188 lines, `platform_validate` starts at ~line 1345

**Step 1: Remove validate from the docstring**

Delete these two lines:
```
    POST /api/platform/validate - Pre-flight validation before submission
```
```
    platform_validate: HTTP trigger for POST /api/platform/validate
```

**Step 2: Delete the `platform_validate` function**

Delete the entire function from `async def platform_validate` through its final closing `)` — ~163 lines. This is now the last function in the file.

**Step 3: Verify syntax**

Run: `python -m py_compile triggers/trigger_platform_status.py`
Expected: No output (clean compile)

**Step 4: Commit**

```bash
git add triggers/trigger_platform_status.py
git commit -m "refactor: remove dead platform_lineage and platform_validate functions

Both endpoints had zero callers. /validate is fully superseded by
/submit?dry_run=true. /lineage is superseded by /status/{id}?detail=full."
```

---

### Task 3: Remove route registrations from blueprint

**Files:**
- Modify: `triggers/platform/platform_bp.py` (delete lines 294-332, 697-801)

**Step 1: Delete the lineage route (lines 294-304)**

Delete the entire `platform_lineage_route` function:
```python
@bp.route(route="platform/lineage/{request_id}", methods=["GET"])
async def platform_lineage_route(req: func.HttpRequest) -> func.HttpResponse:
    ...
    from triggers.trigger_platform_status import platform_lineage
    return await platform_lineage(req)
```

**Step 2: Delete the validate route (lines 307-332, renumbered after step 1)**

Delete the entire `platform_validate_route` function:
```python
@bp.route(route="platform/validate", methods=["POST"])
async def platform_validate_route(req: func.HttpRequest) -> func.HttpResponse:
    ...
    from triggers.trigger_platform_status import platform_validate
    return await platform_validate(req)
```

**Step 3: Delete the 3 deprecated 410-Gone handlers (lines 695-801)**

Delete everything from the `# DEPRECATED` section header through `platform_vector_deprecated` — the `import json` on line 697, all 3 handler functions, through line 801.

**Step 4: Verify syntax**

Run: `python -m py_compile triggers/platform/platform_bp.py`
Expected: No output (clean compile)

**Step 5: Commit**

```bash
git add triggers/platform/platform_bp.py
git commit -m "refactor: remove 5 dead route registrations from platform blueprint

Removed: /platform/lineage, /platform/validate, /platform/raster,
/platform/raster-collection, /platform/vector (410 Gone shims)"
```

---

### Task 4: Remove from OpenAPI specs

**Files:**
- Modify: `openapi/platform-api-v1.json`
- Modify: `raster_api/openapi/platform-api-v1.json`

**Step 1: Remove `/api/platform/validate` entry from both JSON files**

Delete the full object at key `"/api/platform/validate"` from the `paths` object.

**Step 2: Remove `/api/platform/lineage/{request_id}` entry from both JSON files**

Delete the full object at key `"/api/platform/lineage/{request_id}"` from the `paths` object.

**Step 3: Validate JSON syntax**

Run: `python -m json.tool openapi/platform-api-v1.json > /dev/null && python -m json.tool raster_api/openapi/platform-api-v1.json > /dev/null && echo "OK"`
Expected: `OK`

**Step 4: Commit**

```bash
git add openapi/platform-api-v1.json raster_api/openapi/platform-api-v1.json
git commit -m "refactor: remove validate and lineage from OpenAPI specs"
```

---

## Batch 2: Normalize Response Contracts

### Task 5: Add `success: true` to `/platform/health`

**Files:**
- Modify: `triggers/trigger_platform_status.py`

**Step 1: Add `"success": True` to the health success response**

Find the `result = {` dict at ~line 1081 (renumbered after deletions) and add `"success": True` as the first field:

```python
# Before:
        result = {
            "status": status,
            "ready_for_jobs": ready_for_jobs,

# After:
        result = {
            "success": True,
            "status": status,
            "ready_for_jobs": ready_for_jobs,
```

**Step 2: Add `"success": False` to the health error response**

Find the exception handler dict at ~line 1100 (renumbered) and add:

```python
# Before:
            json.dumps({
                "status": "unavailable",
                "ready_for_jobs": False,
                "error": "Health check failed",

# After:
            json.dumps({
                "success": False,
                "status": "unavailable",
                "ready_for_jobs": False,
                "error": "Health check failed",
                "error_type": "HealthCheckError",
```

---

### Task 6: Add `success: true` to `/platform/failures`

**Files:**
- Modify: `triggers/trigger_platform_status.py`

**Step 1: Add `"success": True` to the failures result dict**

Find the `result = {` dict at ~line 1157 (renumbered) and add:

```python
# Before:
        result = {
            "period_hours": hours,

# After:
        result = {
            "success": True,
            "period_hours": hours,
```

**Step 2: Fix the failures exception handler**

Find the exception handler at ~line 1296 (renumbered) and add `success` and `error_type`:

```python
# Before:
            json.dumps({
                "error": "Failed to retrieve failure data",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),

# After:
            json.dumps({
                "success": False,
                "error": "Failed to retrieve failure data",
                "error_type": "QueryError",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }),
```

---

### Task 7: Add `error_type` to status 404 and deprecated-param errors

**Files:**
- Modify: `triggers/trigger_platform_status.py`

**Step 1: Add `error_type` to the status/{id} 404 response**

Find the 404 response at ~line 184 (renumbered):

```python
# Before:
                    json.dumps({
                        "success": False,
                        "error": f"No Platform request found for ID: {lookup_id}",
                        "hint": "ID can be a request_id, job_id, release_id, or asset_id"
                    }),

# After:
                    json.dumps({
                        "success": False,
                        "error": f"No Platform request found for ID: {lookup_id}",
                        "error_type": "NotFound",
                        "hint": "ID can be a request_id, job_id, release_id, or asset_id"
                    }),
```

**Step 2: Add `error_type` to the deprecated query param 400 response**

Find the 400 response at ~line 118 (renumbered):

```python
# Before:
                json.dumps({
                    "success": False,
                    "error": f"Query parameter '{param_name}' is not supported for lookups",

# After:
                json.dumps({
                    "success": False,
                    "error": f"Query parameter '{param_name}' is not supported for lookups",
                    "error_type": "ValidationError",
```

---

### Task 8: Add `success: true` to `submit?dry_run=true` response

**Files:**
- Modify: `triggers/platform/submit.py`

**Step 1: Add `"success": True` alongside `"valid": True`**

Find the dry_run response at ~line 254:

```python
# Before:
                return func.HttpResponse(
                    json.dumps({
                        "valid": True,
                        "dry_run": True,

# After:
                return func.HttpResponse(
                    json.dumps({
                        "success": True,
                        "valid": True,
                        "dry_run": True,
```

This is additive — existing clients checking `valid` still work, new clients can use `success`.

---

### Task 9: Verify, commit, and validate

**Step 1: Syntax check all modified files**

```bash
python -m py_compile triggers/trigger_platform_status.py && \
python -m py_compile triggers/platform/platform_bp.py && \
python -m py_compile triggers/platform/submit.py && \
echo "All OK"
```
Expected: `All OK`

**Step 2: Verify no remaining references to deleted endpoints**

```bash
grep -rn "platform_lineage\|platform_validate\|platform/lineage\|platform/validate" \
  triggers/ services/ --include="*.py" | grep -v "\.pyc" | grep -v "__pycache__"
```
Expected: No matches (or only archive/doc references)

**Step 3: Commit**

```bash
git add triggers/trigger_platform_status.py triggers/platform/submit.py
git commit -m "fix: ADV-3 normalize platform response contracts

Add success/error_type to health, failures, status 404, and dry_run
responses. All /platform/* endpoints now guarantee {success, error, error_type}
on errors and {success: true} on success."
```

---

## Summary

| Change | Lines removed | Lines added |
|--------|-------------|-------------|
| Delete `platform_lineage` | ~188 | 0 |
| Delete `platform_validate` | ~163 | 0 |
| Delete lineage + validate routes | ~40 | 0 |
| Delete 3 deprecated 410 handlers | ~107 | 0 |
| Delete OpenAPI entries | ~70 | 0 |
| Add success/error_type fields | 0 | ~10 |
| **Total** | **~568** | **~10** |

**Post-implementation contract**: Every `/api/platform/*` endpoint returns:
- Success: `{success: true, ...}`
- Error: `{success: false, error: "message", error_type: "Category", ...}`
