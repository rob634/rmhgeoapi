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

        Updated 30 DEC 2025: Smaller cards, header with count, action bar.
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

        .collection-card .meta {
            font-size: 11px;
            color: var(--ds-gray);
            display: flex;
            gap: 12px;
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

        // Render collections grid
        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');
            grid.innerHTML = collections.map(c => {
                const itemCount = c.summaries?.total_items || 0;
                const type = c.type || 'unknown';
                const title = c.title || c.id;
                const desc = c.description || 'No description available';

                return `
                    <div class="collection-card" onclick="showCollectionDetail('${c.id}')" title="${title}">
                        <h3>${title}</h3>
                        <div class="description">${desc}</div>
                        <div class="meta">
                            <span>📄 ${itemCount.toLocaleString()} items</span>
                            <span>${type === 'raster' ? '🌍' : '📐'} ${type}</span>
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
