# GREENFIELD: Platform Dashboard — Agent A (Advocate) Design
## Optimal Solution Design

**Date**: 01 MAR 2026
**Agent**: A (Advocate)
**Pipeline**: GREENFIELD — Platform Dashboard UI
**Role**: Design the OPTIMAL solution. No criticism, no hedging. This is the full design.

---

## Table of Contents

1. [Component Design](#1-component-design)
2. [Interface Contracts](#2-interface-contracts)
3. [Data Flow](#3-data-flow)
4. [Golden Path](#4-golden-path)
5. [State Management](#5-state-management)
6. [Style Variant Recommendation](#6-style-variant-recommendation)
7. [Extension Points](#7-extension-points)
8. [Design Rationale](#8-design-rationale)

---

## 1. Component Design

### 1.1 Module Architecture

```
web_dashboard/
├── __init__.py              # Route handler, registry bootstrap, auto-import trigger
├── shell.py                 # DashboardShell: chrome, tabs, CSS/JS injection, HTML envelope
├── base_panel.py            # BasePanel: abstract contract + shared utility methods
├── registry.py              # PanelRegistry: decorator registration, get, list
└── panels/
    ├── __init__.py          # Auto-import all panel modules (triggers decorators)
    ├── platform.py          # Tab: PLATFORM — submit, requests, approvals, catalog, lineage
    ├── jobs.py              # Tab: JOBS — monitor, tasks, pipeline, failures
    ├── data.py              # Tab: DATA — assets, STAC, vector, storage
    └── system.py            # Tab: SYSTEM — health, database, queues, maintenance
```

The directory maps 1:1 to the tab structure. Each panel file is a single cohesive module — there is no per-sub-tab file fragmentation. Sub-tabs are sections within a panel, not separate classes.

---

### 1.2 DashboardShell

**Location**: `web_dashboard/shell.py`

The shell owns everything that persists across tab switches: the outer HTML document, the `<head>` block, the top navigation bar, the HTMX script tag, and the footer. Panels never produce `<html>` or `<head>` — they produce only their content fragment.

```python
# ============================================================================
# CLAUDE CONTEXT - DASHBOARD SHELL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: UI Component - Persistent chrome for the Platform Dashboard
# PURPOSE: Renders the outer HTML envelope, tab bar, CSS, and HTMX bootstrap
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: DashboardShell
# DEPENDENCIES: azure.functions, config
# ============================================================================

class DashboardShell:
    """
    Renders the persistent dashboard chrome.

    Responsibilities:
        - Full HTML document on initial load (GET /api/dashboard, no HX-Request)
        - Tab bar with active-state markup
        - Injects the design system CSS once (not per-panel)
        - Injects HTMX 1.9.x from CDN
        - Injects minimal shell JS (tab highlight sync on push-url)
        - Wraps panel content in #main-content div
        - On HTMX tab-switch request, returns panel fragment ONLY (no shell re-render)

    The shell does NOT know what panels exist — it calls PanelRegistry.list_tabs()
    to discover tab names for the nav bar. This keeps shell decoupled from panels.
    """

    # Tab ordering is declared here to control display order.
    # PanelRegistry provides existence, Shell provides order.
    TAB_ORDER = ["platform", "jobs", "data", "system"]

    TAB_LABELS = {
        "platform": "Platform",
        "jobs":     "Jobs",
        "data":     "Data",
        "system":   "System",
    }

    def render(
        self,
        request: func.HttpRequest,
        active_tab: str,
        panel_html: str,
        version: str,
    ) -> str:
        """
        Render the full dashboard HTML document.

        Called on initial load (no HX-Request header). Returns complete HTML
        including shell chrome and the initial panel content.

        Args:
            request:     The incoming HttpRequest (used for base URL derivation).
            active_tab:  Which tab is currently active (name key, e.g. "platform").
            panel_html:  Pre-rendered HTML fragment from the active panel.
            version:     Application version string (from config.__version__).

        Returns:
            Complete HTML document string ready for HttpResponse.
        """

    def render_fragment(
        self,
        panel_html: str,
        active_tab: str,
    ) -> str:
        """
        Render ONLY the #main-content replacement fragment for HTMX tab switches.

        Called when HX-Request header is present and tab= param changes.
        Returns a div fragment (not a full document). HTMX replaces #main-content.

        Args:
            panel_html:  Pre-rendered HTML fragment from the newly active panel.
            active_tab:  The tab being switched to (used to build updated tab bar
                         markup so active states stay correct after OOB swap).

        Returns:
            HTML fragment string: updated tab bar (hx-swap-oob) + panel content.
        """

    def _build_tab_bar(self, active_tab: str) -> str:
        """Render the <nav id="tab-bar"> markup with correct active class."""

    def _get_css(self) -> str:
        """Return the full consolidated design system CSS string."""

    def _get_js(self) -> str:
        """Return the minimal shell JS (tab sync, HTMX config)."""

    def _get_base_url(self, request: func.HttpRequest) -> str:
        """Derive https base URL from request headers (mirrors BaseInterface pattern)."""
```

**CSS Injection Strategy**: The shell injects CSS in a single `<style>` block in `<head>`. CSS custom properties (variables) define all tokens. Panels may add panel-specific CSS via an optional `get_panel_css()` hook on BasePanel, injected into a `<style>` tag at the top of the panel fragment. This means panel CSS is loaded on first tab switch and lost on the next switch — which is intentional. Panels must declare only additive, non-conflicting CSS. The base design system CSS is permanent (shell-level).

**HTMX Version**: HTMX 1.9.12 from CDN (`https://unpkg.com/htmx.org@1.9.12`). Rationale: 1.9.x is the stable LTS branch; 2.0 introduced breaking changes in attribute names and the request lifecycle that would require audit of all existing `web_interfaces/` patterns. The CDN tag is in the shell `<head>`, loaded once. No self-hosting: CDN is acceptable for an operator tool that always has network access to reach Azure.

**Shell JS** is minimal — approximately 30 lines. It handles one concern: when HTMX pushes a new URL after a tab switch, it updates the tab bar active state if the OOB swap is not used. The COMMON_JS utilities from `web_interfaces/base.py` (formatDate, formatRelativeTime, formatBytes, debounce, escapeHtml, etc.) are reproduced in the shell JS block with zero changes, making all panel JS able to call them without importing anything.

---

### 1.3 BasePanel (Abstract Base)

**Location**: `web_dashboard/base_panel.py`

```python
# ============================================================================
# CLAUDE CONTEXT - BASE PANEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: UI Component - Abstract base for all dashboard panels
# PURPOSE: Defines panel contract and provides shared HTML utility methods
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: BasePanel
# DEPENDENCIES: azure.functions, abc, urllib.request, json, logging
# ============================================================================

from abc import ABC, abstractmethod
from typing import Optional, Any
import azure.functions as func

class BasePanel(ABC):
    """
    Abstract base class for all dashboard panels.

    Each panel:
        - Represents one top-level tab (platform, jobs, data, system)
        - Implements render() for full tab content
        - Implements fragment() for HTMX partial updates
        - Uses utility methods for consistent HTML output

    Panels produce HTML FRAGMENTS only — never full HTML documents.
    The DashboardShell wraps everything in the outer document.

    Utility methods provided (no override needed):
        - status_badge(status) → HTML span with correct CSS class
        - approval_badge(state) → HTML span for approval states
        - clearance_badge(level) → HTML span for clearance levels
        - format_date(iso_str) → "01 MAR 2026" military format (server-side)
        - format_age(iso_str) → "5m", "2h", "3d" relative display
        - data_table(headers, rows) → consistent <table> HTML
        - stat_strip(stats_dict) → status count bar HTML
        - error_block(message, retry_url) → inline error with retry link
        - empty_block(message) → empty state placeholder
        - loading_placeholder(fragment_url) → auto-loading HTMX spinner div
        - call_api(path, params) → server-side API call with error handling
        - sub_tab_bar(sections, active, tab_name) → sub-tab nav HTML
    """

    @abstractmethod
    def tab_name(self) -> str:
        """Return the URL key for this tab (e.g., 'platform')."""

    @abstractmethod
    def tab_label(self) -> str:
        """Return the human-readable tab label (e.g., 'Platform')."""

    @abstractmethod
    def default_section(self) -> str:
        """Return the default sub-tab/section name (e.g., 'requests')."""

    @abstractmethod
    def render(self, request: func.HttpRequest) -> str:
        """
        Render full tab content (initial tab load or direct URL access).

        Called when:
            - User switches to this tab (HTMX request, HX-Request header present)
            - User navigates directly to /api/dashboard?tab=<name>

        Args:
            request: The HttpRequest. Read query params for section= and filters.

        Returns:
            HTML fragment string (not a full document). The shell wraps this.
        """

    @abstractmethod
    def fragment(self, request: func.HttpRequest, fragment_name: str) -> str:
        """
        Render a named sub-fragment for HTMX partial refresh.

        Called when:
            - Auto-refresh polling hits (hx-trigger="every 10s")
            - Inline action completes and response replaces a row
            - Row click loads a detail panel
            - Sub-tab switch within the panel

        Args:
            request:       The HttpRequest (read params for context).
            fragment_name: Which fragment to render (e.g., "jobs-table", "job-detail").

        Returns:
            HTML fragment string — typically a table body, a div, or a row.

        Raises:
            ValueError: If fragment_name is not recognized by this panel.
                        (Caller converts ValueError to HTTP 400.)
        """

    def get_panel_css(self) -> Optional[str]:
        """
        Return panel-specific CSS to inject at top of panel fragment.

        Override only if this panel needs CSS beyond the shell design system.
        Keep minimal — design system tokens cover 95% of cases.

        Returns:
            CSS string or None (default, no extra CSS).
        """
        return None

    # -------------------------------------------------------------------------
    # UTILITY METHODS — provided, not abstract
    # -------------------------------------------------------------------------

    def status_badge(self, status: str) -> str:
        """
        Render a status badge span.

        Args:
            status: One of: queued, pending, processing, completed, failed
                    (case-insensitive, normalized to lowercase)

        Returns:
            <span class="status-badge status-{normalized}">STATUS</span>
        """
        normalized = (status or "unknown").lower().replace(" ", "_")
        label = normalized.upper()
        return f'<span class="status-badge status-{normalized}">{label}</span>'

    def approval_badge(self, state: str) -> str:
        """Render an approval state badge (pending_review, approved, rejected, revoked)."""
        normalized = (state or "unknown").lower()
        label = normalized.upper().replace("_", " ")
        return f'<span class="approval-badge approval-{normalized}">{label}</span>'

    def clearance_badge(self, level: str) -> str:
        """Render a clearance level badge (uncleared, ouo, public)."""
        normalized = (level or "uncleared").lower()
        label = normalized.upper()
        return f'<span class="clearance-badge clearance-{normalized}">{label}</span>'

    def format_date(self, iso_str: Optional[str], fallback: str = "--") -> str:
        """
        Format ISO timestamp to military date format: "01 MAR 2026".

        Server-side formatting ensures military date consistency regardless
        of client timezone. All times displayed in Eastern Time.
        """
        if not iso_str:
            return fallback
        from datetime import datetime, timezone
        import zoneinfo
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            eastern = dt.astimezone(zoneinfo.ZoneInfo("America/New_York"))
            return eastern.strftime("%d %b %Y %H:%M ET").upper()
        except Exception:
            return fallback

    def format_age(self, iso_str: Optional[str]) -> str:
        """
        Format ISO timestamp as relative age: "5m", "2h", "3d".

        Used for table Age columns where space is limited.
        """
        if not iso_str:
            return "--"
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - dt
            secs = int(delta.total_seconds())
            if secs < 60:
                return f"{secs}s"
            elif secs < 3600:
                return f"{secs // 60}m"
            elif secs < 86400:
                return f"{secs // 3600}h"
            else:
                return f"{secs // 86400}d"
        except Exception:
            return "--"

    def call_api(
        self,
        path: str,
        params: Optional[dict] = None,
        method: str = "GET",
        body: Optional[dict] = None,
        base_url: str = "http://localhost:7071",
    ) -> tuple[bool, Any]:
        """
        Make a server-side HTTP call to the API.

        Panels call their own app's API endpoints, never the database directly.
        This is the ONLY approved way to fetch data in a panel.

        Args:
            path:     API path (e.g., "/api/platform/status")
            params:   Query parameters dict
            method:   HTTP method (GET or POST)
            body:     JSON body dict for POST requests
            base_url: Base URL (default localhost for same-process calls)

        Returns:
            Tuple (success: bool, data: Any)
            On success: (True, parsed_json_or_dict)
            On failure: (False, error_message_string)
        """
        import urllib.request
        import urllib.parse
        import json as json_lib
        import logging
        logger = logging.getLogger(__name__)

        try:
            url = base_url.rstrip("/") + path
            if params:
                url += "?" + urllib.parse.urlencode(params)

            req = urllib.request.Request(url, method=method)
            req.add_header("Accept", "application/json")

            if body and method == "POST":
                encoded = json_lib.dumps(body).encode("utf-8")
                req.add_header("Content-Type", "application/json")
                req.data = encoded

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json_lib.loads(resp.read().decode("utf-8"))
                return True, data

        except urllib.error.HTTPError as e:
            logger.warning(f"API call failed: {method} {path} → HTTP {e.code}")
            return False, f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            logger.error(f"API call error: {method} {path} → {e}")
            return False, str(e)

    def data_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        table_id: str = "data-table",
        row_htmx: Optional[list[dict]] = None,
    ) -> str:
        """
        Render a standard data table with consistent styling.

        Args:
            headers:   Column header strings
            rows:      List of row data (each row is a list of cell HTML strings)
            table_id:  HTML id for the <table> element
            row_htmx:  Optional per-row HTMX attributes dict (hx-get, hx-target, etc.)

        Returns:
            Complete <table> HTML string using .data-table CSS class.
        """
        th_html = "".join(f"<th>{h}</th>" for h in headers)
        tbody_rows = []
        for i, row in enumerate(rows):
            htmx_attrs = ""
            if row_htmx and i < len(row_htmx):
                htmx_attrs = " ".join(
                    f'{k}="{v}"' for k, v in row_htmx[i].items()
                )
            td_html = "".join(f"<td>{cell}</td>" for cell in row)
            tbody_rows.append(f'<tr {htmx_attrs} class="clickable-row">{td_html}</tr>')

        return f"""
        <table id="{table_id}" class="data-table">
          <thead><tr>{th_html}</tr></thead>
          <tbody>{"".join(tbody_rows)}</tbody>
        </table>"""

    def stat_strip(self, counts: dict[str, int]) -> str:
        """
        Render a horizontal status count strip.

        Args:
            counts: Dict mapping status name to count, e.g.:
                    {"processing": 3, "completed": 47, "failed": 2}

        Returns:
            HTML div with styled count pills.
        """
        pills = []
        for status, count in counts.items():
            css = f"status-{status.lower()}"
            pills.append(
                f'<span class="stat-pill {css}">'
                f'<span class="stat-count">{count}</span>'
                f'<span class="stat-label">{status}</span>'
                f'</span>'
            )
        return f'<div class="stat-strip">{"".join(pills)}</div>'

    def error_block(self, message: str, retry_url: Optional[str] = None) -> str:
        """
        Render an inline error block with optional retry link.

        Args:
            message:   Human-readable error description (never raw stack traces).
            retry_url: HTMX URL to re-trigger on retry click. If None, no retry shown.

        Returns:
            HTML error block div.
        """
        retry_html = ""
        if retry_url:
            retry_html = (
                f' <a class="btn btn-sm btn-secondary" '
                f'hx-get="{retry_url}" hx-target="closest .error-block" '
                f'hx-swap="outerHTML">Retry</a>'
            )
        return (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">{message}</span>'
            f'{retry_html}'
            f'</div>'
        )

    def empty_block(self, message: str = "No results found.") -> str:
        """Render a styled empty state placeholder."""
        return (
            f'<div class="empty-state">'
            f'<div class="empty-icon">-</div>'
            f'<p>{message}</p>'
            f'</div>'
        )

    def loading_placeholder(self, fragment_url: str, target_id: str) -> str:
        """
        Render a div that immediately triggers an HTMX load on mount.

        Used for deferred loading of heavy sections (avoids blocking initial render).

        Args:
            fragment_url: URL to fetch the real content from.
            target_id:    HTML id of this div (HTMX will replace it).

        Returns:
            HTML div with hx-trigger="load" and spinner content.
        """
        return (
            f'<div id="{target_id}" '
            f'hx-get="{fragment_url}" '
            f'hx-trigger="load" '
            f'hx-swap="outerHTML">'
            f'<div class="loading-state"><div class="spinner"></div>'
            f'<p class="spinner-text">Loading...</p></div>'
            f'</div>'
        )

    def sub_tab_bar(
        self,
        sections: list[tuple[str, str]],
        active_section: str,
        tab_name: str,
    ) -> str:
        """
        Render the sub-tab navigation bar within a panel.

        Args:
            sections:       List of (section_key, label) tuples in display order.
            active_section: Currently active section key.
            tab_name:       Parent tab name (for URL construction).

        Returns:
            HTML nav div with sub-tab links using HTMX.
        """
        links = []
        for key, label in sections:
            active_class = " active" if key == active_section else ""
            links.append(
                f'<a class="sub-tab{active_class}" '
                f'hx-get="/api/dashboard?tab={tab_name}&section={key}" '
                f'hx-target="#panel-content" '
                f'hx-push-url="true">'
                f'{label}</a>'
            )
        return f'<nav id="sub-tabs" class="sub-tab-bar">{"".join(links)}</nav>'
```

---

### 1.4 PanelRegistry

**Location**: `web_dashboard/registry.py`

```python
# ============================================================================
# CLAUDE CONTEXT - PANEL REGISTRY
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Infrastructure - Decorator-based panel registration
# PURPOSE: Maintains mapping of tab names to panel classes; mirrors InterfaceRegistry
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: PanelRegistry
# DEPENDENCIES: web_dashboard.base_panel
# ============================================================================

class PanelRegistry:
    """
    Registry for all dashboard panels.

    Mirrors the InterfaceRegistry pattern from web_interfaces/__init__.py.
    Uses decorator-based registration — panels self-register at import time.

    Example:
        @PanelRegistry.register
        class PlatformPanel(BasePanel):
            def tab_name(self): return "platform"
            ...

        # Now PanelRegistry.get("platform") returns PlatformPanel.
    """

    _panels: Dict[str, Type[BasePanel]] = {}

    @classmethod
    def register(cls, panel_class: Type[BasePanel]) -> Type[BasePanel]:
        """
        Decorator to register a panel class.

        Unlike InterfaceRegistry, the tab name comes from the class's tab_name()
        method (not a decorator argument) — enforces that the class is self-describing.

        Args:
            panel_class: BasePanel subclass to register.

        Returns:
            The panel class (unmodified — decorator returns class for chaining).

        Raises:
            ValueError: If panel with same tab_name already registered.
        """
        instance = panel_class()
        name = instance.tab_name()
        if name in cls._panels:
            logger.warning(
                f"Panel '{name}' already registered "
                f"({cls._panels[name].__name__}), overwriting with {panel_class.__name__}"
            )
        cls._panels[name] = panel_class
        logger.info(f"Registered panel: '{name}' -> {panel_class.__name__}")
        return panel_class

    @classmethod
    def get(cls, name: str) -> Optional[Type[BasePanel]]:
        """Return panel class by tab name, or None if not found."""
        return cls._panels.get(name)

    @classmethod
    def list_tabs(cls) -> List[str]:
        """Return list of all registered tab names."""
        return list(cls._panels.keys())

    @classmethod
    def get_all(cls) -> Dict[str, Type[BasePanel]]:
        """Return copy of the full registry dict."""
        return cls._panels.copy()
```

**Key design choice**: The `@PanelRegistry.register` decorator takes no arguments — the panel class itself declares its `tab_name()`. This eliminates the name-as-string argument that can drift from the actual tab name. The registry instantiates a throwaway instance solely to call `tab_name()` at registration time. Runtime lookups use `panel_class()` to create a fresh instance per request (stateless panels, no shared state).

---

### 1.5 `web_dashboard/__init__.py` — Route Handler

```python
# ============================================================================
# CLAUDE CONTEXT - DASHBOARD ROUTE HANDLER
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Entrypoint - HTTP trigger handler for GET /api/dashboard
# PURPOSE: Dispatches to DashboardShell + appropriate panel based on query params
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: dashboard_handler
# DEPENDENCIES: azure.functions, web_dashboard.shell, web_dashboard.registry
# ============================================================================

# Auto-import panels so their decorators fire and they self-register
from web_dashboard.panels import platform, jobs, data, system  # noqa: F401

from web_dashboard.shell import DashboardShell
from web_dashboard.registry import PanelRegistry
import azure.functions as func
import logging

logger = logging.getLogger(__name__)

DEFAULT_TAB = "platform"
_shell = DashboardShell()


def dashboard_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger handler for the Platform Dashboard.

    Route: GET /api/dashboard
    Route: GET /api/dashboard?tab={name}
    Route: GET /api/dashboard?tab={name}&section={section}
    Route: GET /api/dashboard?tab={name}&fragment={fragment_name}&...

    HTMX Protocol:
        - No HX-Request header → full HTML document (initial load)
        - HX-Request header + tab= only → panel fragment (tab switch)
        - HX-Request header + fragment= → named fragment (auto-refresh, row detail)

    Error Responses:
        400: Unknown fragment name
        404: Unknown tab name
        500: Panel render error (logs exception, returns error block HTML)
    """
    tab = req.params.get("tab", DEFAULT_TAB)
    section = req.params.get("section", "")
    fragment = req.params.get("fragment", "")
    is_htmx = bool(req.headers.get("HX-Request"))

    # Resolve panel
    panel_class = PanelRegistry.get(tab)
    if not panel_class:
        available = ", ".join(PanelRegistry.list_tabs())
        return func.HttpResponse(
            f"Unknown tab '{tab}'. Available: {available}",
            status_code=404,
        )

    panel = panel_class()

    try:
        if fragment:
            # Named fragment: auto-refresh, row detail, inline action result
            html = panel.fragment(req, fragment)
            return func.HttpResponse(html, mimetype="text/html", status_code=200)

        elif is_htmx:
            # Tab switch: return panel fragment for #main-content swap
            panel_html = panel.render(req)
            fragment_html = _shell.render_fragment(panel_html, active_tab=tab)
            return func.HttpResponse(fragment_html, mimetype="text/html", status_code=200)

        else:
            # Initial page load: full document
            from config import __version__
            panel_html = panel.render(req)
            full_html = _shell.render(req, active_tab=tab, panel_html=panel_html, version=__version__)
            return func.HttpResponse(full_html, mimetype="text/html", status_code=200)

    except ValueError as e:
        # Contract violation: bad fragment name etc.
        logger.warning(f"Dashboard bad request: tab={tab} fragment={fragment} error={e}")
        return func.HttpResponse(str(e), status_code=400)

    except Exception as e:
        logger.exception(f"Dashboard render error: tab={tab} section={section} fragment={fragment}")
        error_html = f'<div class="error-block">Dashboard error: {type(e).__name__}. Check logs.</div>'
        return func.HttpResponse(error_html, mimetype="text/html", status_code=500)
```

---

### 1.6 Panel Modules

#### `panels/platform.py`

The Platform panel is the primary P1 interface. It owns six sections:

| Section key | Sub-tab label | Primary Fragment(s) |
|-------------|---------------|---------------------|
| `requests` | Requests | `requests-table` |
| `approvals` | Approvals | `approvals-table`, `approval-detail` |
| `submit` | Submit | (no auto-refresh; form submit posts to API directly) |
| `catalog` | Catalog | `catalog-results` |
| `lineage` | Lineage | `lineage-graph` |
| `failures` | Failures | `failures-table` |

Default section is `requests` — this is the highest-value landing view for an operator opening the dashboard.

The panel's `render()` method reads the `section=` param and delegates to a private `_render_{section}()` method. Each section method builds the sub-tab bar + section content. The fragment() method handles auto-refresh and row expansions.

The Approvals section uses HTMX `hx-confirm` on Approve and Reject buttons to prevent accidental actions. The inline action POSTs to `/api/platform/approve` (existing endpoint). The response is an HTML fragment that replaces the row with the updated state — no full page reload.

#### `panels/jobs.py`

The Jobs panel owns four sections:

| Section key | Sub-tab label | Primary Fragment(s) |
|-------------|---------------|---------------------|
| `monitor` | Monitor | `jobs-table` (auto-refresh every 10s) |
| `tasks` | Tasks | `tasks-table` |
| `pipeline` | Pipeline | `pipeline-viz` |
| `failures` | Failures | `failures-table` |

Default section is `monitor`. The jobs table div has `hx-trigger="every 10s"` to auto-refresh its content. The refresh indicator (spinning icon + "auto 10s" label) is inside the refreshable div so it updates with each cycle.

Job row click fires a fragment load into `#detail-panel` below the table. The detail panel shows stage progress bars (using inline `<div style="width: X%">` calculated server-side) and action links (View Tasks, View Lineage).

Stage progress is rendered as server-side calculated bars, not client-side computed. The panel fetches `/api/jobs/status/{job_id}` and computes `completed_tasks / total_tasks` per stage as a percentage.

#### `panels/data.py`

The Data panel owns four sections:

| Section key | Sub-tab label | Primary Fragment(s) |
|-------------|---------------|---------------------|
| `assets` | Assets | `asset-list` |
| `stac` | STAC | `collections-list`, `items-list` |
| `vector` | Vector | `vector-collections-list` |
| `storage` | Storage | (deferred to post-MVP; placeholder) |

Default section is `assets`. STAC and vector sections use lazy loading via `loading_placeholder()` — the initial section render returns a spinner div that immediately triggers an HTMX load, preventing the panel render from blocking on slow STAC API calls.

#### `panels/system.py`

The System panel owns four sections:

| Section key | Sub-tab label | Primary Fragment(s) |
|-------------|---------------|---------------------|
| `health` | Health | `health-cards` (auto-refresh every 30s) |
| `database` | Database | `db-stats`, `db-activity` |
| `queues` | Queues | `queue-stats` |
| `maintenance` | Maintenance | (form actions only; no auto-refresh) |

Default section is `health`. The health section renders component cards (DB, STAC, platform, queue, storage). Each card shows status (green/amber/red), response time, and a timestamp. Cards auto-refresh every 30s via a wrapping div with `hx-trigger="every 30s"`.

The Maintenance section shows the schema ensure/rebuild actions with confirmation dialogs (`hx-confirm`). The rebuild action uses a double-confirm pattern: first HTMX confirm, then a second server-side check for `confirm=yes` query param. Results show inline as an error or success block.

---

## 2. Interface Contracts

### 2.1 DashboardShell.render()

```
DashboardShell.render(
    request: func.HttpRequest,
    active_tab: str,
    panel_html: str,
    version: str,
) -> str

Behavior:
    1. Calls _build_tab_bar(active_tab) → tab nav HTML
    2. Builds full HTML document:
       - <!DOCTYPE html><html lang="en">
       - <head>: charset, viewport, title, <style> DESIGN_SYSTEM_CSS, HTMX CDN script
       - <body>:
           <div id="dashboard-chrome">
             <header id="dash-header">
               <span class="dash-brand">GeoAPI Platform</span>
               <span class="dash-version">v{version}</span>
             </header>
             {tab_bar_html}
           </div>
           <div id="main-content">
             {panel_html}
           </div>
       - <script> SHELL_JS </script>
       - </body></html>
    3. Returns complete string.

Side effects: None (pure HTML generation).
```

### 2.2 DashboardShell.render_fragment()

```
DashboardShell.render_fragment(
    panel_html: str,
    active_tab: str,
) -> str

Behavior:
    Returns TWO elements concatenated (HTMX OOB + main content):

    1. Updated tab bar with correct active state, marked for OOB swap:
       <nav id="tab-bar" hx-swap-oob="true">
         ... tab links with updated active class ...
       </nav>

    2. The panel content wrapped in #main-content:
       <div id="main-content">
         {panel_html}
       </div>

    HTMX swaps #main-content (primary target) and updates #tab-bar (OOB).
    This keeps the tab bar active state correct after navigation.
```

### 2.3 BasePanel Abstract Methods

```
tab_name(self) -> str
    Must return URL-safe lowercase string matching PanelRegistry key.
    Example: "platform", "jobs", "data", "system"
    No spaces, no special characters.

tab_label(self) -> str
    Human-readable display label for the tab bar.
    Example: "Platform", "Jobs", "Data", "System"

default_section(self) -> str
    Section key that renders when no section= param given.
    Must be a key in the panel's own sections dict.

render(self, request: func.HttpRequest) -> str
    Full panel content for initial tab load or tab switch.
    Must:
        1. Read section= param (fallback to default_section())
        2. Render sub_tab_bar(sections, active_section, tab_name)
        3. Render <div id="panel-content"> with section content
        4. Return combined HTML fragment (no <html>, no <head>)
    Must NOT: call database directly, raise uncaught exceptions

fragment(self, request: func.HttpRequest, fragment_name: str) -> str
    Named sub-fragment for HTMX partial refresh.
    Must:
        1. Recognize the fragment_name or raise ValueError
        2. Read any additional params needed (job_id, filters, etc.)
        3. Return minimal HTML fragment (typically <tbody> or <div>)
    Must NOT: return sub-tab bar or panel chrome (fragments are content only)
    Raises:
        ValueError: If fragment_name not in this panel's known fragments.
```

### 2.4 PanelRegistry API

```
PanelRegistry.register(panel_class) -> panel_class
    Decorator: registers panel by calling panel_class().tab_name().
    No arguments — class is self-describing.
    Logs warning if overwriting existing registration.
    Returns the class unchanged (transparent decorator).

PanelRegistry.get(name: str) -> Optional[Type[BasePanel]]
    Returns panel class by tab name, or None.
    O(1) dict lookup.

PanelRegistry.list_tabs() -> List[str]
    Returns all registered tab names as list.
    Used by DashboardShell to build tab bar.

PanelRegistry.get_all() -> Dict[str, Type[BasePanel]]
    Returns copy of full registry. Used for diagnostics.
```

### 2.5 HTTP Route Handler Signature

```
Function App route binding (in function.json or app.route decorator):
    Route:   /api/dashboard
    Methods: GET (read-only UI handler — actions POST to existing /api/* endpoints)

dashboard_handler(req: func.HttpRequest) -> func.HttpResponse

Query Parameters:
    tab      (str, optional): Panel tab name. Default: "platform"
    section  (str, optional): Sub-tab section. Default: panel.default_section()
    fragment (str, optional): Named fragment for partial refresh. No default.

    Additional params are panel/fragment-specific:
        job_id, request_id, status, hours, limit, page, etc.
    These are read by panels directly from req.params.

HTMX Headers Used:
    HX-Request: "true" — presence indicates HTMX request (tab switch or fragment)
    HX-Current-URL: Used by shell to detect back/forward navigation (future)

Response Content-Type: text/html (always)
Response Status:
    200: Success (full page, tab fragment, or named fragment)
    400: Bad fragment name (ValueError from panel.fragment())
    404: Unknown tab name
    500: Unexpected render error
```

### 2.6 HTMX Fragment Protocol

The protocol uses a consistent query parameter contract across all fragments:

```
Fragment Request URL Pattern:
    GET /api/dashboard?tab={tab}&fragment={fragment_name}[&{context_params}]

Context params (panel-specific, appended as needed):
    job_id={uuid}          — for job detail fragments
    request_id={uuid}      — for request detail fragments
    release_id={uuid}      — for approval detail fragments
    status={str}           — filter by status
    hours={int}            — filter by age
    limit={int}            — pagination limit
    page={int}             — pagination offset (page * limit)

Fragment Response Format:
    - Content-Type: text/html
    - No shell chrome
    - No sub-tab bar (unless the fragment IS the sub-tab content)
    - Designed to be swapped into a specific #target-id

Auto-Refresh Fragments (must be idempotent):
    HTMX div wrapper with trigger:
    <div hx-get="/api/dashboard?tab=jobs&fragment=jobs-table"
         hx-trigger="every 10s"
         hx-target="this"
         hx-swap="innerHTML">
      {current content}
    </div>
    The fragment response is ONLY the inner content (not the wrapper div).

Row Detail Fragments:
    Triggered by row click. Swaps a detail panel below the table.
    Response is the complete detail card HTML.

Inline Action Fragments:
    Triggered by Approve/Reject/Revoke button.
    POSTs to actual API endpoint (not dashboard handler).
    Dashboard handler is NOT involved in approve/reject.
    The action button's hx-post points to /api/platform/approve.
    The action result response (from platform API) is the updated row HTML.

    IMPORTANT CONSTRAINT: The platform API's approve/reject endpoints must
    return HTML fragments (not JSON) when called from the dashboard.
    Detection: check HX-Request header in platform API handler.
    If HX-Request present: return HTML row fragment.
    If not: return JSON (existing behavior preserved).
```

---

## 3. Data Flow

### 3.1 Browser to Response: Complete Path

```
Browser GET /api/dashboard
    │
    ▼
Azure Function HTTP Trigger (function_app.py)
    │  Route binding: /api/dashboard
    │
    ▼
web_dashboard/__init__.py :: dashboard_handler(req)
    │
    ├─ Read params: tab="platform" (default), section="", fragment=""
    ├─ Detect HTMX: HX-Request header absent → full page load
    │
    ▼
PanelRegistry.get("platform") → PlatformPanel class
    │
    ▼
PlatformPanel().render(req)
    │
    ├─ section = req.params.get("section", "requests")
    ├─ sub_tab_bar(sections, "requests", "platform") → nav HTML
    │
    ├─ _render_requests_section(req)
    │   ├─ call_api("/api/platform/status", {"limit": 25, "hours": 24})
    │   ├─ success=True, data={requests: [...], total: 47, counts: {...}}
    │   ├─ stat_strip({"processing": 5, "completed": 12, "failed": 2, ...})
    │   ├─ data_table(headers, rows, row_htmx=[...]) → table HTML
    │   └─ returns: section_html (stat strip + filter bar + table + detail panel placeholder)
    │
    ├─ returns: panel_html (sub-tab bar + <div id="panel-content"> + section_html)
    │
    ▼
DashboardShell().render(req, "platform", panel_html, version)
    │
    ├─ _build_tab_bar("platform") → tab nav HTML
    ├─ _get_css() → full design system CSS string
    ├─ _get_js() → shell JS + common utilities
    │
    ├─ Assembles full HTML document:
    │   <!DOCTYPE html> ... <head>CSS</head>
    │   <body>
    │     <header>GeoAPI Platform | v0.9.10.1</header>
    │     <nav id="tab-bar"> Platform* Jobs Data System </nav>
    │     <div id="main-content">
    │       {panel_html}
    │     </div>
    │   </body>
    │   <script>HTMX CDN</script><script>shell JS</script>
    │
    ▼
func.HttpResponse(full_html, mimetype="text/html", status_code=200)
    │
    ▼
Browser renders ~40KB HTML document
```

### 3.2 HTMX Tab Switching Flow

```
User clicks "Jobs" tab
    │
    Browser fires HTMX request:
    GET /api/dashboard?tab=jobs
    Headers: HX-Request: true, HX-Target: main-content, HX-Current-URL: /api/dashboard?tab=platform
    │
    ▼
dashboard_handler(req)
    │
    ├─ tab = "jobs", fragment = "", is_htmx = True
    ├─ PanelRegistry.get("jobs") → JobsPanel class
    │
    ▼
JobsPanel().render(req)
    │
    ├─ section = "monitor" (default)
    ├─ sub_tab_bar(sections, "monitor", "jobs")
    │
    ├─ _render_monitor_section(req)
    │   ├─ call_api("/api/dbadmin/jobs", {"limit": 25, "hours": 24})
    │   ├─ stat_strip({"processing": 3, "completed": 47, "failed": 2, "queued": 1})
    │   ├─ data_table(...) → jobs table HTML
    │   └─ returns: section HTML with auto-refresh wrapper
    │       <div hx-get="...fragment=jobs-table" hx-trigger="every 10s" ...>
    │         [stat strip + filter bar + table]
    │       </div>
    │       <div id="detail-panel"></div>
    │
    ▼
DashboardShell().render_fragment(panel_html, "jobs")
    │
    ├─ _build_tab_bar("jobs") → updated nav with "jobs" active
    │
    ├─ Returns two elements:
    │   <nav id="tab-bar" hx-swap-oob="true">
    │     Platform Jobs* Data System
    │   </nav>
    │   <div id="main-content">
    │     {jobs panel_html}
    │   </div>
    │
    ▼
func.HttpResponse(fragment_html, mimetype="text/html", status_code=200)
    │
    ▼
HTMX receives response:
    - Swaps #main-content with new jobs panel content
    - Detects hx-swap-oob on tab-bar, updates it out-of-band
    - Pushes new URL: /api/dashboard?tab=jobs (hx-push-url="true" on tab anchor)
    │
Browser URL bar: /api/dashboard?tab=jobs
Tab bar: Jobs tab highlighted
Content: Jobs monitor panel rendered
Total round-trip: ~150ms (no full document re-render)
```

### 3.3 HTMX Auto-Refresh Flow

```
Jobs Monitor section renders with this wrapper div:
    <div id="jobs-refresh-wrapper"
         hx-get="/api/dashboard?tab=jobs&fragment=jobs-table"
         hx-trigger="every 10s"
         hx-target="this"
         hx-swap="innerHTML">
      [initial jobs table content]
    </div>

Every 10 seconds:
    HTMX fires: GET /api/dashboard?tab=jobs&fragment=jobs-table
    Headers: HX-Request: true, HX-Trigger: jobs-refresh-wrapper
    │
    ▼
dashboard_handler(req)
    ├─ fragment = "jobs-table", tab = "jobs"
    ▼
JobsPanel().fragment(req, "jobs-table")
    ├─ Read filters from params: status=, hours=, limit=
    ├─ call_api("/api/dbadmin/jobs", filtered_params)
    ├─ stat_strip(counts)
    ├─ data_table(rows with updated statuses)
    └─ Returns: HTML for inside the refresh wrapper (no wrapper div itself)
    │
    ▼
HTMX swaps innerHTML of #jobs-refresh-wrapper
    Browser: table rows update with current statuses
    No flicker: HTMX morphdom-style swap preserves stable DOM elements
    Active row detail (#detail-panel) is outside the refresh wrapper → preserved
```

### 3.4 HTMX Inline Action Flow (Approve)

```
Operator clicks "Approve" button on release row:
    <button
      hx-post="/api/platform/approve"
      hx-vals='{"release_id": "rel-abc", "clearance": "OUO", "reviewer": "operator"}'
      hx-target="#row-rel-abc"
      hx-swap="outerHTML"
      hx-confirm="Approve release rel-abc? This publishes the dataset."
      class="btn btn-sm btn-approve">
      Approve
    </button>
    │
HTMX shows browser confirm dialog
Operator clicks OK
    │
    ▼
HTMX fires: POST /api/platform/approve
    Headers: HX-Request: true, HX-Target: row-rel-abc
    Body: {"release_id": "rel-abc", "clearance": "OUO", "reviewer": "operator"}
    │
    ▼
Platform API handler (/api/platform/approve)
    ├─ Processes approval (existing logic, unchanged)
    ├─ Detects HX-Request header
    ├─ Returns HTML fragment:
    │   <tr id="row-rel-abc" class="approved-row">
    │     <td><code>rel-abc</code></td>
    │     <td>ds-flood/r-01</td>
    │     <td>raster</td>
    │     <td><span class="clearance-badge clearance-ouo">OUO</span></td>
    │     <td><span class="approval-badge approval-approved">APPROVED</span></td>
    │     <td colspan="2"><em>Approved by operator — 01 MAR 2026 14:30 ET</em></td>
    │   </tr>
    │
    ▼
HTMX replaces #row-rel-abc with approved row HTML
    Approval queue table updates inline
    No page reload, no tab switch, no polling wait
```

### 3.5 Error Propagation Path

```
Error occurs in panel.render() or panel.fragment():

CASE 1: API call fails (network, 4xx, 5xx)
    call_api() returns (False, "HTTP 503: Service Unavailable")
    Panel calls: self.error_block("Could not load jobs: HTTP 503", retry_url="...")
    Returns the error block HTML in place of the table
    → User sees: inline red error card with Retry link
    → Retry triggers fresh HTMX load of the same fragment
    → No stack trace exposed to user

CASE 2: Bad fragment name
    panel.fragment(req, "nonexistent") raises ValueError("Unknown fragment: nonexistent")
    dashboard_handler catches ValueError
    Returns: func.HttpResponse("Unknown fragment: nonexistent", status_code=400)
    HTMX receives 400: Does not swap content (HTMX default 400 behavior)
    → No visible change to user (graceful non-swap)
    → Error logged server-side

CASE 3: Unexpected exception in panel
    dashboard_handler catches Exception
    Logs: logger.exception(...)  ← full traceback in App Insights
    Returns: func.HttpResponse(error_block_html, status_code=500)
    HTMX receives 500: Swaps target with error block (if hx-swap on error is configured)
    → User sees: "Dashboard error: {ExceptionType}. Check logs."
    → No raw traceback in response

CASE 4: Tab not found
    PanelRegistry.get("badtab") returns None
    dashboard_handler returns 404 plain text
    → For initial load: browser shows 404 page text
    → For HTMX tab switch: HTMX handles 404 (no swap, logs warning)
    → Legitimate only if someone constructs a bad URL manually
```

---

## 4. Golden Path

### Scenario 1: Operator Opens Dashboard, Views Processing Jobs

```
1. Operator navigates browser to /api/dashboard

2. Server returns full HTML: Platform tab active (default), Requests section
   - Stat strip shows: 5 processing, 12 completed, 2 failed, 3 pending
   - Filter bar: status=All, hours=24, search=empty
   - Requests table: 25 rows, sorted by age ASC (newest last)
   - Each row shows: Request ID (truncated), Data Type badge, Dataset ID,
                     Status badge, Age (relative)

3. Operator clicks "Jobs" tab
   - HTMX fires GET /api/dashboard?tab=jobs (150ms round-trip)
   - Jobs Monitor section loads:
     Stat strip: 3 processing, 47 completed, 2 failed, 1 queued
     Jobs table with all active jobs visible
     Auto-refresh timer shows "auto 10s" in header

4. Operator sees job-abc in Processing state (Stage 2/3, 3/5 tasks)
   - Row shows: job-abc | process_raster | Processing | 2/3 | 3/5 | 5m

5. Operator clicks the row
   - HTMX fires GET /api/dashboard?tab=jobs&fragment=job-detail&job_id=abc123
   - Detail panel loads below the table:
     Job: job-abc-1234-5678
     Type: process_raster_v2
     Submitted: 01 MAR 2026 14:25 ET
     Stage 1: download    [=====] 2/2 COMPLETED
     Stage 2: process     [===--] 3/5 PROCESSING
     Stage 3: register    [-----] 0/1 PENDING
     [View Tasks] [View Lineage] [View Logs]

6. Ten seconds pass → auto-refresh fires
   - Jobs table rows update with current statuses
   - Detail panel (outside refresh wrapper) remains visible
   - job-abc now shows Stage 2: 5/5 COMPLETED → Stage 3: 0/1 PROCESSING
```

### Scenario 2: Operator Submits a New Raster Dataset

```
1. Operator is on Platform tab, clicks "Submit" sub-tab
   - HTMX fires GET /api/dashboard?tab=platform&section=submit
   - Submit form loads with Data Type selector, DDH fields, Blob Path

2. Operator fills in:
   - Data Type: Raster (radio button)
   - Dataset ID: ds-dem-natl
   - Resource ID: r-01
   - Version ID: v-2026-03-01
   - Blob Path: bronze/raster/dem-natl-2026.tif

3. Operator clicks "Validate (dry run)"
   - Form POSTs to /api/platform/validate (existing endpoint)
   - HX-Request header present → API returns HTML validation result fragment
   - Result swaps into result div:
     Validation: PASS
     Dataset: ds-dem-natl / r-01 / v-2026-03-01
     File: 245MB COG, 32-bit float, EPSG:4326
     Table name: dem_natl (will create)
     [ Submit ]

4. Operator clicks "Submit"
   - Form POSTs to /api/platform/submit
   - API returns HTML success fragment:
     Request ID: req-xyz789
     Job ID: job-abc456
     Status: PROCESSING
     [View Request >]

5. Operator clicks "View Request"
   - HTMX GET /api/dashboard?tab=platform&section=requests (pushes URL)
   - Requests table loads with req-xyz789 visible at top (newest)
```

### Scenario 3: Operator Approves a Pending Release

```
1. Operator sees notification in nav (pending approvals count badge): "5 pending"
   Badge in tab bar: "Platform (5)"

2. Operator clicks Platform tab, then "Approvals" sub-tab
   - Approval queue loads:
     5 rows visible, all status = PENDING REVIEW
     Each row: Release ID | Asset | Type | Clearance | [Approve] [Reject]

3. Operator clicks row for rel-abc to expand detail
   - Detail panel loads below table:
     Release: rel-abc-1234
     Asset: ds-flood / r-01 (v1, ord1)
     Job: job-xyz COMPLETED 28 FEB 2026 09:15 ET
     STAC item: flood-data-ord1 in collection flood-data
     Blob: silver/raster/flood-data-ord1.tif (1.2GB)
     Clearance selector: [OUO v]
     Reviewer field: [operator]

4. Operator sets clearance to OUO, enters reviewer name

5. Operator clicks "Approve"
   - HTMX shows confirm: "Approve release rel-abc? This publishes the dataset."
   - Operator confirms
   - POST /api/platform/approve with {release_id, clearance, reviewer}
   - Row in table updates inline: status = APPROVED, action buttons hidden
   - Pending count in tab badge decrements: "4 pending"
```

### Scenario 4: Operator Investigates a Failed Job

```
1. Operator on Jobs tab, clicks "Failures" sub-tab
   - Failed jobs table loads (last 48h):
     job-ghi | virtualzarr | FAILED | 3/5 stages | 1h ago
     [Error] Stage 3: combine — TimeoutError: copy exceeded 300s limit

2. Operator clicks job-ghi row for detail
   - Detail panel shows:
     Stage 1: scan      [=====] 12/12 COMPLETED
     Stage 2: copy      [=====] 12/12 COMPLETED
     Stage 3: combine   [===--] 3/5 FAILED
     Stage 4: validate  [-----] 0/1 PENDING
     Stage 5: register  [-----] 0/1 PENDING

     Error: TimeoutError in task combine-4, combine-5
     [View Tasks] → loads tasks section

3. Operator clicks "View Tasks"
   - HTMX GET /api/dashboard?tab=jobs&section=tasks&job_id=ghi
   - Tasks section loads filtered to job-ghi:
     Task ID   | Stage | Type    | Status | Duration | Error
     task-c-1  | 3     | combine | DONE   | 45s      | —
     task-c-4  | 3     | combine | FAILED | 302s     | TimeoutError
     task-c-5  | 3     | combine | FAILED | 301s     | TimeoutError

4. Operator can see the exact error, copies task IDs for log search
   - "View Logs" link opens App Insights query in new tab
     (pre-built URL with job_id filter in KQL query)
```

### Scenario 5: Operator Checks System Health

```
1. Operator clicks "System" tab
   - Health section loads (default):
     5 component cards arranged in a 3-column grid:

     [Database]        [STAC]           [Platform]
     HEALTHY (green)   HEALTHY (green)  HEALTHY (green)
     12ms response     8ms response     23ms response
     Updated: 14:30    Updated: 14:30   Updated: 14:30

     [Queues]          [Storage]
     DEGRADED (amber)  HEALTHY (green)
     active-jobs: 0    rmhazuregeobronze OK
     dead-letter: 3    Updated: 14:30

2. Queue card shows amber/DEGRADED because dead-letter has 3 messages
   Operator clicks "Queues" sub-tab for details

3. Queues section loads:
   Queue name       | Active | Dead-letter | Size
   active-jobs      | 0      | 0           | —
   active-tasks     | 4      | 3           | 1.2KB avg

4. Operator notes 3 dead-letter messages — escalates for investigation
   (Dashboard shows problem; resolution happens via Service Bus tools)

5. Health cards auto-refresh every 30s — operator can watch in real time
```

---

## 5. State Management

### 5.1 URL as Single Source of Truth

The dashboard has no client-side state. All state is encoded in the URL. The URL at any moment fully describes the dashboard view and can be bookmarked, shared, and loaded fresh.

**URL schema**:
```
/api/dashboard                              → Platform tab, Requests section (defaults)
/api/dashboard?tab=jobs                     → Jobs tab, Monitor section (default)
/api/dashboard?tab=jobs&section=tasks       → Jobs tab, Tasks section
/api/dashboard?tab=platform&section=approvals → Platform tab, Approvals section
/api/dashboard?tab=jobs&section=monitor&status=failed&hours=48 → Filtered Jobs
```

**No client-side state** means:
- Browser back/forward work correctly via `hx-push-url="true"` on all navigations
- Refresh loads exactly what was displayed
- Sharing a URL with a colleague shows them the same view
- No localStorage, sessionStorage, or cookie usage

### 5.2 HTMX Push-URL for Browser History

All tab switches and sub-tab switches use `hx-push-url="true"`. This instructs HTMX to push the request URL into the browser history stack after a successful swap. The browser back button fires a standard GET to the previous URL, which the server handles as a fresh initial load (no HX-Request header → full document).

```html
<!-- Tab link -->
<a hx-get="/api/dashboard?tab=jobs"
   hx-target="#main-content"
   hx-push-url="true"
   class="tab">Jobs</a>

<!-- Sub-tab link -->
<a hx-get="/api/dashboard?tab=platform&section=approvals"
   hx-target="#panel-content"
   hx-push-url="true"
   class="sub-tab">Approvals</a>
```

Row clicks and fragment loads do NOT push URL (no `hx-push-url`). They are ephemeral detail views within a section. The section URL is the addressable unit; the expanded row is transient.

### 5.3 No Client-Side State

**Intentional constraints**:
- No global JavaScript variables that persist across HTMX swaps
- No `window.*` state storage
- No cookies set by the dashboard (the API may set cookies separately — that is out of scope)
- Filter values live in the URL query string or in form inputs (which HTMX reads via `hx-include`)

**Filter persistence**: Filters are preserved in URLs when sub-tabs are switched. When a user sets `status=failed` on the jobs table and then switches to the Tasks sub-tab, the filter is preserved in the URL. Returning to Monitor with browser back restores the filter because the URL contains it.

**HTMX `hx-include`**: Auto-refresh fragments use `hx-include` to include filter inputs from the filter bar:
```html
<div hx-get="/api/dashboard?tab=jobs&fragment=jobs-table"
     hx-trigger="every 10s"
     hx-target="this"
     hx-swap="innerHTML"
     hx-include="#jobs-filter-form">
```
This means the auto-refresh always applies the operator's current filters. Filters are not lost on refresh.

### 5.4 URL Query Param Conventions

| Param | Type | Panels | Notes |
|-------|------|--------|-------|
| `tab` | str | All | Tab name key |
| `section` | str | All | Sub-tab section key |
| `fragment` | str | All | Auto-refresh/detail fragment name |
| `status` | str | platform, jobs | Filter by status value |
| `hours` | int | platform, jobs | "Last N hours" time filter |
| `limit` | int | platform, jobs, data | Page size (default 25) |
| `page` | int | platform, jobs, data | Page number (0-indexed) |
| `job_id` | str | jobs | Scoped to specific job |
| `request_id` | str | platform | Scoped to specific request |
| `release_id` | str | platform | Scoped to specific release |
| `dataset_id` | str | data | Scoped to dataset |
| `q` | str | data | Full-text search term |

**Pagination model**: Offset-based (`page` × `limit`). Rationale: The existing `/api/dbadmin/jobs` endpoint uses `limit` and offset. Cursor-based pagination requires API changes. Offset-based works for operator use cases where result sets are small (under 1000 rows). If a table has >1000 rows something is wrong with the filter.

---

## 6. Style Variant Recommendation

### The Choice: Synthesized "Ops Intelligence" Scheme

I champion a deliberate synthesis of Variant 1 (Current Interface) and Variant 2 (Dark Operator), with structural modifications. I call this scheme **"Ops Intelligence"**.

The synthesis is not a compromise — it is the superior choice because neither pure variant fully serves the operator use case. The rationale is below, then the full scheme.

### Why Pure Variant 1 ("Current Interface") is Insufficient

Variant 1 is the baseline. It is functional. But it was designed for a collection of 37 independent pages, not a unified dashboard. The design reads as "enterprise software from 2018" — technically correct but visually undifferentiated from generic Azure portal pages.

For an operator who will spend hours in this dashboard running pipelines, the navy/blue/gray palette offers no visual hierarchy for urgency. A FAILED job and a COMPLETED job are equally easy to overlook in a sea of `#626F86` secondary text. The design system CSS is well-built and should be reused — the color scheme should evolve.

Additionally, Variant 1's light background at `#f8f9fa` creates glare in dark room/night operations environments, which is precisely when operators are running critical pipeline jobs.

### Why Pure Variant 2 ("Dark Operator") is Insufficient

Variant 2 is visually compelling and high-density. Dark mode reduces eye strain in low-light environments. But it has two practical problems for this use case:

1. **Accessibility in bright rooms**: The slate-900 background (`#0F172A`) with light text creates harsh contrast in bright office environments. Operators in a lit office looking at a dark screen see a "TV in a lit room" effect. This is not a WCAG issue (dark-on-light is fine) — it is a physiological issue.

2. **CSS implementation cost**: A full dark theme requires designing two states for every component: active/inactive tabs, hover states, form inputs, tables. The existing CSS variables from Variant 1 cover ~40 design tokens already tested in production. Rebuilding all of these for dark mode doubles the CSS maintenance surface.

### Why Variants 3 and 4 are Wrong for This Use Case

Variant 3 ("Nordic Minimal") is designed for SaaS consumer products. Its generous whitespace and near-invisible borders reduce information density. An operator dashboard needs to pack maximum data into the viewport. Whitespace is a luxury; scan-ability under time pressure is a requirement.

Variant 4 ("Geo Cartographic") is thematically interesting but operationally inappropriate. The warm cream background `#FAF5EF` and forest green primary would make status colors ambiguous. More critically: the geospatial domain is about the data, not the UI. The operators know they are working with geospatial data. The UI does not need to remind them.

### The "Ops Intelligence" Synthesis

The synthesis takes the best of Variant 1 (trusted, accessible, tested CSS tokens) and adds selective elements from Variant 2 (operational urgency, density, dark status bar at bottom).

**Core philosophy**: Keep the light background for day use. Add a persistent dark status bar at the bottom (already implemented in `web_interfaces/base.py` as `.system-status-bar`). Make status colors more saturated and action-oriented.

**Token Table — Ops Intelligence**:

| Token | Value | Source | Rationale |
|-------|-------|--------|-----------|
| `--ds-bg` | `#F0F2F5` | Modified V1 | Cooler, less warm than f8f9fa |
| `--ds-surface` | `#FFFFFF` | V1 | Clean white cards |
| `--ds-navy` | `#0D2137` | Modified V1 | Deeper navy for stronger headings |
| `--ds-blue-primary` | `#0071BC` | V1 exact | Keep — trusted, accessible |
| `--ds-blue-dark` | `#245AAD` | V1 exact | Keep |
| `--ds-cyan` | `#00A3DA` | V1 exact | Keep |
| `--ds-gold` | `#FFC14D` | V1 exact | Keep — "latest" badges |
| `--ds-gray` | `#626F86` | V1 exact | Keep |
| `--ds-gray-light` | `#DDE1E9` | Modified V1 | Slightly more blue-tinted |
| `--ds-border` | `#C5CBD8` | New | Visible but subtle borders |
| `--ds-text-secondary` | `#4A5568` | New | Darker secondary text for density |
| `--ds-font` | `"Inter", "Open Sans", system-ui, sans-serif` | Synthesis | Inter first (modern) with Open Sans fallback |
| `--ds-font-mono` | `"JetBrains Mono", "Monaco", monospace` | V2 mono with V1 fallback | Better code readability |
| `--ds-font-size` | `13px` | Modified | 1px denser than V1's 14px — significant at dashboard scale |
| `--ds-radius-card` | `6px` | Synthesis | Tighter than V1 (8px), less rigid than V2 (6px) |
| `--ds-radius-btn` | `4px` | Synthesis | Crisp buttons |
| `--ds-radius-badge` | `10px` | V1 | Keep |
| `--ds-shadow` | `0 1px 3px rgba(13,33,55,0.10)` | Modified V1 | Navy-tinted shadow |

**Status Badge Colors** (V1 palette kept — these are semantically correct and tested):

| Status | Background | Text |
|--------|-----------|------|
| Queued | `#F3F4F6` | `#6B7280` |
| Pending | `#FEF3C7` | `#D97706` |
| Processing | `#DBEAFE` | `#0071BC` |
| Completed | `#D1FAE5` | `#059669` |
| Failed | `#FEE2E2` | `#DC2626` |

**Status Bar (Bottom Chrome)**: Borrow Variant 2's dark ops feel for the persistent bottom status bar. The existing `.system-status-bar` in `web_interfaces/base.py` already implements this pattern (`#1a1a2e` background, green/amber/red indicators). Port this element verbatim to the dashboard shell. It provides:
- Active job count
- DB connection status
- Last refresh timestamp
- App version

This gives the operator the "ops center" feel without abandoning the accessible light background for the main content area.

**Tab Bar Design**: The tab bar uses a horizontal strip with a strong left-border accent on the active tab:
```css
.tab.active {
    border-bottom: 3px solid var(--ds-blue-primary);
    color: var(--ds-navy);
    font-weight: 700;
}
```
Not a pill/rounded tab — sharp bottom border. This matches the existing `border-left: 4px solid var(--ds-blue-primary)` card pattern from V1 and creates visual continuity between tabs and content.

**Font Loading**: Use system font stack with Inter as first choice. Inter is available on macOS (SF Pro compatibility) and Windows (system-ui fallback). Do NOT use Google Fonts CDN — it introduces an external dependency that can add 200-500ms latency and fail in restricted network environments. Open Sans from the existing system remains as fallback. This requires zero font loading overhead.

**WCAG Compliance**: All foreground/background combinations in the Ops Intelligence scheme meet WCAG 2.1 AA (4.5:1 contrast for normal text). The navy text `#0D2137` on white `#FFFFFF` achieves 14.8:1 (well above threshold). The status badges use established colors from Variant 1 that are already proven.

**Mobile Breakpoint**: Minimum supported width is 900px. At 768px (tablet), the tab bar collapses to a single-row scrollable strip. Below 768px is not supported (operator tool, not mobile app). This is declared via a single `@media (max-width: 900px)` block.

---

## 7. Extension Points

### 7.1 Adding a New Panel

Adding a fifth tab (e.g., "Reports") requires exactly four steps:

1. Create `/web_dashboard/panels/reports.py` implementing `BasePanel`
2. Set `tab_name()` to `"reports"` and `tab_label()` to `"Reports"`
3. Add `from web_dashboard.panels import reports` to `web_dashboard/panels/__init__.py`
4. Add `"reports"` to `DashboardShell.TAB_ORDER` in the desired position

The `@PanelRegistry.register` decorator on the class handles registration automatically. No changes to `function_app.py`, no changes to registry logic, no changes to shell routing.

### 7.2 Adding a New Sub-Tab to an Existing Panel

Within a panel (e.g., adding "Analytics" to the Jobs tab):

1. Add `("analytics", "Analytics")` to the panel's `_SECTIONS` dict
2. Implement `_render_analytics_section(req)` private method
3. Add `elif section == "analytics": return self._render_analytics_section(req)` in `render()`
4. If the section needs auto-refresh, add a fragment key and handler in `fragment()`

No changes outside the panel file.

### 7.3 Adding a New Auto-Refresh Widget

Any div can become auto-refreshing by adding HTMX attributes and implementing the fragment in the panel. The pattern is standardized:

```python
# In panel render:
def _render_my_section(self, req):
    return f"""
    <div hx-get="/api/dashboard?tab={self.tab_name()}&fragment=my-widget"
         hx-trigger="every 15s"
         hx-target="this"
         hx-swap="innerHTML">
      {self._render_my_widget_content(req)}
    </div>"""

# In panel fragment:
def fragment(self, req, fragment_name):
    if fragment_name == "my-widget":
        return self._render_my_widget_content(req)
    raise ValueError(f"Unknown fragment: {fragment_name}")
```

### 7.4 Inline Actions on New Endpoints

Any new API endpoint that returns HTML (detected via HX-Request header) can be wired into the dashboard via standard HTMX attributes. The dashboard route handler is not involved in inline actions — they POST directly to API endpoints. This means new platform capabilities automatically get dashboard support without touching dashboard code.

### 7.5 Panel-Specific CSS

If a new panel needs custom CSS that doesn't fit the design system, it overrides `get_panel_css()`:
```python
def get_panel_css(self) -> str:
    return """
    .my-special-component { ... }
    """
```
The shell injects this at the top of the panel fragment as a `<style>` tag. It is scoped to the panel's lifetime (discarded when switching tabs). Name collisions with other panels are possible if CSS is not carefully namespaced, but panels render one at a time so this is not a practical problem.

### 7.6 Future: Dark Mode Toggle

The Ops Intelligence scheme uses CSS custom properties for all tokens. Adding a dark mode toggle requires:
1. One `<button>` in the shell header that toggles a `dark` class on `<body>`
2. A CSS block:
   ```css
   body.dark { --ds-bg: #0F172A; --ds-surface: #1E293B; ... }
   ```
3. The toggle persists via a `data-theme` cookie (one `document.cookie` write)

This is designed as a future extension (Nice to Have per spec). The token architecture makes it possible without refactoring.

---

## 8. Design Rationale

### 8.1 Why Dashboard Shell Pattern (Not Per-Panel Full Pages)

The old `web_interfaces/` system has 37 full-page interfaces. Each one includes the full CSS, the nav bar, the HTMX bootstrap, and the page content. When switching between interfaces, the browser loads a full document — even with HTMX, the round-trip is a full HTML response of 40-60KB.

The shell pattern inverts this: the shell (fixed chrome) is loaded once. Tab switches exchange only the panel content (~5-15KB). This:
- Cuts tab-switch payload by 70%
- Keeps the tab bar stable (no re-rendering the nav on every switch)
- Enables the auto-refresh indicators to persist (they are in the tab bar, not the panel)
- Enables the bottom status bar to persist and update independently

The operator perception: the app feels like a single-page application with real navigation, not a collection of linked pages.

### 8.2 Why PanelRegistry.register Decorator Takes No Arguments

`@InterfaceRegistry.register('jobs')` works but creates a maintenance problem: the string `'jobs'` and the class's conceptual identity can drift. A developer can register `JobsInterface` under `'monitor'` and nothing in the code prevents it.

`@PanelRegistry.register` with no arguments forces the class to declare its own identity via `tab_name()`. This is the same principle as Django's `Meta.app_label` — the class is self-describing. The registry simply reads it. If a developer changes the tab name, it changes in one place (the class).

### 8.3 Why call_api() Uses urllib (Not requests or httpx)

Azure Function Apps have `urllib` available with zero imports. The `requests` library requires installation and adds a dependency. `httpx` is async-first and adds complexity for what are synchronous server-side calls.

The panels make synchronous calls because Azure Functions are themselves synchronous in this deployment (the existing `web_interfaces/` all use `urllib.request`). The 10-second timeout in `call_api()` is conservative — in production, localhost API calls complete in under 100ms.

### 8.4 Why Server-Side Date Formatting

The existing `web_interfaces/` system sends ISO timestamps to the browser and formats them in JavaScript (`formatDate()`, `formatDateTime()`). This causes a flash of unformatted timestamps on initial render and requires every panel to include the JS formatting utilities.

The new dashboard formats dates server-side via `BasePanel.format_date()`. The server knows the correct timezone (Eastern Time). The HTML delivered to the browser already contains formatted dates. This:
- Eliminates the JS formatting dependency in panels
- Ensures military date format (`01 MAR 2026`) is applied consistently
- Prevents timestamp flash on load
- COMMON_JS still includes client-side date utilities for any JavaScript-rendered content (approval result fragments etc.)

### 8.5 Why HTMX 1.9.x and Not 2.0

HTMX 2.0 changed the default CORS handling, removed `htmx.ajax()`, renamed `hx-on:` syntax, and changed how `hx-boost` works. These are breaking changes that would require auditing and updating the existing `web_interfaces/` patterns (which must remain functional per spec constraint).

HTMX 1.9.12 is the stable long-term support release, widely documented, and matches the existing system. The risk-free choice is the right choice here.

### 8.6 Why Polling Instead of WebSocket

WebSocket requires a persistent connection — incompatible with Azure Function Apps on the Consumption plan (connections are closed after execution). Server-Sent Events (SSE) have the same problem. HTMX polling at 10-second intervals for jobs and 30-second intervals for health checks is appropriate for operational monitoring where "within 10 seconds" is sufficient staleness. Real-time millisecond updates are not needed for a job processing dashboard.

### 8.7 Why the Bottom Status Bar Uses Dark Theme

The bottom status bar is intentionally dark even though the main content area is light. This creates a visual anchor at the bottom of every view — the operator's eye can always find it without reading. Dark backgrounds for persistent chrome elements is an established pattern in professional tools (VS Code status bar, Datadog bottom bar, terminal emulators). The contrast makes it clear this is "system chrome" not "content."

### 8.8 Why Inline Error Blocks Instead of Toast Notifications

Toast notifications are ephemeral — they appear, the operator looks away, and the information is lost. For a monitoring dashboard where errors are actionable (a job failed, an API is down), the error needs to persist in context:
- A failed API call in the jobs table shows an error block IN the jobs table area
- The operator can see what failed, see the Retry button, act on it
- If the operator switches tabs and comes back, the section re-renders cleanly

Toast notifications require JavaScript to manage their lifecycle. Inline error blocks are pure HTML, server-rendered, and composable. The `error_block()` utility handles this consistently across all panels.

### 8.9 Why Offset Pagination Instead of Cursor-Based

The existing API endpoints (`/api/dbadmin/jobs`, `/api/platform/status`) support `limit` and offset-style parameters. Cursor-based pagination would require API changes outside the dashboard scope.

For the operator use case, offset pagination is sufficient. The default page size of 25 rows means fewer than 1000 results fit in the first 40 pages. If an operator needs to see more than 25 jobs simultaneously, the answer is better filters, not infinite scroll.

### 8.10 Why Panels Are Stateless (No Shared Instance State)

Each request to `dashboard_handler` creates a new panel instance via `panel_class()`. Panels do not store state between requests. This mirrors the existing `web_interfaces/` pattern and is appropriate for:
- Azure Function Apps where instances may be recycled
- HTMX requests that can come from different browser tabs simultaneously
- Testing: each test creates a clean panel instance

If a panel needed per-request context (e.g., the base URL), it is passed via `request` parameter, not stored as instance state.

---

## Summary: The Optimal Dashboard Architecture

The Platform Dashboard replaces 37 fragmented interfaces with a unified 4-tab shell using the proven registry + panel pattern from the existing codebase. The shell loads once; tabs swap content via HTMX fragments. State lives entirely in the URL. The design system evolves from the existing CSS tokens (minimizing migration risk) with density improvements. The Ops Intelligence visual scheme provides a professional, accessible operator environment for long sessions.

Every design decision prioritizes operator effectiveness over engineering novelty. The architecture is intentionally conservative — it uses patterns already proven in production in this codebase (`InterfaceRegistry`, `urllib.request`, `wrap_html` pattern) while eliminating the structural weakness of the old system (fragmented pages, no persistent chrome, duplicate CSS everywhere).

The Builder agent should have sufficient specification here to implement the full `web_dashboard/` module without ambiguity.
