"""
Task monitoring interface module.

Web dashboard for viewing tasks of a specific job with stage grouping and detail views.

Exports:
    TasksInterface: Task monitoring dashboard with job metadata and expandable task sections
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('tasks')
class TasksInterface(BaseInterface):
    """
    Task Monitoring Dashboard interface.

    Displays tasks for a specific job with stage grouping and detail views.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Task Monitoring dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object
                     Expected query param: job_id

        Returns:
            Complete HTML document string
        """
        # Get job_id from query params
        job_id = request.params.get('job_id', '')

        # HTML content
        content = self._generate_html_content(job_id)

        # Custom CSS for Task Monitor
        custom_css = self._generate_custom_css()

        # Custom JavaScript for Task Monitor
        custom_js = self._generate_custom_js(job_id)

        return self.wrap_html(
            title=f"Task Monitor - {job_id[:8] if job_id else 'No Job'}",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js
        )

    def _generate_html_content(self, job_id: str) -> str:
        """Generate HTML content structure."""
        return f"""
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1>📋 Task Monitor Dashboard</h1>
                        <p class="subtitle">View tasks for job: <span id="job-id-display" style="font-family: 'Courier New', monospace; color: #0071BC; font-size: 14px;">{job_id[:16] if job_id else 'Loading...'}...</span></p>
                    </div>
                    <a href="/api/interface/jobs" class="back-button-link">
                        ← Back to Jobs
                    </a>
                </div>
            </header>

            <!-- Job Info Card -->
            <div id="job-info-card" class="job-info-card">
                <div class="spinner"></div>
            </div>

            <!-- Loading State -->
            <div id="loading-spinner" class="spinner hidden"></div>

            <!-- Tasks Container -->
            <div id="tasks-container">
                <!-- Tasks will be inserted here -->
            </div>

            <!-- Empty State -->
            <div id="empty-state" class="empty-state hidden">
                <div class="icon">📭</div>
                <h3>No Tasks Found</h3>
                <p>This job has no tasks yet</p>
            </div>

            <!-- Error State -->
            <div id="error-state" class="error-state hidden">
                <div class="icon">⚠️</div>
                <h3>Error Loading Data</h3>
                <p id="error-message"></p>
                <button onclick="loadData()" class="refresh-button" style="margin-top: 20px;">
                    🔄 Retry
                </button>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Task Monitor."""
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

        .back-button-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            background: white;
            border: 1px solid #e9ecef;
            color: #0071BC;
            border-radius: 3px;
            font-size: 14px;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.2s;
        }

        .back-button-link:hover {
            background: #f8f9fa;
            border-color: #0071BC;
            color: #00A3DA;
        }

        /* Job Info Card */
        .job-info-card {
            background: white;
            border: 1px solid #e9ecef;
            border-left: 4px solid #0071BC;
            padding: 30px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }

        .job-info-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }

        .info-item {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            padding: 15px;
            border-radius: 3px;
        }

        .info-label {
            font-size: 11px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 8px;
        }

        .info-value {
            font-size: 16px;
            color: #053657;
            font-weight: 600;
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

        /* Tasks Container */
        #tasks-container {
            background: white;
            padding: 25px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .tasks-header {
            font-size: 20px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #e9ecef;
        }

        .stage-group {
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            padding: 15px;
            margin-bottom: 15px;
        }

        .stage-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            padding: 10px;
            background: white;
            border-radius: 3px;
            transition: background 0.2s;
        }

        .stage-header:hover {
            background: #f8f9fa;
        }

        .stage-header h4 {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin: 0;
        }

        .stage-stats {
            display: flex;
            gap: 15px;
            align-items: center;
            font-size: 14px;
            font-weight: 600;
        }

        .stage-stats span {
            color: #626F86;
        }

        .stage-tasks {
            margin-top: 15px;
            display: grid;
            gap: 10px;
        }

        .task-card {
            background: white;
            border: 1px solid #e9ecef;
            padding: 15px;
            border-radius: 3px;
            transition: box-shadow 0.2s;
        }

        .task-card:hover {
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        .task-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 10px;
        }

        .task-type {
            font-size: 14px;
            font-weight: 600;
            color: #053657;
        }

        .task-id {
            font-size: 11px;
            color: #626F86;
            font-family: 'Courier New', monospace;
            margin-top: 5px;
        }

        .error-details {
            margin-top: 10px;
            padding: 10px;
            background: #FEE2E2;
            border-left: 3px solid #DC2626;
            border-radius: 3px;
        }

        .error-details strong {
            color: #DC2626;
            font-size: 13px;
        }

        .error-details p {
            color: #991B1B;
            font-size: 13px;
            margin: 5px 0 0 0;
            line-height: 1.4;
        }

        .view-result-button {
            margin-top: 10px;
            padding: 8px 16px;
            background: white;
            border: 1px solid #e9ecef;
            color: #0071BC;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.2s;
        }

        .view-result-button:hover {
            background: #f8f9fa;
            border-color: #0071BC;
        }

        .result-json {
            margin-top: 10px;
            background: #053657;
            color: #f8f9fa;
            padding: 15px;
            border-radius: 3px;
            overflow-x: auto;
            font-size: 12px;
            font-family: 'Courier New', monospace;
            max-height: 400px;
            overflow-y: auto;
        }

        /* Empty/Error States */
        .empty-state, .error-state {
            text-align: center;
            padding: 60px 20px;
            color: #626F86;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .empty-state .icon, .error-state .icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .empty-state h3, .error-state h3 {
            color: #053657;
            margin-bottom: 10px;
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
        """

    def _generate_custom_js(self, job_id: str) -> str:
        """Generate custom JavaScript for Task Monitor."""
        return f"""
        const JOB_ID = '{job_id}';

        // Load data on page load
        document.addEventListener('DOMContentLoaded', loadData);

        // Load job + tasks data
        async function loadData() {{
            if (!JOB_ID) {{
                showError('No job ID provided');
                return;
            }}

            const jobInfoCard = document.getElementById('job-info-card');
            const tasksContainer = document.getElementById('tasks-container');
            const emptyState = document.getElementById('empty-state');
            const errorState = document.getElementById('error-state');
            const spinner = document.getElementById('loading-spinner');

            // Show loading
            jobInfoCard.innerHTML = '<div class="spinner"></div>';
            tasksContainer.innerHTML = '';
            emptyState.classList.add('hidden');
            errorState.classList.add('hidden');
            spinner.classList.remove('hidden');

            try {{
                // Fetch job + tasks in parallel
                const [job, tasksData] = await Promise.all([
                    fetchJSON(`${{API_BASE_URL}}/api/dbadmin/jobs/${{JOB_ID}}`),
                    fetchJSON(`${{API_BASE_URL}}/api/dbadmin/tasks/${{JOB_ID}}`)
                ]);

                spinner.classList.add('hidden');

                const tasks = tasksData.tasks || [];

                // Render job info (API returns {job: {...}, timestamp: ...})
                const jobData = job.job || job;
                renderJobInfo(jobData);

                // Render tasks
                if (tasks.length === 0) {{
                    tasksContainer.classList.add('hidden');
                    emptyState.classList.remove('hidden');
                }} else {{
                    renderTasks(jobData, tasks);
                }}

            }} catch (error) {{
                console.error('Error loading data:', error);
                spinner.classList.add('hidden');
                showError(error.message || 'Failed to load data');
            }}
        }}

        // Render job info card
        function renderJobInfo(job) {{
            const failedTasks = job.result_data?.tasks_by_status?.failed || 0;
            const completedTasks = job.result_data?.tasks_by_status?.completed || 0;
            const processingTasks = job.result_data?.tasks_by_status?.processing || 0;
            const queuedTasks = job.result_data?.tasks_by_status?.queued || 0;
            const totalTasks = failedTasks + completedTasks + processingTasks + queuedTasks;

            const stageProgress = job.total_stages > 0 ? `${{job.stage || 0}}/${{job.total_stages}}` : 'N/A';

            let html = `
                <h2 style="font-size: 18px; color: #053657; margin-bottom: 15px;">${{job.job_type}}</h2>
            `;

            // Error banner if failed
            if (job.status === 'failed') {{
                html += `
                    <div style="background: #FEE2E2; border: 1px solid #DC2626; border-left: 4px solid #DC2626; padding: 15px; border-radius: 3px; margin-bottom: 20px;">
                        <strong style="color: #DC2626; font-size: 14px;">Job Failed</strong>
                        <p style="color: #991B1B; font-size: 13px; margin: 5px 0 0 0;">${{job.error_details || 'No error details available'}}</p>
                    </div>
                `;
            }}

            html += `
                <div class="job-info-grid">
                    <div class="info-item">
                        <span class="info-label">Job ID</span>
                        <span class="info-value" style="font-family: 'Courier New', monospace; font-size: 12px;">${{job.job_id.substring(0, 8)}}...${{job.job_id.substring(job.job_id.length - 8)}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Status</span>
                        <span class="status-badge status-${{job.status}}">${{job.status}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Stage Progress</span>
                        <span class="info-value">${{stageProgress}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Total Tasks</span>
                        <span class="info-value">${{totalTasks}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Queued</span>
                        <span class="info-value" style="color: #626F86;">${{queuedTasks}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Processing</span>
                        <span class="info-value" style="color: #F59E0B;">${{processingTasks}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Completed</span>
                        <span class="info-value" style="color: #10B981;">${{completedTasks}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Failed</span>
                        <span class="info-value" style="color: #DC2626;">${{failedTasks}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Created</span>
                        <span class="info-value" style="font-size: 13px;">${{new Date(job.created_at).toLocaleString()}}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Updated</span>
                        <span class="info-value" style="font-size: 13px;">${{new Date(job.updated_at).toLocaleString()}}</span>
                    </div>
                </div>
            `;

            document.getElementById('job-info-card').innerHTML = html;
        }}

        // Render tasks grouped by stage
        function renderTasks(job, tasks) {{
            // Group tasks by stage
            const tasksByStage = {{}};
            tasks.forEach(task => {{
                const stage = task.stage || 0;
                if (!tasksByStage[stage]) {{
                    tasksByStage[stage] = [];
                }}
                tasksByStage[stage].push(task);
            }});

            let html = `<div class="tasks-header">Tasks (${{tasks.length}} total)</div>`;

            // Render each stage
            const stages = Object.keys(tasksByStage).sort((a, b) => parseInt(a) - parseInt(b));
            stages.forEach(stage => {{
                const stageTasks = tasksByStage[stage];
                const failed = stageTasks.filter(t => t.status === 'failed').length;
                const completed = stageTasks.filter(t => t.status === 'completed').length;
                const processing = stageTasks.filter(t => t.status === 'processing').length;
                const queued = stageTasks.filter(t => t.status === 'queued').length;

                html += `
                    <div class="stage-group">
                        <div class="stage-header" onclick="toggleStage('stage-${{stage}}')">
                            <h4>Stage ${{stage}} (${{stageTasks.length}} tasks)</h4>
                            <div class="stage-stats">
                                <span style="color: #626F86;">Q: ${{queued}}</span>
                                <span style="color: #F59E0B;">P: ${{processing}}</span>
                                <span style="color: #10B981;">C: ${{completed}}</span>
                                <span style="color: #DC2626;">F: ${{failed}}</span>
                                <span>▼</span>
                            </div>
                        </div>
                        <div id="stage-${{stage}}" class="stage-tasks hidden">
                `;

                // Render tasks in this stage
                stageTasks.forEach(task => {{
                    const errorHTML = task.status === 'failed' && task.error_details ? `
                        <div class="error-details">
                            <strong>Error:</strong>
                            <p>${{task.error_details}}</p>
                        </div>
                    ` : '';

                    const resultButton = task.result_data ? `
                        <button class="view-result-button" onclick="toggleResult('task-${{task.task_id}}')">
                            View Result Data
                        </button>
                        <div id="task-${{task.task_id}}" class="result-json hidden">
                            <pre>${{JSON.stringify(task.result_data, null, 2)}}</pre>
                        </div>
                    ` : '';

                    html += `
                        <div class="task-card">
                            <div class="task-header">
                                <div>
                                    <div class="task-type">${{task.task_type}}</div>
                                    <div class="task-id">${{task.task_id.substring(0, 8)}}...${{task.task_id.substring(task.task_id.length - 8)}}</div>
                                </div>
                                <span class="status-badge status-${{task.status}}">${{task.status}}</span>
                            </div>
                            ${{errorHTML}}
                            ${{resultButton}}
                        </div>
                    `;
                }});

                html += `
                        </div>
                    </div>
                `;
            }});

            document.getElementById('tasks-container').innerHTML = html;
        }}

        // Toggle stage visibility
        function toggleStage(stageId) {{
            const stageEl = document.getElementById(stageId);
            if (stageEl) {{
                stageEl.classList.toggle('hidden');
            }}
        }}

        // Toggle result JSON visibility
        function toggleResult(taskId) {{
            const resultEl = document.getElementById(taskId);
            if (resultEl) {{
                resultEl.classList.toggle('hidden');
            }}
        }}

        // Show error state
        function showError(message) {{
            document.getElementById('job-info-card').classList.add('hidden');
            document.getElementById('tasks-container').classList.add('hidden');
            document.getElementById('empty-state').classList.add('hidden');
            document.getElementById('error-state').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }}
        """