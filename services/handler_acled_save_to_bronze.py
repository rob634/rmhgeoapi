# ============================================================================
# CLAUDE CONTEXT - ACLED SAVE TO BRONZE HANDLER
# ============================================================================
# EPOCH: 5 - DAG ORCHESTRATION
# STATUS: Service - DAG task handler for Bronze audit copy
# PURPOSE: Save raw ACLED API responses to Bronze blob storage for audit/rebuild
# LAST_REVIEWED: 20 MAR 2026
# EXPORTS: acled_save_to_bronze
# DEPENDENCIES: infrastructure.blob (BlobRepository)
# ============================================================================

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BRONZE_CONTAINER = "acled"


def acled_save_to_bronze(
    params: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Save raw ACLED API page responses to Bronze blob storage for audit and rebuild.

    Receives `raw_responses` and `fetch_metadata` via DAG `receives:` mapping,
    serialises the list of raw page response dicts to JSON, and writes a single
    dated blob to the Bronze zone.

    Args:
        params: Task parameters injected by the DAG runner.  Expected keys:
            raw_responses  (list[list[dict]]): Raw API page payloads from fetch.
            fetch_metadata (dict):             Metadata from acled_fetch_and_diff,
                                               including `new_count`.
        context: Optional DAG execution context (unused).

    Returns:
        dict: Handler result envelope.
            On skip:    {"success": True, "result": {"skipped": True, "reason": str}}
            On success: {"success": True, "result": {"bronze_path": str,
                                                      "bytes_written": int,
                                                      "response_count": int}}
    """
    raw_responses = params.get("raw_responses", [])
    fetch_metadata = params.get("fetch_metadata", {})

    new_count = fetch_metadata.get("new_count", 0)

    if not raw_responses or new_count == 0:
        logger.info(
            "acled_save_to_bronze: no new data (raw_responses=%d, new_count=%d) — skipping.",
            len(raw_responses),
            new_count,
        )
        return {"success": True, "result": {"skipped": True, "reason": "no new data"}}

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    blob_path = f"acled/sync_{timestamp_str}.json"

    payload_bytes = json.dumps(raw_responses).encode("utf-8")
    bytes_written = len(payload_bytes)

    logger.info(
        "acled_save_to_bronze: writing %d bytes to bronze://%s/%s",
        bytes_written,
        BRONZE_CONTAINER,
        blob_path,
    )

    from infrastructure.blob import BlobRepository

    bronze_repo = BlobRepository.for_zone("bronze")
    bronze_repo.write_blob(
        container=BRONZE_CONTAINER,
        blob_path=blob_path,
        data=payload_bytes,
        overwrite=True,
        content_type="application/json",
    )

    logger.info(
        "acled_save_to_bronze: wrote %d bytes (%d page responses) → %s",
        bytes_written,
        len(raw_responses),
        blob_path,
    )

    return {
        "success": True,
        "result": {
            "bronze_path": blob_path,
            "bytes_written": bytes_written,
            "response_count": len(raw_responses),
        },
    }
