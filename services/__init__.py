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
from .container_summary import analyze_container_summary
from .stac_catalog import list_raster_files, extract_stac_metadata
from .stac_vector_catalog import extract_vector_stac_metadata, create_vector_stac
from .raster_validation import validate_raster
from .raster_cog import create_cog
from .handler_create_h3_stac import create_h3_stac
from .handler_h3_native_streaming import h3_native_streaming_postgis
from .handler_generate_h3_grid import generate_h3_grid
from .handler_cascade_h3_descendants import cascade_h3_descendants
from .handler_finalize_h3_pyramid import finalize_h3_pyramid
from .vector.process_vector_tasks import process_vector_prepare, process_vector_upload
from .raster_mosaicjson import create_mosaicjson
from .stac_collection import create_stac_collection
from .tiling_scheme import generate_tiling_scheme
from .tiling_extraction import extract_tiles
from .fathom_etl import (
    fathom_tile_inventory,
    fathom_band_stack,
    fathom_grid_inventory,
    fathom_spatial_merge,
    fathom_stac_register,
    fathom_stac_rebuild,
)
from .geospatial_inventory import (
    classify_geospatial_file,
    aggregate_geospatial_inventory,
)
from .container_inventory import (
    list_blobs_with_metadata,
    analyze_blob_basic,
    aggregate_blob_analysis as aggregate_blob_analysis_v2,
)
from .fathom_container_inventory import (
    fathom_generate_scan_prefixes,
    fathom_scan_prefix,
    fathom_assign_grid_cells,
    fathom_inventory_summary,
)

# Unpublish handlers
from .unpublish_handlers import (
    inventory_raster_item,
    inventory_vector_item,
    delete_blob,
    drop_postgis_table,
    delete_stac_and_audit,
)

# Curated dataset update handlers
from jobs.curated_update import (
    curated_check_source,
    curated_fetch_data,
    curated_etl_process,
    curated_finalize,
)

# H3 Aggregation handlers
from .h3_aggregation import (
    h3_inventory_cells,
    h3_raster_zonal_stats,
    h3_aggregation_finalize,
    h3_export_validate,
    h3_export_build,
    h3_export_register,
)

# STAC Repair handlers
from .stac_repair_handlers import (
    stac_repair_inventory,
    stac_repair_item,
)

# STAC Rebuild handlers (F7.11 Self-Healing)
from .rebuild_stac_handlers import (
    stac_rebuild_validate,
    stac_rebuild_item,
)

# Orphan Blob handlers (F7.11 STAC Self-Healing)
from .orphan_blob_handlers import (
    orphan_blob_inventory,
    silver_blob_validate,
    silver_blob_register,
)

# Docker consolidated handlers (F7.13, F7.18)
from .handler_process_raster_complete import process_raster_complete
from .handler_process_large_raster_complete import process_large_raster_complete
from .handler_h3_pyramid_complete import h3_pyramid_complete

# Ingest Collection handlers
from .ingest import ALL_HANDLERS as INGEST_HANDLERS

# Validate no handler name collisions before merge
def _validate_no_handler_collisions(base_keys: set, merge_dict: dict, merge_name: str):
    """Fail fast if handler registries have overlapping keys."""
    collisions = base_keys & set(merge_dict.keys())
    if collisions:
        raise ValueError(
            f"FATAL: Handler name collision when merging {merge_name}: {collisions}. "
            f"Each handler must have a unique name across all registries."
        )

# ============================================================================
# STAC METADATA HELPER
# ============================================================================
from .iso3_attribution import ISO3Attribution, ISO3AttributionService
from .stac_metadata_helper import (
    STACMetadataHelper,
    PlatformMetadata,
    AppMetadata,
    VisualizationMetadata
)

# ============================================================================
# EXPLICIT HANDLER REGISTRY
# ============================================================================
# To add a new handler:
# 1. Create function in services/service_*.py
# 2. Import it above
# 3. Add entry to ALL_HANDLERS dict below
# ============================================================================

