# ============================================================================
# CLAUDE CONTEXT - JOB EXECUTION DASHBOARD INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Unified Job Execution Dashboard
# PURPOSE: Combined job monitoring with metrics, progress, and task details
# LAST_REVIEWED: 29 DEC 2025
# EXPORTS: ExecutionInterface
# DEPENDENCIES: web_interfaces.base, infrastructure
# ============================================================================
"""
Job Execution Dashboard Interface.

Unified dashboard for monitoring job execution with two modes:

Mode 1 - Overview (/api/interface/execution):
    - Active jobs grid with real-time progress cards
    - Historical jobs table with filtering
    - Click job card/row to go to detail view

Mode 2 - Detail (/api/interface/execution?job_id=X):
    - Single job focus with progress bar
    - Real-time metrics (rate, ETA, context-specific)
    - Workflow stage visualization
    - Task list with stage/status filtering

Features:
    - HTMX-powered live updates
    - Configurable auto-refresh
    - Deep linking via job_id parameter

Routes:
    /api/interface/execution - Overview mode
    /api/interface/execution?job_id=X - Detail mode
    /api/interface/execution?fragment=active-jobs - HTMX partial
    /api/interface/execution?fragment=jobs-table - HTMX partial
    /api/interface/execution?fragment=job-progress&job_id=X - HTMX partial
    /api/interface/execution?fragment=tasks-table&job_id=X - HTMX partial
"""

