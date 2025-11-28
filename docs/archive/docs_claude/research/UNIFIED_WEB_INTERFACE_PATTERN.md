# Unified Web Interface Pattern - Dynamic Module Loading

**Date**: 14 NOV 2025
**Author**: Robert and Geospatial Claude Legion
**Status**: ✅ APPROVED PATTERN

---

## 🎯 The Pattern

**Single Route**: `/api/interface/{name}`
**Dynamic Loading**: Load interface module based on `{name}` parameter

### Examples:

```bash
# STAC dashboard
GET /api/interface/stac

# Vector viewer (with query params)
GET /api/interface/vector?collection=test_geojson_fresh

# Job monitor
GET /api/interface/jobs

# API explorer
GET /api/interface/docs
```

---

## 🏗️ Folder Structure

```
web_interfaces/
├── __init__.py                   # Registry + unified handler
├── base.py                       # Base template class
│
├── stac/                         # STAC dashboard module
│   ├── __init__.py
│   └── interface.py              # StacInterface class
│
├── vector/                       # Vector viewer module
│   ├── __init__.py
│   └── interface.py              # VectorInterface class
│
├── jobs/                         # Job monitor module
│   ├── __init__.py
│   └── interface.py              # JobsInterface class
│
└── docs/                         # API explorer module
    ├── __init__.py
    └── interface.py              # DocsInterface class
```

---

## 📝 Implementation Pattern

### 1. Base Interface Class

```python
# web_interfaces/base.py

from abc import ABC, abstractmethod
from typing import Dict, Any
import azure.functions as func

class BaseInterface(ABC):
    """
    Base class for all web interfaces.

    Each interface must implement render() to generate HTML.
    """

    # Common CSS used by all interfaces
    COMMON_CSS = """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        /* ... more common styles ... */
    """

    # Common JavaScript utilities
    COMMON_JS = """
        const API_BASE_URL = window.location.origin;

        function showSpinner(id) {
            document.getElementById(id).classList.remove('hidden');
        }

        function hideSpinner(id) {
            document.getElementById(id).classList.add('hidden');
        }

        function setStatus(msg, isError = false) {
            const el = document.getElementById('status');
            if (el) {
                el.textContent = msg;
                el.style.color = isError ? '#e74c3c' : '#666';
            }
        }
    """

    @abstractmethod
    def render(self, request: func.HttpRequest) -> str:
        """
        Generate HTML for this interface.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML string
        """
        pass

    def get_query_params(self, request: func.HttpRequest) -> Dict[str, Any]:
        """Extract query parameters from request."""
        return {key: request.params.get(key) for key in request.params}

    def wrap_html(self, title: str, content: str, custom_css: str = "", custom_js: str = "") -> str:
        """Wrap content in complete HTML document."""
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
            <style>
                {self.COMMON_CSS}
                {custom_css}
            </style>
        </head>
        <body>
            {self._render_navbar()}
            {content}
            <script>
                {self.COMMON_JS}
                {custom_js}
            </script>
        </body>
        </html>
        """

    def _render_navbar(self) -> str:
        """Render navigation bar with links to all interfaces."""
        return """
        <nav style="background: white; padding: 15px 30px; border-radius: 12px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 20px;
                    display: flex; justify-content: space-between; align-items: center;">
            <div style="font-size: 20px; font-weight: 700; color: #2c3e50;">
                🛰️ Geospatial API
            </div>
            <div style="display: flex; gap: 20px;">
                <a href="/api/interface/stac" style="color: #667eea; text-decoration: none;
                   font-weight: 500; transition: opacity 0.3s;"
                   onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1'">
                    STAC
                </a>
                <a href="/api/interface/vector" style="color: #667eea; text-decoration: none;
                   font-weight: 500; transition: opacity 0.3s;"
                   onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1'">
                    Vectors
                </a>
                <a href="/api/interface/jobs" style="color: #667eea; text-decoration: none;
                   font-weight: 500; transition: opacity 0.3s;"
                   onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1'">
                    Jobs
                </a>
                <a href="/api/interface/docs" style="color: #667eea; text-decoration: none;
                   font-weight: 500; transition: opacity 0.3s;"
                   onmouseover="this.style.opacity='0.7'" onmouseout="this.style.opacity='1'">
                    API Docs
                </a>
            </div>
        </nav>
        """
```

