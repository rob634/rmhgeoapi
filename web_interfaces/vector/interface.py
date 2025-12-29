"""
OGC Features interface module.

Web dashboard for browsing OGC API - Features collections with metadata and API endpoints.

Features (24 DEC 2025 - S12.3.3):
    - HTMX enabled for future partial updates
    - Uses COMMON_CSS and COMMON_JS utilities

Exports:
    VectorInterface: OGC Features collections browser with clickable cards and spatial extents
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
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

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
            <!-- Header -->
            <header class="dashboard-header">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 15px;">
                    <div>
                        <h1>📐 OGC Features Collections</h1>
                        <p class="subtitle">Browse vector feature collections via OGC API - Features standard</p>
                    </div>
                    <a href="/api/interface/promote-vector" class="promote-link">
                        <span>⬆️</span> Promote Vector →
                    </a>
                </div>
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
        """Generate custom CSS for OGC Features dashboard.

        Note: Most styles now in COMMON_CSS (S12.1.1).
        Only vector-specific styles remain here.
        """
        return """
        /* Vector-specific: Stats banner as grid layout */
        .stats-banner {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 20px;
        }

        /* Vector-specific: Card meta section with border */
        .collection-card .meta {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid var(--ds-gray-light);
            color: var(--ds-gray);
        }

        .collection-card .meta-item {
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .collection-card .feature-count {
            color: var(--ds-blue-primary);
            font-weight: 600;
        }

        .collection-card .bbox {
            font-family: 'Courier New', monospace;
            font-size: 11px;
            color: var(--ds-gray);
        }

        .collection-card .links {
            margin-top: 12px;
            display: flex;
            gap: 10px;
        }

        .promote-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 10px 18px;
            background: linear-gradient(135deg, #0071BC 0%, #00A3DA 100%);
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.2s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .promote-link:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
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
