# ============================================================================
# TIMER TRIGGERS MODULE
# ============================================================================
# STATUS: Trigger layer - Timer-based scheduled triggers
# PURPOSE: Centralized timer triggers using Azure Functions Blueprint
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 3 Timer Trigger Extraction
# ============================================================================
"""
Timer Triggers Module.

Provides a Blueprint with all timer triggers for scheduled system operations:
- Janitor timers: task_watchdog, job_health, orphan_detector
- Geo maintenance: geo_orphan_check, metadata_consistency, geo_integrity_check
- Scheduled operations: curated_dataset_scheduler
- System monitoring: system_snapshot, log_cleanup, external_service_health

This module extracts ~250 lines of timer trigger code from function_app.py
into a reusable Blueprint pattern.

Usage in function_app.py:
    from triggers.timers import timer_bp
    app.register_blueprint(timer_bp)

Exports:
    timer_bp: Azure Functions Blueprint with all timer triggers
"""

from .timer_bp import bp as timer_bp

__all__ = ['timer_bp']
