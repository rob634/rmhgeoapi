"""
Health monitoring interface module.

Web dashboard for viewing system health status with component cards and expandable details.

Exports:
    HealthInterface: Health monitoring dashboard with status badges and component grid
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('health')
class HealthInterface(BaseInterface):
    """
    Health Monitoring Dashboard interface.

    Displays system health status with:
        - Overall status banner
        - Component cards with status badges
        - Expandable details for each component
        - Refresh button and auto-load on page load
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Health Dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="System Health Dashboard",
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
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">
                    <div>
                        <h1>System Health Dashboard</h1>
                        <p class="subtitle">Real-time platform health monitoring</p>
                    </div>
                    <div class="header-actions">
                        <button onclick="loadHealth()" class="refresh-button" id="refresh-btn">
                            Refresh
                        </button>
                        <span id="last-checked" class="last-checked"></span>
                    </div>
                </div>
            </header>

            <!-- Overall Status Banner -->
            <div id="overall-status" class="overall-status loading">
                <div class="spinner"></div>
                <div>
                    <span>Loading health status...</span>
                    <div class="loading-hint">Health check may take up to 60 seconds</div>
                </div>
            </div>

            <!-- Error Banner (hidden by default) -->
            <div id="error-banner" class="error-banner hidden">
                <strong>Error:</strong> <span id="error-message"></span>
            </div>

            <!-- Environment Info -->
            <div id="environment-info" class="environment-info hidden"></div>

            <!-- Components Grid -->
            <div id="components-grid" class="components-grid">
                <!-- Components will be inserted here -->
            </div>

            <!-- Debug Info (if DEBUG_MODE=true) -->
            <div id="debug-info" class="debug-info hidden"></div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Health Dashboard."""
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
            margin-bottom: 8px;
            font-weight: 700;
        }

        .subtitle {
            color: #626F86;
            font-size: 16px;
            margin: 0;
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .refresh-button {
            padding: 10px 20px;
            background: #0071BC;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
        }

        .refresh-button:hover {
            background: #00A3DA;
        }

        .refresh-button:disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        .last-checked {
            color: #626F86;
            font-size: 13px;
        }

        /* Overall Status Banner */
        .overall-status {
            padding: 25px 30px;
            border-radius: 3px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 18px;
            font-weight: 600;
        }

        .overall-status.loading {
            background: #f8f9fa;
            color: #626F86;
            border: 1px solid #e9ecef;
        }

        .loading-hint {
            font-size: 13px;
            font-weight: 400;
            margin-top: 5px;
            opacity: 0.8;
        }

        .overall-status.healthy {
            background: #D1FAE5;
            color: #065F46;
            border: 1px solid #10B981;
        }

        .overall-status.unhealthy {
            background: #FEE2E2;
            color: #991B1B;
            border: 1px solid #DC2626;
        }

        .overall-status .status-icon {
            font-size: 32px;
        }

        .overall-status .status-details {
            font-size: 14px;
            font-weight: 400;
            margin-top: 5px;
            opacity: 0.9;
        }

        /* Error Banner */
        .error-banner {
            background: #FEE2E2;
            border: 1px solid #DC2626;
            border-left: 4px solid #DC2626;
            color: #991B1B;
            padding: 15px 20px;
            border-radius: 3px;
            margin-bottom: 20px;
        }

        /* Environment Info */
        .environment-info {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 20px;
            margin-bottom: 20px;
        }

        .environment-info h3 {
            color: #053657;
            font-size: 16px;
            margin-bottom: 15px;
            font-weight: 600;
        }

        .env-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
        }

        .env-item {
            background: #f8f9fa;
            padding: 10px 15px;
            border-radius: 3px;
            font-size: 13px;
        }

        .env-label {
            color: #626F86;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .env-value {
            color: #053657;
            font-weight: 600;
            margin-top: 3px;
            word-break: break-all;
        }

        /* Components Grid */
        .components-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
        }

        /* Component Card */
        .component-card {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            overflow: hidden;
            transition: box-shadow 0.2s;
        }

        .component-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }

        .component-card.healthy {
            border-left: 4px solid #10B981;
        }

        .component-card.unhealthy,
        .component-card.error {
            border-left: 4px solid #DC2626;
        }

        .component-card.disabled,
        .component-card.deprecated {
            border-left: 4px solid #626F86;
        }

        .component-card.warning,
        .component-card.partial {
            border-left: 4px solid #F59E0B;
        }

        .component-header {
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            transition: background 0.2s;
        }

        .component-header:hover {
            background: #f8f9fa;
        }

        .component-name {
            font-size: 15px;
            font-weight: 600;
            color: #053657;
        }

        .component-description {
            font-size: 12px;
            color: #626F86;
            margin-top: 3px;
        }

        /* Status Badge */
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .status-badge.healthy {
            background: #D1FAE5;
            color: #065F46;
        }

        .status-badge.unhealthy,
        .status-badge.error {
            background: #FEE2E2;
            color: #991B1B;
        }

        .status-badge.disabled,
        .status-badge.deprecated {
            background: #e9ecef;
            color: #626F86;
        }

        .status-badge.warning,
        .status-badge.partial {
            background: #FEF3C7;
            color: #92400E;
        }

        /* Component Details */
        .component-details {
            padding: 0 20px 20px 20px;
            border-top: 1px solid #e9ecef;
            background: #f8f9fa;
            display: none;
        }

        .component-details.expanded {
            display: block;
        }

        .details-content {
            padding-top: 15px;
        }

        .detail-section {
            margin-bottom: 15px;
        }

        .detail-section:last-child {
            margin-bottom: 0;
        }

        .detail-label {
            font-size: 11px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }

        .detail-value {
            font-size: 13px;
            color: #053657;
        }

        .detail-json {
            background: #053657;
            color: #f8f9fa;
            padding: 12px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
            font-size: 11px;
            overflow-x: auto;
            max-height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
        }

        /* Expand indicator */
        .expand-indicator {
            color: #626F86;
            font-size: 12px;
            transition: transform 0.2s;
        }

        .component-header.expanded .expand-indicator {
            transform: rotate(180deg);
        }

        /* Debug Info */
        .debug-info {
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            border-radius: 3px;
            padding: 20px;
            margin-top: 20px;
        }

        .debug-info h3 {
            color: #92400E;
            font-size: 14px;
            margin-bottom: 10px;
        }

        /* Identity Info */
        .identity-section {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 20px;
            margin-bottom: 20px;
        }

        .identity-section h3 {
            color: #053657;
            font-size: 16px;
            margin-bottom: 15px;
            font-weight: 600;
        }

        .identity-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }

        .identity-card {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 15px;
        }

        .identity-card h4 {
            color: #053657;
            font-size: 14px;
            margin-bottom: 10px;
            font-weight: 600;
        }

        .identity-item {
            font-size: 13px;
            color: #626F86;
            margin-bottom: 5px;
        }

        .identity-item strong {
            color: #053657;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for Health Dashboard."""
        return """
        // Load health data on page load
        document.addEventListener('DOMContentLoaded', loadHealth);

        // Load health data from API
        async function loadHealth() {
            const refreshBtn = document.getElementById('refresh-btn');
            const overallStatus = document.getElementById('overall-status');
            const errorBanner = document.getElementById('error-banner');
            const componentsGrid = document.getElementById('components-grid');

            // Disable refresh button and show loading
            refreshBtn.disabled = true;
            refreshBtn.textContent = 'Loading...';
            overallStatus.className = 'overall-status loading';
            overallStatus.innerHTML = '<div class="spinner"></div><span>Loading health status...</span>';
            errorBanner.classList.add('hidden');
            componentsGrid.innerHTML = '';

            try {
                const data = await fetchJSON(`${API_BASE_URL}/api/health`);

                // Render overall status
                renderOverallStatus(data);

                // Render environment info
                renderEnvironmentInfo(data);

                // Render identity info
                renderIdentityInfo(data);

                // Render component cards
                renderComponents(data.components);

                // Render debug info if present
                renderDebugInfo(data);

                // Update last checked timestamp
                updateLastChecked(data.timestamp);

            } catch (error) {
                console.error('Error loading health data:', error);
                overallStatus.className = 'overall-status unhealthy';
                overallStatus.innerHTML = `
                    <span class="status-icon">&#x274C;</span>
                    <div>
                        <div>Failed to load health data</div>
                        <div class="status-details">${error.message || 'Unknown error'}</div>
                    </div>
                `;
                errorBanner.classList.remove('hidden');
                document.getElementById('error-message').textContent = error.message || 'Failed to fetch health endpoint';
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = 'Refresh';
            }
        }

        // Render overall status banner
        function renderOverallStatus(data) {
            const overallStatus = document.getElementById('overall-status');
            const status = data.status || 'unknown';
            const errors = data.errors || [];
            const components = data.components || {};
            const componentCount = Object.keys(components).length;

            let statusIcon, statusText;
            if (status === 'healthy') {
                statusIcon = '&#x2705;';
                statusText = 'All Systems Operational';
            } else if (status === 'unhealthy') {
                statusIcon = '&#x274C;';
                statusText = 'System Issues Detected';
            } else {
                statusIcon = '&#x26A0;';
                statusText = 'Unknown Status';
            }

            overallStatus.className = `overall-status ${status}`;
            overallStatus.innerHTML = `
                <span class="status-icon">${statusIcon}</span>
                <div>
                    <div>${statusText}</div>
                    <div class="status-details">${componentCount} components checked ${errors.length > 0 ? '&bull; ' + errors.length + ' warning(s)' : ''}</div>
                </div>
            `;
        }

        // Render environment info section
        function renderEnvironmentInfo(data) {
            const envInfo = document.getElementById('environment-info');
            const env = data.environment || {};

            if (Object.keys(env).length === 0) {
                envInfo.classList.add('hidden');
                return;
            }

            envInfo.classList.remove('hidden');
            envInfo.innerHTML = `
                <h3>Environment</h3>
                <div class="env-grid">
                    ${Object.entries(env).map(([key, value]) => `
                        <div class="env-item">
                            <div class="env-label">${formatLabel(key)}</div>
                            <div class="env-value">${value || 'N/A'}</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        // Render identity info section
        function renderIdentityInfo(data) {
            const identity = data.identity;
            if (!identity) return;

            const envInfo = document.getElementById('environment-info');

            const identityHtml = `
                <div class="identity-section">
                    <h3>Authentication & Identity</h3>
                    <div class="identity-grid">
                        ${identity.database ? `
                            <div class="identity-card">
                                <h4>Database Authentication</h4>
                                <div class="identity-item"><strong>Method:</strong> ${identity.database.auth_method || 'N/A'}</div>
                                <div class="identity-item"><strong>Managed Identity:</strong> ${identity.database.use_managed_identity ? 'Yes' : 'No'}</div>
                                ${identity.database.admin_identity_name ? `<div class="identity-item"><strong>Identity:</strong> ${identity.database.admin_identity_name}</div>` : ''}
                            </div>
                        ` : ''}
                        ${identity.storage ? `
                            <div class="identity-card">
                                <h4>Storage Authentication</h4>
                                <div class="identity-item"><strong>Method:</strong> ${identity.storage.auth_method || 'N/A'}</div>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;

            envInfo.insertAdjacentHTML('afterend', identityHtml);
        }

        // Render component cards
        function renderComponents(components) {
            const grid = document.getElementById('components-grid');

            if (!components || Object.keys(components).length === 0) {
                grid.innerHTML = '<p style="color: #626F86; text-align: center; padding: 40px;">No components to display</p>';
                return;
            }

            // Sort components: healthy first, then unhealthy, then disabled/deprecated
            const sortOrder = { healthy: 0, partial: 1, warning: 2, unhealthy: 3, error: 4, disabled: 5, deprecated: 6 };
            const sortedComponents = Object.entries(components).sort((a, b) => {
                const statusA = sortOrder[a[1].status] ?? 99;
                const statusB = sortOrder[b[1].status] ?? 99;
                return statusA - statusB;
            });

            grid.innerHTML = sortedComponents.map(([name, component]) => {
                const status = component.status || 'unknown';
                const description = component.description || '';
                const details = component.details || {};
                const checkedAt = component.checked_at;

                return `
                    <div class="component-card ${status}">
                        <div class="component-header" onclick="toggleDetails('${name}')">
                            <div>
                                <div class="component-name">${formatLabel(name)}</div>
                                ${description ? `<div class="component-description">${description}</div>` : ''}
                            </div>
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span class="status-badge ${status}">${getStatusIcon(status)} ${status}</span>
                                <span class="expand-indicator">&#x25BC;</span>
                            </div>
                        </div>
                        <div class="component-details" id="details-${name}">
                            <div class="details-content">
                                ${checkedAt ? `
                                    <div class="detail-section">
                                        <div class="detail-label">Last Checked</div>
                                        <div class="detail-value">${new Date(checkedAt).toLocaleString()}</div>
                                    </div>
                                ` : ''}
                                ${Object.keys(details).length > 0 ? `
                                    <div class="detail-section">
                                        <div class="detail-label">Details</div>
                                        <div class="detail-json">${JSON.stringify(details, null, 2)}</div>
                                    </div>
                                ` : '<div class="detail-value" style="color: #626F86;">No additional details available</div>'}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Render debug info if DEBUG_MODE=true
        function renderDebugInfo(data) {
            const debugInfo = document.getElementById('debug-info');

            if (!data._debug_mode) {
                debugInfo.classList.add('hidden');
                return;
            }

            debugInfo.classList.remove('hidden');
            debugInfo.innerHTML = `
                <h3>Debug Mode Active</h3>
                <p style="margin-bottom: 10px; font-size: 13px;">${data._debug_notice || 'DEBUG_MODE=true'}</p>
                ${data.config_sources ? `
                    <div class="detail-section">
                        <div class="detail-label">Configuration Sources</div>
                        <div class="detail-json">${JSON.stringify(data.config_sources, null, 2)}</div>
                    </div>
                ` : ''}
                ${data.debug_status ? `
                    <div class="detail-section" style="margin-top: 15px;">
                        <div class="detail-label">Debug Status</div>
                        <div class="detail-json">${JSON.stringify(data.debug_status, null, 2)}</div>
                    </div>
                ` : ''}
            `;
        }

        // Toggle component details
        function toggleDetails(name) {
            const details = document.getElementById(`details-${name}`);
            const header = details.previousElementSibling;

            if (details.classList.contains('expanded')) {
                details.classList.remove('expanded');
                header.classList.remove('expanded');
            } else {
                details.classList.add('expanded');
                header.classList.add('expanded');
            }
        }

        // Update last checked timestamp
        function updateLastChecked(timestamp) {
            const lastChecked = document.getElementById('last-checked');
            if (timestamp) {
                lastChecked.textContent = `Last checked: ${new Date(timestamp).toLocaleString()}`;
            } else {
                lastChecked.textContent = `Last checked: ${new Date().toLocaleString()}`;
            }
        }

        // Format label (snake_case to Title Case)
        function formatLabel(str) {
            return str
                .split('_')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ');
        }

        // Get status icon
        function getStatusIcon(status) {
            switch (status) {
                case 'healthy': return '&#x2705;';
                case 'unhealthy':
                case 'error': return '&#x274C;';
                case 'disabled':
                case 'deprecated': return '&#x26AB;';
                case 'warning':
                case 'partial': return '&#x26A0;';
                default: return '&#x2753;';
            }
        }
        """
