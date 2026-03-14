# ============================================================================
# TIMER TRIGGERS BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Timer-based scheduled triggers
# PURPOSE: Azure Functions Blueprint with all timer triggers
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 3 Timer Trigger Extraction
# ============================================================================
"""
Timer Triggers Blueprint.

Contains all scheduled timer triggers for system maintenance and monitoring.
Register this blueprint in function_app.py to enable all timers.

Timer Schedule Overview:
    - system_guardian_sweep: Every 5 minutes (4-phase distributed recovery)
    - geo_orphan_check_timer: Every 6 hours
    - metadata_consistency_timer: 03:00, 09:00, 15:00, 21:00 UTC
    - geo_integrity_check_timer: 02:00, 08:00, 14:00, 20:00 UTC
    - curated_dataset_scheduler: Daily at 2 AM UTC
    - system_snapshot_timer: Every hour on the hour
    - log_cleanup_timer: Daily at 3 AM UTC
    - external_service_health_timer: Every hour on the hour

Usage:
    from triggers.timers import timer_bp
    app.register_blueprint(timer_bp)
"""

import azure.functions as func

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.TRIGGER, "TimerBlueprint")

# Create Blueprint
bp = func.Blueprint()


# ============================================================================
# SYSTEM GUARDIAN (14 MAR 2026 - replaces 3 janitor timers)
# ============================================================================
# Single timer runs 4 ordered phases: task recovery, stage recovery,
# job recovery, consistency. Replaces task_watchdog + job_health +
# orphan_detector.
#
# Configuration via environment variables:
# - GUARDIAN_ENABLED: true/false (default: true)
# - GUARDIAN_PROCESSING_TASK_TIMEOUT_MINUTES: 30
# - GUARDIAN_DOCKER_TASK_TIMEOUT_MINUTES: 180
# - GUARDIAN_ANCIENT_JOB_TIMEOUT_MINUTES: 360
# - GUARDIAN_MAX_TASK_RETRIES: 3
# ============================================================================

@bp.timer_trigger(
    schedule="0 */5 * * * *",
    arg_name="timer",
    run_on_startup=False
)
def system_guardian_sweep(timer: func.TimerRequest) -> None:
    """
    SystemGuardian — distributed systems recovery sweep.

    Runs 4 ordered phases: task recovery → stage recovery → job recovery → consistency.
    Replaces task_watchdog + job_health + orphan_detector.

    Schedule: Every 5 minutes
    """
    from triggers.janitor import system_guardian_handler
    system_guardian_handler(timer)


# ============================================================================
# GEO MAINTENANCE TIMERS (09 JAN 2026 - F7.10)
# ============================================================================

@bp.timer_trigger(
    schedule="0 0 */6 * * *",  # Every 6 hours at minute 0
    arg_name="timer",
    run_on_startup=False
)
def geo_orphan_check_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check for geo schema orphans every 6 hours.

    Detects:
    1. Orphaned Tables: Tables in geo schema without metadata records
    2. Orphaned Metadata: Metadata records for non-existent tables

    Detection only - does NOT auto-delete. Logs findings to Application Insights.

    Schedule: Every 6 hours - low overhead monitoring for data integrity

    Handler: triggers/admin/geo_orphan_timer.py (extracted 09 JAN 2026)
    """
    from triggers.admin.geo_orphan_timer import geo_orphan_timer_handler
    geo_orphan_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 3,9,15,21 * * *",  # Every 6 hours at 03:00, 09:00, 15:00, 21:00 UTC
    arg_name="timer",
    run_on_startup=False
)
def metadata_consistency_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Unified metadata consistency check every 6 hours.

    Tier 1 Checks (DB + blob HEAD):
    - STAC <-> Metadata cross-reference (vector and raster)
    - Broken backlinks (metadata -> STAC items)
    - Dataset refs FK integrity
    - Raster blob existence (HEAD only)

    Detection only - does NOT auto-delete. Logs findings to Application Insights.

    Schedule: Every 6 hours, offset from geo_orphan by 3 hours to spread load.

    Handler: triggers/admin/metadata_consistency_timer.py
    """
    from triggers.admin.metadata_consistency_timer import metadata_consistency_timer_handler
    metadata_consistency_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 2,8,14,20 * * *",  # Every 6 hours at 02:00, 08:00, 14:00, 20:00 UTC
    arg_name="timer",
    run_on_startup=False
)
def geo_integrity_check_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check geo schema table integrity every 6 hours.

    Detects tables incompatible with TiPG/OGC Features:
    1. Untyped geometry columns (GEOMETRY without POLYGON, POINT, etc.)
    2. Missing SRID (srid = 0 or NULL)
    3. Missing spatial indexes
    4. Tables not registered in geometry_columns view

    Detection only - does NOT auto-delete. Logs DELETE CANDIDATES for manual action.

    Schedule: Every 6 hours, offset from geo_orphan by 2 hours to spread load.

    Handler: triggers/admin/geo_integrity_timer.py
    """
    from triggers.admin.geo_integrity_timer import geo_integrity_timer_handler
    geo_integrity_timer_handler.handle(timer)


# ============================================================================
# SYSTEM MONITORING TIMERS (04 JAN 2026)
# ============================================================================

@bp.timer_trigger(
    schedule="0 0 * * * *",  # Every hour on the hour
    arg_name="timer",
    run_on_startup=False
)
def system_snapshot_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Capture system configuration snapshot hourly.

    Captures current system configuration including network/VNet settings,
    instance info, and config sources. Compares to previous snapshot and
    logs if configuration drift is detected.

    Schedule: Every hour on the hour (aligns with instance scaling)

    Handler: triggers/admin/system_snapshot_timer.py (extracted 09 JAN 2026)
    """
    from triggers.admin.system_snapshot_timer import system_snapshot_timer_handler
    system_snapshot_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 3 * * *",  # Daily at 3 AM UTC
    arg_name="timer",
    run_on_startup=False
)
def log_cleanup_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Clean up expired JSONL log files daily.

    Deletes old log files from Azure Blob Storage based on retention settings:
    - Verbose logs (DEBUG+): 7 days (JSONL_DEBUG_RETENTION_DAYS)
    - Default logs (WARNING+): 30 days (JSONL_WARNING_RETENTION_DAYS)
    - Metrics logs: 14 days (JSONL_METRICS_RETENTION_DAYS)

    Schedule: Daily at 3 AM UTC (low traffic period)

    Handler: triggers/admin/log_cleanup_timer.py (created 11 JAN 2026 - F7.12.F)
    """
    from triggers.admin.log_cleanup_timer import log_cleanup_timer_handler
    log_cleanup_timer_handler.handle(timer)


@bp.timer_trigger(
    schedule="0 0 * * * *",  # Every hour on the hour
    arg_name="timer",
    run_on_startup=False
)
def external_service_health_timer(timer: func.TimerRequest) -> None:
    """
    Timer trigger: Check health of registered external geospatial services.

    Checks all services where next_check_at <= NOW() AND enabled = true.
    Updates status, consecutive_failures, and health_history.
    Sends notifications for status changes (outages and recoveries).

    Schedule: Every hour on the hour

    Handler: triggers/admin/external_service_timer.py (created 22 JAN 2026)
    """
    from triggers.admin.external_service_timer import external_service_health_timer_handler
    external_service_health_timer_handler.handle(timer)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['bp']
