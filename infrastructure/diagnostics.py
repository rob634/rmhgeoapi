# ============================================================================
# SYSTEM DIAGNOSTICS MODULE
# ============================================================================
# STATUS: Infrastructure - Lightweight diagnostics for QA environment debugging
# PURPOSE: Quick connectivity checks, DNS timing, pool stats for opaque environments
# LAST_REVIEWED: 09 JAN 2026
# EXPORTS: SystemDiagnostics, get_diagnostics
# DEPENDENCIES: None (uses only stdlib + psycopg for pool stats)
# ============================================================================
"""
System Diagnostics Module.

Provides lightweight diagnostic checks for debugging corporate Azure environments
with VNet/ASE complexity. Designed to answer "what's slow?" quickly.

Features:
    - Dependency connectivity with latency measurement
    - DNS resolution timing
    - Connection pool statistics
    - Instance/cold start information
    - Network environment summary

Usage:
    from infrastructure.diagnostics import get_diagnostics

    # Full diagnostics
    result = get_diagnostics()

    # Specific checks
    result = get_diagnostics(
        check_dependencies=True,
        check_dns=True,
        check_pools=True,
        check_instance=True,
        check_network=True
    )

Design:
    - All checks have timeouts to prevent hanging
    - Each check is independent and isolated
    - Errors are captured, not raised
    - Results include timing for every operation
"""

import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# Startup time captured at module load (for cold start detection)
_MODULE_LOAD_TIME = datetime.now(timezone.utc)
_PROCESS_START_TIME = time.time()


# ============================================================================
# CONFIGURATION
# ============================================================================

# Timeouts for various checks (seconds)
DNS_TIMEOUT = 5.0
CONNECTIVITY_TIMEOUT = 10.0
POOL_CHECK_TIMEOUT = 5.0

# Default ports for services
SERVICE_PORTS = {
    "postgresql": 5432,
    "service_bus": 5671,  # AMQP
    "service_bus_https": 443,
    "blob_storage": 443,
}


# ============================================================================
# DIAGNOSTIC RESULTS
# ============================================================================

@dataclass
class DependencyCheck:
    """Result of a dependency connectivity check."""
    name: str
    host: str
    port: int
    status: str  # "ok", "timeout", "error", "dns_failed"
    latency_ms: float
    error: Optional[str] = None
    dns_latency_ms: Optional[float] = None
    ip_address: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
        }
        if self.dns_latency_ms is not None:
            result["dns_latency_ms"] = round(self.dns_latency_ms, 2)
        if self.ip_address:
            result["ip_address"] = self.ip_address
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class DNSCheck:
    """Result of a DNS resolution check."""
    hostname: str
    resolved: bool
    latency_ms: float
    ip_addresses: List[str] = field(default_factory=list)
    is_private_ip: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "hostname": self.hostname,
            "resolved": self.resolved,
            "latency_ms": round(self.latency_ms, 2),
        }
        if self.ip_addresses:
            result["ip_addresses"] = self.ip_addresses
            result["is_private_ip"] = self.is_private_ip
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class DiagnosticsResult:
    """Complete diagnostics result."""
    timestamp: str
    duration_ms: float
    dependencies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dns_resolution: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    connection_pools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    instance: Dict[str, Any] = field(default_factory=dict)
    network: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "timestamp": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.dependencies:
            result["dependencies"] = self.dependencies
        if self.dns_resolution:
            result["dns_resolution"] = self.dns_resolution
        if self.connection_pools:
            result["connection_pools"] = self.connection_pools
        if self.instance:
            result["instance"] = self.instance
        if self.network:
            result["network"] = self.network
        return result


# ============================================================================
# DIAGNOSTIC CHECKS
# ============================================================================

def _is_private_ip(ip: str) -> bool:
    """Check if IP is in a private range (RFC 1918 + link-local)."""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        first = int(parts[0])
        second = int(parts[1])
        # 10.x.x.x
        if first == 10:
            return True
        # 172.16.x.x - 172.31.x.x
        if first == 172 and 16 <= second <= 31:
            return True
        # 192.168.x.x
        if first == 192 and second == 168:
            return True
        # 169.254.x.x (link-local)
        if first == 169 and second == 254:
            return True
        return False
    except (ValueError, IndexError):
        return False


