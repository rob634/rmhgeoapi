"""
Task monitoring interface module.

Web dashboard for viewing tasks of a specific job with workflow visualization.

Features:
    - HTMX-powered auto-refresh
    - Visual workflow diagram showing predefined stages
    - Task counts per stage with status colors (P/Q/R/C/F)
    - Expandable task detail sections
    - Docker Worker Progress Panel (F7.19 - 19 JAN 2026):
      - Internal phase visualization (Validation → COG → STAC)
      - Real-time progress bar and status message
      - Checkpoint phase indicator

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
                        <button id="resubmitBtn" class="resubmit-button" onclick="showResubmitModal()">
                            🔄 Resubmit Job
                        </button>
                        <button id="deleteBtn" class="delete-button" onclick="showDeleteModal()">
                            🗑️ Delete Job
                        </button>
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

            <!-- Event Timeline Swimlane (03 FEB 2026) - Always Visible -->
            <div id="events-section" class="events-section">
                <div class="events-header">
                    <div class="events-header-left">
                        <h3>📊 Event Timeline</h3>
                        <span class="events-count" id="events-count"></span>
                    </div>
                    <div class="events-header-right">
                        <button id="refreshEventsBtn" class="events-refresh-btn" onclick="loadEvents()">
                            Refresh
                        </button>
                    </div>
                </div>
                <div id="events-content" class="events-content">
                    <div id="events-loading" class="events-loading hidden">
                        <div class="spinner-small"></div>
                        <span>Loading events...</span>
                    </div>
                    <div id="events-empty" class="events-empty hidden">
                        <span>No events recorded yet</span>
                    </div>
                    <div id="swimlane-container" class="swimlane-container hidden">
                        <!-- Swimlane will be rendered here by JavaScript -->
                    </div>
                </div>
            </div>

            <!-- Job Details Container (moved below events) -->
            <div id="job-details-container"></div>

            <!-- Processing Rate Banner -->
            <div id="processing-rate-banner" class="processing-rate-banner hidden">
                <div class="rate-item">
                    <span class="rate-icon">⚡</span>
                    <span class="rate-value" id="rate-tasks-per-min">--</span>
                    <span class="rate-label">tasks/min</span>
                </div>
                <div class="rate-item">
                    <span class="rate-icon">⏱️</span>
                    <span class="rate-value" id="rate-eta">--</span>
                    <span class="rate-label">ETA</span>
                </div>
                <div class="rate-item">
                    <span class="rate-icon">📊</span>
                    <span class="rate-value" id="rate-avg-time">--</span>
                    <span class="rate-label">avg time</span>
                </div>
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

            <!-- Logs Section (12 JAN 2026) -->
            <div id="logs-section" class="logs-section">
                <div class="logs-header" onclick="toggleLogsSection()">
                    <div class="logs-header-left">
                        <span class="logs-toggle-icon" id="logs-toggle-icon">▶</span>
                        <h3>📋 Job Logs</h3>
                        <span class="logs-count" id="logs-count"></span>
                    </div>
                    <div class="logs-header-right">
                        <select id="logsLevelFilter" class="logs-filter-select" onclick="event.stopPropagation()">
                            <option value="DEBUG">All (DEBUG+)</option>
                            <option value="INFO" selected>INFO+</option>
                            <option value="WARNING">WARNING+</option>
                            <option value="ERROR">ERROR only</option>
                        </select>
                        <button id="refreshLogsBtn" class="logs-refresh-btn" onclick="event.stopPropagation(); loadLogs()">
                            Refresh Logs
                        </button>
                    </div>
                </div>
                <div id="logs-content" class="logs-content hidden">
                    <div id="logs-loading" class="logs-loading hidden">
                        <div class="spinner-small"></div>
                        <span>Loading logs from Application Insights...</span>
                    </div>
                    <div id="logs-empty" class="logs-empty hidden">
                        <span>No logs found for this job</span>
                    </div>
                    <div id="logs-error" class="logs-error hidden">
                        <span id="logs-error-message"></span>
                    </div>
                    <table id="logs-table" class="logs-table hidden">
                        <thead>
                            <tr>
                                <th class="log-col-time">Timestamp</th>
                                <th class="log-col-level">Level</th>
                                <th class="log-col-component">Component</th>
                                <th class="log-col-stage">Stage</th>
                                <th class="log-col-message">Message</th>
                            </tr>
                        </thead>
                        <tbody id="logs-table-body">
                        </tbody>
                    </table>
                </div>
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

            <!-- Resubmit Modal (12 JAN 2026) -->
            <div id="resubmit-modal" class="modal-overlay hidden">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>🔄 Resubmit Job</h3>
                        <button class="modal-close" onclick="hideResubmitModal()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div id="resubmit-loading" class="modal-loading hidden">
                            <div class="spinner-small"></div>
                            <span>Analyzing job artifacts...</span>
                        </div>
                        <div id="resubmit-preview" class="hidden">
                            <p class="resubmit-warning">
                                ⚠️ This will <strong>delete all progress</strong> and restart the job from scratch.
                            </p>
                            <div class="cleanup-preview">
                                <h4>Cleanup Preview</h4>
                                <div class="cleanup-item">
                                    <span class="cleanup-label">Tasks to delete:</span>
                                    <span class="cleanup-value" id="preview-tasks">0</span>
                                </div>
                                <div class="cleanup-item">
                                    <span class="cleanup-label">STAC items to delete:</span>
                                    <span class="cleanup-value" id="preview-stac">0</span>
                                </div>
                                <div class="cleanup-item">
                                    <span class="cleanup-label">Tables to drop:</span>
                                    <span class="cleanup-value" id="preview-tables">0</span>
                                </div>
                            </div>
                            <div class="resubmit-options">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="delete-blobs-checkbox">
                                    <span>Also delete blob files (COGs)</span>
                                </label>
                            </div>
                        </div>
                        <div id="resubmit-error" class="modal-error hidden">
                            <span id="resubmit-error-message"></span>
                        </div>
                        <div id="resubmit-success" class="modal-success hidden">
                            <span>✅ Job resubmitted successfully!</span>
                            <p>Redirecting to new job...</p>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="modal-btn modal-btn-cancel" onclick="hideResubmitModal()">Cancel</button>
                        <button class="modal-btn modal-btn-confirm" id="confirm-resubmit-btn" onclick="executeResubmit()">
                            Resubmit Job
                        </button>
                    </div>
                </div>
            </div>

            <!-- Delete Modal (14 JAN 2026) -->
            <div id="delete-modal" class="modal-overlay hidden">
                <div class="modal-content">
                    <div class="modal-header delete-modal-header">
                        <h3>🗑️ Delete Job</h3>
                        <button class="modal-close" onclick="hideDeleteModal()">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div id="delete-loading" class="modal-loading hidden">
                            <div class="spinner-small"></div>
                            <span>Analyzing job artifacts...</span>
                        </div>
                        <div id="delete-preview" class="hidden">
                            <p class="delete-warning">
                                ⚠️ This will <strong>permanently delete</strong> the job and all its data. This cannot be undone.
                            </p>
                            <div class="cleanup-preview">
                                <h4>Items to Delete</h4>
                                <div class="cleanup-item">
                                    <span class="cleanup-label">Tasks to delete:</span>
                                    <span class="cleanup-value" id="delete-preview-tasks">0</span>
                                </div>
                                <div class="cleanup-item">
                                    <span class="cleanup-label">STAC items to delete:</span>
                                    <span class="cleanup-value" id="delete-preview-stac">0</span>
                                </div>
                                <div class="cleanup-item">
                                    <span class="cleanup-label">Tables to drop:</span>
                                    <span class="cleanup-value" id="delete-preview-tables">0</span>
                                </div>
                            </div>
                            <div class="resubmit-options">
                                <label class="checkbox-label">
                                    <input type="checkbox" id="delete-blobs-checkbox-del">
                                    <span>Also delete blob files (COGs)</span>
                                </label>
                            </div>
                        </div>
                        <div id="delete-error" class="modal-error hidden">
                            <span id="delete-error-message"></span>
                        </div>
                        <div id="delete-success" class="modal-success hidden">
                            <span>✅ Job deleted successfully!</span>
                            <p>Redirecting to pipeline...</p>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="modal-btn modal-btn-cancel" onclick="hideDeleteModal()">Cancel</button>
                        <button class="modal-btn modal-btn-danger" id="confirm-delete-btn" onclick="executeDelete()">
                            Delete Job
                        </button>
                    </div>
                </div>
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

        /* Resubmit button (12 JAN 2026) */
        .resubmit-button {
            background: #F59E0B;
            color: white;
            border: none;
            padding: 10px 16px;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 13px;
        }

        .resubmit-button:hover {
            background: #D97706;
        }

        .resubmit-button:disabled {
            background: #e9ecef;
            color: #626F86;
            cursor: not-allowed;
        }

        /* Delete button (14 JAN 2026) */
        .delete-button {
            background: #DC2626;
            color: white;
            border: none;
            padding: 10px 16px;
            border-radius: 3px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 13px;
        }

        .delete-button:hover {
            background: #B91C1C;
        }

        .delete-button:disabled {
            background: #e9ecef;
            color: #626F86;
            cursor: not-allowed;
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

        /* Processing Rate Banner */
        .processing-rate-banner {
            background: linear-gradient(135deg, #0071BC 0%, #00A3DA 100%);
            border-radius: 8px;
            padding: 16px 24px;
            margin-bottom: 20px;
            display: flex;
            justify-content: center;
            gap: 40px;
            box-shadow: 0 4px 12px rgba(0, 113, 188, 0.3);
        }

        .rate-item {
            display: flex;
            align-items: center;
            gap: 8px;
            color: white;
        }

        .rate-icon {
            font-size: 20px;
        }

        .rate-value {
            font-size: 24px;
            font-weight: 700;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .rate-label {
            font-size: 12px;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Job Summary Card */
        .job-summary-card {
            background: white;
            border: 1px solid #e9ecef;
            padding: 12px 20px;
            border-radius: 3px;
            margin-bottom: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .job-summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
            gap: 10px;
        }

        .summary-item {
            text-align: center;
            padding: 8px;
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

        /* Duration display styles */
        .duration-item {
            background: linear-gradient(135deg, #E0F2FE 0%, #BAE6FD 100%);
            border: 1px solid #7DD3FC;
        }

        .duration-value {
            color: #0369A1 !important;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .running-indicator {
            color: #10B981;
            animation: pulse-dot 1s ease-in-out infinite;
            font-size: 12px;
        }

        @keyframes pulse-dot {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }

        /* Stage duration badge */
        .stage-duration-badge {
            background: rgba(255,255,255,0.2);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 13px;
            font-weight: 600;
            margin-left: 12px;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .stage-duration-badge.running {
            background: rgba(16, 185, 129, 0.2);
        }

        .running-dot {
            color: #34D399;
            animation: pulse-dot 1s ease-in-out infinite;
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

        .stage-metrics .metric-value.memory {
            color: #8B5CF6;
        }

        .stage-metrics .metric-value.duration {
            color: #0369A1;
            font-family: 'Monaco', 'Courier New', monospace;
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

        /* ============================================
         * Approval Panel (17 FEB 2026)
         * Inline approve/reject for platform assets
         * ============================================ */

        .approval-panel {
            margin-top: 20px;
            padding: 20px;
            background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%);
            border: 1px solid #3B82F6;
            border-radius: 12px;
        }

        .approval-panel h4 {
            font-size: 16px;
            font-weight: 600;
            color: #1E3A5F;
            margin: 0 0 16px 0;
        }

        .approval-status-row {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-bottom: 16px;
        }

        .approval-status-item {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .approval-status-label {
            font-size: 11px;
            font-weight: 600;
            color: #1D4ED8;
            text-transform: uppercase;
        }

        .approval-status-value {
            font-size: 14px;
            color: #1E3A5F;
        }

        .approval-badge {
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .approval-badge.pending_review {
            background: #FEF3C7;
            color: #92400E;
            border: 1px solid #F59E0B;
        }

        .approval-badge.approved {
            background: #D1FAE5;
            color: #065F46;
            border: 1px solid #10B981;
        }

        .approval-badge.rejected {
            background: #FEE2E2;
            color: #991B1B;
            border: 1px solid #EF4444;
        }

        .approval-badge.revoked {
            background: #F3F4F6;
            color: #4B5563;
            border: 1px solid #9CA3AF;
        }

        .approval-form {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-top: 12px;
        }

        .approval-form-row {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }

        .approval-field {
            display: flex;
            flex-direction: column;
            gap: 4px;
            flex: 1;
            min-width: 180px;
        }

        .approval-field label {
            font-size: 12px;
            font-weight: 600;
            color: #1D4ED8;
        }

        .approval-field input,
        .approval-field select,
        .approval-field textarea {
            padding: 8px 12px;
            border: 1px solid #93C5FD;
            border-radius: 6px;
            font-size: 13px;
            background: white;
            color: #1E3A5F;
            font-family: inherit;
        }

        .approval-field input:focus,
        .approval-field select:focus,
        .approval-field textarea:focus {
            outline: none;
            border-color: #3B82F6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
        }

        .approval-field textarea {
            resize: vertical;
            min-height: 60px;
        }

        .approval-actions {
            display: flex;
            gap: 12px;
            margin-top: 8px;
        }

        .approval-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 10px 20px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .approval-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .approval-btn-approve {
            background: #10B981;
            color: white;
        }

        .approval-btn-approve:hover:not(:disabled) {
            background: #059669;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
        }

        .approval-btn-reject {
            background: #EF4444;
            color: white;
        }

        .approval-btn-reject:hover:not(:disabled) {
            background: #DC2626;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.3);
        }

        .approval-btn-revoke {
            background: #6B7280;
            color: white;
        }

        .approval-btn-revoke:hover:not(:disabled) {
            background: #4B5563;
            transform: translateY(-1px);
        }

        .approval-result {
            margin-top: 12px;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
        }

        .approval-result.success {
            background: #D1FAE5;
            color: #065F46;
            border: 1px solid #10B981;
        }

        .approval-result.error {
            background: #FEE2E2;
            color: #991B1B;
            border: 1px solid #EF4444;
        }

        .approval-readonly {
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.6);
            border-radius: 8px;
            font-size: 13px;
            color: #1E3A5F;
        }

        .approval-readonly strong {
            font-weight: 600;
        }

        .approval-version-section {
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.5);
            border: 1px dashed #93C5FD;
            border-radius: 8px;
        }

        .approval-version-section .section-label {
            font-size: 11px;
            font-weight: 600;
            color: #1D4ED8;
            text-transform: uppercase;
            margin-bottom: 8px;
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
            background: linear-gradient(90deg, #0071BC 0%, #60A5FA 100%);
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
            background: #E3F2FD;
            color: #0071BC;
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
            background: #E3F2FD;
            color: #0071BC;
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

        /* Stage Summary Cards */
        .stage-summary-card {
            background: white;
            border: 1px solid #e9ecef;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            overflow: hidden;
        }

        .stage-summary-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            background: linear-gradient(135deg, #053657 0%, #0a4a7a 100%);
            color: white;
        }

        .stage-summary-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .stage-number-badge {
            width: 32px;
            height: 32px;
            background: rgba(255,255,255,0.2);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 14px;
        }

        .stage-summary-title h4 {
            margin: 0;
            font-size: 16px;
            font-weight: 700;
        }

        .task-type-label {
            font-size: 11px;
            opacity: 0.8;
            font-family: 'Courier New', monospace;
        }

        .stage-status-counts {
            display: flex;
            gap: 8px;
        }

        .stage-summary-body {
            padding: 20px;
        }

        .summary-stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 16px;
        }

        .summary-stat {
            text-align: center;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 6px;
        }

        .summary-stat .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: #053657;
            display: block;
        }

        .summary-stat .stat-label {
            font-size: 11px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 4px;
            display: block;
        }

        /* Execution Time Summary */
        .exec-time-summary {
            background: #F0F9FF;
            border: 1px solid #BAE6FD;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 16px;
        }

        .exec-time-header {
            font-size: 12px;
            font-weight: 600;
            color: #0369A1;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .exec-time-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }

        .exec-time-stat {
            text-align: center;
        }

        .exec-time-stat .stat-label {
            font-size: 10px;
            color: #64748B;
            display: block;
            margin-bottom: 2px;
        }

        .exec-time-stat .stat-value {
            font-size: 14px;
            font-weight: 600;
            color: #0284C7;
            font-family: 'Courier New', monospace;
        }

        /* Memory Summary Section */
        .memory-summary-section {
            background: #F0FDF4;
            border: 1px solid #BBF7D0;
            border-radius: 6px;
            padding: 16px;
            margin-bottom: 16px;
        }

        .memory-summary-header {
            font-size: 12px;
            font-weight: 600;
            color: #166534;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .memory-summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }

        .memory-stat {
            text-align: center;
        }

        .memory-stat .stat-label {
            font-size: 10px;
            color: #64748B;
            display: block;
            margin-bottom: 2px;
        }

        .memory-stat .stat-value {
            font-size: 14px;
            font-weight: 600;
            color: #15803D;
            font-family: 'Courier New', monospace;
        }

        /* Errors Summary */
        .errors-summary {
            background: #FEF2F2;
            border: 1px solid #FECACA;
            border-left: 4px solid #DC2626;
            border-radius: 6px;
            padding: 16px;
        }

        .errors-header {
            font-size: 12px;
            font-weight: 600;
            color: #DC2626;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .errors-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .error-item {
            display: flex;
            gap: 12px;
            padding: 8px 12px;
            background: white;
            border-radius: 4px;
            border: 1px solid #FECACA;
        }

        .error-task-id {
            font-family: 'Courier New', monospace;
            font-size: 11px;
            color: #991B1B;
            font-weight: 600;
            white-space: nowrap;
        }

        .error-message {
            font-size: 12px;
            color: #7F1D1D;
            line-height: 1.4;
        }

        .error-more {
            font-size: 11px;
            color: #DC2626;
            font-style: italic;
            padding-top: 4px;
        }

        @media (max-width: 768px) {
            .summary-stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .exec-time-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .memory-summary-grid {
                grid-template-columns: 1fr;
            }
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
            color: #0071BC;
            border-color: #BAE6FD;
        }

        .view-memory-button:hover {
            border-color: #0071BC;
            background: #E3F2FD;
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
            background: #0071BC;
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

        /* Logs Section (12 JAN 2026) */
        .logs-section {
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-top: 20px;
            overflow: hidden;
        }

        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
            cursor: pointer;
            user-select: none;
        }

        .logs-header:hover {
            background: #f1f3f5;
        }

        .logs-header-left {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .logs-header-left h3 {
            margin: 0;
            font-size: 14px;
            color: #053657;
            font-weight: 600;
        }

        .logs-toggle-icon {
            font-size: 10px;
            color: #626F86;
            transition: transform 0.2s;
        }

        .logs-toggle-icon.expanded {
            transform: rotate(90deg);
        }

        .logs-count {
            background: #e9ecef;
            color: #626F86;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 10px;
        }

        .logs-header-right {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .logs-filter-select {
            padding: 6px 10px;
            border: 1px solid #e9ecef;
            border-radius: 3px;
            font-size: 12px;
            background: white;
            cursor: pointer;
        }

        .logs-refresh-btn {
            padding: 6px 12px;
            background: #0071BC;
            color: white;
            border: none;
            border-radius: 3px;
            font-size: 12px;
            cursor: pointer;
            transition: background 0.2s;
        }

        .logs-refresh-btn:hover {
            background: #005a96;
        }

        .logs-content {
            padding: 0;
            max-height: 400px;
            overflow-y: auto;
        }

        .logs-content.hidden {
            display: none;
        }

        .logs-loading, .logs-empty, .logs-error {
            padding: 30px;
            text-align: center;
            color: #626F86;
            font-size: 13px;
        }

        .logs-loading {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        .spinner-small {
            width: 16px;
            height: 16px;
            border: 2px solid #e9ecef;
            border-top-color: #0071BC;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        .logs-error {
            color: #DC2626;
            background: #FEE2E2;
        }

        .logs-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }

        .logs-table thead {
            background: #f8f9fa;
            position: sticky;
            top: 0;
        }

        .logs-table th {
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
            color: #053657;
            border-bottom: 1px solid #e9ecef;
            white-space: nowrap;
        }

        .logs-table td {
            padding: 8px 12px;
            border-bottom: 1px solid #f1f3f5;
            vertical-align: top;
        }

        .logs-table tr:hover {
            background: #f8f9fa;
        }

        .log-col-time { width: 160px; }
        .log-col-level { width: 70px; }
        .log-col-component { width: 150px; }
        .log-col-stage { width: 60px; text-align: center; }
        .log-col-message { min-width: 300px; }

        .log-level {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .log-level-debug { background: #e9ecef; color: #626F86; }
        .log-level-info { background: #DBEAFE; color: #1D4ED8; }
        .log-level-warning { background: #FEF3C7; color: #B45309; }
        .log-level-error { background: #FEE2E2; color: #DC2626; }
        .log-level-critical { background: #7F1D1D; color: white; }

        .log-timestamp {
            font-family: 'Courier New', monospace;
            color: #626F86;
            font-size: 11px;
        }

        .log-component {
            color: #0071BC;
            font-size: 11px;
        }

        .log-stage {
            display: inline-block;
            background: #e9ecef;
            color: #053657;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        }

        .log-message {
            color: #053657;
            word-break: break-word;
            max-width: 500px;
        }

        /* Event Timeline Section (03 FEB 2026) */
        .events-section {
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-top: 20px;
            overflow: hidden;
        }

        .events-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
        }

        .events-header-left {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .events-header-left h3 {
            margin: 0;
            font-size: 14px;
            color: #053657;
            font-weight: 600;
        }

        .events-count {
            background: #6366F1;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
        }

        .events-header-right {
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .events-refresh-btn {
            padding: 6px 12px;
            background: #6366F1;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
        }

        .events-refresh-btn:hover {
            background: #4F46E5;
        }

        .events-content {
            max-height: 500px;
            overflow-y: auto;
        }

        .events-loading, .events-empty {
            padding: 40px;
            text-align: center;
            color: #626F86;
        }

        .events-loading .spinner-small {
            display: inline-block;
            margin-right: 10px;
        }

        /* Swimlane Visualization */
        .swimlane-container {
            padding: 20px;
        }

        .swimlane-stage {
            margin-bottom: 16px;
        }

        .swimlane-stage-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e9ecef;
        }

        .swimlane-stage-num {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 12px;
            flex-shrink: 0;
        }

        .swimlane-stage-num.completed {
            background: #10B981;
            color: white;
        }

        .swimlane-stage-num.processing {
            background: #0071BC;
            color: white;
            animation: pulse-bg 1.5s ease-in-out infinite;
        }

        .swimlane-stage-num.pending {
            background: #e9ecef;
            color: #626F86;
        }

        .swimlane-stage-num.failed {
            background: #DC2626;
            color: white;
        }

        @keyframes pulse-bg {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .swimlane-stage-name {
            font-weight: 600;
            color: #053657;
            font-size: 13px;
        }

        .swimlane-stage-time {
            color: #626F86;
            font-size: 11px;
            margin-left: auto;
        }

        /* Event chips flow */
        .swimlane-events {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            padding-left: 40px;
        }

        .event-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
            white-space: nowrap;
            transition: transform 0.1s;
        }

        .event-chip:hover {
            transform: scale(1.02);
        }

        .event-chip-icon {
            font-size: 10px;
        }

        /* Event type colors */
        .event-chip.job_created { background: #DBEAFE; color: #1D4ED8; }
        .event-chip.stage_started { background: #E0E7FF; color: #4338CA; }
        .event-chip.stage_completed { background: #D1FAE5; color: #047857; }
        .event-chip.task_queued { background: #FEF3C7; color: #B45309; }
        .event-chip.task_started { background: #DBEAFE; color: #1D4ED8; }
        .event-chip.task_completed { background: #D1FAE5; color: #047857; }
        .event-chip.task_failed { background: #FEE2E2; color: #DC2626; }
        .event-chip.checkpoint { background: #F3E8FF; color: #7C3AED; }
        .event-chip.job_completed { background: #D1FAE5; color: #047857; border: 2px solid #10B981; }
        .event-chip.job_failed { background: #FEE2E2; color: #DC2626; border: 2px solid #DC2626; }

        /* Arrow connector */
        .event-arrow {
            color: #CBD5E1;
            font-size: 12px;
            padding: 0 2px;
        }

        /* Swimlane legend */
        .swimlane-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            padding: 12px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            font-size: 11px;
            color: #626F86;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .legend-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        .legend-dot.checkpoint { background: #7C3AED; }
        .legend-dot.task { background: #1D4ED8; }
        .legend-dot.success { background: #10B981; }
        .legend-dot.failed { background: #DC2626; }

        /* Resubmit Modal (12 JAN 2026) */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }

        .modal-overlay.hidden {
            display: none;
        }

        .modal-content {
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            width: 90%;
            max-width: 480px;
            max-height: 90vh;
            overflow: hidden;
        }

        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            border-bottom: 1px solid #e9ecef;
            background: #f8f9fa;
        }

        .modal-header h3 {
            margin: 0;
            color: #053657;
            font-size: 16px;
        }

        .modal-close {
            background: none;
            border: none;
            font-size: 24px;
            color: #626F86;
            cursor: pointer;
            padding: 0;
            line-height: 1;
        }

        .modal-close:hover {
            color: #DC2626;
        }

        .modal-body {
            padding: 20px;
        }

        .modal-loading {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            padding: 20px;
            color: #626F86;
        }

        .resubmit-warning {
            background: #FEF3C7;
            border: 1px solid #F59E0B;
            border-radius: 4px;
            padding: 12px;
            margin-bottom: 16px;
            color: #92400E;
            font-size: 13px;
        }

        /* Delete modal styles (14 JAN 2026) */
        .delete-warning {
            background: #FEE2E2;
            border: 1px solid #DC2626;
            border-radius: 4px;
            padding: 12px;
            margin-bottom: 16px;
            color: #991B1B;
            font-size: 13px;
        }

        .delete-modal-header {
            background: #FEE2E2 !important;
            border-bottom-color: #DC2626 !important;
        }

        .delete-modal-header h3 {
            color: #991B1B !important;
        }

        .modal-btn-danger {
            background: #DC2626;
            border: none;
            color: white;
        }

        .modal-btn-danger:hover {
            background: #B91C1C;
        }

        .modal-btn-danger:disabled {
            background: #e9ecef;
            color: #626F86;
            cursor: not-allowed;
        }

        .cleanup-preview {
            background: #f8f9fa;
            border-radius: 4px;
            padding: 12px;
            margin-bottom: 16px;
        }

        .cleanup-preview h4 {
            margin: 0 0 10px 0;
            font-size: 13px;
            color: #053657;
        }

        .cleanup-item {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            font-size: 13px;
        }

        .cleanup-label {
            color: #626F86;
        }

        .cleanup-value {
            color: #053657;
            font-weight: 600;
        }

        .resubmit-options {
            margin-top: 12px;
        }

        .checkbox-label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: #626F86;
            cursor: pointer;
        }

        .checkbox-label input {
            width: 16px;
            height: 16px;
        }

        .modal-error {
            background: #FEE2E2;
            border: 1px solid #DC2626;
            border-radius: 4px;
            padding: 12px;
            color: #DC2626;
            font-size: 13px;
        }

        .modal-success {
            background: #D1FAE5;
            border: 1px solid #10B981;
            border-radius: 4px;
            padding: 12px;
            color: #065F46;
            font-size: 13px;
            text-align: center;
        }

        .modal-success p {
            margin: 8px 0 0 0;
            font-size: 12px;
        }

        .modal-footer {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            padding: 16px 20px;
            border-top: 1px solid #e9ecef;
            background: #f8f9fa;
        }

        .modal-btn {
            padding: 10px 20px;
            border-radius: 4px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .modal-btn-cancel {
            background: white;
            border: 1px solid #e9ecef;
            color: #626F86;
        }

        .modal-btn-cancel:hover {
            background: #f8f9fa;
            border-color: #626F86;
        }

        .modal-btn-confirm {
            background: #DC2626;
            border: none;
            color: white;
        }

        .modal-btn-confirm:hover {
            background: #B91C1C;
        }

        .modal-btn-confirm:disabled {
            background: #e9ecef;
            color: #626F86;
            cursor: not-allowed;
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

        /* ============================================
         * Docker Worker Progress Panel (F7.19)
         * 19 JAN 2026 - Real-time progress for single-stage Docker jobs
         * ============================================ */

        .docker-progress-panel {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 16px;
            margin-top: 12px;
        }

        .docker-progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .docker-progress-title {
            font-size: 12px;
            font-weight: 600;
            color: #475569;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .docker-progress-badge {
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 10px;
            background: #dbeafe;
            color: #1d4ed8;
            font-weight: 500;
        }

        /* Internal phases list */
        .docker-phases {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-bottom: 16px;
        }

        .docker-phase {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
            font-size: 13px;
        }

        .docker-phase.completed {
            border-color: #10b981;
            background: #ecfdf5;
        }

        .docker-phase.active {
            border-color: #f59e0b;
            background: #fffbeb;
            animation: phase-pulse 2s ease-in-out infinite;
        }

        .docker-phase.pending {
            border-color: #e2e8f0;
            background: #f8fafc;
            color: #94a3b8;
        }

        @keyframes phase-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.2); }
            50% { box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.1); }
        }

        .docker-phase-icon {
            font-size: 14px;
            width: 20px;
            text-align: center;
        }

        .docker-phase-name {
            flex: 1;
            font-weight: 500;
            color: #334155;
        }

        .docker-phase.pending .docker-phase-name {
            color: #94a3b8;
        }

        .docker-phase-duration {
            font-size: 11px;
            color: #64748b;
            font-family: 'Courier New', monospace;
        }

        /* Progress bar */
        .docker-progress-bar-container {
            background: #e2e8f0;
            border-radius: 8px;
            height: 10px;
            overflow: hidden;
            margin-bottom: 8px;
        }

        .docker-progress-bar-fill {
            height: 100%;
            border-radius: 8px;
            background: linear-gradient(90deg, #3b82f6 0%, #2563eb 100%);
            transition: width 0.5s ease-out;
        }

        .docker-progress-bar-fill.complete {
            background: linear-gradient(90deg, #10b981 0%, #059669 100%);
        }

        /* Status text */
        .docker-progress-status {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }

        .docker-progress-message {
            color: #475569;
            font-weight: 500;
        }

        .docker-progress-percent {
            color: #1d4ed8;
            font-weight: 700;
            font-size: 14px;
        }

        .docker-progress-percent.complete {
            color: #059669;
        }

        .docker-progress-updated {
            font-size: 11px;
            color: #94a3b8;
            margin-top: 8px;
            text-align: right;
        }

        /* Running indicator */
        .docker-running-indicator {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 11px;
            color: #f59e0b;
            font-weight: 500;
        }

        .docker-running-dot {
            width: 8px;
            height: 8px;
            background: #f59e0b;
            border-radius: 50%;
            animation: running-dot-pulse 1.5s ease-in-out infinite;
        }

        @keyframes running-dot-pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(0.8); }
        }

        /* ============================================
         * Job Details Panel (19 JAN 2026)
         * Expandable section for full job context
         * ============================================ */

        #job-details-container {
            margin-top: 16px;
        }

        .job-details-toggle {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 12px 16px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            color: #475569;
            transition: all 0.2s ease;
        }

        .job-details-toggle:hover {
            background: #f1f5f9;
            border-color: #cbd5e1;
        }

        .job-details-toggle .toggle-icon {
            transition: transform 0.2s ease;
        }

        .job-details-toggle.expanded .toggle-icon {
            transform: rotate(90deg);
        }

        .job-details-panel {
            display: none;
            margin-top: 12px;
            padding: 16px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
        }

        .job-details-panel.visible {
            display: block;
        }

        .job-detail-row {
            display: flex;
            align-items: flex-start;
            gap: 12px;
            padding: 8px 0;
            border-bottom: 1px solid #e2e8f0;
        }

        .job-detail-row:last-child {
            border-bottom: none;
        }

        .job-detail-label {
            flex: 0 0 120px;
            font-size: 12px;
            font-weight: 600;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .job-detail-value {
            flex: 1;
            font-size: 13px;
            color: #334155;
            word-break: break-all;
        }

        .job-id-full {
            font-family: 'Courier New', monospace;
            font-size: 12px;
            background: #e2e8f0;
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }

        .copy-btn {
            background: none;
            border: none;
            cursor: pointer;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
            color: #64748b;
            transition: all 0.2s;
        }

        .copy-btn:hover {
            background: #cbd5e1;
            color: #334155;
        }

        .copy-btn.copied {
            color: #059669;
        }

        .job-params-container {
            background: #1e293b;
            border-radius: 6px;
            padding: 12px;
            overflow-x: auto;
            max-height: 300px;
            overflow-y: auto;
        }

        .job-params-json {
            font-family: 'Courier New', monospace;
            font-size: 12px;
            color: #e2e8f0;
            white-space: pre-wrap;
            margin: 0;
        }

        .job-params-json .json-key {
            color: #7dd3fc;
        }

        .job-params-json .json-string {
            color: #86efac;
        }

        .job-params-json .json-number {
            color: #fcd34d;
        }

        .job-params-json .json-boolean {
            color: #f472b6;
        }

        .job-params-json .json-null {
            color: #94a3b8;
        }

        .job-timestamps {
            display: flex;
            gap: 24px;
            font-size: 12px;
            color: #64748b;
        }

        .job-timestamps span {
            display: flex;
            align-items: center;
            gap: 6px;
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
                    {{ number: 3, name: 'Catalog', taskType: 'vector_create_stac', description: 'Create STAC record' }}
                ]
            }},
            'process_raster': {{
                name: 'Raster ETL Pipeline',
                stages: [
                    {{ number: 1, name: 'Validate', taskType: 'raster_validate', description: 'Validate raster file' }},
                    {{ number: 2, name: 'Create COG', taskType: 'raster_create_cog', description: 'Convert to Cloud Optimized GeoTIFF' }},
                    {{ number: 3, name: 'Catalog', taskType: 'raster_extract_stac_metadata', description: 'Extract STAC metadata' }}
                ]
            }},
            'process_raster_v2': {{
                name: 'Raster ETL Pipeline v2',
                stages: [
                    {{ number: 1, name: 'Validate', taskType: 'raster_validate', description: 'Validate raster file' }},
                    {{ number: 2, name: 'Create COG', taskType: 'raster_create_cog', description: 'Convert to Cloud Optimized GeoTIFF' }},
                    {{ number: 3, name: 'Catalog', taskType: 'raster_extract_stac_metadata', description: 'Extract STAC metadata' }}
                ]
            }},
            'hello_world': {{
                name: 'Hello World Test',
                stages: [
                    {{ number: 1, name: 'Greeting', taskType: 'hello_world_greeting', description: 'Generate greetings' }},
                    {{ number: 2, name: 'Reply', taskType: 'hello_world_reply', description: 'Generate replies' }}
                ]
            }},
            // Docker Worker Jobs (F7.19 - 19 JAN 2026)
            // Single-stage with internal phases: Validate → COG → STAC
            'process_raster_docker': {{
                name: 'Docker Raster ETL',
                isDockerJob: true,
                stages: [
                    {{ number: 1, name: 'Process Raster', taskType: 'raster_process_complete', description: 'Validate → COG → STAC (Docker)' }}
                ],
                internalPhases: [
                    {{ number: 1, name: 'Validation', description: 'Validate CRS and raster type' }},
                    {{ number: 2, name: 'COG Creation', description: 'Convert to Cloud Optimized GeoTIFF' }},
                    {{ number: 3, name: 'STAC Registration', description: 'Register with STAC catalog' }}
                ]
            }},
            'process_large_raster_docker': {{
                name: 'Docker Large Raster ETL',
                isDockerJob: true,
                stages: [
                    {{ number: 1, name: 'Process Large Raster', taskType: 'raster_process_large_complete', description: 'Tile → Extract → COG → STAC (Docker)' }}
                ],
                internalPhases: [
                    {{ number: 1, name: 'Tiling Scheme', description: 'Generate tile grid' }},
                    {{ number: 2, name: 'Tile Extraction', description: 'Extract tiles from source' }},
                    {{ number: 3, name: 'COG Creation', description: 'Create COGs from tiles' }},
                    {{ number: 4, name: 'MosaicJSON', description: 'Generate mosaic definition' }},
                    {{ number: 5, name: 'STAC Registration', description: 'Register with STAC catalog' }}
                ]
            }},
            // Docker H3 Pyramid Job (F7.20 - 20 JAN 2026)
            // Single-stage with internal phases: Base → Cascade → Finalize
            'bootstrap_h3_docker': {{
                name: 'Docker H3 Pyramid',
                isDockerJob: true,
                stages: [
                    {{ number: 1, name: 'H3 Pyramid', taskType: 'h3_pyramid_complete', description: 'Base → Cascade → Finalize (Docker)' }}
                ],
                internalPhases: [
                    {{ number: 1, name: 'Base Generation', description: 'Generate res 2 base grid with land filter' }},
                    {{ number: 2, name: 'Cascade', description: 'Cascade to res 3-7 (batched with checkpoints)' }},
                    {{ number: 3, name: 'Finalization', description: 'Verify cell counts and update metadata' }}
                ]
            }}
        }};

        // Check if job is a Docker worker job (F7.19)
        function isDockerJob(jobType) {{
            const def = WORKFLOW_DEFINITIONS[jobType];
            return def?.isDockerJob === true || jobType?.includes('docker');
        }}

        // Format JSON with syntax highlighting (19 JAN 2026)
        function formatJsonWithHighlighting(obj, indent = 2) {{
            const json = JSON.stringify(obj, null, indent);
            return json
                .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
                .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
                .replace(/: (\\d+\\.?\\d*)/g, ': <span class="json-number">$1</span>')
                .replace(/: (true|false)/g, ': <span class="json-boolean">$1</span>')
                .replace(/: (null)/g, ': <span class="json-null">$1</span>');
        }}

        // Copy text to clipboard with feedback
        function copyToClipboard(text, buttonEl) {{
            navigator.clipboard.writeText(text).then(() => {{
                const originalText = buttonEl.textContent;
                buttonEl.textContent = '✓ Copied';
                buttonEl.classList.add('copied');
                setTimeout(() => {{
                    buttonEl.textContent = originalText;
                    buttonEl.classList.remove('copied');
                }}, 2000);
            }}).catch(err => {{
                console.error('Copy failed:', err);
            }});
        }}

        // Toggle job details panel visibility
        function toggleJobDetails() {{
            const toggle = document.getElementById('job-details-toggle');
            const panel = document.getElementById('job-details-panel');
            if (toggle && panel) {{
                toggle.classList.toggle('expanded');
                panel.classList.toggle('visible');
            }}
        }}

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

                // Update processing rate banner
                updateProcessingRateBanner(metrics, job);

                // Load events for swimlane (always visible)
                loadEvents();

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

            // Calculate job duration
            const jobDuration = calculateJobDuration(job);

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

            // Build duration display
            let durationItem = '';
            if (jobDuration) {{
                const runningIndicator = jobDuration.isRunning ? ' <span class="running-indicator">●</span>' : '';
                durationItem = `
                    <div class="summary-item duration-item">
                        <span class="summary-label">Duration</span>
                        <span class="summary-value duration-value">${{jobDuration.formatted}}${{runningIndicator}}</span>
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
                    ${{durationItem}}
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

            // Show processing rate if we have metrics
            window.currentJobSummary = {{ job, total, completed, failed, processing }};

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

            // Add approval panel placeholder for platform jobs
            if (job.asset_id) {{
                html += `<div id="approval-panel-container"></div>`;
            }}

            document.getElementById('job-summary-card').innerHTML = html;

            // Load approval state for platform jobs
            if (job.asset_id) {{
                loadApprovalState(job);
            }}

            // Add Job Details toggle and panel to separate container (below events)
            const jobParams = job.parameters || {{}};
            const hasParams = Object.keys(jobParams).length > 0;

            const detailsHtml = `
                <div id="job-details-toggle" class="job-details-toggle" onclick="toggleJobDetails()">
                    <span class="toggle-icon">▶</span>
                    <span>Job Details</span>
                    <span style="color: #94a3b8; font-weight: 400; margin-left: auto;">Full ID, Parameters, Timestamps</span>
                </div>
                <div id="job-details-panel" class="job-details-panel">
                    <div class="job-detail-row">
                        <span class="job-detail-label">Job ID</span>
                        <span class="job-detail-value">
                            <span class="job-id-full">
                                ${{job.job_id}}
                                <button class="copy-btn" onclick="event.stopPropagation(); copyToClipboard('${{job.job_id}}', this)">📋 Copy</button>
                            </span>
                        </span>
                    </div>
                    <div class="job-detail-row">
                        <span class="job-detail-label">Job Type</span>
                        <span class="job-detail-value">${{job.job_type}}</span>
                    </div>
                    <div class="job-detail-row">
                        <span class="job-detail-label">Timestamps</span>
                        <span class="job-detail-value">
                            <div class="job-timestamps">
                                <span>📅 Created: ${{job.created_at ? new Date(job.created_at).toLocaleString() : 'N/A'}}</span>
                                <span>🔄 Updated: ${{job.updated_at ? new Date(job.updated_at).toLocaleString() : 'N/A'}}</span>
                            </div>
                        </span>
                    </div>
                    ${{hasParams ? `
                    <div class="job-detail-row">
                        <span class="job-detail-label">Parameters</span>
                        <span class="job-detail-value">
                            <div class="job-params-container">
                                <pre class="job-params-json">${{formatJsonWithHighlighting(jobParams)}}</pre>
                            </div>
                        </span>
                    </div>
                    ` : ''}}
                </div>
            `;

            document.getElementById('job-details-container').innerHTML = detailsHtml;
        }}

        // Update the processing rate banner at the top
        function updateProcessingRateBanner(metrics, job) {{
            const banner = document.getElementById('processing-rate-banner');
            if (!banner) return;

            // Find the stage with the most tasks (usually stage 2)
            let bestMetrics = null;
            let totalPending = 0;
            Object.values(metrics).forEach(m => {{
                if (m && m.tasks_per_minute && (!bestMetrics || m.completed > bestMetrics.completed)) {{
                    bestMetrics = m;
                }}
                if (m && m.pending) totalPending += m.pending;
            }});

            if (!bestMetrics || !bestMetrics.tasks_per_minute) {{
                banner.classList.add('hidden');
                return;
            }}

            banner.classList.remove('hidden');

            // Tasks per minute
            document.getElementById('rate-tasks-per-min').textContent = bestMetrics.tasks_per_minute;

            // Average time
            document.getElementById('rate-avg-time').textContent = bestMetrics.avg_execution_time_formatted || '--';

            // ETA calculation
            if (totalPending > 0 && bestMetrics.avg_execution_time_ms) {{
                const remainingMs = totalPending * bestMetrics.avg_execution_time_ms;
                const remainingMin = Math.ceil(remainingMs / 60000);
                if (remainingMin > 60) {{
                    document.getElementById('rate-eta').textContent = (remainingMin / 60).toFixed(1) + 'h';
                }} else {{
                    document.getElementById('rate-eta').textContent = remainingMin + 'm';
                }}
            }} else if (job.status === 'completed') {{
                document.getElementById('rate-eta').textContent = 'Done';
            }} else {{
                document.getElementById('rate-eta').textContent = '--';
            }}
        }}

        // Helper: Get peak memory for a stage from tasks
        function getStagePeakMemoryFromTasks(tasks, stageNumber) {{
            const stageTasks = tasks.filter(t => t.stage === stageNumber);
            let maxPeak = 0;

            stageTasks.forEach(task => {{
                const peak = getPeakMemory(task);
                if (peak && peak.rss_mb > maxPeak) {{
                    maxPeak = peak.rss_mb;
                }}
            }});

            if (maxPeak === 0) return null;

            // Format the memory value
            if (maxPeak >= 1024) {{
                return (maxPeak / 1024).toFixed(1) + ' GB';
            }}
            return Math.round(maxPeak) + ' MB';
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
                    // Show expected count or "?" for stages with no tasks yet
                    if (stage.expectCountFromStage1 && expectedStage2Count) {{
                        html += `<span class="count-badge count-pending">0 / ${{expectedStage2Count}}</span>`;
                    }} else {{
                        html += `<span class="count-badge count-queued">? tasks</span>`;
                    }}
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

                // Always show progress bar - with placeholder if no tasks yet
                // Determine expected total for this stage
                let expectedTotal = totalTasks;
                if (stage.expectCountFromStage1 && expectedStage2Count) {{
                    expectedTotal = expectedStage2Count;
                }}

                if (expectedTotal > 0 || totalTasks > 0) {{
                    html += renderProgressBar(stageCounts, expectedTotal || totalTasks);
                }} else {{
                    // Show placeholder bar for stages with no tasks yet
                    html += `
                        <div class="stage-progress">
                            <div class="progress-bar-container">
                                <div class="progress-bar-fill">
                                    <div class="progress-segment pending" style="width: 100%"></div>
                                </div>
                            </div>
                            <div class="progress-text">
                                <span class="progress-percent">Waiting</span>
                                <span class="progress-count">? tasks</span>
                            </div>
                        </div>
                    `;
                }}

                // Add stage metrics if available
                const stageMetrics = metrics[stage.number];

                // Get peak memory for this stage from tasks
                const stagePeakMemory = getStagePeakMemoryFromTasks(tasks, stage.number);

                // Get stage duration from tasks
                const stageTasksForDuration = tasks.filter(t => t.stage === stage.number);
                const stageDuration = calculateStageDuration(stageTasksForDuration);

                if ((stageMetrics && stageMetrics.avg_execution_time_ms) || stagePeakMemory || stageDuration) {{
                    html += `<div class="stage-metrics">`;

                    // Show wall-clock duration first
                    if (stageDuration) {{
                        const runningDot = stageDuration.isRunning ? ' <span class="running-dot">●</span>' : '';
                        html += `
                            <div class="metric-row">
                                <span class="metric-label">Duration:</span>
                                <span class="metric-value duration">${{stageDuration.formatted}}${{runningDot}}</span>
                            </div>
                        `;
                    }}

                    if (stageMetrics && stageMetrics.avg_execution_time_ms) {{
                        html += `
                            <div class="metric-row">
                                <span class="metric-label">Avg:</span>
                                <span class="metric-value">${{stageMetrics.avg_execution_time_formatted}}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">Rate:</span>
                                <span class="metric-value rate">${{stageMetrics.tasks_per_minute || '-'}} /min</span>
                            </div>
                        `;
                    }}

                    if (stagePeakMemory) {{
                        html += `
                            <div class="metric-row">
                                <span class="metric-label">Peak:</span>
                                <span class="metric-value memory">${{stagePeakMemory}}</span>
                            </div>
                        `;
                    }}

                    html += `</div>`;
                }}

                // F7.19: Add Docker progress panel for Docker worker jobs
                if (isDockerJob(job.job_type)) {{
                    // Find the task for this stage (Docker jobs have 1 task per stage)
                    const dockerTask = tasks.find(t => t.stage === stage.number);
                    if (dockerTask) {{
                        html += renderDockerProgressPanel(dockerTask, job.job_type);
                    }}
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
                }} else {{
                    // Show placeholder bar
                    html += `
                        <div class="stage-progress">
                            <div class="progress-bar-container">
                                <div class="progress-bar-fill">
                                    <div class="progress-segment pending" style="width: 100%"></div>
                                </div>
                            </div>
                            <div class="progress-text">
                                <span class="progress-percent">Waiting</span>
                                <span class="progress-count">? tasks</span>
                            </div>
                        </div>
                    `;
                }}

                // Add peak memory and duration for this stage
                const stagePeakMemory = getStagePeakMemoryFromTasks(tasks, parseInt(stageNum));
                const stageTasksForDuration = tasks.filter(t => t.stage === parseInt(stageNum));
                const stageDuration = calculateStageDuration(stageTasksForDuration);

                if (stagePeakMemory || stageDuration) {{
                    html += `<div class="stage-metrics">`;

                    if (stageDuration) {{
                        const runningDot = stageDuration.isRunning ? ' <span class="running-dot">●</span>' : '';
                        html += `
                            <div class="metric-row">
                                <span class="metric-label">Duration:</span>
                                <span class="metric-value duration">${{stageDuration.formatted}}${{runningDot}}</span>
                            </div>
                        `;
                    }}

                    if (stagePeakMemory) {{
                        html += `
                            <div class="metric-row">
                                <span class="metric-label">Peak:</span>
                                <span class="metric-value memory">${{stagePeakMemory}}</span>
                            </div>
                        `;
                    }}

                    html += `</div>`;
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

        // Render Docker progress panel (F7.19 - 19 JAN 2026)
        // Shows internal phases, progress bar, and status message for Docker worker tasks
        function renderDockerProgressPanel(task, jobType) {{
            if (!task) return '';

            const workflowDef = WORKFLOW_DEFINITIONS[jobType];
            const internalPhases = workflowDef?.internalPhases || [
                {{ number: 1, name: 'Validation' }},
                {{ number: 2, name: 'COG Creation' }},
                {{ number: 3, name: 'STAC Registration' }}
            ];

            // Get checkpoint phase (0 = not started, 1-3 = completed phases)
            const checkpointPhase = task.checkpoint_phase || 0;

            // Get progress from metadata
            const progress = task.metadata?.progress || {{}};
            const progressPercent = progress.percent || 0;
            const progressMessage = progress.message || '';
            const progressUpdated = progress.updated_at;

            // Determine current active phase based on checkpoint
            // checkpoint_phase = N means phase N is complete, so N+1 is active (if task is processing)
            const isProcessing = task.status === 'processing';
            const isComplete = task.status === 'completed';
            const activePhase = isProcessing ? checkpointPhase + 1 : (isComplete ? internalPhases.length : 0);

            // Format time ago for last update
            function formatTimeAgo(isoString) {{
                if (!isoString) return '';
                const date = new Date(isoString);
                const now = new Date();
                const diffMs = now - date;
                const diffSec = Math.floor(diffMs / 1000);
                if (diffSec < 60) return `${{diffSec}}s ago`;
                const diffMin = Math.floor(diffSec / 60);
                if (diffMin < 60) return `${{diffMin}}m ago`;
                return `${{Math.floor(diffMin / 60)}}h ago`;
            }}

            // Build phases HTML
            let phasesHtml = '';
            internalPhases.forEach(phase => {{
                let phaseClass = 'pending';
                let icon = '⏳';

                if (phase.number <= checkpointPhase) {{
                    phaseClass = 'completed';
                    icon = '✅';
                }} else if (phase.number === activePhase && isProcessing) {{
                    phaseClass = 'active';
                    icon = '🔄';
                }}

                phasesHtml += `
                    <div class="docker-phase ${{phaseClass}}">
                        <span class="docker-phase-icon">${{icon}}</span>
                        <span class="docker-phase-name">Phase ${{phase.number}}: ${{phase.name}}</span>
                    </div>
                `;
            }});

            // Progress bar fill class
            const barClass = isComplete ? 'complete' : '';
            const percentClass = isComplete ? 'complete' : '';

            // Running indicator for active tasks
            const runningIndicator = isProcessing ? `
                <span class="docker-running-indicator">
                    <span class="docker-running-dot"></span>
                    Processing
                </span>
            ` : '';

            // Last updated text
            const updatedText = progressUpdated ? `Last update: ${{formatTimeAgo(progressUpdated)}}` : '';

            return `
                <div class="docker-progress-panel">
                    <div class="docker-progress-header">
                        <span class="docker-progress-title">🐳 Docker Worker Progress</span>
                        ${{runningIndicator}}
                    </div>
                    <div class="docker-phases">
                        ${{phasesHtml}}
                    </div>
                    <div class="docker-progress-bar-container">
                        <div class="docker-progress-bar-fill ${{barClass}}" style="width: ${{progressPercent}}%"></div>
                    </div>
                    <div class="docker-progress-status">
                        <span class="docker-progress-message">${{progressMessage || (isComplete ? 'Complete' : 'Waiting for progress update...')}}</span>
                        <span class="docker-progress-percent ${{percentClass}}">${{progressPercent.toFixed(0)}}%</span>
                    </div>
                    ${{updatedText ? `<div class="docker-progress-updated">${{updatedText}}</div>` : ''}}
                </div>
            `;
        }}

        // Render task details grouped by stage - SUMMARY VIEW
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

            let html = `<div class="tasks-header">Stage Summary (${{tasks.length}} total tasks)</div>`;

            const stages = Object.keys(tasksByStage).sort((a, b) => parseInt(a) - parseInt(b));
            stages.forEach(stage => {{
                const stageTasks = tasksByStage[stage];
                const pending = stageTasks.filter(t => t.status === 'pending').length;
                const queued = stageTasks.filter(t => t.status === 'queued').length;
                const processing = stageTasks.filter(t => t.status === 'processing').length;
                const completed = stageTasks.filter(t => t.status === 'completed').length;
                const failed = stageTasks.filter(t => t.status === 'failed').length;

                // Get task type (should be same for all tasks in stage)
                const taskType = stageTasks[0]?.task_type || 'unknown';

                // Calculate execution time stats for completed tasks
                const completedTasks = stageTasks.filter(t => t.status === 'completed' && t.execution_time_ms);
                let execTimeStats = null;
                if (completedTasks.length > 0) {{
                    const times = completedTasks.map(t => t.execution_time_ms);
                    const avgMs = times.reduce((a, b) => a + b, 0) / times.length;
                    const minMs = Math.min(...times);
                    const maxMs = Math.max(...times);
                    execTimeStats = {{
                        avg: formatDuration(avgMs),
                        min: formatDuration(minMs),
                        max: formatDuration(maxMs),
                        total: formatDuration(times.reduce((a, b) => a + b, 0))
                    }};
                }}

                // Collect errors from failed tasks
                const failedTasks = stageTasks.filter(t => t.status === 'failed' && t.error_details);

                // Get memory stats
                const memoryStats = getStageMemoryStats(stageTasks);

                // Calculate stage wall-clock duration
                const stageDuration = calculateStageDuration(stageTasks);

                // Build duration badge for header
                const durationBadge = stageDuration ? `
                    <span class="stage-duration-badge${{stageDuration.isRunning ? ' running' : ''}}">
                        ⏱ ${{stageDuration.formatted}}${{stageDuration.isRunning ? ' <span class="running-dot">●</span>' : ''}}
                    </span>
                ` : '';

                html += `
                    <div class="stage-summary-card" id="stage-group-${{stage}}">
                        <div class="stage-summary-header">
                            <div class="stage-summary-title">
                                <span class="stage-number-badge">${{stage}}</span>
                                <div>
                                    <h4>Stage ${{stage}}</h4>
                                    <span class="task-type-label">${{taskType}}</span>
                                </div>
                                ${{durationBadge}}
                            </div>
                            <div class="stage-status-counts">
                                ${{pending > 0 ? `<span class="count-badge count-pending">P: ${{pending}}</span>` : ''}}
                                ${{queued > 0 ? `<span class="count-badge count-queued">Q: ${{queued}}</span>` : ''}}
                                ${{processing > 0 ? `<span class="count-badge count-processing">R: ${{processing}}</span>` : ''}}
                                ${{completed > 0 ? `<span class="count-badge count-completed">C: ${{completed}}</span>` : ''}}
                                ${{failed > 0 ? `<span class="count-badge count-failed">F: ${{failed}}</span>` : ''}}
                            </div>
                        </div>

                        <div class="stage-summary-body">
                            <div class="summary-stats-grid">
                                <div class="summary-stat">
                                    <span class="stat-value">${{stageTasks.length}}</span>
                                    <span class="stat-label">Total Tasks</span>
                                </div>
                                <div class="summary-stat">
                                    <span class="stat-value" style="color: #10B981;">${{completed}}</span>
                                    <span class="stat-label">Completed</span>
                                </div>
                                <div class="summary-stat">
                                    <span class="stat-value" style="color: #F59E0B;">${{pending + queued + processing}}</span>
                                    <span class="stat-label">In Progress</span>
                                </div>
                                <div class="summary-stat">
                                    <span class="stat-value" style="color: #DC2626;">${{failed}}</span>
                                    <span class="stat-label">Failed</span>
                                </div>
                            </div>

                            ${{execTimeStats ? `
                                <div class="exec-time-summary">
                                    <div class="exec-time-header">Execution Times</div>
                                    <div class="exec-time-grid">
                                        <div class="exec-time-stat">
                                            <span class="stat-label">Avg</span>
                                            <span class="stat-value">${{execTimeStats.avg}}</span>
                                        </div>
                                        <div class="exec-time-stat">
                                            <span class="stat-label">Min</span>
                                            <span class="stat-value">${{execTimeStats.min}}</span>
                                        </div>
                                        <div class="exec-time-stat">
                                            <span class="stat-label">Max</span>
                                            <span class="stat-value">${{execTimeStats.max}}</span>
                                        </div>
                                        <div class="exec-time-stat">
                                            <span class="stat-label">Total</span>
                                            <span class="stat-value">${{execTimeStats.total}}</span>
                                        </div>
                                    </div>
                                </div>
                            ` : ''}}

                            ${{memoryStats ? `
                                <div class="memory-summary-section">
                                    <div class="memory-summary-header">Memory Usage</div>
                                    <div class="memory-summary-grid">
                                        <div class="memory-stat">
                                            <span class="stat-label">Peak RSS</span>
                                            <span class="stat-value">${{memoryStats.peakFormatted}}</span>
                                        </div>
                                        <div class="memory-stat">
                                            <span class="stat-label">Avg Peak</span>
                                            <span class="stat-value">${{memoryStats.avgFormatted}}</span>
                                        </div>
                                        <div class="memory-stat">
                                            <span class="stat-label">Tasks Tracked</span>
                                            <span class="stat-value">${{memoryStats.taskCount}}</span>
                                        </div>
                                    </div>
                                </div>
                            ` : ''}}

                            ${{failedTasks.length > 0 ? `
                                <div class="errors-summary">
                                    <div class="errors-header">Failed Tasks (${{failedTasks.length}})</div>
                                    <div class="errors-list">
                                        ${{failedTasks.slice(0, 3).map(t => `
                                            <div class="error-item">
                                                <span class="error-task-id">${{t.task_id.substring(0, 8)}}...</span>
                                                <span class="error-message">${{(t.error_details || 'Unknown error').substring(0, 100)}}${{(t.error_details || '').length > 100 ? '...' : ''}}</span>
                                            </div>
                                        `).join('')}}
                                        ${{failedTasks.length > 3 ? `<div class="error-more">+ ${{failedTasks.length - 3}} more errors</div>` : ''}}
                                    </div>
                                </div>
                            ` : ''}}
                        </div>
                    </div>
                `;
            }});

            document.getElementById('tasks-container').innerHTML = html;
        }}

        // Format duration from milliseconds
        function formatDuration(ms) {{
            // Handle invalid/negative values
            if (ms === null || ms === undefined || isNaN(ms) || ms < 0) return '--';

            if (ms < 1000) return ms.toFixed(0) + 'ms';
            if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
            if (ms < 3600000) return (ms / 60000).toFixed(1) + 'm';
            return (ms / 3600000).toFixed(1) + 'h';
        }}

        // Format duration for display (longer form for job totals)
        function formatDurationLong(ms) {{
            // Handle invalid/negative values
            if (ms === null || ms === undefined || isNaN(ms) || ms < 0) return '--';

            if (ms < 1000) return ms.toFixed(0) + ' ms';
            if (ms < 60000) return (ms / 1000).toFixed(1) + ' sec';
            if (ms < 3600000) {{
                const mins = Math.floor(ms / 60000);
                const secs = Math.round((ms % 60000) / 1000);
                return mins + 'm ' + secs + 's';
            }}
            const hrs = Math.floor(ms / 3600000);
            const mins = Math.round((ms % 3600000) / 60000);
            return hrs + 'h ' + mins + 'm';
        }}

        // Calculate job total duration
        function calculateJobDuration(job) {{
            if (!job.created_at) return null;

            const startTime = new Date(job.created_at);
            // Validate start time parsed correctly
            if (isNaN(startTime.getTime())) return null;

            let endTime;

            if (job.status === 'completed' || job.status === 'failed') {{
                endTime = job.updated_at ? new Date(job.updated_at) : new Date();
            }} else {{
                endTime = new Date(); // Still running
            }}

            // Validate end time
            if (isNaN(endTime.getTime())) endTime = new Date();

            const durationMs = endTime - startTime;

            // Guard against negative durations (clock skew, timezone issues)
            if (durationMs < 0) return null;

            return {{
                ms: durationMs,
                formatted: formatDurationLong(durationMs),
                isRunning: job.status !== 'completed' && job.status !== 'failed'
            }};
        }}

        // Calculate stage wall-clock duration from tasks
        function calculateStageDuration(stageTasks) {{
            if (!stageTasks || stageTasks.length === 0) return null;

            // Find earliest start and latest end
            let earliestStart = null;
            let latestEnd = null;

            stageTasks.forEach(task => {{
                // Use execution_started_at if available, otherwise created_at
                const startStr = task.execution_started_at || task.created_at;
                const endStr = task.updated_at;

                if (startStr) {{
                    const start = new Date(startStr);
                    // Validate parsed date
                    if (!isNaN(start.getTime())) {{
                        if (!earliestStart || start < earliestStart) {{
                            earliestStart = start;
                        }}
                    }}
                }}

                if (endStr && (task.status === 'completed' || task.status === 'failed')) {{
                    const end = new Date(endStr);
                    // Validate parsed date
                    if (!isNaN(end.getTime())) {{
                        if (!latestEnd || end > latestEnd) {{
                            latestEnd = end;
                        }}
                    }}
                }}
            }});

            if (!earliestStart) return null;

            // If stage is still running, use current time
            const hasRunningTasks = stageTasks.some(t =>
                t.status === 'processing' || t.status === 'queued' || t.status === 'pending'
            );

            if (!latestEnd || hasRunningTasks) {{
                latestEnd = new Date();
            }}

            const durationMs = latestEnd - earliestStart;

            // Guard against negative durations (clock skew, timezone issues)
            if (durationMs < 0) return null;

            return {{
                ms: durationMs,
                formatted: formatDurationLong(durationMs),
                startTime: earliestStart,
                endTime: latestEnd,
                isRunning: hasRunningTasks
            }};
        }}

        // Get memory stats for a stage
        function getStageMemoryStats(tasks) {{
            const peakMemories = [];
            tasks.forEach(task => {{
                const peak = getPeakMemory(task);
                if (peak) {{
                    peakMemories.push(peak.rss_mb);
                }}
            }});

            if (peakMemories.length === 0) return null;

            const maxPeak = Math.max(...peakMemories);
            const avgPeak = peakMemories.reduce((a, b) => a + b, 0) / peakMemories.length;

            return {{
                peak: maxPeak,
                avg: avgPeak,
                taskCount: peakMemories.length,
                peakFormatted: maxPeak >= 1024 ? (maxPeak / 1024).toFixed(1) + ' GB' : maxPeak.toFixed(0) + ' MB',
                avgFormatted: avgPeak >= 1024 ? (avgPeak / 1024).toFixed(1) + ' GB' : avgPeak.toFixed(0) + ' MB'
            }};
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
        // EVENT TIMELINE SECTION (03 FEB 2026)
        // ============================================================

        let eventsData = null;

        // Load events from API
        async function loadEvents() {{
            const loading = document.getElementById('events-loading');
            const empty = document.getElementById('events-empty');
            const swimlane = document.getElementById('swimlane-container');
            const countBadge = document.getElementById('events-count');

            // Show loading
            loading.classList.remove('hidden');
            empty.classList.add('hidden');
            swimlane.classList.add('hidden');

            try {{
                const response = await fetchJSON(
                    `${{API_BASE_URL}}/api/jobs/${{JOB_ID}}/events`
                );

                loading.classList.add('hidden');

                const events = response.events || [];
                eventsData = events;
                countBadge.textContent = `${{events.length}} events`;

                if (events.length === 0) {{
                    empty.classList.remove('hidden');
                    return;
                }}

                // Render swimlane
                renderEventsSwimlane(events);
                swimlane.classList.remove('hidden');

            }} catch (err) {{
                loading.classList.add('hidden');
                empty.classList.remove('hidden');
                countBadge.textContent = 'error';
                console.error('Failed to load events:', err);
            }}
        }}

        // Render events as horizontal swimlane
        function renderEventsSwimlane(events) {{
            const container = document.getElementById('swimlane-container');

            // Group events by stage
            const stageEvents = {{}};
            const jobEvents = [];

            // Process events (they come in reverse chronological order)
            const sortedEvents = [...events].reverse();

            for (const event of sortedEvents) {{
                if (event.stage) {{
                    if (!stageEvents[event.stage]) {{
                        stageEvents[event.stage] = [];
                    }}
                    stageEvents[event.stage].push(event);
                }} else {{
                    jobEvents.push(event);
                }}
            }}

            // Get stage numbers
            const stageNums = Object.keys(stageEvents).map(Number).sort((a, b) => a - b);

            // Build HTML
            let html = '<div class="swimlane-stages">';

            // Job-level events first (if any)
            if (jobEvents.length > 0) {{
                html += `
                    <div class="swimlane-stage">
                        <div class="swimlane-stage-header">
                            <div class="swimlane-stage-num completed">J</div>
                            <span class="swimlane-stage-name">Job Events</span>
                        </div>
                        <div class="swimlane-events">
                            ${{renderEventChips(jobEvents.filter(e => !e.event_type.startsWith('stage_')))}}
                        </div>
                    </div>
                `;
            }}

            // Stage events
            for (const stageNum of stageNums) {{
                const stgEvents = stageEvents[stageNum];

                // Determine stage status from events
                const hasCompleted = stgEvents.some(e => e.event_type === 'stage_completed');
                const hasFailed = stgEvents.some(e => e.event_type.includes('failed'));
                const hasStarted = stgEvents.some(e => e.event_type === 'stage_started' || e.event_type === 'task_started');

                let statusClass = 'pending';
                if (hasCompleted) statusClass = 'completed';
                else if (hasFailed) statusClass = 'failed';
                else if (hasStarted) statusClass = 'processing';

                // Get stage name from stage_started event
                const startEvent = stgEvents.find(e => e.event_type === 'stage_started');
                const stageName = startEvent?.event_data?.stage_name || `Stage ${{stageNum}}`;

                // Calculate duration if we have start and end
                const stageStart = stgEvents.find(e => e.event_type === 'stage_started');
                const stageEnd = stgEvents.find(e => e.event_type === 'stage_completed' || e.event_type.includes('failed'));
                let duration = '';
                if (stageStart && stageEnd) {{
                    const ms = new Date(stageEnd.timestamp) - new Date(stageStart.timestamp);
                    duration = ms < 1000 ? `${{ms}}ms` : `${{(ms / 1000).toFixed(1)}}s`;
                }}

                html += `
                    <div class="swimlane-stage">
                        <div class="swimlane-stage-header">
                            <div class="swimlane-stage-num ${{statusClass}}">
                                ${{statusClass === 'completed' ? '✓' : stageNum}}
                            </div>
                            <span class="swimlane-stage-name">${{formatStageName(stageName)}}</span>
                            ${{duration ? `<span class="swimlane-stage-time">${{duration}}</span>` : ''}}
                        </div>
                        <div class="swimlane-events">
                            ${{renderEventChips(stgEvents)}}
                        </div>
                    </div>
                `;
            }}

            html += '</div>';

            // Legend
            html += `
                <div class="swimlane-legend">
                    <div class="legend-item"><span class="legend-dot checkpoint"></span> Checkpoint</div>
                    <div class="legend-item"><span class="legend-dot task"></span> Task</div>
                    <div class="legend-item"><span class="legend-dot success"></span> Success</div>
                    <div class="legend-item"><span class="legend-dot failed"></span> Failed</div>
                </div>
            `;

            container.innerHTML = html;
        }}

        // Render event chips with arrows
        function renderEventChips(events) {{
            if (!events || events.length === 0) return '<span style="color:#626F86;font-size:11px;">No events</span>';

            return events.map((event, idx) => {{
                const icon = getEventIcon(event.event_type);
                const label = event.checkpoint_name || event.event_type_display || event.event_type;
                const shortLabel = label.length > 30 ? label.substring(0, 28) + '...' : label;
                const arrow = idx < events.length - 1 ? '<span class="event-arrow">→</span>' : '';

                // Add duration if available
                const duration = event.duration_ms ? ` (${{event.duration_ms}}ms)` : '';

                return `
                    <span class="event-chip ${{event.event_type}}" title="${{label}}${{duration}}">
                        <span class="event-chip-icon">${{icon}}</span>
                        ${{shortLabel}}
                    </span>
                    ${{arrow}}
                `;
            }}).join('');
        }}

        // Get icon for event type
        function getEventIcon(eventType) {{
            const icons = {{
                'job_created': '🆕',
                'job_started': '▶️',
                'job_completed': '✅',
                'job_failed': '❌',
                'stage_started': '📂',
                'stage_completed': '✓',
                'task_queued': '📤',
                'task_started': '⚡',
                'task_completed': '✓',
                'task_failed': '✗',
                'checkpoint': '📍',
                'callback_started': '📞',
                'callback_success': '📞',
                'callback_failed': '📞',
                'approval_requested': '📋',
                'approval_granted': '✅',
                'approval_rejected': '❌',
                'approval_revoked': '🚫'
            }};
            return icons[eventType] || '•';
        }}

        // Format stage name
        function formatStageName(name) {{
            return name.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
        }}

        // ============================================================
        // LOGS SECTION (12 JAN 2026)
        // ============================================================

        let logsExpanded = false;

        // Toggle logs section visibility
        function toggleLogsSection() {{
            logsExpanded = !logsExpanded;
            const content = document.getElementById('logs-content');
            const icon = document.getElementById('logs-toggle-icon');

            if (logsExpanded) {{
                content.classList.remove('hidden');
                icon.classList.add('expanded');
                // Load logs on first expand
                if (!content.dataset.loaded) {{
                    loadLogs();
                    content.dataset.loaded = 'true';
                }}
            }} else {{
                content.classList.add('hidden');
                icon.classList.remove('expanded');
            }}
        }}

        // Load logs from API
        async function loadLogs() {{
            const level = document.getElementById('logsLevelFilter').value;
            const loading = document.getElementById('logs-loading');
            const empty = document.getElementById('logs-empty');
            const error = document.getElementById('logs-error');
            const table = document.getElementById('logs-table');
            const countBadge = document.getElementById('logs-count');

            // Show loading
            loading.classList.remove('hidden');
            empty.classList.add('hidden');
            error.classList.add('hidden');
            table.classList.add('hidden');

            try {{
                const response = await fetchJSON(
                    `${{API_BASE_URL}}/api/jobs/${{JOB_ID}}/logs?level=${{level}}&limit=200&timespan=PT48H`
                );

                loading.classList.add('hidden');

                if (!response.success) {{
                    throw new Error(response.error || 'Failed to load logs');
                }}

                const logs = response.logs || [];
                countBadge.textContent = `${{logs.length}} logs`;

                if (logs.length === 0) {{
                    empty.classList.remove('hidden');
                    return;
                }}

                // Render logs table
                renderLogsTable(logs);
                table.classList.remove('hidden');

            }} catch (err) {{
                loading.classList.add('hidden');
                error.classList.remove('hidden');
                document.getElementById('logs-error-message').textContent = err.message;
                countBadge.textContent = 'error';
            }}
        }}

        // Render logs into table
        function renderLogsTable(logs) {{
            const tbody = document.getElementById('logs-table-body');
            tbody.innerHTML = '';

            for (const log of logs) {{
                const row = document.createElement('tr');

                // Format timestamp
                const ts = new Date(log.timestamp);
                const timeStr = ts.toLocaleString('en-US', {{
                    month: 'short',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false
                }});

                // Level class
                const levelClass = `log-level-${{log.level.toLowerCase()}}`;

                // Stage display
                const stageHtml = log.stage ? `<span class="log-stage">S${{log.stage}}</span>` : '-';

                // Component display
                const componentDisplay = log.component || log.component_type || '-';

                row.innerHTML = `
                    <td><span class="log-timestamp">${{timeStr}}</span></td>
                    <td><span class="log-level ${{levelClass}}">${{log.level}}</span></td>
                    <td><span class="log-component">${{componentDisplay}}</span></td>
                    <td>${{stageHtml}}</td>
                    <td><span class="log-message">${{escapeHtml(log.message)}}</span></td>
                `;

                tbody.appendChild(row);
            }}
        }}

        // Escape HTML to prevent XSS
        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        // Update logs when level filter changes
        document.addEventListener('DOMContentLoaded', () => {{
            document.getElementById('logsLevelFilter').addEventListener('change', () => {{
                if (logsExpanded) {{
                    loadLogs();
                }}
            }});
        }});

        // ============================================================
        // RESUBMIT MODAL (12 JAN 2026)
        // ============================================================

        let resubmitCleanupPlan = null;

        // Show resubmit modal with dry-run preview
        async function showResubmitModal() {{
            const modal = document.getElementById('resubmit-modal');
            const loading = document.getElementById('resubmit-loading');
            const preview = document.getElementById('resubmit-preview');
            const error = document.getElementById('resubmit-error');
            const success = document.getElementById('resubmit-success');
            const confirmBtn = document.getElementById('confirm-resubmit-btn');

            // Reset state
            loading.classList.remove('hidden');
            preview.classList.add('hidden');
            error.classList.add('hidden');
            success.classList.add('hidden');
            confirmBtn.disabled = true;

            // Show modal
            modal.classList.remove('hidden');

            try {{
                // Fetch dry-run preview
                const response = await fetch(`${{API_BASE_URL}}/api/jobs/${{JOB_ID}}/resubmit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ dry_run: true }})
                }});

                const data = await response.json();

                loading.classList.add('hidden');

                if (!data.success && !data.dry_run) {{
                    throw new Error(data.error || 'Failed to analyze job');
                }}

                // Store cleanup plan for later
                resubmitCleanupPlan = data.cleanup_plan || {{}};

                // Update preview
                document.getElementById('preview-tasks').textContent = resubmitCleanupPlan.tasks_to_delete || 0;
                document.getElementById('preview-stac').textContent = (resubmitCleanupPlan.stac_items_to_delete || []).length;
                document.getElementById('preview-tables').textContent = (resubmitCleanupPlan.tables_to_drop || []).length;

                // Show preview
                preview.classList.remove('hidden');
                confirmBtn.disabled = false;

            }} catch (err) {{
                loading.classList.add('hidden');
                error.classList.remove('hidden');
                document.getElementById('resubmit-error-message').textContent = err.message;
            }}
        }}

        // Hide resubmit modal
        function hideResubmitModal() {{
            document.getElementById('resubmit-modal').classList.add('hidden');
            resubmitCleanupPlan = null;
        }}

        // Execute resubmit
        async function executeResubmit() {{
            const preview = document.getElementById('resubmit-preview');
            const error = document.getElementById('resubmit-error');
            const success = document.getElementById('resubmit-success');
            const confirmBtn = document.getElementById('confirm-resubmit-btn');
            const deleteBlobs = document.getElementById('delete-blobs-checkbox').checked;

            // Disable button and hide preview
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Resubmitting...';
            error.classList.add('hidden');

            try {{
                const response = await fetch(`${{API_BASE_URL}}/api/jobs/${{JOB_ID}}/resubmit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        dry_run: false,
                        delete_blobs: deleteBlobs
                    }})
                }});

                const data = await response.json();

                if (!data.success) {{
                    throw new Error(data.error || 'Resubmit failed');
                }}

                // Show success
                preview.classList.add('hidden');
                success.classList.remove('hidden');

                // Redirect to new job after delay
                const newJobId = data.new_job_id || data.original_job_id;
                setTimeout(() => {{
                    window.location.href = `/api/interface/tasks?job_id=${{newJobId}}`;
                }}, 1500);

            }} catch (err) {{
                error.classList.remove('hidden');
                document.getElementById('resubmit-error-message').textContent = err.message;
                confirmBtn.disabled = false;
                confirmBtn.textContent = 'Resubmit Job';
            }}
        }}

        // ============================================================
        // DELETE MODAL (14 JAN 2026)
        // ============================================================

        let deleteCleanupPlan = null;

        // Show delete modal with dry-run preview
        async function showDeleteModal() {{
            const modal = document.getElementById('delete-modal');
            const loading = document.getElementById('delete-loading');
            const preview = document.getElementById('delete-preview');
            const error = document.getElementById('delete-error');
            const success = document.getElementById('delete-success');
            const confirmBtn = document.getElementById('confirm-delete-btn');

            // Reset state
            loading.classList.remove('hidden');
            preview.classList.add('hidden');
            error.classList.add('hidden');
            success.classList.add('hidden');
            confirmBtn.disabled = true;

            // Show modal
            modal.classList.remove('hidden');

            try {{
                // Fetch dry-run preview using resubmit endpoint (same cleanup plan)
                const response = await fetch(`${{API_BASE_URL}}/api/jobs/${{JOB_ID}}/resubmit`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ dry_run: true }})
                }});

                const data = await response.json();

                loading.classList.add('hidden');

                if (!data.success && !data.dry_run) {{
                    throw new Error(data.error || 'Failed to analyze job');
                }}

                // Store cleanup plan for later
                deleteCleanupPlan = data.cleanup_plan || {{}};

                // Update preview
                document.getElementById('delete-preview-tasks').textContent = deleteCleanupPlan.tasks_to_delete || 0;
                document.getElementById('delete-preview-stac').textContent = (deleteCleanupPlan.stac_items_to_delete || []).length;
                document.getElementById('delete-preview-tables').textContent = (deleteCleanupPlan.tables_to_drop || []).length;

                // Show preview
                preview.classList.remove('hidden');
                confirmBtn.disabled = false;

            }} catch (err) {{
                loading.classList.add('hidden');
                error.classList.remove('hidden');
                document.getElementById('delete-error-message').textContent = err.message;
            }}
        }}

        // Hide delete modal
        function hideDeleteModal() {{
            document.getElementById('delete-modal').classList.add('hidden');
            deleteCleanupPlan = null;
        }}

        // Execute delete
        async function executeDelete() {{
            const preview = document.getElementById('delete-preview');
            const error = document.getElementById('delete-error');
            const success = document.getElementById('delete-success');
            const confirmBtn = document.getElementById('confirm-delete-btn');
            const deleteBlobs = document.getElementById('delete-blobs-checkbox-del').checked;

            // Disable button
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Deleting...';
            error.classList.add('hidden');

            try {{
                const response = await fetch(`${{API_BASE_URL}}/api/jobs/${{JOB_ID}}?confirm=yes&delete_blobs=${{deleteBlobs}}`, {{
                    method: 'DELETE'
                }});

                const data = await response.json();

                if (!data.success) {{
                    throw new Error(data.error || 'Delete failed');
                }}

                // Show success
                preview.classList.add('hidden');
                success.classList.remove('hidden');

                // Redirect to pipeline after delay
                setTimeout(() => {{
                    window.location.href = '/api/interface/pipeline';
                }}, 1500);

            }} catch (err) {{
                error.classList.remove('hidden');
                document.getElementById('delete-error-message').textContent = err.message;
                confirmBtn.disabled = false;
                confirmBtn.textContent = 'Delete Job';
            }}
        }}

        // Close modals on escape key
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') {{
                hideResubmitModal();
                hideDeleteModal();
            }}
        }});

        // ============================================================
        // APPROVAL PANEL (17 FEB 2026)
        // ============================================================

        async function loadApprovalState(job) {{
            const container = document.getElementById('approval-panel-container');
            if (!container) return;

            container.innerHTML = `
                <div class="approval-panel" style="opacity: 0.6;">
                    <h4>Loading approval state...</h4>
                </div>
            `;

            try {{
                const approvalState = await fetchJSON(
                    `${{API_BASE_URL}}/api/assets/${{job.asset_id}}/approval`
                );
                renderApprovalPanel(container, job, approvalState);
            }} catch (err) {{
                container.innerHTML = `
                    <div class="approval-panel">
                        <h4>Approval</h4>
                        <div class="approval-result error">Failed to load approval state: ${{err.message}}</div>
                    </div>
                `;
            }}
        }}

        function renderApprovalPanel(container, job, state) {{
            const approvalState = state.approval_state || 'unknown';
            const processingStatus = state.processing_status || 'unknown';
            const isDraft = !job.parameters?.version_id;

            let html = `<div class="approval-panel">`;
            html += `<h4>Approval</h4>`;

            // Status row
            html += `
                <div class="approval-status-row">
                    <div class="approval-status-item">
                        <span class="approval-status-label">Approval Status</span>
                        <span class="approval-badge ${{approvalState}}">${{approvalState.replace(/_/g, ' ')}}</span>
                    </div>
                    <div class="approval-status-item">
                        <span class="approval-status-label">Processing</span>
                        <span class="approval-status-value">${{processingStatus}}</span>
                    </div>
                    <div class="approval-status-item">
                        <span class="approval-status-label">Asset</span>
                        <span class="approval-status-value" style="font-family: monospace; font-size: 12px;">${{job.asset_id.substring(0, 12)}}...</span>
                    </div>
                    ${{isDraft ? `
                    <div class="approval-status-item">
                        <span class="approval-status-label">Mode</span>
                        <span class="approval-badge pending_review">Draft</span>
                    </div>
                    ` : ''}}
                </div>
            `;

            // Already approved — read-only
            if (approvalState === 'approved') {{
                html += `
                    <div class="approval-readonly">
                        <strong>Approved</strong>
                        ${{state.reviewer ? ` by ${{state.reviewer}}` : ''}}
                        ${{state.approved_at ? ` on ${{new Date(state.approved_at).toLocaleString()}}` : ''}}
                        ${{state.clearance_level ? ` — Clearance: ${{state.clearance_level}}` : ''}}
                    </div>
                `;
                if (state.can_revoke) {{
                    html += `
                        <div class="approval-actions">
                            <button class="approval-btn approval-btn-revoke" onclick="executeRevoke('${{job.asset_id}}')">
                                Revoke Approval
                            </button>
                        </div>
                    `;
                }}
                html += `</div>`;
                container.innerHTML = html;
                return;
            }}

            // Rejected — read-only
            if (approvalState === 'rejected') {{
                html += `
                    <div class="approval-readonly">
                        <strong>Rejected</strong>
                        ${{state.reviewer ? ` by ${{state.reviewer}}` : ''}}
                        ${{state.rejected_at ? ` on ${{new Date(state.rejected_at).toLocaleString()}}` : ''}}
                        ${{state.rejection_reason ? `<br>Reason: ${{state.rejection_reason}}` : ''}}
                    </div>
                `;
                html += `</div>`;
                container.innerHTML = html;
                return;
            }}

            // Revoked — read-only
            if (approvalState === 'revoked') {{
                html += `
                    <div class="approval-readonly">
                        <strong>Revoked</strong>
                        ${{state.reviewer ? ` by ${{state.reviewer}}` : ''}}
                    </div>
                `;
                html += `</div>`;
                container.innerHTML = html;
                return;
            }}

            // Processing not complete — no actions
            if (processingStatus !== 'completed' && job.status !== 'completed') {{
                html += `
                    <div class="approval-readonly">
                        Processing is still in progress. Approval actions will be available once processing completes.
                    </div>
                `;
                html += `</div>`;
                container.innerHTML = html;
                return;
            }}

            // Processing failed — warn
            if (processingStatus === 'failed') {{
                html += `
                    <div class="approval-result error">
                        Processing failed. Cannot approve this asset.
                    </div>
                `;
                html += `</div>`;
                container.innerHTML = html;
                return;
            }}

            // Pending review — show form
            html += `<div class="approval-form">`;

            // Version fields for drafts
            if (isDraft) {{
                html += `
                    <div class="approval-version-section">
                        <div class="section-label">Version (required for drafts)</div>
                        <div class="approval-form-row">
                            <div class="approval-field">
                                <label for="approval-version-id">Version ID</label>
                                <input type="text" id="approval-version-id" placeholder="e.g. v1.0" />
                            </div>
                            <div class="approval-field">
                                <label for="approval-previous-version">Previous Version (for lineage)</label>
                                <input type="text" id="approval-previous-version" placeholder="Optional" />
                            </div>
                        </div>
                    </div>
                `;
            }}

            html += `
                <div class="approval-form-row">
                    <div class="approval-field">
                        <label for="approval-reviewer">Reviewer</label>
                        <input type="text" id="approval-reviewer" placeholder="user@example.com" />
                    </div>
                    <div class="approval-field">
                        <label for="approval-clearance">Clearance Level</label>
                        <select id="approval-clearance">
                            <option value="public">Public</option>
                            <option value="OUO" selected>OUO</option>
                            <option value="FOUO">FOUO</option>
                            <option value="restricted">Restricted</option>
                        </select>
                    </div>
                </div>
                <div class="approval-field">
                    <label for="approval-notes">Notes</label>
                    <input type="text" id="approval-notes" placeholder="Optional notes" />
                </div>
                <div class="approval-field">
                    <label for="reject-reason">Rejection Reason (only used if rejecting)</label>
                    <textarea id="reject-reason" placeholder="Required if rejecting"></textarea>
                </div>
            `;

            html += `
                <div class="approval-actions">
                    ${{state.can_approve ? `
                        <button class="approval-btn approval-btn-approve" id="approve-btn" onclick="executeApproval()">
                            Approve
                        </button>
                    ` : ''}}
                    ${{state.can_reject ? `
                        <button class="approval-btn approval-btn-reject" id="reject-btn" onclick="executeRejection()">
                            Reject
                        </button>
                    ` : ''}}
                </div>
            `;

            html += `</div>`;  // close approval-form
            html += `<div id="approval-result-area"></div>`;
            html += `</div>`;  // close approval-panel

            container.innerHTML = html;
        }}

        async function executeApproval() {{
            const btn = document.getElementById('approve-btn');
            const resultArea = document.getElementById('approval-result-area');
            const reviewer = document.getElementById('approval-reviewer').value.trim();

            if (!reviewer) {{
                resultArea.innerHTML = `<div class="approval-result error">Reviewer is required.</div>`;
                return;
            }}

            btn.disabled = true;
            btn.textContent = 'Approving...';
            resultArea.innerHTML = '';

            const payload = {{
                job_id: JOB_ID,
                reviewer: reviewer,
                clearance_level: document.getElementById('approval-clearance').value,
                notes: document.getElementById('approval-notes').value.trim() || undefined
            }};

            // Draft mode: include version fields
            const versionEl = document.getElementById('approval-version-id');
            if (versionEl && versionEl.value.trim()) {{
                payload.version_id = versionEl.value.trim();
            }}
            const prevEl = document.getElementById('approval-previous-version');
            if (prevEl && prevEl.value.trim()) {{
                payload.previous_version_id = prevEl.value.trim();
            }}

            try {{
                const response = await fetchJSON(`${{API_BASE_URL}}/api/platform/approve`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});

                resultArea.innerHTML = `<div class="approval-result success">Asset approved successfully.</div>`;

                // Refresh events timeline and approval panel
                loadEvents();
                setTimeout(() => loadData(), 1500);

            }} catch (err) {{
                resultArea.innerHTML = `<div class="approval-result error">Approval failed: ${{err.message}}</div>`;
                btn.disabled = false;
                btn.textContent = 'Approve';
            }}
        }}

        async function executeRejection() {{
            const btn = document.getElementById('reject-btn');
            const resultArea = document.getElementById('approval-result-area');
            const reviewer = document.getElementById('approval-reviewer').value.trim();
            const reason = document.getElementById('reject-reason').value.trim();

            if (!reviewer) {{
                resultArea.innerHTML = `<div class="approval-result error">Reviewer is required.</div>`;
                return;
            }}
            if (!reason) {{
                resultArea.innerHTML = `<div class="approval-result error">Rejection reason is required.</div>`;
                return;
            }}

            btn.disabled = true;
            btn.textContent = 'Rejecting...';
            resultArea.innerHTML = '';

            try {{
                const response = await fetchJSON(`${{API_BASE_URL}}/api/platform/reject`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        job_id: JOB_ID,
                        reviewer: reviewer,
                        reason: reason
                    }})
                }});

                resultArea.innerHTML = `<div class="approval-result success">Asset rejected.</div>`;

                // Refresh events timeline and approval panel
                loadEvents();
                setTimeout(() => loadData(), 1500);

            }} catch (err) {{
                resultArea.innerHTML = `<div class="approval-result error">Rejection failed: ${{err.message}}</div>`;
                btn.disabled = false;
                btn.textContent = 'Reject';
            }}
        }}

        async function executeRevoke(assetId) {{
            if (!confirm('Are you sure you want to revoke the approval?')) return;

            try {{
                // Use the asset's approval endpoint for revocation
                const response = await fetchJSON(`${{API_BASE_URL}}/api/platform/revoke`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        asset_id: assetId,
                        reviewer: 'workflow_monitor'
                    }})
                }});

                loadEvents();
                setTimeout(() => loadData(), 1500);

            }} catch (err) {{
                alert('Revoke failed: ' + err.message);
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
