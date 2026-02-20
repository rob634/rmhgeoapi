# ============================================================================
# APPLICATION HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Plugin - Application components
# PURPOSE: App Mode, Endpoints, Jobs Registry health checks
# CREATED: 29 JAN 2026
# MIGRATED: 29 JAN 2026 (Phase 2)
# EXPORTS: ApplicationHealthChecks
# DEPENDENCIES: base.HealthCheckPlugin, config
# ============================================================================
"""
Application Health Checks Plugin.

Monitors application-level components:
- App Mode configuration (multi-Function App architecture)
- Endpoint registration (validates routes match APP_MODE)
- Jobs Registry (available job types)

These checks verify application configuration and routing.
"""

import os
import sys
from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class ApplicationHealthChecks(HealthCheckPlugin):
    """
    Health checks for application components.

    Checks:
    - app_mode: Multi-Function App deployment mode
    - endpoint_registration: Route availability vs APP_MODE
    - jobs: Job registry and available job types
    """

    name = "application"
    description = "App Mode, Endpoints, and Jobs Registry"
    priority = 20  # Run early (after startup)

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return application health checks."""
        return [
            ("app_mode", self.check_app_mode),
            ("endpoint_registration", self.check_endpoint_registration),
            ("jobs", self.check_jobs_registry),
        ]

    def is_enabled(self, config) -> bool:
        """Application checks are always enabled."""
        return True

    # =========================================================================
    # CHECK: App Mode
    # =========================================================================

    def check_app_mode(self) -> Dict[str, Any]:
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
        def check_app_mode_inner():
            from config import get_config, get_app_mode_config

            app_mode_config = get_app_mode_config()
            config = get_config()

            return {
                "mode": app_mode_config.mode.value,
                "app_name": app_mode_config.app_name,
                "docker_worker_enabled": app_mode_config.docker_worker_enabled,
                "queues_listening": {
                    "jobs": app_mode_config.listens_to_jobs_queue,
                    "container_tasks": app_mode_config.listens_to_container_tasks,
                },
                "queue_names": {
                    "jobs": config.queues.jobs_queue,
                    "container_tasks": config.queues.container_tasks_queue,
                },
                "routing": {
                    "routes_tasks_externally": app_mode_config.routes_tasks_externally,
                },
                "role": {
                    "is_platform": app_mode_config.is_platform_mode,
                    "is_worker": app_mode_config.is_worker_mode,
                    "has_http": app_mode_config.has_http_endpoints
                },
                "endpoints_enabled": {
                    "platform": app_mode_config.has_platform_endpoints,
                    "admin": app_mode_config.has_admin_endpoints,
                    "jobs": app_mode_config.has_jobs_endpoints,
                },
                "environment_var": {
                    "APP_MODE": os.getenv("APP_MODE", "not_set (defaults to standalone)"),
                    "APP_NAME": os.getenv("APP_NAME", "not_set (defaults to rmhazuregeoapi)"),
                    "DOCKER_WORKER_ENABLED": os.getenv("DOCKER_WORKER_ENABLED", "not_set (defaults to false)")
                }
            }

        return self.check_component_health(
            "app_mode",
            check_app_mode_inner,
            description="Multi-Function App deployment mode and queue routing configuration"
        )

    # =========================================================================
    # CHECK: Endpoint Registration
    # =========================================================================

    def check_endpoint_registration(self) -> Dict[str, Any]:
        """
        Check endpoint registration consistency (27 JAN 2026 - BUG-006 detection).

        Validates that endpoints expected for the current APP_MODE are actually
        registered and accessible. Detects configuration issues like:
        - Platform endpoints expected but not registered
        - Import failures preventing blueprint registration
        - Mismatched APP_MODE vs actual endpoint availability

        This check helps diagnose 404 errors when endpoints should be available
        but are disabled due to APP_MODE misconfiguration.

        Returns:
            Dict with endpoint registration health including warnings
        """
        def check_endpoints():
            from config import get_app_mode_config

            app_mode_config = get_app_mode_config()
            warnings = []
            issues = []

            # Define endpoint expectations per mode
            endpoint_checks = {
                "platform_endpoints": {
                    "expected": app_mode_config.has_platform_endpoints,
                    "description": "/api/platform/* (approve, revoke, approvals, submit)",
                    "modes_enabled": ["standalone", "platform", "orchestrator"],
                    # NOTE: trigger_approvals is lazy-loaded inside handlers (by design)
                    # Only check the blueprint module which IS loaded at startup
                    "test_modules": [
                        "triggers.platform.platform_bp",
                    ],
                },
                "admin_endpoints": {
                    "expected": app_mode_config.has_admin_endpoints,
                    "description": "/api/dbadmin/*, /api/admin/*",
                    "modes_enabled": ["standalone", "orchestrator"],
                    "test_modules": [
                        "triggers.admin.admin_db",
                        "triggers.admin.admin_system",
                    ],
                },
                "jobs_endpoints": {
                    "expected": app_mode_config.has_jobs_endpoints,
                    "description": "/api/jobs/* (submit, status)",
                    "modes_enabled": ["standalone", "orchestrator"],
                    # NOTE: Jobs use individual trigger modules, not a blueprint
                    "test_modules": [
                        "triggers.submit_job",
                        "triggers.get_job_status",
                    ],
                },
            }

            results = {}
            for endpoint_type, config in endpoint_checks.items():
                result = {
                    "expected": config["expected"],
                    "modes_enabled": config["modes_enabled"],
                    "description": config["description"],
                }

                if config["expected"]:
                    # Verify modules are loaded (would not be loaded if blueprint not registered)
                    module_results = []
                    all_loaded = True
                    for module_path in config["test_modules"]:
                        is_loaded = module_path in sys.modules
                        module_results.append({
                            "module": module_path,
                            "loaded": is_loaded
                        })
                        if not is_loaded:
                            all_loaded = False

                    result["modules_loaded"] = module_results
                    result["all_modules_loaded"] = all_loaded

                    if not all_loaded:
                        # This is a serious issue - endpoints expected but not registered
                        warning_msg = (
                            f"{endpoint_type}: Expected endpoints not registered. "
                            f"Check for import errors in Application Insights. "
                            f"APP_MODE={app_mode_config.mode.value}"
                        )
                        warnings.append(warning_msg)
                        result["warning"] = warning_msg
                else:
                    result["note"] = f"Disabled for APP_MODE={app_mode_config.mode.value}"

                results[endpoint_type] = result

            # Build summary
            summary = {
                "app_mode": app_mode_config.mode.value,
                "endpoints": results,
            }

            if warnings:
                summary["warnings"] = warnings
            if issues:
                summary["issues"] = issues

            # Provide actionable guidance for common issues
            if app_mode_config.mode.value == "worker_docker":
                summary["guidance"] = (
                    f"APP_MODE={app_mode_config.mode.value} disables platform endpoints. "
                    "If you need /api/platform/approve or /api/platform/approvals, "
                    "set APP_MODE=standalone or APP_MODE=orchestrator"
                )

            return summary

        return self.check_component_health(
            "endpoint_registration",
            check_endpoints,
            description="Validates expected endpoints are registered for current APP_MODE"
        )

    # =========================================================================
    # CHECK: Jobs Registry
    # =========================================================================

    def check_jobs_registry(self) -> Dict[str, Any]:
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


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ApplicationHealthChecks']
