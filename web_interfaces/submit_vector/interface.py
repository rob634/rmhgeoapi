"""
Submit Vector Job interface module.

Web interface for submitting ProcessVectorJob with file browser and form.

Features (23 DEC 2025 - S12.2.3):
    - HTMX-powered file browser (reuses Storage patterns)
    - Auto-filter for vector extensions (.csv, .geojson, .json, .gpkg, .kml, .kmz, .shp, .zip)
    - Form for ProcessVectorJob parameters
    - HTMX job submission with result display
    - CSV-specific fields (lat/lon or WKT)

Exports:
    SubmitVectorInterface: Job submission interface for vector ETL
"""

import logging
from datetime import datetime
from typing import List, Dict, Any
import json

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)

# Valid storage zones
VALID_ZONES = ["bronze"]

# Valid vector file extensions
VECTOR_EXTENSIONS = ['.csv', '.geojson', '.json', '.gpkg', '.kml', '.kmz', '.shp', '.zip']


@InterfaceRegistry.register('submit-vector')
class SubmitVectorInterface(BaseInterface):
    """
    Submit Vector Job interface with HTMX interactivity.

    Combines file browser (from Storage pattern) with ProcessVectorJob
    submission form. Demonstrates HTMX form submission pattern.

    Fragments supported:
        - containers: Returns container <option> elements for zone
        - files: Returns file table rows (filtered for vector extensions)
        - submit: Handles job submission and returns result
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Submit Vector Job HTML with HTMX attributes.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Submit Vector Job",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """
        Handle HTMX partial requests for submit-vector fragments.

        Fragments:
            containers: Returns <option> elements for container dropdown
            files: Returns table rows for file listing (vector files only)
            submit: Handles job submission and returns result

        Args:
            request: Azure Functions HttpRequest
            fragment: Fragment name to render

        Returns:
            HTML fragment string
        """
        if fragment == 'containers':
            return self._render_containers_fragment(request)
        elif fragment == 'files':
            return self._render_files_fragment(request)
        elif fragment == 'submit':
            return self._render_submit_fragment(request)
        else:
            raise ValueError(f"Unknown fragment: {fragment}")

    def _render_containers_fragment(self, request: func.HttpRequest) -> str:
        """Render container options for a given zone."""
        zone = request.params.get('zone', '')

        if not zone:
            return '<option value="">Select zone first</option>'

        if zone not in VALID_ZONES:
            return f'<option value="">Invalid zone: {zone}</option>'

        try:
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            containers = repo.list_containers()

            if not containers:
                return '<option value="">No containers in zone</option>'

            # Return container options
            options = [f'<option value="{c["name"]}">{c["name"]}</option>' for c in containers]
            return '\n'.join(options)

        except Exception as e:
            logger.error(f"Error loading containers for zone {zone}: {e}")
            return f'<option value="">Error loading containers</option>'

    def _render_files_fragment(self, request: func.HttpRequest) -> str:
        """Render file table rows (filtered for vector extensions)."""
        zone = request.params.get('zone', '')
        container = request.params.get('container', '')
        prefix = request.params.get('prefix', '')
        limit = int(request.params.get('limit', '250'))

        if not zone or not container:
            return self._render_files_error("Please select a zone and container first")

        try:
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            blobs = repo.list_blobs(
                container=container,
                prefix=prefix if prefix else "",
                limit=limit * 2  # Fetch more since we'll filter
            )

            # Filter for vector extensions
            vector_blobs = []
            for blob in blobs:
                name = blob.get('name', '').lower()
                if any(name.endswith(ext) for ext in VECTOR_EXTENSIONS):
                    vector_blobs.append(blob)
                if len(vector_blobs) >= limit:
                    break

            if not vector_blobs:
                return self._render_files_empty()

            # Build table rows
            rows = []
            for i, blob in enumerate(vector_blobs):
                size_mb = blob.get('size', 0) / (1024 * 1024)
                last_modified = blob.get('last_modified', '')
                if last_modified:
                    try:
                        from zoneinfo import ZoneInfo
                        eastern = ZoneInfo('America/New_York')
                        dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                        dt_eastern = dt.astimezone(eastern)
                        date_str = dt_eastern.strftime('%m/%d/%Y')
                    except Exception:
                        date_str = 'N/A'
                else:
                    date_str = 'N/A'

                name = blob.get('name', '')
                short_name = name.split('/')[-1] if '/' in name else name

                # Get extension
                ext = short_name.split('.')[-1].upper() if '.' in short_name else 'File'

                row = f'''
                <tr class="file-row"
                    onclick="selectFile('{name}', '{container}', '{zone}')"
                    data-blob="{name}"
                    data-container="{container}"
                    data-zone="{zone}">
                    <td>
                        <div class="file-name" title="{name}">{short_name}</div>
                    </td>
                    <td>
                        <span class="file-size">{size_mb:.2f} MB</span>
                    </td>
                    <td>
                        <span class="file-date">{date_str}</span>
                    </td>
                    <td>
                        <span class="file-type">{ext}</span>
                    </td>
                </tr>'''
                rows.append(row)

            # Return just the table rows (no OOB swap for now - simplify debugging)
            return '\n'.join(rows)

        except Exception as e:
            logger.error(f"Error loading files: {e}", exc_info=True)
            return self._render_files_error(str(e))

    def _render_files_empty(self) -> str:
        """Render empty state for files table."""
        return '''
        <tr>
            <td colspan="4">
                <div class="empty-state" style="margin: 0; box-shadow: none;">
                    <div class="icon" style="font-size: 48px;">📁</div>
                    <h3>No Vector Files Found</h3>
                    <p>No files with supported vector extensions (.csv, .geojson, .gpkg, etc.)</p>
                </div>
            </td>
        </tr>
        '''

    def _render_files_error(self, message: str) -> str:
        """Render error state for files table."""
        return f'''
        <tr>
            <td colspan="4">
                <div class="error-state" style="margin: 0; box-shadow: none;">
                    <div class="icon" style="font-size: 48px;">⚠️</div>
                    <h3>Error Loading Files</h3>
                    <p>{message}</p>
                </div>
            </td>
        </tr>
        '''

    def _render_submit_fragment(self, request: func.HttpRequest) -> str:
        """Handle job submission via Platform API and return result HTML."""
        try:
            # Get form data
            body = request.get_body().decode('utf-8')
            # Parse form-encoded data
            from urllib.parse import parse_qs
            form_data = parse_qs(body)

            # Extract parameters (parse_qs returns lists)
            def get_param(key, default=None):
                values = form_data.get(key, [])
                return values[0] if values else default

            # DDH Identifiers (required)
            dataset_id = get_param('dataset_id')
            resource_id = get_param('resource_id')
            version_id = get_param('version_id')

            # File info
            blob_name = get_param('blob_name')
            container_name = get_param('container_name')
            file_extension = get_param('file_extension')

            # Optional metadata
            title = get_param('title') or get_param('service_name')  # Support legacy field name

            # Validate required fields
            if not dataset_id:
                return self._render_submit_error("Missing dataset_id. Please enter a DDH dataset identifier.")
            if not resource_id:
                return self._render_submit_error("Missing resource_id. Please enter a DDH resource identifier.")
            # Default version_id if not provided
            if not version_id:
                version_id = "v1.0"
            if not blob_name:
                return self._render_submit_error("Missing blob_name. Please select a file.")

            # Build Platform API payload
            platform_payload = {
                'dataset_id': dataset_id,
                'resource_id': resource_id,
                'version_id': version_id,
                'data_type': 'vector',
                'operation': 'CREATE',
                'container_name': container_name,
                'file_name': blob_name
            }

            # Optional metadata
            description = get_param('description')
            access_level = get_param('access_level')
            tags = get_param('tags')

            # title is optional - will be auto-generated from DDH IDs if not provided
            if title:
                platform_payload['title'] = title
            if description:
                platform_payload['description'] = description
            if access_level:
                platform_payload['access_level'] = access_level
            if tags:
                platform_payload['tags'] = [t.strip() for t in tags.split(',') if t.strip()]

            # Processing options
            processing_options = {}

            overwrite = get_param('overwrite')
            if overwrite == 'true':
                processing_options['overwrite'] = True

            # CSV-specific parameters
            lat_name = get_param('lat_name')
            lon_name = get_param('lon_name')
            wkt_column = get_param('wkt_column')

            if lat_name:
                processing_options['lat_column'] = lat_name
            if lon_name:
                processing_options['lon_column'] = lon_name
            if wkt_column:
                processing_options['wkt_column'] = wkt_column

            if processing_options:
                platform_payload['processing_options'] = processing_options

            # Submit via Platform API internal functions
            from config import get_config, generate_platform_request_id
            from infrastructure import PlatformRepository
            from core.models import ApiRequest, PlatformRequest
            from services.platform_translation import translate_to_coremachine
            from services.platform_job_submit import create_and_submit_job
            config = get_config()

            # Create Platform request object
            platform_req = PlatformRequest(**platform_payload)

            # Generate deterministic request ID
            request_id = generate_platform_request_id(
                platform_req.dataset_id,
                platform_req.resource_id,
                platform_req.version_id
            )

            # Check for existing request (idempotent)
            platform_repo = PlatformRepository()
            existing = platform_repo.get_request(request_id)
            if existing:
                return self._render_submit_success_platform({
                    'request_id': request_id,
                    'job_id': existing.job_id,
                    'status': 'exists'
                }, platform_payload)

            # Translate to CoreMachine job parameters
            job_type, job_params = translate_to_coremachine(platform_req, config)

            # Create and submit job
            job_id = create_and_submit_job(job_type, job_params, request_id)

            if not job_id:
                return self._render_submit_error("Failed to create CoreMachine job")

            # Store tracking record
            api_request = ApiRequest(
                request_id=request_id,
                dataset_id=platform_req.dataset_id,
                resource_id=platform_req.resource_id,
                version_id=platform_req.version_id,
                job_id=job_id,
                data_type=platform_req.data_type.value
            )
            platform_repo.create_request(api_request)

            return self._render_submit_success_platform({
                'request_id': request_id,
                'job_id': job_id,
                'job_type': job_type,
                'status': 'accepted'
            }, platform_payload)

        except Exception as e:
            logger.error(f"Error submitting job: {e}", exc_info=True)
            return self._render_submit_error(str(e))

    def _render_submit_success_platform(self, result: dict, payload: dict) -> str:
        """Render successful Platform API submission result."""
        request_id = result.get('request_id', 'N/A')
        job_id = result.get('job_id', 'N/A')
        table_name = result.get('table_name', 'Auto-generated')
        status = result.get('status', 'accepted')

        # Determine message based on status
        if status == 'exists':
            title = "Request Already Processed (Idempotent)"
        elif status == 'accepted':
            title = "Request Submitted Successfully"
        else:
            title = "Request Processed"

        return f'''
        <div class="submit-result success">
            <div class="result-icon">✅</div>
            <h3>{title}</h3>
            <div class="result-details">
                <div class="detail-row">
                    <span class="detail-label">Request ID</span>
                    <span class="detail-value mono">{request_id}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Job ID</span>
                    <span class="detail-value mono">{job_id}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Table Name</span>
                    <span class="detail-value">{table_name}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">DDH Identifier</span>
                    <span class="detail-value">{payload.get('dataset_id')}/{payload.get('resource_id')}/{payload.get('version_id')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Source File</span>
                    <span class="detail-value">{payload.get('file_name', 'N/A')}</span>
                </div>
            </div>
            <div class="result-actions">
                <a href="/api/interface/tasks?job_id={job_id}" class="btn btn-primary">Workflow Monitor</a>
            </div>
        </div>
        '''

    def _render_submit_success(self, job_id: str, params: dict, message: str = None) -> str:
        """Render successful job submission result (legacy)."""
        title = message if message else "Job Submitted Successfully"
        return f'''
        <div class="submit-result success">
            <div class="result-icon">✅</div>
            <h3>{title}</h3>
            <div class="result-details">
                <div class="detail-row">
                    <span class="detail-label">Job ID</span>
                    <span class="detail-value mono">{job_id}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Table Name</span>
                    <span class="detail-value">{params.get('table_name', 'N/A')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Source File</span>
                    <span class="detail-value">{params.get('blob_name', 'N/A')}</span>
                </div>
            </div>
            <div class="result-actions">
                <a href="/api/interface/tasks?job_id={job_id}" class="btn btn-primary">Workflow Monitor</a>
            </div>
        </div>
        '''

    def _render_submit_error(self, message: str) -> str:
        """Render job submission error."""
        return f'''
        <div class="submit-result error">
            <div class="result-icon">❌</div>
            <h3>Submission Failed</h3>
            <p class="error-message">{message}</p>
            <button onclick="document.getElementById('submit-result').innerHTML = ''; document.getElementById('submit-result').classList.add('hidden');"
                    class="btn btn-secondary">
                Dismiss
            </button>
        </div>
        '''

    def _generate_html_content(self) -> str:
        """Generate HTML content structure with HTMX attributes."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <h1>📤 Submit Vector Job</h1>
                <p class="subtitle">Upload vector data via Platform API - generate cURL or submit directly</p>
            </header>

            <div class="two-column-layout">
                <!-- Left Column: File Browser -->
                <div class="browser-section">
                    <div class="section-header">
                        <h2>1. Select Source File</h2>
                        <p class="section-subtitle">Browse and select a vector file</p>
                    </div>

                    <!-- Controls - Two rows -->
                    <div class="controls-grid">
                        <div class="controls-row">
                            <div class="control-group">
                                <label>Zone:</label>
                                <div class="zone-badge-bronze">BRONZE (Source Data)</div>
                                <input type="hidden" id="zone-select" name="zone" value="bronze">
                            </div>

                            <div class="control-group">
                                <label for="container-select">Container:</label>
                                <select id="container-select" name="container" class="filter-select"
                                        hx-get="/api/interface/submit-vector?fragment=containers&zone=bronze"
                                        hx-trigger="load"
                                        hx-target="this"
                                        hx-swap="innerHTML"
                                        hx-indicator="#container-spinner"
                                        onchange="updateLoadButton()">
                                    <option value="">Loading containers...</option>
                                </select>
                                <span id="container-spinner" class="htmx-indicator spinner-sm"></span>
                            </div>
                        </div>

                        <div class="controls-row">
                            <div class="control-group filter-group">
                                <label for="prefix-input">Path Filter:</label>
                                <input type="text" id="prefix-input" name="prefix" class="filter-input"
                                       placeholder="e.g., uploads/">
                            </div>

                            <button id="load-btn" class="refresh-button" disabled
                                    hx-get="/api/interface/submit-vector?fragment=files"
                                    hx-target="#files-tbody"
                                    hx-trigger="click"
                                    hx-indicator="#loading-spinner"
                                    hx-include="#zone-select, #container-select, #prefix-input"
                                    onclick="showFilesTable()">
                                🔄 Load Files
                            </button>
                        </div>
                    </div>

                    <!-- Stats Banner -->
                    <div id="stats-banner" class="stats-banner hidden">
                        <div id="stats-content">
                            <div class="stat-item">
                                <span class="stat-label">Vector Files</span>
                                <span class="stat-value">0</span>
                            </div>
                        </div>
                    </div>

                    <!-- Files Table -->
                    <div class="files-section">
                        <div id="loading-spinner" class="htmx-indicator spinner"></div>

                        <table class="files-table hidden" id="files-table">
                            <thead>
                                <tr>
                                    <th>Name</th>
                                    <th>Size</th>
                                    <th>Modified</th>
                                    <th>Type</th>
                                </tr>
                            </thead>
                            <tbody id="files-tbody">
                                <!-- Files will be inserted here via HTMX -->
                            </tbody>
                        </table>

                        <!-- Initial State -->
                        <div id="initial-state" class="empty-state">
                            <div class="icon">📁</div>
                            <h3>Select a Container</h3>
                            <p>Choose a container from the Bronze zone to browse vector files</p>
                            <p class="supported-formats">Supported: .csv, .geojson, .json, .gpkg, .kml, .kmz, .shp, .zip</p>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Job Form -->
                <div class="form-section">
                    <div class="section-header">
                        <h2>2. Configure Platform API Request</h2>
                        <p class="section-subtitle">Set DDH identifiers and processing options</p>
                    </div>

                    <form id="submit-form"
                          hx-post="/api/interface/submit-vector?fragment=submit"
                          hx-target="#submit-result"
                          hx-indicator="#submit-spinner">

                        <!-- Hidden fields populated by file selection -->
                        <input type="hidden" id="blob_name" name="blob_name" value="">
                        <input type="hidden" id="container_name" name="container_name" value="">
                        <input type="hidden" id="file_extension" name="file_extension" value="">

                        <!-- Selected File Display -->
                        <div class="form-group">
                            <label>Selected File</label>
                            <div id="selected-file" class="selected-file-display">
                                <span class="placeholder">No file selected - click a file in the browser</span>
                            </div>
                        </div>

                        <!-- DDH Identifiers Section -->
                        <div class="ddh-section">
                            <div class="form-group-header">DDH Identifiers (Required)</div>
                            <div class="form-group required">
                                <label for="dataset_id">Dataset ID *</label>
                                <input type="text" id="dataset_id" name="dataset_id" required
                                       placeholder="e.g., parcels-2024"
                                       pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
                                       title="Lowercase letters, numbers, hyphens. No leading/trailing hyphens.">
                                <span class="field-hint">DDH dataset identifier (lowercase, hyphens allowed)</span>
                            </div>

                            <div class="form-row">
                                <div class="form-group required">
                                    <label for="resource_id">Resource ID *</label>
                                    <input type="text" id="resource_id" name="resource_id" required
                                           placeholder="e.g., county-king"
                                           pattern="[a-z0-9][a-z0-9-]*[a-z0-9]"
                                           title="Lowercase letters, numbers, hyphens.">
                                    <span class="field-hint">DDH resource identifier</span>
                                </div>
                                <div class="form-group">
                                    <label for="version_id">Version ID</label>
                                    <input type="text" id="version_id" name="version_id"
                                           value="v1.0"
                                           placeholder="e.g., v1.0">
                                    <span class="field-hint">Version identifier (any string, defaults to v1.0)</span>
                                </div>
                            </div>
                        </div>

                        <!-- CSV-specific fields (shown conditionally) -->
                        <div id="csv-fields" class="csv-fields hidden">
                            <div class="form-group-header">CSV Geometry Configuration</div>

                            <div class="form-row">
                                <div class="form-group">
                                    <label for="lat_name">Latitude Column</label>
                                    <input type="text" id="lat_name" name="lat_name"
                                           placeholder="e.g., lat, latitude, y">
                                </div>
                                <div class="form-group">
                                    <label for="lon_name">Longitude Column</label>
                                    <input type="text" id="lon_name" name="lon_name"
                                           placeholder="e.g., lon, longitude, x">
                                </div>
                            </div>

                            <div class="form-group-or">OR</div>

                            <div class="form-group">
                                <label for="wkt_column">WKT Column</label>
                                <input type="text" id="wkt_column" name="wkt_column"
                                       placeholder="e.g., geometry, geom, wkt">
                                <span class="field-hint">Column containing WKT geometry strings</span>
                            </div>
                        </div>

                        <!-- Metadata Section -->
                        <div class="metadata-section-open">
                            <div class="form-group-header">Metadata</div>
                            <div class="metadata-fields">
                                <div class="form-group">
                                    <label for="title">Title</label>
                                    <input type="text" id="title" name="title"
                                           placeholder="Human-readable dataset title">
                                    <span class="field-hint">Display title (auto-generated from DDH IDs if not provided)</span>
                                </div>
                                <div class="form-group">
                                    <label for="description">Description</label>
                                    <textarea id="description" name="description" rows="2"
                                              placeholder="Full dataset description"></textarea>
                                </div>
                                <div class="form-row">
                                    <div class="form-group">
                                        <label for="access_level">Access Level</label>
                                        <select id="access_level" name="access_level">
                                            <option value="">Not specified</option>
                                            <option value="OUO">OUO (Official Use Only)</option>
                                            <option value="PUBLIC">PUBLIC</option>
                                            <option value="restricted">Restricted</option>
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label for="tags">Tags</label>
                                        <input type="text" id="tags" name="tags"
                                               placeholder="e.g., boundaries, admin">
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Processing Parameters Section -->
                        <div class="processing-section">
                            <div class="form-group-header">Processing Parameters</div>
                            <div class="processing-fields">
                                <div class="form-group checkbox-group">
                                    <label>
                                        <input type="checkbox" id="overwrite" name="overwrite" value="true">
                                        Allow overwrite if data exists
                                    </label>
                                    <span class="field-hint">If enabled, existing data will be replaced</span>
                                </div>
                            </div>
                        </div>

                        <!-- Platform API cURL Section (Prominent) -->
                        <div class="curl-section-prominent" id="curl-section">
                            <div class="curl-section-header">
                                <span class="curl-title">📋 Platform API cURL</span>
                                <button type="button" class="btn btn-sm btn-copy" onclick="copyCurl()">
                                    <span id="copy-icon">📋</span> Copy
                                </button>
                            </div>
                            <pre id="curl-command" class="curl-code">Fill in DDH identifiers to see the Platform API cURL command</pre>
                            <div class="curl-hint">Copy to Postman or terminal - or use the Submit button below</div>
                        </div>

                        <div class="submit-divider">
                            <span>OR submit directly</span>
                        </div>

                        <!-- Submit Button -->
                        <div class="form-actions">
                            <button type="submit" id="submit-btn" class="btn btn-primary" disabled>
                                🚀 Submit via Platform API
                            </button>
                            <span id="submit-spinner" class="htmx-indicator spinner-inline"></span>
                        </div>
                    </form>

                    <!-- Result Display -->
                    <div id="submit-result" class="submit-result-container hidden">
                        <!-- Result will be inserted here via HTMX -->
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Submit Vector interface."""
        return """
        /* Two-column layout - equal width columns */
        .two-column-layout {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }

        @media (max-width: 1200px) {
            .two-column-layout {
                grid-template-columns: 1fr;
            }
        }

        /* Section headers */
        .section-header {
            margin-bottom: 16px;
        }

        .section-header h2 {
            font-size: 18px;
            color: var(--ds-navy);
            margin-bottom: 4px;
        }

        .section-subtitle {
            font-size: 13px;
            color: var(--ds-gray);
            margin: 0;
        }

        /* Browser section */
        .browser-section {
            background: white;
            border-radius: 6px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        /* Form section */
        .form-section {
            background: white;
            border-radius: 6px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        /* Controls - Grid layout */
        .controls-grid {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 16px;
        }

        .controls-row {
            display: flex;
            gap: 16px;
            align-items: flex-end;
        }

        .control-group {
            display: flex;
            flex-direction: column;
            gap: 4px;
            position: relative;
            flex: 1;
        }

        .control-group.filter-group {
            flex: 1;
        }

        .control-group label {
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Zone badge - fixed to Bronze */
        .zone-badge-bronze {
            background: #cd7f32;
            color: white;
            padding: 8px 12px;
            border-radius: 3px;
            font-weight: 600;
            text-align: center;
            font-size: 13px;
        }

        .filter-input {
            padding: 8px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            font-size: 14px;
            color: var(--ds-navy);
            width: 100%;
        }

        /* Stats banner */
        .stats-banner {
            background: var(--ds-bg);
            padding: 12px 16px;
            border-radius: 4px;
            margin-bottom: 16px;
        }

        /* Files table */
        .files-section {
            max-height: 400px;
            overflow-y: auto;
        }

        .files-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        .files-table thead {
            background: var(--ds-bg);
            position: sticky;
            top: 0;
        }

        .files-table th {
            text-align: left;
            padding: 10px 12px;
            font-weight: 600;
            color: var(--ds-navy);
            border-bottom: 2px solid var(--ds-gray-light);
            font-size: 11px;
            text-transform: uppercase;
        }

        .files-table td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .files-table tbody tr {
            cursor: pointer;
            transition: background 0.2s;
        }

        .files-table tbody tr:hover {
            background: var(--ds-bg);
        }

        .files-table tbody tr.selected {
            background: #E6F3FF;
            border-left: 3px solid var(--ds-blue-primary);
        }

        .file-name {
            font-weight: 500;
            color: var(--ds-blue-primary);
            word-break: break-all;
        }

        .file-size, .file-date {
            font-size: 12px;
            color: var(--ds-gray);
        }

        .file-type {
            display: inline-block;
            padding: 2px 6px;
            background: var(--ds-bg);
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
            color: var(--ds-gray);
        }

        .supported-formats {
            font-size: 12px;
            color: var(--ds-gray);
            margin-top: 8px;
        }

        /* Form styles */
        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 6px;
        }

        .form-group.required label::after {
            content: ' *';
            color: var(--ds-status-failed-fg);
        }

        .form-group input[type="text"],
        .form-group textarea,
        .form-group select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            font-size: 14px;
            color: var(--ds-navy);
            background: white;
        }

        .form-group input:focus,
        .form-group textarea:focus,
        .form-group select:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 2px rgba(0, 113, 188, 0.1);
        }

        .field-hint {
            display: block;
            font-size: 11px;
            color: var(--ds-gray);
            margin-top: 4px;
        }

        /* Checkbox group */
        .checkbox-group label {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            font-weight: 400;
        }

        .checkbox-group input[type="checkbox"] {
            width: 16px;
            height: 16px;
        }

        /* Selected file display */
        .selected-file-display {
            padding: 12px;
            background: var(--ds-bg);
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            color: var(--ds-navy);
            word-break: break-all;
        }

        .selected-file-display .placeholder {
            color: var(--ds-gray);
            font-family: inherit;
            font-style: italic;
        }

        .selected-file-display .file-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .selected-file-display .file-path {
            font-weight: 600;
            color: var(--ds-blue-primary);
        }

        .selected-file-display .file-meta {
            font-size: 11px;
            color: var(--ds-gray);
        }

        /* CSV fields */
        .csv-fields {
            background: #fffbf0;
            border: 1px solid var(--ds-gold);
            border-radius: 4px;
            padding: 16px;
            margin-bottom: 16px;
        }

        .form-group-header {
            font-size: 13px;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 12px;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .form-group-or {
            text-align: center;
            color: var(--ds-gray);
            font-size: 12px;
            font-weight: 600;
            padding: 8px 0;
        }

        /* Metadata section (always open) */
        .metadata-section-open {
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            margin-bottom: 16px;
            background: white;
        }

        .metadata-section-open .form-group-header {
            padding: 12px 16px;
            background: var(--ds-bg);
            border-bottom: 1px solid var(--ds-gray-light);
            border-radius: 6px 6px 0 0;
            margin-bottom: 0;
        }

        .metadata-fields {
            padding: 16px;
        }

        /* Processing Parameters section */
        .processing-section {
            border: 1px solid var(--ds-gray-light);
            border-radius: 6px;
            margin-bottom: 16px;
            background: white;
        }

        .processing-section .form-group-header {
            padding: 12px 16px;
            background: var(--ds-bg);
            border-bottom: 1px solid var(--ds-gray-light);
            border-radius: 6px 6px 0 0;
            margin-bottom: 0;
        }

        .processing-fields {
            padding: 16px;
        }

        .processing-fields .checkbox-group {
            margin-bottom: 0;
        }

        .processing-fields .field-hint {
            margin-left: 24px;
        }

        /* Form actions */
        .form-actions {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .btn {
            padding: 12px 24px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            border: none;
        }

        .btn-primary {
            background: var(--ds-blue-primary);
            color: white;
        }

        .btn-primary:hover:not(:disabled) {
            background: var(--ds-cyan);
        }

        .btn-primary:disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        .btn-secondary {
            background: white;
            color: var(--ds-blue-primary);
            border: 1px solid var(--ds-blue-primary);
        }

        .btn-secondary:hover {
            background: var(--ds-bg);
        }

        /* Spinner inline */
        .spinner-inline {
            width: 20px;
            height: 20px;
            border: 2px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        /* Submit result */
        .submit-result-container {
            margin-top: 20px;
        }

        .submit-result {
            padding: 20px;
            border-radius: 6px;
            text-align: center;
        }

        .submit-result.success {
            background: var(--ds-status-completed-bg);
            border: 1px solid var(--ds-status-completed-fg);
        }

        .submit-result.error {
            background: var(--ds-status-failed-bg);
            border: 1px solid var(--ds-status-failed-fg);
        }

        .result-icon {
            font-size: 48px;
            margin-bottom: 12px;
        }

        .submit-result h3 {
            margin: 0 0 16px 0;
            color: var(--ds-navy);
        }

        .result-details {
            background: white;
            border-radius: 4px;
            padding: 16px;
            text-align: left;
            margin-bottom: 16px;
        }

        .result-details .detail-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .result-details .detail-row:last-child {
            border-bottom: none;
        }

        .result-details .detail-label {
            font-weight: 600;
            color: var(--ds-gray);
        }

        .result-details .detail-value {
            color: var(--ds-navy);
        }

        .result-details .mono {
            font-family: 'Courier New', monospace;
            font-size: 12px;
        }

        .result-actions {
            display: flex;
            gap: 12px;
            justify-content: center;
        }

        .error-message {
            color: var(--ds-status-failed-fg);
            margin-bottom: 16px;
        }

        /* Small spinner */
        .spinner-sm {
            width: 16px;
            height: 16px;
            border: 2px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            position: absolute;
            right: -24px;
            bottom: 10px;
        }

        /* DDH Section */
        .ddh-section {
            background: #f0f7ff;
            border: 1px solid var(--ds-blue-primary);
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 16px;
        }

        .ddh-section .form-group-header {
            color: var(--ds-blue-primary);
            margin-bottom: 12px;
        }

        /* Prominent cURL Section */
        .curl-section-prominent {
            background: #1e293b;
            border-radius: 8px;
            padding: 16px;
            margin: 20px 0;
        }

        .curl-section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .curl-title {
            color: #e2e8f0;
            font-weight: 600;
            font-size: 14px;
        }

        .curl-section-prominent .curl-hint {
            color: #94a3b8;
            font-size: 11px;
            margin-top: 8px;
            text-align: center;
        }

        .curl-section-prominent .btn-copy {
            background: #334155;
            border-color: #475569;
            color: #e2e8f0;
        }

        .curl-section-prominent .btn-copy:hover {
            background: var(--ds-blue-primary);
            border-color: var(--ds-blue-primary);
        }

        .curl-code {
            background: #0f172a;
            color: #e2e8f0;
            padding: 16px;
            border-radius: 6px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            line-height: 1.5;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
            margin: 0;
            max-height: 300px;
        }

        /* Submit Divider */
        .submit-divider {
            display: flex;
            align-items: center;
            text-align: center;
            margin: 16px 0;
        }

        .submit-divider::before,
        .submit-divider::after {
            content: '';
            flex: 1;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .submit-divider span {
            padding: 0 12px;
            color: var(--ds-gray);
            font-size: 12px;
            font-weight: 500;
            text-transform: uppercase;
        }

        /* Legacy cURL section (collapsible) - kept for backwards compat */
        .curl-section {
            margin-top: 20px;
            background: var(--ds-bg);
            border-radius: 8px;
            border: 1px solid var(--ds-gray-light);
        }

        .curl-section summary {
            padding: 12px 16px;
            cursor: pointer;
            font-weight: 600;
            color: var(--ds-navy);
            user-select: none;
        }

        .curl-section summary:hover {
            background: white;
        }

        .curl-container {
            padding: 0 16px 16px 16px;
        }

        .curl-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .curl-hint {
            font-size: 12px;
            color: var(--ds-gray);
        }

        .btn-copy {
            padding: 4px 10px;
            font-size: 12px;
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            cursor: pointer;
        }

        .btn-copy:hover {
            background: var(--ds-blue-primary);
            color: white;
            border-color: var(--ds-blue-primary);
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate JavaScript for Submit Vector interface with Platform API support."""
        return """
        // Update load button state based on selections
        function updateLoadButton() {
            const container = document.getElementById('container-select').value;
            const loadBtn = document.getElementById('load-btn');

            loadBtn.disabled = !container;
        }

        // Show files table and hide initial state
        function showFilesTable() {
            document.getElementById('initial-state')?.classList.add('hidden');
            document.getElementById('files-table')?.classList.remove('hidden');
            document.getElementById('stats-banner')?.classList.remove('hidden');
        }

        // Update submit button state based on required fields
        function updateSubmitButton() {
            const blobName = document.getElementById('blob_name').value;
            const datasetId = document.getElementById('dataset_id').value;
            const resourceId = document.getElementById('resource_id').value;
            const versionId = document.getElementById('version_id').value;

            const submitBtn = document.getElementById('submit-btn');
            // title is optional - only require DDH identifiers and file selection
            submitBtn.disabled = !(blobName && datasetId && resourceId && versionId);
        }

        // Select a file from the browser
        function selectFile(blobName, container, zone) {
            // Update hidden form fields
            document.getElementById('blob_name').value = blobName;
            document.getElementById('container_name').value = container;

            // Extract and set file extension
            const ext = blobName.split('.').pop().toLowerCase();
            document.getElementById('file_extension').value = ext;

            // Highlight selected row
            document.querySelectorAll('.files-table tbody tr').forEach(row => {
                row.classList.remove('selected');
            });
            event.currentTarget.classList.add('selected');

            // Update selected file display
            const shortName = blobName.split('/').pop();
            document.getElementById('selected-file').innerHTML = `
                <div class="file-info">
                    <span class="file-path">${shortName}</span>
                    <span class="file-meta">${container} / ${blobName}</span>
                </div>
            `;

            // Show/hide CSV fields
            const csvFields = document.getElementById('csv-fields');
            if (ext === 'csv') {
                csvFields.classList.remove('hidden');
            } else {
                csvFields.classList.add('hidden');
            }

            // Auto-suggest dataset_id from filename if empty
            const datasetInput = document.getElementById('dataset_id');
            if (!datasetInput.value) {
                // Convert filename to valid DDH identifier
                let datasetId = shortName.split('.')[0]
                    .toLowerCase()
                    .replace(/[^a-z0-9-]/g, '-')
                    .replace(/^-+|-+$/g, '')
                    .replace(/--+/g, '-');
                datasetInput.value = datasetId;
            }

            updateSubmitButton();
            updateCurlPreview();
        }

        // Listen for HTMX events
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            // After loading files, show the table
            if (evt.detail.target.id === 'files-tbody') {
                showFilesTable();
            }

            // After submit, show result container
            if (evt.detail.target.id === 'submit-result') {
                document.getElementById('submit-result').classList.remove('hidden');
            }
        });

        // Handle Enter key in filter input
        document.getElementById('prefix-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('load-btn').click();
            }
        });

        // Generate Platform API cURL command from form values
        function generateCurl() {
            const blobName = document.getElementById('blob_name').value;
            const containerName = document.getElementById('container_name').value;
            const fileExtension = document.getElementById('file_extension').value;

            // DDH Identifiers
            const datasetId = document.getElementById('dataset_id').value;
            const resourceId = document.getElementById('resource_id').value;
            const versionId = document.getElementById('version_id').value;

            // Processing options
            const overwrite = document.getElementById('overwrite').checked;

            // Optional metadata
            const title = document.getElementById('title').value;
            const description = document.getElementById('description').value;
            const accessLevel = document.getElementById('access_level').value;
            const tags = document.getElementById('tags').value;

            // CSV-specific
            const latName = document.getElementById('lat_name').value;
            const lonName = document.getElementById('lon_name').value;
            const wktColumn = document.getElementById('wkt_column').value;

            if (!datasetId || !resourceId || !versionId) {
                return 'Fill in DDH identifiers (dataset_id, resource_id, version_id) to see the Platform API cURL command';
            }

            if (!blobName) {
                return 'Select a file to see the Platform API cURL command';
            }

            const baseUrl = window.location.origin;

            // Build Platform API payload
            const payload = {
                dataset_id: datasetId,
                resource_id: resourceId,
                version_id: versionId,
                data_type: "vector",
                operation: "CREATE",
                container_name: containerName,
                file_name: blobName
            };

            // Optional metadata
            if (title) payload.title = title;
            if (accessLevel) payload.access_level = accessLevel;
            if (description) payload.description = description;
            if (tags) {
                payload.tags = tags.split(',').map(t => t.trim()).filter(t => t);
            }

            // Processing options
            const processingOptions = {};
            if (overwrite) processingOptions.overwrite = true;

            // CSV fields
            if (fileExtension === 'csv') {
                if (latName) processingOptions.lat_column = latName;
                if (lonName) processingOptions.lon_column = lonName;
                if (wktColumn) processingOptions.wkt_column = wktColumn;
            }

            if (Object.keys(processingOptions).length > 0) {
                payload.processing_options = processingOptions;
            }

            const jsonStr = JSON.stringify(payload, null, 2);

            return `curl -X POST "${baseUrl}/api/platform/submit" \\
  -H "Content-Type: application/json" \\
  -d '${jsonStr}'`;
        }

        // Update cURL preview
        function updateCurlPreview() {
            const curlEl = document.getElementById('curl-command');
            if (curlEl) {
                curlEl.textContent = generateCurl();
            }
        }

        // Copy cURL to clipboard
        function copyCurl() {
            const curlText = generateCurl();
            navigator.clipboard.writeText(curlText).then(() => {
                const copyIcon = document.getElementById('copy-icon');
                copyIcon.textContent = '✅';
                setTimeout(() => { copyIcon.textContent = '📋'; }, 1500);
            }).catch(err => {
                console.error('Copy failed:', err);
                alert('Copy failed. Please select and copy manually.');
            });
        }

        // Add event listeners for form changes to update cURL and submit button
        document.addEventListener('DOMContentLoaded', () => {
            const formInputs = ['dataset_id', 'resource_id', 'version_id', 'overwrite',
                                'title', 'description', 'access_level', 'tags',
                                'lat_name', 'lon_name', 'wkt_column'];
            formInputs.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.addEventListener('input', () => {
                        updateCurlPreview();
                        updateSubmitButton();
                    });
                    el.addEventListener('change', () => {
                        updateCurlPreview();
                        updateSubmitButton();
                    });
                }
            });
        });
        """
