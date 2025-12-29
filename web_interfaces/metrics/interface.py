# ============================================================================
# CLAUDE CONTEXT - METRICS INTERFACE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Web Interface - Pipeline Observability Dashboard
# PURPOSE: Real-time job progress monitoring with HTMX live updates
# LAST_REVIEWED: 28 DEC 2025
# EXPORTS: MetricsInterface
# DEPENDENCIES: web_interfaces.base, infrastructure.metrics_repository
# ============================================================================
"""
Pipeline Monitor Interface.

Real-time dashboard for monitoring long-running jobs with progress bars,
rates, and ETAs. Uses HTMX for live updates without full page refresh.

Features (E13: Pipeline Observability - 28 DEC 2025):
    - Active jobs grid with real-time progress
    - Rate calculations (tasks/minute, cells/second)
    - ETA estimation
    - Context-specific metrics (H3, FATHOM, Raster)
    - Auto-refresh with polling
    - Job details panel

Routes:
    /api/interface/metrics - Full dashboard
    /api/interface/metrics?fragment=active-jobs - HTMX partial (active jobs)
    /api/interface/metrics?fragment=job-details&job_id=X - HTMX partial (job details)

Exports:
    MetricsInterface: Pipeline monitoring dashboard with HTMX interactivity
"""

import logging
from typing import Dict, Any, List, Optional

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('metrics')
class MetricsInterface(BaseInterface):
    """
    Pipeline Monitor Dashboard with HTMX live updates.

    Displays real-time progress for active jobs including:
    - Progress bars with completion percentages
    - Rate metrics (tasks/minute, cells/second)
    - ETA estimation
    - Context-specific fields per job type

    Fragments supported:
        - active-jobs: Returns job cards grid
        - job-details: Returns detailed panel for specific job
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Pipeline Monitor dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        return self.wrap_html(
            title="Pipeline Monitor",
            content=self._generate_html_content(),
            custom_css=self._generate_css(),
            custom_js=self._generate_js(),
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """
        Handle HTMX partial requests.

        Fragments:
            active-jobs: Returns job cards grid
            job-details: Returns detailed panel for specific job

        Args:
            request: Azure Functions HttpRequest
            fragment: Fragment name to render

        Returns:
            HTML fragment string
        """
        if fragment == 'active-jobs':
            return self._render_active_jobs_fragment(request)
        elif fragment == 'job-details':
            job_id = request.params.get('job_id')
            if not job_id:
                return '<div class="error-state">Job ID required</div>'
            return self._render_job_details_fragment(job_id)
        else:
            raise ValueError(f"Unknown fragment: {fragment}")

    def _render_active_jobs_fragment(self, request: func.HttpRequest) -> str:
        """Render active jobs cards via HTMX."""
        try:
            jobs = self._get_active_jobs()

            if not jobs:
                return '''
                <div class="empty-state">
                    <div class="icon" style="font-size: 48px;">📊</div>
                    <h3>No Active Jobs</h3>
                    <p>No jobs with recent metrics activity</p>
                </div>
                '''

            cards = []
            for job in jobs:
                cards.append(self._render_job_card(job))

            return '\n'.join(cards)

        except Exception as e:
            logger.error(f"Error loading active jobs: {e}", exc_info=True)
            return f'''
            <div class="error-state">
                <p>Error loading jobs: {str(e)}</p>
            </div>
            '''

    def _render_job_details_fragment(self, job_id: str) -> str:
        """Render job details panel via HTMX."""
        try:
            details = self._get_job_details(job_id)

            if not details:
                return f'''
                <div class="error-state">
                    <p>No metrics found for job {job_id[:8]}...</p>
                </div>
                '''

            return self._render_details_panel(details)

        except Exception as e:
            logger.error(f"Error loading job details: {e}", exc_info=True)
            return f'''
            <div class="error-state">
                <p>Error: {str(e)}</p>
            </div>
            '''

    def _get_active_jobs(self) -> List[Dict[str, Any]]:
        """Get active jobs with recent metrics."""
        from infrastructure.metrics_repository import MetricsRepository

        repo = MetricsRepository()
        return repo.get_active_jobs(minutes=15)

    def _get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed metrics for a job."""
        from infrastructure.metrics_repository import MetricsRepository

        repo = MetricsRepository()
        return repo.get_job_summary(job_id)

    def _render_job_card(self, job: Dict[str, Any]) -> str:
        """Render a single job card."""
        job_id = job.get('job_id', 'unknown')
        job_id_short = job_id[:8] if job_id else '??'
        job_type = job.get('job_type', 'unknown')
        job_status = job.get('job_status', 'unknown')
        payload = job.get('payload', {})

        # Extract progress info from payload
        progress = payload.get('progress', {})
        rates = payload.get('rates', {})
        context = payload.get('context', {})

        tasks_completed = progress.get('tasks_completed', 0)
        tasks_total = progress.get('tasks_total', 1)
        progress_pct = progress.get('progress_pct', 0)
        stage = progress.get('stage', 0)
        total_stages = progress.get('total_stages', 1)
        stage_name = progress.get('stage_name', '')

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
        context_html = self._render_context_metrics(context)

        # Status badge class
        status_class = f"status-{job_status}" if job_status else "status-unknown"

        return f'''
        <div class="job-card"
             hx-get="/api/interface/metrics?fragment=job-details&job_id={job_id}"
             hx-target="#job-details-panel"
             hx-trigger="click">
            <div class="job-header">
                <span class="job-id" title="{job_id}">{job_id_short}</span>
                <span class="status-badge {status_class}">{job_status}</span>
            </div>
            <div class="job-type">{job_type}</div>

            <div class="progress-section">
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: {progress_pct}%"></div>
                </div>
                <div class="progress-text">{progress_pct:.1f}% ({tasks_completed}/{tasks_total})</div>
            </div>

            <div class="stage-info">
                Stage {stage}/{total_stages}: {stage_name}
            </div>

            <div class="metrics-row">
                <div class="metric">
                    <span class="metric-value">{tasks_per_min:.1f}</span>
                    <span class="metric-label">tasks/min</span>
                </div>
                <div class="metric">
                    <span class="metric-value">{eta_str}</span>
                    <span class="metric-label">ETA</span>
                </div>
            </div>

            {context_html}
        </div>
        '''

    def _render_context_metrics(self, context: Dict[str, Any]) -> str:
        """Render context-specific metrics based on type."""
        ctx_type = context.get('type', '')

        if ctx_type == 'h3_aggregation':
            cells_processed = context.get('cells_processed', 0)
            cells_total = context.get('cells_total', 0)
            cells_rate = context.get('cells_rate_per_sec', 0)
            stats_computed = context.get('stats_computed', 0)

            return f'''
            <div class="context-metrics h3-context">
                <div class="context-label">H3 Aggregation</div>
                <div class="context-row">
                    <span>Cells: {cells_processed:,}/{cells_total:,}</span>
                    <span>{cells_rate:.0f} cells/sec</span>
                </div>
                <div class="context-row">
                    <span>Stats: {stats_computed:,}</span>
                </div>
            </div>
            '''

        elif ctx_type == 'fathom_etl':
            tiles_merged = context.get('tiles_merged', 0)
            tiles_total = context.get('tiles_total', 0)
            bytes_gb = context.get('bytes_processed_gb', 0)

            return f'''
            <div class="context-metrics fathom-context">
                <div class="context-label">FATHOM ETL</div>
                <div class="context-row">
                    <span>Tiles: {tiles_merged}/{tiles_total}</span>
                    <span>{bytes_gb:.2f} GB</span>
                </div>
            </div>
            '''

        elif ctx_type == 'raster_collection':
            files_processed = context.get('files_processed', 0)
            files_total = context.get('files_total', 0)
            output_gb = context.get('output_size_gb', 0)

            return f'''
            <div class="context-metrics raster-context">
                <div class="context-label">Raster Collection</div>
                <div class="context-row">
                    <span>Files: {files_processed}/{files_total}</span>
                    <span>{output_gb:.2f} GB</span>
                </div>
            </div>
            '''

        return ''

    def _render_details_panel(self, details: Dict[str, Any]) -> str:
        """Render detailed job panel."""
        job_id = details.get('job_id', 'unknown')
        total_snapshots = details.get('total_snapshots', 0)
        first_activity = details.get('first_activity', '')
        last_activity = details.get('last_activity', '')
        duration_seconds = details.get('duration_seconds', 0)
        latest_payload = details.get('latest_payload', {})

        # Format duration
        if duration_seconds:
            if duration_seconds < 60:
                duration_str = f"{duration_seconds:.0f}s"
            elif duration_seconds < 3600:
                duration_str = f"{duration_seconds / 60:.1f}m"
            else:
                duration_str = f"{duration_seconds / 3600:.1f}h"
        else:
            duration_str = "--"

        # Format timestamps
        first_str = str(first_activity)[:19] if first_activity else '--'
        last_str = str(last_activity)[:19] if last_activity else '--'

        # Recent events
        events_html = ''
        recent_events = latest_payload.get('recent_events', [])
        if recent_events:
            events_items = []
            for event in recent_events[-5:]:
                event_type = event.get('type', 'unknown')
                timestamp = event.get('timestamp', '')[:19]
                events_items.append(f'<li><span class="event-type">{event_type}</span> <span class="event-time">{timestamp}</span></li>')
            events_html = f'''
            <div class="events-section">
                <h4>Recent Events</h4>
                <ul class="events-list">
                    {''.join(events_items)}
                </ul>
            </div>
            '''

        return f'''
        <div class="details-panel">
            <h3>Job Details</h3>
            <div class="detail-row">
                <span class="detail-label">Job ID:</span>
                <span class="detail-value">{job_id}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Duration:</span>
                <span class="detail-value">{duration_str}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Snapshots:</span>
                <span class="detail-value">{total_snapshots}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">First Activity:</span>
                <span class="detail-value">{first_str}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Last Activity:</span>
                <span class="detail-value">{last_str}</span>
            </div>
            {events_html}
        </div>
        '''

    def _generate_html_content(self) -> str:
        """Generate main content HTML."""
        return '''
        <div class="container">
            <header class="dashboard-header">
                <h1>Pipeline Monitor</h1>
                <p class="subtitle">Real-time job progress and metrics (E13)</p>
                <div class="header-actions">
                    <label class="auto-refresh-toggle">
                        <input type="checkbox" id="autoRefresh" checked>
                        Auto-refresh (5s)
                    </label>
                    <button class="btn btn-primary"
                            hx-get="/api/interface/metrics?fragment=active-jobs"
                            hx-target="#active-jobs-grid"
                            hx-indicator="#loading-spinner">
                        Refresh Now
                    </button>
                </div>
            </header>

            <!-- Loading Spinner -->
            <div id="loading-spinner" class="htmx-indicator spinner-container">
                <div class="spinner"></div>
                <div class="spinner-text">Loading metrics...</div>
            </div>

            <!-- Main Content Grid -->
            <div class="metrics-layout">
                <!-- Active Jobs Grid -->
                <div class="jobs-section">
                    <h2>Active Jobs</h2>
                    <div id="active-jobs-grid" class="jobs-grid"
                         hx-get="/api/interface/metrics?fragment=active-jobs"
                         hx-trigger="load, every 5s [autoRefreshEnabled]"
                         hx-indicator="#loading-spinner">
                        <!-- Loaded via HTMX -->
                    </div>
                </div>

                <!-- Details Panel -->
                <div class="details-section">
                    <div id="job-details-panel">
                        <div class="empty-state">
                            <p>Click a job card to view details</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        '''

    def _generate_css(self) -> str:
        """Pipeline monitor specific styles."""
        return '''
            /* Layout */
            .metrics-layout {
                display: grid;
                grid-template-columns: 1fr 350px;
                gap: 20px;
            }

            @media (max-width: 1024px) {
                .metrics-layout {
                    grid-template-columns: 1fr;
                }
            }

            .jobs-section h2 {
                margin: 0 0 16px 0;
                color: var(--ds-navy);
                font-size: 18px;
            }

            /* Jobs Grid */
            .jobs-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 16px;
            }

            /* Job Card */
            .job-card {
                background: white;
                border: 2px solid var(--ds-gray-light);
                border-radius: 8px;
                padding: 16px;
                cursor: pointer;
                transition: all 0.2s;
            }

            .job-card:hover {
                border-color: var(--ds-blue-primary);
                box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            }

            .job-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            }

            .job-id {
                font-family: monospace;
                font-size: 14px;
                color: var(--ds-gray);
            }

            .job-type {
                font-weight: 600;
                color: var(--ds-navy);
                margin-bottom: 12px;
            }

            /* Progress Bar */
            .progress-section {
                margin-bottom: 12px;
            }

            .progress-bar-container {
                height: 8px;
                background: var(--ds-gray-light);
                border-radius: 4px;
                overflow: hidden;
                margin-bottom: 4px;
            }

            .progress-bar {
                height: 100%;
                background: linear-gradient(90deg, var(--ds-blue-primary), var(--ds-cyan));
                border-radius: 4px;
                transition: width 0.3s ease;
            }

            .progress-text {
                font-size: 12px;
                color: var(--ds-gray);
                text-align: right;
            }

            .stage-info {
                font-size: 12px;
                color: var(--ds-gray);
                margin-bottom: 12px;
            }

            /* Metrics Row */
            .metrics-row {
                display: flex;
                gap: 16px;
                padding-top: 12px;
                border-top: 1px solid var(--ds-gray-light);
            }

            .metric {
                display: flex;
                flex-direction: column;
                align-items: center;
            }

            .metric-value {
                font-size: 18px;
                font-weight: 700;
                color: var(--ds-blue-primary);
            }

            .metric-label {
                font-size: 10px;
                color: var(--ds-gray);
                text-transform: uppercase;
            }

            /* Context Metrics */
            .context-metrics {
                margin-top: 12px;
                padding: 8px;
                background: var(--ds-bg);
                border-radius: 4px;
                font-size: 12px;
            }

            .context-label {
                font-weight: 600;
                color: var(--ds-navy);
                margin-bottom: 4px;
            }

            .context-row {
                display: flex;
                justify-content: space-between;
                color: var(--ds-gray);
            }

            .h3-context { border-left: 3px solid #10b981; }
            .fathom-context { border-left: 3px solid #8b5cf6; }
            .raster-context { border-left: 3px solid #f59e0b; }

            /* Details Section */
            .details-section {
                background: white;
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.08);
                height: fit-content;
                position: sticky;
                top: 20px;
            }

            .details-panel h3 {
                margin: 0 0 16px 0;
                color: var(--ds-navy);
                font-size: 16px;
                padding-bottom: 12px;
                border-bottom: 2px solid var(--ds-blue-primary);
            }

            .detail-row {
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                border-bottom: 1px solid var(--ds-gray-light);
            }

            .detail-label {
                color: var(--ds-gray);
                font-size: 13px;
            }

            .detail-value {
                font-weight: 500;
                color: var(--ds-navy);
                font-size: 13px;
                word-break: break-all;
            }

            /* Events */
            .events-section {
                margin-top: 16px;
            }

            .events-section h4 {
                margin: 0 0 8px 0;
                font-size: 14px;
                color: var(--ds-navy);
            }

            .events-list {
                list-style: none;
                padding: 0;
                margin: 0;
            }

            .events-list li {
                padding: 6px 0;
                border-bottom: 1px solid var(--ds-gray-light);
                font-size: 12px;
                display: flex;
                justify-content: space-between;
            }

            .event-type {
                color: var(--ds-navy);
                font-weight: 500;
            }

            .event-time {
                color: var(--ds-gray);
                font-family: monospace;
            }

            /* Header Actions */
            .header-actions {
                display: flex;
                align-items: center;
                gap: 16px;
                margin-top: 12px;
            }

            .auto-refresh-toggle {
                display: flex;
                align-items: center;
                gap: 8px;
                cursor: pointer;
                font-size: 14px;
                color: var(--ds-gray);
            }

            .auto-refresh-toggle input {
                width: 16px;
                height: 16px;
            }

            /* Fix: Ensure spinner-container respects htmx-indicator */
            .spinner-container.htmx-indicator {
                display: none !important;
            }
            .spinner-container.htmx-indicator.htmx-request {
                display: flex !important;
            }
        '''

    def _generate_js(self) -> str:
        """JavaScript for auto-refresh toggle."""
        return '''
        // Auto-refresh control
        let autoRefreshEnabled = true;

        document.addEventListener('DOMContentLoaded', () => {
            const checkbox = document.getElementById('autoRefresh');
            if (checkbox) {
                checkbox.addEventListener('change', (e) => {
                    autoRefreshEnabled = e.target.checked;
                    // Update HTMX trigger by setting/removing attribute
                    const grid = document.getElementById('active-jobs-grid');
                    if (grid) {
                        if (autoRefreshEnabled) {
                            grid.setAttribute('hx-trigger', 'load, every 5s');
                        } else {
                            grid.setAttribute('hx-trigger', 'load');
                        }
                        htmx.process(grid);
                    }
                });
            }
        });

        // Make autoRefreshEnabled available to HTMX triggers
        window.autoRefreshEnabled = true;
        '''
