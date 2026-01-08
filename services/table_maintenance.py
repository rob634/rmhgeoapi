# ============================================================================
# TABLE MAINTENANCE SERVICE
# ============================================================================
# STATUS: Services - Database table maintenance operations
# PURPOSE: Async VACUUM scheduling via pg_cron (fire-and-forget pattern)
# CREATED: 08 JAN 2026
# ============================================================================
"""
Table Maintenance Service.

Provides fire-and-forget VACUUM scheduling via pg_cron extension.
Functions return immediately - vacuum runs asynchronously in database.

PREREQUISITE: pg_cron extension must be enabled and configured.
See docs_claude/TABLE_MAINTENANCE.md for setup instructions.

Usage:
    from services.table_maintenance import schedule_vacuum_async

    # In a handler:
    result = schedule_vacuum_async('h3.cells')
    # Returns immediately: {"status": "scheduled", "table": "h3.cells", ...}

Exports:
    schedule_vacuum_async: Schedule one-time VACUUM via pg_cron
    check_vacuum_status: Check pg_cron job history
    get_table_bloat_stats: Get dead tuple statistics
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import time
import logging

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "table_maintenance")


# ============================================================================
# VACUUM SCHEDULING
# ============================================================================

def schedule_vacuum_async(
    table_name: str,
    connection_provider=None
) -> Dict[str, Any]:
    """
    Schedule a one-time VACUUM ANALYZE via pg_cron.

    This function returns immediately. The vacuum job is queued and
    will execute within 1 minute via pg_cron.

    Args:
        table_name: Fully qualified table name (e.g., 'h3.cells', 'geo.admin0')
        connection_provider: Object with _get_connection() method (e.g., repository)
                           If None, creates a new PostgreSQLRepository

    Returns:
        Dict with scheduling result:
        - status: 'scheduled' | 'schedule_failed' | 'pg_cron_not_available'
        - table: Table name
        - job_name: Unique job identifier (if scheduled)
        - error: Error message (if failed)

    Example:
        >>> result = schedule_vacuum_async('h3.cells')
        >>> print(result)
        {'status': 'scheduled', 'table': 'h3.cells', 'job_name': 'vacuum-h3-cells-1704700000'}
    """
    # Validate table name format (prevent SQL injection)
    if not _validate_table_name(table_name):
        return {
            "status": "invalid_table_name",
            "table": table_name,
            "error": "Table name must be schema.table format with valid identifiers"
        }

    # Get connection provider
    if connection_provider is None:
        from infrastructure.postgresql import PostgreSQLRepository
        connection_provider = PostgreSQLRepository()

    # Create unique job name
    job_name = f"vacuum-{table_name.replace('.', '-')}-{int(time.time())}"

    try:
        with connection_provider._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if pg_cron is available
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'
                    )
                """)
                pg_cron_available = cur.fetchone()[0]

                if not pg_cron_available:
                    logger.warning(
                        f"pg_cron extension not available - cannot schedule async VACUUM for {table_name}"
                    )
                    return {
                        "status": "pg_cron_not_available",
                        "table": table_name,
                        "error": "pg_cron extension is not installed. See docs_claude/TABLE_MAINTENANCE.md",
                        "manual_command": f"VACUUM ANALYZE {table_name}"
                    }

                # Schedule job for next minute (fires once then we unschedule)
                cur.execute(
                    "SELECT cron.schedule(%s, '* * * * *', %s)",
                    (job_name, f'VACUUM ANALYZE {table_name}')
                )
                job_id = cur.fetchone()[0]

                # Immediately unschedule (job is already queued for next minute)
                cur.execute("SELECT cron.unschedule(%s)", (job_name,))

            conn.commit()

        logger.info(f"VACUUM scheduled: {job_name} for {table_name} (executes within 1 minute)")
        return {
            "status": "scheduled",
            "table": table_name,
            "job_name": job_name,
            "job_id": job_id,
            "note": "VACUUM will execute within 1 minute"
        }

    except Exception as e:
        logger.warning(f"Failed to schedule async VACUUM for {table_name}: {e}")
        return {
            "status": "schedule_failed",
            "table": table_name,
            "error": str(e),
            "manual_command": f"VACUUM ANALYZE {table_name}"
        }


def _validate_table_name(table_name: str) -> bool:
    """
    Validate table name format to prevent SQL injection.

    Valid format: schema.table where both are valid SQL identifiers.

    Args:
        table_name: Table name to validate

    Returns:
        True if valid, False otherwise
    """
    import re

    # Must be schema.table format
    if '.' not in table_name:
        return False

    parts = table_name.split('.')
    if len(parts) != 2:
        return False

    # Each part must be a valid SQL identifier
    # Alphanumeric + underscore, not starting with number
    identifier_pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'

    return all(re.match(identifier_pattern, part) for part in parts)


