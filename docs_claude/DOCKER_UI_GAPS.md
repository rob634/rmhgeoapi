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
**Status**: 🚧 IN PROGRESS
**Tests Enabled**: INF-01, INF-02, INF-03, INF-04

**Problem**: Health dashboard only shows Docker Worker health. Many tests require verifying Function App health from the same interface.

**Solution**: Enhance `/interface/health` to show:
- [ ] Function App health status (fetch from FA /api/health)
- [ ] Function App database stats
- [ ] Side-by-side comparison view
- [ ] Clear labeling of which system each component belongs to

**Files to Modify**:
- `templates/pages/admin/health.html`
- `static/js/health.js`
- `static/css/health.css`
- `docker_service.py` (add FA proxy endpoint)

---

### GAP-02: Queue Infrastructure Visibility
**Priority**: HIGH
**Status**: ⏳ PENDING
**Tests Enabled**: INF-05, INF-06, INF-07, INF-08

**Problem**: No UI visibility into Service Bus queue status.

**Solution**: Add queue status panel to health dashboard showing:
- [ ] Queue names (container-tasks, functionapp-tasks)
- [ ] Active message count
- [ ] Dead-letter message count
- [ ] Listener status (Docker listening, FA listening)
- [ ] Last message processed timestamp

**Files to Modify**:
- `templates/pages/admin/health.html` (add queue panel)
- `static/js/health.js` (fetch queue stats)
- `docker_service.py` (add queue stats endpoint)

**API Needed**: `/api/queues/status` or enhance `/health` response

---

### GAP-03: Log Viewing
**Priority**: MEDIUM
**Status**: ⏳ PENDING
**Tests Enabled**: CHK-01, CHK-02, CHK-04, MNT-04

**Problem**: No log viewer in Docker UI. Function App has one in tasks interface.

**Solution**: Add log viewing capability:
- [ ] Job-specific logs panel on job detail page
- [ ] Or standalone `/interface/logs` page
- [ ] Application Insights integration
- [ ] Filter by level (DEBUG, INFO, WARNING, ERROR)
- [ ] Filter by job_id, component

**Files to Create/Modify**:
- `templates/pages/jobs/detail.html` (add logs panel)
- `static/js/jobs.js` (add log fetching)
- `docker_service.py` (add logs endpoint)

**Dependency**: Application Insights query access from Docker worker

---

### GAP-04: TiTiler/STAC Viewer Links
**Priority**: MEDIUM
**Status**: ⏳ PENDING
**Tests Enabled**: RAS-10, RAS-14, VEC-11, VEC-12

**Problem**: Job results don't link to visualization tools.

**Solution**: Add viewer links to job completion results:
- [ ] "View in TiTiler" link for COG outputs
- [ ] "View in STAC Browser" link for STAC items
- [ ] "View in Map" link for vector outputs
- [ ] Links in job detail page results section
- [ ] Links in collections browser item list

**Files to Modify**:
- `templates/pages/jobs/detail.html`
- `templates/pages/browse/collections.html`
- `static/css/jobs.css`

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
| 1 | GAP-01: Cross-System Health | Medium | High | Current |
| 2 | GAP-02: Queue Visibility | Low | High | Current |
| 3 | GAP-04: Viewer Links | Low | Medium | Next |
| 4 | GAP-03: Log Viewing | Medium | Medium | Next |
| 5 | GAP-05: Storage Browser | Medium | Low | Future |
| 6 | GAP-06: API Verification | Low | Low | Future |
| 7 | GAP-07: Test Data Mgmt | Low | Low | Defer |

---

## Completion Tracking

| Gap | Status | Completed | Notes |
|-----|--------|-----------|-------|
| GAP-01 | 🚧 | -- | Starting 25 JAN |
| GAP-02 | ⏳ | -- | |
| GAP-03 | ⏳ | -- | |
| GAP-04 | ⏳ | -- | |
| GAP-05 | ⏳ | -- | |
| GAP-06 | ⏳ | -- | |
| GAP-07 | ⏳ | -- | Deferred |

---

*Document created: 25 JAN 2026*
*Last updated: 25 JAN 2026*
