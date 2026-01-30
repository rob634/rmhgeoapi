# ============================================================================
# EXTERNAL SERVICES HEALTH CHECKS
# ============================================================================
# EPOCH: 4 - ACTIVE
# STATUS: Health Check Plugin - External service components
# PURPOSE: GeoTiler, OGC Features, Docker Worker health checks
# CREATED: 29 JAN 2026
# MIGRATED: 29 JAN 2026 (Phase 4)
# EXPORTS: ExternalServicesHealthChecks
# DEPENDENCIES: base.HealthCheckPlugin, requests, config
# ============================================================================
"""
External Services Health Checks Plugin.

Monitors external HTTP services:
- GeoTiler (TiTiler + TiPG) for raster tiles and vector features
- OGC Features API availability
- Docker Worker for heavy processing

These checks make HTTP calls and benefit from parallel execution.
"""

from typing import Dict, Any, List, Tuple, Callable

from .base import HealthCheckPlugin


class ExternalServicesHealthChecks(HealthCheckPlugin):
    """
    Health checks for external HTTP services.

    Checks (run in parallel):
    - geotiler: TiTiler COG tiles + TiPG OGC Features
    - ogc_features: Vector feature API
    - docker_worker: Heavy processing container

    These are I/O-bound checks that run in parallel via get_parallel_checks().
    """

    name = "external_services"
    description = "GeoTiler, OGC Features, Docker Worker HTTP services"
    priority = 50  # Run last (parallel, I/O-bound)

    def get_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return sequential checks (none for this plugin)."""
        # External services use parallel execution
        return []

    def get_parallel_checks(self) -> List[Tuple[str, Callable[[], Dict[str, Any]]]]:
        """Return checks that run in parallel."""
        from config import get_app_mode_config

        checks = [
            ("geotiler", self.check_geotiler_health),
            ("ogc_features", self.check_ogc_features_health),
        ]

        # Add Docker worker check if enabled
        app_mode_config = get_app_mode_config()
        if app_mode_config.docker_worker_enabled and app_mode_config.docker_worker_url:
            checks.append(("docker_worker", self.check_docker_worker_health))

        return checks

    def is_enabled(self, config) -> bool:
        """External service checks are always enabled."""
        return True

    # =========================================================================
    # CHECK: GeoTiler (TiTiler + TiPG + STAC)
    # =========================================================================

    def check_geotiler_health(self) -> Dict[str, Any]:
        """
        Check GeoTiler Docker app health (13 JAN 2026 - E8 TiPG Integration).

        GeoTiler is a Docker container that hosts multiple services:
        - COG: Cloud-Optimized GeoTIFF tile serving (TiTiler core)
        - XArray: Zarr/NetCDF multidimensional array tiles
        - pgSTAC: STAC mosaic searches and dynamic tiling
        - TiPG: OGC Features API + Vector Tiles (MVT)
        - STAC API: STAC catalog browsing and search

        Returns:
            Dict with GeoTiler health status including individual service statuses.
        """
        def check_geotiler():
            import requests
            from config import get_config

            config = get_config()
            geotiler_url = config.titiler_base_url.rstrip('/')

            # Check if URL is the placeholder default (not configured)
            if geotiler_url == "https://your-titiler-webapp-url":
                return {
                    "configured": False,
                    "error": "TITILER_BASE_URL not configured (using placeholder default)",
                    "impact": "Tile serving and OGC Features unavailable",
                    "fix": "Set TITILER_BASE_URL environment variable to your GeoTiler deployment URL"
                }

            livez_ok = False
            health_ok = False
            livez_response = None
            health_body = None
            livez_error = None
            health_error = None

            # Check /livez endpoint (basic liveness probe)
            try:
                resp = requests.get(f"{geotiler_url}/livez", timeout=10)
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

            # Check /health endpoint (full readiness probe with service details)
            try:
                resp = requests.get(f"{geotiler_url}/health", timeout=10)
                health_ok = resp.status_code == 200
                try:
                    health_body = resp.json()
                except Exception:
                    health_body = None
            except requests.exceptions.Timeout:
                health_error = "Connection timed out (10s)"
            except requests.exceptions.ConnectionError as e:
                health_error = f"Connection failed: {str(e)[:100]}"
            except Exception as e:
                health_error = f"Error: {str(e)[:100]}"

            # Parse individual service statuses from health response
            services = {}
            dependencies = {}
            service_summary = {"healthy": 0, "degraded": 0, "disabled": 0, "unavailable": 0}

            if health_body and isinstance(health_body, dict):
                # Extract services section
                if "services" in health_body:
                    for svc_name, svc_data in health_body["services"].items():
                        if isinstance(svc_data, dict):
                            svc_status = svc_data.get("status", "unknown")
                            svc_available = svc_data.get("available", False)

                            services[svc_name] = {
                                "status": svc_status,
                                "available": svc_available,
                            }

                            # Include description if provided
                            if "description" in svc_data:
                                services[svc_name]["description"] = svc_data["description"]

                            # Include endpoints if provided
                            if "endpoints" in svc_data:
                                services[svc_name]["endpoints"] = svc_data["endpoints"]

                            # Include details (e.g., tipg collections count)
                            if "details" in svc_data:
                                services[svc_name]["details"] = svc_data["details"]

                            # Include disabled reason if applicable
                            if "disabled_reason" in svc_data:
                                services[svc_name]["disabled_reason"] = svc_data["disabled_reason"]

                            # Count by status
                            if svc_status == "healthy":
                                service_summary["healthy"] += 1
                            elif svc_status == "disabled":
                                service_summary["disabled"] += 1
                            elif svc_status == "unavailable":
                                service_summary["unavailable"] += 1
                            else:
                                service_summary["degraded"] += 1

                # Extract dependencies section
                if "dependencies" in health_body:
                    for dep_name, dep_data in health_body["dependencies"].items():
                        if isinstance(dep_data, dict):
                            dependencies[dep_name] = {
                                "status": dep_data.get("status", "unknown")
                            }
                            # Include ping time for database
                            if "ping_time_ms" in dep_data:
                                dependencies[dep_name]["ping_time_ms"] = dep_data["ping_time_ms"]
                            # Include expiry for oauth tokens
                            if "expires_in_seconds" in dep_data:
                                dependencies[dep_name]["expires_in_seconds"] = dep_data["expires_in_seconds"]
                            # Include required_by mapping
                            if "required_by" in dep_data:
                                dependencies[dep_name]["required_by"] = dep_data["required_by"]

            # Determine overall status
            if livez_ok and health_ok:
                geotiler_status = health_body.get("status", "healthy") if health_body else "healthy"
                if geotiler_status == "healthy" and service_summary["unavailable"] == 0:
                    overall_status = "healthy"
                    status_reason = f"All {service_summary['healthy']} services healthy"
                else:
                    overall_status = "warning"
                    status_reason = f"{service_summary['healthy']} healthy, {service_summary['unavailable']} unavailable, {service_summary['disabled']} disabled"
            elif livez_ok and not health_ok:
                overall_status = "warning"
                status_reason = "App is alive (/livez OK) but health check failed"
            else:
                overall_status = "unhealthy"
                status_reason = "GeoTiler not responding - neither /livez nor /health accessible"

            result = {
                "configured": True,
                "base_url": geotiler_url,
                "livez": livez_response if livez_response else {"error": livez_error},
                "overall_status": overall_status,
                "status_reason": status_reason,
                "purpose": "Multi-service tile server: COG, XArray, pgSTAC mosaic, TiPG OGC Features, STAC API",
                "_status": overall_status
            }

            # Add version if available
            if health_body and "version" in health_body:
                result["version"] = health_body["version"]

            # Add services breakdown
            if services:
                result["services"] = services
                result["service_summary"] = service_summary

            # Add dependencies breakdown
            if dependencies:
                result["dependencies"] = dependencies

            # Add issues from health response
            if health_body and health_body.get("issues"):
                result["issues"] = health_body["issues"]

            # Add health error if check failed
            if health_error:
                result["health_error"] = health_error

            # Add error field for unhealthy status
            if overall_status == "unhealthy":
                result["error"] = status_reason

            return result

        return self.check_component_health(
            "geotiler",
            check_geotiler,
            description="GeoTiler Docker app: COG, XArray, pgSTAC, TiPG (OGC Features + Vector Tiles), STAC API"
        )

    # =========================================================================
    # CHECK: OGC Features (TiPG)
    # =========================================================================

    def check_ogc_features_health(self) -> Dict[str, Any]:
        """
        Check TiPG OGC Features API health (28 JAN 2026).

        TiPG runs in the same Docker container as TiTiler at the /vector prefix.
        Checks the /vector/collections endpoint to verify TiPG is responding.

        Returns:
            Dict with TiPG health status including collections count.
        """
        def check_tipg():
            import requests
            from config import get_config

            config = get_config()
            tipg_url = config.tipg_base_url.rstrip('/')

            # Check if TITILER_BASE_URL is configured (TiPG derives from it)
            if "your-titiler-webapp-url" in tipg_url:
                return {
                    "configured": False,
                    "error": "TITILER_BASE_URL not configured (using placeholder default)",
                    "impact": "TiPG OGC Features API unavailable for vector queries",
                    "fix": "Set TITILER_BASE_URL environment variable"
                }

            collections_endpoint = f"{tipg_url}/collections"
            health_ok = False
            collections_count = None
            health_error = None

            try:
                resp = requests.get(collections_endpoint, timeout=15)
                health_ok = resp.status_code == 200
                if health_ok:
                    try:
                        body = resp.json()
                        collections = body.get("collections", [])
                        collections_count = len(collections)
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
                status_reason = f"TiPG responding with {collections_count} collections"
            else:
                overall_status = "unhealthy"
                status_reason = health_error or "TiPG not responding"

            result = {
                "configured": True,
                "tipg_url": tipg_url,
                "collections_endpoint": collections_endpoint,
                "collections_count": collections_count,
                "overall_status": overall_status,
                "status_reason": status_reason,
                "purpose": "TiPG OGC API - Features for PostGIS vector queries"
            }

            # Add error field for unhealthy status
            if overall_status == "unhealthy":
                result["error"] = status_reason

            return result

        return self.check_component_health(
            "ogc_features",
            check_tipg,
            description="TiPG OGC API - Features for PostGIS vector queries (at TiTiler /vector)"
        )

    # =========================================================================
    # CHECK: Docker Worker
    # =========================================================================

    def check_docker_worker_health(self) -> Dict[str, Any]:
        """
        Check Docker worker health (11 JAN 2026 - F7.13).

        The Docker worker handles long-running tasks that exceed Function App
        timeout limits (e.g., large raster processing).

        Returns:
            Dict with Docker worker health status.
        """
        def check_docker_worker():
            import requests
            from config import get_app_mode_config

            app_mode_config = get_app_mode_config()
            worker_url = app_mode_config.docker_worker_url.rstrip('/')

            health_ok = False
            health_response = None
            health_error = None

            # Check /health endpoint
            health_endpoint = f"{worker_url}/health"
            try:
                resp = requests.get(health_endpoint, timeout=15)
                health_ok = resp.status_code == 200
                health_response = {
                    "status_code": resp.status_code,
                    "ok": health_ok
                }
                # Try to get health response body if JSON
                try:
                    body = resp.json()
                    health_response["body"] = body
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
                status_reason = "/health endpoint responding"
            else:
                overall_status = "unhealthy"
                status_reason = health_error or "Docker worker not responding"

            result = {
                "url": worker_url,
                "health_endpoint": health_endpoint,
                "health": health_response if health_response else {"error": health_error},
                "overall_status": overall_status,
                "status_reason": status_reason,
                "purpose": "Long-running task processing (large rasters, Docker-based COG creation)"
            }

            # Add error field for unhealthy status
            if overall_status == "unhealthy":
                result["error"] = status_reason

            return result

        return self.check_component_health(
            "docker_worker",
            check_docker_worker,
            description="Docker worker for long-running geospatial tasks"
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['ExternalServicesHealthChecks']
