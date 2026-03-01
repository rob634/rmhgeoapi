# GREENFIELD VALIDATOR REPORT - Platform Dashboard
**Agent**: V (Validator)
**Date**: 01 MAR 2026
**Methodology**: Reverse-engineered from code only. No spec consulted.
**Files reviewed**: `web_dashboard/__init__.py`, `registry.py`, `base_panel.py`, `shell.py`, `panels/__init__.py`, `panels/platform.py`, `panels/jobs.py`, `panels/data.py`, `panels/system.py`, `function_app.py` (dashboard block)

---

## INFERRED PURPOSE

This is a **server-side-rendered HTML operational dashboard** for the GeoAPI Platform. It provides a single-page-like experience using **HTMX** for partial page updates without a frontend build step. The dashboard has no JavaScript business logic of its own -- all interactivity is driven by HTMX declarative attributes and server-side HTML fragments.

**Problem it solves**: Operations staff need a unified view of the platform lifecycle -- submissions, approval queues, job monitoring, data catalog, and system health -- without needing to compose raw API calls or query the database directly.

**Who it is for**: Internal operators (data managers, platform administrators, system operators). Not a public-facing consumer UI. The code itself notes "No authentication enforced" which implies trust is inherited from network/infrastructure controls, not application-layer auth.

**Architecture summary**: The dashboard is a single Azure Function route (`/api/dashboard`) that dispatches to one of four response modes: full HTML page, HTMX fragment (tab switch), HTMX section fragment (sub-tab switch), or action proxy (POST to internal APIs). Panels auto-register via a decorator pattern on import. The shell provides the Chrome (header, tab bar, CSS design system, HTMX bootstrap). Each panel provides sections (sub-tabs) and named fragments.

---

## INFERRED CONTRACTS

### Module Contracts

**`PanelRegistry`**
- `@PanelRegistry.register` decorator: registers a panel class by calling `tab_name()` on a temporary instance. Returns the class unchanged.
- `get(name)` -> panel class or None
- `get_ordered()` -> list of `(tab_name, panel_instance)` sorted by `tab_order`
- `list_panels()` -> list of tab name strings
- `get_all()` -> dict copy

**`BasePanel` (ABC)**
- Abstract: `tab_name()`, `tab_label()`, `default_section()`, `sections()`, `render_section(req, section)`, `render_fragment(req, fragment_name)`
- Concrete template: `render(req)` -> `style_block + sub_tab_bar + <div id="panel-content">section_html</div>`
- Concrete utilities: `call_api()`, `status_badge()`, `approval_badge()`, `clearance_badge()`, `data_type_badge()`, `format_date()`, `format_age()`, `truncate_id()`, `data_table()`, `stat_strip()`, `error_block()`, `empty_block()`, `loading_placeholder()`, `sub_tab_bar()`, `pagination_controls()`, `filter_bar()`, `select_filter()`

**`DashboardShell`**
- `render_full_page(active_tab, panel_html, panels)` -> complete HTML document
- `render_fragment(active_tab, panel_html, panels)` -> OOB tab bar + panel HTML (for HTMX tab switch)
- `render_tab_bar(panels, active_tab)` -> `<nav id="tab-bar">` HTML

**`dashboard_handler` (public API)**
- `GET /api/dashboard` -> full page
- `GET /api/dashboard?tab=X` -> full page with tab X active
- `GET /api/dashboard?tab=X&section=Y` + HX-Request -> section swap + OOB sub-tab bar
- `GET /api/dashboard?tab=X&section=Y` (no HX-Request) -> full page with tab X, section Y active
- `GET /api/dashboard?fragment=F&tab=X` -> fragment HTML
- `POST /api/dashboard?action=A` -> action proxy result HTML

### API Contracts Called by Dashboard

