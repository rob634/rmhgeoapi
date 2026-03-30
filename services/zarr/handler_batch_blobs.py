# ============================================================================
# CLAUDE CONTEXT - ZARR BATCH BLOBS HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.10.6)
# STATUS: Atomic handler - Batch a blob list into fan-out-friendly chunks
# PURPOSE: Takes a flat blob_list from zarr validate and splits into batches
#          of ~500MB each. The fan-out then creates one task per batch.
# LAST_REVIEWED: 23 MAR 2026
# EXPORTS: zarr_batch_blobs
# DEPENDENCIES: none
# ============================================================================
"""
Zarr Batch Blobs — split blob_list into fan-out batches.

For Zarr stores with 50,000+ chunk blobs, creating one task per blob
would flood the workflow_tasks table. Instead, this handler groups
blobs into batches (default 2000 blobs per batch) for the copy fan-out.
"""

from typing import Any, Dict, Optional

from util_logger import LoggerFactory, ComponentType

logger = LoggerFactory.create_logger(ComponentType.SERVICE, "handler_batch_blobs")

DEFAULT_BATCH_SIZE = 2000  # ~500MB per batch assuming ~250KB per chunk


def zarr_batch_blobs(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Split a blob_list into batches for fan-out copy.

    Params:
        blob_list (list[str], required): Full list of blob names from validate
        batch_size (int, optional): Blobs per batch (default 2000)

    Returns:
        {"success": True, "result": {batches: [[blob1, blob2, ...], ...], batch_count, total_blobs}}
    """
    blob_list = params.get("blob_list", [])
    batch_size = params.get("batch_size", DEFAULT_BATCH_SIZE)

    if not blob_list:
        return {
            "success": True,
            "result": {
                "batches": [],
                "batch_count": 0,
                "total_blobs": 0,
            },
        }

    # Split into batches
    batches = [
        blob_list[i:i + batch_size]
        for i in range(0, len(blob_list), batch_size)
    ]

    logger.info(
        "zarr_batch_blobs: %d blobs → %d batches (batch_size=%d)",
        len(blob_list), len(batches), batch_size,
    )

    return {
        "success": True,
        "result": {
            "batches": batches,
            "batch_count": len(batches),
            "total_blobs": len(blob_list),
        },
    }
