# Docker Worker UI - Gap Tracking

**Created**: 25 JAN 2026
**Source**: V0.8_TESTING_PLAN.md gap analysis
**Status**: IN PROGRESS

---

## Overview

This document tracks UI gaps identified when comparing the Docker Worker web interface against the V0.8 Testing Plan requirements. Each gap is tracked with implementation status.

**Coverage Summary**:
- Total V0.8 Tests: 68
- Testable via UI: 40 (59%)
- Requires CLI/Portal: 28 (41%)

---

## Gap Tracking

### GAP-01: Cross-System Health Visibility
**Priority**: HIGH
**Status**: ✅ COMPLETE (25 JAN 2026)
**Tests Enabled**: INF-01, INF-02, INF-03, INF-04

**Problem**: Health dashboard only shows Docker Worker health. Many tests require verifying Function App health from the same interface.

**Solution**: Enhance `/interface/health` to show:
- [x] Function App health status (fetch from FA /api/health)
- [x] Function App database stats (via `/api/proxy/fa/dbadmin/stats`)
- [x] Side-by-side comparison view (system status cards)
- [x] Clear labeling of which system each component belongs to

**Implementation**:
- Added `/api/proxy/fa/health` endpoint to docker_service.py
- Added `/api/proxy/fa/dbadmin/stats` endpoint to docker_service.py
- Updated health.html with system status grid (Docker + FA cards)
- Updated health.html with FA components section (collapsible)
- Updated health.js with `fetchFunctionAppHealth()` function
- Updated health.js with `updateSystemStatusCard()` and `renderFunctionAppComponents()`
- Added CSS for system status cards and FA section

**Files Modified**:
- `templates/pages/admin/health.html`
- `static/js/health.js`
- `static/css/health.css`
- `docker_service.py`

---

### GAP-02: Queue Infrastructure Visibility
**Priority**: HIGH
**Status**: ✅ COMPLETE (25 JAN 2026)
**Tests Enabled**: INF-05, INF-06, INF-07, INF-08

**Problem**: No UI visibility into Service Bus queue status.

**Solution**: Add queue status panel to health dashboard showing:
- [x] Queue names (geospatial-jobs, container-tasks, functionapp-tasks)
- [x] Active message count
- [x] Dead-letter message count
- [x] Scheduled message count
- [x] Listener status with links to listener pages
- [x] Last accessed timestamp
- [x] Queue purge functionality (active and DLQ) with confirmation

**Implementation**:
- Added `/api/queues/status` endpoint to docker_service.py
- Added `/api/queues/{queue_name}/purge` endpoint with confirm=yes requirement
- Added queue status panel to health.html
- Added `fetchQueueStatus()`, `renderQueueStatus()`, `renderQueueCard()` to health.js
- Added `confirmPurgeQueue()`, `purgeQueue()` functions for queue clearing
- Added comprehensive CSS styling for queue cards

**Files Modified**:
- `templates/pages/admin/health.html`
- `static/js/health.js`
- `static/css/health.css`
- `docker_service.py`

---

### GAP-03: Log Viewing
**Priority**: MEDIUM
**Status**: ✅ COMPLETE (25 JAN 2026)
**Tests Enabled**: CHK-01, CHK-02, CHK-04, MNT-04

**Problem**: No log viewer in Docker UI. Function App has one in tasks interface.

**Solution**: Standalone `/interface/logs` page with:
- [x] Application Insights integration via Azure REST API
- [x] Filter by severity level (Verbose, Info, Warning, Error, Critical)
- [x] Filter by time range (5m, 15m, 30m, 1h, 3h, 6h, 24h)
- [x] Filter by source (traces, requests, exceptions, dependencies)
- [x] Filter by job_id
- [x] Text search in messages
- [x] Quick filter buttons (Errors, Jobs, Tasks, Service Bus, Database, STAC)
- [x] Log detail modal with full message and custom dimensions
- [x] Summary stats (total, errors, warnings, info counts)
- [x] UUID and task ID highlighting in messages

**Implementation**:
- Added `/interface/logs` route to docker_service.py
- Added `/api/logs/query` endpoint using Azure Monitor REST API
- Created `templates/pages/logs/index.html`
- Created `static/js/logs.js` with full log viewer functionality
- Created `static/css/logs.css` with comprehensive styling

**Files Created/Modified**:
- `templates/pages/logs/index.html` (new)
- `static/js/logs.js` (new)
- `static/css/logs.css` (new)
- `docker_service.py`

---

### GAP-04: TiTiler/STAC Viewer Links
**Priority**: MEDIUM
**Status**: ✅ COMPLETE (25 JAN 2026)
**Tests Enabled**: RAS-10, RAS-14, VEC-11, VEC-12

**Problem**: Job results don't link to visualization tools. Curators need to inspect raster output data before approval.

**Solution**: Created standalone Raster Curator interface (`/interface/raster/viewer`) with:
- [x] Leaflet map with TiTiler tile layers (20% sidebar, 80% map)
- [x] Collection and item browsing from STAC API
- [x] Band selection with RGB presets (Natural Color, Infrared, SWIR, etc.)
- [x] Stretch controls (Auto, 2-98%, 5-95%, Min-Max, Custom)
- [x] Colormap selection (15+ curated options)
- [x] Per-band statistics display (min/max/mean/std/percentiles)
- [x] Point query on map click for pixel values
- [x] Raster metadata display (dimensions, CRS, data type, nodata)
- [x] QA Approve/Reject buttons wired to approval workflow
- [x] Navigation links added to navbar

