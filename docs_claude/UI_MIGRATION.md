# UI Migration Plan: Function App → Docker/Jinja2

**Created**: 23 JAN 2026
**Status**: Planning
**Reference Implementation**: `/Users/robertharrison/python_builds/rmhtitiler`

---

## Executive Summary

This document outlines the migration of web interfaces from inline Python f-strings in the Azure Function App to a proper Jinja2 template system in the Docker worker application. The migration will reduce code by ~60%, improve maintainability, enable component reuse, and provide proper static asset caching.

---

## Current State Analysis

### Overall Statistics

| Metric | Value |
|--------|-------|
| **Total Interface Modules** | 36 |
| **Total Lines (interfaces)** | 40,485 |
| **Base Infrastructure** | 3,354 lines (base.py + __init__.py) |
| **Grand Total** | ~44,000 lines |
| **Template Engine** | None - 100% Python f-strings |
| **CSS Location** | 943 lines embedded in base.py |
| **JS Location** | 578 lines embedded in base.py |
| **Component Reuse** | None - all inline HTML strings |

### Base Infrastructure Files

| File | Lines | Purpose |
|------|-------|---------|
| `web_interfaces/base.py` | 2,881 | BaseInterface class, COMMON_CSS (943 lines), COMMON_JS (578 lines), HTMX utilities |
| `web_interfaces/__init__.py` | 473 | InterfaceRegistry, unified_interface_handler, routing |

---

## Complete Web Interface Module Inventory

### Priority 1: System Health (FIRST)

| Module | Lines | Purpose | HTMX Partials | Phase |
|--------|-------|---------|---------------|-------|
| `health` | 2,910 | System health dashboard | Yes | **Phase 2** |

### Priority 2: Unified Collection Browser (NEW)

This is a **new interface** that will replace separate STAC and Vector browsers:

| Current Modules | Lines | To Be Replaced By |
|-----------------|-------|-------------------|
| `vector` | 944 | Unified Collection Browser |
| `stac` | 1,342 | Unified Collection Browser |
| `stac_collection` | 900 | Collection Detail View |

**Phase 3** will create a single searchable interface for both STAC and OGC Feature collections.

### Priority 3: Job Pipeline (REVIEW BEFORE MIGRATION)

| Module | Lines | Purpose | HTMX Partials | Phase |
|--------|-------|---------|---------------|-------|
| `jobs` | 562 | Job listing, status, resubmit | Yes | Phase 4 |
| `tasks` | 4,378 | Task monitoring, workflow diagrams, Docker progress | Yes | Phase 4 |
| `pipeline` | 897 | Pipeline overview, stage visualization | No | Phase 4 |
| `queues` | 901 | Service Bus queue monitoring | Yes | Phase 4 |
| `execution` | 1,469 | Execution timeline viewer | No | Phase 4 |

**Subtotal: 8,207 lines** - Each interface requires design review before migration.

### Priority 4: Submit Workflows (REVIEW BEFORE MIGRATION)

| Module | Lines | Purpose | HTMX Partials | Phase |
|--------|-------|---------|---------------|-------|
| `submit_vector` | 1,587 | Vector data submission workflow | Yes | Phase 5 |
| `submit_raster` | 1,778 | Raster data submission workflow | Yes | Phase 5 |
| `submit_raster_collection` | 1,643 | Multi-file raster submission | Yes | Phase 5 |
| `upload` | 714 | File upload interface | Yes | Phase 5 |

**Subtotal: 5,722 lines** - Each interface requires design review before migration.

### Priority 5: Map Viewers (REVIEW BEFORE MIGRATION)

| Module | Lines | Purpose | HTMX Partials | Phase |
|--------|-------|---------|---------------|-------|
| `map` | 665 | General map viewer (Leaflet) | No | Phase 6 |
| `stac_map` | 905 | STAC items on map | No | Phase 6 |
| `h3_map` | 827 | H3 hexagon visualization | No | Phase 6 |
| `raster_viewer` | 993 | COG/raster tile viewer | No | Phase 6 |
| `fathom_viewer` | 1,019 | FATHOM flood data viewer | No | Phase 6 |
| `vector_tiles` | 946 | Vector tile preview | No | Phase 6 |
| `service_preview` | 923 | External service map preview | No | Phase 6 |

**Subtotal: 6,278 lines**

### Priority 6: Admin & Specialized (REVIEW BEFORE MIGRATION)

| Module | Lines | Purpose | HTMX Partials | Phase |
|--------|-------|---------|---------------|-------|
| `external_services` | 1,749 | External service registry | Yes | Phase 7 |
| `database` | 835 | Database admin interface | Yes | Phase 7 |
| `metrics` | 697 | Pipeline metrics dashboard | No | Phase 7 |
| `platform` | 500 | Platform integration status | No | Phase 7 |
| `integration` | 2,066 | System integration dashboard | No | Phase 7 |
| `storage` | 898 | Blob storage browser | Yes | Phase 7 |
| `promote_vector` | 1,389 | Vector promotion workflow | Yes | Phase 7 |
| `gallery` | 747 | Dataset gallery view | No | Phase 7 |
| `promoted_viewer` | 692 | Promoted datasets browser | No | Phase 7 |

**Subtotal: 9,573 lines**

### Priority 7: Documentation & Utilities (LOW PRIORITY)

| Module | Lines | Purpose | HTMX Partials | Phase |
|--------|-------|---------|---------------|-------|
| `home` | 471 | Landing page, navigation | No | Phase 8 |
| `docs` | 1,332 | API documentation browser | No | Phase 8 |
| `swagger` | 271 | Swagger UI wrapper | No | Phase 8 |
| `redoc` | 194 | ReDoc wrapper | No | Phase 8 |
| `h3` | 656 | H3 index tools | No | Phase 8 |
| `h3_sources` | 554 | H3 data sources | No | Phase 8 |
| `zarr` | 1,131 | Zarr/XArray viewer | No | Phase 8 |

**Subtotal: 4,609 lines**

---

## Current Architecture Pain Points

### 1. Massive Inline HTML Strings

