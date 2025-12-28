"""
Web interfaces base module.

Abstract base class and common utilities for all web interface modules.

Exports:
    BaseInterface: Abstract base class with common HTML utilities and navigation

Dependencies:
    azure.functions: HTTP request handling
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import azure.functions as func

from config import __version__


class BaseInterface(ABC):
    """
    Abstract base class for all web interfaces.

    Provides:
        - Common CSS and JavaScript utilities
        - HTML document structure (wrap_html)
        - Navigation bar across all interfaces
        - Query parameter helpers

    Each interface must implement:
        - render(request) -> str
    """

    # Common CSS used by all interfaces
    # Consolidated 23 DEC 2025 - S12.1.1
    COMMON_CSS = """
        /* ============================================================
           DESIGN SYSTEM - Consolidated CSS (S12.1.1)
           ============================================================ */

        /* Design System Color Variables */
        :root {
            --ds-blue-primary: #0071BC;
            --ds-blue-dark: #245AAD;
            --ds-navy: #053657;
            --ds-cyan: #00A3DA;
            --ds-gold: #FFC14D;
            --ds-gray: #626F86;
            --ds-gray-light: #e9ecef;
            --ds-bg: #f8f9fa;
            /* Status colors */
            --ds-status-queued-bg: #f3f4f6;
            --ds-status-queued-fg: #6b7280;
            --ds-status-pending-bg: #fef3c7;
            --ds-status-pending-fg: #d97706;
            --ds-status-processing-bg: #dbeafe;
            --ds-status-processing-fg: #0071BC;
            --ds-status-completed-bg: #d1fae5;
            --ds-status-completed-fg: #059669;
            --ds-status-failed-bg: #fee2e2;
            --ds-status-failed-fg: #dc2626;
        }

        /* CSS Reset */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Open Sans", Arial, sans-serif;
            background: var(--ds-bg);
            min-height: 100vh;
            padding: 20px;
            color: var(--ds-navy);
            font-size: 14px;
            line-height: 1.6;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .hidden {
            display: none !important;
        }

        /* ============================================================
           DASHBOARD HEADER - Used by jobs, stac, vector, h3, etc.
           ============================================================ */
        .dashboard-header {
            background: white;
            padding: 25px 30px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            border-left: 4px solid var(--ds-blue-primary);
        }

        .dashboard-header h1 {
            color: var(--ds-navy);
            font-size: 24px;
            margin-bottom: 8px;
            font-weight: 700;
        }

        .dashboard-header .subtitle,
        .subtitle {
            color: var(--ds-gray);
            font-size: 14px;
            margin: 0;
        }

        /* ============================================================
           BUTTONS - Consistent button styles
           ============================================================ */
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 10px 20px;
            border-radius: 3px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
            border: 1px solid transparent;
            text-decoration: none;
        }

        .btn-primary {
            background: var(--ds-blue-primary);
            color: white;
            border-color: var(--ds-blue-primary);
        }

        .btn-primary:hover {
            background: #005a96;
            border-color: #005a96;
        }

        .btn-secondary {
            background: white;
            color: var(--ds-gray);
            border-color: var(--ds-gray-light);
        }

        .btn-secondary:hover {
            background: var(--ds-gray-light);
            color: var(--ds-navy);
        }

        .btn-sm {
            padding: 6px 12px;
            font-size: 12px;
        }

        .refresh-button {
            background: var(--ds-blue-primary);
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

        /* ============================================================
           STATUS BADGES - Consistent status indicators
           ============================================================ */
        .status-badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }

        .status-badge.status-queued,
        .status-queued {
            background: var(--ds-status-queued-bg);
            color: var(--ds-status-queued-fg);
        }

        .status-badge.status-pending,
        .status-pending {
            background: var(--ds-status-pending-bg);
            color: var(--ds-status-pending-fg);
        }

        .status-badge.status-processing,
        .status-processing {
            background: var(--ds-status-processing-bg);
            color: var(--ds-status-processing-fg);
        }

        .status-badge.status-completed,
        .status-completed {
            background: var(--ds-status-completed-bg);
            color: var(--ds-status-completed-fg);
        }

        .status-badge.status-failed,
        .status-failed {
            background: var(--ds-status-failed-bg);
            color: var(--ds-status-failed-fg);
        }

        /* ============================================================
           STATS BANNER - Summary statistics display
           ============================================================ */
        .stats-banner {
            background: white;
            padding: 20px 30px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            gap: 40px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            flex-wrap: wrap;
        }

        .stat-item {
            display: flex;
            flex-direction: column;
            text-align: center;
            padding: 15px;
            background: var(--ds-bg);
            border-radius: 6px;
            min-width: 120px;
        }

        .stat-label {
            font-size: 11px;
            color: var(--ds-gray);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .stat-value {
            font-size: 28px;
            font-weight: 700;
            color: var(--ds-navy);
        }

        .stat-value.highlight {
            color: var(--ds-blue-primary);
        }

        /* Grid-based stats (jobs dashboard) */
        .stat-card {
            background: white;
            border-radius: 8px;
            padding: 1.25rem;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        /* ============================================================
           FILTER BAR - Search and filter controls
           ============================================================ */
        .filter-bar {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            display: flex;
            gap: 1.5rem;
            align-items: flex-end;
            flex-wrap: wrap;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            min-width: 150px;
        }

        .filter-group label {
            font-size: 0.875rem;
            font-weight: 500;
            color: #374151;
        }

        .filter-select,
        .filter-input {
            padding: 0.5rem 0.75rem;
            border: 1px solid #d1d5db;
            border-radius: 6px;
            font-size: 0.875rem;
            background: white;
            cursor: pointer;
        }

        .filter-select:focus,
        .filter-input:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 3px rgba(0, 113, 188, 0.1);
        }

        .filter-actions {
            display: flex;
            gap: 0.75rem;
            margin-left: auto;
        }

        /* Simpler controls container */
        .controls {
            background: white;
            padding: 20px;
            border-radius: 3px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }

        .search-input {
            width: 100%;
            padding: 12px 20px;
            border: 1px solid var(--ds-gray-light);
            border-radius: 3px;
            font-size: 14px;
            color: var(--ds-navy);
            font-weight: 600;
        }

        .search-input:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 3px rgba(0,113,188,0.1);
        }

        /* ============================================================
           DATA TABLES - Consistent table styling
           ============================================================ */
        .data-table,
        .items-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .data-table thead,
        .items-table thead {
            background: #f9fafb;
        }

        .data-table th,
        .items-table th {
            padding: 1rem;
            text-align: left;
            font-size: 0.875rem;
            font-weight: 600;
            color: #374151;
            border-bottom: 2px solid #e5e7eb;
        }

        .data-table td,
        .items-table td {
            padding: 1rem;
            border-bottom: 1px solid #e5e7eb;
            font-size: 0.875rem;
        }

        .data-table tbody tr:hover,
        .items-table tbody tr:hover {
            background: #f9fafb;
        }

        /* ============================================================
           CARDS - Card components for grids
           ============================================================ */
        .card {
            background: white;
            border-radius: 8px;
            padding: 24px;
            text-decoration: none;
            color: inherit;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            border-left: 4px solid var(--ds-blue-primary);
            transition: all 0.2s;
            display: flex;
            flex-direction: column;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            border-left-color: var(--ds-cyan);
        }

        .card-title,
        .card h3 {
            font-size: 18px;
            color: var(--ds-navy);
            margin-bottom: 10px;
            font-weight: 700;
        }

        .card-description,
        .card .description {
            font-size: 14px;
            color: var(--ds-gray);
            margin-bottom: 15px;
            line-height: 1.6;
        }

        .card-footer {
            font-size: 14px;
            font-weight: 600;
            color: var(--ds-blue-primary);
            margin-top: auto;
        }

        .card:hover .card-footer {
            color: var(--ds-cyan);
        }

        /* Collection card variant */
        .collection-card {
            background: white;
            border: 1px solid var(--ds-gray-light);
            border-left: 4px solid var(--ds-blue-primary);
            border-radius: 3px;
            padding: 24px;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }

        .collection-card:hover {
            box-shadow: 0 4px 12px rgba(0,113,188,0.15);
            border-left-color: var(--ds-cyan);
            transform: translateY(-2px);
        }

        .collection-card h3 {
            font-size: 18px;
            color: var(--ds-navy);
            margin-bottom: 10px;
            font-weight: 700;
        }

        .collection-card .description {
            font-size: 14px;
            color: var(--ds-gray);
            margin-bottom: 15px;
            line-height: 1.6;
        }

        .collection-card .meta {
            display: flex;
            gap: 15px;
            font-size: 13px;
            color: var(--ds-blue-primary);
            font-weight: 600;
        }

        /* Cards grid layout */
        .cards-grid,
        .collections-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }

        /* ============================================================
           LOADING / EMPTY / ERROR STATES
           ============================================================ */
        .spinner {
            border: 4px solid var(--ds-gray-light);
            border-top: 4px solid var(--ds-blue-primary);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 0.8s linear infinite;
            margin: 20px auto;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .spinner-container,
        .loading-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 60px 20px;
            background: white;
            border-radius: 8px;
        }

        .spinner-text {
            margin-top: 20px;
            color: var(--ds-gray);
            font-size: 14px;
        }

        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--ds-gray);
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }

        .empty-state .icon {
            font-size: 64px;
            margin-bottom: 20px;
            opacity: 0.3;
        }

        .empty-state h3 {
            font-size: 20px;
            margin-bottom: 10px;
            color: var(--ds-navy);
        }

        .error-state {
            text-align: center;
            padding: 40px 20px;
            background: #fee2e2;
            border-radius: 8px;
        }

        .error-state .icon {
            font-size: 48px;
            margin-bottom: 15px;
            opacity: 0.5;
        }

        .error-state h3 {
            color: var(--ds-navy);
            margin-bottom: 10px;
        }

        .error-message {
            color: #dc2626;
            margin-bottom: 1rem;
        }

        /* ============================================================
           LINKS AND BADGES
           ============================================================ */
        .link-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 4px 10px;
            background: var(--ds-bg);
            border: 1px solid var(--ds-gray-light);
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: var(--ds-blue-primary);
            text-decoration: none;
            transition: all 0.2s;
        }

        .link-badge:hover {
            background: var(--ds-blue-primary);
            color: white;
            transform: translateY(-1px);
        }

        .link-badge-primary {
            background: var(--ds-blue-primary);
            color: white;
            border-color: var(--ds-blue-primary);
        }

        .link-badge-primary:hover {
            background: var(--ds-cyan);
            border-color: var(--ds-cyan);
        }

        /* ============================================================
           MONOSPACE / CODE ELEMENTS
           ============================================================ */
        .job-id-short,
        .item-id,
        code {
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.75rem;
            color: var(--ds-gray);
        }

        /* ============================================================
           METADATA DISPLAY
           ============================================================ */
        .metadata {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }

        .metadata-item {
            background: var(--ds-bg);
            border: 1px solid var(--ds-gray-light);
            padding: 12px;
            border-radius: 3px;
        }

        .metadata-item .label {
            font-size: 12px;
            color: var(--ds-gray);
            margin-bottom: 4px;
            text-transform: uppercase;
            font-weight: 600;
        }

        .metadata-item .value {
            font-size: 16px;
            font-weight: 600;
            color: var(--ds-navy);
        }

        /* ============================================================
           STATUS MESSAGE (legacy support)
           ============================================================ */
        #status {
            padding: 12px 16px;
            border-radius: 3px;
            margin: 10px 0;
            font-size: 14px;
            border: 1px solid transparent;
        }

        #status.error {
            background: #fff5f5;
            border-color: #fc8181;
            color: #c53030;
        }

        #status.success {
            background: #f0fff4;
            border-color: #68d391;
            color: #2f855a;
        }

        /* ============================================================
           SECTION TITLES
           ============================================================ */
        .section-title {
            font-size: 16px;
            font-weight: 700;
            color: var(--ds-navy);
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        /* ============================================================
           SYSTEM STATUS BAR - Fixed bottom status bar (28 DEC 2025)
           ============================================================ */
        .system-status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 8px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            z-index: 1000;
            border-top: 1px solid #333;
        }

        .status-bar-left,
        .status-bar-right {
            display: flex;
            gap: 20px;
            align-items: center;
        }

        .status-bar-item {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-bar-label {
            color: #888;
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .status-bar-value {
            font-weight: 600;
            font-family: 'Monaco', 'Courier New', monospace;
        }

        .status-bar-value.good {
            color: #4ade80;
        }

        .status-bar-value.warning {
            color: #fbbf24;
        }

        .status-bar-value.critical {
            color: #f87171;
        }

        .status-bar-meter {
            width: 60px;
            height: 6px;
            background: #333;
            border-radius: 3px;
            overflow: hidden;
        }

        .status-bar-meter-fill {
            height: 100%;
            transition: width 0.3s, background 0.3s;
        }

        .status-bar-meter-fill.good {
            background: #4ade80;
        }

        .status-bar-meter-fill.warning {
            background: #fbbf24;
        }

        .status-bar-meter-fill.critical {
            background: #f87171;
        }

        .status-bar-divider {
            width: 1px;
            height: 20px;
            background: #333;
        }

        /* Activity log toggle button */
        .activity-log-toggle {
            background: transparent;
            border: 1px solid #444;
            color: #e0e0e0;
            padding: 4px 10px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            transition: all 0.2s;
        }

        .activity-log-toggle:hover {
            background: #333;
            border-color: #555;
        }

        /* Adjust body padding for fixed status bar */
        body.has-status-bar {
            padding-bottom: 50px;
        }

        /* ============================================================
           ACTIVITY LOG PANEL - Slide-up panel (28 DEC 2025)
           ============================================================ */
        .activity-log-panel {
            position: fixed;
            bottom: 40px;
            right: 20px;
            width: 400px;
            max-height: 300px;
            background: #1a1a2e;
            border: 1px solid #333;
            border-radius: 8px 8px 0 0;
            box-shadow: 0 -4px 20px rgba(0,0,0,0.3);
            z-index: 999;
            display: none;
            flex-direction: column;
        }

        .activity-log-panel.open {
            display: flex;
        }

        .activity-log-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 15px;
            background: #252540;
            border-bottom: 1px solid #333;
            border-radius: 8px 8px 0 0;
        }

        .activity-log-title {
            color: #e0e0e0;
            font-weight: 600;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .activity-log-close {
            background: transparent;
            border: none;
            color: #888;
            cursor: pointer;
            font-size: 16px;
            padding: 0;
            line-height: 1;
        }

        .activity-log-close:hover {
            color: #e0e0e0;
        }

        .activity-log-content {
            flex: 1;
            overflow-y: auto;
            padding: 0;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 11px;
        }

        .activity-log-entry {
            padding: 8px 15px;
            border-bottom: 1px solid #252540;
            display: flex;
            gap: 10px;
        }

        .activity-log-entry:hover {
            background: #252540;
        }

        .activity-log-time {
            color: #666;
            flex-shrink: 0;
            width: 70px;
        }

        .activity-log-type {
            flex-shrink: 0;
            width: 60px;
            font-weight: 600;
        }

        .activity-log-type.api {
            color: #60a5fa;
        }

        .activity-log-type.job {
            color: #4ade80;
        }

        .activity-log-type.error {
            color: #f87171;
        }

        .activity-log-type.system {
            color: #a78bfa;
        }

        .activity-log-message {
            color: #e0e0e0;
            flex: 1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .activity-log-empty {
            color: #666;
            text-align: center;
            padding: 30px;
            font-style: italic;
        }

        /* Job progress indicator in status bar */
        .job-progress-mini {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .job-progress-mini .progress-bar {
            width: 80px;
            height: 4px;
            background: #333;
            border-radius: 2px;
            overflow: hidden;
        }

        .job-progress-mini .progress-fill {
            height: 100%;
            background: var(--ds-blue-primary);
            transition: width 0.3s;
        }
    """

    # Common JavaScript utilities
    # Expanded 23 DEC 2025 - S12.1.2
    COMMON_JS = """
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
    """

    # ========================================================================
    # HTMX Support - Added S12.2.1
    # ========================================================================

    # HTMX-specific CSS for loading indicators and transitions
    HTMX_CSS = """
        /* ============================================================
           HTMX STYLES - Loading indicators and transitions (S12.2.1)
           ============================================================ */

        /* HTMX loading indicator - shows during requests */
        .htmx-indicator {
            display: none;
        }

        .htmx-request .htmx-indicator,
        .htmx-request.htmx-indicator {
            display: inline-block;
        }

        /* Spinner indicator for HTMX requests */
        .htmx-indicator.spinner-sm {
            width: 16px;
            height: 16px;
            border: 2px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.6s linear infinite;
            margin-left: 8px;
            vertical-align: middle;
        }

        /* Fade out content being replaced */
        .htmx-swapping {
            opacity: 0.5;
            transition: opacity 0.2s ease-out;
        }

        /* Fade in new content */
        .htmx-settling {
            opacity: 1;
            transition: opacity 0.2s ease-in;
        }

        /* Pulse animation for elements being updated */
        .htmx-added {
            animation: htmx-pulse 0.5s ease-out;
        }

        @keyframes htmx-pulse {
            0% { background-color: rgba(0, 113, 188, 0.2); }
            100% { background-color: transparent; }
        }

        /* Loading overlay for containers */
        .htmx-loading-overlay {
            position: relative;
        }

        .htmx-loading-overlay::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255, 255, 255, 0.7);
            display: none;
            z-index: 10;
        }

        .htmx-loading-overlay.htmx-request::after {
            display: block;
        }

        /* Button loading state */
        button.htmx-request {
            opacity: 0.7;
            cursor: wait;
        }

        button.htmx-request .btn-text {
            opacity: 0.5;
        }

        /* Disabled inputs during request */
        .htmx-request input,
        .htmx-request select,
        .htmx-request textarea {
            pointer-events: none;
            opacity: 0.7;
        }

        /* Progress bar for long requests */
        .htmx-progress {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--ds-blue-primary);
            transform: scaleX(0);
            transform-origin: left;
            transition: transform 0.3s ease;
            z-index: 9999;
        }

        .htmx-request .htmx-progress {
            transform: scaleX(0.9);
        }
    """

    # HTMX-specific JavaScript configuration and helpers
    HTMX_JS = """
        // ============================================================
        // HTMX CONFIGURATION AND HELPERS (S12.2.1)
        // ============================================================

        // Configure HTMX defaults
        document.addEventListener('DOMContentLoaded', function() {
            // Global HTMX configuration
            if (typeof htmx !== 'undefined') {
                htmx.config.defaultSwapStyle = 'innerHTML';
                htmx.config.defaultSettleDelay = 100;
                htmx.config.includeIndicatorStyles = false;  // We use our own
                htmx.config.historyCacheSize = 0;  // Disable history cache for API dashboard

                console.log('HTMX ' + htmx.version + ' initialized');
            }
        });

        // ============================================================
        // HTMX EVENT HANDLERS
        // ============================================================

        // Before request - can be used to show loading state
        document.body.addEventListener('htmx:beforeRequest', function(evt) {
            // Clear any previous error states
            clearStatus();
        });

        // After request completes successfully
        document.body.addEventListener('htmx:afterRequest', function(evt) {
            if (evt.detail.successful) {
                // Request succeeded
            } else {
                // Request failed - show error
                const xhr = evt.detail.xhr;
                if (xhr && xhr.status !== 0) {
                    setStatus(`Request failed: HTTP ${xhr.status}`, true);
                }
            }
        });

        // Handle HTMX errors
        document.body.addEventListener('htmx:responseError', function(evt) {
            const xhr = evt.detail.xhr;
            let message = 'Request failed';
            if (xhr) {
                try {
                    const response = JSON.parse(xhr.responseText);
                    message = response.error || response.message || `HTTP ${xhr.status}`;
                } catch (e) {
                    message = `HTTP ${xhr.status}: ${xhr.statusText}`;
                }
            }
            setStatus(message, true);
        });

        // Handle network errors
        document.body.addEventListener('htmx:sendError', function(evt) {
            setStatus('Network error - please check your connection', true);
        });

        // Handle timeout
        document.body.addEventListener('htmx:timeout', function(evt) {
            setStatus('Request timed out - please try again', true);
        });

        // ============================================================
        // HTMX HELPER FUNCTIONS
        // ============================================================

        /**
         * Trigger an HTMX request programmatically
         * @param {string} selector - CSS selector for element with hx-* attributes
         * @param {string} verb - HTTP verb (get, post, etc.)
         */
        function htmxTrigger(selector, verb = 'get') {
            const el = document.querySelector(selector);
            if (el && typeof htmx !== 'undefined') {
                htmx.trigger(el, `hx-${verb}`);
            }
        }

        /**
         * Refresh an HTMX element by re-triggering its request
         * @param {string} selector - CSS selector
         */
        function htmxRefresh(selector) {
            const el = document.querySelector(selector);
            if (el && typeof htmx !== 'undefined') {
                htmx.trigger(el, 'refresh');
            }
        }

        /**
         * Update URL parameters and trigger HTMX request
         * @param {string} selector - Element selector
         * @param {Object} params - URL parameters to set
         */
        function htmxUpdateParams(selector, params) {
            const el = document.querySelector(selector);
            if (!el) return;

            const currentUrl = el.getAttribute('hx-get') || el.getAttribute('hx-post');
            if (!currentUrl) return;

            const url = new URL(currentUrl, window.location.origin);
            Object.entries(params).forEach(([key, value]) => {
                if (value === null || value === '') {
                    url.searchParams.delete(key);
                } else {
                    url.searchParams.set(key, value);
                }
            });

            el.setAttribute('hx-get', url.pathname + url.search);
            if (typeof htmx !== 'undefined') {
                htmx.trigger(el, 'refresh');
            }
        }

        /**
         * Process HTMX with new content (for dynamically added elements)
         * @param {string|Element} content - Element or selector to process
         */
        function htmxProcess(content) {
            if (typeof htmx !== 'undefined') {
                const el = typeof content === 'string' ? document.querySelector(content) : content;
                if (el) htmx.process(el);
            }
        }
    """

    @abstractmethod
    def render(self, request: func.HttpRequest) -> str:
        """
        Generate HTML for this interface.

        This method MUST be implemented by each interface.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML string (full document)
        """
        pass

    def get_query_params(self, request: func.HttpRequest) -> Dict[str, Any]:
        """
        Extract query parameters from request.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Dictionary of query parameter key-value pairs

        Example:
            # Request: /api/interface/vector?collection=test&limit=100
            params = self.get_query_params(request)
            # params = {'collection': 'test', 'limit': '100'}
        """
        return {key: request.params.get(key) for key in request.params}

    def htmx_partial(self, request: func.HttpRequest, fragment: str) -> str:
        """
        Handle HTMX partial requests.

        Override this method in subclasses to return HTML fragments
        for HTMX requests. The fragment parameter specifies which
        partial to render.

        Args:
            request: Azure Functions HttpRequest object
            fragment: Name of fragment to render (from ?fragment= query param)

        Returns:
            HTML fragment string (not a full document)

        Raises:
            ValueError: If fragment is not supported

        Example:
            def htmx_partial(self, request, fragment):
                if fragment == 'containers':
                    zone = request.params.get('zone')
                    return self._render_container_options(zone)
                elif fragment == 'files':
                    return self._render_files_table(request)
                else:
                    raise ValueError(f"Unknown fragment: {fragment}")

        Note:
            The unified_interface_handler routes to this method when
            both HX-Request header is present AND fragment param is set.
        """
        raise ValueError(
            f"Interface {self.__class__.__name__} does not support "
            f"HTMX fragments. Override htmx_partial() to add support."
        )

    # HTMX version - pinned for stability
    HTMX_VERSION = "1.9.10"

    def wrap_html(
        self,
        title: str,
        content: str,
        custom_css: str = "",
        custom_js: str = "",
        include_navbar: bool = True,
        include_htmx: bool = True,
        include_status_bar: bool = True
    ) -> str:
        """
        Wrap content in complete HTML document.

        Includes:
            - HTMX library (S12.2.1)
            - Common CSS and custom CSS
            - Navigation bar (optional)
            - Content
            - Common JavaScript and custom JavaScript
            - System status bar with memory/CPU/jobs (optional, default: True)

        Args:
            title: Page title (appears in browser tab)
            content: HTML content for page body
            custom_css: Additional CSS specific to this interface
            custom_js: Additional JavaScript specific to this interface
            include_navbar: Whether to include navigation bar (default: True)
            include_htmx: Whether to include HTMX library (default: True)
            include_status_bar: Whether to include system status bar (default: True)

        Returns:
            Complete HTML document string

        Example:
            return self.wrap_html(
                title="STAC Dashboard",
                content="<h1>Hello World</h1>",
                custom_css=".my-class { color: red; }",
                custom_js="console.log('Hello');"
            )
        """
        navbar_html = self._render_navbar() if include_navbar else ""
        htmx_script = f'<script src="https://unpkg.com/htmx.org@{self.HTMX_VERSION}"></script>' if include_htmx else ""
        status_bar_html = self.render_system_status_bar() if include_status_bar else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {htmx_script}
    <style>
        {self.COMMON_CSS}
        {self.HTMX_CSS}
        {custom_css}
    </style>
</head>
<body hx-headers='{{"Accept": "application/json"}}'>
    {navbar_html}
    {content}
    {status_bar_html}
    <script>
        {self.COMMON_JS}
        {self.HTMX_JS}
        {custom_js}
    </script>
</body>
</html>"""

    def _render_navbar(self) -> str:
        """
        Render navigation bar with links to all interfaces.

        Returns:
            HTML string for navigation bar

        Note:
            This is called automatically by wrap_html() unless
            include_navbar=False is specified.
        """
        return f"""
        <nav style="background: white; padding: 15px 30px; border-radius: 3px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px;
                    display: flex; justify-content: space-between; align-items: center;
                    border-bottom: 3px solid #0071BC;">
            <a href="/api/interface/home"
               style="font-size: 20px; font-weight: 700; color: #053657;
                      text-decoration: none; transition: color 0.2s;"
               onmouseover="this.style.color='#0071BC'"
               onmouseout="this.style.color='#053657'">
                Geospatial API v{__version__}
            </a>
            <div style="display: flex; gap: 20px;">
                <a href="/api/interface/gallery"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Gallery
                </a>
                <a href="/api/interface/health"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    System Status
                </a>
                <a href="/api/interface/storage"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Storage
                </a>
                <a href="/api/interface/pipeline"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Pipelines
                </a>
                <a href="/api/interface/h3"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    H3
                </a>
                <a href="/api/interface/queues"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Queues
                </a>
                <a href="/api/interface/stac"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    STAC
                </a>
                <a href="/api/interface/vector"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    OGC Features
                </a>
                <a href="/api/interface/docs"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    API Docs
                </a>
                <a href="/api/interface/swagger"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Swagger
                </a>
            </div>
        </nav>
        """

    # ========================================================================
    # COMPONENT HELPERS - Reusable HTML components (S12.1.3)
    # ========================================================================

    def render_header(
        self,
        title: str,
        subtitle: str = "",
        icon: str = "",
        actions: str = ""
    ) -> str:
        """
        Render a dashboard header with title, subtitle, and optional actions.

        Args:
            title: Main heading text
            subtitle: Optional description text
            icon: Optional emoji or icon prefix for title
            actions: Optional HTML for action buttons (right side)

        Returns:
            HTML string for dashboard header

        Example:
            header = self.render_header(
                title="Job Monitor",
                subtitle="Track ETL job execution",
                icon="⚙️",
                actions='<button class="btn btn-primary">Refresh</button>'
            )
        """
        title_text = f"{icon} {title}" if icon else title
        subtitle_html = f'<p class="subtitle">{subtitle}</p>' if subtitle else ""
        actions_html = f'<div class="header-actions">{actions}</div>' if actions else ""

        return f"""
        <header class="dashboard-header">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h1>{title_text}</h1>
                    {subtitle_html}
                </div>
                {actions_html}
            </div>
        </header>
        """

    def render_status_badge(self, status: str) -> str:
        """
        Render a status badge with appropriate color.

        Args:
            status: Status string (queued, pending, processing, completed, failed)

        Returns:
            HTML string for status badge

        Example:
            badge = self.render_status_badge("processing")
            # <span class="status-badge status-processing">processing</span>
        """
        safe_status = status.lower() if status else "unknown"
        return f'<span class="status-badge status-{safe_status}">{safe_status}</span>'

    def render_stat_card(
        self,
        label: str,
        value: str,
        highlight: bool = False,
        css_class: str = ""
    ) -> str:
        """
        Render a statistics card for dashboards.

        Args:
            label: Label text (e.g., "Total Jobs")
            value: Value to display (e.g., "1,234")
            highlight: Whether to highlight the value in blue
            css_class: Additional CSS class for the value

        Returns:
            HTML string for stat card

        Example:
            card = self.render_stat_card("Total Jobs", "1,234", highlight=True)
        """
        value_class = "stat-value"
        if highlight:
            value_class += " highlight"
        if css_class:
            value_class += f" {css_class}"

        return f"""
        <div class="stat-card">
            <div class="stat-label">{label}</div>
            <div class="{value_class}">{value}</div>
        </div>
        """

    def render_stats_banner(self, stats: list) -> str:
        """
        Render a stats banner with multiple stat items.

        Args:
            stats: List of dicts with 'label', 'value', 'id' (optional), 'highlight' (optional)

        Returns:
            HTML string for stats banner

        Example:
            banner = self.render_stats_banner([
                {'label': 'Total', 'value': '100', 'id': 'totalCount', 'highlight': True},
                {'label': 'Active', 'value': '25', 'id': 'activeCount'},
            ])
        """
        items = []
        for stat in stats:
            id_attr = f' id="{stat["id"]}"' if stat.get("id") else ""
            highlight = " highlight" if stat.get("highlight") else ""
            items.append(f"""
            <div class="stat-item">
                <span class="stat-label">{stat['label']}</span>
                <span class="stat-value{highlight}"{id_attr}>{stat['value']}</span>
            </div>
            """)

        return f"""
        <div class="stats-banner">
            {''.join(items)}
        </div>
        """

    def render_empty_state(
        self,
        icon: str = "📦",
        title: str = "No Data Found",
        message: str = "There's nothing to display here yet.",
        element_id: str = "empty-state"
    ) -> str:
        """
        Render an empty state placeholder.

        Args:
            icon: Emoji or icon to display
            title: Heading text
            message: Description text
            element_id: HTML id attribute for show/hide

        Returns:
            HTML string for empty state

        Example:
            empty = self.render_empty_state(
                icon="🔍",
                title="No Results",
                message="Try adjusting your search criteria"
            )
        """
        return f"""
        <div id="{element_id}" class="empty-state hidden">
            <div class="icon">{icon}</div>
            <h3>{title}</h3>
            <p>{message}</p>
        </div>
        """

    def render_error_state(
        self,
        message: str = "Something went wrong",
        retry_action: str = "loadData()",
        element_id: str = "error-state"
    ) -> str:
        """
        Render an error state with retry button.

        Args:
            message: Error message placeholder (can be updated via JS)
            retry_action: JavaScript function to call on retry
            element_id: HTML id attribute for show/hide

        Returns:
            HTML string for error state

        Example:
            error = self.render_error_state(
                retry_action="loadJobs()"
            )
        """
        return f"""
        <div id="{element_id}" class="error-state hidden">
            <div class="icon">⚠️</div>
            <h3>Error Loading Data</h3>
            <p class="error-message" id="error-message">{message}</p>
            <button class="btn btn-primary" onclick="{retry_action}">
                Retry
            </button>
        </div>
        """

    def render_loading_state(
        self,
        message: str = "Loading...",
        element_id: str = "loading-spinner"
    ) -> str:
        """
        Render a loading spinner with optional message.

        Args:
            message: Text to show below spinner
            element_id: HTML id attribute for show/hide

        Returns:
            HTML string for loading state

        Example:
            loading = self.render_loading_state("Loading jobs...")
        """
        return f"""
        <div id="{element_id}" class="spinner-container">
            <div class="spinner"></div>
            <div class="spinner-text">{message}</div>
        </div>
        """

    def render_card(
        self,
        title: str,
        description: str = "",
        footer: str = "",
        href: str = "",
        icon: str = "",
        featured: bool = False
    ) -> str:
        """
        Render a card component.

        Args:
            title: Card heading
            description: Card body text
            footer: Footer text (e.g., "View Details →")
            href: Optional link URL (makes card clickable)
            icon: Optional emoji/icon
            featured: Whether to apply featured styling

        Returns:
            HTML string for card

        Example:
            card = self.render_card(
                title="STAC Collections",
                description="Browse raster datasets",
                footer="View Collections →",
                href="/api/interface/stac",
                icon="📦"
            )
        """
        tag = "a" if href else "div"
        href_attr = f' href="{href}"' if href else ""
        featured_class = " featured" if featured else ""
        icon_html = f'<div class="card-icon">{icon}</div>' if icon else ""
        desc_html = f'<p class="card-description">{description}</p>' if description else ""
        footer_html = f'<div class="card-footer">{footer}</div>' if footer else ""

        return f"""
        <{tag}{href_attr} class="card{featured_class}">
            {icon_html}
            <h3 class="card-title">{title}</h3>
            {desc_html}
            {footer_html}
        </{tag}>
        """

    def render_filter_bar(self, filters: list, actions: str = "") -> str:
        """
        Render a filter bar with dropdowns and action buttons.

        Args:
            filters: List of filter dicts with 'id', 'label', 'options'
                     options is list of {'value': '', 'label': '', 'selected': bool}
            actions: HTML for action buttons

        Returns:
            HTML string for filter bar

        Example:
            filter_bar = self.render_filter_bar(
                filters=[
                    {
                        'id': 'statusFilter',
                        'label': 'Status',
                        'options': [
                            {'value': '', 'label': 'All Statuses', 'selected': True},
                            {'value': 'completed', 'label': 'Completed'},
                        ]
                    }
                ],
                actions='<button class="btn btn-primary">Refresh</button>'
            )
        """
        filter_groups = []
        for f in filters:
            options_html = []
            for opt in f.get('options', []):
                selected = ' selected' if opt.get('selected') else ''
                options_html.append(
                    f'<option value="{opt["value"]}"{selected}>{opt["label"]}</option>'
                )

            filter_groups.append(f"""
            <div class="filter-group">
                <label for="{f['id']}">{f['label']}</label>
                <select id="{f['id']}" class="filter-select">
                    {''.join(options_html)}
                </select>
            </div>
            """)

        actions_html = f'<div class="filter-actions">{actions}</div>' if actions else ""

        return f"""
        <div class="filter-bar">
            {''.join(filter_groups)}
            {actions_html}
        </div>
        """

    def render_table(
        self,
        columns: list,
        tbody_id: str = "table-body",
        table_id: str = "data-table"
    ) -> str:
        """
        Render a data table structure with headers.

        Args:
            columns: List of column header strings
            tbody_id: ID for tbody element (for JS population)
            table_id: ID for table element

        Returns:
            HTML string for table structure

        Example:
            table = self.render_table(
                columns=['ID', 'Name', 'Status', 'Created', 'Actions'],
                tbody_id='jobsTableBody'
            )
        """
        headers = ''.join([f'<th>{col}</th>' for col in columns])

        return f"""
        <table id="{table_id}" class="data-table">
            <thead>
                <tr>{headers}</tr>
            </thead>
            <tbody id="{tbody_id}">
                <!-- Rows populated by JavaScript -->
            </tbody>
        </table>
        """

    def render_search_input(
        self,
        placeholder: str = "Search...",
        element_id: str = "search-input",
        onkeyup: str = ""
    ) -> str:
        """
        Render a search input field.

        Args:
            placeholder: Placeholder text
            element_id: HTML id attribute
            onkeyup: JavaScript function to call on keyup

        Returns:
            HTML string for search input

        Example:
            search = self.render_search_input(
                placeholder="Search collections...",
                element_id="collection-search",
                onkeyup="filterCollections()"
            )
        """
        onkeyup_attr = f' onkeyup="{onkeyup}"' if onkeyup else ""

        return f"""
        <div class="controls">
            <input type="text"
                   id="{element_id}"
                   class="search-input"
                   placeholder="{placeholder}"
                   {onkeyup_attr}
            />
        </div>
        """

    def render_button(
        self,
        text: str,
        onclick: str = "",
        href: str = "",
        variant: str = "primary",
        size: str = "",
        element_id: str = "",
        icon: str = ""
    ) -> str:
        """
        Render a button or link styled as button.

        Args:
            text: Button text
            onclick: JavaScript onclick handler
            href: Link URL (renders as <a> instead of <button>)
            variant: 'primary', 'secondary', or custom class
            size: 'sm' for small button, '' for normal
            element_id: Optional HTML id
            icon: Optional emoji/icon prefix

        Returns:
            HTML string for button

        Example:
            btn = self.render_button(
                text="Submit",
                onclick="submitForm()",
                variant="primary",
                icon="🚀"
            )
        """
        classes = ["btn", f"btn-{variant}"]
        if size:
            classes.append(f"btn-{size}")

        class_str = ' '.join(classes)
        id_attr = f' id="{element_id}"' if element_id else ""
        icon_html = f"{icon} " if icon else ""

        if href:
            return f'<a href="{href}" class="{class_str}"{id_attr}>{icon_html}{text}</a>'
        else:
            onclick_attr = f' onclick="{onclick}"' if onclick else ""
            return f'<button class="{class_str}"{id_attr}{onclick_attr}>{icon_html}{text}</button>'

    def render_metadata_grid(self, items: list) -> str:
        """
        Render a metadata grid with label/value pairs.

        Args:
            items: List of dicts with 'label' and 'value' keys

        Returns:
            HTML string for metadata grid

        Example:
            meta = self.render_metadata_grid([
                {'label': 'Created', 'value': '2025-12-23'},
                {'label': 'Status', 'value': 'Active'},
            ])
        """
        items_html = []
        for item in items:
            items_html.append(f"""
            <div class="metadata-item">
                <div class="label">{item['label']}</div>
                <div class="value">{item['value']}</div>
            </div>
            """)

        return f"""
        <div class="metadata">
            {''.join(items_html)}
        </div>
        """

    # ========================================================================
    # HTMX COMPONENT HELPERS - Added S12.2.1
    # ========================================================================

    def hx_attrs(
        self,
        get: str = "",
        post: str = "",
        target: str = "",
        swap: str = "",
        trigger: str = "",
        indicator: str = "",
        include: str = "",
        vals: str = "",
        confirm: str = "",
        disabled_elt: str = "",
        push_url: bool = False
    ) -> str:
        """
        Generate HTMX attributes string for an element.

        Args:
            get: URL for hx-get request
            post: URL for hx-post request
            target: CSS selector for target element (hx-target)
            swap: Swap strategy (innerHTML, outerHTML, beforeend, etc.)
            trigger: Event trigger (click, change, load, etc.)
            indicator: CSS selector for loading indicator
            include: CSS selector for additional inputs to include
            vals: JSON values to include with request
            confirm: Confirmation message before request
            disabled_elt: Selector for elements to disable during request
            push_url: Whether to push URL to browser history

        Returns:
            String of HTMX attributes

        Example:
            attrs = self.hx_attrs(
                get="/api/data",
                target="#content",
                trigger="click",
                indicator="#spinner"
            )
            # Returns: 'hx-get="/api/data" hx-target="#content" hx-trigger="click" hx-indicator="#spinner"'
        """
        attrs = []

        if get:
            attrs.append(f'hx-get="{get}"')
        if post:
            attrs.append(f'hx-post="{post}"')
        if target:
            attrs.append(f'hx-target="{target}"')
        if swap:
            attrs.append(f'hx-swap="{swap}"')
        if trigger:
            attrs.append(f'hx-trigger="{trigger}"')
        if indicator:
            attrs.append(f'hx-indicator="{indicator}"')
        if include:
            attrs.append(f'hx-include="{include}"')
        if vals:
            attrs.append(f"hx-vals='{vals}'")
        if confirm:
            attrs.append(f'hx-confirm="{confirm}"')
        if disabled_elt:
            attrs.append(f'hx-disabled-elt="{disabled_elt}"')
        if push_url:
            attrs.append('hx-push-url="true"')

        return ' '.join(attrs)

    def render_hx_select(
        self,
        element_id: str,
        label: str,
        options: list,
        hx_get: str = "",
        hx_target: str = "",
        hx_trigger: str = "change",
        hx_indicator: str = "",
        name: str = ""
    ) -> str:
        """
        Render a select dropdown with HTMX attributes.

        Args:
            element_id: HTML id attribute
            label: Label text
            options: List of {'value': '', 'label': '', 'selected': bool}
            hx_get: URL to fetch on change
            hx_target: Target element for response
            hx_trigger: Trigger event (default: change)
            hx_indicator: Loading indicator selector
            name: Form field name (defaults to element_id)

        Returns:
            HTML string for HTMX-enabled select

        Example:
            select = self.render_hx_select(
                element_id="zone-select",
                label="Zone",
                options=[
                    {'value': '', 'label': 'Select Zone...', 'selected': True},
                    {'value': 'bronze', 'label': 'Bronze'},
                ],
                hx_get="/api/interface/storage/containers",
                hx_target="#container-select",
                hx_indicator="#zone-spinner"
            )
        """
        options_html = []
        for opt in options:
            selected = ' selected' if opt.get('selected') else ''
            options_html.append(
                f'<option value="{opt["value"]}"{selected}>{opt["label"]}</option>'
            )

        hx_attrs = self.hx_attrs(
            get=hx_get,
            target=hx_target,
            trigger=hx_trigger,
            indicator=hx_indicator
        )

        field_name = name or element_id

        return f"""
        <div class="filter-group">
            <label for="{element_id}">{label}</label>
            <select id="{element_id}" name="{field_name}" class="filter-select" {hx_attrs}>
                {''.join(options_html)}
            </select>
            <span class="htmx-indicator spinner-sm" id="{element_id}-spinner"></span>
        </div>
        """

    def render_hx_button(
        self,
        text: str,
        hx_get: str = "",
        hx_post: str = "",
        hx_target: str = "",
        hx_swap: str = "",
        hx_confirm: str = "",
        variant: str = "primary",
        element_id: str = "",
        icon: str = ""
    ) -> str:
        """
        Render a button with HTMX attributes.

        Args:
            text: Button text
            hx_get: URL for GET request
            hx_post: URL for POST request
            hx_target: Target element selector
            hx_swap: Swap strategy
            hx_confirm: Confirmation message
            variant: Button style variant
            element_id: HTML id
            icon: Optional icon prefix

        Returns:
            HTML string for HTMX button

        Example:
            btn = self.render_hx_button(
                text="Load Data",
                hx_get="/api/data",
                hx_target="#content",
                icon="🔄"
            )
        """
        hx_attrs = self.hx_attrs(
            get=hx_get,
            post=hx_post,
            target=hx_target,
            swap=hx_swap,
            confirm=hx_confirm
        )

        classes = f"btn btn-{variant}"
        id_attr = f' id="{element_id}"' if element_id else ""
        icon_html = f"{icon} " if icon else ""

        return f"""
        <button class="{classes}"{id_attr} {hx_attrs}>
            <span class="btn-text">{icon_html}{text}</span>
            <span class="htmx-indicator spinner-sm"></span>
        </button>
        """

    def render_hx_form(
        self,
        action: str,
        fields: str,
        submit_text: str = "Submit",
        hx_target: str = "#result",
        hx_swap: str = "innerHTML",
        element_id: str = "hx-form",
        method: str = "post"
    ) -> str:
        """
        Render a form with HTMX submission.

        Args:
            action: URL to submit to
            fields: HTML string of form fields
            submit_text: Submit button text
            hx_target: Target for response
            hx_swap: Swap strategy
            element_id: Form id
            method: HTTP method (post/get)

        Returns:
            HTML string for HTMX form

        Example:
            form = self.render_hx_form(
                action="/api/jobs/submit/process_vector",
                fields='''
                    <input type="text" name="table_name" placeholder="Table name" required>
                    <input type="text" name="blob_name" placeholder="Blob path" required>
                ''',
                submit_text="Submit Job",
                hx_target="#job-result"
            )
        """
        hx_attr = f'hx-post="{action}"' if method == "post" else f'hx-get="{action}"'

        return f"""
        <form id="{element_id}" {hx_attr} hx-target="{hx_target}" hx-swap="{hx_swap}">
            {fields}
            <div class="form-actions" style="margin-top: 20px;">
                <button type="submit" class="btn btn-primary">
                    <span class="btn-text">{submit_text}</span>
                    <span class="htmx-indicator spinner-sm"></span>
                </button>
            </div>
        </form>
        """

    def render_hx_polling(
        self,
        url: str,
        interval: str = "5s",
        target: str = "",
        element_id: str = "polling-container",
        initial_content: str = "Loading..."
    ) -> str:
        """
        Render a container that polls an endpoint at regular intervals.

        Args:
            url: URL to poll
            interval: Polling interval (e.g., "5s", "10s", "30s")
            target: Target element (defaults to self)
            element_id: Container id
            initial_content: Initial HTML content

        Returns:
            HTML string for polling container

        Example:
            poller = self.render_hx_polling(
                url="/api/jobs/status/abc123",
                interval="5s",
                element_id="job-status"
            )
        """
        target_attr = f'hx-target="{target}"' if target else ""

        return f"""
        <div id="{element_id}"
             hx-get="{url}"
             hx-trigger="load, every {interval}"
             {target_attr}
             hx-swap="innerHTML">
            {initial_content}
        </div>
        """

    # ========================================================================
    # SYSTEM STATUS BAR - Added 28 DEC 2025
    # ========================================================================

    def render_system_status_bar(self) -> str:
        """
        Render the system status bar with memory, CPU, and job stats.

        The status bar is a fixed bottom bar that displays:
        - Memory usage (% and meter)
        - CPU usage (% and meter)
        - Active jobs count
        - Pending jobs count
        - 24h completed/failed counts
        - Activity log toggle button

        The bar auto-refreshes via JavaScript every 15 seconds.

        Returns:
            HTML string for system status bar

        Example:
            # In wrap_html or content:
            status_bar = self.render_system_status_bar()
        """
        return """
        <div id="system-status-bar" class="system-status-bar">
            <div class="status-bar-left">
                <!-- Memory -->
                <div class="status-bar-item">
                    <span class="status-bar-label">MEM</span>
                    <span id="status-mem-value" class="status-bar-value good">--</span>
                    <div class="status-bar-meter">
                        <div id="status-mem-meter" class="status-bar-meter-fill good" style="width: 0%"></div>
                    </div>
                </div>

                <div class="status-bar-divider"></div>

                <!-- CPU -->
                <div class="status-bar-item">
                    <span class="status-bar-label">CPU</span>
                    <span id="status-cpu-value" class="status-bar-value good">--</span>
                    <div class="status-bar-meter">
                        <div id="status-cpu-meter" class="status-bar-meter-fill good" style="width: 0%"></div>
                    </div>
                </div>

                <div class="status-bar-divider"></div>

                <!-- Jobs Summary -->
                <div class="status-bar-item">
                    <span class="status-bar-label">ACTIVE</span>
                    <span id="status-jobs-active" class="status-bar-value">0</span>
                </div>

                <div class="status-bar-item">
                    <span class="status-bar-label">PENDING</span>
                    <span id="status-jobs-pending" class="status-bar-value">0</span>
                </div>

                <div class="status-bar-item">
                    <span class="status-bar-label">24H OK</span>
                    <span id="status-jobs-completed" class="status-bar-value good">0</span>
                </div>

                <div class="status-bar-item">
                    <span class="status-bar-label">24H FAIL</span>
                    <span id="status-jobs-failed" class="status-bar-value good">0</span>
                </div>
            </div>

            <div class="status-bar-right">
                <span id="status-timestamp" class="status-bar-value" style="color: #666;">--</span>
                <button class="activity-log-toggle" onclick="toggleActivityLog()">
                    📋 Activity Log
                </button>
            </div>
        </div>

        <!-- Activity Log Panel -->
        <div id="activity-log-panel" class="activity-log-panel">
            <div class="activity-log-header">
                <span class="activity-log-title">
                    📋 Activity Log
                </span>
                <button class="activity-log-close" onclick="toggleActivityLog()">✕</button>
            </div>
            <div id="activity-log-content" class="activity-log-content">
                <div class="activity-log-empty">No activity yet</div>
            </div>
        </div>
        """