def check_dns_resolution(hostname: str, timeout: float = DNS_TIMEOUT) -> DNSCheck:
    """
    Check DNS resolution with timing.

    Args:
        hostname: Hostname to resolve
        timeout: Timeout in seconds

    Returns:
        DNSCheck with results
    """
    start = time.perf_counter()
    try:
        socket.setdefaulttimeout(timeout)
        # Get all addresses
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_INET)
        latency_ms = (time.perf_counter() - start) * 1000

        ip_addresses = list(set(info[4][0] for info in addr_info))
        is_private = any(_is_private_ip(ip) for ip in ip_addresses)

        return DNSCheck(
            hostname=hostname,
            resolved=True,
            latency_ms=latency_ms,
            ip_addresses=ip_addresses[:5],  # Limit to 5
            is_private_ip=is_private,
        )
    except socket.gaierror as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return DNSCheck(
            hostname=hostname,
            resolved=False,
            latency_ms=latency_ms,
            error=f"DNS resolution failed: {e}",
        )
    except socket.timeout:
        latency_ms = (time.perf_counter() - start) * 1000
        return DNSCheck(
            hostname=hostname,
            resolved=False,
            latency_ms=latency_ms,
            error=f"DNS timeout after {timeout}s",
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        return DNSCheck(
            hostname=hostname,
            resolved=False,
            latency_ms=latency_ms,
            error=str(e),
        )


def check_connectivity(
    name: str,
    host: str,
    port: int,
    timeout: float = CONNECTIVITY_TIMEOUT
) -> DependencyCheck:
    """
    Check TCP connectivity to a service with timing.

    Args:
        name: Service name for reporting
        host: Hostname or IP
        port: Port number
        timeout: Timeout in seconds

    Returns:
        DependencyCheck with results
    """
    total_start = time.perf_counter()

    # First resolve DNS (with timing)
    dns_start = time.perf_counter()
    try:
        socket.setdefaulttimeout(timeout)
        ip_address = socket.gethostbyname(host)
        dns_latency_ms = (time.perf_counter() - dns_start) * 1000
    except socket.gaierror as e:
        total_latency = (time.perf_counter() - total_start) * 1000
        return DependencyCheck(
            name=name,
            host=host,
            port=port,
            status="dns_failed",
            latency_ms=total_latency,
            error=f"DNS resolution failed: {e}",
        )
    except socket.timeout:
        total_latency = (time.perf_counter() - total_start) * 1000
        return DependencyCheck(
            name=name,
            host=host,
            port=port,
            status="dns_failed",
            latency_ms=total_latency,
            error=f"DNS timeout after {timeout}s",
        )

    # Now check TCP connectivity
    connect_start = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout - (time.perf_counter() - total_start))  # Remaining time
        sock.connect((ip_address, port))
        sock.close()
        total_latency = (time.perf_counter() - total_start) * 1000

        return DependencyCheck(
            name=name,
            host=host,
            port=port,
            status="ok",
            latency_ms=total_latency,
            dns_latency_ms=dns_latency_ms,
            ip_address=ip_address,
        )
    except socket.timeout:
        total_latency = (time.perf_counter() - total_start) * 1000
        return DependencyCheck(
            name=name,
            host=host,
            port=port,
            status="timeout",
            latency_ms=total_latency,
            dns_latency_ms=dns_latency_ms,
            ip_address=ip_address,
            error=f"Connection timeout (DNS ok, connect failed)",
        )
    except ConnectionRefusedError:
        total_latency = (time.perf_counter() - total_start) * 1000
        return DependencyCheck(
            name=name,
            host=host,
            port=port,
            status="refused",
            latency_ms=total_latency,
            dns_latency_ms=dns_latency_ms,
            ip_address=ip_address,
            error="Connection refused (port closed or blocked)",
        )
    except Exception as e:
        total_latency = (time.perf_counter() - total_start) * 1000
        return DependencyCheck(
            name=name,
            host=host,
            port=port,
            status="error",
            latency_ms=total_latency,
            dns_latency_ms=dns_latency_ms,
            ip_address=ip_address,
            error=str(e),
        )