# ============================================================================
# MONITORING
# ============================================================================

def check_vacuum_status(
    hours: int = 24,
    connection_provider=None
) -> Dict[str, Any]:
    """
    Check pg_cron job history for vacuum jobs.

    Args:
        hours: Look back period in hours (default: 24)
        connection_provider: Object with _get_connection() method

    Returns:
        Dict with:
        - recent_jobs: List of recent vacuum job runs
        - scheduled_jobs: Currently scheduled vacuum jobs
        - status: 'ok' | 'error'
    """
    if connection_provider is None:
        from infrastructure.postgresql import PostgreSQLRepository
        connection_provider = PostgreSQLRepository()

    try:
        with connection_provider._get_connection() as conn:
            with conn.cursor() as cur:
                # Check if pg_cron exists
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'
                    )
                """)
                if not cur.fetchone()[0]:
                    return {"status": "pg_cron_not_available"}

                # Get recent job runs
                cur.execute("""
                    SELECT jobid, runid, job_pid, command, status,
                           return_message, start_time, end_time,
                           end_time - start_time as duration
                    FROM cron.job_run_details
                    WHERE command LIKE 'VACUUM%%'
                    AND start_time > NOW() - INTERVAL '%s hours'
                    ORDER BY start_time DESC
                    LIMIT 50
                """, (hours,))

                recent_jobs = []
                for row in cur.fetchall():
                    recent_jobs.append({
                        "job_id": row[0],
                        "run_id": row[1],
                        "command": row[3],
                        "status": row[4],
                        "message": row[5],
                        "start_time": row[6].isoformat() if row[6] else None,
                        "end_time": row[7].isoformat() if row[7] else None,
                        "duration": str(row[8]) if row[8] else None
                    })

                # Get scheduled vacuum jobs
                cur.execute("""
                    SELECT jobid, jobname, schedule, command, active
                    FROM cron.job
                    WHERE command LIKE 'VACUUM%%'
                    ORDER BY jobname
                """)

                scheduled_jobs = []
                for row in cur.fetchall():
                    scheduled_jobs.append({
                        "job_id": row[0],
                        "job_name": row[1],
                        "schedule": row[2],
                        "command": row[3],
                        "active": row[4]
                    })

        return {
            "status": "ok",
            "recent_jobs": recent_jobs,
            "scheduled_jobs": scheduled_jobs,
            "query_hours": hours
        }

    except Exception as e:
        logger.error(f"Failed to check vacuum status: {e}")
        return {"status": "error", "error": str(e)}


def get_table_bloat_stats(
    schemas: List[str] = None,
    connection_provider=None
) -> Dict[str, Any]:
    """
    Get dead tuple statistics for tables (indicates need for vacuum).

    Args:
        schemas: List of schemas to check (default: h3, geo, pgstac, app)
        connection_provider: Object with _get_connection() method

    Returns:
        Dict with table bloat statistics
    """
    if schemas is None:
        schemas = ['h3', 'geo', 'pgstac', 'app']

    if connection_provider is None:
        from infrastructure.postgresql import PostgreSQLRepository
        connection_provider = PostgreSQLRepository()

    try:
        with connection_provider._get_connection() as conn:
            with conn.cursor() as cur:
                # Get vacuum stats for specified schemas
                cur.execute("""
                    SELECT schemaname, relname,
                           last_vacuum, last_autovacuum,
                           last_analyze, last_autoanalyze,
                           n_dead_tup, n_live_tup,
                           ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) as dead_pct
                    FROM pg_stat_user_tables
                    WHERE schemaname = ANY(%s)
                    ORDER BY n_dead_tup DESC
                """, (schemas,))

                tables = []
                for row in cur.fetchall():
                    tables.append({
                        "schema": row[0],
                        "table": row[1],
                        "last_vacuum": row[2].isoformat() if row[2] else None,
                        "last_autovacuum": row[3].isoformat() if row[3] else None,
                        "last_analyze": row[4].isoformat() if row[4] else None,
                        "last_autoanalyze": row[5].isoformat() if row[5] else None,
                        "dead_tuples": row[6],
                        "live_tuples": row[7],
                        "dead_pct": float(row[8]) if row[8] else 0.0,
                        "needs_vacuum": row[6] > 10000 or (row[8] and float(row[8]) > 5)
                    })

        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "schemas_checked": schemas,
            "tables": tables,
            "tables_needing_vacuum": [t for t in tables if t.get("needs_vacuum")]
        }

    except Exception as e:
        logger.error(f"Failed to get table bloat stats: {e}")
        return {"status": "error", "error": str(e)}


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'schedule_vacuum_async',
    'check_vacuum_status',
    'get_table_bloat_stats'
]
