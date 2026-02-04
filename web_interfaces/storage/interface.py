"""
Storage browser interface module.

Web dashboard for browsing Azure Blob Storage containers with HTMX-powered
cascading dropdowns and dynamic file loading.

Features (23 DEC 2025 - S12.2.2):
    - HTMX-powered zone→container dropdown cascade
    - HTMX file listing with loading indicators
    - HTMX file detail panel
    - Reduced JavaScript, server-side rendering

Exports:
    StorageInterface: Storage file browser with HTMX interactivity
"""

import logging
from datetime import datetime
from typing import List, Dict, Any

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)

# Valid storage zones
VALID_ZONES = ["bronze", "silver", "silverext", "gold"]


@InterfaceRegistry.register('storage')
class StorageInterface(BaseInterface):
    """
    Storage Browser interface with HTMX interactivity.

    Uses HTMX for:
        - Zone→container dropdown cascade (server-side)
        - File listing with loading indicators
        - File detail panel population

    Fragments supported:
        - containers: Returns container <option> elements for zone
        - files: Returns file table rows
        - file-detail: Returns file detail panel content
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Storage Browser HTML with HTMX attributes.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Storage Browser",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """
        Handle HTMX partial requests for storage fragments.

        Fragments:
            containers: Returns <option> elements for container dropdown
            files: Returns table rows for file listing
            file-detail: Returns file detail panel content

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
        elif fragment == 'file-detail':
            return self._render_file_detail_fragment(request)
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
            # Import BlobRepository to get containers for zone
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            containers = repo.list_containers()

            if not containers:
                return '<option value="">No containers in zone</option>'

            # Return container options - containers is list of dicts with 'name' key
            options = [f'<option value="{c["name"]}">{c["name"]}</option>' for c in containers]
            return '\n'.join(options)

        except Exception as e:
            logger.error(f"Error loading containers for zone {zone}: {e}")
            return f'<option value="">Error loading containers</option>'

    def _render_files_fragment(self, request: func.HttpRequest) -> str:
        """Render file table rows."""
        zone = request.params.get('zone', '')
        container = request.params.get('container', '')
        prefix = request.params.get('prefix', '')
        suffix = request.params.get('suffix', '')
        limit = int(request.params.get('limit', '250'))

        if not zone or not container:
            return self._render_files_error("Please select a zone and container first")

        try:
            # Import BlobRepository to list blobs
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            blobs = repo.list_blobs(
                container=container,
                prefix=prefix if prefix else "",
                limit=limit
            )

            # Apply suffix filter if specified (BlobRepository doesn't support suffix directly)
            if suffix:
                blobs = [b for b in blobs if b.get('name', '').endswith(suffix)]

            if not blobs:
                return self._render_files_empty()

            # Build table rows
            rows = []
            for i, blob in enumerate(blobs):
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

                # Determine file type
                if blob.get('size', 0) == 0:
                    ext = 'Folder'
                elif '.' in short_name:
                    ext = short_name.split('.')[-1].upper()
                else:
                    ext = 'File'

                # Encode blob name for use in hx-get
                encoded_name = name.replace("'", "\\'")

                row = f'''
                <tr class="file-row"
                    hx-get="/api/interface/storage?fragment=file-detail&zone={zone}&container={container}&path={name}"
                    hx-target="#detail-content"
                    hx-trigger="click"
                    hx-indicator="#detail-spinner"
                    onclick="showDetailPanel(); this.closest('tbody').querySelectorAll('tr').forEach(r=>r.classList.remove('selected')); this.classList.add('selected');"
                    data-index="{i}">
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

            # OOB swap to update stats - wrapped in <template> to avoid HTML parsing issues
            # See: https://github.com/bigskysoftware/htmx/issues/1900
            total_size = sum(b.get('size', 0) for b in blobs) / (1024 * 1024)
            stats_html = f'''
            <template>
                <div id="stats-content" hx-swap-oob="true">
                    <div class="stat-item">
                        <span class="stat-label">Files Loaded</span>
                        <span class="stat-value">{len(blobs)}</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Size</span>
                        <span class="stat-value">{total_size:.2f} MB</span>
                    </div>
                </div>
            </template>
            '''

            return '\n'.join(rows) + stats_html

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
                    <h3>No Files Found</h3>
                    <p>No files match the current filter or the container is empty</p>
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

    def _render_file_detail_fragment(self, request: func.HttpRequest) -> str:
        """Render file detail panel content."""
        zone = request.params.get('zone', '')
        container = request.params.get('container', '')
        path = request.params.get('path', '')

        if not zone or not container or not path:
            return '<p class="error-text">Missing file information</p>'

        try:
            # Import BlobRepository to get blob properties
            from infrastructure.blob import BlobRepository

            repo = BlobRepository.for_zone(zone)
            props = repo.get_blob_properties(container=container, blob_path=path)

            if not props:
                return '<p class="error-text">File not found</p>'

            # Extract metadata from blob properties dict
            filename = path.split('/')[-1] if '/' in path else path
            size = props.get('size', 0)
            size_mb = size / (1024 * 1024)
            content_type = props.get('content_type', 'Unknown') or 'Unknown'
            last_modified = props.get('last_modified', 'N/A') or 'N/A'

            # Extract folder from path
            folder = '/'.join(path.split('/')[:-1]) if '/' in path else ''
            # Extract extension
            extension = filename.split('.')[-1] if '.' in filename else ''
            # Get etag
            etag = props.get('etag', '')

            # Format last modified in Eastern Time
            if last_modified and last_modified != 'N/A':
                try:
                    from zoneinfo import ZoneInfo
                    eastern = ZoneInfo('America/New_York')
                    dt = datetime.fromisoformat(last_modified.replace('Z', '+00:00'))
                    dt_eastern = dt.astimezone(eastern)
                    last_modified = dt_eastern.strftime('%m/%d/%Y %I:%M:%S %p') + ' ET'
                except Exception:
                    pass

            html = f'''
            <div class="detail-row">
                <div class="detail-label">Filename</div>
                <div class="detail-value">{filename}</div>
            </div>
            <div class="detail-row">
                <div class="detail-label">Full Path</div>
                <div class="detail-value mono">{path}</div>
            </div>
            <div class="detail-row">
                <div class="detail-label">Size</div>
                <div class="detail-value">{size_mb:.2f} MB ({size:,} bytes)</div>
            </div>
            <div class="detail-row">
                <div class="detail-label">Content Type</div>
                <div class="detail-value">{content_type}</div>
            </div>
            <div class="detail-row">
                <div class="detail-label">Last Modified</div>
                <div class="detail-value">{last_modified}</div>
            </div>
            '''

            if folder:
                html += f'''
            <div class="detail-row">
                <div class="detail-label">Folder</div>
                <div class="detail-value mono">{folder}</div>
            </div>
            '''

            if extension:
                html += f'''
            <div class="detail-row">
                <div class="detail-label">Extension</div>
                <div class="detail-value">.{extension}</div>
            </div>
            '''

            if etag:
                html += f'''
            <div class="detail-row">
                <div class="detail-label">ETag</div>
                <div class="detail-value mono" style="font-size: 11px;">{etag}</div>
            </div>
            '''

            return html

        except Exception as e:
            logger.error(f"Error loading file details: {e}", exc_info=True)
            return f'''
            <div class="error-state" style="padding: 20px; margin: 0; box-shadow: none;">
                <p>Failed to load file details</p>
                <p style="font-size: 12px; color: #999;">{str(e)}</p>
            </div>
            '''

    def _generate_html_content(self) -> str:
        """Generate HTML content structure with HTMX attributes."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <h1>📦 Storage Browser</h1>
                <p class="subtitle">Browse Azure Blob Storage across Bronze, Silver, and Gold zones</p>
            </header>

            <!-- Controls -->
            <div class="controls">
                <div class="control-group">
                    <label for="zone-select">Zone:</label>
                    <select id="zone-select" name="zone" class="filter-select"
                            hx-get="/api/interface/storage?fragment=containers"
                            hx-target="#container-select"
                            hx-trigger="change"
                            hx-indicator="#container-spinner"
                            hx-include="[name='zone']"
                            onchange="updateLoadButton()">
                        <option value="">Loading zones...</option>
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
                           placeholder="e.g., maxar/ or data/2025/">
                </div>

                <div class="control-group">
                    <label for="suffix-input">Extension:</label>
                    <input type="text" id="suffix-input" name="suffix" class="filter-input suffix-input"
                           placeholder=".tif">
                </div>

                <div class="button-group">
                    <button id="load-btn" class="refresh-button" disabled
                            hx-get="/api/interface/storage?fragment=files"
                            hx-target="#files-tbody"
                            hx-trigger="click"
                            hx-indicator="#loading-spinner"
                            hx-include="#zone-select, #container-select, #prefix-input, #suffix-input, #limit-input"
                            onclick="showFilesTable()">
                        🔄 Load Files
                    </button>
                    <input type="hidden" id="limit-input" name="limit" value="250">
                    <button type="button" class="load-button" onclick="setLimit(50)">50</button>
                    <button type="button" class="load-button active" onclick="setLimit(250)">250</button>
                    <button type="button" class="load-button" onclick="setLimit(1000)">1000</button>
                </div>
            </div>

            <!-- Stats Banner -->
            <div id="stats-banner" class="stats-banner hidden">
                <div id="stats-content">
                    <div class="stat-item">
                        <span class="stat-label">Files Loaded</span>
                        <span class="stat-value" id="files-count">0</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Total Size</span>
                        <span class="stat-value" id="total-size">0 MB</span>
                    </div>
                </div>
            </div>

            <!-- Main Content Area -->
            <div class="main-content">
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
                        <p>Choose a storage zone and container, then click "Load Files"</p>
                    </div>
                </div>

                <!-- File Detail Panel -->
                <div id="detail-panel" class="detail-panel hidden">
                    <div class="detail-header">
                        <h3>📄 File Details</h3>
                        <button onclick="closeDetailPanel()" class="close-button">×</button>
                    </div>
                    <div id="detail-content" class="detail-content">
                        <!-- File details will be inserted here via HTMX -->
                        <div id="detail-spinner" class="htmx-indicator spinner"></div>
                    </div>
                    <div class="detail-actions">
                        <div class="job-placeholder">
                            <h4>Submit Processing Job</h4>
                            <p class="placeholder-text">Select a file to see job submission options</p>
                            <a href="/api/interface/submit" class="submit-button" style="display: block; text-align: center; text-decoration: none;">
                                🚀 Submit New Job
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Storage Browser.

        Note: Most styles now in COMMON_CSS (S12.1.1).
        Only storage-specific styles remain here.
        """
        return """
        /* Storage-specific: Controls layout */
        .controls {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            gap: 20px;
            align-items: flex-end;
            flex-wrap: wrap;
        }

        .control-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
            position: relative;
        }

        .control-group label {
            font-size: 12px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .filter-input {
            padding: 10px 15px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            font-size: 14px;
            color: var(--ds-navy);
            background: white;
            min-width: 200px;
        }

        .filter-input.suffix-input {
            min-width: 80px;
            width: 80px;
        }

        .filter-input:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
        }

        .button-group {
            display: flex;
            gap: 8px;
            align-items: center;
        }

        .load-button {
            background: white;
            color: var(--ds-blue-primary);
            border: 1px solid var(--ds-gray-light);
            padding: 10px 16px;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }

        .load-button:hover, .load-button.active {
            background: var(--ds-bg);
            border-color: var(--ds-blue-primary);
        }

        .load-button.active {
            background: var(--ds-blue-primary);
            color: white;
        }

        /* Storage-specific: Stats banner */
        .stats-banner {
            background: white;
            padding: 15px 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            gap: 40px;
        }

        /* Storage-specific: Main content layout */
        .main-content {
            display: flex;
            gap: 20px;
        }

        .files-section {
            flex: 1;
            min-width: 0;
        }

        /* Storage-specific: Files table */
        .files-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 3px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .files-table thead {
            background: var(--ds-bg);
        }

        .files-table th {
            text-align: left;
            padding: 15px;
            font-weight: 700;
            color: var(--ds-navy);
            border-bottom: 2px solid var(--ds-gray-light);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .files-table td {
            padding: 12px 15px;
            border-bottom: 1px solid var(--ds-gray-light);
            color: var(--ds-navy);
            font-size: 14px;
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

        .file-size {
            font-family: 'Courier New', monospace;
            font-size: 13px;
            color: var(--ds-gray);
        }

        .file-date {
            font-size: 13px;
            color: var(--ds-gray);
        }

        .file-type {
            display: inline-block;
            padding: 3px 8px;
            background: var(--ds-bg);
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
        }

        /* Storage-specific: Detail Panel */
        .detail-panel {
            width: 400px;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            flex-shrink: 0;
            display: flex;
            flex-direction: column;
            max-height: calc(100vh - 300px);
        }

        .detail-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .detail-header h3 {
            font-size: 16px;
            color: var(--ds-navy);
            margin: 0;
        }

        .close-button {
            background: none;
            border: none;
            font-size: 24px;
            color: var(--ds-gray);
            cursor: pointer;
            padding: 0;
            line-height: 1;
        }

        .close-button:hover {
            color: var(--ds-navy);
        }

        .detail-content {
            padding: 20px;
            overflow-y: auto;
            flex: 1;
        }

        .detail-row {
            margin-bottom: 15px;
        }

        .detail-label {
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-gray);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }

        .detail-value {
            font-size: 14px;
            color: var(--ds-navy);
            word-break: break-all;
        }

        .detail-value.mono {
            font-family: 'Courier New', monospace;
            font-size: 13px;
            background: var(--ds-bg);
            padding: 8px;
            border-radius: 3px;
        }

        .detail-actions {
            padding: 20px;
            border-top: 1px solid var(--ds-gray-light);
            background: var(--ds-bg);
        }

        .job-placeholder h4 {
            font-size: 14px;
            color: var(--ds-navy);
            margin: 0 0 10px 0;
        }

        .placeholder-text {
            font-size: 13px;
            color: var(--ds-gray);
            margin: 0 0 15px 0;
        }

        .submit-button {
            width: 100%;
            padding: 12px;
            background: var(--ds-blue-primary);
            color: white;
            border: none;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
        }

        .submit-button:hover {
            background: var(--ds-cyan);
        }

        /* Storage-specific: Inline spinner next to dropdown */
        .spinner-sm {
            width: 18px;
            height: 18px;
            border: 2px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            position: absolute;
            right: -25px;
            bottom: 12px;
        }

        /* Responsive */
        @media (max-width: 1200px) {
            .main-content {
                flex-direction: column;
            }

            .detail-panel {
                width: 100%;
                max-height: none;
            }
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate minimal JavaScript for Storage Browser.

        Most functionality now handled by HTMX (S12.2.2).
        Only UI helper functions remain.
        """
        return """
        // Load zones on page load
        document.addEventListener('DOMContentLoaded', loadZones);

        // Load zones from API (still needed for initial population)
        async function loadZones() {
            const zoneSelect = document.getElementById('zone-select');

            try {
                const data = await fetchJSON(`${API_BASE_URL}/api/storage/containers`);
                const zonesData = data.zones || {};

                // Populate zone dropdown
                const zoneOptions = Object.entries(zonesData)
                    .filter(([zone, info]) => !info.error && info.containers?.length > 0)
                    .map(([zone, info]) => {
                        const icon = zone === 'bronze' ? '🟤' :
                                    zone === 'silver' ? '⚪' :
                                    zone === 'silverext' ? '🔘' : '🟡';
                        return `<option value="${zone}">${icon} ${zone} (${info.account}) - ${info.container_count} containers</option>`;
                    });

                if (zoneOptions.length > 0) {
                    zoneSelect.innerHTML = '<option value="">Select a zone...</option>' + zoneOptions.join('');
                } else {
                    zoneSelect.innerHTML = '<option value="">No zones available</option>';
                }

            } catch (error) {
                console.error('Error loading zones:', error);
                zoneSelect.innerHTML = '<option value="">Error loading zones</option>';
            }
        }

        // Update load button state based on selections
        function updateLoadButton() {
            const zone = document.getElementById('zone-select').value;
            const container = document.getElementById('container-select').value;
            const loadBtn = document.getElementById('load-btn');

            loadBtn.disabled = !zone || !container;
        }

        // Set limit and update button state
        function setLimit(limit) {
            document.getElementById('limit-input').value = limit;

            // Update button active state
            document.querySelectorAll('.load-button').forEach(btn => {
                btn.classList.remove('active');
                if (btn.textContent === String(limit)) {
                    btn.classList.add('active');
                }
            });
        }

        // Show files table and hide initial state
        function showFilesTable() {
            document.getElementById('initial-state')?.classList.add('hidden');
            document.getElementById('files-table')?.classList.remove('hidden');
            document.getElementById('stats-banner')?.classList.remove('hidden');
        }

        // Show detail panel
        function showDetailPanel() {
            document.getElementById('detail-panel')?.classList.remove('hidden');
        }

        // Close detail panel
        function closeDetailPanel() {
            document.getElementById('detail-panel')?.classList.add('hidden');
            document.querySelectorAll('.files-table tbody tr').forEach(row => {
                row.classList.remove('selected');
            });
        }

        // Handle Enter key in filter inputs
        ['prefix-input', 'suffix-input'].forEach(id => {
            document.getElementById(id)?.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    document.getElementById('load-btn').click();
                }
            });
        });

        // Listen for HTMX events to update UI
        document.body.addEventListener('htmx:afterSwap', function(evt) {
            // After loading files, show the table
            if (evt.detail.target.id === 'files-tbody') {
                showFilesTable();
            }
        });
        """
