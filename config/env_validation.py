# ============================================================================
# ENVIRONMENT VARIABLE VALIDATION
# ============================================================================
# STATUS: Configuration - Startup validation with regex patterns
# PURPOSE: Validate env vars at startup to fail fast with clear error messages
# LAST_REVIEWED: 26 JAN 2026
# REVIEW_STATUS: New file - part of startup validation enhancement
# ============================================================================
"""
Environment Variable Validation Module.

Validates environment variables at startup using regex patterns to catch
configuration errors EARLY with clear, actionable error messages.

This module is designed to be imported at the very start of function_app.py,
BEFORE any heavy imports that depend on these configuration values.

Design Philosophy:
    - FAIL FAST: Catch config errors at startup, not at runtime
    - CLEAR ERRORS: Show exactly what's wrong and how to fix it
    - REGEX VALIDATION: Format validation, not just presence checks
    - ZERO DEPENDENCIES: Only standard library imports

Usage:
    from config.env_validation import validate_environment, ENV_VAR_RULES

    # Returns list of ValidationError (empty if all valid)
    errors = validate_environment()

    for error in errors:
        print(f"{error.var_name}: {error.message}")
        print(f"  Current value: {error.current_value}")
        print(f"  Expected: {error.expected_pattern}")
        print(f"  Fix: {error.fix_suggestion}")

Example Validations:
    - SERVICE_BUS_FQDN must end in .servicebus.windows.net
    - POSTGIS_HOST must end in .postgres.database.azure.com or be localhost
    - BRONZE_STORAGE_ACCOUNT must be lowercase alphanumeric (3-24 chars)
    - Schema names must be lowercase alphanumeric with underscores

Exports:
    ENV_VAR_RULES: Dict of all validation rules
    ValidationError: Dataclass for validation errors
    validate_environment: Main validation function
    validate_single_var: Validate one variable
"""

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Pattern, Any


# ============================================================================
# VALIDATION ERROR
# ============================================================================

@dataclass
class ValidationError:
    """Result of a failed environment variable validation."""
    var_name: str
    message: str
    current_value: Optional[str]
    expected_pattern: str
    fix_suggestion: str
    severity: str = "error"  # error, warning

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "var_name": self.var_name,
            "message": self.message,
            "current_value": self._mask_sensitive(self.current_value),
            "expected_pattern": self.expected_pattern,
            "fix_suggestion": self.fix_suggestion,
            "severity": self.severity,
        }

    def _mask_sensitive(self, value: Optional[str]) -> Optional[str]:
        """Mask potentially sensitive values."""
        if value is None:
            return None
        sensitive_keywords = ["password", "secret", "key", "token", "connection"]
        var_lower = self.var_name.lower()
        if any(kw in var_lower for kw in sensitive_keywords):
            return "***MASKED***"
        # Show first 20 chars for long values
        if len(value) > 30:
            return f"{value[:20]}...({len(value)} chars)"
        return value


# ============================================================================
# VALIDATION RULE DEFINITION
# ============================================================================

@dataclass
class EnvVarRule:
    """
    Validation rule for an environment variable.

    Attributes:
        pattern: Compiled regex pattern for validation
        pattern_description: Human-readable description of expected format
        required: Whether this variable must be set
        fix_suggestion: How to fix if validation fails
        example: Example valid value
        allow_empty: Allow empty string (default False)
        default_value: Default value used if not set (for warning messages)
        warn_on_default: Emit warning when using default value (default True for optional vars)
    """
    pattern: Pattern
    pattern_description: str
    required: bool
    fix_suggestion: str
    example: str
    allow_empty: bool = False
    default_value: Optional[str] = None
    warn_on_default: bool = True


# ============================================================================
# VALIDATION RULES - Single source of truth for env var formats
# ============================================================================

