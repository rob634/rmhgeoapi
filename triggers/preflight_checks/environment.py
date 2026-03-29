# ============================================================================
# CLAUDE CONTEXT - PREFLIGHT CHECK: ENVIRONMENT VARIABLES
# ============================================================================
# EPOCH: 5 - ACTIVE
# STATUS: Preflight check - environment variable validation
# PURPOSE: Wrap config.env_validation to surface missing/invalid env vars
#          with remediation text as preflight entries
# LAST_REVIEWED: 29 MAR 2026
# EXPORTS: EnvironmentCheck
# DEPENDENCIES: config.env_validation, config.app_mode_config
# ============================================================================
"""
Preflight check: environment variable validation.

Wraps the existing config.env_validation module to surface missing/invalid
env vars with remediation text. This runs the same regex validation as
startup but formats results as preflight entries.
"""

import logging
from typing import Any, Dict

from config.app_mode_config import AppMode
from .base import PreflightCheck, PreflightResult, Remediation

logger = logging.getLogger(__name__)

_ALL_MODES = {AppMode.STANDALONE, AppMode.PLATFORM, AppMode.ORCHESTRATOR, AppMode.WORKER_DOCKER}


class EnvironmentCheck(PreflightCheck):
    name = "environment_vars"
    description = "Validate required environment variables exist and match expected format"
    required_modes = _ALL_MODES

    def run(self, config, app_mode: AppMode) -> PreflightResult:
        from config.env_validation import validate_environment

        errors = validate_environment(include_warnings=False)

        if not errors:
            return PreflightResult.passed("All required environment variables present and valid")

        error_details = {}
        for err in errors:
            error_details[err.var_name] = {
                "message": err.message,
                "current_value": err.current_value or "(not set)",
                "expected_pattern": err.expected_pattern,
                "fix": err.fix_suggestion,
            }

        missing_names = [e.var_name for e in errors]
        return PreflightResult.failed(
            f"{len(errors)} environment variable(s) invalid: {', '.join(missing_names)}",
            remediation=Remediation(
                action=f"Set or fix environment variables: {', '.join(missing_names)}",
                eservice_summary=f"APP CONFIG: Set {len(errors)} missing/invalid env var(s) on app: {', '.join(missing_names)}",
            ),
            sub_checks=error_details,
        )
