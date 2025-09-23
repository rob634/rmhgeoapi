# ============================================================================
# CLAUDE CONTEXT - UTILS PACKAGE INITIALIZATION
# ============================================================================
# PURPOSE: Initialize the utils package for Azure Functions compatibility
# EXPORTS: Import validator and logger utilities
# INTERFACES: None
# PYDANTIC_MODELS: None
# DEPENDENCIES: None
# SOURCE: Package initialization
# SCOPE: Package-level
# VALIDATION: None
# PATTERNS: Package initialization
# ENTRY_POINTS: from utils import *
# INDEX: N/A
# ============================================================================

"""
Utilities package for rmhgeoapi Azure Functions.

This package contains utility modules that are used across the application:
- import_validator: Validates module imports and dependencies
- logger: Centralized logging functionality (future)
"""

# Make imports available at package level for convenience
from .import_validator import ImportValidator, validator
from .contract_validator import enforce_contract

__all__ = [
    'ImportValidator',
    'enforce_contract',
    'validator',
]