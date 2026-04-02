# ============================================================================
# CLAUDE CONTEXT - RASTER COLLECTION ENTRYPOINT HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.10 raster collection)
# STATUS: Atomic handler - Pass-through blob_list for fan-out source resolution
# PURPOSE: The DAG fan-out engine resolves source lists from predecessor outputs,
#          not from workflow inputs (job_params). This handler receives blob_list
#          as a parameter and returns it as a result, making it available as a
#          fan-out source via "prepare_collection.result.blob_list".
# CREATED: 01 APR 2026
# EXPORTS: raster_collection_entrypoint
# DEPENDENCIES: None (pure pass-through, no I/O)
# ============================================================================
"""
Raster Collection Entrypoint -- pass-through handler for DAG workflows.

The DAG fan-out engine's ``expand_fan_outs`` resolves the ``source`` field
exclusively from ``predecessor_outputs`` via ``resolve_dotted_path``.  Workflow
``inputs`` (job_params) are NOT available as fan-out sources.

This handler bridges that gap: it receives ``blob_list`` from job_params
(via the YAML ``params`` list) and returns it in its result dict, making
it accessible to the first fan-out node as:

    source: "prepare_collection.result.blob_list"
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def raster_collection_entrypoint(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Pass-through handler: echo blob_list and collection_id into result.

    Params:
        blob_list (list[str], required): List of blob paths to process.
        collection_id (str, required): STAC collection identifier.

    Returns:
        {
            "success": True,
            "result": {
                "blob_list": [...],
                "collection_id": "...",
                "file_count": N
            }
        }
    """
    blob_list = params.get("blob_list")
    if not blob_list or not isinstance(blob_list, list):
        return {
            "success": False,
            "error": "blob_list is required and must be a non-empty list",
            "error_type": "ValidationError",
            "retryable": False,
        }

    collection_id = params.get("collection_id")
    if not collection_id:
        return {
            "success": False,
            "error": "collection_id is required",
            "error_type": "ValidationError",
            "retryable": False,
        }

    logger.info(
        "raster_collection_entrypoint: %d blobs for collection '%s'",
        len(blob_list), collection_id,
    )

    return {
        "success": True,
        "result": {
            "blob_list": blob_list,
            "collection_id": collection_id,
            "file_count": len(blob_list),
        },
    }