| Dashboard call | Actual route | Status |
|---|---|---|
| `GET /api/platform/status` | `platform/status` (GET) | Exists |
| `GET /api/platform/approvals` | `platform/approvals` (GET) | Exists |
| `GET /api/platform/approvals/{id}` | `platform/approvals/{approval_id}` (GET) | Exists |
| `GET /api/platform/catalog/dataset/{id}` | `platform/catalog/dataset/{dataset_id}` (GET) | Exists |
| `GET /api/platform/catalog/lookup` | `platform/catalog/lookup` (GET) | Exists |
| `GET /api/platform/lineage/{id}` | `platform/lineage/{request_id}` (GET) | Exists |
| `GET /api/platform/failures` | `platform/failures` (GET) | Exists |
| `POST /api/platform/approve` | `platform/approve` (POST) | Exists |
| `POST /api/platform/reject` | `platform/reject` (POST) | Exists |
| `POST /api/platform/revoke` | `platform/revoke` (POST) | Exists |
| `POST /api/platform/submit` | `platform/submit` (POST) | Exists |
| `POST /api/platform/validate` | `platform/validate` (POST) | Exists |
| `POST /api/dbadmin/maintenance` | `dbadmin/maintenance` (POST/GET) | Exists |
| `GET /api/dbadmin/jobs` | `dbadmin/jobs` (GET) | Exists |
| `GET /api/dbadmin/jobs/{job_id}` | `dbadmin/jobs/{job_id}` (GET) | Exists |
| `GET /api/dbadmin/tasks/{job_id}` | `dbadmin/tasks/{job_id}` (GET) | Exists |
| `GET /api/jobs/status/{job_id}` | `jobs/status/{job_id}` (GET) | Exists |
| `GET /api/assets/approval-stats` | `assets/approval-stats` (GET) | Exists |
| `GET /api/assets/pending-review` | `assets/pending-review` (GET) | Exists |
| `GET /api/stac/collections` | `stac/collections` (GET) | Exists |
| `GET /api/stac/collections/{id}/items` | `stac/collections/{collection_id}/items` (GET) | Exists |
| `GET /api/features/collections` | `features/collections` (GET) | Exists |
| `GET /api/dbadmin/schemas` | `dbadmin/schemas` (GET) | Exists |
| `GET /api/dbadmin/activity` | `dbadmin/activity` (GET) | Exists |
| `GET /api/dbadmin/health` | `dbadmin/health` (GET) | Exists |
| `GET /api/stac/health` | `stac/health` (GET) | Exists |
| `GET /api/platform/health` | `platform/health` (GET) | Exists |
| `GET /health` | `health` (GET -> /api/health) | **WRONG PATH** |
| `GET /system-health` | `system-health` -> /api/system-health | **WRONG PATH** |

---

## INFERRED INVARIANTS

1. **Dispatch is strictly ordered**: POST+action > fragment > HTMX+section > HTMX (tab) > full page. The order is enforced by sequential if-checks in `dashboard_handler`.

2. **Errors never crash the page**: All render paths wrap panel rendering in try/except and return error blocks. The outer handler catches anything that escapes. Users always get HTML back, never a 500 stack trace.

3. **All user-controlled strings entering HTML output are escaped via `html.escape()`** (with exceptions noted in CONCERNS).

4. **Panel registration is idempotent with a warning**: Duplicate registrations log a warning and overwrite the prior entry. No exception is raised.

5. **`render()` is final (not overridable)**: The `BasePanel.render()` method is marked as the template method. Panels override `render_section()` and `render_fragment()` instead. This enforces the sub-tab bar + panel-content wrapper structure.

6. **The action proxy is an allowlist**: Only the 7 named actions in `_ACTION_ENDPOINTS` can be proxied. Unknown actions return an error block, preventing arbitrary URL redirection (SSRF).

7. **Auto-refresh is visibility-guarded**: Both health (30s) and jobs (10s) auto-refresh use `[document.visibilityState === 'visible']` guard, preventing wasteful background polling.

---

## INFERRED BOUNDARIES

**Owned by this code:**
- HTTP routing and dispatch
- HTML rendering (all templates are Python f-strings; no template engine)
- HTMX protocol (OOB swaps, fragment requests, tab switches)
- The CSS design system (embedded in DashboardShell.DASHBOARD_CSS)
- HTMX bootstrap (inline or CDN fallback)
- Action proxy translation (form-encoded -> JSON API calls)
- Internal loopback API calls (urllib.request to same Function App)

**Delegated to other systems:**
- Authentication/authorization (none enforced; inherited from network layer)
- Data storage (PostGIS, pgSTAC, blob storage -- all via existing API endpoints)
- Business logic for approvals, submissions, jobs (platform API endpoints)
- STAC catalog management (stac endpoints)
- Queue monitoring (deferred D-6, placeholder rendered)
- Storage browsing (deferred D-5, placeholder rendered)

---

## CONCERNS

### CRITICAL