---

### 2. Interface Registry

```python
# web_interfaces/__init__.py

from typing import Dict, Type, Optional
import azure.functions as func
import logging

from .base import BaseInterface

logger = logging.getLogger(__name__)

class InterfaceRegistry:
    """
    Registry for all web interfaces.

    Handles dynamic loading of interface modules based on name.
    """

    _interfaces: Dict[str, Type[BaseInterface]] = {}

    @classmethod
    def register(cls, name: str):
        """
        Decorator to register an interface.

        Usage:
            @InterfaceRegistry.register('stac')
            class StacInterface(BaseInterface):
                ...
        """
        def decorator(interface_class: Type[BaseInterface]):
            cls._interfaces[name] = interface_class
            logger.info(f"Registered interface: {name} -> {interface_class.__name__}")
            return interface_class
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseInterface]]:
        """Get interface class by name."""
        return cls._interfaces.get(name)

    @classmethod
    def list_all(cls) -> Dict[str, Type[BaseInterface]]:
        """List all registered interfaces."""
        return cls._interfaces.copy()


def unified_interface_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified HTTP handler for all web interfaces.

    Route: /api/interface/{name}
    """
    interface_name = req.route_params.get('name')

    if not interface_name:
        return func.HttpResponse(
            "Missing interface name. Available: " + ", ".join(InterfaceRegistry.list_all().keys()),
            status_code=400
        )

    # Get interface class from registry
    interface_class = InterfaceRegistry.get(interface_name)

    if not interface_class:
        available = ", ".join(InterfaceRegistry.list_all().keys())
        return func.HttpResponse(
            f"Interface '{interface_name}' not found. Available: {available}",
            status_code=404
        )

    try:
        # Instantiate and render
        interface = interface_class()
        html = interface.render(req)

        return func.HttpResponse(
            html,
            mimetype="text/html",
            status_code=200
        )

    except Exception as e:
        logger.error(f"Error rendering interface '{interface_name}': {e}", exc_info=True)
        return func.HttpResponse(
            f"Error rendering interface: {str(e)}",
            status_code=500
        )


# Auto-import all interface modules to trigger registration
from .stac.interface import *
from .vector.interface import *
from .jobs.interface import *
from .docs.interface import *

__all__ = [
    'BaseInterface',
    'InterfaceRegistry',
    'unified_interface_handler'
]
```

---

### 3. Example Interface Module

```python
# web_interfaces/stac/interface.py

from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
import azure.functions as func
import logging

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('stac')
class StacInterface(BaseInterface):
    """STAC Collections Dashboard interface."""

    def render(self, request: func.HttpRequest) -> str:
        """Generate STAC dashboard HTML."""

        # Custom CSS for STAC dashboard
        custom_css = """
        .collections-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }

        .collection-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 10px;
            padding: 24px;
            cursor: pointer;
            transition: all 0.3s;
            color: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .collection-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        }
        """

        # Custom JavaScript for STAC dashboard
        custom_js = """
        async function loadCollections() {
            try {
                const response = await fetch(`${API_BASE_URL}/api/stac/collections`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                const data = await response.json();
                const collections = data.collections || [];

                renderCollections(collections);
            } catch (error) {
                console.error('Error loading collections:', error);
                setStatus('Error: ' + error.message, true);
            }
        }

        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');
            grid.innerHTML = collections.map(c => `
                <div class="collection-card" onclick="showCollection('${c.id}')">
                    <h3>${c.title || c.id}</h3>
                    <p>${c.description || 'No description'}</p>
                    <div>📄 ${c.summaries?.total_items || 0} items</div>
                </div>
            `).join('');
        }

        function showCollection(id) {
            window.location.href = `/api/interface/stac?collection=${id}`;
        }

        window.addEventListener('load', loadCollections);
        """

        # HTML content
        content = """
        <div class="container">
            <header style="background: white; padding: 30px; border-radius: 12px;
                          box-shadow: 0 4px 20px rgba(0,0,0,0.15); margin-bottom: 30px;">
                <h1 style="color: #2c3e50; font-size: 32px; margin-bottom: 10px;">
                    🛰️ STAC Collections Dashboard
                </h1>
                <p style="color: #7f8c8d; font-size: 16px;">
                    Browse and explore SpatioTemporal Asset Catalog collections
                </p>
            </header>

            <div id="status" style="margin-bottom: 20px; color: #666;"></div>

            <div class="collections-grid" id="collections-grid">
                <!-- Collections will be loaded here -->
            </div>
        </div>
        """

        return self.wrap_html(
            title="STAC Collections Dashboard",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )
```

