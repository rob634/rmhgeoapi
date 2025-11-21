# ============================================================================
# CLAUDE CONTEXT - OGC FEATURES INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE ✅
# STATUS: Web Interface - OGC Features collections browser
# PURPOSE: Generate HTML dashboard for browsing OGC API - Features collections
# LAST_REVIEWED: 15 NOV 2025
# EXPORTS: VectorInterface
# INTERFACES: BaseInterface
# PYDANTIC_MODELS: None
# DEPENDENCIES: web_interfaces.base, azure.functions
# SOURCE: OGC Features API endpoints (/api/features/collections)
# SCOPE: Vector feature collections visualization
# VALIDATION: None (display only)
# PATTERNS: Template Method (inherits BaseInterface)
# ENTRY_POINTS: Registered as 'vector' in InterfaceRegistry
# INDEX: VectorInterface:40, render:60, _generate_custom_css:150, _generate_custom_js:300
# ============================================================================

"""
OGC Features Interface

Web interface for browsing OGC API - Features collections. Provides:
    - Collections grid view with metadata
    - Clickable cards that open API endpoints
    - Feature counts and spatial extents
    - Links to items endpoint

Route: /api/interface/vector

"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('vector')
class VectorInterface(BaseInterface):
    """
    OGC Features Collections Dashboard interface.

    Displays OGC API - Features collections in grid format with clickable
    cards that open the collection's API endpoint.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate OGC Features dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """

        # HTML content
        content = self._generate_html_content()

        # Custom CSS for OGC Features dashboard
        custom_css = self._generate_custom_css()

        # Custom JavaScript for OGC Features dashboard
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="OGC Features Collections",
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
                <h1>📐 OGC Features Collections</h1>
                <p class="subtitle">Browse vector feature collections via OGC API - Features standard</p>
            </header>

            <!-- Stats Banner -->
            <div class="stats-banner hidden" id="stats-banner">
                <div class="stat-item">
                    <span class="stat-label">Total Collections</span>
                    <span class="stat-value" id="total-collections">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Total Features</span>
                    <span class="stat-value" id="total-features">0</span>
                </div>
            </div>

            <!-- Search/Filter -->
            <div class="controls">
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
        """Generate custom CSS for OGC Features dashboard."""
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
            font-size: 16px;
            margin: 0;
        }

        /* Stats Banner */
        .stats-banner {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }

        .stat-item {
            text-align: center;
            padding: 15px;
            border-radius: 3px;
            background: #f8f9fa;
        }

        .stat-label {
            display: block;
            font-size: 12px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .stat-value {
            display: block;
            font-size: 28px;
            color: #053657;
            font-weight: 700;
        }

        /* Controls */
        .controls {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }

        .search-input {
            width: 100%;
            padding: 12px 20px;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            font-size: 14px;
            color: #053657;
            font-weight: 600;
        }

        .search-input:focus {
            outline: none;
            border-color: #0071BC;
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }

        /* Collections Grid */
        .collections-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
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
            color: #053657;
            margin-bottom: 10px;
            font-weight: 700;
        }

        .collection-card .description {
            color: #626F86;
            font-size: 14px;
            margin-bottom: 15px;
            line-height: 1.6;
        }

        .collection-card .meta {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            font-size: 13px;
            color: #626F86;
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e9ecef;
        }

        .collection-card .meta-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .collection-card .feature-count {
            color: #0071BC;
            font-weight: 600;
        }

        .collection-card .bbox {
            font-family: 'Courier New', monospace;
            font-size: 11px;
            color: #626F86;
        }

        .collection-card .links {
            margin-top: 12px;
            display: flex;
            gap: 10px;
        }

        .link-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: #0071BC;
            text-decoration: none;
            transition: all 0.2s;
        }

        .link-badge:hover {
            background: #0071BC;
            color: white;
            transform: translateY(-1px);
        }

        .link-badge-primary {
            background: #0071BC;
            color: white;
            border-color: #0071BC;
        }

        .link-badge-primary:hover {
            background: #00A3DA;
            border-color: #00A3DA;
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #626F86;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .empty-state .icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .empty-state h3 {
            color: #053657;
            margin-bottom: 10px;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for OGC Features dashboard."""
        return """
        // State
        let allCollections = [];

        // Load collections on page load
        document.addEventListener('DOMContentLoaded', loadCollections);

        // Load collections from API
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
                const data = await fetchJSON(`${API_BASE_URL}/api/features/collections`);
                allCollections = data.collections || [];

                spinner.classList.add('hidden');

                if (allCollections.length === 0) {
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Calculate total features
                const totalFeatures = allCollections.reduce((sum, c) => {
                    const desc = c.description || '';
                    const match = desc.match(/\\((\\d+) features\\)/);
                    return sum + (match ? parseInt(match[1]) : 0);
                }, 0);

                // Show stats
                document.getElementById('total-collections').textContent = allCollections.length;
                document.getElementById('total-features').textContent = totalFeatures.toLocaleString();
                statsBanner.classList.remove('hidden');

                // Render collections
                renderCollections(allCollections);

            } catch (error) {
                console.error('Error loading collections:', error);
                spinner.classList.add('hidden');
                emptyState.classList.remove('hidden');
            }
        }

        // Render collections grid
        function renderCollections(collections) {
            const grid = document.getElementById('collections-grid');

            grid.innerHTML = collections.map(c => {
                // Extract feature count from description
                const desc = c.description || 'No description available';
                const featureCount = desc.match(/\\((\\d+) features\\)/);
                const count = featureCount ? parseInt(featureCount[1]).toLocaleString() : 'Unknown';

                // Get bbox if available
                const bbox = c.extent?.spatial?.bbox?.[0];
                const bboxStr = bbox ?
                    `[${bbox.map(v => v.toFixed(2)).join(', ')}]` :
                    'No extent';

                // Get links
                const selfLink = c.links?.find(l => l.rel === 'self')?.href;
                const itemsLink = c.links?.find(l => l.rel === 'items')?.href;
                const viewerLink = `${API_BASE_URL}/api/vector/viewer?collection=${encodeURIComponent(c.id)}`;

                return `
                    <div class="collection-card" onclick="openCollection('${selfLink}', event)">
                        <h3>${c.title || c.id}</h3>
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
                            <a href="${viewerLink}"
                               class="link-badge link-badge-primary"
                               onclick="event.stopPropagation()"
                               target="_blank"
                               title="Interactive map viewer">
                                🗺️ View Map
                            </a>
                            <a href="${selfLink}"
                               class="link-badge"
                               onclick="event.stopPropagation()"
                               target="_blank"
                               title="Collection metadata (JSON)">
                                🔗 Collection
                            </a>
                            <a href="${itemsLink}"
                               class="link-badge"
                               onclick="event.stopPropagation()"
                               target="_blank"
                               title="Features endpoint (GeoJSON)">
                                📄 Items
                            </a>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Filter collections
        function filterCollections() {
            const searchTerm = document.getElementById('search-filter').value.toLowerCase();

            const filtered = allCollections.filter(c => {
                return c.id.toLowerCase().includes(searchTerm) ||
                       (c.title || '').toLowerCase().includes(searchTerm) ||
                       (c.description || '').toLowerCase().includes(searchTerm);
            });

            renderCollections(filtered);
        }

        // Open collection API endpoint
        function openCollection(url, event) {
            // Only open if clicking the card itself, not the links
            if (event.target.tagName !== 'A') {
                window.open(url, '_blank');
            }
        }
        """