**Problem**: Interface files contain thousands of lines of HTML as Python f-strings.

```python
# CURRENT: tasks/interface.py has 4,378 lines like this
def _generate_html_content(self):
    return f"""
    <div class="container">
        <div class="dashboard-header">
            <h1>Task Monitor</h1>
            <!-- 200+ more lines of HTML -->
        </div>
        <!-- More sections... -->
    </div>
    """
```

**Impact**:
- No syntax highlighting in IDE
- String escaping nightmares
- Cannot unit test components
- Difficult to maintain

### 2. Duplicated Component Code

**Problem**: Same UI patterns implemented multiple times.

| Component | Duplicated In | Approx. Duplicate Lines |
|-----------|---------------|-------------------------|
| Modal dialog | vector, stac, promote_vector, tasks, jobs, storage, submit_* | ~1,400 |
| Status badges | 15+ interfaces | ~300 |
| Data tables | 12+ interfaces | ~600 |
| Confirmation dialogs | 8+ interfaces | ~400 |
| Navbar | 8 custom implementations | ~200 |

**Total Duplication**: ~3,000 lines that could be 1 macro each

### 3. CSS/JS Regenerated Every Request

**Problem**: 1,521 lines of CSS/JS parsed as Python strings on every page load.

```python
# base.py lines 36-978: COMMON_CSS (943 lines)
# base.py lines 979-1556: COMMON_JS (578 lines)
```

**Impact**: No browser caching, slower response times, higher CPU usage

### 4. Inconsistent Patterns

| Pattern | Used By | Issues |
|---------|---------|--------|
| `wrap_html()` | 25 interfaces | Good, but limited |
| Custom `<!DOCTYPE>` | 8 interfaces | Duplicates base layout |
| `htmx_partial()` | 12 interfaces | Magic string fragment names |

### 5. No Component Testing

**Problem**: All UI rendering is end-to-end in `render()` method.

**Impact**: Cannot test modal logic, card rendering, or form behavior in isolation.

---

## Target Architecture: Jinja2 in Docker App

### Reference Implementation

The rmhtitiler project demonstrates best practices:

```
geotiler/
├── templates/
│   ├── base.html                    # Root layout
│   ├── base_guide.html              # Specialized base
│   ├── components/
│   │   ├── navbar.html              # Navigation
│   │   ├── footer.html              # Footer
│   │   ├── macros.html              # Reusable macros
│   │   └── _health_fragment.html    # HTMX partial
│   └── pages/
│       ├── admin/
│       │   ├── index.html
│       │   └── _health_fragment.html
│       ├── cog/landing.html
│       └── ...
├── static/
│   ├── css/styles.css               # Design system
│   └── js/common.js                 # Shared utilities
└── templates_utils.py               # Jinja2 configuration
```

### Proposed Docker App Structure

```
docker_app/
├── templates/
│   ├── base.html                    # Main layout with navbar, footer
│   ├── base_dashboard.html          # Dashboard variant
│   ├── base_map.html                # Map viewer variant
│   ├── components/
│   │   ├── navbar.html
│   │   ├── footer.html
│   │   ├── macros.html              # status_badge, modal, data_table, etc.
│   │   ├── job_card.html
│   │   ├── task_row.html
│   │   └── collection_card.html
│   └── pages/
│       ├── home/index.html
│       ├── jobs/
│       │   ├── list.html
│       │   ├── detail.html
│       │   └── _list_fragment.html
│       ├── tasks/
│       │   ├── list.html
│       │   ├── detail.html
│       │   ├── _workflow_fragment.html
│       │   └── _docker_progress.html
│       ├── submit/
│       │   ├── vector.html
│       │   ├── raster.html
│       │   └── _file_browser.html
│       ├── browse/
│       │   ├── vector.html
│       │   ├── stac.html
│       │   └── storage.html
│       ├── maps/
│       │   ├── viewer.html
│       │   ├── stac_map.html
│       │   └── h3_map.html
│       └── admin/
│           ├── health.html
│           ├── database.html
│           └── services.html
├── static/
│   ├── css/
│   │   ├── styles.css               # Full design system
│   │   └── maps.css                 # Map-specific styles
│   └── js/
│       ├── common.js                # Utilities
│       ├── htmx-helpers.js          # HTMX extensions
│       └── map-utils.js             # Leaflet/MapLibre helpers
└── routers/
    ├── ui_home.py
    ├── ui_jobs.py
    ├── ui_tasks.py
    ├── ui_submit.py
    ├── ui_browse.py
    ├── ui_maps.py
    └── ui_admin.py
```

---

## Key Advantages of Migration

### 1. Code Reduction (~60%)

| Current | After Migration | Reduction |
|---------|-----------------|-----------|
| 40,485 lines (interfaces) | ~16,000 lines (templates + routers) | 60% |
| 2,881 lines (base.py) | ~200 lines (templates_utils.py) | 93% |
| 3,000 lines duplicated | 0 (macros) | 100% |

### 2. Component Reuse

```jinja2
{# components/macros.html - Define once, use everywhere #}

{% macro status_badge(status) %}
<span class="badge badge-{{ status }}">{{ status }}</span>
{% endmacro %}

{% macro modal(id, title) %}
<div id="{{ id }}" class="modal-overlay" style="display:none">
    <div class="modal-content">
        <div class="modal-header">
            <h3>{{ title }}</h3>
            <button onclick="closeModal('{{ id }}')">&times;</button>
        </div>
        <div class="modal-body">{{ caller() }}</div>
    </div>
</div>
{% endmacro %}

{% macro data_table(columns, rows, id='data-table') %}
<table id="{{ id }}" class="data-table">
    <thead>
        <tr>
            {% for col in columns %}
            <th>{{ col.label }}</th>
            {% endfor %}
        </tr>
    </thead>
    <tbody>
        {% for row in rows %}
        <tr>
            {% for col in columns %}
            <td>{{ row[col.key] }}</td>
            {% endfor %}
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endmacro %}
```

### 3. Static Asset Caching

```python
# Docker app serves static files with cache headers
app.mount("/static", StaticFiles(directory="static"), name="static")
```

