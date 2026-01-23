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

### Tier 1: Core Operations (High Priority)

| Module | Lines | Purpose | HTMX Partials | Complexity |
|--------|-------|---------|---------------|------------|
| `tasks` | 4,378 | Task monitoring, workflow diagrams, Docker progress | Yes | High |
| `jobs` | 562 | Job listing, status, resubmit | Yes | Medium |
| `pipeline` | 897 | Pipeline overview, stage visualization | No | Medium |
| `submit_vector` | 1,587 | Vector data submission workflow | Yes | High |
| `submit_raster` | 1,778 | Raster data submission workflow | Yes | High |
| `submit_raster_collection` | 1,643 | Multi-file raster submission | Yes | High |
| `health` | 2,910 | System health dashboard | Yes | Medium |
| `queues` | 901 | Service Bus queue monitoring | Yes | Medium |

**Subtotal: 14,656 lines (36%)**

### Tier 2: Data Browsing (Medium Priority)

| Module | Lines | Purpose | HTMX Partials | Complexity |
|--------|-------|---------|---------------|------------|
| `vector` | 944 | Vector collections browser | Yes | Medium |
| `stac` | 1,342 | STAC collections browser | Yes | Medium |
| `stac_collection` | 900 | Single STAC collection detail | No | Medium |
| `gallery` | 747 | Dataset gallery view | No | Low |
| `promoted_viewer` | 692 | Promoted datasets browser | No | Low |
| `storage` | 898 | Blob storage browser | Yes | Medium |

**Subtotal: 5,523 lines (14%)**

### Tier 3: Map Viewers (Medium Priority)

| Module | Lines | Purpose | HTMX Partials | Complexity |
|--------|-------|---------|---------------|------------|
| `map` | 665 | General map viewer (Leaflet) | No | Medium |
| `stac_map` | 905 | STAC items on map | No | Medium |
| `h3_map` | 827 | H3 hexagon visualization | No | Medium |
| `raster_viewer` | 993 | COG/raster tile viewer | No | Medium |
| `fathom_viewer` | 1,019 | FATHOM flood data viewer | No | Medium |
| `vector_tiles` | 946 | Vector tile preview | No | Medium |
| `service_preview` | 923 | External service map preview | No | Medium |

**Subtotal: 6,278 lines (16%)**

### Tier 4: Admin & System (Lower Priority)

| Module | Lines | Purpose | HTMX Partials | Complexity |
|--------|-------|---------|---------------|------------|
| `external_services` | 1,749 | External service registry | Yes | Medium |
| `database` | 835 | Database admin interface | Yes | Medium |
| `metrics` | 697 | Pipeline metrics dashboard | No | Low |
| `platform` | 500 | Platform integration status | No | Low |
| `execution` | 1,469 | Execution timeline viewer | No | Medium |
| `integration` | 2,066 | System integration dashboard | No | Medium |

**Subtotal: 7,316 lines (18%)**

### Tier 5: Specialized Tools (Lower Priority)

| Module | Lines | Purpose | HTMX Partials | Complexity |
|--------|-------|---------|---------------|------------|
| `promote_vector` | 1,389 | Vector promotion workflow | Yes | Medium |
| `upload` | 714 | File upload interface | Yes | Medium |
| `h3` | 656 | H3 index tools | No | Low |
| `h3_sources` | 554 | H3 data sources | No | Low |
| `zarr` | 1,131 | Zarr/XArray viewer | No | Medium |

**Subtotal: 4,444 lines (11%)**

### Tier 6: Documentation & API Docs (Lowest Priority)

| Module | Lines | Purpose | HTMX Partials | Complexity |
|--------|-------|---------|---------------|------------|
| `home` | 471 | Landing page, navigation | No | Low |
| `docs` | 1,332 | API documentation browser | No | Low |
| `swagger` | 271 | Swagger UI wrapper | No | Low |
| `redoc` | 194 | ReDoc wrapper | No | Low |

**Subtotal: 2,268 lines (6%)**

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

### Phase 1: Foundation Setup (Week 1)

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

### Phase 2: Pilot Migration - Jobs & Tasks (Week 2)

**Goal**: Migrate highest-value interfaces to prove the pattern

#### Tasks

1. **Migrate jobs interface** (562 lines → ~150 lines)
   - Create `pages/jobs/list.html`
   - Create `pages/jobs/detail.html`
   - Create `pages/jobs/_list_fragment.html` (HTMX partial)
   - Create `routers/ui_jobs.py`

2. **Migrate tasks interface** (4,378 lines → ~800 lines)
   - Create `pages/tasks/list.html`
   - Create `pages/tasks/detail.html`
   - Create `pages/tasks/_workflow_fragment.html`
   - Create `pages/tasks/_docker_progress.html`
   - Create `routers/ui_tasks.py`

3. **Migrate pipeline interface** (897 lines → ~200 lines)
   - Create `pages/pipeline/index.html`
   - Create `routers/ui_pipeline.py`

#### Deliverables
- [ ] Jobs interface in Jinja2 (3 templates + 1 router)
- [ ] Tasks interface in Jinja2 (4 templates + 1 router)
- [ ] Pipeline interface in Jinja2 (1 template + 1 router)
- [ ] Verification that HTMX partials work correctly

---

### Phase 3: Submit Workflows (Week 3)

**Goal**: Migrate complex submission interfaces

#### Tasks

1. **Migrate submit_vector** (1,587 lines → ~400 lines)
2. **Migrate submit_raster** (1,778 lines → ~450 lines)
3. **Migrate submit_raster_collection** (1,643 lines → ~400 lines)
4. **Create shared file browser component**

#### Deliverables
- [ ] Submit vector in Jinja2
- [ ] Submit raster in Jinja2
- [ ] Submit raster collection in Jinja2
- [ ] Reusable `_file_browser.html` component

---

### Phase 4: Data Browsing (Week 4)

**Goal**: Migrate browsing interfaces

#### Tasks

1. **Migrate vector** (944 lines → ~250 lines)
2. **Migrate stac** (1,342 lines → ~350 lines)
3. **Migrate storage** (898 lines → ~250 lines)
4. **Create collection card component**

#### Deliverables
- [ ] Vector browser in Jinja2
- [ ] STAC browser in Jinja2
- [ ] Storage browser in Jinja2
- [ ] Reusable `collection_card.html` component

---

### Phase 5: Map Viewers (Week 5)

**Goal**: Migrate map-based interfaces

#### Tasks

1. **Create base_map.html** (map viewer template with Leaflet/MapLibre)
2. **Extract map utilities** → static/js/map-utils.js
3. **Migrate map, stac_map, h3_map, raster_viewer**

#### Deliverables
- [ ] Map viewer base template
- [ ] 4 map interfaces migrated
- [ ] Reusable map initialization patterns

---

### Phase 6: Admin & Remaining (Week 6)

**Goal**: Complete migration

#### Tasks

1. **Migrate health, database, metrics, platform**
2. **Migrate external_services, execution, integration**
3. **Migrate remaining specialized tools**
4. **Deprecate Function App web interfaces**

#### Deliverables
- [ ] All 36 interfaces migrated
- [ ] Function App serves API only
- [ ] Docker App serves all UI

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
