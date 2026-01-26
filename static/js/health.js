/**
 * ============================================================================
 * HEALTH DASHBOARD JAVASCRIPT
 * ============================================================================
 * Client-side logic for the System Health Dashboard.
 *
 * Dependencies:
 *   - DOCKER_WORKER_URL (injected from template)
 *   - COMPONENT_TOOLTIPS (injected from template)
 *   - API_BASE_URL (from common.js)
 * ============================================================================
 */

// Component mapping: SVG component ID -> health API component name
const COMPONENT_MAPPING = {
    'comp-platform-api': 'deployment_config',
    'comp-job-queues': 'service_bus',
    'comp-orchestrator': 'jobs',
    'comp-job-tables': 'database',
    'comp-parallel-queue': 'service_bus',
    'comp-compute-queue': 'service_bus',
    'comp-long-queue': 'service_bus',
    'comp-io-worker': 'imports',
    'comp-compute-worker': 'imports',
    'comp-container': 'service_bus',
    'comp-task-tables': 'database',
    'comp-input-storage': 'storage_containers',
    'comp-output-storage': 'storage_containers',
    'comp-output-tables': 'pgstac',
    'comp-titiler': 'titiler',
    'comp-ogc-features': 'ogc_features',
    'comp-titiler-xarray': 'titiler_xarray',
    'comp-zarr-store': 'zarr_store'
};

// ============================================================================
// COMPONENT GROUPING CONFIGURATION
// ============================================================================
// Groups components by their source system for organized display

const COMPONENT_GROUPS = {
    'function_app': {
        label: 'Function App Services',
        icon: '&#x26A1;',
        description: 'Azure Functions orchestration and API services',
        color: '#FFC14D',
        components: [
            'deployment_config',
            'jobs',
            'imports',
            'service_bus',
            'database',
            'storage_containers',
            'pgstac',
            'titiler',
            'ogc_features',
            'duckdb',
            'app_mode',
            'startup_validation',
            'schema_summary',
            'system_reference_tables',
            'vault',
            'network_environment',
            'database_config',
            'geotiler'
        ]
    },
    'docker_worker': {
        label: 'Docker Worker Services',
        icon: '&#x1F433;',
        description: 'Container-based heavy processing and queue worker',
        color: '#0071BC',
        components: [
            'runtime',
            'etl_mount',
            'auth_tokens',
            'connection_pool',
            'lifecycle'
        ]
    },
    'shared': {
        label: 'Shared Infrastructure',
        icon: '&#x1F517;',
        description: 'Resources used by both Function App and Docker Worker',
        color: '#10B981',
        components: [
            'database',
            'storage_containers',
            'service_bus'
        ]
    }
};

// Special components that derive status from TiTiler's available_features
const TITILER_FEATURE_COMPONENTS = {
    'comp-titiler-xarray': 'xarray_zarr',
    'comp-zarr-store': 'xarray_zarr'
};

// Components that derive status from DOCKER_WORKER_ENABLED setting
const DOCKER_WORKER_COMPONENTS = ['comp-long-queue', 'comp-container'];

// Component links mapping - links to related interface pages
const COMPONENT_LINKS = {
    'storage_containers': { url: '/api/interface/storage', label: 'Storage Browser', icon: '&#x1F4C1;' },
    'service_bus': { url: '/api/interface/queues', label: 'Queue Monitor', icon: '&#x1F4E8;' },
    'database': { url: '/api/interface/database', label: 'Database Monitor', icon: '&#x1F418;' }
};

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    applyDynamicTooltips();
    loadHealth();
    setupDiagramClickHandlers();
    setupDiagramHoverHandlers();
});

// Apply dynamic tooltips on page load
function applyDynamicTooltips() {
    if (typeof COMPONENT_TOOLTIPS !== 'undefined') {
        Object.entries(COMPONENT_TOOLTIPS).forEach(([compId, tooltipText]) => {
            const component = document.getElementById(compId);
            if (component) {
                component.setAttribute('data-tooltip', tooltipText);
            }
        });
    }
}

// ============================================================================
// DIAGRAM INTERACTIONS
// ============================================================================

// Click handler for diagram components
function setupDiagramClickHandlers() {
    document.querySelectorAll('.architecture-diagram .component').forEach(comp => {
        comp.addEventListener('click', () => {
            const healthKey = COMPONENT_MAPPING[comp.id];
            if (healthKey) {
                const card = document.querySelector(`[data-component-key="${healthKey}"]`);
                if (card) {
                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    card.style.boxShadow = '0 0 0 3px #0071BC';
                    setTimeout(() => {
                        card.style.boxShadow = '';
                    }, 2000);
                }
            }
        });
    });
}

// Hover handlers for diagram tooltips
function setupDiagramHoverHandlers() {
    const tooltip = document.getElementById('diagram-tooltip');
    if (!tooltip) return;

    document.querySelectorAll('.architecture-diagram .component').forEach(comp => {
        comp.addEventListener('mouseenter', (e) => {
            const tooltipText = comp.getAttribute('data-tooltip');
            if (tooltipText) {
                tooltip.textContent = tooltipText;
                tooltip.classList.add('visible');

                // Position tooltip
                const rect = comp.getBoundingClientRect();
                const diagramRect = document.querySelector('.architecture-diagram').getBoundingClientRect();
                tooltip.style.left = `${rect.left - diagramRect.left + rect.width / 2 - tooltip.offsetWidth / 2}px`;
                tooltip.style.top = `${rect.top - diagramRect.top - tooltip.offsetHeight - 10}px`;
            }
        });

        comp.addEventListener('mouseleave', () => {
            tooltip.classList.remove('visible');
        });
    });
}

