# DAG Brain Assets Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-level asset management UI to the DAG Brain: an asset registry summary page and an asset detail page with approval/reject/revoke admin actions.

**Architecture:** Same proxy pattern as the submit page. The DAG Brain proxies asset API calls to the Function App via `ORCHESTRATOR_URL`. Two pages: `/ui/assets` (registry) and `/ui/assets/{asset_id}` (detail with admin actions). All data comes from the Function App's existing `/api/assets/` endpoints.

**Tech Stack:** FastAPI routes, Jinja2 templates, vanilla JS fetch(), httpx for proxying

---

## API Endpoints on Function App (to be proxied)

| Endpoint | Response Shape | Purpose |
|----------|---------------|---------|
| `GET /api/assets/approval-stats` | `{"stats": {"pending_review": 5, "approved": 100, ...}, "total": 108}` | Counts for stats banner |
| `GET /api/assets/by-approval-state?state=X&limit=100` | `{"releases": [...], "count": N}` | List releases by state |
| `GET /api/assets/{asset_id}/approval` | `{"asset": {...}, "releases": [...], "primary_release": {...}}` | Single asset + all releases |
| `POST /api/assets/{asset_id}/approve` | `{"success": true, "action": "approved_ouo"}` | Body: `{"reviewer": "...", "clearance_state": "ouo\|public", "notes": "..."}` |
| `POST /api/assets/{asset_id}/reject` | `{"success": true, "action": "rejected"}` | Body: `{"reviewer": "...", "reason": "..."}` |
| `POST /api/assets/{asset_id}/revoke` | `{"success": true, "action": "revoked"}` | Body: `{"reviewer": "...", "reason": "..."}` |

## File Structure

```
ui_assets_api.py                         # NEW — proxy API router for asset endpoints
templates/pages/assets.html              # NEW — asset registry summary page
templates/pages/asset_detail.html        # NEW — single asset detail + admin actions
ui_routes.py                             # MODIFY — add /ui/assets and /ui/assets/{id} routes
docker_service.py                        # MODIFY — mount assets API router
```

---

## Task 1: Create Assets Proxy API Router

**Files:**
- Create: `ui_assets_api.py`

Proxy endpoints for the asset APIs. Same pattern as `ui_submit_api.py`.

- [ ] **Step 1: Create ui_assets_api.py**

```python
"""
Assets Proxy API for DAG Brain Admin UI.

Proxies asset management calls to the Function App (orchestrator).

Endpoints:
    GET  /ui/api/assets/stats              - Approval state counts
    GET  /ui/api/assets/by-state           - List releases by approval state
    GET  /ui/api/assets/{asset_id}         - Single asset with releases
    POST /ui/api/assets/{asset_id}/approve - Approve a release
    POST /ui/api/assets/{asset_id}/reject  - Reject a release
    POST /ui/api/assets/{asset_id}/revoke  - Revoke an approval
"""
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api/assets", tags=["assets-proxy"])

PROXY_TIMEOUT = 30.0


def _get_orchestrator_url() -> str:
    url = os.environ.get("ORCHESTRATOR_URL", "").rstrip("/")
    if not url:
        raise ValueError("ORCHESTRATOR_URL not set")
    return url


@router.get("/stats")
async def approval_stats():
    """Proxy GET /api/assets/approval-stats."""
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(f"{orch_url}/api/assets/approval-stats")
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Assets stats proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/by-state")
async def list_by_state(state: str = "pending_review", limit: int = 100):
    """Proxy GET /api/assets/by-approval-state?state=X."""
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(
                f"{orch_url}/api/assets/by-approval-state",
                params={"state": state, "limit": limit},
            )
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.warning(f"Assets by-state proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/{asset_id}")
async def get_asset(asset_id: str):
    """Proxy GET /api/assets/{asset_id}/approval."""
    try:
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.get(f"{orch_url}/api/assets/{asset_id}/approval")
            resp.raise_for_status()
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            content=e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {"error": str(e)},
            status_code=e.response.status_code,
        )
    except Exception as e:
        logger.warning(f"Asset detail proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/{asset_id}/approve")
async def approve_asset(asset_id: str, request: Request):
    """Proxy POST /api/assets/{asset_id}/approve."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(
                f"{orch_url}/api/assets/{asset_id}/approve",
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        return JSONResponse(content=e.response.json(), status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Approve proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/{asset_id}/reject")
async def reject_asset(asset_id: str, request: Request):
    """Proxy POST /api/assets/{asset_id}/reject."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(
                f"{orch_url}/api/assets/{asset_id}/reject",
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        return JSONResponse(content=e.response.json(), status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Reject proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.post("/{asset_id}/revoke")
async def revoke_asset(asset_id: str, request: Request):
    """Proxy POST /api/assets/{asset_id}/revoke."""
    try:
        body = await request.json()
        orch_url = _get_orchestrator_url()
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as client:
            resp = await client.post(
                f"{orch_url}/api/assets/{asset_id}/revoke",
                json=body,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.HTTPStatusError as e:
        return JSONResponse(content=e.response.json(), status_code=e.response.status_code)
    except Exception as e:
        logger.warning(f"Revoke proxy failed: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=502)
```