```
GET /static/css/styles.css
Response: 200 OK
Cache-Control: max-age=86400
ETag: "abc123"

GET /static/css/styles.css (subsequent)
Response: 304 Not Modified
```

### 4. IDE Support

| Feature | Current (f-strings) | Jinja2 Templates |
|---------|---------------------|------------------|
| HTML syntax highlighting | No | Yes |
| CSS syntax highlighting | No | Yes |
| JS syntax highlighting | No | Yes |
| HTML autocomplete | No | Yes |
| Linting | No | Yes |
| Emmet abbreviations | No | Yes |

### 5. Development Velocity

| Task | Current Time | With Jinja2 |
|------|--------------|-------------|
| Add new interface | 2-4 hours | 30-60 min |
| Fix modal bug | Edit 8 files | Edit 1 macro |
| Update navbar | Find/replace in 8+ files | Edit 1 file |
| Change color scheme | Modify base.py + interfaces | Edit 1 CSS file |

### 6. Testability

```python
# Unit test a macro
def test_status_badge_renders_correctly():
    template = env.from_string("{% from 'macros.html' import status_badge %}{{ status_badge('completed') }}")
    result = template.render()
    assert 'badge-completed' in result
    assert 'completed' in result
```

---

## Implementation Plan

> **Migration Philosophy**: Each interface will be **reviewed before migration** to identify redesign opportunities. We are not just porting code - we are improving the UI/UX.

---

### Phase 1: Foundation Setup

**Goal**: Set up Jinja2 infrastructure in Docker app

#### Tasks

1. **Create template directory structure**
   ```
   docker_app/templates/
   docker_app/static/
   ```

2. **Configure Jinja2 in FastAPI**
   ```python
   # templates_utils.py
   from starlette.templating import Jinja2Templates
   from pathlib import Path

   templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

   def get_template_context(request, **kwargs):
       return {
           "request": request,
           "version": __version__,
           "tipg_base_url": settings.tipg_base_url,
           **kwargs
       }
   ```

3. **Extract design system to CSS file**
   - Move COMMON_CSS (943 lines) from base.py → static/css/styles.css
   - Add CSS variables for design tokens
   - Organize into sections (layout, components, utilities)

4. **Extract JavaScript utilities**
   - Move COMMON_JS (578 lines) from base.py → static/js/common.js
   - Add HTMX helpers → static/js/htmx-helpers.js

5. **Create base templates**
   ```jinja2
   {# base.html #}
   <!DOCTYPE html>
   <html>
   <head>
       <link rel="stylesheet" href="{{ url_for('static', path='css/styles.css') }}">
       {% block head %}{% endblock %}
   </head>
   <body>
       {% include "components/navbar.html" %}
       <main>{% block content %}{% endblock %}</main>
       {% include "components/footer.html" %}
       <script src="{{ url_for('static', path='js/common.js') }}"></script>
       {% block scripts %}{% endblock %}
   </body>
   </html>
   ```

6. **Create component macros**
   - `status_badge(status)`
   - `modal(id, title)`
   - `data_table(columns, rows)`
   - `confirm_dialog(id, message, action)`
   - `card(title, icon)`
   - `loading_spinner()`

#### Deliverables
- [ ] templates/ directory with base.html, base_dashboard.html
- [ ] static/css/styles.css (full design system)
- [ ] static/js/common.js (utilities)
- [ ] components/macros.html (6+ reusable macros)
- [ ] components/navbar.html, footer.html
- [ ] templates_utils.py (Jinja2 configuration)

---

### Phase 2: System Health Dashboard (TOP PRIORITY)

**Goal**: Migrate and enhance the system health interface

**Why First**: Health dashboard is the primary operational interface - provides visibility into system status, service health, and quick diagnostics. Critical for operations.

#### Current State
- `health/interface.py`: 2,910 lines
- Shows: database status, queue depths, storage accounts, service endpoints
- Has HTMX partials for auto-refresh

#### Tasks

1. **Review current health interface for redesign opportunities**
2. **Create `pages/admin/health.html`**
3. **Create `pages/admin/_health_status.html`** (HTMX partial for auto-refresh)
4. **Create `routers/ui_admin.py`**
5. **Add service status cards using macros**

#### Deliverables
- [ ] Health dashboard in Jinja2
- [ ] Auto-refresh via HTMX working
- [ ] Improved layout and information hierarchy

---

### Phase 3: Unified Collection Browser (NEW INTERFACE)

**Goal**: Create a **new** unified collection browser that combines STAC collections and OGC Feature Collections in one searchable interface

**Why New**: Currently STAC (`stac/interface.py`, 1,342 lines) and Vector/OGC Features (`vector/interface.py`, 944 lines) are separate interfaces. Users must know which type of data they're looking for. A unified browser provides:
- Single search across all geospatial collections
- Consistent card-based display
- Filter by type (raster/vector), date, tags
- Preview on map

#### Design Concept

