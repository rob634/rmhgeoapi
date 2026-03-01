# GREENFIELD: Platform Dashboard -- Agent M (Mediator) Resolved Spec

**Date**: 01 MAR 2026
**Agent**: M (Mediator)
**Pipeline**: GREENFIELD (7-agent: S -> A+C+O -> M -> B -> V)
**Inputs**: Original Spec, Advocate Design, Critic Report (52 findings), Operator Assessment
**Status**: RESOLVED SPEC -- Ready for Builder (Agent B)

---

## Table of Contents

1. [Conflicts Found](#1-conflicts-found)
2. [Design Tensions](#2-design-tensions)
3. [Resolved Spec](#3-resolved-spec)
4. [Deferred Decisions](#4-deferred-decisions)
5. [Risk Register](#5-risk-register)

---

## 1. CONFLICTS FOUND

### Conflict 1: HTMX CDN vs Self-Hosting (A vs O)

**Advocate** says: CDN is acceptable for an operator tool that always has network access. Uses `https://unpkg.com/htmx.org@1.9.12`.

**Operator** says: CDN is the highest operational risk. If CDN is unreachable, the dashboard is silently dead. Self-host HTMX inside the Function App package.

**Resolution**: **OPERATOR WINS**. Self-host HTMX 1.9.12. The 14KB `htmx.min.js` file is served inline in the shell HTML as a `<script>` block (not a separate route, not a CDN link). This eliminates the CDN dependency entirely with zero additional HTTP requests. The Advocate's concern about CDN caching is irrelevant when the script is inline -- the shell HTML is the cache unit.

---

### Conflict 2: `?section=` vs `?fragment=` Query Parameter Protocol (C-1)

**Original Spec** uses both `?section=` and `?fragment=` without defining the distinction.

**Advocate** defines them but blurs the boundary in some examples.

**Critic** (C-1) flags this as ambiguous.

**Resolution**: **STRICT PROTOCOL** -- these are two distinct, non-overlapping concepts:

| Parameter | Purpose | Returns | Pushes URL | HTMX Target |
|-----------|---------|---------|------------|-------------|
| `section` | Sub-tab navigation within a panel | Sub-tab bar + section content (full panel area) | Yes (`hx-push-url="true"`) | `#panel-content` |
| `fragment` | Partial refresh of a named widget | Minimal HTML (table body, card, row) | No | Element-specific (e.g., `#jobs-refresh-wrapper`) |

They are **never combined** in the same request. If `fragment` is present, `section` is ignored. Fragment requests are for auto-refresh and inline detail loads. Section requests are for sub-tab navigation.

---

### Conflict 3: Approve/Reject Action Flow -- JSON vs HTML Impedance (C-7, C-18, C-45)

**Advocate** says: The `/api/platform/approve` endpoint should detect `HX-Request` header and return HTML when called from HTMX, JSON otherwise. HTMX `hx-post` sends form-encoded data.

**Critic** (C-7) says: `hx-post` with `hx-vals` sends `application/x-www-form-urlencoded`, but `/api/platform/approve` expects `application/json`. Content-type mismatch.

**Critic** (C-18/C-45) says: Adding HX-Request detection to API endpoints violates separation of concerns and requires modifying existing, tested API code.

**Resolution**: **DASHBOARD PROXY PATTERN**. The dashboard handler acts as a proxy for mutating actions. The Builder must NOT modify existing API endpoints.

Flow:
1. HTMX `hx-post` targets `/api/dashboard?action=approve` (not `/api/platform/approve` directly)
2. The dashboard handler receives form-encoded data from HTMX
3. The dashboard handler calls `/api/platform/approve` server-side via `call_api()` with JSON body
4. The dashboard handler receives JSON response from the API
5. The dashboard handler renders an HTML fragment (updated row) and returns it to HTMX

This resolves all three issues:
- No content-type mismatch (dashboard handler translates form-encoded to JSON)
- No modification to existing API endpoints (they continue returning JSON)
- Clean separation of concerns (dashboard owns HTML rendering, API owns business logic)

The dashboard handler gains a POST route. The `action` query parameter selects the action handler:

```
POST /api/dashboard?action=approve   -> calls /api/platform/approve (JSON)
POST /api/dashboard?action=reject    -> calls /api/platform/reject (JSON)
POST /api/dashboard?action=revoke    -> calls /api/platform/revoke (JSON)
POST /api/dashboard?action=submit    -> calls /api/platform/submit (JSON)
POST /api/dashboard?action=validate  -> calls /api/platform/validate (JSON)
POST /api/dashboard?action=ensure    -> calls /api/dbadmin/maintenance?action=ensure (JSON)
POST /api/dashboard?action=rebuild   -> calls /api/dbadmin/maintenance?action=rebuild (JSON)
```

---

### Conflict 4: API Endpoint URLs -- Wrong in Original Spec (C-42)

**Original Spec** lists: `/api/jobs/events/{job_id}` and `/api/jobs/logs/{job_id}`

**Actual routes** (verified in `function_app.py`):
- `/api/jobs/{job_id}/events` (line 509)
- `/api/jobs/{job_id}/logs` (line 552)

**Resolution**: Use the **ACTUAL** routes. The corrected endpoint table is in Section 3.11 below.

---

### Conflict 5: Full Page vs Fragment on Direct URL Access (C-38)

**Critic** (C-38) says: `hx-push-url="true"` means a user can bookmark `/api/dashboard?tab=jobs` and access it directly (no HX-Request header). The handler must detect this and return the full shell with the jobs tab active, not a fragment.

**Advocate** handles this correctly in the `dashboard_handler` code: when `HX-Request` header is absent, it calls `_shell.render()` which returns the full HTML document. When HX-Request is present, it calls `_shell.render_fragment()`.

**Resolution**: **ADVOCATE'S APPROACH IS CORRECT** but must be made explicit as a requirement. The Builder must test all three paths:

1. `GET /api/dashboard?tab=jobs` (no HX-Request) -> full HTML shell + jobs panel
2. `GET /api/dashboard?tab=jobs` (with HX-Request) -> fragment for `#main-content`
3. `GET /api/dashboard?tab=jobs&fragment=jobs-table` (with HX-Request) -> table body only

---

### Conflict 6: Style Variant Selection (A vs spec -- all agents weigh in)

**Advocate** champions "Ops Intelligence" -- a synthesis of V1 (Current) and V2 (Dark Operator).

**Operator** says V1 is operationally proven, V3 is safest new choice, V4 has font-loading risk.

**Critic** would challenge V2's WCAG compliance.

**Resolution**: **ADVOCATE'S "OPS INTELLIGENCE" SYNTHESIS -- ADOPTED WITH MODIFICATIONS**.

The synthesis is well-reasoned: light background for accessibility, V1's proven status colors, tighter spacing for density, dark bottom status bar for ops feel. Two modifications:

1. **Font stack**: Remove Inter as a named font. Use system font stack only: `system-ui, -apple-system, "Segoe UI", "Open Sans", sans-serif`. Inter is not a system font on most machines. Self-hosting fonts is out of scope for MVP. Open Sans is kept as a fallback since it is likely cached from existing interfaces.

2. **Base font size**: Keep at `14px` (V1's value), not the Advocate's proposed `13px`. The 1px reduction saves minimal space but reduces readability. The density gain comes from tighter padding and margins, not smaller text.

Full CSS token table in Section 3.2.

---

### Conflict 7: Which App Hosts the Dashboard (C-25/C-51)

**Critic** asks: Which of the 3 apps (orchestrator/gateway/docker) hosts the dashboard?

**Operator** recommends no APP_MODE gate.

**Resolution**: The dashboard route is registered on the **orchestrator** (`rmhazuregeoapi`, `APP_MODE=standalone`) only. It is NOT gated by `_app_mode` conditionals -- the web_interfaces route is also ungated and this mirrors that pattern. The gateway and docker worker do not serve UI. If the dashboard is loaded on a gateway/worker deployment, the API calls from panels will return errors, and panels will show error blocks. This is acceptable and self-diagnosing.

---

### Conflict 8: Authentication/Authorization (C-23/C-27/C-28)

**Critic** flags: Zero authentication. Anyone with the URL can approve releases and rebuild schemas.

**Advocate**: Silent on auth.

**Operator**: Silent on auth.

**Resolution**: **ACKNOWLEDGED GAP -- DOCUMENTED, NOT BLOCKED**. The existing API endpoints (`/api/platform/approve`, `/api/dbadmin/maintenance`) have no authentication today. The dashboard does not introduce new security surface -- it calls the same endpoints. Auth is a cross-cutting concern for the entire API, not the dashboard specifically.

The Builder must:
1. Add a comment in `dashboard_handler`: `# AUTH: No authentication enforced. Dashboard inherits API-level auth (currently none).`
2. The maintenance actions (ensure/rebuild) use `hx-confirm` double-confirmation as a UX guard, not a security control.
3. Auth is explicitly listed in DEFERRED DECISIONS (Section 4).

---

### Conflict 9: Empty States (C-10/C-30)

**Critic** says no empty states defined for zero jobs, zero approvals, fresh deployment.

**Advocate** provides `empty_block()` utility but does not define per-section empty messages.

**Resolution**: Every section must define its empty state message. The Builder must use `self.empty_block(message)` for each:

| Section | Empty State Message |
|---------|-------------------|
| Platform > Requests | "No platform requests found. Use the Submit tab to create one." |
| Platform > Approvals | "No pending approvals. All releases have been reviewed." |
| Platform > Catalog | "Enter a dataset ID or resource ID to search the catalog." |
| Jobs > Monitor | "No jobs found. The system is idle." |
| Jobs > Tasks | "Select a job from the Monitor tab to view its tasks." |
| Jobs > Failures | "No failed jobs in the selected time period." |
| Data > Assets | "No assets registered. Submit data via the Platform tab." |
| Data > STAC | "No STAC collections found." |
| Data > Vector | "No vector collections found." |
| System > Health | (Always shows cards -- health endpoints always respond) |
| System > Database | "Database diagnostics unavailable." |
| System > Queues | "Queue information unavailable." |
| System > Maintenance | (Always shows action buttons -- no empty state) |

---

### Conflict 10: Loading States (C-29)

**Critic** says no loading states defined for HTMX requests.

**Advocate** provides `loading_placeholder()` utility but does not specify where it is used.

**Resolution**: HTMX provides built-in loading indicators via the `htmx-request` CSS class. The shell CSS must include:

```css
.htmx-indicator {
    display: none;
}
.htmx-request .htmx-indicator,
.htmx-request.htmx-indicator {
    display: inline-block;
}
```

Usage pattern:
- Tab switches: The tab link gets `hx-indicator="#loading-bar"` pointing to a thin loading bar below the tab bar.
- Auto-refresh: No loading indicator (silent background refresh -- the data updates in place).
- Row detail expansion: The detail panel div shows a spinner via `loading_placeholder()`.
- Form submissions (submit/validate/approve): The button gets `hx-indicator="closest .btn-indicator"` showing a spinner next to the button.

---

### Conflict 11: Double-Click Prevention (C-16)

**Critic** says: Double-click on approve sends two requests. No idempotency guard.

**Resolution**: Use HTMX's built-in `hx-disable` attribute extension (available in 1.9.x). All action buttons (approve, reject, revoke, submit, rebuild) must include:

```html
<button hx-post="/api/dashboard?action=approve"
        hx-disabled-elt="this"
        ...>
  Approve
</button>
```

`hx-disabled-elt="this"` disables the button during the HTMX request, preventing double-clicks. The button re-enables when the response arrives. Server-side, the approve endpoint is already idempotent (approving an already-approved release returns success).

---

### Conflict 12: Approval Wireframe Missing Fields (C-40)

**Critic** says: Approval wireframe is missing required `version_id` and `clearance_state` fields.

**Resolution**: The approval action form must include all fields required by `/api/platform/approve`:

```
Required fields in HTMX hx-vals:
- release_id (string) -- from the row data
- reviewer (string) -- from input field
- clearance (string) -- from dropdown (OUO, PUBLIC, UNCLEARED)

Optional:
- notes (string) -- from textarea
- version_id (string) -- populated from row data, hidden input
```

The approval detail expansion panel (on row click) must display: release_id, asset identifier, version, ordinal, associated job status, STAC item reference, blob path, and provide clearance dropdown + reviewer input.

---

### Conflict 13: Default Tab and Default Sub-Tab (C-47)

**Critic** says: Default tab and default sub-tab not specified.

**Advocate** says: Default tab is `platform`, default section per panel is declared by `default_section()`.

**Resolution**: Explicit defaults:

| Tab | Default Section |
|-----|----------------|
| platform | `requests` |
| jobs | `monitor` |
| data | `assets` |
| system | `health` |

When `/api/dashboard` is loaded with no query params, the response is: Platform tab active, Requests section displayed.

---

### Conflict 14: Auto-Refresh Fires on Inactive Tabs (C-48)

**Critic** says: Auto-refresh triggers fire even when the user has navigated away from the tab.

**Operator** provides the solution: use `document.visibilityState` check in the HTMX trigger.

**Resolution**: All auto-refresh triggers must include the visibility guard:

```html
hx-trigger="every 10s [document.visibilityState === 'visible']"
```

Additionally, when the user switches to a different tab, the old tab's content is removed from the DOM (replaced by the new tab's content). HTMX triggers on elements not in the DOM do not fire. This is the primary protection -- the visibility guard is a secondary protection for browser tab backgrounding.

Auto-refresh intervals:
- Jobs Monitor table: `every 10s`
- System Health cards: `every 30s`
- No other sections auto-refresh by default

---

### Conflict 15: File Headers Not Mentioned (C-37)

**Critic** says: File header template not mentioned.

**Tier 2 Constraint**: All .py files must use the project file header template.

**Resolution**: The Advocate's design already includes file headers on `shell.py`, `base_panel.py`, and `registry.py`. This is a Tier 2 requirement -- the Builder must include the standard file header on ALL .py files in `web_dashboard/`. The exact template from CLAUDE.md:

```python
# ============================================================================
# CLAUDE CONTEXT - [DESCRIPTIVE_TITLE]
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: [Component type] - [Brief description]
# PURPOSE: [One sentence description]
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: [Main classes, functions, constants]
# DEPENDENCIES: [Key external libraries]
# ============================================================================
```

---

### Conflict 16: Testing Strategy (C-36)

**Critic** says: No testing strategy defined.

**Resolution**: See Section 3.15 below.

---

### Conflict 17: Import Safety in function_app.py (O priority 2)

**Operator** says: Wrap dashboard import in try/except to prevent a broken dashboard from taking down the entire Function App.

**Advocate**: Does not address this.

**Resolution**: **OPERATOR WINS**. The dashboard import in `function_app.py` must be wrapped:

```python
try:
    from web_dashboard import dashboard_handler as _dashboard_handler
    _dashboard_available = True
except Exception as _dashboard_import_err:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        f"web_dashboard import failed: {_dashboard_import_err}. "
        f"/api/dashboard will return 503."
    )
    _dashboard_available = False
```

The route handler must check `_dashboard_available` and return 503 if False.

---

## 2. DESIGN TENSIONS

### Tension 1: PanelRegistry Decorator Pattern vs Tier 2 "Mirror InterfaceRegistry"

**Tier 2 says**: Use `PanelRegistry` decorator for panel auto-discovery (mirror InterfaceRegistry).

**Advocate** says: `@PanelRegistry.register` takes no arguments -- the class self-describes via `tab_name()`. InterfaceRegistry takes a string argument.

**Resolution**: The Advocate's no-argument decorator is the BETTER pattern. "Mirror InterfaceRegistry" means mirror the concept (decorator-based auto-discovery), not the exact API. The self-describing pattern prevents name drift. This is an improvement over InterfaceRegistry, not a deviation.

---

### Tension 2: No Backward Compatibility Shims vs Dashboard Error Isolation

**Tier 2 says**: No backward compatibility shims. Fail explicitly, never create fallbacks.

**Operator says**: Panels must catch API errors and show inline error cards. The dashboard_handler must catch panel render exceptions and show error HTML.

**Resolution**: These are NOT in conflict. The "no backward compatibility" rule applies to data model evolution and migration patterns (e.g., do not silently default missing fields). Error handling in a UI is not a "backward compatibility shim" -- it is correct behavior. A panel showing "API returned 503 -- Retry" is failing explicitly. It is not silently masking a problem; it is reporting the problem to the operator with an action.

The Builder must:
- Use `call_api()` which returns `(False, error_msg)` on failure -- panels must check the `success` flag and call `self.error_block()` on failure.
- Never use a bare `except: pass` -- all exceptions must be logged with `logger.exception()` and displayed as error blocks.
- Never create silent fallback data (e.g., returning an empty jobs list when the API is down).

---

### Tension 3: Error Handling -- Contract Violations vs Business Errors

**Tier 2 says**: Contract violations (`ContractViolationError`) bubble up. Business errors (`BusinessLogicError`) handled gracefully.

**Application to Dashboard**:
- **Contract violation**: A panel receives a fragment name it does not recognize -> `raise ValueError("Unknown fragment: {name}")` -> dashboard_handler catches and returns 400. This bubbles up correctly.
- **Business error**: API returns 500 because a job query failed -> panel calls `self.error_block()` -> returns inline error HTML. Handled gracefully.
- **Programming bug**: Panel code has a NameError or TypeError -> dashboard_handler's outer except catches it, logs full traceback, returns error HTML with HTTP 200 (so the shell chrome survives). This is correct -- the shell must not crash because one panel has a bug.

---

### Tension 4: Military Date Format Everywhere

**Tier 2 says**: All timestamps as `01 MAR 2026`.

**Advocate** implements `format_date()` server-side returning `"01 MAR 2026 14:30 ET"`.

**Resolution**: The Advocate's implementation is correct. The format must be `DD MMM YYYY HH:MM ET` for datetime values and `DD MMM YYYY` for date-only values. All timestamps in the dashboard must use `self.format_date()`. No raw ISO strings in rendered HTML.

---

### Tension 5: Status Badge Semantics Must Match Existing Mapping

**Tier 2 says**: Status badge semantics must match existing job/approval state color mapping.

**Advocate** keeps V1's exact status badge colors.

**Resolution**: The Advocate's badge colors are correct and must be used exactly. Additional badge types needed:

| Badge Type | States | Source |
|------------|--------|--------|
| `status_badge()` | queued, pending, processing, completed, failed | Job/request status |
| `approval_badge()` | pending_review, approved, rejected, revoked | Release approval state |
| `clearance_badge()` | uncleared, ouo, public | Clearance level |
| `data_type_badge()` | raster, vector, zarr | Data type indicator |

---

## 3. RESOLVED SPEC

### 3.1 Directory Structure (Final)

```
web_dashboard/
    __init__.py              # Route handler (dashboard_handler), panel imports, DEFAULT_TAB
    shell.py                 # DashboardShell: chrome, tabs, CSS, JS, HTML envelope
    base_panel.py            # BasePanel: abstract contract + shared utility methods
    registry.py              # PanelRegistry: decorator registration, get, list
    panels/
        __init__.py          # Auto-import trigger for panel modules
        platform.py          # Tab: PLATFORM -- submit, requests, approvals, catalog, lineage, failures
        jobs.py              # Tab: JOBS -- monitor, tasks, pipeline, failures
        data.py              # Tab: DATA -- assets, STAC, vector, storage
        system.py            # Tab: SYSTEM -- health, database, queues, maintenance
```

No additional files. No `static/` directory. No templates directory. All HTML/CSS/JS is inline Python strings.

---

### 3.2 Style Variant -- "Ops Intelligence" (Final CSS Token Table)

**Selected Variant**: Ops Intelligence (Advocate's synthesis, modified per Mediator).

| CSS Custom Property | Value | Notes |
|--------------------|----|-------|
| `--ds-bg` | `#F0F2F5` | Cooler background than V1 |
| `--ds-surface` | `#FFFFFF` | Card/panel background |
| `--ds-navy` | `#0D2137` | Headings, strong text |
| `--ds-blue-primary` | `#0071BC` | Links, primary buttons, active tab accent |
| `--ds-blue-dark` | `#245AAD` | Hover on primary elements |
| `--ds-cyan` | `#00A3DA` | Secondary links, hover accent |
| `--ds-gold` | `#FFC14D` | Highlight badges ("latest", "new") |
| `--ds-gray` | `#626F86` | Secondary text |
| `--ds-gray-light` | `#DDE1E9` | Borders, dividers |
| `--ds-border` | `#C5CBD8` | Table borders, card borders |
| `--ds-text-primary` | `#0D2137` | Main body text (same as navy) |
| `--ds-text-secondary` | `#4A5568` | Labels, metadata, filter labels |
| `--ds-font` | `system-ui, -apple-system, "Segoe UI", "Open Sans", sans-serif` | System font stack, no CDN |
| `--ds-font-mono` | `"SF Mono", "Monaco", "Cascadia Code", monospace` | Code, IDs, UUIDs |
| `--ds-font-size` | `14px` | Body text |
| `--ds-font-size-sm` | `12px` | Badges, metadata |
| `--ds-font-size-lg` | `16px` | Section headings |
| `--ds-font-size-xl` | `20px` | Tab labels, page headers |
| `--ds-radius-card` | `6px` | Cards, panels |
| `--ds-radius-btn` | `4px` | Buttons |
| `--ds-radius-badge` | `10px` | Status badges |
| `--ds-shadow` | `0 1px 3px rgba(13,33,55,0.10)` | Card elevation |
| `--ds-shadow-hover` | `0 2px 8px rgba(13,33,55,0.15)` | Card hover (optional) |
| `--ds-status-bar-bg` | `#1A1A2E` | Bottom status bar background (dark) |
| `--ds-status-bar-text` | `#E0E0E0` | Bottom status bar text |

**Status Badge Colors (MANDATORY -- do not change)**:

| Status | `--ds-status-{name}-bg` | `--ds-status-{name}-text` | CSS Class |
|--------|------------------------|--------------------------|-----------|
| Queued | `#F3F4F6` | `#6B7280` | `.status-queued` |
| Pending | `#FEF3C7` | `#D97706` | `.status-pending` |
| Processing | `#DBEAFE` | `#0071BC` | `.status-processing` |
| Completed | `#D1FAE5` | `#059669` | `.status-completed` |
| Failed | `#FEE2E2` | `#DC2626` | `.status-failed` |

**Approval Badge Colors**:

| State | Background | Text | CSS Class |
|-------|-----------|------|-----------|
| Pending Review | `#FEF3C7` | `#D97706` | `.approval-pending_review` |
| Approved | `#D1FAE5` | `#059669` | `.approval-approved` |
| Rejected | `#FEE2E2` | `#DC2626` | `.approval-rejected` |
| Revoked | `#F3F4F6` | `#6B7280` | `.approval-revoked` |

---

### 3.3 Route Contract (Complete)

**Route registration** in `function_app.py`:

```python
@app.route(route="dashboard", methods=["GET", "POST"])
def platform_dashboard(req: func.HttpRequest) -> func.HttpResponse:
    ...
```

**GET requests** -- UI rendering:

| URL | HX-Request | Response |
|-----|-----------|----------|
| `/api/dashboard` | absent | Full HTML document. Platform tab, Requests section. |
| `/api/dashboard?tab=jobs` | absent | Full HTML document. Jobs tab, Monitor section. |
| `/api/dashboard?tab=jobs` | `true` | HTML fragment for `#main-content` + OOB tab bar update. |
| `/api/dashboard?tab=jobs&section=tasks` | `true` | HTML fragment for `#panel-content` (sub-tab switch). |
| `/api/dashboard?tab=jobs&fragment=jobs-table` | `true` | Minimal HTML (table body only) for auto-refresh swap. |
| `/api/dashboard?tab=jobs&fragment=job-detail&job_id=abc` | `true` | Detail card HTML for `#detail-panel`. |

**POST requests** -- action proxy:

| URL | Body (form-encoded) | Proxied To | Response |
|-----|----|----|-----|
| `/api/dashboard?action=approve` | `release_id, reviewer, clearance, notes` | `POST /api/platform/approve` (JSON) | HTML fragment (updated row) |
| `/api/dashboard?action=reject` | `release_id, reviewer, reason` | `POST /api/platform/reject` (JSON) | HTML fragment (updated row) |
| `/api/dashboard?action=revoke` | `release_id, reviewer, reason` | `POST /api/platform/revoke` (JSON) | HTML fragment (updated row) |
| `/api/dashboard?action=submit` | form fields | `POST /api/platform/submit` (JSON) | HTML fragment (result card) |
| `/api/dashboard?action=validate` | form fields | `POST /api/platform/validate` (JSON) | HTML fragment (validation result) |
| `/api/dashboard?action=ensure` | `confirm=yes` | `POST /api/dbadmin/maintenance?action=ensure&confirm=yes` | HTML fragment (result) |
| `/api/dashboard?action=rebuild` | `confirm=yes, target` | `POST /api/dbadmin/maintenance?action=rebuild&confirm=yes` | HTML fragment (result) |

**Query parameter catalog**:

| Param | Type | Used By | Notes |
|-------|------|---------|-------|
| `tab` | str | All | Tab name. Default: `platform` |
| `section` | str | All | Sub-tab section. Default: panel's `default_section()` |
| `fragment` | str | All | Named fragment for partial refresh. Mutually exclusive with section. |
| `action` | str | POST only | Action name for proxy dispatch |
| `status` | str | platform, jobs | Filter by status value |
| `hours` | int | platform, jobs | Time window filter |
| `limit` | int | platform, jobs, data | Page size. Default: `25` |
| `page` | int | platform, jobs, data | Page number (0-indexed). Default: `0` |
| `job_id` | str | jobs | Scope to a specific job |
| `request_id` | str | platform | Scope to a specific request |
| `release_id` | str | platform | Scope to a specific release |
| `dataset_id` | str | data | Scope to a dataset |
| `q` | str | data | Search term |

---

### 3.4 Panel Interface (Exact Method Signatures)

```python
from abc import ABC, abstractmethod
from typing import Optional, Any
import azure.functions as func


class BasePanel(ABC):
    """Abstract base for all dashboard panels."""

    # --- Abstract methods (MUST override) ---

    @abstractmethod
    def tab_name(self) -> str:
        """URL key for this tab. Example: 'platform'"""

    @abstractmethod
    def tab_label(self) -> str:
        """Display label. Example: 'Platform'"""

    @abstractmethod
    def default_section(self) -> str:
        """Default sub-tab key. Example: 'requests'"""

    @abstractmethod
    def sections(self) -> list[tuple[str, str]]:
        """
        Return ordered list of (section_key, display_label) tuples.
        Example: [('requests', 'Requests'), ('approvals', 'Approvals')]
        """

    @abstractmethod
    def render_section(self, request: func.HttpRequest, section: str) -> str:
        """
        Render a section's content (sub-tab body).

        Args:
            request: HTTP request with query params for filters/context.
            section: Section key from sections().

        Returns:
            HTML fragment for the section content area.

        Raises:
            ValueError: If section is not recognized.
        """

    @abstractmethod
    def render_fragment(self, request: func.HttpRequest, fragment_name: str) -> str:
        """
        Render a named fragment for auto-refresh or detail expansion.

        Args:
            request: HTTP request with query params for context.
            fragment_name: Fragment identifier.

        Returns:
            Minimal HTML fragment.

        Raises:
            ValueError: If fragment_name is not recognized.
        """

    # --- Concrete methods (do NOT override) ---

    def render(self, request: func.HttpRequest) -> str:
        """
        Render the full panel content (sub-tab bar + section content).

        Reads section= from request params, falls back to default_section().
        Returns sub_tab_bar + <div id="panel-content">{section_html}</div>.
        """
        section = request.params.get("section", "") or self.default_section()
        if section not in dict(self.sections()):
            section = self.default_section()
        tab_bar = self.sub_tab_bar(self.sections(), section, self.tab_name())
        section_html = self.render_section(request, section)
        panel_css = self.get_panel_css() or ""
        style_block = f"<style>{panel_css}</style>" if panel_css else ""
        return f'{style_block}{tab_bar}<div id="panel-content">{section_html}</div>'

    def get_panel_css(self) -> Optional[str]:
        """Override to add panel-specific CSS. Default: None."""
        return None

    # --- Utility methods ---

    def status_badge(self, status: str) -> str: ...
    def approval_badge(self, state: str) -> str: ...
    def clearance_badge(self, level: str) -> str: ...
    def format_date(self, iso_str: Optional[str], fallback: str = "--") -> str: ...
    def format_age(self, iso_str: Optional[str]) -> str: ...
    def call_api(self, path: str, params: Optional[dict] = None,
                 method: str = "GET", body: Optional[dict] = None,
                 timeout: int = 10) -> tuple[bool, Any]: ...
    def data_table(self, headers: list[str], rows: list[list[str]],
                   table_id: str = "data-table",
                   row_htmx: Optional[list[dict]] = None) -> str: ...
    def stat_strip(self, counts: dict[str, int]) -> str: ...
    def error_block(self, message: str, retry_url: Optional[str] = None) -> str: ...
    def empty_block(self, message: str = "No results found.") -> str: ...
    def loading_placeholder(self, fragment_url: str, target_id: str) -> str: ...
    def sub_tab_bar(self, sections: list[tuple[str, str]],
                    active_section: str, tab_name: str) -> str: ...
```

**Key design notes**:
- `render()` is a concrete template method, NOT abstract. It calls `render_section()`. Panels override `render_section()` and `render_fragment()`, never `render()`.
- `call_api()` base_url defaults to `http://localhost:7071` for same-process calls. Timeout is 10 seconds per call.
- `call_api()` returns `(bool, Any)` -- panels must ALWAYS check the bool before using the data.

---

### 3.5 HTMX Protocol (Complete)

**HTMX Version**: 1.9.12 (self-hosted, inline in shell HTML).

**Detection Logic in `dashboard_handler`**:

```python
is_htmx = req.headers.get("HX-Request") == "true"
tab = req.params.get("tab", DEFAULT_TAB)
section = req.params.get("section", "")
fragment = req.params.get("fragment", "")
action = req.params.get("action", "")

if req.method == "POST" and action:
    # Action proxy (approve, reject, submit, etc.)
    return _handle_action(req, action)

if fragment:
    # Named fragment (auto-refresh, row detail)
    return _handle_fragment(req, tab, fragment)

if is_htmx and section:
    # Sub-tab switch (return section content for #panel-content)
    return _handle_section(req, tab, section)

if is_htmx:
    # Tab switch (return panel fragment for #main-content + OOB tab bar)
    return _handle_tab_switch(req, tab)

# Full page load (no HX-Request header)
return _handle_full_page(req, tab)
```

**Tab switch HTML** (returned by shell `render_fragment()`):

The response contains two elements:
1. Updated tab bar with OOB swap: `<nav id="tab-bar" hx-swap-oob="true">...</nav>`
2. Panel content for primary swap: content wrapped for `#main-content`

**Sub-tab switch HTML** (returned by panel `render_section()`):

Just the section content. HTMX swaps it into `#panel-content`. The sub-tab bar is NOT re-rendered on sub-tab switches within the same request -- HTMX handles the active class update via OOB swap of the `#sub-tabs` element.

Actually, correction: the sub-tab bar MUST be re-rendered to update active states. The response for a sub-tab switch must include:

```html
<nav id="sub-tabs" hx-swap-oob="true">{updated sub-tab bar}</nav>
<div id="panel-content">{section content}</div>
```

**Auto-refresh HTML pattern**:

```html
<div id="{refresh-wrapper-id}"
     hx-get="/api/dashboard?tab={tab}&fragment={fragment_name}"
     hx-trigger="every {interval}s [document.visibilityState === 'visible']"
     hx-target="this"
     hx-swap="innerHTML">
  {refreshable content here}
</div>
```

The fragment response is ONLY the inner content (not the wrapper div).

**Tab navigation HTML pattern**:

```html
<a hx-get="/api/dashboard?tab={name}"
   hx-target="#main-content"
   hx-push-url="true"
   hx-swap="innerHTML"
   hx-indicator="#loading-bar"
   class="tab {active_class}">
  {label}
</a>
```

**Sub-tab navigation HTML pattern**:

```html
<a hx-get="/api/dashboard?tab={tab}&section={section}"
   hx-target="#panel-content"
   hx-push-url="true"
   hx-swap="innerHTML"
   class="sub-tab {active_class}">
  {label}
</a>
```

**Action button HTML pattern** (approve/reject):

```html
<button hx-post="/api/dashboard?action=approve"
        hx-vals='{"release_id": "{id}", "reviewer": "", "clearance": "OUO"}'
        hx-target="#row-{id}"
        hx-swap="outerHTML"
        hx-confirm="Approve release {id}? This publishes the dataset."
        hx-disabled-elt="this"
        hx-indicator="closest .btn-indicator"
        class="btn btn-sm btn-approve">
  Approve
</button>
<span class="btn-indicator htmx-indicator">...</span>
```

---

### 3.6 Error Handling (Loading, Empty, Error States)

**Three states every section must handle**:

1. **Loading state**: Used for deferred-load sections (STAC, Vector, heavy queries). The `loading_placeholder(url, id)` method renders:
```html
<div id="{id}" hx-get="{url}" hx-trigger="load" hx-swap="outerHTML">
  <div class="loading-state">
    <div class="spinner"></div>
    <p class="spinner-text">Loading...</p>
  </div>
</div>
```

2. **Empty state**: Used when API returns success but zero results. The `empty_block(msg)` method renders:
```html
<div class="empty-state">
  <div class="empty-icon">--</div>
  <p>{message}</p>
</div>
```

3. **Error state**: Used when API call fails. The `error_block(msg, retry_url)` method renders:
```html
<div class="error-block">
  <span class="error-icon">!</span>
  <span class="error-message">{message}</span>
  <a class="btn btn-sm btn-secondary"
     hx-get="{retry_url}" hx-target="closest .error-block" hx-swap="outerHTML">
    Retry
  </a>
</div>
```

**CSS for these states**:

```css
.loading-state { text-align: center; padding: 2rem; color: var(--ds-gray); }
.spinner { /* CSS-only spinning animation */ }
.empty-state { text-align: center; padding: 3rem 1rem; color: var(--ds-gray); }
.empty-icon { font-size: 2rem; margin-bottom: 0.5rem; }
.error-block {
    background: var(--ds-status-failed-bg);
    border-left: 4px solid var(--ds-status-failed-text);
    padding: 1rem;
    margin: 1rem 0;
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
```

**HTMX error response handling**: When the dashboard_handler returns HTTP 200 with error HTML, HTMX swaps it normally. For HTTP 4xx/5xx responses, HTMX by default does NOT swap. To ensure errors display, add this shell-level HTMX config:

```html
<meta name="htmx-config" content='{"responseHandling": [{"code":"*", "swap": true}]}'>
```

Wait -- HTMX 1.9.x does not support `responseHandling` config. Instead, use `htmx.on("htmx:responseError", ...)` in shell JS to handle non-2xx responses. OR: the dashboard handler should always return HTTP 200 for fragment/tab requests and include error content in the HTML body. The HTTP status code is for API clients; the dashboard is a UI and should always render.

**Final decision**: Dashboard handler returns HTTP 200 for all UI rendering responses (full page, tab switch, fragment, section). Error content is in the HTML body. Only return non-200 for truly invalid requests (404 for unknown tab when no HX-Request, 400 for unknown fragment).

---

### 3.7 APP_MODE (Final)

The dashboard is deployed on the **orchestrator** app (`rmhazuregeoapi`, `APP_MODE=standalone`). The route is NOT gated by `_app_mode` conditionals. The dashboard calls existing API endpoints, which are themselves gated by APP_MODE. If an endpoint is unavailable, the panel shows an error block.

---

### 3.8 Correct API Endpoint URLs (Fixing C-42)

**Jobs Tab Endpoints (corrected)**:

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/api/dbadmin/jobs` | GET | Job list with filters |
| `/api/dbadmin/jobs/{id}` | GET | Job detail |
| `/api/dbadmin/tasks/{job_id}` | GET | Task drill-down |
| `/api/jobs/status/{job_id}` | GET | Stage visualization |
| `/api/jobs/{job_id}/events` | GET | Event timeline |
| `/api/jobs/{job_id}/events/latest` | GET | Latest event |
| `/api/jobs/{job_id}/events/failure` | GET | Failure detail |
| `/api/jobs/{job_id}/logs` | GET | Job logs |
| `/api/platform/failures` | GET | Failure analysis |

**Platform Tab Endpoints (unchanged)**:

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/api/platform/submit` | POST | Submit form (proxied via dashboard action) |
| `/api/platform/validate` | POST | Dry-run validation (proxied via dashboard action) |
| `/api/platform/status` | GET | Request list |
| `/api/platform/status/{id}` | GET | Request detail |
| `/api/platform/health` | GET | Platform health card |
| `/api/platform/failures` | GET | Failures sub-tab |
| `/api/platform/lineage/{id}` | GET | Lineage view |
| `/api/platform/approve` | POST | Approve action (proxied via dashboard action) |
| `/api/platform/reject` | POST | Reject action (proxied via dashboard action) |
| `/api/platform/revoke` | POST | Revoke action (proxied via dashboard action) |
| `/api/platform/approvals` | GET | Approval queue list |
| `/api/platform/approvals/{id}` | GET | Approval detail |
| `/api/platform/approvals/status` | GET | Batch status lookup |
| `/api/platform/catalog/lookup` | GET | Catalog search |
| `/api/platform/catalog/asset/{id}` | GET | Asset detail |
| `/api/platform/catalog/dataset/{id}` | GET | Dataset listing |
| `/api/platform/catalog/item/{c}/{i}` | GET | STAC item view |

**Data Tab Endpoints**:

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/api/stac/collections` | GET | STAC collection list |
| `/api/stac/collections/{id}` | GET | Collection detail |
| `/api/stac/collections/{id}/items` | GET | Item browse |
| `/api/features/collections` | GET | Vector collection list |
| `/api/assets/pending-review` | GET | Pending assets |
| `/api/assets/approval-stats` | GET | Approval counts |

**System Tab Endpoints**:

| Endpoint | Method | Dashboard Usage |
|----------|--------|----------------|
| `/health` | GET | Liveness |
| `/system-health` | GET | Detailed health |
| `/api/platform/health` | GET | Platform readiness |
| `/api/dbadmin/health` | GET | DB health |
| `/api/dbadmin/health/performance` | GET | DB performance |
| `/api/dbadmin/diagnostics` | GET | Full diagnostics |
| `/api/dbadmin/activity` | GET | Active queries |
| `/api/dbadmin/schemas` | GET | Schema stats |
| `/api/stac/health` | GET | STAC health |
| `/api/dbadmin/maintenance` | POST | Schema operations (proxied via dashboard action) |

---

### 3.9 Approve/Reject Action Flow (Complete)

```
1. Operator clicks [Approve] button in approvals table
2. Browser shows confirm dialog (hx-confirm)
3. Operator confirms
4. HTMX sends POST /api/dashboard?action=approve
   Content-Type: application/x-www-form-urlencoded
   Body: release_id=rel-abc&reviewer=operator&clearance=OUO
   Headers: HX-Request: true
5. dashboard_handler receives POST, reads action=approve
6. _handle_action() extracts form data from request body
7. _handle_action() calls call_api("/api/platform/approve",
     method="POST", body={"release_id": "rel-abc", "reviewer": "operator", "clearance": "OUO"})
8. /api/platform/approve processes and returns JSON:
   {"success": true, "status": "approved", ...}
9. _handle_action() receives JSON response
10. _handle_action() renders an HTML table row showing updated state:
    <tr id="row-rel-abc" class="approved-row">...</tr>
11. Returns HttpResponse(html_row, mimetype="text/html", status_code=200)
12. HTMX swaps #row-rel-abc with new row HTML (hx-swap="outerHTML")
```

If step 8 fails (API returns error JSON or HTTP error):
```
9. call_api returns (False, "HTTP 500: Internal Server Error")
10. _handle_action() renders error HTML:
    <tr id="row-rel-abc"><td colspan="6">
      <div class="error-block">Approve failed: HTTP 500. <a ...>Retry</a></div>
    </td></tr>
11. Returns HttpResponse(error_html, mimetype="text/html", status_code=200)
12. HTMX swaps the row with the error row
```

---

### 3.10 Auto-Refresh Rules (Final)

| Panel | Section | Fragment Name | Interval | Visibility Guard |
|-------|---------|--------------|----------|-----------------|
| Jobs | Monitor | `jobs-table` | 10s | Yes |
| System | Health | `health-cards` | 30s | Yes |

**All other sections do NOT auto-refresh.** Operators manually refresh by:
- Clicking the Refresh button in the filter bar
- Switching away and back to the sub-tab
- Using browser refresh (F5)

The visibility guard `[document.visibilityState === 'visible']` prevents polling when:
- The browser tab is not focused (user switched to another browser tab)
- The window is minimized

Additionally, when the user switches to a different dashboard tab, the old tab's content (including auto-refresh divs) is removed from the DOM, stopping all auto-refresh naturally.

---

### 3.11 Double-Click Prevention (Final)

All mutating action buttons use `hx-disabled-elt="this"`:

```html
<button hx-post="/api/dashboard?action=approve"
        hx-disabled-elt="this"
        ...>Approve</button>
```

This attribute disables the button element while the HTMX request is in flight. It re-enables when the response arrives. Combined with `hx-confirm`, this provides two layers of protection:
1. Confirmation dialog prevents accidental clicks
2. `hx-disabled-elt` prevents rapid double-clicks after confirmation

The submit button on the submit form also uses this pattern.

---

### 3.12 Pagination Defaults (Final)

| Parameter | Default | Range |
|-----------|---------|-------|
| `limit` | 25 | 10 - 100 |
| `page` | 0 | 0 - N |

**Pagination model**: Offset-based (`page * limit`).

The existing `/api/dbadmin/jobs` endpoint supports `limit` parameter natively. Page offset is calculated: `offset = page * limit`.

Pagination controls rendered at bottom of every data table:

```html
<div class="pagination">
  <span class="page-info">Showing 1-25 of 47</span>
  <a hx-get="/api/dashboard?tab=jobs&section=monitor&page=0&limit=25"
     hx-target="#panel-content" class="page-btn disabled">Prev</a>
  <a hx-get="/api/dashboard?tab=jobs&section=monitor&page=1&limit=25"
     hx-target="#panel-content" class="page-btn">Next</a>
</div>
```

Pagination is section-level (sub-tab switch), not fragment-level. Clicking Next re-renders the full section with updated data.

---

### 3.13 Testing Approach (Final)

**Unit tests** (Builder must create):

1. `test_registry.py` -- PanelRegistry registration, lookup, duplicate handling
2. `test_base_panel.py` -- Utility methods: `status_badge()`, `format_date()`, `format_age()`, `data_table()`, `stat_strip()`, `error_block()`, `empty_block()`
3. `test_dashboard_handler.py` -- Route dispatch: full page, tab switch, sub-tab switch, fragment, action proxy, unknown tab (404), unknown fragment (400)

**Integration tests** (manual, documented):

```bash
# Full page load
curl -s http://localhost:7071/api/dashboard | head -20
# Expect: <!DOCTYPE html>... with Platform tab active

# Tab switch (simulate HTMX)
curl -s -H "HX-Request: true" "http://localhost:7071/api/dashboard?tab=jobs"
# Expect: HTML fragment with tab-bar OOB swap + jobs panel content

# Fragment (simulate auto-refresh)
curl -s -H "HX-Request: true" "http://localhost:7071/api/dashboard?tab=jobs&fragment=jobs-table"
# Expect: HTML table body only

# Direct URL access (bookmark scenario)
curl -s "http://localhost:7071/api/dashboard?tab=jobs&section=tasks"
# Expect: Full HTML shell with Jobs tab, Tasks section active

# Action proxy (approve)
curl -s -X POST -H "HX-Request: true" \
  -d "release_id=test&reviewer=test&clearance=OUO" \
  "http://localhost:7071/api/dashboard?action=approve"
# Expect: HTML row fragment (or error block if release not found)
```

**Test location**: `tests/test_web_dashboard/` mirroring the module structure.

---

### 3.14 Panel Section Details (Builder Reference)

#### Platform Panel (`platform.py`)

| Section Key | Label | Default | API Endpoint(s) | Auto-Refresh |
|------------|-------|---------|-----------------|--------------|
| `requests` | Requests | YES | `GET /api/platform/status` | No |
| `approvals` | Approvals | No | `GET /api/platform/approvals` | No |
| `submit` | Submit | No | (form only, no GET data) | No |
| `catalog` | Catalog | No | `GET /api/platform/catalog/*` | No |
| `lineage` | Lineage | No | `GET /api/platform/lineage/{id}` | No |
| `failures` | Failures | No | `GET /api/platform/failures` | No |

Fragments: `requests-table`, `approval-detail`, `catalog-results`, `lineage-graph`

#### Jobs Panel (`jobs.py`)

| Section Key | Label | Default | API Endpoint(s) | Auto-Refresh |
|------------|-------|---------|-----------------|--------------|
| `monitor` | Monitor | YES | `GET /api/dbadmin/jobs` | 10s |
| `tasks` | Tasks | No | `GET /api/dbadmin/tasks/{job_id}` | No |
| `pipeline` | Pipeline | No | `GET /api/jobs/status/{job_id}` | No |
| `failures` | Failures | No | `GET /api/platform/failures` | No |

Fragments: `jobs-table` (auto-refresh), `job-detail`

#### Data Panel (`data.py`)

| Section Key | Label | Default | API Endpoint(s) | Auto-Refresh |
|------------|-------|---------|-----------------|--------------|
| `assets` | Assets | YES | `GET /api/platform/catalog/dataset/{id}` | No |
| `stac` | STAC | No | `GET /api/stac/collections` | No |
| `vector` | Vector | No | `GET /api/features/collections` | No |
| `storage` | Storage | No | (deferred -- placeholder) | No |

Fragments: `asset-list`, `collections-list`, `items-list`, `vector-collections-list`

#### System Panel (`system.py`)

| Section Key | Label | Default | API Endpoint(s) | Auto-Refresh |
|------------|-------|---------|-----------------|--------------|
| `health` | Health | YES | `/health`, `/system-health`, `/api/platform/health`, `/api/dbadmin/health`, `/api/stac/health` | 30s |
| `database` | Database | No | `GET /api/dbadmin/diagnostics`, `GET /api/dbadmin/activity`, `GET /api/dbadmin/schemas` | No |
| `queues` | Queues | No | (internal queue stats) | No |
| `maintenance` | Maintenance | No | (action forms only) | No |

Fragments: `health-cards` (auto-refresh), `db-stats`, `db-activity`

---

### 3.15 Dashboard Shell Structure

The `DashboardShell` class in `shell.py` renders the persistent chrome:

```
+----------------------------------------------------------------+
| GeoAPI Platform                                    v0.9.10.1   |  <- header
+----------------------------------------------------------------+
| [Platform]  [Jobs]  [Data]  [System]                           |  <- tab bar
|  -------- loading bar (htmx-indicator) --------                |
+----------------------------------------------------------------+
|                                                                |
|  #main-content                                                 |
|  +------------------------------------------------------------+
|  | [Requests] [Approvals] [Submit] [Catalog] [Lineage] [Fail] |  <- sub-tabs
|  +------------------------------------------------------------+
|  | #panel-content                                              |
|  |                                                             |
|  |  (section content rendered by panel)                        |
|  |                                                             |
|  +------------------------------------------------------------+
|                                                                |
+----------------------------------------------------------------+
| DB: OK | Jobs: 3 active | Last refresh: 14:30 ET | v0.9.10.1 |  <- status bar
+----------------------------------------------------------------+
```

**Tab bar**: Horizontal strip. Active tab has `border-bottom: 3px solid var(--ds-blue-primary)`. Inactive tabs have no bottom border. Tab links use `hx-get` with `hx-push-url="true"`.

**Loading bar**: A thin bar (`height: 3px`) below the tab bar, hidden by default, shown when any HTMX request is in flight (via `htmx-indicator` class).

**Status bar**: Dark background (`--ds-status-bar-bg`), persists across all tab switches. Shows:
- Database connection status (from last health check)
- Active job count
- Last auto-refresh timestamp
- App version

The status bar is NOT auto-refreshed independently. It updates as a side effect of panel data (when the system health fragment refreshes, it can update the status bar via OOB swap).

---

### 3.16 `call_api()` Base URL Resolution

The `call_api()` method on BasePanel makes HTTP requests to the same Function App's API endpoints. The base URL must resolve correctly in all environments:

| Environment | Base URL |
|-------------|----------|
| Local dev (`func start`) | `http://localhost:7071` |
| Azure deployment | `https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net` |

The base URL is derived from the incoming request's host header:

```python
def _get_base_url(self, request: func.HttpRequest) -> str:
    """Derive base URL from the incoming request."""
    host = request.headers.get("Host", "localhost:7071")
    scheme = "https" if "azurewebsites.net" in host else "http"
    return f"{scheme}://{host}"
```

The `call_api()` method on BasePanel must accept the request object (or base_url) to resolve this. The panel's `render_section()` and `render_fragment()` receive the request object and must pass it through.

**Updated `call_api()` signature**:

```python
def call_api(
    self,
    request: func.HttpRequest,
    path: str,
    params: Optional[dict] = None,
    method: str = "GET",
    body: Optional[dict] = None,
    timeout: int = 10,
) -> tuple[bool, Any]:
```

The `request` parameter is used solely to derive the base URL. All panels pass their `request` through.

---

## 4. DEFERRED DECISIONS

The following are explicitly OUT OF SCOPE for MVP. They are recorded here so the Builder does not attempt them and so future work can reference them.

### D-1: Authentication and Authorization

No auth on the dashboard or its proxy actions. The underlying API endpoints have no auth today. Adding auth is a platform-wide decision, not a dashboard-specific one. When API-level auth is implemented, the dashboard will inherit it via its `call_api()` proxy pattern.

### D-2: Dark Mode Toggle

The CSS custom property architecture supports a future dark mode toggle. Not implemented in MVP. Extension point documented in Advocate's design (Section 7.6).

### D-3: Keyboard Shortcuts

j/k navigation, Enter to expand, Esc to close. Requires JavaScript event listeners. Not MVP.

### D-4: CSV Export

Export table data as CSV. Requires a new fragment type or a separate download route. Not MVP.

### D-5: Storage Browser (Data Tab)

The Storage sub-tab in the Data panel is a placeholder. Implementing blob storage browsing requires listing Azure Blob containers, which is a new API capability. Not MVP -- show placeholder message.

### D-6: Queue Monitoring (System Tab)

The Queues sub-tab depends on Service Bus management APIs that may not be exposed. Not MVP -- show whatever data is available from existing endpoints, or placeholder.

### D-7: Pending Approval Count Badge in Tab Bar

The Advocate's golden path mentions a "(5)" badge on the Platform tab for pending approvals. This requires an additional API call on every tab bar render (including auto-refresh). Deferred to post-MVP to avoid unnecessary API calls on every page load.

### D-8: Real-Time Event Timeline

The Pipeline sub-tab in Jobs shows stage progress. A real-time event timeline using `/api/jobs/{job_id}/events` is deferred to post-MVP.

### D-9: Mobile Responsive Design

Minimum width: 900px. Below that, no layout adjustments. A single CSS rule:

```css
@media (max-width: 899px) {
    #dashboard-chrome::before {
        content: "Dashboard requires 900px+ width.";
        display: block;
        padding: 1rem;
        background: var(--ds-status-pending-bg);
        color: var(--ds-status-pending-text);
        text-align: center;
    }
}
```

### D-10: Cursor-Based Pagination

Offset-based pagination is used. Cursor-based pagination requires API changes. Deferred.

---

## 5. RISK REGISTER

### Risk 1: HTMX Script Inline Size

**Risk**: Inlining the full HTMX 1.9.12 minified source (~14KB) adds 14KB to every full page load.

**Likelihood**: Certain (by design).

**Impact**: LOW. 14KB is acceptable for a single-page-load cost. Fragment responses do not include HTMX. The total initial page size is ~65KB (14KB HTMX + 20KB CSS + 5KB shell + 15KB panel + 10KB JS utilities). This is well under the 100KB target.

**Mitigation**: HTMX is only included on full page loads (no HX-Request header). Tab switches and fragments do not re-deliver it.

---

### Risk 2: `call_api()` Loopback Latency

**Risk**: Panels call their own app's API endpoints via HTTP loopback (`http://localhost:7071/api/...`). On Azure Functions Consumption plan, this creates a second invocation within the same request, consuming an additional function execution slot.

**Likelihood**: HIGH (by design -- this is the intended architecture).

**Impact**: MEDIUM. Each panel render triggers 1-3 API calls. The System Health section triggers 5+ API calls (one per health endpoint). Under load, this doubles the invocation count.

**Mitigation**:
1. API call timeout is 10 seconds (prevents indefinite blocking).
2. System Health section uses `loading_placeholder()` for deferred loading -- the initial render returns quickly and the health cards load via HTMX `hx-trigger="load"`.
3. If loopback performance is unacceptable, a future optimization can import service functions directly (breaking the current architecture but improving performance). This is explicitly NOT done in MVP to keep the dashboard decoupled from the service layer.

---

### Risk 3: Dashboard Import Takes Down Function App

**Risk**: A bug in `web_dashboard/` causes an import error. If `function_app.py` imports `dashboard_handler` at module level, the entire Function App fails to start.

**Likelihood**: MEDIUM (during active development, import errors are common).

**Impact**: CRITICAL (entire API is down, not just the dashboard).

**Mitigation**: Wrapped import in `function_app.py` (see Conflict 17 resolution). If import fails, the dashboard route returns 503, but all other API routes function normally.

---

### Risk 4: `.funcignore` Excludes `web_dashboard/`

**Risk**: The `.funcignore` file contains a pattern that excludes the new `web_dashboard/` directory from deployment.

**Likelihood**: MEDIUM (the CLAUDE.md explicitly warns about `*/` pattern).

**Impact**: HIGH (dashboard 404s in production, works locally).

**Mitigation**: Builder must verify `.funcignore` contents before first deployment. Specifically check for `*/` (excludes all subdirectories). Add `!web_dashboard/` if needed.

---

### Risk 5: Form-Encoded Data Parsing in Action Proxy

**Risk**: The dashboard action proxy receives form-encoded data from HTMX `hx-post`. Azure Functions `HttpRequest` exposes form data differently than JSON body. The Builder must correctly parse `req.form` or `req.get_body()` as form-encoded, not as JSON.

**Likelihood**: MEDIUM (common mistake in Azure Functions development).

**Impact**: MEDIUM (approve/reject/submit actions fail).

**Mitigation**: The action handler must use:
```python
from urllib.parse import parse_qs
body = parse_qs(req.get_body().decode("utf-8"))
# body is dict of lists: {"release_id": ["rel-abc"], "reviewer": ["operator"]}
# Extract single values:
release_id = body.get("release_id", [None])[0]
```

Do NOT use `req.get_json()` for HTMX POST requests -- they send form-encoded, not JSON.

---

### Risk 6: OOB Tab Bar Swap Creates Duplicate Elements

**Risk**: If the `render_fragment()` method returns a `<nav id="tab-bar" hx-swap-oob="true">` element AND the HTMX target swap also contains a `#tab-bar`, there will be duplicate elements in the DOM.

**Likelihood**: LOW (if implemented correctly per spec).

**Impact**: MEDIUM (broken tab navigation).

**Mitigation**: The OOB tab bar swap replaces the existing `#tab-bar` element. The primary swap target (`#main-content`) must NOT contain any element with `id="tab-bar"`. Panels must never render a `#tab-bar` element.

---

### Risk 7: Sub-Tab Switch vs Full Page Load URL Ambiguity

**Risk**: The URL `/api/dashboard?tab=platform&section=approvals` is used for both sub-tab HTMX switches (with HX-Request header) and direct URL access (without HX-Request). The handler must return different content for the same URL depending on headers.

**Likelihood**: Certain (by design).

**Impact**: LOW if handled correctly, HIGH if not (users see raw fragments instead of full pages).

**Mitigation**: The dispatch logic in `dashboard_handler` strictly follows the detection hierarchy:
1. `fragment` param present -> fragment response
2. `is_htmx` and `section` -> section content only (for `#panel-content` swap)
3. `is_htmx` and no `section` -> tab switch (panel + OOB tab bar)
4. Not HTMX -> full page (shell + panel)

For case 4 with `section` param present: render full page with that section active. The section param is passed to `panel.render()` which uses it to select the active sub-tab.

---

### Risk 8: Auto-Refresh After Tab Switch

**Risk**: User is on Jobs Monitor (auto-refresh active, every 10s). User switches to Platform tab. The old auto-refresh div is removed from DOM. 10 seconds later, HTMX does NOT fire (element gone). User switches back to Jobs. A NEW auto-refresh div is created. But: if the switch back happened 8 seconds after the element was created, the first refresh fires in 2 seconds, then every 10 seconds. The interval resets per element creation, not per tab session.

**Likelihood**: Certain (HTMX behavior).

**Impact**: LOW (timing offset is acceptable -- the data still refreshes correctly).

**Mitigation**: None needed. The behavior is correct. The 10-second interval is approximate, not precise.

---

*Mediator resolution complete. This document is the single source of truth for the Builder (Agent B). Any ambiguity not resolved here must be escalated back to the Mediator before implementation.*
