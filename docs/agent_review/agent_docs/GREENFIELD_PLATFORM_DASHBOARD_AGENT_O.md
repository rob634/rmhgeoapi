# GREENFIELD: Platform Dashboard — Agent O (Operator) Assessment

**Date**: 01 MAR 2026
**Pipeline**: GREENFIELD (7-agent: S → A+C+O → M → B → V)
**Agent**: O — Operator (Deployment, Failure Modes, Observability, Scaling)
**Spec**: `docs/agent_review/agent_docs/GREENFIELD_PLATFORM_DASHBOARD.md`
**Status**: ASSESSMENT COMPLETE

---

## Executive Summary

The Platform Dashboard design is operationally sound in its core pattern (SSR Python + HTMX on Azure Functions) but carries four material operational risks that must be addressed before or during the Builder phase:

1. **HTMX CDN dependency is a single point of total UI failure** — one blocked CDN call renders the dashboard unusable.
2. **Auto-refresh invocation multiplication** — 10s polling from every open browser tab is not free on Consumption plan and will compound with System Health panel calls.
3. **Panel exception isolation is unspecified** — a broken panel must not take down the entire dashboard shell.
4. **`/api/dashboard` registration requires explicit function_app.py edit** — unlike the `/api/interface/{name}` pattern, the dashboard has no auto-discovery path.

All four are fixable in the Builder phase with clear mitigations documented below.

---

## 1. INFRASTRUCTURE FIT

### How Well This Fits Azure Functions (Python, Consumption Plan)

**Assessment: GOOD FIT with known constraints.**

The design explicitly targets this runtime and avoids the worst pitfalls. The pattern of returning HTML strings from Python is identical to what `web_interfaces/` already does successfully with 37 interfaces. The operational concerns below are incremental, not fundamental.

### Cold Start Impact on Dashboard Loads

**Severity: MEDIUM. Manageable, not critical.**

Cold starts on Azure Functions Python (Consumption plan) currently run 3–8 seconds. The dashboard shell imports `web_dashboard/__init__.py`, `shell.py`, `base_panel.py`, and all four panel modules on first invocation. This import chain will:

- Import the panel registry and all panel classes
- NOT import the existing `web_interfaces/` tree (panels call API endpoints rather than importing services directly)
- NOT touch database connections at import time (connections happen in panel `render()`)

**Estimated cold start penalty**: +200–400ms above baseline. Acceptable.

The critical mitigation is that the spec correctly states the design intention: panels call the existing API endpoints over HTTP (loopback), not by importing Python service objects directly. This is the right call — it prevents the dashboard module from dragging in the full service layer dependency tree and inflating cold start time.

**Risk**: If any panel imports a heavy service module at class definition time rather than inside `render()`, cold start time will spike. Builder must enforce: no top-level service imports in panel files.

### Memory Footprint of the Dashboard Module

**Assessment: LOW RISK.**

The `web_dashboard/` tree (shell + 4 panels + registry + base class) will be pure Python with string templates. Estimating ~500 KB in-process memory for the module, which is trivial compared to the existing `web_interfaces/` tree at ~3,000 lines in `base.py` alone. No numpy, no GDAL, no database drivers loaded by the dashboard module itself.

### Concurrent Request Handling

**Assessment: HANDLED BY AZURE FUNCTIONS.**

Each HTTP trigger invocation in Azure Functions is stateless and independently executed. The `PanelRegistry._panels` dict is a class-level singleton populated at import time (decorator pattern), which means it is read-only during request handling — safe under concurrent access with no locks needed.

The only shared mutable state risk is if panels accumulate state on the class or module level between requests. Builder must enforce: panels are stateless. All state lives in the HTTP request and in the API responses.

### Response Size Limits

**Assessment: NO RISK.**

Azure Functions HTTP responses have a practical limit of ~100MB. The spec targets < 100KB per panel render. The full dashboard shell (CSS + tabs + one panel) will be approximately:
- Inline CSS: ~15–25KB (based on `base.py` COMMON_CSS which is already ~3,000 lines for 37 interfaces; the consolidated shell CSS will be smaller)
- HTMX script tag: 14KB (HTMX 1.9.x minified from CDN, loaded by browser, not in response body)
- Shell HTML: ~3–5KB
- Panel content: ~5–20KB depending on table row count

