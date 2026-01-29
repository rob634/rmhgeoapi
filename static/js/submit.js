/* ============================================================================
   UNIFIED SUBMIT INTERFACE - JavaScript
   ============================================================================
   Handles file selection, type detection, form validation, and submission.
   Phase 4: UI Migration
   ============================================================================ */

// ============================================================================
// State Management
// ============================================================================

const SubmitState = {
    fileSource: 'browse',        // 'browse' or 'upload'
    selectedFile: null,          // { name, container, zone, size, extension, category }
    detectedType: null,          // File type info from FILE_TYPES
    formValid: false
};

// ============================================================================
// File Source Selection
// ============================================================================

/**
 * Set the file source (browse or upload)
 */
function setFileSource(source, element) {
    SubmitState.fileSource = source;

    // Update UI
    document.querySelectorAll('.source-option').forEach(opt => {
        opt.classList.remove('active');
    });
    element.classList.add('active');

    // Clear any existing selection
    clearSelection();
}

// ============================================================================
// File Browser Functions
// ============================================================================

/**
 * Called when container dropdown changes
 */
function containerChanged() {
    const container = document.getElementById('browser-container')?.value;
    const loadBtn = document.getElementById('load-files-btn');

    if (loadBtn) {
        loadBtn.disabled = !container;
    }
}

/**
 * Prepare for file load (show table, hide empty state)
 */
function prepareFileLoad() {
    const table = document.getElementById('files-table');
    const initialState = document.getElementById('files-initial-state');
    const emptyState = document.getElementById('files-empty-state');

    if (table) table.classList.remove('hidden');
    if (initialState) initialState.classList.add('hidden');
    if (emptyState) emptyState.classList.add('hidden');
}

/**
 * Select a file from the browser table
 */
function selectFile(blobName, container, zone, sizeMb) {
    // Get file extension
    const extension = getFileExtension(blobName);

    // Store selection
    SubmitState.selectedFile = {
        name: blobName,
        container: container,
        zone: zone,
        size: sizeMb,
        extension: extension
    };

    // Detect file type
    detectFileType(extension);

    // Update UI
    highlightSelectedRow(blobName);
    showSelectedFile();
    updateForm();
}

/**
 * Highlight the selected row in the files table
 */
function highlightSelectedRow(blobName) {
    document.querySelectorAll('.files-table tbody tr').forEach(row => {
        row.classList.remove('selected');
        if (row.dataset.blob === blobName) {
            row.classList.add('selected');
        }
    });
}

// ============================================================================
// File Upload Functions
// ============================================================================

// Initialize upload handlers when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initUploadHandlers();
});

/**
 * Initialize file upload event handlers
 */
function initUploadHandlers() {
    const dropZone = document.getElementById('upload-drop-zone');
    const fileInput = document.getElementById('upload-file-input');

    if (!dropZone || !fileInput) return;

    // Drag and drop handlers
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

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });

    // File input change handler
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });
}

/**
 * Handle file selection from upload
 */
function handleFileSelect(file) {
    const sizeMb = file.size / (1024 * 1024);
    const extension = getFileExtension(file.name);

    // Validate file size (1GB limit for direct upload - admin/testing use)
    if (sizeMb > 1024) {
        showUploadError('File too large. Maximum size is 1 GB.');
        return;
    }

    // Validate extension
    if (!FILE_TYPES[extension]) {
        showUploadError(`Unsupported file type: .${extension}`);
        return;
    }

    // Store selection
    SubmitState.selectedFile = {
        name: file.name,
        container: null, // Will be set after upload
        zone: 'bronze',
        size: sizeMb,
        extension: extension,
        file: file // Keep file reference for upload
    };

    // Show preview
    showUploadPreview(file.name, sizeMb);

    // Enable upload button
    const uploadBtn = document.getElementById('upload-btn');
    if (uploadBtn) uploadBtn.disabled = false;
}

/**
 * Show upload preview
 */
