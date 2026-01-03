# ============================================================================
# HEALTH CHECK HTTP TRIGGER
# ============================================================================
# STATUS: Trigger - Deployment verification endpoint
# PURPOSE: GET /api/health - Comprehensive system health monitoring
# LAST_REVIEWED: 02 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8: Deployment verification endpoint)
# ============================================================================
"""
Health Check HTTP Trigger.

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
    Add DEBUG_MODE=true to app settings to see config_sources in response

For full deployment verification steps, see CLAUDE.md → Post-Deployment Validation

================================================================================

Comprehensive system health monitoring endpoint for GET /api/health.

Components Monitored:
    - Import Validation
    - Service Bus Queues
    - Database Configuration
    - Database Connectivity
    - DuckDB
    - Jobs Registry
    - PgSTAC
    - System Reference Tables
    - Schema Summary (07 DEC 2025) - All schemas, tables, row counts
    - TiTiler (13 DEC 2025) - Raster tile server health
    - OGC Features (13 DEC 2025) - Vector feature API health

Debug Mode Features (DEBUG_MODE=true):
    - config_sources: Shows env var vs default sources for all config values

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
from config import get_config, AzureDefaults, StorageDefaults, get_app_mode_config
from core.schema.deployer import SchemaManagerFactory
# NOTE: 'from utils import validator' REMOVED (12 DEC 2025)
# Importing validator triggers cascade: validator → function_app → CoreMachine → 75+ seconds
# The lightweight _check_import_validation() now uses sys.modules instead


class HealthCheckTrigger(SystemMonitoringTrigger):
    """Health check HTTP trigger implementation."""
    
    def __init__(self):
        super().__init__("health_check")
    
    def get_allowed_methods(self) -> List[str]:
        """Health check only supports GET."""
        return ["GET"]
    
    def process_request(self, req: func.HttpRequest) -> Dict[str, Any]:
        """
        Perform comprehensive health check.
        
        Args:
            req: HTTP request (not used for health check)
            
        Returns:
            Health status data
        """
        config = get_config()
        health_data = {
            "status": "healthy",
            "components": {},
            "warnings": [],  # Track degraded/warning components
            "environment": {
                "bronze_storage_account": config.storage.bronze.account_name,
                "python_version": sys.version.split()[0],
                "function_runtime": "python",
                "health_check_version": "v2025-12-08_IDENTITY_ECHO"
            },
            "identity": {
                "database": {
                    "admin_identity_name": config.database.managed_identity_admin_name,
                    "use_managed_identity": config.database.use_managed_identity,
                    "auth_method": "managed_identity" if config.database.use_managed_identity else "password",
                    "note": "Single admin identity used for all database operations (ETL, OGC/STAC, TiTiler)"
                },
                "storage": {
                    "auth_method": "DefaultAzureCredential (system-assigned)",
                    "note": "Storage uses system-assigned managed identity via DefaultAzureCredential"
                }
            },
            "errors": []
        }
        
        # Check deployment configuration (critical for new tenant deployment)
        deployment_health = self._check_deployment_config()
        health_data["components"]["deployment_config"] = deployment_health
        # Note: Deployment config using defaults is a WARNING, not a failure
        # This allows the dev environment to work while alerting on production deployments
        if deployment_health.get("details", {}).get("config_status") == "using_defaults":
            health_data["errors"].append("Configuration using development defaults - set environment variables for production")

        # Check app mode configuration (07 DEC 2025 - Multi-Function App Architecture)
        app_mode_health = self._check_app_mode()
        health_data["components"]["app_mode"] = app_mode_health

        # Check hardware/runtime environment (21 DEC 2025)
        hardware_health = self._check_hardware_environment()
        health_data["components"]["hardware"] = hardware_health

        # Task routing coverage REMOVED (12 DEC 2025)
        # Moved to services/__init__.py (startup validation) and scripts/validate_config.py (pre-deployment)
        # This is configuration validation, not runtime health - doesn't belong in health endpoint

        # Check import validation (critical for application startup)
        import_health = self._check_import_validation()
        health_data["components"]["imports"] = import_health
        if import_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(import_health.get("errors", []))

        # Check critical storage containers (08 DEC 2025)
        storage_containers_health = self._check_storage_containers()
        health_data["components"]["storage_containers"] = storage_containers_health
        # Note: Missing containers are a warning, not a failure - the container can be created
        if storage_containers_health["status"] == "error":
            health_data["errors"].append("Storage container check failed")

        # Check Service Bus queues
        service_bus_health = self._check_service_bus_queues()
        health_data["components"]["service_bus"] = service_bus_health
        if service_bus_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(service_bus_health.get("errors", []))

        # Key Vault disabled - using environment variables only
        # vault_health = self._check_vault_configuration()
        # health_data["components"]["vault"] = vault_health
        health_data["components"]["vault"] = {
            "component": "vault", 
            "status": "disabled",
            "details": {"message": "Key Vault disabled - using environment variables only"},
            "checked_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Check database configuration
        db_config_health = self._check_database_configuration()
        health_data["components"]["database_config"] = db_config_health
        if db_config_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(db_config_health.get("errors", []))
        
        # Check database connectivity (optional)
        if self._should_check_database():
            db_health = self._check_database()
            health_data["components"]["database"] = db_health
            if db_health["status"] == "unhealthy":
                health_data["status"] = "unhealthy"
                health_data["errors"].extend(db_health.get("errors", []))

        # Check DuckDB analytical engine (optional component)
        # Controlled by ENABLE_DUCKDB_HEALTH_CHECK environment variable (default: false)
        config = get_config()
        if config.enable_duckdb_health_check:
            duckdb_health = self._check_duckdb()
            health_data["components"]["duckdb"] = duckdb_health
            # Note: DuckDB is optional - don't fail overall health if unavailable
            if duckdb_health["status"] == "error":
                health_data["errors"].append("DuckDB unavailable (optional analytical component)")
        else:
            health_data["components"]["duckdb"] = {
                "component": "duckdb",
                "status": "disabled",
                "details": {
                    "message": "DuckDB check disabled via config - module still available",
                    "enable_with": "Set ENABLE_DUCKDB_HEALTH_CHECK=true"
                },
                "checked_at": datetime.now(timezone.utc).isoformat()
            }

        # Check jobs registry (critical for job processing)
        jobs_health = self._check_jobs_registry()
        health_data["components"]["jobs"] = jobs_health
        if jobs_health["status"] == "unhealthy":
            health_data["status"] = "unhealthy"
            health_data["errors"].extend(jobs_health.get("errors", []))

        # Check PgSTAC (optional but important for STAC workflows)
        # Controlled by ENABLE_DATABASE_HEALTH_CHECK environment variable
        if self._should_check_database():
            pgstac_health = self._check_pgstac()
            health_data["components"]["pgstac"] = pgstac_health
            # Note: PgSTAC is optional - don't fail overall health if unavailable (6 DEC 2025)
            if pgstac_health["status"] == "error":
                health_data["errors"].append("PgSTAC unavailable (impacts STAC collection/item workflows)")
                # Add degraded capabilities info for clarity
                health_data["degraded_capabilities"] = ["STAC API", "STAC item discovery", "STAC collection browsing"]
                health_data["available_capabilities"] = [
                    "OGC Features API (vector queries)",
                    "TiTiler COG viewing (raster tiles)",
                    "Vector ETL (PostGIS)",
                    "Raster ETL (COG creation)"
                ]

            # Check system reference tables (admin0 boundaries for ISO3 attribution)
            system_tables_health = self._check_system_reference_tables()
            health_data["components"]["system_reference_tables"] = system_tables_health
            # Note: System reference tables are optional - don't fail overall health
            # Missing tables just means ISO3 country attribution won't be available
            if system_tables_health["status"] == "error":
                health_data["errors"].append("System reference tables unavailable (ISO3 country attribution disabled)")

            # Schema summary for remote database inspection (07 DEC 2025)
            schema_summary_health = self._check_schema_summary()
            health_data["components"]["schema_summary"] = schema_summary_health

        # Check TiTiler raster tile server (13 DEC 2025)
        # TiTiler is always an external Docker app - check its health endpoints
        titiler_health = self._check_titiler_health()
        health_data["components"]["titiler"] = titiler_health
        # TiTiler is optional for core ETL - don't fail overall health
        titiler_status = titiler_health.get("status")
        if titiler_status == "unhealthy":
            health_data["errors"].append("TiTiler unavailable (raster tile visualization disabled)")
        elif titiler_status == "warning":
            health_data["warnings"].append("TiTiler degraded - alive but /healthz failing (PGSTAC connection issue?)")
            # Set overall status to degraded if not already unhealthy
            if health_data["status"] == "healthy":
                health_data["status"] = "degraded"

        # Check OGC Features API (13 DEC 2025)
        # Can be self-hosted or external - check its health endpoint
        ogc_features_health = self._check_ogc_features_health()
        health_data["components"]["ogc_features"] = ogc_features_health
        # OGC Features is optional for core ETL - don't fail overall health
        if ogc_features_health.get("status") == "unhealthy":
            health_data["errors"].append("OGC Features API unavailable (vector feature queries disabled)")

        # Debug status - always include (07 DEC 2025)
        health_data["debug_status"] = config.get_debug_status()

        # Config sources - only include when DEBUG_MODE=true (07 DEC 2025)
        if config.debug_mode:
            config_sources = self._get_config_sources()
            health_data["config_sources"] = config_sources
            health_data["_debug_mode"] = True
            health_data["_debug_notice"] = "Verbose config sources included - DEBUG_MODE=true"

        return health_data
    
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
        from datetime import datetime, timezone
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
            self.logger.error(f"💥 [{self.trigger_name}] Health check error: {e}")
            
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
    
    def _check_storage_containers(self) -> Dict[str, Any]:
        """
        Check critical storage container existence for Bronze and Silver zones.

        Verifies that storage accounts are accessible and required containers exist:

        Bronze Zone (raw data input):
        - bronze-vectors: Raw vector uploads (Shapefiles, GeoJSON)
        - bronze-rasters: Raw raster uploads (GeoTIFF)

        Silver Zone (processed data):
        - silver-cogs: Cloud Optimized GeoTIFFs (COG output)
        - pickles: Vector ETL intermediate storage

        Updated 09 DEC 2025: Expanded to check Bronze/Silver accounts and critical containers.
        """
        def check_containers():
            from infrastructure.blob import BlobRepository
            from config.defaults import VectorDefaults, StorageDefaults
            from config import get_config

            config = get_config()
            result = {
                "zones": {},
                "summary": {
                    "total_containers_checked": 0,
                    "containers_exist": 0,
                    "containers_missing": 0,
                    "zones_accessible": 0,
                    "zones_error": 0
                }
            }

            # Define critical containers per zone
            # Format: (container_name, purpose, criticality)
            critical_containers = {
                "bronze": [
                    (config.storage.bronze.vectors, "Raw vector uploads (Shapefiles, GeoJSON)", "high"),
                    (config.storage.bronze.rasters, "Raw raster uploads (GeoTIFF)", "high"),
                ],
                "silver": [
                    (config.storage.silver.cogs, "Cloud Optimized GeoTIFFs (COG output)", "high"),
                    (VectorDefaults.PICKLE_CONTAINER, "Vector ETL intermediate storage", "high"),
                ]
            }

            for zone, containers in critical_containers.items():
                zone_result = {
                    "account": None,
                    "account_accessible": False,
                    "containers": {}
                }

                try:
                    # Get repository for zone
                    repo = BlobRepository.for_zone(zone)
                    zone_config = config.storage.get_account(zone)
                    zone_result["account"] = zone_config.account_name
                    zone_result["account_accessible"] = True
                    result["summary"]["zones_accessible"] += 1

                    # Check each critical container
                    for container_name, purpose, criticality in containers:
                        result["summary"]["total_containers_checked"] += 1

                        try:
                            exists = repo.container_exists(container_name)
                            if exists:
                                zone_result["containers"][container_name] = {
                                    "status": "exists",
                                    "purpose": purpose,
                                    "criticality": criticality
                                }
                                result["summary"]["containers_exist"] += 1
                            else:
                                zone_result["containers"][container_name] = {
                                    "status": "missing",
                                    "purpose": purpose,
                                    "criticality": criticality,
                                    "action_required": f"Create container '{container_name}' in {zone_config.account_name}"
                                }
                                result["summary"]["containers_missing"] += 1
                        except Exception as container_error:
                            zone_result["containers"][container_name] = {
                                "status": "error",
                                "purpose": purpose,
                                "criticality": criticality,
                                "error": str(container_error)[:200]
                            }
                            result["summary"]["containers_missing"] += 1

                except Exception as zone_error:
                    zone_result["account_accessible"] = False
                    zone_result["error"] = str(zone_error)[:200]
                    result["summary"]["zones_error"] += 1
                    # Still count containers as missing since we couldn't check them
                    result["summary"]["total_containers_checked"] += len(containers)
                    result["summary"]["containers_missing"] += len(containers)

                result["zones"][zone] = zone_result

            # Determine overall health based on missing containers
            if result["summary"]["containers_missing"] > 0 or result["summary"]["zones_error"] > 0:
                missing_list = []
                for zone, zone_data in result["zones"].items():
                    if zone_data.get("error"):
                        missing_list.append(f"{zone} zone inaccessible")
                    else:
                        for container, status in zone_data.get("containers", {}).items():
                            if status.get("status") != "exists":
                                missing_list.append(f"{zone}/{container}")

                result["error"] = f"Missing or inaccessible: {', '.join(missing_list)}"
                result["impact"] = "ETL operations may fail for affected data types"
                result["fix"] = "Create missing containers or check storage account access"

            return result

        return self.check_component_health(
            "storage_containers",
            check_containers,
            description="Bronze and Silver zone storage accounts and critical containers"
        )

    def _check_service_bus_queues(self) -> Dict[str, Any]:
        """
        Check Azure Service Bus queue health using ServiceBusRepository.

        Updated 03 JAN 2026: Enhanced error tracking and network diagnostics.
        All queues must be accessible for Service Bus to be healthy.

        Queues checked:
        - geospatial-jobs: Job orchestration + stage_complete signals
        - raster-tasks: Memory-intensive GDAL operations (low concurrency)
        - vector-tasks: DB-bound and lightweight operations (high concurrency)
        """
        def classify_error(error_str: str, exception: Exception) -> dict:
            """Classify Service Bus errors for actionable diagnostics."""
            error_lower = error_str.lower()
            exc_type = type(exception).__name__

            # DNS resolution failure
            if "name or service not known" in error_lower or "errno -2" in error_lower:
                return {
                    "error_type": "DNS_RESOLUTION",
                    "category": "network",
                    "error": error_str[:300],
                    "diagnosis": "Cannot resolve Service Bus namespace hostname",
                    "likely_causes": [
                        "SERVICE_BUS_NAMESPACE env var has wrong value",
                        "VNet DNS configuration issue",
                        "Private DNS zone not linked to VNet",
                        "Network isolation blocking DNS"
                    ],
                    "fix": "Verify SERVICE_BUS_NAMESPACE is correct FQDN (e.g., myns.servicebus.windows.net)"
                }

            # Socket/connection errors (VNet, firewall)
            if "socket" in error_lower or "connection refused" in error_lower or "errno 111" in error_lower:
                return {
                    "error_type": "CONNECTION_REFUSED",
                    "category": "network",
                    "error": error_str[:300],
                    "diagnosis": "TCP connection to Service Bus failed",
                    "likely_causes": [
                        "VNet/subnet not configured for Service Bus access",
                        "Private endpoint not configured",
                        "NSG blocking outbound port 5671/5672 (AMQP)",
                        "Firewall blocking Service Bus IPs"
                    ],
                    "fix": "Check VNet service endpoints or private endpoint configuration"
                }

            # Timeout errors
            if "timeout" in error_lower or "timed out" in error_lower:
                return {
                    "error_type": "TIMEOUT",
                    "category": "network",
                    "error": error_str[:300],
                    "diagnosis": "Connection to Service Bus timed out",
                    "likely_causes": [
                        "Network latency or congestion",
                        "Service Bus namespace overloaded",
                        "Partial network connectivity (packets dropping)"
                    ],
                    "fix": "Check network path and Service Bus namespace health in Azure portal"
                }

            # Authentication/authorization errors
            if "unauthorized" in error_lower or "401" in error_str or "403" in error_str:
                return {
                    "error_type": "AUTH_FAILED",
                    "category": "authentication",
                    "error": error_str[:300],
                    "diagnosis": "Authentication to Service Bus failed",
                    "likely_causes": [
                        "Managed identity not assigned Azure Service Bus Data Owner role",
                        "Connection string invalid or expired",
                        "Wrong Service Bus namespace"
                    ],
                    "fix": "Verify managed identity role assignment: az role assignment list --assignee <identity>"
                }

            # Queue not found
            if "not found" in error_lower or "404" in error_str or "MessagingEntityNotFoundError" in exc_type:
                return {
                    "error_type": "QUEUE_NOT_FOUND",
                    "category": "configuration",
                    "error": "Queue does not exist",
                    "diagnosis": "Queue has not been created in Service Bus namespace",
                    "likely_causes": [
                        "Queue never created",
                        "Queue was deleted",
                        "Wrong queue name in configuration"
                    ],
                    "fix": "Run schema rebuild: POST /api/dbadmin/maintenance?action=full-rebuild&confirm=yes"
                }

            # SSL/TLS errors
            if "ssl" in error_lower or "certificate" in error_lower:
                return {
                    "error_type": "TLS_ERROR",
                    "category": "security",
                    "error": error_str[:300],
                    "diagnosis": "TLS/SSL handshake failed",
                    "likely_causes": [
                        "Certificate validation failure",
                        "TLS version mismatch",
                        "Proxy intercepting TLS traffic"
                    ],
                    "fix": "Check if corporate proxy is intercepting traffic"
                }

            # Generic/unknown error
            return {
                "error_type": "UNKNOWN",
                "category": "unknown",
                "error": error_str[:300],
                "exception_type": exc_type,
                "diagnosis": "Unclassified Service Bus error",
                "likely_causes": ["See error message for details"],
                "fix": "Check Application Insights for full stack trace"
            }

        def check_service_bus():
            import socket
            from infrastructure.service_bus import ServiceBusRepository
            from config import get_config

            config = get_config()
            queue_status = {}

            # Network diagnostics - check DNS resolution before attempting connections
            namespace = config.service_bus_namespace
            dns_check = {"namespace": namespace}

            try:
                # Extract hostname (handle both FQDN and short name)
                hostname = namespace if "." in namespace else f"{namespace}.servicebus.windows.net"
                dns_check["hostname_used"] = hostname

                # Attempt DNS resolution
                ip_addresses = socket.getaddrinfo(hostname, 5671, socket.AF_UNSPEC, socket.SOCK_STREAM)
                resolved_ips = list(set([addr[4][0] for addr in ip_addresses]))
                dns_check["resolved"] = True
                dns_check["ip_addresses"] = resolved_ips[:5]  # Limit to 5 IPs
                dns_check["is_private_ip"] = any(
                    ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.168.")
                    for ip in resolved_ips
                )
                if dns_check["is_private_ip"]:
                    dns_check["note"] = "Private IP detected - using Private Endpoint or VNet integration"
            except socket.gaierror as e:
                dns_check["resolved"] = False
                dns_check["dns_error"] = str(e)
                dns_check["diagnosis"] = "DNS resolution failed - check VNet DNS or namespace name"

            queue_status["_network_diagnostics"] = dns_check

            # If DNS failed, we know connections will fail - but still try for specific errors
            try:
                service_bus_repo = ServiceBusRepository()
            except Exception as e:
                queue_status["_status"] = "unhealthy"
                queue_status["error"] = f"Failed to initialize ServiceBusRepository: {str(e)[:200]}"
                queue_status["_repository_error"] = classify_error(str(e), e)
                return queue_status

            # Check all 3 queues
            queues_to_check = [
                {"name": config.service_bus_jobs_queue, "purpose": "Job orchestration + stage_complete signals"},
                {"name": config.queues.raster_tasks_queue, "purpose": "Raster tasks (GDAL, low concurrency)"},
                {"name": config.queues.vector_tasks_queue, "purpose": "Vector tasks (DB, high concurrency)"}
            ]

            queues_accessible = 0
            queues_missing = 0
            queues_connection_error = 0
            error_categories = set()

            for queue_config in queues_to_check:
                queue_name = queue_config["name"]
                try:
                    # Peek at queue to verify connectivity and get approximate count
                    message_count = service_bus_repo.get_queue_length(queue_name)
                    queue_status[queue_name] = {
                        "status": "accessible",
                        "purpose": queue_config["purpose"],
                        "approximate_message_count": message_count,
                        "note": "Count is approximate (peek limit: 100)"
                    }
                    queues_accessible += 1

                except Exception as e:
                    error_info = classify_error(str(e), e)
                    error_categories.add(error_info["category"])

                    if error_info["error_type"] == "QUEUE_NOT_FOUND":
                        queue_status[queue_name] = {
                            "status": "missing",
                            "purpose": queue_config["purpose"],
                            **error_info
                        }
                        queues_missing += 1
                    else:
                        queue_status[queue_name] = {
                            "status": "connection_error",
                            "purpose": queue_config["purpose"],
                            **error_info
                        }
                        queues_connection_error += 1

            # Summary with all error counts
            total_errors = queues_missing + queues_connection_error
            all_healthy = total_errors == 0

            queue_status["_summary"] = {
                "total_queues": len(queues_to_check),
                "accessible": queues_accessible,
                "missing": queues_missing,
                "connection_errors": queues_connection_error,
                "error_categories": list(error_categories) if error_categories else None,
                "all_queues_healthy": all_healthy,
                "multi_function_app_ready": all_healthy
            }

            # Repository info
            queue_status["_repository_info"] = {
                "singleton_id": id(service_bus_repo),
                "type": "ServiceBusRepository",
                "namespace": namespace,
                "connection_method": "managed_identity" if not os.getenv("SERVICE_BUS_CONNECTION_STRING") else "connection_string"
            }

            # Set explicit status - ANY error means unhealthy
            if not all_healthy:
                queue_status["_status"] = "unhealthy"

                # Create top-level error summary for check_component_health detection
                error_parts = []
                if queues_connection_error > 0:
                    queue_status["error"] = f"{queues_connection_error} queue(s) with connection errors"
                    error_parts.append(f"{queues_connection_error} connection error(s)")
                if queues_missing > 0:
                    error_parts.append(f"{queues_missing} missing queue(s)")

                queue_status["_error_summary"] = {
                    "message": " + ".join(error_parts),
                    "categories": list(error_categories),
                    "recommendation": self._get_service_bus_fix_recommendation(error_categories)
                }

            return queue_status

        return self.check_component_health(
            "service_bus",
            check_service_bus,
            description="Azure Service Bus message queues for job and task orchestration"
        )

    def _get_service_bus_fix_recommendation(self, error_categories: set) -> str:
        """Get prioritized fix recommendation based on error categories."""
        if "network" in error_categories:
            return "PRIORITY: Check VNet configuration, Private Endpoints, and DNS settings"
        if "authentication" in error_categories:
            return "Check managed identity role assignments (Azure Service Bus Data Owner)"
        if "configuration" in error_categories:
            return "Run full-rebuild to create missing queues"
        return "Check Application Insights for detailed error logs"

    def _check_database(self) -> Dict[str, Any]:
        """Enhanced PostgreSQL database health check with query metrics.

        IMPORTANT: Uses PostgreSQLRepository which respects USE_MANAGED_IDENTITY setting.
        This ensures health check uses the same authentication method as the application.
        """
        def check_pg():
            import psycopg
            import time
            from config import get_config
            from infrastructure.postgresql import PostgreSQLRepository

            config = get_config()
            start_time = time.time()

            # Use PostgreSQLRepository to get connection string (respects managed identity)
            # This ensures health check uses same auth method as application
            try:
                repo = PostgreSQLRepository(config=config)
                conn_str = repo.conn_string
            except Exception as repo_error:
                # If repository initialization fails, return error immediately
                return {
                    "component": "database",
                    "status": "unhealthy",
                    "error": f"Failed to initialize PostgreSQL repository: {str(repo_error)}",
                    "error_type": type(repo_error).__name__,
                    "checked_at": time.time()
                }

            # Use autocommit mode to allow subtransactions for isolated tests
            with psycopg.connect(conn_str, autocommit=True) as conn:
                with conn.cursor() as cur:
                    # Track connection time
                    connection_time_ms = round((time.time() - start_time) * 1000, 2)
                    # Check PostgreSQL version
                    cur.execute("SELECT version()")
                    pg_version = cur.fetchone()[0]
                    
                    # Check PostGIS version
                    cur.execute("SELECT PostGIS_Version()")
                    postgis_version = cur.fetchone()[0]
                    
                    # Check app schema exists (for jobs and tasks tables)
                    try:
                        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (config.app_schema,))
                        app_schema_exists = cur.fetchone() is not None
                    except Exception as e:
                        self.logger.debug(f"Could not check app schema: {e}")
                        app_schema_exists = False

                    # Check postgis schema exists (for STAC data)
                    try:
                        cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (config.postgis_schema,))
                        postgis_schema_exists = cur.fetchone() is not None
                    except Exception as e:
                        self.logger.debug(f"Could not check postgis schema: {e}")
                        postgis_schema_exists = False

                    # Count STAC items (optional) - use pg_stat for performance (12 DEC 2025)
                    try:
                        cur.execute("""
                            SELECT n_live_tup FROM pg_stat_user_tables
                            WHERE schemaname = %s AND relname = 'items'
                        """, (config.postgis_schema,))
                        result = cur.fetchone()
                        stac_count = result[0] if result else 0
                    except Exception as e:
                        self.logger.debug(f"Could not count STAC items: {e}")
                        stac_count = "unknown"
                    
                    # Ensure app tables exist and validate schema
                    # NOTE: Schema manager uses its own connection - skip during health check
                    # to avoid transaction context conflicts
                    app_tables_status = {}
                    table_management_results = {}

                    if app_schema_exists:
                        # Simple table existence check (no schema manager - it creates its own connection)
                        try:
                            for table_name in ['jobs', 'tasks']:
                                cur.execute("""
                                    SELECT EXISTS (
                                        SELECT FROM information_schema.tables
                                        WHERE table_schema = %s
                                        AND table_name = %s
                                    )
                                """, (config.app_schema, table_name))
                                table_exists = cur.fetchone()[0]
                                app_tables_status[table_name] = table_exists
                                table_management_results[table_name] = "exists" if table_exists else "missing"
                        except Exception as table_check_error:
                            table_management_results['table_check_error'] = f"error: {str(table_check_error)}"
                            app_tables_status['jobs'] = False
                            app_tables_status['tasks'] = False
                    
                    # DETAILED SCHEMA INSPECTION - Added for debugging function signature mismatches
                    # NOTE: Each section wrapped in try-except to prevent transaction cascade failures
                    detailed_schema_info = {}

                    # Inspect table columns (separate transaction to avoid contamination)
                    try:
                        for table_name in ['jobs', 'tasks']:
                            cur.execute("""
                                SELECT column_name, data_type, is_nullable, column_default
                                FROM information_schema.columns
                                WHERE table_schema = %s AND table_name = %s
                                ORDER BY ordinal_position
                            """, (config.app_schema, table_name))

                            columns = cur.fetchall()
                            detailed_schema_info[f"{table_name}_columns"] = [
                                {
                                    "column_name": col[0],
                                    "data_type": col[1],
                                    "is_nullable": col[2],
                                    "column_default": col[3]
                                } for col in columns
                            ]
                    except Exception as col_error:
                        detailed_schema_info['columns_inspection_error'] = f"Column inspection failed: {str(col_error)}"

                    # Inspect PostgreSQL function signatures (separate transaction)
                    try:
                        cur.execute("""
                            SELECT
                                routine_name,
                                data_type as return_type,
                                routine_definition
                            FROM information_schema.routines
                            WHERE routine_schema = %s
                            AND routine_name IN ('check_job_completion', 'complete_task_and_check_stage', 'advance_job_stage')
                            ORDER BY routine_name
                        """, (config.app_schema,))

                        functions = cur.fetchall()
                        detailed_schema_info['postgresql_functions'] = [
                            {
                                "function_name": func[0],
                                "return_type": func[1],
                                "definition_snippet": func[2][:200] + "..." if func[2] and len(func[2]) > 200 else func[2]
                            } for func in functions
                        ]
                    except Exception as func_sig_error:
                        detailed_schema_info['function_signature_error'] = f"Function signature inspection failed: {str(func_sig_error)}"

                    # Test function call (isolated transaction - failure won't affect subsequent queries)
                    try:
                        with conn.transaction():
                            cur.execute(f"SELECT job_complete, final_stage, total_tasks, completed_tasks, task_results FROM {config.app_schema}.check_job_completion('test_job_id')")
                            detailed_schema_info['function_test'] = "SUCCESS - Function signature matches query"
                    except Exception as func_error:
                        # Transaction auto-rolled back by context manager
                        # Cursor remains valid for new queries
                        detailed_schema_info['function_test'] = f"ERROR: {str(func_error)}"
                        detailed_schema_info['function_error_type'] = type(func_error).__name__
                    
                    # NOTE (12 DEC 2025): Query metrics REMOVED for health check performance
                    # Job/task status breakdown and function tests moved to /api/dbadmin/metrics
                    # These were adding 5+ seconds and multiple transactions to health check
                    query_metrics = {
                        "connection_time_ms": connection_time_ms,
                        "note": "Detailed metrics available at /api/dbadmin/stats",
                        "metrics_removed_reason": "Performance optimization - health check should be <5s"
                    }
                    
                    # Determine if critical app schema is missing (08 DEC 2025)
                    # App schema is CRITICAL - without it, job/task orchestration is non-functional
                    tables_ready = all(status is True for status in app_tables_status.values()) if app_tables_status else False

                    # Build error message if app schema is missing or tables not ready
                    error_msg = None
                    impact_msg = None
                    if not app_schema_exists:
                        error_msg = f"CRITICAL: App schema '{config.app_schema}' does not exist - run full-rebuild"
                        impact_msg = "Job/task orchestration completely unavailable"
                    elif not tables_ready:
                        error_msg = f"App schema exists but required tables missing: {table_management_results}"
                        impact_msg = "Job/task orchestration may fail"

                    result = {
                        "postgresql_version": pg_version.split()[0],
                        "postgis_version": postgis_version,
                        "connection": "successful",
                        "connection_time_ms": connection_time_ms,
                        "schema_health": {
                            "app_schema_name": config.app_schema,
                            "app_schema_exists": app_schema_exists,
                            "app_schema_critical": True,  # Indicates this is required for core functionality
                            "postgis_schema_name": config.postgis_schema,
                            "postgis_schema_exists": postgis_schema_exists,
                            "app_tables": app_tables_status if app_schema_exists else "schema_not_found"
                        },
                        "table_management": {
                            "auto_creation_enabled": True,
                            "operations_performed": table_management_results,
                            "tables_ready": tables_ready
                        },
                        "stac_data": {
                            "items_count": stac_count,
                            "schema_accessible": postgis_schema_exists
                        },
                        "detailed_schema_inspection": detailed_schema_info,
                        "query_performance": query_metrics
                    }

                    # Add error field if app schema issues detected (triggers unhealthy status)
                    if error_msg:
                        result["error"] = error_msg
                        result["impact"] = impact_msg
                        result["fix"] = "POST /api/dbadmin/maintenance/full-rebuild?confirm=yes"

                    return result

        return self.check_component_health(
            "database",
            check_pg,
            description="PostgreSQL/PostGIS database connectivity and query metrics"
        )
    
    # NOTE (12 DEC 2025): _check_vault_configuration REMOVED
    # Key Vault is disabled - using environment variables only
    # Dead code removed for maintainability
    
    def _check_database_configuration(self) -> Dict[str, Any]:
        """Check PostgreSQL database configuration."""
        def check_db_config():
            config = get_config()

            # Required environment variables for database connection
            # Note: KEY_VAULT is optional - system uses env vars for password (08 DEC 2025)
            required_env_vars = {
                "POSTGIS_DATABASE": os.getenv("POSTGIS_DATABASE"),
                "POSTGIS_HOST": os.getenv("POSTGIS_HOST"),
                "POSTGIS_USER": os.getenv("POSTGIS_USER"),
                "POSTGIS_PORT": os.getenv("POSTGIS_PORT")
            }

            # Optional environment variables
            # KEY_VAULT is optional - disabled by default, using environment variables (08 DEC 2025)
            optional_env_vars = {
                "KEY_VAULT": os.getenv("KEY_VAULT"),
                "KEY_VAULT_DATABASE_SECRET": os.getenv("KEY_VAULT_DATABASE_SECRET"),
                "POSTGIS_PASSWORD": bool(os.getenv("POSTGIS_PASSWORD")),
                "POSTGIS_SCHEMA": os.getenv("POSTGIS_SCHEMA", "geo"),
                "APP_SCHEMA": os.getenv("APP_SCHEMA", "app")
            }
            
            # Check for missing required variables
            missing_vars = []
            present_vars = {}
            
            for var_name, var_value in required_env_vars.items():
                if var_value:
                    present_vars[var_name] = var_value
                else:
                    missing_vars.append(var_name)
            
            # Configuration from loaded config
            config_values = {
                "postgis_host": config.postgis_host,
                "postgis_port": config.postgis_port,
                "postgis_user": config.postgis_user,
                "postgis_database": config.postgis_database,
                "postgis_schema": config.postgis_schema,
                "app_schema": config.app_schema,
                "key_vault_name": config.key_vault_name,
                "key_vault_database_secret": config.key_vault_database_secret,
                "postgis_password_configured": bool(config.postgis_password)
            }
            
            return {
                "required_env_vars_present": present_vars,
                "missing_required_vars": missing_vars,
                "optional_env_vars": optional_env_vars,
                "loaded_config_values": config_values,
                "configuration_complete": len(missing_vars) == 0
            }

        return self.check_component_health(
            "database_config",
            check_db_config,
            description="PostgreSQL connection environment variables and configuration"
        )
    
    def _should_check_database(self) -> bool:
        """Check if database health check is enabled."""
        return os.getenv("ENABLE_DATABASE_HEALTH_CHECK", "false").lower() == "true"
    
    def _check_import_validation(self) -> Dict[str, Any]:
        """
        Lightweight import validation check (12 DEC 2025 - Performance Fix).

        IMPORTANT: This check verifies that critical modules are loaded in sys.modules
        rather than re-importing them. Re-importing triggers a cascade through
        function_app.py → CoreMachine → all jobs/handlers → GDAL/rasterio which
        takes 75+ seconds and causes health check timeouts.

        Since this health endpoint can only run if function_app.py already loaded
        successfully, re-validating imports is redundant - if imports had failed,
        this endpoint wouldn't be callable in the first place.

        Returns:
            Dict with lightweight import validation status
        """
        def check_imports():
            # Check critical modules are in sys.modules (already loaded at startup)
            # No new imports triggered - just checking what's already there
            critical_modules = {
                'azure.functions': 'Azure Functions runtime',
                'pydantic': 'Data validation library',
                'psycopg': 'PostgreSQL adapter',
                'azure.identity': 'Azure authentication',
                'azure.storage.blob': 'Azure Blob Storage client',
            }

            module_status = {}
            for module, description in critical_modules.items():
                module_status[module] = {
                    'loaded': module in sys.modules,
                    'description': description
                }

            all_loaded = all(status['loaded'] for status in module_status.values())
            loaded_count = sum(1 for status in module_status.values() if status['loaded'])

            return {
                "overall_success": all_loaded,
                "validation_summary": f"All critical modules loaded" if all_loaded else f"Missing modules detected",
                "statistics": {
                    "modules_checked": len(critical_modules),
                    "modules_loaded": loaded_count,
                    "success_rate_percent": round(loaded_count / len(critical_modules) * 100, 1)
                },
                "critical_dependencies": module_status,
                "note": "Lightweight check via sys.modules - full validation runs at startup only",
                "rationale": "If this endpoint responds, function_app.py loaded successfully, proving all imports work"
            }

        return self.check_component_health(
            "import_validation",
            check_imports,
            description="Python module imports (lightweight sys.modules check)"
        )

    def _check_duckdb(self) -> Dict[str, Any]:
        """
        Check DuckDB analytical engine health (optional component).

        DuckDB is an optional analytical query engine used for:
        - Serverless queries over Azure Blob Storage Parquet files
        - Spatial analytics with PostGIS-like ST_* functions
        - GeoParquet exports for Gold tier data products

        This component is NOT critical for core operations - health check
        will not fail if DuckDB is unavailable or not installed.

        Returns:
            Dict with DuckDB health status, extensions, and connection info
        """
        def check_duckdb():
            try:
                # Try to import DuckDB repository
                from infrastructure.factory import RepositoryFactory

                # Create DuckDB repository singleton
                duckdb_repo = RepositoryFactory.create_duckdb_repository()

                # Get comprehensive health check from repository
                health_result = duckdb_repo.health_check()

                # Add component metadata
                health_result["component_type"] = "analytical_engine"
                health_result["optional"] = True
                health_result["purpose"] = "Serverless Parquet queries and GeoParquet exports"

                return health_result

            except ImportError as e:
                # DuckDB not installed - this is OK, it's optional
                return {
                    "status": "not_installed",
                    "optional": True,
                    "message": "DuckDB not installed (optional dependency)",
                    "install_command": "pip install duckdb>=1.1.0 pyarrow>=10.0.0",
                    "impact": "GeoParquet exports and serverless blob queries unavailable"
                }
            except Exception as e:
                # Other errors during initialization
                import traceback
                return {
                    "status": "error",
                    "optional": True,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "Analytical queries and GeoParquet exports unavailable"
                }

        return self.check_component_health(
            "duckdb",
            check_duckdb,
            description="DuckDB analytical engine for serverless queries and GeoParquet exports"
        )

    def _check_jobs_registry(self) -> Dict[str, Any]:
        """
        Check jobs registry status and available job types.

        This provides visibility into which jobs are registered and available,
        helping diagnose deployment issues where jobs fail to register.

        Returns:
            Dict with jobs registry health status including:
            - available_jobs: List of registered job type names
            - total_jobs: Count of registered jobs
            - registry_location: Where jobs are registered
            - validation_performed: Whether validation was successful
        """
        def check_jobs():
            from jobs import ALL_JOBS

            job_types = sorted(list(ALL_JOBS.keys()))

            return {
                "available_jobs": job_types,
                "total_jobs": len(job_types),
                "registry_location": "jobs/__init__.py",
                "validation_performed": True,
                "registry_type": "explicit",
                "note": "Jobs are explicitly registered in jobs/__init__.py ALL_JOBS dict"
            }

        return self.check_component_health(
            "jobs",
            check_jobs,
            description="Job registry showing available ETL job types and their handlers"
        )

    def _check_pgstac(self) -> Dict[str, Any]:
        """
        Check PgSTAC (PostgreSQL STAC extension) health.

        This provides visibility into PgSTAC installation status and critical table availability,
        particularly the pgstac.searches table which is required for TiTiler integration.

        Returns:
            Dict with PgSTAC health status including:
            - pgstac_version: Version string from pgstac.get_version()
            - schema_exists: Whether pgstac schema exists
            - critical_tables: Status of collections, items, searches tables
            - searches_table_exists: Specific check for searches table (required for search registration)
            - table_counts: Row counts for collections and items
        """
        def check_pgstac():
            from infrastructure.postgresql import PostgreSQLRepository
            from config import get_config

            config = get_config()
            repo = PostgreSQLRepository(schema_name='pgstac')

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Check if pgstac schema exists
                        cur.execute(
                            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'pgstac') as schema_exists"
                        )
                        schema_exists = cur.fetchone()['schema_exists']

                        if not schema_exists:
                            return {
                                "schema_exists": False,
                                "installed": False,
                                "error": "PgSTAC schema not found - run /api/stac/setup to install",
                                "impact": "STAC collections and items cannot be created"
                            }

                        # Get PgSTAC version
                        pgstac_version = None
                        try:
                            cur.execute("SELECT pgstac.get_version() as version")
                            pgstac_version = cur.fetchone()['version']
                        except Exception as ver_error:
                            pgstac_version = f"error: {str(ver_error)[:100]}"

                        # Check critical tables existence
                        critical_tables = {}
                        for table_name in ['collections', 'items', 'searches']:
                            cur.execute("""
                                SELECT EXISTS (
                                    SELECT FROM information_schema.tables
                                    WHERE table_schema = 'pgstac'
                                    AND table_name = %s
                                ) as table_exists
                            """, (table_name,))
                            table_exists = cur.fetchone()['table_exists']
                            critical_tables[table_name] = table_exists

                        # Get row counts for collections and items - use pg_stat for performance (12 DEC 2025)
                        table_counts = {}

                        if critical_tables.get('collections', False):
                            try:
                                cur.execute("""
                                    SELECT n_live_tup FROM pg_stat_user_tables
                                    WHERE schemaname = 'pgstac' AND relname = 'collections'
                                """)
                                result = cur.fetchone()
                                table_counts['collections'] = result['n_live_tup'] if result else 0
                            except Exception:
                                table_counts['collections'] = "error"
                        else:
                            table_counts['collections'] = "table_missing"

                        if critical_tables.get('items', False):
                            try:
                                cur.execute("""
                                    SELECT n_live_tup FROM pg_stat_user_tables
                                    WHERE schemaname = 'pgstac' AND relname = 'items'
                                """)
                                result = cur.fetchone()
                                table_counts['items'] = result['n_live_tup'] if result else 0
                            except Exception:
                                table_counts['items'] = "error"
                        else:
                            table_counts['items'] = "table_missing"

                        # Specific check for searches table (critical for TiTiler integration)
                        searches_table_exists = critical_tables.get('searches', False)

                        # Check critical functions for search registration (18 NOV 2025)
                        critical_functions = {}
                        function_warnings = []

                        try:
                            # Check for search_tohash and search_hash functions
                            cur.execute("""
                                SELECT p.proname
                                FROM pg_proc p
                                JOIN pg_namespace n ON p.pronamespace = n.oid
                                WHERE n.nspname = 'pgstac'
                                AND p.proname IN ('search_tohash', 'search_hash')
                            """)
                            functions_found = [row['proname'] for row in cur.fetchall()]

                            critical_functions['search_tohash'] = 'search_tohash' in functions_found
                            critical_functions['search_hash'] = 'search_hash' in functions_found

                            # Check if searches table has GENERATED hash column
                            if searches_table_exists:
                                try:
                                    cur.execute("""
                                        SELECT column_name, is_generated
                                        FROM information_schema.columns
                                        WHERE table_schema = 'pgstac'
                                        AND table_name = 'searches'
                                        AND column_name = 'hash'
                                    """)
                                    hash_column = cur.fetchone()

                                    if hash_column and hash_column.get('is_generated') == 'ALWAYS':
                                        critical_functions['searches_hash_column_generated'] = True
                                    else:
                                        critical_functions['searches_hash_column_generated'] = False
                                        function_warnings.append("searches.hash is not a GENERATED column")
                                except Exception:
                                    critical_functions['searches_hash_column_generated'] = None

                            # Generate warnings for missing functions
                            if not critical_functions['search_tohash']:
                                function_warnings.append("Missing function: pgstac.search_tohash()")
                            if not critical_functions['search_hash']:
                                function_warnings.append("Missing function: pgstac.search_hash()")

                        except Exception as func_error:
                            critical_functions['error'] = str(func_error)[:100]

                        # Determine overall health status
                        all_tables_exist = all(critical_tables.values())
                        all_functions_exist = critical_functions.get('search_tohash', False) and critical_functions.get('search_hash', False)

                        result = {
                            "schema_exists": True,
                            "installed": True,
                            "pgstac_version": pgstac_version,
                            "critical_tables": critical_tables,
                            "searches_table_exists": searches_table_exists,
                            "critical_functions": critical_functions,
                            "table_counts": table_counts,
                            "all_critical_tables_present": all_tables_exist,
                            "all_critical_functions_present": all_functions_exist,
                            "criticality": "medium"  # Not required for single raster workflows
                        }

                        # Add warnings/errors if issues detected (08 DEC 2025)
                        warnings = []

                        if not searches_table_exists:
                            warnings.append("pgstac.searches table missing - search registration will fail")

                        if not all_functions_exist:
                            warnings.extend(function_warnings)
                            warnings.append("Search registration will fail - run /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes")

                        if warnings:
                            result["warnings"] = warnings
                            result["impact"] = "Cannot register pgSTAC searches for TiTiler visualization"
                            result["fix"] = "Run /api/dbadmin/maintenance/pgstac/redeploy?confirm=yes to reinstall pgSTAC"
                            # Add error field to trigger unhealthy status when critical tables/functions missing
                            if not all_tables_exist or not all_functions_exist:
                                result["error"] = f"PgSTAC incomplete: tables_ok={all_tables_exist}, functions_ok={all_functions_exist}"

                        return result

            except Exception as e:
                import traceback
                return {
                    "schema_exists": False,
                    "installed": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "PgSTAC health check failed - STAC operations may be impacted"
                }

        return self.check_component_health(
            "pgstac",
            check_pgstac,
            description="PgSTAC extension for STAC catalog storage and TiTiler integration"
        )

    def _check_system_reference_tables(self) -> Dict[str, Any]:
        """
        Check system reference tables required for spatial operations.

        System reference tables include:
        - admin0 boundaries - Country boundaries for ISO3 attribution

        Resolution order (23 DEC 2025):
        1. Check PromoteService for system-reserved dataset with role 'admin0_boundaries'
        2. Fall back to config default (geo.curated_admin0)

        These tables are used for enriching STAC items with country codes and
        for H3 grid generation with land/ocean filtering.

        Returns:
            Dict with system reference tables health status including:
            - admin0_table: Resolved table name (from promote service or config)
            - admin0_source: Where table name came from ('promote_service' or 'config_default')
            - promoted_dataset: If from promote service, the promoted_id
            - exists: Whether table exists in database
            - row_count: Number of country records loaded
            - columns: Required column availability (iso3, geom, name)
            - spatial_index: Whether GIST index exists for query performance
            - ready_for_attribution: Boolean indicating readiness for ISO3 attribution
        """
        def check_system_tables():
            from infrastructure.postgresql import PostgreSQLRepository

            repo = PostgreSQLRepository()

            # Resolution: ONLY via promote service - no fallback (23 DEC 2025)
            admin0_table = None
            admin0_source = None
            promoted_dataset_info = None
            promote_error_msg = None

            try:
                from services.promote_service import PromoteService
                from core.models.promoted import SystemRole

                promote_service = PromoteService()
                promoted = promote_service.get_by_system_role(SystemRole.ADMIN0_BOUNDARIES.value)

                if promoted:
                    # Get table name from STAC item properties (24 DEC 2025)
                    # STAC items have postgis:schema and postgis:table properties
                    stac_id = promoted.get('stac_collection_id') or promoted.get('stac_item_id')
                    if stac_id:
                        # Try to get actual table from STAC item properties
                        try:
                            from infrastructure.pgstac_bootstrap import get_item_by_id
                            # Pass collection_id for pgstac partitioned lookup (24 DEC 2025)
                            # Vector items go to 'system-vectors' collection
                            collection_id = 'system-vectors' if stac_id.startswith('postgis-') else None
                            stac_item = get_item_by_id(stac_id, collection_id=collection_id)
                            if stac_item and 'error' not in stac_item:
                                props = stac_item.get('properties', {})
                                postgis_schema = props.get('postgis:schema', 'geo')
                                postgis_table = props.get('postgis:table')
                                if postgis_table:
                                    admin0_table = f"{postgis_schema}.{postgis_table}"
                                else:
                                    # Fallback: parse from asset href (24 DEC 2025)
                                    # Asset href format: postgis://host/db/schema.table
                                    assets = stac_item.get('assets', {})
                                    data_asset = assets.get('data', {})
                                    href = data_asset.get('href', '')
                                    if href.startswith('postgis://') and '/' in href:
                                        # Extract schema.table from last path segment
                                        table_part = href.split('/')[-1]
                                        if '.' in table_part:
                                            admin0_table = table_part
                                        else:
                                            admin0_table = f"geo.{stac_id}"
                                    else:
                                        admin0_table = f"geo.{stac_id}"
                            else:
                                # STAC item not found - use stac_id as fallback
                                admin0_table = f"geo.{stac_id}"
                        except Exception as stac_err:
                            self.logger.debug(f"STAC item lookup failed: {stac_err}")
                            admin0_table = f"geo.{stac_id}"

                        admin0_source = "promote_service"
                        promoted_dataset_info = {
                            "promoted_id": promoted.get('promoted_id'),
                            "stac_type": "collection" if promoted.get('stac_collection_id') else "item",
                            "stac_id": stac_id,
                            "system_role": promoted.get('system_role'),
                            "is_system_reserved": promoted.get('is_system_reserved', False)
                        }
            except Exception as promote_error:
                promote_error_msg = str(promote_error)[:200]
                self.logger.debug(f"Promote service lookup failed: {promote_error}")

            # NO FALLBACK - if not found in promote service, report as not configured
            if not admin0_table:
                return {
                    "admin0_table": None,
                    "admin0_source": "not_configured",
                    "exists": False,
                    "error": "No system-reserved dataset found with role 'admin0_boundaries'",
                    "impact": "ISO3 country attribution and H3 land filtering unavailable",
                    "fix": "1. Create admin0 table via process_vector job\n2. Promote with: POST /api/promote {is_system_reserved: true, system_role: 'admin0_boundaries'}",
                    "promote_service_error": promote_error_msg
                }

            # Parse schema.table
            if '.' in admin0_table:
                schema, table = admin0_table.split('.', 1)
            else:
                schema, table = 'geo', admin0_table

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        # Check table exists
                        cur.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables
                                WHERE table_schema = %s AND table_name = %s
                            ) as table_exists
                        """, (schema, table))
                        table_exists = cur.fetchone()['table_exists']

                        if not table_exists:
                            result = {
                                "admin0_table": admin0_table,
                                "admin0_source": admin0_source,
                                "exists": False,
                                "error": f"Table {admin0_table} not found",
                                "impact": "ISO3 country attribution will be unavailable for STAC items",
                                "fix": "Run process_vector job to create admin0 table, then promote with system_role='admin0_boundaries'"
                            }
                            if promoted_dataset_info:
                                result["promoted_dataset"] = promoted_dataset_info
                                result["note"] = "Promoted dataset exists but referenced table is missing"
                            return result

                        # Check required columns
                        cur.execute("""
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = %s AND table_name = %s
                        """, (schema, table))
                        columns = [row['column_name'] for row in cur.fetchall()]

                        # Accept both iso3 and iso_a3 as valid ISO3 column names
                        has_iso3 = 'iso3' in columns or 'iso_a3' in columns
                        has_geom = 'geom' in columns or 'geometry' in columns
                        has_name = 'name' in columns or 'nam_0' in columns

                        # Check row count - use pg_stat for performance (12 DEC 2025)
                        row_count = 0
                        try:
                            cur.execute("""
                                SELECT n_live_tup FROM pg_stat_user_tables
                                WHERE schemaname = %s AND relname = %s
                            """, (schema, table))
                            result = cur.fetchone()
                            row_count = result['n_live_tup'] if result else 0
                        except Exception:
                            row_count = "error"

                        # Check spatial index exists
                        cur.execute("""
                            SELECT COUNT(*) > 0 as has_gist_index
                            FROM pg_indexes
                            WHERE schemaname = %s AND tablename = %s
                            AND indexdef LIKE '%%USING gist%%'
                        """, (schema, table))
                        has_spatial_index = cur.fetchone()['has_gist_index']

                        # Build result
                        ready = has_iso3 and has_geom and isinstance(row_count, int) and row_count > 0

                        # Determine which column names were found
                        iso3_col = 'iso3' if 'iso3' in columns else ('iso_a3' if 'iso_a3' in columns else None)
                        geom_col = 'geom' if 'geom' in columns else ('geometry' if 'geometry' in columns else None)
                        name_col = 'name' if 'name' in columns else ('nam_0' if 'nam_0' in columns else None)

                        result = {
                            "admin0_table": admin0_table,
                            "admin0_source": admin0_source,
                            "exists": True,
                            "row_count": row_count,
                            "columns": {
                                "iso3": iso3_col,
                                "geom": geom_col,
                                "name": name_col
                            },
                            "spatial_index": has_spatial_index,
                            "ready_for_attribution": ready,
                            "criticality": "low"  # Optional - only affects ISO3 country attribution
                        }

                        # Add promoted dataset info if resolved via promote service
                        if promoted_dataset_info:
                            result["promoted_dataset"] = promoted_dataset_info

                        # Add warnings if issues detected
                        warnings = []
                        if not has_iso3:
                            warnings.append("Missing required column: iso3")
                        if not has_geom:
                            warnings.append("Missing required column: geom")
                        if not has_spatial_index:
                            warnings.append("No GIST spatial index - queries will be slow")
                        if isinstance(row_count, int) and row_count == 0:
                            warnings.append("Table is empty - no country boundaries loaded")

                        if warnings:
                            result["warnings"] = warnings
                            result["impact"] = "ISO3 country attribution may fail or be incomplete"
                            result["fix"] = "Ensure table has iso3, geom columns with data and GIST index"

                        return result

            except Exception as e:
                import traceback
                result = {
                    "admin0_table": admin0_table,
                    "admin0_source": admin0_source,
                    "exists": False,
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500],
                    "impact": "System reference tables check failed"
                }
                if promoted_dataset_info:
                    result["promoted_dataset"] = promoted_dataset_info
                return result

        return self.check_component_health(
            "system_reference_tables",
            check_system_tables,
            description="Reference data tables for ISO3 country attribution and spatial enrichment"
        )

    def _check_deployment_config(self) -> Dict[str, Any]:
        """
        Check if deployment configuration is properly set for this Azure tenant.

        Validates that tenant-specific values (storage accounts, URLs, managed identities)
        have been overridden from their development defaults. Uses AzureDefaults class
        from config/defaults.py to detect default values.

        This check helps identify when deploying to a new Azure tenant whether
        all required environment variables have been properly configured.

        Returns:
            Dict with deployment configuration validation status including:
            - config_status: "configured" | "using_defaults" | "partial"
            - issues: List of configuration issues detected
            - defaults_detected: Dict of fields still using development defaults
            - environment_vars_set: Dict of which env vars were found
            - deployment_ready: Boolean indicating readiness for production
        """
        def check_deployment():
            config = get_config()

            issues = []
            defaults_detected = {}
            env_vars_set = {}

            # Check storage accounts (zone-specific - 08 DEC 2025)
            bronze_account = config.storage.bronze.account_name
            if bronze_account == StorageDefaults.DEFAULT_ACCOUNT_NAME:
                defaults_detected['bronze_storage_account'] = {
                    'current_value': bronze_account,
                    'default_value': StorageDefaults.DEFAULT_ACCOUNT_NAME,
                    'env_var': 'BRONZE_STORAGE_ACCOUNT'
                }
                issues.append(f"Bronze storage using development default: {bronze_account}")
            env_vars_set['BRONZE_STORAGE_ACCOUNT'] = bool(os.getenv('BRONZE_STORAGE_ACCOUNT'))

            # Check TiTiler URL
            titiler_url = config.titiler_base_url
            if titiler_url == AzureDefaults.TITILER_BASE_URL:
                defaults_detected['titiler_base_url'] = {
                    'current_value': titiler_url,
                    'default_value': AzureDefaults.TITILER_BASE_URL,
                    'env_var': 'TITILER_BASE_URL'
                }
                issues.append(f"TiTiler URL using development default")
            env_vars_set['TITILER_BASE_URL'] = bool(os.getenv('TITILER_BASE_URL'))

            # Check OGC/STAC URL
            ogc_stac_url = os.getenv('OGC_STAC_APP_URL', AzureDefaults.OGC_STAC_APP_URL)
            if ogc_stac_url == AzureDefaults.OGC_STAC_APP_URL:
                defaults_detected['ogc_stac_app_url'] = {
                    'current_value': ogc_stac_url,
                    'default_value': AzureDefaults.OGC_STAC_APP_URL,
                    'env_var': 'OGC_STAC_APP_URL'
                }
                issues.append(f"OGC/STAC URL using development default")
            env_vars_set['OGC_STAC_APP_URL'] = bool(os.getenv('OGC_STAC_APP_URL'))

            # Check ETL App URL
            etl_url = config.etl_app_base_url
            if etl_url == AzureDefaults.ETL_APP_URL:
                defaults_detected['etl_app_base_url'] = {
                    'current_value': etl_url,
                    'default_value': AzureDefaults.ETL_APP_URL,
                    'env_var': 'ETL_APP_URL'
                }
                issues.append(f"ETL App URL using development default")
            env_vars_set['ETL_APP_URL'] = bool(os.getenv('ETL_APP_URL'))

            # Check Managed Identity name (if using managed identity)
            # NOTE: Default must match database_config.py (default is 'true' for database auth)
            use_managed_identity = os.getenv('USE_MANAGED_IDENTITY', 'true').lower() == 'true'
            if use_managed_identity:
                mi_name = config.database.managed_identity_admin_name
                if mi_name == AzureDefaults.MANAGED_IDENTITY_NAME:
                    defaults_detected['managed_identity_admin_name'] = {
                        'current_value': mi_name,
                        'default_value': AzureDefaults.MANAGED_IDENTITY_NAME,
                        'env_var': 'DB_ADMIN_MANAGED_IDENTITY_NAME'
                    }
                    issues.append(f"Managed Identity Admin using development default: {mi_name}")
                env_vars_set['DB_ADMIN_MANAGED_IDENTITY_NAME'] = bool(os.getenv('DB_ADMIN_MANAGED_IDENTITY_NAME'))
            else:
                env_vars_set['USE_MANAGED_IDENTITY'] = False

            # Check database host (required for any deployment)
            db_host = config.database.host
            env_vars_set['POSTGIS_HOST'] = bool(os.getenv('POSTGIS_HOST'))
            if not os.getenv('POSTGIS_HOST'):
                issues.append("Database host (POSTGIS_HOST) not set via environment variable")

            # Determine overall status
            defaults_count = len(defaults_detected)
            total_azure_configs = 5  # storage, titiler, ogc_stac, etl, managed_identity

            if defaults_count == 0:
                config_status = "configured"
                deployment_ready = True
            elif defaults_count == total_azure_configs:
                config_status = "using_defaults"
                deployment_ready = False
            else:
                config_status = "partial"
                deployment_ready = False

            return {
                "config_status": config_status,
                "deployment_ready": deployment_ready,
                "azure_tenant_specific_configs": {
                    "total_checked": total_azure_configs,
                    "properly_configured": total_azure_configs - defaults_count,
                    "using_defaults": defaults_count
                },
                "issues": issues if issues else None,
                "defaults_detected": defaults_detected if defaults_detected else None,
                "environment_vars_set": env_vars_set,
                "recommendation": None if deployment_ready else (
                    "Set tenant-specific environment variables before deploying to production. "
                    "See config/defaults.py for the list of AzureDefaults values that should be overridden."
                )
            }

        return self.check_component_health(
            "deployment_config",
            check_deployment,
            description="Tenant-specific configuration validation for production deployments"
        )

    def _check_app_mode(self) -> Dict[str, Any]:
        """
        Check application mode configuration (07 DEC 2025 - Multi-Function App Architecture).

        Reports on the current app mode and which queues this instance listens to.
        Used for monitoring multi-Function App deployments.

        Returns:
            Dict with app mode health status including:
            - mode: Current app mode (standalone, platform_raster, etc.)
            - app_name: Unique identifier for this app instance
            - queues_listening: Which queues this app processes
            - routing: External routing configuration
            - role: Platform vs Worker role indicators
        """
        def check_app_mode():
            app_mode_config = get_app_mode_config()
            config = get_config()

            return {
                "mode": app_mode_config.mode.value,
                "app_name": app_mode_config.app_name,
                "queues_listening": {
                    "jobs": app_mode_config.listens_to_jobs_queue,
                    "raster_tasks": app_mode_config.listens_to_raster_tasks,
                    "vector_tasks": app_mode_config.listens_to_vector_tasks,
                },
                "queue_names": {
                    "jobs": config.queues.jobs_queue,
                    "raster_tasks": config.queues.raster_tasks_queue,
                    "vector_tasks": config.queues.vector_tasks_queue,
                },
                "routing": {
                    "routes_raster_externally": app_mode_config.routes_raster_externally,
                    "routes_vector_externally": app_mode_config.routes_vector_externally,
                    "raster_app_url": app_mode_config.raster_app_url,
                    "vector_app_url": app_mode_config.vector_app_url
                },
                "role": {
                    "is_platform": app_mode_config.is_platform_mode,
                    "is_worker": app_mode_config.is_worker_mode,
                    "has_http": app_mode_config.has_http_endpoints
                },
                "environment_var": {
                    "APP_MODE": os.getenv("APP_MODE", "not_set (defaults to standalone)"),
                    "APP_NAME": os.getenv("APP_NAME", "not_set (defaults to rmhazuregeoapi)")
                }
            }

        return self.check_component_health(
            "app_mode",
            check_app_mode,
            description="Multi-Function App deployment mode and queue routing configuration"
        )

    # _check_task_routing_coverage() REMOVED (12 DEC 2025)
    # Moved to services/__init__.py (startup validation) and scripts/validate_config.py (pre-deployment)
    # Configuration validation doesn't belong in runtime health checks

    def _check_schema_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive schema summary for remote database inspection (07 DEC 2025).

        Provides visibility into all schemas, tables, row counts, and STAC statistics
        without requiring direct database access. Critical for QA environment where
        database access requires PRIVX → Windows Server → DBeaver workflow.

        Returns:
            Dict with schema summary including:
            - schemas: Dict of schema names with tables, counts, sizes
            - pgstac: STAC collection/item counts
            - total_tables: Total table count across all schemas
        """
        def check_schemas():
            from infrastructure.postgresql import PostgreSQLRepository
            from config import get_config

            config = get_config()
            repo = PostgreSQLRepository()

            try:
                with repo._get_connection() as conn:
                    with conn.cursor() as cur:
                        schemas_data = {}

                        # Get all relevant schemas
                        target_schemas = ['app', 'geo', 'pgstac', 'h3']

                        for schema_name in target_schemas:
                            # Check if schema exists
                            cur.execute("""
                                SELECT EXISTS(
                                    SELECT 1 FROM pg_namespace WHERE nspname = %s
                                ) as schema_exists
                            """, (schema_name,))
                            schema_exists = cur.fetchone()['schema_exists']

                            if not schema_exists:
                                schemas_data[schema_name] = {
                                    "exists": False,
                                    "tables": [],
                                    "table_count": 0
                                }
                                continue

                            # Get tables in schema
                            cur.execute("""
                                SELECT table_name
                                FROM information_schema.tables
                                WHERE table_schema = %s
                                AND table_type = 'BASE TABLE'
                                ORDER BY table_name
                            """, (schema_name,))
                            tables = [row['table_name'] for row in cur.fetchall()]

                            # Get row counts for all tables in schema - single query using pg_stat (12 DEC 2025)
                            # This is instant regardless of table size, unlike COUNT(*)
                            cur.execute("""
                                SELECT relname, n_live_tup
                                FROM pg_stat_user_tables
                                WHERE schemaname = %s
                                ORDER BY relname
                            """, (schema_name,))
                            table_counts = {row['relname']: row['n_live_tup'] for row in cur.fetchall()}

                            schemas_data[schema_name] = {
                                "exists": True,
                                "tables": tables,
                                "table_count": len(tables),
                                "row_counts": table_counts,
                                "note": "Row counts are approximate (from pg_stat_user_tables)"
                            }

                        # Special handling for pgstac - get collection/item counts using pg_stat (12 DEC 2025)
                        if schemas_data.get('pgstac', {}).get('exists', False):
                            try:
                                cur.execute("""
                                    SELECT relname, n_live_tup
                                    FROM pg_stat_user_tables
                                    WHERE schemaname = 'pgstac' AND relname IN ('collections', 'items')
                                """)
                                stac_counts = {row['relname']: row['n_live_tup'] for row in cur.fetchall()}

                                schemas_data['pgstac']['stac_counts'] = {
                                    "collections": stac_counts.get('collections', 0),
                                    "items": stac_counts.get('items', 0)
                                }
                            except Exception as e:
                                schemas_data['pgstac']['stac_counts'] = {
                                    "error": str(e)[:100]
                                }

                        # Special handling for geo - count geometry columns
                        if schemas_data.get('geo', {}).get('exists', False):
                            try:
                                cur.execute("""
                                    SELECT COUNT(*) as count
                                    FROM geometry_columns
                                    WHERE f_table_schema = 'geo'
                                """)
                                geometry_count = cur.fetchone()['count']
                                schemas_data['geo']['geometry_columns'] = geometry_count
                            except Exception:
                                schemas_data['geo']['geometry_columns'] = "error"

                        # Calculate totals
                        total_tables = sum(
                            s.get('table_count', 0)
                            for s in schemas_data.values()
                            if isinstance(s, dict)
                        )

                        return {
                            "schemas": schemas_data,
                            "total_tables": total_tables,
                            "schemas_checked": target_schemas
                        }

            except Exception as e:
                import traceback
                return {
                    "error": str(e)[:200],
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()[:500]
                }

        return self.check_component_health(
            "schema_summary",
            check_schemas,
            description="Database schema inventory with table counts and STAC statistics"
        )

    def _check_titiler_health(self) -> Dict[str, Any]:
        """
        Check TiTiler tile server health (13 DEC 2025).

        TiTiler is an external Docker container app that serves raster tiles.
        Health logic:
        - Both /livez and /health respond → healthy (green)
        - Only /livez responds → warning (yellow) - app is alive but not fully ready
        - Neither responds → unhealthy (red)

        Returns:
            Dict with TiTiler health status including:
            - livez_status: Response from /livez endpoint
            - health_status: Response from /health endpoint
            - overall_status: healthy/warning/unhealthy based on combined results
        """
        def check_titiler():
            import requests
            from config import get_config

            config = get_config()
            titiler_url = config.titiler_base_url.rstrip('/')

            # Check if URL is the placeholder default (not configured)
            if titiler_url == "https://your-titiler-webapp-url":
                return {
                    "configured": False,
                    "error": "TITILER_BASE_URL not configured (using placeholder default)",
                    "impact": "Raster tile visualization unavailable",
                    "fix": "Set TITILER_BASE_URL environment variable to your TiTiler deployment URL"
                }

            livez_ok = False
            health_ok = False
            livez_response = None
            health_response = None
            livez_error = None
            health_error = None

            # Check /livez endpoint (basic liveness probe)
            try:
                resp = requests.get(f"{titiler_url}/livez", timeout=10)
                livez_ok = resp.status_code == 200
                livez_response = {
                    "status_code": resp.status_code,
                    "ok": livez_ok
                }
            except requests.exceptions.Timeout:
                livez_error = "Connection timed out (10s)"
            except requests.exceptions.ConnectionError as e:
                livez_error = f"Connection failed: {str(e)[:100]}"
            except Exception as e:
                livez_error = f"Error: {str(e)[:100]}"

            # Check /healthz endpoint (full readiness probe)
            try:
                resp = requests.get(f"{titiler_url}/healthz", timeout=10)
                health_ok = resp.status_code == 200
                health_response = {
                    "status_code": resp.status_code,
                    "ok": health_ok
                }
                # Try to get health response body if JSON
                try:
                    health_response["body"] = resp.json()
                except Exception:
                    pass
            except requests.exceptions.Timeout:
                health_error = "Connection timed out (10s)"
            except requests.exceptions.ConnectionError as e:
                health_error = f"Connection failed: {str(e)[:100]}"
            except Exception as e:
                health_error = f"Error: {str(e)[:100]}"

            # Determine overall status based on user requirements
            # Both respond → healthy (green)
            # Only livez responds → warning (yellow) - app is alive but degraded
            # Neither responds → unhealthy (red)
            if livez_ok and health_ok:
                overall_status = "healthy"
                status_reason = "Both /livez and /healthz endpoints responding"
            elif livez_ok and not health_ok:
                overall_status = "warning"
                status_reason = "App is alive (/livez OK) but not fully ready (/healthz failed)"
            else:
                overall_status = "unhealthy"
                status_reason = "TiTiler not responding - neither /livez nor /healthz accessible"

            result = {
                "configured": True,
                "base_url": titiler_url,
                "livez": livez_response if livez_response else {"error": livez_error},
                "health": health_response if health_response else {"error": health_error},
                "overall_status": overall_status,
                "status_reason": status_reason,
                "purpose": "Raster tile server for COG visualization via TiTiler-pgstac",
                # Use _status for wrapper to pick up warning/unhealthy states
                "_status": overall_status
            }

            # Add error field for unhealthy status to trigger proper reporting
            if overall_status == "unhealthy":
                result["error"] = status_reason

            return result

        return self.check_component_health(
            "titiler",
            check_titiler,
            description="TiTiler-pgstac raster tile server for COG visualization"
        )

    def _check_ogc_features_health(self) -> Dict[str, Any]:
        """
        Check OGC Features API health (13 DEC 2025).

        OGC Features can be self-hosted (same app) or external.
        Checks the /health endpoint of the configured OGC/STAC API URL.

        Returns:
            Dict with OGC Features health status including:
            - health_status: Response from /health endpoint
            - is_self: Whether pointing to this same app
        """
        def check_ogc_features():
            import requests
            from config import get_config

            config = get_config()
            ogc_url = config.ogc_features_base_url.rstrip('/')

            # Check if URL is the placeholder default (not configured)
            if ogc_url == "https://your-ogc-stac-app-url":
                return {
                    "configured": False,
                    "error": "OGC_STAC_APP_URL not configured (using placeholder default)",
                    "impact": "OGC Features API reference URL unavailable",
                    "fix": "Set OGC_STAC_APP_URL environment variable"
                }

            # Derive app base URL from ogc_features_base_url
            # ogc_features_base_url may include /api/features path, strip it for health check
            app_base_url = ogc_url
            if app_base_url.endswith('/api/features'):
                app_base_url = app_base_url[:-len('/api/features')]

            # Check if this is self (same app)
            etl_url = config.etl_app_base_url.rstrip('/')
            is_self = app_base_url == etl_url

            # If self-hosted, skip HTTP check to avoid recursive timeout
            # If this health endpoint is responding, OGC Features is also working
            if is_self:
                return {
                    "configured": True,
                    "features_url": ogc_url,
                    "app_base_url": app_base_url,
                    "is_self_hosted": True,
                    "overall_status": "healthy",
                    "status_reason": "Self-hosted - if this health check responds, OGC Features is available",
                    "purpose": "OGC API - Features for vector data queries",
                    "note": "Skipped HTTP health check to avoid recursive call (same app)"
                }

            health_ok = False
            health_response = None
            health_error = None

            # Check /api/health endpoint at app root (only for external OGC Features apps)
            health_endpoint = f"{app_base_url}/api/health"
            try:
                resp = requests.get(health_endpoint, timeout=15)
                health_ok = resp.status_code == 200
                health_response = {
                    "status_code": resp.status_code,
                    "ok": health_ok
                }
                # Try to get health response status if JSON
                try:
                    body = resp.json()
                    health_response["status"] = body.get("status", "unknown")
                except Exception:
                    pass
            except requests.exceptions.Timeout:
                health_error = "Connection timed out (15s)"
            except requests.exceptions.ConnectionError as e:
                health_error = f"Connection failed: {str(e)[:100]}"
            except Exception as e:
                health_error = f"Error: {str(e)[:100]}"

            # Determine status
            if health_ok:
                overall_status = "healthy"
                status_reason = "/api/health endpoint responding"
            else:
                overall_status = "unhealthy"
                status_reason = health_error or "OGC Features API not responding"

            result = {
                "configured": True,
                "features_url": ogc_url,
                "app_base_url": app_base_url,
                "is_self_hosted": False,
                "health_endpoint": health_endpoint,
                "health": health_response if health_response else {"error": health_error},
                "overall_status": overall_status,
                "status_reason": status_reason,
                "purpose": "OGC API - Features for vector data queries"
            }

            # Add error field for unhealthy status
            if overall_status == "unhealthy":
                result["error"] = status_reason

            return result

        return self.check_component_health(
            "ogc_features",
            check_ogc_features,
            description="OGC API - Features for PostGIS vector queries"
        )

    def _check_hardware_environment(self) -> Dict[str, Any]:
        """
        Check hardware/runtime environment (21 DEC 2025).

        Reports CPU, RAM, and platform info for capacity planning and debugging.
        Uses cached runtime environment from util_logger (computed once per process).

        Returns:
            Dict with hardware specs including:
            - cpu_count: Logical CPU count
            - total_ram_gb: Total system RAM
            - available_ram_mb: Current available RAM
            - ram_utilization_percent: Current RAM usage %
            - cpu_utilization_percent: Current CPU usage %
            - platform: OS and kernel version
            - azure_site_name: Function app name
            - azure_sku: App Service Plan SKU
        """
        def check_hardware():
            import psutil
            from util_logger import get_runtime_environment, get_memory_stats

            # Get cached runtime environment (computed once per process)
            runtime = get_runtime_environment()

            # Get current memory/CPU stats
            stats = get_memory_stats() or {}

            # Fallback to direct psutil if util_logger debug mode is off
            if not runtime:
                mem = psutil.virtual_memory()
                runtime = {
                    'cpu_count': psutil.cpu_count() or 0,
                    'total_ram_gb': round(mem.total / (1024**3), 1),
                    'platform': f"{os.sys.platform}",
                    'azure_site_name': os.environ.get('WEBSITE_SITE_NAME', 'local'),
                    'azure_sku': os.environ.get('WEBSITE_SKU', 'unknown'),
                    'azure_instance_id': os.environ.get('WEBSITE_INSTANCE_ID', '')[:16],
                }

            if not stats:
                mem = psutil.virtual_memory()
                stats = {
                    'system_available_mb': round(mem.available / (1024**2), 1),
                    'system_percent': round(mem.percent, 1),
                    'system_cpu_percent': round(psutil.cpu_percent(interval=None), 1),
                    'process_rss_mb': round(psutil.Process().memory_info().rss / (1024**2), 1),
                }

            return {
                # Static hardware specs (from cached runtime)
                "cpu_count": runtime.get('cpu_count'),
                "total_ram_gb": runtime.get('total_ram_gb'),
                "platform": runtime.get('platform'),
                "python_version": runtime.get('python_version'),
                # Azure environment
                "azure_site_name": runtime.get('azure_site_name'),
                "azure_sku": runtime.get('azure_sku'),
                "azure_instance_id": runtime.get('azure_instance_id'),
                # Current utilization
                "available_ram_mb": stats.get('system_available_mb'),
                "ram_utilization_percent": stats.get('system_percent'),
                "cpu_utilization_percent": stats.get('system_cpu_percent'),
                "process_rss_mb": stats.get('process_rss_mb'),
                # Capacity thresholds
                "capacity_notes": {
                    "safe_file_limit_mb": round((runtime.get('total_ram_gb', 7) * 1024) / 4, 0),
                    "warning_threshold_percent": 80,
                    "critical_threshold_percent": 90,
                }
            }

        return self.check_component_health(
            "hardware",
            check_hardware,
            description="Runtime hardware environment (CPU, RAM, platform)"
        )

    def _get_config_sources(self) -> Dict[str, Any]:
        """
        Get configuration values with their sources for debugging (07 DEC 2025).

        Shows whether each config value came from:
        - ENV: Environment variable
        - DEFAULT: AzureDefaults or other default class

        Only included when DEBUG_MODE=true to avoid leaking configuration details.
        Sensitive values (passwords, keys) are masked.

        Returns:
            Dict mapping config key to {value, source, env_var, is_default}
        """
        config = get_config()
        sources = {}

        # Storage configuration (zone-specific - 08 DEC 2025)
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

        # NOTE (08 DEC 2025): Reader identity removed - single admin identity for all operations

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
        sb_env = os.getenv('SERVICE_BUS_NAMESPACE')
        sources['service_bus_namespace'] = {
            "value": config.service_bus_namespace,
            "source": "ENV" if sb_env else "DEFAULT",
            "env_var": "SERVICE_BUS_NAMESPACE",
            "is_default": not bool(sb_env)
        }

        # Debug mode
        debug_env = os.getenv('DEBUG_MODE')
        sources['debug_mode'] = {
            "value": config.debug_mode,
            "source": "ENV" if debug_env else "DEFAULT",
            "env_var": "DEBUG_MODE",
            "is_default": not bool(debug_env)
        }

        # Summary statistics
        env_count = sum(1 for v in sources.values() if v['source'] == 'ENV')
        default_count = sum(1 for v in sources.values() if v['source'] == 'DEFAULT')

        return {
            "configs": sources,
            "summary": {
                "total_checked": len(sources),
                "from_environment": env_count,
                "using_defaults": default_count
            },
            "note": "Only shown when DEBUG_MODE=true"
        }


# Create singleton instance for use in function_app.py
health_check_trigger = HealthCheckTrigger()