---

### 4. Vector Viewer with Query Params

```python
# web_interfaces/vector/interface.py

from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
import azure.functions as func


@InterfaceRegistry.register('vector')
class VectorInterface(BaseInterface):
    """Vector Collection Viewer interface."""

    def render(self, request: func.HttpRequest) -> str:
        """Generate vector viewer HTML."""

        # Get collection from query params
        collection_id = request.params.get('collection')

        if not collection_id:
            # Show collection selector if no collection specified
            return self._render_collection_selector()
        else:
            # Show vector viewer for specified collection
            return self._render_collection_viewer(collection_id)

    def _render_collection_selector(self) -> str:
        """Render collection selection page."""

        custom_js = """
        async function loadCollections() {
            const response = await fetch(`${API_BASE_URL}/api/features/collections`);
            const data = await response.json();

            const select = document.getElementById('collection-select');
            data.collections.forEach(c => {
                const option = document.createElement('option');
                option.value = c.id;
                option.textContent = c.title || c.id;
                select.appendChild(option);
            });
        }

        function viewCollection() {
            const id = document.getElementById('collection-select').value;
            if (id) {
                window.location.href = `/api/interface/vector?collection=${id}`;
            }
        }

        window.addEventListener('load', loadCollections);
        """

        content = """
        <div class="container">
            <h1>Select Vector Collection</h1>
            <select id="collection-select" style="width: 100%; padding: 10px; margin: 20px 0;">
                <option value="">Loading...</option>
            </select>
            <button onclick="viewCollection()" style="padding: 10px 20px; background: #667eea;
                    color: white; border: none; border-radius: 6px; cursor: pointer;">
                View Collection
            </button>
        </div>
        """

        return self.wrap_html(
            title="Select Vector Collection",
            content=content,
            custom_js=custom_js
        )

    def _render_collection_viewer(self, collection_id: str) -> str:
        """Render Leaflet map viewer for specific collection."""

        # Use existing vector viewer HTML generation logic
        # (This would be the same as current VectorViewerService.generate_viewer_html)

        custom_css = """
        #map { height: 600px; width: 100%; border-radius: 8px; }
        .load-button { padding: 8px 16px; margin: 0 5px; background: #667eea;
                      color: white; border: none; border-radius: 4px; cursor: pointer; }
        """

        custom_js = f"""
        const COLLECTION_ID = '{collection_id}';

        // Initialize Leaflet map
        const map = L.map('map').setView([0, 0], 2);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap contributors'
        }}).addTo(map);

        async function loadFeatures(limit) {{
            const url = `${{API_BASE_URL}}/api/features/collections/${{COLLECTION_ID}}/items?limit=${{limit}}`;
            const response = await fetch(url);
            const geojson = await response.json();

            L.geoJSON(geojson).addTo(map);
        }}
        """

        content = f"""
        <div class="container">
            <h1>Vector Collection: {collection_id}</h1>
            <div>
                <button class="load-button" onclick="loadFeatures(100)">Load 100</button>
                <button class="load-button" onclick="loadFeatures(500)">Load 500</button>
                <button class="load-button" onclick="loadFeatures(10000)">Load All</button>
            </div>
            <div id="map" style="margin-top: 20px;"></div>
        </div>

        <!-- Leaflet CSS/JS -->
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        """

        return self.wrap_html(
            title=f"Vector Viewer - {collection_id}",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )
```

