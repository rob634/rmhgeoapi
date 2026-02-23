# ============================================================================
# CLAUDE CONTEXT - ASSET VERSIONS INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - V0.9 Asset/Release version visualization
# PURPOSE: Full lifecycle view of an Asset's releases with approval actions
# LAST_REVIEWED: 23 FEB 2026
# EXPORTS: AssetVersionsInterface
# DEPENDENCIES: web_interfaces.base
# ============================================================================
"""
Asset Versions Interface.

Displays an asset's release history in a table with expandable rows showing
details and approval action buttons. Each row represents an AssetRelease
with its version, processing status, approval state, and clearance state.

Routes:
    GET /api/interface/asset-versions?asset_id=XXX
    GET /api/interface/asset-versions?dataset_id=XXX&resource_id=YYY

The page loads data client-side from the Platform Status API:
    GET /api/platform/status/{asset_id}
    GET /api/platform/status?dataset_id=X&resource_id=Y
"""

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface


@InterfaceRegistry.register('asset-versions')
class AssetVersionsInterface(BaseInterface):
    """
    Asset versions interface showing release history with approval actions.

    Renders a table of all releases for an asset, sorted by version_ordinal
    descending (newest first). Each row expands to show release details and
    context-aware action buttons based on approval/processing state.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Render the asset versions page.

        Query parameters:
            asset_id: Direct asset lookup
            dataset_id + resource_id: Platform refs lookup

        Args:
            request: Azure Functions HTTP request

        Returns:
            Complete HTML page string
        """
        params = self.get_query_params(request)
        asset_id = params.get('asset_id', '')
        dataset_id = params.get('dataset_id', '')
        resource_id = params.get('resource_id', '')

        content = f"""
        <div class="av-container">
            <!-- Loading State -->
            <div id="av-loading" class="av-loading">
                <div class="av-spinner"></div>
                <p>Loading asset versions...</p>
            </div>

            <!-- Error State -->
            <div id="av-error" class="hidden">
                <div class="av-error-box">
                    <h2>Error Loading Asset</h2>
                    <p id="av-error-msg"></p>
                    <a href="/api/interface/home" class="btn btn-secondary btn-sm">Back to Home</a>
                </div>
            </div>

            <!-- Asset Header (filled by JS) -->
            <div id="av-header" class="hidden"></div>

            <!-- Versions Table (filled by JS) -->
            <div id="av-table-container" class="hidden"></div>
        </div>
        """

        return self.wrap_html(
            title="Asset Versions",
            content=content,
            custom_css=self._generate_custom_css(),
            custom_js=self._generate_custom_js(asset_id, dataset_id, resource_id),
        )

    def _generate_custom_css(self) -> str:
        """Asset versions page styles."""
        return """
            .av-container {
                max-width: 1100px;
                margin: 0 auto;
            }

            /* Loading spinner */
            .av-loading {
                text-align: center;
                padding: 60px 20px;
                color: var(--ds-gray);
            }
            .av-spinner {
                width: 40px;
                height: 40px;
                border: 4px solid var(--ds-gray-light);
                border-top-color: var(--ds-blue-primary);
                border-radius: 50%;
                animation: av-spin 0.8s linear infinite;
                margin: 0 auto 16px;
            }
            @keyframes av-spin {
                to { transform: rotate(360deg); }
            }

            /* Error box */
            .av-error-box {
                background: white;
                border: 2px solid var(--ds-status-failed-fg);
                border-radius: 8px;
                padding: 30px;
                text-align: center;
                max-width: 500px;
                margin: 40px auto;
            }
            .av-error-box h2 {
                color: var(--ds-status-failed-fg);
                margin-bottom: 12px;
            }
            .av-error-box p {
                color: var(--ds-gray);
                margin-bottom: 16px;
            }

            /* Versions table */
            .av-table {
                width: 100%;
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                border-collapse: collapse;
            }
            .av-table thead {
                background: var(--ds-navy);
            }
            .av-table thead th {
                padding: 12px 16px;
                text-align: left;
                font-size: 0.8rem;
                font-weight: 600;
                color: white;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                border: none;
            }
            .av-table tbody tr.av-row {
                cursor: pointer;
                transition: background 0.15s;
                border-bottom: 1px solid #e5e7eb;
            }
            .av-table tbody tr.av-row:hover {
                background: #f0f7ff;
            }
            .av-table tbody tr.av-row td {
                padding: 10px 16px;
                font-size: 0.85rem;
                vertical-align: middle;
            }

            /* Expand arrow */
            .av-expand {
                display: inline-block;
                transition: transform 0.2s;
                font-size: 0.75rem;
                color: var(--ds-gray);
            }
            .av-expand.open {
                transform: rotate(90deg);
            }

            /* Detail row */
            .av-detail {
                display: none;
            }
            .av-detail.open {
                display: table-row;
            }
            .av-detail td {
                padding: 0 !important;
                border-bottom: 2px solid var(--ds-blue-primary);
            }
            .av-detail-inner {
                padding: 20px 24px;
                border-left: 3px solid var(--ds-blue-primary);
                margin: 0 12px 12px 12px;
                background: #fafbfc;
                border-radius: 0 0 6px 6px;
            }

            /* Detail grid */
            .av-detail-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px 32px;
                margin-bottom: 16px;
            }
            .av-detail-grid .av-field {
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .av-detail-grid .av-label {
                font-size: 0.7rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                color: var(--ds-gray);
            }
            .av-detail-grid .av-value {
                font-size: 0.85rem;
                color: var(--ds-navy);
                font-family: monospace;
                word-break: break-all;
            }

            /* Action buttons row */
            .av-actions {
                display: flex;
                flex-direction: row;
                gap: 8px;
                padding-top: 12px;
                border-top: 1px solid #e5e7eb;
                flex-wrap: wrap;
            }

            .av-actions .btn {
                font-size: 12px;
                padding: 6px 14px;
            }

            .btn-approve {
                background: var(--ds-approval-approved-bg);
                color: var(--ds-approval-approved-fg);
                border-color: var(--ds-approval-approved-fg);
            }
            .btn-approve:hover {
                background: var(--ds-approval-approved-fg);
                color: white;
            }
            .btn-reject {
                background: var(--ds-approval-rejected-bg);
                color: var(--ds-approval-rejected-fg);
                border-color: var(--ds-approval-rejected-fg);
            }
            .btn-reject:hover {
                background: var(--ds-approval-rejected-fg);
                color: white;
            }
            .btn-revoke {
                background: var(--ds-approval-revoked-bg);
                color: var(--ds-approval-revoked-fg);
                border-color: var(--ds-approval-revoked-fg);
            }
            .btn-revoke:hover {
                background: var(--ds-approval-revoked-fg);
                color: white;
            }

            /* Empty state */
            .av-empty {
                text-align: center;
                padding: 40px;
                color: var(--ds-gray);
                background: white;
                border-radius: 8px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            }

            /* Latest star in table */
            .av-latest-star {
                color: var(--ds-gold);
                font-size: 0.9rem;
                margin-left: 4px;
            }
        """

    def _generate_custom_js(self, asset_id: str, dataset_id: str, resource_id: str) -> str:
        """Asset versions page JavaScript."""
        return f"""
        // Query params injected from server
        const ASSET_ID = '{asset_id}';
        const DATASET_ID = '{dataset_id}';
        const RESOURCE_ID = '{resource_id}';

        // Current expanded row
        let currentOpenRow = null;

        // ============================================================
        // Page load
        // ============================================================
        document.addEventListener('DOMContentLoaded', function() {{
            loadAssetVersions();
        }});

        // ============================================================
        // Data loading
        // ============================================================
        async function loadAssetVersions() {{
            try {{
                let url;
                if (ASSET_ID) {{
                    url = API_BASE_URL + '/api/platform/status/' + ASSET_ID;
                }} else if (DATASET_ID && RESOURCE_ID) {{
                    url = API_BASE_URL + '/api/platform/status?dataset_id=' + encodeURIComponent(DATASET_ID) + '&resource_id=' + encodeURIComponent(RESOURCE_ID);
                }} else {{
                    throw new Error('No asset_id or dataset_id+resource_id provided. Use ?asset_id=XXX or ?dataset_id=XXX&resource_id=YYY');
                }}

                const resp = await fetch(url);
                const data = await resp.json();

                if (!resp.ok || !data.success) {{
                    throw new Error(data.error || 'Failed to load asset data');
                }}

                // Hide loading, show content
                document.getElementById('av-loading').classList.add('hidden');

                if (!data.asset) {{
                    throw new Error('No asset data in response');
                }}

                // Render header
                const headerEl = document.getElementById('av-header');
                headerEl.innerHTML = renderAssetHeader(data.asset);
                headerEl.classList.remove('hidden');

                // Render table
                const tableEl = document.getElementById('av-table-container');
                const versions = data.versions || [];
                tableEl.innerHTML = renderVersionsTable(versions, data.asset, data.services, data.approval);
                tableEl.classList.remove('hidden');

            }} catch (err) {{
                document.getElementById('av-loading').classList.add('hidden');
                document.getElementById('av-error-msg').textContent = err.message;
                document.getElementById('av-error').classList.remove('hidden');
            }}
        }}

        // ============================================================
        // Renderers
        // ============================================================

        function renderAssetHeader(asset) {{
            return `
                <div class="asset-header">
                    <div class="asset-title">${{asset.dataset_id}} / ${{asset.resource_id}}</div>
                    <div class="asset-meta">
                        <span>Type: <code>${{asset.data_type || 'unknown'}}</code></span>
                        <span>Asset: <code>${{asset.asset_id ? asset.asset_id.substring(0, 16) + '...' : '--'}}</code></span>
                        <span>Releases: <strong>${{asset.release_count || 0}}</strong></span>
                    </div>
                </div>
            `;
        }}

        function renderVersionChip(v) {{
            if (!v.version_id) {{
                return '<span class="version-chip version-draft">draft</span>';
            }}
            const latestStar = v.is_latest ? '<span class="latest-star">&#9733;</span>' : '';
            return `<span class="version-chip">${{v.version_id}}${{latestStar}}</span>`;
        }}

        function renderProcessingBadge(status) {{
            const s = (status || 'unknown').toLowerCase();
            return `<span class="status-badge status-${{s}}">${{s}}</span>`;
        }}

        function renderApprovalBadge(state) {{
            const s = (state || 'unknown').toLowerCase();
            const label = s.replace('_', ' ');
            return `<span class="approval-badge approval-${{s}}">${{label}}</span>`;
        }}

        function renderClearanceBadge(state) {{
            const s = (state || 'uncleared').toLowerCase();
            return `<span class="clearance-badge clearance-${{s}}">${{s}}</span>`;
        }}

        function renderVersionsTable(versions, asset, services, approval) {{
            if (!versions || versions.length === 0) {{
                return '<div class="av-empty"><p>No releases found for this asset.</p></div>';
            }}

            // Sort by version_ordinal descending (newest first)
            const sorted = [...versions].sort((a, b) => (b.version_ordinal || 0) - (a.version_ordinal || 0));

            let rows = '';
            sorted.forEach((v, idx) => {{
                const rowId = 'av-row-' + idx;
                rows += `
                    <tr class="av-row" onclick="toggleDetail('${{rowId}}')">
                        <td>${{v.version_ordinal != null ? v.version_ordinal : '--'}}</td>
                        <td>${{renderVersionChip(v)}}</td>
                        <td>${{renderProcessingBadge(v.processing_status)}}</td>
                        <td>${{renderApprovalBadge(v.approval_state)}}</td>
                        <td>${{renderClearanceBadge(v.clearance_state)}}</td>
                        <td>${{v.revision != null ? v.revision : '0'}}</td>
                        <td><span class="av-expand" id="arrow-${{rowId}}">&#9654;</span></td>
                    </tr>
                    <tr class="av-detail" id="${{rowId}}">
                        <td colspan="7">
                            <div class="av-detail-inner">
                                ${{renderDetailContent(v, asset, services, approval)}}
                            </div>
                        </td>
                    </tr>
                `;
            }});

            return `
                <table class="av-table">
                    <thead>
                        <tr>
                            <th>Ord</th>
                            <th>Version</th>
                            <th>Processing</th>
                            <th>Approval</th>
                            <th>Clearance</th>
                            <th>Rev</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        ${{rows}}
                    </tbody>
                </table>
            `;
        }}

        function renderDetailContent(v, asset, services, approval) {{
            // Detail fields
            let grid = `
                <div class="av-detail-grid">
                    <div class="av-field">
                        <span class="av-label">Release ID</span>
                        <span class="av-value">${{v.release_id || '--'}}</span>
                    </div>
                    <div class="av-field">
                        <span class="av-label">Created</span>
                        <span class="av-value">${{formatDateTime(v.created_at)}}</span>
                    </div>
            `;

            // Physical outputs
            if (v.blob_path) {{
                grid += `
                    <div class="av-field">
                        <span class="av-label">Blob Path</span>
                        <span class="av-value">${{v.blob_path}}</span>
                    </div>
                `;
            }}
            if (v.table_name) {{
                grid += `
                    <div class="av-field">
                        <span class="av-label">Table Name</span>
                        <span class="av-value">${{v.table_name}}</span>
                    </div>
                `;
            }}
            if (v.stac_item_id) {{
                grid += `
                    <div class="av-field">
                        <span class="av-label">STAC Item ID</span>
                        <span class="av-value">${{v.stac_item_id}}</span>
                    </div>
                `;
            }}
            if (v.stac_collection_id) {{
                grid += `
                    <div class="av-field">
                        <span class="av-label">STAC Collection ID</span>
                        <span class="av-value">${{v.stac_collection_id}}</span>
                    </div>
                `;
            }}

            grid += '</div>';

            // Action buttons (context-aware)
            const actions = renderActions(v, asset, services, approval);

            return grid + actions;
        }}

        function renderActions(v, asset, services, approval) {{
            const assetId = asset ? asset.asset_id : null;
            if (!assetId) return '';

            const approvalState = (v.approval_state || '').toLowerCase();
            const procStatus = (v.processing_status || '').toLowerCase();

            let buttons = '';

            if (approvalState === 'pending_review' && procStatus === 'completed') {{
                // Actionable: approve, reject, preview
                buttons += `<button class="btn btn-approve" onclick="event.stopPropagation(); approveRelease('${{assetId}}')">Approve</button>`;
                buttons += `<button class="btn btn-reject" onclick="event.stopPropagation(); rejectRelease('${{assetId}}')">Reject</button>`;

                // Preview link based on data type
                if (asset.data_type === 'raster' && v.stac_item_id) {{
                    buttons += `<a class="btn btn-secondary" href="/api/interface/raster-viewer?item_id=${{v.stac_item_id}}&asset_id=${{assetId}}" target="_blank" onclick="event.stopPropagation()">Preview</a>`;
                }} else if (asset.data_type === 'vector' && v.table_name) {{
                    buttons += `<a class="btn btn-secondary" href="/api/interface/vector-viewer?collection=${{v.table_name}}&asset_id=${{assetId}}" target="_blank" onclick="event.stopPropagation()">Preview</a>`;
                }}
            }} else if (approvalState === 'approved') {{
                // Approved: revoke, view in STAC, raster viewer
                buttons += `<button class="btn btn-revoke" onclick="event.stopPropagation(); revokeRelease('${{assetId}}')">Revoke</button>`;

                if (v.stac_collection_id && v.stac_item_id) {{
                    buttons += `<a class="btn btn-secondary" href="/api/interface/stac-collection?collection=${{v.stac_collection_id}}" target="_blank" onclick="event.stopPropagation()">View in STAC</a>`;
                }}
                if (asset.data_type === 'raster' && v.stac_item_id) {{
                    buttons += `<a class="btn btn-secondary" href="/api/interface/raster-viewer?item_id=${{v.stac_item_id}}" target="_blank" onclick="event.stopPropagation()">Raster Viewer</a>`;
                }}
            }}
            // Other states: read-only (no buttons)

            if (!buttons) {{
                return '<div class="av-actions"><span style="color: var(--ds-gray); font-size: 0.8rem;">No actions available for this state</span></div>';
            }}

            return '<div class="av-actions">' + buttons + '</div>';
        }}

        // ============================================================
        // Expand / Collapse
        // ============================================================
        function toggleDetail(rowId) {{
            const detailRow = document.getElementById(rowId);
            const arrow = document.getElementById('arrow-' + rowId);
            if (!detailRow) return;

            if (detailRow.classList.contains('open')) {{
                // Collapse
                detailRow.classList.remove('open');
                if (arrow) arrow.classList.remove('open');
                currentOpenRow = null;
            }} else {{
                // Collapse previously open row (accordion)
                if (currentOpenRow && currentOpenRow !== rowId) {{
                    const prevRow = document.getElementById(currentOpenRow);
                    const prevArrow = document.getElementById('arrow-' + currentOpenRow);
                    if (prevRow) prevRow.classList.remove('open');
                    if (prevArrow) prevArrow.classList.remove('open');
                }}
                // Expand this row
                detailRow.classList.add('open');
                if (arrow) arrow.classList.add('open');
                currentOpenRow = rowId;
            }}
        }}

        // ============================================================
        // Approval Actions
        // ============================================================
        async function approveRelease(assetId) {{
            const reviewer = prompt('Reviewer email:');
            if (!reviewer) return;

            const clearance = prompt('Clearance level (ouo / public):', 'ouo');
            if (!clearance) return;
            if (clearance !== 'ouo' && clearance !== 'public') {{
                alert('Invalid clearance. Must be "ouo" or "public".');
                return;
            }}

            try {{
                const resp = await fetch(API_BASE_URL + '/api/assets/' + assetId + '/approve', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        reviewer: reviewer,
                        clearance_state: clearance
                    }})
                }});
                const data = await resp.json();
                if (data.success) {{
                    alert('Release approved successfully.');
                    loadAssetVersions();
                }} else {{
                    alert('Approval failed: ' + (data.error || 'Unknown error'));
                }}
            }} catch (err) {{
                alert('Error: ' + err.message);
            }}
        }}

        async function rejectRelease(assetId) {{
            const reviewer = prompt('Reviewer email:');
            if (!reviewer) return;

            const reason = prompt('Rejection reason:');
            if (!reason) return;

            try {{
                const resp = await fetch(API_BASE_URL + '/api/assets/' + assetId + '/reject', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        reviewer: reviewer,
                        reason: reason
                    }})
                }});
                const data = await resp.json();
                if (data.success) {{
                    alert('Release rejected.');
                    loadAssetVersions();
                }} else {{
                    alert('Rejection failed: ' + (data.error || 'Unknown error'));
                }}
            }} catch (err) {{
                alert('Error: ' + err.message);
            }}
        }}

        async function revokeRelease(assetId) {{
            const revoker = prompt('Revoker email:');
            if (!revoker) return;

            const reason = prompt('Revocation reason:');
            if (!reason) return;

            if (!confirm('Are you sure you want to revoke this approved release? This action is logged for audit.')) {{
                return;
            }}

            try {{
                const resp = await fetch(API_BASE_URL + '/api/assets/' + assetId + '/revoke', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        revoker: revoker,
                        reason: reason
                    }})
                }});
                const data = await resp.json();
                if (data.success) {{
                    alert('Release revoked successfully.');
                    loadAssetVersions();
                }} else {{
                    alert('Revocation failed: ' + (data.error || 'Unknown error'));
                }}
            }} catch (err) {{
                alert('Error: ' + err.message);
            }}
        }}
        """


# Module-level singleton for auto-import registration
interface = AssetVersionsInterface()
