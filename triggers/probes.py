# ============================================================================
# KUBERNETES-STYLE HEALTH PROBES
# ============================================================================
# STATUS: Trigger - Diagnostic endpoints for startup validation
# PURPOSE: Provide livez/readyz/health endpoints that work even when startup fails
# LAST_REVIEWED: 05 FEB 2026
# REVIEW_STATUS: Updated for three-tier health design (F12.11)
# ============================================================================
"""
Kubernetes-Style Health Probes.

These endpoints have MINIMAL dependencies and are registered FIRST in
function_app.py to ensure they're always available for diagnostics,
even when startup validation fails.

Endpoints:
    GET /api/livez  - Liveness probe (always 200 if process alive)
    GET /api/readyz - Readiness probe (200 if ready, 503 if not)
    GET /api/health - Instance health (this app's status, all modes)

Design Principles:
    1. ZERO dependencies on other project modules (except startup_state)
    2. Registered BEFORE any validation runs
    3. Never crash - always return a response
    4. Provide actionable error information

Usage in function_app.py:
    # At the VERY TOP, before any imports that might fail:
    from triggers.probes import bp as probes_bp
    app.register_functions(probes_bp)

See STARTUP_REFORM.md for full design documentation.

Exports:
    bp: Blueprint with livez/readyz routes
    get_probe_status(): Helper for health endpoint integration
"""

import json
import azure.functions as func
from azure.functions import Blueprint

# Import startup state - this module has zero dependencies
from startup import STARTUP_STATE

# Create Blueprint for probe endpoints
bp = Blueprint()


class LivezProbe:
    """
    Liveness Probe - Is the process alive?

    Always returns 200 if the Python process loaded successfully.
    Used by load balancers and orchestrators to detect crashed processes.

    This endpoint should NEVER fail. If it returns anything other than 200,
    the process should be restarted.
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/livez request."""
        return func.HttpResponse(
            json.dumps({
                "status": "alive",
                "probe": "livez",
                "message": "Process is running"
            }),
            status_code=200,
            mimetype="application/json"
        )


class ReadyzProbe:
    """
    Readiness Probe - Is the app ready to handle requests?

    Returns:
        200: All startup validations passed, app is ready for traffic
        503: Validation failed or still in progress, with error details

    This endpoint is used by load balancers to determine if the app
    should receive traffic. A 503 response means "don't send requests here".
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/readyz request."""

        # Check if validation is still in progress
        if not STARTUP_STATE.validation_complete:
            return func.HttpResponse(
                json.dumps({
                    "status": "initializing",
                    "probe": "readyz",
                    "message": "Startup validation in progress",
                    "startup_time": STARTUP_STATE.startup_time
                }),
                status_code=503,
                mimetype="application/json"
            )

        # Check if all validations passed
        if STARTUP_STATE.all_passed:
            # Import version (safe - config has minimal deps)
            try:
                from config import __version__
                version = __version__
            except ImportError:
                version = "unknown"

            response = {
                "status": "ready",
                "probe": "readyz",
                "version": version,
                "message": "All startup validations passed",
                "summary": STARTUP_STATE.get_summary()
            }

            # Include warnings for env vars using defaults (informational, not errors)
            warnings = STARTUP_STATE.get_warnings()
            if warnings:
                response["warnings"] = warnings
                response["message"] = f"Ready ({len(warnings)} env vars using defaults)"

            # Deep mode: include lightweight diagnostics summary
            deep_mode = req.params.get('deep', 'false').lower() == 'true'
            if deep_mode:
                try:
                    from infrastructure.diagnostics import get_diagnostics_summary
                    response["diagnostics"] = get_diagnostics_summary()
                except Exception as e:
                    response["diagnostics"] = {"error": str(e)}

            return func.HttpResponse(
                json.dumps(response, indent=2),
                status_code=200,
                mimetype="application/json"
            )

        # Validation failed - return 503 with details
        failed_checks = STARTUP_STATE.get_failed_checks()

        # Build error response with actionable information
        errors = []
        for check in failed_checks:
            error_info = {
                "name": check.name,
                "error_type": check.error_type,
                "message": check.error_message
            }
            # Include fix suggestions if available
            if check.details and "likely_causes" in check.details:
                error_info["likely_causes"] = check.details["likely_causes"]
            if check.details and "fix" in check.details:
                error_info["fix"] = check.details["fix"]
            # Include detailed validation errors (08 JAN 2026 - env var regex validation)
            if check.details and "errors" in check.details:
                error_info["validation_errors"] = check.details["errors"]
            errors.append(error_info)

        return func.HttpResponse(
            json.dumps({
                "status": "not_ready",
                "probe": "readyz",
                "message": STARTUP_STATE.critical_error or "Startup validation failed",
                "summary": STARTUP_STATE.get_summary(),
                "errors": errors
            }, indent=2),
            status_code=503,
            mimetype="application/json"
        )


