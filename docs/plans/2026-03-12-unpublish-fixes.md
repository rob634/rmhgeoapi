# Unpublish Pipeline Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three unpublish bugs (400 on DDH, first-submit failure, delete_blobs ignored) and harden the resubmit endpoint to prevent data destruction.

**Architecture:** Surgical fixes at each layer of the unpublish pipeline (trigger → job → handler), plus a safety guard on the resubmit endpoint. No new abstractions needed — follows existing `delete_data_files` pattern from zarr as reference.

**Tech Stack:** Python, Azure Functions, psycopg3, Azure Blob Storage

**Bugs:**
- UNP-3 CRITICAL: `delete_blobs=false` silently ignored — blobs always deleted
- UNP-1 MEDIUM: 400 on valid DDH identifiers when platform request record missing
- UNP-2 MEDIUM: Job fails on first submit, succeeds on resubmit
- UNP-ARCH: `/api/platform/resubmit` can destroy completed work

---

## Chunk 1: UNP-3 — delete_blobs Pipeline Fix (CRITICAL)

The `delete_blobs` parameter is rejected at the HTTP whitelist, never extracted, absent from all job schemas, and the handler deletes unconditionally. Fix requires changes at 5 layers across 6 files.

**Reference pattern:** `delete_data_files` in zarr unpublish (fully working end-to-end).

### Task 1: Add delete_blobs to HTTP whitelist

**Files:**
- Modify: `triggers/platform/unpublish.py:28-35`

- [ ] **Step 1: Add to _UNPUBLISH_FIELDS**

At line 32, add `'delete_blobs'` to the set:
```python
_UNPUBLISH_FIELDS = {
    'request_id', 'job_id', 'dataset_id', 'resource_id', 'version_id',
    'release_id', 'version_ordinal',  # SG2-1
    'data_type', 'table_name', 'schema_name', 'stac_item_id', 'collection_id',
    'dry_run', 'force_approved', 'delete_collection', 'delete_data_files',
    'delete_blobs',  # UNP-3: Control blob deletion (default True for backward compat)
    'reviewer',
    'deleted_by',  # DEPRECATED since v0.9.16.0 — use "reviewer" instead
}
```

- [ ] **Step 2: Commit**
```bash
git add triggers/platform/unpublish.py
git commit -m "fix(UNP-3): add delete_blobs to unpublish field whitelist"
```

### Task 2: Extract and pass delete_blobs in all three unpublish paths

**Files:**
- Modify: `triggers/platform/unpublish.py:541-546` (vector)
- Modify: `triggers/platform/unpublish.py:636-641` (raster)
- Modify: `triggers/platform/unpublish.py:753-759` (zarr)

- [ ] **Step 1: Extract delete_blobs near the top of platform_unpublish()**

After line 151 (`dry_run` extraction), add:
```python
delete_blobs = req_body.get('delete_blobs', True)  # Default: delete (backward compat)
```

- [ ] **Step 2: Pass to vector job_params (line ~541)**

Change the vector job_params dict to include:
```python
job_params = {
    "table_name": table_name,
    "schema_name": schema_name,
    "dry_run": dry_run,
    "force_approved": force_approved,
    "delete_blobs": delete_blobs,
}
```

Note: Vector unpublish drops PostGIS tables (no blobs involved for vector data),
but pass the flag through for consistency and future-proofing. The vector handler
doesn't have blob deletion, so this is a no-op for vector but keeps the API contract
uniform across data types.

- [ ] **Step 3: Pass to raster job_params (line ~636)**

```python
job_params = {
    "stac_item_id": stac_item_id,
    "collection_id": collection_id,
    "dry_run": dry_run,
    "force_approved": force_approved,
    "delete_blobs": delete_blobs,
}
```

- [ ] **Step 4: Pass to zarr job_params (line ~753)**

```python
job_params = {
    "stac_item_id": stac_item_id,
    "collection_id": collection_id,
    "dry_run": dry_run,
    "delete_data_files": delete_data_files,
    "force_approved": force_approved,
    "delete_blobs": delete_blobs,
}
```

- [ ] **Step 5: Commit**
```bash
git add triggers/platform/unpublish.py
git commit -m "fix(UNP-3): extract and pass delete_blobs to all unpublish job types"
```

### Task 3: Add delete_blobs to job parameter schemas

**Files:**
- Modify: `jobs/unpublish_raster.py:93-110`
- Modify: `jobs/unpublish_vector.py:89-106`
- Modify: `jobs/unpublish_zarr.py:92-113`

- [ ] **Step 1: Add to unpublish_raster parameters_schema**

After `force_approved` entry, add:
```python
"delete_blobs": {
    "type": "bool",
    "default": True,
    "description": "Delete COG blobs from storage (default True for backward compat)"
},
```

- [ ] **Step 2: Add to unpublish_vector parameters_schema**

