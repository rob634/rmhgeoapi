"""
H3 Grid Status interface module.

Web dashboard for monitoring H3 hexagonal grid coverage at different resolutions.

Features (16 DEC 2025):
    - Visual display of H3 resolution levels 2-7
    - Cell count per resolution with status indicators
    - Resolution info (average cell size)
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
            custom_js=custom_js
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
        """Generate custom CSS for H3 dashboard."""
        return """
        .dashboard-header {
            background: white;
            padding: 25px 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            border-left: 4px solid #8B5CF6;
        }

        .dashboard-header h1 {
            color: #053657;
            font-size: 24px;
            margin-bottom: 8px;
            font-weight: 700;
        }

        .subtitle {
            color: #626F86;
            font-size: 14px;
            margin: 0;
        }

        .refresh-button {
            background: #8B5CF6;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }

        .refresh-button:hover {
            background: #7C3AED;
        }

        /* Summary Card */
        .summary-card {
            background: white;
            border: 1px solid #e9ecef;
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
            background: #f8f9fa;
            border-radius: 6px;
        }

        .summary-label {
            font-size: 11px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 8px;
        }

        .summary-value {
            font-size: 28px;
            color: #053657;
            font-weight: 700;
        }

        .summary-value.purple {
            color: #8B5CF6;
        }

        /* Section Title */
        .section-title {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e9ecef;
        }

        /* Resolution Grid */
        .resolution-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .resolution-card {
            background: white;
            border: 2px solid #e9ecef;
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
            border-color: #8B5CF6;
            background: linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%);
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
            background: #8B5CF6;
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
            color: #8B5CF6;
            margin: 10px 0;
        }

        .resolution-card.no-data .resolution-level {
            color: #9ca3af;
        }

        .resolution-name {
            font-size: 14px;
            font-weight: 600;
            color: #053657;
            margin-bottom: 8px;
        }

        .resolution-size {
            font-size: 12px;
            color: #626F86;
            margin-bottom: 15px;
        }

        .cell-count {
            font-size: 24px;
            font-weight: 700;
            color: #053657;
        }

        .cell-count-label {
            font-size: 11px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .resolution-card.no-data .cell-count {
            color: #9ca3af;
        }

        /* Info Section */
        .info-section {
            background: white;
            border: 1px solid #e9ecef;
            padding: 25px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .info-content {
            color: #626F86;
            font-size: 14px;
            line-height: 1.6;
        }

        .info-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }

        .info-table th {
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: #053657;
            border-bottom: 2px solid #e9ecef;
        }

        .info-table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
            font-size: 13px;
        }

        .info-table tr:hover {
            background: #f8f9fa;
        }

        /* Error State */
        .error-state {
            text-align: center;
            padding: 60px 20px;
            color: #626F86;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .error-state .icon {
            font-size: 48px;
            margin-bottom: 15px;
            opacity: 0.3;
        }

        .error-state h3 {
            color: #053657;
            margin-bottom: 10px;
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
            const errorState = document.getElementById('error-state');

            // Show loading
            summaryCard.innerHTML = '<div class="spinner"></div>';
            resolutionGrid.innerHTML = '<div class="spinner"></div>';
            errorState.classList.add('hidden');

            try {
                // Fetch H3 stats from API
                const response = await fetchJSON(`${API_BASE_URL}/api/h3/stats`);

                // Render summary
                renderSummary(response);

                // Render resolution cards
                renderResolutionGrid(response);

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
                        <span class="summary-value purple">${totalCells.toLocaleString()}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Populated Levels</span>
                        <span class="summary-value">${populatedLevels} / 6</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Schema</span>
                        <span class="summary-value" style="font-size: 16px;">h3.grids</span>
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
            document.getElementById('error-state').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }
        """
