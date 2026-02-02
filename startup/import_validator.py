# ============================================================================
# IMPORT VALIDATOR
# ============================================================================
# STATUS: Infrastructure - Critical import validation
# PURPOSE: Verify critical modules can be imported at startup
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 1 Startup Logic Extraction
# ============================================================================
"""
Import Validator Module.

Validates that critical Python modules can be imported at startup.
This catches missing dependencies or broken imports early with clear
error messages.

Critical Modules:
    - azure.functions: Azure Functions runtime
    - azure.identity: Azure authentication
    - pydantic: Data validation
    - config: Application configuration
    - core.machine: Job orchestration engine
    - infrastructure: Database and storage access

Usage:
    from startup.import_validator import validate_critical_imports

    result = validate_critical_imports()
    if not result.passed:
        print(f"Import failed: {result.error_message}")
"""

import logging
from typing import List, Tuple

from .state import ValidationResult

_logger = logging.getLogger("startup.import_validator")


# Critical modules that must be importable for the app to function
CRITICAL_IMPORTS: List[Tuple[str, str]] = [
    # (module_path, description)
    ("azure.functions", "Azure Functions runtime"),
    ("azure.identity", "Azure authentication"),
    ("pydantic", "Data validation library"),
    ("config", "Application configuration"),
    ("core.machine", "Job orchestration engine"),
    ("core.schema.queue", "Queue message schemas"),
    ("infrastructure", "Database and storage access"),
    ("services", "Business logic services"),
    ("jobs", "Job definitions"),
    ("util_logger", "Logging utilities"),
]


def validate_critical_imports() -> ValidationResult:
    """
    Validate that critical modules can be imported.

    Attempts to import each critical module and collects any failures.
    Returns a ValidationResult indicating overall success/failure.

    Returns:
        ValidationResult with import validation status
    """
    failed_imports = []
    successful_imports = []

    for module_path, description in CRITICAL_IMPORTS:
        try:
            __import__(module_path)
            successful_imports.append(module_path)
            _logger.debug(f"Import OK: {module_path}")

        except ImportError as e:
            error_info = {
                "module": module_path,
                "description": description,
                "error": str(e),
            }
            failed_imports.append(error_info)
            _logger.error(f"Import FAILED: {module_path} - {e}")

        except Exception as e:
            # Catch other errors (syntax, missing dependencies, etc.)
            error_info = {
                "module": module_path,
                "description": description,
                "error": f"{type(e).__name__}: {e}",
            }
            failed_imports.append(error_info)
            _logger.error(f"Import EXCEPTION: {module_path} - {type(e).__name__}: {e}")

    if failed_imports:
        failed_names = [f["module"] for f in failed_imports]
        return ValidationResult(
            name="imports",
            passed=False,
            error_type="IMPORT_FAILED",
            error_message=f"Failed to import: {', '.join(failed_names)}",
            details={
                "failed_count": len(failed_imports),
                "failed_imports": failed_imports,
                "successful_count": len(successful_imports),
                "successful_imports": successful_imports,
            }
        )

    _logger.info(f"All {len(successful_imports)} critical imports validated")
    return ValidationResult(
        name="imports",
        passed=True,
        details={
            "message": "All critical modules imported successfully",
            "import_count": len(successful_imports),
        }
    )


def validate_single_import(module_path: str) -> Tuple[bool, str]:
    """
    Validate a single module import.

    Args:
        module_path: Dotted module path (e.g., "azure.functions")

    Returns:
        Tuple of (success, error_message)
    """
    try:
        __import__(module_path)
        return True, ""
    except ImportError as e:
        return False, f"ImportError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'validate_critical_imports',
    'validate_single_import',
    'CRITICAL_IMPORTS',
]
