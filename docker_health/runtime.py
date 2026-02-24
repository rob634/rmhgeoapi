# ============================================================================
# DOCKER HEALTH - Runtime Environment Subsystem
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Subsystem - Hardware, GDAL, Imports, ETL Mount
# PURPOSE: Health checks for container runtime environment
# CREATED: 29 JAN 2026
# EXPORTS: RuntimeSubsystem
# DEPENDENCIES: base.WorkerSubsystem, psutil, osgeo
# ============================================================================
"""
Runtime Environment Health Subsystem.

Monitors the Docker container's runtime environment:
- runtime: Hardware metrics (CPU, memory, platform)
- etl_mount: Azure Files mount for large file processing
- gdal: GDAL geospatial library configuration
- imports: Python dependencies loaded
- deployment_config: Container deployment settings

These checks verify the container environment is properly configured.
"""

import os
import sys
import platform
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from .base import WorkerSubsystem


class RuntimeSubsystem(WorkerSubsystem):
    """
    Health checks for container runtime environment.

    Components:
    - runtime: Hardware, instance, process, memory metrics
    - etl_mount: Azure Files mount status (for large rasters)
    - gdal: GDAL library configuration
    - imports: Python dependencies
    - deployment_config: Container deployment settings
    """

    name = "runtime"
    description = "Container runtime environment (hardware, GDAL, mounts)"
    priority = 20  # Run after shared infrastructure

    def __init__(self, etl_mount_status: Optional[dict] = None):
        """
        Initialize with optional ETL mount status.

        Args:
            etl_mount_status: Dict from _etl_mount_status global
        """
        self.etl_mount_status = etl_mount_status or {}

    def is_enabled(self) -> bool:
        """Runtime checks are always enabled."""
        return True

    def get_health(self) -> Dict[str, Any]:
        """Return health status for runtime environment."""
        components = {}
        metrics = {}

        # Check runtime (hardware)
        runtime_result = self._check_runtime()
        components["runtime"] = runtime_result
        # Extract metrics for easy access
        if "details" in runtime_result:
            metrics["hardware"] = runtime_result["details"].get("hardware", {})
            metrics["memory"] = runtime_result["details"].get("memory", {})

        # Check ETL mount
        components["etl_mount"] = self._check_etl_mount()

        # Check GDAL
        components["gdal"] = self._check_gdal()

        # Check imports - COMMENTED OUT (29 JAN 2026)
        # Lazy-loaded modules (rasterio) cause false warnings. The Docker Worker
        # can only respond if imports succeeded, making this check redundant.
        # components["imports"] = self._check_imports()

        # Check deployment config
        components["deployment_config"] = self._check_deployment_config()

        return {
            "status": self.compute_status(components),
            "components": components,
            "metrics": metrics,
        }

    def _check_runtime(self) -> Dict[str, Any]:
        """Check container runtime environment."""
        import psutil

        try:
            memory = psutil.virtual_memory()
            process = psutil.Process()
            mem_info = process.memory_info()
            total_ram_gb = round(memory.total / (1024**3), 1)

            # Hardware specs
            hardware = {
                "cpu_count": psutil.cpu_count(),
                "total_ram_gb": total_ram_gb,
                "platform": platform.system(),
                "python_version": platform.python_version(),
                "azure_site_name": os.environ.get("WEBSITE_SITE_NAME", "docker-worker"),
                "azure_sku": os.environ.get("WEBSITE_SKU", "Container"),
            }

            # Instance info for log correlation
            instance = {
                "container_id": os.environ.get("HOSTNAME", "unknown")[:12],
                "website_instance_id": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:8],
                "instance_id_short": os.environ.get("WEBSITE_INSTANCE_ID", "local")[:8],
                "app_name": os.environ.get("APP_NAME", "docker-worker"),
            }

            # Process info
            try:
                create_time = datetime.fromtimestamp(process.create_time(), tz=timezone.utc)
                uptime_seconds = (datetime.now(timezone.utc) - create_time).total_seconds()
            except Exception:
                uptime_seconds = 0

            process_info = {
                "pid": process.pid,
                "uptime_seconds": round(uptime_seconds),
                "uptime_human": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
                "threads": process.num_threads(),
            }

            # Memory stats
            memory_stats = {
                "system_total_gb": total_ram_gb,
                "system_available_mb": round(memory.available / (1024**2), 1),
                "system_percent": round(memory.percent, 1),
                "process_rss_mb": round(mem_info.rss / (1024**2), 1),
                "process_vms_mb": round(mem_info.vms / (1024**2), 1),
                "process_percent": round(process.memory_percent(), 2),
                "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            }

            # Capacity thresholds
            capacity = {
                "safe_file_limit_mb": round((total_ram_gb * 1024) / 4, 0),
                "warning_threshold_percent": 80,
                "critical_threshold_percent": 90,
            }

            return self.build_component(
                status="healthy",
                description="Docker container runtime environment",
                details={
                    "hardware": hardware,
                    "instance": instance,
                    "process": process_info,
                    "memory": memory_stats,
                    "capacity": capacity,
                }
            )

        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="Docker container runtime environment",
                details={"error": str(e)}
            )

    def _check_etl_mount(self) -> Dict[str, Any]:
        """Check Azure Files ETL mount status."""
        mount_enabled = self.etl_mount_status.get("mount_enabled", False)
        mount_validated = self.etl_mount_status.get("validated", False)
        mount_degraded = self.etl_mount_status.get("degraded", False)

        if mount_enabled and mount_validated:
            mount_status = "healthy"
        elif mount_degraded:
            mount_status = "warning"
        elif not mount_enabled:
            mount_status = "disabled"
        else:
            mount_status = "unhealthy"

        return self.build_component(
            status=mount_status,
            description="Azure Files mount for large raster processing",
            details={
                "mount_enabled": mount_enabled,
                "mount_path": self.etl_mount_status.get("mount_path", "N/A"),
                "validated": mount_validated,
                "disk_space": self.etl_mount_status.get("disk_space"),
                "message": self.etl_mount_status.get("message"),
                "error": self.etl_mount_status.get("error"),
            }
        )

    def _check_gdal(self) -> Dict[str, Any]:
        """Check GDAL geospatial library configuration."""
        try:
            from osgeo import gdal

            gdal_config = {
                "version": gdal.__version__,
                "cpl_tmpdir": os.environ.get("CPL_TMPDIR", "default"),
                "gdal_data": os.environ.get("GDAL_DATA", "default"),
                "proj_lib": os.environ.get("PROJ_LIB", "default"),
            }

            return self.build_component(
                status="healthy",
                description="GDAL geospatial library configuration",
                details=gdal_config
            )

        except Exception as e:
            return self.build_component(
                status="unhealthy",
                description="GDAL geospatial library configuration",
                details={"error": str(e)}
            )

    def _check_imports(self) -> Dict[str, Any]:
        """Check that critical Python dependencies are loaded."""
        critical_modules = {
            'psycopg': 'PostgreSQL adapter',
            'azure.storage.blob': 'Azure Blob Storage client',
            'azure.servicebus': 'Azure Service Bus client',
            'azure.identity': 'Azure authentication',
            'fastapi': 'FastAPI framework',
            'rasterio': 'Raster I/O library',
            'osgeo': 'GDAL/OGR bindings',
        }

        module_status = {}
        for module, description in critical_modules.items():
            module_status[module] = {
                'loaded': module in sys.modules,
                'description': description
            }

        all_loaded = all(status['loaded'] for status in module_status.values())

        return self.build_component(
            status="healthy" if all_loaded else "warning",
            description="Python dependencies loaded",
            details={
                "python_version": platform.python_version(),
                "modules_checked": len(critical_modules),
                "modules_loaded": sum(1 for s in module_status.values() if s['loaded']),
                "critical_dependencies": module_status,
            }
        )

    def _check_deployment_config(self) -> Dict[str, Any]:
        """Check Docker Worker deployment configuration."""
        return self.build_component(
            status="healthy",
            description="Docker Worker deployment",
            details={
                "hostname": os.environ.get("WEBSITE_HOSTNAME", "docker-worker"),
                "container_id": os.environ.get("HOSTNAME", "unknown")[:12],
                "sku": os.environ.get("WEBSITE_SKU", "Container"),
                "environment": os.environ.get("ENVIRONMENT", "dev"),
                "app_name": os.environ.get("APP_NAME", "docker-worker"),
            }
        )


__all__ = ['RuntimeSubsystem']