**Implementation**:
- Added `/interface/raster/viewer` and `/interface/raster/viewer/{collection_id}` routes
- Added `/api/raster/collections` endpoint
- Added `/api/raster/stats` endpoint (TiTiler proxy)
- Added `/api/raster/info` endpoint (TiTiler proxy)
- Added `/api/raster/point` endpoint (TiTiler proxy)

**Files Created/Modified**:
- `templates/pages/raster/viewer.html` (new)
- `static/js/raster-viewer.js` (new)
- `static/css/raster-viewer.css` (new)
- `templates/components/navbar.html` (added Raster Viewer link)
- `docker_service.py` (added raster viewer routes and API endpoints)

---

### GAP-04b: Vector Curator Interface
**Priority**: MEDIUM
**Status**: ✅ COMPLETE (25 JAN 2026)
**Tests Enabled**: VEC-11, VEC-12 (vector data quality review)

**Problem**: Curators need to inspect vector output data before approval, similar to raster viewer.

**Solution**: Created standalone Vector Curator interface (`/interface/vector/viewer`) with:
- [x] MapLibre GL JS map (20% sidebar, 80% map) - WebGL for smooth rendering
- [x] MVT (Mapbox Vector Tiles) mode for high-performance rendering of large datasets
- [x] GeoJSON mode for full attribute access with configurable feature limit
- [x] Layer mode toggle between MVT and GeoJSON
- [x] Collection browsing from OGC Features / TiPG
- [x] Styling controls (fill color, stroke color, opacity, stroke width, point radius)
- [x] Feature inspection on click with popup and sidebar display
- [x] Schema/attribute list display
- [x] Collection metadata display (geometry type, CRS, extent)
- [x] QA Approve/Reject buttons wired to approval workflow
- [x] API links (TileJSON, Collection, Items, TiPG Map)
- [x] Navigation links added to navbar

**Implementation**:
- Added `/interface/vector/viewer` and `/interface/vector/viewer/{collection_id}` routes
- Added `/api/vector/collections` endpoint
- Added `/api/vector/collection/{id}` endpoint
- Added `/api/vector/features/{id}` endpoint (OGC Features proxy)

**Files Created/Modified**:
- `templates/pages/vector/viewer.html` (new)
- `static/js/vector-viewer.js` (new)
- `static/css/vector-viewer.css` (new)
- `templates/components/navbar.html` (added Vector Viewer link)
- `docker_service.py` (added vector viewer routes and API endpoints)

---

### GAP-05: Standalone Storage Browser
**Priority**: LOW
**Status**: ⏳ PENDING
**Tests Enabled**: Test data verification

**Problem**: Storage browser only available within Submit flow, not standalone.

**Solution**: Create dedicated storage browser page:
- [ ] `/interface/storage` route
- [ ] Browse all zones (bronze, silver, gold)
- [ ] File details (size, modified, type)
- [ ] Preview capability for small files
- [ ] Direct links to blob URLs

**Files to Create**:
- `templates/pages/browse/storage.html`
- `static/css/storage.css`
- `docker_service.py` (add storage route)

---

### GAP-06: API Response Verification
**Priority**: LOW
**Status**: ⏳ PENDING
**Tests Enabled**: REG-03, REG-04, ERR-01

**Problem**: No way to verify API response formats in UI.

**Solution**: Options (pick one):
- [ ] Option A: Add "API Explorer" page
- [ ] Option B: Enhance collections browser with raw JSON view
- [ ] Option C: Accept `/docs` (FastAPI Swagger UI) is sufficient

**Decision**: Use existing `/docs` endpoint for API testing. Add JSON view toggle to collections browser as enhancement.

---

### GAP-07: Test Data Management
**Priority**: LOW
**Status**: ⏳ PENDING
**Tests Enabled**: Test data setup verification

**Problem**: No dedicated interface for managing test data.

**Solution**: Add test data helper (optional):
- [ ] List files in test-data/ prefix
- [ ] Show required vs present test files
- [ ] Upload test files with correct paths
- [ ] Generate sample test data

**Decision**: Defer - can use standalone storage browser (GAP-05) instead.

---

## Implementation Order

| Order | Gap | Effort | Impact | Sprint |
|-------|-----|--------|--------|--------|
| 1 | GAP-01: Cross-System Health | Medium | High | ✅ Done |
| 2 | GAP-02: Queue Visibility | Low | High | ✅ Done |
| 3 | GAP-03: Log Viewing | Medium | Medium | ✅ Done |
| 4 | GAP-04: Raster Curator | Medium | High | ✅ Done |
| 4b | GAP-04b: Vector Curator | Medium | High | ✅ Done |
| 5 | GAP-05: Storage Browser | Medium | Low | Future |
| 6 | GAP-06: API Verification | Low | Low | Future |
| 7 | GAP-07: Test Data Mgmt | Low | Low | Defer |

---

## Completion Tracking

| Gap | Status | Completed | Notes |
|-----|--------|-----------|-------|
| GAP-01 | ✅ | 25 JAN 2026 | Cross-system health with proxy endpoints |
| GAP-02 | ✅ | 25 JAN 2026 | Queue status + purge with DLQ visibility |
| GAP-03 | ✅ | 25 JAN 2026 | Standalone log viewer with App Insights |
| GAP-04 | ✅ | 25 JAN 2026 | Raster Curator interface with TiTiler integration |
| GAP-04b | ✅ | 25 JAN 2026 | Vector Curator interface with MapLibre + TiPG |
| GAP-05 | ⏳ | -- | Standalone Storage Browser |
| GAP-06 | ⏳ | -- | |
| GAP-07 | ⏳ | -- | Deferred |

---

*Document created: 25 JAN 2026*
*Last updated: 25 JAN 2026*