function showUploadPreview(name, sizeMb) {
    const preview = document.getElementById('upload-preview');
    const dropZone = document.getElementById('upload-drop-zone');

    if (preview) {
        document.getElementById('upload-preview-name').textContent = name;
        document.getElementById('upload-preview-size').textContent = formatFileSize(sizeMb);
        preview.classList.remove('hidden');
    }

    if (dropZone) {
        dropZone.classList.add('hidden');
    }
}

/**
 * Clear upload selection
 */
function clearUpload() {
    const preview = document.getElementById('upload-preview');
    const dropZone = document.getElementById('upload-drop-zone');
    const fileInput = document.getElementById('upload-file-input');
    const uploadBtn = document.getElementById('upload-btn');

    if (preview) preview.classList.add('hidden');
    if (dropZone) dropZone.classList.remove('hidden');
    if (fileInput) fileInput.value = '';
    if (uploadBtn) uploadBtn.disabled = true;

    SubmitState.selectedFile = null;
}

/**
 * Upload file to blob storage
 */
async function uploadFile() {
    const file = SubmitState.selectedFile?.file;
    const container = document.getElementById('upload-container')?.value;
    const path = document.getElementById('upload-path')?.value;

    if (!file || !container) {
        showUploadError('Please select a file and container.');
        return;
    }

    const uploadBtn = document.getElementById('upload-btn');
    const progress = document.getElementById('upload-progress');
    const progressFill = document.getElementById('upload-progress-fill');
    const progressText = document.getElementById('upload-progress-text');

    // Show progress
    if (uploadBtn) uploadBtn.disabled = true;
    if (progress) progress.classList.remove('hidden');

    try {
        // Create form data
        const formData = new FormData();
        formData.append('file', file);
        formData.append('container', container);
        if (path) formData.append('path', path);

        // Upload with progress
        const xhr = new XMLHttpRequest();

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                if (progressFill) progressFill.style.width = `${percent}%`;
                if (progressText) progressText.textContent = `${percent}%`;
            }
        };

        xhr.onload = () => {
            if (xhr.status === 200) {
                const result = JSON.parse(xhr.responseText);
                handleUploadSuccess(result, container);
            } else {
                showUploadError(`Upload failed: ${xhr.statusText}`);
            }
        };

        xhr.onerror = () => {
            showUploadError('Upload failed. Network error.');
        };

        xhr.open('POST', '/interface/submit/upload');
        xhr.send(formData);

    } catch (error) {
        showUploadError(`Upload failed: ${error.message}`);
    }
}

/**
 * Handle successful upload
 */
function handleUploadSuccess(result, container) {
    const blobName = result.blob_name || result.path;

    // Update state with blob reference
    SubmitState.selectedFile.container = container;
    SubmitState.selectedFile.name = blobName;
    delete SubmitState.selectedFile.file; // No longer need file reference

    // Detect type and update form
    detectFileType(SubmitState.selectedFile.extension);
    showSelectedFile();
    updateForm();

    // Show success message
    const uploadResult = document.getElementById('upload-result');
    if (uploadResult) {
        uploadResult.innerHTML = `
            <div class="type-notice type-notice-info">
                <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
                <span>File uploaded successfully! Complete the form below to submit.</span>
            </div>
        `;
        uploadResult.classList.remove('hidden');
    }
}

/**
 * Show upload error
 */
function showUploadError(message) {
    const uploadResult = document.getElementById('upload-result');
    if (uploadResult) {
        uploadResult.innerHTML = `
            <div class="type-notice type-notice-warning">
                <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/></svg>
                <span>${message}</span>
            </div>
        `;
        uploadResult.classList.remove('hidden');
    }

    // Re-enable upload button
    const uploadBtn = document.getElementById('upload-btn');
    if (uploadBtn) uploadBtn.disabled = false;

    // Hide progress
    const progress = document.getElementById('upload-progress');
    if (progress) progress.classList.add('hidden');
}

