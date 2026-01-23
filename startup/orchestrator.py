# ============================================================================
# STARTUP VALIDATION ORCHESTRATOR
# ============================================================================
# STATUS: Infrastructure - Startup validation coordination
# PURPOSE: Run all validation phases in order and populate STARTUP_STATE
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 1 Startup Logic Extraction
# ============================================================================
"""
Startup Validation Orchestrator.

Runs all validation phases in order and populates STARTUP_STATE.
This module coordinates between individual validators and ensures
proper sequencing (e.g., DNS before queue validation).

Validation Phases:
    1. Environment variables (regex validation)
    2. Critical imports (module availability)
    3. Service Bus DNS (namespace resolves)
    4. Service Bus queues (required queues exist)

Usage:
    from startup import run_startup_validation, STARTUP_STATE

    run_startup_validation()

    if STARTUP_STATE.all_passed:
        # Register triggers
        pass
"""

import logging
import os
from typing import Optional

from startup_state import STARTUP_STATE, ValidationResult

# Create startup logger (minimal dependencies)
_logger = logging.getLogger("startup.orchestrator")


def run_startup_validation(
    app_mode_config: Optional[object] = None,
    app_config: Optional[object] = None
) -> None:
    """
    Run all startup validations and finalize STARTUP_STATE.

    This is the main entry point for startup validation. It runs all
    validation phases in order and populates the global STARTUP_STATE
    singleton with results.

    Args:
        app_mode_config: Optional AppModeConfig instance (lazy-loaded if None)
        app_config: Optional AppConfig instance (lazy-loaded if None)

    Side Effects:
        - Populates STARTUP_STATE with validation results
        - Logs validation progress and results
    """
    _logger.info("=" * 70)
    _logger.info("STARTUP VALIDATION STARTING")
    _logger.info("=" * 70)

    # Phase 1: Environment variable validation
    _logger.info("Phase 1: Validating environment variables...")
    STARTUP_STATE.env_vars = _validate_environment()

    if not STARTUP_STATE.env_vars.passed:
        _logger.critical(f"Phase 1 FAILED: {STARTUP_STATE.env_vars.error_message}")
        # Continue to finalize even on failure

    # Phase 2: Import validation
    _logger.info("Phase 2: Validating critical imports...")
    STARTUP_STATE.imports = _validate_imports()

    if not STARTUP_STATE.imports.passed:
        _logger.critical(f"Phase 2 FAILED: {STARTUP_STATE.imports.error_message}")

    # Phase 3 & 4: Service Bus validation (DNS + queues)
    # Only run if we have valid env vars and imports
    if STARTUP_STATE.env_vars.passed and STARTUP_STATE.imports.passed:
        _logger.info("Phase 3: Validating Service Bus DNS...")
        _logger.info("Phase 4: Validating Service Bus queues...")

        dns_result, queue_result = _validate_service_bus(app_mode_config, app_config)
        STARTUP_STATE.service_bus_dns = dns_result
        STARTUP_STATE.service_bus_queues = queue_result
    else:
        _logger.warning("Skipping Service Bus validation (previous phases failed)")
        STARTUP_STATE.service_bus_dns = ValidationResult(
            name="service_bus_dns",
            passed=False,
            error_type="SKIPPED",
            error_message="Skipped due to earlier validation failures",
        )
        STARTUP_STATE.service_bus_queues = ValidationResult(
            name="service_bus_queues",
            passed=False,
            error_type="SKIPPED",
            error_message="Skipped due to earlier validation failures",
        )

    # Finalize startup state
    STARTUP_STATE.finalize()

    # Detect env vars using defaults (informational warnings)
    STARTUP_STATE.detect_default_env_vars()

    # Log observability mode status
    _log_observability_status()

    # Initialize metrics blob container if enabled
    _init_metrics_container()

    # Log final status
    _logger.info("=" * 70)
    if STARTUP_STATE.all_passed:
        _logger.info("STARTUP VALIDATION COMPLETE - All checks PASSED")
    else:
        failed = STARTUP_STATE.get_failed_checks()
        _logger.warning(f"STARTUP VALIDATION COMPLETE - {len(failed)} check(s) FAILED")
        _logger.warning(f"Failed: {[f.name for f in failed]}")
        _logger.warning("Service Bus triggers will NOT be registered")
        _logger.warning("App will respond to /api/livez, /api/readyz, /api/health only")
    _logger.info("=" * 70)


def _validate_environment() -> ValidationResult:
    """
    Validate environment variables using config.env_validation.

    Returns:
        ValidationResult with pass/fail status
    """
    try:
        from config.env_validation import validate_environment, log_validation_results

        # Run validation (includes warnings for optional vars using defaults)
        errors = validate_environment(include_warnings=False)  # Only errors

        if errors:
            # Log errors for visibility
            log_validation_results(_logger)

            error_vars = [e.var_name for e in errors]
            return ValidationResult(
                name="env_vars",
                passed=False,
                error_type="INVALID_ENV_VARS",
                error_message=f"Invalid environment variables: {', '.join(error_vars)}",
                details={
                    "error_count": len(errors),
                    "error_vars": error_vars,
                    "errors": [e.to_dict() for e in errors],
                }
            )

        _logger.info("Environment variables validated successfully")
        return ValidationResult(
            name="env_vars",
            passed=True,
            details={"message": "All required environment variables valid"}
        )

    except Exception as e:
        _logger.error(f"Environment validation exception: {e}")
        return ValidationResult(
            name="env_vars",
            passed=False,
            error_type="VALIDATION_EXCEPTION",
            error_message=str(e),
        )


def _validate_imports() -> ValidationResult:
    """
    Validate that critical modules can be imported.

    Returns:
        ValidationResult with pass/fail status
    """
    from .import_validator import validate_critical_imports
    return validate_critical_imports()


def _validate_service_bus(
    app_mode_config: Optional[object] = None,
    app_config: Optional[object] = None
) -> tuple[ValidationResult, ValidationResult]:
    """
    Validate Service Bus DNS and queues.

    Args:
        app_mode_config: Optional AppModeConfig instance
        app_config: Optional AppConfig instance

    Returns:
        Tuple of (dns_result, queue_result)
    """
    from .service_bus_validator import validate_service_bus
    return validate_service_bus(app_mode_config, app_config)


def _log_observability_status() -> None:
    """Log observability mode status."""
    try:
        from config import get_config
        obs_config = get_config().observability

        if obs_config.enabled:
            _logger.info(
                f"OBSERVABILITY_MODE=true "
                f"(app={obs_config.app_name}, env={obs_config.environment})"
            )
        else:
            _logger.warning(
                "OBSERVABILITY_MODE not set or false - "
                "debug instrumentation disabled"
            )
    except Exception as e:
        _logger.debug(f"Observability config check skipped: {e}")


def _init_metrics_container() -> None:
    """Initialize metrics blob container if observability is enabled."""
    try:
        from infrastructure.metrics_blob_logger import init_metrics_container

        if init_metrics_container():
            _logger.info("Metrics container 'applogs' initialized")
    except Exception as e:
        _logger.debug(f"Metrics container init skipped: {e}")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ['run_startup_validation']