def get_instance_info() -> Dict[str, Any]:
    """
    Get instance and cold start information.

    Returns:
        Dict with instance details
    """
    now = datetime.now(timezone.utc)
    uptime_seconds = time.time() - _PROCESS_START_TIME

    instance_id = os.environ.get('WEBSITE_INSTANCE_ID', 'local-dev')
    role_instance = os.environ.get('WEBSITE_ROLEINSTANCE_ID')

    result = {
        "instance_id": instance_id[:16] + '...' if len(instance_id) > 16 else instance_id,
        "instance_id_full": instance_id,
        "uptime_seconds": round(uptime_seconds, 1),
        "cold_start": {
            "likely_cold_start": uptime_seconds < 60,
            "startup_time": _MODULE_LOAD_TIME.isoformat(),
            "uptime_category": (
                "cold" if uptime_seconds < 60
                else "warm" if uptime_seconds < 300
                else "stable"
            ),
        },
        "worker_process_count": int(os.environ.get('WEBSITE_WORKER_COUNT', '1')),
    }

    if role_instance:
        result["role_instance_id"] = role_instance

    # Add Azure-specific info if available
    site_name = os.environ.get('WEBSITE_SITE_NAME')
    if site_name:
        result["site_name"] = site_name
        result["is_azure"] = True
    else:
        result["is_azure"] = False

    return result


def get_connection_pool_stats() -> Dict[str, Dict[str, Any]]:
    """
    Get connection pool statistics.

    Returns:
        Dict with pool stats by pool name
    """
    pools = {}

    # Try to get PostgreSQL pool stats
    try:
        # Check if psycopg pool is available
        # Note: Our current implementation creates connections on-demand,
        # not using a persistent pool, so we report that
        pools["postgresql"] = {
            "type": "on-demand",
            "note": "Connections created per-request (no persistent pool)",
            "recommendation": "Consider psycopg_pool for high-throughput scenarios",
        }
    except Exception as e:
        pools["postgresql"] = {
            "status": "unknown",
            "error": str(e),
        }

    # Check for any Azure SDK connection info
    try:
        # Service Bus typically uses AMQP connection pooling internally
        pools["service_bus"] = {
            "type": "azure-sdk-managed",
            "note": "Connection pooling handled by azure-servicebus SDK",
        }
    except Exception:
        pass

    # Blob storage uses HTTP connection pooling
    pools["blob_storage"] = {
        "type": "http-pooling",
        "note": "Uses requests/urllib3 connection pooling (default)",
    }

    return pools


def get_network_summary() -> Dict[str, Any]:
    """
    Get network environment summary.

    Returns:
        Dict with network configuration summary
    """
    summary = {
        "vnet_integrated": False,
        "private_endpoints_likely": False,
        "environment": "unknown",
    }

    # Check for VNet integration
    private_ip = os.environ.get('WEBSITE_PRIVATE_IP')
    if private_ip:
        summary["vnet_integrated"] = True
        summary["private_ip"] = private_ip

    vnet_route_all = os.environ.get('WEBSITE_VNET_ROUTE_ALL')
    if vnet_route_all:
        summary["vnet_route_all"] = vnet_route_all.lower() == '1'

    # Check DNS configuration
    dns_server = os.environ.get('WEBSITE_DNS_SERVER')
    if dns_server:
        summary["custom_dns"] = True
        summary["dns_server"] = dns_server
    else:
        summary["custom_dns"] = False

    # Determine environment type
    ase_name = os.environ.get('WEBSITE_ASE_NAME')
    if ase_name:
        summary["environment"] = "ase"
        summary["ase_name"] = ase_name
    elif private_ip:
        summary["environment"] = "vnet-integrated"
    elif os.environ.get('WEBSITE_SITE_NAME'):
        summary["environment"] = "azure-standard"
    else:
        summary["environment"] = "local-dev"

    # Check for private endpoint indicators
    # Private endpoints typically result in private IPs for Azure services
    summary["private_endpoints_likely"] = summary["vnet_integrated"] and summary.get("custom_dns", False)

    # Outbound IP (if available)
    outbound_ips = os.environ.get('WEBSITE_OUTBOUND_IPS')
    if outbound_ips:
        summary["outbound_ips"] = outbound_ips.split(',')[:3]  # First 3

    return summary


# ============================================================================
# MAIN DIAGNOSTICS FUNCTION
# ============================================================================

