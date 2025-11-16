# ============================================================================
# CLAUDE CONTEXT - JOB MONITOR INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE 
# STATUS: Web Interface - Job monitoring dashboard
# PURPOSE: Generate HTML dashboard for monitoring jobs and tasks in app.jobs
# LAST_REVIEWED: 15 NOV 2025
# EXPORTS: JobsInterface
# INTERFACES: BaseInterface
# PYDANTIC_MODELS: None
# DEPENDENCIES: web_interfaces.base, azure.functions
# SOURCE: Database admin API endpoints (/api/dbadmin/jobs, /api/dbadmin/tasks)
# SCOPE: Job and task monitoring
# VALIDATION: None (display only)
# PATTERNS: Template Method (inherits BaseInterface)
# ENTRY_POINTS: Registered as 'jobs' in InterfaceRegistry
# INDEX: JobsInterface:40, render:60, _generate_custom_css:150, _generate_custom_js:300
# ============================================================================

"""
Job Monitor Interface

Web interface for monitoring jobs and tasks from app.jobs table. Provides:
    - Jobs table with filtering and refresh
    - Stage progress (stage N/total)
    - Task counts by status (queued, processing, completed, failed)
    - Job detail view with task breakdown

Route: /api/interface/jobs

Author: Robert and Geospatial Claude Legion
Date: 15 NOV 2025
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('jobs')
class JobsInterface(BaseInterface):
    """
    Job Monitor Dashboard interface.

    Displays jobs from app.jobs table with task counts and status filtering.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Job Monitor dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """

        # HTML content
        content = self._generate_html_content()

        # Custom CSS for Job Monitor
        custom_css = self._generate_custom_css()

        # Custom JavaScript for Job Monitor
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Job Monitor Dashboard",
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
                <h1>⚙️ Job Monitor Dashboard</h1>
                <p class="subtitle">Monitor job execution and task progress from app.jobs table</p>
            </header>

            <!-- Controls -->
            <div class="controls">
                <button onclick="loadJobs()" class="refresh-button">
                    🔄 Refresh
                </button>
                <select id="status-filter" onchange="loadJobs()" class="filter-select">
                    <option value="">All Statuses</option>
                    <option value="queued">Queued</option>
                    <option value="processing">Processing</option>
                    <option value="completed">Completed</option>
                    <option value="failed">Failed</option>
                </select>
                <select id="limit-filter" onchange="loadJobs()" class="filter-select">
                    <option value="10">Last 10</option>
                    <option value="25" selected>Last 25</option>
                    <option value="50">Last 50</option>
                    <option value="100">Last 100</option>
                </select>
            </div>

            <!-- Loading State -->
            <div id="loading-spinner" class="spinner hidden"></div>

            <!-- Jobs Table -->
            <div id="jobs-container">
                <table class="jobs-table" id="jobs-table">
                    <thead>
                        <tr>
                            <th>Job ID</th>
                            <th>Type</th>
                            <th>Status</th>
                            <th>Stage</th>
                            <th>Tasks</th>
                            <th>Created</th>
                            <th>Updated</th>
                        </tr>
                    </thead>
                    <tbody id="jobs-tbody">
                        <!-- Jobs will be inserted here -->
                    </tbody>
                </table>

                <!-- Empty State -->
                <div id="empty-state" class="empty-state hidden">
                    <div class="icon">📭</div>
                    <h3>No Jobs Found</h3>
                    <p>No jobs match the current filters</p>
                </div>
            </div>

            <!-- Stats Banner -->
            <div id="stats-banner" class="stats-banner hidden">
                <div class="stat-item">
                    <span class="stat-label">Total Displayed</span>
                    <span class="stat-value" id="total-jobs">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Queued</span>
                    <span class="stat-value" id="total-queued">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Processing</span>
                    <span class="stat-value" id="total-processing">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Completed</span>
                    <span class="stat-value" id="total-completed">0</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Failed</span>
                    <span class="stat-value" id="total-failed">0</span>
                </div>
            </div>

            <!-- Job Detail View (hidden by default) -->
            <div id="job-detail-view" class="hidden">
                <button class="back-button" onclick="showJobsList()">
                    ← Back to Jobs
                </button>

                <div class="detail-header" id="detail-header">
                    <!-- Job header will be inserted here -->
                </div>

                <div class="detail-actions" id="detail-actions">
                    <!-- Action buttons will be inserted here -->
                </div>

                <div class="detail-parameters" id="detail-parameters">
                    <!-- Parameters will be inserted here -->
                </div>

                <div class="detail-results" id="detail-results">
                    <!-- Results will be inserted here -->
                </div>

                <div class="detail-tasks" id="detail-tasks">
                    <!-- Tasks will be inserted here -->
                </div>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Job Monitor."""
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
            gap: 15px;
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

        .filter-select {
            padding: 10px 15px;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            font-size: 14px;
            color: #053657;
            background: white;
            cursor: pointer;
            font-weight: 600;
        }

        .filter-select:focus {
            outline: none;
            border-color: #0071BC;
        }

        /* Jobs Table */
        .jobs-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 3px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .jobs-table thead {
            background: #f8f9fa;
        }

        .jobs-table th {
            text-align: left;
            padding: 15px;
            font-weight: 700;
            color: #053657;
            border-bottom: 2px solid #e9ecef;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .jobs-table td {
            padding: 12px 15px;
            border-bottom: 1px solid #e9ecef;
            color: #053657;
            font-size: 14px;
        }

        .jobs-table tbody tr:hover {
            background: #f8f9fa;
            cursor: pointer;
        }

        .job-id {
            font-family: 'Courier New', monospace;
            color: #0071BC;
            font-weight: 500;
            font-size: 12px;
        }

        .job-type {
            font-weight: 600;
            color: #053657;
        }

        /* Status badges */
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .status-queued {
            background: #e9ecef;
            color: #626F86;
        }

        .status-processing {
            background: #FFF4E6;
            color: #F59E0B;
        }

        .status-completed {
            background: #D1FAE5;
            color: #059669;
        }

        .status-failed {
            background: #FEE2E2;
            color: #DC2626;
        }

        /* Stage progress */
        .stage-progress {
            font-weight: 600;
            color: #0071BC;
        }

        /* Task counts */
        .task-counts {
            font-size: 12px;
            color: #626F86;
            line-height: 1.6;
        }

        .task-count-item {
            display: inline-block;
            margin-right: 10px;
        }

        .task-count-label {
            font-weight: 600;
            text-transform: uppercase;
            font-size: 11px;
        }

        /* Timestamp */
        .timestamp {
            color: #626F86;
            font-size: 12px;
        }

        /* Stats Banner */
        .stats-banner {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-top: 20px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
        }

        .stat-item {
            text-align: center;
            padding: 15px;
            border-radius: 3px;
            background: #f8f9fa;
        }

        .stat-label {
            display: block;
            font-size: 12px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .stat-value {
            display: block;
            font-size: 28px;
            color: #053657;
            font-weight: 700;
        }

        /* Empty State */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #626F86;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .empty-state .icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .empty-state h3 {
            color: #053657;
            margin-bottom: 10px;
        }

        /* Job Detail View */
        #job-detail-view {
            margin-top: 20px;
        }

        .back-button {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: white;
            border: 1px solid #e9ecef;
            color: #0071BC;
            border-radius: 3px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 20px;
            transition: all 0.2s;
        }

        .back-button:hover {
            background: #f8f9fa;
            border-color: #0071BC;
            color: #00A3DA;
        }

        .detail-header {
            background: white;
            border: 1px solid #e9ecef;
            border-left: 4px solid #0071BC;
            padding: 30px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .detail-header h2 {
            font-size: 20px;
            color: #053657;
            font-weight: 700;
            margin-bottom: 15px;
        }

        .detail-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }

        .meta-item {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            padding: 12px;
            border-radius: 3px;
        }

        .meta-item .label {
            font-size: 11px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }

        .meta-item .value {
            font-size: 14px;
            color: #053657;
            font-weight: 600;
        }

        .detail-actions {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .action-button {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: #0071BC;
            color: white;
            border: none;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            font-size: 14px;
        }

        .action-button:hover {
            background: #00A3DA;
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(0,113,188,0.3);
        }

        .action-button-secondary {
            background: white;
            color: #0071BC;
            border: 1px solid #e9ecef;
        }

        .action-button-secondary:hover {
            background: #f8f9fa;
            border-color: #0071BC;
        }

        .detail-parameters,
        .detail-results,
        .detail-tasks {
            background: white;
            padding: 25px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }

        .section-title {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e9ecef;
        }

        .params-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
        }

        .param-item {
            padding: 12px;
            background: #f8f9fa;
            border-radius: 3px;
            border: 1px solid #e9ecef;
        }

        .param-label {
            font-size: 12px;
            font-weight: 600;
            color: #626F86;
            margin-bottom: 5px;
        }

        .param-value {
            font-size: 13px;
            color: #053657;
            font-family: 'Courier New', monospace;
            word-break: break-word;
        }

        .result-card {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-left: 4px solid #0071BC;
            padding: 20px;
            border-radius: 3px;
            margin-bottom: 15px;
        }

        .result-card h4 {
            font-size: 14px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 12px;
        }

        .result-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
        }

        .result-item {
            font-size: 13px;
            color: #626F86;
        }

        .result-item strong {
            color: #0071BC;
            font-weight: 600;
        }

        .stage-group {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 15px;
            margin-bottom: 15px;
        }

        .stage-group-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            padding: 5px 0;
        }

        .stage-group-header h4 {
            font-size: 14px;
            font-weight: 700;
            color: #053657;
        }

        .stage-tasks {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e9ecef;
        }

        .task-item {
            background: white;
            border: 1px solid #e9ecef;
            padding: 12px;
            border-radius: 3px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .task-item .task-info {
            flex: 1;
        }

        .task-item .task-id {
            font-size: 12px;
            font-family: 'Courier New', monospace;
            color: #626F86;
        }

        .task-item .task-type {
            font-size: 13px;
            font-weight: 600;
            color: #053657;
            margin: 3px 0;
        }

        .error-banner {
            background: #FEE2E2;
            border: 1px solid #DC2626;
            border-left: 4px solid #DC2626;
            padding: 20px;
            border-radius: 3px;
            margin-bottom: 20px;
        }

        .error-banner h3 {
            color: #DC2626;
            font-size: 16px;
            font-weight: 700;
            margin-bottom: 10px;
        }

        .error-banner p {
            color: #991B1B;
            font-size: 14px;
            line-height: 1.6;
        }

        .expandable-json {
            margin-top: 15px;
        }

        .expandable-json summary {
            cursor: pointer;
            font-weight: 600;
            color: #0071BC;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 3px;
            user-select: none;
        }

        .expandable-json pre {
            background: #053657;
            color: #f8f9fa;
            padding: 15px;
            border-radius: 3px;
            overflow-x: auto;
            font-size: 12px;
            margin-top: 10px;
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for Job Monitor."""
        return """
        // Load jobs on page load
        document.addEventListener('DOMContentLoaded', loadJobs);

        // Load jobs from API
        async function loadJobs() {
            const tbody = document.getElementById('jobs-tbody');
            const table = document.getElementById('jobs-table');
            const spinner = document.getElementById('loading-spinner');
            const emptyState = document.getElementById('empty-state');
            const statsBanner = document.getElementById('stats-banner');

            // Get filters
            const statusFilter = document.getElementById('status-filter').value;
            const limit = document.getElementById('limit-filter').value;

            // Build query params
            const params = new URLSearchParams({ limit });
            if (statusFilter) params.append('status', statusFilter);

            // Show loading
            tbody.innerHTML = '';
            spinner.classList.remove('hidden');
            table.classList.add('hidden');
            emptyState.classList.add('hidden');
            statsBanner.classList.add('hidden');

            try {
                const data = await fetchJSON(`${API_BASE_URL}/api/dbadmin/jobs?${params}`);
                const jobs = data.jobs || [];

                spinner.classList.add('hidden');

                if (jobs.length === 0) {
                    emptyState.classList.remove('hidden');
                    return;
                }

                // Render jobs table
                tbody.innerHTML = jobs.map(job => {
                    const taskCounts = getTaskCounts(job);
                    const stageProgress = `${job.stage}/${job.total_stages || '?'}`;

                    return `
                        <tr onclick="showJobDetail('${job.job_id}')">
                            <td>
                                <div class="job-id">${truncateId(job.job_id)}</div>
                            </td>
                            <td>
                                <div class="job-type">${job.job_type}</div>
                            </td>
                            <td>
                                <span class="status-badge status-${job.status}">${job.status}</span>
                            </td>
                            <td>
                                <div class="stage-progress">${stageProgress}</div>
                            </td>
                            <td>
                                <div class="task-counts">${formatTaskCounts(taskCounts)}</div>
                            </td>
                            <td>
                                <div class="timestamp">${formatTimestamp(job.created_at)}</div>
                            </td>
                            <td>
                                <div class="timestamp">${formatTimestamp(job.updated_at)}</div>
                            </td>
                        </tr>
                    `;
                }).join('');

                table.classList.remove('hidden');

                // Calculate stats
                const stats = calculateStats(jobs);
                updateStats(stats);
                statsBanner.classList.remove('hidden');

            } catch (error) {
                console.error('Error loading jobs:', error);
                spinner.classList.add('hidden');
                emptyState.classList.remove('hidden');
            }
        }

        // Get task counts from job result_data or default to 0
        function getTaskCounts(job) {
            const tasksByStatus = job.result_data?.tasks_by_status || {};
            return {
                queued: tasksByStatus.queued || 0,
                processing: tasksByStatus.processing || 0,
                completed: tasksByStatus.completed || 0,
                failed: tasksByStatus.failed || 0
            };
        }

        // Format task counts for display
        function formatTaskCounts(counts) {
            const items = [];
            if (counts.queued > 0) items.push(`<span class="task-count-item"><span class="task-count-label">Q:</span> ${counts.queued}</span>`);
            if (counts.processing > 0) items.push(`<span class="task-count-item"><span class="task-count-label">P:</span> ${counts.processing}</span>`);
            if (counts.completed > 0) items.push(`<span class="task-count-item"><span class="task-count-label">C:</span> ${counts.completed}</span>`);
            if (counts.failed > 0) items.push(`<span class="task-count-item"><span class="task-count-label">F:</span> ${counts.failed}</span>`);

            return items.length > 0 ? items.join(' ') : '<span style="color: #626F86;">No tasks</span>';
        }

        // Truncate job ID for display
        function truncateId(id) {
            return id.substring(0, 8) + '...' + id.substring(id.length - 8);
        }

        // Format timestamp
        function formatTimestamp(timestamp) {
            if (!timestamp) return 'N/A';
            const date = new Date(timestamp);
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        // Calculate statistics
        function calculateStats(jobs) {
            const stats = {
                total: jobs.length,
                queued: 0,
                processing: 0,
                completed: 0,
                failed: 0
            };

            jobs.forEach(job => {
                stats[job.status] = (stats[job.status] || 0) + 1;
            });

            return stats;
        }

        // Update stats display
        function updateStats(stats) {
            document.getElementById('total-jobs').textContent = stats.total;
            document.getElementById('total-queued').textContent = stats.queued || 0;
            document.getElementById('total-processing').textContent = stats.processing || 0;
            document.getElementById('total-completed').textContent = stats.completed || 0;
            document.getElementById('total-failed').textContent = stats.failed || 0;
        }

        // Show job detail view
        async function showJobDetail(jobId) {
            // Hide jobs list, show detail view
            document.getElementById('jobs-container').classList.add('hidden');
            document.getElementById('stats-banner').classList.add('hidden');
            document.getElementById('controls').classList.add('hidden');
            document.getElementById('job-detail-view').classList.remove('hidden');

            // Show loading state
            document.getElementById('detail-header').innerHTML = '<div class="spinner"></div>';
            document.getElementById('detail-actions').innerHTML = '';
            document.getElementById('detail-parameters').innerHTML = '';
            document.getElementById('detail-results').innerHTML = '';
            document.getElementById('detail-tasks').innerHTML = '';

            try {
                // Fetch job + tasks in parallel
                const [job, tasksData] = await Promise.all([
                    fetchJSON(`${API_BASE_URL}/api/dbadmin/jobs/${jobId}`),
                    fetchJSON(`${API_BASE_URL}/api/dbadmin/tasks/${jobId}`)
                ]);

                // Render detail view
                renderJobDetail(job, tasksData.tasks || []);

            } catch (error) {
                console.error('Error loading job detail:', error);
                document.getElementById('detail-header').innerHTML = `
                    <div class="error-banner">
                        <div class="error-header">Failed to Load Job Details</div>
                        <div class="error-message">${error.message || 'Unknown error occurred'}</div>
                    </div>
                `;
            }
        }

        // Render job detail view
        function renderJobDetail(job, tasks) {
            // Render header with metadata
            renderDetailHeader(job, tasks);

            // Render action buttons
            renderDetailActions(job);

            // Render parameters
            renderDetailParameters(job);

            // Render job-specific results
            renderDetailResults(job);

            // Render tasks grouped by stage
            renderDetailTasks(job, tasks);
        }

        // Render detail header
        function renderDetailHeader(job, tasks) {
            const failedTasks = tasks.filter(t => t.status === 'failed').length;
            const completedTasks = tasks.filter(t => t.status === 'completed').length;
            const processingTasks = tasks.filter(t => t.status === 'processing').length;
            const queuedTasks = tasks.filter(t => t.status === 'queued').length;

            const stageProgress = job.total_stages > 0 ? `${job.stage || 0}/${job.total_stages}` : 'N/A';

            let statusHTML = '';
            if (job.status === 'failed') {
                statusHTML = `
                    <div class="error-banner" style="margin-bottom: 20px;">
                        <div class="error-header">Job Failed</div>
                        <div class="error-message">${job.error_details || 'No error details available'}</div>
                    </div>
                `;
            }

            document.getElementById('detail-header').innerHTML = `
                ${statusHTML}
                <h2>${job.job_type}</h2>
                <div class="meta-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-top: 20px;">
                    <div class="meta-item">
                        <span class="meta-label">Job ID</span>
                        <span class="meta-value" style="font-family: 'Courier New', monospace; font-size: 12px;">${job.job_id.substring(0, 8)}...${job.job_id.substring(job.job_id.length - 8)}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Status</span>
                        <span class="status-badge status-${job.status}">${job.status}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Stage Progress</span>
                        <span class="meta-value">${stageProgress}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Tasks</span>
                        <span class="meta-value">
                            <span style="color: #626F86;">Q:</span> ${queuedTasks}
                            <span style="color: #F59E0B; margin-left: 8px;">P:</span> ${processingTasks}
                            <span style="color: #10B981; margin-left: 8px;">C:</span> ${completedTasks}
                            <span style="color: #DC2626; margin-left: 8px;">F:</span> ${failedTasks}
                        </span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Created</span>
                        <span class="meta-value">${new Date(job.created_at).toLocaleString()}</span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Updated</span>
                        <span class="meta-value">${new Date(job.updated_at).toLocaleString()}</span>
                    </div>
                </div>
            `;
        }

        // Render action buttons
        function renderDetailActions(job) {
            let actionsHTML = '<div style="display: flex; gap: 10px; flex-wrap: wrap;">';

            // Copy Job ID button (always available)
            actionsHTML += `
                <button class="action-button" onclick="copyToClipboard('${job.job_id}', 'Job ID copied!')">
                    📋 Copy Job ID
                </button>
            `;

            // TiTiler link (for raster jobs with MosaicJSON)
            if (job.job_type.includes('raster') && job.result_data?.mosaic_json_url) {
                const titilerUrl = job.result_data.titiler_url || `${API_BASE_URL}/api/titiler/mosaicjson?url=${encodeURIComponent(job.result_data.mosaic_json_url)}`;
                actionsHTML += `
                    <a href="${titilerUrl}" target="_blank" class="action-button" style="text-decoration: none;">
                        🗺️ View in TiTiler
                    </a>
                `;
            }

            // Raw JSON viewer button
            actionsHTML += `
                <button class="action-button action-button-secondary" onclick="toggleJSON('job-raw-json')">
                    📄 View Raw JSON
                </button>
            `;

            actionsHTML += '</div>';

            // Add expandable JSON section
            actionsHTML += `
                <div id="job-raw-json" class="expandable-json hidden" style="margin-top: 15px;">
                    <pre>${JSON.stringify(job, null, 2)}</pre>
                </div>
            `;

            document.getElementById('detail-actions').innerHTML = actionsHTML;
        }

        // Render parameters section
        function renderDetailParameters(job) {
            if (!job.parameters || Object.keys(job.parameters).length === 0) {
                document.getElementById('detail-parameters').innerHTML = '';
                return;
            }

            let paramsHTML = `
                <div class="detail-section">
                    <h3>Input Parameters</h3>
                    <div class="param-grid" style="display: grid; gap: 10px;">
            `;

            for (const [key, value] of Object.entries(job.parameters)) {
                paramsHTML += `
                    <div class="param-item" style="background: #f8f9fa; padding: 12px; border-radius: 3px;">
                        <span style="font-weight: 600; color: #053657; display: block; margin-bottom: 5px;">${key}</span>
                        <span style="color: #626F86; font-family: 'Courier New', monospace; font-size: 13px;">${JSON.stringify(value)}</span>
                    </div>
                `;
            }

            paramsHTML += `
                    </div>
                </div>
            `;

            document.getElementById('detail-parameters').innerHTML = paramsHTML;
        }

        // Render job-specific results
        function renderDetailResults(job) {
            if (!job.result_data || Object.keys(job.result_data).length === 0) {
                document.getElementById('detail-results').innerHTML = '';
                return;
            }

            let resultsHTML = `
                <div class="detail-section">
                    <h3>Job Results</h3>
                    <div class="results-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px;">
            `;

            const rd = job.result_data;

            // COG statistics (for process_raster jobs)
            if (rd.cog_stats) {
                resultsHTML += `
                    <div class="result-card">
                        <h4>📊 COG Statistics</h4>
                        <div class="result-content">
                            <div><strong>Files Created:</strong> ${rd.cog_stats.files_created || 0}</div>
                            <div><strong>Total Size:</strong> ${(rd.cog_stats.total_size_mb || 0).toFixed(2)} MB</div>
                            ${rd.cog_stats.compression ? `<div><strong>Compression:</strong> ${rd.cog_stats.compression}</div>` : ''}
                        </div>
                    </div>
                `;
            }

            // MosaicJSON (for collection jobs)
            if (rd.mosaic_json_url) {
                resultsHTML += `
                    <div class="result-card">
                        <h4>🗺️ MosaicJSON</h4>
                        <div class="result-content">
                            <a href="${rd.mosaic_json_url}" target="_blank" style="color: #0071BC; text-decoration: none; word-break: break-all;">
                                ${rd.mosaic_json_url}
                            </a>
                        </div>
                    </div>
                `;
            }

            // TiTiler URL (for raster jobs)
            if (rd.titiler_url) {
                resultsHTML += `
                    <div class="result-card">
                        <h4>🌐 TiTiler Endpoint</h4>
                        <div class="result-content">
                            <a href="${rd.titiler_url}" target="_blank" style="color: #0071BC; text-decoration: none; word-break: break-all;">
                                ${rd.titiler_url}
                            </a>
                        </div>
                    </div>
                `;
            }

            // STAC collection ID (for jobs that create STAC items)
            if (rd.stac_collection_id) {
                resultsHTML += `
                    <div class="result-card">
                        <h4>📦 STAC Collection</h4>
                        <div class="result-content">
                            <a href="${API_BASE_URL}/api/stac/collections/${rd.stac_collection_id}" target="_blank" style="color: #0071BC; text-decoration: none;">
                                ${rd.stac_collection_id}
                            </a>
                        </div>
                    </div>
                `;
            }

            // Items processed count
            if (rd.items_processed !== undefined) {
                resultsHTML += `
                    <div class="result-card">
                        <h4>✅ Items Processed</h4>
                        <div class="result-content">
                            <span style="font-size: 24px; color: #10B981; font-weight: 700;">${rd.items_processed}</span>
                        </div>
                    </div>
                `;
            }

            // Generic key-value display for other result data
            const displayedKeys = ['cog_stats', 'mosaic_json_url', 'titiler_url', 'stac_collection_id', 'items_processed', 'tasks_by_status'];
            for (const [key, value] of Object.entries(rd)) {
                if (!displayedKeys.includes(key) && value !== null && value !== undefined) {
                    resultsHTML += `
                        <div class="result-card">
                            <h4>${key.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase())}</h4>
                            <div class="result-content">
                                <pre style="margin: 0; white-space: pre-wrap; word-wrap: break-word;">${JSON.stringify(value, null, 2)}</pre>
                            </div>
                        </div>
                    `;
                }
            }

            resultsHTML += `
                    </div>
                </div>
            `;

            document.getElementById('detail-results').innerHTML = resultsHTML;
        }

        // Render tasks grouped by stage
        function renderDetailTasks(job, tasks) {
            if (!tasks || tasks.length === 0) {
                document.getElementById('detail-tasks').innerHTML = `
                    <div class="detail-section">
                        <h3>Tasks</h3>
                        <p style="color: #626F86; text-align: center; padding: 40px;">No tasks found for this job</p>
                    </div>
                `;
                return;
            }

            // Group tasks by stage
            const tasksByStage = {};
            tasks.forEach(task => {
                const stage = task.stage || 0;
                if (!tasksByStage[stage]) {
                    tasksByStage[stage] = [];
                }
                tasksByStage[stage].push(task);
            });

            let tasksHTML = `
                <div class="detail-section">
                    <h3>Tasks (${tasks.length} total)</h3>
            `;

            // Render each stage
            const stages = Object.keys(tasksByStage).sort((a, b) => parseInt(a) - parseInt(b));
            stages.forEach(stage => {
                const stageTasks = tasksByStage[stage];
                const failed = stageTasks.filter(t => t.status === 'failed').length;
                const completed = stageTasks.filter(t => t.status === 'completed').length;
                const processing = stageTasks.filter(t => t.status === 'processing').length;
                const queued = stageTasks.filter(t => t.status === 'queued').length;

                tasksHTML += `
                    <div class="stage-group">
                        <div class="stage-header" onclick="toggleStage('stage-${stage}')" style="cursor: pointer;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <h4 style="margin: 0;">Stage ${stage} (${stageTasks.length} tasks)</h4>
                                <div>
                                    <span style="color: #626F86;">Q:</span> ${queued}
                                    <span style="color: #F59E0B; margin-left: 8px;">P:</span> ${processing}
                                    <span style="color: #10B981; margin-left: 8px;">C:</span> ${completed}
                                    <span style="color: #DC2626; margin-left: 8px;">F:</span> ${failed}
                                    <span style="margin-left: 10px;">▼</span>
                                </div>
                            </div>
                        </div>
                        <div id="stage-${stage}" class="stage-tasks hidden" style="margin-top: 15px;">
                `;

                // Render tasks in this stage
                stageTasks.forEach(task => {
                    const errorHTML = task.status === 'failed' && task.error_details ? `
                        <div style="margin-top: 10px; padding: 10px; background: #FEE2E2; border-left: 3px solid #DC2626; border-radius: 3px;">
                            <strong style="color: #DC2626;">Error:</strong>
                            <div style="color: #DC2626; font-size: 13px; margin-top: 5px;">${task.error_details}</div>
                        </div>
                    ` : '';

                    tasksHTML += `
                        <div class="task-item" style="background: white; padding: 15px; border: 1px solid #e9ecef; border-radius: 3px; margin-bottom: 10px;">
                            <div style="display: flex; justify-content: space-between; align-items: start;">
                                <div>
                                    <div style="font-weight: 600; color: #053657;">${task.task_type}</div>
                                    <div style="font-size: 12px; color: #626F86; font-family: 'Courier New', monospace; margin-top: 5px;">
                                        ${task.task_id.substring(0, 8)}...${task.task_id.substring(task.task_id.length - 8)}
                                    </div>
                                </div>
                                <span class="status-badge status-${task.status}">${task.status}</span>
                            </div>
                            ${errorHTML}
                            ${task.result_data ? `
                                <button class="action-button action-button-secondary" onclick="toggleJSON('task-${task.task_id}')" style="margin-top: 10px; font-size: 12px; padding: 6px 12px;">
                                    View Result Data
                                </button>
                                <div id="task-${task.task_id}" class="expandable-json hidden" style="margin-top: 10px;">
                                    <pre>${JSON.stringify(task.result_data, null, 2)}</pre>
                                </div>
                            ` : ''}
                        </div>
                    `;
                });

                tasksHTML += `
                        </div>
                    </div>
                `;
            });

            tasksHTML += `
                </div>
            `;

            document.getElementById('detail-tasks').innerHTML = tasksHTML;
        }

        // Show jobs list (back button)
        function showJobsList() {
            document.getElementById('job-detail-view').classList.add('hidden');
            document.getElementById('jobs-container').classList.remove('hidden');
            document.getElementById('stats-banner').classList.remove('hidden');
            document.getElementById('controls').classList.remove('hidden');
        }

        // Toggle stage visibility
        function toggleStage(stageId) {
            const stageEl = document.getElementById(stageId);
            if (stageEl) {
                stageEl.classList.toggle('hidden');
            }
        }

        // Toggle JSON visibility
        function toggleJSON(jsonId) {
            const jsonEl = document.getElementById(jsonId);
            if (jsonEl) {
                jsonEl.classList.toggle('hidden');
            }
        }

        // Copy to clipboard utility
        function copyToClipboard(text, message) {
            navigator.clipboard.writeText(text).then(() => {
                alert(message || 'Copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy:', err);
                alert('Failed to copy to clipboard');
            });
        }
        """
