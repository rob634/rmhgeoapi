# Web Interface Architecture

**Last Updated**: 21 NOV 2025
**Author**: Robert and Geospatial Claude Legion

---

## Overview

This document describes the unified web interface architecture for the Geospatial API platform. All web interfaces follow a consistent design pattern using the `BaseInterface` class and `InterfaceRegistry` for automatic route registration.

**Key URL Pattern**: `/api/interface/{name}`

---

## Architecture: Read-Only UI vs CoreMachine ETL

### Web Interfaces (Presentation Layer - READ-ONLY)

```
┌──────────────────────────────────────────────────────────────────┐
│  WEB INTERFACES - PRESENTATION LAYER (UI Operations)             │
│  Purpose: Browse, view, and inspect data (READ-ONLY)             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  /api/interface/stac      → STAC Collections Dashboard           │
│  /api/interface/vector    → OGC Features Collections Browser     │
│  /api/interface/jobs      → Job Monitor Dashboard                │
│  /api/interface/tasks     → Task Detail View                     │
│  /api/interface/pipeline  → Pipeline Dashboard (Bronze Browser)  │
│  /api/interface/docs      → API Documentation                    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Read-Only Operations:                                   │    │
│  │  • Direct database queries (SELECT only)                 │    │
│  │  • Direct Azure Storage reads (list blobs, get metadata) │    │
│  │  • Synchronous HTTP responses (< 1 second)               │    │
│  │  • No side effects on data                               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  NO JOBS | NO TASKS | NO SERVICE BUS | NO BACKGROUND WORKERS     │
└──────────────────────────────────────────────────────────────────┘
```

### CoreMachine ETL (Processing Layer - READ/WRITE)

```
┌──────────────────────────────────────────────────────────────────┐
│  COREMACHINE - PROCESSING LAYER (ETL Operations)                 │
│  Purpose: Process, transform, and analyze data (READ/WRITE)      │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  /api/jobs/submit/{job_type}  → Submit processing job            │
│  /api/jobs/status/{job_id}    → Check job status                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Asynchronous Processing:                                │    │
│  │  • Creates Job records in PostgreSQL                     │    │
│  │  • Creates Task records in PostgreSQL                    │    │
│  │  • Sends messages to Service Bus queues                  │    │
│  │  • Background workers process tasks                      │    │
│  │  • Results stored in database JSONB columns              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  JOBS → TASKS → SERVICE BUS → WORKERS → DATABASE                 │
│  Response Time: Minutes to hours (depending on data size)        │
└──────────────────────────────────────────────────────────────────┘
```

### Key Comparison

| Feature | Web Interfaces (UI) | CoreMachine (ETL) |
|---------|---------------------|-------------------|
| **Purpose** | Browse/view data | Process/transform data |
| **Creates Jobs?** | NO | YES |
| **Creates Tasks?** | NO | YES |
| **Writes to DB?** | NO (read-only) | YES (job/task records) |
| **Service Bus?** | NO | YES |
| **Async Processing?** | NO (synchronous) | YES (background workers) |
| **Response Time** | < 1 second | Minutes to hours |
| **Use Case** | "Show me what's available" | "Process this data" |

---

## Implemented Interfaces

### STAC Collections Dashboard
- **Route**: `/api/interface/stac`
- **File**: `web_interfaces/stac/interface.py`
- **Purpose**: Browse STAC collections with item counts
- **Features**:
  - Collection cards with metadata
  - Item counts from pgSTAC
  - Click card → collection detail view
  - Links to STAC API endpoints

### OGC Features Collections Browser
- **Route**: `/api/interface/vector`
- **File**: `web_interfaces/vector/interface.py`
- **Purpose**: Browse OGC API - Features collections
- **Features**:
  - Grid view of PostGIS collections
  - Feature counts and spatial extents
  - Links to OGC Features API endpoints
  - "View Map" button → Leaflet map viewer

### Vector Collection Map Viewer
- **Route**: `/api/vector/viewer?collection={id}`
- **Files**: `vector_viewer/service.py`, `vector_viewer/triggers.py`
- **Purpose**: Interactive map preview for data curators
- **Features**:
  - Leaflet map with OSM base layer
  - Load 100/500/All features buttons
  - **Simplification parameter** (meters) for geometry simplification
  - Feature popups with properties
  - QA approve/reject buttons (placeholder)

### Job Monitor Dashboard
- **Route**: `/api/interface/jobs`
- **File**: `web_interfaces/jobs/interface.py`
- **Purpose**: Monitor CoreMachine job execution
- **Features**:
  - Jobs table with status filtering
  - Stage progress (stage N/total)
  - Task counts by status (Q/P/C/F)
  - Click job row → navigates to Tasks dashboard
  - Refresh and filter controls

### Task Detail Dashboard
- **Route**: `/api/interface/tasks?job_id={id}`
- **File**: `web_interfaces/tasks/interface.py`
- **Purpose**: View tasks for a specific job
- **Features**:
  - Job metadata header
  - Tasks grouped by stage
  - Expandable task sections
  - Error details for failed tasks
  - Result data JSON viewer
  - Back button to Jobs dashboard

### API Documentation
- **Route**: `/api/interface/docs`
- **File**: `web_interfaces/docs/interface.py`
- **Purpose**: Interactive API reference
- **Features**:
  - Categorized endpoint listing
  - Request/response examples
  - Try-it functionality

---

## In Progress: Pipeline Dashboard

### Purpose
Browse Bronze container files and prepare data for processing.

### Route
`/api/interface/pipeline`

### New API Endpoints (Read-Only)

