# ============================================================================
# CLAUDE CONTEXT - INTEGRATION GUIDE WEB INTERFACES
# ============================================================================
# STATUS: Web Interface - DDH App Integration Guides
# PURPOSE: Step-by-step guides for external app integration with GeoAPI
# CREATED: 12 JAN 2026
# EXPORTS: IntegrationInterface, ProcessRasterIntegrationInterface
# DEPENDENCIES: azure.functions, web_interfaces.base
# ============================================================================
"""
Integration Guide web interfaces.

Provides step-by-step integration guides showing:
- Block 1: Job submission with live CURL generation
- Block 2: Job monitoring with status polling examples
- Block 3: Output data retrieval with highlighted fields

Each integration guide is tailored to a specific job type (raster, vector, etc.)
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('integration')
class IntegrationInterface(BaseInterface):
    """
    Integration Guide landing page.

    Lists all available integration guides for external applications.
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Integration landing page HTML."""
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()

        return self.wrap_html(
            title="Integration Guides",
            content=content,
            custom_css=custom_css,
            include_htmx=False
        )

    def _generate_html_content(self) -> str:
        """Generate landing page content."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Integration Guides</h1>
                <p class="subtitle">Step-by-step guides for DDH App integration with GeoAPI workflows</p>
            </header>

            <div class="cards-grid">
                <a href="/api/interface/integration-process-raster" class="card">
                    <h3>Process Raster</h3>
                    <p class="description">
                        Convert raster files to Cloud Optimized GeoTIFFs (COGs) and register
                        in STAC catalog. Includes validation, processing, and metadata registration.
                    </p>
                    <div class="card-footer">View Guide &rarr;</div>
                </a>

                <div class="card card-disabled">
                    <h3>Process Vector</h3>
                    <p class="description">
                        Load vector files into PostGIS and register in STAC catalog.
                        Coming soon.
                    </p>
                    <div class="card-footer">Coming Soon</div>
                </div>

                <div class="card card-disabled">
                    <h3>Raster Collection</h3>
                    <p class="description">
                        Process multiple raster files into a unified MosaicJSON collection.
                        Coming soon.
                    </p>
                    <div class="card-footer">Coming Soon</div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for landing page."""
        return """
            .card-disabled {
                opacity: 0.6;
                cursor: not-allowed;
                pointer-events: none;
            }

            .card-disabled .card-footer {
                color: var(--ds-gray);
            }
        """


@InterfaceRegistry.register('integration-process-raster')
class ProcessRasterIntegrationInterface(BaseInterface):
    """
    Process Raster V2 Integration Guide.

    Three-block layout showing:
    1. Job submission with live CURL
    2. Job monitoring with status polling
    3. Output data retrieval
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate Process Raster integration guide HTML."""
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Integration: Process Raster",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=False
        )

    def _generate_html_content(self) -> str:
        """Generate the three-block layout."""
        return """
        <div class="container">
            <!-- Page Header -->
            <header class="dashboard-header">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1>Integration Guide: Process Raster</h1>
                        <p class="subtitle">Step-by-step guide for DDH App integration with the raster processing workflow</p>
                    </div>
                    <a href="/api/interface/integration" class="btn btn-secondary">
                        &larr; All Guides
                    </a>
                </div>
            </header>

            <!-- BLOCK 1: Job Submission -->
            <div class="block-row">
                <div class="block-header">
                    <div class="block-number">1</div>
                    <div class="block-title">Submit Processing Job</div>
                    <div class="block-subtitle">POST /api/jobs/submit/process_raster_v2</div>
                </div>
                <div class="block-content">
                    <!-- Left: Form -->
                    <div class="form-section">
                        <!-- Zone (fixed) -->
                        <div class="form-group">
                            <label>Storage Zone</label>
                            <div class="zone-badge">BRONZE (Source Data)</div>
                        </div>

                        <!-- Container Selection -->
                        <div class="form-group">
                            <label>Container</label>
                            <select id="container-select" onchange="updateCurl()">
                                <option value="">-- Select Container --</option>
                                <option value="bronze-rasters">bronze-rasters</option>
                                <option value="bronze-fathom">bronze-fathom</option>
                                <option value="bronze-uploads">bronze-uploads</option>
                            </select>
                        </div>

                        <!-- File List (compact) -->
                        <div class="form-group">
                            <label>Select Source File</label>
                            <div class="file-list-compact" id="file-list">
                                <div class="file-item" onclick="selectFile(this, 'flood_depth_100yr.tif')">flood_depth_100yr.tif</div>
                                <div class="file-item" onclick="selectFile(this, 'elevation_dem.tif')">elevation_dem.tif</div>
                                <div class="file-item" onclick="selectFile(this, 'landcover_2024.tif')">landcover_2024.tif</div>
                                <div class="file-item" onclick="selectFile(this, 'temperature_avg.tif')">temperature_avg.tif</div>
                            </div>
                        </div>

                        <!-- DDH Identifiers Section -->
                        <div class="ddh-section">
                            <div class="ddh-section-title">DDH Identifiers</div>
                            <div class="form-row">
                                <div class="form-group">
                                    <label>Collection ID</label>
                                    <input type="text" id="collection-id" placeholder="e.g., flood-risk-2024" oninput="updateCurl()">
                                </div>
                                <div class="form-group">
                                    <label>Item ID</label>
                                    <input type="text" id="item-id" placeholder="e.g., depth-100yr-northeast" oninput="updateCurl()">
                                </div>
                            </div>
                        </div>

                        <!-- Processing Options -->
                        <div class="form-row-3">
                            <div class="form-group">
                                <label>Output Format</label>
                                <select id="output-format" onchange="updateCurl()">
                                    <option value="COG">COG (Cloud Optimized)</option>
                                    <option value="GeoTIFF">GeoTIFF</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Compression</label>
                                <select id="compression" onchange="updateCurl()">
                                    <option value="LZW">LZW</option>
                                    <option value="DEFLATE">DEFLATE</option>
                                    <option value="ZSTD">ZSTD</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>Target CRS</label>
                                <select id="target-crs" onchange="updateCurl()">
                                    <option value="EPSG:4326">EPSG:4326 (WGS84)</option>
                                    <option value="EPSG:3857">EPSG:3857 (Web Mercator)</option>
                                </select>
                            </div>
                        </div>

                        <button class="btn btn-primary" style="width: 100%;" onclick="simulateSubmit()">Submit Job</button>
                    </div>

                    <!-- Right: CURL -->
                    <div class="curl-section">
                        <div class="curl-header">
                            <span class="curl-label">CURL Command</span>
                            <button class="copy-btn" onclick="copyCurl('curl-submit')">Copy</button>
                        </div>
                        <pre class="curl-code" id="curl-submit"><span class="cmd">curl</span> <span class="flag">-X POST</span> \\
  <span class="url">"https://rmhazuregeoapi.../api/jobs/submit/process_raster_v2"</span> \\
  <span class="flag">-H</span> <span class="string">"Content-Type: application/json"</span> \\
  <span class="flag">-d</span> '{
    <span class="key">"source_container"</span>: <span class="string">""</span>,
    <span class="key">"source_blob"</span>: <span class="string">""</span>,
    <span class="key">"collection_id"</span>: <span class="string">""</span>,
    <span class="key">"item_id"</span>: <span class="string">""</span>,
    <span class="key">"output_format"</span>: <span class="string">"COG"</span>,
    <span class="key">"compression"</span>: <span class="string">"LZW"</span>,
    <span class="key">"target_crs"</span>: <span class="string">"EPSG:4326"</span>
  }'</pre>
                    </div>
                </div>
            </div>

            <!-- Workflow Connector -->
            <div class="workflow-connector">
                <div class="workflow-arrow">Response contains job_id</div>
            </div>

            <!-- BLOCK 2: Job Monitoring -->
            <div class="block-row">
                <div class="block-header">
                    <div class="block-number">2</div>
                    <div class="block-title">Monitor Job Progress</div>
                    <div class="block-subtitle">Poll until status = "completed"</div>
                </div>
                <div class="block-content">
                    <!-- Left: Mini Monitor -->
                    <div class="monitor-mini">
                        <div class="job-status-bar">
                            <span class="job-id-display placeholder" id="job-id-display">(submit job to see ID)</span>
                            <span class="status-badge status-processing" id="status-badge">PROCESSING</span>
                        </div>

                        <div class="stages-mini">
                            <div class="stage-mini completed" id="stage-1">
                                <div class="stage-mini-number">Stage 1</div>
                                <div class="stage-mini-name">Validate</div>
                                <div class="stage-mini-status">1/1 tasks</div>
                            </div>
                            <div class="stage-mini active" id="stage-2">
                                <div class="stage-mini-number">Stage 2</div>
                                <div class="stage-mini-name">Process</div>
                                <div class="stage-mini-status">0/1 tasks</div>
                            </div>
                            <div class="stage-mini" id="stage-3">
                                <div class="stage-mini-number">Stage 3</div>
                                <div class="stage-mini-name">Register</div>
                                <div class="stage-mini-status">pending</div>
                            </div>
                        </div>
                    </div>

                    <!-- Right: CURL Examples -->
                    <div class="curl-section">
                        <div class="curl-header">
                            <span class="curl-label">CURL - Check Job Status</span>
                            <button class="copy-btn" onclick="copyCurl('curl-status')">Copy</button>
                        </div>
                        <pre class="curl-code" id="curl-status"><span class="cmd">curl</span> <span class="url">"https://rmhazuregeoapi.../api/jobs/status/<span id="curl-job-id-1">{job_id}</span>"</span>

