# ============================================================================
# SERVICE BUS VALIDATOR
# ============================================================================
# STATUS: Infrastructure - Service Bus connectivity validation
# PURPOSE: Validate Service Bus DNS resolution and queue existence
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 1 Startup Logic Extraction
# ============================================================================
"""
Service Bus Validator Module.

Validates Service Bus connectivity at startup:
1. DNS Resolution: Verify namespace FQDN resolves
2. Queue Existence: Verify required queues exist and are accessible

This validation runs AFTER environment and import validation passes.
Results determine whether Service Bus triggers are registered.

DNS Validation:
    - Resolves namespace hostname to IP addresses
    - Detects private endpoints (10.x, 172.x, 192.168.x IPs)
    - Identifies VNet/DNS configuration issues

Queue Validation:
    - Checks required queues based on APP_MODE configuration
    - Classifies errors (AUTH_FAILED, TIMEOUT, CONNECTION_FAILED)
    - Provides actionable fix suggestions

Usage:
    from startup.service_bus_validator import validate_service_bus

    dns_result, queue_result = validate_service_bus()

    if dns_result.passed and queue_result.passed:
        # Register Service Bus triggers
        pass
"""

import logging
import socket
from typing import List, Dict, Any, Optional, Tuple

from .state import ValidationResult

_logger = logging.getLogger("startup.service_bus_validator")


def validate_service_bus(
    app_mode_config: Optional[object] = None,
    app_config: Optional[object] = None
) -> Tuple[ValidationResult, ValidationResult]:
    """
    Validate Service Bus DNS and queues.

    Args:
        app_mode_config: Optional AppModeConfig instance (lazy-loaded if None)
        app_config: Optional AppConfig instance (lazy-loaded if None)

    Returns:
        Tuple of (dns_result, queue_result)
    """
    # Lazy load configs if not provided
    if app_mode_config is None:
        from config import get_app_mode_config
        app_mode_config = get_app_mode_config()

    if app_config is None:
        from config import get_config
        app_config = get_config()

    # Build list of required queues based on APP_MODE
    required_queues = _get_required_queues(app_mode_config, app_config)

    if not required_queues:
        # No queues to validate - mark as passed (not applicable)
        _logger.info("No queue validation needed (APP_MODE doesn't listen to any queues)")
        return (
            ValidationResult(
                name="service_bus_dns",
                passed=True,
                details={"message": "No queues configured - DNS check skipped"}
            ),
            ValidationResult(
                name="service_bus_queues",
                passed=True,
                details={"message": "No queues configured"}
            )
        )

    # Phase 1: DNS validation
    dns_result = _validate_dns(app_config)

    if not dns_result.passed:
        # DNS failed - skip queue validation
        _logger.warning("DNS validation failed - skipping queue validation")
        queue_result = ValidationResult(
            name="service_bus_queues",
            passed=False,
            error_type="SKIPPED",
            error_message="Skipped due to DNS resolution failure",
            details={"reason": "DNS must resolve before queue validation can run"}
        )
        return dns_result, queue_result

    # Phase 2: Queue validation
    queue_result = _validate_queues(required_queues)

    return dns_result, queue_result


def _get_required_queues(
    app_mode_config: object,
    app_config: object
) -> List[Dict[str, str]]:
    """
    Build list of required queues based on APP_MODE configuration.

    V0.8 Architecture (24 JAN 2026):
    - geospatial-jobs: Job orchestration
    - functionapp-tasks: FunctionApp worker (lightweight ops)
    - container-tasks: Docker worker (heavy ops)

    Args:
        app_mode_config: AppModeConfig instance
        app_config: AppConfig instance

    Returns:
        List of queue info dicts with name, purpose, and flag
    """
    required_queues = []

    if app_mode_config.listens_to_jobs_queue:
        required_queues.append({
            "name": app_config.service_bus_jobs_queue,
            "purpose": "Job orchestration + stage_complete signals",
            "flag": "listens_to_jobs_queue"
        })

    # V0.9: Docker-only queue (19 FEB 2026)
    if app_mode_config.listens_to_container_tasks:
        required_queues.append({
            "name": app_config.queues.container_tasks_queue,
            "purpose": "Container tasks (Docker worker - heavy ops)",
            "flag": "listens_to_container_tasks"
        })

    return required_queues


