# DAG Brain Admin UI — Merge Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an admin UI in the DAG Brain Docker app (`APP_MODE=orchestrator`) by merging the best patterns from three existing UI codebases.

**Architecture:** FastAPI + Jinja2 templates + HTMX, gated on `APP_MODE=orchestrator`. The UI module (`ui/`) from DAG Master provides the abstraction layer (DTOs, adapters, terminology, features, navigation). The archived Docker UI (`archive/docker_ui/`) provides battle-tested Jinja2 templates, macros, CSS, and JS. Routes are mounted as a FastAPI APIRouter under `/ui/` prefix, with static files at `/static/`.

**Tech Stack:** FastAPI, Jinja2, HTMX 1.9.10, vanilla JS, CSS custom properties, Feather Icons

---

## Source Material Reference

| Source | Location | What we take |
|--------|----------|-------------|
| DAG Master | `/Users/robertharrison/python_builds/rmhdagmaster/ui/` | `dto.py`, `adapters/`, `terminology.py`, `features.py`, `navigation.py` |
| Archived Docker UI | `archive/docker_ui/` | `templates/`, `static/`, `ui/templates.py`, macros, page templates |
| Function App | `web_interfaces/` | CSS design tokens (color vars), HTMX patterns — leave in place, don't modify |

## File Structure

```
ui/                                    # NEW — UI abstraction layer (from DAG Master)
├── __init__.py                        # Module exports
├── dto.py                             # DTOs: JobDTO, NodeDTO, TaskDTO, AssetDTO, etc.
├── adapters/
│   ├── __init__.py                    # Auto-detection router (Epoch4 vs DAG)
│   ├── epoch4.py                      # Epoch 4 model → DTO conversion
│   └── dag.py                         # DAG model → DTO stubs (future)
├── terminology.py                     # Terms: Stage/Node, Job Type/Workflow
├── features.py                        # Feature flags with mode-aware gating
├── navigation.py                      # NavItem definitions, mode-based filtering
└── templates_helper.py                # Jinja2Templates instance + render helpers

templates/                             # NEW — Jinja2 templates (from archived Docker UI)
├── base.html                          # Root layout: navbar + content + footer + HTMX
├── components/
│   ├── navbar.html                    # Sidebar navigation (section-grouped)
│   ├── footer.html                    # Page footer
│   ├── macros.html                    # UI macros: status_badge, card, modal, etc.
│   └── form_macros.html              # Form macros: text_input, select, file_source
├── pages/
│   ├── dashboard.html                 # Admin dashboard (job stats, health summary)
│   ├── jobs/
│   │   ├── list.html                  # Job list with HTMX auto-refresh
│   │   └── detail.html                # Job detail with task breakdown
│   ├── admin/
│   │   └── health.html                # Cross-system health dashboard
│   └── handlers.html                  # Handler registry browser (NEW)

static/                                # NEW — CSS and JS assets
├── css/
│   └── styles.css                     # Design system (from archived, updated tokens)
├── js/
│   ├── common.js                      # Shared utilities (from archived)
│   └── app.js                         # Page-specific behaviors

ui_routes.py                           # NEW — FastAPI APIRouter with UI page routes
```

**Files modified:**
- `docker_service.py` — Mount UI router and static files when `APP_MODE=orchestrator`

**Files NOT modified:**
- `web_interfaces/` — Leave the Function App UI untouched
- `function_app.py` — No changes to the Function App

---

## Task 1: Copy DAG Master UI Abstraction Layer

**Files:**
- Create: `ui/__init__.py`
- Create: `ui/dto.py`
- Create: `ui/adapters/__init__.py`
- Create: `ui/adapters/epoch4.py`
- Create: `ui/adapters/dag.py`
- Create: `ui/terminology.py`
- Create: `ui/features.py`
- Create: `ui/navigation.py`

These files are copied from `/Users/robertharrison/python_builds/rmhdagmaster/ui/` with targeted adaptations for the rmhgeoapi codebase.

