# ============================================================================
# CLAUDE CONTEXT - JANITOR TRIGGERS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Package - Janitor timer triggers
# PURPOSE: Timer triggers for system maintenance (stale tasks, failed jobs, orphans)
# LAST_REVIEWED: 21 NOV 2025
# EXPORTS: task_watchdog_handler, job_health_handler, orphan_detector_handler
# DEPENDENCIES: services.janitor_service
# ============================================================================

"""
Janitor Timer Triggers Package

Provides timer-based maintenance operations for the CoreMachine system:

1. Task Watchdog (every 5 min): Detect stale PROCESSING tasks
2. Job Health Monitor (every 10 min): Detect jobs with failed tasks
3. Orphan Detector (every 15 min): Detect orphaned/zombie records

These triggers run independently of CoreMachine to avoid circular dependencies.
A janitor that uses CoreMachine cannot clean up stuck CoreMachine jobs.
"""

from .task_watchdog import task_watchdog_handler
from .job_health import job_health_handler
from .orphan_detector import orphan_detector_handler

__all__ = [
    'task_watchdog_handler',
    'job_health_handler',
    'orphan_detector_handler'
]
