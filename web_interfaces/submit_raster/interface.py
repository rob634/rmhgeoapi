# ============================================================================
# CLAUDE CONTEXT - SUBMIT RASTER WEB INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Submit Raster Job Form
# PURPOSE: HTMX interface for ProcessRasterV2Job submission
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: SubmitRasterInterface
# DEPENDENCIES: azure.functions, web_interfaces.base, jobs.process_raster_v2
# ============================================================================
"""
Submit Raster Job interface module.

Web interface for submitting ProcessRasterV2Job with file browser and form.

Features (28 DEC 2025):
    - HTMX-powered file browser (reuses Storage patterns)
    - Auto-filter for raster extensions (.tif, .tiff, .img, .jp2, etc.)
    - Form for ProcessRasterV2Job parameters
    - HTMX job submission with result display
    - Raster-specific fields (CRS, raster_type, output_tier)

Exports:
    SubmitRasterInterface: Job submission interface for raster ETL
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

# Valid raster file extensions
RASTER_EXTENSIONS = ['.tif', '.tiff', '.geotiff', '.img', '.jp2', '.ecw', '.vrt', '.nc', '.hdf', '.hdf5']


@InterfaceRegistry.register('submit-raster')
class SubmitRasterInterface(BaseInterface):
    """
    Submit Raster Job interface with HTMX interactivity.

    Combines file browser (from Storage pattern) with ProcessRasterV2Job
    submission form. Demonstrates HTMX form submission pattern.

    Fragments supported:
        - containers: Returns container <option> elements for zone
        - files: Returns file table rows (filtered for raster extensions)
        - submit: Handles job submission and returns result
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Submit Raster Job HTML with HTMX attributes.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Submit Raster Job",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """
        Handle HTMX partial requests for submit-raster fragments.

        Fragments:
            containers: Returns <option> elements for container dropdown
            files: Returns table rows for file listing (raster files only)
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
        """Render file table rows (filtered for raster extensions)."""
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

            # Filter for raster extensions
            raster_blobs = []
            for blob in blobs:
                name = blob.get('name', '').lower()
                if any(name.endswith(ext) for ext in RASTER_EXTENSIONS):
                    raster_blobs.append(blob)
                if len(raster_blobs) >= limit:
                    break

            if not raster_blobs:
                return self._render_files_empty()

            # Build table rows
            rows = []
            for i, blob in enumerate(raster_blobs):
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

                # Size warning for large files
                size_class = 'file-size'
                if size_mb > 1024:
                    size_class = 'file-size warning'

                row = f'''
                <tr class="file-row"
                    onclick="selectFile('{name}', '{container}', '{zone}', {size_mb:.2f})"
                    data-blob="{name}"
                    data-container="{container}"
                    data-zone="{zone}"
                    data-size="{size_mb:.2f}">
                    <td>
                        <div class="file-name" title="{name}">{short_name}</div>
                    </td>
                    <td>
                        <span class="{size_class}">{size_mb:.2f} MB</span>
                    </td>
                    <td>
                        <span class="file-date">{date_str}</span>
                    </td>
                    <td>
                        <span class="file-type">{ext}</span>
                    </td>
                </tr>'''
                rows.append(row)

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
                    <div class="icon" style="font-size: 48px;">🗺️</div>
                    <h3>No Raster Files Found</h3>
                    <p>No files with supported raster extensions (.tif, .tiff, .img, .jp2, etc.)</p>
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
            from urllib.parse import parse_qs
            form_data = parse_qs(body)

            # Extract parameters
            def get_param(key, default=None):
                values = form_data.get(key, [])
                return values[0] if values else default

            blob_name = get_param('blob_name')
            container_name = get_param('container_name')

            # Validate required fields
            if not blob_name:
                return self._render_submit_error("Missing blob_name. Please select a file.")
            if not container_name:
                return self._render_submit_error("Missing container_name. Please select a container.")

            # Build job parameters
            job_params = {
                'blob_name': blob_name,
                'container_name': container_name
            }

            # Optional CRS parameters
            input_crs = get_param('input_crs')
            target_crs = get_param('target_crs')
            if input_crs:
                job_params['input_crs'] = input_crs
            if target_crs:
                job_params['target_crs'] = target_crs

            # Raster type
            raster_type = get_param('raster_type', 'auto')
            if raster_type and raster_type != 'auto':
                job_params['raster_type'] = raster_type

            # Output tier
            output_tier = get_param('output_tier', 'analysis')
            if output_tier:
                job_params['output_tier'] = output_tier

            # JPEG quality (for visualization tier)
            jpeg_quality = get_param('jpeg_quality')
            if jpeg_quality:
                try:
                    job_params['jpeg_quality'] = int(jpeg_quality)
                except ValueError:
                    pass

            # Output folder
            output_folder = get_param('output_folder')
            if output_folder:
                job_params['output_folder'] = output_folder

            # Collection ID
            collection_id = get_param('collection_id')
            if collection_id:
                job_params['collection_id'] = collection_id

            # Behavior flags
            strict_mode = get_param('strict_mode')
            if strict_mode == 'true':
                job_params['strict_mode'] = True

            in_memory = get_param('in_memory')
            if in_memory == 'true':
                job_params['in_memory'] = True
            elif in_memory == 'false':
                job_params['in_memory'] = False

            # Submit job
            from jobs import ALL_JOBS
            from infrastructure.factory import RepositoryFactory

            if 'process_raster_v2' not in ALL_JOBS:
                return self._render_submit_error("ProcessRasterV2Job not found in registry")

            controller_class = ALL_JOBS['process_raster_v2']
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
                    <span class="detail-label">Source File</span>
                    <span class="detail-value">{params.get('blob_name', 'N/A')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Container</span>
                    <span class="detail-value">{params.get('container_name', 'N/A')}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Output Tier</span>
                    <span class="detail-value">{params.get('output_tier', 'analysis')}</span>
                </div>
            </div>
            <div class="result-actions">
                <a href="/api/interface/tasks?job_id={job_id}" class="btn btn-primary">View Job Tasks</a>
                <a href="/api/interface/pipeline" class="btn btn-secondary">View Pipeline Dashboard</a>
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
                <h1>🗺️ Submit Raster Job</h1>
                <p class="subtitle">Convert raster imagery to Cloud-Optimized GeoTIFF with STAC cataloging</p>
            </header>

            <div class="two-column-layout">
                <!-- Left Column: File Browser -->
                <div class="browser-section">
                    <div class="section-header">
                        <h2>1. Select Source File</h2>
                        <p class="section-subtitle">Browse and select a raster file</p>
                    </div>

                    <!-- Controls -->
                    <div class="controls">
                        <div class="control-group">
                            <label for="zone-select">Zone:</label>
                            <select id="zone-select" name="zone" class="filter-select"
                                    hx-get="/api/interface/submit-raster?fragment=containers"
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
                                   placeholder="e.g., rasters/">
                        </div>

                        <button id="load-btn" class="refresh-button" disabled
                                hx-get="/api/interface/submit-raster?fragment=files"
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
                                <span class="stat-label">Raster Files</span>
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
                            <div class="icon">🗺️</div>
                            <h3>Select a Zone and Container</h3>
                            <p>Choose a storage zone and container to browse raster files</p>
                            <p class="supported-formats">Supported: .tif, .tiff, .img, .jp2, .ecw, .vrt, .nc</p>
                        </div>
                    </div>
                </div>

                <!-- Right Column: Job Form -->
                <div class="form-section">
                    <div class="section-header">
                        <h2>2. Configure Job</h2>
                        <p class="section-subtitle">Set processing options</p>
                    </div>

                    <form id="submit-form"
                          hx-post="/api/interface/submit-raster?fragment=submit"
                          hx-target="#submit-result"
                          hx-indicator="#submit-spinner">

                        <!-- Hidden fields populated by file selection -->
                        <input type="hidden" id="blob_name" name="blob_name" value="">
                        <input type="hidden" id="container_name" name="container_name" value="">

                        <!-- Selected File Display -->
                        <div class="form-group">
                            <label>Selected File</label>
                            <div id="selected-file" class="selected-file-display">
                                <span class="placeholder">No file selected - click a file in the browser</span>
                            </div>
                        </div>

                        <!-- Size Warning (shown conditionally) -->
                        <div id="size-warning" class="size-warning hidden">
                            ⚠️ Large file detected (>1GB). Processing may take longer.
                        </div>

                        <!-- Raster Type -->
                        <div class="form-group">
                            <label for="raster_type">Raster Type</label>
                            <select id="raster_type" name="raster_type">
                                <option value="auto" selected>Auto-detect</option>
                                <option value="dem">DEM (elevation)</option>
                                <option value="rgb">RGB imagery</option>
                                <option value="rgba">RGBA imagery</option>
                                <option value="multispectral">Multispectral</option>
                                <option value="categorical">Categorical (landcover)</option>
                                <option value="nir">Near-infrared</option>
                            </select>
                            <span class="field-hint">Auto-detect works for most files</span>
                        </div>

                        <!-- Output Tier -->
                        <div class="form-group">
                            <label for="output_tier">Output Tier</label>
                            <select id="output_tier" name="output_tier" onchange="toggleJpegQuality()">
                                <option value="analysis" selected>Analysis (LZW compression)</option>
                                <option value="visualization">Visualization (JPEG for web)</option>
                                <option value="archive">Archive (DEFLATE, max compression)</option>
                                <option value="all">All tiers</option>
                            </select>
                            <span class="field-hint">Analysis tier recommended for most use cases</span>
                        </div>

                        <!-- JPEG Quality (shown for visualization tier) -->
                        <div id="jpeg-quality-group" class="form-group hidden">
                            <label for="jpeg_quality">JPEG Quality</label>
                            <input type="number" id="jpeg_quality" name="jpeg_quality"
                                   min="1" max="100" value="85"
                                   placeholder="1-100">
                            <span class="field-hint">Higher = better quality, larger file</span>
                        </div>

                        <!-- CRS Section -->
                        <details class="crs-section">
                            <summary>CRS Options</summary>
                            <div class="crs-fields">
                                <div class="form-group">
                                    <label for="input_crs">Input CRS (optional)</label>
                                    <input type="text" id="input_crs" name="input_crs"
                                           placeholder="e.g., EPSG:32618">
                                    <span class="field-hint">Override if source CRS is missing or wrong</span>
                                </div>
                                <div class="form-group">
                                    <label for="target_crs">Target CRS (optional)</label>
                                    <input type="text" id="target_crs" name="target_crs"
                                           placeholder="e.g., EPSG:4326">
                                    <span class="field-hint">Reproject to different CRS (default: EPSG:4326)</span>
                                </div>
                            </div>
                        </details>

                        <!-- Advanced Options -->
                        <details class="advanced-section">
                            <summary>Advanced Options</summary>
                            <div class="advanced-fields">
                                <div class="form-group">
                                    <label for="output_folder">Output Folder</label>
                                    <input type="text" id="output_folder" name="output_folder"
                                           placeholder="e.g., processed/2025/">
                                    <span class="field-hint">Custom output path in silver-cogs container</span>
                                </div>

                                <div class="form-group">
                                    <label for="collection_id">STAC Collection ID</label>
                                    <input type="text" id="collection_id" name="collection_id"
                                           placeholder="e.g., satellite-imagery">
                                    <span class="field-hint">Group related items in STAC catalog</span>
                                </div>

                                <div class="form-group checkbox-group">
                                    <label>
                                        <input type="checkbox" id="strict_mode" name="strict_mode" value="true">
                                        Strict mode (fail on any warning)
                                    </label>
                                </div>

                                <div class="form-group checkbox-group">
                                    <label>
                                        <input type="checkbox" id="in_memory" name="in_memory" value="true">
                                        Process in-memory (faster for small files)
                                    </label>
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

                    <!-- cURL Preview Section -->
                    <details class="curl-section" id="curl-section">
                        <summary>📋 cURL Command</summary>
                        <div class="curl-container">
                            <div class="curl-header">
                                <span class="curl-hint">Equivalent API call - click to copy</span>
                                <button type="button" class="btn btn-sm btn-copy" onclick="copyCurl()">
                                    <span id="copy-icon">📋</span> Copy
                                </button>
                            </div>
                            <pre id="curl-command" class="curl-code">Select a file and fill in the form to see the cURL command</pre>
                        </div>
                    </details>

                    <!-- Result Display -->
                    <div id="submit-result" class="submit-result-container hidden">
                        <!-- Result will be inserted here via HTMX -->
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Submit Raster interface."""
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

        .file-size.warning {
            color: var(--ds-status-pending-fg);
            font-weight: 600;
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

        /* Size warning */
        .size-warning {
            background: var(--ds-status-pending-bg);
            color: var(--ds-status-pending-fg);
            padding: 12px 16px;
            border-radius: 4px;
            margin-bottom: 16px;
            font-size: 13px;
            font-weight: 500;
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

        .form-group input[type="text"],
        .form-group input[type="number"],
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

        /* CRS and Advanced sections */
        .crs-section,
        .advanced-section {
            border: 1px solid var(--ds-gray-light);
            border-radius: 4px;
            margin-bottom: 16px;
        }

        .crs-section summary,
        .advanced-section summary {
            padding: 12px 16px;
            font-weight: 600;
            color: var(--ds-navy);
            cursor: pointer;
            background: var(--ds-bg);
        }

        .crs-section[open] summary,
        .advanced-section[open] summary {
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .crs-fields,
        .advanced-fields {
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

        /* cURL Preview Section */
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

        .curl-code {
            background: #1e293b;
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
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate JavaScript for Submit Raster interface."""
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

        // Toggle JPEG quality field based on output tier
        function toggleJpegQuality() {
            const tier = document.getElementById('output_tier').value;
            const jpegGroup = document.getElementById('jpeg-quality-group');

            if (tier === 'visualization' || tier === 'all') {
                jpegGroup.classList.remove('hidden');
            } else {
                jpegGroup.classList.add('hidden');
            }
        }

        // Select a file from the browser
        function selectFile(blobName, container, zone, sizeMb) {
            // Update hidden form fields
            document.getElementById('blob_name').value = blobName;
            document.getElementById('container_name').value = container;

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
                    <span class="file-meta">${container} / ${blobName} (${sizeMb.toFixed(2)} MB)</span>
                </div>
            `;

            // Show size warning for large files
            const sizeWarning = document.getElementById('size-warning');
            if (sizeMb > 1024) {
                sizeWarning.classList.remove('hidden');
            } else {
                sizeWarning.classList.add('hidden');
            }

            // Enable submit button
            document.getElementById('submit-btn').disabled = false;
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

        // Generate cURL command from form values
        function generateCurl() {
            const blobName = document.getElementById('blob_name').value;
            const containerName = document.getElementById('container_name').value;
            const rasterType = document.getElementById('raster_type').value;
            const outputTier = document.getElementById('output_tier').value;
            const jpegQuality = document.getElementById('jpeg_quality').value;
            const inputCrs = document.getElementById('input_crs').value;
            const targetCrs = document.getElementById('target_crs').value;
            const outputFolder = document.getElementById('output_folder').value;
            const collectionId = document.getElementById('collection_id').value;
            const strictMode = document.getElementById('strict_mode').checked;
            const inMemory = document.getElementById('in_memory').checked;

            if (!blobName) {
                return 'Select a file to see the cURL command';
            }

            const baseUrl = window.location.origin;

            // Build params object
            const params = {
                blob_name: blobName,
                container_name: containerName
            };

            if (rasterType && rasterType !== 'unknown') params.raster_type = rasterType;
            if (outputTier && outputTier !== 'silver') params.output_tier = outputTier;
            if (jpegQuality && outputTier === 'jpeg') params.jpeg_quality = parseInt(jpegQuality);
            if (inputCrs) params.input_crs = inputCrs;
            if (targetCrs) params.target_crs = targetCrs;
            if (outputFolder) params.output_folder = outputFolder;
            if (collectionId) params.collection_id = collectionId;
            if (strictMode) params.strict_mode = true;
            if (inMemory) params.in_memory = true;

            const jsonStr = JSON.stringify(params, null, 2);

            return `curl -X POST "${baseUrl}/api/jobs/submit/process_raster_v2" \\
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

        // Add event listeners for form changes to update cURL
        document.addEventListener('DOMContentLoaded', () => {
            const formInputs = ['raster_type', 'output_tier', 'jpeg_quality', 'input_crs',
                                'target_crs', 'output_folder', 'collection_id', 'strict_mode', 'in_memory'];
            formInputs.forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.addEventListener('input', updateCurlPreview);
                    el.addEventListener('change', updateCurlPreview);
                }
            });
        });

        // Override selectFile to also update cURL
        const originalSelectFile = selectFile;
        selectFile = function(blobName, container, zone, sizeMb) {
            originalSelectFile(blobName, container, zone, sizeMb);
            updateCurlPreview();
        };
        """