// ============================================================================
// File Type Detection
// ============================================================================

/**
 * Detect file type from extension
 */
function detectFileType(extension) {
    const ext = extension.toLowerCase();
    const typeInfo = FILE_TYPES[ext];

    if (typeInfo) {
        SubmitState.detectedType = {
            extension: ext,
            ...typeInfo
        };
    } else {
        SubmitState.detectedType = {
            extension: ext,
            category: 'unknown',
            name: ext.toUpperCase(),
            description: 'Unknown file type'
        };
    }

    // Update hidden field
    const dataTypeField = document.getElementById('data_type');
    if (dataTypeField) {
        dataTypeField.value = SubmitState.detectedType.category;
    }
}

/**
 * Get file extension from filename
 */
function getFileExtension(filename) {
    const parts = filename.split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

// ============================================================================
// Selected File Display
// ============================================================================

/**
 * Show the selected file section with details
 */
function showSelectedFile() {
    const section = document.getElementById('selected-file-section');
    const file = SubmitState.selectedFile;
    const type = SubmitState.detectedType;

    if (!section || !file) return;

    // Update display elements
    document.getElementById('display-file-name').textContent = getShortName(file.name);
    document.getElementById('display-file-size').textContent = formatFileSize(file.size);
    document.getElementById('display-file-type').textContent = type?.name || file.extension.toUpperCase();

    // Update detected type display
    const detectedValue = document.getElementById('detected-type-value');
    const detectedDesc = document.getElementById('detected-type-description');

    if (detectedValue && type) {
        detectedValue.textContent = type.category === 'raster' ? 'RASTER' : 'VECTOR';
        detectedValue.className = `detected-value ${type.category}`;
    }

    if (detectedDesc && type) {
        detectedDesc.textContent = type.description;
    }

    // Show type-specific messages
    showTypeMessages();

    // Show the section
    section.classList.remove('hidden');
}

/**
 * Show type-specific messages (ZIP notice, size warning)
 */
function showTypeMessages() {
    const file = SubmitState.selectedFile;

    // ZIP notice
    const zipNotice = document.getElementById('zip-notice');
    if (zipNotice) {
        if (file.extension === 'zip') {
            zipNotice.classList.remove('hidden');
        } else {
            zipNotice.classList.add('hidden');
        }
    }

    // Size warning (>1GB)
    const sizeWarning = document.getElementById('size-warning');
    if (sizeWarning) {
        if (file.size > 1024) {
            sizeWarning.classList.remove('hidden');
        } else {
            sizeWarning.classList.add('hidden');
        }
    }
}

/**
 * Clear file selection
 */
function clearSelection() {
    SubmitState.selectedFile = null;
    SubmitState.detectedType = null;

    // Hide selected file section
    const section = document.getElementById('selected-file-section');
    if (section) section.classList.add('hidden');

    // Clear table selection
    document.querySelectorAll('.files-table tbody tr').forEach(row => {
        row.classList.remove('selected');
    });

    // Clear hidden fields
    document.getElementById('blob_name').value = '';
    document.getElementById('container_name').value = '';
    document.getElementById('file_extension').value = '';
    document.getElementById('file_size_mb').value = '';
    document.getElementById('data_type').value = '';

    // Hide conditional sections
    document.getElementById('csv-fields')?.classList.add('hidden');
    document.getElementById('vector-fields')?.classList.add('hidden');
    document.getElementById('raster-fields')?.classList.add('hidden');
    document.getElementById('docker-option')?.classList.add('hidden');

    // Disable submit
    document.getElementById('submit-btn').disabled = true;

    // Clear cURL preview
    updateCurlPreview();
}

// ============================================================================
// Form Updates
// ============================================================================

/**
 * Update form based on selection
 */
function updateForm() {
    const file = SubmitState.selectedFile;
    const type = SubmitState.detectedType;

    if (!file || !type) return;

    // Update hidden fields
    document.getElementById('blob_name').value = file.name;
    document.getElementById('container_name').value = file.container || '';
    document.getElementById('storage_zone').value = file.zone;
    document.getElementById('file_extension').value = file.extension;
    document.getElementById('file_size_mb').value = file.size.toFixed(2);

    // Show/hide conditional sections based on type
    const csvFields = document.getElementById('csv-fields');
    const vectorFields = document.getElementById('vector-fields');
    const rasterFields = document.getElementById('raster-fields');
    const dockerOption = document.getElementById('docker-option');

    if (type.category === 'vector') {
        // Show vector configuration for all vector types
        if (vectorFields) vectorFields.classList.remove('hidden');
        if (csvFields) {
            if (file.extension === 'csv') {
                csvFields.classList.remove('hidden');
            } else {
                csvFields.classList.add('hidden');
            }
        }
        if (rasterFields) rasterFields.classList.add('hidden');
        if (dockerOption) dockerOption.classList.add('hidden');
    } else if (type.category === 'raster') {
        if (csvFields) csvFields.classList.add('hidden');
        if (vectorFields) vectorFields.classList.add('hidden');
        if (rasterFields) rasterFields.classList.remove('hidden');
        if (dockerOption) {
            // Show Docker option for raster or large files
            dockerOption.classList.remove('hidden');
            if (file.size > 500) {
                document.getElementById('use_docker').checked = true;
                updateProcessingModeLabel();
            }
        }
    }

    // Update cURL preview
    updateCurlPreview();

    // Validate form
    validateForm();
}

/**
 * Validate the form and enable/disable submit button
 */
function validateForm() {
    const file = SubmitState.selectedFile;
    const type = SubmitState.detectedType;

    if (!file) {
        SubmitState.formValid = false;
        document.getElementById('submit-btn').disabled = true;
        return;
    }

    // Check required fields
    const datasetId = document.getElementById('dataset_id')?.value?.trim();
    const resourceId = document.getElementById('resource_id')?.value?.trim();
    // Note: title is optional - auto-generated from DDH IDs if not provided

    let valid = datasetId && resourceId;

    // Check raster-specific required fields
    if (type?.category === 'raster') {
        const collectionId = document.getElementById('raster_collection_id')?.value?.trim();
        valid = valid && collectionId;
    }

    // Check CSV geometry fields (either lat/lon or WKT required)
    if (file.extension === 'csv') {
        const latCol = document.getElementById('lat_column')?.value?.trim();
        const lonCol = document.getElementById('lon_column')?.value?.trim();
        const wktCol = document.getElementById('wkt_column')?.value?.trim();
        valid = valid && ((latCol && lonCol) || wktCol);
    }

    SubmitState.formValid = valid;
    document.getElementById('submit-btn').disabled = !valid;
}

// Add input listeners for validation
document.addEventListener('DOMContentLoaded', () => {
    const formInputs = [
        'dataset_id', 'resource_id', 'title',
        'raster_collection_id', 'lat_column', 'lon_column', 'wkt_column',
        'table_name'
    ];

    formInputs.forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('input', () => {
                validateForm();
                updateCurlPreview();
            });
        }
    });
});

