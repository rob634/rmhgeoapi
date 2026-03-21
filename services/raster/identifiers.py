# ============================================================================
# CLAUDE CONTEXT - RASTER IDENTIFIER UTILITIES
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.5)
# STATUS: Shared utility - Deterministic ID generation for raster assets
# PURPOSE: Single source of truth for stac_item_id derivation, used by
#          raster_upload_cog and raster_persist_app_tables handlers
# LAST_REVIEWED: 21 MAR 2026
# EXPORTS: derive_stac_item_id
# DEPENDENCIES: none
# ============================================================================
"""
Raster identifier utilities.

Deterministic ID generation for COG assets. The stac_item_id is the primary
key linking cog_metadata, raster_render_configs, and pgSTAC items.

Must produce identical results in both raster_upload_cog (where the ID is
first generated) and raster_persist_app_tables (where it is used as PK).
"""


def derive_stac_item_id(collection_id: str, blob_path: str) -> str:
    """
    Generate a deterministic STAC item ID from collection and blob path.

    Matches the monolith's derivation at handler_process_raster_complete.py L1850-1851:
        safe_name = cog_blob.replace('/', '-').replace('.', '-')
        stac_item_id = f"{collection_id}-{safe_name}"

    Args:
        collection_id: STAC collection ID (e.g., "fathom-flood")
        blob_path: Silver blob path (e.g., "cogs/fathom-flood/dem_analysis.tif")

    Returns:
        Deterministic stac_item_id string
    """
    safe_name = blob_path.replace('/', '-').replace('.', '-')
    return f"{collection_id}-{safe_name}"
