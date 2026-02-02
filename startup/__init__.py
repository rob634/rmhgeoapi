# ============================================================================
# STARTUP MODULE
# ============================================================================
# STATUS: Infrastructure - Startup validation orchestration
# PURPOSE: Centralized startup validation before trigger registration
# CREATED: 23 JAN 2026
# EPIC: APP_CLEANUP - Phase 1 Startup Logic Extraction
# ============================================================================
"""
Startup Validation Module.

Provides comprehensive validation before registering Service Bus triggers:
1. Import validation - critical modules can be imported
2. Environment validation - required vars present with correct format
3. Service Bus DNS - namespace resolves
4. Service Bus queues - required queues exist

This module has minimal dependencies to ensure it loads reliably.
Heavy imports (like config, infrastructure) are done lazily.

Usage:
    from startup import run_startup_validation, STARTUP_STATE

    # Run all validations (populates STARTUP_STATE)
    run_startup_validation()

    # Check results
    if STARTUP_STATE.all_passed:
        # Register Service Bus triggers
        pass
    else:
        # App runs in degraded mode (health endpoints only)
        pass

Design Philosophy:
    - SOFT VALIDATION: Store results, don't crash
    - LAYERED CHECKS: DNS before queues, env before imports
    - DIAGNOSTIC FRIENDLY: Results exposed via /api/readyz

Exports:
    run_startup_validation: Main entry point for all validations
    STARTUP_STATE: Global singleton with validation results
    ValidationResult: Dataclass for individual check results
"""

# Re-export from state module
from .state import STARTUP_STATE, ValidationResult, StartupState, ConfigWarning

# Import orchestrator
from .orchestrator import run_startup_validation

__all__ = [
    'run_startup_validation',
    'STARTUP_STATE',
    'ValidationResult',
    'StartupState',
    'ConfigWarning',
]
