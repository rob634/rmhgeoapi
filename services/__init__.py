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

from .service_hello_world import handle_greeting, handle_reply, handle_generate_list
from .stac_catalog import list_raster_files, extract_stac_metadata
from .raster_validation import validate_raster, validate_raster_header, validate_raster_data
from .raster_cog import create_cog
from .stac_collection import create_stac_collection
from .tiling_scheme import generate_tiling_scheme
from .tiling_extraction import extract_tiles

# Unpublish handlers
from .unpublish_handlers import (
    inventory_raster_item,
    inventory_vector_item,
    inventory_vector_multi_source,
    inventory_zarr_item,
    delete_blob,
    drop_postgis_table,
    delete_stac_and_audit,
)

# Docker consolidated handler (F7.13)
from .handler_process_raster_complete import process_raster_complete

# Docker Vector ETL handler (V0.8 - single stage with checkpoints)
from .handler_vector_docker_complete import vector_docker_complete

# Multi-source vector collection handler (V0.9 - N files or N layers -> N tables)
from .handler_vector_multi_source import vector_multi_source_complete

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

# IngestZarr handlers (native Zarr store pipeline)
from .handler_ingest_zarr import (
    ingest_zarr_validate,
    ingest_zarr_copy,
    ingest_zarr_register,
    ingest_zarr_rechunk,
)

# NetCDF-to-Zarr handlers (real conversion pipeline, replaces virtualzarr)
from .handler_netcdf_to_zarr import (
    netcdf_scan,
    netcdf_copy,
    netcdf_validate,
    netcdf_convert,
    netcdf_convert_and_pyramid,
    netcdf_register,
)

# V0.10.5 Raster atomic handlers (DAG node decomposition)
from .raster.handler_download_source import raster_download_source
from .raster.handler_validate import raster_validate as raster_validate_atomic
from .raster.handler_create_cog import raster_create_cog as raster_create_cog_atomic
from .raster.handler_upload_cog import raster_upload_cog
from .raster.handler_persist_app_tables import raster_persist_app_tables
from .raster.handler_generate_tiling_scheme import raster_generate_tiling_scheme_atomic
from .raster.handler_process_single_tile import raster_process_single_tile
from .raster.handler_persist_tiled import raster_persist_tiled
from .raster.handler_finalize import raster_finalize

# V0.10.6 Composable STAC handlers
from .stac.handler_materialize_item import stac_materialize_item
from .stac.handler_materialize_collection import stac_materialize_collection

# V0.10.6 Zarr DAG handlers
from .zarr.handler_batch_blobs import zarr_batch_blobs
from .zarr.handler_register import zarr_register_metadata
from .zarr.handler_validate_source import zarr_validate_source
from .zarr.handler_generate_pyramid import zarr_generate_pyramid
from .zarr.handler_download_to_mount import zarr_download_to_mount

# V0.10.5 Vector atomic handlers (DAG node decomposition)
from .vector.handler_refresh_tipg import vector_refresh_tipg
from .vector.handler_create_split_views import vector_create_split_views
from .vector.handler_register_catalog import vector_register_catalog
from .vector.handler_load_source import vector_load_source
from .vector.handler_validate_and_clean import vector_validate_and_clean
from .vector.handler_create_and_load_tables import vector_create_and_load_tables
from .vector.handler_finalize import vector_finalize

