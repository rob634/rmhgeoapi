# ============================================================================
# CLAUDE CONTEXT - WEB_DASHBOARD_MODULE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Route handler - Dashboard entry point and dispatch logic
# PURPOSE: Handle /api/dashboard requests with panel auto-discovery and HTMX
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: dashboard_handler
# DEPENDENCIES: azure.functions, web_dashboard.shell, web_dashboard.registry
# ============================================================================
"""
Web dashboard module.

Provides the main HTTP handler for /api/dashboard with:
    - Panel auto-discovery via PanelRegistry
    - Full page vs fragment vs section vs action dispatch
    - HX-Request detection for HTMX partial responses
    - Action proxy (approve, reject, submit, etc.) translating form-encoded
      data to JSON API calls

AUTH: No authentication enforced. Dashboard inherits API-level auth (currently none).

Route registration:
    This module exports dashboard_handler which should be called from
    function_app.py's @app.route(route="dashboard", methods=["GET", "POST"]).

Exports:
    dashboard_handler: The main HTTP handler function
"""

import html as html_module
import json
import logging
from urllib.parse import parse_qs

import azure.functions as func

from web_dashboard.registry import PanelRegistry
from web_dashboard.shell import DashboardShell

# Import panels package to trigger @PanelRegistry.register decorators
import web_dashboard.panels  # noqa: F401

logger = logging.getLogger(__name__)

# Default tab when none specified
DEFAULT_TAB = "platform"

# Shared shell instance
_shell = DashboardShell()


def dashboard_handler(req: func.HttpRequest) -> func.HttpResponse:
    """
    Main dashboard HTTP handler.

    Dispatch hierarchy (strictly ordered):
        1. POST with action= -> action proxy
        2. fragment= present -> fragment response (partial refresh)
        3. HX-Request + section= -> section switch (sub-tab)
        4. HX-Request (no section) -> tab switch (panel + OOB tab bar)
        5. No HX-Request -> full page load

    Args:
        req: Azure Functions HttpRequest

    Returns:
        HttpResponse with HTML content

    Route:
        GET/POST /api/dashboard
    """
    try:
        is_htmx = req.headers.get("HX-Request") == "true"
        tab = req.params.get("tab", "") or DEFAULT_TAB
        section = req.params.get("section", "")
        fragment = req.params.get("fragment", "")
        action = req.params.get("action", "")

        # 1. POST action proxy
        if req.method == "POST" and action:
            return _handle_action(req, action)

        # 2. Fragment request (auto-refresh, detail expansion)
        if fragment:
            return _handle_fragment(req, tab, fragment)

        # 3. HTMX sub-tab switch
        if is_htmx and section:
            return _handle_section(req, tab, section)

        # 4. HTMX tab switch
        if is_htmx:
            return _handle_tab_switch(req, tab)

        # 5. Full page load
        return _handle_full_page(req, tab)

    except Exception as e:
        logger.exception(f"Dashboard handler error: {e}")
        error_html = (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">'
            f'Dashboard error: {html_module.escape(str(e))}'
            f'</span>'
            f'</div>'
        )
        return func.HttpResponse(
            error_html,
            mimetype="text/html",
            status_code=200,
        )


def _get_panels() -> list:
    """Get ordered list of (tab_name, panel_instance) tuples."""
    return PanelRegistry.get_ordered()


def _get_panel(tab: str):
    """Get a panel instance by tab name, falling back to default."""
    panel_class = PanelRegistry.get(tab)
    if panel_class:
        return panel_class()
    # Fall back to default tab
    panel_class = PanelRegistry.get(DEFAULT_TAB)
    if panel_class:
        return panel_class()
    return None


# ---------------------------------------------------------------------------
# Dispatch handlers
# ---------------------------------------------------------------------------

def _handle_full_page(req: func.HttpRequest, tab: str) -> func.HttpResponse:
    """Handle full page load (no HX-Request header)."""
    panels = _get_panels()
    panel = _get_panel(tab)

    if not panel:
        return func.HttpResponse(
            f"Dashboard has no registered panels.",
            status_code=500,
            mimetype="text/plain",
        )

    # If the tab doesn't exist, use default
    valid_tabs = [name for name, _ in panels]
    if tab not in valid_tabs:
        tab = DEFAULT_TAB
        panel = _get_panel(tab)

    try:
        panel_html = panel.render(req)
    except Exception as e:
        logger.exception(f"Error rendering panel '{tab}': {e}")
        panel_html = (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">'
            f'Error rendering {html_module.escape(tab)} panel: '
            f'{html_module.escape(str(e))}'
            f'</span>'
            f'</div>'
        )

    full_html = _shell.render_full_page(tab, panel_html, panels)

    return func.HttpResponse(
        full_html,
        mimetype="text/html",
        status_code=200,
        headers={"Content-Security-Policy": "frame-ancestors *"},
    )