- [ ] **Step 1: Copy dto.py from DAG Master**

Copy `/Users/robertharrison/python_builds/rmhdagmaster/ui/dto.py` to `ui/dto.py`. No changes needed — DTOs are codebase-agnostic Pydantic models.

- [ ] **Step 2: Copy terminology.py from DAG Master**

Copy `/Users/robertharrison/python_builds/rmhdagmaster/ui/terminology.py` to `ui/terminology.py`. Change mode detection to use `APP_MODE` instead of `UI_MODE`/`DAG_ENABLED`:

```python
def get_current_mode() -> str:
    app_mode = os.environ.get("APP_MODE", "").lower()
    if app_mode == "orchestrator":
        return "dag"
    return "epoch4"
```

- [ ] **Step 3: Copy features.py from DAG Master**

Copy `/Users/robertharrison/python_builds/rmhdagmaster/ui/features.py` to `ui/features.py`. Same mode detection change as terminology.py.

- [ ] **Step 4: Copy navigation.py from DAG Master**

Copy `/Users/robertharrison/python_builds/rmhdagmaster/ui/navigation.py` to `ui/navigation.py`. Update:
1. Same mode detection change (use `APP_MODE`)
2. Update nav paths from `/interface/` to `/ui/` (the DAG Brain URL prefix)
3. Remove items that don't apply yet (queues — SB is being removed, external-services)
4. Add new items: Handlers (`/ui/handlers`), Scheduler (`/ui/scheduler`)

- [ ] **Step 5: Copy adapters package**

Copy `/Users/robertharrison/python_builds/rmhdagmaster/ui/adapters/__init__.py`, `epoch4.py`, and `dag.py` to `ui/adapters/`. The epoch4 adapter uses `Any` typing and `getattr`/`hasattr` throughout — it has **no host-project model imports** by design. No import path changes should be needed. The DAG adapter (`dag.py`) is a stub that raises `NotImplementedError`.

- [ ] **Step 6: Create ui/__init__.py**

