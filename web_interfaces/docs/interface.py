"""
API Documentation Interface.

Static rendering of API documentation for key job submission endpoints.
Focuses on process_vector and process_raster jobs.

Note: Future enhancement could use OpenAPI/Swagger for dynamic docs.
See TODO.md "Dynamic OpenAPI Documentation Generation" for details.
"""

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface


@InterfaceRegistry.register('docs')
class DocsInterface(BaseInterface):
    """
    API documentation interface.

    Provides OpenAPI-style documentation for:
        - process_vector job (CSV, GeoJSON, Shapefile, etc.)
        - process_raster job (GeoTIFF to COG conversion)
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate API documentation page."""
        return self.wrap_html(
            title="API Documentation - Job Submission",
            content=self._generate_html_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js()
        )

    def _generate_css(self) -> str:
        """Documentation-specific styles."""
        return """
            .docs-header {
                background: linear-gradient(135deg, var(--wb-navy) 0%, var(--wb-blue-dark) 100%);
                color: white;
                padding: 30px;
                border-radius: 8px;
                margin-bottom: 24px;
            }

            .docs-header h1 {
                margin: 0 0 8px 0;
                font-size: 28px;
            }

            .subtitle {
                opacity: 0.9;
                font-size: 16px;
                margin: 0;
            }

            .endpoint-section {
                background: white;
                border-radius: 8px;
                margin-bottom: 24px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
                overflow: hidden;
            }

            .endpoint-header {
                background: var(--wb-bg);
                padding: 20px 24px;
                border-bottom: 1px solid var(--wb-gray-light);
                display: flex;
                align-items: center;
                gap: 16px;
            }

            .endpoint-header h2 {
                margin: 0;
                font-size: 20px;
                color: var(--wb-navy);
            }

            .method-badge {
                font-family: monospace;
                font-weight: 700;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 14px;
            }

            .method-badge.post {
                background: #28a745;
                color: white;
            }

            .endpoint-path {
                font-family: 'Monaco', 'Consolas', monospace;
                font-size: 14px;
                color: var(--wb-blue-primary);
                background: white;
                padding: 4px 8px;
                border-radius: 4px;
                border: 1px solid #ddd;
            }

            .endpoint-body {
                padding: 24px;
            }

            .endpoint-desc {
                color: var(--wb-gray);
                margin-bottom: 20px;
                line-height: 1.6;
            }

            .params-section {
                margin-bottom: 24px;
            }

            .params-section h3 {
                font-size: 16px;
                color: var(--wb-navy);
                margin: 0 0 12px 0;
                padding-bottom: 8px;
                border-bottom: 1px solid var(--wb-gray-light);
            }

            .params-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }

            .params-table th,
            .params-table td {
                padding: 10px 12px;
                text-align: left;
                border-bottom: 1px solid #eee;
            }

            .params-table th {
                background: #f8f9fa;
                font-weight: 600;
                color: var(--wb-navy);
            }

            .param-name {
                font-family: monospace;
                color: var(--wb-blue-primary);
                font-weight: 600;
            }

            .param-type {
                font-family: monospace;
                font-size: 12px;
                color: #6c757d;
                background: #f8f9fa;
                padding: 2px 6px;
                border-radius: 3px;
            }

            .param-required {
                color: #dc3545;
                font-weight: 600;
                font-size: 12px;
            }

            .param-optional {
                color: #6c757d;
                font-size: 12px;
            }

            .code-block {
                background: #2d3748;
                color: #e2e8f0;
                padding: 16px;
                border-radius: 6px;
                font-family: 'Monaco', 'Consolas', monospace;
                font-size: 13px;
                overflow-x: auto;
                margin: 12px 0;
            }

            .code-block .comment {
                color: #68d391;
            }

            .code-block .string {
                color: #fbd38d;
            }

            .code-block .key {
                color: #90cdf4;
            }

            .example-tabs {
                display: flex;
                gap: 8px;
                margin-bottom: 12px;
            }

            .example-tab {
                padding: 8px 16px;
                background: #f8f9fa;
                border: 1px solid #ddd;
                border-radius: 4px;
                cursor: pointer;
                font-size: 13px;
                transition: all 0.2s;
            }

            .example-tab:hover {
                background: #e9ecef;
            }

            .example-tab.active {
                background: var(--wb-blue-primary);
                color: white;
                border-color: var(--wb-blue-primary);
            }

            .response-section {
                margin-top: 20px;
            }

            .response-section h4 {
                font-size: 14px;
                color: var(--wb-navy);
                margin: 0 0 8px 0;
            }

            .status-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
                margin-right: 8px;
            }

            .status-badge.success {
                background: #d4edda;
                color: #155724;
            }

            .status-badge.error {
                background: #f8d7da;
                color: #721c24;
            }

            .toc {
                background: white;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 24px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .toc h3 {
                margin: 0 0 12px 0;
                color: var(--wb-navy);
                font-size: 16px;
            }

            .toc ul {
                list-style: none;
                padding: 0;
                margin: 0;
            }

            .toc li {
                padding: 6px 0;
            }

            .toc a {
                color: var(--wb-blue-primary);
                text-decoration: none;
            }

            .toc a:hover {
                text-decoration: underline;
            }

            .file-types {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 8px;
            }

            .file-type {
                background: var(--wb-bg);
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 12px;
                font-family: monospace;
                border: 1px solid #ddd;
            }
        """

    def _generate_html_content(self) -> str:
        """Generate documentation content."""
        return """
        <div class="container">
            <header class="docs-header">
                <h1>API Documentation</h1>
                <p class="subtitle">Job Submission Endpoints for Geospatial Data Processing</p>
            </header>

            <!-- Table of Contents -->
            <div class="toc">
                <h3>Endpoints</h3>
                <ul>
                    <li><a href="#process-vector">POST /api/jobs/submit/process_vector</a> - Vector data ingestion</li>
                    <li><a href="#process-raster">POST /api/jobs/submit/process_raster</a> - Raster to COG conversion</li>
                    <li><a href="#job-status">GET /api/jobs/status/{job_id}</a> - Check job status</li>
                </ul>
            </div>

            <!-- Process Vector -->
            <div id="process-vector" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/jobs/submit/process_vector</code>
                    <h2>Process Vector</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Load vector data into PostGIS with idempotent DELETE+INSERT pattern.
                        Supports CSV, GeoJSON, Shapefile, GeoPackage, KML, and KMZ formats.
                        Creates STAC metadata and enables OGC Features API access.
                    </p>

                    <div class="params-section">
                        <h3>Supported File Types</h3>
                        <div class="file-types">
                            <span class="file-type">.csv</span>
                            <span class="file-type">.geojson</span>
                            <span class="file-type">.json</span>
                            <span class="file-type">.gpkg</span>
                            <span class="file-type">.kml</span>
                            <span class="file-type">.kmz</span>
                            <span class="file-type">.shp (zipped)</span>
                        </div>
                    </div>

                    <div class="params-section">
                        <h3>Parameters</h3>
                        <table class="params-table">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Type</th>
                                    <th>Required</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><span class="param-name">blob_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>Source file path in blob container</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">file_extension</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>File type: csv, geojson, json, gpkg, kml, kmz, shp, zip</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">table_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>Target PostGIS table name (will be created)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">container_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Source container (default: rmhazuregeobronze)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">schema</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>PostgreSQL schema (default: geo)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">chunk_size</span></td>
                                    <td><span class="param-type">integer</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Rows per chunk (100-500000, auto-calculated if not set)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">converter_params</span></td>
                                    <td><span class="param-type">object</span></td>
                                    <td><span class="param-optional">Required for CSV</span></td>
                                    <td>CSV: {lat_name, lon_name} or {wkt_column}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="example-tabs">
                            <button class="example-tab active" onclick="showExample('vector', 'csv')">CSV</button>
                            <button class="example-tab" onclick="showExample('vector', 'geojson')">GeoJSON</button>
                            <button class="example-tab" onclick="showExample('vector', 'shapefile')">Shapefile</button>
                        </div>

                        <div id="vector-csv" class="code-block">
<span class="comment"># CSV with lat/lon columns</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/process_vector \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"blob_name"</span>: <span class="string">"data/events.csv"</span>,
    <span class="key">"file_extension"</span>: <span class="string">"csv"</span>,
    <span class="key">"table_name"</span>: <span class="string">"events_table"</span>,
    <span class="key">"converter_params"</span>: {
      <span class="key">"lat_name"</span>: <span class="string">"latitude"</span>,
      <span class="key">"lon_name"</span>: <span class="string">"longitude"</span>
    }
  }'</div>

                        <div id="vector-geojson" class="code-block" style="display: none;">
<span class="comment"># GeoJSON file</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/process_vector \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"blob_name"</span>: <span class="string">"boundaries.geojson"</span>,
    <span class="key">"file_extension"</span>: <span class="string">"geojson"</span>,
    <span class="key">"table_name"</span>: <span class="string">"admin_boundaries"</span>
  }'</div>

                        <div id="vector-shapefile" class="code-block" style="display: none;">
<span class="comment"># Zipped Shapefile</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/process_vector \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"blob_name"</span>: <span class="string">"roads.zip"</span>,
    <span class="key">"file_extension"</span>: <span class="string">"shp"</span>,
    <span class="key">"table_name"</span>: <span class="string">"roads_network"</span>
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">200 OK</span>
                        <div class="code-block">
{
  <span class="key">"job_id"</span>: <span class="string">"a3f2c1b8e9d7..."</span>,
  <span class="key">"status"</span>: <span class="string">"created"</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_vector"</span>,
  <span class="key">"message"</span>: <span class="string">"Job created and queued"</span>
}</div>
                    </div>
                </div>
            </div>

            <!-- Process Raster -->
            <div id="process-raster" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/jobs/submit/process_raster</code>
                    <h2>Process Raster</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Convert raster files (GeoTIFF, etc.) to Cloud-Optimized GeoTIFF (COG) with STAC metadata.
                        Outputs are served via TiTiler for web map visualization.
                    </p>

                    <div class="params-section">
                        <h3>Parameters</h3>
                        <table class="params-table">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Type</th>
                                    <th>Required</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><span class="param-name">blob_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>Raster file name in blob storage</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">container_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>Source blob container</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">collection_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>STAC collection ID (default: system-rasters)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">output_tier</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>analysis (DEFLATE), visualization (JPEG), archive (LZW)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">target_crs</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Target CRS (default: EPSG:4326)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">raster_type</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>auto, rgb, rgba, dem, categorical, multispectral</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">output_folder</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Custom output folder in silver-cogs container</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="code-block">
<span class="comment"># Convert GeoTIFF to COG</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/process_raster \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"blob_name"</span>: <span class="string">"satellite_image.tif"</span>,
    <span class="key">"container_name"</span>: <span class="string">"rmhazuregeobronze"</span>,
    <span class="key">"output_tier"</span>: <span class="string">"analysis"</span>,
    <span class="key">"output_folder"</span>: <span class="string">"cogs/my_project"</span>
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Successful Response</h4>
                        <span class="status-badge success">200 OK</span>
                        <div class="code-block">
{
  <span class="key">"job_id"</span>: <span class="string">"def456abc789..."</span>,
  <span class="key">"status"</span>: <span class="string">"created"</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_raster"</span>,
  <span class="key">"message"</span>: <span class="string">"Job created and queued"</span>
}</div>
                    </div>

                    <div class="response-section">
                        <h4>Completed Job Result</h4>
                        <div class="code-block" style="font-size: 12px;">
{
  <span class="key">"status"</span>: <span class="string">"completed"</span>,
  <span class="key">"resultData"</span>: {
    <span class="key">"cog"</span>: {
      <span class="key">"cog_blob"</span>: <span class="string">"cogs/my_project/image_cog.tif"</span>,
      <span class="key">"size_mb"</span>: 127.58,
      <span class="key">"compression"</span>: <span class="string">"deflate"</span>
    },
    <span class="key">"stac"</span>: {
      <span class="key">"collection_id"</span>: <span class="string">"system-rasters"</span>,
      <span class="key">"inserted_to_pgstac"</span>: true
    },
    <span class="key">"share_url"</span>: <span class="string">"https://titiler.../map.html?url=..."</span>
  }
}</div>
                    </div>
                </div>
            </div>

            <!-- Job Status -->
            <div id="job-status" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge" style="background: #007bff; color: white;">GET</span>
                    <code class="endpoint-path">/api/jobs/status/{job_id}</code>
                    <h2>Job Status</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Check the status of a submitted job. Returns current status, stage progress, and result data when complete.
                    </p>

                    <div class="params-section">
                        <h3>Path Parameters</h3>
                        <table class="params-table">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Type</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><span class="param-name">job_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td>Job ID returned from submission</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Job Status Values</h3>
                        <table class="params-table">
                            <tbody>
                                <tr>
                                    <td><code>queued</code></td>
                                    <td>Job is waiting to be processed</td>
                                </tr>
                                <tr>
                                    <td><code>processing</code></td>
                                    <td>Job is currently being executed</td>
                                </tr>
                                <tr>
                                    <td><code>completed</code></td>
                                    <td>Job finished successfully</td>
                                </tr>
                                <tr>
                                    <td><code>failed</code></td>
                                    <td>Job encountered an error</td>
                                </tr>
                                <tr>
                                    <td><code>completed_with_errors</code></td>
                                    <td>Job finished but some tasks failed</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example</h3>
                        <div class="code-block">
curl ${API_BASE_URL}/api/jobs/status/a3f2c1b8e9d7...</div>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_js(self) -> str:
        """JavaScript for interactive examples."""
        return """
        function showExample(endpoint, type) {
            // Hide all examples for this endpoint
            document.querySelectorAll(`[id^="${endpoint}-"]`).forEach(el => {
                el.style.display = 'none';
            });

            // Show selected example
            document.getElementById(`${endpoint}-${type}`).style.display = 'block';

            // Update tab states
            const section = document.getElementById(endpoint === 'vector' ? 'process-vector' : 'process-raster');
            section.querySelectorAll('.example-tab').forEach(tab => {
                tab.classList.remove('active');
            });
            event.target.classList.add('active');
        }

        // Replace ${API_BASE_URL} placeholders in code blocks
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('.code-block').forEach(block => {
                block.innerHTML = block.innerHTML.replace(/\\${API_BASE_URL}/g, API_BASE_URL);
            });
        });
        """
