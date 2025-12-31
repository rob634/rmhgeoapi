## Epic E12: Interface Modernization ✅ Phase 1 Complete

**Business Requirement**: Clean, maintainable admin interfaces with modern interactivity
**Status**: ✅ Phase 1 Complete (24 DEC 2025), Phase 2 (NiceGUI) planned
**Owner**: Geospatial Team
**Documentation**: [NICEGUI.md](docs_claude/NICEGUI.md)

**Strategic Context**:
> Current `web_interfaces/` contains 15 interfaces with ~3,500 LOC of duplicated code.
> Phase 1 cleans up and adds HTMX. Phase 2 evaluates NiceGUI on Docker Web App.

**Architecture**:
```
Phase 1: HTMX (Azure Functions)     Phase 2: NiceGUI (Docker Web App)
┌─────────────────────────────────┐ ┌─────────────────────────────────┐
│ Clean up duplicated code        │ │ Pure Python UI framework        │
│ Add HTMX for interactivity      │ │ Rich components (AG Grid, maps) │
│ Create component library        │ │ WebSocket-based reactivity      │
│ Build Submit Vector interface   │ │ Requires persistent server      │
└─────────────────────────────────┘ └─────────────────────────────────┘
       Works on Azure Functions           Requires Docker Web App
```

---

### Feature F12.1: Interface Cleanup (Enabler) ✅ COMPLETE

**Deliverable**: Consolidated CSS/JS, reusable Python components
**Effort**: 2.5 days
**Completed**: 23 DEC 2025

**Current State Audit (23 DEC 2025)**:
| Metric | Value | Issue |
|--------|-------|-------|
| Duplicated CSS | ~2,000 LOC | Dashboard headers copied 9x |
| Duplicated JS | ~1,500 LOC | Same patterns reimplemented |
| Status badge styles | 4 different | Need standardization |
| Filter implementations | 5 different | Need shared component |
| Largest file | health/interface.py (1,979 LOC) | Needs decomposition |

| Story | Status | Description | Effort | Acceptance Criteria |
|-------|--------|-------------|--------|---------------------|
| S12.1.1 | ✅ | CSS Consolidation | 1 day | Move duplicates to `COMMON_CSS`, remove ~1,500 LOC |
| S12.1.2 | ✅ | JavaScript Utilities | 0.5 day | Add `formatDate()`, `formatBytes()`, `debounce()`, `handleError()` to `COMMON_JS` |
| S12.1.3 | ✅ | Python Component Helpers | 1 day | Add `render_header()`, `render_status_badge()`, `render_card()`, `render_empty_state()`, `render_table()` to `BaseInterface` |

**Key Files**: `web_interfaces/base.py`

---

### Feature F12.2: HTMX Integration ✅ COMPLETE

**Deliverable**: HTMX-powered interactivity without custom JavaScript
**Effort**: 2.5 days (includes Storage refactor + Submit Vector)

| Story | Status | Description | Effort | Acceptance Criteria |
|-------|--------|-------------|--------|---------------------|
| S12.2.1 | ✅ | Add HTMX to BaseInterface | 0.5 day | HTMX loaded in all interfaces, config set |
| S12.2.2 | ✅ | Refactor Storage Interface | 1 day | Zone→Container cascade via `hx-get`, file loading via HTMX |
| S12.2.3 | ✅ | Create Submit Vector Interface | 2 days | File browser, form fields, `hx-post` submission |

**HTMX Patterns**:
```html
<!-- Cascading dropdowns (zone → container) -->
<select name="zone" hx-get="/api/interface/storage/containers"
        hx-target="#container-select" hx-trigger="change">

<!-- Form submission with result display -->
<form hx-post="/api/jobs/submit/process_vector"
      hx-target="#result" hx-swap="innerHTML">

<!-- Auto-polling for job status -->
<div hx-get="/api/jobs/status/{job_id}"
     hx-trigger="every 5s" hx-target="this">
```

**Key Files**: `web_interfaces/base.py`, `web_interfaces/storage/interface.py`, `web_interfaces/submit_vector/interface.py` (new)

---

### Feature F12.3: Interface Migration ✅ COMPLETE

**Deliverable**: All 15 interfaces using new patterns
**Effort**: 2-3 days
**Completed**: 27 DEC 2025

