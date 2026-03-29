# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT CHECK: RUNTIME LIBRARIES AND MOUNT
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Preflight check - handler imports, GDAL version, mount write canary
# PURPOSE: Validate Docker worker runtime: geospatial libraries importable,
#          GDAL version meets minimum, ETL mount is writable with free space
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: HandlerImportsCheck, GDALVersionCheck, MountWriteCheck
# DEPENDENCIES: importlib, os, osgeo.gdal, config
# ============================================================================
"""
Preflight checks: Docker worker runtime validation.

Three checks:
1. HandlerImportsCheck — all required geospatial libraries importable
2. GDALVersionCheck    — GDAL >= 3.x installed and parseable
3. MountWriteCheck     — ETL mount exists, is writable, has sufficient free space
"""

import importlib
import logging
import os

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

REQUIRED_IMPORTS = {
    "rasterio": "Raster I/O (COG creation, tiling)",
    "osgeo.gdal": "GDAL (raster processing, coordinate transforms)",
    "numpy": "Numerical operations (raster/vector processing)",
    "geopandas": "Vector ETL (shapefile, GeoJSON, GeoPackage)",
    "xarray": "Zarr/NetCDF operations",
    "zarr": "Zarr store creation and pyramids",
    "pyproj": "CRS transforms",
    "shapely": "Geometry operations",
}

_WORKER_MODES = {AppMode.WORKER_DOCKER}

_CANARY_FILENAME = "_preflight_canary.txt"
_CANARY_CONTENT = "preflight-canary-test"
_FREE_SPACE_WARN_BYTES = 1 * 1024 ** 3  # 1 GB


# ============================================================================
# Check 1: HandlerImportsCheck — required geospatial libraries importable
# ============================================================================

class HandlerImportsCheck(PreflightCheck):
    """Verify all required geospatial handler libraries can be imported."""

    name = "handler_imports"
    description = "Verify all required geospatial libraries are importable in the current runtime"
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        sub_checks: dict = {}
        missing: list[str] = []

        for module_name, purpose in REQUIRED_IMPORTS.items():
            try:
                importlib.import_module(module_name)
                sub_checks[module_name] = f"pass ({purpose})"
            except ImportError as exc:
                sub_checks[module_name] = f"fail: {exc}"
                missing.append(module_name)
                logger.warning("HandlerImportsCheck: cannot import %s: %s", module_name, exc)

        if not missing:
            return PreflightResult.passed(
                f"All {len(REQUIRED_IMPORTS)} required libraries importable",
                sub_checks=sub_checks,
            )

        return PreflightResult.failed(
            f"{len(missing)} required library/libraries not importable: {', '.join(missing)}",
            remediation=Remediation(
                action=(
                    f"Rebuild the Docker image to include missing packages: "
                    f"{', '.join(missing)}. "
                    "Verify the Dockerfile installs all geospatial dependencies "
                    "(rasterio, GDAL, geopandas, xarray, zarr, pyproj, shapely, numpy)."
                ),
                eservice_summary=(
                    f"DOCKER IMAGE: Missing Python packages in runtime: {', '.join(missing)}. "
                    "Rebuild and redeploy the Docker worker image with all geospatial "
                    "dependencies installed."
                ),
            ),
            sub_checks=sub_checks,
        )


# ============================================================================
# Check 2: GDALVersionCheck — GDAL >= 3.x
# ============================================================================

class GDALVersionCheck(PreflightCheck):
    """Verify GDAL is installed and meets the minimum version requirement."""

    name = "gdal_version"
    description = "Verify GDAL is installed and is version 3.x or higher"
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        try:
            from osgeo import gdal

            version_str = gdal.VersionInfo()
            # GDAL VersionInfo() returns e.g. "3080400" → major=3, minor=08, patch=04
            major = int(version_str[0])
            minor = int(version_str[1:3])
            patch = int(version_str[3:5])
            version_display = f"{major}.{minor}.{patch}"

            if major < 3:
                return PreflightResult.warned(
                    f"GDAL version {version_display} is below recommended minimum (3.x). "
                    "Some raster operations may not behave as expected.",
                    remediation=Remediation(
                        action=(
                            f"Upgrade GDAL to version 3.x or higher. "
                            f"Current version: {version_display}. "
                            "Update the Docker base image or conda environment."
                        ),
                        eservice_summary=(
                            f"DOCKER IMAGE: GDAL version {version_display} is below 3.x. "
                            "Rebuild the Docker image with GDAL >= 3.0."
                        ),
                    ),
                )

            return PreflightResult.passed(
                f"GDAL version {version_display} meets requirements (>= 3.x)"
            )

        except ImportError as exc:
            logger.warning("GDALVersionCheck: osgeo.gdal not importable: %s", exc)
            return PreflightResult.failed(
                f"GDAL not importable: {exc}",
                remediation=Remediation(
                    action=(
                        "Install GDAL in the Docker image. "
                        "Verify 'osgeo.gdal' (from the 'gdal' or 'GDAL' package) is present "
                        "in the Docker image and accessible to the Python runtime."
                    ),
                    eservice_summary=(
                        "DOCKER IMAGE: GDAL (osgeo.gdal) is not installed or not importable. "
                        "Rebuild the Docker worker image with GDAL support."
                    ),
                ),
            )


