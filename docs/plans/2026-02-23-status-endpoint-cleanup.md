# Status Endpoint Cleanup Implementation Plan — COMPLETE

> **Status**: IMPLEMENTED in v0.8.24.0 (23 FEB 2026). All 6 tasks executed, deployed, QA-verified.

**Goal:** Reshape `/api/platform/status` response from a ~140-line operational blob into a clean ~40-line B2B output with separated concerns.

**Architecture:** Single file change (`triggers/trigger_platform_status.py`). Replace the monolithic `_build_single_status_response()` with focused helper functions that read from Release records instead of parsing `job_result`. Fix the silent 404 bug on asset_id/release_id/job_id lookups. Always include version history.

**Tech Stack:** Python, Azure Functions, existing Asset/Release/Platform repositories

**Post-execution addition:** `?detail=full` parameter added to expose old operational blob on demand.

---

## Context for Implementer

**File:** `triggers/trigger_platform_status.py` (~1060 lines)

**Key functions to modify:**
- `platform_request_status()` (line 61) — main handler, auto-detect ID logic
- `_build_single_status_response()` (line 555) — builds the response dict
- `_generate_data_access_urls()` (line 903) — generates service/approval URLs
- `_handle_platform_refs_lookup()` (line 726) — dataset_id+resource_id lookup
- `_build_version_summary()` (line 695) — already clean, keep as-is

**Data model (read `core/models/asset.py`):**
- `Asset`: identity container (`asset_id`, `dataset_id`, `resource_id`, `data_type`, `release_count`)
- `AssetRelease`: versioned artifact with physical outputs on the record itself:
  - `blob_path` (raster COG path), `table_name` (vector PostGIS table)
  - `stac_item_id`, `stac_collection_id`
  - `version_id`, `version_ordinal`, `revision`, `is_latest`
  - `approval_state`, `clearance_state`, `processing_status`

**Current response problems:**
1. `job_result` dumps 80+ lines of raw worker output (memory stats, checksums, etc.)
2. `task_summary` is internal job execution detail
3. `data_access` mixes 9 titiler URLs, generic STAC search, approval workflow
4. `urls` has internal admin endpoints (`/api/dbadmin/tasks/...`)
5. `versions` array only included for `?dataset_id&resource_id` lookups
6. `dataset_id`, `resource_id` duplicated at top level AND inside `asset` block
7. Auto-detect for asset_id/release_id/job_id silently 404s due to bare `except Exception: pass`

---

## Task 1: Fix the 404 Bug in Auto-Detect ID Lookup

**Files:**
- Modify: `triggers/trigger_platform_status.py:161-191`

**What:** The release_id and asset_id lookup paths (lines 161-191) wrap everything in `try/except Exception: pass`, silently swallowing real errors and falling through to 404. Replace bare excepts with specific exception handling and add logging.

**Step 1: Fix the release_id lookup block (lines 161-172)**

Replace:
```python
if not platform_request:
    # V0.9: Try as release_id
    try:
        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()
        release = release_repo.get_by_id(lookup_id)
        if release and release.job_id:
            platform_request = platform_repo.get_request_by_job(release.job_id)
            lookup_type = "release_id"
            pre_resolved_release = release
    except Exception:
        pass
```

With:
```python
if not platform_request:
    # V0.9: Try as release_id
    try:
        from infrastructure import ReleaseRepository
        release_repo = ReleaseRepository()
        release = release_repo.get_by_id(lookup_id)
        if release:
            if release.job_id:
                platform_request = platform_repo.get_request_by_job(release.job_id)
            lookup_type = "release_id"
            pre_resolved_release = release
    except ImportError:
        logger.warning("ReleaseRepository not available for release_id lookup")
    except Exception as e:
        logger.warning(f"Release lookup failed for {lookup_id}: {e}")
```

Note: Removed the `release.job_id` guard from the outer `if release` — a release without a job_id is still a valid release lookup (e.g., a release whose job failed before writing job_id). We still set `pre_resolved_release` so the response builder can use it.

**Step 2: Fix the asset_id lookup block (lines 174-191)**