```
┌─────────────────────────────────────────────────────────────┐
│  Collection Browser                          [Search...]    │
├─────────────────────────────────────────────────────────────┤
│  Filters: [All Types ▼] [All Tags ▼] [Date Range]  [Reset] │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 🛰️ STAC      │  │ 📐 Vector    │  │ 🛰️ STAC      │       │
│  │ Flood Data   │  │ Watersheds   │  │ Elevation    │       │
│  │ 24 items     │  │ 1,234 feat.  │  │ 156 items    │       │
│  │ [View] [Map] │  │ [View] [Map] │  │ [View] [Map] │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

#### Tasks

1. **Design unified collection data model**
   - Common fields: id, title, description, type, bbox, item_count, created_at
   - Type-specific: stac_version (STAC), geometry_type (vector)

2. **Create API endpoint for unified collection list**
   - Aggregates from pgstac + PostGIS metadata tables
   - Returns normalized collection objects

3. **Create `pages/browse/collections.html`**
4. **Create `pages/browse/_collection_card.html`** (reusable component)
5. **Create `pages/browse/_collection_grid.html`** (HTMX partial)
6. **Create collection detail pages**
   - `pages/browse/stac_collection.html`
   - `pages/browse/feature_collection.html`

7. **Create `routers/ui_browse.py`**

#### Deliverables
- [ ] Unified collection browser (NEW)
- [ ] Search across STAC + OGC collections
- [ ] Filter by type, tags, date
- [ ] Collection detail views
- [ ] Map preview integration

---

---

## Job Events System - Progress Tracking Implementation

**Created**: 23 JAN 2026
**Dependencies**: V0.8 Queue Consolidation, CoreMachine
**Purpose**: Enable real-time job progress visibility for both FunctionApp and Docker workers

### Overview

The `app.job_events` table is designed to capture execution events from both FunctionApp workers and Docker workers. This provides a unified progress tracking system regardless of where tasks execute.

### Architecture Context (from V0.8_PLAN.md)

```
┌─────────────────────────────────────────────────────────────────┐
│                        JOB EVENTS FLOW                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Platform API                                                    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────┐     ┌──────────────────┐                       │
│  │ Orchestrator│────▶│ geospatial-jobs  │                       │
│  │             │     │                  │                       │
│  │  RECORDS:   │     └────────┬─────────┘                       │
│  │  JOB_CREATED│              │                                  │
│  │  JOB_STARTED│              ▼                                  │
│  └─────────────┘     ┌────────────────┐                         │
│                      │  CoreMachine   │                         │
│                      │  (Job Router)  │                         │
│                      │                │                         │
│                      │  RECORDS:      │                         │
│                      │  STAGE_STARTED │                         │
│                      │  TASK_QUEUED   │                         │
│                      └───────┬────────┘                         │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              │               │               │                   │
│              ▼               ▼               ▼                   │
│     ┌────────────────┐ ┌──────────────┐                         │
│     │ container-tasks│ │functionapp-  │                         │
│     │     Queue      │ │tasks Queue   │                         │
│     └───────┬────────┘ └──────┬───────┘                         │
│             │                 │                                  │
│             ▼                 ▼                                  │
│     ┌────────────────┐ ┌──────────────┐                         │
│     │ Docker Worker  │ │ FunctionApp  │                         │
│     │                │ │   Worker     │                         │
│     │ RECORDS:       │ │              │                         │
│     │ TASK_STARTED   │ │ RECORDS:     │                         │
│     │ CHECKPOINT     │ │ TASK_STARTED │                         │
│     │ TASK_COMPLETED │ │ TASK_COMPLTD │                         │
│     └────────────────┘ └──────────────┘                         │
│                                                                  │
│     ────────────────────────────────────────────────────        │
│                          ▼                                       │
│                 ┌─────────────────┐                             │
│                 │ app.job_events  │  ◄── UNIFIED EVENT LOG      │
│                 │                 │                             │
│                 │ All events from │                             │
│                 │ ALL workers     │                             │
│                 └─────────────────┘                             │
│                          │                                       │
│                          ▼                                       │
│                 ┌─────────────────┐                             │
│                 │ Job Monitor UI  │                             │
│                 │ (Event Timeline)│                             │
│                 └─────────────────┘                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Event Types (from JobEventType enum)

| Category | Event Types | When Recorded |
|----------|-------------|---------------|
| **Job Lifecycle** | `job_created`, `job_started`, `job_completed`, `job_failed` | Orchestrator/CoreMachine |
| **Stage Events** | `stage_started`, `stage_completed`, `stage_advancement_failed` | CoreMachine stage transitions |
| **Task Events** | `task_queued`, `task_started`, `task_completed`, `task_failed`, `task_retrying` | Task handlers (FunctionApp OR Docker) |
| **Callbacks** | `callback_started`, `callback_success`, `callback_failed` | Platform API callbacks |
| **Checkpoints** | `checkpoint`, `status_update` | Within task handlers |

### Table Schema (Already Defined)

```sql
CREATE TABLE app.job_events (
    event_id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64),                    -- NULL for job-level events
    stage INTEGER,                          -- Stage number
    event_type VARCHAR(50) NOT NULL,        -- JobEventType enum
    event_status VARCHAR(20) DEFAULT 'info', -- success/failure/warning/info/pending
    checkpoint_name VARCHAR(100),           -- For App Insights correlation
    event_data JSONB DEFAULT '{}',          -- Flexible context
    error_message VARCHAR(1000),            -- Error details if failure
    duration_ms INTEGER,                    -- Operation timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_job FOREIGN KEY (job_id) REFERENCES app.jobs(job_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_job_events_job_id ON app.job_events(job_id);
CREATE INDEX idx_job_events_job_time ON app.job_events(job_id, created_at DESC);
CREATE INDEX idx_job_events_task_id ON app.job_events(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX idx_job_events_event_type ON app.job_events(event_type);
```

---

### Implementation Phases

#### Phase 4.1: Infrastructure Layer

**Goal**: Create JobEventRepository for consistent event recording

**File**: `infrastructure/job_event_repository.py`

```python
class JobEventRepository:
    """
    Repository for recording and querying job execution events.

    Used by:
    - CoreMachine (job/stage events)
    - Task handlers in FunctionApp (task events)
    - Task handlers in Docker worker (task events)
    """

    def __init__(self, connection_pool):
        self.pool = connection_pool

    # =========================================================================
    # RECORDING METHODS (called during execution)
    # =========================================================================

    def record_event(self, event: JobEvent) -> int:
        """
        Record a single event to the database.

        Returns:
            event_id of the inserted record
        """
        pass

    def record_job_event(
        self,
        job_id: str,
        event_type: JobEventType,
        event_status: JobEventStatus = JobEventStatus.INFO,
        event_data: Optional[Dict] = None,
        error_message: Optional[str] = None
    ) -> int:
        """Convenience method for job-level events."""
        pass

    def record_task_event(
        self,
        job_id: str,
        task_id: str,
        stage: int,
        event_type: JobEventType,
        event_status: JobEventStatus = JobEventStatus.INFO,
        checkpoint_name: Optional[str] = None,
        event_data: Optional[Dict] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None
    ) -> int:
        """Convenience method for task-level events."""
        pass

    # =========================================================================
    # QUERY METHODS (called by UI)
    # =========================================================================

    def get_events_for_job(
        self,
        job_id: str,
        limit: int = 100,
        event_types: Optional[List[JobEventType]] = None,
        since: Optional[datetime] = None
    ) -> List[JobEvent]:
        """Get events for a job, optionally filtered."""
        pass

    def get_events_for_task(self, task_id: str) -> List[JobEvent]:
        """Get all events for a specific task."""
        pass

    def get_latest_event(self, job_id: str) -> Optional[JobEvent]:
        """Get the most recent event for a job."""
        pass

    def get_event_counts_by_type(self, job_id: str) -> Dict[str, int]:
        """Get count of events by type for a job."""
        pass

    def get_events_timeline(
        self,
        job_id: str,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get events formatted for timeline display.

        Returns list with:
        - timestamp (formatted)
        - event_type
        - event_status
        - summary (human-readable)
        - duration_ms (if available)
        - task_id (if task-level)
        """
        pass
```

