"""
Task monitoring interface module.

Web dashboard for viewing tasks of a specific job with workflow visualization.

Features (15 DEC 2025):
    - Visual workflow diagram showing predefined stages
    - Task counts per stage with status colors
    - Auto-refresh capability
    - Expandable task detail sections

Exports:
    TasksInterface: Task monitoring dashboard with workflow visualization
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('tasks')
class TasksInterface(BaseInterface):
    """
    Task Monitoring Dashboard interface with workflow visualization.

    Displays predefined workflow stages with task counts and status indicators.
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
                        <h1>Workflow Monitor</h1>
                        <p class="subtitle">Job: <span id="job-id-display" style="font-family: 'Courier New', monospace; color: #0071BC; font-size: 14px;">{job_id[:16] if job_id else 'Loading...'}...</span></p>
                    </div>
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <button id="refreshBtn" class="refresh-button">Refresh</button>
                        <a href="/api/interface/pipeline" class="back-button-link">
                            Back to Pipeline
                        </a>
                    </div>
                </div>
            </header>

            <!-- Job Summary Card -->
            <div id="job-summary-card" class="job-summary-card">
                <div class="spinner"></div>
            </div>

            <!-- Workflow Diagram -->
            <div id="workflow-diagram" class="workflow-diagram">
                <div class="spinner"></div>
            </div>

            <!-- Loading State -->
            <div id="loading-spinner" class="spinner hidden"></div>

            <!-- Tasks Detail Container -->
            <div id="tasks-container" class="tasks-container hidden">
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
                <div class="icon">⚠</div>
                <h3>Error Loading Data</h3>
                <p id="error-message"></p>
                <button onclick="loadData()" class="refresh-button" style="margin-top: 20px;">
                    Retry
                </button>
            </div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Task Monitor with workflow diagram."""
        return """
        .dashboard-header {
            background: white;
            padding: 25px 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            border-left: 4px solid #0071BC;
        }

        .dashboard-header h1 {
            color: #053657;
            font-size: 24px;
            margin-bottom: 8px;
            font-weight: 700;
        }

        .subtitle {
            color: #626F86;
            font-size: 14px;
            margin: 0;
        }

        .back-button-link {
            display: inline-flex;
            align-items: center;
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
            background: #005a96;
        }

        /* Job Summary Card */
        .job-summary-card {
            background: white;
            border: 1px solid #e9ecef;
            padding: 20px 25px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .job-summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 15px;
        }

        .summary-item {
            text-align: center;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 3px;
        }

        .summary-label {
            font-size: 11px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 6px;
        }

        .summary-value {
            font-size: 18px;
            color: #053657;
            font-weight: 700;
        }

        /* Workflow Diagram */
        .workflow-diagram {
            background: white;
            border: 1px solid #e9ecef;
            padding: 30px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .workflow-title {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 25px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
        }

        .workflow-stages {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0;
            flex-wrap: wrap;
        }

        .stage-box {
            background: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            min-width: 180px;
            text-align: center;
            position: relative;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .stage-box:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }

        .stage-box.pending {
            border-color: #d1d5db;
            background: #f9fafb;
        }

        .stage-box.active {
            border-color: #F59E0B;
            background: #FFFBEB;
            box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
        }

        .stage-box.completed {
            border-color: #10B981;
            background: #ECFDF5;
        }

        .stage-box.failed {
            border-color: #DC2626;
            background: #FEF2F2;
        }

        .stage-number {
            position: absolute;
            top: -12px;
            left: 50%;
            transform: translateX(-50%);
            background: #053657;
            color: white;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            font-size: 12px;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .stage-box.completed .stage-number {
            background: #10B981;
        }

        .stage-box.active .stage-number {
            background: #F59E0B;
        }

        .stage-box.failed .stage-number {
            background: #DC2626;
        }

        .stage-name {
            font-size: 14px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 6px;
            margin-top: 4px;
        }

        .stage-task-type {
            font-size: 11px;
            color: #626F86;
            font-family: 'Courier New', monospace;
            margin-bottom: 12px;
        }

        .stage-counts {
            display: flex;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .count-badge {
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 10px;
        }

        .count-queued {
            background: #e5e7eb;
            color: #6b7280;
        }

        .count-processing {
            background: #FEF3C7;
            color: #D97706;
        }

        .count-completed {
            background: #D1FAE5;
            color: #059669;
        }

        .count-failed {
            background: #FEE2E2;
            color: #DC2626;
        }

        .stage-arrow {
            display: flex;
            align-items: center;
            padding: 0 10px;
            color: #9ca3af;
            font-size: 24px;
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
        .tasks-container {
            background: white;
            padding: 25px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .tasks-header {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid #e9ecef;
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
            font-size: 14px;
            font-weight: 700;
            color: #053657;
            margin: 0;
        }

        .stage-stats {
            display: flex;
            gap: 12px;
            align-items: center;
            font-size: 12px;
            font-weight: 600;
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
            font-size: 13px;
            font-weight: 600;
            color: #053657;
        }

        .task-id {
            font-size: 10px;
            color: #626F86;
            font-family: 'Courier New', monospace;
            margin-top: 4px;
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
            font-size: 12px;
        }

        .error-details p {
            color: #991B1B;
            font-size: 12px;
            margin: 5px 0 0 0;
            line-height: 1.4;
            word-break: break-word;
        }

        .view-result-button {
            margin-top: 10px;
            padding: 6px 12px;
            background: white;
            border: 1px solid #e9ecef;
            color: #0071BC;
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            font-weight: 600;
            transition: all 0.2s;
        }

        .view-result-button:hover {
            background: #f8f9fa;
            border-color: #0071BC;
        }

        .result-json {
            margin-top: 10px;
            background: #1e293b;
            color: #e2e8f0;
            padding: 15px;
            border-radius: 3px;
            overflow-x: auto;
            font-size: 11px;
            font-family: 'Courier New', monospace;
            max-height: 300px;
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
            font-size: 48px;
            margin-bottom: 15px;
            opacity: 0.3;
        }

        .empty-state h3, .error-state h3 {
            color: #053657;
            margin-bottom: 10px;
        }

        /* Error banner */
        .error-banner {
            background: #FEE2E2;
            border: 1px solid #DC2626;
            border-left: 4px solid #DC2626;
            padding: 15px;
            border-radius: 3px;
            margin-bottom: 20px;
        }

        .error-banner strong {
            color: #DC2626;
            font-size: 14px;
        }

        .error-banner p {
            color: #991B1B;
            font-size: 13px;
            margin: 5px 0 0 0;
        }

        /* Responsive */
        @media (max-width: 768px) {
            .workflow-stages {
                flex-direction: column;
                gap: 20px;
            }
            .stage-arrow {
                transform: rotate(90deg);
                padding: 5px 0;
            }
        }
        """

    def _generate_custom_js(self, job_id: str) -> str:
        """Generate custom JavaScript for Task Monitor with workflow visualization."""
        return f"""
        const JOB_ID = '{job_id}';

        // Predefined workflow definitions
        const WORKFLOW_DEFINITIONS = {{
            'process_vector': {{
                name: 'Vector ETL Pipeline',
                stages: [
                    {{ number: 1, name: 'Prepare', taskType: 'process_vector_prepare', description: 'Load, validate, chunk data' }},
                    {{ number: 2, name: 'Upload', taskType: 'process_vector_upload', description: 'Fan-out chunk uploads' }},
                    {{ number: 3, name: 'Catalog', taskType: 'create_vector_stac', description: 'Create STAC record' }}
                ]
            }},
            'process_raster': {{
                name: 'Raster ETL Pipeline',
                stages: [
                    {{ number: 1, name: 'Validate', taskType: 'validate_raster', description: 'Validate raster file' }},
                    {{ number: 2, name: 'Create COG', taskType: 'create_cog', description: 'Convert to Cloud Optimized GeoTIFF' }},
                    {{ number: 3, name: 'Catalog', taskType: 'extract_stac_metadata', description: 'Extract STAC metadata' }}
                ]
            }},
            'process_raster_v2': {{
                name: 'Raster ETL Pipeline v2',
                stages: [
                    {{ number: 1, name: 'Validate', taskType: 'validate_raster', description: 'Validate raster file' }},
                    {{ number: 2, name: 'Create COG', taskType: 'create_cog', description: 'Convert to Cloud Optimized GeoTIFF' }},
                    {{ number: 3, name: 'Catalog', taskType: 'extract_stac_metadata', description: 'Extract STAC metadata' }}
                ]
            }},
            'hello_world': {{
                name: 'Hello World Test',
                stages: [
                    {{ number: 1, name: 'Greeting', taskType: 'hello_world_greeting', description: 'Generate greetings' }},
                    {{ number: 2, name: 'Reply', taskType: 'hello_world_reply', description: 'Generate replies' }}
                ]
            }}
        }};

        // Load data on page load
        document.addEventListener('DOMContentLoaded', () => {{
            loadData();
            document.getElementById('refreshBtn').addEventListener('click', loadData);
        }});

        // Load job + tasks data
        async function loadData() {{
            if (!JOB_ID) {{
                showError('No job ID provided');
                return;
            }}

            const jobSummaryCard = document.getElementById('job-summary-card');
            const workflowDiagram = document.getElementById('workflow-diagram');
            const tasksContainer = document.getElementById('tasks-container');
            const emptyState = document.getElementById('empty-state');
            const errorState = document.getElementById('error-state');
            const spinner = document.getElementById('loading-spinner');

            // Show loading
            jobSummaryCard.innerHTML = '<div class="spinner"></div>';
            workflowDiagram.innerHTML = '<div class="spinner"></div>';
            tasksContainer.innerHTML = '';
            tasksContainer.classList.add('hidden');
            emptyState.classList.add('hidden');
            errorState.classList.add('hidden');

            try {{
                // Fetch job + tasks in parallel
                const [jobResponse, tasksData] = await Promise.all([
                    fetchJSON(`${{API_BASE_URL}}/api/dbadmin/jobs/${{JOB_ID}}`),
                    fetchJSON(`${{API_BASE_URL}}/api/dbadmin/tasks/${{JOB_ID}}`)
                ]);

                const tasks = tasksData.tasks || [];
                const job = jobResponse.job || jobResponse;

                // Render job summary
                renderJobSummary(job);

                // Render workflow diagram
                renderWorkflowDiagram(job, tasks);

                // Render task details
                if (tasks.length > 0) {{
                    renderTaskDetails(job, tasks);
                    tasksContainer.classList.remove('hidden');
                }}

            }} catch (error) {{
                console.error('Error loading data:', error);
                showError(error.message || 'Failed to load data');
            }}
        }}

        // Render job summary card
        function renderJobSummary(job) {{
            const taskCounts = job.result_data?.tasks_by_status || {{}};
            const queued = taskCounts.queued || 0;
            const processing = taskCounts.processing || 0;
            const completed = taskCounts.completed || 0;
            const failed = taskCounts.failed || 0;
            const total = queued + processing + completed + failed;

            let statusClass = 'status-' + (job.status || 'queued');
            let html = '';

            // Error banner if failed
            if (job.status === 'failed') {{
                html += `
                    <div class="error-banner">
                        <strong>Job Failed</strong>
                        <p>${{job.error_details || 'No error details available'}}</p>
                    </div>
                `;
            }}

            html += `
                <div class="job-summary-grid">
                    <div class="summary-item">
                        <span class="summary-label">Job Type</span>
                        <span class="summary-value" style="font-size: 14px;">${{job.job_type}}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Status</span>
                        <span class="status-badge ${{statusClass}}">${{job.status}}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Stage</span>
                        <span class="summary-value">${{job.stage || 0}} / ${{job.total_stages || '?'}}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Tasks</span>
                        <span class="summary-value">${{total}}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Completed</span>
                        <span class="summary-value" style="color: #10B981;">${{completed}}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Failed</span>
                        <span class="summary-value" style="color: #DC2626;">${{failed}}</span>
                    </div>
                </div>
            `;

            document.getElementById('job-summary-card').innerHTML = html;
        }}

        // Render workflow diagram
        function renderWorkflowDiagram(job, tasks) {{
            const workflowDef = WORKFLOW_DEFINITIONS[job.job_type];

            if (!workflowDef) {{
                // Unknown workflow - show generic based on actual tasks
                renderGenericWorkflow(job, tasks);
                return;
            }}

            // Group tasks by stage
            const tasksByStage = {{}};
            tasks.forEach(task => {{
                const stage = task.stage || 0;
                if (!tasksByStage[stage]) {{
                    tasksByStage[stage] = {{ queued: 0, processing: 0, completed: 0, failed: 0 }};
                }}
                tasksByStage[stage][task.status] = (tasksByStage[stage][task.status] || 0) + 1;
            }});

            let html = `
                <div class="workflow-title">${{workflowDef.name}}</div>
                <div class="workflow-stages">
            `;

            workflowDef.stages.forEach((stage, index) => {{
                const stageCounts = tasksByStage[stage.number] || {{ queued: 0, processing: 0, completed: 0, failed: 0 }};
                const totalTasks = stageCounts.queued + stageCounts.processing + stageCounts.completed + stageCounts.failed;

                // Determine stage status
                let stageStatus = 'pending';
                if (stageCounts.failed > 0) {{
                    stageStatus = 'failed';
                }} else if (stageCounts.processing > 0) {{
                    stageStatus = 'active';
                }} else if (stageCounts.completed > 0 && stageCounts.queued === 0 && stageCounts.processing === 0) {{
                    stageStatus = 'completed';
                }} else if (stageCounts.queued > 0) {{
                    stageStatus = 'active';
                }}

                // Add arrow before stage (except first)
                if (index > 0) {{
                    html += `<div class="stage-arrow">&#8594;</div>`;
                }}

                html += `
                    <div class="stage-box ${{stageStatus}}" onclick="scrollToStage(${{stage.number}})">
                        <div class="stage-number">${{stage.number}}</div>
                        <div class="stage-name">${{stage.name}}</div>
                        <div class="stage-task-type">${{stage.taskType}}</div>
                        <div class="stage-counts">
                `;

                if (totalTasks === 0) {{
                    html += `<span class="count-badge count-queued">No tasks</span>`;
                }} else {{
                    if (stageCounts.queued > 0) {{
                        html += `<span class="count-badge count-queued">Q:${{stageCounts.queued}}</span>`;
                    }}
                    if (stageCounts.processing > 0) {{
                        html += `<span class="count-badge count-processing">P:${{stageCounts.processing}}</span>`;
                    }}
                    if (stageCounts.completed > 0) {{
                        html += `<span class="count-badge count-completed">C:${{stageCounts.completed}}</span>`;
                    }}
                    if (stageCounts.failed > 0) {{
                        html += `<span class="count-badge count-failed">F:${{stageCounts.failed}}</span>`;
                    }}
                }}

                html += `
                        </div>
                    </div>
                `;
            }});

            html += `</div>`;
            document.getElementById('workflow-diagram').innerHTML = html;
        }}

        // Render generic workflow for unknown job types
        function renderGenericWorkflow(job, tasks) {{
            // Group tasks by stage
            const tasksByStage = {{}};
            tasks.forEach(task => {{
                const stage = task.stage || 0;
                if (!tasksByStage[stage]) {{
                    tasksByStage[stage] = {{ queued: 0, processing: 0, completed: 0, failed: 0, taskType: task.task_type }};
                }}
                tasksByStage[stage][task.status] = (tasksByStage[stage][task.status] || 0) + 1;
            }});

            const stages = Object.keys(tasksByStage).sort((a, b) => parseInt(a) - parseInt(b));

            let html = `
                <div class="workflow-title">${{job.job_type}} Workflow</div>
                <div class="workflow-stages">
            `;

            stages.forEach((stageNum, index) => {{
                const stageCounts = tasksByStage[stageNum];
                const totalTasks = stageCounts.queued + stageCounts.processing + stageCounts.completed + stageCounts.failed;

                let stageStatus = 'pending';
                if (stageCounts.failed > 0) stageStatus = 'failed';
                else if (stageCounts.processing > 0) stageStatus = 'active';
                else if (stageCounts.completed > 0 && stageCounts.queued === 0) stageStatus = 'completed';
                else if (stageCounts.queued > 0) stageStatus = 'active';

                if (index > 0) {{
                    html += `<div class="stage-arrow">&#8594;</div>`;
                }}

                html += `
                    <div class="stage-box ${{stageStatus}}" onclick="scrollToStage(${{stageNum}})">
                        <div class="stage-number">${{stageNum}}</div>
                        <div class="stage-name">Stage ${{stageNum}}</div>
                        <div class="stage-task-type">${{stageCounts.taskType || 'unknown'}}</div>
                        <div class="stage-counts">
                `;

                if (stageCounts.queued > 0) html += `<span class="count-badge count-queued">Q:${{stageCounts.queued}}</span>`;
                if (stageCounts.processing > 0) html += `<span class="count-badge count-processing">P:${{stageCounts.processing}}</span>`;
                if (stageCounts.completed > 0) html += `<span class="count-badge count-completed">C:${{stageCounts.completed}}</span>`;
                if (stageCounts.failed > 0) html += `<span class="count-badge count-failed">F:${{stageCounts.failed}}</span>`;

                html += `
                        </div>
                    </div>
                `;
            }});

            html += `</div>`;
            document.getElementById('workflow-diagram').innerHTML = html;
        }}

        // Render task details grouped by stage
        function renderTaskDetails(job, tasks) {{
            // Group tasks by stage
            const tasksByStage = {{}};
            tasks.forEach(task => {{
                const stage = task.stage || 0;
                if (!tasksByStage[stage]) {{
                    tasksByStage[stage] = [];
                }}
                tasksByStage[stage].push(task);
            }});

            let html = `<div class="tasks-header">Task Details (${{tasks.length}} total)</div>`;

            const stages = Object.keys(tasksByStage).sort((a, b) => parseInt(a) - parseInt(b));
            stages.forEach(stage => {{
                const stageTasks = tasksByStage[stage];
                const failed = stageTasks.filter(t => t.status === 'failed').length;
                const completed = stageTasks.filter(t => t.status === 'completed').length;
                const processing = stageTasks.filter(t => t.status === 'processing').length;
                const queued = stageTasks.filter(t => t.status === 'queued').length;

                html += `
                    <div class="stage-group" id="stage-group-${{stage}}">
                        <div class="stage-header" onclick="toggleStage('stage-${{stage}}')">
                            <h4>Stage ${{stage}} (${{stageTasks.length}} tasks)</h4>
                            <div class="stage-stats">
                                <span style="color: #626F86;">Q:${{queued}}</span>
                                <span style="color: #F59E0B;">P:${{processing}}</span>
                                <span style="color: #10B981;">C:${{completed}}</span>
                                <span style="color: #DC2626;">F:${{failed}}</span>
                                <span style="font-size: 10px;">&#9660;</span>
                            </div>
                        </div>
                        <div id="stage-${{stage}}" class="stage-tasks hidden">
                `;

                stageTasks.forEach(task => {{
                    const errorHTML = task.status === 'failed' && task.error_details ? `
                        <div class="error-details">
                            <strong>Error:</strong>
                            <p>${{task.error_details}}</p>
                        </div>
                    ` : '';

                    const resultButton = task.result_data ? `
                        <button class="view-result-button" onclick="event.stopPropagation(); toggleResult('task-${{task.task_id}}')">
                            View Result
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
                                    <div class="task-id">${{task.task_id.substring(0, 8)}}...${{task.task_id.slice(-8)}}</div>
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

        // Scroll to stage details
        function scrollToStage(stageNum) {{
            const stageGroup = document.getElementById('stage-group-' + stageNum);
            if (stageGroup) {{
                stageGroup.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                // Expand the stage
                const stageEl = document.getElementById('stage-' + stageNum);
                if (stageEl && stageEl.classList.contains('hidden')) {{
                    stageEl.classList.remove('hidden');
                }}
            }}
        }}

        // Show error state
        function showError(message) {{
            document.getElementById('job-summary-card').classList.add('hidden');
            document.getElementById('workflow-diagram').classList.add('hidden');
            document.getElementById('tasks-container').classList.add('hidden');
            document.getElementById('empty-state').classList.add('hidden');
            document.getElementById('error-state').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }}
        """