Replace:
```python
if not platform_request:
    # V0.9: Try as asset_id
    try:
        from infrastructure import AssetRepository, ReleaseRepository
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(lookup_id)
        if asset:
            # Get latest release with a job
            release_repo = ReleaseRepository()
            release = release_repo.get_latest(asset.asset_id)
            if not release:
                release = release_repo.get_draft(asset.asset_id)
            if release and release.job_id:
                platform_request = platform_repo.get_request_by_job(release.job_id)
                lookup_type = "asset_id"
                pre_resolved_release = release
    except Exception as asset_err:
        logger.debug(f"Asset lookup failed (non-fatal): {asset_err}")
```

With:
```python
if not platform_request:
    # V0.9: Try as asset_id
    try:
        from infrastructure import AssetRepository, ReleaseRepository
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(lookup_id)
        if asset:
            release_repo = ReleaseRepository()
            release = release_repo.get_latest(asset.asset_id)
            if not release:
                release = release_repo.get_draft(asset.asset_id)
            if release:
                if release.job_id:
                    platform_request = platform_repo.get_request_by_job(release.job_id)
                lookup_type = "asset_id"
                pre_resolved_release = release
    except ImportError:
        logger.warning("AssetRepository/ReleaseRepository not available for asset_id lookup")
    except Exception as e:
        logger.warning(f"Asset lookup failed for {lookup_id}: {e}")
```

Same pattern: separate `release.job_id` from `pre_resolved_release` assignment.

**Step 3: Allow response building WITHOUT a platform_request**

Currently line 193 returns 404 if `platform_request` is None. But with release_id/asset_id lookups, we may have a valid `pre_resolved_release` without a matching `api_requests` row (e.g., job_id is None, or api_requests row was never created).

Replace lines 193-202:
```python
if not platform_request:
    return func.HttpResponse(
        json.dumps({
            "success": False,
            "error": f"No Platform request found for ID: {lookup_id}",
            "hint": "ID can be a request_id, job_id, release_id, or asset_id"
        }),
        status_code=404,
        headers={"Content-Type": "application/json"}
    )
```

With:
```python
if not platform_request and not pre_resolved_release:
    return func.HttpResponse(
        json.dumps({
            "success": False,
            "error": f"No Platform request found for ID: {lookup_id}",
            "hint": "ID can be a request_id, job_id, release_id, or asset_id"
        }),
        status_code=404,
        headers={"Content-Type": "application/json"}
    )
```

And update lines 207-210 to handle None platform_request:
```python
result = _build_single_status_response(
    platform_request, job_repo, task_repo,
    verbose=verbose, pre_resolved_release=pre_resolved_release
)
```

The response builder (Task 3) will handle `platform_request=None` gracefully.

**Step 4: Verify**

```bash
conda activate azgeo && python -m pytest test/test_draft_mode.py -v && python -m pytest test/test_deployment_readiness.py -v
```

---

## Task 2: Create New Helper Functions

**Files:**
- Modify: `triggers/trigger_platform_status.py` — add 3 new functions after `_build_version_summary()` (after line 723)

**Step 1: Add `_build_outputs_block()`**

This replaces digging through `job_result` — reads directly from the Release record (authoritative source).

```python
def _build_outputs_block(release, job_result: Optional[dict] = None) -> Optional[dict]:
    """
    Build the outputs block from Release physical fields.

    Reads blob_path, table_name, stac_item_id, stac_collection_id directly
    from the Release record. Falls back to job_result for container name
    (not stored on Release).

    Args:
        release: AssetRelease object
        job_result: Optional job result dict for supplementary fields

    Returns:
        Dict with output artifact locations, or None if no outputs yet
    """
    if not release:
        return None

    # No outputs if processing hasn't completed
    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    outputs = {
        "stac_item_id": release.stac_item_id,
        "stac_collection_id": release.stac_collection_id,
    }

    # Raster outputs
    if release.blob_path:
        outputs["blob_path"] = release.blob_path
        # Container from job_result (not stored on release)
        container = None
        if job_result:
            cog_data = job_result.get('cog', {})
            if isinstance(cog_data, dict):
                container = cog_data.get('cog_container')
        outputs["container"] = container or "silver-cogs"

    # Vector outputs
    if release.table_name:
        outputs["table_name"] = release.table_name
        outputs["schema"] = "geo"

    return outputs
```