Total initial load: **~25–50KB uncompressed**. Azure Functions gzip compression is not automatic on Consumption plan for custom routes — this is worth noting. At these sizes it does not matter.

Fragment responses (auto-refresh tbody rows): < 5KB. Fine.

### Request Timeout Limits (230s for Azure Functions)

**Assessment: NO RISK for UI rendering itself. LATENT RISK for System tab.**

Dashboard panel render time is dominated by the internal HTTP calls each panel makes to the existing API endpoints. For Platform/Jobs panels, individual API calls (jobs list, request list) return in < 2 seconds under normal conditions. Well within the 230s limit.

**Exception**: The System tab calls multiple health-check endpoints including `/api/dbadmin/diagnostics` (which does DB round-trips) and `/api/system-health` (which fans out to all three apps). If the System tab renders all panels in sequence and any single downstream call hangs, the cumulative timeout could approach 30–60 seconds. The fix is panel-level `asyncio` timeouts on internal HTTP calls.

**Recommendation**: Builder must add per-API-call timeouts of 10–15 seconds inside all panel `render()` methods. Do not rely on the 230s function timeout as a safety net.

### Impact on Existing Function App Performance

**Assessment: LOW. Additive load only.**

The dashboard adds one new HTTP route (`/api/dashboard`). On the Consumption plan, each invocation gets its own process slot. The dashboard does not share resources with existing API invocations beyond the database connection pool (addressed under Failure Modes below).

The one systemic impact is that **auto-refresh polling increases total invocation count on the Function App**. See Scaling section for the math.

---

## 2. DEPLOYMENT REQUIREMENTS

### New Route Registration in function_app.py

**This is required. It cannot be auto-discovered.**

The existing `web_interfaces/` system works via auto-discovery because all interfaces share the single route `interface/{name}` — the `{name}` wildcard does the work. The dashboard spec defines its own top-level route `/api/dashboard`.

This means `function_app.py` must be modified to add the new route. The pattern, following what exists at line 848, is:

```python
# ============================================================================
# PLATFORM DASHBOARD (GREENFIELD - REPLACE WITH DATE)
# ============================================================================

from web_dashboard import dashboard_handler

@app.route(route="dashboard", methods=["GET", "POST"])
def platform_dashboard(req: func.HttpRequest) -> func.HttpResponse:
    """
    Unified Platform Dashboard.

    GET  /api/dashboard               → Full shell with default tab
    GET  /api/dashboard?tab={name}    → Tab switch (HTMX fragment)
    GET  /api/dashboard?tab={name}&section={sub} → Sub-tab (HTMX fragment)
    GET  /api/dashboard?tab={name}&fragment={id} → Auto-refresh fragment
    POST /api/dashboard               → (reserved for future form actions)
    """
    return dashboard_handler(req)
```

**Placement**: Add after the existing web interface block (after line 887), before the OPENAPI SPEC section. This is consistent with the existing structure.

**APP_MODE consideration**: Review whether `/api/dashboard` should be gated by `_app_mode`. The existing `/api/interface/{name}` route has no mode gate, suggesting the UI layer is always available. Recommend no gate on the dashboard route — it is a read-only UI that calls existing gated endpoints; those endpoints will return appropriate errors if unavailable.

### Package Dependencies

The spec mandates zero build step and no npm. The Python runtime dependencies introduced by `web_dashboard/` are:

| Dependency | Status | Notes |
|------------|--------|-------|
| `azure.functions` | Already present | HTTP request/response handling |
| `httpx` or `urllib` | Check requirements.txt | Internal API calls from panels |
| `html` (stdlib) | Already used in web_interfaces | HTML escaping |
| HTMX | **CDN-loaded by browser** | Not a Python package |

**Action for Builder**: Verify `httpx` is already in `requirements.txt`. If internal API calls are made via `urllib.request` (stdlib), no new dependency is needed. If using `httpx` or `aiohttp` (async), verify presence in requirements.

No new Azure Function App settings are needed for the dashboard module itself. The dashboard calls existing endpoints which use the existing configuration.

### Font Loading Strategy

