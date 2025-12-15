"""
Job monitor interface module.

Web dashboard for monitoring jobs and tasks with filtering and refresh capabilities.

Exports:
    JobsInterface: Job monitoring dashboard with stage progress and task status counts
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

        # Wrap in base HTML template
        return self.wrap_html(
            title="Job Monitor",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content for Job Monitor dashboard."""
        return """
        <div class="container">
            <div class="page-header">
                <h1 class="page-title">Job Monitor</h1>
                <p class="page-subtitle">Monitor jobs and tasks from app.jobs table</p>
            </div>

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
                    <label for="limitFilter">Limit:</label>
                    <select id="limitFilter" class="filter-select">
                        <option value="10">10</option>
                        <option value="25" selected>25</option>
                        <option value="50">50</option>
                        <option value="100">100</option>
                    </select>
                </div>

                <div class="filter-actions">
                    <button id="refreshBtn" class="btn btn-primary">🔄 Refresh</button>
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
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Job Monitor."""
        return """
        .filter-bar {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            display: flex;
            gap: 1.5rem;
            align-items: flex-end;
            flex-wrap: wrap;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            min-width: 150px;
        }

        .filter-group label {
            font-size: 0.875rem;
            font-weight: 500;
            color: #374151;
        }

        .filter-select {
            padding: 0.5rem 0.75rem;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 0.875rem;
            background: white;
            cursor: pointer;
        }

        .filter-select:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
        }

        .filter-actions {
            display: flex;
            gap: 0.75rem;
            margin-left: auto;
        }

        .stats-banner {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }

        .stat-card {
            background: white;
            border-radius: 8px;
            padding: 1.25rem;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .stat-label {
            font-size: 0.875rem;
            color: #6b7280;
            margin-bottom: 0.5rem;
        }

        .stat-value {
            font-size: 2rem;
            font-weight: 700;
            color: #1f2937;
        }

        .stat-queued { color: #6b7280; }
        .stat-processing { color: var(--ds-blue-primary); }
        .stat-completed { color: #10b981; }
        .stat-failed { color: #ef4444; }

        .data-table {
            width: 100%;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .data-table thead {
            background: #f9fafb;
        }

        .data-table th {
            padding: 1rem;
            text-align: left;
            font-size: 0.875rem;
            font-weight: 600;
            color: #374151;
            border-bottom: 2px solid #e5e7eb;
        }

        .data-table td {
            padding: 1rem;
            border-bottom: 1px solid #e5e7eb;
            font-size: 0.875rem;
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
            gap: 0.75rem;
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
            background: white;
            border-radius: 8px;
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

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for Job Monitor."""
        return """
        let currentFilters = {
            status: '',
            limit: 25
        };

        // Load jobs on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadJobs();

            // Event listeners
            document.getElementById('refreshBtn').addEventListener('click', loadJobs);
            document.getElementById('statusFilter').addEventListener('change', (e) => {
                currentFilters.status = e.target.value;
                loadJobs();
            });
            document.getElementById('limitFilter').addEventListener('change', (e) => {
                currentFilters.limit = parseInt(e.target.value);
                loadJobs();
            });
            document.getElementById('clearFiltersBtn').addEventListener('click', () => {
                currentFilters = { status: '', limit: 25 };
                document.getElementById('statusFilter').value = '';
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
                params.append('limit', currentFilters.limit);

                const response = await fetch(`/api/dbadmin/jobs?${params.toString()}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);

                const data = await response.json();

                // Update stats
                updateStats(data.jobs);

                // Render table
                renderJobsTable(data.jobs);

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

        function updateStats(jobs) {
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

        function renderJobsTable(jobs) {
            const tbody = document.getElementById('jobsTableBody');
            tbody.innerHTML = '';

            if (jobs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 2rem;">No jobs found</td></tr>';
                return;
            }

            jobs.forEach(job => {
                const row = document.createElement('tr');

                // Job ID (short version) - API returns job_id, not id
                const jobId = job.job_id || job.id;
                const jobIdShort = jobId ? jobId.substring(0, 8) : '--';
                const createdAt = job.created_at ? new Date(job.created_at).toLocaleString() : '--';

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
                        <a href="/api/interface/tasks?job_id=${jobId}" class="btn btn-sm btn-primary">View Tasks</a>
                    </td>
                `;

                tbody.appendChild(row);
            });
        }
        """