---

### 5. Function App Registration

```python
# function_app.py

from web_interfaces import unified_interface_handler

# Single route handles all web interfaces
@app.route(route="interface/{name}", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def web_interface_unified(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified web interface handler.

    Examples:
        /api/interface/stac
        /api/interface/vector?collection=test_geojson_fresh
        /api/interface/jobs
        /api/interface/docs
    """
    return unified_interface_handler(req)
```

---

## ✅ Benefits of This Pattern

### 1. Clean URLs
```bash
# Before (separate routes):
/api/stac/dashboard
/api/vector/viewer?collection=...
/api/jobs/monitor
/api/docs

# After (unified):
/api/interface/stac
/api/interface/vector?collection=...
/api/interface/jobs
/api/interface/docs
```

### 2. Easy to Add New Interfaces
```python
# Just create new file and register!

# web_interfaces/raster/interface.py
@InterfaceRegistry.register('raster')
class RasterInterface(BaseInterface):
    def render(self, request):
        return self.wrap_html("Raster Viewer", "<h1>Raster data here</h1>")

# That's it! /api/interface/raster now works
```

### 3. Automatic Discovery
```python
# List all available interfaces
GET /api/interface/

# Returns:
{
  "available_interfaces": ["stac", "vector", "jobs", "docs", "raster"]
}
```

### 4. Shared Navigation
All interfaces automatically have navbar with links to other interfaces (in BaseInterface._render_navbar())

### 5. Consistent Error Handling
Registry handles 404s for unknown interfaces uniformly

---

## 🚀 Migration Path

### Step 1: Create Structure
```bash
mkdir -p web_interfaces/stac
mkdir -p web_interfaces/vector
mkdir -p web_interfaces/jobs
mkdir -p web_interfaces/docs

touch web_interfaces/__init__.py
touch web_interfaces/base.py
touch web_interfaces/stac/__init__.py
touch web_interfaces/stac/interface.py
# ... etc
```

### Step 2: Implement Base Classes
1. Create `web_interfaces/base.py` (BaseInterface)
2. Create `web_interfaces/__init__.py` (InterfaceRegistry)

### Step 3: Migrate Vector Viewer
1. Create `web_interfaces/vector/interface.py`
2. Copy HTML generation logic from `vector_viewer/service.py`
3. Wrap in VectorInterface class with @InterfaceRegistry.register('vector')

### Step 4: Add STAC Dashboard
1. Create `web_interfaces/stac/interface.py`
2. Implement StacInterface with dashboard HTML
3. Register with @InterfaceRegistry.register('stac')

### Step 5: Update Function App
1. Add unified route: `@app.route(route="interface/{name}")`
2. Call `unified_interface_handler(req)`
3. Test all interfaces work

### Step 6: Deprecate Old Routes (Optional)
1. Keep `/api/vector/viewer` as redirect to `/api/interface/vector`
2. Add deprecation notice in old routes
3. Update documentation

---

## 📊 Comparison

| Pattern | Routes | Maintenance | Discovery | Flexibility |
|---------|--------|-------------|-----------|-------------|
| **Separate Routes** | Many (`/api/stac/dashboard`, `/api/vector/viewer`, etc.) | Update function_app.py for each | Manual docs | Medium |
| **Unified Route** ✅ | One (`/api/interface/{name}`) | Auto-discovery via registry | Automatic | High |

---

## 🎯 Next Steps

1. ✅ Approve this pattern
2. Create folder structure
3. Implement BaseInterface + InterfaceRegistry
4. Migrate vector viewer as first example
5. Add STAC dashboard as second example
6. Update function_app.py with unified route

---

**Want me to start implementing this pattern?** 🚀