**Deliverables**:
- [ ] `infrastructure/job_event_repository.py` created
- [ ] Unit tests for repository methods
- [ ] Export from `infrastructure/__init__.py`

---

#### Phase 4.2: CoreMachine Instrumentation

**Goal**: Record events at key execution points in CoreMachine

**File**: `core/machine.py` (modify existing)

**Instrumentation Points**:

```python
# In CoreMachine.__init__():
self.event_repo = JobEventRepository(self.pool)

# In CoreMachine.submit_job():
def submit_job(self, job_type: str, parameters: dict) -> str:
    job_id = self._generate_job_id(job_type, parameters)

    # Record job creation
    self.event_repo.record_job_event(
        job_id=job_id,
        event_type=JobEventType.JOB_CREATED,
        event_data={"job_type": job_type, "parameters": parameters}
    )

    # ... existing job creation logic ...

    return job_id

# In CoreMachine._advance_to_stage():
def _advance_to_stage(self, job_id: str, stage: int):
    self.event_repo.record_job_event(
        job_id=job_id,
        event_type=JobEventType.STAGE_STARTED,
        event_data={"stage": stage, "stage_name": stage_name}
    )

    # ... existing stage advancement logic ...

# In CoreMachine._queue_task():
def _queue_task(self, job_id: str, task_id: str, task_type: str, stage: int):
    self.event_repo.record_task_event(
        job_id=job_id,
        task_id=task_id,
        stage=stage,
        event_type=JobEventType.TASK_QUEUED,
        event_data={"task_type": task_type, "queue": target_queue}
    )

    # ... existing queue logic ...

# In CoreMachine.process_task_message():
def process_task_message(self, message: dict):
    task_id = message["task_id"]
    job_id = message["job_id"]
    stage = message["stage"]

    # Record task start
    start_time = time.time()
    self.event_repo.record_task_event(
        job_id=job_id,
        task_id=task_id,
        stage=stage,
        event_type=JobEventType.TASK_STARTED
    )

    try:
        result = self._execute_handler(...)
        duration_ms = int((time.time() - start_time) * 1000)

        # Record task completion
        self.event_repo.record_task_event(
            job_id=job_id,
            task_id=task_id,
            stage=stage,
            event_type=JobEventType.TASK_COMPLETED,
            event_status=JobEventStatus.SUCCESS,
            duration_ms=duration_ms,
            event_data={"result_summary": self._summarize_result(result)}
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)

        # Record task failure
        self.event_repo.record_task_event(
            job_id=job_id,
            task_id=task_id,
            stage=stage,
            event_type=JobEventType.TASK_FAILED,
            event_status=JobEventStatus.FAILURE,
            error_message=str(e)[:1000],
            duration_ms=duration_ms
        )
        raise

# In CoreMachine._complete_job():
def _complete_job(self, job_id: str):
    self.event_repo.record_job_event(
        job_id=job_id,
        event_type=JobEventType.JOB_COMPLETED,
        event_status=JobEventStatus.SUCCESS
    )

    # ... existing completion logic ...
```

**Checkpoint Helper** (for use within handlers):

```python
# In core/machine.py or separate module

def record_checkpoint(
    job_id: str,
    task_id: str,
    stage: int,
    checkpoint_name: str,
    data: Optional[Dict] = None
):
    """
    Record a checkpoint event from within a task handler.

    Usage in handler:
        from core.events import record_checkpoint

        record_checkpoint(
            job_id, task_id, stage,
            checkpoint_name="cog_conversion_complete",
            data={"output_size_mb": 45.2}
        )
    """
    event_repo = get_event_repository()
    event_repo.record_task_event(
        job_id=job_id,
        task_id=task_id,
        stage=stage,
        event_type=JobEventType.CHECKPOINT,
        checkpoint_name=checkpoint_name,
        event_data=data or {}
    )
```

**Deliverables**:
- [ ] CoreMachine instrumented with event recording
- [ ] `record_checkpoint()` helper function created
- [ ] Events recorded for: job_created, job_started, job_completed, job_failed
- [ ] Events recorded for: stage_started, stage_completed
- [ ] Events recorded for: task_queued, task_started, task_completed, task_failed
- [ ] Works identically for FunctionApp and Docker workers

---

#### Phase 4.3: API Endpoints

**Goal**: Expose job events via REST API

**File**: `triggers/http/jobs_events.py` (new) or add to existing jobs router

```python
@router.get("/api/jobs/{job_id}/events")
async def get_job_events(
    job_id: str,
    limit: int = Query(default=50, le=500),
    event_type: Optional[str] = None,
    since: Optional[str] = None
) -> List[Dict]:
    """
    Get events for a job.

    Query params:
        limit: Max events to return (default 50)
        event_type: Filter by type (e.g., "task_completed")
        since: ISO timestamp to get events after

    Returns:
        List of event objects with timeline formatting
    """
    pass

@router.get("/api/jobs/{job_id}/events/latest")
async def get_latest_event(job_id: str) -> Optional[Dict]:
    """Get the most recent event for a job."""
    pass

@router.get("/api/jobs/{job_id}/events/summary")
async def get_event_summary(job_id: str) -> Dict:
    """
    Get event summary for a job.

    Returns:
        {
            "total_events": 45,
            "by_type": {"task_completed": 20, "checkpoint": 15, ...},
            "by_status": {"success": 35, "info": 10},
            "first_event": "2026-01-23T10:45:32Z",
            "last_event": "2026-01-23T10:52:14Z",
            "total_duration_ms": 402000
        }
    """
    pass

@router.get("/api/tasks/{task_id}/events")
async def get_task_events(task_id: str) -> List[Dict]:
    """Get all events for a specific task."""
    pass
```

