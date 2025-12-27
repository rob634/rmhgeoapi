"""
Service Bus Queues interface module.

Web dashboard for monitoring Azure Service Bus queue status and messages.

Features (16 DEC 2025):
    - Visual display of all active Service Bus queues
    - Active message count per queue
    - Dead Letter Queue (DLQ) message count
    - Queue utilization and size metrics
    - Auto-refresh capability
    - Quick actions to view queue details

Exports:
    QueuesInterface: Service Bus queue monitoring dashboard
"""

import azure.functions as func
from web_interfaces.base import BaseInterface
from web_interfaces import InterfaceRegistry


@InterfaceRegistry.register('queues')
class QueuesInterface(BaseInterface):
    """
    Service Bus Queues Dashboard.

    Displays status, active messages, and DLQ counts for all monitored queues.
    """

    def render(self, request: func.HttpRequest) -> str:
        """
        Generate Service Bus Queues dashboard HTML.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML document string
        """
        content = self._generate_html_content()
        custom_css = self._generate_custom_css()
        custom_js = self._generate_custom_js()

        return self.wrap_html(
            title="Service Bus Queues",
            content=content,
            custom_css=custom_css,
            custom_js=custom_js,
            include_htmx=True
        )

    def _generate_html_content(self) -> str:
        """Generate HTML content for Queues dashboard."""
        return """
        <div class="container">
            <!-- Header -->
            <header class="dashboard-header">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h1>Service Bus Queues</h1>
                        <p class="subtitle">Azure Service Bus Queue Monitoring Dashboard</p>
                    </div>
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <span id="last-updated" class="last-updated"></span>
                        <button id="refreshBtn" class="refresh-button">Refresh</button>
                    </div>
                </div>
            </header>

            <!-- Summary Card -->
            <div id="summary-card" class="summary-card">
                <div class="spinner"></div>
            </div>

            <!-- Queue Cards -->
            <div class="section-title">Queue Status</div>
            <div id="queue-grid" class="queue-grid">
                <div class="spinner"></div>
            </div>

            <!-- Info Section -->
            <div class="info-section">
                <div class="section-title">About Service Bus Queues</div>
                <div class="info-content">
                    <p>Azure Service Bus queues provide asynchronous message processing for the geospatial ETL pipeline.</p>
                    <table class="info-table">
                        <thead>
                            <tr>
                                <th>Queue</th>
                                <th>Purpose</th>
                                <th>Consumer</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><code>jobs</code></td>
                                <td>Job orchestration messages</td>
                                <td>Job processor trigger</td>
                            </tr>
                            <tr>
                                <td><code>raster-tasks</code></td>
                                <td>Raster processing tasks (COG conversion)</td>
                                <td>Raster task processor</td>
                            </tr>
                            <tr>
                                <td><code>vector-tasks</code></td>
                                <td>Vector processing tasks (PostGIS load)</td>
                                <td>Vector task processor</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Error State -->
            <div id="error-state" class="error-state hidden">
                <div class="icon">⚠</div>
                <h3>Error Loading Data</h3>
                <p id="error-message"></p>
                <button onclick="loadData()" class="refresh-button" style="margin-top: 20px;">Retry</button>
            </div>

            <!-- Confirmation Modal -->
            <div id="confirmModal" class="modal-overlay" style="display: none;"></div>
        </div>
        """

    def _generate_custom_css(self) -> str:
        """Generate custom CSS for Queues dashboard."""
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

        .last-updated {
            font-size: 12px;
            color: #626F86;
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

        /* Summary Card */
        .summary-card {
            background: white;
            border: 1px solid #e9ecef;
            padding: 25px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 20px;
        }

        .summary-item {
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
        }

        .summary-label {
            font-size: 11px;
            color: #626F86;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: block;
            margin-bottom: 8px;
        }

        .summary-value {
            font-size: 28px;
            color: #053657;
            font-weight: 700;
        }

        .summary-value.highlight {
            color: #0071BC;
        }

        .summary-value.warning {
            color: #f59e0b;
        }

        .summary-value.error {
            color: #ef4444;
        }

        /* Section Title */
        .section-title {
            font-size: 16px;
            font-weight: 700;
            color: #053657;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e9ecef;
        }

        /* Queue Grid */
        .queue-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .queue-card {
            background: white;
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 25px;
            transition: all 0.3s ease;
            position: relative;
        }

        .queue-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }

        .queue-card.healthy {
            border-color: #10b981;
        }

        .queue-card.warning {
            border-color: #f59e0b;
            background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
        }

        .queue-card.error {
            border-color: #ef4444;
            background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
        }

        .queue-badge {
            position: absolute;
            top: -12px;
            left: 20px;
            background: #0071BC;
            color: white;
            padding: 4px 16px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 700;
        }

        .queue-card.healthy .queue-badge {
            background: #10b981;
        }

        .queue-card.warning .queue-badge {
            background: #f59e0b;
        }

        .queue-card.error .queue-badge {
            background: #ef4444;
        }

        .queue-name {
            font-size: 18px;
            font-weight: 700;
            color: #053657;
            margin: 10px 0 15px 0;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .queue-metrics {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }

        .metric {
            text-align: center;
            padding: 12px;
            background: #f8f9fa;
            border-radius: 6px;
        }

        .metric-value {
            font-size: 24px;
            font-weight: 700;
            color: #053657;
        }

        .metric-value.active {
            color: #0071BC;
        }

        .metric-value.dlq {
            color: #ef4444;
        }

        .metric-value.scheduled {
            color: #8b5cf6;
        }

        .metric-label {
            font-size: 10px;
            color: #626F86;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 4px;
        }

        .queue-footer {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e9ecef;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .utilization-bar {
            flex: 1;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
            margin-right: 15px;
        }

        .utilization-fill {
            height: 100%;
            background: #0071BC;
            border-radius: 4px;
            transition: width 0.3s ease;
        }

        .utilization-fill.warning {
            background: #f59e0b;
        }

        .utilization-fill.error {
            background: #ef4444;
        }

        .utilization-text {
            font-size: 12px;
            color: #626F86;
            min-width: 50px;
            text-align: right;
        }

        /* Info Section */
        .info-section {
            background: white;
            border: 1px solid #e9ecef;
            padding: 25px;
            border-radius: 3px;
            margin-bottom: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .info-content {
            color: #626F86;
            font-size: 14px;
            line-height: 1.6;
        }

        .info-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }

        .info-table th {
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            color: #053657;
            border-bottom: 2px solid #e9ecef;
        }

        .info-table td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
            font-size: 13px;
        }

        .info-table tr:hover {
            background: #f8f9fa;
        }

        .info-table code {
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 12px;
        }

        /* Error State */
        .error-state {
            text-align: center;
            padding: 60px 20px;
            color: #626F86;
            background: white;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .error-state .icon {
            font-size: 48px;
            margin-bottom: 15px;
            opacity: 0.3;
        }

        .error-state h3 {
            color: #053657;
            margin-bottom: 10px;
        }

        /* Action Buttons */
        .queue-actions {
            margin-top: 15px;
            display: flex;
            gap: 10px;
        }

        .action-btn {
            padding: 6px 12px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            background: white;
            color: #053657;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
        }

        .action-btn:hover {
            border-color: #0071BC;
            color: #0071BC;
        }

        .action-btn.danger:hover {
            border-color: #ef4444;
            color: #ef4444;
        }

        .action-btn.danger-solid {
            background: #ef4444;
            color: white;
            border-color: #ef4444;
        }

        .action-btn.danger-solid:hover {
            background: #dc2626;
            border-color: #dc2626;
        }

        .action-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Confirmation Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }

        .modal-content {
            background: white;
            border-radius: 8px;
            padding: 30px;
            max-width: 450px;
            width: 90%;
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }

        .modal-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 20px;
        }

        .modal-header .icon {
            font-size: 32px;
        }

        .modal-header h3 {
            color: #053657;
            margin: 0;
            font-size: 20px;
        }

        .modal-body {
            color: #626F86;
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 20px;
        }

        .modal-body .queue-name {
            font-family: monospace;
            background: #f3f4f6;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
        }

        .modal-body .warning {
            background: #fef2f2;
            border: 1px solid #fecaca;
            border-radius: 6px;
            padding: 12px;
            margin-top: 15px;
            color: #991b1b;
            font-size: 13px;
        }

        .modal-footer {
            display: flex;
            gap: 12px;
            justify-content: flex-end;
        }

        .modal-btn {
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .modal-btn.cancel {
            background: #f3f4f6;
            border: 1px solid #e5e7eb;
            color: #374151;
        }

        .modal-btn.cancel:hover {
            background: #e5e7eb;
        }

        .modal-btn.confirm {
            background: #ef4444;
            border: 1px solid #ef4444;
            color: white;
        }

        .modal-btn.confirm:hover {
            background: #dc2626;
        }

        .modal-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Toast notification */
        .toast {
            position: fixed;
            bottom: 20px;
            right: 20px;
            padding: 15px 25px;
            border-radius: 8px;
            color: white;
            font-weight: 600;
            font-size: 14px;
            z-index: 1001;
            animation: slideIn 0.3s ease;
        }

        .toast.success {
            background: #10b981;
        }

        .toast.error {
            background: #ef4444;
        }

        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        """

    def _generate_custom_js(self) -> str:
        """Generate custom JavaScript for Queues dashboard."""
        return """
        // Load data on page load
        document.addEventListener('DOMContentLoaded', () => {
            loadData();
            document.getElementById('refreshBtn').addEventListener('click', loadData);
        });

        async function loadData() {
            const summaryCard = document.getElementById('summary-card');
            const queueGrid = document.getElementById('queue-grid');
            const errorState = document.getElementById('error-state');

            // Show loading
            summaryCard.innerHTML = '<div class="spinner"></div>';
            queueGrid.innerHTML = '<div class="spinner"></div>';
            errorState.classList.add('hidden');

            try {
                // Fetch queue stats from API
                const response = await fetchJSON(`${API_BASE_URL}/api/servicebus?type=queues`);

                // Update last updated time
                const lastUpdated = document.getElementById('last-updated');
                lastUpdated.textContent = 'Updated: ' + formatTime(new Date());

                // Render summary
                renderSummary(response);

                // Render queue cards
                renderQueueGrid(response);

            } catch (error) {
                console.error('Error loading queue data:', error);
                showError(error.message || 'Failed to load Service Bus queue data');
            }
        }

        function renderSummary(data) {
            const queues = data.queues || [];
            const totalActive = data.total_active_messages || 0;
            const totalDLQ = data.total_dead_letter_messages || 0;
            const healthyQueues = queues.filter(q => !q.error && (q.dead_letter_messages || 0) === 0).length;
            const warningQueues = queues.filter(q => !q.error && (q.dead_letter_messages || 0) > 0).length;

            let dlqClass = 'highlight';
            if (totalDLQ > 0 && totalDLQ < 10) dlqClass = 'warning';
            if (totalDLQ >= 10) dlqClass = 'error';

            const html = `
                <div class="summary-grid">
                    <div class="summary-item">
                        <span class="summary-label">Total Queues</span>
                        <span class="summary-value">${queues.length}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Active Messages</span>
                        <span class="summary-value highlight">${totalActive.toLocaleString()}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Dead Letter</span>
                        <span class="summary-value ${dlqClass}">${totalDLQ.toLocaleString()}</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">Healthy</span>
                        <span class="summary-value">${healthyQueues} / ${queues.length}</span>
                    </div>
                </div>
            `;

            document.getElementById('summary-card').innerHTML = html;
        }

        function renderQueueGrid(data) {
            const queues = data.queues || [];
            let html = '';

            if (queues.length === 0) {
                html = '<div class="error-state"><div class="icon">📭</div><h3>No Queues Found</h3><p>No Service Bus queues are configured.</p></div>';
                document.getElementById('queue-grid').innerHTML = html;
                return;
            }

            queues.forEach(queue => {
                if (queue.error) {
                    html += renderErrorQueueCard(queue);
                } else {
                    html += renderQueueCard(queue);
                }
            });

            document.getElementById('queue-grid').innerHTML = html;
        }

        function renderQueueCard(queue) {
            const active = queue.active_messages || 0;
            const dlq = queue.dead_letter_messages || 0;
            const scheduled = queue.scheduled_messages || 0;
            const total = queue.total_messages || 0;
            const utilization = queue.utilization_percent || 0;

            // Determine status
            let status = 'healthy';
            let badge = 'Healthy';
            if (dlq > 0 && dlq < 10) {
                status = 'warning';
                badge = 'Warning';
            } else if (dlq >= 10) {
                status = 'error';
                badge = 'DLQ Alert';
            }

            // Utilization bar class
            let utilClass = '';
            if (utilization > 50) utilClass = 'warning';
            if (utilization > 80) utilClass = 'error';

            return `
                <div class="queue-card ${status}">
                    <div class="queue-badge">${badge}</div>
                    <div class="queue-name">${queue.queue_name}</div>
                    <div class="queue-metrics">
                        <div class="metric">
                            <div class="metric-value active">${active.toLocaleString()}</div>
                            <div class="metric-label">Active</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value dlq">${dlq.toLocaleString()}</div>
                            <div class="metric-label">Dead Letter</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value scheduled">${scheduled.toLocaleString()}</div>
                            <div class="metric-label">Scheduled</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">${total.toLocaleString()}</div>
                            <div class="metric-label">Total</div>
                        </div>
                    </div>
                    <div class="queue-footer">
                        <div class="utilization-bar">
                            <div class="utilization-fill ${utilClass}" style="width: ${Math.min(utilization, 100)}%"></div>
                        </div>
                        <span class="utilization-text">${utilization.toFixed(1)}%</span>
                    </div>
                    <div class="queue-actions">
                        <a href="/api/servicebus/queue/${queue.queue_name}?type=peek" target="_blank" class="action-btn">Peek Messages</a>
                        <a href="/api/servicebus/queue/${queue.queue_name}?type=deadletter" target="_blank" class="action-btn">View DLQ</a>
                        <button onclick="showClearQueueModal('${queue.queue_name}', ${total})" class="action-btn danger-solid">Clear Queue</button>
                    </div>
                </div>
            `;
        }

        function renderErrorQueueCard(queue) {
            return `
                <div class="queue-card error">
                    <div class="queue-badge">Error</div>
                    <div class="queue-name">${queue.queue_name}</div>
                    <div style="padding: 20px; text-align: center; color: #ef4444;">
                        <p>Failed to retrieve queue metrics</p>
                        <p style="font-size: 12px; color: #626F86;">${queue.error}</p>
                    </div>
                </div>
            `;
        }

        function showError(message) {
            document.getElementById('summary-card').innerHTML = '';
            document.getElementById('queue-grid').innerHTML = '';
            document.getElementById('error-state').classList.remove('hidden');
            document.getElementById('error-message').textContent = message;
        }

        // Clear Queue Modal Functions
        function showClearQueueModal(queueName, messageCount) {
            const modal = document.getElementById('confirmModal');
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <span class="icon">⚠️</span>
                        <h3>Clear Queue Messages</h3>
                    </div>
                    <div class="modal-body">
                        <p>You are about to clear all messages from queue:</p>
                        <p><span class="queue-name">${queueName}</span></p>
                        <p>This will delete <strong>${messageCount.toLocaleString()}</strong> message(s) including:</p>
                        <ul style="margin: 10px 0; padding-left: 20px;">
                            <li>Active messages</li>
                            <li>Dead letter messages</li>
                            <li>Scheduled messages</li>
                        </ul>
                        <div class="warning">
                            <strong>⚠️ Warning:</strong> This action is IRREVERSIBLE. All messages will be permanently deleted.
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="modal-btn cancel" onclick="hideModal()">Cancel</button>
                        <button class="modal-btn confirm" id="confirmClearBtn" onclick="clearQueue('${queueName}')">
                            Clear All Messages
                        </button>
                    </div>
                </div>
            `;
            modal.style.display = 'flex';

            // Close modal on overlay click
            modal.addEventListener('click', (e) => {
                if (e.target === modal) hideModal();
            });
        }

        function hideModal() {
            const modal = document.getElementById('confirmModal');
            modal.style.display = 'none';
            modal.innerHTML = '';
        }

        async function clearQueue(queueName) {
            const confirmBtn = document.getElementById('confirmClearBtn');
            confirmBtn.disabled = true;
            confirmBtn.textContent = 'Clearing...';

            try {
                const response = await fetch(
                    `/api/servicebus/queue/${encodeURIComponent(queueName)}?type=nuke&confirm=yes&target=all`,
                    { method: 'POST' }
                );

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || `HTTP ${response.status}`);
                }

                // Success
                hideModal();
                showToast(`Cleared ${data.deleted.total} messages from ${queueName}`, 'success');

                // Refresh the queue data
                loadData();

            } catch (error) {
                console.error('Error clearing queue:', error);
                hideModal();
                showToast(`Failed to clear queue: ${error.message}`, 'error');
            }
        }

        function showToast(message, type) {
            // Remove existing toasts
            document.querySelectorAll('.toast').forEach(t => t.remove());

            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            document.body.appendChild(toast);

            // Auto-remove after 5 seconds
            setTimeout(() => {
                toast.remove();
            }, 5000);
        }
        """
