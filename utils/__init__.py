# ============================================================================
# UTILITIES PACKAGE
# ============================================================================
# STATUS: Utility - Cross-cutting validation and contract enforcement
# PURPOSE: Export ImportValidator for startup checks and enforce_contract decorator
# LAST_REVIEWED: 04 JAN 2026
# REVIEW_STATUS: Checks 1-7 Applied (Check 8 N/A - no infrastructure config)
# ============================================================================
"""
Utilities Package.

Cross-cutting utilities used throughout the application.

Exports:
    ImportValidator: Module import validation
    validator: Singleton ImportValidator instance
    enforce_contract: Contract validation decorator
"""

# Make imports available at package level for convenience
from .import_validator import ImportValidator, validator
from .contract_validator import enforce_contract

__all__ = [
    'ImportValidator',
    'enforce_contract',
    'validator',
]