# Common regex patterns (reusable)
_AZURE_STORAGE_ACCOUNT = re.compile(r"^[a-z0-9]{3,24}$")
_AZURE_HOST_FQDN = re.compile(r"^[a-z0-9][a-z0-9-]*\.(postgres\.database\.azure\.com|database\.windows\.net)$", re.IGNORECASE)
# Service Bus FQDN: Accept multiple Azure cloud domains (09 JAN 2026)
# - .servicebus.windows.net (Azure Public)
# - .servicebus.usgovcloudapi.net (Azure Government)
# - .servicebus.chinacloudapi.cn (Azure China)
# - Any other .servicebus.*.net domain (future-proof)
_SERVICE_BUS_FQDN = re.compile(r"^[a-z0-9][a-z0-9-]*\.servicebus\.[a-z0-9.-]+$", re.IGNORECASE)
_LOCALHOST_OR_AZURE = re.compile(r"^(localhost|127\.0\.0\.1|[a-z0-9][a-z0-9-]*\.(postgres\.database\.azure\.com|database\.windows\.net))$", re.IGNORECASE)
_SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_DATABASE_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,62}$")
_HTTPS_URL = re.compile(r"^https://[a-z0-9][a-z0-9.-]+\.[a-z]{2,}.*$", re.IGNORECASE)
_APP_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,62}$")
_POSITIVE_INT = re.compile(r"^[1-9][0-9]*$")
_BOOLEAN = re.compile(r"^(true|false|1|0|yes|no)$", re.IGNORECASE)


