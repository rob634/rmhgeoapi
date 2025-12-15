# Web Interfaces Module

**Date**: 15 NOV 2025

## Overview

Unified web interface system for the Geospatial API platform. Provides browser-based dashboards for interacting with STAC collections, OGC Features, job monitoring, and more.

## Architecture

### Unified Route Pattern

All web interfaces are accessible via a single dynamic route:

```
/api/interface/{name}
```

**Examples**:
- `/api/interface/stac` - STAC collections dashboard
- `/api/interface/jobs` - Job monitor dashboard
- `/api/interface/vector` - OGC Features viewer (coming soon)
- `/api/interface/docs` - API documentation (coming soon)

### Design Pattern: Template Method + Registry

```
BaseInterface (Abstract)
    ├── Common CSS (Design System colors, typography)
    ├── Common JS (API utilities, error handling)
    ├── wrap_html() - Template wrapper
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
├── __init__.py                  # Registry + unified handler
├── base.py                      # BaseInterface abstract class
│
├── stac/
│   ├── __init__.py
│   └── interface.py             # ✅ STAC Collections Dashboard
│
├── jobs/
│   ├── __init__.py
│   └── interface.py             # ✅ Job Monitor Dashboard
│
├── vector/
│   └── __init__.py              # ⏳ PENDING
│
└── docs/
    └── __init__.py              # ⏳ PENDING
```

## Design System

### Design System Color Palette

