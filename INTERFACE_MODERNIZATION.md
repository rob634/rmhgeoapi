# Interface Modernization Plan

**Created**: 31 DEC 2025
**Status**: Planning
**Epic**: E12 - Interface Modernization (Phase 2)

---

## Executive Summary

Analysis of the `web_interfaces/` codebase revealed significant DRY (Don't Repeat Yourself) violations. **17 component helper methods exist in `base.py` but only 3 are actively used**. The remaining 14 helpers are ignored, with interfaces writing 100+ lines of raw HTML instead of using the provided abstractions.

**Estimated Impact**: 40% code reduction (~3,600 LOC) across 23 interfaces.

---

## TODO List

### Phase 1: Foundation
- [ ] **TODO-1.1**: Create `web_interfaces/COMPONENTS.md` - document all 17 helpers with examples
- [ ] **TODO-1.2**: Enhance `render_hx_select()` - add `hx_include` parameter support
- [ ] **TODO-1.3**: Create `render_htmx_table()` helper - table with HTMX attributes
- [ ] **TODO-1.4**: Create `render_state_container()` helper - loading + empty + error in one call

### Phase 2: Exemplar Interfaces
- [ ] **TODO-2.1**: Refactor `jobs/interface.py` - use all applicable helpers (reference implementation)
- [ ] **TODO-2.2**: Refactor `tasks/interface.py` - validate list view pattern
- [ ] **TODO-2.3**: Refactor `stac/interface.py` - validate card grid + detail view pattern

### Phase 3: High-Traffic Interfaces
- [ ] **TODO-3.1**: Refactor `vector/interface.py`
- [ ] **TODO-3.2**: Refactor `storage/interface.py`
- [ ] **TODO-3.3**: Refactor `health/interface.py`
- [ ] **TODO-3.4**: Refactor `pipeline/interface.py`
- [ ] **TODO-3.5**: Refactor `home/interface.py`
- [ ] **TODO-3.6**: Refactor `gallery/interface.py`

### Phase 4: Form Interfaces
- [ ] **TODO-4.1**: Refactor `submit-vector/interface.py`
- [ ] **TODO-4.2**: Refactor `submit-raster/interface.py`
- [ ] **TODO-4.3**: Refactor `promote-vector/interface.py`
- [ ] **TODO-4.4**: Refactor `h3/interface.py`

### Phase 5: Remaining Interfaces
- [ ] **TODO-5.1**: Batch refactor remaining interfaces (queues, metrics, zarr-viewer, vector-viewer, etc.)
- [ ] **TODO-5.2**: Create `web_interfaces/_template/interface.py` - new interface template
- [ ] **TODO-5.3**: Update contribution guidelines - require helper usage in PRs

### Phase 6: Validation & Cleanup
- [ ] **TODO-6.1**: Visual regression testing - screenshot comparison before/after
- [ ] **TODO-6.2**: Remove dead CSS - consolidate to COMMON_CSS
- [ ] **TODO-6.3**: Create component showcase page at `/api/interface/components`

---

## Current Architecture

### File Structure
```
web_interfaces/
├── base.py                    # 2,784 lines - BaseInterface + helpers
├── __init__.py                # Interface registry
└── {interface_name}/
    └── interface.py           # Each interface: 200-400 LOC
```

### Base Class Hierarchy
```
BaseInterface (base.py)
├── COMMON_CSS (923 lines)     # Shared styles
├── COMMON_JS (535 lines)      # Shared JavaScript
├── HTMX_CSS (106 lines)       # HTMX-specific styles
├── HTMX_JS (131 lines)        # HTMX-specific JS
└── Component Helpers (17 methods, lines 1930-2690)
```

### Registered Interfaces (23 total)
| Interface | Path | Lines | Helper Usage |
|-----------|------|-------|--------------|
| jobs | `/api/interface/jobs` | ~450 | 1 method (render_status_badge) |
| tasks | `/api/interface/tasks` | ~380 | 0 methods |
| stac | `/api/interface/stac` | ~520 | 0 methods |
| vector | `/api/interface/vector` | ~480 | 0 methods |
| storage | `/api/interface/storage` | ~350 | 2 methods (hx_attrs, render_hx_select) |
| submit-vector | `/api/interface/submit-vector` | ~600 | 1 method (render_hx_form) |
| submit-raster | `/api/interface/submit-raster` | ~550 | 1 method (render_hx_form) |
| promote-vector | `/api/interface/promote-vector` | ~400 | 1 method (render_hx_form) |
| pipeline | `/api/interface/pipeline` | ~320 | 0 methods |
| gallery | `/api/interface/gallery` | ~280 | 0 methods |
| health | `/api/interface/health` | ~400 | 0 methods |
| home | `/api/interface/home` | ~250 | 0 methods |
| h3 | `/api/interface/h3` | ~380 | 0 methods |
| ... | ... | ... | ... |

---

## Available Component Helpers (base.py)

### Standard Components (Lines 1933-2404)

| Method | Line | Purpose | Usage |
|--------|------|---------|-------|
| `render_header()` | 1933 | Dashboard header with title/subtitle/actions | **0%** |
| `render_status_badge()` | 1976 | Colored status pill (queued/processing/completed/failed) | **4%** (jobs only) |
| `render_stat_card()` | 1993 | Single statistic with label/value | **0%** |
| `render_stats_banner()` | 2028 | Grid of stat cards | **0%** |
| `render_empty_state()` | 2061 | "No data found" placeholder | **0%** |
| `render_error_state()` | 2095 | Error message with retry button | **0%** |
| `render_loading_state()` | 2128 | Spinner with message | **0%** |
| `render_card()` | 2153 | Clickable card component | **0%** |
| `render_filter_bar()` | 2201 | Filter dropdowns | **0%** |
| `render_table()` | 2255 | Table with headers | **0%** |
| `render_search_input()` | 2291 | Search input field | **0%** |
| `render_button()` | 2328 | Styled button | **0%** |
| `render_metadata_grid()` | 2375 | Label/value metadata grid | **0%** |

### HTMX Components (Lines 2410-2689)

| Method | Line | Purpose | Usage |
|--------|------|---------|-------|
| `hx_attrs()` | 2410 | Build HTMX attribute strings | **4%** (storage only) |
| `render_hx_select()` | 2479 | HTMX-enabled dropdown | **4%** (storage only) |
| `render_hx_button()` | 2545 | HTMX-enabled button | **0%** |
| `render_hx_form()` | 2601 | HTMX form with submit | **13%** (3 interfaces) |
| `render_hx_polling()` | 2651 | Auto-polling container | **0%** |

---

## The Problem: Raw HTML vs Helpers

### Current Pattern (BAD)

**jobs/interface.py lines 335-437** - 100+ lines of raw HTML:

```python
def _generate_html_content(self) -> str:
    return """
    <header class="dashboard-header">
        <h1>Job Monitor</h1>
        <p class="subtitle">Monitor jobs and tasks from app.jobs table</p>
    </header>

    <div class="filter-bar">
        <div class="filter-group">
            <label for="statusFilter">Status:</label>
            <select id="statusFilter" name="status" class="filter-select"
                    hx-get="/api/interface/jobs?fragment=jobs-table"
                    hx-target="#jobsTableBody"
                    hx-trigger="change"
                    hx-include="#limitFilter"
                    hx-indicator="#loading-spinner">
                <option value="">All</option>
                <option value="queued">Queued</option>
                <option value="processing">Processing</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
            </select>
        </div>
        <!-- ... 40 more lines of filter HTML ... -->
    </div>

    <div class="stats-banner" id="stats-content">
        <div class="stat-card">
            <div class="stat-label">Total Jobs</div>
            <div class="stat-value">--</div>
        </div>
        <!-- ... 20 more lines of stat cards ... -->
    </div>

    <div id="loading-spinner" class="htmx-indicator spinner-container">
        <div class="spinner"></div>
        <div class="spinner-text">Loading jobs...</div>
    </div>

    <table class="data-table">
        <thead>
            <tr>
                <th>Job ID</th>
                <th>Job Type</th>
                <th>Status</th>
                <th>Stage</th>
                <th>Tasks</th>
                <th>Created</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody id="jobsTableBody" hx-get="..." hx-trigger="load">
        </tbody>
    </table>
    """
```

### Target Pattern (GOOD)

**Using component helpers** - ~25 lines:

```python
def _generate_html_content(self) -> str:
    header = self.render_header(
        title="Job Monitor",
        subtitle="Monitor jobs and tasks from app.jobs table",
        icon="⚙️"
    )

    status_filter = self.render_hx_select(
        element_id="statusFilter",
        label="Status",
        options=[
            {'value': '', 'label': 'All', 'selected': True},
            {'value': 'queued', 'label': 'Queued'},
            {'value': 'processing', 'label': 'Processing'},
            {'value': 'completed', 'label': 'Completed'},
            {'value': 'failed', 'label': 'Failed'},
        ],
        hx_get="/api/interface/jobs?fragment=jobs-table",
        hx_target="#jobsTableBody",
        hx_indicator="#loading-spinner"
    )

    stats = self.render_stats_banner([
        {'label': 'Total Jobs', 'value': '--', 'id': 'stat-total'},
        {'label': 'Queued', 'value': '--', 'id': 'stat-queued'},
        {'label': 'Processing', 'value': '--', 'id': 'stat-processing'},
        {'label': 'Completed', 'value': '--', 'id': 'stat-completed'},
        {'label': 'Failed', 'value': '--', 'id': 'stat-failed'},
    ])

    loading = self.render_loading_state("Loading jobs...")

    table = self.render_table(
        columns=['Job ID', 'Job Type', 'Status', 'Stage', 'Tasks', 'Created', 'Actions'],
        tbody_id='jobsTableBody'
    )

    return f"""
    <div class="container">
        {header}
        <div class="filter-bar">{status_filter}</div>
        {stats}
        {loading}
        {table}
    </div>
    """
```

---

## Repeated Patterns Identified

### Pattern 1: Dashboard Headers (15+ occurrences)

**Files**: jobs:335, stac:54, vector:55, health:40, pipeline, tasks, storage, h3, etc.

```html
<!-- Repeated 15+ times with slight variations -->
<header class="dashboard-header">
    <h1>{icon} {title}</h1>
    <p class="subtitle">{subtitle}</p>
</header>
```

**Helper**: `render_header(title, subtitle, icon, actions)`

---

### Pattern 2: Filter Bars (15+ occurrences)

**Files**: jobs:341-383, stac:66-79, vector:65-75, storage, pipeline, tasks

```html
<!-- Repeated with same structure, different options -->
<div class="filter-bar">
    <div class="filter-group">
        <label for="filter">Label:</label>
        <select id="filter" class="filter-select" hx-get="..." hx-target="...">
            <option value="">All</option>
            ...
        </select>
    </div>
</div>
```

**Helper**: `render_filter_bar(filters, actions)` or `render_hx_select()`

---

### Pattern 3: State Containers (25+ occurrences)

**Files**: ALL 23 interfaces define these manually

```html
<!-- Loading -->
<div id="loading-spinner" class="spinner-container">
    <div class="spinner"></div>
    <div class="spinner-text">Loading...</div>
</div>

<!-- Empty -->
<div id="empty-state" class="empty-state hidden">
    <div class="icon">📦</div>
    <h3>No Data Found</h3>
    <p>Nothing to display.</p>
</div>

<!-- Error -->
<div id="error-state" class="error-state hidden">
    <div class="icon">⚠️</div>
    <h3>Error Loading Data</h3>
    <p id="error-message"></p>
    <button onclick="retry()">Retry</button>
</div>
```

**Helpers**: `render_loading_state()`, `render_empty_state()`, `render_error_state()`

---

### Pattern 4: Stats Banners (12+ occurrences)

**Files**: jobs:385-407, health, metrics, platform, pipeline

```html
<div class="stats-banner">
    <div class="stat-card">
        <div class="stat-label">Label</div>
        <div class="stat-value">--</div>
    </div>
    <!-- Repeat 4-6 times -->
</div>
```

**Helper**: `render_stats_banner(stats)`

---

### Pattern 5: Data Tables (10+ occurrences)

**Files**: jobs:416-435, tasks, storage, queues, stac:122-129

```html
<table class="data-table">
    <thead>
        <tr><th>Col1</th><th>Col2</th>...</tr>
    </thead>
    <tbody id="tableBody" hx-get="..." hx-trigger="load">
    </tbody>
</table>
```

**Helper**: `render_table(columns, tbody_id)`

---

### Pattern 6: Card Grids (18+ occurrences)

**Files**: home:43-123, gallery, stac, vector

```html
<div class="cards-grid">
    <a href="/api/interface/..." class="card">
        <div class="card-icon">📦</div>
        <h3 class="card-title">Title</h3>
        <p class="card-description">Description</p>
        <div class="card-footer">View →</div>
    </a>
</div>
```

**Helper**: `render_card(title, description, footer, href, icon)`

---

## Estimated Impact

### Code Reduction

| Metric | Current | After | Savings |
|--------|---------|-------|---------|
| base.py | 2,784 lines | 3,000 lines (+enhanced helpers) | - |
| 23 interfaces | ~6,500 lines | ~2,500 lines | **62%** |
| **Total** | ~9,300 lines | ~5,500 lines | **~3,800 LOC (41%)** |

### Developer Benefits

| Benefit | Impact |
|---------|--------|
| Consistency | All interfaces use identical components |
| Maintainability | Update styling in one place (base.py) |
| Velocity | New interfaces built 30-50% faster |
| Onboarding | Reference component library, not copy-paste |
| Testing | Unit test components independently |

---

## Implementation Plan

### Phase 1: Foundation (Week 1)

- [ ] **1.1** Create component documentation in `web_interfaces/COMPONENTS.md`
  - Document all 17 helpers with examples
  - Add usage guidelines
  - Include before/after comparisons

- [ ] **1.2** Enhance `render_hx_select()` to support `hx-include` attribute
  - Currently missing from helper
  - Required for filter chains (status + limit)

- [ ] **1.3** Add `render_htmx_table()` helper
  - Combines `render_table()` with HTMX attributes
  - Supports `hx-get`, `hx-trigger="load"`, `hx-indicator`

- [ ] **1.4** Add `render_state_container()` helper
  - Generates loading + empty + error in one call
  - Eliminates most common duplication

### Phase 2: Exemplar Interface (Week 1-2)

- [ ] **2.1** Refactor `jobs/interface.py` as reference implementation
  - Use all applicable helpers
  - Document each helper usage with comments
  - Verify functionality unchanged

- [ ] **2.2** Refactor `tasks/interface.py`
  - Similar structure to jobs
  - Validates helper patterns work for list views

- [ ] **2.3** Refactor `stac/interface.py`
  - Tests card grid helpers
  - Tests detail view pattern

### Phase 3: High-Traffic Interfaces (Week 2-3)

- [ ] **3.1** Refactor `vector/interface.py`
- [ ] **3.2** Refactor `storage/interface.py`
- [ ] **3.3** Refactor `health/interface.py`
- [ ] **3.4** Refactor `pipeline/interface.py`
- [ ] **3.5** Refactor `home/interface.py`
- [ ] **3.6** Refactor `gallery/interface.py`

### Phase 4: Form Interfaces (Week 3)

- [ ] **4.1** Refactor `submit-vector/interface.py`
  - Already uses `render_hx_form()` - extend usage

- [ ] **4.2** Refactor `submit-raster/interface.py`
- [ ] **4.3** Refactor `promote-vector/interface.py`
- [ ] **4.4** Refactor `h3/interface.py`

### Phase 5: Remaining Interfaces (Week 4)

- [ ] **5.1** Refactor remaining interfaces (batch)
  - queues, metrics, zarr-viewer, vector-viewer, etc.

- [ ] **5.2** Create interface template file
  - `web_interfaces/_template/interface.py`
  - Demonstrates all helper patterns

- [ ] **5.3** Update contribution guidelines
  - Require helper usage in code review
  - Add to PR checklist

### Phase 6: Validation & Cleanup (Week 4)

- [ ] **6.1** Visual regression testing
  - Screenshot comparison before/after
  - Verify no UI changes

- [ ] **6.2** Remove dead CSS
  - Identify unused selectors
  - Consolidate to COMMON_CSS

- [ ] **6.3** Create component showcase page
  - `/api/interface/components`
  - Visual gallery of all helpers

---

## Helper Enhancement Proposals

### New Helper: `render_state_container()`

```python
def render_state_container(
    self,
    loading_id: str = "loading-spinner",
    loading_msg: str = "Loading...",
    empty_id: str = "empty-state",
    empty_icon: str = "📦",
    empty_title: str = "No Data Found",
    empty_msg: str = "Nothing to display.",
    error_id: str = "error-state",
    retry_action: str = "loadData()"
) -> str:
    """Generate loading + empty + error states in one call."""
    return f"""
    {self.render_loading_state(loading_msg, loading_id)}
    {self.render_empty_state(empty_icon, empty_title, empty_msg, empty_id)}
    {self.render_error_state(retry_action=retry_action, element_id=error_id)}
    """
```

### New Helper: `render_htmx_table()`

```python
def render_htmx_table(
    self,
    columns: list,
    tbody_id: str,
    hx_get: str,
    hx_trigger: str = "load",
    hx_indicator: str = "#loading-spinner",
    hx_include: str = ""
) -> str:
    """Render table with HTMX-enabled tbody."""
    headers = ''.join([f'<th>{col}</th>' for col in columns])
    hx_attrs = self.hx_attrs(
        get=hx_get,
        trigger=hx_trigger,
        indicator=hx_indicator,
        include=hx_include
    )
    return f"""
    <table class="data-table">
        <thead><tr>{headers}</tr></thead>
        <tbody id="{tbody_id}" {hx_attrs}></tbody>
    </table>
    """
```

### Enhancement: `render_hx_select()` with `hx_include`

```python
def render_hx_select(
    self,
    element_id: str,
    label: str,
    options: list,
    hx_get: str = "",
    hx_target: str = "",
    hx_trigger: str = "change",
    hx_indicator: str = "",
    hx_include: str = "",  # NEW: Support include
    name: str = ""
) -> str:
```

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Helper usage rate | 4% | 80%+ | Grep for `self.render_` calls |
| Lines per interface | 300-500 | 100-200 | Line count |
| Duplicate HTML patterns | 150+ | <10 | Manual audit |
| Time to create new interface | 2-4 hours | 30-60 min | Developer feedback |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Visual regression | Medium | High | Screenshot testing before/after |
| Breaking HTMX behavior | Low | High | Test all interactive features |
| Helper gaps | Medium | Low | Enhance helpers as needed |
| Developer resistance | Low | Medium | Show productivity gains |

---

## Related Documents

- `docs_claude/ARCHITECTURE_REFERENCE.md` - System architecture
- `EPICS.md` - E12 Interface Modernization epic
- `docs_claude/TODO.md` - Sprint tasks
- `web_interfaces/base.py` - Component helpers source (lines 1930-2690)

---

## Appendix: Helper Method Signatures

### Standard Components

```python
# Headers
render_header(title: str, subtitle: str = "", icon: str = "", actions: str = "") -> str

# Status
render_status_badge(status: str) -> str

# Statistics
render_stat_card(label: str, value: str, highlight: bool = False, css_class: str = "") -> str
render_stats_banner(stats: list) -> str  # [{'label': '', 'value': '', 'id': '', 'highlight': bool}]

# States
render_empty_state(icon: str = "📦", title: str = "No Data Found", message: str = "", element_id: str = "empty-state") -> str
render_error_state(message: str = "Something went wrong", retry_action: str = "loadData()", element_id: str = "error-state") -> str
render_loading_state(message: str = "Loading...", element_id: str = "loading-spinner") -> str

# Cards
render_card(title: str, description: str = "", footer: str = "", href: str = "", icon: str = "", featured: bool = False) -> str

# Forms
render_filter_bar(filters: list, actions: str = "") -> str  # [{'id': '', 'label': '', 'options': []}]
render_search_input(placeholder: str = "Search...", element_id: str = "search-input", onkeyup: str = "") -> str

# Tables
render_table(columns: list, tbody_id: str = "table-body", table_id: str = "data-table") -> str

# Buttons
render_button(text: str, onclick: str = "", href: str = "", variant: str = "primary", size: str = "", element_id: str = "", icon: str = "") -> str

# Metadata
render_metadata_grid(items: list) -> str  # [{'label': '', 'value': ''}]
```

### HTMX Components

```python
# Attribute builder
hx_attrs(get: str = "", post: str = "", target: str = "", swap: str = "", trigger: str = "", indicator: str = "", include: str = "", vals: str = "", confirm: str = "", disabled_elt: str = "", push_url: bool = False) -> str

# HTMX-enabled elements
render_hx_select(element_id: str, label: str, options: list, hx_get: str = "", hx_target: str = "", hx_trigger: str = "change", hx_indicator: str = "", name: str = "") -> str
render_hx_button(text: str, hx_get: str = "", hx_post: str = "", hx_target: str = "", hx_swap: str = "", hx_confirm: str = "", variant: str = "primary", element_id: str = "", icon: str = "") -> str
render_hx_form(action: str, fields: str, submit_text: str = "Submit", hx_target: str = "#result", hx_swap: str = "innerHTML", element_id: str = "hx-form", method: str = "post") -> str
render_hx_polling(url: str, interval: str = "5s", target: str = "", element_id: str = "polling-container", initial_content: str = "Loading...") -> str
```