- [ ] **Step 2: Commit**

```bash
git add ui_assets_api.py
git commit -m "feat(ui): add assets proxy API router for DAG Brain"
```

---

## Task 2: Create Asset Registry Template

**Files:**
- Create: `templates/pages/assets.html`

The asset registry landing page. Shows:
- Stats banner: pending, approved, rejected, revoked counts
- Filter tabs: All, Pending Review, Approved, Rejected, Revoked
- Asset table: each row = one release, grouped visually by asset_id
- Columns: Asset ID (truncated), Dataset/Resource, Data Type, Version, Status badges (processing, approval, clearance), Date
- Click row → navigate to `/ui/assets/{asset_id}`
- Search/filter input

- [ ] **Step 1: Create templates/pages/assets.html**

The template should implement:

**Stats Banner:**
- Loaded on page init via `fetch('/ui/api/assets/stats')`
- 4 stat cards: Pending Review (amber), Approved (green), Rejected (red), Revoked (gray)
- Total count

**Filter Tabs:**
- "All" (default), "Pending Review", "Approved", "Rejected", "Revoked"
- Clicking a tab calls `fetch('/ui/api/assets/by-state?state=X&limit=200')`
- "All" loads all states in parallel

**Release Table:**
- Columns: Asset ID (first 16 chars, monospace), Dataset ID, Data Type, Version (ordinal), Processing, Approval, Clearance, Created
- Each row clickable → `window.location = '/ui/assets/' + asset_id`
- Status badges using existing CSS classes from styles.css:
  - Processing: `processing`, `completed`, `failed`
  - Approval: `pending_review`, `approved`, `rejected`, `revoked`
  - Clearance: `uncleared`, `ouo`, `public`

**Search:**
- Client-side filter on asset_id, dataset_id, stac_collection_id
- Debounced input

**Release object fields** (from API response):
```json
{
  "release_id": "...",
  "asset_id": "...",
  "version_ordinal": 1,
  "version_id": "v1",
  "data_type": "raster",
  "processing_status": "completed",
  "approval_state": "pending_review",
  "clearance_state": "uncleared",
  "blob_path": "...",
  "table_name": "...",
  "stac_collection_id": "...",
  "stac_item_id": "...",
  "job_id": "...",
  "created_at": "...",
  "updated_at": "..."
}
```

- [ ] **Step 2: Commit**

```bash
git add templates/pages/assets.html
git commit -m "feat(ui): add asset registry summary page template"
```

---

## Task 3: Create Asset Detail Template

**Files:**
- Create: `templates/pages/asset_detail.html`

Detailed view for a single asset with all its releases and admin action buttons.

