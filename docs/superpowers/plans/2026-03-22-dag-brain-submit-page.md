# DAG Brain Submit Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified submit page to the DAG Brain admin UI that supports raster (single + collection) and vector submissions with validation-first workflow.

**Architecture:** The submit page lives in the DAG Brain Docker app (`APP_MODE=orchestrator`). It uses Jinja2 templates with HTMX for progressive disclosure. The DAG Brain doesn't have direct access to blob storage or the Platform API — it proxies these calls to the Function App (orchestrator) via `ORCHESTRATOR_URL` env var. Server-side FastAPI routes handle the proxying; the template never calls external APIs directly from JS.

**Tech Stack:** FastAPI routes, Jinja2 templates, HTMX 1.9.10, vanilla JS, Python `httpx` for proxying to Platform API

---

## Architecture: Proxy Pattern

The Function App (`rmhazuregeoapi`, APP_MODE=standalone) owns:
- `POST /api/platform/submit` — job submission + dry_run validation
- Blob storage access via `BlobRepository`

The DAG Brain (`rmhdagmaster`, APP_MODE=orchestrator) proxies via:
- `GET /ui/submit` — renders the submit page
- `GET /ui/api/containers?zone=bronze` — proxies container listing
- `GET /ui/api/files?zone=...&container=...&data_type=...` — proxies file listing
- `POST /ui/api/validate` — proxies dry_run validation
- `POST /ui/api/submit` — proxies actual submission

The `ORCHESTRATOR_URL` env var (e.g., `https://rmhazuregeoapi-....azurewebsites.net`) is used to construct proxy URLs. This must be set on the `rmhdagmaster` app before deployment.

## File Structure

```
templates/pages/submit.html              # NEW — unified submit page template
ui_routes.py                             # MODIFY — add submit page route
ui_submit_api.py                         # NEW — FastAPI router for submit proxy API endpoints
docker_service.py                        # MODIFY — mount submit API router
ui/navigation.py                         # VERIFY — Submit nav item should already exist
```

---

## Task 1: Set ORCHESTRATOR_URL on DAG Brain App

**Files:** None (Azure config only)

- [ ] **Step 1: Set the env var**

```bash
az webapp config appsettings set \
  --name rmhdagmaster \
  --resource-group rmhazure_rg \
  --settings ORCHESTRATOR_URL=https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net
```

- [ ] **Step 2: Verify**

```bash
az webapp config appsettings list --name rmhdagmaster --resource-group rmhazure_rg \
  --query "[?name=='ORCHESTRATOR_URL'].value" -o tsv
```

Expected: `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net`

---

## Task 2: Create Submit Proxy API Router

**Files:**
- Create: `ui_submit_api.py`

This router provides API endpoints that the submit page's HTMX calls. Each endpoint proxies to the Function App's Platform API or storage API.

- [ ] **Step 1: Create ui_submit_api.py**

