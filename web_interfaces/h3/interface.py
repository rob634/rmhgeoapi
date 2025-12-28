"""
H3 Grid Status interface module.

Web dashboard for monitoring H3 hexagonal grid coverage at different resolutions.

Features (27 DEC 2025 - Updated):
    - HTMX enabled for future partial updates
    - Visual display of H3 resolution levels 2-7
    - Cell count per resolution with status indicators
    - Resolution info (average cell size)
    - **Data Source Catalog** - displays registered h3.source_catalog entries
    - Auto-refresh capability

Exports:
    H3Interface: H3 grid status dashboard
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('h3')
class H3Interface(BaseInterface):
    """
    H3 Grid Status Dashboard.

    Displays cell counts for H3 resolutions 2-7 with visual status indicators.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate H3 Grid Status dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="H3 Grid Status",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content for H3 dashboard."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1>H3 Grid Status</h1>
                        <p class="subtitle">Hexagonal Hierarchical Spatial Index - Land Grid Coverage</p>
                    </div>
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <button id="refreshBtn" class="refresh-button">Refresh</button>
                    </div>
                </div>
            </header>

            <!-- Summary Card -->
            <div id="summary-card" class="summary-card">
                <div class="spinner"></div>
            </div>

            <!-- Resolution Grid -->
            <div class="section-title">Resolution Levels</div>
            <div id="resolution-grid" class="resolution-grid">
                <div class="spinner"></div>
            </div>

            <!-- Source Catalog Section -->
            <div class="section-title">Data Sources <span id="source-count" class="badge">--</span></div>
            <div id="source-catalog" class="source-catalog">
                <div class="spinner"></div>
            </div>

            <!-- H3 Info Section -->
            <div class="info-section">
                <div class="section-title">About H3</div>
                <div class="info-content">
                    <p>H3 is Uber's Hexagonal Hierarchical Spatial Index system. Each resolution level subdivides hexagons into 7 children.</p>
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Resolution</th>
                                <th>Avg Hex Area</th>
                                <th>Avg Edge Length</th>
                                <th>Use Case</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr><td>2</td><td>86,745 km2</td><td>158.2 km</td><td>Continental regions</td></tr>
                            <tr><td>3</td><td>12,393 km2</td><td>59.8 km</td><td>Country/State level</td></tr>
                            <tr><td>4</td><td>1,770 km2</td><td>22.6 km</td><td>Metro areas</td></tr>
                            <tr><td>5</td><td>252.9 km2</td><td>8.5 km</td><td>City districts</td></tr>
                            <tr><td>6</td><td>36.1 km2</td><td>3.2 km</td><td>Neighborhoods</td></tr>
                            <tr><td>7</td><td>5.2 km2</td><td>1.2 km</td><td>Census blocks</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Error State -->
            <div id="error-state" class="error-state hidden">
                <div class="icon">⚠</div>
                <h3>Error Loading Data</h3>
                <p id="error-message"></p>
                <button onclick="loadData()" class="refresh-button" style="margin-top: 20px;">Retry</button>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for H3 dashboard.

        Note: Most styles now in COMMON_CSS (S12.1.1).
        Only H3-specific styles remain here.
        """
        return """
        /* H3-specific: Summary card */
        .summary-card {
            background: white;
            border: 1px solid var(--ds-gray-light);
            padding: 25px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
        }

        .summary-item {
            text-align: center;
            padding: 15px;
            background: var(--ds-bg);
            border-radius: 6px;
        }

        .summary-label {
            font-size: 11px;
            color: var(--ds-gray);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 8px;
        }

        .summary-value {
            font-size: 28px;
            color: var(--ds-navy);
            font-weight: 700;
        }

        .summary-value.highlight {
            color: var(--ds-blue-primary);
        }

        /* H3-specific: Resolution grid and cards */
        .resolution-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .resolution-card {
            background: white;
            border: 2px solid var(--ds-gray-light);
            border-radius: 8px;
            padding: 25px;
            text-align: center;
            transition: all 0.3s ease;
            position: relative;
        }

        .resolution-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }

        .resolution-card.has-data {
            border-color: var(--ds-blue-primary);
            background: linear-gradient(135deg, #EBF5FF 0%, #DBEAFE 100%);
        }

        .resolution-card.no-data {
            border-color: #d1d5db;
            background: #f9fafb;
            opacity: 0.7;
        }

        .resolution-badge {
            position: absolute;
            top: -12px;
            left: 50%;
            transform: translateX(-50%);
            background: var(--ds-blue-primary);
            color: white;
            padding: 4px 16px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
        }

        .resolution-card.no-data .resolution-badge {
            background: #9ca3af;
        }

        .resolution-level {
            font-size: 48px;
            font-weight: 700;
            color: var(--ds-blue-primary);
            margin: 10px 0;
        }

        .resolution-card.no-data .resolution-level {
            color: #9ca3af;
        }

        .resolution-name {
            font-size: 14px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 8px;
        }

        .resolution-size {
            font-size: 12px;
            color: var(--ds-gray);
            margin-bottom: 15px;
        }

        .cell-count {
            font-size: 24px;
            font-weight: 700;
            color: var(--ds-navy);
        }

        .cell-count-label {
            font-size: 11px;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .resolution-card.no-data .cell-count {
            color: #9ca3af;
        }

        /* H3-specific: Info section */
        .info-section {
            background: white;
            border: 1px solid var(--ds-gray-light);
            padding: 25px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .info-content {
            color: var(--ds-gray);
            font-size: 14px;
            line-height: 1.6;
        }

        .info-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }

        .info-table th {
            background: var(--ds-bg);
            padding: 12px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: var(--ds-navy);
            border-bottom: 2px solid var(--ds-gray-light);
        }

        .info-table td {
            padding: 10px 12px;
            border-bottom: 1px solid var(--ds-gray-light);
            font-size: 13px;
        }

        .info-table tr:hover {
            background: var(--ds-bg);
        }

        /* H3-specific: Source catalog */
        .source-catalog {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .source-card {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 8px;
            padding: 20px;
            transition: all 0.2s ease;
        }

        .source-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            border-color: var(--ds-blue-primary);
        }

        .source-card.inactive {
            opacity: 0.6;
            background: #f9fafb;
        }

        .source-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 12px;
        }

        .source-title {
            font-size: 16px;
            font-weight: 600;
            color: var(--ds-navy);
            margin: 0;
        }

        .source-id {
            font-size: 11px;
            color: var(--ds-gray);
            font-family: monospace;
            margin-top: 4px;
        }

        .source-badges {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }

        .source-badge {
            font-size: 10px;
            padding: 3px 8px;
            border-radius: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .source-badge.theme {
            background: #EBF5FF;
            color: var(--ds-blue-primary);
        }

        .source-badge.type {
            background: #F0FDF4;
            color: #059669;
        }

        .source-badge.inactive {
            background: #FEE2E2;
            color: #DC2626;
        }

        .source-description {
            font-size: 13px;
            color: var(--ds-gray);
            margin-bottom: 15px;
            line-height: 1.5;
        }

        .source-meta {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            font-size: 12px;
            padding-top: 12px;
            border-top: 1px solid var(--ds-gray-light);
        }

        .source-meta-item {
            display: flex;
            flex-direction: column;
        }

        .source-meta-label {
            color: var(--ds-gray);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .source-meta-value {
            color: var(--ds-navy);
            font-weight: 600;
        }

        .source-empty {
            grid-column: 1 / -1;
            text-align: center;
            padding: 40px;
            color: var(--ds-gray);
        }

        .source-empty-icon {
            font-size: 48px;
            margin-bottom: 12px;
        }

        .badge {
            background: var(--ds-blue-primary);
            color: white;
            font-size: 12px;
            padding: 2px 10px;
            border-radius: 12px;
            margin-left: 8px;
            font-weight: 600;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for H3 dashboard."""
        return """
        // H3 resolution metadata
        const H3_RESOLUTIONS = {
            2: { name: 'Continental', avgArea: '86,745 km²', avgEdge: '158.2 km' },
            3: { name: 'Country/State', avgArea: '12,393 km²', avgEdge: '59.8 km' },
            4: { name: 'Metro Areas', avgArea: '1,770 km²', avgEdge: '22.6 km' },
            5: { name: 'City Districts', avgArea: '252.9 km²', avgEdge: '8.5 km' },
            6: { name: 'Neighborhoods', avgArea: '36.1 km²', avgEdge: '3.2 km' },
            7: { name: 'Census Blocks', avgArea: '5.2 km²', avgEdge: '1.2 km' }
        };

        // Load data on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadData();
            document.getElementById('refreshBtn').addEventListener('click', loadData);
        });

        async function loadData() {
            const summaryCard = document.getElementById('summary-card');
            const resolutionGrid = document.getElementById('resolution-grid');
            const sourceCatalog = document.getElementById('source-catalog');
            const errorState = document.getElementById('error-state');

            // Show loading
            summaryCard.innerHTML = '<div class="spinner"></div>';
            resolutionGrid.innerHTML = '<div class="spinner"></div>';
            sourceCatalog.innerHTML = '<div class="spinner"></div>';
            errorState.classList.add('hidden');

            try {
                // Fetch H3 stats and sources in parallel
                const [statsResponse, sourcesResponse] = await Promise.all([
                    fetchJSON(`${API_BASE_URL}/api/h3/stats`),
                    fetchJSON(`${API_BASE_URL}/api/h3/sources`).catch(err => {
                        console.warn('Could not load sources:', err);
                        return { sources: [] };
                    })
                ]);

                // Render summary
                renderSummary(statsResponse);

                // Render resolution cards
                renderResolutionGrid(statsResponse);

                // Render source catalog
                renderSourceCatalog(sourcesResponse);

            } catch (error) {
                console.error('Error loading H3 data:', error);
                showError(error.message || 'Failed to load H3 grid data');
            }
        }

        function renderSummary(data) {
            const stats = data.stats || {};
            const totalCells = Object.values(stats).reduce((sum, count) => sum + count, 0);
            const populatedLevels = Object.keys(stats).filter(k => stats[k] > 0).length;

            const html = `
                <div class="summary-grid">
                    <div class="summary-item">
                        <span class="summary-label">Total Cells</span>
                        <span class="summary-value highlight">${totalCells.toLocaleString()}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Populated Levels</span>
                        <span class="summary-value">${populatedLevels} / 6</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Schema</span>
                        <span class="summary-value" style="font-size: 16px;">h3.cells</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Index Type</span>
                        <span class="summary-value" style="font-size: 16px;">Land Grid</span>
                    </div>
                </div>
            `;

            document.getElementById('summary-card').innerHTML = html;
        }

        function renderResolutionGrid(data) {
            const stats = data.stats || {};
            let html = '';

            // Render cards for resolutions 2-7
            for (let res = 2; res <= 7; res++) {
                const count = stats[res] || 0;
                const hasData = count > 0;
                const meta = H3_RESOLUTIONS[res];

                html += `
                    <div class="resolution-card ${hasData ? 'has-data' : 'no-data'}">
                        <div class="resolution-badge">${hasData ? 'Active' : 'Empty'}</div>
                        <div class="resolution-level">${res}</div>
                        <div class="resolution-name">${meta.name}</div>
                        <div class="resolution-size">${meta.avgArea} avg</div>
                        <div class="cell-count">${count.toLocaleString()}</div>
                        <div class="cell-count-label">cells</div>
                    </div>
                `;
            }

            document.getElementById('resolution-grid').innerHTML = html;
        }

        function showError(message) {
            document.getElementById('summary-card').innerHTML = '';
            document.getElementById('resolution-grid').innerHTML = '';
            document.getElementById('source-catalog').innerHTML = '';
            document.getElementById('error-state').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }

        function renderSourceCatalog(data) {
            const sources = data.sources || [];
            const container = document.getElementById('source-catalog');
            const countBadge = document.getElementById('source-count');

            // Update count badge
            countBadge.textContent = sources.length;

            if (sources.length === 0) {
                container.innerHTML = `
                    <div class="source-empty">
                        <div class="source-empty-icon">📦</div>
                        <h3>No Data Sources Registered</h3>
                        <p>Register data sources using POST /api/h3/sources</p>
                    </div>
                `;
                return;
            }

            let html = '';
            for (const source of sources) {
                const isActive = source.is_active !== false;
                const theme = source.theme || 'unknown';
                const sourceType = source.source_type || 'unknown';
                const resolution = source.native_resolution_m ? `${source.native_resolution_m}m` : '--';
                const h3Range = source.recommended_h3_res_min && source.recommended_h3_res_max
                    ? `${source.recommended_h3_res_min}-${source.recommended_h3_res_max}`
                    : '--';

                html += `
                    <div class="source-card ${isActive ? '' : 'inactive'}">
                        <div class="source-header">
                            <div>
                                <h4 class="source-title">${source.display_name || source.id}</h4>
                                <div class="source-id">${source.id}</div>
                            </div>
                            <div class="source-badges">
                                <span class="source-badge theme">${theme}</span>
                                <span class="source-badge type">${sourceType.replace('_', ' ')}</span>
                                ${!isActive ? '<span class="source-badge inactive">Inactive</span>' : ''}
                            </div>
                        </div>
                        <div class="source-description">
                            ${source.description || 'No description available'}
                        </div>
                        <div class="source-meta">
                            <div class="source-meta-item">
                                <span class="source-meta-label">Resolution</span>
                                <span class="source-meta-value">${resolution}</span>
                            </div>
                            <div class="source-meta-item">
                                <span class="source-meta-label">H3 Levels</span>
                                <span class="source-meta-value">${h3Range}</span>
                            </div>
                            ${source.collection_id ? `
                            <div class="source-meta-item">
                                <span class="source-meta-label">Collection</span>
                                <span class="source-meta-value">${source.collection_id}</span>
                            </div>
                            ` : ''}
                            ${source.source_provider ? `
                            <div class="source-meta-item">
                                <span class="source-meta-label">Provider</span>
                                <span class="source-meta-value">${source.source_provider}</span>
                            </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            }

            container.innerHTML = html;
        }
        """