- [ ] **Step 1: Create templates/pages/asset_detail.html**

The template receives `asset_id` from the URL (passed via route context). On load, it fetches `/ui/api/assets/{asset_id}`.

**Asset Header:**
- Asset ID (full, monospace)
- Dataset ID, Resource ID, Data Type
- Total release count
- Primary release badge (latest or draft)

**Releases Table:**
- One row per release, newest first (by `version_ordinal` DESC)
- Columns: Version (ordinal + version_id), Processing Status, Approval State, Clearance, Created, Actions
- Expandable row detail (click to toggle):
  - blob_path or table_name
  - stac_collection_id, stac_item_id
  - job_id (link to `/ui/jobs/{job_id}`)
  - reviewer, review_notes, reviewed_at (if approved/rejected)
  - Full timestamps

**Admin Action Buttons** (context-aware per release state):

| Current State | Available Actions |
|--------------|-------------------|
| `pending_review` + `processing=completed` | Approve, Reject |
| `approved` | Revoke |
| `rejected` | (none — resubmit via Platform API) |
| `revoked` | (none) |
| `processing != completed` | (none — wait for processing) |

**Approve Modal:**
- Reviewer email (required)
- Clearance state: radio buttons — "Official Use Only (OUO)" or "Public"
- Notes (optional textarea)
- Confirm button → `POST /ui/api/assets/{asset_id}/approve` with `{"reviewer": "...", "clearance_state": "ouo|public", "notes": "..."}`
- Show result (success/error)

**Reject Modal:**
- Reviewer email (required)
- Reason (required textarea)
- Confirm button → `POST /ui/api/assets/{asset_id}/reject` with `{"reviewer": "...", "reason": "..."}`

**Revoke Modal:**
- Reviewer email (required)
- Reason (required textarea)
- Confirm button → `POST /ui/api/assets/{asset_id}/revoke` with `{"reviewer": "...", "reason": "..."}`

**After any action succeeds:** Reload the asset data to reflect new state.

**Back link:** "← Back to Asset Registry" → `/ui/assets`

- [ ] **Step 2: Commit**

```bash
git add templates/pages/asset_detail.html
git commit -m "feat(ui): add asset detail page with approval actions"
```

---

## Task 4: Add Routes and Mount Router

**Files:**
- Modify: `ui_routes.py` — add `/ui/assets` and `/ui/assets/{asset_id}` routes
- Modify: `docker_service.py` — mount `ui_assets_api.router`
- Modify: `.funcignore` — add `ui_assets_api.py`

- [ ] **Step 1: Add asset routes to ui_routes.py**

Add after the submit route:

```python
@router.get("/assets", response_class=HTMLResponse)
async def assets_page(request: Request):
    """Asset registry — summary of all assets with approval states."""
    return render_template(
        request,
        "pages/assets.html",
        nav_active="/ui/assets",
    )


@router.get("/assets/{asset_id}", response_class=HTMLResponse)
async def asset_detail_page(request: Request, asset_id: str):
    """Asset detail — release history with admin actions."""
    return render_template(
        request,
        "pages/asset_detail.html",
        asset_id=asset_id,
        nav_active="/ui/assets",
    )
```

**IMPORTANT:** The `/assets/{asset_id}` route MUST come after `/assets` to avoid the path parameter swallowing "stats" or "by-state" from the API router. Since `ui_routes.py` uses prefix `/ui` and `ui_assets_api.py` uses prefix `/ui/api/assets`, they won't conflict — but verify the route order.

- [ ] **Step 2: Mount assets API router in docker_service.py**

In the `APP_MODE=orchestrator` block, after the submit API router mount:

```python
    try:
        from ui_assets_api import router as assets_api_router
        app.include_router(assets_api_router)
        logger.info("Mounted /ui/api/assets/ proxy routes")
    except Exception as e:
        logger.warning(f"Assets proxy routes failed to mount: {e}")
```

- [ ] **Step 3: Add Assets nav item**

