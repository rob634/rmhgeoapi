"""
Core Orchestration Components.

Contains fundamental building blocks for job orchestration,
separated from job-specific business logic.

Structure:
    models/: Pure data structures (no business logic)
    logic/: Business logic separated from models
    schema/: Database schema management
    Core orchestration classes

Exports:
    CoreController: Base controller abstraction
    StateManager: Job/Task state management
    OrchestrationManager: Orchestration coordination
    CoreMachine: Core processing machine
    CoreMachineErrorHandler: Centralized error handling
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
    'CoreMachine': '.machine',
    'CoreMachineErrorHandler': '.error_handler'
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
    'CoreMachineErrorHandler',
    'models',
    'logic',
    'schema'
]