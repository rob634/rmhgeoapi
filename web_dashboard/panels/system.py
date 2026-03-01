# ============================================================================
# CLAUDE CONTEXT - SYSTEM_PANEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Dashboard panel - System health, database, queues, maintenance
# PURPOSE: Tab 4 of the dashboard: system operations and diagnostics
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: SystemPanel
# DEPENDENCIES: azure.functions, web_dashboard.base_panel, web_dashboard.registry
# ============================================================================
"""
System panel for the dashboard.

Provides sub-tabs for:
    - health: System health cards with auto-refresh (30s)
    - database: Database diagnostics and schema stats
    - queues: Queue monitoring (placeholder -- deferred D-6)
    - maintenance: Schema ensure/rebuild actions

Exports:
    SystemPanel: Registered panel class
"""

import html as html_module
import json
import logging
import azure.functions as func

from web_dashboard.base_panel import BasePanel
from web_dashboard.registry import PanelRegistry

logger = logging.getLogger(__name__)


@PanelRegistry.register
class SystemPanel(BasePanel):
    """System operations panel -- health, database, queues, maintenance."""

    tab_order = 4

    def tab_name(self) -> str:
        return "system"

    def tab_label(self) -> str:
        return "System"

    def default_section(self) -> str:
        return "health"

    def sections(self) -> list:
        return [
            ("health", "Health"),
            ("database", "Database"),
            ("queues", "Queues"),
            ("maintenance", "Maintenance"),
        ]

    def render_section(self, request: func.HttpRequest, section: str) -> str:
        dispatch = {
            "health": self._render_health,
            "database": self._render_database,
            "queues": self._render_queues,
            "maintenance": self._render_maintenance,
        }
        handler = dispatch.get(section)
        if not handler:
            raise ValueError(f"Unknown system section: {section}")
        return handler(request)

    def render_fragment(self, request: func.HttpRequest, fragment_name: str) -> str:
        dispatch = {
            "health-cards": self._fragment_health_cards,
            "db-stats": self._fragment_db_stats,
            "db-activity": self._fragment_db_activity,
        }
        handler = dispatch.get(fragment_name)
        if not handler:
            raise ValueError(f"Unknown system fragment: {fragment_name}")
        return handler(request)

    # -----------------------------------------------------------------------
    # HEALTH section (auto-refresh: 30s)
    # -----------------------------------------------------------------------

    def _render_health(self, request: func.HttpRequest) -> str:
        """Render health cards with auto-refresh wrapper."""
        cards = self._build_health_cards(request)

        return f"""<div id="health-refresh-wrapper"
     hx-get="/api/dashboard?tab=system&fragment=health-cards"
     hx-trigger="every 30s [document.visibilityState === 'visible']"
     hx-target="this"
     hx-swap="innerHTML">
{cards}
</div>"""

    def _build_health_cards(self, request: func.HttpRequest) -> str:
        """Build health cards HTML (used by both section and fragment)."""
        # Define health endpoints to check
        endpoints = [
            ("/health", "Liveness"),
            ("/system-health", "System Health"),
            ("/api/platform/health", "Platform"),
            ("/api/dbadmin/health", "Database"),
            ("/api/stac/health", "STAC"),
        ]

        cards = []
        for path, label in endpoints:
            ok, data = self.call_api(request, path, timeout=5)

            if ok:
                status_dot = '<span class="status-dot"></span>'
                status_text = "OK"
                detail_html = ""

                if isinstance(data, dict):
                    status_text = data.get("status", "OK")
                    # Extract interesting details
                    details = []
                    for key in ["version", "environment", "database", "uptime",
                                "connection_pool", "collections", "items"]:
                        if key in data:
                            val = data[key]
                            if isinstance(val, dict):
                                val = json.dumps(val)
                            details.append(
                                f'<span style="font-size:11px; color:var(--ds-gray);">'
                                f'{html_module.escape(key)}: {html_module.escape(str(val)[:50])}'
                                f'</span>'
                            )
                    if details:
                        detail_html = (
                            '<div style="margin-top:8px; display:flex; '
                            'flex-direction:column; gap:2px;">'
                            + "".join(details)
                            + "</div>"
                        )
                elif isinstance(data, str):
                    status_text = data[:50] if data else "OK"
            else:
                status_dot = '<span class="status-dot error"></span>'
                status_text = f"Error: {html_module.escape(str(data)[:60])}"
                detail_html = ""

            safe_label = html_module.escape(label)
            safe_status = html_module.escape(str(status_text))

            cards.append(
                f'<div class="health-card">'
                f'<h4>{status_dot} {safe_label}</h4>'
                f'<div class="health-status">{safe_status}</div>'
                f'{detail_html}'
                f'</div>'
            )

        return f'<div class="health-grid">{"".join(cards)}</div>'

    def _fragment_health_cards(self, request: func.HttpRequest) -> str:
        """Fragment: health cards only (for auto-refresh)."""
        return self._build_health_cards(request)

    # -----------------------------------------------------------------------
    # DATABASE section
    # -----------------------------------------------------------------------

    def _render_database(self, request: func.HttpRequest) -> str:
        """Render database diagnostics."""
        # Schema stats
        schema_html = self.loading_placeholder(
            "/api/dashboard?tab=system&fragment=db-stats",
            "db-stats-container",
        )

        # Active queries
        activity_html = self.loading_placeholder(
            "/api/dashboard?tab=system&fragment=db-activity",
            "db-activity-container",
        )

        return f"""<h3 class="section-heading">Database Diagnostics</h3>
<div style="display:flex; flex-direction:column; gap:20px;">
    <div>
        <h4 style="font-size:var(--ds-font-size); margin-bottom:8px; color:var(--ds-navy);">Schema Statistics</h4>
        {schema_html}
    </div>
    <div>
        <h4 style="font-size:var(--ds-font-size); margin-bottom:8px; color:var(--ds-navy);">Active Queries</h4>
        {activity_html}
    </div>
</div>"""

    def _fragment_db_stats(self, request: func.HttpRequest) -> str:
        """Fragment: database schema stats."""
        ok, data = self.call_api(request, "/api/dbadmin/schemas")

        if not ok:
            return self.error_block(
                f"Database diagnostics unavailable: {data}",
                retry_url="/api/dashboard?tab=system&fragment=db-stats",
            )

        if not data:
            return self.empty_block("Database diagnostics unavailable.")

        # Render schema info
        if isinstance(data, dict):
            schemas = data.get("schemas", data.get("items", []))
            if isinstance(schemas, list) and schemas:
                headers = ["Schema", "Tables", "Indexes", "Size"]
                rows = []
                for s in schemas:
                    rows.append([
                        html_module.escape(str(s.get("schema_name", s.get("name", "--")))),
                        html_module.escape(str(s.get("table_count", s.get("tables", "--")))),
                        html_module.escape(str(s.get("index_count", s.get("indexes", "--")))),
                        html_module.escape(str(s.get("size", s.get("total_size", "--")))),
                    ])
                return self.data_table(headers, rows, table_id="db-schemas-table")
            else:
                # Flat response (stats as key-value)
                items = []
                for key, val in data.items():
                    if key in ("schemas", "items"):
                        continue
                    items.append(
                        f'<div class="detail-item">'
                        f'<span class="detail-label">{html_module.escape(str(key))}</span>'
                        f'<span class="detail-value">{html_module.escape(str(val))}</span>'
                        f'</div>'
                    )
                return f'<div class="detail-grid">{"".join(items)}</div>'

        return f'<pre style="font-family:var(--ds-font-mono); font-size:12px; overflow-x:auto;">{html_module.escape(str(data))}</pre>'

    def _fragment_db_activity(self, request: func.HttpRequest) -> str:
        """Fragment: active database queries."""
        ok, data = self.call_api(request, "/api/dbadmin/activity")

        if not ok:
            return self.error_block(
                f"Activity query failed: {data}",
                retry_url="/api/dashboard?tab=system&fragment=db-activity",
            )

        queries = []
        if isinstance(data, dict):
            queries = data.get("queries", data.get("activity", data.get("items", [])))
        elif isinstance(data, list):
            queries = data

        if not queries:
            return self.empty_block("No active queries.")

        headers = ["PID", "State", "Duration", "Query"]
        rows = []
        for q in queries:
            pid = q.get("pid", q.get("process_id", "--"))
            state = q.get("state", "--")
            duration = q.get("duration", q.get("query_duration", "--"))
            query_text = q.get("query", q.get("query_text", "--"))

            rows.append([
                html_module.escape(str(pid)),
                html_module.escape(str(state)),
                html_module.escape(str(duration)),
                f'<span style="font-family:var(--ds-font-mono); font-size:11px;">'
                f'{html_module.escape(str(query_text)[:120])}</span>',
            ])

        return self.data_table(headers, rows, table_id="db-activity-table")

    # -----------------------------------------------------------------------
    # QUEUES section (deferred -- D-6)
    # -----------------------------------------------------------------------

    def _render_queues(self, request: func.HttpRequest) -> str:
        """Render queue monitoring placeholder."""
        return f"""<div class="empty-state">
<div class="empty-icon">--</div>
<p>Queue monitoring is not yet available.</p>
<p style="font-size:var(--ds-font-size-sm); color:var(--ds-gray); margin-top:8px;">
Queue monitoring depends on Service Bus management APIs.
This feature is planned for a future iteration (D-6).
</p>
</div>"""

    # -----------------------------------------------------------------------
    # MAINTENANCE section
    # -----------------------------------------------------------------------

    def _render_maintenance(self, request: func.HttpRequest) -> str:
        """Render maintenance action forms."""
        return """<h3 class="section-heading">Schema Maintenance</h3>

<div style="display:flex; flex-direction:column; gap:20px;">

    <div class="detail-panel">
        <h4 style="margin-bottom:8px; color:var(--ds-navy);">Ensure Schema (Safe)</h4>
        <p style="font-size:var(--ds-font-size-sm); color:var(--ds-gray); margin-bottom:12px;">
            Creates missing tables, indexes, and enum types. Preserves all existing data.
            This is safe to run at any time and is idempotent.
        </p>
        <button hx-post="/api/dashboard?action=ensure"
                hx-vals='{"confirm": "yes"}'
                hx-target="#maintenance-result"
                hx-swap="innerHTML"
                hx-confirm="Run schema ensure? This creates missing tables/indexes (no data loss)."
                hx-disabled-elt="this"
                class="btn btn-primary">
            Run Ensure
            <span class="btn-indicator htmx-indicator">...</span>
        </button>
    </div>

    <div class="detail-panel" style="border-left:4px solid var(--ds-status-failed-text);">
        <h4 style="margin-bottom:8px; color:var(--ds-status-failed-text);">Rebuild Schema (DESTRUCTIVE)</h4>
        <p style="font-size:var(--ds-font-size-sm); color:var(--ds-gray); margin-bottom:12px;">
            Drops and recreates all schemas. ALL DATA WILL BE LOST.
            Only use for fresh dev/test environments or after major schema redesigns.
        </p>
        <div style="display:flex; gap:12px; flex-wrap:wrap;">
            <div>
                <label class="filter-label" style="margin-bottom:4px;">Target:</label>
                <select id="rebuild-target" name="target" class="filter-select">
                    <option value="">All schemas</option>
                    <option value="app">App schema only</option>
                    <option value="pgstac">PgSTAC schema only</option>
                </select>
            </div>
            <button hx-post="/api/dashboard?action=rebuild"
                    hx-include="#rebuild-target"
                    hx-vals='{"confirm": "yes"}'
                    hx-target="#maintenance-result"
                    hx-swap="innerHTML"
                    hx-confirm="REBUILD SCHEMA? This DELETES ALL DATA. Are you absolutely sure?"
                    hx-disabled-elt="this"
                    class="btn btn-danger">
                Rebuild Schema
                <span class="btn-indicator htmx-indicator">...</span>
            </button>
        </div>
    </div>

</div>

<div id="maintenance-result" style="margin-top:20px;"></div>"""
