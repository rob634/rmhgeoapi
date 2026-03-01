# ============================================================================
# CLAUDE CONTEXT - BASE_PANEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Abstract base - Dashboard panel contract and shared utilities
# PURPOSE: Define the abstract interface and utility methods for all panels
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: BasePanel
# DEPENDENCIES: azure.functions, urllib.request, json, html
# ============================================================================
"""
Abstract base class for dashboard panels.

Provides the panel contract (tab_name, sections, render_section, render_fragment)
and shared utility methods (status_badge, call_api, data_table, etc.).

Exports:
    BasePanel: Abstract base class for all dashboard panels
"""

from abc import ABC, abstractmethod
from typing import Optional, Any
from datetime import datetime, timezone
import azure.functions as func
import html as html_module
import json
import logging
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)


class BasePanel(ABC):
    """
    Abstract base for all dashboard panels.

    Subclasses must implement:
        - tab_name() -> str
        - tab_label() -> str
        - tab_order -> int (class attribute)
        - default_section() -> str
        - sections() -> list[tuple[str, str]]
        - render_section(request, section) -> str
        - render_fragment(request, fragment_name) -> str

    Provides concrete methods:
        - render(request) -> str (template method -- do NOT override)
        - status_badge, approval_badge, clearance_badge, data_type_badge
        - format_date, format_age, truncate_id
        - call_api (HTTP client with error handling)
        - data_table, stat_strip, pagination_controls
        - error_block, empty_block, loading_placeholder
        - sub_tab_bar
    """

    tab_order: int = 99  # Override in subclasses for ordering

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
    def sections(self) -> list:
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

    # --- Concrete template method (do NOT override) ---

    def render(self, request: func.HttpRequest) -> str:
        """
        Render the full panel content (sub-tab bar + section content).

        Reads section= from request params, falls back to default_section().
        Returns sub_tab_bar + <div id="panel-content">{section_html}</div>.
        """
        section = request.params.get("section", "") or self.default_section()
        valid_sections = dict(self.sections())
        if section not in valid_sections:
            section = self.default_section()
        tab_bar_html = self.sub_tab_bar(self.sections(), section, self.tab_name())
        section_html = self.render_section(request, section)
        panel_css = self.get_panel_css() or ""
        style_block = f"<style>{panel_css}</style>" if panel_css else ""
        return f'{style_block}{tab_bar_html}<div id="panel-content">{section_html}</div>'

    def get_panel_css(self) -> Optional[str]:
        """Override to add panel-specific CSS. Default: None."""
        return None

    # --- Utility methods ---

    def status_badge(self, status: str) -> str:
        """Render a job/request status badge."""
        if not status:
            return '<span class="status-badge status-unknown">--</span>'
        safe = html_module.escape(str(status).lower())
        label = html_module.escape(str(status).upper().replace("_", " "))
        return f'<span class="status-badge status-{safe}">{label}</span>'

    def approval_badge(self, state: str) -> str:
        """Render an approval state badge."""
        if not state:
            return '<span class="approval-badge">--</span>'
        safe = html_module.escape(str(state).lower())
        label = html_module.escape(str(state).upper().replace("_", " "))
        return f'<span class="approval-badge approval-{safe}">{label}</span>'

    def clearance_badge(self, level: str) -> str:
        """Render a clearance level badge."""
        if not level:
            return '<span class="clearance-badge">--</span>'
        safe = html_module.escape(str(level).lower())
        label = html_module.escape(str(level).upper())
        return f'<span class="clearance-badge clearance-{safe}">{label}</span>'

    def data_type_badge(self, data_type: str) -> str:
        """Render a data type badge (raster, vector, zarr)."""
        if not data_type:
            return '<span class="data-type-badge">--</span>'
        safe = html_module.escape(str(data_type).lower())
        label = html_module.escape(str(data_type).upper())
        colors = {
            "raster": ("background: #DBEAFE; color: #1E40AF;"),
            "vector": ("background: #D1FAE5; color: #065F46;"),
            "zarr": ("background: #EDE9FE; color: #5B21B6;"),
        }
        style = colors.get(safe, "background: #F3F4F6; color: #6B7280;")
        return (
            f'<span class="data-type-badge" '
            f'style="{style} padding:0.2rem 0.6rem; border-radius:10px; '
            f'font-size:0.7rem; font-weight:600; text-transform:uppercase; '
            f'letter-spacing:0.025em; display:inline-block;">'
            f'{label}</span>'
        )

    def format_date(self, iso_str: Optional[str], fallback: str = "--") -> str:
        """
        Format an ISO datetime string to military format.

        Returns: 'DD MMM YYYY HH:MM ET' for datetime, 'DD MMM YYYY' for date-only.
        """
        if not iso_str:
            return fallback
        try:
            # Handle various ISO formats
            raw = str(iso_str).replace("Z", "+00:00")
            if "T" in raw:
                # Has time component
                dt = datetime.fromisoformat(raw)
                return dt.strftime("%d %b %Y %H:%M ET").upper()
            else:
                # Date only
                dt = datetime.fromisoformat(raw)
                return dt.strftime("%d %b %Y").upper()
        except (ValueError, TypeError):
            return html_module.escape(str(iso_str))

    def format_age(self, iso_str: Optional[str]) -> str:
        """Format an ISO datetime as a human-readable age (e.g., '3h ago', '2d ago')."""
        if not iso_str:
            return "--"
        try:
            raw = str(iso_str).replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = now - dt
            seconds = int(delta.total_seconds())
            if seconds < 0:
                return "just now"
            if seconds < 60:
                return f"{seconds}s ago"
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes}m ago"
            hours = minutes // 60
            if hours < 24:
                return f"{hours}h ago"
            days = hours // 24
            if days < 30:
                return f"{days}d ago"
            months = days // 30
            return f"{months}mo ago"
        except (ValueError, TypeError):
            return "--"

    def truncate_id(self, full_id: Optional[str], length: int = 8) -> str:
        """Truncate a UUID or long ID for display, with title for hover."""
        if not full_id:
            return "--"
        safe_full = html_module.escape(str(full_id))
        safe_short = html_module.escape(str(full_id)[:length])
        return f'<span class="truncated-id" title="{safe_full}">{safe_short}...</span>'

    def _get_base_url(self, request: func.HttpRequest) -> str:
        """Derive base URL from the incoming request."""
        host = request.headers.get("Host", "localhost:7071")
        if "azurewebsites.net" in host:
            scheme = "https"
        elif host.startswith("localhost") or host.startswith("127.0.0.1"):
            scheme = "http"
        else:
            forwarded = request.headers.get("X-Forwarded-Proto", "").lower()
            scheme = "https" if forwarded == "https" else "http"
        return f"{scheme}://{host}"

    def call_api(
        self,
        request: func.HttpRequest,
        path: str,
        params: Optional[dict] = None,
        method: str = "GET",
        body: Optional[dict] = None,
        timeout: int = 10,
    ) -> tuple:
        """
        Call an internal API endpoint and return (success, data_or_error).

        Uses urllib.request (stdlib) with configurable timeout.
        Returns (True, parsed_json) on success, (False, error_message) on failure.
        Never raises -- all exceptions are caught and returned as error messages.

        Args:
            request: The incoming HTTP request (used to derive base URL).
            path: API path (e.g., '/api/dbadmin/jobs'). Must start with '/'.
            params: Optional query parameters dict.
            method: HTTP method ('GET' or 'POST').
            body: Optional JSON body for POST requests.
            timeout: Request timeout in seconds (default: 10).

        Returns:
            Tuple of (bool, Any): (True, response_data) or (False, error_string).
        """
        base_url = self._get_base_url(request)
        url = f"{base_url}{path}"

        if params:
            qs = urllib.parse.urlencode(params)
            url = f"{url}?{qs}"

        try:
            if method.upper() == "POST" and body is not None:
                data = json.dumps(body).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
            elif method.upper() == "POST":
                req = urllib.request.Request(url, data=b"", method="POST")
            else:
                req = urllib.request.Request(url, method="GET")

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                try:
                    return (True, json.loads(resp_body))
                except json.JSONDecodeError:
                    # Non-JSON response (e.g., plain text health check)
                    return (True, resp_body)

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            msg = f"HTTP {e.code}: {error_body[:200]}" if error_body else f"HTTP {e.code}"
            logger.warning(f"call_api failed: {method} {path} -> {msg}")
            return (False, msg)
        except urllib.error.URLError as e:
            msg = f"Connection error: {e.reason}"
            logger.warning(f"call_api failed: {method} {path} -> {msg}")
            return (False, msg)
        except Exception as e:
            msg = f"Unexpected error: {e}"
            logger.exception(f"call_api failed: {method} {path}")
            return (False, msg)

    def data_table(
        self,
        headers: list,
        rows: list,
        table_id: str = "data-table",
        row_attrs: Optional[list] = None,
    ) -> str:
        """
        Render an HTML data table.

        Args:
            headers: List of column header strings.
            rows: List of row lists (each row is a list of HTML cell content strings).
            table_id: HTML id for the table element.
            row_attrs: Optional list of dicts with extra attributes per row
                       (e.g., [{'id': 'row-abc', 'class': 'clickable'}]).

        Returns:
            Complete <table> HTML string.
        """
        header_cells = "".join(
            f"<th>{html_module.escape(str(h))}</th>" for h in headers
        )
        body_rows = []
        for i, row in enumerate(rows):
            attrs_str = ""
            if row_attrs and i < len(row_attrs):
                attrs = row_attrs[i]
                attrs_str = " ".join(
                    f'{k}="{html_module.escape(str(v))}"'
                    for k, v in attrs.items()
                )
                if attrs_str:
                    attrs_str = " " + attrs_str
            # Row cell content is already HTML (may contain badges, links, etc.)
            cells = "".join(f"<td>{cell}</td>" for cell in row)
            body_rows.append(f"<tr{attrs_str}>{cells}</tr>")

        body_html = "\n".join(body_rows)
        return f"""<table id="{html_module.escape(table_id)}" class="data-table">
<thead><tr>{header_cells}</tr></thead>
<tbody>{body_html}</tbody>
</table>"""

    def stat_strip(self, counts: dict) -> str:
        """
        Render a horizontal strip of stat cards.

        Args:
            counts: Dict of label -> value (e.g., {'Completed': 42, 'Failed': 3}).

        Returns:
            HTML for the stat strip.
        """
        cards = []
        for label, value in counts.items():
            safe_label = html_module.escape(str(label))
            safe_value = html_module.escape(str(value))
            css_class = f"stat-{label.lower().replace(' ', '-')}"
            cards.append(
                f'<div class="stat-card {css_class}">'
                f'<div class="stat-value">{safe_value}</div>'
                f'<div class="stat-label">{safe_label}</div>'
                f'</div>'
            )
        return f'<div class="stat-strip">{"".join(cards)}</div>'

    def error_block(self, message: str, retry_url: Optional[str] = None) -> str:
        """
        Render an error block with optional retry button.

        Args:
            message: Error message to display.
            retry_url: Optional URL for the retry button (hx-get).

        Returns:
            HTML for the error block.
        """
        safe_msg = html_module.escape(str(message))
        retry_html = ""
        if retry_url:
            safe_url = html_module.escape(str(retry_url))
            retry_html = (
                f' <a class="btn btn-sm btn-secondary" '
                f'hx-get="{safe_url}" hx-target="closest .error-block" '
                f'hx-swap="outerHTML">Retry</a>'
            )
        return (
            f'<div class="error-block">'
            f'<span class="error-icon">!</span>'
            f'<span class="error-message">{safe_msg}</span>'
            f'{retry_html}'
            f'</div>'
        )

    def empty_block(self, message: str = "No results found.") -> str:
        """
        Render an empty state block.

        Args:
            message: Message to display in the empty state.

        Returns:
            HTML for the empty block.
        """
        safe_msg = html_module.escape(str(message))
        return (
            f'<div class="empty-state">'
            f'<div class="empty-icon">--</div>'
            f'<p>{safe_msg}</p>'
            f'</div>'
        )

    def loading_placeholder(self, fragment_url: str, target_id: str) -> str:
        """
        Render a loading placeholder that auto-loads content via HTMX.

        Uses hx-trigger="load" to fetch content immediately after the
        placeholder is inserted into the DOM.

        Args:
            fragment_url: URL to fetch the content from.
            target_id: HTML id for the placeholder div.

        Returns:
            HTML for the loading placeholder.
        """
        safe_url = html_module.escape(str(fragment_url))
        safe_id = html_module.escape(str(target_id))
        return (
            f'<div id="{safe_id}" hx-get="{safe_url}" '
            f'hx-trigger="load" hx-swap="outerHTML">'
            f'<div class="loading-state">'
            f'<div class="spinner"></div>'
            f'<p class="spinner-text">Loading...</p>'
            f'</div>'
            f'</div>'
        )

    def sub_tab_bar(
        self,
        sections_list: list,
        active_section: str,
        tab_name: str,
    ) -> str:
        """
        Render the sub-tab navigation bar for a panel.

        Args:
            sections_list: List of (section_key, display_label) tuples.
            active_section: Currently active section key.
            tab_name: Parent tab name (for URL construction).

        Returns:
            HTML <nav> element with sub-tab links.
        """
        links = []
        for key, label in sections_list:
            active_class = "active" if key == active_section else ""
            safe_label = html_module.escape(str(label))
            safe_url = html_module.escape(f"/api/dashboard?tab={tab_name}&section={key}")
            links.append(
                f'<a hx-get="{safe_url}" '
                f'hx-target="#panel-content" '
                f'hx-push-url="true" '
                f'hx-swap="innerHTML" '
                f'class="sub-tab {active_class}">'
                f'{safe_label}'
                f'</a>'
            )
        return f'<nav id="sub-tabs" class="sub-tab-bar">{"".join(links)}</nav>'

    def pagination_controls(
        self,
        tab: str,
        section: str,
        page: int,
        limit: int,
        total: int,
    ) -> str:
        """
        Render pagination controls.

        Args:
            tab: Tab name for URL.
            section: Section name for URL.
            page: Current page number (0-indexed).
            limit: Items per page.
            total: Total items.

        Returns:
            HTML for pagination controls.
        """
        start = page * limit + 1
        end = min((page + 1) * limit, total)
        has_prev = page > 0
        has_next = end < total

        prev_class = "" if has_prev else "disabled"
        next_class = "" if has_next else "disabled"

        prev_url = html_module.escape(
            f"/api/dashboard?tab={tab}&section={section}&page={page - 1}&limit={limit}"
        )
        next_url = html_module.escape(
            f"/api/dashboard?tab={tab}&section={section}&page={page + 1}&limit={limit}"
        )

        prev_link = (
            f'<a hx-get="{prev_url}" hx-target="#panel-content" '
            f'hx-swap="innerHTML" class="page-btn {prev_class}">Prev</a>'
            if has_prev
            else f'<span class="page-btn disabled">Prev</span>'
        )
        next_link = (
            f'<a hx-get="{next_url}" hx-target="#panel-content" '
            f'hx-swap="innerHTML" class="page-btn {next_class}">Next</a>'
            if has_next
            else f'<span class="page-btn disabled">Next</span>'
        )

        return (
            f'<div class="pagination">'
            f'<span class="page-info">Showing {start}-{end} of {total}</span>'
            f'{prev_link}'
            f'{next_link}'
            f'</div>'
        )

    def filter_bar(self, tab: str, section: str, filters: list) -> str:
        """
        Render a filter/toolbar bar for a section.

        Args:
            tab: Tab name.
            section: Section name.
            filters: List of filter HTML strings (selects, inputs, buttons).

        Returns:
            HTML for the filter bar.
        """
        filter_html = "".join(filters)
        refresh_url = html_module.escape(
            f"/api/dashboard?tab={tab}&section={section}"
        )
        return (
            f'<div class="filter-bar">'
            f'{filter_html}'
            f'<button hx-get="{refresh_url}" '
            f'hx-target="#panel-content" hx-swap="innerHTML" '
            f'class="btn btn-sm btn-secondary">Refresh</button>'
            f'</div>'
        )

    def select_filter(
        self,
        name: str,
        label: str,
        options: list,
        selected: str = "",
    ) -> str:
        """
        Render a <select> filter element.

        Args:
            name: Select name attribute.
            label: Display label.
            options: List of (value, display_text) tuples.
            selected: Currently selected value.

        Returns:
            HTML string for the labeled select.
        """
        safe_label = html_module.escape(str(label))
        opts = []
        for val, text in options:
            sel = " selected" if val == selected else ""
            safe_val = html_module.escape(str(val))
            safe_text = html_module.escape(str(text))
            opts.append(f'<option value="{safe_val}"{sel}>{safe_text}</option>')
        opt_html = "".join(opts)
        safe_name = html_module.escape(str(name))
        return (
            f'<label class="filter-label">{safe_label}: '
            f'<select name="{safe_name}" class="filter-select">'
            f'{opt_html}</select></label>'
        )
