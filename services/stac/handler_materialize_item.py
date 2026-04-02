# ============================================================================
# CLAUDE CONTEXT - STAC MATERIALIZE ITEM HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6 composable STAC)
# STATUS: Atomic handler - Generic STAC item materialization (DB → pgSTAC)
# PURPOSE: Read stac_item_json from cog_metadata, sanitize, inject TiTiler URLs,
#          upsert into pgSTAC. Used by ALL raster + zarr workflows.
# LAST_REVIEWED: 22 MAR 2026
# EXPORTS: stac_materialize_item
# DEPENDENCIES: services.stac_materialization.STACMaterializer,
#               infrastructure.raster_metadata_repository
# ============================================================================
"""
STAC Materialize Item — composable handler for DAG workflows.

Reads the cached stac_item_json from cog_metadata (source of truth),
applies B2C sanitization, injects TiTiler preview URLs, and upserts
into pgSTAC. Same handler for single COG, tiled COG, and zarr items.

pgSTAC is a materialized view — this handler is the write path.
"""

import copy
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def stac_materialize_item(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Materialize a single STAC item from cog_metadata into pgSTAC.

    Params:
        item_id (str, required): Primary key in cog_metadata or zarr_metadata table.
            Also accepted as cog_id for backward compatibility with raster workflows.
        collection_id (str, required): STAC collection to insert into
        blob_path (str, optional): Silver blob path for TiTiler URL injection

    Returns:
        {"success": True, "result": {item_id, collection_id, pgstac_id}}
    """
    dry_run = params.get("dry_run", False)
    if dry_run:
        logger.info("stac_materialize_item: [DRY-RUN] skipping materialization")
        return {
            "success": True,
            "result": {
                "item_id": "dry-run",
                "collection_id": params.get("collection_id", "dry-run"),
                "dry_run": True,
            },
        }

    item_id = params.get("item_id") or params.get("cog_id")
    collection_id = params.get("collection_id")
    blob_path = params.get("blob_path")

    if not item_id or not collection_id:
        missing = []
        if not item_id:
            missing.append("item_id or cog_id")
        if not collection_id:
            missing.append("collection_id")
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    try:
        from services.stac_materialization import STACMaterializer

        # Step 1: Read stac_item_json from metadata tables
        # Try cog_metadata first (raster), then zarr_metadata (zarr/netcdf)
        stac_item_json = None
        metadata_source = None

        cog_metadata = None  # Initialize to prevent NameError on zarr path

        try:
            from infrastructure.raster_metadata_repository import RasterMetadataRepository
            cog_repo = RasterMetadataRepository.instance()
            cog_metadata = cog_repo.get_by_id(item_id)
            if cog_metadata and cog_metadata.get("stac_item_json"):
                stac_item_json = cog_metadata["stac_item_json"]
                metadata_source = "cog_metadata"
                if not blob_path:
                    blob_path = cog_metadata.get("blob_path")
        except Exception as exc:
            logger.warning("cog_metadata lookup failed for %s: %s", item_id, exc)

        if stac_item_json is None:
            try:
                from infrastructure.zarr_metadata_repository import ZarrMetadataRepository
                zarr_repo = ZarrMetadataRepository()
                zarr_metadata = zarr_repo.get_by_id(item_id)
                if zarr_metadata and zarr_metadata.get("stac_item_json"):
                    stac_item_json = zarr_metadata["stac_item_json"]
                    metadata_source = "zarr_metadata"
            except Exception as exc:
                logger.warning("zarr_metadata lookup failed for %s: %s", item_id, exc)

        if stac_item_json is None:
            return {
                "success": False,
                "error": f"stac_item_json not found in cog_metadata or zarr_metadata for id: {item_id}",
                "error_type": "NotFoundError",
                "retryable": False,
            }

        # Resolve effective blob_path before materializing
        effective_blob_path = blob_path or (cog_metadata.get("blob_path") if cog_metadata else None)

        # Resolve zarr_prefix for xarray URL injection (C-3 fix)
        # When source is zarr_metadata, extract store_prefix so materialize_to_pgstac
        # can inject TiTiler xarray URLs (tilejson, viewer, variables endpoints).
        effective_zarr_prefix = None
        if metadata_source == "zarr_metadata" and zarr_metadata:
            effective_zarr_prefix = zarr_metadata.get("store_prefix")

        # Stamp item ID before passing to materializer
        stac_item_json = copy.deepcopy(stac_item_json)  # Deep copy to avoid mutating nested dicts
        stac_item_json["id"] = item_id

        # Materialize to pgSTAC via single write path
        materializer = STACMaterializer()
        result = materializer.materialize_to_pgstac(
            stac_item_json=stac_item_json,
            collection_id=collection_id,
            blob_path=effective_blob_path,
            zarr_prefix=effective_zarr_prefix,
        )

        if not result.get("success"):
            return {
                "success": False,
                "error": result.get("error", "Materialization failed"),
                "error_type": "MaterializationError",
                "retryable": True,
            }

        return {
            "success": True,
            "result": {
                "item_id": item_id,
                "collection_id": collection_id,
                "pgstac_id": result.get("pgstac_id"),
            },
        }

    except Exception as exc:
        import traceback
        logger.error("stac_materialize_item failed: %s\n%s", exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"STAC materialization failed for {item_id}: {exc}",
            "error_type": "MaterializationError",
            "retryable": True,
        }
