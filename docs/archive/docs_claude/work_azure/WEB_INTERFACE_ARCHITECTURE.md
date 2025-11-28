# Web Interface Architecture Proposal

**Date**: 14 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: 📋 PROPOSAL - Awaiting approval

---

## 🎯 Overview

Proposed folder structure for embedded web interfaces within the Azure Function App monolith, following the proven `vector_viewer/` pattern.

---

## 🏗️ Current State

**What We Have**:
- ✅ `/vector_viewer/` - Standalone module serving HTML for vector QA
- ✅ `/ogc_features/map.html` - Static map embedded in module (legacy pattern)
- ✅ `$web` container - Public static site (OGC Features map)

**Current Pattern (vector_viewer/)**:
```
vector_viewer/
├── __init__.py          # Module exports
├── service.py           # VectorViewerService - HTML generation
└── triggers.py          # HTTP handler for /api/vector/viewer
```

**How It Works**:
1. User requests: `GET /api/vector/viewer?collection=test_geojson_fresh`
2. `triggers.py` → `VectorViewerService.generate_viewer_html()`
3. Service fetches collection metadata from OGC API
4. Returns **self-contained HTML** with embedded Leaflet map
5. **No CORS issues** - same origin as API
6. **No auth issues** - inherits function app auth context

---

## 📁 Proposed Folder Structure

### Option A: Separate Modules (Recommended)

**Pattern**: Each web interface is a standalone module (like vector_viewer)

```
rmhgeoapi/
├── web_interfaces/               # 🆕 Parent folder for all web UIs
│   ├── __init__.py               # Exports all viewer services
│   │
│   ├── shared/                   # 🆕 Shared templates & components
│   │   ├── __init__.py
│   │   ├── base_template.py      # Base HTML template class
│   │   ├── components.py         # Reusable HTML components (navbar, footer, etc.)
│   │   └── styles.py             # Shared CSS constants
│   │
│   ├── stac_dashboard/           # 🆕 STAC collections browser
│   │   ├── __init__.py
│   │   ├── service.py            # StacDashboardService
│   │   └── triggers.py           # /api/stac/dashboard
│   │
│   ├── vector_viewer/            # ✅ EXISTING (move here)
│   │   ├── __init__.py
│   │   ├── service.py            # VectorViewerService
│   │   └── triggers.py           # /api/vector/viewer
│   │
│   ├── job_monitor/              # 🆕 CoreMachine job monitoring
│   │   ├── __init__.py
│   │   ├── service.py            # JobMonitorService
│   │   └── triggers.py           # /api/jobs/monitor
│   │
│   └── api_explorer/             # 🆕 Interactive API documentation
│       ├── __init__.py
│       ├── service.py            # ApiExplorerService
│       └── triggers.py           # /api/docs
│
├── static_assets/                # 🆕 OPTIONAL - Static files (if needed)
│   ├── css/
│   │   └── common.css            # Shared styles
│   ├── js/
│   │   └── common.js             # Shared JavaScript
│   └── images/
│       └── logo.png
│
├── ogc_features/                 # ✅ EXISTING
│   ├── map.html                  # DEPRECATE? (move to web_interfaces/ogc_map/)
│   └── ...
│
├── stac_api/                     # ✅ EXISTING
├── infrastructure/               # ✅ EXISTING
├── jobs/                         # ✅ EXISTING
├── services/                     # ✅ EXISTING
└── function_app.py               # ✅ EXISTING - Register all web routes
```

### Option B: Single `web/` Module (Simpler)

**Pattern**: All web interfaces in one module with subfolders

```
rmhgeoapi/
├── web/                          # 🆕 All web interfaces
│   ├── __init__.py               # Exports all services
│   ├── base.py                   # Shared base template class
│   ├── components.py             # Reusable components
│   │
│   ├── stac_dashboard.py         # StacDashboardService + triggers
│   ├── vector_viewer.py          # VectorViewerService + triggers (move from vector_viewer/)
│   ├── job_monitor.py            # JobMonitorService + triggers
│   └── api_explorer.py           # ApiExplorerService + triggers
│
├── vector_viewer/                # DEPRECATE (move to web/)
└── ...
```

---

## 🎨 Recommended: Option A (Separate Modules)

### Why This Pattern?

✅ **Separation of Concerns** - Each dashboard is independent
✅ **Easier Testing** - Test each module in isolation
✅ **Clear Ownership** - Each module has single responsibility
✅ **Future Microservices** - Easy to split into separate Function Apps later
✅ **Proven Pattern** - Already working with `vector_viewer/`

### Migration Path:

```bash
# 1. Create new structure
mkdir -p web_interfaces/shared
mkdir -p web_interfaces/stac_dashboard
mkdir -p web_interfaces/job_monitor
mkdir -p web_interfaces/api_explorer

# 2. Move existing vector_viewer into web_interfaces/
mv vector_viewer web_interfaces/

# 3. Update imports in function_app.py
# OLD: from vector_viewer import get_vector_viewer_triggers
# NEW: from web_interfaces.vector_viewer import get_vector_viewer_triggers
```

