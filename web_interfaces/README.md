# Web Interfaces Module

**Last Updated**: 16 DEC 2025

## Overview

Unified web interface system for the Geospatial API platform. Provides browser-based dashboards for monitoring system health, managing pipelines, viewing STAC collections, OGC Features, and more.

## Architecture

### Unified Route Pattern

All web interfaces are accessible via a single dynamic route:

```
/api/interface/{name}
```

**Examples**:
- `/api/interface/home` - Landing page
- `/api/interface/health` - System Status
- `/api/interface/pipeline` - Pipeline workflows
- `/api/interface/stac` - STAC Collections
- `/api/interface/queues` - Service Bus queues

### Design Pattern: Template Method + Registry

```
BaseInterface (Abstract)
    ├── Common CSS (Design System colors, typography)
    ├── Common JS (API utilities, error handling)
    ├── wrap_html() - Template wrapper with navbar
    └── render() - Abstract method (implemented by subclasses)

InterfaceRegistry (Singleton)
    ├── Decorator-based registration: @InterfaceRegistry.register('name')
    ├── Auto-discovery via __init__.py imports
    └── Dynamic route handling
```

### File Structure

```
web_interfaces/
├── README.md                    # This file
├── __init__.py                  # Registry + unified handler + auto-imports
├── base.py                      # BaseInterface abstract class
│
├── home/                        # ✅ Landing page
│   ├── __init__.py
│   └── interface.py
│
├── health/                      # ✅ System Status dashboard
│   ├── __init__.py
│   └── interface.py
│
├── platform/                    # ✅ Platform overview
│   ├── __init__.py
│   └── interface.py
│
├── storage/                     # ✅ Storage container browser
│   ├── __init__.py
│   └── interface.py
│
├── pipeline/                    # ✅ Pipeline workflows + recent jobs
│   ├── __init__.py
│   └── interface.py
│
├── h3/                          # ✅ H3 Grid Status
│   ├── __init__.py
│   └── interface.py
│
├── queues/                      # ✅ Service Bus Queues monitor
│   ├── __init__.py
│   └── interface.py
│
├── stac/                        # ✅ STAC Collections dashboard
│   ├── __init__.py
│   └── interface.py
│
├── vector/                      # ✅ OGC Features viewer
│   ├── __init__.py
│   └── interface.py
│
├── tasks/                       # ✅ Task monitor (workflow visualization)
│   ├── __init__.py
│   └── interface.py
│
├── jobs/                        # ✅ Job monitor
│   ├── __init__.py
│   └── interface.py
│
├── map/                         # ✅ Full-page Leaflet map
│   ├── __init__.py
│   └── interface.py
│
└── docs/                        # ✅ API Documentation
    ├── __init__.py
    └── interface.py
```

## Design System

### Color Palette

```css
--ds-blue-primary: #0071BC    /* Primary blue - links, buttons */
--ds-blue-dark: #245AAD       /* Dark blue - hover states */
--ds-navy: #053657            /* Navy - headings, text */
--ds-cyan: #00A3DA            /* Cyan - hover accents */
--ds-gold: #FFC14D            /* Gold - highlights */
--ds-gray: #626F86            /* Gray - secondary text */
--ds-gray-light: #e9ecef      /* Light gray - borders */
--ds-bg: #f8f9fa              /* Background gray */
```

### Typography

- **Font Family**: "Open Sans", Arial, sans-serif
- **Headings**: Font weight 700 (bold)
- **Body**: 14px, line-height 1.6
- **Professional, clean, data-focused aesthetic**

### Status Badges

| Status | Background | Text Color | Use Case |
|--------|------------|------------|----------|
| Pending | `#f3e8ff` | `#9333ea` (Purple) | Task created, awaiting queue |
| Queued | `#e5e7eb` | `#6b7280` (Gray) | In queue, not started |
| Processing | `#FEF3C7` | `#D97706` (Amber) | Currently running |
| Completed | `#D1FAE5` | `#059669` (Green) | Successfully finished |
| Failed | `#FEE2E2` | `#DC2626` (Red) | Error occurred |

