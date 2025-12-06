"""
Janitor Triggers Package.

Timer and HTTP triggers for system maintenance operations.

Exports:
    task_watchdog_handler: Timer trigger for detecting stale tasks
    job_health_handler: Timer trigger for detecting jobs with failed tasks
    orphan_detector_handler: Timer trigger for detecting orphaned records
    janitor_run_handler: HTTP trigger for manual janitor execution
    janitor_status_handler: HTTP trigger for janitor status
    janitor_history_handler: HTTP trigger for janitor run history
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
