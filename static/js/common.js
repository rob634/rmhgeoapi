/* ============================================================
   Common JavaScript Utilities - Extracted from web_interfaces/base.py
   23 JAN 2026 - Phase 1: UI Migration
   ============================================================ */

// ============================================================
        // COMMON UTILITIES - Consolidated JS (S12.1.2)
        // ============================================================

        // API base URL (current origin)
        const API_BASE_URL = window.location.origin;

        // ============================================================
        // ELEMENT VISIBILITY
        // ============================================================

        /**
         * Show an element by removing 'hidden' class
         * @param {string} id - Element ID
         */
        function show(id) {
            const el = document.getElementById(id);
            if (el) el.classList.remove('hidden');
        }

        /**
         * Hide an element by adding 'hidden' class
         * @param {string} id - Element ID
         */
        function hide(id) {
            const el = document.getElementById(id);
            if (el) el.classList.add('hidden');
        }

        /**
         * Toggle element visibility
         * @param {string} id - Element ID
         * @param {boolean} visible - Whether to show (true) or hide (false)
         */
        function toggle(id, visible) {
            visible ? show(id) : hide(id);
        }

        // Legacy aliases for backward compatibility
        function showSpinner(id = 'spinner') { show(id); }
        function hideSpinner(id = 'spinner') { hide(id); }

        // ============================================================
        // STATUS MESSAGES
        // ============================================================

        /**
         * Display a status message
         * @param {string} msg - Message to display
         * @param {boolean} isError - Whether this is an error (red) or success (green)
         */
        function setStatus(msg, isError = false) {
            const el = document.getElementById('status');
            if (el) {
                el.textContent = msg;
                el.className = isError ? 'error' : 'success';
                el.classList.remove('hidden');
                el.style.display = 'block';
            }
        }

        /**
         * Clear/hide the status message
         */
        function clearStatus() {
            const el = document.getElementById('status');
            if (el) {
                el.style.display = 'none';
                el.classList.add('hidden');
            }
        }

        // ============================================================
        // DATE/TIME FORMATTING - All times displayed in Eastern Time
        // ============================================================

        const TIMEZONE = 'America/New_York';
        const LOCALE = 'en-US';

        /**
         * Format a date string or Date object to Eastern Time date string
         * @param {string|Date} date - Date to format
         * @param {string} fallback - Fallback if date is null/invalid
         * @returns {string} Formatted date string in ET
         */
        function formatDate(date, fallback = '--') {
            if (!date) return fallback;
            try {
                return new Date(date).toLocaleDateString(LOCALE, {timeZone: TIMEZONE});
            } catch (e) {
                return fallback;
            }
        }

        /**
         * Format a date string or Date object to Eastern Time date+time string
         * @param {string|Date} date - Date to format
         * @param {string} fallback - Fallback if date is null/invalid
         * @returns {string} Formatted datetime string in ET with timezone indicator
         */
        function formatDateTime(date, fallback = '--') {
            if (!date) return fallback;
            try {
                const formatted = new Date(date).toLocaleString(LOCALE, {
                    timeZone: TIMEZONE,
                    year: 'numeric',
                    month: 'numeric',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true
                });
                return formatted + ' ET';
            } catch (e) {
                return fallback;
            }
        }

        /**
         * Format a date to Eastern Time time only
         * @param {string|Date} date - Date to format
         * @param {string} fallback - Fallback if date is null/invalid
         * @returns {string} Formatted time string in ET
         */
        function formatTime(date, fallback = '--') {
            if (!date) return fallback;
            try {
                const formatted = new Date(date).toLocaleTimeString(LOCALE, {
                    timeZone: TIMEZONE,
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true
                });
                return formatted + ' ET';
            } catch (e) {
                return fallback;
            }
        }

        /**
         * Format a date as relative time (e.g., "5 minutes ago")
         * @param {string|Date} date - Date to format
         * @returns {string} Relative time string
         */
        function formatRelativeTime(date) {
            if (!date) return '--';
            const now = new Date();
            const then = new Date(date);
            const diffMs = now - then;
            const diffSec = Math.floor(diffMs / 1000);
            const diffMin = Math.floor(diffSec / 60);
            const diffHour = Math.floor(diffMin / 60);
            const diffDay = Math.floor(diffHour / 24);

            if (diffSec < 60) return 'just now';
            if (diffMin < 60) return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`;
            if (diffHour < 24) return `${diffHour} hour${diffHour !== 1 ? 's' : ''} ago`;
            if (diffDay < 7) return `${diffDay} day${diffDay !== 1 ? 's' : ''} ago`;
            return formatDate(date);
        }

        // ============================================================
        // NUMBER FORMATTING
        // ============================================================

        /**
         * Format a number with locale-specific separators (e.g., 1,234,567)
         * @param {number} num - Number to format
         * @param {string} fallback - Fallback if num is null/invalid
         * @returns {string} Formatted number string
         */
        function formatNumber(num, fallback = '0') {
            if (num === null || num === undefined || isNaN(num)) return fallback;
            return Number(num).toLocaleString();
        }

        /**
         * Format bytes to human-readable size (KB, MB, GB)
         * @param {number} bytes - Size in bytes
         * @param {number} decimals - Number of decimal places
         * @returns {string} Formatted size string
         */
        function formatBytes(bytes, decimals = 2) {
            if (!bytes || bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(decimals)) + ' ' + sizes[i];
        }

        /**
         * Format a percentage
         * @param {number} value - Value (0-100 or 0-1)
         * @param {boolean} isDecimal - Whether value is 0-1 (true) or 0-100 (false)
         * @returns {string} Formatted percentage string
         */
        function formatPercent(value, isDecimal = false) {
            if (value === null || value === undefined) return '--';
            const pct = isDecimal ? value * 100 : value;
            return pct.toFixed(1) + '%';
        }

        // ============================================================
        // UTILITY FUNCTIONS
        // ============================================================

        /**
         * Debounce a function (delay execution until pause in calls)
         * Useful for search inputs to avoid excessive API calls
         * @param {Function} fn - Function to debounce
         * @param {number} delay - Delay in milliseconds
         * @returns {Function} Debounced function
         */
        function debounce(fn, delay = 300) {
            let timeoutId;
            return function(...args) {
                clearTimeout(timeoutId);
                timeoutId = setTimeout(() => fn.apply(this, args), delay);
            };
        }

        /**
         * Truncate a string with ellipsis
         * @param {string} str - String to truncate
         * @param {number} maxLength - Maximum length before truncation
         * @returns {string} Truncated string
         */
        function truncate(str, maxLength = 50) {
            if (!str) return '';
            return str.length > maxLength ? str.substring(0, maxLength) + '...' : str;
        }

        /**
         * Escape HTML special characters to prevent XSS
         * @param {string} str - String to escape
         * @returns {string} Escaped string safe for innerHTML
         */
        function escapeHtml(str) {
            if (!str) return '';
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        // ============================================================
        // API FETCH HELPERS
        // ============================================================

        /**
         * Fetch JSON from an API endpoint (GET request)
         * @param {string} url - URL to fetch
         * @param {Object} options - Additional fetch options
         * @returns {Promise<Object>} Parsed JSON response
         */
        async function fetchJSON(url, options = {}) {
            try {
                const response = await fetch(url, {
                    headers: { 'Accept': 'application/json' },
                    ...options
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return await response.json();
            } catch (error) {
                console.error('Fetch error:', error);
                setStatus('Error: ' + error.message, true);
                throw error;
            }
        }

        /**
         * POST JSON to an API endpoint
         * @param {string} url - URL to post to
         * @param {Object} data - Data to send as JSON body
         * @returns {Promise<Object>} Parsed JSON response
         */
        async function postJSON(url, data) {
            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify(data)
                });
                if (!response.ok) {
                    const errorBody = await response.text();
                    throw new Error(`HTTP ${response.status}: ${errorBody || response.statusText}`);
                }
                return await response.json();
            } catch (error) {
                console.error('POST error:', error);
                setStatus('Error: ' + error.message, true);
                throw error;
            }
        }

        // ============================================================
        // STATE MANAGEMENT HELPERS
        // ============================================================

        /**
         * Show loading state (show spinner, hide content and error)
         * @param {Object} ids - Object with spinner, content, error element IDs
         */
        function showLoading(ids = {}) {
            const { spinner = 'loading-spinner', content = 'content', error = 'error-state' } = ids;
            show(spinner);
            hide(content);
            hide(error);
        }

        /**
         * Show content state (hide spinner, show content, hide error)
         * @param {Object} ids - Object with spinner, content, error element IDs
         */
        function showContent(ids = {}) {
            const { spinner = 'loading-spinner', content = 'content', error = 'error-state' } = ids;
            hide(spinner);
            show(content);
            hide(error);
        }

        /**
         * Show error state (hide spinner, hide content, show error)
         * @param {string} message - Error message to display
         * @param {Object} ids - Object with spinner, content, error, errorMessage element IDs
         */
        function showError(message, ids = {}) {
            const {
                spinner = 'loading-spinner',
                content = 'content',
                error = 'error-state',
                errorMessage = 'error-message'
            } = ids;
            hide(spinner);
            hide(content);
            show(error);
            const msgEl = document.getElementById(errorMessage);
            if (msgEl) msgEl.textContent = message;
        }

        // ============================================================
        // COLLECTION FILTERING - Common filter function (S12.5.4 - 08 JAN 2026)
        // Used by: stac, vector interfaces
        // Requires: global allCollections array and renderCollections() function
        // ============================================================

        /**
         * Filter collection cards by search term and optional type.
         * Expects: #search-filter input, optional #type-filter select
         * Expects: global allCollections array and renderCollections(filtered) function
         *
         * Note: stac_map uses a DOM-based variant and should keep its own implementation.
         */
        function filterCollections() {
            const searchTerm = (document.getElementById('search-filter')?.value || '').toLowerCase();
            const typeFilter = document.getElementById('type-filter')?.value || '';

            if (typeof allCollections === 'undefined') {
                console.warn('filterCollections: allCollections not defined');
                return;
            }

            const filtered = allCollections.filter(c => {
                const matchesSearch = !searchTerm ||
                    c.id.toLowerCase().includes(searchTerm) ||
                    (c.title || '').toLowerCase().includes(searchTerm) ||
                    (c.description || '').toLowerCase().includes(searchTerm);
                const matchesType = !typeFilter || c.type === typeFilter;
                return matchesSearch && matchesType;
            });

            if (typeof renderCollections === 'function') {
                renderCollections(filtered);
            } else {
                console.warn('filterCollections: renderCollections function not defined');
            }
        }

        // ============================================================
        // SYSTEM STATUS BAR - Polling and updates (28 DEC 2025)
        // ============================================================

        // Activity log entries (kept in memory)
        const activityLog = [];
        const MAX_LOG_ENTRIES = 50;

        /**
         * Add entry to activity log
         * @param {string} type - Entry type (api, job, error, system)
         * @param {string} message - Log message
         */
        function logActivity(type, message) {
            const entry = {
                time: new Date(),
                type: type,
                message: message
            };
            activityLog.unshift(entry);
            if (activityLog.length > MAX_LOG_ENTRIES) {
                activityLog.pop();
            }
            updateActivityLogPanel();
        }

        /**
         * Update the activity log panel UI
         */
        function updateActivityLogPanel() {
            const content = document.getElementById('activity-log-content');
            if (!content) return;

            if (activityLog.length === 0) {
                content.innerHTML = '<div class="activity-log-empty">No activity yet</div>';
                return;
            }

            const html = activityLog.map(entry => {
                const time = entry.time.toLocaleTimeString(LOCALE, {
                    timeZone: TIMEZONE,
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
                return `
                    <div class="activity-log-entry">
                        <span class="activity-log-time">${time}</span>
                        <span class="activity-log-type ${entry.type}">${entry.type.toUpperCase()}</span>
                        <span class="activity-log-message" title="${escapeHtml(entry.message)}">${escapeHtml(entry.message)}</span>
                    </div>
                `;
            }).join('');

            content.innerHTML = html;
        }

        /**
         * Toggle activity log panel visibility
         */
        function toggleActivityLog() {
            const panel = document.getElementById('activity-log-panel');
            if (panel) {
                panel.classList.toggle('open');
            }
        }

        /**
         * Update system status bar with data from /api/system/stats
         * @param {Object} data - Stats data from API
         */
        function updateSystemStatusBar(data) {
            // Memory
            const memPercent = data.memory?.used_percent || 0;
            const memAvailable = data.memory?.available_mb || 0;
            const memClass = memPercent > 90 ? 'critical' : memPercent > 75 ? 'warning' : 'good';

            const memValue = document.getElementById('status-mem-value');
            const memMeter = document.getElementById('status-mem-meter');
            if (memValue) {
                memValue.textContent = memPercent.toFixed(0) + '%';
                memValue.className = 'status-bar-value ' + memClass;
            }
            if (memMeter) {
                memMeter.style.width = memPercent + '%';
                memMeter.className = 'status-bar-meter-fill ' + memClass;
            }

            // CPU
            const cpuPercent = data.cpu?.percent || 0;
            const cpuClass = cpuPercent > 90 ? 'critical' : cpuPercent > 75 ? 'warning' : 'good';

            const cpuValue = document.getElementById('status-cpu-value');
            const cpuMeter = document.getElementById('status-cpu-meter');
            if (cpuValue) {
                cpuValue.textContent = cpuPercent.toFixed(0) + '%';
                cpuValue.className = 'status-bar-value ' + cpuClass;
            }
            if (cpuMeter) {
                cpuMeter.style.width = cpuPercent + '%';
                cpuMeter.className = 'status-bar-meter-fill ' + cpuClass;
            }

            // Jobs
            const jobsActive = data.jobs?.active || 0;
            const jobsPending = data.jobs?.pending || 0;
            const jobsCompleted = data.jobs?.completed_24h || 0;
            const jobsFailed = data.jobs?.failed_24h || 0;

            const activeEl = document.getElementById('status-jobs-active');
            const pendingEl = document.getElementById('status-jobs-pending');
            const completedEl = document.getElementById('status-jobs-completed');
            const failedEl = document.getElementById('status-jobs-failed');

            if (activeEl) activeEl.textContent = jobsActive;
            if (pendingEl) pendingEl.textContent = jobsPending;
            if (completedEl) completedEl.textContent = jobsCompleted;
            if (failedEl) {
                failedEl.textContent = jobsFailed;
                failedEl.className = 'status-bar-value ' + (jobsFailed > 0 ? 'warning' : 'good');
            }

            // Update timestamp
            const tsEl = document.getElementById('status-timestamp');
            if (tsEl) {
                tsEl.textContent = formatTime(data.timestamp);
            }
        }

        /**
         * Fetch and update system stats
         */
        async function refreshSystemStats() {
            try {
                const response = await fetch('/api/system/stats');
                if (response.ok) {
                    const data = await response.json();
                    updateSystemStatusBar(data);
                }
            } catch (error) {
                console.warn('Failed to fetch system stats:', error);
            }
        }

        // Initialize system status polling
        document.addEventListener('DOMContentLoaded', function() {
            // Check if status bar exists
            if (document.getElementById('system-status-bar')) {
                // Add body class for padding
                document.body.classList.add('has-status-bar');

                // Initial fetch
                refreshSystemStats();

                // Poll every 15 seconds
                setInterval(refreshSystemStats, 15000);

                // Log page load
                logActivity('system', 'Page loaded: ' + document.title);
            }
        });

        // Intercept fetch to log API activity
        const originalFetch = window.fetch;
        window.fetch = async function(...args) {
            const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || 'unknown';
            const method = args[1]?.method || 'GET';

            // Don't log system stats polling
            if (!url.includes('/api/system/stats')) {
                const shortUrl = url.replace(window.location.origin, '');
                logActivity('api', `${method} ${shortUrl}`);
            }

            try {
                const response = await originalFetch.apply(this, args);

                // Log errors
                if (!response.ok && !url.includes('/api/system/stats')) {
                    logActivity('error', `HTTP ${response.status}: ${url}`);
                }

                return response;
            } catch (error) {
                logActivity('error', `Network error: ${url}`);
                throw error;
            }
        };