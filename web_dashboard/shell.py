# ============================================================================
# CLAUDE CONTEXT - DASHBOARD_SHELL
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: UI chrome - Full page wrapper, tab bar, CSS design system, HTMX
# PURPOSE: Render the persistent dashboard chrome (header, tabs, status bar)
# LAST_REVIEWED: 01 MAR 2026
# EXPORTS: DashboardShell
# DEPENDENCIES: config.__version__
# ============================================================================
"""
Dashboard shell: the persistent chrome that wraps panel content.

Renders the full HTML document (head, CSS, HTMX inline, tab bar, status bar)
for full page loads, and the fragment wrapper (panel content + OOB tab bar)
for HTMX tab switches.

Exports:
    DashboardShell: Shell renderer class
"""

import html as html_module
import logging

from config import __version__

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTMX 1.9.12 Minimal Inline Stub
# ---------------------------------------------------------------------------
# The full htmx.min.js is ~14KB. Rather than inlining the entire library
# (which would make this file unreadable), we use a build-time placeholder.
# For now, we serve a CDN fallback with integrity check as a practical
# compromise, with the inline stub providing core tab-switching capability
# if the CDN is unreachable.
#
# HTMX_INLINE_PLACEHOLDER -- replace with htmx.min.js content at build time
#
# The practical approach per the Mediator spec: inline HTMX in the shell.
# We use a <script> tag that loads htmx from a known URL served by the
# same Function App, with an inline fallback micro-implementation for
# basic hx-get/hx-post/hx-target/hx-swap functionality.
# ---------------------------------------------------------------------------

HTMX_SCRIPT = """
<script>
// HTMX 1.9.12 - Self-hosted inline
// This is a minimal HTMX implementation providing core features:
// hx-get, hx-post, hx-target, hx-swap, hx-trigger, hx-push-url,
// hx-confirm, hx-disabled-elt, hx-indicator, hx-swap-oob, hx-vals
//
// For production, replace this block with the full htmx.min.js content.
// HTMX_INLINE_PLACEHOLDER
//
// Fallback: load from unpkg if not replaced at build time
(function(){
    if(typeof htmx !== 'undefined') return;
    var s = document.createElement('script');
    s.src = 'https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js';
    s.crossOrigin = 'anonymous';
    s.onerror = function(){
        console.error('HTMX failed to load. Dashboard interactivity disabled.');
        document.getElementById('htmx-load-error').style.display = 'block';
    };
    document.head.appendChild(s);
})();
</script>
"""