ENV_VAR_RULES: Dict[str, EnvVarRule] = {
    # =========================================================================
    # SERVICE BUS (Critical - connectivity)
    # =========================================================================
    "SERVICE_BUS_FQDN": EnvVarRule(
        pattern=_SERVICE_BUS_FQDN,
        pattern_description="Must be full FQDN containing .servicebus. (e.g., *.servicebus.windows.net)",
        required=True,
        fix_suggestion="Use full FQDN like 'myservicebus.servicebus.windows.net' (not just 'myservicebus')",
        example="myservicebus.servicebus.windows.net",
    ),

    # Legacy name - still validate if present
    "SERVICE_BUS_NAMESPACE": EnvVarRule(
        pattern=_SERVICE_BUS_FQDN,
        pattern_description="Must be full FQDN containing .servicebus. (DEPRECATED - use SERVICE_BUS_FQDN)",
        required=False,
        fix_suggestion="Rename to SERVICE_BUS_FQDN. Use full FQDN like 'myservicebus.servicebus.windows.net'",
        example="myservicebus.servicebus.windows.net",
    ),

    # =========================================================================
    # DATABASE (Critical - connectivity)
    # =========================================================================
    "POSTGIS_HOST": EnvVarRule(
        pattern=_LOCALHOST_OR_AZURE,
        pattern_description="Must be 'localhost' or Azure FQDN ending in .postgres.database.azure.com",
        required=True,
        fix_suggestion="Use full Azure FQDN like 'myserver.postgres.database.azure.com' or 'localhost' for local dev",
        example="myserver.postgres.database.azure.com",
    ),

    "POSTGIS_DATABASE": EnvVarRule(
        pattern=_DATABASE_NAME,
        pattern_description="Alphanumeric database name (letters, numbers, underscore, hyphen)",
        required=True,
        fix_suggestion="Use a valid PostgreSQL database name",
        example="geodb",
    ),

    "POSTGIS_PORT": EnvVarRule(
        pattern=_POSITIVE_INT,
        pattern_description="Positive integer (default 5432)",
        required=False,
        fix_suggestion="Use a valid port number like 5432",
        example="5432",
    ),

    # =========================================================================
    # DATABASE SCHEMAS (Critical - no defaults)
    # =========================================================================
    "POSTGIS_SCHEMA": EnvVarRule(
        pattern=_SCHEMA_NAME,
        pattern_description="Lowercase schema name (letters, numbers, underscore)",
        required=True,
        fix_suggestion="Set schema name like 'geo'",
        example="geo",
    ),

    "APP_SCHEMA": EnvVarRule(
        pattern=_SCHEMA_NAME,
        pattern_description="Lowercase schema name (letters, numbers, underscore)",
        required=True,
        fix_suggestion="Set schema name like 'app'",
        example="app",
    ),

    "PGSTAC_SCHEMA": EnvVarRule(
        pattern=_SCHEMA_NAME,
        pattern_description="Lowercase schema name (letters, numbers, underscore)",
        required=True,
        fix_suggestion="Set schema name like 'pgstac'",
        example="pgstac",
    ),

    "H3_SCHEMA": EnvVarRule(
        pattern=_SCHEMA_NAME,
        pattern_description="Lowercase schema name (letters, numbers, underscore)",
        required=True,
        fix_suggestion="Set schema name like 'h3'",
        example="h3",
    ),

    # =========================================================================
    # STORAGE ACCOUNTS (Critical - zone-based storage)
    # =========================================================================
    "BRONZE_STORAGE_ACCOUNT": EnvVarRule(
        pattern=_AZURE_STORAGE_ACCOUNT,
        pattern_description="Lowercase alphanumeric, 3-24 characters (Azure storage account name)",
        required=True,
        fix_suggestion="Use a valid Azure storage account name (lowercase, 3-24 chars, no special characters)",
        example="myappbronze",
    ),

    "SILVER_STORAGE_ACCOUNT": EnvVarRule(
        pattern=_AZURE_STORAGE_ACCOUNT,
        pattern_description="Lowercase alphanumeric, 3-24 characters (Azure storage account name)",
        required=True,
        fix_suggestion="Use a valid Azure storage account name (lowercase, 3-24 chars, no special characters)",
        example="myappsilver",
    ),

    "SILVEREXT_STORAGE_ACCOUNT": EnvVarRule(
        pattern=_AZURE_STORAGE_ACCOUNT,
        pattern_description="Lowercase alphanumeric, 3-24 characters (Azure storage account name)",
        required=False,
        fix_suggestion="Use a valid Azure storage account name (falls back to SILVER if not set)",
        example="myappsilverext",
    ),

    "GOLD_STORAGE_ACCOUNT": EnvVarRule(
        pattern=_AZURE_STORAGE_ACCOUNT,
        pattern_description="Lowercase alphanumeric, 3-24 characters (Azure storage account name)",
        required=False,
        fix_suggestion="Use a valid Azure storage account name (falls back to SILVER if not set)",
        example="myappgold",
    ),

    # =========================================================================
    # SERVICE URLS (Critical for operation)
    # =========================================================================
    "TITILER_BASE_URL": EnvVarRule(
        pattern=_HTTPS_URL,
        pattern_description="HTTPS URL (must start with https://)",
        required=False,
        fix_suggestion="Use full HTTPS URL like 'https://mytitiler.azurewebsites.net'",
        example="https://mytitiler.azurewebsites.net",
    ),

    "ETL_APP_URL": EnvVarRule(
        pattern=_HTTPS_URL,
        pattern_description="HTTPS URL (must start with https://)",
        required=False,
        fix_suggestion="Use full HTTPS URL like 'https://myetl.azurewebsites.net'",
        example="https://myetl.azurewebsites.net",
    ),

    # OGC_STAC_APP_URL removed 28 JAN 2026 - OGC Features now served by TiPG at {TITILER_BASE_URL}/vector

    # =========================================================================
    # APPLICATION IDENTITY
    # =========================================================================
    "APP_NAME": EnvVarRule(
        pattern=_APP_NAME,
        pattern_description="Alphanumeric app name (letters, numbers, underscore, hyphen)",
        required=False,
        fix_suggestion="Set to your Function App name",
        example="rmhazuregeoapi",
    ),

    "USE_MANAGED_IDENTITY": EnvVarRule(
        pattern=_BOOLEAN,
        pattern_description="Boolean value (true/false)",
        required=False,
        fix_suggestion="Set to 'true' for Azure deployment, 'false' for local development",
        example="true",
    ),

    # =========================================================================
    # OBSERVABILITY (10 JAN 2026 - F7.12.C Flag Consolidation)
    # =========================================================================
    "APPLICATIONINSIGHTS_CONNECTION_STRING": EnvVarRule(
        pattern=re.compile(r"^InstrumentationKey=[a-f0-9-]{36}.*$", re.IGNORECASE),
        pattern_description="Application Insights connection string (required for Docker telemetry)",
        required=False,
        fix_suggestion="Copy connection string from Application Insights resource in Azure Portal",
        example="InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=...",
        default_value=None,
        warn_on_default=True,  # Warn if telemetry disabled
    ),

    "OBSERVABILITY_MODE": EnvVarRule(
        pattern=_BOOLEAN,
        pattern_description="Boolean value (true/false)",
        required=False,
        fix_suggestion="Set to 'true' to enable debug instrumentation (memory tracking, latency logging)",
        example="true",
    ),

    "LOG_LEVEL": EnvVarRule(
        pattern=re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$", re.IGNORECASE),
        pattern_description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
        required=False,
        fix_suggestion="Set to DEBUG for verbose logging, INFO for normal operation",
        example="INFO",
        default_value="INFO",
    ),

    # =========================================================================
    # APP MODE & DOCKER WORKER (12 JAN 2026)
    # =========================================================================
    "APP_MODE": EnvVarRule(
        pattern=re.compile(r"^(standalone|platform|orchestrator|worker_functionapp|worker_docker)$"),
        pattern_description="Deployment mode (standalone, platform, orchestrator, worker_functionapp, worker_docker)",
        required=False,
        fix_suggestion="Set to 'standalone' for single-app deployment or specific mode for multi-app",
        example="standalone",
        default_value="standalone",
    ),

    "DOCKER_WORKER_ENABLED": EnvVarRule(
        pattern=_BOOLEAN,
        pattern_description="Boolean value (true/false)",
        required=False,
        fix_suggestion="Set to 'true' to enable Docker worker queue validation",
        example="true",
        default_value="false",
    ),

    "DOCKER_WORKER_URL": EnvVarRule(
        pattern=_HTTPS_URL,
        pattern_description="HTTPS URL for Docker worker health checks",
        required=False,
        fix_suggestion="Set to Docker worker URL if using external Docker processing",
        example="https://mydockerworker.azurewebsites.net",
        default_value=None,
        warn_on_default=False,  # Optional - no warning needed
    ),

    # =========================================================================
    # QUEUE CONFIGURATION (12 JAN 2026)
    # =========================================================================
    "SERVICE_BUS_JOBS_QUEUE": EnvVarRule(
        pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
        pattern_description="Queue name (lowercase, alphanumeric with hyphens)",
        required=False,
        fix_suggestion="Set queue name or use default 'geospatial-jobs'",
        example="geospatial-jobs",
        default_value="geospatial-jobs",
    ),

    "SERVICE_BUS_RASTER_TASKS_QUEUE": EnvVarRule(
        pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
        pattern_description="Queue name (lowercase, alphanumeric with hyphens)",
        required=False,
        fix_suggestion="Set queue name or use default 'raster-tasks'",
        example="raster-tasks",
        default_value="raster-tasks",
    ),

    "SERVICE_BUS_VECTOR_TASKS_QUEUE": EnvVarRule(
        pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
        pattern_description="Queue name (lowercase, alphanumeric with hyphens)",
        required=False,
        fix_suggestion="Set queue name or use default 'vector-tasks'",
        example="vector-tasks",
        default_value="vector-tasks",
    ),

    "SERVICE_BUS_LONG_RUNNING_TASKS_QUEUE": EnvVarRule(
        pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
        pattern_description="Queue name (lowercase, alphanumeric with hyphens)",
        required=False,
        fix_suggestion="Set queue name or use default 'long-running-tasks'",
        example="long-running-tasks",
        default_value="long-running-tasks",
    ),

    "SERVICE_BUS_CONTAINER_TASKS_QUEUE": EnvVarRule(
        pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
        pattern_description="Queue name for Docker container tasks (V0.8 critical)",
        required=False,
        fix_suggestion="Set queue name for Docker worker or use default 'container-tasks'",
        example="container-tasks",
        default_value="container-tasks",
    ),

    # =========================================================================
    # RASTER PROCESSING CONFIG (V0.8 - 24 JAN 2026)
    # =========================================================================
    # RASTER_ROUTE_* settings removed in V0.8 - all raster goes to Docker
    # STAC_DEFAULT_COLLECTION removed (14 JAN 2026) - collection_id now required

    "RASTER_USE_ETL_MOUNT": EnvVarRule(
        pattern=_BOOLEAN,
        pattern_description="Enable Azure Files mount for Docker temp files",
        required=False,
        fix_suggestion="Set to 'true' to enable mount (expected in V0.8 production)",
        example="true",
        default_value="true",
    ),

    "RASTER_TILING_THRESHOLD_MB": EnvVarRule(
        pattern=_POSITIVE_INT,
        pattern_description="Size threshold in MB for tiled output vs single COG",
        required=False,
        fix_suggestion="Set size threshold (MB) above which files produce tiled output",
        example="2000",
        default_value="2000",
    ),

    "RASTER_TILE_TARGET_MB": EnvVarRule(
        pattern=_POSITIVE_INT,
        pattern_description="Target size in MB per tile when tiling",
        required=False,
        fix_suggestion="Set target size (MB) per tile",
        example="400",
        default_value="400",
    ),

    "RASTER_COG_COMPRESSION": EnvVarRule(
        pattern=re.compile(r"^(LZW|DEFLATE|ZSTD|JPEG|WEBP|NONE)$", re.IGNORECASE),
        pattern_description="COG compression algorithm",
        required=False,
        fix_suggestion="Set compression: LZW, DEFLATE, ZSTD, JPEG, WEBP, or NONE",
        example="LZW",
        default_value="LZW",
    ),

    "RASTER_TARGET_CRS": EnvVarRule(
        pattern=re.compile(r"^EPSG:\d{4,5}$"),
        pattern_description="Target CRS in EPSG format",
        required=False,
        fix_suggestion="Set target CRS like 'EPSG:4326' for WGS84",
        example="EPSG:4326",
        default_value="EPSG:4326",
    ),

    # =========================================================================
    # ENVIRONMENT & IDENTITY (12 JAN 2026)
    # =========================================================================
    "ENVIRONMENT": EnvVarRule(
        pattern=re.compile(r"^(dev|qa|uat|test|staging|prod|production)$", re.IGNORECASE),
        pattern_description="Environment name (dev, qa, uat, test, staging, prod)",
        required=False,
        fix_suggestion="Set to 'dev', 'qa', 'uat', 'test', 'staging', or 'prod'",
        example="dev",
        default_value="dev",
    ),

    "DB_ADMIN_MANAGED_IDENTITY_NAME": EnvVarRule(
        pattern=_APP_NAME,
        pattern_description="Managed identity name for database admin",
        required=False,
        fix_suggestion="Set to your managed identity name",
        example="myapp-identity",
        default_value=None,
        warn_on_default=False,  # Uses system-assigned MI if not set
    ),

    # =========================================================================
    # VECTOR PROCESSING CONFIG (12 JAN 2026)
    # =========================================================================
    "VECTOR_TARGET_SCHEMA": EnvVarRule(
        pattern=_SCHEMA_NAME,
        pattern_description="Target PostgreSQL schema for vector tables",
        required=False,
        fix_suggestion="Set schema name for vector data output",
        example="geo",
        default_value="geo",
    ),

    # =========================================================================
    # V0.8 DOCKER WORKER CONFIG (26 JAN 2026)
    # =========================================================================
    "RASTER_ETL_MOUNT_PATH": EnvVarRule(
        pattern=re.compile(r"^(/[a-zA-Z0-9._-]+)+$"),
        pattern_description="Unix path for Azure Files mount in Docker container",
        required=False,
        fix_suggestion="Set to mount path like '/mnt/etl' for Docker worker temp files",
        example="/mnt/etl",
        default_value="/mnt/etl",
    ),

    "SERVICE_BUS_FUNCTIONAPP_TASKS_QUEUE": EnvVarRule(
        pattern=re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$"),
        pattern_description="Queue name for Docker worker tasks (lowercase, alphanumeric with hyphens)",
        required=False,
        fix_suggestion="Set queue name for Docker worker or use default 'functionapp-tasks'",
        example="functionapp-tasks",
        default_value="functionapp-tasks",
    ),

    # =========================================================================
    # PLATFORM / CLASSIFICATION CONFIG (26 JAN 2026)
    # =========================================================================
    "PLATFORM_DEFAULT_ACCESS_LEVEL": EnvVarRule(
        pattern=re.compile(r"^(public|internal|restricted|confidential)$", re.IGNORECASE),
        pattern_description="Default data classification level (public, internal, restricted, confidential)",
        required=False,
        fix_suggestion="Set default access level for datasets without explicit classification",
        example="internal",
        default_value="internal",
    ),

    "PLATFORM_WEBHOOK_ENABLED": EnvVarRule(
        pattern=_BOOLEAN,
        pattern_description="Boolean value (true/false) to enable DDH webhooks",
        required=False,
        fix_suggestion="Set to 'true' to enable webhook notifications to DDH",
        example="false",
        default_value="false",
    ),

    "PLATFORM_PRIMARY_CLIENT": EnvVarRule(
        pattern=re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,30}$"),
        pattern_description="Primary client identifier for Platform API",
        required=False,
        fix_suggestion="Set to primary client name (e.g., 'ddh' for Data Development Hub)",
        example="ddh",
        default_value="ddh",
    ),
}


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_single_var(
    var_name: str,
    rule: EnvVarRule,
    include_warnings: bool = True
) -> Optional[ValidationError]:
    """
    Validate a single environment variable against its rule.

    Args:
        var_name: Environment variable name
        rule: Validation rule to apply
        include_warnings: Whether to return warnings for vars using defaults

    Returns:
        ValidationError if validation fails or warning if using default, None if passes
    """
    value = os.environ.get(var_name)

    # Check required
    if rule.required and (value is None or (not rule.allow_empty and value == "")):
        return ValidationError(
            var_name=var_name,
            message=f"Required environment variable not set",
            current_value=value,
            expected_pattern=rule.pattern_description,
            fix_suggestion=f"{rule.fix_suggestion}. Example: {rule.example}",
            severity="error",
        )

    # If not required and not set, emit warning if warn_on_default is True
    if value is None or value == "":
        if include_warnings and not rule.required and rule.warn_on_default and rule.default_value is not None:
            return ValidationError(
                var_name=var_name,
                message=f"Not set, using default value",
                current_value=None,
                expected_pattern=f"Default: {rule.default_value}",
                fix_suggestion=f"Set explicitly or accept default. {rule.fix_suggestion}",
                severity="warning",
            )
        return None

    # Validate pattern
    if not rule.pattern.match(value):
        return ValidationError(
            var_name=var_name,
            message=f"Invalid format",
            current_value=value,
            expected_pattern=rule.pattern_description,
            fix_suggestion=f"{rule.fix_suggestion}. Example: {rule.example}",
            severity="error",
        )

    return None


