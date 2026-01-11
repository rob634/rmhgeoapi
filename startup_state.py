# ============================================================================
# STARTUP STATE MODULE
# ============================================================================
# STATUS: Infrastructure - Startup validation state storage
# PURPOSE: Store validation results for diagnostic endpoints (livez/readyz/health)
# LAST_REVIEWED: 03 JAN 2026
# REVIEW_STATUS: New file - part of STARTUP_REFORM.md implementation
# ============================================================================
"""
Startup State Module.

Stores validation results for diagnostic endpoints. This module has ZERO
dependencies on other project modules to ensure it loads first.

This is part of the Kubernetes-style health probe implementation that allows
diagnostic endpoints (/api/livez, /api/readyz, /api/health) to be available
even when startup validation fails.

See STARTUP_REFORM.md for full design documentation.

Exports:
    ValidationResult: Dataclass for individual validation check results
    StartupState: Dataclass for overall startup state
    STARTUP_STATE: Global singleton instance

Usage:
    from startup_state import STARTUP_STATE, ValidationResult

    # Store a validation result
    STARTUP_STATE.env_vars = ValidationResult(
        name="env_vars",
        passed=False,
        error_type="MISSING_ENV_VARS",
        error_message="Missing: POSTGIS_HOST, SERVICE_BUS_FQDN"
    )

    # Check if all validations passed
    if STARTUP_STATE.all_passed:
        # Register operational triggers
        pass

    # Get failed checks for error reporting
    failed = STARTUP_STATE.get_failed_checks()
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone


@dataclass
class ConfigWarning:
    """
    Warning for a configuration value using its default.

    These are not errors - the app works fine - but useful for debugging
    when behavior differs between environments (DEV vs QA).
    """
    var_name: str
    default_value: str
    description: str
    category: str = "config"  # config, metrics, debug

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "var_name": self.var_name,
            "default_value": self.default_value,
            "description": self.description,
            "category": self.category,
        }


@dataclass
class ValidationResult:
    """
    Result of a single validation check.

    Attributes:
        name: Identifier for this validation (e.g., "env_vars", "service_bus_dns")
        passed: Whether the validation passed
        error_type: Category of error if failed (e.g., "DNS_RESOLUTION_FAILED")
        error_message: Human-readable error description
        details: Additional context (IPs resolved, missing vars, etc.)
        timestamp: When this validation was performed
    """
    name: str
    passed: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        result = {
            "name": self.name,
            "passed": self.passed,
            "timestamp": self.timestamp
        }
        if self.error_type:
            result["error_type"] = self.error_type
        if self.error_message:
            result["error_message"] = self.error_message
        if self.details:
            result["details"] = self.details
        return result


@dataclass
class StartupState:
    """
    Global startup state for diagnostic endpoints.

    This class stores the results of all startup validation checks.
    It's designed to be populated during function_app.py startup and
    read by the livez/readyz/health endpoints.

    Validation Checks:
        env_vars: Required environment variables present
        imports: Critical Python modules importable
        service_bus_dns: Service Bus namespace DNS resolves
        service_bus_queues: Required queues exist and accessible
        database: PostgreSQL connection works

    Attributes:
        validation_complete: True when all checks have run (pass or fail)
        all_passed: True only if ALL checks passed
        startup_time: When the app started
    """

    # Individual validation results
    env_vars: Optional[ValidationResult] = None
    imports: Optional[ValidationResult] = None
    service_bus_dns: Optional[ValidationResult] = None
    service_bus_queues: Optional[ValidationResult] = None
    database: Optional[ValidationResult] = None

    # Overall status
    validation_complete: bool = False
    all_passed: bool = False
    startup_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Error summary for quick access
    critical_error: Optional[str] = None

    # Warnings for env vars using defaults (not errors, just informational)
    config_warnings: List[ConfigWarning] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "validation_complete": self.validation_complete,
            "all_passed": self.all_passed,
            "startup_time": self.startup_time,
            "critical_error": self.critical_error,
            "checks": {
                "env_vars": self.env_vars.to_dict() if self.env_vars else None,
                "imports": self.imports.to_dict() if self.imports else None,
                "service_bus_dns": self.service_bus_dns.to_dict() if self.service_bus_dns else None,
                "service_bus_queues": self.service_bus_queues.to_dict() if self.service_bus_queues else None,
                "database": self.database.to_dict() if self.database else None,
            }
        }

    def get_failed_checks(self) -> List[ValidationResult]:
        """Get list of failed validation checks."""
        checks = [
            self.env_vars,
            self.imports,
            self.service_bus_dns,
            self.service_bus_queues,
            self.database
        ]
        return [c for c in checks if c is not None and not c.passed]

    def get_passed_checks(self) -> List[ValidationResult]:
        """Get list of passed validation checks."""
        checks = [
            self.env_vars,
            self.imports,
            self.service_bus_dns,
            self.service_bus_queues,
            self.database
        ]
        return [c for c in checks if c is not None and c.passed]

    def finalize(self) -> None:
        """
        Mark validation as complete and compute all_passed.

        Call this after all validation checks have been performed.
        """
        self.validation_complete = True

        # Check if all performed validations passed
        checks = [
            self.env_vars,
            self.imports,
            self.service_bus_dns,
            self.service_bus_queues,
            # Note: database is optional, don't require it
        ]

        # Filter to only checks that were actually performed
        performed = [c for c in checks if c is not None]

        if not performed:
            # No checks performed - consider it failed
            self.all_passed = False
            self.critical_error = "No validation checks were performed"
        else:
            self.all_passed = all(c.passed for c in performed)

            if not self.all_passed:
                failed = self.get_failed_checks()
                if failed:
                    # Set critical error to first failure
                    first_fail = failed[0]
                    self.critical_error = f"{first_fail.name}: {first_fail.error_message or first_fail.error_type}"

    def get_summary(self) -> Dict[str, Any]:
        """Get a brief summary suitable for readyz response."""
        failed = self.get_failed_checks()
        passed = self.get_passed_checks()

        return {
            "validation_complete": self.validation_complete,
            "all_passed": self.all_passed,
            "checks_passed": len(passed),
            "checks_failed": len(failed),
            "failed_check_names": [f.name for f in failed],
            "critical_error": self.critical_error,
            "warning_count": len(self.config_warnings),
        }

    def get_warnings(self) -> List[Dict[str, Any]]:
        """Get list of config warnings as dicts."""
        return [w.to_dict() for w in self.config_warnings]

    def detect_default_env_vars(self) -> None:
        """
        Detect which optional env vars are using defaults and add warnings.

        Call this during startup after validation passes. These are not
        errors - the app works fine - but help debug environment differences.
        """
        self.config_warnings = []

        for var_name, info in ENV_VARS_WITH_DEFAULTS.items():
            current_value = os.environ.get(var_name)
            if current_value is None or current_value == "":
                self.config_warnings.append(ConfigWarning(
                    var_name=var_name,
                    default_value=info["default"],
                    description=info["description"],
                    category=info.get("category", "config"),
                ))


# ============================================================================
# ENV VARS WITH DEFAULTS - Registry for warning detection
# ============================================================================
# These are optional env vars that have sensible defaults. When not explicitly
# set, the app works but behavior may differ between environments. Useful for
# debugging "why does QA behave differently than DEV?"
# ============================================================================

ENV_VARS_WITH_DEFAULTS: Dict[str, Dict[str, str]] = {
    # Observability flags (10 JAN 2026 - F7.12.C Flag Consolidation)
    "OBSERVABILITY_MODE": {
        "default": "false",
        "description": "Master switch for debug instrumentation (memory tracking, latency logging, blob metrics)",
        "category": "observability",
    },
    # Legacy aliases - kept for backward compatibility, prefer OBSERVABILITY_MODE
    "DEBUG_MODE": {
        "default": "false",
        "description": "[LEGACY] Use OBSERVABILITY_MODE instead. Falls back to this if OBSERVABILITY_MODE not set.",
        "category": "observability",
    },
    "METRICS_DEBUG_MODE": {
        "default": "false",
        "description": "[LEGACY] Use OBSERVABILITY_MODE instead. Falls back to this if OBSERVABILITY_MODE not set.",
        "category": "observability",
    },
    # Logging verbosity - use LOG_LEVEL=DEBUG instead of DEBUG_LOGGING=true
    "LOG_LEVEL": {
        "default": "INFO",
        "description": "Logging verbosity (DEBUG, INFO, WARNING, ERROR). Use DEBUG for verbose logging.",
        "category": "observability",
    },
    # ETL metrics (separate purpose - not consolidated)
    "METRICS_ENABLED": {
        "default": "true",
        "description": "Master switch for job/ETL metrics collection (separate from OBSERVABILITY_MODE)",
        "category": "metrics",
    },
    "SERVICE_LATENCY_SLOW_MS": {
        "default": "2000",
        "description": "Threshold (ms) for slow operation warnings",
        "category": "metrics",
    },

    # Connection/Pool settings
    "DB_POOL_MIN": {
        "default": "1",
        "description": "Minimum database connection pool size",
        "category": "database",
    },
    "DB_POOL_MAX": {
        "default": "10",
        "description": "Maximum database connection pool size",
        "category": "database",
    },
    "POSTGIS_PORT": {
        "default": "5432",
        "description": "PostgreSQL port",
        "category": "database",
    },

    # Feature flags
    "USE_MANAGED_IDENTITY": {
        "default": "true",
        "description": "Use Azure Managed Identity for auth (false = password auth)",
        "category": "auth",
    },

    # Optional storage tiers
    "SILVEREXT_STORAGE_ACCOUNT": {
        "default": "(uses SILVER_STORAGE_ACCOUNT)",
        "description": "External silver zone storage account",
        "category": "storage",
    },
    "GOLD_STORAGE_ACCOUNT": {
        "default": "(uses SILVER_STORAGE_ACCOUNT)",
        "description": "Gold tier storage account for exports",
        "category": "storage",
    },

    # Service URLs (optional)
    "TITILER_BASE_URL": {
        "default": "(not configured)",
        "description": "TiTiler service URL for raster tiles",
        "category": "services",
    },
    "OGC_BASE_URL": {
        "default": "(auto-detected from request)",
        "description": "OGC API base URL for self-links (set explicitly for consistent URLs)",
        "category": "services",
    },
    "OGC_STAC_APP_URL": {
        "default": "(not configured)",
        "description": "Dedicated OGC/STAC app URL (for multi-app deployments)",
        "category": "services",
    },
}


# Global singleton instance - imported by diagnostic endpoints
# This is populated during function_app.py startup
STARTUP_STATE = StartupState()