**This is the highest operational risk in the design layer. Recommendation: self-host or use system fonts.**

**Current situation**: `base.py` (line 118) uses `"Open Sans", Arial, sans-serif`. Open Sans is a Google Font. The current interfaces load it via a Google Fonts CDN link (or inline via base64 — needs verification).

**For the dashboard shell, three options:**

| Option | Reliability | Cold Start Impact | Offline Behavior | Recommendation |
|--------|-------------|-------------------|------------------|----------------|
| Google Fonts CDN `<link>` in `<head>` | Depends on CDN | None (browser async) | Falls back to Arial | Acceptable for operator tool |
| Self-hosted in blob storage (static site) | High | None | Full fonts | Best if already serving static assets |
| System font stack only | Maximum | None | Always works | Simplest; fonts look fine |

**Recommendation for Operator**: Use the system font stack as primary with named fonts as enhancement:

```css
font-family: "Inter", "Segoe UI", "Open Sans", system-ui, -apple-system, sans-serif;
```

This loads instantly with no CDN dependency. If Inter is the selected variant (V2 or V3), it can be self-hosted as a WOFF2 in the static blob site. **Do not place font files inside the Function App deployment package** — they add to package size and slow zip-deploy.

If Google Fonts CDN is chosen, the `<link rel="preconnect" href="https://fonts.googleapis.com">` tag must come before HTMX in the `<head>` to avoid render-blocking.

### HTMX Delivery Strategy — CRITICAL FINDING

**The spec says CDN-served HTMX. This is an operational risk that must be addressed.**

If `https://unpkg.com/htmx.org@1.9.x/dist/htmx.min.js` (or any CDN) is unreachable — due to network policy, CDN outage, VNet configuration, or corporate firewall — the dashboard renders a static HTML page with no interactivity. Tab switching stops working. Auto-refresh stops. Every button that uses `hx-post` becomes inert.

This is not hypothetical. Azure Functions on Consumption plan run in multi-tenant infrastructure where outbound CDN requests can be throttled or blocked by network policy.

**Mitigation options (in order of preference):**

1. **Self-host HTMX inside the Function App package**: Add `htmx.min.js` (14KB) to `web_dashboard/static/htmx.min.js` and serve it via a dedicated route or inline it. This is the operationally sound choice. A one-time route to serve a static file adds < 5ms overhead and eliminates the CDN dependency entirely.

2. **Serve from Azure Blob static site**: Upload HTMX to the `rmhazuregeobronze` or a dedicated static hosting container and reference via `https://rmhazuregeo.z13.web.core.windows.net/htmx.min.js`. Reliable, Azure-controlled, no external CDN dependency.

3. **CDN with inline fallback**: Load from CDN, then inline a small `<script>` that checks `if (!window.htmx)` and inlines the full HTMX source as a data URI fallback. Hacky but possible.

**Bottom line**: Builder must not rely on an external CDN for a critical JavaScript dependency. Option 1 (embed in Function App package) is cleanest for a tool this size.

### CSS Delivery

**Assessment: Inline in shell.py is correct.**

The spec's approach of embedding CSS in the shell Python string is the right call for this deployment. No separate CSS file means one fewer HTTP request, no separate serving infrastructure, and no CDN dependency. The existing `base.py` COMMON_CSS already proves this pattern at ~300 lines of CSS. The dashboard shell CSS will be similar in size.

**Concern**: If the consolidated design system CSS grows beyond ~50KB uncompressed, it will add meaningful response size to every `/api/dashboard` request. Keep the CSS budget to < 20KB.

### Interaction with deploy.sh

**Assessment: NO CHANGES NEEDED to deploy.sh.**

`web_dashboard/` is a new Python package directory inside the Function App. It deploys via the existing `func azure functionapp publish rmhazuregeoapi --python --build remote` path. The only requirement is that `web_dashboard/` is not listed in `.funcignore`.

**Critical check**: Verify `.funcignore` does not have `*/` (the project CLAUDE.md flags this as a known pitfall). Adding a new top-level directory `web_dashboard/` will be excluded by `*/` if present.

### New Azure Function App Settings Needed

None. The dashboard is a UI layer that calls existing API endpoints. It inherits all configuration via those API calls.

---

