# ============================================================================
# CLAUDE CONTEXT - JANITOR TRIGGERS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Package - Janitor timer and HTTP triggers
# PURPOSE: Timer and HTTP triggers for system maintenance (stale tasks, failed jobs, orphans)
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: Timer handlers + HTTP handlers for manual triggering
# DEPENDENCIES: services.janitor_service
# ============================================================================

"""
Janitor Triggers Package

Provides both timer-based AND HTTP-based maintenance operations:

Timer Triggers (automatic):
1. Task Watchdog (every 5 min): Detect stale PROCESSING tasks
2. Job Health Monitor (every 10 min): Detect jobs with failed tasks
3. Orphan Detector (every 15 min): Detect orphaned/zombie records

HTTP Triggers (manual):
- POST /api/admin/janitor/run?type={type} - Manually trigger janitor
- GET /api/admin/janitor/status - Get janitor config and recent stats
- GET /api/admin/janitor/history - Get janitor run history

These triggers run independently of CoreMachine to avoid circular dependencies.
A janitor that uses CoreMachine cannot clean up stuck CoreMachine jobs.
"""

# Timer trigger handlers
from .task_watchdog import task_watchdog_handler
from .job_health import job_health_handler
from .orphan_detector import orphan_detector_handler

# HTTP trigger handlers
from .http_triggers import (
    janitor_run_handler,
    janitor_status_handler,
    janitor_history_handler
)

__all__ = [
    # Timer handlers
    'task_watchdog_handler',
    'job_health_handler',
    'orphan_detector_handler',
    # HTTP handlers
    'janitor_run_handler',
    'janitor_status_handler',
    'janitor_history_handler'
]