**Deliverables**:
- [ ] `GET /api/jobs/{job_id}/events` endpoint
- [ ] `GET /api/jobs/{job_id}/events/latest` endpoint
- [ ] `GET /api/jobs/{job_id}/events/summary` endpoint
- [ ] `GET /api/tasks/{task_id}/events` endpoint
- [ ] OpenAPI documentation for all endpoints

---

#### Phase 4.4: UI Components

**Goal**: Create reusable event timeline component for job monitoring

**Templates**:

1. **Event Timeline Component**: `templates/components/_event_timeline.html`

```jinja2
{# Event Timeline Component

   Usage:
       {% include "components/_event_timeline.html" with context %}

   Context:
       job_id: Job ID for HTMX polling
       events: Initial events list (optional)
       auto_refresh: Enable auto-refresh (default: true)
       refresh_interval: Seconds between refreshes (default: 5)
#}

<div class="event-timeline"
     id="event-timeline-{{ job_id[:8] }}"
     hx-get="/interface/jobs/{{ job_id }}/events"
     hx-trigger="{{ 'load, every ' ~ (refresh_interval|default(5)) ~ 's' if auto_refresh|default(true) else 'load' }}"
     hx-swap="innerHTML">

    {% if events %}
        {% for event in events %}
            {% include "components/_event_row.html" %}
        {% endfor %}
    {% else %}
        <div class="timeline-loading">
            <div class="spinner"></div>
            <span>Loading events...</span>
        </div>
    {% endif %}
</div>
```

2. **Event Row Component**: `templates/components/_event_row.html`

```jinja2
{# Single Event Row

   Context:
       event: Event object with timestamp, event_type, event_status, etc.
#}

<div class="event-row event-{{ event.event_status }}">
    <div class="event-indicator">
        {% if event.event_status == 'success' %}
            <span class="indicator-dot success"></span>
        {% elif event.event_status == 'failure' %}
            <span class="indicator-dot failure"></span>
        {% elif event.event_status == 'warning' %}
            <span class="indicator-dot warning"></span>
        {% else %}
            <span class="indicator-dot info"></span>
        {% endif %}
    </div>

    <div class="event-time">
        {{ event.created_at | format_time }}
    </div>

    <div class="event-type">
        <span class="event-type-badge {{ event.event_type }}">
            {{ event.event_type | format_event_type }}
        </span>
    </div>

    <div class="event-summary">
        {{ event | format_event_summary }}
        {% if event.duration_ms %}
            <span class="event-duration">({{ event.duration_ms }}ms)</span>
        {% endif %}
    </div>

    {% if event.task_id %}
    <div class="event-task">
        <a href="/interface/tasks/{{ event.task_id }}">
            {{ event.task_id[:8] }}
        </a>
    </div>
    {% endif %}

    {% if event.event_data %}
    <button class="event-expand" onclick="toggleEventData('{{ event.event_id }}')">
        Details
    </button>
    <div id="event-data-{{ event.event_id }}" class="event-data hidden">
        <pre>{{ event.event_data | tojson(indent=2) }}</pre>
    </div>
    {% endif %}
</div>
```

3. **Failure Context Component**: `templates/components/_failure_context.html`

```jinja2
{# Failure Context Panel

   Shows last N events before a failure for debugging.

   Context:
       job_id: Job ID
       failure_event: The failure event
       preceding_events: List of events before failure
#}

<div class="failure-context-panel">
    <div class="failure-header">
        <span class="failure-icon">✖</span>
        <span class="failure-title">
            {{ failure_event.event_type | format_event_type }} at
            {{ failure_event.created_at | format_time }}
        </span>
    </div>

    {% if failure_event.error_message %}
    <div class="failure-message">
        {{ failure_event.error_message }}
    </div>
    {% endif %}

    <div class="failure-timeline">
        <h4>Events Before Failure</h4>
        {% for event in preceding_events %}
            {% include "components/_event_row.html" %}
        {% endfor %}
    </div>

    <div class="failure-actions">
        <button onclick="copyErrorDetails('{{ job_id }}')">Copy Error</button>
        <a href="/interface/jobs/{{ job_id }}/events" class="btn">View All Events</a>
        {% if failure_event.checkpoint_name %}
        <a href="https://portal.azure.com/..." target="_blank" class="btn">
            View in App Insights
        </a>
        {% endif %}
    </div>
</div>
```

**CSS**: Add to `static/css/events.css`

```css
/* Event Timeline Styles */
.event-timeline {
    max-height: 400px;
    overflow-y: auto;
    border: 1px solid #e9ecef;
    border-radius: 6px;
}

.event-row {
    display: grid;
    grid-template-columns: 24px 80px 140px 1fr auto auto;
    gap: 12px;
    align-items: center;
    padding: 10px 16px;
    border-bottom: 1px solid #f0f0f0;
    font-size: 13px;
}

.event-row:hover {
    background: #f8f9fa;
}

.indicator-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}

.indicator-dot.success { background: #10B981; }
.indicator-dot.failure { background: #EF4444; }
.indicator-dot.warning { background: #F59E0B; }
.indicator-dot.info { background: #3B82F6; }

.event-time {
    font-family: 'Courier New', monospace;
    color: #626F86;
    font-size: 11px;
}

.event-type-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
}

.event-type-badge.task_completed { background: #D1FAE5; color: #059669; }
.event-type-badge.task_failed { background: #FEE2E2; color: #DC2626; }
.event-type-badge.checkpoint { background: #E0E7FF; color: #4F46E5; }
.event-type-badge.stage_started { background: #FEF3C7; color: #D97706; }

.event-duration {
    color: #9CA3AF;
    font-size: 11px;
}

/* Failure Context Panel */
.failure-context-panel {
    background: #FEF2F2;
    border: 1px solid #EF4444;
    border-radius: 6px;
    padding: 20px;
    margin: 20px 0;
}

.failure-header {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 16px;
    font-weight: 600;
    color: #DC2626;
    margin-bottom: 12px;
}

.failure-message {
    background: #1F2937;
    color: #FCA5A5;
    padding: 12px 16px;
    border-radius: 4px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    margin-bottom: 16px;
    overflow-x: auto;
}
```