---

## 📝 Template Pattern

### Shared Base Template Class

```python
# web_interfaces/shared/base_template.py

class BaseTemplate:
    """Base HTML template with common structure."""

    COMMON_CSS = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        /* ... more shared styles ... */
    """

    COMMON_JS = """
        const API_BASE_URL = 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net';

        function showSpinner() { /* ... */ }
        function hideSpinner() { /* ... */ }
        function setStatus(msg, isError) { /* ... */ }
    """

    @classmethod
    def render(cls, title: str, content: str, custom_css: str = "", custom_js: str = "") -> str:
        """Render complete HTML page."""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>{cls.COMMON_CSS}{custom_css}</style>
        </head>
        <body>
            {cls._render_navbar()}
            {content}
            <script>{cls.COMMON_JS}{custom_js}</script>
        </body>
        </html>
        """

    @classmethod
    def _render_navbar(cls) -> str:
        """Render common navigation bar."""
        return """
        <nav class="navbar">
            <div class="nav-brand">🛰️ Geospatial API</div>
            <div class="nav-links">
                <a href="/api/stac/dashboard">STAC</a>
                <a href="/api/vector/viewer">Vectors</a>
                <a href="/api/jobs/monitor">Jobs</a>
                <a href="/api/docs">API Docs</a>
            </div>
        </nav>
        """
```

### Module Service Class Pattern

```python
# web_interfaces/stac_dashboard/service.py

from web_interfaces.shared.base_template import BaseTemplate

class StacDashboardService:
    """Generate STAC collections dashboard HTML."""

    def generate_dashboard_html(self) -> str:
        """Generate full dashboard HTML."""

        content = """
        <div class="container">
            <header>
                <h1>STAC Collections Dashboard</h1>
            </header>
            <div id="collections-grid"></div>
        </div>
        """

        custom_css = """
        .collections-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }
        """

        custom_js = """
        async function loadCollections() {
            const response = await fetch(`${API_BASE_URL}/api/stac/collections`);
            // ...
        }
        window.addEventListener('load', loadCollections);
        """

        return BaseTemplate.render(
            title="STAC Collections Dashboard",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )
```

### Module Trigger Pattern

```python
# web_interfaces/stac_dashboard/triggers.py

import azure.functions as func
from .service import StacDashboardService

def get_stac_dashboard_triggers():
    """Return trigger configuration for STAC dashboard."""
    return [
        {
            'route': 'stac/dashboard',
            'methods': ['GET'],
            'handler': stac_dashboard_handler
        }
    ]

def stac_dashboard_handler(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP handler for STAC dashboard."""
    service = StacDashboardService()
    html = service.generate_dashboard_html()
    return func.HttpResponse(html, mimetype="text/html")
```

---

## 🚀 Proposed Web Interfaces

### 1. STAC Collections Dashboard
**Route**: `/api/stac/dashboard`
**Purpose**: Browse STAC collections, view items, metadata
**Status**: ✅ HTML created, needs integration

### 2. Vector Viewer (QA Tool)
**Route**: `/api/vector/viewer?collection={id}`
**Purpose**: Preview vector data after ETL for QA
**Status**: ✅ Already implemented

### 3. Job Monitor Dashboard
**Route**: `/api/jobs/monitor`
**Purpose**: Monitor CoreMachine jobs, tasks, status
**Features**:
- List all jobs with filters (status, job_type, date range)
- Drill down to job → stages → tasks
- Real-time status updates (polling)
- Retry failed jobs button

### 4. OGC Features Map
**Route**: `/api/features/map`
**Purpose**: Interactive map for exploring vector collections
**Status**: 🔄 Currently in `$web` container, should migrate

### 5. API Explorer
**Route**: `/api/docs`
**Purpose**: Interactive API documentation (like Swagger UI)
**Features**:
- List all endpoints
- Try API calls in browser
- Show request/response examples
- Authentication helper

### 6. Platform API Dashboard
**Route**: `/api/platform/dashboard`
**Purpose**: Monitor Platform orchestration layer
**Features**:
- API requests table
- Orchestration jobs status
- Dataset processing pipeline view

---

## 🎯 Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Create `web_interfaces/` folder structure
- [ ] Build `shared/base_template.py` with common CSS/JS
- [ ] Move `vector_viewer/` → `web_interfaces/vector_viewer/`
- [ ] Update imports in `function_app.py`
- [ ] Test vector viewer still works

### Phase 2: STAC Dashboard (Week 1)
- [ ] Create `web_interfaces/stac_dashboard/`
- [ ] Implement `StacDashboardService`
- [ ] Add route `/api/stac/dashboard`
- [ ] Test with real STAC collections
- [ ] Document usage in STAC docs

### Phase 3: Job Monitor (Week 2)
- [ ] Create `web_interfaces/job_monitor/`
- [ ] Implement `JobMonitorService`
- [ ] Add route `/api/jobs/monitor`
- [ ] Add filters (status, job_type, date)
- [ ] Add real-time polling for updates

