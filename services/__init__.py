# ============================================================================
# SERVICE HANDLER REGISTRY
# ============================================================================
# STATUS: Services - Explicit task handler registration (no decorators)
# PURPOSE: Central registry mapping task_type strings to handler functions
# LAST_REVIEWED: 14 JAN 2026
# ============================================================================
"""
Service Handler Registry - Explicit Registration (No Decorators!)

All task handlers are registered here explicitly. No decorators, no auto-discovery, no import magic.
If you don't see it in ALL_HANDLERS, it's not registered.

CRITICAL: We avoid decorator-based registration because:
1. Decorators only execute when module is imported
2. If service module never imported, decorators never run
3. This caused silent registration failures in previous implementations
4. Explicit registration is clear, visible, and predictable

Registration Process:
1. Create your handler functions in services/service_your_domain.py
2. Import them at the top of this file
3. Add entries to ALL_HANDLERS dict
4. Done! No decorators, no magic, just a simple dict

Handler Function Contract (ENFORCED BY CoreMachine):
    def handler(params: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        '''
        Args:
            params: Task parameters from job definition
            context: Optional context with predecessor results, job metadata

        Returns:
            Dict with REQUIRED 'success' field (bool):

            SUCCESS: {"success": True, "result": {...}}
            FAILURE: {"success": False, "error": "message", "error_type": "ValueError"}

        CONTRACT ENFORCEMENT:
            - Missing 'success' field -> ContractViolationError
            - Task marked COMPLETED if success=True, FAILED if success=False

        EXCEPTION HANDLING:
            - Handlers can raise exceptions instead of returning {"success": False, ...}
            - CoreMachine catches exceptions and auto-creates failure result
        '''
        return {"success": True, "result": {"foo": "bar"}}

Historical context archived in: docs/archive/INIT_PY_HISTORY.md
"""

from .service_hello_world import handle_greeting, handle_reply
from .stac_catalog import list_raster_files, extract_stac_metadata
from .raster_validation import validate_raster, validate_raster_header, validate_raster_data
from .raster_cog import create_cog
from .raster_mosaicjson import create_mosaicjson
from .stac_collection import create_stac_collection
from .tiling_scheme import generate_tiling_scheme
from .tiling_extraction import extract_tiles

# Unpublish handlers
from .unpublish_handlers import (
    inventory_raster_item,
    inventory_vector_item,
    delete_blob,
    drop_postgis_table,
    delete_stac_and_audit,
)

# Docker consolidated handler (F7.13)
from .handler_process_raster_complete import process_raster_complete

# Docker Vector ETL handler (V0.8 - single stage with checkpoints)
from .handler_vector_docker_complete import vector_docker_complete

# Docker Raster Collection handler (V0.8 - sequential checkpoint-based)
from .handler_raster_collection_complete import raster_collection_complete

# VirtualiZarr handlers (V0.9 - NetCDF virtual reference pipeline)
from .handler_virtualzarr import (
    virtualzarr_scan,
    virtualzarr_copy,
    virtualzarr_validate,
    virtualzarr_combine,
    virtualzarr_register,
)

# ============================================================================
# STAC METADATA HELPER
# ============================================================================
from .iso3_attribution import ISO3Attribution, ISO3AttributionService
from .stac_metadata_helper import (
    STACMetadataHelper,
    VisualizationMetadata
)

# ============================================================================
# PLATFORM VALIDATION (V0.8 Release Control - dry_run support)
# ============================================================================
from .platform_validation import validate_version_lineage, VersionValidationResult

# ============================================================================
# STAC MATERIALIZATION (26 FEB 2026 — B2C materialized view engine)
# ============================================================================
from .stac_materialization import STACMaterializer

# ============================================================================
# EXPLICIT HANDLER REGISTRY
# ============================================================================
# To add a new handler:
# 1. Create function in services/service_*.py
# 2. Import it above
# 3. Add entry to ALL_HANDLERS dict below
# ============================================================================

# ARCHIVED (13 FEB 2026): H3 (12), Fathom (11), legacy FunctionApp vector (4) handlers
# → docs/archive/v08_archive_feb2026/services/
# ARCHIVED (18 FEB 2026): V0.9 Docker migration — inventory (5), STAC rebuild (2), orphan blob (3)
# → docs/archive/v09_archive_feb2026/services/
ALL_HANDLERS = {
    # Hello World (test handlers)
    "hello_world_greeting": handle_greeting,
    "hello_world_reply": handle_reply,

    # Raster handlers (shared by Docker jobs)
    "raster_list_files": list_raster_files,
    "raster_extract_stac_metadata": extract_stac_metadata,
    "raster_validate": validate_raster,
    "raster_create_cog": create_cog,
    "raster_create_mosaicjson": create_mosaicjson,
    "raster_create_stac_collection": create_stac_collection,
    "raster_generate_tiling_scheme": generate_tiling_scheme,
    "raster_extract_tiles": extract_tiles,

    # Docker consolidated handlers (F7.13)
    "raster_process_complete": process_raster_complete,
    "raster_collection_complete": raster_collection_complete,

    # Vector handlers (Docker - single stage with checkpoints)
    "vector_docker_complete": vector_docker_complete,

    # Unpublish handlers
    "unpublish_inventory_raster": inventory_raster_item,
    "unpublish_inventory_vector": inventory_vector_item,
    "unpublish_delete_blob": delete_blob,
    "unpublish_drop_table": drop_postgis_table,
    "unpublish_delete_stac": delete_stac_and_audit,

    # VirtualiZarr handlers (NetCDF virtual reference pipeline)
    "virtualzarr_scan": virtualzarr_scan,
    "virtualzarr_copy": virtualzarr_copy,
    "virtualzarr_validate": virtualzarr_validate,
    "virtualzarr_combine": virtualzarr_combine,
    "virtualzarr_register": virtualzarr_register,

}

# ============================================================================
# VALIDATION
# ============================================================================

def validate_handler_registry():
    """
    Validate all handlers in registry on startup.
    Catches configuration errors immediately at import time.
    """
    for task_type, handler in ALL_HANDLERS.items():
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


# ============================================================================
# STARTUP VALIDATION - Fail Fast
# ============================================================================

def validate_task_routing_coverage():
    """
    Validate all handlers have queue routing configured.
    Runs at import time - fail fast if misconfigured.
    """
    from config.defaults import TaskRoutingDefaults

    all_tasks = set(ALL_HANDLERS.keys())
    # V0.9: All tasks route to Docker (19 FEB 2026)
    docker_set = set(TaskRoutingDefaults.DOCKER_TASKS)

    unmapped = all_tasks - docker_set

    if unmapped:
        raise ValueError(
            f"FATAL: {len(unmapped)} handler(s) have NO queue routing configured! "
            f"Tasks will fail at runtime. Add to config/defaults.py "
            f"TaskRoutingDefaults.DOCKER_TASKS: {sorted(unmapped)}"
        )


# Validate on import - fail fast if something's wrong.
validate_handler_registry()
validate_task_routing_coverage()

__all__ = [
    # Handler registry
    'ALL_HANDLERS',
    'get_handler',
    'validate_handler_registry',
    'validate_task_routing_coverage',
    # STAC Metadata Helper
    'STACMetadataHelper',
    'VisualizationMetadata',
    'ISO3Attribution',
    'ISO3AttributionService',
    # Platform validation (V0.8 Release Control)
    'validate_version_lineage',
    'VersionValidationResult',
    # STAC Materialization (26 FEB 2026)
    'STACMaterializer',
]
