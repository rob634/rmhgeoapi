"""
Task monitoring interface module.

Web dashboard for viewing tasks of a specific job with workflow visualization.

Features (24 DEC 2025 - S12.3.2):
    - HTMX-powered auto-refresh
    - Visual workflow diagram showing predefined stages
    - Task counts per stage with status colors (P/Q/R/C/F)
    - Expandable task detail sections

Task Status Legend:
    - P (Pending): Task record created, message sent to queue
    - Q (Queued): Queue trigger received and opened message
    - R (Processing): Task handler actively running
    - C (Completed): Task finished successfully
    - F (Failed): Task encountered an error

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
    Uses HTMX for auto-refresh.
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
            custom_js=custom_js,
            include_htmx=True,
            include_status_bar=True
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
                        <div class="auto-refresh-toggle">
                            <label class="toggle-label">
                                <input type="checkbox" id="autoRefreshToggle" checked>
                                <span class="toggle-slider"></span>
                            </label>
                            <span class="toggle-text">Auto-refresh</span>
                            <select id="refreshInterval" class="interval-select">
                                <option value="10">10s</option>
                                <option value="30" selected>30s</option>
                                <option value="60">1m</option>
                                <option value="120">2m</option>
                            </select>
                            <span id="refreshCountdown" class="countdown-text"></span>
                        </div>
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

        /* Auto-refresh toggle */
        .auto-refresh-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: #f8f9fa;
            border-radius: 4px;
            border: 1px solid #e9ecef;
        }

        .toggle-label {
            position: relative;
            display: inline-block;
            width: 40px;
            height: 22px;
            cursor: pointer;
        }

        .toggle-label input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: #ccc;
            border-radius: 22px;
            transition: 0.3s;
        }

        .toggle-slider:before {
            content: "";
            position: absolute;
            height: 16px;
            width: 16px;
            left: 3px;
            bottom: 3px;
            background: white;
            border-radius: 50%;
            transition: 0.3s;
        }

        .toggle-label input:checked + .toggle-slider {
            background: #10B981;
        }

        .toggle-label input:checked + .toggle-slider:before {
            transform: translateX(18px);
        }

        .toggle-text {
            font-size: 12px;
            font-weight: 600;
            color: #053657;
        }

        .interval-select {
            padding: 4px 8px;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            font-size: 12px;
            background: white;
            cursor: pointer;
        }

        .countdown-text {
            font-size: 11px;
            color: #626F86;
            font-family: 'Courier New', monospace;
            min-width: 30px;
        }

        .refresh-button.refreshing {
            background: #10B981;
            animation: pulse 0.5s ease-in-out;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
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

        .job-overall-progress {
            margin-top: 20px;
            padding-top: 20px;
            border-top: 1px solid #e9ecef;
        }

        .overall-progress-label {
            font-size: 12px;
            font-weight: 600;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
        }

        .job-overall-progress .progress-bar-container {
            height: 16px;
        }

        .job-overall-progress .progress-text {
            margin-top: 8px;
        }

        .job-overall-progress .progress-percent {
            font-size: 14px;
        }

        .job-overall-progress .progress-count {
            font-size: 13px;
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
            margin-bottom: 8px;
        }

        /* Expected count display - shows Stage 1 chunk count for Stage 2 visibility */
        .expected-count {
            font-size: 10px;
            font-weight: 600;
            color: #0071BC;
            background: #E3F2FD;
            padding: 4px 10px;
            border-radius: 12px;
            margin-bottom: 10px;
            display: inline-block;
        }

        /* Stage metrics display */
        .stage-metrics {
            font-size: 9px;
            color: #626F86;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #E5E8EB;
        }

        .stage-metrics .metric-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 2px;
        }

        .stage-metrics .metric-label {
            color: #8993A4;
        }

        .stage-metrics .metric-value {
            font-weight: 600;
            color: #44546F;
        }

        .stage-metrics .metric-value.rate {
            color: #10B981;
        }

        /* Processing metrics panel */
        .metrics-panel {
            background: linear-gradient(135deg, #F0F9FF 0%, #E0F2FE 100%);
            border: 1px solid #BAE6FD;
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 20px;
        }

        .metrics-panel h3 {
            font-size: 14px;
            font-weight: 600;
            color: #0369A1;
            margin: 0 0 12px 0;
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 16px;
        }

        .metric-card {
            background: white;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }

        .metric-card .metric-value {
            font-size: 24px;
            font-weight: 700;
            color: #0284C7;
        }

        .metric-card .metric-label {
            font-size: 11px;
            color: #64748B;
            margin-top: 4px;
        }

        .metric-card.rate .metric-value {
            color: #10B981;
        }

        .metric-card.time .metric-value {
            color: #8B5CF6;
        }

        /* Results panel for completed jobs */
        .results-panel {
            margin-top: 20px;
            padding: 20px;
            background: linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%);
            border: 1px solid #10B981;
            border-radius: 12px;
        }

        .results-panel h4 {
            font-size: 16px;
            font-weight: 600;
            color: #065F46;
            margin: 0 0 16px 0;
        }

        .results-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }

        .result-item {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .result-label {
            font-size: 11px;
            font-weight: 600;
            color: #047857;
            text-transform: uppercase;
        }

        .result-value {
            font-size: 14px;
            color: #065F46;
        }

        .result-value code {
            background: rgba(16, 185, 129, 0.15);
            padding: 2px 8px;
            border-radius: 4px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 13px;
        }

        .results-links {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }

        .result-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 12px 20px;
            background: white;
            border: 2px solid #10B981;
            border-radius: 8px;
            color: #065F46;
            text-decoration: none;
            font-weight: 600;
            font-size: 14px;
            transition: all 0.2s;
        }

        .result-link:hover {
            background: #10B981;
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }

        .result-link-primary {
            background: #10B981;
            color: white;
        }

        .result-link-primary:hover {
            background: #059669;
            border-color: #059669;
        }

        .stage-counts {
            display: flex;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        /* Progress Bar */
        .stage-progress {
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid rgba(0,0,0,0.08);
        }

        .progress-bar-container {
            background: #e9ecef;
            border-radius: 8px;
            height: 12px;
            overflow: hidden;
            position: relative;
        }

        .progress-bar-fill {
            height: 100%;
            border-radius: 8px;
            transition: width 0.6s ease-out;
            display: flex;
        }

        .progress-segment {
            height: 100%;
            transition: width 0.6s ease-out;
        }

        .progress-segment.completed {
            background: linear-gradient(90deg, #10B981 0%, #34D399 100%);
        }

        .progress-segment.failed {
            background: linear-gradient(90deg, #DC2626 0%, #F87171 100%);
        }

        .progress-segment.processing {
            background: linear-gradient(90deg, #F59E0B 0%, #FBBF24 100%);
            animation: progress-pulse 1.5s ease-in-out infinite;
        }

        .progress-segment.queued {
            background: linear-gradient(90deg, #6B7280 0%, #9CA3AF 100%);
        }

        .progress-segment.pending {
            background: linear-gradient(90deg, #9333EA 0%, #A855F7 100%);
        }

        @keyframes progress-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .progress-text {
            display: flex;
            justify-content: space-between;
            margin-top: 6px;
            font-size: 11px;
        }

        .progress-percent {
            font-weight: 700;
            color: #053657;
        }

        .progress-count {
            color: #626F86;
        }

        /* Active stage glow effect */
        .stage-box.active {
            border-color: #F59E0B;
            background: #FFFBEB;
            box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
            animation: active-glow 2s ease-in-out infinite;
        }

        @keyframes active-glow {
            0%, 100% { box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2); }
            50% { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.15); }
        }

        .count-badge {
            font-size: 11px;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 10px;
        }

        .count-pending {
            background: #f3e8ff;
            color: #9333ea;
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

        .status-pending {
            background: #f3e8ff;
            color: #9333ea;
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

        .task-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
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

        .view-result-button, .view-memory-button {
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
            margin-right: 8px;
        }

        .view-result-button:hover, .view-memory-button:hover {
            background: #f8f9fa;
            border-color: #0071BC;
        }

        .view-memory-button {
            color: #7c3aed;
            border-color: #ddd6fe;
        }

        .view-memory-button:hover {
            border-color: #7c3aed;
            background: #f5f3ff;
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

        /* Memory Metrics Styles */
        .memory-badge {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 600;
            margin-left: 8px;
        }

        .memory-badge.memory-low {
            background: #D1FAE5;
            color: #059669;
        }

        .memory-badge.memory-medium {
            background: #FEF3C7;
            color: #D97706;
        }

        .memory-badge.memory-high {
            background: #FEE2E2;
            color: #DC2626;
        }

        .memory-timeline {
            margin-top: 10px;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            overflow: hidden;
        }

        .memory-timeline-header {
            background: #7c3aed;
            color: white;
            padding: 10px 15px;
            font-size: 12px;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .memory-timeline-body {
            padding: 0;
        }

        .memory-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }

        .memory-table th {
            background: #f1f5f9;
            padding: 8px 12px;
            text-align: left;
            font-weight: 600;
            color: #475569;
            border-bottom: 1px solid #e2e8f0;
        }

        .memory-table td {
            padding: 8px 12px;
            border-bottom: 1px solid #e9ecef;
            font-family: 'Courier New', monospace;
        }

        .memory-table tr:last-child td {
            border-bottom: none;
        }

        .memory-table tr.peak-row {
            background: #fef3c7;
        }

        .memory-table tr.peak-row td {
            font-weight: 600;
        }

        .memory-summary {
            display: flex;
            gap: 20px;
            padding: 12px 15px;
            background: white;
            border-top: 1px solid #e9ecef;
            font-size: 11px;
        }

        .memory-summary-item {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .memory-summary-label {
            color: #64748b;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 9px;
            letter-spacing: 0.5px;
        }

        .memory-summary-value {
            color: #1e293b;
            font-weight: 700;
            font-family: 'Courier New', monospace;
        }

        .oom-warning {
            margin-top: 10px;
            padding: 12px 15px;
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-left: 4px solid #dc2626;
            border-radius: 3px;
        }

        .oom-warning-title {
            color: #dc2626;
            font-weight: 700;
            font-size: 12px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .oom-warning-detail {
            color: #991b1b;
            font-size: 11px;
            line-height: 1.5;
        }

        .oom-warning-detail strong {
            color: #7f1d1d;
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

        // Auto-refresh state
        let autoRefreshInterval = null;
        let countdownInterval = null;
        let countdownValue = 0;

        // Predefined workflow definitions
        const WORKFLOW_DEFINITIONS = {{
            'process_vector': {{
                name: 'Vector ETL Pipeline',
                stages: [
                    {{ number: 1, name: 'Prepare', taskType: 'process_vector_prepare', description: 'Load, validate, chunk data' }},
                    {{ number: 2, name: 'Upload', taskType: 'process_vector_upload', description: 'Fan-out chunk uploads', expectCountFromStage1: true }},
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
            document.getElementById('refreshBtn').addEventListener('click', manualRefresh);

            // Set up auto-refresh controls
            const toggleEl = document.getElementById('autoRefreshToggle');
            const intervalEl = document.getElementById('refreshInterval');

            toggleEl.addEventListener('change', () => {{
                if (toggleEl.checked) {{
                    startAutoRefresh();
                }} else {{
                    stopAutoRefresh();
                }}
            }});

            intervalEl.addEventListener('change', () => {{
                if (toggleEl.checked) {{
                    stopAutoRefresh();
                    startAutoRefresh();
                }}
            }});

            // Start auto-refresh by default
            startAutoRefresh();
        }});

        // Manual refresh with visual feedback
        function manualRefresh() {{
            const btn = document.getElementById('refreshBtn');
            btn.classList.add('refreshing');
            loadData().finally(() => {{
                setTimeout(() => btn.classList.remove('refreshing'), 500);
            }});

            // Reset countdown if auto-refresh is on
            if (document.getElementById('autoRefreshToggle').checked) {{
                stopAutoRefresh();
                startAutoRefresh();
            }}
        }}

        // Start auto-refresh
        function startAutoRefresh() {{
            const intervalSec = parseInt(document.getElementById('refreshInterval').value) || 30;
            countdownValue = intervalSec;
            updateCountdown();

            // Countdown timer (updates every second)
            countdownInterval = setInterval(() => {{
                countdownValue--;
                updateCountdown();

                if (countdownValue <= 0) {{
                    countdownValue = intervalSec;
                    loadData();
                }}
            }}, 1000);
        }}

        // Stop auto-refresh
        function stopAutoRefresh() {{
            if (countdownInterval) {{
                clearInterval(countdownInterval);
                countdownInterval = null;
            }}
            document.getElementById('refreshCountdown').textContent = '';
        }}

        // Update countdown display
        function updateCountdown() {{
            const el = document.getElementById('refreshCountdown');
            if (countdownValue > 0) {{
                el.textContent = countdownValue + 's';
            }} else {{
                el.textContent = '...';
            }}
        }}

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
                const metrics = tasksData.metrics || {{}};
                const job = jobResponse.job || jobResponse;

                // Render job summary (pass tasks for Stage 1 metadata)
                renderJobSummary(job, tasks);

                // Render metrics panel if we have metrics
                renderMetricsPanel(metrics, job);

                // Render workflow diagram (pass metrics for stage-level display)
                renderWorkflowDiagram(job, tasks, metrics);

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

        // Helper: Get Stage 1 metadata from completed task or job result
        function getStage1Metadata(job, tasks) {{
            // First check job result_data summary (for completed jobs)
            const summary = job.result_data?.summary;
            if (summary?.stage_1_metadata) {{
                return summary.stage_1_metadata;
            }}

            // Otherwise check Stage 1 task result (for in-progress jobs)
            const stage1Task = tasks?.find(t =>
                t.stage === 1 &&
                t.status === 'completed' &&
                t.result_data
            );

            if (stage1Task?.result_data?.result) {{
                const r = stage1Task.result_data.result;
                return {{
                    chunk_count: r.num_chunks || r.chunk_count,
                    total_features: r.total_features,
                    chunk_size_used: r.chunk_size_used
                }};
            }}
            return null;
        }}

        // Render job summary card
        function renderJobSummary(job, tasks) {{
            const taskCounts = job.result_data?.tasks_by_status || {{}};
            const pending = taskCounts.pending || 0;
            const queued = taskCounts.queued || 0;
            const processing = taskCounts.processing || 0;
            const completed = taskCounts.completed || 0;
            const failed = taskCounts.failed || 0;
            const total = pending + queued + processing + completed + failed;

            // Get Stage 1 metadata if available
            const stage1Meta = getStage1Metadata(job, tasks);

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

            // Calculate overall progress
            const doneTasks = completed + failed;
            const progressPct = total > 0 ? ((doneTasks / total) * 100).toFixed(0) : 0;

            // Build Stage 1 metadata items if available
            let stage1MetaItems = '';
            if (stage1Meta) {{
                if (stage1Meta.total_features) {{
                    stage1MetaItems += `
                        <div class="summary-item">
                            <span class="summary-label">Total Features</span>
                            <span class="summary-value" style="font-size: 14px;">${{stage1Meta.total_features.toLocaleString()}}</span>
                        </div>
                    `;
                }}
                if (stage1Meta.chunk_count) {{
                    stage1MetaItems += `
                        <div class="summary-item">
                            <span class="summary-label">Chunks</span>
                            <span class="summary-value" style="color: #0071BC;">${{stage1Meta.chunk_count}}</span>
                        </div>
                    `;
                }}
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
                    ${{stage1MetaItems}}
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

            // Add overall progress bar if there are tasks
            if (total > 0) {{
                const counts = {{ pending, queued, processing, completed, failed }};
                html += `
                    <div class="job-overall-progress">
                        <div class="overall-progress-label">Overall Progress</div>
                        ${{renderProgressBar(counts, total)}}
                    </div>
                `;
            }}

            // Add results panel for completed jobs with URLs
            if (job.status === 'completed' && job.result_data) {{
                const resultData = job.result_data;
                const viewerUrl = resultData.viewer_url;
                const ogcFeaturesUrl = resultData.ogc_features_url;
                const tableName = resultData.table_name;
                const schema = resultData.schema;
                const blobName = resultData.blob_name;

                if (viewerUrl || ogcFeaturesUrl) {{
                    html += `
                        <div class="results-panel">
                            <h4>🎉 Results</h4>
                            <div class="results-grid">
                    `;

                    if (tableName) {{
                        html += `
                            <div class="result-item">
                                <span class="result-label">Table</span>
                                <span class="result-value"><code>${{schema || 'geo'}}.${{tableName}}</code></span>
                            </div>
                        `;
                    }}

                    if (blobName) {{
                        html += `
                            <div class="result-item">
                                <span class="result-label">Source</span>
                                <span class="result-value">${{blobName}}</span>
                            </div>
                        `;
                    }}

                    html += `</div><div class="results-links">`;

                    if (viewerUrl) {{
                        html += `
                            <a href="${{viewerUrl}}" target="_blank" class="result-link result-link-primary">
                                🗺️ Open Map Viewer
                            </a>
                        `;
                    }}

                    if (ogcFeaturesUrl) {{
                        html += `
                            <a href="${{ogcFeaturesUrl}}" target="_blank" class="result-link">
                                📡 OGC Features API
                            </a>
                        `;
                    }}

                    html += `</div></div>`;
                }}
            }}

            document.getElementById('job-summary-card').innerHTML = html;
        }}

        // Render metrics panel with processing rate and execution time stats
        function renderMetricsPanel(metrics, job) {{
            // Only show if we have meaningful metrics
            const hasMetrics = Object.values(metrics).some(m => m.avg_execution_time_ms !== null);
            if (!hasMetrics) {{
                return; // No metrics to display yet
            }}

            // Find stage 2 metrics (the parallel upload stage with the most data)
            const stage2Metrics = metrics[2] || null;
            const currentStage = job.stage || 1;

            let html = `
                <div class="metrics-panel">
                    <h3>📊 Processing Metrics</h3>
                    <div class="metrics-grid">
            `;

            // Stage 2 metrics (most interesting for parallel processing)
            if (stage2Metrics && stage2Metrics.avg_execution_time_ms) {{
                html += `
                    <div class="metric-card rate">
                        <div class="metric-value">${{stage2Metrics.tasks_per_minute || '-'}}</div>
                        <div class="metric-label">Tasks/Min (Stage 2)</div>
                    </div>
                    <div class="metric-card time">
                        <div class="metric-value">${{stage2Metrics.avg_execution_time_formatted || '-'}}</div>
                        <div class="metric-label">Avg Task Time</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">${{(stage2Metrics.min_execution_time_ms/1000).toFixed(1)}}s - ${{(stage2Metrics.max_execution_time_ms/1000).toFixed(1)}}s</div>
                        <div class="metric-label">Min - Max Time</div>
                    </div>
                `;

                // Estimate time remaining if still processing
                if (currentStage === 2 && stage2Metrics.pending > 0 && stage2Metrics.avg_execution_time_ms) {{
                    const remainingMs = stage2Metrics.pending * stage2Metrics.avg_execution_time_ms;
                    const remainingMin = Math.ceil(remainingMs / 60000);
                    html += `
                        <div class="metric-card">
                            <div class="metric-value">~${{remainingMin}} min</div>
                            <div class="metric-label">Est. Remaining</div>
                        </div>
                    `;
                }}
            }}

            // Show Stage 1 metrics if available
            const stage1Metrics = metrics[1] || null;
            if (stage1Metrics && stage1Metrics.avg_execution_time_ms) {{
                html += `
                    <div class="metric-card time">
                        <div class="metric-value">${{stage1Metrics.avg_execution_time_formatted || '-'}}</div>
                        <div class="metric-label">Stage 1 Time</div>
                    </div>
                `;
            }}

            html += `
                    </div>
                </div>
            `;

            // Insert after workflow diagram
            const workflowDiagram = document.getElementById('workflow-diagram');
            const metricsDiv = document.createElement('div');
            metricsDiv.innerHTML = html;
            workflowDiagram.parentNode.insertBefore(metricsDiv.firstElementChild, workflowDiagram.nextSibling);
        }}

        // Helper: Get expected Stage 2 task count from Stage 1 result
        function getExpectedStage2Count(tasks) {{
            // Find completed Stage 1 task with result data
            const stage1Task = tasks.find(t =>
                t.stage === 1 &&
                t.status === 'completed' &&
                t.task_type === 'process_vector_prepare' &&
                t.result_data
            );

            if (stage1Task && stage1Task.result_data) {{
                const result = stage1Task.result_data.result || {{}};
                return result.num_chunks || result.chunk_count || null;
            }}
            return null;
        }}

        // Render workflow diagram
        function renderWorkflowDiagram(job, tasks, metrics = {{}}) {{
            const workflowDef = WORKFLOW_DEFINITIONS[job.job_type];

            if (!workflowDef) {{
                // Unknown workflow - show generic based on actual tasks
                renderGenericWorkflow(job, tasks);
                return;
            }}

            // Get expected Stage 2 count if available (for process_vector)
            const expectedStage2Count = getExpectedStage2Count(tasks);

            // Group tasks by stage
            const tasksByStage = {{}};
            tasks.forEach(task => {{
                const stage = task.stage || 0;
                if (!tasksByStage[stage]) {{
                    tasksByStage[stage] = {{ pending: 0, queued: 0, processing: 0, completed: 0, failed: 0 }};
                }}
                tasksByStage[stage][task.status] = (tasksByStage[stage][task.status] || 0) + 1;
            }});

            let html = `
                <div class="workflow-title">${{workflowDef.name}}</div>
                <div class="workflow-stages">
            `;

            workflowDef.stages.forEach((stage, index) => {{
                const stageCounts = tasksByStage[stage.number] || {{ pending: 0, queued: 0, processing: 0, completed: 0, failed: 0 }};
                const totalTasks = stageCounts.pending + stageCounts.queued + stageCounts.processing + stageCounts.completed + stageCounts.failed;

                // Determine stage status
                // Priority: failed > processing > queued > pending > completed > no-tasks
                let stageStatus = 'pending';
                if (stageCounts.failed > 0) {{
                    stageStatus = 'failed';
                }} else if (stageCounts.processing > 0) {{
                    stageStatus = 'active';
                }} else if (stageCounts.queued > 0) {{
                    stageStatus = 'active';
                }} else if (stageCounts.pending > 0) {{
                    stageStatus = 'active';
                }} else if (stageCounts.completed > 0) {{
                    stageStatus = 'completed';
                }}

                // Add arrow before stage (except first)
                if (index > 0) {{
                    html += `<div class="stage-arrow">&#8594;</div>`;
                }}

                // Show expected count badge for Stage 2 if available
                let expectedBadge = '';
                if (stage.expectCountFromStage1 && expectedStage2Count) {{
                    expectedBadge = `<div class="expected-count">Expected: ${{expectedStage2Count}} tasks</div>`;
                }}

                html += `
                    <div class="stage-box ${{stageStatus}}" onclick="scrollToStage(${{stage.number}})">
                        <div class="stage-number">${{stage.number}}</div>
                        <div class="stage-name">${{stage.name}}</div>
                        <div class="stage-task-type">${{stage.taskType}}</div>
                        ${{expectedBadge}}
                        <div class="stage-counts">
                `;

                if (totalTasks === 0) {{
                    html += `<span class="count-badge count-queued">No tasks</span>`;
                }} else {{
                    if (stageCounts.pending > 0) {{
                        html += `<span class="count-badge count-pending">P:${{stageCounts.pending}}</span>`;
                    }}
                    if (stageCounts.queued > 0) {{
                        html += `<span class="count-badge count-queued">Q:${{stageCounts.queued}}</span>`;
                    }}
                    if (stageCounts.processing > 0) {{
                        html += `<span class="count-badge count-processing">R:${{stageCounts.processing}}</span>`;
                    }}
                    if (stageCounts.completed > 0) {{
                        html += `<span class="count-badge count-completed">C:${{stageCounts.completed}}</span>`;
                    }}
                    if (stageCounts.failed > 0) {{
                        html += `<span class="count-badge count-failed">F:${{stageCounts.failed}}</span>`;
                    }}
                }}

                html += `</div>`;

                // Add progress bar if there are tasks
                if (totalTasks > 0) {{
                    html += renderProgressBar(stageCounts, totalTasks);
                }}

                // Add stage metrics if available
                const stageMetrics = metrics[stage.number];
                if (stageMetrics && stageMetrics.avg_execution_time_ms) {{
                    html += `
                        <div class="stage-metrics">
                            <div class="metric-row">
                                <span class="metric-label">Avg:</span>
                                <span class="metric-value">${{stageMetrics.avg_execution_time_formatted}}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">Rate:</span>
                                <span class="metric-value rate">${{stageMetrics.tasks_per_minute || '-'}} /min</span>
                            </div>
                        </div>
                    `;
                }}

                html += `</div>`;
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
                    tasksByStage[stage] = {{ pending: 0, queued: 0, processing: 0, completed: 0, failed: 0, taskType: task.task_type }};
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
                const totalTasks = stageCounts.pending + stageCounts.queued + stageCounts.processing + stageCounts.completed + stageCounts.failed;

                let stageStatus = 'pending';
                if (stageCounts.failed > 0) stageStatus = 'failed';
                else if (stageCounts.processing > 0) stageStatus = 'active';
                else if (stageCounts.queued > 0) stageStatus = 'active';
                else if (stageCounts.pending > 0) stageStatus = 'active';
                else if (stageCounts.completed > 0) stageStatus = 'completed';

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

                if (stageCounts.pending > 0) html += `<span class="count-badge count-pending">P:${{stageCounts.pending}}</span>`;
                if (stageCounts.queued > 0) html += `<span class="count-badge count-queued">Q:${{stageCounts.queued}}</span>`;
                if (stageCounts.processing > 0) html += `<span class="count-badge count-processing">R:${{stageCounts.processing}}</span>`;
                if (stageCounts.completed > 0) html += `<span class="count-badge count-completed">C:${{stageCounts.completed}}</span>`;
                if (stageCounts.failed > 0) html += `<span class="count-badge count-failed">F:${{stageCounts.failed}}</span>`;

                html += `</div>`;

                // Add progress bar
                if (totalTasks > 0) {{
                    html += renderProgressBar(stageCounts, totalTasks);
                }}

                html += `</div>`;
            }});

            html += `</div>`;
            document.getElementById('workflow-diagram').innerHTML = html;
        }}

        // Render progress bar HTML
        function renderProgressBar(counts, total) {{
            if (total === 0) return '';

            const completedPct = (counts.completed / total) * 100;
            const failedPct = (counts.failed / total) * 100;
            const processingPct = (counts.processing / total) * 100;
            const queuedPct = (counts.queued / total) * 100;
            const pendingPct = (counts.pending / total) * 100;

            // Calculate overall progress (completed + failed = done)
            const donePct = completedPct + failedPct;
            const doneCount = counts.completed + counts.failed;

            return `
                <div class="stage-progress">
                    <div class="progress-bar-container">
                        <div class="progress-bar-fill">
                            <div class="progress-segment completed" style="width: ${{completedPct}}%"></div>
                            <div class="progress-segment failed" style="width: ${{failedPct}}%"></div>
                            <div class="progress-segment processing" style="width: ${{processingPct}}%"></div>
                            <div class="progress-segment queued" style="width: ${{queuedPct}}%"></div>
                            <div class="progress-segment pending" style="width: ${{pendingPct}}%"></div>
                        </div>
                    </div>
                    <div class="progress-text">
                        <span class="progress-percent">${{donePct.toFixed(0)}}% done</span>
                        <span class="progress-count">${{doneCount}}/${{total}} tasks</span>
                    </div>
                </div>
            `;
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
                const pending = stageTasks.filter(t => t.status === 'pending').length;
                const queued = stageTasks.filter(t => t.status === 'queued').length;
                const processing = stageTasks.filter(t => t.status === 'processing').length;
                const completed = stageTasks.filter(t => t.status === 'completed').length;
                const failed = stageTasks.filter(t => t.status === 'failed').length;

                html += `
                    <div class="stage-group" id="stage-group-${{stage}}">
                        <div class="stage-header" onclick="toggleStage('stage-${{stage}}')">
                            <h4>Stage ${{stage}} (${{stageTasks.length}} tasks)</h4>
                            <div class="stage-stats">
                                <span style="color: #9333ea;">P:${{pending}}</span>
                                <span style="color: #626F86;">Q:${{queued}}</span>
                                <span style="color: #F59E0B;">R:${{processing}}</span>
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

                    // Check for OOM warning (failed task with high memory at last checkpoint)
                    const oomWarningHTML = renderOOMWarning(task);

                    const resultButton = task.result_data ? `
                        <button class="view-result-button" onclick="event.stopPropagation(); toggleResult('task-${{task.task_id}}')">
                            View Result
                        </button>
                        <div id="task-${{task.task_id}}" class="result-json hidden">
                            <pre>${{JSON.stringify(task.result_data, null, 2)}}</pre>
                        </div>
                    ` : '';

                    // Memory button and timeline
                    const memoryHTML = renderMemorySection(task);

                    // Memory badge for task header
                    const memoryBadge = renderMemoryBadge(task);

                    html += `
                        <div class="task-card">
                            <div class="task-header">
                                <div>
                                    <div class="task-type">${{task.task_type}}${{memoryBadge}}</div>
                                    <div class="task-id">${{task.task_id.substring(0, 8)}}...${{task.task_id.slice(-8)}}</div>
                                </div>
                                <span class="status-badge status-${{task.status}}">${{task.status}}</span>
                            </div>
                            ${{errorHTML}}
                            ${{oomWarningHTML}}
                            <div class="task-actions">
                                ${{resultButton}}
                                ${{memoryHTML}}
                            </div>
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

        // ============================================================
        // MEMORY METRICS RENDERING FUNCTIONS
        // ============================================================

        // Get peak RSS from memory snapshots
        function getPeakMemory(task) {{
            if (!task.metadata) return null;

            const snapshots = task.metadata.memory_snapshots || [];
            if (snapshots.length === 0) return null;

            let peak = {{ rss_mb: 0, checkpoint: '', index: -1 }};
            snapshots.forEach((snap, idx) => {{
                const rss = snap.process_rss_mb || snap.rss_mb || 0;
                if (rss > peak.rss_mb) {{
                    peak = {{ rss_mb: rss, checkpoint: snap.checkpoint || snap.name, index: idx }};
                }}
            }});

            return peak.rss_mb > 0 ? peak : null;
        }}

        // Render memory badge for task header
        function renderMemoryBadge(task) {{
            const peak = getPeakMemory(task);
            if (!peak) return '';

            // Determine color based on peak RSS
            let colorClass = 'memory-low';
            if (peak.rss_mb >= 2048) {{
                colorClass = 'memory-high';
            }} else if (peak.rss_mb >= 1024) {{
                colorClass = 'memory-medium';
            }}

            const displayMB = peak.rss_mb >= 1024
                ? (peak.rss_mb / 1024).toFixed(1) + ' GB'
                : Math.round(peak.rss_mb) + ' MB';

            return `<span class="memory-badge ${{colorClass}}">📊 ${{displayMB}}</span>`;
        }}

        // Render OOM warning for failed tasks with high memory
        function renderOOMWarning(task) {{
            if (task.status !== 'failed') return '';
            if (!task.metadata) return '';

            const lastCheckpoint = task.metadata.last_memory_checkpoint;
            const snapshots = task.metadata.memory_snapshots || [];

            if (!lastCheckpoint && snapshots.length === 0) return '';

            // Check if last checkpoint shows high memory pressure
            const lastSnap = lastCheckpoint || snapshots[snapshots.length - 1];
            if (!lastSnap) return '';

            const rss = lastSnap.rss_mb || lastSnap.process_rss_mb || 0;
            const systemPercent = lastSnap.system_percent || 0;
            const availableMB = lastSnap.available_mb || lastSnap.system_available_mb || 0;

            // Only show warning if memory was high when task failed
            // (RSS > 2GB or system > 85% used or available < 500MB)
            if (rss < 2048 && systemPercent < 85 && availableMB > 500) return '';

            const checkpointName = lastSnap.name || lastSnap.checkpoint || 'unknown';

            return `
                <div class="oom-warning">
                    <div class="oom-warning-title">⚠️ Possible Memory Issue</div>
                    <div class="oom-warning-detail">
                        <strong>Last checkpoint:</strong> ${{checkpointName}}<br>
                        <strong>Process RSS:</strong> ${{rss.toFixed(0)}} MB<br>
                        <strong>System available:</strong> ${{availableMB.toFixed(0)}} MB (${{(100 - systemPercent).toFixed(1)}}% free)<br>
                        Task stopped responding after this checkpoint.
                    </div>
                </div>
            `;
        }}

        // Render memory timeline section
        function renderMemorySection(task) {{
            if (!task.metadata) return '';

            const snapshots = task.metadata.memory_snapshots || [];
            if (snapshots.length === 0) return '';

            const peak = getPeakMemory(task);
            const taskIdShort = task.task_id.substring(0, 8);

            // Calculate total duration if timestamps available
            let totalDuration = '';
            if (snapshots.length >= 2) {{
                try {{
                    const firstTime = new Date(snapshots[0].timestamp);
                    const lastTime = new Date(snapshots[snapshots.length - 1].timestamp);
                    const durationSec = (lastTime - firstTime) / 1000;
                    if (durationSec > 0) {{
                        totalDuration = durationSec >= 60
                            ? (durationSec / 60).toFixed(1) + ' min'
                            : durationSec.toFixed(1) + 's';
                    }}
                }} catch (e) {{
                    // Ignore timestamp parsing errors
                }}
            }}

            // Build table rows
            let tableRows = '';
            let prevTime = null;

            snapshots.forEach((snap, idx) => {{
                const checkpoint = snap.checkpoint || snap.name || `Step ${{idx + 1}}`;
                const rss = snap.process_rss_mb || snap.rss_mb || 0;
                const available = snap.system_available_mb || snap.available_mb || 0;
                const systemPct = snap.system_percent || 0;
                const cpu = snap.cpu_percent || snap.process_cpu_percent || 0;

                // Calculate duration from previous checkpoint
                let duration = '--';
                if (snap.timestamp && prevTime) {{
                    try {{
                        const currTime = new Date(snap.timestamp);
                        const durationSec = (currTime - prevTime) / 1000;
                        duration = durationSec >= 60
                            ? (durationSec / 60).toFixed(1) + 'm'
                            : durationSec.toFixed(1) + 's';
                    }} catch (e) {{}}
                }}
                if (snap.timestamp) {{
                    try {{
                        prevTime = new Date(snap.timestamp);
                    }} catch (e) {{}}
                }}

                const isPeak = peak && idx === peak.index;
                const rowClass = isPeak ? 'peak-row' : '';
                const peakMarker = isPeak ? ' ⬅ Peak' : '';

                tableRows += `
                    <tr class="${{rowClass}}">
                        <td>${{checkpoint}}${{peakMarker}}</td>
                        <td>${{rss.toFixed(0)}}</td>
                        <td>${{available.toFixed(0)}}</td>
                        <td>${{systemPct.toFixed(0)}}%</td>
                        <td>${{cpu.toFixed(0)}}%</td>
                        <td>${{duration}}</td>
                    </tr>
                `;
            }});

            // Summary stats
            const peakDisplay = peak
                ? (peak.rss_mb >= 1024 ? (peak.rss_mb / 1024).toFixed(2) + ' GB' : peak.rss_mb.toFixed(0) + ' MB')
                : 'N/A';
            const peakCheckpoint = peak ? peak.checkpoint : 'N/A';

            return `
                <button class="view-memory-button" onclick="event.stopPropagation(); toggleMemory('memory-${{taskIdShort}}')">
                    📊 Memory (${{snapshots.length}} checkpoints)
                </button>
                <div id="memory-${{taskIdShort}}" class="memory-timeline hidden">
                    <div class="memory-timeline-header">
                        <span>Memory Timeline</span>
                        <span>${{snapshots.length}} checkpoints</span>
                    </div>
                    <div class="memory-timeline-body">
                        <table class="memory-table">
                            <thead>
                                <tr>
                                    <th>Checkpoint</th>
                                    <th>RSS (MB)</th>
                                    <th>Avail (MB)</th>
                                    <th>Sys %</th>
                                    <th>CPU %</th>
                                    <th>Duration</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${{tableRows}}
                            </tbody>
                        </table>
                        <div class="memory-summary">
                            <div class="memory-summary-item">
                                <span class="memory-summary-label">Peak RSS</span>
                                <span class="memory-summary-value">${{peakDisplay}}</span>
                            </div>
                            <div class="memory-summary-item">
                                <span class="memory-summary-label">Peak At</span>
                                <span class="memory-summary-value">${{peakCheckpoint}}</span>
                            </div>
                            <div class="memory-summary-item">
                                <span class="memory-summary-label">Total Duration</span>
                                <span class="memory-summary-value">${{totalDuration || 'N/A'}}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }}

        // Toggle memory timeline visibility
        function toggleMemory(memoryId) {{
            const memoryEl = document.getElementById(memoryId);
            if (memoryEl) {{
                memoryEl.classList.toggle('hidden');
            }}
        }}

        // ============================================================
        // ERROR/UTILITY FUNCTIONS
        // ============================================================

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