# ============================================================================
# Check 3: MountWriteCheck — ETL mount exists, writable, has free space
# ============================================================================

class MountWriteCheck(PreflightCheck):
    """
    Verify the ETL Azure File Share mount is present, writable, and has
    sufficient free space (>= 1 GB warning threshold).
    """

    name = "mount_write"
    description = (
        "Verify ETL mount path exists, accepts writes (canary file), "
        "and has >= 1 GB free space"
    )
    required_modes = _WORKER_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        if not hasattr(config, "docker") or not config.docker:
            return PreflightResult.failed(
                "Docker config not available — cannot determine mount path",
                remediation=Remediation(
                    action="Verify APP_MODE is set to worker_docker and docker config is loaded",
                ),
            )
        mount_path = config.docker.etl_mount_path

        # ------------------------------------------------------------------ #
        # Step 1: Directory exists
        # ------------------------------------------------------------------ #
        if not os.path.isdir(mount_path):
            return PreflightResult.failed(
                f"ETL mount path does not exist: {mount_path}",
                remediation=Remediation(
                    action=(
                        f"Mount the Azure File Share at '{mount_path}'. "
                        "Configure the 'azureFiles' volume mount in the App Service container "
                        "settings or Kubernetes pod spec. Verify STORAGE_MOUNT_PATH env var."
                    ),
                    azure_role="Storage File Data SMB Share Contributor",
                    eservice_summary=(
                        f"AZURE MOUNT: ETL mount not present at '{mount_path}'. "
                        "Configure Azure File Share mount on the Docker worker app service."
                    ),
                ),
            )

        # ------------------------------------------------------------------ #
        # Step 2: Canary write + delete
        # ------------------------------------------------------------------ #
        canary_path = os.path.join(mount_path, _CANARY_FILENAME)
        try:
            with open(canary_path, "w") as fh:
                fh.write(_CANARY_CONTENT)
            os.remove(canary_path)
            write_ok = True
        except OSError as exc:
            logger.warning("MountWriteCheck: write canary failed at %s: %s", canary_path, exc)
            return PreflightResult.failed(
                f"ETL mount at '{mount_path}' is not writable: {exc}",
                remediation=Remediation(
                    action=(
                        f"Verify the Azure File Share mounted at '{mount_path}' "
                        "has read-write permissions. Check the App Service mount configuration "
                        "and confirm the managed identity has 'Storage File Data SMB Share "
                        "Contributor' role on the File Share."
                    ),
                    azure_role="Storage File Data SMB Share Contributor",
                    eservice_summary=(
                        f"AZURE MOUNT: ETL mount at '{mount_path}' is read-only or inaccessible. "
                        "Assign 'Storage File Data SMB Share Contributor' role on the "
                        "Azure File Share and verify mount mode is read-write."
                    ),
                ),
            )

        # ------------------------------------------------------------------ #
        # Step 3: Free space check
        # ------------------------------------------------------------------ #
        try:
            stat = os.statvfs(mount_path)
            free_bytes = stat.f_bavail * stat.f_frsize
            free_gb = free_bytes / (1024 ** 3)

            if free_bytes < _FREE_SPACE_WARN_BYTES:
                return PreflightResult.warned(
                    f"ETL mount at '{mount_path}' is writable but has low free space: "
                    f"{free_gb:.2f} GB available (threshold: 1 GB)",
                    remediation=Remediation(
                        action=(
                            f"Increase Azure File Share quota or clear old ETL artifacts "
                            f"from '{mount_path}'. Current free space: {free_gb:.2f} GB."
                        ),
                        eservice_summary=(
                            f"AZURE MOUNT: Low disk space on ETL mount '{mount_path}' — "
                            f"{free_gb:.2f} GB free. Increase the Azure File Share quota "
                            "or clean up stale files."
                        ),
                    ),
                )

        except OSError as exc:
            # statvfs failure is non-fatal — mount is writable, space unknown
            logger.warning(
                "MountWriteCheck: statvfs failed at %s: %s (non-fatal)", mount_path, exc
            )
            return PreflightResult.passed(
                f"ETL mount at '{mount_path}' is writable (free space check unavailable: {exc})"
            )

        return PreflightResult.passed(
            f"ETL mount at '{mount_path}' is writable with {free_gb:.2f} GB free"
        )
