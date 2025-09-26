# ============================================================================
# CLAUDE CONTEXT - MODULE
# ============================================================================
# PURPOSE: Services module initialization - exports all service handler factories
# EXPORTS: create_blob_handler, create_greeting_handler, create_reply_handler, create_stac_setup_handler
# INTERFACES: None - exports handler factory functions for task execution
# PYDANTIC_MODELS: None - individual services use dict-based parameters
# DEPENDENCIES: Individual service modules in this folder
# SOURCE: Handler factories from service_*.py files
# SCOPE: Task-level business logic for all services
# VALIDATION: Each service validates its own parameters
# PATTERNS: Handler factory pattern, Explicit Registration (via function_app.py)
# ENTRY_POINTS: Imported by function_app.py for task catalog registration
# INDEX: Imports:20, Exports:30
# ============================================================================

"""
Services Module

Exports all service handler factories for task execution.
These are registered explicitly in function_app.py via TaskCatalog.
"""

# Import handler factories from service modules
from .service_blob import (
    create_orchestration_handler,
    create_metadata_handler,
    create_summary_handler,
    create_index_handler
)
from .service_hello_world import create_greeting_handler, create_reply_handler
from .service_stac_setup import create_install_pgstac_handler

# Export all handler factories
__all__ = [
    'create_orchestration_handler',
    'create_metadata_handler',
    'create_summary_handler',
    'create_index_handler',
    'create_greeting_handler',
    'create_reply_handler',
    'create_install_pgstac_handler'
]