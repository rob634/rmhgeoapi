# ============================================================================
# CLAUDE CONTEXT - CORE PACKAGE INITIALIZATION
# ============================================================================
# CATEGORY: STATE MANAGEMENT & ORCHESTRATION
# PURPOSE: Core architectural component for job/task lifecycle management
# EPOCH: Shared by all epochs (may evolve with architecture changes)# PURPOSE: Initialize core orchestration components package
# EXPORTS: CoreController, StateManager, OrchestrationManager, models, logic, schema
# AZURE FUNCTIONS: CRITICAL - This __init__.py is REQUIRED for folder imports
# ============================================================================

"""
Core orchestration components for the geospatial ETL pipeline.

This package contains the fundamental building blocks for job orchestration,
separated from job-specific business logic.

Structure:
- models/: Pure data structures (no business logic)
- logic/: Business logic separated from models
- schema/: Database schema management
- Core orchestration classes
"""

# Make subpackages available first (no circular dependencies)
from . import models
from . import logic
from . import schema

# Lazy imports to avoid circular dependencies
# These are imported on first access via __getattr__
_LAZY_IMPORTS = {
    'CoreController': '.core_controller',
    'StateManager': '.state_manager',
    'OrchestrationManager': '.orchestration_manager',
    'CoreMachine': '.machine'
}

def __getattr__(name):
    """Lazy import core classes to avoid circular dependencies."""
    if name in _LAZY_IMPORTS:
        from importlib import import_module
        module = import_module(_LAZY_IMPORTS[name], package='core')
        return getattr(module, name)
    raise AttributeError(f"module 'core' has no attribute '{name}'")

__all__ = [
    'CoreController',
    'StateManager',
    'OrchestrationManager',
    'CoreMachine',
    'models',
    'logic',
    'schema'
]