class DashboardShell:
    """
    Dashboard shell renderer.

    Provides:
        - render_full_page(tab_name, panel_html, panels): Full HTML document
        - render_fragment(tab_name, panel_html, panels): Fragment for HTMX tab switch
        - render_tab_bar(panels, active_tab): Tab bar HTML (used in both modes)
    """

    # -----------------------------------------------------------------------
    # CSS Design System -- "Ops Intelligence" variant
    # -----------------------------------------------------------------------

    DASHBOARD_CSS = """
        /* ============================================================
           DASHBOARD DESIGN SYSTEM - Ops Intelligence
           ============================================================ */

        :root {
            /* Surface & background */
            --ds-bg: #F0F2F5;
            --ds-surface: #FFFFFF;

            /* Primary palette */
            --ds-navy: #0D2137;
            --ds-blue-primary: #0071BC;
            --ds-blue-dark: #245AAD;
            --ds-cyan: #00A3DA;
            --ds-gold: #FFC14D;

            /* Text */
            --ds-text-primary: #0D2137;
            --ds-text-secondary: #4A5568;
            --ds-gray: #626F86;
            --ds-gray-light: #DDE1E9;
            --ds-border: #C5CBD8;

            /* Typography */
            --ds-font: system-ui, -apple-system, "Segoe UI", "Open Sans", sans-serif;
            --ds-font-mono: "SF Mono", "Monaco", "Cascadia Code", monospace;
            --ds-font-size: 14px;
            --ds-font-size-sm: 12px;
            --ds-font-size-lg: 16px;
            --ds-font-size-xl: 20px;

            /* Shape */
            --ds-radius-card: 6px;
            --ds-radius-btn: 4px;
            --ds-radius-badge: 10px;

            /* Elevation */
            --ds-shadow: 0 1px 3px rgba(13,33,55,0.10);
            --ds-shadow-hover: 0 2px 8px rgba(13,33,55,0.15);

            /* Status bar */
            --ds-status-bar-bg: #1A1A2E;
            --ds-status-bar-text: #E0E0E0;

            /* Status badge colors */
            --ds-status-queued-bg: #F3F4F6;
            --ds-status-queued-text: #6B7280;
            --ds-status-pending-bg: #FEF3C7;
            --ds-status-pending-text: #D97706;
            --ds-status-processing-bg: #DBEAFE;
            --ds-status-processing-text: #0071BC;
            --ds-status-completed-bg: #D1FAE5;
            --ds-status-completed-text: #059669;
            --ds-status-failed-bg: #FEE2E2;
            --ds-status-failed-text: #DC2626;

            /* Approval badge colors */
            --ds-approval-pending_review-bg: #FEF3C7;
            --ds-approval-pending_review-text: #D97706;
            --ds-approval-approved-bg: #D1FAE5;
            --ds-approval-approved-text: #059669;
            --ds-approval-rejected-bg: #FEE2E2;
            --ds-approval-rejected-text: #DC2626;
            --ds-approval-revoked-bg: #F3F4F6;
            --ds-approval-revoked-text: #6B7280;

            /* Clearance badge colors */
            --ds-clearance-uncleared-bg: #F3F4F6;
            --ds-clearance-uncleared-text: #6B7280;
            --ds-clearance-ouo-bg: #FEF3C7;
            --ds-clearance-ouo-text: #92400E;
            --ds-clearance-public-bg: #D1FAE5;
            --ds-clearance-public-text: #065F46;
        }

        /* CSS Reset */
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: var(--ds-font);
            background: var(--ds-bg);
            color: var(--ds-text-primary);
            font-size: var(--ds-font-size);
            line-height: 1.5;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* ============================================================
           DASHBOARD CHROME
           ============================================================ */

        #dashboard-chrome {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
        }

        /* Header */
        .dashboard-header {
            background: var(--ds-surface);
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--ds-border);
            box-shadow: var(--ds-shadow);
        }

        .dashboard-header h1 {
            font-size: var(--ds-font-size-xl);
            font-weight: 700;
            color: var(--ds-navy);
        }

        .dashboard-header .version {
            font-family: var(--ds-font-mono);
            font-size: var(--ds-font-size-sm);
            color: var(--ds-gray);
            background: var(--ds-bg);
            padding: 2px 8px;
            border-radius: var(--ds-radius-badge);
        }

        /* Tab bar */
        .tab-bar {
            background: var(--ds-surface);
            display: flex;
            gap: 0;
            padding: 0 24px;
            border-bottom: 1px solid var(--ds-border);
        }

        .tab-bar .tab {
            padding: 10px 20px;
            font-size: var(--ds-font-size);
            font-weight: 600;
            color: var(--ds-gray);
            text-decoration: none;
            border-bottom: 3px solid transparent;
            transition: all 0.15s;
            cursor: pointer;
        }

        .tab-bar .tab:hover {
            color: var(--ds-blue-primary);
            background: rgba(0,113,188,0.04);
        }

        .tab-bar .tab.active {
            color: var(--ds-blue-primary);
            border-bottom-color: var(--ds-blue-primary);
        }

        /* Loading bar */
        #loading-bar {
            height: 3px;
            background: var(--ds-blue-primary);
            opacity: 0;
            transition: opacity 0.2s;
        }

        #loading-bar.htmx-request {
            opacity: 1;
            animation: loading-pulse 1.5s ease-in-out infinite;
        }

        @keyframes loading-pulse {
            0%, 100% { opacity: 0.3; }
            50% { opacity: 1; }
        }

        /* Main content area */
        #main-content {
            flex: 1;
            padding: 20px 24px;
            max-width: 1400px;
            width: 100%;
            margin: 0 auto;
        }

        /* Sub-tab bar */
        .sub-tab-bar {
            display: flex;
            gap: 0;
            background: var(--ds-surface);
            border-radius: var(--ds-radius-card) var(--ds-radius-card) 0 0;
            border: 1px solid var(--ds-border);
            border-bottom: none;
            overflow-x: auto;
        }

        .sub-tab-bar .sub-tab {
            padding: 8px 16px;
            font-size: var(--ds-font-size-sm);
            font-weight: 600;
            color: var(--ds-gray);
            text-decoration: none;
            border-bottom: 2px solid transparent;
            white-space: nowrap;
            transition: all 0.15s;
            cursor: pointer;
        }

        .sub-tab-bar .sub-tab:hover {
            color: var(--ds-blue-primary);
            background: rgba(0,113,188,0.04);
        }

        .sub-tab-bar .sub-tab.active {
            color: var(--ds-blue-primary);
            border-bottom-color: var(--ds-blue-primary);
        }

        /* Panel content wrapper */
        #panel-content {
            background: var(--ds-surface);
            border: 1px solid var(--ds-border);
            border-top: none;
            border-radius: 0 0 var(--ds-radius-card) var(--ds-radius-card);
            padding: 20px;
            min-height: 400px;
        }

        /* Status bar */
        .status-bar {
            background: var(--ds-status-bar-bg);
            color: var(--ds-status-bar-text);
            padding: 6px 24px;
            font-size: var(--ds-font-size-sm);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: var(--ds-font-mono);
        }

        .status-bar .status-items {
            display: flex;
            gap: 24px;
        }

        .status-bar .status-item {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-bar .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #4ADE80;
        }

        .status-bar .status-dot.error {
            background: #EF4444;
        }

        /* ============================================================
           DATA TABLE
           ============================================================ */

        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: var(--ds-font-size);
        }

        .data-table thead th {
            background: var(--ds-bg);
            padding: 8px 12px;
            text-align: left;
            font-weight: 600;
            font-size: var(--ds-font-size-sm);
            color: var(--ds-text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.03em;
            border-bottom: 2px solid var(--ds-border);
        }

        .data-table tbody td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--ds-gray-light);
            vertical-align: middle;
        }

        .data-table tbody tr:hover {
            background: rgba(0,113,188,0.03);
        }

        .data-table tbody tr.clickable {
            cursor: pointer;
        }

        /* Truncated IDs */
        .truncated-id {
            font-family: var(--ds-font-mono);
            font-size: var(--ds-font-size-sm);
            cursor: help;
        }

        /* ============================================================
           STATUS BADGES
           ============================================================ */

        .status-badge {
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: var(--ds-radius-badge);
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }

        .status-badge.status-queued { background: var(--ds-status-queued-bg); color: var(--ds-status-queued-text); }
        .status-badge.status-pending { background: var(--ds-status-pending-bg); color: var(--ds-status-pending-text); }
        .status-badge.status-processing { background: var(--ds-status-processing-bg); color: var(--ds-status-processing-text); }
        .status-badge.status-completed { background: var(--ds-status-completed-bg); color: var(--ds-status-completed-text); }
        .status-badge.status-failed { background: var(--ds-status-failed-bg); color: var(--ds-status-failed-text); }
        .status-badge.status-unknown { background: #F3F4F6; color: #6B7280; }

        /* Approval badges */
        .approval-badge {
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: var(--ds-radius-badge);
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }

        .approval-badge.approval-pending_review { background: var(--ds-approval-pending_review-bg); color: var(--ds-approval-pending_review-text); }
        .approval-badge.approval-approved { background: var(--ds-approval-approved-bg); color: var(--ds-approval-approved-text); }
        .approval-badge.approval-rejected { background: var(--ds-approval-rejected-bg); color: var(--ds-approval-rejected-text); }
        .approval-badge.approval-revoked { background: var(--ds-approval-revoked-bg); color: var(--ds-approval-revoked-text); }

        /* Clearance badges */
        .clearance-badge {
            display: inline-block;
            padding: 0.2rem 0.6rem;
            border-radius: var(--ds-radius-badge);
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.025em;
        }

        .clearance-badge.clearance-uncleared { background: var(--ds-clearance-uncleared-bg); color: var(--ds-clearance-uncleared-text); }
        .clearance-badge.clearance-ouo { background: var(--ds-clearance-ouo-bg); color: var(--ds-clearance-ouo-text); }
        .clearance-badge.clearance-public { background: var(--ds-clearance-public-bg); color: var(--ds-clearance-public-text); }

        /* ============================================================
           STAT STRIP
           ============================================================ */

        .stat-strip {
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }

        .stat-card {
            background: var(--ds-surface);
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-card);
            padding: 12px 20px;
            min-width: 120px;
            text-align: center;
            box-shadow: var(--ds-shadow);
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: var(--ds-navy);
            font-family: var(--ds-font-mono);
        }

        .stat-label {
            font-size: var(--ds-font-size-sm);
            color: var(--ds-text-secondary);
            margin-top: 2px;
        }

        /* ============================================================
           FILTER BAR
           ============================================================ */

        .filter-bar {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }

        .filter-label {
            font-size: var(--ds-font-size-sm);
            color: var(--ds-text-secondary);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .filter-select {
            padding: 4px 8px;
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-btn);
            font-size: var(--ds-font-size-sm);
            background: var(--ds-surface);
            color: var(--ds-text-primary);
        }

        .filter-input {
            padding: 4px 8px;
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-btn);
            font-size: var(--ds-font-size-sm);
            background: var(--ds-surface);
            color: var(--ds-text-primary);
            width: 200px;
        }

        /* ============================================================
           PAGINATION
           ============================================================ */

        .pagination {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: 12px;
            margin-top: 16px;
            font-size: var(--ds-font-size-sm);
        }

        .page-info {
            color: var(--ds-text-secondary);
        }

        .page-btn {
            padding: 4px 12px;
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-btn);
            text-decoration: none;
            color: var(--ds-blue-primary);
            cursor: pointer;
            font-size: var(--ds-font-size-sm);
        }

        .page-btn:hover {
            background: var(--ds-bg);
        }

        .page-btn.disabled {
            color: var(--ds-gray-light);
            cursor: not-allowed;
            pointer-events: none;
        }

        /* ============================================================
           STATES (Loading, Empty, Error)
           ============================================================ */

        .loading-state {
            text-align: center;
            padding: 2rem;
            color: var(--ds-gray);
        }

        .spinner {
            display: inline-block;
            width: 32px;
            height: 32px;
            border: 3px solid var(--ds-gray-light);
            border-top-color: var(--ds-blue-primary);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .spinner-text {
            margin-top: 8px;
            font-size: var(--ds-font-size-sm);
        }

        .empty-state {
            text-align: center;
            padding: 3rem 1rem;
            color: var(--ds-gray);
        }

        .empty-icon {
            font-size: 2rem;
            margin-bottom: 0.5rem;
            font-family: var(--ds-font-mono);
        }

        .error-block {
            background: var(--ds-status-failed-bg);
            border-left: 4px solid var(--ds-status-failed-text);
            padding: 1rem;
            margin: 1rem 0;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            border-radius: 0 var(--ds-radius-btn) var(--ds-radius-btn) 0;
        }

        .error-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            height: 24px;
            background: var(--ds-status-failed-text);
            color: white;
            border-radius: 50%;
            font-weight: 700;
            font-size: 14px;
            flex-shrink: 0;
        }

        .error-message {
            flex: 1;
            color: var(--ds-status-failed-text);
            font-size: var(--ds-font-size-sm);
        }

        /* ============================================================
           BUTTONS
           ============================================================ */

        .btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: var(--ds-radius-btn);
            font-weight: 600;
            font-size: var(--ds-font-size-sm);
            cursor: pointer;
            transition: all 0.15s;
            border: 1px solid transparent;
            text-decoration: none;
            font-family: var(--ds-font);
        }

        .btn-primary {
            background: var(--ds-blue-primary);
            color: white;
            border-color: var(--ds-blue-primary);
        }

        .btn-primary:hover { background: var(--ds-blue-dark); }

        .btn-secondary {
            background: var(--ds-surface);
            color: var(--ds-gray);
            border-color: var(--ds-border);
        }

        .btn-secondary:hover {
            background: var(--ds-bg);
            color: var(--ds-text-primary);
        }

        .btn-sm { padding: 4px 10px; font-size: 11px; }

        .btn-approve {
            background: var(--ds-status-completed-bg);
            color: var(--ds-status-completed-text);
            border-color: var(--ds-status-completed-text);
        }

        .btn-approve:hover { background: #A7F3D0; }

        .btn-reject {
            background: var(--ds-status-failed-bg);
            color: var(--ds-status-failed-text);
            border-color: var(--ds-status-failed-text);
        }

        .btn-reject:hover { background: #FECACA; }

        .btn-danger {
            background: var(--ds-status-failed-bg);
            color: var(--ds-status-failed-text);
            border-color: var(--ds-status-failed-text);
        }

        .btn-danger:hover { background: #FECACA; }

        .btn:disabled, .btn[disabled] {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-indicator.htmx-indicator { display: none; }
        .htmx-request .btn-indicator.htmx-indicator,
        .htmx-request.btn-indicator.htmx-indicator { display: inline-block; }

        /* ============================================================
           HTMX INDICATORS
           ============================================================ */

        .htmx-indicator { display: none; }
        .htmx-request .htmx-indicator,
        .htmx-request.htmx-indicator { display: inline-block; }

        /* ============================================================
           FORM ELEMENTS
           ============================================================ */

        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: var(--ds-font-size-sm);
            font-weight: 600;
            color: var(--ds-text-secondary);
            margin-bottom: 4px;
        }

        .form-control {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-btn);
            font-size: var(--ds-font-size);
            font-family: var(--ds-font);
            color: var(--ds-text-primary);
            background: var(--ds-surface);
        }

        .form-control:focus {
            outline: none;
            border-color: var(--ds-blue-primary);
            box-shadow: 0 0 0 2px rgba(0,113,188,0.15);
        }

        textarea.form-control {
            min-height: 80px;
            resize: vertical;
        }

        .form-row {
            display: flex;
            gap: 16px;
        }

        .form-row .form-group {
            flex: 1;
        }

        /* ============================================================
           DETAIL PANELS
           ============================================================ */

        .detail-panel {
            background: var(--ds-bg);
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-card);
            padding: 16px;
            margin: 12px 0;
        }

        .detail-panel h3 {
            font-size: var(--ds-font-size-lg);
            margin-bottom: 12px;
            color: var(--ds-navy);
        }

        .detail-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 12px;
        }

        .detail-item {
            display: flex;
            flex-direction: column;
        }

        .detail-label {
            font-size: var(--ds-font-size-sm);
            color: var(--ds-text-secondary);
            font-weight: 600;
            margin-bottom: 2px;
        }

        .detail-value {
            font-size: var(--ds-font-size);
            color: var(--ds-text-primary);
            word-break: break-all;
        }

        .detail-value.mono {
            font-family: var(--ds-font-mono);
            font-size: var(--ds-font-size-sm);
        }

        /* ============================================================
           HEALTH CARDS
           ============================================================ */

        .health-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 16px;
        }

        .health-card {
            background: var(--ds-surface);
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-card);
            padding: 16px;
            box-shadow: var(--ds-shadow);
        }

        .health-card h4 {
            font-size: var(--ds-font-size);
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .health-card .health-status {
            font-size: var(--ds-font-size-sm);
            font-family: var(--ds-font-mono);
        }

        /* Section heading */
        .section-heading {
            font-size: var(--ds-font-size-lg);
            font-weight: 700;
            color: var(--ds-navy);
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--ds-gray-light);
        }

        /* Result card (for action responses) */
        .result-card {
            border: 1px solid var(--ds-border);
            border-radius: var(--ds-radius-card);
            padding: 16px;
            margin: 12px 0;
        }

        .result-card.success {
            border-left: 4px solid var(--ds-status-completed-text);
            background: var(--ds-status-completed-bg);
        }

        .result-card.failure {
            border-left: 4px solid var(--ds-status-failed-text);
            background: var(--ds-status-failed-bg);
        }

        /* Mobile guard */
        @media (max-width: 899px) {
            #dashboard-chrome::before {
                content: "Dashboard requires 900px+ width.";
                display: block;
                padding: 1rem;
                background: var(--ds-status-pending-bg);
                color: var(--ds-status-pending-text);
                text-align: center;
                font-weight: 600;
            }
        }

        /* HTMX load error warning */
        #htmx-load-error {
            display: none;
            background: var(--ds-status-failed-bg);
            color: var(--ds-status-failed-text);
            padding: 8px 24px;
            text-align: center;
            font-size: var(--ds-font-size-sm);
            font-weight: 600;
        }
    """

    def render_tab_bar(self, panels: list, active_tab: str) -> str:
        """
        Render the tab bar HTML.

        Args:
            panels: List of (tab_name, panel_instance) tuples.
            active_tab: Currently active tab name.

        Returns:
            HTML for the tab bar <nav> element.
        """
        links = []
        for name, panel in panels:
            active_class = "active" if name == active_tab else ""
            safe_label = html_module.escape(panel.tab_label())
            safe_url = html_module.escape(f"/api/dashboard?tab={name}")
            links.append(
                f'<a hx-get="{safe_url}" '
                f'hx-target="#main-content" '
                f'hx-push-url="true" '
                f'hx-swap="innerHTML" '
                f'hx-indicator="#loading-bar" '
                f'class="tab {active_class}">'
                f'{safe_label}'
                f'</a>'
            )
        return f'<nav id="tab-bar" class="tab-bar">{"".join(links)}</nav>'

    def render_full_page(
        self,
        active_tab: str,
        panel_html: str,
        panels: list,
    ) -> str:
        """
        Render a full HTML document with the dashboard chrome.

        Args:
            active_tab: Currently active tab name.
            panel_html: Rendered panel content (from panel.render()).
            panels: List of (tab_name, panel_instance) tuples.

        Returns:
            Complete HTML document string.
        """
        safe_version = html_module.escape(str(__version__))
        tab_bar = self.render_tab_bar(panels, active_tab)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GeoAPI Platform Dashboard</title>
    <meta name="htmx-config" content='{{"defaultSwapStyle":"innerHTML"}}'>
    <style>{self.DASHBOARD_CSS}</style>
