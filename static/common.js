/**
 * Shared configuration and utilities for dashboard pages.
 *
 * Usage: Include this script before page-specific scripts.
 * <script src="common.js"></script>
 */

// API Configuration - Auto-detect from current URL
// When served from /api/dashboard/, use same origin
// When served from static website, use hardcoded URL
const API_BASE_URL = (function() {
    const path = window.location.pathname;
    if (path.startsWith('/api/dashboard')) {
        // Served from Function App - use same origin
        return window.location.origin;
    }
    // Fallback for static website hosting
    return 'https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net';
})();

/**
 * Fetch JSON from API endpoint with error handling.
 * @param {string} path - API path (e.g., '/api/health')
 * @returns {Promise<object>} - Parsed JSON response
 */
async function fetchAPI(path) {
    const response = await fetch(`${API_BASE_URL}${path}`);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json();
}

/**
 * Format bytes to human-readable size.
 * @param {number} bytes - Size in bytes
 * @returns {string} - Formatted size (e.g., "125.4 MB")
 */
function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

/**
 * Format ISO date string to readable format.
 * @param {string} isoString - ISO date string
 * @returns {string} - Formatted date (e.g., "12 Dec 2025 14:30")
 */
function formatDate(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    const day = date.getDate();
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[date.getMonth()];
    const year = date.getFullYear();
    const hours = date.getHours().toString().padStart(2, '0');
    const mins = date.getMinutes().toString().padStart(2, '0');
    return `${day} ${month} ${year} ${hours}:${mins}`;
}

/**
 * Format time as HH:MM:SS.
 * @returns {string} - Current time
 */
function formatTime() {
    return new Date().toLocaleTimeString('en-GB');
}