def validate_environment(
    rules: Optional[Dict[str, EnvVarRule]] = None,
    include_warnings: bool = True
) -> List[ValidationError]:
    """
    Validate all environment variables against their rules.

    Args:
        rules: Optional custom rules dict (defaults to ENV_VAR_RULES)
        include_warnings: Whether to include warnings for vars using defaults

    Returns:
        List of ValidationError objects (errors and optionally warnings)
    """
    if rules is None:
        rules = ENV_VAR_RULES

    results = []
    for var_name, rule in rules.items():
        result = validate_single_var(var_name, rule, include_warnings=include_warnings)
        if result:
            results.append(result)

    return results


def get_validation_summary(include_warnings: bool = True) -> Dict[str, Any]:
    """
    Get a summary of environment variable validation status.

    Args:
        include_warnings: Whether to include warnings in the summary

    Returns:
        Dict with validation summary suitable for health endpoint
    """
    all_results = validate_environment(include_warnings=include_warnings)

    # Separate errors and warnings
    errors = [r for r in all_results if r.severity == "error"]
    warnings = [r for r in all_results if r.severity == "warning"]

    required_vars = [name for name, rule in ENV_VAR_RULES.items() if rule.required]
    optional_vars = [name for name, rule in ENV_VAR_RULES.items() if not rule.required]

    # Check which vars are set vs missing
    set_required = [name for name in required_vars if os.environ.get(name)]
    missing_required = [name for name in required_vars if not os.environ.get(name)]
    set_optional = [name for name in optional_vars if os.environ.get(name)]
    using_defaults = [name for name in optional_vars if not os.environ.get(name)]

    return {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "required_vars": {
            "total": len(required_vars),
            "set": len(set_required),
            "missing": missing_required,
        },
        "optional_vars": {
            "total": len(optional_vars),
            "set": len(set_optional),
            "using_defaults": len(using_defaults),
        },
        "errors": [e.to_dict() for e in errors],
        "warnings": [w.to_dict() for w in warnings],
    }