**Deliverables**:
- [ ] `templates/components/_event_timeline.html` created
- [ ] `templates/components/_event_row.html` created
- [ ] `templates/components/_failure_context.html` created
- [ ] `static/css/events.css` created
- [ ] HTMX auto-refresh working
- [ ] Event detail expansion working

---

#### Phase 4.5: Integration with Tasks Interface

**Goal**: Add event timeline to existing task monitoring page

**Modify**: `templates/pages/tasks/detail.html`

```jinja2
{% extends "base.html" %}

{% block content %}
<div class="task-monitor">
    <!-- Existing job summary card -->
    <div class="job-summary-card">
        ...
    </div>

    <!-- Existing workflow diagram -->
    <div class="workflow-diagram">
        ...
    </div>

    <!-- NEW: Event Timeline Panel -->
    <div class="panel event-timeline-panel">
        <div class="panel-header">
            <h3>Event Timeline</h3>
            <div class="panel-controls">
                <label class="toggle">
                    <input type="checkbox" id="auto-refresh-events" checked>
                    <span>Live</span>
                </label>
                <select id="event-filter" onchange="filterEvents(this.value)">
                    <option value="all">All Events</option>
                    <option value="job">Job Events</option>
                    <option value="stage">Stage Events</option>
                    <option value="task">Task Events</option>
                    <option value="checkpoint">Checkpoints</option>
                </select>
            </div>
        </div>

        {% include "components/_event_timeline.html" %}
    </div>

    <!-- Existing task list -->
    <div class="task-list">
        ...
    </div>
</div>
{% endblock %}
```

**Deliverables**:
- [ ] Event timeline integrated into task monitor page
- [ ] Filter by event type working
- [ ] Auto-refresh toggle working
- [ ] Event timeline updates with job progress

---

### Testing Checklist

#### Repository Tests
- [ ] `record_event()` inserts correctly
- [ ] `get_events_for_job()` returns ordered events
- [ ] `get_events_for_task()` filters by task_id
- [ ] `get_latest_event()` returns most recent
- [ ] Pagination works with limit/offset

#### Integration Tests
- [ ] Submit hello_world job → events recorded
- [ ] Submit raster_etl job (Docker) → events recorded
- [ ] Submit vector job (FunctionApp) → events recorded
- [ ] Job failure → failure event recorded with error_message
- [ ] Stage transition → stage events recorded
- [ ] Checkpoint in handler → checkpoint event recorded

#### UI Tests
- [ ] Event timeline loads on task monitor page
- [ ] HTMX auto-refresh updates events
- [ ] Event detail expansion shows event_data
- [ ] Failure context panel shows on failed jobs
- [ ] Filter by event type works

---

### Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Job status visibility | "Processing" | "Stage 2, task xyz (3s ago)" |
| Failure debugging | Check App Insights | Full timeline in UI |
| Stalled job detection | Manual check | Alert if no events for 5 min |
| Cross-worker consistency | Different UIs | Same event timeline |

---

### Phase 4: Job Pipeline Interfaces (REVIEW REQUIRED)

**Goal**: Migrate job monitoring interfaces after design review

**Note**: Before migration, each interface will be reviewed with Robert to identify:
- Features to keep, remove, or add
- Layout improvements
- Better information hierarchy
- Mobile responsiveness needs

#### Interfaces to Review & Migrate

| Interface | Lines | Review Status | Migration Status |
|-----------|-------|---------------|------------------|
| `jobs` | 562 | ⬜ Pending | ⬜ Pending |
| `tasks` | 4,378 | ⬜ Pending | ⬜ Pending |
| `pipeline` | 897 | ⬜ Pending | ⬜ Pending |
| `queues` | 901 | ⬜ Pending | ⬜ Pending |
| `execution` | 1,469 | ⬜ Pending | ⬜ Pending |

#### Deliverables
- [ ] Design review completed for each interface
- [ ] Jobs interface migrated
- [ ] Tasks interface migrated
- [ ] Pipeline interface migrated
- [ ] Queues interface migrated

---

### Phase 5: Submit Workflows (REVIEW REQUIRED)

**Goal**: Migrate submission interfaces after design review

#### Interfaces to Review & Migrate

| Interface | Lines | Review Status | Migration Status |
|-----------|-------|---------------|------------------|
| `submit_vector` | 1,587 | ⬜ Pending | ⬜ Pending |
| `submit_raster` | 1,778 | ⬜ Pending | ⬜ Pending |
| `submit_raster_collection` | 1,643 | ⬜ Pending | ⬜ Pending |
| `upload` | 714 | ⬜ Pending | ⬜ Pending |

#### Deliverables
- [ ] Design review completed for each interface
- [ ] Shared file browser component created
- [ ] All submit interfaces migrated

---

### Phase 6: Map Viewers (REVIEW REQUIRED)

**Goal**: Migrate map-based interfaces after design review

#### Interfaces to Review & Migrate

| Interface | Lines | Review Status | Migration Status |
|-----------|-------|---------------|------------------|
| `map` | 665 | ⬜ Pending | ⬜ Pending |
| `stac_map` | 905 | ⬜ Pending | ⬜ Pending |
| `h3_map` | 827 | ⬜ Pending | ⬜ Pending |
| `raster_viewer` | 993 | ⬜ Pending | ⬜ Pending |
| `fathom_viewer` | 1,019 | ⬜ Pending | ⬜ Pending |
| `vector_tiles` | 946 | ⬜ Pending | ⬜ Pending |
| `service_preview` | 923 | ⬜ Pending | ⬜ Pending |

