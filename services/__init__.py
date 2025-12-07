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

"""

from .service_hello_world import handle_greeting, handle_reply
from .container_summary import analyze_container_summary
# Old container_list handlers - ARCHIVED (07 DEC 2025)
# list_container_blobs: replaced by list_blobs_with_metadata
# analyze_single_blob: replaced by analyze_blob_basic
# aggregate_blob_analysis: replaced by container_inventory.aggregate_blob_analysis
# from .container_list import list_container_blobs, analyze_single_blob, aggregate_blob_analysis
from .stac_catalog import list_raster_files, extract_stac_metadata
from .stac_vector_catalog import extract_vector_stac_metadata, create_vector_stac
# test_minimal removed (30 NOV 2025) - file doesn't exist
from .raster_validation import validate_raster
from .raster_cog import create_cog
from .handler_h3_level4 import h3_level4_generate
from .handler_h3_base import h3_base_generate
from .handler_insert_h3_postgis import insert_h3_to_postgis
from .handler_create_h3_stac import create_h3_stac
from .handler_h3_native_streaming import h3_native_streaming_postgis
from .handler_generate_h3_grid import generate_h3_grid  # Universal H3 handler (14 NOV 2025) - replaces bootstrap_res2
from .handler_cascade_h3_descendants import cascade_h3_descendants  # Multi-level cascade handler (15 NOV 2025) - res N → res N+1,N+2,etc
from .handler_finalize_h3_pyramid import finalize_h3_pyramid  # H3 pyramid finalization (14 NOV 2025)
# Old ingest_vector handlers REMOVED (27 NOV 2025) - process_vector uses new idempotent handlers
# from .vector.tasks import prepare_vector_chunks, upload_pickled_chunk
from .vector.process_vector_tasks import process_vector_prepare, process_vector_upload  # Idempotent (26 NOV 2025)
from .raster_mosaicjson import create_mosaicjson
from .stac_collection import create_stac_collection
from .tiling_scheme import generate_tiling_scheme
from .tiling_extraction import extract_tiles
from .fathom_etl import (
    # Phase 1: Band stacking (03 DEC 2025)
    fathom_tile_inventory,
    fathom_band_stack,
    # Phase 2: Spatial merge (03 DEC 2025)
    fathom_grid_inventory,
    fathom_spatial_merge,
    # Shared
    fathom_stac_register,
    # Legacy handlers ARCHIVED (05 DEC 2025) → docs/archive/jobs/fathom_legacy_dec2025/
)
from .geospatial_inventory import (
    classify_geospatial_file,
    aggregate_geospatial_inventory,
)
from .container_inventory import (
    list_blobs_with_metadata,
    analyze_blob_basic,
    aggregate_blob_analysis as aggregate_blob_analysis_v2,  # New consolidated handler
)
from .fathom_container_inventory import (
    fathom_generate_scan_prefixes,
    fathom_scan_prefix,
    fathom_assign_grid_cells,
    fathom_inventory_summary,
)

# ============================================================================
# STAC METADATA HELPER (25 NOV 2025)
# ============================================================================
# Centralized STAC metadata enrichment - platform, app, geographic, visualization
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
    "hello_world_greeting": handle_greeting,
    "hello_world_reply": handle_reply,
    "container_summary_task": analyze_container_summary,
    # Old container_list handlers ARCHIVED (07 DEC 2025) - see Container Inventory handlers below
    # "list_container_blobs": list_container_blobs,
    # "analyze_single_blob": analyze_single_blob,
    "list_raster_files": list_raster_files,
    "extract_stac_metadata": extract_stac_metadata,
    "extract_vector_stac_metadata": extract_vector_stac_metadata,
    # "test_minimal" removed (30 NOV 2025) - file doesn't exist
    "validate_raster": validate_raster,
    "create_cog": create_cog,
    "h3_level4_generate": h3_level4_generate,
    "h3_base_generate": h3_base_generate,
    # H3 PostGIS + STAC handlers (9 NOV 2025 - Phase 2)
    "insert_h3_to_postgis": insert_h3_to_postgis,  # Stage 2: Load GeoParquet → PostGIS (DEPRECATED - use h3_native_streaming_postgis)
    "create_h3_stac": create_h3_stac,              # Stage 3: Create STAC item for H3 grid
    # H3 Native Streaming Handler (9 NOV 2025 - Phase 3)
    "h3_native_streaming_postgis": h3_native_streaming_postgis,  # Stage 1: h3-py → async stream → PostGIS (3.5x faster)
    # H3 Universal Handlers (14-15 NOV 2025 - DRY Architecture)
    "generate_h3_grid": generate_h3_grid,  # Universal handler for ALL resolutions (0-15), base OR cascade, flexible filtering (replaces bootstrap_res2)
    "cascade_h3_descendants": cascade_h3_descendants,  # Multi-level cascade handler (15 NOV 2025) - res N → [N+1, N+2, ..., N+K] in one operation
    "finalize_h3_pyramid": finalize_h3_pyramid,  # H3 pyramid finalization and verification (14 NOV 2025)
    # Vector ETL handlers - OLD ingest_vector handlers REMOVED (27 NOV 2025)
    # "prepare_vector_chunks" and "upload_pickled_chunk" removed - use process_vector idempotent handlers
    "create_vector_stac": create_vector_stac,        # Stage 3: Create STAC record (shared by process_vector)
    # Raster collection handlers (20 OCT 2025)
    "create_mosaicjson": create_mosaicjson,          # Stage 3: Create MosaicJSON from COG collection
    "create_stac_collection": create_stac_collection,  # Stage 4: Create STAC collection item
    # Big Raster ETL handlers (24 OCT 2025)
    "generate_tiling_scheme": generate_tiling_scheme,  # Stage 1: Generate tiling scheme in EPSG:4326
    "extract_tiles": extract_tiles,                   # Stage 2: Extract tiles sequentially
    # Fathom ETL handlers - Two-Phase Architecture (03 DEC 2025)
    # Phase 1: Band stacking (~500MB/task, 16+ concurrent)
    "fathom_tile_inventory": fathom_tile_inventory,   # Stage 1: Group by tile + scenario
    "fathom_band_stack": fathom_band_stack,           # Stage 2: Stack 8 RPs into multi-band COG
    # Phase 2: Spatial merge (~2-3GB/task, 4-5 concurrent)
    "fathom_grid_inventory": fathom_grid_inventory,   # Stage 1: Group by NxN grid cell
    "fathom_spatial_merge": fathom_spatial_merge,     # Stage 2: Merge tiles band-by-band
    # Shared handler (both phases)
    "fathom_stac_register": fathom_stac_register,     # Stage 3: STAC collection/items
    # Legacy handlers ARCHIVED (05 DEC 2025) → docs/archive/jobs/fathom_legacy_dec2025/
    # Idempotent Vector ETL handlers (26 NOV 2025)
    "process_vector_prepare": process_vector_prepare,  # Stage 1: Load, validate, chunk, create table
    "process_vector_upload": process_vector_upload,    # Stage 2: DELETE+INSERT idempotent upload
    # Note: create_vector_stac already registered above - reused for Stage 3
    # Container Inventory handlers - consolidated (07 DEC 2025)
    # Base handlers (analysis_mode="basic")
    "list_blobs_with_metadata": list_blobs_with_metadata,  # Stage 1: List blobs with full metadata
    "analyze_blob_basic": analyze_blob_basic,  # Stage 2: Basic per-blob analysis
    "aggregate_blob_analysis": aggregate_blob_analysis_v2,  # Stage 3: Aggregate basic analysis (replaces old handler)
    # Geospatial handlers (analysis_mode="geospatial")
    "classify_geospatial_file": classify_geospatial_file,  # Stage 2: Per-blob geospatial classification
    "aggregate_geospatial_inventory": aggregate_geospatial_inventory,  # Stage 3: Group into collections
    # Fathom Container Inventory handlers (05 DEC 2025)
    "fathom_generate_scan_prefixes": fathom_generate_scan_prefixes,  # Stage 1: Generate prefix list
    "fathom_scan_prefix": fathom_scan_prefix,  # Stage 2: Parallel scan + batch insert
    "fathom_assign_grid_cells": fathom_assign_grid_cells,  # Stage 3: Calculate grid assignments
    "fathom_inventory_summary": fathom_inventory_summary,  # Stage 4: Generate statistics
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


# Validate on import - fail fast if something's wrong.
validate_handler_registry()

__all__ = [
    # Handler registry
    'ALL_HANDLERS',
    'get_handler',
    'validate_handler_registry',
    # STAC Metadata Helper (25 NOV 2025)
    'STACMetadataHelper',
    'PlatformMetadata',
    'AppMetadata',
    'VisualizationMetadata',
    'ISO3Attribution',
    'ISO3AttributionService',
]