def _validate_dns(app_config: object) -> ValidationResult:
    """
    Validate Service Bus namespace DNS resolution.

    Args:
        app_config: AppConfig instance

    Returns:
        ValidationResult for DNS validation
    """
    namespace = app_config.service_bus_namespace
    hostname = namespace if "." in namespace else f"{namespace}.servicebus.windows.net"

    _logger.info(f"Checking DNS for Service Bus namespace: {hostname}")

    try:
        # Resolve hostname
        dns_results = socket.getaddrinfo(hostname, 5671, socket.AF_UNSPEC, socket.SOCK_STREAM)
        resolved_ips = list(set([addr[4][0] for addr in dns_results]))

        # Check for private endpoint IPs
        is_private = any(
            ip.startswith("10.") or
            ip.startswith("172.") or
            ip.startswith("192.168.")
            for ip in resolved_ips
        )

        _logger.info(f"DNS resolved {hostname} -> {resolved_ips[:3]}")
        if is_private:
            _logger.info("Private IP detected - using Private Endpoint or VNet integration")

        return ValidationResult(
            name="service_bus_dns",
            passed=True,
            details={
                "hostname": hostname,
                "resolved_ips": resolved_ips[:3],
                "is_private_endpoint": is_private
            }
        )

    except socket.gaierror as dns_error:
        _logger.critical(f"DNS resolution failed for {hostname}: {dns_error}")
        return ValidationResult(
            name="service_bus_dns",
            passed=False,
            error_type="DNS_RESOLUTION_FAILED",
            error_message=str(dns_error),
            details={
                "hostname": hostname,
                "likely_causes": [
                    "SERVICE_BUS_FQDN env var has wrong value",
                    "VNet DNS configuration issue (ASE/Private Endpoint)",
                    "Private DNS zone not linked to VNet",
                    "Network isolation blocking DNS resolution"
                ],
                "fix": "Check Azure Portal -> Service Bus -> Networking settings"
            }
        )

    except Exception as e:
        _logger.critical(f"DNS check exception: {e}")
        return ValidationResult(
            name="service_bus_dns",
            passed=False,
            error_type="DNS_CHECK_EXCEPTION",
            error_message=str(e),
            details={"exception_type": type(e).__name__}
        )


def _validate_queues(required_queues: List[Dict[str, str]]) -> ValidationResult:
    """
    Validate that required Service Bus queues exist.

    Args:
        required_queues: List of queue info dicts

    Returns:
        ValidationResult for queue validation
    """
    try:
        from infrastructure.service_bus import ServiceBusRepository
        sb_repo = ServiceBusRepository()
    except ImportError as ie:
        _logger.warning(f"Could not import ServiceBusRepository: {ie}")
        return ValidationResult(
            name="service_bus_queues",
            passed=False,
            error_type="IMPORT_FAILED",
            error_message=str(ie),
            details={"message": "Could not import ServiceBusRepository"}
        )

    missing_queues = []
    connection_errors = []
    validated_queues = []

    for queue_info in required_queues:
        queue_name = queue_info["name"]

        try:
            if not sb_repo.queue_exists(queue_name):
                missing_queues.append(queue_info)
                _logger.warning(f"Queue missing: {queue_name} ({queue_info['purpose']})")
            else:
                validated_queues.append(queue_name)
                _logger.info(f"Queue exists: {queue_name}")

        except Exception as qe:
            error_info = _classify_queue_error(qe, queue_info)
            connection_errors.append(error_info)
            _logger.warning(f"Queue connection error: {queue_name} - {error_info['error_type']}")

    # Build result
    if connection_errors or missing_queues:
        return ValidationResult(
            name="service_bus_queues",
            passed=False,
            error_type="QUEUE_VALIDATION_FAILED",
            error_message=f"{len(connection_errors)} connection errors, {len(missing_queues)} missing queues",
            details={
                "connection_errors": [
                    {"name": q["name"], "error_type": q["error_type"], "fix": q["fix"]}
                    for q in connection_errors
                ],
                "missing_queues": [q["name"] for q in missing_queues],
                "validated_queues": validated_queues
            }
        )

    _logger.info(f"All {len(required_queues)} required queues validated")
    return ValidationResult(
        name="service_bus_queues",
        passed=True,
        details={"validated_queues": validated_queues}
    )


def _classify_queue_error(error: Exception, queue_info: Dict[str, str]) -> Dict[str, Any]:
    """
    Classify a queue validation error and provide fix suggestions.

    Args:
        error: The exception that occurred
        queue_info: Queue info dict with name, purpose, flag

    Returns:
        Extended queue_info dict with error_type, error, and fix
    """
    error_str = str(error).lower()
    result = dict(queue_info)

    if "unauthorized" in error_str or "401" in str(error) or "403" in str(error):
        result["error_type"] = "AUTH_FAILED"
        result["error"] = str(error)[:200]
        result["fix"] = "Check managed identity role: Azure Service Bus Data Owner"

    elif "timeout" in error_str or "timed out" in error_str:
        result["error_type"] = "TIMEOUT"
        result["error"] = str(error)[:200]
        result["fix"] = "Network connectivity issue - check NSG/firewall rules"

    elif "socket" in error_str or "connection" in error_str:
        result["error_type"] = "CONNECTION_FAILED"
        result["error"] = str(error)[:200]
        result["fix"] = "Check VNet service endpoints or private endpoint config"

    else:
        result["error_type"] = "UNKNOWN"
        result["error"] = str(error)[:200]
        result["fix"] = "Check Application Insights for details"

    return result


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'validate_service_bus',
]