Inspired by [datacatalog.worldbank.org](https://datacatalog.worldbank.org/home):

```css
--wb-blue-primary: #0071BC    /* Primary blue - links, buttons */
--wb-blue-dark: #245AAD       /* Dark blue - hover states */
--wb-navy: #053657            /* Navy - headings, text */
--wb-cyan: #00A3DA            /* Cyan - hover accents */
--wb-gold: #FFC14D            /* Gold - highlights */
--wb-gray: #626F86            /* Gray - secondary text */
--wb-gray-light: #e9ecef      /* Light gray - borders */
--wb-bg: #f8f9fa              /* Background gray */
```

### Typography

- **Font Family**: "Open Sans", Arial, sans-serif
- **Headings**: Font weight 700 (bold)
- **Body**: 14px, line-height 1.6
- **Professional, clean, data-focused aesthetic**

### UI Components

**Status Badges**:
- Queued: Gray background
- Processing: Orange/yellow background
- Completed: Green background
- Failed: Red background

**Cards**:
- White background
- Blue left border (4px solid)
- Subtle shadows (0 1px 3px rgba(0,0,0,0.08))
- Rounded corners (3px)

**Navigation Bar**:
- White background
- Blue bottom border (3px solid)
- Links turn cyan on hover
- Grayed out items for coming soon features

## Implemented Interfaces

### 1. STAC Collections Dashboard ✅

**Route**: `/api/interface/stac`
**File**: [stac/interface.py](stac/interface.py)

**Features**:
- Grid view of STAC collections with metadata cards
- Collection detail view with full STAC metadata:
  - Collection ID, title, description
  - Total items count
  - Type (raster/vector with icons)
  - Spatial extent (bbox)
  - Temporal extent
  - License information
  - Providers
  - Keywords/tags
  - STAC version
- **Clickable links** with icons:
  - 🔗 **self** - Collection metadata (JSON)
  - 📄 **items** - Items endpoint (GeoJSON)
  - ⬆️ **parent** - Parent catalog
  - 🏠 **root** - Root catalog
- Items table (text display, clickable coming soon)
- Search and filter by name/type
- Stats banner (total collections, total items)

**API**: `/api/stac/collections`, `/api/stac/collections/{id}`

### 2. Job Monitor Dashboard ✅

**Route**: `/api/interface/jobs`
**File**: [jobs/interface.py](jobs/interface.py)

**Features**:
- Jobs table from `app.jobs` database table
- Displays:
  - Job ID (truncated: first 8 + last 8 chars)
  - Job Type (process_raster, process_raster_collection, etc.)
  - Status with colored badges (queued, processing, completed, failed)
  - **Stage Progress**: Current stage / total stages (e.g., "4/4")
  - **Task Counts**:
    - Q: queued tasks
    - P: processing tasks
    - C: completed tasks
    - F: failed tasks
  - Created & Updated timestamps
- Controls:
  - 🔄 Refresh button
  - Status filter dropdown
  - Limit filter (10, 25, 50, 100)
- Stats banner:
  - Total jobs displayed
  - Count by status (queued, processing, completed, failed)
- Click job row for details (placeholder - full implementation coming soon)

**API**: `/api/dbadmin/jobs`, `/api/dbadmin/tasks`

## Pending Interfaces

### 3. Vector Viewer (OGC Features) ⏳

**Route**: `/api/interface/vector` (planned)
**Status**: Placeholder folder created, awaiting implementation

**Planned Features**:
- Interactive Leaflet map
- Collection selector dropdown
- Load features with limit controls
- Simplification and precision parameters
- Click polygons for property popups
- Zoom to features
- Feature count display

**Current Status**:
- Static HTML version exists in Azure Storage $web container
- Needs to be migrated to web_interfaces module for consistency
- Will use same Design System design system

### 4. API Documentation ⏳

**Route**: `/api/interface/docs` (planned)
**Status**: Placeholder folder created, awaiting implementation

**Planned Features**:
- Interactive API explorer
- Endpoint documentation
- Request/response examples
- Try-it-out functionality
- Authentication guides

### 5. Staging Container Browser ⏳

**Navbar Item**: "Staging Container" (grayed out)
**Status**: Placeholder in navigation, no implementation yet

**Planned Features**:
- Browse rmhazuregeobronze container contents
- File metadata display
- Preview capabilities
- Initiate ETL jobs from browser
- File size/type filtering

## Navigation

The global navigation bar (rendered by `BaseInterface._render_navbar()`) includes:

```
🛰️ Geospatial API

[STAC Collections] [OGC Features] [Staging Container] [Job Monitor] [API Docs]
     ✅               ⏳                 ⏳                ✅            ⏳
```

- **Blue links**: Active and clickable
- **Gray text**: Coming soon (not yet implemented)

## Implementation Guide

### Creating a New Interface

1. **Create folder and file**:
   ```bash
   mkdir web_interfaces/myinterface
   touch web_interfaces/myinterface/__init__.py
   touch web_interfaces/myinterface/interface.py
   ```

2. **Implement the interface**:
   ```python
   # web_interfaces/myinterface/interface.py
   import azure.functions as func
   from web_interfaces.base import BaseInterface
   from web_interfaces import InterfaceRegistry

   @InterfaceRegistry.register('myinterface')
   class MyInterface(BaseInterface):
       def render(self, request: func.HttpRequest) -> str:
           content = "<h1>My Interface</h1>"
           custom_css = "/* Custom styles */"
           custom_js = "/* Custom JavaScript */"

           return self.wrap_html(
               title="My Interface",
               content=content,
               custom_css=custom_css,
               custom_js=custom_js
           )
   ```

3. **Add auto-import to web_interfaces/__init__.py**:
   ```python
   try:
       from .myinterface import interface as _myinterface
       logger.info("✅ Imported MyInterface module")
   except ImportError as e:
       logger.warning(f"⚠️ Could not import MyInterface: {e}")
   ```

4. **Access at**: `/api/interface/myinterface`

### Using BaseInterface Utilities

**wrap_html(title, content, custom_css, custom_js)**:
- Wraps your content in full HTML document
- Includes common CSS (Design System colors, reset, utilities)
- Includes common JS (API utilities, error handling)
- Adds navigation bar automatically
- Handles responsive design

**Common CSS Variables** (available in all interfaces):
```css
var(--wb-blue-primary)
var(--wb-navy)
var(--wb-gray)
/* etc. */
```

**Common JavaScript Utilities**:
```javascript
API_BASE_URL              // Current origin
fetchJSON(url)            // Fetch with error handling
showSpinner(id)           // Show loading spinner
hideSpinner(id)           // Hide loading spinner
setStatus(msg, isError)   // Display status message
```

## Testing

### Local Testing

Start Azure Functions locally:
```bash
func start --port 7072
```

Access interfaces:
- http://localhost:7072/api/interface/stac
- http://localhost:7072/api/interface/jobs

### Azure Testing

Production URLs (replace with your function app URL):
```
https://rmhazuregeoapi-{hash}.eastus-01.azurewebsites.net/api/interface/stac
https://rmhazuregeoapi-{hash}.eastus-01.azurewebsites.net/api/interface/jobs
```

## Recent Changes

### 15 NOV 2025
- ✅ Design System design system implemented across all interfaces
- ✅ "Vector Viewer" renamed to "OGC Features" in navbar
- ✅ "Staging Container" placeholder added to navbar
- ✅ STAC collection links made clickable with icons (🔗📄⬆️🏠)
- ✅ Job Monitor dashboard created from scratch
- ✅ UTF-8 encoding issues resolved (emoji corruption fixed)

### Key Design Decisions

**Why Design System Design?**
- Professional, data-focused aesthetic
- Clean and accessible
- Familiar to data professionals
- Anodyne enough to not distract from content

**Why Unified Route Pattern?**
- Single entry point for all web UIs
- Consistent URL structure
- Easy to add new interfaces without modifying function_app.py
- Clean separation of concerns

**Why Template Method Pattern?**
- DRY principle - common functionality in base class
- Consistent look and feel across all interfaces
- Easy to update global styles/scripts
- Interfaces only implement their unique content

## Future Enhancements

### Short Term
1. **Make STAC items clickable** - Click to see full STAC item metadata
2. **Job detail view** - Click job row to see full task breakdown
3. **Implement Vector Viewer** - Migrate from $web, add Design System styling
4. **Add pagination** - For jobs table and collections grid

### Medium Term
5. **Real-time updates** - WebSocket or polling for job status
6. **Filtering and search** - Advanced query capabilities
7. **Export functionality** - Download filtered data as CSV/JSON
8. **User preferences** - Save filter settings, default views

### Long Term
9. **Staging Container browser** - Full implementation
10. **API Documentation** - Interactive docs with try-it-out
11. **Admin dashboard** - System health, metrics, logs
12. **Data lineage visualization** - Track data flow through pipeline

## Known Issues

- ⚠️ Jobs interface shows task counts from `result_data.tasks_by_status` which may not be present in all jobs
- ⚠️ STAC items table is text-only (not clickable yet)
- ⚠️ Vector and Docs interfaces are placeholders

## Contributing

When adding new interfaces:
1. Follow the Design System design system
2. Use the provided CSS variables
3. Implement responsive design (mobile-friendly)
4. Add proper error handling
5. Include loading states (spinners)
6. Test UTF-8 encoding (especially emojis!)
7. Update this README with new features

## Support

For issues or questions:
- Check Application Insights logs (see docs_claude/APPLICATION_INSIGHTS_QUERY_PATTERNS.md)
- Review CLAUDE.md for project context
- Check function_app.py for route definitions