ALL_HANDLERS = {
    # Hello World (test handlers)
    "hello_world_greeting": handle_greeting,
    "hello_world_reply": handle_reply,

    # Container inventory
    "inventory_container_summary": analyze_container_summary,
    "inventory_list_blobs": list_blobs_with_metadata,
    "inventory_analyze_blob": analyze_blob_basic,
    "inventory_aggregate_analysis": aggregate_blob_analysis_v2,
    "inventory_classify_geospatial": classify_geospatial_file,
    "inventory_aggregate_geospatial": aggregate_geospatial_inventory,

    # Raster handlers
    "raster_list_files": list_raster_files,
    "raster_extract_stac_metadata": extract_stac_metadata,
    "raster_validate": validate_raster,
    "raster_create_cog": create_cog,
    "raster_create_mosaicjson": create_mosaicjson,
    "raster_create_stac_collection": create_stac_collection,
    "raster_generate_tiling_scheme": generate_tiling_scheme,
    "raster_extract_tiles": extract_tiles,

    # Docker consolidated handlers (F7.13, F7.18)
    "raster_process_complete": process_raster_complete,
    "raster_process_large_complete": process_large_raster_complete,

    # Vector handlers
    "vector_extract_stac_metadata": extract_vector_stac_metadata,
    "vector_create_stac": create_vector_stac,
    "process_vector_prepare": process_vector_prepare,
    "process_vector_upload": process_vector_upload,

    # H3 handlers (Function App)
    "h3_create_stac": create_h3_stac,
    "h3_native_streaming_postgis": h3_native_streaming_postgis,
    "h3_generate_grid": generate_h3_grid,
    "h3_cascade_descendants": cascade_h3_descendants,
    "h3_finalize_pyramid": finalize_h3_pyramid,
    "h3_inventory_cells": h3_inventory_cells,
    "h3_raster_zonal_stats": h3_raster_zonal_stats,
    "h3_aggregation_finalize": h3_aggregation_finalize,
    "h3_export_validate": h3_export_validate,
    "h3_export_build": h3_export_build,
    "h3_export_register": h3_export_register,

    # H3 handlers (Docker - single stage)
    "h3_pyramid_complete": h3_pyramid_complete,

    # Fathom ETL handlers
    "fathom_tile_inventory": fathom_tile_inventory,
    "fathom_band_stack": fathom_band_stack,
    "fathom_grid_inventory": fathom_grid_inventory,
    "fathom_spatial_merge": fathom_spatial_merge,
    "fathom_stac_register": fathom_stac_register,
    "fathom_stac_rebuild": fathom_stac_rebuild,
    "fathom_generate_scan_prefixes": fathom_generate_scan_prefixes,
    "fathom_scan_prefix": fathom_scan_prefix,
    "fathom_assign_grid_cells": fathom_assign_grid_cells,
    "fathom_inventory_summary": fathom_inventory_summary,

    # Unpublish handlers
    "unpublish_inventory_raster": inventory_raster_item,
    "unpublish_inventory_vector": inventory_vector_item,
    "unpublish_delete_blob": delete_blob,
    "unpublish_drop_table": drop_postgis_table,
    "unpublish_delete_stac": delete_stac_and_audit,

    # Curated dataset handlers
    "curated_check_source": curated_check_source,
    "curated_fetch_data": curated_fetch_data,
    "curated_etl_process": curated_etl_process,
    "curated_finalize": curated_finalize,

    # STAC Repair handlers
    "stac_repair_inventory": stac_repair_inventory,
    "stac_repair_item": stac_repair_item,

    # STAC Rebuild handlers (F7.11)
    "stac_rebuild_validate": stac_rebuild_validate,
    "stac_rebuild_item": stac_rebuild_item,

    # Orphan Blob handlers (F7.11 STAC Self-Healing)
    "orphan_blob_inventory": orphan_blob_inventory,
    "silver_blob_validate": silver_blob_validate,
    "silver_blob_register": silver_blob_register,
}

# Validate no collisions before merging INGEST_HANDLERS
_validate_no_handler_collisions(set(ALL_HANDLERS.keys()), INGEST_HANDLERS, "INGEST_HANDLERS")

# Merge Ingest Collection handlers
ALL_HANDLERS.update(INGEST_HANDLERS)

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
    raster_set = set(TaskRoutingDefaults.RASTER_TASKS)
    vector_set = set(TaskRoutingDefaults.VECTOR_TASKS)
    long_running_set = set(TaskRoutingDefaults.LONG_RUNNING_TASKS)

    unmapped = all_tasks - raster_set - vector_set - long_running_set

    if unmapped:
        raise ValueError(
            f"FATAL: {len(unmapped)} handler(s) have NO queue routing configured! "
            f"Tasks will fail at runtime. Add to config/defaults.py "
            f"TaskRoutingDefaults.RASTER_TASKS, VECTOR_TASKS, or LONG_RUNNING_TASKS: {sorted(unmapped)}"
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
    'PlatformMetadata',
    'AppMetadata',
    'VisualizationMetadata',
    'ISO3Attribution',
    'ISO3AttributionService',
]