<span class="comment"># Response:</span>
{
  <span class="key">"job_id"</span>: <span class="string">"abc123..."</span>,
  <span class="key">"status"</span>: <span class="string">"processing"</span>,
  <span class="key">"stage"</span>: <span class="number">2</span>,
  <span class="key">"total_stages"</span>: <span class="number">3</span>,
  <span class="key">"progress_pct"</span>: <span class="number">66</span>
}</pre>
                    </div>
                </div>
            </div>

            <!-- Workflow Connector -->
            <div class="workflow-connector">
                <div class="workflow-arrow">When status = "completed"</div>
            </div>

            <!-- BLOCK 3: Output Data -->
            <div class="block-row">
                <div class="block-header">
                    <div class="block-number">3</div>
                    <div class="block-title">Retrieve Output Data</div>
                    <div class="block-subtitle">GET /api/jobs/status/{job_id}</div>
                </div>
                <div class="block-content">
                    <!-- Left: JSON Output -->
                    <div class="output-section">
                        <div class="json-display">
{
  <span class="key">"job_id"</span>: <span class="string">"a1b2c3d4e5f6..."</span>,
  <span class="key">"status"</span>: <span class="string">"completed"</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_raster_v2"</span>,
  <span class="key">"result_data"</span>: {
    <span class="key">"cog"</span>: {
      <span class="key highlight highlight-url">"output_url"</span>: <span class="string highlight highlight-url">"https://rmhazuregeosilver.blob.../silver-cogs/flood_depth_100yr.tif"</span>,
      <span class="key">"size_bytes"</span>: <span class="number">15234567</span>,
      <span class="key">"compression"</span>: <span class="string">"LZW"</span>
    },
    <span class="key">"stac"</span>: {
      <span class="key highlight highlight-ddh">"collection_id"</span>: <span class="string highlight highlight-ddh">"flood-risk-2024"</span>,
      <span class="key highlight highlight-ddh">"item_id"</span>: <span class="string highlight highlight-ddh">"depth-100yr-northeast"</span>,
      <span class="key highlight highlight-url">"item_url"</span>: <span class="string highlight highlight-url">"https://rmhazuregeoapi.../api/stac/collections/flood-risk-2024/items/depth-100yr-northeast"</span>
    },
    <span class="key">"metadata"</span>: {
      <span class="key">"bbox"</span>: [<span class="number">-74.5</span>, <span class="number">40.2</span>, <span class="number">-73.7</span>, <span class="number">41.1</span>],
      <span class="key">"crs"</span>: <span class="string">"EPSG:4326"</span>,
      <span class="key">"resolution"</span>: <span class="number">10.0</span>
    }
  }
}</div>
                        <div class="legend">
                            <div class="legend-item">
                                <div class="legend-color url"></div>
                                <span>Output URLs (for data access)</span>
                            </div>
                            <div class="legend-item">
                                <div class="legend-color ddh"></div>
                                <span>DDH Identifiers (for cataloging)</span>
                            </div>
                        </div>
                    </div>

                    <!-- Right: CURL -->
                    <div class="curl-section">
                        <div class="curl-header">
                            <span class="curl-label">CURL - Get Completed Job</span>
                            <button class="copy-btn" onclick="copyCurl('curl-result')">Copy</button>
                        </div>
                        <pre class="curl-code" id="curl-result"><span class="cmd">curl</span> <span class="url">"https://rmhazuregeoapi.../api/jobs/status/<span id="curl-job-id-2">{job_id}</span>"</span>

