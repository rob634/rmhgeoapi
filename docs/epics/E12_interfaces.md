## Epic E12: Integration Onboarding UI 🚧

**Type**: Enabler
**Value Statement**: "Hi! Here's how to integrate me!" — Self-service onboarding for integrators.
**Runs On**: E1, E2, E8, E9 (Data APIs)
**Status**: 🚧 PARTIAL (Enablers ✅, Core Interfaces 📋)
**Last Updated**: 13 JAN 2026
**Owner**: Geospatial Team

**Strategic Context**:
> This isn't just an admin dashboard. It's an *onboarding experience* for anyone integrating with the platform.
> Every button shows the raw API call (CURL command in a nearby box). It's designed to:
>
> 1. Enable operators to manage pipelines without CLI/database access
> 2. **Teach other teams how to integrate** — this is the real purpose
> 3. Define the interaction patterns consumers will eventually implement
> 4. Be so helpful that copying it is the path of least resistance

**The CURL Box Strategy**:
```
┌─────────────────────────────────────────────────────┐
│  [Submit Vector Job]                                │
│                                                     │
│  curl -X POST https://api.geo.../jobs/submit/vector│
│    -H "Content-Type: application/json"              │
│    -d '{"container": "bronze", "blob": "data.shp"}'│
│                                                     │
│  📋 Copy to clipboard                               │
└─────────────────────────────────────────────────────┘
```
Every button says "this is what you would copy." When integrators replicate this UI, they're copying example code that calls *your* APIs with *your* contracts.

**Feature Summary**:
| Feature | Status | Description |
|---------|--------|-------------|
| F12.1 | ✅ | Interface Cleanup (Enabler) |
| F12.2 | ✅ | HTMX Integration (Enabler) |
| F12.3 | ✅ | Interface Migration (Enabler) |
| F12.EN1 | 📋 | Helper Enhancements (Enabler) |
| F12.4 | 📋 | System Dashboard |
| F12.5 | 📋 | Pipeline Workflow Hub |
| F12.6 | 📋 | STAC & Raster Collections Browser |
| F12.7 | 📋 | OGC Features Collections Browser |
| F12.8 | 📋 | API Documentation Hub |
| SP12.9 | ✅ | NiceGUI Evaluation Spike (Not Pursuing) |
| SP12.10 | 📋 | MapLibre H3 Visualization Spike |

**Architecture**:
```
Integration Onboarding UI (Azure Functions + HTMX)
┌─────────────────────────────────────────────────────────────────────┐
│  Every interface includes: [Action Button] + [CURL Box] + [Copy]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  F12.4: System Dashboard     F12.5: Pipeline Workflow Hub           │
│  ┌─────────────────────┐     ┌─────────────────────────────────┐   │
│  │ Architecture Map    │     │ Process Vector  │ Process Raster│   │
│  │ Health Components   │     │ Raster Collection │ H3 Pipelines│   │
│  │ [curl /api/health]  │     │ [curl /api/jobs/submit/...]     │   │
│  └─────────────────────┘     └─────────────────────────────────┘   │
│                                                                     │
│  F12.6: STAC/Raster          F12.7: OGC Features                   │
│  ┌─────────────────────┐     ┌─────────────────────────────────┐   │
│  │ Collection Cards    │     │ Collection Cards                │   │
│  │ [curl /api/stac/..] │     │ [curl /api/features/..]         │   │
│  └─────────────────────┘     └─────────────────────────────────┘   │
│                                                                     │
│  F12.8: API Documentation Hub                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Swagger UI  │  Integration Guides  │  Copy-Paste Examples   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
        Built on: BaseInterface + HTMX + Component Helpers
```

---

# ENABLERS (Foundation)

### Feature F12.1: Interface Cleanup ✅ COMPLETE

