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

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def stac_materialize_item(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Materialize a single STAC item from cog_metadata into pgSTAC.

    Params:
        cog_id (str, required): Primary key in cog_metadata table
        collection_id (str, required): STAC collection to insert into
        blob_path (str, optional): Silver blob path for TiTiler URL injection

    Returns:
        {"success": True, "result": {item_id, collection_id, pgstac_id}}
    """
    cog_id = params.get("cog_id")
    collection_id = params.get("collection_id")
    blob_path = params.get("blob_path")

    if not cog_id or not collection_id:
        missing = []
        if not cog_id:
            missing.append("cog_id")
        if not collection_id:
            missing.append("collection_id")
        return {
            "success": False,
            "error": f"Missing required parameters: {', '.join(missing)}",
            "error_type": "ValidationError",
            "retryable": False,
        }

    try:
        from infrastructure.raster_metadata_repository import RasterMetadataRepository
        from infrastructure.pgstac_repository import PgStacRepository
        from services.stac_materialization import STACMaterializer

        # Step 1: Read stac_item_json from cog_metadata
        cog_repo = RasterMetadataRepository.instance()
        cog_metadata = cog_repo.get_by_id(cog_id)

        if cog_metadata is None:
            return {
                "success": False,
                "error": f"cog_metadata not found for cog_id: {cog_id}",
                "error_type": "NotFoundError",
                "retryable": False,
            }

        stac_item_json = cog_metadata.get("stac_item_json")
        if stac_item_json is None:
            return {
                "success": False,
                "error": f"stac_item_json is null in cog_metadata for cog_id: {cog_id}",
                "error_type": "DataError",
                "retryable": False,
            }

        # Step 2: Ensure item ID and collection are set
        stac_item_json = dict(stac_item_json)  # Copy to avoid mutation
        stac_item_json["id"] = cog_id
        stac_item_json["collection"] = collection_id

        # Step 3: B2C sanitization (strip geoetl:* internal properties)
        materializer = STACMaterializer()
        materializer.sanitize_item_properties(stac_item_json)

        # Step 4: Inject TiTiler visualization URLs
        effective_blob_path = blob_path or cog_metadata.get("blob_path")
        if effective_blob_path:
            materializer._inject_titiler_urls(stac_item_json, effective_blob_path)

        # Step 5: Ensure collection exists before inserting item
        pgstac = PgStacRepository()
        existing_collection = pgstac.get_collection(collection_id)
        if not existing_collection:
            from services.stac_collection import build_raster_stac_collection
            bbox = stac_item_json.get("bbox", [-180, -90, 180, 90])
            collection_dict = build_raster_stac_collection(
                collection_id=collection_id,
                bbox=bbox,
            )
            pgstac.insert_collection(collection_dict)
            logger.info("stac_materialize_item: created collection %s", collection_id)

        # Step 6: Upsert item into pgSTAC
        pgstac_id = pgstac.insert_item(stac_item_json, collection_id)

        logger.info(
            "stac_materialize_item: %s → pgSTAC collection %s",
            cog_id, collection_id,
        )

        return {
            "success": True,
            "result": {
                "item_id": cog_id,
                "collection_id": collection_id,
                "pgstac_id": pgstac_id,
            },
        }

    except Exception as exc:
        import traceback
        logger.error("stac_materialize_item failed: %s\n%s", exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"STAC materialization failed for {cog_id}: {exc}",
            "error_type": "MaterializationError",
            "retryable": True,
        }