#### Deliverables
- [ ] base_map.html template created
- [ ] static/js/map-utils.js extracted
- [ ] All map interfaces migrated

---

### Phase 7: Admin & Specialized (REVIEW REQUIRED)

**Goal**: Migrate remaining interfaces after design review

#### Interfaces to Review & Migrate

| Interface | Lines | Review Status | Migration Status |
|-----------|-------|---------------|------------------|
| `database` | 835 | ⬜ Pending | ⬜ Pending |
| `metrics` | 697 | ⬜ Pending | ⬜ Pending |
| `platform` | 500 | ⬜ Pending | ⬜ Pending |
| `external_services` | 1,749 | ⬜ Pending | ⬜ Pending |
| `integration` | 2,066 | ⬜ Pending | ⬜ Pending |
| `storage` | 898 | ⬜ Pending | ⬜ Pending |
| `promote_vector` | 1,389 | ⬜ Pending | ⬜ Pending |
| `gallery` | 747 | ⬜ Pending | ⬜ Pending |
| `promoted_viewer` | 692 | ⬜ Pending | ⬜ Pending |

#### Deliverables
- [ ] Design review completed for each interface
- [ ] All admin interfaces migrated

---

### Phase 8: Documentation & Cleanup

**Goal**: Complete migration and deprecate Function App interfaces

#### Tasks

1. **Migrate remaining interfaces**
   - `home`, `docs`, `swagger`, `redoc`
   - `h3`, `h3_sources`, `zarr`
   - `stac_collection`

2. **Update Function App**
   - Remove web_interfaces/ directory
   - Update routing to redirect to Docker app
   - Function App becomes API-only

3. **Documentation**
   - Update CLAUDE.md with new UI architecture
   - Document Docker app UI routes

#### Deliverables
- [ ] All interfaces migrated
- [ ] Function App serves API only
- [ ] Docker App serves all UI
- [ ] Documentation updated

---

## Migration Checklist Per Interface

For each interface migration:

- [ ] Analyze current interface.py
- [ ] Identify reusable components (extract to macros if new)
- [ ] Create page template(s)
- [ ] Create HTMX partial template(s) if needed
- [ ] Create FastAPI router
- [ ] Test full page render
- [ ] Test HTMX partials
- [ ] Verify mobile responsiveness
- [ ] Update navigation links
- [ ] Document any interface-specific patterns

---

## Risk Mitigation

### Risk 1: Two Systems During Transition

**Mitigation**: Keep Function App interfaces working until Docker versions are verified. Use feature flag to switch traffic.

### Risk 2: HTMX Partial Compatibility

**Mitigation**: Test each HTMX partial thoroughly. Ensure fragment selectors and swap behaviors match.

### Risk 3: CSS/JS Differences

**Mitigation**: Extract CSS/JS from base.py to static files first, before template migration. Verify visual parity.

### Risk 4: Performance Regression

**Mitigation**: Static files should improve performance. Monitor response times during migration.

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Total UI code lines | 44,000 | 18,000 |
| Time to add new interface | 2-4 hours | 30-60 min |
| Time to fix cross-cutting bug | Hours (multiple files) | Minutes (1 file) |
| CSS/JS delivery | Dynamic (every request) | Static (cached) |
| Component test coverage | 0% | 80%+ |

---

## Appendix: Interface Quick Reference

### By Line Count (Descending)

| Rank | Module | Lines | Priority |
|------|--------|-------|----------|
| 1 | tasks | 4,378 | High |
| 2 | health | 2,910 | High |
| 3 | integration | 2,066 | Medium |
| 4 | submit_raster | 1,778 | High |
| 5 | external_services | 1,749 | Medium |
| 6 | submit_raster_collection | 1,643 | High |
| 7 | submit_vector | 1,587 | High |
| 8 | execution | 1,469 | Medium |
| 9 | promote_vector | 1,389 | Medium |
| 10 | stac | 1,342 | Medium |
| 11 | docs | 1,332 | Low |
| 12 | zarr | 1,131 | Low |
| 13 | fathom_viewer | 1,019 | Low |
| 14 | raster_viewer | 993 | Medium |
| 15 | vector_tiles | 946 | Low |
| 16 | vector | 944 | Medium |
| 17 | service_preview | 923 | Low |
| 18 | stac_map | 905 | Medium |
| 19 | queues | 901 | High |
| 20 | stac_collection | 900 | Medium |
| 21 | storage | 898 | Medium |
| 22 | pipeline | 897 | High |
| 23 | database | 835 | Medium |
| 24 | h3_map | 827 | Low |
| 25 | gallery | 747 | Low |
| 26 | upload | 714 | Medium |
| 27 | metrics | 697 | Low |
| 28 | promoted_viewer | 692 | Low |
| 29 | map | 665 | Medium |
| 30 | h3 | 656 | Low |
| 31 | jobs | 562 | High |
| 32 | h3_sources | 554 | Low |
| 33 | platform | 500 | Low |
| 34 | home | 471 | Low |
| 35 | swagger | 271 | Low |
| 36 | redoc | 194 | Low |

### By Category

**Job Pipeline** (High Priority): tasks, jobs, pipeline, queues, execution
**Data Submission** (High Priority): submit_vector, submit_raster, submit_raster_collection, upload
**Data Browsing** (Medium Priority): vector, stac, stac_collection, storage, gallery, promoted_viewer
**Map Viewers** (Medium Priority): map, stac_map, h3_map, raster_viewer, fathom_viewer, vector_tiles, service_preview
**Admin** (Medium Priority): health, database, metrics, external_services, platform, integration
**Specialized** (Low Priority): promote_vector, h3, h3_sources, zarr
**Documentation** (Low Priority): home, docs, swagger, redoc

---

## Next Steps

1. **Review and prioritize** this migration plan
2. **Approve Phase 1** foundation setup
3. **Create GitHub issues** for each phase
4. **Begin Phase 1** implementation

---

*Document maintained by: Claude Code*
*Last updated: 23 JAN 2026*