import logging
from typing import Dict, Any, List, Optional

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('execution')
class ExecutionInterface(BaseInterface):
    """
    Unified Job Execution Dashboard with Overview and Detail modes.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Job Execution Dashboard HTML.

        Renders Overview mode if no job_id, Detail mode if job_id provided.
        """
        job_id = request.params.get('job_id', '')

        if job_id:
            return self._render_detail_mode(job_id)
        else:
            return self._render_overview_mode()

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """Handle HTMX partial requests."""
        if fragment == 'active-jobs':
            return self._render_active_jobs_fragment()
        elif fragment == 'jobs-table':
            return self._render_jobs_table_fragment(request)
        elif fragment == 'job-progress':
            job_id = request.params.get('job_id', '')
            return self._render_job_progress_fragment(job_id)
        elif fragment == 'tasks-table':
            job_id = request.params.get('job_id', '')
            stage = request.params.get('stage', '')
            status = request.params.get('status', '')
            return self._render_tasks_table_fragment(job_id, stage, status)
        elif fragment == 'workflow-stages':
            job_id = request.params.get('job_id', '')
            return self._render_workflow_stages_fragment(job_id)
        else:
            raise ValueError(f"Unknown fragment: {fragment}")

    # =========================================================================
    # OVERVIEW MODE
    # =========================================================================

    def _render_overview_mode(self) -> str:
        """Render the overview dashboard (all jobs)."""
        return self.wrap_html(
            title="Job Execution Dashboard",
            content=self._generate_overview_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_overview_js(),
            include_htmx=True
        )

    def _generate_overview_content(self) -> str:
        """Generate overview mode HTML content."""
        return '''
        <div class="container">
            <header class="dashboard-header">
                <div class="header-row">
                    <div>
                        <h1>Job Execution Dashboard</h1>
                        <p class="subtitle">Monitor active and historical job execution</p>
                    </div>
                    <div class="header-controls">
                        <label class="auto-refresh-toggle">
                            <input type="checkbox" id="autoRefresh" checked>
                            Auto-refresh
                        </label>
                        <select id="refreshInterval" class="refresh-select">
                            <option value="5">5s</option>
                            <option value="10" selected>10s</option>
                            <option value="30">30s</option>
                            <option value="60">1m</option>
                        </select>
                        <button class="btn btn-primary btn-refresh"
                                onclick="refreshAll()">
                            Refresh Now
                        </button>
                    </div>
                </div>
            </header>

            <!-- Active Jobs Section -->
            <section class="section">
                <h2>Active Jobs</h2>
                <div id="active-jobs-grid" class="active-jobs-grid"
                     hx-get="/api/interface/execution?fragment=active-jobs"
                     hx-trigger="load"
                     hx-indicator="#active-spinner">
                    <div class="loading-placeholder">Loading active jobs...</div>
                </div>
                <div id="active-spinner" class="htmx-indicator spinner-inline"></div>
            </section>

            <!-- All Jobs Section -->
            <section class="section">
                <div class="section-header">
                    <h2>All Jobs</h2>
                    <div class="filter-controls">
                        <select id="statusFilter" class="filter-select"
                                hx-get="/api/interface/execution?fragment=jobs-table"
                                hx-target="#jobs-table-body"
                                hx-include="#statusFilter, #typeFilter, #limitFilter"
                                hx-indicator="#table-spinner">
                            <option value="">All Status</option>
                            <option value="queued">Queued</option>
                            <option value="processing">Processing</option>
                            <option value="completed">Completed</option>
                            <option value="failed">Failed</option>
                        </select>
                        <select id="typeFilter" class="filter-select"
                                hx-get="/api/interface/execution?fragment=jobs-table"
                                hx-target="#jobs-table-body"
                                hx-include="#statusFilter, #typeFilter, #limitFilter"
                                hx-indicator="#table-spinner">
                            <option value="">All Types</option>
                            <option value="process_vector">Vector</option>
                            <option value="process_vector_docker">Vector (Docker)</option>
                            <option value="process_raster_v2">Raster</option>
                            <option value="process_raster_docker">Raster (Docker)</option>
                            <option value="process_raster_collection_v2">Collection</option>
                            <option value="process_raster_collection_docker">Collection (Docker)</option>
                        </select>
                        <select id="limitFilter" class="filter-select"
                                hx-get="/api/interface/execution?fragment=jobs-table"
                                hx-target="#jobs-table-body"
                                hx-include="#statusFilter, #typeFilter, #limitFilter"
                                hx-indicator="#table-spinner">
                            <option value="25">25 jobs</option>
                            <option value="50">50 jobs</option>
                            <option value="100">100 jobs</option>
                        </select>
                        <span id="table-spinner" class="htmx-indicator spinner-inline"></span>
                    </div>
                </div>
                <div class="table-container">
                    <table class="jobs-table">
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Type</th>
                                <th>Status</th>
                                <th>Progress</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="jobs-table-body"
                               hx-get="/api/interface/execution?fragment=jobs-table"
                               hx-trigger="load"
                               hx-indicator="#table-spinner">
                            <tr><td colspan="6" class="loading-cell">Loading jobs...</td></tr>
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
        '''

    def _generate_overview_js(self) -> str:
        """JavaScript for overview mode."""
        return '''
        let refreshInterval = null;
        let autoRefreshEnabled = true;

        function refreshAll() {
            htmx.trigger('#active-jobs-grid', 'htmx:trigger');
            htmx.trigger('#jobs-table-body', 'htmx:trigger');
        }

        function setupAutoRefresh() {
            const checkbox = document.getElementById('autoRefresh');
            const intervalSelect = document.getElementById('refreshInterval');

            function updateRefresh() {
                if (refreshInterval) clearInterval(refreshInterval);

                autoRefreshEnabled = checkbox.checked;
                if (autoRefreshEnabled) {
                    const seconds = parseInt(intervalSelect.value);
                    refreshInterval = setInterval(refreshAll, seconds * 1000);
                }
            }

            checkbox.addEventListener('change', updateRefresh);
            intervalSelect.addEventListener('change', updateRefresh);
            updateRefresh();
        }

        document.addEventListener('DOMContentLoaded', setupAutoRefresh);
        '''

    # =========================================================================
    # DETAIL MODE
    # =========================================================================

    def _render_detail_mode(self, job_id: str) -> str:
        """Render the detail dashboard (single job)."""
        job_id_short = job_id[:8] if len(job_id) > 8 else job_id

        return self.wrap_html(
            title=f"Job {job_id_short} - Execution",
            content=self._generate_detail_content(job_id),
            custom_css=self._generate_css(),
            custom_js=self._generate_detail_js(job_id),
            include_htmx=True
        )

    def _generate_detail_content(self, job_id: str) -> str:
        """Generate detail mode HTML content."""
        job_id_short = job_id[:8] if len(job_id) > 8 else job_id

        return f'''
        <div class="container">
            <header class="dashboard-header">
                <div class="header-row">
                    <div>
                        <a href="/api/interface/execution" class="back-link">&larr; Back to All Jobs</a>
                        <h1>Job Execution Detail</h1>
                        <p class="subtitle job-id-display">
                            <span class="job-id-label">Job ID:</span>
                            <code class="job-id-code">{job_id}</code>
                        </p>
                    </div>
                    <div class="header-controls">
                        <label class="auto-refresh-toggle">
                            <input type="checkbox" id="autoRefresh" checked>
                            Auto-refresh
                        </label>
                        <select id="refreshInterval" class="refresh-select">
                            <option value="3">3s</option>
                            <option value="5" selected>5s</option>
                            <option value="10">10s</option>
                            <option value="30">30s</option>
                        </select>
                        <button class="btn btn-primary btn-refresh"
                                onclick="refreshDetail()">
                            Refresh Now
                        </button>
                    </div>
                </div>
            </header>

            <!-- Progress & Metrics Row -->
            <div class="detail-grid">
                <section class="section progress-section">
                    <h2>Progress</h2>
                    <div id="job-progress"
                         hx-get="/api/interface/execution?fragment=job-progress&job_id={job_id}"
                         hx-trigger="load"
                         hx-indicator="#progress-spinner">
                        <div class="loading-placeholder">Loading progress...</div>
                    </div>
                    <span id="progress-spinner" class="htmx-indicator spinner-inline"></span>
                </section>

                <section class="section metrics-section">
                    <h2>Metrics</h2>
                    <div id="job-metrics">
                        <!-- Populated via job-progress fragment -->
                    </div>
                </section>
            </div>

            <!-- Workflow Stages -->
            <section class="section">
                <h2>Workflow Stages</h2>
                <div id="workflow-stages"
                     hx-get="/api/interface/execution?fragment=workflow-stages&job_id={job_id}"
                     hx-trigger="load"
                     hx-indicator="#stages-spinner">
                    <div class="loading-placeholder">Loading stages...</div>
                </div>
                <span id="stages-spinner" class="htmx-indicator spinner-inline"></span>
            </section>

            <!-- Tasks Table -->
            <section class="section">
                <div class="section-header">
                    <h2>Tasks</h2>
                    <div class="filter-controls">
                        <select id="stageFilter" class="filter-select"
                                hx-get="/api/interface/execution?fragment=tasks-table&job_id={job_id}"
                                hx-target="#tasks-table-body"
                                hx-include="#stageFilter, #taskStatusFilter"
                                hx-indicator="#tasks-spinner">
                            <option value="">All Stages</option>
                        </select>
                        <select id="taskStatusFilter" class="filter-select"
                                hx-get="/api/interface/execution?fragment=tasks-table&job_id={job_id}"
                                hx-target="#tasks-table-body"
                                hx-include="#stageFilter, #taskStatusFilter"
                                hx-indicator="#tasks-spinner">
                            <option value="">All Status</option>
                            <option value="pending">Pending</option>
                            <option value="queued">Queued</option>
                            <option value="processing">Processing</option>
                            <option value="completed">Completed</option>
                            <option value="failed">Failed</option>
                        </select>
                        <span id="tasks-spinner" class="htmx-indicator spinner-inline"></span>
                    </div>
                </div>
                <div class="table-container">
                    <table class="tasks-table">
                        <thead>
                            <tr>
                                <th>Task ID</th>
                                <th>Stage</th>
                                <th>Type</th>
                                <th>Status</th>
                                <th>Duration</th>
                                <th>Message</th>
                            </tr>
                        </thead>
                        <tbody id="tasks-table-body"
                               hx-get="/api/interface/execution?fragment=tasks-table&job_id={job_id}"
                               hx-trigger="load"
                               hx-indicator="#tasks-spinner">
                            <tr><td colspan="6" class="loading-cell">Loading tasks...</td></tr>
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
        '''

    def _generate_detail_js(self, job_id: str) -> str:
        """JavaScript for detail mode."""
        return f'''
        let refreshInterval = null;
        let autoRefreshEnabled = true;
        const JOB_ID = "{job_id}";

        function refreshDetail() {{
            htmx.trigger('#job-progress', 'htmx:trigger');
            htmx.trigger('#workflow-stages', 'htmx:trigger');
            htmx.trigger('#tasks-table-body', 'htmx:trigger');
        }}

        function setupAutoRefresh() {{
            const checkbox = document.getElementById('autoRefresh');
            const intervalSelect = document.getElementById('refreshInterval');

            function updateRefresh() {{
                if (refreshInterval) clearInterval(refreshInterval);

                autoRefreshEnabled = checkbox.checked;
                if (autoRefreshEnabled) {{
                    const seconds = parseInt(intervalSelect.value);
                    refreshInterval = setInterval(refreshDetail, seconds * 1000);
                }}
            }}

            checkbox.addEventListener('change', updateRefresh);
            intervalSelect.addEventListener('change', updateRefresh);
            updateRefresh();
        }}

        document.addEventListener('DOMContentLoaded', setupAutoRefresh);
        '''

    # =========================================================================
    # HTMX FRAGMENTS
    # =========================================================================

    def _render_active_jobs_fragment(self) -> str:
        """Render active jobs cards."""
        try:
            jobs = self._get_active_jobs()

            if not jobs:
                return '''
                <div class="empty-state">
                    <div class="empty-icon">📊</div>
                    <h3>No Active Jobs</h3>
                    <p>No jobs currently processing</p>
                </div>
                '''

            cards = []
            for job in jobs:
                cards.append(self._render_job_card(job))

            return '\n'.join(cards)

        except Exception as e:
            logger.error(f"Error loading active jobs: {e}", exc_info=True)
            return f'<div class="error-state">Error: {str(e)}</div>'

    def _render_jobs_table_fragment(self, request: func.HttpRequest) -> str:
        """Render jobs table rows."""
        status = request.params.get('status', '')
        job_type = request.params.get('type', '')
        limit = int(request.params.get('limit', '25'))

        try:
            jobs = self._query_jobs(status, job_type, limit)

            if not jobs:
                return '<tr><td colspan="6" class="empty-cell">No jobs found</td></tr>'

            rows = []
            for job in jobs:
                rows.append(self._render_job_row(job))

            return '\n'.join(rows)

        except Exception as e:
            logger.error(f"Error loading jobs: {e}", exc_info=True)
            return f'<tr><td colspan="6" class="error-cell">Error: {str(e)}</td></tr>'

    def _render_job_progress_fragment(self, job_id: str) -> str:
        """Render job progress panel."""
        try:
            job_info = self._get_job_info(job_id)
            metrics = self._get_job_metrics(job_id)

            if not job_info:
                return '<div class="error-state">Job not found</div>'

            status = job_info.get('status', 'unknown')
            job_type = job_info.get('job_type', 'unknown')

            # Get progress from metrics or estimate from tasks
            progress_pct = 0
            tasks_completed = 0
            tasks_total = 0
            stage_name = ''
            stage_num = 0
            total_stages = 1

            if metrics:
                payload = metrics.get('payload', {})
                progress = payload.get('progress', {})
                progress_pct = progress.get('progress_pct', 0)
                tasks_completed = progress.get('tasks_completed', 0)
                tasks_total = progress.get('tasks_total', 1)
                stage_name = progress.get('stage_name', '')
                stage_num = progress.get('stage', 0)
                total_stages = progress.get('total_stages', 1)

                # Render metrics panel
                rates = payload.get('rates', {})
                context = payload.get('context', {})
                metrics_html = self._render_metrics_panel(rates, context)
            else:
                # Fallback to task counts
                task_counts = self._get_task_counts(job_id)
                tasks_completed = task_counts.get('completed', 0) + task_counts.get('failed', 0)
                tasks_total = sum(task_counts.values()) or 1
                progress_pct = (tasks_completed / tasks_total) * 100
                metrics_html = '<div class="no-metrics">No real-time metrics available</div>'

            # Update metrics panel via OOB swap
            status_class = f"status-{status}"

            return f'''
            <div class="progress-panel">
                <div class="progress-header">
                    <span class="job-type">{job_type}</span>
                    <span class="status-badge {status_class}">{status}</span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: {progress_pct}%"></div>
                </div>
                <div class="progress-info">
                    <span class="progress-pct">{progress_pct:.1f}%</span>
                    <span class="progress-tasks">{tasks_completed}/{tasks_total} tasks</span>
                </div>
                {f'<div class="stage-info">Stage {stage_num}/{total_stages}: {stage_name}</div>' if stage_name else ''}
            </div>
            <div id="job-metrics" hx-swap-oob="innerHTML">{metrics_html}</div>
            '''

        except Exception as e:
            logger.error(f"Error loading job progress: {e}", exc_info=True)
            return f'<div class="error-state">Error: {str(e)}</div>'

    def _render_metrics_panel(self, rates: Dict, context: Dict) -> str:
        """Render metrics panel content."""
        tasks_per_min = rates.get('tasks_per_minute', 0)
        eta_seconds = rates.get('eta_seconds')

        # Format ETA
        if eta_seconds:
            if eta_seconds < 60:
                eta_str = f"{eta_seconds:.0f}s"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds / 60:.1f}m"
            else:
                eta_str = f"{eta_seconds / 3600:.1f}h"
        else:
            eta_str = "--"

        # Context-specific metrics
        ctx_type = context.get('type', '')
        context_html = ''

        if ctx_type == 'h3_aggregation':
            cells_processed = context.get('cells_processed', 0)
            cells_total = context.get('cells_total', 0)
            cells_rate = context.get('cells_rate_per_sec', 0)
            context_html = f'''
            <div class="metric-item context-metric h3">
                <span class="metric-icon">🔷</span>
                <span class="metric-value">{cells_processed:,}/{cells_total:,}</span>
                <span class="metric-label">H3 Cells ({cells_rate:.0f}/sec)</span>
            </div>
            '''
        elif ctx_type == 'fathom_etl':
            tiles_merged = context.get('tiles_merged', 0)
            bytes_gb = context.get('bytes_processed_gb', 0)
            context_html = f'''
            <div class="metric-item context-metric fathom">
                <span class="metric-icon">🌊</span>
                <span class="metric-value">{tiles_merged} tiles</span>
                <span class="metric-label">{bytes_gb:.2f} GB processed</span>
            </div>
            '''

        return f'''
        <div class="metrics-grid">
            <div class="metric-item">
                <span class="metric-icon">⚡</span>
                <span class="metric-value">{tasks_per_min:.1f}</span>
                <span class="metric-label">tasks/min</span>
            </div>
            <div class="metric-item">
                <span class="metric-icon">⏱️</span>
                <span class="metric-value">{eta_str}</span>
                <span class="metric-label">ETA</span>
            </div>
            {context_html}
        </div>
        '''

    def _render_workflow_stages_fragment(self, job_id: str) -> str:
        """Render workflow stages visualization."""
        try:
            stages = self._get_job_stages(job_id)
            task_counts_by_stage = self._get_task_counts_by_stage(job_id)

            if not stages:
                return '<div class="no-stages">No stage information available</div>'

            stage_cards = []
            for i, stage in enumerate(stages):
                stage_num = stage.get('number', i + 1)
                stage_name = stage.get('name', f'Stage {stage_num}')

                counts = task_counts_by_stage.get(stage_num, {})
                completed = counts.get('completed', 0)
                failed = counts.get('failed', 0)
                processing = counts.get('processing', 0)
                pending = counts.get('pending', 0) + counts.get('queued', 0)
                total = completed + failed + processing + pending

                # Determine stage status
                if total == 0:
                    status_icon = '⏳'
                    status_class = 'pending'
                elif failed > 0:
                    status_icon = '❌'
                    status_class = 'failed'
                elif processing > 0:
                    status_icon = '🔄'
                    status_class = 'processing'
                elif completed == total:
                    status_icon = '✅'
                    status_class = 'completed'
                else:
                    status_icon = '⏳'
                    status_class = 'pending'

                stage_cards.append(f'''
                <div class="stage-card {status_class}">
                    <div class="stage-icon">{status_icon}</div>
                    <div class="stage-name">{stage_name}</div>
                    <div class="stage-counts">{completed}/{total}</div>
                </div>
                ''')

                if i < len(stages) - 1:
                    stage_cards.append('<div class="stage-arrow">→</div>')

            # Populate stage filter dropdown via OOB
            stage_options = '<option value="">All Stages</option>'
            for stage in stages:
                stage_num = stage.get('number', 0)
                stage_name = stage.get('name', f'Stage {stage_num}')
                stage_options += f'<option value="{stage_num}">{stage_name}</option>'

            return f'''
            <div class="workflow-stages">
                {''.join(stage_cards)}
            </div>
            <select id="stageFilter" hx-swap-oob="innerHTML">{stage_options}</select>
            '''

        except Exception as e:
            logger.error(f"Error loading stages: {e}", exc_info=True)
            return f'<div class="error-state">Error: {str(e)}</div>'

    def _render_tasks_table_fragment(self, job_id: str, stage: str = '', status: str = '') -> str:
        """Render tasks table rows."""
        try:
            tasks = self._query_tasks(job_id, stage, status)

            if not tasks:
                return '<tr><td colspan="6" class="empty-cell">No tasks found</td></tr>'

            rows = []
            for task in tasks:
                rows.append(self._render_task_row(task))

            return '\n'.join(rows)

        except Exception as e:
            logger.error(f"Error loading tasks: {e}", exc_info=True)
            return f'<tr><td colspan="6" class="error-cell">Error: {str(e)}</td></tr>'

    # =========================================================================
    # RENDER HELPERS
    # =========================================================================

    def _render_job_card(self, job: Dict[str, Any]) -> str:
        """Render a single active job card."""
        job_id = job.get('job_id', 'unknown')
        job_id_short = job_id[:8] if job_id else '??'
        job_type = job.get('job_type', 'unknown')
        job_status = job.get('job_status', 'unknown')
        payload = job.get('payload', {})

        progress = payload.get('progress', {})
        rates = payload.get('rates', {})

        progress_pct = progress.get('progress_pct', 0)
        tasks_completed = progress.get('tasks_completed', 0)
        tasks_total = progress.get('tasks_total', 1)
        tasks_per_min = rates.get('tasks_per_minute', 0)
        eta_seconds = rates.get('eta_seconds')

        # Format ETA
        if eta_seconds:
            if eta_seconds < 60:
                eta_str = f"{eta_seconds:.0f}s"
            elif eta_seconds < 3600:
                eta_str = f"{eta_seconds / 60:.1f}m"
            else:
                eta_str = f"{eta_seconds / 3600:.1f}h"
        else:
            eta_str = "--"

        status_class = f"status-{job_status}"

        return f'''
        <a href="/api/interface/execution?job_id={job_id}" class="job-card">
            <div class="card-header">
                <span class="job-id">{job_id_short}</span>
                <span class="status-badge {status_class}">{job_status}</span>
            </div>
            <div class="job-type">{job_type}</div>
            <div class="progress-bar-container">
                <div class="progress-bar" style="width: {progress_pct}%"></div>
            </div>
            <div class="card-footer">
                <span class="progress-text">{progress_pct:.0f}% ({tasks_completed}/{tasks_total})</span>
                <span class="eta-text">ETA: {eta_str}</span>
            </div>
        </a>
        '''

    def _render_job_row(self, job: Dict[str, Any]) -> str:
        """Render a single job table row."""
        job_id = job.get('job_id', job.get('id', ''))
        job_id_short = job_id[:8] if job_id else '--'
        job_type = job.get('job_type', '--')
        status = job.get('status', 'unknown')
        created = job.get('created_at', '')

        # Format created timestamp
        if created:
            created_str = str(created)[:19]
        else:
            created_str = '--'

        # Get task counts for progress
        task_counts = job.get('task_counts', {})
        completed = task_counts.get('completed', 0)
        total = sum(task_counts.values()) if task_counts else 0
        progress_pct = (completed / total * 100) if total > 0 else 0

        status_class = f"status-{status}"

        return f'''
        <tr>
            <td><code class="job-id-code">{job_id_short}</code></td>
            <td>{job_type}</td>
            <td><span class="status-badge {status_class}">{status}</span></td>
            <td>
                <div class="progress-bar-mini">
                    <div class="progress-fill" style="width: {progress_pct}%"></div>
                </div>
                <span class="progress-text-mini">{progress_pct:.0f}%</span>
            </td>
            <td class="timestamp">{created_str}</td>
            <td>
                <a href="/api/interface/execution?job_id={job_id}" class="btn btn-sm">View &rarr;</a>
            </td>
        </tr>
        '''

    def _render_task_row(self, task: Dict[str, Any]) -> str:
        """Render a single task table row."""
        task_id = task.get('task_id', task.get('id', ''))
        task_id_short = task_id[:8] if task_id else '--'
        stage = task.get('stage', '--')
        task_type = task.get('task_type', '--')
        status = task.get('status', 'unknown')
        duration = task.get('duration_seconds', 0)
        error_message = task.get('error_message', '')

        # Format duration
        if duration:
            if duration < 60:
                duration_str = f"{duration:.1f}s"
            elif duration < 3600:
                duration_str = f"{duration / 60:.1f}m"
            else:
                duration_str = f"{duration / 3600:.1f}h"
        else:
            duration_str = '--'

        # Status message
        message = error_message if error_message else ('OK' if status == 'completed' else '')

        status_class = f"status-{status}"

        return f'''
        <tr class="{status_class}-row">
            <td><code>{task_id_short}</code></td>
            <td>{stage}</td>
            <td>{task_type}</td>
            <td><span class="status-badge {status_class}">{status}</span></td>
            <td>{duration_str}</td>
            <td class="message-cell" title="{message}">{message[:50]}{'...' if len(message) > 50 else ''}</td>
        </tr>
        '''

    # =========================================================================
    # DATA ACCESS
    # =========================================================================

    def _get_active_jobs(self) -> List[Dict[str, Any]]:
        """Get active jobs with recent metrics."""
        try:
            from infrastructure.metrics_repository import MetricsRepository
            repo = MetricsRepository()
            return repo.get_active_jobs(minutes=15)
        except Exception as e:
            logger.warning(f"Could not get metrics: {e}")
            return []

    def _get_job_metrics(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific job."""
        try:
            from infrastructure.metrics_repository import MetricsRepository
            repo = MetricsRepository()
            return repo.get_job_summary(job_id)
        except Exception as e:
            logger.warning(f"Could not get job metrics: {e}")
            return None

    def _query_jobs(self, status: str = '', job_type: str = '', limit: int = 25) -> List[Dict[str, Any]]:
        """
        Query jobs from database.

        V0.8.16 (09 FEB 2026): Refactored to use JobRepository.list_jobs_with_filters()
        """
        try:
            from infrastructure import JobRepository
            from core.models import JobStatus

            job_repo = JobRepository()

            # Convert status string to enum if provided
            status_enum = None
            if status:
                try:
                    status_enum = JobStatus(status)
                except ValueError:
                    pass

            jobs = job_repo.list_jobs_with_filters(
                status=status_enum,
                job_type=job_type if job_type else None,
                limit=limit
            )

            # Convert JobRecord objects to dicts
            return [
                {
                    'job_id': j.job_id,
                    'job_type': j.job_type,
                    'status': j.status.value if hasattr(j.status, 'value') else j.status,
                    'created_at': j.created_at,
                    'parameters': j.parameters
                }
                for j in jobs
            ]

        except Exception as e:
            logger.error(f"Error querying jobs: {e}")
            return []

    def _get_job_info(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job info from database.

        V0.8.16 (09 FEB 2026): Refactored to use JobRepository.get_job_summary()
        """
        try:
            from infrastructure import JobRepository

            job_repo = JobRepository()
            return job_repo.get_job_summary(job_id)

        except Exception as e:
            logger.error(f"Error getting job info: {e}")
            return None

    def _get_job_stages(self, job_id: str) -> List[Dict[str, Any]]:
        """Get stage definitions for a job."""
        try:
            job_info = self._get_job_info(job_id)
            if not job_info:
                return []

            job_type = job_info.get('job_type', '')

            # Get job class to get stages
            from jobs import JOB_REGISTRY
            job_class = JOB_REGISTRY.get(job_type)

            if job_class and hasattr(job_class, 'stages'):
                return job_class.stages

            return []

        except Exception as e:
            logger.error(f"Error getting job stages: {e}")
            return []

    def _get_task_counts(self, job_id: str) -> Dict[str, int]:
        """
        Get task counts by status for a job.

        V0.8.16 (09 FEB 2026): Refactored to use TaskRepository.get_task_counts_for_job()
        """
        try:
            from infrastructure import TaskRepository

            task_repo = TaskRepository()
            return task_repo.get_task_counts_for_job(job_id)

        except Exception as e:
            logger.error(f"Error getting task counts: {e}")
            return {}

    def _get_task_counts_by_stage(self, job_id: str) -> Dict[int, Dict[str, int]]:
        """
        Get task counts by stage and status.

        V0.8.16 (09 FEB 2026): Refactored to use TaskRepository.get_task_counts_by_stage()
        """
        try:
            from infrastructure import TaskRepository

            task_repo = TaskRepository()
            rows = task_repo.get_task_counts_by_stage(job_id)

            # Convert list to nested dict format expected by caller
            counts = {}
            for row in rows:
                stage = row.get('stage', 0)
                status = row.get('status', 'unknown')
                count = row.get('count', 0)

                if stage not in counts:
                    counts[stage] = {}
                counts[stage][status] = count

            return counts

        except Exception as e:
            logger.error(f"Error getting task counts by stage: {e}")
            return {}

    def _query_tasks(self, job_id: str, stage: str = '', status: str = '') -> List[Dict[str, Any]]:
        """
        Query tasks for a job.

        V0.8.16 (09 FEB 2026): Refactored to use TaskRepository.list_tasks_with_filters()
        """
        try:
            from infrastructure import TaskRepository

            task_repo = TaskRepository()

            # Convert stage to int if provided
            stage_num = int(stage) if stage else None

            tasks = task_repo.list_tasks_with_filters(
                job_id=job_id,
                status=status if status else None,
                stage=stage_num,
                limit=100
            )

            return tasks

        except Exception as e:
            logger.error(f"Error querying tasks: {e}")
            return []

    # =========================================================================
    # CSS
    # =========================================================================

    def _generate_css(self) -> str:
        """Generate CSS for both modes."""
        return '''
            /* Layout */
            .header-row {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                flex-wrap: wrap;
                gap: 16px;
            }

            .header-controls {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .back-link {
                display: inline-block;
                color: var(--ds-blue-primary);
                text-decoration: none;
                margin-bottom: 8px;
                font-size: 14px;
            }

            .back-link:hover {
                text-decoration: underline;
            }

            .job-id-display {
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .job-id-code {
                background: var(--ds-bg);
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                color: var(--ds-navy);
            }

            /* Auto-refresh controls */
            .auto-refresh-toggle {
                display: flex;
                align-items: center;
                gap: 6px;
                font-size: 14px;
                color: var(--ds-gray);
            }

            .refresh-select, .filter-select {
                padding: 6px 10px;
                border: 1px solid var(--ds-gray-light);
                border-radius: 4px;
                font-size: 13px;
            }

            .btn-refresh {
                padding: 8px 16px;
                font-size: 13px;
            }

            /* Section */
            .section {
                background: white;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            }

            .section h2 {
                margin: 0 0 16px 0;
                font-size: 18px;
                color: var(--ds-navy);
                padding-bottom: 12px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .section-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 16px;
            }

            .section-header h2 {
                margin: 0;
                padding: 0;
                border: none;
            }

            .filter-controls {
                display: flex;
                gap: 10px;
                align-items: center;
            }

            /* Detail grid */
            .detail-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
            }

            @media (max-width: 768px) {
                .detail-grid {
                    grid-template-columns: 1fr;
                }
            }

            /* Active jobs grid */
            .active-jobs-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
                gap: 16px;
            }

            /* Job card */
            .job-card {
                display: block;
                background: var(--ds-bg);
                border: 2px solid var(--ds-gray-light);
                border-radius: 8px;
                padding: 16px;
                text-decoration: none;
                color: inherit;
                transition: all 0.2s;
            }

            .job-card:hover {
                border-color: var(--ds-blue-primary);
                box-shadow: 0 4px 12px rgba(0,113,188,0.15);
                transform: translateY(-2px);
            }

            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            }

            .job-id {
                font-family: monospace;
                font-size: 13px;
                color: var(--ds-gray);
            }

            .job-type {
                font-weight: 600;
                color: var(--ds-navy);
                margin-bottom: 12px;
                font-size: 14px;
            }

            .card-footer {
                display: flex;
                justify-content: space-between;
                font-size: 12px;
                color: var(--ds-gray);
                margin-top: 8px;
            }

            /* Progress bar */
            .progress-bar-container {
                height: 8px;
                background: var(--ds-gray-light);
                border-radius: 4px;
                overflow: hidden;
            }

            .progress-bar {
                height: 100%;
                background: linear-gradient(90deg, var(--ds-blue-primary), var(--ds-cyan));
                border-radius: 4px;
                transition: width 0.3s ease;
            }

            .progress-bar-mini {
                display: inline-block;
                width: 60px;
                height: 6px;
                background: var(--ds-gray-light);
                border-radius: 3px;
                overflow: hidden;
                vertical-align: middle;
            }

            .progress-fill {
                height: 100%;
                background: var(--ds-blue-primary);
            }

            .progress-text-mini {
                font-size: 11px;
                color: var(--ds-gray);
                margin-left: 6px;
            }

            /* Progress panel */
            .progress-panel {
                padding: 16px;
                background: var(--ds-bg);
                border-radius: 8px;
            }

            .progress-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 12px;
            }

            .progress-info {
                display: flex;
                justify-content: space-between;
                margin-top: 8px;
                font-size: 13px;
            }

            .progress-pct {
                font-weight: 700;
                color: var(--ds-blue-primary);
            }

            .progress-tasks {
                color: var(--ds-gray);
            }

            .stage-info {
                margin-top: 8px;
                font-size: 12px;
                color: var(--ds-gray);
            }

            /* Metrics */
            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
                gap: 16px;
            }

            .metric-item {
                text-align: center;
                padding: 12px;
                background: var(--ds-bg);
                border-radius: 8px;
            }

            .metric-icon {
                display: block;
                font-size: 20px;
                margin-bottom: 4px;
            }

            .metric-value {
                display: block;
                font-size: 20px;
                font-weight: 700;
                color: var(--ds-blue-primary);
            }

            .metric-label {
                display: block;
                font-size: 11px;
                color: var(--ds-gray);
                text-transform: uppercase;
            }

            .context-metric.h3 { border-left: 3px solid #10b981; }
            .context-metric.fathom { border-left: 3px solid #8b5cf6; }

            .no-metrics {
                text-align: center;
                color: var(--ds-gray);
                padding: 20px;
            }

            /* Workflow stages */
            .workflow-stages {
                display: flex;
                align-items: center;
                gap: 8px;
                flex-wrap: wrap;
                justify-content: center;
            }

            .stage-card {
                text-align: center;
                padding: 16px 20px;
                background: var(--ds-bg);
                border: 2px solid var(--ds-gray-light);
                border-radius: 8px;
                min-width: 100px;
            }

            .stage-card.completed {
                border-color: #10b981;
                background: #f0fdf4;
            }

            .stage-card.processing {
                border-color: var(--ds-blue-primary);
                background: #eff6ff;
            }

            .stage-card.failed {
                border-color: #ef4444;
                background: #fef2f2;
            }

            .stage-icon {
                font-size: 24px;
                margin-bottom: 4px;
            }

            .stage-name {
                font-weight: 600;
                font-size: 13px;
                color: var(--ds-navy);
                margin-bottom: 4px;
            }

            .stage-counts {
                font-size: 12px;
                color: var(--ds-gray);
            }

            .stage-arrow {
                font-size: 20px;
                color: var(--ds-gray-light);
            }

            .no-stages {
                text-align: center;
                color: var(--ds-gray);
                padding: 20px;
            }

            /* Tables */
            .table-container {
                overflow-x: auto;
            }

            .jobs-table, .tasks-table {
                width: 100%;
                border-collapse: collapse;
            }

            .jobs-table th, .tasks-table th {
                text-align: left;
                padding: 12px;
                background: var(--ds-bg);
                font-weight: 600;
                font-size: 13px;
                color: var(--ds-navy);
                border-bottom: 2px solid var(--ds-gray-light);
            }

            .jobs-table td, .tasks-table td {
                padding: 12px;
                border-bottom: 1px solid var(--ds-gray-light);
                font-size: 13px;
            }

            .jobs-table tr:hover, .tasks-table tr:hover {
                background: var(--ds-bg);
            }

            .timestamp {
                font-family: monospace;
                font-size: 12px;
                color: var(--ds-gray);
            }

            .message-cell {
                max-width: 200px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .loading-cell, .empty-cell, .error-cell {
                text-align: center;
                color: var(--ds-gray);
                padding: 24px;
            }

            .error-cell {
                color: #ef4444;
            }

            .failed-row {
                background: #fef2f2;
            }

            /* Status badges */
            .status-badge {
                display: inline-block;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
            }

            .status-queued { background: #fef3c7; color: #92400e; }
            .status-processing { background: #dbeafe; color: #1e40af; }
            .status-completed { background: #d1fae5; color: #065f46; }
            .status-failed { background: #fee2e2; color: #991b1b; }
            .status-pending { background: #f3f4f6; color: #6b7280; }
            .status-unknown { background: #f3f4f6; color: #6b7280; }

            /* Empty/error states */
            .empty-state, .error-state {
                text-align: center;
                padding: 40px;
                color: var(--ds-gray);
            }

            .empty-icon {
                font-size: 48px;
                margin-bottom: 12px;
            }

            .empty-state h3 {
                margin: 0 0 8px 0;
                color: var(--ds-navy);
            }

            .error-state {
                color: #ef4444;
                background: #fef2f2;
                border-radius: 8px;
            }

            /* Utilities */
            .loading-placeholder {
                text-align: center;
                color: var(--ds-gray);
                padding: 20px;
            }

            .spinner-inline {
                display: inline-block;
                width: 16px;
                height: 16px;
                border: 2px solid var(--ds-gray-light);
                border-top-color: var(--ds-blue-primary);
                border-radius: 50%;
                animation: spin 0.8s linear infinite;
            }

            .htmx-indicator {
                display: none;
            }

            .htmx-request .htmx-indicator,
            .htmx-indicator.htmx-request {
                display: inline-block;
            }

            @keyframes spin {
                to { transform: rotate(360deg); }
            }

            .btn-sm {
                padding: 4px 10px;
                font-size: 12px;
                background: var(--ds-blue-primary);
                color: white;
                border: none;
                border-radius: 4px;
                text-decoration: none;
                cursor: pointer;
            }

            .btn-sm:hover {
                background: var(--ds-cyan);
            }
        '''