**Deliverable**: Consolidated CSS/JS, reusable Python components
**Completed**: 23 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S12.1.1 | ✅ | CSS Consolidation - move duplicates to `COMMON_CSS` |
| S12.1.2 | ✅ | JavaScript Utilities - add `formatDate()`, `formatBytes()`, `debounce()` to `COMMON_JS` |
| S12.1.3 | ✅ | Python Component Helpers - add `render_header()`, `render_status_badge()`, `render_card()` to `BaseInterface` |

**Key Files**: `web_interfaces/base.py`

---

### Feature F12.2: HTMX Integration ✅ COMPLETE

**Deliverable**: HTMX-powered interactivity without custom JavaScript
**Completed**: 24 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S12.2.1 | ✅ | Add HTMX to BaseInterface - loaded in all interfaces |
| S12.2.2 | ✅ | Refactor Storage Interface - zone→container cascade via `hx-get` |
| S12.2.3 | ✅ | Create Submit Vector Interface - file browser + `hx-post` submission |

**HTMX Patterns Established**:
```html
<!-- Cascading dropdowns -->
<select hx-get="/api/..." hx-target="#container" hx-trigger="change">

<!-- Form submission -->
<form hx-post="/api/jobs/submit/..." hx-target="#result">

<!-- Auto-polling -->
<div hx-get="/api/jobs/status/{id}" hx-trigger="every 5s">
```

**Key Files**: `web_interfaces/base.py`, `web_interfaces/storage/`, `web_interfaces/submit_vector/`

---

### Feature F12.3: Interface Migration ✅ COMPLETE

**Deliverable**: All 15+ interfaces using HTMX patterns
**Completed**: 27 DEC 2025

| Story | Status | Description |
|-------|--------|-------------|
| S12.3.1 | ✅ | Migrate Jobs interface |
| S12.3.2 | ✅ | Migrate Tasks interface |
| S12.3.3 | ✅ | Migrate STAC interface |
| S12.3.4 | ✅ | Migrate Vector interface |
| S12.3.5 | ✅ | Migrate H3 interface |
| S12.3.6 | ✅ | Migrate Health interface |
| S12.3.7 | ✅ | Migrate remaining interfaces (pipeline, gallery, docs, queues, home, map) |

**Key Files**: `web_interfaces/*/interface.py`

---

### Feature F12.EN1: Helper Enhancements 📋 PLANNED

**Deliverable**: Enhanced component helpers for Phase 2 interfaces
**Reference**: `INTERFACE_MODERNIZATION.md`

| Story | Status | Description |
|-------|--------|-------------|
| S12.EN1.1 | 📋 | Enhance `render_hx_select()` - add `hx_include` parameter support |
| S12.EN1.2 | 📋 | Create `render_htmx_table()` helper - table with HTMX attributes |
| S12.EN1.3 | 📋 | Create `render_state_container()` helper - loading + empty + error in one call |
| S12.EN1.4 | 📋 | Create `web_interfaces/COMPONENTS.md` - document all helpers with examples |

**Helper Usage Gap** (from INTERFACE_MODERNIZATION.md audit):
- 17 component helpers exist in `base.py`
- Only 3 are actively used (4% usage rate)
- Target: 80%+ usage after refactoring

---

# CORE INTERFACES

### Feature F12.4: System Dashboard 📋 PLANNED

**Deliverable**: Unified system health and architecture overview
**Endpoint**: `/api/interface/dashboard` (new) or enhanced `/api/interface/health`

| Story | Status | Description |
|-------|--------|-------------|
| S12.4.1 | 📋 | Refactor `health/interface.py` using component helpers |
| S12.4.2 | 📋 | Add architecture component map (visual diagram of system components) |
| S12.4.3 | 📋 | Add Function App resource cards (CPU, RAM, runtime, instance count) |
| S12.4.4 | 📋 | Add health check component cards (database, storage, queues, TiTiler) |
| S12.4.5 | 📋 | Add database schema summary section (app, geo, pgstac, h3 schemas) |

