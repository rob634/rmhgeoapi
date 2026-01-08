# ============================================================================
# ENVIRONMENT VARIABLE VALIDATION
# ============================================================================
# STATUS: Configuration - Startup validation with regex patterns
# PURPOSE: Validate env vars at startup to fail fast with clear error messages
# LAST_REVIEWED: 08 JAN 2026
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
    """
    pattern: Pattern
    pattern_description: str
    required: bool
    fix_suggestion: str
    example: str
    allow_empty: bool = False


# ============================================================================
# VALIDATION RULES - Single source of truth for env var formats
# ============================================================================

# Common regex patterns (reusable)
_AZURE_STORAGE_ACCOUNT = re.compile(r"^[a-z0-9]{3,24}$")
_AZURE_HOST_FQDN = re.compile(r"^[a-z0-9][a-z0-9-]*\.(postgres\.database\.azure\.com|database\.windows\.net)$", re.IGNORECASE)
_SERVICE_BUS_FQDN = re.compile(r"^[a-z0-9][a-z0-9-]*\.servicebus\.windows\.net$", re.IGNORECASE)
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
        pattern_description="Must be full FQDN ending in .servicebus.windows.net",
        required=True,
        fix_suggestion="Use full URL like 'myservicebus.servicebus.windows.net' (not just 'myservicebus')",
        example="myservicebus.servicebus.windows.net",
    ),

    # Legacy name - still validate if present
    "SERVICE_BUS_NAMESPACE": EnvVarRule(
        pattern=_SERVICE_BUS_FQDN,
        pattern_description="Must be full FQDN ending in .servicebus.windows.net (DEPRECATED - use SERVICE_BUS_FQDN)",
        required=False,
        fix_suggestion="Rename to SERVICE_BUS_FQDN. Use full URL like 'myservicebus.servicebus.windows.net'",
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

    "OGC_STAC_APP_URL": EnvVarRule(
        pattern=_HTTPS_URL,
        pattern_description="HTTPS URL (must start with https://)",
        required=False,
        fix_suggestion="Use full HTTPS URL like 'https://myogcstac.azurewebsites.net'",
        example="https://myogcstac.azurewebsites.net",
    ),

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
}


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_single_var(var_name: str, rule: EnvVarRule) -> Optional[ValidationError]:
    """
    Validate a single environment variable against its rule.

    Args:
        var_name: Environment variable name
        rule: Validation rule to apply

    Returns:
        ValidationError if validation fails, None if passes
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

    # If not required and not set, skip pattern validation
    if value is None or value == "":
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


def validate_environment(rules: Optional[Dict[str, EnvVarRule]] = None) -> List[ValidationError]:
    """
    Validate all environment variables against their rules.

    Args:
        rules: Optional custom rules dict (defaults to ENV_VAR_RULES)

    Returns:
        List of ValidationError objects (empty if all valid)
    """
    if rules is None:
        rules = ENV_VAR_RULES

    errors = []
    for var_name, rule in rules.items():
        error = validate_single_var(var_name, rule)
        if error:
            errors.append(error)

    return errors


def get_validation_summary() -> Dict[str, Any]:
    """
    Get a summary of environment variable validation status.

    Returns:
        Dict with validation summary suitable for health endpoint
    """
    errors = validate_environment()

    required_vars = [name for name, rule in ENV_VAR_RULES.items() if rule.required]
    optional_vars = [name for name, rule in ENV_VAR_RULES.items() if not rule.required]

    # Check which vars are set vs missing
    set_vars = [name for name in required_vars if os.environ.get(name)]
    missing_vars = [name for name in required_vars if not os.environ.get(name)]

    return {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "required_vars": {
            "total": len(required_vars),
            "set": len(set_vars),
            "missing": missing_vars,
        },
        "errors": [e.to_dict() for e in errors],
    }


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
]