## 3. FAILURE MODES

### Failure Mode 1: Dashboard loads but one or more API endpoints are down

**What happens**: A panel calls `/api/platform/status` and gets a 500 or connection timeout.

**What user sees (spec is silent on this)**: If not handled, the panel's `render()` method throws an exception, which propagates to `dashboard_handler`, which returns HTTP 500 with a generic error page. The entire dashboard is down, not just the affected panel.

**Required behavior**: Each panel must catch API call failures and render an inline error card:

```html
<div class="panel-error">
  Platform status unavailable — API returned 500.
  <button hx-get="/api/dashboard?tab=platform&section=requests" hx-target="#panel-content">
    Retry
  </button>
</div>
```

**Builder requirement**: `BasePanel` must wrap all internal API calls in try/except and return error HTML, never raise. The spec calls for "API errors shown inline with retry affordance" — this must be enforced at the base class level, not left to individual panels.

### Failure Mode 2: HTMX CDN unreachable

**What happens**: Browser loads the dashboard HTML shell. The `<script src="https://unpkg.com/htmx.org...">` fails. HTMX never initializes.

**What user sees**: A fully rendered HTML page with navigation tabs and content areas. Clicking a tab does nothing (the HTMX `hx-get` attributes are inert). The page looks functional but is frozen on the initial view. No error message is shown to the user.

**This is the worst kind of failure: silent and confusing.** The dashboard appears loaded but nothing works.

**Mitigation**: Self-host HTMX (see Deployment section). If CDN is kept, add a `<noscript>` and a JavaScript self-check:

```html
<script>
  window.addEventListener('load', function() {
    if (!window.htmx) {
      document.getElementById('htmx-error').style.display = 'block';
    }
  });
</script>
<div id="htmx-error" style="display:none; background:#fee2e2; padding:1rem; margin:1rem;">
  HTMX failed to load. Dashboard navigation is unavailable.
  Check network access to unpkg.com CDN or contact administrator.
</div>
```

### Failure Mode 3: Database connection pool exhausted

**What happens**: The Function App's PostgreSQL connection pool (shared across all invocations via connection pooling) is saturated. New connections fail with `too many clients`.

**Dashboard contribution**: Each panel that calls a DB-backed API endpoint (`/api/dbadmin/jobs`, `/api/platform/status`, etc.) triggers a DB query on the API endpoint's invocation — not directly from the dashboard. However, auto-refresh at 10s intervals from multiple tabs multiplies the number of such API calls (see Scaling section).

**Manifestation**: The dashboard panels that call DB-backed endpoints will receive 500 or 503 responses and show their inline error cards. This is the correct behavior. The dashboard is a symptom indicator, not the root cause.

**Mitigation**: Auto-refresh fragment requests should be deprioritized. If DB health is critical, the System tab Health panel should show the connection count prominently so operators can identify the cause.

### Failure Mode 4: Panel rendering throws exception

**What happens**: A panel's `render()` or `fragment()` method throws an uncaught Python exception (bug, missing key, malformed API response, etc.).

**What user sees without isolation**: HTTP 500, generic error page, entire dashboard down.

**What user should see with isolation**: The broken panel renders an error card inline. Other tabs continue working.

**Implementation requirement**: `dashboard_handler` in `web_dashboard/__init__.py` must wrap each `panel.render()` call:

```python
try:
    panel_html = panel.render(req)
except Exception as e:
    logger.error(f"Panel render failed: {tab_name}/{section}: {e}", exc_info=True)
    panel_html = _render_panel_error(tab_name, str(e))
```

This is functionally identical to how `unified_interface_handler` in `web_interfaces/__init__.py` (line 235) wraps `interface.render(req)` — except the existing implementation returns HTTP 500 to the user. The dashboard handler should return HTTP 200 with an error card, not HTTP 500, so the shell chrome remains intact.

### Failure Mode 5: Concurrent HTMX requests during rapid tab switching

**What happens**: User clicks Platform → Jobs → System rapidly before HTMX receives the Platform response. HTMX queues requests by default.

**HTMX default behavior**: HTMX 1.9.x queues outgoing requests to the same `hx-target`. If the user clicks three tabs quickly, three requests are queued. They will execute in sequence. The last response will be the final displayed content. This is correct behavior but will produce a visual stutter.

