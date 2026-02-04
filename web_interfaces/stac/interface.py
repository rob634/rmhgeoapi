"""
STAC dashboard interface module.

Web dashboard for browsing STAC collections and items with search and filter capabilities.

Features (24 DEC 2025 - S12.3.3):
    - HTMX enabled for future partial updates
    - Uses COMMON_CSS and COMMON_JS utilities

Exports:
    StacInterface: STAC collections browser with grid view and collection detail views
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('stac')
class StacInterface(BaseInterface):
    """
    STAC Collections Dashboard interface.

    Displays STAC collections in grid format, allows drilling down into
    collection details and viewing items.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate STAC dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="STAC Collections Dashboard",
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
                    <h1>🛰️ STAC Collections</h1>
                </div>
                <div class="header-right">
                    <span class="collection-count" id="total-collections">Loading...</span>
                </div>
            </header>

            <!-- Collections List View -->
            <div id="collections-view">
                <!-- Action Bar -->
                <div class="action-bar">
                    <a href="/api/interface/submit" class="btn btn-primary">
                        ➕ Submit New Job
                    </a>
                    <div class="filter-group">
                        <input type="text" class="search-input" id="search-filter"
                               placeholder="Search collections..." onkeyup="filterCollections()">
                        <select class="filter-select" id="type-filter" onchange="filterCollections()">
                            <option value="">All Types</option>
                            <option value="raster">Raster Only</option>
                            <option value="vector">Vector Only</option>
                        </select>
                    </div>
                </div>

                <!-- Loading Spinner -->
                <div id="loading-spinner" class="spinner"></div>

                <!-- Collections Grid -->
                <div class="collections-grid" id="collections-grid">
                    <!-- Collections will be inserted here by JavaScript -->
                </div>

                <!-- Empty State -->
                <div class="empty-state hidden" id="empty-state">
                    <div class="icon">📦</div>
                    <h3>No Collections Found</h3>
                    <p>There are no STAC collections available yet.</p>
                </div>
            </div>

            <!-- Collection Detail View (hidden by default) -->
            <div id="detail-view" class="hidden">
                <div class="detail-nav">
                    <button class="back-button" onclick="showCollectionsList()">← Back to Collections</button>
                    <a id="titiler-viewer-btn" class="titiler-button hidden" href="#" target="_blank">
                        🗺️ Open in Raster Viewer
                    </a>
                </div>

                <div class="detail-header">
                    <h2 id="detail-title">Collection Name</h2>
                    <div class="description" id="detail-description">Description will appear here</div>
                    <div class="metadata" id="detail-metadata">
                        <!-- Metadata items will be inserted here -->
                    </div>
                </div>

                <h3 style="margin: 20px 0; color: #2c3e50;">Items</h3>

                <div class="spinner-container hidden" id="items-loading-spinner">
                    <div class="spinner"></div>
                    <div class="spinner-text">Loading items...</div>
                </div>

                <table class="items-table hidden" id="items-table">
                    <thead>
                        <tr>
                            <th>Item ID</th>
                            <th>Geometry</th>
                            <th>Assets</th>
                            <th>Properties</th>
                            <th>Preview</th>
                        </tr>
                    </thead>
                    <tbody id="items-tbody">
                        <!-- Items will be inserted here -->
                    </tbody>
                </table>

                <div class="empty-state hidden" id="items-empty-state">
                    <div class="icon">📄</div>
                    <h3>No Items Found</h3>
                    <p>This collection doesn't have any items yet.</p>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for STAC dashboard.

        Note: Most styles now in COMMON_CSS (S12.1.1).
        Header/action-bar consolidated S12.5.1-S12.5.2 (08 JAN 2026).
        Only STAC-specific styles remain here.

        Updated 31 DEC 2025: Match vector interface card style with Map/Promote/Delete buttons.
        """
        return """
        /* STAC-specific: narrower search input in filter group */
        .filter-group .search-input {
            width: 200px;
        }

        /* Compact 2-column grid - horizontal cards (03 FEB 2026) */
        .collections-grid {
            grid-template-columns: repeat(2, 1fr) !important;
            gap: 8px !important;
        }

        .collection-card {
            padding: 8px 12px !important;
            cursor: pointer;
            display: flex;
            flex-direction: row;
            align-items: center;
            gap: 12px;
        }

        /* Left section: badges + title + description */
        .collection-card .card-info {
            flex: 1;
            min-width: 0;
            display: flex;
            flex-direction: column;
        }

        .collection-card .card-badges {
            display: flex;
            gap: 3px;
            margin-bottom: 2px;
        }

        .collection-card h3 {
            font-size: 13px !important;
            margin: 0 !important;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .collection-card .description {
            font-size: 10px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: var(--ds-gray);
            margin: 0;
        }

        /* Middle section: bbox */
        .collection-card .bbox {
            font-family: 'Courier New', monospace;
            font-size: 9px;
            color: var(--ds-gray);
            white-space: nowrap;
            flex-shrink: 0;
        }

        /* Right section: action buttons */
        .collection-card .links {
            display: flex;
            gap: 3px;
            flex-shrink: 0;
        }

        .collection-card .link-badge {
            font-size: 10px !important;
            padding: 2px 5px !important;
        }

        /* Items button */
        .link-badge-info {
            background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%) !important;
            color: white !important;
            border-color: #2563EB !important;
            text-decoration: none !important;
        }

        .link-badge-info:hover {
            background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
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

        /* Compact status badges */
        .approved-badge {
            display: inline-block;
            background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%);
            color: white;
            font-size: 8px;
            font-weight: 600;
            padding: 1px 4px;
            border-radius: 3px;
        }

        /* Disabled/protected button */
        .link-badge-disabled {
            background: linear-gradient(135deg, #9CA3AF 0%, #6B7280 100%) !important;
            color: white !important;
            cursor: not-allowed !important;
            opacity: 0.7;
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

        /* STAC-specific: Detail view */
        .detail-header {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-left: 4px solid var(--ds-blue-primary);
            padding: 30px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .detail-header h2 {
            font-size: 28px;
            margin-bottom: 10px;
            color: var(--ds-navy);
            font-weight: 700;
        }

        .detail-header .description {
            font-size: 16px;
            color: var(--ds-gray);
            margin-bottom: 15px;
        }

        .detail-nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .back-button {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: white;
            border: 1px solid var(--ds-gray-light);
            color: var(--ds-blue-primary);
            border-radius: 3px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 20px;
            transition: all 0.2s;
        }

        .back-button:hover {
            background: var(--ds-bg);
            border-color: var(--ds-blue-primary);
            color: var(--ds-cyan);
        }

        /* STAC-specific: TiTiler button */
        .titiler-button {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 24px;
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            border: none;
            color: white;
            border-radius: 6px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s;
            box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
        }

        .titiler-button:hover {
            background: linear-gradient(135deg, #059669 0%, #047857 100%);
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
            transform: translateY(-1px);
        }

        /* STAC-specific: Preview link in items table */
        .preview-link {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 6px 12px;
            background: #10B981;
            color: white;
            border-radius: 4px;
            text-decoration: none;
            font-size: 12px;
            font-weight: 600;
            transition: background 0.2s;
        }

        .preview-link:hover {
            background: #059669;
        }

        .no-preview {
            color: #9CA3AF;
            font-size: 12px;
            font-style: italic;
        }

        /* STAC-specific: Item ID styling */
        .item-id {
            font-family: 'Courier New', monospace;
            color: var(--ds-blue-primary);
            font-weight: 500;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for STAC dashboard.

        Updated 31 DEC 2025: Match vector interface with Map/Promote/Delete buttons.
        """
        return """
        // State
        let allCollections = [];
        let currentCollection = null;

        // Load collections on page load
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
                const data = await fetchJSON(`${API_BASE_URL}/api/stac/collections`);
                allCollections = data.collections || [];

                // Fetch approval statuses for all collections (17 JAN 2026)
                if (allCollections.length > 0) {
                    const collectionIds = allCollections.map(c => c.id).join(',');
                    try {
                        const approvalData = await fetchJSON(
                            `${API_BASE_URL}/api/platform/approvals/status?stac_collection_ids=${encodeURIComponent(collectionIds)}`
                        );
                        window.approvalStatuses = approvalData.statuses || {};
                    } catch (e) {
                        console.warn('Could not fetch approval statuses:', e);
                        window.approvalStatuses = {};
                    }
                }

                spinner.classList.add('hidden');

                if (allCollections.length === 0) {
                    countDisplay.textContent = '0 Collections';
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
                countDisplay.textContent = 'Error';
            }
        }

        // Render collections grid - compact horizontal cards (03 FEB 2026)
        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');
            grid.innerHTML = collections.map(c => {
                const title = c.title || c.id;
                const desc = c.description || 'No description available';

                // Get bbox if available
                const bbox = c.extent?.spatial?.bbox?.[0];
                const bboxStr = bbox ?
                    `[${bbox.map(v => v.toFixed(2)).join(', ')}]` :
                    'No extent';

                // Check approval status
                const approvalStatus = window.approvalStatuses?.[c.id] || {};
                const isApproved = approvalStatus.is_approved === true;

                // Build action buttons - Items, Map, Delete only (no Promote)
                let actionButtons = `
                    <a class="link-badge link-badge-info"
                       href="/api/interface/stac-collection?id=${c.id}"
                       onclick="event.stopPropagation()"
                       title="View items">
                        📄
                    </a>
                    <button class="link-badge link-badge-primary"
                            onclick="openMapView('${c.id}', event)"
                            title="Open in viewer">
                        🗺️
                    </button>`;

                // Show delete or protected based on approval status
                if (isApproved) {
                    actionButtons += `
                        <span class="link-badge link-badge-disabled" title="Protected">🔒</span>`;
                } else {
                    actionButtons += `
                        <button class="link-badge link-badge-delete"
                                onclick="deleteCollection('${c.id}', event)"
                                title="Delete collection">
                            🗑️
                        </button>`;
                }

                // Build badges HTML
                const badgesHtml = isApproved ? `
                    <div class="card-badges">
                        <span class="approved-badge">✓</span>
                    </div>` : '';

                return `
                    <div class="collection-card" onclick="showCollectionDetail('${c.id}')" title="${title}">
                        <div class="card-info">
                            ${badgesHtml}
                            <h3>${title}</h3>
                            <div class="description">${desc}</div>
                        </div>
                        <span class="bbox">${bboxStr}</span>
                        <div class="links">${actionButtons}</div>
                    </div>
                `;
            }).join('');
        }

        // Open map view - loads first item's COG in raster viewer
        async function openMapView(collectionId, event) {
            event.stopPropagation();

            // Get collection type
            const collection = allCollections.find(c => c.id === collectionId);
            const collectionType = collection?.type || 'raster';

            // For vector collections, use the vector map
            if (collectionType === 'vector') {
                window.open(`${API_BASE_URL}/api/interface/map?collection=${collectionId}`, '_blank');
                return;
            }

            // For raster collections, get first item's COG URL
            try {
                const itemsResp = await fetchJSON(`${API_BASE_URL}/api/stac/collections/${collectionId}/items?limit=1`);
                const items = itemsResp.features || [];

                if (items.length === 0) {
                    showResultModal(
                        'No Items',
                        `Collection <strong>${collectionId}</strong> has no items to display.`,
                        { 'Collection': collectionId },
                        'ℹ️'
                    );
                    return;
                }

                const item = items[0];

                // Find COG URL from assets - look for 'cog', 'data', 'visual', or first asset
                let cogUrl = null;
                const assets = item.assets || {};

                // Priority order for asset keys
                const assetPriority = ['cog', 'data', 'visual', 'image', 'raster'];
                for (const key of assetPriority) {
                    if (assets[key]?.href) {
                        cogUrl = assets[key].href;
                        break;
                    }
                }

                // Fallback to first asset with a .tif or .tiff extension
                if (!cogUrl) {
                    for (const [key, asset] of Object.entries(assets)) {
                        if (asset.href && (asset.href.endsWith('.tif') || asset.href.endsWith('.tiff'))) {
                            cogUrl = asset.href;
                            break;
                        }
                    }
                }

                // Final fallback - just use first asset
                if (!cogUrl) {
                    const firstAsset = Object.values(assets)[0];
                    if (firstAsset?.href) {
                        cogUrl = firstAsset.href;
                    }
                }

                if (!cogUrl) {
                    showResultModal(
                        'No COG Found',
                        `Could not find a COG asset in collection <strong>${collectionId}</strong>.`,
                        { 'Collection': collectionId, 'Item': item.id },
                        '⚠️'
                    );
                    return;
                }

                // Open raster viewer with the COG URL
                window.open(`${API_BASE_URL}/api/interface/raster-viewer?url=${encodeURIComponent(cogUrl)}`, '_blank');

            } catch (error) {
                console.error('Error opening map view:', error);
                showResultModal(
                    'Error',
                    `Failed to load collection items: ${error.message}`,
                    { 'Collection': collectionId },
                    '❌'
                );
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

        // Delete collection - unpublish all items in the collection (shows CURL before executing)
        async function deleteCollection(collectionId, event) {
            event.stopPropagation();

            // Get item count for this collection
            let itemCount = 0;
            const collection = allCollections.find(c => c.id === collectionId);
            if (collection) {
                itemCount = collection.summaries?.total_items || 0;
            }

            if (itemCount === 0) {
                showResultModal(
                    'Delete Collection',
                    `Collection <strong>${collectionId}</strong> has no items to delete.`,
                    { 'Collection': collectionId },
                    'ℹ️'
                );
                return;
            }

            // 26 JAN 2026: Use consolidated endpoint (deprecated /unpublish/raster route was never registered)
            const endpoint = '/api/platform/unpublish';
            const payload = {
                data_type: 'raster',  // Explicit data type for consolidated endpoint
                collection_id: collectionId,
                delete_collection: true,
                dry_run: false
            };

            const confirmed = await showCurlConfirmModal(
                'Delete Collection',
                `This will unpublish <strong>${collectionId}</strong> and delete all <strong>${itemCount}</strong> item(s) and their associated blobs. This action cannot be undone.`,
                endpoint,
                'POST',
                payload,
                'Delete All Items'
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
                        'Collection Unpublish Submitted',
                        `Submitted ${result.jobs_submitted} unpublish job(s) for collection.`,
                        {
                            'Collection': collectionId,
                            'Total Items': result.total_items,
                            'Jobs Submitted': result.jobs_submitted,
                            'Jobs Skipped': result.jobs_skipped || 0
                        },
                        '✅'
                    );
                    // Refresh the grid after a short delay
                    setTimeout(loadCollections, 2000);
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

        // filterCollections() now in COMMON_JS (S12.5.4 - 08 JAN 2026)

        // Show collection detail
        async function showCollectionDetail(collectionId) {
            // Hide collections view, show detail view
            document.getElementById('collections-view').classList.add('hidden');
            document.getElementById('detail-view').classList.remove('hidden');

            const spinner = document.getElementById('items-loading-spinner');
            const metadata = document.getElementById('detail-metadata');

            // Show loading
            spinner.classList.remove('hidden');
            metadata.innerHTML = '<div class="spinner"></div>';
            document.getElementById('detail-title').textContent = 'Loading...';
            document.getElementById('detail-description').textContent = '';

            try {
                // Fetch full collection metadata from STAC API
                const collection = await fetchJSON(`${API_BASE_URL}/api/stac/collections/${collectionId}`);
                currentCollection = collection;

                // Set header
                document.getElementById('detail-title').textContent = collection.title || collectionId;
                document.getElementById('detail-description').textContent = collection.description || 'No description available';

                // Build comprehensive metadata display
                const metadataItems = [];

                // Core metadata
                metadataItems.push(`
                    <div class="metadata-item">
                        <div class="label">Collection ID</div>
                        <div class="value">${collection.id}</div>
                    </div>
                `);

                // Total items
                if (collection.summaries?.total_items !== undefined) {
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">Total Items</div>
                            <div class="value">${collection.summaries.total_items.toLocaleString()}</div>
                        </div>
                    `);
                }

                // Type
                if (collection.type) {
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">Type</div>
                            <div class="value">${collection.type === 'raster' ? '🌍 Raster' : '📐 Vector'}</div>
                        </div>
                    `);
                }

                // License
                if (collection.license) {
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">License</div>
                            <div class="value">${collection.license}</div>
                        </div>
                    `);
                }

                // Extent - Spatial
                if (collection.extent?.spatial?.bbox) {
                    const bbox = collection.extent.spatial.bbox[0];
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">Spatial Extent</div>
                            <div class="value" style="font-family: monospace; font-size: 12px;">
                                [${bbox.map(v => v.toFixed(4)).join(', ')}]
                            </div>
                        </div>
                    `);
                }

                // Extent - Temporal
                if (collection.extent?.temporal?.interval) {
                    const interval = collection.extent.temporal.interval[0];
                    const start = interval[0] ? formatDate(interval[0]) : 'Open';
                    const end = interval[1] ? formatDate(interval[1]) : 'Open';
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">Temporal Extent</div>
                            <div class="value">${start} → ${end}</div>
                        </div>
                    `);
                }

                // Links - formatted and clickable
                if (collection.links && collection.links.length > 0) {
                    const linksHtml = collection.links.map(link => {
                        const icon = link.rel === 'self' ? '🔗' :
                                    link.rel === 'items' ? '📄' :
                                    link.rel === 'parent' ? '⬆️' :
                                    link.rel === 'root' ? '🏠' : '🔗';
                        return `
                            <div style="margin: 4px 0;">
                                ${icon} <a href="${link.href}" target="_blank" style="color: #0071BC; text-decoration: none;">
                                    <strong>${link.rel}</strong>
                                </a> - ${link.title || link.type || 'Link'}
                            </div>
                        `;
                    }).join('');

                    metadataItems.push(`
                        <div class="metadata-item" style="grid-column: 1 / -1;">
                            <div class="label">Links (${collection.links.length})</div>
                            <div class="value" style="line-height: 1.8;">${linksHtml}</div>
                        </div>
                    `);
                }

                // Providers
                if (collection.providers && collection.providers.length > 0) {
                    const providerNames = collection.providers.map(p => p.name).join(', ');
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">Providers</div>
                            <div class="value">${providerNames}</div>
                        </div>
                    `);
                }

                // Keywords/Tags
                if (collection.keywords && collection.keywords.length > 0) {
                    metadataItems.push(`
                        <div class="metadata-item" style="grid-column: 1 / -1;">
                            <div class="label">Keywords</div>
                            <div class="value">${collection.keywords.join(', ')}</div>
                        </div>
                    `);
                }

                // STAC Version
                if (collection.stac_version) {
                    metadataItems.push(`
                        <div class="metadata-item">
                            <div class="label">STAC Version</div>
                            <div class="value">${collection.stac_version}</div>
                        </div>
                    `);
                }

                metadata.innerHTML = metadataItems.join('');

                // Load items
                await loadCollectionItems(collectionId);

            } catch (error) {
                console.error('Error loading collection detail:', error);
                spinner.classList.add('hidden');
                metadata.innerHTML = `<div class="error">Failed to load collection metadata</div>`;
            }
        }

        // Load collection items
        async function loadCollectionItems(collectionId) {
            const spinner = document.getElementById('items-loading-spinner');
            const table = document.getElementById('items-table');
            const tbody = document.getElementById('items-tbody');
            const emptyState = document.getElementById('items-empty-state');
            const titilerBtn = document.getElementById('titiler-viewer-btn');

            // Hide TiTiler button initially
            titilerBtn.classList.add('hidden');

            // Show loading
            spinner.classList.remove('hidden');
            table.classList.add('hidden');
            emptyState.classList.add('hidden');

            try {
                const data = await fetchJSON(`${API_BASE_URL}/api/stac/collections/${collectionId}/items`);
                const items = data.features || [];

                spinner.classList.add('hidden');

                if (items.length === 0) {
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Check for mosaic search_id first (collection-level mosaic view)
                // This provides a seamless view of all items in the collection
                const searchId = currentCollection?.['mosaic:search_id'];

                if (searchId) {
                    // Use mosaic mode with search_id for collection-wide view
                    titilerBtn.href = `/api/interface/raster-viewer?search_id=${encodeURIComponent(searchId)}`;
                    titilerBtn.textContent = '🗺️ Open Collection Mosaic';
                    titilerBtn.classList.remove('hidden');
                } else {
                    // Fallback: Find first COG URL for single-item view
                    let firstCogUrl = null;
                    for (const item of items) {
                        const cogUrl = getCogUrlFromItem(item);
                        if (cogUrl) {
                            firstCogUrl = cogUrl;
                            break;
                        }
                    }

                    // Show raster viewer button if we have a COG
                    if (firstCogUrl) {
                        titilerBtn.href = `/api/interface/raster-viewer?url=${encodeURIComponent(firstCogUrl)}`;
                        titilerBtn.textContent = '🗺️ Open in Raster Viewer';
                        titilerBtn.classList.remove('hidden');
                    }
                }

                // Render items with raster viewer links
                tbody.innerHTML = items.map(item => {
                    const assetCount = Object.keys(item.assets || {}).length;
                    const propCount = Object.keys(item.properties || {}).length;
                    const geomType = item.geometry?.type || 'None';

                    // Find COG URL for this item
                    const cogUrl = getCogUrlFromItem(item);
                    const previewHtml = cogUrl
                        ? `<a href="/api/interface/raster-viewer?url=${encodeURIComponent(cogUrl)}" target="_blank" class="preview-link">🗺️ View</a>`
                        : '<span class="no-preview">—</span>';

                    return `
                        <tr>
                            <td><span class="item-id">${item.id}</span></td>
                            <td>${geomType}</td>
                            <td>${assetCount} asset${assetCount !== 1 ? 's' : ''}</td>
                            <td>${propCount} propert${propCount !== 1 ? 'ies' : 'y'}</td>
                            <td>${previewHtml}</td>
                        </tr>
                    `;
                }).join('');

                table.classList.remove('hidden');

            } catch (error) {
                console.error('Error loading items:', error);
                spinner.classList.add('hidden');
                emptyState.classList.remove('hidden');
            }
        }

        // Extract COG URL from a STAC item's assets
        function getCogUrlFromItem(item) {
            const assets = item.assets || {};
            const assetKeys = Object.keys(assets);

            // Priority order for asset keys
            const assetPriority = ['cog', 'data', 'visual', 'image', 'raster'];
            for (const key of assetPriority) {
                if (assets[key]?.href) {
                    return assets[key].href;
                }
            }

            // Fallback to first asset with a .tif or .tiff extension
            for (const [key, asset] of Object.entries(assets)) {
                if (asset.href && (asset.href.endsWith('.tif') || asset.href.endsWith('.tiff'))) {
                    return asset.href;
                }
            }

            // Final fallback - just use first asset
            if (assetKeys.length > 0) {
                return assets[assetKeys[0]]?.href || null;
            }

            return null;
        }

        // Show collections list
        function showCollectionsList() {
            document.getElementById('detail-view').classList.add('hidden');
            document.getElementById('collections-view').classList.remove('hidden');
            // Reset TiTiler button
            const titilerBtn = document.getElementById('titiler-viewer-btn');
            titilerBtn.classList.add('hidden');
            titilerBtn.textContent = '🗺️ Open in Raster Viewer';  // Reset to default text
        }

        // Initialize on page load
        window.addEventListener('load', function() {
            console.log('STAC Dashboard initialized');
            loadCollections();
        });
        """


# Export for testing
__all__ = ['StacInterface']
