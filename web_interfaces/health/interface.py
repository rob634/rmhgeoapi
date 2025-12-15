"""
Health monitoring interface module.

Web dashboard for viewing system health status with component cards and expandable details.

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
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        tooltips = self._get_component_tooltips()
        custom_js = self._generate_custom_js(tooltips)

        return self.wrap_html(
            title="System Health Dashboard",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )

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
        long_queue = config.queues.long_running_raster_tasks_queue

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
            'comp-long-queue': f"Queue: {long_queue}\n(Docker worker - not implemented)",

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

            # Not implemented
            'comp-container': f"Docker Worker\nQueue: {long_queue}\n(not implemented)",
            'comp-titiler-xarray': "TiTiler-xarray\n(not implemented)",
            'comp-zarr-store': "Zarr Store\n(not implemented)",
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

                    <!-- Arrow: Orchestrator -> Long Task Queue (NOT IMPLEMENTED) -->
                    <path d="M 440 360 L 520 435" class="flow-arrow inactive" marker-end="url(#arrowhead-grey)"/>

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

                    <!-- ========== LONG-RUNNING TASK PATH - NOT IMPLEMENTED ========== -->
                    <g class="component disabled" id="comp-long-queue" data-component="task_queue_long" data-tooltip="(not implemented)">
                        <rect x="520" y="405" width="100" height="60" rx="6" class="comp-box inactive"/>
                        <text x="570" y="430" class="comp-icon disabled">📨</text>
                        <text x="570" y="450" class="comp-label disabled">Long Queue</text>
                        <circle cx="610" cy="415" r="8" class="status-indicator" data-status="disabled"/>
                    </g>

                    <path d="M 620 435 L 680 435" class="flow-arrow inactive" marker-end="url(#arrowhead-grey)"/>

                    <g class="component disabled" id="comp-container" data-component="worker_container" data-tooltip="(not implemented)">
                        <rect x="680" y="405" width="110" height="60" rx="6" class="comp-box inactive"/>
                        <text x="735" y="430" class="comp-icon disabled">🐳</text>
                        <text x="735" y="450" class="comp-label disabled">Long Worker</text>
                        <circle cx="780" cy="415" r="8" class="status-indicator" data-status="disabled"/>
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

                    <!-- ========== NEW COLUMN: Zarr/xarray (NOT IMPLEMENTED - grey) ========== -->
                    <!-- TiTiler-xarray: above Zarr Store (x=1005 center) - NOT IMPLEMENTED -->
                    <g class="component disabled" id="comp-titiler-xarray" data-tooltip="(not implemented)">
                        <rect x="955" y="5" width="100" height="60" rx="6" class="comp-box inactive"/>
                        <text x="1005" y="30" class="comp-icon disabled">🐳</text>
                        <text x="1005" y="50" class="comp-label disabled">TiTiler-xarray</text>
                        <circle cx="1045" cy="15" r="8" class="status-indicator" data-status="disabled"/>
                    </g>

                    <!-- Zarr Store: to the right of PostGIS (x=1005 center) - NOT IMPLEMENTED -->
                    <g class="component disabled" id="comp-zarr-store" data-tooltip="(not implemented)">
                        <rect x="955" y="95" width="100" height="60" rx="6" class="comp-box inactive"/>
                        <text x="1005" y="120" class="comp-icon disabled">📦</text>
                        <text x="1005" y="140" class="comp-label disabled">Zarr Store</text>
                        <circle cx="1045" cy="105" r="8" class="status-indicator" data-status="disabled"/>
                    </g>

                    <!-- Arrow: Zarr Store -> TiTiler-xarray (up) - grey/dashed for not implemented -->
                    <path d="M 1005 95 L 1005 65" class="flow-arrow inactive" marker-end="url(#arrowhead-grey)"/>

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

    def _generate_custom_js(self, tooltips: dict) -> str:
        """Generate custom JavaScript for Health Dashboard."""
        tooltips_json = json.dumps(tooltips)

        # Inject dynamic tooltips at the start, then use regular string for the rest
        return f"""
        // Dynamic component tooltips from server config
        const COMPONENT_TOOLTIPS = {tooltips_json};

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
            'comp-ogc-features': 'ogc_features'          // OGC Features API
        }};

        // Update architecture diagram status indicators
        function updateDiagramStatus(components) {{
            if (!components) return;

            // Update each component in the diagram
            Object.entries(COMPONENT_MAPPING).forEach(([svgId, healthKey]) => {{
                const component = components[healthKey];
                const indicator = document.querySelector(`#${{svgId}} .status-indicator`);

                if (indicator) {{
                    let status = 'unknown';
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
                    indicator.setAttribute('data-status', status);
                }}
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

        // Load health data from API
        async function loadHealth() {{
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

            try {{
                const data = await fetchJSON(`${{API_BASE_URL}}/api/health`);

                // Render overall status
                renderOverallStatus(data);

                // Render environment info
                renderEnvironmentInfo(data);

                // Render identity info
                renderIdentityInfo(data);

                // Render component cards
                renderComponents(data.components);

                // Update architecture diagram
                updateDiagramStatus(data.components);

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

            if (Object.keys(env).length === 0) {{
                envInfo.classList.add('hidden');
                return;
            }}

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

        // Render component cards
        function renderComponents(components) {{
            const grid = document.getElementById('components-grid');

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

                return `
                    <div class="component-card ${{status}}" data-component-key="${{name}}">
                        <div class="component-header" onclick="toggleDetails('${{name}}')">
                            <div>
                                <div class="component-name">${{formatLabel(name)}}</div>
                                ${{description ? `<div class="component-description">${{description}}</div>` : ''}}
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
                                        <div class="detail-value">${{new Date(checkedAt).toLocaleString()}}</div>
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
                lastChecked.textContent = `Last checked: ${{new Date(timestamp).toLocaleString()}}`;
            }} else {{
                lastChecked.textContent = `Last checked: ${{new Date().toLocaleString()}}`;
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
