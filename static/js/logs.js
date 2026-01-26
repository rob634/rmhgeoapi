/**
 * Logs Page JavaScript (GAP-03)
 * Application Insights log viewer functionality.
 * Created: 25 JAN 2026
 */

// ============================================================================
// STATE
// ============================================================================

let currentLogs = [];
let isLoading = false;

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Check for job_id in URL params
    const urlParams = new URLSearchParams(window.location.search);
    const jobId = urlParams.get('job_id');
    if (jobId) {
        document.getElementById('job-id').value = jobId;
    }

    // Initial load
    refreshLogs();
});

// ============================================================================
// DATA FETCHING
// ============================================================================

async function refreshLogs() {
    if (isLoading) return;
    isLoading = true;

    const refreshBtn = document.getElementById('refresh-btn');
    const logsBody = document.getElementById('logs-body');
    const summary = document.getElementById('logs-summary');
    const statusBanner = document.getElementById('status-banner');

    // Update UI state
    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Loading...';
    statusBanner.classList.add('hidden');

    logsBody.innerHTML = `
        <tr class="loading-row">
            <td colspan="5">
                <div class="loading-indicator">
                    <div class="spinner"></div>
                    <span>Querying Application Insights...</span>
                </div>
            </td>
        </tr>
    `;

    summary.innerHTML = `
        <div class="summary-loading">
            <div class="spinner-sm"></div>
            <span>Loading logs...</span>
        </div>
    `;

    try {
        // Get filter values
        const timeRange = document.getElementById('time-range').value;
        const severity = document.getElementById('severity').value;
        const source = document.getElementById('source').value;
        const limit = document.getElementById('limit').value;
        const jobId = document.getElementById('job-id').value.trim();
        const searchText = document.getElementById('search-text').value.trim();

        // Build query params
        const params = new URLSearchParams({
            time_range: timeRange,
            severity: severity,
            source: source,
            limit: limit
        });

        if (jobId) params.append('job_id', jobId);
        if (searchText) params.append('search', searchText);

        // Fetch logs
        const response = await fetch(`${LOGS_API_URL}?${params}`, {
            method: 'GET',
            headers: { 'Accept': 'application/json' },
            signal: AbortSignal.timeout(60000)  // 60 second timeout
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || `HTTP ${response.status}`);
        }

        const data = await response.json();
        currentLogs = data.logs || [];

        // Render results
        renderSummary(data);
        renderLogs(currentLogs);
        updateLastRefreshed();

    } catch (error) {
        console.error('Error fetching logs:', error);
        showError(error.message);
        logsBody.innerHTML = `
            <tr class="empty-row">
                <td colspan="5">
                    <div class="empty-icon">&#x26A0;</div>
                    <div>Failed to load logs: ${escapeHtml(error.message)}</div>
                </td>
            </tr>
        `;
        summary.innerHTML = `
            <div class="summary-info" style="color: #DC2626;">
                Error loading logs
            </div>
        `;
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.textContent = 'Refresh';
        isLoading = false;
    }
}

// ============================================================================
// RENDERING
// ============================================================================

function renderSummary(data) {
    const summary = document.getElementById('logs-summary');

    const total = data.total || 0;
    const errors = data.error_count || 0;
    const warnings = data.warning_count || 0;
    const info = data.info_count || 0;

    summary.innerHTML = `
        <div class="summary-stats">
            <div class="summary-stat">
                <span class="stat-value">${formatNumber(total)}</span>
                <span class="stat-label">Total</span>
            </div>
            <div class="summary-stat errors">
                <span class="stat-value">${formatNumber(errors)}</span>
                <span class="stat-label">Errors</span>
            </div>
            <div class="summary-stat warnings">
                <span class="stat-value">${formatNumber(warnings)}</span>
                <span class="stat-label">Warnings</span>
            </div>
            <div class="summary-stat info">
                <span class="stat-value">${formatNumber(info)}</span>
                <span class="stat-label">Info</span>
            </div>
        </div>
        <div class="summary-info">
            Query: ${escapeHtml(data.query_time || 'N/A')} |
            Source: ${escapeHtml(data.source || 'Application Insights')}
        </div>
    `;
}

