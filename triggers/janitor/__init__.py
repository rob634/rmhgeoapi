# ============================================================================
# JANITOR TRIGGERS PACKAGE
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger layer - Package init for system maintenance triggers
# PURPOSE: Export SystemGuardian trigger and HTTP handlers
# LAST_REVIEWED: 14 MAR 2026
# EXPORTS: system_guardian_handler, janitor_*_handler
# ============================================================================
"""
Janitor Triggers Package.

SystemGuardian timer trigger and HTTP triggers for maintenance operations.

Exports:
    system_guardian_handler: Timer trigger for 4-phase sweep (replaces
        task_watchdog, job_health, orphan_detector)
    janitor_run_handler: HTTP trigger for manual sweep/maintenance
    janitor_status_handler: HTTP trigger for status
    janitor_history_handler: HTTP trigger for history
"""

from .system_guardian import system_guardian_handler

# HTTP trigger handlers
from .http_triggers import (
    janitor_run_handler,
    janitor_status_handler,
    janitor_history_handler
)

__all__ = [
    'system_guardian_handler',
    'janitor_run_handler',
    'janitor_status_handler',
    'janitor_history_handler'
]