### Card Components

- White background
- Blue left border (4px solid `#0071BC`)
- Subtle shadows (`0 1px 3px rgba(0,0,0,0.08)`)
- Rounded corners (3px)

## Navigation Bar

The global navigation bar includes links to all main interfaces:

```
🛰️ Geospatial API v{version}

[System Status] [Platform] [Storage] [Pipelines] [H3] [Queues] [STAC] [OGC Features] [API Docs]
```

All links are active and use the design system blue color with cyan hover state.

## Implemented Interfaces

### 1. Home (`/api/interface/home`) ✅

Landing page with quick links to all interfaces and system overview.

### 2. System Status (`/api/interface/health`) ✅

Real-time system health monitoring dashboard with:
- Database connection status
- Service Bus connectivity
- Storage account health
- Function app status
- Dynamic tooltips showing health check details

### 3. Platform (`/api/interface/platform`) ✅

Platform overview showing:
- API endpoints summary
- Available services
- Configuration status

### 4. Storage (`/api/interface/storage`) ✅

Azure Storage container browser:
- Browse bronze/silver/gold containers
- File listing and metadata
- Size and timestamp display

### 5. Pipelines (`/api/interface/pipeline`) ✅

Pipeline workflow management:
- Available pipelines (Vector, Raster, Raster Collection)
- Pipeline stage visualization
- Recent jobs table with filtering
- Job stats by status (queued/processing/completed/failed)
- Click to view task details

### 6. Queues (`/api/interface/queues`) ✅

Service Bus queue monitoring:
- Queue cards showing active/DLQ/scheduled counts
- Utilization percentage bars
- Health status indicators
- Quick actions to peek messages and view DLQ

### 7. STAC Collections (`/api/interface/stac`) ✅

STAC metadata catalog dashboard:
- Collection cards with metadata
- Total items count per collection
- Spatial/temporal extent display
- Clickable STAC links (self, items, parent, root)
- Search and filter by name/type

### 8. OGC Features (`/api/interface/vector`) ✅

OGC API - Features viewer:
- Collection selector dropdown
- Feature table with pagination
- Click to view full feature properties
- BBOX spatial filtering

### 9. Tasks (`/api/interface/tasks?job_id={id}`) ✅

Workflow visualization for specific jobs:
- Visual stage diagram with predefined workflows
- Task counts per stage (P/Q/R/C/F badges)
- Color-coded stage status
- Expandable task detail sections
- Click stage to scroll to details

**Task Status Legend**:
- **P** (Purple) = Pending - Task created, message sent
- **Q** (Gray) = Queued - Queue trigger opened message
- **R** (Amber) = Processing - Handler running
- **C** (Green) = Completed - Success
- **F** (Red) = Failed - Error

### 10. Jobs (`/api/interface/jobs`) ✅

Job monitor dashboard with:
- Jobs table sorted by creation time
- Status filtering
- Click to view task details

### 11. Map (`/api/interface/map`) ✅

Full-page interactive Leaflet map:
- Collection selector
- Feature limit controls
- Click polygons for property popups
- Hover highlighting
- Zoom to features

### 12. API Docs (`/api/interface/docs`) ✅

Interactive API documentation:
- Endpoint reference
- Request/response examples

## Implementation Guide

### Creating a New Interface

1. **Create folder and files**:
   ```bash
   mkdir web_interfaces/myinterface
   touch web_interfaces/myinterface/__init__.py
   touch web_interfaces/myinterface/interface.py
   ```

2. **Create the `__init__.py`**:
   ```python
   """MyInterface module."""
   from .interface import MyInterface

   __all__ = ['MyInterface']
   ```