**Step 2: Add `_build_services_block()`**

Replaces the 9-URL titiler dump and generic STAC search with 2-3 useful URLs.

```python
def _build_services_block(release, data_type: str) -> Optional[dict]:
    """
    Build focused service URLs for accessing the output data.

    Raster: preview, tiles, viewer (from titiler)
    Vector: collection, items (from OGC Features/TiPG)

    Args:
        release: AssetRelease object
        data_type: "raster" or "vector"

    Returns:
        Dict with service URLs, or None if no outputs
    """
    if not release:
        return None

    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    from config import get_config
    config = get_config()

    services = {}

    if data_type == "raster" and release.blob_path:
        titiler_base = config.titiler_base_url
        from urllib.parse import quote
        cog_url = quote(f"/vsiaz/silver-cogs/{release.blob_path}", safe='')
        services["preview"] = f"{titiler_base}/cog/preview.png?url={cog_url}&max_size=512"
        services["tiles"] = f"{titiler_base}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={cog_url}"
        services["viewer"] = f"{titiler_base}/cog/WebMercatorQuad/map.html?url={cog_url}"

    elif data_type == "vector" and release.table_name:
        tipg_base = config.tipg_base_url
        qualified = f"geo.{release.table_name}" if '.' not in release.table_name else release.table_name
        services["collection"] = f"{tipg_base}/collections/{qualified}"
        services["items"] = f"{tipg_base}/collections/{qualified}/items"

    # STAC URLs (both raster and vector)
    if release.stac_collection_id:
        etl_base = config.etl_app_base_url
        services["stac_collection"] = f"{etl_base}/api/collections/{release.stac_collection_id}"
        if release.stac_item_id:
            services["stac_item"] = f"{etl_base}/api/collections/{release.stac_collection_id}/items/{release.stac_item_id}"

    return services if services else None
```

**Step 3: Add `_build_approval_block()`**

```python
def _build_approval_block(release, asset_id: str, data_type: str) -> Optional[dict]:
    """
    Build approval workflow URLs.

    Only included when the release is in pending_review state.

    Args:
        release: AssetRelease object
        asset_id: Asset ID for approve/reject POST
        data_type: "raster" or "vector"

    Returns:
        Dict with approval URLs, or None if not pending
    """
    if not release:
        return None

    approval_state = release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state)
    if approval_state != 'pending_review':
        return None

    proc_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)
    if proc_status != 'completed':
        return None

    from config import get_config
    config = get_config()
    platform_base = config.platform_url.rstrip('/')

    approval = {
        "approve_url": f"{platform_base}/api/platform/approve",
        "asset_id": asset_id,
    }

    if data_type == "raster" and release.blob_path:
        from urllib.parse import quote
        cog_url = quote(f"/vsiaz/silver-cogs/{release.blob_path}", safe='')
        if release.stac_item_id:
            approval["viewer_url"] = f"{platform_base}/api/interface/raster-viewer?item_id={release.stac_item_id}&asset_id={asset_id}"
            approval["embed_url"] = f"{platform_base}/api/interface/raster-viewer?item_id={release.stac_item_id}&asset_id={asset_id}&embed=true"
        else:
            approval["viewer_url"] = f"{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={asset_id}"
            approval["embed_url"] = f"{platform_base}/api/interface/raster-viewer?url={cog_url}&asset_id={asset_id}&embed=true"

    elif data_type == "vector" and release.table_name:
        approval["viewer_url"] = f"{platform_base}/api/interface/vector-viewer?collection={release.table_name}&asset_id={asset_id}"
        approval["embed_url"] = f"{platform_base}/api/interface/vector-viewer?collection={release.table_name}&asset_id={asset_id}&embed=true"

    return approval
```

**Step 4: Verify no syntax errors**

```bash
conda activate azgeo && python -c "import triggers.trigger_platform_status; print('OK')"
```

---

## Task 3: Rewrite `_build_single_status_response()`

**Files:**
- Modify: `triggers/trigger_platform_status.py:555-692` — replace entire function