def _handle_tab_switch(req: func.HttpRequest, tab: str) -> func.HttpResponse:
    """Handle HTMX tab switch (return panel content + OOB tab bar)."""
    panels = _get_panels()
    panel = _get_panel(tab)

    if not panel:
        return func.HttpResponse(
            '<div class="error-block"><span class="error-icon">!</span>'
            f'<span class="error-message">Unknown tab: {html_module.escape(tab)}</span></div>',
            mimetype="text/html",
            status_code=200,
        )

    try:
        panel_html = panel.render(req)
    except Exception as e:
        logger.exception(f"Error rendering panel '{tab}': {e}")
        panel_html = (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">'
            f'Error rendering {html_module.escape(tab)} panel: '
            f'{html_module.escape(str(e))}'
            f'</span>'
            f'</div>'
        )

    fragment_html = _shell.render_fragment(tab, panel_html, panels)

    return func.HttpResponse(
        fragment_html,
        mimetype="text/html",
        status_code=200,
    )


def _handle_section(
    req: func.HttpRequest, tab: str, section: str
) -> func.HttpResponse:
    """Handle HTMX sub-tab switch (return section content + OOB sub-tab bar)."""
    panel = _get_panel(tab)
    if not panel:
        return func.HttpResponse(
            '<div class="error-block"><span class="error-icon">!</span>'
            f'<span class="error-message">Unknown tab: {html_module.escape(tab)}</span></div>',
            mimetype="text/html",
            status_code=200,
        )

    valid_sections = dict(panel.sections())
    if section not in valid_sections:
        section = panel.default_section()

    try:
        section_html = panel.render_section(req, section)
    except ValueError as e:
        return func.HttpResponse(
            f'<div class="error-block"><span class="error-icon">!</span>'
            f'<span class="error-message">{html_module.escape(str(e))}</span></div>',
            mimetype="text/html",
            status_code=200,
        )
    except Exception as e:
        logger.exception(f"Error rendering section '{section}' in '{tab}': {e}")
        section_html = (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">'
            f'Error rendering section: {html_module.escape(str(e))}'
            f'</span>'
            f'</div>'
        )

    # Return section content + OOB sub-tab bar update
    sub_tab_bar = panel.sub_tab_bar(panel.sections(), section, panel.tab_name())
    oob_sub_tabs = sub_tab_bar.replace(
        'id="sub-tabs"',
        'id="sub-tabs" hx-swap-oob="true"',
        1,
    )

    return func.HttpResponse(
        f'{oob_sub_tabs}\n{section_html}',
        mimetype="text/html",
        status_code=200,
    )