```python
"delete_blobs": {
    "type": "bool",
    "default": True,
    "description": "Reserved for future use (vector has no blob deletion)"
},
```

- [ ] **Step 3: Add to unpublish_zarr parameters_schema**

```python
"delete_blobs": {
    "type": "bool",
    "default": True,
    "description": "Delete zarr reference blobs from storage (default True). Separate from delete_data_files which controls source NetCDF files."
},
```

- [ ] **Step 4: Commit**
```bash
git add jobs/unpublish_raster.py jobs/unpublish_vector.py jobs/unpublish_zarr.py
git commit -m "fix(UNP-3): add delete_blobs to all unpublish job parameter schemas"
```

### Task 4: Pass delete_blobs through to Stage 2 blob deletion tasks

**Files:**
- Modify: `jobs/unpublish_raster.py:186-197` (Stage 2 task creation)
- Modify: `jobs/unpublish_zarr.py:182-192` (Stage 2 task creation)

- [ ] **Step 1: Raster — add delete_blobs to Stage 2 task params**

In `create_tasks_for_stage` Stage 2 section, add to each blob task's parameters:
```python
"parameters": {
    "container": blob_info.get("container"),
    "blob_path": blob_info.get("blob_path"),
    "dry_run": dry_run,
    "delete_blobs": job_params.get("delete_blobs", True),
    "stac_item_id": job_params["stac_item_id"]
}
```

- [ ] **Step 2: Zarr — add delete_blobs to Stage 2 task params**

Same pattern as raster.

- [ ] **Step 3: Commit**
```bash
git add jobs/unpublish_raster.py jobs/unpublish_zarr.py
git commit -m "fix(UNP-3): pass delete_blobs through to Stage 2 blob deletion tasks"
```

### Task 5: Add delete_blobs guard in delete_blob handler

**Files:**
- Modify: `services/unpublish_handlers.py:918-997`

- [ ] **Step 1: Add guard before blob deletion**

After the dry_run check (line ~963) and before the actual delete call (line ~981),
add a `delete_blobs` check:

```python
# Check delete_blobs flag (UNP-3: respect user's preservation request)
if not params.get('delete_blobs', True):
    logger.info(f"Skipped blob deletion (delete_blobs=false): {container}/{blob_path}")
    return {
        "success": True,
        "deleted": False,
        "skipped_by_flag": True,
        "container": container,
        "blob_path": blob_path,
    }
```

Insert this AFTER the dry_run block and BEFORE the zone detection / actual deletion code.

- [ ] **Step 2: Commit**
```bash
git add services/unpublish_handlers.py
git commit -m "fix(UNP-3): add delete_blobs guard in delete_blob handler — prevents data loss"
```

---

## Chunk 2: UNP-1 — Better DDH Resolution Fallback

The unpublish endpoint returns 400 when DDH identifiers don't match any platform request
record. The fix adds a fallback that searches for the actual resource directly in PostGIS
and pgSTAC when the platform request lookup fails.

### Task 6: Add direct resource lookup fallback in _resolve_unpublish_data_type

**Files:**
- Modify: `triggers/platform/unpublish.py:347-382`

- [ ] **Step 1: After DDH lookup fails, try direct resource search**

After the `get_request_by_ddh_ids()` returns None (line ~354), instead of falling
through silently, add a direct search:

```python
if original_request:
    # ... existing success path ...
else:
    # DDH lookup failed — try direct resource search (UNP-1)
    logger.info(
        f"No platform request for DDH ids "
        f"({dataset_id}/{resource_id}/{version_id}), "
        f"attempting direct resource lookup"
    )

    # Try vector: check geo.table_catalog for matching table pattern
    # Convention: table names derived from resource_id
    try:
        from infrastructure import RepositoryFactory
        repos = RepositoryFactory.create_repositories()
        pg_repo = repos['pg_repo']
        with pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                # Search catalog for tables matching DDH pattern
                cur.execute("""
                    SELECT table_name, schema_name
                    FROM geo.table_catalog
                    WHERE table_name ILIKE %s
                    LIMIT 1
                """, (f"%{resource_id.lower().replace('-', '_')}%",))
                row = cur.fetchone()
                if row:
                    return 'vector', {
                        'table_name': row['table_name'],
                        'schema_name': row['schema_name'],
                    }, None
    except Exception as e:
        logger.debug(f"Direct vector lookup failed: {e}")

    # Try raster: check pgstac for matching STAC item
    try:
        with pg_repo._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, collection
                    FROM pgstac.items
                    WHERE id ILIKE %s
                    LIMIT 1
                """, (f"%{dataset_id}%{resource_id}%",))
                row = cur.fetchone()
                if row:
                    return 'raster', {
                        'stac_item_id': row['id'],
                        'collection_id': row['collection'],
                    }, None
    except Exception as e:
        logger.debug(f"Direct raster lookup failed: {e}")
```

- [ ] **Step 2: Improve 400 error message with actionable guidance**

