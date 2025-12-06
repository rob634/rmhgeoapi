"""
Pipeline dashboard interface module.

Web dashboard for browsing Azure Blob Storage bronze container files with filtering and detail views.

Exports:
    PipelineInterface: Bronze container file browser with metadata and selection capabilities
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('pipeline')
class PipelineInterface(BaseInterface):
    """
    Pipeline Dashboard interface for Bronze container browsing.

    Displays files from Azure Blob Storage bronze containers with
    filtering, sorting, and detail view capabilities.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Pipeline Dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        # HTML content
        content = self._generate_html_content()

        # Custom CSS for Pipeline Dashboard
        custom_css = self._generate_custom_css()

        # Custom JavaScript for Pipeline Dashboard
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Pipeline Dashboard",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content structure."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <h1>📦 Pipeline Dashboard</h1>
                <p class="subtitle">Browse Bronze container files for processing</p>
            </header>

            <!-- Controls -->
            <div class="controls">
                <div class="control-group">
                    <label for="container-select">Container:</label>
                    <select id="container-select" class="filter-select">
                        <option value="rmhazuregeobronze" selected>rmhazuregeobronze (Bronze)</option>
                        <option value="rmhazuregeosilver">rmhazuregeosilver (Silver)</option>
                        <option value="rmhazuregeogold">rmhazuregeogold (Gold)</option>
                        <option value="silver-cogs">silver-cogs</option>
                        <option value="source-data">source-data</option>
                    </select>
                </div>

                <div class="control-group">
                    <label for="prefix-input">Folder Filter:</label>
                    <input type="text" id="prefix-input" class="filter-input"
                           placeholder="e.g., maxar/ or data/2025/">
                </div>

                <div class="button-group">
                    <button onclick="loadBlobs()" class="refresh-button">🔄 Refresh</button>
                    <button onclick="loadBlobs(10)" class="load-button">10</button>
                    <button onclick="loadBlobs(50)" class="load-button active">50</button>
                    <button onclick="loadBlobs(1000)" class="load-button">All</button>
                </div>
            </div>

            <!-- Stats Banner -->
            <div id="stats-banner" class="stats-banner hidden">
                <div class="stat-item">
                    <span class="stat-label">Files Loaded</span>
                    <span class="stat-value" id="files-count">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Total Size</span>
                    <span class="stat-value" id="total-size">0 MB</span>
                </div>
            </div>

            <!-- Main Content Area -->
            <div class="main-content">
                <!-- Files Table -->
                <div class="files-section">
                    <div id="loading-spinner" class="spinner hidden"></div>

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
                            <!-- Files will be inserted here -->
                        </tbody>
                    </table>

                    <!-- Empty State -->
                    <div id="empty-state" class="empty-state hidden">
                        <div class="icon">📁</div>
                        <h3>No Files Found</h3>
                        <p>No files match the current filter or the container is empty</p>
                    </div>

                    <!-- Error State -->
                    <div id="error-state" class="error-state hidden">
                        <div class="icon">⚠️</div>
                        <h3>Error Loading Files</h3>
                        <p id="error-message"></p>
                        <button onclick="loadBlobs()" class="refresh-button" style="margin-top: 15px;">
                            🔄 Retry
                        </button>
                    </div>
                </div>

                <!-- File Detail Panel -->
                <div id="detail-panel" class="detail-panel hidden">
                    <div class="detail-header">
                        <h3>📄 File Details</h3>
                        <button onclick="closeDetailPanel()" class="close-button">×</button>
                    </div>
                    <div id="detail-content" class="detail-content">
                        <!-- File details will be inserted here -->
                    </div>
                    <div class="detail-actions">
                        <div class="job-placeholder">
                            <h4>Submit Processing Job</h4>
                            <p class="placeholder-text">Job submission coming soon...</p>
                            <button class="submit-button disabled" disabled>
                                🚀 Submit Job (Coming Soon)
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Pipeline Dashboard."""
        return """
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
            margin-bottom: 10px;
            font-weight: 700;
        }

        .subtitle {
            color: #626F86;
            font-size: 16px;
            margin: 0;
        }

        /* Controls */
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
        }

        .control-group label {
            font-size: 12px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .filter-select, .filter-input {
            padding: 10px 15px;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            font-size: 14px;
            color: #053657;
            background: white;
            min-width: 180px;
        }

        .filter-input {
            min-width: 250px;
        }

        .filter-select:focus, .filter-input:focus {
            outline: none;
            border-color: #0071BC;
        }

        .button-group {
            display: flex;
            gap: 8px;
            align-items: center;
        }

        .refresh-button {
            background: #0071BC;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }

        .refresh-button:hover {
            background: #00A3DA;
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(0,113,188,0.3);
        }

        .load-button {
            background: white;
            color: #0071BC;
            border: 1px solid #e9ecef;
            padding: 10px 16px;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }

        .load-button:hover, .load-button.active {
            background: #f8f9fa;
            border-color: #0071BC;
        }

        .load-button.active {
            background: #0071BC;
            color: white;
        }

        /* Stats Banner */
        .stats-banner {
            background: white;
            padding: 15px 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            gap: 40px;
        }

        .stat-item {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .stat-label {
            font-size: 12px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 18px;
            color: #053657;
            font-weight: 700;
        }

        /* Main Content */
        .main-content {
            display: flex;
            gap: 20px;
        }

        .files-section {
            flex: 1;
            min-width: 0;
        }

        /* Files Table */
        .files-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 3px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .files-table thead {
            background: #f8f9fa;
        }

        .files-table th {
            text-align: left;
            padding: 15px;
            font-weight: 700;
            color: #053657;
            border-bottom: 2px solid #e9ecef;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .files-table td {
            padding: 12px 15px;
            border-bottom: 1px solid #e9ecef;
            color: #053657;
            font-size: 14px;
        }

        .files-table tbody tr {
            cursor: pointer;
            transition: background 0.2s;
        }

        .files-table tbody tr:hover {
            background: #f8f9fa;
        }

        .files-table tbody tr.selected {
            background: #E6F3FF;
            border-left: 3px solid #0071BC;
        }

        .file-name {
            font-weight: 500;
            color: #0071BC;
            word-break: break-all;
        }

        .file-size {
            font-family: 'Courier New', monospace;
            font-size: 13px;
            color: #626F86;
        }

        .file-date {
            font-size: 13px;
            color: #626F86;
        }

        .file-type {
            display: inline-block;
            padding: 3px 8px;
            background: #f8f9fa;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
        }

        /* Detail Panel */
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
            border-bottom: 1px solid #e9ecef;
        }

        .detail-header h3 {
            font-size: 16px;
            color: #053657;
            margin: 0;
        }

        .close-button {
            background: none;
            border: none;
            font-size: 24px;
            color: #626F86;
            cursor: pointer;
            padding: 0;
            line-height: 1;
        }

        .close-button:hover {
            color: #053657;
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
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }

        .detail-value {
            font-size: 14px;
            color: #053657;
            word-break: break-all;
        }

        .detail-value.mono {
            font-family: 'Courier New', monospace;
            font-size: 13px;
            background: #f8f9fa;
            padding: 8px;
            border-radius: 3px;
        }

        .detail-actions {
            padding: 20px;
            border-top: 1px solid #e9ecef;
            background: #f8f9fa;
        }

        .job-placeholder h4 {
            font-size: 14px;
            color: #053657;
            margin: 0 0 10px 0;
        }

        .placeholder-text {
            font-size: 13px;
            color: #626F86;
            margin: 0 0 15px 0;
        }

        .submit-button {
            width: 100%;
            padding: 12px;
            background: #0071BC;
            color: white;
            border: none;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
        }

        .submit-button.disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        /* Empty/Error States */
        .empty-state, .error-state {
            text-align: center;
            padding: 60px 20px;
            color: #626F86;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .empty-state .icon, .error-state .icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .empty-state h3, .error-state h3 {
            color: #053657;
            margin-bottom: 10px;
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
        """Generate custom JavaScript for Pipeline Dashboard."""
        return """
        let currentLimit = 50;
        let currentBlobs = [];
        let selectedBlob = null;

        // Load blobs on page load
        document.addEventListener('DOMContentLoaded', () => loadBlobs(50));

        // Load blobs from API
        async function loadBlobs(limit = null) {
            if (limit !== null) {
                currentLimit = limit;
                // Update active button
                document.querySelectorAll('.load-button').forEach(btn => {
                    btn.classList.remove('active');
                    if ((limit === 10 && btn.textContent === '10') ||
                        (limit === 50 && btn.textContent === '50') ||
                        (limit === 1000 && btn.textContent === 'All')) {
                        btn.classList.add('active');
                    }
                });
            }

            const container = document.getElementById('container-select').value;
            const prefix = document.getElementById('prefix-input').value.trim();

            const spinner = document.getElementById('loading-spinner');
            const table = document.getElementById('files-table');
            const tbody = document.getElementById('files-tbody');
            const emptyState = document.getElementById('empty-state');
            const errorState = document.getElementById('error-state');
            const statsBanner = document.getElementById('stats-banner');

            // Show loading
            spinner.classList.remove('hidden');
            table.classList.add('hidden');
            emptyState.classList.add('hidden');
            errorState.classList.add('hidden');
            statsBanner.classList.add('hidden');
            closeDetailPanel();

            try {
                // Build URL
                const params = new URLSearchParams({ limit: currentLimit });
                if (prefix) params.append('prefix', prefix);

                const url = `${API_BASE_URL}/api/containers/${container}/blobs?${params}`;
                const data = await fetchJSON(url);

                spinner.classList.add('hidden');
                currentBlobs = data.blobs || [];

                if (currentBlobs.length === 0) {
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Render table
                tbody.innerHTML = currentBlobs.map((blob, index) => {
                    const sizeMB = (blob.size / (1024 * 1024)).toFixed(2);
                    const date = blob.last_modified ? new Date(blob.last_modified).toLocaleDateString() : 'N/A';
                    const shortName = blob.name.split('/').pop();

                    // Determine type: folders (size=0) or file extension
                    let ext;
                    if (blob.size === 0) {
                        ext = 'Folder';
                    } else if (shortName.includes('.')) {
                        ext = shortName.split('.').pop().toUpperCase();
                    } else {
                        ext = 'File';
                    }

                    return `
                        <tr onclick="selectBlob(${index})" data-index="${index}">
                            <td>
                                <div class="file-name" title="${blob.name}">${shortName}</div>
                            </td>
                            <td>
                                <span class="file-size">${sizeMB} MB</span>
                            </td>
                            <td>
                                <span class="file-date">${date}</span>
                            </td>
                            <td>
                                <span class="file-type">${ext}</span>
                            </td>
                        </tr>
                    `;
                }).join('');

                table.classList.remove('hidden');

                // Update stats
                const totalSize = currentBlobs.reduce((sum, b) => sum + (b.size || 0), 0);
                const totalSizeMB = (totalSize / (1024 * 1024)).toFixed(2);
                document.getElementById('files-count').textContent = currentBlobs.length;
                document.getElementById('total-size').textContent = `${totalSizeMB} MB`;
                statsBanner.classList.remove('hidden');

            } catch (error) {
                console.error('Error loading blobs:', error);
                spinner.classList.add('hidden');
                errorState.classList.remove('hidden');
                document.getElementById('error-message').textContent = error.message || 'Failed to load files';
            }
        }

        // Select blob and show details
        async function selectBlob(index) {
            const blob = currentBlobs[index];
            if (!blob) return;

            selectedBlob = blob;

            // Highlight selected row
            document.querySelectorAll('.files-table tbody tr').forEach(row => {
                row.classList.remove('selected');
            });
            document.querySelector(`tr[data-index="${index}"]`)?.classList.add('selected');

            // Show detail panel with loading state
            const detailPanel = document.getElementById('detail-panel');
            const detailContent = document.getElementById('detail-content');

            detailPanel.classList.remove('hidden');
            detailContent.innerHTML = '<div class="spinner"></div>';

            try {
                // Fetch detailed metadata
                const container = document.getElementById('container-select').value;
                // Use query param for blob path (Azure Functions v4 doesn't support :path constraint)
                const url = `${API_BASE_URL}/api/containers/${container}/blob?path=${encodeURIComponent(blob.name)}`;
                const metadata = await fetchJSON(url);

                // Render details
                detailContent.innerHTML = `
                    <div class="detail-row">
                        <div class="detail-label">Filename</div>
                        <div class="detail-value">${metadata.filename || blob.name.split('/').pop()}</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Full Path</div>
                        <div class="detail-value mono">${metadata.name || blob.name}</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Size</div>
                        <div class="detail-value">${metadata.size_mb || (blob.size / (1024 * 1024)).toFixed(2)} MB (${(metadata.size || blob.size).toLocaleString()} bytes)</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Content Type</div>
                        <div class="detail-value">${metadata.content_type || 'Unknown'}</div>
                    </div>
                    <div class="detail-row">
                        <div class="detail-label">Last Modified</div>
                        <div class="detail-value">${metadata.last_modified ? new Date(metadata.last_modified).toLocaleString() : 'N/A'}</div>
                    </div>
                    ${metadata.folder ? `
                    <div class="detail-row">
                        <div class="detail-label">Folder</div>
                        <div class="detail-value mono">${metadata.folder}</div>
                    </div>
                    ` : ''}
                    ${metadata.extension ? `
                    <div class="detail-row">
                        <div class="detail-label">Extension</div>
                        <div class="detail-value">.${metadata.extension}</div>
                    </div>
                    ` : ''}
                    ${metadata.etag ? `
                    <div class="detail-row">
                        <div class="detail-label">ETag</div>
                        <div class="detail-value mono" style="font-size: 11px;">${metadata.etag}</div>
                    </div>
                    ` : ''}
                `;

            } catch (error) {
                console.error('Error loading blob details:', error);
                detailContent.innerHTML = `
                    <div class="error-state" style="padding: 20px;">
                        <p>Failed to load file details</p>
                        <p style="font-size: 12px; color: #999;">${error.message}</p>
                    </div>
                `;
            }
        }

        // Close detail panel
        function closeDetailPanel() {
            document.getElementById('detail-panel').classList.add('hidden');
            document.querySelectorAll('.files-table tbody tr').forEach(row => {
                row.classList.remove('selected');
            });
            selectedBlob = null;
        }

        // Handle Enter key in prefix input
        document.getElementById('prefix-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                loadBlobs();
            }
        });
        """
