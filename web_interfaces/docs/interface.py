"""
API Documentation Interface.

Static rendering of API documentation for Platform endpoints used by DDH.
Platform is the Anti-Corruption Layer that translates DDH requests to CoreMachine jobs.

Note: Future enhancement could use OpenAPI/Swagger for dynamic docs.
See TODO.md "Dynamic OpenAPI Documentation Generation" for details.
"""

import azure.functions as func

from web_interfaces import InterfaceRegistry
from web_interfaces.base import BaseInterface


@InterfaceRegistry.register('docs')
class DocsInterface(BaseInterface):
    """
    API documentation interface for Platform (DDH) endpoints.

    Provides documentation for:
        - POST /api/platform/submit - Generic data submission
        - POST /api/platform/raster - Single raster file
        - POST /api/platform/raster-collection - Multiple raster files
        - GET /api/platform/status/{request_id} - Check request status
        - GET /api/platform/health - Platform health check
        - GET /api/platform/stats - Job statistics
        - GET /api/platform/failures - Recent failures
        - POST /api/jobs/submit/unpublish_vector - Remove vector data
        - POST /api/jobs/submit/unpublish_raster - Remove raster data
    """

    def render(self, request: func.HttpRequest) -> str:
        """Generate API documentation page."""
        return self.wrap_html(
            title="Platform API Documentation - DDH Integration",
            content=self._generate_html_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js()
        )

    def _generate_css(self) -> str:
        """Documentation-specific styles."""
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

            .info-box {
                background: #e7f3ff;
                border: 1px solid #b3d7ff;
                border-radius: 6px;
                padding: 16px 20px;
                margin-bottom: 24px;
                font-size: 14px;
                color: #0056b3;
            }

            .info-box strong {
                display: block;
                margin-bottom: 8px;
            }

            .endpoint-section {
                background: white;
                border-radius: 8px;
                margin-bottom: 24px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
                overflow: hidden;
            }

            .endpoint-header {
                background: var(--ds-bg);
                padding: 20px 24px;
                border-bottom: 1px solid var(--ds-gray-light);
                display: flex;
                align-items: center;
                gap: 16px;
                flex-wrap: wrap;
            }

            .endpoint-header h2 {
                margin: 0;
                font-size: 20px;
                color: var(--ds-navy);
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

            .method-badge.get {
                background: #007bff;
                color: white;
            }

            .endpoint-path {
                font-family: 'Monaco', 'Consolas', monospace;
                font-size: 14px;
                color: var(--ds-blue-primary);
                background: white;
                padding: 4px 8px;
                border-radius: 4px;
                border: 1px solid #ddd;
            }

            .endpoint-body {
                padding: 24px;
            }

            .endpoint-desc {
                color: var(--ds-gray);
                margin-bottom: 20px;
                line-height: 1.6;
            }

            .params-section {
                margin-bottom: 24px;
            }

            .params-section h3 {
                font-size: 16px;
                color: var(--ds-navy);
                margin: 0 0 12px 0;
                padding-bottom: 8px;
                border-bottom: 1px solid var(--ds-gray-light);
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
                color: var(--ds-navy);
            }

            .param-name {
                font-family: monospace;
                color: var(--ds-blue-primary);
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
                white-space: pre;
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
                flex-wrap: wrap;
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
                background: var(--ds-blue-primary);
                color: white;
                border-color: var(--ds-blue-primary);
            }

            .response-section {
                margin-top: 20px;
            }

            .response-section h4 {
                font-size: 14px;
                color: var(--ds-navy);
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
                color: var(--ds-navy);
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
                color: var(--ds-blue-primary);
                text-decoration: none;
            }

            .toc a:hover {
                text-decoration: underline;
            }

            .toc-section {
                margin-top: 12px;
                padding-top: 12px;
                border-top: 1px solid #eee;
            }

            .toc-section-title {
                font-weight: 600;
                color: var(--ds-navy);
                font-size: 13px;
                margin-bottom: 8px;
            }

            .access-level {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 12px;
                font-size: 11px;
                font-weight: 600;
            }

            .access-level.public { background: #d4edda; color: #155724; }
            .access-level.ouo { background: #fff3cd; color: #856404; }
            .access-level.restricted { background: #f8d7da; color: #721c24; }
        """

    def _generate_html_content(self) -> str:
        """Generate documentation content for Platform API."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Platform API Documentation</h1>
                <p class="subtitle">DDH Integration Endpoints for Geospatial Data Processing</p>
            </header>

            <div class="info-box">
                <strong>Anti-Corruption Layer (ACL)</strong>
                Platform translates DDH requests to CoreMachine jobs. DDH submits data using
                <code>dataset_id</code>, <code>resource_id</code>, and <code>version_id</code>.
                Platform generates deterministic <code>request_id</code> for idempotent operations
                and maps these to internal job/task workflows.
            </div>

            <!-- Table of Contents -->
            <div class="toc">
                <h3>Platform Endpoints</h3>
                <div class="toc-section-title">Submission</div>
                <ul>
                    <li><a href="#platform-submit">POST /api/platform/submit</a> - Generic data submission (auto-detect type)</li>
                    <li><a href="#platform-raster">POST /api/platform/raster</a> - Single raster file</li>
                    <li><a href="#platform-raster-collection">POST /api/platform/raster-collection</a> - Multiple raster files (MosaicJSON)</li>
                </ul>
                <div class="toc-section">
                    <div class="toc-section-title">Monitoring</div>
                    <ul>
                        <li><a href="#platform-status">GET /api/platform/status/{request_id}</a> - Check request status</li>
                        <li><a href="#platform-health">GET /api/platform/health</a> - Platform health check</li>
                        <li><a href="#platform-stats">GET /api/platform/stats</a> - Job statistics</li>
                        <li><a href="#platform-failures">GET /api/platform/failures</a> - Recent failures</li>
                    </ul>
                </div>
                <div class="toc-section">
                    <div class="toc-section-title">Unpublish / Delete</div>
                    <ul>
                        <li><a href="#unpublish-vector">POST /api/jobs/submit/unpublish_vector</a> - Remove vector data</li>
                        <li><a href="#unpublish-raster">POST /api/jobs/submit/unpublish_raster</a> - Remove raster data</li>
                    </ul>
                </div>
            </div>

            <!-- Platform Submit -->
            <div id="platform-submit" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/platform/submit</code>
                    <h2>Generic Submission</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Submit data for processing. Platform auto-detects data type (vector/raster)
                        based on file extension and routes to appropriate CoreMachine job.
                        Returns <code>request_id</code> for status polling.
                    </p>

                    <div class="params-section">
                        <h3>Request Parameters</h3>
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
                                    <td><span class="param-name">dataset_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>DDH dataset identifier (e.g., "aerial-imagery-2024")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">resource_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>DDH resource identifier (e.g., "site-alpha")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">version_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>DDH version identifier (e.g., "v1.0")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">container_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>Bronze tier container: bronze-vectors, bronze-rasters, bronze-misc</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">file_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>File path in container (e.g., "data/parcels.geojson")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">service_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Human-readable name for the dataset</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">description</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Dataset description for STAC metadata</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">access_level</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>
                                        <span class="access-level public">public</span>
                                        <span class="access-level ouo">OUO</span> (default)
                                        <span class="access-level restricted">restricted</span>
                                    </td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">data_type</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Explicit type: "vector" or "raster" (auto-detected if omitted)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">processing_options</span></td>
                                    <td><span class="param-type">object</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>See Processing Options below</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Processing Options</h3>
                        <table class="params-table">
                            <thead>
                                <tr>
                                    <th>Option</th>
                                    <th>Applies To</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><span class="param-name">lon_column</span></td>
                                    <td>Vector (CSV)</td>
                                    <td>Column name containing longitude values</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">lat_column</span></td>
                                    <td>Vector (CSV)</td>
                                    <td>Column name containing latitude values</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">wkt_column</span></td>
                                    <td>Vector (CSV)</td>
                                    <td>Column name containing WKT geometry</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">overwrite</span></td>
                                    <td>Vector</td>
                                    <td>Force overwrite existing table (default: false)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">crs</span></td>
                                    <td>Raster</td>
                                    <td>Target CRS (default: EPSG:4326)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">output_tier</span></td>
                                    <td>Raster</td>
                                    <td>analysis (DEFLATE), visualization (JPEG), archive (LZW)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">raster_type</span></td>
                                    <td>Raster</td>
                                    <td>auto, rgb, rgba, dem, categorical, multispectral</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="example-tabs">
                            <button class="example-tab active" onclick="showExample('submit', 'vector')">Vector</button>
                            <button class="example-tab" onclick="showExample('submit', 'raster')">Raster</button>
                            <button class="example-tab" onclick="showExample('submit', 'csv')">CSV with Coords</button>
                        </div>

                        <div id="submit-vector" class="code-block"><span class="comment"># Submit vector data (GeoJSON)</span>
curl -X POST \\
  ${API_BASE_URL}/api/platform/submit \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"dataset_id"</span>: <span class="string">"parcels-2024"</span>,
    <span class="key">"resource_id"</span>: <span class="string">"downtown-district"</span>,
    <span class="key">"version_id"</span>: <span class="string">"v1.0"</span>,
    <span class="key">"container_name"</span>: <span class="string">"bronze-vectors"</span>,
    <span class="key">"file_name"</span>: <span class="string">"parcels/downtown.geojson"</span>,
    <span class="key">"service_name"</span>: <span class="string">"Downtown Parcels 2024"</span>,
    <span class="key">"access_level"</span>: <span class="string">"OUO"</span>
  }'</div>

                        <div id="submit-raster" class="code-block" style="display: none;"><span class="comment"># Submit raster data (GeoTIFF)</span>
curl -X POST \\
  ${API_BASE_URL}/api/platform/submit \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"dataset_id"</span>: <span class="string">"aerial-imagery-2024"</span>,
    <span class="key">"resource_id"</span>: <span class="string">"site-alpha"</span>,
    <span class="key">"version_id"</span>: <span class="string">"v1.0"</span>,
    <span class="key">"container_name"</span>: <span class="string">"bronze-rasters"</span>,
    <span class="key">"file_name"</span>: <span class="string">"imagery/site_alpha.tif"</span>,
    <span class="key">"service_name"</span>: <span class="string">"Aerial Imagery Site Alpha"</span>,
    <span class="key">"access_level"</span>: <span class="string">"OUO"</span>,
    <span class="key">"processing_options"</span>: {
      <span class="key">"output_tier"</span>: <span class="string">"analysis"</span>
    }
  }'</div>

                        <div id="submit-csv" class="code-block" style="display: none;"><span class="comment"># Submit CSV with coordinate columns</span>
curl -X POST \\
  ${API_BASE_URL}/api/platform/submit \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"dataset_id"</span>: <span class="string">"facilities-2024"</span>,
    <span class="key">"resource_id"</span>: <span class="string">"health-centers"</span>,
    <span class="key">"version_id"</span>: <span class="string">"v1.0"</span>,
    <span class="key">"container_name"</span>: <span class="string">"bronze-vectors"</span>,
    <span class="key">"file_name"</span>: <span class="string">"health_centers.csv"</span>,
    <span class="key">"service_name"</span>: <span class="string">"Health Centers 2024"</span>,
    <span class="key">"data_type"</span>: <span class="string">"vector"</span>,
    <span class="key">"processing_options"</span>: {
      <span class="key">"lon_column"</span>: <span class="string">"longitude"</span>,
      <span class="key">"lat_column"</span>: <span class="string">"latitude"</span>
    }
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">202 Accepted</span>
                        <div class="code-block">{
  <span class="key">"success"</span>: true,
  <span class="key">"request_id"</span>: <span class="string">"a3f2c1b8e9d7f6a5..."</span>,
  <span class="key">"job_id"</span>: <span class="string">"abc123def456..."</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_vector"</span>,
  <span class="key">"message"</span>: <span class="string">"Platform request submitted. CoreMachine job created."</span>,
  <span class="key">"monitor_url"</span>: <span class="string">"/api/platform/status/a3f2c1b8e9d7f6a5..."</span>
}</div>
                    </div>
                </div>
            </div>

            <!-- Platform Raster -->
            <div id="platform-raster" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/platform/raster</code>
                    <h2>Single Raster</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Submit a single raster file for COG conversion and STAC cataloging.
                        Use this endpoint when submitting one raster file.
                        <code>file_name</code> must be a string (not a list).
                    </p>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="code-block"><span class="comment"># Single raster file</span>
curl -X POST \\
  ${API_BASE_URL}/api/platform/raster \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"dataset_id"</span>: <span class="string">"elevation-data"</span>,
    <span class="key">"resource_id"</span>: <span class="string">"region-west"</span>,
    <span class="key">"version_id"</span>: <span class="string">"v2.0"</span>,
    <span class="key">"container_name"</span>: <span class="string">"bronze-rasters"</span>,
    <span class="key">"file_name"</span>: <span class="string">"dem/region_west_dem.tif"</span>,
    <span class="key">"service_name"</span>: <span class="string">"Region West DEM"</span>,
    <span class="key">"access_level"</span>: <span class="string">"public"</span>
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">202 Accepted</span>
                        <div class="code-block">{
  <span class="key">"success"</span>: true,
  <span class="key">"request_id"</span>: <span class="string">"b4e5d6c7..."</span>,
  <span class="key">"job_id"</span>: <span class="string">"xyz789..."</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_raster_v2"</span>,
  <span class="key">"message"</span>: <span class="string">"Single raster request submitted."</span>,
  <span class="key">"monitor_url"</span>: <span class="string">"/api/platform/status/b4e5d6c7..."</span>
}</div>
                    </div>
                </div>
            </div>

            <!-- Platform Raster Collection -->
            <div id="platform-raster-collection" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/platform/raster-collection</code>
                    <h2>Raster Collection (MosaicJSON)</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Submit multiple raster files as a collection. Creates MosaicJSON for
                        seamless tiled access. <code>file_name</code> must be a list with at least 2 files.
                    </p>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="code-block"><span class="comment"># Multiple raster files (tiles)</span>
curl -X POST \\
  ${API_BASE_URL}/api/platform/raster-collection \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"dataset_id"</span>: <span class="string">"satellite-tiles-2024"</span>,
    <span class="key">"resource_id"</span>: <span class="string">"coverage-area"</span>,
    <span class="key">"version_id"</span>: <span class="string">"v1.0"</span>,
    <span class="key">"container_name"</span>: <span class="string">"bronze-rasters"</span>,
    <span class="key">"file_name"</span>: [
      <span class="string">"tiles/tile_001.tif"</span>,
      <span class="string">"tiles/tile_002.tif"</span>,
      <span class="string">"tiles/tile_003.tif"</span>,
      <span class="string">"tiles/tile_004.tif"</span>
    ],
    <span class="key">"service_name"</span>: <span class="string">"Satellite Coverage 2024"</span>,
    <span class="key">"access_level"</span>: <span class="string">"OUO"</span>
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">202 Accepted</span>
                        <div class="code-block">{
  <span class="key">"success"</span>: true,
  <span class="key">"request_id"</span>: <span class="string">"c5f6e7d8..."</span>,
  <span class="key">"job_id"</span>: <span class="string">"mno456..."</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_raster_collection_v2"</span>,
  <span class="key">"file_count"</span>: 4,
  <span class="key">"message"</span>: <span class="string">"Raster collection request submitted (4 files)."</span>,
  <span class="key">"monitor_url"</span>: <span class="string">"/api/platform/status/c5f6e7d8..."</span>
}</div>
                    </div>
                </div>
            </div>

            <!-- Platform Status -->
            <div id="platform-status" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge get">GET</span>
                    <code class="endpoint-path">/api/platform/status/{request_id}</code>
                    <h2>Request Status</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Check the status of a Platform request. Returns DDH identifiers,
                        delegated CoreMachine job status, task summary, and data access URLs when complete.
                    </p>

                    <div class="params-section">
                        <h3>Query Parameters</h3>
                        <table class="params-table">
                            <tbody>
                                <tr>
                                    <td><span class="param-name">verbose</span></td>
                                    <td><span class="param-type">boolean</span></td>
                                    <td>Include full task details (default: false)</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example</h3>
                        <div class="code-block">curl ${API_BASE_URL}/api/platform/status/a3f2c1b8e9d7f6a5...</div>
                    </div>

                    <div class="response-section">
                        <h4>Response (Completed)</h4>
                        <span class="status-badge success">200 OK</span>
                        <div class="code-block">{
  <span class="key">"success"</span>: true,
  <span class="key">"request_id"</span>: <span class="string">"a3f2c1b8e9d7f6a5..."</span>,
  <span class="key">"dataset_id"</span>: <span class="string">"parcels-2024"</span>,
  <span class="key">"resource_id"</span>: <span class="string">"downtown-district"</span>,
  <span class="key">"version_id"</span>: <span class="string">"v1.0"</span>,
  <span class="key">"data_type"</span>: <span class="string">"vector"</span>,
  <span class="key">"job_id"</span>: <span class="string">"abc123..."</span>,
  <span class="key">"job_type"</span>: <span class="string">"process_vector"</span>,
  <span class="key">"job_status"</span>: <span class="string">"completed"</span>,
  <span class="key">"job_stage"</span>: 3,
  <span class="key">"task_summary"</span>: {
    <span class="key">"total"</span>: 5,
    <span class="key">"completed"</span>: 5,
    <span class="key">"failed"</span>: 0
  },
  <span class="key">"data_access"</span>: {
    <span class="key">"ogc_features"</span>: {
      <span class="key">"collection"</span>: <span class="string">"/api/features/collections/parcels_2024_downtown_district_v1_0"</span>,
      <span class="key">"items"</span>: <span class="string">"/api/features/collections/parcels_2024_downtown_district_v1_0/items"</span>
    }
  }
}</div>
                    </div>
                </div>
            </div>

            <!-- Platform Health -->
            <div id="platform-health" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge get">GET</span>
                    <code class="endpoint-path">/api/platform/health</code>
                    <h2>Platform Health</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Simplified health endpoint for DDH consumption. Returns high-level
                        system health without internal implementation details.
                    </p>

                    <div class="params-section">
                        <h3>Example</h3>
                        <div class="code-block">curl ${API_BASE_URL}/api/platform/health</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">200 OK</span>
                        <div class="code-block">{
  <span class="key">"status"</span>: <span class="string">"healthy"</span>,
  <span class="key">"api_version"</span>: <span class="string">"v1.0"</span>,
  <span class="key">"components"</span>: {
    <span class="key">"job_processing"</span>: <span class="string">"healthy"</span>,
    <span class="key">"stac_catalog"</span>: <span class="string">"healthy"</span>,
    <span class="key">"storage"</span>: <span class="string">"healthy"</span>
  },
  <span class="key">"recent_activity"</span>: {
    <span class="key">"jobs_last_24h"</span>: 45,
    <span class="key">"success_rate"</span>: <span class="string">"93.3%"</span>
  }
}</div>
                    </div>
                </div>
            </div>

            <!-- Platform Stats -->
            <div id="platform-stats" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge get">GET</span>
                    <code class="endpoint-path">/api/platform/stats</code>
                    <h2>Job Statistics</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Aggregated job statistics for DDH visibility.
                    </p>

                    <div class="params-section">
                        <h3>Query Parameters</h3>
                        <table class="params-table">
                            <tbody>
                                <tr>
                                    <td><span class="param-name">hours</span></td>
                                    <td><span class="param-type">integer</span></td>
                                    <td>Time period in hours (default: 24)</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example</h3>
                        <div class="code-block">curl "${API_BASE_URL}/api/platform/stats?hours=48"</div>
                    </div>
                </div>
            </div>

            <!-- Platform Failures -->
            <div id="platform-failures" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge get">GET</span>
                    <code class="endpoint-path">/api/platform/failures</code>
                    <h2>Recent Failures</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Recent failures for DDH troubleshooting. Returns sanitized error
                        information (no internal paths or stack traces).
                    </p>

                    <div class="params-section">
                        <h3>Query Parameters</h3>
                        <table class="params-table">
                            <tbody>
                                <tr>
                                    <td><span class="param-name">hours</span></td>
                                    <td><span class="param-type">integer</span></td>
                                    <td>Time period in hours (default: 24)</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">limit</span></td>
                                    <td><span class="param-type">integer</span></td>
                                    <td>Max results (default: 10)</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example</h3>
                        <div class="code-block">curl "${API_BASE_URL}/api/platform/failures?hours=24&limit=5"</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <div class="code-block">{
  <span class="key">"failures"</span>: [
    {
      <span class="key">"request_id"</span>: <span class="string">"def456..."</span>,
      <span class="key">"dataset_id"</span>: <span class="string">"parcels-2024"</span>,
      <span class="key">"failed_at"</span>: <span class="string">"2025-12-07T09:15:00Z"</span>,
      <span class="key">"error_category"</span>: <span class="string">"resource_not_found"</span>,
      <span class="key">"error_summary"</span>: <span class="string">"Source file not found in bronze-vectors container"</span>,
      <span class="key">"can_retry"</span>: true
    }
  ],
  <span class="key">"total_failures"</span>: 3
}</div>
                    </div>
                </div>
            </div>

            <!-- Unpublish Vector -->
            <div id="unpublish-vector" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/jobs/submit/unpublish_vector</code>
                    <h2>Unpublish Vector Data</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Remove a vector dataset from the platform. Drops the PostGIS table,
                        deletes metadata from <code>geo.table_metadata</code>, and optionally removes
                        the associated STAC item. Supports dry run mode for safe previewing.
                    </p>

                    <div class="params-section">
                        <h3>Request Parameters</h3>
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
                                    <td><span class="param-name">table_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>PostGIS table name to remove (e.g., "city_parcels_v1_0")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">schema_name</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>PostgreSQL schema (default: "geo")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">dry_run</span></td>
                                    <td><span class="param-type">boolean</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Preview mode - shows what would be deleted without executing (default: true)</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Workflow Stages</h3>
                        <table class="params-table">
                            <thead>
                                <tr>
                                    <th>Stage</th>
                                    <th>Task</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>1</td>
                                    <td><code>inventory_vector</code></td>
                                    <td>Query geo.table_metadata for ETL/STAC linkage</td>
                                </tr>
                                <tr>
                                    <td>2</td>
                                    <td><code>drop_vector_table</code></td>
                                    <td>DROP PostGIS table + DELETE metadata row</td>
                                </tr>
                                <tr>
                                    <td>3</td>
                                    <td><code>cleanup_vector</code></td>
                                    <td>Delete STAC item if linked + create audit record</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="example-tabs">
                            <button class="example-tab active" onclick="showExample('unpublish-vector', 'preview')">Preview (Dry Run)</button>
                            <button class="example-tab" onclick="showExample('unpublish-vector', 'execute')">Execute Delete</button>
                        </div>

                        <div id="unpublish-vector-preview" class="code-block"><span class="comment"># Preview what will be deleted (safe - dry_run=true)</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/unpublish_vector \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"table_name"</span>: <span class="string">"city_parcels_v1_0"</span>,
    <span class="key">"dry_run"</span>: true
  }'</div>

                        <div id="unpublish-vector-execute" class="code-block" style="display: none;"><span class="comment"># Actually delete (set dry_run=false)</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/unpublish_vector \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"table_name"</span>: <span class="string">"city_parcels_v1_0"</span>,
    <span class="key">"dry_run"</span>: false
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">202 Accepted</span>
                        <div class="code-block">{
  <span class="key">"success"</span>: true,
  <span class="key">"job_id"</span>: <span class="string">"abc123..."</span>,
  <span class="key">"job_type"</span>: <span class="string">"unpublish_vector"</span>,
  <span class="key">"message"</span>: <span class="string">"Vector unpublish job submitted (dry_run=true)"</span>,
  <span class="key">"monitor_url"</span>: <span class="string">"/api/jobs/status/abc123..."</span>
}</div>
                    </div>

                    <div class="response-section">
                        <h4>Job Result (when completed)</h4>
                        <div class="code-block">{
  <span class="key">"job_result"</span>: {
    <span class="key">"table_dropped"</span>: <span class="string">"geo.city_parcels_v1_0"</span>,
    <span class="key">"metadata_deleted"</span>: true,
    <span class="key">"stac_item_deleted"</span>: <span class="string">"city-parcels-v1-0"</span>,
    <span class="key">"audit_record_id"</span>: <span class="string">"unpublish_abc123"</span>
  }
}</div>
                    </div>
                </div>
            </div>

            <!-- Unpublish Raster -->
            <div id="unpublish-raster" class="endpoint-section">
                <div class="endpoint-header">
                    <span class="method-badge post">POST</span>
                    <code class="endpoint-path">/api/jobs/submit/unpublish_raster</code>
                    <h2>Unpublish Raster Data</h2>
                </div>
                <div class="endpoint-body">
                    <p class="endpoint-desc">
                        Remove a raster dataset from the platform. Deletes the STAC item and
                        associated COG/MosaicJSON blobs from Azure storage. Supports dry run mode
                        for safe previewing.
                    </p>

                    <div class="params-section">
                        <h3>Request Parameters</h3>
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
                                    <td><span class="param-name">stac_item_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>STAC item ID to remove (e.g., "aerial-imagery-2024-site-alpha-v1.0")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">collection_id</span></td>
                                    <td><span class="param-type">string</span></td>
                                    <td><span class="param-required">Required</span></td>
                                    <td>STAC collection containing the item (e.g., "aerial-imagery-2024")</td>
                                </tr>
                                <tr>
                                    <td><span class="param-name">dry_run</span></td>
                                    <td><span class="param-type">boolean</span></td>
                                    <td><span class="param-optional">Optional</span></td>
                                    <td>Preview mode - shows what would be deleted without executing (default: true)</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Workflow Stages</h3>
                        <table class="params-table">
                            <thead>
                                <tr>
                                    <th>Stage</th>
                                    <th>Task</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td>1</td>
                                    <td><code>inventory_raster</code></td>
                                    <td>Query STAC item, extract asset hrefs for deletion</td>
                                </tr>
                                <tr>
                                    <td>2</td>
                                    <td><code>delete_raster_blobs</code></td>
                                    <td>Fan-out deletion of COG/MosaicJSON blobs</td>
                                </tr>
                                <tr>
                                    <td>3</td>
                                    <td><code>cleanup_raster</code></td>
                                    <td>Delete STAC item + create audit record</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>

                    <div class="params-section">
                        <h3>Example Request</h3>
                        <div class="example-tabs">
                            <button class="example-tab active" onclick="showExample('unpublish-raster', 'preview')">Preview (Dry Run)</button>
                            <button class="example-tab" onclick="showExample('unpublish-raster', 'execute')">Execute Delete</button>
                        </div>

                        <div id="unpublish-raster-preview" class="code-block"><span class="comment"># Preview what will be deleted (safe - dry_run=true)</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/unpublish_raster \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"stac_item_id"</span>: <span class="string">"aerial-imagery-2024-site-alpha-v1.0"</span>,
    <span class="key">"collection_id"</span>: <span class="string">"aerial-imagery-2024"</span>,
    <span class="key">"dry_run"</span>: true
  }'</div>

                        <div id="unpublish-raster-execute" class="code-block" style="display: none;"><span class="comment"># Actually delete (set dry_run=false)</span>
