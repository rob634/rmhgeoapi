"""
STAC Collection Items Viewer Interface.

Displays all items in a STAC collection as cards with preview links
to the raster viewer.

Route: /api/interface/stac-collection?id=<collection_id>

Features:
    - Collection metadata header
    - Item cards with thumbnails/previews
    - Direct links to raster viewer for each item
    - Asset details and property summaries
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('stac-collection')
class StacCollectionInterface(BaseInterface):
    """
    STAC Collection Items Viewer.

    Displays all items in a collection as interactive cards with
    preview links to the raster viewer.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate STAC collection items viewer HTML.

        Query Parameters:
            id: Collection ID (required)

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        collection_id = request.params.get('id', '')

        content = self._generate_html_content(collection_id)
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        title = f"STAC Collection: {collection_id}" if collection_id else "STAC Collection Viewer"

        return self.wrap_html(
            title=title,
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def _generate_html_content(self, collection_id: str) -> str:
        """Generate HTML content structure."""
        return f"""
        <div class="container">
            <!-- Back Navigation -->
            <div class="back-nav">
                <a href="/api/interface/stac" class="back-link">← Back to Collections</a>
            </div>

            <!-- Collection Header (populated by JS) -->
            <header class="collection-header" id="collection-header">
                <div class="header-skeleton">
                    <div class="skeleton-title"></div>
                    <div class="skeleton-desc"></div>
                </div>
            </header>

            <!-- Filter Bar -->
            <div class="filter-bar">
                <div class="filter-left">
                    <input type="text" class="search-input" id="item-search"
                           placeholder="Search items..." onkeyup="filterItems()">
                </div>
                <div class="filter-right">
                    <span class="item-count" id="item-count">Loading...</span>
                </div>
            </div>

            <!-- Loading Spinner -->
            <div id="loading-spinner" class="spinner-container">
                <div class="spinner"></div>
                <div class="spinner-text">Loading collection items...</div>
            </div>

            <!-- Items Grid -->
            <div class="items-grid" id="items-grid">
                <!-- Item cards will be inserted here by JavaScript -->
            </div>

            <!-- Empty State -->
            <div class="empty-state hidden" id="empty-state">
                <div class="icon">📄</div>
                <h3>No Items Found</h3>
                <p>This collection doesn't have any items yet.</p>
            </div>

            <!-- Error State -->
            <div class="error-state hidden" id="error-state">
                <div class="icon">⚠️</div>
                <h3>Error Loading Collection</h3>
                <p id="error-message">An error occurred while loading the collection.</p>
                <a href="/api/interface/stac" class="btn btn-primary">Back to Collections</a>
            </div>
        </div>

        <!-- Store collection ID for JavaScript -->
        <script>
            window.COLLECTION_ID = '{collection_id}';
        </script>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for collection viewer."""
        return """
        /* Back navigation */
        .back-nav {
            margin-bottom: 16px;
        }

        .back-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--ds-blue-primary);
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            padding: 8px 16px;
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            transition: all 0.2s;
        }

        .back-link:hover {
            background: var(--ds-bg);
            border-color: var(--ds-blue-primary);
        }

        /* Collection header */
        .collection-header {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-left: 4px solid var(--ds-blue-primary);
            padding: 24px;
            border-radius: 4px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }

        /* Header top row with title and action button (13 JAN 2026) */
        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 20px;
            margin-bottom: 16px;
        }

        .header-text {
            flex: 1;
        }

        .header-actions {
            flex-shrink: 0;
        }

        .collection-header h1 {
            font-size: 24px;
            color: var(--ds-navy);
            margin-bottom: 8px;
        }

        .collection-header .description {
            color: var(--ds-gray);
            font-size: 14px;
            line-height: 1.5;
            margin: 0;
        }

        /* Mosaic view button (13 JAN 2026) */
        .btn-mosaic-view {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 20px;
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
            box-shadow: 0 2px 4px rgba(16, 185, 129, 0.3);
        }

        .btn-mosaic-view:hover {
            background: linear-gradient(135deg, #059669 0%, #047857 100%);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(16, 185, 129, 0.4);
        }

        /* No search warning (13 JAN 2026) */
        .no-search-warning {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            color: #92400E;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }

        .collection-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
        }

        .meta-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: var(--ds-gray-lighter);
            border-radius: 4px;
            font-size: 13px;
            color: var(--ds-gray-dark);
        }

        .meta-badge strong {
            color: var(--ds-navy);
        }

        /* Skeleton loading */
        .header-skeleton {
            animation: pulse 1.5s ease-in-out infinite;
        }

        .skeleton-title {
            height: 28px;
            width: 300px;
            background: var(--ds-gray-light);
            border-radius: 4px;
            margin-bottom: 12px;
        }

        .skeleton-desc {
            height: 16px;
            width: 500px;
            background: var(--ds-gray-light);
            border-radius: 4px;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Filter bar */
        .filter-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            gap: 16px;
        }

        .filter-left {
            flex: 1;
            max-width: 300px;
        }

        .item-count {
            background: var(--ds-blue-primary);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }

        /* Spinner container */
        .spinner-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 60px;
        }

        .spinner-container .spinner {
            width: 40px;
            height: 40px;
            border: 4px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-bottom: 16px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .spinner-text {
            color: var(--ds-gray);
            font-size: 14px;
        }

        /* Items grid */
        .items-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 16px;
        }

        /* Item card */
        .item-card {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            overflow: hidden;
            transition: all 0.2s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }

        .item-card:hover {
            border-color: var(--ds-blue-primary);
            box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            transform: translateY(-2px);
        }

        .item-card-header {
            background: linear-gradient(135deg, #053657 0%, #0071BC 100%);
            color: white;
            padding: 14px 16px;
        }

        .item-card-header h3 {
            font-size: 14px;
            font-weight: 600;
            margin: 0;
            word-break: break-all;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .item-card-body {
            padding: 16px;
        }

        .item-props {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 12px;
        }

        .item-prop {
            font-size: 12px;
        }

        .item-prop-label {
            color: var(--ds-gray);
            display: block;
            margin-bottom: 2px;
        }

        .item-prop-value {
            color: var(--ds-navy);
            font-weight: 500;
        }

        .item-prop-value.mono {
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 11px;
        }

        /* Assets section */
        .item-assets {
            border-top: 1px solid var(--ds-gray-light);
            padding-top: 12px;
            margin-top: 12px;
        }

        .assets-header {
            font-size: 11px;
            text-transform: uppercase;
            color: var(--ds-gray);
            font-weight: 600;
            margin-bottom: 8px;
        }

        .asset-list {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }

        .asset-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 8px;
            background: var(--ds-gray-lighter);
            border-radius: 4px;
            font-size: 11px;
            color: var(--ds-gray-dark);
        }

        .asset-badge.primary {
            background: rgba(0, 113, 188, 0.1);
            color: var(--ds-blue-primary);
            font-weight: 600;
        }

        /* Action buttons */
        .item-actions {
            display: flex;
            gap: 8px;
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid var(--ds-gray-light);
        }

        .btn-view {
            flex: 1;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            padding: 10px 16px;
            background: linear-gradient(135deg, #10B981 0%, #059669 100%);
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }

        .btn-view:hover {
            background: linear-gradient(135deg, #059669 0%, #047857 100%);
            transform: translateY(-1px);
        }

        .btn-view:disabled {
            background: var(--ds-gray-light);
            color: var(--ds-gray);
            cursor: not-allowed;
            transform: none;
        }

        .btn-json {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 10px 12px;
            background: var(--ds-gray-lighter);
            color: var(--ds-gray-dark);
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }

        .btn-json:hover {
            background: var(--ds-gray-light);
            color: var(--ds-navy);
        }

        /* Empty/Error states */
        .empty-state, .error-state {
            text-align: center;
            padding: 60px 20px;
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
        }

        .empty-state .icon, .error-state .icon {
            font-size: 48px;
            margin-bottom: 16px;
        }

        .empty-state h3, .error-state h3 {
            color: var(--ds-navy);
            margin-bottom: 8px;
        }

        .empty-state p, .error-state p {
            color: var(--ds-gray);
            margin-bottom: 20px;
        }

        /* Properties tooltip */
        .props-more {
            font-size: 11px;
            color: var(--ds-blue-primary);
            cursor: pointer;
            margin-top: 4px;
        }

        .props-more:hover {
            text-decoration: underline;
        }

        /* Bbox display */
        .bbox-display {
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 10px;
            background: var(--ds-gray-lighter);
            padding: 4px 8px;
            border-radius: 3px;
            margin-top: 8px;
            color: var(--ds-gray-dark);
            word-break: break-all;
        }

        /* STAC API Links Section (19 JAN 2026) */
        .stac-api-links {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid var(--ds-gray-light);
        }

        .stac-api-links-label {
            font-size: 11px;
            text-transform: uppercase;
            color: var(--ds-gray);
            font-weight: 600;
            width: 100%;
            margin-bottom: 4px;
        }

        .btn-stac-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            background: white;
            color: var(--ds-blue-primary);
            border: 1px solid var(--ds-blue-primary);
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .btn-stac-link:hover {
            background: var(--ds-blue-primary);
            color: white;
        }

        /* Default bbox warning */
        .bbox-warning {
            color: #D97706;
            font-size: 10px;
            font-style: italic;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for collection viewer."""
        return """
        // State
        let collectionData = null;
        let allItems = [];

        // Load collection and items on page load
        async function loadCollection() {
            const collectionId = window.COLLECTION_ID;

            if (!collectionId) {
                showError('No collection ID provided. Please specify a collection.');
                return;
            }

            const spinner = document.getElementById('loading-spinner');
            const grid = document.getElementById('items-grid');
            const emptyState = document.getElementById('empty-state');
            const errorState = document.getElementById('error-state');
            const countDisplay = document.getElementById('item-count');

            // Show loading
            spinner.classList.remove('hidden');
            grid.innerHTML = '';
            emptyState.classList.add('hidden');
            errorState.classList.add('hidden');

            try {
                // Fetch collection metadata and items in parallel
                const [collection, itemsData] = await Promise.all([
                    fetchJSON(`${API_BASE_URL}/api/stac/collections/${collectionId}`),
                    fetchJSON(`${API_BASE_URL}/api/stac/collections/${collectionId}/items?limit=1000`)
                ]);

                collectionData = collection;
                allItems = itemsData.features || [];

                // Render header with actual item count (19 JAN 2026 - fixes "?" display)
                renderCollectionHeader(collection, allItems.length);

                spinner.classList.add('hidden');

                if (allItems.length === 0) {
                    countDisplay.textContent = '0 Items';
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Update count
                countDisplay.textContent = `${allItems.length} Items`;

                // Render items
                renderItems(allItems);

            } catch (error) {
                console.error('Error loading collection:', error);
                spinner.classList.add('hidden');
                showError(`Failed to load collection: ${error.message}`);
            }
        }

        // Render collection header (updated 19 JAN 2026 - STAC API links + bbox fixes)
        function renderCollectionHeader(collection, actualItemCount = null) {
            const header = document.getElementById('collection-header');

            const title = collection.title || collection.id;
            const desc = collection.description || 'No description available';
            const type = collection.type || 'unknown';
            const license = collection.license || 'Not specified';
            // Use actual fetched count if available, otherwise fall back to summary
            const itemCount = actualItemCount !== null ? actualItemCount : (collection.summaries?.total_items || '?');

            // Get bbox with default detection
            let bboxStr = 'Not specified';
            let bboxIsDefault = false;
            if (collection.extent?.spatial?.bbox?.[0]) {
                const bbox = collection.extent.spatial.bbox[0];
                // Detect world-spanning defaults [-180, -90, 180, 90]
                const isWorldDefault = (
                    Math.abs(bbox[0] + 180) < 0.01 &&
                    Math.abs(bbox[1] + 90) < 0.01 &&
                    Math.abs(bbox[2] - 180) < 0.01 &&
                    Math.abs(bbox[3] - 90) < 0.01
                );
                if (isWorldDefault) {
                    bboxStr = 'World (default)';
                    bboxIsDefault = true;
                } else {
                    bboxStr = `[${bbox.map(v => v.toFixed(2)).join(', ')}]`;
                }
            }

            // Find preview link for TiTiler mosaic viewer (13 JAN 2026)
            let previewUrl = null;
            if (collection.links) {
                const previewLink = collection.links.find(link => link.rel === 'preview');
                if (previewLink && previewLink.href) {
                    previewUrl = previewLink.href;
                }
            }

            // Build mosaic viewer button or warning if no search registered
            const mosaicButton = previewUrl
                ? `<a href="${previewUrl}" target="_blank" class="btn-mosaic-view">🗺️ View Collection Mosaic</a>`
                : `<div class="no-search-warning">⚠️ No pgSTAC search registered</div>`;

            // Build bbox display with warning if default
            const bboxDisplay = bboxIsDefault
                ? `<span style="font-family: monospace; font-size: 11px;">${bboxStr}</span> <span class="bbox-warning">(needs recalculation)</span>`
                : `<span style="font-family: monospace; font-size: 11px;">${bboxStr}</span>`;

            // STAC API JSON endpoint links (19 JAN 2026)
            const collectionId = collection.id;
            const stacApiLinks = `
                <div class="stac-api-links">
                    <div class="stac-api-links-label">STAC API Endpoints (JSON)</div>
                    <a href="${API_BASE_URL}/api/stac/collections/${collectionId}" target="_blank" class="btn-stac-link">
                        📄 /collections/${collectionId}
                    </a>
                    <a href="${API_BASE_URL}/api/stac/collections/${collectionId}/items" target="_blank" class="btn-stac-link">
                        📋 /collections/${collectionId}/items
                    </a>
                    <a href="${API_BASE_URL}/api/stac/collections/${collectionId}/items?limit=10" target="_blank" class="btn-stac-link">
                        🔍 /items?limit=10
                    </a>
                </div>
            `;

            header.innerHTML = `
                <div class="header-top">
                    <div class="header-text">
                        <h1>${title}</h1>
                        <div class="description">${desc}</div>
                    </div>
                    <div class="header-actions">${mosaicButton}</div>
                </div>
                <div class="collection-meta">
                    <span class="meta-badge">
                        <span>${type === 'raster' ? '🌍' : '📐'}</span>
                        <strong>${type}</strong>
                    </span>
                    <span class="meta-badge">
                        <span>📄</span>
                        <strong>${itemCount}</strong> items
                    </span>
                    <span class="meta-badge">
                        <span>📜</span>
                        ${license}
                    </span>
                    <span class="meta-badge">
                        <span>🗺️</span>
                        ${bboxDisplay}
                    </span>
                </div>
                ${stacApiLinks}
            `;
        }

        // Render items grid
        function renderItems(items) {
            const grid = document.getElementById('items-grid');

            grid.innerHTML = items.map(item => {
                const itemId = item.id;
                const geomType = item.geometry?.type || 'None';
                const assets = item.assets || {};
                const assetKeys = Object.keys(assets);
                const props = item.properties || {};

                // Get datetime
                const datetime = props.datetime ? formatDate(props.datetime) : 'Not specified';

                // Get bbox
                let bboxStr = null;
                if (item.bbox) {
                    bboxStr = `[${item.bbox.map(v => v.toFixed(3)).join(', ')}]`;
                }

                // Find COG URL for viewer
                let cogUrl = null;
                const assetPriority = ['cog', 'data', 'visual', 'image', 'raster'];
                for (const key of assetPriority) {
                    if (assets[key]?.href) {
                        cogUrl = assets[key].href;
                        break;
                    }
                }
                if (!cogUrl) {
                    for (const [key, asset] of Object.entries(assets)) {
                        if (asset.href && (asset.href.endsWith('.tif') || asset.href.endsWith('.tiff'))) {
                            cogUrl = asset.href;
                            break;
                        }
                    }
                }
                if (!cogUrl && assetKeys.length > 0) {
                    cogUrl = assets[assetKeys[0]]?.href;
                }

                // Build asset badges (max 4)
                const assetBadges = assetKeys.slice(0, 4).map((key, idx) => {
                    const asset = assets[key];
                    const isPrimary = idx === 0;
                    const type = asset.type ? asset.type.split('/').pop() : 'file';
                    return `<span class="asset-badge ${isPrimary ? 'primary' : ''}">${key} (${type})</span>`;
                }).join('');

                const moreAssets = assetKeys.length > 4 ? `<span class="asset-badge">+${assetKeys.length - 4} more</span>` : '';

                // Build key properties display
                const propsToShow = ['datetime', 'created', 'updated', 'gsd', 'proj:epsg'];
                let propsHtml = '';
                for (const key of propsToShow) {
                    if (props[key] !== undefined) {
                        let value = props[key];
                        if (key === 'datetime' || key === 'created' || key === 'updated') {
                            value = formatDate(value);
                        } else if (key === 'gsd') {
                            value = value.toFixed(2) + ' m';
                        }
                        propsHtml += `
                            <div class="item-prop">
                                <span class="item-prop-label">${key}</span>
                                <span class="item-prop-value">${value}</span>
                            </div>
                        `;
                    }
                }

                // View button
                const viewButton = cogUrl
                    ? `<a href="/api/interface/raster-viewer?url=${encodeURIComponent(cogUrl)}" target="_blank" class="btn-view">🗺️ View in Raster Viewer</a>`
                    : `<button class="btn-view" disabled>No COG Available</button>`;

                return `
                    <div class="item-card" data-item-id="${itemId}">
                        <div class="item-card-header">
                            <h3>${itemId}</h3>
                        </div>
                        <div class="item-card-body">
                            <div class="item-props">
                                <div class="item-prop">
                                    <span class="item-prop-label">Geometry</span>
                                    <span class="item-prop-value">${geomType}</span>
                                </div>
                                <div class="item-prop">
                                    <span class="item-prop-label">Assets</span>
                                    <span class="item-prop-value">${assetKeys.length}</span>
                                </div>
                                ${propsHtml}
                            </div>

                            ${bboxStr ? `<div class="bbox-display">📍 ${bboxStr}</div>` : ''}

                            <div class="item-assets">
                                <div class="assets-header">Assets</div>
                                <div class="asset-list">
                                    ${assetBadges}${moreAssets}
                                </div>
                            </div>

                            <div class="item-actions">
                                ${viewButton}
                                <a href="${API_BASE_URL}/api/stac/collections/${window.COLLECTION_ID}/items/${itemId}"
                                   target="_blank" class="btn-json" title="View raw JSON">{ }</a>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Filter items
        function filterItems() {
            const searchTerm = document.getElementById('item-search').value.toLowerCase();

            const filtered = allItems.filter(item => {
                return item.id.toLowerCase().includes(searchTerm);
            });

            renderItems(filtered);

            // Update count
            const countDisplay = document.getElementById('item-count');
            if (searchTerm) {
                countDisplay.textContent = `${filtered.length} of ${allItems.length} Items`;
            } else {
                countDisplay.textContent = `${allItems.length} Items`;
            }
        }

        // Show error state
        function showError(message) {
            const errorState = document.getElementById('error-state');
            const errorMessage = document.getElementById('error-message');
            const spinner = document.getElementById('loading-spinner');
            const header = document.getElementById('collection-header');

            spinner.classList.add('hidden');
            header.innerHTML = `<h1>Collection Not Found</h1>`;
            errorMessage.textContent = message;
            errorState.classList.remove('hidden');
        }

        // Initialize on page load
        window.addEventListener('load', function() {
            console.log('STAC Collection Viewer initialized');
            loadCollection();
        });
        """


# Export for testing
__all__ = ['StacCollectionInterface']