// Update architecture diagram status indicators
function updateDiagramStatus(components, dockerHealth = null) {
    if (!components) return;

    const titilerComponent = components['titiler'];
    const titilerFeatures = titilerComponent?.details?.health?.body?.available_features || {};
    const appModeConfig = components['app_mode'];
    const dockerWorkerEnabled = appModeConfig?.details?.docker_worker_enabled === true;

    Object.entries(COMPONENT_MAPPING).forEach(([svgId, healthKey]) => {
        const indicator = document.querySelector(`#${svgId} .status-indicator`);
        if (!indicator) return;

        let status = 'unknown';

        if (DOCKER_WORKER_COMPONENTS.includes(svgId)) {
            if (!dockerWorkerEnabled && !DOCKER_WORKER_URL) {
                status = 'unknown';
            } else if (dockerHealth) {
                const dockerStatus = dockerHealth.status || 'unknown';
                if (dockerStatus === 'healthy') {
                    status = 'healthy';
                } else if (dockerStatus === 'unhealthy' || dockerStatus === 'unreachable') {
                    status = 'unhealthy';
                } else if (dockerStatus === 'warning') {
                    status = 'warning';
                } else {
                    status = 'unknown';
                }
            } else if (dockerWorkerEnabled) {
                status = 'warning';
            }
        } else if (TITILER_FEATURE_COMPONENTS[svgId]) {
            const featureKey = TITILER_FEATURE_COMPONENTS[svgId];
            const titilerStatus = titilerComponent?.details?.overall_status || titilerComponent?.status;
            const titilerHealthy = titilerStatus === 'healthy';

            if (titilerComponent && titilerHealthy) {
                status = titilerFeatures[featureKey] === true ? 'healthy' : 'unhealthy';
            } else if (titilerComponent) {
                status = 'warning';
            }
        } else {
            const component = components[healthKey];
            if (component) {
                if (component.details && component.details.overall_status) {
                    status = component.details.overall_status;
                } else {
                    status = component.status || 'unknown';
                }
                if (status === 'error') status = 'unhealthy';
                if (status === 'partial') status = 'warning';
                if (status === 'disabled' || status === 'deprecated') status = 'unknown';
            }
        }

        indicator.setAttribute('data-status', status);
    });
}

// ============================================================================
// DOCKER WORKER HEALTH
// ============================================================================

async function fetchDockerWorkerHealth() {
    if (!DOCKER_WORKER_URL) return null;

    try {
        const response = await fetch(`${DOCKER_WORKER_URL}/health`, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            mode: 'cors',
            signal: AbortSignal.timeout(10000)
        });

        if (!response.ok) {
            return { status: 'unhealthy', error: `HTTP ${response.status}`, url: DOCKER_WORKER_URL };
        }

        const data = await response.json();
        return { ...data, status: data.status || 'healthy', url: DOCKER_WORKER_URL };
    } catch (err) {
        return { status: 'unreachable', error: err.message, url: DOCKER_WORKER_URL };
    }
}

// ============================================================================
// FUNCTION APP HEALTH (GAP-01: Cross-System Health)
// ============================================================================

async function fetchFunctionAppHealth() {
    // Fetch FA health via our proxy endpoint
    try {
        const response = await fetch('/api/proxy/fa/health', {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            signal: AbortSignal.timeout(35000)  // Allow extra time for proxy
        });

        if (!response.ok) {
            return {
                status: 'unhealthy',
                error: `Proxy returned HTTP ${response.status}`,
                _source: 'function_app'
            };
        }

        const data = await response.json();
        return data;
    } catch (err) {
        return {
            status: 'unreachable',
            error: err.message,
            _source: 'function_app'
        };
    }
}

function updateSystemStatusCard(cardId, statusId, healthData) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;

    const status = healthData?.status || 'unknown';
    let statusIcon = '&#x26AA;';  // Grey circle
    let statusText = 'Unknown';

    if (status === 'healthy') {
        statusIcon = '&#x1F7E2;';  // Green circle
        statusText = 'Healthy';
    } else if (status === 'unhealthy' || status === 'error') {
        statusIcon = '&#x1F534;';  // Red circle
        statusText = 'Unhealthy';
    } else if (status === 'unreachable') {
        statusIcon = '&#x1F534;';  // Red circle
        statusText = 'Unreachable';
    } else if (status === 'warning') {
        statusIcon = '&#x1F7E1;';  // Yellow circle
        statusText = 'Warning';
    }

    statusEl.className = `system-status ${status}`;
    statusEl.innerHTML = `
        <span class="status-icon">${statusIcon}</span>
        <span>${statusText}</span>
        ${healthData?.error ? `<span style="font-size: 12px; color: #626F86;">(${healthData.error.substring(0, 50)}...)</span>` : ''}
    `;

    // Update component count if available
    if (healthData?.components) {
        const count = Object.keys(healthData.components).length;
        statusEl.innerHTML += `<span style="font-size: 12px; margin-left: auto; color: #626F86;">${count} components</span>`;
    }
}

function renderFunctionAppComponents(faHealth) {
    const faSection = document.getElementById('fa-health-section');
    const faGrid = document.getElementById('fa-components-grid');

    if (!faHealth || faHealth.status === 'unreachable' || !faHealth.components) {
        faSection.classList.add('hidden');
        return;
    }

    faSection.classList.remove('hidden');
    faGrid.innerHTML = '';

    const components = faHealth.components;
    const sortOrder = { healthy: 0, partial: 1, warning: 2, unhealthy: 3, error: 4, disabled: 5, deprecated: 6 };

    // Sort components by status (unhealthy first)
    const sortedComponents = Object.entries(components).sort((a, b) => {
        const statusA = (a[1].status || 'unknown').toLowerCase();
        const statusB = (b[1].status || 'unknown').toLowerCase();
        return (sortOrder[statusA] ?? 10) - (sortOrder[statusB] ?? 10);
    });

    sortedComponents.forEach(([name, component]) => {
        const status = component.status || 'unknown';
        const description = component.description || '';

        let statusBadgeClass = 'status-badge';
        if (status === 'healthy') statusBadgeClass += ' status-completed';
        else if (status === 'warning' || status === 'partial') statusBadgeClass += ' status-pending';
        else if (status === 'unhealthy' || status === 'error') statusBadgeClass += ' status-failed';
        else statusBadgeClass += ' status-queued';

        const card = document.createElement('div');
        card.className = 'component-card';
        card.setAttribute('data-component-key', name);
        card.innerHTML = `
            <div class="component-header">
                <div>
                    <div class="component-name">${formatLabel(name)}</div>
                    <div class="component-description">${description}</div>
                </div>
                <span class="${statusBadgeClass}">${status}</span>
            </div>
        `;
        faGrid.appendChild(card);
    });
}

