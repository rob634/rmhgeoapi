"""
Job monitor interface module.

Web dashboard for monitoring jobs and tasks with filtering and refresh capabilities.

Features (24 DEC 2025 - S12.3.1):
    - HTMX-powered filtering and auto-refresh
    - Uses BaseInterface component helpers
    - Reduced JavaScript, server-side rendering

Exports:
    JobsInterface: Job monitoring dashboard with stage progress and task status counts
"""

import logging
from typing import Dict, Any, List

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry

logger = logging.getLogger(__name__)


@InterfaceRegistry.register('jobs')
class JobsInterface(BaseInterface):
    """
    Job Monitor Dashboard interface with HTMX interactivity.

    Displays jobs from app.jobs table with task counts and status filtering.

    Fragments supported:
        - jobs-table: Returns table rows for job listing
        - stats: Returns stats banner content
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Job Monitor dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Job Monitor",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """
        Handle HTMX partial requests for jobs fragments.

        Fragments:
            jobs-table: Returns table rows for job listing
            stats: Returns stats banner content

        Args:
            request: Azure Functions HttpRequest
            fragment: Fragment name to render

        Returns:
            HTML fragment string
        """
        if fragment == 'jobs-table':
            return self._render_jobs_table_fragment(request)
        elif fragment == 'stats':
            return self._render_stats_fragment(request)
        else:
            raise ValueError(f"Unknown fragment: {fragment}")

    def _render_jobs_table_fragment(self, request: func.HttpRequest) -> str:
        """Render jobs table rows via HTMX."""
        status = request.params.get('status', '')
        limit = int(request.params.get('limit', '25'))

        try:
            jobs = self._query_jobs_with_task_counts(status, limit)

            if not jobs:
                return self._render_empty_jobs()

            # Build table rows
            rows = []
            stats = {'total': 0, 'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0}

            for job in jobs:
                job_id = job.get('job_id', job.get('id', ''))
                job_id_short = job_id[:8] if job_id else '--'
                job_type = job.get('job_type', '--')
                job_status = job.get('status', 'unknown')
                stage = job.get('stage', 0)
                total_stages = job.get('total_stages', '?')
                created_at = job.get('created_at', '')
                tc = job.get('task_counts', {})

                # Update stats
                stats['total'] += 1
                if job_status in stats:
                    stats[job_status] += 1

                # Format created_at in Eastern Time
                if created_at:
                    try:
                        from datetime import datetime
                        from zoneinfo import ZoneInfo
                        eastern = ZoneInfo('America/New_York')

                        if hasattr(created_at, 'astimezone'):
                            # Already a datetime object
                            dt_eastern = created_at.astimezone(eastern)
                        else:
                            # Parse from string (assume UTC if no timezone)
                            dt = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                            dt_eastern = dt.astimezone(eastern)

                        created_str = dt_eastern.strftime('%m/%d/%Y %I:%M %p') + ' ET'
                    except Exception:
                        created_str = str(created_at)[:16]
                else:
                    created_str = '--'

                # Task counts HTML
                task_counts_html = self._render_task_counts(tc)

                row = f'''
                <tr>
                    <td><span class="job-id-short" title="{job_id}">{job_id_short}</span></td>
                    <td>{job_type}</td>
                    <td>{self.render_status_badge(job_status)}</td>
                    <td><span class="stage-badge">Stage {stage}/{total_stages}</span></td>
                    <td>{task_counts_html}</td>
                    <td>{created_str}</td>
                    <td>
                        <a href="/api/interface/tasks?job_id={job_id}" class="btn btn-sm btn-primary">View Tasks</a>
                    </td>
                </tr>'''
                rows.append(row)

            # OOB swap RE-ENABLED (26 DEC 2025) - Fixed by wrapping in <template>
            # Issue: Browser HTML parser can't handle <div> inside <tbody> context
            # Fix: Wrap OOB element in <template> tag for proper HTMX extraction
            # See: https://github.com/bigskysoftware/htmx/issues/1900
            stats_html = self._render_stats_oob(stats)
            return '\n'.join(rows) + stats_html

        except Exception as e:
            logger.error(f"Error loading jobs: {e}", exc_info=True)
            return f'''
            <tr>
                <td colspan="7">
                    <div class="error-state" style="margin: 0; box-shadow: none;">
                        <p>Error loading jobs: {str(e)}</p>
                    </div>
                </td>
            </tr>
            '''

    def _render_task_counts(self, tc: Dict[str, int]) -> str:
        """Render task count badges."""
        parts = []
        if tc.get('queued', 0) > 0:
            parts.append(f'<span class="task-count task-count-queued">Q:{tc["queued"]}</span>')
        if tc.get('processing', 0) > 0:
            parts.append(f'<span class="task-count task-count-processing">P:{tc["processing"]}</span>')
        if tc.get('completed', 0) > 0:
            parts.append(f'<span class="task-count task-count-completed">C:{tc["completed"]}</span>')
        if tc.get('failed', 0) > 0:
            parts.append(f'<span class="task-count task-count-failed">F:{tc["failed"]}</span>')

        if not parts:
            return '<span class="task-count" style="color: var(--ds-gray);">--</span>'

        return f'<div class="task-summary">{" ".join(parts)}</div>'

    def _render_stats_oob(self, stats: Dict[str, int]) -> str:
        """
        Render stats as OOB swap wrapped in template tag.

        HTMX OOB swaps have parsing issues when mixed with table elements (<tr>, <td>).
        The browser's HTML parser can't handle a <div> inside a <tbody> context.
        Wrapping in <template> allows HTMX to extract the OOB element correctly.

        See: https://github.com/bigskysoftware/htmx/issues/1900
        See: https://htmx.org/attributes/hx-swap-oob/
        """
        return f'''
        <template>
            <div id="stats-content" class="stats-banner" hx-swap-oob="true">
                <div class="stat-card">
                    <div class="stat-label">Total Jobs</div>
                    <div class="stat-value">{stats['total']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Queued</div>
                    <div class="stat-value stat-queued">{stats['queued']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Processing</div>
                    <div class="stat-value stat-processing">{stats['processing']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Completed</div>
                    <div class="stat-value stat-completed">{stats['completed']}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value stat-failed">{stats['failed']}</div>
                </div>
            </div>
        </template>
        '''

    def _render_stats_fragment(self, request: func.HttpRequest) -> str:
        """Render stats banner content."""
        # This is called separately if needed
        return self._render_stats_oob({'total': 0, 'queued': 0, 'processing': 0, 'completed': 0, 'failed': 0})

    def _render_empty_jobs(self) -> str:
        """Render empty state for jobs table."""
        return '''
        <tr>
            <td colspan="7">
                <div class="empty-state" style="margin: 0; box-shadow: none;">
                    <div class="icon" style="font-size: 48px;">📋</div>
                    <h3>No Jobs Found</h3>
                    <p>No jobs match the current filter criteria</p>
                </div>
            </td>
        </tr>
        '''

    def _query_jobs_with_task_counts(self, status: str, limit: int) -> List[Dict[str, Any]]:
        """
        Query jobs with task counts from database.

        Mirrors the dbadmin endpoint query but returns dicts for rendering.
        """
        from config import get_config
        from infrastructure.postgresql import PostgreSQLRepository

        config = get_config()
        repo = PostgreSQLRepository()
        app_schema = config.database.app_schema

        # Build query with task_counts subquery
        query_parts = [
            f"""SELECT j.job_id, j.job_type, j.status::text as status, j.stage, j.total_stages,
                   j.created_at, j.updated_at,
                   COALESCE(tc.queued, 0) as task_queued,
                   COALESCE(tc.processing, 0) as task_processing,
                   COALESCE(tc.completed, 0) as task_completed,
                   COALESCE(tc.failed, 0) as task_failed
            FROM {app_schema}.jobs j
            LEFT JOIN (
                SELECT parent_job_id,
                       COUNT(*) FILTER (WHERE status::text = 'queued') as queued,
                       COUNT(*) FILTER (WHERE status::text = 'processing') as processing,
                       COUNT(*) FILTER (WHERE status::text = 'completed') as completed,
                       COUNT(*) FILTER (WHERE status::text = 'failed') as failed
                FROM {app_schema}.tasks
                GROUP BY parent_job_id
            ) tc ON j.job_id = tc.parent_job_id
            WHERE 1=1"""
        ]

        params = []

        # Add 7-day time filter by default for performance
        query_parts.append("AND j.created_at >= NOW() - INTERVAL '168 hours'")

        if status:
            query_parts.append("AND j.status::text = %s")
            params.append(status)

        query_parts.extend([
            "ORDER BY j.created_at DESC",
            "LIMIT %s"
        ])
        params.append(limit)

        query = " ".join(query_parts)

        # Execute query using repository connection
        with repo._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params if params else None)
                rows = cursor.fetchall()

                jobs = []
                for row in rows:
                    # Handle both dict-like and tuple rows
                    if hasattr(row, 'keys'):
                        job = dict(row)
                    else:
                        # Tuple row - map by position
                        job = {
                            'job_id': row[0],
                            'job_type': row[1],
                            'status': row[2],
                            'stage': row[3],
                            'total_stages': row[4],
                            'created_at': row[5],
                            'updated_at': row[6],
                            'task_queued': row[7],
                            'task_processing': row[8],
                            'task_completed': row[9],
                            'task_failed': row[10]
                        }

                    # Restructure task counts
                    job['task_counts'] = {
                        'queued': job.pop('task_queued', 0),
                        'processing': job.pop('task_processing', 0),
                        'completed': job.pop('task_completed', 0),
                        'failed': job.pop('task_failed', 0)
                    }
                    jobs.append(job)

                return jobs

    def _generate_html_content(self) -> str:
        """Generate HTML content for Job Monitor dashboard with HTMX."""
        return """
        <div class="container">
            <header class="dashboard-header">
                <h1>⚙️ Job Monitor</h1>
                <p class="subtitle">Monitor jobs and tasks from app.jobs table</p>
            </header>

            <!-- Filter Bar with HTMX -->
            <div class="filter-bar">
                <div class="filter-group">
                    <label for="statusFilter">Status:</label>
                    <select id="statusFilter" name="status" class="filter-select"
                            hx-get="/api/interface/jobs?fragment=jobs-table"
                            hx-target="#jobsTableBody"
                            hx-trigger="change"
                            hx-include="#limitFilter"
                            hx-indicator="#loading-spinner">
                        <option value="">All</option>
                        <option value="queued">Queued</option>
                        <option value="processing">Processing</option>
                        <option value="completed">Completed</option>
                        <option value="failed">Failed</option>
                    </select>
                </div>

                <div class="filter-group">
                    <label for="limitFilter">Limit:</label>
                    <select id="limitFilter" name="limit" class="filter-select"
                            hx-get="/api/interface/jobs?fragment=jobs-table"
                            hx-target="#jobsTableBody"
                            hx-trigger="change"
                            hx-include="#statusFilter"
                            hx-indicator="#loading-spinner">
                        <option value="10">10</option>
                        <option value="25" selected>25</option>
                        <option value="50">50</option>
                        <option value="100">100</option>
                    </select>
                </div>

                <div class="filter-actions">
                    <button class="btn btn-primary"
                            hx-get="/api/interface/jobs?fragment=jobs-table"
                            hx-target="#jobsTableBody"
                            hx-include="#statusFilter, #limitFilter"
                            hx-indicator="#loading-spinner">
                        🔄 Refresh
                    </button>
                    <button class="btn btn-secondary" onclick="clearFilters()">Clear Filters</button>
                </div>
            </div>

            <!-- Stats Banner -->
            <div class="stats-banner" id="stats-content">
                <div class="stat-card">
                    <div class="stat-label">Total Jobs</div>
                    <div class="stat-value">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Queued</div>
                    <div class="stat-value stat-queued">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Processing</div>
                    <div class="stat-value stat-processing">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Completed</div>
                    <div class="stat-value stat-completed">--</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Failed</div>
                    <div class="stat-value stat-failed">--</div>
                </div>
            </div>

            <!-- Loading Spinner -->
            <div id="loading-spinner" class="htmx-indicator spinner-container">
                <div class="spinner"></div>
                <div class="spinner-text">Loading jobs...</div>
            </div>

            <!-- Jobs Table -->
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
                <tbody id="jobsTableBody"
                       hx-get="/api/interface/jobs?fragment=jobs-table"
                       hx-trigger="load"
                       hx-include="#statusFilter, #limitFilter"
                       hx-indicator="#loading-spinner">
                    <!-- Loaded via HTMX on page load -->
                </tbody>
            </table>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Job Monitor.

        Note: Most styles now in COMMON_CSS (S12.1.1).
        Only job-specific styles remain here.
        """
        return """
        /* Fix: Ensure spinner-container respects htmx-indicator */
        .spinner-container.htmx-indicator {
            display: none !important;
        }
        .spinner-container.htmx-indicator.htmx-request {
            display: flex !important;
        }

        /* Jobs-specific: Stats banner as grid */
        .stats-banner {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            padding: 0;
            background: transparent;
            box-shadow: none;
        }

        /* Jobs-specific: Colored stat values */
        .stat-queued { color: var(--ds-status-queued-fg); }
        .stat-processing { color: var(--ds-blue-primary); }
        .stat-completed { color: var(--ds-status-completed-fg); }
        .stat-failed { color: var(--ds-status-failed-fg); }

        /* Jobs-specific: Stage badge */
        .stage-badge {
            font-size: 0.875rem;
            color: var(--ds-gray);
        }

        /* Jobs-specific: Task count summary */
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
            background: var(--ds-status-queued-bg);
            color: var(--ds-status-queued-fg);
        }

        .task-count-processing {
            background: var(--ds-status-processing-bg);
            color: var(--ds-status-processing-fg);
        }

        .task-count-completed {
            background: var(--ds-status-completed-bg);
            color: var(--ds-status-completed-fg);
        }

        .task-count-failed {
            background: var(--ds-status-failed-bg);
            color: var(--ds-status-failed-fg);
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate minimal JavaScript for Job Monitor.

        Most functionality now handled by HTMX (S12.3.1).
        Only helper functions remain.
        """
        return """
        // Clear filters and reload
        function clearFilters() {
            document.getElementById('statusFilter').value = '';
            document.getElementById('limitFilter').value = '25';

            // Trigger HTMX reload
            htmx.trigger('#jobsTableBody', 'load');
        }
        """