### Phase 4: OGC Map Migration (Week 2)
- [ ] Create `web_interfaces/ogc_map/`
- [ ] Migrate `$web/index.html` into function app
- [ ] Add route `/api/features/map`
- [ ] Deprecate `$web` container usage
- [ ] Update documentation

### Phase 5: API Explorer (Week 3)
- [ ] Create `web_interfaces/api_explorer/`
- [ ] Build dynamic endpoint discovery
- [ ] Add interactive request builder
- [ ] Add authentication flow helper

---

## 📊 Static Assets Strategy

### Option A: Embed Everything (Recommended for Now)
**Pattern**: All CSS/JS embedded in HTML strings (current approach)

**Pros**:
- ✅ Self-contained HTML files
- ✅ No additional HTTP requests
- ✅ Easier deployment (no asset management)
- ✅ Works perfectly with function app pattern

**Cons**:
- ❌ Larger HTML payloads
- ❌ CSS/JS duplication across pages
- ❌ No browser caching of common assets

### Option B: Serve Static Assets from Function App
**Pattern**: Separate routes for CSS/JS files

```python
@app.route(route="static/css/{filename}", methods=["GET"])
def serve_css(req: func.HttpRequest) -> func.HttpResponse:
    filename = req.route_params.get('filename')
    # Read from static_assets/css/{filename}
    return func.HttpResponse(css_content, mimetype="text/css")
```

**When to use**: Only if HTML payload size becomes a problem (>500KB)

### Option C: CDN for Common Libraries
**Pattern**: Use CDNs for third-party libraries (Leaflet, etc.)

```html
<!-- Already doing this! ✅ -->
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

**Recommendation**: Continue using CDNs for third-party libraries, embed custom CSS/JS

---

## 🔐 Authentication Strategy

### Current Setup:
- Function App has **Easy Auth enabled** (Azure AD)
- Routes set to `AuthLevel.ANONYMOUS` but still require auth (Easy Auth override)

### For Web Interfaces:

**Option 1: Same Auth as APIs** (Recommended)
- Web interfaces inherit function app's Easy Auth
- User logs in once → can use all dashboards + APIs
- **Benefit**: Secure by default, no CORS issues

**Option 2: Public Dashboards, Protected APIs**
- Disable Easy Auth for `/api/stac/dashboard`, `/api/vector/viewer`, etc.
- Keep Easy Auth for data endpoints
- **Benefit**: Public demos, controlled data access

**Option 3: Mixed Strategy**
- Public: `/api/docs`, `/api/stac/dashboard` (read-only)
- Protected: `/api/jobs/monitor`, `/api/vector/viewer` (write operations)

---

## 📚 Documentation Updates Needed

After implementing web interfaces:

1. **Update CLAUDE.md**:
   - Add `web_interfaces/` to project structure
   - Document web interface URLs

2. **Create WEB_INTERFACES_GUIDE.md**:
   - How to add new dashboards
   - Template patterns
   - Best practices

3. **Update API docs**:
   - Add web interface endpoints to API reference
   - Add screenshots

4. **Update FILE_CATALOG.md**:
   - Add new web_interfaces/ files

---

## 🎨 Design System

### Color Palette (Current)
```css
--primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
--text-primary: #2c3e50;
--text-secondary: #7f8c8d;
--background-light: #f8f9fa;
--border-color: #dee2e6;
```

### Typography
```css
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
```

### Components Library
**Consider creating** `web_interfaces/shared/components.py`:
- Spinner
- Status badge
- Data table
- Card grid
- Filter controls
- Modal dialog

---

## ✅ Recommendation Summary

**Do This**:
1. ✅ Use **Option A** - Separate modules in `web_interfaces/`
2. ✅ Create `shared/base_template.py` for common structure
3. ✅ Embed CSS/JS in HTML (self-contained)
4. ✅ Use CDNs for third-party libraries (Leaflet, etc.)
5. ✅ Follow vector_viewer pattern: service.py + triggers.py
6. ✅ Implement in phases (STAC → Job Monitor → OGC Map → API Explorer)

**Don't Do This**:
- ❌ Don't use `$web` container for authenticated dashboards
- ❌ Don't create separate service principals for static sites
- ❌ Don't duplicate HTML templates (use shared base)
- ❌ Don't serve static assets separately (unless payload >500KB)

---

## 🚦 Next Steps

1. **Get Approval** on folder structure (Option A vs B)
2. **Create `web_interfaces/` skeleton** with shared/base_template.py
3. **Migrate vector_viewer/** into new structure
4. **Implement STAC dashboard** as first new module
5. **Document pattern** for future dashboards

---

**Questions to Answer**:
1. Do you prefer **Option A** (separate modules) or **Option B** (single web/ folder)?
2. Should we deprecate `$web` container entirely or keep for truly public content?
3. Any specific dashboards you want prioritized?
4. Should we add user authentication UI or rely on Easy Auth redirect?