**C-1: Health endpoint paths missing /api/ prefix**
- File: `web_dashboard/panels/system.py`, `_build_health_cards()`, line 101-102
- The SystemPanel checks `('/health', 'Liveness')` and `('/system-health', 'System Health')`
- `call_api(request, '/health')` builds URL `http://host/health`
- Azure Functions routes require the `/api/` prefix (host.json has no custom `routePrefix`)
- Actual working routes are `/api/health` and `/api/system-health`
- Result: both health cards will always show as errors ("Connection error" or "HTTP 404") on both local and deployed environments
- Fix: change to `('/api/health', 'Liveness')` and `('/api/system-health', 'System Health')`

**C-2: Fragment handler does not exist for row click in Requests table**
- File: `web_dashboard/panels/platform.py`, `_render_requests()`, line 166-171
- Each row in the requests table has `hx-get="/api/dashboard?tab=platform&section=requests&fragment=request-detail&request_id=..."` and `hx-target="next .detail-panel"`
- The `render_fragment()` dispatch in `PlatformPanel` registers: `requests-table`, `approval-detail`, `catalog-results`, `lineage-graph`
- There is NO handler for `request-detail`
- Additionally, there is no `.detail-panel` element rendered after the requests table, so `hx-target="next .detail-panel"` finds nothing
- Result: clicking any row in the requests table raises `ValueError("Unknown platform fragment: request-detail")`, which is caught and rendered as an error block -- but the error block also goes to a target that doesn't exist, so the user sees nothing and receives no feedback
- This is a completely broken feature: the row click-to-detail functionality in the Platform > Requests section is dead on arrival

---

### HIGH

**H-1: Query parameter injection in action proxy URL construction**
- File: `web_dashboard/__init__.py`, `_handle_action()`, line 358-360
- For `ensure` and `rebuild` actions, the URL is constructed as:
  ```python
  api_path_with_params = api_path + "?" + "&".join(f"{k}={v}" for k, v in query_params.items())
  ```