Check `ui/navigation.py` for an existing assets nav item. If missing, add:

```python
NavItem(
    path="/ui/assets",
    label="Assets",
    icon="box",
    section="jobs",
),
```

- [ ] **Step 4: Update .funcignore**

Add `ui_assets_api.py` to the exclusion list.

- [ ] **Step 5: Commit**

```bash
git add ui_routes.py docker_service.py ui/navigation.py .funcignore
git commit -m "feat(ui): wire asset routes and mount assets proxy API"
```

---

## Task 5: Generate Local Preview

**Files:** None (verification only)

- [ ] **Step 1: Render preview**

```bash
/Users/robertharrison/anaconda3/envs/azgeo/bin/python -c "
from jinja2 import Environment, FileSystemLoader
import os, shutil

env = Environment(loader=FileSystemLoader('templates'))
preview_dir = '/tmp/dag-brain-preview'
os.makedirs(preview_dir, exist_ok=True)
shutil.copytree('static', f'{preview_dir}/static', dirs_exist_ok=True)

# Mock context
ctx = {
    'version': '0.10.5.5',
    'terms': type('T', (), {'mode_display': 'DAG Orchestrator'})(),
    'features': {},
    'nav_items': [],
    'nav_sections': {
        'main': [type('N', (), {'path': '/ui/', 'label': 'Dashboard', 'icon': 'home', 'badge': None})()],
        'data': [type('N', (), {'path': '/ui/submit', 'label': 'Submit', 'icon': 'upload', 'badge': None})()],
        'jobs': [
            type('N', (), {'path': '/ui/jobs', 'label': 'Jobs', 'icon': 'list', 'badge': None})(),
            type('N', (), {'path': '/ui/assets', 'label': 'Assets', 'icon': 'box', 'badge': None})(),
        ],
        'admin': [type('N', (), {'path': '/ui/handlers', 'label': 'Handlers', 'icon': 'cpu', 'badge': None})()],
    },
    'nav_active': '/ui/assets',
}

for name, tpl, extra in [
    ('assets', 'pages/assets.html', {}),
    ('asset_detail', 'pages/asset_detail.html', {'asset_id': 'abc123def456'}),
]:
    c = dict(ctx)
    c.update(extra)
    c['nav_active'] = '/ui/assets'
    html = env.get_template(tpl).render(**c)
    html = html.replace('href=\"/static/', f'href=\"file://{preview_dir}/static/')
    html = html.replace('src=\"/static/', f'src=\"file://{preview_dir}/static/')
    with open(f'{preview_dir}/{name}.html', 'w') as f:
        f.write(html)
    print(f'  {name}.html')

print(f'Preview: file://{preview_dir}/assets.html')
"
```

- [ ] **Step 2: Open in browser and review**

```bash
open file:///tmp/dag-brain-preview/assets.html
```

---

## Task 6: Deploy and Verify

**Files:** None (deployment + verification)

- [ ] **Step 1: Deploy DAG Brain**

```bash
./deploy.sh dagbrain
```

- [ ] **Step 2: Verify pages**

```bash
# Assets registry page
curl -s https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/assets | grep "Asset Registry"

# Assets proxy - stats
curl -s https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/api/assets/stats

# Assets proxy - by state
curl -s "https://rmhdagmaster-gcfzd5bqfxc7g7cv.eastus-01.azurewebsites.net/ui/api/assets/by-state?state=approved&limit=5"
```

---

## Scope Boundaries

**In scope:**
- Asset registry summary page (stats + filtered release table)
- Asset detail page (release history + expandable rows)
- Approve/Reject/Revoke admin actions with confirmation modals
- Proxy API endpoints for all asset operations
- Context-aware action buttons (only show valid transitions)

**Out of scope (future):**
- Bulk approve/reject (multiple assets at once)
- Approval audit log / history timeline
- Asset comparison (diff between versions)
- Raster/vector preview links (needs TiTiler/TiPG proxy)
- STAC catalog links