def _handle_fragment(
    req: func.HttpRequest, tab: str, fragment: str
) -> func.HttpResponse:
    """Handle fragment request (auto-refresh, detail expansion)."""
    panel = _get_panel(tab)
    if not panel:
        return func.HttpResponse(
            f'<div class="error-block"><span class="error-icon">!</span>'
            f'<span class="error-message">Unknown tab: {html_module.escape(tab)}</span></div>',
            mimetype="text/html",
            status_code=200,
        )

    try:
        fragment_html = panel.render_fragment(req, fragment)
    except ValueError as e:
        return func.HttpResponse(
            f'<div class="error-block"><span class="error-icon">!</span>'
            f'<span class="error-message">{html_module.escape(str(e))}</span></div>',
            mimetype="text/html",
            status_code=200,
        )
    except Exception as e:
        logger.exception(f"Error rendering fragment '{fragment}' in '{tab}': {e}")
        fragment_html = (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">'
            f'Error rendering fragment: {html_module.escape(str(e))}'
            f'</span>'
            f'</div>'
        )

    return func.HttpResponse(
        fragment_html,
        mimetype="text/html",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Action proxy
# ---------------------------------------------------------------------------

# Action dispatch table: action name -> (api_path, method, query_params)
_ACTION_ENDPOINTS = {
    "approve": ("/api/platform/approve", "POST"),
    "reject": ("/api/platform/reject", "POST"),
    "revoke": ("/api/platform/revoke", "POST"),
    "submit": ("/api/platform/submit", "POST"),
    "validate": ("/api/platform/validate", "POST"),
    "ensure": ("/api/dbadmin/maintenance", "POST"),
    "rebuild": ("/api/dbadmin/maintenance", "POST"),
}


def _handle_action(req: func.HttpRequest, action: str) -> func.HttpResponse:
    """
    Handle POST action proxy.

    Translates form-encoded data from HTMX into JSON API calls.
    Returns HTML fragment showing the result.
    """
    endpoint_info = _ACTION_ENDPOINTS.get(action)
    if not endpoint_info:
        return func.HttpResponse(
            f'<div class="error-block"><span class="error-icon">!</span>'
            f'<span class="error-message">Unknown action: {html_module.escape(action)}</span></div>',
            mimetype="text/html",
            status_code=200,
        )

    api_path, method = endpoint_info

    # Parse form-encoded body from HTMX
    try:
        raw_body = req.get_body().decode("utf-8")
        form_data = parse_qs(raw_body)
        # Convert list values to single values
        body = {k: v[0] if len(v) == 1 else v for k, v in form_data.items()}
    except Exception as e:
        logger.warning(f"Failed to parse form data for action '{action}': {e}")
        body = {}

    # Special handling for maintenance actions
    if action in ("ensure", "rebuild"):
        query_params = {"action": action, "confirm": "yes"}
        target = body.get("target", "")
        if target:
            query_params["target"] = target
        # Maintenance endpoint uses query params, not body
        api_path_with_params = api_path + "?" + "&".join(
            f"{k}={v}" for k, v in query_params.items()
        )
        result = _call_api_direct(req, api_path_with_params, "POST")
    else:
        result = _call_api_direct(req, api_path, "POST", body=body)

    ok, data = result

    if ok:
        # Success response
        result_detail = ""
        if isinstance(data, dict):
            details = []
            for key, val in list(data.items())[:6]:
                safe_key = html_module.escape(str(key))
                safe_val = html_module.escape(str(val)[:100])
                details.append(f"<strong>{safe_key}:</strong> {safe_val}")
            result_detail = "<br>".join(details)
        else:
            result_detail = html_module.escape(str(data)[:200])

        return func.HttpResponse(
            f'<div class="result-card success">'
            f'<strong>{html_module.escape(action.title())} succeeded</strong>'
            f'<div style="margin-top:8px; font-size:var(--ds-font-size-sm);">'
            f'{result_detail}'
            f'</div>'
            f'</div>',
            mimetype="text/html",
            status_code=200,
        )
    else:
        return func.HttpResponse(
            f'<div class="result-card failure">'
            f'<strong>{html_module.escape(action.title())} failed</strong>'
            f'<div style="margin-top:8px; font-size:var(--ds-font-size-sm);">'
            f'{html_module.escape(str(data)[:300])}'
            f'</div>'
            f'</div>',
            mimetype="text/html",
            status_code=200,
        )


def _call_api_direct(
    req: func.HttpRequest,
    path: str,
    method: str = "GET",
    body: dict = None,
    timeout: int = 15,
) -> tuple:
    """
    Direct API call helper for the action proxy.

    Uses urllib.request (same as BasePanel.call_api but standalone).
    """
    import urllib.request
    import urllib.error
    import urllib.parse

    host = req.headers.get("Host", "localhost:7071")
    if "azurewebsites.net" in host:
        scheme = "https"
    elif host.startswith("localhost") or host.startswith("127.0.0.1"):
        scheme = "http"
    else:
        forwarded = req.headers.get("X-Forwarded-Proto", "").lower()
        scheme = "https" if forwarded == "https" else "http"
    base_url = f"{scheme}://{host}"
    url = f"{base_url}{path}"

    try:
        if method.upper() == "POST" and body:
            data = json.dumps(body).encode("utf-8")
            api_req = urllib.request.Request(
                url,
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        elif method.upper() == "POST":
            api_req = urllib.request.Request(url, data=b"", method="POST")
        else:
            api_req = urllib.request.Request(url, method="GET")

        with urllib.request.urlopen(api_req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            try:
                return (True, json.loads(resp_body))
            except json.JSONDecodeError:
                return (True, resp_body)

    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        msg = f"HTTP {e.code}: {error_body[:200]}" if error_body else f"HTTP {e.code}"
        logger.warning(f"Action API call failed: {method} {path} -> {msg}")
        return (False, msg)
    except urllib.error.URLError as e:
        msg = f"Connection error: {e.reason}"
        logger.warning(f"Action API call failed: {method} {path} -> {msg}")
        return (False, msg)
    except Exception as e:
        msg = f"Unexpected error: {e}"
        logger.exception(f"Action API call failed: {method} {path}")
        return (False, msg)


# Public API
__all__ = ["dashboard_handler"]
