# ============================================================================
# CLAUDE CONTEXT - PLATFORM_PANEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Dashboard panel - Platform operations (submit, requests, approvals)
# PURPOSE: Tab 1 of the dashboard: platform request lifecycle management
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: PlatformPanel
# DEPENDENCIES: azure.functions, web_dashboard.base_panel, web_dashboard.registry
# ============================================================================
"""
Platform panel for the dashboard.

Provides sub-tabs for:
    - submit: Submit new platform requests
    - requests: View and filter platform requests
    - approvals: Review and approve/reject pending releases
    - catalog: Search the data catalog by dataset/resource ID
    - lineage: View asset lineage chains
    - failures: View platform failures

Exports:
    PlatformPanel: Registered panel class
"""

import html as html_module
import logging
import azure.functions as func

from web_dashboard.base_panel import BasePanel
from web_dashboard.registry import PanelRegistry

logger = logging.getLogger(__name__)


@PanelRegistry.register
class PlatformPanel(BasePanel):
    """Platform operations panel -- submit, requests, approvals, catalog, lineage."""

    tab_order = 1

    def tab_name(self) -> str:
        return "platform"

    def tab_label(self) -> str:
        return "Platform"

    def default_section(self) -> str:
        return "requests"

    def sections(self) -> list:
        return [
            ("requests", "Requests"),
            ("approvals", "Approvals"),
            ("submit", "Submit"),
            ("catalog", "Catalog"),
            ("lineage", "Lineage"),
            ("failures", "Failures"),
        ]

    def render_section(self, request: func.HttpRequest, section: str) -> str:
        dispatch = {
            "requests": self._render_requests,
            "approvals": self._render_approvals,
            "submit": self._render_submit,
            "catalog": self._render_catalog,
            "lineage": self._render_lineage,
            "failures": self._render_failures,
        }
        handler = dispatch.get(section)
        if not handler:
            raise ValueError(f"Unknown platform section: {section}")
        return handler(request)

    def render_fragment(self, request: func.HttpRequest, fragment_name: str) -> str:
        dispatch = {
            "requests-table": self._fragment_requests_table,
            "approval-detail": self._fragment_approval_detail,
            "catalog-results": self._fragment_catalog_results,
            "lineage-graph": self._fragment_lineage_graph,
        }
        handler = dispatch.get(fragment_name)
        if not handler:
            raise ValueError(f"Unknown platform fragment: {fragment_name}")
        return handler(request)

    # -----------------------------------------------------------------------
    # REQUESTS section
    # -----------------------------------------------------------------------

    def _render_requests(self, request: func.HttpRequest) -> str:
        """Render the requests list with filters."""
        status_filter = request.params.get("status", "")
        hours_filter = request.params.get("hours", "24")
        limit = int(request.params.get("limit", "25"))
        page = int(request.params.get("page", "0"))

        # Build filter bar
        status_select = self.select_filter(
            "status", "Status",
            [
                ("", "All"),
                ("pending", "Pending"),
                ("processing", "Processing"),
                ("completed", "Completed"),
                ("failed", "Failed"),
            ],
            selected=status_filter,
        )
        hours_select = self.select_filter(
            "hours", "Period",
            [
                ("24", "Last 24h"),
                ("72", "Last 3 days"),
                ("168", "Last 7 days"),
                ("720", "Last 30 days"),
            ],
            selected=hours_filter,
        )
        filters = self.filter_bar("platform", "requests", [status_select, hours_select])

        # Fetch data
        params = {"limit": str(limit), "hours": hours_filter}
        if status_filter:
            params["status"] = status_filter

        ok, data = self.call_api(request, "/api/platform/status", params=params)

        if not ok:
            return filters + self.error_block(
                f"Failed to load requests: {data}",
                retry_url="/api/dashboard?tab=platform&section=requests",
            )

        # Parse response
        requests_list = []
        if isinstance(data, dict):
            requests_list = data.get("requests", data.get("items", []))
        elif isinstance(data, list):
            requests_list = data

        if not requests_list:
            return filters + self.empty_block(
                "No platform requests found. Use the Submit tab to create one."
            )

        # Build table
        headers = ["ID", "Type", "Dataset", "Status", "Created", "Age"]
        rows = []
        row_attrs = []
        for req_item in requests_list:
            req_id = req_item.get("request_id", req_item.get("id", ""))
            job_type = req_item.get("job_type", req_item.get("type", "--"))
            dataset = req_item.get("dataset_id", req_item.get("identifier", "--"))
            status = req_item.get("status", "--")
            created = req_item.get("created_at", req_item.get("submitted_at", ""))
            rows.append([
                self.truncate_id(req_id),
                html_module.escape(str(job_type)),
                html_module.escape(str(dataset)),
                self.status_badge(status),
                self.format_date(created),
                self.format_age(created),
            ])
            row_attrs.append({
                "id": f"row-{html_module.escape(str(req_id)[:8])}",
                "class": "clickable",
                "hx-get": f"/api/dashboard?tab=platform&section=requests&fragment=request-detail&request_id={html_module.escape(str(req_id))}",
                "hx-target": "next .detail-panel",
                "hx-swap": "innerHTML",
            })

        table = self.data_table(headers, rows, table_id="requests-table", row_attrs=row_attrs)

        # Pagination
        total = len(requests_list)
        if isinstance(data, dict):
            total = data.get("total", total)
        pagination = ""
        if total > limit:
            pagination = self.pagination_controls("platform", "requests", page, limit, total)

        return filters + table + pagination

    def _fragment_requests_table(self, request: func.HttpRequest) -> str:
        """Fragment: refresh requests table body only."""
        return self._render_requests(request)

    # -----------------------------------------------------------------------
    # APPROVALS section
    # -----------------------------------------------------------------------

    def _render_approvals(self, request: func.HttpRequest) -> str:
        """Render the approval queue."""
        ok, data = self.call_api(request, "/api/platform/approvals")

        if not ok:
            return self.error_block(
                f"Failed to load approvals: {data}",
                retry_url="/api/dashboard?tab=platform&section=approvals",
            )

        approvals_list = []
        if isinstance(data, dict):
            approvals_list = data.get("releases", data.get("approvals", data.get("items", [])))
        elif isinstance(data, list):
            approvals_list = data

        if not approvals_list:
            return self.empty_block(
                "No pending approvals. All releases have been reviewed."
            )

        # Stat strip for approval states
        state_counts = {}
        for item in approvals_list:
            state = item.get("approval_state", item.get("state", "unknown"))
            state_counts[state] = state_counts.get(state, 0) + 1
        stats = self.stat_strip(state_counts)

        # Build table
        headers = ["Release", "Asset", "Version", "State", "Clearance", "Updated", "Actions"]
        rows = []
        row_attrs = []
        for item in approvals_list:
            release_id = item.get("release_id", item.get("id", ""))
            asset_id = item.get("asset_identifier", item.get("asset_id", "--"))
            version = item.get("version_ordinal", item.get("version", "--"))
            state = item.get("approval_state", item.get("state", "--"))
            clearance = item.get("clearance_state", item.get("clearance", "--"))
            updated = item.get("updated_at", item.get("reviewed_at", ""))

            # Action buttons for pending_review items
            actions = ""
            if str(state).lower() == "pending_review":
                safe_rid = html_module.escape(str(release_id))
                actions = (
                    f'<button hx-post="/api/dashboard?action=approve" '
                    f'hx-vals=\'{{"release_id": "{safe_rid}", "reviewer": "", "clearance": "OUO"}}\' '
                    f'hx-target="#row-{html_module.escape(str(release_id)[:12])}" '
                    f'hx-swap="outerHTML" '
                    f'hx-confirm="Approve release {safe_rid}? This publishes the dataset." '
                    f'hx-disabled-elt="this" '
                    f'class="btn btn-sm btn-approve">Approve</button> '
                    f'<button hx-post="/api/dashboard?action=reject" '
                    f'hx-vals=\'{{"release_id": "{safe_rid}", "reviewer": "", "reason": ""}}\' '
                    f'hx-target="#row-{html_module.escape(str(release_id)[:12])}" '
                    f'hx-swap="outerHTML" '
                    f'hx-confirm="Reject release {safe_rid}?" '
                    f'hx-disabled-elt="this" '
                    f'class="btn btn-sm btn-reject">Reject</button>'
                    f'<span class="btn-indicator htmx-indicator">...</span>'
                )
            elif str(state).lower() == "approved":
                safe_rid = html_module.escape(str(release_id))
                actions = (
                    f'<button hx-post="/api/dashboard?action=revoke" '
                    f'hx-vals=\'{{"release_id": "{safe_rid}", "reviewer": "", "reason": ""}}\' '
                    f'hx-target="#row-{html_module.escape(str(release_id)[:12])}" '
                    f'hx-swap="outerHTML" '
                    f'hx-confirm="Revoke approval for release {safe_rid}? This unpublishes the dataset." '
                    f'hx-disabled-elt="this" '
                    f'class="btn btn-sm btn-danger">Revoke</button>'
                    f'<span class="btn-indicator htmx-indicator">...</span>'
                )

            rows.append([
                self.truncate_id(release_id, 12),
                html_module.escape(str(asset_id)),
                html_module.escape(str(version)),
                self.approval_badge(state),
                self.clearance_badge(clearance),
                self.format_date(updated),
                actions,
            ])
            row_attrs.append({
                "id": f"row-{html_module.escape(str(release_id)[:12])}",
            })

        table = self.data_table(
            headers, rows, table_id="approvals-table", row_attrs=row_attrs,
        )
        return stats + table

    def _fragment_approval_detail(self, request: func.HttpRequest) -> str:
        """Fragment: load approval detail panel."""
        release_id = request.params.get("release_id", "")
        if not release_id:
            return self.empty_block("No release ID specified.")

        ok, data = self.call_api(
            request, f"/api/platform/approvals/{release_id}"
        )
        if not ok:
            return self.error_block(
                f"Failed to load approval detail: {data}",
                retry_url=f"/api/dashboard?tab=platform&fragment=approval-detail&release_id={html_module.escape(release_id)}",
            )

        if not data:
            return self.empty_block(f"Release {html_module.escape(release_id)} not found.")

        # Render detail panel
        release = data if isinstance(data, dict) else {}
        safe_rid = html_module.escape(str(release.get("release_id", release_id)))
        return f"""<div class="detail-panel">
<h3>Release: {safe_rid}</h3>
<div class="detail-grid">
    <div class="detail-item">
        <span class="detail-label">Asset</span>
        <span class="detail-value">{html_module.escape(str(release.get("asset_identifier", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Version</span>
        <span class="detail-value">{html_module.escape(str(release.get("version_ordinal", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Approval State</span>
        <span class="detail-value">{self.approval_badge(release.get("approval_state", "--"))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Clearance</span>
        <span class="detail-value">{self.clearance_badge(release.get("clearance_state", "--"))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Job ID</span>
        <span class="detail-value mono">{html_module.escape(str(release.get("job_id", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Blob Path</span>
        <span class="detail-value mono">{html_module.escape(str(release.get("blob_path", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">STAC Item</span>
        <span class="detail-value mono">{html_module.escape(str(release.get("stac_item_id", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Reviewed By</span>
        <span class="detail-value">{html_module.escape(str(release.get("reviewer", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Created</span>
        <span class="detail-value">{self.format_date(release.get("created_at"))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Updated</span>
        <span class="detail-value">{self.format_date(release.get("updated_at"))}</span>
    </div>
</div>
</div>"""

    # -----------------------------------------------------------------------
    # SUBMIT section
    # -----------------------------------------------------------------------

    def _render_submit(self, request: func.HttpRequest) -> str:
        """Render the submission form."""
        return """<h3 class="section-heading">Submit Platform Request</h3>
<form id="submit-form" class="detail-panel">
    <div class="form-row">
        <div class="form-group">
            <label for="submit-job-type">Job Type</label>
            <select id="submit-job-type" name="job_type" class="form-control" required>
                <option value="">Select job type...</option>
                <option value="ingest_raster">Ingest Raster</option>
                <option value="ingest_vector">Ingest Vector</option>
                <option value="ingest_zarr">Ingest Zarr</option>
                <option value="virtualzarr">VirtualiZarr Pipeline</option>
            </select>
        </div>
        <div class="form-group">
            <label for="submit-source">Source URL</label>
            <input type="text" id="submit-source" name="source_url"
                   class="form-control" placeholder="https://... or /vsiaz/..."
                   required>
        </div>
    </div>
    <div class="form-row">
        <div class="form-group">
            <label for="submit-dataset">Dataset ID</label>
            <input type="text" id="submit-dataset" name="dataset_id"
                   class="form-control" placeholder="my_dataset_name">
        </div>
        <div class="form-group">
            <label for="submit-clearance">Clearance</label>
            <select id="submit-clearance" name="clearance" class="form-control">
                <option value="UNCLEARED">Uncleared</option>
                <option value="OUO" selected>OUO</option>
                <option value="PUBLIC">Public</option>
            </select>
        </div>
    </div>
    <div class="form-group">
        <label for="submit-params">Additional Parameters (JSON)</label>
        <textarea id="submit-params" name="parameters"
                  class="form-control" placeholder='{"key": "value"}'></textarea>
    </div>
    <div class="form-group">
        <label for="submit-notes">Notes</label>
        <textarea id="submit-notes" name="notes"
                  class="form-control" placeholder="Optional notes..."></textarea>
    </div>
    <div style="display:flex; gap:12px; margin-top:8px;">
        <button type="button"
                hx-post="/api/dashboard?action=validate"
                hx-include="#submit-form"
                hx-target="#submit-result"
                hx-swap="innerHTML"
                hx-disabled-elt="this"
                class="btn btn-secondary">
            Validate (Dry Run)
            <span class="btn-indicator htmx-indicator">...</span>
        </button>
        <button type="button"
                hx-post="/api/dashboard?action=submit"
                hx-include="#submit-form"
                hx-target="#submit-result"
                hx-swap="innerHTML"
                hx-confirm="Submit this request? This will start processing."
                hx-disabled-elt="this"
                class="btn btn-primary">
            Submit Request
            <span class="btn-indicator htmx-indicator">...</span>
        </button>
    </div>
</form>
<div id="submit-result"></div>"""

    # -----------------------------------------------------------------------
    # CATALOG section
    # -----------------------------------------------------------------------

    def _render_catalog(self, request: func.HttpRequest) -> str:
        """Render the catalog search interface."""
        dataset_id = request.params.get("dataset_id", "")
        q = request.params.get("q", "")

        search_bar = f"""<div class="filter-bar">
<label class="filter-label">Dataset ID:
<input type="text" name="dataset_id" value="{html_module.escape(dataset_id)}"
       class="filter-input" placeholder="Enter dataset ID..."
       hx-get="/api/dashboard?tab=platform&section=catalog"
       hx-target="#panel-content"
       hx-trigger="keyup changed delay:500ms"
       hx-include="this"
       hx-push-url="true">
</label>
<label class="filter-label">Search:
<input type="text" name="q" value="{html_module.escape(q)}"
       class="filter-input" placeholder="Search term..."
       hx-get="/api/dashboard?tab=platform&section=catalog"
       hx-target="#panel-content"
       hx-trigger="keyup changed delay:500ms"
       hx-include="this"
       hx-push-url="true">
</label>
</div>"""

        if not dataset_id and not q:
            return search_bar + self.empty_block(
                "Enter a dataset ID or resource ID to search the catalog."
            )

        # Search catalog
        if dataset_id:
            ok, data = self.call_api(
                request, f"/api/platform/catalog/dataset/{dataset_id}"
            )
        else:
            ok, data = self.call_api(
                request, "/api/platform/catalog/lookup", params={"q": q}
            )

        if not ok:
            return search_bar + self.error_block(
                f"Catalog search failed: {data}",
                retry_url=f"/api/dashboard?tab=platform&section=catalog&dataset_id={html_module.escape(dataset_id)}&q={html_module.escape(q)}",
            )

        # Handle different response shapes
        items = []
        if isinstance(data, dict):
            items = data.get("assets", data.get("items", data.get("results", [])))
            if not items and data:
                # Single result (asset detail)
                items = [data]
        elif isinstance(data, list):
            items = data

        if not items:
            return search_bar + self.empty_block(
                f"No catalog entries found for '{html_module.escape(dataset_id or q)}'."
            )

        headers = ["ID", "Dataset", "Type", "Version", "Status", "Created"]
        table_rows = []
        for item in items:
            item_id = item.get("asset_id", item.get("id", ""))
            dataset = item.get("dataset_id", item.get("identifier", "--"))
            data_type = item.get("data_type", "--")
            version = item.get("version_ordinal", item.get("version", "--"))
            status = item.get("status", item.get("approval_state", "--"))
            created = item.get("created_at", "")
            table_rows.append([
                self.truncate_id(item_id),
                html_module.escape(str(dataset)),
                self.data_type_badge(data_type),
                html_module.escape(str(version)),
                self.status_badge(status),
                self.format_date(created),
            ])

        table = self.data_table(headers, table_rows, table_id="catalog-table")
        return search_bar + table

    def _fragment_catalog_results(self, request: func.HttpRequest) -> str:
        """Fragment: catalog search results only."""
        return self._render_catalog(request)

    # -----------------------------------------------------------------------
    # LINEAGE section
    # -----------------------------------------------------------------------

    def _render_lineage(self, request: func.HttpRequest) -> str:
        """Render the lineage viewer."""
        request_id = request.params.get("request_id", "")

        search_bar = f"""<div class="filter-bar">
<label class="filter-label">Request ID:
<input type="text" name="request_id" value="{html_module.escape(request_id)}"
       class="filter-input" placeholder="Enter request ID..."
       hx-get="/api/dashboard?tab=platform&section=lineage"
       hx-target="#panel-content"
       hx-trigger="keyup changed delay:500ms"
       hx-include="this"
       hx-push-url="true">
</label>
</div>"""

        if not request_id:
            return search_bar + self.empty_block(
                "Enter a request ID to view its lineage chain."
            )

        ok, data = self.call_api(
            request, f"/api/platform/lineage/{request_id}"
        )

        if not ok:
            return search_bar + self.error_block(
                f"Lineage lookup failed: {data}",
                retry_url=f"/api/dashboard?tab=platform&section=lineage&request_id={html_module.escape(request_id)}",
            )

        if not data:
            return search_bar + self.empty_block(
                f"No lineage found for request '{html_module.escape(request_id)}'."
            )

        # Render lineage chain
        lineage = data if isinstance(data, dict) else {}
        chain = lineage.get("chain", lineage.get("lineage", []))
        if isinstance(chain, list) and chain:
            chain_html = []
            for i, step in enumerate(chain):
                step_type = html_module.escape(str(step.get("type", step.get("event_type", "--"))))
                step_status = step.get("status", "--")
                step_time = step.get("timestamp", step.get("created_at", ""))
                step_detail = html_module.escape(str(step.get("detail", step.get("message", ""))))
                arrow = " -> " if i < len(chain) - 1 else ""
                chain_html.append(
                    f'<div class="detail-panel" style="margin-bottom:8px;">'
                    f'<strong>{step_type}</strong> '
                    f'{self.status_badge(step_status)} '
                    f'<span style="color:var(--ds-gray); font-size:12px;">'
                    f'{self.format_date(step_time)}</span>'
                    f'{f"<p style=margin-top:4px>{step_detail}</p>" if step_detail else ""}'
                    f'</div>'
                )
            return search_bar + "".join(chain_html)
        else:
            # Single lineage response (render as detail panel)
            return search_bar + f"""<div class="detail-panel">
<h3>Lineage: {html_module.escape(request_id[:16])}</h3>
<pre style="background:var(--ds-bg); padding:12px; border-radius:4px;
     font-family:var(--ds-font-mono); font-size:12px; overflow-x:auto;
     white-space:pre-wrap;">{html_module.escape(str(data))}</pre>
</div>"""

    def _fragment_lineage_graph(self, request: func.HttpRequest) -> str:
        """Fragment: lineage content only."""
        return self._render_lineage(request)

    # -----------------------------------------------------------------------
    # FAILURES section
    # -----------------------------------------------------------------------

    def _render_failures(self, request: func.HttpRequest) -> str:
        """Render the failures view."""
        hours = request.params.get("hours", "24")
        hours_select = self.select_filter(
            "hours", "Period",
            [("24", "Last 24h"), ("72", "Last 3 days"), ("168", "Last 7 days")],
            selected=hours,
        )
        filters = self.filter_bar("platform", "failures", [hours_select])

        ok, data = self.call_api(
            request, "/api/platform/failures", params={"hours": hours}
        )

        if not ok:
            return filters + self.error_block(
                f"Failed to load failures: {data}",
                retry_url="/api/dashboard?tab=platform&section=failures",
            )

        failures = []
        if isinstance(data, dict):
            failures = data.get("failures", data.get("items", []))
        elif isinstance(data, list):
            failures = data

        if not failures:
            return filters + self.empty_block(
                "No failed requests in the selected time period."
            )

        headers = ["ID", "Type", "Error", "Failed At"]
        rows = []
        for f in failures:
            fid = f.get("request_id", f.get("job_id", f.get("id", "")))
            ftype = f.get("job_type", f.get("type", "--"))
            error = f.get("error_message", f.get("error", f.get("failure_reason", "--")))
            failed_at = f.get("failed_at", f.get("updated_at", ""))
            rows.append([
                self.truncate_id(fid),
                html_module.escape(str(ftype)),
                html_module.escape(str(error)[:120]),
                self.format_date(failed_at),
            ])

        return filters + self.data_table(headers, rows, table_id="failures-table")