**Step 1: Replace `_build_single_status_response()`**

Replace lines 555-692 with:

```python
def _build_single_status_response(
    platform_request,
    job_repo,
    task_repo,
    verbose: bool = False,
    pre_resolved_release=None
) -> dict:
    """
    Build clean B2B status response for a single Platform request.

    V0.9.1 (23 FEB 2026): Restructured for B2B clarity.
    - Reads outputs from Release record (authoritative), not job_result
    - Separates concerns: identity (asset), lifecycle (release), artifacts (outputs),
      access (services), workflow (approval)
    - Drops internal operational detail from default response (job_result,
      task_summary, admin URLs). Available via ?detail=full (future).

    Args:
        platform_request: ApiRequest record (can be None for release/asset lookups)
        job_repo: JobRepository instance
        task_repo: TaskRepository instance
        verbose: Include full task details (future: ?detail=full)
        pre_resolved_release: AssetRelease if already fetched (skips re-query)

    Returns:
        Response dict ready for JSON serialization
    """
    from infrastructure import ReleaseRepository, AssetRepository

    # =====================================================================
    # 1. Resolve Release and Asset
    # =====================================================================
    release = pre_resolved_release
    asset = None

    if not release and platform_request and platform_request.job_id:
        try:
            release = ReleaseRepository().get_by_job_id(platform_request.job_id)
        except Exception:
            pass

    if release:
        try:
            asset = AssetRepository().get_by_id(release.asset_id)
        except Exception:
            pass

    # Fallback asset from platform_request.asset_id if release didn't resolve
    if not asset and platform_request and getattr(platform_request, 'asset_id', None):
        try:
            asset = AssetRepository().get_by_id(platform_request.asset_id)
        except Exception:
            pass

    # =====================================================================
    # 2. Resolve Job status (single field, not the full result blob)
    # =====================================================================
    job = None
    job_status = "unknown"
    job_result = None
    job_id = None

    if platform_request and platform_request.job_id:
        job_id = platform_request.job_id
    elif release and release.job_id:
        job_id = release.job_id

    if job_id:
        job = job_repo.get_job(job_id)

    if job:
        job_status = job.status.value if hasattr(job.status, 'value') else job.status
        job_result = job.result_data
    elif release:
        # Use release processing_status as proxy if job not found
        job_status = release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status)

    # =====================================================================
    # 3. Determine data_type
    # =====================================================================
    data_type = None
    if asset:
        data_type = asset.data_type
    elif platform_request:
        data_type = platform_request.data_type

    # =====================================================================
    # 4. Build response
    # =====================================================================
    result = {
        "success": True,
        "request_id": platform_request.request_id if platform_request else None,
    }

    # Asset block
    if asset:
        result["asset"] = {
            "asset_id": asset.asset_id,
            "dataset_id": asset.dataset_id,
            "resource_id": asset.resource_id,
            "data_type": asset.data_type,
            "release_count": asset.release_count,
        }
    else:
        result["asset"] = None

    # Release block (with version_ordinal — new)
    if release:
        result["release"] = {
            "release_id": release.release_id,
            "version_id": release.version_id,
            "version_ordinal": release.version_ordinal,
            "revision": release.revision,
            "is_latest": release.is_latest,
            "processing_status": release.processing_status.value if hasattr(release.processing_status, 'value') else str(release.processing_status),
            "approval_state": release.approval_state.value if hasattr(release.approval_state, 'value') else str(release.approval_state),
            "clearance_state": release.clearance_state.value if hasattr(release.clearance_state, 'value') else str(release.clearance_state),
        }
    else:
        result["release"] = None

    # Job status (single field)
    result["job_status"] = job_status

    # Outputs (from Release record, not job_result)
    result["outputs"] = _build_outputs_block(release, job_result)

    # Services (focused URLs)
    result["services"] = _build_services_block(release, data_type) if data_type else None

    # Approval (only when pending_review + completed)
    asset_id = asset.asset_id if asset else None
    result["approval"] = _build_approval_block(release, asset_id, data_type) if (asset_id and data_type) else None

    # Version history (always include if asset has releases)
    result["versions"] = None
    if asset:
        try:
            release_repo = ReleaseRepository()
            all_releases = release_repo.list_by_asset(asset.asset_id)
            if all_releases:
                result["versions"] = _build_version_summary(all_releases)
        except Exception:
            pass

    return result
```

