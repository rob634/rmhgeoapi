# ============================================================================
# CLAUDE CONTEXT - PLATFORM CONFIGURATION & STATUS LOOKUP INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Platform dashboard with interactive status lookup
# PURPOSE: DDH integration config, status lookup by any ID, endpoint reference
# LAST_REVIEWED: 25 FEB 2026
# EXPORTS: PlatformInterface
# DEPENDENCIES: azure.functions, web_interfaces.base, urllib.request
# ============================================================================
"""
Platform Configuration Interface.

Shows DDH (Development Data Hub) integration configuration, Platform API endpoints,
system health status, and interactive status lookup.

Features (25 FEB 2026):
    - Status Lookup: Query by Request ID, Job ID, Dataset+Resource, Asset ID, Release ID
    - HTMX-powered result cards showing asset, release, job, outputs, services, approval, versions
    - Updated endpoint reference table grouped by category
    - Live platform health status

The Platform layer is an Anti-Corruption Layer (ACL) that translates DDH requests
to CoreMachine jobs, providing stable internal APIs while DDH APIs may evolve.
"""

import json
import logging

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('platform')
class PlatformInterface(BaseInterface):
    """
    Platform configuration and DDH integration dashboard.

    Shows:
        - DDH configuration patterns (table naming, output folders, STAC IDs)
        - Valid input containers and access levels
        - Platform API endpoints with documentation
        - Placeholder for DDH application health (future)
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Platform configuration page."""
        return self.wrap_html(
            title="Platform Configuration - DDH Integration",
            content=self._generate_html_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js(),
            include_htmx=True
        )

    # ========================================================================
    # HTMX PARTIAL HANDLERS — Status Lookup
    # ========================================================================

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """Handle HTMX partial requests for platform fragments."""
        if fragment == 'status-lookup':
            return self._render_status_lookup_fragment(request)
        else:
            raise ValueError(f"Unknown fragment: {fragment}")

    def _render_status_lookup_fragment(self, request: func.HttpRequest) -> str:
        """
        Handle status lookup form submission.

        Reads lookup_type and identifier(s) from POST form body,
        calls the Platform status API, and renders the result.
        """
        import urllib.request
        import urllib.error
        import os
        from urllib.parse import parse_qs

        # Parse POST form body
        body = request.get_body().decode('utf-8')
        form = parse_qs(body)

        lookup_type = (form.get('lookup_type', [''])[0]).strip()
        if not lookup_type:
            return self._render_status_error("No lookup type selected.")

        # Build URL based on lookup type
        website_hostname = os.environ.get('WEBSITE_HOSTNAME')
        if not website_hostname:
            return self._render_status_error("WEBSITE_HOSTNAME not set — cannot call Platform API.")

        base_url = f"https://{website_hostname}"

        if lookup_type == 'dataset_resource':
            dataset_id = (form.get('dataset_id', [''])[0]).strip()
            resource_id = (form.get('resource_id', [''])[0]).strip()
            if not dataset_id or not resource_id:
                return self._render_status_error("Both dataset_id and resource_id are required for dataset+resource lookup.")
            from urllib.parse import quote
            api_url = f"{base_url}/api/platform/status?dataset_id={quote(dataset_id)}&resource_id={quote(resource_id)}&detail=full"
        else:
            # request_id, job_id, asset_id, release_id — all use the same pattern
            lookup_id = (form.get('lookup_id', [''])[0]).strip()
            if not lookup_id:
                return self._render_status_error(f"An identifier is required for {lookup_type} lookup.")
            from urllib.parse import quote
            api_url = f"{base_url}/api/platform/status/{quote(lookup_id)}?detail=full"

        logger.info(f"[PlatformStatus] Lookup: type={lookup_type}, url={api_url}")

        # Call Platform status API (GET request)
        http_request = urllib.request.Request(api_url, method='GET')

        try:
            with urllib.request.urlopen(http_request, timeout=30) as response:
                response_data = json.loads(response.read().decode('utf-8'))
                logger.info(f"[PlatformStatus] Success: request_id={response_data.get('request_id', 'N/A')}")
                return self._render_status_result(response_data)

        except urllib.error.HTTPError as http_err:
            error_body = http_err.read().decode('utf-8')
            try:
                error_json = json.loads(error_body)
                error_msg = error_json.get('error', str(http_err))
                hint = error_json.get('hint', '')
                if hint:
                    error_msg = f"{error_msg} — {hint}"
            except Exception:
                error_msg = error_body or str(http_err)
            logger.error(f"[PlatformStatus] HTTP {http_err.code}: {error_msg}")
            return self._render_status_error(error_msg)

        except urllib.error.URLError as url_err:
            logger.error(f"[PlatformStatus] Connection error: {url_err}")
            return self._render_status_error(f"Connection error: {url_err.reason}")

        except Exception as exc:
            logger.error(f"[PlatformStatus] Unexpected error: {exc}")
            return self._render_status_error(f"Unexpected error: {exc}")

    # ========================================================================
    # STATUS RESULT RENDERER
    # ========================================================================

    def _render_status_result(self, data: dict) -> str:
        """
        Render the full Platform status API response as styled HTML cards.

        Each data block is rendered as a card only when non-null.
        """
        parts = ['<div class="status-result-container">']

        # Request ID bar
        request_id = data.get('request_id')
        if request_id:
            parts.append(
                f'<div class="request-id-bar">'
                f'<span class="result-label">Request ID:</span> '
                f'<span class="result-value mono">{self._esc(request_id)}</span>'
                f'</div>'
            )

        # --- Asset card ---
        asset = data.get('asset')
        if asset:
            parts.append('<div class="result-card">')
            parts.append('<h3 class="result-card-title">Asset</h3>')
            parts.append('<div class="result-grid">')
            parts.append(self._field('Dataset ID', self._esc(asset.get('dataset_id'))))
            parts.append(self._field('Resource ID', self._esc(asset.get('resource_id'))))
            parts.append(self._field('Data Type', self._data_type_badge(asset.get('data_type', ''))))
            parts.append(self._field('Release Count', self._esc(asset.get('release_count'))))
            parts.append(self._field('Asset ID', self._esc(asset.get('asset_id')), full_width=True))
            parts.append('</div>')
            parts.append('</div>')

        # --- Release card ---
        release = data.get('release')
        if release:
            parts.append('<div class="result-card">')
            parts.append('<h3 class="result-card-title">Release</h3>')
            parts.append('<div class="result-grid">')
            parts.append(self._field('Version ID', self._esc(release.get('version_id'))))
            ordinal = release.get('version_ordinal')
            parts.append(self._field('Ordinal', f'ord{ordinal}' if ordinal is not None else ''))
            parts.append(self._field('Revision', self._esc(release.get('revision'))))
            is_latest = release.get('is_latest')
            parts.append(self._field('Latest', 'Yes' if is_latest else 'No'))
            parts.append(self._field('Processing', self._status_badge(release.get('processing_status', 'unknown'))))
            parts.append(self._field('Approval', self._approval_badge(release.get('approval_state', 'unknown'))))
            parts.append(self._field('Clearance', self._clearance_badge(release.get('clearance_state', 'unknown'))))
            parts.append(self._field('Release ID', self._esc(release.get('release_id')), full_width=True))
            parts.append('</div>')
            parts.append('</div>')

        # --- Job card ---
        job_status = data.get('job_status')
        detail = data.get('detail') or {}
        if job_status or detail:
            parts.append('<div class="result-card">')
            parts.append('<h3 class="result-card-title">Job</h3>')
            parts.append('<div class="result-grid">')
            if job_status:
                parts.append(self._field('Status', self._status_badge(job_status)))
            job_id = detail.get('job_id')
            if job_id:
                parts.append(self._field('Job ID', self._esc(job_id)))
            job_type = detail.get('job_type')
            if job_type:
                parts.append(self._field('Job Type', self._esc(job_type)))
            job_stage = detail.get('job_stage')
            if job_stage is not None:
                parts.append(self._field('Stage', self._esc(job_stage)))
            created_at = detail.get('created_at')
            if created_at:
                parts.append(self._field('Created', self._esc(created_at), full_width=True))
            parts.append('</div>')
            if job_id:
                parts.append(self._job_link(job_id))
            parts.append('</div>')

        # --- Error card ---
        error = data.get('error')
        if error:
            parts.append('<div class="result-card result-card-error">')
            parts.append('<h3 class="result-card-title">Error</h3>')
            parts.append('<div class="result-grid">')
            if error.get('code'):
                parts.append(self._field('Code', self._esc(error.get('code'))))
            if error.get('category'):
                parts.append(self._field('Category', self._esc(error.get('category'))))
            if error.get('message'):
                parts.append(self._field('Message', self._esc(error.get('message')), full_width=True))
            if error.get('remediation'):
                parts.append(self._field('Remediation', self._esc(error.get('remediation')), full_width=True))
            if error.get('user_fixable') is not None:
                parts.append(self._field('User Fixable', 'Yes' if error.get('user_fixable') else 'No'))
            if error.get('detail'):
                parts.append(self._field('Detail', self._esc(error.get('detail')), full_width=True))
            parts.append('</div>')
            parts.append('</div>')

        # --- Outputs card ---
        outputs = data.get('outputs')
        if outputs:
            parts.append('<div class="result-card">')
            parts.append('<h3 class="result-card-title">Outputs</h3>')
            parts.append('<div class="result-grid">')
            if outputs.get('blob_path'):
                parts.append(self._field('Blob Path', f'<span class="mono">{self._esc(outputs.get("blob_path"))}</span>', full_width=True))
            if outputs.get('table_name'):
                parts.append(self._field('Table', f'<span class="mono">{self._esc(outputs.get("table_name"))}</span>'))
            if outputs.get('schema'):
                parts.append(self._field('Schema', f'<span class="mono">{self._esc(outputs.get("schema"))}</span>'))
            if outputs.get('container'):
                parts.append(self._field('Container', f'<span class="mono">{self._esc(outputs.get("container"))}</span>'))
            if outputs.get('stac_collection_id'):
                parts.append(self._field('STAC Collection', f'<span class="mono">{self._esc(outputs.get("stac_collection_id"))}</span>'))
            if outputs.get('stac_item_id'):
                parts.append(self._field('STAC Item', f'<span class="mono">{self._esc(outputs.get("stac_item_id"))}</span>', full_width=True))
            parts.append('</div>')
            parts.append('</div>')

        # --- Services card ---
        services = data.get('services')
        if services:
            parts.append('<div class="result-card">')
            parts.append('<h3 class="result-card-title">Services</h3>')
            parts.append('<div class="service-links">')
            service_labels = {
                'preview': 'Preview',
                'tiles': 'Tiles',
                'viewer': 'Viewer',
                'collection': 'Collection',
                'items': 'Items',
                'stac_collection': 'STAC Collection',
                'stac_item': 'STAC Item',
            }
            for key, label in service_labels.items():
                url = services.get(key)
                if url:
                    parts.append(
                        f'<a href="{self._esc(url)}" target="_blank" class="service-link">{label}</a>'
                    )
            parts.append('</div>')
            parts.append('</div>')

        # --- Approval card ---
        approval = data.get('approval')
        if approval:
            parts.append('<div class="result-card result-card-approval">')
            parts.append('<h3 class="result-card-title">Approval</h3>')
            parts.append('<div class="result-grid">')
            if approval.get('asset_id'):
                parts.append(self._field('Asset ID', self._esc(approval.get('asset_id')), full_width=True))
            if approval.get('approve_url'):
                parts.append(self._field('Approve URL', f'<span class="mono">{self._esc(approval.get("approve_url"))}</span>', full_width=True))
            parts.append('</div>')
            parts.append(self._approval_viewer_link(approval))
            parts.append('</div>')

        # --- Versions card ---
        versions = data.get('versions')
        if versions:
            parts.append('<div class="result-card">')
            parts.append('<h3 class="result-card-title">Versions</h3>')
            parts.append('<table class="versions-table">')
            parts.append(
                '<thead><tr>'
                '<th>Version</th><th>Ordinal</th><th>Processing</th>'
                '<th>Approval</th><th>Clearance</th><th>Latest</th><th>Release ID</th>'
                '</tr></thead>'
            )
            parts.append('<tbody>')
            for v in versions:
                release_id = self._esc(v.get('release_id', ''))
                truncated_id = release_id[:16] + '...' if len(release_id) > 16 else release_id
                ordinal = v.get('version_ordinal')
                parts.append(
                    f'<tr>'
                    f'<td>{self._esc(v.get("version_id", ""))}</td>'
                    f'<td>{"ord" + str(ordinal) if ordinal is not None else ""}</td>'
                    f'<td>{self._status_badge(v.get("processing_status", "unknown"))}</td>'
                    f'<td>{self._approval_badge(v.get("approval_state", "unknown"))}</td>'
                    f'<td>{self._clearance_badge(v.get("clearance_state", "unknown"))}</td>'
                    f'<td>{"Yes" if v.get("is_latest") else "No"}</td>'
                    f'<td title="{release_id}"><span class="mono">{truncated_id}</span></td>'
                    f'</tr>'
                )
            parts.append('</tbody></table>')
            parts.append('</div>')

        parts.append('</div>')  # close status-result-container
        return '\n'.join(parts)

    # ========================================================================
    # STATUS ERROR RENDERER
    # ========================================================================

    def _render_status_error(self, message: str) -> str:
        """Render an error message for a failed status lookup."""
        return f'''
        <div class="status-result-container">
            <div class="result-card result-card-error">
                <h3 class="result-card-title">Lookup Failed</h3>
                <p class="error-message">{self._esc(message)}</p>
            </div>
        </div>'''

    # ========================================================================
    # HELPER METHODS — Badges, escaping, field rendering
    # ========================================================================

    @staticmethod
    def _field(label: str, value, full_width: bool = False) -> str:
        """Render a single field in a result grid."""
        css = 'result-field full-width' if full_width else 'result-field'
        return (
            f'<div class="{css}">'
            f'<span class="result-label">{label}</span>'
            f'<span class="result-value">{value}</span>'
            f'</div>'
        )

    @staticmethod
    def _esc(value) -> str:
        """HTML-escape a string."""
        import html as html_mod
        return html_mod.escape(str(value)) if value is not None else ''

    @staticmethod
    def _status_badge(status: str) -> str:
        """Render a processing status badge."""
        colors = {
            'completed': ('badge-success', 'completed'),
            'failed': ('badge-error', 'failed'),
            'processing': ('badge-processing', 'processing'),
            'pending': ('badge-pending', 'pending'),
            'queued': ('badge-pending', 'queued'),
            'unknown': ('badge-unknown', 'unknown'),
        }
        css_class, label = colors.get(status, ('badge-unknown', status))
        import html as html_mod
        return f'<span class="badge {css_class}">{html_mod.escape(str(label))}</span>'

    @staticmethod
    def _approval_badge(state: str) -> str:
        """Render an approval state badge."""
        colors = {
            'approved': 'badge-success',
            'pending_review': 'badge-warning',
            'rejected': 'badge-error',
            'revoked': 'badge-error',
            'draft': 'badge-pending',
            'not_submitted': 'badge-unknown',
        }
        css_class = colors.get(state, 'badge-unknown')
        import html as html_mod
        return f'<span class="badge {css_class}">{html_mod.escape(str(state))}</span>'

    @staticmethod
    def _clearance_badge(state: str) -> str:
        """Render a clearance state badge."""
        colors = {
            'cleared': 'badge-success',
            'pending': 'badge-pending',
            'not_cleared': 'badge-unknown',
        }
        css_class = colors.get(state, 'badge-unknown')
        import html as html_mod
        return f'<span class="badge {css_class}">{html_mod.escape(str(state))}</span>'

    @staticmethod
    def _data_type_badge(data_type: str) -> str:
        """Render a data type badge (raster/vector)."""
        colors = {
            'raster': 'badge-raster',
            'vector': 'badge-vector',
        }
        css_class = colors.get(data_type, 'badge-unknown')
        import html as html_mod
        return f'<span class="badge {css_class}">{html_mod.escape(str(data_type))}</span>'

    @staticmethod
    def _job_link(job_id: str) -> str:
        """Render a link to the Execution Dashboard for a job."""
        if not job_id:
            return ''
        import html as html_mod
        safe_id = html_mod.escape(str(job_id))
        return (
            f'<div class="result-actions">'
            f'<a href="/api/interface/execution?job_id={safe_id}" class="action-link">'
            f'View in Execution Dashboard</a>'
            f'</div>'
        )

    @staticmethod
    def _approval_viewer_link(approval: dict) -> str:
        """Render a link to open the viewer for approval review."""
        viewer = approval.get('viewer_url')
        if not viewer:
            return ''
        import html as html_mod
        return (
            f'<div class="result-actions">'
            f'<a href="{html_mod.escape(viewer)}" target="_blank" class="action-link">'
            f'Open Viewer for Review</a>'
            f'</div>'
        )

    # ========================================================================
    # CSS / HTML / JS GENERATORS (existing)
    # ========================================================================

    def _generate_css(self) -> str:
        """Platform-specific styles."""
        return """
            .dashboard-header {
                background: white;
                padding: 25px 30px;
                border-radius: 3px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                margin-bottom: 20px;
                border-left: 4px solid #0071BC;
            }

            .dashboard-header h1 {
                color: #053657;
                font-size: 24px;
                margin-bottom: 8px;
                font-weight: 700;
            }

            .subtitle {
                color: #626F86;
                font-size: 14px;
                margin: 0;
            }

            .section {
                background: white;
                border-radius: 8px;
                padding: 24px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .section h2 {
                color: var(--ds-navy);
                font-size: 20px;
                margin: 0 0 16px 0;
                padding-bottom: 12px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .config-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 16px;
            }

            .config-card {
                background: var(--ds-bg);
                border: 1px solid var(--ds-gray-light);
                border-radius: 6px;
                padding: 16px;
            }

            .config-card h3 {
                color: var(--ds-blue-primary);
                font-size: 14px;
                margin: 0 0 8px 0;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .config-value {
                font-family: 'Monaco', 'Consolas', monospace;
                font-size: 13px;
                background: white;
                padding: 8px 12px;
                border-radius: 4px;
                border: 1px solid #ddd;
                word-break: break-all;
            }

            .tag-list {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 8px;
            }

            .tag {
                background: var(--ds-blue-primary);
                color: white;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
            }

            .tag.bronze { background: #8B4513; }
            .tag.silver { background: #6c757d; }
            .tag.gold { background: #DAA520; }
            .tag.public { background: #28a745; }
            .tag.ouo { background: #ffc107; color: #333; }
            .tag.restricted { background: #dc3545; }

            .endpoint-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }

            .endpoint-table th,
            .endpoint-table td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .endpoint-table th {
                background: var(--ds-bg);
                font-weight: 600;
                color: var(--ds-navy);
            }

            .endpoint-table tr:hover {
                background: #f8f9fa;
            }

            .method {
                font-family: monospace;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
            }

            .method.post { background: #d4edda; color: #155724; }
            .method.get { background: #cce5ff; color: #004085; }

            .endpoint-group {
                background: #f0f4f8;
                font-weight: 700;
                color: var(--ds-navy);
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                padding: 8px 12px;
            }

            .endpoint-path {
                font-family: monospace;
                color: var(--ds-blue-primary);
            }

            .status-card {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 16px;
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 6px;
            }

            .status-icon {
                font-size: 24px;
            }

            .status-text h4 {
                margin: 0 0 4px 0;
                color: #856404;
            }

            .status-text p {
                margin: 0;
                font-size: 13px;
                color: #856404;
            }

            .live-status {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
            }

            .live-status.healthy {
                background: #d4edda;
                color: #155724;
            }

            .live-status.loading {
                background: #fff3cd;
                color: #856404;
            }

            .live-status.error {
                background: #f8d7da;
                color: #721c24;
            }

            .pulse {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: currentColor;
                animation: pulse 2s infinite;
            }

            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }

            /* Status Lookup Form */
            .lookup-form { margin-bottom: 20px; }
            .lookup-controls {
                display: flex;
                gap: 8px;
                align-items: center;
                flex-wrap: wrap;
            }
            .lookup-select {
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
                background: white;
                min-width: 180px;
            }
            .lookup-inputs { display: flex; gap: 8px; flex: 1; min-width: 200px; }
            .lookup-input {
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
                font-family: 'Monaco', 'Consolas', monospace;
                flex: 1;
            }
            .lookup-input-half { flex: 1; }
            .lookup-input:focus { outline: none; border-color: var(--ds-blue-primary); box-shadow: 0 0 0 2px rgba(0,113,188,0.2); }
            .lookup-btn { white-space: nowrap; }

            /* Result Cards */
            .status-result-container { margin-top: 16px; }
            .request-id-bar {
                padding: 8px 12px;
                background: #f0f4f8;
                border-radius: 4px;
                font-size: 13px;
                color: #626F86;
                margin-bottom: 12px;
            }
            .result-card {
                background: #f8f9fa;
                border: 1px solid #e1e4e8;
                border-radius: 6px;
                padding: 16px;
                margin-bottom: 12px;
            }
            .result-card-error {
                background: #fef2f2;
                border-color: #fecaca;
            }
            .result-card-approval {
                background: #fffbeb;
                border-color: #fde68a;
            }
            .result-card-title {
                color: var(--ds-blue-primary);
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin: 0 0 12px 0;
                padding-bottom: 8px;
                border-bottom: 1px solid #e1e4e8;
            }
            .result-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 12px;
            }
            .result-field { display: flex; flex-direction: column; gap: 2px; }
            .result-field.full-width { grid-column: 1 / -1; }
            .result-label { font-size: 11px; color: #626F86; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
            .result-value { font-size: 14px; color: #1a1a2e; }
            .result-value.mono { font-family: 'Monaco', 'Consolas', monospace; font-size: 13px; }
            .result-value.small, .mono.small { font-size: 11px; word-break: break-all; }
            .error-message { color: #991b1b; font-size: 14px; margin: 0; }

            /* Badges */
            .badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 600;
            }
            .badge-success { background: #d1fae5; color: #065f46; }
            .badge-error { background: #fee2e2; color: #991b1b; }
            .badge-processing { background: #dbeafe; color: #1e40af; }
            .badge-pending { background: #e0e7ff; color: #3730a3; }
            .badge-warning { background: #fef3c7; color: #92400e; }
            .badge-unknown { background: #f3f4f6; color: #6b7280; }
            .badge-raster { background: #dbeafe; color: #1e40af; }
            .badge-vector { background: #d1fae5; color: #065f46; }

            /* Service Links */
            .service-links { display: flex; gap: 8px; flex-wrap: wrap; }
            .service-link {
                display: inline-block;
                padding: 6px 14px;
                background: var(--ds-blue-primary);
                color: white;
                text-decoration: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: 600;
            }
            .service-link:hover { opacity: 0.85; }

            /* Action Links */
            .result-actions { margin-top: 12px; padding-top: 8px; border-top: 1px solid #e1e4e8; }
            .action-link {
                color: var(--ds-blue-primary);
                text-decoration: none;
                font-size: 13px;
                font-weight: 600;
            }
            .action-link:hover { text-decoration: underline; }

            /* Versions Table */
            .versions-table { width: 100%; border-collapse: collapse; font-size: 13px; }
            .versions-table th, .versions-table td {
                padding: 8px 10px;
                text-align: left;
                border-bottom: 1px solid #e1e4e8;
            }
            .versions-table th {
                background: #f0f4f8;
                font-weight: 600;
                color: var(--ds-navy);
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            /* HTMX Spinner */
            .spinner-inline { display: none; }
            .htmx-indicator.spinner-inline {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 2px solid #ddd;
                border-top-color: var(--ds-blue-primary);
                border-radius: 50%;
                animation: spin 0.6s linear infinite;
            }
            @keyframes spin { to { transform: rotate(360deg); } }
        """

    def _generate_html_content(self) -> str:
        """Generate main content HTML."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Platform Configuration</h1>
                <p class="subtitle">DDH (Development Data Hub) Integration Settings</p>
            </header>

            <!-- Platform Health Status -->
            <div class="section">
                <h2>Platform Status</h2>
                <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                    <div>
                        <strong>API Status:</strong>
                        <span id="platform-status" class="live-status loading">
                            <span class="pulse"></span> Checking...
                        </span>
                    </div>
                    <div>
                        <strong>Jobs (24h):</strong>
                        <span id="jobs-count">--</span>
                    </div>
                    <div>
                        <strong>Success Rate:</strong>
                        <span id="success-rate">--</span>
                    </div>
                    <div>
                        <strong>Pending Review:</strong>
                        <span id="pending-review-count" style="font-weight: 700;">--</span>
                    </div>
                    <div>
                        <a href="/api/interface/asset-versions" style="color: var(--ds-blue-primary); text-decoration: none; font-weight: 600;">
                            Asset Versions &rarr;
                        </a>
                    </div>
                </div>
            </div>

            <!-- Status Lookup -->
            <div class="section">
                <h2>Status Lookup</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Look up any Platform request, job, asset, or release by ID.
                </p>
                <form id="status-lookup-form" class="lookup-form"
                      hx-post="/api/interface/platform?fragment=status-lookup"
                      hx-target="#status-result"
                      hx-indicator="#lookup-spinner">
                    <div class="lookup-controls">
                        <select name="lookup_type" id="lookup-type" class="lookup-select"
                                onchange="updateLookupInputs()">
                            <option value="request_id">Request ID</option>
                            <option value="job_id">Job ID</option>
                            <option value="dataset_resource">Dataset + Resource</option>
                            <option value="asset_id">Asset ID</option>
                            <option value="release_id">Release ID</option>
                        </select>
                        <div id="lookup-inputs" class="lookup-inputs">
                            <input type="text" name="lookup_id" id="lookup-id"
                                   placeholder="Enter Request ID..."
                                   class="lookup-input">
                        </div>
                        <button type="submit" class="btn btn-primary lookup-btn">Search</button>
                        <span id="lookup-spinner" class="htmx-indicator spinner-inline"></span>
                    </div>
                </form>
                <div id="status-result"></div>
            </div>

            <!-- DDH Configuration -->
            <div class="section">
                <h2>DDH Naming Patterns</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Platform translates DDH identifiers (dataset_id, resource_id, version_id) to CoreMachine outputs. Version ID is optional at submit (draft mode) and assigned at approval:
                </p>
                <div class="config-grid">
                    <div class="config-card">
                        <h3>PostGIS Table Name</h3>
                        <div class="config-value">{dataset_id}_{resource_id}_{version_id|draft}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial_imagery_site_alpha_v1_0 (or _draft before approval)
                        </p>
                    </div>
                    <div class="config-card">
                        <h3>Raster Output Folder</h3>
                        <div class="config-value">{dataset_id}/{resource_id}/{version_id|draft}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial-imagery/site-alpha/v1.0 (or /draft before approval)
                        </p>
                    </div>
                    <div class="config-card">
                        <h3>STAC Collection ID</h3>
                        <div class="config-value">{dataset_id}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial-imagery
                        </p>
                    </div>
                    <div class="config-card">
                        <h3>STAC Item ID</h3>
                        <div class="config-value">{dataset_id}_{resource_id}_{version_id|draft}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial-imagery-site-alpha-v1-0 (or -draft before approval)
                        </p>
                    </div>
                </div>
            </div>

            <!-- Valid Containers -->
            <div class="section">
                <h2>Valid Input Containers</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    DDH can submit data from these Bronze tier containers:
                </p>
                <div id="bronze-containers" class="tag-list">
                    <span class="tag" style="background: #ccc;">Loading...</span>
                </div>
                <p id="bronze-account" style="font-size: 12px; color: #666; margin-top: 12px;"></p>
            </div>

            <!-- Access Levels -->
            <div class="section">
                <h2>Access Levels</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Data classification levels (for future APIM enforcement):
                </p>
                <div class="tag-list">
                    <span class="tag public">public</span>
                    <span class="tag ouo">OUO (Default)</span>
                    <span class="tag restricted">restricted</span>
                </div>
            </div>

            <!-- Platform API Endpoints -->
            <div class="section">
                <h2>Platform API Endpoints</h2>
                <table class="endpoint-table">
                    <thead>
                        <tr>
                            <th>Method</th>
                            <th>Endpoint</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- Submit/Status -->
                        <tr><td colspan="3" class="endpoint-group">Submit / Status</td></tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/submit</code></td>
                            <td>Submit DDH request (auto-detects raster/vector). <code>?dry_run=true</code> for validation.</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/status/{id}</code></td>
                            <td>Lookup by any ID (request, job, asset, release — auto-detected). <code>?detail=full</code></td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/status</code></td>
                            <td>List requests. Filter: <code>?dataset_id=X&amp;resource_id=Y</code> or <code>?limit=N</code></td>
                        </tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/validate</code></td>
                            <td>Pre-flight validation (same body as submit)</td>
                        </tr>
                        <!-- Approvals -->
                        <tr><td colspan="3" class="endpoint-group">Approvals</td></tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/approve</code></td>
                            <td>Approve pending dataset for publication</td>
                        </tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/reject</code></td>
                            <td>Reject pending dataset (reason required)</td>
                        </tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/revoke</code></td>
                            <td>Revoke approved dataset (reason required)</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/approvals</code></td>
                            <td>List approvals. Filter: <code>?status=&amp;classification=&amp;limit=</code></td>
                        </tr>
                        <!-- Catalog -->
                        <tr><td colspan="3" class="endpoint-group">Catalog</td></tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/catalog/lookup</code></td>
                            <td>Unified lookup by DDH IDs: <code>?dataset_id=&amp;resource_id=&amp;version_id=</code></td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/catalog/asset/{id}</code></td>
                            <td>Asset details + service URLs</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/catalog/dataset/{id}</code></td>
                            <td>All assets (raster + vector) for a DDH dataset</td>
                        </tr>
                        <!-- Operations -->
                        <tr><td colspan="3" class="endpoint-group">Operations</td></tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/unpublish</code></td>
                            <td>Unpublish by DDH IDs, request_id, or job_id. <code>?dry_run=true</code> (default)</td>
                        </tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/resubmit</code></td>
                            <td>Resubmit failed job with cleanup</td>
                        </tr>
                        <!-- Diagnostics -->
                        <tr><td colspan="3" class="endpoint-group">Diagnostics</td></tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/health</code></td>
                            <td>System readiness check (simplified for external apps)</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/failures</code></td>
                            <td>Recent failures with sanitized errors. <code>?hours=&amp;limit=</code></td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/lineage/{id}</code></td>
                            <td>Data lineage trace by request ID</td>
                        </tr>
                        <!-- Platform Registry -->
                        <tr><td colspan="3" class="endpoint-group">Platform Registry</td></tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platforms</code></td>
                            <td>List supported B2B platforms</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platforms/{id}</code></td>
                            <td>Platform details with required/optional refs</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- DDH Application Health (Placeholder) -->
            <div class="section">
                <h2>DDH Application Health</h2>
                <div class="status-card">
                    <span class="status-icon">🔮</span>
                    <div class="status-text">
                        <h4>Future Integration</h4>
                        <p>DDH health check URL will be configured here once available. This will show real-time status of the DDH application.</p>
                    </div>
                </div>
                <div style="margin-top: 16px; padding: 12px; background: #f8f9fa; border-radius: 4px;">
                    <code style="color: #666;">DDH_HEALTH_URL: Not configured</code>
                </div>
            </div>

            <!-- Request ID Generation -->
            <div class="section">
                <h2>Request ID Generation</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Platform generates deterministic, idempotent request IDs from DDH identifiers:
                </p>
                <div class="config-card">
                    <h3>Formula</h3>
                    <div class="config-value">SHA256(dataset_id | resource_id [| version_id])[:32]</div>
                    <p style="font-size: 12px; color: #666; margin-top: 8px;">
                        Same inputs always produce same request_id, enabling natural deduplication.
                        Draft mode omits version_id — one draft per dataset+resource.
                    </p>
                </div>
            </div>
        </div>
        """

    def _generate_js(self) -> str:
        """JavaScript for live status updates."""
        return """
        async function loadPlatformHealth() {
            const statusEl = document.getElementById('platform-status');
            const jobsEl = document.getElementById('jobs-count');
            const rateEl = document.getElementById('success-rate');

            try {
                const response = await fetch(`${API_BASE_URL}/api/platform/health`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();

                // Update status badge
                if (data.status === 'healthy') {
                    statusEl.className = 'live-status healthy';
                    statusEl.innerHTML = '<span class="pulse"></span> Healthy';
                } else {
                    statusEl.className = 'live-status error';
                    statusEl.innerHTML = '<span class="pulse"></span> ' + data.status;
                }

                // Update activity stats
                if (data.recent_activity) {
                    jobsEl.textContent = data.recent_activity.jobs_last_24h || '0';
                    rateEl.textContent = data.recent_activity.success_rate || 'N/A';
                }

            } catch (error) {
                console.error('Failed to load platform health:', error);
                statusEl.className = 'live-status error';
                statusEl.innerHTML = '<span class="pulse"></span> Error';
            }

            // V0.9 approval stats
            try {
                const approvalResp = await fetch(`${API_BASE_URL}/api/assets/approval-stats`);
                if (approvalResp.ok) {
                    const stats = await approvalResp.json();
                    const pendingEl = document.getElementById('pending-review-count');
                    if (pendingEl && stats.pending_review !== undefined) {
                        pendingEl.textContent = stats.pending_review;
                        if (stats.pending_review > 0) {
                            pendingEl.style.color = '#d97706';
                        }
                    }
                }
            } catch (e) {
                console.warn('Could not fetch approval stats:', e);
            }
        }

        // Load Bronze containers from storage API
        async function loadBronzeContainers() {
            const containersEl = document.getElementById('bronze-containers');
            const accountEl = document.getElementById('bronze-account');

            try {
                const response = await fetch(`${API_BASE_URL}/api/storage/containers?zone=bronze`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                const bronzeData = data.zones?.bronze;

                if (bronzeData && bronzeData.containers && bronzeData.containers.length > 0) {
                    // Build tags for each container
                    containersEl.innerHTML = bronzeData.containers
                        .map(name => `<span class="tag bronze">${name}</span>`)
                        .join('');

                    // Show storage account info
                    accountEl.textContent = `Storage Account: ${bronzeData.account} (${bronzeData.container_count} containers)`;
                } else if (bronzeData?.error) {
                    containersEl.innerHTML = `<span class="tag" style="background: #f8d7da; color: #721c24;">Error: ${escapeHtml(bronzeData.error)}</span>`;
                    accountEl.textContent = '';
                } else {
                    containersEl.innerHTML = '<span class="tag" style="background: #fff3cd; color: #856404;">No containers found</span>';
                    accountEl.textContent = '';
                }

            } catch (error) {
                console.error('Failed to load Bronze containers:', error);
                containersEl.innerHTML = `<span class="tag" style="background: #f8d7da; color: #721c24;">Failed to load containers</span>`;
                accountEl.textContent = '';
            }
        }

        // Status Lookup input switching
        function updateLookupInputs() {
            const lookupType = document.getElementById('lookup-type').value;
            const container = document.getElementById('lookup-inputs');

            const placeholders = {
                'request_id': 'Enter Request ID...',
                'job_id': 'Enter Job ID...',
                'asset_id': 'Enter Asset ID...',
                'release_id': 'Enter Release ID...',
            };

            if (lookupType === 'dataset_resource') {
                container.innerHTML = `
                    <input type="text" name="dataset_id" id="lookup-dataset"
                           placeholder="dataset_id" class="lookup-input lookup-input-half">
                    <input type="text" name="resource_id" id="lookup-resource"
                           placeholder="resource_id" class="lookup-input lookup-input-half">
                `;
            } else {
                container.innerHTML = `
                    <input type="text" name="lookup_id" id="lookup-id"
                           placeholder="${placeholders[lookupType] || 'Enter ID...'}"
                           class="lookup-input">
                `;
            }
        }

        // Load on page ready
        document.addEventListener('DOMContentLoaded', () => {
            loadPlatformHealth();
            loadBronzeContainers();
        });
        """