```python
"""
Submit Proxy API for DAG Brain Admin UI.

Proxies storage browsing and Platform API calls to the Function App (orchestrator).
The DAG Brain doesn't have direct blob access — it delegates to the orchestrator.

Endpoints:
    GET  /ui/api/containers   — List bronze containers (proxied)
    GET  /ui/api/files        — List files in container (proxied)
    POST /ui/api/validate     — dry_run validation via Platform API
    POST /ui/api/submit       — Job submission via Platform API
"""
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, HTMLResponse
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["submit-proxy"])

PROXY_TIMEOUT = 30.0


def _get_orchestrator_url() -> str:
    """Get orchestrator URL, raising if not configured."""
    url = os.environ.get("ORCHESTRATOR_URL", "").rstrip("/")
    if not url:
        raise ValueError("ORCHESTRATOR_URL not set — cannot proxy to orchestrator")
    return url


@router.get("/containers")
async def list_containers(zone: str = "bronze"):
    """
    Proxy container listing from orchestrator's storage API.

    Orchestrator endpoint: GET /api/storage/containers?zone=bronze
    Response shape: {"zone": "bronze", "containers": [{"name": "wargames", ...}, ...]}
    We extract the containers array and return it.
    """
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(
                f"{orch_url}/api/storage/containers",
                params={"zone": zone},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            content={"error": f"Orchestrator returned {e.response.status_code}"},
            status_code=502,
        )
    except Exception as e:
        logger.warning(f"Container proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/files")
async def list_files(
    zone: str = "bronze",
    container: str = "",
    prefix: str = "",
    data_type: str = "raster",
    limit: int = 250,
):
    """
    Proxy file listing from orchestrator's storage API, filtered by data type.

    The orchestrator endpoint is: GET /api/storage/{container_name}/blobs
    Query params: zone, prefix, suffix, limit
    Response: {"blobs": [{"name": "...", "size": 12345, "last_modified": "..."}, ...]}
    """
    if not container:
        return JSONResponse(content={"error": "container required"}, status_code=400)

    raster_exts = {'.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5'}
    vector_exts = {'.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip'}
    exts = vector_exts if data_type == "vector" else raster_exts

    try:
        orch_url = _get_orchestrator_url()
        # The actual endpoint is /api/storage/{container}/blobs (NOT /api/storage/files)
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(
                f"{orch_url}/api/storage/{container}/blobs",
                params={"zone": zone, "prefix": prefix, "limit": limit * 2},
            )
            resp.raise_for_status()
            data = resp.json()

        # Response shape: {"blobs": [...]} or list directly
        blobs = data.get("blobs", data) if isinstance(data, dict) else data
        if not isinstance(blobs, list):
            blobs = []

        # Filter by extension
        filtered = []
        for blob in blobs:
            name = (blob.get("name") or "").lower()
            if any(name.endswith(ext) for ext in exts):
                filtered.append(blob)
                if len(filtered) >= limit:
                    break

        return JSONResponse(content={"files": filtered})
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            content={"error": f"Orchestrator returned {e.response.status_code}"},
            status_code=502,
        )
    except Exception as e:
        logger.warning(f"Files proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/validate")
async def validate_submission(request: Request):
    """Proxy dry_run validation to Platform API."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()

        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(
                f"{orch_url}/api/platform/submit",
                params={"dry_run": "true"},
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Validate proxy failed: {e}")
        return JSONResponse(
            content={"error": str(e), "validation": {"valid": False, "warnings": [str(e)]}},
            status_code=502,
        )


@router.post("/submit")
async def submit_job(request: Request):
    """Proxy job submission to Platform API."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{orch_url}/api/platform/submit",
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Submit proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)
```

- [ ] **Step 2: Verify httpx is available**

```bash
/Users/robertharrison/anaconda3/envs/azgeo/bin/python -c "import httpx; print('httpx OK')"
```

If not installed, add `httpx` to `requirements-docker.txt`. httpx is already commonly used in FastAPI projects for async HTTP. Check:
```bash
grep httpx requirements-docker.txt
```

If missing, add it.

- [ ] **Step 3: Commit**

```bash
git add ui_submit_api.py
git commit -m "feat(ui): add submit proxy API router for DAG Brain"
```

---

## Task 3: Create Submit Page Template

**Files:**
- Create: `templates/pages/submit.html`

This is a Jinja2 template implementing the 3-step submit workflow: data type selection → file browser → configure & submit. Uses HTMX for dynamic file loading and vanilla JS for form state.

- [ ] **Step 1: Create templates/pages/submit.html**

The template should implement:

**Step 1 — Data Type Selection:**
- Radio buttons: Single Raster, Raster Collection, Vector
- On change, updates file browser filter and shows/hides type-specific options

**Step 2 — File Browser:**
- Zone dropdown (fixed to "bronze")
- Container dropdown (loaded via fetch to `/ui/api/containers?zone=bronze`)
- Prefix filter input
- "Load Files" button
- File table (loaded via fetch to `/ui/api/files?...`)
- Single-select (click row) for raster/vector; multi-select (checkboxes) for collection

**Step 3 — Configuration Form (revealed after file selection):**
- DDH identifiers: dataset_id (required), resource_id (required), version_id (optional)
- Raster options: raster_type dropdown, output_tier dropdown, input_crs
- Vector options: table_name, layer_name, lat_name, lon_name, wkt_column (shown for CSV)
- Collection options: jpeg_quality, license, strict_mode
- Overwrite checkbox
- "Validate" button → calls `/ui/api/validate` → shows result
- "Submit Job" button (enabled after validation passes) → calls `/ui/api/submit`

**Key patterns:**
- All API calls use `fetch()` to `/ui/api/...` endpoints (same-origin, no CORS)
- Results rendered client-side in JS (not HTMX fragments — simpler for the DAG Brain)
- Form state managed via JS (hidden inputs for blob_name, blob_list, container_name)
- Progressive disclosure: config form hidden until file selected
- Validation result shown in-page (green success / red error)
- After submit success, show job_id with link to `/ui/jobs/{job_id}`

**File extension filtering:** Handled server-side by `/ui/api/files?data_type=raster|vector`. The template does NOT need client-side extension lists — the proxy filters before returning results.

