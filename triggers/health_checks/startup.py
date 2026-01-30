# ============================================================================
# STARTUP HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Plugin - Startup and deployment components
# PURPOSE: Deployment config, Startup validation, Imports, Runtime health checks
# CREATED: 29 JAN 2026
# MIGRATED: 29 JAN 2026 (Phase 3)
# EXPORTS: StartupHealthChecks
# DEPENDENCIES: base.HealthCheckPlugin, config, startup_state
# ============================================================================
"""
Startup Health Checks Plugin.

Monitors startup and deployment components:
- Deployment configuration (tenant-specific settings)
- Startup validation (env vars, DNS, queues)
- Import validation (critical modules loaded)
- Runtime environment (hardware, memory, process)

These checks verify the application started correctly.
"""

import os
import sys
from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class StartupHealthChecks(HealthCheckPlugin):
    """
    Health checks for startup and deployment.

    Checks:
    - deployment_config: Tenant-specific configuration
    - startup_validation: Environment and connectivity
    - imports: Critical module availability
    - runtime: Hardware and process info
    """

    name = "startup"
    description = "Deployment, Startup, Imports, and Runtime"
    priority = 10  # Run first

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return startup health checks."""
        return [
            ("deployment_config", self.check_deployment_config),
            ("startup_validation", self.check_startup_validation),
            ("imports", self.check_import_validation),
            ("runtime", self.check_runtime_environment),
        ]

    def is_enabled(self, config) -> bool:
        """Startup checks are always enabled."""
        return True

    # =========================================================================
    # CHECK: Deployment Config
    # =========================================================================

    def check_deployment_config(self) -> Dict[str, Any]:
        """
        Check if deployment configuration is properly set for this Azure tenant.

        Validates that tenant-specific values (storage accounts, URLs, managed identities)
        have been overridden from their development defaults.

        Returns:
            Dict with deployment configuration validation status
        """
        def check_deployment():
            from config import get_config, AzureDefaults, StorageDefaults

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
            env_vars_set['POSTGIS_HOST'] = bool(os.getenv('POSTGIS_HOST'))
            if not os.getenv('POSTGIS_HOST'):
                issues.append("Database host (POSTGIS_HOST) not set via environment variable")

            # Determine overall status
            defaults_count = len(defaults_detected)
            total_azure_configs = 5

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

    # =========================================================================
    # CHECK: Startup Validation
    # =========================================================================

    def check_startup_validation(self) -> Dict[str, Any]:
        """
        Check startup validation state from STARTUP_STATE (03 JAN 2026).

        Shows the results of Phase 2 soft validation that runs during startup.
        Checks env_vars, imports, Service Bus DNS, and queues.

        Returns:
            Dict with startup validation status and any failures
        """
        def check_startup():
            from startup_state import STARTUP_STATE

            # Check if validation has completed
            if not STARTUP_STATE.validation_complete:
                return {
                    "validation_complete": False,
                    "all_passed": False,
                    "message": "Startup validation still in progress",
                    "startup_time": STARTUP_STATE.startup_time
                }

            # Get summary from STARTUP_STATE
            summary = STARTUP_STATE.get_summary()

            # Build detailed check results
            checks = {}
            for check_name in ["env_vars", "imports", "service_bus_dns", "service_bus_queues"]:
                check_result = getattr(STARTUP_STATE, check_name, None)
                if check_result:
                    checks[check_name] = check_result.to_dict()

            result = {
                "validation_complete": STARTUP_STATE.validation_complete,
                "all_passed": STARTUP_STATE.all_passed,
                "startup_time": STARTUP_STATE.startup_time,
                "summary": summary,
                "checks": checks
            }

            # Add critical error if present
            if STARTUP_STATE.critical_error:
                result["critical_error"] = STARTUP_STATE.critical_error

            # Add service bus trigger status
            result["triggers_registered"] = STARTUP_STATE.all_passed

            return result

        # Use check_component_health wrapper for consistent formatting
        component_result = self.check_component_health(
            "startup_validation",
            check_startup,
            description="Startup validation state (env_vars, imports, Service Bus DNS/queues)"
        )

        # Override status based on STARTUP_STATE.all_passed
        try:
            from startup_state import STARTUP_STATE
            if STARTUP_STATE.validation_complete and not STARTUP_STATE.all_passed:
                component_result["status"] = "unhealthy"
                failed = STARTUP_STATE.get_failed_checks()
                component_result["errors"] = [
                    f"{f.name}: {f.error_message or f.error_type}" for f in failed
                ]
        except Exception:
            pass

        return component_result

    # =========================================================================
    # CHECK: Import Validation
    # =========================================================================

    def check_import_validation(self) -> Dict[str, Any]:
        """
        Lightweight import validation check (12 DEC 2025 - Performance Fix).

        Verifies that critical modules are loaded in sys.modules rather than
        re-importing them. Since this endpoint can only run if function_app.py
        loaded successfully, re-validating imports is redundant.

        Returns:
            Dict with lightweight import validation status
        """
        def check_imports():
            # Check critical modules are in sys.modules (already loaded at startup)
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
                "validation_summary": "All critical modules loaded" if all_loaded else "Missing modules detected",
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

    # =========================================================================
    # CHECK: Runtime Environment
    # =========================================================================

    def check_runtime_environment(self) -> Dict[str, Any]:
        """
        Check runtime environment including hardware and instance info (07 JAN 2026).

        Provides comprehensive view of:
        - Hardware specs (CPU, RAM, platform)
        - Instance identification (for log correlation)
        - Process details (uptime, threads, memory)
        - Cold start detection
        - Worker configuration

        Returns:
            Dict with hardware, instance, process, memory sections
        """
        def check_runtime():
            import psutil
            import threading
            from datetime import datetime, timezone

            # Single psutil Process object for all process-related queries
            process = psutil.Process()
            mem = psutil.virtual_memory()
            mem_info = process.memory_info()

            # Process timing
            process_create_time = datetime.fromtimestamp(
                process.create_time(), tz=timezone.utc
            )
            now = datetime.now(timezone.utc)
            process_uptime_seconds = (now - process_create_time).total_seconds()

            def format_uptime(seconds: float) -> str:
                """Format uptime in human-readable form."""
                if seconds < 60:
                    return f"{int(seconds)}s (cold)"
                elif seconds < 3600:
                    return f"{int(seconds // 60)}m {int(seconds % 60)}s"
                elif seconds < 86400:
                    hours = int(seconds // 3600)
                    mins = int((seconds % 3600) // 60)
                    return f"{hours}h {mins}m"
                else:
                    days = int(seconds // 86400)
                    hours = int((seconds % 86400) // 3600)
                    return f"{days}d {hours}h"

            # Hardware specs
            total_ram_gb = round(mem.total / (1024**3), 1)
            hardware = {
                "cpu_count": psutil.cpu_count() or 0,
                "total_ram_gb": total_ram_gb,
                "platform": os.sys.platform,
                "python_version": sys.version.split()[0],
                "azure_sku": os.environ.get('WEBSITE_SKU', 'unknown'),
                "azure_site_name": os.environ.get('WEBSITE_SITE_NAME', 'local'),
            }

            # Instance identification (for correlating with Application Insights logs)
            instance_id_full = os.environ.get('WEBSITE_INSTANCE_ID', 'local')
            instance = {
                "instance_id": instance_id_full,
                "instance_id_short": instance_id_full[:16] + '...' if len(instance_id_full) > 16 else instance_id_full,
            }
            # Add optional ASE-specific fields if present
            role_instance = os.environ.get('WEBSITE_ROLE_INSTANCE_ID')
            if role_instance:
                instance["role_instance_id"] = role_instance
            worker_id = os.environ.get('WEBSITE_WORKER_ID')
            if worker_id:
                instance["worker_id"] = worker_id

            # Process details
            process_info = {
                "pid": process.pid,
                "uptime_seconds": round(process_uptime_seconds, 1),
                "uptime_human": format_uptime(process_uptime_seconds),
                "start_time": process_create_time.isoformat(),
                "thread_count": threading.active_count(),
                "thread_names": [t.name for t in threading.enumerate()][:10],
            }

            # Memory stats (system and process combined)
            memory = {
                "system_total_gb": total_ram_gb,
                "system_available_mb": round(mem.available / (1024**2), 1),
                "system_percent": round(mem.percent, 1),
                "process_rss_mb": round(mem_info.rss / (1024**2), 1),
                "process_vms_mb": round(mem_info.vms / (1024**2), 1),
                "process_percent": round(process.memory_percent(), 2),
                "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            }

            # Cold start detection
            cold_start = {
                "likely_cold_start": process_uptime_seconds < 60,
                "likely_warm": process_uptime_seconds > 300,
            }

            # Worker configuration
            worker_config = {
                "process_count": os.environ.get('FUNCTIONS_WORKER_PROCESS_COUNT', '1'),
                "runtime": os.environ.get('FUNCTIONS_WORKER_RUNTIME', 'python'),
            }
            max_concurrent = os.environ.get('FUNCTIONS_MAX_CONCURRENT_REQUESTS')
            if max_concurrent:
                worker_config["max_concurrent_requests"] = max_concurrent

            # Scale controller logging status
            scale_logging = os.environ.get('SCALE_CONTROLLER_LOGGING_ENABLED')
            scale_controller = {
                "logging_enabled": scale_logging or 'disabled',
            }
            if not scale_logging:
                scale_controller["tip"] = "Set SCALE_CONTROLLER_LOGGING_ENABLED=AppInsights:Verbose"

            # Capacity thresholds for reference
            capacity = {
                "safe_file_limit_mb": round((total_ram_gb * 1024) / 4, 0),
                "warning_threshold_percent": 80,
                "critical_threshold_percent": 90,
            }

            return {
                "hardware": hardware,
                "instance": instance,
                "process": process_info,
                "memory": memory,
                "cold_start": cold_start,
                "worker_config": worker_config,
                "scale_controller": scale_controller,
                "capacity_thresholds": capacity,
            }

        return self.check_component_health(
            "runtime",
            check_runtime,
            description="Runtime environment (hardware, instance, process, memory)"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['StartupHealthChecks']