function toggleFaSection() {
    const faSection = document.getElementById('fa-health-section');
    faSection.classList.toggle('collapsed');
}

function renderDockerWorkerInfo(dockerHealth) {
    if (!dockerHealth) return;

    const envInfo = document.getElementById('environment-info');
    if (!envInfo) return;

    const status = dockerHealth.status || 'unknown';
    const version = dockerHealth.version || 'N/A';
    const runtime = dockerHealth.runtime || {};
    const hardware = runtime.hardware || {};
    const memory = runtime.memory || {};
    const tokens = dockerHealth.tokens || {};
    const url = dockerHealth.url || DOCKER_WORKER_URL;

    let statusColor = '#6B7280';
    let statusIcon = '&#x26AA;';
    if (status === 'healthy') { statusColor = '#10B981'; statusIcon = '&#x1F7E2;'; }
    else if (status === 'unhealthy' || status === 'unreachable') { statusColor = '#DC2626'; statusIcon = '&#x1F534;'; }
    else if (status === 'warning') { statusColor = '#F59E0B'; statusIcon = '&#x1F7E1;'; }

    const pgToken = tokens.postgres || {};
    const storageToken = tokens.storage || {};
    const pgValid = pgToken.has_token === true;
    const storageValid = storageToken.has_token === true;
    const tokensValid = pgValid && storageValid;

    const cpuPercent = memory.cpu_percent || 0;
    let cpuBarColor = '#10B981';
    if (cpuPercent >= 90) cpuBarColor = '#DC2626';
    else if (cpuPercent >= 70) cpuBarColor = '#F59E0B';

    const ramPercent = memory.system_percent || 0;
    let ramBarColor = '#10B981';
    if (ramPercent >= 90) ramBarColor = '#DC2626';
    else if (ramPercent >= 70) ramBarColor = '#F59E0B';

    let displayUrl = url;
    if (displayUrl.startsWith('https://')) displayUrl = displayUrl.substring(8);
    if (displayUrl.startsWith('http://')) displayUrl = displayUrl.substring(7);
    if (displayUrl.length > 35) displayUrl = displayUrl.substring(0, 32) + '...';

    let dockerHtml;
    if (status === 'healthy' || status === 'warning') {
        dockerHtml = `
            <div class="docker-worker-section">
                <h3>&#x1F433; Docker Worker Resources</h3>
                <div class="docker-worker-grid">
                    <div class="docker-worker-card">
                        <div class="card-label">${statusIcon} Azure Site</div>
                        <div class="card-value">${hardware.azure_site_name || 'docker-worker'}</div>
                        <div class="card-sub">${hardware.azure_sku || 'Container'} &bull; v${version}</div>
                    </div>
                    <div class="docker-worker-card">
                        <div class="card-label">&#x26A1; CPU</div>
                        <div class="card-value">${hardware.cpu_count || 'N/A'} cores</div>
                        <div class="card-bar-container">
                            <div class="card-bar" style="width: ${Math.min(cpuPercent, 100)}%; background: ${cpuBarColor};"></div>
                        </div>
                        <div class="card-sub">${cpuPercent.toFixed(1)}% utilized</div>
                    </div>
                    <div class="docker-worker-card">
                        <div class="card-label">&#x1F4BE; Memory</div>
                        <div class="card-value">${hardware.total_ram_gb || 'N/A'} GB total</div>
                        <div class="card-bar-container">
                            <div class="card-bar" style="width: ${Math.min(ramPercent, 100)}%; background: ${ramBarColor};"></div>
                        </div>
                        <div class="card-sub">${memory.system_available_mb ? (memory.system_available_mb / 1024).toFixed(1) + ' GB' : 'N/A'} available (${(100 - ramPercent).toFixed(1)}% free)</div>
                    </div>
                    <div class="docker-worker-card">
                        <div class="card-label">&#x1F4CA; Process RSS</div>
                        <div class="card-value">${memory.process_rss_mb ? (memory.process_rss_mb >= 1024 ? (memory.process_rss_mb / 1024).toFixed(2) + ' GB' : memory.process_rss_mb.toFixed(0) + ' MB') : 'N/A'}</div>
                        <div class="card-sub">Current process memory</div>
                    </div>
                    <div class="docker-worker-card">
                        <div class="card-label">&#x1F5A5; Platform</div>
                        <div class="card-value">${hardware.platform || 'N/A'}</div>
                        <div class="card-sub">Python ${hardware.python_version || 'N/A'}</div>
                    </div>
                    <div class="docker-worker-card">
                        <div class="card-label">&#x1F511; Auth Tokens</div>
                        <div class="card-value" style="color: ${tokensValid ? '#10B981' : '#DC2626'}">${tokensValid ? 'Valid' : 'Issues'}</div>
                        <div class="card-sub">PG: ${pgValid ? '&#x2713;' : '&#x2717;'} Storage: ${storageValid ? '&#x2713;' : '&#x2717;'}</div>
                    </div>
                </div>
            </div>
        `;
    } else {
        dockerHtml = `
            <div class="docker-worker-section">
                <h3>&#x1F433; Docker Worker Resources</h3>
                <div class="docker-worker-grid">
                    <div class="docker-worker-card">
                        <div class="card-label">${statusIcon} Status</div>
                        <div class="card-value" style="color: ${statusColor}; text-transform: capitalize;">${status}</div>
                        <div class="card-sub">${displayUrl}</div>
                    </div>
                    <div class="docker-worker-card" style="grid-column: span 5;">
                        <div class="card-label">&#x26A0; Error</div>
                        <div class="card-value" style="color: #DC2626;">${dockerHealth.error || 'Unable to connect to Docker worker'}</div>
                        <div class="card-sub">Check Docker worker deployment and network connectivity</div>
                    </div>
                </div>
            </div>
        `;
    }

    const existingDockerSection = envInfo.parentElement.querySelector('.docker-worker-section');
    if (existingDockerSection) {
        existingDockerSection.outerHTML = dockerHtml;
    } else {
        envInfo.insertAdjacentHTML('afterend', dockerHtml);
    }
}