**Platform API payload shape** (sent to `/ui/api/validate` and `/ui/api/submit`):
```json
{
  "dataset_id": "string",
  "resource_id": "string",
  "version_id": "string|null",
  "container_name": "string",
  "file_name": "string|array",
  "processing_options": {
    "overwrite": true,
    "raster_type": "auto",
    "output_tier": "analysis",
    "crs": "EPSG:4326",
    "lat_column": "lat",
    "lon_column": "lon",
    "collection_id": "my-collection"
  }
}
```

**Raster type options:**
auto-detect, dem, rgb, rgba, multispectral, categorical, nir, continuous, vegetation_index, flood_depth, flood_probability, hydrology, temporal, population

**Output tier options:**
analysis (default), visualization, archive, all

- [ ] **Step 2: Commit**

```bash
git add templates/pages/submit.html
git commit -m "feat(ui): add unified submit page template"
```

---

## Task 4: Add Submit Route and Mount Proxy Router

**Files:**
- Modify: `ui_routes.py` — add `/ui/submit` route
- Modify: `docker_service.py` — mount `ui_submit_api.router`

- [ ] **Step 1: Add submit route to ui_routes.py**

Add this route to `ui_routes.py`:

```python
@router.get("/submit", response_class=HTMLResponse)
async def submit_page(request: Request):
    """Unified submit page for raster and vector data."""
    return render_template(
        request,
        "pages/submit.html",
        nav_active="/ui/submit",
    )
```

- [ ] **Step 2: Mount submit API router in docker_service.py**

In the `APP_MODE=orchestrator` block in `docker_service.py` (around line 1084), after the `ui_router` include, add:

```python
    try:
        from ui_submit_api import router as submit_api_router
        app.include_router(submit_api_router)
        logger.info("Mounted /ui/api/ submit proxy routes")
    except Exception as e:
        logger.warning(f"Submit proxy routes failed to mount: {e}")
```

- [ ] **Step 3: Verify Submit nav item exists**

The Submit nav item should already exist in `ui/navigation.py` (added during the initial UI setup). Verify:
```bash
grep -n "submit" ui/navigation.py
```
If it's missing, add it to the "data" section. If it's there, skip this step.

- [ ] **Step 4: Commit**

```bash
git add ui_routes.py docker_service.py ui/navigation.py
git commit -m "feat(ui): wire submit page route and proxy API"
```

---

## Task 5: Add .funcignore Entry and Verify httpx Dependency

**Files:**
- Modify: `.funcignore` — add `ui_submit_api.py`
- Modify: `requirements-docker.txt` — add `httpx` if missing

- [ ] **Step 1: Update .funcignore**

Add `ui_submit_api.py` to the exclusion list (under the existing UI section):

```
ui_submit_api.py
```

- [ ] **Step 2: Ensure httpx in requirements-docker.txt**

```bash
grep -q httpx requirements-docker.txt || echo "httpx>=0.27.0" >> requirements-docker.txt
```

- [ ] **Step 3: Commit**

```bash
git add .funcignore requirements-docker.txt
git commit -m "chore: add httpx dependency and funcignore for submit proxy"
```

---

## Task 6: Deploy and Verify

**Files:** None (deployment + verification)

- [ ] **Step 1: Deploy DAG Brain**

```bash
./deploy.sh dagbrain
```

- [ ] **Step 2: Verify submit page renders**

```bash
curl -s https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/submit | grep "Submit Data"
```

- [ ] **Step 3: Verify proxy endpoints**

```bash
# Container listing
curl -s https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/api/containers?zone=bronze

# File listing (should return files from orchestrator's bronze storage)
curl -s "https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/api/files?zone=bronze&container=wargames&data_type=raster&limit=5"
```

- [ ] **Step 4: Test full validation workflow in browser**

Open: `https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/submit`

1. Select "Single Raster"
2. Click "Load Files" (should show files from bronze storage)
3. Click a file row
4. Fill dataset_id and resource_id
5. Click "Validate" — should show green or red result
6. If valid, click "Submit" — should show job_id

---

## Scope Boundaries

**In scope:**
- Unified submit page (raster single, raster collection, vector)
- Proxy API endpoints (containers, files, validate, submit)
- Progressive disclosure (type → files → config → validate → submit)
- File extension filtering
- DDH identifier fields + processing options
- Validation-first workflow (dry_run before submit)

**Out of scope (future):**
- File upload to bronze (separate page — needs multipart proxy)
- WebSocket progress tracking during submission
- Saved/recent submissions history
- Template/preset configurations
- Advanced raster tiling options