**Race condition risk**: If sub-tab requests use a different target (`#panel-content`) and tab requests use `#main-content`, they can execute concurrently and the sub-tab response may swap content that belongs to a different tab. This is a real risk in the sub-tab pattern.

**Mitigation**: Add `hx-sync="closest body:queue last"` to the main tab bar navigation links. This tells HTMX to cancel in-flight requests when a new tab is clicked:

```html
<a hx-get="/api/dashboard?tab=jobs"
   hx-target="#main-content"
   hx-push-url="true"
   hx-sync="closest body:queue last">Jobs</a>
```

### Failure Mode 6: Azure Function App restarts mid-request

**What happens**: App restarts during a panel render or an HTMX auto-refresh.

**What user sees**: The in-flight request returns a connection error or TCP reset. HTMX receives no response and does nothing by default (no automatic retry). The dashboard shell remains displayed from the previous load. The auto-refresh timer continues and will succeed on the next cycle (10s). For a mid-render restart, the user sees a stale dashboard for up to 10s.

**Assessment**: This is acceptable behavior. No special handling needed beyond the existing auto-refresh mechanism.

---

## 4. OBSERVABILITY

### Application Insights Integration

The dashboard runs on the same Function App as all other endpoints. Application Insights telemetry is already configured via `APPLICATIONINSIGHTS_CONNECTION_STRING`. Dashboard invocations will appear automatically in the dependency/request tables.

**Issue**: By default, all HTTP triggers appear as `web_interface_unified` or the function name in App Insights. Dashboard requests will appear as `platform_dashboard` (the function name in function_app.py). This is sufficient for distinguishing dashboard traffic.

### Distinguishing Dashboard Traffic from API Traffic

Dashboard requests will appear in App Insights as:
- `operation_Name`: `GET /api/dashboard`
- `url`: full URL with query params (`?tab=jobs&fragment=jobs-table`)

The `fragment` and `tab` query parameters are preserved in the URL telemetry automatically.

**Recommended custom telemetry** (optional but valuable): Add structured logging in `dashboard_handler` for each panel render:

```python
logger.info(
    "Dashboard request",
    extra={
        "custom_dimensions": {
            "dashboard_tab": tab,
            "dashboard_section": section,
            "dashboard_fragment": fragment,
            "is_htmx": req.headers.get("HX-Request") == "true",
            "is_autorefresh": fragment is not None
        }
    }
)
```

This lets you write App Insights queries to distinguish:
- Full page loads (cold sessions)
- Tab switches (user navigating)
- Auto-refresh cycles (background polling)

### Log Queries for Dashboard Monitoring

```kusto
// Dashboard traffic breakdown (last hour)
requests
| where timestamp > ago(1h)
| where url contains "/api/dashboard"
| extend tab = extract(@"tab=([^&]+)", 1, url)
| extend fragment = extract(@"fragment=([^&]+)", 1, url)
| extend is_autorefresh = isnotempty(fragment)
| summarize count() by tab, is_autorefresh, bin(timestamp, 5m)

// Dashboard panel errors (last 24h)
traces
| where timestamp > ago(24h)
| where message contains "Panel render failed"
| project timestamp, message, customDimensions
| order by timestamp desc

// Dashboard render latency by tab
requests
| where url contains "/api/dashboard"
| extend tab = extract(@"tab=([^&]+)", 1, url)
| summarize avg_ms = avg(duration), p95_ms = percentile(duration, 95) by tab
```

### Error Tracking for Panel Rendering Failures

Panel errors should be logged with structured data (tab name, section, exception type). The `dashboard_handler` wrapper (see Failure Mode 4) should call `logger.error(..., exc_info=True)` which captures the full stack trace in App Insights exceptions table.

**Alert to create**: Alert on `exceptions | where type contains "PanelRenderError"` with threshold > 0 in a 5-minute window.

### Performance Metrics

Key metrics to track:
- **Dashboard shell render time** (initial load): target < 500ms P95
- **Panel fragment render time** (tab switch): target < 300ms P95
- **Auto-refresh fragment render time**: target < 200ms P95
- **Internal API call latency from panels**: measured by tracing HTTP calls inside panel render

