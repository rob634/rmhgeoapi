# DAG Brain UI: Direct Service Calls (Remove Function App Proxy)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all httpx proxy calls in the DAG Brain UI (Docker orchestrator) with direct Python service calls, eliminating dependency on the Function App for UI operations.

**Architecture:** The DAG Brain runs the same codebase as the Function App. Every service, repository, and model class is already importable. The current proxy pattern (`UI → httpx → Function App → service → DB`) becomes (`UI → service → DB`). This removes the cross-app auth problem entirely — DAG Brain will have its own Easy Auth, and its UI never needs to call the Function App.

**Tech Stack:** FastAPI (existing), BlobRepository, AssetService, AssetApprovalService, PlatformRequest, translate_to_coremachine, create_and_submit_job

**Context:** The Function App's `web_interfaces/` UI is a test harness for API endpoints (loopback by design). The DAG Brain's `ui_routes.py` / `ui_submit_api.py` / `ui_assets_api.py` UI is the "real" admin UI — it should call services directly.

---

## Background

### Why the Proxy Existed
The original DAG Brain UI assumed it had no direct DB or blob access, so it proxied everything through the Function App via `ORCHESTRATOR_URL`. In practice, DAG Brain has full DB access (it polls the same state tables) and blob access (same managed identity). The proxy adds latency, creates a cross-app auth dependency, and will break when DAG Brain gets its own restrictive Easy Auth.

### What Changes
- `ui_submit_api.py` — 4 endpoints: containers, files, validate, submit
- `ui_assets_api.py` — 6 endpoints: stats, by-state, detail, approve, reject, revoke
- `templates/pages/jobs/detail.html` — 1 JS fetch to `ORCHESTRATOR_URL/api/jobs/resubmit/`

### What Doesn't Change
- `ui_routes.py` — page renders already use direct DB queries via `ui/` adapters
- `templates/` HTML — all fetch calls target `/ui/api/*` (local), no changes needed
- `static/` JS — no changes needed

### Tables Touched (all already accessible from DAG Brain)

| Table | Endpoints | Op |
|-------|-----------|-----|
| None (Azure Blob) | containers, files | READ |
| `app.assets` | submit, detail | R/W |
| `app.asset_releases` | submit, stats, by-state, detail, approve/reject/revoke | R/W |
| `app.api_requests` | submit | W |
| `app.release_audit` | approve/reject/revoke | W |
| `app.jobs` | submit (via CoreMachine) | W |
| pgSTAC | approve, revoke | W |

---

## File Structure

**Files to rewrite (replace proxy logic with direct calls):**
- `ui_submit_api.py` — Storage + platform submit (4 endpoints)
- `ui_assets_api.py` — Asset approval lifecycle (6 endpoints)

**Files to modify:**
- `templates/pages/jobs/detail.html` — Change resubmit JS to call local endpoint
- `ui_routes.py` — Add resubmit API endpoint (or new small router)

**Reference files (proven patterns to follow):**
- `web_interfaces/submit_raster_collection/interface.py:344-400` — Direct service call for platform submit
- `web_interfaces/submit/interface.py:102-128` — Direct BlobRepository for container/file listing
- `triggers/assets/asset_approvals_bp.py` — Approval service usage

---

## Task 1: Rewrite Storage Endpoints (containers + files)

**Files:**
- Modify: `ui_submit_api.py`

These endpoints hit Azure Blob Storage only — no database.

- [ ] **Step 1: Rewrite `GET /ui/api/containers`**

Replace httpx proxy with direct BlobRepository call:

