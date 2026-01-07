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
                    <a href="/api/interface/submit-raster" class="btn btn-primary">
                        ➕ Create New Raster Collection
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
                        🗺️ Open in TiTiler Viewer
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
        Only STAC-specific styles remain here.

        Updated 31 DEC 2025: Match vector interface card style with Map/Promote/Delete buttons.
        """
        return """
        /* Header with count - flex layout */
        .header-with-count {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 12px;
        }

        .header-with-count h1 {
            margin: 0;
        }

        .collection-count {
            background: var(--ds-blue-primary);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
        }

        /* Action bar with button and filters */
        .action-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            gap: 16px;
        }

        .filter-group {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .filter-group .search-input {
            width: 200px;
        }

        .filter-select {
            padding: 8px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-size: 13px;
        }

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

        /* Card meta section with border - matches vector */
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

        .collection-card .item-count {
            color: var(--ds-blue-primary);
            font-weight: 600;
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

        // Render collections grid - matches vector interface style
        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');
            grid.innerHTML = collections.map(c => {
                const itemCount = c.summaries?.total_items || 0;
                const type = c.type || 'unknown';
                const title = c.title || c.id;
                const desc = c.description || 'No description available';

                // Get bbox if available
                const bbox = c.extent?.spatial?.bbox?.[0];
                const bboxStr = bbox ?
                    `[${bbox.map(v => v.toFixed(2)).join(', ')}]` :
                    'No extent';

                // Build action buttons - Items, Map, Promote, Delete
                const actionButtons = `
                    <a class="link-badge link-badge-info"
                       href="/api/interface/stac-collection?id=${c.id}"
                       onclick="event.stopPropagation()"
                       title="View all items in collection">
                        📄 Items
                    </a>
                    <button class="link-badge link-badge-primary"
                            onclick="openMapView('${c.id}', event)"
                            title="Open in raster viewer">
                        🗺️ Map
                    </button>
                    <button class="link-badge link-badge-promote"
                            onclick="promoteCollection('${c.id}', event)"
                            title="Promote collection (coming soon)">
                        ⬆️ Promote
                    </button>
                    <button class="link-badge link-badge-delete"
                            onclick="deleteCollection('${c.id}', event)"
                            title="Delete this collection (unpublish)">
                        🗑️ Delete
                    </button>
                `;

                return `
                    <div class="collection-card" onclick="showCollectionDetail('${c.id}')" title="${title}">
                        <h3>${title}</h3>
                        <div class="description">${desc}</div>

                        <div class="meta">
                            <div class="meta-item">
                                <span>📄</span>
                                <span class="item-count">${itemCount.toLocaleString()} items</span>
                            </div>
                            <div class="meta-item">
                                <span>${type === 'raster' ? '🌍' : '📐'}</span>
                                <span>${type}</span>
                            </div>
                            <div class="meta-item">
                                <span>🗺️</span>
                                <span style="font-family: monospace; font-size: 10px;">${bboxStr}</span>
                            </div>
                        </div>

                        <div class="links">
                            ${actionButtons}
                        </div>
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

        // Placeholder: Promote collection
        function promoteCollection(collectionId, event) {
            event.stopPropagation();
            showResultModal(
                'Promote Collection',
                'Promote workflow for STAC raster collections is coming soon.',
                { 'Collection': collectionId },
                '⬆️'
            );
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

        // Delete collection - unpublish all items in the collection
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

            const confirmed = await showConfirmModal(
                'Delete Collection?',
                `This will unpublish <strong>${collectionId}</strong> and delete all <strong>${itemCount}</strong> item(s) and their associated blobs. This action cannot be undone.`,
                'Delete All',
                '🗑️'
            );

            if (!confirmed) return;

            try {
                const response = await fetch(`${API_BASE_URL}/api/platform/unpublish/raster`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        collection_id: collectionId,
                        delete_collection: true,
                        dry_run: false
                    })
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

        // Filter collections
        function filterCollections() {
            const searchTerm = document.getElementById('search-filter').value.toLowerCase();
            const typeFilter = document.getElementById('type-filter').value;

            const filtered = allCollections.filter(c => {
                const matchesSearch = !searchTerm ||
                    c.id.toLowerCase().includes(searchTerm) ||
                    (c.title || '').toLowerCase().includes(searchTerm) ||
                    (c.description || '').toLowerCase().includes(searchTerm);

                const matchesType = !typeFilter || c.type === typeFilter;

                return matchesSearch && matchesType;
            });

            renderCollections(filtered);
        }

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

                // Find first preview link for the header button (exclude system-rasters)
                let firstPreviewUrl = null;
                if (collectionId !== 'system-rasters') {
                    for (const item of items) {
                        const previewLink = (item.links || []).find(l => l.rel === 'preview');
                        if (previewLink?.href) {
                            firstPreviewUrl = previewLink.href;
                            break;
                        }
                    }
                }

                // Show TiTiler button if we have a preview
                if (firstPreviewUrl) {
                    titilerBtn.href = firstPreviewUrl;
                    titilerBtn.classList.remove('hidden');
                }

                // Render items with preview links
                tbody.innerHTML = items.map(item => {
                    const assetCount = Object.keys(item.assets || {}).length;
                    const propCount = Object.keys(item.properties || {}).length;
                    const geomType = item.geometry?.type || 'None';

                    // Find preview link for this item
                    const previewLink = (item.links || []).find(l => l.rel === 'preview');
                    const previewHtml = previewLink?.href
                        ? `<a href="${previewLink.href}" target="_blank" class="preview-link">🗺️ View</a>`
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

        // Show collections list
        function showCollectionsList() {
            document.getElementById('detail-view').classList.add('hidden');
            document.getElementById('collections-view').classList.remove('hidden');
            // Reset TiTiler button
            document.getElementById('titiler-viewer-btn').classList.add('hidden');
        }

        // Initialize on page load
        window.addEventListener('load', function() {
            console.log('STAC Dashboard initialized');
            loadCollections();
        });
        """


# Export for testing
__all__ = ['StacInterface']