Azure Functions automatically records function duration in App Insights. For panel-level granularity, add timing logs inside `BasePanel.render()`.

### Tracing a User Dashboard Session

Azure Functions assigns a unique `operation_Id` to each HTTP invocation. Because HTMX tab switches are independent HTTP requests, there is no automatic session-level trace grouping.

**Practical approach**: HTMX sends the `HX-Current-URL` header on fragment requests, which contains the browser URL. Log this header to correlate tab switches to an originating session URL. This is not true distributed tracing but is sufficient for debugging.

---

## 5. SCALING BEHAVIOR

### Invocation Math

**Baseline: 1 operator, Jobs tab open with auto-refresh active**

| Event | Invocations per minute |
|-------|----------------------|
| Initial page load | 1 (one-time) |
| Jobs table auto-refresh (10s) | 6 |
| Total (steady state) | 6/min |

**Realistic: 3 operators with dashboards open**

| Scenario | Invocations per minute |
|----------|----------------------|
| 3x Jobs tab auto-refresh | 18 |
| Plus 1 Platform tab (requests section, 10s refresh) | 6 |
| Plus 1 System tab (health section, 10s refresh) | 6 |
| Tab switches (5 per minute per operator) | 15 |
| Total | ~45/min |

**Worst case: 5 operators, all tabs with auto-refresh**

The spec defines auto-refresh on Jobs Monitor (`every 10s`). If the same interval is applied to the Platform Requests section and System Health panel, and each triggers 1–3 downstream API calls:

```
5 operators × 6 refreshes/min × 3 tabs = 90 dashboard invocations/min
Each dashboard invocation triggers ~2 API endpoint invocations (jobs list + stats)
Total: ~270 invocations/min = 4.5 invocations/second
```

**Azure Functions Consumption plan behavior**: The plan scales from 0 to 200 instances. At < 5 invocations/second, the function app stays on 1–2 instances. No scaling pressure from dashboard traffic at this operator headcount.

**DB connection pressure** (more important than invocation count): Each auto-refresh cycle that calls a DB-backed endpoint opens a DB query. At 90 dashboard invocations/min + existing API traffic, total DB queries per minute increases by ~30–50%. On a pooled connection model this is absorbed. If the pool size is tuned tightly for existing traffic, this is the number to watch.

### Impact on Existing API Endpoints

The dashboard calls existing endpoints as a client. From the API endpoint's perspective, dashboard traffic is indistinguishable from external client traffic. A dashboard request to `/api/dbadmin/jobs?limit=25` generates the same invocation as an external caller.

**At 3 operators with Jobs tab open**: `/api/dbadmin/jobs` is called 18 times/min from dashboard auto-refresh. Current usage from external clients is likely < 5 times/min in development. Dashboard traffic will dominate the `dbadmin` endpoints during operations sessions.

**Assessment**: Not a problem in development. In a production scenario with high external API traffic, the dashboard's polling becomes a material contributor. Add `hx-trigger` conditions (e.g., pause auto-refresh when tab is not visible) to mitigate:

```html
<div hx-get="/api/dashboard?tab=jobs&fragment=jobs-table"
     hx-trigger="every 10s [document.visibilityState == 'visible']"
     hx-target="this">
```

This browser API check stops auto-refresh when the tab is backgrounded, cutting invocations by ~70% for typical operator workflows.

### Auto-Refresh Design Constraint

The spec currently specifies auto-refresh only on the Jobs Monitor table. The spec is silent on whether Platform Requests, Approval Queue, and System Health panels also auto-refresh.

**Recommendation**: Auto-refresh should be opt-in per panel, not default. Jobs Monitor justifies auto-refresh (operators watch active jobs). Platform Requests and Approvals do not need it — operators review those manually. System Health should have a slower refresh (30s, not 10s).

---

## 6. OPERATIONAL HANDOFF

### How to Add a New Panel

1. Create `web_dashboard/panels/{panel_name}.py` with the project file header.
2. Define a class extending `BasePanel`.
3. Decorate with `@PanelRegistry.register(tab_name='...', section_name='...')`.
4. Implement `render(req) -> str` and optionally `fragment(req, fragment_name) -> str`.
5. No changes to `function_app.py` or `web_dashboard/__init__.py` — auto-discovery handles registration (mirror the `web_interfaces/` pkgutil pattern).

