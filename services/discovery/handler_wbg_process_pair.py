# ============================================================================
# CLAUDE CONTEXT - WBG PROCESS SINGLE PAIR HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION (v0.11.0 discovery automation)
# STATUS: Composite handler - Copy ZIP to bronze, unzip, classify, upload rasters
# PURPOSE: For a single WBG JSON+ZIP pair: copy from cold to bronze, extract,
#          classify contents, upload extracted rasters back to bronze.
# CREATED: 03 APR 2026
# EXPORTS: wbg_process_single_pair
# DEPENDENCIES: infrastructure.blob, infrastructure.etl_mount,
#               services.discovery.handler_classify_raster_contents,
#               services.discovery.handler_unzip_to_mount
# ============================================================================
"""
WBG Process Single Pair -- composite handler for one JSON+ZIP pair.

Orchestrates: copy to bronze → unzip to mount → classify → upload rasters to bronze.
Returns classification result with bronze blob paths for downstream workflow submission.
"""

import logging
import os
from pathlib import PurePosixPath
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def wbg_process_single_pair(
    params: Dict[str, Any], context: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Process a single WBG JSON+ZIP pair.

    Params:
        zip_blob (str, required): ZIP blob path in source container.
        json_blob (str, required): JSON sidecar blob path.
        metadata (dict, optional): Pre-read JSON sidecar metadata.
        container_name (str, required): Target bronze container.
        source_container (str, required): Source container (cold).
        _run_id (str, system-injected): DAG run ID.

    Returns:
        Success: {"success": True, "result": {"stem": "...", "classification": "...", ...}}
    """
    zip_blob = params.get("zip_blob")
    json_blob = params.get("json_blob")
    metadata = params.get("metadata")
    container_name = params.get("container_name")
    source_container = params.get("source_container")
    run_id = params.get("_run_id", "unknown")

    if not zip_blob:
        return {"success": False, "error": "zip_blob is required",
                "error_type": "ValidationError", "retryable": False}
    if not container_name:
        return {"success": False, "error": "container_name is required",
                "error_type": "ValidationError", "retryable": False}
    if not source_container:
        return {"success": False, "error": "source_container is required",
                "error_type": "ValidationError", "retryable": False}

    stem = PurePosixPath(zip_blob).stem
    bronze_prefix = f"wbg_extracted/{stem}"

    from infrastructure.blob import BlobRepository
    blob_repo = BlobRepository.for_zone("bronze")

    # Step 1: Copy ZIP from cold to bronze (server-side, no client transfer)
    bronze_zip_path = f"{bronze_prefix}/{stem}.zip"
    try:
        blob_repo.copy_blob(source_container, zip_blob, container_name, bronze_zip_path)
        logger.info("wbg_process_pair: copied %s -> %s/%s", zip_blob, container_name, bronze_zip_path)
    except Exception as exc:
        return {"success": False, "error": f"Failed to copy ZIP to bronze: {exc}",
                "error_type": "CopyError", "retryable": True}

    # Step 2: Unzip to mount
    from services.discovery.handler_unzip_to_mount import unzip_to_mount

    unzip_result = unzip_to_mount({
        "container_name": container_name,
        "blob_name": bronze_zip_path,
        "_run_id": run_id,
    })

    if not unzip_result.get("success"):
        return unzip_result  # Pass through the failure

    extract_result = unzip_result["result"]
    extract_path = extract_result["extract_path"]
    contents = extract_result["contents"]

    # Step 3: Classify contents
    from services.discovery.handler_classify_raster_contents import classify_raster_contents

    classify_result = classify_raster_contents({
        "contents": contents,
        "extract_path": extract_path,
        "metadata_json": metadata,
    })

    if not classify_result.get("success"):
        return classify_result

    classification = classify_result["result"]
    raster_files = classification.get("raster_files", [])

    # Step 4: Upload extracted rasters to bronze
    bronze_raster_paths = []
    for rel_path in raster_files:
        local_path = os.path.join(extract_path, rel_path)
        bronze_blob_path = f"{bronze_prefix}/{rel_path}"

        if not os.path.exists(local_path):
            logger.warning("wbg_process_pair: raster file not found on mount: %s", local_path)
            continue

        try:
            blob_repo.upload_file_to_blob(container_name, bronze_blob_path, local_path)
            bronze_raster_paths.append(bronze_blob_path)
            logger.info("wbg_process_pair: uploaded %s -> %s/%s",
                        rel_path, container_name, bronze_blob_path)
        except Exception as exc:
            logger.warning("wbg_process_pair: failed to upload %s: %s", rel_path, exc)

    # Build recommended_params with bronze paths
    recommended_params = classification.get("recommended_params", {})
    workflow = classification.get("recommended_workflow")

    if workflow == "process_raster" and bronze_raster_paths:
        recommended_params["blob_name"] = bronze_raster_paths[0]
        recommended_params["container_name"] = container_name
    elif workflow == "process_raster_collection" and bronze_raster_paths:
        recommended_params["blob_list"] = bronze_raster_paths
        recommended_params["container_name"] = container_name
        recommended_params["collection_id"] = stem

    logger.info(
        "wbg_process_pair: %s — %s (%d rasters -> bronze)",
        stem, classification.get("classification"), len(bronze_raster_paths),
    )

    return {
        "success": True,
        "result": {
            "stem": stem,
            "source_blob": zip_blob,
            "classification": classification.get("classification"),
            "evidence": classification.get("evidence", {}),
            "bronze_raster_paths": bronze_raster_paths,
            "metadata": metadata,
            "recommended_workflow": workflow,
            "recommended_params": recommended_params,
        },
    }
