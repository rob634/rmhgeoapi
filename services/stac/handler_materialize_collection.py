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
            logger.info(
                "stac_materialize_collection: %s — bbox=%s, items=%s",
                collection_id,
                result.get("bbox"),
                result.get("item_count"),
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