<span class="comment"># Extract COG URL:</span>
<span class="cmd">curl</span> <span class="url">"...api/jobs/status/{job_id}"</span> | \\
  <span class="cmd">jq</span> <span class="string">'.result_data.cog.output_url'</span>

<span class="comment"># Fetch STAC Item directly:</span>
<span class="cmd">curl</span> <span class="url">"https://rmhazuregeoapi.../api/stac/collections/<span id="curl-collection-id">{collection_id}</span>/items/<span id="curl-item-id">{item_id}</span>"</span></pre>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for integration guide."""
        return """
            /* ============================================================
               BLOCK ROWS - Integration Steps
               ============================================================ */
            .block-row {
                background: white;
                border-radius: 3px;
                margin-bottom: 20px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                overflow: hidden;
                border-left: 4px solid var(--ds-blue-primary);
            }

            .block-header {
                background: var(--ds-bg);
                padding: 16px 24px;
                display: flex;
                align-items: center;
                gap: 16px;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .block-number {
                background: var(--ds-blue-primary);
                color: white;
                width: 32px;
                height: 32px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 700;
                font-size: 16px;
                flex-shrink: 0;
            }

            .block-title {
                font-size: 16px;
                font-weight: 700;
                color: var(--ds-navy);
            }

            .block-subtitle {
                color: var(--ds-gray);
                font-size: 13px;
                margin-left: auto;
                font-family: 'Monaco', 'Courier New', monospace;
            }

            .block-content {
                padding: 24px;
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 24px;
            }

            /* ============================================================
               FORM STYLES
               ============================================================ */
            .form-section {
                display: flex;
                flex-direction: column;
                gap: 16px;
            }

            .form-row {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
            }

            .form-row-3 {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                gap: 16px;
            }

            /* Zone Badge (non-selectable) */
            .zone-badge {
                background: #cd7f32;
                color: white;
                padding: 10px 16px;
                border-radius: 3px;
                font-weight: 600;
                text-align: center;
                font-size: 14px;
            }

            /* File List (compact) */
            .file-list-compact {
                background: var(--ds-bg);
                border: 1px solid var(--ds-gray-light);
                border-radius: 3px;
                height: 100px;
                overflow-y: auto;
                padding: 8px;
            }

            .file-item {
                padding: 6px 10px;
                font-size: 13px;
                color: var(--ds-gray);
                cursor: pointer;
                border-radius: 3px;
                font-family: 'Monaco', 'Courier New', monospace;
            }

            .file-item:hover {
                background: var(--ds-gray-light);
                color: var(--ds-navy);
            }

            .file-item.selected {
                background: var(--ds-blue-primary);
                color: white;
            }

            /* DDH Section */
            .ddh-section {
                background: var(--ds-bg);
                border: 2px solid var(--ds-gold);
                border-radius: 3px;
                padding: 16px;
            }

            .ddh-section-title {
                color: var(--ds-navy);
                font-size: 14px;
                font-weight: 700;
                margin-bottom: 12px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .ddh-section-title::before {
                content: "";
                display: inline-block;
                width: 4px;
                height: 16px;
                background: var(--ds-gold);
                border-radius: 2px;
            }

            /* ============================================================
               CURL DISPLAY - Code block styling
               ============================================================ */
            .curl-section {
                background: #1e1e1e;
                border-radius: 3px;
                overflow: hidden;
                display: flex;
                flex-direction: column;
            }

            .curl-header {
                background: #2d2d2d;
                padding: 10px 16px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #444;
            }

            .curl-label {
                color: #888;
                font-size: 12px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .copy-btn {
                background: var(--ds-blue-primary);
                color: white;
                border: none;
                padding: 4px 12px;
                border-radius: 3px;
                font-size: 12px;
                font-weight: 600;
                cursor: pointer;
                transition: background 0.2s;
            }

            .copy-btn:hover {
                background: var(--ds-cyan);
            }

            .curl-code {
                padding: 16px;
                font-family: 'Monaco', 'Courier New', monospace;
                font-size: 12px;
                color: #d4d4d4;
                white-space: pre-wrap;
                word-break: break-all;
                max-height: 240px;
                overflow-y: auto;
                line-height: 1.5;
                flex: 1;
            }

            .curl-code .cmd { color: #569cd6; }
            .curl-code .flag { color: #9cdcfe; }
            .curl-code .url { color: #ce9178; }
            .curl-code .string { color: #ce9178; }
            .curl-code .key { color: #9cdcfe; }
            .curl-code .comment { color: #6a9955; }
            .curl-code .number { color: #b5cea8; }

            /* ============================================================
               BLOCK 2: MONITORING - Mini status display
               ============================================================ */
            .monitor-mini {
                display: flex;
                flex-direction: column;
                gap: 16px;
            }

            .job-status-bar {
                display: flex;
                align-items: center;
                gap: 16px;
                padding: 12px 16px;
                background: var(--ds-bg);
                border-radius: 3px;
                border: 1px solid var(--ds-gray-light);
            }

            .job-id-display {
                font-family: 'Monaco', 'Courier New', monospace;
                font-size: 13px;
                color: var(--ds-blue-primary);
            }

            .job-id-display.placeholder {
                color: var(--ds-gray);
                font-style: italic;
            }

            .stages-mini {
                display: flex;
                gap: 12px;
            }

            .stage-mini {
                flex: 1;
                background: var(--ds-bg);
                border: 1px solid var(--ds-gray-light);
                border-radius: 3px;
                padding: 12px;
                text-align: center;
            }

            .stage-mini.active {
                border-color: var(--ds-blue-primary);
                background: rgba(0, 113, 188, 0.05);
            }

            .stage-mini.completed {
                border-color: #059669;
                background: rgba(5, 150, 105, 0.05);
            }

            .stage-mini-number {
                font-size: 11px;
                color: var(--ds-gray);
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            .stage-mini-name {
                font-size: 14px;
                font-weight: 600;
                color: var(--ds-navy);
                margin-top: 4px;
            }

            .stage-mini-status {
                font-size: 11px;
                color: var(--ds-gray);
                margin-top: 4px;
            }

            /* ============================================================
               BLOCK 3: OUTPUT - JSON display
               ============================================================ */
            .output-section {
                display: flex;
                flex-direction: column;
                gap: 16px;
            }

            .json-display {
                background: #1e1e1e;
                border-radius: 3px;
                padding: 16px;
                font-family: 'Monaco', 'Courier New', monospace;
                font-size: 12px;
                max-height: 320px;
                overflow-y: auto;
                color: #d4d4d4;
                line-height: 1.5;
            }

            .json-display .key { color: #9cdcfe; }
            .json-display .string { color: #ce9178; }
            .json-display .number { color: #b5cea8; }

            .json-display .highlight {
                padding: 2px 4px;
                border-radius: 3px;
            }

            .json-display .highlight-url {
                background: rgba(0, 113, 188, 0.2);
            }

            .json-display .highlight-ddh {
                background: rgba(255, 193, 77, 0.25);
            }

            /* Legend */
            .legend {
                display: flex;
                gap: 20px;
                padding: 12px 16px;
                background: var(--ds-bg);
                border-radius: 3px;
                font-size: 12px;
            }

            .legend-item {
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .legend-color {
                width: 14px;
                height: 14px;
                border-radius: 3px;
            }

            .legend-color.url { background: rgba(0, 113, 188, 0.4); }
            .legend-color.ddh { background: rgba(255, 193, 77, 0.5); }

            /* ============================================================
               WORKFLOW CONNECTOR
               ============================================================ */
            .workflow-connector {
                display: flex;
                justify-content: center;
                padding: 12px 0;
            }

            .workflow-arrow {
                color: var(--ds-gray);
                font-size: 13px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .workflow-arrow::before,
            .workflow-arrow::after {
                content: "";
                width: 40px;
                height: 2px;
                background: var(--ds-gray-light);
            }

            /* ============================================================
               RESPONSIVE
               ============================================================ */
            @media (max-width: 1100px) {
                .block-content {
                    grid-template-columns: 1fr;
                }

                .form-row-3 {
                    grid-template-columns: 1fr 1fr;
                }
            }

            @media (max-width: 768px) {
                .form-row,
                .form-row-3 {
                    grid-template-columns: 1fr;
                }

                .block-header {
                    flex-wrap: wrap;
                }

                .block-subtitle {
                    margin-left: 48px;
                    width: 100%;
                }
            }
        """

    def _generate_custom_js(self) -> str:
        """Generate JavaScript for interactive CURL generation."""
        return """
            // State
            let selectedFile = '';
            let currentJobId = '';

            function selectFile(element, filename) {
                document.querySelectorAll('.file-item').forEach(el => el.classList.remove('selected'));
                element.classList.add('selected');
                selectedFile = filename;
                updateCurl();
            }

            function updateCurl() {
                const container = document.getElementById('container-select').value;
                const collectionId = document.getElementById('collection-id').value;
                const itemId = document.getElementById('item-id').value;
                const outputFormat = document.getElementById('output-format').value;
                const compression = document.getElementById('compression').value;
                const targetCrs = document.getElementById('target-crs').value;

                const curlHtml = `<span class="cmd">curl</span> <span class="flag">-X POST</span> \\\\
  <span class="url">"https://rmhazuregeoapi.../api/jobs/submit/process_raster_v2"</span> \\\\
  <span class="flag">-H</span> <span class="string">"Content-Type: application/json"</span> \\\\
  <span class="flag">-d</span> '{
    <span class="key">"source_container"</span>: <span class="string">"${container}"</span>,
    <span class="key">"source_blob"</span>: <span class="string">"${selectedFile}"</span>,
    <span class="key">"collection_id"</span>: <span class="string">"${collectionId}"</span>,
    <span class="key">"item_id"</span>: <span class="string">"${itemId}"</span>,
    <span class="key">"output_format"</span>: <span class="string">"${outputFormat}"</span>,
    <span class="key">"compression"</span>: <span class="string">"${compression}"</span>,
    <span class="key">"target_crs"</span>: <span class="string">"${targetCrs}"</span>
  }'`;

                document.getElementById('curl-submit').innerHTML = curlHtml;

                // Update Block 3 CURL with collection/item IDs
                if (collectionId) {
                    document.getElementById('curl-collection-id').textContent = collectionId;
                }
                if (itemId) {
                    document.getElementById('curl-item-id').textContent = itemId;
                }
            }

            function simulateSubmit() {
                // Generate a fake job ID for demo
                currentJobId = 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6';

                // Update displays
                document.getElementById('job-id-display').textContent = currentJobId.substring(0, 16) + '...';
                document.getElementById('job-id-display').classList.remove('placeholder');

                // Update CURL job IDs in Block 2 and 3
                document.getElementById('curl-job-id-1').textContent = currentJobId.substring(0, 16) + '...';
                document.getElementById('curl-job-id-2').textContent = currentJobId.substring(0, 16) + '...';

                // Simulate progress
                simulateProgress();
            }

            function simulateProgress() {
                const stages = ['stage-1', 'stage-2', 'stage-3'];
                let currentStage = 0;

                // Reset stages
                stages.forEach(s => {
                    document.getElementById(s).classList.remove('active', 'completed');
                });
                document.getElementById('stage-1').classList.add('completed');
                document.getElementById('stage-2').classList.add('active');
                document.getElementById('status-badge').textContent = 'PROCESSING';
                document.getElementById('status-badge').className = 'status-badge status-processing';

                currentStage = 2;

                const interval = setInterval(() => {
                    if (currentStage > 0 && currentStage <= stages.length) {
                        document.getElementById(stages[currentStage - 1]).classList.remove('active');
                        document.getElementById(stages[currentStage - 1]).classList.add('completed');
                    }

                    currentStage++;

                    if (currentStage <= stages.length) {
                        document.getElementById(stages[currentStage - 1]).classList.add('active');
                    } else {
                        clearInterval(interval);
                        document.getElementById('status-badge').textContent = 'COMPLETED';
                        document.getElementById('status-badge').className = 'status-badge status-completed';
                    }
                }, 1500);
            }

            function copyCurl(elementId) {
                const element = document.getElementById(elementId);
                const text = element.textContent;
                navigator.clipboard.writeText(text).then(() => {
                    // Find the copy button in the curl-header
                    const header = element.previousElementSibling;
                    const btn = header ? header.querySelector('.copy-btn') : null;
                    if (btn) {
                        const originalText = btn.textContent;
                        btn.textContent = 'Copied!';
                        setTimeout(() => btn.textContent = originalText, 2000);
                    }
                });
            }
        """