// ============================================================================
// MAIN HEALTH LOADER
// ============================================================================

async function loadHealth() {
    const refreshBtn = document.getElementById('refresh-btn');
    const overallStatus = document.getElementById('overall-status');
    const errorBanner = document.getElementById('error-banner');
    const componentsGrid = document.getElementById('components-grid');
    const envInfo = document.getElementById('environment-info');
    const schemaSummary = document.getElementById('schema-summary');

    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Loading...';
    overallStatus.className = 'overall-status loading';
    overallStatus.innerHTML = '<div class="spinner"></div><div><span>Loading health status...</span><div class="loading-hint">Health check may take up to 60 seconds</div></div>';
    errorBanner.classList.add('hidden');

    envInfo.classList.add('skeleton-section');
    schemaSummary.classList.add('skeleton-section');
    componentsGrid.querySelectorAll('.component-card').forEach(card => {
        card.classList.add('skeleton-card');
    });

    try {
        // Fetch Docker Worker health (this system)
        const healthPromise = fetchJSON('/health');

        // Fetch Function App health via proxy (GAP-01)
        const faHealthPromise = fetchFunctionAppHealth().catch(err => {
            console.warn('Function App health fetch failed:', err.message);
            return { status: 'unreachable', error: err.message, _source: 'function_app' };
        });

        // Fetch external Docker Worker health if configured (legacy behavior)
        let dockerHealthPromise = Promise.resolve(null);
        if (typeof DOCKER_WORKER_URL !== 'undefined' && DOCKER_WORKER_URL) {
            dockerHealthPromise = fetchDockerWorkerHealth().catch(err => {
                console.warn('Docker worker health fetch failed:', err.message);
                return { status: 'unreachable', error: err.message };
            });
        }

        // Fetch Queue Status (GAP-02)
        const queueStatusPromise = fetchQueueStatus().catch(err => {
            console.warn('Queue status fetch failed:', err.message);
            return { status: 'error', error: err.message, queues: [] };
        });

        const [data, faHealth, dockerHealth, queueStatus] = await Promise.all([healthPromise, faHealthPromise, dockerHealthPromise, queueStatusPromise]);
        window.dockerWorkerHealth = dockerHealth;
        window.functionAppHealth = faHealth;

        // Update system status cards (GAP-01)
        updateSystemStatusCard('docker-status-card', 'docker-overall-status', data);
        updateSystemStatusCard('fa-status-card', 'fa-overall-status', faHealth);

        renderOverallStatus(data);
        renderEnvironmentInfo(data);

        if (typeof DOCKER_WORKER_URL !== 'undefined' && DOCKER_WORKER_URL) {
            renderDockerWorkerInfo(dockerHealth);
        }

        renderIdentityInfo(data);
        renderComponents(data.components, dockerHealth);
        updateDiagramStatus(data.components, dockerHealth);
        renderSchemaSummary(data.components);

        // Render Function App components (GAP-01)
        renderFunctionAppComponents(faHealth);

        // Render Queue Status (GAP-02)
        renderQueueStatus(queueStatus);

        renderDebugInfo(data);
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

// ============================================================================
// RENDER FUNCTIONS
// ============================================================================

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

function renderEnvironmentInfo(data) {
    const envInfo = document.getElementById('environment-info');
    const env = data.environment || {};

    envInfo.classList.remove('skeleton-section');

    if (Object.keys(env).length === 0) {
        envInfo.classList.add('hidden');
        return;
    }

    const runtime = data.components?.runtime?.details || {};
    const hardware = runtime.hardware || {};
    const memory = runtime.memory || {};
    const instance = runtime.instance || {};

    const hwInfo = {
        ...hardware,
        ram_utilization_percent: memory.system_percent || 0,
        cpu_utilization_percent: memory.cpu_percent || 0,
        available_ram_mb: memory.system_available_mb || 0,
        process_rss_mb: memory.process_rss_mb || 0,
        azure_instance_id: instance.instance_id_short || instance.instance_id || '',
    };

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
        ${Object.keys(hwInfo).length > 0 ? renderHardwareInfo(hwInfo) : ''}
    `;
}

function renderHardwareInfo(hardware) {
    const ramPercent = hardware.ram_utilization_percent || 0;
    let ramBarColor = '#10B981';
    if (ramPercent >= 90) ramBarColor = '#DC2626';
    else if (ramPercent >= 80) ramBarColor = '#F59E0B';

    const cpuPercent = hardware.cpu_utilization_percent || 0;
    let cpuBarColor = '#10B981';
    if (cpuPercent >= 90) cpuBarColor = '#DC2626';
    else if (cpuPercent >= 70) cpuBarColor = '#F59E0B';

    return `
        <div class="hardware-section">
            <h4>Function App Resources</h4>
            <div class="hardware-grid">
                <div class="hardware-card">
                    <div class="hardware-icon">&#x2601;</div>
                    <div class="hardware-details">
                        <div class="hardware-label">Azure Site</div>
                        <div class="hardware-value">${hardware.azure_site_name || 'local'}</div>
                        <div class="hardware-sub">${hardware.azure_sku || 'N/A'} ${hardware.azure_instance_id ? '&bull; ' + hardware.azure_instance_id : ''}</div>
                    </div>
                </div>
                <div class="hardware-card">
                    <div class="hardware-icon">&#x26A1;</div>
                    <div class="hardware-details">
                        <div class="hardware-label">CPU</div>
                        <div class="hardware-value">${hardware.cpu_count || 'N/A'} cores</div>
                        <div class="hardware-bar-container">
                            <div class="hardware-bar" style="width: ${Math.min(cpuPercent, 100)}%; background: ${cpuBarColor};"></div>
                        </div>
                        <div class="hardware-sub">${cpuPercent.toFixed(1)}% utilized</div>
                    </div>
                </div>
                <div class="hardware-card">
                    <div class="hardware-icon">&#x1F4BE;</div>
                    <div class="hardware-details">
                        <div class="hardware-label">Memory</div>
                        <div class="hardware-value">${hardware.total_ram_gb || 'N/A'} GB total</div>
                        <div class="hardware-bar-container">
                            <div class="hardware-bar" style="width: ${Math.min(ramPercent, 100)}%; background: ${ramBarColor};"></div>
                        </div>
                        <div class="hardware-sub">${hardware.available_ram_mb ? (hardware.available_ram_mb / 1024).toFixed(1) + ' GB' : 'N/A'} available (${(100 - ramPercent).toFixed(1)}% free)</div>
                    </div>
                </div>
                <div class="hardware-card">
                    <div class="hardware-icon">&#x1F4CA;</div>
                    <div class="hardware-details">
                        <div class="hardware-label">Process RSS</div>
                        <div class="hardware-value">${hardware.process_rss_mb ? (hardware.process_rss_mb >= 1024 ? (hardware.process_rss_mb / 1024).toFixed(2) + ' GB' : hardware.process_rss_mb.toFixed(0) + ' MB') : 'N/A'}</div>
                        <div class="hardware-sub">Current process memory usage</div>
                    </div>
                </div>
                <div class="hardware-card">
                    <div class="hardware-icon">&#x1F5A5;</div>
                    <div class="hardware-details">
                        <div class="hardware-label">Platform</div>
                        <div class="hardware-value">${hardware.platform || 'N/A'}</div>
                        <div class="hardware-sub">Python ${hardware.python_version || 'N/A'}</div>
                    </div>
                </div>
                ${hardware.capacity_notes ? `
                <div class="hardware-card">
                    <div class="hardware-icon">&#x1F4CF;</div>
                    <div class="hardware-details">
                        <div class="hardware-label">Safe File Limit</div>
                        <div class="hardware-value">${hardware.capacity_notes.safe_file_limit_mb ? (hardware.capacity_notes.safe_file_limit_mb / 1024).toFixed(1) + ' GB' : 'N/A'}</div>
                        <div class="hardware-sub">Warn at ${hardware.capacity_notes.warning_threshold_percent}% &bull; Critical at ${hardware.capacity_notes.critical_threshold_percent}%</div>
                    </div>
                </div>
                ` : ''}
            </div>
        </div>
    `;
}

function renderIdentityInfo(data) {
    const identity = data.identity;
    if (!identity) return;

    const envInfo = document.getElementById('environment-info');

    const identityHtml = `
        <div class="identity-section">
            <h3>Authentication &amp; Identity</h3>
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

function renderComponents(components, dockerWorkerComponents = null) {
    const grid = document.getElementById('components-grid');
    grid.querySelectorAll('.skeleton-card').forEach(card => card.remove());

    if (!components || Object.keys(components).length === 0) {
        grid.innerHTML = '<p style="color: #626F86; text-align: center; padding: 40px;">No components to display</p>';
        return;
    }

    // Merge Docker Worker components if provided separately
    const allComponents = { ...components };
    if (dockerWorkerComponents && dockerWorkerComponents.components) {
        Object.entries(dockerWorkerComponents.components).forEach(([key, value]) => {
            // Prefix Docker Worker components to avoid collisions
            allComponents[`docker_${key}`] = {
                ...value,
                _source: 'docker_worker'
            };
        });
    }

    // Tag components with their source based on COMPONENT_GROUPS
    Object.keys(allComponents).forEach(name => {
        if (!allComponents[name]._source) {
            if (COMPONENT_GROUPS.docker_worker.components.includes(name) || name.startsWith('docker_')) {
                allComponents[name]._source = 'docker_worker';
            } else {
                allComponents[name]._source = 'function_app';
            }
        }
    });

    // Group components by source
    const groupedComponents = {
        function_app: [],
        docker_worker: []
    };

    Object.entries(allComponents).forEach(([name, component]) => {
        const source = component._source || 'function_app';
        if (groupedComponents[source]) {
            groupedComponents[source].push([name, component]);
        } else {
            groupedComponents.function_app.push([name, component]);
        }
    });

    // Sort within each group
    const sortOrder = { healthy: 0, partial: 1, warning: 2, unhealthy: 3, error: 4, disabled: 5, deprecated: 6 };
    Object.keys(groupedComponents).forEach(group => {
        groupedComponents[group].sort((a, b) => {
            const statusA = sortOrder[a[1].status] ?? 99;
            const statusB = sortOrder[b[1].status] ?? 99;
            return statusA - statusB;
        });
    });

    // Render grouped sections
    let html = '';

    // Function App Section
    if (groupedComponents.function_app.length > 0) {
        const faConfig = COMPONENT_GROUPS.function_app;
        const faStats = getGroupStats(groupedComponents.function_app);
        html += renderComponentGroup('function_app', faConfig, groupedComponents.function_app, faStats);
    }

    // Docker Worker Section
    if (groupedComponents.docker_worker.length > 0) {
        const dwConfig = COMPONENT_GROUPS.docker_worker;
        const dwStats = getGroupStats(groupedComponents.docker_worker);
        html += renderComponentGroup('docker_worker', dwConfig, groupedComponents.docker_worker, dwStats);
    }

    grid.innerHTML = html;
}

function getGroupStats(components) {
    const stats = { total: 0, healthy: 0, warning: 0, unhealthy: 0, disabled: 0 };
    components.forEach(([name, component]) => {
        stats.total++;
        const status = component.status || 'unknown';
        if (status === 'healthy') stats.healthy++;
        else if (status === 'warning' || status === 'partial') stats.warning++;
        else if (status === 'unhealthy' || status === 'error') stats.unhealthy++;
        else if (status === 'disabled' || status === 'deprecated') stats.disabled++;
    });
    return stats;
}

function renderComponentGroup(groupId, config, components, stats) {
    const statusClass = stats.unhealthy > 0 ? 'unhealthy' : stats.warning > 0 ? 'warning' : 'healthy';

    const cardsHtml = components.map(([name, component]) => {
        const status = component.status || 'unknown';
        const description = component.description || '';
        const details = component.details || {};
        const checkedAt = component.checked_at;
        const displayName = name.startsWith('docker_') ? name.replace('docker_', '') : name;

        const linkInfo = COMPONENT_LINKS[name] || COMPONENT_LINKS[displayName];
        let linkHtml = '';
        if (linkInfo) {
            if (linkInfo.disabled) {
                linkHtml = `<span class="component-link disabled" title="${linkInfo.label}">${linkInfo.icon} ${linkInfo.label}</span>`;
            } else {
                linkHtml = `<a href="${linkInfo.url}" class="component-link" onclick="event.stopPropagation();">${linkInfo.icon} ${linkInfo.label} &rarr;</a>`;
            }
        }

        return `
            <div class="component-card ${status}" data-component-key="${name}">
                <div class="component-header" onclick="toggleDetails('${name}')">
                    <div>
                        <div class="component-name">${formatLabel(displayName)}</div>
                        ${description ? `<div class="component-description">${description}</div>` : ''}
                        ${linkHtml}
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
                                <div class="detail-value">${formatDateTime(checkedAt)}</div>
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

    return `
        <div class="component-group ${groupId}" data-group="${groupId}">
            <div class="component-group-header ${statusClass}" style="border-left-color: ${config.color};">
                <div class="group-title">
                    <span class="group-icon">${config.icon}</span>
                    <div>
                        <h3>${config.label}</h3>
                        <p class="group-description">${config.description}</p>
                    </div>
                </div>
                <div class="group-stats">
                    <span class="group-stat total">${stats.total} components</span>
                    ${stats.healthy > 0 ? `<span class="group-stat healthy">${stats.healthy} healthy</span>` : ''}
                    ${stats.warning > 0 ? `<span class="group-stat warning">${stats.warning} warning</span>` : ''}
                    ${stats.unhealthy > 0 ? `<span class="group-stat unhealthy">${stats.unhealthy} unhealthy</span>` : ''}
                    ${stats.disabled > 0 ? `<span class="group-stat disabled">${stats.disabled} disabled</span>` : ''}
                </div>
            </div>
            <div class="component-group-cards">
                ${cardsHtml}
            </div>
        </div>
    `;
}

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

function renderSchemaSummary(components) {
    const schemaSummary = document.getElementById('schema-summary');
    const schemaCards = document.getElementById('schema-cards');

    schemaSummary.classList.remove('skeleton-section');

    const schemaSummaryData = components?.schema_summary?.details;
    if (!schemaSummaryData || !schemaSummaryData.schemas) {
        schemaSummary.classList.add('hidden');
        return;
    }

    schemaSummary.classList.remove('hidden');

    const schemas = schemaSummaryData.schemas;
    const totalTables = schemaSummaryData.total_tables || 0;

    const schemaConfig = {
        'app': { icon: '&#x2699;', label: 'Application', highlight: '' },
        'geo': { icon: '&#x1F5FA;', label: 'PostGIS', highlight: 'geo-highlight' },
        'pgstac': { icon: '&#x1F4E6;', label: 'STAC Catalog', highlight: 'stac-highlight' },
        'h3': { icon: '&#x2B22;', label: 'H3 Hexagons', highlight: '' }
    };

    let cardsHtml = '';

    Object.entries(schemas).forEach(([schemaName, schemaData]) => {
        const config = schemaConfig[schemaName] || { icon: '&#x1F4C1;', label: schemaName, highlight: '' };
        const exists = schemaData.exists;
        const tableCount = schemaData.table_count || 0;
        const tables = schemaData.tables || [];
        const rowCounts = schemaData.row_counts || {};

        let totalRows = 0;
        Object.values(rowCounts).forEach(count => {
            if (typeof count === 'number') totalRows += count;
        });

        let specialStats = '';
        if (schemaName === 'pgstac' && schemaData.stac_counts) {
            const stacCounts = schemaData.stac_counts;
            specialStats = `
                <div class="schema-stat">
                    <div class="stat-label">Collections</div>
                    <div class="stat-value highlight">${formatNumber(stacCounts.collections || 0)}</div>
                </div>
                <div class="schema-stat">
                    <div class="stat-label">Items</div>
                    <div class="stat-value highlight">${formatNumber(stacCounts.items || 0)}</div>
                </div>
            `;
        } else if (schemaName === 'geo' && schemaData.geometry_columns !== undefined) {
            specialStats = `
                <div class="schema-stat full-width">
                    <div class="stat-label">Geometry Columns</div>
                    <div class="stat-value highlight">${schemaData.geometry_columns}</div>
                </div>
            `;
        }

        let tablesListHtml = '';
        if (tables.length > 0) {
            const tableRows = tables.map(tableName => {
                const count = rowCounts[tableName];
                return `
                    <div class="table-row">
                        <span class="table-name">${tableName}</span>
                        <span class="table-count">${typeof count === 'number' ? formatNumber(count) : '-'}</span>
                    </div>
                `;
            }).join('');

            tablesListHtml = `
                <div class="schema-tables-list">
                    <div class="schema-tables-toggle" onclick="toggleSchemaTables('${schemaName}')">
                        <span>&#x25BC;</span> Show ${tables.length} tables
                    </div>
                    <div class="schema-tables-content" id="schema-tables-${schemaName}">
                        ${tableRows}
                    </div>
                </div>
            `;
        }

        cardsHtml += `
            <div class="schema-card ${exists ? config.highlight : 'not-found'}">
                <div class="schema-card-header">
                    <div class="schema-name">
                        <span class="schema-icon">${config.icon}</span>
                        ${config.label}
                    </div>
                    <span class="schema-badge ${exists ? 'exists' : 'missing'}">
                        ${exists ? 'Active' : 'Missing'}
                    </span>
                </div>
                ${exists ? `
                    <div class="schema-stats">
                        <div class="schema-stat">
                            <div class="stat-label">Tables</div>
                            <div class="stat-value">${tableCount}</div>
                        </div>
                        <div class="schema-stat">
                            <div class="stat-label">Rows (approx)</div>
                            <div class="stat-value">${formatNumber(totalRows)}</div>
                        </div>
                        ${specialStats}
                    </div>
                    ${tablesListHtml}
                ` : `
                    <div style="color: #991B1B; font-size: 12px;">
                        Schema not found in database
                    </div>
                `}
            </div>
        `;
    });

    // Add summary card
    cardsHtml = `
        <div class="schema-card" style="background: linear-gradient(135deg, #E8F4FD 0%, #F8F9FA 100%); border-color: #0071BC;">
            <div class="schema-card-header">
                <div class="schema-name">
                    <span class="schema-icon">&#x1F4CA;</span>
                    Summary
                </div>
            </div>
            <div class="schema-stats">
                <div class="schema-stat full-width">
                    <div class="stat-label">Total Tables</div>
                    <div class="stat-value highlight">${totalTables}</div>
                </div>
            </div>
        </div>
    ` + cardsHtml;

    schemaCards.innerHTML = cardsHtml;
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function toggleDetails(componentName) {
    const details = document.getElementById(`details-${componentName}`);
    const header = details.previousElementSibling;

    details.classList.toggle('expanded');
    header.classList.toggle('expanded');
}

function toggleSchemaTables(schemaName) {
    const content = document.getElementById(`schema-tables-${schemaName}`);
    const toggle = content.previousElementSibling;

    content.classList.toggle('expanded');
    if (content.classList.contains('expanded')) {
        toggle.innerHTML = '<span>&#x25B2;</span> Hide tables';
    } else {
        const tableCount = content.querySelectorAll('.table-row').length;
        toggle.innerHTML = `<span>&#x25BC;</span> Show ${tableCount} tables`;
    }
}

function updateLastChecked(timestamp) {
    const lastChecked = document.getElementById('last-checked');
    if (timestamp && lastChecked) {
        lastChecked.textContent = `Last checked: ${formatDateTime(timestamp)}`;
    }
}

function getStatusIcon(status) {
    const icons = {
        healthy: '&#x2705;',
        unhealthy: '&#x274C;',
        error: '&#x274C;',
        warning: '&#x26A0;',
        partial: '&#x26A0;',
        disabled: '&#x26AA;',
        deprecated: '&#x26AA;'
    };
    return icons[status] || '&#x2753;';
}

// ============================================================================
// QUEUE INFRASTRUCTURE (GAP-02)
// ============================================================================

async function fetchQueueStatus() {
    try {
        const response = await fetch('/api/queues/status', {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            signal: AbortSignal.timeout(30000)
        });

        if (!response.ok) {
            return { status: 'error', error: `HTTP ${response.status}`, queues: [] };
        }

        return await response.json();
    } catch (err) {
        return { status: 'error', error: err.message, queues: [] };
    }
}

async function refreshQueueStatus() {
    const refreshBtn = document.getElementById('queue-refresh-btn');
    const summary = document.getElementById('queue-summary');
    const cardsContainer = document.getElementById('queue-cards');

    if (refreshBtn) {
        refreshBtn.disabled = true;
        refreshBtn.textContent = 'Loading...';
    }

    summary.className = 'queue-summary loading';
    summary.innerHTML = '<div class="spinner-sm"></div><span>Loading queue status...</span>';

    try {
        const data = await fetchQueueStatus();
        renderQueueStatus(data);
    } catch (error) {
        console.error('Error fetching queue status:', error);
        summary.className = 'queue-summary error';
        summary.innerHTML = `<span class="status-icon">&#x274C;</span><span>Failed to load queue status: ${error.message}</span>`;
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.textContent = 'Refresh';
        }
    }
}

function renderQueueStatus(data) {
    const summary = document.getElementById('queue-summary');
    const cardsContainer = document.getElementById('queue-cards');

    if (!data || data.status === 'error') {
        summary.className = 'queue-summary error';
        summary.innerHTML = `
            <span class="status-icon">&#x274C;</span>
            <span>Queue status unavailable</span>
            <span class="queue-error-detail">${data?.error || 'Unknown error'}</span>
        `;
        cardsContainer.innerHTML = '';
        return;
    }

    // Render summary
    const totalActive = data.summary?.total_active_messages || 0;
    const totalDlq = data.summary?.total_dead_letter_messages || 0;

    let statusIcon = '&#x2705;';
    let statusClass = 'healthy';
    let statusText = 'All Queues Healthy';

    if (data.status === 'error') {
        statusIcon = '&#x274C;';
        statusClass = 'error';
        statusText = 'Queue Errors Detected';
    } else if (data.status === 'warning' || totalDlq > 0) {
        statusIcon = '&#x26A0;';
        statusClass = 'warning';
        statusText = totalDlq > 0 ? `${totalDlq} Dead-Letter Messages` : 'Queue Warnings';
    }

    summary.className = `queue-summary ${statusClass}`;
    summary.innerHTML = `
        <div class="queue-summary-status">
            <span class="status-icon">${statusIcon}</span>
            <span>${statusText}</span>
        </div>
        <div class="queue-summary-stats">
            <span class="queue-stat active">
                <span class="stat-value">${formatNumber(totalActive)}</span>
                <span class="stat-label">Active</span>
            </span>
            <span class="queue-stat dlq ${totalDlq > 0 ? 'has-messages' : ''}">
                <span class="stat-value">${formatNumber(totalDlq)}</span>
                <span class="stat-label">Dead-Letter</span>
            </span>
            <span class="queue-stat namespace">
                <span class="stat-label">Namespace:</span>
                <span class="stat-value">${data.namespace || 'N/A'}</span>
            </span>
        </div>
    `;

    // Render queue cards
    if (!data.queues || data.queues.length === 0) {
        cardsContainer.innerHTML = '<div class="no-queues">No queues configured</div>';
        return;
    }

    cardsContainer.innerHTML = data.queues.map(queue => renderQueueCard(queue)).join('');
}

function renderQueueCard(queue) {
    const status = queue.status || 'unknown';
    const active = queue.active_message_count || 0;
    const dlq = queue.dead_letter_message_count || 0;
    const scheduled = queue.scheduled_message_count || 0;

    let statusClass = 'healthy';
    let statusBadge = '&#x2705; Healthy';
    if (status === 'error' || status === 'not_found') {
        statusClass = 'error';
        statusBadge = status === 'not_found' ? '&#x26A0; Not Found' : '&#x274C; Error';
    } else if (dlq > 0) {
        statusClass = 'warning';
        statusBadge = '&#x26A0; Has DLQ';
    }

    const listenerLink = queue.listener_url
        ? `<a href="${queue.listener_url}" class="listener-link">${queue.listener} &rarr;</a>`
        : `<span class="listener-name">${queue.listener}</span>`;

    const lastAccessed = queue.accessed_at
        ? formatDateTime(queue.accessed_at)
        : 'Never';

    const purgeButtons = `
        <div class="queue-actions">
            ${active > 0 ? `<button class="btn btn-sm btn-warning" onclick="confirmPurgeQueue('${queue.name}', 'active', ${active})">Clear Active</button>` : ''}
            ${dlq > 0 ? `<button class="btn btn-sm btn-danger" onclick="confirmPurgeQueue('${queue.name}', 'dlq', ${dlq})">Clear DLQ</button>` : ''}
        </div>
    `;

    return `
        <div class="queue-card ${statusClass}" data-queue="${queue.name}">
            <div class="queue-header">
                <div class="queue-title">
                    <span class="queue-icon">${queue.icon || '&#x1F4E8;'}</span>
                    <div>
                        <div class="queue-name">${queue.display_name}</div>
                        <div class="queue-real-name">${queue.name}</div>
                    </div>
                </div>
                <span class="queue-status-badge ${statusClass}">${statusBadge}</span>
            </div>
            <div class="queue-description">${queue.description}</div>
            <div class="queue-stats">
                <div class="queue-stat-item">
                    <span class="stat-icon">&#x1F4EC;</span>
                    <span class="stat-value ${active > 0 ? 'has-messages' : ''}">${formatNumber(active)}</span>
                    <span class="stat-label">Active</span>
                </div>
                <div class="queue-stat-item ${dlq > 0 ? 'dlq-warning' : ''}">
                    <span class="stat-icon">&#x2620;</span>
                    <span class="stat-value ${dlq > 0 ? 'has-messages danger' : ''}">${formatNumber(dlq)}</span>
                    <span class="stat-label">Dead Letter</span>
                </div>
                <div class="queue-stat-item">
                    <span class="stat-icon">&#x23F0;</span>
                    <span class="stat-value">${formatNumber(scheduled)}</span>
                    <span class="stat-label">Scheduled</span>
                </div>
            </div>
            <div class="queue-footer">
                <div class="queue-listener">
                    <span class="listener-label">Listener:</span>
                    ${listenerLink}
                </div>
                <div class="queue-last-accessed">
                    <span>Last accessed: ${lastAccessed}</span>
                </div>
            </div>
            ${active > 0 || dlq > 0 ? purgeButtons : ''}
            ${queue.error ? `<div class="queue-error">${queue.error}</div>` : ''}
        </div>
    `;
}

function confirmPurgeQueue(queueName, target, count) {
    const targetLabel = target === 'dlq' ? 'dead-letter' : 'active';
    const message = `Are you sure you want to permanently delete ${count} ${targetLabel} message(s) from "${queueName}"?\n\nThis action cannot be undone!`;

    if (confirm(message)) {
        purgeQueue(queueName, target);
    }
}

async function purgeQueue(queueName, target) {
    try {
        const response = await fetch(`/api/queues/${queueName}/purge?confirm=yes&target=${target}`, {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        });

        const result = await response.json();

        if (response.ok) {
            alert(`Successfully cleared ${result.total_cleared} messages from ${queueName}`);
            // Refresh queue status
            refreshQueueStatus();
        } else {
            alert(`Failed to purge queue: ${result.error || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Error purging queue:', error);
        alert(`Error purging queue: ${error.message}`);
    }
}

function toggleQueueSection() {
    const section = document.getElementById('queue-status-section');
    const content = document.getElementById('queue-content');
    const toggleIcon = document.getElementById('queue-toggle-icon');

    section.classList.toggle('collapsed');

    if (section.classList.contains('collapsed')) {
        content.style.display = 'none';
        toggleIcon.innerHTML = '&#x25B6;';
    } else {
        content.style.display = 'block';
        toggleIcon.innerHTML = '&#x25BC;';
    }
}
