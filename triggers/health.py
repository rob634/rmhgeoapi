# ============================================================================
# HEALTH CHECK HTTP TRIGGER - ORCHESTRATOR
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Trigger - Deployment verification endpoint (Refactored)
# PURPOSE: GET /api/health - Comprehensive system health monitoring
# LAST_REVIEWED: 29 JAN 2026
# REFACTORED: 29 JAN 2026 - Plugin architecture (see HEALTH_REFACTOR.md)
# ============================================================================
#
# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║  MAGNIFICENT REFACTORING - 29 JAN 2026 - V0.8.1.1                         ║
# ║                                                                           ║
# ║  This file was reduced from 3,231 lines to ~510 lines (84% reduction)     ║
# ║  by extracting 20 health checks into a modular plugin architecture.       ║
# ║                                                                           ║
# ║  The monolithic God Class anti-pattern has been replaced with:            ║
# ║    • 5 category-based plugins in triggers/health_checks/                  ║
# ║    • Priority-ordered execution (10→50)                                   ║
# ║    • Parallel execution for I/O-bound external service checks             ║
# ║    • Independent testability per plugin                                   ║
# ║                                                                           ║
# ║  See HEALTH_REFACTOR.md for full documentation.                           ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
# ============================================================================
"""
Health Check HTTP Trigger - Orchestrator.

================================================================================
DEPLOYMENT VERIFICATION
================================================================================

This endpoint is the PRIMARY deployment verification tool. After any deployment:

    curl -sf https://rmhazuregeoapi-a3dma3ctfdgngwf6.eastus-01.azurewebsites.net/api/health

Response Interpretation:
    HTTP 200 + "status": "healthy"  →  Deployment successful
    HTTP 200 + "status": "degraded" →  Partial issues (check "warnings" array)
    HTTP 404 or connection refused  →  App startup failed

Common Startup Failures (check Application Insights for STARTUP_FAILED):
    - Missing environment variables (POSTGIS_HOST, SERVICE_BUS_NAMESPACE, etc.)
    - Database connectivity (firewall rules, managed identity)
    - Service Bus connectivity (namespace permissions)

Debug Mode (for troubleshooting):
    Add OBSERVABILITY_MODE=true to app settings to see config_sources in response

For full deployment verification steps, see CLAUDE.md → Post-Deployment Validation

================================================================================
PLUGIN ARCHITECTURE (29 JAN 2026)
================================================================================

Health checks are organized into category-based plugins:

    triggers/health_checks/
    ├── base.py              # HealthCheckPlugin base class
    ├── startup.py           # Priority 10 - deployment, startup, imports, runtime
    ├── application.py       # Priority 20 - app_mode, endpoints, jobs
    ├── infrastructure.py    # Priority 30 - storage, service_bus, network
    ├── database.py          # Priority 40 - database, pgstac, duckdb, schema
    └── external_services.py # Priority 50 - geotiler, ogc_features, docker_worker

Each plugin returns checks via get_checks() (sequential) or get_parallel_checks() (I/O-bound).
See HEALTH_REFACTOR.md for full architecture documentation.

================================================================================

Exports:
    HealthCheckTrigger: Health check trigger class
    health_check_trigger: Singleton trigger instance
"""

from typing import Dict, Any, List
import os
import sys
from datetime import datetime, timezone

import azure.functions as func
from .http_base import SystemMonitoringTrigger
from .health_checks import get_all_plugins
from config import get_config, AzureDefaults, StorageDefaults, get_app_mode_config


