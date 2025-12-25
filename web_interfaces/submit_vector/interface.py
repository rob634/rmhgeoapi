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
VALID_ZONES = ["bronze", "silver", "silverext"]

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
                        dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                        date_str = dt.strftime('%Y-%m-%d')
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
        """Handle job submission and return result HTML."""
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

            blob_name = get_param('blob_name')
            container_name = get_param('container_name')
            table_name = get_param('table_name')
            file_extension = get_param('file_extension')

            # Validate required fields
            if not blob_name:
                return self._render_submit_error("Missing blob_name. Please select a file.")
            if not table_name:
                return self._render_submit_error("Missing table_name. Please enter a table name.")

            # Auto-detect extension if not provided
            if not file_extension and '.' in blob_name:
                file_extension = blob_name.split('.')[-1].lower()

            if not file_extension:
                return self._render_submit_error("Could not detect file extension. Please provide it explicitly.")

            # Build job parameters
            job_params = {
                'blob_name': blob_name,
                'file_extension': file_extension,
                'table_name': table_name
            }

            # Add optional parameters
            if container_name:
                job_params['container_name'] = container_name

            schema = get_param('schema')
            if schema:
                job_params['schema'] = schema

            overwrite = get_param('overwrite')
            if overwrite == 'true':
                job_params['overwrite'] = True

            # CSV-specific parameters
            lat_name = get_param('lat_name')
            lon_name = get_param('lon_name')
            wkt_column = get_param('wkt_column')

            if lat_name:
                job_params['lat_name'] = lat_name
            if lon_name:
                job_params['lon_name'] = lon_name
            if wkt_column:
                job_params['wkt_column'] = wkt_column

            # Metadata parameters
            title = get_param('title')
            description = get_param('description')
            attribution = get_param('attribution')
            license_val = get_param('license')
            keywords = get_param('keywords')

            if title:
                job_params['title'] = title
            if description:
                job_params['description'] = description
            if attribution:
                job_params['attribution'] = attribution
            if license_val:
                job_params['license'] = license_val
            if keywords:
                job_params['keywords'] = keywords

            # Submit job using the same pattern as submit_job_trigger
            from jobs import ALL_JOBS
            from infrastructure.factory import RepositoryFactory

            if 'process_vector' not in ALL_JOBS:
                return self._render_submit_error("ProcessVectorJob not found in registry")

            # Get job controller
            controller_class = ALL_JOBS['process_vector']
            controller = controller_class()

            # Validate parameters
            validated_params = controller.validate_job_parameters(job_params)

            # Generate job ID
            job_id = controller.generate_job_id(validated_params)

            # Check if job already exists
            repos = RepositoryFactory.create_repositories()
            existing_job = repos['job_repo'].get_job(job_id)

            if existing_job:
                job_status = existing_job.status.value if hasattr(existing_job.status, 'value') else str(existing_job.status)
                if job_status == 'completed':
                    return self._render_submit_success(job_id, validated_params, message="Job already completed (idempotent)")
                elif job_status in ('pending', 'processing'):
                    return self._render_submit_success(job_id, validated_params, message=f"Job already {job_status}")

            # Create job record
            controller.create_job_record(job_id, validated_params)

            # Queue job for processing
            controller.queue_job(job_id, validated_params)

            return self._render_submit_success(job_id, validated_params)

        except Exception as e:
            logger.error(f"Error submitting job: {e}", exc_info=True)
            return self._render_submit_error(str(e))

    def _render_submit_success(self, job_id: str, params: dict, message: str = None) -> str:
        """Render successful job submission result."""
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
                <a href="/api/interface/jobs" class="btn btn-primary">View Jobs Dashboard</a>
                <a href="/api/jobs/status/{job_id}" class="btn btn-secondary" target="_blank">View Job Status (JSON)</a>
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
                <p class="subtitle">Upload vector data to PostGIS with STAC cataloging</p>
            </header>

            <div class="two-column-layout">
                <!-- Left Column: File Browser -->
                <div class="browser-section">
                    <div class="section-header">
                        <h2>1. Select Source File</h2>
                        <p class="section-subtitle">Browse and select a vector file</p>
                    </div>

                    <!-- Controls -->
                    <div class="controls">
                        <div class="control-group">
                            <label for="zone-select">Zone:</label>
                            <select id="zone-select" name="zone" class="filter-select"
                                    hx-get="/api/interface/submit-vector?fragment=containers"
                                    hx-target="#container-select"
                                    hx-trigger="change"
                                    hx-indicator="#container-spinner"
                                    hx-include="[name='zone']"
                                    onchange="updateLoadButton()">
                                <option value="">Select zone...</option>
                                <option value="bronze">🟤 Bronze (raw uploads)</option>
                                <option value="silver">⚪ Silver (processed)</option>
                            </select>
                            <span id="container-spinner" class="htmx-indicator spinner-sm"></span>
                        </div>

                        <div class="control-group">
                            <label for="container-select">Container:</label>
                            <select id="container-select" name="container" class="filter-select"
                                    onchange="updateLoadButton()">
                                <option value="">Select zone first</option>
                            </select>
                        </div>

                        <div class="control-group">
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
                            <h3>Select a Zone and Container</h3>
                            <p>Choose a storage zone and container to browse vector files</p>
                            <p class="supported-formats">Supported: .csv, .geojson, .json, .gpkg, .kml, .kmz, .shp, .zip</p>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Job Form -->
                <div class="form-section">
                    <div class="section-header">
                        <h2>2. Configure Job</h2>
                        <p class="section-subtitle">Set table name and options</p>
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

                        <!-- Required Fields -->
                        <div class="form-group required">
                            <label for="table_name">Table Name *</label>
                            <input type="text" id="table_name" name="table_name" required
                                   placeholder="e.g., my_vector_data"
                                   pattern="[a-z][a-z0-9_]*"
                                   title="Lowercase letters, numbers, underscores. Must start with letter.">
                            <span class="field-hint">Target PostGIS table name</span>
                        </div>

                        <div class="form-group">
                            <label for="schema">Schema</label>
                            <select id="schema" name="schema">
                                <option value="geo" selected>geo (default)</option>
                                <option value="public">public</option>
                            </select>
                            <span class="field-hint">Target PostGIS schema</span>
                        </div>

                        <div class="form-group checkbox-group">
                            <label>
                                <input type="checkbox" id="overwrite" name="overwrite" value="true">
                                Allow overwrite if table exists
                            </label>
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

                        <!-- Metadata Section (collapsible) -->
                        <details class="metadata-section">
                            <summary>Optional Metadata</summary>
                            <div class="metadata-fields">
                                <div class="form-group">
                                    <label for="title">Title</label>
                                    <input type="text" id="title" name="title"
                                           placeholder="Human-readable dataset name">
                                </div>
                                <div class="form-group">
                                    <label for="description">Description</label>
                                    <textarea id="description" name="description" rows="2"
                                              placeholder="Full dataset description"></textarea>
                                </div>
                                <div class="form-group">
                                    <label for="attribution">Attribution</label>
                                    <input type="text" id="attribution" name="attribution"
                                           placeholder="e.g., Natural Earth - naturalearthdata.com">
                                </div>
                                <div class="form-group">
                                    <label for="license">License</label>
                                    <select id="license" name="license">
                                        <option value="">Not specified</option>
                                        <option value="CC0-1.0">CC0-1.0 (Public Domain)</option>
                                        <option value="CC-BY-4.0">CC-BY-4.0 (Attribution)</option>
                                        <option value="CC-BY-SA-4.0">CC-BY-SA-4.0 (Attribution-ShareAlike)</option>
                                        <option value="MIT">MIT</option>
                                        <option value="ODbL-1.0">ODbL-1.0 (Open Database)</option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label for="keywords">Keywords</label>
                                    <input type="text" id="keywords" name="keywords"
                                           placeholder="Comma-separated tags, e.g., boundaries,admin">
                                </div>
                            </div>
                        </details>

                        <!-- Submit Button -->
                        <div class="form-actions">
                            <button type="submit" id="submit-btn" class="btn btn-primary" disabled>
                                🚀 Submit Job
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
        /* Two-column layout */
        .two-column-layout {
            display: grid;
            grid-template-columns: 1fr 400px;
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

        /* Controls */
        .controls {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            align-items: flex-end;
            margin-bottom: 16px;
        }

        .control-group {
            display: flex;
            flex-direction: column;
            gap: 4px;
            position: relative;
        }

        .control-group label {
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .filter-input {
            padding: 8px 12px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            font-size: 14px;
            color: var(--ds-navy);
            min-width: 150px;
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

        /* Metadata section */
        .metadata-section {
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            margin-bottom: 16px;
        }

        .metadata-section summary {
            padding: 12px 16px;
            font-weight: 600;
            color: var(--ds-navy);
            cursor: pointer;
            background: var(--ds-bg);
        }

        .metadata-section[open] summary {
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .metadata-fields {
            padding: 16px;
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
        """

    def _generate_custom_js(self) -> str:
        """Generate minimal JavaScript for Submit Vector interface."""
        return """
        // Update load button state based on selections
        function updateLoadButton() {
            const zone = document.getElementById('zone-select').value;
            const container = document.getElementById('container-select').value;
            const loadBtn = document.getElementById('load-btn');

            loadBtn.disabled = !zone || !container;
        }

        // Show files table and hide initial state
        function showFilesTable() {
            document.getElementById('initial-state')?.classList.add('hidden');
            document.getElementById('files-table')?.classList.remove('hidden');
            document.getElementById('stats-banner')?.classList.remove('hidden');
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

            // Enable submit button
            document.getElementById('submit-btn').disabled = false;

            // Auto-suggest table name from filename
            const tableInput = document.getElementById('table_name');
            if (!tableInput.value) {
                // Convert filename to valid table name
                let tableName = shortName.split('.')[0]
                    .toLowerCase()
                    .replace(/[^a-z0-9_]/g, '_')
                    .replace(/^[0-9]/, 't_$&');
                tableInput.value = tableName;
            }
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
        """