**Step 2: Verify import and basic syntax**

```bash
conda activate azgeo && python -c "import triggers.trigger_platform_status; print('OK')"
```

---

## Task 4: Simplify `_handle_platform_refs_lookup()`

**Files:**
- Modify: `triggers/trigger_platform_status.py:726-900`

**What:** The platform_refs handler currently has its own duplicated response construction (lines 841-882) for the edge case where no `platform_request` is found. Since `_build_single_status_response()` now handles `platform_request=None`, we can simplify.

**Step 1: Replace `_handle_platform_refs_lookup()`**

Replace lines 726-900 with:

```python
def _handle_platform_refs_lookup(
    dataset_id: str,
    resource_id: str,
    job_repo,
    task_repo,
    platform_repo,
    verbose: bool = False
) -> func.HttpResponse:
    """
    Lookup status by dataset_id + resource_id (platform refs).

    V0.9.1 (23 FEB 2026): Simplified — delegates to _build_single_status_response()
    which now handles None platform_request and always includes versions.

    Priority logic for selecting the primary release:
        1. Release with active processing (PENDING or PROCESSING)
        2. Completed draft (no version_id, processing done)
        3. Latest approved release
        4. Most recent release overall

    Args:
        dataset_id: Platform dataset identifier
        resource_id: Platform resource identifier
        job_repo: JobRepository instance
        task_repo: TaskRepository instance
        platform_repo: PlatformRepository instance
        verbose: Include full task details

    Returns:
        func.HttpResponse with status JSON
    """
    from infrastructure import AssetRepository, ReleaseRepository

    asset_repo = AssetRepository()
    release_repo = ReleaseRepository()

    # Find asset by identity triple
    asset = asset_repo.get_by_identity("ddh", dataset_id, resource_id)
    if not asset:
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"No asset found for dataset_id={dataset_id}, resource_id={resource_id}",
                "hint": "Check dataset_id and resource_id values, or submit a new request via /api/platform/submit"
            }),
            status_code=404,
            headers={"Content-Type": "application/json"}
        )

    # Get all releases for this asset
    releases = release_repo.list_by_asset(asset.asset_id)
    if not releases:
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "asset": {
                    "asset_id": asset.asset_id,
                    "dataset_id": asset.dataset_id,
                    "resource_id": asset.resource_id,
                    "data_type": asset.data_type,
                    "release_count": asset.release_count,
                },
                "releases": [],
                "message": "Asset exists but has no releases"
            }, indent=2, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    # Priority: active processing > completed draft > latest approved > most recent
    primary_release = None

    for r in releases:
        proc = r.processing_status.value if hasattr(r.processing_status, 'value') else str(r.processing_status)
        if proc in ('pending', 'processing'):
            primary_release = r
            break
    if not primary_release:
        for r in releases:
            if r.is_draft() and (r.processing_status.value if hasattr(r.processing_status, 'value') else str(r.processing_status)) == 'completed':
                primary_release = r
                break
    if not primary_release:
        for r in releases:
            if r.is_latest:
                primary_release = r
                break
    if not primary_release:
        primary_release = releases[0]

    # Get platform request for primary release's job
    platform_request = None
    if primary_release.job_id:
        platform_request = platform_repo.get_request_by_job(primary_release.job_id)

    # Build response using shared builder
    result = _build_single_status_response(
        platform_request, job_repo, task_repo,
        verbose=verbose, pre_resolved_release=primary_release
    )

    # Add lookup_type marker
    result["lookup_type"] = "platform_refs"

    return func.HttpResponse(
        json.dumps(result, indent=2, default=str),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )
```

**What changed:** Removed the duplicated response construction (lines 841-882), removed the separate workflow_status/message logic, removed the separate versions append (shared builder now always includes versions).

**Step 2: Verify syntax**

```bash
conda activate azgeo && python -c "import triggers.trigger_platform_status; print('OK')"
```

---