At line ~155, update the error message to suggest what the user can provide:
```python
return validation_error(
    f"Could not resolve resource for dataset_id={dataset_id}, "
    f"resource_id={resource_id}, version_id={version_id}. "
    f"No matching platform request found. Try providing one of: "
    f"request_id, job_id, table_name (vector), or "
    f"stac_item_id + collection_id (raster/zarr)."
)
```

- [ ] **Step 3: Commit**
```bash
git add triggers/platform/unpublish.py
git commit -m "fix(UNP-1): add direct resource lookup fallback when DDH lookup fails"
```

---

## Chunk 3: UNP-2 — First-Submit Resilience

The root cause of first-submit failure is unclear without logs from the actual failing
job. The most likely cause is deterministic job ID collision with a stale record. Fix
adds better error reporting and collision handling.

### Task 7: Add job ID collision handling in unpublish submission

**Files:**
- Modify: `triggers/platform/unpublish.py` (near `create_and_submit_job` calls)

- [ ] **Step 1: Check for existing job before creating**

Before each `create_and_submit_job()` call (lines ~555, ~648, ~766), add collision check:

```python
from core.job_id import generate_deterministic_job_id

# Check for existing job with same deterministic ID
expected_job_id = generate_deterministic_job_id(job_type, job_params)
existing_job = job_repo.get_job(expected_job_id)

if existing_job:
    if existing_job.status.value == 'failed':
        # Previous attempt failed — clean up and retry with fresh ID
        logger.info(
            f"Found stale failed job {expected_job_id[:16]}..., "
            f"cleaning up and resubmitting"
        )
        job_repo.delete_job(expected_job_id)
    elif existing_job.status.value == 'completed':
        return platform_response(
            success=True,
            message=f"Unpublish already completed (job {expected_job_id[:16]}...)",
            data={"job_id": expected_job_id, "status": "already_completed"},
            status_code=200
        )
    elif existing_job.status.value == 'processing':
        return platform_response(
            success=False,
            message=f"Unpublish already in progress (job {expected_job_id[:16]}...)",
            data={"job_id": expected_job_id, "status": "processing"},
            status_code=409
        )
```

- [ ] **Step 2: Commit**
```bash
git add triggers/platform/unpublish.py
git commit -m "fix(UNP-2): handle job ID collision on unpublish — auto-clean failed, report in-progress"
```

---

## Chunk 4: UNP-ARCH — Harden Resubmit Endpoint

The resubmit endpoint can destroy completed work. Add a guard against resubmitting
completed jobs (require `force=true`), and log a deprecation warning encouraging
migration to the standard submit flow.

### Task 8: Add completed-job guard to resubmit

**Files:**
- Modify: `triggers/platform/resubmit.py:130-143`

- [ ] **Step 1: Add completed-job block**

After the processing check (line 131), add:
```python
# Block resubmit on completed jobs unless force=True (UNP-ARCH)
if job.status.value == 'completed' and not force:
    return func.HttpResponse(
        json.dumps({
            "success": False,
            "error": (
                "Job already completed successfully. Resubmitting will destroy "
                "the completed output and re-run from scratch. "
                "Use force=true to confirm, or submit a new job instead."
            ),
            "job_status": job.status.value,
            "job_id": job_id,
            "platform_refs": platform_refs,
            "error_type": "JobAlreadyCompleted"
        }),
        status_code=409,
        mimetype="application/json"
    )
```

- [ ] **Step 2: Add deprecation log**

At the top of `handle()` (after line 67), add:
```python
logger.warning(
    "DEPRECATION: /api/platform/resubmit called. "
    "This endpoint is for internal error recovery only. "
    "External clients should use /api/platform/submit for new submissions."
)
```

- [ ] **Step 3: Commit**
```bash
git add triggers/platform/resubmit.py
git commit -m "fix(UNP-ARCH): block resubmit on completed jobs, add deprecation warning"
```

---

## Chunk 5: Verification

### Task 9: Verify all changes

- [ ] **Step 1: Run existing unit tests**
```bash
conda run -n azgeo pytest tests/ -x -q 2>&1 | tail -20
```

- [ ] **Step 2: Verify delete_blobs pipeline end-to-end (code review)**

Trace the parameter through all layers:
1. `_UNPUBLISH_FIELDS` contains `'delete_blobs'`
2. `platform_unpublish()` extracts `delete_blobs = req_body.get('delete_blobs', True)`
3. All three `job_params` dicts include `delete_blobs`
4. All three `parameters_schema` include `delete_blobs`
5. Raster + zarr `create_tasks_for_stage` Stage 2 passes `delete_blobs` to task params
6. `delete_blob()` handler checks `params.get('delete_blobs', True)` before deleting

- [ ] **Step 3: Verify resubmit guard**

Confirm `completed` status check exists before cleanup execution.

- [ ] **Step 4: Final commit with all changes**
```bash
git log --oneline -8  # Verify commit history
```