class HealthCheckTrigger(SystemMonitoringTrigger):
    """
    Health check HTTP trigger - orchestrates health check plugins.

    This class coordinates the execution of health check plugins and
    aggregates their results into a unified health response.
    """

    def __init__(self):
        super().__init__("health_check")
        # Plugins are instantiated fresh for each request to ensure clean state

    def get_allowed_methods(self) -> List[str]:
        """Health check only supports GET."""
        return ["GET"]

    def _run_checks_parallel(
        self,
        checks: List[tuple],
        max_workers: int = 4,
        timeout_seconds: float = 30.0
    ) -> Dict[str, Dict[str, Any]]:
        """
        Run multiple health checks in parallel using ThreadPoolExecutor.

        This is ideal for I/O-bound checks like HTTP calls to external services
        (TiTiler, OGC Features) where most time is spent waiting for responses.
        Python's GIL doesn't block I/O operations.

        Args:
            checks: List of (name, check_method) tuples
                    e.g., [("geotiler", self._check_geotiler_health), ...]
            max_workers: Maximum concurrent threads (default 4)
            timeout_seconds: Max time to wait for all checks (default 30s)

        Returns:
            Dict mapping check names to their results
            e.g., {"geotiler": {...}, "ogc_features": {...}}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

        results = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all checks - they start immediately
            future_to_name = {
                executor.submit(check_method): name
                for name, check_method in checks
            }

            # Collect results as they complete
            try:
                for future in as_completed(future_to_name, timeout=timeout_seconds):
                    name = future_to_name[future]
                    try:
                        results[name] = future.result()
                    except Exception as e:
                        # Individual check failed - record error but continue
                        self.logger.error(f"Parallel check '{name}' failed: {e}")
                        results[name] = {
                            "component": name,
                            "status": "error",
                            "error": str(e)[:200],
                            "error_type": type(e).__name__,
                            "checked_at": datetime.now(timezone.utc).isoformat()
                        }
            except TimeoutError:
                # Some checks didn't complete in time
                self.logger.warning(f"Parallel checks timed out after {timeout_seconds}s")
                for future, name in future_to_name.items():
                    if name not in results:
                        results[name] = {
                            "component": name,
                            "status": "timeout",
                            "error": f"Check timed out after {timeout_seconds}s",
                            "checked_at": datetime.now(timezone.utc).isoformat()
                        }

        return results

    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Perform comprehensive health check using plugin architecture.

        Iterates through all registered health check plugins (sorted by priority)
        and executes their checks. Sequential checks run one-by-one, while
        parallel checks (I/O-bound) run concurrently for performance.

        Args:
            req: HTTP request (not used for health check)

        Returns:
            Health status data with all component results
        """
        from config import __version__

        config = get_config()

        # Initialize health data structure
        health_data = {
            "status": "healthy",
            "version": __version__,
            "components": {},
            "warnings": [],
            "environment": {
                "bronze_storage_account": config.storage.bronze.account_name,
                "python_version": sys.version.split()[0],
                "function_runtime": "python",
                "health_check_version": "v2026-01-29_PLUGIN_ARCH"
            },
            "identity": {
                "database": {
                    "admin_identity_name": config.database.managed_identity_admin_name,
                    "use_managed_identity": config.database.use_managed_identity,
                    "auth_method": "managed_identity" if config.database.use_managed_identity else "password",
                    "note": "Single admin identity used for all database operations"
                },
                "storage": {
                    "auth_method": "DefaultAzureCredential (system-assigned)",
                    "note": "Storage uses system-assigned managed identity"
                }
            },
            "errors": []
        }

        # Get all plugins (instantiated fresh, sorted by priority)
        plugins = get_all_plugins(logger=self.logger)

        # Track all parallel checks to run at the end
        all_parallel_checks = []

        # Execute each plugin's checks
        for plugin in plugins:
            if not plugin.is_enabled(config):
                continue

            # Run sequential checks
            for check_name, check_method in plugin.get_checks():
                try:
                    result = check_method()
                    health_data["components"][check_name] = result
                    self._update_health_status(health_data, check_name, result)
                except Exception as e:
                    self.logger.error(f"Check '{check_name}' failed: {e}")
                    error_result = {
                        "component": check_name,
                        "status": "error",
                        "error": str(e)[:200],
                        "error_type": type(e).__name__,
                        "checked_at": datetime.now(timezone.utc).isoformat()
                    }
                    health_data["components"][check_name] = error_result
                    self._update_health_status(health_data, check_name, error_result)

            # Collect parallel checks (run all together at the end)
            parallel_checks = plugin.get_parallel_checks()
            all_parallel_checks.extend(parallel_checks)

        # Run all parallel checks together for maximum concurrency
        if all_parallel_checks:
            parallel_results = self._run_checks_parallel(
                all_parallel_checks,
                timeout_seconds=25.0
            )
            for check_name, result in parallel_results.items():
                health_data["components"][check_name] = result
                self._update_health_status(health_data, check_name, result)

        # Add vault placeholder (disabled - using env vars only)
        health_data["components"]["vault"] = {
            "component": "vault",
            "status": "disabled",
            "details": {"message": "Key Vault disabled - using environment variables only"},
            "checked_at": datetime.now(timezone.utc).isoformat()
        }

        # Observability status - always include
        health_data["observability_status"] = config.get_debug_status()

        # Config sources - only include when OBSERVABILITY_MODE=true
        if config.is_observability_enabled():
            config_sources = self._get_config_sources()
            health_data["config_sources"] = config_sources
            health_data["_observability_mode"] = True
            health_data["_debug_notice"] = "Verbose config sources included - OBSERVABILITY_MODE=true"

        return health_data

    def _update_health_status(
        self,
        health_data: Dict[str, Any],
        check_name: str,
        result: Dict[str, Any]
    ) -> None:
        """
        Update overall health status based on individual check result.

        Status hierarchy:
        - "unhealthy" (highest) - critical component failed
        - "degraded" - optional component failed or warning
        - "healthy" (lowest) - all checks passed

        Args:
            health_data: The health data dict to update
            check_name: Name of the check for error messages
            result: The check result dict
        """
        status = result.get("status", "healthy")

        if status == "unhealthy":
            health_data["status"] = "unhealthy"
            if result.get("error"):
                health_data["errors"].append(f"{check_name}: {result['error']}")
            elif result.get("errors"):
                health_data["errors"].extend(result["errors"])

        elif status == "error":
            # Error status also degrades health
            if health_data["status"] == "healthy":
                health_data["status"] = "degraded"
            if result.get("error"):
                health_data["errors"].append(f"{check_name}: {result['error']}")

        elif status == "warning":
            if health_data["status"] == "healthy":
                health_data["status"] = "degraded"
            if result.get("warning"):
                health_data["warnings"].append(result["warning"])
            elif result.get("warnings"):
                health_data["warnings"].extend(result["warnings"])

    def handle_request(self, req: func.HttpRequest) -> func.HttpResponse:
        """
        Override to provide proper HTTP status codes for health checks.

        Returns:
            - 200 OK when all components are healthy or degraded (app functional)
            - 503 Service Unavailable when any critical component is unhealthy
            - 500 Internal Server Error for unexpected errors

        Note: "degraded" status returns 200 because the app is still functional,
        just with some optional components (TiTiler, OGC Features) having issues.
        Azure health probes should treat 200 as healthy.
        """
        import json
        import uuid

        request_id = str(uuid.uuid4())

        try:
            # Validate HTTP method
            if req.method not in self.get_allowed_methods():
                return func.HttpResponse(
                    json.dumps({
                        "error": "Method not allowed",
                        "message": f"Method {req.method} not allowed. Allowed: GET",
                        "request_id": request_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }),
                    status_code=405,
                    mimetype="application/json"
                )

            # Process the health check
            health_data = self.process_request(req)

            # Determine HTTP status code based on health status
            # "degraded" returns 200 because app is functional (optional components have issues)
            if health_data["status"] in ("healthy", "degraded"):
                status_code = 200  # OK - app is functional
            elif health_data["status"] == "unhealthy":
                status_code = 503  # Service Unavailable - critical components failing
            else:
                status_code = 500  # Internal Server Error (unexpected status)

            # Add response metadata
            response_data = {
                **health_data,
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return func.HttpResponse(
                json.dumps(response_data, default=str),
                status_code=status_code,
                mimetype="application/json",
                headers={
                    "X-Request-ID": request_id,
                    "Cache-Control": "no-cache, no-store, must-revalidate"
                }
            )

        except Exception as e:
            # Log the error
            self.logger.error(f"Health check error: {e}")

            return func.HttpResponse(
                json.dumps({
                    "error": "Internal server error",
                    "message": f"Health check failed: {str(e)}",
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "error"
                }),
                status_code=500,
                mimetype="application/json",
                headers={"X-Request-ID": request_id}
            )

    def _get_config_sources(self) -> Dict[str, Any]:
        """
        Get configuration values with their sources for debugging.

        Shows whether each config value came from:
        - ENV: Environment variable
        - DEFAULT: AzureDefaults or other default class

        Only included when OBSERVABILITY_MODE=true to avoid leaking configuration details.
        Sensitive values (passwords, keys) are masked.

        Returns:
            Dict mapping config key to {value, source, env_var, is_default}
        """
        config = get_config()
        sources = {}

        # Storage configuration (zone-specific)
        bronze_env = os.getenv('BRONZE_STORAGE_ACCOUNT')
        sources['bronze_storage_account'] = {
            "value": config.storage.bronze.account_name,
            "source": "ENV" if bronze_env else "DEFAULT",
            "env_var": "BRONZE_STORAGE_ACCOUNT",
            "is_default": config.storage.bronze.account_name == StorageDefaults.DEFAULT_ACCOUNT_NAME
        }

        # Managed Identity (Admin)
        mi_env = os.getenv('DB_ADMIN_MANAGED_IDENTITY_NAME')
        sources['managed_identity_admin_name'] = {
            "value": config.database.managed_identity_admin_name,
            "source": "ENV" if mi_env else "DEFAULT",
            "env_var": "DB_ADMIN_MANAGED_IDENTITY_NAME",
            "is_default": config.database.managed_identity_admin_name == AzureDefaults.MANAGED_IDENTITY_NAME
        }

        # Database host
        db_host_env = os.getenv('POSTGIS_HOST')
        sources['postgis_host'] = {
            "value": config.database.host,
            "source": "ENV" if db_host_env else "DEFAULT",
            "env_var": "POSTGIS_HOST",
            "is_default": not bool(db_host_env)
        }

        # Database name
        db_name_env = os.getenv('POSTGIS_DATABASE')
        sources['postgis_database'] = {
            "value": config.database.database,
            "source": "ENV" if db_name_env else "DEFAULT",
            "env_var": "POSTGIS_DATABASE",
            "is_default": not bool(db_name_env)
        }

        # TiTiler URL
        titiler_env = os.getenv('TITILER_BASE_URL')
        sources['titiler_base_url'] = {
            "value": config.titiler_base_url,
            "source": "ENV" if titiler_env else "DEFAULT",
            "env_var": "TITILER_BASE_URL",
            "is_default": config.titiler_base_url == AzureDefaults.TITILER_BASE_URL
        }

        # ETL App URL
        etl_env = os.getenv('ETL_APP_URL')
        sources['etl_app_base_url'] = {
            "value": config.etl_app_base_url,
            "source": "ENV" if etl_env else "DEFAULT",
            "env_var": "ETL_APP_URL",
            "is_default": config.etl_app_base_url == AzureDefaults.ETL_APP_URL
        }

        # Service Bus namespace
        sb_fqdn = os.getenv('SERVICE_BUS_FQDN')
        sb_namespace = os.getenv('SERVICE_BUS_NAMESPACE')
        sb_env = sb_fqdn or sb_namespace
        sources['service_bus_namespace'] = {
            "value": config.service_bus_namespace,
            "source": "ENV (SERVICE_BUS_FQDN)" if sb_fqdn else ("ENV (SERVICE_BUS_NAMESPACE)" if sb_namespace else "DEFAULT"),
            "env_var": "SERVICE_BUS_FQDN",
            "is_default": not bool(sb_env)
        }

        # Observability mode
        obs_env = os.getenv('OBSERVABILITY_MODE')
        debug_env = os.getenv('DEBUG_MODE')
        metrics_debug_env = os.getenv('METRICS_DEBUG_MODE')
        if obs_env:
            source = "ENV (OBSERVABILITY_MODE)"
        elif metrics_debug_env:
            source = "ENV (METRICS_DEBUG_MODE - legacy)"
        elif debug_env:
            source = "ENV (DEBUG_MODE - legacy)"
        else:
            source = "DEFAULT"

        sources['observability_mode'] = {
            "value": config.is_observability_enabled(),
            "source": source,
            "env_var": "OBSERVABILITY_MODE",
            "is_default": not bool(obs_env or debug_env or metrics_debug_env),
            "note": "Unified flag replacing DEBUG_MODE/METRICS_DEBUG_MODE"
        }

        # Summary statistics
        env_count = sum(1 for v in sources.values() if v['source'].startswith('ENV'))
        default_count = sum(1 for v in sources.values() if v['source'] == 'DEFAULT')

        return {
            "configs": sources,
            "summary": {
                "total_checked": len(sources),
                "from_environment": env_count,
                "using_defaults": default_count
            },
            "note": "Only shown when OBSERVABILITY_MODE=true"
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

health_check_trigger = HealthCheckTrigger()


# ============================================================================
# AZURE FUNCTION ENTRY POINT
# ============================================================================

def main(req: func.HttpRequest) -> func.HttpResponse:
    """Azure Function entry point for health check."""
    return health_check_trigger.handle_request(req)