3. **Implement the interface**:
   ```python
   # web_interfaces/myinterface/interface.py
   """
   MyInterface module.

   Description of what this interface does.

   Features (DD MMM YYYY):
       - Feature 1
       - Feature 2

   Exports:
       MyInterface: Brief description
   """

   import azure.functions as func
   from web_interfaces.base import BaseInterface
   from web_interfaces import InterfaceRegistry

   @InterfaceRegistry.register('myinterface')
   class MyInterface(BaseInterface):
       """MyInterface dashboard."""

       def render(self, request: func.HttpRequest) -> str:
           content = self._generate_html_content()
           custom_css = self._generate_custom_css()
           custom_js = self._generate_custom_js()

           return self.wrap_html(
               title="My Interface",
               content=content,
               custom_css=custom_css,
               custom_js=custom_js
           )

       def _generate_html_content(self) -> str:
           return """<div class="container"><h1>My Interface</h1></div>"""

       def _generate_custom_css(self) -> str:
           return """/* Custom styles */"""

       def _generate_custom_js(self) -> str:
           return """// Custom JavaScript"""
   ```

4. **Add auto-import to `web_interfaces/__init__.py`**:
   ```python
   try:
       from .myinterface import interface as _myinterface
       logger.info("✅ Imported MyInterface module")
   except ImportError as e:
       logger.warning(f"⚠️ Could not import MyInterface: {e}")
   ```

5. **Optionally add to navbar** in `web_interfaces/base.py`

6. **Access at**: `/api/interface/myinterface`

### Using BaseInterface Utilities

**wrap_html(title, content, custom_css, custom_js, include_navbar=True)**:
- Wraps content in full HTML document
- Includes common CSS (design system colors, reset, utilities)
- Includes common JS (API utilities, error handling)
- Adds navigation bar automatically (unless `include_navbar=False`)

**Common CSS Variables** (available in all interfaces):
```css
var(--ds-blue-primary)
var(--ds-blue-dark)
var(--ds-navy)
var(--ds-cyan)
var(--ds-gold)
var(--ds-gray)
var(--ds-gray-light)
var(--ds-bg)
```

**Common JavaScript Utilities**:
```javascript
API_BASE_URL              // Current origin
fetchJSON(url)            // Fetch with error handling
showSpinner(id)           // Show loading spinner
hideSpinner(id)           // Hide loading spinner
setStatus(msg, isError)   // Display status message
clearStatus()             // Clear status message
```

## Testing

### Local Testing

Start Azure Functions locally:
```bash
func start --port 7072
```

Access interfaces:
- http://localhost:7072/api/interface/home
- http://localhost:7072/api/interface/health
- http://localhost:7072/api/interface/pipeline

### Azure Testing

Production URL:
```
https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/interface/{name}
```

## Recent Changes

### 16 DEC 2025
- ✅ Added PENDING task status to Tasks interface (P/Q/R/C/F badges)
- ✅ Created Queues interface for Service Bus monitoring
- ✅ Created H3 Grid Status interface
- ✅ Updated Tasks interface with workflow visualization

### 15 DEC 2025
- ✅ Created Tasks interface with predefined workflow diagrams
- ✅ Created Pipeline interface with jobs table
- ✅ Created Health interface with dynamic tooltips

### Previous Updates
- ✅ Design system implemented across all interfaces
- ✅ STAC collection links made clickable with icons
- ✅ Vector viewer with OGC Features support
- ✅ Full-page Leaflet map interface

## Contributing

When adding new interfaces:
1. Follow the design system color palette
2. Use the provided CSS variables
3. Implement responsive design (mobile-friendly)
4. Add proper error handling with user-friendly messages
5. Include loading states (spinners)
6. Test UTF-8 encoding (especially emojis!)
7. Update this README with new features
8. Add docstring with date and feature list

## Support

For issues or questions:
- Check Application Insights logs (see `docs_claude/APPLICATION_INSIGHTS.md`)
- Review `CLAUDE.md` for project context
- Check `function_app.py` for route definitions
