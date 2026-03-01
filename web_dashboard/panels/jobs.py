# ============================================================================
# CLAUDE CONTEXT - JOBS_PANEL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Dashboard panel - Job monitoring and task inspection
# PURPOSE: Tab 2 of the dashboard: job lifecycle monitoring and drill-down
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: JobsPanel
# DEPENDENCIES: azure.functions, web_dashboard.base_panel, web_dashboard.registry
# ============================================================================
"""
Jobs panel for the dashboard.

Provides sub-tabs for:
    - monitor: Real-time job list with auto-refresh (10s)
    - tasks: Task drill-down for a specific job
    - pipeline: Stage visualization for a job
    - failures: Failed job analysis

Exports:
    JobsPanel: Registered panel class
"""

import html as html_module
import logging
import azure.functions as func

from web_dashboard.base_panel import BasePanel
from web_dashboard.registry import PanelRegistry

logger = logging.getLogger(__name__)


@PanelRegistry.register
class JobsPanel(BasePanel):
    """Job monitoring panel -- monitor, tasks, pipeline, failures."""

    tab_order = 2

    def tab_name(self) -> str:
        return "jobs"

    def tab_label(self) -> str:
        return "Jobs"

    def default_section(self) -> str:
        return "monitor"

    def sections(self) -> list:
        return [
            ("monitor", "Monitor"),
            ("tasks", "Tasks"),
            ("pipeline", "Pipeline"),
            ("failures", "Failures"),
        ]

    def render_section(self, request: func.HttpRequest, section: str) -> str:
        dispatch = {
            "monitor": self._render_monitor,
            "tasks": self._render_tasks,
            "pipeline": self._render_pipeline,
            "failures": self._render_failures,
        }
        handler = dispatch.get(section)
        if not handler:
            raise ValueError(f"Unknown jobs section: {section}")
        return handler(request)

    def render_fragment(self, request: func.HttpRequest, fragment_name: str) -> str:
        dispatch = {
            "jobs-table": self._fragment_jobs_table,
            "job-detail": self._fragment_job_detail,
        }
        handler = dispatch.get(fragment_name)
        if not handler:
            raise ValueError(f"Unknown jobs fragment: {fragment_name}")
        return handler(request)

    # -----------------------------------------------------------------------
    # MONITOR section (auto-refresh: 10s)
    # -----------------------------------------------------------------------

    def _render_monitor(self, request: func.HttpRequest) -> str:
        """Render the job monitor with auto-refresh wrapper."""
        status_filter = request.params.get("status", "")
        hours_filter = request.params.get("hours", "24")
        limit = int(request.params.get("limit", "25"))
        page = int(request.params.get("page", "0"))

        # Build filter bar
        status_select = self.select_filter(
            "status", "Status",
            [
                ("", "All"),
                ("pending", "Pending"),
                ("processing", "Processing"),
                ("completed", "Completed"),
                ("failed", "Failed"),
            ],
            selected=status_filter,
        )
        hours_select = self.select_filter(
            "hours", "Period",
            [
                ("24", "Last 24h"),
                ("72", "Last 3 days"),
                ("168", "Last 7 days"),
                ("720", "Last 30 days"),
            ],
            selected=hours_filter,
        )
        filters = self.filter_bar("jobs", "monitor", [status_select, hours_select])

        # Build the auto-refresh wrapper URL
        refresh_params = f"tab=jobs&fragment=jobs-table"
        if status_filter:
            refresh_params += f"&status={html_module.escape(status_filter)}"
        refresh_params += f"&hours={html_module.escape(hours_filter)}"
        refresh_params += f"&limit={limit}"

        # Fetch the table content
        table_content = self._build_jobs_table(request, status_filter, hours_filter, limit, page)

        # Wrap in auto-refresh div (10s, visibility-guarded)
        return f"""{filters}
<div id="jobs-refresh-wrapper"
     hx-get="/api/dashboard?{html_module.escape(refresh_params)}"
     hx-trigger="every 10s [document.visibilityState === 'visible']"
     hx-target="this"
     hx-swap="innerHTML">
{table_content}
</div>"""

    def _build_jobs_table(
        self,
        request: func.HttpRequest,
        status_filter: str,
        hours_filter: str,
        limit: int,
        page: int,
    ) -> str:
        """Build the jobs table HTML (used by both section and fragment)."""
        params = {"limit": str(limit), "hours": hours_filter}
        if status_filter:
            params["status"] = status_filter

        ok, data = self.call_api(request, "/api/dbadmin/jobs", params=params)

        if not ok:
            return self.error_block(
                f"Failed to load jobs: {data}",
                retry_url="/api/dashboard?tab=jobs&section=monitor",
            )

        jobs_list = []
        if isinstance(data, dict):
            jobs_list = data.get("jobs", data.get("items", []))
        elif isinstance(data, list):
            jobs_list = data

        if not jobs_list:
            return self.empty_block("No jobs found. The system is idle.")

        # Stats strip
        status_counts = {}
        for job in jobs_list:
            s = job.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        stats = self.stat_strip(status_counts)

        # Build table
        headers = ["Job ID", "Type", "Status", "Stage", "Progress", "Created", "Age"]
        rows = []
        row_attrs = []
        for job in jobs_list:
            job_id = job.get("job_id", job.get("id", ""))
            job_type = job.get("job_type", job.get("type", "--"))
            status = job.get("status", "--")
            current_stage = job.get("current_stage", job.get("stage", "--"))
            total_stages = job.get("total_stages", "")
            progress = f"{current_stage}/{total_stages}" if total_stages else str(current_stage)
            created = job.get("created_at", job.get("submitted_at", ""))

            rows.append([
                self.truncate_id(job_id),
                html_module.escape(str(job_type)),
                self.status_badge(status),
                html_module.escape(str(current_stage)),
                html_module.escape(str(progress)),
                self.format_date(created),
                self.format_age(created),
            ])
            row_attrs.append({
                "id": f"job-{html_module.escape(str(job_id)[:8])}",
                "class": "clickable",
                "hx-get": f"/api/dashboard?tab=jobs&section=tasks&job_id={html_module.escape(str(job_id))}",
                "hx-target": "#panel-content",
                "hx-push-url": "true",
                "hx-swap": "innerHTML",
            })

        table = self.data_table(headers, rows, table_id="jobs-table", row_attrs=row_attrs)

        # Pagination
        total = len(jobs_list)
        if isinstance(data, dict):
            total = data.get("total", total)
        pagination = ""
        if total > limit:
            pagination = self.pagination_controls("jobs", "monitor", page, limit, total)

        return stats + table + pagination

    def _fragment_jobs_table(self, request: func.HttpRequest) -> str:
        """Fragment: auto-refresh table content only (no filter bar, no wrapper)."""
        status_filter = request.params.get("status", "")
        hours_filter = request.params.get("hours", "24")
        limit = int(request.params.get("limit", "25"))
        page = int(request.params.get("page", "0"))
        return self._build_jobs_table(request, status_filter, hours_filter, limit, page)

    def _fragment_job_detail(self, request: func.HttpRequest) -> str:
        """Fragment: job detail card."""
        job_id = request.params.get("job_id", "")
        if not job_id:
            return self.empty_block("No job ID specified.")

        ok, data = self.call_api(request, f"/api/dbadmin/jobs/{job_id}")
        if not ok:
            return self.error_block(
                f"Failed to load job detail: {data}",
                retry_url=f"/api/dashboard?tab=jobs&fragment=job-detail&job_id={html_module.escape(job_id)}",
            )

        if not data:
            return self.empty_block(f"Job {html_module.escape(job_id[:8])} not found.")

        job = data if isinstance(data, dict) else {}
        safe_id = html_module.escape(str(job.get("job_id", job_id)))
        return f"""<div class="detail-panel">
<h3>Job: {self.truncate_id(safe_id, 16)}</h3>
<div class="detail-grid">
    <div class="detail-item">
        <span class="detail-label">Job ID</span>
        <span class="detail-value mono">{safe_id}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Type</span>
        <span class="detail-value">{html_module.escape(str(job.get("job_type", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Status</span>
        <span class="detail-value">{self.status_badge(job.get("status", "--"))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Current Stage</span>
        <span class="detail-value">{html_module.escape(str(job.get("current_stage", "--")))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Created</span>
        <span class="detail-value">{self.format_date(job.get("created_at"))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Updated</span>
        <span class="detail-value">{self.format_date(job.get("updated_at"))}</span>
    </div>
    <div class="detail-item">
        <span class="detail-label">Error</span>
        <span class="detail-value" style="color:var(--ds-status-failed-text);">{html_module.escape(str(job.get("error_message", "--")))}</span>
    </div>
</div>
<div style="margin-top:12px; display:flex; gap:8px;">
    <a hx-get="/api/dashboard?tab=jobs&section=tasks&job_id={html_module.escape(str(job_id))}"
       hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML"
       class="btn btn-sm btn-primary">View Tasks</a>
    <a hx-get="/api/dashboard?tab=jobs&section=pipeline&job_id={html_module.escape(str(job_id))}"
       hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML"
       class="btn btn-sm btn-secondary">View Pipeline</a>
</div>
</div>"""

    # -----------------------------------------------------------------------
    # TASKS section
    # -----------------------------------------------------------------------

    def _render_tasks(self, request: func.HttpRequest) -> str:
        """Render task drill-down for a specific job."""
        job_id = request.params.get("job_id", "")

        if not job_id:
            return self.empty_block(
                "Select a job from the Monitor tab to view its tasks."
            )

        ok, data = self.call_api(request, f"/api/dbadmin/tasks/{job_id}")

        if not ok:
            return self.error_block(
                f"Failed to load tasks: {data}",
                retry_url=f"/api/dashboard?tab=jobs&section=tasks&job_id={html_module.escape(job_id)}",
            )

        tasks = []
        if isinstance(data, dict):
            tasks = data.get("tasks", data.get("items", []))
        elif isinstance(data, list):
            tasks = data

        # Job header
        safe_jid = html_module.escape(str(job_id))
        header = (
            f'<div style="margin-bottom:16px; display:flex; align-items:center; gap:12px;">'
            f'<h3 class="section-heading" style="margin:0; border:none; padding:0;">Tasks for Job: {self.truncate_id(job_id, 16)}</h3>'
            f'<a hx-get="/api/dashboard?tab=jobs&section=monitor" '
            f'hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML" '
            f'class="btn btn-sm btn-secondary">Back to Monitor</a>'
            f'</div>'
        )

        if not tasks:
            return header + self.empty_block(
                f"No tasks found for job {html_module.escape(job_id[:8])}."
            )

        headers = ["Task ID", "Type", "Stage", "Status", "Worker", "Started", "Duration"]
        rows = []
        for task in tasks:
            task_id = task.get("task_id", task.get("id", ""))
            task_type = task.get("task_type", task.get("type", "--"))
            stage = task.get("stage_number", task.get("stage", "--"))
            status = task.get("status", "--")
            worker = task.get("worker_id", task.get("worker", "--"))
            started = task.get("started_at", task.get("created_at", ""))
            completed = task.get("completed_at", "")

            # Calculate duration
            duration = "--"
            if started and completed:
                try:
                    from datetime import datetime
                    s = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                    e = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                    delta = e - s
                    secs = int(delta.total_seconds())
                    if secs < 60:
                        duration = f"{secs}s"
                    elif secs < 3600:
                        duration = f"{secs // 60}m {secs % 60}s"
                    else:
                        duration = f"{secs // 3600}h {(secs % 3600) // 60}m"
                except (ValueError, TypeError):
                    duration = "--"

            rows.append([
                self.truncate_id(task_id),
                html_module.escape(str(task_type)),
                html_module.escape(str(stage)),
                self.status_badge(status),
                html_module.escape(str(worker)[:20] if worker else "--"),
                self.format_date(started),
                html_module.escape(str(duration)),
            ])

        table = self.data_table(headers, rows, table_id="tasks-table")
        return header + table

    # -----------------------------------------------------------------------
    # PIPELINE section
    # -----------------------------------------------------------------------

    def _render_pipeline(self, request: func.HttpRequest) -> str:
        """Render stage visualization for a job."""
        job_id = request.params.get("job_id", "")

        if not job_id:
            return self.empty_block(
                "Select a job from the Monitor tab to view its pipeline."
            )

        ok, data = self.call_api(request, f"/api/jobs/status/{job_id}")

        if not ok:
            return self.error_block(
                f"Failed to load pipeline: {data}",
                retry_url=f"/api/dashboard?tab=jobs&section=pipeline&job_id={html_module.escape(job_id)}",
            )

        if not data:
            return self.empty_block(
                f"No pipeline info for job {html_module.escape(job_id[:8])}."
            )

        job_status = data if isinstance(data, dict) else {}
        safe_jid = html_module.escape(str(job_id))
        job_type = html_module.escape(str(job_status.get("job_type", "--")))
        overall_status = job_status.get("status", "--")

        header = (
            f'<div style="margin-bottom:16px; display:flex; align-items:center; gap:12px;">'
            f'<h3 class="section-heading" style="margin:0; border:none; padding:0;">'
            f'Pipeline: {self.truncate_id(job_id, 16)} ({job_type})</h3>'
            f'{self.status_badge(overall_status)}'
            f'<a hx-get="/api/dashboard?tab=jobs&section=monitor" '
            f'hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML" '
            f'class="btn btn-sm btn-secondary">Back to Monitor</a>'
            f'</div>'
        )

        # Render stages
        stages = job_status.get("stages", [])
        if not stages:
            # Try alternate response shape
            current = job_status.get("current_stage", "")
            total = job_status.get("total_stages", "")
            summary = (
                f'<div class="detail-panel">'
                f'<div class="detail-grid">'
                f'<div class="detail-item">'
                f'<span class="detail-label">Current Stage</span>'
                f'<span class="detail-value">{html_module.escape(str(current))}</span>'
                f'</div>'
                f'<div class="detail-item">'
                f'<span class="detail-label">Total Stages</span>'
                f'<span class="detail-value">{html_module.escape(str(total))}</span>'
                f'</div>'
                f'<div class="detail-item">'
                f'<span class="detail-label">Status</span>'
                f'<span class="detail-value">{self.status_badge(overall_status)}</span>'
                f'</div>'
                f'</div>'
                f'</div>'
            )
            return header + summary

        stage_cards = []
        for stage in stages:
            s_num = html_module.escape(str(stage.get("stage_number", stage.get("number", "?"))))
            s_name = html_module.escape(str(stage.get("stage_name", stage.get("name", "Stage"))))
            s_status = stage.get("status", "--")
            s_tasks_total = stage.get("total_tasks", 0)
            s_tasks_done = stage.get("completed_tasks", 0)
            s_tasks_failed = stage.get("failed_tasks", 0)

            progress_pct = 0
            if s_tasks_total > 0:
                progress_pct = int((s_tasks_done / s_tasks_total) * 100)

            stage_cards.append(
                f'<div class="health-card">'
                f'<h4>Stage {s_num}: {s_name} {self.status_badge(s_status)}</h4>'
                f'<div style="margin:8px 0;">'
                f'<div style="background:var(--ds-gray-light); height:8px; border-radius:4px; overflow:hidden;">'
                f'<div style="background:var(--ds-blue-primary); width:{progress_pct}%; height:100%; transition:width 0.3s;"></div>'
                f'</div>'
                f'<span style="font-size:11px; color:var(--ds-gray);">'
                f'{s_tasks_done}/{s_tasks_total} tasks complete'
                f'{f", {s_tasks_failed} failed" if s_tasks_failed else ""}'
                f'</span>'
                f'</div>'
                f'</div>'
            )

        return header + f'<div class="health-grid">{"".join(stage_cards)}</div>'

    # -----------------------------------------------------------------------
    # FAILURES section
    # -----------------------------------------------------------------------

    def _render_failures(self, request: func.HttpRequest) -> str:
        """Render failed jobs analysis."""
        hours = request.params.get("hours", "24")
        hours_select = self.select_filter(
            "hours", "Period",
            [("24", "Last 24h"), ("72", "Last 3 days"), ("168", "Last 7 days")],
            selected=hours,
        )
        filters = self.filter_bar("jobs", "failures", [hours_select])

        ok, data = self.call_api(
            request, "/api/platform/failures", params={"hours": hours}
        )

        if not ok:
            return filters + self.error_block(
                f"Failed to load failure data: {data}",
                retry_url="/api/dashboard?tab=jobs&section=failures",
            )

        failures = []
        if isinstance(data, dict):
            failures = data.get("failures", data.get("items", []))
        elif isinstance(data, list):
            failures = data

        if not failures:
            return filters + self.empty_block(
                "No failed jobs in the selected time period."
            )

        # Group failures by type for analysis
        type_counts = {}
        for f in failures:
            ft = f.get("job_type", f.get("type", "unknown"))
            type_counts[ft] = type_counts.get(ft, 0) + 1

        stats = self.stat_strip(type_counts)

        headers = ["Job ID", "Type", "Stage", "Error", "Failed At", "Actions"]
        rows = []
        for f in failures:
            fid = f.get("job_id", f.get("id", ""))
            ftype = f.get("job_type", f.get("type", "--"))
            stage = f.get("failed_stage", f.get("current_stage", "--"))
            error = f.get("error_message", f.get("error", "--"))
            failed_at = f.get("failed_at", f.get("updated_at", ""))

            safe_fid = html_module.escape(str(fid))
            actions = (
                f'<a hx-get="/api/dashboard?tab=jobs&section=tasks&job_id={safe_fid}" '
                f'hx-target="#panel-content" hx-push-url="true" hx-swap="innerHTML" '
                f'class="btn btn-sm btn-secondary">Tasks</a>'
            )

            rows.append([
                self.truncate_id(fid),
                html_module.escape(str(ftype)),
                html_module.escape(str(stage)),
                html_module.escape(str(error)[:100]),
                self.format_date(failed_at),
                actions,
            ])

        table = self.data_table(headers, rows, table_id="job-failures-table")
        return filters + stats + table
