# ============================================================================
# SYSTEM HEALTH ENDPOINT (06 FEB 2026 - F12.11)
# ============================================================================
# STATUS: Trigger - Infrastructure health for admins
# PURPOSE: Comprehensive health view of all apps, queues, databases
# LAST_REVIEWED: 06 FEB 2026
# EXPORTS: bp (Blueprint), system_health_route
# NOTES: Docker worker checked unconditionally (required infrastructure)
# ============================================================================
"""
System Health Endpoint - Infrastructure Admin View.

GET /api/system-health

Provides comprehensive health status of the entire infrastructure:
- All app instances (gateway, orchestrator, Docker worker)
- All Service Bus queues
- Database cluster
- Recent errors across components

This endpoint is only exposed on ORCHESTRATOR and STANDALONE modes.
NOT exposed on PLATFORM (gateway) - admins use orchestrator for infra health.

Design:
    - Makes HTTP calls to other apps' /api/health endpoints
    - Checks Service Bus queue depths directly
    - Queries database for recent job statistics
    - Aggregates into single infrastructure view

Target response time: <5s (due to cross-app calls)
"""

import json
import azure.functions as func
from azure.functions import Blueprint
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Create Blueprint
bp = Blueprint()


class SystemHealthProbe:
    """
    System Health Probe - Infrastructure admin view.

    Aggregates health from:
    - All deployed app instances
    - Service Bus queues
    - Database
    - Recent error counts
    """

    def __init__(self):
        self._app_urls: Optional[Dict[str, str]] = None

    def _get_app_urls(self) -> Dict[str, str]:
        """Get URLs for all app instances from config."""
        if self._app_urls is None:
            try:
                from config import get_config, get_app_mode_config
                config = get_config()
                app_mode = get_app_mode_config()

                self._app_urls = {}

                # Gateway URL (if configured)
                gateway_url = getattr(config.platform, 'gateway_url', None)
                if gateway_url:
                    self._app_urls['gateway'] = gateway_url

                # Docker worker URL - store even if None (checked unconditionally)
                # Docker worker is REQUIRED infrastructure (06 FEB 2026)
                self._app_urls['docker_worker'] = app_mode.docker_worker_url

                # This app (self) - we'll check locally instead of HTTP
                self._app_urls['_self'] = app_mode.app_name

            except Exception as e:
                logger.warning(f"Failed to get app URLs: {e}")
                self._app_urls = {}

        return self._app_urls

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/system-health request."""
        import time
        start_time = time.time()

        try:
            from config import __version__, get_app_mode_config

            app_mode = get_app_mode_config()

            # Check if this mode allows system-health
            if not app_mode.has_system_health_endpoint:
                return func.HttpResponse(
                    json.dumps({
                        "error": "system-health endpoint not available",
                        "message": f"APP_MODE={app_mode.mode.value} does not expose /api/system-health",
                        "hint": "Use orchestrator or standalone mode for infrastructure health"
                    }, indent=2),
                    status_code=403,
                    mimetype="application/json"
                )

            # Collect health from all sources
            apps_health = self._check_all_apps()
            queues_health = self._check_all_queues()
            database_health = self._check_database()
            job_stats = self._get_job_stats()
            errors_last_hour = self._get_recent_errors()

            # Determine overall status
            overall_status = self._determine_overall_status(
                apps_health, queues_health, database_health
            )

            response = {
                "status": overall_status,
                "version": __version__,
                "checked_from": app_mode.app_name,
                "apps": apps_health,
                "queues": queues_health,
                "database": database_health,
                "jobs": job_stats,
                "errors_last_hour": errors_last_hour,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }

            return func.HttpResponse(
                json.dumps(response, indent=2),
                status_code=200,
                mimetype="application/json"
            )

        except Exception as e:
            logger.exception("System health check failed")
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "response_time_ms": round((time.time() - start_time) * 1000, 2)
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )

    def _check_all_apps(self) -> Dict[str, Any]:
        """Check health of all app instances."""
        import requests

        apps = {}
        app_urls = self._get_app_urls()

        # Check this app locally (faster than HTTP)
        try:
            from config import __version__, get_app_mode_config
            app_mode = get_app_mode_config()
            apps[app_mode.app_name] = {
                "status": "healthy",
                "version": __version__,
                "mode": app_mode.mode.value,
                "source": "local"
            }
        except Exception as e:
            apps["self"] = {"status": "error", "error": str(e)}

        # Check remote apps via HTTP
        for app_name, url in app_urls.items():
            if app_name == '_self':
                continue  # Already checked locally

            # Docker worker is REQUIRED infrastructure (06 FEB 2026)
            # Check URL configuration first - missing URL = degraded system
            if app_name == 'docker_worker':
                if not url:
                    apps[app_name] = {
                        "status": "not_configured",
                        "error": "DOCKER_WORKER_URL not set - required infrastructure",
                        "source": "config"
                    }
                    continue

                # Docker worker: use /readyz for fast infrastructure check
                try:
                    readyz_url = f"{url.rstrip('/')}/readyz"
                    response = requests.get(readyz_url, timeout=5)

                    if response.status_code == 200:
                        apps[app_name] = {
                            "status": "healthy",
                            "url": url,
                            "source": "http",
                            "check": "readyz"
                        }
                    else:
                        apps[app_name] = {
                            "status": "unhealthy",
                            "http_status": response.status_code,
                            "url": url,
                            "source": "http",
                            "check": "readyz"
                        }
                except requests.exceptions.Timeout:
                    apps[app_name] = {"status": "timeout", "url": url, "source": "http"}
                except requests.exceptions.ConnectionError:
                    apps[app_name] = {"status": "unreachable", "url": url, "source": "http"}
                except Exception as e:
                    apps[app_name] = {"status": "error", "error": str(e), "url": url, "source": "http"}
                continue

            # Other apps: use /api/health for full status
            try:
                health_url = f"{url.rstrip('/')}/api/health"
                response = requests.get(health_url, timeout=5)

                if response.status_code == 200:
                    data = response.json()
                    apps[app_name] = {
                        "status": data.get("status", "unknown"),
                        "version": data.get("instance", {}).get("version", "unknown"),
                        "mode": data.get("instance", {}).get("app_mode", "unknown"),
                        "source": "http"
                    }
                else:
                    apps[app_name] = {
                        "status": "error",
                        "http_status": response.status_code,
                        "source": "http"
                    }
            except requests.exceptions.Timeout:
                apps[app_name] = {"status": "timeout", "source": "http"}
            except requests.exceptions.ConnectionError:
                apps[app_name] = {"status": "unreachable", "source": "http"}
            except Exception as e:
                apps[app_name] = {"status": "error", "error": str(e), "source": "http"}

        return apps

    def _check_all_queues(self) -> Dict[str, Any]:
        """Check all Service Bus queue depths."""
        queues = {}

        try:
            from azure.servicebus.management import ServiceBusAdministrationClient
            from azure.identity import DefaultAzureCredential
            from config import get_config

            config = get_config()
            fqdn = config.queues.service_bus_fqdn

            if not fqdn:
                return {"error": "Service Bus not configured"}

            credential = DefaultAzureCredential()
            admin_client = ServiceBusAdministrationClient(
                fully_qualified_namespace=fqdn,
                credential=credential
            )

            queue_names = [
                config.queues.job_queue_name,
                config.queues.container_tasks_queue
            ]

            for queue_name in queue_names:
                if not queue_name:
                    continue
                try:
                    props = admin_client.get_queue_runtime_properties(queue_name)
                    queues[queue_name] = {
                        "active_messages": props.active_message_count,
                        "dead_letter": props.dead_letter_message_count,
                        "status": "ok" if props.dead_letter_message_count == 0 else "warning"
                    }
                except Exception as e:
                    queues[queue_name] = {"status": "error", "error": str(e)}

        except Exception as e:
            return {"error": f"Failed to check queues: {e}"}

        return queues

    def _check_database(self) -> Dict[str, Any]:
        """Check database health and connection stats."""
        try:
            from infrastructure import get_connection_pool
            from config import get_config

            config = get_config()
            pool = get_connection_pool()

            # Get pool stats
            pool_stats = {
                "host": config.database.host,
                "database": config.database.database,
                "status": "healthy"
            }

            # Test connection
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")

            # Get connection count if possible
            try:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT count(*) FROM pg_stat_activity
                            WHERE datname = current_database()
                        """)
                        result = cur.fetchone()
                        pool_stats["active_connections"] = result[0] if result else -1
            except Exception:
                pool_stats["active_connections"] = "unknown"

            return pool_stats

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _get_job_stats(self) -> Dict[str, Any]:
        """Get job statistics for the last 24 hours."""
        try:
            from infrastructure import JobRepository

            job_repo = JobRepository()

            # Get counts by status
            stats = {
                "processing": 0,
                "completed_24h": 0,
                "failed_24h": 0
            }

            # This is a simplified check - could be enhanced with actual queries
            try:
                from datetime import timedelta
                jobs = job_repo.get_jobs_by_status("processing", limit=100)
                stats["processing"] = len(jobs) if jobs else 0
            except Exception:
                stats["processing"] = "unknown"

            return stats

        except Exception as e:
            return {"error": str(e)}

    def _get_recent_errors(self) -> int:
        """Get count of errors in the last hour from App Insights."""
        # This would require App Insights query - return placeholder for now
        # Can be enhanced to query exceptions table
        return -1  # -1 indicates "not implemented"

    def _determine_overall_status(
        self,
        apps: Dict[str, Any],
        queues: Dict[str, Any],
        database: Dict[str, Any]
    ) -> str:
        """Determine overall system status from component statuses."""

        # Check for any errors
        has_error = False
        has_warning = False

        # Check apps
        for app_name, app_health in apps.items():
            status = app_health.get("status", "unknown")
            if status in ["error", "unreachable", "timeout", "unhealthy"]:
                has_error = True
            elif status in ["degraded", "not_configured"]:
                # not_configured = required infrastructure missing = degraded
                has_warning = True

        # Check queues
        if "error" in queues:
            has_error = True
        else:
            for queue_name, queue_health in queues.items():
                if isinstance(queue_health, dict):
                    if queue_health.get("status") == "error":
                        has_error = True
                    elif queue_health.get("dead_letter", 0) > 0:
                        has_warning = True

        # Check database
        if database.get("status") == "error":
            has_error = True

        if has_error:
            return "unhealthy"
        elif has_warning:
            return "degraded"
        else:
            return "healthy"


_system_health_probe = SystemHealthProbe()


@bp.route(
    route="system-health",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def system_health_route(req: func.HttpRequest) -> func.HttpResponse:
    """
    Infrastructure health - admin view of all components.

    Returns comprehensive health status of the entire infrastructure:
    - All app instances (gateway, orchestrator, Docker worker)
    - All Service Bus queues with message counts
    - Database connectivity and connection count
    - Recent error counts

    Only available on ORCHESTRATOR and STANDALONE modes.
    NOT available on PLATFORM (gateway) - use orchestrator for admin tasks.

    Returns:
        200: {"status": "healthy|degraded|unhealthy", "apps": {...}, "queues": {...}, ...}
        403: {"error": "not available on this mode"}
        500: {"status": "error", "error": "..."}

    Example:
        GET /api/system-health
    """
    return _system_health_probe.handle(req)