| Story | Status | Description | Priority |
|-------|--------|-------------|----------|
| S12.3.1 | ✅ | Migrate Jobs interface | P1 |
| S12.3.2 | ✅ | Migrate Tasks interface | P1 |
| S12.3.3 | ✅ | Migrate STAC interface | P2 |
| S12.3.4 | ✅ | Migrate Vector interface | P2 |
| S12.3.5 | ✅ | Migrate H3 interface | P2 |
| S12.3.6 | ✅ | Migrate Health interface (decompose 1,979 LOC) | P2 |
| S12.3.7 | ✅ | Migrate remaining interfaces (pipeline, gallery, docs, queues, home, map) | P3 |

**Additional Improvements (27 DEC 2025)**:
- All timestamps display in Eastern Time with "ET" indicator
- Submit Vector success links directly to task dashboard
- Promote interface dropdown loading fixed with retry capability

---

### Feature F12.4: NiceGUI Evaluation 📋 PHASE 2

**Deliverable**: Proof-of-concept NiceGUI app on Docker Web App
**Status**: 📋 Planned after Phase 1 HTMX completion
**Prerequisite**: Existing Docker Web App infrastructure

| Story | Status | Description | Backend Dep |
|-------|--------|-------------|-------------|
| S12.4.1 | 📋 | Create NiceGUI project structure | Docker Web App |
| S12.4.2 | 📋 | Build Storage browser with NiceGUI | `/api/storage/*` ✅ |
| S12.4.3 | 📋 | Build Submit Vector form with NiceGUI | `/api/jobs/submit/*` ✅ |
| S12.4.4 | 📋 | Evaluate developer experience vs HTMX | — |
| S12.4.5 | 📋 | Decision: Migrate more interfaces to NiceGUI? | — |

**NiceGUI Advantages** (if Phase 2 proceeds):
- 60+ UI components (AG Grid, Leaflet maps, charts)
- Pure Python (no HTML/JS strings)
- Reactive data binding
- Tailwind CSS built-in

**NiceGUI Constraints**:
- Requires persistent WebSocket connection
- Cannot run on Azure Functions (serverless)
- Needs Docker Web App or Container Apps

---

### Feature F12.5: Promote Vector Interface ✅ COMPLETE

**Deliverable**: Interface for promoting vector datasets from geo schema to OGC Features
**Status**: ✅ Complete (29 DEC 2025)

| Story | Status | Description |
|-------|--------|-------------|
| S12.5.1 | ✅ | Create promote_vector interface with collection dropdown |
| S12.5.2 | ✅ | Add license selection (CC-BY-4.0, CC-BY-NC-4.0, CC0-1.0) |
| S12.5.3 | ✅ | Integrate with promote service backend |
| S12.5.4 | ✅ | Add success feedback with OGC Features links |

**Key Files**: `web_interfaces/promote_vector/interface.py`

---

### E12 Phased Rollout

```
Phase 1: HTMX (Week 1-2)                    Phase 2: NiceGUI (Week 3+)
┌─────────────────────────────────────┐     ┌─────────────────────────────────┐
│ S12.1.1-3: Cleanup (2.5 days)       │     │ S12.4.1-5: NiceGUI PoC          │
│ S12.2.1: Add HTMX (0.5 day)         │     │ Evaluate on Docker Web App      │
│ S12.2.2: Storage refactor (1 day)   │────▶│ Decision: Expand or stay HTMX   │
│ S12.2.3: Submit Vector (2 days)     │     │                                 │
│ S12.3.*: Migrate others (2-3 days)  │     │                                 │
└─────────────────────────────────────┘     └─────────────────────────────────┘
        Azure Functions                              Docker Web App
```

**Total Phase 1 Effort**: 8-10 days

---

### E12 Success Criteria

**Phase 1 Complete When**:
1. ✅ Duplicated CSS/JS removed from individual interfaces
2. ✅ `BaseInterface` has reusable component methods
3. ✅ Storage interface uses HTMX for dropdowns/file loading
4. ✅ Submit Vector interface works end-to-end
5. ✅ Job submission triggers `process_vector` successfully

**Phase 2 Decision Point**:
After Phase 1, evaluate:
- Is HTMX sufficient for our needs?
- Does NiceGUI's richer component library justify Docker deployment?
- What's the cost/benefit of maintaining two interface patterns?

---

**Last Updated**: 30 DEC 2025 (E7/E8/E9 restructured: E7=Infrastructure, E8=GeoAnalytics, E9=Large Data)