function renderLogs(logs) {
    const logsBody = document.getElementById('logs-body');

    if (!logs || logs.length === 0) {
        logsBody.innerHTML = `
            <tr class="empty-row">
                <td colspan="5">
                    <div class="empty-icon">&#x1F4ED;</div>
                    <div>No logs found matching your filters</div>
                    <div style="margin-top: 10px; font-size: 12px;">
                        Try adjusting the time range or filters
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    logsBody.innerHTML = logs.map((log, index) => renderLogRow(log, index)).join('');
}

function renderLogRow(log, index) {
    const timestamp = formatTimestamp(log.timestamp);
    const severity = getSeverityInfo(log.severity_level);
    const source = getSourceInfo(log.source);
    const message = highlightIds(escapeHtml(truncateMessage(log.message, 200)));

    return `
        <tr class="log-row severity-${severity.class}" data-index="${index}">
            <td class="col-time">
                <span class="log-timestamp">${timestamp}</span>
            </td>
            <td class="col-severity">
                <span class="severity-badge ${severity.class}">${severity.label}</span>
            </td>
            <td class="col-source">
                <span class="source-badge ${source.class}">${source.label}</span>
            </td>
            <td class="col-message">
                <div class="log-message">${message}</div>
            </td>
            <td class="col-actions">
                <button class="btn btn-sm btn-secondary btn-view" onclick="showLogDetail(${index})">
                    View
                </button>
            </td>
        </tr>
    `;
}

function getSeverityInfo(level) {
    const severities = {
        0: { label: 'VERBOSE', class: 'verbose' },
        1: { label: 'INFO', class: 'info' },
        2: { label: 'WARNING', class: 'warning' },
        3: { label: 'ERROR', class: 'error' },
        4: { label: 'CRITICAL', class: 'critical' }
    };
    return severities[level] || { label: 'UNKNOWN', class: 'verbose' };
}

function getSourceInfo(source) {
    const sources = {
        'traces': { label: 'Trace', class: 'traces' },
        'requests': { label: 'Request', class: 'requests' },
        'exceptions': { label: 'Exception', class: 'exceptions' },
        'dependencies': { label: 'Dependency', class: 'dependencies' }
    };
    return sources[source] || { label: source || 'Unknown', class: '' };
}

// ============================================================================
// LOG DETAIL MODAL
// ============================================================================

function showLogDetail(index) {
    const log = currentLogs[index];
    if (!log) return;

    const modal = document.getElementById('log-detail-modal');
    const content = document.getElementById('log-detail-content');

    const severity = getSeverityInfo(log.severity_level);
    const source = getSourceInfo(log.source);

    let detailsHtml = `
        <div class="detail-grid">
            <div class="detail-item">
                <div class="item-label">Timestamp</div>
                <div class="item-value">${formatTimestamp(log.timestamp, true)}</div>
            </div>
            <div class="detail-item">
                <div class="item-label">Severity</div>
                <div class="item-value">
                    <span class="severity-badge ${severity.class}">${severity.label}</span>
                </div>
            </div>
            <div class="detail-item">
                <div class="item-label">Source</div>
                <div class="item-value">
                    <span class="source-badge ${source.class}">${source.label}</span>
                </div>
            </div>
            ${log.operation_name ? `
            <div class="detail-item">
                <div class="item-label">Operation</div>
                <div class="item-value">${escapeHtml(log.operation_name)}</div>
            </div>
            ` : ''}
        </div>

        <div class="detail-section">
            <div class="detail-label">Message</div>
            <div class="detail-value monospace">${escapeHtml(log.message)}</div>
        </div>
    `;

    // Add custom dimensions if present
    if (log.custom_dimensions && Object.keys(log.custom_dimensions).length > 0) {
        detailsHtml += `
            <div class="detail-section">
                <div class="detail-label">Custom Dimensions</div>
                <div class="detail-value json">${JSON.stringify(log.custom_dimensions, null, 2)}</div>
            </div>
        `;
    }

    // Add exception details for exceptions
    if (log.source === 'exceptions' && log.details) {
        detailsHtml += `
            <div class="detail-section">
                <div class="detail-label">Exception Details</div>
                <div class="detail-value json">${escapeHtml(log.details)}</div>
            </div>
        `;
    }

    // Add request details for requests
    if (log.source === 'requests') {
        detailsHtml += `
            <div class="detail-grid">
                ${log.result_code ? `
                <div class="detail-item">
                    <div class="item-label">Status Code</div>
                    <div class="item-value">${log.result_code}</div>
                </div>
                ` : ''}
                ${log.duration ? `
                <div class="detail-item">
                    <div class="item-label">Duration</div>
                    <div class="item-value">${log.duration}ms</div>
                </div>
                ` : ''}
                ${log.success !== undefined ? `
                <div class="detail-item">
                    <div class="item-label">Success</div>
                    <div class="item-value">${log.success ? 'Yes' : 'No'}</div>
                </div>
                ` : ''}
            </div>
        `;
    }

    content.innerHTML = detailsHtml;
    modal.classList.remove('hidden');

    // Close on Escape key
    document.addEventListener('keydown', handleModalEscape);
}

function closeLogDetail() {
    const modal = document.getElementById('log-detail-modal');
    modal.classList.add('hidden');
    document.removeEventListener('keydown', handleModalEscape);
}

function handleModalEscape(e) {
    if (e.key === 'Escape') {
        closeLogDetail();
    }
}

// ============================================================================
// QUICK FILTERS
// ============================================================================

function applyQuickFilter(filter) {
    // Clear existing quick filter highlights
    document.querySelectorAll('.quick-filter').forEach(btn => {
        btn.classList.remove('active');
    });

    // Reset filters
    document.getElementById('search-text').value = '';
    document.getElementById('severity').value = '1';  // Info+

    switch (filter) {
        case 'errors':
            document.getElementById('severity').value = '3';  // Error+
            break;
        case 'jobs':
            document.getElementById('search-text').value = 'job_id';
            break;
        case 'tasks':
            document.getElementById('search-text').value = 'task_id OR Processing task';
            break;
        case 'servicebus':
            document.getElementById('search-text').value = 'Service Bus OR queue';
            break;
        case 'database':
            document.getElementById('search-text').value = 'PostgreSQL OR database OR SQL';
            break;
        case 'stac':
            document.getElementById('search-text').value = 'STAC OR collection OR pgstac';
            break;
    }

    // Highlight active filter
    event.target.classList.add('active');

    refreshLogs();
}

function clearFilters() {
    document.getElementById('time-range').value = '15m';
    document.getElementById('severity').value = '1';
    document.getElementById('source').value = 'all';
    document.getElementById('limit').value = '100';
    document.getElementById('job-id').value = '';
    document.getElementById('search-text').value = '';

    // Clear quick filter highlights
    document.querySelectorAll('.quick-filter').forEach(btn => {
        btn.classList.remove('active');
    });

    refreshLogs();
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function formatTimestamp(isoString, full = false) {
    if (!isoString) return 'N/A';
    try {
        const date = new Date(isoString);
        if (full) {
            return date.toLocaleString();
        }
        // Show time with milliseconds for logs
        const hours = String(date.getHours()).padStart(2, '0');
        const mins = String(date.getMinutes()).padStart(2, '0');
        const secs = String(date.getSeconds()).padStart(2, '0');
        const ms = String(date.getMilliseconds()).padStart(3, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${month}-${day} ${hours}:${mins}:${secs}.${ms}`;
    } catch {
        return isoString;
    }
}

function formatNumber(num) {
    if (num === undefined || num === null) return '0';
    return num.toLocaleString();
}

function truncateMessage(msg, maxLen) {
    if (!msg) return '';
    if (msg.length <= maxLen) return msg;
    return msg.substring(0, maxLen) + '...';
}

function highlightIds(text) {
    // Highlight job IDs (UUID format)
    text = text.replace(
        /\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b/gi,
        '<span class="job-id-highlight">$1</span>'
    );
    // Highlight short task IDs
    text = text.replace(
        /\b([0-9a-f]{8}-s\d+)\b/gi,
        '<span class="task-id-highlight">$1</span>'
    );
    return text;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showError(message) {
    const banner = document.getElementById('status-banner');
    banner.className = 'status-banner error';
    banner.innerHTML = `<strong>Error:</strong> ${escapeHtml(message)}`;
    banner.classList.remove('hidden');
}

function updateLastRefreshed() {
    const elem = document.getElementById('last-refreshed');
    if (elem) {
        const now = new Date();
        elem.textContent = `Last refreshed: ${now.toLocaleTimeString()}`;
    }
}