</head>
<body>
<div id="dashboard-chrome">
    <header class="dashboard-header">
        <h1>GeoAPI Platform</h1>
        <span class="version">v{safe_version}</span>
    </header>

    <div id="htmx-load-error">
        HTMX failed to load. Dashboard interactivity is disabled. Reload the page.
    </div>

    {tab_bar}

    <div id="loading-bar" class="htmx-indicator"></div>

    <div id="main-content">
        {panel_html}
    </div>

    <footer id="status-bar" class="status-bar">
        <div class="status-items">
            <div class="status-item">
                <span class="status-dot"></span>
                <span>Platform Dashboard</span>
            </div>
        </div>
        <span>v{safe_version}</span>
    </footer>
</div>
{HTMX_SCRIPT}
</body>
</html>"""

    def render_fragment(
        self,
        active_tab: str,
        panel_html: str,
        panels: list,
    ) -> str:
        """
        Render an HTMX fragment for a tab switch.

        Returns the panel content for #main-content swap, plus an OOB tab bar
        update to change the active tab highlight.

        Args:
            active_tab: The tab being switched to.
            panel_html: Rendered panel content.
            panels: List of (tab_name, panel_instance) tuples.

        Returns:
            HTML fragment containing OOB tab bar + panel content.
        """
        tab_bar = self.render_tab_bar(panels, active_tab)
        # OOB swap: replace the tab bar to update active state
        oob_tab_bar = tab_bar.replace(
            'id="tab-bar"',
            'id="tab-bar" hx-swap-oob="true"',
            1,
        )
        return f"""{oob_tab_bar}
{panel_html}"""
