"""
OGC Features interface module.

Web dashboard for browsing OGC API - Features collections with metadata and API endpoints.

Features (24 DEC 2025 - S12.3.3):
    - HTMX enabled for future partial updates
    - Uses COMMON_CSS and COMMON_JS utilities

Updated (23 JAN 2026 - TiPG Standardization):
    - Collections fetched from TiPG (high-performance Docker endpoint)
    - Internal OGC Features API reserved for emergency backup only
    - Schema-qualified collection IDs (geo.{table_name}) for TiPG

Exports:
    VectorInterface: OGC Features collections browser with clickable cards and spatial extents
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
from config import get_config


@InterfaceRegistry.register('vector')
class VectorInterface(BaseInterface):
    """
    OGC Features Collections Dashboard interface.

    Displays OGC API - Features collections in grid format with clickable
    cards that open the collection's API endpoint.

    Updated 23 JAN 2026: Uses TiPG as primary endpoint for collections.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate OGC Features dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        # Get TiPG base URL from config (23 JAN 2026)
        try:
            config = get_config()
            tipg_base_url = config.tipg_base_url.rstrip('/')
        except Exception:
            # Fallback for local dev
            tipg_base_url = 'https://rmhtitiler-ckdxapgkg4e2gtfp.eastus-01.azurewebsites.net/vector'

        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js(tipg_base_url)

        return self.wrap_html(
            title="OGC Features Collections",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content structure."""
        return """
        <div class="container">
            <!-- Header with count -->
            <header class="dashboard-header header-with-count">
                <div class="header-left">
                    <h1>📐 OGC Features</h1>
                </div>
                <div class="header-right">
                    <span class="collection-count" id="total-collections">Loading...</span>
                </div>
            </header>

            <!-- Action Bar -->
            <div class="action-bar">
                <a href="/api/interface/submit-vector" class="btn btn-primary">
                    ➕ Create New Feature Collection
                </a>
                <input
                    type="text"
                    id="search-filter"
                    placeholder="Search collections..."
                    onkeyup="filterCollections()"
                    class="search-input"
                />
            </div>

            <!-- Loading State -->
            <div id="loading-spinner" class="spinner"></div>

            <!-- Collections Grid -->
            <div id="collections-grid" class="collections-grid">
                <!-- Collections will be inserted here -->
            </div>

            <!-- Empty State -->
            <div id="empty-state" class="empty-state hidden">
                <div class="icon">📦</div>
                <h3>No Collections Found</h3>
                <p>No OGC Features collections are available</p>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for OGC Features dashboard.

        Note: Most styles now in COMMON_CSS (S12.1.1).
        Header/action-bar consolidated S12.5.1-S12.5.2 (08 JAN 2026).
        Only vector-specific styles remain here.

        Updated 30 DEC 2025: Smaller cards, 4 per row, promoted badges, delete buttons.
        """
        return """
        /* Smaller cards - 4 per row */
        .collections-grid {
            grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)) !important;
            gap: 12px !important;
        }

        .collection-card {
            padding: 12px !important;
            cursor: pointer;
            position: relative;
        }

        .collection-card h3 {
            font-size: 13px !important;
            margin-bottom: 6px !important;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .collection-card .description {
            font-size: 11px;
            max-height: 32px;
            overflow: hidden;
            text-overflow: ellipsis;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            color: var(--ds-gray);
            margin-bottom: 8px;
        }

        /* Vector-specific: Card meta section with border */
        .collection-card .meta {
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid var(--ds-gray-light);
            color: var(--ds-gray);
            font-size: 11px;
        }

        .collection-card .meta-item {
            display: flex;
            align-items: center;
            gap: 4px;
            margin-bottom: 2px;
        }

        .collection-card .feature-count {
            color: var(--ds-blue-primary);
            font-weight: 600;
        }

        .collection-card .bbox {
            font-family: 'Courier New', monospace;
            font-size: 10px;
            color: var(--ds-gray);
        }

        .collection-card .links {
            margin-top: 8px;
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }

        .collection-card .link-badge {
            font-size: 11px !important;
            padding: 3px 8px !important;
        }

        /* Promoted badge */
        .promoted-badge {
            display: inline-block;
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            color: white;
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            margin-bottom: 6px;
        }

        /* Approved badge (17 JAN 2026) */
        .approved-badge {
            display: inline-block;
            background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%);
            color: white;
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            margin-bottom: 6px;
            margin-right: 4px;
        }

        /* Disabled/protected button (17 JAN 2026) */
        .link-badge-disabled {
            background: linear-gradient(135deg, #9CA3AF 0%, #6B7280 100%) !important;
            color: white !important;
            cursor: not-allowed !important;
            opacity: 0.7;
        }

        /* Tiles button (13 JAN 2026) */
        .link-badge-tiles {
            background: linear-gradient(135deg, #8B5CF6 0%, #7C3AED 100%) !important;
            color: white !important;
            border-color: #7C3AED !important;
        }

        .link-badge-tiles:hover {
            background: linear-gradient(135deg, #7C3AED 0%, #6D28D9 100%) !important;
        }

        /* Promote button */
        .link-badge-promote {
            background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
            color: white !important;
            border-color: #059669 !important;
        }

        .link-badge-promote:hover {
            background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
        }

        /* Delete button */
        .link-badge-delete {
            background: linear-gradient(135deg, #EF4444 0%, #DC2626 100%) !important;
            color: white !important;
            border-color: #DC2626 !important;
        }

        .link-badge-delete:hover {
            background: linear-gradient(135deg, #DC2626 0%, #B91C1C 100%) !important;
        }

        /* Modal overlay */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.6);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
        }

        .modal-content {
            background: white;
            border-radius: 8px;
            max-width: 700px;
            max-height: 80vh;
            overflow-y: auto;
            padding: 24px;
            position: relative;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
        }

        .modal-close {
            position: absolute;
            top: 12px;
            right: 12px;
            background: none;
            border: none;
            font-size: 24px;
            cursor: pointer;
            color: var(--ds-gray);
        }

        .modal-close:hover {
            color: var(--ds-blue-primary);
        }

        .modal-content h2 {
            margin-bottom: 16px;
            padding-right: 30px;
        }

        .modal-section {
            margin-bottom: 16px;
        }

        .modal-section h4 {
            color: var(--ds-gray);
            font-size: 12px;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .modal-section pre {
            background: var(--ds-gray-lighter);
            padding: 12px;
            border-radius: 4px;
            font-size: 11px;
            overflow-x: auto;
        }

        .modal-links {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 16px;
        }

        /* Confirm/Alert modal specific styles */
        .modal-content.modal-confirm {
            max-width: 400px;
            text-align: center;
        }

        .modal-confirm .modal-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .modal-confirm .modal-message {
            color: var(--ds-gray);
            margin-bottom: 20px;
            line-height: 1.5;
        }

        .modal-confirm .modal-buttons {
            display: flex;
            gap: 12px;
            justify-content: center;
        }

        .modal-confirm .btn-danger {
            background: linear-gradient(135deg, #EF4444 0%, #DC2626 100%);
            color: white;
            border: none;
            padding: 10px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }

        .modal-confirm .btn-danger:hover {
            background: linear-gradient(135deg, #DC2626 0%, #B91C1C 100%);
        }

        .modal-confirm .btn-cancel {
            background: var(--ds-gray-lighter);
            color: var(--ds-gray-dark);
            border: 1px solid var(--ds-gray-light);
            padding: 10px 24px;
            border-radius: 6px;
            cursor: pointer;
        }

        .modal-confirm .btn-cancel:hover {
            background: var(--ds-gray-light);
        }

        .modal-content.modal-success {
            max-width: 450px;
            text-align: center;
        }

        .modal-success .modal-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .modal-success .modal-details {
            background: var(--ds-gray-lighter);
            padding: 12px;
            border-radius: 6px;
            margin: 16px 0;
            text-align: left;
        }

        .modal-success .detail-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 6px;
        }

        .modal-success .detail-label {
            color: var(--ds-gray);
            font-size: 12px;
        }

        .modal-success .detail-value {
            font-family: monospace;
            font-size: 12px;
        }

        /* CURL Confirmation Modal */
        .modal-content.modal-curl {
            max-width: 650px;
            text-align: left;
        }

        .modal-curl .modal-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
        }

        .modal-curl .modal-icon {
            font-size: 32px;
        }

        .modal-curl .modal-header h3 {
            margin: 0;
            color: var(--ds-navy);
        }

        .modal-curl .modal-warning {
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 16px;
            color: #92400E;
            font-size: 13px;
        }

        .modal-curl .curl-section {
            background: #1e293b;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }

        .modal-curl .curl-section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .modal-curl .curl-title {
            color: #e2e8f0;
            font-weight: 600;
            font-size: 13px;
        }

        .modal-curl .btn-copy {
            background: #334155;
            border: 1px solid #475569;
            color: #e2e8f0;
            padding: 4px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }

        .modal-curl .btn-copy:hover {
            background: var(--ds-blue-primary);
            border-color: var(--ds-blue-primary);
        }

        .modal-curl .curl-code {
            background: #0f172a;
            color: #e2e8f0;
            padding: 12px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
            margin: 0;
            max-height: 200px;
        }

        .modal-curl .modal-buttons {
            display: flex;
            justify-content: flex-end;
            gap: 12px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--ds-gray-light);
        }
        """

    def _generate_custom_js(self, tipg_base_url: str) -> str:
        """Generate custom JavaScript for OGC Features dashboard.

        Updated 30 DEC 2025: Fetch promoted datasets, conditional buttons, delete, modal.
        Updated 23 JAN 2026: Use TiPG as primary endpoint for collections.

        Args:
            tipg_base_url: TiPG base URL for OGC Features (e.g., https://titiler.../vector)
        """
        # Inject TiPG URL at start, keep rest as plain string to avoid escaping issues
        return """
        // State
        let allCollections = [];
        let promotedCollectionIds = new Set();

        // TiPG endpoint for high-performance OGC Features (23 JAN 2026)
        const TIPG_BASE_URL = '""" + tipg_base_url + """';

        // Load collections on page load
        document.addEventListener('DOMContentLoaded', loadCollections);

        // Load collections from TiPG API (23 JAN 2026 - standardized to TiPG)
        async function loadCollections() {
            const grid = document.getElementById('collections-grid');
            const spinner = document.getElementById('loading-spinner');
            const emptyState = document.getElementById('empty-state');
            const countDisplay = document.getElementById('total-collections');

            // Show loading
            grid.innerHTML = '';
            spinner.classList.remove('hidden');
            emptyState.classList.add('hidden');
            countDisplay.textContent = 'Loading...';

            try {
                // Fetch collections from TiPG and promoted datasets in parallel
                // TiPG is the primary endpoint; Function App is emergency backup only
                const [collectionsData, promotedData] = await Promise.all([
                    fetchJSON(`${TIPG_BASE_URL}/collections`),
                    fetchJSON(`${API_BASE_URL}/api/promote`).catch(() => ({ data: [] }))
                ]);

                allCollections = collectionsData.collections || [];

                // Build Set of promoted collection IDs
                promotedCollectionIds = new Set(
                    (promotedData.data || []).map(p => p.stac_collection_id)
                );

                // Helper: Extract table name from schema-qualified ID (geo.table_name -> table_name)
                // TiPG returns schema-qualified IDs but other APIs use just the table name
                const getTableName = (id) => id.includes('.') ? id.split('.').pop() : id;

                // Fetch approval statuses for all collections (17 JAN 2026)
                if (allCollections.length > 0) {
                    // Use table names (without schema) for approval API
                    const tableNames = allCollections.map(c => getTableName(c.id)).join(',');
                    try {
                        const approvalData = await fetchJSON(
                            `${API_BASE_URL}/api/platform/approvals/status?table_names=${encodeURIComponent(tableNames)}`
                        );
                        window.approvalStatuses = approvalData.statuses || {};
                    } catch (e) {
                        console.warn('Could not fetch approval statuses:', e);
                        window.approvalStatuses = {};
                    }
                }

                spinner.classList.add('hidden');

                if (allCollections.length === 0) {
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Update count in header
                countDisplay.textContent = `${allCollections.length} Collections`;

                // Render collections
                renderCollections(allCollections);

            } catch (error) {
                console.error('Error loading collections:', error);
                spinner.classList.add('hidden');
                emptyState.classList.remove('hidden');
            }
        }

        // Helper: Extract table name from schema-qualified ID (geo.table -> table)
        const getTableName = (id) => id.includes('.') ? id.split('.').pop() : id;

        // Render collections grid
        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');

            grid.innerHTML = collections.map(c => {
                // Get table name without schema for lookups and links
                const tableName = getTableName(c.id);

                // Extract feature count from description
                const desc = c.description || 'No description available';
                const featureCount = desc.match(/\\((\\d+) features\\)/);
                const count = featureCount ? parseInt(featureCount[1]).toLocaleString() : 'Unknown';

                // Get bbox if available
                const bbox = c.extent?.spatial?.bbox?.[0];
                const bboxStr = bbox ?
                    `[${bbox.map(v => v.toFixed(2)).join(', ')}]` :
                    'No extent';

                // Get links - use table name (without schema) for internal links
                const selfLink = c.links?.find(l => l.rel === 'self')?.href || '';
                const viewerLink = `${API_BASE_URL}/api/vector/viewer?collection=${encodeURIComponent(tableName)}`;
                const promoteLink = `/api/interface/promote-vector?collection=${encodeURIComponent(tableName)}`;

                // Check if promoted (use table name for lookup)
                const isPromoted = promotedCollectionIds.has(tableName);
                const title = c.title || tableName;

                // Check approval status (17 JAN 2026) - use table name for lookup
                const approvalStatus = window.approvalStatuses?.[tableName] || {};
                const isApproved = approvalStatus.is_approved === true;

                // Build action buttons (13 JAN 2026: Added Vector Tiles viewer)
                // Note: Tiles viewer handles schema qualification internally
                const tilesLink = `/api/interface/vector-tiles?collection=${encodeURIComponent(tableName)}`;
                let actionButtons = `
                    <a href="${viewerLink}"
                       class="link-badge link-badge-primary"
                       onclick="event.stopPropagation()"
                       target="_blank"
                       title="Leaflet + GeoJSON viewer">
                        🗺️ Map
                    </a>
                    <a href="${tilesLink}"
                       class="link-badge link-badge-tiles"
                       onclick="event.stopPropagation()"
                       target="_blank"
                       title="MapLibre + MVT tiles (better for large datasets)">
                        🧱 Tiles
                    </a>`;

                if (isPromoted) {
                    // No action buttons for promoted - just view
                } else if (isApproved) {
                    // Approved: Show promote but NO delete button (17 JAN 2026)
                    actionButtons += `
                        <a href="${promoteLink}"
                           class="link-badge link-badge-promote"
                           onclick="event.stopPropagation()"
                           title="Promote to gallery with styling">
                            ⬆️ Promote
                        </a>
                        <span class="link-badge link-badge-disabled"
                              title="Cannot delete: Dataset is approved. Use /api/platform/revoke first.">
                            🔒 Protected
                        </span>`;
                } else {
                    // Not promoted, not approved: Show promote and delete buttons
                    actionButtons += `
                        <a href="${promoteLink}"
                           class="link-badge link-badge-promote"
                           onclick="event.stopPropagation()"
                           title="Promote to gallery with styling">
                            ⬆️ Promote
                        </a>
                        <button class="link-badge link-badge-delete"
                                onclick="deleteCollection('${tableName}', event)"
                                title="Delete this collection (unpublish)">
                            🗑️ Delete
                        </button>`;
                }

                return `
                    <div class="collection-card" onclick="showCollectionDetail('${c.id}', '${tableName}', event)" title="${title}">
                        ${isApproved ? '<span class="approved-badge">✓ Approved</span>' : ''}
                        ${isPromoted ? '<span class="promoted-badge">⭐ Promoted</span>' : ''}
                        <h3>${title}</h3>
                        <div class="description">${desc}</div>

                        <div class="meta">
                            <div class="meta-item">
                                <span>📊</span>
                                <span class="feature-count">${count} features</span>
                            </div>
                            <div class="meta-item">
                                <span>🗺️</span>
                                <span class="bbox">${bboxStr}</span>
                            </div>
                        </div>

                        <div class="links">
                            ${actionButtons}
                        </div>
                    </div>
                `;
            }).join('');
        }

        // filterCollections() now in COMMON_JS (S12.5.4 - 08 JAN 2026)

        // Show collection detail modal (23 JAN 2026: Uses TiPG with schema-qualified ID)
        async function showCollectionDetail(tipgId, tableName, event) {
            // Don't open modal if clicking links/buttons
            if (event.target.tagName === 'A' || event.target.tagName === 'BUTTON') {
                return;
            }

            try {
                // Fetch from TiPG using schema-qualified ID
                const data = await fetchJSON(`${TIPG_BASE_URL}/collections/${encodeURIComponent(tipgId)}`);

                const selfLink = data.links?.find(l => l.rel === 'self')?.href || '';
                const itemsLink = data.links?.find(l => l.rel === 'items')?.href || '';
                const viewerLink = `${API_BASE_URL}/api/vector/viewer?collection=${encodeURIComponent(tableName)}`;

                // Format extent
                const bbox = data.extent?.spatial?.bbox?.[0];
                const bboxStr = bbox ? `[${bbox.map(v => v.toFixed(4)).join(', ')}]` : 'Not available';

                // Format temporal extent
                const temporal = data.extent?.temporal?.interval?.[0];
                const temporalStr = temporal ? `${temporal[0] || 'Unknown'} to ${temporal[1] || 'Present'}` : 'Not available';

                const modal = document.createElement('div');
                modal.className = 'modal-overlay';
                modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
                modal.innerHTML = `
                    <div class="modal-content">
                        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">&times;</button>
                        <h2>${data.title || data.id}</h2>

                        <div class="modal-section">
                            <h4>Description</h4>
                            <p>${data.description || 'No description available'}</p>
                        </div>

                        <div class="modal-section">
                            <h4>Collection ID</h4>
                            <code>${data.id}</code>
                        </div>

                        <div class="modal-section">
                            <h4>Spatial Extent (BBOX)</h4>
                            <code>${bboxStr}</code>
                        </div>

                        <div class="modal-section">
                            <h4>Temporal Extent</h4>
                            <code>${temporalStr}</code>
                        </div>

                        <div class="modal-section">
                            <h4>CRS</h4>
                            <code>${(data.crs || ['Unknown']).join(', ')}</code>
                        </div>

                        <div class="modal-links">
                            <a href="${viewerLink}" class="link-badge link-badge-primary" target="_blank">🗺️ View Map</a>
                            <a href="${selfLink}" class="link-badge" target="_blank">🔗 Collection JSON</a>
                            <a href="${itemsLink}" class="link-badge" target="_blank">📄 Items GeoJSON</a>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            } catch (error) {
                console.error('Error loading collection detail:', error);
                alert('Failed to load collection details');
            }
        }

        // Show confirmation modal - returns Promise that resolves to true/false
        function showConfirmModal(title, message, confirmText = 'Delete', icon = '⚠️') {
            return new Promise((resolve) => {
                const modal = document.createElement('div');
                modal.className = 'modal-overlay';
                modal.innerHTML = `
                    <div class="modal-content modal-confirm">
                        <div class="modal-icon">${icon}</div>
                        <h3>${title}</h3>
                        <p class="modal-message">${message}</p>
                        <div class="modal-buttons">
                            <button class="btn-cancel" onclick="this.closest('.modal-overlay').remove(); window._confirmResolve(false);">Cancel</button>
                            <button class="btn-danger" onclick="this.closest('.modal-overlay').remove(); window._confirmResolve(true);">${confirmText}</button>
                        </div>
                    </div>
                `;
                window._confirmResolve = resolve;
                document.body.appendChild(modal);
            });
        }

        // Show success/info modal
        function showResultModal(title, message, details = null, icon = '✅') {
            const modal = document.createElement('div');
            modal.className = 'modal-overlay';
            modal.onclick = (e) => { if (e.target === modal) modal.remove(); };

            let detailsHtml = '';
            if (details) {
                detailsHtml = `<div class="modal-details">
                    ${Object.entries(details).map(([k, v]) => `
                        <div class="detail-row">
                            <span class="detail-label">${k}</span>
                            <span class="detail-value">${v}</span>
                        </div>
                    `).join('')}
                </div>`;
            }

            modal.innerHTML = `
                <div class="modal-content modal-success">
                    <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">&times;</button>
                    <div class="modal-icon">${icon}</div>
                    <h3>${title}</h3>
                    <p class="modal-message">${message}</p>
                    ${detailsHtml}
                    <button class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">OK</button>
                </div>
            `;
            document.body.appendChild(modal);
        }

        // Show CURL confirmation modal - displays the API call before executing
        // Returns Promise that resolves to true (execute) or false (cancel)
        function showCurlConfirmModal(title, warning, endpoint, method, payload, confirmText = 'Delete') {
            return new Promise((resolve) => {
                const modal = document.createElement('div');
                modal.className = 'modal-overlay';

                const jsonStr = JSON.stringify(payload, null, 2);
                const curlCommand = `curl -X ${method} "${window.location.origin}${endpoint}" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(payload)}'`;

                modal.innerHTML = `
                    <div class="modal-content modal-curl">
                        <button class="modal-close" onclick="this.closest('.modal-overlay').remove(); window._curlConfirmResolve(false);">&times;</button>
                        <div class="modal-header">
                            <span class="modal-icon">🗑️</span>
                            <h3>${title}</h3>
                        </div>
                        <div class="modal-warning">
                            ⚠️ ${warning}
                        </div>
                        <div class="curl-section">
                            <div class="curl-section-header">
                                <span class="curl-title">📋 API Call (cURL)</span>
                                <button class="btn-copy" onclick="copyCurlToClipboard(this)">
                                    <span class="copy-icon">📋</span> Copy
                                </button>
                            </div>
                            <pre class="curl-code">${curlCommand}</pre>
                        </div>
                        <div class="modal-buttons">
                            <button class="btn-cancel" onclick="this.closest('.modal-overlay').remove(); window._curlConfirmResolve(false);">Cancel</button>
                            <button class="btn-danger" onclick="this.closest('.modal-overlay').remove(); window._curlConfirmResolve(true);">${confirmText}</button>
                        </div>
                    </div>
                `;

                window._curlConfirmResolve = resolve;
                document.body.appendChild(modal);
            });
        }

        // Copy CURL command to clipboard
        function copyCurlToClipboard(btn) {
            const curlCode = btn.closest('.curl-section').querySelector('.curl-code').textContent;
            navigator.clipboard.writeText(curlCode).then(() => {
                const icon = btn.querySelector('.copy-icon');
                icon.textContent = '✅';
                setTimeout(() => { icon.textContent = '📋'; }, 1500);
            }).catch(err => {
                console.error('Copy failed:', err);
                alert('Copy failed. Please select and copy manually.');
            });
        }

        // Delete collection (trigger unpublish) - shows CURL before executing
        async function deleteCollection(collectionId, event) {
            event.stopPropagation();

            // 26 JAN 2026: Use consolidated endpoint (deprecated /unpublish/vector route was never registered)
            const endpoint = '/api/platform/unpublish';
            const payload = {
                data_type: 'vector',  // Explicit data type for consolidated endpoint
                table_name: collectionId,
                dry_run: false
            };

            const confirmed = await showCurlConfirmModal(
                'Delete Collection',
                `This will unpublish <strong>${collectionId}</strong> and remove it from the database. This action cannot be undone.`,
                endpoint,
                'POST',
                payload,
                'Delete Collection'
            );

            if (!confirmed) return;

            try {
                const response = await fetch(`${API_BASE_URL}${endpoint}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (result.success) {
                    showResultModal(
                        'Unpublish Submitted',
                        'The collection will be removed shortly.',
                        {
                            'Job ID': result.job_id,
                            'Collection': collectionId
                        },
                        '✅'
                    );
                    // Refresh the grid
                    loadCollections();
                } else {
                    showResultModal(
                        'Delete Failed',
                        result.error || 'Unknown error occurred',
                        null,
                        '❌'
                    );
                }
            } catch (error) {
                console.error('Error deleting collection:', error);
                showResultModal(
                    'Request Failed',
                    'Failed to submit delete request: ' + error.message,
                    null,
                    '❌'
                );
            }
        }
        """