```
GET /api/containers/{container_name}/blobs
    ?prefix={folder_path}     # Optional: filter by path
    &limit={number}           # Optional: max results (default: 50)

    Returns: {"blobs": [...], "count": N}

GET /api/containers/{container_name}/blobs/{blob_path}

    Returns: Single blob metadata object
```

### Architecture

```
Pipeline Dashboard (UI)
    │
    ▼
GET /api/containers/bronze-rasters/blobs?limit=50
    │
    ▼
BlobRepository.list_blobs()  ─── infrastructure/blob.py
    │
    ▼
Azure SDK: container_client.list_blobs()
    │
    ▼
Direct Azure Storage read (NO JOBS, NO TASKS)
```

### Planned Features
1. Container selector (bronze-vectors, bronze-rasters)
2. Prefix/folder filter input
3. Load 10 / Load 50 / Load All buttons
4. Files table (Name, Size, Modified, Type)
5. Click file → Detail panel with full metadata
6. Placeholder for job submission (future)

---

## Technology Stack

### BaseInterface Pattern

All interfaces inherit from `BaseInterface` which provides:
- `wrap_html(title, content, custom_css, custom_js)` - Consistent page structure
- Shared navigation bar
- Common CSS utilities (spinner, hidden class)
- Common JavaScript utilities (fetchJSON, showSpinner)
- API base URL configuration

### InterfaceRegistry Pattern

```python
from web_interfaces import InterfaceRegistry

@InterfaceRegistry.register('myinterface')
class MyInterface(BaseInterface):
    def render(self, request):
        return self.wrap_html(
            title="My Dashboard",
            content="<h1>Hello</h1>",
            custom_css="...",
            custom_js="..."
        )

# Now /api/interface/myinterface works automatically!
```

### Design System (World Bank-Inspired)

```css
/* Primary Colors */
--primary-blue: #0071BC;
--primary-dark: #053657;
--accent-cyan: #00A3DA;

/* Status Colors */
--success: #10B981;  /* Completed */
--warning: #F59E0B;  /* Processing */
--error: #DC2626;    /* Failed */
--neutral: #626F86;  /* Queued */

/* Typography */
font-family: 'Open Sans', -apple-system, sans-serif;

/* Common Elements */
- Cards with blue left border (4px solid #0071BC)
- Status badges with colored backgrounds
- Tables with hover highlighting
- Responsive grid layouts
```

---

## OGC Features Map Viewer (Static Website)

### Live URL
`https://rmhazuregeo.z13.web.core.windows.net/`

### Features
- Leaflet interactive map
- Collection selector dropdown
- Feature count controls (50-1000)
- **Simplification parameter input** (meters)
- Click polygons → popup with properties
- Hover → highlight features
- Zoom to features button

### File Location
`ogc_features/map.html` → Deployed to Azure Static Website (`$web` container)

---

## File Structure

```
web_interfaces/
├── __init__.py              # InterfaceRegistry, unified_interface_handler
├── base.py                  # BaseInterface class
├── stac/
│   ├── __init__.py
│   └── interface.py         # STAC Collections Dashboard
├── vector/
│   ├── __init__.py
│   └── interface.py         # OGC Features Collections Browser
├── jobs/
│   ├── __init__.py
│   └── interface.py         # Job Monitor Dashboard
├── tasks/
│   ├── __init__.py
│   └── interface.py         # Task Detail Dashboard
├── docs/
│   ├── __init__.py
│   └── interface.py         # API Documentation
└── pipeline/                # IN PROGRESS
    ├── __init__.py
    └── interface.py         # Pipeline Dashboard (Bronze Browser)

vector_viewer/
├── __init__.py
├── service.py               # HTML generation + simplification support
└── triggers.py              # HTTP trigger handler

ogc_features/
└── map.html                 # Static map viewer (deployed to Azure)
```

---

## Adding a New Interface

### Step 1: Create Interface Module

```python
# web_interfaces/myinterface/__init__.py
# (empty file or module init)

# web_interfaces/myinterface/interface.py
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

@InterfaceRegistry.register('myinterface')
class MyInterface(BaseInterface):
    def render(self, request):
        content = "<h1>My Dashboard</h1>"
        return self.wrap_html(
            title="My Dashboard",
            content=content,
            custom_css="",
            custom_js=""
        )
```

### Step 2: Import in Registry

```python
# web_interfaces/__init__.py (add at bottom)
try:
    from .myinterface import interface as _myinterface
    logger.info("✅ Imported MyInterface module")
except ImportError as e:
    logger.warning(f"⚠️ Could not import MyInterface: {e}")
```

### Step 3: Deploy and Access

```bash
func azure functionapp publish rmhazuregeoapi --python --build remote

# Access at:
# https://rmhazuregeoapi-.../api/interface/myinterface
```

---

## Future Enhancements

### Pipeline Dashboard Extensions
- [ ] Silver container browser (processed COGs)
- [ ] Gold container browser (exports)
- [ ] Direct job submission from file selection
- [ ] Batch file selection for multi-file jobs

### Job Monitor Extensions
- [ ] Real-time job status updates (WebSocket/polling)
- [ ] Job cancellation button
- [ ] Retry failed tasks button

### Cross-Interface Navigation
- [ ] "View in TiTiler" from STAC items
- [ ] "Submit Job" from Pipeline file browser
- [ ] "View Results" from Job Monitor to STAC

---

## Related Documentation

- `docs_claude/CLAUDE_CONTEXT.md` - Primary project context
- `docs_claude/COREMACHINE_PLATFORM_ARCHITECTURE.md` - Two-layer architecture
- `docs_claude/SERVICE_BUS_HARMONIZATION.md` - Service Bus configuration
- `JOB_CREATION_QUICKSTART.md` - JobBaseMixin pattern for new jobs
