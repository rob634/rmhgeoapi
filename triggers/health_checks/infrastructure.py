# ============================================================================
# INFRASTRUCTURE HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Plugin - Infrastructure components
# PURPOSE: Storage containers, Service Bus queues, Network environment checks
# CREATED: 29 JAN 2026
# MIGRATED: 29 JAN 2026 (Phase 5)
# EXPORTS: InfrastructureHealthChecks
# DEPENDENCIES: base.HealthCheckPlugin, azure.storage.blob, config
# ============================================================================
"""
Infrastructure Health Checks Plugin.

Monitors infrastructure components:
- Storage containers (Bronze/Silver zones)
- Azure Service Bus queues
- Network/VNet/ASE environment

These checks verify Azure infrastructure connectivity.
"""

import os
from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class InfrastructureHealthChecks(HealthCheckPlugin):
    """
    Health checks for Azure infrastructure.

    Checks:
    - storage_containers: Bronze/Silver zone storage accounts and containers
    - service_bus: Azure Service Bus queues for job/task orchestration
    - network_environment: VNet/ASE configuration
    """

    name = "infrastructure"
    description = "Storage, Service Bus, and Network"
    priority = 30  # Run after application checks

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return infrastructure health checks."""
        return [
            ("storage_containers", self.check_storage_containers),
            ("service_bus", self.check_service_bus_queues),
            ("network_environment", self.check_network_environment),
        ]

    def is_enabled(self, config) -> bool:
        """Infrastructure checks are always enabled."""
        return True

    # =========================================================================
    # CHECK: Storage Containers
    # =========================================================================

    def check_storage_containers(self) -> Dict[str, Any]:
        """
        Check critical storage container existence for Bronze and Silver zones.

        Verifies that storage accounts are accessible and required containers exist:

        Bronze Zone (raw data input):
        - bronze-vectors: Raw vector uploads (Shapefiles, GeoJSON)
        - bronze-rasters: Raw raster uploads (GeoTIFF)

        Silver Zone (processed data):
        - silver-cogs: Cloud Optimized GeoTIFFs (COG output)
        - pickles: Vector ETL intermediate storage

        Returns:
            Dict with storage container health status
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
                    result["summary"]["total_containers_checked"] += len(containers)
                    result["summary"]["containers_missing"] += len(containers)

                result["zones"][zone] = zone_result

            # Determine overall health
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

    # =========================================================================
    # CHECK: Service Bus Queues
    # =========================================================================

    def check_service_bus_queues(self) -> Dict[str, Any]:
        """
        Check Azure Service Bus queue health using ServiceBusRepository.

        Queues checked (V0.8):
        - geospatial-jobs: Job orchestration + stage_complete signals
        - functionapp-tasks: Lightweight operations (DB, STAC, inventory)
        - container-tasks: Heavy operations (GDAL, geopandas) - Docker worker

        Returns:
            Dict with Service Bus queue health status
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
                        "SERVICE_BUS_FQDN env var has wrong value",
                        "VNet DNS configuration issue",
                        "Private DNS zone not linked to VNet",
                        "Network isolation blocking DNS"
                    ],
                    "fix": "Verify SERVICE_BUS_FQDN is correct (e.g., myns.servicebus.windows.net)"
                }

            # Socket/connection errors
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
                        "Firewall blocking Service Bus IPs",
                        "Corporate firewall blocking AMQP - try WebSocket transport (port 443)"
                    ],
                    "fix": "Check VNet service endpoints, or try AMQP-over-WebSockets if port 5671 is blocked"
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

            # Authentication errors
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
                    "fix": "Run schema rebuild: POST /api/dbadmin/maintenance?action=rebuild&confirm=yes"
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

            # Generic error
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

            # Network diagnostics - check DNS resolution
            namespace = config.service_bus_namespace
            dns_check = {"namespace": namespace}

            try:
                hostname = namespace if "." in namespace else f"{namespace}.servicebus.windows.net"
                dns_check["hostname_used"] = hostname

                # DNS resolution
                ip_addresses = socket.getaddrinfo(hostname, 5671, socket.AF_UNSPEC, socket.SOCK_STREAM)
                resolved_ips = list(set([addr[4][0] for addr in ip_addresses]))
                dns_check["resolved"] = True
                dns_check["ip_addresses"] = resolved_ips[:5]
                dns_check["is_private_ip"] = any(
                    ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.168.")
                    for ip in resolved_ips
                )
                if dns_check["is_private_ip"]:
                    dns_check["note"] = "Private IP detected - using Private Endpoint or VNet integration"

                # Port connectivity checks
                port_checks = {}
                for port, protocol in [(5671, "AMQP"), (443, "AMQP-over-WebSockets")]:
                    try:
                        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        test_socket.settimeout(5)
                        result = test_socket.connect_ex((hostname, port))
                        test_socket.close()
                        port_checks[port] = {
                            "protocol": protocol,
                            "reachable": result == 0,
                            "error_code": result if result != 0 else None
                        }
                    except Exception as port_error:
                        port_checks[port] = {
                            "protocol": protocol,
                            "reachable": False,
                            "error": str(port_error)[:100]
                        }

                dns_check["port_connectivity"] = port_checks

                # Transport recommendation
                amqp_ok = port_checks.get(5671, {}).get("reachable", False)
                websocket_ok = port_checks.get(443, {}).get("reachable", False)

                if amqp_ok:
                    dns_check["recommended_transport"] = "AMQP (port 5671)"
                elif websocket_ok:
                    dns_check["recommended_transport"] = "AMQP-over-WebSockets (port 443)"
                    dns_check["transport_warning"] = "Standard AMQP port 5671 blocked - consider configuring WebSocket transport"
                else:
                    dns_check["transport_error"] = "Neither AMQP (5671) nor WebSocket (443) ports are reachable"

            except socket.gaierror as e:
                dns_check["resolved"] = False
                dns_check["dns_error"] = str(e)
                dns_check["diagnosis"] = "DNS resolution failed - check VNet DNS or namespace name"

            queue_status["_network_diagnostics"] = dns_check

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
                {"name": config.queues.functionapp_tasks_queue, "purpose": "Lightweight tasks (DB, STAC, inventory)"},
                {"name": config.queues.container_tasks_queue, "purpose": "Heavy tasks (GDAL, geopandas) - Docker worker"}
            ]

            queues_accessible = 0
            queues_missing = 0
            queues_connection_error = 0
            error_categories = set()

            for queue_config in queues_to_check:
                queue_name = queue_config["name"]
                try:
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

            # Summary
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

            queue_status["_repository_info"] = {
                "singleton_id": id(service_bus_repo),
                "type": "ServiceBusRepository",
                "namespace": namespace,
                "connection_method": "managed_identity" if not os.getenv("SERVICE_BUS_CONNECTION_STRING") else "connection_string"
            }

            if not all_healthy:
                queue_status["_status"] = "unhealthy"

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
            return "Run rebuild to create missing queues"
        return "Check Application Insights for detailed error logs"

    # =========================================================================
    # CHECK: Network Environment
    # =========================================================================

    def check_network_environment(self) -> Dict[str, Any]:
        """
        Check network/VNet/ASE environment configuration.

        Captures Azure platform environment variables related to
        networking, VNet integration, and App Service Environment settings.

        Returns:
            Dict with network configuration including VNet, DNS, ASE settings
        """
        def check_network():
            # Known environment variable categories
            vnet_vars = {
                'private_ip': 'WEBSITE_PRIVATE_IP',
                'vnet_route_all': 'WEBSITE_VNET_ROUTE_ALL',
                'content_over_vnet': 'WEBSITE_CONTENTOVERVNET',
                'swap_vnet': 'WEBSITE_SWAP_WARMUP_VNET',
            }

            dns_vars = {
                'dns_server': 'WEBSITE_DNS_SERVER',
                'dns_alt_server': 'WEBSITE_DNS_ALT_SERVER',
            }

            ase_vars = {
                'ase_name': 'WEBSITE_ASE_NAME',
                'home_stampname': 'WEBSITE_HOME_STAMPNAME',
                'stamp_deployment_id': 'WEBSITE_STAMP_DEPLOYMENT_ID',
                'worker_id': 'WEBSITE_WORKER_ID',
                'roleinstance_id': 'WEBSITE_ROLEINSTANCE_ID',
            }

            platform_vars = {
                'site_name': 'WEBSITE_SITE_NAME',
                'hostname': 'WEBSITE_HOSTNAME',
                'instance_id': 'WEBSITE_INSTANCE_ID',
                'sku': 'WEBSITE_SKU',
                'compute_mode': 'WEBSITE_COMPUTE_MODE',
                'slot_name': 'WEBSITE_SLOT_NAME',
                'owner_name': 'WEBSITE_OWNER_NAME',
                'resource_group': 'WEBSITE_RESOURCE_GROUP',
                'region_name': 'REGION_NAME',
                'platform_version': 'WEBSITE_PLATFORM_VERSION',
                'node_default_version': 'WEBSITE_NODE_DEFAULT_VERSION',
            }

            storage_vars = {
                'contentazurefileconnectionstring': 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING',
                'contentshare': 'WEBSITE_CONTENTSHARE',
                'run_from_package': 'WEBSITE_RUN_FROM_PACKAGE',
                'use_zip_deploy': 'WEBSITE_USE_ZIP_DEPLOY',
            }

            functions_vars = {
                'functions_extension_version': 'FUNCTIONS_EXTENSION_VERSION',
                'functions_worker_runtime': 'FUNCTIONS_WORKER_RUNTIME',
                'azure_functions_environment': 'AZURE_FUNCTIONS_ENVIRONMENT',
                'scm_run_from_package': 'SCM_RUN_FROM_PACKAGE',
            }

            auth_vars = {
                'auth_enabled': 'WEBSITE_AUTH_ENABLED',
                'auth_encryption_key': 'WEBSITE_AUTH_ENCRYPTION_KEY',
                'https_only': 'WEBSITE_HTTPSONLY',
            }

            def get_vars(var_map: dict) -> dict:
                result = {}
                for key, env_name in var_map.items():
                    value = os.environ.get(env_name)
                    if value is not None:
                        # Mask sensitive values
                        if 'connection' in key.lower() or 'key' in key.lower():
                            result[key] = f"[SET - {len(value)} chars]"
                        elif len(value) > 200:
                            result[key] = value[:200] + f"... [{len(value)} chars total]"
                        else:
                            result[key] = value
                return result

            # Collect all known variables
            network_config = {
                'vnet': get_vars(vnet_vars),
                'dns': get_vars(dns_vars),
                'ase': get_vars(ase_vars),
                'platform': get_vars(platform_vars),
                'storage': get_vars(storage_vars),
                'functions': get_vars(functions_vars),
                'auth': get_vars(auth_vars),
            }

            # Remove empty categories
            network_config = {k: v for k, v in network_config.items() if v}

            # Dynamic discovery
            known_vars = set()
            for var_map in [vnet_vars, dns_vars, ase_vars, platform_vars,
                           storage_vars, functions_vars, auth_vars]:
                known_vars.update(var_map.values())

            discovered = {}
            for env_name, env_value in os.environ.items():
                if env_name.startswith(('WEBSITE_', 'AZURE_', 'APPSETTING_')):
                    if env_name not in known_vars:
                        if any(s in env_name.lower() for s in ['key', 'secret', 'password', 'connection', 'token']):
                            discovered[env_name] = f"[SET - {len(env_value)} chars]"
                        elif len(env_value) > 200:
                            discovered[env_name] = env_value[:200] + f"... [{len(env_value)} chars total]"
                        else:
                            discovered[env_name] = env_value

            if discovered:
                network_config['discovered'] = discovered

            # Environment summary
            env_type = "standard"
            if network_config.get('ase', {}).get('ase_name'):
                env_type = "ase"
            elif network_config.get('vnet', {}).get('private_ip'):
                env_type = "vnet_integrated"

            network_config['_summary'] = {
                'environment_type': env_type,
                'has_vnet_integration': bool(network_config.get('vnet')),
                'has_ase': bool(network_config.get('ase')),
                'has_custom_dns': bool(network_config.get('dns')),
                'total_vars_captured': sum(len(v) for v in network_config.values() if isinstance(v, dict)),
                'discovered_count': len(discovered),
            }

            return network_config

        return self.check_component_health(
            "network_environment",
            check_network,
            description="Azure network/VNet/ASE environment configuration"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['InfrastructureHealthChecks']
