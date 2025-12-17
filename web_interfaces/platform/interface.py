"""
Platform Configuration Interface.

Shows DDH (Development Data Hub) integration configuration, Platform API endpoints,
and system health status.

The Platform layer is an Anti-Corruption Layer (ACL) that translates DDH requests
to CoreMachine jobs, providing stable internal APIs while DDH APIs may evolve.
"""

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface


@InterfaceRegistry.register('platform')
class PlatformInterface(BaseInterface):
    """
    Platform configuration and DDH integration dashboard.

    Shows:
        - DDH configuration patterns (table naming, output folders, STAC IDs)
        - Valid input containers and access levels
        - Platform API endpoints with documentation
        - Placeholder for DDH application health (future)
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Platform configuration page."""
        return self.wrap_html(
            title="Platform Configuration - DDH Integration",
            content=self._generate_html_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js()
        )

    def _generate_css(self) -> str:
        """Platform-specific styles."""
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

            .section {
                background: white;
                border-radius: 8px;
                padding: 24px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .section h2 {
                color: var(--ds-navy);
                font-size: 20px;
                margin: 0 0 16px 0;
                padding-bottom: 12px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .config-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 16px;
            }

            .config-card {
                background: var(--ds-bg);
                border: 1px solid var(--ds-gray-light);
                border-radius: 6px;
                padding: 16px;
            }

            .config-card h3 {
                color: var(--ds-blue-primary);
                font-size: 14px;
                margin: 0 0 8px 0;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .config-value {
                font-family: 'Monaco', 'Consolas', monospace;
                font-size: 13px;
                background: white;
                padding: 8px 12px;
                border-radius: 4px;
                border: 1px solid #ddd;
                word-break: break-all;
            }

            .tag-list {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 8px;
            }

            .tag {
                background: var(--ds-blue-primary);
                color: white;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
            }

            .tag.bronze { background: #8B4513; }
            .tag.silver { background: #6c757d; }
            .tag.gold { background: #DAA520; }
            .tag.public { background: #28a745; }
            .tag.ouo { background: #ffc107; color: #333; }
            .tag.restricted { background: #dc3545; }

            .endpoint-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }

            .endpoint-table th,
            .endpoint-table td {
                padding: 12px;
                text-align: left;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .endpoint-table th {
                background: var(--ds-bg);
                font-weight: 600;
                color: var(--ds-navy);
            }

            .endpoint-table tr:hover {
                background: #f8f9fa;
            }

            .method {
                font-family: monospace;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
            }

            .method.post { background: #d4edda; color: #155724; }
            .method.get { background: #cce5ff; color: #004085; }

            .endpoint-path {
                font-family: monospace;
                color: var(--ds-blue-primary);
            }

            .status-card {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 16px;
                background: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 6px;
            }

            .status-icon {
                font-size: 24px;
            }

            .status-text h4 {
                margin: 0 0 4px 0;
                color: #856404;
            }

            .status-text p {
                margin: 0;
                font-size: 13px;
                color: #856404;
            }

            .live-status {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
            }

            .live-status.healthy {
                background: #d4edda;
                color: #155724;
            }

            .live-status.loading {
                background: #fff3cd;
                color: #856404;
            }

            .live-status.error {
                background: #f8d7da;
                color: #721c24;
            }

            .pulse {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: currentColor;
                animation: pulse 2s infinite;
            }

            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
        """

    def _generate_html_content(self) -> str:
        """Generate main content HTML."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Platform Configuration</h1>
                <p class="subtitle">DDH (Development Data Hub) Integration Settings</p>
            </header>

            <!-- Platform Health Status -->
            <div class="section">
                <h2>Platform Status</h2>
                <div style="display: flex; gap: 20px; flex-wrap: wrap;">
                    <div>
                        <strong>API Status:</strong>
                        <span id="platform-status" class="live-status loading">
                            <span class="pulse"></span> Checking...
                        </span>
                    </div>
                    <div>
                        <strong>Jobs (24h):</strong>
                        <span id="jobs-count">--</span>
                    </div>
                    <div>
                        <strong>Success Rate:</strong>
                        <span id="success-rate">--</span>
                    </div>
                </div>
            </div>

            <!-- DDH Configuration -->
            <div class="section">
                <h2>DDH Naming Patterns</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Platform translates DDH identifiers (dataset_id, resource_id, version_id) to CoreMachine outputs using these patterns:
                </p>
                <div class="config-grid">
                    <div class="config-card">
                        <h3>PostGIS Table Name</h3>
                        <div class="config-value">{dataset_id}_{resource_id}_{version_id}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial_imagery_site_alpha_v1_0
                        </p>
                    </div>
                    <div class="config-card">
                        <h3>Raster Output Folder</h3>
                        <div class="config-value">{dataset_id}/{resource_id}/{version_id}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial-imagery/site-alpha/v1.0
                        </p>
                    </div>
                    <div class="config-card">
                        <h3>STAC Collection ID</h3>
                        <div class="config-value">{dataset_id}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial-imagery
                        </p>
                    </div>
                    <div class="config-card">
                        <h3>STAC Item ID</h3>
                        <div class="config-value">{dataset_id}_{resource_id}_{version_id}</div>
                        <p style="font-size: 12px; color: #666; margin-top: 8px;">
                            Example: aerial-imagery-site-alpha-v1-0
                        </p>
                    </div>
                </div>
            </div>

            <!-- Valid Containers -->
            <div class="section">
                <h2>Valid Input Containers</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    DDH can submit data from these Bronze tier containers:
                </p>
                <div id="bronze-containers" class="tag-list">
                    <span class="tag" style="background: #ccc;">Loading...</span>
                </div>
                <p id="bronze-account" style="font-size: 12px; color: #666; margin-top: 12px;"></p>
            </div>

            <!-- Access Levels -->
            <div class="section">
                <h2>Access Levels</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Data classification levels (for future APIM enforcement):
                </p>
                <div class="tag-list">
                    <span class="tag public">public</span>
                    <span class="tag ouo">OUO (Default)</span>
                    <span class="tag restricted">restricted</span>
                </div>
            </div>

            <!-- Platform API Endpoints -->
            <div class="section">
                <h2>Platform API Endpoints</h2>
                <table class="endpoint-table">
                    <thead>
                        <tr>
                            <th>Method</th>
                            <th>Endpoint</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/submit</code></td>
                            <td>Generic DDH request submission (auto-detects data type)</td>
                        </tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/raster</code></td>
                            <td>Single raster file submission</td>
                        </tr>
                        <tr>
                            <td><span class="method post">POST</span></td>
                            <td><code class="endpoint-path">/api/platform/raster-collection</code></td>
                            <td>Multi-file raster collection (MosaicJSON)</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/status/{request_id}</code></td>
                            <td>Check request status by Platform request ID</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/status</code></td>
                            <td>List all Platform requests</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/health</code></td>
                            <td>Platform health status (simplified for DDH)</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/stats</code></td>
                            <td>Aggregated job statistics</td>
                        </tr>
                        <tr>
                            <td><span class="method get">GET</span></td>
                            <td><code class="endpoint-path">/api/platform/failures</code></td>
                            <td>Recent failures (sanitized for troubleshooting)</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- DDH Application Health (Placeholder) -->
            <div class="section">
                <h2>DDH Application Health</h2>
                <div class="status-card">
                    <span class="status-icon">🔮</span>
                    <div class="status-text">
                        <h4>Future Integration</h4>
                        <p>DDH health check URL will be configured here once available. This will show real-time status of the DDH application.</p>
                    </div>
                </div>
                <div style="margin-top: 16px; padding: 12px; background: #f8f9fa; border-radius: 4px;">
                    <code style="color: #666;">DDH_HEALTH_URL: Not configured</code>
                </div>
            </div>

            <!-- Request ID Generation -->
            <div class="section">
                <h2>Request ID Generation</h2>
                <p style="color: var(--ds-gray); margin-bottom: 16px;">
                    Platform generates deterministic, idempotent request IDs from DDH identifiers:
                </p>
                <div class="config-card">
                    <h3>Formula</h3>
                    <div class="config-value">SHA256(dataset_id | resource_id | version_id)[:32]</div>
                    <p style="font-size: 12px; color: #666; margin-top: 8px;">
                        Same inputs always produce same request_id, enabling natural deduplication.
                    </p>
                </div>
            </div>
        </div>
        """

    def _generate_js(self) -> str:
        """JavaScript for live status updates."""
        return """
        async function loadPlatformHealth() {
            const statusEl = document.getElementById('platform-status');
            const jobsEl = document.getElementById('jobs-count');
            const rateEl = document.getElementById('success-rate');

            try {
                const response = await fetch(`${API_BASE_URL}/api/platform/health`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();

                // Update status badge
                if (data.status === 'healthy') {
                    statusEl.className = 'live-status healthy';
                    statusEl.innerHTML = '<span class="pulse"></span> Healthy';
                } else {
                    statusEl.className = 'live-status error';
                    statusEl.innerHTML = '<span class="pulse"></span> ' + data.status;
                }

                // Update activity stats
                if (data.recent_activity) {
                    jobsEl.textContent = data.recent_activity.jobs_last_24h || '0';
                    rateEl.textContent = data.recent_activity.success_rate || 'N/A';
                }

            } catch (error) {
                console.error('Failed to load platform health:', error);
                statusEl.className = 'live-status error';
                statusEl.innerHTML = '<span class="pulse"></span> Error';
            }
        }

        // Load Bronze containers from storage API
        async function loadBronzeContainers() {
            const containersEl = document.getElementById('bronze-containers');
            const accountEl = document.getElementById('bronze-account');

            try {
                const response = await fetch(`${API_BASE_URL}/api/storage/containers?zone=bronze`);

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                const bronzeData = data.zones?.bronze;

                if (bronzeData && bronzeData.containers && bronzeData.containers.length > 0) {
                    // Build tags for each container
                    containersEl.innerHTML = bronzeData.containers
                        .map(name => `<span class="tag bronze">${name}</span>`)
                        .join('');

                    // Show storage account info
                    accountEl.textContent = `Storage Account: ${bronzeData.account} (${bronzeData.container_count} containers)`;
                } else if (bronzeData?.error) {
                    containersEl.innerHTML = `<span class="tag" style="background: #f8d7da; color: #721c24;">Error: ${bronzeData.error}</span>`;
                    accountEl.textContent = '';
                } else {
                    containersEl.innerHTML = '<span class="tag" style="background: #fff3cd; color: #856404;">No containers found</span>';
                    accountEl.textContent = '';
                }

            } catch (error) {
                console.error('Failed to load Bronze containers:', error);
                containersEl.innerHTML = `<span class="tag" style="background: #f8d7da; color: #721c24;">Failed to load containers</span>`;
                accountEl.textContent = '';
            }
        }

        // Load on page ready
        document.addEventListener('DOMContentLoaded', () => {
            loadPlatformHealth();
            loadBronzeContainers();
        });
        """