Copy from DAG Master, verify all imports resolve against the files created in steps 1-5. Add `get_nav_sections` to the navigation exports (DAG Master's `__init__.py` only exports `get_nav_items` and `get_nav_items_for_mode`, but `templates_helper.py` needs `get_nav_sections` too):

```python
# Navigation
from .navigation import (
    NavItem,
    get_nav_items,
    get_nav_items_for_mode,
    get_nav_sections,    # needed by templates_helper.py
)
```

- [ ] **Step 7: Verify imports**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "from ui.dto import JobDTO, NodeDTO, TaskDTO; print('DTOs OK')"
python -c "from ui.terminology import get_terms; print(get_terms()); print('Terms OK')"
python -c "from ui.features import is_enabled, get_enabled_features; print('Features OK')"
python -c "from ui.navigation import get_nav_items; print(f'{len(get_nav_items())} nav items'); print('Nav OK')"
```

Expected: All 4 print OK. Adapters should also work (they use `Any` typing, no host-project imports).

- [ ] **Step 8: Commit**

```bash
git add ui/
git commit -m "feat(ui): copy DAG Master abstraction layer (DTOs, adapters, terminology, features, navigation)"
```

---

## Task 2: Verify Adapter Imports

**Files:**
- Verify: `ui/adapters/epoch4.py`
- Verify: `ui/adapters/__init__.py`

The DAG Master epoch4 adapter uses `Any` typing and `getattr`/`hasattr` throughout — it has **zero host-project model imports**. This is by design (the adapter pattern). No import fixes should be needed; this task is verification only.

- [ ] **Step 1: Verify adapter import chain**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo
python -c "from ui.adapters import job_to_dto, task_to_dto, asset_to_dto; print('Adapters OK')"
python -c "from ui.adapters import DAG_AVAILABLE; print(f'DAG_AVAILABLE={DAG_AVAILABLE}')"
```

Expected: `Adapters OK` and `DAG_AVAILABLE=False` (DAG adapter stubs raise `NotImplementedError`).

If any import fails, inspect the specific error. The epoch4 adapter should only import from `ui.dto` — if it accidentally imports host-project models, remove those imports and use `Any` with `getattr()` instead.

- [ ] **Step 2: Commit (only if fixups needed)**

```bash
git add ui/adapters/
git commit -m "fix(ui): adapter import fixups"
```

---

## Task 3: Create Template Rendering Helper

**Files:**
- Create: `ui/templates_helper.py`

This is adapted from `archive/docker_ui/ui/templates.py` but updated for the new directory structure.

- [ ] **Step 1: Create templates_helper.py**

```python
"""
Jinja2 Template Utilities for DAG Brain Admin UI.

Provides Jinja2Templates instance and render helpers.
Adapted from archive/docker_ui/ui/templates.py for the DAG Brain.
"""
from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from starlette.templating import Jinja2Templates

from config import __version__
from ui.terminology import get_terms
from ui.features import get_enabled_features
from ui.navigation import get_nav_items, get_nav_sections

# Templates directory is at project root level
_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)


def get_template_context(request: Request, **kwargs: Any) -> Dict[str, Any]:
    """Build standard template context with common variables."""
    context = {
        "request": request,
        "version": __version__,
        "terms": get_terms(),
        "features": get_enabled_features(),
        "nav_items": get_nav_items(),
        "nav_sections": get_nav_sections(),
        "nav_active": kwargs.pop("nav_active", None),
    }
    context.update(kwargs)
    return context


def render_template(request: Request, template_name: str, **kwargs: Any):
    """Render a Jinja2 template with standard context."""
    context = get_template_context(request, **kwargs)
    return templates.TemplateResponse(template_name, context)


def render_fragment(request: Request, template_name: str, **kwargs: Any):
    """Render an HTMX fragment (no base layout)."""
    context = {"request": request, "version": __version__}
    context.update(kwargs)
    return templates.TemplateResponse(template_name, context)
```

- [ ] **Step 2: Verify import**

```bash
python -c "from ui.templates_helper import render_template; print('Templates helper OK')"
```

Expected: OK (templates directory doesn't need to exist yet for the import to succeed — Jinja2Templates is lazy).

- [ ] **Step 3: Commit**

```bash
git add ui/templates_helper.py
git commit -m "feat(ui): add Jinja2 template rendering helper"
```

---

## Task 4: Restore Templates from Archive

**Files:**
- Create: `templates/base.html`
- Create: `templates/components/navbar.html`
- Create: `templates/components/footer.html`
- Create: `templates/components/macros.html`
- Create: `templates/components/form_macros.html`
- Create: `templates/pages/dashboard.html`
- Create: `templates/pages/jobs/list.html`
- Create: `templates/pages/jobs/detail.html`
- Create: `templates/pages/admin/health.html`

- [ ] **Step 1: Copy base template and components**

```bash
mkdir -p templates/components templates/pages/jobs templates/pages/admin
cp archive/docker_ui/templates/base.html templates/base.html
cp archive/docker_ui/templates/components/navbar.html templates/components/navbar.html
cp archive/docker_ui/templates/components/footer.html templates/components/footer.html
cp archive/docker_ui/templates/components/macros.html templates/components/macros.html
cp archive/docker_ui/templates/components/form_macros.html templates/components/form_macros.html
```

- [ ] **Step 2: Update base.html**

The archived `base.html` uses simple `{% include "components/navbar.html" %}`. Update it to:
1. Pass `nav_sections` and `nav_active` to the navbar include
2. Update the HTMX CDN to include SRI hash (copy from `web_interfaces/base.py`)
3. Ensure `/static/` paths are correct (they should be — FastAPI serves from `/static/`)

Key change in base.html — add terms and features to the template context check:
```html
<title>{% block title %}Dashboard{% endblock %} - rmhgeoapi v{{ version }}</title>
```

This should already work since `render_template()` injects `version`.

- [ ] **Step 3: Update navbar.html to use navigation.py data**

Replace the hardcoded nav links in `navbar.html` with a loop over `nav_sections`:

```html
{% for section_name, items in nav_sections.items() %}
  <div class="nav-section">
    <div class="nav-section-title">{{ section_name | title }}</div>
    {% for item in items %}
      <a href="{{ item.path }}"
         class="nav-item {% if nav_active == item.path %}active{% endif %}">
        <i data-feather="{{ item.icon }}"></i>
        <span>{{ item.label }}</span>
        {% if item.badge %}
          <span class="nav-badge">{{ item.badge }}</span>
        {% endif %}
      </a>
    {% endfor %}
  </div>
{% endfor %}
```

- [ ] **Step 4: Copy page templates**

```bash
cp archive/docker_ui/templates/pages/jobs/list.html templates/pages/jobs/list.html
cp archive/docker_ui/templates/pages/jobs/detail.html templates/pages/jobs/detail.html
cp archive/docker_ui/templates/pages/admin/health.html templates/pages/admin/health.html
```

Review each template for hardcoded `/interface/` paths and change to `/ui/`. Also review for any template variables that reference old context names and update to use DTOs (`job.workflow_id` not `job.job_type`).

- [ ] **Step 5: Create dashboard.html**

The archived `home.html` is admin-focused. Copy from `archive/docker_ui/templates/pages/admin/home.html` to `templates/pages/dashboard.html`. Update to use the terminology system:

```html
{% extends "base.html" %}
{% from "components/macros.html" import status_badge, stat_item %}

{% block title %}{{ terms.mode_display }} Dashboard{% endblock %}

{% block content %}
<div class="dashboard-header">
    <h1>{{ terms.mode_display }} Admin Console</h1>
    <p class="subtitle">rmhgeoapi v{{ version }}</p>
</div>

<div class="stats-banner">
    {{ stat_item("Active Jobs", stats.active, highlight=true) }}
    {{ stat_item("Completed (24h)", stats.completed) }}
    {{ stat_item("Failed (24h)", stats.failed) }}
    {{ stat_item("Handlers", stats.handler_count) }}
</div>
{% endblock %}
```

- [ ] **Step 6: Copy job card component**

```bash
cp archive/docker_ui/templates/components/_job_card.html templates/components/_job_card.html
```

Update to use DTO field names: `job.workflow_id` (not `job.job_type`), `job.current_step`/`job.total_steps` (not `job.stage`/`job.total_stages`).

- [ ] **Step 7: Commit**

```bash
git add templates/
git commit -m "feat(ui): restore Jinja2 templates from archive, update for DTO/terminology"
```

---

## Task 5: Restore Static Assets

**Files:**
- Create: `static/css/styles.css`
- Create: `static/css/jobs.css`
- Create: `static/css/health.css`
- Create: `static/js/common.js`
- Create: `static/js/app.js`

- [ ] **Step 1: Copy CSS**

```bash
mkdir -p static/css static/js
cp archive/docker_ui/static/css/styles.css static/css/styles.css
cp archive/docker_ui/static/css/jobs.css static/css/jobs.css
cp archive/docker_ui/static/css/health.css static/css/health.css
```

- [ ] **Step 2: Verify CSS design tokens match**

Open `static/css/styles.css` and verify the CSS variables match the Function App design system (`web_interfaces/base.py` COMMON_CSS). The color tokens should be the same WB blue palette:
```css
--ds-blue-primary: #0071BC;
--ds-navy: #053657;
--ds-cyan: #00A3DA;
```

If the archived CSS diverged, update to match. The design system should be consistent across both UIs.

- [ ] **Step 3: Copy JS**

```bash
cp archive/docker_ui/static/js/common.js static/js/common.js
```

Create a minimal `static/js/app.js`:

```javascript
/* DAG Brain Admin UI — page behaviors */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Feather Icons if loaded
    if (typeof feather !== 'undefined') {
        feather.replace();
    }
});
```

- [ ] **Step 4: Commit**

```bash
git add static/
git commit -m "feat(ui): restore static assets (CSS design system + JS utilities)"
```

---

## Task 6: Create UI Routes (FastAPI APIRouter)

**Files:**
- Create: `ui_routes.py`

This is the FastAPI router that serves UI pages. Only mounted when `APP_MODE=orchestrator`.

- [ ] **Step 1: Create ui_routes.py**

```python
"""
DAG Brain Admin UI Routes.

FastAPI APIRouter serving Jinja2-rendered admin pages.
Mounted at /ui/ prefix in docker_service.py when APP_MODE=orchestrator.

Pages:
    /ui/              Dashboard (job stats, health summary, handler count)
    /ui/jobs           Job list with HTMX auto-refresh
    /ui/jobs/{job_id}  Job detail with task breakdown
    /ui/health         Cross-system health dashboard
    /ui/handlers       Handler registry browser
"""
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ui.templates_helper import render_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["admin-ui"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Admin dashboard with job stats and health summary."""
    stats = _get_dashboard_stats()
    return render_template(
        request,
        "pages/dashboard.html",
        stats=stats,
        nav_active="/ui/",
    )


@router.get("/jobs", response_class=HTMLResponse)
async def job_list(request: Request, status: Optional[str] = None, hours: int = 24):
    """Job list with filtering."""
    from infrastructure.jobs_tasks import JobRepository
    job_repo = JobRepository()

    # list_jobs_with_filters() accepts status as JobStatus enum or None
    status_enum = None
    if status:
        from core.models.enums import JobStatus
        try:
            status_enum = JobStatus(status)
        except ValueError:
            pass  # Invalid status string — show all jobs

    jobs_raw = job_repo.list_jobs_with_filters(
        status=status_enum, hours=hours, limit=50
    )

    from ui.adapters import jobs_to_dto
    jobs = jobs_to_dto(jobs_raw) if jobs_raw else []

    return render_template(
        request,
        "pages/jobs/list.html",
        jobs=jobs,
        filters={"status": status, "hours": hours},
        nav_active="/ui/jobs",
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    """Job detail with task breakdown."""
    from infrastructure.jobs_tasks import JobRepository, TaskRepository
    job_repo = JobRepository()
    task_repo = TaskRepository()

    job_raw = job_repo.get_job(job_id)
    if not job_raw:
        return HTMLResponse(f"Job {job_id} not found", status_code=404)

    tasks_raw = task_repo.get_tasks_for_job(job_id)

    from ui.adapters import job_to_dto, tasks_to_dto
    job = job_to_dto(job_raw)
    tasks = tasks_to_dto(tasks_raw) if tasks_raw else []

    return render_template(
        request,
        "pages/jobs/detail.html",
        job=job,
        tasks=tasks,
        nav_active="/ui/jobs",
    )


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    """Cross-system health dashboard."""
    return render_template(
        request,
        "pages/admin/health.html",
        nav_active="/ui/health",
    )


@router.get("/handlers", response_class=HTMLResponse)
async def handlers_page(request: Request):
    """Handler registry browser."""
    try:
        from services import ALL_HANDLERS
        handlers = sorted(ALL_HANDLERS.keys())
    except Exception:
        handlers = []

    return render_template(
        request,
        "pages/handlers.html",
        handlers=handlers,
        nav_active="/ui/handlers",
    )


def _get_dashboard_stats() -> dict:
    """Gather stats for the dashboard."""
    try:
        from infrastructure.jobs_tasks import JobRepository
        job_repo = JobRepository()
        # list_jobs_with_filters() is the actual method on JobRepository
        recent = job_repo.list_jobs_with_filters(hours=24, limit=200)
        statuses = [getattr(j, 'status', None) for j in (recent or [])]
        status_vals = [s.value if hasattr(s, 'value') else str(s) for s in statuses]

        from services import ALL_HANDLERS
        handler_count = len(ALL_HANDLERS)
    except Exception as e:
        logger.warning(f"Dashboard stats failed: {e}")
        return {"active": 0, "completed": 0, "failed": 0, "handler_count": 0}

    return {
        "active": sum(1 for s in status_vals if s == "processing"),
        "completed": sum(1 for s in status_vals if s == "completed"),
        "failed": sum(1 for s in status_vals if s == "failed"),
        "handler_count": handler_count,
    }
```

- [ ] **Step 2: Verify import**

```bash
python -c "from ui_routes import router; print(f'{len(router.routes)} routes'); print('Router OK')"
```

Expected: 5 routes, Router OK.

- [ ] **Step 3: Commit**

```bash
git add ui_routes.py
git commit -m "feat(ui): add FastAPI UI routes (dashboard, jobs, health, handlers)"
```

---

## Task 7: Mount UI in docker_service.py

**Files:**
- Modify: `docker_service.py` (lines ~1016-1038, ~1063-1069)

This is the integration point. We mount the UI router and static files only when `APP_MODE=orchestrator`.

- [ ] **Step 1: Add static file mount and UI router**

After the `app = FastAPI(...)` definition (around line 1064), add:

```python
# ============================================================================
# ADMIN UI (APP_MODE=orchestrator only)
# ============================================================================
import os as _os
if _os.environ.get("APP_MODE") == "orchestrator":
    from fastapi.staticfiles import StaticFiles
    from pathlib import Path

    _static_dir = Path(__file__).parent / "static"
    if _static_dir.exists():
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")
        logger.info("Mounted /static for Admin UI")

    try:
        from ui_routes import router as ui_router
        app.include_router(ui_router)
        logger.info("Mounted /ui/ Admin UI routes")
    except Exception as e:
        logger.warning(f"Admin UI routes failed to mount: {e}")
```

- [ ] **Step 2: Update root redirect for orchestrator mode**

Change the existing `root_redirect` (line ~1082) to redirect to `/ui/` instead of `/health` when in orchestrator mode:

```python
@app.get("/")
def root_redirect():
    """Redirect root to appropriate landing page."""
    if os.environ.get("APP_MODE") == "orchestrator":
        return RedirectResponse(url="/ui/", status_code=302)
    return RedirectResponse(url="/health", status_code=302)
```

- [ ] **Step 3: Exclude UI files from Function App deployment**

Add to `.funcignore` so `func azure functionapp publish` doesn't include Docker-only files:

```
# Admin UI (Docker orchestrator only)
ui/
templates/
static/
ui_routes.py
```

- [ ] **Step 4: Verify docker_service.py still imports cleanly**

```bash
python -c "import docker_service; print('docker_service OK')"
```

This may fail if APP_MODE is not set. That's expected. The key is that it doesn't have syntax errors.

- [ ] **Step 5: Commit**

```bash
git add docker_service.py .funcignore
git commit -m "feat(ui): mount admin UI router + static files in orchestrator mode"
```

---

## Task 8: Create Handlers Page Template

**Files:**
- Create: `templates/pages/handlers.html`

This is a net-new page — the DAG Brain's handler registry is unique to this app.

- [ ] **Step 1: Create handlers.html**

```html
{% extends "base.html" %}
{% from "components/macros.html" import empty_state %}

{% block title %}Handler Registry{% endblock %}

{% block content %}
<div class="dashboard-header">
    <h1>Handler Registry</h1>
    <p class="subtitle">{{ handlers | length }} registered atomic handlers</p>
</div>

<div class="filter-bar">
    <input type="text" class="search-input" placeholder="Filter handlers..."
           onkeyup="filterHandlers(this.value)">
</div>

<div class="handler-grid" id="handler-list">
    {% if handlers %}
        {% for handler in handlers %}
        <div class="handler-card" data-name="{{ handler }}">
            <div class="handler-name">{{ handler }}</div>
        </div>
        {% endfor %}
    {% else %}
        {{ empty_state("No Handlers", "No handlers registered in ALL_HANDLERS") }}
    {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
function filterHandlers(query) {
    const cards = document.querySelectorAll('.handler-card');
    const q = query.toLowerCase();
    cards.forEach(card => {
        const name = card.dataset.name.toLowerCase();
        card.style.display = name.includes(q) ? '' : 'none';
    });
}
</script>
{% endblock %}

{% block styles %}
/* Handler-specific styles — note: base.html wraps this block in <style> tags */
.handler-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 12px;
    margin-top: 16px;
}
.handler-card {
    background: white;
    border-left: 4px solid var(--ds-blue-primary, #0071BC);
    padding: 16px;
    border-radius: 3px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.handler-name {
    font-family: monospace;
    font-size: 14px;
    color: var(--ds-navy, #053657);
}
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/pages/handlers.html
git commit -m "feat(ui): add handler registry browser page"
```

---

## Task 9: Smoke Test — Local Startup

**Files:** None (verification only)

- [ ] **Step 1: Set up environment and start**

```bash
cd /Users/robertharrison/python_builds/rmhgeoapi
conda activate azgeo

# Set orchestrator mode for testing
export APP_MODE=orchestrator
export POSTGIS_HOST=rmhpostgres.postgres.database.azure.com
export POSTGIS_DATABASE=geopgflex

# Start uvicorn (same as Docker entrypoint)
python -m uvicorn docker_service:app --host 127.0.0.1 --port 8080 --log-level info
```

- [ ] **Step 2: Verify endpoints**

In a separate terminal:
```bash
# Root should redirect to /ui/
curl -s -o /dev/null -w "%{http_code} %{redirect_url}" http://localhost:8080/
# Expected: 302 http://localhost:8080/ui/

# Dashboard should render HTML
curl -s http://localhost:8080/ui/ | head -5
# Expected: <!DOCTYPE html> ...

# Handlers page
curl -s http://localhost:8080/ui/handlers | grep "Handler Registry"
# Expected: match

# Static CSS
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/static/css/styles.css
# Expected: 200

# Health endpoints still work
curl -s http://localhost:8080/livez
# Expected: {"status": "alive"}
```

- [ ] **Step 3: Stop the server (Ctrl+C)**

- [ ] **Step 4: Commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix(ui): smoke test fixups"
```

---

## Task 10: Final Commit and Documentation

**Files:**
- Modify: `V10_MIGRATION.md` — Add UI entry to v0.10.5 section

- [ ] **Step 1: Update V10_MIGRATION.md**

Add to the v0.10.5 section:

```markdown
### Admin UI (DAG Brain)
- **Location**: `ui/`, `templates/`, `static/`, `ui_routes.py`
- **Mounted at**: `/ui/` prefix, `APP_MODE=orchestrator` only
- **Source**: Merged from DAG Master abstraction layer + archived Docker UI templates
- **Pages**: Dashboard, Jobs (list + detail), Health, Handlers
- **Tech**: FastAPI + Jinja2 + HTMX + vanilla JS
- **Design system**: Same WB blue tokens as Function App `web_interfaces/`
```

- [ ] **Step 2: Final commit**

```bash
git add V10_MIGRATION.md
git commit -m "docs: document DAG Brain Admin UI in V10 migration"
```

---

## Scope Boundaries

**In scope (this plan):**
- UI abstraction layer (DTOs, adapters, terminology, features, navigation)
- Base template infrastructure (base.html, navbar, macros, footer)
- Core pages: Dashboard, Jobs (list + detail), Health, Handlers
- Static assets (CSS design system, JS utilities)
- Router mounting in docker_service.py

**Out of scope (future plans):**
- Raster Viewer page (restore from archive — needs TiTiler proxy endpoints)
- Vector Viewer page (restore from archive — needs TiPG proxy endpoints)
- Log Viewer page (restore from archive — needs App Insights proxy)
- Submit page (restore from archive — needs file upload endpoints)
- DAG Graph visualization (net-new — needs D3.js or similar)
- Scheduler dashboard (net-new — needs scheduler API endpoints)
- STAC Browser page
- Dark theme toggle
- Authentication/authorization for admin UI

Each of these is a self-contained follow-up plan once the foundation from this plan is deployed and verified.