**Test locally**: `func start` then `curl http://localhost:7071/api/dashboard?tab={name}`.

### How to Modify the Design System

All design system CSS lives in `web_dashboard/shell.py` inside the `_DESIGN_SYSTEM_CSS` string constant. Edit that string. Changes apply to all panels on next deploy.

**Danger zone**: Changing CSS custom property names (e.g., renaming `--ds-blue-primary`) requires updating every reference in every panel HTML template. Use property names that match the existing `web_interfaces/base.py` variable names where possible to reduce divergence.

### How to Debug a Broken Panel

1. **Check App Insights**: Query `exceptions | where operation_Name == "platform_dashboard"`.
2. **Direct URL test**: Hit `GET /api/dashboard?tab={name}` directly (not through browser HTMX). Check raw HTML response for error card content.
3. **Fragment isolation**: Test the broken fragment directly: `GET /api/dashboard?tab=jobs&fragment=jobs-table`. This invokes only the failing fragment render code.
4. **Underlying API test**: If the panel renders an error card, check the API endpoint it calls: `curl /api/dbadmin/jobs?limit=25`. If the underlying API is broken, fix the API, not the panel.
5. **Log streaming**: `az webapp log tail --name rmhazuregeoapi --resource-group rmhazure_rg` for live function output.

### How to Roll Back if Dashboard Breaks

The dashboard is additive — it adds one new route and one new directory. Rolling back:

1. Remove `web_dashboard/` directory from the deployment package.
2. Remove the `@app.route(route="dashboard", ...)` block and `from web_dashboard import dashboard_handler` import from `function_app.py`.
3. Redeploy: `./deploy.sh orchestrator`.
4. The old `/api/interface/*` routes are unaffected and continue working.

**If the dashboard import is failing at startup** (causing import validation to fail and the entire app to 404): comment out the import in `function_app.py` and redeploy. This is why the dashboard handler import must be wrapped in the same conditional/try-except pattern as other blueprints.

**Recommendation**: Wrap the dashboard import in function_app.py:

```python
try:
    from web_dashboard import dashboard_handler as _dashboard_handler
    _dashboard_available = True
except Exception as _dashboard_import_err:
    logger.warning(f"web_dashboard import failed: {_dashboard_import_err}. /api/dashboard will return 503.")
    _dashboard_available = False
```

This prevents a broken dashboard module from taking down the entire Function App at startup.

### Monitoring Alerts to Set Up

| Alert | Condition | Threshold | Severity |
|-------|-----------|-----------|----------|
| Dashboard error rate | `requests | where url contains "/api/dashboard" | where resultCode >= 500` | > 5% of requests in 5min window | HIGH |
| Panel render failure | `exceptions | where operation_Name == "platform_dashboard"` | > 0 in 5min | MEDIUM |
| Dashboard P95 latency | `requests | where url contains "/api/dashboard"` | P95 > 3000ms | MEDIUM |
| Auto-refresh spike | Invocation count on `platform_dashboard` function | > 200/min | LOW (informational) |

---

## 7. COST MODEL

### Azure Function Invocations

Azure Functions Consumption plan pricing: first 1M invocations/month free, then $0.20 per 1M.

**Baseline operator usage** (5 operators, 8h/day, 22 working days/month):

| Event | Count/Month |
|-------|------------|
| Initial page loads | 5 × 22 × 5 sessions/day = 550 |
| Tab switches | 5 × 22 × 8h × 10/h = 8,800 |
| Auto-refresh cycles (Jobs tab only) | 5 × 22 × 4h active × 360/h = 792,000 |
| Downstream API invocations triggered | 792,000 × 2 = 1,584,000 |
| **Total dashboard-related invocations** | **~2.4M** |

**Cost**: (2.4M - 1M free) = 1.4M × $0.20/1M = **$0.28/month**.

This is genuinely negligible. Azure Functions Consumption plan invocation cost is not the right concern here.

### Bandwidth

