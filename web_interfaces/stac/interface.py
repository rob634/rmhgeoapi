"""
STAC dashboard interface module.

Web dashboard for browsing STAC collections and items with search and filter capabilities.

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

        # HTML content
        content = self._generate_html_content()

        # Custom CSS for STAC dashboard
        custom_css = self._generate_custom_css()

        # Custom JavaScript for STAC dashboard
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="STAC Collections Dashboard",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content structure."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <h1>🛰️ STAC Collections Dashboard</h1>
                <p class="subtitle">Browse and explore SpatioTemporal Asset Catalog collections</p>
            </header>

            <!-- Collections List View -->
            <div id="collections-view">
                <!-- Stats Banner -->
                <div class="stats-banner hidden" id="stats-banner">
                    <div class="stat-item">
                        <span class="stat-label">Total Collections</span>
                        <span class="stat-value" id="total-collections">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Items</span>
                        <span class="stat-value" id="total-items">0</span>
                    </div>
                </div>

                <!-- Filters -->
                <div class="filters">
                    <input type="text" class="filter-input" id="search-filter"
                           placeholder="Search collections..." onkeyup="filterCollections()">
                    <select class="filter-select" id="type-filter" onchange="filterCollections()">
                        <option value="">All Types</option>
                        <option value="raster">Raster Only</option>
                        <option value="vector">Vector Only</option>
                    </select>
                </div>

                <!-- Collections Grid -->
                <div class="collections-grid" id="collections-grid">
                    <!-- Collections will be inserted here by JavaScript -->
                </div>

                <!-- Loading Spinner -->
                <div class="spinner-container hidden" id="loading-spinner">
                    <div class="spinner"></div>
                    <div class="spinner-text">Loading collections...</div>
                </div>

                <!-- Empty State -->
                <div class="empty-state hidden" id="empty-state">
                    <div class="icon">📦</div>
                    <h3>No Collections Found</h3>
                    <p>There are no STAC collections available yet.</p>
                </div>

                <!-- Status Message -->
                <div id="status" class="hidden"></div>
            </div>

            <!-- Collection Detail View (hidden by default) -->
            <div id="detail-view" class="hidden">
                <button class="back-button" onclick="showCollectionsList()">← Back to Collections</button>

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
        """Generate custom CSS for STAC dashboard - World Bank inspired."""
        return """
        .dashboard-header {
            background: white;
            padding: 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            border-left: 4px solid #0071BC;
        }

        .dashboard-header h1 {
            color: #053657;
            font-size: 28px;
            margin-bottom: 10px;
            font-weight: 700;
        }

        .subtitle {
            color: #626F86;
            font-size: 14px;
        }

        /* Stats Banner */
        .stats-banner {
            background: white;
            padding: 20px 30px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            gap: 40px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .stat-item {
            display: flex;
            flex-direction: column;
        }

        .stat-label {
            font-size: 12px;
            color: #7f8c8d;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: #2c3e50;
        }

        /* Filters */
        .filters {
            display: flex;
            gap: 15px;
            margin-bottom: 20px;
        }

        .filter-input, .filter-select {
            padding: 10px 15px;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            font-size: 14px;
            background: white;
        }

        .filter-input {
            flex: 1;
            max-width: 400px;
        }

        .filter-select {
            cursor: pointer;
        }

        /* Collections Grid */
        .collections-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }

        .collection-card {
            background: white;
            border: 1px solid #e9ecef;
            border-left: 4px solid #0071BC;
            border-radius: 3px;
            padding: 24px;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .collection-card:hover {
            box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            border-left-color: #00A3DA;
            transform: translateY(-2px);
        }

        .collection-card h3 {
            font-size: 18px;
            margin-bottom: 10px;
            color: #053657;
            font-weight: 700;
        }

        .collection-card .description {
            font-size: 14px;
            color: #626F86;
            margin-bottom: 15px;
            line-height: 1.6;
        }

        .collection-card .meta {
            display: flex;
            gap: 15px;
            font-size: 13px;
            color: #0071BC;
            font-weight: 600;
        }

        /* Collection Detail */
        .detail-header {
            background: white;
            border: 1px solid #e9ecef;
            border-left: 4px solid #0071BC;
            padding: 30px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .detail-header h2 {
            font-size: 28px;
            margin-bottom: 10px;
            color: #053657;
            font-weight: 700;
        }

        .detail-header .description {
            font-size: 16px;
            color: #626F86;
            margin-bottom: 15px;
        }

        .metadata {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }

        .metadata-item {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            padding: 12px;
            border-radius: 3px;
        }

        .metadata-item .label {
            font-size: 12px;
            color: #626F86;
            margin-bottom: 4px;
            text-transform: uppercase;
            font-weight: 600;
        }

        .metadata-item .value {
            font-size: 16px;
            font-weight: 600;
            color: #053657;
        }

        .back-button {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: white;
            border: 1px solid #e9ecef;
            color: #0071BC;
            border-radius: 3px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 20px;
            transition: all 0.2s;
        }

        .back-button:hover {
            background: #f8f9fa;
            border-color: #0071BC;
            color: #00A3DA;
        }

        /* Items Table */
        .items-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .items-table thead {
            background: #f8f9fa;
        }

        .items-table th {
            text-align: left;
            padding: 12px;
            font-weight: 600;
            color: #2c3e50;
            border-bottom: 2px solid #dee2e6;
        }

        .items-table td {
            padding: 12px;
            border-bottom: 1px solid #dee2e6;
        }

        .items-table tbody tr:hover {
            background: #f8f9fa;
        }

        .item-id {
            font-family: 'Courier New', monospace;
            color: #0071BC;
            font-weight: 500;
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #7f8c8d;
            background: white;
            border-radius: 8px;
        }

        .empty-state .icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .empty-state h3 {
            font-size: 20px;
            margin-bottom: 10px;
            color: #2c3e50;
        }

        /* Spinner Container */
        .spinner-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 60px 20px;
            background: white;
            border-radius: 8px;
        }

        .spinner-text {
            margin-top: 20px;
            color: #7f8c8d;
            font-size: 14px;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for STAC dashboard."""
        return """
        // State
        let allCollections = [];
        let currentCollection = null;

        // Load collections on page load
        async function loadCollections() {
            const grid = document.getElementById('collections-grid');
            const spinner = document.getElementById('loading-spinner');
            const emptyState = document.getElementById('empty-state');
            const statsBanner = document.getElementById('stats-banner');

            // Show loading
            grid.innerHTML = '';
            spinner.classList.remove('hidden');
            emptyState.classList.add('hidden');
            statsBanner.classList.add('hidden');

            try {
                const data = await fetchJSON(`${API_BASE_URL}/api/stac/collections`);
                allCollections = data.collections || [];

                spinner.classList.add('hidden');

                if (allCollections.length === 0) {
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Show stats
                const totalItems = allCollections.reduce((sum, c) => sum + (c.summaries?.total_items || 0), 0);
                document.getElementById('total-collections').textContent = allCollections.length;
                document.getElementById('total-items').textContent = totalItems.toLocaleString();
                statsBanner.classList.remove('hidden');

                // Render collections
                renderCollections(allCollections);

            } catch (error) {
                console.error('Error loading collections:', error);
                spinner.classList.add('hidden');
                // Error already shown by fetchJSON
            }
        }

        // Render collections grid
        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');
            grid.innerHTML = collections.map(c => {
                const itemCount = c.summaries?.total_items || 0;
                const type = c.type || 'unknown';

                return `
                    <div class="collection-card" onclick="showCollectionDetail('${c.id}')">
                        <h3>${c.title || c.id}</h3>
                        <div class="description">${c.description || 'No description available'}</div>
                        <div class="meta">
                            <div>📄 ${itemCount.toLocaleString()} items</div>
                            <div>${type === 'raster' ? '🌍' : '📐'} ${type}</div>
                        </div>
                    </div>
                `;
            }).join('');
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
                    const start = interval[0] ? new Date(interval[0]).toLocaleDateString() : 'Open';
                    const end = interval[1] ? new Date(interval[1]).toLocaleDateString() : 'Open';
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

                // Render items
                tbody.innerHTML = items.map(item => {
                    const assetCount = Object.keys(item.assets || {}).length;
                    const propCount = Object.keys(item.properties || {}).length;
                    const geomType = item.geometry?.type || 'None';

                    return `
                        <tr>
                            <td><span class="item-id">${item.id}</span></td>
                            <td>${geomType}</td>
                            <td>${assetCount} asset${assetCount !== 1 ? 's' : ''}</td>
                            <td>${propCount} propert${propCount !== 1 ? 'ies' : 'y'}</td>
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
        }

        // Initialize on page load
        window.addEventListener('load', function() {
            console.log('STAC Dashboard initialized');
            loadCollections();
        });
        """


# Export for testing
__all__ = ['StacInterface']