// ============================================================================
// cURL Preview
// ============================================================================

/**
 * Update the cURL command preview
 */
function updateCurlPreview() {
    const curlElement = document.getElementById('curl-command');
    if (!curlElement) return;

    const file = SubmitState.selectedFile;
    const type = SubmitState.detectedType;

    if (!file) {
        curlElement.textContent = 'Select a file to see the cURL command';
        return;
    }

    // Get form values
    const datasetId = document.getElementById('dataset_id')?.value?.trim() || '<dataset_id>';
    const resourceId = document.getElementById('resource_id')?.value?.trim() || '<resource_id>';
    const versionId = document.getElementById('version_id')?.value?.trim() || 'v1.0';
    const title = document.getElementById('title')?.value?.trim() || '';
    const description = document.getElementById('description')?.value?.trim() || '';
    const overwrite = document.getElementById('overwrite')?.checked || false;

    // Build request body
    const body = {
        dataset_id: datasetId,
        resource_id: resourceId,
        version_id: versionId,
        blob_name: file.name,
        container_name: file.container || '<container>',
        overwrite: overwrite
    };

    if (title) body.title = title;
    if (description) body.description = description;

    // Add type-specific fields
    if (type?.category === 'raster') {
        const rasterType = document.getElementById('raster_type')?.value;
        const outputTier = document.getElementById('output_tier')?.value;
        const inputCrs = document.getElementById('input_crs')?.value?.trim();
        const collectionId = document.getElementById('raster_collection_id')?.value?.trim();
        const useDocker = document.getElementById('use_docker')?.checked;

        if (rasterType && rasterType !== 'auto') body.raster_type = rasterType;
        if (outputTier) body.output_tier = outputTier;
        if (inputCrs) body.input_crs = inputCrs;
        if (collectionId) body.collection_id = collectionId;
        if (useDocker) body.processing_mode = 'docker';
    } else if (type?.category === 'vector') {
        // Vector-specific fields
        const tableName = document.getElementById('table_name')?.value?.trim();
        if (tableName) body.table_name = tableName;

        // CSV-specific geometry fields
        if (file.extension === 'csv') {
            const latCol = document.getElementById('lat_column')?.value?.trim();
            const lonCol = document.getElementById('lon_column')?.value?.trim();
            const wktCol = document.getElementById('wkt_column')?.value?.trim();

            if (latCol) body.lat_column = latCol;
            if (lonCol) body.lon_column = lonCol;
            if (wktCol) body.wkt_column = wktCol;
        }
    }

    // Determine endpoint
    const endpoint = type?.category === 'raster' ? '/api/platform/raster' : '/api/platform/vector';

    // Build cURL command
    const curl = `curl -X POST '${window.location.origin}${endpoint}' \\
  -H 'Content-Type: application/json' \\
  -d '${JSON.stringify(body, null, 2)}'`;

    curlElement.textContent = curl;
}

