"""
Upload interface module.

Web dashboard for uploading files to bronze storage containers.

Features (15 JAN 2026):
    - File upload form with drag-and-drop
    - Container selection (bronze-* only)
    - Path customization
    - Upload progress indicator
    - Upload history display

Exports:
    UploadInterface: File upload form with HTMX interactivity
"""

import logging
from typing import Dict, Any

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('upload')
class UploadInterface(BaseInterface):
    """
    Upload interface for bronze storage.

    Provides a form for uploading files to bronze-* containers.
    Security: Only bronze containers allowed (untrusted data zone).
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Upload form HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Upload to Bronze Storage",
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
                <h1>Upload to Bronze Storage</h1>
                <p class="subtitle">Upload files to bronze storage containers (untrusted data zone)</p>
            </header>

            <!-- Upload Form Card -->
            <div class="upload-card">
                <form id="upload-form" enctype="multipart/form-data">
                    <!-- Container Selection -->
                    <div class="form-group">
                        <label for="container-select">Target Container</label>
                        <select id="container-select" name="container" class="form-select" required>
                            <option value="">Loading containers...</option>
                        </select>
                        <span class="form-hint">Only bronze-* containers allowed</span>
                    </div>

                    <!-- Path Input -->
                    <div class="form-group">
                        <label for="path-input">Path (optional)</label>
                        <input type="text" id="path-input" name="path" class="form-input"
                               placeholder="e.g., uploads/subfolder/filename.gpkg">
                        <span class="form-hint">Leave empty to use original filename</span>
                    </div>

                    <!-- File Drop Zone -->
                    <div class="form-group">
                        <label>Select File</label>
                        <div id="drop-zone" class="drop-zone">
                            <div class="drop-zone-content">
                                <div class="drop-icon">+</div>
                                <p class="drop-text">Drag and drop a file here, or click to browse</p>
                                <p class="drop-hint">Maximum file size: 100 MB</p>
                            </div>
                            <input type="file" id="file-input" name="file" class="file-input" required>
                        </div>
                    </div>

                    <!-- Selected File Info -->
                    <div id="file-info" class="file-info hidden">
                        <div class="file-icon">+</div>
                        <div class="file-details">
                            <span id="file-name" class="file-name"></span>
                            <span id="file-size" class="file-size"></span>
                        </div>
                        <button type="button" id="clear-file" class="clear-button">X</button>
                    </div>

                    <!-- Submit Button -->
                    <div class="form-actions">
                        <button type="submit" id="upload-btn" class="upload-button" disabled>
                            Upload File
                        </button>
                    </div>
                </form>

                <!-- Progress Bar -->
                <div id="progress-container" class="progress-container hidden">
                    <div class="progress-bar">
                        <div id="progress-fill" class="progress-fill"></div>
                    </div>
                    <span id="progress-text" class="progress-text">Uploading...</span>
                </div>
            </div>

            <!-- Result Panel -->
            <div id="result-panel" class="result-panel hidden">
                <div id="result-content"></div>
            </div>

            <!-- Upload History -->
            <div class="history-card">
                <h3>Recent Uploads (This Session)</h3>
                <div id="history-list" class="history-list">
                    <p class="history-empty">No uploads yet</p>
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for upload interface."""
        return """
        /* Upload card */
        .upload-card {
            background: white;
            padding: 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-left: 4px solid var(--ds-blue-primary);
            margin-bottom: 20px;
        }

        /* Form groups */
        .form-group {
            margin-bottom: 24px;
        }

        .form-group label {
            display: block;
            font-weight: 600;
            color: var(--ds-navy);
            margin-bottom: 8px;
            font-size: 14px;
        }

        .form-select, .form-input {
            width: 100%;
            padding: 12px 15px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            font-size: 14px;
            color: var(--ds-navy);
            background: white;
            transition: border-color 0.2s;
        }

        .form-select:focus, .form-input:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
        }

        .form-hint {
            display: block;
            font-size: 12px;
            color: var(--ds-gray);
            margin-top: 5px;
        }

        /* Drop zone */
        .drop-zone {
            border: 2px dashed var(--ds-gray-light);
            border-radius: 8px;
            padding: 40px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
            position: relative;
        }

        .drop-zone:hover, .drop-zone.drag-over {
            border-color: var(--ds-blue-primary);
            background: rgba(0, 113, 188, 0.05);
        }

        .drop-zone.drag-over {
            border-style: solid;
        }

        .drop-icon {
            font-size: 48px;
            color: var(--ds-gray);
            margin-bottom: 10px;
        }

        .drop-text {
            font-size: 16px;
            color: var(--ds-navy);
            margin-bottom: 5px;
        }

        .drop-hint {
            font-size: 12px;
            color: var(--ds-gray);
        }

        .file-input {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: pointer;
        }

        /* Selected file info */
        .file-info {
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 15px;
            background: var(--ds-bg);
            border-radius: 3px;
            margin-top: 15px;
        }

        .file-info .file-icon {
            font-size: 24px;
            color: var(--ds-blue-primary);
        }

        .file-details {
            flex: 1;
        }

        .file-info .file-name {
            display: block;
            font-weight: 600;
            color: var(--ds-navy);
        }

        .file-info .file-size {
            font-size: 12px;
            color: var(--ds-gray);
        }

        .clear-button {
            background: none;
            border: none;
            font-size: 18px;
            color: var(--ds-gray);
            cursor: pointer;
            padding: 5px;
        }

        .clear-button:hover {
            color: #dc2626;
        }

        /* Submit button */
        .form-actions {
            margin-top: 20px;
        }

        .upload-button {
            width: 100%;
            padding: 15px 30px;
            background: var(--ds-blue-primary);
            color: white;
            border: none;
            border-radius: 3px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }

        .upload-button:hover:not(:disabled) {
            background: var(--ds-cyan);
        }

        .upload-button:disabled {
            background: var(--ds-gray-light);
            color: var(--ds-gray);
            cursor: not-allowed;
        }

        /* Progress bar */
        .progress-container {
            margin-top: 20px;
        }

        .progress-bar {
            height: 8px;
            background: var(--ds-gray-light);
            border-radius: 4px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            background: var(--ds-blue-primary);
            border-radius: 4px;
            width: 0%;
            transition: width 0.3s;
        }

        .progress-text {
            display: block;
            text-align: center;
            margin-top: 8px;
            font-size: 13px;
            color: var(--ds-gray);
        }

        /* Result panel */
        .result-panel {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }

        .result-success {
            border-left: 4px solid #059669;
        }

        .result-error {
            border-left: 4px solid #dc2626;
        }

        .result-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 15px;
        }

        .result-success .result-title {
            color: #059669;
        }

        .result-error .result-title {
            color: #dc2626;
        }

        .result-detail {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid var(--ds-gray-light);
            font-size: 13px;
        }

        .result-detail:last-child {
            border-bottom: none;
        }

        .result-label {
            color: var(--ds-gray);
        }

        .result-value {
            color: var(--ds-navy);
            font-family: monospace;
        }

        /* History card */
        .history-card {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .history-card h3 {
            font-size: 16px;
            color: var(--ds-navy);
            margin: 0 0 15px 0;
        }

        .history-list {
            max-height: 300px;
            overflow-y: auto;
        }

        .history-empty {
            color: var(--ds-gray);
            font-size: 13px;
            text-align: center;
            padding: 20px;
        }

        .history-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        .history-item:last-child {
            border-bottom: none;
        }

        .history-path {
            font-family: monospace;
            font-size: 13px;
            color: var(--ds-navy);
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .history-size {
            font-size: 12px;
            color: var(--ds-gray);
            margin-left: 15px;
        }

        .history-status {
            margin-left: 10px;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate JavaScript for upload functionality."""
        return """
        // Session upload history
        const uploadHistory = [];

        // Load containers on page load
        document.addEventListener('DOMContentLoaded', loadContainers);

        async function loadContainers() {
            const select = document.getElementById('container-select');

            try {
                const data = await fetchJSON(`${API_BASE_URL}/api/storage/containers?zone=bronze`);
                const bronzeData = data.zones?.bronze;

                if (!bronzeData || bronzeData.error) {
                    select.innerHTML = '<option value="">Bronze storage not configured</option>';
                    return;
                }

                const containers = bronzeData.containers || [];
                if (containers.length === 0) {
                    select.innerHTML = '<option value="">No bronze containers found</option>';
                    return;
                }

                // Populate container dropdown
                const options = containers.map(c =>
                    `<option value="${c}">${c}</option>`
                );
                select.innerHTML = '<option value="">Select a container...</option>' + options.join('');

            } catch (error) {
                console.error('Error loading containers:', error);
                select.innerHTML = '<option value="">Error loading containers</option>';
            }
        }

        // File input handling
        const dropZone = document.getElementById('drop-zone');
        const fileInput = document.getElementById('file-input');
        const fileInfo = document.getElementById('file-info');
        const fileName = document.getElementById('file-name');
        const fileSize = document.getElementById('file-size');
        const uploadBtn = document.getElementById('upload-btn');
        const clearBtn = document.getElementById('clear-file');

        // Drag and drop events
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');

            if (e.dataTransfer.files.length > 0) {
                fileInput.files = e.dataTransfer.files;
                handleFileSelect();
            }
        });

        fileInput.addEventListener('change', handleFileSelect);

        function handleFileSelect() {
            const file = fileInput.files[0];

            if (file) {
                // Check file size (100MB max)
                if (file.size > 100 * 1024 * 1024) {
                    alert('File too large. Maximum size is 100 MB.');
                    fileInput.value = '';
                    return;
                }

                fileName.textContent = file.name;
                fileSize.textContent = formatFileSize(file.size);
                fileInfo.classList.remove('hidden');
                dropZone.style.display = 'none';
                updateUploadButton();
            }
        }

        clearBtn.addEventListener('click', () => {
            fileInput.value = '';
            fileInfo.classList.add('hidden');
            dropZone.style.display = 'block';
            updateUploadButton();
        });

        function formatFileSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
        }

        function updateUploadButton() {
            const container = document.getElementById('container-select').value;
            const file = fileInput.files[0];
            uploadBtn.disabled = !container || !file;
        }

        document.getElementById('container-select').addEventListener('change', updateUploadButton);

        // Form submission
        document.getElementById('upload-form').addEventListener('submit', async (e) => {
            e.preventDefault();

            const container = document.getElementById('container-select').value;
            const path = document.getElementById('path-input').value;
            const file = fileInput.files[0];

            if (!container || !file) {
                alert('Please select a container and file');
                return;
            }

            // Show progress
            const progressContainer = document.getElementById('progress-container');
            const progressFill = document.getElementById('progress-fill');
            const progressText = document.getElementById('progress-text');
            const resultPanel = document.getElementById('result-panel');

            progressContainer.classList.remove('hidden');
            resultPanel.classList.add('hidden');
            uploadBtn.disabled = true;

            // Build form data
            const formData = new FormData();
            formData.append('file', file);
            formData.append('container', container);
            if (path) {
                formData.append('path', path);
            }

            try {
                // Use XMLHttpRequest for progress tracking
                const xhr = new XMLHttpRequest();

                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        progressFill.style.width = percent + '%';
                        progressText.textContent = `Uploading... ${percent}%`;
                    }
                });

                xhr.addEventListener('load', () => {
                    progressContainer.classList.add('hidden');

                    try {
                        const result = JSON.parse(xhr.responseText);

                        if (xhr.status === 200 && result.success) {
                            showResult(true, result);
                            addToHistory(result.upload);
                            resetForm();
                        } else {
                            showResult(false, result);
                        }
                    } catch (e) {
                        showResult(false, { error: 'Invalid response', message: xhr.responseText });
                    }

                    uploadBtn.disabled = false;
                });

                xhr.addEventListener('error', () => {
                    progressContainer.classList.add('hidden');
                    showResult(false, { error: 'Network error', message: 'Failed to connect to server' });
                    uploadBtn.disabled = false;
                });

                xhr.open('POST', `${API_BASE_URL}/api/storage/upload`);
                xhr.send(formData);

            } catch (error) {
                progressContainer.classList.add('hidden');
                showResult(false, { error: 'Upload failed', message: error.message });
                uploadBtn.disabled = false;
            }
        });

        function showResult(success, data) {
            const panel = document.getElementById('result-panel');
            const content = document.getElementById('result-content');

            panel.classList.remove('hidden', 'result-success', 'result-error');
            panel.classList.add(success ? 'result-success' : 'result-error');

            if (success) {
                const upload = data.upload || {};
                content.innerHTML = `
                    <div class="result-title">Upload Successful</div>
                    <div class="result-detail">
                        <span class="result-label">Container</span>
                        <span class="result-value">${upload.container || ''}</span>
                    </div>
                    <div class="result-detail">
                        <span class="result-label">Path</span>
                        <span class="result-value">${upload.path || ''}</span>
                    </div>
                    <div class="result-detail">
                        <span class="result-label">Size</span>
                        <span class="result-value">${upload.size_mb || 0} MB</span>
                    </div>
                    <div class="result-detail">
                        <span class="result-label">Storage Account</span>
                        <span class="result-value">${data.storage?.account || ''}</span>
                    </div>
                    <div class="result-detail">
                        <span class="result-label">Upload Time</span>
                        <span class="result-value">${data.upload_time_seconds || 0}s</span>
                    </div>
                `;
            } else {
                content.innerHTML = `
                    <div class="result-title">Upload Failed</div>
                    <div class="result-detail">
                        <span class="result-label">Error</span>
                        <span class="result-value">${data.error || 'Unknown error'}</span>
                    </div>
                    ${data.message ? `
                    <div class="result-detail">
                        <span class="result-label">Details</span>
                        <span class="result-value">${data.message}</span>
                    </div>
                    ` : ''}
                    ${data.hint ? `
                    <div class="result-detail">
                        <span class="result-label">Hint</span>
                        <span class="result-value">${data.hint}</span>
                    </div>
                    ` : ''}
                `;
            }
        }

        function addToHistory(upload) {
            uploadHistory.unshift(upload);

            const list = document.getElementById('history-list');
            list.innerHTML = uploadHistory.map(u => `
                <div class="history-item">
                    <span class="history-path" title="${u.container}/${u.path}">${u.container}/${u.path}</span>
                    <span class="history-size">${u.size_mb} MB</span>
                    <span class="history-status" style="color: #059669;">OK</span>
                </div>
            `).join('');
        }

        function resetForm() {
            fileInput.value = '';
            document.getElementById('path-input').value = '';
            fileInfo.classList.add('hidden');
            dropZone.style.display = 'block';
            document.getElementById('progress-fill').style.width = '0%';
            updateUploadButton();
        }
        """
