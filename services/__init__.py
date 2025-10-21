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

Handler Function Contract (ENFORCED BY CoreMachine):
    def handler(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        '''
        Task handler function signature and return contract.

        Args:
            params: Task parameters from job definition (dict)
            context: Optional context with predecessor results, job metadata, etc. (dict or None)

        Returns:
            Dict with REQUIRED 'success' field (bool) and additional data:

            SUCCESS FORMAT:
                {
                    "success": True,        # REQUIRED - Must be boolean True
                    "result": {...}         # Optional - Your task results
                }

            FAILURE FORMAT:
                {
                    "success": False,       # REQUIRED - Must be boolean False
                    "error": "error message",  # REQUIRED - Describe what went wrong
                    "error_type": "ValueError" # Optional - Exception type name
                }

        CONTRACT ENFORCEMENT:
            - Missing 'success' field → ContractViolationError (crashes function)
            - Non-boolean 'success' → ContractViolationError (crashes function)
            - Task marked COMPLETED if success=True, FAILED if success=False

        EXCEPTION HANDLING:
            - Handlers can raise exceptions instead of returning {"success": False, ...}
            - CoreMachine catches exceptions and auto-creates failure result
            - Prefer raising exceptions for unexpected errors (simpler code)
            - Use {"success": False, ...} for expected business logic failures
        '''
        # Your handler logic here
        return {"success": True, "result": {"foo": "bar"}}

Author: Robert and Geospatial Claude Legion
Date: 1 OCT 2025
"""

from .service_hello_world import handle_greeting, handle_reply
from .container_summary import analyze_container_summary
from .container_list import list_container_blobs, analyze_single_blob, aggregate_blob_analysis
from .stac_catalog import list_raster_files, extract_stac_metadata
from .stac_vector_catalog import extract_vector_stac_metadata, create_vector_stac
from .test_minimal import test_minimal_handler
from .raster_validation import validate_raster
from .raster_cog import create_cog
from .handler_h3_level4 import h3_level4_generate
from .handler_h3_base import h3_base_generate
from .vector.tasks import prepare_vector_chunks, upload_pickled_chunk
from .raster_mosaicjson import create_mosaicjson
from .stac_collection import create_stac_collection

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
    "container_summary_task": analyze_container_summary,
    "list_container_blobs": list_container_blobs,
    "analyze_single_blob": analyze_single_blob,
    "aggregate_blob_analysis": aggregate_blob_analysis,  # Fan-in aggregation handler (16 OCT 2025)
    "list_raster_files": list_raster_files,
    "extract_stac_metadata": extract_stac_metadata,
    "extract_vector_stac_metadata": extract_vector_stac_metadata,
    "test_minimal": test_minimal_handler,
    "validate_raster": validate_raster,
    "create_cog": create_cog,
    "h3_level4_generate": h3_level4_generate,
    "h3_base_generate": h3_base_generate,
    # Vector ETL handlers (17 OCT 2025)
    "prepare_vector_chunks": prepare_vector_chunks,  # Stage 1: Load, validate, chunk, pickle
    "upload_pickled_chunk": upload_pickled_chunk,    # Stage 2: Load pickle and upload to PostGIS
    "create_vector_stac": create_vector_stac,        # Stage 3: Create STAC record (18 OCT 2025 - Priority 0A)
    # Raster collection handlers (20 OCT 2025)
    "create_mosaicjson": create_mosaicjson,          # Stage 3: Create MosaicJSON from COG collection
    "create_stac_collection": create_stac_collection,  # Stage 4: Create STAC collection item
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