/**
 * Copy cURL command to clipboard
 */
function copyCurl(elementId) {
    const element = document.getElementById(elementId || 'curl-command');
    if (!element) return;

    navigator.clipboard.writeText(element.textContent).then(() => {
        // Show feedback
        const copyBtn = element.parentElement?.querySelector('.btn-copy');
        if (copyBtn) {
            const originalText = copyBtn.innerHTML;
            copyBtn.innerHTML = 'Copied!';
            setTimeout(() => {
                copyBtn.innerHTML = originalText;
            }, 2000);
        }
    });
}

/**
 * Update processing mode label
 */
function updateProcessingModeLabel() {
    const checkbox = document.getElementById('use_docker');
    const label = document.getElementById('processing-mode-label');

    if (label) {
        label.textContent = checkbox?.checked ? 'Docker Worker (recommended for large files)' : 'Function App (default)';
    }
}

// ============================================================================
// Utility Functions
// ============================================================================

/**
 * Get short name from full blob path
 */
function getShortName(fullPath) {
    if (!fullPath) return '';
    const parts = fullPath.split('/');
    return parts[parts.length - 1];
}

/**
 * Format file size in human-readable format
 */
function formatFileSize(sizeMb) {
    if (sizeMb >= 1024) {
        return `${(sizeMb / 1024).toFixed(2)} GB`;
    } else if (sizeMb >= 1) {
        return `${sizeMb.toFixed(2)} MB`;
    } else {
        return `${(sizeMb * 1024).toFixed(0)} KB`;
    }
}

// ============================================================================
// HTMX Event Handlers
// ============================================================================

// Handle HTMX after swap events
document.body.addEventListener('htmx:afterSwap', (event) => {
    // Re-initialize handlers after content swap
    if (event.target.id === 'file-source-content') {
        initUploadHandlers();
    }
});