```python
from infrastructure.blob import BlobRepository

@router.get("/containers")
async def list_containers(zone: str = "bronze"):
    """List storage containers for a zone."""
    try:
        repo = BlobRepository.for_zone(zone)
        containers = repo.list_containers()
        return JSONResponse(content={
            "zone": zone,
            "containers": containers or [],
        })
    except Exception as e:
        logger.warning(f"Container listing failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 2: Rewrite `GET /ui/api/files`**

Replace httpx proxy with direct BlobRepository call + extension filtering:

```python
@router.get("/files")
async def list_files(
    zone: str = "bronze",
    container: str = "",
    prefix: str = "",
    data_type: str = "raster",
    limit: int = 250,
):
    """List files in a container, filtered by data type extension."""
    if not container:
        return JSONResponse(content={"error": "container required"}, status_code=400)

    raster_exts = {'.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5'}
    vector_exts = {'.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip'}
    exts = vector_exts if data_type == "vector" else raster_exts

    try:
        repo = BlobRepository.for_zone(zone)
        blobs = repo.list_blobs(container, prefix=prefix, limit=limit * 2)

        filtered = []
        for blob in blobs:
            name = (blob.get("name") or "").lower()
            if any(name.endswith(ext) for ext in exts):
                filtered.append(blob)
                if len(filtered) >= limit:
                    break

        return JSONResponse(content={"files": filtered})
    except Exception as e:
        logger.warning(f"File listing failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 3: Remove httpx import and `_get_orchestrator_url()` from `ui_submit_api.py`**

These are no longer needed once all four endpoints are rewritten. Remove in this task for storage, leave the validate/submit rewrite for Task 2.

Actually — wait until Task 2 is complete, then remove in a cleanup step. For now just rewrite the two storage endpoints.

- [ ] **Step 4: Test locally**

```bash
conda activate azgeo
python -c "from infrastructure.blob import BlobRepository; r = BlobRepository.for_zone('bronze'); print(r.list_containers()[:3])"
```

- [ ] **Step 5: Commit**

```bash
git add ui_submit_api.py
git commit -m "refactor: direct BlobRepository calls for DAG Brain storage endpoints"
```

---

## Task 2: Rewrite Platform Submit Endpoints (validate + submit)

**Files:**
- Modify: `ui_submit_api.py`

**Reference:** `web_interfaces/submit_raster_collection/interface.py:344-400`

- [ ] **Step 1: Rewrite `POST /ui/api/validate` (dry_run)**

Dry run only validates the PlatformRequest and translates — no DB writes:

```python
from core.models.platform import PlatformRequest
from services.platform_translation import translate_to_coremachine
from pydantic import ValidationError

@router.post("/validate")
async def validate_submission(request: Request):
    """Validate a platform submission (dry_run — no job created)."""
    try:
        body = await request.json()
        platform_req = PlatformRequest(**body)
        job_type, job_params = translate_to_coremachine(platform_req)

        return JSONResponse(content={
            "success": True,
            "valid": True,
            "dry_run": True,
            "request_id": None,
            "would_create_job_type": job_type,
            "data_type": platform_req.data_type.value,
        })
    except ValidationError as e:
        return JSONResponse(
            content={
                "success": False,
                "valid": False,
                "dry_run": True,
                "validation": {"valid": False, "warnings": [str(err) for err in e.errors()]},
            },
            status_code=400,
        )
    except ValueError as e:
        return JSONResponse(
            content={
                "success": False,
                "valid": False,
                "dry_run": True,
                "validation": {"valid": False, "warnings": [str(e)]},
            },
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Validate failed: {e}", exc_info=True)
        return JSONResponse(
            content={"error": str(e), "validation": {"valid": False, "warnings": [str(e)]}},
            status_code=500,
        )
```

- [ ] **Step 2: Rewrite `POST /ui/api/submit` (full submission)**

Full platform submit chain — follows the pattern from `submit_raster_collection/interface.py`:

```python
from config import get_config, generate_platform_request_id
from infrastructure import PlatformRepository
from core.models import ApiRequest
from core.models.platform import PlatformRequest
from services.platform_translation import translate_to_coremachine
from services.platform_job_submit import create_and_submit_job
from services.asset_service import AssetService
from pydantic import ValidationError

@router.post("/submit")
async def submit_job(request: Request):
    """Submit a platform request — creates asset, release, and job."""
    try:
        body = await request.json()
        config = get_config()

        # 1. Validate
        platform_req = PlatformRequest(**body)

        # 2. Generate deterministic request ID
        request_id = generate_platform_request_id(
            platform_req.dataset_id,
            platform_req.resource_id,
            platform_req.version_id,
        )

        # 3. Check idempotent (already submitted?)
        platform_repo = PlatformRepository()
        existing = platform_repo.get_request(request_id)
        if existing:
            return JSONResponse(content={
                "success": True,
                "request_id": request_id,
                "job_id": existing.job_id,
                "message": "Submission already processed for these parameters.",
                "hint": "Use processing_options.overwrite=true to force reprocessing",
            })

        # 4. Asset/Release lifecycle
        asset_service = AssetService()
        asset, asset_op = asset_service.find_or_create_asset(
            platform_id=platform_req.client_id or "ddh",
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            data_type=platform_req.data_type.value,
        )

        overwrite = (platform_req.processing_options or {})
        if isinstance(overwrite, dict):
            overwrite = overwrite.get("overwrite", False)
        else:
            overwrite = getattr(overwrite, "overwrite", False)

        release, release_op = asset_service.get_or_overwrite_release(
            asset_id=asset.asset_id,
            overwrite=bool(overwrite),
            stac_item_id=platform_req.stac_item_id,
            stac_collection_id=f"{platform_req.dataset_id}-{platform_req.resource_id}",
            request_id=request_id,
            suggested_version_id=platform_req.version_id,
            data_type=platform_req.data_type.value,
        )

        # 5. Translate to CoreMachine
        job_type, job_params = translate_to_coremachine(platform_req, config)
        job_params["asset_id"] = asset.asset_id
        job_params["release_id"] = release.release_id

        # 6. Create and submit job
        job_id = create_and_submit_job(job_type, job_params, request_id)

        # 7. Link job to release
        asset_service.link_job_to_release(release.release_id, job_id)

        # 8. Store tracking record
        api_request = ApiRequest(
            request_id=request_id,
            dataset_id=platform_req.dataset_id,
            resource_id=platform_req.resource_id,
            version_id=platform_req.version_id or "",
            job_id=job_id,
            data_type=platform_req.data_type.value,
            asset_id=asset.asset_id,
            platform_id=platform_req.client_id or "ddh",
        )
        platform_repo.create_request(api_request)

        return JSONResponse(
            content={
                "success": True,
                "request_id": request_id,
                "job_id": job_id,
                "job_type": job_type,
                "monitor_url": f"/api/platform/status/{request_id}",
                "message": "Platform request submitted. Job created.",
            },
            status_code=202,
        )

    except ValidationError as e:
        return JSONResponse(content={"error": "Validation failed", "details": e.errors()}, status_code=400)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error(f"Submit failed: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 3: Clean up imports — remove httpx, remove `_get_orchestrator_url()`**

The file no longer needs httpx or the orchestrator URL.

- [ ] **Step 4: Commit**

```bash
git add ui_submit_api.py
git commit -m "refactor: direct service calls for DAG Brain submit/validate endpoints"
```

---

## Task 3: Rewrite Asset Read Endpoints (stats, by-state, detail)

**Files:**
- Modify: `ui_assets_api.py`

- [ ] **Step 1: Rewrite `GET /ui/api/assets/stats`**

```python
from services.asset_approval_service import AssetApprovalService

@router.get("/stats")
async def approval_stats():
    """Get approval state counts."""
    try:
        service = AssetApprovalService()
        stats = service.get_approval_stats()
        total = sum(stats.values())
        return JSONResponse(content={"success": True, "stats": stats, "total": total})
    except Exception as e:
        logger.warning(f"Approval stats failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 2: Rewrite `GET /ui/api/assets/by-state`**

```python
from infrastructure.release_repository import ReleaseRepository

@router.get("/by-state")
async def list_by_state(state: str = "pending_review", limit: int = 100):
    """List releases by approval state."""
    try:
        repo = ReleaseRepository()
        releases = repo.list_by_approval_state(state, limit=limit)
        return JSONResponse(content={
            "success": True,
            "releases": [r.to_dict() for r in releases],
            "count": len(releases),
            "limit": limit,
        })
    except Exception as e:
        logger.warning(f"By-state query failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

Note: Verify `AssetRelease` has a `to_dict()` method. If not, use `dataclasses.asdict()` or build the dict manually matching the existing response shape.

- [ ] **Step 3: Rewrite `GET /ui/api/assets/{asset_id}`**

```python
from infrastructure.asset_repository import AssetRepository
from infrastructure.release_repository import ReleaseRepository

@router.get("/{asset_id}")
async def get_asset(asset_id: str):
    """Get asset with all releases."""
    try:
        asset_repo = AssetRepository()
        asset = asset_repo.get_by_id(asset_id)
        if not asset:
            return JSONResponse(content={"error": "Asset not found"}, status_code=404)

        release_repo = ReleaseRepository()
        releases = release_repo.list_by_asset(asset_id)

        return JSONResponse(content={
            "success": True,
            "asset": asset.to_dict() if hasattr(asset, 'to_dict') else vars(asset),
            "releases": [r.to_dict() for r in releases],
        })
    except Exception as e:
        logger.warning(f"Asset detail failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 4: Commit**

```bash
git add ui_assets_api.py
git commit -m "refactor: direct DB queries for DAG Brain asset read endpoints"
```

---

## Task 4: Rewrite Asset Write Endpoints (approve, reject, revoke)

**Files:**
- Modify: `ui_assets_api.py`

- [ ] **Step 1: Rewrite `POST /ui/api/assets/{asset_id}/approve`**

```python
from services.asset_approval_service import AssetApprovalService

@router.post("/{asset_id}/approve")
async def approve_asset(asset_id: str, request: Request):
    """Approve a release for publication."""
    try:
        body = await request.json()
        service = AssetApprovalService()
        result = service.approve_release(
            release_id=body.get("release_id", asset_id),
            reviewer=body["reviewer"],
            clearance_state=body.get("clearance_state", "ouo"),
            version_id=body.get("version_id"),
            notes=body.get("notes"),
        )
        status = 200 if result.get("success") else 409
        return JSONResponse(content=result, status_code=status)
    except KeyError as e:
        return JSONResponse(content={"error": f"Missing required field: {e}"}, status_code=400)
    except Exception as e:
        logger.warning(f"Approve failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 2: Rewrite `POST /ui/api/assets/{asset_id}/reject`**

```python
@router.post("/{asset_id}/reject")
async def reject_asset(asset_id: str, request: Request):
    """Reject a release."""
    try:
        body = await request.json()
        service = AssetApprovalService()
        result = service.reject_release(
            release_id=body.get("release_id", asset_id),
            reviewer=body["reviewer"],
            reason=body["reason"],
        )
        status = 200 if result.get("success") else 400
        return JSONResponse(content=result, status_code=status)
    except KeyError as e:
        return JSONResponse(content={"error": f"Missing required field: {e}"}, status_code=400)
    except Exception as e:
        logger.warning(f"Reject failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 3: Rewrite `POST /ui/api/assets/{asset_id}/revoke`**

```python
@router.post("/{asset_id}/revoke")
async def revoke_asset(asset_id: str, request: Request):
    """Revoke a previously approved release."""
    try:
        body = await request.json()
        service = AssetApprovalService()
        result = service.revoke_release(
            release_id=body.get("release_id", asset_id),
            revoker=body.get("reviewer", body.get("revoker")),
            reason=body["reason"],
        )
        status = 200 if result.get("success") else 400
        return JSONResponse(content=result, status_code=status)
    except KeyError as e:
        return JSONResponse(content={"error": f"Missing required field: {e}"}, status_code=400)
    except Exception as e:
        logger.warning(f"Revoke failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
```

- [ ] **Step 4: Clean up imports — remove httpx, remove `_get_orchestrator_url()`**

- [ ] **Step 5: Commit**

```bash
git add ui_assets_api.py
git commit -m "refactor: direct service calls for DAG Brain asset approval endpoints"
```

---

## Task 5: Fix Job Resubmit JS Call

**Files:**
- Modify: `templates/pages/jobs/detail.html`

The job detail page has a JS `fetch()` call to `ORCHESTRATOR_URL + '/api/jobs/resubmit/' + jobId`. This should call a local endpoint instead.

- [ ] **Step 1: Check if resubmit is already available locally**

The DAG Brain may already have a `/api/jobs/resubmit/` endpoint registered in `docker_service.py`. If not, the simplest fix is to add a thin route in `ui_routes.py` that calls the job resubmit service directly.

If the job resubmit logic is tightly coupled to the Function App's CoreMachine triggers, an alternative is to write directly to the `app.jobs` table (which DAG Brain already polls).

This task requires investigation at implementation time — the key change is replacing the `ORCHESTRATOR_URL` reference in the JS.

- [ ] **Step 2: Update template to use local URL**

Change:
```javascript
const response = await fetch(ORCHESTRATOR_URL + '/api/jobs/resubmit/' + jobId, {
```

To:
```javascript
const response = await fetch('/ui/api/jobs/resubmit/' + jobId, {
```

Or remove `ORCHESTRATOR_URL` entirely if all calls are now local.

- [ ] **Step 3: Commit**

```bash
git add templates/pages/jobs/detail.html
git commit -m "fix: job resubmit calls local endpoint instead of orchestrator"
```

---

## Task 6: Cleanup and Verification

- [ ] **Step 1: Remove `ORCHESTRATOR_URL` from environment requirements**

Check `docker_service.py` for any startup validation that requires `ORCHESTRATOR_URL`. It may no longer be needed (or only needed for specific cross-app scenarios). Do NOT remove the env var itself — just ensure the UI doesn't fail if it's unset.

- [ ] **Step 2: Verify all `/ui/api/*` endpoints work without `ORCHESTRATOR_URL`**

```bash
# In Docker container or local test:
unset ORCHESTRATOR_URL
# Hit each endpoint and confirm no 502/proxy errors
```

- [ ] **Step 3: Update docstrings**

Update module docstrings in `ui_submit_api.py` and `ui_assets_api.py` to reflect direct service calls instead of proxy pattern.

- [ ] **Step 4: Final commit**

```bash
git add ui_submit_api.py ui_assets_api.py
git commit -m "chore: remove proxy pattern remnants from DAG Brain UI"
```

---

## Notes

### Response Shape Compatibility
The templates (`assets.html`, `asset_detail.html`, `submit.html`) parse specific JSON shapes from the `/ui/api/*` responses. The direct service calls must return the **same JSON shape** as the proxy was returning. Check each template's JS for the expected fields before finalizing.

### What This Does NOT Change
- Function App `web_interfaces/` — these are API test harnesses, loopback by design
- Function App `api/platform/submit` — still exists as the external API
- DAG Brain polling loop — unaffected, reads same state tables
- Worker behaviour — unaffected

### Serialization
`AssetRelease` and `Asset` models need to be serializable to JSON for the response. Check if they have `to_dict()`, `__dict__`, or need manual dict building. If they're dataclasses, `dataclasses.asdict()` works. If they're Pydantic, `.model_dump()` works.