curl -X POST \\
  ${API_BASE_URL}/api/jobs/submit/unpublish_raster \\
  -H 'Content-Type: application/json' \\
  -d '{
    <span class="key">"stac_item_id"</span>: <span class="string">"aerial-imagery-2024-site-alpha-v1.0"</span>,
    <span class="key">"collection_id"</span>: <span class="string">"aerial-imagery-2024"</span>,
    <span class="key">"dry_run"</span>: false
  }'</div>
                    </div>

                    <div class="response-section">
                        <h4>Response</h4>
                        <span class="status-badge success">202 Accepted</span>
                        <div class="code-block">{
  <span class="key">"success"</span>: true,
  <span class="key">"job_id"</span>: <span class="string">"def456..."</span>,
  <span class="key">"job_type"</span>: <span class="string">"unpublish_raster"</span>,
  <span class="key">"message"</span>: <span class="string">"Raster unpublish job submitted (dry_run=true)"</span>,
  <span class="key">"monitor_url"</span>: <span class="string">"/api/jobs/status/def456..."</span>
}</div>
                    </div>

                    <div class="response-section">
                        <h4>Job Result (when completed)</h4>
                        <div class="code-block">{
  <span class="key">"job_result"</span>: {
    <span class="key">"stac_item_deleted"</span>: <span class="string">"aerial-imagery-2024-site-alpha-v1.0"</span>,
    <span class="key">"blobs_deleted"</span>: [
      <span class="string">"silver-cogs/aerial-imagery-2024/site-alpha/v1.0/site-alpha_cog_analysis.tif"</span>
    ],
    <span class="key">"collection_cleanup"</span>: false,
    <span class="key">"audit_record_id"</span>: <span class="string">"unpublish_def456"</span>
  }
}</div>
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
            const section = document.getElementById('platform-' + endpoint);
            if (section) {
                section.querySelectorAll('.example-tab').forEach(tab => {
                    tab.classList.remove('active');
                });
            }
            event.target.classList.add('active');
        }

        // Replace ${API_BASE_URL} placeholders in code blocks
        document.addEventListener('DOMContentLoaded', function() {
            document.querySelectorAll('.code-block').forEach(block => {
                block.innerHTML = block.innerHTML.replace(/\\${API_BASE_URL}/g, API_BASE_URL);
            });
        });
        """
