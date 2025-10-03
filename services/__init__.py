"""
Service Handler Registry - Explicit Registration (No Decorators!)

All task handlers are registered here explicitly. No decorators, no auto-discovery, no import magic.
If you don't see it in ALL_HANDLERS, it's not registered.

CRITICAL: We avoid decorator-based registration because:
1. Decorators only execute when module is imported
2. If service module never imported, decorators never run
3. This caused silent registration failures in previous implementation (10 SEP 2025)
4. Explicit registration is clear, visible, and predictable

Registration Process:
1. Create your handler functions in services/service_your_domain.py
2. Import them at the top of this file: `from .service_your_domain import handle_foo, handle_bar`
3. Add entries to ALL_HANDLERS dict: `"task_type": handler_function`
4. Done! No decorators, no magic, just a simple dict

Example:
    # In services/service_raster.py:
    def handle_tile_processing(params: dict, context: dict = None) -> dict:
        return {"success": True, "tile_id": params["tile_id"]}
    
    # In services/__init__.py (this file):
    from .service_raster import handle_tile_processing
    
    ALL_HANDLERS = {
        "hello_world_greeting": handle_greeting,
        "process_tile": handle_tile_processing,  # <- Added here!
    }

Handler Function Signature:
    def handler(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        '''
        Args:
            params: Task parameters from job definition
            context: Optional context with predecessor results, job metadata, etc.
        
        Returns:
            Result dict with task output data
        '''
        return {"success": True, "result": "..."}

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from .service_hello_world import handle_greeting, handle_reply

# ============================================================================
# EXPLICIT HANDLER REGISTRY
# ============================================================================
# To add a new handler:
# 1. Create function in services/service_*.py
# 2. Import it above
# 3. Add entry to ALL_HANDLERS dict below
# ============================================================================

ALL_HANDLERS = {
    "hello_world_greeting": handle_greeting,
    "hello_world_reply": handle_reply,
    # Add new handlers here explicitly
    # "process_tile": handle_tile_processing,
    # "validate_geotiff": handle_geotiff_validation,
    # "extract_metadata": handle_metadata_extraction,
}

# ============================================================================
# VALIDATION
# ============================================================================

def validate_handler_registry():
    """
    Validate all handlers in registry on startup.

    This catches configuration errors immediately at import time,
    not when a task tries to execute.
    """
    for task_type, handler in ALL_HANDLERS.items():
        # Verify handler is callable
        if not callable(handler):
            raise ValueError(
                f"Handler for '{task_type}' is not callable. "
                f"Got {type(handler).__name__} instead of function."
            )

    return True


def get_handler(task_type: str):
    """
    Get handler function by task type.

    Args:
        task_type: Task type string (e.g., "hello_world_greeting")

    Returns:
        Handler function

    Raises:
        ValueError: If task_type not in registry
    """
    if task_type not in ALL_HANDLERS:
        available = list(ALL_HANDLERS.keys())
        raise ValueError(
            f"Unknown task type: '{task_type}'. "
            f"Available handlers: {available}"
        )

    return ALL_HANDLERS[task_type]


# Validate on import - fail fast if something's wrong!
validate_handler_registry()

__all__ = [
    'ALL_HANDLERS',
    'get_handler',
    'validate_handler_registry',
]
