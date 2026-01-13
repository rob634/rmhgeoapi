"""
Health monitoring interface module.

Web dashboard for viewing system health status with component cards and expandable details.

Features (24 DEC 2025 - S12.3.4):
    - HTMX enabled for future partial updates
    - Dynamic architecture diagram with tooltips
    - Component cards with expandable details

Exports:
    HealthInterface: Health monitoring dashboard with status badges and component grid

Dependencies:
    azure.functions: HTTP request handling
    web_interfaces.base: BaseInterface
    web_interfaces: InterfaceRegistry
"""

import os
import json
import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry
from config import get_config, __version__


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

        Note:
            This method is designed to be resilient - it will render a useful
            diagnostic page even if config loading or other dependencies fail.
        """
        startup_errors = []
        tooltips = {}
        docker_worker_url = ''

        # Try to load config and generate tooltips - capture errors but don't fail
        try:
            tooltips = self._get_component_tooltips()
        except Exception as e:
            startup_errors.append(f"Config loading failed: {type(e).__name__}: {str(e)}")

        # Try to get Docker worker URL
        try:
            from config import get_app_mode_config
            app_mode_config = get_app_mode_config()
            docker_worker_url = app_mode_config.docker_worker_url or ''
        except Exception as e:
            startup_errors.append(f"App mode config failed: {type(e).__name__}: {str(e)}")

        # Generate content - use error-aware version if there are startup errors
        if startup_errors:
            content = self._generate_error_html_content(startup_errors)
        else:
            content = self._generate_html_content()

        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js(tooltips, docker_worker_url, startup_errors)

        return self.wrap_html(
            title="System Health Dashboard",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def _generate_error_html_content(self, startup_errors: list) -> str:
        """
        Generate HTML content when there are startup/config errors.

        Shows a prominent error banner with details about what failed,
        while still providing access to manual health checks.
        """
        error_items = ''.join(f'<li>{err}</li>' for err in startup_errors)

        return f"""
        <div class="container">
            <!-- Startup Error Banner -->
            <div class="startup-error-banner">
                <h2>⚠️ System Startup Errors Detected</h2>
                <p>The health dashboard encountered errors loading configuration. This usually indicates:</p>
                <ul>
                    <li>Missing or invalid environment variables</li>
                    <li>Database connection issues</li>
                    <li>Storage account configuration problems</li>
                </ul>
                <div class="error-details">
                    <h3>Error Details:</h3>
                    <ul class="error-list">
                        {error_items}
                    </ul>
                </div>
                <div class="error-actions">
                    <p><strong>Recommended Actions:</strong></p>
                    <ol>
                        <li>Check Application Insights for <code>STARTUP_FAILED</code> logs</li>
                        <li>Verify all required environment variables are set in Azure Function App settings</li>
                        <li>Check database and storage account connectivity</li>
                    </ol>
                </div>
            </div>

            <!-- Manual Health Check Section -->
            <div class="manual-health-section">
                <h3>Manual Health Check</h3>
                <p>Try fetching the health endpoint directly to see more details:</p>
                <div class="curl-example">
                    <code>curl {os.environ.get('WEBSITE_HOSTNAME', 'localhost')}/api/health</code>
                </div>
                <button class="btn btn-primary" onclick="tryHealthEndpoint()">
                    🔍 Try Health Endpoint
                </button>
                <div id="manual-health-result" class="manual-result hidden"></div>
            </div>

            <!-- Environment Info -->
            <div class="env-info-section">
                <h3>Environment Information</h3>
                <table class="env-table">
                    <tr><td>WEBSITE_HOSTNAME</td><td>{os.environ.get('WEBSITE_HOSTNAME', 'NOT SET')}</td></tr>
                    <tr><td>FUNCTIONS_WORKER_RUNTIME</td><td>{os.environ.get('FUNCTIONS_WORKER_RUNTIME', 'NOT SET')}</td></tr>
                    <tr><td>POSTGIS_HOST</td><td>{os.environ.get('POSTGIS_HOST', 'NOT SET')[:30] + '...' if os.environ.get('POSTGIS_HOST') else 'NOT SET'}</td></tr>
                    <tr><td>POSTGIS_DATABASE</td><td>{os.environ.get('POSTGIS_DATABASE', 'NOT SET')}</td></tr>
                    <tr><td>APP_SCHEMA</td><td>{os.environ.get('APP_SCHEMA', 'NOT SET')}</td></tr>
                    <tr><td>PGSTAC_SCHEMA</td><td>{os.environ.get('PGSTAC_SCHEMA', 'NOT SET')}</td></tr>
                </table>
            </div>
        </div>
        """

    def _get_component_tooltips(self) -> dict:
        """
        Generate dynamic tooltips from application config.

        Returns tooltip text for each architecture component based on actual
        configuration values from the config module (Pydantic-validated settings).

        Tooltip Format:
            - Resource name/hostname
            - Schema/container names in parentheses
            - Queue names for Service Bus components

        Returns:
            Dictionary mapping SVG component IDs to tooltip text strings

        Raises:
            Exception: If config fails to load (no fallback - fail fast)
        """
        config = get_config()

        # Website hostname from Azure environment
        website_hostname = os.environ.get('WEBSITE_HOSTNAME', 'localhost')

        # Service Bus namespace - extract from connection string if needed
        service_bus_ns = config.queues.namespace or ''
        if not service_bus_ns:
            conn_str = config.queues.connection_string or ''
            if 'Endpoint=sb://' in conn_str:
                service_bus_ns = conn_str.split('Endpoint=sb://')[1].split('/')[0]
            else:
                service_bus_ns = 'Service Bus (namespace not configured)'

        # Database info
        db_host = config.database.host
        db_name = config.database.database
        app_schema = config.database.app_schema
        geo_schema = config.database.postgis_schema
        pgstac_schema = config.database.pgstac_schema

        # Storage accounts
        bronze_account = config.storage.bronze.account_name
        silver_account = config.storage.silver.account_name
        bronze_rasters = config.storage.bronze.rasters
        silver_cogs = config.storage.silver.cogs

        # TiTiler URL - clean up for display
        titiler_url = config.titiler_base_url
        if titiler_url.startswith('https://'):
            titiler_url = titiler_url[8:]
        if titiler_url.startswith('http://'):
            titiler_url = titiler_url[7:]

        # Queue names from config
        jobs_queue = config.queues.jobs_queue
        raster_queue = config.queues.raster_tasks_queue
        vector_queue = config.queues.vector_tasks_queue
        long_queue = config.queues.long_running_tasks_queue

        # Docker worker config
        from config import get_app_mode_config
        app_mode_config = get_app_mode_config()
        docker_worker_enabled = app_mode_config.docker_worker_enabled
        docker_worker_url = app_mode_config.docker_worker_url or ''

        # OGC Features URL - clean up for display
        ogc_url = config.ogc_features_base_url
        if ogc_url.startswith('https://'):
            ogc_url = ogc_url[8:]
        if ogc_url.startswith('http://'):
            ogc_url = ogc_url[7:]
        # Remove /api/features suffix for cleaner display
        ogc_url = ogc_url.replace('/api/features', '')

        return {
            # Platform API and workers (all same Function App in standalone mode)
            'comp-platform-api': f"{website_hostname}\nEndpoints: /api/platform/*, /api/jobs/*",
            'comp-orchestrator': f"{website_hostname}\nListens: {jobs_queue}",
            'comp-io-worker': f"{website_hostname}\nListens: {vector_queue}",
            'comp-compute-worker': f"{website_hostname}\nListens: {raster_queue}",

            # Service Bus queues
            'comp-job-queues': f"{service_bus_ns}\nQueue: {jobs_queue}",
            'comp-parallel-queue': f"{service_bus_ns}\nQueue: {vector_queue}",
            'comp-compute-queue': f"{service_bus_ns}\nQueue: {raster_queue}",

            # Database
            'comp-job-tables': f"{db_host}\nDB: {db_name}\nSchema: {app_schema}.jobs",
            'comp-task-tables': f"{db_host}\nDB: {db_name}\nSchema: {app_schema}.tasks",
            'comp-output-tables': f"{db_host}\nDB: {db_name}\nSchemas: {geo_schema}, {pgstac_schema}",

            # Storage
            'comp-input-storage': f"{bronze_account}\nContainer: {bronze_rasters}",
            'comp-output-storage': f"{silver_account}\nContainer: {silver_cogs}",

            # External services
            'comp-titiler': f"{titiler_url}\nMode: {config.titiler_mode}",
            'comp-ogc-features': f"{ogc_url}\nOGC API - Features",

            # Docker Worker (status fetched from actual Docker app health)
            'comp-long-queue': f"{service_bus_ns}\nQueue: {long_queue}\nDocker Worker: {'Enabled' if docker_worker_enabled else 'Disabled'}",
            'comp-container': f"{docker_worker_url or 'Not configured'}\nQueue: {long_queue}\nStatus: {'Enabled' if docker_worker_enabled else 'Disabled (set DOCKER_WORKER_ENABLED=true)'}",

            # Zarr/xarray components - TiTiler-xarray uses same TiTiler, Zarr uses same silver account
            'comp-titiler-xarray': f"{titiler_url}\nxarray/Zarr endpoint\nStatus: check available_features.xarray_zarr",
            'comp-zarr-store': f"{silver_account}\nZarr datasets",
        }

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

            <!-- Architecture Diagram -->
            <div class="architecture-diagram" style="position: relative;">
                <h3>System Architecture</h3>
                <div id="diagram-tooltip" class="diagram-tooltip"></div>
                <div class="diagram-legend">
                    <span class="legend-item"><span class="legend-dot healthy"></span> Healthy</span>
                    <span class="legend-item"><span class="legend-dot warning"></span> Warning</span>
                    <span class="legend-item"><span class="legend-dot unhealthy"></span> Unhealthy</span>
                    <span class="legend-item"><span class="legend-dot unknown"></span> Unknown</span>
                </div>
                <svg viewBox="0 0 1100 580" class="arch-svg" id="arch-diagram">
                    <!-- Definitions for icons and markers -->
                    <defs>
                        <marker id="arrowhead" markerWidth="7" markerHeight="4.9" refX="6.3" refY="2.45" orient="auto">
                            <polygon points="0 0, 7 2.45, 0 4.9" fill="#0071BC"/>
                        </marker>
                        <!-- Grey arrowhead for inactive/not implemented components -->
                        <marker id="arrowhead-grey" markerWidth="7" markerHeight="4.9" refX="6.3" refY="2.45" orient="auto">
                            <polygon points="0 0, 7 2.45, 0 4.9" fill="#9CA3AF"/>
                        </marker>
                        <!-- Function App icon pattern -->
                        <pattern id="funcapp-pattern" width="1" height="1">
                            <rect width="100%" height="100%" fill="#FFC14D"/>
                        </pattern>
                    </defs>

                    <!-- Background groups for organization -->
                    <!-- ETL Pipelines Box - encloses queues and workers -->
                    <rect x="510" y="195" width="295" height="282" rx="8" fill="#FAFBFC" stroke="#E1E4E8" stroke-width="1"/>
                    <!-- Header bar -->
                    <rect x="510" y="195" width="295" height="28" rx="8" fill="#0071BC"/>
                    <!-- Bottom corners of header need to be square where they meet the body -->
                    <rect x="510" y="215" width="295" height="8" fill="#0071BC"/>
                    <text x="657" y="214" class="diagram-header-label">ETL Pipelines</text>

                    <!-- ========== ROW 1: Platform API ========== -->
                    <g class="component" id="comp-platform-api" data-component="platform_api" data-tooltip="">
                        <rect x="30" y="320" width="100" height="60" rx="6" class="comp-box funcapp"/>
                        <text x="80" y="345" class="comp-icon">⚡</text>
                        <text x="80" y="365" class="comp-label">Platform API</text>
                        <circle cx="120" cy="330" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- Arrow: Platform API -> Job Queues -->
                    <path d="M 130 350 L 175 350" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="145" y="340" class="flow-label">Queue Job</text>

                    <!-- ========== Job Queues (Service Bus) ========== -->
                    <g class="component" id="comp-job-queues" data-component="service_bus" data-tooltip="">
                        <rect x="180" y="320" width="100" height="60" rx="6" class="comp-box servicebus"/>
                        <text x="230" y="345" class="comp-icon">📨</text>
                        <text x="230" y="365" class="comp-label">Job Queues</text>
                        <circle cx="270" cy="330" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- Arrow: Job Queues -> Orchestrator -->
                    <path d="M 280 350 L 325 350" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="295" y="340" class="flow-label">Trigger</text>

                    <!-- ========== Orchestrator (Function App) ========== -->
                    <g class="component" id="comp-orchestrator" data-component="orchestrator" data-tooltip="">
                        <rect x="330" y="320" width="110" height="60" rx="6" class="comp-box funcapp"/>
                        <text x="385" y="345" class="comp-icon">⚡</text>
                        <text x="385" y="365" class="comp-label">Orchestrator</text>
                        <circle cx="430" cy="330" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- Arrow: Orchestrator -> Job Tables (straight down) -->
                    <path d="M 385 380 L 385 510" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="395" y="445" class="flow-label">Update State</text>

                    <!-- ========== Job Tables (PostgreSQL) - vertically aligned with Orchestrator, horizontally with Task Tables ========== -->
                    <g class="component" id="comp-job-tables" data-component="database" data-tooltip="">
                        <rect x="335" y="510" width="100" height="60" rx="6" class="comp-box postgres"/>
                        <text x="385" y="535" class="comp-icon">🐘</text>
                        <text x="385" y="555" class="comp-label">Job Tables</text>
                        <circle cx="425" cy="520" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== Fan-out arrows from Orchestrator ========== -->
                    <!-- Arrow: Orchestrator -> Parallel Task Queue -->
                    <path d="M 440 340 L 520 265" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="460" y="290" class="flow-label">Fan-out</text>

                    <!-- Arrow: Orchestrator -> Compute Task Queue -->
                    <path d="M 440 350 L 520 350" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <!-- Arrow: Orchestrator -> Long Task Queue -->
                    <path d="M 440 360 L 520 435" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <!-- ========== PARALLEL TASK PATH ========== -->
                    <g class="component" id="comp-parallel-queue" data-component="task_queue_parallel" data-tooltip="">
                        <rect x="520" y="235" width="100" height="60" rx="6" class="comp-box servicebus"/>
                        <text x="570" y="260" class="comp-icon">📨</text>
                        <text x="570" y="280" class="comp-label">Parallel Queue</text>
                        <circle cx="610" cy="245" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <path d="M 620 265 L 680 265" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <g class="component" id="comp-io-worker" data-component="worker_io" data-tooltip="">
                        <rect x="680" y="235" width="110" height="60" rx="6" class="comp-box funcapp"/>
                        <text x="735" y="260" class="comp-icon">⚡</text>
                        <text x="735" y="280" class="comp-label">I/O Optimized</text>
                        <circle cx="780" cy="245" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== COMPUTE TASK PATH ========== -->
                    <g class="component" id="comp-compute-queue" data-component="task_queue_compute" data-tooltip="">
                        <rect x="520" y="320" width="100" height="60" rx="6" class="comp-box servicebus"/>
                        <text x="570" y="345" class="comp-icon">📨</text>
                        <text x="570" y="365" class="comp-label">Compute Queue</text>
                        <circle cx="610" cy="330" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <path d="M 620 350 L 680 350" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <g class="component" id="comp-compute-worker" data-component="worker_compute" data-tooltip="">
                        <rect x="680" y="320" width="110" height="60" rx="6" class="comp-box funcapp"/>
                        <text x="735" y="345" class="comp-icon">⚡</text>
                        <text x="735" y="365" class="comp-label">Compute Worker</text>
                        <circle cx="780" cy="330" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== LONG-RUNNING TASK PATH ========== -->
                    <!-- Status driven by DOCKER_WORKER_ENABLED env var -->
                    <g class="component" id="comp-long-queue" data-component="task_queue_long" data-tooltip="">
                        <rect x="520" y="405" width="100" height="60" rx="6" class="comp-box servicebus"/>
                        <text x="570" y="430" class="comp-icon">📨</text>
                        <text x="570" y="450" class="comp-label">Long Queue</text>
                        <circle cx="610" cy="415" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <path d="M 620 435 L 680 435" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <g class="component" id="comp-container" data-component="worker_container" data-tooltip="">
                        <rect x="680" y="405" width="110" height="60" rx="6" class="comp-box appservice"/>
                        <text x="735" y="430" class="comp-icon">🐳</text>
                        <text x="735" y="450" class="comp-label">Long Worker</text>
                        <circle cx="780" cy="415" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== TASK COMPLETION -> Task Tables ========== -->
                    <!-- Single arrow from ETL box right edge, horizontally aligned with Compute Worker center (y=350), 90° turn down to Task Tables -->
                    <path d="M 805 350 L 870 350 L 870 510" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="835" y="340" class="flow-label">Task Complete</text>

                    <g class="component" id="comp-task-tables" data-component="database" data-tooltip="">
                        <rect x="820" y="510" width="100" height="60" rx="6" class="comp-box postgres"/>
                        <text x="870" y="535" class="comp-icon">🐘</text>
                        <text x="870" y="555" class="comp-label">Task Tables</text>
                        <circle cx="910" cy="520" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== STATE PROGRESSION FEEDBACK ========== -->
                    <!-- From Task Tables left edge to Job Tables right edge -->
                    <path d="M 820 540 L 435 540" class="flow-arrow" marker-end="url(#arrowhead)" stroke-dasharray="5,3"/>
                    <text x="610" y="555" class="flow-label">Last Task Triggers State Progression</text>

                    <!-- ========== TOP ROW: TiTiler-pgstac and OGC Features ========== -->
                    <!-- TiTiler-pgstac: above Output Data (x=735 center) -->
                    <g class="component" id="comp-titiler" data-tooltip="">
                        <rect x="685" y="5" width="100" height="60" rx="6" class="comp-box appservice"/>
                        <text x="735" y="30" class="comp-icon">🐳</text>
                        <text x="735" y="50" class="comp-label">TiTiler-pgstac</text>
                        <circle cx="775" cy="15" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- OGC Features: above PostGIS (x=870 center) -->
                    <g class="component" id="comp-ogc-features" data-tooltip="">
                        <rect x="820" y="5" width="100" height="60" rx="6" class="comp-box funcapp"/>
                        <text x="870" y="30" class="comp-icon">⚡</text>
                        <text x="870" y="50" class="comp-label">OGC Features</text>
                        <circle cx="910" cy="15" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== STORAGE ROW: Input/Output/PostGIS ========== -->
                    <!-- Input Data: aligned with queues (x=570 center) -->
                    <g class="component" id="comp-input-storage" data-component="storage_bronze" data-tooltip="">
                        <rect x="520" y="95" width="100" height="60" rx="6" class="comp-box storage"/>
                        <text x="570" y="120" class="comp-icon">📦</text>
                        <text x="570" y="140" class="comp-label">Input Data</text>
                        <circle cx="610" cy="105" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- Output Data: aligned with workers (x=735 center) -->
                    <g class="component" id="comp-output-storage" data-component="storage_silver" data-tooltip="">
                        <rect x="685" y="95" width="100" height="60" rx="6" class="comp-box storage"/>
                        <text x="735" y="120" class="comp-icon">📦</text>
                        <text x="735" y="140" class="comp-label">Output Data</text>
                        <circle cx="775" cy="105" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- PostGIS - horizontally aligned with storage -->
                    <g class="component" id="comp-output-tables" data-component="postgis" data-tooltip="">
                        <rect x="820" y="95" width="100" height="60" rx="6" class="comp-box postgres"/>
                        <text x="870" y="120" class="comp-icon">🐘</text>
                        <text x="870" y="140" class="comp-label">PostGIS</text>
                        <circle cx="910" cy="105" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- ========== NEW COLUMN: Zarr/xarray ========== -->
                    <!-- TiTiler-xarray: above Zarr Store (x=1005 center) - uses same TiTiler instance -->
                    <g class="component" id="comp-titiler-xarray" data-tooltip="">
                        <rect x="955" y="5" width="100" height="60" rx="6" class="comp-box appservice"/>
                        <text x="1005" y="30" class="comp-icon">🐳</text>
                        <text x="1005" y="50" class="comp-label">TiTiler-xarray</text>
                        <circle cx="1045" cy="15" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- Zarr Store: to the right of PostGIS (x=1005 center) - same account as Silver -->
                    <g class="component" id="comp-zarr-store" data-tooltip="">
                        <rect x="955" y="95" width="100" height="60" rx="6" class="comp-box storage"/>
                        <text x="1005" y="120" class="comp-icon">📦</text>
                        <text x="1005" y="140" class="comp-label">Zarr Store</text>
                        <circle cx="1045" cy="105" r="8" class="status-indicator" data-status="unknown"/>
                    </g>

                    <!-- Arrow: Zarr Store -> TiTiler-xarray (up) -->
                    <path d="M 1005 95 L 1005 65" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <!-- Arrows: Output Data -> TiTiler-pgstac (up) -->
                    <path d="M 735 95 L 735 65" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <!-- Arrows: PostGIS -> OGC Features (up) -->
                    <path d="M 870 95 L 870 65" class="flow-arrow" marker-end="url(#arrowhead)"/>

                    <!-- Arrows: Input Data -> ETL Apps box (down) -->
                    <path d="M 570 155 L 570 195" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="580" y="178" class="flow-label-tiny">Read</text>

                    <!-- ETL Apps box -> Output Data (up) -->
                    <path d="M 735 195 L 735 155" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="745" y="178" class="flow-label-tiny">Write</text>

                    <!-- ETL Apps box (right edge) -> PostGIS - 90 degree: right then up -->
                    <path d="M 805 225 L 870 225 L 870 155" class="flow-arrow" marker-end="url(#arrowhead)"/>
                    <text x="875" y="190" class="flow-label-tiny">Write</text>

                    <!-- ETL Apps box -> Zarr Store - branches from PostGIS junction, continues right then up -->
                    <path d="M 870 225 L 1005 225 L 1005 155" class="flow-arrow" marker-end="url(#arrowhead)"/>
                </svg>
            </div>

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
            <div id="environment-info" class="environment-info skeleton-section">
                <h3>Environment</h3>
                <div class="env-grid">
                    <div class="env-item skeleton-item">
                        <div class="env-label">Version</div>
                        <div class="env-value"><span class="skeleton-text">Loading...</span></div>
                    </div>
                    <div class="env-item skeleton-item">
                        <div class="env-label">Environment</div>
                        <div class="env-value"><span class="skeleton-text">Loading...</span></div>
                    </div>
                    <div class="env-item skeleton-item">
                        <div class="env-label">Debug Mode</div>
                        <div class="env-value"><span class="skeleton-text">Loading...</span></div>
                    </div>
                    <div class="env-item skeleton-item">
                        <div class="env-label">Hostname</div>
                        <div class="env-value"><span class="skeleton-text">Loading...</span></div>
                    </div>
                </div>
            </div>

            <!-- Components Grid -->
            <div id="components-grid" class="components-grid">
                <!-- Skeleton component cards - will be replaced when data loads -->
                <div class="component-card skeleton-card" data-skeleton="database">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Database</div>
                            <div class="component-description">PostgreSQL connection</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="service_bus">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Service Bus</div>
                            <div class="component-description">Azure Service Bus queues</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="storage_containers">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Storage Containers</div>
                            <div class="component-description">Azure Blob Storage</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="imports">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Imports</div>
                            <div class="component-description">Python dependencies</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="jobs">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Jobs</div>
                            <div class="component-description">Job registry</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="pgstac">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Pgstac</div>
                            <div class="component-description">STAC catalog</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="titiler">
                    <div class="component-header">
                        <div>
                            <div class="component-name">Titiler</div>
                            <div class="component-description">Raster tile server</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
                <div class="component-card skeleton-card" data-skeleton="ogc_features">
                    <div class="component-header">
                        <div>
                            <div class="component-name">OGC Features</div>
                            <div class="component-description">Vector features API</div>
                        </div>
                        <span class="status-badge skeleton-badge">Loading</span>
                    </div>
                </div>
            </div>

            <!-- Schema Summary (from schema_summary component) -->
            <div id="schema-summary" class="schema-summary skeleton-section">
                <h3>Database Schemas</h3>
                <div id="schema-cards" class="schema-cards">
                    <!-- Skeleton schema cards -->
                    <div class="schema-card skeleton-card">
                        <div class="schema-card-header">
                            <div class="schema-name"><span class="schema-icon">&#x1F4CA;</span> Summary</div>
                        </div>
                        <div class="schema-stats">
                            <div class="schema-stat full-width">
                                <div class="stat-label">Total Tables</div>
                                <div class="stat-value"><span class="skeleton-text">--</span></div>
                            </div>
                        </div>
                    </div>
                    <div class="schema-card skeleton-card">
                        <div class="schema-card-header">
                            <div class="schema-name"><span class="schema-icon">&#x2699;</span> Application</div>
                            <span class="schema-badge skeleton-badge">Loading</span>
                        </div>
                        <div class="schema-stats">
                            <div class="schema-stat"><div class="stat-label">Tables</div><div class="stat-value"><span class="skeleton-text">--</span></div></div>
                            <div class="schema-stat"><div class="stat-label">Rows</div><div class="stat-value"><span class="skeleton-text">--</span></div></div>
                        </div>
                    </div>
                    <div class="schema-card skeleton-card">
                        <div class="schema-card-header">
                            <div class="schema-name"><span class="schema-icon">&#x1F5FA;</span> PostGIS</div>
                            <span class="schema-badge skeleton-badge">Loading</span>
                        </div>
                        <div class="schema-stats">
                            <div class="schema-stat"><div class="stat-label">Tables</div><div class="stat-value"><span class="skeleton-text">--</span></div></div>
                            <div class="schema-stat"><div class="stat-label">Rows</div><div class="stat-value"><span class="skeleton-text">--</span></div></div>
                        </div>
                    </div>
                    <div class="schema-card skeleton-card">
                        <div class="schema-card-header">
                            <div class="schema-name"><span class="schema-icon">&#x1F4E6;</span> STAC Catalog</div>
                            <span class="schema-badge skeleton-badge">Loading</span>
                        </div>
                        <div class="schema-stats">
                            <div class="schema-stat"><div class="stat-label">Tables</div><div class="stat-value"><span class="skeleton-text">--</span></div></div>
                            <div class="schema-stat"><div class="stat-label">Rows</div><div class="stat-value"><span class="skeleton-text">--</span></div></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Debug Info (if DEBUG_MODE=true) -->
            <div id="debug-info" class="debug-info hidden"></div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Health Dashboard."""
        return """
        /* ========== Architecture Diagram Styles ========== */
        .architecture-diagram {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 20px;
            margin-bottom: 20px;
            overflow-x: auto;
        }

        .architecture-diagram h3 {
            color: #053657;
            font-size: 16px;
            margin: 0 0 15px 0;
            font-weight: 600;
        }

        .diagram-legend {
            display: flex;
            gap: 20px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: #626F86;
        }

        .legend-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            border: 2px solid white;
            box-shadow: 0 0 0 1px #ccc;
        }

        .legend-dot.healthy { background: #10B981; box-shadow: 0 0 0 1px #10B981; }
        .legend-dot.warning { background: #F59E0B; box-shadow: 0 0 0 1px #F59E0B; }
        .legend-dot.unhealthy { background: #DC2626; box-shadow: 0 0 0 1px #DC2626; }
        .legend-dot.unknown { background: #9CA3AF; box-shadow: 0 0 0 1px #9CA3AF; }

        .arch-svg {
            width: 100%;
            max-width: 1100px;
            height: auto;
            min-height: 400px;
            display: block;
            margin: 0 auto;
        }

        /* Component boxes */
        .comp-box {
            stroke-width: 2;
            transition: all 0.3s;
        }

        .comp-box.funcapp {
            fill: #FFF8E7;
            stroke: #FFC14D;
        }

        .comp-box.servicebus {
            fill: #E8F4FD;
            stroke: #0078D4;
        }

        .comp-box.postgres {
            fill: #E8F0F5;
            stroke: #336791;
        }

        .comp-box.storage {
            fill: #F0F7EE;
            stroke: #5BB381;
        }

        .comp-box.appservice {
            fill: #F3E8FF;
            stroke: #7C3AED;
        }

        /* Inactive/Not Implemented components - grey styling */
        .comp-box.inactive {
            fill: #F3F4F6;
            stroke: #9CA3AF;
            stroke-dasharray: 4,2;
        }

        .comp-icon.disabled {
            opacity: 0.5;
        }

        .comp-label.disabled {
            fill: #9CA3AF;
        }

        .flow-arrow.inactive {
            stroke: #9CA3AF;
            stroke-dasharray: 4,2;
        }

        .status-indicator[data-status="disabled"] {
            fill: #D1D5DB;
            stroke: #9CA3AF;
        }

        /* Component hover effect */
        .component:hover .comp-box {
            filter: brightness(0.95);
        }

        .component {
            cursor: pointer;
        }

        /* Tooltip styles */
        .diagram-tooltip {
            position: absolute;
            background: #1F2937;
            color: white;
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 11px;
            font-family: 'Courier New', monospace;
            pointer-events: none;
            z-index: 1000;
            white-space: pre-line;
            line-height: 1.4;
            max-width: 350px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            opacity: 0;
            transition: opacity 0.2s;
        }

        .diagram-tooltip.visible {
            opacity: 1;
        }

        .diagram-tooltip::after {
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border: 6px solid transparent;
            border-top-color: #1F2937;
        }

        /* Labels */
        .comp-icon {
            font-size: 16px;
            text-anchor: middle;
            dominant-baseline: middle;
        }

        .comp-label {
            font-size: 11px;
            font-weight: 600;
            fill: #053657;
            text-anchor: middle;
        }

        .comp-label-small {
            font-size: 9px;
            font-weight: 600;
            fill: #053657;
            text-anchor: middle;
        }

        .diagram-label-small {
            font-size: 11px;
            fill: #626F86;
            font-style: italic;
        }

        .diagram-header-label {
            font-size: 12px;
            font-weight: 600;
            fill: white;
            text-anchor: middle;
        }

        /* Flow arrows */
        .flow-arrow {
            fill: none;
            stroke: #0071BC;
            stroke-width: 2;
        }

        .flow-label {
            font-size: 9px;
            fill: #626F86;
            text-anchor: middle;
        }

        .flow-label-tiny {
            font-size: 8px;
            fill: #626F86;
        }

        /* Status indicators */
        .status-indicator {
            stroke: white;
            stroke-width: 2;
            transition: fill 0.3s;
        }

        .status-indicator[data-status="healthy"] {
            fill: #10B981;
        }

        .status-indicator[data-status="warning"] {
            fill: #F59E0B;
        }

        .status-indicator[data-status="unhealthy"] {
            fill: #DC2626;
        }

        .status-indicator[data-status="unknown"] {
            fill: #9CA3AF;
        }

        /* Pulse animation for unhealthy */
        @keyframes pulse-unhealthy {
            0%, 100% { r: 8; opacity: 1; }
            50% { r: 10; opacity: 0.8; }
        }

        .status-indicator[data-status="unhealthy"] {
            animation: pulse-unhealthy 1.5s ease-in-out infinite;
        }

        /* ========== Original Dashboard Styles ========== */
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

        /* Startup Error Banner (for config/initialization failures) */
        .startup-error-banner {
            background: #FEF2F2;
            border: 2px solid #DC2626;
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 24px;
        }

        .startup-error-banner h2 {
            color: #DC2626;
            margin: 0 0 16px 0;
            font-size: 20px;
        }

        .startup-error-banner p {
            color: #7F1D1D;
            margin: 8px 0;
        }

        .startup-error-banner ul, .startup-error-banner ol {
            color: #7F1D1D;
            margin: 8px 0 8px 20px;
        }

        .startup-error-banner .error-details {
            background: #FEE2E2;
            border-radius: 4px;
            padding: 16px;
            margin: 16px 0;
        }

        .startup-error-banner .error-details h3 {
            color: #991B1B;
            margin: 0 0 8px 0;
            font-size: 14px;
        }

        .startup-error-banner .error-list {
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 12px;
            background: #1F2937;
            color: #F87171;
            padding: 12px 16px;
            border-radius: 4px;
            list-style: none;
            margin: 0;
        }

        .startup-error-banner .error-list li {
            padding: 4px 0;
            border-bottom: 1px solid #374151;
        }

        .startup-error-banner .error-list li:last-child {
            border-bottom: none;
        }

        .startup-error-banner .error-actions {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid #FECACA;
        }

        .startup-error-banner code {
            background: #FEE2E2;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 12px;
        }

        /* Manual Health Check Section */
        .manual-health-section {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 24px;
        }

        .manual-health-section h3 {
            margin: 0 0 12px 0;
            color: var(--ds-navy);
        }

        .curl-example {
            background: #1F2937;
            color: #10B981;
            padding: 12px 16px;
            border-radius: 4px;
            margin: 12px 0;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 13px;
        }

        .manual-result {
            margin-top: 16px;
            padding: 16px;
            border-radius: 4px;
            max-height: 400px;
            overflow-y: auto;
        }

        .manual-result .loading {
            color: var(--ds-blue-primary);
        }

        .manual-result .success {
            background: #D1FAE5;
            border: 1px solid #10B981;
            border-radius: 4px;
            padding: 12px;
        }

        .manual-result .success h4 {
            color: #065F46;
            margin: 0 0 8px 0;
        }

        .manual-result .error {
            background: #FEE2E2;
            border: 1px solid #DC2626;
            border-radius: 4px;
            padding: 12px;
        }

        .manual-result .error h4 {
            color: #991B1B;
            margin: 0 0 8px 0;
        }

        .manual-result pre {
            background: #1F2937;
            color: #E5E7EB;
            padding: 12px;
            border-radius: 4px;
            font-size: 11px;
            overflow-x: auto;
            max-height: 250px;
        }

        /* Environment Info Section (for error page) */
        .env-info-section {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 8px;
            padding: 24px;
        }

        .env-info-section h3 {
            margin: 0 0 16px 0;
            color: var(--ds-navy);
        }

        .env-table {
            width: 100%;
            border-collapse: collapse;
        }

        .env-table td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--ds-gray-light);
            font-size: 13px;
        }

        .env-table td:first-child {
            font-weight: 600;
            color: var(--ds-gray);
            width: 200px;
        }

        .env-table td:last-child {
            font-family: 'Monaco', 'Courier New', monospace;
            color: var(--ds-navy);
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

        /* Docker Worker Resources - Follows identity-section pattern */
        .docker-worker-section {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 20px;
            margin-bottom: 20px;
        }

        .docker-worker-section h3 {
            color: #053657;
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 15px;
        }

        .docker-worker-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
        }

        .docker-worker-card {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 12px 15px;
        }

        .docker-worker-card .card-label {
            color: #626F86;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }

        .docker-worker-card .card-value {
            color: #053657;
            font-size: 15px;
            font-weight: 600;
        }

        .docker-worker-card .card-sub {
            color: #626F86;
            font-size: 11px;
            margin-top: 4px;
        }

        .docker-worker-card .card-bar-container {
            height: 4px;
            background: #e9ecef;
            border-radius: 2px;
            margin: 6px 0 4px 0;
            overflow: hidden;
        }

        .docker-worker-card .card-bar {
            height: 100%;
            border-radius: 2px;
            transition: width 0.3s ease;
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

        .component-link {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            margin-top: 8px;
            padding: 4px 10px;
            background: #E8F4FD;
            border: 1px solid #0071BC;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: #0071BC;
            text-decoration: none;
            transition: all 0.2s;
        }

        .component-link:hover {
            background: #0071BC;
            color: white;
            transform: translateY(-1px);
        }

        .component-link.disabled {
            background: #f3f4f6;
            border-color: #9CA3AF;
            color: #9CA3AF;
            cursor: not-allowed;
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

        /* Schema Summary Section */
        .schema-summary {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 20px;
            margin-bottom: 20px;
        }

        .schema-summary h3 {
            color: #053657;
            font-size: 16px;
            margin-bottom: 15px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .schema-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 15px;
        }

        .schema-card {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 15px;
            transition: all 0.2s;
        }

        .schema-card:hover {
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .schema-card.not-found {
            opacity: 0.6;
            border-style: dashed;
        }

        .schema-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .schema-name {
            font-size: 15px;
            font-weight: 600;
            color: #053657;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .schema-name .schema-icon {
            font-size: 14px;
        }

        .schema-badge {
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .schema-badge.exists {
            background: #D1FAE5;
            color: #065F46;
        }

        .schema-badge.missing {
            background: #FEE2E2;
            color: #991B1B;
        }

        .schema-stats {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .schema-stat {
            background: white;
            padding: 8px 10px;
            border-radius: 4px;
            border: 1px solid #e9ecef;
        }

        .schema-stat.full-width {
            grid-column: 1 / -1;
        }

        .stat-label {
            font-size: 10px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-top: 2px;
        }

        .stat-value.highlight {
            color: #0071BC;
        }

        .schema-tables-list {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #e9ecef;
        }

        .schema-tables-toggle {
            font-size: 11px;
            color: #0071BC;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .schema-tables-toggle:hover {
            text-decoration: underline;
        }

        .schema-tables-content {
            display: none;
            margin-top: 8px;
            max-height: 200px;
            overflow-y: auto;
        }

        .schema-tables-content.expanded {
            display: block;
        }

        .table-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 11px;
            border-bottom: 1px solid #f0f0f0;
        }

        .table-row:last-child {
            border-bottom: none;
        }

        .table-name {
            color: #053657;
            font-family: 'Courier New', monospace;
        }

        .table-count {
            color: #626F86;
            font-weight: 600;
        }

        /* Special highlights for STAC counts */
        .stac-highlight {
            background: linear-gradient(135deg, #F3E8FF 0%, #E8F4FD 100%);
            border-color: #7C3AED;
        }

        .geo-highlight {
            background: linear-gradient(135deg, #F0F7EE 0%, #E8F4FD 100%);
            border-color: #5BB381;
        }

        /* ========== Skeleton Loading Styles ========== */
        @keyframes skeleton-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .skeleton-section {
            opacity: 0.7;
        }

        .skeleton-card {
            border-left: 4px solid #D1D5DB !important;
            opacity: 0.8;
        }

        .skeleton-card .component-name,
        .skeleton-card .schema-name {
            color: #9CA3AF;
        }

        .skeleton-card .component-description {
            color: #D1D5DB;
        }

        .skeleton-badge {
            background: #E5E7EB !important;
            color: #9CA3AF !important;
            animation: skeleton-pulse 1.5s ease-in-out infinite;
        }

        .skeleton-text {
            color: #9CA3AF;
            animation: skeleton-pulse 1.5s ease-in-out infinite;
        }

        .skeleton-item {
            opacity: 0.7;
        }

        .skeleton-item .env-value {
            color: #9CA3AF;
        }

        /* Transition for when data loads */
        .component-card,
        .schema-card,
        .env-item {
            transition: opacity 0.3s ease, border-color 0.3s ease;
        }

        .component-card.loaded,
        .schema-card.loaded {
            opacity: 1;
        }

        /* Hide skeleton sections when they get real class */
        .environment-info.hidden {
            display: none;
        }

        .schema-summary.hidden {
            display: none;
        }

        /* Hardware/Function App Resources Section */
        .hardware-section {
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e9ecef;
        }

        .hardware-section h4 {
            color: #053657;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 15px;
        }

        .hardware-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
        }

        .hardware-card {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 12px;
            display: flex;
            gap: 12px;
            align-items: flex-start;
        }

        .hardware-icon {
            font-size: 20px;
            flex-shrink: 0;
        }

        .hardware-details {
            flex: 1;
            min-width: 0;
        }

        .hardware-label {
            font-size: 10px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 2px;
        }

        .hardware-value {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 4px;
        }

        .hardware-sub {
            font-size: 11px;
            color: #626F86;
        }

        .hardware-bar-container {
            height: 6px;
            background: #e9ecef;
            border-radius: 3px;
            overflow: hidden;
            margin: 6px 0;
        }

        .hardware-bar {
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s ease;
        }
        """

    def _generate_custom_js(self, tooltips: dict, docker_worker_url: str = '', startup_errors: list = None) -> str:
        """Generate custom JavaScript for Health Dashboard."""
        tooltips_json = json.dumps(tooltips)
        has_startup_errors = 'true' if startup_errors else 'false'

        # Inject dynamic tooltips at the start, then use regular string for the rest
        return f"""
        // Dynamic component tooltips from server config
        const COMPONENT_TOOLTIPS = {tooltips_json};

        // Docker Worker URL for health checks (empty string if not configured)
        const DOCKER_WORKER_URL = '{docker_worker_url}';

        // Whether there were startup errors (config loading failures)
        const HAS_STARTUP_ERRORS = {has_startup_errors};

        // Manual health endpoint check (for error recovery UI)
        async function tryHealthEndpoint() {{
            const resultDiv = document.getElementById('manual-health-result');
            if (!resultDiv) return;

            resultDiv.classList.remove('hidden');
            resultDiv.innerHTML = '<div class="loading">Checking health endpoint...</div>';

            try {{
                const response = await fetch('/api/health');
                const data = await response.json();

                if (response.ok) {{
                    resultDiv.innerHTML = `
                        <div class="success">
                            <h4>✅ Health endpoint responded (HTTP ${{response.status}})</h4>
                            <pre>${{JSON.stringify(data, null, 2)}}</pre>
                        </div>
                    `;
                }} else {{
                    resultDiv.innerHTML = `
                        <div class="error">
                            <h4>⚠️ Health endpoint returned error (HTTP ${{response.status}})</h4>
                            <pre>${{JSON.stringify(data, null, 2)}}</pre>
                        </div>
                    `;
                }}
            }} catch (err) {{
                resultDiv.innerHTML = `
                    <div class="error">
                        <h4>❌ Failed to reach health endpoint</h4>
                        <p><strong>Error:</strong> ${{err.message}}</p>
                        <p>This usually means the Azure Function is not starting properly.
                           Check Application Insights for startup errors.</p>
                    </div>
                `;
            }}
        }}

        // Apply dynamic tooltips on page load
        function applyDynamicTooltips() {{
            Object.entries(COMPONENT_TOOLTIPS).forEach(([compId, tooltipText]) => {{
                const component = document.getElementById(compId);
                if (component) {{
                    component.setAttribute('data-tooltip', tooltipText);
                }}
            }});
        }}

        // Load health data on page load
        document.addEventListener('DOMContentLoaded', () => {{
            applyDynamicTooltips();
            loadHealth();
            setupDiagramClickHandlers();
        }});

        // Component mapping: SVG component ID -> health API component name
        // Maps diagram components to /api/health response components
        const COMPONENT_MAPPING = {{
            'comp-platform-api': 'deployment_config',    // API deployment configuration
            'comp-job-queues': 'service_bus',            // Azure Service Bus queues
            'comp-orchestrator': 'jobs',                 // Job orchestration/registry
            'comp-job-tables': 'database',               // PostgreSQL jobs/tasks tables
            'comp-parallel-queue': 'service_bus',        // Service Bus (all queues)
            'comp-compute-queue': 'service_bus',         // Service Bus (all queues)
            'comp-long-queue': 'service_bus',            // Service Bus (all queues)
            'comp-io-worker': 'imports',                 // Workers need imports healthy
            'comp-compute-worker': 'imports',            // Workers need imports healthy
            'comp-container': 'duckdb',                  // Container worker (DuckDB)
            'comp-task-tables': 'database',              // PostgreSQL tasks table
            'comp-input-storage': 'storage_containers',  // Bronze storage
            'comp-output-storage': 'storage_containers', // Silver storage
            'comp-output-tables': 'pgstac',              // PostGIS/pgstac output
            'comp-titiler': 'titiler',                   // TiTiler-pgstac raster tile server
            'comp-ogc-features': 'ogc_features',         // OGC Features API
            'comp-titiler-xarray': 'titiler_xarray',     // TiTiler xarray endpoint (special handling)
            'comp-zarr-store': 'zarr_store'              // Zarr storage (special handling)
        }};

        // Special components that derive status from TiTiler's available_features
        const TITILER_FEATURE_COMPONENTS = {{
            'comp-titiler-xarray': 'xarray_zarr',        // TiTiler xarray/Zarr feature flag
            'comp-zarr-store': 'xarray_zarr'             // Zarr uses same feature flag
        }};

        // Components that derive status from DOCKER_WORKER_ENABLED setting
        const DOCKER_WORKER_COMPONENTS = ['comp-long-queue', 'comp-container'];

        // Update architecture diagram status indicators
        function updateDiagramStatus(components, dockerHealth = null) {{
            if (!components) return;

            // Get TiTiler component for feature flag checks
            // available_features is nested in: titiler.details.health.body.available_features
            const titilerComponent = components['titiler'];
            const titilerFeatures = titilerComponent?.details?.health?.body?.available_features || {{}};

            // Get Docker Worker enabled setting from deployment_config
            const deploymentConfig = components['deployment_config'];
            const dockerWorkerEnabled = deploymentConfig?.details?.docker_worker_enabled === true;

            // Update each component in the diagram
            Object.entries(COMPONENT_MAPPING).forEach(([svgId, healthKey]) => {{
                const indicator = document.querySelector(`#${{svgId}} .status-indicator`);
                if (!indicator) return;

                let status = 'unknown';

                // Check if this is a Docker Worker component
                if (DOCKER_WORKER_COMPONENTS.includes(svgId)) {{
                    // Status based on actual Docker worker health (if configured)
                    if (!dockerWorkerEnabled && !DOCKER_WORKER_URL) {{
                        status = 'unknown';  // Grey - not enabled/configured
                    }} else if (dockerHealth) {{
                        // Use actual Docker worker health status
                        const dockerStatus = dockerHealth.status || 'unknown';
                        if (dockerStatus === 'healthy') {{
                            status = 'healthy';
                        }} else if (dockerStatus === 'unhealthy' || dockerStatus === 'unreachable') {{
                            status = 'unhealthy';
                        }} else if (dockerStatus === 'warning') {{
                            status = 'warning';
                        }} else {{
                            status = 'unknown';
                        }}
                    }} else if (dockerWorkerEnabled) {{
                        // Docker enabled but no health data (URL not configured)
                        status = 'warning';
                    }}
                }}
                // Check if this is a TiTiler feature-based component
                else if (TITILER_FEATURE_COMPONENTS[svgId]) {{
                    const featureKey = TITILER_FEATURE_COMPONENTS[svgId];
                    // Status based on TiTiler's available_features flag
                    // Check both top-level status and details.overall_status for TiTiler health
                    const titilerStatus = titilerComponent?.details?.overall_status || titilerComponent?.status;
                    const titilerHealthy = titilerStatus === 'healthy';

                    if (titilerComponent && titilerHealthy) {{
                        // TiTiler is healthy - check if xarray_zarr feature is enabled
                        status = titilerFeatures[featureKey] === true ? 'healthy' : 'unhealthy';
                    }} else if (titilerComponent) {{
                        status = 'warning';  // TiTiler exists but not fully healthy
                    }}
                }} else {{
                    // Standard component lookup
                    const component = components[healthKey];
                    if (component) {{
                        // For TiTiler and OGC Features, check details.overall_status for nuanced status
                        // (these components can have warning state: livez OK but health not OK)
                        if (component.details && component.details.overall_status) {{
                            status = component.details.overall_status;
                        }} else {{
                            status = component.status || 'unknown';
                        }}
                        // Normalize status values
                        if (status === 'error') status = 'unhealthy';
                        if (status === 'partial') status = 'warning';
                        if (status === 'disabled' || status === 'deprecated') status = 'unknown';
                    }}
                }}

                indicator.setAttribute('data-status', status);
            }});
        }}

        // Click handler for diagram components
        function setupDiagramClickHandlers() {{
            document.querySelectorAll('.architecture-diagram .component').forEach(comp => {{
                comp.addEventListener('click', () => {{
                    const healthKey = COMPONENT_MAPPING[comp.id];
                    if (healthKey) {{
                        // Scroll to and highlight the corresponding component card
                        const card = document.querySelector(`[data-component-key="${{healthKey}}"]`);
                        if (card) {{
                            card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                            card.style.boxShadow = '0 0 0 3px #0071BC';
                            setTimeout(() => {{
                                card.style.boxShadow = '';
                            }}, 2000);
                        }}
                    }}
                }});
            }});
        }}

        // Fetch Docker Worker health from its endpoint
        async function fetchDockerWorkerHealth() {{
            if (!DOCKER_WORKER_URL) {{
                return null;
            }}

            try {{
                const response = await fetch(`${{DOCKER_WORKER_URL}}/health`, {{
                    method: 'GET',
                    headers: {{ 'Accept': 'application/json' }},
                    mode: 'cors',
                    // Short timeout - don't block main health display
                    signal: AbortSignal.timeout(10000)
                }});

                if (!response.ok) {{
                    return {{
                        status: 'unhealthy',
                        error: `HTTP ${{response.status}}`,
                        url: DOCKER_WORKER_URL
                    }};
                }}

                const data = await response.json();
                return {{
                    ...data,
                    status: data.status || 'healthy',
                    url: DOCKER_WORKER_URL
                }};
            }} catch (err) {{
                return {{
                    status: 'unreachable',
                    error: err.message,
                    url: DOCKER_WORKER_URL
                }};
            }}
        }}

        // Render Docker Worker info section (matching Function App Resources format)
        function renderDockerWorkerInfo(dockerHealth) {{
            if (!dockerHealth) return;

            const envInfo = document.getElementById('environment-info');
            if (!envInfo) return;

            // Extract health data from Docker worker response
            const status = dockerHealth.status || 'unknown';
            const version = dockerHealth.version || 'N/A';
            const hardware = dockerHealth.hardware || {{}};
            const memory = dockerHealth.memory || {{}};
            const tokens = dockerHealth.tokens || {{}};
            const workers = dockerHealth.background_workers || {{}};
            const url = dockerHealth.url || DOCKER_WORKER_URL;

            // Calculate status color and icon
            let statusColor = '#6B7280';
            let statusIcon = '⚪';
            if (status === 'healthy') {{
                statusColor = '#10B981';
                statusIcon = '🟢';
            }} else if (status === 'unhealthy' || status === 'unreachable') {{
                statusColor = '#DC2626';
                statusIcon = '🔴';
            }} else if (status === 'warning') {{
                statusColor = '#F59E0B';
                statusIcon = '🟡';
            }}

            // Token status for subtitle
            const pgToken = tokens.postgres || {{}};
            const storageToken = tokens.storage || {{}};
            const pgValid = pgToken.has_token === true;
            const storageValid = storageToken.has_token === true;
            const tokensValid = pgValid && storageValid;

            // CPU utilization bar
            const cpuPercent = memory.cpu_percent || 0;
            let cpuBarColor = '#10B981';
            if (cpuPercent >= 90) cpuBarColor = '#DC2626';
            else if (cpuPercent >= 70) cpuBarColor = '#F59E0B';

            // Memory utilization bar
            const ramPercent = memory.system_percent || 0;
            let ramBarColor = '#10B981';
            if (ramPercent >= 90) ramBarColor = '#DC2626';
            else if (ramPercent >= 70) ramBarColor = '#F59E0B';

            // Clean URL for display
            let displayUrl = url;
            if (displayUrl.startsWith('https://')) displayUrl = displayUrl.substring(8);
            if (displayUrl.startsWith('http://')) displayUrl = displayUrl.substring(7);
            if (displayUrl.length > 35) displayUrl = displayUrl.substring(0, 32) + '...';

            let dockerHtml;

            if (status === 'healthy' || status === 'warning') {{
                dockerHtml = `
                    <div class="docker-worker-section">
                        <h3>🐳 Docker Worker Resources</h3>
                        <div class="docker-worker-grid">
                            <div class="docker-worker-card">
                                <div class="card-label">${{statusIcon}} Azure Site</div>
                                <div class="card-value">${{hardware.azure_site_name || 'docker-worker'}}</div>
                                <div class="card-sub">${{hardware.azure_sku || 'Container'}} • v${{version}}</div>
                            </div>

                            <div class="docker-worker-card">
                                <div class="card-label">⚡ CPU</div>
                                <div class="card-value">${{hardware.cpu_count || 'N/A'}} cores</div>
                                <div class="card-bar-container">
                                    <div class="card-bar" style="width: ${{Math.min(cpuPercent, 100)}}%; background: ${{cpuBarColor}};"></div>
                                </div>
                                <div class="card-sub">${{cpuPercent.toFixed(1)}}% utilized</div>
                            </div>

                            <div class="docker-worker-card">
                                <div class="card-label">💾 Memory</div>
                                <div class="card-value">${{hardware.total_ram_gb || 'N/A'}} GB total</div>
                                <div class="card-bar-container">
                                    <div class="card-bar" style="width: ${{Math.min(ramPercent, 100)}}%; background: ${{ramBarColor}};"></div>
                                </div>
                                <div class="card-sub">${{memory.system_available_mb ? (memory.system_available_mb / 1024).toFixed(1) + ' GB' : 'N/A'}} available (${{(100 - ramPercent).toFixed(1)}}% free)</div>
                            </div>

                            <div class="docker-worker-card">
                                <div class="card-label">📊 Process RSS</div>
                                <div class="card-value">${{memory.process_rss_mb ? (memory.process_rss_mb >= 1024 ? (memory.process_rss_mb / 1024).toFixed(2) + ' GB' : memory.process_rss_mb.toFixed(0) + ' MB') : 'N/A'}}</div>
                                <div class="card-sub">Current process memory</div>
                            </div>

                            <div class="docker-worker-card">
                                <div class="card-label">🖥️ Platform</div>
                                <div class="card-value">${{hardware.platform || 'N/A'}}</div>
                                <div class="card-sub">Python ${{hardware.python_version || 'N/A'}}</div>
                            </div>

                            <div class="docker-worker-card">
                                <div class="card-label">🔑 Auth Tokens</div>
                                <div class="card-value" style="color: ${{tokensValid ? '#10B981' : '#DC2626'}}">${{tokensValid ? 'Valid' : 'Issues'}}</div>
                                <div class="card-sub">PG: ${{pgValid ? '✓' : '✗'}} Storage: ${{storageValid ? '✓' : '✗'}}</div>
                            </div>
                        </div>
                    </div>
                `;
            }} else {{
                // Error state - show minimal cards with error info
                dockerHtml = `
                    <div class="docker-worker-section">
                        <h3>🐳 Docker Worker Resources</h3>
                        <div class="docker-worker-grid">
                            <div class="docker-worker-card">
                                <div class="card-label">${{statusIcon}} Status</div>
                                <div class="card-value" style="color: ${{statusColor}}; text-transform: capitalize;">${{status}}</div>
                                <div class="card-sub">${{displayUrl}}</div>
                            </div>

                            <div class="docker-worker-card" style="grid-column: span 5;">
                                <div class="card-label">⚠️ Error</div>
                                <div class="card-value" style="color: #DC2626;">${{dockerHealth.error || 'Unable to connect to Docker worker'}}</div>
                                <div class="card-sub">Check Docker worker deployment and network connectivity</div>
                            </div>
                        </div>
                    </div>
                `;
            }}

            // Insert after Function App Resources section
            const existingDockerSection = envInfo.parentElement.querySelector('.docker-worker-section');
            if (existingDockerSection) {{
                existingDockerSection.outerHTML = dockerHtml;
            }} else {{
                envInfo.insertAdjacentHTML('afterend', dockerHtml);
            }}
        }}

        // Load health data from API
        async function loadHealth() {{
            const refreshBtn = document.getElementById('refresh-btn');
            const overallStatus = document.getElementById('overall-status');
            const errorBanner = document.getElementById('error-banner');
            const componentsGrid = document.getElementById('components-grid');
            const envInfo = document.getElementById('environment-info');
            const schemaSummary = document.getElementById('schema-summary');

            // Disable refresh button and show loading
            refreshBtn.disabled = true;
            refreshBtn.textContent = 'Loading...';
            overallStatus.className = 'overall-status loading';
            overallStatus.innerHTML = '<div class="spinner"></div><div><span>Loading health status...</span><div class="loading-hint">Health check may take up to 60 seconds</div></div>';
            errorBanner.classList.add('hidden');

            // Keep skeleton cards visible - don't clear componentsGrid
            // Add skeleton class to sections if not already present
            envInfo.classList.add('skeleton-section');
            schemaSummary.classList.add('skeleton-section');
            componentsGrid.querySelectorAll('.component-card').forEach(card => {{
                card.classList.add('skeleton-card');
            }});

            try {{
                // Fetch main health and Docker worker health in parallel
                const healthPromise = fetchJSON(`${{API_BASE_URL}}/api/health`);

                // Only fetch Docker health if URL is configured
                let dockerHealthPromise = Promise.resolve(null);
                if (DOCKER_WORKER_URL) {{
                    dockerHealthPromise = fetchDockerWorkerHealth().catch(err => {{
                        console.warn('Docker worker health fetch failed:', err.message);
                        return {{ status: 'unreachable', error: err.message }};
                    }});
                }}

                const [data, dockerHealth] = await Promise.all([healthPromise, dockerHealthPromise]);

                // Store Docker health globally for diagram status updates
                window.dockerWorkerHealth = dockerHealth;

                // Render overall status
                renderOverallStatus(data);

                // Render environment info
                renderEnvironmentInfo(data);

                // Render Docker worker info (if configured)
                if (DOCKER_WORKER_URL) {{
                    renderDockerWorkerInfo(dockerHealth);
                }}

                // Render identity info
                renderIdentityInfo(data);

                // Render component cards
                renderComponents(data.components);

                // Update architecture diagram (pass Docker health for Long Worker/Queue status)
                updateDiagramStatus(data.components, dockerHealth);

                // Render schema summary
                renderSchemaSummary(data.components);

                // Render debug info if present
                renderDebugInfo(data);

                // Update last checked timestamp
                updateLastChecked(data.timestamp);

            }} catch (error) {{
                console.error('Error loading health data:', error);
                overallStatus.className = 'overall-status unhealthy';
                overallStatus.innerHTML = `
                    <span class="status-icon">&#x274C;</span>
                    <div>
                        <div>Failed to load health data</div>
                        <div class="status-details">${{error.message || 'Unknown error'}}</div>
                    </div>
                `;
                errorBanner.classList.remove('hidden');
                document.getElementById('error-message').textContent = error.message || 'Failed to fetch health endpoint';
            }} finally {{
                refreshBtn.disabled = false;
                refreshBtn.textContent = 'Refresh';
            }}
        }}

        // Render overall status banner
        function renderOverallStatus(data) {{
            const overallStatus = document.getElementById('overall-status');
            const status = data.status || 'unknown';
            const errors = data.errors || [];
            const components = data.components || {{}};
            const componentCount = Object.keys(components).length;

            let statusIcon, statusText;
            if (status === 'healthy') {{
                statusIcon = '&#x2705;';
                statusText = 'All Systems Operational';
            }} else if (status === 'unhealthy') {{
                statusIcon = '&#x274C;';
                statusText = 'System Issues Detected';
            }} else {{
                statusIcon = '&#x26A0;';
                statusText = 'Unknown Status';
            }}

            overallStatus.className = `overall-status ${{status}}`;
            overallStatus.innerHTML = `
                <span class="status-icon">${{statusIcon}}</span>
                <div>
                    <div>${{statusText}}</div>
                    <div class="status-details">${{componentCount}} components checked ${{errors.length > 0 ? '&bull; ' + errors.length + ' warning(s)' : ''}}</div>
                </div>
            `;
        }}

        // Render environment info section
        function renderEnvironmentInfo(data) {{
            const envInfo = document.getElementById('environment-info');
            const env = data.environment || {{}};

            // Remove skeleton class
            envInfo.classList.remove('skeleton-section');

            if (Object.keys(env).length === 0) {{
                envInfo.classList.add('hidden');
                return;
            }}

            // Get runtime details from runtime component (07 JAN 2026 restructure)
            // Path: components.runtime.details contains hardware, memory, instance, process
            const runtime = data.components?.runtime?.details || {{}};
            const hardware = runtime.hardware || {{}};
            const memory = runtime.memory || {{}};
            const instance = runtime.instance || {{}};

            // Merge into combined object for renderHardwareInfo
            const hwInfo = {{
                ...hardware,
                ram_utilization_percent: memory.system_percent || 0,
                cpu_utilization_percent: memory.cpu_percent || 0,
                available_ram_mb: memory.system_available_mb || 0,
                process_rss_mb: memory.process_rss_mb || 0,
                azure_instance_id: instance.instance_id_short || instance.instance_id || '',
            }};

            envInfo.classList.remove('hidden');
            envInfo.innerHTML = `
                <h3>Environment</h3>
                <div class="env-grid">
                    ${{Object.entries(env).map(([key, value]) => `
                        <div class="env-item">
                            <div class="env-label">${{formatLabel(key)}}</div>
                            <div class="env-value">${{value || 'N/A'}}</div>
                        </div>
                    `).join('')}}
                </div>
                ${{Object.keys(hwInfo).length > 0 ? renderHardwareInfo(hwInfo) : ''}}
            `;
        }}

        // Render hardware/Function App info section
        function renderHardwareInfo(hardware) {{
            // Calculate memory bar color based on utilization
            const ramPercent = hardware.ram_utilization_percent || 0;
            let ramBarColor = '#10B981'; // green
            if (ramPercent >= 90) ramBarColor = '#DC2626'; // red
            else if (ramPercent >= 80) ramBarColor = '#F59E0B'; // yellow

            const cpuPercent = hardware.cpu_utilization_percent || 0;
            let cpuBarColor = '#10B981';
            if (cpuPercent >= 90) cpuBarColor = '#DC2626';
            else if (cpuPercent >= 70) cpuBarColor = '#F59E0B';

            return `
                <div class="hardware-section">
                    <h4>Function App Resources</h4>
                    <div class="hardware-grid">
                        <!-- Azure Info -->
                        <div class="hardware-card">
                            <div class="hardware-icon">☁️</div>
                            <div class="hardware-details">
                                <div class="hardware-label">Azure Site</div>
                                <div class="hardware-value">${{hardware.azure_site_name || 'local'}}</div>
                                <div class="hardware-sub">${{hardware.azure_sku || 'N/A'}} ${{hardware.azure_instance_id ? '• ' + hardware.azure_instance_id : ''}}</div>
                            </div>
                        </div>

                        <!-- CPU Info -->
                        <div class="hardware-card">
                            <div class="hardware-icon">⚡</div>
                            <div class="hardware-details">
                                <div class="hardware-label">CPU</div>
                                <div class="hardware-value">${{hardware.cpu_count || 'N/A'}} cores</div>
                                <div class="hardware-bar-container">
                                    <div class="hardware-bar" style="width: ${{Math.min(cpuPercent, 100)}}%; background: ${{cpuBarColor}};"></div>
                                </div>
                                <div class="hardware-sub">${{cpuPercent.toFixed(1)}}% utilized</div>
                            </div>
                        </div>

                        <!-- RAM Info -->
                        <div class="hardware-card">
                            <div class="hardware-icon">💾</div>
                            <div class="hardware-details">
                                <div class="hardware-label">Memory</div>
                                <div class="hardware-value">${{hardware.total_ram_gb || 'N/A'}} GB total</div>
                                <div class="hardware-bar-container">
                                    <div class="hardware-bar" style="width: ${{Math.min(ramPercent, 100)}}%; background: ${{ramBarColor}};"></div>
                                </div>
                                <div class="hardware-sub">${{hardware.available_ram_mb ? (hardware.available_ram_mb / 1024).toFixed(1) + ' GB' : 'N/A'}} available (${{(100 - ramPercent).toFixed(1)}}% free)</div>
                            </div>
                        </div>

                        <!-- Process Info -->
                        <div class="hardware-card">
                            <div class="hardware-icon">📊</div>
                            <div class="hardware-details">
                                <div class="hardware-label">Process RSS</div>
                                <div class="hardware-value">${{hardware.process_rss_mb ? (hardware.process_rss_mb >= 1024 ? (hardware.process_rss_mb / 1024).toFixed(2) + ' GB' : hardware.process_rss_mb.toFixed(0) + ' MB') : 'N/A'}}</div>
                                <div class="hardware-sub">Current process memory usage</div>
                            </div>
                        </div>

                        <!-- Platform Info -->
                        <div class="hardware-card">
                            <div class="hardware-icon">🖥️</div>
                            <div class="hardware-details">
                                <div class="hardware-label">Platform</div>
                                <div class="hardware-value">${{hardware.platform || 'N/A'}}</div>
                                <div class="hardware-sub">Python ${{hardware.python_version || 'N/A'}}</div>
                            </div>
                        </div>

                        <!-- Capacity Limits -->
                        ${{hardware.capacity_notes ? `
                        <div class="hardware-card">
                            <div class="hardware-icon">📏</div>
                            <div class="hardware-details">
                                <div class="hardware-label">Safe File Limit</div>
                                <div class="hardware-value">${{hardware.capacity_notes.safe_file_limit_mb ? (hardware.capacity_notes.safe_file_limit_mb / 1024).toFixed(1) + ' GB' : 'N/A'}}</div>
                                <div class="hardware-sub">Warn at ${{hardware.capacity_notes.warning_threshold_percent}}% • Critical at ${{hardware.capacity_notes.critical_threshold_percent}}%</div>
                            </div>
                        </div>
                        ` : ''}}
                    </div>
                </div>
            `;
        }}

        // Render identity info section
        function renderIdentityInfo(data) {{
            const identity = data.identity;
            if (!identity) return;

            const envInfo = document.getElementById('environment-info');

            const identityHtml = `
                <div class="identity-section">
                    <h3>Authentication & Identity</h3>
                    <div class="identity-grid">
                        ${{identity.database ? `
                            <div class="identity-card">
                                <h4>Database Authentication</h4>
                                <div class="identity-item"><strong>Method:</strong> ${{identity.database.auth_method || 'N/A'}}</div>
                                <div class="identity-item"><strong>Managed Identity:</strong> ${{identity.database.use_managed_identity ? 'Yes' : 'No'}}</div>
                                ${{identity.database.admin_identity_name ? `<div class="identity-item"><strong>Identity:</strong> ${{identity.database.admin_identity_name}}</div>` : ''}}
                            </div>
                        ` : ''}}
                        ${{identity.storage ? `
                            <div class="identity-card">
                                <h4>Storage Authentication</h4>
                                <div class="identity-item"><strong>Method:</strong> ${{identity.storage.auth_method || 'N/A'}}</div>
                            </div>
                        ` : ''}}
                    </div>
                </div>
            `;

            envInfo.insertAdjacentHTML('afterend', identityHtml);
        }}

        // Component links mapping - links to related interface pages
        const COMPONENT_LINKS = {{
            'storage_containers': {{ url: '/api/interface/storage', label: 'Storage Browser', icon: '📁' }},
            'service_bus': {{ url: '/api/interface/queues', label: 'Queue Monitor', icon: '📨' }},
            'database': {{ url: '/api/interface/database', label: 'Database Monitor', icon: '🐘' }}
        }};

        // Render component cards
        function renderComponents(components) {{
            const grid = document.getElementById('components-grid');

            // Remove all skeleton cards first
            grid.querySelectorAll('.skeleton-card').forEach(card => card.remove());

            if (!components || Object.keys(components).length === 0) {{
                grid.innerHTML = '<p style="color: #626F86; text-align: center; padding: 40px;">No components to display</p>';
                return;
            }}

            // Sort components: healthy first, then unhealthy, then disabled/deprecated
            const sortOrder = {{ healthy: 0, partial: 1, warning: 2, unhealthy: 3, error: 4, disabled: 5, deprecated: 6 }};
            const sortedComponents = Object.entries(components).sort((a, b) => {{
                const statusA = sortOrder[a[1].status] ?? 99;
                const statusB = sortOrder[b[1].status] ?? 99;
                return statusA - statusB;
            }});

            grid.innerHTML = sortedComponents.map(([name, component]) => {{
                const status = component.status || 'unknown';
                const description = component.description || '';
                const details = component.details || {{}};
                const checkedAt = component.checked_at;

                // Check if this component has a link
                const linkInfo = COMPONENT_LINKS[name];
                let linkHtml = '';
                if (linkInfo) {{
                    if (linkInfo.disabled) {{
                        linkHtml = `<span class="component-link disabled" title="${{linkInfo.label}}">${{linkInfo.icon}} ${{linkInfo.label}}</span>`;
                    }} else {{
                        linkHtml = `<a href="${{linkInfo.url}}" class="component-link" onclick="event.stopPropagation();">${{linkInfo.icon}} ${{linkInfo.label}} &rarr;</a>`;
                    }}
                }}

                return `
                    <div class="component-card ${{status}}" data-component-key="${{name}}">
                        <div class="component-header" onclick="toggleDetails('${{name}}')">
                            <div>
                                <div class="component-name">${{formatLabel(name)}}</div>
                                ${{description ? `<div class="component-description">${{description}}</div>` : ''}}
                                ${{linkHtml}}
                            </div>
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <span class="status-badge ${{status}}">${{getStatusIcon(status)}} ${{status}}</span>
                                <span class="expand-indicator">&#x25BC;</span>
                            </div>
                        </div>
                        <div class="component-details" id="details-${{name}}">
                            <div class="details-content">
                                ${{checkedAt ? `
                                    <div class="detail-section">
                                        <div class="detail-label">Last Checked</div>
                                        <div class="detail-value">${{formatDateTime(checkedAt)}}</div>
                                    </div>
                                ` : ''}}
                                ${{Object.keys(details).length > 0 ? `
                                    <div class="detail-section">
                                        <div class="detail-label">Details</div>
                                        <div class="detail-json">${{JSON.stringify(details, null, 2)}}</div>
                                    </div>
                                ` : '<div class="detail-value" style="color: #626F86;">No additional details available</div>'}}
                            </div>
                        </div>
                    </div>
                `;
            }}).join('');
        }}

        // Render debug info if DEBUG_MODE=true
        function renderDebugInfo(data) {{
            const debugInfo = document.getElementById('debug-info');

            if (!data._debug_mode) {{
                debugInfo.classList.add('hidden');
                return;
            }}

            debugInfo.classList.remove('hidden');
            debugInfo.innerHTML = `
                <h3>Debug Mode Active</h3>
                <p style="margin-bottom: 10px; font-size: 13px;">${{data._debug_notice || 'DEBUG_MODE=true'}}</p>
                ${{data.config_sources ? `
                    <div class="detail-section">
                        <div class="detail-label">Configuration Sources</div>
                        <div class="detail-json">${{JSON.stringify(data.config_sources, null, 2)}}</div>
                    </div>
                ` : ''}}
                ${{data.debug_status ? `
                    <div class="detail-section" style="margin-top: 15px;">
                        <div class="detail-label">Debug Status</div>
                        <div class="detail-json">${{JSON.stringify(data.debug_status, null, 2)}}</div>
                    </div>
                ` : ''}}
            `;
        }}

        // Render schema summary section
        function renderSchemaSummary(components) {{
            const schemaSummary = document.getElementById('schema-summary');
            const schemaCards = document.getElementById('schema-cards');

            // Remove skeleton class
            schemaSummary.classList.remove('skeleton-section');

            // Get schema_summary from components
            const schemaSummaryData = components?.schema_summary?.details;
            if (!schemaSummaryData || !schemaSummaryData.schemas) {{
                schemaSummary.classList.add('hidden');
                return;
            }}

            schemaSummary.classList.remove('hidden');

            const schemas = schemaSummaryData.schemas;
            const totalTables = schemaSummaryData.total_tables || 0;

            // Schema icons and highlight classes
            const schemaConfig = {{
                'app': {{ icon: '&#x2699;', label: 'Application', highlight: '' }},
                'geo': {{ icon: '&#x1F5FA;', label: 'PostGIS', highlight: 'geo-highlight' }},
                'pgstac': {{ icon: '&#x1F4E6;', label: 'STAC Catalog', highlight: 'stac-highlight' }},
                'h3': {{ icon: '&#x2B22;', label: 'H3 Hexagons', highlight: '' }}
            }};

            // Build schema cards HTML
            let cardsHtml = '';

            Object.entries(schemas).forEach(([schemaName, schemaData]) => {{
                const config = schemaConfig[schemaName] || {{ icon: '&#x1F4C1;', label: schemaName, highlight: '' }};
                const exists = schemaData.exists;
                const tableCount = schemaData.table_count || 0;
                const tables = schemaData.tables || [];
                const rowCounts = schemaData.row_counts || {{}};

                // Calculate total rows
                let totalRows = 0;
                Object.values(rowCounts).forEach(count => {{
                    if (typeof count === 'number') totalRows += count;
                }});

                // Special stats for pgstac and geo
                let specialStats = '';
                if (schemaName === 'pgstac' && schemaData.stac_counts) {{
                    const stacCounts = schemaData.stac_counts;
                    specialStats = `
                        <div class="schema-stat">
                            <div class="stat-label">Collections</div>
                            <div class="stat-value highlight">${{formatNumber(stacCounts.collections || 0)}}</div>
                        </div>
                        <div class="schema-stat">
                            <div class="stat-label">Items</div>
                            <div class="stat-value highlight">${{formatNumber(stacCounts.items || 0)}}</div>
                        </div>
                    `;
                }} else if (schemaName === 'geo' && schemaData.geometry_columns !== undefined) {{
                    specialStats = `
                        <div class="schema-stat full-width">
                            <div class="stat-label">Geometry Columns</div>
                            <div class="stat-value highlight">${{schemaData.geometry_columns}}</div>
                        </div>
                    `;
                }}

                // Build tables list
                let tablesListHtml = '';
                if (tables.length > 0) {{
                    const tableRows = tables.map(tableName => {{
                        const count = rowCounts[tableName];
                        return `
                            <div class="table-row">
                                <span class="table-name">${{tableName}}</span>
                                <span class="table-count">${{typeof count === 'number' ? formatNumber(count) : '-'}}</span>
                            </div>
                        `;
                    }}).join('');

                    tablesListHtml = `
                        <div class="schema-tables-list">
                            <div class="schema-tables-toggle" onclick="toggleSchemaTables('${{schemaName}}')">
                                <span>&#x25BC;</span> Show ${{tables.length}} tables
                            </div>
                            <div class="schema-tables-content" id="schema-tables-${{schemaName}}">
                                ${{tableRows}}
                            </div>
                        </div>
                    `;
                }}

                cardsHtml += `
                    <div class="schema-card ${{exists ? config.highlight : 'not-found'}}">
                        <div class="schema-card-header">
                            <div class="schema-name">
                                <span class="schema-icon">${{config.icon}}</span>
                                ${{config.label}}
                            </div>
                            <span class="schema-badge ${{exists ? 'exists' : 'missing'}}">
                                ${{exists ? 'Active' : 'Missing'}}
                            </span>
                        </div>
                        ${{exists ? `
                            <div class="schema-stats">
                                <div class="schema-stat">
                                    <div class="stat-label">Tables</div>
                                    <div class="stat-value">${{tableCount}}</div>
                                </div>
                                <div class="schema-stat">
                                    <div class="stat-label">Rows (approx)</div>
                                    <div class="stat-value">${{formatNumber(totalRows)}}</div>
                                </div>
                                ${{specialStats}}
                            </div>
                            ${{tablesListHtml}}
                        ` : `
                            <div style="color: #991B1B; font-size: 12px;">
                                Schema not found in database
                            </div>
                        `}}
                    </div>
                `;
            }});

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
                            <div class="stat-value highlight">${{totalTables}}</div>
                        </div>
                    </div>
                </div>
            ` + cardsHtml;

            schemaCards.innerHTML = cardsHtml;
        }}

        // Toggle schema tables visibility
        function toggleSchemaTables(schemaName) {{
            const content = document.getElementById(`schema-tables-${{schemaName}}`);
            const toggle = content.previousElementSibling;

            if (content.classList.contains('expanded')) {{
                content.classList.remove('expanded');
                toggle.innerHTML = `<span>&#x25BC;</span> Show ${{content.children.length}} tables`;
            }} else {{
                content.classList.add('expanded');
                toggle.innerHTML = `<span>&#x25B2;</span> Hide tables`;
            }}
        }}

        // Format number with commas
        function formatNumber(num) {{
            if (typeof num !== 'number') return num;
            return num.toLocaleString();
        }}

        // Toggle component details
        function toggleDetails(name) {{
            const details = document.getElementById(`details-${{name}}`);
            const header = details.previousElementSibling;

            if (details.classList.contains('expanded')) {{
                details.classList.remove('expanded');
                header.classList.remove('expanded');
            }} else {{
                details.classList.add('expanded');
                header.classList.add('expanded');
            }}
        }}

        // Update last checked timestamp
        function updateLastChecked(timestamp) {{
            const lastChecked = document.getElementById('last-checked');
            if (timestamp) {{
                lastChecked.textContent = `Last checked: ${{formatDateTime(timestamp)}}`;
            }} else {{
                lastChecked.textContent = `Last checked: ${{formatDateTime(new Date())}}`;
            }}
        }}

        // Format label (snake_case to Title Case)
        function formatLabel(str) {{
            return str
                .split('_')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ');
        }}

        // Get status icon
        function getStatusIcon(status) {{
            switch (status) {{
                case 'healthy': return '&#x2705;';
                case 'unhealthy':
                case 'error': return '&#x274C;';
                case 'disabled':
                case 'deprecated': return '&#x26AB;';
                case 'warning':
                case 'partial': return '&#x26A0;';
                default: return '&#x2753;';
            }}
        }}

        // Tooltip functionality
        const tooltip = document.getElementById('diagram-tooltip');
        const diagramContainer = document.querySelector('.architecture-diagram');

        document.querySelectorAll('.component[data-tooltip]').forEach(component => {{
            component.addEventListener('mouseenter', (e) => {{
                const tooltipText = component.getAttribute('data-tooltip');
                if (tooltipText) {{
                    tooltip.textContent = tooltipText;
                    tooltip.classList.add('visible');
                }}
            }});

            component.addEventListener('mousemove', (e) => {{
                const containerRect = diagramContainer.getBoundingClientRect();
                const x = e.clientX - containerRect.left;
                const y = e.clientY - containerRect.top;

                // Position tooltip above cursor
                tooltip.style.left = (x - tooltip.offsetWidth / 2) + 'px';
                tooltip.style.top = (y - tooltip.offsetHeight - 15) + 'px';
            }});

            component.addEventListener('mouseleave', () => {{
                tooltip.classList.remove('visible');
            }});
        }});
        """
