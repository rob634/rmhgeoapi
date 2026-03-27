# ============================================================================
# CLAUDE CONTEXT - STAC MATERIALIZE COLLECTION HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6 composable STAC)
# STATUS: Atomic handler - Recalculate collection extent from pgSTAC items
# PURPOSE: Compute union bbox + temporal extent from all items in a collection,
#          upsert the collection into pgSTAC. Used after item materialization.
# LAST_REVIEWED: 22 MAR 2026
# EXPORTS: stac_materialize_collection
# DEPENDENCIES: services.stac_materialization.STACMaterializer
# ============================================================================
"""
STAC Materialize Collection — composable handler for DAG workflows.

After items are materialized into pgSTAC, this handler recalculates
the collection's spatial and temporal extent from all its items and
upserts the collection record. TiTiler needs a valid collection to
serve mosaic tiles via /stac/tilejson.json?collection=X.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def stac_materialize_collection(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Recalculate and upsert a STAC collection from its pgSTAC items.

    Params:
        collection_id (str, required): STAC collection ID

    Returns:
        {"success": True, "result": {collection_id, bbox, item_count}}
    """
    dry_run = params.get("dry_run", False)
    if dry_run:
        logger.info("stac_materialize_collection: [DRY-RUN] skipping materialization")
        return {
            "success": True,
            "result": {
                "collection_id": params.get("collection_id", "dry-run"),
                "dry_run": True,
            },
        }

    collection_id = params.get("collection_id")

    if not collection_id:
        return {
            "success": False,
            "error": "collection_id is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    try:
        from services.stac_materialization import STACMaterializer

        materializer = STACMaterializer()
        result = materializer.materialize_collection(collection_id)

        if result.get("success"):
            bbox = result.get("bbox")
            item_count = result.get("item_count", 0)
            logger.info(
                "stac_materialize_collection: %s — bbox=%s, items=%s",
                collection_id,
                bbox,
                item_count,
            )

            # Register pgSTAC search for tiled collections (mosaic TiTiler preview)
            # Only register when collection has multiple items — single COG uses direct item URL
            if item_count and item_count > 1:
                try:
                    from services.pgstac_search_registration import PgSTACSearchRegistration
                    registrar = PgSTACSearchRegistration()
                    search_id = registrar.register_collection_search(
                        collection_id=collection_id,
                        bbox=bbox,
                    )
                    logger.info(
                        "Registered pgSTAC search for tiled collection %s: %s",
                        collection_id,
                        search_id,
                    )
                    result["search_id"] = search_id
                except Exception as reg_exc:
                    logger.warning(
                        "pgSTAC search registration failed (non-fatal): %s", reg_exc
                    )

            return {"success": True, "result": result}
        else:
            return {
                "success": False,
                "error": result.get("error", "Collection materialization failed"),
                "error_type": "MaterializationError",
                "retryable": True,
            }

    except Exception as exc:
        import traceback
        logger.error("stac_materialize_collection failed: %s\n%s", exc, traceback.format_exc())
        return {
            "success": False,
            "error": f"Collection materialization failed for {collection_id}: {exc}",
            "error_type": "MaterializationError",
            "retryable": True,
        }
