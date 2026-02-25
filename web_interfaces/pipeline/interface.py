"""
Pipeline workflows interface module.

Web dashboard showing ETL pipeline workflows, job status, and the ability to
monitor and manage data processing pipelines.

Features (24 DEC 2025 - S12.3.4):
    - HTMX enabled for future partial updates
    - Pipeline workflow diagrams
    - Jobs table with filtering

Exports:
    PipelineInterface: Pipeline workflow dashboard with job monitoring
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('pipeline')
class PipelineInterface(BaseInterface):
    """
    Pipeline Workflows interface for monitoring ETL jobs.

    Displays:
        - Available pipeline types (Vector, Raster, Raster Collection)
        - Recent job status and progress
        - Pipeline workflow diagrams
        - Quick actions to view job details
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Pipeline Workflows HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        return self.wrap_html(
            title="Pipeline Workflows",
            content=self._generate_html_content(),
            custom_css=self._generate_custom_css(),
            custom_js=self._generate_custom_js(),
            include_htmx=True
        )

    def _generate_custom_css(self) -> str:
        """Pipeline-specific styles."""
        return """
            .dashboard-header {
                background: white;
                padding: 14px 20px;
                border-radius: 3px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                margin-bottom: 12px;
                border-left: 4px solid #0071BC;
            }

            .dashboard-header h1 {
                color: #053657;
                font-size: 20px;
                margin-bottom: 4px;
                font-weight: 700;
            }

            .subtitle {
                color: #626F86;
                font-size: 13px;
                margin: 0;
            }

            .section {
                background: white;
                border-radius: 6px;
                padding: 16px;
                margin-bottom: 12px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .section h2 {
                color: var(--ds-navy);
                font-size: 16px;
                margin: 0 0 12px 0;
                padding-bottom: 8px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .pipeline-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 12px;
            }

            .pipeline-card {
                background: var(--ds-bg);
                border: 2px solid var(--ds-gray-light);
                border-radius: 6px;
                padding: 14px;
                transition: all 0.2s;
                display: flex;
                flex-direction: column;
            }

            .pipeline-card:hover {
                border-color: var(--ds-blue-primary);
                box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            }

            .pipeline-card h3 {
                color: var(--ds-navy);
                font-size: 15px;
                margin: 0 0 6px 0;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .pipeline-card .icon {
                font-size: 20px;
            }

            .pipeline-card .description {
                color: var(--ds-gray);
                font-size: 12px;
                margin-bottom: 10px;
                line-height: 1.4;
            }

            .stage {
                background: white;
                border: 1px solid var(--ds-gray-light);
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 10px;
                font-weight: 600;
                color: var(--ds-navy);
            }

            .pipeline-stats {
                display: flex;
                gap: 12px;
                padding-top: 8px;
                border-top: 1px solid var(--ds-gray-light);
            }

            .stat {
                text-align: center;
            }

            .stat-value {
                font-size: 16px;
                font-weight: 700;
                color: var(--ds-blue-primary);
            }

            .stat-label {
                font-size: 10px;
                color: var(--ds-gray);
                text-transform: uppercase;
            }

            /* Pipeline action button */
            .pipeline-action {
                margin-top: auto;
                padding-top: 10px;
                border-top: 1px solid var(--ds-gray-light);
            }

            .btn-submit {
                display: inline-block;
                width: 100%;
                padding: 8px 12px;
                background: var(--ds-blue-primary);
                color: white;
                text-align: center;
                text-decoration: none;
                border-radius: 4px;
                font-weight: 600;
                font-size: 12px;
                transition: background 0.2s;
            }

            .btn-submit:hover {
                background: var(--ds-cyan);
            }

            .btn-placeholder {
                display: inline-block;
                width: 100%;
                padding: 8px 12px;
                background: #e5e7eb;
                color: #9ca3af;
                text-align: center;
                border-radius: 4px;
                font-weight: 600;
                font-size: 12px;
                cursor: not-allowed;
            }

            /* Jobs Filter Bar */
            .filter-bar {
                background: var(--ds-bg);
                border-radius: 6px;
                padding: 0.75rem;
                margin-bottom: 0.75rem;
                display: flex;
                gap: 1rem;
                align-items: flex-end;
                flex-wrap: wrap;
            }

            .filter-group {
                display: flex;
                flex-direction: column;
                gap: 0.25rem;
                min-width: 100px;
            }

            .filter-group label {
                font-size: 0.75rem;
                font-weight: 500;
                color: #374151;
            }

            .filter-select {
                padding: 0.375rem 0.5rem;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                font-size: 0.8rem;
                background: white;
                cursor: pointer;
            }

            .filter-select:focus {
                outline: none;
                border-color: var(--ds-blue-primary);
                box-shadow: 0 0 0 2px rgba(0, 113, 188, 0.1);
            }

            .filter-actions {
                display: flex;
                gap: 0.5rem;
                margin-left: auto;
            }

            /* Jobs Stats Banner */
            .stats-banner {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
                gap: 0.5rem;
                margin-bottom: 0.75rem;
            }

            .stat-card {
                background: var(--ds-bg);
                border-radius: 6px;
                padding: 0.5rem;
                text-align: center;
            }

            .stat-card .stat-label {
                font-size: 0.65rem;
                color: #6b7280;
                margin-bottom: 0.125rem;
                text-transform: uppercase;
            }

            .stat-card .stat-value {
                font-size: 1.25rem;
                font-weight: 700;
                color: #1f2937;
            }

            .stat-queued { color: #6b7280 !important; }
            .stat-processing { color: var(--ds-blue-primary) !important; }
            .stat-completed { color: #10b981 !important; }
            .stat-failed { color: #ef4444 !important; }

            /* Jobs Table */
            .data-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 12px;
            }

            .data-table thead {
                background: var(--ds-bg);
            }

            .data-table th {
                padding: 0.5rem 0.75rem;
                text-align: left;
                font-size: 0.75rem;
                font-weight: 600;
                color: #374151;
                border-bottom: 2px solid #e5e7eb;
            }

            .data-table td {
                padding: 0.5rem 0.75rem;
                border-bottom: 1px solid #e5e7eb;
                font-size: 0.8rem;
            }

            .data-table tbody tr:hover {
                background: #f9fafb;
            }

            .status-badge {
                padding: 0.25rem 0.75rem;
                border-radius: 12px;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: uppercase;
            }

            .status-queued {
                background: #f3f4f6;
                color: #6b7280;
            }

            .status-processing {
                background: #dbeafe;
                color: var(--ds-blue-primary);
            }

            .status-completed {
                background: #d1fae5;
                color: #059669;
            }

            .status-failed {
                background: #fee2e2;
                color: #dc2626;
            }

            .stage-badge {
                font-size: 0.875rem;
                color: #6b7280;
            }

            .task-summary {
                display: flex;
                gap: 0.5rem;
                font-size: 0.75rem;
            }

            .task-count {
                padding: 0.125rem 0.5rem;
                border-radius: 4px;
                font-weight: 600;
            }

            .task-count-queued {
                background: #f3f4f6;
                color: #6b7280;
            }

            .task-count-processing {
                background: #dbeafe;
                color: var(--ds-blue-primary);
            }

            .task-count-completed {
                background: #d1fae5;
                color: #059669;
            }

            .task-count-failed {
                background: #fee2e2;
                color: #dc2626;
            }

            .job-id-short {
                font-family: 'Monaco', 'Courier New', monospace;
                font-size: 0.75rem;
                color: #6b7280;
            }

            .loading-state {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 3rem;
            }

            .spinner {
                width: 40px;
                height: 40px;
                border: 4px solid #f3f4f6;
                border-top-color: var(--ds-blue-primary);
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }

            @keyframes spin {
                to { transform: rotate(360deg); }
            }

            .error-state {
                padding: 2rem;
                background: #fee2e2;
                border-radius: 8px;
                text-align: center;
            }

            .error-message {
                color: #dc2626;
                margin-bottom: 1rem;
            }
        """

    def _generate_html_content(self) -> str:
        """Generate main content HTML."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>Pipeline Workflows</h1>
                <p class="subtitle">Monitor and manage ETL data processing pipelines</p>
            </header>

            <!-- Submit New Job -->
            <div class="section">
                <h2>Submit New Job</h2>
                <div class="pipeline-grid">
                    <!-- Unified Submit -->
                    <div class="pipeline-card" style="border-color: var(--ds-blue-primary); border-width: 2px;">
                        <h3><span class="icon">📤</span> Submit Job</h3>
                        <p class="description">
                            Unified job submission for all data types. Browse storage, configure
                            DDH identifiers, validate with dry_run, and submit for processing.
                        </p>
                        <div style="margin-bottom: 10px;">
                            <div style="font-size: 11px; color: var(--ds-gray); margin-bottom: 6px; font-weight: 600;">SUPPORTED TYPES:</div>
                            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                                <span class="stage" style="background: #e0f2fe;">🛰️ Raster</span>
                                <span class="stage" style="background: #e0f2fe;">🗂️ Collection</span>
                                <span class="stage" style="background: #dcfce7;">🗺️ Vector</span>
                            </div>
                        </div>
                        <div class="pipeline-stats">
                            <div class="stat">
                                <div class="stat-value" id="submit-24h">--</div>
                                <div class="stat-label">Last 24h</div>
                            </div>
                            <div class="stat">
                                <div class="stat-value" id="submit-success">--</div>
                                <div class="stat-label">Success Rate</div>
                            </div>
                        </div>
                        <div class="pipeline-action">
                            <a href="/api/interface/submit" class="btn btn-submit" style="font-size: 14px; padding: 10px 14px;">📤 Submit New Job</a>
                        </div>
                    </div>

                </div>
            </div>

            <!-- Recent Jobs -->
            <div class="section">
                <h2>Recent Jobs</h2>

                <!-- Filter Bar -->
                <div class="filter-bar">
                    <div class="filter-group">
                        <label for="statusFilter">Status:</label>
                        <select id="statusFilter" class="filter-select">
                            <option value="">All</option>
                            <option value="queued">Queued</option>
                            <option value="processing">Processing</option>
                            <option value="completed">Completed</option>
                            <option value="failed">Failed</option>
                        </select>
                    </div>

                    <div class="filter-group">
                        <label for="hoursFilter">Time Range:</label>
                        <select id="hoursFilter" class="filter-select">
                            <option value="24">Last 24 hours</option>
                            <option value="72">Last 3 days</option>
                            <option value="168" selected>Last 7 days</option>
                            <option value="336">Last 14 days</option>
                            <option value="720">Last 30 days</option>
                            <option value="0">All time</option>
                        </select>
                    </div>

                    <div class="filter-group">
                        <label for="limitFilter">Limit:</label>
                        <select id="limitFilter" class="filter-select">
                            <option value="10">10</option>
                            <option value="25" selected>25</option>
                            <option value="50">50</option>
                            <option value="100">100</option>
                        </select>
                    </div>

                    <div class="filter-actions">
                        <button id="refreshBtn" class="btn btn-primary">Refresh</button>
                        <button id="clearFiltersBtn" class="btn btn-secondary">Clear Filters</button>
                    </div>
                </div>

                <!-- Loading State -->
                <div id="loadingState" class="loading-state">
                    <div class="spinner"></div>
                    <p>Loading jobs...</p>
                </div>

                <!-- Error State -->
                <div id="errorState" class="error-state" style="display: none;">
                    <p class="error-message"></p>
                    <button id="retryBtn" class="btn btn-primary">Retry</button>
                </div>

                <!-- Jobs Table -->
                <div id="jobsTableContainer" style="display: none;">
                    <div class="stats-banner">
                        <div class="stat-card">
                            <div class="stat-label">Total Jobs</div>
                            <div class="stat-value" id="totalJobs">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Queued</div>
                            <div class="stat-value stat-queued" id="queuedJobs">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Processing</div>
                            <div class="stat-value stat-processing" id="processingJobs">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Completed</div>
                            <div class="stat-value stat-completed" id="completedJobs">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Failed</div>
                            <div class="stat-value stat-failed" id="failedJobs">0</div>
                        </div>
                    </div>

                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Job Type</th>
                                <th>Status</th>
                                <th>Stage</th>
                                <th>Tasks</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="jobsTableBody">
                            <!-- Populated by JavaScript -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        """

    def _generate_custom_js(self) -> str:
        """JavaScript for loading job data."""
        return """
        // Job filters
        let currentFilters = {
            status: '',
            hours: 168,  // Default 7 days
            limit: 25
        };

        // Load jobs on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadJobs();

            // Event listeners for job filters
            document.getElementById('refreshBtn').addEventListener('click', loadJobs);
            document.getElementById('statusFilter').addEventListener('change', (e) => {
                currentFilters.status = e.target.value;
                loadJobs();
            });
            document.getElementById('hoursFilter').addEventListener('change', (e) => {
                currentFilters.hours = parseInt(e.target.value);
                loadJobs();
            });
            document.getElementById('limitFilter').addEventListener('change', (e) => {
                currentFilters.limit = parseInt(e.target.value);
                loadJobs();
            });
            document.getElementById('clearFiltersBtn').addEventListener('click', () => {
                currentFilters = { status: '', hours: 168, limit: 25 };
                document.getElementById('statusFilter').value = '';
                document.getElementById('hoursFilter').value = '168';
                document.getElementById('limitFilter').value = '25';
                loadJobs();
            });
            document.getElementById('retryBtn').addEventListener('click', loadJobs);
        });

        async function loadJobs() {
            const loadingState = document.getElementById('loadingState');
            const errorState = document.getElementById('errorState');
            const tableContainer = document.getElementById('jobsTableContainer');

            // Show loading
            loadingState.style.display = 'flex';
            errorState.style.display = 'none';
            tableContainer.style.display = 'none';

            try {
                // Build query string
                const params = new URLSearchParams();
                if (currentFilters.status) params.append('status', currentFilters.status);
                params.append('hours', currentFilters.hours);  // Include hours filter
                params.append('limit', currentFilters.limit);

                const response = await fetch(`${API_BASE_URL}/api/dbadmin/jobs?${params.toString()}`);
                const data = await response.json();

                // Handle schema not deployed error (503)
                if (response.status === 503 && data.error === 'Schema not deployed') {
                    loadingState.style.display = 'none';
                    errorState.style.display = 'block';
                    errorState.querySelector('.error-message').innerHTML = `
                        <strong>Schema not deployed:</strong> ${escapeHtml(data.message)}<br>
                        <span style="font-size: 12px; color: #666;">
                            Hint: ${escapeHtml(data.hint || 'Deploy the database schema first')}
                        </span>
                    `;
                    return;
                }

                if (!response.ok) throw new Error(data.error || `HTTP ${response.status}: ${response.statusText}`);

                const jobs = data.jobs || [];

                // Update stats
                updateJobStats(jobs);

                // Update pipeline card stats
                updatePipelineStats(jobs);

                // Render table with query info
                renderJobsTable(jobs, data.query_info);

                // Show table
                loadingState.style.display = 'none';
                tableContainer.style.display = 'block';

            } catch (error) {
                console.error('Failed to load jobs:', error);
                loadingState.style.display = 'none';
                errorState.style.display = 'block';
                errorState.querySelector('.error-message').textContent = 'Failed to load jobs: ' + error.message;
            }
        }

        function updateJobStats(jobs) {
            const stats = jobs.reduce((acc, job) => {
                acc.total++;
                acc[job.status] = (acc[job.status] || 0) + 1;
                return acc;
            }, { total: 0, queued: 0, processing: 0, completed: 0, failed: 0 });

            document.getElementById('totalJobs').textContent = stats.total;
            document.getElementById('queuedJobs').textContent = stats.queued;
            document.getElementById('processingJobs').textContent = stats.processing;
            document.getElementById('completedJobs').textContent = stats.completed;
            document.getElementById('failedJobs').textContent = stats.failed;
        }

        function updatePipelineStats(jobs) {
            // Calculate unified submit stats (all pipeline jobs)
            const now = new Date();
            const last24h = new Date(now - 24 * 60 * 60 * 1000);

            const pipelineTypes = [
                'process_vector', 'process_vector_docker',
                'process_raster_v2', 'process_raster_docker',
                'process_raster_collection_v2', 'process_raster_collection_docker',
                'process_large_raster_v2'
            ];
            const allSubmitJobs = jobs.filter(j => pipelineTypes.includes(j.job_type));
            const submitRecent = allSubmitJobs.filter(j => new Date(j.created_at) > last24h);
            const submitSuccess = allSubmitJobs.filter(j => j.status === 'completed').length;
            document.getElementById('submit-24h').textContent = submitRecent.length;
            document.getElementById('submit-success').textContent =
                allSubmitJobs.length > 0 ? Math.round(submitSuccess / allSubmitJobs.length * 100) + '%' : '--';
        }

        function renderJobsTable(jobs, queryInfo) {
            const tbody = document.getElementById('jobsTableBody');
            tbody.innerHTML = '';

            if (jobs.length === 0) {
                const hoursText = queryInfo?.hours_back === 'all' ? 'any time' : `last ${queryInfo?.hours_back || 168} hours`;
                const schemaText = queryInfo?.schema ? ` in schema '${queryInfo.schema}'` : '';
                tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 2rem;">
                    No jobs found${schemaText} (${hoursText}).<br>
                    <span style="font-size: 12px; color: #666;">Try selecting "All time" or submit a test job.</span>
                </td></tr>`;
                return;
            }

            jobs.forEach(job => {
                const row = document.createElement('tr');

                // Job ID (short version) - API returns job_id, not id
                const jobId = job.job_id || job.id;
                const jobIdShort = jobId ? jobId.substring(0, 8) : '--';
                const createdAt = formatDateTime(job.created_at);

                // Task counts
                const taskCounts = job.task_counts || { queued: 0, processing: 0, completed: 0, failed: 0 };

                row.innerHTML = `
                    <td><span class="job-id-short" title="${jobId}">${jobIdShort}</span></td>
                    <td>${job.job_type || '--'}</td>
                    <td><span class="status-badge status-${job.status || 'unknown'}">${job.status || 'unknown'}</span></td>
                    <td><span class="stage-badge">Stage ${job.stage || 0}/${job.total_stages || '?'}</span></td>
                    <td>
                        <div class="task-summary">
                            ${taskCounts.queued > 0 ? `<span class="task-count task-count-queued">Q:${taskCounts.queued}</span>` : ''}
                            ${taskCounts.processing > 0 ? `<span class="task-count task-count-processing">P:${taskCounts.processing}</span>` : ''}
                            ${taskCounts.completed > 0 ? `<span class="task-count task-count-completed">C:${taskCounts.completed}</span>` : ''}
                            ${taskCounts.failed > 0 ? `<span class="task-count task-count-failed">F:${taskCounts.failed}</span>` : ''}
                        </div>
                    </td>
                    <td>${createdAt}</td>
                    <td>
                        <a href="/api/interface/status?job_id=${jobId}" class="btn btn-sm btn-primary">View Status</a>
                    </td>
                `;

                tbody.appendChild(row);
            });
        }
        """