# Singleton instances
_livez_probe = LivezProbe()
_readyz_probe = ReadyzProbe()


# ============================================================================
# BLUEPRINT ROUTES
# ============================================================================
# These routes are registered via Blueprint pattern for consistency with
# other trigger modules (admin_db.py, admin_servicebus.py, h3_sources).
# ============================================================================

@bp.route(
    route="livez",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def livez(req: func.HttpRequest) -> func.HttpResponse:
    """
    Liveness probe - Is the process alive?

    Always returns 200 if the Python process loaded successfully.
    Used by load balancers to detect crashed processes.

    Returns:
        200: {"status": "alive", "probe": "livez"}
    """
    return _livez_probe.handle(req)


@bp.route(
    route="readyz",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def readyz(req: func.HttpRequest) -> func.HttpResponse:
    """
    Readiness probe - Is the app ready to handle requests?

    Returns 200 if all startup validations passed.
    Returns 503 if any validation failed (with error details).

    Returns:
        200: {"status": "ready", "probe": "readyz", ...}
        503: {"status": "not_ready", "probe": "readyz", "errors": [...]}
    """
    return _readyz_probe.handle(req)


def get_probe_status() -> dict:
    """
    Get current probe status for inclusion in other endpoints.

    Useful for including probe information in /api/health response.

    Returns:
        Dict with livez and readyz status
    """
    return {
        "livez": "alive",  # Always alive if this code runs
        "readyz": "ready" if STARTUP_STATE.all_passed else "not_ready",
        "validation_complete": STARTUP_STATE.validation_complete,
        "startup_time": STARTUP_STATE.startup_time
    }


# ============================================================================
# INSTANCE HEALTH ENDPOINT (05 FEB 2026 - F12.11)
# ============================================================================
# /api/health - THIS app's health status (all modes)
# Different from /api/platform/health (B2B system health) and
# /api/system-health (infrastructure health, admin only)
# ============================================================================

class InstanceHealthProbe:
    """
    Instance Health Probe - This app's status.

    Returns health information for THIS specific app instance:
    - App name, mode, version
    - Uptime and memory usage
    - Local connectivity to database, service bus, storage

    This is a fast, lightweight check (<100ms target) that runs
    local checks only - no cross-app calls.

    All modes expose this endpoint.
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/health request."""
        import time
        start_time = time.time()

        try:
            # Import here to avoid import-time failures
            from datetime import datetime, timezone
            from config import __version__, get_app_mode_config

            app_mode = get_app_mode_config()

            # Build response
            health_data = {
                "status": "healthy",
                "instance": {
                    "app_name": app_mode.app_name,
                    "app_mode": app_mode.mode.value,
                    "version": __version__,
                    "uptime_seconds": self._get_uptime(),
                    "memory_mb": self._get_memory_usage()
                },
                "connectivity": self._check_connectivity(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            # Determine overall status based on connectivity
            conn = health_data["connectivity"]
            if conn.get("database") != "ok" or conn.get("storage") != "ok":
                health_data["status"] = "degraded"

            # Add response time
            health_data["response_time_ms"] = round((time.time() - start_time) * 1000, 2)

            return func.HttpResponse(
                json.dumps(health_data, indent=2),
                status_code=200,
                mimetype="application/json"
            )

        except Exception as e:
            return func.HttpResponse(
                json.dumps({
                    "status": "unhealthy",
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "response_time_ms": round((time.time() - start_time) * 1000, 2)
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )

    def _get_uptime(self) -> int:
        """Get process uptime in seconds."""
        try:
            import psutil
            from datetime import datetime, timezone
            process = psutil.Process()
            create_time = datetime.fromtimestamp(process.create_time(), tz=timezone.utc)
            return int((datetime.now(timezone.utc) - create_time).total_seconds())
        except Exception:
            return -1

    def _get_memory_usage(self) -> int:
        """Get current memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return int(process.memory_info().rss / (1024 * 1024))
        except Exception:
            return -1

    def _check_connectivity(self) -> dict:
        """
        Check connectivity to core dependencies.

        Returns dict with status for each dependency:
        - "ok": Connected successfully
        - "error": Connection failed (with reason)
        - "skipped": Not applicable for this mode
        """
        connectivity = {}

        # Database connectivity
        try:
            from infrastructure import get_connection_pool
            pool = get_connection_pool()
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            connectivity["database"] = "ok"
        except Exception as e:
            connectivity["database"] = f"error: {type(e).__name__}"

        # Storage connectivity
        try:
            from config import get_config
            config = get_config()
            # Just check we can get config - actual blob check would be slow
            if config.storage.bronze_account:
                connectivity["storage"] = "ok"
            else:
                connectivity["storage"] = "error: no storage configured"
        except Exception as e:
            connectivity["storage"] = f"error: {type(e).__name__}"

        # Service Bus connectivity (send capability)
        try:
            from config import get_config
            config = get_config()
            if config.queues.service_bus_fqdn:
                connectivity["service_bus"] = "ok"
            else:
                connectivity["service_bus"] = "error: no service bus configured"
        except Exception as e:
            connectivity["service_bus"] = f"error: {type(e).__name__}"

        return connectivity


_instance_health_probe = InstanceHealthProbe()


@bp.route(
    route="health",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """
    Instance health - THIS app's status.

    Returns health information for this specific app instance including:
    - App name, mode, version
    - Uptime and memory usage
    - Connectivity to database, storage, service bus

    This is different from:
    - /api/platform/health - B2B system health (can I submit jobs?)
    - /api/system-health - Infrastructure health (admin view of all apps)

    Returns:
        200: {"status": "healthy|degraded", "instance": {...}, "connectivity": {...}}
        500: {"status": "unhealthy", "error": "..."}

    Example:
        GET /api/health
    """
    return _instance_health_probe.handle(req)


# ============================================================================
# DIAGNOSTICS ENDPOINT
# ============================================================================

class DiagnosticsProbe:
    """
    Diagnostics Probe - Deep system diagnostics for QA debugging.

    Provides comprehensive diagnostics including:
    - Dependency connectivity with latency measurement
    - DNS resolution timing
    - Connection pool statistics
    - Instance/cold start information
    - Network environment summary

    Use this endpoint for debugging opaque corporate Azure environments
    where VNet/ASE complexity may cause connectivity issues.
    """

    def handle(self, req: func.HttpRequest) -> func.HttpResponse:
        """Handle GET /api/diagnostics request."""
        try:
            # Import here to avoid import-time failures
            from infrastructure.diagnostics import get_diagnostics

            # Parse query params for selective checks
            check_deps = req.params.get('dependencies', 'true').lower() == 'true'
            check_dns = req.params.get('dns', 'true').lower() == 'true'
            check_pools = req.params.get('pools', 'true').lower() == 'true'
            check_instance = req.params.get('instance', 'true').lower() == 'true'
            check_network = req.params.get('network', 'true').lower() == 'true'

            # Custom timeout (default 10s, max 30s)
            timeout = min(float(req.params.get('timeout', '10')), 30.0)

            # Run diagnostics
            result = get_diagnostics(
                check_dependencies=check_deps,
                check_dns=check_dns,
                check_pools=check_pools,
                check_instance=check_instance,
                check_network=check_network,
                dependency_timeout=timeout,
            )

            return func.HttpResponse(
                json.dumps(result.to_dict(), indent=2),
                status_code=200,
                mimetype="application/json"
            )

        except Exception as e:
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "probe": "diagnostics",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )


_diagnostics_probe = DiagnosticsProbe()


@bp.route(
    route="diagnostics",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def diagnostics(req: func.HttpRequest) -> func.HttpResponse:
    """
    Diagnostics endpoint - Deep system diagnostics for QA debugging.

    Query Parameters:
        dependencies: Check dependency connectivity (default: true)
        dns: Check DNS resolution timing (default: true)
        pools: Check connection pool stats (default: true)
        instance: Check instance/cold start info (default: true)
        network: Check network environment (default: true)
        timeout: Timeout for connectivity checks in seconds (default: 10, max: 30)

    Returns:
        200: Full diagnostics report with timing information

    Example:
        GET /api/diagnostics
        GET /api/diagnostics?dependencies=true&dns=true&timeout=5
    """
    return _diagnostics_probe.handle(req)


# ============================================================================
# METRICS FLUSH ENDPOINT
# ============================================================================

@bp.route(
    route="metrics/flush",
    methods=["POST"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def metrics_flush(req: func.HttpRequest) -> func.HttpResponse:
    """
    Flush buffered metrics to blob storage.

    Use this endpoint to force-flush metrics before a deployment or
    to ensure recent metrics are persisted for debugging.

    Returns:
        200: Flush stats including records flushed, errors, etc.

    Example:
        POST /api/metrics/flush
    """
    try:
        from infrastructure.metrics_blob_logger import flush_metrics, get_metrics_stats

        # Flush and get stats
        flush_result = flush_metrics()
        stats = get_metrics_stats()

        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "flush": flush_result,
                "stats": stats,
            }, indent=2),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(
    route="metrics/stats",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def metrics_stats(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get metrics logger statistics.

    Returns:
        200: Current logger stats (records logged, flushed, errors, buffer size)

    Example:
        GET /api/metrics/stats
    """
    try:
        from infrastructure.metrics_blob_logger import get_metrics_stats

        stats = get_metrics_stats()

        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "metrics": stats,
            }, indent=2),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )


# ============================================================================
# APP INSIGHTS LOG EXPORT ENDPOINT (10 JAN 2026 - F7.12.D)
# ============================================================================

@bp.route(
    route="appinsights/query",
    methods=["POST"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def appinsights_query(req: func.HttpRequest) -> func.HttpResponse:
    """
    Query Application Insights logs.

    Request body:
        {
            "query": "traces | where timestamp >= ago(1h) | take 100",
            "timespan": "PT1H"  // Optional, default PT1H
        }

    Returns:
        200: Query results with rows and metadata

    Example:
        POST /api/appinsights/query
        {"query": "traces | take 10"}
    """
    try:
        from infrastructure.appinsights_exporter import query_logs

        # Parse request body
        try:
            body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"status": "error", "error": "Invalid JSON body"}),
                status_code=400,
                mimetype="application/json"
            )

        query = body.get("query")
        if not query:
            return func.HttpResponse(
                json.dumps({"status": "error", "error": "Missing 'query' field"}),
                status_code=400,
                mimetype="application/json"
            )

        timespan = body.get("timespan", "PT1H")

        # Run query
        result = query_logs(query, timespan)

        if result.success:
            return func.HttpResponse(
                json.dumps({
                    "status": "ok",
                    "row_count": result.row_count,
                    "columns": result.columns,
                    "rows": result.rows[:100],  # Limit response size
                    "query_duration_ms": round(result.query_duration_ms, 2),
                    "truncated": result.row_count > 100,
                }, indent=2),
                status_code=200,
                mimetype="application/json"
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "error": result.error,
                    "query_duration_ms": round(result.query_duration_ms, 2),
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(
    route="appinsights/export",
    methods=["POST"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def appinsights_export(req: func.HttpRequest) -> func.HttpResponse:
    """
    Export Application Insights logs to blob storage.

    Request body:
        {
            "query": "traces | where message contains 'SERVICE_LATENCY'",
            "timespan": "PT24H",  // Optional, default PT24H
            "container": "applogs",  // Optional, default "applogs"
            "prefix": "exports"  // Optional, default "exports"
        }

    Or use a template:
        {
            "template": "service_latency",  // One of: recent_traces, recent_errors,
                                            // service_latency, db_latency, exceptions
            "timespan": "24h",  // Without PT prefix
            "limit": 1000
        }

    Returns:
        200: Export result with blob path

    Example:
        POST /api/appinsights/export
        {"template": "service_latency", "timespan": "24h"}
    """
    try:
        from infrastructure.appinsights_exporter import export_logs_to_blob, export_template

        # Parse request body
        try:
            body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"status": "error", "error": "Invalid JSON body"}),
                status_code=400,
                mimetype="application/json"
            )

        # Check for template-based export
        template = body.get("template")
        if template:
            timespan = body.get("timespan", "1h")
            limit = body.get("limit", 1000)
            container = body.get("container", "applogs")

            result = export_template(template, timespan, limit, container)
        else:
            # Custom query export
            query = body.get("query")
            if not query:
                return func.HttpResponse(
                    json.dumps({"status": "error", "error": "Missing 'query' or 'template' field"}),
                    status_code=400,
                    mimetype="application/json"
                )

            timespan = body.get("timespan", "PT24H")
            container = body.get("container", "applogs")
            prefix = body.get("prefix", "exports")

            result = export_logs_to_blob(query, timespan, container, prefix)

        if result.success:
            return func.HttpResponse(
                json.dumps({
                    "status": "ok",
                    "blob_path": result.blob_path,
                    "row_count": result.row_count,
                    "query_duration_ms": round(result.query_duration_ms, 2),
                    "export_duration_ms": round(result.export_duration_ms, 2),
                }, indent=2),
                status_code=200,
                mimetype="application/json"
            )
        else:
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "error": result.error,
                    "row_count": result.row_count,
                    "query_duration_ms": round(result.query_duration_ms, 2),
                }, indent=2),
                status_code=500,
                mimetype="application/json"
            )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )


@bp.route(
    route="appinsights/templates",
    methods=["GET"],
    auth_level=func.AuthLevel.ANONYMOUS
)
def appinsights_templates(req: func.HttpRequest) -> func.HttpResponse:
    """
    List available query templates.

    Returns:
        200: List of templates with descriptions

    Example:
        GET /api/appinsights/templates
    """
    try:
        from infrastructure.appinsights_exporter import AppInsightsExporter

        templates = {}
        for name, query in AppInsightsExporter.QUERY_TEMPLATES.items():
            templates[name] = {
                "query_pattern": query,
                "description": name.replace("_", " ").title(),
            }

        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "templates": templates,
                "usage": "POST /api/appinsights/export with {\"template\": \"<name>\", \"timespan\": \"24h\"}",
            }, indent=2),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }, indent=2),
            status_code=500,
            mimetype="application/json"
        )
