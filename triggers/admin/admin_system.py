# ============================================================================
# SYSTEM ADMIN BLUEPRINT
# ============================================================================
# STATUS: Trigger layer - Blueprint for system-level admin routes
# PURPOSE: System health, stats, and monitoring endpoints
# CREATED: 12 JAN 2026 (Consolidated from function_app.py)
# EXPORTS: bp (Blueprint)
# ============================================================================
"""
System Admin Blueprint - System-level administration routes.

Routes (2 total):
    GET /api/health        - Comprehensive system health check
    GET /api/system/stats  - Lightweight stats for UI widgets

NOTE: /api/livez and /api/readyz are in triggers/probes.py (Phase 1 startup)
NOTE: /api/system/snapshot/* are in triggers/admin/snapshot.py
"""

import azure.functions as func
from azure.functions import Blueprint
import json
from datetime import datetime

bp = Blueprint()


# ============================================================================
# SYSTEM HEALTH & STATS (2 routes)
# ============================================================================

@bp.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Comprehensive system health check.

    GET /api/health

    Returns health status for all system components:
    - Database connectivity
    - Storage accounts
    - Service Bus queues
    - Runtime metrics
    """
    from triggers.health import health_check_trigger
    return health_check_trigger.handle_request(req)


@bp.route(route="system/stats", methods=["GET"])
def system_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Lightweight system stats for UI widgets.

    GET /api/system/stats

    Returns memory, CPU, and basic job stats for dashboard widgets.
    Designed to be polled frequently (every 10-30 seconds).

    Response:
        {
            "memory": {"used_percent": 52.1, "available_mb": 3800, "total_mb": 7900},
            "cpu": {"percent": 15.2},
            "jobs": {"active": 2, "pending": 5, "completed_24h": 47},
            "timestamp": "2025-12-28T18:30:00Z"
        }
    """
    import psutil
    import logging

    logger = logging.getLogger(__name__)

    try:
        # Memory stats
        mem = psutil.virtual_memory()
        memory_stats = {
            "used_percent": round(mem.percent, 1),
            "available_mb": round(mem.available / (1024 * 1024), 1),
            "total_mb": round(mem.total / (1024 * 1024), 1)
        }

        # CPU stats
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_stats = {
            "percent": round(cpu_percent, 1)
        }

        # Job stats (lightweight query)
        job_stats = {"active": 0, "pending": 0, "completed_24h": 0, "failed_24h": 0}
        try:
            from infrastructure.factory import RepositoryFactory
            repos = RepositoryFactory.create_repositories()
            job_repo = repos['job_repo']

            with job_repo._get_connection() as conn:
                with conn.cursor() as cur:
                    # Count by status
                    cur.execute("""
                        SELECT status, COUNT(*) as count
                        FROM app.jobs
                        WHERE status IN ('pending', 'processing', 'queued')
                           OR (status IN ('completed', 'failed') AND updated_at > NOW() - INTERVAL '24 hours')
                        GROUP BY status
                    """)
                    for row in cur.fetchall():
                        status = row['status']
                        count = row['count']
                        if status in ('pending', 'queued'):
                            job_stats['pending'] += count
                        elif status == 'processing':
                            job_stats['active'] = count
                        elif status == 'completed':
                            job_stats['completed_24h'] = count
                        elif status == 'failed':
                            job_stats['failed_24h'] = count
        except Exception as e:
            logger.warning(f"Could not fetch job stats: {e}")

        response = {
            "memory": memory_stats,
            "cpu": cpu_stats,
            "jobs": job_stats,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        return func.HttpResponse(
            json.dumps(response),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logger.error(f"Error getting system stats: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