**Dashboard Sections**:
```
┌─────────────────────────────────────────────────────────────────┐
│ SYSTEM DASHBOARD                                                │
├─────────────────────────────────────────────────────────────────┤
│ Architecture Component Map                                      │
│ ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐         │
│ │ Function│──▶│ Service │──▶│ PostGIS │   │ TiTiler │         │
│ │ App     │   │ Bus     │   │ Database│   │ Raster  │         │
│ └─────────┘   └─────────┘   └─────────┘   └─────────┘         │
├─────────────────────────────────────────────────────────────────┤
│ Environment & Resources                                         │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│ │ CPU: 45% │ │ RAM: 2GB │ │ Runtime  │ │ Instances│           │
│ │          │ │ / 3.5GB  │ │ Python   │ │ 2 active │           │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────────┤
│ Health Check Components                                         │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│ │ Database │ │ Storage  │ │ Service  │ │ TiTiler  │           │
│ │ ✅ OK    │ │ ✅ OK    │ │ Bus ✅   │ │ ✅ OK    │           │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
├─────────────────────────────────────────────────────────────────┤
│ Database Schemas                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ app: jobs, tasks, job_metrics | geo: 12 collections      │   │
│ │ pgstac: 2 collections, 847 items | h3: res 2-7, 5 sources│   │
│ └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Key Files**: `web_interfaces/health/interface.py`, `web_interfaces/platform/interface.py`

**Backend Dependencies**:
- `/api/health` - component health checks ✅
- `/api/platform/status` - environment info ✅
- `/api/dbadmin/stats` - schema statistics ✅

---

### Feature F12.5: Pipeline Workflow Hub 📋 PLANNED

**Deliverable**: Unified pipeline submission and job monitoring
**Endpoint**: `/api/interface/pipeline` (enhanced)

| Story | Status | Description |
|-------|--------|-------------|
| S12.5.1 | 📋 | Create unified pipeline hub layout with workflow cards |
| S12.5.2 | 📋 | Add Process Vector workflow card (link to submit-vector) |
| S12.5.3 | 📋 | Add Process Raster workflow card (link to submit-raster) |
| S12.5.4 | 📋 | Add Process Raster Collection workflow card |
| S12.5.5 | 📋 | Add H3 Pipelines workflow card (aggregation, export) |
| S12.5.6 | 📋 | Add completed jobs summary table (recent 20, filterable) |
| S12.5.7 | 📋 | Refactor `submit-vector/` and `submit-raster/` using helpers |

**Pipeline Hub Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│ PIPELINE WORKFLOW HUB                                           │
├─────────────────────────────────────────────────────────────────┤
│ Available Pipelines                                             │
│ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐          │
│ │ 📦 Process    │ │ 🗺️ Process    │ │ 📚 Raster     │          │
│ │ Vector        │ │ Raster        │ │ Collection    │          │
│ │               │ │               │ │               │          │
│ │ GeoJSON/SHP   │ │ GeoTIFF→COG   │ │ Batch ingest  │          │
│ │ → PostGIS     │ │ → STAC        │ │ with STAC     │          │
│ │ [Launch →]    │ │ [Launch →]    │ │ [Launch →]    │          │
│ └───────────────┘ └───────────────┘ └───────────────┘          │
│ ┌───────────────┐ ┌───────────────┐                            │
│ │ ⬡ H3 Raster   │ │ ⬡ H3 Export   │                            │
│ │ Aggregation   │ │ Dataset       │                            │
│ │               │ │               │                            │
│ │ COG → H3      │ │ H3 → OGC      │                            │
│ │ zonal stats   │ │ Features      │                            │
│ │ [Launch →]    │ │ [Launch →]    │                            │
│ └───────────────┘ └───────────────┘                            │
├─────────────────────────────────────────────────────────────────┤
│ Recent Jobs                                          [View All] │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ Job ID      │ Type           │ Status    │ Created       │  │
│ │ abc123...   │ process_vector │ ✅ Done   │ 5 min ago     │  │
│ │ def456...   │ process_raster │ 🔄 Running│ 12 min ago    │  │
│ │ ghi789...   │ h3_aggregation │ ✅ Done   │ 1 hour ago    │  │
│ └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Files**: `web_interfaces/pipeline/interface.py`, `web_interfaces/submit_vector/`, `web_interfaces/submit_raster/`

**Backend Dependencies**:
- `/api/jobs/submit/*` - job submission ✅
- `/api/jobs/status/*` - job polling ✅
- `/api/dbadmin/jobs` - job listing ✅

---

### Feature F12.6: STAC & Raster Collections Browser 📋 PLANNED

**Deliverable**: Browse and preview STAC collections and raster items
**Endpoint**: `/api/interface/stac` (enhanced)

| Story | Status | Description |
|-------|--------|-------------|
| S12.6.1 | 📋 | Refactor `stac/interface.py` using component helpers |
| S12.6.2 | 📋 | Add collection card grid with thumbnails from TiTiler |
| S12.6.3 | 📋 | Add raster viewer integration (click to view on map) |
| S12.6.4 | 📋 | Add filter/search capabilities (by collection, date, bbox) |

**STAC Browser Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│ STAC & RASTER COLLECTIONS                    [Search...] 🔍    │
├─────────────────────────────────────────────────────────────────┤
│ Filter: [All Collections ▼] [Date Range] [Bbox]                │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                │
│ │ [thumbnail] │ │ [thumbnail] │ │ [thumbnail] │                │
│ │             │ │             │ │             │                │
│ │ system-     │ │ mapspam-    │ │ fathom-     │                │
│ │ rasters     │ │ production  │ │ flood       │                │
│ │ 47 items    │ │ 156 items   │ │ 892 items   │                │
│ │ [View →]    │ │ [View →]    │ │ [View →]    │                │
│ └─────────────┘ └─────────────┘ └─────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

**Key Files**: `web_interfaces/stac/interface.py`, `web_interfaces/gallery/interface.py`, `web_interfaces/raster_viewer/`

**Backend Dependencies**:
- `/api/stac/collections` - collection list ✅
- `/api/stac/collections/{id}/items` - item list ✅
- TiTiler `/preview` endpoint for thumbnails ✅

---

### Feature F12.7: OGC Features Collections Browser 📋 PLANNED

**Deliverable**: Browse and preview OGC Features (vector) collections
**Endpoint**: `/api/interface/vector` (enhanced)

| Story | Status | Description |
|-------|--------|-------------|
| S12.7.1 | 📋 | Refactor `vector/interface.py` using component helpers |
| S12.7.2 | 📋 | Add collection card grid with feature counts |
| S12.7.3 | 📋 | Add map viewer links (click to view on map) |
| S12.7.4 | 📋 | Add promote status indicators (promoted vs unpromoted) |

**OGC Features Browser Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│ OGC FEATURES COLLECTIONS                     [Search...] 🔍    │
├─────────────────────────────────────────────────────────────────┤
│ Filter: [All ▼] [Promoted Only ☐]                              │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                │
│ │ 📍          │ │ 📍          │ │ 📍          │                │
│ │ kenya_      │ │ rwanda_     │ │ ethiopia_   │                │
│ │ admin1      │ │ buildings   │ │ roads       │                │
│ │ 47 features │ │ 12,456 feat │ │ 8,923 feat  │                │
│ │ ✅ Promoted │ │ 📋 Pending  │ │ ✅ Promoted │                │
│ │ [Map] [API] │ │ [Map] [Pro] │ │ [Map] [API] │                │
│ └─────────────┘ └─────────────┘ └─────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

**Key Files**: `web_interfaces/vector/interface.py`, `web_interfaces/map/`, `web_interfaces/promoted_viewer/`

**Backend Dependencies**:
- `/api/features/collections` - collection list ✅
- `/api/vector/viewer` - map viewer ✅
- `/api/promote/status` - promotion status ✅

---

### Feature F12.8: API Documentation Hub 📋 PLANNED

**Deliverable**: Unified API documentation with integration guides
**Endpoint**: `/api/interface/docs` (enhanced)

| Story | Status | Description |
|-------|--------|-------------|
| S12.8.1 | 📋 | Create unified docs landing page with sections |
| S12.8.2 | 📋 | Integrate Swagger UI (link to `/api/interface/swagger`) |
| S12.8.3 | 📋 | Add DDH Platform integration guide |
| S12.8.4 | 📋 | Add job submission examples (curl, Python) |
| S12.8.5 | 📋 | Add data access patterns guide (OGC Features, STAC, Raster) |

**Documentation Hub Layout**:
```
┌─────────────────────────────────────────────────────────────────┐
│ API DOCUMENTATION                                               │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│ │ 📖 API          │ │ 🔗 Platform     │ │ 📝 Examples     │    │
│ │ Reference       │ │ Integration     │ │                 │    │
│ │                 │ │                 │ │                 │    │
│ │ OpenAPI 3.0     │ │ DDH Integration │ │ Job Submission  │    │
│ │ Swagger UI      │ │ Authentication  │ │ Data Access     │    │
│ │ [View →]        │ │ [View →]        │ │ [View →]        │    │
│ └─────────────────┘ └─────────────────┘ └─────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│ Quick Links                                                     │
│ • Swagger UI: /api/interface/swagger                           │
│ • OpenAPI JSON: /api/openapi.json                              │
│ • Health Check: /api/health                                    │
├─────────────────────────────────────────────────────────────────┤
│ Data Access Patterns                                            │
│ ┌───────────────────────────────────────────────────────────┐  │
│ │ OGC Features    │ GET /api/features/collections/{id}/items│  │
│ │ STAC Catalog    │ GET /api/stac/collections/{id}/items   │  │
│ │ Raster Extract  │ GET /api/raster/point?item_id=&lon=&lat│  │
│ │ H3 Analytics    │ GET /api/h3/stats?iso3=&resolution=    │  │
│ └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Files**: `web_interfaces/docs/interface.py`, `web_interfaces/swagger/`

**Backend Dependencies**:
- `/api/openapi.json` - OpenAPI spec ✅
- `/api/interface/swagger` - Swagger UI ✅

---

# BACKLOG

### Spike SP12.9: NiceGUI Evaluation ✅ COMPLETE (Not Pursuing)

**Deliverable**: Evaluate NiceGUI as alternative to HTMX
**Status**: ✅ COMPLETE - **Decision: Not pursuing NiceGUI**
**Completed**: 07 JAN 2026

| Story | Status | Description |
|-------|--------|-------------|
| SP12.9.1 | ✅ | Evaluated NiceGUI architecture |
| SP12.9.2 | ✅ | Compared with HTMX approach |
| SP12.9.3 | ✅ | Assessed deployment requirements |
| SP12.9.4 | ✅ | **Decision: Stay with HTMX** |

**Decision Rationale**:
- NiceGUI requires persistent WebSocket → cannot run on Azure Functions
- Would need separate Docker deployment (Container Apps)
- HTMX approach working well, simpler architecture
- No compelling benefit to justify additional infrastructure

---

### Spike SP12.10: MapLibre H3 Visualization 📋 PLANNED

**Deliverable**: Evaluate MapLibre GL JS for H3 hexagonal data visualization using vector tiles
**Status**: 📋 PLANNED
**Dependencies**: TiPG vector tile server (E8)

| Story | Status | Description |
|-------|--------|-------------|
| SP12.10.1 | 📋 | Research MapLibre GL JS integration patterns for HTMX interfaces |
| SP12.10.2 | 📋 | Prototype TiPG vector tile endpoint for H3 data (`h3` schema tables) |
| SP12.10.3 | 📋 | Implement basic H3 hexagon rendering with MapLibre fill-extrusion |
| SP12.10.4 | 📋 | Add interactive features (hover tooltips, click for details) |
| SP12.10.5 | 📋 | Evaluate performance with large H3 datasets (resolution 4-7) |
| SP12.10.6 | 📋 | Document integration pattern and decision |

**Context**:
The H3 visualization use case requires rendering hexagonal grids with statistical data (flood exposure, crop production, etc.) at various resolutions. MapLibre GL JS is the leading open-source alternative to Mapbox GL JS and supports vector tiles natively.

**Technical Approach**:
```
TiPG (Vector Tiles)              MapLibre GL JS
┌─────────────────────┐         ┌─────────────────────────────────┐
│ h3.fathom_stats     │         │ Vector Tile Layer               │
│ h3.crop_production  │───MVT──▶│ ├── H3 hexagon polygons         │
│ h3.population       │ tiles   │ ├── fill-color by value         │
└─────────────────────┘         │ ├── fill-extrusion for 3D       │
                                │ └── hover/click interactivity   │
PostgreSQL + PostGIS            └─────────────────────────────────┘
┌─────────────────────┐
│ H3 index → geometry │  (h3_cell_to_boundary_wkb)
│ aggregated stats    │
└─────────────────────┘
```

**Key Questions to Answer**:
1. Can TiPG serve H3 geometries efficiently (PostGIS h3 extension)?
2. What's the optimal tile zoom → H3 resolution mapping?
3. How to handle multi-resolution datasets (res 2 at zoom 4, res 7 at zoom 10)?
4. Performance with ~500K hexagons at resolution 7?

**Spike Output**:
- Working prototype in `web_interfaces/h3_map/` (if successful)
- Performance benchmarks for various H3 resolutions
- Go/No-Go decision for full implementation

**Alternative Approaches** (if MapLibre doesn't work):
- Deck.gl H3HexagonLayer (WebGL-based, more complex integration)
- Pre-rendered GeoJSON (simpler but limited scalability)
- Leaflet with custom H3 plugin (less performant for large datasets)

---

# SUMMARY

## Story Counts

| Feature | Stories | Status |
|---------|:-------:|--------|
| F12.1: Interface Cleanup | 3 | ✅ Complete |
| F12.2: HTMX Integration | 3 | ✅ Complete |
| F12.3: Interface Migration | 7 | ✅ Complete |
| F12.EN1: Helper Enhancements | 4 | 📋 Planned |
| F12.4: System Dashboard | 5 | 📋 Planned |
| F12.5: Pipeline Workflow Hub | 7 | 📋 Planned |
| F12.6: STAC & Raster Browser | 4 | 📋 Planned |
| F12.7: OGC Features Browser | 4 | 📋 Planned |
| F12.8: API Documentation Hub | 5 | 📋 Planned |
| SP12.9: NiceGUI Spike | 4 | ✅ Complete (Not Pursuing) |
| SP12.10: MapLibre H3 Spike | 6 | 📋 Planned |
| **Total** | **52** | |

## Implementation Order

```
Phase 1 (Complete)           Phase 2 (Current)
┌─────────────────────┐     ┌─────────────────────────────────────┐
│ F12.1: Cleanup ✅    │     │ F12.EN1: Helper Enhancements        │
│ F12.2: HTMX ✅       │────▶│ F12.4: System Dashboard             │
│ F12.3: Migration ✅  │     │ F12.5: Pipeline Workflow Hub        │
└─────────────────────┘     │ F12.6: STAC & Raster Browser        │
                            │ F12.7: OGC Features Browser         │
                            │ F12.8: API Documentation Hub        │
                            └─────────────────────────────────────┘
```

## Related Documents

- `INTERFACE_MODERNIZATION.md` - Detailed refactoring plan and helper analysis
- `web_interfaces/base.py` - Component helpers (lines 1930-2690)
- `docs_claude/ARCHITECTURE_REFERENCE.md` - System architecture

---

**Last Updated**: 13 JAN 2026 (Added SP12.10 MapLibre H3 Visualization spike)