- The `target` value comes from user-submitted form data (`body.get("target", "")`) and is injected into the query string WITHOUT URL encoding
- A malicious form submission with `target=app%26confirm%3Dno%26action%3Drebuild` (or via a browser form manipulation) could inject additional query parameters
- Example: `target=app&other_param=injected` produces `?action=rebuild&confirm=yes&target=app&other_param=injected`
- While `other_param` is probably ignored by the maintenance endpoint, the `confirm` and `action` params could be overridden: `target=pgstac%26action%3Densure` would change `action` to `ensure` after the initial value (last-write-wins behavior depends on the endpoint's parameter parsing)
- Fix: use `urllib.parse.urlencode(query_params)` to properly encode all values

**H-2: stat_strip injects CSS class from API-controlled data without escaping**
- File: `web_dashboard/base_panel.py`, `stat_strip()`, line 387
- `css_class = f"stat-{label.lower().replace(' ', '-')}"` is written directly into the `class` attribute without `html.escape()`
- `label` comes from dict keys passed by callers, which come from API response data (e.g., `approval_state`, `status` enum values)
- If the API returns an unexpected enum value containing `<`, `>`, or `"`, it creates an XSS vector via class attribute injection
- Example: label `"><script>alert(1)</script>` produces `class="stat-card stat-"><script>alert(1)</script>"`
- In practice, these are PostgreSQL enum values which are constrained, but the code offers no defense-in-depth
- Fix: `css_class = f"stat-{html_module.escape(label.lower().replace(' ', '-'))}"`

**H-3: Filter bar Refresh button does not preserve current filter state**
- File: `web_dashboard/base_panel.py`, `filter_bar()`, lines 570-579
- The Refresh button URL is `f"/api/dashboard?tab={tab}&section={section}"` with no filter params
- Clicking Refresh silently resets all filters to their defaults (e.g., status=All, hours=24h)
- This is compounded by the fact that the `<select>` elements rendered by `select_filter()` have no HTMX trigger attributes, so the only way to apply filter changes is via the Refresh button -- which then resets them
- Result: filters are functionally broken in Platform > Requests, Jobs > Monitor, and both Failures sections. A user who changes the status filter to "Failed" and clicks Refresh gets All statuses back
- Fix: add `hx-get`, `hx-include`, and `hx-trigger="change"` to the `<select>` element in `select_filter()`, or add `hx-include` to the Refresh button to capture current form values

---

### MEDIUM

**M-1: Code duplication of API call infrastructure**
- Files: `web_dashboard/__init__.py` (`_call_api_direct()`), `web_dashboard/base_panel.py` (`call_api()`)
- Both functions implement the same scheme detection logic (`_get_base_url` equivalent), the same error handling structure, and the same urllib.request pattern -- 60+ lines of identical code
- They have inconsistent timeout defaults: `_call_api_direct` uses 15 seconds, `call_api` uses 10 seconds
- If the scheme detection logic needs to change (e.g., to support X-Forwarded-Host), it must be updated in two places
- Fix: `_call_api_direct` should use `BasePanel._get_base_url()` logic (static method extraction) or `_call_api_direct` should instantiate a temporary `BasePanel`-compatible caller

**M-2: HTMX CDN fallback has no Subresource Integrity (SRI) hash**
- File: `web_dashboard/shell.py`, `HTMX_SCRIPT`, line 61-62
- The dynamically created script tag loading `https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js` has no `integrity` attribute
- `s.crossOrigin = 'anonymous'` is set (CORS) but without SRI, the browser will not verify the script content
- If unpkg.com is compromised or the package tampered with, malicious JavaScript would execute in the dashboard
- The dashboard has no `Content-Security-Policy: script-src` restriction to limit this exposure
- The current CSP is only `frame-ancestors *` (allows any iframe embedding -- this seems overly permissive for an ops dashboard)
- Fix: add `s.integrity = 'sha384-...'` with the correct hash for htmx 1.9.12, and restrict `frame-ancestors` to `'self'`

**M-3: PanelRegistry instantiates panels on every request**
- File: `web_dashboard/registry.py`, `get_ordered()`, line 123-129; `web_dashboard/__init__.py`, `_get_panel()`, lines 122-129
- `get_ordered()` instantiates ALL panels (`len(panels)` instantiations) and is called on every full page load and every HTMX tab switch
- `_get_panel()` instantiates the target panel again (1 more instantiation)
- A single full page load instantiates 5 panel objects (4 panels via `get_ordered()` + 1 via `_get_panel()`)
- Currently harmless since BasePanel has no `__init__` overhead, but fragile: if a panel adds a constructor with side effects (DB connection, config lookup), it will fire multiple times per request
- Fix: cache panel instances in the registry or use a factory pattern that separates class lookup from instantiation

**M-4: Double-escaping of row_attrs values in data_table**
- File: `web_dashboard/base_panel.py`, `data_table()`, line 356-358; multiple callers in panel files
- `data_table()` escapes all `row_attrs` values with `html.escape()`:
  `f'{k}="{html_module.escape(str(v))}"'`
- However, callers in `_render_requests` and `_build_jobs_table` already pre-escape the `id` attribute value:
  `"id": f"row-{html_module.escape(str(req_id)[:8])}"`
- This produces double-escaping: `&` in an ID becomes `&amp;` from the caller, then `&amp;amp;` after `data_table` re-escapes it
- In practice, IDs are UUIDs or SHA256 hashes (no HTML special characters), so there is no visible rendering defect, but the code is semantically incorrect
- Fix: either have `data_table()` trust its input (no escaping of attrs) or remove pre-escaping from callers

**M-5: `format_date` silently labels times as "ET" regardless of timezone**
- File: `web_dashboard/base_panel.py`, `format_date()`, line 196
- `dt.strftime("%d %b %Y %H:%M ET").upper()` appends "ET" (Eastern Time) hardcoded
- ISO timestamps from the database are UTC (stored with `+00:00` or `Z` suffix)
- The code does NOT convert to Eastern Time -- it simply labels UTC time as "ET"
- A timestamp of `2026-03-01T15:00:00Z` is rendered as "01 MAR 2026 15:00 ET" but the actual ET time would be "01 MAR 2026 10:00 ET" (UTC-5 in EST) or "01 MAR 2026 11:00 ET" (UTC-4 in EDT)
- Fix: either label as "UTC" or convert using `datetime.astimezone(timezone(timedelta(hours=-5)))` with DST awareness

---

### LOW

**L-1: `hx-vals` JSON breakage risk for non-UUID release IDs**
- File: `web_dashboard/panels/platform.py`, `_render_approvals()`, lines 238-265
- Action buttons use `hx-vals='{"release_id": "<safe_rid>", ...}'` where `safe_rid = html_module.escape(str(release_id))`
- A backslash in `release_id` would not be escaped by `html.escape()` (backslash is not an HTML special character), breaking the JSON string in the `hx-vals` attribute
- A double-quote in `release_id` becomes `&quot;` from `html.escape()`, which is then NOT un-escaped by JSON.parse (it parses `&quot;` as a literal 6-character string, corrupting the release_id value sent to the API)
- In practice, release IDs are UUIDs (no backslash or double-quote possible), but the code has no input validation to enforce this assumption
- Fix: use `json.dumps({"release_id": str(release_id), ...})` to produce a properly JSON-serialized `hx-vals` string, then HTML-escape the whole JSON string as the attribute value

**L-2: Row attribute keys are not escaped in data_table**
- File: `web_dashboard/base_panel.py`, `data_table()`, line 356-361
- `f'{k}="{html_module.escape(str(v))}"'` -- the key `k` is not escaped
- All current callers pass hardcoded string keys (`"id"`, `"class"`, `"hx-get"`, `"hx-target"`, `"hx-swap"`, `"hx-push-url"`, `"hx-disabled-elt"`), so no current risk
- If a future caller passes a dynamic key, XSS is possible
- Fix: add `html_module.escape(str(k))` for completeness

**L-3: `select_filter` has no HTMX trigger for live filtering**
- File: `web_dashboard/base_panel.py`, `select_filter()`, lines 600-614
- The `<select>` element has no `hx-get`, `hx-trigger`, or `hx-include` attributes
- Users must click the Refresh button in `filter_bar()` to apply a filter selection
- This is compounded by bug H-3 (Refresh button resets filters)
- The result is that filters are entirely decorative from a UX standpoint
- This is a design gap, not a code bug per se (the omission appears to be intentional scaffolding)
- Fix: add HTMX trigger attributes to `select_filter`, or document that filters require form submission

**L-4: The `_render_storage` and `_render_queues` placeholder sections have no auto-enable path**
- Files: `web_dashboard/panels/data.py` (storage), `web_dashboard/panels/system.py` (queues)
- Both sections render a static "not yet available" message referencing future stories (D-5, D-6)
- They are registered in `sections()` and appear in the sub-tab bar, creating user confusion (tabs that go nowhere)
- There is no `is_enabled` flag or conditional registration to hide them until implemented
- Fix: either hide these sections from `sections()` until implemented, or add a `coming_soon_block()` utility that is more clearly provisional

**L-5: Maintenance rebuild form includes `hx-vals='{"confirm": "yes"}'` alongside `hx-include="#rebuild-target"`**
- File: `web_dashboard/panels/system.py`, `_render_maintenance()`, lines 331-339
- HTMX merges `hx-vals` with the included form data. Both `confirm=yes` (from `hx-vals`) and whatever `#rebuild-target` contains will be sent
- The `confirm` value from `hx-vals` is redundant (the action proxy hardcodes `confirm=yes` for `rebuild`/`ensure` actions anyway)
- But more importantly: `hx-vals` values override `hx-include` values when keys conflict in some HTMX versions
- If `#rebuild-target` ever includes a `confirm` input, the `hx-vals` would shadow it
- This is low-risk but reflects an inconsistent understanding of the HTMX data merging order
- Fix: remove the `hx-vals='{"confirm": "yes"}'` from the rebuild button since `_handle_action` handles `confirm` in the query string construction, and `hx-vals` data flows into the form body, not the action query params

**L-6: `int(request.params.get("limit", "25"))` is unguarded**
- Files: `panels/platform.py` line 95, `panels/jobs.py` line 87, `panels/data.py` line 214
- `int(request.params.get("limit", "25"))` will raise `ValueError` if `limit=abc` is passed
- Same for `page` on the same lines
- The outer try/except in `dashboard_handler` catches this, returning an error block instead of a panel, but the error message exposes the internal exception text
- Fix: wrap with `try/except ValueError` and fall back to the default, or use a utility function like `_safe_int(val, default)`

---

## QUALITY ASSESSMENT

### Grade: B-

**Strengths:**

1. **The overall architecture is sound.** The dispatch hierarchy (full page / HTMX tab / HTMX section / fragment / action proxy) is well-defined and consistently implemented. A developer reading the handler for the first time can understand all code paths within a minute.

2. **Error handling is genuinely robust.** Every panel render path has try/except. The outer handler catches everything. Error states always return usable HTML, not 500s. The error block is consistently used across all panels.

3. **HTML escaping is applied correctly in the vast majority of places.** The builder understood that Python f-strings require explicit escaping and applied `html.escape()` consistently on user-visible data fields. There is no wholesale XSS vulnerability.

4. **The HTMX OOB swap pattern is implemented correctly.** The sub-tab bar update on section switch and the tab bar update on tab switch are both correct HTMX OOB patterns. The visibility-guarded auto-refresh is good operational UX.

5. **The action proxy allowlist prevents SSRF.** The `_ACTION_ENDPOINTS` dict is a proper allowlist; unknown actions are rejected before any HTTP call is made.

6. **Panel auto-discovery via `pkgutil.iter_modules` + import is clean.** Adding a new panel requires only creating the file; no manual registration needed.

7. **The CSS design system is comprehensive.** The embedded `DASHBOARD_CSS` covers all necessary component states and is self-contained.

**Weaknesses justifying the grade:**

- **Two functional features are broken before the first commit** (C-1: health cards always error; C-2: request row click completely non-functional). These are not edge cases -- they are primary dashboard features that will fail on first use.

- **The filter mechanism is architecturally broken** (H-3 + L-3). The combination of no HTMX trigger on selects and a Refresh button that resets state means filters cannot be applied. This is a core interaction pattern of the dashboard.

- **A URL injection vulnerability exists** in the action proxy (H-1). It is behind authentication-free endpoints that can trigger destructive operations (schema rebuild).

- **The codebase would score higher** if the three issues above were fixed. The code quality of the non-broken parts (base_panel utilities, registry, shell, data/stac/vector sections) is solid B+ work.

---

## END-TO-END REQUEST TRACE

**Scenario**: User navigates to `/api/dashboard` for the first time.

1. `function_app.py:platform_dashboard(req)` is called
2. `_dashboard_available` is True (import succeeded at startup)
3. `dashboard_handler(req)` is called
4. `is_htmx = False` (no HX-Request header on initial load)
5. `tab = "platform"` (default), `section = ""`, `fragment = ""`, `action = ""`
6. Dispatch falls through to `_handle_full_page(req, "platform")`
7. `panels = PanelRegistry.get_ordered()` -> returns 4 `(name, instance)` tuples in order `[platform, jobs, data, system]` (by `tab_order`)
8. `panel = _get_panel("platform")` -> instantiates `PlatformPanel()`
9. `panel_html = panel.render(req)`:
   - section = `""` -> defaults to `"requests"`
   - `sub_tab_bar(...)` generates `<nav id="sub-tabs">` with 6 links
   - `render_section(req, "requests")` -> `_render_requests(req)`:
     - Calls `call_api(req, "/api/platform/status", params={"limit": "25", "hours": "24"})`
     - On success: builds filter bar + table + pagination
     - On failure: returns filter bar + error block
   - Returns `style_block + nav#sub-tabs + <div id="panel-content">...</div>`
10. `_shell.render_full_page("platform", panel_html, panels)`:
    - Renders full HTML document with CSS, HTMX script, tab bar, panel content, footer
11. Returns HTTP 200 with `Content-Security-Policy: frame-ancestors *`

**Scenario**: User clicks the "Jobs" tab.

1. Browser sends `GET /api/dashboard?tab=jobs` with `HX-Request: true`
2. `is_htmx = True`, `tab = "jobs"`, no section/fragment/action
3. Dispatch: `_handle_tab_switch(req, "jobs")`
4. `panels = PanelRegistry.get_ordered()` (4 instances)
5. `panel = _get_panel("jobs")` -> `JobsPanel()` instance
6. `panel.render(req)` -> renders Monitor section (default)
7. `_shell.render_fragment("jobs", panel_html, panels)`:
   - Builds new tab bar with "jobs" active
   - Adds `hx-swap-oob="true"` to `nav#tab-bar`
   - Returns `oob_tab_bar + panel_html`
8. HTMX client receives response:
   - Swaps `innerHTML` of `#main-content` with `panel_html` (sub-tab bar + monitor section)
   - OOB-swaps `nav#tab-bar` to update active state
9. Browser URL updated to `/api/dashboard?tab=jobs` (hx-push-url)

This trace works correctly end-to-end.
