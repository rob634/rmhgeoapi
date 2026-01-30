# ============================================================================
# DOCKER HEALTH - Health Aggregator
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Aggregation - Combines subsystem health into unified response
# PURPOSE: Aggregate multiple subsystem health checks into final health response
# CREATED: 29 JAN 2026
# EXPORTS: HealthAggregator
# DEPENDENCIES: base.WorkerSubsystem
# ============================================================================
"""
Health Aggregator for Docker Worker.

Combines health from all subsystems into a unified health response that:
- Maintains compatibility with health.js UI (components format)
- Provides subsystem-level grouping for operational visibility
- Computes overall status from worst component status
- Includes legacy fields for backward compatibility
"""

import os
from datetime import datetime, timezone
from typing import Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import WorkerSubsystem


class HealthAggregator:
    """
    Aggregates health from multiple subsystems into unified response.

    The aggregator:
    1. Iterates over subsystems in priority order
    2. Collects health from each enabled subsystem
    3. Flattens components for health.js compatibility
    4. Computes overall status
    5. Builds response with legacy fields for backward compatibility
    """

    def __init__(self, subsystems: List["WorkerSubsystem"]):
        """
        Initialize with list of subsystems.

        Args:
            subsystems: List of WorkerSubsystem instances (sorted by priority)
        """
        self.subsystems = subsystems

    def get_health(self) -> Dict[str, Any]:
        """
        Aggregate health from all subsystems.

        Returns:
            Dict with:
            - status: Overall health status
            - timestamp: ISO timestamp
            - environment: Version and deployment info
            - subsystems: Detailed subsystem health (new format)
            - components: Flattened components (health.js compatible)
            - errors: List of error messages
            - Legacy fields for backward compatibility
        """
        from config import get_config, __version__

        config = get_config()
        timestamp = datetime.now(timezone.utc)

        # Collect health from all subsystems
        subsystem_health = {}
        all_components = {}
        all_errors = []
        all_metrics = {}

        for subsystem in self.subsystems:
            if not subsystem.is_enabled():
                subsystem_health[subsystem.name] = {
                    "status": "disabled",
                    "description": subsystem.description,
                }
                continue

            try:
                health = subsystem.get_health()
                subsystem_health[subsystem.name] = {
                    "status": health.get("status", "unknown"),
                    "description": subsystem.description,
                    "components": health.get("components", {}),
                    "metrics": health.get("metrics"),
                }

                # Flatten components for health.js compatibility
                for comp_name, comp_data in health.get("components", {}).items():
                    all_components[comp_name] = comp_data

                # Collect errors
                if health.get("errors"):
                    all_errors.extend(health["errors"])

                # Collect metrics
                if health.get("metrics"):
                    all_metrics[subsystem.name] = health["metrics"]

            except Exception as e:
                subsystem_health[subsystem.name] = {
                    "status": "unhealthy",
                    "description": subsystem.description,
                    "error": str(e),
                }
                all_errors.append(f"{subsystem.name}: {str(e)}")

        # Compute overall status from all components
        overall_status = self._compute_overall_status(all_components)

        # Add compatibility placeholders (components expected by health.js)
        all_components = self._add_compatibility_placeholders(all_components, config)

        # Environment info (for health.js renderEnvironmentInfo)
        environment = {
            "version": __version__,
            "environment": os.environ.get("ENVIRONMENT", "dev"),
            "debug_mode": os.environ.get("DEBUG_MODE", "false").lower() == "true",
            "hostname": os.environ.get("WEBSITE_HOSTNAME", os.environ.get("HOSTNAME", "docker-worker")),
        }

        # Build response
        response = {
            "status": overall_status,
            "timestamp": timestamp.isoformat(),
            "errors": all_errors if all_errors else [],
            "environment": environment,

            # New subsystem format (operational visibility)
            "subsystems": subsystem_health,

            # Flattened components (health.js compatible)
            "components": all_components,

            # Version (duplicate for backward compatibility)
            "version": __version__,
        }

        # Add legacy fields for backward compatibility
        response.update(self._build_legacy_fields(subsystem_health, all_metrics))

        return response, overall_status

    def _compute_overall_status(self, components: Dict[str, Dict]) -> str:
        """
        Compute overall status from component statuses.

        Priority (worst wins):
        1. unhealthy
        2. degraded/warning
        3. healthy

        Args:
            components: Dict of component health

        Returns:
            Overall status string
        """
        statuses = [c.get("status", "unknown") for c in components.values()]

        # Filter out disabled components for overall status
        active_statuses = [s for s in statuses if s != "disabled"]

        if not active_statuses:
            return "healthy"

        if any(s == "unhealthy" for s in active_statuses):
            return "unhealthy"
        if any(s in ("degraded", "warning") for s in active_statuses):
            return "degraded"
        return "healthy"

    def _add_compatibility_placeholders(
        self,
        components: Dict[str, Dict],
        config
    ) -> Dict[str, Dict]:
        """
        Add placeholder components expected by health.js UI.

        These are marked as disabled/N/A for Docker Worker context.

        Args:
            components: Existing components dict
            config: App config

        Returns:
            Components dict with placeholders added
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        # Jobs component (expected by comp-orchestrator)
        if "jobs" not in components:
            components["jobs"] = {
                "status": "disabled",
                "description": "Job orchestration (Function App only)",
                "checked_at": timestamp,
                "_source": "function_app",
                "details": {
                    "note": "Docker Worker processes tasks, not jobs",
                    "context": "docker_worker",
                }
            }

        # Pgstac component (expected by comp-output-tables)
        if "pgstac" not in components:
            db_connected = components.get("database", {}).get("status") == "healthy"
            components["pgstac"] = {
                "status": "healthy" if db_connected else "unhealthy",
                "description": "STAC catalog (via database)",
                "checked_at": timestamp,
                "_source": "function_app",
                "details": {
                    "note": "Accessed via shared PostgreSQL database",
                    "database_connected": db_connected,
                }
            }

        # TiTiler component (expected by comp-titiler)
        if "titiler" not in components:
            titiler_url = getattr(config, 'titiler_base_url', '') or ''
            components["titiler"] = {
                "status": "disabled",
                "description": "TiTiler-pgstac (external service)",
                "checked_at": timestamp,
                "_source": "function_app",
                "details": {
                    "url": titiler_url,
                    "note": "External raster tile service",
                }
            }

        # OGC Features component (expected by comp-ogc-features)
        if "ogc_features" not in components:
            components["ogc_features"] = {
                "status": "disabled",
                "description": "OGC Features API (Function App only)",
                "checked_at": timestamp,
                "_source": "function_app",
                "details": {
                    "note": "Served by Function App, not Docker Worker",
                }
            }

        return components

    def _build_legacy_fields(
        self,
        subsystem_health: Dict[str, Dict],
        metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build legacy fields for backward compatibility.

        These fields match the original docker_service.py health response
        structure for tools/scripts that depend on them.

        Args:
            subsystem_health: Subsystem health dict
            metrics: Collected metrics

        Returns:
            Dict with legacy fields
        """
        legacy = {}

        # Extract lifecycle status
        classic = subsystem_health.get("classic_worker", {})
        classic_components = classic.get("components", {})
        lifecycle_comp = classic_components.get("lifecycle", {})
        legacy["lifecycle"] = lifecycle_comp.get("details", {})

        # Extract token status
        auth_comp = classic_components.get("auth_tokens", {})
        auth_details = auth_comp.get("details", {})
        legacy["tokens"] = {
            "postgres": auth_details.get("postgres", {}),
            "storage": auth_details.get("storage", {}),
        }

        # Extract connectivity
        shared = subsystem_health.get("shared_infrastructure", {})
        shared_components = shared.get("components", {})
        db_comp = shared_components.get("database", {})
        storage_comp = shared_components.get("storage_containers", {})
        legacy["connectivity"] = {
            "database": {
                "connected": db_comp.get("status") == "healthy",
                **db_comp.get("details", {}),
            },
            "storage": {
                "connected": storage_comp.get("status") == "healthy",
                **storage_comp.get("details", {}),
            },
        }

        # Extract background workers
        queue_comp = classic_components.get("queue_worker", {})
        legacy["background_workers"] = {
            "token_refresh": auth_details.get("token_refresh_worker", {}),
            "queue_worker": queue_comp.get("details", {}),
        }

        # Extract connection pool
        pool_comp = classic_components.get("connection_pool", {})
        legacy["connection_pool"] = pool_comp.get("details", {})

        # Extract runtime
        runtime_sub = subsystem_health.get("runtime", {})
        runtime_components = runtime_sub.get("components", {})
        runtime_comp = runtime_components.get("runtime", {})
        runtime_details = runtime_comp.get("details", {})
        legacy["runtime"] = {
            "hardware": runtime_details.get("hardware", {}),
            "instance": runtime_details.get("instance", {}),
            "process": runtime_details.get("process", {}),
            "memory": runtime_details.get("memory", {}),
            "capacity": runtime_details.get("capacity", {}),
        }

        return legacy


__all__ = ['HealthAggregator']