def log_validation_results(logger=None) -> bool:
    """
    Log validation results at appropriate levels.

    Logs errors at ERROR level, warnings at WARNING level.
    Returns True if no errors (warnings are OK).

    Args:
        logger: Optional logger instance (uses print if None)

    Returns:
        True if no errors, False if there are errors
    """
    all_results = validate_environment(include_warnings=True)

    errors = [r for r in all_results if r.severity == "error"]
    warnings = [r for r in all_results if r.severity == "warning"]

    def _log(level: str, msg: str):
        if logger:
            getattr(logger, level.lower())(msg)
        else:
            print(f"[{level.upper()}] {msg}")

    # Log errors
    for error in errors:
        _log("error", f"ENV VAR ERROR: {error.var_name} - {error.message}")
        _log("error", f"  Expected: {error.expected_pattern}")
        _log("error", f"  Fix: {error.fix_suggestion}")

    # Log warnings (optional vars using defaults)
    if warnings:
        _log("warning", f"ENV VARS: {len(warnings)} optional variables using defaults:")
        for warning in warnings:
            default_val = warning.expected_pattern.replace("Default: ", "")
            _log("warning", f"  {warning.var_name} → {default_val}")

    # Summary
    if errors:
        _log("error", f"❌ STARTUP_FAILED: {len(errors)} environment variable errors")
        return False
    elif warnings:
        _log("info", f"✅ Environment validation passed ({len(warnings)} vars using defaults)")
        return True
    else:
        _log("info", f"✅ Environment validation passed (all vars explicitly set)")
        return True


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ENV_VAR_RULES",
    "EnvVarRule",
    "ValidationError",
    "validate_environment",
    "validate_single_var",
    "get_validation_summary",
    "log_validation_results",
]