def get_diagnostics(
    check_dependencies: bool = True,
    check_dns: bool = True,
    check_pools: bool = True,
    check_instance: bool = True,
    check_network: bool = True,
    dependency_timeout: float = CONNECTIVITY_TIMEOUT,
) -> DiagnosticsResult:
    """
    Run system diagnostics.

    Args:
        check_dependencies: Check connectivity to dependencies
        check_dns: Check DNS resolution timing
        check_pools: Check connection pool stats
        check_instance: Check instance/cold start info
        check_network: Check network environment
        dependency_timeout: Timeout for dependency checks

    Returns:
        DiagnosticsResult with all requested checks
    """
    start = time.perf_counter()
    result = DiagnosticsResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=0,
    )

    # Get hosts from environment
    postgres_host = os.environ.get('POSTGIS_HOST')
    service_bus_fqdn = os.environ.get('SERVICE_BUS_FQDN')
    bronze_storage = os.environ.get('BRONZE_STORAGE_ACCOUNT')
    silver_storage = os.environ.get('SILVER_STORAGE_ACCOUNT')

    # Dependency connectivity checks (in parallel)
    if check_dependencies:
        dependencies = {}

        # Build list of checks
        checks_to_run = []
        if postgres_host:
            port = int(os.environ.get('POSTGIS_PORT', '5432'))
            checks_to_run.append(("database", postgres_host, port))
        if service_bus_fqdn:
            checks_to_run.append(("service_bus", service_bus_fqdn, 5671))
            checks_to_run.append(("service_bus_https", service_bus_fqdn, 443))
        if bronze_storage:
            checks_to_run.append(("bronze_storage", f"{bronze_storage}.blob.core.windows.net", 443))
        if silver_storage and silver_storage != bronze_storage:
            checks_to_run.append(("silver_storage", f"{silver_storage}.blob.core.windows.net", 443))

        # Run checks in parallel with timeout
        if checks_to_run:
            with ThreadPoolExecutor(max_workers=len(checks_to_run)) as executor:
                futures = {
                    executor.submit(
                        check_connectivity, name, host, port, dependency_timeout
                    ): name
                    for name, host, port in checks_to_run
                }

                for future in futures:
                    name = futures[future]
                    try:
                        check_result = future.result(timeout=dependency_timeout + 1)
                        dependencies[name] = check_result.to_dict()
                    except FuturesTimeoutError:
                        dependencies[name] = {
                            "status": "timeout",
                            "error": f"Check timed out after {dependency_timeout}s",
                        }
                    except Exception as e:
                        dependencies[name] = {
                            "status": "error",
                            "error": str(e),
                        }

        result.dependencies = dependencies

    # DNS resolution timing
    if check_dns:
        dns_results = {}
        hostnames_to_check = []

        if postgres_host:
            hostnames_to_check.append(postgres_host)
        if service_bus_fqdn:
            hostnames_to_check.append(service_bus_fqdn)
        if bronze_storage:
            hostnames_to_check.append(f"{bronze_storage}.blob.core.windows.net")
        if silver_storage and silver_storage != bronze_storage:
            hostnames_to_check.append(f"{silver_storage}.blob.core.windows.net")

        for hostname in hostnames_to_check:
            dns_check = check_dns_resolution(hostname)
            dns_results[hostname] = dns_check.to_dict()

        result.dns_resolution = dns_results

    # Connection pool stats
    if check_pools:
        result.connection_pools = get_connection_pool_stats()

    # Instance info
    if check_instance:
        result.instance = get_instance_info()

    # Network summary
    if check_network:
        result.network = get_network_summary()

    result.duration_ms = (time.perf_counter() - start) * 1000
    return result


def get_diagnostics_summary() -> Dict[str, Any]:
    """
    Get a lightweight diagnostics summary for readyz.

    Only includes quick checks - no network calls.

    Returns:
        Dict with summary suitable for readyz response
    """
    instance = get_instance_info()
    network = get_network_summary()

    return {
        "instance_id": instance.get("instance_id"),
        "uptime_seconds": instance.get("uptime_seconds"),
        "cold_start": instance.get("cold_start", {}).get("likely_cold_start"),
        "environment": network.get("environment"),
        "vnet_integrated": network.get("vnet_integrated"),
    }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "get_diagnostics",
    "get_diagnostics_summary",
    "check_connectivity",
    "check_dns_resolution",
    "get_instance_info",
    "get_connection_pool_stats",
    "get_network_summary",
    "DiagnosticsResult",
    "DependencyCheck",
    "DNSCheck",
]