## Task 5: Clean Up — Remove Old `_generate_data_access_urls()` and Update Docstring

**Files:**
- Modify: `triggers/trigger_platform_status.py`

**Step 1: Delete `_generate_data_access_urls()` (lines 903-1057)**

This function is replaced by `_build_services_block()` and `_build_approval_block()`. Remove the entire function.

**Step 2: Update the module docstring (lines 1-37)**

Update the response example in `platform_request_status()` docstring (lines 87-111) to show the new shape:

```python
    Response for single request:
    {
        "success": true,
        "request_id": "a3f2c1b8...",
        "asset": {"asset_id": "...", "dataset_id": "...", "resource_id": "...", "data_type": "raster", "release_count": 2},
        "release": {"release_id": "...", "version_id": "v1", "version_ordinal": 1, "approval_state": "approved", ...},
        "job_status": "completed",
        "outputs": {"blob_path": "...", "stac_item_id": "...", "stac_collection_id": "..."},
        "services": {"preview": "...", "tiles": "...", "viewer": "..."},
        "approval": null,
        "versions": [{"release_id": "...", "version_id": "v1", ...}]
    }
```

**Step 3: Verify full import and existing tests still pass**

```bash
conda activate azgeo && python -c "import triggers.trigger_platform_status; print('OK')"
conda activate azgeo && python -m pytest test/test_draft_mode.py test/test_deployment_readiness.py -v
```

---

## Task 6: Deploy and Smoke Test

**Step 1: Deploy all apps**

```bash
./deploy.sh all
```

**Step 2: Verify the 404 fixes — all ID types should work**

Using test data from the current database (raster asset `v09-raster-test/dctest`):

```bash
# By request_id (should already work)
curl -s "https://rmhazuregeoapi-.../api/platform/status/5af1552b2ae9d82e3efbb879079584f3" | python3 -m json.tool

# By asset_id (was broken, should now work)
curl -s "https://rmhazuregeoapi-.../api/platform/status/05cb99e14cffa92e31f5b3fd1944e1cf" | python3 -m json.tool

# By release_id (was broken, should now work)
curl -s "https://rmhazuregeoapi-.../api/platform/status/a8b1da7b27cdb794667447ac19ac3113" | python3 -m json.tool

# By dataset_id + resource_id
curl -s "https://rmhazuregeoapi-.../api/platform/status?dataset_id=v09-raster-test&resource_id=dctest" | python3 -m json.tool
```

**Step 3: Verify response shape**

All lookups should return the new clean shape with:
- `asset` block (not duplicated at top level)
- `release` block (with `version_ordinal`)
- `job_status` (single field, not `job_result` blob)
- `outputs` block (from Release record)
- `services` block (2-3 URLs, not 9)
- `approval` block (only when pending_review) or `null`
- `versions` array (always present)

**Step 4: Save sample outputs to `/tmp/` and update `JSON_RESPONSE.md`**

```bash
curl -s "https://rmhazuregeoapi-.../api/platform/status/5af1552b..." > /tmp/ep_new_request.json
curl -s "https://rmhazuregeoapi-.../api/platform/status/05cb99e1..." > /tmp/ep_new_asset.json
curl -s "https://rmhazuregeoapi-.../api/platform/status?dataset_id=v09-raster-test&resource_id=dctest" > /tmp/ep_new_refs.json
```

Update `JSON_RESPONSE.md` in the project root to replace old outputs with new ones.

---

## Parallel Execution Notes

**Tasks 1-2 modify different line ranges** in the same file but are logically independent:
- Task 1: lines 161-202 (auto-detect block)
- Task 2: new functions inserted after line 723

**Task 3 depends on Task 2** (uses the new helper functions).

**Task 4 depends on Task 3** (calls the rewritten `_build_single_status_response()`).

**Task 5 depends on Tasks 3-4** (removes old function, updates docstring after new code is in place).

**Task 6 depends on all** (deploy and verify).

**Suggested batching:**
- Batch A: Tasks 1 + 2 (independent line ranges)
- Batch B: Tasks 3 + 4 (rewrite response builders)
- Batch C: Task 5 (cleanup)
- Batch D: Task 6 (deploy + smoke test)