# ACLED sync handlers (API-driven scheduled workflow)
from .handler_acled_fetch_and_diff import acled_fetch_and_diff
from .handler_acled_save_to_bronze import acled_save_to_bronze
from .handler_acled_append_to_silver import acled_append_to_silver

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
    "hello_world_generate_list": handle_generate_list,

    # Raster atomic handlers (v0.10.5 DAG decomposition)
    "raster_download_source": raster_download_source,
    "raster_validate_atomic": raster_validate_atomic,
    "raster_create_cog_atomic": raster_create_cog_atomic,
    "raster_upload_cog": raster_upload_cog,
    "raster_persist_app_tables": raster_persist_app_tables,
    "raster_generate_tiling_scheme_atomic": raster_generate_tiling_scheme_atomic,
    "raster_process_single_tile": raster_process_single_tile,
    "raster_persist_tiled": raster_persist_tiled,
    "raster_finalize": raster_finalize,

    # Composable STAC handlers (v0.10.6)
    "stac_materialize_item": stac_materialize_item,
    "stac_materialize_collection": stac_materialize_collection,

    # Zarr DAG handlers (v0.10.6)
    "zarr_batch_blobs": zarr_batch_blobs,
    "zarr_register_metadata": zarr_register_metadata,
    "zarr_validate_source": zarr_validate_source,
    "zarr_generate_pyramid": zarr_generate_pyramid,
    "zarr_download_to_mount": zarr_download_to_mount,

    # Raster handlers (Epoch 4 — shared by Docker jobs)
    "raster_list_files": list_raster_files,
    "raster_extract_stac_metadata": extract_stac_metadata,
    "raster_validate": validate_raster,
    "raster_create_cog": create_cog,
    "raster_create_stac_collection": create_stac_collection,
    "raster_generate_tiling_scheme": generate_tiling_scheme,
    "raster_extract_tiles": extract_tiles,

    # Docker consolidated handlers (F7.13)
    "raster_process_complete": process_raster_complete,
    "raster_collection_complete": raster_collection_complete,

    # Vector handlers (Docker - single stage with checkpoints)
    "vector_docker_complete": vector_docker_complete,
    "vector_multi_source_complete": vector_multi_source_complete,

    # Vector atomic handlers (v0.10.5 DAG decomposition)
    "vector_refresh_tipg": vector_refresh_tipg,
    "vector_create_split_views": vector_create_split_views,
    "vector_register_catalog": vector_register_catalog,
    "vector_load_source": vector_load_source,
    "vector_validate_and_clean": vector_validate_and_clean,
    "vector_create_and_load_tables": vector_create_and_load_tables,
    "vector_finalize": vector_finalize,

    # Unpublish handlers
    "unpublish_inventory_raster": inventory_raster_item,
    "unpublish_inventory_vector": inventory_vector_item,
    "unpublish_inventory_vector_multi": inventory_vector_multi_source,
    "unpublish_inventory_zarr": inventory_zarr_item,
    "unpublish_delete_blob": delete_blob,
    "unpublish_drop_table": drop_postgis_table,
    "unpublish_delete_stac": delete_stac_and_audit,

    # VirtualiZarr handlers (NetCDF virtual reference pipeline)
    "virtualzarr_scan": virtualzarr_scan,
    "virtualzarr_copy": virtualzarr_copy,
    "virtualzarr_validate": virtualzarr_validate,
    "virtualzarr_combine": virtualzarr_combine,
    "virtualzarr_register": virtualzarr_register,

    # IngestZarr handlers (native Zarr store pipeline)
    "ingest_zarr_validate": ingest_zarr_validate,
    "ingest_zarr_copy": ingest_zarr_copy,
    "ingest_zarr_register": ingest_zarr_register,
    "ingest_zarr_rechunk": ingest_zarr_rechunk,

    # NetCDF-to-Zarr handlers (real conversion pipeline)
    "netcdf_scan": netcdf_scan,
    "netcdf_copy": netcdf_copy,
    "netcdf_validate": netcdf_validate,
    "netcdf_convert": netcdf_convert,
    "netcdf_convert_and_pyramid": netcdf_convert_and_pyramid,
    "netcdf_register": netcdf_register,

    # ACLED sync handlers (API-driven scheduled workflow)
    "acled_fetch_and_diff": acled_fetch_and_diff,
    "acled_save_to_bronze": acled_save_to_bronze,
    "acled_append_to_silver": acled_append_to_silver,

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
