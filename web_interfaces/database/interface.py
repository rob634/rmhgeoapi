# ============================================================================
# CLAUDE CONTEXT - DATABASE INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Database health and monitoring dashboard
# PURPOSE: Display PostgreSQL health, performance, and utilization metrics
# LAST_REVIEWED: 05 JAN 2026
# EXPORTS: DatabaseInterface
# DEPENDENCIES: web_interfaces.base, InterfaceRegistry
# ============================================================================
"""
Database Interface - PostgreSQL health and monitoring dashboard.

Features:
    - Connection pool utilization with visual bar
    - Database and schema size display
    - Health checks with status indicators
    - Performance metrics (cache hit ratio, index usage)
    - Long-running query detection
    - Auto-refresh capability

Route: /api/interface/database
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('database')
class DatabaseInterface(BaseInterface):
    """
    Database Health Dashboard.

    Displays PostgreSQL health metrics, performance data, and utilization.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Database dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Database Health",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content for Database dashboard."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1>Database Health</h1>
                        <p class="subtitle">PostgreSQL Performance and Health Monitoring</p>
                    </div>
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <span id="last-updated" class="last-updated"></span>
                        <button id="refreshBtn" class="refresh-button">Refresh</button>
                    </div>
                </div>
            </header>

            <!-- Summary Card -->
            <div id="summary-card" class="summary-card">
                <div class="spinner"></div>
            </div>

            <!-- Main Grid -->
            <div class="db-grid">
                <!-- Connection Pool Card -->
                <div class="panel">
                    <h3 class="panel-title">Connection Pool</h3>
                    <div id="connection-pool" class="panel-content">
                        <div class="spinner"></div>
                    </div>
                </div>

                <!-- Database Sizes Card -->
                <div class="panel">
                    <h3 class="panel-title">Database Size</h3>
                    <div id="db-sizes" class="panel-content">
                        <div class="spinner"></div>
                    </div>
                </div>
            </div>

            <!-- Health Checks -->
            <div class="section-title">Health Checks</div>
            <div id="health-checks" class="health-grid">
                <div class="spinner"></div>
            </div>

            <!-- Performance Metrics -->
            <div class="section-title">Performance Metrics</div>
            <div id="performance-metrics" class="performance-grid">
                <div class="spinner"></div>
            </div>

            <!-- Info Section -->
            <div class="info-section">
                <div class="section-title">Quick Actions</div>
                <div class="info-content">
                    <div class="action-links">
                        <a href="/api/dbadmin/health" target="_blank" class="action-link">
                            <span class="action-icon">API</span>
                            <span class="action-text">Raw Health JSON</span>
                        </a>
                        <a href="/api/dbadmin/health/performance" target="_blank" class="action-link">
                            <span class="action-icon">API</span>
                            <span class="action-text">Performance JSON</span>
                        </a>
                        <a href="/api/dbadmin/health/utilization" target="_blank" class="action-link">
                            <span class="action-icon">API</span>
                            <span class="action-text">Utilization JSON</span>
                        </a>
                        <a href="/api/dbadmin/stats" target="_blank" class="action-link">
                            <span class="action-icon">API</span>
                            <span class="action-text">Database Stats</span>
                        </a>
                        <a href="/api/dbadmin/diagnostics/all" target="_blank" class="action-link">
                            <span class="action-icon">API</span>
                            <span class="action-text">All Diagnostics</span>
                        </a>
                    </div>
                </div>
            </div>

            <!-- Error State -->
            <div id="error-state" class="error-state hidden">
                <div class="icon">database</div>
                <h3>Error Loading Data</h3>
                <p id="error-message"></p>
                <button onclick="loadData()" class="refresh-button" style="margin-top: 20px;">Retry</button>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Database dashboard."""
        return """
        .dashboard-header {
            background: white;
            padding: 25px 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            border-left: 4px solid #0071BC;
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

        .last-updated {
            font-size: 12px;
            color: #626F86;
        }

        .refresh-button {
            background: #0071BC;
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
            background: #005a96;
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

        .summary-value.healthy {
            color: #10b981;
        }

        .summary-value.warning {
            color: #f59e0b;
        }

        .summary-value.error {
            color: #ef4444;
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

        /* DB Grid */
        .db-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .panel {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            overflow: hidden;
        }

        .panel-title {
            font-size: 14px;
            font-weight: 700;
            color: #053657;
            padding: 15px 20px;
            margin: 0;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
        }

        .panel-content {
            padding: 20px;
            min-height: 150px;
        }

        /* Connection Pool */
        .pool-bar-container {
            margin-bottom: 20px;
        }

        .pool-bar-label {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 13px;
        }

        .pool-bar {
            height: 24px;
            background: #e9ecef;
            border-radius: 12px;
            overflow: hidden;
            position: relative;
        }

        .pool-bar-fill {
            height: 100%;
            border-radius: 12px;
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 12px;
        }

        .pool-bar-fill.healthy {
            background: linear-gradient(90deg, #10b981, #059669);
        }

        .pool-bar-fill.warning {
            background: linear-gradient(90deg, #f59e0b, #d97706);
        }

        .pool-bar-fill.error {
            background: linear-gradient(90deg, #ef4444, #dc2626);
        }

        .pool-stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-top: 15px;
        }

        .pool-stat {
            text-align: center;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 6px;
        }

        .pool-stat-value {
            font-size: 20px;
            font-weight: 700;
            color: #053657;
        }

        .pool-stat-label {
            font-size: 11px;
            color: #626F86;
            text-transform: uppercase;
            margin-top: 4px;
        }

        /* Database Sizes */
        .size-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #e9ecef;
        }

        .size-item:last-child {
            border-bottom: none;
        }

        .size-item.total {
            background: #f8f9fa;
            margin: 0 -20px;
            padding: 15px 20px;
            font-weight: 700;
        }

        .size-label {
            font-size: 14px;
            color: #053657;
        }

        .size-value {
            font-size: 14px;
            font-weight: 600;
            color: #0071BC;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        /* Health Checks */
        .health-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }

        .health-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            display: flex;
            align-items: flex-start;
            gap: 15px;
            transition: all 0.2s;
        }

        .health-card.healthy {
            border-color: #10b981;
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
        }

        .health-card.warning {
            border-color: #f59e0b;
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
        }

        .health-card.error {
            border-color: #ef4444;
            background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
        }

        .health-icon {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            flex-shrink: 0;
        }

        .health-card.healthy .health-icon {
            background: #10b981;
            color: white;
        }

        .health-card.warning .health-icon {
            background: #f59e0b;
            color: white;
        }

        .health-card.error .health-icon {
            background: #ef4444;
            color: white;
        }

        .health-info {
            flex: 1;
        }

        .health-name {
            font-size: 14px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 4px;
            text-transform: capitalize;
        }

        .health-message {
            font-size: 13px;
            color: #626F86;
        }

        /* Performance Metrics */
        .performance-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .metric-card {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .metric-value {
            font-size: 32px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 5px;
        }

        .metric-value.good {
            color: #10b981;
        }

        .metric-value.warning {
            color: #f59e0b;
        }

        .metric-value.bad {
            color: #ef4444;
        }

        .metric-label {
            font-size: 12px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .metric-detail {
            font-size: 11px;
            color: #9ca3af;
            margin-top: 8px;
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

        .action-links {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }

        .action-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 16px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            text-decoration: none;
            color: #053657;
            font-size: 13px;
            transition: all 0.2s;
        }

        .action-link:hover {
            background: #e9ecef;
            border-color: #0071BC;
        }

        .action-icon {
            font-size: 10px;
            font-weight: 700;
            background: #0071BC;
            color: white;
            padding: 2px 6px;
            border-radius: 3px;
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
        """Generate custom JavaScript for Database dashboard."""
        return """
        // Load data on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadData();
            document.getElementById('refreshBtn').addEventListener('click', loadData);
        });

        async function loadData() {
            const summaryCard = document.getElementById('summary-card');
            const connectionPool = document.getElementById('connection-pool');
            const dbSizes = document.getElementById('db-sizes');
            const healthChecks = document.getElementById('health-checks');
            const performanceMetrics = document.getElementById('performance-metrics');
            const errorState = document.getElementById('error-state');

            // Show loading
            summaryCard.innerHTML = '<div class="spinner"></div>';
            connectionPool.innerHTML = '<div class="spinner"></div>';
            dbSizes.innerHTML = '<div class="spinner"></div>';
            healthChecks.innerHTML = '<div class="spinner"></div>';
            performanceMetrics.innerHTML = '<div class="spinner"></div>';
            errorState.classList.add('hidden');

            try {
                // Fetch health and performance data in parallel
                const [healthResponse, performanceResponse] = await Promise.all([
                    fetchJSON(`${API_BASE_URL}/api/dbadmin/health`),
                    fetchJSON(`${API_BASE_URL}/api/dbadmin/health/performance`)
                ]);

                // Update last updated time
                const lastUpdated = document.getElementById('last-updated');
                lastUpdated.textContent = 'Updated: ' + formatTime(new Date());

                // Render all sections
                renderSummary(healthResponse);
                renderConnectionPool(healthResponse.connection_pool);
                renderDatabaseSizes(healthResponse.database_size);
                renderHealthChecks(healthResponse.checks);
                renderPerformanceMetrics(performanceResponse);

            } catch (error) {
                console.error('Error loading database data:', error);
                showError(error.message || 'Failed to load database health data');
            }
        }

        function renderSummary(data) {
            const status = data.status || 'unknown';
            const pool = data.connection_pool || {};
            const vacuum = data.vacuum_status || {};

            let statusClass = status === 'healthy' ? 'healthy' : (status === 'warning' ? 'warning' : 'error');
            let statusIcon = status === 'healthy' ? 'check' : (status === 'warning' ? '!' : 'X');

            const html = `
                <div class="summary-grid">
                    <div class="summary-item">
                        <span class="summary-label">Status</span>
                        <span class="summary-value ${statusClass}">${status.toUpperCase()}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Connections</span>
                        <span class="summary-value">${pool.total || 0} / ${pool.max || 50}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Pool Utilization</span>
                        <span class="summary-value ${pool.utilization_percent > 80 ? 'error' : (pool.utilization_percent > 50 ? 'warning' : 'healthy')}">${(pool.utilization_percent || 0).toFixed(1)}%</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Need Vacuum</span>
                        <span class="summary-value ${vacuum.tables_needing_vacuum > 0 ? 'warning' : 'healthy'}">${vacuum.tables_needing_vacuum || 0}</span>
                    </div>
                </div>
            `;

            document.getElementById('summary-card').innerHTML = html;
        }

        function renderConnectionPool(pool) {
            if (!pool) {
                document.getElementById('connection-pool').innerHTML = '<p>No connection pool data</p>';
                return;
            }

            const utilization = pool.utilization_percent || 0;
            let barClass = 'healthy';
            if (utilization > 80) barClass = 'error';
            else if (utilization > 50) barClass = 'warning';

            const html = `
                <div class="pool-bar-container">
                    <div class="pool-bar-label">
                        <span>Pool Utilization</span>
                        <span>${pool.total} / ${pool.max} connections</span>
                    </div>
                    <div class="pool-bar">
                        <div class="pool-bar-fill ${barClass}" style="width: ${Math.min(utilization, 100)}%">
                            ${utilization.toFixed(1)}%
                        </div>
                    </div>
                </div>
                <div class="pool-stats">
                    <div class="pool-stat">
                        <div class="pool-stat-value">${pool.active || 0}</div>
                        <div class="pool-stat-label">Active</div>
                    </div>
                    <div class="pool-stat">
                        <div class="pool-stat-value">${pool.idle || 0}</div>
                        <div class="pool-stat-label">Idle</div>
                    </div>
                    <div class="pool-stat">
                        <div class="pool-stat-value">${pool.max || 50}</div>
                        <div class="pool-stat-label">Max</div>
                    </div>
                </div>
            `;

            document.getElementById('connection-pool').innerHTML = html;
        }

        function renderDatabaseSizes(sizes) {
            if (!sizes) {
                document.getElementById('db-sizes').innerHTML = '<p>No size data</p>';
                return;
            }

            const html = `
                <div class="size-item total">
                    <span class="size-label">Total Database</span>
                    <span class="size-value">${sizes.total || 'N/A'}</span>
                </div>
                <div class="size-item">
                    <span class="size-label">app schema</span>
                    <span class="size-value">${sizes.app_schema || 'N/A'}</span>
                </div>
                <div class="size-item">
                    <span class="size-label">geo schema</span>
                    <span class="size-value">${sizes.geo_schema || 'N/A'}</span>
                </div>
                <div class="size-item">
                    <span class="size-label">pgstac schema</span>
                    <span class="size-value">${sizes.pgstac_schema || 'N/A'}</span>
                </div>
            `;

            document.getElementById('db-sizes').innerHTML = html;
        }

        function renderHealthChecks(checks) {
            if (!checks || checks.length === 0) {
                document.getElementById('health-checks').innerHTML = '<p>No health checks available</p>';
                return;
            }

            let html = '';
            checks.forEach(check => {
                const status = check.status || 'unknown';
                const icon = status === 'healthy' ? '&#10003;' : (status === 'warning' ? '!' : '&#10007;');
                const name = (check.name || '').replace(/_/g, ' ');

                html += `
                    <div class="health-card ${status}">
                        <div class="health-icon">${icon}</div>
                        <div class="health-info">
                            <div class="health-name">${name}</div>
                            <div class="health-message">${check.message || ''}</div>
                        </div>
                    </div>
                `;
            });

            document.getElementById('health-checks').innerHTML = html;
        }

        function renderPerformanceMetrics(perf) {
            if (!perf) {
                document.getElementById('performance-metrics').innerHTML = '<p>No performance data</p>';
                return;
            }

            const cacheHit = (perf.cache_hit_ratio || 0) * 100;
            const indexHit = (perf.index_hit_ratio || 0) * 100;
            const txStats = perf.transaction_stats || {};
            const seqScans = perf.sequential_scans || {};

            // Determine classes based on thresholds
            let cacheClass = cacheHit >= 99 ? 'good' : (cacheHit >= 95 ? 'warning' : 'bad');
            let indexClass = indexHit >= 95 ? 'good' : (indexHit >= 90 ? 'warning' : 'bad');
            let rollbackClass = txStats.rollback_ratio < 0.01 ? 'good' : (txStats.rollback_ratio < 0.05 ? 'warning' : 'bad');

            const html = `
                <div class="metric-card">
                    <div class="metric-value ${cacheClass}">${cacheHit.toFixed(2)}%</div>
                    <div class="metric-label">Cache Hit Ratio</div>
                    <div class="metric-detail">Target: &gt; 99%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value ${indexClass}">${indexHit.toFixed(2)}%</div>
                    <div class="metric-label">Index Hit Ratio</div>
                    <div class="metric-detail">Target: &gt; 95%</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${(txStats.commits || 0).toLocaleString()}</div>
                    <div class="metric-label">Total Commits</div>
                    <div class="metric-detail">Since last restart</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value ${rollbackClass}">${((txStats.rollback_ratio || 0) * 100).toFixed(2)}%</div>
                    <div class="metric-label">Rollback Ratio</div>
                    <div class="metric-detail">${txStats.rollbacks || 0} rollbacks</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value">${(seqScans.total || 0).toLocaleString()}</div>
                    <div class="metric-label">Sequential Scans</div>
                    <div class="metric-detail">${(seqScans.tables_with_high_seqscans || []).length} hot tables</div>
                </div>
            `;

            document.getElementById('performance-metrics').innerHTML = html;
        }

        function showError(message) {
            document.getElementById('summary-card').innerHTML = '';
            document.getElementById('connection-pool').innerHTML = '';
            document.getElementById('db-sizes').innerHTML = '';
            document.getElementById('health-checks').innerHTML = '';
            document.getElementById('performance-metrics').innerHTML = '';
            document.getElementById('error-state').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }
        """