**Per auto-refresh cycle** (jobs-table fragment): ~3KB HTML
**Per tab switch** (panel fragment): ~15KB HTML
**Per initial load** (full shell + first panel): ~50KB HTML

**Monthly bandwidth** (same 5-operator scenario):
- Auto-refresh: 792,000 × 3KB = 2.38GB
- Tab switches: 8,800 × 15KB = 132MB
- Initial loads: 550 × 50KB = 27.5MB
- **Total**: ~2.5GB/month

Azure Functions Consumption plan outbound data: first 5GB/month free. Dashboard traffic stays well within free tier.

### API Endpoint Load Increase

The more meaningful cost is compute time on DB-backed API calls triggered by the dashboard:

- Each auto-refresh of the Jobs Monitor calls `/api/dbadmin/jobs` → 1 DB query
- At 792,000 auto-refresh cycles/month: 792,000 additional DB queries/month to the jobs table
- At < 5ms per query: ~65 CPU-minutes/month of additional DB load

**Assessment**: This is noise relative to actual ETL pipeline activity. Not a cost concern.

### Summary

The Platform Dashboard adds approximately **$0.30/month** in direct Azure costs at 5-operator scale. The operational costs that actually matter are the ones measured in engineering time: CDN dependency resolution, panel isolation implementation, and the function_app.py registration edit. All are one-time setup costs, not ongoing.

---

## 8. OPEN QUESTIONS — OPERATOR POSITIONS

The spec lists 7 open questions. Operator positions:

**1. Style Variant Selection**: From an operational standpoint, V2 (Dark Operator) introduces WCAG contrast compliance risk on some status badge combinations (dark background with amber text). V1 (Current) is operationally proven — it already ships in 37 interfaces. V3 (Nordic Minimal) is the safest new choice. V4 adds font-loading risk (Source Sans 3 is a Google Font). Operator defers to Advocate/Mediator on aesthetics.

**2. HTMX Version**: Pin to HTMX 1.9.x. HTMX 2.0 changes default behavior for several swap operations and is not yet widely documented with known gotchas. 1.9.12 is the stable production version as of the knowledge cutoff.

**3. Font Loading**: Self-host or system fonts. Do not use Google Fonts CDN for an operator tool. Network policy, VPN, or corporate firewall can block `fonts.googleapis.com`. System font stack is operationally safest.

**4. Tab State Persistence**: URL-only (`hx-push-url="true"`) is the correct choice. Browser back/forward works. No server-side session needed. Zero extra complexity.

**5. Error Handling UX**: Inline error cards with retry buttons (as specified). No toast notifications — toasts auto-dismiss and operators may miss transient errors. No dedicated error panel — too much navigation overhead.

**6. Mobile Breakpoint**: 768px minimum. This is a power-user operator tool. Below 768px, display a "Dashboard is optimized for desktop" message with a link to the existing `/api/interface/home` as fallback.

**7. Pagination Model**: Offset-based for initial implementation (`?page=2&limit=25`). Cursor-based pagination requires API changes that are out of scope for the dashboard spec. The underlying `/api/dbadmin/jobs` endpoint already uses offset-based `limit` parameter.

---

## 9. CRITICAL REQUIREMENTS FOR BUILDER

In priority order:

| # | Requirement | Risk if Skipped |
|---|-------------|-----------------|
| 1 | Self-host HTMX (no external CDN) | Silent total UI failure if CDN unreachable |
| 2 | Wrap dashboard import in try/except in function_app.py | Broken dashboard import takes down entire Function App |
| 3 | BasePanel wraps all API calls in try/except with inline error HTML | One broken API takes down entire dashboard |
| 4 | dashboard_handler wraps panel.render() in try/except | One broken panel takes down entire dashboard |
| 5 | Add `hx-trigger="every 10s [document.visibilityState == 'visible']"` to all auto-refresh | Unnecessary invocations on backgrounded tabs |
| 6 | Per-API-call timeout of 10–15s inside panel render methods | System tab can hang for 230s |
| 7 | Add structured logging for dashboard tab/section/fragment per request | Cannot debug production issues without it |
| 8 | Verify .funcignore does not contain `*/` before deploying | web_dashboard/ silently excluded from deployment |

---

*Agent O assessment complete. Ready for Mediator (Agent M) synthesis.*
